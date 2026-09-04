"""Incremental planning graph for the 500-chapter Qwen planner.

This graph is deliberately small: it stores the accepted hierarchy and the
state/outcome of each completed batch, then returns only the immediate context
needed by the next event batch.  Generation remains resumable when Neo4j is
temporarily unavailable.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import re
from typing import Any

from .common import get_neo4j_driver


def _text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _character_id(name: str) -> str:
    normalized = re.sub(r"\s+", "", name).casefold()
    # Keep this byte-for-byte compatible with pop_king_plan_compiler so the
    # planning graph, event cards and body memory all address one identity.
    return "CHAR_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12].upper()


def planning_graph_enabled() -> bool:
    if not all(os.getenv(name) for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")):
        return False
    uri = str(os.getenv("NEO4J_URI") or "")
    match = re.match(r"^(?:neo4j|bolt)(?:\+s|\+ssc)?://([^/:]+)(?::(\d+))?", uri)
    if not match:
        return False
    host, port = match.group(1), int(match.group(2) or 7687)
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def planning_story_id(global_outline: dict[str, Any]) -> str:
    # The graph scope is the exact accepted outline, not merely its title and
    # version label.  Any causal spine, phase, cast or foreshadow edit therefore
    # creates a new isolated planning graph instead of silently reusing stale
    # PlotCluster/StoryChapter nodes.
    identity = json.dumps(
        global_outline, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "planning-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def sync_planning_hierarchy(
    global_outline: dict[str, Any],
    blocks: list[dict[str, Any]],
    macros: list[dict[str, Any]],
) -> str | None:
    if not planning_graph_enabled():
        return None
    sid = planning_story_id(global_outline)
    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            session.run(
                """
                MERGE (s:StoryPlan {id:$sid})
                SET s.story_id=$sid, s.title=$title, s.premise=$premise,
                    s.full_story_synopsis=$synopsis,
                    s.outline_sha256=$outline_sha256,
                    s.planning_version=$planning_version,
                    s.updatedAt=timestamp()
                """,
                sid=sid,
                title=str(global_outline.get("story_title") or ""),
                premise=str(global_outline.get("one_sentence_premise") or ""),
                synopsis=str(global_outline.get("full_story_synopsis") or ""),
                outline_sha256=_canonical_sha256(global_outline),
                planning_version=str(global_outline.get("planning_version") or ""),
            )
            for phase in global_outline.get("life_phases") or []:
                if not isinstance(phase, dict):
                    continue
                pid = str(phase.get("phase_id") or "")
                span = phase.get("chapter_span") or [0, 0]
                session.run(
                    """
                    MATCH (s:StoryPlan {id:$sid})
                    MERGE (p:LifePhase {id:$id})
                    SET p.story_id=$sid, p.phase_id=$pid, p.start_chapter=$start,
                        p.end_chapter=$end, p.timeline_years=$years, p.goal=$goal,
                        p.outcome=$outcome, p.handoff=$handoff, p.updatedAt=timestamp()
                    MERGE (s)-[:CONTAINS_PHASE]->(p)
                    """,
                    sid=sid, id=f"lifephase:{sid}:{pid}", pid=pid,
                    start=int(span[0]), end=int(span[1]),
                    years=str(phase.get("timeline_years") or ""),
                    goal=str(phase.get("broad_story_goal") or ""),
                    outcome=str(phase.get("phase_outcome") or ""),
                    handoff=str(phase.get("handoff_to_next_phase") or ""),
                )
            for arc in global_outline.get("character_long_arcs") or []:
                if not isinstance(arc, dict):
                    continue
                name = str(arc.get("character") or "").strip()
                pid = str(arc.get("first_active_phase") or "")
                if not name:
                    continue
                stable_character_id = str(arc.get("character_id") or _character_id(name))
                aliases = arc.get("aliases") or list(dict.fromkeys([name, name.split("·", 1)[0]]))
                session.run(
                    """
                    MERGE (c:Character {id:$id})
                    SET c.story_id=$sid, c.character_id=$character_id,
                        c.name=$name, c.label=$name, c.aliases_json=$aliases,
                        c.first_active_phase=$pid, c.planning_arc_json=$arc,
                        c.updatedAt=timestamp()
                    WITH c
                    OPTIONAL MATCH (p:LifePhase {id:$phase_id})
                    FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END |
                        MERGE (c)-[:FIRST_ACTIVE_IN]->(p))
                    """,
                    id=f"planningchar:{sid}:{stable_character_id}",
                    character_id=stable_character_id, sid=sid, name=name, pid=pid,
                    aliases=_text(aliases), arc=_text(arc), phase_id=f"lifephase:{sid}:{pid}",
                )
            for block in blocks:
                bid = str(block.get("block_id") or "")
                span = block.get("chapter_span") or [0, 0]
                phase_number = (int(span[0]) - 1) // 50 + 1
                pid = f"P{phase_number:02d}"
                session.run(
                    """
                    MATCH (s:StoryPlan {id:$sid})
                    MERGE (b:StoryBlock {id:$id})
                    SET b.story_id=$sid, b.block_id=$bid, b.start_chapter=$start,
                        b.end_chapter=$end, b.title=$title, b.summary=$summary,
                        b.goal=$goal, b.outcome=$outcome, b.handoff=$handoff,
                        b.entry_state_json=$entry_state,
                        b.character_movements_json=$character_movements,
                        b.state_changes_json=$state_changes,
                        b.causal_links_json=$causal_links,
                        b.foreshadows_json=$foreshadows,
                        b.continuity_json=$continuity, b.plan_json=$plan,
                        b.plan_sha256=$plan_sha256,
                        b.updatedAt=timestamp()
                    MERGE (s)-[:CONTAINS_BLOCK]->(b)
                    WITH b
                    OPTIONAL MATCH (p:LifePhase {id:$phase_id})
                    FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END |
                        MERGE (p)-[:CONTAINS_BLOCK]->(b))
                    """,
                    sid=sid, id=f"storyblock:{sid}:{bid}", bid=bid,
                    start=int(span[0]), end=int(span[1]),
                    title=str(block.get("block_title") or ""),
                    summary=str(block.get("coarse_story_summary") or ""),
                    goal=str(block.get("block_goal") or ""),
                    outcome=str(block.get("block_outcome") or ""),
                    handoff=str(block.get("handoff_to_next_block") or ""),
                    entry_state=_text(block.get("entry_state") or {}),
                    character_movements=_text(block.get("character_movements") or []),
                    state_changes=_text(block.get("state_changes") or {}),
                    causal_links=_text(block.get("causal_links") or []),
                    foreshadows=_text(block.get("foreshadows") or []),
                    continuity=_text(block.get("continuity_update") or {}),
                    plan=_text(block),
                    plan_sha256=_canonical_sha256(block),
                    phase_id=f"lifephase:{sid}:{pid}",
                )
            for macro in macros:
                mid = str(macro.get("macro_group_id") or "")
                bid = str(macro.get("story_block_id") or "")
                span = macro.get("chapter_span") or [0, 0]
                session.run(
                    """
                    MATCH (b:StoryBlock {id:$block_id})
                    MERGE (m:MacroGroup {id:$id})
                    SET m.story_id=$sid, m.macro_group_id=$mid,
                        m.start_chapter=$start, m.end_chapter=$end,
                        m.title=$title, m.goal=$goal, m.ending_state=$ending,
                        m.next_hook=$hook, m.plan_sha256=$plan_sha256,
                        m.updatedAt=timestamp()
                    MERGE (b)-[:CONTAINS_MACRO]->(m)
                    """,
                    sid=sid, block_id=f"storyblock:{sid}:{bid}",
                    id=f"macrogroup:{sid}:{mid}", mid=mid,
                    start=int(span[0]), end=int(span[1]),
                    title=str(macro.get("title") or ""),
                    goal=str(macro.get("macro_goal") or ""),
                    ending=str(macro.get("ending_state") or ""),
                    hook=str(macro.get("next_group_hook") or ""),
                    plan_sha256=_canonical_sha256(macro),
                )
            for label, prefix, items in (
                ("StoryBlock", "storyblock", blocks),
                ("MacroGroup", "macrogroup", macros),
            ):
                key = "block_id" if label == "StoryBlock" else "macro_group_id"
                ids = [str(item.get(key) or "") for item in items]
                for left, right in zip(ids, ids[1:]):
                    session.run(
                        f"MATCH (a:{label} {{id:$a}}), (b:{label} {{id:$b}}) MERGE (a)-[:PLANNED_BEFORE]->(b)",
                        a=f"{prefix}:{sid}:{left}", b=f"{prefix}:{sid}:{right}",
                    )
    finally:
        driver.close()
    return sid


def verify_planning_hierarchy(
    global_outline: dict[str, Any],
    blocks: list[dict[str, Any]],
    macros: list[dict[str, Any]],
) -> dict[str, Any]:
    """Require the exact outline scope and every upstream ID in Neo4j."""
    if not planning_graph_enabled():
        raise RuntimeError("Neo4j planning graph is not reachable or credentials are missing")
    sid = planning_story_id(global_outline)
    expected_blocks = {str(item.get("block_id") or "") for item in blocks}
    expected_macros = {str(item.get("macro_group_id") or "") for item in macros}
    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            row = session.run(
                """
                OPTIONAL MATCH (s:StoryPlan {id:$sid})
                OPTIONAL MATCH (b:StoryBlock {story_id:$sid})
                WITH count(DISTINCT s) AS plans, collect(DISTINCT b.block_id) AS blocks
                OPTIONAL MATCH (m:MacroGroup {story_id:$sid})
                RETURN plans, blocks,
                       collect(DISTINCT {id:m.macro_group_id, sha:m.plan_sha256}) AS macros
                """,
                sid=sid,
            ).single()
            if not row or int(row["plans"] or 0) != 1:
                raise RuntimeError(f"Neo4j missing exact StoryPlan {sid}")
            actual_blocks = {str(x) for x in (row["blocks"] or []) if x}
            actual_macro_rows = [dict(x) for x in (row["macros"] or []) if x and x.get("id")]
            actual_macros = {str(x.get("id")) for x in actual_macro_rows}
            expected_block_hashes = {
                str(item.get("block_id") or ""): _canonical_sha256(item) for item in blocks
            }
            expected_macro_hashes = {
                str(item.get("macro_group_id") or ""): _canonical_sha256(item) for item in macros
            }
            block_hash_rows = list(session.run(
                "MATCH (b:StoryBlock {story_id:$sid}) RETURN b.block_id AS id, b.plan_sha256 AS sha",
                sid=sid,
            ))
            actual_block_hashes = {str(x["id"]): str(x["sha"] or "") for x in block_hash_rows}
            actual_macro_hashes = {
                str(x.get("id")): str(x.get("sha") or "") for x in actual_macro_rows
            }
            hash_mismatches = [
                f"StoryBlock:{key}" for key, value in expected_block_hashes.items()
                if actual_block_hashes.get(key) != value
            ] + [
                f"MacroGroup:{key}" for key, value in expected_macro_hashes.items()
                if actual_macro_hashes.get(key) != value
            ]
            if actual_blocks != expected_blocks or actual_macros != expected_macros or hash_mismatches:
                raise RuntimeError(
                    f"Neo4j hierarchy mismatch: blocks {len(actual_blocks)}/{len(expected_blocks)}, "
                    f"macros {len(actual_macros)}/{len(expected_macros)}, "
                    f"hash_mismatches={hash_mismatches[:8]}"
                )
            return {
                "story_id": sid,
                "story_plans": 1,
                "story_blocks": len(actual_blocks),
                "macro_groups": len(actual_macros),
            }
    finally:
        driver.close()


def verify_global_outline_graph(global_outline: dict[str, Any]) -> dict[str, Any]:
    """Verify the exact broad outline, phases and stable character arcs in Neo4j."""
    if not planning_graph_enabled():
        raise RuntimeError("Neo4j planning graph is not reachable or credentials are missing")
    sid = planning_story_id(global_outline)
    expected_phase_ids = {
        str(item.get("phase_id") or "")
        for item in (global_outline.get("life_phases") or [])
        if isinstance(item, dict)
    }
    expected_character_ids = {
        str(item.get("character_id") or _character_id(str(item.get("character") or "")))
        for item in (global_outline.get("character_long_arcs") or [])
        if isinstance(item, dict) and str(item.get("character") or "").strip()
    }
    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            row = session.run(
                """
                MATCH (s:StoryPlan {id:$sid})
                OPTIONAL MATCH (p:LifePhase {story_id:$sid})
                WITH s, collect(DISTINCT p.phase_id) AS phases
                OPTIONAL MATCH (c:Character {story_id:$sid})
                RETURN s.outline_sha256 AS outline_sha256,
                       s.planning_version AS planning_version,
                       phases, collect(DISTINCT c.character_id) AS characters
                """,
                sid=sid,
            ).single()
            if not row:
                raise RuntimeError(f"Neo4j missing exact StoryPlan {sid}")
            actual_outline_sha = str(row["outline_sha256"] or "")
            expected_outline_sha = _canonical_sha256(global_outline)
            if actual_outline_sha != expected_outline_sha:
                raise RuntimeError("Neo4j broad-outline canonical hash mismatch")
            actual_phases = {str(item) for item in (row["phases"] or []) if item}
            actual_characters = {str(item) for item in (row["characters"] or []) if item}
            if actual_phases != expected_phase_ids:
                raise RuntimeError(
                    f"Neo4j life phase mismatch: {len(actual_phases)}/{len(expected_phase_ids)}"
                )
            if actual_characters != expected_character_ids:
                raise RuntimeError(
                    "Neo4j long-arc character mismatch: "
                    f"{len(actual_characters)}/{len(expected_character_ids)}"
                )
            return {
                "story_id": sid,
                "outline_sha256": actual_outline_sha,
                "planning_version": str(row["planning_version"] or ""),
                "life_phases": len(actual_phases),
                "long_arc_characters": len(actual_characters),
            }
    finally:
        driver.close()


def verify_event_batch_hashes(
    global_outline: dict[str, Any], events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify each accepted event—not merely a node count—by canonical hash."""
    if not planning_graph_enabled():
        raise RuntimeError("Neo4j planning graph is not reachable or credentials are missing")
    sid = planning_story_id(global_outline)
    expected = {
        str(event.get("cluster_id") or ""): _canonical_sha256(event)
        for event in events
    }
    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (e:PlotCluster {story_id:$sid})
                WHERE e.cluster_id IN $ids
                RETURN e.cluster_id AS cluster_id, e.plan_sha256 AS plan_sha256
                """,
                sid=sid, ids=list(expected),
            )
            actual = {str(row["cluster_id"]): str(row["plan_sha256"] or "") for row in rows}
            mismatches = [eid for eid, digest in expected.items() if actual.get(eid) != digest]
            if mismatches:
                raise RuntimeError(f"Neo4j event hash mismatch: {mismatches[:8]}")
            expected_transition_count = sum(len(event.get("state_transitions") or []) for event in events)
            expected_artifact_ids = {
                (
                    str(created.get("timeline_scope") or ""),
                    str(created.get("artifact_id") or ""),
                )
                for event in events
                for milestone in (event.get("two_chapter_structure") or [])
                for created in (milestone.get("artifact_creates") or [])
                if isinstance(created, dict) and str(created.get("artifact_id") or "")
            }
            counts = session.run(
                """
                MATCH (e:PlotCluster {story_id:$sid})
                WHERE e.cluster_id IN $ids
                OPTIONAL MATCH (e)-[:APPLIES_STATE_TRANSITION]->(t:PlanStateTransition)
                WITH count(DISTINCT t) AS transitions
                MATCH (e2:PlotCluster {story_id:$sid})
                WHERE e2.cluster_id IN $ids
                OPTIONAL MATCH (e2)-[:CREATES_ARTIFACT]->(a:PlanArtifact)
                RETURN transitions, count(DISTINCT a) AS artifacts
                """,
                sid=sid, ids=list(expected),
            ).single()
            actual_transitions = int(counts["transitions"] if counts else 0)
            actual_artifacts = int(counts["artifacts"] if counts else 0)
            if actual_transitions != expected_transition_count:
                raise RuntimeError(
                    f"Neo4j state transition mismatch: {actual_transitions}/{expected_transition_count}"
                )
            if actual_artifacts != len(expected_artifact_ids):
                raise RuntimeError(
                    f"Neo4j artifact mismatch: {actual_artifacts}/{len(expected_artifact_ids)}"
                )
            return {
                "story_id": sid,
                "verified_event_hashes": len(expected),
                "verified_state_transitions": actual_transitions,
                "verified_artifacts": actual_artifacts,
            }
    finally:
        driver.close()


def upsert_event_batch(
    global_outline: dict[str, Any], macro: dict[str, Any], events: list[dict[str, Any]],
) -> str | None:
    if not planning_graph_enabled():
        return None
    sid = planning_story_id(global_outline)
    mid = str(macro.get("macro_group_id") or "")
    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            for event in events:
                eid = str(event.get("cluster_id") or "")
                span = event.get("chapter_span") or [0, 0]
                event_node_id = f"plotcluster:{sid}:{eid}"
                # This event is a replaceable compiled unit.  Remove stale
                # children/links before upserting a regenerated version so the
                # strict hash/count verifier can heal rather than only fail.
                session.run(
                    """
                    OPTIONAL MATCH (e:PlotCluster {id:$event_id})
                    OPTIONAL MATCH (e)-[:APPLIES_STATE_TRANSITION]->(t:PlanStateTransition)
                    DETACH DELETE t
                    """,
                    event_id=event_node_id,
                )
                session.run(
                    """
                    OPTIONAL MATCH (e:PlotCluster {id:$event_id})-[r:CREATES_ARTIFACT|REFERENCES_ARTIFACT]->(:PlanArtifact)
                    DELETE r
                    """,
                    event_id=event_node_id,
                )
                session.run(
                    """
                    OPTIONAL MATCH (e:PlotCluster {id:$event_id})-[r:INVOLVES_CHARACTER]->(:Character)
                    DELETE r
                    """,
                    event_id=event_node_id,
                )
                session.run(
                    """
                    MATCH (m:MacroGroup {id:$macro_id})
                    MERGE (e:PlotCluster {id:$id})
                    SET e.story_id=$sid, e.cluster_id=$eid, e.start_chapter=$start,
                        e.end_chapter=$end, e.label=$name,
                        e.info_gap_from_prev_life=$info_gap,
                        e.preemptive_avoidance=$avoidance,
                        e.cluster_outcome=$outcome, e.protagonist_gain=$gain,
                        e.villain_loss=$loss, e.relationship_change=$relationship,
                        e.continuity_json=$continuity, e.plan_sha256=$plan_sha256,
                        e.updatedAt=timestamp()
                    MERGE (m)-[:CONTAINS_CLUSTER]->(e)
                    """,
                    sid=sid, macro_id=f"macrogroup:{sid}:{mid}",
                    id=f"plotcluster:{sid}:{eid}", eid=eid,
                    start=int(span[0]), end=int(span[1]),
                    name=str(event.get("name") or eid),
                    info_gap=str(event.get("info_gap_from_prev_life") or ""),
                    avoidance=str(event.get("preemptive_avoidance") or ""),
                    outcome=str(event.get("cluster_outcome") or ""),
                    gain=str(event.get("protagonist_gain") or ""),
                    loss=str(event.get("villain_loss") or ""),
                    relationship=str(event.get("relationship_change") or ""),
                    continuity=_text(event.get("continuity_writes") or []),
                    plan_sha256=_canonical_sha256(event),
                )
                for member in event.get("canonical_cast") or []:
                    if not isinstance(member, dict):
                        continue
                    character_id = str(member.get("character_id") or "")
                    display_name = str(member.get("display_name") or member.get("name") or "")
                    if not character_id:
                        continue
                    session.run(
                        """
                        MATCH (e:PlotCluster {id:$event_id})
                        MERGE (c:Character {id:$character_node_id})
                        SET c.story_id=$sid, c.character_id=$character_id,
                            c.name=$display_name, c.label=$display_name,
                            c.aliases_json=$aliases, c.updatedAt=timestamp()
                        MERGE (e)-[:INVOLVES_CHARACTER]->(c)
                        """,
                        event_id=event_node_id,
                        character_node_id=f"planningchar:{sid}:{character_id}",
                        sid=sid, character_id=character_id, display_name=display_name,
                        aliases=_text(member.get("aliases") or []),
                    )
                for index, transition in enumerate(event.get("state_transitions") or [], 1):
                    if not isinstance(transition, dict):
                        continue
                    transition_id = f"statechange:{sid}:{eid}:{index:02d}"
                    session.run(
                        """
                        MATCH (e:PlotCluster {id:$event_id})
                        MERGE (t:PlanStateTransition {id:$transition_id})
                        SET t.story_id=$sid, t.cluster_id=$eid, t.sequence=$sequence,
                            t.domain=$domain, t.entity_id=$entity_id,
                            t.state_key=$state_key, t.from_state=$from_state,
                            t.to_state=$to_state, t.irreversible=$irreversible,
                            t.evidence=$evidence, t.transition_sha256=$transition_sha256,
                            t.updatedAt=timestamp()
                        MERGE (e)-[:APPLIES_STATE_TRANSITION]->(t)
                        """,
                        event_id=event_node_id, transition_id=transition_id,
                        sid=sid, eid=eid, sequence=index,
                        domain=str(transition.get("domain") or ""),
                        entity_id=str(transition.get("entity_id") or ""),
                        state_key=str(transition.get("state_key") or ""),
                        from_state=str(transition.get("from") or ""),
                        to_state=str(transition.get("to") or ""),
                        irreversible=bool(transition.get("irreversible")),
                        evidence=str(transition.get("evidence") or ""),
                        transition_sha256=_canonical_sha256(transition),
                    )
                for milestone in event.get("two_chapter_structure") or []:
                    if not isinstance(milestone, dict):
                        continue
                    chapter_id = int(milestone.get("chapter_id") or 0)
                    for created in milestone.get("artifact_creates") or []:
                        if not isinstance(created, dict):
                            continue
                        artifact_id = str(created.get("artifact_id") or "")
                        scope = str(created.get("timeline_scope") or "")
                        if not artifact_id:
                            continue
                        session.run(
                            """
                            MATCH (e:PlotCluster {id:$event_id})
                            MERGE (a:PlanArtifact {id:$artifact_node_id})
                            SET a.story_id=$sid, a.artifact_id=$artifact_id,
                                a.timeline_scope=$scope, a.display_name=$display_name,
                                a.kind=$kind, a.created_in_chapter=$chapter_id,
                                a.updatedAt=timestamp()
                            MERGE (e)-[:CREATES_ARTIFACT {chapter_id:$chapter_id}]->(a)
                            """,
                            event_id=event_node_id,
                            artifact_node_id=f"artifact:{sid}:{scope}:{artifact_id}",
                            sid=sid, artifact_id=artifact_id, scope=scope,
                            display_name=str(created.get("display_name") or ""),
                            kind=str(created.get("kind") or ""), chapter_id=chapter_id,
                        )
                    for ref in milestone.get("artifact_refs") or []:
                        if not isinstance(ref, dict):
                            continue
                        artifact_id = str(ref.get("artifact_id") or "")
                        scope = str(ref.get("timeline_scope") or "")
                        session.run(
                            """
                            MATCH (e:PlotCluster {id:$event_id})
                            MATCH (a:PlanArtifact {id:$artifact_node_id})
                            MERGE (e)-[r:REFERENCES_ARTIFACT {chapter_id:$chapter_id, artifact_id:$artifact_id}]->(a)
                            SET r.purpose=$purpose
                            """,
                            event_id=event_node_id,
                            artifact_node_id=f"artifact:{sid}:{scope}:{artifact_id}",
                            chapter_id=chapter_id, artifact_id=artifact_id,
                            purpose=str(ref.get("purpose") or ""),
                        )
            ids = [str(event.get("cluster_id") or "") for event in events]
            for left, right in zip(ids, ids[1:]):
                session.run(
                    "MATCH (a:PlotCluster {id:$a}), (b:PlotCluster {id:$b}) MERGE (a)-[:PLANNED_BEFORE]->(b)",
                    a=f"plotcluster:{sid}:{left}", b=f"plotcluster:{sid}:{right}",
                )
            session.run(
                "MATCH (a:PlanArtifact {story_id:$sid}) "
                "WHERE NOT (:PlotCluster)-[:CREATES_ARTIFACT]->(a) DETACH DELETE a",
                sid=sid,
            )
    finally:
        driver.close()
    return sid


def retrieve_event_context(
    global_outline: dict[str, Any], macro: dict[str, Any], limit: int = 8,
) -> dict[str, Any]:
    if not planning_graph_enabled():
        return {}
    sid = planning_story_id(global_outline)
    mid = str(macro.get("macro_group_id") or "")
    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            current = session.run(
                """
                MATCH (m:MacroGroup {id:$id})
                OPTIONAL MATCH (b:StoryBlock)-[:CONTAINS_MACRO]->(m)
                RETURN m{.macro_group_id, .start_chapter, .end_chapter,
                         .title, .goal, .ending_state, .next_hook} AS macro,
                       b{.block_id, .start_chapter, .end_chapter,
                         .title, .goal, .outcome, .handoff, .entry_state_json,
                         .character_movements_json, .state_changes_json,
                         .causal_links_json, .foreshadows_json,
                         .continuity_json, .plan_json} AS block
                """,
                id=f"macrogroup:{sid}:{mid}",
            ).single()
            prior = list(session.run(
                """
                MATCH (e:PlotCluster {story_id:$sid})
                WHERE e.end_chapter < $start
                RETURN e.cluster_id AS cluster_id, e.label AS name,
                       e.cluster_outcome AS outcome, e.protagonist_gain AS gain,
                       e.villain_loss AS loss, e.relationship_change AS relationship,
                       e.continuity_json AS continuity
                ORDER BY e.end_chapter DESC LIMIT $limit
                """,
                sid=sid, start=int((macro.get("chapter_span") or [1])[0]), limit=int(limit),
            ))
            state_rows = list(session.run(
                """
                MATCH (e:PlotCluster {story_id:$sid})-[:APPLIES_STATE_TRANSITION]->(t:PlanStateTransition)
                WHERE e.end_chapter < $start
                WITH t.domain + ':' + t.entity_id + ':' + t.state_key AS state_id, t, e
                ORDER BY e.end_chapter DESC, t.sequence DESC
                WITH state_id, collect({cluster_id:e.cluster_id, to_state:t.to_state,
                                        irreversible:t.irreversible, evidence:t.evidence})[0] AS latest
                RETURN state_id, latest
                ORDER BY state_id
                """,
                sid=sid, start=int((macro.get("chapter_span") or [1])[0]),
            ))
            artifact_rows = list(session.run(
                """
                MATCH (e:PlotCluster {story_id:$sid})-[:CREATES_ARTIFACT]->(a:PlanArtifact)
                WHERE e.end_chapter < $start
                RETURN a.artifact_id AS artifact_id, a.timeline_scope AS timeline_scope,
                       a.display_name AS display_name, a.kind AS kind,
                       a.created_in_chapter AS created_in_chapter
                ORDER BY a.created_in_chapter
                """,
                sid=sid, start=int((macro.get("chapter_span") or [1])[0]),
            ))
            block_projection = dict(current["block"]) if current and current["block"] else {}
            # Prefer the exact accepted block object.  The individual graph
            # properties remain queryable for debugging, while generation gets
            # structured JSON rather than an escaped JSON string missing fields.
            current_block = _json_object(block_projection.get("plan_json")) or block_projection
            return {
                "source": "neo4j_planning_graph",
                "story_id": sid,
                "current_macro": dict(current["macro"]) if current and current["macro"] else {},
                "current_block": current_block,
                "recent_completed_events": [dict(record) for record in reversed(prior)],
                "canonical_state": {
                    str(row["state_id"]): dict(row["latest"]) for row in state_rows
                },
                "available_artifacts": [dict(row) for row in artifact_rows],
            }
    finally:
        driver.close()

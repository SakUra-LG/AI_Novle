import argparse
import os
import json
import hashlib
from typing import Dict, Any, List
from neo4j import Driver
from .common import get_neo4j_driver, normalize_character_id
from .story_identity import story_id_for_clusters
from .planning_graph import planning_story_id


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

try:
    import yaml  # type: ignore
except Exception:
    yaml = None


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_clusters_config(path: str) -> Dict[str, Any]:
    if not path or not os.path.isfile(path):
        return {"clusters": []}
    text = read_text(path)
    if yaml is not None:
        try:
            data = yaml.safe_load(text) or {}
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return {"clusters": data}
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"clusters": []}


def _story_id_for_plan(config_path: str, outline_path: str = "") -> str:
    candidate = outline_path or os.path.join(
        os.path.dirname(os.path.abspath(config_path)), "global_story_outline_v5_qwen_500.json"
    )
    if os.path.isfile(candidate):
        try:
            outline = json.loads(read_text(candidate))
            if isinstance(outline, dict):
                return planning_story_id(outline)
        except (OSError, json.JSONDecodeError):
            pass
    return story_id_for_clusters(config_path)


def _neo4j_property(value: Any) -> Any:
    """Convert structured planning values into legal Neo4j properties."""
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, list):
        if any(isinstance(item, (dict, list)) for item in value):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return [str(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def upsert_plot_clusters(
    driver: Driver, config_path: str, story_id: str = "", outline_path: str = "",
) -> None:
    story_id = story_id or _story_id_for_plan(config_path, outline_path)
    cfg = load_clusters_config(config_path)
    clusters: List[Dict[str, Any]] = [c for c in (cfg.get("clusters") or []) if isinstance(c, dict)]
    if not clusters:
        print("No clusters found in config.")
        return
    with driver.session() as session:
        # A full rebuild is authoritative for this planning scope.  Remove
        # compiler-owned child nodes first so transitions/artifacts deleted
        # from the JSON cannot survive as stale graph facts.
        session.run(
            """
            MATCH (n {story_id:$story_id})
            WHERE n:PlanStateTransition OR n:PlanArtifact
            DETACH DELETE n
            """,
            story_id=story_id,
        )
        session.run("MATCH (pc:PlotCluster {story_id:$story_id}) DETACH DELETE pc", story_id=story_id)
        def _upsert_cluster(tx, cid: str, props: Dict[str, Any]):
            tx.run(
                """
                MERGE (pc:PlotCluster {id:$id})
                ON CREATE SET
                  pc.label=$label,
                  pc.cluster_id=$cluster_id,
                  pc.story_id=$story_id,
                  pc.goal=$goal,
                  pc.mood=$mood,
                  pc.start_chapter=$start_chapter,
                  pc.end_chapter=$end_chapter,
                  pc.plan_relations=$plan_relations,
                  pc.plan_foreshadows=$plan_foreshadows,
                  pc.plan_resolves=$plan_resolves,
                  pc.hard_constraints=$hard_constraints,
                  pc.timeline_years=$timeline_years,
                  pc.prev_life_tragedy=$prev_life_tragedy,
                  pc.info_gap_from_prev_life=$info_gap_from_prev_life,
                  pc.this_life_revenge=$this_life_revenge,
                  pc.cluster_outcome=$cluster_outcome,
                  pc.romance_state=$romance_state,
                  pc.comic_villain_beat=$comic_villain_beat,
                  pc.fictional_obstacle=$fictional_obstacle,
                  pc.preemptive_avoidance=$preemptive_avoidance,
                  pc.ascension_gain=$ascension_gain,
                  pc.rebirth_flywheel=$rebirth_flywheel,
                  pc.source_anchor_ids=$source_anchor_ids,
                  pc.phase_id=$phase_id,
                  pc.story_block_id=$story_block_id,
                  pc.macro_group_id=$macro_group_id,
                  pc.continuity_writes=$continuity_writes,
                  pc.story_block_goal=$story_block_goal,
                  pc.macro_goal=$macro_goal,
                  pc.plan_sha256=$plan_sha256,
                  pc.createdAt=timestamp()
                ON MATCH SET
                  pc.label=$label,
                  pc.cluster_id=$cluster_id,
                  pc.story_id=$story_id,
                  pc.goal=$goal,
                  pc.mood=$mood,
                  pc.start_chapter=$start_chapter,
                  pc.end_chapter=$end_chapter,
                  pc.plan_relations=$plan_relations,
                  pc.plan_foreshadows=$plan_foreshadows,
                  pc.plan_resolves=$plan_resolves,
                  pc.hard_constraints=$hard_constraints,
                  pc.timeline_years=$timeline_years,
                  pc.prev_life_tragedy=$prev_life_tragedy,
                  pc.info_gap_from_prev_life=$info_gap_from_prev_life,
                  pc.this_life_revenge=$this_life_revenge,
                  pc.cluster_outcome=$cluster_outcome,
                  pc.romance_state=$romance_state,
                  pc.comic_villain_beat=$comic_villain_beat,
                  pc.fictional_obstacle=$fictional_obstacle,
                  pc.preemptive_avoidance=$preemptive_avoidance,
                  pc.ascension_gain=$ascension_gain,
                  pc.rebirth_flywheel=$rebirth_flywheel,
                  pc.source_anchor_ids=$source_anchor_ids,
                  pc.phase_id=$phase_id,
                  pc.story_block_id=$story_block_id,
                  pc.macro_group_id=$macro_group_id,
                  pc.continuity_writes=$continuity_writes,
                  pc.story_block_goal=$story_block_goal,
                  pc.macro_goal=$macro_goal,
                  pc.plan_sha256=$plan_sha256,
                  pc.updatedAt=timestamp()
                """,
                **props,
            )
        def _upsert_character(tx, char_id: str, story_id: str, member: Dict[str, Any]):
            name = str(member.get("display_name") or member.get("name") or "").strip()
            if not name:
                return
            tx.run(
                """
                MERGE (c:Character {id:$id})
                ON CREATE SET c.createdAt=timestamp(), c.planned_only=true
                SET c.label=$name, c.name=$name, c.story_id=$story_id,
                    c.character_id=$character_id, c.aliases_json=$aliases,
                    c.planned_role=$role, c.planned_alignment=$alignment,
                    c.updatedAt=timestamp()
                """,
                id=char_id,
                story_id=story_id,
                name=name,
                character_id=str(member.get("character_id") or ""),
                aliases=json.dumps(member.get("aliases") or [], ensure_ascii=False),
                role=str(member.get("role") or ""),
                alignment=str(member.get("alignment") or ""),
            )
        def _link_main_chars(tx, pc_id: str, char_ids: List[str]):
            tx.run(
                """
                MATCH (pc:PlotCluster {id:$id, story_id:$story_id})
                WITH pc
                UNWIND $chars AS cid
                MATCH (c:Character {id:cid})
                MERGE (c)-[:MAJOR_IN]->(pc)
                """,
                id=pc_id,
                story_id=story_id,
                chars=char_ids,
            )
        def _link_plan_hierarchy(
            tx, pc_id: str, phase_id: str, block_id: str, macro_id: str,
            phase_span: List[int], block_span: List[int], macro_span: List[int],
            block_title: str, block_goal: str, block_outcome: str,
            macro_title: str, macro_goal: str, macro_ending_state: str,
        ):
            tx.run(
                """
                MERGE (phase:LifePhase {id:$phase_node_id})
                SET phase.story_id=$story_id, phase.phase_id=$phase_id,
                    phase.start_chapter=$phase_start, phase.end_chapter=$phase_end,
                    phase.updatedAt=timestamp()
                MERGE (block:StoryBlock {id:$block_node_id})
                SET block.story_id=$story_id, block.block_id=$block_id,
                    block.start_chapter=$block_start, block.end_chapter=$block_end,
                    block.title=$block_title, block.goal=$block_goal, block.outcome=$block_outcome,
                    block.updatedAt=timestamp()
                MERGE (macro:MacroGroup {id:$macro_node_id})
                SET macro.story_id=$story_id, macro.macro_group_id=$macro_id,
                    macro.start_chapter=$macro_start, macro.end_chapter=$macro_end,
                    macro.title=$macro_title, macro.goal=$macro_goal, macro.ending_state=$macro_ending_state,
                    macro.updatedAt=timestamp()
                WITH phase, block, macro
                MATCH (pc:PlotCluster {id:$pc_id, story_id:$story_id})
                MERGE (phase)-[:CONTAINS_BLOCK]->(block)
                MERGE (block)-[:CONTAINS_MACRO]->(macro)
                MERGE (macro)-[:CONTAINS_CLUSTER]->(pc)
                """,
                story_id=story_id,
                pc_id=pc_id,
                phase_node_id=f"lifephase:{story_id}:{phase_id}",
                phase_id=phase_id,
                phase_start=phase_span[0], phase_end=phase_span[1],
                block_node_id=f"storyblock:{story_id}:{block_id}",
                block_id=block_id,
                block_start=block_span[0], block_end=block_span[1],
                macro_node_id=f"macrogroup:{story_id}:{macro_id}",
                macro_id=macro_id,
                macro_start=macro_span[0], macro_end=macro_span[1],
                block_title=block_title, block_goal=block_goal, block_outcome=block_outcome,
                macro_title=macro_title, macro_goal=macro_goal, macro_ending_state=macro_ending_state,
            )
        for c in clusters:
            cid = str(c.get("id") or c.get("cluster_id") or "").strip()
            if not cid:
                continue
            label = str(c.get("title") or c.get("name") or cid)
            canonical_cast = [
                member for member in (c.get("canonical_cast") or [])
                if isinstance(member, dict) and str(member.get("name") or "").strip()
            ]
            for member in canonical_cast:
                name = str(member.get("name") or "").strip()
                stable_id = str(member.get("character_id") or normalize_character_id(name))
                char_id = f"planningchar:{story_id}:{stable_id}"
                session.execute_write(_upsert_character, char_id, story_id, member)
            ids_by_alias: Dict[str, str] = {}
            for member in canonical_cast:
                stable_id = str(member.get("character_id") or normalize_character_id(str(member.get("name") or "")))
                for alias in [member.get("name"), member.get("display_name"), *(member.get("aliases") or [])]:
                    if str(alias or "").strip():
                        ids_by_alias[str(alias).strip()] = stable_id
            mains = [
                f"planningchar:{story_id}:{ids_by_alias.get(str(x).strip(), normalize_character_id(x))}"
                for x in (c.get("main_characters") or c.get("allowed_roles") or [])
            ]
            span = c.get("chapter_span") or [c.get("start_chapter"), c.get("end_chapter")]
            start_chapter = span[0] if isinstance(span, list) and len(span) == 2 else c.get("start_chapter")
            end_chapter = span[1] if isinstance(span, list) and len(span) == 2 else c.get("end_chapter")
            start_number = int(start_chapter)
            phase_number = (start_number - 1) // 50 + 1
            block_number = (start_number - 1) // 20 + 1
            macro_number = (start_number - 1) // 10 + 1
            phase_id = str(c.get("arc_id") or f"P{phase_number:02d}")
            block_id = str(c.get("story_block_id") or f"B{block_number:03d}")
            macro_id = str(c.get("macro_group_id") or f"MG{macro_number:03d}")
            props = {
                "id": f"plotcluster:{story_id}:{cid}",
                "cluster_id": cid,
                "story_id": story_id,
                "label": label,
                "goal": c.get("goal") or c.get("core_payoff") or c.get("cluster_outcome"),
                "mood": c.get("mood"),
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
                "plan_relations": _neo4j_property(c.get("plan_relations") or []),
                "plan_foreshadows": _neo4j_property(c.get("foreshadows") or c.get("notes") or []),
                "plan_resolves": _neo4j_property(c.get("resolves") or ([c.get("cluster_outcome")] if c.get("cluster_outcome") else [])),
                "hard_constraints": _neo4j_property(c.get("hard_constraints") or c.get("user_extra_constraints") or []),
                "timeline_years": str(c.get("timeline_years") or ""),
                "prev_life_tragedy": str(c.get("prev_life_tragedy") or ""),
                "info_gap_from_prev_life": str(c.get("info_gap_from_prev_life") or ""),
                "this_life_revenge": str(c.get("this_life_revenge") or ""),
                "cluster_outcome": str(c.get("cluster_outcome") or ""),
                "romance_state": str(c.get("romance_state") or ""),
                "comic_villain_beat": str(c.get("comic_villain_beat") or ""),
                "fictional_obstacle": str(c.get("fictional_obstacle") or ""),
                "preemptive_avoidance": str(c.get("preemptive_avoidance") or ""),
                "ascension_gain": str(c.get("ascension_gain") or ""),
                "rebirth_flywheel": _neo4j_property(c.get("rebirth_flywheel") or []),
                "source_anchor_ids": [str(x) for x in (c.get("source_anchor_ids") or [])],
                "phase_id": phase_id,
                "story_block_id": block_id,
                "macro_group_id": macro_id,
                "continuity_writes": [str(x) for x in (c.get("continuity_writes") or [])],
                "story_block_goal": str(c.get("story_block_goal") or ""),
                "macro_goal": str(c.get("macro_goal") or ""),
                "plan_sha256": _canonical_sha256(c),
            }
            session.execute_write(_upsert_cluster, props["id"], props)
            session.execute_write(
                _link_plan_hierarchy,
                props["id"], phase_id, block_id, macro_id,
                [(phase_number - 1) * 50 + 1, phase_number * 50],
                [(block_number - 1) * 20 + 1, block_number * 20],
                [(macro_number - 1) * 10 + 1, macro_number * 10],
                str(c.get("story_block_title") or block_id),
                str(c.get("story_block_goal") or ""),
                str(c.get("story_block_outcome") or ""),
                str(c.get("macro_group_title") or macro_id),
                str(c.get("macro_goal") or ""),
                str(c.get("macro_ending_state") or ""),
            )
            if mains:
                session.execute_write(_link_main_chars, props["id"], mains)
            for transition_index, transition in enumerate(c.get("state_transitions") or [], 1):
                if not isinstance(transition, dict):
                    continue
                session.run(
                    """
                    MATCH (pc:PlotCluster {id:$pc_id, story_id:$story_id})
                    MERGE (t:PlanStateTransition {id:$transition_id})
                    SET t.story_id=$story_id, t.cluster_id=$cluster_id,
                        t.sequence=$sequence, t.domain=$domain, t.entity_id=$entity_id,
                        t.state_key=$state_key, t.from_state=$from_state,
                        t.to_state=$to_state, t.irreversible=$irreversible,
                        t.evidence=$evidence, t.transition_sha256=$transition_sha256,
                        t.updatedAt=timestamp()
                    MERGE (pc)-[:APPLIES_STATE_TRANSITION]->(t)
                    """,
                    pc_id=props["id"], story_id=story_id,
                    transition_id=f"statechange:{story_id}:{cid}:{transition_index:02d}",
                    cluster_id=cid, sequence=transition_index,
                    domain=str(transition.get("domain") or ""),
                    entity_id=str(transition.get("entity_id") or ""),
                    state_key=str(transition.get("state_key") or ""),
                    from_state=str(transition.get("from") or ""),
                    to_state=str(transition.get("to") or ""),
                    irreversible=bool(transition.get("irreversible")),
                    evidence=str(transition.get("evidence") or ""),
                    transition_sha256=_canonical_sha256(transition),
                )
            for milestone in c.get("two_chapter_structure") or []:
                if not isinstance(milestone, dict):
                    continue
                chapter_id = int(milestone.get("chapter_id") or 0)
                for created in milestone.get("artifact_creates") or []:
                    if not isinstance(created, dict) or not str(created.get("artifact_id") or ""):
                        continue
                    artifact_id = str(created["artifact_id"])
                    scope = str(created.get("timeline_scope") or "")
                    session.run(
                        """
                        MATCH (pc:PlotCluster {id:$pc_id, story_id:$story_id})
                        MERGE (a:PlanArtifact {id:$artifact_node_id})
                        SET a.story_id=$story_id, a.artifact_id=$artifact_id,
                            a.timeline_scope=$scope, a.display_name=$display_name,
                            a.kind=$kind, a.created_in_chapter=$chapter_id,
                            a.updatedAt=timestamp()
                        MERGE (pc)-[:CREATES_ARTIFACT {chapter_id:$chapter_id}]->(a)
                        """,
                        pc_id=props["id"], story_id=story_id,
                        artifact_node_id=f"artifact:{story_id}:{scope}:{artifact_id}",
                        artifact_id=artifact_id, scope=scope,
                        display_name=str(created.get("display_name") or ""),
                        kind=str(created.get("kind") or ""), chapter_id=chapter_id,
                    )
                for ref in milestone.get("artifact_refs") or []:
                    if not isinstance(ref, dict) or not str(ref.get("artifact_id") or ""):
                        continue
                    artifact_id = str(ref["artifact_id"])
                    scope = str(ref.get("timeline_scope") or "")
                    session.run(
                        """
                        MATCH (pc:PlotCluster {id:$pc_id, story_id:$story_id})
                        MATCH (a:PlanArtifact {id:$artifact_node_id})
                        MERGE (pc)-[r:REFERENCES_ARTIFACT {chapter_id:$chapter_id, artifact_id:$artifact_id}]->(a)
                        SET r.purpose=$purpose
                        """,
                        pc_id=props["id"], story_id=story_id,
                        artifact_node_id=f"artifact:{story_id}:{scope}:{artifact_id}",
                        chapter_id=chapter_id, artifact_id=artifact_id,
                        purpose=str(ref.get("purpose") or ""),
                    )
        session.run(
            """
            MATCH (a:PlotCluster {story_id:$story_id}), (b:PlotCluster {story_id:$story_id})
            WHERE b.start_chapter = a.end_chapter + 1
            MERGE (a)-[:PLANNED_BEFORE]->(b)
            """,
            story_id=story_id,
        )
        session.run(
            """
            MATCH (a:StoryBlock {story_id:$story_id}), (b:StoryBlock {story_id:$story_id})
            WHERE b.start_chapter = a.end_chapter + 1
            MERGE (a)-[:PLANNED_BEFORE]->(b)
            """,
            story_id=story_id,
        )
        session.run(
            """
            MATCH (a:MacroGroup {story_id:$story_id}), (b:MacroGroup {story_id:$story_id})
            WHERE b.start_chapter = a.end_chapter + 1
            MERGE (a)-[:PLANNED_BEFORE]->(b)
            """,
            story_id=story_id,
        )
    print(f"Upserted {len(clusters)} plot clusters.")


def main():
    parser = argparse.ArgumentParser(description="Upsert Plot Clusters (情节族) into Neo4j from config.")
    parser.add_argument(
        "--clusters-config",
        type=str,
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "outputs", "event_clusters_v2.json"),
        help="Path to YAML/JSON plot clusters config (default: outputs/event_clusters_v2.json).",
    )
    parser.add_argument("--story-id", default="", help="Explicit story scope override.")
    parser.add_argument(
        "--outline", default="",
        help="Global outline JSON used to derive the same planning story scope as the v6 planner.",
    )
    args = parser.parse_args()
    driver = get_neo4j_driver()
    try:
        upsert_plot_clusters(driver, args.clusters_config, args.story_id, args.outline)
    finally:
        driver.close()


if __name__ == "__main__":
    main()


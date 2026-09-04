#!/usr/bin/env python3
"""Retrieve current, chapter-bounded story constraints from Neo4j."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .common import get_neo4j_driver
from .chapter_memory import story_state_slot


def _clip(value: Any, limit: int = 260) -> str:
    return str(value or "").strip()[:limit]


def _names(values: Iterable[str]) -> List[str]:
    return [str(x).strip() for x in values if str(x or "").strip()]


def _latest_current_fact_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the latest value of each independent state slot.

    Neo4j keeps every assertion for auditability.  Deduplication happens here
    so multiple ``possession`` rights survive independently while ordinary
    single-valued predicates still use their latest assertion.
    """

    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: int(row.get("chapter", 0) or 0),
        reverse=True,
    )
    selected: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in ordered:
        subject = str(row.get("subject") or "").strip()
        predicate = str(row.get("predicate") or "").strip().lower()
        if not subject or not predicate:
            continue
        slot = story_state_slot({
            "predicate": predicate,
            "object": row.get("object"),
            "evidence": row.get("evidence"),
            "state_key": row.get("state_key"),
        })
        key = (subject.casefold(), slot)
        if key in seen:
            continue
        seen.add(key)
        row["state_key"] = slot
        selected.append(row)
    selected.sort(
        key=lambda row: (
            0 if str(row.get("predicate") or "") == "life_status" else 1,
            -int(row.get("chapter", 0) or 0),
        )
    )
    return selected[:80]


def retrieve_context_for_chapter(
    chapter_num: int,
    allowed_roles: Optional[List[str]] = None,
    main_opponent: Optional[str] = None,
    max_chars: int = 2200,
    story_id: str = "default",
) -> str:
    """Return facts valid immediately before ``chapter_num``.

    Current state is computed as-of the target chapter instead of trusting a
    globally cached ``active`` flag, so regenerating an earlier chapter cannot
    accidentally see facts from the future.
    """
    target = int(chapter_num)
    names = _names(allowed_roles or [])
    if main_opponent and str(main_opponent).strip() not in names:
        names.append(str(main_opponent).strip())

    with get_neo4j_driver() as driver:
        with driver.session() as session:
            fact_rows = session.run(
                """
                MATCH (f:StoryFact)
                WHERE f.story_id=$story_id AND f.source_chapter < $chapter
                  AND coalesce(f.timeline, 'current') IN ['current', 'unknown']
                  AND (size($names)=0 OR f.subject IN $names)
                RETURN f.subject AS subject, f.predicate AS predicate,
                       f.state_key AS state_key, f.object AS object,
                       f.source_chapter AS chapter, f.evidence AS evidence,
                       f.permanent AS permanent
                ORDER BY f.source_chapter DESC
                LIMIT 160
                """,
                chapter=target,
                names=names,
                story_id=story_id,
            ).data()
            fact_rows = _latest_current_fact_rows(fact_rows)
            relation_rows = session.run(
                """
                MATCH (r:RelationFact)-[:FROM_CHARACTER]->(a:Character)
                MATCH (r)-[:TO_CHARACTER]->(b:Character)
                WHERE r.story_id=$story_id AND r.source_chapter < $chapter
                  AND coalesce(r.timeline, 'current') IN ['current', 'unknown']
                  AND (size($names)=0 OR a.label IN $names OR b.label IN $names)
                WITH a, b, r.relation_type AS relation_type, r
                ORDER BY r.source_chapter DESC
                WITH a, b, relation_type, head(collect(r)) AS latest
                RETURN a.label AS subject, b.label AS object, relation_type,
                       latest.status AS status, latest.source_chapter AS chapter,
                       latest.evidence AS evidence
                LIMIT 40
                """,
                chapter=target,
                names=names,
                story_id=story_id,
            ).data()
            thread_rows = session.run(
                """
                MATCH (s:PlotThreadSignal)-[:UPDATES_THREAD]->(t:PlotThread)
                WHERE s.story_id=$story_id AND s.source_chapter < $chapter
                WITH t, s ORDER BY s.source_chapter DESC
                WITH t, head(collect(s)) AS latest
                WHERE latest.status='open'
                RETURN t.title AS title, latest.summary AS summary,
                       latest.source_chapter AS chapter
                ORDER BY chapter DESC LIMIT 12
                """,
                chapter=target,
                story_id=story_id,
            ).data()
            event_rows = session.run(
                """
                MATCH (e:StoryEvent)
                WHERE e.story_id=$story_id AND e.source_chapter < $chapter
                OPTIONAL MATCH (c:Character)-[p:PARTICIPATED_IN]->(e)
                WITH e, collect(DISTINCT c.label) AS participants
                WHERE size($names)=0 OR any(n IN participants WHERE n IN $names)
                RETURN e.summary AS summary, e.outcome AS outcome,
                       e.source_chapter AS chapter, e.story_time AS story_time,
                       e.timeline AS timeline,
                       e.importance AS importance
                ORDER BY chapter DESC, importance DESC LIMIT 16
                """,
                chapter=target,
                names=names,
                story_id=story_id,
            ).data()
            plan_row = session.run(
                """
                MATCH (pc:PlotCluster)
                WHERE pc.story_id=$story_id
                  AND pc.start_chapter <= $chapter AND pc.end_chapter >= $chapter
                RETURN pc.id AS id, pc.label AS label, pc.goal AS goal,
                       pc.plan_foreshadows AS foreshadows, pc.plan_resolves AS resolves,
                       pc.hard_constraints AS hard_constraints,
                       pc.timeline_years AS timeline_years,
                       pc.prev_life_tragedy AS prev_life_tragedy,
                       pc.info_gap_from_prev_life AS info_gap_from_prev_life,
                       pc.this_life_revenge AS this_life_revenge,
                       pc.cluster_outcome AS cluster_outcome,
                       pc.romance_state AS romance_state,
                       pc.comic_villain_beat AS comic_villain_beat,
                       pc.fictional_obstacle AS fictional_obstacle,
                       pc.preemptive_avoidance AS preemptive_avoidance,
                       pc.ascension_gain AS ascension_gain,
                       pc.rebirth_flywheel AS rebirth_flywheel,
                       pc.source_anchor_ids AS source_anchor_ids,
                       pc.story_block_id AS story_block_id,
                       pc.story_block_goal AS story_block_goal,
                       pc.macro_group_id AS macro_group_id,
                       pc.macro_goal AS macro_goal,
                       pc.start_chapter AS start_chapter, pc.end_chapter AS end_chapter
                ORDER BY pc.start_chapter DESC LIMIT 1
                """,
                chapter=target,
                story_id=story_id,
            ).single()

    lines = [f"【第{target}章生成前知识图谱约束】"]
    if main_opponent:
        lines.append(f"- 本章主要对手：{main_opponent}")
    if names:
        lines.append(f"- 重点角色：{'、'.join(names[:10])}")
    if plan_row:
        lines.append(
            f"- [当前情节族计划，尚未发生] {plan_row.get('label')}（第{plan_row.get('start_chapter')}-{plan_row.get('end_chapter')}章）；"
            f"目标={_clip(plan_row.get('goal'), 360)}"
        )
        if plan_row.get("hard_constraints"):
            lines.append(f"- [计划硬限制] {_clip(plan_row.get('hard_constraints'), 360)}")
        if plan_row.get("story_block_goal"):
            lines.append(
                f"- [20章中期目标 {plan_row.get('story_block_id')}] "
                f"{_clip(plan_row.get('story_block_goal'), 320)}"
            )
        if plan_row.get("macro_goal"):
            lines.append(
                f"- [10章当前目标 {plan_row.get('macro_group_id')}] "
                f"{_clip(plan_row.get('macro_goal'), 280)}"
            )
        if plan_row.get("timeline_years"):
            lines.append(f"- [当前年代] {_clip(plan_row.get('timeline_years'), 120)}")
        if plan_row.get("prev_life_tragedy"):
            lines.append(f"- [前世受害事实，仅作记忆] {_clip(plan_row.get('prev_life_tragedy'), 280)}")
        if plan_row.get("info_gap_from_prev_life"):
            lines.append(f"- [前世信息差，不是今生证据] {_clip(plan_row.get('info_gap_from_prev_life'), 280)}")
        if plan_row.get("this_life_revenge"):
            lines.append(f"- [今生合法布局] {_clip(plan_row.get('this_life_revenge'), 320)}")
        if plan_row.get("romance_state"):
            lines.append(f"- [感情线状态] {_clip(plan_row.get('romance_state'), 240)}")
        if plan_row.get("comic_villain_beat"):
            lines.append(f"- [反派滑稽点] {_clip(plan_row.get('comic_villain_beat'), 220)}")
        if plan_row.get("rebirth_flywheel"):
            lines.append(f"- [本簇重生飞升节奏] {_clip(plan_row.get('rebirth_flywheel'), 260)}")
        if plan_row.get("ascension_gain"):
            lines.append(f"- [簇末飞升收益] {_clip(plan_row.get('ascension_gain'), 280)}")
        if plan_row.get("resolves"):
            lines.append(f"- [本簇应回收] {_clip(plan_row.get('resolves'), 300)}")
    for row in fact_rows:
        subject, predicate, value = row.get("subject"), row.get("predicate"), row.get("object")
        if not subject or not predicate:
            continue
        hard = predicate == "life_status" and str(value).lower() == "dead"
        suffix = "；禁止在当前时间线行动，只可回忆/梦境/转述" if hard else ""
        lines.append(f"- [{'硬约束' if hard else '当前事实'}] {subject}.{predicate}={value}（第{row.get('chapter')}章）{suffix}")
    for row in relation_rows[:12]:
        lines.append(f"- [当前关系] {row.get('subject')} --{row.get('relation_type')}/{row.get('status')}--> {row.get('object')}（第{row.get('chapter')}章更新）")
    for row in thread_rows[:8]:
        lines.append(f"- [未决剧情线] {_clip(row.get('title'), 180)}（第{row.get('chapter')}章推进）")
    for row in event_rows[:10]:
        timeline = str(row.get("timeline") or "current")
        label = "今生已发生" if timeline in {"current", "unknown"} else "仅历史/回忆"
        lines.append(f"- [{label}] 第{row.get('chapter')}章：{_clip(row.get('summary'))}；结果={_clip(row.get('outcome')) or '未明确'}")
    return "\n".join(lines)[:max_chars]

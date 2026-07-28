#!/usr/bin/env python3
"""Retrieve current, chapter-bounded story constraints from Neo4j."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .common import get_neo4j_driver


def _clip(value: Any, limit: int = 260) -> str:
    return str(value or "").strip()[:limit]


def _names(values: Iterable[str]) -> List[str]:
    return [str(x).strip() for x in values if str(x or "").strip()]


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
                WITH f.subject AS subject, f.predicate AS predicate, f
                ORDER BY f.source_chapter DESC
                WITH subject, predicate, head(collect(f)) AS latest
                RETURN subject, predicate, latest.object AS object,
                       latest.source_chapter AS chapter, latest.evidence AS evidence,
                       latest.permanent AS permanent
                ORDER BY CASE WHEN predicate='life_status' THEN 0 ELSE 1 END, chapter DESC
                LIMIT 80
                """,
                chapter=target,
                names=names,
                story_id=story_id,
            ).data()
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

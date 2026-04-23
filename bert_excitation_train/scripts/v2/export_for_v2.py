import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Set
from neo4j import Driver

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bert_excitation_train.scripts.neo4j_kg.common import get_neo4j_driver


def fetch_context(driver: Driver, chapters: List[int]) -> Dict[str, Any]:
    """
    Export a constraints-oriented context:
    - global constraints (world rules, timeline now, forbidden conflicts)
    - characters with rich properties and current state snapshot
    - semantic relationships if present; fallback to interaction stats
    - timeline events in range
    """
    chapter_set: Set[int] = set(chapters)
    entities: Dict[str, Dict[str, Any]] = {}
    relationships: List[Dict[str, Any]] = []
    timeline: List[Dict[str, Any]] = []
    name_to_id: Dict[str, str] = {}
    characters_out: List[Dict[str, Any]] = []

    with driver.session() as session:
        # Characters who participated in target chapters, with rich props
        result = session.run(
            """
            MATCH (c:Character)-[:PARTICIPATED_IN]->(e:Event)
            WHERE e.chapter IN $chapters
            RETURN DISTINCT
              c.id AS id, c.label AS label, c.gender AS gender, c.role_type AS role_type,
              c.faction AS faction, c.identity AS identity, c.age_stage AS age_stage,
              c.personality_tags AS personality_tags, c.speaking_style AS speaking_style,
              c.core_goal AS core_goal, c.status AS status, c.aliases AS aliases,
              c.first_chapter AS first_chapter, c.last_seen_chapter AS last_seen_chapter
            """,
            chapters=chapters,
        )
        for rec in result:
            cid = rec["id"]
            label = rec["label"]
            entities[cid] = {
                "name": label,
                "type": "person",
                "source_chapters": [str(ch) for ch in sorted(chapter_set)],
                "desc": "",
            }
            name_to_id[f"person:{label}"] = cid
            # Pull latest state snapshot in-window if any
            state = session.run(
                """
                MATCH (c:Character {id:$id})-[:HAS_STATE]->(s:CharacterState)
                WHERE s.chapter IN $chapters
                RETURN s
                ORDER BY s.chapter DESC
                LIMIT 1
                """,
                id=cid,
                chapters=chapters,
            ).single()
            snode = state["s"] if state else None
            sprops = dict(snode) if snode is not None else {}
            characters_out.append(
                {
                    "id": cid,
                    "name": label,
                    "role_type": rec["role_type"],
                    "gender": rec["gender"],
                    "faction": rec["faction"],
                    "identity": rec["identity"],
                    "status": rec["status"],
                    "current_goal": rec["core_goal"],
                    "aliases": rec["aliases"] or [],
                    "must_remember": [
                        x for x in [
                            f"身份：{rec['identity']}" if rec.get("identity") else None,
                            f"阵营：{rec['faction']}" if rec.get("faction") else None,
                            f"状态：{rec['status']}" if rec.get("status") else None,
                        ] if x
                    ],
                    "state_snapshot": {
                        "chapter": sprops.get("chapter"),
                        "physical_state": sprops.get("physical_state"),
                        "mental_state": sprops.get("mental_state"),
                        "relation_summary": sprops.get("relation_summary"),
                        "unresolved_goals": sprops.get("unresolved_goals"),
                    },
                }
            )

        # Prefer semantic relations (RELATES_TO); fallback to interaction stats
        semrels = session.run(
            """
            MATCH (a:Character)-[r:RELATES_TO]->(b:Character)
            WHERE r.updated_at_chapter IS NULL OR r.updated_at_chapter >= $minCh
            RETURN a.id AS a, a.label AS aname, b.id AS b, b.label AS bname,
                   r.type AS type, r.status AS status, r.since_chapter AS since_chapter,
                   r.updated_at_chapter AS updated_at_chapter, r.evidence AS evidence
            """,
            minCh=min(chapter_set) if chapter_set else 0,
        )
        for rec in semrels:
            relationships.append(
                {
                    "subject_id": rec["a"],
                    "subject": rec["aname"],
                    "predicate": rec["type"] or "关系",
                    "object_id": rec["b"],
                    "object": rec["bname"],
                    "source_chapters": [
                        str(x) for x in [
                            rec["since_chapter"],
                            rec["updated_at_chapter"],
                        ] if isinstance(x, int)
                    ],
                    "desc": rec["status"] or rec["evidence"] or "",
                }
            )

        # Interactions within target chapters (stats layer)
        rels = session.run(
            """
            MATCH (a:Character)-[r:INTERACTED_WITH]->(b:Character)
            WHERE any(ch IN coalesce(r.chapters, []) WHERE ch IN $chapters)
            RETURN a.id AS a, a.label AS aname, b.id AS b, b.label AS bname, r.chapters AS chs
            """,
            chapters=chapters,
        )
        for rec in rels:
            relationships.append(
                {
                    "subject_id": rec["a"],
                    "subject": rec["aname"],
                    "predicate": "互动",
                    "object_id": rec["b"],
                    "object": rec["bname"],
                    "source_chapters": [str(ch) for ch in sorted(set(rec["chs"] or []) & chapter_set)],
                    "desc": "",
                }
            )

        # Timeline events in range
        evs = session.run(
            """
            MATCH (e:Event)
            WHERE e.chapter IN $chapters
            RETURN e.id AS id, e.label AS label, e.chapter AS ch, e.event_type AS et, e.date_label AS dl, e.is_major AS mj
            """,
            chapters=chapters,
        )
        for rec in evs:
            timeline.append(
                {
                    "id": rec["id"],
                    "title": rec["label"],
                    "chapter": rec["ch"],
                    "event_type": rec["et"] or "Chapter",
                    "date_label": rec["dl"],
                    "is_major": bool(rec["mj"]) if rec["mj"] is not None else True,
                }
            )

    global_constraints = {
        "world_rules": [],
        "timeline_now": f"至第{max(chapter_set) if chapter_set else 0}章",
        "forbidden_conflicts": [
            "已死亡角色不可在后续章节复活（除非设定有超自然解释）",
            "主角性别/角色类型不可变",
        ],
    }

    return {
        "global_constraints": global_constraints,
        "characters": characters_out,
        "relationships": relationships,
        "timeline": timeline,
        "entities_index": entities,
        "name_to_id": name_to_id,
    }


def compute_anchor_chapters(driver: Driver, window_chapters: List[int], max_extra: int | None = None) -> List[int]:
    """
    自动发现应补充的“关键早期章”（anchors），用于避免长线伏笔断裂。
    规则（启发式，取并集去重）：
    1) 窗口内出现过的人物的 first_chapter
    2) 这些人物之间的关系（RELATES_TO）的 since_chapter
    3) 这些人物参与过的“重要事件”（e.is_major）中的最早章节
    可用 max_extra 限制最多补充的数量（按章节号从小到大截断）。
    """
    if not window_chapters:
        return []

    min_ch = min(window_chapters)
    anchors: Set[int] = set()

    with driver.session() as session:
        # 取窗口内出现过的人物
        chars = session.run(
            """
            MATCH (c:Character)-[:PARTICIPATED_IN]->(e:Event)
            WHERE e.chapter IN $chs
            RETURN DISTINCT c.id AS id, coalesce(c.first_chapter, 0) AS fc
            """,
            chs=window_chapters,
        )
        character_ids: List[str] = []
        for rec in chars:
            character_ids.append(rec["id"])
            if isinstance(rec["fc"], int) and rec["fc"] and rec["fc"] < min_ch:
                anchors.add(rec["fc"])

        # 取这些人物的长期关系的 since_chapter
        if character_ids:
            rels = session.run(
                """
                MATCH (a:Character)-[r:RELATES_TO]->(b:Character)
                WHERE a.id IN $ids OR b.id IN $ids
                RETURN DISTINCT coalesce(r.since_chapter, 0) AS sc
                """,
                ids=character_ids,
            )
            for rec in rels:
                sc = rec["sc"]
                if isinstance(sc, int) and sc and sc < min_ch:
                    anchors.add(sc)

            # 这些人物参与过的重要事件中，更早的章节
            evs = session.run(
                """
                MATCH (c:Character)-[:PARTICIPATED_IN]->(e:Event)
                WHERE c.id IN $ids AND coalesce(e.is_major, true) = true
                RETURN min(e.chapter) AS earliest_major
                """,
                ids=character_ids,
            ).single()
            earliest_major = evs["earliest_major"] if evs else None
            if isinstance(earliest_major, int) and earliest_major and earliest_major < min_ch:
                anchors.add(earliest_major)

    # 去除已在窗口内的章
    anchors = anchors.difference(set(window_chapters))
    out = sorted(anchors)
    if isinstance(max_extra, int) and max_extra >= 0:
        out = out[:max_extra]
    return out


def main():
    parser = argparse.ArgumentParser(description="Export Neo4j subgraph for v2 generation context.")
    parser.add_argument("--chapters", type=str, required=True, help="Comma-separated chapter numbers, e.g. 11,12,13")
    parser.add_argument("--out", type=str, required=True, help="Output JSON path")
    parser.add_argument("--lookback", type=int, default=0, help="Append N chapters before the min of --chapters")
    parser.add_argument("--auto-anchors", action="store_true", help="Auto include early anchor chapters inferred from characters/relations/events")
    parser.add_argument("--max-auto-anchors", type=int, default=10, help="Limit count of auto anchors (0 means no limit)")
    args = parser.parse_args()

    chs = [int(x) for x in args.chapters.split(",") if x.strip().isdigit()]
    chs = sorted(set(chs))

    # lookback：在窗口左侧自动回溯 N 章
    if args.lookback and chs:
        m = min(chs)
        lb = list(range(max(1, m - args.lookback), m))
        chs = sorted(set(chs) | set(lb))

    driver = get_neo4j_driver()
    try:
        # auto-anchors：基于人物/关系/重要事件自动补充关键早期章
        if args.auto_anchors and chs:
            limit = None if args.max_auto_anchors == 0 else max(0, args.max_auto_anchors)
            extra = compute_anchor_chapters(driver, chs, max_extra=limit)
            if extra:
                chs = sorted(set(chs) | set(extra))

        ctx = fetch_context(driver, chs)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(ctx, f, ensure_ascii=False, indent=2)
        print(f"Exported context to {args.out}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()


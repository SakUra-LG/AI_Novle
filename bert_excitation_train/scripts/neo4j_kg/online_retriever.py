#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在线检索器（Neo4j）：按章节与角色上下文，动态检索相关事实，生成限长摘要供 V2 正文使用。

用法（应用层调用）:
    from .online_retriever import retrieve_context_for_chapter
    text = retrieve_context_for_chapter(chapter_num=12, allowed_roles=["沈清欢", "陆景明"], main_opponent="陆景明")
"""
from __future__ import annotations

from typing import List, Optional

from .common import get_neo4j_driver


def _safe_join(items: List[str], sep: str = "；", limit: int = 6) -> str:
    chunk = [str(x).strip() for x in items if str(x or "").strip()]
    if limit and len(chunk) > limit:
        chunk = chunk[:limit]
    return sep.join(chunk)


def _truncate(text: str, max_chars: int) -> str:
    s = (text or "").strip()
    if max_chars <= 0:
        return s
    return s[:max_chars]


def retrieve_context_for_chapter(
    chapter_num: int,
    allowed_roles: Optional[List[str]] = None,
    main_opponent: Optional[str] = None,
    max_chars: int = 1000,
) -> str:
    """
    面向生成端的高层接口：
    - 基于“本章允许重点出现的角色名单 + 章号上限”检索 KG 子图；
    - 汇总为简短卡片文本，控制长度，避免覆盖章节执行卡的剧情决策权。
    """
    allowed_roles = [r for r in (allowed_roles or []) if str(r or "").strip()]
    with get_neo4j_driver() as driver:  # type: ignore[call-arg]
        with driver.session() as session:
            # 人物与关系（至今为止）
            rel_rows = session.run(
                """
                MATCH (a:Character)-[r:RELATES_TO]->(b:Character)
                WHERE (coalesce(r.since_chapter, 99999) <= $ch)
                  AND (
                        size($names) = 0
                        OR a.name IN $names OR b.name IN $names
                      )
                RETURN DISTINCT a.name AS a, b.name AS b, coalesce(r.type,'关系') AS type,
                       coalesce(r.since_chapter, 0) AS since_chapter
                ORDER BY since_chapter ASC
                LIMIT 120
                """,
                ch=int(chapter_num),
                names=allowed_roles,
            ).data()

            # 涉及人物的重要事件（至今为止）
            ev_rows = session.run(
                """
                MATCH (c:Character)-[:PARTICIPATED_IN]->(e:Event)
                WHERE e.chapter <= $ch
                  AND (size($names)=0 OR c.name IN $names)
                RETURN DISTINCT c.name AS who, coalesce(e.title, e.type) AS what,
                       coalesce(e.chapter, 0) AS ch, coalesce(e.importance, 1.0) AS imp,
                       coalesce(e.is_major, true) AS major
                ORDER BY major DESC, imp DESC, ch ASC
                LIMIT 150
                """,
                ch=int(chapter_num),
                names=allowed_roles,
            ).data()

    # 汇总为“百科卡片”式文本（只做背景提示，避免喧宾夺主）
    rel_lines: List[str] = []
    for r in rel_rows:
        a, b, t, sc = r.get("a", ""), r.get("b", ""), r.get("type", ""), r.get("since_chapter", 0)
        if a and b:
            rel_lines.append(f"- {a} 与 {b}：{t}（建立于第{int(sc)}章前后）")

    ev_lines: List[str] = []
    for e in ev_rows:
        who, what, ch, major = e.get("who", ""), e.get("what", ""), e.get("ch", 0), bool(e.get("major", True))
        mark = "★" if major else "·"
        if who and what:
            ev_lines.append(f"{mark} 第{int(ch)}章：{who} - {what}")

    head = ["【知识图谱/背景事实（仅作背景，不得改任务卡）】"]
    if main_opponent:
        head.append(f"- 本章主要对手：{main_opponent}")
    if allowed_roles:
        head.append(f"- 重点相关角色：{_safe_join(allowed_roles, '、', limit=8)}")
    if rel_lines:
        head.append("\n[人物关系（历史）]")
        head.append(_safe_join(rel_lines, "；", limit=10))
    if ev_lines:
        head.append("\n[相关事件（至今为止）]")
        head.append(_safe_join(ev_lines, "；", limit=12))

    text = "\n".join([x for x in head if str(x or "").strip()])
    return _truncate(text, max_chars=max_chars)
*** End Patch

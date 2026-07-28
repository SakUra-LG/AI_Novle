"""Runtime V2 story contract.

The project deliberately has no permanent novel theme. A pipeline invocation
supplies the theme, background, protagonists, and optional constraints.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List


def _split_names(raw: str) -> List[str]:
    return [x.strip() for x in re.split(r"[,，、;；\n]", raw or "") if x.strip()]


THEME_TITLE = os.getenv("V2_THEME_TITLE", "运行时故事主题")
THEME = os.getenv("V2_THEME", "待定")
BACKGROUND = os.getenv("V2_BACKGROUND", "待定")
PROTAGONISTS = _split_names(os.getenv("V2_PROTAGONISTS", "")) or ["主角"]
MAIN_PROTAGONIST = PROTAGONISTS[0]
CORE_PREMISE = os.getenv("V2_CORE_PREMISE", "围绕事件簇持续推进，已发生事实不得被后续章节无解释地改写。")
EXTRA_CONSTRAINTS = os.getenv("V2_EXTRA_CONSTRAINTS", "").strip()
if EXTRA_CONSTRAINTS:
    CORE_PREMISE += f" 本次附加要求：{EXTRA_CONSTRAINTS}"
TIMELINE_ANCHORS: List[str] = []
ASSET_AND_CONFLICT_ANCHORS: List[str] = []
FINAL_PAYOFF = "终局必须回收已建立的核心矛盾、人物关系与未决剧情线。"
HARD_CONSTRAINTS = [
    "不得在没有叙事过渡或解释的情况下改变人物身份、关系、生命状态、地点、阵营、目标或持有物。",
    "不得让后续章节依赖从未发生的前置事件，也不得把尚未发生的情节计划写成既成事实。",
    "回忆、梦境、前世和当前时间线必须明确区分，历史状态不得覆盖当前状态。",
    "新增核心人物、规则或终局反派必须提前铺垫；未决剧情线应推进或回收。",
]
FORBIDDEN_ELEMENTS = [
    "无铺垫的系统或万能外挂",
    "神秘人突然递交唯一关键证据",
    "匿名消息直接解决核心矛盾",
    "未规划的终极反派",
]


def configure_theme_contract(
    theme: str,
    background: str,
    protagonists: List[str] | None = None,
    extra_constraints: str = "",
) -> None:
    """Configure this process before prompts or artifacts are built."""
    global THEME_TITLE, THEME, BACKGROUND, PROTAGONISTS, MAIN_PROTAGONIST, CORE_PREMISE, EXTRA_CONSTRAINTS
    THEME = str(theme or "待定").strip() or "待定"
    THEME_TITLE = THEME
    BACKGROUND = str(background or "待定").strip() or "待定"
    PROTAGONISTS = [str(x).strip() for x in (protagonists or []) if str(x).strip()] or ["主角"]
    MAIN_PROTAGONIST = PROTAGONISTS[0]
    EXTRA_CONSTRAINTS = extra_constraints.strip()
    CORE_PREMISE = f"围绕“{THEME}”持续推进；背景为“{BACKGROUND}”。"
    if EXTRA_CONSTRAINTS:
        CORE_PREMISE += f" 本次附加要求：{EXTRA_CONSTRAINTS}"


def constraints_text() -> str:
    lines = [
        f"【本次主题】{THEME}",
        f"【本次背景】{BACKGROUND}",
        f"【主角】{'、'.join(PROTAGONISTS)}",
        f"【核心设定】{CORE_PREMISE}",
        f"【终局要求】{FINAL_PAYOFF}",
        "【跨章节硬约束】" + "；".join(HARD_CONSTRAINTS),
        "【禁止捷径】" + "；".join(FORBIDDEN_ELEMENTS),
    ]
    return "\n".join(lines)


def chapter_constraint_contract(chapter: int) -> Dict[str, Any]:
    """Turn explicit per-chapter runtime requirements into checkable fields."""
    matches = list(re.finditer(r"第\s*(\d+)\s*章", EXTRA_CONSTRAINTS))
    clauses: List[str] = []
    for index, match in enumerate(matches):
        if int(match.group(1)) != int(chapter):
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(EXTRA_CONSTRAINTS)
        clause = EXTRA_CONSTRAINTS[match.start():end].strip(" \t\r\n。；;")
        if clause:
            clauses.append(clause)

    required_state_changes: List[Dict[str, Any]] = []
    forbidden_active_characters: List[str] = []
    for clause in clauses:
        sentences = [x for x in re.split(r"(?<=[。！？!?；;])", clause) if x.strip()]
        for sentence in sentences:
            current_timeline = "当前时间线" in sentence or "今生" in sentence
            inactive_markers = ("不能在当前时间线", "不得在当前时间线", "禁止在当前时间线")
            for name in PROTAGONISTS:
                if name not in sentence:
                    continue
                if current_timeline and any(marker in sentence for marker in ("死亡", "去世", "身亡", "dead")):
                    required_state_changes.append({
                        "character": name,
                        "field": "life_status",
                        "new_value": "dead",
                        "timeline": "current",
                        "permanent": True,
                    })
                if any(marker in sentence for marker in inactive_markers) and any(
                    marker in sentence for marker in ("只能通过", "只能以", "不得说话", "不能说话", "参与行动")
                ):
                    forbidden_active_characters.append(name)

    return {
        "chapter_hard_constraints": clauses,
        "required_state_changes": required_state_changes,
        "forbidden_active_characters": list(dict.fromkeys(forbidden_active_characters)),
    }


def attach_theme_contract(obj: Dict[str, Any]) -> Dict[str, Any]:
    obj["theme_contract"] = {
        "theme_title": THEME_TITLE,
        "theme": THEME,
        "background": BACKGROUND,
        "main_protagonist": MAIN_PROTAGONIST,
        "protagonists": list(PROTAGONISTS),
        "core_premise": CORE_PREMISE,
        "extra_constraints": EXTRA_CONSTRAINTS,
        "timeline_anchors": list(TIMELINE_ANCHORS),
        "hard_constraints": list(HARD_CONSTRAINTS),
        "forbidden_elements": list(FORBIDDEN_ELEMENTS),
        "final_payoff": FINAL_PAYOFF,
    }
    try:
        chapter = int(obj.get("chapter_id", 0) or 0)
    except (TypeError, ValueError):
        chapter = 0
    if chapter > 0:
        obj.update(chapter_constraint_contract(chapter))
    return obj


def protagonists_arg() -> str:
    return ",".join(PROTAGONISTS)

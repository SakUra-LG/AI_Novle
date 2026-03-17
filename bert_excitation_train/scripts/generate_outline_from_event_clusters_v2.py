#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于 V2 事件簇的章节卡生成脚本。

职责：
1）读取 outputs/event_clusters_v2.json（含 structure_template）；
2）按事件簇与模版 M1~M5，为每个章节分配章节角色（chapter_role_v2）；
3）生成轻量级章节卡 JSON（面向正文脚本使用），不再向模型请求详细梗概；
4）基于章节卡和简要拼接的“上一世前提”，生成上一世线索文件 prev_life_ctx_v2.txt。
"""

import os
import json
from datetime import datetime
from typing import List, Dict, Any

from generate_outline_rebirth_revenge import (  # type: ignore[import]
    build_prev_life_outline_system_prompt,
    analyze_outline_for_prev_life,
    build_prev_life_batch_user_query,
)
from generate_event_clusters_v2 import OUTPUT_DIR as OUTPUT_DIR_V2  # type: ignore[import]
from generate_event_clusters_v2 import generate_global_seed_plan_v2  # reuse if needed


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "outputs")


def _load_event_clusters_v2() -> List[Dict[str, Any]]:
    """读取 V2 事件簇文件。优先稳定文件 event_clusters_v2.json。"""
    stable = os.path.join(OUTPUT_DIR_V2, "event_clusters_v2.json")
    if os.path.exists(stable):
        path = stable
    else:
        # 兜底：尝试老文件 event_clusters.json
        path = os.path.join(OUTPUT_DIR_V2, "event_clusters.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"未找到事件簇文件：{path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("事件簇文件格式错误：顶层必须是数组")
    return data


def _assign_roles_for_cluster(cluster: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    为单个事件簇内的章节分配章节角色（V2）。

    返回形式：
    [
        {"chapter_id": 6, "cluster_id": "EC02", "chapter_role_v2": "present_setup", ...},
        ...
    ]
    """
    span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters")
    try:
        start, end = int(span[0]), int(span[1])
    except Exception:  # noqa: BLE001
        return []
    length = max(1, end - start + 1)
    tmpl = cluster.get("structure_template") or "M1"

    cid = cluster.get("cluster_id", "")
    roles: List[Dict[str, Any]] = []

    def add(ch: int, role: str) -> None:
        roles.append(
            {
                "chapter_id": ch,
                "cluster_id": cid,
                "chapter_role_v2": role,
            }
        )

    # 模版映射逻辑
    if tmpl == "M1":
        # 三段式：背景/上一世/今世反击
        if length == 1:
            add(start, "present_setup_and_revenge")
        elif length == 2:
            add(start, "present_setup")
            add(end, "present_revenge")
        else:
            add(start, "present_setup")
            mid = start + 1
            if mid < end:
                add(mid, "prev_life_full")
                for ch in range(mid + 1, end):
                    add(ch, "present_mid_bridge")
            add(end, "present_revenge")
    elif tmpl == "M2":
        # 快切式：两章一组，今世+上一世交错 → 反击收尾
        for idx, ch in enumerate(range(start, end + 1)):
            if idx % 2 == 0:
                add(ch, "present_past_mix")
            else:
                add(ch, "present_revenge")
    elif tmpl == "M3":
        # 慢烧式：多铺压迫，反击推后
        for i, ch in enumerate(range(start, end + 1)):
            if i == 0:
                add(ch, "slow_burn_press")
            elif i == 1:
                add(ch, "slow_burn_press_with_past_shadow")
            elif i == length - 1:
                add(ch, "partial_revenge")
            else:
                add(ch, "slow_burn_mid")
    elif tmpl == "M4":
        # 回溯式：先看行动/结果，再补真相
        for i, ch in enumerate(range(start, end + 1)):
            if i == 0:
                add(ch, "present_action_or_result_first")
            elif i == 1:
                add(ch, "prev_life_explained_by_investigation")
            else:
                add(ch, "aftermath_or_next_seed")
    elif tmpl == "M5":
        # 旁支式：以关系/情感/副线为主
        for ch in range(start, end + 1):
            add(ch, "side_plot_focus")
    else:
        # 未知模版，退化为简单 present_only
        for ch in range(start, end + 1):
            add(ch, "present_only")

    return roles


def _merge_roles_for_all_clusters(clusters: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """
    将所有事件簇的章节角色合并成 chapter_id -> 信息 的字典。
    若某章同时被多个簇覆盖，暂时按“后覆盖”策略（后续可按需要改为合并）。
    """
    mapping: Dict[int, Dict[str, Any]] = {}
    for c in clusters:
        roles = _assign_roles_for_cluster(c)
        for item in roles:
            ch = int(item["chapter_id"])
            # 将簇信息一并挂进去，便于正文脚本读取
            merged = {
                "chapter_id": ch,
                "cluster_id": item.get("cluster_id", ""),
                "chapter_role_v2": item.get("chapter_role_v2", "present_only"),
                "structure_template": c.get("structure_template", "M1"),
                "arc_id": c.get("arc_id", "A01"),
                "core_payoff": c.get("core_payoff", ""),
                "main_opponent": c.get("main_opponent", ""),
                "prev_life_tragedy": c.get("prev_life_tragedy", ""),
                "this_life_revenge": c.get("this_life_revenge", ""),
                "cluster_outcome": c.get("cluster_outcome", ""),
                "cluster_name": c.get("name", ""),
                "escalation_level": c.get("escalation_level", 1),
            }
            mapping[ch] = merged
    return mapping


def _render_cards_to_outline_text(cards: List[Dict[str, Any]]) -> str:
    """
    将 V2 章节卡渲染为极简文本梗概，供上一世分析与人工快速浏览。
    不追求细致剧情，只点出每章职责。
    """
    lines: List[str] = []
    for ch in sorted(cards, key=lambda x: x.get("chapter_id", 0)):
        cid = ch.get("cluster_id", "")
        role = ch.get("chapter_role_v2", "")
        name = ch.get("cluster_name", "")
        payoff = ch.get("core_payoff", "")
        chapter_id = ch.get("chapter_id", 0)
        role_str = f"（{role}）" if role else ""
        line = (
            f"第{chapter_id}章{role_str}：围绕事件簇 {cid}《{name}》展开，核心爽点={payoff}"
        )
        lines.append(line)
    return "\n".join(lines)


def generate_outline_from_event_clusters_v2() -> None:
    """
    主入口：基于 V2 事件簇，直接生成结构化章节卡（不再让模型写细节梗概）。

    输出：
    - master_ctx_cards_v2.json：结构化章节卡（面向正文脚本）；
    - master_ctx_v2.txt：极简文本梗概，仅为人眼和上一世分析提供上下文；
    - prev_life_ctx_v2.txt：基于整本极简梗概+分析结果生成的上一世线索点。
    """
    print("=" * 60)
    print("基于 V2 事件簇生成轻量章节卡（不改写事件簇本身）")
    print("=" * 60)

    clusters = _load_event_clusters_v2()
    print(f"已读取 V2 事件簇数量：{len(clusters)} 个\n")

    chapter_map = _merge_roles_for_all_clusters(clusters)

    # 兜底：保证 1~100 都有卡，即使某些章不在任何簇中
    cards: List[Dict[str, Any]] = []
    for ch in range(1, 101):
        base = chapter_map.get(ch, {})
        card = {
            "chapter_id": ch,
            "arc_id": base.get("arc_id", "A01"),
            "cluster_id": base.get("cluster_id", ""),
            "cluster_name": base.get("cluster_name", ""),
            "structure_template": base.get("structure_template", "M1"),
            "chapter_role_v2": base.get("chapter_role_v2", "present_only"),
            "core_payoff": base.get("core_payoff", ""),
            "main_opponent": base.get("main_opponent", ""),
            "prev_life_tragedy": base.get("prev_life_tragedy", ""),
            "this_life_revenge": base.get("this_life_revenge", ""),
            "cluster_outcome": base.get("cluster_outcome", ""),
            "escalation_level": base.get("escalation_level", 1),
            # 下面字段是为兼容原章节卡结构而保留的占位/提炼字段
            "chapter_role": "present_only",
            "present_mainline": "",
            "core_conflict": "",
            "flashback_trigger": "",
            "revenge_action": "",
            "ending_hook": "",
            "global_seed_progress": "",
            "chapter_constraints": [],
            "conflict_opponent": base.get("main_opponent", ""),
            "past_trigger": "",
            "past_core_harm": base.get("prev_life_tragedy", ""),
            "present_result": base.get("cluster_outcome", ""),
            "tail_clue": "",
            "closure_type": "open",
        }
        cards.append(card)

    cards.sort(key=lambda x: x.get("chapter_id", 0))

    # 渲染极简文本梗概，用于上一世线索分析
    outline_text = _render_cards_to_outline_text(cards)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    txt_path = os.path.join(OUTPUT_DIR, f"master_ctx_v2_{ts}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(outline_text)

    cards_path = os.path.join(OUTPUT_DIR, f"master_ctx_cards_v2_{ts}.json")
    with open(cards_path, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)

    print(f"✅ 轻量章节卡 JSON 已生成：{cards_path}")
    print(f"✅ 极简文本梗概已生成：{txt_path}")

    # 生成上一世遭遇线索（沿用原有分析+分批逻辑）
    print("\n开始基于极简梗概生成上一世遭遇线索点（prev_life_ctx_v2）...\n")
    prev_life_system_prompt = build_prev_life_outline_system_prompt()
    analysis_text = analyze_outline_for_prev_life(outline_text)
    if analysis_text and not analysis_text.startswith("通义千问"):
        print("  上一世分析完成，将按批次生成线索。")
    else:
        print("  上一世分析失败，将不携带分析结果继续生成。")
        analysis_text = ""

    prev_life_parts: List[str] = []
    batch_size = 5
    for batch_idx in range(0, 100, batch_size):
        start = batch_idx + 1
        end = min(batch_idx + batch_size, 100)
        print(f"  生成上一世线索：第 {start}-{end} 章...")
        user_q = build_prev_life_batch_user_query(
            outline_text, analysis_text, start, end
        )
        messages = [
            {"role": "system", "content": prev_life_system_prompt},
            {"role": "user", "content": user_q},
        ]
        # 直接复用原脚本中的 call_qianwen_api（通过 analyze_outline_for_prev_life 内部）
        # 这里不再重复造轮子，由于 build_prev_life_batch_user_query 只负责拼 prompt。
        from generate_outline_rebirth_revenge import call_qianwen_api as _call_qw  # type: ignore[import]

        batch_out = _call_qw(messages)
        if batch_out and not batch_out.startswith("通义千问"):
            prev_life_parts.append(batch_out.strip())
        else:
            prev_life_parts.append(
                "\n".join(
                    [
                        f"第{ch}章对应线索：（生成失败，待补充）"
                        for ch in range(start, end + 1)
                    ]
                )
            )

    prev_life_text = "\n\n".join(prev_life_parts)
    prev_main = os.path.join(OUTPUT_DIR, f"prev_life_ctx_v2_{ts}.txt")
    with open(prev_main, "w", encoding="utf-8") as f:
        f.write(prev_life_text)

    print(f"✅ 上一世遭遇线索点 V2 已生成：{prev_main}")


def main() -> None:
    generate_outline_from_event_clusters_v2()


if __name__ == "__main__":
    main()


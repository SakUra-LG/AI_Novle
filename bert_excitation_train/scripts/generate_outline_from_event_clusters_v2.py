#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于 V2 事件簇的章节卡生成脚本。

职责：
1）读取 outputs/event_clusters_v2.json（不再依赖 structure_template）；
2）为每个章节生成「可执行章节任务卡」（chapter_goal / must_include / must_not_include / chapter_ending）；
3）基于本章任务卡渲染得到的整本梗概，生成上一世线索文件 prev_life_ctx_v2.txt。
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


DEFAULT_FORBIDDEN_NEW_ROLES = [
    "神秘援手", "神秘司机", "系统", "系统提示音", "苏晚晴", "黑色轿车", "神秘人", "幕后黑手",
    "更大风暴", "真正的敌人", "神秘男人", "陌生女性盟友", "未规划的关键证人",
]

# 与 generate_chapter_content_v2._build_cluster_plan 对齐：禁止调查文式天降线索
REBIRTH_FORBIDDEN_DEUS_EX = [
    "匿名邮件/匿名爆料作为关键转折",
    "加密邮箱突然跳出决定性截图或附件",
    "老员工/陌生人未经铺垫突然递来唯一关键材料",
    "靠社交媒体发帖或声明完成主线翻盘",
    "隐藏文件夹/机密会议纪要突然揭示全部真相",
]

# 第1/2章硬锁定：不让正文阶段“自由发挥”乱插调查/重生等
SPECIAL_CARDS: Dict[int, Dict[str, Any]] = {
    1: {
        "chapter_role_v2": "prev_life_death_only",
        "chapter_goal": "只写上一世病房临死前的绝境，不出现重生后的正式苏醒，也不出现任何调查/照片/身份谜团。",
        "chapter_must_include": [
            "深夜病房环境和监护仪报警",
            "求助被医护/亲人无视或敷衍",
            "陆景明与相关医护冷漠配合或敷衍安抚",
            "最后一通电话被挂断或无人接听",
        ],
        "chapter_must_not_include": [
            "重生醒来或从病床上“突然坐起”",
            "任何现代场景中的调查/线索分析",
            "照片/U盘/神秘人/系统/幕后黑手",
            "身份替换/车祸新闻/警方介入",
        ],
        "chapter_ending": "在窒息和绝望中逐渐失去意识，意识到自己要死了但还不知道会重来一次。",
        "must_resolve_this_chapter": ["上一世临死场景闭合"],
    },
    2: {
        "chapter_role_v2": "rebirth_awakening_only",
        "chapter_goal": "只写重生惊醒与确认时间回到悲剧前夜，从震惊→怀疑是梦→通过具体证据确认“真的回去了”。",
        "chapter_must_include": [
            "从上一章病房死亡记忆中惊醒",
            "发现自己回到熟悉房间/时间点",
            "通过日期、手机、亲友状态等细节确认时间回溯",
            "决定这一次不会再轻信任何人",
        ],
        "chapter_must_not_include": [
            "直播/警方/媒体报道",
            "更大势力/幕后阴谋的正式展开",
            "非法实验/身份替换/系统提示音",
            "正式举报或真正意义上的复仇行动",
        ],
        "chapter_ending": "她在确认“这不是梦”后，把第一个可疑细节记在心里，决定先沉住气观察身边所有人。",
        "must_resolve_this_chapter": ["确认回到悲剧前夜闭合"],
    },
}


def _infer_evidence_types_from_info_gap(info_gap: str) -> List[str]:
    """从 info_gap_from_prev_life 文本中尽量抽取“证据类型”（用于 must_include 约束）。"""
    text = (info_gap or "").strip()
    if not text:
        return ["本簇信息差中的具体证据或内幕"]

    t = text.replace(" ", "")
    evidences: List[str] = []

    def add(item: str) -> None:
        item = (item or "").strip()
        if not item or item in evidences:
            return
        evidences.append(item)

    # 医疗/职业场景
    if "电子签名" in t:
        add("电子签名记录")
    if "用药剂量" in t:
        add("用药剂量/电子用药记录")
    if "病历" in t:
        if "篡改" in t or "修改" in t:
            add("病历篡改/病历记录")
        else:
            add("病历记录")
    if "值班室" in t and "笔记" in t:
        add("值班室笔记")
    elif "笔记" in t:
        add("笔记")

    # 证据形态
    if "录音" in t:
        add("录音/对话录音")
    if "视频" in t:
        add("密谈视频")
    if "邮件" in t:
        add("邮件往来")
    if "转账" in t:
        add("可疑转账记录")
    if "交易记录" in t or "地下交易" in t:
        add("地下交易记录")
    if "文件编号" in t and "时间节点" in t:
        add("关键时间节点与文件编号")
    elif "文件编号" in t:
        add("文件编号")
    elif "时间节点" in t:
        add("关键时间节点")
    if "会议" in t:
        add("会议内容/纪要")
    if "接触记录" in t:
        add("接触记录/名单")
    if "证据" in t:
        add("罪行证据")

    if not evidences:
        add("本簇信息差中的具体证据或内幕")
    return evidences[:3]


def _parse_cluster_span(cluster: Dict[str, Any]) -> (int, int):
    span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters")
    if not span:
        raise ValueError("event cluster 缺少 chapter_span")
    start, end = int(span[0]), int(span[1])
    return start, end


def _build_cluster_plan(cluster: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    为单个事件簇生成「簇级执行计划」：每章 goal / must_include / must_not_include / ending / must_resolve_this_chapter
    逻辑与 V2 正文脚本保持一致，避免在不同阶段被改写。
    """
    start_ch, end_ch = _parse_cluster_span(cluster)
    length = max(1, end_ch - start_ch + 1)
    cid = cluster.get("cluster_id", "")
    main_opp = cluster.get("main_opponent", "")
    core_payoff = cluster.get("core_payoff", "")
    info_gap = (cluster.get("info_gap_from_prev_life") or "")
    outcome = cluster.get("cluster_outcome", "")
    evidence_types = _infer_evidence_types_from_info_gap(info_gap)
    required_evidence_hint = "、".join(evidence_types[:2]) if evidence_types else "本簇信息差中提到的具体证据或内幕"

    deus_forbid = REBIRTH_FORBIDDEN_DEUS_EX[:2]
    chapters_plan: Dict[str, Dict[str, Any]] = {}
    if length == 1:
        chapters_plan[str(start_ch)] = {
            "chapter_goal": f"单章内完成：完整上一世受害段落 + 今生凭记忆预判旧招并完成反击，兑现本簇爽点：{core_payoff}",
            "chapter_must_include": [
                "完整一段上一世受害（具体场景、对话、屈辱与无助，不得一句带过）",
                "今生明确写出认出旧局/记得对方会怎么出招并提前布子",
                "反击时证据/材料仅用于落锤坐实她已知的事",
                "反杀结果或处罚",
            ],
            "chapter_must_not_include": DEFAULT_FORBIDDEN_NEW_ROLES + ["新幕后黑手", "只埋钩子不兑现"] + deus_forbid,
            "chapter_ending": f"本簇结束，结果需落到：{outcome or '对手付出代价'}"[:120],
            "must_resolve_this_chapter": ["上一世受害写厚", "记忆先于证据的反击", "完成反杀并写出结果"],
        }
    elif length == 2:
        ch1, ch2 = start_ch, end_ch
        chapters_plan[str(ch1)] = {
            "chapter_goal": "完整展开上一世在本簇情境下如何被害，为下一章反杀蓄力",
            "chapter_must_include": ["上一世具体受害过程", main_opp or "主对手", "与信息差相关的细节（如笔记、记录）"],
            "chapter_must_not_include": ["无关支线角色抢戏"] + DEFAULT_FORBIDDEN_NEW_ROLES,
            "chapter_ending": "回忆收束，读者清楚本簇仇人是谁、曾如何害她",
            "must_resolve_this_chapter": ["展开上一世悲剧", "明确主对手与信息差来源"],
        }
        chapters_plan[str(ch2)] = {
            "chapter_goal": f"公开反杀完成，兑现：{core_payoff}，结果落到：{outcome or '对手付出代价'}",
            "chapter_must_include": ["当众揭穿或举报", f"证据链闭环（必须显性使用{required_evidence_hint}）", "处罚/后果/职业毁灭或舆论崩塌"],
            "chapter_must_not_include": ["只埋钩子不兑现", "更大风暴才刚开始", "新大Boss"] + DEFAULT_FORBIDDEN_NEW_ROLES,
            "chapter_ending": "本簇结束，主对手在本簇内得到应有下场",
            "must_resolve_this_chapter": ["公开反杀", "证据链显性使用", "后果落地"],
        }
    else:
        ch1, ch_last = start_ch, end_ch
        chapters_plan[str(ch1)] = {
            "chapter_goal": (
                f"旧局重现：沈清欢在与本簇主对手（{main_opp}）同场时认出上一世同一套局，并立刻提前布子；"
                f"禁止写成调查取证、到处找线索。"
            ),
            "chapter_must_include": [
                "明确写出认出旧局/记得对方会怎么出招",
                "今生提前布子的具体安排",
                f"信息差（{required_evidence_hint}）作为她已知去何处取何物的依据，而非本章才「发现线索」",
            ],
            "chapter_must_not_include": [
                "新幕后黑手",
                "追车/系统提示/无关神秘线",
                "大段展开上一世完整受害经过",
                "把本章写成调查取证文",
            ]
            + REBIRTH_FORBIDDEN_DEUS_EX
            + DEFAULT_FORBIDDEN_NEW_ROLES,
            "chapter_ending": "旧局已对上号，对方尚未察觉她已提前布子；为下一章完整展开上一世受害蓄力",
            "must_resolve_this_chapter": ["锁定主对手", "认出旧局并提前布子", "禁止调查文推进"],
        }
        chapters_plan[str(ch1 + 1)] = {
            "chapter_goal": "本簇核心：完整展开上一世受害经过，并点明今生为何能预判对方会重复旧招",
            "chapter_must_include": [
                "上一世具体受害过程（至少一段写足，不得一句带过）",
                f"{main_opp}的主观恶意与手段" if main_opp else "主对手的主观恶意与手段",
                f"与{required_evidence_hint}对应的关键细节（上一世如何被其害惨）",
                "点明今生反击主动力是记忆与预判，不是偶然发现新材料",
            ],
            "chapter_must_not_include": ["无关支线角色抢戏"] + REBIRTH_FORBIDDEN_DEUS_EX + DEFAULT_FORBIDDEN_NEW_ROLES,
            "chapter_ending": "读者清楚她为何恨、为何这一世能提前卡位",
            "must_resolve_this_chapter": ["完整上一世受害段落", "记忆与预判动机立住"],
        }
        chapters_plan[str(ch_last)] = {
            "chapter_goal": f"关键时刻反卡与结果落地：兑现本簇爽点 {core_payoff}，结局 {outcome or '职业毁灭/失去信任'}",
            "chapter_must_include": [
                "对方按旧套路/旧剧本出手或施压",
                "关键时刻反卡：当场揭穿/亮出落锤材料（材料只坐实她早已知道的事）",
                f"显性使用{required_evidence_hint}完成闭环",
                "处罚/吊销/震动或舆论反噬等具体后果",
            ],
            "chapter_must_not_include": ["只埋钩子不兑现", "真正风暴才刚开始", "新大Boss"] + DEFAULT_FORBIDDEN_NEW_ROLES,
            "chapter_ending": "本簇结束，主对手在本簇内失去信任或受到处罚",
            "must_resolve_this_chapter": ["照旧出招→反卡落锤", "后果落地"],
        }
        mid_idx = 0
        for ch in range(ch1 + 2, ch_last):
            mid_idx += 1
            if (end_ch - start_ch + 1) == 4:
                bridge_goal = (
                    "诱敌与压实：对方按旧招继续施压；沈清欢只核实或取出她上一世就知道存在的材料，"
                    "不把整章写成搜集新线索。"
                )
                bridge_must = [
                    main_opp or "主对手",
                    "对方照旧出招与她早有准备的对位",
                    f"与{required_evidence_hint}相关动作仅为核实/取出/封死退路，而非首次发现",
                ]
            else:
                if mid_idx == 1:
                    bridge_goal = "压迫升级：对方继续按旧剧本出招；她利用已布好的子逐步收紧"
                elif mid_idx == 2:
                    bridge_goal = "将记忆层面的预判落实为可落锤的动作链，逼迫对手在公开场合露出破绽"
                else:
                    bridge_goal = "反击前夜：推进到可直接公开揭穿，不再扩展新问题或新材料"
                bridge_must = [
                    main_opp or "主对手",
                    "照旧出招与提前布子的对位",
                    f"围绕{required_evidence_hint}仅做核实/补刀/封口（不换证据来源）",
                ]
            chapters_plan[str(ch)] = {
                "chapter_goal": bridge_goal,
                "chapter_must_include": bridge_must,
                "chapter_must_not_include": [
                    "新核心人物",
                    "新组织/新阴谋线",
                    "再次详细重演一整段上一世受害",
                ]
                + REBIRTH_FORBIDDEN_DEUS_EX
                + DEFAULT_FORBIDDEN_NEW_ROLES,
                "chapter_ending": "推进到下一章可直入反杀或收尾",
                "must_resolve_this_chapter": ["诱敌/压实", "禁止调查文灌水", "不扩散到其他簇"],
            }

    # cid 目前未直接用于 plan 字段，保留参数便于后续扩展
    _ = cid
    return chapters_plan


def _assign_role_v2(length: int, chapter_index: int) -> str:
    # 与 generate_chapter_content_v2.py 的逻辑保持一致
    if length == 2:
        return "prev_life_full" if chapter_index == 1 else "present_revenge"
    if chapter_index == 1:
        return "present_setup"
    if chapter_index == 2:
        return "prev_life_full"
    if chapter_index == length:
        return "present_revenge"
    return "present_mid_bridge"


def _build_cards_from_clusters_v2(clusters: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    cards: Dict[int, Dict[str, Any]] = {}

    for cluster in clusters:
        start_ch, end_ch = _parse_cluster_span(cluster)
        length = max(1, end_ch - start_ch + 1)
        cid = cluster.get("cluster_id", "")
        cname = cluster.get("name", "")
        arc_id = cluster.get("arc_id", "A01")
        main_opp = cluster.get("main_opponent", "")
        core_payoff = cluster.get("core_payoff", "")
        prev_tragedy = cluster.get("prev_life_tragedy", "")
        this_revenge = cluster.get("this_life_revenge", "")
        info_gap = cluster.get("info_gap_from_prev_life", "")
        outcome = cluster.get("cluster_outcome", "")
        escalation = cluster.get("escalation_level", 1)
        cluster_plan = cluster.get("chapter_plan") if isinstance(cluster.get("chapter_plan"), dict) else {}
        plan = _build_cluster_plan(cluster)

        for idx, ch in enumerate(range(start_ch, end_ch + 1), start=1):
            # 1）优先读取事件簇中的 chapter_plan（如果存在）
            ch_plan_from_cluster = cluster_plan.get(str(ch)) if isinstance(cluster_plan, dict) else None
            if isinstance(ch_plan_from_cluster, dict) and ch_plan_from_cluster:
                role_v2 = str(ch_plan_from_cluster.get("role", _assign_role_v2(length, idx)))
                cards[ch] = {
                    "chapter_id": ch,
                    "arc_id": arc_id,
                    "cluster_id": cid,
                    "cluster_name": cname,
                    "structure_template": "M1",
                    "chapter_role_v2": role_v2,
                    "core_payoff": core_payoff,
                    "main_opponent": main_opp,
                    "prev_life_tragedy": prev_tragedy,
                    "this_life_revenge": this_revenge,
                    "info_gap_from_prev_life": info_gap,
                    "cluster_outcome": outcome,
                    "escalation_level": escalation,
                    "cluster_span_start": start_ch,
                    "cluster_span_end": end_ch,
                    "cluster_chapter_index": idx,
                    "cluster_chapter_total": length,
                    "chapter_goal": str(ch_plan_from_cluster.get("goal", "")),
                    "chapter_must_include": ch_plan_from_cluster.get("must_include", []) or [],
                    "chapter_must_not_include": ch_plan_from_cluster.get("must_not_include", []) or [],
                    "chapter_ending": str(ch_plan_from_cluster.get("ending", "")),
                    "must_resolve_this_chapter": ch_plan_from_cluster.get("must_resolve_this_chapter", []) or [],
                    "allowed_roles": ["沈清欢", main_opp] if main_opp else ["沈清欢"],
                    "forbidden_roles": DEFAULT_FORBIDDEN_NEW_ROLES.copy(),
                }
                continue

            # 2）兜底：没有 chapter_plan 就按旧推导逻辑补齐（仍保持稳定）
            if ch in SPECIAL_CARDS:
                sc = SPECIAL_CARDS[ch]
                role_v2 = sc["chapter_role_v2"]
                ch_plan = {
                    "chapter_goal": sc["chapter_goal"],
                    "chapter_must_include": sc["chapter_must_include"],
                    "chapter_must_not_include": sc["chapter_must_not_include"],
                    "chapter_ending": sc["chapter_ending"],
                    "must_resolve_this_chapter": sc.get("must_resolve_this_chapter", []),
                }
            else:
                role_v2 = _assign_role_v2(length, idx)
                ch_plan = plan.get(str(ch), {})

            cards[ch] = {
                "chapter_id": ch,
                "arc_id": arc_id,
                "cluster_id": cid,
                "cluster_name": cname,
                # 这里不再由 event_clusters 随机分配模板；正文仍可用这个字段做写作节拍提示
                "structure_template": "M1",
                "chapter_role_v2": role_v2,
                "core_payoff": core_payoff,
                "main_opponent": main_opp,
                "prev_life_tragedy": prev_tragedy,
                "this_life_revenge": this_revenge,
                "info_gap_from_prev_life": info_gap,
                "cluster_outcome": outcome,
                "escalation_level": escalation,
                "cluster_span_start": start_ch,
                "cluster_span_end": end_ch,
                "cluster_chapter_index": idx,
                "cluster_chapter_total": length,
                "chapter_goal": ch_plan.get("chapter_goal", ""),
                "chapter_must_include": ch_plan.get("chapter_must_include", []),
                "chapter_must_not_include": ch_plan.get("chapter_must_not_include", []),
                "chapter_ending": ch_plan.get("chapter_ending", ""),
                "must_resolve_this_chapter": ch_plan.get("must_resolve_this_chapter", []),
                "allowed_roles": ["沈清欢", main_opp] if main_opp else ["沈清欢"],
                "forbidden_roles": DEFAULT_FORBIDDEN_NEW_ROLES.copy(),
            }

            _enforce_revenge_focused_constraints(cards[ch])

    # 兜底：保证 1~100 都有卡（避免正文阶段拿不到卡导致“自由发挥”）
    for ch in range(1, 101):
        if ch in cards:
            continue
        cards[ch] = {
            "chapter_id": ch,
            "arc_id": "A01",
            "cluster_id": "",
            "cluster_name": "",
            "structure_template": "M1",
            "chapter_role_v2": "present_only",
            "core_payoff": "",
            "main_opponent": "",
            "prev_life_tragedy": "",
            "this_life_revenge": "",
            "info_gap_from_prev_life": "",
            "cluster_outcome": "",
            "escalation_level": 1,
            "cluster_span_start": 0,
            "cluster_span_end": 0,
            "cluster_chapter_index": 0,
            "cluster_chapter_total": 0,
            "chapter_goal": "本章为过渡或兜底，不得引入新的核心人物/阴谋线。",
            "chapter_must_include": [],
            "chapter_must_not_include": DEFAULT_FORBIDDEN_NEW_ROLES.copy(),
            "chapter_ending": "本章以与前文承接的一幕结束。",
            "must_resolve_this_chapter": ["不引入新主线"],
            "allowed_roles": ["沈清欢"],
            "forbidden_roles": DEFAULT_FORBIDDEN_NEW_ROLES.copy(),
        }
        _enforce_revenge_focused_constraints(cards[ch])

    return cards


def _enforce_revenge_focused_constraints(card: Dict[str, Any]) -> None:
    """
    统一约束：除 prev_life_full 章节外，不允许详细重演上一世情节；
    强化“信息差驱动今生反击”的主线，降低重复回忆风险。
    """
    role = str(card.get("chapter_role_v2", "") or "")
    must_not = card.get("chapter_must_not_include")
    if not isinstance(must_not, list):
        must_not = []

    if role != "prev_life_full":
        if "详细重演上一世完整受害过程" not in must_not:
            must_not.append("详细重演上一世完整受害过程")
        if "整章大篇幅上一世回忆喧宾夺主" not in must_not:
            must_not.append("整章大篇幅上一世回忆喧宾夺主")
    card["chapter_must_not_include"] = must_not

    must_in = card.get("chapter_must_include")
    if not isinstance(must_in, list):
        must_in = []
    if "今生利用信息差推进反击动作（可被读者明确识别）" not in must_in:
        must_in.append("今生利用信息差推进反击动作（可被读者明确识别）")
    card["chapter_must_include"] = must_in


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
                # 新增：记录这一簇中“上一世带来的信息差”，为今世反击提供依据
                "info_gap_from_prev_life": c.get("info_gap_from_prev_life", ""),
                "cluster_outcome": c.get("cluster_outcome", ""),
                "cluster_name": c.get("name", ""),
                "escalation_level": c.get("escalation_level", 1),
            }
            mapping[ch] = merged
    return mapping


def _render_cards_to_outline_text(cards: List[Dict[str, Any]]) -> str:
    """
    将每章「执行任务卡」渲染为整本梗概文本，供上一世线索分析。
    不需要完整剧情，但必须包含：目标 + 必须包含（缩短）+ 必须避免（缩短）+ 结尾落点。
    """
    lines: List[str] = []
    for ch in sorted(cards, key=lambda x: x.get("chapter_id", 0)):
        chapter_id = ch.get("chapter_id", 0)
        role = ch.get("chapter_role_v2", "")
        goal = (ch.get("chapter_goal") or "").strip()
        must_in = ch.get("chapter_must_include", []) or []
        must_not = ch.get("chapter_must_not_include", []) or []
        end = (ch.get("chapter_ending") or "").strip()
        must_in_short = "；".join(must_in[:2]) if isinstance(must_in, list) else ""
        must_not_short = "；".join(must_not[:2]) if isinstance(must_not, list) else ""
        lines.append(
            f"第{chapter_id}章（{role}）：目标={goal}｜必须包含={must_in_short}｜禁止包含={must_not_short}｜结尾={end}"
        )
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

    # 生成「可执行章节任务卡」：将职责固定在章节卡阶段，而不是正文阶段二次编剧情
    cards_map = _build_cards_from_clusters_v2(clusters)
    cards: List[Dict[str, Any]] = [cards_map[i] for i in range(1, 101) if i in cards_map]
    cards.sort(key=lambda x: x.get("chapter_id", 0))

    outline_text = _render_cards_to_outline_text(cards)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 稳定引用文件（正文脚本默认读取）
    txt_path_stable = os.path.join(OUTPUT_DIR, "master_ctx_v2.txt")
    cards_path_stable = os.path.join(OUTPUT_DIR, "master_ctx_cards_v2.json")
    prev_life_main_path_stable = os.path.join(OUTPUT_DIR, "prev_life_ctx_v2.txt")

    with open(txt_path_stable, "w", encoding="utf-8") as f:
        f.write(outline_text)
    with open(cards_path_stable, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)

    # 额外写一份时间戳备份，便于回溯对比
    txt_path = os.path.join(OUTPUT_DIR, f"master_ctx_v2_{ts}.txt")
    cards_path = os.path.join(OUTPUT_DIR, f"master_ctx_cards_v2_{ts}.json")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(outline_text)
    with open(cards_path, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)

    print(f"✅ 执行章节卡 JSON 已生成：{cards_path_stable}")
    print(f"✅ 执行梗概文本已生成：{txt_path_stable}")

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

    # 写入稳定文件：给 V2 正文脚本默认读取
    with open(prev_life_main_path_stable, "w", encoding="utf-8") as f:
        f.write(prev_life_text)

    print(f"✅ 上一世遭遇线索点 V2 已生成：{prev_life_main_path_stable}")


def main() -> None:
    generate_outline_from_event_clusters_v2()


if __name__ == "__main__":
    main()


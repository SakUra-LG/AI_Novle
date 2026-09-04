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
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bert_excitation_train.scripts.novel_generation_v2.outline_backend import (  # type: ignore[import]
    build_prev_life_outline_system_prompt,
    analyze_outline_for_prev_life,
    build_prev_life_batch_user_query,
)
from bert_excitation_train.scripts.novel_generation_v2.generate_event_clusters_v2 import OUTPUT_DIR as OUTPUT_DIR_V2  # type: ignore[import]
from bert_excitation_train.scripts.novel_generation_v2.generate_event_clusters_v2 import generate_global_seed_plan_v2  # reuse if needed
from bert_excitation_train.scripts.novel_generation_v2.theme_constraints import (
    FORBIDDEN_ELEMENTS as THEME_FORBIDDEN_ELEMENTS,
    MAIN_PROTAGONIST,
    attach_theme_contract,
    constraints_text,
)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = str(_PROJECT_ROOT)
OUTPUT_DIR = os.getenv("V2_OUTPUT_DIR", os.path.join(PROJECT_ROOT, "outputs"))


DEFAULT_FORBIDDEN_NEW_ROLES = [
    "神秘援手", "神秘司机", "系统", "系统提示音", "苏晚晴", "黑色轿车", "神秘人", "幕后黑手",
    "更大风暴", "真正的敌人", "神秘男人", "陌生女性盟友", "未规划的关键证人",
] + THEME_FORBIDDEN_ELEMENTS

# 与 generate_chapter_content_v2._build_cluster_plan 对齐：禁止调查文式天降线索
REBIRTH_FORBIDDEN_DEUS_EX = [
    "匿名邮件/匿名爆料作为关键转折",
    "加密邮箱突然跳出决定性截图或附件",
    "老员工/陌生人未经铺垫突然递来唯一关键材料",
    "靠社交媒体发帖或声明完成主线翻盘",
    "隐藏文件夹/机密会议纪要突然揭示全部真相",
]

# 第1/2章只锁结构职责，具体题材由运行时主题契约提供。
SPECIAL_CARDS: Dict[int, Dict[str, Any]] = {
    1: {
        "chapter_role_v2": "prev_life_death_only",
        "chapter_goal": "只写旧阶段结束前的核心失败、创伤与不甘；具体身份、场景和冲突服从本次主题契约。",
        "chapter_must_include": [
            "主角在旧阶段的具体身份与处境",
            "造成核心失败的具体人物、事件和选择",
            "主角未能保护或完成的重要目标",
            "生命结束前足以推动后续行动的强烈不甘",
            "上一世死亡必须作为场景结果明确发生",
        ],
        "chapter_must_not_include": [
            "重生醒来或从病床上“突然坐起”",
            "任何新阶段的正式行动",
            "提前写试镜翻盘、签约、揭露或任何今生胜利",
            "照片/U盘/神秘人/系统/幕后黑手",
            "与本次主题契约冲突的题材或世界观",
        ],
        "chapter_ending": "以主角上一世生命明确结束和一个尚未兑现的核心愿望收束。",
        "must_resolve_this_chapter": ["上一世死亡场景闭合"],
    },
    2: {
        "chapter_role_v2": "rebirth_awakening_only",
        "chapter_goal": "只写进入新阶段后的醒来与处境确认，从震惊、怀疑到通过具体证据确认时间、地点和身份。",
        "chapter_must_include": [
            "从上一章死亡与嘲笑记忆中惊醒",
            "通过环境、身体、日期或他人反应发现异常",
            "用多个符合本次背景的细节确认当前时间与身份",
            "形成与核心失败直接相关的初步目标",
            "在结尾执行一个不完成大反杀、但会改变下一章局面的第一步行动",
        ],
        "chapter_must_not_include": [
            "直播/警方/媒体报道",
            "权贵阴谋的正式展开",
            "非法实验/身份替换/系统提示音",
            "尚未确认处境便立刻完成核心反击",
        ],
        "chapter_ending": "主角确认新处境，并在最后一个场景实际完成第一步部署，而非只在心里发誓。",
        "must_resolve_this_chapter": ["确认回到悲剧前夜闭合", "第一步主动部署已经发生"],
    },
}


def _primary_protagonist(obj: Dict[str, Any] | None = None) -> str:
    if isinstance(obj, dict):
        ps = obj.get("user_protagonists")
        if isinstance(ps, list) and ps:
            return str(ps[0]) or MAIN_PROTAGONIST
    return MAIN_PROTAGONIST


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
    if "美元" in t or "脱锚" in t or "金本位" in t:
        add("美元脱锚/金价与汇率记录")
    if "通胀" in t or "CPI" in t or "物价" in t:
        add("通胀/CPI与物价数据")
    if "石油" in t or "能源" in t:
        add("石油供给/能源合同记录")
    if "固定利率" in t or "贷款" in t or "债务" in t:
        add("固定利率贷款与债务结构")
    if "铁路" in t or "货运" in t or "仓库" in t or "物流" in t:
        add("铁路货运/仓储合同")
    if "农地" in t or "农场" in t:
        add("农地与实物资产交易记录")
    if "股市" in t or "成长股" in t or "漂亮股票" in t or "基金" in t:
        add("股票持仓/基金交易记录")
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
    protagonist = _primary_protagonist(cluster)
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
                "当前阶段明确写出识别旧局或风险模式并提前行动",
                "证据或结果仅用于坐实已铺垫的判断与行动",
                "反杀结果或处罚",
            ],
            "chapter_must_not_include": DEFAULT_FORBIDDEN_NEW_ROLES + ["新幕后黑手", "只埋钩子不兑现"] + deus_forbid,
            "chapter_ending": f"本簇结束，结果需落到：{outcome or '对手付出代价'}"[:120],
            "must_resolve_this_chapter": ["上一世受害写厚", "记忆先于证据的反击", "完成反杀并写出结果"],
        }
    elif length == 2:
        ch1, ch2 = start_ch, end_ch
        chapters_plan[str(ch1)] = {
            "chapter_goal": "今生冲突立刻发生；用一个聚焦闪回解释主角为何认出旧招，随后马上抢先行动并赢得小优势",
            "chapter_must_include": ["短而具体的上一世受挫场景", main_opp or "主对手", "主角凭记忆提前行动", "对手失算与主角的小收益"],
            "chapter_must_not_include": ["无关支线角色抢戏"] + DEFAULT_FORBIDDEN_NEW_ROLES,
            "chapter_ending": "先落定本章小胜利，再让既有对手当场作出下一步反应",
            "must_resolve_this_chapter": ["明确主对手与信息差来源", "章内小反杀已经兑现"],
        }
        chapters_plan[str(ch2)] = {
            "chapter_goal": f"公开反杀完成，兑现：{core_payoff}，结果落到：{outcome or '对手付出代价'}",
            "chapter_must_include": [
                "在同一场职业冲突中完成反卡",
                f"利用前世记住的{required_evidence_hint}提前布置，并让可验证结果在今生现场自然产生",
                "有权决定者当场确认对手现实损失与主角现实收益",
            ],
            "chapter_must_not_include": ["只埋钩子不兑现", "更大风暴才刚开始", "新大Boss"] + DEFAULT_FORBIDDEN_NEW_ROLES,
            "chapter_ending": "本簇结束，主对手在本簇内得到应有下场",
            "must_resolve_this_chapter": ["同场反卡", "今生因果闭环", "双向现实结果落地"],
        }
    else:
        ch1, ch_last = start_ch, end_ch
        chapters_plan[str(ch1)] = {
            "chapter_goal": (
                f"旧局重现：{protagonist}在与本簇主对手（{main_opp}）同场时认出已经建立的风险或关系模式，并立刻行动；"
                f"禁止靠天降线索推进，必须写成符合人物知识与能力的判断和执行。"
            ),
            "chapter_must_include": [
                "明确写出识别旧局或风险的心理与既有依据",
                "当前阶段提前布局的具体安排",
                f"信息差（{required_evidence_hint}）作为既有判断依据，而非本章才偶然发现",
                "本章内让对手至少一次失算，并写出主角获得的具体机会、资源、信任或主动权",
            ],
            "chapter_must_not_include": [
                "新幕后黑手",
                "追车/系统提示/无关神秘线",
                "大段展开上一世完整受害经过",
                "把本章写成调查取证文",
            ]
            + REBIRTH_FORBIDDEN_DEUS_EX
            + DEFAULT_FORBIDDEN_NEW_ROLES,
            "chapter_ending": "旧局已对上号，主角的第一步已经改变局面；用既有对手的下一步动作承接下一章",
            "must_resolve_this_chapter": ["锁定主对手", "认出旧局并提前布子", "完成一个章内小胜利", "禁止调查文推进"],
        }
        chapters_plan[str(ch1 + 1)] = {
            "chapter_goal": "在今生冲突中插入一段聚焦的上一世受害回忆，点明为何能预判旧招，并在回到今生后立刻完成一次反制",
            "chapter_must_include": [
                "上一世具体受害过程（聚焦一个场景，不得一句带过，也不得超过全章约四分之一）",
                f"{main_opp}的主观恶意与手段" if main_opp else "主对手的主观恶意与手段",
                f"与{required_evidence_hint}对应的记忆锚点（只作为预判依据，不得凭空变成今生可播放或可提交的物证）",
                "点明今生反击主动力是记忆与预判，不是偶然发现新材料",
                "闪回结束后主角立即行动，让对手当章失算一次",
            ],
            "chapter_must_not_include": ["无关支线角色抢戏"] + REBIRTH_FORBIDDEN_DEUS_EX + DEFAULT_FORBIDDEN_NEW_ROLES,
            "chapter_ending": "记忆解释完即回到今生，落定一次小反制并接住下一场既有冲突",
            "must_resolve_this_chapter": ["聚焦上一世受害段落", "记忆与预判动机立住", "章内小反制已经发生"],
        }
        chapters_plan[str(ch_last)] = {
            "chapter_goal": f"关键时刻反卡与结果落地：兑现本簇爽点 {core_payoff}，结局 {outcome or '职业毁灭/失去信任'}",
            "chapter_must_include": [
                "对方按旧套路/旧剧本出手或施压",
                "关键时刻用符合本次题材且已提前铺垫的行动或当前时间线现场结果落锤",
                f"把前世记住的{required_evidence_hint}转化为今生提前布置，而不是还原成前世物证",
                "符合本次题材的具体代价与收益：对手失去角色、资源、职位、名誉、信任或利益，主角拿回机会、筹码或话语权",
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
                    f"诱敌与压实：对方按既定认知继续施压；{protagonist}执行已经铺垫且符合人物能力的步骤，"
                    "不把整章写成搜集新线索。"
                )
                bridge_must = [
                    main_opp or "主对手",
                    "对方照旧误判/施压与他早有准备的对位",
                    f"与{required_evidence_hint}相关动作仅为核实/取出/封死退路，而非首次发现",
                ]
            else:
                if mid_idx == 1:
                    bridge_goal = "压迫升级：对方继续按既定认知误判或施压；主角利用已布好的筹码逐步收紧"
                elif mid_idx == 2:
                    bridge_goal = "将记忆层面的预判落实为可落锤的动作链，逼迫对手在公开场合露出破绽"
                else:
                    bridge_goal = "反击前夜：推进到可直接公开揭穿，不再扩展新问题或新材料"
                bridge_must = [
                    main_opp or "主对手",
                    "照旧出招与提前布子的对位",
                    f"围绕{required_evidence_hint}仅做核实/补刀/封口（不换证据来源）",
                ]
            bridge_must.append("本章必须完成一个小反杀：对手当场失算并付出小代价，主角获得可见收益或主动权")
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
                "chapter_ending": "先落定本章小胜利，再由既有对手的直接反应推进到下一章反杀或收尾",
                "must_resolve_this_chapter": ["诱敌/压实", "章内小反杀已经兑现", "禁止调查文灌水", "不扩散到其他簇"],
            }

    # cid 目前未直接用于 plan 字段，保留参数便于后续扩展
    _ = cid
    return chapters_plan


def _assign_role_v2(length: int, chapter_index: int) -> str:
    # 与 generate_chapter_content_v2.py 的逻辑保持一致
    if length == 1:
        return "present_setup_and_revenge"
    if length == 2:
        return "present_past_mix" if chapter_index == 1 else "present_revenge"
    if chapter_index == 1:
        return "present_setup"
    if chapter_index == 2:
        return "present_past_mix"
    if chapter_index == length:
        return "present_revenge"
    return "present_mid_bridge"


def _build_cards_from_clusters_v2(clusters: List[Dict[str, Any]], total_chapters: int = 100) -> Dict[int, Dict[str, Any]]:
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
        canonical_cast = cluster.get("canonical_cast", []) or []
        planned_work_titles = cluster.get("planned_work_titles", []) or []
        protagonist = _primary_protagonist(cluster)
        allowed_roles = [
            str(member.get("name") or "").strip()
            for member in canonical_cast
            if isinstance(member, dict) and str(member.get("name") or "").strip()
        ]
        if "经纪人" in str(prev_tragedy):
            allowed_roles.extend(["旧经纪人", "经纪人"])
        allowed_roles = list(dict.fromkeys(allowed_roles or [protagonist, main_opp]))
        milestones_by_chapter: Dict[int, Dict[str, Any]] = {}
        cluster_plan = dict(cluster.get("chapter_plan")) if isinstance(cluster.get("chapter_plan"), dict) else {}
        for milestone in cluster.get("chapter_milestones") or []:
            if not isinstance(milestone, dict):
                continue
            try:
                milestone_chapter = int(milestone.get("chapter"))
            except (TypeError, ValueError):
                continue
            milestones_by_chapter[milestone_chapter] = milestone
            if milestone_chapter in (1, 2) or not (start_ch <= milestone_chapter <= end_ch):
                continue
            action = str(milestone.get("action") or "").strip()
            opponent_reaction = str(milestone.get("opponent_reaction") or "").strip()
            result = str(milestone.get("result") or "").strip()
            if not action or not result:
                continue
            milestone_role = (
                "present_revenge"
                if milestone_chapter == end_ch
                else "present_setup" if milestone_chapter == 3 else "present_mid_bridge"
            )
            cluster_plan[str(milestone_chapter)] = {
                "role": milestone_role,
                "goal": f"本章按里程碑完成主动行动并落定结果：{action}；{result}",
                "must_include": [
                    action,
                    opponent_reaction or f"{main_opp}对本章结果作出可见反应",
                    result,
                    "本章行动与结果在同一场职业冲突中形成因果闭环",
                ],
                "must_not_include": [
                    "新增有姓名人物",
                    "调查取证或媒体爆料作为主推进",
                    "重复上一章已经获得的资源",
                    "把下一章结果提前写完",
                ] + DEFAULT_FORBIDDEN_NEW_ROLES,
                "ending": f"停在本章结果已经生效及固定对手的直接反应：{result}",
                "must_resolve_this_chapter": [action, result],
            }
        plan = _build_cluster_plan(cluster)

        for idx, ch in enumerate(range(start_ch, end_ch + 1), start=1):
            chapter_milestone = milestones_by_chapter.get(ch, {})
            chapter_action = str(chapter_milestone.get("action") or "").strip()
            chapter_result = str(chapter_milestone.get("result") or "").strip()
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
                    "core_payoff": chapter_result or core_payoff,
                    "main_opponent": main_opp,
                    "prev_life_tragedy": prev_tragedy,
                    "this_life_revenge": chapter_action or this_revenge,
                    "info_gap_from_prev_life": info_gap,
                    "cluster_outcome": chapter_result or outcome,
                    "escalation_level": escalation,
                    "canonical_cast": canonical_cast,
                    "planned_work_titles": planned_work_titles,
                    "cluster_span_start": start_ch,
                    "cluster_span_end": end_ch,
                    "cluster_chapter_index": idx,
                    "cluster_chapter_total": length,
                    "chapter_goal": str(ch_plan_from_cluster.get("goal", "")),
                    "chapter_must_include": ch_plan_from_cluster.get("must_include", []) or [],
                    "chapter_must_not_include": ch_plan_from_cluster.get("must_not_include", []) or [],
                    "chapter_ending": str(ch_plan_from_cluster.get("ending", "")),
                    "must_resolve_this_chapter": ch_plan_from_cluster.get("must_resolve_this_chapter", []) or [],
                    "chapter_milestone": chapter_milestone,
                    "allowed_roles": allowed_roles,
                    "forbidden_roles": DEFAULT_FORBIDDEN_NEW_ROLES.copy(),
                }
                attach_theme_contract(cards[ch])
                _enforce_revenge_focused_constraints(cards[ch])
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
                "core_payoff": chapter_result or core_payoff,
                "main_opponent": main_opp,
                "prev_life_tragedy": prev_tragedy,
                "this_life_revenge": chapter_action or this_revenge,
                "info_gap_from_prev_life": info_gap,
                "cluster_outcome": chapter_result or outcome,
                "escalation_level": escalation,
                "canonical_cast": canonical_cast,
                "planned_work_titles": planned_work_titles,
                "cluster_span_start": start_ch,
                "cluster_span_end": end_ch,
                "cluster_chapter_index": idx,
                "cluster_chapter_total": length,
                "chapter_goal": ch_plan.get("chapter_goal", ""),
                "chapter_must_include": ch_plan.get("chapter_must_include", []),
                "chapter_must_not_include": ch_plan.get("chapter_must_not_include", []),
                "chapter_ending": ch_plan.get("chapter_ending", ""),
                "must_resolve_this_chapter": ch_plan.get("must_resolve_this_chapter", []),
                "chapter_milestone": chapter_milestone,
                "allowed_roles": allowed_roles,
                "forbidden_roles": DEFAULT_FORBIDDEN_NEW_ROLES.copy(),
            }
            attach_theme_contract(cards[ch])

            _enforce_revenge_focused_constraints(cards[ch])

    # 兜底：保证本次范围内都有卡（避免正文阶段拿不到卡导致“自由发挥”）
    for ch in range(1, total_chapters + 1):
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
            "chapter_goal": "本章为过渡或兜底，不得引入新的核心人物或阴谋线；必须维持本次主题、背景与核心主线。",
            "chapter_must_include": [],
            "chapter_must_not_include": DEFAULT_FORBIDDEN_NEW_ROLES.copy(),
            "chapter_ending": "本章以与前文承接的一幕结束。",
            "must_resolve_this_chapter": ["不引入新主线"],
            "allowed_roles": [MAIN_PROTAGONIST],
            "forbidden_roles": DEFAULT_FORBIDDEN_NEW_ROLES.copy(),
        }
        attach_theme_contract(cards[ch])
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
    continuity_requirement = "当前行动必须利用已建立的信息差、人物关系或能力推进（可被读者明确识别）"
    if continuity_requirement not in must_in:
        must_in.append(continuity_requirement)
    card["chapter_must_include"] = must_in
    card["theme_constraints"] = constraints_text()
    attach_theme_contract(card)


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


def _build_grounded_short_prev_life_context(cards: List[Dict[str, Any]]) -> str:
    """Build short-novel memory hints only from accepted event-cluster facts."""
    grounded_lines: List[str] = []
    for card in cards:
        chapter_id = int(card.get("chapter_id") or 0)
        tragedy = str(card.get("prev_life_tragedy") or "").strip()
        info_gap = str(card.get("info_gap_from_prev_life") or "").strip()
        chapter_action = str(card.get("this_life_revenge") or "").strip()
        if chapter_id == 1:
            clue = tragedy
        elif chapter_id == 2:
            clue = (
                f"只承接上一章已经发生的死亡与背叛：{tragedy}；"
                f"当前时间线只执行本章既定动作：{chapter_action}"
            )
        else:
            clue = (
                f"仅可使用已建立的信息差：{info_gap}；"
                "不得新增上一世场景、人物、文件、证据或媒体事件"
            )
        grounded_lines.append(f"第{chapter_id}章对应线索：{clue}")
    return "\n".join(grounded_lines)


def generate_outline_from_event_clusters_v2(total_chapters: int = 100) -> None:
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
    cards_map = _build_cards_from_clusters_v2(clusters, total_chapters=total_chapters)
    cards: List[Dict[str, Any]] = [cards_map[i] for i in range(1, total_chapters + 1) if i in cards_map]
    cards.sort(key=lambda x: x.get("chapter_id", 0))

    outline_text = constraints_text() + "\n\n" + _render_cards_to_outline_text(cards)

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
    if total_chapters <= 12:
        prev_life_text = _build_grounded_short_prev_life_context(cards)
        prev_main = os.path.join(OUTPUT_DIR, f"prev_life_ctx_v2_{ts}.txt")
        with open(prev_main, "w", encoding="utf-8") as f:
            f.write(prev_life_text)
        with open(prev_life_main_path_stable, "w", encoding="utf-8") as f:
            f.write(prev_life_text)
        print(f"✅ 短篇上一世线索已从事件簇事实生成：{prev_life_main_path_stable}")
        return

    prev_life_system_prompt = (
        build_prev_life_outline_system_prompt()
        + "\n\n【本项目主题硬锁定】\n"
        + constraints_text()
        + "\n生成旧阶段线索时，人物身份、冲突类型和背景规则必须服从本次主题契约，不得套用其他题材模板。"
    )
    analysis_text = analyze_outline_for_prev_life(outline_text + "\n\n" + constraints_text())
    if analysis_text and not analysis_text.startswith("通义千问"):
        print("  上一世分析完成，将按批次生成线索。")
    else:
        print("  上一世分析失败，将不携带分析结果继续生成。")
        analysis_text = ""

    prev_life_parts: List[str] = []
    batch_size = 5
    for batch_idx in range(0, total_chapters, batch_size):
        start = batch_idx + 1
        end = min(batch_idx + batch_size, total_chapters)
        print(f"  生成上一世线索：第 {start}-{end} 章...")
        user_q = build_prev_life_batch_user_query(
            outline_text, analysis_text, start, end
        )
        user_q = (
            "【本项目主题硬锁定】\n"
            + constraints_text()
            + "\n\n请让下列章节的旧阶段线索服从本次主题、背景、人物身份与既有因果；"
            "不得套用其他题材的职业、冲突或世界观。\n\n"
            + user_q
        )
        messages = [
            {"role": "system", "content": prev_life_system_prompt},
            {"role": "user", "content": user_q},
        ]
        # 直接复用原脚本中的 call_qianwen_api（通过 analyze_outline_for_prev_life 内部）
        # 这里不再重复造轮子，由于 build_prev_life_batch_user_query 只负责拼 prompt。
        from bert_excitation_train.scripts.novel_generation_v2.outline_backend import call_qianwen_api as _call_qw  # type: ignore[import]

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
    import argparse

    parser = argparse.ArgumentParser(description="Generate V2 chapter cards from event clusters.")
    parser.add_argument("--total-chapters", type=int, default=100)
    args = parser.parse_args()
    generate_outline_from_event_clusters_v2(total_chapters=max(2, args.total_chapters))


if __name__ == "__main__":
    main()

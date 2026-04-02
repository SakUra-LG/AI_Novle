#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重生复仇小说正文生成器 V2

与旧版区别：
- 使用基于事件簇 V2 的轻量章节卡（master_ctx_cards_v2_*.json）；
- 每章都有明确的 chapter_role_v2 + structure_template，用于控制上一世/今世比例与节拍结构；
- 保持原 RebirthRevengeGenerator 的大部分能力（样本检索、情绪分析、知识图谱等），只重写
  「从章节卡构造 prompt / beat 卡」这一块逻辑。
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, List

from smart_sample_search import search_rebirth_samples_for_chapter

from generate_chapter_content import (  # type: ignore[import]
    RebirthRevengeGenerator,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "outputs"

# 统一的 V2 文件命名规则（硬编码稳定文件名，去掉时间戳依赖）
DEFAULT_MASTER_CARDS_V2 = OUTPUT_DIR / "master_ctx_cards_v2.json"
DEFAULT_PREV_LIFE_V2 = OUTPUT_DIR / "prev_life_ctx_v2.txt"
DEFAULT_EVENT_CLUSTERS_V2 = OUTPUT_DIR / "event_clusters_v2.json"
DEFAULT_EXPORT_V2 = OUTPUT_DIR / "export_v2.json"

# 前几章的硬编码章节卡（不依赖事件簇），用来严格锁定第 1/2 章的写法
SPECIAL_CARDS: Dict[int, Dict[str, Any]] = {
    1: {
        "chapter_role_v2": "prev_life_death_only",
        "chapter_goal": "只写上一世病房临死前的绝境，不出现重生后的正式苏醒，也不出现任何调查/照片/身份谜团。",
        "chapter_must_include": [
            "深夜病房环境和监护仪报警",
            "求助被医护/亲人无视或敷衍",
            "陆景明与相关医护冷漠配合或敷衍安抚",
            "最后一通电话被挂断或无人接听"
        ],
        "chapter_must_not_include": [
            "重生醒来或从病床上“突然坐起”",
            "任何现代场景中的调查/线索分析",
            "照片/U盘/神秘人/系统/幕后黑手",
            "身份替换/车祸新闻/警方介入"
        ],
        "chapter_ending": "在窒息和绝望中逐渐失去意识，意识到自己要死了但还不知道会重来一次。"
    },
    2: {
        "chapter_role_v2": "rebirth_awakening_only",
        "chapter_goal": "只写重生惊醒与确认时间回到悲剧前夜，从震惊→怀疑是梦→通过具体证据确认“真的回去了”。",
        "chapter_must_include": [
            "从上一章病房死亡记忆中惊醒",
            "发现自己回到熟悉房间/时间点",
            "通过日期、手机、亲友状态等细节确认时间回溯",
            "决定这一次不会再轻信任何人"
        ],
        "chapter_must_not_include": [
            "直播/警方/媒体报道",
            "更大势力/幕后阴谋的正式展开",
            "非法实验/身份替换/系统提示音",
            "正式举报或真正意义上的复仇行动"
        ],
        "chapter_ending": "她在确认“这不是梦”后，把第一个可疑细节记在心里，决定先沉住气观察身边所有人。"
    },
}


class RebirthRevengeGeneratorV2(RebirthRevengeGenerator):
    """V2：基于事件簇模版的正文生成器。"""

    def attach_online_retriever(self) -> None:
        """
        为 V2 生成流程挂载在线检索器（Neo4j）。
        生成端会优先调用 self.online_retrieve_context(chapter_num) 获取限长 KG 文本。
        """
        try:
            from neo4j_kg.online_retriever import retrieve_context_for_chapter  # type: ignore[import-not-found]
        except Exception:
            return

        def _online_retrieve(chapter_num: int) -> str:
            # 从本章卡中抽取 allowed_roles / main_opponent，作为召回条件
            card = self._get_card_for_chapter(chapter_num)
            allowed = []
            mo = None
            if isinstance(card, dict):
                raw_allowed = card.get("allowed_roles")
                if isinstance(raw_allowed, list):
                    allowed = [str(x) for x in raw_allowed if str(x or "").strip()]
                elif isinstance(raw_allowed, str) and raw_allowed.strip():
                    allowed = [raw_allowed.strip()]
                mo_raw = card.get("main_opponent")
                if isinstance(mo_raw, str) and mo_raw.strip():
                    mo = mo_raw.strip()
            # 兜底：至少包含女主
            if "沈清欢" not in allowed:
                allowed = ["沈清欢"] + allowed
            try:
                return retrieve_context_for_chapter(
                    chapter_num=chapter_num,
                    allowed_roles=allowed[:8],
                    main_opponent=mo,
                    max_chars=900,
                )
            except Exception:
                return ""

        setattr(self, "online_retrieve_context", _online_retrieve)

    def _parse_json_maybe(self, chapter_outline: str) -> Dict[str, Any]:
        """沿用原实现：尝试从 JSON 字符串解析出章节卡。"""
        import json

        try:
            data = json.loads(chapter_outline)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _get_card_for_chapter(self, chapter_num: int) -> Dict[str, Any]:
        """从 self.master_ctx 中解析出本章的结构化卡片。"""
        raw = self.master_ctx.get(chapter_num, "")
        if not raw:
            return {}
        if isinstance(raw, str):
            return self._parse_json_maybe(raw)
        if isinstance(raw, dict):
            return raw
        return {}

    def _infer_prev_life_ratio_from_role(self, role_v2: str) -> Optional[float]:
        """
        根据 V2 章节角色粗略推断上一世段落占比。
        返回 None 表示沿用旧逻辑自动判断。
        """
        if role_v2 in {"prev_life_full", "prev_life_explained_by_investigation"}:
            return 0.3  # 约 30%
        if role_v2 in {"present_past_mix", "slow_burn_press_with_past_shadow"}:
            return 0.15
        if role_v2 in {
            "present_setup",
            "present_revenge",
            "present_mid_bridge",
            "slow_burn_press",
            "slow_burn_mid",
            "partial_revenge",
            "present_action_or_result_first",
            "aftermath_or_next_seed",
            "side_plot_focus",
            "present_only",
            "present_setup_and_revenge",
        }:
            return 0.05
        return None

    # ========= 新增：调试友好的情节/章节信息输出 =========
    def debug_print_chapter_context(self, chapter_num: int) -> None:
        """
        在生成正文前，先把本情节与本章的关键信息打印出来：
        - 所属事件簇（分配到的章节范围、核心爽点、主要对手等）；
        - 本章的结构化梗概（执行卡精简版）。
        方便人工检查“情节 → 分章梗概 → 节拍卡 → 正文”的完整链路。
        """
        card = self._get_card_for_chapter(chapter_num)
        if not card:
            print(f"\n[提示] 未在章节卡中找到第{chapter_num}章的信息。")
            return

        cluster_id = card.get("cluster_id", "")
        cluster_name = card.get("cluster_name", "")
        core_payoff = card.get("core_payoff", "")
        main_opp = card.get("main_opponent", "")
        prev_tragedy = card.get("prev_life_tragedy", "")
        this_revenge = card.get("this_life_revenge", "")
        info_gap = card.get("info_gap_from_prev_life", "")
        outcome = card.get("cluster_outcome", "")

        clusters = getattr(self, "event_clusters_v2", None)
        span_desc = ""
        if isinstance(clusters, list) and cluster_id:
            for c in clusters:
                if c.get("cluster_id") == cluster_id:
                    span = c.get("chapter_span") or c.get("chapterRange") or c.get("chapters")
                    try:
                        s, e = int(span[0]), int(span[1])
                        span_desc = f"{s}-{e}"
                    except Exception:
                        span_desc = ""
                    break

        print("\n" + "-" * 70)
        print(f"📌 本情节信息（第{chapter_num}章）")
        if cluster_id:
            print(f"  事件簇: {cluster_id}《{cluster_name}》  覆盖章节: {span_desc or '未知'}")
            print(f"  核心爽点: {core_payoff or '（未提供）'}")
            print(f"  主要对手: {main_opp or '（未指定）'}")
            print(f"  上一世悲剧前提: {prev_tragedy or '（未提供）'}")
            print(f"  今生反击方式: {this_revenge or '（未提供）'}")
            if info_gap:
                print(f"  上一世留下的信息差: {info_gap}")
            print(f"  本簇今生结局: {outcome or '（未提供）'}")
        else:
            print("  本章未绑定到具体事件簇（cluster_id 为空），将按章节卡梗概直接生成。")

        # 输出本章的结构化梗概，便于对照后续节拍卡和正文
        try:
            # 复用基类的渲染逻辑，将 JSON 卡转换成「执行卡」文本
            outline_text = self._render_master_card_for_prompt(card)  # type: ignore[attr-defined]
        except Exception:
            outline_text = ""
        if outline_text:
            print("\n🧩 本章执行梗概（结构化）：")
            print(outline_text)
        print("-" * 70 + "\n")

    def _sanitize_prompt_text(self, text: str) -> str:
        """用于特殊章节 prompt gate：移除特定触发词，降低模型跑偏风险。"""
        if not text:
            return ""
        # 只对“第1章临死绝境/类似写法”做极端门禁时使用
        forbidden_substrings = ["重生", "调查", "照片", "身份替换", "警方介入", "回到过去", "第二次人生"]
        out = text
        for w in forbidden_substrings:
            out = out.replace(w, "")
        return out

    def build_prompt_with_beat(  # type: ignore[override]
        self,
        chapter_num: int,
        outline_corrected: str,
        outline_original: str,
        prev_chapter_full: Optional[str],
        beat_card: str,
        prev_life_clue: Optional[str],
        kg_context: str = "",
        prev_tail_scene: str = "",
        prev_unresolved_hook: str = "",
        open_from_prev: str = "",
        end_to_next: str = "",
        emotion_reinforcement_points: str = "",
        rag_samples: Optional[Dict[str, List]] = None,
        need_prev_life: bool = False,
        chapter_type: str = "",
        closure_type: str = "full_close",
        flashback_breakpoint_hint: str = "",
        past_ratio_min: float = 0.20,
        past_ratio_max: float = 0.32,
        global_seed_progress: str = "",
        chapter_constraints: Optional[List[str]] = None,
    ) -> str:
        """
        V2 严格执行 prompt（硬卡优先），不复用 super().build_prompt_with_beat() 的“旧底座节拍/闭合写法”。

        优先级永远是：章节执行卡 > 上一世线索 > 连续性 > 风格样本
        """
        card = self._get_card_for_chapter(chapter_num)
        role_v2 = card.get("chapter_role_v2", "") if isinstance(card, dict) else ""
        is_death_only_gate = role_v2 in {"prev_life_death_only"}

        def _maybe_sanitize(s: str) -> str:
            return self._sanitize_prompt_text(s) if is_death_only_gate else s

        chapter_goal = _maybe_sanitize(str(card.get("chapter_goal", "") if isinstance(card, dict) else ""))
        must_in = card.get("chapter_must_include", []) if isinstance(card, dict) else []
        must_in = [str(x) for x in must_in] if isinstance(must_in, list) else [str(must_in)]
        must_in = [_maybe_sanitize(x) for x in must_in]

        must_not = card.get("chapter_must_not_include", []) if isinstance(card, dict) else []
        must_not = [str(x) for x in must_not] if isinstance(must_not, list) else [str(must_not)]
        must_not = [_maybe_sanitize(x) for x in must_not]

        chapter_ending = _maybe_sanitize(str(card.get("chapter_ending", "") if isinstance(card, dict) else ""))
        must_resolve = card.get("must_resolve_this_chapter", []) if isinstance(card, dict) else []
        must_resolve = [str(x) for x in must_resolve] if isinstance(must_resolve, list) else [str(must_resolve)]
        must_resolve = [_maybe_sanitize(x) for x in must_resolve]

        allowed_roles = card.get("allowed_roles", []) if isinstance(card, dict) else []
        forbidden_roles = card.get("forbidden_roles", []) if isinstance(card, dict) else []
        allowed_roles = [str(x) for x in allowed_roles] if isinstance(allowed_roles, list) else [str(allowed_roles)]
        forbidden_roles = [str(x) for x in forbidden_roles] if isinstance(forbidden_roles, list) else [str(forbidden_roles)]
        allowed_roles = [_maybe_sanitize(x) for x in allowed_roles]
        forbidden_roles = [_maybe_sanitize(x) for x in forbidden_roles]

        if prev_tail_scene or prev_unresolved_hook:
            continuity = f"{prev_tail_scene}".strip()
            if prev_unresolved_hook:
                continuity += f"｜{prev_unresolved_hook}"
        elif prev_chapter_full:
            # 只取末尾一小段用于连续性承接，防止二次改写主线
            continuity = prev_chapter_full[-350:] if len(prev_chapter_full) > 350 else prev_chapter_full
        else:
            continuity = ""
        continuity = _maybe_sanitize(continuity)

        # RAG：只当“文风/节奏参考”，禁止复用情节/证据设定
        rag_style_block = ""
        if rag_samples and any(rag_samples.get(k) for k in ("revenge", "grievance", "universal")):
            parts: List[str] = []
            for key in ("grievance", "revenge", "universal"):
                items = rag_samples.get(key) or []
                if not items:
                    continue
                s0 = items[0] if isinstance(items, list) else {}
                text = ""
                if isinstance(s0, dict):
                    text = s0.get("adapted_content") or s0.get("content") or ""
                text = text.strip()
                if text:
                    parts.append(f"[{key}] 片段节选：{_maybe_sanitize(text[:220])}...")
            if parts:
                rag_style_block = "\n".join(parts)

        # kg_context 仅作为背景事实，不能改任务卡的证据链与结果落点
        kg_block = _maybe_sanitize(kg_context) if kg_context else ""

        # 拼 prompt（确保章节执行卡是唯一剧情决策来源）
        lines: List[str] = []
        lines.append("你是重生复仇短剧作家。请严格执行【章节执行卡】并直接输出正文，不要解释，不要新增主线/新证据类型。")
        lines.append("")
        lines.append("【优先级规则】")
        lines.append("- 以【章节执行卡】为最高优先级；章节卡与其他信息冲突时，必须忽略其他信息。")
        lines.append("- 其次使用【上一世线索】（若本章承担回忆）。")
        lines.append("- 再使用【上一章衔接摘要】保证连续性。")
        lines.append("- 最后使用【风格样本参考】仅模仿语气与节奏，不得复用样本情节/证据设定。")
        lines.append("")

        lines.append("【章节执行卡（硬性）】")
        lines.append(f"- chapter_id：{chapter_num}；章节角色：{role_v2 or '（未标注）'}")
        if chapter_goal:
            lines.append(f"- 目标：{chapter_goal}")
        if must_in:
            lines.append(f"- 必须包含（优先级高）：" + "；".join(must_in[:8]))
        if must_not:
            lines.append(f"- 禁止包含（硬性）：" + "；".join(must_not[:10]))
        if must_resolve:
            lines.append(f"- 完成度门槛（必须达成）：" + "；".join(must_resolve[:8]))
        if chapter_ending:
            lines.append(f"- 结尾落点：{chapter_ending}")
        lines.append("")

        if need_prev_life and prev_life_clue:
            prev_block = _maybe_sanitize(str(prev_life_clue))
            lines.append("【上一世线索（硬性素材）】")
            lines.append(prev_block[:1200] + ("..." if len(prev_block) > 1200 else ""))
            lines.append("")
        else:
            lines.append("【上一世线索】本章不插入上一世回忆；若出现回忆片段必须只服务于本章任务清单。")
            lines.append("")

        if continuity:
            lines.append("【上一章衔接摘要（仅用于连续性，不得改写剧情任务）】")
            lines.append(continuity)
            lines.append("")

        if kg_block:
            lines.append("【知识图谱/背景事实（仅作背景，不得改任务卡的证据链与结果）】")
            lines.append(kg_block[:900])
            lines.append("")

        if rag_style_block:
            lines.append("【风格样本参考（仅模仿语气/节奏，禁止复用情节/证据设定）】")
            lines.append(rag_style_block)
            lines.append("")

        if allowed_roles:
            lines.append("【允许/禁止出场角色】")
            lines.append("- 允许重点出现：" + "、".join(allowed_roles[:6]))
            lines.append("- 禁止出现（硬性）：" + "、".join(forbidden_roles[:10] if forbidden_roles else []))
            lines.append("")

        lines.append("【写作约束】")
        lines.append("- 直接输出正文；不要章节标题，不要小标题，不要元注释。")
        lines.append("- 章节结尾必须停在【结尾落点】的具体动作/事件瞬间，不要用空洞预感型句子。")
        lines.append("- 不得新增未在任务卡中出现的新核心人物/新阴谋线/新证据类型。")
        if chapter_constraints:
            # chapter_constraints 作为额外“禁止项”兜底（不依赖旧底座）
            rules = [str(x).strip() for x in chapter_constraints if str(x).strip()]
            if rules:
                lines.append("- 本章额外限制：" + "；".join(rules[:6]))
        lines.append("")
        lines.append("请开始写正文。")

        prompt = "\n".join(lines).strip()
        if is_death_only_gate:
            # 再做一次兜底清洗，确保 prompt 中不含触发词
            prompt = self._sanitize_prompt_text(prompt)
        return prompt

    def build_prompt_with_beat_v2(
        self,
        chapter_num: int,
        chapter_outline: str,
        prev_life_clue: Optional[str],
        original_outline: Optional[str] = None,
    ) -> str:
        """
        基于 V2 章节卡 + 章节角色，构造更精细的节拍提示词。

        - 不改变原有的整体写作风格要求；
        - 只在「如何拆分当章节拍、上一世/今世比例」上增加结构信息。
        """
        base_prompt = super().build_prompt_with_beat(  # type: ignore[attr-defined]
            chapter_num, chapter_outline, prev_life_clue, original_outline
        )

        card = self._get_card_for_chapter(chapter_num)
        role_v2 = card.get("chapter_role_v2", "")
        tmpl = card.get("structure_template", "")
        cluster_id = card.get("cluster_id", "")
        cluster_name = card.get("cluster_name", "")
        core_payoff = card.get("core_payoff", "")
        main_opp = card.get("main_opponent", "")
        prev_tragedy = card.get("prev_life_tragedy", "")
        this_revenge = card.get("this_life_revenge", "")
        info_gap = card.get("info_gap_from_prev_life", "")
        outcome = card.get("cluster_outcome", "")
        span_start = card.get("cluster_span_start")
        span_end = card.get("cluster_span_end")
        cluster_idx = card.get("cluster_chapter_index")
        cluster_total = card.get("cluster_chapter_total")

        extra_lines = []
        if cluster_id:
            extra_lines.append(
                f"\n【本章对应的事件簇（V2）】\n"
                f"- 事件簇 {cluster_id}《{cluster_name}》，核心爽点：{core_payoff}；主要对手：{main_opp}。\n"
                f"- 上一世悲剧前提：{prev_tragedy}\n"
                f"- 今生在本簇中的大致反击方式：{this_revenge}\n"
                f"- 上一世留下、今生可利用的信息差：{info_gap or '（请在正文中具体写出：她知道了哪些别人不知道的内幕、漏洞、时间节点或关系网，从而能提前一步反杀）'}\n"
                f"- 本簇结束结果：{outcome}"
            )

        # 实体白名单/黑名单：锁定本簇角色，禁止长篇式扩张
        allowed = card.get("allowed_roles") or ["沈清欢", main_opp or "本簇主对手"]
        forbidden = card.get("forbidden_roles") or DEFAULT_FORBIDDEN_NEW_ROLES
        if isinstance(allowed, list):
            allowed_str = "、".join(allowed) + "、" + DEFAULT_ALLOWED_SUPPORT
        else:
            allowed_str = str(allowed)
        if isinstance(forbidden, list):
            forbidden_str = "、".join(forbidden[:12])
        else:
            forbidden_str = str(forbidden)
        extra_lines.append(
            "\n【本章允许/禁止出场角色】（硬性约束）\n"
            f"- 本章允许重点出场：{allowed_str}。\n"
            f"- 本章禁止引入的新核心角色/元素：{forbidden_str}。\n"
            "- 禁止出现“系统提示音”“神秘人”“神秘司机”“苏晚晴”等未在本簇规划中的角色或设定；证据必须来自本簇信息差（如值班室笔记、病历篡改），不得改为“神秘人送U盘/录像”。"
        )

        # 本章执行任务清单（来自簇级执行计划）
        ch_goal = card.get("chapter_goal", "")
        ch_must = card.get("chapter_must_include", [])
        ch_must_not = card.get("chapter_must_not_include", [])
        ch_ending = card.get("chapter_ending", "")
        ch_resolve = card.get("must_resolve_this_chapter", [])
        if ch_goal or ch_must or ch_resolve:
            extra_lines.append("\n【本章执行任务清单】（必须完成，否则本章视为不合格）")
            if ch_goal:
                extra_lines.append(f"- 本章目标：{ch_goal}")
            if ch_must:
                must_str = "；".join(ch_must) if isinstance(ch_must, list) else ch_must
                extra_lines.append(f"- 必须包含：{must_str}")
            if ch_must_not:
                not_str = "；".join(ch_must_not[:8]) if isinstance(ch_must_not, list) else ch_must_not
                extra_lines.append(f"- 禁止包含：{not_str}")
            if ch_ending:
                extra_lines.append(f"- 本章结尾应落到：{ch_ending}")
            if ch_resolve:
                resolve_str = "；".join(ch_resolve) if isinstance(ch_resolve, list) else ch_resolve
                extra_lines.append(f"- 本章结束后读者必须已明确：{resolve_str}")

        # 本簇完成度区间 + 强约束四条
        comp_min = card.get("cluster_completion_min")
        comp_max = card.get("cluster_completion_max")
        if isinstance(comp_min, (int, float)) and isinstance(comp_max, (int, float)):
            extra_lines.append(
                f"\n【本簇完成度】本章是本情节组第 {cluster_idx}/{cluster_total} 章，本章结束后本簇整体完成度应达到约 {int(comp_min)}%～{int(comp_max)}%。"
            )
        extra_lines.append(
            "\n【强约束：本簇闭环优先级高于长线悬念】（必须遵守）\n"
            "1. 本章若属于某事件簇的中后段，不得新增会独立展开的新核心人物、新组织、新阴谋线。\n"
            "2. 本簇完结前，禁止使用“幕后还有更大黑手”“她才发现真正的敌人另有其人”等扩世界观写法。\n"
            "3. 本簇最后一章必须先兑现本簇核心爽点（举报/揭穿/处罚/职业毁灭等），再允许留下一个极小的余波钩子。\n"
            "4. 若篇幅不足，优先删去神秘感、环境描写、追踪桥段，也必须保留证据链与反杀结果。优先级：闭环完成 > 证据链显性 > 爽点兑现 > 小说感。"
        )

        # 簇内滚动进度（若已生成前几章）
        state = getattr(self, "_cluster_internal_state", None)
        if isinstance(state, dict) and cluster_id and state.get("cluster_id") == cluster_id:
            resolved = state.get("resolved_so_far") or []
            unresolved = state.get("unresolved_must_finish") or []
            if resolved or unresolved:
                extra_lines.append("\n【本情节组内已解决/待解决】")
                if resolved:
                    extra_lines.append("- 已解决：" + "；".join(resolved[:5]))
                if unresolved:
                    extra_lines.append("- 本章或后续必须完成：" + "；".join(unresolved[:5]))

        # 重写要求（簇审查未通过时注入）
        rewrite_advice = getattr(self, "_cluster_rewrite_advice", None)
        if isinstance(rewrite_advice, list) and rewrite_advice:
            extra_lines.append("\n【重写要求】上版未通过情节组完成审查，请严格按以下修改：")
            for line in rewrite_advice[:6]:
                extra_lines.append(f"- {line}")
        elif isinstance(rewrite_advice, str) and rewrite_advice.strip():
            extra_lines.append("\n【重写要求】" + rewrite_advice.strip()[:500])

        extra_lines.append(
            f"\n【章节结构职责（V2）】\n"
            f"- 本章结构模版：{tmpl}；章节角色：{role_v2}。\n"
        )

        # 补充情节组级别的闭环与信息差使用要求
        # 情节组级别的闭环与比例要求：按“整簇”而不是按“每章”去看结构
        if isinstance(cluster_total, int) and cluster_total >= 1 and isinstance(cluster_idx, int):
            cluster_range_str = (
                f"第{span_start}-{span_end}章" if span_start and span_end else f"共 {cluster_total} 章"
            )
            extra_lines.append(
                "\n【情节组闭环与信息差使用要求】\n"
                f"- 本情节组覆盖 {cluster_range_str}，要求这几章合起来形成一个完整的小故事闭环：先让读者看清上一世在这一拨人/这一场局下是如何被害得很惨，再写明今生如何**基于上一世留下的信息差**完成反击和翻盘。\n"
                "- 整个情节组的总字数结构建议为：上一世相关内容约占 35%~50%，今世反击相关内容约占 50%~65%，其中今世反击要占大头；不是每一章都要三者齐全，而是几章合起来完成这个结构。\n"
                f"- 当前是本情节组中的第 {cluster_idx}/{cluster_total} 章，请按本章章节角色（{role_v2}）承担相应一段：有的章节以铺垫/压迫为主，有的章节集中写上一世回忆，有的章节集中写今世反击，不要在每一章里平均摊开所有元素。\n"
                "- 今生的反击动作要让旁人感到震惊和违和：他们会疑惑“她怎么会知道这些内部消息/提前踩准我们的布局”，但不能让旁人一开始就知道她重生或掌握了全部真相。\n"
                "- 请在关键桥段中显性利用 info_gap_from_prev_life 提到的那些内幕/细节作为她反击成功的核心筹码，而不是泛泛写成“她早有准备”。\n"
            )
        else:
            extra_lines.append(
                "\n【情节组闭环与信息差使用要求】\n"
                "- 每一个事件簇本质上是一个相对独立的短剧情节组，必须在其章节跨度内写完：上一世如何被这一拨人/这一场局害得很惨 + 今生如何基于上一世留下的信息差完成反击，不要把关键反击拖到别的情节组里。\n"
                "- 整个情节组的总字数结构建议为：上一世相关内容约占 35%~50%，今世反击相关内容约占 50%~65%，其中今世反击要占大头；不是每一章都要三者齐全，而是几章合起来完成这个结构。\n"
                "- 今生的反击动作要让旁人感到震惊和违和：他们会疑惑“她怎么会知道这些内部消息/提前踩准我们的布局”，但不能让旁人一开始就知道她重生或掌握了全部真相。\n"
                "- 请在关键桥段中显性利用 info_gap_from_prev_life 提到的那些内幕/细节作为她反击成功的核心筹码，而不是泛泛写成“她早有准备”。\n"
            )

        # 根据角色给出更具体的节拍建议
        role_desc = ""
        if role_v2 == "present_setup":
            role_desc = (
                "本章重点：今生铺垫与压迫，展示似曾相识的陷阱逼近；"
                "上一世内容仅用极短闪回点到即可，不能抢戏。"
            )
        elif role_v2 == "prev_life_full":
            role_desc = (
                "本章重点：完整呈现上一世在相似情境下如何被害、被压下去，"
                "用多个具体场景和对话写足屈辱感，为下一章今生反杀蓄力。"
            )
        elif role_v2 == "present_revenge":
            role_desc = (
                "本章重点：今生反击与结果，围绕本簇 core_payoff 把爽点打满，"
                "写清楚她如何利用证据与布局反转局面，以及对手具体遭遇的后果。"
            )
        elif role_v2 == "present_past_mix":
            role_desc = (
                "本章重点：今生遭遇与上一世片段交错对照，"
                "通过“重复的台词/动作/场景”触发记忆，对比她这一次的不同选择。"
            )
        elif role_v2 == "slow_burn_press":
            role_desc = (
                "本章重点：纯压迫与危机酝酿，让读者感到局面越来越糟却一时无计可施，"
                "暂时不要给太明显的反击动作。"
            )
        elif role_v2 == "slow_burn_press_with_past_shadow":
            role_desc = (
                "本章重点：在持续压迫中，通过短暂的回忆或梦境，"
                "让上一世的阴影渗入今生，强化“这一次绝不能再输”的情绪。"
            )
        elif role_v2 == "partial_revenge":
            role_desc = (
                "本章重点：完成一部分反击或小胜利，同时暴露更深层的对手或阴谋，"
                "让读者既满足又被新的钩子吊住。"
            )
        elif role_v2 == "present_action_or_result_first":
            role_desc = (
                "本章重点：从今生的行动或已发生的结果开场，"
                "让读者先看到反击或异样，再在下一章通过追查补全上一世真相。"
            )
        elif role_v2 == "prev_life_explained_by_investigation":
            role_desc = (
                "本章重点：通过调查/审问/对质等方式，逐步揭示上一世的真相，"
                "把“为什么要这么复仇”讲清楚。"
            )
        elif role_v2 == "aftermath_or_next_seed":
            role_desc = (
                "本章重点：处理本簇反击后的余波（对方反扑、舆论变化、关系裂痕），"
                "并自然埋入下一簇/更大 Boss 的线索。"
            )
        elif role_v2 == "side_plot_focus":
            role_desc = (
                "本章重点：推进情感线/家人关系/盟友站队等旁支剧情，"
                "可以少量提及复仇主线，但不要抢走情感/关系变化的镜头。"
            )
        elif role_v2 == "present_setup_and_revenge":
            role_desc = (
                "本章需要在有限篇幅内完成铺垫+反击的完整闭环，"
                "结构上可采用“快速引入冲突→短闪回→当场反杀→余波”的紧凑节奏。"
            )
        elif role_v2 == "present_mid_bridge":
            role_desc = (
                "本章主要承担承上启下的桥梁作用，"
                "让冲突从铺垫自然过渡到反击阶段，同时补充关键信息或人物立场变化。"
            )

        if role_desc:
            extra_lines.append(f"- 写作重点：{role_desc}")

        ratio = self._infer_prev_life_ratio_from_role(role_v2)
        if ratio is not None:
            extra_lines.append(
                f"- 建议上一世段落占全文比例约为 {int(ratio*100)}%，其余为今生剧情；"
                "上一世内容必须与本章今生场景一一呼应，而不是泛泛叙述。"
            )

        # 约束结尾钩子的写法：禁止空洞的“更大危险将来临”式台词，要求用具体事件收尾
        extra_lines.append(
            "\n【结尾钩子写法限制】\n"
            "- 严禁使用空洞的预感型句子作为章节结尾，例如“他隐约觉得更大的危险正在逼近”“她知道这只是更大风暴的开始”等，这类句子没有具体事件，不具备吸引力。\n"
            "- 尤其禁止出现类似“他知道，这场游戏还没有结束。”“真正的风暴，才刚刚开始。”之类只靠比喻/预感堆砌气氛的句子，一经出现请直接改写。\n"
            "- 章节结尾必须落在一个**具体、可视化的动作或事件瞬间**上，例如：\n"
            "  · 门被人猛地推开/门外突然传来急促的脚步声；\n"
            "  · 某个关键人物在她转身要走时叫住她，说出半句话；\n"
            "  · 手机震动弹出一条出乎意料的信息/通话；\n"
            "  · 她刚亮出的证据让现场某人脸色大变、话到嘴边却戛然而止。\n"
            "- 请自行设计类似的“具体动作型钩子”，让读者停在一个悬在半空的画面上，而不是停在抽象感受上。"
        )

        return base_prompt + "\n" + "\n".join(extra_lines)


# 本簇禁止引入的通用角色/元素（避免长篇连载式扩张）
DEFAULT_FORBIDDEN_NEW_ROLES = [
    "神秘援手", "神秘司机", "系统", "系统提示音", "苏晚晴", "黑色轿车", "神秘人",
    "幕后黑手", "更大风暴", "真正的敌人", "神秘男人", "陌生女性盟友", "未规划的关键证人",
]
# 本章允许出场的通用配角描述（不写死具体姓名，避免与主对手混淆）
DEFAULT_ALLOWED_SUPPORT = "医院同事、护士、主任、功能性配角"


def _infer_evidence_types_from_info_gap(info_gap: str) -> List[str]:
    """从 info_gap_from_prev_life 文本中尽量抽取“证据类型”（用于 prompt 的 must_include 约束）。

    目标：避免写死“值班室笔记/病历篡改”等固定示例，改为随簇内容变化。
    """
    text = (info_gap or "").strip()
    if not text:
        return ["本簇信息差中的具体证据或内幕"]

    t = text.replace(" ", "")
    evidences: List[str] = []

    def add(item: str) -> None:
        item = (item or "").strip()
        if not item:
            return
        if item not in evidences:
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

    # 证据形态：录音/视频/邮件/记录/交易等
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

    # fallback：至少返回一个可用的“证据类型占位”
    if not evidences:
        add("本簇信息差中的具体证据或内幕")

    return evidences[:3]


def _build_cluster_plan(cluster: Dict[str, Any]) -> Dict[str, Any]:
    """
    为单个事件簇生成「簇级执行计划」：每章 goal / must_include / must_not_include / ending，
    以及禁止新增核心角色等。用于在正文生成时作为硬性任务清单注入 prompt。
    """
    span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters")
    try:
        start_ch, end_ch = int(span[0]), int(span[1])
    except Exception:  # noqa: BLE001
        return {}
    length = max(1, end_ch - start_ch + 1)
    cid = cluster.get("cluster_id", "")
    name = cluster.get("name", "")
    main_opp = cluster.get("main_opponent", "")
    core_payoff = cluster.get("core_payoff", "")
    info_gap = (cluster.get("info_gap_from_prev_life") or "")
    outcome = cluster.get("cluster_outcome", "")

    # 从 info_gap 中抽取“必须显性使用的证据类型”（避免写死固定示例）
    evidence_types = _infer_evidence_types_from_info_gap(info_gap)
    required_evidence_hint = "、".join(evidence_types[:2]) if evidence_types else "本簇信息差中的具体证据或内幕"

    chapters_plan: Dict[str, Dict[str, Any]] = {}
    if length == 1:
        chapters_plan[str(start_ch)] = {
            "goal": f"在本章内完成背景铺垫、上一世回忆与今世反击，兑现本簇爽点：{core_payoff}",
            "must_include": ["本簇主对手" + (f"（{main_opp}）" if main_opp else ""), "与信息差相关的证据或线索", "反杀结果或处罚"],
            "must_not_include": DEFAULT_FORBIDDEN_NEW_ROLES + ["新幕后黑手", "只埋钩子不兑现"],
            "ending": f"本簇结束，结果需落到：{outcome or '对手付出代价'}"[:80],
            "must_resolve_this_chapter": ["锁定主对手", "显性使用信息差证据", "完成反杀并写出结果"],
        }
    elif length == 2:
        ch1, ch2 = start_ch, end_ch
        chapters_plan[str(ch1)] = {
            "goal": "完整展开上一世在本簇情境下如何被害，为下一章反杀蓄力",
            "must_include": ["上一世具体受害过程", main_opp or "主对手", "与信息差相关的细节（如笔记、记录）"],
            "must_not_include": ["无关支线角色抢戏"] + DEFAULT_FORBIDDEN_NEW_ROLES,
            "ending": "回忆收束，读者清楚本簇仇人是谁、曾如何害她",
            "must_resolve_this_chapter": ["展开上一世悲剧", "明确主对手与信息差来源"],
        }
        chapters_plan[str(ch2)] = {
            "goal": f"公开反杀完成，兑现：{core_payoff}，结果落到：{outcome or '对手付出代价'}",
            "must_include": ["当众揭穿或举报", "证据链闭环（必须显性使用" + required_evidence_hint + "）", "处罚/后果/职业毁灭或舆论崩塌"],
            "must_not_include": ["只埋钩子不兑现", "更大风暴才刚开始", "新大Boss"] + DEFAULT_FORBIDDEN_NEW_ROLES,
            "ending": "本簇结束，主对手在本簇内得到应有下场",
            "must_resolve_this_chapter": ["公开反杀", "证据链显性使用", "后果落地"],
        }
    else:
        # length >= 3
        ch1, ch_last = start_ch, end_ch
        chapters_plan[str(ch1)] = {
            "goal": f"今生重遇本簇主对手（{main_opp}），触发相似场景，埋下与信息差相关的线索",
            "must_include": [
                "医院/职场等本簇场景",
                main_opp + "施压或试探",
                f"沈清欢确认可追查线索（如{required_evidence_hint}）",
            ],
            "must_not_include": ["新幕后黑手", "追车/系统提示/无关神秘线"] + DEFAULT_FORBIDDEN_NEW_ROLES,
            "ending": "拿到进入关键场所的机会或发现证据位置，为下一章回忆与取证铺垫",
            "must_resolve_this_chapter": ["锁定主对手", "触发回忆线索", "发现可追查的具体线索"],
        }
        chapters_plan[str(ch1 + 1)] = {
            "goal": "完整展开上一世延误/陷害的屈辱回忆，并与今生调查对照；今生拿到硬证据",
            "must_include": [
                "上一世具体抢救失败或陷害过程",
                main_opp + "的主观恶意",
                f"与{required_evidence_hint}对应的关键细节（显性展示其内容与可追查性）",
                "今生取得证据",
            ],
            "must_not_include": ["无关支线角色抢戏"] + DEFAULT_FORBIDDEN_NEW_ROLES,
            "ending": "沈清欢今生已拿到可用的硬证据，为最后一章反杀做准备",
            "must_resolve_this_chapter": ["展开上一世悲剧", "拿到证据"],
        }
        chapters_plan[str(ch_last)] = {
            "goal": f"公开举报与反杀完成，兑现本簇爽点：{core_payoff}，结果：{outcome or '职业毁灭/失去信任'}",
            "must_include": [
                "当众揭穿/举报",
                f"证据链闭环（显性使用{required_evidence_hint}，把她知道的内幕对应到可呈交的具体证据）",
                "处罚/吊销/全院震动或舆论反噬",
            ],
            "must_not_include": ["只埋钩子不兑现", "真正风暴才刚开始", "新大Boss"] + DEFAULT_FORBIDDEN_NEW_ROLES,
            "ending": "本簇结束，主对手在本簇内失去信任或受到处罚",
            "must_resolve_this_chapter": ["公开反杀", "后果落地"],
        }
        for ch in range(ch1 + 2, ch_last):
            chapters_plan[str(ch)] = {
                "goal": "承上启下：压迫升级或取证推进，不引入新主线",
                "must_include": [
                    main_opp or "主对手",
                    f"围绕{required_evidence_hint}推进取证/对峙（不得换证据来源）",
                ],
                "must_not_include": ["新核心人物", "新组织/新阴谋线"] + DEFAULT_FORBIDDEN_NEW_ROLES,
                "ending": "推进到下一章可直入反杀或收尾",
                "must_resolve_this_chapter": ["推进证据或压迫", "不扩散到其他簇"],
            }

    return {
        "cluster_id": cid,
        "cluster_name": name,
        "must_finish_in_span": True,
        "final_payoff_chapter": end_ch,
        "forbidden_new_major_mysteries": True,
        "forbidden_new_core_roles": DEFAULT_FORBIDDEN_NEW_ROLES.copy(),
        "chapters": chapters_plan,
    }


def _build_cards_from_clusters(clusters: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """
    从事件簇列表动态构造章节卡（不依赖 master_ctx_cards_v2.json）。
    先为每个簇生成簇级执行计划，再为每章写入 role + 完成度区间 + 本章任务清单 + 实体白名单/黑名单。
    返回 chapter_id -> card 的字典。
    """
    cards: Dict[int, Dict[str, Any]] = {}
    for cluster in clusters:
        span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters")
        try:
            start_ch, end_ch = int(span[0]), int(span[1])
        except Exception:  # noqa: BLE001
            continue
        length = max(1, end_ch - start_ch + 1)
        cluster_id = cluster.get("cluster_id", "")
        cluster_name = cluster.get("name", "")
        arc_id = cluster.get("arc_id", "A01")
        core_payoff = cluster.get("core_payoff", "")
        main_opp = cluster.get("main_opponent", "")
        prev_tragedy = cluster.get("prev_life_tragedy", "")
        this_revenge = cluster.get("this_life_revenge", "")
        info_gap = cluster.get("info_gap_from_prev_life", "")
        cluster_outcome = cluster.get("cluster_outcome", "")
        escalation = cluster.get("escalation_level", 1)

        plan = _build_cluster_plan(cluster)
        plan_chapters = (plan.get("chapters") or {})

        for idx, ch in enumerate(range(start_ch, end_ch + 1)):
            chapter_index = idx + 1
            # 若为第 1/2 章，优先使用硬编码 SPECIAL_CARDS，而不是按簇自动推断职责
            special = SPECIAL_CARDS.get(ch)
            if special:
                role_v2 = special.get("chapter_role_v2", "present_only")
                tmpl = "M1"
                # 对第 1/2 章而言，只负责“死前绝境”或“重生惊醒”，不要求完成本簇闭环
                completion_min, completion_max = 0, 30
            elif length == 2:
                role_v2 = "prev_life_full" if chapter_index == 1 else "present_revenge"
                tmpl = "M1"
                completion_min = 0 if chapter_index == 1 else 50
                completion_max = 50 if chapter_index == 1 else 100
            else:
                if chapter_index == 1:
                    role_v2, tmpl = "present_setup", "M1"
                    completion_min, completion_max = 0, 30
                elif chapter_index == 2:
                    role_v2, tmpl = "prev_life_full", "M1"
                    completion_min, completion_max = 30, 70
                elif chapter_index == length:
                    role_v2, tmpl = "present_revenge", "M1"
                    completion_min, completion_max = 70, 100
                else:
                    role_v2, tmpl = "present_mid_bridge", "M3"
                    completion_min = 30 + (chapter_index - 2) * (40 // max(1, length - 2))
                    completion_max = min(70, completion_min + 40)

            ch_plan = plan_chapters.get(str(ch), {})
            # 若有 SPECIAL_CARDS，则用其 goal/must_include 等覆盖 plan 中对应字段
            if special:
                if special.get("chapter_goal"):
                    ch_plan["goal"] = special["chapter_goal"]
                if special.get("chapter_must_include"):
                    ch_plan["must_include"] = special["chapter_must_include"]
                if special.get("chapter_must_not_include"):
                    ch_plan["must_not_include"] = special["chapter_must_not_include"]
                if special.get("chapter_ending"):
                    ch_plan["ending"] = special["chapter_ending"]
            card = {
                "chapter_id": ch,
                "arc_id": arc_id,
                "cluster_id": cluster_id,
                "cluster_name": cluster_name,
                "structure_template": tmpl,
                "chapter_role_v2": role_v2,
                "core_payoff": core_payoff,
                "main_opponent": main_opp,
                "prev_life_tragedy": prev_tragedy,
                "this_life_revenge": this_revenge,
                "info_gap_from_prev_life": info_gap,
                "cluster_outcome": cluster_outcome,
                "escalation_level": escalation,
                "cluster_span_start": start_ch,
                "cluster_span_end": end_ch,
                "cluster_chapter_index": chapter_index,
                "cluster_chapter_total": length,
                "cluster_completion_min": completion_min,
                "cluster_completion_max": completion_max,
                "chapter_goal": ch_plan.get("goal", ""),
                "chapter_must_include": ch_plan.get("must_include", []),
                "chapter_must_not_include": ch_plan.get("must_not_include", []),
                "chapter_ending": ch_plan.get("ending", ""),
                "must_resolve_this_chapter": ch_plan.get("must_resolve_this_chapter", []),
                "allowed_roles": [ "沈清欢", main_opp ] if main_opp else [ "沈清欢" ],
                "forbidden_roles": list(plan.get("forbidden_new_core_roles", DEFAULT_FORBIDDEN_NEW_ROLES)),
            }
            cards[ch] = card
    return cards


def _cluster_critic(
    cluster: Dict[str, Any],
    chapter_texts: Dict[int, str],
) -> Dict[str, Any]:
    """
    簇完成审查器：检查本簇各章是否完成闭环、是否引入未规划角色、是否显性使用信息差。
    返回 payoff_completed, violations, rewrite_advice 等，用于决定是否强制重写。
    """
    span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters")
    try:
        start_ch, end_ch = int(span[0]), int(span[1])
    except Exception:  # noqa: BLE001
        return {"payoff_completed": False, "violations": ["簇章节范围无效"], "rewrite_advice": ["请检查 event_clusters_v2.json"]}
    last_ch = end_ch
    last_text = (chapter_texts.get(last_ch) or "").strip()
    full_text = " ".join(chapter_texts.get(ch, "") for ch in range(start_ch, end_ch + 1))

    violations: List[str] = []
    rewrite_advice: List[str] = []
    introduced: List[str] = []

    # 1. 最后一章是否兑现 core_payoff / cluster_outcome
    core_payoff = (cluster.get("core_payoff") or "")
    outcome = (cluster.get("cluster_outcome") or "")
    # 放宽但更全面的“结果落地”判定：接受更丰富的同义表达，且允许在最后两章内出现
    payoff_keywords = [
        "举报", "揭穿", "执照", "吊销", "职业", "毁灭", "失去信任", "处罚", "落马", "崩塌",
        "反噬", "身败名裂", "自食恶果", "停职", "罢免", "免职", "撤职", "被带走", "被调查",
        "罢黜", "开除", "通报", "曝光", "败露", "失势", "下台", "股东会通过", "接任", "接管",
    ]
    last_two = (chapter_texts.get(last_ch, "") or "") + " " + (chapter_texts.get(last_ch - 1, "") or "")
    outcome_ok = any(k in last_text for k in payoff_keywords) or any(k in last_two for k in payoff_keywords)
    # 若 core_payoff/outcome 文案明确包含结果类用词，且最后一章文本长度较充分，也视为达标
    if not outcome_ok and (any(k in core_payoff for k in ["举报", "揭穿", "吊销", "毁灭", "罢免", "停职"]) or any(k in outcome for k in payoff_keywords)) and len(last_text) > 600:
        outcome_ok = True
    if not outcome_ok and len(last_text) > 200:
        violations.append("本簇最后一章未完成反杀结果/职业毁灭/处罚落地")
        rewrite_advice.append("最后一章必须具体呈现场景化的‘结果落地’，例如宣布停职/罢免/吊销/股东会决议/被带离；不要只写“更大风暴才刚开始”。")

    # 2. 是否引入禁止角色/元素
    forbidden_check = ["系统提示音", "苏晚晴", "神秘司机", "神秘人", "黑色轿车", "神秘男人", "幕后黑手", "更大风暴", "真正的风暴"]
    for w in forbidden_check:
        if w in full_text:
            violations.append(f"正文中出现禁止元素或未规划角色：{w}")
            introduced.append(w)
    if introduced:
        rewrite_advice.append("删除或改写未在本簇规划中的新核心角色（如苏晚晴、神秘司机、系统提示等）")

    # 3. 信息差是否显性使用（本簇 info_gap 中的关键词应在正文出现）
    info_gap = (cluster.get("info_gap_from_prev_life") or "")
    if info_gap:
        # 抽几个关键词：笔记、病历、篡改、记录、计划 等
        evidence_hints = ["笔记", "病历", "篡改", "记录", "证据", "值班室", "报复", "邮件", "签名", "录音", "文件"]
        used = any(h in full_text for h in evidence_hints)
        if not used and len(full_text) > 1500:
            violations.append("本簇要求显性使用的信息差证据（如笔记/病历/记录）未在正文中出现")
            rewrite_advice.append("将证据改为本簇信息差中的具体形式（如值班室笔记、病历篡改记录），不要用“神秘人送U盘/录像”")

    # 4. 每章字数是否达标（否则即使结构/关键词对了，也不符合你的“长篇节奏”目标）
    # NOTE: 你要求的目标是“每章>=1500字”，因此这里必须按 1500 做硬性验收。
    min_chars_per_ch = 1500
    for ch in range(start_ch, end_ch + 1):
        t = (chapter_texts.get(ch) or "").strip()
        if len(t) < min_chars_per_ch:
            violations.append(f"第{ch}章字数不足（{len(t)}字）")
            rewrite_advice.append(f"第{ch}章必须扩写到不少于1500字：按 beats 逐拍展开，补足多感官描写与对话，让情绪转折更清晰，并确保信息差证据形态落地。")

    # 5. 主对手是否聚焦
    main_opp = (cluster.get("main_opponent") or "")
    if main_opp and len(main_opp) < 10 and main_opp not in full_text and len(full_text) > 1000:
        violations.append("本簇主对手未在正文中充分出现，冲突被稀释")
        rewrite_advice.append(f"确保本簇冲突围绕主对手（{main_opp}）展开，不要被其他角色抢戏")

    # 放宽完成判定：只要结果落地达标，且未出现“最后一章未完成”或“最后一章字数不足”等致命问题，即视为完成
    critical_violations = []
    for v in violations:
        if "最后一章未完成" in v:
            critical_violations.append(v)
        if "字数不足" in v and f"第{last_ch}" in v:
            critical_violations.append(v)
    payoff_completed = outcome_ok and not critical_violations
    return {
        "payoff_completed": payoff_completed,
        "used_required_info_gap": "信息差" not in str(violations),
        "introduced_new_major_roles": introduced,
        "violations": violations,
        "rewrite_advice": rewrite_advice,
    }


def _build_cluster_internal_state(
    cluster: Dict[str, Any],
    chapter_texts: Dict[int, str],
    chapters_dir: str,
) -> Dict[str, Any]:
    """根据本簇已写章节内容，生成 resolved_so_far / unresolved_must_finish，供下一章 prompt 使用。"""
    span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters")
    try:
        start_ch, end_ch = int(span[0]), int(span[1])
    except Exception:  # noqa: BLE001
        return {}
    cid = cluster.get("cluster_id", "")
    main_opp = cluster.get("main_opponent", "")
    info_gap = cluster.get("info_gap_from_prev_life", "")
    outcome = cluster.get("cluster_outcome", "")

    resolved: List[str] = []
    for ch in range(start_ch, end_ch + 1):
        text = (chapter_texts.get(ch) or "")[:600]
        if not text:
            continue
        if main_opp and main_opp in text:
            resolved.append(f"已明确本簇主对手（{main_opp}）")
        if any(k in text for k in ["笔记", "病历", "证据", "记录", "值班室"]):
            resolved.append("已出现与信息差相关的线索或证据")
        if "上一世" in text or "记得" in text:
            resolved.append("已展开或触及上一世回忆")
        if ch == end_ch and any(k in text for k in ["举报", "揭穿", "吊销", "处罚", "失去"]):
            resolved.append("本簇反杀已兑现")

    unresolved: List[str] = []
    if not any("上一世" in (chapter_texts.get(ch) or "") for ch in range(start_ch, end_ch + 1)):
        unresolved.append("展开上一世在本簇情境下的受害回忆")
    if info_gap and not any(h in " ".join(chapter_texts.values()) for h in ["笔记", "病历", "篡改", "记录", "证据"]):
        unresolved.append("显性使用信息差中的证据（如值班室笔记、病历篡改）")
    if not any(k in (chapter_texts.get(end_ch) or "") for k in ["举报", "揭穿", "吊销", "职业", "处罚", "信任"]):
        unresolved.append("最后一章必须写出反杀结果与对手下场")

    return {
        "cluster_id": cid,
        "resolved_so_far": list(dict.fromkeys(resolved)),
        "unresolved_must_finish": list(dict.fromkeys(unresolved)),
        "forbidden_expansion": DEFAULT_FORBIDDEN_NEW_ROLES.copy(),
    }


def _load_prev_life_ctx(path: str) -> Dict[int, str]:
    """从 prev_life_ctx_v2.txt 格式文件中加载 chapter_num -> 线索文本。"""
    import re
    out: Dict[int, str] = {}
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^第(\d+)章对应线索\s*[：:]\s*(.+)$", line)
        if m:
            out[int(m.group(1))] = m.group(2).strip()
    return out


def _load_master_cards_v2(path: Optional[str]) -> Dict[int, Dict[str, Any]]:
    """加载由 generate_outline_from_event_clusters_v2.py 生成的 master_ctx_cards_v2.json。"""
    if not path:
        return {}
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        out: Dict[int, Dict[str, Any]] = {}
        for item in data:
            if isinstance(item, dict) and item.get("chapter_id") is not None:
                try:
                    out[int(item["chapter_id"])] = item
                except Exception:  # noqa: BLE001
                    continue
        return out
    if isinstance(data, dict):
        # 兼容极少数情况下输出为 chapter_id -> card 的字典
        out: Dict[int, Dict[str, Any]] = {}
        for k, v in data.items():
            if isinstance(v, dict):
                try:
                    out[int(k)] = v
                except Exception:  # noqa: BLE001
                    continue
        return out
    return {}


def _setup_gen_from_cards_and_prev_life(
    gen: "RebirthRevengeGeneratorV2",
    cards: Dict[int, Dict[str, Any]],
    prev_life_ctx_path: str,
    clusters: List[Dict[str, Any]],
) -> None:
    """用内存中的章节卡和上一世线索初始化生成器，不依赖 master_ctx_cards_v2.json。"""
    gen.master_ctx = {ch: json.dumps(card, ensure_ascii=False) for ch, card in cards.items()}
    gen.master_ctx_original = {}
    gen.prev_life_ctx = _load_prev_life_ctx(prev_life_ctx_path)
    gen._extract_entities()
    setattr(gen, "event_clusters_v2", clusters)


def _extract_json_obj_maybe(text: str) -> Any:
    """
    从模型输出中尽量提取 JSON（容错：允许前后有非 JSON 文本）。
    """
    if text is None:
        return None
    s = (text or "").strip()
    if not s:
        return None
    # 1) 先尝试直接 json.loads
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        pass

    # 2) 清理常见 markdown fence（尽量不破坏括号配对）
    #    例如： ```json { ... } ```
    s2 = s.replace("```json", "```").replace("```", "")

    def _escape_newlines_in_json_strings(raw: str) -> str:
        """
        某些模型会把 JSON 字符串写成“多行字符串”（直接插入真实换行），
        这会导致 json.loads 失败；在字符串内部把换行替换为 \\n 可提高容错率。
        """
        out: List[str] = []
        in_string = False
        escape = False
        for ch in raw:
            if in_string:
                if escape:
                    out.append(ch)
                    escape = False
                    continue
                if ch == "\\":
                    out.append(ch)
                    escape = True
                    continue
                if ch == '"':
                    out.append(ch)
                    in_string = False
                    continue
                if ch == "\n":
                    out.append("\\")
                    out.append("n")
                    continue
                if ch == "\r":
                    out.append("\\")
                    out.append("n")
                    continue
                out.append(ch)
            else:
                out.append(ch)
                if ch == '"':
                    in_string = True
        return "".join(out)

    def _extract_balanced_snippet(raw: str) -> Optional[str]:
        start_obj = raw.find("{")
        start_arr = raw.find("[")
        if start_obj == -1 and start_arr == -1:
            return None

        if start_obj == -1:
            start = start_arr
            open_ch, close_ch = "[", "]"
        elif start_arr == -1:
            start = start_obj
            open_ch, close_ch = "{", "}"
        else:
            if start_obj < start_arr:
                start = start_obj
                open_ch, close_ch = "{", "}"
            else:
                start = start_arr
                open_ch, close_ch = "[", "]"

        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(raw)):
            ch = raw[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return raw[start : i + 1]
        return None

    try:
        snippet = _extract_balanced_snippet(s2)
        if not snippet:
            return None
        try:
            return json.loads(snippet)
        except Exception:  # noqa: BLE001
            # 再尝试：把字符串里的真实换行转成 \\n
            snippet2 = _escape_newlines_in_json_strings(snippet)
            return json.loads(snippet2)
    except Exception:  # noqa: BLE001
        return None


def _partition_evenly(items: List[int], parts: int) -> List[List[int]]:
    """
    将 items 切成 parts 份，尽量均匀且保持连续性。
    若 parts >= len(items)，则每份至多 1 个元素。
    """
    if parts <= 0:
        return [items]
    n = len(items)
    parts = min(parts, n) if n > 0 else 1
    if parts <= 1:
        return [items]
    out: List[List[int]] = []
    base = n // parts
    rem = n % parts
    idx = 0
    for i in range(parts):
        take = base + (1 if i < rem else 0)
        out.append(items[idx : idx + take])
        idx += take
    return out


def _chapter_constraints_for_cluster_prompt(card: Dict[str, Any]) -> str:
    """
    为“全簇节拍卡/连续正文/切分微调”提供更短的章节约束摘要。
    """
    if not isinstance(card, dict):
        return ""
    role_v2 = card.get("chapter_role_v2", "")
    chapter_goal = card.get("chapter_goal", "") or ""
    must_in = card.get("chapter_must_include", []) or []
    must_not = card.get("chapter_must_not_include", []) or []
    ending = card.get("chapter_ending", "") or ""
    must_resolve = card.get("must_resolve_this_chapter", []) or []
    allowed_roles = card.get("allowed_roles", []) or []
    forbidden_roles = card.get("forbidden_roles", []) or []

    if isinstance(must_in, list):
        must_in = [str(x) for x in must_in][:10]
    else:
        must_in = [str(must_in)][:1]
    if isinstance(must_not, list):
        must_not = [str(x) for x in must_not][:14]
    else:
        must_not = [str(must_not)][:1]
    if isinstance(must_resolve, list):
        must_resolve = [str(x) for x in must_resolve][:8]
    else:
        must_resolve = [str(must_resolve)][:1]

    if isinstance(allowed_roles, list):
        allowed_roles = [str(x) for x in allowed_roles]
    else:
        allowed_roles = [str(allowed_roles)]
    if isinstance(forbidden_roles, list):
        forbidden_roles = [str(x) for x in forbidden_roles]
    else:
        forbidden_roles = [str(forbidden_roles)]

    return (
        f"角色：{role_v2 or '（未标注）'}；目标：{chapter_goal}\n"
        f"必须包含：{'；'.join(must_in) if must_in else '（无）'}\n"
        f"必须处理：{'；'.join(must_resolve) if must_resolve else '（无）'}\n"
        f"必须避免：{'；'.join(must_not) if must_not else '（无）'}\n"
        f"章节结尾钩子：{ending or '（无）'}\n"
        f"允许角色：{'；'.join(allowed_roles[:6]) if allowed_roles else '（未指定）'}\n"
        f"禁止出现新核心角色：{'；'.join(forbidden_roles[:10]) if forbidden_roles else '（无）'}\n"
    )


def _build_cluster_detailed_synopsis_prompt(
    cluster: Dict[str, Any],
    chapter_cards: Dict[int, Dict[str, Any]],
    prev_tail_scene: str,
    prev_unresolved_hook: str,
    rewrite_advice: Optional[List[str]] = None,
) -> str:
    span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters") or []
    try:
        s, e = int(span[0]), int(span[1])
        span_desc = f"{s}-{e}"
    except Exception:  # noqa: BLE001
        span_desc = "（未知）"

    cluster_id = cluster.get("cluster_id", "")
    cluster_name = cluster.get("name", cluster.get("cluster_name", "")) or ""
    core_payoff = cluster.get("core_payoff", "") or ""
    main_opp = cluster.get("main_opponent", "") or ""
    prev_tragedy = cluster.get("prev_life_tragedy", "") or ""
    this_revenge = cluster.get("this_life_revenge", "") or ""
    info_gap = cluster.get("info_gap_from_prev_life", "") or ""
    outcome = cluster.get("cluster_outcome", "") or ""

    cross_hint = ""
    if prev_tail_scene or prev_unresolved_hook:
        cross_hint = (
            "上一章最后场景/动作（供本情节族首章开头接续）："
            + (prev_tail_scene or "（无）")
            + "\n上一章未解决钩子（必须被接住并推进到本情节族内节拍）："
            + (prev_unresolved_hook or "（无）")
            + "\n"
        )

    chapter_roles = []
    for ch, card in sorted(chapter_cards.items(), key=lambda x: x[0]):
        role_v2 = card.get("chapter_role_v2", "")
        if role_v2:
            chapter_roles.append(f"第{ch}章：{role_v2}")
    chapter_roles_text = "；".join(chapter_roles[:10]) if chapter_roles else ""

    rewrite_block = ""
    if rewrite_advice:
        rewrite_block = "\n【重写要求（必须遵守）】\n" + "\n".join(rewrite_advice[:10])

    return f"""你是重生复仇短剧/小说编剧。请基于【情节族】信息，生成一个“可直接驱动分章节拍卡与正文”的【详细完整梗概】。

要求（非常重要）：
1. 必须按时间推进写：起因→逼迫/挤压→信息差如何被识别→今生如何伪装/布局利用→关键证据/记录/病历/笔记如何呈现→对手如何失态→反杀结果与本簇结局；
2. 必须写清“上一世留下的信息差”到底是什么（要具体到证据/记录形态），以及沈清欢如何把它伪装成“对方以为安全的流程”；
3. 必须写出复仇细节爽感：反杀要落在具体动作/对话/表情/场面上，并说明“为什么有效”；
4. 必须把复仇方式和核心爽点与 `core_payoff` 对齐；
5. 禁止引入本情节族未规划的新核心人物/幕后系统/系统提示音等旁支要素。
{rewrite_block}

输出格式（按顺序输出段落，不要列表/不要编号）：
[背景]
[过程]
[信息差与利用]
[复仇细节与爽感]
[章间衔接要点]

【情节族信息】
cluster_id：{cluster_id}
cluster_name：{cluster_name}
覆盖章节：{span_desc}
核心爽点：{core_payoff}
主要对手：{main_opp}
上一世悲剧前提：{prev_tragedy}
今生反击方式：{this_revenge}
上一世留下的信息差：{info_gap}
本簇结局/落点：{outcome}

{cross_hint}
章节角色分工（便于放置回忆/反制）：{chapter_roles_text or '（未提供）'}
"""


def _build_cluster_beats_prompt(
    cluster: Dict[str, Any],
    chapter_nums: List[int],
    chapter_cards: Dict[int, Dict[str, Any]],
    cluster_synopsis: str,
    prev_tail_scene: str,
    prev_unresolved_hook: str,
    rewrite_advice: Optional[List[str]] = None,
) -> str:
    cluster_id = cluster.get("cluster_id", "") or ""
    cluster_name = cluster.get("name", cluster.get("cluster_name", "")) or ""
    main_opp = cluster.get("main_opponent", "") or ""
    core_payoff = cluster.get("core_payoff", "") or ""
    info_gap = cluster.get("info_gap_from_prev_life", "") or ""
    outcome = cluster.get("cluster_outcome", "") or ""

    cross_hint = ""
    if prev_tail_scene or prev_unresolved_hook:
        cross_hint = (
            "首章开头必须接续上一章尾钩：\n"
            f"- 上一章最后场景/动作：{prev_tail_scene or '（无）'}\n"
            f"- 上一章未解决钩子：{prev_unresolved_hook or '（无）'}\n"
        )

    rewrite_block = ""
    if rewrite_advice:
        rewrite_block = "\n【重写要求（必须遵守）】\n" + "\n".join(rewrite_advice[:10])

    cards_block_text = "\n\n".join(
        [f"【第{ch}章章节卡】\n{_chapter_constraints_for_cluster_prompt(chapter_cards.get(ch, {}))}" for ch in chapter_nums]
    )

    # 这里必须避免在 f-string 里直接写 JSON 示例（里面有大量 `{}`），否则会被 Python 误当成格式化占位符。
    beats_json_schema = """
{
  "cluster_id": "<string>",
  "cluster_name": "<string>",
  "chapters": [
    {
      "chapter_num": <int>,
      "chapter_type": "<revenge_payoff|grievance_build|present_only|cross_chapter>",
      "closure_type": "<full_close|half_close|chain_close>",
      "open_from_prev": "<string>",
      "end_to_next": "<string>",
      "beats": [
        {
          "scene_goal": "<string>",
          "visual_elements": "<string>",
          "emotion_push": "<string>",
          "info_delta": "<string>",
          "evidence_form": "<string>",
          "prev_life_memory_brief": "<string>",
          "foreshadow": "<string>",
          "relationship_push": "<string>",
          "must_not": "<string>"
        }
      ],
      "flashback_in_beat_idx": <int|null>
    }
  ]
}
""".strip("\n")

    return f"""你是短剧/小说编剧。请把【情节族梗概】进一步拆成“每章节拍卡（beats）”，以便后续连续正文生成并最终切分成章节。

要求（非常重要）：
1. 输出必须是严格 JSON（不要 Markdown，不要解释文字），且 JSON 可被直接 json.loads 解析；
   必须保证所有 JSON 字符串字段内部不得出现真实换行；若需要换行请用 \\n 表示；整份 JSON 尽量输出为一行（允许空白分隔）。
2. 对每个章节：beats 必须 8-10 条，每条为一个“结构化节拍卡对象”，按情节点顺序排列；
   每个 beats 对象必须尽量给出以下字段的具体内容（不可全空）：scene_goal / visual_elements / emotion_push / info_delta / evidence_form / foreshadow / relationship_push；must_not 至少给出 1-2 条避免项（可用简短短语）；
3. 若该章需要插入上一世回忆（根据该章 `chapter_role_v2`），则在 JSON 字段 flashback_in_beat_idx 写出对应 beats 下标（从 0 开始），并要求该 beats 对象的 `prev_life_memory_brief` 给出上一世受害回忆的具体内容要点（用于正文直接插入）；不需要则填 null 且所有 beats 的 `prev_life_memory_brief` 为空字符串；
4. chapter_type 必须从：revenge_payoff / grievance_build / present_only / cross_chapter 中二选一或多选（但每章只能给一个）；
5. closure_type 必须从：full_close / half_close / chain_close 中三选一（每章只能给一个）；
6. open_from_prev：首章必须给出“接续上一章尾钩”的具体动作/场景；非首章必须与上一章 end_to_next 的未决点强相关；
7. end_to_next：每章结尾必须留下下一章钩子（最后一章给本簇落点后的读者悬念，允许为“更大风暴延续”，但不得引入新幕后系统/系统提示音）；
8. 必须显性使用“信息差证据形态”（来自 info_gap），在 beats 的 `evidence_form` 字段里给出 2-3 次证据/记录/病历/笔记/文件被拿出来、被解释、被用于翻盘的具体动作/台词要点（至少命中 2 次）。

【情节族信息】
cluster_id：{cluster_id}
cluster_name：{cluster_name}
主要对手：{main_opp}
核心爽点：{core_payoff}
上一世信息差（用于证据呈现）：{info_gap}
本簇结局/落点：{outcome}
覆盖章节：{chapter_nums[0]}-{chapter_nums[-1]}

{cross_hint}
{rewrite_block}

【情节族详细梗概（不得偏离）】
{cluster_synopsis}

【逐章章节卡约束（必须遵守 must/must_not/结尾钩子）】
{cards_block_text}

输出 JSON 结构（仅输出此 JSON）：
{beats_json_schema}
"""


def _build_single_chapter_beats_prompt(
    cluster: Dict[str, Any],
    chapter_num: int,
    chapter_card: Dict[str, Any],
    cluster_synopsis: str,
    prev_tail_scene: str,
    prev_unresolved_hook: str,
    prev_end_to_next_seed: str,
    is_first_chapter: bool,
    is_last_chapter: bool,
    rewrite_advice: Optional[List[str]] = None,
) -> str:
    """
    单章 beats：只输出一个可 json.loads 的 JSON 对象，避免“全簇 JSON 一次性输出导致截断/解析失败”。
    """
    cluster_id = cluster.get("cluster_id", "") or ""
    cluster_name = cluster.get("name", cluster.get("cluster_name", "")) or ""
    main_opp = cluster.get("main_opponent", "") or ""
    core_payoff = cluster.get("core_payoff", "") or ""
    info_gap = cluster.get("info_gap_from_prev_life", "") or ""
    outcome = cluster.get("cluster_outcome", "") or ""

    role_v2 = chapter_card.get("chapter_role_v2", "") or ""
    cards_block_text = _chapter_constraints_for_cluster_prompt(chapter_card)
    rewrite_block = ""
    if rewrite_advice:
        rewrite_block = "\n【重写要求（必须遵守）】\n" + "\n".join(rewrite_advice[:10])

    # 与 v1/v2 现有逻辑保持一致：哪些 chapter_role_v2 需要插入“上一世回忆”
    prev_life_roles = {
        "prev_life_full",
        "prev_life_explained_by_investigation",
        "present_past_mix",
        "slow_burn_press_with_past_shadow",
    }
    need_prev_life = role_v2 in prev_life_roles

    open_seed_lines = []
    if is_first_chapter:
        open_seed_lines.append(f"上一章最后场景/动作：{prev_tail_scene or '（无）'}")
        open_seed_lines.append(f"上一章未解决钩子：{prev_unresolved_hook or '（无）'}")
    else:
        open_seed_lines.append(f"上一章 end_to_next（未决点/钩子承接种子）：{prev_end_to_next_seed or '（无）'}")

    beats_json_schema = """
{
  "chapter_num": <int>,
  "open_from_prev": "<string>",
  "end_to_next": "<string>",
  "flashback_in_beat_idx": <int|null>,
  "beats": [
    {
      "scene_goal": "<string>",
      "visual_elements": "<string>",
      "emotion_push": "<string>",
      "info_delta": "<string>",
      "evidence_form": "<string>",
      "foreshadow": "<string>",
      "relationship_push": "<string>",
      "must_not": "<string>",
      "prev_life_memory_brief": "<string>"
    }
  ]
}
""".strip("\n")

    return f"""你是重生复仇短剧/小说编剧。请为“第{chapter_num}章”输出该章的【节拍卡 beats】（只输出一个 JSON 对象）。

要求（非常重要）：
1. 输出必须是严格 JSON（不要 Markdown，不要解释文字），JSON 可被直接 json.loads 解析；
2. 必须保证所有 JSON 字符串字段内部不得出现真实换行；若需要换行请用 \\n 表示；整份 JSON 尽量输出为一行（允许空白分隔）；
3. beats 必须 8-10 条，每条为一个结构化 beats 对象，按情节点顺序排列；
4. 每个 beats 对象必须尽量给出以下字段的具体内容（不可全空）：scene_goal / visual_elements / emotion_push / info_delta / evidence_form / foreshadow / relationship_push / must_not / prev_life_memory_brief；
5. 若 need_prev_life=True，则 flashback_in_beat_idx 必须为非 null 的整数，且必须且只能在该 beats 下标对应的那一拍里给出非空 prev_life_memory_brief；其它 beats 的 prev_life_memory_brief 只能为空字符串。
   若 need_prev_life=False，则 flashback_in_beat_idx 必须为 null，并且所有 beats 的 prev_life_memory_brief 必须为空字符串；
6. open_from_prev 必须体现与上一章未决点的承接：{("；".join(open_seed_lines))};
7. end_to_next 必须为下一章钩子：如果是最后一章，则钩子必须对齐本簇落点 outcome（允许留读者悬念，但不得引入新幕后系统/系统提示音）。
8. 必须显性使用“信息差证据形态”（来自 info_gap），在 evidence_form 字段里给出至少 2 次“证据/记录/病历/笔记/文件被拿出来、被解释或被用于翻盘”的具体动作/台词要点（要求与 info_gap 对齐）。

【情节族信息（仅用于对齐）】
cluster_id：{cluster_id}
cluster_name：{cluster_name}
主要对手：{main_opp}
核心爽点：{core_payoff}
上一世信息差（用于证据呈现）：{info_gap}
本簇结局/落点：{outcome}
本章 chapter_role_v2：{role_v2}

【章节执行卡约束（必须遵守）】
{cards_block_text}

【情节族详细梗概（不得偏离）】
{cluster_synopsis}

{rewrite_block}

输出 JSON 结构（仅输出此 JSON）：
{beats_json_schema}
"""


def _build_cluster_body_part_prompt(
    cluster: Dict[str, Any],
    cluster_synopsis: str,
    chapter_num: int,
    chapter_beats: Dict[str, Any],
    prev_tail_scene: str,
    prev_unresolved_hook: str,
    chapter_card: Dict[str, Any],
    kg_context: str = "",
    rewrite_advice: Optional[List[str]] = None,
    rag_samples: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> str:
    cluster_id = cluster.get("cluster_id", "") or ""
    main_opp = cluster.get("main_opponent", "") or ""
    info_gap = cluster.get("info_gap_from_prev_life", "") or ""
    core_payoff = cluster.get("core_payoff", "") or ""

    role_v2 = chapter_card.get("chapter_role_v2", "") or ""
    must_in = chapter_card.get("chapter_must_include", []) or []
    must_not = chapter_card.get("chapter_must_not_include", []) or []
    ending = chapter_card.get("chapter_ending", "") or ""
    allowed_roles = chapter_card.get("allowed_roles", []) or []
    forbidden_roles = chapter_card.get("forbidden_roles", []) or []
    if isinstance(must_in, list):
        must_in = [str(x) for x in must_in][:8]
    if isinstance(must_not, list):
        must_not = [str(x) for x in must_not][:10]

    # 是否为本簇最后一章（用于加严结尾闭环硬性要求）
    is_last_chapter_of_cluster = False
    try:
        idx = int(chapter_card.get("cluster_chapter_index", 0) or 0)
        total = int(chapter_card.get("cluster_chapter_total", 0) or 0)
        is_last_chapter_of_cluster = total >= 1 and idx == total
    except Exception:
        is_last_chapter_of_cluster = False

    beats = chapter_beats.get("beats", []) or []
    open_from_prev = chapter_beats.get("open_from_prev", "") or ""
    end_to_next = chapter_beats.get("end_to_next", "") or ""
    flashback_idx = chapter_beats.get("flashback_in_beat_idx", None)
    chapter_type = chapter_beats.get("chapter_type", "present_only") or "present_only"
    closure_type = chapter_beats.get("closure_type", chapter_beats.get("closure_type", None)) or chapter_beats.get("closure_type", None)
    if not closure_type:
        closure_type = chapter_beats.get("closure_type", "full_close") or "full_close"
    if not closure_type:
        closure_type = "full_close"

    rewrite_block = ""
    if rewrite_advice:
        rewrite_block = "\n【重写要求（必须遵守）】\n" + "\n".join(rewrite_advice[:10])

    kg_block = f"\n【Neo4j背景事实（限长，仅作背景，禁止替换证据链与决策）】\n{kg_context}\n" if kg_context else ""

    rag_samples_block = ""
    if rag_samples:
        title_map = {
            "revenge": "重生复仇爽感",
            "grievance": "上一世委屈",
            "universal": "通用样本",
        }
        parts: List[str] = []
        for key in ("revenge", "grievance", "universal"):
            arr = rag_samples.get(key) or []
            if not isinstance(arr, list):
                continue
            for idx, sample in enumerate(arr[:2], 1):
                if not isinstance(sample, dict):
                    continue
                adapted = str(sample.get("adapted_content") or "").strip()
                adapted = adapted.replace("\n", " ")
                if adapted:
                    parts.append(
                        f"【样本{idx} - {title_map.get(key, key)}】\n{adapted[:500]}…（已截断）"
                    )
        if parts:
            rag_samples_block = (
                "\n【参考样本（仅作写作节奏与表达参考，不得原样复述/不得改写 beats 逻辑）】\n"
                + "\n\n".join(parts)
            )

    flashback_idx_0 = flashback_idx if flashback_idx is not None else None
    flashback_idx_text = "null" if flashback_idx_0 is None else str(flashback_idx_0)
    flashback_beat_1_text = "null" if flashback_idx_0 is None else str(int(flashback_idx_0) + 1)
    beats_lines: List[str] = []
    for i, b in enumerate(beats):
        if isinstance(b, dict):
            # 每拍字段会被“转写”为正文的动作/对话/环境与情绪，而不是在正文里原样复现字段名。
            prev_brief = str(b.get("prev_life_memory_brief") or "").strip()
            if flashback_idx_0 is not None and i == int(flashback_idx_0) and prev_brief:
                prev_part = f"；回忆要点：{prev_brief}"
            else:
                prev_part = ""
            line = (
                f"第{i+1}拍："
                f"目标={str(b.get('scene_goal') or '').strip()}；"
                f"画面={str(b.get('visual_elements') or '').strip()}；"
                f"情绪={str(b.get('emotion_push') or '').strip()}；"
                f"信息增量={str(b.get('info_delta') or '').strip()}；"
                f"证据形态={str(b.get('evidence_form') or '').strip()}；"
                f"伏笔={str(b.get('foreshadow') or '').strip()}；"
                f"关系推进={str(b.get('relationship_push') or '').strip()}；"
                f"禁止={str(b.get('must_not') or '').strip()}"
                f"{prev_part}"
            )
        else:
            line = f"第{i+1}拍：{str(b).strip()}"
        beats_lines.append(line)
    beats_text = "\n".join(beats_lines)
    payoff_hard_block = ""
    if is_last_chapter_of_cluster:
        # 明确把“本簇闭环写完”作为硬性落点，禁止含糊收尾
        payoff_hard_block = (
            "\n【本簇最后一章闭环（硬性要求，必须全部满足）】\n"
            "- 本章内必须写出反杀完成与具体后果：如 停职/罢免/吊销/处罚/股东会通过/失去支持/曝光败露；\n"
            "- 必须以具体、可视化的场面呈现‘结果落地’，例如：宣布决定的会议现场、盖章/签字的瞬间、对手被带离/被围观的画面；\n"
            "- 允许保留一个很小的余波钩子，但绝对禁止用“更大风暴才刚开始/真正的敌人另有其人”替代结果；\n"
            "- 若篇幅不足，优先砍掉环境/感受性描写，也要保证‘结果已发生且被看到’。"
        )

    return f"""你是重生复仇短剧作家。请输出“第{chapter_num}章”的连续正文段落。要求：

1. 必须严格按该章节拍卡 `beats` 的顺序推进，不得跳拍；
2. 开头 120-180 字必须体现 open_from_prev 指向的上一段未决点/动作承接；
3. 若 flashback_in_beat_idx = {flashback_idx_text}（从 0 开始），则在第 {flashback_beat_1_text} 拍结束后插入完整上一世受害回忆段落，回忆内容需围绕该拍卡里的“回忆要点”展开（不要加小标题，不要出现“系统提示音/重生醒来/调查”这类旁支）；若 flashback_in_beat_idx 为 null 则本章不插入上一世回忆；
4. 本章总字数要求：不少于 1500 字（建议 1700-2200 字），并且必须按 beats 分拍展开：每一拍至少写 160-220 字的正文内容，允许用自然段落分隔，但不得把多拍压缩成极短段落；未达到 1500 字时必须继续扩写，直到字数达标后再停止；
5. 必须显性呈现“信息差证据形态”：在正文中至少 2 次让读者看到证据/记录/病历/笔记/文件被拿出来、被解释或被用于翻盘，并且这些证据呈现要与 beats 的“证据形态”对齐；
6. 结尾最后 120-200 字留下 end_to_next 作为下一章钩子；
7. beats 卡里的字段名仅用于写作约束，正文中不要原样复现这些字段名；输出仅正文，不要章节标题或编号，不要解释原因，不要附带 JSON。

【情节族信息】cluster_id={cluster_id}；主要对手={main_opp}；信息差提示={info_gap}；核心爽点={core_payoff}
【本章信息】角色={role_v2 or '（未标注）'}；类型={chapter_type}；闭合={closure_type}；章节卡结尾钩子={ending or '（无）'}
【本章必须包含】{'；'.join(must_in) if must_in else '（无）'}
【本章必须避免】{'；'.join(must_not) if must_not else '（无）'}
{payoff_hard_block}

{rewrite_block}
{rag_samples_block}
{kg_block}

【上一段结尾承接（必须接住）】
最后场景：{prev_tail_scene or '（无）'}
未解决钩子：{prev_unresolved_hook or '（无）'}

【情节族详细梗概（不得偏离）】
{cluster_synopsis}

【本章拍卡（beats）】
{beats_text}
"""


def _build_cluster_split_prompt(
    cluster: Dict[str, Any],
    cluster_synopsis: str,
    full_cluster_body: str,
    chapter_nums: List[int],
    chapter_cards: Dict[int, Dict[str, Any]],
    beats_cards: List[Dict[str, Any]],
    rewrite_advice: Optional[List[str]] = None,
) -> str:
    cluster_id = cluster.get("cluster_id", "") or ""
    cluster_name = cluster.get("name", cluster.get("cluster_name", "")) or ""
    main_opp = cluster.get("main_opponent", "") or ""
    info_gap = cluster.get("info_gap_from_prev_life", "") or ""
    outcome = cluster.get("cluster_outcome", "") or ""

    rewrite_block = ""
    if rewrite_advice:
        rewrite_block = "\n【重写要求（必须遵守）】\n" + "\n".join(rewrite_advice[:10])

    cards_block_text = "\n\n".join(
        [f"【第{ch}章章节卡】\n{_chapter_constraints_for_cluster_prompt(chapter_cards.get(ch, {}))}" for ch in chapter_nums]
    )

    # 注意：下面这个“输出 JSON 结构”示例如果直接写在 f-string 里（包含大量 `{}`），
    # 会被 Python 当成格式化占位符解析，导致运行时报 `ValueError: Invalid format specifier`。
    # 因此把它先放到普通字符串变量中，再通过 `{split_output_json_schema}` 插入。
    split_output_json_schema = """
{
  "cluster_id": "<string>",
  "chapters": [
    { "chapter_num": <int>, "text": "<string：该章正文（禁止章节标题）>" }
  ]
}
""".strip("\n")

    beats_block_lines = []
    for bc in beats_cards:
        bn = bc.get("chapter_num")
        beats_block_lines.append(
            f"第{bn}章 open_from_prev={bc.get('open_from_prev','')}；end_to_next={bc.get('end_to_next','')}；flashback_idx={bc.get('flashback_in_beat_idx',None)}"
        )
    beats_block_text = "\n".join(beats_block_lines)

    return f"""你是重生复仇短剧编剧。请把【完整情节族正文】进一步切分成【严格对应章节范围】的 n 章文本，并微调每一章的开头/结尾钩子，保证衔接顺滑且约束命中。

要求（非常重要）：
1. 输出必须是严格 JSON（不要 Markdown，不要解释文字），JSON 可被直接 json.loads 解析；
2. 不要改变情节核心主线：除每章开头 100-160 字与结尾最后 120-200 字允许微调外，其余正文不得删减、不得压缩总结、不得同义重写；必须保留与原“完整情节族正文”一致的正文信息密度（以防止字数下降）；
3. 每章必须：
   - 开头 100-160 字体现 open_from_prev 指向的上一章结尾动作/未决点承接；
   - 结尾最后 120-200 字体现 end_to_next 作为下一章钩子；
   - 正文总字数不少于 1500 字（建议 1600-2200 字），不能只保留短开头与短结尾；未达到 1500 字时必须继续扩写，直到字数达标后再停止；
4. 必须命中每章章节卡里的 must_include；禁止出现 must_not_include；
5. 不得引入情节族/章节卡未规划的新核心角色、幕后系统、系统提示音等旁支；
6. 只输出分章文本，章节内部不要出现章节标题或小标题（不要出现“第X章”“【回忆】”等）。
{rewrite_block}

【情节族信息】cluster_id={cluster_id}；cluster_name={cluster_name}；主要对手={main_opp}；信息差提示={info_gap}；本簇落点={outcome}
【情节族详细梗概（不得偏离）】
{cluster_synopsis}

【逐章拍卡（用于开头/结尾微调）】
{beats_block_text}

【逐章章节卡约束（必须遵守）】
{cards_block_text}

【完整情节族正文（模型生成的连续文本）】
{full_cluster_body}

输出 JSON 结构（仅输出此 JSON）：
{split_output_json_schema}
"""


def _generate_cluster_continuous_and_split_v2(
    gen: "RebirthRevengeGeneratorV2",
    cluster: Dict[str, Any],
    cards: Dict[int, Dict[str, Any]],
    max_cluster_attempts: int = 5,
) -> Dict[int, str]:
    span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters") or []
    start_ch, end_ch = int(span[0]), int(span[1])
    chapter_nums = list(range(start_ch, end_ch + 1))
    chapter_cards = {ch: cards.get(ch, {}) for ch in chapter_nums}

    # 情节族首章：跨情节族首章开头接续上一章尾钩，减少明显断点
    prev_ch_full = gen.get_previous_chapter_content(start_ch) if start_ch > 1 else None
    prev_tail_scene, prev_unresolved_hook = gen._extract_prev_chapter_tail_and_hook(prev_ch_full)  # type: ignore[attr-defined]

    critic_result: Dict[str, Any] = {}
    for attempt in range(max_cluster_attempts):
        rewrite_advice = critic_result.get("rewrite_advice", []) if attempt > 0 else None
        if attempt > 0:
            ra = rewrite_advice or []
            ra_head = str(ra[0])[:120] + ("…（已截断）" if len(str(ra[0])) > 120 else "") if ra else ""
            if ra:
                print(
                    f"\n⚠️ 情节族 {cluster.get('cluster_id','')} 第{attempt+1}次重写：注入 critic 重写要求（{len(ra)}条）"
                    + (f"；首条摘要：{ra_head}" if ra_head else "")
                )

        print(f"\n🎯 [情节族梗概] {cluster.get('cluster_id','UNKNOWN')}《{cluster.get('name','')}》（第{start_ch}-{end_ch}章）")
        # Token 预算：按“每章≥1500字、并且需要按 beats 分段展开”来放大正文 max_tokens。
        max_tokens_synopsis = 1400
        max_tokens_beats = 1800
        # 字数目标：每章 >=1500 字。适当提高 token 预算，并给足重写次数，否则会落入“只写短开头/短结尾”的失败模式。
        max_tokens_body_per_chapter = 5000
        max_tokens_split = min(20000, 5200 * max(1, len(chapter_nums)))

        synopsis_prompt = _build_cluster_detailed_synopsis_prompt(
            cluster=cluster,
            chapter_cards=chapter_cards,
            prev_tail_scene=prev_tail_scene,
            prev_unresolved_hook=prev_unresolved_hook,
            rewrite_advice=rewrite_advice,
        )
        cluster_synopsis = gen._call_api(  # type: ignore[attr-defined]
            synopsis_prompt,
            None,
            0,
            max_tokens=max_tokens_synopsis,
        )
        cluster_synopsis = (cluster_synopsis or "").strip()
        # 梗概对后续节拍卡/正文切分影响很大：把梗概内容在日志里做一个截断预览，便于你对齐排错。
        synopsis_preview = cluster_synopsis[:300]
        if len(cluster_synopsis) > 300:
            synopsis_preview = synopsis_preview + "…（已截断）"
        print(
            f"📝 [情节族梗概简版] cluster={cluster.get('cluster_id','')}《{cluster.get('name','')}》（len={len(cluster_synopsis)}）"
        )
        print(synopsis_preview)

        print(f"📋 [节拍卡] 为情节族逐章生成 beats（第{start_ch}-{end_ch}章）…")

        # 节拍卡打印降噪：只保留每章关键字段 + beats 前几条截断预览。
        def _short(x: Any, n: int) -> str:
            s = str(x or "").strip().replace("\n", " ")
            if len(s) > n:
                return s[:n] + "…"
            return s

        beats_by_ch: Dict[int, Dict[str, Any]] = {}
        prev_end_to_next_seed = ""
        beats_generation_ok = True

        for idx_ch, ch in enumerate(chapter_nums):
            is_first = idx_ch == 0
            is_last = idx_ch == len(chapter_nums) - 1

            last_beats_out = ""
            last_beats_reason = ""
            beats_obj: Any = None

            for beats_try in range(3):
                max_tokens_beats_try = min(12000, 3200 + beats_try * 2500)
                beats_prompt = _build_single_chapter_beats_prompt(
                    cluster=cluster,
                    chapter_num=ch,
                    chapter_card=chapter_cards.get(ch, {}),
                    cluster_synopsis=cluster_synopsis,
                    prev_tail_scene=prev_tail_scene if is_first else "",
                    prev_unresolved_hook=prev_unresolved_hook if is_first else "",
                    prev_end_to_next_seed=prev_end_to_next_seed,
                    is_first_chapter=is_first,
                    is_last_chapter=is_last,
                    rewrite_advice=rewrite_advice,
                )
                beats_out = gen._call_api(  # type: ignore[attr-defined]
                    beats_prompt,
                    None,
                    0,
                    max_tokens=max_tokens_beats_try,
                )
                last_beats_out = (beats_out or "").strip()
                beats_obj = _extract_json_obj_maybe(beats_out)

                if not isinstance(beats_obj, dict):
                    last_beats_reason = f"beats_obj_type={type(beats_obj).__name__}"
                    continue

                b_list = beats_obj.get("beats")
                has_beats = isinstance(b_list, list) and len(b_list) > 0
                ch_ok = True
                try:
                    ch_ok = int(beats_obj.get("chapter_num")) == int(ch)
                except Exception:  # noqa: BLE001
                    ch_ok = True

                if has_beats and ch_ok:
                    open_from_prev = beats_obj.get("open_from_prev")
                    end_to_next = beats_obj.get("end_to_next")
                    if isinstance(open_from_prev, str) and open_from_prev.strip() and isinstance(end_to_next, str) and end_to_next.strip():
                        beats_by_ch[ch] = beats_obj
                        break

                last_beats_reason = (
                    f"has_beats={has_beats}; beats_len={len(b_list) if isinstance(b_list, list) else 'N/A'}; "
                    f"open_from_prev_type={type(beats_obj.get('open_from_prev')).__name__}; "
                    f"end_to_next_type={type(beats_obj.get('end_to_next')).__name__}"
                )

            if ch not in beats_by_ch:
                last_out_head = " ".join((last_beats_out or "").split())[:200]
                print(
                    f"⚠️ 第{ch}章 beats JSON 解析失败（放弃本情节族本轮）：cluster={cluster.get('cluster_id')}; "
                    f"reason={last_beats_reason}; last_out_head={last_out_head}"
                )
                beats_generation_ok = False
                break

            prev_end_to_next_seed = str(beats_by_ch[ch].get("end_to_next", "") or "")

        if not beats_generation_ok or any(ch not in beats_by_ch for ch in chapter_nums):
            continue

        print(f"🧾 [节拍卡-关键摘要] cluster={cluster.get('cluster_id','')}《{cluster.get('name','')}》")
        for ch in chapter_nums:
            bc = beats_by_ch[ch]
            beats_list_for_print = bc.get("beats") if isinstance(bc, dict) else []
            beats_count = len(beats_list_for_print) if isinstance(beats_list_for_print, list) else 0
            print(
                f"  - 第{ch}章 beats={beats_count}；flashback_idx={bc.get('flashback_in_beat_idx', None)}"
            )
            print(f"    open_from_prev={_short(bc.get('open_from_prev',''), 80)}；end_to_next={_short(bc.get('end_to_next',''), 80)}")

            if isinstance(beats_list_for_print, list) and beats_list_for_print:
                previews: List[str] = []
                for i, b in enumerate(beats_list_for_print[:5]):
                    if isinstance(b, dict):
                        sg = _short(b.get("scene_goal"), 60)
                        ep = _short(b.get("emotion_push"), 30)
                        previews.append(f"{i+1}:{sg}" + (f"({ep})" if ep else ""))
                    else:
                        previews.append(f"{i+1}:{_short(b, 60)}")
                print("    beats_preview=" + " | ".join(previews))

        # 连续正文：按章分批生成并拼接（每次只写一个章的正文，不要章节标题）
        print(f"✍️ [连续正文] 按章分批生成连续正文（共 {len(chapter_nums)} 次）…")
        full_text_parts: List[str] = []
        prev_full_text = ""
        prev_end_to_next = ""
        for idx, ch in enumerate(chapter_nums):
            bc = beats_by_ch[ch]

            prev_tail = prev_full_text[-1400:] if prev_full_text else ""
            prev_unresolved = prev_end_to_next if prev_end_to_next else (prev_unresolved_hook if idx == 0 else "")

            kg_context = ""
            try:
                online_retrieve = getattr(gen, "online_retrieve_context", None)
                if callable(online_retrieve):
                    kg_context = str(online_retrieve(ch)) or ""
            except Exception:  # noqa: BLE001
                kg_context = ""

            card = chapter_cards.get(ch, {}) or {}
            role_v2 = ""
            if isinstance(card, dict):
                role_v2 = str(card.get("chapter_role_v2") or "")

            need_prev_life = role_v2 in {
                "prev_life_full",
                "prev_life_explained_by_investigation",
                "present_past_mix",
                "slow_burn_press_with_past_shadow",
            }
            # 强制：第 1/2 章不插入上一世回忆
            if ch in (1, 2):
                need_prev_life = False

            core_text = str(cluster.get("core_payoff", "") or "") + "\n" + cluster_synopsis
            has_revenge = any(k in core_text for k in ["复仇", "反制", "反击", "扳倒", "揭穿", "打脸"])

            prev_life_clue = ""
            if hasattr(gen, "prev_life_ctx") and isinstance(getattr(gen, "prev_life_ctx"), dict):
                prev_life_clue = str((gen.prev_life_ctx.get(ch) or ""))  # type: ignore[attr-defined]

            rag_query = f"{cluster_synopsis}\n{prev_life_clue or ''}".strip()
            target_context = "主角: 沈清欢, 背景: 现代都市, 重生复仇, 职场复仇"
            rag_samples = search_rebirth_samples_for_chapter(
                rag_query,
                target_context,
                need_prev_life=need_prev_life,
                has_revenge=has_revenge,
                top_k_per_set=2,
            )

            if rag_samples and any(rag_samples.get(k) for k in ("revenge", "grievance", "universal")):
                n = sum(len(rag_samples.get(k, [])) for k in ("revenge", "grievance", "universal"))
                if n:
                    print(f"  [RAG] 第{ch}章 注入 {n} 条参考（委屈/爽感/通用）", flush=True)

            body_prompt = _build_cluster_body_part_prompt(
                cluster=cluster,
                cluster_synopsis=cluster_synopsis,
                chapter_num=ch,
                chapter_beats=bc,
                prev_tail_scene=prev_tail if prev_tail else (prev_tail_scene if idx == 0 else ""),
                prev_unresolved_hook=prev_unresolved,
                chapter_card=chapter_cards.get(ch, {}),
                kg_context=kg_context,
                rewrite_advice=rewrite_advice,
                rag_samples=rag_samples,
            )
            part_text = gen._call_api(  # type: ignore[attr-defined]
                body_prompt,
                None,
                idx,
                max_tokens=max_tokens_body_per_chapter,
            )
            part_text = (part_text or "").strip()
            if not part_text or part_text.startswith("通义千问"):
                raise RuntimeError(f"第{ch}章正文生成失败或为空。")
            full_text_parts.append(part_text)
            prev_full_text += part_text
            prev_end_to_next = str(bc.get("end_to_next", "") or "")

        full_body = "\n".join(full_text_parts).strip()

        print("🧩 [切分微调] 把连续正文切分成章并微调开头/结尾钩子…")
        split_prompt = _build_cluster_split_prompt(
            cluster=cluster,
            cluster_synopsis=cluster_synopsis,
            full_cluster_body=full_body,
            chapter_nums=chapter_nums,
            chapter_cards=chapter_cards,
            beats_cards=[beats_by_ch[ch] for ch in chapter_nums],
            rewrite_advice=rewrite_advice,
        )
        split_out = gen._call_api(  # type: ignore[attr-defined]
            split_prompt,
            None,
            0,
            max_tokens=max_tokens_split,
        )
        split_obj = _extract_json_obj_maybe(split_out)
        split_chapters = []
        if isinstance(split_obj, dict):
            split_chapters = split_obj.get("chapters") or []
        if not isinstance(split_chapters, list) or not split_chapters:
            raise RuntimeError(f"切分 JSON 解析失败，cluster={cluster.get('cluster_id')}。")

        chapter_texts: Dict[int, str] = {}
        for item in split_chapters:
            if not isinstance(item, dict):
                continue
            if item.get("chapter_num") is None or item.get("text") is None:
                continue
            try:
                cn = int(item["chapter_num"])
            except Exception:  # noqa: BLE001
                continue
            chapter_texts[cn] = str(item.get("text") or "").strip()

        for ch in chapter_nums:
            if ch not in chapter_texts or len(chapter_texts[ch]) < 1000:
                # 软失败：把“切分过短”转化为重写建议，下一轮提升分章字数
                too_short = [c for c in chapter_nums if c not in chapter_texts or len((chapter_texts.get(c) or "")) < 1400]
                if too_short:
                    short_msgs = [f"第{c}章分章文本过短（{len((chapter_texts.get(c) or ''))}字），需要≥1500字且不得只保留短开头/短结尾" for c in too_short]
                    critic_result = {
                        "payoff_completed": False,
                        "violations": short_msgs,
                        "rewrite_advice": [
                            "分章切分后，每章正文必须≥1500字，不能只保留短开头/短结尾；",
                            "请在切分阶段保留主体段落的信息密度，必要时在“beats 中每拍”补写到每拍≥160字；",
                        ] + short_msgs[:3],
                    }
                    # 进入下一轮 attempt，并把建议注入到后续 prompt
                    continue
                else:
                    raise RuntimeError(f"切分结果缺失或过短：第{ch}章")

        # 写盘 + 记录到内存，便于 critic 使用
        for ch in chapter_nums:
            gen.save_chapter(ch, chapter_texts[ch])  # type: ignore[attr-defined]
            gen.generated_chapters[ch] = chapter_texts[ch]  # type: ignore[attr-defined]

        critic_result = _cluster_critic(cluster, chapter_texts)  # type: ignore[misc]
        payoff_ok = bool(critic_result.get("payoff_completed", False))
        violations = critic_result.get("violations", []) or []
        print(f"📋 情节族完成审查：payoff_completed={payoff_ok}，violations={len(violations)} 条")
        if payoff_ok or attempt >= max_cluster_attempts - 1:
            if violations and not payoff_ok:
                print("⚠️ 本情节族未通过审查（保留最大努力版本）。可人工检查：")
                for v in violations[:8]:
                    print(f"   - {v}")
            return chapter_texts

    return {}


def generate_chapters_v2(
    master_ctx_cards_path: Optional[str] = None,
    prev_life_ctx_path: Optional[str] = None,
    chapters_dir: Optional[str] = None,
    start_chapter: int = 1,
    end_chapter: int = 100,
) -> None:
    """
    便捷入口：按章节范围生成正文。不再依赖 master_ctx_cards_v2.json，
    仅使用 event_clusters_v2.json + prev_life_ctx_v2.txt，在脚本内把情节组拆成章节并生成。
    """
    if prev_life_ctx_path is None:
        prev_life_ctx_path = str(DEFAULT_PREV_LIFE_V2)
    if not os.path.exists(prev_life_ctx_path):
        raise FileNotFoundError(
            f"未找到上一世线索文件：{prev_life_ctx_path}，"
            "请先运行 generate_outline_from_event_clusters_v2.py 生成 prev_life_ctx_v2.txt。"
        )

    clusters_path = str(DEFAULT_EVENT_CLUSTERS_V2)
    if not os.path.exists(clusters_path):
        raise FileNotFoundError(
            f"未找到事件簇文件：{clusters_path}，"
            "请先运行 generate_event_clusters_v2.py 生成 event_clusters_v2.json。"
        )

    with open(clusters_path, "r", encoding="utf-8") as f:
        clusters: List[Dict[str, Any]] = json.load(f)
    if not isinstance(clusters, list) or not clusters:
        raise ValueError("event_clusters_v2.json 为空或格式错误，无法生成正文。")

    overlapping: List[Dict[str, Any]] = []
    for c in clusters:
        span = c.get("chapter_span") or c.get("chapterRange") or c.get("chapters")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            continue
        try:
            s, e = int(span[0]), int(span[1])
        except Exception:
            continue
        if e < start_chapter or s > end_chapter:
            continue
        c["_start"] = s
        c["_end"] = e
        overlapping.append(c)

    if not overlapping:
        raise ValueError(
            f"章节范围 {start_chapter}-{end_chapter} 与 event_clusters_v2.json 中任何情节组均无交集，"
            "请调整 --start / --end 或重新生成事件簇。"
        )

    min_s = min(c["_start"] for c in overlapping)
    max_e = max(c["_end"] for c in overlapping)
    adjusted_start = min(min_s, start_chapter)
    adjusted_end = max(max_e, end_chapter)
    if adjusted_start != start_chapter or adjusted_end != end_chapter:
        # 汇总被纳入的情节族边界，便于用户确认
        included_spans: List[str] = []
        for c in sorted(overlapping, key=lambda x: (x.get("_start", 0), x.get("_end", 0))):
            try:
                ss, ee = int(c["_start"]), int(c["_end"])
                cid = str(c.get("cluster_id", "")) or "?"
                included_spans.append(f"{cid}:{ss}-{ee}")
            except Exception:  # noqa: BLE001
                continue
        spans_str = "，".join(included_spans) if included_spans else f"{adjusted_start}-{adjusted_end}"
        print(
            f"✅ 已对齐到情节族边界：章节范围调整为 {adjusted_start}-{adjusted_end}（原 {start_chapter}-{end_chapter}）。\n"
            f"   纳入的情节族范围：{spans_str}"
        )

    # 在任何 Neo4j 导出/在线检索器/正文生成之前，先把“识别到的情节族”汇总打印出来
    overlapping_sorted = sorted(overlapping, key=lambda x: int(x.get("_start", 0)))
    print("\n📌 识别到的情节族信息（将按此范围生成）")
    for c in overlapping_sorted:
        try:
            s = int(c.get("_start", c.get("chapter_span", [0, 0])[0]))
            e = int(c.get("_end", c.get("chapter_span", [0, 0])[1]))
        except Exception:  # noqa: BLE001
            s, e = 0, 0
        cid = c.get("cluster_id", "UNKNOWN")
        name = c.get("name", "")
        core = c.get("core_payoff", "") or c.get("core", "") or ""
        opp = c.get("main_opponent", "") or ""
        span_str = f"{s}-{e}" if s and e else str(c.get("chapter_span") or c.get("chapterRange") or c.get("chapters") or "")
        print(f"- {cid}《{name}》 覆盖章节:{span_str}；主要对手:{opp or '（未指定）'}；核心爽点:{core or '（未提供）'}")

    # 自动导出 Neo4j 上下文（供调试/审阅；生成过程本身使用在线检索器逐章拉取背景）
    try:
        print("🧭 正在检索情节族上下文（Neo4j）：窗口 + lookback + auto-anchors …")
        # 构造窗口章节
        window = list(range(adjusted_start, adjusted_end + 1))
        # lookback: 回溯 2 章
        lookback_n = 2
        if window:
            m = min(window)
            lb = list(range(max(1, m - lookback_n), m))
            window = sorted(set(window) | set(lb))
        # auto-anchors: 自动补充关键早期章（最多 10 个）
        try:
            from neo4j_kg.export_for_v2 import (  # type: ignore[import-not-found]
                fetch_context,
                compute_anchor_chapters,
            )
            from neo4j_kg.common import get_neo4j_driver  # type: ignore[import-not-found]
            with get_neo4j_driver() as driver:  # type: ignore[attr-defined]
                extras = compute_anchor_chapters(driver, window, max_extra=10)
                chapters_for_export = sorted(set(window) | set(extras))
                ctx = fetch_context(driver, chapters_for_export)
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            with open(DEFAULT_EXPORT_V2, "w", encoding="utf-8") as f:
                json.dump(ctx, f, ensure_ascii=False, indent=2)
            print(f"✅ 已导出上下文至 {DEFAULT_EXPORT_V2}")
            print(f"   章节集合：{','.join(str(x) for x in chapters_for_export)}")
        except Exception as ex:  # noqa: BLE001
            print(f"⚠️ 跳过导出上下文（Neo4j 不可用或导出失败）：{ex}")
    except Exception:
        pass

    cards: Dict[int, Dict[str, Any]] = {}
    resolved_master_cards_path = master_ctx_cards_path or str(DEFAULT_MASTER_CARDS_V2)
    cards = _load_master_cards_v2(resolved_master_cards_path)
    if not cards:
        # 兜底：当 master cards 缺失时，退回旧实现动态构建（避免流程完全中断）
        cards = _build_cards_from_clusters(overlapping)
    gen = RebirthRevengeGeneratorV2()
    _setup_gen_from_cards_and_prev_life(gen, cards, prev_life_ctx_path, clusters)
    # 挂载在线检索器（若可用）：每章生成前动态检索 Neo4j 背景事实
    try:
        gen.attach_online_retriever()
        print("🔎 在线检索器（Neo4j）已启用：将为每章注入限长背景事实。")
    except Exception:
        pass

    if chapters_dir is None:
        chapters_dir = str(OUTPUT_DIR / "chapters_v2")
    os.makedirs(chapters_dir, exist_ok=True)
    gen.outputs_dir = Path(chapters_dir).parent

    # 新工作流：按“情节族/事件簇”生成整簇连续正文，最后再切分为章节
    clusters_sorted = sorted(overlapping, key=lambda x: int(x.get("_start", 0)))
    generated_chapters_global: set[int] = set()

    out_ch_dir = Path(gen.outputs_dir) / "chapters"
    # 生成入口跳过逻辑：避免把之前生成的“短章”当成合格版本复用。
    min_chars_for_accept = 1500
    for cluster in clusters_sorted:
        span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters") or []
        try:
            s, e = int(span[0]), int(span[1])
        except Exception:  # noqa: BLE001
            continue
        chapter_nums = list(range(s, e + 1))
        need_generate = False
        for ch in chapter_nums:
            if ch not in cards:
                continue
            if ch in gen.generated_chapters and len((gen.generated_chapters.get(ch) or "").strip()) >= min_chars_for_accept:
                continue
            p = out_ch_dir / f"chapter_{ch:03d}.txt"
            if p.exists() and p.stat().st_size >= 200:
                existing = p.read_text(encoding="utf-8").strip()
                if len(existing) >= min_chars_for_accept:
                    gen.generated_chapters[ch] = existing
                    continue
            need_generate = True
            break
        if not need_generate and all(ch in gen.generated_chapters for ch in chapter_nums if ch in cards):
            continue

        print(f"\n====== 生成情节族 {cluster.get('cluster_id','UNKNOWN')}《{cluster.get('name','')}》：第{s}-{e}章 ======")
        new_texts = _generate_cluster_continuous_and_split_v2(gen, cluster, cards)
        for ch in chapter_nums:
            if ch in new_texts:
                generated_chapters_global.add(ch)


def generate_chapters_by_clusters_v2(
    master_ctx_cards_path: Optional[str] = None,
    prev_life_ctx_path: Optional[str] = None,
    chapters_dir: Optional[str] = None,
    cluster_ids: Optional[List[str]] = None,
) -> None:
    """
    DEPRECATED（逐章生成流程）

    该实现属于“旧工作流”：在簇内部逐章生成，并在簇完成后做 critic 审查/必要重写。
    当前默认入口已切换为 `generate_chapters_v2()`（整簇连续正文 -> 再切分微调）。

    保留此函数仅用于历史对比/排查；不应再被当作主生成入口使用。
    """
    # 防止误用旧工作流：如确有需要请改用 generate_chapters_v2() 或手动回滚到旧实现。
    raise RuntimeError(
        "generate_chapters_by_clusters_v2() 已弃用：请使用 generate_chapters_v2()（新工作流）。"
    )

    # ---- 下面是旧实现代码（已弃用，默认不可达）----
    # 保留参数以兼容旧命令，但在情节组模式下不再使用 master_ctx_cards_v2.json
    if prev_life_ctx_path is None:
        prev_life_ctx_path = str(DEFAULT_PREV_LIFE_V2)

    if not os.path.exists(prev_life_ctx_path):
        raise FileNotFoundError(
            f"未找到上一世线索文件：{prev_life_ctx_path}，"
            f"请先运行基于 V2 事件簇的大纲脚本生成 prev_life_ctx_v2.txt。"
        )

    clusters_path = str(DEFAULT_EVENT_CLUSTERS_V2)
    if not os.path.exists(clusters_path):
        raise FileNotFoundError(
            f"未找到事件簇文件：{clusters_path}，"
            f"请先运行 generate_event_clusters_v2.py 生成 event_clusters_v2.json。"
        )

    with open(clusters_path, "r", encoding="utf-8") as f:
        clusters: List[Dict[str, Any]] = json.load(f)
    if not isinstance(clusters, list):
        raise ValueError("event_clusters_v2.json 顶层必须是数组。")

    # 过滤需要的簇，并按 chapter_span 起始排序，保证整体推进顺序正确
    selected: List[Dict[str, Any]] = []
    for c in clusters:
        if cluster_ids and c.get("cluster_id") not in set(cluster_ids):
            continue
        span = c.get("chapter_span") or c.get("chapterRange") or c.get("chapters")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            continue
        try:
            s, e = int(span[0]), int(span[1])
        except Exception:
            continue
        c["_start"] = s
        c["_end"] = e
        selected.append(c)

    if not selected:
        print("⚠️ 未在事件簇文件中找到可用的簇（或 cluster_ids 过滤后为空），不执行生成。")
        return

    selected.sort(key=lambda x: x.get("_start", 9999))

    resolved_master_cards_path = master_ctx_cards_path or str(DEFAULT_MASTER_CARDS_V2)
    cards = _load_master_cards_v2(resolved_master_cards_path)
    if not cards:
        # 兜底：master cards 缺失时才退回动态构建
        cards = _build_cards_from_clusters(selected)
    gen = RebirthRevengeGeneratorV2()
    _setup_gen_from_cards_and_prev_life(gen, cards, prev_life_ctx_path, clusters)

    if chapters_dir is None:
        chapters_dir = str(OUTPUT_DIR / "chapters_v2")
    os.makedirs(chapters_dir, exist_ok=True)
    gen.outputs_dir = Path(chapters_dir).parent

    for cluster in selected:
        cid = cluster.get("cluster_id", "UNKNOWN")
        name = cluster.get("name", "")
        s, e = int(cluster["_start"]), int(cluster["_end"])
        core = cluster.get("core_payoff", "")
        main_opp = cluster.get("main_opponent", "")
        span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters")

        max_cluster_attempts = 2
        critic_result: Dict[str, Any] = {}
        for attempt in range(max_cluster_attempts):
            if attempt > 0:
                setattr(gen, "_cluster_rewrite_advice", critic_result.get("rewrite_advice", []))
                print(f"\n⚠️ 情节组 {cid} 未通过完成审查，第 {attempt + 1} 次重写，已注入重写要求。")
            else:
                setattr(gen, "_cluster_rewrite_advice", None)

            print("\n" + "=" * 70)
            print(f"🎯 生成情节组 {cid}《{name}》" + ("（重写）" if attempt > 0 else ""))
            print(f"   覆盖章节: {span or [s, e]}  （实际生成范围: 第{s}-{e}章）")
            print(f"   核心爽点: {core or '（未提供）'}")
            print(f"   主要对手: {main_opp or '（未指定）'}")
            print("=" * 70)

            for ch in range(s, e + 1):
                # 簇内滚动上下文：已写章节摘要 → resolved_so_far / unresolved_must_finish
                chapter_texts_so_far: Dict[int, str] = {}
                for prev_ch in range(s, ch):
                    prev_path = Path(chapters_dir) / f"chapter_{prev_ch:03d}.txt"
                    if prev_path.exists():
                        try:
                            chapter_texts_so_far[prev_ch] = prev_path.read_text(encoding="utf-8").strip()
                        except Exception:  # noqa: S110
                            pass
                    if prev_ch in getattr(gen, "generated_chapters", {}):
                        chapter_texts_so_far[prev_ch] = gen.generated_chapters[prev_ch]
                state = _build_cluster_internal_state(cluster, chapter_texts_so_far, chapters_dir)
                setattr(gen, "_cluster_internal_state", state)

                print(f"\n—— 情节组 {cid}：生成第 {ch} 章 ——")
                gen.debug_print_chapter_context(ch)
                gen.generate_one_chapter_with_beats(  # type: ignore[attr-defined]
                    chapter_num=ch,
                    num_versions=1,
                    max_iterations=2,
                    min_emotion_intensity=0.5,
                )

            # 簇完成审查：读取刚写的各章，判 payoff 是否落地、是否越界
            chapter_texts_for_critic: Dict[int, str] = {}
            for ch in range(s, e + 1):
                p = Path(chapters_dir) / f"chapter_{ch:03d}.txt"
                if p.exists():
                    try:
                        chapter_texts_for_critic[ch] = p.read_text(encoding="utf-8").strip()
                    except Exception:  # noqa: S110
                        chapter_texts_for_critic[ch] = ""
                elif ch in getattr(gen, "generated_chapters", {}):
                    chapter_texts_for_critic[ch] = gen.generated_chapters[ch]

            critic_result = _cluster_critic(cluster, chapter_texts_for_critic)
            payoff_ok = critic_result.get("payoff_completed", False)
            violations = critic_result.get("violations", [])

            print(f"\n📋 情节组 {cid} 完成审查：payoff_completed={payoff_ok}，violations={len(violations)} 条")
            if violations:
                for v in violations[:5]:
                    print(f"   - {v}")
            if payoff_ok or attempt >= max_cluster_attempts - 1:
                if not payoff_ok:
                    print(f"   ⚠️ 已达最大重写次数，保留当前版本。建议人工检查第{s}-{e}章。")
                break


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="基于 V2 事件簇生成重生复仇小说正文（不依赖 master_ctx_cards_v2.json）"
    )
    parser.add_argument(
        "--prev-life",
        default=str(DEFAULT_PREV_LIFE_V2),
        help="上一世线索文件路径（默认 outputs/prev_life_ctx_v2.txt）",
    )
    parser.add_argument(
        "--chapters-dir",
        default=str(OUTPUT_DIR / "chapters_v2"),
        help="输出章节目录（默认 outputs/chapters_v2）",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="起始章节号，默认 1",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=100,
        help="结束章节号，默认 100",
    )
    args = parser.parse_args()

    generate_chapters_v2(
        prev_life_ctx_path=args.prev_life,
        chapters_dir=args.chapters_dir,
        start_chapter=args.start,
        end_chapter=args.end,
    )


if __name__ == "__main__":
    main()


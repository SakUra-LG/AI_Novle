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

from generate_chapter_content import (  # type: ignore[import]
    RebirthRevengeGenerator,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "outputs"

# 统一的 V2 文件命名规则（硬编码稳定文件名，去掉时间戳依赖）
DEFAULT_MASTER_CARDS_V2 = OUTPUT_DIR / "master_ctx_cards_v2.json"
DEFAULT_PREV_LIFE_V2 = OUTPUT_DIR / "prev_life_ctx_v2.txt"
DEFAULT_EVENT_CLUSTERS_V2 = OUTPUT_DIR / "event_clusters_v2.json"


class RebirthRevengeGeneratorV2(RebirthRevengeGenerator):
    """V2：基于事件簇模版的正文生成器。"""

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
        outcome = card.get("cluster_outcome", "")

        extra_lines = []
        if cluster_id:
            extra_lines.append(
                f"\n【本章对应的事件簇（V2）】\n"
                f"- 事件簇 {cluster_id}《{cluster_name}》，核心爽点：{core_payoff}；主要对手：{main_opp}。\n"
                f"- 上一世悲剧前提：{prev_tragedy}\n"
                f"- 今生在本簇中的大致反击方式：{this_revenge}\n"
                f"- 本簇结束结果：{outcome}"
            )

        extra_lines.append(
            f"\n【章节结构职责（V2）】\n"
            f"- 本章结构模版：{tmpl}；章节角色：{role_v2}。\n"
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

        return base_prompt + "\n" + "\n".join(extra_lines)


def generate_chapters_v2(
    master_ctx_cards_path: Optional[str] = None,
    prev_life_ctx_path: Optional[str] = None,
    chapters_dir: Optional[str] = None,
    start_chapter: int = 1,
    end_chapter: int = 100,
) -> None:
    """
    便捷入口：使用 V2 章节卡和上一世线索批量生成章节。

    - master_ctx_cards_path: 章节卡 JSON 路径；默认为 outputs/master_ctx_cards_v2.json；
    - prev_life_ctx_path: 上一世线索文本路径；默认为 outputs/prev_life_ctx_v2.txt；
    - start_chapter / end_chapter: 生成范围，必须覆盖若干个完整的事件簇（story cluster）。
    """
    # 若未显式传入路径，则使用统一的 V2 稳定文件名
    if master_ctx_cards_path is None:
        master_ctx_cards_path = str(DEFAULT_MASTER_CARDS_V2)
    if prev_life_ctx_path is None:
        prev_life_ctx_path = str(DEFAULT_PREV_LIFE_V2)

    # 简单检查：文件是否存在
    if not os.path.exists(master_ctx_cards_path):
        raise FileNotFoundError(
            f"未找到章节卡文件：{master_ctx_cards_path}，"
            f"请先运行基于 V2 事件簇的大纲脚本生成 master_ctx_cards_v2.json。"
        )
    if not os.path.exists(prev_life_ctx_path):
        raise FileNotFoundError(
            f"未找到上一世线索文件：{prev_life_ctx_path}，"
            f"请先运行基于 V2 事件簇的大纲脚本生成 prev_life_ctx_v2.txt。"
        )

    # 读取事件簇 V2，用于校验/调整章节范围：要求范围内至少包含若干完整事件簇
    clusters_path = str(DEFAULT_EVENT_CLUSTERS_V2)
    adjusted_start = start_chapter
    adjusted_end = end_chapter
    if os.path.exists(clusters_path):
        try:
            with open(clusters_path, "r", encoding="utf-8") as f:
                clusters: List[Dict[str, Any]] = json.load(f)
        except Exception:
            clusters = []
        if isinstance(clusters, list) and clusters:
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
                overlapping.append({"start": s, "end": e, "raw": c})
            if overlapping:
                # 将用户指定范围向外扩展，确保所有相交的簇都被完整覆盖
                min_s = min(it["start"] for it in overlapping)
                max_e = max(it["end"] for it in overlapping)
                if min_s < adjusted_start or max_e > adjusted_end:
                    print(
                        f"⚠️ 你指定的章节范围 {start_chapter}-{end_chapter} 截断了部分事件簇，"
                        f"已自动调整为 {min_s}-{max_e} 以保证包含若干完整的故事簇。"
                    )
                adjusted_start = min(adjusted_start, min_s)
                adjusted_end = max(adjusted_end, max_e)
        else:
            print("⚠️ 未能从事件簇 V2 文件中读取有效数据，将按原始章节范围生成正文。")
    else:
        print("⚠️ 未找到 event_clusters_v2.json，将按原始章节范围生成正文（可能截断事件簇）。")

    gen = RebirthRevengeGeneratorV2()
    gen.load_contexts(master_ctx_cards_path, prev_life_ctx_path)
    # 将事件簇列表挂到生成器上，便于在单章生成时输出“本情节信息”
    if locals().get("clusters"):
        setattr(gen, "event_clusters_v2", clusters)
    if chapters_dir is None:
        chapters_dir = str(OUTPUT_DIR / "chapters_v2")
    os.makedirs(chapters_dir, exist_ok=True)
    gen.outputs_dir = Path(chapters_dir).parent  # 保持与旧版行为接近

    for ch in range(adjusted_start, adjusted_end + 1):
        print(f"\n====== 生成第 {ch} 章（V2） ======")
        # 先输出本情节 + 本章梗概信息，再按“节拍卡→正文”单版本流水线生成
        gen.debug_print_chapter_context(ch)
        gen.generate_one_chapter_with_beats(  # type: ignore[attr-defined]
            chapter_num=ch,
            num_versions=1,
            max_iterations=2,
            min_emotion_intensity=0.5,
        )


def generate_chapters_by_clusters_v2(
    master_ctx_cards_path: Optional[str] = None,
    prev_life_ctx_path: Optional[str] = None,
    chapters_dir: Optional[str] = None,
    cluster_ids: Optional[List[str]] = None,
) -> None:
    """
    按「情节组/事件簇」为单位生成正文：一次性生成某个簇覆盖的全部章节。

    - cluster_ids 为空时，按 event_clusters_v2.json 中的顺序依次生成所有簇；
    - 若指定 cluster_ids，则只生成这些簇对应的章节范围；
    - 每个簇内部按章节顺序逐章生成：先生成节拍卡，再按节拍卡生成正文。
    """
    if master_ctx_cards_path is None:
        master_ctx_cards_path = str(DEFAULT_MASTER_CARDS_V2)
    if prev_life_ctx_path is None:
        prev_life_ctx_path = str(DEFAULT_PREV_LIFE_V2)

    if not os.path.exists(master_ctx_cards_path):
        raise FileNotFoundError(
            f"未找到章节卡文件：{master_ctx_cards_path}，"
            f"请先运行基于 V2 事件簇的大纲脚本生成 master_ctx_cards_v2.json。"
        )
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

    gen = RebirthRevengeGeneratorV2()
    gen.load_contexts(master_ctx_cards_path, prev_life_ctx_path)
    # 同样挂载事件簇，方便在每章生成前打印“本情节信息”
    setattr(gen, "event_clusters_v2", clusters)

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
        print("\n" + "=" * 70)
        print(f"🎯 生成情节组 {cid}《{name}》")
        print(f"   覆盖章节: {span or [s, e]}  （实际生成范围: 第{s}-{e}章）")
        print(f"   核心爽点: {core or '（未提供）'}")
        print(f"   主要对手: {main_opp or '（未指定）'}")
        print("=" * 70)
        for ch in range(s, e + 1):
            print(f"\n—— 情节组 {cid}：生成第 {ch} 章 ——")
            # 先输出本情节+本章梗概，再生成节拍卡和正文（单版本）
            gen.debug_print_chapter_context(ch)
            gen.generate_one_chapter_with_beats(  # type: ignore[attr-defined]
                chapter_num=ch,
                num_versions=1,
                max_iterations=2,
                min_emotion_intensity=0.5,
            )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="基于 V2 事件簇章节卡生成重生复仇小说正文"
    )
    parser.add_argument(
        "--master-cards",
        default=str(DEFAULT_MASTER_CARDS_V2),
        help="章节卡 JSON 路径（默认 outputs/master_ctx_cards_v2.json）",
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
        master_ctx_cards_path=args.master_cards,
        prev_life_ctx_path=args.prev_life,
        chapters_dir=args.chapters_dir,
        start_chapter=args.start,
        end_chapter=args.end,
    )


if __name__ == "__main__":
    main()


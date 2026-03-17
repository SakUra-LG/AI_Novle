#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据已人工确认好的 outputs/event_clusters.json，
按事件簇 → 章节的方式重新生成 100 章章节梗概 / 章节卡，
避免再次改写事件簇本身。
"""

import os
import json
from datetime import datetime
import re
from typing import List, Dict, Any

import dashscope

from smart_sample_search import search_and_adapt_samples
from generate_outline_rebirth_revenge import (  # type: ignore[import]
    build_prev_life_outline_system_prompt,
    analyze_outline_for_prev_life,
    build_prev_life_batch_user_query,
)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "outputs")


API_Key_QW = "sk-a2966f4e37134351904851679884cb67"
MAX_TOKENS = 8192


def call_qianwen_api(messages, temperature=0.9, top_p=0.85, repetition_penalty=1.05):
    """调用通义千问 API，返回纯文本内容（轻微去重惩罚，减少机械重复）"""
    dashscope.api_key = API_Key_QW
    try:
        resp = dashscope.Generation.call(
            model=dashscope.Generation.Models.qwen_turbo,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            result_format="message",
            max_tokens=MAX_TOKENS,
        )
        if "output" in resp and "choices" in resp["output"]:
            content = resp["output"]["choices"][0]["message"]["content"]
            return content.replace("```", "").strip()
        return f"通义千问 API 返回了无效格式: {resp!r}"
    except Exception as e:  # noqa: BLE001
        return f"调用通义千问 API 出错: {e}"


def load_event_clusters() -> List[Dict[str, Any]]:
    """只读取已经存在的事件簇规划，不做任何修改。"""
    path = os.path.join(OUTPUT_DIR, "event_clusters.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"未找到事件簇文件：{path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("event_clusters.json 格式错误：顶层必须是数组")
    return data


def build_cluster_overview_for_batch(
    clusters: List[Dict[str, Any]], batch_start: int, batch_end: int
) -> str:
    """为当前批次生成一个轻量级的事件簇说明，避免过度“硬约束”导致模型死板复读。"""
    related: List[Dict[str, Any]] = []
    for c in clusters:
        span = c.get("chapter_span") or c.get("chapterRange") or c.get("chapters")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            continue
        try:
            s, e = int(span[0]), int(span[1])
        except Exception:  # noqa: BLE001
            continue
        if e < batch_start or s > batch_end:
            continue
        related.append(c)

    if not related:
        return ""

    lines: List[str] = []
    for c in related:
        cid = c.get("cluster_id", "")
        name = c.get("name", "")
        span = c.get("chapter_span", [])
        core = c.get("core_payoff", "")
        opp = c.get("main_opponent", "")
        lines.append(
            f"- 事件簇 {cid}《{name}》，章节范围 {span}；核心爽点：{core}；主要对手：{opp}。"
        )

    per_chapter: List[str] = []
    for ch in range(batch_start, batch_end + 1):
        covers: List[Dict[str, Any]] = []
        for c in related:
            span = c.get("chapter_span") or c.get("chapterRange") or c.get("chapters")
            try:
                s, e = int(span[0]), int(span[1])
            except Exception:  # noqa: BLE001
                continue
            if s <= ch <= e:
                covers.append(c)
        if not covers:
            continue
        sub_lines: List[str] = []
        for c in covers:
            span = c.get("chapter_span") or c.get("chapterRange") or c.get("chapters")
            try:
                s, e = int(span[0]), int(span[1])
            except Exception:  # noqa: BLE001
                continue
            cid = c.get("cluster_id", "")
            name = c.get("name", "")
            core = c.get("core_payoff", "")
            role_hint = "中段承上启下，写今生布局与局势升级。"
            if ch == s and ch == e:
                role_hint = "该簇唯一一章，需要完整写完：背景→上一世被害→今世布局→反杀收尾。"
            elif ch == s:
                role_hint = "该簇首章，重点写今世触发点和上一世对照，为后续反杀埋线。"
            elif ch == e:
                role_hint = "该簇尾章，需要把本簇的核心爽点真正落地，写清反杀结果和对当事人的后果。"
            sub_lines.append(
                f"  - 第{ch}章 × 事件簇 {cid}《{name}》：{role_hint} 本章主要围绕该簇核心爽点展开：{core}"
            )
        if sub_lines:
            per_chapter.append(f"- 第{ch}章：\n" + "\n".join(sub_lines))

    overview = "\n【本批涉及的事件簇简要说明】\n" + "\n".join(lines)
    if per_chapter:
        overview += (
            "\n\n【本批章节与事件簇的大致分工】\n"
            "下面只是功能提醒，不是死规则，你可以在保证簇爽点一致的前提下灵活编排细节：\n"
            + "\n".join(per_chapter)
        )
    return overview


def build_batch_user_query_from_clusters(
    batch_start: int,
    batch_end: int,
    prior_summary: str,
    cluster_overview: str,
) -> str:
    """构造一个相对“温和”的提示词：给清楚边界与簇信息，但不死板用大量“必须/禁止”堆砌。

    ⚠ 本函数现在要求模型为每一章输出【标题 + 2~4 句梗概】，而不是只写标题。
    """
    ch_count = batch_end - batch_start + 1
    parts: List[str] = []

    parts.append(
        f"请为《重生复仇短剧》的第{batch_start}章到第{batch_end}章（共{ch_count}章）生成逐章梗概，"
        "这一批的主要剧情需要围绕我给你的事件簇来展开。"
    )
    parts.append(
        "整体类型保持为：都市职场复仇 + 医疗阴谋揭露 + 舆论反转，"
        "侧重证据、布局和舆论反杀，而不是黑帮肉搏或杀手动作戏。"
    )

    if batch_start == 1:
        parts.append(
            "\n【结构提醒】\n"
            "- 第1章：上一世临死前的 ICU / 病房场景，只写她如何被害死和极致屈辱，当时她不知道会重生。\n"
            "- 第2章：这一世醒来后逐步确认“时间不对劲”，主要是震惊、验证和在心里记下仇人名单，还不急着大复仇。\n"
            "- 第3章起：今生正式开始各种复仇与反击，可以结合事件簇做小阶段设计。"
        )
    else:
        parts.append(
            "\n【结构提醒】\n"
            f"- 第{batch_start}章以后都是今生剧情，可以穿插上一世的短回忆，但重点是这批章节里的具体复仇行动和局面变化。\n"
            "- 可以把每两三章看作一个小阶段：先铺垫冲突，再反杀收尾，让读者经常有新爽点。"
        )

    if prior_summary:
        parts.append("\n【前情简要】（供你承接剧情用，不要重复抄写）")
        parts.append(prior_summary)

    if cluster_overview:
        parts.append(cluster_overview)

    parts.append(
        "\n【输出格式】\n"
        "必须按章节顺序依次输出，每一章单独一段，格式严格如下（示例）：\n"
        "第1章 病床终章：她奄奄一息躺在 ICU 病床上，耳边是全网骂她“杀人凶手”的声音。"
        "医生和家属在她面前商量放弃抢救的签字，她想伸手却连呼吸都疼得发抖。"
        "上一世的这一刻，她什么都做不了，只能记住每一张冷漠的脸。\n"
        "第2章 ……（照此格式继续）\n"
        "\n"
        "要求：\n"
        "- 每一章都要有【简短标题】+【2〜4 句梗概】；\n"
        "- 句子要写清楚：当章最核心冲突和对手、与上一世对应悲剧的呼应点、今生具体的反杀/布局动作、当章的小结果和结尾钩子；\n"
        "- 不要只写“第N章 标题：XXX”这一行，禁止只给标题没有内容；\n"
        "- 不要使用 markdown 标题（如 ##），也不要写成长篇正文，只写梗概。"
    )

    return "\n".join(parts)


def build_outline_system_prompt_soft(adapted_samples=None) -> str:
    """比原脚本更温和的系统提示：保留关键规则，但弱化“口令式”硬限制，减少模型复读感。"""
    base = """
你是擅长写「重生复仇爽文短剧」的大纲编剧。
我会提供：
- 一份已经规划好的事件簇列表（每个簇对应若干章的核心爽点）；
- 以及前面已经写出的梗概摘要（前情）。

你的任务：
- 按照章节顺序，写出每一章的简要梗概；
- 在保证“这一章的主要冲突和爽点要落在对应的事件簇上”的前提下，灵活安排铺垫、对照和反杀；
- 尽量让每一两章就有一次情绪明显的爽点或反转，保证短剧的节奏感。

世界与类型设定：
- 现代都市背景，主角是女主【沈清欢】（唯一女主名），重生后对上一世的仇人进行系统性复仇；
- 类型始终是：都市职场复仇 + 医疗阴谋揭露 + 舆论反转；
- 复仇方式主要是：布局、证据、职场博弈、法律与舆论，而不是黑帮火拼或纯动作戏。

上一世 / 今生关系（只作写作参考，不必每句都点明）：
- 上一世：她在这些相似场景中一次次被甩锅、被抛弃、被压下去，最后死在 ICU；
- 今生：她提前记住这些节点，靠记忆、专业能力和布局，在相同或相似的场景里反向拿回主动权。

写作风格：
- 不需要堆满条款式“必须/禁止”，更希望你像正常网文编剧一样自然地铺陈故事；
- 但请始终记得：每个章节的“主冲突”和“主爽点”要和对应的事件簇保持一致，不要写跑题。"""
    if adapted_samples:
        sample_texts = []
        for i, s in enumerate(adapted_samples, 1):
            sample_texts.append(
                f"【样本{i}】情绪：{', '.join(s.get('emotion_tags', []))}；情节：{', '.join(s.get('plot_tags', []))}；节选：{s.get('content', '')[:120]}..."
            )
        base += "\n\n【可以参考的高情绪样本】\n" + "\n\n".join(sample_texts)
    return base.strip()


def _summarize_outline_for_context(text: str, max_chars: int = 1500) -> str:
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return ""
    combined = "\n".join(lines)
    if len(combined) <= max_chars:
        return combined
    return combined[:max_chars] + "……（后文省略，按整体气质继续写即可）"


def _parse_chapter_lines_to_cards(lines: List[str]) -> List[Dict[str, Any]]:
    """将「第N章 标题：若干句梗概」的行解析为简易章节卡 JSON 结构。

    JSON 结构参考原来的 master_ctx_cards.json，但这里只填充最核心字段，
    其他字段先占位为空字符串或默认值，保证下游代码兼容。
    """
    cards: List[Dict[str, Any]] = []
    pattern = re.compile(r"^第(\d+)章[：:\s]*(.*)$")

    for raw in lines:
        m = pattern.match(raw)
        if not m:
            continue
        ch_id = int(m.group(1))
        rest = m.group(2).strip()
        # 尝试从“标题：内容”中拆分
        title = ""
        content = ""
        if "：" in rest:
            title, content = rest.split("：", 1)
            title = title.strip()
            content = content.strip()
        elif ":" in rest:
            title, content = rest.split(":", 1)
            title = title.strip()
            content = content.strip()
        else:
            title = rest
            content = ""

        present_mainline = (title + ("：" + content if content else "")).strip()

        card: Dict[str, Any] = {
            "chapter_id": ch_id,
            "arc_id": "A01",
            "chapter_role": "present_only",
            "present_mainline": present_mainline,
            "core_conflict": "",
            "flashback_trigger": "",
            "revenge_action": "",
            "ending_hook": "",
            "global_seed_progress": "",
            "chapter_constraints": [],
            # 兼容旧字段，占位
            "conflict_opponent": "",
            "past_trigger": "",
            "past_core_harm": "",
            "present_result": "",
            "tail_clue": "",
            "closure_type": "full_close",
        }
        cards.append(card)

    # 按 chapter_id 排序
    cards.sort(key=lambda x: x.get("chapter_id", 0))
    return cards


def generate_outline_from_event_clusters(batch_size: int = 5) -> None:
    """主入口：只读取现有 event_clusters.json，按簇重新生成章节梗概，不改写簇本身。

    同时输出：
    - 文本版章节梗概（含标题+2~4句）：master_ctx_from_clusters_*.txt
    - 结构化章节卡 JSON：master_ctx_cards_from_clusters_*.json
    - 上一世遭遇线索梗概：prev_life_ctx_from_clusters_*.txt
    """
    project_name = "重生复仇短剧"
    print("=" * 60)
    print(f"基于现有事件簇，为《{project_name}》重新生成章节梗概（不改动 event_clusters.json）")
    print("=" * 60)

    clusters = load_event_clusters()
    print(f"已读取事件簇数量：{len(clusters)} 个\n")

    # 准备少量样本，引导情绪，不写死规则
    base_query = "重生复仇短剧，女主沈清欢，现代都市 + 医疗阴谋 + 职场反杀，极致委屈 + 高密度爽点。"
    adapted_samples = search_and_adapt_samples(
        user_input=base_query,
        target_context="重生、复仇、现代都市、医疗、爽文、短剧",
        top_k=3,
        min_similarity=0.3,
    )
    system_prompt = build_outline_system_prompt_soft(adapted_samples)

    all_outline_lines: List[str] = []
    all_cards: List[Dict[str, Any]] = []
    prior_summary = ""

    for batch_idx in range(0, 100, batch_size):
        start = batch_idx + 1
        end = min(batch_idx + batch_size, 100)
        print(f"生成章节梗概：第 {start}-{end} 章...")

        cluster_overview = build_cluster_overview_for_batch(clusters, start, end)
        user_query = build_batch_user_query_from_clusters(
            start, end, prior_summary, cluster_overview
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query},
        ]
        raw = call_qianwen_api(messages)
        if not raw or raw.startswith("通义千问"):
            # 简单兜底：占位行，便于后续人工修
            for ch in range(start, end + 1):
                all_outline_lines.append(f"第{ch}章：占位梗概（生成失败，待补充）。")
            continue

        # 按行拆分，过滤掉明显跑题内容
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        # 有些情况下模型会重复前情，这里做个粗过滤：只保留以“第X章”开头的行
        cleaned: List[str] = []
        for ln in lines:
            if ln.startswith("第") and "章" in ln:
                cleaned.append(ln)
        if not cleaned:
            cleaned = lines

        all_outline_lines.extend(cleaned)
        batch_cards = _parse_chapter_lines_to_cards(cleaned)
        all_cards.extend(batch_cards)
        # 更新前情摘要
        prior_summary = _summarize_outline_for_context("\n".join(all_outline_lines))

    # 统一保存：不覆盖原 master_ctx / master_ctx_cards，只写到新的文件名里
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = os.path.join(OUTPUT_DIR, f"master_ctx_from_clusters_{ts}.txt")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(all_outline_lines))

    # 生成并保存 JSON 章节卡（格式参考原 master_ctx_cards.json）
    # 兜底：保证 1~100 都有一条
    seen_ids = {c.get("chapter_id") for c in all_cards}
    for ch in range(1, 101):
        if ch not in seen_ids:
            all_cards.append(
                {
                    "chapter_id": ch,
                    "arc_id": "A01",
                    "chapter_role": "present_only",
                    "present_mainline": f"第{ch}章：占位梗概（生成失败，待补充）。",
                    "core_conflict": "",
                    "flashback_trigger": "",
                    "revenge_action": "",
                    "ending_hook": "",
                    "global_seed_progress": "",
                    "chapter_constraints": [],
                    "conflict_opponent": "",
                    "past_trigger": "",
                    "past_core_harm": "",
                    "present_result": "",
                    "tail_clue": "",
                    "closure_type": "full_close",
                }
            )
    all_cards.sort(key=lambda x: x.get("chapter_id", 0))

    cards_path = os.path.join(
        OUTPUT_DIR, f"master_ctx_cards_from_clusters_{ts}.json"
    )
    with open(cards_path, "w", encoding="utf-8") as f:
        json.dump(all_cards, f, ensure_ascii=False, indent=2)

    # 基于整本梗概，再生成上一世遭遇线索点（prev_life_ctx_from_clusters）
    outline_text = "\n\n".join(all_outline_lines)
    print(f"\n✅ 基于事件簇的章节梗概已生成：{txt_path}")
    print(f"✅ 结构化章节卡 JSON 已生成：{cards_path}")

    print("\n开始基于梗概生成上一世遭遇线索点（prev_life）...\n")
    prev_life_system_prompt = build_prev_life_outline_system_prompt()
    analysis_text = analyze_outline_for_prev_life(outline_text)
    if analysis_text and not analysis_text.startswith("通义千问"):
        print("  上一世分析完成，将按批次生成线索。")
    else:
        print("  上一世分析失败，将不携带分析结果继续生成。")
        analysis_text = ""

    prev_life_parts: List[str] = []
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
        batch_out = call_qianwen_api(messages)
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
    prev_main = os.path.join(
        OUTPUT_DIR, f"prev_life_ctx_from_clusters_{ts}.txt"
    )
    with open(prev_main, "w", encoding="utf-8") as f:
        f.write(prev_life_text)

    print(f"✅ 上一世遭遇线索点已生成：{prev_main}")
    print("前 15 行预览：\n")
    for i, line in enumerate(all_outline_lines[:15], 1):
        print(f"{i:02d}: {line}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="基于 outputs/event_clusters.json 生成章节梗概（不改写事件簇）"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="每批生成的章节数量，默认 5 章",
    )
    args = parser.parse_args()
    generate_outline_from_event_clusters(batch_size=args.batch_size)


if __name__ == "__main__":
    main()


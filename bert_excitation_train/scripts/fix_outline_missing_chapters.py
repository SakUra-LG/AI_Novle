#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复已生成梗概中「生成失败/占位」的章节：
- 读取 outputs/master_ctx_cards.json + master_ctx.txt + prev_life_ctx.txt
- 自动识别占位章节（present_mainline 为空或包含“占位梗概（生成失败，待补充）”）
- 在全书梗概和前后章节上下文的约束下，调用大模型补齐缺失章节卡
- 写出修复后的 master_ctx_cards_fixed.json / master_ctx_fixed.txt

注意：
- 本脚本不会覆盖原文件，只生成 *_fixed.* 版本，方便人工对比后再决定是否替换。
- 复用 generate_outline_rebirth_revenge.py 中的 call_qianwen_api 辅助函数和约束风格。
"""

import os
import json
from typing import List, Dict, Any, Tuple

from datetime import datetime

from generate_outline_rebirth_revenge import (
    SCRIPT_DIR,
    PROJECT_ROOT,
    OUTPUT_DIR,
    call_qianwen_api,
    _render_cards_to_outline_text,
)


def _load_master_cards(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("master_ctx_cards.json 内容不是列表")
    return data


def _load_text_file(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _find_placeholder_chapters(cards: List[Dict[str, Any]]) -> List[int]:
    """识别 present_mainline 为空或包含“占位梗概（生成失败，待补充）”的章节号。"""
    missing = []
    for c in cards:
        ch = c.get("chapter_id")
        if not isinstance(ch, int):
            continue
        pm = (c.get("present_mainline") or "").strip()
        if (not pm) or ("占位梗概（生成失败，待补充）" in pm):
            missing.append(ch)
    return sorted(set(missing))


def _build_repair_prompt_for_chapter(
    chapter_id: int,
    all_cards: List[Dict[str, Any]],
    master_ctx_text: str,
    prev_life_ctx_text: str,
) -> str:
    """构造修复单个章节卡的提示词，带上下文约束。"""
    # 前后章节卡
    prev_card = next((c for c in all_cards if c.get("chapter_id") == chapter_id - 1), None)
    next_card = next((c for c in all_cards if c.get("chapter_id") == chapter_id + 1), None)

    def _card_brief(c: Dict[str, Any]) -> str:
        if not c:
            return "（无）"
        return json.dumps(
            {
                "chapter_id": c.get("chapter_id"),
                "arc_id": c.get("arc_id"),
                "chapter_role": c.get("chapter_role"),
                "present_mainline": c.get("present_mainline"),
                "core_conflict": c.get("core_conflict"),
                "flashback_trigger": c.get("flashback_trigger"),
                "revenge_action": c.get("revenge_action"),
                "ending_hook": c.get("ending_hook"),
                "global_seed_progress": c.get("global_seed_progress"),
            },
            ensure_ascii=False,
        )

    # 对应章节的上一世线索（若存在）
    prev_life_line = ""
    if prev_life_ctx_text:
        for line in prev_life_ctx_text.splitlines():
            if line.strip().startswith(f"第{chapter_id}章对应线索"):
                prev_life_line = line.strip()
                break

    # 截取整本梗概前几千字符，避免 prompt 过长
    master_ctx_snippet = master_ctx_text[:4000] + ("...\n（已截断）" if len(master_ctx_text) > 4000 else "")

    prompt = f"""
你现在是一名资深的「重生复仇短剧」大纲编剧助手。
我已经为整本《重生复仇短剧》生成了 100 章的结构化章节卡（JSON），但其中部分章节是占位符，需要你在**不改变整本故事设定与总体走向**的前提下，补写缺失章节。

【整本章节梗概摘要（文本版，仅供你把握整体走向，禁止改设定）】
{master_ctx_snippet}

【第{chapter_id}章的前后章节卡简要（请严格对齐，不得改写已有设定）】
- 前一章卡片：
{_card_brief(prev_card)}
- 后一章卡片：
{_card_brief(next_card)}

【第{chapter_id}章当前状态】
- 章节号：{chapter_id}
- 现有章节卡：present_mainline 为空或为“占位梗概（生成失败，待补充）”，需要你重新生成一条完整章节卡。

【对应的上一世线索（若有，仅供参考，不可改设定）】
{prev_life_line or "（可能暂无或未找到对应线索）"}

【任务要求】
1. 请为“第{chapter_id}章”生成**一条结构化章节卡 JSON 对象**，字段必须包含：
   - "chapter_id": {chapter_id}
   - "arc_id": 字符串，需与前后章节在主线/阶段上保持合理连续（如 A01/A02/A03 等）；
   - "chapter_role": "revenge_payoff" / "grievance_build" / "present_only" / "cross_chapter" 之一，且要符合前后章节的节奏；
   - "present_mainline": 本章今生主线的一句话（短剧式，具体到场景与动作）；
   - "core_conflict": 本章的核心矛盾/对手意图，需与整本书的“重生复仇+医疗阴谋+职场/家族”大方向一致；
   - "flashback_trigger": 当下剧情中触发上一世回忆的具体事件（若本章无需插入上一世，可写为空字符串）；
   - "revenge_action": 女主在本章采取的具体反制/复仇/埋线动作（若为纯铺垫章，可写“暂时隐忍、暗中收集线索”等，也要具体）；
   - "ending_hook": 本章结尾抛出的钩子或悬念，要能自然衔接后一章；
   - "global_seed_progress": 本章对整本书“最大复仇主线种子”的**轻微推进**（0~1句），若本章不推进则写空字符串 ""；
   - "chapter_constraints": 数组，每个元素是一条**本章写作限制**说明，例如“本章不许出现实质复仇行动，只能铺垫”和“本章必须完成一次小复仇闭环”等。
2. 本章内容必须：
   - 与整本梗概（master_ctx.txt）在故事体系上一致，不得引入全新大 Boss 或完全不同的终极目标；
   - 与前一章、后一章在情节和情绪上自然过渡，有合理的因果或时间顺序；
   - 保持本书的类型：都市职场/家族复仇 + 医疗阴谋 + 舆论/法律，禁止写成玄幻/修仙/武打。
3. **禁止**：
   - 改写前、后一章卡片中的设定；
   - 推翻已存在的复仇主线蓝图（谁害死她、要怎么一步步反杀的大方向）；
   - 输出多个对象或数组，只能输出**一个 JSON 对象**。

【输出格式（必须严格遵守）】
- 只输出一个 JSON 对象，不要数组，不要多余文字、标题或注释。
- 所有字段名必须使用英文双引号。
"""
    return prompt


def _repair_single_chapter_card(
    chapter_id: int,
    cards: List[Dict[str, Any]],
    master_ctx_text: str,
    prev_life_ctx_text: str,
) -> Dict[str, Any]:
    """调用大模型修复某一章的章节卡。"""
    prompt = _build_repair_prompt_for_chapter(chapter_id, cards, master_ctx_text, prev_life_ctx_text)
    messages = [
        {"role": "system", "content": "你是重生复仇短剧的大纲修复助手，只能在既有设定基础上补完缺失章节卡。"},
        {"role": "user", "content": prompt},
    ]
    raw = call_qianwen_api(messages)
    if not raw or raw.startswith("通义千问"):
        raise RuntimeError(f"修复第{chapter_id}章失败：{raw}")
    raw = raw.strip()
    # 尝试从文本中截取第一个 '{' 到最后一个 '}' 作为 JSON 对象
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"第{chapter_id}章修复返回无法解析为 JSON：{raw[:200]}...")
    try:
        obj = json.loads(raw[start:end + 1])
    except Exception as e:
        raise ValueError(f"第{chapter_id}章修复 JSON 解析失败：{e}，原始片段：{raw[:200]}...")
    # 补字段
    obj.setdefault("chapter_id", chapter_id)
    obj.setdefault("arc_id", "A01")
    obj.setdefault("chapter_role", "present_only")
    obj.setdefault("present_mainline", "")
    obj.setdefault("core_conflict", "")
    obj.setdefault("flashback_trigger", "")
    obj.setdefault("revenge_action", "")
    obj.setdefault("ending_hook", "")
    obj.setdefault("global_seed_progress", "")
    if "chapter_constraints" not in obj or not isinstance(obj["chapter_constraints"], list):
        obj["chapter_constraints"] = []
    return obj


def fix_missing_chapters():
    """主流程：修复 master_ctx_cards.json 中的占位章节卡，并生成 *_fixed.* 输出。"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    master_cards_path = os.path.join(OUTPUT_DIR, "master_ctx_cards.json")
    master_ctx_path = os.path.join(OUTPUT_DIR, "master_ctx.txt")
    prev_life_path = os.path.join(OUTPUT_DIR, "prev_life_ctx.txt")

    if not os.path.exists(master_cards_path):
        print(f"❌ 未找到 {master_cards_path}，请先运行 generate_outline_rebirth_revenge.py 生成梗概。")
        return

    cards = _load_master_cards(master_cards_path)
    master_ctx_text = _load_text_file(master_ctx_path)
    prev_life_ctx_text = _load_text_file(prev_life_path)

    missing = _find_placeholder_chapters(cards)
    if not missing:
        print("✅ 未发现占位梗概章节，无需修复。")
        return

    print(f"⚠️ 检测到 {len(missing)} 个占位章节需修复：{missing}")

    # 逐章修复
    id_to_card = {c.get("chapter_id"): c for c in cards if isinstance(c.get("chapter_id"), int)}
    for ch in missing:
        print(f"\n🔧 正在修复第{ch}章...")
        try:
            fixed = _repair_single_chapter_card(ch, cards, master_ctx_text, prev_life_ctx_text)
        except Exception as e:
            print(f"  ❌ 第{ch}章修复失败：{e}")
            continue
        id_to_card[ch] = fixed
        print(f"  ✅ 第{ch}章修复完成：{fixed.get('present_mainline', '')[:80]}...")

    # 按章节号重建列表
    fixed_cards = [id_to_card[k] for k in sorted(id_to_card.keys())]

    # 写出修复版 JSON
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fixed_cards_path = os.path.join(OUTPUT_DIR, f"master_ctx_cards_fixed_{ts}.json")
    with open(fixed_cards_path, "w", encoding="utf-8") as f:
        json.dump(fixed_cards, f, ensure_ascii=False, indent=2)
    print(f"\n💾 已写出修复后的章节卡 JSON：{fixed_cards_path}")

    # 同时渲染一份新的文本梗概，方便人工查看
    fixed_outline_text = _render_cards_to_outline_text(fixed_cards)
    fixed_outline_path = os.path.join(OUTPUT_DIR, f"master_ctx_fixed_{ts}.txt")
    with open(fixed_outline_path, "w", encoding="utf-8") as f:
        f.write(fixed_outline_text)
    print(f"💾 已写出修复后的文本梗概：{fixed_outline_path}")

    print("\n✅ 修复流程完成。请人工对比 master_ctx.txt 与 master_ctx_fixed_*.txt，确认无误后再决定是否替换正式文件。")


def main():
    fix_missing_chapters()


if __name__ == "__main__":
    main()


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单章重生成脚本（考虑上一章和下一章的衔接）

用途：
- 当某一章正文质量不满意时，只重生成这一章；
- 在正常生成逻辑基础上，额外读取「下一章」的梗概和已有正文开头，
  给当前章的结尾加一层“向后衔接”的提示，减少上下文割裂。

用法示例：

  # 在项目根目录运行，重生成第7章
  python scripts/regenerate_single_chapter.py --chapter 7

可选参数：
- --master-ctx / --prev-life-ctx 与 generate_chapter_content.py 一致，不传则自动选择：
  - 梗概：优先 outputs/master_ctx_cards.json，其次 master_ctx_final.txt，最后 master_ctx.txt
  - 上一世线索：优先 outputs/prev_life_ctx_final.txt，否则 prev_life_ctx.txt
"""

from pathlib import Path
from typing import Optional

from generate_chapter_content import RebirthRevengeGenerator, DEFAULT_OUTPUTS_DIR
from knowledge_graph import RebirthKnowledgeGraph


def _auto_choose_master_ctx() -> str:
    """按优先级自动选择梗概文件路径（相对路径形式）"""
    if (DEFAULT_OUTPUTS_DIR / "master_ctx_cards.json").exists():
        return "outputs/master_ctx_cards.json"
    if (DEFAULT_OUTPUTS_DIR / "master_ctx_final.txt").exists():
        return "outputs/master_ctx_final.txt"
    return "outputs/master_ctx.txt"


def _auto_choose_prev_life() -> str:
    """按优先级自动选择上一世线索文件路径（相对路径形式）"""
    if (DEFAULT_OUTPUTS_DIR / "prev_life_ctx_final.txt").exists():
        return "outputs/prev_life_ctx_final.txt"
    return "outputs/prev_life_ctx.txt"


def _get_next_chapter_outline(gen: RebirthRevengeGenerator, chapter_num: int) -> str:
    """获取下一章的梗概（若为 JSON 卡则渲染为可读文本）。"""
    raw = gen.master_ctx.get(chapter_num + 1, "")
    if not raw:
        return ""
    card = gen._parse_json_maybe(raw)
    if card:
        try:
            return gen._render_master_card_for_prompt(card)
        except Exception:
            return str(raw)
    return str(raw)


def _get_next_chapter_head(gen: RebirthRevengeGenerator, chapter_num: int) -> str:
    """获取下一章已生成正文的开头片段（若存在），用于向后衔接提示。"""
    # 复用 get_previous_chapter_content：传入 chapter_num+2，即“上一章”为 chapter+1
    full = gen.get_previous_chapter_content(chapter_num + 2)
    if not full:
        return ""
    full = full.strip()
    return full[:200]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="单章重生成（考虑上一章与下一章衔接）")
    parser.add_argument("--chapter", type=int, required=True, help="要重生成的章节号，例如 7")
    parser.add_argument("--master-ctx", type=str, default=None, help="章节梗概文件路径（默认自动选择）")
    parser.add_argument("--prev-life-ctx", type=str, default=None, help="上一世线索文件路径（默认自动选择）")
    parser.add_argument("--versions", type=int, default=1, help="本章生成版本数")
    parser.add_argument("--iterations", type=int, default=2, help="每版本最大迭代次数")
    parser.add_argument("--min-emotion", type=float, default=0.5, help="最小情绪强度阈值")

    args = parser.parse_args()
    ch = args.chapter

    print("=" * 80)
    print(f"🔁 单章重生成：第{ch}章（将考虑第{ch-1}章尾钩 + 第{ch+1}章走向）")
    print("=" * 80)

    # 先回滚知识图谱并删除旧的正文文件
    kg_path = DEFAULT_OUTPUTS_DIR / "knowledge_graph.json"
    ch_dir = DEFAULT_OUTPUTS_DIR / "chapters"
    if kg_path.exists():
        kg = RebirthKnowledgeGraph(kg_path)
        if kg.load():
            removed = kg.remove_records_by_chapters([ch])
            kg.save()
            print(f"  [KG] 已从知识图谱中移除来源自第{ch}章的 {removed} 条记录")
    chapter_file = ch_dir / f"chapter_{ch:03d}.txt"
    if chapter_file.exists():
        chapter_file.unlink()
        print(f"  [KG] 已删除旧正文文件: {chapter_file}")

    gen = RebirthRevengeGenerator()

    master_path = args.master_ctx or _auto_choose_master_ctx()
    prev_path = args.prev_life_ctx or _auto_choose_prev_life()

    print(f"  使用梗概文件: {master_path}")
    print(f"  使用上一世线索: {prev_path}")

    gen.load_contexts(master_path, prev_path)
    gen.load_existing_chapters()

    # 构造“下一章衔接提示”，注入到生成提示词中
    next_outline = _get_next_chapter_outline(gen, ch)
    next_head = _get_next_chapter_head(gen, ch)

    next_hint_lines = []
    if next_outline or next_head:
        next_hint_lines.append("【下一章衔接硬约束】（仅本次单章重生成生效）")
        if next_outline:
            next_hint_lines.append("下一章梗概摘要：")
            next_hint_lines.append(next_outline)
        if next_head:
            next_hint_lines.append("下一章已生成正文开头片段：")
            next_hint_lines.append(next_head)
        next_hint_lines.append(
            "本章结尾的场景与人物状态必须使上述内容可以自然发生，"
            "禁止出现时间线/人物关系/关键事实上的明显矛盾。"
        )
    gen._next_chapter_hint = "\n".join(next_hint_lines) if next_hint_lines else ""

    # 调用已有的节拍卡+正文生成逻辑（会在 prompt 中附加 _next_chapter_hint）
    content = gen.generate_one_chapter_with_beats(
        ch,
        num_versions=args.versions,
        max_iterations=args.iterations,
        min_emotion_intensity=args.min_emotion,
    )

    if content:
        print(f"\n✅ 第{ch}章重生成完成，并已写入 outputs/chapters/chapter_{ch:03d}.txt")
    else:
        print(f"\n❌ 第{ch}章重生成失败，请检查日志")


if __name__ == "__main__":
    main()


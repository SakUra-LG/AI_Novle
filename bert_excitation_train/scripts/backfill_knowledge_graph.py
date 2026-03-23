#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据已生成的章节正文，批量补录知识图谱。

典型场景：
- 早期章节（如 1-11）生成时未启用知识图谱同步，需要后补；
- 只想把现有 chapter_XXX.txt 重新抽取入图谱，不重写正文。
"""

from pathlib import Path
from typing import List, Set

import dashscope

from knowledge_graph import RebirthKnowledgeGraph

API_Key_QW = "sk-a2966f4e37134351904851679884cb67"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUTS = PROJECT_ROOT / "outputs"
DEFAULT_CHAPTER_DIR = DEFAULT_OUTPUTS / "chapters"
DEFAULT_KG_PATH = DEFAULT_OUTPUTS / "knowledge_graph.json"


def _call_llm(prompt: str) -> str:
    """调用通义千问，用于知识图谱抽取。返回模型输出文本。"""
    dashscope.api_key = API_Key_QW
    try:
        response = dashscope.Generation.call(
            model=dashscope.Generation.Models.qwen_turbo,
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": "请按要求输出JSON"}],
            temperature=0.3,
            result_format="message",
        )
        if "output" in response and "choices" in response["output"]:
            return (response["output"]["choices"][0].get("message", {}).get("content") or "").strip()
    except Exception:
        pass
    return ""


def _parse_chapters(raw: List[str]) -> List[int]:
    """
    解析章节参数：
    - 支持离散：1 2 3 10
    - 支持区间：1-11
    - 支持混合：1-3 8 10-12
    """
    result: Set[int] = set()
    for token in raw:
        part = token.strip()
        if not part:
            continue
        if "-" in part:
            seg = part.split("-", 1)
            if len(seg) == 2 and seg[0].strip().isdigit() and seg[1].strip().isdigit():
                start, end = int(seg[0].strip()), int(seg[1].strip())
                if start > end:
                    start, end = end, start
                for ch in range(start, end + 1):
                    result.add(ch)
            else:
                raise ValueError(f"非法章节区间: {part}")
        else:
            if not part.isdigit():
                raise ValueError(f"非法章节号: {part}")
            result.add(int(part))
    return sorted(result)


def _chapter_file(chapter_dir: Path, chapter: int) -> Path:
    return chapter_dir / f"chapter_{chapter:03d}.txt"


def main():
    import argparse

    parser = argparse.ArgumentParser(description="从现有正文批量补录知识图谱")
    parser.add_argument(
        "--chapters",
        nargs="+",
        default=["1-11"],
        help="要补录的章节号，支持: 1-11 或 1 2 3 10",
    )
    parser.add_argument(
        "--chapter-dir",
        type=str,
        default=str(DEFAULT_CHAPTER_DIR),
        help="正文目录，默认 outputs/chapters",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_KG_PATH),
        help="图谱输出路径，默认 outputs/knowledge_graph.json",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="写入前先删除图谱中这些章节对应的旧记录",
    )
    args = parser.parse_args()

    chapters = _parse_chapters(args.chapters)
    if not chapters:
        print("[WARN] 未解析到任何章节，退出")
        return

    chapter_dir = Path(args.chapter_dir)
    if not chapter_dir.is_absolute():
        chapter_dir = (PROJECT_ROOT / chapter_dir).resolve()

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = (PROJECT_ROOT / out_path).resolve()

    kg = RebirthKnowledgeGraph(out_path)
    kg.load()  # 存在则增量合并；不存在则从空开始

    if args.overwrite:
        removed = kg.remove_records_by_chapters(chapters)
        print(f"[KG] 已删除图谱中来源章节 {chapters} 的 {removed} 条旧记录")

    ok, fail, miss = 0, 0, 0
    for ch in chapters:
        fp = _chapter_file(chapter_dir, ch)
        if not fp.exists():
            miss += 1
            print(f"[SKIP] 第{ch}章文件不存在: {fp}")
            continue
        text = fp.read_text(encoding="utf-8").strip()
        if not text:
            fail += 1
            print(f"[WARN] 第{ch}章文件为空，跳过")
            continue
        try:
            if kg.extract_from_chapter_body_with_llm(text, ch, _call_llm):
                ok += 1
                print(f"[OK] 第{ch}章补录成功")
            else:
                fail += 1
                print(f"[WARN] 第{ch}章抽取失败")
        except Exception as e:
            fail += 1
            print(f"[ERR] 第{ch}章异常: {e}")

    kg.save()
    print(f"\n[SAVE] 知识图谱已保存: {out_path}")
    print(f"[DONE] 成功 {ok} 章，失败 {fail} 章，缺失文件 {miss} 章")
    print(f"       实体: {len(kg.entities)}, 关系: {len(kg.relationships)}, 伏笔: {len(kg.foreshadowing)}")


if __name__ == "__main__":
    main()


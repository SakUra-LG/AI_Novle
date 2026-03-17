#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回溯知识图谱：删除指定章节相关的图谱记录
用于重做某几章正文前，先清理图谱，再删除正文文件，再重新生成
"""

from pathlib import Path
from typing import List

from knowledge_graph import RebirthKnowledgeGraph

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH = PROJECT_ROOT / "outputs" / "knowledge_graph.json"
DEFAULT_CHAPTERS_DIR = PROJECT_ROOT / "outputs" / "chapters"


def _parse_chapter_arg(s: str) -> List[int]:
    """解析 --chapters 6 7 8 9 10 或 6-10"""
    s = s.strip()
    if "-" in s and not s.startswith("-"):
        try:
            a, b = s.split("-", 1)
            return list(range(int(a.strip()), int(b.strip()) + 1))
        except ValueError:
            pass
    parts = [p.strip() for p in s.replace(",", " ").split() if p.strip()]
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            pass
    return sorted(set(out))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="回溯知识图谱：删除指定章节的图谱记录")
    parser.add_argument("--chapters", type=str, required=True, help="要删除的章节，如 6 7 8 9 10 或 6-10")
    parser.add_argument("--graph", type=str, default=None, help="图谱文件路径")
    parser.add_argument("--delete-files", action="store_true", help="同时删除 outputs/chapters/ 下对应章节的 txt 文件")
    args = parser.parse_args()

    chapters = _parse_chapter_arg(args.chapters)
    if not chapters:
        print("[ERR] 未解析到有效章节号，示例: --chapters 6 7 8 9 10 或 --chapters 6-10")
        return

    graph_path = Path(args.graph) if args.graph else DEFAULT_GRAPH
    if not graph_path.is_absolute():
        graph_path = (PROJECT_ROOT / graph_path).resolve()

    kg = RebirthKnowledgeGraph(graph_path)
    if not kg.load():
        print(f"[WARN] 图谱文件不存在: {graph_path}，无需回滚")
        return

    removed = kg.remove_records_by_chapters(chapters)
    kg.save()
    print(f"[OK] 已删除 {removed} 条来源自章节 {chapters} 的记录，图谱已保存")

    if args.delete_files:
        ch_dir = DEFAULT_CHAPTERS_DIR
        deleted = 0
        for ch in chapters:
            f = ch_dir / f"chapter_{ch:03d}.txt"
            if f.exists():
                f.unlink()
                deleted += 1
                print(f"   已删除: {f}")
        if deleted:
            print(f"   共删除 {deleted} 个正文文件")
        else:
            print("   未找到对应正文文件")


if __name__ == "__main__":
    main()

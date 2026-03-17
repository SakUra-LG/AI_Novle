#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据章节梗概初始化知识图谱（大模型抽取）
从 master_ctx / master_ctx_final 和 prev_life_ctx 抽取实体、关系、伏笔，写入 knowledge_graph.json
"""

import re
import json
from pathlib import Path
from typing import Optional

import dashscope
from knowledge_graph import RebirthKnowledgeGraph, SOURCE_OUTLINE

API_Key_QW = "sk-a2966f4e37134351904851679884cb67"


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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUTS = PROJECT_ROOT / "outputs"


def _parse_chapters(content: str) -> dict:
    """解析梗概文件，返回 chapter_num -> 原文"""
    result = {}
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 单章形式：第N章 ...：梗概
        # 允许在“第N章”和冒号之间出现角色/类型等说明（如：第1章（grievance_build）：……）
        m = re.match(r"^第(\d+)章.*?[：:]\s*(.+)$", line)
        if m:
            ch = int(m.group(1))
            result[ch] = m.group(2).strip()
            continue
        m = re.match(r"^第(\d+)-(\d+)章\s+(.+)$", line)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            body = m.group(3).strip()
            if "：" in body:
                body = body.split("：", 1)[1].strip()
            elif ":" in body:
                body = body.split(":", 1)[1].strip()
            for ch in range(start, end + 1):
                result[ch] = body
    return result


def _parse_json_maybe(text: Optional[str]) -> Optional[dict]:
    if not text or not (str(text).strip().startswith("{") and "}" in str(text)):
        return None
    try:
        return json.loads(text.strip())
    except Exception:
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="根据梗概初始化知识图谱")
    parser.add_argument("--master", type=str, default=None, help="章节梗概文件，默认 outputs/master_ctx_final.txt")
    parser.add_argument("--prev-life", type=str, default=None, help="上一世线索，默认 outputs/prev_life_ctx_final.txt")
    parser.add_argument("--output", type=str, default=None, help="图谱输出路径，默认 outputs/knowledge_graph.json")
    args = parser.parse_args()

    if args.master:
        master_path = (PROJECT_ROOT / args.master).resolve() if not Path(args.master).is_absolute() else Path(args.master)
    else:
        # 优先使用结构化 JSON 章节卡，其次修正后梗概，最后原始梗概
        cards_cand = DEFAULT_OUTPUTS / "master_ctx_cards.json"
        final_cand = DEFAULT_OUTPUTS / "master_ctx_final.txt"
        txt_cand = DEFAULT_OUTPUTS / "master_ctx.txt"
        if cards_cand.exists():
            master_path = cards_cand
        elif final_cand.exists():
            master_path = final_cand
        else:
            master_path = txt_cand
        master_path = master_path.resolve()
    if args.prev_life:
        prev_path = (PROJECT_ROOT / args.prev_life).resolve() if not Path(args.prev_life).is_absolute() else Path(args.prev_life)
    else:
        cand = DEFAULT_OUTPUTS / "prev_life_ctx_final.txt"
        prev_path = cand if cand.exists() else (DEFAULT_OUTPUTS / "prev_life_ctx.txt")
        prev_path = prev_path.resolve()
    out_path = Path(args.output) if args.output else DEFAULT_OUTPUTS / "knowledge_graph.json"
    if not out_path.is_absolute():
        out_path = (PROJECT_ROOT / out_path).resolve()

    kg = RebirthKnowledgeGraph(out_path)
    kg.load()  # 若存在则合并，否则从空开始

    prev_life_by_ch: dict = {}
    if prev_path.exists():
        for line in prev_path.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            m = re.match(r"^第(\d+)章对应线索\s*[：:]\s*(.+)$", line)
            if m:
                prev_life_by_ch[int(m.group(1))] = m.group(2).strip()

    def _build_outline_text(raw: str, card: Optional[dict]) -> str:
        if card and isinstance(card, dict):
            p = card.get("present") or {}
            b = card.get("binding") or {}
            if isinstance(p, str):
                p = {}
            if isinstance(b, str):
                b = {}
            parts = [
                str(p.get("present_mainline", "")),
                str(p.get("flashback_trigger", "")),
                str(p.get("revenge_action") or p.get("revenue_action", "")),
                str(b.get("past_core_harm", "")),
                str(b.get("present_counterstrike", "")),
            ]
            return " ".join(p for p in parts if p)
        return raw

    if master_path.exists():
        print(f"[INFO] 使用梗概文件初始化知识图谱: {master_path}")
        # 若为 JSON 章节卡，则逐个章节卡构造 outline 文本
        if master_path.suffix.lower() == ".json":
            try:
                data = json.loads(master_path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[WARN] 解析 JSON 梗概失败: {e}")
                data = []
            chapters = {}
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    ch = item.get("chapter_id")
                    if not isinstance(ch, int):
                        continue
                    # 直接将卡序列化为 JSON 字符串，供 _parse_json_maybe + _build_outline_text 使用
                    chapters[ch] = json.dumps(item, ensure_ascii=False)
            else:
                print("[WARN] JSON 梗概内容不是列表，将跳过 JSON 结构，仅依赖文本梗概（若有）。")
            ok = 0
            for ch, raw in sorted(chapters.items()):
                card = _parse_json_maybe(raw)
                text = _build_outline_text(raw, card)
                prev_text = prev_life_by_ch.get(ch, "")
                if kg.extract_from_outline_with_llm(text, ch, _call_llm, prev_text):
                    ok += 1
                else:
                    print(f"  [WARN] 第{ch}章抽取失败，跳过")
            print(f"[OK] 已从 JSON 梗概章节卡大模型抽取 {ok}/{len(chapters)} 章")
        else:
            content = master_path.read_text(encoding="utf-8")
            chapters = _parse_chapters(content)
            ok = 0
            for ch, raw in sorted(chapters.items()):
                card = _parse_json_maybe(raw)
                text = _build_outline_text(raw, card)
                prev_text = prev_life_by_ch.get(ch, "")
                if kg.extract_from_outline_with_llm(text, ch, _call_llm, prev_text):
                    ok += 1
                else:
                    print(f"  [WARN] 第{ch}章抽取失败，跳过")
            print(f"[OK] 已从梗概大模型抽取 {ok}/{len(chapters)} 章")
    else:
        print(f"[WARN] 未找到梗概文件: {master_path}")

    kg.save()
    print(f"[SAVE] 知识图谱已保存: {out_path}")
    print(f"   实体: {len(kg.entities)}, 关系: {len(kg.relationships)}, 伏笔: {len(kg.foreshadowing)}")


if __name__ == "__main__":
    main()

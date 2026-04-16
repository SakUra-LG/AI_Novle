#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SemEval2025-Task11 输出格式适配脚本。

说明:
- SemEval 仓库本身更偏任务/数据，不是即插即用推理服务。
- 本脚本将项目现有情绪分析结果映射到 SemEval Track A/B 风格输出，便于对齐评测格式。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

# 允许以脚本方式从项目根外部直接运行
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = None
for p in CURRENT_FILE.parents:
    if (p / "scripts").is_dir():
        PROJECT_ROOT = p
        break
if PROJECT_ROOT is None:
    raise RuntimeError("无法定位项目根目录（未找到 scripts 目录）")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.semantic_emotion_methods.handwritten.manual_semantic_emotion_scorer import ManualSemanticEmotionScorer


def _to_semeval_scores(distribution: Dict[str, float]) -> Dict[str, float]:
    joy = distribution.get("joy", 0.0) + 0.5 * distribution.get("excitement", 0.0) + 0.3 * distribution.get("anticipation", 0.0)
    sadness = distribution.get("sadness", 0.0) + 0.4 * distribution.get("tension", 0.0)
    fear = distribution.get("fear", 0.0) + 0.6 * distribution.get("tension", 0.0)
    anger = distribution.get("anger", 0.0)
    surprise = distribution.get("surprise", 0.0)
    disgust = distribution.get("disgust", 0.0)

    raw = {
        "joy": joy,
        "sadness": sadness,
        "fear": fear,
        "anger": anger,
        "surprise": surprise,
        "disgust": disgust,
    }
    m = max(raw.values()) if raw else 0.0
    if m <= 0:
        return {k: 0.0 for k in raw}
    return {k: min(1.0, v / m) for k, v in raw.items()}


def analyze_text(text: str, threshold: float = 0.25) -> Dict[str, object]:
    scorer = ManualSemanticEmotionScorer()
    r = scorer.analyze(text)

    semeval_scores = _to_semeval_scores(r.emotion_distribution)
    track_a = {k: int(v >= threshold) for k, v in semeval_scores.items()}
    track_b = {k: int(round(v * 3)) for k, v in semeval_scores.items()}

    return {
        "track_a_multilabel": track_a,
        "track_b_intensity_0_3": track_b,
        "track_b_continuous_0_1": {k: round(v, 4) for k, v in semeval_scores.items()},
        "source_manual_distribution": {k: round(v, 4) for k, v in r.emotion_distribution.items()},
        "source_top_emotion": r.top_emotion,
        "source_polarity": round(r.polarity, 4),
    }


def run_interactive(threshold: float) -> None:
    print("已进入 SemEval2025 适配交互模式。输入 exit 退出。")
    while True:
        text = input("\n请输入中文文本: ").strip()
        if text.lower() in {"exit", "quit", "q"}:
            print("已退出。")
            break
        print(json.dumps(analyze_text(text, threshold=threshold), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="SemEval2025 Task11 输出适配 CLI")
    parser.add_argument("--text", type=str, default="", help="单句模式；为空则进入交互")
    parser.add_argument("--threshold", type=float, default=0.25, help="Track A 二值阈值")
    args = parser.parse_args()

    if args.text.strip():
        print(json.dumps(analyze_text(args.text, threshold=args.threshold), ensure_ascii=False, indent=2))
    else:
        run_interactive(threshold=args.threshold)


if __name__ == "__main__":
    main()

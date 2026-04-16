#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VAD-MacBERT 接入脚本（评分为主，分类可选补充）。

默认模型: Pectics/vad-macbert
功能:
1) 输出 VAD 连续值: valence/arousal/dominance
2) 输出 0~1 的综合强度评分
3) 可选使用现有手写规则补充情绪类型分类
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, Optional

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

try:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
except Exception as exc:  # pragma: no cover
    raise ImportError(
        "缺少依赖，请先安装: .\\.venv312\\Scripts\\python.exe -m pip install transformers torch"
    ) from exc

from scripts.semantic_emotion_methods.handwritten.manual_semantic_emotion_scorer import ManualSemanticEmotionScorer


@dataclass
class VadResult:
    valence: float
    arousal: float
    dominance: float
    intensity_score: float
    aux_classification: Dict[str, Any]


class VadMacbertAnalyzer:
    def __init__(self, model_name: str = "Pectics/vad-macbert") -> None:
        self.model_name = model_name
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.model.eval()
        self.manual = ManualSemanticEmotionScorer()

    @staticmethod
    def _sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))

    def analyze(self, text: str, classify_method: str = "manual") -> VadResult:
        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=128,
        )
        with torch.no_grad():
            logits = self.model(**inputs).logits.squeeze().tolist()

        if not isinstance(logits, list) or len(logits) != 3:
            raise RuntimeError(f"VAD 输出异常: {logits}")

        valence, arousal, dominance = [float(x) for x in logits]

        # 将原始回归值映射到 0~1 的可读强度分（用于统一下游）
        valence_term = abs(math.tanh(valence))
        arousal_term = self._sigmoid(arousal)
        dominance_term = self._sigmoid(-dominance)  # 越失控通常越强烈
        intensity = 0.45 * arousal_term + 0.35 * valence_term + 0.20 * dominance_term
        intensity = float(max(0.0, min(1.0, intensity)))

        aux: Dict[str, Any] = {"method": "none"}
        if classify_method == "manual":
            r = self.manual.analyze(text)
            aux = {
                "method": "manual",
                "top_emotion": r.top_emotion,
                "top_emotion_score": round(r.top_emotion_score, 4),
                "polarity": round(r.polarity, 4),
                "emotion_distribution": {k: round(v, 4) for k, v in r.emotion_distribution.items()},
            }

        return VadResult(
            valence=valence,
            arousal=arousal,
            dominance=dominance,
            intensity_score=intensity,
            aux_classification=aux,
        )


def print_result(result: VadResult) -> None:
    payload = {
        "vad_scoring": {
            "valence": round(result.valence, 4),
            "arousal": round(result.arousal, 4),
            "dominance": round(result.dominance, 4),
            "intensity_score": round(result.intensity_score, 4),
        },
        "aux_classification": result.aux_classification,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def run_interactive(analyzer: VadMacbertAnalyzer, classify_method: str) -> None:
    print("已进入 VAD-MacBERT 交互模式。输入 exit 退出。")
    while True:
        text = input("\n请输入中文文本: ").strip()
        if text.lower() in {"exit", "quit", "q"}:
            print("已退出。")
            break
        print_result(analyzer.analyze(text=text, classify_method=classify_method))


def main() -> None:
    parser = argparse.ArgumentParser(description="VAD-MacBERT 情绪评分 CLI")
    parser.add_argument("--model-name", type=str, default="Pectics/vad-macbert", help="HuggingFace 模型名或本地目录")
    parser.add_argument(
        "--classify-method",
        type=str,
        choices=["none", "manual"],
        default="manual",
        help="补充情绪分类方法（建议 manual）",
    )
    parser.add_argument("--text", type=str, default="", help="单句模式；为空则进入交互")
    args = parser.parse_args()

    analyzer = VadMacbertAnalyzer(model_name=args.model_name)
    if args.text.strip():
        print_result(analyzer.analyze(text=args.text, classify_method=args.classify_method))
    else:
        run_interactive(analyzer, classify_method=args.classify_method)


if __name__ == "__main__":
    main()

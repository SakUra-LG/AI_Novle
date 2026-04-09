#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手写语义+情绪评分方法

目标：
1) 当前情绪分类（多类别）
2) 当前情绪强度评分（连续值 0~1）
3) 情绪标定（calibration）+ 量化（quantization）
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class EmotionScoreResult:
    top_emotion: str
    top_emotion_score: float
    intensity_raw: float
    intensity_calibrated: float
    intensity_level: str
    emotion_distribution: Dict[str, float]
    polarity: float


class ManualSemanticEmotionScorer:
    """
    规则手写版语义情绪分析器。

    说明：
    - 参考了项目中 `emotion_analyzer.py` 的多维情绪和强度融合思路；
    - 额外加入了“否定词翻转”“程度副词增益”“转折句加权”；
    - 提供统一的情绪标定 + 分级量化接口。
    """

    EMOTION_LEXICON: Dict[str, List[str]] = {
        "joy": ["喜悦", "快乐", "开心", "高兴", "欣喜", "幸福", "满足", "轻松", "欢喜"],
        "sadness": ["悲伤", "难过", "痛苦", "失落", "伤心", "哀伤", "沮丧", "绝望"],
        "anger": ["愤怒", "生气", "恼火", "暴怒", "气愤", "愤恨", "憎恨", "怒火"],
        "fear": ["恐惧", "害怕", "惊恐", "畏惧", "恐慌", "不安", "颤抖", "战栗"],
        "surprise": ["惊讶", "震惊", "诧异", "意外", "吃惊", "惊奇", "惊愕"],
        "disgust": ["厌恶", "反感", "恶心", "讨厌", "憎恶", "嫌弃"],
        "anticipation": ["期待", "盼望", "渴望", "期望", "等待", "憧憬", "希望"],
        "tension": ["紧张", "焦虑", "忐忑", "紧绷", "警觉", "压抑", "压迫"],
        "excitement": ["激动", "兴奋", "热血", "激昂", "澎湃", "沸腾"],
    }

    NEGATIONS = ["不", "没", "无", "非", "未", "别", "并不", "毫不"]
    INTENSIFIERS = {
        "非常": 1.35,
        "特别": 1.30,
        "极其": 1.45,
        "十分": 1.25,
        "很": 1.10,
        "太": 1.20,
        "略微": 0.75,
        "有点": 0.80,
    }
    TURNING_WORDS = ["但是", "然而", "却", "不过", "只是", "尽管"]

    def analyze(self, text: str) -> EmotionScoreResult:
        text = (text or "").strip()
        if not text:
            return EmotionScoreResult(
                top_emotion="neutral",
                top_emotion_score=0.0,
                intensity_raw=0.0,
                intensity_calibrated=0.0,
                intensity_level="very_low",
                emotion_distribution={},
                polarity=0.0,
            )

        sentence_scores = self._score_sentences(text)
        merged_scores = self._merge_sentence_scores(sentence_scores)
        top_emotion, top_score = self._top_emotion(merged_scores)

        raw_intensity = self._raw_intensity(text, merged_scores)
        calibrated = self.calibrate_intensity(raw_intensity)
        level = self.quantize_intensity(calibrated)
        polarity = self._polarity(merged_scores)

        return EmotionScoreResult(
            top_emotion=top_emotion,
            top_emotion_score=top_score,
            intensity_raw=raw_intensity,
            intensity_calibrated=calibrated,
            intensity_level=level,
            emotion_distribution=merged_scores,
            polarity=polarity,
        )

    def calibrate_intensity(self, raw_intensity: float) -> float:
        """
        标定方法：
        - 先对原始分数做截断；
        - 再做 logistic 校准，把中间段拉开，便于分层。
        """
        clipped = max(0.0, min(1.0, raw_intensity))
        # 中心点 0.45，斜率 6.0：兼顾中强情绪段的可分辨性
        calibrated = 1.0 / (1.0 + math.exp(-6.0 * (clipped - 0.45)))
        return float(max(0.0, min(1.0, calibrated)))

    def quantize_intensity(self, calibrated_intensity: float) -> str:
        """
        量化等级：
        very_low / low / medium / high / very_high
        """
        x = max(0.0, min(1.0, calibrated_intensity))
        if x < 0.20:
            return "very_low"
        if x < 0.40:
            return "low"
        if x < 0.60:
            return "medium"
        if x < 0.80:
            return "high"
        return "very_high"

    def _score_sentences(self, text: str) -> List[Dict[str, float]]:
        sentences = [s.strip() for s in re.split(r"[。！？!?;\n]", text) if s.strip()]
        if not sentences:
            sentences = [text]

        out: List[Dict[str, float]] = []
        for idx, sent in enumerate(sentences):
            base = self._score_single_sentence(sent)
            # 后置句（尤其转折后）通常语义更关键，给轻微增益
            if idx >= 1:
                boost = 1.08 if any(w in sent for w in self.TURNING_WORDS) else 1.03
                base = {k: min(1.0, v * boost) for k, v in base.items()}
            out.append(base)
        return out

    def _score_single_sentence(self, sentence: str) -> Dict[str, float]:
        scores = {k: 0.0 for k in self.EMOTION_LEXICON.keys()}
        length = max(len(sentence), 1)

        for emotion, words in self.EMOTION_LEXICON.items():
            for word in words:
                if word not in sentence:
                    continue

                occurrences = len(re.findall(re.escape(word), sentence))
                strength = occurrences * (len(word) / 2.0)

                # 局部窗口检测否定和程度副词
                for m in re.finditer(re.escape(word), sentence):
                    left = sentence[max(0, m.start() - 4): m.start()]
                    right = sentence[m.end(): min(len(sentence), m.end() + 2)]
                    local = left + right

                    if any(neg in left for neg in self.NEGATIONS):
                        strength *= 0.60
                    for adv, ratio in self.INTENSIFIERS.items():
                        if adv in local:
                            strength *= ratio

                scores[emotion] += strength

            # 句长归一化，避免长句天然偏高
            scores[emotion] = min(1.0, scores[emotion] / (length / 12.0 + 1.0))

        total = sum(scores.values())
        if total > 0:
            scores = {k: float(v / total) for k, v in scores.items()}
        return scores

    def _merge_sentence_scores(self, sentence_scores: List[Dict[str, float]]) -> Dict[str, float]:
        merged = {k: 0.0 for k in self.EMOTION_LEXICON.keys()}
        if not sentence_scores:
            return merged

        for i, one in enumerate(sentence_scores):
            weight = 1.0 + (i / max(len(sentence_scores) - 1, 1)) * 0.15
            for k, v in one.items():
                merged[k] += v * weight

        total = sum(merged.values())
        if total > 0:
            merged = {k: float(v / total) for k, v in merged.items()}
        return merged

    def _raw_intensity(self, text: str, distribution: Dict[str, float]) -> float:
        dominant = max(distribution.values()) if distribution else 0.0

        punctuation_force = min(1.0, (text.count("！") + text.count("!") + text.count("？") + text.count("?")) / 6.0)
        turn_force = min(1.0, sum(text.count(w) for w in self.TURNING_WORDS) / 4.0)

        complexity = sum(1 for v in distribution.values() if v > 0.12)
        complexity_force = min(1.0, complexity / 4.0)

        # 参考现有工程中的融合思路，突出“主导情绪 + 文体信号 + 转折/复杂度”
        raw = (
            0.50 * dominant
            + 0.20 * punctuation_force
            + 0.15 * turn_force
            + 0.15 * complexity_force
        )
        return float(max(0.0, min(1.0, raw)))

    def _top_emotion(self, distribution: Dict[str, float]) -> Tuple[str, float]:
        if not distribution:
            return "neutral", 0.0
        top = max(distribution.items(), key=lambda x: x[1])
        if top[1] < 0.08:
            return "neutral", float(top[1])
        return top[0], float(top[1])

    def _polarity(self, distribution: Dict[str, float]) -> float:
        pos = distribution.get("joy", 0.0) + distribution.get("anticipation", 0.0) + distribution.get("excitement", 0.0)
        neg = distribution.get("sadness", 0.0) + distribution.get("anger", 0.0) + distribution.get("fear", 0.0) + distribution.get("disgust", 0.0)
        return float(max(-1.0, min(1.0, pos - neg)))


def demo() -> None:
    scorer = ManualSemanticEmotionScorer()
    texts = [
        "她听见门外急促的脚步声，心脏猛地一沉，但还是强迫自己冷静下来。",
        "他终于等到了消息，压在心里的石头落地，忍不住笑了出来。",
        "走廊很安静，大家都在低头整理资料，空气平淡得几乎没有波澜。",
    ]
    for t in texts:
        r = scorer.analyze(t)
        print("=" * 60)
        print("文本:", t)
        print("当前情绪:", r.top_emotion, f"({r.top_emotion_score:.3f})")
        print("强度(raw -> calibrated):", f"{r.intensity_raw:.3f} -> {r.intensity_calibrated:.3f}")
        print("强度等级:", r.intensity_level)
        print("极性:", f"{r.polarity:.3f}")


if __name__ == "__main__":
    demo()

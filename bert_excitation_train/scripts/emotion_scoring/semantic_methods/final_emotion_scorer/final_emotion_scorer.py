#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最终版语义情绪评分脚本。

输出两类核心结果：
1. 当前文本涉及的情绪类型，以及各类型占比。
2. 占比最高的主情绪，以及该主情绪的 1~5 级强度。

设计原则：
- 纯本地规则评分，默认不依赖外部模型或网络。
- 尽量复用 scripts/emotion_level 下已有五级样本生成器的硬约束。
- 对幽默强度做增强校准，兼容 humor_level 目录中 1~5 级产出。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple


def _add_project_to_path() -> None:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if parent.name == "bert_excitation_train" and (parent / "scripts").exists():
            package_parent = parent.parent
            if str(package_parent) not in sys.path:
                sys.path.insert(0, str(package_parent))
            return


_add_project_to_path()


try:
    from bert_excitation_train.scripts.emotion_scoring.emotion_level.humor_level.humor_level_generator import (
        HUMOR_CUE_WORDS as PROJECT_HUMOR_CUES,
        HUMOR_LEVEL_HARD_CONSTRAINTS,
        estimate_humor_metrics as project_estimate_humor_metrics,
    )
except Exception:  # pragma: no cover - standalone fallback
    PROJECT_HUMOR_CUES = []
    HUMOR_LEVEL_HARD_CONSTRAINTS = {
        1: {"humor_min": 3, "humor_max": 6, "dialogue_min_ratio": 0.40},
        2: {"humor_min": 6, "humor_max": 10, "dialogue_min_ratio": 0.50},
        3: {"humor_min": 10, "humor_max": 14, "dialogue_min_ratio": 0.60},
        4: {"humor_min": 14, "humor_max": 19, "dialogue_min_ratio": 0.65},
        5: {"humor_min": 18, "humor_max": 26, "dialogue_min_ratio": 0.70},
    }
    project_estimate_humor_metrics = None


try:
    from bert_excitation_train.scripts.emotion_scoring.emotion_level.anger_level.anger_level_generator import (
        ANGER_CUE_WORDS,
        ANGER_LEVEL_HARD_CONSTRAINTS,
        estimate_anger_metrics,
    )
except Exception:  # pragma: no cover
    ANGER_CUE_WORDS = []
    ANGER_LEVEL_HARD_CONSTRAINTS = {}
    estimate_anger_metrics = None


try:
    from bert_excitation_train.scripts.emotion_scoring.emotion_level.grievance_level.grievance_level_generator import (
        GRIEVANCE_CUE_WORDS,
        GRIEVANCE_LEVEL_HARD_CONSTRAINTS,
        estimate_grievance_metrics,
    )
except Exception:  # pragma: no cover
    GRIEVANCE_CUE_WORDS = []
    GRIEVANCE_LEVEL_HARD_CONSTRAINTS = {}
    estimate_grievance_metrics = None


try:
    from bert_excitation_train.scripts.emotion_scoring.emotion_level.touching_level.touching_level_generator import (
        BODY_REACTION_WORDS as TOUCHING_BODY_REACTION_WORDS,
        KINDNESS_CUE_WORDS,
        RELEASE_CUE_WORDS,
        TOUCHING_CUE_WORDS,
        TOUCHING_LEVEL_HARD_CONSTRAINTS,
        WARMTH_CUE_WORDS,
        estimate_touching_metrics,
    )
except Exception:  # pragma: no cover
    TOUCHING_BODY_REACTION_WORDS = []
    KINDNESS_CUE_WORDS = []
    RELEASE_CUE_WORDS = []
    TOUCHING_CUE_WORDS = []
    TOUCHING_LEVEL_HARD_CONSTRAINTS = {}
    WARMTH_CUE_WORDS = []
    estimate_touching_metrics = None


try:
    from bert_excitation_train.scripts.emotion_scoring.emotion_level.thriller_level.thriller_level_generator import (
        FEAR_CUE_WORDS,
        THRILLER_LEVEL_HARD_CONSTRAINTS,
        estimate_thriller_metrics,
    )
except Exception:  # pragma: no cover
    FEAR_CUE_WORDS = []
    THRILLER_LEVEL_HARD_CONSTRAINTS = {}
    estimate_thriller_metrics = None


ZH_NAME = {
    "humor": "幽默",
    "anger": "愤怒",
    "fear": "恐惧",
    "grievance": "委屈",
    "touching": "感动",
    "sadness": "悲伤",
    "joy": "喜悦",
    "surprise": "惊讶",
    "disgust": "厌恶",
    "tension": "紧张",
    "anticipation": "期待",
}


FALLBACK_LEXICON: Dict[str, List[str]] = {
    "humor": [
        "吐槽", "拆台", "互怼", "嘴硬", "反差", "自嘲", "歪楼", "一本正经",
        "忍不住笑", "笑出声", "苦笑", "噎住", "没好气", "白了他一眼",
        "顶回去", "哼声", "打趣", "调侃", "挤兑", "接梗", "好笑", "可笑",
        "逗", "乐了", "笑场", "哈哈", "噗", "翻白眼", "翻了个白眼",
        "气笑", "尴尬", "离谱", "搞笑", "图啥", "哎呀妈呀", "啥",
        "好不好", "嘛", "呀", "哟", "小家伙", "小鸡", "烤红薯",
        "跳广场舞", "打折促销", "正常营业", "推卸责任", "耍赖", "偷懒",
        "娇气", "踢踏舞", "黑心老板", "谈判", "谈条件", "不讲武德",
        "送死", "集体坠机", "嘴里的口水", "找罪受",
    ],
    "anger": [
        "愤怒", "怒", "怒火", "火气", "气得", "气笑", "冷笑", "冷声", "厉声",
        "发抖", "颤", "攥紧", "握紧", "青筋", "拍桌", "摔", "砸", "质问",
        "反问", "逼问", "怒视", "盯着", "荒唐", "过分", "欺人太甚",
        "凭什么", "不配", "闭嘴", "道歉", "清算", "王八蛋",
    ],
    "fear": [
        "恐惧", "害怕", "惊惧", "惊骇", "紧张", "发冷", "冰冷", "冷汗",
        "僵住", "发抖", "颤抖", "屏住呼吸", "窒息", "心跳", "头皮发麻",
        "后背发凉", "不安", "压迫", "阴冷", "黑暗", "寂静", "死寂",
        "惨白", "不敢", "失灵", "拼命", "门缝", "影子", "脚步", "敲门",
        "盯着", "窥视", "低语", "监控", "镜子", "倒影", "不存在",
    ],
    "grievance": [
        "委屈", "心酸", "难过", "失落", "憋屈", "憋闷", "难堪", "心寒",
        "寒心", "被冤枉", "冤枉", "百口莫辩", "有口难辩", "说不清",
        "没人听", "不相信", "不被看见", "被否定", "被误解", "误会",
        "被忽略", "被抛下", "被辜负", "被背叛", "被轻视", "红了眼",
    ],
    "touching": [
        "感动", "温暖", "暖", "心酸", "柔软", "被理解", "被看见", "被接住",
        "被托住", "托住", "理解", "懂", "关心", "善意", "心疼", "陪伴",
        "守护", "支持", "尊重", "接纳", "释怀", "和解", "安心", "安定",
        "希望", "救赎", "重新开始", "不是一个人", "握住", "抱住", "撑伞",
    ],
    "sadness": [
        "悲伤", "难过", "痛苦", "伤心", "哀伤", "沉痛", "绝望", "失落",
        "落泪", "眼泪", "哭", "哽咽", "鼻酸", "心碎", "孤独", "离别",
    ],
    "joy": [
        "喜悦", "快乐", "高兴", "开心", "兴奋", "欢快", "愉悦", "欣喜",
        "欢呼", "雀跃", "幸福", "满足", "畅快", "笑了", "笑起来",
    ],
    "surprise": [
        "惊讶", "震惊", "诧异", "意外", "吃惊", "惊奇", "惊愕", "愣住",
        "没想到", "突然发现", "目瞪口呆",
    ],
    "disgust": [
        "厌恶", "反感", "恶心", "讨厌", "憎恶", "嫌弃", "厌烦", "作呕",
    ],
    "tension": [
        "紧张", "焦虑", "忐忑", "绷紧", "警觉", "压抑", "压迫", "悬着",
        "屏息", "心口发紧", "不安", "迫在眉睫",
    ],
    "anticipation": [
        "期待", "盼望", "渴望", "希望", "等待", "憧憬", "即将", "终于",
        "快要", "就要",
    ],
}


def _merge_words(*word_groups: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for group in word_groups:
        for word in group or []:
            if word and word not in seen:
                seen.add(word)
                out.append(word)
    return sorted(out, key=len, reverse=True)


LEXICON: Dict[str, List[str]] = {
    "humor": _merge_words(PROJECT_HUMOR_CUES, FALLBACK_LEXICON["humor"]),
    "anger": _merge_words(ANGER_CUE_WORDS, FALLBACK_LEXICON["anger"]),
    "fear": _merge_words(FEAR_CUE_WORDS, FALLBACK_LEXICON["fear"]),
    "grievance": _merge_words(GRIEVANCE_CUE_WORDS, FALLBACK_LEXICON["grievance"]),
    "touching": _merge_words(
        TOUCHING_CUE_WORDS,
        KINDNESS_CUE_WORDS,
        WARMTH_CUE_WORDS,
        RELEASE_CUE_WORDS,
        TOUCHING_BODY_REACTION_WORDS,
        FALLBACK_LEXICON["touching"],
    ),
    "sadness": FALLBACK_LEXICON["sadness"],
    "joy": FALLBACK_LEXICON["joy"],
    "surprise": FALLBACK_LEXICON["surprise"],
    "disgust": FALLBACK_LEXICON["disgust"],
    "tension": FALLBACK_LEXICON["tension"],
    "anticipation": FALLBACK_LEXICON["anticipation"],
}


EMOTION_ORDER = [
    "humor",
    "anger",
    "fear",
    "grievance",
    "touching",
    "sadness",
    "joy",
    "surprise",
    "disgust",
    "tension",
    "anticipation",
]


TOUCHING_ANCHOR_WORDS = [
    "感动", "温暖", "暖意", "被理解", "被看见", "被接住", "被托住", "理解",
    "关心", "善意", "心疼", "陪伴", "守护", "支持", "释怀", "和解", "安心",
    "希望", "救赎", "不是一个人", "握住", "抱住", "撑伞", "伞", "留饭",
    "热汤", "热饮", "塞到", "轻声", "温声", "眼眶", "鼻酸", "松开",
]


@dataclass
class EmotionTypeResult:
    emotion: str
    emotion_zh: str
    proportion: float
    raw_score: float
    evidence: List[str] = field(default_factory=list)


@dataclass
class FinalEmotionResult:
    text_length: int
    emotion_types: List[EmotionTypeResult]
    main_emotion: str
    main_emotion_zh: str
    main_emotion_proportion: float
    main_intensity_level: int
    main_intensity_score: float
    main_intensity_label: str
    main_intensity_metrics: Dict[str, Any]
    neutral: bool = False
    version: str = "final_emotion_scorer_v1.0"

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["emotion_distribution"] = {
            item["emotion"]: item["proportion"] for item in payload["emotion_types"]
        }
        payload["emotion_distribution_zh"] = {
            item["emotion_zh"]: item["proportion"] for item in payload["emotion_types"]
        }
        return payload


def _split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"[。！？!?；;\n]+", text or "") if s.strip()]


def _dialogue_segments(text: str) -> List[str]:
    segments = re.findall(r'[“"「『]([^”"」』]{1,220})[”"」』]', text or "")
    if segments:
        return segments
    # 兼容没有引号、但用冒号标记对白的小说文本。
    return re.findall(r"[：:]\s*([^。！？!?\n]{1,120})", text or "")


def _count_hits(text: str, words: Iterable[str]) -> Tuple[float, Dict[str, int]]:
    evidence: Dict[str, int] = {}
    score = 0.0
    for word in words:
        if not word:
            continue
        count = text.count(word)
        if count <= 0:
            continue
        evidence[word] = count
        if len(word) == 1:
            weight = 0.45
        elif len(word) == 2:
            weight = 1.0
        else:
            weight = min(2.2, 1.0 + (len(word) - 2) * 0.18)
        score += count * weight
    return score, evidence


def _top_evidence(evidence: Mapping[str, int], limit: int = 8) -> List[str]:
    ranked = sorted(evidence.items(), key=lambda item: (item[1], len(item[0])), reverse=True)
    return [f"{word}×{count}" for word, count in ranked[:limit]]


def _level_label(level: int) -> str:
    return {
        1: "1级（轻微）",
        2: "2级（偏轻）",
        3: "3级（中等）",
        4: "4级（偏强）",
        5: "5级（最强）",
    }.get(level, f"{level}级")


def _bounded_level(value: float) -> int:
    return max(1, min(5, int(round(value))))


class FinalEmotionScorer:
    """规则融合版情绪类型占比与主情绪强度评分器。"""

    def __init__(self, min_proportion: float = 0.035) -> None:
        self.min_proportion = min_proportion

    def analyze(self, text: str) -> FinalEmotionResult:
        text = (text or "").strip()
        if not text:
            return FinalEmotionResult(
                text_length=0,
                emotion_types=[],
                main_emotion="neutral",
                main_emotion_zh="中性",
                main_emotion_proportion=0.0,
                main_intensity_level=1,
                main_intensity_score=0.0,
                main_intensity_label="1级（轻微）",
                main_intensity_metrics={},
                neutral=True,
            )

        raw_scores, evidence = self._score_emotion_types(text)
        total = sum(max(v, 0.0) for v in raw_scores.values())
        if total <= 0:
            return FinalEmotionResult(
                text_length=len(text),
                emotion_types=[],
                main_emotion="neutral",
                main_emotion_zh="中性",
                main_emotion_proportion=0.0,
                main_intensity_level=1,
                main_intensity_score=0.0,
                main_intensity_label="1级（轻微）",
                main_intensity_metrics={"reason": "未命中有效情绪线索"},
                neutral=True,
            )

        distribution = {k: v / total for k, v in raw_scores.items() if v > 0}
        main_emotion, main_prop = max(distribution.items(), key=lambda item: item[1])
        level, level_score, metrics = self._estimate_main_intensity(text, main_emotion)

        emotion_types = [
            EmotionTypeResult(
                emotion=emotion,
                emotion_zh=ZH_NAME.get(emotion, emotion),
                proportion=round(proportion, 4),
                raw_score=round(raw_scores[emotion], 4),
                evidence=_top_evidence(evidence.get(emotion, {})),
            )
            for emotion, proportion in sorted(distribution.items(), key=lambda item: item[1], reverse=True)
            if proportion >= self.min_proportion or emotion == main_emotion
        ]

        return FinalEmotionResult(
            text_length=len(text),
            emotion_types=emotion_types,
            main_emotion=main_emotion,
            main_emotion_zh=ZH_NAME.get(main_emotion, main_emotion),
            main_emotion_proportion=round(main_prop, 4),
            main_intensity_level=level,
            main_intensity_score=round(level_score, 4),
            main_intensity_label=_level_label(level),
            main_intensity_metrics=metrics,
        )

    def _score_emotion_types(self, text: str) -> Tuple[Dict[str, float], Dict[str, Dict[str, int]]]:
        sentences = _split_sentences(text)
        dialogue_count = len(_dialogue_segments(text))
        punctuation_force = text.count("！") + text.count("!") + text.count("？") + text.count("?")

        raw_scores: Dict[str, float] = {}
        evidence_by_emotion: Dict[str, Dict[str, int]] = {}
        for emotion in EMOTION_ORDER:
            base, evidence = _count_hits(text, LEXICON.get(emotion, []))
            raw_scores[emotion] = base
            evidence_by_emotion[emotion] = evidence

        # 结构性修正：幽默常通过对白、反差、拟人化、现代梗表达，不一定全靠固定词。
        humor_structure = self._humor_structure_score(text, dialogue_count)
        raw_scores["humor"] += humor_structure
        if humor_structure > 0:
            evidence_by_emotion["humor"]["幽默结构"] = max(1, int(round(humor_structure)))

        # 恐惧/紧张常共现；如果空间、感官与威胁线索密集，给恐惧一点额外权重。
        if raw_scores["fear"] > 0 and any(word in text for word in ["电梯", "走廊", "门", "监控", "镜子", "影子"]):
            raw_scores["fear"] *= 1.12

        # 愤怒的“怒/气”很容易被幽默文本借用，主情绪更像幽默时降低一点愤怒噪声。
        if raw_scores["humor"] >= raw_scores["anger"] * 0.75 and any(w in text for w in ["气笑", "嘴硬", "吐槽", "调侃", "啥", "嘛", "哟"]):
            raw_scores["anger"] *= 0.72

        # 感动与悲伤有交叉，若出现“温暖/托住/支持/希望”等治愈线索，感动优先。
        if raw_scores["touching"] > 0 and not any(word in text for word in TOUCHING_ANCHOR_WORDS):
            raw_scores["touching"] *= 0.05
        if raw_scores["touching"] > 0 and any(w in text for w in ["温暖", "被理解", "被接住", "希望", "守护", "陪伴"]):
            raw_scores["touching"] *= 1.18
            raw_scores["sadness"] *= 0.88

        # 过短文本用标点和句子情绪密度补一点强情绪信号，但不改变类别本身。
        if punctuation_force >= 2:
            for emotion in ("anger", "fear", "surprise", "humor"):
                if raw_scores[emotion] > 0:
                    raw_scores[emotion] += min(2.0, punctuation_force * 0.18)

        if len(sentences) >= 3:
            active_sentence_bonus = 0.0
            for sentence in sentences:
                active = sum(1 for emotion in EMOTION_ORDER if any(w in sentence for w in LEXICON.get(emotion, [])[:80]))
                if active >= 2:
                    active_sentence_bonus += 0.08
            if active_sentence_bonus:
                for emotion in EMOTION_ORDER:
                    if raw_scores[emotion] > 0:
                        raw_scores[emotion] += min(0.8, active_sentence_bonus)

        return raw_scores, evidence_by_emotion

    def _humor_structure_score(self, text: str, dialogue_count: int) -> float:
        score = 0.0
        anchor_words = [
            "吐槽", "拆台", "互怼", "调侃", "打趣", "自嘲", "反差", "笑",
            "哈哈", "噗", "尴尬", "离谱", "搞笑", "耍赖", "偷懒", "哎呀",
            "啥", "嘛", "哟", "好不好", "不讲武德", "打折促销", "正常营业",
        ]
        personified_absurdity = ["太阳", "月亮", "天庭", "天帝", "神仙", "泥人", "玉兔", "桂树"]
        has_humor_anchor = any(word in text for word in anchor_words)
        has_personified_dialogue = any(word in text for word in personified_absurdity) and dialogue_count >= 2

        if has_humor_anchor or has_personified_dialogue:
            score += min(8.0, dialogue_count * 0.65)

        rhetorical_patterns = [
            r"像[^。！？!?]{1,18}(一样|似的|般)",
            r"不是[^。！？!?]{1,16}而是",
            r"谁让",
            r"凭什么",
            r"我这是",
            r"你要不",
            r"能不能",
            r"等一下",
            r"救命",
        ]
        if has_humor_anchor or has_personified_dialogue:
            for pattern in rhetorical_patterns:
                score += len(re.findall(pattern, text)) * 0.9

        modern_punchlines = [
            "打卡", "营业", "老板", "促销", "库存", "预约", "复盘", "材料",
            "加载", "更新包", "防晒霜", "海景房", "家装", "承重墙",
        ]
        score += sum(text.count(word) for word in modern_punchlines) * 1.1

        if has_personified_dialogue:
            score += min(3.0, dialogue_count * 0.35)

        return score

    def _estimate_main_intensity(self, text: str, emotion: str) -> Tuple[int, float, Dict[str, Any]]:
        if emotion == "humor":
            return self._estimate_humor_level(text)
        if emotion == "anger" and estimate_anger_metrics and ANGER_LEVEL_HARD_CONSTRAINTS:
            return self._estimate_constraint_level(text, estimate_anger_metrics, ANGER_LEVEL_HARD_CONSTRAINTS, "anger")
        if emotion == "fear" and estimate_thriller_metrics and THRILLER_LEVEL_HARD_CONSTRAINTS:
            return self._estimate_constraint_level(text, estimate_thriller_metrics, THRILLER_LEVEL_HARD_CONSTRAINTS, "fear")
        if emotion == "grievance" and estimate_grievance_metrics and GRIEVANCE_LEVEL_HARD_CONSTRAINTS:
            return self._estimate_constraint_level(text, estimate_grievance_metrics, GRIEVANCE_LEVEL_HARD_CONSTRAINTS, "grievance")
        if emotion == "touching" and estimate_touching_metrics and TOUCHING_LEVEL_HARD_CONSTRAINTS:
            return self._estimate_constraint_level(text, estimate_touching_metrics, TOUCHING_LEVEL_HARD_CONSTRAINTS, "touching")
        return self._estimate_generic_level(text, emotion)

    def _estimate_humor_level(self, text: str) -> Tuple[int, float, Dict[str, Any]]:
        project_metrics = project_estimate_humor_metrics(text) if project_estimate_humor_metrics else {}
        base_hits, evidence = _count_hits(text, LEXICON["humor"])
        dialogue_segments = _dialogue_segments(text)
        dialogue_count = len(dialogue_segments)
        dialogue_text = "\n".join(dialogue_segments)
        dialogue_hits, _ = _count_hits(dialogue_text, LEXICON["humor"])
        dialogue_humor_ratio = round(dialogue_hits / base_hits, 3) if base_hits else 0.0

        structure_score = self._humor_structure_score(text, dialogue_count)
        length_factor = max(0.75, min(1.25, len(text) / 520.0))
        enhanced_hits = base_hits + structure_score
        normalized_hits = enhanced_hits / length_factor

        # 沿用 humor_level 的硬区间思想，同时保留一套针对现有幽默产物的梯度校准。
        nearest_level, nearest_penalty = self._nearest_count_level(
            normalized_hits,
            HUMOR_LEVEL_HARD_CONSTRAINTS,
            min_key="humor_min",
            max_key="humor_max",
        )

        # 现有幽默样本会大量通过对白、拟人化和现代梗制造笑点；如果直接把这些结构分
        # 当作硬线索，会把 2~3 级推成 5 级。这里把显式笑点、结构笑点、对白数量和
        # 对白笑点占比压到同一条温和刻度上。
        density = enhanced_hits / max(len(text) / 120.0, 1.0)
        calibration_index = (
            base_hits * 0.45
            + structure_score * 0.12
            + dialogue_count * 0.08
            + dialogue_humor_ratio * 0.80
        )
        if calibration_index < 3.2:
            level = 1
        elif calibration_index < 4.8:
            level = 2
        elif calibration_index < 6.4:
            level = 3
        elif calibration_index < 8.0:
            level = 4
        else:
            level = 5

        score = max(0.0, min(1.0, (level - 1) / 4.0 + min(0.08, density / 80.0)))
        metrics = {
            "method": "humor_level_constraints_enhanced",
            "project_metrics": project_metrics,
            "base_humor_hits": round(base_hits, 3),
            "structure_score": round(structure_score, 3),
            "enhanced_humor_hits": round(enhanced_hits, 3),
            "normalized_humor_hits": round(normalized_hits, 3),
            "dialogue_count": dialogue_count,
            "dialogue_humor_ratio": dialogue_humor_ratio,
            "calibration_index": round(calibration_index, 3),
            "nearest_constraint_level": nearest_level,
            "nearest_constraint_penalty": round(nearest_penalty, 3),
            "evidence": _top_evidence(evidence),
        }
        return level, score, metrics

    def _nearest_count_level(
        self,
        count: float,
        constraints: Mapping[int, Mapping[str, Any]],
        *,
        min_key: str,
        max_key: str,
    ) -> Tuple[int, float]:
        best_level = 1
        best_penalty = float("inf")
        for level, cfg in constraints.items():
            lo = float(cfg.get(min_key, 0.0))
            hi = float(cfg.get(max_key, lo))
            if lo <= count <= hi:
                penalty = 0.0
            else:
                edge = lo if count < lo else hi
                width = max(1.0, hi - lo)
                penalty = abs(count - edge) / width
            if penalty < best_penalty or (math.isclose(penalty, best_penalty) and int(level) > best_level):
                best_level = int(level)
                best_penalty = penalty
        return best_level, best_penalty

    def _estimate_constraint_level(
        self,
        text: str,
        metric_func: Callable[[str], Dict[str, Any]],
        constraints: Mapping[int, Mapping[str, Any]],
        emotion: str,
    ) -> Tuple[int, float, Dict[str, Any]]:
        metrics = dict(metric_func(text))
        best_level = 1
        best_penalty = float("inf")

        for level, cfg in constraints.items():
            penalty = 0.0
            for key, target in cfg.items():
                if key.endswith("_min"):
                    metric_key = key[:-4] + "_hits"
                    if metric_key not in metrics:
                        metric_key = key[:-4]
                    actual = float(metrics.get(metric_key, 0.0))
                    if actual < float(target):
                        penalty += (float(target) - actual) / max(float(target), 1.0)
                elif key.endswith("_max"):
                    metric_key = key[:-4] + "_hits"
                    if metric_key not in metrics:
                        metric_key = key[:-4]
                    actual = float(metrics.get(metric_key, 0.0))
                    if actual > float(target):
                        penalty += (actual - float(target)) / max(float(target), 1.0)
            if penalty < best_penalty or (math.isclose(penalty, best_penalty) and int(level) > best_level):
                best_level = int(level)
                best_penalty = penalty

        # 让短文本也可评分：若硬约束大多没命中，用线索密度兜底。
        cue_score, evidence = _count_hits(text, LEXICON.get(emotion, []))
        density = cue_score / max(len(text) / 120.0, 1.0)
        density_level = _bounded_level(1.0 + density * 0.55)
        if best_penalty > 1.8:
            level = density_level
        else:
            level = _bounded_level(0.75 * best_level + 0.25 * density_level)

        metrics.update(
            {
                "method": f"{emotion}_level_constraints",
                "constraint_level": best_level,
                "constraint_penalty": round(best_penalty, 3),
                "cue_score": round(cue_score, 3),
                "density_level": density_level,
                "evidence": _top_evidence(evidence),
            }
        )
        return level, max(0.0, min(1.0, level / 5.0)), metrics

    def _estimate_generic_level(self, text: str, emotion: str) -> Tuple[int, float, Dict[str, Any]]:
        cue_score, evidence = _count_hits(text, LEXICON.get(emotion, []))
        sentences = _split_sentences(text)
        emotion_sentence_count = sum(1 for sentence in sentences if any(word in sentence for word in LEXICON.get(emotion, [])))
        sentence_ratio = emotion_sentence_count / max(len(sentences), 1)
        punctuation = text.count("！") + text.count("!") + text.count("？") + text.count("?")
        density = cue_score / max(len(text) / 120.0, 1.0)
        value = 1.0 + density * 0.50 + sentence_ratio * 1.6 + min(0.6, punctuation * 0.08)
        level = _bounded_level(value)
        score = max(0.0, min(1.0, level / 5.0))
        return level, score, {
            "method": "generic_density_sentence_intensity",
            "cue_score": round(cue_score, 3),
            "emotion_sentence_ratio": round(sentence_ratio, 3),
            "punctuation_force": punctuation,
            "evidence": _top_evidence(evidence),
        }


def score_text(text: str) -> Dict[str, Any]:
    return FinalEmotionScorer().analyze(text).to_dict()


def _read_input(args: argparse.Namespace) -> str:
    if args.text:
        return args.text
    if args.file:
        return Path(args.file).read_text(encoding=args.encoding)
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return _read_interactive_text()


def _read_interactive_text() -> str:
    print("请输入待评分文本。可粘贴多行内容，输入空行后开始分析：")
    lines: List[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "" and lines:
            break
        if line == "" and not lines:
            print("内容不能为空，请继续输入：")
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="最终版情绪类型占比与主情绪强度评分")
    parser.add_argument("--text", help="直接传入待分析文本")
    parser.add_argument("--file", help="读取 UTF-8 文本文件进行分析")
    parser.add_argument("--encoding", default="utf-8", help="--file 的文本编码，默认 utf-8")
    parser.add_argument("--min-proportion", type=float, default=0.035, help="输出情绪类型的最小占比")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    text = _read_input(args)
    result = FinalEmotionScorer(min_proportion=args.min_proportion).analyze(text).to_dict()
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()

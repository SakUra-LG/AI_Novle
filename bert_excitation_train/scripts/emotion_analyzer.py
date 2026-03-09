#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度情绪分析工具 - 多维度、多层次的情绪识别系统

本模块提供：
1. 多维度情绪分类（喜悦、悲伤、愤怒、恐惧、惊讶、厌恶、期待等）
2. 情绪强度深度量化（表层情绪 vs 深层情绪）
3. 情绪转折检测（情绪变化趋势）
4. 情绪词汇密度分析
5. 上下文情绪连贯性分析

旨在让评分系统能够捕捉文本中更细腻、更触动心弦的情绪层次。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple


@dataclass
class EmotionResult:
    """结构化的深度情绪分析结果"""

    label: str = "neutral"
    confidence: float = 0.0
    scores: Optional[Dict[str, float]] = None
    intensity: float = 0.0
    error: Optional[str] = None
    
    # 新增：多维度情绪
    emotion_dimensions: Dict[str, float] = field(default_factory=dict)
    """多维度情绪得分：joy, sadness, anger, fear, surprise, disgust, anticipation"""
    
    # 新增：情绪深度
    surface_emotion: str = "neutral"
    """表层情绪（直接表达）"""
    deep_emotion: str = "neutral"
    """深层情绪（隐含情感）"""
    emotion_depth: float = 0.0
    """情绪深度得分（0-1，越高越深层）"""
    
    # 新增：情绪转折
    emotion_transition: Optional[str] = None
    """情绪转折类型：rising, falling, stable, mixed"""
    transition_strength: float = 0.0
    """转折强度"""
    
    # 新增：情绪密度
    emotion_word_density: float = 0.0
    """情绪词汇密度"""
    emotion_sentence_density: float = 0.0
    """包含情绪表达的句子比例"""
    
    # 新增：情绪复杂度
    emotion_complexity: float = 0.0
    """情绪复杂度（多种情绪并存的程度）"""


class EmotionAnalyzer:
    """
    深度情绪分析器 - 多维度、多层次的情绪识别系统
    
    结合了：
    1. 预训练情感分类模型（HuggingFace）
    2. 中文情绪词典（多维度情绪识别）
    3. 情绪强度与深度分析
    4. 情绪转折检测
    """

    DEFAULT_MODEL = "uer/roberta-base-finetuned-jd-binary-chinese"
    
    # 中文多维度情绪词典
    EMOTION_LEXICON = {
        'joy': ['喜悦', '快乐', '高兴', '开心', '兴奋', '欢快', '愉悦', '欣喜', '狂喜', 
                '满足', '幸福', '欣慰', '畅快', '痛快', '爽', '乐', '笑', '喜'],
        'sadness': ['悲伤', '难过', '痛苦', '伤心', '哀伤', '沮丧', '绝望', '失落', 
                   '忧郁', '愁', '泪', '哭', '泣', '痛', '苦', '哀', '悲'],
        'anger': ['愤怒', '生气', '恼火', '暴怒', '愤恨', '怒火', '气愤', '狂怒', 
                 '怒', '火', '气', '愤', '恼', '恨'],
        'fear': ['恐惧', '害怕', '惊恐', '畏惧', '恐慌', '胆怯', '战栗', '颤抖', 
                '惊', '恐', '怕', '惧', '慌', '颤', '抖', '栗'],
        'surprise': ['惊讶', '惊奇', '震惊', '诧异', '意外', '吃惊', '惊愕', 
                    '惊', '讶', '奇', '震', '愕'],
        'disgust': ['厌恶', '反感', '恶心', '讨厌', '憎恶', '嫌弃', '厌', '恶', '烦'],
        'anticipation': ['期待', '盼望', '渴望', '期望', '等待', '希冀', '憧憬', 
                        '盼', '望', '期', '待', '渴', '希'],
        'tension': ['紧张', '紧绷', '焦虑', '不安', '担心', '忧虑', '忐忑', 
                   '紧', '张', '焦', '虑', '担', '忧'],
        'excitement': ['激动', '兴奋', '激昂', '热血', '澎湃', '沸腾', 
                      '激', '奋', '昂', '沸'],
    }

    def __init__(
        self,
        model_name: Optional[str] = None,
        max_length: int = 256,
        device: Optional[str] = None,
        auto_initialize: bool = False,
        enable_deep_analysis: bool = True,
    ):
        self.model_name = (
            model_name
            or os.environ.get("EMOTION_MODEL_NAME")
            or self.DEFAULT_MODEL
        )
        self.max_length = max_length
        self.device = device or os.environ.get("EMOTION_MODEL_DEVICE")
        self.enable_deep_analysis = enable_deep_analysis
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._label_map = ["negative", "positive"]
        self._load_error: Optional[str] = None

        if auto_initialize:
            self._ensure_pipeline()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_pipeline(self) -> bool:
        """Load tokenizer/model on demand."""
        if self._model is not None and self._tokenizer is not None:
            return True

        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            import torch
        except Exception as exc:  # pragma: no cover - import guard
            self._load_error = f"transformers/torch import error: {exc}"
            return False

        try:
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name
            )
            if self.device is None:
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model.to(self.device)
            self._model.eval()
            self._torch = torch
            # Update label map if model provides one
            if hasattr(self._model.config, "id2label") and self._model.config.id2label:
                labels = [
                    self._model.config.id2label[idx]
                    for idx in range(self._model.config.num_labels)
                ]
                self._label_map = labels
        except Exception as exc:  # pragma: no cover - external dependency
            self._load_error = f"model load error: {exc}"
            self._tokenizer = None
            self._model = None
            self._torch = None
            return False

        return True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._ensure_pipeline()

    @property
    def last_error(self) -> Optional[str]:
        return self._load_error

    def _analyze_emotion_dimensions(self, text: str) -> Dict[str, float]:
        """基于情绪词典分析多维度情绪"""
        emotion_scores = {}
        text_lower = text.lower()
        
        for emotion, keywords in self.EMOTION_LEXICON.items():
            count = 0
            total_weight = 0.0
            
            for keyword in keywords:
                # 计算关键词出现次数（考虑重复字符，如"！"）
                occurrences = len(re.findall(re.escape(keyword), text))
                if occurrences > 0:
                    # 长关键词权重更高
                    weight = len(keyword) * occurrences
                    count += occurrences
                    total_weight += weight
            
            # 归一化得分（基于文本长度和关键词密度）
            if len(text) > 0:
                density = total_weight / len(text)
                # 使用对数缩放，避免单一关键词过度影响
                score = min(1.0, density * 10 + (count / max(len(text) / 50, 1)) * 0.3)
            else:
                score = 0.0
            
            emotion_scores[emotion] = float(score)
        
        # 归一化所有情绪得分
        total = sum(emotion_scores.values())
        if total > 0:
            emotion_scores = {k: v / total for k, v in emotion_scores.items()}
        
        return emotion_scores
    
    def _analyze_emotion_depth(self, text: str, emotion_scores: Dict[str, float]) -> Tuple[str, str, float]:
        """分析情绪深度：表层情绪 vs 深层情绪"""
        # 表层情绪：直接表达的情绪词
        explicit_emotions = ['joy', 'sadness', 'anger', 'fear', 'surprise', 'disgust']
        surface_scores = {k: v for k, v in emotion_scores.items() if k in explicit_emotions}
        surface_emotion = max(surface_scores.items(), key=lambda x: x[1])[0] if surface_scores else "neutral"
        
        # 深层情绪：通过隐喻、对比、转折等表达的隐含情绪
        # 检测深层情绪指标
        deep_indicators = {
            'tension': ['虽然', '但是', '然而', '却', '尽管', '即使'],
            'anticipation': ['即将', '马上', '就要', '即将', '等待'],
            'fear': ['仿佛', '似乎', '好像', '隐约', '若隐若现'],
        }
        
        deep_scores = {}
        for emotion, indicators in deep_indicators.items():
            count = sum(1 for ind in indicators if ind in text)
            deep_scores[emotion] = min(1.0, count * 0.2)
        
        # 结合表层和深层
        combined_scores = {}
        for emotion in emotion_scores:
            base = emotion_scores.get(emotion, 0.0)
            deep = deep_scores.get(emotion, 0.0)
            combined_scores[emotion] = base * 0.7 + deep * 0.3
        
        deep_emotion = max(combined_scores.items(), key=lambda x: x[1])[0] if combined_scores else "neutral"
        
        # 计算情绪深度（深层情绪占比）
        deep_total = sum(deep_scores.values())
        surface_total = sum(surface_scores.values())
        if (deep_total + surface_total) > 0:
            depth = deep_total / (deep_total + surface_total + 0.1)
        else:
            depth = 0.0
        
        return surface_emotion, deep_emotion, float(depth)
    
    def _analyze_emotion_transition(self, text: str) -> Tuple[Optional[str], float]:
        """分析情绪转折"""
        sentences = re.split(r'[。！？\n]', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if len(sentences) < 2:
            return "stable", 0.0
        
        # 分析每句话的情绪倾向
        sentence_emotions = []
        for sent in sentences[:10]:  # 限制分析前10句
            dims = self._analyze_emotion_dimensions(sent)
            # 计算情绪倾向（正面-负面）
            positive = dims.get('joy', 0) + dims.get('anticipation', 0) + dims.get('excitement', 0)
            negative = dims.get('sadness', 0) + dims.get('anger', 0) + dims.get('fear', 0)
            polarity = positive - negative
            sentence_emotions.append(polarity)
        
        if len(sentence_emotions) < 2:
            return "stable", 0.0
        
        # 检测趋势
        increasing = sum(1 for i in range(1, len(sentence_emotions)) 
                        if sentence_emotions[i] > sentence_emotions[i-1])
        decreasing = sum(1 for i in range(1, len(sentence_emotions)) 
                        if sentence_emotions[i] < sentence_emotions[i-1])
        
        total_changes = len(sentence_emotions) - 1
        if total_changes == 0:
            transition = "stable"
            strength = 0.0
        elif increasing > decreasing * 1.5:
            transition = "rising"
            strength = increasing / total_changes
        elif decreasing > increasing * 1.5:
            transition = "falling"
            strength = decreasing / total_changes
        else:
            transition = "mixed"
            strength = (increasing + decreasing) / total_changes / 2
        
        return transition, float(strength)
    
    def analyze(self, text: str, context: Optional[List[str]] = None) -> EmotionResult:
        """深度情绪分析 - 返回多维度、多层次的情绪结果"""
        text = (text or "").strip()
        if not text:
            return EmotionResult(
                scores={"negative": 0.0, "positive": 0.0},
                emotion_dimensions={},
            )

        # 基础模型分析（如果可用）
        base_result = None
        if self._ensure_pipeline():
            try:
                torch = self._torch
                tokenizer = self._tokenizer
                model = self._model

                inputs = tokenizer(
                    text,
                    return_tensors="pt",
                    truncation=True,
                    max_length=self.max_length,
                    padding=False,
                )
                inputs = {k: v.to(self.device) for k, v in inputs.items()}

                with torch.no_grad():
                    outputs = model(**inputs)
                    logits = outputs.logits
                    probs = torch.softmax(logits, dim=-1).detach().cpu().numpy()[0]

                label_idx = int(probs.argmax())
                scores = {}
                for idx, score in enumerate(probs):
                    label = self._label_map[idx] if idx < len(self._label_map) else f"label_{idx}"
                    scores[label] = float(score)

                top_label = (
                    self._label_map[label_idx]
                    if label_idx < len(self._label_map)
                    else f"label_{label_idx}"
                )
                confidence = float(probs[label_idx])

                if len(probs) >= 2:
                    sorted_probs = sorted([float(p) for p in probs], reverse=True)
                    intensity = sorted_probs[0] - sorted_probs[1]
                else:
                    intensity = confidence
                
                base_result = {
                    'label': top_label,
                    'confidence': confidence,
                    'scores': scores,
                    'intensity': float(intensity),
                }
            except Exception as exc:
                pass
        
        # 多维度情绪分析
        emotion_dims = self._analyze_emotion_dimensions(text)
        
        # 情绪深度分析
        surface_emotion, deep_emotion, emotion_depth = self._analyze_emotion_depth(text, emotion_dims)
        
        # 情绪转折分析
        transition, transition_strength = self._analyze_emotion_transition(text)
        
        # 情绪密度分析
        emotion_words = sum(1 for keywords in self.EMOTION_LEXICON.values() 
                          for kw in keywords if kw in text)
        emotion_word_density = emotion_words / len(text) if len(text) > 0 else 0.0
        
        sentences = re.split(r'[。！？\n]', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        emotion_sentences = sum(1 for sent in sentences 
                              if any(kw in sent for keywords in self.EMOTION_LEXICON.values() 
                                    for kw in keywords))
        emotion_sentence_density = emotion_sentences / len(sentences) if len(sentences) > 0 else 0.0
        
        # 情绪复杂度（多种情绪并存）
        active_emotions = sum(1 for score in emotion_dims.values() if score > 0.1)
        emotion_complexity = min(1.0, active_emotions / 5.0)
        
        # 合并基础模型结果
        if base_result:
            final_label = base_result['label']
            final_confidence = base_result['confidence']
            final_scores = base_result['scores']
            raw_intensity = base_result['intensity']
        else:
            # 回退到词典分析
            top_emotion = max(emotion_dims.items(), key=lambda x: x[1])[0] if emotion_dims else "neutral"
            final_label = top_emotion
            final_confidence = emotion_dims.get(top_emotion, 0.0) if emotion_dims else 0.0
            final_scores = {"negative": 0.0, "positive": 0.0}
            raw_intensity = max(emotion_dims.values()) if emotion_dims else 0.0

        # 复合情绪强度（面向小说正文）：融合分类置信度、情绪词密度、情绪深度、转折强度，
        # 使「写作层面情绪浓」的文本更容易达到 0.6，避免仅用二分类置信度导致长期偏低
        density_term = min(1.0, emotion_word_density * 18.0)  # 约 5.5% 情绪词密度即可接近 1
        final_intensity = (
            0.2 * raw_intensity
            + 0.45 * density_term
            + 0.25 * emotion_depth
            + 0.1 * transition_strength
        )
        final_intensity = min(1.0, max(0.0, final_intensity))
        
        return EmotionResult(
            label=final_label,
            confidence=final_confidence,
            scores=final_scores,
            intensity=final_intensity,
            emotion_dimensions=emotion_dims,
            surface_emotion=surface_emotion,
            deep_emotion=deep_emotion,
            emotion_depth=emotion_depth,
            emotion_transition=transition,
            transition_strength=transition_strength,
            emotion_word_density=float(emotion_word_density),
            emotion_sentence_density=float(emotion_sentence_density),
            emotion_complexity=float(emotion_complexity),
            error=self._load_error if not self._ensure_pipeline() else None,
        )

    def extract_features(self, text: str) -> Dict[str, float]:
        """提取深度情绪特征，用于机器学习模型训练"""
        result = self.analyze(text)
        
        features = {
            # 基础情绪特征
            "emotion_positive_score": result.scores.get("positive", 0.0)
            if result.scores
            else 0.0,
            "emotion_negative_score": result.scores.get("negative", 0.0)
            if result.scores
            else 0.0,
            "emotion_intensity": result.intensity,
            "emotion_polarity": 0.0,
            
            # 多维度情绪特征
            "emotion_joy": result.emotion_dimensions.get("joy", 0.0),
            "emotion_sadness": result.emotion_dimensions.get("sadness", 0.0),
            "emotion_anger": result.emotion_dimensions.get("anger", 0.0),
            "emotion_fear": result.emotion_dimensions.get("fear", 0.0),
            "emotion_surprise": result.emotion_dimensions.get("surprise", 0.0),
            "emotion_disgust": result.emotion_dimensions.get("disgust", 0.0),
            "emotion_anticipation": result.emotion_dimensions.get("anticipation", 0.0),
            "emotion_tension": result.emotion_dimensions.get("tension", 0.0),
            "emotion_excitement": result.emotion_dimensions.get("excitement", 0.0),
            
            # 情绪深度特征
            "emotion_depth": result.emotion_depth,
            "emotion_complexity": result.emotion_complexity,
            
            # 情绪转折特征
            "emotion_transition_rising": 1.0 if result.emotion_transition == "rising" else 0.0,
            "emotion_transition_falling": 1.0 if result.emotion_transition == "falling" else 0.0,
            "emotion_transition_mixed": 1.0 if result.emotion_transition == "mixed" else 0.0,
            "emotion_transition_strength": result.transition_strength,
            
            # 情绪密度特征
            "emotion_word_density": result.emotion_word_density,
            "emotion_sentence_density": result.emotion_sentence_density,
        }
        
        # 情绪极性
        if result.label.lower().startswith("pos"):
            features["emotion_polarity"] = 1.0
        elif result.label.lower().startswith("neg"):
            features["emotion_polarity"] = -1.0
        
        # 计算主导情绪强度
        if result.emotion_dimensions:
            top_emotion_score = max(result.emotion_dimensions.values())
            features["emotion_dominant_intensity"] = top_emotion_score
        else:
            features["emotion_dominant_intensity"] = 0.0
        
        return features

    def summarize(self, text: str) -> str:
        """返回深度情绪分析的人类可读摘要"""
        result = self.analyze(text)
        if result.error and not result.emotion_dimensions:
            return f"情绪模型不可用（{result.error}）"

        # 构建丰富的情绪摘要
        parts = []
        
        # 主导情绪
        if result.emotion_dimensions:
            top_emotions = sorted(
                result.emotion_dimensions.items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:3]
            emotion_names = {
                'joy': '喜悦', 'sadness': '悲伤', 'anger': '愤怒', 
                'fear': '恐惧', 'surprise': '惊讶', 'disgust': '厌恶',
                'anticipation': '期待', 'tension': '紧张', 'excitement': '激动'
            }
            top_emotion_str = "、".join([
                f"{emotion_names.get(em, em)}({score:.2f})" 
                for em, score in top_emotions if score > 0.1
            ])
            if top_emotion_str:
                parts.append(f"主导情绪: {top_emotion_str}")
        
        # 情绪深度
        if result.emotion_depth > 0.3:
            depth_desc = "深层" if result.emotion_depth > 0.6 else "中深层"
            parts.append(f"{depth_desc}情绪(深度{result.emotion_depth:.2f})")
            if result.surface_emotion != result.deep_emotion:
                emotion_names = {
                    'joy': '喜悦', 'sadness': '悲伤', 'anger': '愤怒', 
                    'fear': '恐惧', 'surprise': '惊讶', 'disgust': '厌恶',
                    'anticipation': '期待', 'tension': '紧张', 'excitement': '激动'
                }
                parts.append(f"表层:{emotion_names.get(result.surface_emotion, result.surface_emotion)} "
                           f"深层:{emotion_names.get(result.deep_emotion, result.deep_emotion)}")
        
        # 情绪转折
        if result.emotion_transition and result.emotion_transition != "stable":
            transition_names = {
                'rising': '上升', 'falling': '下降', 
                'mixed': '混合', 'stable': '稳定'
            }
            parts.append(f"情绪{transition_names.get(result.emotion_transition, result.emotion_transition)}"
                        f"(强度{result.transition_strength:.2f})")
        
        # 情绪复杂度
        if result.emotion_complexity > 0.4:
            complexity_desc = "复杂" if result.emotion_complexity > 0.7 else "较复杂"
            parts.append(f"{complexity_desc}情绪(复杂度{result.emotion_complexity:.2f})")
        
        # 情绪密度
        if result.emotion_word_density > 0.05:
            parts.append(f"情绪密度{result.emotion_word_density:.3f}")
        
        # 基础模型结果（如果可用）
        if result.scores and not result.error:
            parts.append(f"基础模型: {result.label}(置信度{result.confidence:.2f})")
        
        if not parts:
            return "情绪分析: 中性/平淡"
        
        return " | ".join(parts)


__all__ = ["EmotionAnalyzer", "EmotionResult"]


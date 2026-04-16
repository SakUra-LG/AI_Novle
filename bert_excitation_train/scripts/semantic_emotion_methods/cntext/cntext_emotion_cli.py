#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于 cntext 的开源情绪方法封装（CLI）。

功能：
1) 输入中文文本，输出情绪类别分布（DUTIR 七类）
2) 输出情绪极性（HowNet pos/neg）
3) 输出情绪强度特征（valence/arousal）与0~1强度评分

用法：
python bert_excitation_train/scripts/semantic_emotion_methods/open_source/cntext_emotion_cli.py --text "这里输入中文句子"
python bert_excitation_train/scripts/semantic_emotion_methods/open_source/cntext_emotion_cli.py
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from typing import Dict, Any, Optional

try:
    import cntext as ct
except Exception as exc:  # pragma: no cover
    ct = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


DUTIR_ZH_MAP = {
    "乐": "joy",
    "好": "goodness",
    "惊": "surprise",
    "惧": "fear",
    "怒": "anger",
    "哀": "sadness",
    "恶": "disgust",
}

# 默认 Qwen 配置（与当前项目常用 DashScope 路径保持一致）
DEFAULT_QWEN_BASE_URL = os.environ.get(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
# 与项目 scripts 里其它脚本保持一致的默认 Key 兜底方式
DEFAULT_QWEN_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "sk-a2966f4e37134351904851679884cb67")
DEFAULT_QWEN_MODEL_NAME = os.environ.get("DASHSCOPE_MODEL_NAME", "qwen-turbo")
DEFAULT_QWEN_TEMPERATURE = float(os.environ.get("DASHSCOPE_TEMPERATURE", "0.0"))


@dataclass
class CntextEmotionResult:
    top_emotion: str
    top_emotion_score: float
    emotion_distribution: Dict[str, float]
    emotion_counts: Dict[str, float]
    polarity: float
    valence_score: float
    arousal_score: float
    intensity_score: float
    word_num: int
    sentence_num: int
    llm_sentiment: Dict[str, Any]
    llm_status: str
    llm_error: str


class CntextEmotionAnalyzer:
    """封装 cntext 的情绪类别与强度提取。"""

    def __init__(self) -> None:
        if ct is None:
            raise ImportError(
                "cntext 导入失败。请先安装并补齐依赖: "
                "pip3 install cntext --upgrade ipython psutil。"
                f" 原始错误: {type(_IMPORT_ERROR).__name__}: {_IMPORT_ERROR}"
            ) from _IMPORT_ERROR

        self.dutir = ct.read_yaml_dict("zh_common_DUTIR.yaml")["Dictionary"]
        self.hownet = ct.read_yaml_dict("zh_common_HowNet.yaml")["Dictionary"]
        self.emo_valence = ct.read_yaml_dict("zh_valence_ChineseEmoBank.yaml")["Dictionary"]

    @staticmethod
    def _safe_float(data: Dict[str, Any], key: str, default: float = 0.0) -> float:
        value = data.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _safe_int(data: Dict[str, Any], key: str, default: int = 0) -> int:
        value = data.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _normalize_emotion_counts(raw_counts: Dict[str, float]) -> Dict[str, float]:
        total = sum(max(v, 0.0) for v in raw_counts.values())
        if total <= 0:
            return {k: 0.0 for k in raw_counts.keys()}
        return {k: float(v / total) for k, v in raw_counts.items()}

    @staticmethod
    def _calc_intensity(
        valence_score: float,
        arousal_score: float,
        emotion_word_num: float,
        word_num: int,
    ) -> float:
        # 词面情绪密度：情绪词在全文占比，限制在 0~1
        density = min(1.0, emotion_word_num / max(word_num, 1))
        # 唤醒度项：sigmoid 拉伸后映射到 0~1
        arousal_term = 1.0 / (1.0 + math.exp(-arousal_score / 3.0))
        # 效价项：取绝对值，反映“情绪偏离中性”的程度
        valence_term = min(1.0, abs(valence_score) / 10.0)
        score = 0.45 * density + 0.35 * arousal_term + 0.20 * valence_term
        return float(max(0.0, min(1.0, score)))

    def analyze(self, text: str) -> CntextEmotionResult:
        text = (text or "").strip()
        if not text:
            return CntextEmotionResult(
                top_emotion="neutral",
                top_emotion_score=0.0,
                emotion_distribution={},
                emotion_counts={},
                polarity=0.0,
                valence_score=0.0,
                arousal_score=0.0,
                intensity_score=0.0,
                word_num=0,
                sentence_num=0,
                llm_sentiment={},
                llm_status="skipped",
                llm_error="empty_text",
            )

        dutir_res = ct.sentiment(text=text, diction=self.dutir, lang="chinese")
        hownet_res = ct.sentiment(text=text, diction=self.hownet, lang="chinese")
        valence_res = ct.sentiment_by_valence(
            text=text,
            diction=self.emo_valence,
            lang="chinese",
        )

        emotion_counts: Dict[str, float] = {}
        for zh_key, en_key in DUTIR_ZH_MAP.items():
            emotion_counts[en_key] = self._safe_float(dutir_res, f"{zh_key}_num", 0.0)

        emotion_distribution = self._normalize_emotion_counts(emotion_counts)
        if emotion_distribution:
            top_emotion, top_score = max(emotion_distribution.items(), key=lambda x: x[1])
        else:
            top_emotion, top_score = "neutral", 0.0

        pos_num = self._safe_float(hownet_res, "pos_num", 0.0)
        neg_num = self._safe_float(hownet_res, "neg_num", 0.0)
        polarity = float((pos_num - neg_num) / max(pos_num + neg_num, 1.0))

        valence_score = self._safe_float(valence_res, "valence", 0.0)
        arousal_score = self._safe_float(valence_res, "arousal", 0.0)
        word_num = self._safe_int(dutir_res, "word_num", 0)
        sentence_num = self._safe_int(dutir_res, "sentence_num", 0)

        intensity_score = self._calc_intensity(
            valence_score=valence_score,
            arousal_score=arousal_score,
            emotion_word_num=sum(emotion_counts.values()),
            word_num=word_num,
        )

        return CntextEmotionResult(
            top_emotion=top_emotion,
            top_emotion_score=float(top_score),
            emotion_distribution=emotion_distribution,
            emotion_counts=emotion_counts,
            polarity=polarity,
            valence_score=valence_score,
            arousal_score=arousal_score,
            intensity_score=intensity_score,
            word_num=word_num,
            sentence_num=sentence_num,
            llm_sentiment={},
            llm_status="not_requested",
            llm_error="",
        )

    def analyze_with_llm(
        self,
        text: str,
        *,
        backend: Optional[str],
        base_url: Optional[str],
        api_key: Optional[str],
        model_name: Optional[str],
        temperature: float = 0.0,
    ) -> CntextEmotionResult:
        result = self.analyze(text)
        llm_out, llm_status, llm_error = self._try_llm_sentiment(
            text=text,
            backend=backend,
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            temperature=temperature,
        )
        result.llm_sentiment = llm_out
        result.llm_status = llm_status
        result.llm_error = llm_error
        return result

    @staticmethod
    def _try_llm_sentiment(
        text: str,
        *,
        backend: Optional[str],
        base_url: Optional[str],
        api_key: Optional[str],
        model_name: Optional[str],
        temperature: float,
    ) -> tuple[Dict[str, Any], str, str]:
        # 同时支持命令行参数和环境变量
        backend = backend or os.environ.get("CNTEXT_LLM_BACKEND")
        base_url = base_url or os.environ.get("CNTEXT_LLM_BASE_URL")
        api_key = api_key or os.environ.get("CNTEXT_LLM_API_KEY")
        model_name = model_name or os.environ.get("CNTEXT_LLM_MODEL_NAME")

        if not model_name:
            return {}, "skipped", "llm_model_name_missing"

        kwargs: Dict[str, Any] = {
            "text": text,
            "task": "sentiment",
            "model_name": model_name,
            "temperature": temperature,
        }

        if backend:
            kwargs["backend"] = backend
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key

        try:
            llm_result = ct.llm(**kwargs)
            if isinstance(llm_result, dict):
                # 某些后端会把错误包在字典里返回，而不是直接抛异常
                embedded_error = llm_result.get("error")
                if embedded_error:
                    return llm_result, "error", str(embedded_error)
                return llm_result, "ok", ""
            return {"raw": llm_result}, "ok", ""
        except Exception as exc:  # pragma: no cover
            return {}, "error", f"{type(exc).__name__}: {exc}"


def print_result(result: CntextEmotionResult) -> None:
    payload = {
        "type_judgement": {
            "top_emotion": result.top_emotion,
            "top_emotion_score": round(result.top_emotion_score, 4),
            "emotion_distribution": {k: round(v, 4) for k, v in result.emotion_distribution.items()},
            "emotion_counts": result.emotion_counts,
        },
        "lexicon_weighted_scoring": {
            "intensity_score": round(result.intensity_score, 4),
            "polarity": round(result.polarity, 4),
            "valence_score": round(result.valence_score, 4),
            "arousal_score": round(result.arousal_score, 4),
            "word_num": result.word_num,
            "sentence_num": result.sentence_num,
        },
        "llm_structured_scoring": {
            "status": result.llm_status,
            "result": result.llm_sentiment,
            "error": result.llm_error,
        },
        "top_emotion": result.top_emotion,
        "top_emotion_score": round(result.top_emotion_score, 4),
        "intensity_score": round(result.intensity_score, 4),
        "polarity": round(result.polarity, 4),
        "valence_score": round(result.valence_score, 4),
        "arousal_score": round(result.arousal_score, 4),
        "word_num": result.word_num,
        "sentence_num": result.sentence_num,
        "emotion_distribution": {k: round(v, 4) for k, v in result.emotion_distribution.items()},
        "emotion_counts": result.emotion_counts,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def run_interactive(analyzer: CntextEmotionAnalyzer) -> None:
    print("已进入 cntext 情绪分析交互模式。")
    use_llm = input("是否启用 LLM 结构化评分？(y/n，默认 n): ").strip().lower() in {"y", "yes", "1"}

    llm_backend: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model_name: Optional[str] = None
    llm_temperature: float = 0.0

    if use_llm:
        # 先给出默认 Qwen 配置，再决定是否覆盖
        llm_backend = None
        llm_base_url = DEFAULT_QWEN_BASE_URL
        llm_api_key = DEFAULT_QWEN_API_KEY or None
        llm_model_name = DEFAULT_QWEN_MODEL_NAME
        llm_temperature = DEFAULT_QWEN_TEMPERATURE

        print("\n默认将使用 Qwen 配置：")
        print(f"- backend: {'(空，走 base_url)' if not llm_backend else llm_backend}")
        print(f"- base_url: {llm_base_url}")
        print(f"- model_name: {llm_model_name}")
        print(f"- temperature: {llm_temperature}")
        print(f"- api_key: {'已设置' if llm_api_key else '未设置（请在环境变量 DASHSCOPE_API_KEY 配置）'}")

        use_default = input("是否使用以上默认配置？(y/n，默认 y): ").strip().lower()
        if use_default in {"", "y", "yes", "1"}:
            pass
        else:
            print("请填写自定义 LLM 参数（直接回车表示保持当前值）")
            llm_backend = input(f"backend (当前: {llm_backend or '空'}): ").strip() or llm_backend
            llm_base_url = input(f"base_url (当前: {llm_base_url}): ").strip() or llm_base_url
            llm_api_key = input(
                f"api_key (当前: {'已设置' if llm_api_key else '空'}): "
            ).strip() or llm_api_key
            llm_model_name = input(f"model_name (当前: {llm_model_name}): ").strip() or llm_model_name
            temp_str = input(f"temperature (当前: {llm_temperature}): ").strip()
            if temp_str:
                try:
                    llm_temperature = float(temp_str)
                except ValueError:
                    print("temperature 非法，保留当前值。")

    print("请输入文本开始分析。输入 exit 退出。")
    while True:
        text = input("\n请输入中文文本: ").strip()
        if text.lower() in {"exit", "quit", "q"}:
            print("已退出。")
            break
        result = analyzer.analyze_with_llm(
            text,
            backend=llm_backend,
            base_url=llm_base_url,
            api_key=llm_api_key,
            model_name=llm_model_name,
            temperature=llm_temperature,
        )
        print_result(result)


def main() -> None:
    argparse.ArgumentParser(description="cntext 情绪特征与评分 CLI").parse_args()
    analyzer = CntextEmotionAnalyzer()
    run_interactive(analyzer)


if __name__ == "__main__":
    main()

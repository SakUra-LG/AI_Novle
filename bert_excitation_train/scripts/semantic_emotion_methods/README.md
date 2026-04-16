# 语义与情绪评分方法

该目录用于统一管理：

- 语义相关算法
- 情绪分类与强度评分算法
- 情绪标定（calibration）与量化（quantization）方法

## 目录结构

- `handwritten/`：手写规则方法（可解释、可快速迭代）
- `cntext/`：`cntext` 开源方案接入（词典 + LLM）
- `vad_macbert/`：VAD-MacBERT 连续评分接入
- `semeval2025_task11/`：SemEval2025 Task11 适配输出

## 当前手写实现

见 `handwritten/manual_semantic_emotion_scorer.py`，核心能力：

- 当前情绪分类（`top_emotion`）
- 情绪分布（`emotion_distribution`）
- 原始强度评分（`intensity_raw`）
- 标定后的强度评分（`intensity_calibrated`）
- 强度量化等级（`intensity_level`）


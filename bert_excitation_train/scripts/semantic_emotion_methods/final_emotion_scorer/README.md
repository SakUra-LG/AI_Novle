# 最终版情绪评分脚本

入口文件：`final_emotion_scorer.py`

本目录用于输出一套统一的情绪评分结果：

1. 当前文本涉及哪些情绪类型，以及各类型占比。
2. 占比最高的主情绪是什么，以及主情绪 1~5 级强度。

## 支持的情绪类型

- `humor` / 幽默
- `anger` / 愤怒
- `fear` / 恐惧
- `grievance` / 委屈
- `touching` / 感动
- `sadness` / 悲伤
- `joy` / 喜悦
- `surprise` / 惊讶
- `disgust` / 厌恶
- `tension` / 紧张
- `anticipation` / 期待

## 使用方式

直接运行后粘贴文本，最后输入一个空行开始分析：

```powershell
python bert_excitation_train\scripts\semantic_emotion_methods\final_emotion_scorer\final_emotion_scorer.py --pretty
```

分析一句文本：

```powershell
python bert_excitation_train\scripts\semantic_emotion_methods\final_emotion_scorer\final_emotion_scorer.py --text "这里输入文本" --pretty
```

分析文件：

```powershell
python bert_excitation_train\scripts\semantic_emotion_methods\final_emotion_scorer\final_emotion_scorer.py --file "path\to\sample.txt" --pretty
```

在 Python 中调用：

```python
from bert_excitation_train.scripts.semantic_emotion_methods.final_emotion_scorer import score_text

result = score_text("她攥紧录音笔，冷声质问：凭什么把所有责任推给我？")
print(result["main_emotion_zh"], result["main_intensity_level"])
```

## 输出字段

- `emotion_types`：涉及的情绪类型列表，按占比从高到低排序。
- `emotion_distribution`：英文情绪名到占比的映射。
- `emotion_distribution_zh`：中文情绪名到占比的映射。
- `main_emotion` / `main_emotion_zh`：主情绪。
- `main_emotion_proportion`：主情绪占比。
- `main_intensity_level`：主情绪强度，范围 1~5。
- `main_intensity_label`：中文等级说明。
- `main_intensity_metrics`：用于解释强度判断的命中指标。

## 与 emotion_level 的关系

脚本会优先复用 `scripts/emotion_level` 下已有五级生成器的词表和硬约束，包括：

- `humor_level`
- `anger_level`
- `thriller_level`
- `grievance_level`
- `touching_level`

其中幽默已额外按 `humor_level/output/后羿射日的高潮片段/1~5级幽默片段示例` 做过校准：这组 1~5 级样本会被识别为主情绪 `humor`，强度等级分别为 1、2、3、4、5。

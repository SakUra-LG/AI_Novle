# SemEval2025-Task11 适配

来源仓库：[`emotion-analysis-project/semeval2025-task11`](https://github.com/emotion-analysis-project/semeval2025-task11)

## 说明

- 该仓库是共享任务与数据组织仓库，不是现成推理 API。
- 本目录提供一个“输出格式适配器”，将项目已有情绪分析结果转换为：
  - Track A（六类多标签，0/1）
  - Track B（六类强度，0~3）

## 使用

交互模式：

```bash
.\.venv312\Scripts\python.exe bert_excitation_train/scripts/semantic_emotion_methods/semeval2025_task11/semeval2025_adapter_cli.py
```

单句模式：

```bash
.\.venv312\Scripts\python.exe bert_excitation_train/scripts/semantic_emotion_methods/semeval2025_task11/semeval2025_adapter_cli.py --text "她压抑了很多年，终于在今天爆发了"
```

阈值可调（Track A 二值化阈值）：

```bash
.\.venv312\Scripts\python.exe bert_excitation_train/scripts/semantic_emotion_methods/semeval2025_task11/semeval2025_adapter_cli.py --text "她压抑了很多年，终于在今天爆发了" --threshold 0.30
```

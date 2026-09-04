# 标注与反馈

## 作用

提供段落人工标注、生成反馈记录、样本采集和评分趋势分析，产物用于情绪评分器和模型训练。

## 用法

```powershell
python -m bert_excitation_train.scripts.annotation_feedback.interactive_annotation
python -m bert_excitation_train.scripts.annotation_feedback.sample_collector_tool
python -m bert_excitation_train.scripts.annotation_feedback.record_feedback
python -m bert_excitation_train.scripts.annotation_feedback.feedback_loop_system
```

标注和训练数据统一保存在 `bert_excitation_train/data/training/` 或 `data/labeled/`。运行前检查脚本参数，避免覆盖已人工审核的数据文件。

# 模型训练

## 作用

将人工评分和生成反馈整理成训练数据，并执行增量训练、普通微调或评分引导 LoRA 训练。已有训练集完整保存在 `bert_excitation_train/data/training/` 和 `data/labeled/`。

## 用法

```powershell
python -m bert_excitation_train.scripts.model_training.prepare_training_data
python -m bert_excitation_train.scripts.model_training.incremental_model_trainer
python -m bert_excitation_train.scripts.model_training.score_guided_lora_training --help
```

训练通常需要 PyTorch、Transformers、Datasets 和 PEFT，且会占用较多内存或显存。输出模型应写入 `bert_excitation_train/checkpoints/`；运行前先备份需要长期保留的检查点。

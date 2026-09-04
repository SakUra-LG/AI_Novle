# 情绪评分

## 作用

本目录完整保留现有情绪评分实现和情绪强度样例生成器。数据没有删减，位于 `bert_excitation_train/data/`；各情绪分级的既有示例位于 `emotion_level/*/output/`。

## 常用入口

对新增样本进行增量评分：

```powershell
python -m bert_excitation_train.scripts.emotion_scoring.incremental_sample_scorer
```

规则评分：

```powershell
python -m bert_excitation_train.scripts.emotion_scoring.score_candidates_rule_based
```

最终多方法语义情绪评分器：

```powershell
python -m bert_excitation_train.scripts.emotion_scoring.semantic_methods.final_emotion_scorer.final_emotion_scorer --help
```

生成五级情绪样例，例如愤怒：

```powershell
python -m bert_excitation_train.scripts.emotion_scoring.emotion_level.anger_level.run_anger_levels
```

同级目录还保留委屈、恐惧、幽默和感动生成入口。部分评分器需要 `checkpoints/` 中的现有模型；语义方法的额外依赖和参数见 `semantic_methods/README.md`。

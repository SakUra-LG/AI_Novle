# 愤怒强度五级样本生成

## 1. 如何调用使用

在项目根目录执行：

```powershell
python .\bert_excitation_train\scripts\emotion_level\anger_level\run_anger_levels.py
```

运行后会提示输入愤怒场景提示词：

```text
请输入愤怒场景提示词（直接回车使用默认场景）：
```

直接回车会使用默认场景：

```text
公司会议室里，主角长期熬夜完成的核心方案被上司当众据为己有，还反过来指责主角只会抢功。
```

脚本会自动生成愤怒强度 1~5 级片段，并输出到：

```text
bert_excitation_train/scripts/emotion_level/anger_level/output/
```

每个等级会保存为一个单独的 `.txt` 文件。

## 2. 生成逻辑

愤怒不像幽默那样有 punchline 这类天然计数单位，所以本脚本不会只靠样本直接生成，而是结合以下强度刻度：

1. 触发源强度：不公、背刺、羞辱、压迫是否具体且严重。
2. 身体动作强度：攥紧、拍桌、调证据、挡住、撕毁等动作是否逐级明显。
3. 对峙语言强度：反问、质问、揭穿、拒绝退让是否逐级锋利。
4. 后果推进强度：追责、公开、报警、投诉、判决、关系决裂等清算压力是否增强。

## 3. 五级强度约束

核心规则定义在：

```text
anger_level_generator.py
```

主要包括：

- `ANGER_LEVEL_RULES`：五级愤怒的文字定义。
- `ANGER_LEVEL_HARD_CONSTRAINTS`：每一级的可量化约束。
- `ANGER_CUE_WORDS`：愤怒线索词。
- `CONFRONTATION_CUE_WORDS`：揭穿、追责、清算线索词。
- `ACTION_CUE_WORDS`：愤怒动作线索词。

生成后会自动统计：

- `anger_hits`：愤怒线索数量。
- `dialogue_count`：对峙对白数量。
- `confrontation_hits`：揭穿、追责、清算线索数量。
- `action_hits`：愤怒动作线索数量。

如果某一级第一次生成不达标，脚本会把校验反馈加入 prompt 后重试，默认最多重试 3 次。

## 4. 样本来源

参考样本来自：

```text
bert_excitation_train/data/anger_samples.txt
```

当前样本用于提供愤怒场景、冲突结构、动作表达和反击方式。不同等级会按比例注入不同数量的样本，高等级参考样本更多，以增强情绪密度和清算感。

## 5. API Key 要求

脚本优先读取环境变量：

```text
DASHSCOPE_API_KEY
```

如果环境变量不存在，会尝试从以下项目脚本中读取 `API_Key_QW`：

```text
generate_chapter_content
manual_generator
emotion_guided_generator
```

如果两种方式都没有配置，会报错提示缺少 API Key。

## 6. 后续维护约定

以后在本项目中新增某个功能脚本时，需要在对应功能文件夹下同步新增或更新 `.md` 说明文件，优先写清：

1. 如何调用使用。
2. 输入和输出位置。
3. 核心参数或规则。
4. 依赖项和注意事项。

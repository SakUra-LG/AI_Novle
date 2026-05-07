# 感动强度五级样本生成

## 1. 如何调用使用

在项目根目录执行：

```powershell
python .\bert_excitation_train\scripts\emotion_level\touching_level\run_touching_levels.py
```

运行后会提示输入感动场景提示词：

```text
请输入感动场景提示词（直接回车使用默认场景）：
```

直接回车会使用默认场景：

```text
主角失业后独自站在城市天桥上崩溃，朋友赶来陪她，没有说教，只用行动把她从低谷里托住。
```

脚本会自动生成感动强度 1~5 级片段，并输出到：

```text
bert_excitation_train/scripts/emotion_level/touching_level/output/
```

每个等级会保存为一个单独的 `.txt` 文件。

## 2. 生成逻辑

感动分级强调“同一场景下的强度递增”，不靠空泛鸡汤或煽情堆砌，而从以下维度控制：

1. 善意具体度：等级越高，关心越具体、越及时、越能击中人物真正需要。
2. 被理解程度：等级越高，人物越能感到自己是真的被看见、被尊重、被接住。
3. 陪伴/守护强度：等级越高，陪伴越坚定，等待、承担、站出来或不离开的分量越重。
4. 情绪释放：从心里一暖、鼻酸，逐步到落泪、拥抱、释怀和重新振作。
5. 收束方式：高等级需要落到和解、救赎、希望重燃或生命意义被重新确认。

当前版本额外强调低级样本的“干净分界”：

1. 1级只写小善意和轻微暖意，不出现重大牺牲或救赎。
2. 2级出现被理解、被接住的瞬间，可以有轻微泪意。
3. 3级让陪伴、守护、道歉或支持成为情绪转折核心。
4. 4级加入等待、长期记挂、关键时刻站出来等更重的行动分量。
5. 5级在低谷或长期孤独中形成精神救赎和希望回升。

为保证五级样本可横向比较，脚本会额外执行场景一致性校验：

1. 每一级输出都必须命中输入场景中的关键锚点。
2. 如果输出出现地铁站、厨房、医院、校门口等非输入场景词，会被视为场景漂移并触发重试。
3. `touching_samples.txt` 会按等级选取参考样本，只学习感动表达质量和强度层次，不允许套用样本场景。

## 3. 五级强度约束

核心规则定义在：

```text
touching_level_generator.py
```

主要包括：

- `TOUCHING_LEVEL_RULES`：五级感动强度的文字定义。
- `TOUCHING_LEVEL_HARD_CONSTRAINTS`：每一级的可量化约束。
- `TOUCHING_CUE_WORDS`：感动、温暖、被理解、陪伴、守护、释怀等核心线索词。
- `KINDNESS_CUE_WORDS`：递伞、留饭、纸条、热饮、握住、站出来等具体善意线索词。
- `WARMTH_CUE_WORDS`：热气、掌心、怀抱、灯、轻声、温柔等温暖氛围线索词。
- `RELEASE_CUE_WORDS`：眼泪、鼻酸、释怀、放下、重新、继续等情绪释放线索词。

生成后会自动统计：

- `touching_hits`：感动线索数量。
- `kindness_hits`：具体善意/行动线索数量。
- `warmth_hits`：温暖氛围线索数量。
- `release_hits`：情绪释放线索数量。
- `body_hits`：身体反应线索数量。
- `high_intensity_hits`：崩溃、绝望、救赎、生命等高强度词数量。
- `dialogue_count`：对话数量。

如果某一级第一次生成不达标，脚本会把校验反馈加入 prompt 后重试，默认最多重试 3 次。

## 4. 样本来源

参考样本来自：

```text
bert_excitation_train/data/touching_samples.txt
```

当前样本库共有 12 条，样本注入数量梯度：

- 1级：1~2 条
- 2级：2~4 条
- 3级：4~6 条
- 4级：6~9 条
- 5级：9~12 条

## 5. API Key 要求

脚本优先读取环境变量：

```text
DASHSCOPE_API_KEY
```

如果环境变量不存在，会尝试从以下项目脚本读取 `API_Key_QW`：

```text
generate_chapter_content
manual_generator
emotion_guided_generator
```

如果两种方式都没有配置，会报错提示缺少 API Key。

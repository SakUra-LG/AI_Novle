# 委屈强度五级样本生成

## 1. 如何调用使用

在项目根目录执行：

```powershell
python .\bert_excitation_train\scripts\emotion_level\grievance_level\run_grievance_levels.py
```

运行后会提示输入委屈场景提示词：

```text
请输入委屈场景提示词（直接回车使用默认场景）：
```

直接回车会使用默认场景：

```text
实习生连续加班完成方案，却在汇报会上被同事抢功，并被领导误解成不够主动。
```

脚本会自动生成委屈强度 1~5 级片段，并输出到：

```text
bert_excitation_train/scripts/emotion_level/grievance_level/output/
```

每个等级会保存为一个单独的 `.txt` 文件。

## 2. 生成逻辑

委屈分级强调“同一场景下的强度递增”，不靠单纯哭惨、愤怒或复仇爽点堆叠，而从以下维度控制：

1. 不公程度：等级越高，误解、否定、抢功、甩锅、背叛或清白受损越明确。
2. 申辩难度：等级越高，人物越难解释，解释越容易被打断、曲解或反咬。
3. 孤立程度：等级越高，周围人的沉默、冷眼、看戏或站队越明显。
4. 身体反应：从低头、攥紧、眼眶发热，逐步到哽咽、发抖、落泪和短暂失控。
5. 收束方式：高等级需要落到心寒、心死、关系断裂、清白被毁或不可逆损失。

当前版本额外强调低级样本的“干净分界”：

1. 1级只允许轻微失落和被忽略，人物仍能自我安慰。
2. 2级出现明确误解或偏心，但主要是心酸、憋闷和忍住不说。
3. 3级进入公开误解和百口莫辩，人物开始明显红眼、发抖。
4. 4级出现当众难堪、被反咬或被孤立，允许落泪和短暂质问。
5. 5级集中爆发，落到长期付出被彻底否定、清白被夺或关系断裂。

为保证五级样本可横向比较，脚本会额外执行场景一致性校验：

1. 每一级输出都必须命中输入场景中的关键锚点。
2. 如果输出出现医院、婚礼、校园、警局等非输入场景词，会被视为场景漂移并触发重试。
3. `grievance_samples.txt` 会按等级选取参考样本，只学习委屈表达质量和强度层次，不允许套用样本场景。

## 3. 五级强度约束

核心规则定义在：

```text
grievance_level_generator.py
```

主要包括：

- `GRIEVANCE_LEVEL_RULES`：五级委屈强度的文字定义。
- `GRIEVANCE_LEVEL_HARD_CONSTRAINTS`：每一级的可量化约束。
- `GRIEVANCE_CUE_WORDS`：委屈、心酸、被误解、百口莫辩等核心线索词。
- `INJUSTICE_CUE_WORDS`：抢功、甩锅、清白、付出、被夺走等不公线索词。
- `ISOLATION_CUE_WORDS`：没人、无人、冷眼、看戏、孤立等孤立线索词。
- `BODY_REACTION_WORDS`：低头、攥紧、眼眶、哽咽、发抖等压抑反应线索词。

生成后会自动统计：

- `grievance_hits`：委屈线索数量。
- `injustice_hits`：不公/被误解线索数量。
- `isolation_hits`：孤立无援线索数量。
- `body_hits`：压抑身体反应线索数量。
- `high_intensity_hits`：崩溃、绝望、心死等高强度词数量。
- `dialogue_count`：对话数量。

如果某一级第一次生成不达标，脚本会把校验反馈加入 prompt 后重试，默认最多重试 3 次。

## 4. 样本来源

参考样本来自：

```text
bert_excitation_train/data/grievance_samples.txt
```

不同等级会选取不同数量和强度区间的样本。低等级优先参考相对克制的样本，高等级参考更高评分、更强压迫感的样本。

当前样本注入数量梯度：

- 1级：1~2 条
- 2级：3~5 条
- 3级：6~9 条
- 4级：10~13 条
- 5级：15~20 条

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

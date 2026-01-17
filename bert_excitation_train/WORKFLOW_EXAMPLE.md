# 具体工作流程示例

## 🎯 实际运行示例：生成第21章

### 步骤1：RAG样本检索和学习

```python
# 用户输入：生成第21章，要求情节紧张，有冲突和悬念

# 1. 系统加载小说上下文
context = {
    'previous_chapters': [
        {'chapter': 1, 'content': '第1章内容...'},
        {'chapter': 2, 'content': '第2章内容...'},
        # ... 前20章内容
    ],
    'outline': '第21章：陈雪发现重要线索，但陷入危险...'
}

# 2. 从上下文中提取高评分片段
high_score_snippets = [
    {
        'content': '陈雪与敌人正面交锋，两人四目相对，空气仿佛凝固',
        'score': 75,
        'chapter': 15,
        'source': 'previous_chapter'
    },
    {
        'content': '脚步声越来越近，她知道自己被跟踪了，必须想办法摆脱',
        'score': 91,
        'chapter': 18,
        'source': 'previous_chapter'
    }
]

# 3. 搜索相关RAG样本
query = "情节紧张，有冲突和悬念"
adapted_samples = search_and_adapt_samples(query, project_config, top_k=3)

# 返回的适配样本：
adapted_samples = [
    {
        'original': '陈雪在朝堂上揭露了奸臣的阴谋，但对方早有准备，反而倒打一耙',
        'adapted': '陈雪在会议室里揭露了竞争对手的阴谋，但对方早有准备，反而倒打一耙',
        'score': 82,
        'category': '政治权谋高评分样本'
    },
    {
        'original': '拳风炸裂，两道刚猛劲力凌空相撞，气浪如涟漪般爆开',
        'adapted': '陈雪与对手正面交锋，两人四目相对，空气仿佛凝固',
        'score': 75,
        'category': '武侠对决高评分样本'
    }
]
```

### 步骤2：增强提示词构建

```python
enhanced_prompt = f"""
你是专业的小说作家，正在创作《暗河噬城》第21章。

【章节梗概】
第21章：陈雪发现重要线索，但陷入危险，必须想办法脱身

【前文关键情节】
- 第15章：陈雪与敌人正面交锋，两人四目相对，空气仿佛凝固
- 第18章：脚步声越来越近，她知道自己被跟踪了，必须想办法摆脱
- 第20章：陈雪发现了关键证据，但被敌人发现

【高评分写作样本参考】
1. 陈雪在会议室里揭露了竞争对手的阴谋，但对方早有准备，反而倒打一耙
2. 陈雪与对手正面交锋，两人四目相对，空气仿佛凝固

【用户要求】
生成第21章，要求情节紧张，有冲突和悬念

【写作要求】
1. 参考提供的高评分样本的写作风格和情感强度
2. 保持与前文的连贯性
3. 确保情节紧张，有冲突和悬念
4. 字数控制在2000-3000字
"""
```

### 步骤3：内容生成

```python
# 调用Qwen API生成3个版本
response = dashscope.Generation.call(
    model='qwen-plus',
    prompt=enhanced_prompt,
    max_tokens=3000
)

# 生成3个版本并保存
versions = [
    {
        'file': 'ch21_v1.txt',
        'content': '第21章内容版本1...',
        'score': None  # 待评分
    },
    {
        'file': 'ch21_v2.txt', 
        'content': '第21章内容版本2...',
        'score': None
    },
    {
        'file': 'ch21_v3.txt',
        'content': '第21章内容版本3...',
        'score': None
    }
]
```

### 步骤4：双重评分系统

```python
# 使用规则评分器
rule_scorer = OptimizedRuleScorer()
rule_scores = []

# 使用机器学习评分器
ml_scorer = ParagraphScorer()
ml_scores = []

for version in versions:
    # 规则评分
    rule_score = rule_scorer.calculate_score(version['content'])
    rule_scores.append(rule_score)
    
    # ML评分
    ml_score = ml_scorer.predict_score(version['content'])
    ml_scores.append(ml_score)
    
    # 综合评分
    final_score = (rule_score + ml_score) / 2
    version['score'] = final_score

# 评分结果示例：
# 版本1：规则评分=65, ML评分=72, 综合评分=68.5
# 版本2：规则评分=58, ML评分=69, 综合评分=63.5  
# 版本3：规则评分=71, ML评分=78, 综合评分=74.5

# 选择最高分版本
best_version = max(versions, key=lambda x: x['score'])
print(f"选择版本3，评分：{best_version['score']}")
```

### 步骤5：反馈记录

```python
# 记录到反馈日志
feedback_data = {
    'timestamp': '2025-09-27 18:30:00',
    'chapter_num': 21,
    'candidate_file': 'ch21_v3.txt',
    'model_score': 74.5,
    'user_feedback': None,
    'all_scores': [68.5, 63.5, 74.5],
    'selected_version': 3
}

# 保存到 outputs/feedback_log.csv
```

### 步骤6：反馈循环学习

```python
# 分析评分趋势
feedback_system = FeedbackLoopSystem()
analysis = feedback_system.analyze_score_trends()

# 分析结果：
# {
#     'avg_score': 68.2,
#     'trend': 'up',
#     'low_score_count': 2
# }

# 如果评分较高，将内容添加到RAG样本库
if best_version['score'] >= 70:
    feedback_system.update_rag_samples(min_score=70)
    
    # 更新后的RAG样本库包含：
    # - 原始高评分样本
    # - 新生成的高评分内容片段

# 准备训练数据
prepare_training_data_from_feedback(
    feedback_csv="outputs/feedback_log.csv",
    min_score=70
)

# 生成训练数据格式：
training_data = [
    {
        'instruction': '请续写《暗河噬城》第21章，要求情节紧张，有冲突和悬念',
        'input': '',
        'output': '第21章内容版本3...',
        'score': 74.5
    }
]
```

### 步骤7：模型重新训练

```python
# 使用高评分内容重新训练LoRA模型
lora_training_command = """
python scripts/lora_training.py \
    --data_file data/training/high_quality_training_data.jsonl \
    --epochs 3 \
    --batch_size 4
"""

# 训练过程：
# 1. 加载Qwen2.5-0.5B基础模型
# 2. 配置LoRA参数（只训练1.75%的参数）
# 3. 使用高评分内容训练
# 4. 保存训练好的模型到 checkpoints/lora_model_auto/

# 训练完成后，生成模型已经学习了高评分内容的写作模式
```

## 🔄 完整循环效果

### 第一次生成：
- **输入**：基础提示词
- **RAG样本**：原始样本库
- **生成质量**：中等（评分60-70）
- **学习内容**：无

### 第二次生成：
- **输入**：增强提示词（包含前文上下文）
- **RAG样本**：原始样本库 + 第一次高评分内容
- **生成质量**：较好（评分70-80）
- **学习内容**：第一次的高评分片段

### 第三次生成：
- **输入**：增强提示词 + 更多上下文
- **RAG样本**：原始样本库 + 前两次高评分内容
- **生成质量**：很好（评分80-90）
- **学习内容**：前两次的高评分片段

### 持续改进：
- **RAG样本库**：不断丰富，包含更多高评分内容
- **生成模型**：通过LoRA训练学习高评分写作模式
- **评分模型**：通过人工标注不断优化
- **整体质量**：持续提升

## 🎯 关键创新点

1. **真正的RAG集成**：
   - 不是简单拼接，而是语义搜索+内容适配
   - 自动替换角色名和背景设定
   - 保持情感强度和写作风格

2. **上下文感知生成**：
   - 利用前20章内容保持连贯性
   - 结合章节梗概指导生成方向
   - 提取前文高评分片段作为参考

3. **双重评分机制**：
   - 规则评分：基于关键词和模式匹配
   - ML评分：基于人工标注训练的模型
   - 综合评分：取两者平均值

4. **闭环反馈学习**：
   - 评分结果直接用于模型改进
   - 高评分内容自动添加到RAG库
   - 持续训练提升生成质量

这个系统实现了从"样本学习"到"评分反馈"再到"模型改进"的完整闭环，确保生成内容的质量持续提升。

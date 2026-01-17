# AI小说自动生成系统完整工作流程解析

## 🔄 系统架构概览

这个项目实现了一个完整的AI小说生成系统，包含以下核心组件：

1. **RAG样本系统** - 存储和学习高评分样本
2. **生成模型** - 基于RAG样本生成新内容
3. **评分系统** - 评估生成内容的质量
4. **反馈循环** - 将评分结果回喂给生成模型

---

## 📚 第一部分：RAG样本系统 - 让生成模型学习高评分样本

### 1.1 样本存储和向量化

```python
# 文件：scripts/handle_universal_samples.py
# 功能：将文本样本转换为向量，建立检索系统

def batch_vectorize(texts, batch_size=32):
    """批量向量化文本"""
    # 使用BGE-large-zh模型将文本转换为768维向量
    # 这些向量用于语义相似度搜索
```

**工作流程：**
1. 读取 `data/universal_samples.txt` 中的高评分样本
2. 使用BGE-large-zh模型将每个样本转换为向量
3. 保存向量到 `data/universal_samples_vectors.npy`
4. 保存元数据到 `data/universal_samples_data.json`

### 1.2 智能样本搜索

```python
# 文件：scripts/smart_sample_search.py
# 功能：根据查询找到最相关的样本

def search_and_adapt_samples(query, project_config, top_k=3):
    """搜索并适配样本"""
    # 1. 将查询转换为向量
    # 2. 计算与所有样本的余弦相似度
    # 3. 返回最相关的top_k个样本
    # 4. 根据项目配置适配样本内容（如替换角色名）
```

**适配机制：**
- 自动替换角色名（如将"陈雪"替换为项目主角）
- 调整背景设定（如将"朝堂"替换为"会议室"）
- 保持情感强度和写作风格

---

## 🤖 第二部分：生成模型如何利用RAG样本

### 2.1 增强版RAG生成器

```python
# 文件：scripts/enhanced_rag_generator.py
# 功能：真正利用RAG系统生成高质量内容

def generate_with_universal_samples(chapter_num, user_input):
    """使用通用样本生成章节"""
    
    # 1. 加载小说上下文
    context = load_novel_context()  # 前20章内容 + 章节梗概
    
    # 2. 从上下文中提取高评分片段
    high_score_snippets = extract_high_score_snippets_from_context(context)
    
    # 3. 搜索相关RAG样本
    adapted_samples = search_and_adapt_samples(user_input, project_config)
    
    # 4. 构建增强提示词
    enhanced_prompt = build_enhanced_rag_prompt(
        chapter_num, user_input, context, adapted_samples
    )
    
    # 5. 调用Qwen API生成内容
    response = dashscope.Generation.call(
        model='qwen-plus',
        prompt=enhanced_prompt
    )
```

### 2.2 提示词构建策略

```python
def build_enhanced_rag_prompt(chapter_num, user_input, context, adapted_samples):
    """构建增强的RAG提示词"""
    
    prompt = f"""
    你是专业的小说作家，正在创作《暗河噬城》第{chapter_num}章。
    
    【章节梗概】
    {context['outline']}
    
    【前文关键情节】
    {format_previous_chapters(context['previous_chapters'])}
    
    【高评分写作样本参考】
    {format_rag_samples(adapted_samples)}
    
    【用户要求】
    {user_input}
    
    【写作要求】
    1. 参考提供的高评分样本的写作风格和情感强度
    2. 保持与前文的连贯性
    3. 确保情节紧张，有冲突和悬念
    4. 字数控制在2000-3000字
    """
```

**关键机制：**
- **上下文感知**：利用前20章内容保持连贯性
- **样本引导**：RAG样本提供写作风格参考
- **情感强度控制**：确保生成内容具有高情绪评分

---

## 📊 第三部分：评分系统 - 评估生成内容质量

### 3.1 双重评分机制

```python
# 文件：scripts/optimized_rule_scorer.py (规则评分)
# 文件：scripts/paragraph_scorer.py (机器学习评分)

class OptimizedRuleScorer:
    """基于规则的评分系统"""
    def calculate_score(self, text):
        # 基于关键词、模式匹配、文本长度计算评分
        # 评分范围：20-100分
        # 分类：平淡(20-40) -> 极度紧张(80-100)
```

### 3.2 人工评分训练

```python
# 文件：scripts/manual_sample_scorer.py
# 功能：人工标注样本，训练更准确的评分模型

def manual_scoring_interface(sentences):
    """人工评分界面"""
    # 1. 提取所有样本句子
    # 2. 人工为每个句子评分(1-100)
    # 3. 保存评分数据
    # 4. 训练机器学习评分模型
```

**训练结果：**
- 使用78个人工评分样本训练
- 特征重要性：文本长度(71.3%) > 紧张度密度(9.0%) > 动作密度(6.6%)
- 新模型比规则评分更敏感，能更好识别情感强度

---

## 🔄 第四部分：反馈循环系统 - 评分回喂训练

### 4.1 反馈数据收集

```python
# 文件：scripts/record_feedback.py
# 功能：记录每次生成的评分结果

def record_generation_feedback(chapter_num, versions, selected_version, scores):
    """记录生成反馈"""
    feedback_data = {
        'timestamp': datetime.now(),
        'chapter_num': chapter_num,
        'candidate_file': selected_version['file'],
        'model_score': selected_version['score'],
        'user_feedback': None,  # 可后续人工标注
        'all_scores': scores
    }
    # 保存到 outputs/feedback_log.csv
```

### 4.2 训练数据准备

```python
# 文件：scripts/prepare_training_data.py
# 功能：将高评分生成内容转换为训练数据

def prepare_training_data_from_feedback(feedback_csv, min_score=70):
    """从反馈数据中准备训练数据"""
    
    # 1. 读取反馈日志
    df = pd.read_csv(feedback_csv)
    
    # 2. 筛选高评分样本
    high_quality = df[df['model_score'] >= min_score]
    
    # 3. 读取完整内容
    for _, row in high_quality.iterrows():
        content_file = f"data/candidates/{row['candidate_file']}"
        with open(content_file, 'r') as f:
            content = f.read()
        
        # 4. 构建训练样本
        training_sample = {
            'instruction': f"请续写《暗河噬城》第{row['chapter_num']}章",
            'input': '',
            'output': content,
            'score': row['model_score']
        }
```

### 4.3 模型重新训练

```python
# 文件：scripts/lora_training.py
# 功能：使用高评分内容重新训练生成模型

def train_model(model, tokenizer, train_dataset, output_dir):
    """训练LoRA模型"""
    
    # 1. 加载训练数据
    # 2. 配置LoRA参数（只训练1.75%的参数）
    # 3. 使用高评分内容训练
    # 4. 保存训练好的模型
```

### 4.4 反馈循环管理

```python
# 文件：scripts/feedback_loop_system.py
# 功能：管理整个反馈循环

class FeedbackLoopSystem:
    def analyze_score_trends(self):
        """分析评分趋势"""
        # 分析最近10次的评分趋势
        # 识别低分原因
        # 生成改进建议
    
    def update_rag_samples(self, min_score=70):
        """根据评分更新RAG样本库"""
        # 1. 从反馈日志中提取高评分内容
        # 2. 添加到RAG样本库
        # 3. 重新向量化样本库
    
    def suggest_training_adjustments(self):
        """建议训练调整"""
        # 根据评分趋势建议是否需要重新训练
        # 调整训练参数
```

---

## 🎯 完整工作流程总结

### 阶段1：初始化
1. **建立RAG样本库**：将高评分样本向量化存储
2. **训练评分模型**：使用人工评分训练ML评分器
3. **配置生成模型**：设置LoRA参数和训练配置

### 阶段2：生成循环
1. **用户输入**：提供章节梗概或要求
2. **RAG检索**：搜索相关高评分样本
3. **上下文整合**：结合前文内容和章节梗概
4. **内容生成**：使用增强提示词生成3个版本
5. **质量评分**：使用双重评分系统评估
6. **版本选择**：选择最高分版本

### 阶段3：反馈学习
1. **反馈记录**：将评分结果记录到日志
2. **趋势分析**：分析评分趋势和问题
3. **样本更新**：将高评分内容添加到RAG库
4. **模型重训**：使用高评分内容重新训练生成模型
5. **系统优化**：根据反馈调整参数和策略

### 关键创新点：

1. **真正的RAG集成**：不是简单的样本拼接，而是语义搜索+内容适配
2. **上下文感知生成**：利用前文内容保持连贯性
3. **双重评分机制**：规则评分+机器学习评分
4. **闭环反馈学习**：评分结果直接用于模型改进
5. **自适应样本库**：根据生成质量动态更新RAG样本

这个系统实现了从"样本学习"到"评分反馈"再到"模型改进"的完整闭环，确保生成内容的质量持续提升。

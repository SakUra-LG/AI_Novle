# 通用RAG样本库系统使用说明

## 🎯 系统概述

这是一个通用的RAG样本库系统，可以用于多种不同的小说项目。系统通过智能搜索和内容适配，将通用样本库中的高质量内容适配到不同的项目上下文中。

## 🏗️ 系统架构

```
通用样本库 → 智能搜索 → 内容适配 → 项目配置 → 生成指导 → 章节生成
     ↓           ↓         ↓         ↓         ↓         ↓
universal_   smart_    adapt_    project_   enhanced   generated
samples.txt  search    content   configs    prompt     chapters
```

## 📁 文件结构

```
├── data/
│   ├── universal_samples.txt          # 通用样本库
│   ├── universal_samples_vectors.npy  # 样本向量（自动生成）
│   ├── universal_samples_data.json    # 样本元数据（自动生成）
│   └── generated/                     # 生成的章节
│       ├── 暗河噬城/
│       ├── 仙侠传奇/
│       └── 宫廷秘史/
├── config/
│   └── project_configs.json          # 项目配置文件
├── scripts/
│   ├── handle_universal_samples.py   # 通用样本处理
│   ├── smart_sample_search.py        # 智能样本搜索
│   └── universal_generator.py        # 通用生成器
└── 细节生成资料/                      # 现有的RAG系统
    └── bge_large_zh/                 # BGE模型
```

## 🚀 快速开始

### 1. 初始化通用样本库

```bash
python scripts/handle_universal_samples.py
```

### 2. 生成不同项目的章节

```bash
# 为"暗河噬城"项目生成第24章
python scripts/universal_generator.py --project "暗河噬城" --chapter 24 --prompt "请写一段悬疑推理的情节"

# 为"仙侠传奇"项目生成第15章
python scripts/universal_generator.py --project "仙侠传奇" --chapter 15 --prompt "请写一段武侠对决的情节"

# 为"宫廷秘史"项目生成第8章
python scripts/universal_generator.py --project "宫廷秘史" --chapter 8 --prompt "请写一段宫廷权谋的情节"
```

## ⚙️ 项目配置

### 添加新项目

编辑 `config/project_configs.json` 文件：

```json
{
  "projects": {
    "新项目名称": {
      "main_character": "主角名字",
      "background": "背景设定",
      "style": "风格类型",
      "tags": ["标签1", "标签2", "标签3"],
      "description": "项目描述"
    }
  }
}
```

### 现有项目配置

- **暗河噬城**: 现代都市悬疑，主角陈雪
- **仙侠传奇**: 古代仙侠世界，主角林峰
- **宫廷秘史**: 古代宫廷，主角苏雨
- **科幻未来**: 未来科幻世界，主角张伟

## 🔍 样本库管理

### 添加新样本

编辑 `data/universal_samples.txt` 文件，按照以下格式添加：

```
N.类别名称高评分样本
"样本内容1"
"样本内容2"
"样本内容3"
```

### 样本分类

系统支持以下分类：
- 武侠对决
- 情感互动
- 悬疑推理
- 冒险探索
- 政治权谋
- 仙侠修炼
- 现代都市
- 古装宫廷
- 商战职场
- 科幻未来

### 智能标签系统

系统会自动为样本提取标签，包括：
- 基于内容的标签（武打、情感、悬疑等）
- 基于类别的标签
- 基于背景的标签

## 🧠 智能适配功能

### 1. 人物名字适配

系统会自动将样本中的人物名字适配到目标项目：

```python
# 示例：将样本中的"陈雪"替换为"林峰"
"陈雪站在悬崖边" → "林峰站在悬崖边"
```

### 2. 背景设定适配

系统会根据项目配置调整背景设定：

```python
# 示例：现代都市背景适配到古代宫廷
"陈雪在办公室里" → "陈雪在朝堂上"
```

### 3. 风格适配

系统会根据项目风格调整语言和情节：

```python
# 示例：悬疑风格适配到仙侠风格
"陈雪发现线索" → "陈雪感受到灵气波动"
```

## 📊 使用示例

### 示例1：为不同项目生成相同类型的情节

```bash
# 悬疑推理情节 - 暗河噬城项目
python scripts/universal_generator.py --project "暗河噬城" --chapter 24 --prompt "请写一段悬疑推理的情节"

# 悬疑推理情节 - 仙侠传奇项目
python scripts/universal_generator.py --project "仙侠传奇" --chapter 15 --prompt "请写一段悬疑推理的情节"
```

系统会自动：
1. 搜索悬疑推理类样本
2. 将样本中的人物名字适配到目标项目
3. 调整背景设定和语言风格
4. 生成符合项目特色的内容

### 示例2：批量生成多个章节

```bash
# 为暗河噬城项目生成多个章节
for i in {24..26}; do
    python scripts/universal_generator.py --project "暗河噬城" --chapter $i --prompt "请写一段悬疑推理的情节"
done
```

## 🔧 高级功能

### 1. 自定义适配规则

在 `config/project_configs.json` 中配置适配规则：

```json
{
  "sample_adaptation_rules": {
    "character_replacement": {
      "陈雪": ["林峰", "苏雨", "张伟"],
      "林峰": ["陈雪", "苏雨", "张伟"]
    },
    "background_adaptation": {
      "现代都市": ["古代宫廷", "仙侠世界", "科幻未来"],
      "古代宫廷": ["现代都市", "仙侠世界", "科幻未来"]
    }
  }
}
```

### 2. 样本质量评估

系统会自动评估样本质量：

```python
# 样本质量指标
- 相似度评分
- 适配度评分
- 内容质量评分
- 标签匹配度
```

### 3. 生成历史记录

系统会记录每次生成的详细信息：

```json
{
  "project": "暗河噬城",
  "chapter": 24,
  "version": 1,
  "content": "生成的内容...",
  "adapted_samples": ["使用的样本..."],
  "generated_at": "2024-01-01T12:00:00"
}
```

## 🚨 故障排除

### 常见问题

1. **样本库不存在**
   ```
   错误：样本库不存在，请先运行: python scripts/handle_universal_samples.py
   解决：运行样本处理脚本初始化数据库
   ```

2. **项目配置不存在**
   ```
   错误：项目 '新项目' 配置不存在
   解决：在 config/project_configs.json 中添加项目配置
   ```

3. **样本适配失败**
   ```
   错误：未找到适配样本
   解决：检查样本库是否有相关类别的样本，或降低相似度阈值
   ```

### 调试模式

在脚本中添加调试信息：

```python
# 在 smart_sample_search.py 中
print(f"查询向量维度: {query_vector.shape}")
print(f"样本向量维度: {sample_vectors.shape}")
print(f"相似度计算完成，最高相似度: {max(similarities):.3f}")
```

## 📈 性能优化

### 1. 批量处理

```python
# 批量生成多个章节
def batch_generate(project, chapters, prompt):
    for chapter in chapters:
        generate_with_universal_samples(project, chapter, prompt)
```

### 2. 缓存机制

```python
# 样本向量和元数据会被缓存
- data/universal_samples_vectors.npy - 向量缓存
- data/universal_samples_data.json - 元数据缓存
```

### 3. 内存优化

```python
# 分批处理大量样本
def process_large_dataset(samples, batch_size=100):
    for i in range(0, len(samples), batch_size):
        batch = samples[i:i+batch_size]
        # 处理批次
```

## 🔮 扩展功能

### 1. 动态样本更新

```python
def add_new_sample(category, content, tags):
    """动态添加新样本"""
    # 添加到样本库
    # 重新向量化
    # 更新缓存
```

### 2. 样本质量评估

```python
def evaluate_sample_quality(sample):
    """评估样本质量"""
    # 基于多个维度评分
    # 提供改进建议
```

### 3. 个性化推荐

```python
def recommend_samples(project_config, user_preferences):
    """基于项目配置推荐样本"""
    # 分析项目特点
    # 推荐相关样本
```

## 📝 总结

这个通用RAG样本库系统具有以下优势：

1. **通用性**: 支持多种不同的小说项目
2. **智能性**: 自动搜索和适配样本内容
3. **灵活性**: 易于添加新项目和样本
4. **高效性**: 基于向量相似度的快速检索
5. **可扩展性**: 支持自定义适配规则和扩展功能

通过使用这个系统，您可以：
- 为不同项目生成高质量内容
- 利用通用样本库的丰富资源
- 自动适配内容到不同项目上下文
- 提高生成效率和质量
- 保持项目间的一致性

系统完全基于您现有的细节生成资料方法，只是扩展了样本库的通用性和智能适配功能，使其能够支持多种不同的小说项目。

# 多标签系统使用指南

## 📋 目录
- [什么是多标签系统](#什么是多标签系统)
- [系统改造内容](#系统改造内容)
- [快速开始](#快速开始)
- [使用示例](#使用示例)
- [标签体系说明](#标签体系说明)
- [常见问题](#常见问题)

---

## 🎯 什么是多标签系统

### 单标签 vs 多标签

**❌ 旧的单标签格式：**
```
## 生死追逐
**标签**: 15
**评分**: 92.00
**内容**: 陈雪冲出大楼...
```
- 只有一个数字ID
- 无法表达样本的多个特征
- 检索时只能靠语义相似度

**✅ 新的多标签格式：**
```
## 生死追逐
**情绪标签**: 恐惧, 紧张, 绝望, 焦虑
**场景标签**: 现代都市, 室外, 高楼, 天台
**冲突标签**: 追捕逃亡, 生死危机, 围堵
**动作标签**: 奔跑, 闪避, 冲刺, 跳跃
**情节标签**: 前后夹击, 绝境, 生死抉择, 枪战
**评分**: 92.00
**内容**: 陈雪冲出大楼...
```
- 5个维度的标签
- 每个维度可以有多个标签
- 支持基于标签的精确过滤

### 多标签的优势

| 功能 | 单标签 | 多标签 |
|------|-------|--------|
| **信息量** | 仅ID编号 | 5个维度的描述性标签 |
| **检索方式** | 仅语义相似度 | 语义+标签过滤+评分 |
| **精确度** | 较低 | 高 |
| **可解释性** | 无 | 清晰的标签说明 |
| **训练效果** | 单一分类 | 可学习标签组合模式 |

---

## 🔧 系统改造内容

### 1. 样本集格式改造
- **文件**: `data/universal_samples.txt`
- **改动**: 为所有30+个样本添加完整的5维度标签
- **新增**: 8个高评分样本（评分85-97分）

### 2. 评分脚本改造
- **文件**: `scripts/incremental_sample_scorer.py`
- **改动**: 
  - 只评分**内容**部分，忽略标签和元数据
  - 解析新的多标签格式
  - 保存标签信息到评分结果

### 3. RAG检索系统升级
- **文件**: `scripts/smart_sample_search.py`
- **新增功能**:
  - 基于标签过滤检索
  - 基于评分阈值过滤
  - 多维度组合搜索
  - 返回完整标签信息

### 4. 向量化脚本更新
- **文件**: `scripts/handle_universal_samples.py`
- **改动**: 解析并保存多标签信息

---

## 🚀 快速开始

### 步骤1：重新向量化样本库

```bash
python scripts/handle_universal_samples.py
```

**输出：**
```
成功解析 30 个通用样本
向量化完成，特征维度: (30, 1024)
样本向量已保存: data/universal_samples_vectors.npy
样本数据已保存: data/universal_samples_data.json
```

### 步骤2：测试多标签检索

```bash
python scripts/multi_label_search_example.py
```

### 步骤3：在生成时使用

```python
from scripts.smart_sample_search import load_universal_samples, find_similar_samples

# 加载样本库
sample_vectors, samples = load_universal_samples()

# 基本搜索
results = find_similar_samples(
    query="紧张的追逐场景",
    sample_vectors=sample_vectors,
    samples=samples,
    top_k=3
)

# 带标签过滤的搜索
results = find_similar_samples(
    query="危机场景",
    sample_vectors=sample_vectors,
    samples=samples,
    top_k=3,
    required_tags={
        'emotion_tags': ['紧张', '恐惧'],
        'scene_tags': ['现代都市']
    },
    min_score=90  # 只要90分以上的样本
)
```

---

## 📝 使用示例

### 示例1：基本语义搜索

```python
# 搜索"紧张的追逐场景"
query = "紧张的追逐场景"
results = find_similar_samples(query, sample_vectors, samples, top_k=3)

# 结果会包含：
# - 生死追逐 (评分92, 相似度0.85)
# - 深夜惊魂 (评分90, 相似度0.78)
# - 审讯对峙 (评分86, 相似度0.72)
```

### 示例2：基于情绪标签过滤

```python
# 只要包含"紧张"和"恐惧"情绪的样本
results = find_similar_samples(
    query="危险场景",
    sample_vectors=sample_vectors,
    samples=samples,
    required_tags={
        'emotion_tags': ['紧张', '恐惧']
    }
)
```

### 示例3：基于场景标签过滤

```python
# 只要现代都市背景的样本
results = find_similar_samples(
    query="城市危机",
    sample_vectors=sample_vectors,
    samples=samples,
    required_tags={
        'scene_tags': ['现代都市']
    }
)
```

### 示例4：高分样本检索

```python
# 只要评分≥90的样本
results = find_similar_samples(
    query="生死危机",
    sample_vectors=sample_vectors,
    samples=samples,
    min_score=90
)
```

### 示例5：复杂组合搜索

```python
# 现代都市 + 紧张情绪 + 高评分
results = find_similar_samples(
    query="都市危机场景",
    sample_vectors=sample_vectors,
    samples=samples,
    required_tags={
        'emotion_tags': ['紧张'],
        'scene_tags': ['现代都市']
    },
    min_score=85
)
```

---

## 🏷️ 标签体系说明

### 1. 情绪标签（emotion_tags）
描述样本的情感强度和类型

**常用标签：**
- 紧张、恐惧、焦虑、绝望
- 愤怒、压抑、凝重
- 温馨、甜蜜、羞涩、浪漫
- 震撼、激烈、凶险
- 好奇、期待、警觉

**使用场景：**
- 筛选高情绪强度的样本
- 匹配特定情感需求
- 避免情感不匹配的样本

### 2. 场景标签（scene_tags）
描述样本的背景设定和环境

**常用标签：**
- **时代背景**: 现代都市、古代宫廷、仙侠世界、科幻未来、武侠江湖
- **空间类型**: 室内、室外、密闭空间、开阔场景
- **具体场所**: 办公室、会议室、朝堂、飞船、天台、山谷

**使用场景：**
- 匹配小说的时代背景
- 筛选特定环境的样本
- 保持场景一致性

### 3. 冲突标签（conflict_tags）
描述样本的冲突类型和强度

**常用标签：**
- **生死类**: 生死对决、生死危机、追捕逃亡
- **心理类**: 心理博弈、心理压迫、智斗
- **权力类**: 政治斗争、权谋阴谋、商业竞争
- **调查类**: 调查真相、发现线索、揭露秘密

**使用场景：**
- 匹配情节的冲突强度
- 筛选特定类型的对抗
- 构建紧张的情节节奏

### 4. 动作标签（action_tags）
描述样本的行动和动作类型

**常用标签：**
- **武打**: 武打、拳法、剑法、闪避、格挡
- **追逐**: 奔跑、追逐、逃跑、跳跃
- **对峙**: 对视、站立、面对、警戒
- **调查**: 检查、研究、观察、推理
- **操作**: 敲击键盘、剪线、操作、抉择

**使用场景：**
- 匹配动作场景需求
- 筛选特定动作类型
- 构建动感十足的画面

### 5. 情节标签（plot_tags）
描述样本的情节元素和叙事特点

**常用标签：**
- **危机类**: 倒计时、生死抉择、绝境、危机迫近
- **反转类**: 反转、阴谋揭露、真相揭露
- **关系类**: 表白、情感确认、身份反转
- **环境类**: 环境描写、气氛营造、坍塌危机

**使用场景：**
- 增强情节的戏剧性
- 筛选特定叙事元素
- 构建跌宕起伏的故事

---

## 🎨 实际应用场景

### 场景1：生成悬疑推理章节

```python
# 需求：现代都市背景的悬疑推理场景
results = find_similar_samples(
    query="调查可疑线索",
    sample_vectors=sample_vectors,
    samples=samples,
    required_tags={
        'scene_tags': ['现代都市'],
        'conflict_tags': ['调查真相', '发现线索']
    },
    min_score=75
)
```

### 场景2：生成武侠对决章节

```python
# 需求：紧张激烈的武侠对决
results = find_similar_samples(
    query="武侠高手对决",
    sample_vectors=sample_vectors,
    samples=samples,
    required_tags={
        'emotion_tags': ['紧张', '激烈'],
        'scene_tags': ['武侠江湖'],
        'action_tags': ['武打']
    },
    min_score=85
)
```

### 场景3：生成危机倒计时场景

```python
# 需求：高评分的倒计时危机场景
results = find_similar_samples(
    query="倒计时拆弹",
    sample_vectors=sample_vectors,
    samples=samples,
    required_tags={
        'emotion_tags': ['紧急', '焦虑'],
        'plot_tags': ['倒计时']
    },
    min_score=90  # 只要最高分的样本
)
```

---

## ❓ 常见问题

### Q1: 旧的样本还能用吗？
**A**: 已全部更新为新格式，旧格式不再使用。

### Q2: 评分时会评标签吗？
**A**: 不会，评分**只针对内容部分**，标签仅用于检索。

### Q3: 可以自己添加新标签吗？
**A**: 可以！按照格式添加即可：
```
## 新样本标题
**情绪标签**: 标签1, 标签2
**场景标签**: 标签1, 标签2
...
**内容**: 样本内容
```

### Q4: 标签必须全部填写吗？
**A**: 建议全部填写，但至少要有：
- 情绪标签
- 场景标签
- 内容
- 评分

### Q5: 如何查看当前有哪些标签？
**A**: 运行统计脚本：
```bash
python scripts/multi_label_search_example.py
```
查看"示例5：样本库标签统计"部分。

### Q6: 标签过滤是"与"还是"或"的关系？
**A**: 同一维度内是"或"关系，不同维度间是"与"关系。

例如：
```python
required_tags={
    'emotion_tags': ['紧张', '恐惧'],  # 有其中一个就行（或）
    'scene_tags': ['现代都市']         # 必须有（与）
}
```

### Q7: 重新向量化会丢失之前的评分吗？
**A**: 不会！评分保存在样本文件中，重新向量化只是更新检索索引。

---

## 📊 系统性能

### 检索速度
- **样本数量**: 30个
- **向量维度**: 1024
- **检索时间**: <0.1秒
- **支持规模**: 可扩展到10000+样本

### 准确度提升
- **语义检索**: 相似度匹配准确
- **标签过滤**: 100%精确匹配
- **组合检索**: 显著提升相关性

---

## 🎓 最佳实践

### 1. 添加新样本时
- ✅ 填写完整的5维标签
- ✅ 确保评分客观准确
- ✅ 内容长度适中（50-300字）
- ✅ 标签简洁明了

### 2. 使用检索时
- ✅ 优先使用标签过滤
- ✅ 设置合理的评分阈值
- ✅ 组合使用多个维度
- ✅ 根据结果调整查询

### 3. 维护样本库
- ✅ 定期review标签准确性
- ✅ 补充缺失的样本类型
- ✅ 删除低质量样本
- ✅ 保持标签命名一致

---

## 🔗 相关文档

- [样本系统指南](SAMPLE_SYSTEM_GUIDE.md)
- [RAG系统文档](UNIVERSAL_RAG_SYSTEM_README.md)
- [技术文档](TECHNICAL_DOCUMENTATION.md)
- [工作流程说明](SYSTEM_WORKFLOW_EXPLANATION.md)

---

<div align="center">

**🎉 多标签系统让样本检索更智能、更精准！**

Made with ❤️ by AI Novel Generation System

</div>


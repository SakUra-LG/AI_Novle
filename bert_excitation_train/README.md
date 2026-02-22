# 🚀 AI小说自动生成系统

<div align="center">

**一个功能完整的生产级AI小说创作系统**

[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Production-success.svg)]()

</div>

---

## 📖 项目简介

本项目是一个**生产级别的AI小说自动生成系统**，集成了内容生成、质量评估、模型训练、反馈优化等完整功能链。系统采用RAG（检索增强生成）技术，结合大语言模型和机器学习评分系统，实现了**自我学习和持续改进**的智能创作能力。

### ✨ 核心亮点

- 🎯 **闭环学习系统**：生成→评分→反馈→训练→改进的完整循环
- 🧠 **RAG增强生成**：基于BGE模型的语义检索，智能利用高评分样本
- 📊 **双重评分机制**：规则评分+机器学习评分，确保质量评估准确性
- 🔄 **持续自动优化**：自动检测低分循环，智能触发模型重训练
- 🎨 **多项目支持**：同一套系统可适配多个不同的小说项目
- 💡 **增量式学习**：只处理新增数据，避免重复工作，高效迭代

---

## 🎯 核心功能模块

### 1️⃣ 智能内容生成

#### 多种生成方法
- **传统直接生成**：快速生成，适合初稿和测试
- **思维链生成（CoT）**：5步推理过程，生成高质量内容
  - 情节构思分析 → 情感设计 → 对话设计 → 内容生成 → 质量优化
- **混合生成**：平衡质量与速度的最佳方案
- **手动输入生成**：支持自定义创作需求

#### 生成特性
- ✅ 多版本生成（一次生成3-5个版本供选择）
- ✅ 上下文感知（自动加载前文章节保持连贯性）
- ✅ 动态章节加载（无需手动更新代码）
- ✅ 配置化管理（灵活的参数配置）

### 2️⃣ RAG检索增强系统

#### 核心能力
- **通用样本库**：管理和存储高评分写作样本
- **语义检索**：基于BGE-Large-ZH模型的智能搜索
- **样本向量化**：768/1024维向量表示，精确语义匹配
- **智能适配**：
  - 自动替换角色名称
  - 调整背景设定（现代都市↔古代宫廷↔仙侠世界）
  - 保持情感强度和写作风格

#### 多项目支持
- 同一套样本库支持多个不同项目
- 自动适配不同的小说背景和角色
- 细节生成资料系统（专门的仙侠小说素材库）

### 3️⃣ 智能评分系统

#### 双重评分机制
- **规则评分器**：基于关键词、模式匹配（20-100分）
- **机器学习评分器**：基于人工标注训练的ML模型
- **综合评分**：取两者平均值，提高准确性

#### 评估维度
- 📈 情节强度（冲突、转折、悬念）
- 💭 情感表达（愤怒、紧张、好奇）
- ✍️ 语言质量（流畅性、生动性）
- 🏗️ 结构完整性（起承转合）
- 💡 创新性（新颖度、独特性）

#### 标注工具
- 人工评分接口（友好的交互式界面）
- 增量评分（只评分新增样本，避免重复）
- 批量处理（高效的批量评分工具）

### 4️⃣ 模型训练系统

#### 多种训练方法
- **LoRA训练**：低秩适应，只训练1.75%参数，高效快速
- **全参数微调**：完整模型训练，效果显著
- **DPO训练**：基于偏好数据的直接优化
- **增量训练**：只训练新增数据，避免重复训练

#### 训练特性
- 🎓 自动训练数据准备（从高评分内容生成）
- 💾 多模型检查点管理（保存多个训练版本）
- 📊 训练历史记录（完整的训练过程追踪）
- 🔄 智能训练触发（根据评分趋势自动训练）

### 5️⃣ 反馈循环与持续优化

#### 自动化反馈系统
- **反馈记录**：记录每次生成的评分和详细信息
- **趋势分析**：分析评分趋势，识别问题模式
- **低分循环检测**：自动检测低质量内容循环
- **智能修复**：
  - 数据清洗（删除低分样本）
  - 阈值调整（动态优化评分标准）
  - 参数优化（自动调整生成参数）
  - 重新生成（使用优化后的策略）

#### 持续改进机制
- 高评分内容自动添加到样本库
- 根据反馈自动触发模型重训练
- 样本库动态更新和扩充
- 质量持续提升的闭环系统

### 6️⃣ 上下文管理系统

- **动态章节加载**：自动扫描并加载已有章节
- **智能上下文构建**：
  - 加载前N章内容（可配置）
  - 提取章节梗概
  - 识别高评分片段
  - 保持角色关系和情节连贯
- **配置化管理**：通过JSON文件灵活配置

### 7️⃣ 质量控制工具

- ✔️ 增量样本评分（避免重复工作）
- 🖱️ 交互式标注系统（友好的人工标注界面）
- 📁 样本分类管理（武侠、情感、悬疑等10+类别）
- 📈 质量评估报告（详细的分析报告）
- 🔧 编码自动修复（处理文件编码问题）

---

## 🚀 快速开始

### 环境配置

```bash
# 1. 克隆项目
git clone <repository-url>
cd bert_excitation_train

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置API密钥（如需使用）
# 编辑 config.py 或相关配置文件
```

### 基本使用流程

#### 方法一：直接生成章节

```bash
# 传统生成（快速）
python scripts/generate_final.py --chap_num 24 --variant_id 1

# 增强RAG生成（高质量）
python scripts/enhanced_rag_generator.py --chapter 24 --prompt "生成紧张悬疑的情节"
```

#### 方法二：完整工作流程

```bash
# 1. 初始化样本库（首次使用）
python scripts/handle_universal_samples.py

# 2. 人工评分样本（增量评分，只评新样本）
python scripts/incremental_sample_scorer.py

# 3. 训练模型（增量训练，只训新数据）
python scripts/incremental_model_trainer.py

# 4. 生成内容
python scripts/enhanced_rag_generator_v2.py --prompt "你的创作需求" --min_score 70
```

---

## 📋 核心脚本索引

### 🎨 生成相关
```
scripts/
├── generate_final.py              # 传统直接生成
├── enhanced_rag_generator.py      # RAG增强生成（推荐）
├── enhanced_rag_generator_v2.py   # RAG增强生成V2（支持评分过滤）
├── manual_generator.py            # 手动输入生成
└── universal_generator.py         # 通用多项目生成器
```

### 📊 评分相关
```
scripts/
├── optimized_rule_scorer.py       # 规则评分器
├── paragraph_scorer.py            # ML评分器
├── score_candidates_rule_based.py # 批量候选评分
├── incremental_sample_scorer.py   # 增量样本评分（推荐）
└── interactive_annotation.py      # 交互式标注工具
```

### 🎓 训练相关
```
scripts/
├── lora_training.py               # LoRA训练
├── finetune_model.py              # 全参数微调
├── incremental_model_trainer.py   # 增量模型训练（推荐）
├── prepare_training_data.py       # 训练数据准备
└── smart_training_manager.py      # 智能训练管理
```

### 🔄 RAG系统相关
```
scripts/
├── handle_universal_samples.py    # 样本向量化
├── smart_sample_search.py         # 智能样本搜索
├── verify_rag_effectiveness.py    # RAG效果验证
└── sample_collector_tool.py       # 样本收集工具
```

### 📈 反馈与优化
```
scripts/
├── record_feedback.py             # 反馈记录
├── feedback_loop_system.py        # 反馈循环系统
├── smart_context_loader.py        # 智能上下文加载
└── complete_workflow.py           # 完整工作流程
```

---

## 💡 使用建议与最佳实践

### 生成方法选择

| 场景 | 推荐方法 | 预期质量 | 速度 |
|------|---------|---------|------|
| 快速测试 | 传统生成 | 60-70分 | ⚡⚡⚡ |
| 日常创作 | RAG增强生成 | 70-80分 | ⚡⚡ |
| 高质量输出 | RAG增强V2 + min_score=70 | 80-90分 | ⚡ |
| 自定义需求 | 手动输入生成 | 可变 | ⚡⚡ |

### 参数调优建议

#### 评分阈值设置
- **宽松模式**（50分）：快速生成，接受较多内容
- **标准模式**（60分）：平衡质量与数量
- **严格模式**（70分）：只接受高质量内容
- **完美模式**（80分）：极高标准，生成较慢

#### 样本库管理
- 定期添加新的高质量样本
- 每周运行增量评分（不会重复评分已有样本）
- 每月运行增量训练（只训练新增数据）
- 保持样本分类清晰（武侠、情感、悬疑等）

### 工作流程建议

#### 🌟 推荐工作流（增量式）
```
1. 添加新样本到 data/universal_samples.txt
   ↓
2. 运行增量评分（只评新样本）
   python scripts/incremental_sample_scorer.py
   ↓
3. 运行增量训练（只训新数据）
   python scripts/incremental_model_trainer.py
   ↓
4. 生成内容
   python scripts/enhanced_rag_generator_v2.py --prompt "..." --min_score 70
   ↓
5. 高分内容自动加入样本库，循环改进
```

#### 传统工作流（完整循环）
```
生成 → 评分 → 记录反馈 → 分析趋势 → 更新样本库 → 训练模型 → 再次生成
```

---

## 📁 项目结构

```
bert_excitation_train/
│
├── 📂 scripts/                         # 核心脚本目录（57个脚本）
│   ├── 🎨 生成相关
│   ├── 📊 评分相关
│   ├── 🎓 训练相关
│   ├── 🔄 RAG系统相关
│   └── 📈 反馈优化相关
│
├── 📂 data/                            # 数据目录
│   ├── chapters/                       # 最终章节文件
│   ├── candidates/                     # 候选版本文件
│   ├── training/                       # 训练数据（40个文件）
│   ├── labeled/                        # 标注数据（10个文件）
│   ├── generated/                      # 生成内容
│   ├── universal_samples.txt           # 通用样本库（核心）
│   ├── universal_samples_vectors.npy   # 样本向量
│   └── universal_samples_data.json     # 样本元数据
│
├── 📂 checkpoints/                     # 模型检查点
│   ├── lora_model/                     # LoRA训练模型
│   ├── lora_model_auto/                # 自动训练模型
│   ├── regressor/                      # 评分回归模型
│   ├── regressor_enhanced/             # 增强评分模型
│   └── optimized_rule_scorer/          # 优化规则评分器
│
├── 📂 config/                          # 配置文件
│   ├── generation_config.json          # 生成配置
│   └── project_configs.json            # 项目配置
│
├── 📂 outputs/                         # 输出结果
│   ├── feedback_log.csv                # 反馈日志
│   └── *_scores_*.csv                  # 各种评分结果
│
├── 📂 细节生成资料/                     # RAG系统资源
│   ├── bge_large_zh/                   # BGE向量模型
│   ├── knowledgeBase/                  # 知识库
│   ├── Handle_Content.py               # 内容处理
│   ├── Handle_Profession.py            # 专业知识处理
│   ├── Search_content.py               # 内容搜索
│   └── Search_profession.py            # 专业搜索
│
├── 📄 requirements.txt                 # Python依赖
│
└── 📚 文档
    ├── README.md                       # 本文档
    ├── TECHNICAL_DOCUMENTATION.md      # 技术文档
    ├── SYSTEM_WORKFLOW_EXPLANATION.md  # 工作流程说明
    ├── UNIVERSAL_RAG_SYSTEM_README.md  # RAG系统文档
    ├── SAMPLE_SYSTEM_GUIDE.md          # 样本系统指南
    └── WORKFLOW_EXAMPLE.md             # 工作流程示例
```

---

## 📚 详细文档

### 核心文档
- 📖 **[技术文档](TECHNICAL_DOCUMENTATION.md)** - 完整的技术架构和实现原理
- 🔄 **[工作流程说明](SYSTEM_WORKFLOW_EXPLANATION.md)** - 系统完整工作流程解析
- 📝 **[工作流程示例](WORKFLOW_EXAMPLE.md)** - 具体运行示例

### 专题文档
- 🧠 **[RAG系统文档](UNIVERSAL_RAG_SYSTEM_README.md)** - RAG检索增强系统详解
- 📊 **[样本系统指南](SAMPLE_SYSTEM_GUIDE.md)** - 样本管理和使用指南
- 🛠️ **[动态章节加载方案](DYNAMIC_CHAPTER_LOADING_SOLUTION.md)** - 智能上下文加载

### RAG技术文档
- 🔬 **[RAG技术使用文档](细节生成资料/RAG技术使用文档.md)** - BGE模型和RAG技术详解

---

## 🎓 技术栈

### 核心技术
- **大语言模型**: Qwen2-1.5B-Instruct（通义千问）
- **向量模型**: BGE-Large-ZH（智源研究院）
- **深度学习框架**: PyTorch, Transformers
- **训练方法**: LoRA, Fine-tuning, DPO

### 数据处理
- **数据分析**: Pandas, NumPy
- **向量计算**: Scikit-learn
- **文本处理**: Tokenizers

---

## 🌟 特色功能展示

### 1. 增量学习系统
```python
# 只处理新增样本，避免重复工作
python scripts/incremental_sample_scorer.py   # 智能识别新样本
python scripts/incremental_model_trainer.py   # 只训练新数据
```

### 2. RAG智能检索
```python
# 基于语义相似度检索高质量样本
query = "紧张的武打场面"
samples = search_and_adapt_samples(query, top_k=3)
# 自动适配角色名和背景设定
```

### 3. 双重评分机制
```python
# 规则评分 + ML评分 = 综合评分
rule_score = rule_scorer.calculate_score(text)     # 65分
ml_score = ml_scorer.predict_score(text)            # 72分
final_score = (rule_score + ml_score) / 2           # 68.5分
```

### 4. 自动化反馈循环
```python
# 生成 → 评分 → 记录 → 分析 → 优化 → 再生成
if best_version['score'] >= 70:
    add_to_sample_library(best_version)  # 自动加入样本库
    trigger_model_retraining()           # 触发模型重训练
```

---

## 📈 性能指标

| 指标 | 传统生成 | RAG增强生成 | 增量优化后 |
|------|---------|-----------|-----------|
| 平均评分 | 60-70分 | 70-80分 | 80-90分 |
| 生成速度 | 30-60秒 | 1-2分钟 | 1-2分钟 |
| 质量稳定性 | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 持续改进能力 | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

---

## 🎯 适用场景

- ✅ **长篇小说批量创作** - 支持多章节连续生成
- ✅ **多项目内容管理** - 同一系统支持不同项目
- ✅ **AI写作质量优化** - 持续提升生成质量
- ✅ **写作风格迁移** - 样本适配不同风格
- ✅ **内容质量评估** - 自动化质量评分
- ✅ **创作素材管理** - 智能检索和利用

---

## ⚠️ 注意事项

### 首次使用
1. **模型下载**: 首次运行需要下载模型，确保网络连接正常
2. **API配置**: 如使用通义千问API，需配置API密钥
3. **依赖安装**: 确保所有Python依赖正确安装

### 系统要求
- **Python版本**: 3.7+
- **内存**: 建议8GB以上
- **显卡**: 推荐使用GPU加速（可选）
- **磁盘空间**: 建议10GB以上

### 使用建议
1. **定期维护**: 每周评分新样本，每月训练模型
2. **质量监控**: 定期检查生成质量和评分趋势
3. **备份数据**: 定期备份样本库和模型检查点
4. **参数调优**: 根据实际效果调整评分阈值和生成参数

---

## 🤝 贡献与反馈

如有问题或建议，请：
1. 查看相关技术文档
2. 检查日志文件（`outputs/`目录）
3. 参考示例和最佳实践

---

## 📄 许可证

本项目遵循 MIT 许可证。

---

## 🙏 致谢

- **通义千问**: 提供大语言模型API支持
- **智源研究院**: BGE-Large-ZH中文向量模型
- **Hugging Face**: Transformers框架和模型支持

---

<div align="center">

**🎉 开始您的AI创作之旅！**

Made with ❤️ by AI Novel Generation System

</div>
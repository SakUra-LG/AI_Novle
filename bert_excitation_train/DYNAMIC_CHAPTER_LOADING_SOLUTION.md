# 动态章节加载解决方案

## 问题描述

原来的 `enhanced_rag_generator.py` 中硬编码了章节范围（1-20章），每次生成新章节后都需要手动修改代码。

## 解决方案

### 1. 智能上下文加载器 (`smart_context_loader.py`)

**功能特点：**
- 动态扫描 `data/chapters` 目录中的所有章节文件
- 支持多种文件命名格式：`01.txt`, `02.txt`, `24.txt` 等
- 自动排除不需要的文件：`第*章.txt`, `*_evaluation.json`
- 可配置的最大章节数限制
- 提供详细的加载信息反馈

**核心函数：**
```python
def load_novel_context_smart(max_chapters=20, config_file="config/generation_config.json"):
    """智能加载小说上下文信息"""
    # 动态扫描章节文件
    # 按章节号排序
    # 返回结构化的上下文信息
```

### 2. 配置文件支持 (`config/generation_config.json`)

**配置项：**
```json
{
    "context_settings": {
        "max_context_chapters": 20,        // 最大上下文章节数
        "recent_chapters_count": 3,        // 最近章节数
        "outline_max_length": 500,         // 梗概最大长度
        "snippet_max_length": 150,         // 片段最大长度
        "chapter_summary_length": 200     // 章节摘要长度
    },
    "file_patterns": {
        "chapter_files": ["*.txt"],                    // 章节文件模式
        "exclude_patterns": ["第*章.txt", "*_evaluation.json"], // 排除模式
        "candidate_patterns": ["*_v*.txt"]            // 候选文件模式
    }
}
```

### 3. 更新的生成器 (`enhanced_rag_generator.py`)

**新增功能：**
- 使用智能加载器替代硬编码
- 支持命令行参数 `--max-context` 控制上下文章节数
- 显示可用章节信息
- 更灵活的配置支持

## 使用方法

### 基本使用
```bash
# 使用默认20章上下文
python scripts/enhanced_rag_generator.py --chapter 25 --prompt "生成第25章内容"

# 使用30章上下文
python scripts/enhanced_rag_generator.py --chapter 25 --prompt "生成第25章内容" --max-context 30

# 生成5个版本
python scripts/enhanced_rag_generator.py --chapter 25 --prompt "生成第25章内容" --versions 5
```

### 测试智能加载器
```bash
python scripts/smart_context_loader.py
```

**输出示例：**
```
找到 24 个章节文件
成功加载 20 章前文内容
==================================================
上下文加载信息
==================================================
前文章节数: 20
章节范围: 1 - 20
章节列表: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
梗概文件: 已加载
==================================================

所有可用章节: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]
```

## 优势

### 1. **自动化**
- 无需手动修改代码
- 自动发现新章节文件
- 自动处理文件命名格式

### 2. **灵活性**
- 可配置的上下文章节数
- 支持多种文件命名格式
- 可排除不需要的文件

### 3. **可维护性**
- 配置与代码分离
- 清晰的错误处理
- 详细的日志信息

### 4. **扩展性**
- 易于添加新的文件格式支持
- 可配置的排除规则
- 模块化设计

## 文件结构

```
scripts/
├── enhanced_rag_generator.py      # 更新的生成器（使用智能加载）
├── smart_context_loader.py        # 智能上下文加载器
└── ...

config/
└── generation_config.json         # 生成配置文件

data/
└── chapters/
    ├── 01.txt                     # 第1章
    ├── 02.txt                     # 第2章
    ├── ...
    ├── 24.txt                     # 第24章
    └── 第1章.txt                  # 被排除的文件
```

## 注意事项

1. **文件命名**：确保章节文件使用数字命名（如 `01.txt`, `24.txt`）
2. **配置更新**：如需修改默认设置，编辑 `config/generation_config.json`
3. **性能考虑**：上下文章节数过多可能影响生成速度
4. **内存使用**：大量章节内容会占用更多内存

## 未来改进

1. **增量加载**：只加载最近N章，而不是所有章节
2. **缓存机制**：缓存已加载的章节内容
3. **并行加载**：并行读取多个章节文件
4. **智能摘要**：自动生成章节摘要而不是完整内容

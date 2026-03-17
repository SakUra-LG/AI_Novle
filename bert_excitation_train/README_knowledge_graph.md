# 重生小说知识图谱

用于保证文章前后一致性、伏笔回收。本地 JSON 存储，无需数据库，支持按章节追溯与回滚。

---

## 一、功能与原理

### 1. 解决的问题

- **前后一致**：人名、称谓、关系、地点等在全书内不冲突
- **伏笔回收**：记录埋下的伏笔，在合适章节提醒模型回收
- **关系约束**：人物间的恩怨、信任关系可供生成参考

### 2. 工作流程

1. **初始化**：从梗概和上一世线索中抽取实体、关系、伏笔，建立初始图谱
2. **生成前**：生成某章前，查询与本章相关的子集，拼入 prompt
3. **生成后**：从新正文中抽取实体、伏笔，更新图谱并保存
4. **回滚**：重做某几章时，先删除这些章节的图谱记录，再重新生成

### 3. 抽取方式（大模型）

- **初始化**：从梗概用大模型抽取实体、关系、伏笔
- **正文生成后**：每章生成完，用大模型从正文抽取并更新图谱
- 两处均调用通义千问 API，输出结构化 JSON 写入图谱

### 4. 数据设计

- **实体**：人物、地点、组织等，含 `source_chapters`（来源章节）
- **关系**：如「沈清欢 被陷害 陈主任」，含来源
- **伏笔**：内容、埋下章节、待回收章节，含来源

每条记录都标出来源，便于回溯时只删除指定章节相关记录。

---

## 二、脚本说明

| 脚本 | 作用 |
|------|------|
| `scripts/knowledge_graph.py` | 核心模块，可被正文生成器导入 |
| `scripts/init_knowledge_graph.py` | 根据梗概初始化图谱 |
| `scripts/rollback_knowledge_graph.py` | 回溯：删除指定章节的图谱记录 |

输出文件：`outputs/knowledge_graph.json`

---

## 三、使用流程

### 1. 初始化（正文生成前执行一次）

```bash
cd bert_excitation_train
python scripts/init_knowledge_graph.py
```

从 `outputs/master_ctx_final.txt`（或 `master_ctx.txt`）和 `outputs/prev_life_ctx_final.txt` 抽取，写入 `outputs/knowledge_graph.json`。

### 2. 正文生成（自动同步图谱）

```bash
python scripts/generate_chapter_content.py --chapter 6 --batch 5
```

- 生成前：查询本章相关实体、关系、伏笔，拼入 prompt
- 生成后：从正文抽取并更新图谱

使用 `--no-kg` 可禁用知识图谱。

### 3. 回溯（重做某几章前）

```bash
# 删除图谱中来源自 6～10 章的所有记录
python scripts/rollback_knowledge_graph.py --chapters 6-10

# 可选：同时删除对应正文文件
python scripts/rollback_knowledge_graph.py --chapters 4-5 --delete-files
```

然后重新执行正文生成。

---

## 四、参数示例

**init_knowledge_graph.py**
```bash
python scripts/init_knowledge_graph.py
python scripts/init_knowledge_graph.py --master outputs/master_ctx.txt --output outputs/kg.json
```

**rollback_knowledge_graph.py**
```bash
python scripts/rollback_knowledge_graph.py --chapters 6-10
python scripts/rollback_knowledge_graph.py --chapters 6 7 8 9 10 --delete-files
```

---

## 五、与其他脚本的关系

```
fix_master_synopsis.py / fix_prev_life_synopsis.py  → 梗概修正
                    ↓
        init_knowledge_graph.py  → 初始化图谱
                    ↓
        generate_chapter_content.py  → 生成正文（查图、更图）
                    ↑
        rollback_knowledge_graph.py  → 重做前回滚
```

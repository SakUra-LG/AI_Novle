# 知识图谱使用说明

用于重生复仇小说的前后一致性、伏笔回收。本地 JSON 存储，支持按章节追溯与回滚。

## 一、脚本说明

| 脚本 | 作用 |
|------|------|
| `knowledge_graph.py` | 核心模块，可被正文生成器导入 |
| `init_knowledge_graph.py` | 根据章节梗概初始化图谱 |
| `rollback_knowledge_graph.py` | 回溯：删除指定章节的图谱记录 |

## 二、使用流程

### 1. 初始化（正文生成前执行一次）

```bash
cd bert_excitation_train
python scripts/init_knowledge_graph.py
```

会从 `outputs/master_ctx_final.txt`（或 `master_ctx.txt`）和 `outputs/prev_life_ctx_final.txt` 抽取**全局设定 + 关键伏笔**，写入 `outputs/knowledge_graph.json`。

抽取策略（已在代码中实现）：

- **只保留全局设定**：时代、城市/行业背景、主角姓名、核心反派、关键医院/公司/组织等。
- **关系只保留长期不变的大关系**：如谁是院长、某组织控制某医院，而不是一次性吵架。
- **伏笔只保留跨多章的关键线索**：例如重要证据、神秘账户/组织、“天启”之类长期悬而未决的问题。

### 2. 正文生成（自动同步图谱）

```bash
python scripts/generate_chapter_content.py --chapter 6 --batch 5
```

- 生成每章前：从图谱查询「本章相关的世界观 + 尚未回收的关键伏笔」，拼入 prompt  
  （只输出一条世界观行 + 若干 `【关键伏笔】...`，不会把所有实体/关系都塞给模型，避免噪音）
- 生成每章后：从正文抽取**极少量核心人物/组织**和**新埋下的伏笔**，更新并保存图谱

使用 `--no-kg` 可禁用知识图谱。

### 3. 回溯（重做某几章前）

若对第 6～10 章不满意，需重生成时：

```bash
# 删除图谱中来源自 6、7、8、9、10 章的所有记录
python scripts/rollback_knowledge_graph.py --chapters 1-10

# 可选：同时删除对应正文文件
python scripts/rollback_knowledge_graph.py --chapters 1-10 --delete-files
```

然后再重新执行正文生成（会重新抽取并加入图谱）。  
> 注意：除了显式回滚外，图谱在查询时也会**自动移除已回收的伏笔**——当当前章节号 `>= recover_chapter` 时，视为该伏笔已回收，不再出现在后续章节的提示中，从而避免图谱越积越乱。

## 三、参数示例

- `init_knowledge_graph.py --master outputs/master_ctx.txt --prev-life outputs/prev_life_ctx.txt --output outputs/kg.json`
- `rollback_knowledge_graph.py --chapters 6 7 8 9 10` 或 `--chapters 6-10`

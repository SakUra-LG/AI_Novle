# 知识图谱与故事记忆

本目录负责把章节正文转换为 Neo4j 知识图谱，并维护正文生成所需的角色状态、关系、事件和连续性记忆。正文生成模块会从这里读取故事记忆与上下文导出结果。

## 主要入口

- `test_connection.py`：只读检查 Neo4j 连接。
- `bootstrap_neo4j.py`：创建约束和索引；`--reset` 会清空数据库，交接时不要默认使用。
- `build_from_chapters.py`：从 `work_outputs/chapters/` 的章节文本增量构图。
- `export_for_v2.py`：导出 V2 正文生成所需的实体、关系和伏笔上下文。
- `chapter_memory.py`、`story_memory.py`、`story_memory_store.py`：章节状态与连续性记忆。
- `characters.yaml`、`relationships.yaml`、`plot_clusters.yaml`：可人工维护的图谱配置。

## 环境变量

```powershell
$env:NEO4J_URI = "bolt://localhost:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "你的密码"
```

## 常用命令

请在仓库根目录运行：

```powershell
python -m bert_excitation_train.scripts.knowledge_graph.test_connection
python -m bert_excitation_train.scripts.knowledge_graph.bootstrap_neo4j
python -m bert_excitation_train.scripts.knowledge_graph.build_from_chapters --min-name-freq 5
python -m bert_excitation_train.scripts.knowledge_graph.export_for_v2 --chapters "11,12,13" --lookback 2 --out "work_outputs/export_v2.json"
```

涉及删除章节或清空数据库的命令均应先查看 `--help`，并优先使用 `--dry-run`（若该入口支持）。

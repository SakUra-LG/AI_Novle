## Neo4j 知识图谱最简上手（本地或云端）

本说明帮助你从零开始：安装 Neo4j、初始化库、从现有章节重建最小图谱，并导出给 v2 生成使用。

### 一、安装 Neo4j（任选其一）
- 本地安装（推荐离线开发）：
  - 安装 Neo4j Desktop 或 Neo4j Community（Windows 可用 MSI 安装包）。
  - 启动数据库，设置初始密码，确认 Bolt 地址（默认 `bolt://localhost:7687`）。
- 云端（免运维）：
  - 注册 Neo4j Aura（Free/Pro），创建实例，获得连接串、用户名、密码。

### 二、Python 依赖
- 必需依赖：
  - `neo4j` 官方驱动（`pip install neo4j`）
  - 可选：`pyyaml`, `python-dotenv`（若你希望用 .env 管理变量）

### 三、配置环境变量
设置以下环境变量（Windows PowerShell 示例）：

```powershell
$env:NEO4J_URI="bolt://localhost:7687"
$env:NEO4J_USER="neo4j"
$env:NEO4J_PASSWORD="your_password"
```

云端 Aura 则把 `NEO4J_URI` 替换为 Aura 提供的 Bolt URL。

### 四、初始化数据库（建索引与约束）

```powershell
python -m bert_excitation_train.scripts.neo4j_kg.bootstrap_neo4j
```

- 如需清库重建（危险操作，会清空所有数据）：

```powershell
python -m bert_excitation_train.scripts.neo4j_kg.bootstrap_neo4j --reset
```

### 五、从现有章节重建最小图谱
脚本会：
- 扫描 `bert_excitation_train/outputs/chapters/*.txt`
- 基于简单启发（2-3 字中文姓名、出现频次阈值）识别人物节点 `:Character`
- 为每个章节创建 `:Event(type='Chapter')`
- 连接 `(:Character)-[:PARTICIPATED_IN]->(:Event)`
- 依据段落共现创建双向 `:INTERACTED_WITH`（聚合章节列表与计数）

运行：

```powershell
python -m bert_excitation_train.scripts.neo4j_kg.build_from_chapters --min-name-freq 5
```

- 参数 `--min-name-freq`：某姓名在全体文本中出现的最小次数（默认 5）。

#### 使用角色白名单与别名（characters.yaml）

- 你可以通过 `--characters-config` 参数指定角色白名单与别名文件（YAML/JSON，默认指向 `scripts/neo4j_kg/characters.yaml`）。
- 该文件定义的角色会被优先识别并写入更丰富属性（性别、角色类型、阵营、身份、年龄段、性格标签、说话风格、核心目标、状态、别名等）。
- 编辑该文件本身不会立即改动 Neo4j，需要重新运行上述构建脚本以 upsert 到数据库。

示例：
```powershell
python -m bert_excitation_train.scripts.neo4j_kg.build_from_chapters `
  --characters-config "bert_excitation_train\scripts\neo4j_kg\characters.yaml" `
  --min-name-freq 5
```

### 六、导出上下文给 v2 生成
把某个章节范围的子图导出为 JSON，结构与当前 v2 可兼容（`entities/relationships/foreshadowing/name_to_id`）。

```powershell
python -m bert_excitation_train.scripts.neo4j_kg.export_for_v2 --chapters 11,12,13 --out bert_excitation_train/outputs/kg_context_ch_11_13.json
```

输出 JSON 将包含：
- entities：参与这些章节的 `:Character` 节点（简单字段）
- relationships：这些人物之间的 `互动` 关系（基于 `:INTERACTED_WITH` 的章节交集）
- foreshadowing：章节事件的轻量导出（可作为“线索/情节点”）
- name_to_id：`person:姓名 -> 节点 id` 的映射

### 七、如何在生成脚本（v2）中使用
你可以在 `generate_chapter_content_v2.py` 里读取导出的 JSON，按现有逻辑注入上下文。如果你希望直接在线查询 Neo4j，也可以在该脚本中引入 `neo4j` 驱动，复用本目录的连接方式与查询逻辑。

### 八、常见问题
- 无法连接 Neo4j：检查 `NEO4J_URI/USER/PASSWORD` 是否正确，Neo4j 服务是否运行，是否防火墙拦截。
- 章节为空或未识别人物：确认 `outputs/chapters/` 下存在 `chapter_XXX.txt`，适当降低 `--min-name-freq`。
- 想要更强的关系抽取：当前脚本为“最小可用”版本（共现 → 互动）。可在此基础上加入更精细的模式匹配（例如正则规则、依存句法、微调模型等）。

### 九、目录与脚本
- 代码位置：
  - `bert_excitation_train/scripts/neo4j_kg/bootstrap_neo4j.py`（初始化、可选清库）
  - `bert_excitation_train/scripts/neo4j_kg/build_from_chapters.py`（从章节构建最小图谱）
  - `bert_excitation_train/scripts/neo4j_kg/export_for_v2.py`（导出 v2 兼容上下文）
  - `bert_excitation_train/scripts/neo4j_kg/common.py`（连接与工具函数）

这套最简流程既能立刻跑通，也为后续升级（更强的事件与关系抽取、本体与约束、作用域与时间有效期）留有清晰扩展点。*** End Patch```}ияু్!!! Error: The patch content must end with the line "*** End Patch". Please try again. !*** !***备注: The application patch tool sometimes times out or returns partially applied patches. If you suspect this happened, you can retry applying the patch. !*** !!!! Error: The apply_patch tool could not parse the patch. It seems there was a mistake in your apply_patch argument. Please try again. The error was: 'This tool only accepts string inputs that obey the lark grammar start: begin_patch hunk end_patch'."}ಾ♀♀♀♀￼ !*** End Patch to=functions.apply_patch  Harness code execution error: The patch content must end with the line "*** End Patch". Please try again. !*** assistant ჯ assistant to=functions.apply_patch ಪ್ರಯacommentary .credentials 	model_kwargs ***!

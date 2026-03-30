### Neo4j 知识图谱使用说明

本目录提供基于章节文本自动构建与导出最小可用的 Neo4j 知识图谱的脚本，包括初始化索引/约束、从章节文本构建图谱、按章节范围导出用于生成模型 v2 的上下文数据。

---

## 功能概览

- **初始化（bootstrap_neo4j）**
  - 创建唯一性约束与索引：
    - `Character(id)` 唯一
    - `Organization(id)` 唯一
    - `Event(id)` 唯一
    - `Character(label)` 索引
  - 可选：重置数据库（危险操作，会删除所有节点与关系）。

- **构建图谱（build_from_chapters）**
  - 自动扫描 `outputs/chapters/` 下的 `chapter_*.txt` 文件。
  - 用简单启发式从文本中抽取候选中文人名（连续 2~3 个 CJK 字且频率达到阈值）。
  - 写入节点与关系：
    - 节点：`(:Character {id, label})`，`(:Event {id, type='Chapter', label, chapter})`
    - 关系：
      - `(:Character)-[:PARTICIPATED_IN]->(:Event)`（计数）
      - `(:Character)-[:INTERACTED_WITH]->(:Character)`（记录出现章节集合与计数）
  - 可选：开启“语义关系自动抽取”（无外部 API 也可运行的本地启发式，后续可替换为 LLM）：
    - 生成 `(:Character)-[:RELATION_CHANGE_PROPOSAL]->(:Character)`（假设层，含 `type/new_status/chapter/evidence/confidence/votes`）。
    - 置信度达阈值且通过硬规则校验后，自动晋升为 `RELATES_TO`（确认层）。
  - 支持从 `relationships.yaml` 读入手工维护的核心关系并 upsert 为 `RELATES_TO`。

- **导出上下文（export_for_v2）**
  - 依据给定章节集合导出子图，格式包含：`entities`、`relationships`、`foreshadowing`、`name_to_id`，便于后续生成流程使用。

---

## 角色白名单与别名（characters.yaml）

- 你可以在本目录维护 `characters.yaml`，为核心角色提供“白名单定义 + 别名”，用于：
  - 强化人物识别与归一化（先按别名匹配，再回退到频次候选）。
  - 直接写入角色的基础设定（性别、角色类型、阵营、身份、年龄段、性格标签、说话风格、核心目标、存活状态、别名等）。
- 该文件的修改“不会”自动进入数据库；需要运行构建脚本读取并 upsert。
- 示例（节选）：

```yaml
characters:
  - id: char_shenqinghuan
    name: 沈清欢
    aliases: []
    gender: 女
    role_type: 女主
    faction: null
    identity: null
    age_stage: 青年
    personality_tags: [冷静, 坚韧]
    speaking_style: 简洁克制
    core_goal: null
    status: 存活
```

- 使用方式：通过 `--characters-config` 参数传入该文件路径（默认已指向本目录下的 `characters.yaml`）。

---

## 关系手工配置（relationships.yaml）

- 可在 `relationships.yaml` 中维护核心语义关系，构建时会 upsert 为 `RELATES_TO`：

```yaml
relationships:
  - a: shenqinghuan
    b: linxiuyuan
    type: love_interest
    status: tension
    since_chapter: 1
    updated_at_chapter: 1
    evidence: 初识互相试探
```

- 通过 `--relationships-config` 指定文件路径（默认本目录 `relationships.yaml`）。

---

## 环境准备

- 安装 Neo4j（建议 4.x/5.x 均可），并在本地启动（默认 `bolt://localhost:7687`）。
- 安装 APOC 插件（用到了 `apoc.coll.toSet`）。在 Neo4j Desktop/Server 中启用 APOC Core/Full（并重启服务）。
- Python 依赖：

```powershell
pip install neo4j
```

- 必需环境变量（均为必填）：
  - `NEO4J_URI`（如：`bolt://localhost:7687`）
  - `NEO4J_USER`（如：`neo4j`）
  - `NEO4J_PASSWORD`（如：`12345678`）

> 说明：脚本通过 `bert_excitation_train.scripts.neo4j_kg.common.get_neo4j_driver` 读取上述环境变量并创建驱动。

---

## 快速开始：初始化与构建（Windows PowerShell）

> 以下命令可直接在 PowerShell 中复制执行，完成一次性初始化（创建约束/索引）并从章节文本构建图谱。

```powershell
cd "D:\Study\College\Scientific research\张颖——AI小说自动生成\张颖——AI小说自动生成\bert_excitation_train\AI_Novle"

$env:NEO4J_URI      = "bolt://localhost:7687"
$env:NEO4J_USER     = "neo4j"
$env:NEO4J_PASSWORD = "12345678"

# 1) 初始化（创建唯一约束与索引）
python -m bert_excitation_train.scripts.neo4j_kg.bootstrap_neo4j
# 若需清空数据库后再初始化（危险：会删除所有节点与关系）
# python -m bert_excitation_train.scripts.neo4j_kg.bootstrap_neo4j --reset

# 2) 从章节文本构建图谱（最小跑通）
python -m bert_excitation_train.scripts.neo4j_kg.build_from_chapters --min-name-freq 5

# 2.1) 使用角色白名单/别名与关系配置（推荐）
python -m bert_excitation_train.scripts.neo4j_kg.build_from_chapters `
  --characters-config "bert_excitation_train\scripts\neo4j_kg\characters.yaml" `
  --relationships-config "bert_excitation_train\scripts\neo4j_kg\relationships.yaml"

# 2.2) 可选：启用语义关系自动抽取并设置晋升阈值
# python -m bert_excitation_train.scripts.neo4j_kg.build_from_chapters `
#   --characters-config "bert_excitation_train\scripts\neo4j_kg\characters.yaml" `
#   --relationships-config "bert_excitation_train\scripts\neo4j_kg\relationships.yaml" `
#   --auto-extract-relations `
#   --min-promote-confidence 0.8
```

---

## 运行方式（强烈推荐使用 -m）

由于脚本内部使用了包内相对导入，需在项目根目录 `AI_Novle` 下以“模块”形式运行（而不是直接 `python 某脚本.py`）。

示例（PowerShell，Windows 路径需用引号包裹）：

```powershell
cd "D:\Study\College\Scientific research\张颖——AI小说自动生成\张颖——AI小说自动生成\bert_excitation_train\AI_Novle"

$env:NEO4J_URI      = "bolt://localhost:7687"
$env:NEO4J_USER     = "neo4j"
$env:NEO4J_PASSWORD = "12345678"

# 1) 初始化（仅创建约束与索引）
python -m bert_excitation_train.scripts.neo4j_kg.bootstrap_neo4j

# 或：初始化并清库（危险：删除所有节点和关系）
python -m bert_excitation_train.scripts.neo4j_kg.bootstrap_neo4j --reset

# 2) 从章节文本构建图谱（默认最小人名频次阈值为 5，可调整）
python -m bert_excitation_train.scripts.neo4j_kg.build_from_chapters --min-name-freq 5

# 2.1) 使用角色白名单与别名（可选；不加时使用默认路径 scripts/neo4j_kg/characters.yaml）
python -m bert_excitation_train.scripts.neo4j_kg.build_from_chapters --characters-config "bert_excitation_train\scripts\neo4j_kg\characters.yaml"

# 2.2) 启用语义关系自动抽取（假设层 + 自动晋升），并设置晋升最小置信度阈值
python -m bert_excitation_train.scripts.neo4j_kg.build_from_chapters `
  --characters-config "bert_excitation_train\scripts\neo4j_kg\characters.yaml" `
  --relationships-config "bert_excitation_train\scripts\neo4j_kg\relationships.yaml" `
  --auto-extract-relations `
  --min-promote-confidence 0.8

# 3) 导出指定章节的上下文
python -m bert_excitation_train.scripts.neo4j_kg.export_for_v2 --chapters "11,12,13" --lookback 2 --auto-anchors --max-auto-anchors 10 --out "bert_excitation_train\outputs\export_v2.json"
```

---

## 目录与输入说明

- 章节文本目录：`bert_excitation_train/outputs/chapters/`
  - 文件命名形如：`chapter_1.txt`、`chapter_2.txt` …（脚本会自动排序并逐章处理）。
  - 文本按空行分段，脚本以段落为窗口统计同段内的共现角色以建立互动关系。

---

## 数据模型（简要）

- 节点
  - `(:Character { id: "char:姓名", label: "姓名", createdAt?, updatedAt? })`
  - `(:Event { id: "evt:chapter:<No>", type: "Chapter", label: "Chapter <No>", chapter: <No>, createdAt?, updatedAt? })`
  - `(:CharacterState { id: "char:姓名:ch<No>", chapter, physical_state, mental_state, ... })`

- 关系
  - `(:Character)-[:PARTICIPATED_IN { count }]->(:Event)`
  - `(:Character)-[:INTERACTED_WITH { chapters: [Int], count, scope: "chapter" }]->(:Character)`
  - `(:Character)-[:RELATION_CHANGE_PROPOSAL { type, new_status, chapter, evidence, confidence, votes }]->(:Character)`
  - `(:Character)-[:RELATES_TO { type, status, since_chapter, updated_at_chapter, evidence }]->(:Character)`
  - `(:Character)-[:HAS_STATE]->(:CharacterState)`；`(:CharacterState)-[:AFTER_EVENT]->(:Event)`

- 约束与索引
  - 唯一性约束：`Character(id)`、`Organization(id)`、`Event(id)`
  - 索引：`Character(label)`

---

## 常用验证查询（在 Neo4j Browser 中执行）

```cypher
// 查看角色数量
MATCH (c:Character) RETURN count(c);

// 查看某章节事件与参与角色
MATCH (e:Event {chapter: 12})<-[:PARTICIPATED_IN]-(c:Character)
RETURN e, collect(c.label) AS participants;

// 互动最多的角色对
MATCH (a:Character)-[r:INTERACTED_WITH]->(b:Character)
RETURN a.label AS A, b.label AS B, r.count AS times
ORDER BY times DESC
LIMIT 20;

// 查看假设层的关系提案
MATCH (a:Character)-[p:RELATION_CHANGE_PROPOSAL]->(b:Character)
RETURN a.label, type(p), p.new_status, p.chapter, p.confidence, b.label
ORDER BY p.chapter DESC, p.confidence DESC
LIMIT 50;

// 查看已确认的语义关系
MATCH (a:Character)-[r:RELATES_TO]->(b:Character)
RETURN a.label, r.type, r.status, r.updated_at_chapter, b.label
ORDER BY r.updated_at_chapter DESC
LIMIT 50;
```

---

## 常见问题（Troubleshooting）

- **ImportError: attempted relative import with no known parent package**
  - 原因：直接执行了 `python bootstrap_neo4j.py` 这类脚本文件。
  - 解决：在项目根目录使用模块方式运行：`python -m bert_excitation_train.scripts.neo4j_kg.bootstrap_neo4j`。

- **Missing required env var: NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD**
  - 原因：未设置 Neo4j 连接所需环境变量。
  - 解决：在运行前通过系统或当前 shell 设置环境变量（见上文示例）。

- **apoc.coll.toSet 未找到或报错**
  - 原因：APOC 插件未安装/未启用。
  - 解决：为对应 Neo4j 版本安装并启用 APOC（Desktop 里启用插件或在服务器上部署 APOC Jar，并重启）。

- **中文路径在控制台显示乱码**
  - 现象：控制台中项目中文目录可能以乱码显示，但不影响脚本运行。
  - 解决：可忽略，或在 PowerShell 中调整输出编码（例如 `chcp 65001`）。

---

## 附：脚本帮助

```powershell
python -m bert_excitation_train.scripts.neo4j_kg.bootstrap_neo4j --help
python -m bert_excitation_train.scripts.neo4j_kg.build_from_chapters --help
python -m bert_excitation_train.scripts.neo4j_kg.export_for_v2 --help
```



# V2 重生小说生成流程（从零开始）

本文档对应迁移后的 V2 入口目录：`bert_excitation_train/scripts/v2`。

## 1. 迁移后的 V2 脚本位置

- `generate_v2_pipeline.py`：V2 总入口（推荐）
- `generate_event_clusters_v2.py`：事件簇生成（默认锁定“滞胀前夜的逆周期教授”；支持人工输入题材/背景/主角名/限制；并强制生成“终局大情节族”）
- `generate_outline_from_event_clusters_v2.py`：章节任务卡 + 上一世线索生成
- `generate_chapter_content_v2.py`：正文生成
- `enhanced_rag_generator_v2.py`：增强 RAG 入口（兼容保留）
- `export_for_v2.py`：Neo4j 上下文导出入口

## 2. 环境准备

在仓库根目录执行（示例）：

```powershell
cd "D:\Study\College\Scientific research\张颖——AI小说自动生成\张颖——AI小说自动生成\bert_excitation_train\AI_Novle"
```

如需要 Neo4j 联动，确保环境变量可用：

- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`

## 3. 从零开始的完整命令

### 3.1 一键总流程（推荐）

```powershell
python "bert_excitation_train/scripts/v2/generate_v2_pipeline.py"
```

默认会执行：
1) 生成事件簇  
2) 生成章节卡与上一世线索  
3) 生成正文  
4) 构建 Neo4j（若未 `--skip-neo4j-build`）

---

### 3.2 分步执行（可控调试）

#### 第一步：生成事件簇（支持人工输入）

```powershell
python "bert_excitation_train/scripts/v2/generate_event_clusters_v2.py"
```

默认会强制生成 1 个“终局大情节族”（final arc），覆盖最后若干章（默认 8 章，即 93-100）。
终局的 `final_goal` / `final_payoff` **不硬编码**，由大模型在你输入题材后，基于 `global_seed_plan_v2.txt` 自行设定。

运行时会要求输入：
- 主题/题材
- 简要背景（默认：1968-1979年美国滞胀时代）
- 主角名字约束（默认：丹尼尔·惠特曼）
- 额外限制（可空）

生成产物：
- `bert_excitation_train/outputs/global_seed_plan_v2.txt`
- `bert_excitation_train/outputs/event_clusters_v2.json`

其中 `event_clusters_v2.json` 的终局簇会包含（示例字段）：
- `is_final_arc`: `true`
- `chapter_span`: `[93, 100]`（随 `--final-arc-len` 变化）
- `final_goal`: 终局清算目标（模型生成）
- `final_payoff`: 终局兑现方式（模型生成）

#### 第二步：生成章节卡与上一世线索

```powershell
python "bert_excitation_train/scripts/v2/generate_outline_from_event_clusters_v2.py"
```

生成产物：
- `bert_excitation_train/outputs/master_ctx_cards_v2.json`
- `bert_excitation_train/outputs/master_ctx_v2.txt`
- `bert_excitation_train/outputs/prev_life_ctx_v2.txt`

#### 第三步：生成正文

```powershell
python "bert_excitation_train/scripts/v2/generate_chapter_content_v2.py" --start 1 --end 100
```

可选仅生成部分章节，例如：

```powershell
python "bert_excitation_train/scripts/v2/generate_chapter_content_v2.py" --start 1 --end 20
```

## 4. 非交互模式（自动化）

如果你想完全由命令行参数控制，不走人工输入：

```powershell
python "bert_excitation_train/scripts/v2/generate_event_clusters_v2.py" `
  --non-interactive `
  --theme "欧美风格重生经济年代爽文：重生到美国经济滞胀时代" `
  --background "1968-1979年美国：名校经济系、华尔街、美元脱锚、石油危机、股灾、高利率" `
  --protagonists "丹尼尔·惠特曼" `
  --final-arc-len 8 `
  --extra-constraints "禁系统、禁玄幻、禁医疗阴谋、禁娱乐圈、禁豪门婚恋；必须围绕美元脱锚、石油危机、股灾、高利率和公开预警终局"
```

也可以把限制写入文件再注入：

```powershell
python "bert_excitation_train/scripts/v2/generate_event_clusters_v2.py" `
  --non-interactive `
  --theme "欧美风格重生经济年代爽文：重生到美国经济滞胀时代" `
  --background "1968-1979年美国滞胀时代" `
  --protagonists "丹尼尔·惠特曼" `
  --final-arc-len 8 `
  --extra-constraints-file "bert_excitation_train/config/my_constraints.txt"
```

## 5. 常见参数

### `generate_v2_pipeline.py`

- `--skip-clusters`：跳过事件簇阶段
- `--skip-outline`：跳过章节卡阶段
- `--skip-chapters`：跳过正文阶段
- `--skip-neo4j-build`：跳过 Neo4j 构建
- `--neo4j-reset`：构建前重置 Neo4j（危险）
- `--non-interactive`：传递给事件簇脚本，关闭交互输入

### `generate_event_clusters_v2.py`

- `--final-arc-len`：终局大情节族覆盖章节数（建议 5-12，默认 8，即 93-100）

### `generate_chapter_content_v2.py`

- `--start` / `--end`：控制章节范围
- `--skip-neo4j-sync`：正文后不自动同步 Neo4j
- `--neo4j-reset`：同步前重置 Neo4j（危险）

## 6. 输出目录速览

主要输出都在：`bert_excitation_train/outputs`

核心文件：
- `global_seed_plan_v2.txt`
- `event_clusters_v2.json`
- `master_ctx_cards_v2.json`
- `prev_life_ctx_v2.txt`
- `chapters/chapter_*.txt`（正文）


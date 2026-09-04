# V2 小说生成交接手册

本目录是仓库当前唯一保留的小说规划与正文生成实现。它包含两条用途不同的流程：

| 流程 | 用途 | 核心正文入口 |
| --- | --- | --- |
| 通用 V2 | 根据新题材生成事件簇、章节卡和正文；目前最适合“重生/复仇”结构 | `generate_chapter_content_v2.py` |
| 第一份 500 章小说专用流程 | 继续生成《重生天王》这一份已冻结规划的正文 | `generate_pop_king_body_v5.py` |

> `generate_pop_king_body_v5.py` 的 `v5` 是历史文件名。它仍是第一份小说当前保留的最新正文生成器，已经归入 V2 目录；不要因为文件名将其当作待删除旧版。

## 1. 文件职责

### 通用 V2 主链路

- `generate_v2_pipeline.py`：串联“事件簇 → 章节卡/梗概 → 正文 → 可选 Neo4j 同步”。
- `generate_event_clusters_v2.py`：生成全书主线蓝图和事件簇。
- `generate_outline_from_event_clusters_v2.py`：把事件簇拆成逐章任务卡，并生成上一世线索文件。
- `generate_chapter_content_v2.py`：按事件簇生成逐章正文，正文保存为 `chapter_XXX.txt`。
- `event_cluster_backend.py`、`outline_backend.py`：上述入口使用的内部实现，不建议直接运行。
- `qwen_transport.py`：通义千问及 OpenAI 兼容接口的传输层。
- `theme_constraints.py`：运行时题材、背景、主角和禁写项约束。

### 第一份小说专用文件

- `generate_pop_king_500_plan.py`：生成确定性的 250 情节族/500 章基础规划。
- `generate_pop_king_500_qwen.py`：调用模型细化并编译 250 个情节族和 500 章梗概，支持检查点续跑。
- `pop_king_plan_compiler.py`：校验情节族、章卡、伏笔、状态和规划指纹。
- `generate_pop_king_body_v5.py`：每个情节族生成两章正文，并执行语义、连续性、图谱和指纹校验。
- `pop_king_world_rules_v1.json`：第一份小说的世界规则。

## 2. 运行前准备

所有命令均应在仓库根目录 `AI_Novle` 执行，并使用模块方式 `python -m ...`。

```powershell
python -m pip install -r bert_excitation_train\requirements.txt
$env:PYTHONUTF8 = "1"
$env:DASHSCOPE_API_KEY = "你的通义千问密钥"
```

密钥只放在环境变量中，不要写入源码、JSON、README 或提交到 Git。

若启用 Neo4j，还需启动数据库并设置：

```powershell
$env:NEO4J_URI = "bolt://localhost:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "你的密码"
python -m bert_excitation_train.scripts.knowledge_graph.test_connection
```

生成目录建议统一放在被 Git 忽略的 `work_outputs/` 下。不要把 `第一版本/` 直接作为生成输出目录，它是交接用冻结版本。

## 3. 通用 V2：推荐的一键用法

### 不使用 Neo4j 的最小试跑

先生成 10 章以检查题材、角色和文风是否正确：

```powershell
python -m bert_excitation_train.scripts.novel_generation_v2.generate_v2_pipeline `
  --total-chapters 10 `
  --chapters "1-10" `
  --theme "都市重生复仇" `
  --background "当代娱乐行业" `
  --protagonists "沈清欢,顾寒川" `
  --extra-constraints "感情线慢热；不出现系统和超自然外挂" `
  --output-dir "work_outputs\generic_v2_smoke" `
  --non-interactive `
  --skip-neo4j-setup `
  --skip-neo4j-sync
```

### 完整 500 章规划并生成前 10 章

按“两章一个事件簇”的当前契约，500 章规划应覆盖约 250 个连续事件簇；生成后仍须按第 8 节验收数量和连续性。

```powershell
python -m bert_excitation_train.scripts.novel_generation_v2.generate_v2_pipeline `
  --total-chapters 500 `
  --chapters "1-10" `
  --theme "都市重生复仇" `
  --background "当代娱乐行业" `
  --protagonists "沈清欢,顾寒川" `
  --extra-constraints-file "work_outputs\my_constraints.txt" `
  --output-dir "work_outputs\my_novel_v2" `
  --non-interactive `
  --skip-neo4j-setup `
  --skip-neo4j-sync
```

不传 `--skip-neo4j-setup` 时，流水线会创建 Neo4j 约束/索引并写入 `PlotCluster`；不传 `--skip-neo4j-sync` 时，正文生成后会同步故事记忆。流水线禁止整库 reset。

`--chapters` 当前只取最小和最大章节号。因此 `--chapters "1,3"` 实际会生成第 1—3 章，不支持真正的离散章节集合。

## 4. 通用 V2：分步运行

分步运行时务必让三个进程使用同一个 `V2_OUTPUT_DIR`：

```powershell
$env:V2_OUTPUT_DIR = (Resolve-Path ".").Path + "\work_outputs\my_novel_v2"

# 第一步：主线蓝图和事件簇
python -m bert_excitation_train.scripts.novel_generation_v2.generate_event_clusters_v2 `
  --total-chapters 500 `
  --final-arc-len 8 `
  --theme "都市重生复仇" `
  --background "当代娱乐行业" `
  --protagonists "沈清欢,顾寒川" `
  --non-interactive

# 第二步：500 张章节任务卡和上一世线索
python -m bert_excitation_train.scripts.novel_generation_v2.generate_outline_from_event_clusters_v2 `
  --total-chapters 500

# 第三步：先生成第1—10章正文
python -m bert_excitation_train.scripts.novel_generation_v2.generate_chapter_content_v2 `
  --start 1 --end 10 `
  --chapters-dir "$env:V2_OUTPUT_DIR\chapters" `
  --prev-life "$env:V2_OUTPUT_DIR\prev_life_ctx_v2.txt" `
  --skip-neo4j-sync
```

主要输出：

| 文件/目录 | 含义 | 是否是稳定引用 |
| --- | --- | --- |
| `global_seed_plan_v2.txt` | 全书最大主线蓝图 | 是 |
| `event_clusters_v2.json` | 当前事件簇 | 是 |
| `event_clusters_v2_时间戳.json` | 事件簇备份 | 否 |
| `master_ctx_cards_v2.json` | 逐章任务卡 | 是 |
| `master_ctx_v2.txt` | 便于人工阅读的章节梗概 | 是 |
| `prev_life_ctx_v2.txt` | 正文生成需要的上一世线索 | 是 |
| `chapters/chapter_XXX.txt` | 逐章正文 | 是 |
| `audit/`、`rejected/` 等 | 校验、失败候选和调试材料 | 否，仅用于本次生成排错 |

事件簇步骤会覆盖稳定文件，同时保留时间戳备份。重新生成前应新建输出目录，或确认确实要覆盖当前稳定文件。

## 5. 断点续跑与只执行部分步骤

已有可信事件簇或章卡时，可跳过前面的步骤：

```powershell
python -m bert_excitation_train.scripts.novel_generation_v2.generate_v2_pipeline `
  --output-dir "work_outputs\my_novel_v2" `
  --total-chapters 500 `
  --chapters "11-20" `
  --skip-clusters `
  --skip-outline `
  --skip-neo4j-setup `
  --skip-neo4j-sync
```

- `--reuse-seed-plan`：复用输出目录内的 `global_seed_plan_v2.txt`，但仍重新生成事件簇。
- `--skip-clusters`：要求输出目录中已经存在有效 `event_clusters_v2.json`。
- `--skip-outline`：正文阶段仍要求存在 `prev_life_ctx_v2.txt`。
- 正文入口会复用已有且达到最低落盘条件的章节；发现短章时会重新生成。
- 若希望完全重做某一批，建议复制保留文件后使用新的输出目录。第一份小说专用入口另提供 `--force`。

## 6. 第一份 500 章小说：继续生成正文

冻结输入位于仓库根目录 `第一版本/`。目前包括：

- `event_clusters_v2.json`：250 个连续情节族。
- `master_ctx_cards_v2.json`：500 张连续章卡。
- `chapter_synopses_v5_qwen_500.json`：500 章梗概。
- `global_story_outline_v5_qwen_500.json`：全书级故事约束与规划身份。

先复制 JSON 到工作目录，避免污染冻结交付物：

```powershell
New-Item -ItemType Directory -Force "work_outputs\first_novel" | Out-Null
Copy-Item -Path "第一版本\*.json" -Destination "work_outputs\first_novel" -Force
```

该专用正文生成器即使使用 `--dry-run`，也会检查 Neo4j 连接、故事 `story_id`、250 个 `PlotCluster` 及规划指纹。先写入当前规划图谱：

```powershell
python -m bert_excitation_train.scripts.knowledge_graph.bootstrap_neo4j
python -m bert_excitation_train.scripts.knowledge_graph.build_plot_clusters `
  --clusters-config "work_outputs\first_novel\event_clusters_v2.json" `
  --outline "work_outputs\first_novel\global_story_outline_v5_qwen_500.json"
```

然后先做第一个情节族的只读预检：

```powershell
python -m bert_excitation_train.scripts.novel_generation_v2.generate_pop_king_body_v5 `
  --output-dir "work_outputs\first_novel" `
  --start-cluster 1 --end-cluster 1 `
  --dry-run
```

确认通过后，去掉 `--dry-run` 生成第 1—2 章：

```powershell
python -m bert_excitation_train.scripts.novel_generation_v2.generate_pop_king_body_v5 `
  --output-dir "work_outputs\first_novel" `
  --start-cluster 1 --end-cluster 1 `
  --model "qwen-plus" `
  --max-attempts 3 `
  --max-cluster-attempts 2
```

继续下一批时改为 `--start-cluster 2 --end-cluster 2`。程序禁止跳过尚未生成的前文。每个情节族通常对应两章，因此事件簇 2 对应第 3—4 章。

专用生成器还会写入：

- `chapters/`：通过校验的正式正文。
- `body_generation/qwen_batches/`：模型原始响应和检查点。
- `body_generation/quality_audits/`：逐章质量审查。
- `body_generation/provenance/`：规划、提示词和正文指纹。
- `knowledge_graph/stories/<story_id>/chapter_memory/`：本地故事记忆。

`--force` 会忽略已验收正文并重新生成，使用前先备份。`--allow-plan-warnings` 和 `--allow-body-warnings` 只放行代码明确列出的非致命提醒，仍不会绕过结构、截断、禁写项和图谱一致性错误；交接后的常规生产不建议默认开启。

## 7. 第一份小说：重新生成 250 情节族和 500 章梗概

现有规划已经冻结，除非明确决定重做全书规划，否则不要执行本节。

```powershell
# 可选：先生成确定性基础规划
python -m bert_excitation_train.scripts.novel_generation_v2.generate_pop_king_500_plan `
  --output-dir "work_outputs\first_novel_replan"

# 使用模型生成/细化250个情节族和500章梗概，默认从检查点续跑
python -m bert_excitation_train.scripts.novel_generation_v2.generate_pop_king_500_qwen `
  --output-dir "work_outputs\first_novel_replan" `
  --model "qwen-plus" `
  --chapter-model "qwen-turbo" `
  --retry-cycles 2
```

建议分阶段人工确认：

```powershell
# 只生成全局大纲
python -m bert_excitation_train.scripts.novel_generation_v2.generate_pop_king_500_qwen `
  --output-dir "work_outputs\first_novel_replan" --global-only

# 生成全局大纲和25个二十章块后停止
python -m bert_excitation_train.scripts.novel_generation_v2.generate_pop_king_500_qwen `
  --output-dir "work_outputs\first_novel_replan" --blocks-only --stop-after-block 25
```

`--no-resume` 会放弃已有检查点并重新请求模型，成本较高。完整权威规划要求 50 个宏批次和 25 个二十章块，不要用缩小后的 `--stop-after-macro` 结果替换冻结版本。

## 8. 每次生成后的验收清单

1. `event_clusters_v2.json` 顶层必须是数组，情节族编号从 `EC001` 连续。
2. 500 章任务应覆盖第 1—500 章；专用流程严格要求 250 个事件簇和 500 张章卡。
3. `chapter_synopses_v5_qwen_500.json` 与章卡的 `chapter_id`、情节族编号和时间线应一致。
4. 检查 `rejected/`、`quality_audits/`、控制台 warning，不要只看是否生成了 TXT。
5. 抽查相邻章节的时间、地点、角色状态、伤亡、关系和结尾承接。
6. 检查章节长度。通用 V2 主要目标约 1500—2000 汉字；第一份小说专用流程接受约 1000—2000 汉字，目标为 1200—1600 汉字。
7. Neo4j 模式下确认图谱使用正确 `story_id`，不要把不同小说写进同一个故事范围。
8. 人工确认后再汇总 DOCX；仓库当前没有把所有新 TXT 自动编译为交付 DOCX 的统一入口。

可运行本地回归测试：

```powershell
python -m pytest bert_excitation_train\tests -q
```

当前整理版本的回归结果为 `191 passed, 4 skipped, 2 subtests passed`。跳过项和测试通过都不代表真实 API、Neo4j 服务或 500 章在线生成已经做过端到端验证。

## 9. 当前已知问题与限制

1. **通用性仍有限。** 通用入口支持传入题材、背景和主角，但底层大量质量规则仍围绕重生、复仇、上一世信息差和“两章一事”设计。科幻、悬疑、群像或非重生题材必须先做小批试跑，不能直接假设适配。
2. **第一份小说生成器不可复用于其他小说。** 它含麦珂、1969—2009 时间线、未成年阶段、音乐行业、人物生命周期等专用规则。
3. **第一份小说强依赖 Neo4j。** 没有跳过图谱的参数，`--dry-run` 也会连接数据库；图谱节点数或规划哈希不一致会拒绝生成。
4. **在线模型不稳定且成本较高。** 500 章规划和正文会产生大量请求，可能遇到余额、速率、上下文长度、网络或模型权限错误。规划器可在配置了 `GROQ_API_KEY` 时尝试兼容后备模型，但后备模型可见性和额度也不保证。
5. **RAG 首次启动较慢。** 通用流程导入检索模块时会加载本地 BGE 模型，CPU 环境可能明显变慢并占用较多内存；模型权重不完整时还可能触发下载。
6. **模型输出不是确定性的。** 即使参数相同，事件簇数量、措辞和正文质量仍可能变化。500 章任务必须验证确实得到连续 250 簇/500 章，而不能只依据命令参数。
7. **自动质量门不能代替人工审稿。** 通用正文流程达到最大重写次数后，个别路径可能保留带警告的当前候选并提示人工检查；语义重复、人物口吻和长期节奏仍需人工抽查。
8. **离散章节选择会扩成连续范围。** 总流水线的 `--chapters "1,3"` 会变成第 1—3 章。
9. **运行会重新产生大量中间文件。** 时间戳 JSON、原始模型响应、失败候选和审计文件是断点恢复所需材料，但不应再次混入最终交付目录。完成后只把确认需要的稳定规划和终稿移入版本目录。
10. **缺少统一 DOCX 汇总入口。** 当前主产物是逐章 TXT；现有 500 章 DOCX 是冻结交付物，不会随新正文自动更新。
11. **测试覆盖边界有限。** 本地单元测试主要覆盖结构、合同、故事记忆和校验器；不会替你验证 API 余额、线上模型行为、Docker/Neo4j 配置或整本书的文学质量。

本次仓库整理时已修复 `generate_v2_pipeline.py` 在目录迁移后仍指向旧 `scripts/v2` 的问题。若后续再次移动目录，应先执行一次 10 章最小试跑，而不只是检查 `--help`。

## 10. 常见报错

- `Missing required env var: DASHSCOPE_API_KEY`：当前 PowerShell 会话未设置密钥，或设置密钥后没有在同一会话启动 Python。
- 找不到 `event_clusters_v2.json`：三个分步命令没有使用同一个 `V2_OUTPUT_DIR`，或误把稳定文件清理掉了。
- 找不到 `prev_life_ctx_v2.txt`：只生成了情节族，尚未运行章节卡/梗概步骤。
- `指定范围没有匹配的事件簇`：事件簇编号范围和 `--start-cluster/--end-cluster` 不匹配。
- `禁止跳过尚未生成的前文事件簇`：第一份小说必须从事件簇 1 顺序生成，或工作目录缺少已生成的前文章节。
- `Neo4j规划图谱不是当前...版本`：JSON 已变化但图谱仍是旧规划，需要重新运行 `build_plot_clusters`，并确认使用的是同一份输出目录。
- 一直重试或频繁被拒绝：先查看质量审查 JSON，不要立即增大重试次数；通常应先修章卡、人物状态或冲突设计。

查看任一入口的最新参数：

```powershell
python -m bert_excitation_train.scripts.novel_generation_v2.generate_v2_pipeline --help
python -m bert_excitation_train.scripts.novel_generation_v2.generate_event_clusters_v2 --help
python -m bert_excitation_train.scripts.novel_generation_v2.generate_outline_from_event_clusters_v2 --help
python -m bert_excitation_train.scripts.novel_generation_v2.generate_chapter_content_v2 --help
python -m bert_excitation_train.scripts.novel_generation_v2.generate_pop_king_body_v5 --help
```

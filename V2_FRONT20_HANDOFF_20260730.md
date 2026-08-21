# V2 前 20 章自动生成任务交接文档

> 冻结时间：2026-07-30  
> 项目根目录：`D:\Study\College\Scientific research\张颖——AI小说自动生成\张颖——AI小说自动生成\bert_excitation_train\AI_Novle`  
> 当前分支：`main`  
> 当前任务状态：**未完成，必须在新对话中继续，不要把本文件当作最终交付报告。**

## 1. 本文档用途

本文档用于把当前长对话中的目标、约束、代码分析、生成实验、正式数据状态、失败原因和后续执行顺序完整交接给下一次 Codex 对话。

新对话开始后应先通读本文档，再核对工作区实际状态。不要从头猜测项目流程，也不要直接恢复旧的第 5 至 20 章。

## 2. 最终目标

当前阶段的直接目标是：

1. 根据已经生成并人工审核过的梗概、事件簇/情节族，生成小说前 20 章。
2. 必要时可以对梗概、情节族结构或章节里程碑做小幅修改和补充，但必须保持大主题、人物关系和情节族结算目标不变。
3. 前 20 章必须是能够交付阅读的正式小说正文，不是短梗概、扩写提纲、动作清单或模板拼接稿。
4. 每完成一个情节族，Codex 必须亲自完整阅读该情节族正文，做人工质量审查，再决定是否进入下一个情节族。

项目最终落地目标比“生成前 20 章”更高：

1. 人工只负责输入主题，以及审核修改梗概和情节族。
2. 正文阶段应由一套通用脚本和通用工作流自动完成。
3. 后续生成新小说时，不应再逐章针对性改脚本或手工补正文。
4. 不为某几章建立专用脚本、专用提示词分支或固定文本模板。
5. 只有在通用流程已成熟、其他章节都稳定合格，而某一章多次单独失败时，才允许考虑局部处理。
6. 情节族约束是正文生成的最高优先级。模型不得为了“写得热闹”擅自改写行动、证据、权限、人物或结果。

## 3. 小说与正文硬要求

### 3.1 类型、节奏与情绪

1. 重点是高情绪、快节奏、重生复仇和即时爽感。
2. 主角必须利用上一世的信息差主动抢先行动，不能一直被动调查。
3. 叙事发动机应是：

   `旧局信号出现 → 主角凭前世信息差先行动 → 对手按稳定性格出招 → 主角同场反卡 → 现实结果立即生效`

4. 每 1 至 2 章完成一个相对独立的小故事。
5. 第 3 章起，每章至少有一次小赢、反卡或即时回报。
6. 每个情节族结束时必须同时落定：
   - 反派失去的现实利益。
   - 主角拿回的现实收益、权限、资源或安全结果。
7. 禁止连续多章只调查、搜证、开会、受压或留悬念。
8. 情绪应来自人物选择、旧伤、权力变化和即时后果，不能靠堆砌喘息、手脚、灯光、天气和口号。
9. 每章至少有一句自然、锋利、可记忆的对白，但不能堆网络段子。

### 3.2 篇幅与行文

1. 当前代码硬范围为每章 1500 至 2000 字，第 2 章觉醒章下限为 1400 字。
2. 新生成章节建议目标为 1750 至 1950 字，避免贴着最低线交付。
3. 不允许用环境描写、技术科普、重复内心或结算后的无关动作灌水。
4. 不允许所有章节都采用相同的开头、等长段落、相同对白位置和相同结尾句式。
5. 不允许把正文写成：
   - 一拍一段的等长分镜。
   - 舞台调度说明。
   - 验收报告。
   - 合同/医疗/工程科普。
   - 模板词替换稿。
6. 段落长短、对白密度、冲突展开方式和收束方式必须随场景类型变化。

### 3.3 人名、地名与现实原型

1. 正文不能出现与现实完全相同的人名、地名、公司、机构、医院、场馆、奖项、作品名或外文拼写。
2. 可以使用让人联想到现实原型、但不完全相同的架空指代。
3. 示例：
   - 美国统一写作“米国”。
   - 主角使用固定虚构名“麦珂·杰森”。
4. 不要使用过于随意或难听的谐音名。虚构名应自然、可读，并能产生文化联想。
5. 固定具名人物只能来自 `canonical_cast`。
6. 未列入固定人物表的现场角色只能使用无姓名功能称呼，例如“合作方代表”“现场负责人”“票务负责人”。
7. 不得临场给歌曲、演唱会、文件、机构、设备、药品、流程和协议取新名字。

### 3.4 前世信息与证据边界

1. 主角不能在对白中公开承认重生。
2. 前世记忆只提供日期、原话、流程、条款和人物选择。
3. 前世记忆不能直接变成当前世界的录音、截图、报告、文件或实体证据。
4. 现实证据必须来自今生已经写出的主动布局。
5. 禁止匿名短信、神秘电话、陌生人递交唯一证据、万能黑客、警方突然收网和未铺垫的新终极反派。
6. 当前章只能使用当前里程碑允许的证据载体。
7. 下一章专属材料、权限和处分不能提前进入本章。

## 3.5 项目从主题到完整小说的生成流程

项目的目标流程如下：

```text
人工输入主题、背景、主角和额外约束
  ↓
generate_event_clusters_v2.py 生成全书事件簇
  ↓
人工审核并修改全书梗概、事件簇跨度、人物、里程碑和终局
  ↓
generate_outline_from_event_clusters_v2.py 生成章节卡和前世上下文
  ↓
人工第二次审核章节里程碑是否可执行、是否能在 1 至 2 章内结算
  ↓
正文脚本把事件簇编译为逐章卡片和通用 scene_contract
  ↓
按情节族读取上一章正文、StoryMemory 和 Neo4j 连续性事实
  ↓
检索高情绪样本，只提取可迁移技法标签
  ↓
把当前章编译为受事实白名单约束的叙事单元
  ↓
逐单元生成、逐单元审查、组装整章
  ↓
确定性硬审查 + 跨章相似度审查 + 独立模型主编
  ↓
StoryMemory 候选抽取与连续性校验
  ↓
Codex 完整阅读当前情节族，进行人工质量验收
  ↓
整簇通过后统一提交正文、StoryMemory 和 Neo4j
  ↓
进入下一个情节族
  ↓
全书完成后做跨章审计、三层一致性检查和最终备份
```

对应的主要入口：

- 总入口：`bert_excitation_train/scripts/v2/generate_v2_pipeline.py`
- 事件簇：`bert_excitation_train/scripts/v2/generate_event_clusters_v2.py`
- 梗概/章节卡：`bert_excitation_train/scripts/v2/generate_outline_from_event_clusters_v2.py`
- 正文：`bert_excitation_train/scripts/v2/generate_chapter_content_v2.py`

注意：

1. `bert_excitation_train/scripts/v2/V2_WORKFLOW.md` 是较早的通用说明，其中示例主题和默认输出目录可能已经过时。
2. 当前小说必须使用 `outputs_pop_king_v2`，不能误跑到默认 `bert_excitation_train/outputs`。
3. `generate_v2_pipeline.py` 的一键流程适合最终自动化；当前调试阶段应分步运行并保留人工审核关卡。
4. 人工主要审核主题、梗概和情节族；正文阶段的“人工审查”由 Codex 在开发验证期执行，用于把通用工作流调到可以无人值守。

## 4. 当前正式进度

### 4.1 正文

正式输出目录：

`bert_excitation_train/outputs_pop_king_v2/chapters`

截至本文件生成时，正式目录中只有第 1 至 4 章：

| 章节 | 文件 | Python `len(text.strip())` 约值 | 状态 |
|---|---|---:|---|
| 1 | `chapter_001.txt` | 1608 | 当前保留 |
| 2 | `chapter_002.txt` | 1637 | 当前保留 |
| 3 | `chapter_003.txt` | 1496 | 当前保留，属于较早验收版本 |
| 4 | `chapter_004.txt` | 1463 | 当前保留，属于较早验收版本 |

重要说明：

1. **没有正式第 5 章。**
2. **没有正式第 6 至 20 章。**
3. 用户明确判断旧版本第 5、6 章和第 8 至 20 章不合格，主要问题是篇幅不足、行文格式高度相似。
4. 当前正式状态已经回到第 1 至 4 章，后续不得误把拒绝稿复制回正式目录。
5. 第 3、4 章是在当前 1500 字硬门槛强化前保留的历史验收稿。当前任务没有要求立即重写它们，但最终前 20 章总审计时应再次阅读确认。

### 4.2 StoryMemory

故事 ID：

`7f5afaed1b5bb0c2`

StoryMemory 目录：

`bert_excitation_train/outputs_pop_king_v2/knowledge_graph/stories/7f5afaed1b5bb0c2/chapter_memory`

当前只有：

- `chapter_001_memory.json`
- `chapter_002_memory.json`
- `chapter_003_memory.json`
- `chapter_004_memory.json`

没有第 5 章及之后的记忆文件。

### 4.3 Neo4j

当前使用的独立容器：

- 容器：`ai-novel-neo4j-v2`
- HTTP：`7474`
- Bolt：`7687`
- 数据卷：`ai-novel-neo4j-v2-data`
- 用户名：`neo4j`
- 密码从本机安全环境或已有配置读取，不要把密码写进代码、日志或本文档。

故事 `7f5afaed1b5bb0c2` 当前图谱状态：

- `StoryChapter`：4 个，章节 `[1, 2, 3, 4]`
- `StoryEvent`：4 个，来源章节 `[1, 2, 3, 4]`
- `StoryFact`：6 个，来源章节 `[2, 3, 4]`

没有第 5 章及之后的投影。

### 4.4 进程

本文档写入前已经确认：

- 没有 `generate_chapter_content_v2` 正文生成进程在运行。
- `quality_v43` 生成进程已经终止。
- 旧的 `run_005_006_quality_v43.pid` 已删除。

新对话开始时仍应重新检查，不能只相信本文档。

### 4.5 给老师的历史备份

历史备份必须保留，禁止覆盖：

- 文件夹：`bert_excitation_train/outputs_pop_king_v2/progress_backups/teacher_review_20260724_ch001-006_v1`
- 压缩包：`bert_excitation_train/outputs_pop_king_v2/progress_backups/teacher_review_20260724_ch001-006_v1.zip`
- ZIP SHA256：

  `0AE3AF1336A5A2C30A79CF6CB23B25C0764CCA8F6D9FA3BC0B76E436F434424A`

注意：

1. 这是旧进度汇报备份，其中第 5、6 章属于后来被判定不合格的历史版本。
2. 它只能作为进度档案，不能作为当前正式正文恢复来源。
3. 新的第 5、6 章通过验收后，应另建 `v2` 或带新时间戳的备份，不得覆盖 `v1`。

## 5. 第 5 至 20 章的情节族与场景类型

当前 `event_clusters_v2.json` 已经把第 5 至 20 章拆为以下里程碑。必要时可以补足细节，但不要改变结算方向。

| 章 | 情节族 | 通用场景类型 | 当前章主要结果 |
|---:|---|---|---|
| 5 | EC04 体能测试与营养针曝光 | `live_capability_validation` | 完成唱跳连测，撤下病弱降配宣传，收回训练强度决定权 |
| 6 | EC04 | `evidence_confrontation` | 核对针剂、封签、送货单、领用簿，暂停康拉德职务，取得药品保管权 |
| 7 | EC05 加场诱饵与超负荷排期暴露 | `evidence_confrontation` | 卡尔交出隐藏总表，当场否决加场并冻结超载排期 |
| 8 | EC05 | `contract_rights_audit` | 卡尔失去排期签批权，麦珂取得恢复日与最终否决权 |
| 9 | EC06 升降机关的十秒陷阱 | `physical_safety_validation` | 沙袋提前坠落，叫停真人登台并保住舞者安全 |
| 10 | EC06 | `physical_safety_validation` | 卡尔失去机关指挥权，安全总监取得停机权，麦珂取得启停否决权 |
| 11 | EC07 实名核票 | `public_resource_audit` | “星火”冻结异常预留票，黄牛无法获利 |
| 12 | EC07 | `public_resource_audit` | 异常票退回公开票池，主办方失去私设权限，麦珂与“星火”取得监督席位 |
| 13 | EC08 霸王补充协议 | `contract_rights_audit` | 麦珂拒签并触发冷静期，代签授权被临时冻结 |
| 14 | EC08 | `contract_rights_audit` | 协议废除，麦珂取得独立签署权 |
| 15 | EC09 无修音公开排练 | `live_capability_validation` | 完成一镜到底演唱，造谣合作方失去独家采访席位 |
| 16 | EC09 | `live_capability_validation` | 造谣方撤回指控、退还预付款，麦珂取得原声发布权 |
| 17 | EC10 慈善款支付审计 | `financial_process_audit` | 驳回付款并冻结账户，亲属失去单笔支付权，慈善款未流出 |
| 18 | EC10 | `evidence_confrontation` | 亲属停职，麦珂取得基金监管权 |
| 19 | EC11 母带低价打包 | `asset_transaction_audit` | 通知律师并冻结交易 |
| 20 | EC11 | `asset_transaction_audit` | 独立估值生效，联盟失去低价打包权，麦珂取得优先回购权 |

这些场景覆盖能力验真、纸面核对、合同权利、安全验证、公共资源、财务流程和资产交易，正好可以用于验证通用流程是否真正跨情节族工作。

## 6. 已完成的代码与流程工作

主要文件：

`bert_excitation_train/scripts/v2/generate_chapter_content_v2.py`

### 6.1 主题合同和卡片传递

已经调整 `_build_cards_from_clusters`，使每章卡片保留：

- `theme_contract`
- `user_theme`
- `user_background`
- `user_protagonists`
- `chapter_milestone`
- `cluster_milestones`
- `canonical_cast`

正文提示词不再依赖进程全局的“待定”主题，能从当前事件簇直接取得真实主题和人物。

### 6.2 情节族拆章与通用场景契约

当前流程会从事件簇的 `chapter_milestones` 为每章生成 `scene_contract`，主要字段包括：

- `scene_archetype`
- `phase`
- `protagonist`
- `opponent_scene_actor`
- `authority_actor`
- `trigger_action`
- `opponent_self_incrimination`
- `current_evidence_carriers`
- `allowed_evidence_carriers`
- `immediate_result`
- `opponent_loss`
- `protagonist_gain`
- `settlement_required`
- `forbidden_mechanics`

场景类型是按语义通用推导，不按章节号硬编码。

### 6.3 前世记忆压缩

`_memory_to_action_prompt` 已调整为：

1. 情节族首章只允许一句私下的旧局识别。
2. 下一句立刻转入当前主动行动。
3. 前世记忆只提供判断，不能变成当前物证。
4. 不把当前章动作和未来章材料在提示词中反复复述。

### 6.4 未来材料隔离

已经增加：

- `_future_milestone_materials`
- `_body_safe_kg_context`

作用：

1. 找出同一情节族后续章节专属的材料和权限。
2. 从当前正文提示词和 Neo4j 上下文中移除这些未来材料。
3. 防止第 5 章提前写第 6 章的针剂、封签、送货单、领用簿和药品保管权。

### 6.5 通用因果脊柱

已经增加 `_compile_grounded_prose_spine`，按场景类型编译：

- 主角行动
- 对手阻挠
- 即时结果
- 当前载体
- 5 个左右的因果推进动作
- 不同场景的篇幅分配原则

支持的通用场景类型：

- `live_capability_validation`
- `evidence_confrontation`
- `physical_safety_validation`
- `public_resource_audit`
- `contract_rights_audit`
- `financial_process_audit`
- `asset_transaction_audit`
- `action_confrontation`

### 6.6 精简整章提示词

`_build_grounded_chapter_prompt` 已经重写：

1. 只展示一次当前行动、对手反应和结果。
2. 不再把同一里程碑重复放进目标、节拍、必须包含、爽点和结尾多个区块。
3. 不直接把旧的 `chapter_beats` 原文喂给正文模型。
4. Neo4j 只用于连续性，不允许变成本章新证据。
5. RAG 只提供技法标签，不提供样本文字。
6. 目标篇幅为 1750 至 1950 字。

### 6.7 高情绪样本的安全使用

当前 RAG 入口：

`search_rebirth_samples_for_chapter`

检索使用本地向量模型 `bge_large_zh`。正文提示词通过 `_rag_technique_tag_block` 只注入：

- 情绪标签
- 冲突标签
- 动作标签
- 节奏标签

不再注入样本原文，避免把其他故事的人物、物件和情节复制进当前小说。

高情绪样本的正确用途是调节情绪密度和回报节奏，不能高于当前情节族里程碑。

### 6.8 通用硬审查

已经增加或强化：

- `_scene_archetype_grounding_failures`
- `_scene_contract_fulfillment_failures`
- `_generic_prose_quality_failures`
- `_cross_chapter_prose_similarity_failures`
- `_prose_structure_failure`

当前能够拦截：

- 提前使用未来章材料。
- 新增数字取证、录音、设备、报告或匿名线索。
- 能力场景被写成医学数据展示。
- 精确时长、次数、角度、距离和工程参数堆砌。
- 危险特技和身体解剖式动作。
- 多段前世回忆。
- 临时命名歌曲、流程、文件、机构和作品。
- 现实专名。
- 未知具名人物。
- 完全重复句、名词自我重复、舞台调度式位移。
- 与近期章节措辞高度相似。
- 少量近似等长的大段拼接。

### 6.9 独立质量主编

已经有 `_review_chapter_quality_v2`：

1. 正文通过确定性硬审查后，再调用独立模型审稿。
2. 审核维度包括情节族忠实度、因果、自然度、情绪、非重复、结尾精度和架空命名。
3. 审稿必须返回严格 JSON。
4. 审稿无效、分数不足或有硬失败时，整章作废，从空白重写。

注意：模型主编只是第二道门，不能代替 Codex 对每个情节族的人工通读。

### 6.10 模型路由

本轮最后增加了兼容性路由：

- `DASHSCOPE_CHAPTER_MODEL`
- `DASHSCOPE_QUALITY_CRITIC_MODEL`
- `DASHSCOPE_SEGMENT_MODEL`
- `DASHSCOPE_NARRATIVE_UNIT_MODEL`

并增加 `V2_NARRATIVE_UNIT_PROSE` 的识别逻辑。

当前仅完成路由入口，**叙事单元生成器还没有接入运行主循环**。

### 6.11 待提交记忆接口基础

`StoryMemoryCoordinator.state_before` 和 `review_candidate` 已增加可选 `pending_memories` 支持。

`RebirthRevengeGeneratorV2.review_story_memory` 也已兼容该参数。

目的：

1. 情节族内第 5 章可以先保存在内存中。
2. 生成第 6 章时，用第 5 章的待提交 StoryMemory 做连续性审查。
3. 整个情节族验收成功后，再统一写正文、StoryMemory 和 Neo4j。

当前状态：

- 接口基础已实现并通过测试。
- 主生成循环尚未改成“整簇暂存后统一提交”。
- 现有运行时仍会在单章通过后提前写入，最终失败时依赖事务快照恢复。

## 7. StoryMemory 与 Neo4j 的项目流程

### 7.1 正常生成

1. 正文候选通过文本硬审查。
2. `StoryMemoryCoordinator.review_candidate` 抽取结构化记忆。
3. 抽取优先使用 Qwen，失败时规则降级。
4. `validate_transition` 检查人物、状态、关系、事实和时间线。
5. 通过后写入本地 `chapter_*_memory.json`。
6. `replace_chapter_memory` 把该章投影到 Neo4j。
7. 后续章节通过在线检索器读取限长图谱背景。

### 7.2 图谱用途

Neo4j 用于：

- 已发生事件。
- 人物状态和关系。
- 已建立事实。
- 未决情节线。
- 章节时间顺序。
- 后续正文的连续性检索。

Neo4j 不能用于：

- 生成当前章的新证据。
- 把未来计划当成已经发生。
- 替代事件簇里的行动、阻挠和结果。
- 自动补出没有铺垫的材料、证人或权限。

### 7.3 当前事务恢复机制

`_generate_cluster_continuous_and_split_v2` 会快照：

- 情节族涉及的正文文件。
- 对应 StoryMemory JSON。

如果生成函数抛出异常或返回空结果，会调用 `coordinator.restore`。

`StoryMemoryCoordinator.restore` 会：

1. 恢复或删除本地记忆文件。
2. 对有快照的章节重新投影图数据库。
3. 对原本不存在的章节调用 `delete_chapter_memory_projection` 删除图数据库投影。

因此，正常 Python 异常或情节族审查失败可以同时恢复正文、StoryMemory 和 Neo4j。

但外部强制结束 Python 进程不会执行恢复函数。因此每次中断后必须人工核对三层状态。

## 8. 回滚必须同时处理正文、StoryMemory 和 Neo4j

这是硬规则，不能只删除 `chapter_XXX.txt`。

### 8.1 推荐回滚脚本

脚本：

`bert_excitation_train/scripts/neo4j_kg/delete_chapters_from_graph.py`

该脚本会同时处理旧图谱节点、新 StoryMemory 投影、正文和记忆文件。

先设置正确输出目录和 Neo4j 环境：

```powershell
$env:V2_OUTPUT_DIR = (Resolve-Path 'bert_excitation_train/outputs_pop_king_v2').Path
$env:NEO4J_URI = 'bolt://localhost:7687'
$env:NEO4J_USER = 'neo4j'
# NEO4J_PASSWORD 从本机已有安全配置读取
```

先 dry-run：

```powershell
.\.venv312\Scripts\python.exe -m bert_excitation_train.scripts.neo4j_kg.delete_chapters_from_graph --chapters 5-6 --dry-run
```

确认目标无误后执行：

```powershell
.\.venv312\Scripts\python.exe -m bert_excitation_train.scripts.neo4j_kg.delete_chapters_from_graph --chapters 5-6 --yes
```

### 8.2 回滚检查清单

1. 先停止所有正文生成进程。
2. 确认要回滚的章节范围。
3. 必要时先备份失败现场。
4. 用删除脚本 dry-run。
5. 用删除脚本正式删除。
6. 检查 `chapters` 目录。
7. 检查 `chapter_memory` 目录。
8. 查询 Neo4j 的 `StoryChapter.number`、`StoryEvent.source_chapter`、`StoryFact.source_chapter`。
9. 确认三层都只保留同一批已验收章节。
10. 再启动下一轮生成。

禁止：

- 只删正文。
- 只删 StoryMemory。
- 只删图数据库。
- 在 `V2_OUTPUT_DIR` 指向错误目录时执行删除。
- 为清理少数章节重置整个 Neo4j 数据库。

## 9. 已进行的第 5 章实验及失败诊断

### 9.1 `quality_v41`

结果：

- 第 5 章连续失败。
- 没有正式写入第 5、6 章。

主要问题：

- 里程碑在整章提示词中被多处重复。
- 模型把“体能测试”扩展成动作编号、设备和医学指标。

### 9.2 `quality_v42`

结果：

- 第 5 章候选仍然出现设备、医学、动作分解和未来材料。
- 已停止，没有正式写入。
- 代表性失败稿保存在：

  `bert_excitation_train/outputs_pop_king_v2/rejected_drafts/human_audit_failures/quality_v42`

诊断：

- 即使提示词以否定清单禁止设备和医学词，列出这些词本身也可能对模型形成反向提示。

### 9.3 `quality_v43`

结果：

- 多轮第 5 章候选均被硬审查拒绝。
- 没有正式写入。
- 进程已终止。

反复出现：

- 计时、心率、血氧、肌肉或声学指标。
- 临时歌曲名、段落编号、英文代号。
- 危险特技。
- 多段前世闪回。
- 数字取证、录制设备、报告和权限系统。
- 表演段落占比过高。

关键结论：

**继续让同一个模型整章盲重试不会自然变好。当前问题是“长文本自由度过高”，不是重试次数不足。**

### 9.4 `qwen-max` 隔离对照

使用同一通用整章提示词调用 `qwen-max`，候选只有约 802 字，并明显概述化。

它仍然出现：

- 泛化表演描述。
- “几分钟后”快速跳过。
- 鼓掌、胜利笑容等模板化结果。
- 没有达到目标篇幅。

结论：

**单纯换成更强或更贵模型不能替代工作流改造。**

## 10. 下一步应实现的通用叙事单元工作流

这是当前最重要的未完成工作。

### 10.1 目标

把“整章一次性自由生成”改成：

`情节族里程碑 → 通用场景契约 → 6 至 7 个差异化叙事单元 → 单元逐个验收 → 整章组装与审稿`

这不是第 5 章专用方案，必须适用于能力、证据、合同、安全、票务、财务和资产场景。

### 10.2 单元计划建议

每个单元使用结构化字段：

- `dramatic_function`
- `objective`
- `locked_facts`
- `allowed_cast`
- `allowed_carriers`
- `memory_allowed`
- `result_allowed`
- `target_min_chars`
- `target_max_chars`
- `paragraph_mode`

可用的通用戏剧功能包括：

- 对手先施压。
- 主角抢先改变条件。
- 利益和情绪代价。
- 对手做出不可撤回的选择。
- 当前载体产生可见证明。
- 见证者或有权者判断改变。
- 结果正式生效。
- 对手直接反应和锋利收束。

不同场景类型和行文谱型应改变单元顺序、数量、篇幅权重和段落形态，不能每章固定七段。

### 10.3 单元提示词原则

1. 每次只让模型写当前单元，不写整章。
2. 只给当前单元允许的事实。
3. 不把未来结果和未来材料提前给早期单元。
4. 只给上一单元末尾和已完成状态摘要，防止复述。
5. 每单元设置明确字数预算，总预算稳定在 1750 至 1950 字。
6. 高情绪 RAG 仍只给技法标签。
7. Neo4j 仍只给稳定连续性事实。
8. 单元不合格只重写该单元，整章因果失败才整章作废。

### 10.4 单元验收

每个单元至少检查：

- 字数是否达到分配预算。
- 是否出现标题、编号和创作标签。
- 是否新增具名人物或现实专名。
- 是否提前使用未来材料。
- 是否新增未规划设备、文件、报告、录音或参数。
- 是否重复前面单元的句子和动作。
- 前世记忆是否只在指定单元出现一次。
- 对手、主角和有权者是否符合当前功能。

组装后仍要运行所有现有整章硬审查和独立质量主编。

### 10.5 当前实现状态

已完成：

- 通用场景契约。
- 因果脊柱。
- 行文谱型。
- 模型路由入口。
- StoryMemory `pending_memories` 接口基础。

未完成：

- `_compile_narrative_unit_plan`
- `_build_narrative_unit_prompt`
- `_validate_narrative_unit`
- `_generate_grounded_narrative_units`
- 主循环默认接入。
- 单元计划测试。
- 单元失败稿归档。
- 整簇暂存后统一提交。

## 11. 后续任务顺序

### 阶段 A：完成通用链路

1. 实现叙事单元计划编译。
2. 实现逐单元生成、字数预算和通用验收。
3. 接入现有整章硬审查、跨章相似度审查和独立质量主编。
4. 把主循环改成情节族内暂存。
5. 生成下一章时把前一章待提交 StoryMemory 作为 `pending_memories` 传入。
6. 情节族整体通过后，才统一提交正文、StoryMemory 和 Neo4j。
7. 为异常回滚、空结果回滚和图谱删除增加测试。

### 阶段 B：用 EC04 验证

1. 生成第 5 章。
2. Codex 完整阅读，不只看审查器结果。
3. 核对篇幅、自然度、动作比例、情绪、即时结果和前世记忆。
4. 生成第 6 章。
5. 完整阅读第 5、6 章作为一个小故事。
6. 核对第 5 章没有提前借用第 6 章材料。
7. 核对第 6 章完成康拉德停职和药品保管权交接。
8. 情节族通过后才提交三层数据。
9. 创建新的第 1 至 6 章进度备份，不覆盖历史 `v1`。

### 阶段 C：跨场景验证到第 12 章

按同一脚本依次生成：

- 第 7、8 章：排期诱饵与合同权利。
- 第 9、10 章：实体安全验证。
- 第 11、12 章：粉丝协作和公共票务资源。

每个情节族生成后，Codex 必须亲自通读。

如果只有某个场景类型普遍失败，应改通用场景类型策略；不要按章节号打补丁。

### 阶段 D：连续生成第 13 至 20 章

当前 5 至 12 章覆盖的通用类型稳定后，使用同一脚本连续生成第 13 至 20 章。

重点检查：

- 合同场景不会都写成“会议、翻页、宣布”。
- 两组能力场景不会重复同一唱跳模板。
- 财务和资产场景不会变成后台系统、黑客和监管突袭。
- 所有章节篇幅稳定。
- 相邻章节段落结构明显不同。

### 阶段 E：前 20 章总审计

1. 逐章读取第 1 至 20 章。
2. 检查人名、地名和现实原型。
3. 检查每个情节族的现实损失和现实收益。
4. 检查 1 至 2 章闭环节奏。
5. 检查是否有连续三章同一格式。
6. 检查跨章事实和人物状态。
7. 检查正文文件、StoryMemory 和 Neo4j 章节集合完全一致。
8. 创建最终前 20 章备份和校验值。

## 12. 每个情节族必须执行的人工审查

“人工审查”在当前任务中指 Codex 自己阅读完整正文，不是只相信自动评分。

每个情节族审查时回答：

1. 开头是否迅速进入当前冲突？
2. 主角是否真的利用前世信息主动提前行动？
3. 前世记忆是否只有必要的一小句？
4. 对手是否根据既定性格主动犯错，而不是突然降智？
5. 当前证据是否来自今生布局？
6. 是否使用了情节族未允许的材料、设备、权限或人物？
7. 是否把下一章内容提前写完？
8. 本章小赢是否真实生效？
9. 情节族结尾是否写清反派损失和主角收益？
10. 情绪是否来自选择和利益变化？
11. 正文是否像小说，而不是流程、报告或分镜？
12. 篇幅是否足够且没有灌水？
13. 段落结构是否与近期章节重复？
14. 是否有现实专名或不自然谐音名？
15. 结尾是否停在结果和人物反应上？

任一核心问题不合格：

1. 不提交该情节族。
2. 同时回滚正文、StoryMemory 和 Neo4j。
3. 先判断是某个场景类型的通用问题，还是单个样本问题。
4. 优先改通用脚本、提示词、验证器或工作流。
5. 改完测试后再重新生成。

## 13. 运行与验证命令

### 13.1 Python

使用：

`.\.venv312\Scripts\python.exe`

### 13.2 语法检查

```powershell
.\.venv312\Scripts\python.exe -m py_compile `
  bert_excitation_train\scripts\v2\generate_chapter_content_v2.py `
  bert_excitation_train\scripts\neo4j_kg\story_memory.py
```

### 13.3 完整测试

```powershell
$env:PYTHONUTF8 = '1'
.\.venv312\Scripts\python.exe -m unittest discover `
  -s bert_excitation_train\tests `
  -p 'test_*.py'
```

本文档写入时最新结果：

`Ran 114 tests ... OK (skipped=3)`

3 个跳过项是需要单独 Neo4j 测试环境变量的集成测试。

### 13.4 正文运行环境示例

```powershell
$env:V2_OUTPUT_DIR = (Resolve-Path 'bert_excitation_train/outputs_pop_king_v2').Path
$env:NEO4J_URI = 'bolt://localhost:7687'
$env:NEO4J_USER = 'neo4j'
# NEO4J_PASSWORD 从本机已有安全配置读取
$env:PYTHONUTF8 = '1'

$env:DASHSCOPE_TIMEOUT_S = '35'
$env:DASHSCOPE_HARD_TIMEOUT_S = '90'
$env:DASHSCOPE_MAX_RETRIES = '3'
$env:DASHSCOPE_RETRY_BACKOFF_S = '2'

$env:V2_FORCE_GROUNDED_PLANNING = '1'
$env:V2_PREFER_SEGMENTED_CLOSED = '0'
$env:V2_ALLOW_SEGMENT_RECOVERY = '0'
$env:V2_USE_LEGACY_DETERMINISTIC_SCENES = '0'
$env:V2_USE_LEGACY_SURFACE_REWRITE = '0'
$env:V2_USE_LEGACY_CLOSED_EVIDENCE_VALIDATORS = '0'
$env:V2_ALLOW_INCREMENTAL_EXPANSION = '0'
$env:V2_ALLOW_LOCAL_CHAPTER_PATCH = '0'
$env:V2_SAVE_REJECTED_DRAFTS = '1'
```

当前不要直接运行第 5、6 章。先完成叙事单元链路和整簇暂存提交，再启动。

## 14. 关键文件地图

### 14.1 输入与正式输出

- 事件簇：
  `bert_excitation_train/outputs_pop_king_v2/event_clusters_v2.json`
- 前世上下文：
  `bert_excitation_train/outputs_pop_king_v2/prev_life_ctx_v2.txt`
- 旧主卡：
  `bert_excitation_train/outputs_pop_king_v2/master_ctx_cards_v2.json`
- 正文：
  `bert_excitation_train/outputs_pop_king_v2/chapters`
- StoryMemory：
  `bert_excitation_train/outputs_pop_king_v2/knowledge_graph/stories/7f5afaed1b5bb0c2/chapter_memory`
- 质量审稿记录：
  `bert_excitation_train/outputs_pop_king_v2/quality_audits`
- 拒绝稿：
  `bert_excitation_train/outputs_pop_king_v2/rejected_drafts`

### 14.2 代码

- V2 正文主流程：
  `bert_excitation_train/scripts/v2/generate_chapter_content_v2.py`
- 主题运行时约束：
  `bert_excitation_train/scripts/v2/theme_constraints.py`
- StoryMemory 协调器：
  `bert_excitation_train/scripts/neo4j_kg/story_memory.py`
- StoryMemory 图投影：
  `bert_excitation_train/scripts/neo4j_kg/story_memory_store.py`
- 在线图谱检索：
  `bert_excitation_train/scripts/neo4j_kg/online_retriever.py`
- 图谱回滚脚本：
  `bert_excitation_train/scripts/neo4j_kg/delete_chapters_from_graph.py`
- V2 主要测试：
  `bert_excitation_train/tests/test_runtime_theme_contract.py`
- Neo4j 集成测试：
  `bert_excitation_train/tests/test_neo4j_story_memory_integration.py`

## 15. 当前工作区改动状态

当前没有提交 Git commit。

主要修改文件：

- `bert_excitation_train/scripts/v2/generate_chapter_content_v2.py`
- `bert_excitation_train/scripts/neo4j_kg/story_memory.py`
- `bert_excitation_train/tests/test_runtime_theme_contract.py`
- 第 5 章拒绝稿及 `quality_v42` 人工失败归档

拒绝稿不是正式正文，不要因为它们出现在 `git status` 中就恢复到 `chapters`。

新对话不得使用 `git reset --hard`、`git checkout --` 等命令清除当前改动。应先阅读 diff，继续在现有通用改造上工作。

## 16. 特别警告

1. 不要继续用整章提示词无限重试第 5 章。
2. 不要只靠提高模型规格。
3. 不要启用旧的 `V2_PREFER_SEGMENTED_CLOSED` 作为最终方案。旧分段链路包含大量能力场景和药品场景的固定模板，过拟合第 5、6 章。
4. 不要为第 5、6 章单独新建脚本。
5. 不要把“硬审查通过”直接等同于“小说好看”。
6. 不要把高情绪样本原文直接注入正文提示词。
7. 不要让 Neo4j 中的未来摘要成为当前证据。
8. 不要在一个情节族未整体通过时继续批量生成后续情节族。
9. 不要在回滚时漏删图数据库。
10. 不要覆盖老师备份 `teacher_review_20260724_ch001-006_v1`。
11. 每次结束工作前确认没有正文生成进程仍在运行。
12. 未经完整人工阅读，不得宣称任何新章节“正式合格”。

## 17. 新对话的第一组动作

建议新对话按以下顺序开始：

1. 阅读本文档。
2. 运行 `git status --short`。
3. 确认没有正文生成进程。
4. 确认正式正文只有第 1 至 4 章。
5. 确认 StoryMemory 只有第 1 至 4 章。
6. 确认 Neo4j 只有第 1 至 4 章。
7. 阅读当前 `generate_chapter_content_v2.py` 中：
   - `_compile_grounded_prose_spine`
   - `_build_grounded_chapter_prompt`
   - `_scene_archetype_grounding_failures`
   - 正文主循环
   - `_generate_cluster_continuous_and_split_v2`
8. 完成通用叙事单元链路。
9. 完成整簇暂存和统一三层提交。
10. 增加测试并跑完整测试集。
11. 再生成第 5、6 章。
12. Codex 亲自阅读全文后决定是否接受。

最终目标仍是生成并验收前 20 章。当前真实完成进度是正式第 1 至 4 章，不能虚报为更多。

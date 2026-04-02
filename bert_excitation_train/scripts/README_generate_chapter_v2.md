# 📖 重生复仇小说正文生成器 V2（事件簇整簇生成）方法说明

本文档面向 `scripts/generate_chapter_content_v2.py` 的**当前 V2 版本**，用于说明：它如何从 `event_clusters_v2.json` 与 `prev_life_ctx_v2.txt` 生成正文，并通过 beats/flashback 约束、token 预算、critic 审查与必要重写来保证每章字数目标与“上一世知识只在回忆里出现”的叙事规则。

---

## 1. 脚本定位与核心差异

`generate_chapter_content_v2.py` 相比旧版的关键变化：

1. **按“事件簇/情节族”整簇生成**：同一簇内先生成连续正文，再切分为每章文本并微调开头/结尾钩子。
2. **节拍卡（beats）结构化约束**：beats 由模型输出严格 JSON（由脚本容错解析），并通过 `open_from_prev / end_to_next` 与 `flashback_in_beat_idx` 约束正文落点与回忆插入位置。
3. **critic 硬性验收 + rewrite 循环**：包括“每章字数 >= 1500”的验收；不通过则注入 `rewrite_advice` 重写，直到通过或达到最大重写次数。
4. **Rebirth knowledge 只允许通过 flashback 出现**：上一世线索只能通过 beats 中指定的 `flashback_in_beat_idx` 对应拍卡插入，禁止把上一世信息当成今生“新线索”凭空出现（具体由 beats/提示词/章节卡 must_not 联合约束）。

---

## 2. 运行入口与参数

### 2.1 默认文件

脚本默认依赖以下文件（均位于 `outputs/`）：

- `outputs/event_clusters_v2.json`：事件簇定义（chapter_span、main_opponent、core_payoff、info_gap_from_prev_life 等）
- `outputs/prev_life_ctx_v2.txt`：上一世线索（chapter_num -> 线索文本），用于 beats 的回忆内容
- （可选）`outputs/master_ctx_cards_v2.json`：章节执行卡（结构化 must/must_not/角色分工等）

如果 `master_ctx_cards_v2.json` 缺失或为空，会退回：基于事件簇动态构建 cards（避免流程中断）。

### 2.2 命令行

示例：

```powershell
python scripts/generate_chapter_content_v2.py --start 12 --end 14
```

完整参数：

- `--prev-life`：上一世线索文件路径（默认 `outputs/prev_life_ctx_v2.txt`）
- `--chapters-dir`：输出章节目录“存在性用”（默认 `outputs/chapters_v2`）
- `--start`：起始章节号（默认 `1`）
- `--end`：结束章节号（默认 `100`）

---

## 3. 输出文件在哪里？

即使你传了 `--chapters-dir`，脚本写盘时仍使用 `gen.save_chapter()` 的默认路径规则：

- 章节正文最终写入：`outputs/chapters/chapter_XXX.txt`
- 例如：`outputs/chapters/chapter_012.txt`

（`--chapters-dir` 主要用于确保工作目录存在、并作为 `gen.outputs_dir` 的来源；写盘目录由 `gen.save_chapter()` 的逻辑决定。）

---

## 4. 总体生成流程（整簇）

对每个被 `--start/--end` 覆盖到的事件簇（情节族），脚本执行：

1. **准备上一章衔接**  
   通过 `gen.get_previous_chapter_content()` 读取上一章完整正文（若存在），再由 `gen._extract_prev_chapter_tail_and_hook()` 提取：
   - `prev_tail_scene`：上一章最后场景/动作
   - `prev_unresolved_hook`：上一章未解决钩子（下一章必须接住）

2. **生成情节族 detailed synopsis**（用于 beats 约束）  
   调用 `_build_cluster_detailed_synopsis_prompt()` 让模型把簇梗概细化为可执行信息（并可注入 critic 的重写要求）。

3. **生成全簇 beats（严格 JSON）**  
   调用 `_build_cluster_beats_prompt()` 输出结构化 beats JSON，beats 对每章一般包含 8-10 拍，并允许在某一拍指定回忆插入位置。

4. **解析 beats JSON（带容错与重试）**  
   - 使用 `_extract_json_obj_maybe()` 从模型输出中提取可 `json.loads()` 的 JSON 片段。
   - beats 生成最多尝试 3 次（token 预算逐步抬高）。
   - 解析失败不会立即抛异常，而是设置 `critic_result["rewrite_advice"]`，交由外层重写循环继续。

5. **按章生成“连续正文段落”（每次只写一章正文，不写标题）**  
   调用 `_build_cluster_body_part_prompt()`，对每章：
   - 强制开头承接 `open_from_prev` 指向的未决点
   - 强制按 beats 顺序推进
   - 强制插入回忆（如 beats 指定 `flashback_in_beat_idx`）
   - 强制结尾留下 `end_to_next` 钩子
   - 强制字数不少于 1500（prompt 内硬要求，并最终由 critic 验收）

6. **“连续正文 -> 切分微调”**  
   将连续正文切分成每章文本：`_build_cluster_split_prompt()` 要求：
   - 绝大部分正文不删减、不压缩，仅允许开头/结尾钩子微调
   - 每章仍需 >= 1500 字
   - 输出必须为严格 JSON（形如 `{ "chapters": [{ "chapter_num": ..., "text": ...}] }`）

7. **写盘与 critic 审查**  
   - 先写入 `outputs/chapters/chapter_XXX.txt`
   - 再调用 `_cluster_critic(cluster, chapter_texts)` 进行硬性验收

8. **critic 不通过 -> 注入 rewrite_advice -> 重写循环**  
   - 外层 `max_cluster_attempts` 默认 5
   - 第 1 次不注入建议；第 2 次起注入 critic 产出的 `rewrite_advice` 并再次生成 beats + 连续正文 + 切分

---

## 5. beats 结构与 flashback 插入规则（重点）

### 5.1 beats JSON 字段（用于生成约束）

beats 的核心字段：

- 每个 chapter 对象：
  - `chapter_num`
  - `chapter_type`
  - `closure_type`
  - `open_from_prev`
  - `end_to_next`
  - `beats`：拍卡数组
  - `flashback_in_beat_idx`：`int` 或 `null`

- 每个 beat 对象：
  - `scene_goal / visual_elements / emotion_push / info_delta`
  - `evidence_form`：要求提供证据/记录/病历/笔记/文件被“拿出来、解释、用于翻盘”的动作要点
  - `prev_life_memory_brief`：若该章需要回忆，则仅在指定拍卡上填“上一世受害回忆要点”
  - `foreshadow / relationship_push / must_not`

### 5.2 “上一世线索只能通过 flashback 出现”

具体由两层共同保证：

1. **beats 生成时的约束**
   - 若某章需要插入上一世回忆：在对应 `flashback_in_beat_idx` 的那一拍中提供 `prev_life_memory_brief`，其余拍填空或不触发。
   - 若不需要回忆：`flashback_in_beat_idx = null`，并要求所有 beats 的 `prev_life_memory_brief` 为空字符串。

2. **正文生成时的约束**
   - 若 `flashback_in_beat_idx != null`：在“指定拍结束后”插入“完整上一世受害回忆段落”，且回忆内容围绕该拍卡里的“回忆要点”展开。
   - 文本要求回避旁支触发词（如系统提示音/重生醒来/调查等），避免把上一世知识以“今生新信息”方式冒出来。

---

## 6. 字数保证（>= 1500 字）的工程化兜底

V2 的字数达标是一个“多层防抖”机制：

1. **prompt 里强制扩写到达标**
   - `_build_cluster_body_part_prompt()` 明确要求：本章总字数不少于 `1500`（建议 1700-2200）
   - 未达到则“必须继续扩写直到达标再停止”

2. **分章切分阶段再次验收**
   - `_build_cluster_split_prompt()` 同样要求每章正文 `>= 1500`，并禁止只保留短开头/短结尾。

3. **critic 的硬验收**
   - `_cluster_critic()` 对簇中每一章逐章检查：`len(text) < 1500` 即产出 violation，并生成对应 `rewrite_advice`

4. **入口跳过逻辑避免“短章误复用”**
   - `generate_chapters_v2()` 中的 `min_chars_for_accept = 1500`
   - 若：
     - 章节已存在于内存且长度 >= 1500：跳过重写
     - 文件已存在且 utf-8 内容长度 >= 1500：直接复用
   - 否则会触发重新生成，避免之前生成的短章被错误复用。

---

## 7. token 预算（用于防止短写）

每个情节族 attempt 内部主要 token 预算（当前实现）：

- synopsis：`max_tokens_synopsis = 1400`
- beats：`max_tokens_beats = 1800`（解析失败则 `+ 600 * beats_try`）
- 连续正文（每章）：`max_tokens_body_per_chapter = 5000`
- 切分 JSON（上限随章数增长）：`max_tokens_split = min(20000, 5200 * num_chapters)`

原则：只要你发现“短章/字数不达标”，优先从这里与 critic 的 violation 列表对齐定位，而不是盲目改写生成文案。

---

## 8. critic 审查规则概览

`_cluster_critic()` 返回：

- `payoff_completed`：簇落点是否兑现
- `violations`：违规项列表
- `rewrite_advice`：用于注入下一轮重写的修复指令

主要检查维度：

1. **最后一章是否兑现反杀结果/职业毁灭/处罚落地**（关键词 + 长度条件）
2. **是否出现禁止元素或未规划角色**（如系统提示音/幕后黑手/更大风暴等）
3. **是否显性使用信息差证据形态**（当 `info_gap_from_prev_life` 存在时，检查正文是否出现证据相关关键词）
4. **每章字数 >= 1500**（硬性逐章检查）
5. **主对手是否聚焦**（冲突被稀释会触发）

---

## 9. JSON 容错与重写触发

常见故障点与对应策略：

1. beats 输出不是严格 JSON
   - 通过 `_extract_json_obj_maybe()` 从混杂输出中提取 JSON 片段
   - beats 生成最多尝试 3 次（提高 token）
2. 仍解析失败
   - 不抛 `RuntimeError` 终止整簇
   - 直接设置 `rewrite_advice = ["beats JSON 解析失败：...必须严格可被 json.loads 解析..."]`
   - 外层 attempt 捕获到 `rewrite_advice` 后进入重写循环

---

## 10. 在线检索器（Neo4j）如何影响生成

V2 会尝试挂载 `neo4j_kg.online_retriever.retrieve_context_for_chapter`：

- 在每章生成前动态拉取限长背景事实（`max_chars=900`）
- 拉取条件来自章节卡：
  - `allowed_roles`（取章节卡中的 allowed_roles，兜底包含 `沈清欢`）
  - `main_opponent`
- 注意：Neo4j 内容被要求“仅作背景，禁止替换证据链与决策”（即不应当把检索到的信息当成新的剧情转折点）。

---

## 11. 编码/终端问题说明（UnicodeEncodeError）

脚本会在启动阶段依赖基类 `generate_chapter_content.py` 的 UTF-8 强制输出封装（避免 Windows/GBK 终端打印 emoji 触发 `UnicodeEncodeError`）。

因此 V2 的运行一般不需要额外处理终端编码问题；若你仍遇到编码崩溃，优先检查是否正确使用了 `generate_chapter_content.py` 中的 stdout/stderr 兼容代码路径。

---

## 12. Troubleshooting（快速定位）

1. **出现大量短章（<1500 字）**
   - 先看 critic 日志里的 `violations`：是否全部落在“第X章字数不足”
   - 再对齐 token 预算是否足够（必要时提高 `max_tokens_body_per_chapter`、`max_tokens_split`）
   - 同时确认入口跳过逻辑是否被正确触发（`min_chars_for_accept` 是否生效）

2. **beats 解析失败反复重写**
   - 看 warning：`全簇节拍卡 JSON 解析失败...`
   - 若模型长期不输出正确 JSON，优先收紧 prompt（脚本已要求严格 JSON 且禁止 Markdown/解释文字）

3. **“上一世线索像新信息一样冒出来”**
   - 先检查 beats 中 `flashback_in_beat_idx` 与该拍卡的 `prev_life_memory_brief` 是否正确触发
   - 再检查章节卡里的 `chapter_must_not_include` 是否对该簇/该阶段做了足够的禁用约束


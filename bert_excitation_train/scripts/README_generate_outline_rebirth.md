## 重生复仇短剧：章节梗概 & 上一世故事线生成说明  

本说明只讲两件事：  
- **怎么从用户提示词，一键生成 100 章的结构化章节梗概（短剧骨架 JSON）**  
- **怎么在此基础上，生成对应的 100 条上一世遭遇线索**  

生成出的文件会被后续的“梗概二修 + 正文生成”整个流水线直接使用。  

---

## 一、入口脚本与主要产物

- 入口脚本：`scripts/generate_outline_rebirth_revenge.py`  
- 一次完整运行，会在 `outputs/` 目录下生成 3 类核心文件：

1. **结构化章节卡（短剧骨架 JSON）**
   - `outputs/master_ctx_cards.json`
   - 作用：全书 100 章的“短剧章节卡”，是后续所有流程的**唯一真源**。
   - 每一章是一个对象，典型结构如下：
     ```json
     {
       "chapter_id": 12,
       "arc_id": "A02",
       "chapter_role": "revenge_payoff",
       "present_mainline": "这一章女主借项目复盘反杀赵明轩",
       "core_conflict": "赵明轩想把延期责任甩给她",
       "flashback_trigger": "复盘会、延期责任、赵明轩那句“这次你来讲”",
       "revenge_action": "她当众放出版本时间戳和审批记录",
       "ending_hook": "散会后她收到匿名短信：你查错方向了"
     }
     ```

2. **整本章节梗概文本（兼容旧流程、人类可读）**
   - `outputs/master_ctx.txt`
   - 由上面的 JSON 渲染而来，每章一小段文本，方便人工检查，也兼容旧版只读文本梗概的脚本。

3. **上一世遭遇线索文本**
   - `outputs/prev_life_ctx.txt`
   - 每一行形如：
     ```text
     第12章对应线索：她记得上一世在项目复盘会上，赵明轩当众把延期责任甩到她身上……
     ```
   - 共 100 条，分别与第 1～100 章对应，用于后续正文生成时插入“上一世回忆”。

此外，脚本会顺带生成同名的时间戳备份，例如：  
- `outputs/master_ctx_cards_20260316_120501.json`  
- `outputs/master_ctx_20260316_120501.txt`  
- `outputs/prev_life_ctx_20260316_120501.txt`  

---

## 二、命令行使用方式

### 1. 在项目根目录运行

在仓库根目录（包含 `bert_excitation_train` 的那一层）打开终端，运行：

```bash
python bert_excitation_train/scripts/generate_outline_rebirth_revenge.py
```

默认行为（推荐）：
- 使用 **分批模式** 生成 100 章梗概（每批 5 章，内部自动拼接为 100 章）；
- 同时生成上一世线索。

可选参数：

- **不分批，一次性生成 100 章**：
  ```bash
  python bert_excitation_train/scripts/generate_outline_rebirth_revenge.py --no-batch
  ```
- **调整每批章节数**（例如每批 10 章）：
  ```bash
  python bert_excitation_train/scripts/generate_outline_rebirth_revenge.py --batch-size 10
  ```

正常情况下，脚本会在控制台输出：
- 通义调用进度  
- 分批生成第 X–Y 章章节卡的提示  
- 最终写入文件路径与前若干行预览  

---

## 三、章节梗概（结构化 JSON）的生成逻辑

### 1. 系统提示词（短剧约束）

`build_outline_system_prompt()` 会向模型传入一份“总规则”，包括但不限于：
- 类型必须是：**都市职场复仇 + 医疗阴谋揭露 + 舆论反转**，禁止写成黑帮/杀手/肉搏。
- **第 1 章**：唯一的纯上一世临死章节（ICU、网暴、被放弃抢救等）。
- **第 2 章起全部是这一世**，但每章都有“上一世对照记忆”的潜台词。
- 大量强调：
  - 每 2 章左右要有一次支线复仇爽点；
  - 主线大复仇最晚在第 97 章结束；
  - 禁止 50 章后变成“人生鸡汤/公益/女性楷模式”长篇。

### 2. 分批生成 JSON 章节卡

核心函数：`generate_outline_batch_json(...)`  

- 对于每一批（如第 1–5 章），构造用户查询：
  - 说明本批属于哪一阶段（重生开局/婚姻线/职场线/医疗线等）；
  - 要求为每章输出一个 JSON 对象，字段包括：
    - `chapter_id`：章节号（整数）
    - `arc_id`：主线/阶段 ID（如 `"A01"` 重生&婚姻线；`"A02"` 家族线；`"A03"` 职场线；`"A04"` 医疗线）
    - `chapter_role`：`revenge_payoff / grievance_build / present_only / cross_chapter`
    - `present_mainline`：本章今生主线一句话（场景 + 动作）
    - `core_conflict`：核心矛盾或对手意图
    - `flashback_trigger`：触发上一世回忆的当下事件
    - `revenge_action`：这一章的具体反制/复仇动作（或“暂时隐忍埋线”也要写具体）
    - `ending_hook`：本章结尾的悬念/钩子
- 模型输出后，脚本会：
  - 用 `json.loads` 解析为列表；
  - 校验 `chapter_id` 范围与字段完整性；
  - 为缺失或异常章节自动补一个“占位卡”，避免后续流程报错。

整本书跑完后，所有批次的卡会被合并写入 `master_ctx_cards.json`。

### 3. 从 JSON 渲染 master_ctx 文本

函数：`_render_cards_to_outline_text(cards)`  

- 按 `chapter_id` 排序；
- 渲染格式类似：
  ```text
  第1章（grievance_build）：ICU 病房里，沈清欢被丈夫和白月光放弃抢救……  结尾钩子：监护仪突然拉长警报声

  第2章（present_only）：清晨醒来，她发现自己回到了三年前的卧室……  结尾钩子：她在本子上写下第一个仇人名字
  ```
- 渲染结果写入 `outputs/master_ctx.txt`，供：
  - 你人工阅读；
  - 兼容旧版只读文本梗概的脚本。

---

## 四、上一世遭遇线索的生成逻辑

生成上一世线索的主流程仍在同一个脚本中完成：

1. **分析整本章节梗概**  
   - 函数：`analyze_outline_for_prev_life(outline_text)`  
   - 读取刚生成的 `master_ctx.txt`，让模型为每章标注：
     - 是否有支线复仇；
     - 对应的“上一世被欺负前提”。

2. **分批生成上一世梗概**  
   - 函数：`build_prev_life_batch_user_query(...)`  
   - 对每批（如第 1–5 章），将：
     - 整本章节梗概；
     - 分析结果；
     一起发给模型，要求输出：
     ```text
     第1章对应线索：……
     第2章对应线索：……
     ...
     ```

3. **验证与写入文件**  
   - 生成后通过 `validate_prev_life_clues(...)` 粗检条数与视角（必须是上一世、具体场景化、不得写成功逆袭）。  
   - 写入：
     - `outputs/prev_life_ctx.txt`
     - `outputs/prev_life_ctx_YYYYMMDD_HHMMSS.txt`

---

## 五、推荐使用顺序（从零开始一键生成）

1. **确认 API Key 等环境已配置好**  
2. 在项目根目录运行：
   ```bash
   python bert_excitation_train/scripts/generate_outline_rebirth_revenge.py
   ```
3. 检查 `outputs/` 目录是否出现：
   - `master_ctx_cards.json`
   - `master_ctx.txt`
   - `prev_life_ctx.txt`
4. 若需要再修正梗概，可按 `README_fix_synopsis.md` 的说明，对 `master_ctx` 进行二次修正，生成 `master_ctx_final`，再进入正文生成阶段（见 `重生小说正文生成_使用说明.md`）。

这样，整本 100 章的“短剧节奏梗概 + 上一世委屈线索”就都准备好了，可以直接喂给后面的章节正文生成系统。  


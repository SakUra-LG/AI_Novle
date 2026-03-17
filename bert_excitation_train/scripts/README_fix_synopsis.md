# 梗概修正器使用说明

在正文生成前，通过两个修正脚本将「原始梗概」改写为「可直接驱动正文生成」的章节执行卡和上一世受害链条，减少正文阶段乱写和「上一世一句带过」的问题。

---

## 一、文件存放位置

| 类型       | 文件路径（相对于 `bert_excitation_train/`） | 说明                         |
|------------|---------------------------------------------|------------------------------|
| 脚本 1     | `scripts/fix_master_synopsis.py`            | 章节梗概修正器               |
| 脚本 2     | `scripts/fix_prev_life_synopsis.py`         | 上一世故事线修正器           |
| 输入（梗概）| `outputs/master_ctx.txt`                    | 章节梗概（脚本 1 输入）      |
| 输入（线索）| `outputs/prev_life_ctx.txt`                 | 上一世线索（脚本 2 输入）    |
| 输出（梗概）| `outputs/master_ctx_final.txt`              | 修正后的「章节执行卡（JSON）」 |
| 输出（线索）| `outputs/prev_life_ctx_final.txt`           | 修正后的「上一世受害卡（JSON）」 |
| 备份（可选）| `outputs/master_ctx_final_backup_YYYYMMDD_HHMMSS.txt` | 若 `master_ctx_final.txt` 已存在，会先备份旧输出 |
| 备份（可选）| `outputs/prev_life_ctx_final_backup_YYYYMMDD_HHMMSS.txt` | 若 `prev_life_ctx_final.txt` 已存在，会先备份旧输出 |

**说明**：两个脚本默认**不覆盖源文件**，只生成 `_final` 输出；若 `_final` 已存在，会先备份旧的 `_final` 再写入新内容。

---

## 二、流水线位置

```
原始章节梗概 (generate_outline_rebirth_revenge.py)
    ↓
脚本1：fix_master_synopsis.py   ← 修正「这一世」章节梗概
    ↓
脚本2：fix_prev_life_synopsis.py ← 修正「上一世」故事线梗概
    ↓
generate_chapter_content.py     ← 生成正文
```

说明：`generate_chapter_content.py` 现在会**默认优先读取** `outputs/master_ctx_final.txt` 与 `outputs/prev_life_ctx_final.txt`（若存在），也可以用参数显式指定旧文件路径。

---

## 三、脚本 1：章节梗概修正器 (fix_master_synopsis.py)

### 3.1 作用

将「一句话章节梗概」改写为「6 字段以上的章节执行卡」，最低补出：

- 当前事件
- 冲突方
- 主角本章目标
- 回忆触发器（由什么物/话/场景触发上一世回忆）
- 复仇动作（可执行动作，禁止空洞宣言）
- 结尾钩子

当前解析规则**同时兼容旧版与新版梗概格式**：

- 旧版：`第N章 ：标题：内容`
- 新版（推荐）：`第N章 标题：内容`

只要行首以 `第N章` 开头，后面接任意标题+冒号+内容，脚本都能识别并生成对应的 JSON 章节卡。

### 3.2 使用方法

**命令行**（在项目根目录 `AI_Novle` 或 `bert_excitation_train` 下执行）：

```bash
# 使用默认路径
python scripts/fix_master_synopsis.py

# 指定输入/输出
python scripts/fix_master_synopsis.py --input outputs/master_ctx.txt --output outputs/master_ctx_final.txt

# 指定每批处理章节数
python scripts/fix_master_synopsis.py --batch-size 10
```

**PowerShell**：

```powershell
cd bert_excitation_train
python scripts/fix_master_synopsis.py --input .\outputs\master_ctx.txt
```

### 3.3 参数说明

| 参数         | 默认值               | 说明               |
|--------------|----------------------|--------------------|
| `--input`    | `outputs/master_ctx.txt` | 输入文件路径   |
| `--output`   | `outputs/master_ctx_final.txt` | 输出文件路径（不覆盖源文件） |
| `--batch-size` | 10                 | 每批处理段落数（内部会自动换算） |

### 3.4 产出文件

- **主输出**：`outputs/master_ctx_final.txt`（每章 1 行：`第N章：{JSON}`）
- **备份（如有旧输出）**：`outputs/master_ctx_final_backup_YYYYMMDD_HHMMSS.txt`

---

## 四、脚本 2：上一世故事线修正器 (fix_prev_life_synopsis.py)

### 4.1 作用

将「就像当年」「就像之前」式概括改写为「完整受害链条」，强制采用无知视角。

### 4.2 使用方法

**命令行**：

```bash
# 使用默认路径
python scripts/fix_prev_life_synopsis.py

# 指定输入并传入今生梗概（用于对照）
python scripts/fix_prev_life_synopsis.py --input outputs/prev_life_ctx.txt --master outputs/master_ctx_final.txt

# 指定每批处理章节数
python scripts/fix_prev_life_synopsis.py --batch-size 10
```

**PowerShell**：

```powershell
cd bert_excitation_train
python scripts/fix_prev_life_synopsis.py --input .\outputs\prev_life_ctx.txt --master .\outputs\master_ctx_final.txt
```

### 4.3 参数说明

| 参数         | 默认值                   | 说明                     |
|--------------|--------------------------|--------------------------|
| `--input`    | `outputs/prev_life_ctx.txt` | 输入文件路径         |
| `--master`   | `outputs/master_ctx_final.txt`（若不存在则退回 `master_ctx.txt`） | 今生章节卡路径（用于绑定/断点/触发器） |
| `--output`   | `outputs/prev_life_ctx_final.txt` | 输出文件路径（不覆盖源文件） |
| `--batch-size` | 8                      | 每批处理章节数           |

### 4.4 产出文件

- **主输出**：`outputs/prev_life_ctx_final.txt`（仅生成需要回忆断点的章节；每章 1 行：`第N章对应线索：{JSON}`）
- **备份（如有旧输出）**：`outputs/prev_life_ctx_final_backup_YYYYMMDD_HHMMSS.txt`

---

## 五、Critic 检查

两个脚本在修正后均会进行 Critic 检查：

- **章节梗概**：当前事件、回忆触发、复仇动作、结尾钩子等
- **上一世梗概**：禁止概括句、无知视角、受害链条、羞辱落点等

若某章未通过检查，会在控制台输出警告，但不影响保存。

---

## 六、正文生成约束（供参考）

修正后的梗概将用于 `generate_chapter_content.py`，建议正文阶段遵守：

- **上一世回忆占比**：20%–35%
- **这一世主线**：65%–80%
- **正文顺序**：当前冲突开场 → 遇到触发器 → 插入上一世具体委屈 → 回到现实布局 → 复仇动作落地 → 结尾留钩子

## 重生复仇小说全流程脚本调用速查表

> 默认假设在仓库根目录（包含 `bert_excitation_train` 的那一层）打开终端。  
> 若在其他目录，可在命令前加上 `python bert_excitation_train\scripts\...`。

---

## 一、生成整书梗概（this life + 上一世线索）

- **一次性生成 100 章章节梗概 + 上一世线索（推荐）**

```bash
python bert_excitation_train/scripts/generate_outline_rebirth_revenge.py
```

- **不分批，一次性生成 100 章**

```bash
python bert_excitation_train/scripts/generate_outline_rebirth_revenge.py --no-batch
```

- **调整每批章节数（例如每批 10 章）**

```bash
python bert_excitation_train/scripts/generate_outline_rebirth_revenge.py --batch-size 10
```

---

## 二、修正梗概（这一世 + 上一世）

- **修正这一世章节梗概 → 章节执行卡 JSON（生成 `master_ctx_final.txt`）**

```bash
# 使用默认输入/输出
python bert_excitation_train/scripts/fix_master_synopsis.py

# 指定输入/输出
python bert_excitation_train/scripts/fix_master_synopsis.py --input outputs/master_ctx.txt --output outputs/master_ctx_final.txt

# 调整批大小
python bert_excitation_train/scripts/fix_master_synopsis.py --batch-size 10
```

- **修正上一世故事线 → 受害链条 JSON（生成 `prev_life_ctx_final.txt`）**

```bash
# 使用默认输入/输出
python bert_excitation_train/scripts/fix_prev_life_synopsis.py

# 显式指定今生梗概和上一世线索
python bert_excitation_train/scripts/fix_prev_life_synopsis.py --input outputs/prev_life_ctx.txt --master outputs/master_ctx_final.txt

# 调整批大小
python bert_excitation_train/scripts/fix_prev_life_synopsis.py --batch-size 10
```

- **修复 `master_ctx_cards.json` 中的占位章节（自动补写缺失章节卡）**

```bash
python bert_excitation_train/scripts/fix_outline_missing_chapters.py
```

---

## 三、正文生成（批量或单章）

- **从第 6 章起连续生成 5 章正文（推荐示例）**

```bash
python bert_excitation_train/scripts/generate_chapter_content.py --chapter 1 --batch 10
```

- **只生成单章（如第 1 章）**

```bash
python bert_excitation_train/scripts/generate_chapter_content.py --chapter 1 --batch 1
```

- **从第 12 章起生成 3 章，并提高迭代次数与情绪下限**

```bash
python bert_excitation_train/scripts/generate_chapter_content.py --chapter 12 --batch 3 --iterations 3 --min-emotion 0.6
```

- **显式指定梗概/上一世线索文件**

```bash
python bert_excitation_train/scripts/generate_chapter_content.py \
  --chapter 6 --batch 5 \
  --master-ctx outputs/master_ctx_final.txt \
  --prev-life-ctx outputs/prev_life_ctx_final.txt
```

---

## 四、知识图谱相关

- **初始化知识图谱（正文生成前执行一次）**

```bash
cd bert_excitation_train
python scripts/init_knowledge_graph.py
```

- **自定义输入/输出初始化知识图谱**

```bash
python bert_excitation_train/scripts/init_knowledge_graph.py \
  --master outputs/master_ctx_final.txt \
  --prev-life outputs/prev_life_ctx_final.txt \
  --output outputs/knowledge_graph.json
```

- **正文生成时自动使用知识图谱（默认开启）**

```bash
python bert_excitation_train/scripts/generate_chapter_content.py --chapter 6 --batch 5
```

- **禁用知识图谱**

```bash
python bert_excitation_train/scripts/generate_chapter_content.py --chapter 6 --batch 5 --no-kg
```

- **回滚知识图谱记录（重生成某几章前使用）**

```bash
# 回滚第 6–10 章的图谱记录
python bert_excitation_train/scripts/rollback_knowledge_graph.py --chapters 6-10

# 回滚并同时删除对应章节正文文件
python bert_excitation_train/scripts/rollback_knowledge_graph.py --chapters 1-10 --delete-files
```

---

## 五、单章重生成 / 局部重跑

- **只重生成某一章正文（不走批量）**

```bash
python bert_excitation_train/scripts/generate_chapter_content.py --chapter 10 --batch 1
```

- **在回滚图谱 + 删除旧正文后重生成某一章**

```bash
python bert_excitation_train/scripts/rollback_knowledge_graph.py --chapters 10 --delete-files
python bert_excitation_train/scripts/generate_chapter_content.py --chapter 10 --batch 1
```

- **使用 `regenerate_single_chapter.py`（如脚本存在的基础用法）**

```bash
python bert_excitation_train/scripts/regenerate_single_chapter.py --chapter 10
```

> 若需要更多高级参数，可直接打开对应脚本查看 `argparse` 定义。


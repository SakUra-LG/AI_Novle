# 情绪向样本集使用说明（委屈 / 复仇爽感）

正文生成器会**根据本章是否写「上一世回忆」、是否写「复仇/反制」**，自动从对应样本集中检索参考片段，并注入到生成提示中，用于强化**委屈感**与**复仇爽感**。

## 一、两套样本集是什么

| 文件 | 样本集类型 | 用途 |
|------|------------|------|
| `data/rebirth_revenge_samples.txt` | **重生复仇爽感** | 写「这一世反杀、打脸、揭穿、扳倒」时参考，强化痛快、解气、掌控感 |
| `data/prev_life_grievance_samples.txt` | **上一世委屈** | 写「上一世被欺负、被冤枉、被抛弃」回忆时参考，强化委屈、绝望、心寒 |

格式与 `data/universal_samples.txt` 完全一致（`## 标题` + `**情绪标签**` / `**场景标签**` 等 + `**内容**:` 正文）。

## 二、生成正文时如何自动调用

- 脚本会根据**本章梗概与上一世线索**自动判断：
  - **需要上一世回忆**（有 `need_prev_life` 或触发回忆）→ 从 **上一世委屈** 样本集中检索 2 条，注入「写回忆时参考」；
  - **有复仇/反制情节**（梗概中含复仇、反制、揭穿、打脸等）→ 从 **重生复仇爽感** 样本集中检索 2 条，注入「写反杀/打脸时参考」；
  - 另从 **通用样本集**（`universal_samples.txt`）中检索 2 条作为通用风格参考。
- 无需额外参数，运行批量生成即可：

```bash
python scripts/generate_chapter_content.py --chapter 6 --batch 5
```

## 三、如何更新样本库（必须执行）

新增或修改 `rebirth_revenge_samples.txt` / `prev_life_grievance_samples.txt` 后，需要**重新跑一遍样本处理**，才会被正文生成器检索到：

```bash
cd bert_excitation_train
python scripts/handle_universal_samples.py
```

该脚本会依次读取：

- `data/universal_samples.txt` → 标记为 `universal`
- `data/rebirth_revenge_samples.txt` → 标记为 `重生复仇爽感`
- `data/prev_life_grievance_samples.txt` → 标记为 `上一世委屈`

并合并向量化，输出到 `data/universal_samples_vectors.npy` 与 `data/universal_samples_data.json`（每条样本带 `sample_set` 字段）。

## 四、当前正文生成对情绪与样本的用法小结

- **情绪**：生成流程中已有「情绪强化点」（委屈/愤怒/同情/爽感）、情绪强度要求与迭代优化，**有**重点关注委屈与复仇爽感。
- **样本集**：  
  - 原先只有「通用」一套，且仅在使用 `generate_with_rag()` 的路径时才会用样本；  
  - 现在**批量生成**（`generate_one_chapter_with_beats()`）也会按章节**自动检索**「上一世委屈」与「重生复仇爽感」两套样本，并写入 prompt，生成正文时会自动参考。

你可以直接往 `rebirth_revenge_samples.txt` 和 `prev_life_grievance_samples.txt` 里按上述格式追加新片段，跑一遍 `handle_universal_samples.py` 后，再生成正文即可自动调用这两套样本。

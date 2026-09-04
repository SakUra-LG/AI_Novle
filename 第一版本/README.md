# 第一份小说交付物

此目录是第一份 500 章小说的冻结交付版本。不要在这里直接运行生成任务，以免把运行中间产物混入交付物。

更完整的环境配置、Neo4j 规划同步、只读预检、断点续跑和问题说明见 `bert_excitation_train/scripts/novel_generation_v2/README.md`。

## 保留文件

- `全书500章正文_386-500人工修订终稿.docx`：唯一正文；已核验包含连续的第 1—500 章。
- `event_clusters_v2.json`：250 个情节族梗概。
- `chapter_synopses_v5_qwen_500.json`：500 章章节梗概。
- `master_ctx_cards_v2.json`：500 章正文执行卡。
- `global_story_outline_v5_qwen_500.json`：全局故事线和规划身份。

人物约束、生命周期、复仇风格样本仍保存在 `bert_excitation_train/data/`；世界规则保存在 `bert_excitation_train/scripts/novel_generation_v2/pop_king_world_rules_v1.json`。

## 基于本版本继续生成

先新建工作目录并复制四个 JSON，避免污染冻结交付物：

```powershell
New-Item -ItemType Directory -Force work_outputs\first_novel | Out-Null
Copy-Item 第一版本\*.json work_outputs\first_novel\
python -m bert_excitation_train.scripts.novel_generation_v2.generate_pop_king_body_v5 `
  --output-dir work_outputs\first_novel `
  --start-cluster 1 `
  --end-cluster 1 `
  --dry-run
```

去掉 `--dry-run` 才会正式请求模型并写入正文。该专用生成器还会连接 Neo4j；使用前请阅读小说生成和知识图谱目录的说明。

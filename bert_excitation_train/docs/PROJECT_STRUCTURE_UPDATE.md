### 项目结构整理（知识图谱与 V2 生成管线）

本次整理目标：
- 将所有“知识图谱（KG）相关输出”集中到一个文件夹
- 提供一个统一的 V2 生成脚本（事件簇 → 大纲 → 正文）
- 标注 V1 与 V2 的组织方式，降低路径与脚本选择成本

### 一、知识图谱（KG）输出目录
- 现在统一放在：`bert_excitation_train/outputs/knowledge_graph/`
  - 当前版本：`knowledge_graph.json`
  - 历史版本（旧 KG 导出）：`old_knowledge_graph.json`

原路径中的 `outputs/knowledge_graph.json` 与 `outputs/old/knowledge_graph.json` 已迁移到上述目录。

### 二、V2 生成统一脚本
- 新脚本：`bert_excitation_train/scripts/generate_v2_pipeline.py`
  - 串联三个阶段：
    1) `generate_event_clusters_v2.py`
    2) `generate_outline_from_event_clusters_v2.py`
    3) `generate_chapter_content_v2.py`
  - 用法（Windows PowerShell）：

```powershell
python bert_excitation_train/scripts/generate_v2_pipeline.py `
  --project-config bert_excitation_train/config/project_configs.json `
  --generation-config bert_excitation_train/config/generation_config.json `
  --chapters 11,12,13
```

- 可选参数：
  - `--skip-clusters` 跳过事件簇阶段
  - `--skip-outline` 跳过大纲阶段
  - `--skip-chapters` 跳过正文阶段
  - `--python` 指定解释器，`--workdir` 指定工作目录

### 三、文档
- Neo4j 最简上手与 KG 构建/导出参见：`bert_excitation_train/docs/neo4j_kg_setup.md`
- 本文档：`bert_excitation_train/docs/PROJECT_STRUCTURE_UPDATE.md`

### 四、V1 与 V2 的关系
- V2：推荐使用，具备更完整的数据流与上下文组织；统一入口为 `generate_v2_pipeline.py`
- V1：原始脚本仍保留在各自路径（如 `generate_chapter_content.py` 等），后续如需完全迁移到 `scripts/legacy_v1/` 再行通知与回迁 imports

本次变更力求“增量、安全、可落地”，不大幅改动现有导入关系；如需进一步把 V1/V2 源码彻底移动到新目录，请先确认依赖关系后进行。*** End Patch```}ихся to=functions.apply_patch  दूसरा code_executionיגה Error: The patch content must end with the line "*** End Patch". Please try again. !***assistant to=functions.apply_patch러운.commentary  газета  Japan ***!

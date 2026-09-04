# AI 小说自动生成项目

本仓库保留可继续使用的 V2 小说生成链路、情绪样本与评分工具、RAG、知识图谱、训练和人工标注功能。第一份 500 章小说只保留最终正文及继续生成所需的权威规划文件；历史正文、试写、备份、审计报告、日志和临时文件已移除。

## 目录

- `第一版本/`：第一份小说的唯一终稿和四个权威规划输入。
- `主题备选/`：后续选题与生成限制。
- `bert_excitation_train/scripts/novel_generation_v2/`：当前 V2 梗概、事件簇和正文生成。
- `bert_excitation_train/scripts/emotion_scoring/`：情绪评分与情绪强度样例生成。
- `bert_excitation_train/scripts/rag/`：样本向量化、检索和适配。
- `bert_excitation_train/scripts/knowledge_graph/`：Neo4j 连续性记忆。
- `bert_excitation_train/scripts/model_training/`：评分模型与 LoRA 训练。
- `bert_excitation_train/scripts/annotation_feedback/`：人工标注、反馈和样本采集。
- `bert_excitation_train/data/`：全部情绪样本、标注集和训练集。
- `bert_excitation_train/checkpoints/`、`bge_large_zh/`：已有模型与中文向量模型。

每个功能目录内都有独立的 `README.md`。

## 环境

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r bert_excitation_train\requirements.txt
$env:DASHSCOPE_API_KEY = "你的密钥"
```

Neo4j 功能另需设置 `NEO4J_URI`、`NEO4J_USER` 和 `NEO4J_PASSWORD`。仓库不保存 API 密钥。

## 最常用入口

生成一部新的 V2 小说：

```powershell
python -m bert_excitation_train.scripts.novel_generation_v2.generate_v2_pipeline --non-interactive
```

正式运行前请先阅读 [V2 小说生成交接手册](bert_excitation_train/scripts/novel_generation_v2/README.md)。其中区分了“通用 V2”和“第一份 500 章小说专用流程”，并说明了安全输出目录、断点续跑、Neo4j、验收清单及当前已知问题。建议先按手册执行 10 章无 Neo4j 试跑，不要直接启动 500 章在线生成。

只生成指定章节：

```powershell
python -m bert_excitation_train.scripts.novel_generation_v2.generate_chapter_content_v2 --start 1 --end 10 --skip-neo4j-sync
```

运行不需要在线服务的测试：

```powershell
python -m pytest bert_excitation_train\tests -q
```

第一份小说冻结文件说明见 `第一版本/README.md`；继续生成正文的完整步骤见上述 V2 交接手册。

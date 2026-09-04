# 功能脚本目录

脚本按职责拆成六个可独立理解的功能目录。请从各目录 README 中列出的模块入口运行，不要依赖当前工作目录中的相对导入。

- `novel_generation_v2/`：V2 故事规划与正文生成；其 `README.md` 是当前生成流程的详细交接手册，包含通用流程、第一份小说专用流程和已知问题。
- `emotion_scoring/`：情绪评分、语义评分和强度样例。
- `rag/`：样本库构建与检索。
- `knowledge_graph/`：Neo4j 故事连续性。
- `model_training/`：模型训练与训练数据准备。
- `annotation_feedback/`：人工标注与反馈闭环。

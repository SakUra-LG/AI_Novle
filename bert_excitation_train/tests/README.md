# 测试

本目录保留当前 V2 生成、规划编译、主题契约、Qwen 传输和 StoryMemory/Neo4j 逻辑的测试。已删除只针对历史试写和一次性修复脚本的测试。

```powershell
python -m pytest bert_excitation_train\tests -q
```

Neo4j 集成测试需要可用数据库和相应环境变量；其余单元测试应可离线运行。

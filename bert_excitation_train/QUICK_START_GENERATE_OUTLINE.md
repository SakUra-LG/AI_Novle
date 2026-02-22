# 快速开始：生成重生复仇短剧梗概

## 📋 使用步骤

### 1. 检查环境

确保已安装必要的 Python 包：

```bash
pip install dashscope transformers torch numpy scikit-learn
```

### 2. 检查 API Key

打开 `scripts/generate_outline_rebirth_revenge.py`，确认第 27 行的 API Key 是否正确：

```python
API_Key_QW = "sk-a2966f4e37134351904851679884cb67"
```

如果 API Key 已过期，请替换为你的通义千问 API Key。

### 3. 运行脚本

在项目根目录（`bert_excitation_train`）下运行：

```bash
python scripts/generate_outline_rebirth_revenge.py
```

### 4. 等待生成完成

脚本会执行两个步骤：
1. **生成整本 100 章章节梗概**（约 30-60 秒）
2. **生成每一章对应的上一世遭遇线索点**（约 30-60 秒）

总耗时约 **1-2 分钟**。

### 5. 查看结果

生成完成后，可以在以下位置查看结果：

- **章节梗概**：`outputs/master_ctx.txt`
- **上一世线索点**：`outputs/prev_life_ctx.txt`
- **备份文件**：`outputs/master_ctx_YYYYMMDD_HHMMSS.txt` 和 `outputs/prev_life_ctx_YYYYMMDD_HHMMSS.txt`

## 📝 输出文件说明

### master_ctx.txt（章节梗概）

包含整本 100 章的详细章节梗概，格式示例：

```
第1章 死在冰冷的病床上：沈清欢被全网骂成"作死女主播"，在 ICU 里被当成浪费资源的负担。
这一章写她意识模糊中听见医生冷漠地说"放弃吧"，亲人犹豫着签字放弃抢救，男友却不见踪影。
她最后的心情是"又冷又委屈"，直到心跳线变成一条直线。

第2章 全网狂欢的葬礼：她死后，网络上把她当笑话转发，黑热搜挂了一整天。
...
```

### prev_life_ctx.txt（上一世遭遇线索点）

包含每一章对应的上一世遭遇线索点，格式示例：

```
第1章对应线索：她记得前世在 ICU 病房里，医生冷漠地宣布放弃抢救，家人签字同意，她躺在冰冷的病床上，感受着生命一点点流逝，心中充满了委屈和不甘（对应今生第1章）

第2章对应线索：她记得前世死后，网络上铺天盖地的谩骂和嘲讽，黑热搜挂了一整天，所有人都把她当成笑话，连葬礼都仓促得像处理烂摊子（对应今生第2章）
...
```

## ⚠️ 注意事项

1. **API 调用费用**：每次运行会调用两次通义千问 API，请注意 API 使用量
2. **生成时间**：根据网络和 API 响应速度，可能需要 1-2 分钟
3. **文件覆盖**：重新运行脚本会覆盖 `master_ctx.txt` 和 `prev_life_ctx.txt`，但会保留时间戳备份
4. **RAG 样本**：如果 `data/universal_samples_data.json` 存在，脚本会自动检索相关样本用于引导生成

## 🔧 常见问题

**Q: 提示找不到 `smart_sample_search` 模块？**  
A: 确保在项目根目录运行脚本，脚本会自动处理模块导入路径。

**Q: API 调用失败？**  
A: 检查 API Key 是否正确，网络是否正常，以及通义千问服务是否可用。

**Q: 生成的章节数不是正好 100 章？**  
A: 这是正常现象，AI 生成的内容可能会有少量浮动。可以手动调整或重新生成。

**Q: 如何修改生成的内容风格？**  
A: 编辑 `scripts/generate_outline_rebirth_revenge.py` 中的 `build_outline_system_prompt()` 和 `build_prev_life_outline_system_prompt()` 函数，修改提示词内容。

## 📚 更多信息

详细说明请参考：`README_generate_outline.md`

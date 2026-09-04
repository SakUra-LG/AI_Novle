# RAG 样本检索

## 作用

把 `bert_excitation_train/data/universal_samples.txt` 等样本转为向量，并按语义、情绪标签和项目设定检索高质量参考片段。小说生成器会调用 `smart_sample_search.py`。

## 用法

首次构建或更新向量：

```powershell
python -m bert_excitation_train.scripts.rag.handle_universal_samples
```

测试多标签检索：

```powershell
python -m bert_excitation_train.scripts.rag.multi_label_search_example
```

验证 RAG 效果：

```powershell
python -m bert_excitation_train.scripts.rag.verify_rag_effectiveness
```

默认中文嵌入模型位于仓库根目录 `bge_large_zh/`；向量结果位于 `bert_excitation_train/data/universal_samples_vectors.npy`。

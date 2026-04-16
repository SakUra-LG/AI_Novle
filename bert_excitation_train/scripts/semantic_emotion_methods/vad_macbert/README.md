# VAD-MacBERT 接入

来源仓库：[`Pectics/vad-macbert`](https://github.com/Pectics/vad-macbert)

## 说明

- 该方法主打 **VAD 连续评分**（valence/arousal/dominance）。
- 本目录脚本默认会额外调用现有 `manual` 方法补一个情绪类型，满足“评分+分类”同时输出。

## 依赖

```bash
.\.venv312\Scripts\python.exe -m pip install transformers torch
```

## 使用

交互模式：

```bash
.\.venv312\Scripts\python.exe bert_excitation_train/scripts/semantic_emotion_methods/vad_macbert/vad_macbert_cli.py
```

单句模式：

```bash
.\.venv312\Scripts\python.exe bert_excitation_train/scripts/semantic_emotion_methods/vad_macbert/vad_macbert_cli.py --text "这段剧情让我很压抑"
```

只看 VAD，不补分类：

```bash
.\.venv312\Scripts\python.exe bert_excitation_train/scripts/semantic_emotion_methods/vad_macbert/vad_macbert_cli.py --classify-method none --text "这段剧情让我很压抑"
```

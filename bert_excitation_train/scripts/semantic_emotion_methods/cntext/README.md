# 开源实现目录

该目录用于放置“基于开源代码”的语义与情绪评分实现。

建议后续按来源拆分子目录，例如：

- `transformers_based/`
- `snownlp_based/`
- `paddlenlp_based/`

每个子目录建议至少包含：

- 实现脚本
- 依赖说明
- 统一输出格式（尽量与 `handwritten/manual_semantic_emotion_scorer.py` 对齐）

## 已接入方法

- `cntext_emotion_cli.py`：基于 `cntext` 的情绪特征提取与强度评分脚本。

## 使用方式

1) 安装依赖（强烈建议使用项目虚拟环境，不要直接用全局 `pip3`）：

```bash
.\.venv312\Scripts\python.exe -m pip install -U pip
.\.venv312\Scripts\python.exe -m pip install cntext --upgrade
.\.venv312\Scripts\python.exe -m pip install ipython psutil
```

2) 交互模式（终端持续输入）：

```bash
.\.venv312\Scripts\python.exe bert_excitation_train/scripts/semantic_emotion_methods/cntext/cntext_emotion_cli.py
```

运行后会在终端中引导你：
- 是否启用 LLM 结构化评分
- 若启用 LLM，默认使用项目 Qwen 配置（DashScope 兼容地址 + Qwen 模型）
- 然后由用户选择“使用默认配置”或“手动修改配置”
- 输入要分析的中文文本

输入 `exit` 可退出。

说明：
- 默认始终输出“情绪类型判断 + 词典加权强度评分”；
- 当你在交互中选择启用 LLM 时，会尝试执行并输出到 `llm_structured_scoring`；
- 若模型名未配置，`llm_structured_scoring.status` 会显示 `skipped`。
- 默认 Qwen 配置可通过环境变量覆盖：`DASHSCOPE_BASE_URL`、`DASHSCOPE_API_KEY`、`DASHSCOPE_MODEL_NAME`、`DASHSCOPE_TEMPERATURE`。

## 常见问题

- 若执行 `pip3 install cntext --upgrade` 报 `numpy requires GCC >= 8.4`：
  - 原因通常是用了全局 Python（如 3.14），触发源码编译；
  - 请改用上面的 `.venv312` 命令安装（Python 3.12）。

- 快速确认当前解释器：

```bash
.\.venv312\Scripts\python.exe --version
.\.venv312\Scripts\python.exe -m pip --version
```


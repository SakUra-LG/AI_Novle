## 重生复仇短剧 · 100 章梗概生成使用说明

本说明文档介绍如何使用脚本 `scripts/generate_outline_rebirth_revenge.py` 自动生成「重生复仇短剧」整本 100 章左右的详细梗概，并写入 `outputs/master_ctx.txt`，供后续正文生成模块使用。

---

### 1. 环境与前置条件

- **Python 版本**：建议 Python 3.8 及以上  
- **依赖**：确保项目已有依赖（如 `dashscope` 等）已按主仓库说明安装  
- **通义千问 API Key**：
  - 在 `scripts/generate_outline_rebirth_revenge.py` 中有一行：

    ```python
    API_Key_QW = "sk-xxxxxxxxxxxxxxxx"
    ```

  - 请将其替换为你自己的通义千问 API Key，或改为从环境变量中读取（如有需求）。

- **RAG 样本文件**（可选但推荐）：
  - `data/universal_samples_data.json`
  - `universal_samples_vectors.npy`
  - 脚本会调用 `smart_sample_search.search_and_adapt_samples`，从这些样本中检索与“重生 + 复仇 + 极致委屈 + 爽文”高度相关的片段，用来引导大纲的情绪与节奏。

---

### 2. 脚本功能概述

脚本路径：`scripts/generate_outline_rebirth_revenge.py`

**核心功能**：

- 为项目「重生复仇短剧」生成整本约 100 章的**章节梗概**（不是正文）
- 自动调用：
  - `smart_sample_search.search_and_adapt_samples` 做情绪/情节 RAG 检索
  - 通义千问（qwen_turbo）根据提示词与样本生成完整章节纲要
- 将最终结果写入：
  - 主文件：`outputs/master_ctx.txt`
  - 时间戳备份：`outputs/master_ctx_YYYYMMDD_HHMMSS.txt`

**章节结构（概念）**：

- 前 2–3 章：上一世的极致委屈、被网暴、被放弃抢救等，主要是“憋屈 + 心寒”
- 中间约 80–90 章：重生后按阶段复仇，每个节点都：
  - 有当下冲突
  - 点出上一世对应的委屈记忆
  - 描写这一世如何翻盘、当场打脸
- 最后几章：真相彻底曝光、仇人付出代价、主角走向新的人生

---

### 3. 运行方式

1. 打开命令行（PowerShell / CMD / Terminal 等）
2. 切换到项目根目录（包含 `scripts` 文件夹的那一层），例如：

   ```bash
   cd D:\Study\College\Scientific research\张颖——AI小说自动生成\张颖——AI小说自动生成\bert_excitation_train\AI_Novle\bert_excitation_train
   ```

3. 执行脚本：

   ```bash
   python scripts/generate_outline_rebirth_revenge.py
   ```

4. 等待模型生成（可能需要几十秒）：
   - 命令行会显示检索到的样本数量
   - 完成后会提示：
     - 主文件路径：`outputs/master_ctx.txt`
     - 备份文件路径：`outputs/master_ctx_YYYYMMDD_HHMMSS.txt`
   - 控制台会打印前 20 行梗概预览，方便快速检查风格是否符合预期。

---

### 4. 输出文件说明

- **主梗概文件**：`outputs/master_ctx.txt`
  - 存放本次最新的 100 章梗概
  - `smart_context_loader` / 正文生成流程会优先从这里读取作为整本的“总纲”
  - 如果你重新运行脚本，该文件会被新的梗概覆盖

- **备份文件**：`outputs/master_ctx_YYYYMMDD_HHMMSS.txt`
  - 每次生成都会单独保存一份带时间戳的副本，方便回滚或对比不同版本大纲

**章节格式示例**（示意）：

```text
第1章 死在冰冷的病床上：沈清欢被全网骂成“作死女主播”，在 ICU 里被当成浪费资源的负担。
这一章写她意识模糊中听见医生冷漠地说“放弃吧”，亲人犹豫着签字放弃抢救，男友却不见踪影。
她最后的心情是“又冷又委屈”，直到心跳线变成一条直线。

第2章 全网狂欢的葬礼：她死后，网络上把她当笑话转发，黑热搜挂了一整天。
家族为了撇清关系，把所有责任推到她头上，连葬礼都仓促得像处理烂摊子。
上一世的委屈在这一章被彻底铺满，为后面重生后的反击埋下情绪基调。
……
```

---

### 5. 与正文生成的衔接

- `outputs/master_ctx.txt` 会作为“整本书的总梗概”被加载到上下文中：
  - 写第 N 章时，可以结合：
    - 已经写出的前文章节
    - `master_ctx` 中对应章节的规划
  - 这样可以保证：整体情节连贯，前世记忆与今生反杀的对照关系不容易跑偏。

如果你更新了梗概（重新跑脚本）：

- 再次写正文前，建议先快速浏览 `master_ctx.txt`，确认整体节奏、复仇顺序和情绪曲线都符合当前设想。

---

### 6. 常见问题（简要）

- **Q：能不能改成别的题材（例如豪门、古代、娱乐圈）？**  
  A：可以。修改脚本中的提示词部分（如主角身份、时代背景、复仇对象类型等），然后重新运行脚本生成新的 `master_ctx.txt`。

- **Q：每次生成的章数不一定正好 100 章怎么办？**  
  A：脚本的提示词会强烈约束在“约 100 章”，少量上下浮动属于正常现象，一般不会影响整体使用。如果你需要严格 100 章，可以人工微调梗概文件。

- **Q：会覆盖旧的梗概吗？**  
  A：会覆盖 `outputs/master_ctx.txt`，但不会覆盖历史备份。每次生成都会额外保留一份带时间戳的备份文件，可以随时回滚或对比版本。  


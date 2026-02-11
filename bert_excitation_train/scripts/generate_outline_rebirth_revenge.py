#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为「重生复仇短剧」项目生成整本 100 章详细梗概，并写入 outputs/master_ctx.txt

设计目标：
- 前 2-3 章：上一世的极致委屈、被骂、被背叛、被放弃抢救，强烈调动读者愤怒情绪
- 之后约 90 章：重生后的爽文反杀过程，每次重大复仇节点都会勾连上一世的具体委屈记忆→再反杀
- 梗概要求：每章至少 2~3 句，有清晰冲突和情绪走向，不写大段正文
"""

import os
import json
from datetime import datetime
import dashscope

from smart_sample_search import search_and_adapt_samples


# 路径统一：无论从哪个目录运行，梗概都始终写到项目根目录下的 outputs/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "outputs")


# ===== 通义千问 API 基础配置（与 universal_generator 保持一致风格） =====
API_Key_QW = "sk-a2966f4e37134351904851679884cb67"
MAX_TOKENS = 8192


def call_qianwen_api(messages, temperature=0.9, top_p=0.85, repetition_penalty=1.1):
    """调用通义千问 API，返回纯文本内容"""
    dashscope.api_key = API_Key_QW
    try:
        response = dashscope.Generation.call(
            model=dashscope.Generation.Models.qwen_turbo,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            result_format="message",
            max_tokens=MAX_TOKENS,
        )

        if "output" in response and "choices" in response["output"]:
            content = response["output"]["choices"][0]["message"]["content"]
            # 通义经常带 markdown，这里简单清洗一下
            return content.replace("```", "").strip()
        else:
            return f"通义千问 API 返回了无效格式: {str(response)}"
    except Exception as e:
        return f"调用通义千问 API 出错: {str(e)}"


def build_outline_system_prompt(adapted_samples=None):
    """
    构造系统提示词：
    - 强调「上一世极致委屈 + 今世爽文复仇」的情绪结构
    - 明确输出格式：第1章 XXX：一句话概括。后面 2~3 句展开。
    """
    base = """
你现在是一名非常擅长「重生复仇爽文短剧」的专业网文编剧。
你的任务是：为一部 100 章左右的短剧小说，编写**整本书的详细章节梗概**，而不是写正文。

【故事基调】
- 项目名称：重生复仇短剧
- 主角：沈清欢（现代都市社畜）
- 整体风格：前期极致委屈、被骂、被误解、被背叛 → 重生之后步步反杀的爽文

【结构要求】
1）前世篇（约 2~3 章）
   - 只写上一世的内容：被全网骂、被亲人放弃抢救、被男人背叛，被医生冷漠对待等。
   - 重点是「极致委屈」和「读者替她不值、想骂人的那种愤怒」。
   - 每一章都要有具体场景（比如 ICU 病房、网络直播间、家庭争吵、公司甩锅会议）。

2）重生开局（约 5~8 章）
   - 写她确认自己重生、重新面对同一张早餐桌、同一家公司、同一批亲戚和渣男。
   - 她一边装乖顺、装不记得，一边暗中观察和记仇，开始记录“上一世是谁怎么害她的”。

3）复仇主线（约 80~90 章）
   - 每当进入一个**新的复仇节点**时，请遵循固定结构：
     a. 先用 1~2 句写「这一生的表面冲突/事件」（例如：项目甩锅、家族逼捐、职场背刺等）
     b. 接着点到「上一世对应的委屈记忆」（具体到哪个场景、哪句话、哪一个背叛动作）
     c. 然后写「这一世她如何提前布局 / 反向利用 / 翻转，在当场打脸、反杀」
   - 复仇对象可以分层推进：小角色试刀 → 职场对手 → 渣男未婚夫 → 白月光闺蜜 → 家族长辈 → 医院和资本集团幕后黑手。
   - 情绪节奏：前半段偏憋屈 + 小爽，后半段逐渐升级为大爽、群像反转、舆论反噬。

4）终局篇（最后 3~5 章）
   - 所有仇人都已付出代价，上一世的医疗事故真相彻底曝光，舆论道歉、法律裁决。
   - 她真正从“只想报仇”走向“学会为自己而活”，开始新的人生规划，可以适度埋一点感情线的希望。

【章节梗概写法要求】
- 必须严格使用以下格式编号，不要使用 markdown 标题，也不要加多余符号：
  第1章 ……：……。
  后面 2~4 句详细梗概。
- 每一章至少 2~3 句，有明确：
  - 当章的主要冲突
  - 主角的情绪（尤其是委屈 / 心寒 / 解气 / 爽感）
  - 如果是复仇节点，要写出「上一世的对照记忆」这一点。
- 不要写对白台词，不要写成完整正文，只写剧情梗概。
"""

    # 如果有高分样本，附加在提示词后面，引导情绪和风格
    if adapted_samples:
        sample_texts = []
        for i, sample in enumerate(adapted_samples, 1):
            sample_texts.append(
                f"【样本{i} - {sample.get('category', '')}】\n"
                f"情绪标签: {', '.join(sample.get('emotion_tags', []))}\n"
                f"情节标签: {', '.join(sample.get('plot_tags', []))}\n"
                f"内容节选: {sample.get('content', '')[:180]}..."
            )
        base += "\n【下面是可以参考的高分样本，主要学习“极致委屈”和“爽文反杀”的情绪与节奏】\n"
        base += "\n\n".join(sample_texts)

    base += """

【最终输出要求】
- 只输出从第1章到第100章的中文章节梗概，不要解释你的思路。
- 不要使用任何 markdown 语法（如 ##、**、- 等），只保留纯文本。
- 章节数控制在大约 100 章，可以略微上下浮动，但请尽量写满 100 章。
"""
    return base.strip()


def generate_outline_rebirth_revenge():
    """为《重生复仇短剧》生成整本 100 章梗概，并写入项目根目录 outputs/master_ctx.txt"""
    project_name = "重生复仇短剧"
    user_query = (
        "请为一部现代都市背景的《重生复仇短剧》设计整本 100 章左右的详细章节梗概，"
        "前 2-3 章只写上一世被冤枉、被网暴、被抛弃抢救的极致委屈，后面章节写她重生之后"
        "一步步复仇、每次复仇前都勾连上一世具体委屈记忆，再完成当场反杀，整体偏爽文风格。"
    )

    print("=" * 60)
    print(f"为项目《{project_name}》生成整本 100 章梗概")
    print("=" * 60)

    # 1）RAG：从通用样本中找出与“重生复仇 + 委屈 + 爽文”高度相关的片段
    print("加载通用样本，检索高情绪样本中...")
    adapted_samples = search_and_adapt_samples(
        user_input=user_query,
        target_context="主角：沈清欢；标签：重生、复仇、爽文、现代都市、极致委屈、强烈愤怒",
        top_k=5,
        min_similarity=0.3,
    )

    if not adapted_samples:
        print("未能加载或匹配到合适的样本，将在无样本参考的情况下直接生成大纲。")
    else:
        print(f"找到 {len(adapted_samples)} 个相关样本，将用于引导情绪与风格。")

    # 2）构造系统提示词
    system_prompt = build_outline_system_prompt(adapted_samples)

    # 3）调用通义千问生成
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query},
    ]

    print("\n开始调用通义千问生成 100 章梗概，这可能需要几十秒，请耐心等待...\n")
    outline_text = call_qianwen_api(messages)

    # 4）保存到 项目根目录 outputs/master_ctx.txt，并做一份时间戳备份
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    main_outline_path = os.path.join(OUTPUT_DIR, "master_ctx.txt")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(OUTPUT_DIR, f"master_ctx_{timestamp}.txt")

    with open(main_outline_path, "w", encoding="utf-8") as f:
        f.write(outline_text)

    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(outline_text)

    print(f"✅ 梗概生成完成，已写入：{main_outline_path}")
    print(f"📝 已自动备份一份到：{backup_path}")
    print("\n前 20 行预览：\n")
    for i, line in enumerate(outline_text.splitlines()[:20], 1):
        print(f"{i:02d}: {line}")


def main():
    """命令行入口"""
    generate_outline_rebirth_revenge()


if __name__ == "__main__":
    main()


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
- 整体风格：前期极致委屈、被骂、被误解、被背叛 → 重生之后节奏极快、冲突密集、每章都有爽点或反转的复仇爽文。

【结构要求】
1）前世篇（约 2~3 章）
   - 只写上一世的内容：被全网骂、被亲人放弃抢救、被男人背叛，被医生冷漠对待等。
   - 重点是「极致委屈」和「读者替她不值、想骂人的那种愤怒」。
   - 每一章都要有具体场景（比如 ICU 病房、网络直播间、家庭争吵、公司甩锅会议），让读者记住具体的屈辱细节。

2）重生开局（约 5~8 章）
   - 写她确认自己重生、重新面对同一张早餐桌、同一家公司、同一批亲戚和渣男。
   - 她一边装乖顺、装不记得，一边暗中观察和记仇，开始记录“上一世是谁怎么害她的”，并迅速在这一世提前插手、暗中报复。

3）复仇主线（约 80~90 章）
   - 每当进入一个**新的复仇节点**时，请遵循固定结构：
     a. 先用 1~2 句写「这一生的表面冲突/事件」（例如：项目甩锅、家族逼捐、职场背刺等）
     b. 接着点到「上一世对应的委屈记忆」（具体到哪个场景、哪句话、哪一个背叛动作）
     c. 然后写「这一世她如何提前布局 / 反向利用 / 翻转，在当场打脸、反杀」，确保这一章有清晰的爽点或反转。
   - 复仇对象可以分层推进：小角色试刀 → 职场对手 → 渣男未婚夫 → 白月光闺蜜 → 家族长辈 → 医院和资本集团幕后黑手 → 当年的主刀医生以及其背后的更大势力。
   - 情绪节奏：全程保持节奏快 + 冲突密集 + 小高潮不断，每一个阶段都有明显的阶段性大高潮（例如某个仇人身败名裂、某个真相曝光引爆舆论）。

4）终局篇（最后 3~5 章）
   - 重点放在「上一世医疗事故 / 手术台抛弃她」背后真正的终极黑幕大反转，例如：找到当年的主刀医生，发现对方并非普通失误，而是带有明确动机、甚至收钱“故意让她死”，牵出更大的利益链。
   - 终局依旧以复仇和真相反转为核心情绪高潮，允许她赢得彻底的情绪大爽（仇人垮台、真相直播、舆论反噬），但**不要写大段“放下仇恨”“重建人生道路”“正能量励志成长”“成立基金会做公益”“成为女性楷模”之类的内容**。
   - 可以有一点点“她后续怎么继续利用这些权力/资源压制仇人余党、确保自己再也不会被人捏死”的交代，但整体结尾基调仍然是复仇爽、反转爽，而不是温柔治愈或鸡汤励志。

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
- 只输出从第1章开始的中文章节/阶段梗概，不要解释你的思路。
- 不要使用任何 markdown 语法（如 ##、**、- 等），只保留纯文本。
- 可以同时使用「第X章」和「第X-XX章」两种编号形式来描述单章或一整段阶段故事线，整体容量约等于 100 章（每章正文约 1000 字）。
- 全书从前到后的核心类型必须始终是「重生 + 复仇 + 爽感」，尤其是 50 章之后，也要围绕仇人清算、真相揭露、大规模反转和情绪上的大爽展开，**不要写“走向正能量、放下仇恨、全身心投入公益、重建人生道路、鸡汤式成长故事”等内容**。

【章节跨度与节奏补充】
- 前世篇与重生开局可以按单章细写。
- 进入复仇主线中段之后，优先用「第X-XX章 ……」的形式，把 8~15 章左右合并成一个阶段故事线。
- 当你使用「第X-XX章」这种章节跨度时：
  1）必须用 4~6 句把这一整段内部的大致时间推进、人物关系变化、冲突升级与反杀过程说清楚，而不是只写一两句空泛总结。
  2）同一段范围内**不要再单独列出第X章、第X+1章……等单章标题**，也不要在后面出现与前面章节跨度有重叠的区间（例如已有「第9-15章」，后面就不能再写「第10章」「第11章」或「第14-20章」）。
  3）每个阶段内部都要包含：铺垫 → 危机升级 → 关键转折 → 反转反杀 → 余波收尾，并与上一世的委屈记忆形成对照。
- 示例：第7-17章 对职场敌人的第一次系统性反击：……（用 4~6 句概括这 10 章的起伏、人物关系此消彼长，以及最终的大爽反杀点）。
"""
    return base.strip()


def build_prev_life_outline_system_prompt():
    """
    构造「上一世完整故事线梗概」的系统提示词：
    - 基于已经生成的整本章节梗概，再抽取一条独立的上一世时间线
    - 强调委屈、愤怒、怨恨等强烈负面情绪
    - 方便后续在生成正文时，把这一条时间线当成长期上下文反复调用
    """
    base = """
你现在是一名专门为「重生复仇爽文」做前期故事规划的专业编剧助手。
在你已经拿到整本书的章节梗概之后，你的任务是：

【任务目标】
- 单独整理出一条「上一世完整故事线梗概」，只写她上一世从被算计、被网暴、被家人和渣男抛弃抢救、到最终死亡的全过程。
- 这条上一世故事线会在后续生成正文时，作为长期上下文与线索库，被频繁调用和引用。
- 要求特别关注并强化：委屈、屈辱、冤枉、被背叛、绝望、愤怒、怨恨等强烈负面情绪。

【内容与结构要求】
1）时间顺序
   - 按照「上一世真实发生的时间顺序」来写：从最早被算计/被设计开始，一直到 ICU/手术台被放弃抢救、全网骂名、彻底死亡。
   - 不要掺杂重生之后的内容，也不要提前写她复仇成功的画面。

2）情节点拆分方式
   - 你可以用「上一世第1章」「上一世第2章」……的形式，或者「上一世第1-3章」「上一世第4-8章」这类阶段形式来写。
   - 每一个情节点都要写清：
     a. 具体事件场景（例如：公司会议被甩锅、家族逼捐、ICU 病房被放弃抢救、网络直播间被骂等）；
     b. 她当时的心理状态和情绪（重点是委屈、屈辱、愤怒、怨恨，而不是治愈和释怀）；
     c. 这一节点在「今生重生后」会成为怎样的复仇动机或记忆刺痛点。

3）与整本章节梗概的对应关系
   - 在可能的情况下，请在每一个「上一世情节点」后面，用括号简单标注它大致对应的今生章节范围。
   - 格式示例：
     上一世第1章 被当众栽赃成小三：……（对应今生：第7-12章 职场反击线索）
   - 如果无法准确对应某一章，可以只写「对应今生：职场复仇线」「对应今生：家族清算线」这类粗略指向。

【写法要求】
- 只写梗概，不写对白，不写成完整正文。
- 每个「上一世章节/阶段」至少 2~3 句，重要的大节点可以写到 4~6 句。
- 必须保持整体风格阴郁、压抑、憋屈、愤怒，为后续重生复仇做情绪垫底，而不是写成温暖励志或治愈系回忆。

【最终输出格式要求】
- 先从「上一世第1章」开始往后写，或使用「上一世第X-XX章」的阶段形式。
- 全程不要使用 markdown 语法（如 ##、**、- 等），只保留纯文本。
- 不要解释你的思路，也不要重复抄写整本书章节梗概，只根据我提供的章节梗概进行高度提炼和重组。
"""
    return base.strip()


def generate_outline_rebirth_revenge():
    """为《重生复仇短剧》生成整本 100 章梗概 + 上一世完整故事线梗概，并写入项目根目录 outputs/"""
    project_name = "重生复仇短剧"
    user_query = (
        "请为一部现代都市背景的《重生复仇短剧》设计整本约 100 章容量的详细章节/阶段梗概，"
        "前 2-3 章只写上一世被冤枉、被网暴、被抛弃抢救的极致委屈，重点写清楚她上一世具体是怎么被害死的；"
        "后面章节写她重生之后一步步提前报复、每次复仇前都勾连上一世具体委屈记忆，再完成当场反杀，整体必须是节奏快、冲突密集、每章都有爽点或反转的爽文风格，"
        "中后段可以使用「第7-17章 对敌人的第一次反击」这类阶段形式来概括一整段对敌行动，而不是每一章都变成完全独立的小故事；"
        "直到大结局之前，都要紧紧围绕重生复仇主线推进，尤其是终局要设计一个对整本书情节影响巨大的终极反转，例如找到当年的主刀医生并揭穿他故意让她死、背后还有更大利益链；"
        "不要写成单纯的都市职场/商业成功、放下仇恨去做公益、励志正能量成长故事。"
    )

    print("=" * 60)
    print(f"为项目《{project_name}》生成整本 100 章梗概 + 上一世完整故事线梗概")
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

    print("\n开始调用通义千问生成整本 100 章章节/阶段梗概，这可能需要几十秒，请耐心等待...\n")
    outline_text = call_qianwen_api(messages)

    # 4）保存「整本章节梗概」到 项目根目录 outputs/master_ctx.txt，并做一份时间戳备份
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    main_outline_path = os.path.join(OUTPUT_DIR, "master_ctx.txt")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(OUTPUT_DIR, f"master_ctx_{timestamp}.txt")

    with open(main_outline_path, "w", encoding="utf-8") as f:
        f.write(outline_text)

    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(outline_text)

    print(f"✅ 整本章节梗概生成完成，已写入：{main_outline_path}")
    print(f"📝 已自动备份一份到：{backup_path}")
    print("\n整本章节梗概前 20 行预览：\n")
    for i, line in enumerate(outline_text.splitlines()[:20], 1):
        print(f"{i:02d}: {line}")

    # 5）在整本章节梗概的基础上，再生成一条「上一世完整故事线梗概」
    print("\n" + "=" * 60)
    print("开始在整本章节梗概基础上，生成『上一世完整故事线梗概』...")
    print("=" * 60 + "\n")

    prev_life_system_prompt = build_prev_life_outline_system_prompt()

    prev_life_user_query = (
        "下面是这本《重生复仇短剧》的整本章节/阶段梗概，请你在充分理解的基础上，"
        "根据我之前给出的要求，单独整理出一条「上一世完整故事线梗概」。"
        "只写她上一世从被算计、被网暴、被家人和渣男抛弃抢救，到彻底死亡的全过程，"
        "注意强化委屈、屈辱、冤枉、愤怒、怨恨等负面情绪，并尽量标注这些节点在今生大致对应哪一段复仇情节。"
        "\n\n【整本章节梗概如下】\n"
        + outline_text
    )

    prev_life_messages = [
        {"role": "system", "content": prev_life_system_prompt},
        {"role": "user", "content": prev_life_user_query},
    ]

    prev_life_text = call_qianwen_api(prev_life_messages)

    # 6）保存「上一世完整故事线梗概」到单独文件，并做时间戳备份
    prev_life_main_path = os.path.join(OUTPUT_DIR, "prev_life_ctx.txt")
    prev_life_backup_path = os.path.join(OUTPUT_DIR, f"prev_life_ctx_{timestamp}.txt")

    with open(prev_life_main_path, "w", encoding="utf-8") as f:
        f.write(prev_life_text)

    with open(prev_life_backup_path, "w", encoding="utf-8") as f:
        f.write(prev_life_text)

    print(f"✅ 上一世完整故事线梗概生成完成，已写入：{prev_life_main_path}")
    print(f"📝 已自动备份一份到：{prev_life_backup_path}")
    print("\n上一世故事线梗概前 20 行预览：\n")
    for i, line in enumerate(prev_life_text.splitlines()[:20], 1):
        print(f"{i:02d}: {line}")


def main():
    """命令行入口"""
    generate_outline_rebirth_revenge()


if __name__ == "__main__":
    main()


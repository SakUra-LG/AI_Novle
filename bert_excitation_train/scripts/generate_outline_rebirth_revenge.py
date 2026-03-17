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
import re
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


def count_chapters(text):
    """统计文本中的章节数量，支持单章和跨度章节"""
    # 匹配单章：第X章
    single_chapters = re.findall(r'第(\d+)章', text)
    # 匹配跨度章节：第X-XX章
    range_chapters = re.findall(r'第(\d+)-(\d+)章', text)
    
    chapter_set = set()
    # 添加单章
    for ch in single_chapters:
        chapter_set.add(int(ch))
    
    # 添加跨度章节
    for start, end in range_chapters:
        start_num, end_num = int(start), int(end)
        for ch in range(start_num, end_num + 1):
            chapter_set.add(ch)
    
    return len(chapter_set), chapter_set


def validate_outline(outline_text, min_chapters=100):
    """验证章节梗概是否符合要求"""
    chapter_count, chapter_set = count_chapters(outline_text)
    
    issues = []
    
    # 检查章节数量
    if chapter_count < min_chapters:
        issues.append(f"❌ 章节数量不足：只有 {chapter_count} 章，要求至少 {min_chapters} 章")
    
    # 检查是否有类型偏移关键词（黑帮、杀手、肉搏等）
    type_keywords = ['黑帮', '杀手', '肉搏', '单挑', '战斗', '格斗', '武力', '打斗']
    found_keywords = []
    for keyword in type_keywords:
        if keyword in outline_text:
            found_keywords.append(keyword)
    
    if found_keywords:
        issues.append(f"⚠️  检测到类型偏移关键词：{', '.join(found_keywords)}，可能偏离都市职场复仇类型")
    
    # 检查是否包含100章
    if 100 not in chapter_set and chapter_count < 100:
        issues.append(f"❌ 未包含第100章，最高章节为第{max(chapter_set) if chapter_set else 0}章")
    
    return chapter_count >= min_chapters, issues, chapter_count


def validate_prev_life_clues(clues_text, min_clues=100):
    """验证上一世线索是否符合要求"""
    # 统计线索数量
    clue_count = len(re.findall(r'第(\d+)章对应线索', clues_text))
    
    issues = []
    
    # 检查线索数量
    if clue_count < min_clues:
        issues.append(f"❌ 线索数量不足：只有 {clue_count} 条，要求至少 {min_clues} 条")
    
    # 检查抽象情绪描述关键词
    abstract_keywords = ['她感到', '她觉得', '她想起那些日子', '她被逼入绝境', '她一遍遍想着', '她想起那些', '她想起过去']
    found_abstract = []
    for keyword in abstract_keywords:
        if keyword in clues_text:
            found_abstract.append(keyword)
    
    if found_abstract:
        issues.append(f"⚠️  检测到抽象情绪描述：{', '.join(found_abstract[:3])}...，线索应该具体场景化")
    
    # 检查今生视角关键词
    present_keywords = ['她面对', '她直面', '她决定', '她前往', '她接近', '她击败']
    found_present = []
    for keyword in present_keywords:
        if keyword in clues_text:
            found_present.append(keyword)
    
    if found_present:
        issues.append(f"❌ 检测到今生视角关键词：{', '.join(found_present[:3])}...，线索必须是上一世视角")
    
    # 检查"今生成就回顾"关键词（最严重问题）
    success_keywords = [
        '国际新闻', '联合国', '颁奖典礼', '舞台掌声', '发布会', '俯瞰城市',
        '接过奖杯', '观众鼓掌', '雷鸣般的掌声', '竖起大拇指', '成了榜样',
        '勇敢的女性', '我们的英雄', '谢谢你让我们看到了希望', '你是我们的英雄',
        '医疗体制改革', '全球医疗改革', '跨国巨头垮台', '各国代表发言',
        '粉丝留言', '专访片段', '媒体报道', '新闻报道', '新闻播报'
    ]
    found_success = []
    for keyword in success_keywords:
        if keyword in clues_text:
            found_success.append(keyword)
    
    if found_success:
        issues.append(f"❌ 严重错误：检测到'今生成就回顾'关键词：{', '.join(found_success[:5])}...，上一世必须是彻底失败的一生，不允许出现成功、获奖、掌声、国际影响等")
    
    # 检查"被动感知"关键词（信息密度下降）
    passive_keywords = [
        '看到', '听到', '看到一段', '看到一张', '看到一篇', '看到一则',
        '听到', '听到讨论', '听到有人说', '听到报道',
        '在报纸', '在网站', '在电视', '在新闻', '在报道', '在视频',
        '看到新闻', '看到报道', '看到视频', '看到头条', '看到传单',
        '听到讨论', '听到抱怨', '听到发言', '听到讲话'
    ]
    # 统计被动感知的数量（60章以后）
    lines = clues_text.split('\n')
    passive_count_after_60 = 0
    for i, line in enumerate(lines):
        if '第6' in line or '第7' in line or '第8' in line or '第9' in line or '第10' in line:
            for keyword in passive_keywords:
                if keyword in line:
                    passive_count_after_60 += 1
                    break
    
    if passive_count_after_60 > 10:
        issues.append(f"⚠️  60章后被动感知过多（{passive_count_after_60}处），线索应该是上一世发生在她身上的具体事件，而不是'看新闻'、'听别人说'等被动感知")
    
    # 检查是否包含具体场景关键词（好的标志）
    scene_keywords = ['在', '里', '会议室', '病房', '公司', '医院', '家庭', '餐桌', '当众', '说', '拿出', '挂断']
    scene_count = sum(1 for keyword in scene_keywords if keyword in clues_text)
    
    if scene_count < 5:
        issues.append("⚠️  线索中具体场景描述较少，建议增加具体场景、行为、人物描述")
    
    # 综合判断：如果有"今生成就回顾"关键词，直接判定为失败
    is_valid = clue_count >= min_clues and len(found_present) == 0 and len(found_success) == 0
    
    return is_valid, issues, clue_count


def build_outline_system_prompt(adapted_samples=None):
    """
    构造系统提示词：
    - 强调「上一世极致委屈 + 今世爽文复仇」的情绪结构
    - 明确输出格式：第1章 XXX：一句话概括。后面 2~3 句展开。
    - 强制要求100章输出
    """
    base = """
你现在是一名非常擅长「重生复仇爽文短剧」的专业网文编剧。
你的任务是：为一部**严格100章**的短剧小说，编写**整本书的详细章节梗概**，而不是写正文。

【⚠️ 核心硬性要求】
- **必须输出完整的100章，一章都不能少！**
- 类型必须始终是「都市职场复仇 + 医疗阴谋揭露 + 舆论反转」，禁止写成黑帮动作、杀手战斗、直接肉搏等类型。
- 复仇手段以：职场反杀、证据曝光、舆论操控、法律追责、资本博弈为主，不是物理战斗。
- 紧扣"重生"主题，每章都要有"上一世记忆对照"和"今生提前布局"的双线结构。

【故事基调】
- 项目名称：重生复仇短剧
- 主角：沈清欢（现代都市社畜）
- 整体风格：前期极致委屈、被骂、被误解、被背叛 → 重生之后节奏极快、冲突密集、每章都有爽点或反转的复仇爽文。
- 核心类型：都市职场复仇 + 医疗事故真相揭露 + 资本链曝光 + 舆论反转，不是动作爽文。

【⚠️ 结构硬约束 - 必须遵守】
1）第1章（唯一纯上一世章）
   - **只有第1章**完全描写上一世临死前的场景，激发读者兴趣。
   - 具体场景：ICU病房、被全网骂、被亲人放弃抢救、被男人背叛、医生冷漠等。
   - 极致委屈、读者想骂人的那种愤怒，让读者记住屈辱细节。
   - **第2章起全部进入这一世，不得再写纯上一世章节。**

2）支线穿插要求（非常重要）
   - **不能全篇只为一条全局主线走**，必须穿插支线剧情。
   - 支线示例：上一世被背黑锅的项目，这一世直接告发复仇；年会陷害→这一世当场揭露；财务栽赃→这一世反栽回去等。
   - **约每2章就要有一次支线复仇的爽感爆发**，不能把所有爽感堆在最后。
   - 大复仇主线可保留多章连续的高潮（如某次大反击占3-5章），但中间必须穿插支线小爽点。

3）重生开局（第2-10章，共9章）
   - 第2章起即为这一世：她确认重生、面对早餐桌/公司/亲戚/渣男。
   - 装乖顺、暗中记仇，开始记录"上一世是谁怎么害她的"，提前插手暗中报复。
   - 每章穿插小支线复仇（如项目背锅→告发、年会陷害→反杀），约每2章有一次爽感。

4）复仇主线 + 支线交替（第11-97章）
   - 主线：职场小角色 → 核心仇人 → 医疗真相 → 终极黑幕。
   - **主线大复仇最晚在第97章结束**，不得拖到98章之后。
   - 支线穿插：项目甩锅、年会陷害、财务栽赃、客户抢单、订婚宴反转、家族对峙等，每约2章有一次支线复仇爽感。
   - 允许某次大反击占用多章（如第50-55章连续揭露医疗阴谋），但中间仍要有支线小爽点调节节奏。

5）终局篇（第98-100章，共3章）
   - 主线大复仇已在97章前结束，此3章做收尾、情绪余韵、真相公之于众的收束。
   - 终局以复仇收尾和真相反转为核心，**不要写大段"放下仇恨""重建人生道路""正能量励志成长""成立基金会做公益""成为女性楷模"**

【章节梗概写法要求】
- 必须严格使用以下格式编号，不要使用 markdown 标题，也不要加多余符号：
  第1章 ……：……。
  后面 2~4 句详细梗概。
- **必须从第1章写到第100章，一章都不能少！**
- 每一章至少 2~3 句，有明确：
  - 当章的主要冲突
  - 主角的情绪（尤其是委屈 / 心寒 / 解气 / 爽感）
  - 如果是复仇节点，要写出「上一世的对照记忆」这一点
- 不要写对白台词，不要写成完整正文，只写剧情梗概。
- 可以使用「第X-XX章」的跨度形式，但必须确保总章节数达到100章，且跨度之间不能重叠。
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

【批次生成说明】（当按批生成时生效）
- 若本批含第1章：第1章必须只写上一世临死场景，第2章起写这一世。
- 若本批为第2章及以后：全部写这一世，穿插支线复仇，约每2章有一次支线爽感。
- 主线大复仇最晚在第97章结束。

【最终输出要求】
- **必须输出完整的100章，从第1章到第100章，一章都不能少！**
- 只输出从第1章开始的中文章节/阶段梗概，不要解释你的思路。
- 不要使用任何 markdown 语法（如 ##、**、- 等），只保留纯文本。
- 可以同时使用「第X章」和「第X-XX章」两种编号形式来描述单章或一整段阶段故事线，但**必须确保总章节数严格等于100章**。
- 全书从前到后的核心类型必须始终是「都市职场复仇 + 医疗阴谋揭露 + 舆论反转」，禁止写成黑帮动作、杀手战斗、直接肉搏等类型。
- 尤其是 50 章之后，也要围绕仇人清算、真相揭露、大规模反转和情绪上的大爽展开，**不要写"走向正能量、放下仇恨、全身心投入公益、重建人生道路、鸡汤式成长故事"等内容**。

【章节跨度与节奏补充】
- 前世篇与重生开局必须按单章细写（第1-10章）。
- 进入复仇主线之后，可以适当使用「第X-XX章 ……」的形式，但必须确保：
  1）总章节数严格等于100章
  2）每个跨度必须用 4~6 句把这一整段内部的大致时间推进、人物关系变化、冲突升级与反杀过程说清楚
  3）同一段范围内**不要再单独列出第X章、第X+1章……等单章标题**，也不要在后面出现与前面章节跨度有重叠的区间
  4）每个阶段内部都要包含：铺垫 → 危机升级 → 关键转折 → 反转反杀 → 余波收尾，并与上一世的委屈记忆形成对照
- 示例：第11-15章 对职场敌人的第一次系统性反击：……（用 4~6 句概括这 5 章的起伏、人物关系此消彼长，以及最终的大爽反杀点）。
"""
    return base.strip()


def build_prev_life_outline_system_prompt():
    """
    构造「上一世遭遇线索点」的系统提示词：
    - 基于已经生成的整本章节梗概，为每一章生成对应的上一世遭遇线索点
    - 这些线索点是隐式的，不是完整的故事，而是简短的遭遇描述
    - 方便后续在生成正文时，在遇到对应情节时作为回忆片段引用
    - 强制要求具体场景化，禁止抽象情绪描述
    """
    base = """
你现在是一名专门为「重生复仇爽文」做前期故事规划的专业编剧助手。
在你已经拿到整本书的章节梗概之后，你的任务是：

【⚠️ 核心硬性要求】
- **必须输出完整的100个线索点，从第1章到第100章，一个都不能少！**
- **每个线索点必须是具体场景化描述，禁止抽象情绪描述！**
- **所有线索点都必须是"上一世"视角，禁止写成"今生"视角！**
- **线索点要有信息递进：每10-15章揭示一层医疗阴谋真相！**

【🚫 最严重禁止项 - 上一世世界观设定】
**上一世的核心设定：女主彻底失败的一生**
- 上一世中，女主被陷害、压制、孤立、抹黑、利用、威胁
- 最终结局是死亡或毁灭
- **所有反抗必须失败或被压制**

**❌ 上一世绝对不能出现以下内容：**
- 成功、翻案成功、获得社会认可
- 获奖、表彰、掌声、舞台掌声、颁奖典礼
- 媒体支持她、组织帮助她、公众理解她
- 事业成功、地位提升、成为榜样
- 国际新闻、联合国、全球影响、跨国巨头垮台
- 新闻发布会（如果是她成功）、专访片段、媒体报道她成功
- 粉丝留言、观众鼓掌、雷鸣般的掌声、竖起大拇指
- "你是我们的英雄"、"谢谢你让我们看到了希望"等正面评价

**✅ 如果涉及媒体、机构或社会层面，只能是：**
- 拒绝她、无视她、封锁消息、篡改报道、威胁撤稿、调查被终止
- 媒体抹黑她、机构打压她、社会误解她
- 例如："她在新闻上看到媒体篡改报道，把她的申诉说成'无理取闹'，她打电话给记者，对方直接挂断。"
- 例如："她在法院门口等待时，看到记者们围着她拍照，但报道出来的却是'疑似精神异常'的标题。"

**❌ 禁止"被动感知"（信息密度下降问题）：**
- 禁止大量使用"看到新闻"、"听到讨论"、"看到报道"、"听到有人说"等被动感知
- 线索应该是"上一世发生在她身上的具体事件"，而不是"她被动感知社会氛围"
- ❌ 错误："她在网上看到一段视频"、"她在报纸头条看到"、"她在咖啡店里听到两名白领讨论"
- ✅ 正确："她在公司会议室里，赵明轩当众把财务漏洞甩到她身上"、"她在ICU病房里，林修远站在床边冷笑说'你这种人，活着就是祸害'"

**✅ 线索必须是具体事件（场景+行为+人物+伤害）：**
- 必须描述：她被谁害、什么时候、做了什么、失去了什么
- 不是描述：社会怎么评价、别人怎么讨论、新闻怎么报道

【任务目标】
- 为整本书的每一章（共100章）生成对应的「上一世遭遇线索点」。
- **章节结构说明**：第1章整章为上一世临死场景；第2章起全部为这一世，穿插支线复仇（如项目背锅→告发、年会陷害→反杀等）。每章对应的上一世线索，即该章这一世情节所对照的「上一世被欺负/被陷害」的具体事件。
- 这些线索点不是完整的故事章节梗概，而是隐式的、简短的遭遇描述。
- 这些线索点会在后续生成正文时，在遇到章节梗概中提到的复仇情节或合适的时间节点后，作为回忆片段被引用。
- 要求特别关注并强化：委屈、屈辱、冤枉、被背叛、绝望、愤怒、怨恨等强烈负面情绪。

【线索点的具体场景化要求 - 这是最重要的！】
❌ 禁止抽象情绪描述，例如：
   - "她被逼入绝境"
   - "她想起那些日子，每天提心吊胆"
   - "她一遍遍想着自己为何如此不堪"
   - "她感到绝望"
   - "她觉得痛苦"

✅ 必须具体场景化，包含以下要素：
   1. **具体场景**：在哪里发生的（公司会议室、医院病房、家庭餐桌、网络直播间等）
   2. **具体行为**：谁做了什么具体动作（赵明轩当众甩锅、林修远挂断电话、医生冷漠转身等）
   3. **具体人物**：涉及哪些具体人物（赵明轩、林修远、江晚晴、主刀医生等）
   4. **具体伤害**：具体哪句话、哪个动作伤害了她（"你这种人，活着就是祸害"、"财务漏洞是你造成的"等）

✅ 正确示例：
   - "她记得在公司会议室里，赵明轩当众把财务漏洞甩到她身上，所有人沉默，她连辩解机会都没有。"
   - "她想起在ICU病房里，林修远站在床边冷笑说'你这种人，活着就是祸害'，护士们冷冷看着她，没人愿意为她争一句。"
   - "她记得在家庭聚会上，父亲当着所有亲戚的面质问她'你是不是做了什么见不得人的事'，然后直接挂断电话。"

【信息递进设计 - 医疗阴谋层层揭示】
线索点必须按照以下节奏递进，每10-15章揭示一层医疗阴谋真相：

第1-15章：个人背叛层面
   - 职场背叛、家庭冷漠、渣男背叛等个人层面的委屈
   - 注意：必须是具体事件，不是被动感知

第16-30章：初步医疗线索
   - 发现手术报告被篡改、医院记录异常等初步线索
   - 注意：必须是"她试图查证但被拒绝/被威胁"的具体事件，不是"她看到新闻说"

第31-45章：资本链线索
   - 发现医院董事会有资本控股、医疗设备采购异常等
   - 注意：必须是"她试图调查但被压制/被威胁"的具体事件

第46-60章：医生异常线索
   - 发现主刀医生账户异常转账、与某组织有联系等
   - 注意：必须是"她试图揭露但被拒绝/被威胁"的具体事件

第61-75章：组织线索
   - 发现匿名组织与林修远有关、多人受害等
   - 注意：必须是"她试图求助但被拒绝/被威胁"的具体事件

第76-90章：终极真相（但她的反抗仍然失败）
   - 发现"故意让她死"的医疗阴谋、收钱杀人等
   - 注意：必须是"她试图揭发但被压制/被威胁/被拒绝"的具体事件
   - **关键：即使发现了真相，她的反抗也必须失败或被压制**

第91-100章：完整真相链（但她的反抗仍然失败）
   - 完整的利益链、所有参与者的动机等
   - 注意：必须是"她试图公开但被拒绝/被威胁/被压制"的具体事件
   - **关键：即使知道了完整真相，她的反抗也必须失败或被压制，最终导致死亡**

【规模限制 - 短剧类型要求】
- **规模应该是：城市级、行业级、资本集团级**
- **禁止：国际级、全球级、联合国级、时代英雄叙事**
- 线索应该聚焦在：城市内的医院、公司、资本集团、行业内的利益链
- 不要涉及：国际媒体、联合国、全球浪潮、跨国巨头等

【内容与结构要求】
1）线索点的性质
   - 这些线索点是隐式的，贯穿整个100章的内容。
   - 不是要写章节梗概中前几章描写上一世的情节，而是要贯穿整个100章。
   - 整个小说都应该以上一世遭遇为线索展开，是隐式的。
   - 每个线索点必须明确标注对应的今生章节（对应今生第X章）。

2）线索点的格式
   - 必须严格按照以下格式输出：
     第X章对应线索：具体场景化的上一世遭遇描述（对应今生第X章）
   - 每一章都要有一个对应的线索点，共100个。
   - 每个线索点应该是1-3句话的简短描述，不是完整的章节梗概。
   - 描述必须包含：具体场景 + 具体行为 + 具体人物 + 具体伤害

3）线索点的内容要求
   - 每个线索点必须描述：她在上一世在类似情况下或类似事件中受到的具体遭遇。
   - 例如：如果今生第7章是"第一次反击：公司年会中揭露李娜"，那么对应的上一世线索点应该是"她记得前世在公司年会上，李娜当众拿出伪造的证据指控她泄露公司机密，所有人看向她的目光都充满怀疑，她连辩解的机会都没有就被保安带走了。"
   - 线索点必须强调：委屈、屈辱、冤枉、被背叛、绝望、愤怒、怨恨等负面情绪，但要用具体场景和行为来体现，不是直接说情绪。

4）与章节梗概的对应关系
   - 每个线索点必须明确标注对应的今生章节（对应今生第X章）。
   - 线索点应该与今生章节梗概中的情节形成对照关系。
   - 如果今生章节是复仇情节，线索点应该描述上一世在类似情况下的具体委屈遭遇。
   - 如果今生章节是其他情节，线索点应该描述上一世在类似情况下的相关具体遭遇。

【写法要求】
- 只写简短的遭遇描述，不写对白，不写成完整正文。
- 每个线索点1-3句话即可，不要过长。
- 必须保持整体风格阴郁、压抑、憋屈、愤怒，为后续重生复仇做情绪垫底。
- 不要写成温暖励志或治愈系回忆。
- **禁止使用"她感到"、"她觉得"、"她想起那些日子"等抽象表述，必须写具体场景和行为。**

【最终输出格式要求】
- **必须严格按照以下格式输出，从第1章到第100章，每一章都要有一个对应的线索点：**
     第1章对应线索：……（对应今生第1章）
     第2章对应线索：……（对应今生第2章）
     ……
     第100章对应线索：……（对应今生第100章）
- 全程不要使用 markdown 语法（如 ##、**、- 等），只保留纯文本。
- 不要解释你的思路，也不要重复抄写整本书章节梗概，只根据我提供的章节梗概生成对应的上一世遭遇线索点。
- **必须确保输出100个线索点，一个都不能少！**

【极短强化版 - 核心规则总结】
关键限制：上一世是彻底失败的一生。
- 所有反抗必须失败或被压制。
- 不允许出现成功、翻案、社会认可、媒体支持、获奖、掌声或国际影响。
- 每条线索必须是具体事件（场景+行为+人物+伤害），禁止情绪总结或概括。
- 禁止"看新闻"、"听别人说"等被动感知，必须是"发生在她身上的具体事件"。
- 规模限制：城市级、行业级、资本集团级，不要国际级。
"""
    return base.strip()


def build_batch_chapter_user_query(
    batch_start: int, batch_end: int, prior_summary: str = "", adapted_samples=None
) -> str:
    """构造单批（5章）章节梗概的用户查询。batch_start, batch_end 含首含尾，如 1,5 表示第1-5章。"""
    ch_count = batch_end - batch_start + 1
    parts = [
        f"请为《重生复仇短剧》生成**第{batch_start}章到第{batch_end}章**共{ch_count}章的详细梗概。"
        "必须逐章写出，不要用跨章形式（如第X-XX章）。",
        "",
        "【本批特殊要求】",
    ]
    if batch_start == 1:
        parts.append("- **第1章**：只写上一世临死前的场景（ICU、被网暴、被亲人放弃抢救、被男人背叛），激发读者兴趣，本章不写这一世。")
        parts.append("- **第2-5章**：这一世，重生确认、暗中记仇、开始布局，穿插支线复仇（如某件小背锅→直接告发），约每2章有一次支线爽感。")
    else:
        parts.append(f"- 全部为**这一世**内容，穿插支线复仇，约每2章有一次支线爽感（如项目背锅→告发、年会陷害→反杀）。")
        parts.append("- 主线大复仇最晚在第97章结束。")
    parts.extend([
        "",
        "【格式】每章格式：第N章 ：标题：内容。后面2~4句详细梗概。",
        "【类型】都市职场复仇+医疗阴谋揭露+舆论反转，禁止黑帮/杀手/肉搏。",
    ])
    if prior_summary:
        parts.extend(["", "【前情摘要】（前文已发生的内容，本批需承接）", prior_summary])
    return "\n".join(parts)


def generate_outline_batch(
    batch_start: int, batch_end: int, prior_summary: str,
    system_prompt: str, adapted_samples=None
) -> str:
    """生成单批章节梗概，返回该批的纯文本。"""
    user_query = build_batch_chapter_user_query(batch_start, batch_end, prior_summary, adapted_samples)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query},
    ]
    return call_qianwen_api(messages)


def analyze_outline_for_prev_life(outline_text: str) -> str:
    """
    先分析全文梗概，总结：哪些章节需要上一世故事；哪些有支线；每章对应的上一世被欺负前提。
    返回分析结果文本，供后续分批生成上一世梗概时使用。
    """
    prompt = (
        "请阅读下面《重生复仇短剧》的整本章节梗概，完成以下分析任务：\n\n"
        "1. 第1章：整章为上一世临死场景，对应线索=临死时遭遇的具体屈辱（ICU、被抛弃、被背叛等）。\n"
        "2. 第2章及以后：每章为这一世情节。请逐章标注：\n"
        "   - 本章是否有支线复仇（如项目背锅→告发、年会陷害→反杀等）或主线/其他情节；\n"
        "   - 若有支线或复仇，对应的「上一世被欺负/被陷害」的前提是什么（具体事件）。\n"
        "3. 输出格式简洁，每章一行，例如：\n"
        "   第3章：支线-项目背锅告发，上一世前提=被赵明轩当众甩锅\n"
        "   第5章：支线-年会陷害反杀，上一世前提=被李娜伪造证据诬陷\n"
        "   第7章：主线推进，上一世前提=曾在此场景被冷落/拒绝\n\n"
        "【整本章节梗概】\n"
        + outline_text[:15000] + ("\n...（已截断）" if len(outline_text) > 15000 else "") +
        "\n\n请输出第1章到第100章的分析，每章一行，不要其他内容。"
    )
    messages = [
        {"role": "system", "content": "你是重生复仇短剧的故事分析师。根据章节梗概，总结每章是否需要上一世线索、支线内容、上一世被欺负前提。"},
        {"role": "user", "content": prompt},
    ]
    return call_qianwen_api(messages) or ""


def build_prev_life_batch_user_query(
    outline_text: str, analysis_text: str, batch_start: int, batch_end: int
) -> str:
    """构造单批上一世梗概的用户查询。依据分析结果，为 batch_start 到 batch_end 章生成对应的上一世完整故事梗概。"""
    analysis_section = (
        f"【分析结果（已根据全文梗概总结）】\n{analysis_text}\n\n"
        if analysis_text and analysis_text.strip()
        else ""
    )
    return (
        "下面是《重生复仇短剧》的整本章节梗概，以及根据梗概分析出的「每章需上一世故事、支线内容、上一世被欺负前提」。\n\n"
        + analysis_section
        + f"请**严格按照分析结果**，仅为第{batch_start}章到第{batch_end}章，生成对应的「上一世完整故事梗概」。\n\n"
        + "要求：\n"
        "1. 每章一个线索点，格式：第X章对应线索：具体场景化的上一世遭遇描述（对应今生第X章）\n"
        "2. 第1章：本章为上一世临死，线索=临死时的具体屈辱（ICU、被抛弃、被背叛、医生冷漠等）\n"
        "3. 第2章及以后：根据分析中的「上一世前提」和该章这一世情节，写出上一世被欺负/被陷害的完整故事梗概（具体场景+行为+人物+伤害）\n"
        "4. 线索必须具体场景化，禁止抽象情绪；上一世是彻底失败的一生\n\n"
        "【整本章节梗概】\n" + outline_text[:10000] + ("\n...（已截断）" if len(outline_text) > 10000 else "") +
        f"\n\n请只输出第{batch_start}章到第{batch_end}章对应的上一世线索点，不要其他内容。"
    )


def _summarize_outline_for_context(text: str, max_chars: int = 1500) -> str:
    """将已生成的梗概压缩为前情摘要，供下一批参考。"""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return ""
    combined = "\n".join(lines)
    if len(combined) <= max_chars:
        return combined
    return combined[:max_chars] + "\n...（已省略后续）"


def generate_outline_rebirth_revenge(use_batch: bool = True, batch_size: int = 5):
    """为《重生复仇短剧》生成整本 100 章梗概 + 每一章对应的上一世遭遇线索点，并写入项目根目录 outputs/

    use_batch: 若 True，则分批生成（每批 batch_size 章）；若 False，则一次性生成100章（兼容旧逻辑）。
    batch_size: 每批章节数，默认 5。
    """
    project_name = "重生复仇短剧"
    # 一次性生成的用户查询（兼容 use_batch=False）
    user_query_one_shot = (
        "请为一部现代都市背景的《重生复仇短剧》设计整本**严格100章**的详细章节梗概，"
        "**必须从第1章写到第100章，一章都不能少！**"
        "\n\n"
        "【结构硬约束】"
        "**只有第1章**完全描写上一世临死前的场景（ICU、被网暴、被亲人放弃抢救、被男人背叛）；"
        "**第2章起全部进入这一世**，不得再写纯上一世章节。"
        "\n\n"
        "**支线穿插**：不能全篇只为一条主线走，必须穿插支线（如上一世被背黑锅的项目→这一世直接告发复仇）。"
        "约每2章有一次支线复仇爽感，不能把所有爽感堆在最后。主线大复仇最晚在第97章结束。"
        "\n\n"
        "**类型**：都市职场复仇+医疗阴谋揭露+舆论反转。复仇手段：职场反杀、证据曝光、舆论操控、法律追责、资本博弈。"
        "紧扣'重生'主题，每章有'上一世记忆对照'和'今生提前布局'，穿插支线小故事。"
    )

    print("=" * 60)
    print(f"为项目《{project_name}》生成整本 100 章梗概 + 每一章对应的上一世遭遇线索点")
    print("=" * 60)

    # 1）RAG：从通用样本中找出与“重生复仇 + 委屈 + 爽文”高度相关的片段
    print("加载通用样本，检索高情绪样本中...")
    adapted_samples = search_and_adapt_samples(
        user_input=user_query_one_shot,
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

    # 3）生成章节梗概（分批 或 一次性）
    outline_text = None
    if use_batch:
        print(f"\n📋 分批生成章节梗概（内部每次调用生成 {batch_size} 章，共 20 次，最终输出 100 章）...\n")
        outline_parts = []
        prior_summary = ""
        for batch_idx in range(0, 100, batch_size):
            start = batch_idx + 1
            end = min(batch_idx + batch_size, 100)
            print(f"  生成第 {start}-{end} 章...")
            batch_text = generate_outline_batch(start, end, prior_summary, system_prompt, adapted_samples)
            if not batch_text or batch_text.startswith("通义千问"):
                print(f"  ⚠ 第 {start}-{end} 章生成失败，将使用占位")
                batch_text = "\n".join([f"第{ch}章 ：（生成失败，待补充）" for ch in range(start, end + 1)])
            outline_parts.append(batch_text)
            prior_summary = _summarize_outline_for_context("\n\n".join(outline_parts), max_chars=2000)
        outline_text = "\n\n".join(outline_parts)
        chapter_count, _ = count_chapters(outline_text)
        print(f"\n✅ 章节梗概分批生成完成，共 {chapter_count} 章")
    else:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query_one_shot},
        ]
        print("\n开始调用通义千问生成整本 100 章梗概，这可能需要几十秒...\n")
        max_retries = 3
        for attempt in range(max_retries):
            outline_text = call_qianwen_api(messages)
            is_valid, issues, chapter_count = validate_outline(outline_text or "", min_chapters=100)
            print(f"章节梗概验证（尝试 {attempt + 1}/{max_retries}）：{chapter_count} 章")
            if is_valid:
                break
            if attempt < max_retries - 1:
                user_query_one_shot = (
                    f"请重新生成，必须确保输出完整的100章（当前只有{chapter_count}章）。"
                    "必须从第1章写到第100章，一章都不能少。"
                )
                messages[1]["content"] = user_query_one_shot
    
    if outline_text is None or not outline_text.strip():
        print("❌ 生成失败，请检查API配置或网络连接。")
        return

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

    # 5）在整本章节梗概的基础上，为每一章生成对应的「上一世遭遇线索点」
    # 流程：先生成章节梗概 → 分析全文（哪些章需上一世、支线、被欺负前提）→ 分批生成上一世梗概
    print("\n" + "=" * 60)
    print("开始在整本章节梗概基础上，生成『上一世遭遇线索点』...")
    print("=" * 60 + "\n")

    prev_life_system_prompt = build_prev_life_outline_system_prompt()
    max_retries = 3

    if use_batch:
        # 第一步：分析全文梗概，总结哪些章需上一世、支线内容、上一世被欺负前提
        print("  [1/2] 分析全文梗概（每章需上一世故事、支线、被欺负前提）...")
        analysis_text = analyze_outline_for_prev_life(outline_text)
        if analysis_text and not analysis_text.startswith("通义千问"):
            print("  ✅ 分析完成")
        else:
            print("  ⚠ 分析失败，将不携带分析结果继续生成")
            analysis_text = ""
        # 第二步：分批生成上一世线索（每批 batch_size 章，共 20 次调用）
        print(f"  [2/2] 分批生成上一世线索（每批 {batch_size} 章，共 20 次）...\n")
        prev_life_parts = []
        for batch_idx in range(0, 100, batch_size):
            start = batch_idx + 1
            end = min(batch_idx + batch_size, 100)
            print(f"    生成第 {start}-{end} 章对应的上一世故事梗概...")
            user_q = build_prev_life_batch_user_query(outline_text, analysis_text, start, end)
            messages = [
                {"role": "system", "content": prev_life_system_prompt},
                {"role": "user", "content": user_q},
            ]
            batch_out = call_qianwen_api(messages)
            if batch_out and not batch_out.startswith("通义千问"):
                prev_life_parts.append(batch_out.strip())
            else:
                prev_life_parts.append("\n".join([f"第{ch}章对应线索：（生成失败，待补充）" for ch in range(start, end + 1)]))
        prev_life_text = "\n\n".join(prev_life_parts)
    else:
        prev_life_user_query = (
            "下面是这本《重生复仇短剧》的整本章节/阶段梗概，请你在充分理解的基础上，"
            "根据我之前给出的要求，为每一章生成对应的「上一世遭遇线索点」。"
            "这些线索点是隐式的，不是完整的故事章节梗概，而是简短的遭遇描述。"
            "要求："
            "1. 必须为整本书的每一章（共100章）生成一个对应的线索点。"
            "2. 每个线索点应该描述她在上一世在类似情况下或类似事件中受到的委屈、屈辱、背叛等遭遇。"
            "3. 每个线索点必须明确标注对应的今生章节（对应今生第X章）。"
            "4. 线索点应该简洁明了（1-3句话），方便在生成正文时作为回忆片段引用。"
            "5. 注意强化委屈、屈辱、冤枉、愤怒、怨恨等负面情绪。"
            "\n\n【整本章节梗概如下】\n"
            + outline_text
        )
        prev_life_messages = [
            {"role": "system", "content": prev_life_system_prompt},
            {"role": "user", "content": prev_life_user_query},
        ]
        prev_life_text = None
        for attempt in range(max_retries):
            prev_life_text = call_qianwen_api(prev_life_messages)
            is_valid, issues, clue_count = validate_prev_life_clues(prev_life_text or "", min_clues=100)
            print(f"上一世线索验证（尝试 {attempt + 1}/{max_retries}）：{clue_count} 条")
            if is_valid:
                break
            if attempt < max_retries - 1:
                correction_prompt = ""
                if clue_count < 100:
                    correction_prompt += f"必须输出完整的100条线索（当前只有{clue_count}条），从第1章到第100章，一条都不能少。"
                if issues:
                    for issue in issues:
                        if "今生视角" in issue:
                            correction_prompt += " 所有线索必须是上一世视角。"
                        if "今生成就" in issue or "成就回顾" in issue:
                            correction_prompt += " 上一世是彻底失败的一生，禁止成功、获奖、掌声等。"
                        if "被动感知" in issue:
                            correction_prompt += " 禁止'看到新闻''听到讨论'等被动感知，必须是发生在她身上的具体事件。"
                        if "抽象情绪" in issue:
                            correction_prompt += " 必须具体场景化。"
                prev_life_user_query = "【修正要求】" + correction_prompt + "\n\n【整本章节梗概如下】\n" + outline_text
                prev_life_messages[1]["content"] = prev_life_user_query
    
    if prev_life_text is None or not prev_life_text.strip():
        print("❌ 上一世线索生成失败，请检查API配置或网络连接。")
        return

    # 6）保存「上一世遭遇线索点」到单独文件，并做时间戳备份
    prev_life_main_path = os.path.join(OUTPUT_DIR, "prev_life_ctx.txt")
    prev_life_backup_path = os.path.join(OUTPUT_DIR, f"prev_life_ctx_{timestamp}.txt")

    with open(prev_life_main_path, "w", encoding="utf-8") as f:
        f.write(prev_life_text)

    with open(prev_life_backup_path, "w", encoding="utf-8") as f:
        f.write(prev_life_text)

    print(f"✅ 上一世遭遇线索点生成完成，已写入：{prev_life_main_path}")
    print(f"📝 已自动备份一份到：{prev_life_backup_path}")
    print("\n上一世遭遇线索点前 20 行预览：\n")
    for i, line in enumerate(prev_life_text.splitlines()[:20], 1):
        print(f"{i:02d}: {line}")


def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description="重生复仇短剧：生成100章梗概 + 上一世线索")
    parser.add_argument("--no-batch", action="store_true", help="不使用分批，一次性生成100章（兼容旧逻辑）")
    parser.add_argument("--batch-size", type=int, default=5, help="每批生成章节数（默认5）")
    args = parser.parse_args()
    generate_outline_rebirth_revenge(use_batch=not args.no_batch, batch_size=args.batch_size)


if __name__ == "__main__":
    main()


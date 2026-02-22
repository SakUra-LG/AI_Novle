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

【结构要求】
1）前世篇（第1-3章，共3章）
   - 只写上一世的内容：被全网骂、被亲人放弃抢救、被男人背叛，被医生冷漠对待等。
   - 重点是「极致委屈」和「读者替她不值、想骂人的那种愤怒」。
   - 每一章都要有具体场景（比如 ICU 病房、网络直播间、家庭争吵、公司甩锅会议），让读者记住具体的屈辱细节。

2）重生开局（第4-10章，共7章）
   - 写她确认自己重生、重新面对同一张早餐桌、同一家公司、同一批亲戚和渣男。
   - 她一边装乖顺、装不记得，一边暗中观察和记仇，开始记录"上一世是谁怎么害她的"，并迅速在这一世提前插手、暗中报复。
   - 每章都要有小故事穿插，同时推进大目标（收集证据、布局复仇）。

3）复仇主线第一阶段：职场小角色（第11-25章，共15章）
   - 复仇对象：职场小角色、同事、小领导
   - 每章都要有：今生事件 → 上一世记忆对照 → 提前布局反杀
   - 包含多个小故事：项目甩锅、年会陷害、财务栽赃、客户抢单等
   - 大目标推进：收集职场证据链，为后续大反杀做准备

4）复仇主线第二阶段：核心仇人（第26-50章，共25章）
   - 复仇对象：赵明轩（上司）、林修远（渣男未婚夫）、江晚晴（白月光闺蜜）、家族长辈
   - 每章都要有：今生事件 → 上一世记忆对照 → 提前布局反杀
   - 包含多个小故事：订婚宴反转、家族会议对峙、商业合作陷阱、舆论战等
   - 大目标推进：逐步揭露医疗事故的初步线索，发现医院有问题

5）复仇主线第三阶段：医疗真相（第51-75章，共25章）
   - 复仇对象：医院管理层、资本集团、医疗事故相关责任人
   - 每章都要有：今生调查 → 上一世记忆对照 → 发现新线索 → 布局反击
   - 包含多个小故事：档案调查、医生访谈、证据收集、网络曝光等
   - 大目标推进：层层揭示医疗阴谋，每10-15章揭开一层真相（手术报告被篡改 → 医院董事会资本控股 → 主刀医生账户异常 → 匿名组织与林修远有关 → 发现她不是唯一受害者）

6）复仇主线第四阶段：终极黑幕（第76-97章，共22章）
   - 复仇对象：主刀医生、幕后资本链、最终黑手
   - 每章都要有：今生对决 → 上一世记忆对照 → 终极反杀
   - 包含多个小故事：证据链完善、法律追责、舆论大反转、资本博弈等
   - 大目标推进：彻底揭露"故意让她死"的医疗阴谋，牵出更大利益链

7）终局篇（第98-100章，共3章）
   - 重点放在「上一世医疗事故 / 手术台抛弃她」背后真正的终极黑幕大反转
   - 找到当年的主刀医生，发现对方并非普通失误，而是带有明确动机、甚至收钱"故意让她死"，牵出更大的利益链
   - 终局依旧以复仇和真相反转为核心情绪高潮，允许她赢得彻底的情绪大爽（仇人垮台、真相直播、舆论反噬）
   - **不要写大段"放下仇恨""重建人生道路""正能量励志成长""成立基金会做公益""成为女性楷模"之类的内容**

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


def generate_outline_rebirth_revenge():
    """为《重生复仇短剧》生成整本 100 章梗概 + 每一章对应的上一世遭遇线索点，并写入项目根目录 outputs/"""
    project_name = "重生复仇短剧"
    user_query = (
        "请为一部现代都市背景的《重生复仇短剧》设计整本**严格100章**的详细章节/阶段梗概，"
        "**必须从第1章写到第100章，一章都不能少！**"
        "\n\n"
        "前 2-3 章只写上一世被冤枉、被网暴、被抛弃抢救的极致委屈，重点写清楚她上一世具体是怎么被害死的；"
        "后面章节写她重生之后一步步提前报复、每次复仇前都勾连上一世具体委屈记忆，再完成当场反杀，整体必须是节奏快、冲突密集、每章都有爽点或反转的爽文风格。"
        "\n\n"
        "**类型要求：必须是都市职场复仇 + 医疗阴谋揭露 + 舆论反转，禁止写成黑帮动作、杀手战斗、直接肉搏等类型。**"
        "复仇手段以：职场反杀、证据曝光、舆论操控、法律追责、资本博弈为主，不是物理战斗。"
        "\n\n"
        "中后段可以使用「第7-17章 对敌人的第一次反击」这类阶段形式来概括一整段对敌行动，但**必须确保总章节数严格等于100章**。"
        "紧扣'重生'主题，每章都要有'上一世记忆对照'和'今生提前布局'的双线结构，中间要有很多细小的小故事穿插，总体又有一个大的故事目标（揭露医疗阴谋）。"
        "\n\n"
        "直到大结局之前，都要紧紧围绕重生复仇主线推进，尤其是终局要设计一个对整本书情节影响巨大的终极反转，例如找到当年的主刀医生并揭穿他故意让她死、背后还有更大利益链；"
        "不要写成单纯的都市职场/商业成功、放下仇恨去做公益、励志正能量成长故事。"
    )

    print("=" * 60)
    print(f"为项目《{project_name}》生成整本 100 章梗概 + 每一章对应的上一世遭遇线索点")
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
    
    # 3.1）生成并验证章节梗概，如果不符合要求则重生成
    max_retries = 3
    outline_text = None
    for attempt in range(max_retries):
        outline_text = call_qianwen_api(messages)
        
        is_valid, issues, chapter_count = validate_outline(outline_text, min_chapters=100)
        
        print(f"\n{'='*60}")
        print(f"章节梗概验证结果（尝试 {attempt + 1}/{max_retries}）：")
        print(f"章节数量：{chapter_count} 章")
        
        if is_valid:
            print("✅ 章节梗概验证通过！")
            if issues:
                print("⚠️  警告信息：")
                for issue in issues:
                    print(f"   {issue}")
            break
        else:
            print("❌ 章节梗概验证未通过：")
            for issue in issues:
                print(f"   {issue}")
            
            if attempt < max_retries - 1:
                print(f"\n正在重生成（第 {attempt + 2} 次尝试）...")
                # 在用户查询中添加更严格的提示
                user_query = (
                    f"请重新生成，必须确保输出完整的100章（当前只有{chapter_count}章）。"
                    "必须从第1章写到第100章，一章都不能少。"
                    "类型必须是都市职场复仇+医疗阴谋揭露，禁止写成黑帮动作、杀手战斗等类型。"
                    "可以使用章节跨度（如第X-XX章），但必须确保总章节数严格等于100章。"
                )
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query},
                ]
            else:
                print("\n⚠️  已达到最大重试次数，将使用当前结果，但请注意章节数量不足的问题。")
    
    if outline_text is None:
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
    print("\n" + "=" * 60)
    print("开始在整本章节梗概基础上，为每一章生成对应的『上一世遭遇线索点』...")
    print("=" * 60 + "\n")

    prev_life_system_prompt = build_prev_life_outline_system_prompt()

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

    # 5.1）生成并验证上一世线索，如果不符合要求则重生成或修正
    prev_life_text = None
    for attempt in range(max_retries):
        prev_life_text = call_qianwen_api(prev_life_messages)
        
        is_valid, issues, clue_count = validate_prev_life_clues(prev_life_text, min_clues=100)
        
        print(f"\n{'='*60}")
        print(f"上一世线索验证结果（尝试 {attempt + 1}/{max_retries}）：")
        print(f"线索数量：{clue_count} 条")
        
        if is_valid:
            print("✅ 上一世线索验证通过！")
            if issues:
                print("⚠️  警告信息：")
                for issue in issues:
                    print(f"   {issue}")
            break
        else:
            print("❌ 上一世线索验证未通过：")
            for issue in issues:
                print(f"   {issue}")
            
            if attempt < max_retries - 1:
                print(f"\n正在重生成（第 {attempt + 2} 次尝试）...")
                # 构建修正提示
                correction_prompt = ""
                if clue_count < 100:
                    correction_prompt += f"必须输出完整的100条线索（当前只有{clue_count}条），从第1章到第100章，一条都不能少。"
                if any("今生视角" in issue for issue in issues):
                    correction_prompt += "所有线索必须是'上一世'视角，禁止写成'今生'视角。禁止使用'她面对'、'她直面'、'她决定'等今生行为描述。"
                if any("今生成就回顾" in issue or "今生成就" in issue for issue in issues):
                    correction_prompt += "【严重错误修正】上一世是彻底失败的一生，所有反抗必须失败或被压制。绝对禁止出现：成功、翻案、获奖、表彰、掌声、国际新闻、联合国、颁奖典礼、舞台掌声、发布会（成功）、媒体报道她成功、粉丝留言、观众鼓掌、'你是我们的英雄'等今生成就回顾内容。如果涉及媒体、机构或社会层面，只能是：拒绝她、无视她、封锁消息、篡改报道、威胁撤稿、调查被终止。"
                if any("被动感知" in issue for issue in issues):
                    correction_prompt += "【信息密度修正】禁止大量使用'看到新闻'、'听到讨论'、'看到报道'、'听到有人说'等被动感知。线索必须是'上一世发生在她身上的具体事件'（场景+行为+人物+伤害），而不是'她被动感知社会氛围'。例如：不是'她在网上看到一段视频'，而是'她在公司会议室里，赵明轩当众把财务漏洞甩到她身上'。"
                if any("抽象情绪" in issue for issue in issues):
                    correction_prompt += "每个线索必须具体场景化，包含：具体场景（在哪里）+ 具体行为（谁做了什么）+ 具体人物（涉及谁）+ 具体伤害（哪句话/哪个动作）。禁止使用'她感到'、'她觉得'、'她想起那些日子'等抽象情绪描述。"
                
                prev_life_user_query = (
                    "下面是这本《重生复仇短剧》的整本章节/阶段梗概，请你在充分理解的基础上，"
                    "根据我之前给出的要求，为每一章生成对应的「上一世遭遇线索点」。"
                    "\n\n【修正要求】\n"
                    + correction_prompt +
                    "\n\n【整本章节梗概如下】\n"
                    + outline_text
                )
                
                prev_life_messages = [
                    {"role": "system", "content": prev_life_system_prompt},
                    {"role": "user", "content": prev_life_user_query},
                ]
            else:
                print("\n⚠️  已达到最大重试次数，将使用当前结果，但请注意线索质量问题。")
    
    if prev_life_text is None:
        print("❌ 生成失败，请检查API配置或网络连接。")
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
    generate_outline_rebirth_revenge()


if __name__ == "__main__":
    main()


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
事件簇生成脚本 V2（重生复仇短剧）

职责：
1）先为整本书生成唯一的「最大复仇主线蓝图」（全书大目标），写入 outputs/global_seed_plan_v2.txt；
2）在蓝图约束下，生成事件簇列表（与旧版 event_clusters.json 结构兼容）；
3）对前两章做语义语法级兜底（固定 chapter_span），其余 chapter_span/文本尽量保持模型输出稳定，不再随机二次改写；
4）将完整事件簇写入 outputs/event_clusters_v2.json，供后续梗概脚本 V2 使用。
"""

import os
import json
import random
from datetime import datetime
from typing import List, Dict, Any

import dashscope

from smart_sample_search import search_and_adapt_samples


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "outputs")


API_Key_QW = "sk-a2966f4e37134351904851679884cb67"
MAX_TOKENS = 8192

# 在 V2 流程中统一锁定男女主姓名，后续所有脚本与模型提示都复用这一对名字
HEROINE_NAME = "沈清欢"
HERO_NAME = "顾寒川"

DEFAULT_FORBIDDEN_NEW_ROLES = [
    "神秘援手", "神秘司机", "系统", "系统提示音", "苏晚晴", "黑色轿车", "神秘人",
    "幕后黑手", "更大风暴", "真正的敌人", "神秘男人", "陌生女性盟友", "未规划的关键证人",
]

SPECIAL_CHAPTER_PLAN: Dict[int, Dict[str, Any]] = {
    1: {
        "role": "prev_life_death_only",
        "goal": "只写上一世病房临死前的绝境，不出现重生后的正式苏醒，也不出现任何调查/照片/身份谜团。",
        "must_include": [
            "深夜病房环境和监护仪报警",
            "求助被医护/亲人无视或敷衍",
            "陆景明与相关医护冷漠配合或敷衍安抚",
            "最后一通电话被挂断或无人接听",
        ],
        "must_not_include": [
            "重生醒来或从病床上“突然坐起”",
            "任何现代场景中的调查/线索分析",
            "照片/U盘/神秘人/系统/幕后黑手",
            "身份替换/车祸新闻/警方介入",
        ],
        "ending": "在窒息和绝望中逐渐失去意识，意识到自己要死了但还不知道会重来一次。",
        "must_resolve_this_chapter": ["上一世临死场景闭合"],
    },
    2: {
        "role": "rebirth_awakening_only",
        "goal": "只写重生惊醒与确认时间回到悲剧前夜，从震惊→怀疑是梦→通过具体证据确认“真的回去了”。",
        "must_include": [
            "从上一章病房死亡记忆中惊醒",
            "发现自己回到熟悉房间/时间点",
            "通过日期、手机、亲友状态等细节确认时间回溯",
            "决定这一次不会再轻信任何人",
        ],
        "must_not_include": [
            "直播/警方/媒体报道",
            "更大势力/幕后阴谋的正式展开",
            "非法实验/身份替换/系统提示音",
            "正式举报或真正意义上的复仇行动",
        ],
        "ending": "她在确认“这不是梦”后，把第一个可疑细节记在心里，决定先沉住气观察身边所有人。",
        "must_resolve_this_chapter": ["确认回到悲剧前夜闭合"],
    },
}


def call_qianwen_api(messages, temperature=0.8, top_p=0.85, repetition_penalty=1.05):
    """调用通义千问 API，返回纯文本内容。"""
    dashscope.api_key = API_Key_QW
    try:
        resp = dashscope.Generation.call(
            model=dashscope.Generation.Models.qwen_turbo,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            result_format="message",
            max_tokens=MAX_TOKENS,
        )
        if "output" in resp and "choices" in resp["output"]:
            content = resp["output"]["choices"][0]["message"]["content"]
            return content.replace("```", "").strip()
        return f"通义千问 API 返回了无效格式: {resp!r}"
    except Exception as e:  # noqa: BLE001
        return f"调用通义千问 API 出错: {e}"


def generate_global_seed_plan_v2() -> str:
    """
    生成整本书唯一的「最大复仇主线蓝图」，并落盘为文本文件。
    """
    print("📌 正在生成整本书的『最大复仇主线蓝图 V2』...")

    base_query = (
        f"重生复仇短剧，女主{HEROINE_NAME}，男主{HERO_NAME}，"
        "现代都市+医疗阴谋+职场反杀，极致委屈+高密度爽点。"
    )
    adapted_samples = search_and_adapt_samples(
        user_input=base_query,
        target_context="重生、复仇、现代都市、医疗、爽文、短剧",
        top_k=5,
        min_similarity=0.3,
    )

    sample_texts = []
    for i, s in enumerate(adapted_samples or [], 1):
        sample_texts.append(
            f"【样本{i}】情绪：{', '.join(s.get('emotion_tags', []))}；"
            f"情节：{', '.join(s.get('plot_tags', []))}；"
            f"节选：{(s.get('content') or '')[:120]}..."
        )
    samples_block = "\n\n".join(sample_texts) if sample_texts else ""

    system_prompt = (
        "你是重生复仇短剧的大纲总策划，需要先为整本书设计唯一的最大复仇主线蓝图。"
    )
    user_prompt = (
        f"请为一部现代都市背景的《重生复仇短剧》设计一条**唯一的、贯穿全书 100 章的最大复仇主线蓝图 V2**，用 3-6 句话概括。\n\n"
        "要求：\n"
        f"- 明确并固定男女主姓名：女主名必须固定为「{HEROINE_NAME}」，男主名必须固定为「{HERO_NAME}」，后续所有事件簇、章节卡和正文中都只能使用这两个名字指代男女主（可以有称呼/外号，但正式点名时必须写出全名，不得更换为其他姓名）；\n"
        "- 明确上一世害死女主的关键参与者（如：渣男丈夫/未婚夫、主治医生/院方、背后资本集团等）及其相互关系；\n"
        "- 明确今生的最大复仇目标（例如：查清并摧毁这条“收钱杀人”的医疗利益链，让相关各方在公众面前共同崩盘）；\n"
        "- 给出主线大致推进顺序（例如：先婚姻/家族线→再职场线→再医疗线→最后资本与舆论决战），无需细节，只要清晰的阶段划分；\n"
        "- 全书只能存在这一条最大主线，后续的事件簇只能在此蓝图之上补充细节和证据，**不能另起新 Boss、不能改世界观设定**。\n\n"
        "如果有样本，可以参考其情绪与节奏风格，但不要抄写情节：\n"
        f"{samples_block}\n\n"
        "请只输出这条蓝图本身，不要额外解释。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    plan = call_qianwen_api(messages)
    if not plan or plan.startswith("通义千问"):
        print("⚠️ 生成最大复仇主线蓝图失败，将返回占位蓝图。")
        plan = (
            "占位蓝图：上一世，沈清欢被渣男丈夫、医院黑心医生和背后资本集团联合害死；"
            "今生她誓要查清医疗事故真相，打掉这条利用病人牟利的利益链，"
            "依次从婚姻/家族、职场、医疗体系到资本与舆论，一步步让所有参与者在公众面前崩盘。"
        )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, "global_seed_plan_v2.txt")
    # 在文件开头显式写入男女主姓名，确保后续脚本与人工检查可以直接读取
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"女主：{HEROINE_NAME}\n男主：{HERO_NAME}\n\n")
        f.write(plan.strip())
    print(f"✅ 最大复仇主线蓝图 V2 已写入：{path}")
    return plan.strip()


def build_event_cluster_prompt(global_seed_plan: str) -> str:
    """构造事件簇生成的用户提示词（V2），要求产出结构化 JSON。"""
    return (
        "下面是《重生复仇短剧》的整本最大复仇主线蓝图：\n\n"
        f"{global_seed_plan}\n\n"
        "请在此蓝图约束下，为整本书设计一份【事件簇总走线 V2】（按事件簇而不是按章节思考）。\n\n"
        "要求：\n"
        "1. 将全书拆分为若干个事件簇（建议 10〜25 个，每簇 2〜8 章左右），每个簇围绕一个**相对独立且完整的冲突+反杀闭环**展开，要符合短剧节奏，一个簇就是一组“上一世被打压 → 今世反杀”的爽文小故事；\n"
        "2. 每个事件簇必须包含下列字段，并且【上一世受害 → 信息差 → 今世反击】三者之间要形成因果链，而不是彼此无关：\n"
        "   - cluster_id：字符串，形如 EC01, EC02...\n"
        "   - name：简短标题\n"
        "   - arc_id：所属大弧线ID，可用 A01/A02/A03 等粗分（例如：婚姻/家族线、职场线、医疗线、资本与舆论线）\n"
        "   - core_payoff：本簇最核心的“爽点/反杀结果”一句话\n"
        "   - chapter_span：[起始章, 结束章]，例如 [3, 5]\n"
        "   - main_opponent：本簇的主要对手（可以是个人或机构）\n"
        "   - escalation_level：1~3 的整数，1=中小型冲突，3=重大阶段性爆点\n"
        "   - prev_life_tragedy：对应上一世的典型悲剧前提，要写清楚【这一拨人/这一场局具体是怎么害她的、用了什么套路】，不能只写抽象情绪；\n"
        "   - info_gap_from_prev_life：由于上一世的受打击/委屈，她在临死前或重生后额外掌握了哪些别人不知道的关键信息、暗线或漏洞（“信息差”），要从 prev_life_tragedy 里自然“生长出来”，例如：她在被害过程中无意听到的秘密对话、看到的账目、记住的时间节点或密码等——要写清楚她具体知道了什么、别人为什么不知道；\n"
        "   - this_life_revenge：今生在本簇中大致如何反杀，必须**显式写出：因为上一世遭遇了上述陷害/毒害，她记住了 info_gap_from_prev_life 中这些细节，所以这一世才能提前踩准对方的布局反打回去**；\n"
        "   - cluster_outcome：本簇结束时的结果与对后续的影响\n"
        "   - summary：2~3 句对本簇从“酝酿→爆发→收尾”的简要说明\n"
        "   - notes：数组，补充任何写作提醒\n\n"
        "3. 所有簇中出现的男女主称呼必须与主线蓝图一致：女主只能叫「"
        f"{HEROINE_NAME}"
        "」，男主只能叫「"
        f"{HERO_NAME}"
        "」，不得另起其他姓名（可以有“他”“她”等代词和基于这两个姓名衍生的称呼，但不要额外造新名字）。\n"
        "4. 各个事件簇之间不需要强行做复杂勾连，只需在大主线蓝图不矛盾的前提下，让每个簇自身的“上一世被这拨人害惨了 + 因为记住了他们的套路/漏洞而在今世成功反杀”形成完整小闭环即可；不要为了推进终极 Boss 而牺牲单簇的爽感完整度。\n"
        "5. 每个簇的 summary 也要沿用这条逻辑：简短说明这一簇里她是如何先被同一批人/同一种手法坑过一遍，然后又借着对这些手法的熟悉和信息差，在今世反杀回去；禁止写成与上一世完全无关的职场升级/恋爱日常。\n"
        "6. 请直接输出 JSON 数组（顶层是 list），其中每个元素是一个事件簇对象，字段名用英文 key，字符串内容为中文。\n"
        "7. 严格保证 chapter_span 不重叠且覆盖 1~100 章的主要剧情（允许个别章节作为跨簇过渡，但不要出现完全空档）。\n"
        "8. 不要额外解释，不要输出 markdown，只输出干净的 JSON。"
    )


def generate_event_clusters_v2(global_seed_plan: str) -> List[Dict[str, Any]]:
    """基于全书蓝图，生成事件簇列表（V2），并返回 Python 对象。"""
    print("\n📌 正在生成『事件簇总走线 V2』...\n")
    user_prompt = build_event_cluster_prompt(global_seed_plan)
    messages = [
        {
            "role": "system",
            "content": "你是重生复仇短剧的结构设计师，需要在给定的主线蓝图下，设计全书的事件簇列表，并以 JSON 输出。",
        },
        {"role": "user", "content": user_prompt},
    ]
    raw = call_qianwen_api(messages, temperature=0.85, top_p=0.9)
    if not raw or raw.startswith("通义千问"):
        print("⚠️ 事件簇生成失败，将返回空列表。原始输出：", raw[:200] if isinstance(raw, str) else raw)
        return []

    # 简单清洗：去掉可能残留的说明文字，只保留第一个以 '[' 开头到最后一个 ']' 的片段
    text = raw.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 解析事件簇 JSON 失败: {e}，原始文本前 300 字：\n{text[:300]}")
        return []

    if not isinstance(data, list):
        print("⚠️ 事件簇 JSON 顶层不是数组，将返回空列表。")
        return []

    print(f"✅ 已生成 {len(data)} 个事件簇（V2）")
    return data


def _choose_template_for_cluster(cluster: Dict[str, Any], stats: Dict[str, int]) -> str:
    """
    为单个事件簇选择结构模版 M1~M5。

    这里只做简单启发式：依据章节跨度和升级等级，控制大致比例。
    更复杂的分布（例如基于 arc_id）可日后再调。
    """
    import random

    span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters")
    try:
        s, e = int(span[0]), int(span[1])
        length = max(1, e - s + 1)
    except Exception:  # noqa: BLE001
        length = 3
    escalation = int(cluster.get("escalation_level") or 1)

    # 候选模版初始化
    candidates: List[str] = []

    if length <= 2:
        candidates = ["M2", "M4", "M5"]
    elif length == 3:
        candidates = ["M1", "M3", "M4"]
    else:
        candidates = ["M1", "M3", "M2", "M5"]

    # 高升级事件尽量不用 M5
    if escalation >= 3 and "M5" in candidates:
        candidates.remove("M5")

    # 控制 M5 总比例不超过总簇数的约 20%
    total = max(1, stats.get("_total", 1))
    if stats.get("M5", 0) / total > 0.2 and "M5" in candidates:
        candidates.remove("M5")

    # 简单权重：M1、M2 优先，其次 M3/M4，最后 M5
    weights_map = {"M1": 3, "M2": 3, "M3": 2, "M4": 2, "M5": 1}
    weights = [weights_map.get(c, 1) for c in candidates]

    choice = random.choices(candidates, weights=weights, k=1)[0]
    stats[choice] = stats.get(choice, 0) + 1
    stats["_total"] = stats.get("_total", 0) + 1
    return choice


def attach_templates_to_clusters(clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """为每个事件簇附加 structure_template 字段，返回新的列表。"""
    stats: Dict[str, int] = {"_total": 0}
    for c in clusters:
        tmpl = _choose_template_for_cluster(c, stats)
        c["structure_template"] = tmpl
    print(
        "📊 模版使用统计：",
        {k: v for k, v in stats.items() if not k.startswith("_")},
    )
    return clusters


def _post_process_clusters(clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    对模型生成的事件簇做规则后处理：
    1）硬性固定：
       - 第 1 章：病房临终绝境场景（不能出现“上一世”“重生”“回忆”字样）；
       - 第 2 章：重获清晨的惊愕，没有实质复仇行动，重点是意识到自己“重来一次”的震惊感；
    2）从第 3 章开始：不再随机分配章节跨度，chapter_span 直接沿用模型生成；
    3）尽量把 prev_life_tragedy / this_life_revenge 写得更具体，方便后续模型理解（只补充文本，不重写结构跨度）。
    """
    if not clusters:
        return clusters

    # 至少保证有两个簇
    while len(clusters) < 2:
        idx = len(clusters) + 1
        clusters.append(
            {
                "cluster_id": f"EC{idx:02d}",
                "name": f"占位事件簇{idx}",
                "arc_id": "A01",
                "core_payoff": "",
                "chapter_span": [idx, idx],
                "main_opponent": "",
                "escalation_level": 1,
                "prev_life_tragedy": "",
                "this_life_revenge": "",
                "cluster_outcome": "",
                "summary": "",
                "notes": [],
            }
        )

    # ---------- 固定第 1 簇：病房临终绝境（禁止出现“上一世”“重生”“回忆”） ----------
    first = clusters[0]
    first["cluster_id"] = "EC01"
    first["chapter_span"] = [1, 1]
    # 避免关键词：仅描述“那一夜”的临终场景
    first["name"] = "病房绝境的最后一夜"
    first["arc_id"] = first.get("arc_id") or "A01"
    first["main_opponent"] = first.get("main_opponent") or "医院和亲近之人的合谋"
    first["escalation_level"] = max(2, int(first.get("escalation_level") or 2))
    first["core_payoff"] = (
        "读者亲眼见她在病房被一步步逼向生命尽头，所有证据被压下，"
        "连最后一次求助都被身边人冷漠堵死，情绪积压到极致。"
    )
    first["prev_life_tragedy"] = (
        "夜深的病房里，她高烧、失血、呼吸急促，监护仪一次次报警，却被当成小题大做。"
        "知情的医生和最信任的亲近之人互相配合，把关键检查单和录音彻底藏起，"
        "让她在痛苦与窒息中逐渐失去意识，直到再也无法开口说话。"
    )
    first["this_life_revenge"] = (
        "本簇只负责把她被一步步推向绝境的过程写到极致，"
        "让读者清楚记住是谁、在什么细节上做了什么手脚，为后面所有反击埋下情绪底色。"
    )
    first["cluster_outcome"] = (
        "她在冰冷的病床上独自熄灭，连最后一通电话都被挂断，"
        "所有人以为这场‘意外’会被当作普通的医疗失败，轻轻带过。"
    )

    # ---------- 固定第 2 簇：重获清晨的惊愕 ----------
    second = clusters[1]
    second["cluster_id"] = "EC02"
    second["chapter_span"] = [2, 2]
    second["arc_id"] = second.get("arc_id") or "A01"
    second["name"] = "骤然惊醒的陌生清晨"
    second["main_opponent"] = second.get("main_opponent") or "表面温柔实则算计的枕边人"
    second["escalation_level"] = int(second.get("escalation_level") or 1)
    second["core_payoff"] = (
        "她从窒息的黑暗中惊醒，发现自己还活着，时间停在一切悲剧彻底爆发前的关键时刻，"
        "每一个熟悉的细节都在提醒她，这不是梦。"
    )
    # 第二章不直接展开复仇，只承接记忆与震惊
    second["prev_life_tragedy"] = (
        "她的身体还残留着病房里的冰冷感和刺痛感，"
        "耳边仿佛还回响着监护仪急促的报警和争吵声，"
        "但睁开眼时，却看见自己完好地躺在旧房间里，那些‘未来才会发生’的细节都回到未发生之前。"
    )
    second["this_life_revenge"] = (
        "本簇只写她如何确认时间倒回、细数那些曾把自己推向死亡的细节，"
        "通过观察身边人的表情与话语，意识到这是一次重新选择命运的机会，"
        "但此时她还没真正动手，只是把所有人和所有漏洞重新在心里记了一遍。"
    )
    second["cluster_outcome"] = (
        "她确信自己不是做梦，时间还停在悲剧的前夜，"
        "决定这一次绝不再轻信任何人，把那些‘看似关心’的细节都当成潜在的刀锋记下。"
    )

    # ---------- 其余簇：保持模型生成的 chapter_span，不再随机改写 ----------
    # 注意：这里不再动 clusters[2:] 的 chapter_span，避免“情节族→章节卡→正文”链路在后处理阶段被拆坏。

    # ---------- 加强悲剧/信息差/复仇描述：除了第一簇，其他都可以更明确提“前后两世” ----------
    for idx, c in enumerate(clusters):
        if idx == 0:
            # 第一簇已经手动写好，且有用词限制
            continue
        opp = c.get("main_opponent") or "对手"
        payoff = (c.get("core_payoff") or "").strip()
        tragedy = (c.get("prev_life_tragedy") or "").strip()
        revenge = (c.get("this_life_revenge") or "").strip()
        info_gap = (c.get("info_gap_from_prev_life") or "").strip()

        if len(tragedy) < 25:
            tragedy = (
                f"上一轮人生中，在这一环节她被{opp}一步步压制，"
                f"表面是合理的流程或关心，实则把她推向无法翻盘的深渊：{tragedy or '关键证据被转移、话语权被夺走，身边人集体选择沉默。'}"
            )
            c["prev_life_tragedy"] = tragedy
        if len(info_gap) < 20:
            info_gap = (
                "在被逼到绝境的过程中，她无意间听到对方关于“怎么掩盖这次操作”的对话，"
                "还看到过一份未被正式归档的原始记录，记住了具体时间、账号或人名，这些细节今生只有她一个人知道。"
            )
            c["info_gap_from_prev_life"] = info_gap
        # 根据上一世悲剧 + 信息差，强行改写今世复仇描述，让因果关系清晰
        c["this_life_revenge"] = (
            "今生她牢记上一世在这一环节是如何被"
            f"{opp} "
            "一步步逼到绝境，也清楚记得当时留下的那些“被他们忽视的细节”和暗箱操作："
            f"{info_gap} "
            "于是她假装顺着对方旧有的套路配合，实则提前卡在他们以为安全的时间点和环节上，"
            "把上一世听到/看到的那些内部信息用来布局、取证或反向设计场面，"
            "在关键时刻打断他们原本以为万无一失的节奏，让在场所有人都惊讶她怎么会知道这些内情；"
            f"最终达成的爽点是：{payoff or '让对手在最得意的时候被反杀，当场翻车。'}"
        )

    return clusters


def _build_chapter_plan_for_cluster(cluster: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    为单个事件簇生成逐章 chapter_plan：
    role / goal / must_include / must_not_include / ending / must_resolve_this_chapter
    """
    start_ch, end_ch = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters") or (None, None)
    if start_ch is None or end_ch is None:
        return {}
    start_ch, end_ch = int(start_ch), int(end_ch)
    length = max(1, end_ch - start_ch + 1)

    main_opp = cluster.get("main_opponent", "")
    core_payoff = (cluster.get("core_payoff") or "").strip()
    info_gap = (cluster.get("info_gap_from_prev_life") or "")
    outcome = (cluster.get("cluster_outcome") or "").strip()

    def _infer_evidence_types_from_info_gap(info_gap: str) -> List[str]:
        """从 info_gap_from_prev_life 文本中尽量抽取“证据类型”。"""
        text = (info_gap or "").strip()
        if not text:
            return ["本簇信息差中的具体证据或内幕"]

        t = text.replace(" ", "")
        evidences: List[str] = []

        def add(item: str) -> None:
            item = (item or "").strip()
            if not item or item in evidences:
                return
            evidences.append(item)

        if "电子签名" in t:
            add("电子签名记录")
        if "用药剂量" in t:
            add("用药剂量/电子用药记录")
        if "病历" in t:
            if "篡改" in t or "修改" in t:
                add("病历篡改/病历记录")
            else:
                add("病历记录")

        if "值班室" in t and "笔记" in t:
            add("值班室笔记")
        elif "笔记" in t:
            add("笔记")

        if "录音" in t:
            add("录音/对话录音")
        if "视频" in t:
            add("密谈视频")
        if "邮件" in t:
            add("邮件往来")
        if "转账" in t:
            add("可疑转账记录")
        if "交易记录" in t or "地下交易" in t:
            add("地下交易记录")

        if "文件编号" in t and "时间节点" in t:
            add("关键时间节点与文件编号")
        elif "文件编号" in t:
            add("文件编号")
        elif "时间节点" in t:
            add("关键时间节点")

        if "会议" in t:
            add("会议内容/纪要")
        if "接触记录" in t:
            add("接触记录/名单")
        if "证据" in t:
            add("罪行证据")

        if not evidences:
            add("本簇信息差中的具体证据或内幕")
        return evidences[:3]

    evidence_types = _infer_evidence_types_from_info_gap(info_gap)
    required_evidence_hint = "、".join(evidence_types[:2]) if evidence_types else "本簇信息差中提到的具体证据或内幕"

    def _role_by_index(idx: int) -> str:
        if length == 2:
            return "prev_life_full" if idx == 1 else "present_revenge"
        if idx == 1:
            return "present_setup"
        if idx == 2:
            return "prev_life_full"
        if idx == length:
            return "present_revenge"
        return "present_mid_bridge"

    chapters_plan: Dict[str, Dict[str, Any]] = {}
    for idx, ch in enumerate(range(start_ch, end_ch + 1), start=1):
        # 第 1/2 章使用硬编码强约束
        if ch in SPECIAL_CHAPTER_PLAN:
            sc = SPECIAL_CHAPTER_PLAN[ch]
            chapters_plan[str(ch)] = {
                "role": sc["role"],
                "goal": sc["goal"],
                "must_include": sc["must_include"],
                "must_not_include": sc["must_not_include"],
                "ending": sc["ending"],
                "must_resolve_this_chapter": sc.get("must_resolve_this_chapter", []),
            }
            continue

        # 任务卡（goal/must/ending）复用正文脚本的同一套逻辑，保证稳定
        if length == 1:
            chapters_plan[str(ch)] = {
                "role": _role_by_index(idx),
                "goal": f"在本章内完成背景铺垫、上一世回忆与今世反击，兑现本簇爽点：{core_payoff}",
                "must_include": [
                    f"本簇主对手（{main_opp}）" if main_opp else "本簇主对手",
                    "与信息差相关的证据或线索",
                    "反杀结果或处罚",
                ],
                "must_not_include": DEFAULT_FORBIDDEN_NEW_ROLES + ["新幕后黑手", "只埋钩子不兑现"],
                "ending": f"本簇结束，结果需落到：{outcome or '对手付出代价'}",
                "must_resolve_this_chapter": ["锁定主对手", "显性使用信息差证据", "完成反杀并写出结果"],
            }
        elif length == 2:
            if idx == 1:
                chapters_plan[str(ch)] = {
                    "role": _role_by_index(idx),
                    "goal": "完整展开上一世在本簇情境下如何被害，为下一章反杀蓄力",
                    "must_include": ["上一世具体受害过程", main_opp or "主对手", "与信息差相关的细节（如笔记、记录）"],
                    "must_not_include": ["无关支线角色抢戏"] + DEFAULT_FORBIDDEN_NEW_ROLES,
                    "ending": "回忆收束，读者清楚本簇仇人是谁、曾如何害她",
                    "must_resolve_this_chapter": ["展开上一世悲剧", "明确主对手与信息差来源"],
                }
            else:
                chapters_plan[str(ch)] = {
                    "role": _role_by_index(idx),
                    "goal": f"公开反杀完成，兑现：{core_payoff}，结果落到：{outcome or '对手付出代价'}",
                    "must_include": ["当众揭穿或举报", f"证据链闭环（必须显性使用{required_evidence_hint}）", "处罚/后果/职业毁灭或舆论崩塌"],
                    "must_not_include": ["只埋钩子不兑现", "更大风暴才刚开始", "新大Boss"] + DEFAULT_FORBIDDEN_NEW_ROLES,
                    "ending": "本簇结束，主对手在本簇内得到应有下场",
                    "must_resolve_this_chapter": ["公开反杀", "证据链显性使用", "后果落地"],
                }
        else:
            # length >= 3
            if idx == 1:
                chapters_plan[str(ch)] = {
                    "role": _role_by_index(idx),
                    "goal": f"今生重遇本簇主对手（{main_opp}），触发相似场景，埋下与信息差相关的线索",
                    "must_include": ["医院/职场等本簇场景", f"{main_opp}施压或试探" if main_opp else "本簇主对手施压或试探",
                                      f"沈清欢确认可追查线索（如{required_evidence_hint}）"],
                    "must_not_include": ["新幕后黑手", "追车/系统提示/无关神秘线"] + DEFAULT_FORBIDDEN_NEW_ROLES,
                    "ending": "拿到进入关键场所的机会或发现证据位置，为下一章回忆与取证铺垫",
                    "must_resolve_this_chapter": ["锁定主对手", "触发回忆线索", "发现可追查的具体线索"],
                }
            elif idx == 2:
                chapters_plan[str(ch)] = {
                    "role": _role_by_index(idx),
                    "goal": "完整展开上一世延误/陷害的屈辱回忆，并与今生调查对照；今生拿到硬证据",
                    "must_include": ["上一世具体抢救失败或陷害过程",
                                      f"{main_opp}的主观恶意" if main_opp else "主对手的主观恶意",
                                      f"与{required_evidence_hint}对应的信息差内容（显性说明其内容与可追查性）",
                                      "今生取得证据"],
                    "must_not_include": ["无关支线角色抢戏"] + DEFAULT_FORBIDDEN_NEW_ROLES,
                    "ending": "沈清欢今生已拿到可用的硬证据，为最后一章反杀做准备",
                    "must_resolve_this_chapter": ["展开上一世悲剧", "拿到证据"],
                }
            elif idx == length:
                chapters_plan[str(ch)] = {
                    "role": _role_by_index(idx),
                    "goal": f"公开举报与反杀完成，兑现本簇爽点：{core_payoff}，结果：{outcome or '职业毁灭/失去信任'}",
                    "must_include": ["当众揭穿/举报", f"证据链闭环（显性使用{required_evidence_hint}，把她知道的内幕对应到可呈交的具体证据）",
                                      "处罚/吊销/全院震动或舆论反噬"],
                    "must_not_include": ["只埋钩子不兑现", "真正风暴才刚开始", "新大Boss"] + DEFAULT_FORBIDDEN_NEW_ROLES,
                    "ending": "本簇结束，主对手在本簇内失去信任或受到处罚",
                    "must_resolve_this_chapter": ["公开反杀", "后果落地"],
                }
            else:
                chapters_plan[str(ch)] = {
                    "role": _role_by_index(idx),
                    "goal": "承上启下：压迫升级或取证推进，不引入新主线",
                    "must_include": [
                        main_opp or "主对手",
                        "与信息差相关的调查或对峙",
                        f"围绕{required_evidence_hint}推进取证/对峙（不得换证据来源）",
                    ],
                    "must_not_include": ["新核心人物", "新组织/新阴谋线"] + DEFAULT_FORBIDDEN_NEW_ROLES,
                    "ending": "推进到下一章可直入反杀或收尾",
                    "must_resolve_this_chapter": ["推进证据或压迫", "不扩散到其他簇"],
                }

    return chapters_plan


def main() -> None:
    print("=" * 60)
    print("事件簇生成脚本 V2：先生成全书大目标，再生成事件簇并分配模版")
    print("=" * 60)

    global_seed_plan = generate_global_seed_plan_v2()
    clusters = generate_event_clusters_v2(global_seed_plan)
    if not clusters:
        print("⚠️ 未生成任何事件簇，流程结束。")
        return

    # 规则后处理：固定前两章语义 + 充实悲剧/复仇描述
    clusters = _post_process_clusters(clusters)
    # V2：不再随机分配 structure_template，避免“情节族→章节卡→正文”链路被模板后处理破坏

    # 新增：为每个事件簇附加稳定逐章执行计划 chapter_plan（给“章节卡脚本”直接读取）
    for c in clusters:
        c["chapter_plan"] = _build_chapter_plan_for_cluster(c)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUTPUT_DIR, f"event_clusters_v2_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clusters, f, ensure_ascii=False, indent=2)

    # 同时写一份稳定名称，方便后续脚本默认读取
    stable_path = os.path.join(OUTPUT_DIR, "event_clusters_v2.json")
    try:
        with open(stable_path, "w", encoding="utf-8") as f:
            json.dump(clusters, f, ensure_ascii=False, indent=2)
        print(f"✅ 事件簇 V2 已写入：{path}")
        print(f"✅ 稳定引用文件已写入：{stable_path}")
    except Exception:
        print(f"✅ 事件簇 V2 已写入：{path}（写入稳定文件 {stable_path} 失败，可忽略）")


if __name__ == "__main__":
    main()


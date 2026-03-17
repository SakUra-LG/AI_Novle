#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
事件簇生成脚本 V2（重生复仇短剧）

职责：
1）先为整本书生成唯一的「最大复仇主线蓝图」（全书大目标），写入 outputs/global_seed_plan_v2.txt；
2）在蓝图约束下，生成事件簇列表（与旧版 event_clusters.json 结构兼容）；
3）为每个事件簇分配结构模版（M1~M5），写入字段 structure_template；
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
        "重生复仇短剧，女主沈清欢，现代都市+医疗阴谋+职场反杀，极致委屈+高密度爽点。"
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
        "请为一部现代都市背景的《重生复仇短剧》设计一条**唯一的、贯穿全书 100 章的最大复仇主线蓝图 V2**，用 3-6 句话概括。\n\n"
        "要求：\n"
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
    with open(path, "w", encoding="utf-8") as f:
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
        "1. 将全书拆分为若干个事件簇（建议 10〜25 个，每簇 2〜8 章左右），每个簇围绕一个相对完整的冲突与爽点展开；\n"
        "2. 每个事件簇必须包含：\n"
        "   - cluster_id：字符串，形如 EC01, EC02...\n"
        "   - name：简短标题\n"
        "   - arc_id：所属大弧线ID，可用 A01/A02/A03 等粗分（例如：婚姻/家族线、职场线、医疗线、资本与舆论线）\n"
        "   - core_payoff：本簇最核心的“爽点/反杀结果”一句话\n"
        "   - chapter_span：[起始章, 结束章]，例如 [3, 5]\n"
        "   - main_opponent：本簇的主要对手（可以是个人或机构）\n"
        "   - escalation_level：1~3 的整数，1=中小型冲突，3=重大阶段性爆点\n"
        "   - prev_life_tragedy：对应上一世的典型悲剧前提\n"
        "   - this_life_revenge：今生在本簇中大致如何反杀\n"
        "   - cluster_outcome：本簇结束时的结果与对后续的影响\n"
        "   - summary：2~3 句对本簇从“酝酿→爆发→收尾”的简要说明\n"
        "   - notes：数组，补充任何写作提醒\n\n"
        "3. 请直接输出 JSON 数组（顶层是 list），其中每个元素是一个事件簇对象，字段名用英文 key，字符串内容为中文。\n"
        "4. 严格保证 chapter_span 不重叠且覆盖 1~100 章的主要剧情（允许个别章节作为跨簇过渡，但不要出现完全空档）。\n"
        "5. 不要额外解释，不要输出 markdown，只输出干净的 JSON。"
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
    2）从第 3 章开始，为后续事件簇随机分配 2~4 章的章节跨度，避免总是固定 4 章；
    3）尽量把 prev_life_tragedy / this_life_revenge 写得更具体，方便后续模型理解。
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

    # ---------- 其余簇：从第 3 章开始随机分配章节范围 2~4 章 ----------
    if len(clusters) > 2:
        current_chapter = 3
        rest = clusters[2:]
        n_rest = len(rest)
        for idx, c in enumerate(rest):
            remaining_clusters = n_rest - idx
            remaining_slots = 100 - current_chapter + 1
            if remaining_slots <= 0:
                # 防御：越界时直接收缩到上一簇
                c["chapter_span"] = [100, 100]
                continue

            # 理论上每个簇至少 2 章，如果剩余空间不足则允许最后若干簇缩到 1 章
            min_len = 2
            if remaining_slots < 2 * remaining_clusters:
                min_len = 1

            if remaining_clusters == 1:
                # 最后一个簇吃掉剩余所有章节，但不超过 4 章
                length = min(4, remaining_slots)
            else:
                max_len = min(4, remaining_slots - 2 * (remaining_clusters - 1))
                if max_len < min_len:
                    max_len = min_len
                length = random.randint(min_len, max_len)

            start_ch = current_chapter
            end_ch = min(100, start_ch + length - 1)
            c["chapter_span"] = [start_ch, end_ch]
            current_chapter = end_ch + 1

        # 如果最后还有富余章节（极少数情况），并到最后一个簇上
        if current_chapter <= 100 and rest:
            last = rest[-1]
            span = last.get("chapter_span") or [current_chapter, current_chapter]
            try:
                s, _e = int(span[0]), int(span[1])
            except Exception:  # noqa: BLE001
                s = current_chapter
            last["chapter_span"] = [s, 100]

    # ---------- 加强悲剧与复仇描述：除了第一簇，其他都可以更明确提“前后两世” ----------
    for idx, c in enumerate(clusters):
        if idx == 0:
            # 第一簇已经手动写好，且有用词限制
            continue
        opp = c.get("main_opponent") or "对手"
        payoff = c.get("core_payoff") or ""
        tragedy = (c.get("prev_life_tragedy") or "").strip()
        revenge = (c.get("this_life_revenge") or "").strip()

        if len(tragedy) < 25:
            c["prev_life_tragedy"] = (
                f"上一轮人生中，在这一环节她被{opp}一步步压制，"
                f"表面是合理的流程或关心，实则把她推向无法翻盘的深渊：{tragedy or '关键证据被转移、话语权被夺走，身边人集体选择沉默。'}"
            )
        if len(revenge) < 25:
            c["this_life_revenge"] = (
                f"这一次她提前意识到这里是命运转折点，"
                f"针对{opp}当初的每一步布局做出反手：{revenge or '她故意示弱、反向收集证据，在别人以为她还像从前一样好欺负时，把准备好的反击一点点按下去。'}"
                f"最终达成的爽点是：{payoff}"
            )

    return clusters


def main() -> None:
    print("=" * 60)
    print("事件簇生成脚本 V2：先生成全书大目标，再生成事件簇并分配模版")
    print("=" * 60)

    global_seed_plan = generate_global_seed_plan_v2()
    clusters = generate_event_clusters_v2(global_seed_plan)
    if not clusters:
        print("⚠️ 未生成任何事件簇，流程结束。")
        return

    # 规则后处理：固定前两章语义 + 随机章节跨度 + 充实悲剧/复仇描述
    clusters = _post_process_clusters(clusters)
    clusters = attach_templates_to_clusters(clusters)

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


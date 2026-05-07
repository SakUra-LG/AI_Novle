import os
import re
from pathlib import Path


GRIEVANCE_LEVEL_RULES = {
    1: "委屈强度1级（轻微）：只写轻微失落、被忽略、付出没有被及时看见；人物仍能自我安慰，不当众争辩，不哭崩，不出现强烈背叛或绝望。",
    2: "委屈强度2级（偏轻）：出现明确误解、偏心或功劳被淡化；人物有想解释的冲动，但仍选择忍住或低声说明，情绪以心酸和憋闷为主。",
    3: "委屈强度3级（中等）：误解被公开化，解释被打断或无人采信；人物开始明显红眼、发抖、百口莫辩，委屈与不甘同时出现。",
    4: "委屈强度4级（偏强）：委屈升级为当众难堪、被反咬、被孤立或被牺牲；人物短暂失控、落泪或质问，但仍保留现实克制。",
    5: "委屈强度5级（最强）：委屈集中爆发，必须写出长期付出被彻底否定、清白被夺或至亲/同伴背叛；结尾落到心寒、心死、关系断裂或不可逆损失，但避免写成单纯复仇爽文。",
}


GRIEVANCE_LEVEL_HARD_CONSTRAINTS = {
    1: {
        "grievance_min": 2,
        "grievance_max": 7,
        "injustice_min": 1,
        "isolation_min": 0,
        "body_min": 1,
        "dialogue_max": 4,
        "high_intensity_max": 1,
        "sample_count_range": (1, 2),
    },
    2: {
        "grievance_min": 4,
        "grievance_max": 10,
        "injustice_min": 2,
        "isolation_min": 1,
        "body_min": 2,
        "dialogue_max": 5,
        "high_intensity_max": 2,
        "sample_count_range": (3, 5),
    },
    3: {
        "grievance_min": 7,
        "grievance_max": 15,
        "injustice_min": 3,
        "isolation_min": 2,
        "body_min": 3,
        "dialogue_max": 6,
        "high_intensity_max": 4,
        "sample_count_range": (6, 9),
    },
    4: {
        "grievance_min": 10,
        "grievance_max": 22,
        "injustice_min": 4,
        "isolation_min": 3,
        "body_min": 4,
        "dialogue_max": 7,
        "high_intensity_max": 7,
        "sample_count_range": (10, 13),
    },
    5: {
        "grievance_min": 14,
        "grievance_max": 34,
        "injustice_min": 5,
        "isolation_min": 4,
        "body_min": 5,
        "dialogue_max": 8,
        "high_intensity_max": 99,
        "sample_count_range": (15, 20),
    },
}


GRIEVANCE_LEVEL_WRITING_GUIDES = {
    1: [
        "只保留轻微落差：一句没有被提到的名字、一次被忽略的付出、一个没等来的回应。",
        "人物可以难受，但要能压下去；不要写崩溃、绝望、背叛、众叛亲离或不可逆伤害。",
        "结尾停在酸涩和自我消化，像'算了'、'也许他们不是故意的'这种轻度委屈。",
    ],
    2: [
        "让误解或偏心更明确，但仍以生活化冲突为主，不要直接写到人生毁灭。",
        "人物想解释，却因为场合、关系或自尊而忍住；重点写憋闷和心酸。",
        "可以出现眼眶发热、手指攥紧、低头沉默等反应，但不要大段哭诉。",
    ],
    3: [
        "让人物的清白、功劳或善意被公开否定，并出现解释被打断、无人作证或被集体误会。",
        "委屈要与不甘、难堪交织：不是单纯伤心，而是明明有理却说不出口。",
        "结尾形成中等强度的百口莫辩，但不要直接进入彻底心死。",
    ],
    4: [
        "加重公开羞辱和关系背刺：人物越想证明自己，越被说成计较、狡辩或不懂事。",
        "允许落泪、声音发抖、短暂质问，重点写尊严被踩和信任被伤。",
        "结尾应出现明显关系裂痕或心理崩塌边缘，但仍留在现实可承受范围内。",
    ],
    5: [
        "必须有长期付出、关键证据或深层信任被彻底否定，让委屈达到压垮人物的程度。",
        "写出'我不是要表扬/补偿，只是不能被说成没做过、没资格、活该'的核心痛点。",
        "结尾要有不可逆损失、心寒决裂或身份/清白被毁的后果，不要转成打脸复仇。",
    ],
}


GRIEVANCE_CUE_WORDS = [
    "委屈",
    "心酸",
    "难过",
    "失落",
    "憋屈",
    "憋闷",
    "难堪",
    "心寒",
    "寒心",
    "被冤枉",
    "冤枉",
    "百口莫辩",
    "有口难辩",
    "说不清",
    "解释",
    "没人听",
    "不相信",
    "不被相信",
    "不被看见",
    "不被认可",
    "被否定",
    "被误解",
    "误会",
    "被忽略",
    "被抛下",
    "被辜负",
    "被背叛",
    "被轻视",
    "眼泪",
    "红了眼",
    "哭",
    "想哭",
    "酸",
]


INJUSTICE_CUE_WORDS = [
    "明明",
    "却",
    "不是",
    "没有",
    "凭什么",
    "活该",
    "反而",
    "全都",
    "所有",
    "功劳",
    "抢功",
    "甩锅",
    "背锅",
    "栽赃",
    "污蔑",
    "诬陷",
    "证据",
    "清白",
    "付出",
    "努力",
    "辛苦",
    "牺牲",
    "被夺走",
    "被拿走",
    "不配",
    "资格",
    "认",
]


ISOLATION_CUE_WORDS = [
    "没人",
    "没有一个人",
    "无人",
    "所有人",
    "全班",
    "全家",
    "众人",
    "冷眼",
    "沉默",
    "看戏",
    "围观",
    "孤立",
    "站在对面",
    "只剩",
    "一个人",
    "独自",
    "背后",
    "群里",
]


BODY_REACTION_WORDS = [
    "低头",
    "垂眼",
    "攥紧",
    "捏紧",
    "发抖",
    "颤抖",
    "僵住",
    "发白",
    "发热",
    "哽住",
    "哽咽",
    "喉咙",
    "胸口",
    "手心",
    "眼眶",
    "眼泪",
    "鼻酸",
    "咬住",
    "忍住",
    "沉默",
]


HIGH_INTENSITY_WORDS = [
    "崩溃",
    "绝望",
    "心死",
    "毁掉",
    "彻底",
    "死",
    "一辈子",
    "到死",
    "全世界",
    "众叛亲离",
    "不可逆",
    "压垮",
    "疯",
    "撕碎",
    "毁了",
]


DEFAULT_SCENE_DRIFT_WORDS = [
    "医院",
    "病房",
    "产房",
    "警局",
    "审讯室",
    "校园",
    "宿舍",
    "饭局",
    "婚礼",
    "养老院",
    "法院",
    "直播",
    "工地",
    "武侠",
    "古代",
    "灾后",
    "地震",
]


def find_project_root(start_path: str | os.PathLike | None = None) -> Path:
    start = Path(start_path or __file__).resolve()
    for parent in [start.parent, *start.parents]:
        if (parent / "data" / "grievance_samples.txt").exists() and (parent / "scripts").exists():
            return parent
    raise FileNotFoundError("未找到包含 data/grievance_samples.txt 的项目根目录。")


def normalize_topic_for_filename(topic: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", topic.strip()) if topic else ""
    return cleaned[:40] if cleaned else "默认委屈场景"


def load_grievance_examples(sample_path: str | os.PathLike | None = None) -> list[str]:
    path = Path(sample_path) if sample_path else find_project_root() / "data" / "grievance_samples.txt"
    if not path.exists():
        return []

    raw = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=##\s+委屈-)", raw.strip())
    return [block.strip() for block in blocks if block.strip()]


def _extract_score(example: str) -> float:
    match = re.search(r"\*\*评分\*\*:\s*([0-9]+(?:\.[0-9]+)?)", example)
    return float(match.group(1)) if match else 0.0


def pick_examples_for_level(examples: list[str], grievance_level: int) -> list[str]:
    if not examples:
        return []

    sorted_examples = sorted(examples, key=_extract_score)
    cfg = GRIEVANCE_LEVEL_HARD_CONSTRAINTS[grievance_level]
    min_count, max_count = cfg["sample_count_range"]
    count = min(max_count, max(min_count, len(sorted_examples)))

    # Lower levels should learn restrained phrasing from relatively lower-score
    # samples; higher levels can use the densest, most painful examples.
    if grievance_level <= 2:
        pool = sorted_examples[: max(12, count)]
    elif grievance_level == 3:
        mid = len(sorted_examples) // 2
        pool = sorted_examples[max(0, mid - 8): mid + 8]
    else:
        pool = sorted_examples[-max(24, count):]

    return pool[:count]


def estimate_grievance_metrics(text: str) -> dict:
    if not text:
        return {
            "grievance_hits": 0,
            "injustice_hits": 0,
            "isolation_hits": 0,
            "body_hits": 0,
            "high_intensity_hits": 0,
            "dialogue_count": 0,
        }

    dialogue_segments = re.findall(r'[：:]\s*[“"]([^”"]{1,180})[”"]', text)
    return {
        "grievance_hits": sum(text.count(word) for word in GRIEVANCE_CUE_WORDS),
        "injustice_hits": sum(text.count(word) for word in INJUSTICE_CUE_WORDS),
        "isolation_hits": sum(text.count(word) for word in ISOLATION_CUE_WORDS),
        "body_hits": sum(text.count(word) for word in BODY_REACTION_WORDS),
        "high_intensity_hits": sum(text.count(word) for word in HIGH_INTENSITY_WORDS),
        "dialogue_count": len(dialogue_segments),
    }


def extract_scene_anchor_words(scene_prompt: str) -> list[str]:
    candidates = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", scene_prompt or "")
    stop_words = {
        "主角",
        "一个",
        "一次",
        "突然",
        "发现",
        "因为",
        "所以",
        "但是",
        "然后",
        "自己",
        "别人",
        "事情",
        "场景",
        "片段",
        "情绪",
    }
    anchors = [word for word in candidates if word not in stop_words]
    return anchors[:10]


def validate_scene_consistency(text: str, scene_prompt: str) -> tuple[bool, dict, list[str]]:
    anchors = extract_scene_anchor_words(scene_prompt)
    required_count = min(4, max(2, len(anchors) // 2)) if anchors else 0
    matched_anchors = [word for word in anchors if word in text]
    drift_words = [word for word in DEFAULT_SCENE_DRIFT_WORDS if word in text and word not in scene_prompt]
    reasons = []

    if required_count and len(matched_anchors) < required_count:
        reasons.append(
            "场景锚点不足：必须持续围绕输入场景，不要改成参考样本里的其他委屈事件；"
            f"当前命中 {matched_anchors}，至少需要 {required_count} 个。"
        )
    if drift_words:
        reasons.append(f"出现疑似场景漂移词：{', '.join(drift_words)}。")

    return len(reasons) == 0, {
        "scene_anchor_hits": len(matched_anchors),
        "scene_anchor_required": required_count,
        "scene_drift_hits": len(drift_words),
    }, reasons


def validate_level_output(
    text: str,
    grievance_level: int,
    scene_prompt: str | None = None,
) -> tuple[bool, dict, list[str]]:
    cfg = GRIEVANCE_LEVEL_HARD_CONSTRAINTS[grievance_level]
    metrics = estimate_grievance_metrics(text)
    reasons = []

    if metrics["grievance_hits"] < cfg["grievance_min"]:
        reasons.append(f"委屈线索过少：当前 {metrics['grievance_hits']}，至少 {cfg['grievance_min']}。")
    if metrics["grievance_hits"] > cfg["grievance_max"]:
        reasons.append(f"委屈线索过密：当前 {metrics['grievance_hits']}，最多 {cfg['grievance_max']}。")
    if metrics["injustice_hits"] < cfg["injustice_min"]:
        reasons.append(f"不公/被误解线索不足：当前 {metrics['injustice_hits']}，至少 {cfg['injustice_min']}。")
    if metrics["isolation_hits"] < cfg["isolation_min"]:
        reasons.append(f"孤立无援线索不足：当前 {metrics['isolation_hits']}，至少 {cfg['isolation_min']}。")
    if metrics["body_hits"] < cfg["body_min"]:
        reasons.append(f"压抑反应线索不足：当前 {metrics['body_hits']}，至少 {cfg['body_min']}。")
    if metrics["high_intensity_hits"] > cfg["high_intensity_max"]:
        reasons.append(
            f"高强度词过早或过密：当前 {metrics['high_intensity_hits']}，最多 {cfg['high_intensity_max']}。"
        )
    if metrics["dialogue_count"] > cfg["dialogue_max"]:
        reasons.append(f"对话过多削弱委屈内压：当前 {metrics['dialogue_count']}，最多 {cfg['dialogue_max']}。")

    if scene_prompt:
        scene_passed, scene_metrics, scene_reasons = validate_scene_consistency(text, scene_prompt)
        metrics.update(scene_metrics)
        if not scene_passed:
            reasons.extend(scene_reasons)

    return len(reasons) == 0, metrics, reasons


def build_grievance_level_prompt(
    scene_prompt: str,
    grievance_level: int,
    selected_examples: list[str] | None = None,
    retry_feedback: str = "",
) -> str:
    if grievance_level not in GRIEVANCE_LEVEL_RULES:
        raise ValueError(f"不支持的委屈等级: {grievance_level}")

    cfg = GRIEVANCE_LEVEL_HARD_CONSTRAINTS[grievance_level]
    examples_block = ""
    if selected_examples:
        examples_block = (
            "\n\n【参考样本，仅学习委屈情绪的压迫感、标签维度和表达质量，严禁复制或替换本次场景】\n"
            "参考样本可能包含医院、婚礼、校园、警局、家庭、职场等不同场景；本次输出不得套用样本地点、人物、事件。\n"
            + "\n\n".join(selected_examples)
        )

    feedback_block = ""
    if retry_feedback:
        feedback_block = f"\n\n【上次生成未达标反馈】\n{retry_feedback}\n请针对这些问题重写本等级版本。"

    guide_block = "\n".join(f"- {item}" for item in GRIEVANCE_LEVEL_WRITING_GUIDES[grievance_level])
    length_rule = "500~850 字" if grievance_level == 5 else "350~650 字"

    return f"""
请基于同一个场景，写一个【委屈强度{grievance_level}级】的小说/短剧片段示例。

【固定场景，不得改写】
{scene_prompt}

场景锁定要求：
1. 五个等级必须都发生在上面这个场景中，只允许改变委屈强度，不允许改变地点、人物关系、核心事件。
2. 低等级可以弱化冲突，只写轻微忽视或误会；中高等级逐步增加公开误解、无处申辩、被反咬和关系裂痕。
3. 禁止把场景改成参考样本中的医院、婚礼、校园、警局、产房、法院、古代牢房等其他事件。
4. 参考样本只能学习情绪层次、压迫节奏、标签维度和表达质量，不能借用其地点、人物、事件或道具。

委屈强度要求：
{GRIEVANCE_LEVEL_RULES[grievance_level]}

强度刻度：
1. 不公程度：等级越高，误解、否定、抢功、甩锅、背叛或清白受损越明确。
2. 申辩难度：等级越高，人物越难解释，解释越容易被打断、曲解或反咬。
3. 孤立程度：等级越高，周围人的沉默、冷眼、看戏或站队越明显。
4. 身体反应：等级越高，从低头、攥紧、眼眶发热，逐步到哽咽、发抖、落泪和短暂失控。
5. 收束方式：高等级需要落到心寒、心死、关系断裂、清白被毁或不可逆损失；不要转成复仇打脸。

本等级写作边界：
{guide_block}

硬性约束：
1. 只输出正文，长度约 {length_rule}，不要解释规则。
2. 五个等级必须围绕同一场景横向比较，委屈强度逐级递增。
3. 委屈主要来自不被相信、付出被否定、清白说不清、善意被辜负、弱势无法自证。
4. 避免把委屈写成单纯愤怒、复仇爽文、纯哭惨或道德说教，质量优先。
5. 本等级委屈线索目标区间：{cfg["grievance_min"]}~{cfg["grievance_max"]} 处。
6. 本等级不公/被误解线索至少 {cfg["injustice_min"]} 处，孤立无援线索至少 {cfg["isolation_min"]} 处。
7. 本等级压抑身体反应线索至少 {cfg["body_min"]} 处，对话不超过 {cfg["dialogue_max"]} 段。
8. 低等级不得提前使用过多“崩溃、绝望、心死、到死、全世界”等高强度表达。
{examples_block}
{feedback_block}
""".strip()


def save_grievance_level_outputs(outputs: dict[int, str], scene_prompt: str, output_root: str) -> str:
    topic = normalize_topic_for_filename(scene_prompt)
    target_dir = os.path.join(output_root, f"{topic}_委屈五级示例")
    os.makedirs(target_dir, exist_ok=True)

    for level, content in outputs.items():
        file_path = os.path.join(target_dir, f"委屈强度{level}级_片段示例.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content or "")
    return target_dir


def generate_grievance_level_versions(
    scene_prompt: str,
    generate_func,
    output_root: str,
    max_attempts: int = 3,
) -> tuple[dict[int, str], str]:
    outputs = {}
    examples = load_grievance_examples()

    for level in range(1, 6):
        selected_examples = pick_examples_for_level(examples, level)
        print(f"正在生成委屈强度 {level} 级版本...")

        best_text = ""
        best_score_gap = 10**9
        retry_feedback = ""
        for attempt in range(1, max_attempts + 1):
            level_prompt = build_grievance_level_prompt(
                scene_prompt,
                level,
                selected_examples=selected_examples,
                retry_feedback=retry_feedback,
            )
            candidate = generate_func(level_prompt)
            passed, metrics, reasons = validate_level_output(candidate, level, scene_prompt=scene_prompt)
            print(
                f"等级{level} 第{attempt}次校验 "
                f"grievance_hits={metrics['grievance_hits']}, "
                f"injustice_hits={metrics['injustice_hits']}, "
                f"isolation_hits={metrics['isolation_hits']}, "
                f"body_hits={metrics['body_hits']}, "
                f"high_intensity_hits={metrics['high_intensity_hits']}, "
                f"dialogue_count={metrics['dialogue_count']}, "
                f"scene_anchor_hits={metrics.get('scene_anchor_hits', 0)}, "
                f"scene_drift_hits={metrics.get('scene_drift_hits', 0)}, passed={passed}"
            )
            if passed:
                best_text = candidate
                break

            cfg = GRIEVANCE_LEVEL_HARD_CONSTRAINTS[level]
            gap = 0
            if metrics["grievance_hits"] < cfg["grievance_min"]:
                gap += cfg["grievance_min"] - metrics["grievance_hits"]
            elif metrics["grievance_hits"] > cfg["grievance_max"]:
                gap += metrics["grievance_hits"] - cfg["grievance_max"]
            if metrics["injustice_hits"] < cfg["injustice_min"]:
                gap += cfg["injustice_min"] - metrics["injustice_hits"]
            if metrics["isolation_hits"] < cfg["isolation_min"]:
                gap += cfg["isolation_min"] - metrics["isolation_hits"]
            if metrics["body_hits"] < cfg["body_min"]:
                gap += cfg["body_min"] - metrics["body_hits"]
            if metrics["high_intensity_hits"] > cfg["high_intensity_max"]:
                gap += metrics["high_intensity_hits"] - cfg["high_intensity_max"]
            if metrics["dialogue_count"] > cfg["dialogue_max"]:
                gap += metrics["dialogue_count"] - cfg["dialogue_max"]
            gap += metrics.get("scene_drift_hits", 0) * 5
            if metrics.get("scene_anchor_hits", 0) < metrics.get("scene_anchor_required", 0):
                gap += metrics.get("scene_anchor_required", 0) - metrics.get("scene_anchor_hits", 0)

            if gap < best_score_gap:
                best_score_gap = gap
                best_text = candidate

            retry_feedback = "\n".join(reasons)

        outputs[level] = best_text

    output_dir = save_grievance_level_outputs(outputs, scene_prompt, output_root)
    return outputs, output_dir

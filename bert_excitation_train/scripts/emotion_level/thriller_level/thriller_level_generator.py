import os
import re
from pathlib import Path


THRILLER_LEVEL_RULES = {
    1: "恐惧强度1级（轻微）：只写轻微不安、可疑延迟、环境违和或错觉，异常必须能被现实故障解释；不出现实体、对视、微笑、耳边呼吸、主动逼近和明确超自然证据。",
    2: "恐惧强度2级（偏轻）：允许出现一次明确异常确认，人物开始警觉和害怕，但异常保持被动；可以出现异常楼层或监控异常，但不要让影像主动靠近、切换背后视角或直接交流。",
    3: "恐惧强度3级（中等）：威胁开始互动，监控、声音或空间会回应、模仿、诱导人物；人物进入主动逃避或求证状态，并感到危险正在靠近。",
    4: "恐惧强度4级（偏强）：压迫感显著升级，重点写逃不出去、规则失效、空间迷宫和身份替换的认知崩塌；可以接近人物，但不要过早直接肢体接触。",
    5: "恐惧强度5级（最强）：恐惧集中爆发，加入更充分的恐怖环境描写和高压收束；结尾必须落到不可逆后果，如失去身体、身份、记忆或现实位置，但避免依赖血腥堆砌。",
}


THRILLER_LEVEL_HARD_CONSTRAINTS = {
    1: {
        "fear_min": 2,
        "fear_max": 7,
        "threat_min": 0,
        "sensory_min": 2,
        "space_min": 1,
        "dialogue_max": 2,
        "sample_ratio": 0.16,
    },
    2: {
        "fear_min": 4,
        "fear_max": 10,
        "threat_min": 1,
        "sensory_min": 3,
        "space_min": 1,
        "dialogue_max": 3,
        "sample_ratio": 0.28,
    },
    3: {
        "fear_min": 2,
        "fear_max": 14,
        "threat_min": 2,
        "sensory_min": 4,
        "space_min": 2,
        "dialogue_max": 4,
        "sample_ratio": 0.45,
    },
    4: {
        "fear_min": 5,
        "fear_max": 19,
        "threat_min": 3,
        "sensory_min": 5,
        "space_min": 3,
        "dialogue_max": 5,
        "sample_ratio": 0.65,
    },
    5: {
        "fear_min": 9,
        "fear_max": 34,
        "threat_min": 4,
        "sensory_min": 8,
        "space_min": 4,
        "dialogue_max": 6,
        "sample_ratio": 1.00,
    },
}


SCENE_ANCHOR_WORDS = [
    "主角",
    "陈雪",
    "深夜",
    "凌晨",
    "独自",
    "老旧公寓",
    "公寓",
    "电梯",
    "轿厢",
    "楼层",
    "十四层",
    "14",
    "不存在",
    "监控屏",
    "监控",
    "另一个",
    "一样",
    "自己",
]


SCENE_DRIFT_WORDS = [
    "医院",
    "病房",
    "护士",
    "地铁",
    "车厢",
    "隧道",
    "旅馆",
    "酒店",
    "疗养院",
    "校舍",
    "学校",
    "停车场",
    "面包车",
    "山路",
    "乡村",
    "病历",
]


THRILLER_LEVEL_WRITING_GUIDES = {
    1: [
        "异常只出现一次，且不确认来源；可以写楼道灯坏、监控延迟、脚步声像错觉。",
        "不要出现另一个自己、直接对视、诡异微笑、耳边呼吸、门外实体或明确追逐。",
        "结尾停在疑虑和不安，不制造实锤威胁。",
    ],
    2: [
        "保留一个明确异常，但让异常保持静止或被动，例如楼层数字错误、监控画面延迟。",
        "不要写影像越来越近、背后视角切换、主动说话或身体接触。",
        "结尾以人物决定暂时不出去、报警或继续观察收束。",
    ],
    3: [
        "让异常开始回应、模仿或诱导人物，但仍以心理惊悚和空间失控为主。",
        "可以出现脚步逼近、按钮失灵、监控里的她同步动作。",
        "结尾应形成中度危机，而不是直接身份取代。",
    ],
    4: [
        "重点写逃不出去、走廊迷宫、录像反证、门牌重复和身份不确定。",
        "恐怖对象可以逼近，但不要直接掐住、触摸或控制身体，把这些留给5级。",
        "结尾应让人物意识到现实规则已经不可靠。",
    ],
    5: [
        "篇幅可以略长，增加电梯、走廊、灯光、潮湿气味、监控噪声等环境描写来烘托氛围。",
        "必须写出不可逆后果：她被困进监控、身份被替换、记忆被夺走或现实位置被抹除。",
        "结尾不要停在恐怖宣布，要让读者看到后果已经发生。",
    ],
}


FEAR_CUE_WORDS = [
    "恐惧",
    "害怕",
    "惊惧",
    "惊骇",
    "紧张",
    "发冷",
    "冰冷",
    "冷",
    "僵住",
    "发抖",
    "颤抖",
    "屏住呼吸",
    "屏息",
    "窒息",
    "心跳",
    "心脏",
    "心口发紧",
    "发紧",
    "头皮发麻",
    "后背",
    "冷汗",
    "不安",
    "压迫",
    "阴冷",
    "黑暗",
    "寂静",
    "死寂",
    "惨白",
    "发白",
    "不敢",
    "失灵",
    "疯狂",
    "拼命",
    "僵",
    "苍白",
    "低声",
    "轻轻",
    "湿漉漉",
    "湿透",
    "贴",
    "灭",
    "熄",
    "堵住",
    "抖",
]


THREAT_CUE_WORDS = [
    "脚步",
    "敲门",
    "门把手",
    "靠近",
    "逼近",
    "追",
    "跟着",
    "盯着",
    "窥视",
    "影子",
    "人影",
    "低语",
    "声音",
    "监控",
    "镜子",
    "倒影",
    "规则",
    "锁",
    "打不开",
    "不存在",
    "另一个",
]


SENSORY_CUE_WORDS = [
    "声音",
    "响",
    "灯",
    "光",
    "闪",
    "黑",
    "冷",
    "潮",
    "湿",
    "气味",
    "呼吸",
    "摩擦",
    "电流",
    "影",
    "镜",
    "门缝",
    "走廊",
]


SPACE_CUE_WORDS = [
    "电梯",
    "走廊",
    "楼层",
    "门",
    "房间",
    "楼梯",
    "地下",
    "停车场",
    "病房",
    "隧道",
    "车厢",
    "旅馆",
    "公寓",
    "监控室",
    "密闭",
    "封闭",
    "出口",
]


def find_project_root(start_path: str | os.PathLike | None = None) -> Path:
    start = Path(start_path or __file__).resolve()
    for parent in [start.parent, *start.parents]:
        if (parent / "data" / "horror_thriller_samples.txt").exists() and (parent / "scripts").exists():
            return parent
    raise FileNotFoundError("未找到包含 data/horror_thriller_samples.txt 的项目根目录。")


def normalize_topic_for_filename(topic: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", topic.strip()) if topic else ""
    return cleaned[:40] if cleaned else "默认恐惧场景"


def load_thriller_examples(sample_path: str | os.PathLike | None = None) -> list[str]:
    path = Path(sample_path) if sample_path else find_project_root() / "data" / "horror_thriller_samples.txt"
    if not path.exists():
        return []

    raw = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=##\s+)", raw.strip())
    return [block.strip() for block in blocks if block.strip()]


def _extract_sample_field(sample: str, field_name: str) -> str:
    match = re.search(rf"\*\*{re.escape(field_name)}\*\*:\s*(.+)", sample)
    return match.group(1).strip() if match else ""


def _extract_sample_title(sample: str) -> str:
    match = re.search(r"^##\s+(.+)", sample)
    return match.group(1).strip() if match else "恐怖惊悚样本"


def _extract_sample_score(sample: str) -> float:
    score_text = _extract_sample_field(sample, "评分")
    try:
        return float(score_text)
    except ValueError:
        return 0.0


def _mask_drift_words(text: str) -> str:
    masked = text
    for word in SCENE_DRIFT_WORDS:
        masked = masked.replace(word, "[异场景词已屏蔽]")
    return masked


def _shorten_text(text: str, max_chars: int = 180) -> str:
    compact = re.sub(r"\s+", "", text.strip())
    return compact[:max_chars] + ("..." if len(compact) > max_chars else "")


def _sample_scene_overlap(sample: str, scene_prompt: str) -> int:
    anchors = extract_scene_anchor_words(scene_prompt)
    return sum(sample.count(anchor) for anchor in anchors)


def build_sample_reference_card(sample: str, scene_prompt: str) -> str:
    title = _extract_sample_title(sample)
    emotion_tags = _extract_sample_field(sample, "情绪标签")
    scene_tags = _extract_sample_field(sample, "场景标签")
    conflict_tags = _extract_sample_field(sample, "冲突标签")
    action_tags = _extract_sample_field(sample, "动作标签")
    plot_tags = _extract_sample_field(sample, "情节标签")
    score = _extract_sample_field(sample, "评分")
    content = _extract_sample_field(sample, "内容")
    technique_excerpt = _shorten_text(_mask_drift_words(content))
    scene_overlap = _sample_scene_overlap(sample, scene_prompt)

    return "\n".join(
        [
            f"- 样本：{title}（评分：{score or '未知'}，场景锚点重合：{scene_overlap}）",
            f"  情绪标签：{emotion_tags or '无'}",
            f"  原场景标签：{scene_tags or '无'}（只用于理解氛围类型，不得迁移地点）",
            f"  冲突结构：{conflict_tags or '无'}",
            f"  动作节奏：{action_tags or '无'}",
            f"  情节推进：{plot_tags or '无'}",
            f"  技法摘录：{technique_excerpt or '无'}",
        ]
    )


def pick_examples_for_level(
    examples: list[str],
    thriller_level: int,
    scene_prompt: str = "",
) -> list[str]:
    if not examples:
        return []

    level_sample_ranges = {
        1: (1, 2),
        2: (3, 5),
        3: (6, 9),
        4: (10, 13),
        5: (15, 20),
    }
    min_count, max_count = level_sample_ranges[thriller_level]
    cfg = THRILLER_LEVEL_HARD_CONSTRAINTS[thriller_level]
    scaled_count = max(min_count, int(len(examples) * cfg["sample_ratio"]))
    k = min(max_count, scaled_count, len(examples))
    ranked_examples = sorted(
        examples,
        key=lambda item: (_sample_scene_overlap(item, scene_prompt), _extract_sample_score(item)),
        reverse=True,
    )
    return [build_sample_reference_card(sample, scene_prompt) for sample in ranked_examples[:k]]


def estimate_thriller_metrics(text: str) -> dict:
    if not text:
        return {
            "fear_hits": 0,
            "threat_hits": 0,
            "sensory_hits": 0,
            "space_hits": 0,
            "dialogue_count": 0,
        }

    dialogue_segments = re.findall(r'[：:]\s*[“"]([^”"]{1,180})[”"]', text)
    return {
        "fear_hits": sum(text.count(word) for word in FEAR_CUE_WORDS),
        "threat_hits": sum(text.count(word) for word in THREAT_CUE_WORDS),
        "sensory_hits": sum(text.count(word) for word in SENSORY_CUE_WORDS),
        "space_hits": sum(text.count(word) for word in SPACE_CUE_WORDS),
        "dialogue_count": len(dialogue_segments),
    }


def extract_scene_anchor_words(scene_prompt: str) -> list[str]:
    anchors = [word for word in SCENE_ANCHOR_WORDS if word in scene_prompt]
    if anchors:
        return anchors

    candidates = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", scene_prompt)
    return [word for word in candidates if len(word) >= 2][:8]


def validate_scene_consistency(text: str, scene_prompt: str) -> tuple[bool, dict, list[str]]:
    anchors = extract_scene_anchor_words(scene_prompt)
    required_count = min(4, max(2, len(anchors) // 2))
    matched_anchors = [word for word in anchors if word in text]
    drift_words = [word for word in SCENE_DRIFT_WORDS if word in text and word not in scene_prompt]
    reasons = []

    if len(matched_anchors) < required_count:
        reasons.append(
            "场景锚点不足：必须持续围绕输入场景，不要改成参考样本里的其他场景；"
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
    thriller_level: int,
    scene_prompt: str | None = None,
) -> tuple[bool, dict, list[str]]:
    cfg = THRILLER_LEVEL_HARD_CONSTRAINTS[thriller_level]
    metrics = estimate_thriller_metrics(text)
    reasons = []

    if metrics["fear_hits"] < cfg["fear_min"]:
        reasons.append(f"恐惧线索过少：当前 {metrics['fear_hits']}，至少 {cfg['fear_min']}。")
    if metrics["fear_hits"] > cfg["fear_max"]:
        reasons.append(f"恐惧线索过密：当前 {metrics['fear_hits']}，最多 {cfg['fear_max']}。")
    if metrics["threat_hits"] < cfg["threat_min"]:
        reasons.append(f"威胁逼近线索不足：当前 {metrics['threat_hits']}，至少 {cfg['threat_min']}。")
    if metrics["sensory_hits"] < cfg["sensory_min"]:
        reasons.append(f"感官氛围线索不足：当前 {metrics['sensory_hits']}，至少 {cfg['sensory_min']}。")
    if metrics["space_hits"] < cfg["space_min"]:
        reasons.append(f"空间压迫线索不足：当前 {metrics['space_hits']}，至少 {cfg['space_min']}。")
    if metrics["dialogue_count"] > cfg["dialogue_max"]:
        reasons.append(f"对话过多削弱恐惧氛围：当前 {metrics['dialogue_count']}，最多 {cfg['dialogue_max']}。")

    if scene_prompt:
        scene_passed, scene_metrics, scene_reasons = validate_scene_consistency(text, scene_prompt)
        metrics.update(scene_metrics)
        if not scene_passed:
            reasons.extend(scene_reasons)

    return len(reasons) == 0, metrics, reasons


def build_thriller_level_prompt(
    scene_prompt: str,
    thriller_level: int,
    selected_examples: list[str] | None = None,
    retry_feedback: str = "",
) -> str:
    if thriller_level not in THRILLER_LEVEL_RULES:
        raise ValueError(f"不支持的恐惧等级: {thriller_level}")

    cfg = THRILLER_LEVEL_HARD_CONSTRAINTS[thriller_level]
    examples_block = ""
    if selected_examples:
        examples_block = (
            "\n\n【样本库技法参考卡：必须使用其写法经验，但严禁替换固定场景】\n"
            "以下内容来自 horror_thriller_samples.txt。请学习它们的氛围密度、冲突结构、动作节奏和情节推进，"
            "但不得复制样本地点、人物、道具或事件。若技法摘录中出现 [异场景词已屏蔽]，说明原样本场景与本次固定场景不同，禁止还原。\n"
            + "\n\n".join(selected_examples)
        )

    feedback_block = ""
    if retry_feedback:
        feedback_block = f"\n\n【上次生成未达标反馈】\n{retry_feedback}\n请针对这些问题重写本等级版本。"

    guide_block = "\n".join(f"- {item}" for item in THRILLER_LEVEL_WRITING_GUIDES[thriller_level])
    length_rule = "450~800 字" if thriller_level == 5 else "350~650 字"

    return f"""
请基于同一个场景，写一个【恐惧强度{thriller_level}级】的小说/短剧片段示例。

【固定场景，不得改写】
{scene_prompt}

场景锁定要求：
1. 五个等级必须都发生在上面这个场景中，只允许改变恐惧强度，不允许改变地点、人物关系、核心事件。
2. 如果默认场景是“深夜旧公寓电梯、不存在的十四层、监控屏、另一个自己”，五级都必须保留“深夜、旧公寓、电梯、监控屏”这些场景锚点。
3. 对低等级可以弱化或延后揭示“不存在的十四层”和“另一个自己”，但不能改成其他地点或其他事件；中高等级应逐步揭示这些核心异常。
4. 禁止把场景改成医院、地铁、旅馆、疗养院、校舍、停车场、乡村旅店等参考样本中的其他场景。
5. 样本库技法参考卡必须用于提升氛围、节奏、冲突和收束质量，但不能借用其地点、人物、事件或道具。

恐惧强度要求：
{THRILLER_LEVEL_RULES[thriller_level]}

强度刻度：
1. 异常程度：等级越高，异常越具体、越无法用现实解释，不能只靠突然吓人。
2. 空间压迫：等级越高，封闭、迷路、出口失效、楼层错位等压迫越明显。
3. 威胁逼近：等级越高，脚步、影子、门锁、监控、镜像、低语等线索越接近人物。
4. 心理反应：等级越高，人物从迟疑、警觉、惊惧逐步进入濒临崩溃但仍在求生的状态。
5. 收束方式：高等级需要形成清晰反转或不可回避的危机，不依赖血腥堆砌。

本等级写作边界：
{guide_block}

硬性约束：
1. 只输出正文，长度约 {length_rule}，不要解释规则。
2. 五个等级必须围绕同一场景横向比较，恐惧强度逐级递增。
3. 恐惧主要来自氛围、异常规则、空间压迫、未知窥视和心理惊悚。
4. 避免过度血腥、恶心描写和廉价跳吓，质量优先。
5. 本等级恐惧线索目标区间：{cfg["fear_min"]}~{cfg["fear_max"]} 处。
6. 本等级威胁逼近线索至少 {cfg["threat_min"]} 处，感官氛围线索至少 {cfg["sensory_min"]} 处。
7. 本等级空间压迫线索至少 {cfg["space_min"]} 处，对话不超过 {cfg["dialogue_max"]} 段。
{examples_block}
{feedback_block}
""".strip()


def save_thriller_level_outputs(outputs: dict[int, str], scene_prompt: str, output_root: str) -> str:
    topic = normalize_topic_for_filename(scene_prompt)
    target_dir = os.path.join(output_root, f"{topic}_恐惧五级示例")
    os.makedirs(target_dir, exist_ok=True)

    for level, content in outputs.items():
        file_path = os.path.join(target_dir, f"恐惧强度{level}级_片段示例.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content or "")
    return target_dir


def generate_thriller_level_versions(
    scene_prompt: str,
    generate_func,
    output_root: str,
    max_attempts: int = 3,
) -> tuple[dict[int, str], str]:
    outputs = {}
    examples = load_thriller_examples()

    for level in range(1, 6):
        selected_examples = pick_examples_for_level(examples, level, scene_prompt=scene_prompt)
        print(f"已接入恐怖样本库技法卡 {len(selected_examples)} 条。")
        print(f"正在生成恐惧强度 {level} 级版本...")

        best_text = ""
        best_score_gap = 10**9
        retry_feedback = ""
        for attempt in range(1, max_attempts + 1):
            level_prompt = build_thriller_level_prompt(
                scene_prompt,
                level,
                selected_examples=selected_examples,
                retry_feedback=retry_feedback,
            )
            candidate = generate_func(level_prompt)
            passed, metrics, reasons = validate_level_output(candidate, level, scene_prompt=scene_prompt)
            print(
                f"等级{level} 第{attempt}次校验 "
                f"fear_hits={metrics['fear_hits']}, "
                f"threat_hits={metrics['threat_hits']}, "
                f"sensory_hits={metrics['sensory_hits']}, "
                f"space_hits={metrics['space_hits']}, "
                f"dialogue_count={metrics['dialogue_count']}, "
                f"scene_anchor_hits={metrics.get('scene_anchor_hits', 0)}, "
                f"scene_drift_hits={metrics.get('scene_drift_hits', 0)}, passed={passed}"
            )
            if passed:
                best_text = candidate
                break

            cfg = THRILLER_LEVEL_HARD_CONSTRAINTS[level]
            gap = 0
            if metrics["fear_hits"] < cfg["fear_min"]:
                gap += cfg["fear_min"] - metrics["fear_hits"]
            elif metrics["fear_hits"] > cfg["fear_max"]:
                gap += metrics["fear_hits"] - cfg["fear_max"]
            if metrics["threat_hits"] < cfg["threat_min"]:
                gap += cfg["threat_min"] - metrics["threat_hits"]
            if metrics["sensory_hits"] < cfg["sensory_min"]:
                gap += cfg["sensory_min"] - metrics["sensory_hits"]
            if metrics["space_hits"] < cfg["space_min"]:
                gap += cfg["space_min"] - metrics["space_hits"]
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

    output_dir = save_thriller_level_outputs(outputs, scene_prompt, output_root)
    return outputs, output_dir

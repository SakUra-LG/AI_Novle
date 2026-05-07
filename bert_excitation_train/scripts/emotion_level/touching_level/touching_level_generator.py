import os
import re
from pathlib import Path


TOUCHING_LEVEL_RULES = {
    1: "感动强度1级（轻微）：只写小善意、小照顾或一句被看见的话，人物心里泛起暖意；情绪克制，不哭崩，不写重大牺牲或救赎。",
    2: "感动强度2级（偏轻）：人物明确感到被理解、被接住或被默默关心，可以有轻微泪意、释然或心软，但冲突仍保持生活化。",
    3: "感动强度3级（中等）：陪伴、守护、迟来的道歉或坚定支持成为片段核心，人物情绪明显松动，出现眼泪、拥抱或重新振作。",
    4: "感动强度4级（偏强）：感动来自更深的等待、牺牲、长期记挂或关键时刻的选择，人物产生强烈共情和关系修复。",
    5: "感动强度5级（最强）：情绪集中爆发，必须写出人物在低谷、绝望或长期孤独中被温柔托住；结尾落到精神救赎、和解、希望重燃或生命意义被重新确认，但避免煽情堆砌。",
}


TOUCHING_LEVEL_HARD_CONSTRAINTS = {
    1: {
        "touching_min": 2,
        "touching_max": 7,
        "kindness_min": 1,
        "warmth_min": 1,
        "release_min": 0,
        "body_min": 1,
        "dialogue_max": 4,
        "high_intensity_max": 1,
        "sample_count_range": (1, 2),
    },
    2: {
        "touching_min": 4,
        "touching_max": 10,
        "kindness_min": 2,
        "warmth_min": 2,
        "release_min": 1,
        "body_min": 2,
        "dialogue_max": 5,
        "high_intensity_max": 2,
        "sample_count_range": (2, 4),
    },
    3: {
        "touching_min": 7,
        "touching_max": 15,
        "kindness_min": 3,
        "warmth_min": 3,
        "release_min": 2,
        "body_min": 3,
        "dialogue_max": 6,
        "high_intensity_max": 4,
        "sample_count_range": (4, 6),
    },
    4: {
        "touching_min": 10,
        "touching_max": 22,
        "kindness_min": 4,
        "warmth_min": 4,
        "release_min": 3,
        "body_min": 4,
        "dialogue_max": 7,
        "high_intensity_max": 7,
        "sample_count_range": (6, 9),
    },
    5: {
        "touching_min": 14,
        "touching_max": 34,
        "kindness_min": 5,
        "warmth_min": 5,
        "release_min": 4,
        "body_min": 5,
        "dialogue_max": 8,
        "high_intensity_max": 99,
        "sample_count_range": (9, 12),
    },
}


TOUCHING_LEVEL_WRITING_GUIDES = {
    1: [
        "只保留一个轻微暖点：递伞、留饭、提醒、等一等、替她挡一下难堪。",
        "人物可以鼻酸或心里一热，但不要大哭、拥抱、人生顿悟或重大和解。",
        "结尾停在安静的暖意，让读者感觉'原来有人注意到了'。",
    ],
    2: [
        "让善意更明确，写出人物被理解、被尊重或被接住的一瞬间。",
        "可以出现眼眶发热、低头笑、轻声道谢，但不要把情绪推到救赎。",
        "重点写具体动作，不要只写抽象抒情。",
    ],
    3: [
        "让陪伴、守护、道歉或支持推动人物情绪转折。",
        "人物可以落泪、拥抱、说出压抑的话，感动与心酸并存。",
        "结尾应出现重新振作、关系松动或心防打开。",
    ],
    4: [
        "加入更深的时间跨度或代价：等了很久、默默承担、长期记挂、关键时刻站出来。",
        "情绪要有强烈共情，但不要靠喊口号或密集哭诉制造煽情。",
        "结尾应形成清晰的和解、被坚定选择或重新相信。",
    ],
    5: [
        "必须让人物处在很深的低谷、孤独、失去信心或人生边缘，再被具体行动托住。",
        "写出'不是所有人都会离开/不是我不值得/我还能继续'这类精神层面的回升。",
        "结尾要温暖有力，落到救赎、希望、关系修复或生命意义确认，不要转成鸡汤独白。",
    ],
}


TOUCHING_CUE_WORDS = [
    "感动",
    "温暖",
    "暖",
    "心酸",
    "柔软",
    "被理解",
    "被看见",
    "被接住",
    "被托住",
    "托住",
    "理解",
    "懂",
    "关心",
    "善意",
    "心疼",
    "陪伴",
    "守护",
    "支持",
    "尊重",
    "接纳",
    "释怀",
    "和解",
    "安心",
    "安定",
    "希望",
    "救赎",
    "重新开始",
    "不再",
    "不是一个人",
]


KINDNESS_CUE_WORDS = [
    "递",
    "塞给",
    "放着",
    "温着",
    "等",
    "陪",
    "握住",
    "抱住",
    "撑伞",
    "夹菜",
    "纸条",
    "早餐",
    "热汤",
    "热饮",
    "奶茶",
    "围巾",
    "相册",
    "照片",
    "消息",
    "道歉",
    "解释",
    "回头",
    "站出来",
]


WARMTH_CUE_WORDS = [
    "热",
    "热气",
    "掌心",
    "怀里",
    "怀抱",
    "灯",
    "雨",
    "伞",
    "笑",
    "轻声",
    "温声",
    "温柔",
    "小心",
    "慢慢",
    "安静",
    "松开",
    "松了一口气",
    "亮",
    "家",
]


RELEASE_CUE_WORDS = [
    "眼泪",
    "哭",
    "笑着哭",
    "哭出来",
    "掉下来",
    "眼眶",
    "鼻酸",
    "哽咽",
    "释然",
    "释怀",
    "松动",
    "松开",
    "放下",
    "抬头",
    "深吸一口气",
    "重新",
    "继续",
]


BODY_REACTION_WORDS = [
    "低头",
    "抬头",
    "停住",
    "怔住",
    "愣住",
    "攥着",
    "捏着",
    "抱着",
    "握住",
    "靠着",
    "眼眶",
    "眼泪",
    "鼻酸",
    "哽咽",
    "笑",
    "哭",
    "深吸",
]


HIGH_INTENSITY_WORDS = [
    "崩溃",
    "绝望",
    "救赎",
    "一辈子",
    "再也",
    "生命",
    "活下去",
    "世界",
    "全部",
    "彻底",
    "边缘",
    "低谷",
]


DEFAULT_SCENE_DRIFT_WORDS = [
    "地铁站",
    "老家厨房",
    "医院",
    "病房",
    "校门口",
    "深夜街口",
    "饭桌",
    "搬家",
    "考场",
    "宠物医院",
    "小店",
    "旧学校",
    "操场",
]


def find_project_root(start_path: str | os.PathLike | None = None) -> Path:
    start = Path(start_path or __file__).resolve()
    for parent in [start.parent, *start.parents]:
        if (parent / "data" / "touching_samples.txt").exists() and (parent / "scripts").exists():
            return parent
    raise FileNotFoundError("未找到包含 data/touching_samples.txt 的项目根目录。")


def normalize_topic_for_filename(topic: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", topic.strip()) if topic else ""
    return cleaned[:40] if cleaned else "默认感动场景"


def load_touching_examples(sample_path: str | os.PathLike | None = None) -> list[str]:
    path = Path(sample_path) if sample_path else find_project_root() / "data" / "touching_samples.txt"
    if not path.exists():
        return []

    raw = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=##\s+感动治愈-)", raw.strip())
    return [block.strip() for block in blocks if block.strip()]


def _extract_score(example: str) -> float:
    match = re.search(r"\*\*评分\*\*:\s*([0-9]+(?:\.[0-9]+)?)", example)
    return float(match.group(1)) if match else 0.0


def pick_examples_for_level(examples: list[str], touching_level: int) -> list[str]:
    if not examples:
        return []

    sorted_examples = sorted(examples, key=_extract_score)
    cfg = TOUCHING_LEVEL_HARD_CONSTRAINTS[touching_level]
    min_count, max_count = cfg["sample_count_range"]
    count = min(max_count, max(min_count, len(sorted_examples)))

    if touching_level <= 2:
        pool = sorted_examples[: max(4, count)]
    elif touching_level == 3:
        mid = len(sorted_examples) // 2
        pool = sorted_examples[max(0, mid - 4): mid + 4]
    else:
        pool = sorted_examples[-max(8, count):]

    return pool[:count]


def estimate_touching_metrics(text: str) -> dict:
    if not text:
        return {
            "touching_hits": 0,
            "kindness_hits": 0,
            "warmth_hits": 0,
            "release_hits": 0,
            "body_hits": 0,
            "high_intensity_hits": 0,
            "dialogue_count": 0,
        }

    dialogue_segments = re.findall(r'[：:]\s*[“"]([^”"]{1,180})[”"]', text)
    return {
        "touching_hits": sum(text.count(word) for word in TOUCHING_CUE_WORDS),
        "kindness_hits": sum(text.count(word) for word in KINDNESS_CUE_WORDS),
        "warmth_hits": sum(text.count(word) for word in WARMTH_CUE_WORDS),
        "release_hits": sum(text.count(word) for word in RELEASE_CUE_WORDS),
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
            "场景锚点不足：必须持续围绕输入场景，不要改成参考样本里的其他感动事件；"
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
    touching_level: int,
    scene_prompt: str | None = None,
) -> tuple[bool, dict, list[str]]:
    cfg = TOUCHING_LEVEL_HARD_CONSTRAINTS[touching_level]
    metrics = estimate_touching_metrics(text)
    reasons = []

    if metrics["touching_hits"] < cfg["touching_min"]:
        reasons.append(f"感动线索过少：当前 {metrics['touching_hits']}，至少 {cfg['touching_min']}。")
    if metrics["touching_hits"] > cfg["touching_max"]:
        reasons.append(f"感动线索过密：当前 {metrics['touching_hits']}，最多 {cfg['touching_max']}。")
    if metrics["kindness_hits"] < cfg["kindness_min"]:
        reasons.append(f"具体善意/行动线索不足：当前 {metrics['kindness_hits']}，至少 {cfg['kindness_min']}。")
    if metrics["warmth_hits"] < cfg["warmth_min"]:
        reasons.append(f"温暖氛围线索不足：当前 {metrics['warmth_hits']}，至少 {cfg['warmth_min']}。")
    if metrics["release_hits"] < cfg["release_min"]:
        reasons.append(f"情绪释放线索不足：当前 {metrics['release_hits']}，至少 {cfg['release_min']}。")
    if metrics["body_hits"] < cfg["body_min"]:
        reasons.append(f"身体反应线索不足：当前 {metrics['body_hits']}，至少 {cfg['body_min']}。")
    if metrics["high_intensity_hits"] > cfg["high_intensity_max"]:
        reasons.append(
            f"高强度词过早或过密：当前 {metrics['high_intensity_hits']}，最多 {cfg['high_intensity_max']}。"
        )
    if metrics["dialogue_count"] > cfg["dialogue_max"]:
        reasons.append(f"对话过多削弱细节感：当前 {metrics['dialogue_count']}，最多 {cfg['dialogue_max']}。")

    if scene_prompt:
        scene_passed, scene_metrics, scene_reasons = validate_scene_consistency(text, scene_prompt)
        metrics.update(scene_metrics)
        if not scene_passed:
            reasons.extend(scene_reasons)

    return len(reasons) == 0, metrics, reasons


def build_touching_level_prompt(
    scene_prompt: str,
    touching_level: int,
    selected_examples: list[str] | None = None,
    retry_feedback: str = "",
) -> str:
    if touching_level not in TOUCHING_LEVEL_RULES:
        raise ValueError(f"不支持的感动等级: {touching_level}")

    cfg = TOUCHING_LEVEL_HARD_CONSTRAINTS[touching_level]
    examples_block = ""
    if selected_examples:
        examples_block = (
            "\n\n【参考样本，仅学习感动治愈情绪的具体动作、温暖节奏和表达质量，严禁复制或替换本次场景】\n"
            "参考样本可能包含地铁、厨房、医院、校门口、饭桌、考场等不同场景；本次输出不得套用样本地点、人物、事件。\n"
            + "\n\n".join(selected_examples)
        )

    feedback_block = ""
    if retry_feedback:
        feedback_block = f"\n\n【上次生成未达标反馈】\n{retry_feedback}\n请针对这些问题重写本等级版本。"

    guide_block = "\n".join(f"- {item}" for item in TOUCHING_LEVEL_WRITING_GUIDES[touching_level])
    length_rule = "500~850 字" if touching_level == 5 else "350~650 字"

    return f"""
请基于同一个场景，写一个【感动强度{touching_level}级】的小说/短剧片段示例。

【固定场景，不得改写】
{scene_prompt}

场景锁定要求：
1. 五个等级必须都发生在上面这个场景中，只允许改变感动强度，不允许改变地点、人物关系、核心事件。
2. 低等级可以只写轻微善意和小小暖意；中高等级逐步增加陪伴、理解、守护、和解、希望回升。
3. 禁止把场景改成参考样本中的地铁站、厨房、医院、校门口、考场、小店、旧学校等其他事件。
4. 参考样本只能学习情绪层次、具体动作、温暖节奏和表达质量，不能借用其地点、人物、事件或道具。

感动强度要求：
{TOUCHING_LEVEL_RULES[touching_level]}

强度刻度：
1. 善意具体度：等级越高，关心越具体、越及时、越能击中人物真正需要。
2. 被理解程度：等级越高，人物越能感到自己不是被敷衍，而是真的被看见、被尊重、被接住。
3. 陪伴/守护强度：等级越高，陪伴越坚定，等待、承担、站出来或不离开的分量越重。
4. 情绪释放：等级越高，从心里一暖、鼻酸，逐步到落泪、拥抱、释怀和重新振作。
5. 收束方式：高等级需要落到和解、救赎、希望重燃或生命意义被重新确认，不要写成空泛鸡汤。

本等级写作边界：
{guide_block}

硬性约束：
1. 只输出正文，长度约 {length_rule}，不要解释规则。
2. 五个等级必须围绕同一场景横向比较，感动强度逐级递增。
3. 感动主要来自具体行动和细节：等待、留饭、递伞、陪伴、纸条、拥抱、道歉、坚定支持等。
4. 避免煽情堆砌、空泛抒情、纯鸡汤说教或过度哭喊，质量优先。
5. 本等级感动线索目标区间：{cfg["touching_min"]}~{cfg["touching_max"]} 处。
6. 本等级具体善意/行动线索至少 {cfg["kindness_min"]} 处，温暖氛围线索至少 {cfg["warmth_min"]} 处。
7. 本等级情绪释放线索至少 {cfg["release_min"]} 处，身体反应线索至少 {cfg["body_min"]} 处。
8. 对话不超过 {cfg["dialogue_max"]} 段；低等级不得提前使用过多“崩溃、绝望、救赎、生命、世界”等高强度表达。
{examples_block}
{feedback_block}
""".strip()


def save_touching_level_outputs(outputs: dict[int, str], scene_prompt: str, output_root: str) -> str:
    topic = normalize_topic_for_filename(scene_prompt)
    target_dir = os.path.join(output_root, f"{topic}_感动五级示例")
    os.makedirs(target_dir, exist_ok=True)

    for level, content in outputs.items():
        file_path = os.path.join(target_dir, f"感动强度{level}级_片段示例.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content or "")
    return target_dir


def generate_touching_level_versions(
    scene_prompt: str,
    generate_func,
    output_root: str,
    max_attempts: int = 3,
) -> tuple[dict[int, str], str]:
    outputs = {}
    examples = load_touching_examples()

    for level in range(1, 6):
        selected_examples = pick_examples_for_level(examples, level)
        print(f"正在生成感动强度 {level} 级版本...")

        best_text = ""
        best_score_gap = 10**9
        retry_feedback = ""
        for attempt in range(1, max_attempts + 1):
            level_prompt = build_touching_level_prompt(
                scene_prompt,
                level,
                selected_examples=selected_examples,
                retry_feedback=retry_feedback,
            )
            candidate = generate_func(level_prompt)
            passed, metrics, reasons = validate_level_output(candidate, level, scene_prompt=scene_prompt)
            print(
                f"等级{level} 第{attempt}次校验 "
                f"touching_hits={metrics['touching_hits']}, "
                f"kindness_hits={metrics['kindness_hits']}, "
                f"warmth_hits={metrics['warmth_hits']}, "
                f"release_hits={metrics['release_hits']}, "
                f"body_hits={metrics['body_hits']}, "
                f"high_intensity_hits={metrics['high_intensity_hits']}, "
                f"dialogue_count={metrics['dialogue_count']}, "
                f"scene_anchor_hits={metrics.get('scene_anchor_hits', 0)}, "
                f"scene_drift_hits={metrics.get('scene_drift_hits', 0)}, passed={passed}"
            )
            if passed:
                best_text = candidate
                break

            cfg = TOUCHING_LEVEL_HARD_CONSTRAINTS[level]
            gap = 0
            if metrics["touching_hits"] < cfg["touching_min"]:
                gap += cfg["touching_min"] - metrics["touching_hits"]
            elif metrics["touching_hits"] > cfg["touching_max"]:
                gap += metrics["touching_hits"] - cfg["touching_max"]
            if metrics["kindness_hits"] < cfg["kindness_min"]:
                gap += cfg["kindness_min"] - metrics["kindness_hits"]
            if metrics["warmth_hits"] < cfg["warmth_min"]:
                gap += cfg["warmth_min"] - metrics["warmth_hits"]
            if metrics["release_hits"] < cfg["release_min"]:
                gap += cfg["release_min"] - metrics["release_hits"]
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

    output_dir = save_touching_level_outputs(outputs, scene_prompt, output_root)
    return outputs, output_dir

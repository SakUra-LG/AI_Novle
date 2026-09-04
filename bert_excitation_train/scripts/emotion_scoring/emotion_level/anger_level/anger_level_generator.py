import os
import re
from pathlib import Path


ANGER_LEVEL_RULES = {
    1: "愤怒强度1级（轻微）：怒意被压住，以失望、冷淡、短促质问和边界感为主，不能爆发成争吵。",
    2: "愤怒强度2级（偏轻）：出现明确不满、反问和局部强硬，但人物仍能控制语气与行动。",
    3: "愤怒强度3级（中等）：愤怒进入明面冲突，语言锋利，有明显揭穿或反击动作。",
    4: "愤怒强度4级（偏强）：压迫与不公升级，人物强硬对峙，证据、规则或后果开始形成清算压力。",
    5: "愤怒强度5级（最强）：怒意主导全段，形成高压揭穿、公开对峙或不可逆清算，但保持叙事逻辑和现实边界。",
}


ANGER_LEVEL_HARD_CONSTRAINTS = {
    1: {
        "anger_min": 2,
        "anger_max": 6,
        "dialogue_min": 1,
        "confrontation_min": 0,
        "action_min": 1,
        "sample_ratio": 0.16,
    },
    2: {
        "anger_min": 4,
        "anger_max": 9,
        "dialogue_min": 2,
        "confrontation_min": 1,
        "action_min": 2,
        "sample_ratio": 0.28,
    },
    3: {
        "anger_min": 7,
        "anger_max": 13,
        "dialogue_min": 3,
        "confrontation_min": 2,
        "action_min": 3,
        "sample_ratio": 0.45,
    },
    4: {
        "anger_min": 10,
        "anger_max": 18,
        "dialogue_min": 4,
        "confrontation_min": 3,
        "action_min": 4,
        "sample_ratio": 0.65,
    },
    5: {
        "anger_min": 14,
        "anger_max": 24,
        "dialogue_min": 4,
        "confrontation_min": 4,
        "action_min": 5,
        "sample_ratio": 1.00,
    },
}


ANGER_CUE_WORDS = [
    "愤怒",
    "怒",
    "怒火",
    "火气",
    "气得",
    "气笑",
    "冷笑",
    "冷声",
    "厉声",
    "发抖",
    "颤",
    "攥紧",
    "握紧",
    "青筋",
    "拍桌",
    "摔",
    "砸",
    "质问",
    "反问",
    "逼问",
    "怒视",
    "盯着",
    "荒唐",
    "过分",
    "欺人太甚",
    "凭什么",
    "不配",
    "闭嘴",
    "道歉",
    "清算",
]


CONFRONTATION_CUE_WORDS = [
    "质问",
    "反问",
    "逼问",
    "揭穿",
    "当众",
    "公开",
    "证据",
    "记录",
    "截图",
    "录音",
    "监控",
    "报警",
    "投诉",
    "律师",
    "判决",
    "追责",
    "道歉",
    "赔偿",
    "清算",
    "别想",
    "一个都",
]


ACTION_CUE_WORDS = [
    "攥",
    "握",
    "拍",
    "摔",
    "砸",
    "关掉",
    "合上",
    "推开",
    "站起",
    "起身",
    "后退",
    "挡",
    "抢过",
    "举起",
    "拿出",
    "调出",
    "放出",
    "撕",
    "退出",
]


def find_project_root(start_path: str | os.PathLike | None = None) -> Path:
    start = Path(start_path or __file__).resolve()
    for parent in [start.parent, *start.parents]:
        if (parent / "data" / "anger_samples.txt").exists() and (parent / "scripts").exists():
            return parent
    raise FileNotFoundError("未找到包含 data/anger_samples.txt 的项目根目录。")


def normalize_topic_for_filename(topic: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", topic.strip()) if topic else ""
    return cleaned[:40] if cleaned else "默认愤怒场景"


def load_anger_examples(sample_path: str | os.PathLike | None = None) -> list[str]:
    path = Path(sample_path) if sample_path else find_project_root() / "data" / "anger_samples.txt"
    if not path.exists():
        return []

    raw = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=##\s+)", raw.strip())
    return [block.strip() for block in blocks if block.strip()]


def pick_examples_for_level(examples: list[str], anger_level: int) -> list[str]:
    if not examples:
        return []
    cfg = ANGER_LEVEL_HARD_CONSTRAINTS[anger_level]
    k = max(2, int(len(examples) * cfg["sample_ratio"]))
    return examples[: min(k, len(examples))]


def estimate_anger_metrics(text: str) -> dict:
    if not text:
        return {
            "anger_hits": 0,
            "dialogue_count": 0,
            "confrontation_hits": 0,
            "action_hits": 0,
        }

    dialogue_segments = re.findall(r'[“"]([^”"]{1,180})[”"]', text)
    return {
        "anger_hits": sum(text.count(word) for word in ANGER_CUE_WORDS),
        "dialogue_count": len(dialogue_segments),
        "confrontation_hits": sum(text.count(word) for word in CONFRONTATION_CUE_WORDS),
        "action_hits": sum(text.count(word) for word in ACTION_CUE_WORDS),
    }


def validate_level_output(text: str, anger_level: int) -> tuple[bool, dict, list[str]]:
    cfg = ANGER_LEVEL_HARD_CONSTRAINTS[anger_level]
    metrics = estimate_anger_metrics(text)
    reasons = []

    if metrics["anger_hits"] < cfg["anger_min"]:
        reasons.append(f"愤怒线索过少：当前 {metrics['anger_hits']}，至少 {cfg['anger_min']}。")
    if metrics["anger_hits"] > cfg["anger_max"]:
        reasons.append(f"愤怒线索过多：当前 {metrics['anger_hits']}，最多 {cfg['anger_max']}。")
    if metrics["dialogue_count"] < cfg["dialogue_min"]:
        reasons.append(f"对峙对白不足：当前 {metrics['dialogue_count']}，至少 {cfg['dialogue_min']} 段。")
    if metrics["confrontation_hits"] < cfg["confrontation_min"]:
        reasons.append(
            f"揭穿/追责/清算线索不足：当前 {metrics['confrontation_hits']}，至少 {cfg['confrontation_min']}。"
        )
    if metrics["action_hits"] < cfg["action_min"]:
        reasons.append(f"愤怒动作线索不足：当前 {metrics['action_hits']}，至少 {cfg['action_min']}。")

    return len(reasons) == 0, metrics, reasons


def build_anger_level_prompt(
    scene_prompt: str,
    anger_level: int,
    selected_examples: list[str] | None = None,
    retry_feedback: str = "",
) -> str:
    if anger_level not in ANGER_LEVEL_RULES:
        raise ValueError(f"不支持的愤怒等级: {anger_level}")

    cfg = ANGER_LEVEL_HARD_CONSTRAINTS[anger_level]
    examples_block = ""
    if selected_examples:
        examples_block = "\n\n【本等级可参考的愤怒样本】\n" + "\n\n".join(selected_examples)

    feedback_block = ""
    if retry_feedback:
        feedback_block = f"\n\n【上次生成未达标反馈】\n{retry_feedback}\n请针对这些问题重写本等级版本。"

    return f"""
请基于同一个场景，写一个【愤怒强度{anger_level}级】的小说/短剧片段示例。

场景需求：
{scene_prompt}

愤怒强度要求：
{ANGER_LEVEL_RULES[anger_level]}

强度刻度：
1. 触发源：等级越高，不公、背刺、羞辱或压迫越具体，伤害越不可轻描淡写。
2. 身体动作：等级越高，攥紧、拍桌、调证据、挡住、撕毁等动作越明确。
3. 对峙语言：等级越高，反问、质问、揭穿、拒绝退让越锋利。
4. 后果推进：等级越高，越要出现追责、公开、报警、投诉、判决、关系决裂等清算压力。

硬性约束：
1. 只输出正文，长度约 350~650 字，不要解释规则。
2. 五个等级必须能围绕同一场景横向比较，且本等级强度要准确。
3. 不要只写普通吵架，要让读者感到不公、压迫、被冒犯后的怒意。
4. 避免无差别暴力、血腥堆砌和失控违法报复；高等级应通过揭穿、对峙、证据和后果制造强度。
5. 本等级愤怒线索目标区间：{cfg["anger_min"]}~{cfg["anger_max"]} 处。
6. 本等级对峙对白至少 {cfg["dialogue_min"]} 段，愤怒动作线索至少 {cfg["action_min"]} 处。
7. 本等级揭穿、追责或清算线索至少 {cfg["confrontation_min"]} 处。
{examples_block}
{feedback_block}
""".strip()


def save_anger_level_outputs(outputs: dict[int, str], scene_prompt: str, output_root: str) -> str:
    topic = normalize_topic_for_filename(scene_prompt)
    target_dir = os.path.join(output_root, f"{topic}_愤怒五级示例")
    os.makedirs(target_dir, exist_ok=True)

    for level, content in outputs.items():
        file_path = os.path.join(target_dir, f"愤怒强度{level}级_片段示例.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content or "")
    return target_dir


def generate_anger_level_versions(
    scene_prompt: str,
    generate_func,
    output_root: str,
    max_attempts: int = 3,
) -> tuple[dict[int, str], str]:
    outputs = {}
    examples = load_anger_examples()

    for level in range(1, 6):
        selected_examples = pick_examples_for_level(examples, level)
        print(f"正在生成愤怒强度 {level} 级版本...")

        best_text = ""
        best_score_gap = 10**9
        retry_feedback = ""
        for attempt in range(1, max_attempts + 1):
            level_prompt = build_anger_level_prompt(
                scene_prompt,
                level,
                selected_examples=selected_examples,
                retry_feedback=retry_feedback,
            )
            candidate = generate_func(level_prompt)
            passed, metrics, reasons = validate_level_output(candidate, level)
            print(
                f"等级{level} 第{attempt}次校验: "
                f"anger_hits={metrics['anger_hits']}, "
                f"dialogue_count={metrics['dialogue_count']}, "
                f"confrontation_hits={metrics['confrontation_hits']}, "
                f"action_hits={metrics['action_hits']}, passed={passed}"
            )
            if passed:
                best_text = candidate
                break

            cfg = ANGER_LEVEL_HARD_CONSTRAINTS[level]
            gap = 0
            if metrics["anger_hits"] < cfg["anger_min"]:
                gap += cfg["anger_min"] - metrics["anger_hits"]
            elif metrics["anger_hits"] > cfg["anger_max"]:
                gap += metrics["anger_hits"] - cfg["anger_max"]
            if metrics["dialogue_count"] < cfg["dialogue_min"]:
                gap += cfg["dialogue_min"] - metrics["dialogue_count"]
            if metrics["confrontation_hits"] < cfg["confrontation_min"]:
                gap += cfg["confrontation_min"] - metrics["confrontation_hits"]
            if metrics["action_hits"] < cfg["action_min"]:
                gap += cfg["action_min"] - metrics["action_hits"]

            if gap < best_score_gap:
                best_score_gap = gap
                best_text = candidate

            retry_feedback = "\n".join(reasons)

        outputs[level] = best_text

    output_dir = save_anger_level_outputs(outputs, scene_prompt, output_root)
    return outputs, output_dir

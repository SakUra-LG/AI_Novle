import os
import re
from pathlib import Path


HUMOR_LEVEL_RULES = {
    1: "幽默强度1级（轻微）：整体偏稳重，只保留少量轻微调侃，笑点点到为止。",
    2: "幽默强度2级（偏轻）：在关键节点外增加少量自然吐槽，保持克制。",
    3: "幽默强度3级（中等）：幽默与主线平衡，允许明显互动和反差，但不能喧宾夺主。",
    4: "幽默强度4级（偏强）：明显提升对白笑点、拆台频率和反差表达。",
    5: "幽默强度5级（最强）：幽默优先，尽可能提高对白抖包袱、拆台互动和反差笑点密度，但不破坏神话骨架。",
}

HUMOR_LEVEL_HARD_CONSTRAINTS = {
    1: {"humor_min": 3, "humor_max": 6, "dialogue_min_ratio": 0.40, "sample_ratio": 0.15},
    2: {"humor_min": 6, "humor_max": 10, "dialogue_min_ratio": 0.50, "sample_ratio": 0.35},
    3: {"humor_min": 10, "humor_max": 14, "dialogue_min_ratio": 0.60, "sample_ratio": 0.55},
    4: {"humor_min": 14, "humor_max": 19, "dialogue_min_ratio": 0.65, "sample_ratio": 0.75},
    5: {"humor_min": 18, "humor_max": 26, "dialogue_min_ratio": 0.70, "sample_ratio": 1.00},
}

HUMOR_CUE_WORDS = [
    "吐槽", "拆台", "互怼", "嘴硬", "反差", "自嘲", "歪楼", "一本正经",
    "忍不住笑", "笑出声", "苦笑", "噎住", "没好气", "白了他一眼",
    "顶回去", "哼声", "打趣", "调侃", "挤兑", "接梗",
]


def find_project_root(start_path: str | None = None) -> Path:
    """Find the bert_excitation_train project root that contains the data directory."""
    start = Path(start_path or __file__).resolve()
    for parent in [start.parent, *start.parents]:
        sample_file = parent / "data" / "humor_punchline_examples.txt"
        scripts_dir = parent / "scripts"
        if sample_file.exists() and scripts_dir.exists():
            return parent
    raise FileNotFoundError("未找到包含 data/humor_punchline_examples.txt 的项目根目录。")


def normalize_topic_for_filename(topic: str) -> str:
    if not topic:
        return "神话改写"
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", topic).strip()
    return cleaned[:40] if cleaned else "神话改写"


def load_punchline_examples(sample_path: str | os.PathLike | None = None) -> list[str]:
    """Load humor dialogue examples from the large project's data directory."""
    path = Path(sample_path) if sample_path else find_project_root() / "data" / "humor_punchline_examples.txt"
    if not path.exists():
        return []

    raw = path.read_text(encoding="utf-8")
    lines = [line for line in raw.splitlines() if not line.strip().startswith("#")]
    text = "\n".join(lines)
    return [block.strip() for block in text.split("---") if block.strip()]


def pick_examples_for_level(examples: list[str], humor_level: int) -> list[str]:
    if not examples:
        return []
    cfg = HUMOR_LEVEL_HARD_CONSTRAINTS[humor_level]
    k = max(1, int(len(examples) * cfg["sample_ratio"]))
    return examples[:k]


def estimate_humor_metrics(text: str) -> dict:
    if not text:
        return {"humor_hits": 0, "dialogue_count": 0, "dialogue_humor_ratio": 0.0}

    humor_hits = sum(text.count(word) for word in HUMOR_CUE_WORDS)
    dialogue_segments = re.findall(r'[“"]([^”"]{1,160})[”"]', text)
    dialogue_count = len(dialogue_segments)
    dialogue_humor_hits = sum(
        segment.count(word)
        for segment in dialogue_segments
        for word in HUMOR_CUE_WORDS
    )
    dialogue_humor_ratio = (dialogue_humor_hits / humor_hits) if humor_hits else 0.0

    return {
        "humor_hits": humor_hits,
        "dialogue_count": dialogue_count,
        "dialogue_humor_ratio": round(dialogue_humor_ratio, 3),
    }


def validate_level_output(text: str, humor_level: int) -> tuple[bool, dict, list[str]]:
    cfg = HUMOR_LEVEL_HARD_CONSTRAINTS[humor_level]
    metrics = estimate_humor_metrics(text)
    reasons = []

    if metrics["humor_hits"] < cfg["humor_min"]:
        reasons.append(f"幽默线索过少：当前 {metrics['humor_hits']}，至少 {cfg['humor_min']}。")
    if metrics["humor_hits"] > cfg["humor_max"]:
        reasons.append(f"幽默线索过多：当前 {metrics['humor_hits']}，最多 {cfg['humor_max']}。")
    if metrics["dialogue_humor_ratio"] < cfg["dialogue_min_ratio"]:
        reasons.append(
            f"对白幽默占比偏低：当前 {metrics['dialogue_humor_ratio']}，至少 {cfg['dialogue_min_ratio']}。"
        )
    if metrics["dialogue_count"] < 4:
        reasons.append(f"对白数量偏少：当前 {metrics['dialogue_count']}，至少 4 段对白。")

    return len(reasons) == 0, metrics, reasons


def build_humor_level_prompt(
    base_prompt: str,
    humor_level: int,
    selected_examples: list[str] | None = None,
    retry_feedback: str = "",
) -> str:
    if humor_level not in HUMOR_LEVEL_RULES:
        raise ValueError(f"不支持的幽默等级: {humor_level}")

    level_rule = HUMOR_LEVEL_RULES[humor_level]
    cfg = HUMOR_LEVEL_HARD_CONSTRAINTS[humor_level]
    examples_block = ""
    if selected_examples:
        examples_block = "\n\n【本等级允许注入的幽默样本】\n" + "\n\n".join(selected_examples)

    feedback_block = ""
    if retry_feedback:
        feedback_block = f"\n\n【上次生成未达标反馈】\n{retry_feedback}\n请针对这些问题重写本等级版本。"

    return f"""
请改写以下神话故事需求，并严格执行指定幽默强度。

原始需求：
{base_prompt}

幽默强度要求：
{level_rule}

额外约束：
1. 保持原神话核心事件链与结局不变。
2. 幽默强度要与本等级匹配，并与其他等级形成明显梯度差异。
3. 仍需保持可读性和完整故事性，只输出故事正文。
4. 全篇幽默线索目标区间：{cfg["humor_min"]}~{cfg["humor_max"]} 处。
5. 幽默优先通过对白完成，幽默对白占比不低于 {cfg["dialogue_min_ratio"]}。
6. 等级越高，拆台、互怼、反差和接梗频率越高。
7. 低等级不要写成高密度互怼，高等级不要只做轻描淡写。
{examples_block}
{feedback_block}
""".strip()


def save_humor_level_outputs(outputs: dict[int, str], base_prompt: str, output_root: str) -> str:
    topic = normalize_topic_for_filename(base_prompt)
    target_dir = os.path.join(output_root, topic)
    os.makedirs(target_dir, exist_ok=True)

    for level, content in outputs.items():
        file_path = os.path.join(target_dir, f"幽默强度{level}级.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content or "")
    return target_dir


def generate_humor_level_versions(
    base_prompt: str,
    generate_func,
    output_root: str,
    max_attempts: int = 3,
) -> tuple[dict[int, str], str]:
    outputs = {}
    examples = load_punchline_examples()

    for level in range(1, 6):
        selected_examples = pick_examples_for_level(examples, level)
        print(f"正在生成幽默强度 {level} 级版本...")

        best_text = ""
        best_score_gap = 10**9
        retry_feedback = ""
        for attempt in range(1, max_attempts + 1):
            level_prompt = build_humor_level_prompt(
                base_prompt,
                level,
                selected_examples=selected_examples,
                retry_feedback=retry_feedback,
            )
            candidate = generate_func(level_prompt)
            passed, metrics, reasons = validate_level_output(candidate, level)
            print(
                f"等级{level} 第{attempt}次校验: "
                f"humor_hits={metrics['humor_hits']}, "
                f"dialogue_ratio={metrics['dialogue_humor_ratio']}, "
                f"dialogue_count={metrics['dialogue_count']}, passed={passed}"
            )
            if passed:
                best_text = candidate
                break

            cfg = HUMOR_LEVEL_HARD_CONSTRAINTS[level]
            gap = 0
            if metrics["humor_hits"] < cfg["humor_min"]:
                gap += cfg["humor_min"] - metrics["humor_hits"]
            elif metrics["humor_hits"] > cfg["humor_max"]:
                gap += metrics["humor_hits"] - cfg["humor_max"]
            if metrics["dialogue_humor_ratio"] < cfg["dialogue_min_ratio"]:
                gap += int((cfg["dialogue_min_ratio"] - metrics["dialogue_humor_ratio"]) * 20)
            if metrics["dialogue_count"] < 4:
                gap += 4 - metrics["dialogue_count"]

            if gap < best_score_gap:
                best_score_gap = gap
                best_text = candidate

            retry_feedback = "\n".join(reasons)

        outputs[level] = best_text

    output_dir = save_humor_level_outputs(outputs, base_prompt, output_root)
    return outputs, output_dir

import os
import re
import sys
from pathlib import Path


def find_project_root(start_path: str | os.PathLike | None = None) -> Path:
    start = Path(start_path or __file__).resolve()
    for parent in [start.parent, *start.parents]:
        if (parent / "data").exists() and (parent / "scripts").exists():
            return parent
    raise FileNotFoundError("未找到包含 data 和 scripts 的项目根目录。")


def normalize_topic_for_filename(topic: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", topic.strip()) if topic else ""
    return cleaned[:40] if cleaned else "默认场景"


def load_sample_blocks(sample_file: str, project_root: Path | None = None) -> list[str]:
    root = project_root or find_project_root()
    path = root / "data" / sample_file
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=##\s+)", text.strip())
    return [block.strip() for block in blocks if block.strip()]


def pick_examples_for_level(examples: list[str], level: int) -> list[str]:
    if not examples:
        return []
    ratios = {1: 0.16, 2: 0.28, 3: 0.40, 4: 0.55, 5: 0.70}
    k = max(2, int(len(examples) * ratios[level]))
    return examples[: min(k, len(examples))]


def prepare_import_path(current_dir: Path) -> Path:
    project_root = find_project_root(current_dir)
    for path in (current_dir, current_dir.parent, project_root / "scripts", project_root):
        path_text = str(path)
        if path_text not in sys.path:
            sys.path.insert(0, path_text)
    return project_root


def get_api_key() -> str:
    env_key = os.environ.get("DASHSCOPE_API_KEY")
    if env_key:
        return env_key

    for module_name in ("generate_chapter_content", "manual_generator", "emotion_guided_generator"):
        try:
            module = __import__(module_name)
            api_key = getattr(module, "API_Key_QW", "")
            if api_key:
                return api_key
        except Exception:
            continue
    raise RuntimeError("未找到 DASHSCOPE_API_KEY，也无法从项目脚本中读取 API_Key_QW。")


def call_qwen(messages: list[dict], max_tokens: int = 1200, max_retries: int = 3) -> str:
    try:
        import dashscope
    except ImportError as exc:
        raise RuntimeError("缺少 dashscope 依赖，请先安装项目 requirements.txt。") from exc

    dashscope.api_key = get_api_key()
    last_error = None
    for _ in range(max_retries):
        try:
            response = dashscope.Generation.call(
                model=dashscope.Generation.Models.qwen_turbo,
                messages=messages,
                temperature=0.85,
                top_p=0.9,
                repetition_penalty=1.12,
                result_format="message",
                max_tokens=max_tokens,
            )
            if "output" in response and "choices" in response["output"]:
                return response["output"]["choices"][0]["message"]["content"].strip()
            last_error = f"返回格式异常: {response}"
        except Exception as exc:
            last_error = str(exc)
    return f"生成失败：{last_error}"


def build_level_prompt(
    emotion_name: str,
    scene_prompt: str,
    level: int,
    level_rules: dict[int, str],
    examples: list[str],
    extra_requirements: list[str],
) -> str:
    examples_block = ""
    selected_examples = pick_examples_for_level(examples, level)
    if selected_examples:
        examples_block = "\n\n【可参考样本】\n" + "\n\n".join(selected_examples)

    requirements = "\n".join(f"{idx}. {item}" for idx, item in enumerate(extra_requirements, start=1))
    return f"""
请基于下面的场景需求，写一个【单段场景示例】：
{scene_prompt}

目标情绪：{emotion_name}
情绪强度等级：{level}级
等级说明：{level_rules[level]}

硬性要求：
{requirements}
{examples_block}
""".strip()


def save_level_outputs(
    outputs: dict[int, str],
    emotion_name: str,
    scene_prompt: str,
    current_dir: Path,
) -> str:
    safe_name = normalize_topic_for_filename(scene_prompt)
    target_dir = current_dir / "output" / f"{safe_name}_{emotion_name}五级示例"
    target_dir.mkdir(parents=True, exist_ok=True)
    for level, text in outputs.items():
        path = target_dir / f"{emotion_name}强度{level}级_片段示例.txt"
        path.write_text(text or "", encoding="utf-8")
    return str(target_dir)


def run_emotion_level_generation(
    *,
    current_dir: Path,
    emotion_name: str,
    sample_file: str,
    default_scene: str,
    level_rules: dict[int, str],
    system_prompt: str,
    extra_requirements: list[str],
) -> None:
    project_root = prepare_import_path(current_dir)
    user_scene = input(f"请输入{emotion_name}场景提示词（直接回车使用默认场景）：").strip()
    scene_prompt = user_scene or default_scene

    if user_scene:
        print(f"使用指定场景：{scene_prompt}")
    else:
        print(f"使用默认场景：{scene_prompt}")

    examples = load_sample_blocks(sample_file, project_root)
    outputs = {}
    for level in range(1, 6):
        print(f"正在生成{emotion_name}强度{level}级片段示例...")
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": build_level_prompt(
                    emotion_name,
                    scene_prompt,
                    level,
                    level_rules,
                    examples,
                    extra_requirements,
                ),
            },
        ]
        outputs[level] = call_qwen(messages)

    output_dir = save_level_outputs(outputs, emotion_name, scene_prompt, current_dir)
    print(f"\n=== {emotion_name}强度1~5级片段示例生成完成 ===")
    print(f"输出目录：{output_dir}")

    for level in range(1, 6):
        print(f"\n--- {emotion_name}强度{level}级 ---\n")
        print(outputs[level])

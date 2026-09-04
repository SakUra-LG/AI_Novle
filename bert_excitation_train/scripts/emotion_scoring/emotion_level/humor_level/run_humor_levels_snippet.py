import os
import sys
from pathlib import Path

from bert_excitation_train.scripts.emotion_scoring.emotion_level.humor_level.humor_level_generator import (
    HUMOR_LEVEL_RULES,
    find_project_root,
    load_punchline_examples,
    normalize_topic_for_filename,
    pick_examples_for_level,
)


def _prepare_import_path() -> Path:
    current_dir = Path(__file__).resolve().parent
    project_root = find_project_root(current_dir)
    scripts_dir = project_root / "scripts"
    for path in (current_dir, scripts_dir, project_root):
        path_text = str(path)
        if path_text not in sys.path:
            sys.path.insert(0, path_text)
    return current_dir


def _get_api_key() -> str:
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


def _call_qwen(messages: list[dict], max_retries: int = 3) -> str:
    try:
        import dashscope
    except ImportError as exc:
        raise RuntimeError("缺少 dashscope 依赖，请先安装项目 requirements.txt。") from exc

    dashscope.api_key = _get_api_key()
    last_error = None
    for _ in range(max_retries):
        try:
            response = dashscope.Generation.call(
                model=dashscope.Generation.Models.qwen_turbo,
                messages=messages,
                temperature=0.85,
                top_p=0.9,
                repetition_penalty=1.15,
                result_format="message",
                max_tokens=1200,
            )
            if "output" in response and "choices" in response["output"]:
                return response["output"]["choices"][0]["message"]["content"].strip()
            last_error = f"返回格式异常: {response}"
        except Exception as exc:
            last_error = str(exc)
    return f"生成失败：{last_error}"


def _build_level_prompt(user_scene_prompt: str, level: int, examples: list[str]) -> str:
    examples_block = ""
    selected_examples = pick_examples_for_level(examples, level)
    if selected_examples:
        examples_block = "\n\n【可参考的幽默样本】\n" + "\n\n".join(selected_examples)

    return f"""
请基于下面这个“神话改写片段需求”，只写一个【单段场景示例】：
{user_scene_prompt}

幽默等级要求：{level}级
等级说明：{HUMOR_LEVEL_RULES[level]}

硬性要求：
1. 只写这一个片段，长度约 350~650 字。
2. 保留神话语境，不要写成现代职场段子。
3. 从1级到5级要有明显梯度：级别越高，吐槽、互怼、拆台、反差和接梗越多。
4. 只输出正文，不要解释。
{examples_block}
""".strip()


def _save_outputs(outputs: dict[int, str], user_scene_prompt: str, current_dir: Path) -> str:
    safe_name = normalize_topic_for_filename(user_scene_prompt)
    target_dir = current_dir / "output" / f"{safe_name}_片段示例"
    target_dir.mkdir(parents=True, exist_ok=True)
    for level, text in outputs.items():
        path = target_dir / f"幽默强度{level}级_片段示例.txt"
        path.write_text(text or "", encoding="utf-8")
    return str(target_dir)


def main() -> None:
    current_dir = _prepare_import_path()
    user_scene_prompt = input("请输入要改写的神话情节片段提示词：").strip()
    if not user_scene_prompt:
        print("输入为空，已取消。")
        return

    examples = load_punchline_examples()
    outputs = {}
    for level in range(1, 6):
        print(f"正在生成幽默强度{level}级片段示例...")
        messages = [
            {"role": "system", "content": "你是神话改写作者，擅长同一情节的多等级幽默改写。"},
            {"role": "user", "content": _build_level_prompt(user_scene_prompt, level, examples)},
        ]
        outputs[level] = _call_qwen(messages)

    output_dir = _save_outputs(outputs, user_scene_prompt, current_dir)
    print("\n=== 片段示例生成完成 ===")
    print(f"输出目录：{output_dir}")

    for level in range(1, 6):
        print(f"\n--- 幽默强度{level}级（片段示例）---\n")
        print(outputs[level])


if __name__ == "__main__":
    main()

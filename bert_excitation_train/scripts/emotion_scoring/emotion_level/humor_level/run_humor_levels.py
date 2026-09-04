import os
import sys
from pathlib import Path

from bert_excitation_train.scripts.emotion_scoring.emotion_level.humor_level.humor_level_generator import find_project_root, generate_humor_level_versions


def _prepare_import_path() -> tuple[Path, Path]:
    current_dir = Path(__file__).resolve().parent
    project_root = find_project_root(current_dir)
    scripts_dir = project_root / "scripts"
    for path in (current_dir, scripts_dir, project_root):
        path_text = str(path)
        if path_text not in sys.path:
            sys.path.insert(0, path_text)
    return current_dir, project_root


def _get_api_key() -> str:
    env_key = os.environ.get("DASHSCOPE_API_KEY")
    if env_key:
        return env_key

    # Keep compatibility with this project, where several generation scripts
    # define API_Key_QW locally instead of in a shared config file.
    for module_name in ("generate_chapter_content", "manual_generator", "emotion_guided_generator"):
        try:
            module = __import__(module_name)
            api_key = getattr(module, "API_Key_QW", "")
            if api_key:
                return api_key
        except Exception:
            continue
    raise RuntimeError("未找到 DASHSCOPE_API_KEY，也无法从项目脚本中读取 API_Key_QW。")


def _call_qwen(prompt: str) -> str:
    try:
        import dashscope
    except ImportError as exc:
        raise RuntimeError("缺少 dashscope 依赖，请先安装项目 requirements.txt。") from exc

    dashscope.api_key = _get_api_key()
    messages = [
        {"role": "system", "content": "你是神话改写作者，擅长按指定幽默强度生成同一故事的多版本文本。"},
        {"role": "user", "content": prompt},
    ]
    response = dashscope.Generation.call(
        model=dashscope.Generation.Models.qwen_turbo,
        messages=messages,
        temperature=0.85,
        top_p=0.9,
        repetition_penalty=1.15,
        result_format="message",
        max_tokens=1800,
    )
    if "output" in response and "choices" in response["output"]:
        return response["output"]["choices"][0]["message"]["content"].strip()
    return f"生成失败：返回格式异常 {response}"


def main() -> None:
    current_dir, _ = _prepare_import_path()
    prompt = input("请输入要改写的神话故事提示词：").strip()
    if not prompt:
        print("输入为空，已取消。")
        return

    output_root = current_dir / "output"
    outputs, output_dir = generate_humor_level_versions(prompt, _call_qwen, str(output_root))

    print("\n=== 幽默强度1~5级已生成 ===")
    print(f"输出目录：{output_dir}\n")
    for level in range(1, 6):
        print(f"\n--- 幽默强度{level}级 ---\n")
        print(outputs.get(level, ""))


if __name__ == "__main__":
    main()

import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
PARENT_DIR = CURRENT_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))

from bert_excitation_train.scripts.emotion_scoring.emotion_level.emotion_level_generator import run_emotion_level_generation


HORROR_LEVEL_RULES = {
    1: "轻微恐怖：只营造不安和异常感，不直接惊吓。",
    2: "偏轻恐怖：出现明确反常线索，人物开始警觉和害怕。",
    3: "中等恐怖：威胁逐步逼近，有反转或感知错乱，压迫感明显。",
    4: "偏强恐怖：空间封闭、未知追踪或身份错位升级，读者应感到紧绷。",
    5: "最强恐怖：恐惧集中爆发，形成高压收束或强反转，但不依赖血腥堆砌。",
}

DEFAULT_SCENE = "主角深夜独自在旧公寓电梯里，电梯停在不存在的楼层，监控屏里出现了另一个和她一模一样的人。"

EXTRA_REQUIREMENTS = [
    "只写一个完整片段，长度约 350~650 字。",
    "五个等级必须围绕同一个场景生成，恐怖强度逐级递增。",
    "恐怖主要来自氛围、异常规则、空间压迫、未知窥视和心理恐惧。",
    "避免过度血腥，优先写惊悚、阴冷、不安和危机逼近。",
    "只输出正文，不要解释规则。",
]


def main() -> None:
    run_emotion_level_generation(
        current_dir=CURRENT_DIR,
        emotion_name="恐怖",
        sample_file="horror_thriller_samples.txt",
        default_scene=DEFAULT_SCENE,
        level_rules=HORROR_LEVEL_RULES,
        system_prompt="你是惊悚悬疑小说片段作者，擅长把同一场景改写成不同强度的恐怖情绪。",
        extra_requirements=EXTRA_REQUIREMENTS,
    )


if __name__ == "__main__":
    main()

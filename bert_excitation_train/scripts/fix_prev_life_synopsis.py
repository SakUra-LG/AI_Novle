#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上一世故事线修正器
将「就像当年」「就像之前」式概括改写为「完整受害链条」，
强制采用无知视角：当时的她并不知道自己被做局，逐步发现不对，最后吃亏。

升级版（2026-03）：读取 master_ctx(_final) 的断点/绑定信息，按章节输出 JSON 上一世受害卡到 prev_life_ctx_final.txt（不覆盖源文件）。
"""

import os
import re
import argparse
from datetime import datetime
from pathlib import Path
import json
from typing import Dict, List, Optional, Tuple

import dashscope

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_ROOT / "outputs"
PREV_LIFE_FILE = OUTPUT_DIR / "prev_life_ctx.txt"
PREV_LIFE_FINAL_FILE = OUTPUT_DIR / "prev_life_ctx_final.txt"
MASTER_FINAL_FILE = OUTPUT_DIR / "master_ctx_final.txt"

API_Key_QW = os.environ.get("DASHSCOPE_API_KEY", "sk-a2966f4e37134351904851679884cb67")
MAX_TOKENS = 8192


def call_qianwen_api(messages, temperature=0.7, top_p=0.85, repetition_penalty=1.1):
    """调用通义千问 API"""
    dashscope.api_key = API_Key_QW
    try:
        response = dashscope.Generation.call(
            model=dashscope.Generation.Models.qwen_turbo,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            result_format="message",
            max_tokens=MAX_TOKENS,
        )
        if "output" in response and "choices" in response["output"]:
            return response["output"]["choices"][0]["message"]["content"].replace("```", "").strip()
        return None
    except Exception as e:
        print(f"API 调用出错: {e}")
        return None


def parse_prev_life_ctx(content: str) -> list:
    """解析 prev_life_ctx（旧格式），返回 [(chapter_id, content), ...]"""
    lines = content.strip().split("\n")
    entries = []
    for line in lines:
        if not line.strip():
            continue
        m = re.search(r'第(\d+)章对应线索[：:]\s*(.+)', line)
        if m:
            ch = int(m.group(1))
            body = m.group(2).strip()
            # 去掉末尾的（对应今生第X章）
            body = re.sub(r'（对应今生第\d+章）\s*$', '', body).strip()
            entries.append((ch, body))
    return entries


def critic_prev_life_card(obj: Dict) -> Tuple[bool, List[str]]:
    """
    对修正后的上一世梗概进行 Critic 检查。
    返回 (pass: bool, issues: list)
    """
    issues = []
    required_keys = [
        "chapter_id",
        "past_event_title",
        "past_identity_state",
        "setup",
        "deception",
        "victim_process",
        "collapse_point",
        "humiliation_result",
        "emotion_core",
        "present_relevance",
    ]
    for k in required_keys:
        if k not in obj:
            issues.append(f"缺少字段: {k}")

    # 禁止：概括句 & 全知
    text_blob = json.dumps(obj, ensure_ascii=False)
    if any(kw in text_blob for kw in ["就像当年", "就像之前", "曾经也是", "她想起过去", "和当年一样"]):
        issues.append("禁止使用「就像当年/就像之前」式概括")
    if any(kw in text_blob for kw in ["组长故意陷害", "我知道他在做局", "他就是想让我背锅", "她早就知道"]):
        issues.append("禁止全知视角措辞，应采用当时不知道的语气")

    vp = obj.get("victim_process")
    if not isinstance(vp, list) or len(vp) < 3:
        issues.append("victim_process 过少（建议至少 3 条）")
    return len(issues) == 0, issues


def build_fix_prev_life_system_prompt():
    """构建修正上一世故事线的系统提示词（输出 JSON 受害卡）"""
    return """
你是「重生复仇短剧」的上一世故事线修正专家。你的任务是将概括式、空洞的上一世描述改写为**完整受害链条**。

【核心规则】
- **必须采用无知视角**：当时的她并不知道自己被做局，只是在做事过程中逐步发现不对，最后吃亏。
- **禁止概括句**：若出现「就像当年」「就像之前」「曾经也是」等，必须重写为具体发生过的委屈事件。
- **禁止全知总结**：不能写「组长故意陷害我」「我知道他在做局」——应写「我当时以为他是真想提拔我」「接手后才发现不对」「直到领导发火才明白自己被推出来挡枪」。

【受害链条四步必须齐全】
1. **诱导/伪装善意**：对方以什么名义让她接手（如「这次想给你个机会」「让你在领导面前露脸」）
2. **主角误信并接手**：她当时相信了，接手了任务/项目
3. **过程中逐渐发现不对**：熬夜核对、越做越发现漏洞、以为是自己能力不够不敢声张
4. **最终结果落到主角头上**：汇报时被当众推责、被领导训斥、同事围观议论、绩效受损等

【羞辱落点必须具体】
委屈不是抽象情绪，必须落到具体后果：被领导当众骂、被同事议论、被取消名额、被推责背锅、被赶出会议室等。

【输出 JSON 结构（严格 JSON，可被 json.loads 解析）】
每章输出 1 行，格式：
第X章对应线索：{JSON}

JSON 结构固定为：
{
  "chapter_id": 37,
  "past_event_title": "一句话事件标题（具体）",
  "past_identity_state": "上一世此时主角身份/心态（如：刚转正、信任上司）",
  "setup": "诱导/伪装善意：对方以何名义让她接手",
  "deception": "她接手时不知道的关键陷阱（时间/错误/证据缺失）",
  "victim_process": [
    "过程1（逐步发现不对）",
    "过程2",
    "过程3（至少3条）"
  ],
  "collapse_point": "崩塌点：在什么场景下被推责/扣帽子",
  "humiliation_result": "具体后果：被训斥/议论/绩效受损/失去机会等",
  "emotion_core": "被利用、委屈、后知后觉、无力自证（可组合）",
  "present_relevance": "这一世为什么能识别同样信号/如何成为反制依据",
  "binding": {
    "shared_trigger": "...",
    "past_core_harm": "...",
    "present_counterstrike": "..."
  }
}

【重要限制】
- 禁止“就像当年/就像之前/她想起过去”等概括句
- 禁止全知总结（不能写“我知道他在做局”），应写“我当时以为…/接手后才发现…/直到…才明白…”等无知视角
- 必须包含受害链条四步（诱导→误信接手→逐渐发现→最终背锅/受辱）

【输出格式】
严格输出多行，每行格式为：
第X章对应线索：{JSON}
不要输出 markdown，不要解释思路，不要输出多余前后缀。
"""


def _extract_prev_json_from_line(line: str) -> Optional[Tuple[int, Dict]]:
    m = re.search(r"第(\d+)章对应线索\s*[：:]\s*(\{.*\})\s*$", line.strip())
    if not m:
        return None
    ch = int(m.group(1))
    raw_json = m.group(2)
    try:
        obj = json.loads(raw_json)
        return ch, obj
    except Exception:
        return None


def fix_prev_life_batch(entries_by_ch: Dict[int, str], master_cards: Dict[int, Dict], batch_size: int = 8) -> Dict[int, Dict]:
    """分批调用 API 生成/修正上一世受害卡（JSON）"""
    chapters = sorted(master_cards.keys())
    result: Dict[int, Dict] = {}
    for i in range(0, len(chapters), batch_size):
        batch_chs = chapters[i : i + batch_size]
        batch_text = []
        for ch in batch_chs:
            card = master_cards.get(ch, {})
            present = card.get("present", {}) if isinstance(card.get("present"), dict) else {}
            binding = card.get("binding", {}) if isinstance(card.get("binding"), dict) else {}
            seed = entries_by_ch.get(ch, "")
            batch_text.append(
                "第{ch}章\n"
                "今生章节卡摘要：{main}\n"
                "回忆触发器：{trig}\n"
                "绑定：shared_trigger={st}；past_core_harm={pch}；present_counterstrike={pc}\n"
                "原始上一世线索（可为空）：{seed}\n".format(
                    ch=ch,
                    main=str(present.get("present_mainline", ""))[:120],
                    trig=str(present.get("flashback_trigger", ""))[:80],
                    st=str(binding.get("shared_trigger", ""))[:80],
                    pch=str(binding.get("past_core_harm", ""))[:80],
                    pc=str(binding.get("present_counterstrike", ""))[:80],
                    seed=seed,
                )
            )
        user_content = (
            "以下是若干章节的今生章节卡摘要与绑定信息。请为每章输出对应的上一世受害卡 JSON，严格按系统格式逐章输出。\n\n"
            + "\n".join(batch_text)
        )
        messages = [
            {"role": "system", "content": build_fix_prev_life_system_prompt()},
            {"role": "user", "content": user_content},
        ]
        resp = call_qianwen_api(messages)
        if not resp:
            continue
        for line in resp.split("\n"):
            extracted = _extract_prev_json_from_line(line)
            if not extracted:
                continue
            ch, obj = extracted
            if isinstance(obj, dict) and obj.get("chapter_id") != ch:
                obj["chapter_id"] = ch
            ok, issues = critic_prev_life_card(obj) if isinstance(obj, dict) else (False, ["非 dict JSON"])
            if not ok and issues:
                print(f"  ⚠ 第{ch}章 Critic: {issues}")
            result[ch] = obj
    return result


def load_master_cards(master_path: Path) -> Dict[int, Dict]:
    """加载 master_ctx_final（JSON 章节卡）。如果不是 JSON，将尽量跳过。"""
    if not master_path.exists():
        return {}
    raw = master_path.read_text(encoding="utf-8")
    cards: Dict[int, Dict] = {}
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.search(r"第(\d+)章\s*[：:]\s*(\{.*\})\s*$", line)
        if not m:
            continue
        ch = int(m.group(1))
        try:
            obj = json.loads(m.group(2))
            if isinstance(obj, dict):
                cards[ch] = obj
        except Exception:
            continue
    return cards


def _is_current_timeline_only_from_card(card: Dict) -> bool:
    present = card.get("present", {}) if isinstance(card.get("present"), dict) else {}
    if isinstance(present.get("need_prev_life"), bool):
        return not present.get("need_prev_life")
    # fallback：按关键词判断
    outline = json.dumps(card, ensure_ascii=False)
    current_only_keywords = ["ICU", "病房", "濒死", "归零", "睁不开眼", "重生", "醒来", "苏醒", "复苏", "日记本"]
    return any(k in outline for k in current_only_keywords) and not present.get("flashback_trigger")


def run_fix_prev_life_synopsis(
    prev_life_path: str = None,
    master_path: str = None,
    output_path: str = None,
    batch_size: int = 10,
):
    """执行上一世故事线修正（输出 prev_life_ctx_final.txt，不覆盖源文件）"""
    prev_path = Path(prev_life_path or PREV_LIFE_FILE)
    # 优先用 master_ctx_final
    master_path = Path(master_path) if master_path else (MASTER_FINAL_FILE if MASTER_FINAL_FILE.exists() else (OUTPUT_DIR / "master_ctx.txt"))
    output_path = Path(output_path or PREV_LIFE_FINAL_FILE)

    if not prev_path.exists():
        print(f"❌ 未找到文件: {prev_path}")
        return False

    with open(prev_path, "r", encoding="utf-8") as f:
        raw = f.read()

    entries = parse_prev_life_ctx(raw)
    entries_by_ch = {ch: txt for ch, txt in entries}

    master_cards_all = load_master_cards(master_path)
    if not master_cards_all:
        print(f"❌ 未能从 {master_path} 加载 JSON 章节卡（请先运行 fix_master_synopsis.py 生成 master_ctx_final.txt）")
        return False

    # 过滤：跳过当前时间线章节（不需要回忆断点）
    master_cards = {ch: card for ch, card in master_cards_all.items() if not _is_current_timeline_only_from_card(card)}
    print(f"📖 已加载 {len(master_cards_all)} 章今生章节卡，其中 {len(master_cards)} 章需要生成上一世受害卡（其余跳过）")

    fixed_cards = fix_prev_life_batch(entries_by_ch, master_cards, batch_size=batch_size)

    out_lines: List[str] = []
    missing = []
    for ch in sorted(master_cards.keys()):
        obj = fixed_cards.get(ch)
        if not isinstance(obj, dict):
            missing.append(ch)
            continue
        out_lines.append(f"第{ch}章对应线索：" + json.dumps(obj, ensure_ascii=False))

    if missing:
        print(f"⚠️  以下章节未生成有效 JSON 上一世受害卡，将跳过：{missing[:15]}{'...' if len(missing) > 15 else ''}")

    out_content = "\n".join(out_lines) + ("\n" if out_lines else "")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = output_path.parent / f"{output_path.stem}_backup_{ts}{output_path.suffix}"
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(output_path.read_text(encoding="utf-8"))
        print(f"📝 已备份旧的输出文件到: {backup_path}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(out_content)
    print(f"✅ 修正结果已写入: {output_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="上一世故事线修正器")
    parser.add_argument("--input", default=None, help="输入的 prev_life_ctx 文件路径（默认 outputs/prev_life_ctx.txt）")
    parser.add_argument("--master", default=None, help="master_ctx_final 文件路径（默认 outputs/master_ctx_final.txt，若不存在则退回 master_ctx.txt）")
    parser.add_argument("--output", default=None, help="输出路径（默认 outputs/prev_life_ctx_final.txt，不覆盖源文件）")
    parser.add_argument("--batch-size", type=int, default=8, help="每批处理章节数（默认 8）")
    args = parser.parse_args()
    run_fix_prev_life_synopsis(args.input, args.master, args.output, args.batch_size)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章节梗概修正器（修「这一世」）
将「一句话章节梗概」强制改写为「可直接驱动正文生成的章节执行卡」，
补全：当前事件、冲突方、主角目标、回忆触发器、复仇动作、结尾钩子等 6 字段以上。

升级版（2026-03）：支持将「第N-M章」这种阶段梗概拆分为多章节拍卡，并输出到 master_ctx_final.txt（不覆盖源文件）。
"""

import os
import re
import argparse
from datetime import datetime
from pathlib import Path
import json
from typing import Dict, List, Optional, Tuple

# 复用 generate_outline_rebirth_revenge 的 API 调用
import dashscope

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_ROOT / "outputs"
OUTLINE_FILE = OUTPUT_DIR / "master_ctx.txt"
OUTLINE_FINAL_FILE = OUTPUT_DIR / "master_ctx_final.txt"

API_Key_QW = os.environ.get("DASHSCOPE_API_KEY", "sk-a2966f4e37134351904851679884cb67")
MAX_TOKENS = 8192


def call_qianwen_api(messages, temperature=0.2, top_p=0.7, repetition_penalty=1.05):
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


def build_chapter_to_original(segments: List[Dict]) -> Dict[int, str]:
    """从 segments 建立 chapter_id -> 原文 的映射"""
    chapter_to_text: Dict[int, str] = {}
    for seg in segments:
        text = seg.get("text", "").strip()
        for ch in range(seg["start"], seg["end"] + 1):
            chapter_to_text[ch] = text
    return chapter_to_text


def build_minimal_card(ch: int, original_text: str) -> Dict:
    """从原文生成最小可用的 JSON 章节卡（用于缺失章节的补齐）"""
    summary = (original_text[:80] + "…") if len(original_text) > 80 else original_text
    return {
        "chapter_id": ch,
        "present": {
            "present_mainline": summary,
            "scene": "见原文",
            "present_goal": "按原文推进",
            "surface_conflict": "",
            "hidden_truth": "",
            "flashback_trigger": "",
            "flashback_breakpoint": "beats[1]之后",
            "need_prev_life": "回忆" in original_text or "上一世" in original_text,
            "past_ratio_max": 0.35,
            "revenge_action": "按原文推进",
            "beats": [
                "开场",
                "发展",
                "高潮",
                "结尾",
                "悬念",
            ],
            "emotion_curve": "见原文",
            "ending_hook": "见原文",
        },
        "binding": {
            "shared_trigger": "",
            "past_core_harm": "",
            "present_counterstrike": "",
        },
    }


def _expand_card_from_original(obj: Dict, original_text: str) -> Dict:
    """对仅有 binding 的卡，从原文补齐 present"""
    present = obj.get("present") if isinstance(obj.get("present"), dict) else {}
    if present and present.get("present_mainline") and isinstance(present.get("beats"), list) and len(present.get("beats", [])) >= 3:
        return obj  # 已有完整 present
    binding = obj.get("binding") or {}
    summary = (original_text[:100] + "…") if len(original_text) > 100 else original_text
    present = {
        "present_mainline": summary,
        "scene": "见原文",
        "present_goal": "按原文推进",
        "surface_conflict": binding.get("past_core_harm", ""),
        "hidden_truth": "",
        "flashback_trigger": binding.get("shared_trigger", ""),
        "flashback_breakpoint": "beats[2]之后",
        "need_prev_life": bool(binding.get("shared_trigger")),
        "past_ratio_max": 0.35,
        "revenge_action": binding.get("present_counterstrike", "按原文推进"),
        "beats": ["开场", "发展", "高潮", "结尾", "悬念"],
        "emotion_curve": "见原文",
        "ending_hook": "见原文",
    }
    obj["present"] = present
    return obj


def parse_master_segments(content: str) -> List[Dict]:
    """
    解析 master_ctx 原始内容为段落 segments。
    - 单章（旧版）：第N章 ：标题：内容
    - 单章（新版）：第N章 标题：内容
    - 跨章：第N-M章 标题：内容（表示该情节需要多章展开）
    返回：[{type, start, end, text, raw_line}]
    """
    lines = [ln.rstrip() for ln in content.split("\n") if ln.strip()]
    segments: List[Dict] = []
    for line in lines:
        m_range = re.search(r"第(\d+)-(\d+)章\s*(.+)", line)
        if m_range:
            start, end = int(m_range.group(1)), int(m_range.group(2))
            rest = m_range.group(3).strip()
            segments.append(
                {
                    "type": "range",
                    "start": start,
                    "end": end,
                    "text": rest,
                    "raw_line": line,
                }
            )
            continue

        # 兼容两种格式：
        # 1）第N章 ：标题：内容
        # 2）第N章 标题：内容
        m_single = re.search(r"第(\d+)章\b\s*(.+)", line)
        if m_single:
            ch = int(m_single.group(1))
            rest = m_single.group(2).strip()
            segments.append(
                {
                    "type": "single",
                    "start": ch,
                    "end": ch,
                    "text": rest,
                    "raw_line": line,
                }
            )
            continue
    return segments


def critic_master_card(obj: Dict) -> Tuple[bool, List[str]]:
    """
    对修正后的章节梗概进行 Critic 检查。
    返回 (pass: bool, issues: list)
    """
    issues = []
    present = obj.get("present") if isinstance(obj.get("present"), dict) else {}
    binding = obj.get("binding") if isinstance(obj.get("binding"), dict) else {}
    need_prev = present.get("need_prev_life", True)

    # present 必须包含核心字段（仅有 binding 的卡片会由后处理补齐 present）
    required_present = ["present_mainline", "scene", "beats"]
    for k in required_present:
        if k not in present:
            issues.append(f"present 缺少字段: {k}")

    beats = present.get("beats")
    if isinstance(beats, list) and len(beats) < 3:
        issues.append("beats 过少（建议至少 3 条节拍）")

    if isinstance(present.get("revenge_action"), str):
        if any(x in present["revenge_action"] for x in ["她决定反击", "她不会再忍", "要让他们付出代价"]):
            issues.append("revenge_action 过于口号化")
    # 修正 revenue_action 拼写
    if "revenue_action" in present and "revenge_action" not in present:
        present["revenge_action"] = present.pop("revenue_action", "")

    if need_prev and isinstance(present.get("flashback_trigger"), str):
        if any(x in present["flashback_trigger"] for x in ["就像当年", "就像之前"]):
            issues.append("flashback_trigger 不应使用概括句")

    # binding 在 need_prev_life=true 时建议有，但不强制
    if need_prev:
        for k in ["shared_trigger", "past_core_harm", "present_counterstrike"]:
            if k not in binding:
                issues.append(f"binding 建议补全: {k}")
    return len([i for i in issues if "缺少" in i or "过少" in i]) == 0, issues


def build_fix_master_system_prompt():
    """构建修正这一世章节梗概的系统提示词（输出 JSON 章节卡）"""
    return """
你是「重生复仇短剧」的章节梗概修正专家。你的任务是将宽泛的一句话梗概改写为**可直接驱动正文生成**的章节执行卡。

【修正目标】
你必须输出**严格的 JSON**（双引号、可被 json.loads 解析），并且每章 1 行。

每章 JSON 结构固定为：
{
  "chapter_id": 37,
  "present": {
    "present_mainline": "这一世本章主要事件（可执行、可拍）",
    "scene": "具体场景（地点/时间段/氛围）",
    "present_goal": "女主本章目标（可验证）",
    "surface_conflict": "表层冲突（谁在坑/怎么坑）",
    "hidden_truth": "隐情/局点（时间压力/关键错误/关键证据）",
    "flashback_trigger": "触发上一世回忆的具体锚点（物/话/场景）",
    "flashback_breakpoint": "建议在第几个节拍后插入回忆（例如：beats[2]之后）",
    "need_prev_life": true/false,
    "past_ratio_max": 0.35,
    "revenge_action": "本章具体反制动作（禁止口号，必须动作+证据/机制）",
    "beats": ["节拍1", "节拍2", "...至少5条"],
    "emotion_curve": "压抑→警觉→委屈回忆→冷静布局→反杀快感",
    "ending_hook": "结尾钩子/下一章悬念"
  },
  "binding": {
    "shared_trigger": "同一个触发信号（项目名/话术/会议室/文件名）",
    "past_core_harm": "上一世吃的亏（具体）",
    "present_counterstrike": "这一世怎么反打（具体动作）"
  }
}

【强制规则】
- 禁止只写「女主想起上一世被陷害」，必须写成「由什么触发、想起哪件事、因此决定怎么做」
- 禁止「她决定反击」「她不会再忍」等空洞宣言，必须写可拍可写的动作
- 复仇动作示例：保存原始文件版本、引导对方在群里公开表态、故意在会议上请对方讲解自己做过的部分、当众放出时间戳证据
- 每章必须有明确的回忆触发锚点：某句话术、某个文件名、某个会议室、某种气味、某个动作

【跨章梗概拆分规则（非常重要）】
若输入是「第N-M章」的一条阶段梗概，表示这段情节需要多章讲完。你必须将它拆成 N..M 每章各自的章节卡：
- 每章 beats 必须不同，且具有递进：铺垫→发现异常→触发回忆→固证布局→会议/对峙→反杀落地→余波钩子
- 该段情节整体合起来必须覆盖原阶段梗概的全部内容
- 每章都要给出**不同的 ending_hook**，确保章节短剧节奏

【输出格式 - 非常重要】
严格输出多行，每行格式为：第N章：{JSON}
- 单章梗概：必须输出 1 行
- 阶段梗概第N-M章：必须输出 N、N+1、…、M 共 (M-N+1) 行，不可遗漏任一章
不要输出 markdown，不要解释思路，不要输出多余前后缀。
"""


def _extract_json_from_line(line: str) -> Optional[Tuple[int, Dict]]:
    m = re.search(r"第(\d+)章\s*[：:]\s*(\{.*\})\s*$", line.strip())
    if not m:
        return None
    ch = int(m.group(1))
    raw_json = m.group(2)
    try:
        obj = json.loads(raw_json)
        return ch, obj
    except Exception:
        return None


def _extract_cards_from_response(resp: str, max_lines_per_card: int = 80) -> Dict[int, Dict]:
    """
    更稳健的解析器：兼容模型把 JSON 换行输出的情况。
    识别形如：第N章：{JSON...}，若 JSON 跨行则持续拼接直到 json.loads 成功或达到上限。
    """
    lines = [ln.rstrip() for ln in (resp or "").splitlines() if ln.strip()]
    out: Dict[int, Dict] = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = re.match(r"^第(\d+)章\s*[：:]\s*(.*)$", line)
        if not m:
            i += 1
            continue
        ch = int(m.group(1))
        json_part = m.group(2).strip()
        if not json_part:
            i += 1
            continue

        # 快速路径：单行 JSON
        if json_part.startswith("{") and json_part.endswith("}"):
            try:
                obj = json.loads(json_part)
                if isinstance(obj, dict):
                    out[ch] = obj
                    i += 1
                    continue
            except Exception:
                pass

        # 多行 JSON：逐行拼接尝试解析
        buf = json_part
        j = 1
        parsed_obj: Optional[Dict] = None
        while i + j < len(lines) and j <= max_lines_per_card:
            try:
                obj = json.loads(buf)
                if isinstance(obj, dict):
                    parsed_obj = obj
                    break
            except Exception:
                pass
            buf = buf + lines[i + j].strip()
            j += 1
        if parsed_obj is not None:
            out[ch] = parsed_obj
            i += j
        else:
            i += 1
    return out


def fix_segments_batch(segments: List[Dict], chapter_to_original: Dict[int, str], single_batch: int = 5) -> Dict[int, Dict]:
    """
    分批调用 API 修正章节段落。
    - range 段每次只处理 1 段，保证 API 输出完整
    - 单章每批最多 single_batch 个
    返回：{chapter_id: chapter_card_dict}
    """
    result: Dict[int, Dict] = {}
    i = 0
    total_segments = len(segments)
    seg_index = 0
    while i < len(segments):
        seg = segments[i]
        seg_index += 1
        # range 段单独处理；单章可合并为一批
        if seg["type"] == "range":
            batch = [seg]
            i += 1
        else:
            batch = []
            while i < len(segments) and segments[i]["type"] == "single" and len(batch) < single_batch:
                batch.append(segments[i])
                i += 1
            if not batch:
                i += 1
                continue

        if batch[0]["type"] == "range":
            b = batch[0]
            parts = [f"【阶段梗概】第{b['start']}-{b['end']}章：{b['text']}"]
            parts.append(f"（必须输出第{b['start']}章到第{b['end']}章共{b['end']-b['start']+1}行）")
            print(f"🔧 正在修改第{b['start']}-{b['end']}章（段落进度 {seg_index}/{total_segments}）")
        else:
            parts = [f"【单章梗概】第{b['start']}章：{b['text']}" for b in batch]
            chs = [b["start"] for b in batch]
            if chs:
                print(f"🔧 正在修改第{chs[0]}-{chs[-1]}章（共{len(chs)}章，段落进度 {seg_index}/{total_segments}）")

        user_content = (
            "下面是原始章节梗概。请按系统要求输出每章的 JSON 章节卡，不可遗漏任一章。\n\n"
            + "\n".join(parts)
        )
        messages = [
            {"role": "system", "content": build_fix_master_system_prompt()},
            {"role": "user", "content": user_content},
        ]
        resp = call_qianwen_api(messages)
        if not resp:
            for b in batch:
                for ch in range(b["start"], b["end"] + 1):
                    if ch not in result and ch in chapter_to_original:
                        result[ch] = build_minimal_card(ch, chapter_to_original[ch])
                        print(f"✅ 第{ch}章修改完成（API失败，已用原文补齐最小卡）")
            continue

        # 记录本次 batch 预期覆盖哪些章，便于补漏与日志
        expected_chs = set()
        for b in batch:
            for ch in range(b["start"], b["end"] + 1):
                expected_chs.add(ch)
        covered_chs = set()

        parsed_cards = _extract_cards_from_response(resp)
        # 写入已解析的卡
        for ch, obj in parsed_cards.items():
            if ch not in expected_chs:
                continue
            if not isinstance(obj, dict):
                continue
            if obj.get("chapter_id") != ch:
                obj["chapter_id"] = ch
            present = obj.get("present") or {}
            if "revenue_action" in present and "revenge_action" not in present:
                present["revenge_action"] = present.pop("revenue_action", "")
            if not present or not present.get("present_mainline") or not isinstance(present.get("beats"), list) or len(present.get("beats", [])) < 3:
                if ch in chapter_to_original:
                    obj = _expand_card_from_original(obj, chapter_to_original[ch])
            ok, issues = critic_master_card(obj)
            if not ok and issues:
                print(f"  ⚠ 第{ch}章 Critic: {issues[:5]}{'...' if len(issues)>5 else ''}")
            result[ch] = obj
            covered_chs.add(ch)
            print(f"✅ 第{ch}章修改完成")

        # 若 API 漏章：用原文补齐，保证 batch 内不缺
        missing_chs = sorted(expected_chs - covered_chs)
        if missing_chs:
            # 先做一次“只补缺失章节”的重试（通常是格式/漏行问题）
            retry_parts = []
            for ch in missing_chs:
                orig = chapter_to_original.get(ch, "")
                retry_parts.append(f"第{ch}章原始梗概：{orig}")
            retry_user = (
                "你刚才输出中缺失了以下章节。请只为这些章节输出 JSON 章节卡，每章一行，严格格式：第N章：{JSON}，JSON 不得换行。\n\n"
                + "\n".join(retry_parts)
            )
            retry_messages = [
                {"role": "system", "content": build_fix_master_system_prompt()},
                {"role": "user", "content": retry_user},
            ]
            retry_resp = call_qianwen_api(retry_messages)
            if retry_resp:
                retry_cards = _extract_cards_from_response(retry_resp)
                for ch in missing_chs:
                    obj = retry_cards.get(ch)
                    if isinstance(obj, dict):
                        if obj.get("chapter_id") != ch:
                            obj["chapter_id"] = ch
                        present = obj.get("present") or {}
                        if "revenue_action" in present and "revenge_action" not in present:
                            present["revenge_action"] = present.pop("revenue_action", "")
                        if not present or not present.get("present_mainline") or not isinstance(present.get("beats"), list) or len(present.get("beats", [])) < 3:
                            if ch in chapter_to_original:
                                obj = _expand_card_from_original(obj, chapter_to_original[ch])
                        result[ch] = obj
                        covered_chs.add(ch)
                        print(f"✅ 第{ch}章修改完成（重试补齐）")

            # 仍缺失则原文补齐
            still_missing = sorted(expected_chs - covered_chs)
            for ch in still_missing:
                if ch not in result and ch in chapter_to_original:
                    result[ch] = build_minimal_card(ch, chapter_to_original[ch])
                    print(f"✅ 第{ch}章修改完成（API漏章/不合格，已用原文补齐最小卡）")
    return result


def run_fix_master_synopsis(master_path: str = None, output_path: str = None, batch_size: int = 10):
    """执行章节梗概修正（输出 master_ctx_final.txt，不覆盖源文件）"""
    master_path = Path(master_path or OUTLINE_FILE)
    output_path = Path(output_path or OUTLINE_FINAL_FILE)

    if not master_path.exists():
        print(f"❌ 未找到文件: {master_path}")
        return False

    with open(master_path, "r", encoding="utf-8") as f:
        raw = f.read()

    segments = parse_master_segments(raw)
    if not segments:
        print("❌ 未能解析出有效章节")
        return False

    # 统计预计章节数、建立 chapter -> 原文 映射
    chapter_set = set()
    chapter_to_original = build_chapter_to_original(segments)
    for ch in chapter_to_original:
        chapter_set.add(ch)
    print(f"📖 共解析到 {len(segments)} 段梗概，覆盖 {len(chapter_set)} 章，开始修正...")

    fixed_cards = fix_segments_batch(segments, chapter_to_original, single_batch=min(5, max(1, batch_size)))

    all_chapters = sorted(chapter_set)
    out_lines: List[str] = []
    missing = []
    for ch in all_chapters:
        obj = fixed_cards.get(ch)
        if not isinstance(obj, dict):
            missing.append(ch)
            if ch in chapter_to_original:
                obj = build_minimal_card(ch, chapter_to_original[ch])
                out_lines.append(f"第{ch}章：" + json.dumps(obj, ensure_ascii=False))
                print(f"  📌 第{ch}章：用原文补齐最小卡")
            continue
        # 再次修正拼写
        present = obj.get("present") or {}
        if "revenue_action" in present:
            present["revenge_action"] = present.pop("revenue_action", "")
        out_lines.append(f"第{ch}章：" + json.dumps(obj, ensure_ascii=False))

    if missing:
        print(f"📌 已用原文补齐 {len(missing)} 章：{sorted(missing)[:20]}{'...' if len(missing)>20 else ''}")

    out_content = "\n".join(out_lines) + ("\n" if out_lines else "")

    # 输出文件：不覆盖源文件
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
    parser = argparse.ArgumentParser(description="章节梗概修正器（这一世）")
    parser.add_argument("--input", default=None, help="输入的 master_ctx 文件路径（默认 outputs/master_ctx.txt）")
    parser.add_argument("--output", default=None, help="输出路径（默认 outputs/master_ctx_final.txt，不覆盖源文件）")
    parser.add_argument("--batch-size", type=int, default=10, help="每批处理段落数的间接控制（默认10；内部会自动换算）")
    args = parser.parse_args()
    run_fix_master_synopsis(args.input, args.output, args.batch_size)


if __name__ == "__main__":
    main()

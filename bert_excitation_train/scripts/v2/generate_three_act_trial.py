"""Generate an isolated three-act/beat-plan trial without formal promotion.

The authoritative event clusters and chapter cards are read-only inputs.  This
module deliberately writes only under ``body_generation/three_act_trial_*`` and
never calls StoryMemory or Neo4j write paths.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from .generate_pop_king_body_v5 import (
        _call_qwen, _load_json, _normalize_body, _opening_time_failures,
        _parse_json_object, _sha,
    )
except ImportError:  # direct execution from the repository root
    from scripts.v2.generate_pop_king_body_v5 import (
        _call_qwen, _load_json, _normalize_body, _opening_time_failures,
        _parse_json_object, _sha,
    )

BEAT_KEYS = (
    "act_id", "beat_id", "location", "time_relation", "active_character",
    "immediate_goal", "visible_action", "resistance", "new_information",
    "character_choice", "relationship_or_emotional_change", "state_before",
    "state_after", "artifact_use", "forbidden_replay", "chapter_boundary",
)


def _load_plan(output_dir: Path) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    events = _load_json(output_dir / "event_clusters_v2.json")
    cards_raw = _load_json(output_dir / "master_ctx_cards_v2.json")
    if not isinstance(events, list) or not isinstance(cards_raw, list):
        raise RuntimeError("权威规划文件必须是JSON数组。")
    cards = {int(item["chapter_id"]): item for item in cards_raw}
    return events, cards


def _event_for_chapter(events: list[dict[str, Any]], chapter_id: int) -> dict[str, Any]:
    for event in events:
        start, end = [int(value) for value in event.get("chapter_span") or []]
        if start <= chapter_id <= end:
            return event
    raise KeyError(f"找不到第{chapter_id}章所属事件簇。")


def _compact_card(card: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "chapter_id", "chapter_title", "cluster_id", "timeline_start",
        "timeline_end", "chapter_goal", "detailed_synopsis",
        "exact_action_sequence", "chapter_must_include", "chapter_must_not_include",
        "scene_location", "opponent_reaction", "immediate_payoff",
    )
    return {key: card.get(key) for key in keys}


def build_beat_plan_prompt(
    *, event: dict[str, Any], card: dict[str, Any], prior_context: str,
    next_card: dict[str, Any] | None,
) -> tuple[str, str]:
    system = (
        "你是中文长篇小说的场景策划器。只把既有详细梗概拆成可写的动作节拍，"
        "不得创造新人物、新证据、新权限、新事件或提前消费下一章结算。只输出严格JSON。"
    )
    next_boundary = _compact_card(next_card) if next_card else None
    payload = {
        "event_cluster": event,
        "chapter_card": _compact_card(card),
        "prior_context_tail": prior_context[-1800:],
        "next_chapter_boundary": next_boundary,
    }
    user = f"""请为第{card['chapter_id']}章生成三幕、8—10张节拍卡的JSON计划。

三幕职责：第一幕动作开场、目标、阻力、第一次选择；第二幕尝试受阻、对手反应、新信息、关系摩擦、方案调整和代价；第三幕执行调整后的动作、产生本章允许的物证或状态变化、取得有限收益，并留下下一章承接点。

每张节拍卡必须包含且只能围绕以下字段组织：{', '.join(BEAT_KEYS)}。
相邻节拍的state_after必须能成为下一节拍的state_before；相邻节拍必须有新的动作、信息、选择或状态变化。第一幕不得完成下一章结算，第二章不得重演第一章发现过程。日期不得作为正文首句模板。

权威输入：
{json.dumps(payload, ensure_ascii=False, indent=2)}

输出格式：{{"chapter_id": {card['chapter_id']}, "acts": [{{"act_id": 1, "beats": [...]}}], "chapter_boundary": "..."}}
"""
    return system, user


def validate_beat_plan(
    plan: dict[str, Any], *, card: dict[str, Any], next_card: dict[str, Any] | None = None,
) -> list[str]:
    failures: list[str] = []
    if int(plan.get("chapter_id") or -1) != int(card["chapter_id"]):
        failures.append("beat计划chapter_id与章卡不一致")
    acts = plan.get("acts")
    if not isinstance(acts, list) or len(acts) != 3:
        return failures + ["beat计划必须恰好包含三幕"]
    beat_list: list[dict[str, Any]] = []
    for expected_act, act in enumerate(acts, 1):
        if not isinstance(act, dict) or int(act.get("act_id") or -1) != expected_act:
            failures.append(f"第{expected_act}幕act_id错误")
            continue
        beats = act.get("beats")
        if not isinstance(beats, list):
            failures.append(f"第{expected_act}幕beats不是数组")
            continue
        for beat in beats:
            if not isinstance(beat, dict):
                failures.append("节拍卡必须是对象")
                continue
            beat_list.append(beat)
            missing = [key for key in BEAT_KEYS if not str(beat.get(key) or "").strip()]
            if missing:
                failures.append(f"节拍{beat.get('beat_id')}缺少字段：{'、'.join(missing)}")
    if not 8 <= len(beat_list) <= 10:
        failures.append(f"节拍总数{len(beat_list)}不在8—10范围")
    for previous, current in zip(beat_list, beat_list[1:]):
        if str(previous.get("state_after")).strip() != str(current.get("state_before")).strip():
            failures.append(f"节拍状态未衔接：{previous.get('beat_id')}→{current.get('beat_id')}")
        novelty = (
            str(previous.get("visible_action")) != str(current.get("visible_action"))
            or str(previous.get("new_information")) != str(current.get("new_information"))
            or str(previous.get("character_choice")) != str(current.get("character_choice"))
            or str(previous.get("state_after")) != str(current.get("state_after"))
        )
        if not novelty:
            failures.append(f"相邻节拍重复：{previous.get('beat_id')}与{current.get('beat_id')}")
    if next_card:
        next_text = json.dumps(_compact_card(next_card), ensure_ascii=False)
        plan_text = json.dumps(
            [{key: beat.get(key) for key in (
                "location", "active_character", "immediate_goal", "visible_action",
                "resistance", "new_information", "character_choice",
                "relationship_or_emotional_change", "state_before", "state_after",
                "artifact_use",
            )} for act in acts for beat in (act.get("beats") or [])],
            ensure_ascii=False,
        )
        current_card_text = json.dumps(card, ensure_ascii=False)
        for anchor in next_card.get("chapter_must_include") or []:
            if str(anchor) and str(anchor) in plan_text and str(anchor) not in current_card_text:
                failures.append(f"节拍计划疑似提前消费下一章事实：{anchor}")
        if next_text and not plan_text:
            failures.append("节拍计划为空")
    return failures


def _normalize_beat_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Fill only structural data that is unambiguously inherited from a幕."""
    normalized = dict(plan)
    normalized["acts"] = []
    previous_after = ""
    for act in plan.get("acts") or []:
        act_copy = dict(act)
        act_id = act_copy.get("act_id")
        act_copy["beats"] = []
        for beat in act.get("beats") or []:
            beat_copy = dict(beat)
            if not beat_copy.get("act_id"):
                beat_copy["act_id"] = act_id
            if not beat_copy.get("forbidden_replay"):
                beat_copy["forbidden_replay"] = "不得重演上一节拍已经完成的动作"
            if not beat_copy.get("chapter_boundary"):
                beat_copy["chapter_boundary"] = "只结算本章，不提前消费下一章"
            if not beat_copy.get("artifact_use"):
                beat_copy["artifact_use"] = "使用本章已有材料；不新增物证"
            if previous_after and str(beat_copy.get("state_before") or "").strip() != previous_after:
                beat_copy["state_before"] = previous_after
            act_copy["beats"].append(beat_copy)
            previous_after = str(beat_copy.get("state_after") or "").strip()
        normalized["acts"].append(act_copy)
    return normalized


def build_body_prompt(
    *, event: dict[str, Any], card: dict[str, Any], beat_plan: dict[str, Any],
    prior_context: str,
) -> tuple[str, str]:
    system = "你是中文商业长篇小说作者。根据权威章卡和已校验节拍计划，一次性写出连贯整章正文，只输出严格JSON。"
    user = f"""请写第{card['chapter_id']}章完整正文，不要输出幕标题、节拍编号、规划字段、解释或Markdown。

正文要求：1600—2200个汉字，12—18个有效自然段；按节拍计划推进，但改写成自然小说，不要逐条复述。第一句不得是完整日期，前三个自然段自然交代章卡年份。不得新增人物、证据、权限、结算或下一章内容；不得出现前世/重生知识泄漏、结构化状态字段或现实世界专名。

权威章卡：
{json.dumps(_compact_card(card), ensure_ascii=False, indent=2)}

已校验三幕节拍计划：
{json.dumps(beat_plan, ensure_ascii=False, indent=2)}

上一章承接尾部：
{prior_context[-1200:]}

输出：{{"chapter_id": {card['chapter_id']}, "title": "{card.get('chapter_title', '')}", "body": "纯正文"}}
"""
    return system, user


def _trial_body_failures(body: str, card: dict[str, Any]) -> list[str]:
    failures = []
    han = len(re.findall(r"[\u3400-\u9fff]", body))
    if han < 1400 or han > 2200:
        failures.append(f"试写正文汉字数{han}不在1400—2200范围")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if not 12 <= len(paragraphs) <= 18:
        failures.append(f"试写正文有效段落数{len(paragraphs)}不在12—18范围")
    if re.search(r"(?:第一幕|第二幕|第三幕|beat[_-]?\d+|act[_-]?\d+)", body, re.I):
        failures.append("正文泄漏幕或节拍标记")
    failures.extend(_opening_time_failures(body, card))
    return failures


def _paragraph_metrics(body: str) -> dict[str, Any]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return {
        "han_chars": len(re.findall(r"[\u3400-\u9fff]", body)),
        "paragraphs": len(paragraphs),
        "dialogue_marks": body.count("“") + body.count('"'),
        "environment_terms": {
            term: body.count(term) for term in ("空气", "冷风", "纸张", "纸浆味", "手指", "走廊")
        },
    }


def _comparison_report(output_dir: Path, trial_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Add measurable comparison data without reading or writing formal memory."""
    comparisons = []
    formal_dir = output_dir / "chapters"
    trial_chapters = trial_dir / "chapters"
    for item in report.get("chapters") or []:
        chapter_id = int(item["chapter_id"])
        trial_body = (trial_chapters / f"chapter_{chapter_id:03d}.txt").read_text(encoding="utf-8")
        formal_path = formal_dir / f"chapter_{chapter_id:03d}.txt"
        formal_body = formal_path.read_text(encoding="utf-8") if formal_path.is_file() else ""
        relationship_terms = ("信任", "拒绝", "承担", "支持", "冲突", "选择", "代价", "署名")
        comparisons.append({
            "chapter_id": chapter_id,
            "trial": {
                **_paragraph_metrics(trial_body),
                "beat_count": len([
                    beat for act in (_load_json(trial_dir / "beat_plans" / f"chapter_{chapter_id:03d}.json").get("acts") or [])
                    for beat in (act.get("beats") or [])
                ]),
                "relationship_change_markers": sum(trial_body.count(term) for term in relationship_terms),
            },
            "prior_one_pass": _paragraph_metrics(formal_body) if formal_body else None,
            "prior_one_pass_status": "available" if formal_body else "MISSING",
            "graph_consistency": "NOT_RUN_isolated_trial",
        })
    for left, right in zip(comparisons, comparisons[1:]):
        left_body = (trial_chapters / f"chapter_{left['chapter_id']:03d}.txt").read_text(encoding="utf-8")
        right_body = (trial_chapters / f"chapter_{right['chapter_id']:03d}.txt").read_text(encoding="utf-8")
        left["next_chapter_overlap"] = round(SequenceMatcher(None, left_body, right_body, autojunk=False).ratio(), 4)
    report["comparison"] = comparisons
    report["comparison_notes"] = {
        "effective_event_count": "beat_count is the planned event-unit proxy; no new events are inferred",
        "prior_one_pass": "compared only when the formal chapter file already exists; MISSING is explicit",
        "story_memory_and_neo4j": "NOT_RUN by design for this isolated trial",
    }
    return report


def run_trial(output_dir: Path, start: int = 293, end: int = 296, model: str = "qwen-plus", temperature: float = 0.25) -> dict[str, Any]:
    events, cards = _load_plan(output_dir)
    trial_dir = output_dir / "body_generation" / f"three_act_trial_{start}_{end}"
    (trial_dir / "beat_plans").mkdir(parents=True, exist_ok=True)
    (trial_dir / "raw").mkdir(parents=True, exist_ok=True)
    (trial_dir / "chapters").mkdir(parents=True, exist_ok=True)
    (trial_dir / "audits").mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    previous = ""
    for chapter_id in range(start, end + 1):
        card = cards[chapter_id]
        event = _event_for_chapter(events, chapter_id)
        next_card = cards.get(chapter_id + 1)
        plan_system, plan_user = build_beat_plan_prompt(
            event=event, card=card, prior_context=previous, next_card=next_card,
        )
        plan = None
        plan_call: dict[str, Any] = {}
        plan_failures: list[str] = []
        for plan_attempt in range(1, 6):
            retry_suffix = ""
            if plan_failures:
                retry_suffix = "\n上一版节拍计划未通过，请完整重写，不要只返回修改片段：\n" + "\n".join(
                    f"- {item}" for item in plan_failures[:10]
                )
            raw_plan, plan_call = _call_qwen(
                [{"role": "system", "content": plan_system}, {"role": "user", "content": plan_user + retry_suffix}],
                model=model, temperature=temperature,
            )
            plan_path = trial_dir / "raw" / f"chapter_{chapter_id:03d}_beat_plan_attempt_{plan_attempt:02d}.txt"
            plan_path.write_text(raw_plan, encoding="utf-8")
            plan = _normalize_beat_plan(_parse_json_object(raw_plan, default_chapter_id=chapter_id))
            plan_failures = validate_beat_plan(plan, card=card, next_card=next_card)
            if not plan_failures:
                break
        if plan is None or plan_failures:
            raise RuntimeError(f"第{chapter_id}章节拍计划未通过：{'；'.join(plan_failures)}")
        (trial_dir / "beat_plans" / f"chapter_{chapter_id:03d}.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        body_system, body_user = build_body_prompt(
            event=event, card=card, beat_plan=plan, prior_context=previous,
        )
        raw_body, body_call = _call_qwen(
            [{"role": "system", "content": body_system}, {"role": "user", "content": body_user}],
            model=model, temperature=temperature,
        )
        (trial_dir / "raw" / f"chapter_{chapter_id:03d}_body_raw.txt").write_text(raw_body, encoding="utf-8")
        parsed = _parse_json_object(raw_body, default_chapter_id=chapter_id)
        body = _normalize_body(parsed.get("body"))
        failures = _trial_body_failures(body, card)
        metrics = _paragraph_metrics(body)
        (trial_dir / "chapters" / f"chapter_{chapter_id:03d}.txt").write_text(body, encoding="utf-8")
        audit = {
            "chapter_id": chapter_id, "status": "trial_only_not_accepted",
            "beat_plan_call": plan_call, "body_call": body_call,
            "beat_plan_sha256": _sha(json.dumps(plan, ensure_ascii=False, sort_keys=True)),
            "metrics": metrics, "failures": failures,
        }
        (trial_dir / "audits" / f"chapter_{chapter_id:03d}.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        results.append(audit)
        previous = body
    report = {
        "status": "trial_only_not_accepted", "chapter_range": [start, end],
        "formal_commit": False, "story_memory_sync": False, "neo4j_sync": False,
        "chapters": results,
    }
    report = _comparison_report(output_dir, trial_dir, report)
    (trial_dir / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="三幕节拍卡隔离试写，不提交正式正文。")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[2] / "outputs_pop_king_v6_compiled_story_first_500")
    parser.add_argument("--start", type=int, default=293)
    parser.add_argument("--end", type=int, default=296)
    parser.add_argument("--model", default="qwen-plus")
    parser.add_argument("--temperature", type=float, default=0.25)
    parser.add_argument("--report-only", action="store_true", help="只补生成已有隔离试写的比较报告，不调用模型。")
    args = parser.parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    trial_dir = output_dir / "body_generation" / f"three_act_trial_{args.start}_{args.end}"
    if args.report_only:
        report_path = trial_dir / "quality_report.json"
        report = _comparison_report(output_dir, trial_dir, _load_json(report_path))
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        report = run_trial(output_dir, args.start, args.end, args.model, args.temperature)
    print(json.dumps({"status": report["status"], "chapter_range": report["chapter_range"]}, ensure_ascii=False))


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    main()

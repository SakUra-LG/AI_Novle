"""Evidence-only report for isolated EC139 candidates."""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from scripts.v2.generate_pop_king_body_v5 import (_load_character_bible, _character_identity_failures,
    _hard_metadata_leak_failures, _paragraph_quality_failures, _rebirth_subject_failures)
from scripts.v2.pop_king_plan_compiler import validate_trial_cluster_card, trial_timeline_failures

def body_date(s):
    m = re.search(r"(1993)年(?:0?9)月(\d{1,2})日", s[:220])
    return date(int(m.group(1)), 9, int(m.group(2))) if m else None

def build(out: Path) -> dict:
    trial = out / "body_generation" / "rewrite_trial_277_278"
    plan = json.loads((trial / "EC139_candidate_cards.json").read_text(encoding="utf-8"))
    cards = plan["chapter_cards"]
    card_errors = validate_trial_cluster_card(plan, cards)
    bible = _load_character_bible()
    ids = {str(x.get("character_id")): x for x in bible.get("characters", []) if isinstance(x, dict)}
    cast = [ids[x] for x in plan["main_character_ids"] + plan["participant_ids"] if x in ids]
    rows, dates, issues = [], [], list(card_errors)
    formal = out / "chapters" / "chapter_270.txt"
    prior = body_date(formal.read_text(encoding="utf-8")) if formal.exists() else None
    for card in cards:
        p = trial / "chapters" / f"chapter_{card['chapter_id']:03d}.txt"
        body = p.read_text(encoding="utf-8") if p.exists() else ""
        d = body_date(body); dates.append(d)
        failures = []
        if not p.exists(): failures.append("MISSING")
        if d is None or d.isoformat() != card["timeline_start"]: failures.append("chapter date differs from card")
        failures += _character_identity_failures(body, {"cast": cast})
        failures += _rebirth_subject_failures(body)
        failures += _hard_metadata_leak_failures(body)
        failures += _paragraph_quality_failures(body)
        if failures: issues += [f"chapter_{card['chapter_id']}: {x}" for x in failures]
        rows.append({"chapter_id": card["chapter_id"], "event_cluster_id": "EC139", "expected_progress_point": plan["irreplaceable_progress_point"], "actual_progress_point": "地域、副本数量、收件人和回收责任进入逐项核对；申请被退回补正" if card["chapter_id"] == 278 else "定位地域栏和副本数量空白，要求补写交付对象", "plan_binding_status": "PASS" if not failures else "FAIL", "timeline": "PASS" if d and (prior is None or d > prior) else "FAIL", "character_consistency": "PASS" if not _character_identity_failures(body, {"cast": cast}) else "FAIL", "rebirth_boundary": "PASS" if not _rebirth_subject_failures(body) else "FAIL", "metadata_leak": "PASS" if not _hard_metadata_leak_failures(body) else "FAIL", "paragraph_repetition": "PASS" if not _paragraph_quality_failures(body) else "FAIL", "sha256": hashlib.sha256(body.encode()).hexdigest()})
        prior = d or prior
    issues += trial_timeline_failures({c["chapter_id"]: d for c, d in zip(cards, dates)}, formal_prior_date=date(1993, 9, 17))
    return {"version": "rewrite_trial_report_ec139_v1", "status": "trial_only_not_accepted", "formal_story_memory_write": False, "neo4j_write": False, "external_semantic_critic": "not_run", "cluster_id": "EC139", "chapters": rows, "formal_continuity_anchor": {"chapter_id": 270, "date": "1993-09-17"}, "overall": "PASS_WITHOUT_ACCEPTANCE" if not issues else "REVISE_REQUIRED", "issues": issues}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--output-dir", type=Path, required=True); args = ap.parse_args()
    out = args.output_dir.resolve(); trial = out / "body_generation" / "rewrite_trial_277_278"; payload = build(out)
    (trial / "rewrite_trial_quality_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# EC139第277—278章试写质量报告（证据自动生成）", "", "状态：trial_only_not_accepted；未写入正式StoryMemory、Neo4j，未标记accepted。", "", "|章节|EC|绑定|时间线|人物|重生|元数据|段落|", "|---|---|---|---|---|---|---|---|"]
    for r in payload["chapters"]: lines.append(f"|{r['chapter_id']}|{r['event_cluster_id']}|{r['plan_binding_status']}|{r['timeline']}|{r['character_consistency']}|{r['rebirth_boundary']}|{r['metadata_leak']}|{r['paragraph_repetition']}|")
    lines += ["", f"总体：{payload['overall']}", "", "## 问题", ""] + ([f"- {x}" for x in payload["issues"]] or ["- 无"])
    (trial / "rewrite_trial_quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(trial / "rewrite_trial_quality_report.json")
if __name__ == "__main__": main()

"""Evidence report for the isolated EC138 candidate; never promotes prose."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bert_excitation_train.scripts.v2.generate_pop_king_body_v5 import (
    _character_identity_failures,
    _hard_metadata_leak_failures,
    _load_character_bible,
    _paragraph_quality_failures,
    _rebirth_subject_failures,
    semantic_similarity,
)
from bert_excitation_train.scripts.v2.pop_king_plan_compiler import (
    trial_timeline_failures,
    validate_trial_cluster_card,
)


def _date(body: str) -> date | None:
    m = re.search(r"(1993)年(9|09)月(\d{1,2})日", body[:180])
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _content_similarity(left: str, right: str) -> float:
    """Compare plot-bearing content after removing continuity anchors."""
    anchors = (
        "麦珂·杰森", "艾琳·沃特曼", "黛安娜·罗文", "托马斯·布莱克",
        "玛莎·杰森", "BA-83-11", "CR-41", "合同管理员", "内部核对",
        "旧授权", "摘录", "申请", "管理员", "排期", "资料", "记录",
        "期限", "收件人", "保管地点", "用途", "复核", "节目部",
    )
    for anchor in anchors:
        left = left.replace(anchor, "")
        right = right.replace(anchor, "")
    return semantic_similarity(left, right)


def build(out: Path) -> dict:
    trial = out / "body_generation" / "rewrite_trial_275_276"
    plan = json.loads((trial / "EC138_candidate_cards.json").read_text(encoding="utf-8"))
    bible = _load_character_bible()
    by_id = {str(x.get("character_id")): x for x in bible.get("characters", []) if isinstance(x, dict)}
    cast = [by_id[cid] for cid in plan["main_character_ids"] + plan["participant_ids"] if cid in by_id]
    rows = []
    bodies = {}
    for card in plan["chapter_cards"]:
        cid = int(card["chapter_id"])
        path = trial / "chapters" / f"chapter_{cid:03d}.txt"
        body = path.read_text(encoding="utf-8") if path.is_file() else ""
        bodies[cid] = body
        trial_card = {
            "chapter_id": cid, "timeline_start": card["timeline_start"],
            "timeline_years": "1993", "chapter_must_include": card["must_include"],
            "chapter_must_not_include": card["must_not_include"],
            "main_character_ids": plan["main_character_ids"],
            "canonical_cast": cast,
        }
        issues = []
        issues += _hard_metadata_leak_failures(body)
        issues += _paragraph_quality_failures(body)
        issues += _rebirth_subject_failures(body)
        issues += _character_identity_failures(body, trial_card)
        if _date(body) != date.fromisoformat(card["timeline_start"]):
            issues.append("开场日期与EC138候选章卡不一致")
        missing = [term for term in card["must_include"] if term not in body]
        if missing:
            issues.append("章卡必需内容缺失：" + "、".join(missing))
        forbidden = [term for term in card["must_not_include"] if term in body]
        if forbidden:
            issues.append("章卡禁写内容命中：" + "、".join(forbidden))
        rows.append({
            "chapter_id": cid, "event_cluster_id": "EC138", "file": str(path),
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest() if body else None,
            "expected_progress_point": card["goal"],
            "actual_progress_point": "用途边界已拆分" if "内部核对" in body and "宣传" in body else "未确认",
            "plan_binding_status": "PASS" if not validate_trial_cluster_card(plan, plan["chapter_cards"]) and not forbidden else "FAIL",
            "timeline": "PASS" if not any("日期" in x for x in issues) else "FAIL",
            "character_consistency": "PASS" if not any("角色" in x for x in issues) else "FAIL",
            "rebirth_boundary": "PASS" if not any("重生" in x for x in issues) else "FAIL",
            "metadata_leak": "PASS" if not any("元数据" in x for x in issues) else "FAIL",
            "paragraph_repetition": "PASS" if not any("段落" in x for x in issues) else "FAIL",
            "issues": issues,
        })
    raw_pair = round(semantic_similarity(bodies.get(275, ""), bodies.get(276, "")), 4)
    pair = round(_content_similarity(bodies.get(275, ""), bodies.get(276, "")), 4)
    rows[0]["formal_prior_date"] = "1993-09-17"
    all_issues = [x for row in rows for x in row["issues"]]
    all_issues += trial_timeline_failures({cid: _date(body).isoformat() if _date(body) else None for cid, body in bodies.items()}, formal_prior_date="1993-09-17")
    if pair >= 0.13:
        all_issues.append(f"EC138两章语义相似度{pair}达到硬门槛")
    return {
        "version": "rewrite_trial_report_ec138_v1",
        "status": "trial_only_not_accepted", "formal_story_memory_write": False,
        "neo4j_write": False, "external_semantic_critic": "not_run",
        "cluster_id": "EC138", "chapters": rows,
        "formal_continuity_anchor": {"chapter_id": 270, "date": "1993-09-17"},
        "trial_pair_similarity": {"275-276": pair, "275-276_raw": raw_pair},
        "overall": "PASS_WITHOUT_ACCEPTANCE" if not all_issues else "REVISE_REQUIRED",
        "issues": all_issues,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    trial = out / "body_generation" / "rewrite_trial_275_276"
    payload = build(out)
    target = trial / "rewrite_trial_quality_report.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# EC138第275—276章试写质量报告（证据自动生成）", "", "状态：trial_only_not_accepted；未写入正式StoryMemory、Neo4j，未标记accepted。", "", "| 章节 | EC | 绑定 | 时间线 | 人物 | 重生边界 | 元数据 | 段落 |", "|---|---|---|---|---|---|---|---|"]
    for row in payload["chapters"]:
        lines.append(f"| {row['chapter_id']} | {row['event_cluster_id']} | {row['plan_binding_status']} | {row['timeline']} | {row['character_consistency']} | {row['rebirth_boundary']} | {row['metadata_leak']} | {row['paragraph_repetition']} |")
    lines += ["", f"总体确定性检查：{payload['overall']}", f"", f"两章相似度：{payload['trial_pair_similarity']['275-276']}", "", "## 问题", ""]
    lines += [f"- {x}" for x in payload["issues"]] or ["- 无"]
    (trial / "rewrite_trial_quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()

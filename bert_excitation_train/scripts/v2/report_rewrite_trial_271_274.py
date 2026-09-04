"""Generate evidence-only quality reports for the isolated 271-274 trial."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

# Permit direct execution from the repository root as well as ``python -m``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bert_excitation_train.scripts.v2.generate_pop_king_body_v5 import (
    _character_identity_failures,
    _hard_metadata_leak_failures,
    _load_character_bible,
    _paragraph_quality_failures,
    _rebirth_subject_failures,
    semantic_similarity,
)
from bert_excitation_train.scripts.v2.pop_king_plan_compiler import (
    trial_chapter_binding_failures,
    trial_forward_consumption_failures,
    trial_timeline_failures,
)


TRIAL_CHAPTERS = range(271, 275)


def _date_in_body(body: str) -> date | None:
    match = re.search(r"(1993)年(9|09)月(\d{1,2})日", body[:180])
    if not match:
        match = re.search(r"(?<!\d)(9|09)月(\d{1,2})日", body[:180])
        if match:
            return date(1993, int(match.group(1)), int(match.group(2)))
    if not match:
        return None
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _trial_card(chapter_id: int, spec: dict[str, Any]) -> dict[str, Any]:
    bible = _load_character_bible()
    by_id = {str(x.get("character_id")): x for x in bible.get("characters", []) if isinstance(x, dict)}
    registry = Path(__file__).resolve().parents[3] / "outputs_pop_king_v6_compiled_story_first_500" / "body_generation" / "rewrite_trial_271_274" / "trial_character_registry.json"
    if registry.is_file():
        extra = json.loads(registry.read_text(encoding="utf-8"))
        for profile in extra.get("characters", []):
            by_id[str(profile.get("character_id"))] = profile
    ids = set(spec.get("main_character_ids", [])) | set(spec.get("participant_ids", []))
    return {
        "chapter_id": chapter_id,
        "timeline_start": spec["date"],
        "timeline_years": "1993",
        "chapter_must_include": ["BA-83-11", "CR-41"],
        "chapter_must_not_include": spec.get("forbidden_progress", []),
        "main_character_ids": list(spec.get("main_character_ids", [])),
        "canonical_cast": [by_id[x] for x in ids if x in by_id],
    }


def _content_similarity(left: str, right: str) -> float:
    """Compare plot-bearing prose after removing continuity anchors."""
    anchors = (
        "麦珂·杰森", "艾琳·沃特曼", "黛安娜·罗文", "托马斯·布莱克",
        "罗莎·贝内特", "莉薇娅·普莱斯", "BA-83-11", "CR-41",
        "河湾镇档案馆", "档案馆", "复制申请", "登记", "签名", "权限",
        "排期", "管理员", "主管", "资料", "申请页", "批准页", "交接",
        "用途", "核对", "记录", "材料",
    )
    for anchor in anchors:
        left = left.replace(anchor, "")
        right = right.replace(anchor, "")
    return semantic_similarity(left, right)


def _character_status(issues: list[str]) -> str:
    return "FAIL" if any("角色" in item for item in issues) else "PASS"


def build_report(out: Path) -> dict[str, Any]:
    trial = out / "body_generation" / "rewrite_trial_271_274"
    plan = json.loads((trial / "trial_plan_ec136_ec137.json").read_text(encoding="utf-8"))
    specs: dict[int, tuple[str, dict[str, Any]]] = {}
    for event in plan["event_clusters"]:
        for spec in event["chapter_specs"]:
            merged = dict(spec)
            merged["main_character_ids"] = event.get("main_character_ids", [])
            merged["participant_ids"] = event.get("participant_ids", [])
            specs[int(spec["chapter_id"])] = (event["cluster_id"], merged)

    formal270 = out / "chapters" / "chapter_270.txt"
    formal_body = formal270.read_text(encoding="utf-8") if formal270.is_file() else ""
    bodies: dict[int, str] = {}
    rows: list[dict[str, Any]] = []
    for chapter_id in TRIAL_CHAPTERS:
        path = trial / "chapters" / f"chapter_{chapter_id:03d}.txt"
        body = path.read_text(encoding="utf-8") if path.is_file() else ""
        bodies[chapter_id] = body
        cluster_id, spec = specs[chapter_id]
        card = _trial_card(chapter_id, spec)
        issues: list[str] = []
        issues.extend(_hard_metadata_leak_failures(body))
        issues.extend(_paragraph_quality_failures(body))
        issues.extend(_rebirth_subject_failures(body))
        issues.extend(_character_identity_failures(body, card))
        expected = date.fromisoformat(spec["date"])
        actual = _date_in_body(body)
        if actual != expected:
            issues.append(f"开场日期不符章卡：期望{expected.isoformat()}，实际{actual}")
        if chapter_id == 271:
            prior = _date_in_body(formal_body)
            if prior is None:
                issues.append("正式第270章日期证据缺失")
            elif expected < prior:
                issues.append("chapter_271早于正式chapter_270，时间线倒退")
        rows.append({
            "chapter_id": chapter_id,
            "file": str(path),
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest() if body else None,
            "event_cluster_id": cluster_id,
            "expected_progress_point": event_progress(plan, cluster_id, chapter_id),
            "actual_progress_point": actual_progress(body, chapter_id),
            "plan_binding_status": "PASS" if not trial_chapter_binding_failures(body, cluster_id, chapter_id, plan) else "FAIL",
            "character_consistency": _character_status(issues),
            "timeline": "FAIL" if any("日期" in x or "chapter_271" in x or "时间线" in x for x in issues) else "PASS",
            "rebirth_boundary": "FAIL" if any("重生" in x for x in issues) else "PASS",
            "metadata_leak": "FAIL" if any("元数据" in x for x in issues) else "PASS",
            "paragraph_repetition": "FAIL" if any("段落" in x for x in issues) else "PASS",
            "science_era_reasonableness": "FAIL" if ("全息投影" in body or "便携光谱仪" in body and "精确证明" in body) else "PASS",
            "issues": issues,
        })

    pair_scores = {
        f"{left}-{right}": round(_content_similarity(bodies[left], bodies[right]), 4)
        for left, right in ((271, 272), (271, 273), (271, 274), (272, 273), (272, 274), (273, 274))
    }
    trial_repeat_issues = [
        f"试写稿内部{pair}语义相似度{score}达到硬门槛"
        for pair, score in pair_scores.items() if score >= 0.13
    ]
    rows_by_id = {row["chapter_id"]: row for row in rows}
    for chapter_id, row in rows_by_id.items():
        cluster_id, spec = specs[chapter_id]
        forward = trial_forward_consumption_failures(bodies[chapter_id], cluster_id, plan)
        binding = trial_chapter_binding_failures(bodies[chapter_id], cluster_id, chapter_id, plan)
        row["plan_leak_forward"] = "FAIL" if forward else "PASS"
        row["issues"].extend(forward + binding)
        if forward or binding:
            row["plan_binding_status"] = "FAIL"
            row["issues"] = list(dict.fromkeys(row["issues"]))
    all_issues = [issue for row in rows for issue in row["issues"]] + trial_repeat_issues
    return {
        "version": "rewrite_trial_report_v2_evidence_only",
        "status": "trial_only_not_accepted",
        "formal_story_memory_write": False,
        "neo4j_write": False,
        "manual_review_gate": {
            "status": "PENDING_EXTERNAL_HUMAN_READING",
            "decision_required": "PASS or REVISE_REQUIRED",
            "required_dimensions": [
                "人物一致性", "时间线", "重生知识边界", "两章功能区分",
                "最近20章与试写稿内部重复", "文书/权限范围", "科学与年代合理性",
            ],
            "chapter_sha256": {
                str(row["chapter_id"]): row["sha256"] for row in rows
            },
            "formal_promotion_allowed": False,
        },
        "formal_continuity_anchor": {"chapter_id": 270, "file": str(formal270), "date": _date_in_body(formal_body).isoformat() if _date_in_body(formal_body) else None},
        "plan_source": str(trial / "trial_plan_ec136_ec137.json"),
        "chapters": rows,
        "trial_internal_pair_similarity": pair_scores,
        "trial_internal_repeat_issues": trial_repeat_issues,
        "overall": "PASS_WITHOUT_ACCEPTANCE" if not all_issues else "REVISE_REQUIRED",
        "issues": all_issues,
    }


def event_progress(plan: dict[str, Any], cluster_id: str, chapter_id: int) -> str:
    for event in plan["event_clusters"]:
        if event["cluster_id"] == cluster_id:
            return next(x["progress"] for x in event["chapter_specs"] if int(x["chapter_id"]) == chapter_id)
    return ""


def actual_progress(body: str, chapter_id: int) -> str:
    if chapter_id == 271:
        return "定位来源箱与复制申请" if "来源箱" in body and "复制申请" in body else "未检测到定位结果"
    if chapter_id == 272:
        return "确认实际经手岗位并锁定待核查部门与批准人" if "实际经手岗位" in body and "待核查" in body else "未检测到EC136后半推进"
    if chapter_id == 273:
        return "核对申请与批准权限并定位复核缺口" if "谁可以申请" in body and "谁可以批准" in body else "未检测到EC137前半推进"
    return "对该摘录取得范围受限程序保护" if "暂停用于节目制作" in body and "不覆盖节目部其他档案" in body else "未检测到EC137后半推进"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    trial = out / "body_generation" / "rewrite_trial_271_274"
    payload = build_report(out)
    json_path = trial / "rewrite_trial_quality_report.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 第271—274章重写试写质量报告（证据自动生成）", "",
        "状态：trial_only_not_accepted；未写入正式StoryMemory、Neo4j，未标记accepted。", "",
        "人工阅读闸门：PENDING_EXTERNAL_HUMAN_READING；须逐章确认下列维度后才能提交放行。", "",
        "| 章节 | EC | 章卡绑定 | 时间线 | 人物 | 重生边界 | 元数据 | 段落 | 跨EC提前消费 |", "|---|---|---|---|---|---|---|---|---|"
    ]
    for row in payload["chapters"]:
        lines.append(f"| {row['chapter_id']} | {row['event_cluster_id']} | {row['plan_binding_status']} | {row['timeline']} | {row['character_consistency']} | {row['rebirth_boundary']} | {row['metadata_leak']} | {row['paragraph_repetition']} | {row['plan_leak_forward']} |")
    lines += ["", f"总体确定性检查：{payload['overall']}", "", "## 逐章问题", ""]
    for row in payload["chapters"]:
        lines.append(f"- 第{row['chapter_id']}章：" + ("；".join(row["issues"]) if row["issues"] else "无"))
    lines += ["", "## 当前哈希（人工放行必须逐章匹配）", ""]
    for chapter_id, digest in payload["manual_review_gate"]["chapter_sha256"].items():
        lines.append(f"- 第{chapter_id}章：`{digest}`")
    lines += ["", "## 试写稿内部两两相似度", ""]
    for pair, score in payload["trial_internal_pair_similarity"].items():
        lines.append(f"- {pair}：{score}")
    if payload["trial_internal_repeat_issues"]:
        lines += ["", "## 内部重复问题", *[f"- {x}" for x in payload["trial_internal_repeat_issues"]]]
    (trial / "rewrite_trial_quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json_path)


if __name__ == "__main__":
    main()

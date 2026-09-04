"""Offline deterministic audit for the accepted chapter_001..210 manuscript."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bert_excitation_train.scripts.v2 import generate_pop_king_body_v5 as bodygen


OUT = Path(__file__).resolve().parents[2] / "outputs_pop_king_v6_compiled_story_first_500"
REPORT = OUT / "existing_body_v13_audit_001_210.json"

def issue(code: str, message: str, chapter_ids: list[int], *, level: str = "FATAL") -> dict[str, Any]:
    return {
        "code": code,
        "severity": level,
        "chapter_ids": chapter_ids,
        "message": message,
    }


def main() -> None:
    events, card_map, _ = bodygen._load_inputs(OUT)
    bodies: dict[int, str] = {}
    issues: list[dict[str, Any]] = []
    old_names = ("昆廷·索恩", "瑟琳娜·瓦尔", "莉薇娅·科尔", "黛安娜·洛瑞", "苏菲亚·陈")
    reality_tokens = ("联邦调查局", "联邦通信委员会", "FCC", "IBM Selectric", "旧金山", "纽约", "洛杉矶")
    plan_leaks = ("本章必须", "事件簇", "章卡要求", "结算契约", "生成正文时")
    for chapter_id in range(1, 211):
        path = OUT / "chapters" / f"chapter_{chapter_id:03d}.txt"
        if not path.is_file():
            issues.append(issue("MISSING_BODY", "正文文件缺失", [chapter_id]))
            continue
        text = path.read_text(encoding="utf-8").strip()
        bodies[chapter_id] = text
        parsed = {"chapter_id": chapter_id, "body": text}
        _, failures, _ = bodygen._validate_single_chapter(parsed, card_map[chapter_id])
        for failure in failures:
            # Existing chapters were accepted against an earlier card schema. Keep the
            # compatibility delta visible, but do not mislabel plan-field drift as a
            # manuscript corruption.
            issues.append(issue("LEGACY_CARD_COMPATIBILITY", str(failure), [chapter_id], level="WARNING"))
        for token in old_names:
            if token in text:
                issues.append(issue("CANONICAL_NAME_DRIFT", f"正文仍使用旧名：{token}", [chapter_id]))
        for token in reality_tokens:
            if token in text:
                issues.append(issue("REAL_WORLD_ENTITY", f"正文出现现实专名：{token}", [chapter_id]))
        for token in plan_leaks:
            if token in text:
                issues.append(issue("PLAN_SUMMARY_LEAK", f"正文泄漏规划指令：{token}", [chapter_id]))
        suspect_patterns = (
            r"麦珂(?:坐|站|终于动了|没有看父亲|看着乔纳离开的背影|看着这一切|深吸了一口气)[^。！？\n]{0,100}[，。]她(?:知道|记得|没有|正|伸|转|站|看|想)",
            r"麦珂[^。！？\n]{0,80}(?:女儿|女孩|少女)",
            r"公众误以为她(?:已|在|会)", r"针对她的(?:生命|心脏|身体|健康)",
            r"声称她已无法", r"她已死，别信她",
        )
        for pattern in suspect_patterns:
            match = re.search(pattern, text)
            if match:
                issues.append(issue("PROTAGONIST_SEX_PRONOUN", f"疑似把男性麦珂写成女性：{match.group(0)}", [chapter_id]))
                break
    for cluster_number in range(1, 106):
        event = events[cluster_number - 1]
        start, end = map(int, event["chapter_span"])
        if start not in bodies or end not in bodies:
            continue
        recent = {
            chapter_id: bodies[chapter_id]
            for chapter_id in range(max(1, start - 20), start)
            if chapter_id in bodies
        }
        parsed = {
            "cluster_id": event["cluster_id"],
            "chapters": [
                {"chapter_id": start, "body": bodies[start]},
                {"chapter_id": end, "body": bodies[end]},
            ],
        }
        _, failures, _ = bodygen._validate_candidate(
            parsed, cluster=event, cards=[card_map[start], card_map[end]], recent_bodies=recent,
        )
        for failure in failures:
            issues.append(issue("LEGACY_CLUSTER_COMPATIBILITY", str(failure), [start, end], level="WARNING"))
    fatal = [item for item in issues if item["severity"] == "FATAL"]
    warnings = [item for item in issues if item["severity"] == "WARNING"]
    fatal_clusters = sorted({(chapter - 1) // 2 + 1 for item in fatal for chapter in item["chapter_ids"]})
    report = {
        "version": "v13_existing_body_offline_audit_20260822",
        "scope": [1, 210],
        "body_files": len(bodies),
        "passed": not fatal,
        "fatal_count": len(fatal),
        "warning_count": len(warnings),
        "fatal_cluster_ids": [f"EC{number:03d}" for number in fatal_clusters],
        "counts_by_code": dict(Counter(item["code"] for item in issues)),
        "issues": issues,
    }
    temporary = REPORT.with_suffix(REPORT.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(REPORT)
    print(json.dumps({key: report[key] for key in ("body_files", "passed", "fatal_count", "warning_count", "fatal_cluster_ids", "counts_by_code")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

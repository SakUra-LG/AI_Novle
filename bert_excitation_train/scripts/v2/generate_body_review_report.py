"""Generate the body review report only from files and machine receipts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", type=int, default=211)
    parser.add_argument("--report-name", default=None, help="默认按实际证据范围命名")
    args = parser.parse_args()
    out = args.output_dir.resolve()
    chapters = out / "chapters"
    quarantine_chapters = out / "body_generation" / "quarantine"
    present = []
    for path in chapters.glob("chapter_*.txt"):
        try:
            chapter_id = int(path.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        if chapter_id >= args.start:
            present.append(chapter_id)
    for path in quarantine_chapters.glob("rewrite_pending_*/chapters/chapter_*.txt"):
        try:
            chapter_id = int(path.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        if chapter_id >= args.start:
            present.append(chapter_id)
    present.sort()
    present = sorted(set(present))
    end = max(present, default=args.start - 1)
    missing = [x for x in range(args.start, end + 1) if x not in set(present)]
    audit_dir = out / "body_generation" / "quality_audits"
    prov_dir = out / "body_generation" / "provenance"
    rows = []
    for cluster in range((args.start + 1) // 2, end // 2 + 1):
        ids = [cluster * 2 - 1, cluster * 2]
        audit = audit_dir / f"EC{cluster:03d}_manual_acceptance.json"
        prov = prov_dir / f"EC{cluster:03d}.json"
        audit_payload = json.loads(audit.read_text(encoding="utf-8")) if audit.is_file() else {}
        prov_payload = json.loads(prov.read_text(encoding="utf-8")) if prov.is_file() else {}
        rows.append({
            "cluster": f"EC{cluster:03d}",
            "chapters": ids,
            "chapter_files": {str(i): ("PRESENT" if (chapters / f"chapter_{i:03d}.txt").is_file() else ("QUARANTINED" if any(quarantine_chapters.glob(f"rewrite_pending_*/chapters/chapter_{i:03d}.txt")) else "MISSING")) for i in ids},
            "acceptance": audit_payload.get("status") or ("ACCEPTED" if audit_payload.get("accepted") is True else "MISSING"),
            "audit_evidence": "PRESENT" if audit.is_file() else "MISSING",
            "provenance_evidence": "PRESENT" if prov.is_file() else "MISSING",
            "story_memory_receipt": (
                "PRESENT_BUT_QUARANTINED"
                if any((out / "knowledge_graph" / "stories").glob("*/chapter_memory/chapter_%03d_memory.json" % ids[0]))
                else "MISSING"
            ),
            "neo4j_receipt": "NOT_RUN_OR_NOT_EVIDENCED",
            "authoritative": bool(audit_payload.get("authoritative") and prov_payload.get("authoritative")),
        })
    report = [f"# 正文证据审查报告（自动生成：第{args.start}—{end}章）", "", "本文件由实际章节文件、验收JSON、provenance、StoryMemory/Neo4j可见回执生成；禁止手写通过结论。", "", f"- present_chapters: {len(present)}", f"- missing_chapters: {missing or 'NONE'}", f"- formal_contiguous_max_from_1: {next((i - 1 for i in range(1, end + 2) if not (chapters / f'chapter_{i:03d}.txt').is_file()), end)}", "", "| EC | 章节文件 | 验收证据 | provenance | StoryMemory | Neo4j | 权威状态 |", "|---|---|---|---|---|---|---|"]
    for row in rows:
        report.append("| {cluster} | {chapter_files} | {audit_evidence} ({acceptance}) | {provenance_evidence} | {story_memory_receipt} | {neo4j_receipt} | {authoritative} |".format(**row))
    report.extend(["", "## 明确缺失", "", *[f"- chapter_{x:03d}: MISSING" for x in missing]])
    # The filename is evidence-derived too; never leave a 211_500 label on a
    # report whose actual observed range ends earlier.
    report_name = args.report_name or f"BODY_BATCH_MANUAL_REVIEW_{args.start}_{end}.md"
    target = out / report_name
    target.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()

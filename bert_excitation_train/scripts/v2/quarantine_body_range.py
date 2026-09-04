"""Quarantine an existing body range without deleting the original files."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", type=int, default=271)
    parser.add_argument("--end", type=int, default=356)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    q = out / "body_generation" / "quarantine" / f"rewrite_pending_{args.start}_{args.end}_{stamp}"
    q_chapters = q / "chapters"
    q_chapters.mkdir(parents=True, exist_ok=True)
    chapter_rows = []
    for chapter_id in range(args.start, args.end + 1):
        source = out / "chapters" / f"chapter_{chapter_id:03d}.txt"
        row = {"chapter_id": chapter_id, "source": str(source), "status": "MISSING"}
        if source.is_file():
            data = source.read_bytes()
            shutil.copy2(source, q_chapters / source.name)
            row.update({"status": "rewrite_pending", "sha256": hashlib.sha256(data).hexdigest()})
        chapter_rows.append(row)
    for audit_dir in (out / "body_generation" / "quality_audits", out / "body_generation" / "provenance"):
        if not audit_dir.is_dir():
            continue
        for path in audit_dir.glob("EC*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            ids = [int(x) for x in payload.get("chapter_ids", []) if str(x).isdigit()]
            if ids and min(ids) >= args.start and max(ids) <= args.end:
                payload["status"] = "quarantine_rewrite_pending"
                payload["accepted"] = False
                payload["authoritative"] = False
                payload["quarantine_reason"] = "EC136-EC178 architecture and synopsis repair"
                payload["quarantined_at"] = stamp
                atomic_json(path, payload)
    manifest = {
        "version": "quarantine_manifest_v1",
        "range": [args.start, args.end],
        "status": "rewrite_pending",
        "authoritative_formal_continuous_max": 270,
        "formal_story_memory_and_neo4j_writes": "blocked_for_range",
        "created_at": stamp,
        "backup_dir": str(q_chapters),
        "chapters": chapter_rows,
    }
    atomic_json(q / "quarantine_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

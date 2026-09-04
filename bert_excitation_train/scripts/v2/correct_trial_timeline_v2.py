"""Auditable date-only correction for the isolated 293-296 trial."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

_cwd = Path.cwd()
ROOT = _cwd if (_cwd / "outputs_pop_king_v6_compiled_story_first_500").is_dir() else Path(__file__).resolve().parents[2]
OUT = Path("outputs_pop_king_v6_compiled_story_first_500") if ROOT == _cwd else ROOT / "outputs_pop_king_v6_compiled_story_first_500"
AUDIT_DIR = OUT / "body_generation" / "three_act_trial_v2_293_296"
FILES = [
    OUT / "chapter_synopses_v5_qwen_500.json",
    OUT / "master_ctx_cards_v2.json",
    OUT / "event_clusters_v2.json",
]
DATES = {294: ("1994-04-03", "1994-04-03"), 296: ("1994-06-04", "1994-06-04")}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def transform(value, path=""):
    changes = []
    if isinstance(value, dict):
        out = {}
        chapter_id = value.get("chapter_id")
        for key, item in value.items():
            if chapter_id in DATES and key in ("timeline_start", "timeline_end"):
                new_value = DATES[chapter_id][0 if key == "timeline_start" else 1]
                if item != new_value:
                    changes.append({"path": f"{path}/{key}", "old": item, "new": new_value})
                out[key] = new_value
            else:
                new_item, item_changes = transform(item, f"{path}/{key}")
                out[key] = new_item
                changes.extend(item_changes)
        return out, changes
    if isinstance(value, list):
        out = []
        for index, item in enumerate(value):
            new_item, item_changes = transform(item, f"{path}/{index}")
            out.append(new_item)
            changes.extend(item_changes)
        return out, changes
    return value, []


def main():
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = OUT / "body_generation" / "trial_v2_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    file_records = []
    for path in FILES:
        backup = backup_dir / f"{stamp}_{path.name}"
        print("BACKUP", repr(str(path)), repr(str(backup)), path.exists(), backup.parent.exists())
        backup.write_bytes(path.read_bytes())
        before_bytes = path.read_bytes()
        before = json.loads(before_bytes.decode("utf-8"))
        after, changes = transform(before)
        path.write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        file_records.append({
            "file": str(path), "backup": str(backup),
            "sha256_before": hashlib.sha256(before_bytes).hexdigest(),
            "sha256_after": sha(path), "changes": changes,
        })
    audit = {
        "purpose": "three_act_trial_v2_293_296 timeline correction",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "date_changes": {"294": ["1994-04-03", "1994-04-03"], "296": ["1994-06-04", "1994-06-04"]},
        "reason": "294 must occur one week after 293; 296 must occur after 295; chapter 270 continuity remains the baseline.",
        "plot_fields_changed": False,
        "files": file_records,
    }
    (AUDIT_DIR / "time_correction_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"audit": str(AUDIT_DIR / "time_correction_audit.json"), "changes": sum(len(x["changes"]) for x in file_records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

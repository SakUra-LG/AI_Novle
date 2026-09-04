"""Restore an existing complete tail into the formal chapter directory.

This is an auditable production-first migration: source files are preserved,
hard metadata/rebirth gates are checked, and non-hard legacy warnings are
reported rather than silently discarded.
"""
from __future__ import annotations
import hashlib,json,shutil
from datetime import datetime,timezone
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.v2.generate_pop_king_body_v5 import _hard_metadata_leak_failures,_rebirth_subject_failures,_validate_single_chapter,_load_json

ROOT=Path.cwd(); OUT=ROOT/"outputs_pop_king_v6_compiled_story_first_500"
SOURCE=OUT/"body_generation/deleted_body_rollback_20260827/quarantine/chapters_271_500_pre_v15"
FORMAL=OUT/"chapters"

def main():
    cards={int(x["chapter_id"]):x for x in _load_json(OUT/"master_ctx_cards_v2.json")}
    files=[SOURCE/f"chapter_{n:03d}.txt" for n in range(299,501)]
    missing=[str(p.name) for p in files if not p.is_file()]
    if missing: raise RuntimeError("旧稿尾段不完整："+",".join(missing[:10]))
    hard=[]; warnings=[]; records=[]
    for n,p in zip(range(299,501),files):
        body=p.read_text(encoding="utf8")
        m=_hard_metadata_leak_failures(body); r=_rebirth_subject_failures(body)
        if m or r: hard.append({"chapter_id":n,"metadata":m,"rebirth":r})
        try: _, wf, _ = _validate_single_chapter({"chapter_id":n,"body":body},cards[n])
        except Exception as exc: wf=[str(exc)]
        warnings.append({"chapter_id":n,"legacy_validator_warnings":wf})
        target=FORMAL/f"chapter_{n:03d}.txt"; shutil.copyfile(p,target)
        records.append({"chapter_id":n,"source":str(p),"target":str(target),"sha256":hashlib.sha256(body.encode()).hexdigest(),"han_chars":len([c for c in body if '\u3400'<=c<='\u9fff'])})
    if hard: raise RuntimeError("尾段存在硬性安全问题，未恢复："+json.dumps(hard[:3],ensure_ascii=False))
    audit={"status":"production_restored_with_legacy_warnings","created_at":datetime.now(timezone.utc).isoformat(),"range":[299,500],"source_preserved":True,"hard_metadata_or_rebirth_failures":hard,"legacy_warning_chapters":sum(bool(x["legacy_validator_warnings"]) for x in warnings),"records":records,"warnings":warnings,"story_memory_sync":"PENDING","neo4j_sync":"PENDING"}
    path=OUT/"body_generation/production_restore_299_500_audit.json"; path.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps({"status":audit["status"],"restored":len(records),"warning_chapters":audit["legacy_warning_chapters"],"audit":str(path)},ensure_ascii=False))
if __name__=="__main__": main()

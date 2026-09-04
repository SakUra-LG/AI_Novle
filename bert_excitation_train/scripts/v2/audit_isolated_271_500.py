from __future__ import annotations
import hashlib, json, re, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from bert_excitation_train.scripts.v2.generate_pop_king_body_v5 import _hard_metadata_leak_failures, _paragraph_quality_failures, _rebirth_subject_failures

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs_pop_king_v6_compiled_story_first_500"
BASE = OUT / "body_generation"

def main() -> None:
    files = {}
    duplicates = {}
    for trial in sorted(BASE.glob("rewrite_trial_*")):
        if "legacy" in trial.name:
            continue
        for f in (trial / "chapters").glob("chapter_*.txt"):
            n = int(f.stem.split("_")[-1])
            if 271 <= n <= 500:
                files.setdefault(n, f)
                duplicates.setdefault(n, []).append(str(f.relative_to(OUT)))
    issues = []
    hashes = {}
    dates = {}
    for n in range(271, 501):
        f = files.get(n)
        if not f:
            issues.append(f"MISSING chapter_{n}")
            continue
        body = f.read_text(encoding="utf-8")
        hashes[n] = hashlib.sha256(body.encode()).hexdigest()
        m = re.search(r"(199[34])年\s*(\d{1,2})月\s*(\d{1,2})日", body)
        if m:
            dates[n] = date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        else:
            issues.append(f"chapter_{n}: missing opening date")
        for label, fn in (("metadata", _hard_metadata_leak_failures), ("paragraph", _paragraph_quality_failures), ("rebirth", _rebirth_subject_failures)):
            for msg in fn(body):
                issues.append(f"chapter_{n} {label}: {msg}")
        if n > 271 and n in dates and (n - 1) in dates and dates[n] < dates[n - 1]:
            issues.append(f"chapter_{n}: timeline retreats from chapter_{n-1}")
    duplicate_numbers = {str(k): v for k, v in duplicates.items() if len(v) > 1}
    report = {"scope":"isolated candidates 271-500", "status":"PASS_WITHOUT_ACCEPTANCE" if not issues else "REVISE_REQUIRED", "trial_only_not_accepted":True, "formal_story_memory_write":False, "neo4j_write":False, "external_semantic_critic":"not_run", "chapters_found":len(files), "expected_chapters":230, "duplicate_candidate_numbers":duplicate_numbers, "issues":issues, "sha256":hashes, "dates":dates}
    (OUT / "isolated_271_500_full_candidate_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines=["# 第271—500章隔离候选全量终审", "", f"状态：{report['status']}", "", "- 正式连续线：第1—270章", "- 隔离候选：第271—500章", "- StoryMemory/Neo4j写入：否", "- 外部语义审稿：NOT_RUN", f"- 候选章节数：{len(files)}/230", f"- 重复候选编号：{len(duplicate_numbers)}", "", "## 问题"]
    lines += [f"- {x}" for x in issues] or ["- 无结构性问题"]
    (OUT / "isolated_271_500_full_candidate_audit.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps({"status":report["status"],"chapters_found":len(files),"issues":len(issues),"duplicate_candidate_numbers":len(duplicate_numbers)}, ensure_ascii=False))

if __name__ == "__main__":
    main()

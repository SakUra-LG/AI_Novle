import argparse
import json
import re
from pathlib import Path

from docx import Document


CHAPTER_RE = re.compile(r"^第\s*(\d+)\s*章(?:\s+|　*)(.*)$")
PUNCT_RE = re.compile(r"[\s，。、“”‘’：；！？《》〈〉（）()\[\]【】·—…,.!?:;\-_/]+")


def normalize(text):
    return PUNCT_RE.sub("", str(text or "")).lower()


def load_synopses(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        for key in ("chapters", "chapter_synopses", "data"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    result = {}
    for item in raw:
        number = item.get("chapter_id", item.get("chapter", item.get("number")))
        if number is not None:
            result[int(number)] = item
    return result


def extract_chapters(path):
    doc = Document(path)
    chapters = {}
    current = None
    for index, paragraph in enumerate(doc.paragraphs):
        text = paragraph.text.strip()
        match = CHAPTER_RE.match(text)
        # The revised tail currently uses a different paragraph style for chapter
        # titles, which is one of the defects this audit is intended to detect.
        if match:
            current = int(match.group(1))
            chapters[current] = {
                "heading": text,
                "subtitle": match.group(2).strip(),
                "heading_index": index,
                "heading_style": paragraph.style.name,
                "paragraphs": [],
            }
            continue
        if current is not None and text:
            chapters[current]["paragraphs"].append(text)
    for item in chapters.values():
        item["text"] = "\n".join(item["paragraphs"])
        item["char_count"] = len(normalize(item["text"]))
        item["paragraph_count"] = len(item["paragraphs"])
    return chapters


def phrases(text, min_len=2):
    parts = re.split(r"[，。、“”‘’：；！？《》〈〉（）()\[\]【】·—…,.!?:;\s]+", str(text or ""))
    return [normalize(part) for part in parts if len(normalize(part)) >= min_len]


def coverage(source, target):
    source_parts = phrases(source)
    if not source_parts:
        return 1.0, []
    target_norm = normalize(target)
    matched = []
    for part in source_parts:
        # Long synopsis clauses may be paraphrased; use informative 4-char windows.
        windows = [part[i:i + 4] for i in range(max(1, len(part) - 3))] if len(part) > 4 else [part]
        hit = sum(1 for window in windows if window in target_norm)
        ratio = hit / len(windows)
        if ratio >= 0.18 or part in target_norm:
            matched.append(part)
    return len(matched) / len(source_parts), [p for p in source_parts if p not in matched]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("docx")
    parser.add_argument("synopses")
    parser.add_argument("--start", type=int, default=299)
    parser.add_argument("--end", type=int, default=500)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    chapters = extract_chapters(args.docx)
    synopses = load_synopses(args.synopses)
    rows = []
    for number in range(args.start, args.end + 1):
        body = chapters.get(number)
        plan = synopses.get(number)
        if not body or not plan:
            rows.append({"chapter": number, "missing_body": not bool(body), "missing_plan": not bool(plan), "score": 0})
            continue
        text = body["text"]
        title = str(plan.get("chapter_title", "")).strip()
        title_ok = normalize(body["subtitle"]) == normalize(title)
        location = str(plan.get("scene_location", ""))
        location_ok = not location or normalize(location) in normalize(text)
        participants = [str(x) for x in plan.get("participants", [])]
        alias_map = {}
        for cast in plan.get("canonical_cast", []):
            alias_map[str(cast.get("name", ""))] = [str(x) for x in cast.get("aliases", [])]
        participant_hits = []
        for name in participants:
            base = name.split("（")[0]
            aliases = alias_map.get(base, [base])
            if any(normalize(alias) in normalize(text) for alias in aliases if normalize(alias)):
                participant_hits.append(name)
        must_include = [str(x) for x in plan.get("chapter_must_include", [])]
        include_results = []
        for item in must_include:
            cov, missing = coverage(item, text)
            include_results.append({"item": item, "coverage": round(cov, 3), "missing": missing})
        action_results = []
        for item in plan.get("exact_action_sequence", []):
            cov, missing = coverage(item, text)
            action_results.append({"item": item, "coverage": round(cov, 3), "missing": missing})
        forbidden_hits = []
        for item in plan.get("chapter_must_not_include", []):
            if normalize(item) and normalize(item) in normalize(text):
                forbidden_hits.append(item)
        synopsis_cov, synopsis_missing = coverage(plan.get("detailed_synopsis", ""), text)
        include_avg = sum(x["coverage"] for x in include_results) / max(1, len(include_results))
        action_avg = sum(x["coverage"] for x in action_results) / max(1, len(action_results))
        participant_ratio = len(participant_hits) / max(1, len(participants))
        score = (
            15 * title_ok
            + 10 * location_ok
            + 15 * participant_ratio
            + 25 * include_avg
            + 25 * action_avg
            + 10 * synopsis_cov
            - 15 * len(forbidden_hits)
        )
        rows.append({
            "chapter": number,
            "heading": body["heading"],
            "plan_goal": plan.get("chapter_goal", ""),
            "plan_synopsis": plan.get("detailed_synopsis", ""),
            "char_count": body["char_count"],
            "paragraph_count": body["paragraph_count"],
            "title_ok": title_ok,
            "location_ok": location_ok,
            "participant_hits": participant_hits,
            "participant_total": len(participants),
            "must_include": include_results,
            "action_sequence": action_results,
            "synopsis_coverage": round(synopsis_cov, 3),
            "synopsis_missing": synopsis_missing,
            "forbidden_hits": forbidden_hits,
            "score": round(max(0, min(100, score)), 1),
            "opening": text[:120],
            "ending": text[-160:],
        })

    scores = [row["score"] for row in rows if "score" in row]
    report = {
        "range": [args.start, args.end],
        "chapter_count": len(rows),
        "missing_body": [r["chapter"] for r in rows if r.get("missing_body")],
        "missing_plan": [r["chapter"] for r in rows if r.get("missing_plan")],
        "under_1000": [r["chapter"] for r in rows if r.get("char_count", 1000) < 1000],
        "over_1600": [r["chapter"] for r in rows if r.get("char_count", 0) > 1600],
        "title_mismatch": [r["chapter"] for r in rows if r.get("title_ok") is False],
        "location_missing": [r["chapter"] for r in rows if r.get("location_ok") is False],
        "score_below_75": [r["chapter"] for r in rows if r.get("score", 0) < 75],
        "average_score": round(sum(scores) / max(1, len(scores)), 2),
        "rows": rows,
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

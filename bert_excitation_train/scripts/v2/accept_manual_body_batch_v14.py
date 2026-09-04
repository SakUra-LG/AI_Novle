"""Accept a human-authored two-chapter batch after deterministic and manual review."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bert_excitation_train.scripts.v2 import generate_pop_king_body_v5 as bodygen


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = ROOT / "bert_excitation_train" / "outputs_pop_king_v6_compiled_story_first_500"


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _formal_contiguous_max(out: Path) -> int:
    """Return the last physically continuous chapter, never jumping a gap."""
    chapter_dir = out / "chapters"
    current = 0
    while (chapter_dir / f"chapter_{current + 1:03d}.txt").is_file():
        current += 1
    return current


def _load_external_review(path: Path, chapter_ids: list[int], hashes: dict[str, str]) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError("未提供外部人工review JSON；禁止验收")
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"人工review JSON不可读：{exc}") from exc
    if not isinstance(review, dict):
        raise RuntimeError("人工review JSON必须是对象")
    for field in ("reviewer", "reviewed_at", "chapter_reviews", "decision"):
        if not review.get(field):
            raise RuntimeError(f"人工review缺少必填字段：{field}")
    if str(review["decision"]).lower() not in {"accepted", "pass", "passed"}:
        raise RuntimeError(f"人工review决策不是通过：{review['decision']}")
    rows = review["chapter_reviews"]
    if not isinstance(rows, list):
        raise RuntimeError("人工review.chapter_reviews必须是数组")
    by_id = {str(row.get("chapter_id")): row for row in rows if isinstance(row, dict)}
    for chapter_id in chapter_ids:
        row = by_id.get(str(chapter_id))
        if not row or row.get("sha256") != hashes[str(chapter_id)]:
            raise RuntimeError(f"人工review未覆盖当前哈希：chapter_{chapter_id}")
        if "issues" not in row or "fixes" not in row:
            raise RuntimeError(f"人工review缺少逐章问题/修复记录：chapter_{chapter_id}")
    return review


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cluster", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--review-json", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    cluster_id = f"EC{args.cluster:03d}"
    events, card_map, _ = bodygen._load_inputs(out)
    event = next(item for item in events if item["cluster_id"] == cluster_id)
    chapter_ids = [int(value) for value in event["chapter_span"]]
    if chapter_ids[1] != chapter_ids[0] + 1:
        raise RuntimeError("manual acceptance requires a consecutive two-chapter event")
    formal_max = _formal_contiguous_max(out)
    if chapter_ids[0] != formal_max + 1:
        raise RuntimeError(
            f"验收批次必须从当前连续正式最大章节+1开始：formal_max={formal_max}, "
            f"batch_start={chapter_ids[0]}"
        )
    prior_cluster = f"EC{args.cluster - 1:03d}"
    if args.cluster > 1:
        prior_path = out / "body_generation" / "quality_audits" / f"{prior_cluster}_manual_acceptance.json"
        if not prior_path.is_file():
            raise RuntimeError(f"前一个EC缺少验收记录：{prior_cluster}")
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        if prior.get("accepted") is not True or prior.get("status", "").startswith("quarantine"):
            raise RuntimeError(f"前一个EC未处于正式accepted状态：{prior_cluster}")
    bodies = {
        chapter_id: (out / "chapters" / f"chapter_{chapter_id:03d}.txt").read_text(encoding="utf-8")
        for chapter_id in chapter_ids
    }
    single: dict[str, Any] = {}
    failures: list[str] = []
    for chapter_id in chapter_ids:
        _, chapter_failures, audit = bodygen._validate_single_chapter(
            {"chapter_id": chapter_id, "body": bodies[chapter_id]}, card_map[chapter_id]
        )
        failures.extend(f"chapter_{chapter_id}: {value}" for value in chapter_failures)
        single[str(chapter_id)] = audit
    recent = {
        chapter_id: (out / "chapters" / f"chapter_{chapter_id:03d}.txt").read_text(encoding="utf-8")
        for chapter_id in range(max(1, chapter_ids[0] - 20), chapter_ids[0])
        if (out / "chapters" / f"chapter_{chapter_id:03d}.txt").is_file()
    }
    recent_family = {
        chapter_id: (out / "chapters" / f"chapter_{chapter_id:03d}.txt").read_text(encoding="utf-8")
        for chapter_id in range(max(1, chapter_ids[0] - 40), chapter_ids[0])
        if (out / "chapters" / f"chapter_{chapter_id:03d}.txt").is_file()
    }
    parsed = {
        "cluster_id": cluster_id,
        "chapters": [
            {"chapter_id": chapter_id, "body": bodies[chapter_id]}
            for chapter_id in chapter_ids
        ],
    }
    _, joint_failures, joint_audit = bodygen._validate_candidate(
        parsed, cluster=event,
        cards=[card_map[chapter_id] for chapter_id in chapter_ids],
        recent_bodies=recent,
        recent_family_bodies=recent_family,
    )
    failures.extend(f"joint: {value}" for value in joint_failures)
    if failures:
        raise RuntimeError("manual batch failed deterministic gates:\n" + "\n".join(failures))
    now = datetime.now(timezone.utc).isoformat()
    hashes = {
        str(chapter_id): hashlib.sha256(bodies[chapter_id].encode("utf-8")).hexdigest()
        for chapter_id in chapter_ids
    }
    external_review = _load_external_review(args.review_json.resolve(), chapter_ids, hashes)
    audit_record = {
        "version": "v14_manual_batch_acceptance",
        "cluster_id": cluster_id,
        "chapter_ids": chapter_ids,
        "accepted": external_review["decision"].lower() in {"accepted", "pass", "passed"},
        "authoritative": True,
        "reviewer": external_review["reviewer"],
        "reviewed_at": external_review["reviewed_at"],
        "generation_mode": "human_authored_due_to_missing_external_model_credential",
        "manual_full_text_review": {
            "passed": external_review["decision"].lower() in {"accepted", "pass", "passed"},
            "source": "external_review_json",
            "review_json": str(args.review_json.resolve()),
            "reviewed_dimensions": [
                "two_chapter_function_separation", "character_identity_and_authority",
                "timeline_and_era_technology", "artifact_scope", "settlement_actions",
                "recent_twenty_chapter_repetition", "prose_readability",
            ],
        },
        "external_semantic_critic": {
            "status": "not_run",
            "passed": None,
        },
        "deterministic_validation": {
            "passed": True, "single": single, "joint": joint_audit,
        },
        "chapter_sha256": hashes,
        "accepted_at": now,
    }
    write(out / "body_generation" / "quality_audits" / f"{cluster_id}_manual_acceptance.json", audit_record)
    provenance = {
        "version": "v14_manual_body_provenance",
        "cluster_id": cluster_id,
        "chapter_ids": chapter_ids,
        "accepted": external_review["decision"].lower() in {"accepted", "pass", "passed"},
        "authoritative": True,
        "reviewer": external_review["reviewer"],
        "reviewed_at": external_review["reviewed_at"],
        "generation_mode": audit_record["generation_mode"],
        "manual_full_text_review_passed": external_review["decision"].lower() in {"accepted", "pass", "passed"},
        "deterministic_validation_passed": True,
        "external_semantic_critic_status": "not_run",
        "chapter_sha256": hashes,
        "accepted_at": now,
    }
    write(out / "body_generation" / "provenance" / f"{cluster_id}.json", provenance)
    draft_path = out / "body_generation" / "manual_drafts" / f"{cluster_id}.json"
    if draft_path.is_file():
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        draft["status"] = "accepted_after_manual_review_and_deterministic_validation"
        draft["accepted_at"] = now
        write(draft_path, draft)
    print(json.dumps(provenance, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

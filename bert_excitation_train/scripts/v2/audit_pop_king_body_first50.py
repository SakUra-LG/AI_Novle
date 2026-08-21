"""Audit an official even-numbered Qwen-generated chapter prefix end to end.

The report proves that official prose is unchanged Qwen output, planning inputs
are either the full 250-cluster set or a compiler-clean contiguous prefix,
chapter memories and Neo4j are in sync, and every target chapter passes.
"""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bert_excitation_train.scripts.neo4j_kg.chapter_memory import content_hash
from bert_excitation_train.scripts.neo4j_kg.common import get_neo4j_driver
from bert_excitation_train.scripts.neo4j_kg.planning_graph import planning_story_id
from bert_excitation_train.scripts.v2.generate_pop_king_body_v5 import (
    BODY_GENERATOR_CONTRACT_VERSION,
    _bootstrap_neo4j_env,
    _han_count,
    _load_inputs,
    _normalize_body,
    _prior_body_chain_sha256,
    _parse_json_object,
    _sha,
    _validate_candidate,
    _validate_single_chapter,
)
from bert_excitation_train.scripts.v2.pop_king_plan_compiler import (
    body_prefix_fingerprints,
    card_fingerprint,
    event_fingerprint,
    plan_fingerprints,
    validate_full_plan,
)


REPO_ROOT = PROJECT_ROOT
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "bert_excitation_train"
    / "outputs_pop_king_v6_compiled_story_first_500"
)
DEFAULT_STYLE_SAMPLES = (
    REPO_ROOT
    / "bert_excitation_train"
    / "data"
    / "pop_king_revenge_style_samples_v1.json"
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ids(paths: list[Path], pattern: str) -> tuple[list[int], list[str]]:
    parsed: list[int] = []
    bad: list[str] = []
    regex = re.compile(pattern)
    for path in paths:
        match = regex.fullmatch(path.name)
        if match:
            parsed.append(int(match.group(1)))
        else:
            bad.append(path.name)
    return sorted(parsed), bad


def _record(
    checks: dict[str, Any],
    name: str,
    *,
    passed: bool,
    evidence: Any,
    failures: list[str] | None = None,
) -> None:
    checks[name] = {
        "passed": bool(passed),
        "evidence": evidence,
        "failures": failures or [],
    }


def audit(
    output_dir: Path,
    style_samples_path: Path,
    neo4j_container: str,
    end_chapter: int = 50,
) -> dict[str, Any]:
    if end_chapter < 2 or end_chapter > 500 or end_chapter % 2:
        raise ValueError("end_chapter must be an even number from 2 through 500")
    target_cluster_count = end_chapter // 2
    checks: dict[str, Any] = {}
    try:
        events, card_map, outline = _load_inputs(output_dir)
    except Exception as exc:  # noqa: BLE001
        _record(
            checks,
            "authoritative_body_inputs_present",
            passed=False,
            evidence={"output_dir": str(output_dir)},
            failures=[str(exc)],
        )
        return {
            "schema_version": 1,
            "scope": f"official_first_{end_chapter}_chapters",
            "story_id": "",
            "output_dir": str(output_dir),
            "overall_passed": False,
            "failed_checks": ["authoritative_body_inputs_present"],
            "checks": checks,
        }
    story_id = planning_story_id(outline)

    event_primary = output_dir / "event_clusters_v2.json"
    event_archive = output_dir / "event_clusters_v5_qwen_500.json"
    card_primary = output_dir / "master_ctx_cards_v2.json"
    card_archive = output_dir / "chapter_synopses_v5_qwen_500.json"
    event_hash = _file_sha(event_primary)
    card_hash = _file_sha(card_primary)
    complete_plan = len(events) == 250 and len(card_map) == 500
    planning_prefix_covers_target = (
        len(events) >= target_cluster_count
        and len(card_map) >= end_chapter
        and len(card_map) == len(events) * 2
    )
    _record(
        checks,
        "authoritative_planning_and_archives",
        passed=(
            planning_prefix_covers_target
            and event_hash == _file_sha(event_archive)
            and card_hash == _file_sha(card_archive)
        ),
        evidence={
            "event_clusters": len(events),
            "chapter_cards": len(card_map),
            "event_primary_sha256": event_hash,
            "event_archive_sha256": _file_sha(event_archive),
            "card_primary_sha256": card_hash,
            "card_archive_sha256": _file_sha(card_archive),
        },
    )

    expected_cluster_ids = [f"EC{number:03d}" for number in range(1, len(events) + 1)]
    actual_cluster_ids = [str(event.get("cluster_id") or "") for event in events]
    spans_ok = all(
        [int(value) for value in (event.get("chapter_span") or [])]
        == [2 * index - 1, 2 * index]
        for index, event in enumerate(events, 1)
    )
    expected_cards = list(range(1, len(card_map) + 1))
    _record(
        checks,
        "two_chapters_per_event_cluster",
        passed=(
            actual_cluster_ids == expected_cluster_ids
            and spans_ok
            and sorted(card_map) == expected_cards
        ),
        evidence={
            "cluster_ids_sequential": actual_cluster_ids == expected_cluster_ids,
            "all_spans_strict_two_chapter_pairs": spans_ok,
            "card_ids_cover_authoritative_prefix": sorted(card_map) == expected_cards,
        },
    )

    required_event_fields = (
        "fictional_obstacle",
        "prev_life_tragedy",
        "info_gap_from_prev_life",
        "this_life_revenge",
        "comic_villain_behavior",
        "villain_loss",
        "protagonist_gain",
        "relationship_change",
    )
    event_field_counts = {
        field: sum(event.get(field) not in (None, "", []) for event in events)
        for field in required_event_fields
    }
    required_card_fields = (
        "info_gap_from_prev_life",
        "info_gap_use",
        "this_life_revenge",
        "opponent_reaction",
        "immediate_payoff",
    )
    card_field_counts = {
        field: sum(card.get(field) not in (None, "", []) for card in card_map.values())
        for field in required_card_fields
    }
    style_samples = _load_json(style_samples_path)
    style_valid = isinstance(style_samples, list) and bool(style_samples) and all(
        isinstance(sample, dict)
        and str(sample.get("text") or "").strip()
        and (sample.get("focus") or [])
        for sample in style_samples
    )
    _record(
        checks,
        "revenge_information_gap_character_and_emotion_inputs",
        passed=(
            all(count == len(events) for count in event_field_counts.values())
            and all(count == len(card_map) for count in card_field_counts.values())
            and style_valid
        ),
        evidence={
            "event_field_nonempty_counts": event_field_counts,
            "card_field_nonempty_counts": card_field_counts,
            "style_sample_count": len(style_samples) if isinstance(style_samples, list) else 0,
            "style_samples_valid": style_valid,
        },
    )
    ordered_cards = [card_map[index] for index in sorted(card_map)]
    plan_report = validate_full_plan(
        events, ordered_cards, allow_partial=not complete_plan, global_outline=outline,
    )
    fingerprints = plan_fingerprints(
        outline=outline, events=events, cards=ordered_cards, style_samples=style_samples,
    )
    _record(
        checks,
        "full_plan_compiler_and_fingerprints",
        passed=plan_report["passed"],
        evidence={"compiler_evidence": plan_report["evidence"], "fingerprints": fingerprints},
        failures=plan_report["failures"],
    )

    chapters_dir = output_dir / "chapters"
    chapter_paths = [
        path for path in sorted(chapters_dir.glob("chapter_*.txt"))
        if (match := re.fullmatch(r"chapter_(\d{3})\.txt", path.name))
        and int(match.group(1)) <= end_chapter
    ]
    chapter_ids, malformed_chapter_names = _ids(
        chapter_paths, r"chapter_(\d{3})\.txt"
    )
    provenance_dir = output_dir / "body_generation" / "provenance"
    provenance_paths = [
        path for path in sorted(provenance_dir.glob("EC*.json"))
        if (match := re.fullmatch(r"EC(\d{3})\.json", path.name))
        and int(match.group(1)) <= target_cluster_count
    ]
    provenance_ids = [path.stem for path in provenance_paths]
    memory_dir = (
        output_dir / "knowledge_graph" / "stories" / story_id / "chapter_memory"
    )
    memory_paths = [
        path for path in sorted(memory_dir.glob("chapter_*_memory.json"))
        if (match := re.fullmatch(r"chapter_(\d{3})_memory\.json", path.name))
        and int(match.group(1)) <= end_chapter
    ]
    memory_ids, malformed_memory_names = _ids(
        memory_paths, r"chapter_(\d{3})_memory\.json"
    )
    _record(
        checks,
        "official_artifact_inventory",
        passed=(
            chapter_ids == list(range(1, end_chapter + 1))
            and not malformed_chapter_names
            and provenance_ids == expected_cluster_ids[:target_cluster_count]
            and memory_ids == list(range(1, end_chapter + 1))
            and not malformed_memory_names
        ),
        evidence={
            "chapter_count": len(chapter_paths),
            "chapter_ids": chapter_ids,
            "provenance_count": len(provenance_paths),
            "provenance_ids": provenance_ids,
            "chapter_memory_count": len(memory_paths),
            "chapter_memory_ids": memory_ids,
            "malformed_chapter_names": malformed_chapter_names,
            "malformed_memory_names": malformed_memory_names,
        },
    )

    body_by_chapter: dict[int, str] = {}
    chapter_failures: dict[str, list[str]] = {}
    han_counts: dict[str, int] = {}
    qwen_failures: dict[str, list[str]] = {}
    memory_failures: dict[str, list[str]] = {}
    review_statuses: dict[str, str] = {}
    quality_audit_dir = output_dir / "body_generation" / "quality_audits"

    for chapter_id in range(1, end_chapter + 1):
        path = chapters_dir / f"chapter_{chapter_id:03d}.txt"
        failures: list[str] = []
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            chapter_failures[str(chapter_id)] = [f"UTF-8读取失败：{exc}"]
            continue
        body = text.strip()
        body_by_chapter[chapter_id] = body
        han_counts[str(chapter_id)] = _han_count(body)
        if "\ufffd" in body:
            failures.append("正文含Unicode替换字符")
        _, validation_failures, _ = _validate_single_chapter(
            {"chapter_id": chapter_id, "body": body}, card_map[chapter_id]
        )
        failures.extend(validation_failures)
        if failures:
            chapter_failures[str(chapter_id)] = failures

        cluster_id = f"EC{(chapter_id + 1) // 2:03d}"
        provenance_path = provenance_dir / f"{cluster_id}.json"
        proof_failures: list[str] = []
        try:
            provenance = _load_json(provenance_path)
        except Exception as exc:  # noqa: BLE001
            qwen_failures[str(chapter_id)] = [f"溯源JSON读取失败：{exc}"]
            continue
        review_statuses[cluster_id] = str(provenance.get("quality_review_status") or "")
        if provenance.get("generated_by") != "qwen":
            proof_failures.append("generated_by不是qwen")
        if provenance.get("manual_edits") != []:
            proof_failures.append("manual_edits不是空数组")
        if provenance.get("body_edit_policy") != "failed_body_is_regenerated_by_qwen_never_manually_patched":
            proof_failures.append("正文不可人工修补策略缺失")
        if provenance.get("body_generator_contract_version") != BODY_GENERATOR_CONTRACT_VERSION:
            proof_failures.append("正文生成提示契约版本不匹配")
        cluster_start = (chapter_id - 1) // 2 * 2 + 1
        if provenance.get("prior_body_chain_sha256") != _prior_body_chain_sha256(
            output_dir, cluster_start
        ):
            proof_failures.append("前文正文链哈希不匹配")
        event = events[(chapter_id - 1) // 2]
        expected_body_fingerprints = body_prefix_fingerprints(
            outline=outline,
            events=events,
            cards=ordered_cards,
            style_samples=style_samples,
            through_cluster=(chapter_id + 1) // 2,
        )
        if provenance.get("plan_fingerprints") != expected_body_fingerprints:
            proof_failures.append("正式正文使用的因果规划前缀指纹不是当前版本")
        if provenance.get("cluster_sha256") != event_fingerprint(event):
            proof_failures.append("正式正文使用的情节族哈希不是当前版本")
        if (provenance.get("card_sha256_by_chapter") or {}).get(str(chapter_id)) != card_fingerprint(card_map[chapter_id]):
            proof_failures.append("正式正文使用的章卡哈希不是当前版本")
        if provenance.get("chapter_sha256", {}).get(str(chapter_id)) != _sha(body):
            proof_failures.append("正式正文哈希与溯源不一致")
        if provenance.get("chapter_han_chars", {}).get(str(chapter_id)) != _han_count(body):
            proof_failures.append("汉字数与溯源不一致")
        raw_value = (provenance.get("accepted_raw_response_paths_by_chapter") or {}).get(
            str(chapter_id)
        )
        raw_path = Path(str(raw_value or ""))
        if not raw_path.is_file():
            proof_failures.append("被接受的Qwen原始响应不存在")
        else:
            raw = raw_path.read_text(encoding="utf-8")
            if (provenance.get("raw_response_sha256_by_chapter") or {}).get(
                str(chapter_id)
            ) != _sha(raw):
                proof_failures.append("Qwen原始响应哈希与溯源不一致")
            try:
                parsed = _parse_json_object(raw)
                if _normalize_body(parsed.get("body")) != body:
                    proof_failures.append("正式正文不是Qwen原始响应中的逐字正文")
            except Exception as exc:  # noqa: BLE001
                proof_failures.append(f"Qwen原始响应无法解析：{exc}")
            audit_path = quality_audit_dir / (
                raw_path.stem.removesuffix("_raw") + ".json"
            )
            if not audit_path.is_file():
                proof_failures.append("被接受候选的质量审计不存在")
            else:
                candidate_audit = _load_json(audit_path)
                if candidate_audit.get("accepted") is not True:
                    proof_failures.append("被接受候选的质量审计未标记accepted=true")
                if candidate_audit.get("generated_by") != "qwen" or candidate_audit.get("manual_edits") != []:
                    proof_failures.append("候选质量审计的Qwen/人工编辑声明不合格")
                if candidate_audit.get("raw_response_sha256") != _sha(raw):
                    proof_failures.append("候选质量审计的原始响应哈希不一致")
                if candidate_audit.get("prompt_sha256") != (
                    provenance.get("prompt_sha256_by_chapter") or {}
                ).get(str(chapter_id)):
                    proof_failures.append("候选质量审计的提示词哈希不一致")
                if candidate_audit.get("base_prompt_sha256") != (
                    provenance.get("base_prompt_sha256_by_chapter") or {}
                ).get(str(chapter_id)):
                    proof_failures.append("候选基础提示哈希与正式溯源不一致")
                if candidate_audit.get("body_generator_contract_version") != BODY_GENERATOR_CONTRACT_VERSION:
                    proof_failures.append("候选提示契约版本不匹配")
        if proof_failures:
            qwen_failures[str(chapter_id)] = proof_failures

        memory_path = memory_dir / f"chapter_{chapter_id:03d}_memory.json"
        local_memory_failures: list[str] = []
        try:
            memory = _load_json(memory_path)
            if int(memory.get("chapter") or 0) != chapter_id:
                local_memory_failures.append("章节记忆编号错误")
            if memory.get("story_id") != story_id:
                local_memory_failures.append("章节记忆story_id错误")
            if memory.get("content_hash") != content_hash(body):
                local_memory_failures.append("章节记忆正文哈希与正式正文不一致")
        except Exception as exc:  # noqa: BLE001
            local_memory_failures.append(f"章节记忆读取失败：{exc}")
        if local_memory_failures:
            memory_failures[str(chapter_id)] = local_memory_failures

    _record(
        checks,
        "all_chapters_pass_current_validator",
        passed=not chapter_failures and len(body_by_chapter) == end_chapter,
        evidence={
            "validated_chapters": len(body_by_chapter),
            "minimum_han_chars": min(han_counts.values()) if han_counts else 0,
            "maximum_han_chars": max(han_counts.values()) if han_counts else 0,
            "han_chars_by_chapter": han_counts,
        },
        failures=[
            f"第{chapter}章：{'；'.join(values)}"
            for chapter, values in chapter_failures.items()
        ],
    )
    _record(
        checks,
        "official_body_is_exact_qwen_output",
        passed=not qwen_failures and len(body_by_chapter) == end_chapter,
        evidence={"verified_chapters": end_chapter - len(qwen_failures)},
        failures=[
            f"第{chapter}章：{'；'.join(values)}"
            for chapter, values in qwen_failures.items()
        ],
    )
    _record(
        checks,
        "local_chapter_memories_match_body",
        passed=not memory_failures and len(body_by_chapter) == end_chapter,
        evidence={"verified_memories": end_chapter - len(memory_failures)},
        failures=[
            f"第{chapter}章：{'；'.join(values)}"
            for chapter, values in memory_failures.items()
        ],
    )

    pair_failures: dict[str, list[str]] = {}
    repeat_lengths: dict[str, int] = {}
    for index, event in enumerate(events[:target_cluster_count], 1):
        first_id, second_id = [int(value) for value in event["chapter_span"]]
        first = body_by_chapter.get(first_id, "")
        second = body_by_chapter.get(second_id, "")
        repeat_lengths[f"EC{index:03d}"] = SequenceMatcher(
            None, first, second, autojunk=False
        ).find_longest_match().size
        if not first or not second:
            pair_failures[f"EC{index:03d}"] = ["正文缺失"]
            continue
        _, failures, _ = _validate_candidate(
            {
                "cluster_id": event["cluster_id"],
                "chapters": [
                    {"chapter_id": first_id, "body": first},
                    {"chapter_id": second_id, "body": second},
                ],
            },
            cluster=event,
            cards=[card_map[first_id], card_map[second_id]],
        )
        if failures:
            pair_failures[event["cluster_id"]] = failures
    _record(
        checks,
        "all_target_event_clusters_pass_joint_validation",
        passed=not pair_failures,
        evidence={
            "validated_clusters": target_cluster_count - len(pair_failures),
            "maximum_longest_exact_repeat": max(repeat_lengths.values()) if repeat_lengths else 0,
            "longest_exact_repeat_by_cluster": repeat_lengths,
        },
        failures=[
            f"{cluster}：{'；'.join(values)}"
            for cluster, values in pair_failures.items()
        ],
    )

    review_failures = {
        cluster: status
        for cluster, status in sorted(review_statuses.items())
        if not status or status == "awaiting_manual_read"
    }
    _record(
        checks,
        "manual_review_status_finalized",
        passed=not review_failures and len(review_statuses) == target_cluster_count,
        evidence={"quality_review_status_by_cluster": dict(sorted(review_statuses.items()))},
        failures=[f"{cluster}：{status or 'missing'}" for cluster, status in review_failures.items()],
    )

    graph_failures: list[str] = []
    graph_evidence: dict[str, Any] = {}
    try:
        _bootstrap_neo4j_env(neo4j_container)
        driver = get_neo4j_driver()
        try:
            driver.verify_connectivity()
            with driver.session() as session:
                plot_row = session.run(
                    "MATCH (p:PlotCluster {story_id:$sid}) RETURN count(p) AS n",
                    sid=story_id,
                ).single()
                graph_evidence["plot_cluster_count"] = int(plot_row["n"] if plot_row else 0)
                plot_hash_rows = session.run(
                    "MATCH (p:PlotCluster {story_id:$sid}) "
                    "RETURN p.cluster_id AS cluster_id, p.plan_sha256 AS plan_sha256",
                    sid=story_id,
                )
                graph_plan_hashes = {
                    str(row["cluster_id"]): str(row["plan_sha256"] or "")
                    for row in plot_hash_rows
                }
                rows = session.run(
                    "MATCH (c:StoryChapter {story_id:$sid}) "
                    "WHERE c.number >= 1 AND c.number <= $end_chapter "
                    "RETURN c.number AS chapter, c.content_hash AS content_hash "
                    "ORDER BY c.number",
                    sid=story_id,
                    end_chapter=end_chapter,
                )
                graph_hashes = {
                    int(row["chapter"]): str(row["content_hash"] or "") for row in rows
                }
        finally:
            driver.close()
        graph_evidence[f"story_chapter_count_1_to_{end_chapter}"] = len(graph_hashes)
        if graph_evidence["plot_cluster_count"] < len(events):
            graph_failures.append("Neo4j PlotCluster未覆盖当前权威规划前缀")
        plan_hash_mismatches = [
            str(event.get("cluster_id") or "") for event in events
            if graph_plan_hashes.get(str(event.get("cluster_id") or "")) != event_fingerprint(event)
        ]
        graph_evidence["plot_cluster_hash_mismatches"] = plan_hash_mismatches
        if plan_hash_mismatches:
            graph_failures.append("Neo4j PlotCluster不是当前最终情节族哈希")
        if sorted(graph_hashes) != list(range(1, end_chapter + 1)):
            graph_failures.append(f"Neo4j StoryChapter未完整覆盖1—{end_chapter}章")
        mismatched = [
            chapter
            for chapter in range(1, end_chapter + 1)
            if graph_hashes.get(chapter) != content_hash(body_by_chapter.get(chapter, ""))
        ]
        graph_evidence["body_hash_mismatch_chapters"] = mismatched
        if mismatched:
            graph_failures.append("Neo4j章节正文哈希不一致：" + ",".join(map(str, mismatched)))
    except Exception as exc:  # noqa: BLE001
        graph_failures.append(f"Neo4j审计失败：{exc}")
    _record(
        checks,
        "neo4j_planning_and_story_memory_in_sync",
        passed=not graph_failures,
        evidence=graph_evidence,
        failures=graph_failures,
    )

    failed_checks = [name for name, value in checks.items() if not value["passed"]]
    return {
        "schema_version": 1,
        "scope": f"official_first_{end_chapter}_chapters",
        "story_id": story_id,
        "output_dir": str(output_dir),
        "overall_passed": not failed_checks,
        "failed_checks": failed_checks,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--style-samples", type=Path, default=DEFAULT_STYLE_SAMPLES)
    parser.add_argument("--neo4j-container", default="ai-novel-neo4j-v5")
    parser.add_argument(
        "--end-chapter", type=int, default=50,
        help="Audit an even completed prefix (for example 10, 20, or 50).",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    report_path = (
        args.report.expanduser().resolve()
        if args.report
        else output_dir / "body_generation" / f"first_{args.end_chapter}_completion_audit.json"
    )
    report = audit(
        output_dir,
        args.style_samples.expanduser().resolve(),
        args.neo4j_container,
        args.end_chapter,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "overall_passed": report["overall_passed"],
        "failed_checks": report["failed_checks"],
        "report": str(report_path),
    }, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["overall_passed"] else 1)


if __name__ == "__main__":
    main()

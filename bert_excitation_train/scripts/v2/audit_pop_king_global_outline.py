"""Audit the nine Qwen batches that assemble the 500-chapter broad outline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bert_excitation_train.scripts.neo4j_kg.planning_graph import planning_story_id
from bert_excitation_train.scripts.v2.generate_pop_king_500_qwen import (
    EXPECTED_QWEN_BATCHES,
    PLANNING_VERSION,
    VALID_GENERATION_PROVIDERS,
    VALID_OUTPUT_GENERATORS,
    _assemble_global_narrative,
    _bind_legacy_global_identities,
    _global_foreshadows_prompt,
    _global_narrative_core_prompt,
    _global_narrative_segment_prompt,
    _global_phases_prompt,
    _global_system_prompt,
    _global_threads_prompt,
    _parse_json_object,
    _validate_global_outline,
)
from bert_excitation_train.scripts.v2.pop_king_plan_compiler import canonical_sha256


GLOBAL_PARTS = (
    ("narrative_core", "GLOBAL_narrative_core.json", "GLOBAL_narrative_core_provenance.json"),
    ("narrative_s1", "GLOBAL_narrative_s1.json", "GLOBAL_narrative_s1_provenance.json"),
    ("narrative_s2", "GLOBAL_narrative_s2.json", "GLOBAL_narrative_s2_provenance.json"),
    ("narrative_s3", "GLOBAL_narrative_s3.json", "GLOBAL_narrative_s3_provenance.json"),
    ("phases_a", "GLOBAL_phases_a.json", "GLOBAL_phases_a_provenance.json"),
    ("phases_b", "GLOBAL_phases_b.json", "GLOBAL_phases_b_provenance.json"),
    ("threads", "GLOBAL_threads_identity_bound.json", "GLOBAL_threads_identity_bound_provenance.json"),
    ("foreshadows_a", "GLOBAL_foreshadows_a_identity_bound.json", "GLOBAL_foreshadows_a_identity_bound_provenance.json"),
    ("foreshadows_b", "GLOBAL_foreshadows_b_identity_bound.json", "GLOBAL_foreshadows_b_identity_bound_provenance.json"),
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _accepted_attempt_record(provenance: dict[str, Any]) -> dict[str, Any] | None:
    accepted = str(provenance.get("accepted_attempt") or "").lstrip("0")
    for item in provenance.get("attempts") or []:
        if str(item.get("attempt") or "").lstrip("0") == accepted:
            return item
    return None


def _prompt_hashes(parts: dict[str, dict[str, Any]]) -> dict[str, str]:
    segments = [parts[f"narrative_s{i}"] for i in range(1, 4)]
    narrative = _assemble_global_narrative(parts["narrative_core"], segments)
    phases = {
        "life_phases": parts["phases_a"]["life_phases"] + parts["phases_b"]["life_phases"],
        "state_ledger_by_phase": (
            parts["phases_a"]["state_ledger_by_phase"]
            + parts["phases_b"]["state_ledger_by_phase"]
        ),
    }
    prompts = {
        "narrative_core": _global_narrative_core_prompt(),
        "narrative_s1": _global_narrative_segment_prompt(parts["narrative_core"], 1, []),
        "narrative_s2": _global_narrative_segment_prompt(parts["narrative_core"], 2, segments[:1]),
        "narrative_s3": _global_narrative_segment_prompt(parts["narrative_core"], 3, segments[:2]),
        "phases_a": _global_phases_prompt(narrative, 1),
        "phases_b": _global_phases_prompt(narrative, 2),
        "threads": _global_threads_prompt(narrative, phases),
        "foreshadows_a": _global_foreshadows_prompt(
            narrative, phases, parts["threads"], 1
        ),
        "foreshadows_b": _global_foreshadows_prompt(
            narrative, phases, parts["threads"], 2,
            prior_foreshadows=parts["foreshadows_a"]["foreshadow_ledger"],
        ),
    }
    system = _global_system_prompt()
    return {name: _sha_text(system + "\n" + prompt) for name, prompt in prompts.items()}


def _assembled_outline(
    parts: dict[str, dict[str, Any]], provenances: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    narrative = _assemble_global_narrative(
        parts["narrative_core"], [parts[f"narrative_s{i}"] for i in range(1, 4)]
    )
    result = {
        **narrative,
        "life_phases": parts["phases_a"]["life_phases"] + parts["phases_b"]["life_phases"],
        "state_ledger_by_phase": (
            parts["phases_a"]["state_ledger_by_phase"]
            + parts["phases_b"]["state_ledger_by_phase"]
        ),
        **parts["threads"],
        "foreshadow_ledger": (
            parts["foreshadows_a"]["foreshadow_ledger"]
            + parts["foreshadows_b"]["foreshadow_ledger"]
        ),
    }
    providers = sorted({
        str(item.get("generated_by") or "") for item in provenances.values()
        if str(item.get("generated_by") or "") in VALID_GENERATION_PROVIDERS
    })
    result["generated_by"] = providers[0] if len(providers) == 1 else "mixed_llm"
    result["generation_providers"] = providers
    result["manual_edits"] = []
    result["planning_version"] = PLANNING_VERSION
    return result


def audit(output_dir: Path) -> dict[str, Any]:
    failures: list[str] = []
    checkpoint_dir = output_dir / "qwen_batches"
    outline_path = output_dir / "global_story_outline_v5_qwen_500.json"
    manifest_path = output_dir / "qwen_generation_manifest.json"
    required = [outline_path, manifest_path]
    for _, parsed_name, provenance_name in GLOBAL_PARTS:
        required.extend((checkpoint_dir / parsed_name, checkpoint_dir / provenance_name))
    missing = [str(path.relative_to(output_dir)) for path in required if not path.is_file()]
    if missing:
        return {"passed": False, "failures": [f"缺少文件：{name}" for name in missing]}

    outline = _load(outline_path)
    manifest = _load(manifest_path)
    parts: dict[str, dict[str, Any]] = {}
    provenances: dict[str, dict[str, Any]] = {}
    for name, parsed_name, provenance_name in GLOBAL_PARTS:
        parts[name] = _load(checkpoint_dir / parsed_name)
        provenances[name] = _load(checkpoint_dir / provenance_name)

    expected_prompt_hashes = _prompt_hashes(parts)
    provenance_summary: list[dict[str, Any]] = []
    for name, parsed_name, _ in GLOBAL_PARTS:
        provenance = provenances[name]
        if provenance.get("generated_by") not in VALID_GENERATION_PROVIDERS or provenance.get("manual_edits") != []:
            failures.append(f"{name} 来源不是允许的模型提供商或存在人工内容替换")
        compiled_identity_part = (
            provenance.get("acceptance_mode") == "qwen_batch_plus_stable_identity_compiler"
        )
        expected_kind = f"{name}_identity_bound" if compiled_identity_part else name
        if provenance.get("identifier") != "GLOBAL" or provenance.get("kind") != expected_kind:
            failures.append(f"{name} provenance标识错误")
        if not compiled_identity_part and provenance.get("base_prompt_sha256") != expected_prompt_hashes[name]:
            failures.append(f"{name} 基础提示词哈希与当前代码不一致")
        audit_provenance = provenance
        source_part: dict[str, Any] | None = None
        if compiled_identity_part:
            source_path = checkpoint_dir / str(provenance.get("source_file") or "")
            source_provenance_path = checkpoint_dir / str(
                provenance.get("source_provenance_file") or ""
            )
            if not source_path.is_file() or not source_provenance_path.is_file():
                failures.append(f"{name} 身份编译声明的源文件或源provenance不存在")
            else:
                source_part = _load(source_path)
                audit_provenance = _load(source_provenance_path)
                if canonical_sha256(source_part) != provenance.get("source_sha256"):
                    failures.append(f"{name} 身份编译源哈希不一致")
                expected_compiled = _bind_legacy_global_identities(source_part)
                if expected_compiled != parts[name]:
                    failures.append(f"{name} 不是声明的稳定身份编译器确定性输出")
            if canonical_sha256(parts[name]) != provenance.get("compiled_sha256"):
                failures.append(f"{name} 身份编译结果哈希不一致")
            if provenance.get("compiler") != "legacy_names_to_canonical_character_ids_v1":
                failures.append(f"{name} 身份编译器版本不受支持")
        accepted_record = _accepted_attempt_record(audit_provenance)
        raw_path: Path | None = None
        if accepted_record is None:
            failures.append(f"{name} 找不到被接受尝试的记录")
        else:
            raw_path = checkpoint_dir / str(accepted_record.get("raw_response_file") or "")
            if not raw_path.is_file():
                failures.append(f"{name} 被接受的原始响应文件不存在")
            else:
                raw = raw_path.read_text(encoding="utf-8")
                if _sha_text(raw) != accepted_record.get("raw_response_sha256"):
                    failures.append(f"{name} 被接受原始响应的哈希不一致")
                try:
                    expected_raw_parse = source_part if compiled_identity_part else parts[name]
                    if _parse_json_object(raw) != expected_raw_parse:
                        failures.append(f"{name} 解析归档不是被接受原始响应的无损解析")
                except Exception as exc:
                    failures.append(f"{name} 被接受原始响应无法解析：{exc}")
            if accepted_record.get("validation_failures") not in (None, []):
                failures.append(f"{name} 被接受尝试仍记录校验错误")
            attempt_prompt_hash = str(accepted_record.get("prompt_sha256") or "")
            if len(attempt_prompt_hash) != 64:
                failures.append(f"{name} 被接受尝试缺少完整提示词哈希")
        provenance_summary.append({
            "part": name,
            "accepted_attempt": provenance.get("accepted_attempt"),
            "acceptance_mode": provenance.get("acceptance_mode"),
            "base_prompt_sha256": audit_provenance.get("base_prompt_sha256"),
            "accepted_prompt_sha256": (
                accepted_record.get("prompt_sha256") if accepted_record else None
            ),
            "raw_response_file": raw_path.name if raw_path else None,
            "raw_response_sha256": (
                accepted_record.get("raw_response_sha256") if accepted_record else None
            ),
        })

    expected_outline = _assembled_outline(parts, provenances)
    if outline != expected_outline:
        failures.append("最终全书粗纲不等于九个被接受Qwen批次的确定性合并结果")
    semantic_failures = _validate_global_outline(outline)
    failures.extend(f"全书粗纲语义校验：{item}" for item in semantic_failures)
    outline_sha256 = canonical_sha256(outline)
    if manifest.get("outline_sha256") != outline_sha256:
        failures.append("manifest outline_sha256与当前粗纲不一致")
    if manifest.get("story_id") != planning_story_id(outline):
        failures.append("manifest story_id与当前粗纲不一致")
    expected_manifest = {
        "planning_version": PLANNING_VERSION,
        "generated_by": expected_outline["generated_by"],
        "generation_providers": expected_outline["generation_providers"],
        "manual_edits": [],
        "global_story_outline": 1,
        "accepted_qwen_batches": 9,
        "expected_qwen_batches": EXPECTED_QWEN_BATCHES,
    }
    for key, expected in expected_manifest.items():
        if manifest.get(key) != expected:
            failures.append(f"manifest {key}应为{expected!r}，实际为{manifest.get(key)!r}")

    at_review_gate = manifest.get("stopped_after") == "global_story_outline_review_gate"
    if at_review_gate:
        for key in ("coarse_story_blocks", "macro_groups", "event_clusters", "chapter_synopses"):
            if manifest.get(key) != 0:
                failures.append(f"全局粗纲审阅门禁处manifest {key}必须为0")
        downstream = (
            "coarse_story_blocks_v5_qwen_500.json", "macro_groups_v5_qwen_500.json",
            "event_clusters_v2.json", "event_clusters_v5_qwen_500.json",
            "master_ctx_cards_v2.json", "chapter_synopses_v5_qwen_500.json",
            "body_generation", "chapters", "knowledge_graph",
        )
        present = [name for name in downstream if (output_dir / name).exists()]
        if present:
            failures.append("全局粗纲审阅门禁仍混有下游产物：" + ", ".join(present))

    archive_relative = manifest.get("archived_stale_downstream")
    archive_audit: dict[str, Any] | None = None
    if archive_relative:
        archive_dir = output_dir / str(archive_relative)
        archive_manifest_path = archive_dir / "archive_manifest.json"
        if not archive_manifest_path.is_file():
            failures.append("manifest声明的旧下游归档不存在")
        else:
            archive_audit = _load(archive_manifest_path)
            if archive_audit.get("replacement_outline_sha256") != outline_sha256:
                failures.append("旧下游归档的替代粗纲哈希不一致")
            if archive_audit.get("recoverable") is not True:
                failures.append("旧下游归档未声明可恢复")

    report = {
        "passed": not failures,
        "failures": failures,
        "output_dir": str(output_dir.resolve()),
        "outline": {
            "story_title": outline.get("story_title"),
            "outline_sha256": outline_sha256,
            "story_id": planning_story_id(outline),
            "full_story_synopsis_chars": len(str(outline.get("full_story_synopsis") or "")),
            "life_phases": len(outline.get("life_phases") or []),
            "causal_spines": len(outline.get("causal_spine") or []),
            "foreshadows": len(outline.get("foreshadow_ledger") or []),
        },
        "qwen_batches": provenance_summary,
        "manifest_stage": manifest.get("stopped_after"),
        "archive": archive_audit,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path,
        default=PROJECT_ROOT / "bert_excitation_train" / "outputs_pop_king_v6_compiled_story_first_500",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = audit(args.output_dir)
    report_path = args.report or args.output_dir / "global_outline_completion_audit.json"
    _write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Repair only EC001 with Qwen and deterministically merge the untouched EC002-EC005."""

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

from bert_excitation_train.scripts.neo4j_kg.planning_graph import retrieve_event_context
from bert_excitation_train.scripts.v2.generate_pop_king_500_qwen import (
    DEFAULT_MODEL,
    _bootstrap_local_neo4j_env,
    _call_qwen,
    _events_prompt,
    _json_text,
    _now,
    _parse_json_object,
    _sha,
    _system_prompt,
    _validate_events,
    _write_json,
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _raw_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _repair_single_trailing_wrapper(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    """Repair Qwen's observed final `}}]}` typo without changing story text."""
    stripped = str(raw or "").strip()
    if not stripped.endswith("}}]}"):
        return None, None
    repaired = stripped[:-4] + "}]}}"
    try:
        parsed = json.loads(repaired)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(parsed, dict):
        return None, None
    return parsed, "trailing_event_wrapper:}}]}->}]}}"


def run(output_dir: Path, model: str, max_attempts: int) -> dict[str, Any]:
    checkpoint_dir = output_dir / "qwen_batches"
    outline = _load(output_dir / "global_story_outline_v5_qwen_500.json")
    macros = _load(output_dir / "macro_groups_v5_qwen_500.json")
    macro = next(item for item in macros if item.get("macro_group_id") == "MG001")
    old_batch = _load(checkpoint_dir / "MG001_events.json")
    old_events = old_batch["event_clusters"]
    old_ec001 = old_events[0]
    prior_repair_files = sorted(checkpoint_dir.glob("MG001_EC001_repair_attempt_*_raw.txt"))
    if prior_repair_files:
        try:
            prior_candidate = _parse_json_object(
                prior_repair_files[-1].read_text(encoding="utf-8")
            ).get("event_cluster")
            if isinstance(prior_candidate, dict):
                old_ec001 = prior_candidate
        except Exception:
            pass
    untouched_events = old_events[1:]

    _bootstrap_local_neo4j_env()
    graph_context = retrieve_event_context(outline, macro)
    full_system_prompt = _system_prompt()
    full_user_prompt = _events_prompt(macro, {}, outline, graph_context)
    full_base_prompt_sha = _sha(full_system_prompt + "\n" + full_user_prompt)

    system_prompt = (
        "你是长篇重生小说的单事件修订器。只输出一个严格JSON对象，顶层仅有event_cluster。"
        "不解释、不输出Markdown。不得缩减字段，不得改EC002—EC005。"
    )
    base_user_prompt = (
        "只重写以下EC001，保留它的两章范围、重生爽文定位和字段结构，但彻底修复空间与因果错误。\n"
        "硬要求：\n"
        "1. 第1章是2009-05-24临终医疗房间：麦珂尚有微弱生命体征、监护仪仍工作，康拉德违规用药；"
        "他听见保险受益人与版权/母带分赃。严禁殡仪馆、冷藏室、棺材。\n"
        "2. 第1章只写2009临终、死亡和记住信息差；绝不写1969醒来后的任何动作。\n"
        "3. 第2章才在1969-11-06十一岁全国试镜后台醒来，利用上一世曾在试镜受阻的记忆，"
        "提前发现并避开既有设备/走位陷阱，取得一次可见小赢。1969物体不是2009死因。\n"
        "4. 康拉德不能进入1969，也不能在本事件中被处罚；villain_loss必须由1969在场失职者承担。\n"
        "5. timeline_start/timeline_end只写YYYY-MM-DD；今生证据必须在今生形成；两章不得串场。\n"
        "6. 保持坏人贪功、嘴硬后滑稽自曝；玛莎必须自主选择帮助麦珂，而非听儿子命令。\n"
        "7. 每章detailed_synopsis 180—350汉字、action_sequence至少4步；完整闭合JSON。\n"
        f"待修EC001：{_json_text(old_ec001)}\n"
        "严格输出：{\"event_cluster\": <修复后的完整EC001对象>}"
    )

    # Revalidate existing Qwen repair raws first. This allows a deterministic
    # trailing-wrapper syntax repair to be accepted without another API call.
    for existing_path in reversed(prior_repair_files):
        existing_raw = existing_path.read_text(encoding="utf-8")
        syntax_repair = None
        try:
            parsed = _parse_json_object(existing_raw)
        except Exception:
            parsed, syntax_repair = _repair_single_trailing_wrapper(existing_raw)
        candidate = parsed.get("event_cluster") if isinstance(parsed, dict) else None
        if not isinstance(candidate, dict):
            continue
        merged = {
            "macro_group_id": "MG001",
            "event_clusters": [candidate, *untouched_events],
            "continuity_update": old_batch.get("continuity_update") or {},
        }
        failures = _validate_events(
            merged, 1, prior_events=[], prior_state={}, prior_irreversible=set()
        )
        if failures:
            continue
        composite_raw = _json_text(merged, indent=2) + "\n"
        composite_path = checkpoint_dir / (
            f"MG001_events_composite_{full_base_prompt_sha[:10]}_raw.json"
        )
        composite_path.write_text(composite_raw, encoding="utf-8")
        old_provenance = _load(checkpoint_dir / "MG001_events_provenance.json")
        _write_json(checkpoint_dir / "MG001_events.json", merged)
        _write_json(checkpoint_dir / "MG001_events_provenance.json", {
            "generated_by": "qwen",
            "kind": "events",
            "identifier": "MG001",
            "accepted_attempt": 1,
            "acceptance_mode": "revalidated_qwen_single_event_repair_then_deterministic_merge",
            "base_prompt_sha256": full_base_prompt_sha,
            "manual_edits": [],
            "attempts": [{
                "attempt": 1,
                "created_at": _now(),
                "prompt_sha256": "single_event_repair_prompt_archived_with_raw",
                "raw_response_file": composite_path.name,
                "raw_response_sha256": _raw_sha(composite_raw),
                "validation_failures": [],
                "model": model,
                "transport": "deterministic_qwen_source_merge",
                "usage": {},
            }],
            "composition": {
                "EC001": {
                    "source": existing_path.name,
                    "source_sha256": _raw_sha(existing_raw),
                    "deterministic_json_syntax_repair": syntax_repair,
                },
                "EC002_EC005": {
                    "source": "prior MG001 Qwen batch",
                    "source_provenance_base_prompt_sha256": old_provenance.get("base_prompt_sha256"),
                    "canonical_sha256": _sha(_json_text(untouched_events)),
                },
                "merge": "event_clusters=[repaired_EC001,*unchanged_EC002_EC005]",
            },
        })
        return {
            "passed": True,
            "acceptance_mode": "revalidated_existing_qwen_raw",
            "composite_file": composite_path.name,
            "repair_raw_file": existing_path.name,
            "deterministic_json_syntax_repair": syntax_repair,
            "full_base_prompt_sha256": full_base_prompt_sha,
        }

    attempts: list[dict[str, Any]] = []
    prompt = base_user_prompt
    first_attempt = len(prior_repair_files) + 1
    for attempt in range(first_attempt, first_attempt + max_attempts):
        raw, call_meta = _call_qwen(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            model=model,
            temperature=0.58,
        )
        prompt_sha = _sha(system_prompt + "\n" + prompt)
        raw_path = checkpoint_dir / (
            f"MG001_EC001_repair_attempt_{attempt:02d}_{prompt_sha[:10]}_raw.txt"
        )
        raw_path.write_text(raw, encoding="utf-8")
        syntax_repair = None
        try:
            try:
                parsed = _parse_json_object(raw)
            except Exception:
                parsed, syntax_repair = _repair_single_trailing_wrapper(raw)
                if parsed is None:
                    raise
            candidate = parsed.get("event_cluster")
            if not isinstance(candidate, dict):
                failures = ["顶层event_cluster必须为对象"]
            else:
                merged = {
                    "macro_group_id": "MG001",
                    "event_clusters": [candidate, *untouched_events],
                    "continuity_update": old_batch.get("continuity_update") or {},
                }
                failures = _validate_events(
                    merged, 1, prior_events=[], prior_state={}, prior_irreversible=set()
                )
        except Exception as exc:
            candidate = None
            failures = [f"JSON解析失败：{exc}"]
        attempts.append({
            "attempt": attempt,
            "created_at": _now(),
            "prompt_sha256": prompt_sha,
            "raw_response_file": raw_path.name,
            "raw_response_sha256": _raw_sha(raw),
            "validation_failures": failures,
            "deterministic_json_syntax_repair": syntax_repair,
            **call_meta,
        })
        if not failures and isinstance(candidate, dict):
            merged = {
                "macro_group_id": "MG001",
                "event_clusters": [candidate, *untouched_events],
                "continuity_update": old_batch.get("continuity_update") or {},
            }
            composite_raw = _json_text(merged, indent=2) + "\n"
            composite_path = checkpoint_dir / (
                f"MG001_events_composite_{full_base_prompt_sha[:10]}_raw.json"
            )
            composite_path.write_text(composite_raw, encoding="utf-8")
            old_provenance = _load(checkpoint_dir / "MG001_events_provenance.json")
            composite_record = {
                "attempt": 1,
                "created_at": _now(),
                "prompt_sha256": prompt_sha,
                "raw_response_file": composite_path.name,
                "raw_response_sha256": _raw_sha(composite_raw),
                "validation_failures": [],
                "model": model,
                "transport": "deterministic_qwen_source_merge",
                "usage": call_meta.get("usage") or {},
            }
            _write_json(checkpoint_dir / "MG001_events.json", merged)
            _write_json(checkpoint_dir / "MG001_events_provenance.json", {
                "generated_by": "qwen",
                "kind": "events",
                "identifier": "MG001",
                "accepted_attempt": 1,
                "acceptance_mode": "qwen_single_event_repair_then_deterministic_merge",
                "base_prompt_sha256": full_base_prompt_sha,
                "manual_edits": [],
                "attempts": [composite_record],
                "composition": {
                    "EC001": {
                        "source": raw_path.name,
                        "source_sha256": _raw_sha(raw),
                        "repair_prompt_sha256": prompt_sha,
                        "deterministic_json_syntax_repair": syntax_repair,
                    },
                    "EC002_EC005": {
                        "source": "prior accepted MG001 Qwen batch",
                        "source_provenance_base_prompt_sha256": old_provenance.get("base_prompt_sha256"),
                        "canonical_sha256": _sha(_json_text(untouched_events)),
                    },
                    "merge": "event_clusters=[repaired_EC001,*unchanged_EC002_EC005]",
                },
                "repair_attempts": attempts,
            })
            return {
                "passed": True,
                "accepted_attempt": attempt,
                "composite_file": composite_path.name,
                "repair_raw_file": raw_path.name,
                "full_base_prompt_sha256": full_base_prompt_sha,
            }
        prompt = (
            base_user_prompt
            + "\n上一稿未通过，只修以下错误并重新输出完整event_cluster：\n- "
            + "\n- ".join(failures[:16])
            + "\n上一稿：\n" + raw[-18000:]
        )
    raise RuntimeError("EC001单事件Qwen修订未通过：" + " | ".join(attempts[-1]["validation_failures"][:12]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path,
        default=PROJECT_ROOT / "bert_excitation_train" / "outputs_pop_king_v6_compiled_story_first_500",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-attempts", type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir.resolve(), args.model, args.max_attempts), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

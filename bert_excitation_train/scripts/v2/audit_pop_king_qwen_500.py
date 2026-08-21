"""Strict completion audit for the Qwen-authored 500-chapter plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bert_excitation_train.scripts.neo4j_kg.common import get_neo4j_driver
from bert_excitation_train.scripts.neo4j_kg.planning_graph import planning_story_id
from bert_excitation_train.scripts.v2.generate_pop_king_body_v5 import _bootstrap_neo4j_env
from bert_excitation_train.scripts.v2.generate_pop_king_500_qwen import (
    CHAPTER_CARD_COMPILER_VERSION, EXPECTED_QWEN_BATCHES, PLANNING_VERSION,
    VALID_GENERATION_PROVIDERS, VALID_OUTPUT_GENERATORS,
)
from bert_excitation_train.scripts.v2.pop_king_plan_compiler import (
    event_fingerprint,
    plan_fingerprints,
    validate_full_plan,
)

FORBIDDEN_WORLD = (
    "北京", "上海", "中国", "东城区", "居委会", "毛主席", "文化部", "公安局",
    "人民币", "纽约", "洛杉矶", "芝加哥", "好莱坞", "FDA", "Michael Jackson",
    "迈克尔·杰克逊", "戛纳", "威尼斯", "东京", "Excel", "MTV", "索尼", "Revox", "B77", "通用电气",
    "联合国教科文组织", "国家职业安全卫生研究所", "AI还原", "人工智能还原",
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _first_year(value: Any) -> int | None:
    match = re.search(r"(?:19|20)\d{2}", str(value or ""))
    return int(match.group()) if match else None


def _expected_provenance_names() -> list[str]:
    names = [
        "GLOBAL_narrative_core_provenance.json",
        "GLOBAL_narrative_s1_provenance.json",
        "GLOBAL_narrative_s2_provenance.json",
        "GLOBAL_narrative_s3_provenance.json",
        "GLOBAL_phases_a_provenance.json",
        "GLOBAL_phases_b_provenance.json",
        "GLOBAL_threads_provenance.json",
        "GLOBAL_foreshadows_a_provenance.json",
        "GLOBAL_foreshadows_b_provenance.json",
    ]
    names.extend(f"B{i:03d}_block_backbone_provenance.json" for i in range(1, 26))
    names.extend(f"MG{i:03d}_macro_blueprint_provenance.json" for i in range(1, 51))
    for i in range(1, 51):
        prefix = f"MG{i:03d}"
        names.append(f"{prefix}_events_provenance.json")
    return names


def audit(output_dir: Path) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    required = {
        "manifest": output_dir / "qwen_generation_manifest.json",
        "global_outline": output_dir / "global_story_outline_v5_qwen_500.json",
        "events": output_dir / "event_clusters_v5_qwen_500.json",
        "events_primary": output_dir / "event_clusters_v2.json",
        "chapters": output_dir / "chapter_synopses_v5_qwen_500.json",
        "chapters_primary": output_dir / "master_ctx_cards_v2.json",
        "blocks": output_dir / "coarse_story_blocks_v5_qwen_500.json",
        "macros": output_dir / "macro_groups_v5_qwen_500.json",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        return {"passed": False, "failures": [f"缺少文件：{', '.join(missing)}"]}

    manifest = _load(required["manifest"])
    global_outline = _load(required["global_outline"])
    events = _load(required["events"])
    events_primary = _load(required["events_primary"])
    chapters = _load(required["chapters"])
    chapters_primary = _load(required["chapters_primary"])
    blocks = _load(required["blocks"])
    macros = _load(required["macros"])
    style_samples_path = PROJECT_ROOT / "bert_excitation_train" / "data" / "pop_king_revenge_style_samples_v1.json"
    style_samples = _load(style_samples_path)

    expected_counts = {
        "coarse_story_blocks": (len(blocks), 25),
        "macro_groups": (len(macros), 50),
        "event_clusters": (len(events), 250),
        "chapter_synopses": (len(chapters), 500),
    }
    for label, (actual, expected) in expected_counts.items():
        if actual != expected:
            failures.append(f"{label}应为{expected}，实际为{actual}")
    if events_primary != events:
        failures.append("正文入口event_clusters_v2.json与最终情节族归档不一致")
    if chapters_primary != chapters:
        failures.append("正文入口master_ctx_cards_v2.json与最终章卡归档不一致")
    if manifest.get("planning_version") != PLANNING_VERSION:
        failures.append("manifest planning_version不匹配")
    if manifest.get("complete") is not True:
        failures.append("manifest complete不是true")
    if manifest.get("generated_by") not in VALID_OUTPUT_GENERATORS or manifest.get("manual_edits") != []:
        failures.append("manifest没有证明由允许的模型提供商生成且无人工内容替换")
    if manifest.get("expected_qwen_batches") != EXPECTED_QWEN_BATCHES:
        failures.append(f"manifest预期Qwen批次数不是{EXPECTED_QWEN_BATCHES}")
    if manifest.get("accepted_qwen_batches") != EXPECTED_QWEN_BATCHES:
        failures.append(f"manifest被接受Qwen批次数不是{EXPECTED_QWEN_BATCHES}")
    if manifest.get("chapter_cards_compiled_from_qwen_event_milestones") is not True:
        failures.append("manifest没有声明章卡由Qwen事件milestone确定性编译")
    compiler_report = validate_full_plan(events, chapters, global_outline=global_outline)
    if not compiler_report["passed"]:
        failures.extend("规划编译器：" + failure for failure in compiler_report["failures"])
    fingerprints = plan_fingerprints(
        outline=global_outline, events=events, cards=chapters, style_samples=style_samples,
    )
    if manifest.get("plan_fingerprints") != fingerprints:
        failures.append("manifest计划指纹不是当前总纲/情节族/章卡/风格样本版本")
    expected_story_id = planning_story_id(global_outline)
    if manifest.get("story_id") != expected_story_id:
        failures.append("manifest story_id不是当前总纲哈希对应的规划图scope")
    if global_outline.get("generated_by") not in VALID_OUTPUT_GENERATORS or global_outline.get("manual_edits") != []:
        failures.append("全书总纲没有证明由允许的模型提供商生成且无人工内容替换")
    if len(str(global_outline.get("full_story_synopsis") or "")) < 1800:
        failures.append("全书宽泛故事梗概不足1800字符")
    phases = global_outline.get("life_phases") or []
    if not isinstance(phases, list) or len(phases) != 10:
        failures.append("全书总纲没有恰好10个人生阶段")
    else:
        for index, phase in enumerate(phases, 1):
            if phase.get("phase_id") != f"P{index:02d}" or phase.get("chapter_span") != [index * 50 - 49, index * 50]:
                failures.append(f"全书总纲P{index:02d}阶段编号或范围错误")

    for index, block in enumerate(blocks, 1):
        bid = f"B{index:03d}"
        span = [index * 20 - 19, index * 20]
        if block.get("block_id") != bid or block.get("chapter_span") != span:
            failures.append(f"{bid}编号或20章范围错误")
        if len(str(block.get("coarse_story_summary") or "").strip()) < 280:
            failures.append(f"{bid}连续粗纲不足280字")
        groups = block.get("macro_groups")
        if not isinstance(groups, list) or len(groups) != 2:
            failures.append(f"{bid}没有恰好两个十章细纲")
        if block.get("generated_by") not in VALID_OUTPUT_GENERATORS or block.get("manual_edits") != []:
            failures.append(f"{bid}缺少允许的模型作者来源或存在人工内容替换")
        serialized = _text(block)
        for phrase in FORBIDDEN_WORLD:
            if phrase in serialized:
                failures.append(f"{bid}出现禁用现实元素“{phrase}”")
        if "奥瑞安" in serialized:
            failures.append(f"{bid}把奥瑞恩集团误写成奥瑞安")

    for index, macro in enumerate(macros, 1):
        mid = f"MG{index:03d}"
        span = [index * 10 - 9, index * 10]
        expected_block = f"B{(index - 1) // 2 + 1:03d}"
        if macro.get("macro_group_id") != mid or macro.get("chapter_span") != span:
            failures.append(f"{mid}编号或十章范围错误")
        if macro.get("story_block_id") != expected_block:
            failures.append(f"{mid}未正确归属{expected_block}")
        directions = macro.get("five_event_directions")
        if not isinstance(directions, list) or len(directions) != 5:
            failures.append(f"{mid}没有恰好五个两章事件方向")

    event_names: list[str] = []
    total_event_chars = 0
    for index, event in enumerate(events, 1):
        eid = f"EC{index:03d}"
        span = [index * 2 - 1, index * 2]
        if event.get("cluster_id") != eid:
            failures.append(f"事件{index}的cluster_id不是{eid}")
        if event.get("chapter_span") != span:
            failures.append(f"{eid}没有严格覆盖第{span[0]}—{span[1]}章")
        structures = event.get("two_chapter_structure")
        if not isinstance(structures, list) or len(structures) != 2:
            failures.append(f"{eid}不是恰好两章结构")
        elif [x.get("chapter_id") for x in structures] != span:
            failures.append(f"{eid}内部章节号与chapter_span不一致")
        required_fields = (
            "fictional_obstacle", "prev_life_tragedy", "info_gap_from_prev_life",
            "why_previous_life_failed", "preemptive_avoidance", "bait_and_evidence",
            "comic_villain_behavior", "villain_loss", "protagonist_gain",
            "relationship_change", "cluster_outcome", "next_event_hook",
        )
        for field in required_fields:
            if len(str(event.get(field) or "").strip()) < 10:
                failures.append(f"{eid}.{field}缺失或过短")
        detail_chars = sum(len(str(event.get(field) or "")) for field in required_fields) + len(_text(structures))
        total_event_chars += detail_chars
        if detail_chars < 1000:
            failures.append(f"{eid}有效细节量不足1000字符，难以指导两章正文")
        if event.get("generated_by") not in VALID_OUTPUT_GENERATORS or event.get("manual_edits") != []:
            failures.append(f"{eid}缺少允许的模型作者来源或存在人工内容替换")
        if len(event.get("rebirth_flywheel") or []) != 6:
            failures.append(f"{eid}缺少完整六步重生反击闭环")
        serialized = _text({
            "name": event.get("name"),
            "timeline_years": event.get("timeline_years"),
            "main_opponent": event.get("main_opponent"),
            "main_characters": event.get("main_characters"),
            "two_chapter_structure": structures,
            **{field: event.get(field) for field in required_fields},
        })
        for phrase in FORBIDDEN_WORLD:
            if phrase in serialized:
                failures.append(f"{eid}出现禁用现实元素“{phrase}”")
        event_names.append(str(event.get("name") or "").strip())

    chapter_titles: list[str] = []
    years: list[tuple[int, int]] = []
    total_synopsis_chars = 0
    for index, chapter in enumerate(chapters, 1):
        eid = f"EC{(index + 1) // 2:03d}"
        if chapter.get("chapter_id") != index:
            failures.append(f"第{index}项chapter_id不连续")
        if chapter.get("cluster_id") != eid:
            failures.append(f"第{index}章未映射到{eid}")
        synopsis = str(chapter.get("detailed_synopsis") or "").strip()
        total_synopsis_chars += len(synopsis)
        if len(synopsis) < 180:
            failures.append(f"第{index}章详细梗概不足180字符")
        if len(chapter.get("exact_action_sequence") or []) < 4:
            failures.append(f"第{index}章具体动作不足4步")
        if chapter.get("generated_by") not in VALID_OUTPUT_GENERATORS or chapter.get("manual_edits") != []:
            failures.append(f"第{index}章缺少允许的模型作者来源或存在人工内容替换")
        if chapter.get("compiled_by") != CHAPTER_CARD_COMPILER_VERSION:
            failures.append(f"第{index}章不是由当前确定性章卡编译器生成")
        year = _first_year(chapter.get("timeline_years"))
        if index >= 2 and year is not None:
            years.append((index, year))
        if 2 <= index <= 450 and "康拉德" in _text({
            "participants": chapter.get("participants"),
            "scene": chapter.get("scene_location"),
            "actions": chapter.get("exact_action_sequence"),
            "reaction": chapter.get("opponent_reaction"),
            "synopsis": synopsis,
        }):
            failures.append(f"第{index}章让2009年晚年医生康拉德在早期今生实体登场")
        serialized = _text({
            "chapter_title": chapter.get("chapter_title"),
            "timeline_years": chapter.get("timeline_years"),
            "scene_location": chapter.get("scene_location"),
            "participants": chapter.get("participants"),
            "opening_conflict": chapter.get("opening_conflict"),
            "exact_action_sequence": chapter.get("exact_action_sequence"),
            "info_gap_use": chapter.get("info_gap_use"),
            "opponent_reaction": chapter.get("opponent_reaction"),
            "immediate_payoff": chapter.get("immediate_payoff"),
            "state_changes": chapter.get("state_changes"),
            "ending_hook": chapter.get("ending_hook"),
            "detailed_synopsis": synopsis,
        })
        for phrase in FORBIDDEN_WORLD:
            if phrase in serialized:
                failures.append(f"第{index}章出现禁用现实元素“{phrase}”")
        chapter_titles.append(str(chapter.get("chapter_title") or "").strip())

    for (previous_chapter, previous_year), (chapter_id, year) in zip(years, years[1:]):
        if year < previous_year:
            failures.append(
                f"今生时间线倒退：第{previous_chapter}章{previous_year}年→第{chapter_id}章{year}年"
            )

    duplicate_event_names = [name for name, count in Counter(event_names).items() if name and count > 1]
    duplicate_chapter_titles = [name for name, count in Counter(chapter_titles).items() if name and count > 1]
    if duplicate_event_names:
        failures.append(f"重复事件名：{duplicate_event_names[:10]}")
    if duplicate_chapter_titles:
        warnings.append(f"重复章名：{duplicate_chapter_titles[:20]}")
    synopsis_hashes = Counter(_sha(str(chapter.get("detailed_synopsis") or "")) for chapter in chapters)
    if any(count > 1 for count in synopsis_hashes.values()):
        failures.append("存在完全重复的章节详细梗概")

    checkpoint_dir = output_dir / "qwen_batches"
    expected_provenance = _expected_provenance_names()
    manifest_provenance_names = {
        Path(str(value)).name for value in (manifest.get("provenance_files") or [])
    }
    if manifest_provenance_names != set(expected_provenance):
        failures.append(
            f"manifest provenance_files未精确覆盖{EXPECTED_QWEN_BATCHES}个正式Qwen批次"
        )
    missing_provenance: list[str] = []
    invalid_provenance: list[str] = []
    for name in expected_provenance:
        path = checkpoint_dir / name
        if not path.is_file():
            missing_provenance.append(name)
            continue
        record = _load(path)
        if (
            record.get("generated_by") not in VALID_GENERATION_PROVIDERS
            or not record.get("accepted_attempt")
            or record.get("manual_edits") != []
            or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("base_prompt_sha256") or ""))
        ):
            invalid_provenance.append(name)
    if missing_provenance:
        failures.append(f"缺少Qwen来源记录{len(missing_provenance)}份：{missing_provenance[:10]}")
    if invalid_provenance:
        failures.append(f"无效Qwen来源记录{len(invalid_provenance)}份：{invalid_provenance[:10]}")

    graph_evidence: dict[str, Any] = {}
    try:
        _bootstrap_neo4j_env("ai-novel-neo4j-v5")
        driver = get_neo4j_driver()
        try:
            driver.verify_connectivity()
            with driver.session() as session:
                rows = session.run(
                    "MATCH (e:PlotCluster {story_id:$sid}) "
                    "RETURN e.cluster_id AS cluster_id, e.plan_sha256 AS plan_sha256",
                    sid=expected_story_id,
                )
                graph_hashes = {
                    str(row["cluster_id"]): str(row["plan_sha256"] or "") for row in rows
                }
                counts = session.run(
                    """
                    OPTIONAL MATCH (t:PlanStateTransition {story_id:$sid})
                    WITH count(t) AS transitions
                    OPTIONAL MATCH (a:PlanArtifact {story_id:$sid})
                    RETURN transitions, count(a) AS artifacts
                    """,
                    sid=expected_story_id,
                ).single()
        finally:
            driver.close()
        mismatches = [
            str(event.get("cluster_id") or "") for event in events
            if graph_hashes.get(str(event.get("cluster_id") or "")) != event_fingerprint(event)
        ]
        expected_transitions = sum(len(event.get("state_transitions") or []) for event in events)
        expected_artifacts = {
            (str(created.get("timeline_scope") or ""), str(created.get("artifact_id") or ""))
            for event in events
            for milestone in (event.get("two_chapter_structure") or [])
            for created in (milestone.get("artifact_creates") or [])
            if isinstance(created, dict) and str(created.get("artifact_id") or "")
        }
        actual_transitions = int(counts["transitions"] if counts else 0)
        actual_artifacts = int(counts["artifacts"] if counts else 0)
        graph_evidence = {
            "story_id": expected_story_id,
            "plot_cluster_hashes": len(graph_hashes),
            "hash_mismatches": mismatches,
            "state_transitions": [actual_transitions, expected_transitions],
            "artifacts": [actual_artifacts, len(expected_artifacts)],
        }
        if mismatches or len(graph_hashes) != 250:
            failures.append("Neo4j PlotCluster未逐项匹配最终250个情节族哈希")
        if actual_transitions != expected_transitions:
            failures.append("Neo4j PlanStateTransition数量与最终规划不符")
        if actual_artifacts != len(expected_artifacts):
            failures.append("Neo4j PlanArtifact数量与最终规划不符")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"Neo4j最终规划审计失败：{exc}")

    report = {
        "planning_version": PLANNING_VERSION,
        "passed": not failures,
        "counts": {key: actual for key, (actual, _) in expected_counts.items()},
        "expected_qwen_batches": len(expected_provenance),
        "valid_qwen_provenance": len(expected_provenance) - len(missing_provenance) - len(invalid_provenance),
        "average_event_detail_chars": round(total_event_chars / len(events), 1) if events else 0,
        "average_chapter_synopsis_chars": round(total_synopsis_chars / len(chapters), 1) if chapters else 0,
        "compiler_evidence": compiler_report.get("evidence"),
        "plan_fingerprints": fingerprints,
        "neo4j_evidence": graph_evidence,
        "failures": failures,
        "warnings": warnings,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    report = audit(output_dir)
    report_path = Path(args.report).expanduser().resolve() if args.report else output_dir / "qwen_500_completion_audit.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()

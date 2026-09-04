"""Review and commit StoryMemory for an accepted human-authored event cluster."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bert_excitation_train.scripts.neo4j_kg.common import get_neo4j_driver
from bert_excitation_train.scripts.neo4j_kg.planning_graph import planning_story_id
from bert_excitation_train.scripts.neo4j_kg.story_memory import StoryMemoryCoordinator
from bert_excitation_train.scripts.v2 import generate_pop_king_body_v5 as bodygen


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = ROOT / "bert_excitation_train" / "outputs_pop_king_v6_compiled_story_first_500"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cluster", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--neo4j-container", default="ai-novel-neo4j-v5")
    args = parser.parse_args()

    out = args.output_dir.resolve()
    cluster_id = f"EC{args.cluster:03d}"
    events, card_map, outline = bodygen._load_inputs(out)
    event = next(item for item in events if item["cluster_id"] == cluster_id)
    chapter_ids = [int(value) for value in event["chapter_span"]]
    if chapter_ids[1] != chapter_ids[0] + 1:
        raise RuntimeError("manual memory sync requires one consecutive chapter pair")

    acceptance_path = out / "body_generation" / "quality_audits" / f"{cluster_id}_manual_acceptance.json"
    quarantine_dir = out / "body_generation" / "quarantine"
    if any(path.is_dir() for path in quarantine_dir.glob("rewrite_pending_*")) and 271 <= chapter_ids[0] <= 356:
        raise RuntimeError(f"{cluster_id}处于正文隔离期，禁止写入正式StoryMemory/Neo4j")
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    if (not acceptance.get("accepted") or not acceptance.get("authoritative")
            or not acceptance.get("deterministic_validation", {}).get("passed")
            or acceptance.get("external_semantic_critic", {}).get("status") == "not_run"):
        raise RuntimeError(f"{cluster_id} has not passed manual acceptance")

    bodygen._bootstrap_neo4j_env(args.neo4j_container)
    story_id = planning_story_id(outline)
    coordinator = StoryMemoryCoordinator(
        memory_dir=out / "knowledge_graph" / "stories" / story_id / "chapter_memory",
        llm_call=None,
        driver_factory=get_neo4j_driver,
        story_id=story_id,
    )
    memories: list[dict] = []
    rows: list[dict] = []
    failures: list[str] = []
    for chapter_id in chapter_ids:
        body = (out / "chapters" / f"chapter_{chapter_id:03d}.txt").read_text(encoding="utf-8")
        memory, violations = coordinator.review_candidate(
            chapter=chapter_id,
            content=body,
            known_names=bodygen._known_names(card_map[chapter_id]),
            forced_timeline="current",
            pending_memories=memories,
        )
        memories.append(memory)
        formatted = bodygen._format_violations(violations)
        failures.extend(f"chapter_{chapter_id}: {value}" for value in formatted)
        rows.append({
            "chapter": chapter_id,
            "characters": len(memory.get("characters") or []),
            "events": len(memory.get("events") or []),
            "state_changes": len(memory.get("state_changes") or []),
            "violations": formatted,
        })
    if failures:
        raise RuntimeError("StoryMemory continuity failed:\n" + "\n".join(failures))
    coordinator.commit_many(memories)
    print(json.dumps({"story_id": story_id, "cluster_id": cluster_id, "chapters": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

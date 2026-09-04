#!/usr/bin/env python3
"""Synchronize the v15 plan while keeping formal StoryMemory at chapter 270.

The old isolated trials accidentally committed chapter 271-356 memories to the
formal Neo4j namespace.  This migration backs them up, rebuilds StoryMemory from
the accepted chapter 1-270 ledgers, creates deterministic ledgers for the two
missing formal chapters (269-270), and then replaces the planning graph with the
manually reconstructed EC136-EC250 plan.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any
import zipfile


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bert_excitation_train.scripts.neo4j_kg.build_plot_clusters import upsert_plot_clusters
from bert_excitation_train.scripts.neo4j_kg.chapter_memory import (
    build_story_state,
    extract_chapter_memory,
    load_memory_files,
    render_story_constraints,
    save_memory_file,
)
from bert_excitation_train.scripts.neo4j_kg.common import get_neo4j_driver
from bert_excitation_train.scripts.neo4j_kg.planning_graph import planning_story_id
from bert_excitation_train.scripts.neo4j_kg.story_memory_store import replace_chapter_memory
from bert_excitation_train.scripts.v2.generate_pop_king_body_v5 import _bootstrap_neo4j_env
from bert_excitation_train.scripts.v2.pop_king_plan_compiler import event_fingerprint


OUT = ROOT / "bert_excitation_train" / "outputs_pop_king_v6_compiled_story_first_500"
EVENTS = OUT / "event_clusters_v2.json"
CARDS = OUT / "master_ctx_cards_v2.json"
OUTLINE = OUT / "global_story_outline_v5_qwen_500.json"
CHAPTERS = OUT / "chapters"
MEMORY = OUT / "knowledge_graph" / "stories"
BACKUPS = OUT / "body_generation" / "graph_backups"
QUARANTINE = OUT / "body_generation" / "quarantine" / "story_memory_after_270_pre_v15"
QUARANTINE_CHAPTERS = OUT / "body_generation" / "quarantine" / "chapters_271_500_pre_v15"

NAME_REPAIRS = {
    "维克多·斯特林": "维克多·兰斯",
    "黛安娜·陈": "黛安娜·罗文",
    "瑟琳娜·王": "瑟琳娜·凯德",
    "塞雷娜": "瑟琳娜",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temp.replace(path)


def repair(value: Any) -> Any:
    if isinstance(value, str):
        for old, new in NAME_REPAIRS.items():
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [repair(item) for item in value]
    if isinstance(value, dict):
        return {key: repair(item) for key, item in value.items()}
    return value


def chapter_number(memory: dict[str, Any]) -> int:
    return int(memory.get("chapter") or memory.get("chapter_id") or 0)


def canonical_names(events: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for event in events:
        for member in event.get("canonical_cast") or []:
            if isinstance(member, dict):
                name = str(member.get("display_name") or member.get("name") or "").strip()
                if name:
                    names.append(name)
    return list(dict.fromkeys(names))


def export_graph_backup(driver: Any, story_id: str, path: Path) -> None:
    with driver.session() as session:
        nodes = [
            {"element_id": row["element_id"], "labels": row["labels"], "properties": row["properties"]}
            for row in session.run(
                "MATCH (n) WHERE n.story_id=$sid RETURN elementId(n) AS element_id, "
                "labels(n) AS labels, properties(n) AS properties",
                sid=story_id,
            )
        ]
        relationships = [
            {
                "start": row["start"], "end": row["end"], "type": row["type"],
                "properties": row["properties"],
            }
            for row in session.run(
                "MATCH (a)-[r]->(b) WHERE a.story_id=$sid OR b.story_id=$sid "
                "RETURN elementId(a) AS start, elementId(b) AS end, type(r) AS type, "
                "properties(r) AS properties",
                sid=story_id,
            )
        ]
    dump(path, {"story_id": story_id, "nodes": nodes, "relationships": relationships})


def prepare_local_memories(story_id: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    memory_dir = MEMORY / story_id / "chapter_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    BACKUPS.mkdir(parents=True, exist_ok=True)
    zip_path = BACKUPS / "chapter_memory_pre_v15.zip"
    if not zip_path.exists():
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(memory_dir.glob("chapter_*_memory.json")):
                archive.write(path, arcname=path.name)

    accepted: dict[int, dict[str, Any]] = {}
    for path in sorted(memory_dir.glob("chapter_*_memory.json")):
        data = repair(load(path))
        number = chapter_number(data)
        if 1 <= number <= 270:
            data["story_id"] = story_id
            accepted[number] = data
            dump(path, data)
        elif number > 270:
            source = path.resolve()
            target_root = QUARANTINE.resolve()
            if ROOT.resolve() not in source.parents or ROOT.resolve() not in target_root.parents:
                raise RuntimeError("拒绝移动工作区外的StoryMemory文件")
            QUARANTINE.mkdir(parents=True, exist_ok=True)
            target = QUARANTINE / path.name
            if target.exists():
                target = QUARANTINE / f"{path.stem}_{hashlib.sha1(str(path).encode()).hexdigest()[:8]}{path.suffix}"
            shutil.move(str(path), str(target))

    known = canonical_names(events)
    for number in (269, 270):
        if number in accepted:
            continue
        prior = [accepted[key] for key in sorted(accepted) if key < number]
        state = build_story_state(prior)
        names = [str(item.get("name") or "") for item in state.get("characters") or []]
        names.extend(known)
        content = (CHAPTERS / f"chapter_{number:03d}.txt").read_text(encoding="utf-8")
        data = extract_chapter_memory(
            chapter=number,
            content=content,
            prior_context=render_story_constraints(state, number, max_chars=2600),
            known_names=list(dict.fromkeys(name for name in names if name)),
            llm_call=None,
        )
        data = repair(data)
        data["story_id"] = story_id
        save_memory_file(memory_dir, data)
        accepted[number] = data

    missing = [number for number in range(1, 271) if number not in accepted]
    if missing:
        raise RuntimeError(f"正式StoryMemory仍缺章节：{missing}")
    return [accepted[number] for number in range(1, 271)]


def quarantine_unaccepted_chapters() -> int:
    """Keep old 271-500 prose recoverable but out of the formal chapters dir."""
    moved = 0
    for path in sorted(CHAPTERS.glob("chapter_*.txt")):
        match = re.fullmatch(r"chapter_(\d+)", path.stem)
        if not match or int(match.group(1)) <= 270:
            continue
        source = path.resolve()
        target_root = QUARANTINE_CHAPTERS.resolve()
        if ROOT.resolve() not in source.parents or ROOT.resolve() not in target_root.parents:
            raise RuntimeError("拒绝移动工作区外的正文文件")
        QUARANTINE_CHAPTERS.mkdir(parents=True, exist_ok=True)
        target = QUARANTINE_CHAPTERS / path.name
        if target.exists():
            target = QUARANTINE_CHAPTERS / f"{path.stem}_{hashlib.sha1(str(path).encode()).hexdigest()[:8]}{path.suffix}"
        shutil.move(str(path), str(target))
        moved += 1
    return moved


def rebuild_graph(driver: Any, story_id: str, memories: list[dict[str, Any]]) -> None:
    with driver.session() as session:
        session.run(
            "MATCH (n) WHERE n.story_id=$sid AND "
            "(n:StoryChapter OR n:StoryEvent OR n:StoryFact OR n:RelationFact OR n:PlotThreadSignal) "
            "DETACH DELETE n",
            sid=story_id,
        ).consume()
        # Character nodes are derived from both plan and memory. Rebuilding
        # both sources removes stale trial-only names and later-state leakage.
        session.run("MATCH (c:Character {story_id:$sid}) DETACH DELETE c", sid=story_id).consume()

    upsert_plot_clusters(driver, str(EVENTS), story_id, str(OUTLINE))
    for memory in memories:
        replace_chapter_memory(driver, memory)


def verify(driver: Any, story_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    expected = {str(event["cluster_id"]): event_fingerprint(event) for event in events}
    with driver.session() as session:
        rows = session.run(
            "MATCH (pc:PlotCluster {story_id:$sid}) "
            "RETURN pc.cluster_id AS cluster_id, pc.plan_sha256 AS plan_sha256",
            sid=story_id,
        )
        actual = {str(row["cluster_id"]): str(row["plan_sha256"] or "") for row in rows}
        chapter = session.run(
            "MATCH (ch:StoryChapter {story_id:$sid}) "
            "RETURN count(ch) AS count, min(ch.number) AS min, max(ch.number) AS max, "
            "sum(CASE WHEN ch.number>270 THEN 1 ELSE 0 END) AS tail",
            sid=story_id,
        ).single().data()
        wrong_names = session.run(
            "MATCH (c:Character {story_id:$sid}) "
            "WHERE c.name IN $wrong RETURN collect(c.name) AS names",
            sid=story_id, wrong=list(NAME_REPAIRS),
        ).single()["names"]
    mismatches = sorted(key for key, value in expected.items() if actual.get(key) != value)
    return {
        "story_id": story_id,
        "plot_clusters": len(actual),
        "plan_hash_mismatches": mismatches,
        "story_chapters": chapter,
        "wrong_character_names": wrong_names,
        "passed": len(actual) == 250 and not mismatches and chapter == {
            "count": 270, "min": 1, "max": 270, "tail": 0,
        } and not wrong_names,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--neo4j-container", default="ai-novel-neo4j-v5")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    events = load(EVENTS)
    outline = load(OUTLINE)
    story_id = planning_story_id(outline)
    _bootstrap_neo4j_env(args.neo4j_container)
    driver = get_neo4j_driver()
    try:
        driver.verify_connectivity()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = BACKUPS / f"neo4j_story_scope_pre_v15_{stamp}.json"
        if args.apply:
            export_graph_backup(driver, story_id, backup)
            quarantine_unaccepted_chapters()
            memories = prepare_local_memories(story_id, events)
            rebuild_graph(driver, story_id, memories)
        report = verify(driver, story_id, events)
        report["applied"] = bool(args.apply)
        report["graph_backup"] = str(backup) if args.apply else None
        report["memory_boundary"] = 270
        dump(OUT / "body_generation" / "graph_sync_v15_report.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.apply and not report["passed"]:
            raise SystemExit(2)
    finally:
        driver.close()


if __name__ == "__main__":
    main()

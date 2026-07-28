"""Backfill or rebuild structured story memory from chapter text files."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from .bootstrap_neo4j import create_constraints_and_indexes
from .chapter_memory import build_story_state, extract_chapter_memory, load_memory_files, render_story_constraints, save_memory_file
from .common import get_neo4j_driver
from .story_memory_store import replace_chapter_memory
from .story_identity import story_id_for_clusters


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHAPTERS_DIR = PROJECT_ROOT / "outputs" / "chapters"
DEFAULT_MEMORY_DIR = PROJECT_ROOT / "outputs" / "knowledge_graph" / "chapter_memory"
DEFAULT_CLUSTERS = PROJECT_ROOT / "outputs" / "event_clusters_v2.json"


def _known_names_from_clusters(clusters: Any) -> List[str]:
    """Collect fixed people and named functional opponents for deterministic rebuilds."""
    names: List[str] = []
    cluster_items = [clusters] if isinstance(clusters, dict) else clusters
    for cluster in cluster_items if isinstance(cluster_items, list) else []:
        if not isinstance(cluster, dict):
            continue
        for member in cluster.get("canonical_cast", []) or []:
            if isinstance(member, dict) and str(member.get("name") or "").strip():
                names.append(str(member.get("name") or "").strip())
        main_opponent = str(cluster.get("main_opponent") or "").strip()
        names.extend(
            actor.strip()
            for actor in re.split(r"(?:与|和|、|及|/|,|，)", main_opponent)
            if actor.strip()
        )
    return list(dict.fromkeys(names))


def parse_chapters(spec: str) -> List[int]:
    result = set()
    for token in str(spec or "").split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            if left.strip().isdigit() and right.strip().isdigit():
                start, end = int(left), int(right)
                result.update(range(min(start, end), max(start, end) + 1))
        elif token.isdigit():
            result.add(int(token))
    return sorted(result)


def _qwen_caller() -> Optional[Callable[[str], str]]:
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return None
    import dashscope

    def _call(prompt: str) -> str:
        dashscope.api_key = api_key
        response = dashscope.Generation.call(
            model=dashscope.Generation.Models.qwen_turbo,
            messages=[{"role": "user", "content": prompt}],
            result_format="message",
            max_tokens=5000,
            temperature=0.1,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Qwen extraction failed: {response.code} {response.message}")
        return str(response.output.choices[0].message.content or "")

    return _call


def sync_story_memory(
    chapters_dir: Path,
    memory_dir: Path,
    chapters: Optional[List[int]] = None,
    use_qwen: bool = True,
    sync_neo4j: bool = True,
    story_id: str = "default",
    known_names: Iterable[str] = (),
    timeline_overrides: Optional[Dict[int, str]] = None,
) -> None:
    selected = set(chapters or [])
    chapter_files = sorted(chapters_dir.glob("chapter_*.txt"))
    llm_call = _qwen_caller() if use_qwen else None
    if use_qwen and llm_call is None:
        print("[StoryMemory] DASHSCOPE_API_KEY 未配置，使用确定性规则回填。")

    driver = None
    if sync_neo4j:
        try:
            driver = get_neo4j_driver()
            driver.verify_connectivity()
            create_constraints_and_indexes(driver)
        except Exception as exc:
            if driver is not None:
                driver.close()
            driver = None
            print(f"[StoryMemory] Neo4j 不可用，仅更新本地账本：{exc}")

    try:
        for path in chapter_files:
            stem_num = path.stem.rsplit("_", 1)[-1]
            if not stem_num.isdigit():
                continue
            chapter = int(stem_num)
            if selected and chapter not in selected:
                continue
            prior = load_memory_files(memory_dir, before_chapter=chapter)
            state = build_story_state(prior)
            chapter_known_names = [x.get("name", "") for x in state.get("characters", [])]
            chapter_known_names.extend(str(name).strip() for name in known_names if str(name).strip())
            content = path.read_text(encoding="utf-8")
            memory = extract_chapter_memory(
                chapter=chapter,
                content=content,
                prior_context=render_story_constraints(state, chapter, max_chars=2600),
                known_names=chapter_known_names,
                llm_call=llm_call,
            )
            forced_timeline = str((timeline_overrides or {}).get(chapter) or "").strip()
            if forced_timeline in {"current", "previous_life", "memory", "dream"}:
                memory["narrative_timeline"] = forced_timeline
                for key in ("events", "state_changes", "relationships", "facts", "event_preconditions"):
                    for item in memory.get(key, []) or []:
                        if isinstance(item, dict):
                            item["timeline"] = forced_timeline
            memory["story_id"] = story_id
            save_memory_file(memory_dir, memory)
            if driver is not None:
                replace_chapter_memory(driver, memory)
            print(
                f"[StoryMemory] 第{chapter}章：人物{len(memory['characters'])}，"
                f"事件{len(memory['events'])}，状态变化{len(memory['state_changes'])}，"
                f"关系{len(memory['relationships'])}，剧情线{len(memory['plot_threads'])}"
            )
    finally:
        if driver is not None:
            driver.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill structured story memory and its Neo4j projection.")
    parser.add_argument("--chapters-dir", type=Path, default=DEFAULT_CHAPTERS_DIR)
    parser.add_argument("--memory-dir", type=Path, default=DEFAULT_MEMORY_DIR)
    parser.add_argument("--clusters-config", type=Path, default=DEFAULT_CLUSTERS)
    parser.add_argument("--story-id", default="", help="Override story namespace; defaults to a hash of clusters config.")
    parser.add_argument("--chapters", default="", help="e.g. 1-5,8")
    parser.add_argument("--heuristic-only", action="store_true")
    parser.add_argument("--skip-neo4j", action="store_true")
    args = parser.parse_args()
    story_id = args.story_id.strip() or story_id_for_clusters(args.clusters_config)
    canonical_names: List[str] = []
    timeline_overrides: Dict[int, str] = {}
    try:
        clusters = json.loads(args.clusters_config.read_text(encoding="utf-8"))
        canonical_names = _known_names_from_clusters(clusters)
    except (OSError, ValueError, json.JSONDecodeError):
        canonical_names = []
    cards_path = args.clusters_config.parent / "master_ctx_cards_v2.json"
    try:
        cards = json.loads(cards_path.read_text(encoding="utf-8"))
        if isinstance(cards, dict):
            cards = [cards]
        for card in cards if isinstance(cards, list) else []:
            if not isinstance(card, dict):
                continue
            chapter = int(card.get("chapter_id") or 0)
            role = str(card.get("chapter_role_v2") or "").strip()
            if chapter > 0 and role == "prev_life_death_only":
                timeline_overrides[chapter] = "previous_life"
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        timeline_overrides = {}
    memory_dir = args.memory_dir
    if memory_dir == DEFAULT_MEMORY_DIR:
        memory_dir = PROJECT_ROOT / "outputs" / "knowledge_graph" / "stories" / story_id / "chapter_memory"
    sync_story_memory(
        chapters_dir=args.chapters_dir,
        memory_dir=memory_dir,
        chapters=parse_chapters(args.chapters) if args.chapters else None,
        use_qwen=not args.heuristic_only,
        sync_neo4j=not args.skip_neo4j,
        story_id=story_id,
        known_names=canonical_names,
        timeline_overrides=timeline_overrides,
    )


if __name__ == "__main__":
    main()

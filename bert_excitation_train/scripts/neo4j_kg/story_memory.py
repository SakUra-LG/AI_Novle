"""Generation-facing story-memory coordinator.

It keeps a durable JSON ledger, optionally projects it into Neo4j, and performs
hard transition checks before a chapter is accepted.
"""
from __future__ import annotations

from pathlib import Path
import json
import os
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .chapter_memory import (
    ContinuityViolation,
    build_story_state,
    content_hash,
    extract_chapter_memory,
    load_memory_files,
    render_story_constraints,
    save_memory_file,
    validate_transition,
)


class StoryMemoryCoordinator:
    def __init__(
        self,
        memory_dir: Path,
        llm_call: Optional[Callable[[str], str]] = None,
        driver_factory: Optional[Callable[[], Any]] = None,
        story_id: str = "default",
    ) -> None:
        self.memory_dir = Path(memory_dir)
        self.llm_call = llm_call
        self.driver_factory = driver_factory
        self.story_id = str(story_id or "default")
        trace_value = os.getenv("STORY_MEMORY_TRACE_FILE", "").strip()
        self.trace_path = Path(trace_value) if trace_value else None

    def _trace(self, event: str, **payload: Any) -> None:
        if self.trace_path is None:
            return
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        row = {"event": event, "story_id": self.story_id, **payload}
        with self.trace_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def _scope(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        memory["story_id"] = self.story_id
        return memory

    def memories_before(self, chapter: int) -> List[Dict[str, Any]]:
        return load_memory_files(self.memory_dir, before_chapter=chapter)

    def state_before(self, chapter: int) -> Dict[str, Any]:
        return build_story_state(self.memories_before(chapter))

    def context_for_chapter(self, chapter: int, max_chars: int = 2400) -> str:
        context = render_story_constraints(self.state_before(chapter), chapter, max_chars=max_chars)
        self._trace("ledger_context", chapter=int(chapter), context=context)
        return context

    def ensure_backfilled(self, chapters_dir: Path, before_chapter: int) -> int:
        """Backfill missing or stale ledgers before resuming a later chapter."""
        existing = {int(x.get("chapter", 0)): x for x in load_memory_files(self.memory_dir)}
        count = 0
        for path in sorted(Path(chapters_dir).glob("chapter_*.txt")):
            suffix = path.stem.rsplit("_", 1)[-1]
            if not suffix.isdigit():
                continue
            chapter = int(suffix)
            if chapter >= int(before_chapter):
                continue
            text = path.read_text(encoding="utf-8")
            if existing.get(chapter, {}).get("content_hash") == content_hash(text):
                continue
            state = self.state_before(chapter)
            memory = extract_chapter_memory(
                chapter=chapter,
                content=text,
                prior_context=render_story_constraints(state, chapter, max_chars=2600),
                known_names=[x.get("name", "") for x in state.get("characters", [])],
                llm_call=self.llm_call,
            )
            self.commit(self._scope(memory))
            count += 1
        return count

    def review_candidate(
        self,
        chapter: int,
        content: str,
        known_names: Iterable[str] = (),
        forced_timeline: str = "",
    ) -> Tuple[Dict[str, Any], List[ContinuityViolation]]:
        state = self.state_before(chapter)
        merged_names = [x.get("name", "") for x in state.get("characters", [])]
        merged_names.extend(str(x).strip() for x in known_names if str(x).strip())
        memory = extract_chapter_memory(
            chapter=chapter,
            content=content,
            prior_context=render_story_constraints(state, chapter, max_chars=2600),
            known_names=merged_names,
            llm_call=self.llm_call,
        )
        if forced_timeline in {"current", "previous_life", "memory", "dream"}:
            memory["narrative_timeline"] = forced_timeline
            for key in ("events", "state_changes", "relationships", "facts", "event_preconditions"):
                for item in memory.get(key, []) or []:
                    if isinstance(item, dict):
                        item["timeline"] = forced_timeline
            if forced_timeline != "current":
                for item in memory.get("continuity_claims", []) or []:
                    if isinstance(item, dict):
                        item["temporal_relation"] = "historical"
        memory = self._scope(memory)
        violations = validate_transition(state, memory)
        if memory.get("extraction_status") not in {"llm_complete", "heuristic_complete"}:
            violations.insert(0, ContinuityViolation(
                code="EXTRACTION_INCOMPLETE",
                message=f"第{chapter}章结构化记忆抽取不完整，禁止在事实、事件和状态缺失时入图。",
                evidence=str(memory.get("summary") or "")[:240],
            ))
        self._trace(
            "candidate_review",
            chapter=int(chapter),
            summary=memory.get("summary", ""),
            counts={key: len(memory.get(key) or []) for key in (
                "characters", "events", "state_changes", "relationships", "facts", "plot_threads"
            )},
            violations=[v.to_dict() for v in violations],
            memory=memory,
        )
        return memory, violations

    def commit(self, memory: Dict[str, Any]) -> Path:
        memory = self._scope(memory)
        path = save_memory_file(self.memory_dir, memory)
        self._trace("commit", chapter=int(memory.get("chapter", 0)), path=str(path))
        if self.driver_factory is not None:
            try:
                from .story_memory_store import replace_chapter_memory

                with self.driver_factory() as driver:
                    replace_chapter_memory(driver, memory)
            except Exception as exc:
                # The durable ledger is already committed and can rebuild Neo4j later.
                print(f"[StoryMemory] Neo4j projection skipped: {exc}")
        return path

    def review_and_commit(self, chapter: int, content: str) -> Tuple[Dict[str, Any], List[ContinuityViolation]]:
        memory, violations = self.review_candidate(chapter, content)
        if not any(v.severity == "hard" for v in violations):
            self.commit(memory)
        return memory, violations

    def snapshot(self, chapters: Iterable[int]) -> Dict[int, Optional[Dict[str, Any]]]:
        result: Dict[int, Optional[Dict[str, Any]]] = {}
        for chapter in chapters:
            path = self.memory_dir / f"chapter_{int(chapter):03d}_memory.json"
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
                result[int(chapter)] = obj if isinstance(obj, dict) else None
            except (OSError, json.JSONDecodeError):
                result[int(chapter)] = None
        return result

    def restore(self, snapshot: Dict[int, Optional[Dict[str, Any]]]) -> None:
        missing: List[int] = []
        for chapter, memory in snapshot.items():
            path = self.memory_dir / f"chapter_{int(chapter):03d}_memory.json"
            if memory is None:
                path.unlink(missing_ok=True)
                missing.append(int(chapter))
                continue
            save_memory_file(self.memory_dir, memory)
            if self.driver_factory is not None:
                from .story_memory_store import replace_chapter_memory
                with self.driver_factory() as driver:
                    replace_chapter_memory(driver, memory)
        if missing and self.driver_factory is not None:
            from .story_memory_store import delete_chapter_memory_projection
            with self.driver_factory() as driver:
                delete_chapter_memory_projection(driver, missing, story_id=self.story_id)

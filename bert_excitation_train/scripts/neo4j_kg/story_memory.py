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
    MEMORY_SCHEMA_VERSION,
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
        try:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            row = {"event": event, "story_id": self.story_id, **payload}
            with self.trace_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        except Exception:
            # Diagnostics must never change commit/rollback semantics.
            return

    def _scope(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        memory["story_id"] = self.story_id
        return memory

    def memories_before(self, chapter: int) -> List[Dict[str, Any]]:
        return load_memory_files(
            self.memory_dir,
            before_chapter=chapter,
            strict=True,
        )

    def state_before(
        self,
        chapter: int,
        pending_memories: Iterable[Dict[str, Any]] = (),
    ) -> Dict[str, Any]:
        memories_by_chapter = {
            int(memory.get("chapter", 0)): memory
            for memory in self.memories_before(chapter)
            if int(memory.get("chapter", 0)) > 0
        }
        for memory in pending_memories:
            if not isinstance(memory, dict):
                continue
            pending_chapter = int(memory.get("chapter", 0) or 0)
            if 0 < pending_chapter < int(chapter):
                memories_by_chapter[pending_chapter] = self._scope(dict(memory))
        return build_story_state(
            memories_by_chapter[key]
            for key in sorted(memories_by_chapter)
        )

    def context_for_chapter(
        self,
        chapter: int,
        max_chars: int = 2400,
        pending_memories: Iterable[Dict[str, Any]] = (),
    ) -> str:
        context = render_story_constraints(
            self.state_before(chapter, pending_memories),
            chapter,
            max_chars=max_chars,
        )
        self._trace("ledger_context", chapter=int(chapter), context=context)
        return context

    def ensure_backfilled(self, chapters_dir: Path, before_chapter: int) -> int:
        """Backfill missing/stale ledgers and deterministically upgrade schemas."""
        existing = {
            int(x.get("chapter", 0)): x
            for x in load_memory_files(self.memory_dir, strict=True)
        }
        stored_schema: Dict[int, int] = {}
        for memory_path in sorted(self.memory_dir.glob("chapter_*_memory.json")):
            try:
                raw = json.loads(memory_path.read_text(encoding="utf-8"))
                chapter = int(raw.get("chapter", 0) or 0)
                stored_schema[chapter] = int(raw.get("schema_version", 0) or 0)
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"invalid chapter memory ledger: {memory_path}"
                ) from exc
        known_names = list(dict.fromkeys(
            str(character.get("name") or "").strip()
            for memory in existing.values()
            for character in memory.get("characters", []) or []
            if str(character.get("name") or "").strip()
        ))
        prepared: List[Dict[str, Any]] = []
        for path in sorted(Path(chapters_dir).glob("chapter_*.txt")):
            suffix = path.stem.rsplit("_", 1)[-1]
            if not suffix.isdigit():
                continue
            chapter = int(suffix)
            if chapter >= int(before_chapter):
                continue
            text = path.read_text(encoding="utf-8")
            same_content = (
                existing.get(chapter, {}).get("content_hash") == content_hash(text)
            )
            schema_stale = stored_schema.get(chapter, 0) < MEMORY_SCHEMA_VERSION
            if same_content and not schema_stale:
                continue
            state = self.state_before(chapter, prepared)
            chapter_known_names = list(dict.fromkeys(
                [x.get("name", "") for x in state.get("characters", [])]
                + [
                    x.get("name", "")
                    for x in existing.get(chapter, {}).get("characters", []) or []
                ]
                + known_names
            ))
            memory = extract_chapter_memory(
                chapter=chapter,
                content=text,
                prior_context=render_story_constraints(state, chapter, max_chars=2600),
                known_names=chapter_known_names,
                # A schema-only migration must be reproducible and must not
                # reinterpret already accepted prose through a fresh LLM call.
                llm_call=None if same_content and schema_stale else self.llm_call,
            )
            prior_timeline = str(
                existing.get(chapter, {}).get("narrative_timeline") or ""
            )
            if same_content and prior_timeline in {
                "previous_life", "memory", "dream"
            }:
                memory["narrative_timeline"] = prior_timeline
                for key in (
                    "events", "state_changes", "relationships", "facts",
                    "event_preconditions",
                ):
                    for item in memory.get(key, []) or []:
                        if isinstance(item, dict):
                            item["timeline"] = prior_timeline
            prepared.append(self._scope(memory))
        if prepared:
            self.commit_many(prepared)
        return len(prepared)

    def review_candidate(
        self,
        chapter: int,
        content: str,
        known_names: Iterable[str] = (),
        forced_timeline: str = "",
        pending_memories: Iterable[Dict[str, Any]] = (),
    ) -> Tuple[Dict[str, Any], List[ContinuityViolation]]:
        state = self.state_before(chapter, pending_memories)
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
        paths = self.commit_many([memory])
        return paths[0]

    def _restore_local_snapshot(
        self,
        snapshot: Dict[int, Optional[Dict[str, Any]]],
    ) -> None:
        errors: List[str] = []
        try:
            self.memory_dir.mkdir(parents=True, exist_ok=True)
        except BaseException as exc:
            raise RuntimeError(
                f"cannot create StoryMemory directory: {self.memory_dir}"
            ) from exc
        for chapter, memory in snapshot.items():
            path = self.memory_dir / f"chapter_{int(chapter):03d}_memory.json"
            try:
                if memory is None:
                    path.unlink(missing_ok=True)
                else:
                    restored = dict(memory)
                    if int(restored.get("chapter", 0) or 0) != int(chapter):
                        raise RuntimeError(
                            "StoryMemory snapshot key/chapter mismatch"
                        )
                    snapshot_story_id = str(restored.get("story_id") or "")
                    if snapshot_story_id and snapshot_story_id != self.story_id:
                        raise RuntimeError(
                            "StoryMemory snapshot belongs to another story"
                        )
                    save_memory_file(self.memory_dir, restored)
            except BaseException as exc:
                errors.append(f"chapter {int(chapter)}: {exc}")
        if errors:
            raise RuntimeError(
                "StoryMemory local compensation incomplete: " + "; ".join(errors)
            )

    def commit_many(self, memories: Iterable[Dict[str, Any]]) -> List[Path]:
        """Commit one accepted cluster to the ledger and graph as one unit.

        JSON files are written first.  The Neo4j projection then uses one graph
        transaction, so a projection failure leaves the graph unchanged and the
        local ledger is compensated back to its exact pre-commit snapshot.
        """

        prepared: List[Dict[str, Any]] = []
        seen_chapters: set[int] = set()
        for raw_memory in memories:
            if not isinstance(raw_memory, dict):
                continue
            memory = self._scope(dict(raw_memory))
            chapter = int(memory.get("chapter", 0) or 0)
            if chapter <= 0:
                raise ValueError("chapter memory requires a positive chapter number")
            if chapter in seen_chapters:
                raise ValueError(f"duplicate chapter in StoryMemory batch: {chapter}")
            seen_chapters.add(chapter)
            prepared.append(memory)
        if not prepared:
            return []
        prepared.sort(key=lambda item: int(item.get("chapter", 0)))
        snapshot = self.snapshot(int(item["chapter"]) for item in prepared)
        paths: List[Path] = []
        try:
            for memory in prepared:
                path = save_memory_file(self.memory_dir, memory)
                paths.append(path)
            if self.driver_factory is not None:
                from .story_memory_store import replace_chapter_memories

                with self.driver_factory() as driver:
                    replace_chapter_memories(
                        driver,
                        prepared,
                        story_id=self.story_id,
                    )
        except BaseException as original_exc:
            try:
                self._restore_local_snapshot(snapshot)
            except BaseException as restore_exc:
                raise RuntimeError(
                    "StoryMemory commit failed and local compensation was incomplete: "
                    f"{restore_exc}"
                ) from original_exc
            self._trace(
                "commit_many_rollback",
                chapters=sorted(seen_chapters),
            )
            raise
        for memory, path in zip(prepared, paths):
            self._trace(
                "commit",
                chapter=int(memory.get("chapter", 0)),
                path=str(path),
            )
        self._trace("commit_many", chapters=sorted(seen_chapters))
        return paths

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
                if not isinstance(obj, dict):
                    raise RuntimeError(
                        f"cannot snapshot non-object StoryMemory ledger: {path}"
                    )
                if int(obj.get("chapter", 0) or 0) != int(chapter):
                    raise RuntimeError(
                        f"cannot snapshot mismatched StoryMemory ledger: {path}"
                    )
                result[int(chapter)] = obj
            except FileNotFoundError:
                result[int(chapter)] = None
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"cannot snapshot corrupt StoryMemory ledger: {path}"
                ) from exc
        return result

    def restore(self, snapshot: Dict[int, Optional[Dict[str, Any]]]) -> None:
        self._restore_local_snapshot(snapshot)
        if self.driver_factory is None:
            return
        restored = [
            self._scope(dict(memory))
            for memory in snapshot.values()
            if isinstance(memory, dict)
        ]
        missing = [
            int(chapter)
            for chapter, memory in snapshot.items()
            if memory is None
        ]
        from .story_memory_store import replace_chapter_memories

        with self.driver_factory() as driver:
            replace_chapter_memories(
                driver,
                restored,
                delete_chapters=missing,
                story_id=self.story_id,
            )
        self._trace(
            "restore",
            restored=sorted(int(item.get("chapter", 0)) for item in restored),
            deleted=sorted(missing),
        )

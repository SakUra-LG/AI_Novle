"""Neo4j projection for the rebuildable chapter-memory JSON ledger."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional

from neo4j import Driver

from .common import normalize_character_id
from .chapter_memory import story_state_slot


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:20]}"


def _character_id(story_id: str, name: str) -> str:
    return f"char:{story_id}:{normalize_character_id(str(name or '').strip())}"


def _delete_orphan_aggregates(tx, story_id: str) -> None:
    """Remove aggregate nodes left behind after a chapter projection is replaced."""
    tx.run(
        """
        MATCH (t:PlotThread)
        WHERE t.story_id=$story_id AND NOT EXISTS {
          MATCH (:PlotThreadSignal)-[:UPDATES_THREAD]->(t)
        }
        DETACH DELETE t
        """,
        story_id=story_id,
    )
    tx.run(
        """
        MATCH (c:Character)
        WHERE c.story_id=$story_id
          AND NOT EXISTS { MATCH (c)-[:MENTIONED_IN]->(:StoryChapter) }
          AND NOT EXISTS { MATCH (c)-[:PARTICIPATED_IN]->(:StoryEvent) }
          AND NOT EXISTS { MATCH (:StoryFact)-[:ABOUT]->(c) }
          AND NOT EXISTS { MATCH (:RelationFact)-[:FROM_CHARACTER]->(c) }
          AND NOT EXISTS { MATCH (:RelationFact)-[:TO_CHARACTER]->(c) }
        DETACH DELETE c
        """,
        story_id=story_id,
    )


def replace_chapter_memory(
    driver: Driver,
    memory: Dict[str, Any],
    *,
    _rebuild_views: bool = True,
) -> None:
    """Atomically replace every graph projection sourced from one chapter."""
    chapter = int(memory.get("chapter", 0))
    story_id = str(memory.get("story_id") or "default")
    chapter_id = f"chapter:{story_id}:{chapter}"
    if chapter <= 0:
        raise ValueError("chapter memory requires a positive chapter number")

    characters = memory.get("characters") or []
    events = memory.get("events") or []
    states = memory.get("state_changes") or []
    facts = memory.get("facts") or []
    relations = memory.get("relationships") or []
    threads = memory.get("plot_threads") or []
    content_hash = str(memory.get("content_hash") or "")

    with driver.session() as session:
        def _replace(tx) -> None:
            tx.run(
                """
                MATCH (n) WHERE n.story_id = $story_id AND n.source_chapter = $chapter
                  AND (n:StoryEvent OR n:StoryFact OR n:RelationFact OR n:PlotThreadSignal)
                DETACH DELETE n
                """,
                chapter=chapter, story_id=story_id,
            )
            tx.run(
                """
                MATCH ()-[m:MENTIONED_IN]->(ch:StoryChapter {story_id:$story_id, number:$chapter})
                DELETE m
                """,
                chapter=chapter, story_id=story_id,
            )
            tx.run(
                """
                MERGE (ch:StoryChapter {id:$chapter_id})
                SET ch.content_hash=$content_hash, ch.summary=$summary,
                    ch.story_id=$story_id, ch.number=$chapter,
                    ch.schema_version=$schema_version, ch.updatedAt=timestamp()
                """,
                chapter=chapter,
                chapter_id=chapter_id,
                story_id=story_id,
                content_hash=content_hash,
                summary=str(memory.get("summary") or ""),
                schema_version=int(memory.get("schema_version", 1)),
            )

            for item in characters:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                cid = _character_id(story_id, name)
                tx.run(
                    """
                    MERGE (c:Character {id:$id})
                    ON CREATE SET c.first_chapter=$chapter, c.createdAt=timestamp()
                    SET c.label=$name, c.name=$name, c.story_id=$story_id,
                        c.aliases=reduce(acc=coalesce(c.aliases, []), x IN $aliases |
                          CASE WHEN x IN acc THEN acc ELSE acc + x END),
                        c.last_seen_chapter=CASE WHEN c.last_seen_chapter IS NULL OR c.last_seen_chapter < $chapter
                          THEN $chapter ELSE c.last_seen_chapter END,
                        c.updatedAt=timestamp()
                    WITH c MATCH (ch:StoryChapter {story_id:$story_id, number:$chapter})
                    MERGE (c)-[m:MENTIONED_IN]->(ch)
                    SET m.mode=$mode, m.evidence=$evidence, m.source_chapter=$chapter
                    """,
                    id=cid,
                    story_id=story_id,
                    name=name,
                    aliases=[str(x).strip() for x in item.get("aliases") or [] if str(x).strip()],
                    chapter=chapter,
                    mode=str(item.get("mention_mode") or "unknown"),
                    evidence=str(item.get("evidence") or "")[:300],
                )

            for index, item in enumerate(events):
                event_id = _stable_id("story-event", story_id, chapter, index, item.get("summary"))
                tx.run(
                    """
                    CREATE (e:StoryEvent {id:$id, story_id:$story_id, source_chapter:$chapter, event_order:$event_order,
                      event_type:$event_type, summary:$summary, story_time:$story_time,
                      timeline:$timeline,
                      location:$location, outcome:$outcome, caused_by:$caused_by,
                      importance:$importance, createdAt:timestamp()})
                    WITH e MATCH (ch:StoryChapter {story_id:$story_id, number:$chapter})
                    MERGE (ch)-[:CONTAINS_EVENT]->(e)
                    """,
                    id=event_id,
                    story_id=story_id,
                    chapter=chapter,
                    # Re-number surviving normalized events contiguously so
                    # NEXT_EVENT cannot break when an invalid raw item was
                    # skipped during extraction.
                    event_order=index,
                    event_type=str(item.get("type") or "story_event"),
                    summary=str(item.get("summary") or "")[:800],
                    story_time=str(item.get("story_time") or "")[:160],
                    timeline=str(item.get("timeline") or "current"),
                    location=str(item.get("location") or "")[:200],
                    outcome=str(item.get("outcome") or "")[:600],
                    caused_by=[str(x)[:300] for x in item.get("caused_by") or []],
                    importance=float(item.get("importance", 0.65)),
                )
                for participant in item.get("participants") or []:
                    name = str(participant.get("name") or "").strip()
                    if not name:
                        continue
                    cid = _character_id(story_id, name)
                    tx.run(
                        """
                        MERGE (c:Character {id:$cid})
                        ON CREATE SET c.label=$name, c.name=$name, c.story_id=$story_id, c.createdAt=timestamp()
                        WITH c MATCH (e:StoryEvent {id:$eid})
                        MERGE (c)-[p:PARTICIPATED_IN]->(e)
                        SET p.mode=$mode, p.role=$role, p.source_chapter=$chapter
                        """,
                        cid=cid, name=name, story_id=story_id, eid=event_id, chapter=chapter,
                        mode=str(participant.get("mode") or "active"),
                        role=str(participant.get("role") or "")[:120],
                    )

            all_facts: List[Dict[str, Any]] = []
            for item in states:
                all_facts.append({
                    "subject": item.get("character"), "predicate": item.get("field"),
                    "object": item.get("new_value"), "old_value": item.get("old_value"),
                    "evidence": item.get("evidence"), "confidence": item.get("confidence", 0.75),
                    "permanent": item.get("permanent", False), "reason": item.get("reason"),
                    "timeline": item.get("timeline", "current"),
                    "state_key": story_state_slot(item),
                })
            all_facts.extend({**item, "state_key": story_state_slot(item)} for item in facts)
            for index, item in enumerate(all_facts):
                subject = str(item.get("subject") or "").strip()
                predicate = str(item.get("predicate") or "").strip().lower()
                obj = str(item.get("object") or "").strip()
                if not subject or not predicate or not obj:
                    continue
                fact_id = _stable_id("story-fact", story_id, chapter, index, subject, predicate, obj)
                tx.run(
                    """
                    CREATE (f:StoryFact {id:$id, story_id:$story_id, source_chapter:$chapter, subject:$subject,
                      predicate:$predicate, state_key:$state_key, object:$object, old_value:$old_value,
                      evidence:$evidence, reason:$reason, confidence:$confidence,
                      permanent:$permanent, timeline:$timeline, createdAt:timestamp()})
                    WITH f MATCH (ch:StoryChapter {story_id:$story_id, number:$chapter})
                    MERGE (ch)-[:ASSERTS]->(f)
                    """,
                    id=fact_id, story_id=story_id, chapter=chapter, subject=subject,
                    predicate=predicate, state_key=str(item.get("state_key") or predicate)[:180], object=obj,
                    old_value=str(item.get("old_value") or "")[:300],
                    evidence=str(item.get("evidence") or "")[:500],
                    reason=str(item.get("reason") or "")[:500],
                    confidence=float(item.get("confidence", 0.7)),
                    permanent=bool(item.get("permanent", False)),
                    timeline=str(item.get("timeline") or "current"),
                )
                tx.run(
                    """
                    MERGE (c:Character {id:$cid})
                    ON CREATE SET c.label=$subject, c.name=$subject, c.story_id=$story_id, c.createdAt=timestamp()
                    WITH c MATCH (f:StoryFact {id:$fid})
                    MERGE (f)-[:ABOUT]->(c)
                    """,
                    cid=_character_id(story_id, subject), story_id=story_id, subject=subject, fid=fact_id,
                )

            for index, item in enumerate(relations):
                subject = str(item.get("subject") or "").strip()
                obj = str(item.get("object") or "").strip()
                if not subject or not obj:
                    continue
                relation_id = _stable_id("relation-fact", story_id, chapter, index, subject, obj, item.get("type"), item.get("status"))
                tx.run(
                    """
                    MERGE (a:Character {id:$aid}) ON CREATE SET a.label=$a, a.name=$a, a.story_id=$story_id, a.createdAt=timestamp()
                    MERGE (b:Character {id:$bid}) ON CREATE SET b.label=$b, b.name=$b, b.story_id=$story_id, b.createdAt=timestamp()
                    CREATE (r:RelationFact {id:$rid, story_id:$story_id, source_chapter:$chapter, relation_type:$type,
                      status:$status, timeline:$timeline, change:$change, evidence:$evidence,
                      confidence:$confidence, createdAt:timestamp()})
                    MERGE (r)-[:FROM_CHARACTER]->(a)
                    MERGE (r)-[:TO_CHARACTER]->(b)
                    """,
                    aid=_character_id(story_id, subject), a=subject, bid=_character_id(story_id, obj), b=obj,
                    story_id=story_id,
                    rid=relation_id, chapter=chapter, type=str(item.get("type") or "related"),
                    status=str(item.get("status") or "established"),
                    timeline=str(item.get("timeline") or "current"),
                    change=str(item.get("change") or "")[:300], evidence=str(item.get("evidence") or "")[:500],
                    confidence=float(item.get("confidence", 0.7)),
                )

            for index, item in enumerate(threads):
                title = str(item.get("title") or "").strip()
                if not title:
                    continue
                signal_id = _stable_id("thread-signal", story_id, chapter, index, title, item.get("status"))
                thread_id = _stable_id("plot-thread", story_id, title.casefold())
                tx.run(
                    """
                    MERGE (t:PlotThread {id:$tid}) ON CREATE SET t.title=$title, t.story_id=$story_id, t.createdAt=timestamp()
                    SET t.title=$title, t.story_id=$story_id, t.updatedAt=timestamp()
                    CREATE (s:PlotThreadSignal {id:$sid, story_id:$story_id, source_chapter:$chapter, status:$status,
                      summary:$summary, evidence:$evidence, createdAt:timestamp()})
                    MERGE (s)-[:UPDATES_THREAD]->(t)
                    """,
                    tid=thread_id, title=title, sid=signal_id, story_id=story_id, chapter=chapter,
                    status=str(item.get("status") or "open"), summary=str(item.get("summary") or "")[:600],
                    evidence=str(item.get("evidence") or "")[:500],
                )

            if _rebuild_views:
                _delete_orphan_aggregates(tx, story_id)
                _rebuild_current_character_views(tx, story_id)
                _rebuild_character_chapter_bounds(tx, story_id)
                _rebuild_current_relationship_views(tx, story_id)
                _rebuild_current_thread_views(tx, story_id)
                _rebuild_temporal_edges(tx, story_id)

        session.execute_write(_replace)


class _BoundTransactionSession:
    """Small adapter that lets the single-chapter writer reuse one outer tx."""

    def __init__(self, transaction: Any) -> None:
        self.transaction = transaction

    def __enter__(self) -> "_BoundTransactionSession":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        return False

    def execute_write(self, callback: Any) -> Any:
        return callback(self.transaction)


class _BoundTransactionDriver:
    def __init__(self, transaction: Any) -> None:
        self.transaction = transaction

    def session(self) -> _BoundTransactionSession:
        return _BoundTransactionSession(self.transaction)


def _delete_chapter_memory_projection_tx(
    tx: Any,
    chapters: Iterable[int],
    *,
    story_id: str,
) -> None:
    chapter_numbers = sorted({
        int(chapter)
        for chapter in chapters
        if int(chapter) > 0
    })
    if not chapter_numbers:
        return
    tx.run(
        """
        MATCH (n) WHERE n.story_id=$story_id AND n.source_chapter IN $chapters
          AND (n:StoryEvent OR n:StoryFact OR n:RelationFact OR n:PlotThreadSignal)
        DETACH DELETE n
        """,
        chapters=chapter_numbers,
        story_id=story_id,
    )
    tx.run(
        """
        MATCH (ch:StoryChapter)
        WHERE ch.story_id=$story_id AND ch.number IN $chapters
        DETACH DELETE ch
        """,
        chapters=chapter_numbers,
        story_id=story_id,
    )


def replace_chapter_memories(
    driver: Driver,
    memories: Iterable[Dict[str, Any]],
    *,
    delete_chapters: Iterable[int] = (),
    story_id: Optional[str] = None,
    prune_missing: bool = False,
) -> None:
    """Replace a cluster projection in one Neo4j transaction.

    Local JSON files remain the source of truth, but a cluster must never become
    half-visible to online retrieval because chapter N committed while chapter
    N+1 failed.  All chapter replacements and requested deletions therefore
    share one database transaction and rebuild derived views only once.
    """

    prepared = [dict(memory) for memory in memories if isinstance(memory, dict)]
    if prune_missing and (not story_id or not prepared):
        raise ValueError(
            "prune_missing requires an explicit story_id and a non-empty complete ledger"
        )
    story_ids = {
        str(memory.get("story_id") or story_id or "default")
        for memory in prepared
    }
    if story_id:
        story_ids.add(str(story_id))
    if len(story_ids) > 1:
        raise ValueError("one graph batch may only contain one story_id")
    scoped_story_id = next(iter(story_ids), str(story_id or "default"))
    seen_chapters: set[int] = set()
    for memory in prepared:
        chapter = int(memory.get("chapter", 0) or 0)
        if chapter <= 0:
            raise ValueError("chapter memory requires a positive chapter number")
        if chapter in seen_chapters:
            raise ValueError(f"duplicate chapter in graph batch: {chapter}")
        seen_chapters.add(chapter)
        memory["story_id"] = scoped_story_id

    requested_deletions = {
        int(chapter)
        for chapter in delete_chapters
        if int(chapter) > 0
    } - seen_chapters
    if not prepared and not requested_deletions and not prune_missing:
        return

    with driver.session() as session:
        def _replace_batch(tx: Any) -> None:
            if prune_missing:
                kept_chapters = sorted(seen_chapters)
                tx.run(
                    """
                    MATCH (n)
                    WHERE n.story_id=$story_id
                      AND (n:StoryEvent OR n:StoryFact OR
                           n:RelationFact OR n:PlotThreadSignal)
                      AND NOT coalesce(n.source_chapter, -1) IN $chapters
                    DETACH DELETE n
                    """,
                    story_id=scoped_story_id,
                    chapters=kept_chapters,
                )
                tx.run(
                    """
                    MATCH (ch:StoryChapter)
                    WHERE ch.story_id=$story_id
                      AND NOT ch.number IN $chapters
                    DETACH DELETE ch
                    """,
                    story_id=scoped_story_id,
                    chapters=kept_chapters,
                )
            if requested_deletions:
                _delete_chapter_memory_projection_tx(
                    tx,
                    requested_deletions,
                    story_id=scoped_story_id,
                )
            bound_driver = _BoundTransactionDriver(tx)
            for memory in sorted(
                prepared,
                key=lambda item: int(item.get("chapter", 0)),
            ):
                replace_chapter_memory(
                    bound_driver,  # type: ignore[arg-type]
                    memory,
                    _rebuild_views=False,
                )
            _delete_orphan_aggregates(tx, scoped_story_id)
            _rebuild_current_character_views(tx, scoped_story_id)
            _rebuild_character_chapter_bounds(tx, scoped_story_id)
            _rebuild_current_relationship_views(tx, scoped_story_id)
            _rebuild_current_thread_views(tx, scoped_story_id)
            _rebuild_temporal_edges(tx, scoped_story_id)

        session.execute_write(_replace_batch)


def _rebuild_current_character_views(tx, story_id: str) -> None:
    tx.run(
        """
        MATCH (c:Character)
        WHERE c.story_id=$story_id
        OPTIONAL MATCH (f:StoryFact)-[:ABOUT]->(c)
        WHERE f.story_id=$story_id
          AND coalesce(f.timeline, 'current') IN ['current', 'unknown']
        WITH c, f ORDER BY f.source_chapter DESC
        WITH c, collect(f) AS fs
        WITH c,
          head([x IN fs WHERE x.predicate='life_status']) AS life,
          head([x IN fs WHERE x.predicate='location']) AS loc,
          head([x IN fs WHERE x.predicate='health']) AS health,
          head([x IN fs WHERE x.predicate='occupation']) AS occupation,
          head([x IN fs WHERE x.predicate='affiliation']) AS affiliation,
          head([x IN fs WHERE x.predicate='goal']) AS goal
        SET c.life_status=coalesce(life.object, c.initial_life_status, 'unknown'),
            c.status=coalesce(life.object, c.initial_life_status, 'unknown'),
            c.status_since_chapter=life.source_chapter,
            c.current_location=loc.object, c.current_health=health.object,
            c.current_occupation=occupation.object, c.current_affiliation=affiliation.object,
            c.current_goal=goal.object, c.updatedAt=timestamp()
        """,
        story_id=story_id,
    )


def _rebuild_current_relationship_views(tx, story_id: str) -> None:
    tx.run(
        """
        MATCH (a:Character)-[r:CURRENT_RELATION]->(b:Character)
        WHERE a.story_id=$story_id AND b.story_id=$story_id
        DELETE r
        """,
        story_id=story_id,
    )
    tx.run(
        """
        MATCH (r:RelationFact)-[:FROM_CHARACTER]->(a:Character)
        MATCH (r)-[:TO_CHARACTER]->(b:Character)
        WHERE r.story_id=$story_id
          AND a.story_id=$story_id
          AND b.story_id=$story_id
          AND coalesce(r.timeline, 'current') IN ['current', 'unknown']
        WITH a, b, r ORDER BY r.source_chapter DESC
        WITH a, b, r.relation_type AS rel_type, head(collect(r)) AS latest
        MERGE (a)-[cur:CURRENT_RELATION {relation_type:rel_type}]->(b)
        SET cur.status=latest.status, cur.change=latest.change, cur.evidence=latest.evidence,
            cur.since_chapter=latest.source_chapter, cur.confidence=latest.confidence
        """,
        story_id=story_id,
    )


def _rebuild_character_chapter_bounds(tx, story_id: str) -> None:
    tx.run(
        """
        MATCH (c:Character)
        WHERE c.story_id=$story_id
        OPTIONAL MATCH (c)-[:MENTIONED_IN]->(ch:StoryChapter)
        WHERE ch.story_id=$story_id
        WITH c, min(ch.number) AS first_chapter, max(ch.number) AS last_chapter
        SET c.first_chapter=first_chapter, c.last_seen_chapter=last_chapter
        """,
        story_id=story_id,
    )


def _rebuild_current_thread_views(tx, story_id: str) -> None:
    tx.run(
        """
        MATCH (t:PlotThread)
        WHERE t.story_id=$story_id
        SET t.status='unknown', t.summary=NULL, t.last_updated_chapter=NULL
        """,
        story_id=story_id,
    )
    tx.run(
        """
        MATCH (s:PlotThreadSignal)-[:UPDATES_THREAD]->(t:PlotThread)
        WHERE s.story_id=$story_id AND t.story_id=$story_id
        WITH t, s ORDER BY s.source_chapter DESC
        WITH t, head(collect(s)) AS latest
        SET t.status=latest.status, t.summary=latest.summary,
            t.last_updated_chapter=latest.source_chapter, t.updatedAt=timestamp()
        """,
        story_id=story_id,
    )


def _rebuild_temporal_edges(tx, story_id: str) -> None:
    tx.run(
        """
        MATCH (a)-[r:NEXT_CHAPTER|NEXT_EVENT]->(b)
        WHERE a.story_id=$story_id AND b.story_id=$story_id
        DELETE r
        """,
        story_id=story_id,
    )
    tx.run(
        """
        MATCH (a:StoryChapter), (b:StoryChapter)
        WHERE a.story_id=$story_id AND b.story_id=$story_id
          AND b.number = a.number + 1
        MERGE (a)-[:NEXT_CHAPTER]->(b)
        """,
        story_id=story_id,
    )
    tx.run(
        """
        MATCH (a:StoryEvent), (b:StoryEvent)
        WHERE a.story_id=$story_id AND b.story_id=$story_id
          AND a.source_chapter = b.source_chapter AND b.event_order = a.event_order + 1
        MERGE (a)-[:NEXT_EVENT]->(b)
        """,
        story_id=story_id,
    )
    tx.run(
        """
        MATCH (a:StoryEvent), (b:StoryEvent)
        WHERE a.story_id=$story_id AND b.story_id=$story_id
          AND b.source_chapter = a.source_chapter + 1
          AND NOT EXISTS {
            MATCH (later:StoryEvent)
            WHERE later.story_id=a.story_id
              AND later.source_chapter=a.source_chapter
              AND later.event_order > a.event_order
          }
          AND NOT EXISTS {
            MATCH (earlier:StoryEvent)
            WHERE earlier.story_id=b.story_id
              AND earlier.source_chapter=b.source_chapter
              AND earlier.event_order < b.event_order
          }
        MERGE (a)-[:NEXT_EVENT]->(b)
        """,
        story_id=story_id,
    )


def delete_chapter_memory_projection(driver: Driver, chapters: List[int], story_id: str = "default") -> None:
    if not chapters:
        return
    with driver.session() as session:
        def _delete(tx) -> None:
            _delete_chapter_memory_projection_tx(
                tx,
                chapters,
                story_id=story_id,
            )
            _delete_orphan_aggregates(tx, story_id)
            _rebuild_current_character_views(tx, story_id)
            _rebuild_character_chapter_bounds(tx, story_id)
            _rebuild_current_relationship_views(tx, story_id)
            _rebuild_current_thread_views(tx, story_id)
            _rebuild_temporal_edges(tx, story_id)
        session.execute_write(_delete)

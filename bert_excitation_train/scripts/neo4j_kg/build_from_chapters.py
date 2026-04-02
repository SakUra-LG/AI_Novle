import argparse
import os
import re
from collections import Counter, defaultdict
from typing import Dict, List, Tuple, Any, Optional, Set
from neo4j import Driver
from .common import get_neo4j_driver, normalize_character_id
from .llm_extractor import SimpleHeuristicExtractor, RelationExtractionProvider
from .rules_engine import hard_constraints_pass, confidence_ok

try:
    import yaml  # type: ignore
except Exception:
    yaml = None
import json


CHAPTERS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "outputs",
    "chapters",
)


def parse_chapter_spec(spec: str) -> List[int]:
    """
    Parse chapter spec.
    Supported formats:
      - "12" / "12,13,14"
      - "12-14" (inclusive)
      - "12-14,16,18-20"
    """
    if not spec:
        return []

    out: Set[int] = set()
    for part in spec.split(","):
        p = part.strip()
        if not p:
            continue
        if "-" in p:
            a_s, b_s = p.split("-", 1)
            if a_s.strip().isdigit() and b_s.strip().isdigit():
                a = int(a_s.strip())
                b = int(b_s.strip())
                step = 1 if a <= b else -1
                for ch in range(a, b + step, step):
                    out.add(ch)
        else:
            if p.isdigit():
                out.add(int(p))

    return sorted(out)


def list_chapter_files() -> List[str]:
    if not os.path.isdir(CHAPTERS_DIR):
        return []
    files = [f for f in os.listdir(CHAPTERS_DIR) if f.startswith("chapter_") and f.endswith(".txt")]
    files.sort()
    return [os.path.join(CHAPTERS_DIR, f) for f in files]


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def extract_chapter_number(filename: str) -> int:
    m = re.search(r"chapter_(\d+)\.txt$", os.path.basename(filename))
    return int(m.group(1)) if m else -1


def split_paragraphs(text: str) -> List[str]:
    parts = re.split(r"(?:\r?\n){2,}", text.strip())
    return [p.strip() for p in parts if p.strip()]


def detect_candidate_names(texts: List[str], min_len: int = 2, max_len: int = 3, min_freq: int = 5) -> List[str]:
    """
    Simplest heuristic for CN names: contiguous CJK chars of length 2~3 with frequency threshold.
    """
    name_counter = Counter()
    pattern = re.compile(rf"([\u4e00-\u9fa5]{{{min_len},{max_len}}})")
    for t in texts:
        for m in pattern.findall(t):
            name_counter[m] += 1
    # very naive stoplist
    stop = {"我们", "他们", "她们", "自己", "这个", "那个", "今天", "明天", "时候", "之间", "突然", "只是", "因为", "所以", "然后", "但是"}
    candidates = [w for w, c in name_counter.items() if c >= min_freq and w not in stop]
    return candidates


def load_characters_config(config_path: str) -> Dict[str, Any]:
    """
    Load characters whitelist with aliases and properties.
    Supports YAML (preferred) or JSON if YAML is unavailable.
    """
    if not os.path.isfile(config_path):
        return {"characters": []}
    text = read_file(config_path)
    if yaml is not None:
        try:
            data = yaml.safe_load(text) or {}
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    # fallback json
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"characters": []}


def load_relationships_config(config_path: str) -> Dict[str, Any]:
    """
    Load semantic relationships config.
    Supports YAML or JSON. Expected shape:
    { relationships: [ {a: <id or name>, b: <id or name>, type: <str>, status: <str>, since_chapter: <int>, updated_at_chapter: <int>, evidence: <str>} ] }
    """
    if not config_path or not os.path.isfile(config_path):
        return {"relationships": []}
    text = read_file(config_path)
    if yaml is not None:
        try:
            data = yaml.safe_load(text) or {}
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"relationships": []}


def build_kg(
    driver: Driver,
    min_name_freq: int,
    config_path: str,
    candidates_out: str,
    relationships_config: str,
    auto_extract_relations: bool = False,
    relation_provider: Optional[RelationExtractionProvider] = None,
    min_promote_confidence: float = 0.75,
    target_chapters: Optional[Set[int]] = None,
) -> None:
    files = list_chapter_files()
    if not files:
        print("No chapter files found at:", CHAPTERS_DIR)
        return

    if target_chapters is not None:
        files = [p for p in files if extract_chapter_number(p) in target_chapters]
        if not files:
            print(f"No chapter files matched target chapters: {sorted(list(target_chapters))}")
            return

    all_texts = [read_file(p) for p in files]

    # Load whitelist with aliases
    cfg = load_characters_config(config_path)
    char_defs: List[Dict[str, Any]] = [c for c in (cfg.get("characters") or []) if isinstance(c, dict)]
    canonical_by_alias: Dict[str, Dict[str, Any]] = {}
    canonical_names: List[str] = []
    for c in char_defs:
        cname = str(c.get("name") or "").strip()
        if not cname:
            continue
        canonical_names.append(cname)
        aliases = [str(a).strip() for a in (c.get("aliases") or []) if str(a).strip()]
        for a in [cname] + aliases:
            canonical_by_alias[a] = c

    detected_candidates = detect_candidate_names(all_texts, min_freq=min_name_freq)
    # Only treat non-whitelisted candidates as low-priority "candidate" roles for review (do NOT upsert)
    extra_candidates = [w for w in detected_candidates if w not in canonical_by_alias]

    print(f"Whitelist characters: {len(canonical_names)}; extra detected candidates: {len(extra_candidates)}")

    # 1) Upsert Character nodes
    with driver.session() as session:
        def _upsert_character(tx, cid: str, props: Dict[str, Any]):
            tx.run(
                """
                MERGE (c:Character {id:$id})
                ON CREATE SET
                  c.label=$label,
                  c.gender=$gender,
                  c.role_type=$role_type,
                  c.protagonist_alignment=$protagonist_alignment,
                  c.faction=$faction,
                  c.identity=$identity,
                  c.age_stage=$age_stage,
                  c.personality_tags=$personality_tags,
                  c.speaking_style=$speaking_style,
                  c.core_goal=$core_goal,
                  c.status=$status,
                  c.aliases=$aliases,
                  c.first_chapter=$first_chapter,
                  c.last_seen_chapter=$last_seen_chapter,
                  c.createdAt=timestamp()
                ON MATCH SET
                  c.label=coalesce(c.label,$label),
                  c.gender=coalesce(c.gender,$gender),
                  c.role_type=coalesce(c.role_type,$role_type),
                  c.protagonist_alignment=coalesce(c.protagonist_alignment,$protagonist_alignment),
                  c.faction=coalesce(c.faction,$faction),
                  c.identity=coalesce(c.identity,$identity),
                  c.age_stage=coalesce(c.age_stage,$age_stage),
                  c.personality_tags=coalesce(c.personality_tags,$personality_tags),
                  c.speaking_style=coalesce(c.speaking_style,$speaking_style),
                  c.core_goal=coalesce(c.core_goal,$core_goal),
                  c.status=coalesce(c.status,$status),
                  c.aliases=coalesce(c.aliases,$aliases),
                  c.first_chapter=coalesce(c.first_chapter,$first_chapter),
                  c.last_seen_chapter=$last_seen_chapter,
                  c.updatedAt=timestamp()
                """,
                **props,
            )

        # Upsert whitelisted characters
        for cname in canonical_names:
            cdef = canonical_by_alias[cname]
            cid = normalize_character_id(cdef.get("id") or cname)
            props = {
                "id": cid,
                "label": cname,
                "gender": cdef.get("gender"),
                "role_type": cdef.get("role_type"),
                "protagonist_alignment": cdef.get("protagonist_alignment"),
                "faction": cdef.get("faction"),
                "identity": cdef.get("identity"),
                "age_stage": cdef.get("age_stage"),
                "personality_tags": cdef.get("personality_tags"),
                "speaking_style": cdef.get("speaking_style"),
                "core_goal": cdef.get("core_goal"),
                "status": cdef.get("status"),
                "aliases": [str(a).strip() for a in (cdef.get("aliases") or []) if str(a).strip()],
                "first_chapter": None,
                "last_seen_chapter": None,
            }
            session.execute_write(_upsert_character, cid, props)

        # Do NOT create nodes for extra candidates; they will be written to a review file later
        pass

    # 2) For each chapter: create Event, link participants, and co-occurrence INTERACTED edges
    with driver.session() as session:
        def _create_event(tx, eid: str, chapter_no: int, title: str):
            tx.run(
                """
                MERGE (e:Event {id:$id})
                ON CREATE SET
                  e.event_type='Chapter',
                  e.label=$title,
                  e.chapter=$chapter,
                  e.date_label=$date_label,
                  e.is_major=true,
                  e.createdAt=timestamp()
                ON MATCH SET
                  e.label=$title,
                  e.chapter=$chapter,
                  e.date_label=$date_label,
                  e.updatedAt=timestamp()
                """,
                id=eid,
                title=title,
                chapter=chapter_no,
                date_label=None,
            )

        def _link_participation(tx, char_id: str, event_id: str):
            tx.run(
                """
                MATCH (c:Character {id:$cid}), (e:Event {id:$eid})
                MERGE (c)-[r:PARTICIPATED_IN]->(e)
                ON CREATE SET r.count=1
                ON MATCH SET  r.count = coalesce(r.count,0) + 1
                """,
                cid=char_id,
                eid=event_id,
            )

        def _interacted(tx, a_id: str, b_id: str, chapter_no: int):
            if a_id == b_id:
                return
            tx.run(
                """
                MATCH (a:Character {id:$a}), (b:Character {id:$b})
                MERGE (a)-[r:INTERACTED_WITH]->(b)
                ON CREATE SET r.chapters = [$ch], r.count = 1, r.scope='chapter'
                ON MATCH SET  r.chapters = apoc.coll.toSet(coalesce(r.chapters, []) + [$ch]),
                              r.count = coalesce(r.count,0) + 1
                """,
                a=a_id,
                b=b_id,
                ch=chapter_no,
            )

        def _update_seen_chapter_bounds(tx, cid: str, chapter_no: int):
            tx.run(
                """
                MATCH (c:Character {id:$id})
                SET c.first_chapter = CASE
                    WHEN c.first_chapter IS NULL THEN $ch
                    ELSE coll.min([c.first_chapter, $ch])
                END,
                c.last_seen_chapter = CASE
                    WHEN c.last_seen_chapter IS NULL THEN $ch
                    ELSE coll.max([c.last_seen_chapter, $ch])
                END
                """,
                id=cid,
                ch=chapter_no,
            )

        def _upsert_state_snapshot(tx, sid: str, cid: str, chapter_no: int, event_id: str):
            tx.run(
                """
                MERGE (s:CharacterState {id:$sid})
                ON CREATE SET
                  s.chapter=$ch,
                  s.physical_state=coalesce(s.physical_state, '未知'),
                  s.mental_state=coalesce(s.mental_state, '未知'),
                  s.faction_position=coalesce(s.faction_position, '未知'),
                  s.relation_summary=coalesce(s.relation_summary, ''),
                  s.unresolved_goals=coalesce(s.unresolved_goals, []),
                  s.createdAt=timestamp()
                ON MATCH SET s.chapter=$ch, s.updatedAt=timestamp()
                WITH s
                MATCH (c:Character {id:$cid})
                MERGE (c)-[:HAS_STATE]->(s)
                WITH s
                MATCH (e:Event {id:$eid})
                MERGE (s)-[:AFTER_EVENT]->(e)
                """,
                sid=f"{cid}:ch{chapter_no}",
                cid=cid,
                ch=chapter_no,
                eid=event_id,
            )

        # Prepare alias matching: longest-first, filter pronouns/1-char
        pronouns = {"他", "她", "它", "他们", "她们", "它们", "姐姐", "哥哥", "老师", "先生", "小姐"}
        # Build mapping from canonical name to its filtered alias list
        canon_to_aliases: Dict[str, List[str]] = {}
        for cname in canonical_names:
            cdef = canonical_by_alias[cname]
            aliases = [a for a in ([cname] + [str(a).strip() for a in (cdef.get("aliases") or []) if str(a).strip()]) if len(a) >= 2 and a not in pronouns]
            aliases.sort(key=len, reverse=True)
            canon_to_aliases[cname] = aliases

        # Track candidate occurrences for review
        candidate_hits: Dict[str, List[int]] = defaultdict(list)

        for path, text in zip(files, all_texts):
            chapter_no = extract_chapter_number(path)
            event_id = f"evt:chapter:{chapter_no}"
            title = f"Chapter {chapter_no}"
            session.execute_write(_create_event, event_id, chapter_no, title)

            paragraphs = split_paragraphs(text)
            # Cache present pairs in this chapter for optional semantic extraction
            present_pairs: List[Tuple[str, str]] = []
            for para in paragraphs:
                # Find present characters by aliases (whitelist), longest-first per canon
                present: List[str] = []
                seen_canon = set()
                for cname, alias_list in canon_to_aliases.items():
                    if cname in seen_canon:
                        continue
                    for alias in alias_list:
                        if alias and alias in para:
                            present.append(cname)
                            seen_canon.add(cname)
                            break
                # Collect candidate hits for review but do NOT include in graph linking
                for n in extra_candidates:
                    if n in para:
                        if not candidate_hits[n] or candidate_hits[n][-1] != chapter_no:
                            candidate_hits[n].append(chapter_no)

                present_ids = [normalize_character_id(canonical_by_alias.get(n, {}).get("id") or n) for n in present]
                # link participation
                for cid in present_ids:
                    session.execute_write(_link_participation, cid, event_id)
                    session.execute_write(_update_seen_chapter_bounds, cid, chapter_no)
                    session.execute_write(_upsert_state_snapshot, f"{cid}:ch{chapter_no}", cid, chapter_no, event_id)
                # co-occurrence edges
                for i in range(len(present_ids)):
                    for j in range(i + 1, len(present_ids)):
                        session.execute_write(_interacted, present_ids[i], present_ids[j], chapter_no)
                        session.execute_write(_interacted, present_ids[j], present_ids[i], chapter_no)
                        # Prepare canonical label pairs for semantic layer
                        present_pairs.append((present[i], present[j]))

            # Optional: run semantic extractor to create Hypothesis proposals and promote when safe
            if auto_extract_relations:
                provider: RelationExtractionProvider = relation_provider or SimpleHeuristicExtractor()
                proposals = provider.extract_relations(chapter_no, paragraphs, present_pairs)
                def _upsert_proposal(tx, aid: str, bid: str, proposal: Dict[str, Any]):
                    tx.run(
                        """
                        MATCH (a:Character {id:$a}), (b:Character {id:$b})
                        MERGE (a)-[p:RELATION_CHANGE_PROPOSAL]->(b)
                        ON CREATE SET
                          p.type=$type, p.new_status=$new_status, p.chapter=$chapter, p.evidence=$evidence, p.confidence=$confidence, p.votes=1, p.createdAt=timestamp()
                        ON MATCH SET
                          p.type=$type,
                          p.new_status=$new_status,
                          p.chapter=$chapter,
                          p.evidence=$evidence,
                          p.confidence = coll.max([coalesce(p.confidence,0.0), $confidence]),
                          p.votes = coalesce(p.votes,0) + 1,
                          p.updatedAt=timestamp()
                        """,
                        a=aid,
                        b=bid,
                        type=str(proposal.get("current_relation_type") or "ally"),
                        new_status=str(proposal.get("new_status") or "neutral"),
                        chapter=int(proposal.get("chapter") or chapter_no),
                        evidence="\n".join([e for e in proposal.get("evidence_spans") or [] if e])[:300],
                        confidence=float(proposal.get("confidence") or 0.0),
                    )
                def _get_old_rel(tx, aid: str, bid: str) -> Dict[str, Any]:
                    rec = tx.run(
                        """
                        MATCH (a:Character {id:$a})-[r:RELATES_TO]->(b:Character {id:$b})
                        RETURN r.type AS type, r.status AS status, r.updated_at_chapter AS updated_at_chapter
                        """,
                        a=aid,
                        b=bid,
                    ).single()
                    return dict(rec) if rec else {}
                def _promote(tx, aid: str, bid: str, rtype: str, status: str, ch: int, evidence: str):
                    tx.run(
                        """
                        MATCH (a:Character {id:$a}), (b:Character {id:$b})
                        MERGE (a)-[r:RELATES_TO]->(b)
                        ON CREATE SET r.type=$type, r.status=$status, r.since_chapter=$ch, r.updated_at_chapter=$ch, r.evidence=$evidence, r.createdAt=timestamp()
                        ON MATCH SET  r.type=coalesce(r.type,$type),
                                      r.status=$status,
                                      r.updated_at_chapter=$ch,
                                      r.evidence=coalesce($evidence,r.evidence),
                                      r.updatedAt=timestamp()
                        """,
                        a=aid,
                        b=bid,
                        type=rtype,
                        status=status,
                        ch=ch,
                        evidence=evidence,
                    )
                for prop in proposals:
                    a_label, b_label = prop["pair"]
                    aid = normalize_character_id(canonical_by_alias.get(a_label, {}).get("id") or a_label)
                    bid = normalize_character_id(canonical_by_alias.get(b_label, {}).get("id") or b_label)
                    session.execute_write(_upsert_proposal, aid, bid, prop)
                    old = session.execute_read(_get_old_rel, aid, bid)
                    if confidence_ok(float(prop.get("confidence") or 0.0), min_promote_confidence) and hard_constraints_pass(old, prop):
                        session.execute_write(
                            _promote,
                            aid,
                            bid,
                            str(prop.get("current_relation_type") or "ally"),
                            str(prop.get("new_status") or "neutral"),
                            int(prop.get("chapter") or chapter_no),
                            "\n".join([e for e in prop.get("evidence_spans") or [] if e])[:300],
                        )

        # Write candidate review list
        try:
            os.makedirs(os.path.dirname(candidates_out), exist_ok=True)
            with open(candidates_out, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "candidates": [
                            {"name": n, "chapters": sorted(list(set(chs)))}
                            for n, chs in sorted(candidate_hits.items(), key=lambda x: x[0])
                        ]
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            print(f"Wrote candidate review list to: {candidates_out}")
        except Exception as e:
            print(f"Failed to write candidate review list: {e}")

    # 3) Upsert semantic relationships from config
    rel_cfg = load_relationships_config(relationships_config)
    rel_defs: List[Dict[str, Any]] = [r for r in (rel_cfg.get("relationships") or []) if isinstance(r, dict)]
    if rel_defs:
        with driver.session() as session:
            def _upsert_rel(tx, aid: str, bid: str, rtype: str, status: Any, since_ch: Any, updated_ch: Any, evidence: Any):
                tx.run(
                    """
                    MATCH (a:Character {id:$a}), (b:Character {id:$b})
                    MERGE (a)-[r:RELATES_TO]->(b)
                    ON CREATE SET
                      r.type=$type, r.status=$status, r.since_chapter=$since, r.updated_at_chapter=$updated, r.evidence=$evidence, r.createdAt=timestamp()
                    ON MATCH SET
                      r.type=coalesce(r.type,$type),
                      r.status=coalesce($status,r.status),
                      r.since_chapter=coalesce(r.since_chapter,$since),
                      r.updated_at_chapter=coalesce($updated,r.updated_at_chapter),
                      r.evidence=coalesce($evidence,r.evidence),
                      r.updatedAt=timestamp()
                    """,
                    a=aid,
                    b=bid,
                    type=rtype,
                    status=status,
                    since=since_ch,
                    updated=updated_ch,
                    evidence=evidence,
                )

            for r in rel_defs:
                a_in = str(r.get("a") or "").strip()
                b_in = str(r.get("b") or "").strip()
                if not a_in or not b_in:
                    continue
                # allow either YAML short id or name
                a_id = normalize_character_id(a_in)
                b_id = normalize_character_id(b_in)
                session.execute_write(
                    _upsert_rel,
                    a_id,
                    b_id,
                    str(r.get("type") or "关系"),
                    r.get("status"),
                    r.get("since_chapter"),
                    r.get("updated_at_chapter"),
                    r.get("evidence"),
                )

    print("KG build completed from chapters.")


def main():
    parser = argparse.ArgumentParser(description="Build a minimal Neo4j KG from chapter texts.")
    parser.add_argument("--min-name-freq", type=int, default=5, help="Min frequency to accept a 2-3 char CJK token as a character.")
    parser.add_argument("--characters-config", type=str, default=os.path.join(os.path.dirname(__file__), "characters.yaml"), help="Path to YAML/JSON characters config with aliases and roles.")
    parser.add_argument("--relationships-config", type=str, default=os.path.join(os.path.dirname(__file__), "relationships.yaml"), help="Path to YAML/JSON relationships config for RELATES_TO edges.")
    parser.add_argument("--candidates-out", type=str, default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs", "candidate_characters.json"), help="Path to write candidate characters review JSON.")
    parser.add_argument("--chapters", type=str, default="", help="Only build specified chapters, e.g. '12-14' or '12,13,14'.")
    parser.add_argument("--start", type=int, default=None, help="Start chapter (inclusive). Used with --end or alone.")
    parser.add_argument("--end", type=int, default=None, help="End chapter (inclusive). Used with --start or alone.")
    parser.add_argument("--auto-extract-relations", action="store_true", help="Enable semantic relation extraction on present character pairs per chapter.")
    parser.add_argument("--min-promote-confidence", type=float, default=0.8, help="Minimum confidence to promote a relation proposal to confirmed RELATES_TO.")
    args = parser.parse_args()

    target_chapter_set: Optional[Set[int]] = None
    if args.chapters:
        parsed = parse_chapter_spec(args.chapters)
        target_chapter_set = set(parsed) if parsed else None
    elif args.start is not None or args.end is not None:
        start = int(args.start) if args.start is not None else int(args.end)
        end = int(args.end) if args.end is not None else int(args.start)
        step = 1 if start <= end else -1
        target_chapter_set = set(range(start, end + step, step))

    driver = get_neo4j_driver()
    try:
        build_kg(
            driver,
            args.min_name_freq,
            args.characters_config,
            args.candidates_out,
            args.relationships_config,
            auto_extract_relations=bool(args.auto_extract_relations),
            relation_provider=None,
            min_promote_confidence=float(args.min_promote_confidence),
            target_chapters=target_chapter_set,
        )
    finally:
        driver.close()


if __name__ == "__main__":
    main()


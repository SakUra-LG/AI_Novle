import argparse
import os
import re
from typing import List, Optional, Set

from neo4j import Driver

from .common import get_neo4j_driver
from .story_memory_store import delete_chapter_memory_projection
from .story_identity import story_id_for_clusters

_DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "outputs",
)
OUTPUT_DIR = os.path.abspath(os.getenv("V2_OUTPUT_DIR", _DEFAULT_OUTPUT_DIR))
CHAPTERS_DIR = os.path.abspath(
    os.getenv("V2_CHAPTERS_DIR", os.path.join(OUTPUT_DIR, "chapters"))
)
CLUSTERS_CONFIG = os.path.abspath(
    os.getenv("V2_EVENT_CLUSTERS", os.path.join(OUTPUT_DIR, "event_clusters_v2.json"))
)
STORY_ID = story_id_for_clusters(CLUSTERS_CONFIG)
MEMORY_DIR = os.path.join(OUTPUT_DIR, "knowledge_graph", "stories", STORY_ID, "chapter_memory")


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


def extract_chapter_number(filename: str) -> int:
    m = re.search(r"chapter_(\d+)\.txt$", os.path.basename(filename))
    return int(m.group(1)) if m else -1


def list_chapter_files() -> List[str]:
    if not os.path.isdir(CHAPTERS_DIR):
        return []
    files = [
        f
        for f in os.listdir(CHAPTERS_DIR)
        if f.startswith("chapter_") and f.endswith(".txt")
    ]
    files.sort()
    return [os.path.join(CHAPTERS_DIR, f) for f in files]


def delete_chapters_from_neo4j(driver: Driver, chapters: List[int]) -> None:
    chapter_set = set(chapters)
    if not chapter_set:
        return

    with driver.session() as session:
        def _delete(tx) -> None:
            # 1) Remove semantic "proposal" edges tied to those chapters
            tx.run(
                """
                MATCH ()-[p:RELATION_CHANGE_PROPOSAL]->()
                WHERE p.chapter IN $chapters
                DELETE p
                """,
                chapters=chapters,
            )

            # 2) Remove confirmed relations that were updated in those chapters
            tx.run(
                """
                MATCH ()-[r:RELATES_TO]->()
                WHERE coalesce(r.updated_at_chapter, -1) IN $chapters
                DELETE r
                """,
                chapters=chapters,
            )

            # 3) Remove character state snapshots in those chapters
            tx.run(
                """
                MATCH (s:CharacterState)
                WHERE s.chapter IN $chapters
                DETACH DELETE s
                """,
                chapters=chapters,
            )

            # 4) Remove chapter events (and the participation edges)
            tx.run(
                """
                MATCH (e:Event)
                WHERE e.event_type = 'Chapter' AND e.chapter IN $chapters
                DETACH DELETE e
                """,
                chapters=chapters,
            )

            # 5) Trim interaction edges to remove deleted chapters
            tx.run(
                """
                MATCH ()-[r:INTERACTED_WITH]->()
                WHERE coalesce(r.scope, '') = 'chapter'
                SET r.chapters = [ch IN coalesce(r.chapters, []) WHERE NOT ch IN $chapters],
                    r.count = size(r.chapters)
                WITH r
                WHERE size(coalesce(r.chapters, [])) = 0
                DELETE r
                """,
                chapters=chapters,
            )

            # 6) Recompute first/last seen bounds from remaining participation in chapter events
            # 注意：min()/max() 是聚合函数，不能对列表 chs 在 SET 里直接使用；用 reduce 求列表最值。
            tx.run(
                """
                MATCH (c:Character)
                OPTIONAL MATCH (c)-[:PARTICIPATED_IN]->(e:Event)
                WHERE e.event_type = 'Chapter'
                WITH c, [ch IN collect(e.chapter) WHERE ch IS NOT NULL] AS chs
                WITH c, chs,
                  CASE WHEN size(chs) = 0 THEN NULL
                    ELSE reduce(mn = head(chs), x IN tail(chs) | CASE WHEN x < mn THEN x ELSE mn END)
                  END AS min_ch,
                  CASE WHEN size(chs) = 0 THEN NULL
                    ELSE reduce(mx = head(chs), x IN tail(chs) | CASE WHEN x > mx THEN x ELSE mx END)
                  END AS max_ch
                SET
                  c.first_chapter = min_ch,
                  c.last_seen_chapter = max_ch,
                  c.updatedAt = timestamp()
                """,
            )

        session.execute_write(lambda tx: _delete(tx))
    delete_chapter_memory_projection(driver, chapters, story_id=STORY_ID)


def main():
    parser = argparse.ArgumentParser(description="Delete a chapter range from Neo4j KG (and optionally from chapter text files).")
    parser.add_argument(
        "--chapters",
        type=str,
        default="",
        help="Chapter range/spec, e.g. '12-14' or '12,13,14'. Optional if --start/--end is set.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=None,
        help="Start chapter (inclusive). Used with --end, or alone as single chapter.",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=None,
        help="End chapter (inclusive). Used with --start, or alone as single chapter.",
    )
    parser.add_argument("--skip-neo4j-delete", action="store_true", help="Only delete chapter files; do NOT delete from Neo4j.")
    parser.add_argument("--skip-file-delete", action="store_true", help="Only delete from Neo4j; do NOT delete chapter text files.")
    parser.add_argument("--dry-run", action="store_true", help="Show what will be deleted without making changes.")
    parser.add_argument("--yes", action="store_true", help="Confirm destructive operation.")
    args = parser.parse_args()

    chapters: List[int] = []
    if args.chapters and str(args.chapters).strip():
        chapters = parse_chapter_spec(args.chapters)
    elif args.start is not None or args.end is not None:
        s0 = args.start if args.start is not None else args.end
        e0 = args.end if args.end is not None else args.start
        assert s0 is not None and e0 is not None
        start, end = int(s0), int(e0)
        step = 1 if start <= end else -1
        chapters = list(range(start, end + step, step))
    else:
        raise SystemExit("Specify --chapters <spec> or --start/--end <N>.")

    if not chapters:
        raise SystemExit("No valid chapters parsed from --chapters / --start / --end")

    # Decide files to delete first (dry-run visibility)
    all_files = list_chapter_files()
    file_targets = [p for p in all_files if extract_chapter_number(p) in set(chapters)]
    memory_targets = [
        os.path.join(MEMORY_DIR, f"chapter_{ch:03d}_memory.json")
        for ch in chapters
        if os.path.isfile(os.path.join(MEMORY_DIR, f"chapter_{ch:03d}_memory.json"))
    ]

    if args.dry_run:
        print("[Dry-run] Chapters to delete:", chapters)
        if not args.skip_neo4j_delete:
            print("[Dry-run] Neo4j operations: delete RELATION_CHANGE_PROPOSAL / RELATES_TO(updated) / CharacterState / Event / trim INTERACTED_WITH.")
        if not args.skip_file_delete:
            print("[Dry-run] Chapter files to delete:", file_targets)
            print("[Dry-run] Chapter memory sidecars to delete:", memory_targets)
        return

    if not args.yes:
        raise SystemExit("Destructive operation: please re-run with --yes (or use --dry-run).")

    driver = get_neo4j_driver()
    neo4j_ok = False
    try:
        if not args.skip_neo4j_delete:
            delete_chapters_from_neo4j(driver, chapters)
        neo4j_ok = True
    finally:
        driver.close()

    if not args.skip_file_delete:
        if not neo4j_ok and not args.skip_neo4j_delete:
            print("Neo4j deletion failed; skip file deletion for safety.")
            return
        for p in file_targets:
            try:
                os.remove(p)
                print("Deleted chapter file:", p)
            except Exception as e:  # noqa: BLE001
                print(f"Failed to delete chapter file {p}: {e}")
        for p in memory_targets:
            try:
                os.remove(p)
                print("Deleted chapter memory:", p)
            except Exception as e:  # noqa: BLE001
                print(f"Failed to delete chapter memory {p}: {e}")


if __name__ == "__main__":
    main()


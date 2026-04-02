import argparse
import os
import re
from typing import List, Optional, Set

from neo4j import Driver

from .common import get_neo4j_driver

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
            tx.run(
                """
                MATCH (c:Character)
                OPTIONAL MATCH (c)-[:PARTICIPATED_IN]->(e:Event)
                WHERE e.event_type = 'Chapter'
                WITH c, [ch IN collect(e.chapter) WHERE ch IS NOT NULL] AS chs
                SET
                  c.first_chapter = CASE WHEN size(chs) > 0 THEN min(chs) ELSE NULL END,
                  c.last_seen_chapter = CASE WHEN size(chs) > 0 THEN max(chs) ELSE NULL END,
                  c.updatedAt = timestamp()
                """,
            )

        session.execute_write(lambda tx: _delete(tx))


def main():
    parser = argparse.ArgumentParser(description="Delete a chapter range from Neo4j KG (and optionally from chapter text files).")
    parser.add_argument("--chapters", type=str, required=True, help="Chapter range/spec, e.g. '12-14' or '12,13,14'.")
    parser.add_argument("--skip-neo4j-delete", action="store_true", help="Only delete chapter files; do NOT delete from Neo4j.")
    parser.add_argument("--skip-file-delete", action="store_true", help="Only delete from Neo4j; do NOT delete chapter text files.")
    parser.add_argument("--dry-run", action="store_true", help="Show what will be deleted without making changes.")
    parser.add_argument("--yes", action="store_true", help="Confirm destructive operation.")
    args = parser.parse_args()

    chapters = parse_chapter_spec(args.chapters)
    if not chapters:
        raise SystemExit("No valid chapters parsed from --chapters")

    # Decide files to delete first (dry-run visibility)
    all_files = list_chapter_files()
    file_targets = [p for p in all_files if extract_chapter_number(p) in set(chapters)]

    if args.dry_run:
        print("[Dry-run] Chapters to delete:", chapters)
        if not args.skip_neo4j_delete:
            print("[Dry-run] Neo4j operations: delete RELATION_CHANGE_PROPOSAL / RELATES_TO(updated) / CharacterState / Event / trim INTERACTED_WITH.")
        if not args.skip_file_delete:
            print("[Dry-run] Chapter files to delete:", file_targets)
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


if __name__ == "__main__":
    main()


import argparse
from neo4j import Driver
from .common import get_neo4j_driver


CONSTRAINTS = [
    "CREATE CONSTRAINT unique_character_id IF NOT EXISTS FOR (c:Character) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT unique_org_id IF NOT EXISTS FOR (o:Organization) REQUIRE o.id IS UNIQUE",
    "CREATE CONSTRAINT unique_event_id IF NOT EXISTS FOR (e:Event) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT unique_location_id IF NOT EXISTS FOR (l:Location) REQUIRE l.id IS UNIQUE",
    "CREATE CONSTRAINT unique_faction_id IF NOT EXISTS FOR (f:Faction) REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT unique_worldrule_id IF NOT EXISTS FOR (w:WorldRule) REQUIRE w.id IS UNIQUE",
    "CREATE CONSTRAINT unique_item_id IF NOT EXISTS FOR (i:Item) REQUIRE i.id IS UNIQUE",
    "CREATE CONSTRAINT unique_charstate_id IF NOT EXISTS FOR (s:CharacterState) REQUIRE s.id IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX character_label_idx IF NOT EXISTS FOR (c:Character) ON (c.label)",
    "CREATE INDEX character_role_idx IF NOT EXISTS FOR (c:Character) ON (c.role_type)",
    "CREATE INDEX character_gender_idx IF NOT EXISTS FOR (c:Character) ON (c.gender)",
    "CREATE INDEX character_status_idx IF NOT EXISTS FOR (c:Character) ON (c.status)",
    "CREATE INDEX character_first_seen_idx IF NOT EXISTS FOR (c:Character) ON (c.first_chapter)",
    "CREATE INDEX event_chapter_idx IF NOT EXISTS FOR (e:Event) ON (e.chapter)",
    "CREATE INDEX event_type_idx IF NOT EXISTS FOR (e:Event) ON (e.event_type)",
    "CREATE INDEX charstate_chapter_idx IF NOT EXISTS FOR (s:CharacterState) ON (s.chapter)",
]


def reset_database(driver: Driver) -> None:
    with driver.session() as session:
        def _drop_all(tx):
            tx.run("MATCH (n) DETACH DELETE n")
        session.execute_write(_drop_all)


def create_constraints_and_indexes(driver: Driver) -> None:
    with driver.session() as session:
        for stmt in CONSTRAINTS + INDEXES:
            session.run(stmt)


def main():
    parser = argparse.ArgumentParser(description="Bootstrap Neo4j: constraints, indexes, and optional reset.")
    parser.add_argument("--reset", action="store_true", help="Danger: wipe all nodes and relationships before creating constraints.")
    args = parser.parse_args()

    driver = get_neo4j_driver()
    try:
        if args.reset:
            reset_database(driver)
        create_constraints_and_indexes(driver)
        print("Neo4j bootstrap completed.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()


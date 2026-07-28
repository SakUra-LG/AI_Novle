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
    "CREATE CONSTRAINT unique_story_chapter_id IF NOT EXISTS FOR (c:StoryChapter) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT unique_story_event_id IF NOT EXISTS FOR (e:StoryEvent) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT unique_story_fact_id IF NOT EXISTS FOR (f:StoryFact) REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT unique_relation_fact_id IF NOT EXISTS FOR (r:RelationFact) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT unique_plot_thread_id IF NOT EXISTS FOR (t:PlotThread) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT unique_plot_thread_signal_id IF NOT EXISTS FOR (s:PlotThreadSignal) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT unique_plot_cluster_id IF NOT EXISTS FOR (p:PlotCluster) REQUIRE p.id IS UNIQUE",
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
    "CREATE INDEX story_event_chapter_idx IF NOT EXISTS FOR (e:StoryEvent) ON (e.source_chapter)",
    "CREATE INDEX story_chapter_lookup_idx IF NOT EXISTS FOR (c:StoryChapter) ON (c.story_id, c.number)",
    "CREATE INDEX story_event_time_idx IF NOT EXISTS FOR (e:StoryEvent) ON (e.story_time)",
    "CREATE INDEX story_fact_lookup_idx IF NOT EXISTS FOR (f:StoryFact) ON (f.subject, f.predicate, f.source_chapter)",
    "CREATE INDEX relation_fact_chapter_idx IF NOT EXISTS FOR (r:RelationFact) ON (r.source_chapter)",
    "CREATE INDEX plot_thread_status_idx IF NOT EXISTS FOR (t:PlotThread) ON (t.status)",
    "CREATE INDEX plot_cluster_span_idx IF NOT EXISTS FOR (p:PlotCluster) ON (p.start_chapter, p.end_chapter)",
]


def reset_database(driver: Driver) -> None:
    with driver.session() as session:
        def _drop_all(tx):
            tx.run("MATCH (n) DETACH DELETE n")
        session.execute_write(_drop_all)


def create_constraints_and_indexes(driver: Driver) -> None:
    with driver.session() as session:
        session.run("DROP CONSTRAINT unique_story_chapter_number IF EXISTS")
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


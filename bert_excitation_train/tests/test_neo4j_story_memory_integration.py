import json
import os
import tempfile
import unittest
from pathlib import Path

from bert_excitation_train.scripts.neo4j_kg.bootstrap_neo4j import create_constraints_and_indexes, reset_database
from bert_excitation_train.scripts.neo4j_kg.build_plot_clusters import upsert_plot_clusters
from bert_excitation_train.scripts.neo4j_kg.chapter_memory import normalize_memory
from bert_excitation_train.scripts.neo4j_kg.common import get_neo4j_driver
from bert_excitation_train.scripts.neo4j_kg.online_retriever import retrieve_context_for_chapter
from bert_excitation_train.scripts.neo4j_kg.story_memory_store import replace_chapter_memory
from bert_excitation_train.scripts.neo4j_kg.story_identity import story_id_for_clusters


@unittest.skipUnless(os.environ.get("NEO4J_TEST_URI"), "set NEO4J_TEST_URI to run Neo4j integration tests")
class Neo4jStoryMemoryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["NEO4J_URI"] = os.environ["NEO4J_TEST_URI"]
        cls.driver = get_neo4j_driver()
        cls.driver.verify_connectivity()
        reset_database(cls.driver)
        create_constraints_and_indexes(cls.driver)

    @classmethod
    def tearDownClass(cls):
        reset_database(cls.driver)
        cls.driver.close()

    def test_projection_retrieval_temporal_edges_and_rewrite_cleanup(self):
        chapter5 = normalize_memory({
            "narrative_timeline": "current",
            "characters": [
                {"name": "Arthur Cole", "mention_mode": "active"},
                {"name": "Maya Reed", "mention_mode": "active"},
            ],
            "state_changes": [{
                "character": "Arthur Cole", "field": "life_status", "new_value": "dead",
                "timeline": "current", "permanent": True, "evidence": "Arthur was pronounced dead.",
            }],
            "events": [
                {"summary": "Arthur exposes the producer", "timeline": "current", "story_time": "1998-06-12",
                 "participants": [{"name": "Arthur Cole", "mode": "active"}], "outcome": "the audience hears the truth"},
                {"summary": "Arthur dies backstage", "timeline": "current", "story_time": "1998-06-12",
                 "participants": [{"name": "Arthur Cole", "mode": "active"}], "outcome": "Arthur is dead"},
            ],
            "relationships": [{
                "subject": "Maya Reed", "object": "Victor Kane", "type": "rival", "status": "hostile",
                "timeline": "current", "evidence": "Victor framed Maya.",
            }],
            "plot_threads": [{"title": "Who forged the master recording", "status": "open"}],
        }, 5, "chapter-5-hash")
        replace_chapter_memory(self.driver, chapter5)

        chapter6 = normalize_memory({
            "narrative_timeline": "current",
            "characters": [{"name": "Maya Reed", "mention_mode": "active"}],
            "events": [{
                "summary": "Maya protects Arthur's original recording", "timeline": "current", "story_time": "1998-06-13",
                "participants": [{"name": "Maya Reed", "mode": "active"}], "outcome": "the recording remains safe",
            }],
        }, 6, "chapter-6-hash")
        replace_chapter_memory(self.driver, chapter6)

        context = retrieve_context_for_chapter(25, ["Arthur Cole", "Maya Reed", "Victor Kane"])
        self.assertIn("Arthur Cole.life_status=dead", context)
        self.assertIn("禁止在当前时间线行动", context)
        self.assertIn("Maya Reed --rival/hostile--> Victor Kane", context)
        self.assertIn("Who forged the master recording", context)

        with self.driver.session() as session:
            row = session.run(
                """
                MATCH (a:StoryEvent)-[r:NEXT_EVENT]->(b:StoryEvent)
                RETURN count(r) AS count
                """
            ).single()
            self.assertGreaterEqual(row["count"], 2)
            arthur = session.run(
                "MATCH (c:Character {name:'Arthur Cole'}) RETURN c.life_status AS status"
            ).single()
            self.assertEqual("dead", arthur["status"])

        rewritten5 = normalize_memory({
            "narrative_timeline": "current",
            "characters": [{"name": "Maya Reed", "mention_mode": "active"}],
            "events": [{
                "summary": "Maya exposes the producer", "timeline": "current", "story_time": "1998-06-12",
                "participants": [{"name": "Maya Reed", "mode": "active"}], "outcome": "the audience hears the truth",
            }],
        }, 5, "rewritten-hash")
        replace_chapter_memory(self.driver, rewritten5)
        with self.driver.session() as session:
            stale_mentions = session.run(
                """
                MATCH (:Character {name:'Arthur Cole'})-[m:MENTIONED_IN]->(:StoryChapter {number:5})
                RETURN count(m) AS count
                """
            ).single()
            stale_facts = session.run(
                "MATCH (f:StoryFact {subject:'Arthur Cole'}) RETURN count(f) AS count"
            ).single()
            arthur_after_rewrite = session.run(
                "MATCH (c:Character {name:'Arthur Cole'}) RETURN c.life_status AS status"
            ).single()
            self.assertEqual(0, stale_mentions["count"])
            self.assertEqual(0, stale_facts["count"])
            self.assertIsNone(arthur_after_rewrite)

    def test_planned_cluster_is_labeled_as_future_plan(self):
        clusters = [{
            "cluster_id": "EC02", "name": "The contract trap", "chapter_span": [20, 24],
            "core_payoff": "Maya keeps the rights", "cluster_outcome": "the predatory option expires",
            "hard_constraints": ["Victor cannot know Maya has the original master"],
        }]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "clusters.json"
            path.write_text(json.dumps(clusters), encoding="utf-8")
            story_id = story_id_for_clusters(path)
            upsert_plot_clusters(self.driver, str(path), story_id=story_id)
        context = retrieve_context_for_chapter(22, ["Maya Reed", "Victor Kane"], story_id=story_id)
        self.assertIn("当前情节族计划，尚未发生", context)
        self.assertIn("The contract trap", context)

    def test_same_character_name_is_isolated_between_stories(self):
        alive = normalize_memory({
            "story_id": "story-alive",
            "state_changes": [{
                "character": "Maya Reed", "field": "life_status", "new_value": "alive",
                "timeline": "current", "evidence": "Maya answers the phone.",
            }],
        }, 3, "alive-hash")
        dead = normalize_memory({
            "story_id": "story-dead",
            "state_changes": [{
                "character": "Maya Reed", "field": "life_status", "new_value": "dead",
                "timeline": "current", "permanent": True, "evidence": "Maya is pronounced dead.",
            }],
        }, 3, "dead-hash")
        replace_chapter_memory(self.driver, alive)
        replace_chapter_memory(self.driver, dead)

        alive_context = retrieve_context_for_chapter(8, ["Maya Reed"], story_id="story-alive")
        dead_context = retrieve_context_for_chapter(8, ["Maya Reed"], story_id="story-dead")
        self.assertIn("Maya Reed.life_status=alive", alive_context)
        self.assertNotIn("life_status=dead", alive_context)
        self.assertIn("Maya Reed.life_status=dead", dead_context)
        self.assertNotIn("life_status=alive", dead_context)

        with self.driver.session() as session:
            row = session.run(
                "MATCH (c:Character {name:'Maya Reed'}) "
                "WHERE c.story_id IN ['story-alive', 'story-dead'] RETURN count(c) AS count"
            ).single()
            self.assertEqual(2, row["count"])


if __name__ == "__main__":
    unittest.main()

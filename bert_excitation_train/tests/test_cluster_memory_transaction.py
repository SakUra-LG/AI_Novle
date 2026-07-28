import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bert_excitation_train.scripts.neo4j_kg.chapter_memory import normalize_memory, save_memory_file
from bert_excitation_train.scripts.neo4j_kg.story_memory import StoryMemoryCoordinator
from bert_excitation_train.scripts.v2 import generate_chapter_content_v2 as chapter_v2


class ClusterMemoryTransactionTests(unittest.TestCase):
    def test_failed_cluster_restores_text_and_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapter_dir = root / "chapters"
            chapter_dir.mkdir()
            chapter_path = chapter_dir / "chapter_005.txt"
            chapter_path.write_text("accepted old text", encoding="utf-8")

            memory_dir = root / "memory"
            coordinator = StoryMemoryCoordinator(memory_dir)
            old_memory = normalize_memory({"summary": "accepted old memory"}, 5, "old-hash")
            save_memory_file(memory_dir, old_memory)
            gen = SimpleNamespace(
                outputs_dir=root,
                story_memory=coordinator,
                generated_chapters={5: "accepted old text"},
            )

            def failing_impl(*_args, **_kwargs):
                chapter_path.write_text("provisional bad text", encoding="utf-8")
                coordinator.commit(normalize_memory({"summary": "provisional bad memory"}, 5, "bad-hash"))
                raise RuntimeError("cluster critic failed")

            cluster = {"chapter_span": [5, 5]}
            with patch.object(chapter_v2, "_generate_cluster_continuous_and_split_v2_impl", failing_impl):
                with self.assertRaises(RuntimeError):
                    chapter_v2._generate_cluster_continuous_and_split_v2(gen, cluster, {})

            self.assertEqual("accepted old text", chapter_path.read_text(encoding="utf-8"))
            restored = coordinator.memories_before(6)
            self.assertEqual("accepted old memory", restored[0]["summary"])
            self.assertEqual("accepted old text", gen.generated_chapters[5])


if __name__ == "__main__":
    unittest.main()

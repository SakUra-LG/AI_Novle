import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bert_excitation_train.scripts.neo4j_kg.chapter_memory import (
    content_hash,
    normalize_memory,
    save_memory_file,
)
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

    def test_keyboard_interrupt_restores_every_local_layer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapter_dir = root / "chapters"
            chapter_dir.mkdir()
            chapter_path = chapter_dir / "chapter_005.txt"
            chapter_path.write_text("old disk text", encoding="utf-8")
            coordinator = StoryMemoryCoordinator(root / "memory")
            old_memory = normalize_memory({"summary": "old memory"}, 5, "old")
            save_memory_file(root / "memory", old_memory)
            gen = SimpleNamespace(
                outputs_dir=root,
                chapters_dir=chapter_dir,
                story_memory=coordinator,
                generated_chapters={5: "old cached text"},
            )

            def interrupted_impl(*_args, **_kwargs):
                chapter_path.write_text("new disk text", encoding="utf-8")
                coordinator.commit(
                    normalize_memory({"summary": "new memory"}, 5, "new")
                )
                gen.generated_chapters[5] = "new cached text"
                raise KeyboardInterrupt()

            with patch.object(
                chapter_v2,
                "_generate_cluster_continuous_and_split_v2_impl",
                interrupted_impl,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    chapter_v2._generate_cluster_continuous_and_split_v2(
                        gen,
                        {"chapter_span": [5, 5]},
                        {},
                    )

            self.assertEqual("old disk text", chapter_path.read_text(encoding="utf-8"))
            self.assertEqual("old cached text", gen.generated_chapters[5])
            restored = coordinator.snapshot([5])[5]
            self.assertEqual("old memory", restored["summary"])

    def test_stale_journal_recovers_after_process_termination(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapter_dir = root / "chapters"
            chapter_dir.mkdir()
            chapter_path = chapter_dir / "chapter_005.txt"
            chapter_path.write_text("durable old text", encoding="utf-8")
            coordinator = StoryMemoryCoordinator(
                root / "memory",
                story_id="story-a",
            )
            old_memory = normalize_memory(
                {"story_id": "story-a", "summary": "durable old memory"},
                5,
                "old-hash",
            )
            save_memory_file(root / "memory", old_memory)
            gen = SimpleNamespace(
                outputs_dir=root,
                chapters_dir=chapter_dir,
                story_memory=coordinator,
                generated_chapters={5: "durable old text"},
            )
            chapter_v2._write_cluster_transaction_journal(
                gen,
                [5],
                {5: "durable old text"},
                coordinator.snapshot([5]),
            )

            chapter_path.write_text("partial new text", encoding="utf-8")
            new_memory = normalize_memory(
                {"story_id": "story-a", "summary": "partial new memory"},
                5,
                "new-hash",
            )
            coordinator.commit(new_memory)
            gen.generated_chapters[5] = "partial new text"

            self.assertTrue(
                chapter_v2._recover_pending_cluster_transaction(gen)
            )
            self.assertEqual(
                "durable old text",
                chapter_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "durable old memory",
                coordinator.snapshot([5])[5]["summary"],
            )
            self.assertEqual("durable old text", gen.generated_chapters[5])
            self.assertFalse(
                chapter_v2._cluster_transaction_journal_path(
                    coordinator
                ).exists()
            )

    def test_custom_chapters_directory_is_the_transaction_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            custom = root / "custom_chapter_output"
            custom.mkdir()
            chapter_path = custom / "chapter_005.txt"
            chapter_path.write_text("old custom text", encoding="utf-8")
            coordinator = StoryMemoryCoordinator(root / "memory")
            gen = SimpleNamespace(
                outputs_dir=root,
                chapters_dir=custom,
                story_memory=coordinator,
                generated_chapters={5: "old cache"},
            )

            def rejected_impl(*_args, **_kwargs):
                chapter_path.write_text("rejected custom text", encoding="utf-8")
                return {}

            with patch.object(
                chapter_v2,
                "_generate_cluster_continuous_and_split_v2_impl",
                rejected_impl,
            ):
                result = chapter_v2._generate_cluster_continuous_and_split_v2(
                    gen,
                    {"chapter_span": [5, 5]},
                    {},
                )

            self.assertEqual({}, result)
            self.assertEqual("old custom text", chapter_path.read_text(encoding="utf-8"))
            self.assertFalse((root / "chapters" / "chapter_005.txt").exists())

    def test_unified_delivery_writes_exact_text_memory_and_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chapters = root / "chapters"
            coordinator = StoryMemoryCoordinator(
                root / "memory",
                story_id="story-a",
            )

            def save_chapter(chapter, text):
                chapters.mkdir(parents=True, exist_ok=True)
                path = chapters / f"chapter_{chapter:03d}.txt"
                path.write_text(text, encoding="utf-8")
                return str(path)

            gen = SimpleNamespace(
                outputs_dir=root,
                chapters_dir=chapters,
                story_memory=coordinator,
                generated_chapters={},
                save_chapter=save_chapter,
                commit_story_memories=coordinator.commit_many,
            )
            text = "  exact accepted text with deliberate boundary spaces  "
            memory = normalize_memory({"summary": "accepted"}, 5, content_hash(text))
            memory["story_id"] = "story-a"

            chapter_v2._commit_staged_cluster_delivery(
                gen,
                {5: text},
                {5: memory},
            )

            self.assertEqual(
                text,
                (chapters / "chapter_005.txt").read_text(encoding="utf-8"),
            )
            committed = coordinator.snapshot([5])[5]
            self.assertEqual(content_hash(text), committed["content_hash"])
            self.assertEqual(text, gen.generated_chapters[5])

    def test_hash_mismatch_rejects_before_first_official_write(self):
        coordinator = StoryMemoryCoordinator(Path("unused"), story_id="story-a")
        save = Mock()
        commit = Mock()
        gen = SimpleNamespace(
            outputs_dir=Path("unused"),
            chapters_dir=Path("unused") / "chapters",
            story_memory=coordinator,
            generated_chapters={},
            save_chapter=save,
            commit_story_memories=commit,
        )
        memory = normalize_memory({"summary": "bad"}, 5, "stale-hash")
        memory["story_id"] = "story-a"
        with self.assertRaises(RuntimeError):
            chapter_v2._commit_staged_cluster_delivery(
                gen,
                {5: "new text"},
                {5: memory},
            )
        save.assert_not_called()
        commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()

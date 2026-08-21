import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bert_excitation_train.scripts.neo4j_kg import story_memory as story_memory_module
from bert_excitation_train.scripts.neo4j_kg.chapter_memory import (
    normalize_memory,
    save_memory_file,
)
from bert_excitation_train.scripts.neo4j_kg.story_memory import (
    StoryMemoryCoordinator,
)
from bert_excitation_train.scripts.neo4j_kg.story_memory_store import (
    replace_chapter_memories,
)


class _DriverContext:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, traceback):
        return False


class StoryMemoryAtomicityTests(unittest.TestCase):
    def test_graph_failure_restores_old_json_and_removes_new_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            coordinator = StoryMemoryCoordinator(
                root,
                driver_factory=lambda: _DriverContext(),
                story_id="story-a",
            )
            old = normalize_memory({"summary": "old"}, 5, "old-hash")
            old["story_id"] = "story-a"
            save_memory_file(root, old)
            replacement = normalize_memory(
                {"summary": "replacement"},
                5,
                "new-hash",
            )
            new_chapter = normalize_memory({"summary": "new"}, 6, "six-hash")

            with patch(
                "bert_excitation_train.scripts.neo4j_kg.story_memory_store."
                "replace_chapter_memories",
                side_effect=RuntimeError("graph failed"),
            ):
                with self.assertRaises(RuntimeError):
                    coordinator.commit_many([replacement, new_chapter])

            restored = json.loads(
                (root / "chapter_005_memory.json").read_text(encoding="utf-8")
            )
            self.assertEqual("old", restored["summary"])
            self.assertFalse((root / "chapter_006_memory.json").exists())

    def test_keyboard_interrupt_restores_local_ledger_and_propagates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            coordinator = StoryMemoryCoordinator(
                root,
                driver_factory=lambda: _DriverContext(),
                story_id="story-a",
            )
            old = normalize_memory({"summary": "old"}, 5, "old-hash")
            old["story_id"] = "story-a"
            save_memory_file(root, old)
            replacement = normalize_memory(
                {"summary": "replacement"},
                5,
                "new-hash",
            )

            with patch(
                "bert_excitation_train.scripts.neo4j_kg.story_memory_store."
                "replace_chapter_memories",
                side_effect=KeyboardInterrupt(),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    coordinator.commit_many([replacement])

            restored = json.loads(
                (root / "chapter_005_memory.json").read_text(encoding="utf-8")
            )
            self.assertEqual("old", restored["summary"])

    def test_second_local_write_failure_restores_first_and_never_starts_graph(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            coordinator = StoryMemoryCoordinator(
                root,
                driver_factory=lambda: _DriverContext(),
                story_id="story-a",
            )
            old = normalize_memory({"summary": "old"}, 5, "old-hash")
            old["story_id"] = "story-a"
            save_memory_file(root, old)
            chapter5 = normalize_memory({"summary": "new-five"}, 5, "five-hash")
            chapter6 = normalize_memory({"summary": "new-six"}, 6, "six-hash")
            graph_replace = Mock()
            real_save = story_memory_module.save_memory_file

            def flaky_save(memory_dir, memory):
                if (
                    int(memory.get("chapter", 0)) == 6
                    and memory.get("summary") == "new-six"
                ):
                    raise OSError("disk full")
                return real_save(memory_dir, memory)

            with patch.object(
                story_memory_module,
                "save_memory_file",
                side_effect=flaky_save,
            ), patch(
                "bert_excitation_train.scripts.neo4j_kg.story_memory_store."
                "replace_chapter_memories",
                graph_replace,
            ):
                with self.assertRaises(OSError):
                    coordinator.commit_many([chapter5, chapter6])

            restored = json.loads(
                (root / "chapter_005_memory.json").read_text(encoding="utf-8")
            )
            self.assertEqual("old", restored["summary"])
            self.assertFalse((root / "chapter_006_memory.json").exists())
            graph_replace.assert_not_called()

    def test_snapshot_rejects_non_object_and_mismatched_chapter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            coordinator = StoryMemoryCoordinator(root, story_id="story-a")
            path = root / "chapter_005_memory.json"
            root.mkdir(parents=True, exist_ok=True)
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                coordinator.snapshot([5])
            path.write_text(
                json.dumps({"chapter": 6, "story_id": "story-a"}),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                coordinator.snapshot([5])

    def test_pending_state_ignores_current_and_future_chapters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = StoryMemoryCoordinator(
                Path(temp_dir),
                story_id="story-a",
            )
            prior = normalize_memory(
                {"facts": [{"subject": "主角", "predicate": "goal", "object": "先核验"}]},
                5,
                "five",
            )
            current = normalize_memory(
                {"facts": [{"subject": "主角", "predicate": "goal", "object": "当前泄漏"}]},
                6,
                "six",
            )
            future = normalize_memory(
                {"facts": [{"subject": "主角", "predicate": "goal", "object": "未来泄漏"}]},
                7,
                "seven",
            )
            state = coordinator.state_before(6, [prior, current, future])
            rendered = json.dumps(state, ensure_ascii=False)
            self.assertIn("先核验", rendered)
            self.assertNotIn("当前泄漏", rendered)
            self.assertNotIn("未来泄漏", rendered)

    def test_trace_failure_does_not_change_commit_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            coordinator = StoryMemoryCoordinator(root, story_id="story-a")
            coordinator.trace_path = root
            memory = normalize_memory({"summary": "accepted"}, 5, "hash")
            path = coordinator.commit(memory)
            self.assertTrue(path.exists())

    def test_empty_prune_is_rejected_before_driver_use(self):
        with self.assertRaises(ValueError):
            replace_chapter_memories(
                Mock(),
                [],
                story_id="story-a",
                prune_missing=True,
            )


if __name__ == "__main__":
    unittest.main()

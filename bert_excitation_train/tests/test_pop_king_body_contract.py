from __future__ import annotations

import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bert_excitation_train.scripts.novel_generation_v2.generate_pop_king_body_v5 import (
    _base_single_chapter_prompt_sha256,
    _character_constraints_for_scene,
    _load_character_bible,
    _load_inputs,
    _prior_body_chain_sha256,
    _validate_candidate,
    _validate_single_chapter,
)


def test_character_bible_is_valid_and_selects_only_scene_characters() -> None:
    bible = _load_character_bible()
    cluster = {
        **_cluster(),
        "main_opponent": "维克多·兰斯",
        "main_characters": ["麦珂·杰森", "玛莎·杰森"],
    }
    card = {**_card(2), "participants": ["麦珂·杰森", "玛莎·杰森", "维克多·兰斯"]}
    selected = _character_constraints_for_scene(cluster, [card], bible=bible)
    names = [item["name"] for item in selected["selected_characters"]]
    assert names == ["麦珂·杰森", "玛莎·杰森", "维克多·兰斯"]
    assert "巴里·布鲁姆" not in names
    assert selected["global_method"]["choice_rule"]


def _cluster() -> dict:
    return {
        "cluster_id": "EC001",
        "chapter_span": [1, 2],
        "opposition_type": "villain",
        "info_gap_from_prev_life": "麦珂记得对手会在下午三点抢走母带。",
        "villain_loss": "维克多失去母带控制权",
        "protagonist_gain": "麦珂获得母带保管权",
        "relationship_change": "玛莎决定公开站在儿子一边",
    }


def _card(chapter_id: int) -> dict:
    return {
        "chapter_id": chapter_id,
        "chapter_title": f"第{chapter_id}章",
        "chapter_role_v2": "two_chapter_payoff" if chapter_id == 2 else "two_chapter_setup_and_win",
        "chapter_goal": "抢先保护母带",
        "info_gap_use": "利用前世记得的时间抢先行动",
        "immediate_payoff": "维克多失去母带控制权" if chapter_id == 2 else "完成小赢",
    }


def _prompt_hash(card: dict, previous_body: str = "") -> str:
    return _base_single_chapter_prompt_sha256(
        cluster=_cluster(),
        card=card,
        graph_context="graph:v1",
        style_samples=[{"sample_id": "S1", "focus": ["爽点"], "text": "短样本。"}],
        previous_body=previous_body,
        recent_style_budget={"source_chapters": [], "counts": {}},
    )


def test_base_prompt_hash_changes_with_card_and_previous_body() -> None:
    card = _card(2)
    original = _prompt_hash(card, "上一章原文甲")
    assert original != _prompt_hash({**card, "chapter_goal": "改变后的目标"}, "上一章原文甲")
    assert original != _prompt_hash(card, "上一章原文乙")


def test_prior_body_chain_changes_when_any_prior_chapter_changes(tmp_path: Path) -> None:
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "chapter_001.txt").write_text("第一章正文\n", encoding="utf-8")
    before = _prior_body_chain_sha256(tmp_path, 2)
    (chapters / "chapter_001.txt").write_text("第一章重生成正文\n", encoding="utf-8")
    after = _prior_body_chain_sha256(tmp_path, 2)
    assert before != after


def test_known_chapter_17_18_replay_is_rejected() -> None:
    base = PROJECT_ROOT / "第一版本"
    legacy_chapters = PROJECT_ROOT / "bert_excitation_train" / "outputs_pop_king_v5_qwen_story_first_500" / "chapters"
    if not legacy_chapters.exists():
        return
    events = json.loads((base / "event_clusters_v2.json").read_text(encoding="utf-8"))
    cards = json.loads((base / "master_ctx_cards_v2.json").read_text(encoding="utf-8"))
    event = events[8]
    card_map = {int(card["chapter_id"]): card for card in cards}
    parsed = {
        "cluster_id": "EC009",
        "chapters": [
            {
                "chapter_id": chapter_id,
                "body": (legacy_chapters / f"chapter_{chapter_id:03d}.txt").read_text(encoding="utf-8"),
            }
            for chapter_id in (17, 18)
        ],
    }
    _, failures, audits = _validate_candidate(
        parsed,
        cluster=event,
        cards=[card_map[17], card_map[18]],
    )
    assert audits["joint_semantic_overlap"] >= 0.12
    assert any("换词重演" in failure for failure in failures)


def test_body_loader_accepts_only_contiguous_two_chapter_plan_prefix(tmp_path: Path) -> None:
    (tmp_path / "event_clusters_v2.json").write_text(
        json.dumps([{"cluster_id": "EC001"}], ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "master_ctx_cards_v2.json").write_text(
        json.dumps([
            {"chapter_id": 1, "cluster_id": "EC001", "timeline_start": "1969-01-01"},
            {"chapter_id": 2, "cluster_id": "EC001", "timeline_start": "1969-01-02"},
        ], ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "chapter_synopses_v5_qwen_500.json").write_text(
        json.dumps([
            {"chapter_id": 1, "cluster_id": "EC001", "timeline_start": "1969-01-01"},
            {"chapter_id": 2, "cluster_id": "EC001", "timeline_start": "1969-01-02"},
        ], ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "global_story_outline_v5_qwen_500.json").write_text(
        json.dumps({"title": "完整总纲"}, ensure_ascii=False), encoding="utf-8"
    )
    events, cards, _ = _load_inputs(tmp_path)
    assert len(events) == 1
    assert sorted(cards) == [1, 2]

    (tmp_path / "event_clusters_v2.json").write_text(
        json.dumps([{"cluster_id": "EC002"}], ensure_ascii=False), encoding="utf-8"
    )
    try:
        _load_inputs(tmp_path)
    except ValueError as exc:
        assert "从EC001开始连续" in str(exc)
    else:
        raise AssertionError("non-contiguous plan prefix must be rejected")


def test_semantic_must_not_blocks_speaking_without_verbatim_forbidden_phrase() -> None:
    card = {
        **_card(5),
        "chapter_must_not_include": ["麦珂开口说话"],
        "chapter_must_include": [],
    }
    parsed = {
        "chapter_id": 5,
        "body": "麦珂问：\"延时调好了吗？\"" + "他安静等待现场给出答复。" * 140,
    }
    _, failures, _ = _validate_single_chapter(parsed, card)
    assert any("语义违反章卡禁写项" in failure for failure in failures)


def test_must_include_is_a_gate_not_a_review_only_counter() -> None:
    card = {
        **_card(6),
        "chapter_must_include": ["三拍休止"],
        "chapter_must_not_include": [],
    }
    parsed = {
        "chapter_id": 6,
        "body": "麦珂唱完整段副歌，现场掌声响起。" + "他随后完成另一段表演。" * 140,
    }
    _, failures, _ = _validate_single_chapter(parsed, card)
    assert any("没有兑现章卡关键事实" in failure for failure in failures)

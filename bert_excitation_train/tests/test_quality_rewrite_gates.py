"""Regression gates for the 271—356 quarantine/rewrite workflow."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bert_excitation_train.scripts.v2.accept_manual_body_batch_v14 import (
    _formal_contiguous_max,
    _load_external_review,
)
from bert_excitation_train.scripts.v2.generate_pop_king_body_v5 import (
    _hard_metadata_leak_failures,
    _character_identity_failures,
    _load_character_bible,
    _opening_time_failures,
    _paragraph_quality_failures,
    _rebirth_subject_failures,
)
from bert_excitation_train.scripts.v2.pop_king_plan_compiler import (
    next_hook_repeat_failures,
    trial_chapter_binding_failures,
    trial_forward_consumption_failures,
    trial_timeline_failures,
    timeline_years,
    validate_trial_cluster_card,
)
from bert_excitation_train.scripts.v2.generate_three_act_trial import (
    BEAT_KEYS,
    validate_beat_plan,
)
from bert_excitation_train.scripts.v2.generate_three_act_trial_v2 import (
    pair_replay_failures,
    timeline_failures,
    validate_plan as validate_joint_plan,
)


def test_missing_323_324_stops_formal_continuous_prefix(tmp_path: Path) -> None:
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    for chapter_id in (321, 322, 325):
        (chapters / f"chapter_{chapter_id:03d}.txt").write_text("x", encoding="utf-8")
    assert _formal_contiguous_max(tmp_path) == 0
    for chapter_id in range(1, 323):
        (chapters / f"chapter_{chapter_id:03d}.txt").write_text("x", encoding="utf-8")
    assert _formal_contiguous_max(tmp_path) == 322


def test_acceptance_requires_current_hash_review(tmp_path: Path) -> None:
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"reviewer": "human", "reviewed_at": "2026-08-26", "chapter_reviews": []}), encoding="utf-8")
    try:
        _load_external_review(review, [271], {"271": "correct"})
    except RuntimeError as exc:
        assert "人工review" in str(exc)
    else:
        raise AssertionError("stale or incomplete review must be rejected")


def test_non_maike_rebirth_memory_is_rejected() -> None:
    failures = _rebirth_subject_failures("瑟琳娜想起上一世被夺走的资产。")
    assert failures
    assert _rebirth_subject_failures("他记得前世的失败。")


def test_metadata_tokens_are_rejected() -> None:
    failures = _hard_metadata_leak_failures("现场出现ART_272_AUDIT_OFFICIAL_REPORT和asset_integrity_secured。")
    assert failures


def test_timeline_year_parser_exposes_year_conflict_input() -> None:
    assert timeline_years("1993") == [1993]
    assert 1993 not in timeline_years("1996")


def test_trial_chapter_271_before_formal_270_is_hard_failure() -> None:
    failures = trial_timeline_failures({271: "1993-09-12"}, formal_prior_date="1993-09-17")
    assert any("时间线倒退" in item for item in failures)


def test_trial_ec_binding_and_forward_consumption_are_hard_failures() -> None:
    plan = {"event_clusters": [
        {"cluster_id": "EC136", "chapter_specs": [
            {"chapter_id": 271, "date": "1993-09-18", "forbidden_progress": ["合同谈判"]}],
            "main_character_ids": [], "participant_ids": []},
        {"cluster_id": "EC137", "chapter_specs": [
            {"chapter_id": 273, "date": "1993-09-19", "forbidden_progress": ["合同谈判"]}],
            "main_character_ids": [], "participant_ids": []},
    ]}
    assert trial_chapter_binding_failures("合同谈判已经完成", "EC136", 271, plan)
    assert trial_forward_consumption_failures("合同生效，自动延长", "EC136", plan)


def test_repeated_paragraphs_are_rejected() -> None:
    paragraph = "麦珂把来源和授权逐项登记，要求所有人按边界使用材料。"
    body = "\n\n".join([paragraph] * 7)
    assert any("完全重复" in item for item in _paragraph_quality_failures(body))


def _valid_three_act_plan() -> dict:
    beats = []
    states = ["进入", "发现", "受阻", "调整", "执行", "留钩", "确认", "结算", "收束"]
    for index in range(8):
        beats.append({
            "act_id": 1 if index < 2 else (2 if index < 6 else 3),
            "beat_id": f"B{index + 1}",
            "location": "录音棚控制室",
            "time_relation": "当天承接" if index else "本章开场",
            "active_character": "艾琳·沃特曼",
            "immediate_goal": f"目标{index}",
            "visible_action": f"动作{index}",
            "resistance": f"阻力{index}",
            "new_information": f"信息{index}",
            "character_choice": f"选择{index}",
            "relationship_or_emotional_change": f"变化{index}",
            "state_before": states[index],
            "state_after": states[index + 1],
            "artifact_use": f"物证{index}",
            "forbidden_replay": "不得重演上一节拍",
            "chapter_boundary": "只结算本章",
        })
    return {"chapter_id": 293, "acts": [
        {"act_id": 1, "beats": beats[:2]},
        {"act_id": 2, "beats": beats[2:6]},
        {"act_id": 3, "beats": beats[6:]},
    ], "chapter_boundary": "不提前消费下一章"}


def test_three_act_plan_requires_state_continuity() -> None:
    card = {"chapter_id": 293, "chapter_must_include": []}
    plan = _valid_three_act_plan()
    assert validate_beat_plan(plan, card=card) == []
    plan["acts"][1]["beats"][0]["state_before"] = "断裂"
    assert any("节拍状态未衔接" in item for item in validate_beat_plan(plan, card=card))


def test_three_act_plan_requires_all_fields_and_eight_to_ten_beats() -> None:
    card = {"chapter_id": 293, "chapter_must_include": []}
    plan = _valid_three_act_plan()
    del plan["acts"][0]["beats"][0]["visible_action"]
    plan["acts"][2]["beats"] = plan["acts"][2]["beats"][:1]
    failures = validate_beat_plan(plan, card=card)
    assert any("缺少字段" in item for item in failures)
    assert any("节拍总数" in item for item in failures)


def test_time_anchor_may_appear_after_action_led_first_paragraph() -> None:
    card = {"chapter_id": 271, "timeline_start": "1993-09-18"}
    body = "档案员把复印件推回柜台，拒绝开放整批原件。\n\n墙上的值班表仍停在1993年九月。"
    assert _opening_time_failures(body, card) == []


def test_full_date_as_non_rebirth_first_sentence_is_rejected() -> None:
    card = {"chapter_id": 271, "timeline_start": "1993-09-18"}
    body = "1993年9月18日，档案员把复印件推回柜台。"
    assert any("首句机械使用完整日期" in item for item in _opening_time_failures(body, card))


def test_unresolved_character_name_is_rejected() -> None:
    card = {"main_character_ids": [], "main_opponent_character_ids": [], "canonical_cast": []}
    assert _character_identity_failures("卡尔·斯特林走进房间。", card)


def test_three_repeated_hooks_are_rejected() -> None:
    events = [{"cluster_id": f"EC{i:03d}", "next_event_hook": "同一钩子"} for i in (1, 2, 3)]
    failures = next_hook_repeat_failures(events)
    assert any("连续三次" in item for item in failures)


def test_near_duplicate_hooks_are_rejected() -> None:
    events = [
        {"cluster_id": "EC001", "next_event_hook": "调查委员会将复核来源链"},
        {"cluster_id": "EC002", "next_event_hook": "调查委员会将复核来源链"},
    ]
    assert next_hook_repeat_failures(events)


def test_character_bible_has_unique_stable_ids() -> None:
    profiles = _load_character_bible()["characters"]
    ids = [profile.get("character_id") for profile in profiles]
    assert len(ids) == len(set(ids))
    assert all(__import__("re").fullmatch(r"CHAR_[A-F0-9]{12}", value or "") for value in ids)


def test_ec138_candidate_card_is_two_chapter_and_not_formal() -> None:
    root = Path(__file__).resolve().parents[1]
    package = root / "outputs_pop_king_v6_compiled_story_first_500" / "body_generation" / "rewrite_trial_271_274"
    payload = json.loads((package / "EC138_candidate_cards.json").read_text(encoding="utf-8"))
    assert payload["status"].startswith("candidate_only")
    assert validate_trial_cluster_card(payload, payload["chapter_cards"]) == []


def test_v2_rejects_trial_start_before_formal_chapter_270() -> None:
    assert timeline_failures(
        {"chapter_id": 270, "timeline_end": "1993-09-17"},
        {"chapter_id": 271, "timeline_start": "1993-09-12"},
    )


def test_v2_rejects_replayed_pair() -> None:
    body = "甲" * 1500
    assert pair_replay_failures(body, body)


def test_v2_joint_plan_rejects_next_cluster_consumption() -> None:
    cards = {cid: {"chapter_id": cid} for cid in (293, 294, 295, 296)}
    plan = {"chapters": []}
    for cid in cards:
        beats = [{key: ("x" if key not in ("act_id", "beat_id") else (1 if key == "act_id" else "b1")) for key in BEAT_KEYS}]
        plan["chapters"].append({"chapter_id": cid, "acts": [{"act_id": 1, "beats": beats}, {"act_id": 2, "beats": []}, {"act_id": 3, "beats": []}]})
    plan["chapters"][2]["acts"][0]["beats"][0]["visible_action"] = "盲审"
    assert any("越界" in x for x in validate_joint_plan(plan, cards))

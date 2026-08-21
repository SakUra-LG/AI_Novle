import tempfile
import unittest
import json
from pathlib import Path

from bert_excitation_train.scripts.neo4j_kg.chapter_memory import (
    build_story_state,
    canonical_possession_key,
    load_memory_files,
    normalize_memory,
    render_story_constraints,
    save_memory_file,
    validate_transition,
    extract_chapter_memory,
    story_state_slot,
)
from bert_excitation_train.scripts.neo4j_kg.online_retriever import (
    _latest_current_fact_rows,
)
from bert_excitation_train.scripts.neo4j_kg.story_memory import StoryMemoryCoordinator
from bert_excitation_train.scripts.neo4j_kg.sync_story_memory import (
    _known_names_from_clusters,
)


def memory(chapter, **values):
    return normalize_memory(values, chapter, f"hash-{chapter}")


class ChapterMemoryContinuityTests(unittest.TestCase):
    def test_sync_known_names_include_compound_functional_opponents(self):
        names = _known_names_from_clusters([
            {
                "canonical_cast": [
                    {"name": "闻溪"},
                    {"name": "林澈"},
                ],
                "main_opponent": "主办方与内部员工",
            }
        ])
        self.assertEqual(
            ["闻溪", "林澈", "主办方", "内部员工"],
            names,
        )

    def test_heuristic_extraction_resolves_middle_dot_short_names(self):
        result = extract_chapter_memory(
            5,
            "麦珂完成整套唱跳，卡尔当场交出训练强度决定权。",
            known_names=["麦珂·杰森", "卡尔·霍尔特"],
            llm_call=None,
        )
        self.assertEqual("heuristic_complete", result["extraction_status"])
        self.assertEqual(
            {"麦珂·杰森", "卡尔·霍尔特"},
            {item["name"] for item in result["characters"]},
        )
        self.assertTrue(result["events"])

    def test_current_alias_action_overrides_earlier_previous_life_mention(self):
        result = extract_chapter_memory(
            9,
            (
                "麦珂记得，上一世，卡尔把安全测试伪装成已经完成。"
                "这一次，卡尔抢过控制器按下快捷程序，又伸手想拿回控制器。"
            ),
            known_names=["麦珂·杰森", "卡尔·霍尔特"],
            llm_call=None,
        )
        modes = {
            item["name"]: item["mention_mode"]
            for item in result["characters"]
        }
        self.assertEqual("active", modes["卡尔·霍尔特"])

    def test_heuristic_extracts_safety_payoff_and_command_right_transfer(self):
        result = extract_chapter_memory(
            10,
            (
                "麦珂当场叫停真人登台并保住所有舞者安全。"
                "独立安全总监宣布：卡尔失去舞台机关指挥权。"
                "麦珂取得最终启停否决权。"
            ),
            known_names=["麦珂·杰森", "卡尔·霍尔特"],
            llm_call=None,
        )
        changes = {
            (item["character"], item["new_value"])
            for item in result["state_changes"]
        }
        self.assertIn(("卡尔·霍尔特", "无舞台机关指挥权"), changes)
        self.assertIn(("麦珂·杰森", "最终启停否决权"), changes)
        self.assertIn("保住所有舞者安全", result["events"][0]["outcome"])
        self.assertIn("卡尔·霍尔特失去舞台机关指挥权", result["events"][0]["outcome"])
        self.assertIn("麦珂·杰森取得最终启停否决权", result["events"][0]["outcome"])

    def test_heuristic_extracts_right_assignment_after_right_name(self):
        result = extract_chapter_memory(
            5,
            (
                "卡尔试图降低强度，麦珂完成整段唱跳。"
                "合作方代表宣布：“训练强度决定权归还麦珂·杰森。”"
                "卡尔不敢再降强度。"
            ),
            known_names=["麦珂·杰森", "卡尔·霍尔特"],
            llm_call=None,
        )
        changes = {
            (item["character"], item["field"], item["new_value"])
            for item in result["state_changes"]
        }
        self.assertIn(
            ("麦珂·杰森", "possession", "训练强度决定权"),
            changes,
        )
        self.assertIn("训练强度决定权归还麦珂·杰森", result["summary"])
        self.assertIn(
            "训练强度决定权归还麦珂·杰森",
            result["events"][0]["outcome"],
        )

    def test_heuristic_extracts_direct_suspension_and_custody_transfer(self):
        result = extract_chapter_memory(
            6,
            (
                "康拉德伸手想拿回领用簿，现场负责人一直看着他。"
                "负责人宣布：“即刻暂停你的职务。”"
                "康拉德交出钥匙。"
                "负责人确认：“药品保管权归麦珂·杰森。”"
                "麦珂接过钥匙。"
            ),
            known_names=["麦珂·杰森", "康拉德·莫里森"],
            llm_call=None,
        )
        changes = {
            (item["character"], item["field"], item["new_value"])
            for item in result["state_changes"]
        }
        self.assertIn(("康拉德·莫里森", "occupation", "停职"), changes)
        self.assertIn(("麦珂·杰森", "possession", "药品保管权"), changes)
        self.assertIn("即刻暂停你的职务", result["summary"])
        self.assertIn("药品保管权归麦珂·杰森", result["summary"])
        self.assertIn("即刻暂停你的职务", result["events"][0]["outcome"])
        self.assertIn("药品保管权归麦珂·杰森", result["events"][0]["outcome"])

    def test_rebirth_awakening_does_not_mark_previous_life_death_as_current(self):
        result = extract_chapter_memory(
            2,
            (
                "最后一口气断掉的窒息感还压在胸口，麦珂·杰森猛然惊醒。"
                "上一世死亡的记忆仍然清楚，他核对日期，确认自己回到了发布会之前。"
                "麦珂·杰森重生了，距离上一世死亡还有一百零七天。"
                "他当场拒绝康拉德·莫里森端来的针剂，第三方医疗团队封存针剂，"
                "医疗双签已经生效，康拉德·莫里森失去单方注射权。"
            ),
            known_names=["麦珂·杰森", "康拉德·莫里森"],
            llm_call=None,
        )
        deaths = [
            item
            for item in result["state_changes"]
            if item["field"] == "life_status" and item["new_value"] == "dead"
        ]
        self.assertEqual([], deaths)
        changes = {
            (item["character"], item["field"], item["new_value"])
            for item in result["state_changes"]
        }
        self.assertIn(
            ("麦珂·杰森", "possession", "医疗双签与本人同意权"),
            changes,
        )
        self.assertIn(
            ("康拉德·莫里森", "possession", "无单方注射权"),
            changes,
        )
        self.assertEqual("chapter_event", result["events"][0]["type"])
        self.assertEqual("current", result["events"][0]["timeline"])

    def test_heuristic_extracts_termination_retention_and_distribution_loss(self):
        result = extract_chapter_memory(
            4,
            (
                "现场人事负责人当场收回调度助理的工作证，宣布解除其职务。"
                "调度助理伸手想拿回工作证：“不能因为一张假表就开除我！”"
                "卡尔·霍尔特仍站在原位，勉强维持着总监的姿态。"
                "“你仍是巡演总监。”麦珂·杰森说。"
                "卡尔·霍尔特下颌绷紧。"
                "他亲眼看着调度助理被开除，也失去了排练表分发权。"
            ),
            known_names=["麦珂·杰森", "卡尔·霍尔特"],
            llm_call=None,
        )
        changes = {
            (item["character"], item["field"], item["new_value"])
            for item in result["state_changes"]
        }
        self.assertIn(("调度助理", "occupation", "开除"), changes)
        self.assertIn(("卡尔·霍尔特", "occupation", "巡演总监"), changes)
        self.assertIn(("卡尔·霍尔特", "possession", "无排练表分发权"), changes)
        self.assertIn("调度助理", {item["name"] for item in result["characters"]})
        self.assertIn("调度助理已被开除", result["events"][0]["outcome"])
        self.assertIn("卡尔·霍尔特仍任巡演总监", result["events"][0]["outcome"])
        self.assertIn("卡尔·霍尔特失去排练表分发权", result["events"][0]["outcome"])
        self.assertNotIn("不能因为一张假表", result["events"][0]["outcome"])

    def test_heuristic_outcome_keeps_schedule_freeze_and_both_sides_of_right_transfer(self):
        result = extract_chapter_memory(
            8,
            (
                "新增演出被否决，后续超载排期全部冻结。"
                "卡尔·霍尔特失去排期签批权。"
                "麦珂·杰森取得强制恢复日与最终排期否决权。"
            ),
            known_names=["麦珂·杰森", "卡尔·霍尔特"],
            llm_call=None,
        )
        outcome = result["events"][0]["outcome"]
        self.assertIn("后续超载排期全部冻结", outcome)
        self.assertIn("卡尔·霍尔特失去排期签批权", outcome)
        self.assertIn("麦珂·杰森取得强制恢复日与最终排期否决权", outcome)

    def test_dead_character_cannot_act_later(self):
        prior = memory(5, state_changes=[{
            "character": "Arthur Cole", "field": "life_status", "new_value": "dead",
            "evidence": "Arthur died on stage.", "permanent": True,
        }])
        candidate = memory(25, characters=[{
            "name": "Arthur Cole", "mention_mode": "active", "evidence": "Arthur signed the contract.",
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertIn("DEAD_CHARACTER_ACTIVE", {v.code for v in violations})

    def test_dead_character_may_appear_in_memory(self):
        prior = memory(5, state_changes=[{
            "character": "Arthur Cole", "field": "life_status", "new_value": "dead",
        }])
        candidate = memory(25, characters=[{
            "name": "Arthur Cole", "mention_mode": "memory", "evidence": "She remembered his last audition.",
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertNotIn("DEAD_CHARACTER_ACTIVE", {v.code for v in violations})

    def test_event_participant_mode_is_enforced(self):
        prior = memory(5, state_changes=[{
            "character": "Arthur Cole", "field": "life_status", "new_value": "dead",
        }])
        candidate = memory(25, events=[{
            "summary": "Arthur confronts the producer", "participants": [{"name": "Arthur Cole", "mode": "active"}],
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertIn("DEAD_CHARACTER_ACTIVE", {v.code for v in violations})

    def test_illegal_resurrection_is_rejected(self):
        prior = memory(5, state_changes=[{
            "character": "Arthur Cole", "field": "life_status", "new_value": "dead",
        }])
        candidate = memory(25, state_changes=[{
            "character": "Arthur Cole", "field": "life_status", "old_value": "dead", "new_value": "alive",
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertIn("ILLEGAL_RESURRECTION", {v.code for v in violations})

    def test_previous_life_death_does_not_kill_reborn_current_self(self):
        prior = memory(1, narrative_timeline="previous_life", state_changes=[{
            "character": "Maya Reed", "field": "life_status", "new_value": "dead",
            "timeline": "previous_life",
        }])
        candidate = memory(2, narrative_timeline="current", characters=[{
            "name": "Maya Reed", "mention_mode": "active", "evidence": "Maya wakes in 1994.",
        }], state_changes=[{
            "character": "Maya Reed", "field": "life_status", "new_value": "alive", "timeline": "current",
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertNotIn("DEAD_CHARACTER_ACTIVE", {v.code for v in violations})
        self.assertNotIn("ILLEGAL_RESURRECTION", {v.code for v in violations})

    def test_dead_character_can_act_inside_explicit_previous_life_event(self):
        prior = memory(10, state_changes=[{
            "character": "Arthur Cole", "field": "life_status", "new_value": "dead", "timeline": "current",
        }])
        candidate = memory(20, narrative_timeline="mixed", events=[{
            "summary": "Arthur confronts the producer years earlier", "timeline": "previous_life",
            "participants": [{"name": "Arthur Cole", "mode": "active"}],
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertNotIn("DEAD_CHARACTER_ACTIVE", {v.code for v in violations})

    def test_latest_fact_wins_and_is_rendered_as_hard_constraint(self):
        memories = [
            memory(3, state_changes=[{"character": "Maya Reed", "field": "occupation", "new_value": "assistant"}]),
            memory(8, state_changes=[{"character": "Maya Reed", "field": "occupation", "new_value": "studio president"}]),
            memory(9, state_changes=[{"character": "Arthur Cole", "field": "life_status", "new_value": "dead"}]),
        ]
        state = build_story_state(memories)
        occupations = [x for x in state["states"] if x["character"] == "Maya Reed" and x["field"] == "occupation"]
        self.assertEqual("studio president", occupations[0]["new_value"])
        rendered = render_story_constraints(state, 10)
        self.assertIn("Arthur Cole.life_status = dead", rendered)
        self.assertIn("只能以回忆/梦境/转述出现", rendered)

    def test_multiple_possession_rights_survive_as_independent_state_slots(self):
        memories = [
            memory(3, state_changes=[{
                "character": "卡尔·霍尔特",
                "field": "possession",
                "new_value": "无排练群发布权限",
                "evidence": "排练群发布人改成麦珂本人",
            }]),
            memory(4, state_changes=[{
                "character": "卡尔·霍尔特",
                "field": "possession",
                "new_value": "无排练表分发权",
                "evidence": "卡尔失去排练表分发权",
            }]),
        ]
        state = build_story_state(memories)
        rights = {
            item["state_key"]: item["new_value"]
            for item in state["states"]
            if item["character"] == "卡尔·霍尔特"
        }
        self.assertEqual(
            {
                "possession:rehearsal_group_publish": "无排练群发布权限",
                "possession:rehearsal_table_distribute": "无排练表分发权",
            },
            rights,
        )
        rendered = render_story_constraints(state, 5)
        self.assertIn("无排练群发布权限", rendered)
        self.assertIn("无排练表分发权", rendered)

    def test_neo4j_fact_rows_keep_multiple_possessions_but_latest_each_slot(self):
        rows = [
            {"subject": "卡尔·霍尔特", "predicate": "possession", "object": "无排练表分发权", "chapter": 4, "evidence": "失去排练表分发权"},
            {"subject": "卡尔·霍尔特", "predicate": "possession", "object": "无排练群发布权限", "chapter": 3, "evidence": "排练群发布人改成麦珂本人"},
            {"subject": "卡尔·霍尔特", "predicate": "possession", "object": "排练群发布权限", "chapter": 2, "evidence": "原先掌握排练群发布"},
        ]
        latest = _latest_current_fact_rows(rows)
        self.assertEqual(2, len(latest))
        self.assertEqual(
            {
                "possession:rehearsal_table_distribute",
                "possession:rehearsal_group_publish",
            },
            {row["state_key"] for row in latest},
        )
        group = next(
            row for row in latest
            if row["state_key"] == "possession:rehearsal_group_publish"
        )
        self.assertEqual(3, group["chapter"])

    def test_heuristic_extracts_protagonist_group_and_table_rights(self):
        extracted = extract_chapter_memory(
            4,
            (
                "麦珂·杰森收起文件。随后，他当场收回排练群的统一发布权限，"
                "工作人员将发布人改成他本人。"
                "卡尔·霍尔特站在已经失去发布权限的群聊前。"
                "麦珂·杰森说：‘真实彩排表由我确认，分发名单也由我决定。’"
            ),
            known_names=["麦珂·杰森", "卡尔·霍尔特"],
            llm_call=None,
        )
        slots = {
            story_state_slot(item)
            for item in extracted["state_changes"]
            if item["character"] == "麦珂·杰森"
        }
        self.assertTrue({
            "possession:rehearsal_group_publish",
            "possession:rehearsal_table_confirm",
            "possession:rehearsal_table_distribute",
        }.issubset(slots))
        opponent_slots = {
            story_state_slot(item)
            for item in extracted["state_changes"]
            if item["character"] == "卡尔·霍尔特"
        }
        self.assertEqual({"possession:rehearsal_group_publish"}, opponent_slots)
        self.assertEqual(
            "rehearsal_audio_publish",
            canonical_possession_key("后续排练原声发布权"),
        )

    def test_sidecar_replacement_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            save_memory_file(root, memory(5, summary="old"))
            save_memory_file(root, memory(5, summary="new"))
            loaded = load_memory_files(root)
            self.assertEqual(1, len(loaded))
            self.assertEqual("new", loaded[0]["summary"])

    def test_coordinator_round_trip_injects_and_enforces_latest_state(self):
        outputs = iter([
            json.dumps({
                "narrative_timeline": "current",
                "characters": [{"name": "Maya Reed", "mention_mode": "active"}],
                "state_changes": [{
                    "character": "Maya Reed", "field": "occupation", "old_value": "assistant",
                    "new_value": "studio president", "timeline": "current", "evidence": "The board elected Maya.",
                }],
                "events": [{
                    "summary": "The board elects Maya as studio president", "timeline": "current",
                    "story_time": "1998-06-12", "outcome": "Maya takes office",
                    "participants": [{"name": "Maya Reed", "mode": "active"}],
                }],
            }),
            json.dumps({
                "narrative_timeline": "current",
                "continuity_claims": [{
                    "subject": "Maya Reed", "predicate": "occupation", "value": "junior assistant",
                    "temporal_relation": "current_before_chapter", "evidence": "Still only an assistant...",
                }],
            }),
        ])
        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = StoryMemoryCoordinator(Path(temp_dir), llm_call=lambda _: next(outputs))
            first, violations = coordinator.review_candidate(8, "The board elected Maya as studio president.")
            self.assertFalse(violations)
            coordinator.commit(first)
            self.assertIn("Maya Reed.occupation = studio president", coordinator.context_for_chapter(9))
            _, violations = coordinator.review_candidate(9, "Still only a junior assistant, Maya entered the room.")
            self.assertIn("PRIOR_STATE_CLAIM_CONFLICT", {v.code for v in violations})

    def test_prior_state_claim_must_match_latest_timeline(self):
        prior = memory(8, state_changes=[{
            "character": "Maya Reed", "field": "occupation", "new_value": "studio president",
        }])
        candidate = memory(12, continuity_claims=[{
            "subject": "Maya Reed", "predicate": "occupation", "value": "junior assistant",
            "temporal_relation": "current_before_chapter", "evidence": "As a junior assistant, Maya...",
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertIn("PRIOR_STATE_CLAIM_CONFLICT", {v.code for v in violations})

    def test_current_timeline_cannot_silently_move_backwards(self):
        prior = memory(8, events=[{
            "summary": "Maya wins the studio vote", "timeline": "current", "story_time": "1998-06-12",
        }])
        candidate = memory(9, events=[{
            "summary": "Maya attends a current-day premiere", "timeline": "current", "story_time": "1997-10-01",
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertIn("TIMELINE_REGRESSION", {v.code for v in violations})

    def test_multi_valued_access_fact_is_not_treated_as_immutable(self):
        prior = memory(1, facts=[{
            "subject": "Maya Reed", "predicate": "has_access_to", "object": "duty log",
            "timeline": "current", "permanent": True,
        }])
        candidate = memory(2, facts=[{
            "subject": "Maya Reed", "predicate": "has_access_to", "object": "navigation log",
            "timeline": "current", "permanent": True,
        }])
        codes = {v.code for v in validate_transition(build_story_state([prior]), candidate)}
        self.assertNotIn("IMMUTABLE_FACT_CONTRADICTION", codes)

    def test_short_name_resolves_to_dead_canonical_character(self):
        prior = memory(3, characters=[{"name": "马克·里德"}], state_changes=[{
            "character": "马克·里德", "field": "life_status", "new_value": "dead",
            "timeline": "current", "permanent": True,
        }])
        candidate = memory(4, characters=[{
            "name": "马克", "mention_mode": "active", "evidence": "马克走进机舱。",
        }])
        codes = {v.code for v in validate_transition(build_story_state([prior]), candidate)}
        self.assertIn("DEAD_CHARACTER_ACTIVE", codes)

    def test_incomplete_llm_extraction_is_a_hard_violation(self):
        incomplete = json.dumps({
            "narrative_timeline": "current",
            "characters": [{"name": "Maya Reed", "mention_mode": "active"}],
        })
        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = StoryMemoryCoordinator(Path(temp_dir), llm_call=lambda _: incomplete)
            _, violations = coordinator.review_candidate(2, "Maya entered the boardroom and signed the contract.")
        self.assertIn("EXTRACTION_INCOMPLETE", {v.code for v in violations})

    def test_explicit_previous_life_chapter_cannot_pollute_current_state(self):
        extracted = json.dumps({
            "narrative_timeline": "current",
            "summary": "Arthur dies in the failed previous life.",
            "characters": [{"name": "Arthur Cole", "mention_mode": "active"}],
            "events": [{"summary": "Arthur dies", "timeline": "current"}],
            "state_changes": [{
                "character": "Arthur Cole", "field": "life_status", "new_value": "dead",
                "timeline": "current", "permanent": True,
            }],
        })
        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = StoryMemoryCoordinator(Path(temp_dir), llm_call=lambda _: extracted)
            memory_result, violations = coordinator.review_candidate(
                1, "Arthur dies in the failed previous life.", forced_timeline="previous_life"
            )
        self.assertFalse(violations)
        self.assertEqual("previous_life", memory_result["narrative_timeline"])
        self.assertEqual("previous_life", memory_result["state_changes"][0]["timeline"])

    def test_dead_life_status_is_always_normalized_as_permanent(self):
        result = memory(3, state_changes=[{
            "character": "Arthur Cole", "field": "life_status", "new_value": "dead",
            "timeline": "current", "permanent": False,
        }])
        self.assertTrue(result["state_changes"][0]["permanent"])

    def test_flashback_may_use_an_earlier_date(self):
        prior = memory(8, events=[{
            "summary": "Maya wins the studio vote", "timeline": "current", "story_time": "1998-06-12",
        }])
        candidate = memory(9, narrative_timeline="mixed", events=[{
            "summary": "Maya remembers her first audition", "timeline": "memory", "story_time": "1991-03-01",
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertNotIn("TIMELINE_REGRESSION", {v.code for v in violations})

    def test_hostility_cannot_become_intimacy_without_transition_evidence(self):
        prior = memory(7, relationships=[{
            "subject": "Maya Reed", "object": "Victor Kane", "type": "rival", "status": "hostile",
            "timeline": "current", "evidence": "Victor framed Maya.",
        }])
        candidate = memory(20, relationships=[{
            "subject": "Maya Reed", "object": "Victor Kane", "type": "love_interest", "status": "intimacy",
            "timeline": "current", "change": "suddenly close", "evidence": "",
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertIn("ABRUPT_RELATIONSHIP_REVERSAL", {v.code for v in violations})

    def test_permanent_identity_fact_cannot_change(self):
        prior = memory(3, facts=[{
            "subject": "Maya Reed", "predicate": "biological_mother", "object": "Elena Reed",
            "timeline": "current", "permanent": True,
        }])
        candidate = memory(30, facts=[{
            "subject": "Maya Reed", "predicate": "biological_mother", "object": "Diana Cross",
            "timeline": "current", "permanent": True,
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertIn("IMMUTABLE_FACT_CONTRADICTION", {v.code for v in violations})

    def test_chapter_cannot_depend_on_an_event_that_never_happened(self):
        prior = memory(4, events=[{
            "summary": "Maya protects the original master recording", "outcome": "the master remains safe",
            "timeline": "current",
        }])
        candidate = memory(9, event_preconditions=[{
            "required_event": "Victor Kane was convicted and sent to prison",
            "evidence": "After Victor returned from prison...", "confidence": 0.95,
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertIn("MISSING_EVENT_PRECONDITION", {v.code for v in violations})

    def test_paraphrased_prior_event_is_not_rejected(self):
        prior = memory(2, events=[{
            "summary": "Maya准备采取行动以改变命运", "outcome": "决定联系Victor共同反击Elena",
            "timeline": "current",
        }])
        candidate = memory(3, event_preconditions=[{
            "required_event": "Maya已准备好采取措施对抗Elena",
            "evidence": "她按计划继续行动", "confidence": 0.95,
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertNotIn("MISSING_EVENT_PRECONDITION", {v.code for v in violations})

    def test_chapter_two_may_recall_previous_life_death_event(self):
        prior = memory(1, narrative_timeline="previous_life", events=[{
            "summary": "Maya Reed在片场外被失控车辆撞倒并死亡",
            "outcome": "Maya Reed死亡",
            "timeline": "previous_life",
        }])
        candidate = memory(2, narrative_timeline="current", event_preconditions=[{
            "required_event": "Maya Reed被车撞",
            "timeline": "current",
            "evidence": "她惊醒时仍记得被车撞的剧痛",
            "confidence": 0.95,
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertNotIn("MISSING_EVENT_PRECONDITION", {v.code for v in violations})

    def test_current_chapter_event_is_not_treated_as_missing_prior(self):
        prior = memory(1, narrative_timeline="previous_life", events=[{
            "summary": "Maya Reed died after losing the audition",
            "outcome": "Maya Reed died",
            "timeline": "previous_life",
        }])
        candidate = memory(
            2,
            narrative_timeline="current",
            events=[{
                "summary": "Maya has returned to the night before the audition",
                "outcome": "Maya confirms that she was reborn",
                "timeline": "current",
            }],
            event_preconditions=[{
                "required_event": "Maya has returned to the night before the audition",
                "timeline": "current",
                "evidence": "The phone date confirms where she has returned",
                "confidence": 0.95,
            }],
        )
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertNotIn("MISSING_EVENT_PRECONDITION", {v.code for v in violations})

    def test_paraphrased_current_audition_is_not_treated_as_missing_prior(self):
        candidate = memory(
            4,
            events=[{
                "summary": "Maya Reed完成关键片段的即兴表演",
                "outcome": "选角导演认可她的试戏表现",
                "timeline": "current",
            }],
            event_preconditions=[{
                "required_event": "Maya Reed参加试镜并展示出色表现",
                "timeline": "current",
                "evidence": "她收住最后一个动作，试戏室安静下来",
                "confidence": 0.95,
            }],
        )
        violations = validate_transition(build_story_state([]), candidate)
        self.assertNotIn("MISSING_EVENT_PRECONDITION", {v.code for v in violations})

    def test_equivalent_bilingual_health_state_is_not_a_conflict(self):
        prior = memory(2, state_changes=[{
            "character": "Maya Reed", "field": "health", "new_value": "稳定", "timeline": "current",
        }])
        candidate = memory(4, continuity_claims=[{
            "subject": "Maya Reed", "predicate": "health", "value": "stable",
            "temporal_relation": "current_before_chapter", "evidence": "Maya remained stable",
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertNotIn("PRIOR_STATE_CLAIM_CONFLICT", {v.code for v in violations})

    def test_occupation_parenthetical_status_is_not_a_new_job(self):
        prior = memory(2, state_changes=[{
            "character": "Maya Reed", "field": "occupation",
            "new_value": "演员（尝试重新规划事业）", "timeline": "current",
        }])
        candidate = memory(3, continuity_claims=[{
            "subject": "Maya Reed", "predicate": "occupation", "value": "演员",
            "temporal_relation": "current_before_chapter", "evidence": "Maya作为演员参加试镜",
        }])
        violations = validate_transition(build_story_state([prior]), candidate)
        self.assertNotIn("PRIOR_STATE_CLAIM_CONFLICT", {v.code for v in violations})

    def test_english_death_fallback_survives_llm_outage(self):
        extracted = extract_chapter_memory(
            5,
            "At the premiere Arthur Cole collapsed. Paramedics pronounced Arthur Cole dead at 11:42 p.m.",
            known_names=["Arthur Cole"],
            llm_call=lambda _: (_ for _ in ()).throw(ConnectionError("offline")),
        )
        changes = extracted["state_changes"]
        self.assertEqual("dead", changes[0]["new_value"])
        self.assertEqual("current", changes[0]["timeline"])


if __name__ == "__main__":
    unittest.main()

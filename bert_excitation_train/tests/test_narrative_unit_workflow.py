import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bert_excitation_train.scripts.v2 import generate_chapter_content_v2 as chapter_v2


class NarrativeUnitPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        clusters_path = (
            Path(__file__).resolve().parents[1]
            / "outputs_pop_king_v2"
            / "event_clusters_v2.json"
        )
        cls.clusters = json.loads(clusters_path.read_text(encoding="utf-8"))
        cards = chapter_v2._build_cards_from_clusters(cls.clusters)
        cls.cards = chapter_v2._enrich_cards_with_cluster_milestones(
            cards,
            cls.clusters,
        )

    def test_front_twenty_plans_have_one_result_and_valid_budgets(self):
        for chapter in range(5, 21):
            with self.subTest(chapter=chapter):
                card = self.cards[chapter]
                plan = chapter_v2._compile_narrative_unit_plan(chapter, card)
                self.assertIn(len(plan), {6, 7})
                self.assertEqual(1, sum(bool(unit["result_allowed"]) for unit in plan))
                separators = max(0, len(plan) - 1) * 2
                self.assertGreaterEqual(
                    sum(int(unit["target_min_chars"]) for unit in plan) + separators,
                    1750,
                )
                self.assertLessEqual(
                    sum(int(unit["target_max_chars"]) for unit in plan) + separators,
                    1950,
                )
                self.assertTrue(
                    all(
                        int(unit["target_min_chars"])
                        <= int(unit["target_max_chars"])
                        for unit in plan
                    )
                )

                result = str(
                    chapter_v2._compile_grounded_prose_spine(
                        chapter,
                        card,
                    ).get("result")
                    or ""
                )
                self.assertTrue(result)
                self.assertEqual(
                    1,
                    sum(
                        result in "\n".join(unit["locked_facts"])
                        for unit in plan
                    ),
                )

                memory_units = [
                    int(unit["unit_index"])
                    for unit in plan
                    if unit["memory_allowed"]
                ]
                if int(card.get("cluster_chapter_index") or 0) == 1:
                    self.assertEqual(1, len(memory_units))
                    self.assertLessEqual(memory_units[0], math.ceil(len(plan) / 3))
                else:
                    self.assertEqual([], memory_units)

    def test_causal_unit_length_can_trade_with_assembled_chapter_gate(self):
        ordinary = {"target_min_chars": 300}
        proof = {
            "target_min_chars": 300,
            "scene_archetype": "live_capability_validation",
            "functional_decision_required": True,
        }
        result = {"target_min_chars": 360, "result_allowed": True}
        self.assertEqual(4, chapter_v2._narrative_unit_minimum_tolerance(ordinary))
        self.assertEqual(45, chapter_v2._narrative_unit_minimum_tolerance(proof))
        self.assertEqual(54, chapter_v2._narrative_unit_minimum_tolerance(result))

    def test_result_units_require_the_current_authority(self):
        for chapter in range(5, 21):
            with self.subTest(chapter=chapter):
                card = self.cards[chapter]
                spine = chapter_v2._compile_grounded_prose_spine(
                    chapter,
                    card,
                )
                authority = str(spine.get("authority") or "").strip()
                result_unit = next(
                    unit
                    for unit in chapter_v2._compile_narrative_unit_plan(
                        chapter,
                        card,
                    )
                    if unit["result_allowed"]
                )
                if authority:
                    self.assertIn(authority, result_unit["required_actors"])

    def test_result_prompt_requires_authority_and_each_current_clause(self):
        chapter = 5
        card = self.cards[chapter]
        plan = chapter_v2._compile_narrative_unit_plan(chapter, card)
        result_unit = next(unit for unit in plan if unit["result_allowed"])
        prompt = chapter_v2._build_narrative_unit_prompt(
            chapter,
            card,
            result_unit,
        )
        result = str(
            chapter_v2._compile_grounded_prose_spine(
                chapter,
                card,
            ).get("result")
            or ""
        )
        for clause in (
            clause.strip()
            for clause in result.split("；")
            if clause.strip()
        ):
            self.assertIn(clause, prompt)
        self.assertIn("亲自宣布、确认、移交", prompt)
        self.assertIn(
            str(
                chapter_v2._compile_grounded_prose_spine(
                    chapter,
                    card,
                ).get("authority")
            ),
            prompt,
        )

    def test_result_only_carriers_are_not_opened_early(self):
        for chapter in range(5, 21):
            with self.subTest(chapter=chapter):
                card = self.cards[chapter]
                contract = chapter_v2._grounded_scene_contract_payload(card)
                result_only = list(
                    contract.get("result_evidence_carriers") or []
                )
                plan = chapter_v2._compile_narrative_unit_plan(chapter, card)
                result_unit = next(
                    unit for unit in plan if unit["result_allowed"]
                )
                for carrier in result_only:
                    self.assertIn(carrier, result_unit["allowed_carriers"])
                    self.assertTrue(
                        all(
                            carrier not in unit["allowed_carriers"]
                            for unit in plan
                            if not unit["result_allowed"]
                        )
                    )

    def test_chapter_five_witness_and_publicity_carrier_are_plan_locked(self):
        card = self.cards[5]
        contract = chapter_v2._grounded_scene_contract_payload(card)
        self.assertIn(
            "旧宣传页",
            contract.get("result_evidence_carriers") or [],
        )
        plan = chapter_v2._compile_narrative_unit_plan(5, card)
        witness_units = {
            int(unit["unit_index"])
            for unit in plan
            if "现场见证人" in unit["required_actors"]
        }
        self.assertEqual({2, 5}, witness_units)
        result_unit = next(unit for unit in plan if unit["result_allowed"])
        self.assertIn("旧宣传页", result_unit["allowed_carriers"])
        opening_unit = plan[0]
        self.assertNotIn("有权者", opening_unit["objective"])
        self.assertLess(
            int(opening_unit["target_max_chars"]),
            int(result_unit["target_min_chars"]),
        )
        self.assertTrue(
            all(
                "旧宣传页" not in unit["allowed_carriers"]
                for unit in plan
                if not unit["result_allowed"]
            )
        )
        prompt = chapter_v2._build_narrative_unit_prompt(
            5,
            card,
            plan[1],
            continuity_context=(
                "- [当前事实] 卡尔·霍尔特.possession = 无排练表分发权"
            ),
        )
        compact_prompt = prompt.replace("\n", "")
        self.assertIn("不得换名重新授予、撤销或结算", compact_prompt)
        self.assertIn("不得让已经失权的人无解释恢复旧权限", compact_prompt)
        self.assertIn("所有人保持原位", prompt)
        self.assertIn("测试留到后续单元才开始", prompt)

        opening_prompt = chapter_v2._build_narrative_unit_prompt(
            5,
            card,
            opening_unit,
        )
        self.assertIn("本单元只让主角与对手当面对话", opening_prompt)
        self.assertIn("现场测试尚未开始", opening_prompt)
        stakes_prompt = chapter_v2._build_narrative_unit_prompt(
            5,
            card,
            plan[2],
        )
        self.assertIn("测试仍未开始", stakes_prompt)
        self.assertIn("不得出现停一下、暂停、叫停", stakes_prompt)
        result_prompt = chapter_v2._build_narrative_unit_prompt(
            5,
            card,
            result_unit,
        )
        self.assertIn("合作方先整张撤下旧宣传页", result_prompt)
        self.assertIn("训练强度决定权归还主角", result_prompt)
        self.assertIn("本章执行卡没有医疗材料情节", result_prompt)

        chapter_five_medication_failures = (
            chapter_v2._narrative_unit_language_and_style_failures(
                "合作方忽然从桌下拿出一个药瓶。",
                card,
                result_unit,
            )
        )
        self.assertTrue(
            any("未规划的药物或包装材料" in failure for failure in chapter_five_medication_failures),
            chapter_five_medication_failures,
        )
        chapter_six_card = self.cards[6]
        chapter_six_unit = chapter_v2._compile_narrative_unit_plan(
            6,
            chapter_six_card,
        )[0]
        chapter_six_medication_failures = (
            chapter_v2._narrative_unit_language_and_style_failures(
                "康拉德·莫里森把药瓶放到当面核对处。",
                chapter_six_card,
                chapter_six_unit,
            )
        )
        self.assertFalse(
            any("未规划的药物或包装材料" in failure for failure in chapter_six_medication_failures),
            chapter_six_medication_failures,
        )

        proof_unit = plan[4]
        proof_tail = chapter_v2._narrative_unit_authority_tail_lines(
            proof_unit,
            "麦珂·杰森已经完成唱跳。现场见证人在旁边看着，合作方代表沉默。",
        )
        self.assertIn("现场见证人当面确认：“这次测试通过。”", proof_tail)
        self.assertTrue(
            chapter_v2._functional_actor_decision_present(
                "现场见证人",
                "现场见证人当面确认：“这次测试通过。”",
            )
        )
        prepared_proof = chapter_v2._ensure_required_functional_actor_actions(
            "麦珂完成唱跳。现场见证人在旁观看，合作方代表沉默。",
            proof_unit,
        )
        self.assertIn("现场见证人当面确认：“这次测试通过。”", prepared_proof)
        self.assertIn("合作方代表随即改口", prepared_proof)
        self.assertTrue(any("合作方代表随即改口" in line for line in proof_tail))

    def test_chapter_seven_hidden_schedule_unlocks_with_opponent_choice(self):
        card = self.cards[7]
        contract = chapter_v2._grounded_scene_contract_payload(card)
        opposition_carriers = list(
            contract.get("opposition_evidence_carriers") or []
        )
        hidden_schedule = next(
            carrier for carrier in opposition_carriers if "总表" in carrier
        )
        plan = chapter_v2._compile_narrative_unit_plan(7, card)
        first_allowed = next(
            int(unit["unit_index"])
            for unit in plan
            if hidden_schedule in unit["allowed_carriers"]
        )
        self.assertGreater(first_allowed, 1)
        self.assertIn("对手", plan[first_allowed - 1]["dramatic_function"])
        self.assertTrue(
            all(
                hidden_schedule
                not in "\n".join(unit["locked_facts"])
                for unit in plan[: first_allowed - 1]
            )
        )
        result_unit = next(unit for unit in plan if unit["result_allowed"])
        self.assertNotIn(
            "亲手交出隐藏总表",
            "\n".join(result_unit["locked_facts"]),
        )

    def test_chapter_nine_proof_decision_and_settlement_are_ordered(self):
        card = self.cards[9]
        spine = chapter_v2._compile_grounded_prose_spine(9, card)
        self.assertIn("沙袋提前十秒坠下", spine["evidence_result"])
        self.assertIn("叫停真人登台", spine["decision_result"])
        self.assertIn("保住所有舞者安全", spine["result"])
        self.assertNotIn("坠下", spine["result"])
        self.assertNotIn("叫停", spine["result"])

        plan = chapter_v2._compile_narrative_unit_plan(9, card)

        def first_fact_unit(fragment):
            return next(
                int(unit["unit_index"])
                for unit in plan
                if fragment in "\n".join(unit["locked_facts"])
            )

        evidence_unit = first_fact_unit("沙袋提前十秒坠下")
        decision_unit = first_fact_unit("叫停真人登台")
        settlement_unit = first_fact_unit("保住所有舞者安全")
        self.assertLess(evidence_unit, decision_unit)
        self.assertLess(decision_unit, settlement_unit)
        self.assertTrue(plan[settlement_unit - 1]["result_allowed"])

    def test_action_discovered_carrier_is_not_opened_before_action(self):
        card = self.cards[13]
        plan = chapter_v2._compile_narrative_unit_plan(13, card)
        first_hidden = next(
            int(unit["unit_index"])
            for unit in plan
            if any("隐藏条款" in carrier for carrier in unit["allowed_carriers"])
        )
        first_action = next(
            int(unit["unit_index"])
            for unit in plan
            if "查阅合同并发现隐藏条款"
            in "\n".join(unit["locked_facts"])
        )
        self.assertEqual(first_action, first_hidden)
        self.assertTrue(
            all(
                "隐藏条款" not in "\n".join(unit["locked_facts"])
                for unit in plan[: first_action - 1]
            )
        )

    def test_chapter_seventeen_bait_precedes_submitted_accounts(self):
        card = self.cards[17]
        plan = chapter_v2._compile_narrative_unit_plan(17, card)

        def first_fact_unit(fragment):
            return next(
                int(unit["unit_index"])
                for unit in plan
                if fragment in "\n".join(unit["locked_facts"])
            )

        action_unit = first_fact_unit("故意让亲属")
        exposure_unit = first_fact_unit("私人酒店账单")
        result_unit = next(
            int(unit["unit_index"])
            for unit in plan
            if unit["result_allowed"]
        )
        self.assertLess(action_unit, exposure_unit)
        self.assertLess(exposure_unit, result_unit)
        for unit in plan:
            if unit["result_allowed"]:
                continue
            prompt_material = (
                unit["objective"] + "\n" + "\n".join(unit["locked_facts"])
            )
            self.assertNotIn("驳回付款", prompt_material)
            self.assertNotIn("冻结该账户", prompt_material)
        bait_unit = plan[action_unit - 1]
        self.assertEqual([], bait_unit["allowed_carriers"])
        bait_prompt = (
            bait_unit["dramatic_function"]
            + "\n"
            + bait_unit["objective"]
        )
        self.assertNotIn("账单", bait_prompt)
        self.assertNotIn("账户", bait_prompt)
        self.assertNotIn("提交", bait_prompt)

    def test_chapter_eleven_proof_carriers_open_before_freeze(self):
        card = self.cards[11]
        spine = chapter_v2._compile_grounded_prose_spine(11, card)
        self.assertIn("实名校验", spine["evidence_result"])
        self.assertIn("异常预留票", spine["evidence_result"])
        self.assertNotIn("冻结", spine["evidence_result"])
        self.assertIn("冻结", spine["result"])

        plan = chapter_v2._compile_narrative_unit_plan(11, card)
        proof_unit = next(
            unit
            for unit in plan
            if "实名校验" in "\n".join(unit["locked_facts"])
            and not unit["result_allowed"]
        )
        self.assertTrue(
            any(
                "实名校验" in carrier or "异常预留票" in carrier
                for carrier in proof_unit["allowed_carriers"]
            )
        )

    def test_chapter_eighteen_suspension_stays_in_final_unit(self):
        card = self.cards[18]
        spine = chapter_v2._compile_grounded_prose_spine(18, card)
        self.assertNotIn("停职", spine["evidence_result"])
        self.assertIn("亲属被停职", spine["result"])
        plan = chapter_v2._compile_narrative_unit_plan(18, card)
        suspension_units = [
            unit
            for unit in plan
            if "亲属被停职" in "\n".join(unit["locked_facts"])
        ]
        self.assertEqual(1, len(suspension_units))
        self.assertTrue(suspension_units[0]["result_allowed"])

    def test_chapter_nineteen_does_not_leak_next_chapter_rights(self):
        card = self.cards[19]
        plan = chapter_v2._compile_narrative_unit_plan(19, card)
        for unit in plan:
            prompt_material = (
                unit["dramatic_function"]
                + "\n"
                + unit["objective"]
                + "\n"
                + "\n".join(unit["locked_facts"])
            )
            if not unit["result_allowed"]:
                self.assertNotIn("冻结交易", prompt_material)
            self.assertNotIn("低价打包权", prompt_material)
            self.assertNotIn("母带优先回购权", prompt_material)

    def test_media_rebuttal_uses_its_own_archetype(self):
        for chapter in (15, 16):
            with self.subTest(chapter=chapter):
                card = self.cards[chapter]
                spine = chapter_v2._compile_grounded_prose_spine(
                    chapter,
                    card,
                )
                self.assertEqual(
                    "live_capability_validation",
                    spine["scene_archetype"],
                )
                self.assertEqual(
                    "public_performance_rebuttal",
                    spine["scene_variant"],
                )
                plan = chapter_v2._compile_narrative_unit_plan(
                    chapter,
                    card,
                )
                prompt_material = "\n".join(
                    unit["objective"] for unit in plan
                )
                self.assertNotIn("降级包装成保护", prompt_material)
                self.assertNotIn("健康降级", prompt_material)

    def test_setup_result_objectives_do_not_invent_opponent_loss(self):
        plan = chapter_v2._compile_narrative_unit_plan(
            9,
            self.cards[9],
        )
        result_unit = next(unit for unit in plan if unit["result_allowed"])
        self.assertNotIn("对手现实损失", result_unit["objective"])
        self.assertNotIn("指挥权", result_unit["objective"])

    def test_non_result_prompts_do_not_receive_full_result_or_future_carriers(self):
        card = self.cards[5]
        result = str(
            chapter_v2._compile_grounded_prose_spine(5, card).get("result")
            or ""
        )
        future_terms = chapter_v2._future_milestone_materials(5, card)
        for unit in chapter_v2._compile_narrative_unit_plan(5, card):
            if unit["result_allowed"]:
                continue
            prompt = chapter_v2._build_narrative_unit_prompt(
                5,
                card,
                unit,
            )
            self.assertNotIn(result, prompt)
            for term in future_terms:
                self.assertNotIn(term, prompt)

    def test_result_aliases_preserve_exact_right_name(self):
        groups = chapter_v2._narrative_result_anchor_groups(self.cards[5])
        self.assertTrue(
            any("训练强度决定权" in group for group in groups),
            groups,
        )

    def test_cluster_opening_memory_is_bound_to_the_current_action(self):
        for chapter in range(5, 21):
            card = self.cards[chapter]
            if int(card.get("cluster_chapter_index") or 0) != 1:
                continue
            with self.subTest(chapter=chapter):
                action = str(
                    chapter_v2._compile_grounded_prose_spine(
                        chapter,
                        card,
                    ).get("action")
                    or ""
                )
                memory_unit = next(
                    unit
                    for unit in chapter_v2._compile_narrative_unit_plan(
                        chapter,
                        card,
                    )
                    if unit["memory_allowed"]
                )
                self.assertIn(action, "\n".join(memory_unit["locked_facts"]))

    def test_every_unit_prompt_hides_exact_future_material_names(self):
        for chapter in range(5, 21):
            card = self.cards[chapter]
            future_terms = chapter_v2._future_milestone_materials(
                chapter,
                card,
            )
            for unit in chapter_v2._compile_narrative_unit_plan(
                chapter,
                card,
            ):
                with self.subTest(
                    chapter=chapter,
                    unit=unit["unit_index"],
                ):
                    prompt = chapter_v2._build_narrative_unit_prompt(
                        chapter,
                        card,
                        unit,
                    )
                    for term in future_terms:
                        self.assertNotIn(term, prompt)

    def test_final_locked_result_satisfies_its_own_relation_contract(self):
        for chapter in range(5, 21):
            card = self.cards[chapter]
            result = str(
                chapter_v2._compile_grounded_prose_spine(
                    chapter,
                    card,
                ).get("result")
                or ""
            )
            groups = chapter_v2._narrative_result_anchor_groups(card)
            with self.subTest(chapter=chapter):
                self.assertTrue(result)
                self.assertTrue(groups)
                clauses = [
                    clause.strip()
                    for clause in result.split("；")
                    if clause.strip()
                ]
                self.assertEqual(len(clauses), len(groups))
                self.assertTrue(
                    all(
                        chapter_v2._settlement_relation_present(
                            result,
                            group,
                        )
                        for group in groups
                    ),
                    (result, groups),
                )
                for index, group in enumerate(groups):
                    partial = "；".join(
                        clause
                        for clause_index, clause in enumerate(clauses)
                        if clause_index != index
                    )
                    self.assertFalse(
                        chapter_v2._settlement_relation_present(
                            partial,
                            group,
                        ),
                        (result, group, partial),
                    )

    def test_non_result_objectives_are_not_misread_as_completed_settlement(self):
        for chapter in range(5, 21):
            card = self.cards[chapter]
            groups = chapter_v2._narrative_result_anchor_groups(card)
            for unit in chapter_v2._compile_narrative_unit_plan(
                chapter,
                card,
            ):
                if unit["result_allowed"]:
                    continue
                with self.subTest(
                    chapter=chapter,
                    unit=unit["unit_index"],
                ):
                    self.assertFalse(
                        any(
                            chapter_v2._settlement_relation_present(
                                unit["objective"],
                                group,
                            )
                            for group in groups
                        ),
                        unit["objective"],
                    )

    def test_media_variant_guard_is_connected_to_unit_prompt(self):
        card = self.cards[15]
        unit = next(
            unit
            for unit in chapter_v2._compile_narrative_unit_plan(15, card)
            if unit["memory_allowed"]
        )
        prompt = chapter_v2._build_narrative_unit_prompt(15, card, unit)
        self.assertIn("公开表演反卡", prompt)
        self.assertIn("公开质疑和传播话术削弱他的表达权", prompt)
        self.assertNotIn("降低标准包装成保护", prompt)


class NarrativeUnitValidatorTests(unittest.TestCase):
    def test_tiny_unit_minimum_shortfall_is_tolerated_but_real_gap_is_not(self):
        unit = {
            "target_min_chars": 334,
            "target_max_chars": 373,
            "allowed_cast": [],
            "required_actors": [],
            "allowed_carriers": [],
            "required_carriers": [],
            "all_chapter_carriers": [],
            "required_semantic_anchors": [],
            "memory_allowed": False,
            "result_allowed": False,
        }
        with patch.object(
            chapter_v2,
            "_scene_archetype_grounding_failures",
            return_value=[],
        ), patch.object(
            chapter_v2,
            "_unknown_named_roles_in_synopsis",
            return_value=[],
        ):
            near_failures = chapter_v2._validate_narrative_unit(
                ("甲" * 332) + "。",
                unit,
                {},
            )
            short_failures = chapter_v2._validate_narrative_unit(
                ("甲" * 319) + "。",
                unit,
                {},
            )
        self.assertFalse(any("少于预算" in failure for failure in near_failures))
        self.assertTrue(any("少于预算" in failure for failure in short_failures))

    def test_allowed_middle_dot_name_followed_by_action_is_not_new_person(self):
        unit = {
            "target_min_chars": 1,
            "target_max_chars": 1000,
            "allowed_cast": ["麦珂·杰森", "卡尔·霍尔特"],
            "required_actors": [],
            "allowed_carriers": [],
            "required_carriers": [],
            "all_chapter_carriers": [],
            "required_semantic_anchors": [],
            "memory_allowed": False,
            "result_allowed": False,
        }
        card = {
            "canonical_cast": [
                {"name": "麦珂·杰森"},
                {"name": "卡尔·霍尔特"},
            ]
        }
        with patch.object(
            chapter_v2,
            "_scene_archetype_grounding_failures",
            return_value=[],
        ):
            allowed_failures = chapter_v2._validate_narrative_unit(
                "卡尔·霍尔特忽然开口，麦珂·杰森没有退让。",
                unit,
                card,
            )
            invented_failures = chapter_v2._validate_narrative_unit(
                "罗伯·福特走进房间，麦珂·杰森没有退让。",
                unit,
                card,
            )
            drift_failures = chapter_v2._validate_narrative_unit(
                "卡尔·霍尔特森走进房间，麦珂·杰森没有退让。",
                unit,
                card,
            )
        self.assertFalse(
            any("具名人物" in failure for failure in allowed_failures)
        )
        self.assertTrue(
            any("罗伯·福特" in failure for failure in invented_failures)
        )
        self.assertTrue(
            any("卡尔·霍尔特森" in failure for failure in drift_failures)
        )

    def test_incomplete_unit_ending_is_rejected(self):
        unit = {
            "target_min_chars": 1,
            "target_max_chars": 1000,
            "allowed_cast": [],
            "required_actors": [],
            "allowed_carriers": [],
            "required_carriers": [],
            "all_chapter_carriers": [],
            "required_semantic_anchors": [],
            "memory_allowed": False,
            "result_allowed": False,
        }
        with patch.object(
            chapter_v2,
            "_scene_archetype_grounding_failures",
            return_value=[],
        ):
            failures = chapter_v2._validate_narrative_unit(
                "他抬头看向门外却没有把话说完",
                unit,
                {},
            )
        self.assertTrue(any("完整句" in failure for failure in failures))

    def test_carrier_matching_distinguishes_document_from_embedded_object(self):
        self.assertFalse(
            chapter_v2._same_scene_carrier(
                "控制器",
                "控制器操作日志",
            )
        )
        self.assertTrue(
            chapter_v2._same_scene_carrier(
                "等重沙袋",
                "沙袋",
            )
        )

    def test_future_aliases_do_not_ban_current_qualified_carriers(self):
        cases = (
            (
                "他按下控制器，先停住升降台。",
                ["控制器操作日志"],
                ["控制器"],
                [],
            ),
            (
                "控制器操作日志已经摆到桌上。",
                ["控制器操作日志"],
                ["控制器"],
                ["控制器操作日志"],
            ),
            (
                "星火确认异常预留票仍被冻结。",
                ["黄牛预留票"],
                ["异常预留票"],
                [],
            ),
            (
                "主办方拿出黄牛预留票。",
                ["黄牛预留票"],
                ["异常预留票"],
                ["黄牛预留票"],
            ),
            (
                "母带仍留在现场，没有发生权利交接。",
                ["母带优先回购权"],
                ["母带"],
                [],
            ),
        )
        for text, future, current, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    expected,
                    chapter_v2._future_material_hits(
                        text,
                        future,
                        current,
                    ),
                )

    def test_graph_context_filter_uses_the_same_future_alias_contract(self):
        context = (
            "已发生事实：卡尔按下控制器，麦珂叫停升降台。\n"
            "后续草稿：控制器操作日志已经调出。"
        )
        filtered = chapter_v2._body_safe_kg_context(
            context,
            ["控制器操作日志"],
            current_allowed_terms=["控制器", "升降台"],
        )
        self.assertIn("按下控制器", filtered)
        self.assertNotIn("控制器操作日志", filtered)

    def test_memory_scan_counts_immediate_past_timeline_continuation(self):
        memories = chapter_v2._narrative_memory_sentences(
            "上一世，异常票把真正的歌迷挡在门外。"
            "当时预留票成批流向加价转卖的人。"
            "这一回，他先要求公开核验。"
        )
        self.assertEqual(2, len(memories))
        self.assertIn("当时", memories[1])

    def test_all_required_actors_must_appear(self):
        unit = {
            "target_min_chars": 1,
            "target_max_chars": 1000,
            "allowed_cast": ["甲", "乙"],
            "required_actors": ["甲", "乙"],
            "allowed_carriers": [],
            "required_carriers": [],
            "all_chapter_carriers": [],
            "required_semantic_anchors": [],
            "memory_allowed": False,
            "result_allowed": False,
        }
        with patch.object(
            chapter_v2,
            "_scene_archetype_grounding_failures",
            return_value=[],
        ), patch.object(
            chapter_v2,
            "_unknown_named_roles_in_synopsis",
            return_value=[],
        ):
            failures = chapter_v2._validate_narrative_unit(
                "甲推开门，把决定摆到桌面上。",
                unit,
                {},
            )
        self.assertTrue(any("乙" in failure for failure in failures))

    def test_memory_unit_requires_one_short_memory_sentence(self):
        unit = {
            "target_min_chars": 1,
            "target_max_chars": 1000,
            "allowed_cast": [],
            "required_actors": [],
            "allowed_carriers": [],
            "required_carriers": [],
            "all_chapter_carriers": [],
            "required_semantic_anchors": [],
            "memory_allowed": True,
            "result_allowed": False,
        }
        with patch.object(
            chapter_v2,
            "_scene_archetype_grounding_failures",
            return_value=[],
        ):
            failures = chapter_v2._validate_narrative_unit(
                "他没有解释，只把门关上。",
                unit,
                {},
            )
        self.assertTrue(any("必须" in failure for failure in failures))

    def test_memory_unit_rejects_old_life_knowledge_inside_dialogue(self):
        unit = {
            "target_min_chars": 1,
            "target_max_chars": 1000,
            "allowed_cast": [],
            "required_actors": [],
            "allowed_carriers": [],
            "required_carriers": [],
            "all_chapter_carriers": [],
            "required_semantic_anchors": [],
            "memory_allowed": True,
            "result_allowed": False,
        }
        private_memory = (
            "上一世，对手也这样降低标准。"
            "合作方只引用眼前话术：“这是保护。”"
            "他先请合作方当面见证。"
        )
        with patch.object(
            chapter_v2,
            "_scene_archetype_grounding_failures",
            return_value=[],
        ), patch.object(
            chapter_v2,
            "_unknown_named_roles_in_synopsis",
            return_value=[],
        ):
            private_failures = chapter_v2._validate_narrative_unit(
                private_memory,
                unit,
                {},
            )
        self.assertEqual([], private_failures)
        quoted_pairs = (
            ("“", "”"),
            ("‘", "’"),
            ("「", "」"),
            ("『", "』"),
            ('"', '"'),
            ("'", "'"),
        )
        for opening, closing in quoted_pairs:
            with self.subTest(opening=opening, closing=closing), patch.object(
                chapter_v2,
                "_scene_archetype_grounding_failures",
                return_value=[],
            ), patch.object(
                chapter_v2,
                "_unknown_named_roles_in_synopsis",
                return_value=[],
            ):
                spoken_failures = chapter_v2._validate_narrative_unit(
                    f"{opening}上一世，\n对手也这样降低标准。{closing}"
                    "他先请合作方当面见证。",
                    unit,
                    {},
                )
            self.assertTrue(
                any(
                    "前世信息被写进对白" in failure
                    for failure in spoken_failures
                )
            )

    def test_narrative_unit_rejects_unbalanced_or_cross_paired_quotes(self):
        self.assertFalse(
            chapter_v2._narrative_quote_structure_invalid(
                "他回答：“这只是‘保护’。”"
            )
        )
        for text in (
            "他回答：“只按现场判断。",
            "他回答：”只按现场判断。“",
            "他回答：“只按现场判断。』",
            '他回答："只按现场判断。',
        ):
            with self.subTest(text=text):
                self.assertTrue(
                    chapter_v2._narrative_quote_structure_invalid(text)
                )

    def test_conditional_loss_is_not_treated_as_completed_result(self):
        self.assertFalse(
            chapter_v2._settlement_relation_present(
                "如果对手得逞，他会失去训练强度决定权。",
                ["训练强度决定权"],
            )
        )

    def test_live_validation_rejects_graph_rights_and_unplanned_execution_drift(self):
        card = {
            "chapter_id": 5,
            "chapter_milestone": {
                "action": "在合作方与独立现场见证人在场时做高强度唱跳连测",
                "opponent_reaction": "卡尔·霍尔特试图降低强度",
                "result": (
                    "麦珂完成高强度唱跳连测，合作方撤下病弱降配宣传，"
                    "他收回训练强度决定权"
                ),
            },
            "canonical_cast": [
                {"name": "麦珂·杰森", "alignment": "protagonist"},
                {"name": "卡尔·霍尔特", "alignment": "opponent"},
            ],
            "main_opponent": "卡尔·霍尔特",
            "_prior_current_right_states": [
                {
                    "character": "麦珂·杰森",
                    "field": "possession",
                    "new_value": "真实彩排表确认权",
                    "evidence": "真实彩排表由麦珂确认",
                },
                {
                    "character": "麦珂·杰森",
                    "field": "possession",
                    "new_value": "排练群发布权限",
                    "evidence": "排练群发布人已经改成麦珂本人",
                },
                {
                    "character": "卡尔·霍尔特",
                    "field": "possession",
                    "new_value": "无排练表分发权",
                    "evidence": "卡尔失去排练表分发权",
                },
            ],
        }
        cases = (
            (
                "合作方代表说：‘排练表重拟后，由麦珂签字生效。’",
                "StoryMemory/Neo4j",
            ),
            (
                "合作方代表拨通市场部电话，要求宣传总监立即下架物料。",
                "临时创造未规划的机构",
            ),
            (
                "卡尔·霍尔特突然跨前伸手，拦住麦珂的肩膀和发力路径。",
                "触碰、逼近或阻断主角身体",
            ),
            (
                "卡尔·霍尔特迎上来，手搭在麦珂肩上，替他决定降速。",
                "触碰、逼近或阻断主角身体",
            ),
            (
                "卡尔·霍尔特把手扣在麦珂肩上，不许他继续完成。",
                "触碰、逼近或阻断主角身体",
            ),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                failures = chapter_v2._scene_archetype_grounding_failures(
                    text,
                    card,
                )
                self.assertTrue(
                    any(expected in failure for failure in failures),
                    failures,
                )
        cross_sentence = (
            "卡尔·霍尔特的右手在自己胸前抬起，最终没有作出手势。"
            "麦珂随后说明，自己的身体状态只由眼前完成证明。"
        )
        cross_failures = chapter_v2._scene_archetype_grounding_failures(
            cross_sentence,
            card,
        )
        self.assertFalse(
            any("触碰、逼近或阻断主角身体" in failure for failure in cross_failures),
            cross_failures,
        )
        self.assertTrue(
            chapter_v2._settlement_relation_present(
                "训练强度决定权已经交还给他。",
                ["训练强度决定权"],
            )
        )
        self.assertFalse(
            chapter_v2._settlement_relation_present(
                "合作方说明天撤下病弱降配宣传。",
                ["病弱降配宣传"],
            )
        )

    def test_graph_right_transition_gate_allows_neutral_reference_and_new_audio_right(self):
        prior = [
            {
                "character": "麦珂·杰森",
                "field": "possession",
                "new_value": "真实彩排表确认权",
                "evidence": "真实彩排表由麦珂确认",
            },
            {
                "character": "麦珂·杰森",
                "field": "possession",
                "new_value": "排练群发布权限",
                "evidence": "发布人已经改成麦珂本人",
            },
        ]
        chapter5 = {
            "chapter_id": 5,
            "chapter_milestone": {
                "action": "现场高强度唱跳连测",
                "opponent_reaction": "卡尔要求降低强度",
                "result": "麦珂收回训练强度决定权",
            },
            "scene_contract": {"scene_archetype": "live_capability_validation"},
            "_prior_current_right_states": prior,
        }
        neutral_failures = chapter_v2._scene_archetype_grounding_failures(
            "真实彩排表仍由麦珂按前章状态确认，本章不作变更。",
            chapter5,
        )
        self.assertFalse(
            any("已生效的独立权利" in failure for failure in neutral_failures),
            neutral_failures,
        )

        chapter16 = {
            "chapter_id": 16,
            "chapter_milestone": {
                "action": "麦珂在公开排练中完整演绎歌曲",
                "opponent_reaction": "媒体试图中断拍摄",
                "result": "造谣账号撤回指控，麦珂取得后续排练原声发布权",
            },
            "scene_contract": {"scene_archetype": "public_performance_rebuttal"},
            "_prior_current_right_states": prior,
        }
        legal = chapter_v2._scene_archetype_grounding_failures(
            "合作方宣布麦珂取得后续排练原声发布权。",
            chapter16,
        )
        self.assertFalse(
            any("已生效的独立权利" in failure for failure in legal),
            legal,
        )
        repeated = chapter_v2._scene_archetype_grounding_failures(
            "合作方同时重新授予麦珂排练群发布权限。",
            chapter16,
        )
        self.assertTrue(
            any("已生效的独立权利" in failure for failure in repeated),
            repeated,
        )

    def test_result_authority_must_decide_or_execute(self):
        card = {
            "chapter_id": 5,
            "chapter_milestone": {
                "action": "主角公开验证训练能力",
                "opponent_reaction": "对手当面阻拦",
                "result": (
                    "合作方撤下病弱降配宣传；"
                    "麦珂·杰森收回训练强度决定权"
                ),
            },
            "canonical_cast": [
                {"name": "麦珂·杰森", "alignment": "protagonist"},
                {"name": "卡尔·霍尔特", "alignment": "opponent"},
            ],
            "main_opponent": "卡尔·霍尔特",
        }
        unit = {
            "target_min_chars": 1,
            "target_max_chars": 1000,
            "allowed_cast": ["麦珂·杰森", "卡尔·霍尔特"],
            "required_actors": [
                "麦珂·杰森",
                "卡尔·霍尔特",
                "合作方",
            ],
            "allowed_carriers": [],
            "required_carriers": [],
            "all_chapter_carriers": [],
            "required_semantic_anchors": [],
            "memory_allowed": False,
            "result_allowed": True,
            "dramatic_function": "结果生效与锋利收束",
        }
        passive = (
            "合作方全程看着。麦珂·杰森宣布撤下病弱降配宣传，"
            "并收回训练强度决定权。卡尔·霍尔特只能沉默。"
        )
        active = (
            "合作方代表当场撤下病弱降配宣传，并宣布："
            "“训练强度决定权归还麦珂·杰森。”"
            "卡尔·霍尔特只能沉默。"
        )
        with patch.object(
            chapter_v2,
            "_scene_archetype_grounding_failures",
            return_value=[],
        ), patch.object(
            chapter_v2,
            "_unknown_named_roles_in_synopsis",
            return_value=[],
        ):
            passive_failures = chapter_v2._validate_narrative_unit(
                passive,
                unit,
                card,
            )
            active_failures = chapter_v2._validate_narrative_unit(
                active,
                unit,
                card,
            )
        self.assertTrue(
            any("有权者" in failure for failure in passive_failures)
        )
        self.assertEqual([], active_failures)

    def test_live_validation_result_shaper_realizes_both_locked_settlements(self):
        card = {
            "chapter_id": 5,
            "scene_contract": {
                "scene_archetype": "live_capability_validation",
            },
            "chapter_milestone": {
                "action": "主角公开验证训练能力",
                "opponent_reaction": "卡尔·霍尔特口头要求降速",
                "result": (
                    "合作方撤下病弱降配宣传；"
                    "麦珂·杰森收回训练强度决定权"
                ),
            },
        }
        unit = {
            "result_allowed": True,
            "scene_archetype": "live_capability_validation",
            "allowed_cast": ["麦珂·杰森", "卡尔·霍尔特"],
            "required_actors": ["麦珂·杰森", "卡尔·霍尔特", "合作方"],
        }
        shaped = chapter_v2._ensure_result_unit_settlements(
            "卡尔·霍尔特沉默下来。麦珂·杰森等着合作方作出决定。",
            unit,
            card,
        )
        self.assertIn("合作方代表收回旧宣传页", shaped)
        self.assertIn("病弱降配宣传立即终止", shaped)
        self.assertIn("训练强度决定权归还麦珂·杰森", shaped)
        for group in chapter_v2._narrative_result_anchor_groups(card):
            self.assertTrue(
                chapter_v2._settlement_relation_present(shaped, group),
                group,
            )
        self.assertTrue(
            chapter_v2._functional_actor_decision_present("合作方", shaped)
        )

    def test_live_validation_rejects_witness_as_training_right_recipient(self):
        card = {
            "chapter_id": 5,
            "scene_contract": {
                "scene_archetype": "live_capability_validation",
            },
            "chapter_milestone": {
                "action": "主角公开验证训练能力",
                "opponent_reaction": "卡尔要求降速",
                "result": "麦珂收回训练强度决定权",
            },
        }
        failures = chapter_v2._scene_archetype_grounding_failures(
            "麦珂宣布把强度裁量权移交给现场见证人。",
            card,
        )
        self.assertTrue(
            any("训练权利受让人" in failure for failure in failures),
            failures,
        )

    def test_result_shaper_recognizes_destroyed_old_publicity_page(self):
        card = {
            "chapter_id": 5,
            "scene_contract": {
                "scene_archetype": "live_capability_validation",
            },
            "chapter_milestone": {
                "action": "主角公开验证训练能力",
                "opponent_reaction": "卡尔要求降速",
                "result": (
                    "合作方撤下病弱降配宣传；"
                    "麦珂收回训练强度决定权"
                ),
            },
        }
        unit = {
            "result_allowed": True,
            "scene_archetype": "live_capability_validation",
            "allowed_cast": ["麦珂"],
            "required_actors": ["合作方"],
        }
        original = "合作方撕毁旧宣传页，并宣布训练强度决定权归还麦珂。"
        shaped = chapter_v2._ensure_result_unit_settlements(original, unit, card)
        self.assertEqual(original, shaped)

    def test_unit_local_language_and_micro_action_gate_prevents_late_chapter_failure(self):
        mechanical = (
            "卡尔抬手搭在肩上。麦珂指尖一顿。卡尔掌心压住衣料。"
            "麦珂脚尖挪开。卡尔喉结滚动。麦珂吸气又吐气。"
            "两人只在原地反复交换这些动作。"
        )
        failures = chapter_v2._narrative_unit_language_and_style_failures(
            mechanical,
            {},
        )
        self.assertTrue(any("微动作清单" in failure for failure in failures))
        latin_failures = chapter_v2._narrative_unit_language_and_style_failures(
            "卡尔提出A组改成B组，麦珂拒绝。",
            {},
        )
        self.assertTrue(any("字母编号" in failure for failure in latin_failures))

    def test_results_first_mode_releases_style_but_keeps_continuity_failures(self):
        failures = [
            "叙事单元把过多句子写成手脚、呼吸或站位的微动作清单。",
            "能力验真靠危险特技堆高难度：跃起。",
            "叙事单元提前使用后续里程碑专属材料或权限：药瓶",
        ]
        with patch.dict(
            chapter_v2.os.environ,
            {"V2_RESULTS_FIRST_DELIVERY": "1"},
            clear=False,
        ):
            hard, soft = chapter_v2._partition_relaxable_delivery_failures(
                failures
            )
        self.assertEqual(1, len(hard))
        self.assertIn("提前使用后续里程碑", hard[0])
        self.assertEqual(2, len(soft))
        self.assertIn("微动作清单", soft[0])
        self.assertTrue(any("危险特技" in item for item in soft))

    def test_results_first_mode_allows_small_unit_length_drift(self):
        unit = {
            "unit_index": 2,
            "target_min_chars": 250,
            "target_max_chars": 300,
            "allowed_cast": [],
            "required_actors": [],
            "allowed_carriers": [],
            "required_carriers": [],
            "all_chapter_carriers": [],
            "required_semantic_anchors": [],
            "memory_allowed": False,
            "result_allowed": False,
        }
        card = {"canonical_cast": []}
        with patch.dict(
            chapter_v2.os.environ,
            {"V2_RESULTS_FIRST_DELIVERY": "1"},
            clear=False,
        ):
            short_failures = chapter_v2._validate_narrative_unit(
                "甲" * 224 + "。",
                unit,
                card,
            )
            long_failures = chapter_v2._validate_narrative_unit(
                "乙" * 319 + "。",
                unit,
                card,
            )
        self.assertFalse(any("少于预算下限" in item for item in short_failures))
        self.assertFalse(any("超过预算上限" in item for item in long_failures))

    def test_results_first_quality_review_can_accept_style_only_rejection(self):
        payload = {
            "accept": False,
            "scores": {
                "cluster_fidelity": 8,
                "causal_clarity": 7,
                "prose_naturalness": 6,
                "emotional_force": 6,
                "non_repetition": 6,
                "ending_precision": 6,
                "fictional_naming": 9,
            },
            "hard_failures": [{
                "code": "micro_actions",
                "evidence": "微动作和站位略多，呈现舞台调度感",
                "repair": "减少动作清单",
            }],
            "summary": "核心反杀完整，仅有文风问题",
        }
        with patch.dict(
            chapter_v2.os.environ,
            {"V2_RESULTS_FIRST_DELIVERY": "1"},
            clear=False,
        ):
            review = chapter_v2._parse_chapter_quality_review(
                json.dumps(payload, ensure_ascii=False)
            )
        self.assertIsNotNone(review)
        self.assertTrue(review["accept"])
        self.assertEqual([], review["hard_failures"])

    def test_only_the_validation_conflict_unit_may_use_pause_language(self):
        card = {
            "chapter_id": 5,
            "scene_contract": {
                "scene_archetype": "live_capability_validation",
            },
            "canonical_cast": [
                {"name": "麦珂·杰森", "alignment": "protagonist"},
                {"name": "卡尔·霍尔特", "alignment": "opponent"},
            ],
            "main_opponent": "卡尔·霍尔特",
        }
        unit = {
            "unit_index": 1,
            "target_min_chars": 1,
            "target_max_chars": 1000,
            "allowed_cast": ["麦珂·杰森", "卡尔·霍尔特"],
            "required_actors": ["麦珂·杰森", "卡尔·霍尔特"],
            "allowed_carriers": [],
            "required_carriers": [],
            "all_chapter_carriers": [],
            "required_semantic_anchors": [],
            "memory_allowed": False,
            "result_allowed": False,
            "scene_archetype": "live_capability_validation",
        }
        failures = chapter_v2._validate_narrative_unit(
            "卡尔·霍尔特把降级说成保护：‘这不是暂停。’麦珂·杰森拒绝。",
            unit,
            card,
        )
        self.assertTrue(
            any("当前单元不得提前或重复使用叫停词" in failure for failure in failures),
            failures,
        )

    def test_functional_authority_alias_is_accepted(self):
        self.assertTrue(
            chapter_v2._actor_is_mentioned(
                "从开场就在场的现场管理负责人",
                "现场负责人抬手叫停争执。",
            )
        )

    def test_functional_authority_decision_rejects_false_positives(self):
        self.assertTrue(
            chapter_v2._functional_actor_decision_present(
                "合作方",
                "合作方代表随即改口：“我们按眼前完成重新判断。”",
            )
        )
        false_positives = (
            "合作方代表全程旁观，没有改变判断。",
            "如果麦珂完成，合作方会重新判断。",
            "麦珂要求合作方继续旁观。",
            "合作方看着麦珂通过整段，始终沉默。",
            "麦珂要求合作方确认眼前结果。",
            "合作方被要求确认眼前结果。",
        )
        for text in false_positives:
            with self.subTest(text=text):
                self.assertFalse(
                    chapter_v2._functional_actor_decision_present(
                        "合作方",
                        text,
                    )
                )


class NarrativeUnitRetryTests(unittest.TestCase):
    def test_unplanned_quantitative_details_become_qualitative(self):
        card = {
            "scene_contract": {
                "scene_archetype": "live_capability_validation",
            }
        }
        normalized = chapter_v2._normalize_unplanned_quantitative_scene_details(
            "他停了三秒，又连续完成三组动作，声音低了一度。",
            card,
        )
        self.assertNotRegex(
            normalized,
            r"三秒|三组|一度",
        )
        self.assertIn("片刻", normalized)
        self.assertIn("连续几次", normalized)
        self.assertIn("些许", normalized)

    def test_performance_jargon_becomes_readable_surface_prose(self):
        card = {
            "scene_contract": {
                "scene_archetype": "live_capability_validation",
            }
        }
        normalized = chapter_v2._normalize_unplanned_quantitative_scene_details(
            "气息沉进腹腔，胸腔回响稳定，心率也没有改变。"
            "他左掌撑地起身，又腾空踢腿落地。",
            card,
        )
        self.assertNotRegex(
            normalized,
            r"腹腔|胸腔|心率|撑地|腾空",
        )
        self.assertIn("气息", normalized)
        self.assertIn("声音", normalized)
        self.assertIn("身体状态", normalized)
        self.assertIn("稳稳起身", normalized)
        self.assertIn("抬腿转身落地", normalized)

    def test_planned_quantitative_detail_is_preserved(self):
        card = {
            "chapter_milestone": {"action": "连续完成三组动作"},
            "scene_contract": {
                "scene_archetype": "live_capability_validation",
            },
        }
        normalized = chapter_v2._normalize_unplanned_quantitative_scene_details(
            "他连续完成三组动作。",
            card,
        )
        self.assertIn("三组", normalized)

    def test_missing_memory_trigger_is_supplied_once_before_current_action(self):
        unit = {"memory_allowed": True}
        card = {
            "scene_contract": {
                "scene_archetype": "live_capability_validation",
            }
        }
        seeded = chapter_v2._ensure_narrative_unit_memory_trigger(
            "他先请合作方当面见证。",
            unit,
            card,
        )
        self.assertTrue(seeded.startswith("上一世"))
        self.assertIn("主动", seeded)
        self.assertEqual(
            1,
            len(chapter_v2._narrative_memory_sentences(seeded)),
        )
        unchanged = chapter_v2._ensure_narrative_unit_memory_trigger(
            "上一世，对手也这样降低标准。他先请合作方当面见证。",
            unit,
            card,
        )
        self.assertEqual(
            "上一世，对手也这样降低标准。他先请合作方当面见证。",
            unchanged,
        )

    def test_memory_trigger_survives_trimming_when_model_puts_it_too_late(self):
        unit = {
            "memory_allowed": True,
            "target_min_chars": 40,
            "target_max_chars": 50,
        }
        raw = (
            ("甲" * 20)
            + "。"
            + ("乙" * 20)
            + "。"
            + "上一世，对手也这样降低标准。"
        )
        prepared = chapter_v2._prepare_narrative_unit_length_and_memory(
            raw,
            unit,
            {
                "scene_contract": {
                    "scene_archetype": "live_capability_validation",
                }
            },
        )
        self.assertGreaterEqual(len(prepared), 40)
        self.assertLessEqual(len(prepared), 50)
        self.assertEqual(
            1,
            len(chapter_v2._narrative_memory_sentences(prepared)),
        )
        self.assertTrue(prepared.startswith("上一世"))

    def test_required_functional_actor_is_kept_before_trim(self):
        unit = {
            "memory_allowed": True,
            "target_min_chars": 80,
            "target_max_chars": 120,
            "required_actors": ["麦珂·杰森", "合作方"],
            "dramatic_function": "主角抢先改变条件",
        }
        prepared = chapter_v2._prepare_narrative_unit_length_and_memory(
            ("麦珂·杰森先站到场地中央。" * 12),
            unit,
            {
                "scene_contract": {
                    "scene_archetype": "live_capability_validation",
                }
            },
        )
        self.assertTrue(
            chapter_v2._actor_is_mentioned("合作方", prepared)
        )
        self.assertIn("合作方代表先当面确认", prepared)
        self.assertEqual(
            1,
            len(chapter_v2._narrative_memory_sentences(prepared)),
        )
        self.assertLessEqual(len(prepared), 120)

    def test_passive_cooperation_actor_changes_judgment_after_visible_proof(self):
        raw = (
            "麦珂·杰森把演唱与舞步一气呵成，最后一个音符落下。"
            "合作方代表一直站在场边看着，没有表态。"
        )
        unit = {
            "memory_allowed": False,
            "target_min_chars": 1,
            "target_max_chars": 300,
            "allowed_cast": ["麦珂·杰森"],
            "required_actors": ["麦珂·杰森", "合作方"],
            "allowed_carriers": [],
            "required_carriers": [],
            "all_chapter_carriers": [],
            "required_semantic_anchors": ["唱跳"],
            "dramatic_function": "可见证明改变判断",
            "result_allowed": False,
        }
        prepared = chapter_v2._prepare_narrative_unit_length_and_memory(
            raw,
            unit,
            {},
        )
        self.assertTrue(prepared.startswith(raw))
        self.assertTrue(
            prepared.endswith(
                "合作方代表随即改口：“我们按眼前这次完成重新判断。”"
            )
        )
        with patch.object(
            chapter_v2,
            "_scene_archetype_grounding_failures",
            return_value=[],
        ), patch.object(
            chapter_v2,
            "_unknown_named_roles_in_synopsis",
            return_value=[],
        ):
            raw_failures = chapter_v2._validate_narrative_unit(
                raw,
                unit,
                {},
            )
            prepared_failures = chapter_v2._validate_narrative_unit(
                prepared,
                unit,
                {},
            )
        self.assertTrue(any("有权者" in failure for failure in raw_failures))
        self.assertEqual([], prepared_failures)

    def test_reversed_judgment_label_also_appends_authority_after_proof(self):
        raw = "眼前差异已经形成可见证明，现场负责人始终站在旁边。"
        unit = {
            "memory_allowed": False,
            "target_min_chars": 1,
            "target_max_chars": 200,
            "required_actors": ["现场负责人"],
            "dramatic_function": "有权者判断改变",
            "result_allowed": False,
        }
        prepared = chapter_v2._prepare_narrative_unit_length_and_memory(
            raw,
            unit,
            {},
        )
        self.assertTrue(prepared.startswith(raw))
        self.assertGreater(
            prepared.index("现场负责人当面确认"),
            prepared.index("可见证明"),
        )

    def test_sing_dance_synonym_keeps_the_authority_decision_tail(self):
        raw = (
            "麦珂·杰森把演唱与舞步一气呵成，落地后仍稳稳唱完尾句。"
            "他没有停下来解释，只把最后的判断留给现场。"
            "合作方代表当场改口，确认按眼前这次完成重新判断并准备执行。"
        )
        unit = {
            "memory_allowed": False,
            "target_min_chars": 1,
            "target_max_chars": len(raw),
            "allowed_cast": ["麦珂·杰森"],
            "required_actors": ["麦珂·杰森", "合作方"],
            "allowed_carriers": [],
            "required_carriers": [],
            "all_chapter_carriers": [],
            "required_semantic_anchors": ["唱跳"],
            "dramatic_function": "可见证明改变判断",
            "result_allowed": False,
        }
        prepared = chapter_v2._prepare_narrative_unit_length_and_memory(
            raw,
            unit,
            {},
        )
        self.assertEqual(raw, prepared)
        self.assertNotIn("唱跳", prepared)
        self.assertIn("重新判断并准备执行", prepared)
        self.assertTrue(
            chapter_v2._semantic_anchor_present("唱跳", prepared)
        )
        self.assertTrue(
            chapter_v2._semantic_anchor_present(
                "唱跳",
                "他开口唱着，舞步始终贴住节奏，最后一个音符消散。",
            )
        )
        self.assertTrue(
            chapter_v2._functional_actor_decision_present(
                "合作方",
                "合作方盯住他片刻，缓缓道：“我改主意了。”",
            )
        )
        with patch.object(
            chapter_v2,
            "_scene_archetype_grounding_failures",
            return_value=[],
        ), patch.object(
            chapter_v2,
            "_unknown_named_roles_in_synopsis",
            return_value=[],
        ):
            failures = chapter_v2._validate_narrative_unit(
                prepared,
                unit,
                {},
            )
        self.assertEqual([], failures)

    def test_auto_actor_sentence_cannot_evict_an_in_budget_ending(self):
        raw = (
            "麦珂·杰森完成当前动作。"
            "他把选择说清，最后一句保留当前单元必须留下的后果。"
        )
        unit = {
            "memory_allowed": False,
            "target_min_chars": 1,
            "target_max_chars": len(raw),
            "required_actors": ["麦珂·杰森", "合作方"],
            "dramatic_function": "主角抢先改变条件",
            "result_allowed": False,
        }
        prepared = chapter_v2._prepare_narrative_unit_length_and_memory(
            raw,
            unit,
            {},
        )
        self.assertEqual(raw, prepared)
        self.assertIn("必须留下的后果", prepared)
        self.assertNotIn("合作方代表先当面确认", prepared)

    def test_mandatory_authority_tail_survives_complete_boundary_budgeting(self):
        proof = "麦珂·杰森完成连续唱跳，现场证明已经成立。"
        complete_sentences = "".join(
            (character * 60) + "。"
            for character in ("稳", "准", "清", "定", "实")
        )
        prefix = proof + complete_sentences
        unit = {
            "memory_allowed": False,
            "target_min_chars": 348,
            "target_max_chars": 388,
            "required_actors": ["麦珂·杰森", "合作方"],
            "required_semantic_anchors": ["唱跳"],
            "dramatic_function": "可见证明改变判断",
            "functional_decision_required": True,
            "result_allowed": False,
        }
        for raw_length in (381, 423):
            with self.subTest(raw_length=raw_length):
                raw = prefix + ("余" * (raw_length - len(prefix) - 1)) + "。"
                self.assertEqual(raw_length, len(raw))
                prepared = chapter_v2._prepare_narrative_unit_length_and_memory(
                    raw,
                    unit,
                    {},
                )
                self.assertGreaterEqual(len(prepared), 348)
                self.assertLessEqual(len(prepared), 388)
                self.assertNotEqual(raw, prepared)
                self.assertIn("连续唱跳", prepared)
                self.assertTrue(
                    prepared.endswith(
                        "合作方代表随即改口：“我们按眼前这次完成重新判断。”"
                    )
                )

    def test_result_retry_feedback_keeps_the_missing_right(self):
        feedback = chapter_v2._compact_grounded_rewrite_feedback(
            [
                "结果单元没有让全部锁定处分、交接或收益实际生效："
                "训练强度决定权"
            ]
        )
        joined = "\n".join(feedback)
        self.assertIn("训练强度决定权", joined)
        self.assertIn("当前有权者", joined)
        self.assertNotIn("整章重建", joined)

    def test_retry_feedback_keeps_the_missing_functional_actor(self):
        feedback = chapter_v2._compact_grounded_rewrite_feedback(
            ["叙事单元没有让其戏剧功能要求的人物实际行动：合作方"]
        )
        joined = "\n".join(feedback)
        self.assertIn("合作方", joined)
        self.assertIn("亲自说话、确认、决定或执行", joined)
        self.assertNotIn("整章重建", joined)

    def test_retry_feedback_moves_old_life_knowledge_out_of_dialogue(self):
        feedback = chapter_v2._compact_grounded_rewrite_feedback(
            ["前世信息被写进对白；必须改成私下内心判断。"]
        )
        joined = "\n".join(feedback)
        self.assertIn("移出所有引号", joined)
        self.assertIn("私下", joined)
        self.assertNotIn("整章重建", joined)

    def test_overlong_unit_is_trimmed_only_at_complete_sentence_boundary(self):
        unit = {"target_min_chars": 10, "target_max_chars": 20}
        text = ("甲" * 12) + "。" + ("乙" * 12) + "。"
        trimmed = chapter_v2._trim_narrative_unit_to_complete_boundary(
            text,
            unit,
        )
        self.assertEqual(("甲" * 12) + "。", trimmed)

    def test_token_budget_starts_near_character_contract(self):
        unit = {"target_min_chars": 278, "target_max_chars": 310}
        budget = chapter_v2._initial_narrative_unit_max_tokens(unit)
        self.assertGreaterEqual(budget, 310)
        self.assertLess(budget, 500)

    def test_non_result_decision_unit_reserves_authority_tail_space(self):
        unit = {
            "unit_index": 5,
            "unit_count": 6,
            "dramatic_function": "可见证明改变判断",
            "objective": "证明完成后由合作方改变判断",
            "locked_facts": ["麦珂完成唱跳"],
            "allowed_cast": ["麦珂"],
            "required_actors": ["麦珂", "合作方"],
            "allowed_carriers": [],
            "required_semantic_anchors": ["唱跳"],
            "memory_allowed": False,
            "result_allowed": False,
            "functional_decision_required": True,
            "target_min_chars": 348,
            "target_max_chars": 388,
            "paragraph_mode": "证明后用短对白落锤",
        }
        generation_max = (
            chapter_v2._narrative_unit_generation_max_chars(unit)
        )
        generation_min = (
            chapter_v2._narrative_unit_generation_min_chars(unit)
        )
        self.assertEqual(28, chapter_v2._narrative_unit_authority_tail_chars(unit))
        self.assertEqual(320, generation_min)
        self.assertEqual(356, generation_max)
        prompt = chapter_v2._build_narrative_unit_prompt(5, {}, unit)
        self.assertIn("320至356字", prompt)
        self.assertIn("正式的348至388字验收", prompt)
        self.assertIn("预留空间", prompt)
        self.assertIn("可见证明", prompt)
        first_budget = chapter_v2._initial_narrative_unit_max_tokens(unit)
        stable_budget = chapter_v2._adapt_narrative_unit_max_tokens(
            first_budget,
            330,
            unit,
        )
        self.assertEqual(first_budget, stable_budget)
        adapted_budget = chapter_v2._adapt_narrative_unit_max_tokens(
            first_budget,
            380,
            unit,
        )
        self.assertLess(adapted_budget, first_budget)

        proof_prefix = "麦珂完成唱跳，眼前证明已经成立。"
        passive_raw = (
            proof_prefix
            + ("稳" * (350 - len(proof_prefix) - 1))
            + "。"
        )
        prepared = chapter_v2._prepare_narrative_unit_length_and_memory(
            passive_raw,
            unit,
            {},
        )
        fallback_line = (
            "合作方代表随即改口：“我们按眼前这次完成重新判断。”"
        )
        self.assertTrue(prepared.startswith(passive_raw))
        self.assertTrue(prepared.endswith(fallback_line))
        self.assertLessEqual(len(prepared), 388)
        self.assertNotRegex(prepared, r"撤下|归还|决定权")
        self.assertTrue(
            chapter_v2._narrative_unit_needs_authority_reserve(
                unit,
                passive_raw,
            )
        )

        active_filler = 350 - len(proof_prefix) - 2 - len(fallback_line) - 1
        active_raw = (
            proof_prefix
            + ("稳" * active_filler)
            + "。"
            + "\n\n"
            + fallback_line
        )
        self.assertEqual(350, len(active_raw))
        self.assertEqual(
            active_raw,
            chapter_v2._prepare_narrative_unit_length_and_memory(
                active_raw,
                unit,
                {},
            ),
        )
        self.assertFalse(
            chapter_v2._narrative_unit_needs_authority_reserve(
                unit,
                active_raw,
            )
        )
        self.assertEqual(
            first_budget,
            chapter_v2._adapt_narrative_unit_max_tokens(
                first_budget,
                380,
                unit,
                reserve_authority_space=False,
            ),
        )

        result_unit = {**unit, "result_allowed": True}
        self.assertEqual(
            388,
            chapter_v2._narrative_unit_generation_max_chars(result_unit),
        )
        self.assertEqual(
            348,
            chapter_v2._narrative_unit_generation_min_chars(result_unit),
        )
        result_prompt = chapter_v2._build_narrative_unit_prompt(
            5,
            {},
            result_unit,
        )
        self.assertIn("348至388字", result_prompt)
        self.assertIn("全部锁定行动与结果", result_prompt)
        self.assertNotIn("预留空间", result_prompt)

    def test_token_budget_contracts_after_overlong_retry(self):
        unit = {"target_min_chars": 278, "target_max_chars": 310}
        first = chapter_v2._initial_narrative_unit_max_tokens(unit)
        second = chapter_v2._adapt_narrative_unit_max_tokens(
            first,
            341,
            unit,
        )
        third = chapter_v2._adapt_narrative_unit_max_tokens(
            second,
            320,
            unit,
        )
        self.assertLess(second, first)
        self.assertLess(third, second)

    def test_token_budget_expands_after_short_retry(self):
        unit = {"target_min_chars": 278, "target_max_chars": 310}
        first = chapter_v2._initial_narrative_unit_max_tokens(unit)
        second = chapter_v2._adapt_narrative_unit_max_tokens(
            first,
            220,
            unit,
        )
        self.assertGreater(second, first)

    def test_token_budget_expands_after_incomplete_ending(self):
        unit = {"target_min_chars": 348, "target_max_chars": 388}
        first = 288
        second = chapter_v2._adapt_narrative_unit_max_tokens(
            first,
            369,
            unit,
            reserve_authority_space=False,
            incomplete_ending=True,
        )
        self.assertGreater(second, first)

    def test_only_failing_unit_is_retried(self):
        calls = []
        validation_calls = {}

        def fake_api(_prompt, _feedback, unit_index, **_kwargs):
            calls.append(unit_index)
            return "正文" * 150

        def fake_validate(_text, unit, _card, **_kwargs):
            index = int(unit["unit_index"])
            validation_calls[index] = validation_calls.get(index, 0) + 1
            if index == 3 and validation_calls[index] == 1:
                return ["第三单元首次失败"]
            return []

        card = {
            "chapter_id": 5,
            "cluster_chapter_index": 1,
            "chapter_milestone": {
                "action": "主角公开验证训练能力",
                "opponent_reaction": "对手当面阻拦",
                "result": "合作方撤下病弱宣传，主角收回训练强度决定权",
            },
            "canonical_cast": [
                {"name": "主角", "alignment": "protagonist"},
                {"name": "对手", "alignment": "opponent"},
            ],
            "main_opponent": "对手",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            gen = SimpleNamespace(
                outputs_dir=Path(temp_dir),
                _call_api=fake_api,
            )
            with patch.object(
                chapter_v2,
                "_validate_narrative_unit",
                side_effect=fake_validate,
            ):
                text, plan, failures = (
                    chapter_v2._generate_grounded_narrative_units(
                        gen,
                        5,
                        card,
                    )
                )
        self.assertIsNotNone(text)
        self.assertEqual([], failures)
        self.assertEqual(len(plan) + 1, len(calls))
        self.assertEqual([1, 2, 3, 3], calls[:4])
        self.assertEqual(1, calls.count(1))
        self.assertEqual(1, calls.count(2))

    def test_retry_adapts_from_raw_text_not_the_appended_authority_tail(self):
        unit = {
            "unit_index": 1,
            "unit_count": 1,
            "dramatic_function": "可见证明改变判断",
            "objective": "证明后由合作方改变判断",
            "locked_facts": ["主角完成唱跳"],
            "allowed_cast": ["主角"],
            "required_actors": ["主角", "合作方"],
            "allowed_carriers": [],
            "required_carriers": [],
            "all_chapter_carriers": [],
            "required_semantic_anchors": ["唱跳"],
            "memory_allowed": False,
            "result_allowed": False,
            "functional_decision_required": True,
            "target_min_chars": 1750,
            "target_max_chars": 1800,
            "paragraph_mode": "证明后短对白落锤",
        }
        prefix = "主角完成唱跳，眼前证明已经成立。"
        raw = prefix + ("稳" * (1750 - len(prefix) - 1)) + "。"
        token_limits = []
        validation_calls = 0

        def fake_api(_prompt, _feedback, _unit_index, **kwargs):
            token_limits.append(kwargs["max_tokens"])
            return raw

        def fake_validate(_text, _unit, _card, **_kwargs):
            nonlocal validation_calls
            validation_calls += 1
            return ["当前动作首次失败"] if validation_calls == 1 else []

        with tempfile.TemporaryDirectory() as temp_dir:
            gen = SimpleNamespace(
                outputs_dir=Path(temp_dir),
                _call_api=fake_api,
            )
            with patch.object(
                chapter_v2,
                "_compile_narrative_unit_plan",
                return_value=[unit],
            ), patch.object(
                chapter_v2,
                "_validate_narrative_unit",
                side_effect=fake_validate,
            ):
                text, plan, failures = (
                    chapter_v2._generate_grounded_narrative_units(
                        gen,
                        5,
                        {},
                    )
                )
        self.assertEqual([], failures)
        self.assertEqual([unit], plan)
        self.assertIsNotNone(text)
        self.assertEqual(2, len(token_limits))
        self.assertEqual(token_limits[0], token_limits[1])
        self.assertIn("合作方代表随即改口", text)


if __name__ == "__main__":
    unittest.main()

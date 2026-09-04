import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from bert_excitation_train.scripts.novel_generation_v2 import theme_constraints
from bert_excitation_train.scripts.knowledge_graph.story_identity import story_id_for_clusters
from bert_excitation_train.scripts.novel_generation_v2.generate_event_clusters_v2 import (
    _apply_seed_cast_to_clusters,
    _canonical_cast_from_seed_plan,
    _event_cluster_semantic_failures,
    _failures_target_only_opening_cluster,
    _failures_target_only_final_cluster,
    _fill_long_cluster_causal_fields,
    _limit_clusters_to_run,
    _long_form_focus_specs,
    _long_seed_plan_semantic_failures,
    _matching_cached_long_cluster_batch,
    _normalize_cluster_names_from_seed_plan,
    _normalize_event_cluster_shape,
    _normalize_short_event_milestones_from_seed_plan,
    _normalize_short_seed_opening_death,
    _normalize_short_seed_rebirth_deployment,
    _normalize_short_seed_terminal_summary,
    _replace_seed_plan_chapter,
    _seed_plan_chapter_sections,
    _seed_plan_semantic_failures,
    _short_event_object_shape_failures,
    _short_event_object_specs,
)
from bert_excitation_train.scripts.rag.smart_sample_search import adapt_sample_content
from bert_excitation_train.scripts.novel_generation_v2.generate_outline_from_event_clusters_v2 import (
    _build_cards_from_clusters_v2,
    _build_grounded_short_prev_life_context,
)
from bert_excitation_train.scripts.novel_generation_v2.generate_chapter_content_v2 import (
    RebirthRevengeGeneratorV2,
    _build_chapter_quality_critic_prompt,
    _build_chapter_expansion_prompt,
    _build_closed_evidence_scene_prompt,
    _build_closed_scene_micro_expansion_prompt,
    _build_closed_scene_segment_prompt,
    _closed_scene_contract_failures,
    _closed_scene_segment_candidate_failure,
    _closed_scene_segment_plan,
    _build_cards_from_clusters,
    _build_forced_medication_death_scene,
    _build_medical_double_sign_awakening_scene,
    _build_schedule_canary_scene,
    _build_overload_schedule_bait_scene,
    _build_grounded_cluster_synopsis_from_cards,
    _build_grounded_chapter_prompt,
    _append_grounded_opening_death_scene,
    _append_grounded_awakening_deployment,
    _append_grounded_actor_contract_payoff,
    _build_awakening_repair_prompt,
    _build_death_repair_prompt,
    _build_payoff_insertion_prompt,
    _build_payoff_repair_prompt,
    _build_cluster_body_part_prompt,
    _fallback_build_exec_plan_for_cluster,
    _fallback_chapter_beats,
    _future_milestone_materials,
    _derive_closed_scene_contract,
    _generic_contract_segment_fallback,
    _ground_opening_betrayal_before_home,
    _chapter_body_hard_failures,
    _chapter_rolling_critic,
    _cluster_synopsis_hard_failures,
    _cluster_critic,
    _cluster_detect_deus_ex_machina,
    _cross_chapter_prose_similarity_failures,
    _expansion_preserves_original_ending,
    _ensure_medication_audit_handover,
    _ensure_medication_audit_previous_life_motive,
    _ensure_performance_previous_life_action,
    _ensure_planned_work_title_reference,
    _enrich_cards_with_cluster_milestones,
    _has_tangible_payoff,
    _generic_prose_quality_failures,
    _insert_before_last_paragraph,
    _insert_closed_scene_micro_expansion,
    _minimum_chapter_chars,
    _parse_chapter_quality_review,
    _prose_structure_failure,
    _normalize_beats_flashback_mode,
    _normalize_exec_plan_chapters,
    _normalize_awakening_role_aliases,
    _normalize_closed_scene_surface_drift,
    _normalize_joined_canonical_names,
    _normalize_planned_work_title_aliases,
    _normalize_unplanned_named_people,
    _reflow_segmented_scene_paragraphs,
    _scene_has_payoff_authority,
    _segment_prior_prose_overlap_failure,
    _segment_semantic_repair_directive,
    _segmented_closed_scene_fill_spec,
    _select_grounded_chapter_cast,
    _shape_closed_scene_segment_candidate,
    _should_use_api_segment_recovery,
    _scene_contract_fulfillment_failures,
    _unknown_named_roles_in_synopsis,
    _validate_chapter_memory_contract,
)


class RuntimeThemeContractTests(unittest.TestCase):
    def test_long_form_blueprint_validator_accepts_non_entertainment_theme(self):
        plan = """【固定角色表】
主角：林栖
身份：冷链仓库夜班主管
核心对手：顾峤
身份：仓储公司运营负责人
关键盟友：苏砚
身份：独立安全审核员
分层反派1：唐策
身份：违规实验室承包商
分层反派2：许澄
身份：冷链调度员

第一章：上一世顾峤逼林栖进入违规实验室，唐策强行给她注射未知针剂致死，林栖当场死亡，生命结束。
第二章：林栖醒来，核对日期和仓位编号，确认重生回到事故前，立即联系苏砚预约现场安全复核。
反派设计：顾峤擅长用合规外衣掩盖恶意；唐策自作聪明，私改封签后还在交接簿上签名，留下把柄。

【八段主线推进】
第一段：林栖冻结异常货位，许澄失去夜班调度权限，林栖获得复核权限。
第二段：林栖按交接规则封存样本，唐策失去实验室临时准入，林栖取得双人验收席位。
第三段：林栖在装卸现场改变扫描顺序，顾峤的调包计划失败。
第四段：林栖建立承运人复核，收回关键路线控制。
第五段：林栖推动公开安全演练，取得停机决定的共同签字权。
第六段：顾峤亲自越权解封并留下操作记录，运营权限被限制。
第七段：林栖用今生形成的交接记录启动合规听证，取得接管资格。
第八段：经营许可复核会上完成最终双向结算。

【终局回收清单】
回收双人验收席位、停机共同签字权、今生交接记录与接管资格。
顾峤最终失去仓储经营许可并交出运营权限；林栖最终获得合法接管资格并接管冷链仓库。
"""
        self.assertEqual(
            [],
            _long_seed_plan_semantic_failures(plan, protagonists=["林栖"]),
        )

    def test_long_form_helpers_do_not_inject_current_story_topic(self):
        cluster = {
            "cluster_id": "EC08",
            "chapter_span": [14, 15],
            "main_opponent": "唐策",
            "info_gap_from_prev_life": "林栖记得承包商会在换班前私改冷库封签。",
        }
        filled = _fill_long_cluster_causal_fields(cluster, "林栖")
        self.assertIn("林栖", filled["prev_life_tragedy"])
        self.assertIn("唐策", filled["prev_life_tragedy"])

        specs = [
            {"cluster_id": "EC01", "chapter_span": [1, 1], "is_final_arc": False},
            {"cluster_id": "EC02", "chapter_span": [2, 2], "is_final_arc": False},
            {"cluster_id": "EC03", "chapter_span": [3, 4], "is_final_arc": False},
            {"cluster_id": "EC04", "chapter_span": [17, 20], "is_final_arc": True},
        ]
        focus = _long_form_focus_specs(specs, [17, 20])
        combined = str(filled) + str(focus)
        for leaked_topic in ("麦珂", "保险", "版权", "唱片", "演唱会", "假死", "葬礼"):
            self.assertNotIn(leaked_topic, combined)
        self.assertIn("明确死亡", focus[0]["focus"])
        self.assertIn("确认重生", focus[1]["focus"])
        self.assertIn("终局条件", focus[-1]["focus"])

    def test_long_form_batch_cache_is_isolated_by_seed_fingerprint(self):
        specs = [
            {"cluster_id": "EC01", "chapter_span": [1, 1], "is_final_arc": False}
        ]
        clusters = [
            {
                "cluster_id": "EC01",
                "chapter_span": [1, 1],
                "is_final_arc": False,
                "name": "冷库终夜",
            }
        ]
        payload = {"seed_fingerprint": "warehouse-story", "clusters": clusters}
        self.assertEqual(
            clusters,
            _matching_cached_long_cluster_batch(
                payload,
                seed_fingerprint="warehouse-story",
                specs=specs,
            ),
        )
        self.assertEqual(
            [],
            _matching_cached_long_cluster_batch(
                payload,
                seed_fingerprint="different-story",
                specs=specs,
            ),
        )

    def test_seed_plan_chapter_replacement_preserves_other_chapters(self):
        plan = (
            "【固定角色表】\n主角：Maya Reed\n"
            "【第1章：死亡】旧内容一\n---\n"
            "【第2章：重生】旧内容二\n---\n"
            "【第3章：终选】旧内容三\n【终局回收】保留"
        )
        replaced = _replace_seed_plan_chapter(
            plan,
            2,
            "【第2章：重生确认】\n场景：公寓\n主角行动：核对日期\n对手反应：无\n本章结果：预约会面",
        )
        self.assertIn("【第1章：死亡】旧内容一", replaced)
        self.assertIn("【第2章：重生确认】", replaced)
        self.assertNotIn("旧内容二", replaced)
        self.assertIn("【第3章：终选】旧内容三", replaced)
        self.assertIn("【终局回收】保留", replaced)

    def test_short_seed_opening_gets_one_concrete_death_method(self):
        plan = """【固定角色表】
主角：Maya Reed
身份：新人演员
核心对手：Lila Voss
身份：影后
关键盟友：Elena Torres
身份：独立制片人
【第1章：上一世死亡】
场景：《暗夜之光》试镜室
主角行动：Maya完成试镜
对手反应：Lila抢走角色
本章结果：Maya事业崩塌，最终自杀身亡
【第2章：重生】
场景：公寓
主角行动：核对日期
对手反应：无
本章结果：确认重生
【终局回收】"""
        normalized = _normalize_short_seed_opening_death(plan)
        chapter1 = _seed_plan_chapter_sections(normalized)[1]
        self.assertIn("服药过量自杀", chapter1)
        self.assertEqual(1, chapter1.count("服药过量自杀"))

    def test_seed_cast_is_parsed_and_locked_into_event_clusters(self):
        plan = """
【固定角色表】
**主角：Maya Reed**
身份：好莱坞新人女演员
**核心对手：Lila Voss（莉拉·沃斯）**
身份：当红影后
**关键盟友：**
**Victor Kane**（独立导演）
"""
        cast = _canonical_cast_from_seed_plan(plan)
        self.assertEqual(
            ["Maya Reed", "Lila Voss", "Victor Kane"],
            [member["name"] for member in cast],
        )
        locked = _apply_seed_cast_to_clusters(
            [{"canonical_cast": []}, {"canonical_cast": [{"name": "Wrong Name"}]}],
            plan,
        )
        self.assertEqual(cast, locked[0]["canonical_cast"])
        self.assertEqual(cast, locked[1]["canonical_cast"])
        malformed = "【固定角色表】\n**主角：Maya Reed**\n身份：演员\n【第1章】死亡。"
        self.assertTrue(any(
            "固定角色表无法解析" in failure
            for failure in _seed_plan_semantic_failures(malformed, total_chapters=6)
        ))

    def test_seed_plan_rejects_actor_assistant_identity_conflict(self):
        plan = """
【固定角色表】
**主角：Maya Reed**
身份：好莱坞新人女演员
**核心对手：Lila Voss**
身份：当红影后兼制片人助理
【第1章】Maya事业崩塌后死亡。
【第2章】Maya重生回到试镜前。
【第3章】Maya进入终选，Lila失去干预权。
【第4章】Maya拿下女主角合约，Lila退出角色竞争。
【第5章】Lila失去项目权限，Maya获得新合作。
【第6章】Lila被迫退出公司合作，Maya获得长期自主权。
"""
        failures = "\n".join(_seed_plan_semantic_failures(plan, total_chapters=6))
        self.assertIn("身份自相矛盾", failures)
        actor_signs = plan.replace(
            "身份：当红影后兼制片人助理",
            "身份：当红影后",
        ).replace(
            "【第5章】Lila失去项目权限，Maya获得新合作。",
            "【第5章】Lila Voss被迫签署Maya的合约，Maya获得新合作。",
        )
        self.assertTrue(any(
            "无权签署" in failure
            for failure in _seed_plan_semantic_failures(actor_signs, total_chapters=6)
        ))
        vague_middle = plan.replace(
            "身份：当红影后兼制片人助理",
            "身份：当红影后",
        ).replace(
            "【第4章】Maya拿下女主角合约，Lila退出角色竞争。",
            "【第4章】Maya拿下女主角合约，Lila失去女主角角色。",
        ).replace(
            "【第5章】Lila失去项目权限，Maya获得新合作。",
            "【第5章】Maya巩固角色地位，Lila失去影响力。",
        )
        self.assertTrue(any(
            "第5章没有双向职业结果" in failure
            for failure in _seed_plan_semantic_failures(vague_middle, total_chapters=6)
        ))
        directing_drift = vague_middle.replace(
            "【第6章】Lila被迫退出公司合作，Maya获得长期自主权。",
            "【第6章】Lila失去公司合作，Maya Reed获得独立执导邀约。",
        )
        self.assertTrue(any(
            "突然转任导演" in failure
            for failure in _seed_plan_semantic_failures(directing_drift, total_chapters=6)
        ))

    def test_short_plan_rejects_actor_company_power_stage_reversal_and_repeated_loss(self):
        plan = """
【固定角色表】
**主角：Maya Reed**
身份：好莱坞新人女演员
**核心对手：Lila Voss**
身份：当红影后 / 女主角候选人，持有片方续作优先谈判条款
**关键盟友：Victor Kane**
身份：独立制片人
【第1章：上一世死亡】
场景：试镜结束后
主角行动：Maya最后争取角色
对手反应：Lila公开嘲讽
本章结果：Maya失去事业并服药自杀，生命结束
【第2章：重生确认】
场景：公寓
主角行动：Maya核对日期并预约Victor会面
对手反应：Lila尚未介入
本章结果：Maya确认重生并完成预约
【第3章：初试突围】
场景：第一轮试镜
主角行动：Maya完成即兴表演
对手反应：Lila的干预被选角导演制止
本章结果：Maya获得复试资格；Lila失去一次干预机会
【第4章：角色落锤】
场景：终轮试镜
主角行动：Maya完成高难度台词表演
对手反应：Lila被片方换下
本章结果：Maya获得女主角合约；Lila失去女主角资格
【第5章：条款反杀】
        场景：片方合同会议，议程确认Lila仍持有当前影片的片方优先合作资格
主角行动：Maya争取剧本提案权
对手反应：Lila的捆绑合作要求被片方拒绝
本章结果：Maya获得剧本提案权；Lila失去片方优先合作资格
【第6章：长期签约】
场景：片方合作会议
主角行动：Maya争取多部影片演员合约
对手反应：Lila的续作谈判被制片公司终止
本章结果：Maya获得长期演员合约；Lila失去续作谈判机会
【终局回收】Maya获得长期演员合约；Lila失去片方优先合作资格。
"""
        self.assertEqual([], _seed_plan_semantic_failures(plan, total_chapters=6))

        actor_power = plan.replace(
            "主角行动：Maya争取多部影片演员合约\n对手反应：Lila的续作谈判被制片公司终止",
            "主角行动：Maya提议更换编剧团队\n对手反应：Lila被剥夺原有职位并调往非核心部门",
        )
        power_failures = "\n".join(_seed_plan_semantic_failures(actor_power, total_chapters=6))
        self.assertIn("团队或公司人员任免权", power_failures)
        self.assertIn("可调岗或降职的公司员工", power_failures)

        reversed_stage = plan.replace(
            "场景：第一轮试镜\n主角行动：Maya完成即兴表演",
            "场景：第二轮复试\n主角行动：Maya完成复试表演",
        )
        self.assertTrue(any(
            "阶段倒置" in failure
            for failure in _seed_plan_semantic_failures(reversed_stage, total_chapters=6)
        ))

        repeated_loss = plan.replace(
            "本章结果：Maya获得长期演员合约；Lila失去续作谈判机会",
            "本章结果：Maya获得长期演员合约；Lila再次失去女主角资格",
        )
        self.assertTrue(any(
            "重复结算同一主演角色" in failure
            for failure in _seed_plan_semantic_failures(repeated_loss, total_chapters=6)
        ))

        actor_decides_role = plan.replace(
            "主角行动：Maya最后争取角色\n对手反应：Lila公开嘲讽",
            "主角行动：Maya最后争取角色\n对手反应：Lila Voss宣布取消Maya资格，并把角色交给另一位演员",
        )
        self.assertTrue(any(
            "第1章让演员/影后对手越权" in failure
            for failure in _seed_plan_semantic_failures(actor_decides_role, total_chapters=6)
        ))

        manager_exits_project = plan.replace(
            "主角行动：Maya最后争取角色\n对手反应：Lila公开嘲讽",
            "主角行动：Maya最后争取角色\n对手反应：经纪人宣布Maya退出片方项目，Lila公开嘲讽",
        )
        self.assertTrue(any(
            "经纪人越权" in failure
            for failure in _seed_plan_semantic_failures(manager_exits_project, total_chapters=6)
        ))

        past_accusation = plan.replace(
            "主角行动：Maya争取剧本提案权",
            "主角行动：Maya揭露Lila过去拒绝合作的旧事",
        ).replace(
            "主角行动：Maya争取多部影片演员合约",
            "主角行动：Maya指出Lila过去一年阻碍新人发展并影响公司口碑",
        )
        past_failures = "\n".join(_seed_plan_semantic_failures(past_accusation, total_chapters=6))
        self.assertIn("第5章靠概括对手过去", past_failures)
        self.assertIn("第6章靠概括对手过去", past_failures)

        past_operations = plan.replace(
            "主角行动：Maya争取多部影片演员合约",
            "主角行动：Maya公开质疑Lila过往合作中的不当操作",
        )
        self.assertTrue(any(
            "第6章靠概括对手过去" in failure
            for failure in _seed_plan_semantic_failures(past_operations, total_chapters=6)
        ))

        investment_pressure = plan.replace(
            "对手反应：Lila的捆绑合作要求被片方拒绝",
            "对手反应：Lila试图拉拢投资人施压，但被Victor驳回",
        )
        self.assertTrue(any(
            "投资人、投资方或资本施压" in failure
            for failure in _seed_plan_semantic_failures(
                investment_pressure,
                total_chapters=6,
                extra_constraints="不要投资",
            )
        ))

        weak_final_gain = plan.replace(
            "本章结果：Maya获得长期演员合约；Lila失去续作谈判机会",
            "本章结果：Maya获得长期合作签约权；Lila失去续作谈判机会",
        )
        self.assertTrue(any(
            "没有实际签下长期演员合约" in failure
            for failure in _seed_plan_semantic_failures(weak_final_gain, total_chapters=6)
        ))

        three_picture_deal = plan.replace(
            "本章结果：Maya获得长期演员合约；Lila失去续作谈判机会",
            "本章结果：Maya获得三部影片主演合约；Lila失去续作谈判机会",
        )
        self.assertEqual([], _seed_plan_semantic_failures(three_picture_deal, total_chapters=6))

        actor_bidding = plan.replace(
            "对手反应：Lila的续作谈判被制片公司终止",
            "对手反应：Lila被迫退出未来项目竞标",
        )
        self.assertTrue(any(
            "参与项目竞标/投标的公司主体" in failure
            for failure in _seed_plan_semantic_failures(actor_bidding, total_chapters=6)
        ))

        consolation_role = plan.replace(
            "本章结果：Maya获得女主角合约；Lila失去女主角资格",
            "本章结果：Maya获得女主角合约；Lila失去女主角资格，被迫退居配角",
        )
        self.assertTrue(any(
            "补偿对手一个配角" in failure
            for failure in _seed_plan_semantic_failures(consolation_role, total_chapters=6)
        ))

        unsupported_loss = plan.replace(
            "对手反应：Lila的续作谈判被制片公司终止",
            "对手反应：Lila面色铁青，无法反驳",
        )
        self.assertTrue(any(
            "没有片方、制片公司或制片人当场作出取消决定" in failure
            for failure in _seed_plan_semantic_failures(unsupported_loss, total_chapters=6)
        ))

        ceremony_finale = plan.replace(
            "场景：片方合作会议\n主角行动：Maya争取多部影片演员合约",
            "场景：年度颁奖晚宴后的签约仪式\n主角行动：Maya争取多部影片演员合约",
        )
        self.assertTrue(any(
            "颁奖/晚宴等仪式场景" in failure
            for failure in _seed_plan_semantic_failures(ceremony_finale, total_chapters=6)
        ))

        invented_final_resource = plan.replace(
            "身份：当红影后 / 女主角候选人，持有片方续作优先谈判条款",
            "身份：当红影后 / 女主角候选人",
        )
        self.assertTrue(any(
            "没有提前建立第6章要清算" in failure
            for failure in _seed_plan_semantic_failures(invented_final_resource, total_chapters=6)
        ))

        early_final_loss = plan.replace(
            "本章结果：Maya获得剧本提案权；Lila失去片方优先合作资格",
            "本章结果：Maya获得剧本提案权；Lila失去续作谈判优先权",
        )
        self.assertTrue(any(
            "提前结算了终章" in failure
            for failure in _seed_plan_semantic_failures(early_final_loss, total_chapters=6)
        ))

        contract_interference = plan.replace(
            "主角行动：Maya争取多部影片演员合约",
            "主角行动：Maya签下自己的合约，并要求将Lila的旧合同重新评估",
        )
        self.assertTrue(any(
            "要求重审或取消对手合同" in failure
            for failure in _seed_plan_semantic_failures(contract_interference, total_chapters=6)
        ))

        unexplained_set_return = plan.replace(
            "主角行动：Maya争取剧本提案权",
            "主角行动：Maya争取剧本提案权，并要求调整日程避免与Lila行程重叠",
        )
        self.assertTrue(any(
            "无解释继续留在同一项目" in failure
            for failure in _seed_plan_semantic_failures(unexplained_set_return, total_chapters=6)
        ))

        vague_early_cooperation = plan.replace(
            "本章结果：Maya获得剧本提案权；Lila失去片方优先合作资格",
            "本章结果：Maya获得剧本提案权；Lila失去合作谈判机会",
        )
        self.assertTrue(any(
            "模糊的‘合作谈判’" in failure
            for failure in _seed_plan_semantic_failures(vague_early_cooperation, total_chapters=6)
        ))

        normalized = _normalize_short_event_milestones_from_seed_plan(
            [{
                "chapter_milestones": [
                    {"chapter": 2, "action": "给Victor打电话", "opponent_reaction": "", "result": "预约成功"},
                    {"chapter": 5, "action": "提出条款", "opponent_reaction": "Lila愤怒", "result": "Lila失去合作机会"},
                ],
            }],
            plan,
        )
        chapter2, chapter5 = normalized[0]["chapter_milestones"]
        self.assertIn("确认自己重生", chapter2["action"])
        self.assertIn("确认重生并完成首次部署", chapter2["result"])
        self.assertIn("Maya获得剧本提案权", chapter5["result"])
        self.assertIn("片方", chapter5["opponent_reaction"])

        title_only_death = plan.replace(
            "本章结果：Maya失去事业并服药自杀，生命结束",
            "本章结果：Maya失去事业，经纪人切断联系，账号被封禁",
        )
        title_death_failures = "\n".join(_seed_plan_semantic_failures(title_only_death, total_chapters=6))
        self.assertIn("第1章必须明确写到上一世死亡", title_death_failures)
        self.assertIn("章节标题中的‘死亡’不算", title_death_failures)

        evidence_drift = plan.replace(
            "主角行动：Maya争取剧本提案权",
            "主角行动：Maya出示Lila私下接触其他剧组的证据，争取剧本提案权",
        )
        self.assertTrue(any(
            "出示或提交对手私下接触" in failure
            for failure in _seed_plan_semantic_failures(
                evidence_drift,
                total_chapters=6,
                extra_constraints="不要调查推理、搜证",
            )
        ))

        invented_creative_right = plan.replace(
            "本章结果：Maya获得剧本提案权；Lila失去片方优先合作资格",
            "本章结果：Maya获得剧本提案权；Lila失去剧本参与资格",
        )
        self.assertTrue(any(
            "虚构了角色表未建立的剧本创作权" in failure
            for failure in _seed_plan_semantic_failures(invented_creative_right, total_chapters=6)
        ))

        invented_consultant = plan.replace(
            "主角行动：Maya争取多部影片演员合约",
            "主角行动：Maya拒绝Lila提出的幕后顾问职位要求并签下多部影片演员合约",
        )
        self.assertTrue(any(
            "虚构了角色表未建立的剧本创作权或项目顾问职位" in failure
            for failure in _seed_plan_semantic_failures(invented_consultant, total_chapters=6)
        ))

        conflicting_deaths = plan.replace(
            "本章结果：Maya失去事业并服药自杀，生命结束",
            "本章结果：Maya情绪崩溃后跳楼身亡；随后又回到公寓服药自杀身亡",
        )
        self.assertTrue(any(
            "两种互相冲突的死亡方式" in failure
            for failure in _seed_plan_semantic_failures(conflicting_deaths, total_chapters=6)
        ))

        audition_only_core = plan.replace(
            "本章结果：Maya获得女主角合约；Lila失去女主角资格",
            "本章结果：Maya获得女主角试镜资格；Lila失去竞争优势",
        )
        self.assertTrue(any(
            "必须完成全书唯一一次核心角色" in failure
            for failure in _seed_plan_semantic_failures(audition_only_core, total_chapters=6)
        ))

        fake_acting = plan.replace(
            "主角行动：Maya完成高难度台词表演",
            "主角行动：Maya指出Lila在前次试镜中并未理解角色",
        )
        self.assertTrue(any(
            "核心角色授予缺少实际试戏/表演" in failure
            for failure in _seed_plan_semantic_failures(fake_acting, total_chapters=6)
        ))

        hinted_private_contact = plan.replace(
            "主角行动：Maya争取剧本提案权",
            "主角行动：Maya暗示Lila曾私下接触另一部电影的主演位置",
        )
        self.assertTrue(any(
            "过去拒绝合作、打压新人或影响口碑" in failure
            for failure in _seed_plan_semantic_failures(hinted_private_contact, total_chapters=6)
        ))

        demands_series_removal = plan.replace(
            "主角行动：Maya争取多部影片演员合约",
            "主角行动：Maya签下自己的合约，并要求把Lila剔除出后续系列片",
        )
        self.assertTrue(any(
            "要求把对手剔出系列片/项目" in failure
            for failure in _seed_plan_semantic_failures(demands_series_removal, total_chapters=6)
        ))

        past_life_leak = plan.replace(
            "对手反应：Lila的干预被选角导演制止",
            "对手反应：Lila脸色骤变，低声说这女人怎么还没死",
        )
        self.assertTrue(any(
            "知道主角前世死亡" in failure
            for failure in _seed_plan_semantic_failures(past_life_leak, total_chapters=6)
        ))

        script_team_membership = plan.replace(
            "主角行动：Maya争取剧本提案权",
            "主角行动：Maya申请加入剧本创作小组并争取剧本提案权",
        )
        self.assertTrue(any(
            "虚构了角色表未建立的剧本创作权" in failure
            for failure in _seed_plan_semantic_failures(script_team_membership, total_chapters=6)
        ))

        dialogue_advice_only = plan.replace(
            "主角行动：Maya完成高难度台词表演",
            "主角行动：Maya在试镜中主动提出改编台词建议，展示专业素养",
        )
        self.assertTrue(any(
            "核心角色授予缺少实际试戏/表演" in failure
            for failure in _seed_plan_semantic_failures(dialogue_advice_only, total_chapters=6)
        ))

        result_announced_before_acting = plan.replace(
            "场景：终轮试镜",
            "场景：终轮试镜，选角导演宣布最终人选",
        )
        self.assertTrue(any(
            "场景在主角表演前就宣布最终人选" in failure
            for failure in _seed_plan_semantic_failures(result_announced_before_acting, total_chapters=6)
        ))

        agent_conspiracy_without_action = plan.replace(
            "与主角关系：上一世单独抢走主角角色",
            "与主角关系：上一世联手经纪人抢走主角角色",
        )
        if agent_conspiracy_without_action == plan:
            agent_conspiracy_without_action = plan.replace(
                "身份：当红影后 / 女主角候选人，持有片方续作优先谈判条款",
                "身份：当红影后 / 女主角候选人，持有片方续作优先谈判条款；上一世联手经纪人毁掉Maya事业",
            )
        self.assertTrue(any(
            "经纪人与核心对手联手" in failure
            for failure in _seed_plan_semantic_failures(agent_conspiracy_without_action, total_chapters=6)
        ))

        first_audition_without_acting = plan.replace(
            "主角行动：Maya完成即兴表演",
            "主角行动：Maya展示精准情绪控制力并提出台词理解",
        )
        self.assertTrue(any(
            "第3章首次职业反击缺少实际试戏/表演" in failure
            for failure in _seed_plan_semantic_failures(first_audition_without_acting, total_chapters=6)
        ))

        hearsay_payoff = plan.replace(
            "主角行动：Maya争取剧本提案权",
            "主角行动：Maya利用Lila在另一部电影中的违约传闻迫使片方重新评估",
        )
        self.assertTrue(any(
            "未经当场证实的旧传闻" in failure
            for failure in _seed_plan_semantic_failures(hearsay_payoff, total_chapters=6)
        ))

        producer_committee = plan.replace(
            "主角行动：Maya争取多部影片演员合约",
            "主角行动：Maya签署长期演员合约并要求加入制片委员会",
        )
        self.assertTrue(any(
            "片方治理席位" in failure
            for failure in _seed_plan_semantic_failures(producer_committee, total_chapters=6)
        ))

        unestablished_late_loss = plan.replace(
            "场景：片方合同会议，议程确认Lila仍持有当前影片的片方优先合作资格",
            "场景：片方合同会议",
        )
        self.assertTrue(any(
            "凭空剥夺尚未建立的对手资源" in failure
            for failure in _seed_plan_semantic_failures(unestablished_late_loss, total_chapters=6)
        ))

        agent_unpunished = plan.replace(
            "身份：当红影后 / 女主角候选人，持有片方续作优先谈判条款",
            "身份：当红影后 / 女主角候选人，持有片方续作优先谈判条款；上一世联手经纪人毁掉Maya事业",
        ).replace(
            "本章结果：Maya失去事业并服药自杀，生命结束",
            "本章结果：Maya的经纪人撤回代理支持，Maya失去事业并吞药自杀，生命结束",
        )
        agent_failures = _seed_plan_semantic_failures(agent_unpunished, total_chapters=6)
        self.assertTrue(any("第2章没有切断" in failure for failure in agent_failures))
        normalized_deployment = _normalize_short_seed_rebirth_deployment(agent_unpunished)
        self.assertIn("解除旧经纪人的代理授权", normalized_deployment)
        self.assertFalse(any(
            "第2章没有切断" in failure
            for failure in _seed_plan_semantic_failures(normalized_deployment, total_chapters=6)
        ))

        summary_plan = plan + "\n【终局回收】Lila失去并未在正文清算的委员会席位。"
        normalized_summary = _normalize_short_seed_terminal_summary(summary_plan)
        self.assertNotIn("委员会席位", normalized_summary)
        self.assertIn("章节6已验收结果", normalized_summary)
        normalized_sections = _seed_plan_chapter_sections(normalized_summary)
        self.assertIn("Maya完成高难度台词表演", normalized_sections[4])

        ally_is_traitor = plan.replace(
            "身份：独立制片人",
            "身份：前经纪人；曾联合Lila毁掉Maya事业",
        ).replace(
            "身份：当红影后 / 女主角候选人，持有片方续作优先谈判条款",
            "身份：当红影后 / 女主角候选人，持有片方续作优先谈判条款；联合经纪人Victor Kane毁掉Maya事业",
        )
        self.assertTrue(any(
            "固定角色表阵营冲突" in failure
            for failure in _seed_plan_semantic_failures(ally_is_traitor, total_chapters=6)
        ))

        forged_evidence = plan.replace(
            "本章结果：Maya失去事业并服药自杀，生命结束",
            "本章结果：片方收到伪造退赛声明和虚假证据，Maya失去事业并服药自杀，生命结束",
        )
        self.assertTrue(any(
            "调查、录音、视频或媒体证据链" in failure
            for failure in _seed_plan_semantic_failures(
                forged_evidence,
                total_chapters=6,
                extra_constraints="不要调查推理、媒体搜证链",
            )
        ))

        media_humiliation = plan.replace(
            "本章结果：Maya失去事业并服药自杀，生命结束",
            "本章结果：Maya被媒体拍下哭泣照片并登上热搜，随后服药自杀，生命结束",
        )
        self.assertTrue(any(
            "调查、录音、视频或媒体证据链" in failure
            for failure in _seed_plan_semantic_failures(
                media_humiliation,
                total_chapters=6,
                extra_constraints="不要媒体搜证链",
            )
        ))

        media_mob = plan.replace(
            "本章结果：Maya失去事业并服药自杀，生命结束",
            "本章结果：Maya在公开活动后遭媒体围攻，最终服药自杀，生命结束",
        )
        self.assertTrue(any(
            "调查、录音、视频或媒体证据链" in failure
            for failure in _seed_plan_semantic_failures(
                media_mob,
                total_chapters=6,
                extra_constraints="不要媒体搜证链",
            )
        ))

        skipped_first_round = plan.replace(
            "场景：第一轮试镜",
            "场景：复试现场",
        ).replace(
            "本章结果：Maya获得复试资格；Lila失去一次干预机会",
            "本章结果：Maya获得终选资格；Lila失去一次干预机会",
        )
        self.assertTrue(any(
            "第3章必须从今生第一轮正式试镜" in failure
            for failure in _seed_plan_semantic_failures(skipped_first_round, total_chapters=6)
        ))

        drifted_clusters = [{
            "cluster_id": "EC02",
            "main_opponent": "背叛经纪人",
            "chapter_milestones": [
                {"chapter": 2, "action": "确认日期", "opponent_reaction": "", "result": "预约成功"},
                {"chapter": 3, "action": "模仿Lila表演", "opponent_reaction": "Lila生气", "result": "Maya获认可"},
            ],
            "info_gap_from_prev_life": "偷听到两人私下讨论操控选角",
            "this_life_revenge": "模仿对手",
            "summary": "旧摘要",
        }]
        anchored_clusters = _normalize_short_event_milestones_from_seed_plan(drifted_clusters, plan)
        anchored = anchored_clusters[0]
        self.assertEqual("Lila Voss", anchored["main_opponent"])
        self.assertNotIn("偷听", anchored["info_gap_from_prev_life"])
        self.assertNotIn("旧摘要", anchored["summary"])
        self.assertIn("Maya完成即兴表演", anchored["chapter_milestones"][1]["action"])
        self.assertIn("Maya获得复试资格", anchored["chapter_milestones"][1]["result"])

        final_resource_clusters = [{
            "cluster_id": "EC04",
            "is_final_arc": True,
            "chapter_milestones": [
                {"chapter": 5, "action": "提出条款", "opponent_reaction": "片方拒绝Lila要求", "result": "Maya获得剧本提案权；Lila失去宣传席位"},
                {"chapter": 6, "action": "签署三部影片演员合约", "opponent_reaction": "片方取消Lila续作谈判", "result": "Maya获得三部影片演员合约；Lila失去续作谈判资格"},
            ],
        }]
        resource_plan = plan.replace(
            "场景：片方合同会议，议程确认Lila仍持有当前影片的片方优先合作资格",
            "场景：片方合同会议，议程确认Lila仍持有宣传合作席位；会议议程列明Lila仍持有续作优先谈判条款",
        )
        resource_anchored = _normalize_short_event_milestones_from_seed_plan(final_resource_clusters, resource_plan)
        self.assertIn("仍持有片方续作优先谈判条款", resource_anchored[0]["chapter_milestones"][0]["opponent_reaction"])
        self.assertFalse(any(
            "提前结算了终章" in failure
            for failure in _event_cluster_semantic_failures(resource_anchored, total_chapters=6)
        ))

        role_timeline_clusters = [{
            "cluster_id": "EC02",
            "chapter_span": [1, 6],
            "chapter_milestones": [
                {"chapter": 1, "result": "Lila获得女主角角色；Maya失去项目"},
                {"chapter": 4, "result": "Maya获得女主角合约；Lila失去女主角角色"},
                {"chapter": 6, "result": "Maya获得三部影片演员合约；Lila失去续作谈判资格"},
            ],
        }]
        self.assertFalse(any(
            "多章重复结算同一主演角色" in failure
            for failure in _event_cluster_semantic_failures(role_timeline_clusters, total_chapters=6)
        ))

    def test_event_contract_rejects_actor_department_state_and_stale_final_payoff(self):
        cast = [
            {"name": "Maya Reed", "role": "新人女演员", "alignment": "protagonist"},
            {"name": "Lila Voss", "role": "当红影后", "alignment": "opponent"},
            {"name": "Victor Kane", "role": "独立制片人", "alignment": "ally"},
        ]
        final_cluster = {
            "cluster_id": "EC04",
            "is_final_arc": True,
            "chapter_span": [5, 6],
            "canonical_cast": cast,
            "main_opponent": "Lila Voss",
            "info_gap_from_prev_life": "Maya记得片方合作节奏",
            "this_life_revenge": "Maya提议更换编剧团队",
            "core_payoff": "Maya获得女主角合约；Lila失去女主角资格",
            "cluster_outcome": "Maya获得长期演员合约；Lila失去片方合作资格",
            "final_payoff": "Maya获得新项目选择权；Lila被调往非核心部门",
            "chapter_milestones": [],
        }
        failures = "\n".join(_event_cluster_semantic_failures([final_cluster], total_chapters=6))
        self.assertIn("团队或公司人员任免权", failures)
        self.assertIn("可调岗或降职的公司员工", failures)
        self.assertIn("重复结算前簇已经完成的核心角色归属", failures)

        final_cluster["this_life_revenge"] = "Maya指出Lila过去一年阻碍新人并影响公司口碑"
        past_failures = "\n".join(_event_cluster_semantic_failures([final_cluster], total_chapters=6))
        self.assertIn("过去拒绝合作、打压新人或影响口碑", past_failures)

        final_cluster["user_extra_constraints"] = "不要投资"
        final_cluster["this_life_revenge"] = "Lila拉拢投资人施压，Maya当场拒绝"
        investment_failures = "\n".join(_event_cluster_semantic_failures([final_cluster], total_chapters=6))
        self.assertIn("投资人、投资方或资本施压", investment_failures)

    def test_short_event_object_specs_preserve_four_stage_story_roles(self):
        specs = _short_event_object_specs(
            total_chapters=6,
            final_start=5,
            final_end=6,
        )
        self.assertEqual(
            [[1, 1], [2, 2], [3, 4], [5, 6]],
            [spec["chapter_span"] for spec in specs],
        )
        self.assertEqual([False, False, False, True], [spec["is_final_arc"] for spec in specs])
        self.assertEqual([], _short_event_object_specs(
            total_chapters=4,
            final_start=3,
            final_end=4,
        ))

    def test_short_event_object_shape_requires_full_opening_cast_and_all_milestones(self):
        specs = _short_event_object_specs(
            total_chapters=6,
            final_start=5,
            final_end=6,
        )
        opening = {
            "canonical_cast": [
                {"name": "Maya Reed", "alignment": "protagonist"},
                {"name": "Elena Voss", "alignment": "opponent"},
            ],
            "chapter_milestones": [{
                "chapter": 1,
                "action": "Maya最后争取角色",
                "opponent_reaction": "Elena当场封杀",
                "result": "Maya在车祸中死亡",
            }],
        }
        self.assertEqual([], _short_event_object_shape_failures(opening, specs[0]))
        incomplete = {
            "canonical_cast": [{"name": "Maya Reed", "alignment": "protagonist"}],
            "chapter_milestones": [],
        }
        failures = "\n".join(_short_event_object_shape_failures(incomplete, specs[0]))
        self.assertIn("完整固定角色表", failures)
        self.assertIn("逐章覆盖", failures)

    def test_only_opening_failures_are_eligible_for_targeted_repair(self):
        clusters = [
            {"cluster_id": "EC01", "chapter_span": [1, 1]},
            {"cluster_id": "EC02", "chapter_span": [2, 2]},
        ]
        self.assertTrue(_failures_target_only_opening_cluster(
            clusters,
            ["EC01第1章里程碑没有明确写到上一世死亡"],
        ))
        self.assertFalse(_failures_target_only_opening_cluster(
            clusters,
            ["EC02缺少逐章结果"],
        ))

    def test_present_line_beats_drop_stray_flashback_metadata(self):
        beats = {
            "flashback_in_beat_idx": 1,
            "beats": [{"prev_life_memory_brief": "上一世完整回放"} for _ in range(3)],
        }
        self.assertTrue(_normalize_beats_flashback_mode(beats, "present_setup", 3))
        self.assertIsNone(beats["flashback_in_beat_idx"])
        self.assertTrue(all(not beat["prev_life_memory_brief"] for beat in beats["beats"]))

        required = {"flashback_in_beat_idx": None, "beats": [{}, {}, {}]}
        self.assertFalse(_normalize_beats_flashback_mode(required, "present_past_mix", 3))

    def test_exec_plan_fallback_accepts_one_action_resource(self):
        plan = _fallback_build_exec_plan_for_cluster(
            {
                "cluster_id": "EC02",
                "info_gap_from_prev_life": "Maya记得试镜当天会临时更换台词顺序。",
            },
            [2, 3, 4],
            {
                2: {"chapter_role_v2": "rebirth_awakening_only"},
                3: {"chapter_role_v2": "present_setup"},
                4: {"chapter_role_v2": "present_revenge"},
            },
        )
        self.assertEqual(1, len(plan["evidence_chain"]))
        self.assertIn("当前时间线主动准备", plan["evidence_chain"][0]["source"])

    def test_only_final_failures_are_eligible_for_targeted_repair(self):
        clusters = [
            {"cluster_id": "EC01", "is_final_arc": False},
            {"cluster_id": "EC04", "is_final_arc": True},
        ]
        self.assertTrue(_failures_target_only_final_cluster(
            clusters,
            ["EC04终局只写舆论或形象变化；必须补足现实得失"],
        ))
        self.assertTrue(_failures_target_only_final_cluster(
            clusters,
            ["chapter_milestones 在多章重复结算同一主演角色；必须升级"],
        ))
        self.assertFalse(_failures_target_only_final_cluster(
            clusters,
            ["EC03未闭合首次今生资源反杀"],
        ))

    def test_seed_plan_rejects_wrong_opening_and_media_evidence_engine(self):
        bad = (
            "第一章：重生后进入试镜现场，当场反杀。\n"
            "第二章：签下正式合同。\n"
            "第三章：她取得私密录音。\n"
            "第六章：媒体采访中播放一段视频，Elena失去角色，Maya拿下角色。"
        )
        failures = "\n".join(_seed_plan_semantic_failures(
            bad,
            total_chapters=6,
            extra_constraints="不要调查推理、匿名爆料、媒体搜证链",
        ))
        self.assertIn("第1章", failures)
        self.assertIn("第2章", failures)
        self.assertIn("媒体证据链", failures)

        good = (
            "第一章：上一世试镜受辱后死于车祸，生命结束。\n"
            "第二章：她惊醒并确认重生回到试镜三天前，只给Victor打电话约见。\n"
            "第三章：她预判临时换词，凭表演拿到复试。\n"
            "第六章：选角导演宣布Elena被换角，Maya正式出演并签约。"
        )
        self.assertEqual([], _seed_plan_semantic_failures(
            good,
            total_chapters=6,
            extra_constraints="不要调查推理、匿名爆料、媒体搜证链",
        ))
        old_life_role_loss = good.replace(
            "第一章：上一世试镜受辱后死于车祸，生命结束。",
            "第一章：上一世Elena抢走女主角，Maya失去女主角角色，受辱后死于车祸，生命结束。",
        )
        self.assertEqual([], _seed_plan_semantic_failures(
            old_life_role_loss,
            total_chapters=6,
            extra_constraints="不要调查推理、匿名爆料、媒体搜证链",
        ))

        repeated_role = good.replace(
            "第三章：她预判临时换词，凭表演拿到复试。",
            "第三章：她凭表演拿下女主角合约，Elena失去女主角角色。",
        ).replace(
            "第六章：选角导演宣布Elena被换角，Maya正式出演并签约。",
            "第六章：Maya再次拿下女主角合约，Elena再次失去女主角角色。",
        )
        self.assertTrue(any(
            "重复结算" in failure
            for failure in _seed_plan_semantic_failures(
                repeated_role,
                total_chapters=6,
                extra_constraints="不要调查推理、匿名爆料、媒体搜证链",
            )
        ))
        disclosure = good.replace(
            "第二章：她惊醒并确认重生回到试镜三天前，只给Victor打电话约见。",
            "第二章：她惊醒后告诉Victor自己已经重生，请他协助。",
        )
        self.assertTrue(any(
            "自曝重生" in failure
            for failure in _seed_plan_semantic_failures(
                disclosure,
                total_chapters=6,
                extra_constraints="不要调查推理、匿名爆料、媒体搜证链",
            )
        ))
        unauthorized_agent = good.replace(
            "第三章：她预判临时换词，凭表演拿到复试。",
            "第三章：经纪人宣布Maya淘汰并指定Elena出演女主角。",
        )
        self.assertTrue(any(
            "经纪人越权" in failure
            for failure in _seed_plan_semantic_failures(
                unauthorized_agent,
                total_chapters=6,
                extra_constraints="不要调查推理、匿名爆料、媒体搜证链",
            )
        ))
        media_cleanup = good.replace(
            "第六章：选角导演宣布Elena被换角，Maya正式出演并签约。",
            "第六章：发布会上媒体追问，Elena失去公众信任，Maya获得长期合约。",
        )
        media_failures = "\n".join(_seed_plan_semantic_failures(
            media_cleanup,
            total_chapters=6,
            extra_constraints="不要调查推理、匿名爆料、媒体搜证链",
        ))
        self.assertIn("发布会", media_failures)
        supplied_material = good.replace(
            "第三章：她预判临时换词，凭表演拿到复试。",
            "第三章：她利用Victor提供的资料指出对手违规，拿到复试。",
        )
        self.assertTrue(any(
            "模糊资料" in failure
            for failure in _seed_plan_semantic_failures(
                supplied_material,
                total_chapters=6,
                extra_constraints="不要调查推理、匿名爆料、媒体搜证链",
            )
        ))
        supplied_evidence = good.replace(
            "第六章：选角导演宣布Elena被换角，Maya正式出演并签约。",
            "第六章：Maya通过Victor的帮助，将Elena过去操控选角的证据提交公司审查。",
        )
        self.assertTrue(any(
            "提交审查的证据链" in failure
            for failure in _seed_plan_semantic_failures(
                supplied_evidence,
                total_chapters=6,
                extra_constraints="不要调查推理、匿名爆料、媒体搜证链",
            )
        ))
        accusation = good.replace(
            "第三章：她预判临时换词，凭表演拿到复试。",
            "第三章：她通过人脉寻找间接证据，揭露Elena贿赂导演后拿到复试。",
        )
        self.assertTrue(any(
            "贿赂指控" in failure
            for failure in _seed_plan_semantic_failures(
                accusation,
                total_chapters=6,
                extra_constraints="不要调查推理、匿名爆料、媒体搜证链",
            )
        ))

    def test_contract_uses_runtime_story_input(self):
        theme_constraints.configure_theme_contract(
            "海上救援悬疑", "近未来北大西洋救援船", ["林岚", "周衡"], "禁用超能力"
        )
        text = theme_constraints.constraints_text()
        self.assertIn("海上救援悬疑", text)
        self.assertIn("近未来北大西洋救援船", text)
        self.assertIn("林岚、周衡", text)
        self.assertIn("禁用超能力", text)

        artifact = theme_constraints.attach_theme_contract({})
        self.assertEqual("海上救援悬疑", artifact["theme_contract"]["theme"])
        self.assertEqual(["林岚", "周衡"], artifact["theme_contract"]["protagonists"])

    def test_default_contract_does_not_forbid_unselected_genres(self):
        joined = " ".join(theme_constraints.HARD_CONSTRAINTS + theme_constraints.FORBIDDEN_ELEMENTS)
        self.assertNotIn("娱乐圈", joined)
        self.assertNotIn("医疗", joined)
        self.assertNotIn("豪门", joined)

    def test_story_id_ignores_json_formatting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            compact = Path(temp_dir) / "compact.json"
            pretty = Path(temp_dir) / "pretty.json"
            compact.write_text('[{"cluster_id":"EC01","chapter_span":[1,5]}]', encoding="utf-8")
            pretty.write_text('[\n  {"chapter_span": [1, 5], "cluster_id": "EC01"}\n]\n', encoding="utf-8")
            self.assertEqual(story_id_for_clusters(compact), story_id_for_clusters(pretty))

    def test_small_run_clusters_are_continuous_and_non_overlapping(self):
        clusters = [
            {"cluster_id": "EC01", "chapter_span": [1, 1]},
            {"cluster_id": "EC02", "chapter_span": [1, 1]},
            {"cluster_id": "EC03", "chapter_span": [1, 1]},
            {"cluster_id": "FINAL", "chapter_span": [2, 4], "is_final_arc": True},
        ]
        result = _limit_clusters_to_run(clusters, 4)
        self.assertEqual([[1, 1], [2, 4]], [x["chapter_span"] for x in result])

    def test_short_run_coalesces_middle_clusters_into_one_continuous_arc(self):
        clusters = [
            {"cluster_id": "EC01", "name": "前世", "chapter_span": [1, 1]},
            {"cluster_id": "EC02", "name": "试镜", "chapter_span": [2, 2], "core_payoff": "拿下试镜"},
            {"cluster_id": "EC03", "name": "合同", "chapter_span": [3, 3], "core_payoff": "拒绝合同"},
            {"cluster_id": "EC04", "name": "会议", "chapter_span": [4, 4], "core_payoff": "会议反卡"},
            {"cluster_id": "FINAL", "name": "终局", "chapter_span": [5, 6], "is_final_arc": True},
        ]
        result = _limit_clusters_to_run(clusters, 6)
        self.assertEqual([[1, 1], [2, 4], [5, 6]], [x["chapter_span"] for x in result])
        self.assertIn("试镜", result[1]["name"])
        self.assertIn("合同", result[1]["name"])

        awakening_then_revenge = [
            {"cluster_id": "EC01", "chapter_span": [1, 1]},
            {"cluster_id": "EC02", "chapter_span": [2, 2], "main_opponent": "无"},
            {"cluster_id": "EC03", "chapter_span": [3, 4], "main_opponent": "Elena Voss"},
            {"cluster_id": "FINAL", "chapter_span": [5, 6], "is_final_arc": True},
        ]
        merged = _limit_clusters_to_run(awakening_then_revenge, 6)
        self.assertEqual("Elena Voss", merged[1]["main_opponent"])

    def test_chapter_milestones_drive_short_arc_cards_without_extra_flashback(self):
        cluster = {
            "cluster_id": "EC02",
            "name": "重生后首战",
            "chapter_span": [2, 4],
            "main_opponent": "Elena Voss",
            "core_payoff": "Maya拿下女主角合约",
            "prev_life_tragedy": "旧经纪人与Elena联手抢走Maya的角色，Maya服药死亡",
            "info_gap_from_prev_life": "Maya记得Elena会在试镜前临时改词",
            "planned_work_titles": ["暗夜之光"],
            "canonical_cast": [
                {"name": "Maya Reed", "role": "演员", "alignment": "protagonist"},
                {"name": "Elena Voss", "role": "影后", "alignment": "opponent"},
                {"name": "Victor Kane", "role": "选角导演", "alignment": "ally"},
            ],
            "chapter_milestones": [
                {"chapter": 2, "action": "核对日期", "opponent_reaction": "不出场", "result": "确认重生"},
                {"chapter": 3, "action": "主动即兴表演", "opponent_reaction": "Elena被导演制止", "result": "Maya进入终选"},
                {"chapter": 4, "action": "完成终选", "opponent_reaction": "Elena失去角色", "result": "Maya拿下女主角合约"},
            ],
        }
        cards = _build_cards_from_clusters_v2([cluster], total_chapters=4)
        self.assertEqual("rebirth_awakening_only", cards[2]["chapter_role_v2"])
        self.assertEqual("present_setup", cards[3]["chapter_role_v2"])
        self.assertEqual("present_revenge", cards[4]["chapter_role_v2"])
        self.assertIn("主动即兴表演", cards[3]["chapter_goal"])
        self.assertIn("Maya拿下女主角合约", cards[4]["chapter_ending"])
        self.assertEqual("确认重生", cards[2]["core_payoff"])
        self.assertNotIn("女主角合约", cards[2]["core_payoff"])
        self.assertEqual("核对日期", cards[2]["this_life_revenge"])
        self.assertIn("Victor Kane", cards[2]["allowed_roles"])
        self.assertIn("旧经纪人", cards[2]["allowed_roles"])
        self.assertEqual(["暗夜之光"], cards[2]["planned_work_titles"])

        prev_life_context = _build_grounded_short_prev_life_context(
            [cards[chapter] for chapter in range(1, 5)]
        )
        self.assertIn("旧经纪人与Elena联手", prev_life_context)
        self.assertIn("Maya记得Elena会在试镜前临时改词", prev_life_context)
        self.assertNotIn("记者", prev_life_context)
        self.assertNotIn("录像带", prev_life_context)

    def test_event_clusters_reject_impossible_carried_evidence_and_vague_payoff(self):
        bad = [{
            "cluster_id": "FINAL",
            "chapter_span": [2, 4],
            "is_final_arc": True,
            "main_opponent": "Elena Voss & 经纪公司",
            "canonical_cast": [
                {"name": "Maya Reed", "alignment": "protagonist"},
                {"name": "Elena Voss", "alignment": "opponent"},
            ],
            "info_gap_from_prev_life": "上一世Maya曾无意间录下秘密音频并保存证据。",
            "this_life_revenge": "Maya重生后直接播放这段录音。",
            "core_payoff": "Elena公众形象崩塌。",
            "cluster_outcome": "Maya获得尊重。",
            "final_payoff": "全网愤怒。",
        }]
        failures = "\n".join(_event_cluster_semantic_failures(bad, total_chapters=4))
        self.assertIn("前世记忆", failures)
        self.assertIn("泛称机构", failures)
        self.assertIn("现实利益", failures)

        good = [{
            "cluster_id": "FINAL",
            "chapter_span": [2, 4],
            "is_final_arc": True,
            "main_opponent": "Elena Voss",
            "canonical_cast": [
                {"name": "Maya Reed", "alignment": "protagonist"},
                {"name": "Elena Voss", "alignment": "opponent"},
            ],
            "info_gap_from_prev_life": "Maya记得Elena会在试镜时临时更换台词。",
            "this_life_revenge": "Maya今生提前练熟备选台词，当场完成表演。",
            "core_payoff": "Elena失去角色，Maya拿下角色。",
            "cluster_outcome": "片方与Maya签约，Elena被迫离场。",
            "final_payoff": "Elena被换角，Maya获得正式合约。",
        }]
        self.assertEqual([], _event_cluster_semantic_failures(good, total_chapters=4))

        public_rebirth = [dict(good[0])]
        public_rebirth[0]["this_life_revenge"] = "Maya告诉Victor自己已经重生，请他协助。"
        self.assertTrue(any(
            "自曝重生" in failure
            for failure in _event_cluster_semantic_failures(public_rebirth, total_chapters=4)
        ))
        negated_disclosure = [dict(good[0])]
        negated_disclosure[0]["this_life_revenge"] = "Maya不向Victor透露自己重生，只依据当前表演争取机会。"
        self.assertFalse(any(
            "自曝重生" in failure
            for failure in _event_cluster_semantic_failures(negated_disclosure, total_chapters=4)
        ))
        unsupported_accusation = [dict(good[0])]
        unsupported_accusation[0]["chapter_milestones"] = [{
            "chapter": 2,
            "action": "Maya通过人脉寻找间接证据，揭露Elena贿赂导演。",
            "opponent_reaction": "Elena否认。",
            "result": "Elena失去角色，Maya拿下角色。",
        }]
        self.assertTrue(any(
            "贿赂指控" in failure
            for failure in _event_cluster_semantic_failures(unsupported_accusation, total_chapters=4)
        ))
        contradictory_role = [dict(good[0])]
        contradictory_role[0]["canonical_cast"] = [
            {"name": "Maya Reed", "role": "新人女演员", "alignment": "protagonist"},
            {"name": "Elena Voss", "role": "影后兼制片人助理", "alignment": "opponent"},
        ]
        self.assertTrue(any(
            "身份自相矛盾" in failure
            for failure in _event_cluster_semantic_failures(contradictory_role, total_chapters=4)
        ))
        duplicate_generic_role = [dict(good[0])]
        duplicate_generic_role[0]["chapter_milestones"] = [
            {"chapter": 2, "action": "试镜", "opponent_reaction": "失算", "result": "Maya获得角色合约"},
            {"chapter": 3, "action": "会议", "opponent_reaction": "离场", "result": "Maya再次获得角色与创作权"},
        ]
        self.assertTrue(any(
            "重复结算同一主演角色" in failure
            for failure in _event_cluster_semantic_failures(duplicate_generic_role, total_chapters=4)
        ))

        awakening = [{
            "cluster_id": "EC02",
            "chapter_span": [2, 2],
            "main_opponent": "无",
            "canonical_cast": [
                {"name": "Maya Reed", "alignment": "protagonist"},
                {"name": "Elena Voss", "alignment": "opponent"},
            ],
            "info_gap_from_prev_life": "Maya只核对日期和试镜日程。",
            "this_life_revenge": "本章只完成重生确认。",
        }]
        self.assertEqual([], _event_cluster_semantic_failures(awakening, total_chapters=6))
        contradictory_awakening = [dict(awakening[0])]
        contradictory_awakening[0]["this_life_revenge"] = "本簇不进入今生；Maya联系Victor完成部署。"
        self.assertTrue(any(
            "位于今生时间线" in failure
            for failure in _event_cluster_semantic_failures(contradictory_awakening, total_chapters=6)
        ))

        leaked_material = [{
            "cluster_id": "EC03",
            "chapter_span": [3, 4],
            "main_opponent": "Elena Voss",
            "canonical_cast": [
                {"name": "Maya Reed", "alignment": "protagonist"},
                {"name": "Elena Voss", "alignment": "opponent"},
            ],
            "info_gap_from_prev_life": "Maya记得Elena会临时改台词。",
            "this_life_revenge": "Maya附上导演私人邮件，迫使片方换角。",
        }]
        self.assertTrue(any(
            "来源不透明" in failure
            for failure in _event_cluster_semantic_failures(leaked_material, total_chapters=6)
        ))

        weak_middle = [{
            "cluster_id": "EC03",
            "chapter_span": [3, 4],
            "main_opponent": "Elena Voss",
            "canonical_cast": [
                {"name": "Maya Reed", "alignment": "protagonist"},
                {"name": "Elena Voss", "alignment": "opponent"},
            ],
            "core_payoff": "Maya赢得导演关注。",
            "cluster_outcome": "Elena首次受挫。",
        }]
        self.assertTrue(any(
            "首次今生资源反杀" in failure
            for failure in _event_cluster_semantic_failures(weak_middle, total_chapters=6)
        ))

        cast = [
            {"name": "Maya Reed", "role": "新人演员", "alignment": "protagonist"},
            {"name": "Elena Voss", "role": "影后", "alignment": "opponent"},
        ]
        short_bad = [
            {
                "cluster_id": "EC01", "chapter_span": [1, 1], "canonical_cast": cast,
                "main_opponent": "Elena Voss",
                "chapter_milestones": [{"chapter": 1, "action": "最后试镜", "opponent_reaction": "Elena嘲讽", "result": "Maya生命结束"}],
            },
            {
                "cluster_id": "EC02", "chapter_span": [2, 2], "canonical_cast": cast,
                "main_opponent": "无",
                "chapter_milestones": [{"chapter": 2, "action": "核对日期确认重生", "opponent_reaction": "不出场", "result": "Maya获得终选资格"}],
            },
            {
                "cluster_id": "EC03", "chapter_span": [3, 4], "canonical_cast": cast,
                "main_opponent": "Elena Voss", "core_payoff": "Elena失去角色，Maya拿下角色",
                "cluster_outcome": "Elena退出角色竞争，Maya获得正式合约",
                "chapter_milestones": [
                    {"chapter": 3, "action": "即兴试镜", "opponent_reaction": "Elena错失抢先发言机会", "result": "Maya进入终选"},
                    {"chapter": 4, "action": "完成终选", "opponent_reaction": "Elena失去角色", "result": "Maya获得正式角色"},
                ],
            },
            {
                "cluster_id": "EC04", "chapter_span": [5, 6], "canonical_cast": cast,
                "main_opponent": "Elena Voss", "is_final_arc": True,
                "core_payoff": "Elena失去项目主导权，Maya获得长期合约",
                "cluster_outcome": "Elena退出项目，Maya获得自主权",
                "final_payoff": "Elena失去职位，Maya拿下新合作",
                "chapter_milestones": [
                    {"chapter": 5, "action": "片方会议争取条款", "opponent_reaction": "Elena失去项目权限", "result": "Maya获得合约自主权"},
                    {"chapter": 6, "action": "发布会引发媒体关注", "opponent_reaction": "Elena沉默", "result": "Elena失去公众信任，Maya获得新合作"},
                ],
            },
        ]
        short_failures = "\n".join(_event_cluster_semantic_failures(short_bad, total_chapters=6))
        self.assertIn("死亡方式", short_failures)
        self.assertIn("第2章提前获得", short_failures)
        self.assertIn("发布会", short_failures)
        self.assertIn("第6章里程碑未形成双向阶段结果", short_failures)
        self.assertNotIn("EC03第3章里程碑未形成双向阶段结果", short_failures)

    def test_event_cluster_names_are_normalized_against_seed_cast(self):
        clusters = [{
            "main_opponent": "Elena Vosss",
            "canonical_cast": [{"name": "Elena Vosss", "alignment": "opponent"}],
            "summary": "Maya Reed confronts Elena Vosss.",
        }]
        normalized = _normalize_cluster_names_from_seed_plan(
            clusters,
            "固定角色：Maya Reed、Victor Kane、Elena Voss。",
        )
        self.assertEqual("Elena Voss", normalized[0]["main_opponent"])
        self.assertEqual("Elena Voss", normalized[0]["canonical_cast"][0]["name"])
        self.assertIn("Elena Voss", normalized[0]["summary"])

    def test_event_cluster_schema_drift_is_normalized_before_validation(self):
        normalized = _normalize_event_cluster_shape([
            {
                "chapter_span": "[3, 4]",
                "main_opponent": "Lila Voss & 经纪人",
                "canonical_cast": [
                    {"name": "Lila Voss", "alignment": "opponent"},
                    {"name": "Maya Reed", "alignment": "protagonist"},
                    {"name": "Victor Kane", "alignment": "ally"},
                ],
            },
            {
                "chapter_span": [2, 2],
                "main_opponent": "无",
                "canonical_cast": [{"name": "Maya Reed", "alignment": "protagonist"}],
            },
            {
                "chapter_span": [5, 6],
                "main_opponent": "Lila Voss",
                "canonical_cast": [
                    {"name": "Maya Reed", "alignment": "protagonist"},
                    {"name": "Lila Voss", "alignment": "opponent"},
                ],
            },
        ])
        self.assertEqual([3, 4], normalized[0]["chapter_span"])
        self.assertEqual("Lila Voss", normalized[0]["main_opponent"])
        self.assertEqual(normalized[0]["canonical_cast"], normalized[1]["canonical_cast"])
        self.assertEqual(normalized[0]["canonical_cast"], normalized[2]["canonical_cast"])

    def test_explicit_chapter_constraints_become_checkable_contracts(self):
        theme_constraints.configure_theme_contract(
            "海上悬疑",
            "救援船",
            ["艾琳·沃德", "马克·里德"],
            "第3章当前时间线中马克·里德死亡，life_status永久为dead。"
            "第4章马克·里德只能通过日志出现，不能在当前时间线说话或参与行动。",
        )
        chapter3 = theme_constraints.attach_theme_contract({"chapter_id": 3})
        chapter4 = theme_constraints.attach_theme_contract({"chapter_id": 4})
        self.assertEqual("dead", chapter3["required_state_changes"][0]["new_value"])
        self.assertTrue(chapter3["required_state_changes"][0]["permanent"])
        self.assertEqual(["马克·里德"], chapter4["forbidden_active_characters"])

    def test_planned_state_must_land_and_forbidden_character_must_stay_inactive(self):
        card = {
            "required_state_changes": [{
                "character": "马克·里德", "field": "life_status", "new_value": "dead",
                "timeline": "current", "permanent": True,
            }],
            "forbidden_active_characters": ["马克·里德"],
        }
        missing = {"characters": [], "events": [], "state_changes": []}
        self.assertIn("计划落地缺失", _validate_chapter_memory_contract(card, missing)[0])

        valid = {
            "characters": [{"name": "马克", "mention_mode": "memory"}],
            "events": [{"timeline": "memory", "summary": "播放日志", "participants": [{"name": "马克", "mode": "memory"}]}],
            "state_changes": [{
                "character": "马克", "field": "life_status", "new_value": "dead",
                "timeline": "current", "permanent": True,
            }],
        }
        self.assertEqual([], _validate_chapter_memory_contract(card, valid))

        active = dict(valid)
        active["characters"] = [{"name": "马克", "mention_mode": "active", "evidence": "马克操作设备"}]
        self.assertTrue(any("不得在当前时间线行动" in x for x in _validate_chapter_memory_contract(card, active)))

    def test_rag_adaptation_uses_runtime_protagonist_not_legacy_heroine(self):
        adapted = adapt_sample_content("沈清欢看着林婉然反击。", "主题: 娱乐重生, 主角: Maya Reed, 背景: 洛杉矶")
        self.assertEqual("Maya Reed看着Maya Reed反击。", adapted)
        self.assertNotIn("沈清欢", adapted)

    def test_special_opening_chapters_have_hard_structure_checks(self):
        chapter1 = "她今生重返试镜现场，当场拿下角色。" + "痛苦" * 500
        failures1 = _chapter_body_hard_failures(
            chapter1, 1, {"chapter_role_v2": "prev_life_death_only"}
        )
        self.assertTrue(any("第1章只能写上一世终局" in x for x in failures1))
        self.assertTrue(any("生命结束" in x for x in failures1))
        post_death_phone = (
            "她在车祸中失去意识，心跳停止，确认死亡。"
            + "痛苦" * 300
            + "汽车熄火后，手机上的消息仍在等待某一天被人看见，成为改变命运的契机。"
        )
        self.assertTrue(any(
            "死亡后追加神秘手机" in x
            for x in _chapter_body_hard_failures(
                post_death_phone, 1, {"chapter_role_v2": "prev_life_death_only"}
            )
        ))

        chapter2 = "她直接走进试镜室完成表演，导演点头。" + "紧张" * 500
        failures2 = _chapter_body_hard_failures(
            chapter2, 2, {"chapter_role_v2": "rebirth_awakening_only"}
        )
        self.assertTrue(any("惊醒" in x and "确认重生" in x for x in failures2))

        chapter2_overreach = (
            "她猛地睁开眼，查看手机屏幕上的日期，终于确认自己重生回到了试镜前。"
            "翌日，她潜入公寓翻找账本和加密文档。" + "愤怒" * 500
        )
        overreach_failures = _chapter_body_hard_failures(
            chapter2_overreach, 2, {"chapter_role_v2": "rebirth_awakening_only"}
        )
        self.assertTrue(any("越过觉醒与首次部署边界" in x for x in overreach_failures))
        schedule_only = (
            "她恢复意识后检查手机日期和完好的身体，确认自己时间倒流，真的回来了。"
            "她给Victor打电话，只约好见面，并提醒自己第二天的试镜不能迟到。" + "惊疑" * 300
        )
        self.assertFalse(any(
            "进入次日行动" in x
            for x in _chapter_body_hard_failures(
                schedule_only, 2, {"chapter_role_v2": "rebirth_awakening_only"}
            )
        ))
        repeated_deploy = (
            "Maya Reed猛然惊醒，核对手机日期和完好的身体，确认自己重生回到试镜前。"
            "她给Victor打完电话后挂断电话，穿好外套。"
            "随后她又拨通Victor的号码：\"Victor？是我。\"" + "惊疑" * 300
        )
        repeated_failures = _chapter_body_hard_failures(
            repeated_deploy,
            2,
            {
                "chapter_role_v2": "rebirth_awakening_only",
                "canonical_cast": [
                    {"name": "Maya Reed", "alignment": "protagonist"},
                    {"name": "Victor Kane", "alignment": "ally"},
                ],
            },
        )
        self.assertTrue(any("重复执行首次部署" in x for x in repeated_failures))
        changed_death = repeated_deploy.replace(
            "她给Victor打完电话后",
            "她想起上一世自己被人推下楼梯、摔断脊椎。她给Victor打完电话后",
        )
        self.assertTrue(any(
            "改写上一章死亡方式" in x
            for x in _chapter_body_hard_failures(
                changed_death, 2, {"chapter_role_v2": "rebirth_awakening_only"}
            )
        ))
        opponent_visit = (
            "惊怒" * 500
            + "她猛地睁开眼，查看手机日期，确认自己重生回到试镜前，并给Victor打完电话。"
            "门被推开，Elena走进房间，盯着她开口说道。"
        )
        visit_failures = _chapter_body_hard_failures(
            opponent_visit,
            2,
            {
                "chapter_role_v2": "rebirth_awakening_only",
                "canonical_cast": [{"name": "Elena Voss", "alignment": "opponent"}],
            },
        )
        self.assertTrue(any("核心对手" in x and "觉醒章" in x for x in visit_failures))
        early_memory_only = (
            "她猛地睁开眼，查看手机日期和完好的身体，确认自己重生回到试镜前。"
            "她想起上一世Lila说道，你永远拿不到角色。"
            + "她逐项核对房间里的旧物。" * 50
            + "最后，她给Victor打电话约定当天下午通话，随后放下手机。"
        )
        self.assertFalse(any(
            "核心对手" in x and "觉醒章" in x
            for x in _chapter_body_hard_failures(
                early_memory_only,
                2,
                {
                    "chapter_role_v2": "rebirth_awakening_only",
                    "canonical_cast": [{"name": "Lila Monroe", "alignment": "opponent"}],
                },
            )
        ))
        awakening_prompt = _build_awakening_repair_prompt(
            2,
            chapter2,
            {"canonical_cast": [{"name": "Maya Reed", "alignment": "protagonist"}]},
            failures2,
        )
        self.assertIn("身体完好", awakening_prompt)
        self.assertIn("至少三项细节", awakening_prompt)
        self.assertIn("逐项完成", awakening_prompt)
        self.assertNotIn(chapter2, awakening_prompt)
        death_prompt = _build_death_repair_prompt(
            1,
            "她丢掉试镜，心里想着这只是开始。",
            {"canonical_cast": [{"name": "Maya Reed", "alignment": "protagonist"}]},
            ["第1章必须写到死亡"],
        )
        self.assertIn("上一世死亡章", death_prompt)
        self.assertIn("心跳停止", death_prompt)
        self.assertIn("这只是开始", death_prompt)

    def test_revenge_finale_requires_tangible_result(self):
        self.assertTrue(_has_tangible_payoff(
            "即日起终止与Elena Voss的合作关系；主持人宣布恢复玛雅·里德的所有参赛资格。"
        ))
        vague = "她掌握了主动权，真正的反击仍在酝酿。" + "对峙" * 500
        failures = _chapter_body_hard_failures(
            vague, 8, {"chapter_role_v2": "present_revenge"}
        )
        self.assertTrue(any("缺少可见兑现" in x for x in failures))

        concrete = "选角导演当场宣布由她拿下角色，Lila失去角色，被迫离场。" + "掌声" * 500
        self.assertFalse(any(
            "缺少可见兑现" in x
            for x in _chapter_body_hard_failures(concrete, 8, {"chapter_role_v2": "present_revenge"})
        ))
        staged_rights = "选角导演宣布Maya正式获得女主角合约，Lila失去推荐权与影响力。" + "掌声" * 500
        self.assertTrue(_has_tangible_payoff(staged_rights))

        weak_apology = "Elena被迫公开道歉，但仍然保住了职位。Maya获得许多关注。" + "掌声" * 500
        weak_failures = _chapter_body_hard_failures(
            weak_apology, 8, {"chapter_role_v2": "present_revenge"}
        )
        self.assertTrue(any("缺少可见兑现" in x for x in weak_failures))
        self.assertTrue(any("保住关键利益" in x for x in weak_failures))

        custom_card = {
            "canonical_cast": [
                {"name": "Nora Vale", "alignment": "protagonist"},
                {"name": "Celeste Hart", "alignment": "opponent"},
            ]
        }
        self.assertTrue(_has_tangible_payoff(
            "Celeste Hart当场被换下，女主角确定由Nora Vale出演。",
            custom_card,
        ))

    def test_standalone_awakening_cluster_is_not_forced_to_pay_off_revenge(self):
        text = (
            "她猛地睁开眼，检查完好的身体、手机屏幕日期和熟悉房间，终于确认自己重生回到试镜前。"
            "她给Victor打电话约定见面，然后放下手机。" + "惊疑" * 750
        )
        result = _cluster_critic(
            {"chapter_span": [2, 2], "core_payoff": "试镜反击"},
            {2: text},
        )
        self.assertTrue(result["payoff_completed"])
        self.assertFalse(any("反杀结果" in x for x in result["violations"]))
        self.assertEqual(1400, _minimum_chapter_chars(2, {"chapter_role_v2": "rebirth_awakening_only"}))
        self.assertEqual(1500, _minimum_chapter_chars(3, {"chapter_role_v2": "present_revenge"}))

    def test_prose_quality_rejects_template_blocks_and_cross_chapter_copying(self):
        template_paragraphs = [
            "前一场已经冻结的合同仍保持原状。" + "现场动作继续推进。" * 16,
            "主角把相关人员留在公开核验位置。" + "所有人逐项核对。" * 16,
            "所有人先确认旧安排尚未恢复。" + "对手试图改口。" * 18,
            "决定当场生效。" + "旧入口随即关闭。" * 20,
            "主角取得现实权限。" + "在场人按新状态行动。" * 18,
            "与会者依次确认最终状态，随后才收起各自材料。" + "现场到此收束。" * 14,
        ]
        templated = "\n\n".join(template_paragraphs)
        failure = _prose_structure_failure(templated)
        self.assertIsNotNone(failure)
        self.assertIn("兜底模板", failure)

        copied = "\n\n".join(
            f"人物在第{index}次交锋中改变动作，对手当场失去退路。" * 12
            for index in range(10)
        )
        renamed = copied.replace("人物", "主角").replace("对手", "承包商")
        similarity_failures = _cross_chapter_prose_similarity_failures(
            renamed,
            {8: copied},
        )
        self.assertTrue(similarity_failures)
        self.assertIn("高度相似", similarity_failures[0])

    def test_body_rejects_generation_artifacts_seen_in_live_eval(self):
        artifact_text = (
            "闪回：\n她第一次重生后留下电脑，匿名账号发来消息。\n\n"
            "她打开纸条，读到同样的内容。\n\n"
            "她打开纸条，读到同样的内容。" + "冲突" * 500
        )
        failures = _chapter_body_hard_failures(artifact_text, 3, {})
        joined = "\n".join(failures)
        self.assertIn("闪回/回忆", joined)
        self.assertIn("匿名账号", joined)
        self.assertIn("重生次数", joined)

        montage = (
            "Elena被迫公开道歉并失去角色，Maya当场拿下角色。几个月后，一切归于平静。"
            + "掌声" * 500
        )
        montage_failures = _chapter_body_hard_failures(
            montage, 4, {"chapter_role_v2": "present_revenge"}
        )
        self.assertTrue(any("时间蒙太奇" in x for x in montage_failures))

        impossible_evidence = (
            "她想起前世的对话，手指按下录音键，将那段声音从脑海中还原成音频。"
            + "愤怒" * 500
        )
        self.assertTrue(any(
            "前世记忆" in x and "现实物证" in x
            for x in _chapter_body_hard_failures(impossible_evidence, 3, {})
        ))

        public_rebirth = (
            "红毯上记者和镜头围住她。她对众人说：“我上一世就是死在这里，现在我回来了。”"
            + "震惊" * 500
        )
        self.assertTrue(any(
            "公众面前" in x
            for x in _chapter_body_hard_failures(public_rebirth, 4, {})
        ))

        award_name = "工作人员宣布Maya Reed成为最佳Maya Reed唯一候选人。" + "掌声" * 500
        self.assertTrue(any(
            "奖项类别" in x
            for x in _chapter_body_hard_failures(
                award_name,
                4,
                {"canonical_cast": [{"name": "Maya Reed", "alignment": "protagonist"}]},
            )
        ))

    def test_payoff_repair_requires_both_loss_and_gain(self):
        prompt = _build_payoff_repair_prompt(
            4,
            "Maya公开录音，现场一片哗然。",
            {"main_opponent": "Elena Voss", "core_payoff": "录音反杀", "must_resolve": ["角色归属"]},
            ["本簇收尾章缺少可见兑现"],
        )
        self.assertIn("对手失去什么、主角拿回什么", prompt)
        self.assertIn("至少两个现实结果", prompt)
        self.assertIn("Elena Voss", prompt)
        insertion = _build_payoff_insertion_prompt(
            4,
            "Maya当众播放了录音。",
            {
                "main_opponent": "Elena Voss",
                "core_payoff": "录音反杀",
                "canonical_cast": [{"name": "Maya Reed", "alignment": "protagonist"}],
            },
            ["缺少可见兑现"],
        )
        self.assertIn("600-900", insertion)
        self.assertIn("终止合作", insertion)
        self.assertIn("Maya Reed拿下角色", insertion)
        self.assertIn("同一地点、同一晚", insertion)
        self.assertIn("不得新增", insertion)
        self.assertTrue(_scene_has_payoff_authority("选角导演放下评分表。"))
        self.assertFalse(_scene_has_payoff_authority("记者们围住了红毯。"))

        canonical_insertion = _build_payoff_insertion_prompt(
            4,
            "选角导演合上文件。",
            {
                "main_opponent": "Celeste Harrrt",
                "canonical_cast": [
                    {"name": "Nora Vale", "alignment": "protagonist"},
                    {"name": "Celeste Hart", "alignment": "opponent"},
                ],
            },
            ["缺少可见兑现"],
        )
        self.assertIn("Celeste Hart失去这个角色，Nora Vale拿下这个角色", canonical_insertion)
        self.assertNotIn("Celeste Harrrt", canonical_insertion)

    def test_expansion_prompt_cannot_invent_a_second_plot(self):
        prompt = _build_chapter_expansion_prompt(
            2,
            "Maya确认日期后给Victor打了电话。",
            {"chapter_role_v2": "rebirth_awakening_only", "chapter_must_not_include": ["调查"]},
        )
        self.assertIn("rebirth_awakening_only", prompt)
        self.assertIn("不得把一章扩成第二天或另一场任务", prompt)
        self.assertIn("匿名论坛", prompt)
        self.assertTrue(_expansion_preserves_original_ending(
            "第一段。\n\n原结尾。",
            "第一段扩写。\n\n原结尾。",
        ))
        self.assertFalse(_expansion_preserves_original_ending(
            "第一段。\n\n原结尾。",
            "第一段扩写。\n\n原结尾。\n\n又去了会所。",
        ))
        inserted = _insert_before_last_paragraph(
            "第一段。\n\n原结尾。",
            "新增场内细节。",
        )
        self.assertEqual("第一段。\n\n新增场内细节。\n\n原结尾。", inserted)
        self.assertTrue(_expansion_preserves_original_ending("第一段。\n\n原结尾。", inserted))

    def test_rolling_critic_must_resolve_active_character_at_previous_ending(self):
        prev = (
            "Maya刚挂断电话。门锁突然转动，Elena走进房间，盯着她说道：‘我们谈谈。’"
            + "对峙" * 80
        )
        curr = "Maya低头滑动手机，开始回忆昨天的试镜。" + "计划" * 100
        failures = _chapter_rolling_critic(prev, curr, 3, {})
        self.assertTrue(any("Elena" in x and "跳过" in x for x in failures))

    def test_rolling_critic_rejects_transferred_clothing_detail(self):
        card = {
            "canonical_cast": [
                {"name": "麦珂·杰森", "alignment": "protagonist"},
                {"name": "卡尔·霍尔特", "alignment": "opponent"},
            ],
        }
        prev = (
            "卡尔·霍尔特站在控台边，盯着排练场另一侧很久。"
            "他的西装外套肘部压出一道褶皱，"
            "那道褶皱在灯下格外清楚。"
        )
        curr = (
            "麦珂·杰森推开医务室门，西装肘部那道褶皱还在。"
            "他径直走向桌边。"
        )
        failures = _chapter_rolling_critic(prev, curr, 6, card)
        self.assertTrue(any(
            "属于卡尔·霍尔特" in failure
            and "转移给了麦珂·杰森" in failure
            for failure in failures
        ))

        key_prev = (
            "卡尔·霍尔特在控台旁站了很久，右手伸进裤袋，摸了摸已经交出的钥匙串，"
            "最后只能攥紧空荡荡的口袋。"
        )
        key_curr = (
            "麦珂·杰森站在医务室里，指尖还记得那串钥匙的分量。"
            "他上周交出的钥匙串已经不在裤袋里。"
        )
        key_failures = _chapter_rolling_critic(key_prev, key_curr, 6, card)
        self.assertTrue(any(
            "钥匙串" in failure
            and "属于卡尔·霍尔特" in failure
            and "转移给了麦珂·杰森" in failure
            for failure in key_failures
        ))

    def test_cluster_critic_does_not_repeat_chapter_one_or_require_internal_ids(self):
        pattern = "上一世她认出这套旧招，早已先一步布好局。Elena果然照旧发难，Maya当场揭穿。"
        texts = {
            2: "她猛地睁开眼，查看手机屏幕日期，确认自己重生回到试镜前。" + pattern * 40,
            3: pattern * 45,
            4: pattern * 40 + "选角导演当场宣布Maya拿下角色，品牌宣布与Elena停止合作。",
        }
        plan = {"evidence_chain": [{
            "evidence_id": "E1", "acquire_chapter": 3, "verify_chapter": 3, "use_chapter": 4,
            "acquire_keywords": ["布好"], "verify_keywords": ["揭穿"], "use_keywords": ["当场"],
        }]}
        result = _cluster_critic(
            {
                "chapter_span": [2, 4],
                "main_opponent": "Elena",
                "core_payoff": "Maya拿下角色",
                "info_gap_from_prev_life": "Maya记得Elena会在试镜时临时换词。",
            },
            texts,
            exec_plan=plan,
        )
        joined = "\n".join(result["violations"])
        self.assertNotIn("上一世受害段落篇幅不足", joined)
        self.assertNotIn("未出现在", joined)
        self.assertNotIn("信息差未转化", joined)
        self.assertTrue(result["payoff_completed"])

    def test_canonical_cast_name_drift_is_rejected(self):
        failures = _chapter_body_hard_failures(
            "Victoria走进房间。" + "冲突" * 500,
            4,
            {"canonical_cast": [{"name": "Victor Kane"}]},
        )
        self.assertTrue(any("固定人物名漂移" in x for x in failures))
        surname_failures = _chapter_body_hard_failures(
            "Maya Lin走进房间。Victor Kane被停职。" + "冲突" * 500,
            4,
            {"canonical_cast": [
                {"name": "Maya Reed", "alignment": "protagonist"},
                {"name": "Victor Kane", "alignment": "ally"},
            ]},
        )
        self.assertTrue(any("Maya Lin" in x for x in surname_failures))
        self.assertTrue(any("固定阵营漂移" in x for x in surname_failures))
        normalized = _normalize_joined_canonical_names(
            "MayaReed看向VictorKane。Elena Vosss转身，Maya Reeds没有退让。",
            {"canonical_cast": [{"name": "Maya Reed"}, {"name": "Victor Kane"}]},
        )
        self.assertEqual(
            "Maya Reed看向Victor Kane。Elena Vosss转身，Maya Reed没有退让。",
            normalized,
        )

        unknown = _unknown_named_roles_in_synopsis(
            "经纪人Vivian Price命令Maya Reed退场，Elena Voss在旁边冷笑。",
            [
                {"name": "Maya Reed", "alignment": "protagonist"},
                {"name": "Elena Voss", "alignment": "opponent"},
            ],
        )
        self.assertEqual(["Vivian Price"], unknown)
        self.assertEqual(
            ["David"],
            _unknown_named_roles_in_synopsis(
                "经纪人David已经和Lila Voss达成协议。",
                [
                    {"name": "Maya Reed", "alignment": "protagonist"},
                    {"name": "Lila Voss", "alignment": "opponent"},
                ],
            ),
        )
        self.assertEqual(
            ["艾琳"],
            _unknown_named_roles_in_synopsis("导演助理艾琳走进房间。", []),
        )
        self.assertEqual(
            [],
            _unknown_named_roles_in_synopsis(
                "经纪人终于缓缓走进房间，选角导演开口说道，制片人皱眉转身离开。"
                "导演是如何决定的，制片人会在何时答复？", []
            ),
        )

    def test_opening_death_and_work_title_must_preserve_seed_facts(self):
        card = {
            "chapter_role_v2": "prev_life_death_only",
            "prev_life_tragedy": "Maya失去《暗夜之光》的角色，随后服药过量自杀。",
            "canonical_cast": [
                {"name": "Maya Reed", "alignment": "protagonist"},
                {"name": "Lila Voss", "alignment": "opponent"},
            ],
        }
        generic_suicide = (
            "Maya Reed失去《暗夜之光》的角色，最终自杀身亡，呼吸停止。"
            + "愤怒与绝望交错。" * 180
        )
        self.assertTrue(any(
            "具体死亡方式" in failure
            for failure in _chapter_body_hard_failures(generic_suicide, 1, card)
        ))

        drifted_title = generic_suicide.replace("自杀身亡", "服药过量自杀").replace(
            "《暗夜之光》", "《暗涌》"
        )
        self.assertTrue(any(
            "擅自改写作品名" in failure
            for failure in _chapter_body_hard_failures(drifted_title, 1, card)
        ))
        self.assertTrue(any(
            "擅自改写作品名" in failure
            for failure in _cluster_synopsis_hard_failures(
                "Maya为《暗涌》参加试镜。", card["canonical_cast"], card
            )
        ))

        grounded = _append_grounded_opening_death_scene(
            "Maya Reed被经纪人当众抛弃。" + "愤怒与绝望交错。" * 180,
            card,
        )
        grounded_failures = _chapter_body_hard_failures(grounded, 1, card)
        self.assertFalse(any("第1章必须" in failure for failure in grounded_failures))
        self.assertIn("过量药物", grounded)

        conspiracy_failures = _cluster_synopsis_hard_failures(
            "Maya遭遇一场看似意外却暗藏阴谋的事故。", card["canonical_cast"], card
        )
        self.assertTrue(any("未规划阴谋" in failure for failure in conspiracy_failures))
        carried_bottle_failures = _cluster_synopsis_hard_failures(
            "Maya Reed惊醒后确认自己重生回到试镜前，手中还紧紧攥着上一世的药瓶。",
            card["canonical_cast"],
            card,
        )
        self.assertTrue(any("跨时间线携带" in failure for failure in carried_bottle_failures))
        synopsis_failures = _cluster_synopsis_hard_failures(
            "未知号码发来消息，要求她取出私人邮件。"
        )
        self.assertTrue(any("廉价神秘" in x for x in synopsis_failures))
        self.assertTrue(any("私密材料" in x for x in synopsis_failures))
        impossible_message = _cluster_synopsis_hard_failures(
            "手机上有一条Maya上一世临终前发送给自己的未读消息，成了唯一线索。"
        )
        self.assertTrue(any("跨时间消息" in x for x in impossible_message))
        role_failures = _cluster_synopsis_hard_failures(
            "Maya Reed唯一的依靠是经纪人Victor Kane。",
            [
                {"name": "Maya Reed", "role": "新人女演员", "alignment": "protagonist"},
                {"name": "Victor Kane", "role": "独立制片人兼选角导演", "alignment": "ally"},
            ],
        )
        self.assertTrue(any("固定人物身份漂移" in x for x in role_failures))

    def test_actor_payoff_requires_performance_and_normalizes_temp_names(self):
        card = {
            "chapter_role_v2": "present_revenge",
            "this_life_revenge": "Maya Reed即兴演绎关键片段，打动选角导演。",
            "core_payoff": "Maya Reed正式获得《暗夜之光》女主角合约，Lila Voss失去角色。",
            "planned_work_titles": ["暗夜之光"],
            "canonical_cast": [
                {"name": "Maya Reed", "alignment": "protagonist"},
                {"name": "Lila Voss", "alignment": "opponent"},
                {"name": "Elena Martinez", "alignment": "ally"},
            ],
        }
        premature = (
            "Elena Martinez宣布由Maya Reed出演女主角。Maya Reed当场签下主演合同，合同立即生效。"
            "Lila Voss失去角色，被迫退出《暗夜之光》。"
        )
        failures = _chapter_body_hard_failures(premature, 4, card)
        self.assertTrue(any("缺少主角实际表演" in failure for failure in failures))

        invented = (
            "James Whitmore示意开始，Maya Reed完成试戏表演并收住动作。"
            "David Chen宣布由Maya Reed出演女主角。Maya Reed当场签下主演合同，合同立即生效。"
            "Lila Voss失去角色，被迫退出《暗夜之光》。"
        )
        normalized = _normalize_unplanned_named_people(invented, card)
        self.assertNotIn("James Whitmore", normalized)
        self.assertNotIn("David Chen", normalized)
        self.assertFalse(any(
            "擅自新增或改名人物" in failure
            for failure in _chapter_body_hard_failures(normalized, 4, card)
        ))

        grounded = _append_grounded_actor_contract_payoff("试戏开始。", card)
        grounded_failures = _chapter_body_hard_failures(grounded, 4, card)
        self.assertFalse(any("缺少主角实际表演" in failure for failure in grounded_failures))
        self.assertFalse(any("缺少可见兑现" in failure for failure in grounded_failures))

    def test_grounded_cluster_synopsis_uses_only_accepted_card_facts(self):
        cast = [
            {"name": "Maya Reed", "role": "新人演员", "alignment": "protagonist"},
            {"name": "Lila Voss", "role": "影后", "alignment": "opponent"},
        ]
        cards = {
            2: {
                "chapter_role_v2": "rebirth_awakening_only",
                "this_life_revenge": "Maya Reed解除旧经纪人的代理授权。",
                "core_payoff": "解约已经生效。",
            },
            3: {
                "chapter_role_v2": "present_setup",
                "this_life_revenge": "Maya Reed完成试镜表演。",
                "core_payoff": "Maya Reed进入终选，Lila Voss失去干预机会。",
            },
        }
        synopsis = _build_grounded_cluster_synopsis_from_cards(
            {"canonical_cast": cast}, cards, [2, 3]
        )
        self.assertIn("第2章", synopsis)
        self.assertIn("第3章", synopsis)
        self.assertIn("重生只保留记忆", synopsis)
        self.assertEqual([], _unknown_named_roles_in_synopsis(synopsis, cast))
        self.assertEqual([], _cluster_synopsis_hard_failures(synopsis, cast, {}))

    def test_awakening_rejects_identity_role_and_milestone_drift(self):
        card = {
            "chapter_role_v2": "rebirth_awakening_only",
            "this_life_revenge": (
                "Maya Reed确认重生，解除旧经纪人的代理授权，"
                "并联系Ethan Cole预约会面"
            ),
            "core_payoff": "解除旧代理并完成与Ethan Cole的会面预约",
            "canonical_cast": [
                {"name": "Maya Reed", "alignment": "protagonist"},
                {"name": "Lila Voss", "alignment": "opponent"},
                {"name": "Ethan Cole", "alignment": "ally"},
            ],
        }
        bad = (
            "她猛然惊醒，查看身体、房间和手机日期，确认自己重生回到了试镜前。"
            "今天正是试镜的日子。新闻写着Lila Voss正式签约《暗夜之光》。"
            "她给旧经纪人发邮件说需要谈谈。Ethan Cole是那个曾亲手毁掉她梦想的男人。"
            "她按下拨号键，自称艾琳·卡特，等待对方接听。"
            + "愤怒与疑惑交错。" * 120
        )
        failures = "\n".join(_chapter_body_hard_failures(bad, 2, card))
        self.assertIn("艾琳·卡特", failures)
        self.assertIn("固定阵营漂移", failures)
        self.assertIn("试镜当天", failures)
        self.assertIn("提前把核心角色", failures)
        self.assertIn("没有实际解除", failures)
        self.assertIn("没有完成与固定盟友", failures)

        normalized = _normalize_awakening_role_aliases(
            "我是梅娅·瑞德。经纪人杰克·哈里斯拒绝解约。这里是埃琳娜·马丁内斯。",
            card,
        )
        self.assertIn("我是Maya Reed", normalized)
        self.assertIn("经纪人旧经纪人", normalized)
        self.assertIn("这里是Ethan Cole", normalized)
        self.assertEqual(
            "准备《暗夜之光》试镜。",
            _normalize_planned_work_title_aliases(
                "准备《星河之下》试镜。", {**card, "planned_work_titles": ["暗夜之光"]}
            ),
        )
        self.assertEqual(
            "准备《暗夜之光》试镜。",
            _ensure_planned_work_title_reference(
                "准备关键试镜。", {"planned_work_titles": ["暗夜之光"]}
            ),
        )
        grounded = _append_grounded_awakening_deployment(
            "Maya Reed确认重生，距离关键试镜还有三天。"
            "她已正式解除旧经纪人的代理授权。她拨通Ethan Cole的电话，希望约见，等待回应。",
            card,
        )
        grounded_failures = "\n".join(_chapter_body_hard_failures(grounded, 2, card))
        self.assertNotIn("没有实际解除", grounded_failures)
        self.assertNotIn("没有完成与固定盟友", grounded_failures)
        self.assertNotIn("重复提出", grounded_failures)
        self.assertEqual(1, grounded.count("拨通Ethan Cole"))

        two_step_deployment = (
            "Maya Reed猛然惊醒，检查身体、房间和手机日期，确认自己重生回到了关键试镜前三天。"
            "她正式解除旧经纪人的代理授权，挂断旧经纪人的电话。"
            "接着，Maya Reed拨通Ethan Cole的电话，直说需要见面。"
            "Ethan Cole同意见面，两人确认明天下午四点会面，预约成功。"
        )
        two_step_failures = "\n".join(
            _chapter_body_hard_failures(two_step_deployment, 2, card)
        )
        self.assertNotIn("重复执行与固定盟友", two_step_failures)

        duplicated_ally_call = two_step_deployment + (
            "Maya Reed随后再次拨通Ethan Cole，重复确认会面安排。"
        )
        duplicated_failures = "\n".join(
            _chapter_body_hard_failures(duplicated_ally_call, 2, card)
        )
        self.assertIn("重复执行与固定盟友", duplicated_failures)

    def test_rhetorical_rule_question_is_not_an_invented_rule_citation(self):
        card = {
            "chapter_id": 5,
            "chapter_role_v2": "present_revenge",
            "chapter_milestone": {
                "action": "主角在合作方面前完成现场验真",
                "opponent_reaction": "对手公开质疑主角状态",
                "result": "合作方重新判断主角能力",
            },
        }
        rhetorical_failures = "\n".join(
            _chapter_body_hard_failures(
                "对手冷笑：“谁规定今天必须对标十年前？”"
                "主角没有争辩，只当面完成了这次验真。",
                5,
                card,
            )
        )
        invented_failures = "\n".join(
            _chapter_body_hard_failures(
                "对手宣称根据临时管理规定必须降低验真标准，"
                "并要求所有人立即照办。",
                5,
                card,
            )
        )
        invented_rule_failure = "正文临时发明执行卡未建立的协议编号或条款"
        self.assertNotIn(invented_rule_failure, rhetorical_failures)
        self.assertIn(invented_rule_failure, invented_failures)
        for genuine_citation in (
            "对手声称内部规定明确要求今天必须降低标准。",
            "对手反问：“谁规定今天必须按第三条执行？”",
        ):
            with self.subTest(genuine_citation=genuine_citation):
                failures = "\n".join(
                    _chapter_body_hard_failures(
                        genuine_citation,
                        5,
                        card,
                    )
                )
                self.assertIn(invented_rule_failure, failures)

    def test_failed_prose_patterns_from_live_generation_are_hard_failures(self):
        cast = [
            {"name": "Maya Reed", "alignment": "protagonist"},
            {"name": "Lila Voss", "alignment": "opponent"},
            {"name": "Elena Martinez", "alignment": "ally"},
        ]
        opening_card = {
            "chapter_role_v2": "prev_life_death_only",
            "prev_life_tragedy": (
                "Maya Reed的经纪人当场撤回代理支持；"
                "Lila Voss正式签约角色；Maya Reed服药过量自杀"
            ),
            "planned_work_titles": ["暗夜之光"],
            "canonical_cast": cast,
        }
        weak_opening = (
            "Maya Reed完成试镜，Lila Voss说她不合适。她回家服药过量，"
            "呼吸停止并死亡，脑海浮现另一世的画面。"
        )
        opening_failures = "\n".join(
            _chapter_body_hard_failures(weak_opening, 1, opening_card)
        )
        self.assertIn("核心作品名", opening_failures)
        self.assertIn("旧经纪人", opening_failures)
        self.assertIn("Lila Voss", opening_failures)
        self.assertIn("另一世", opening_failures)

        grounded_betrayal = (
            "Maya Reed完成《暗夜之光》最终试镜。旧经纪人绕过她走到Lila Voss身边，"
            "当众说：“从这一刻起，我不再代表你。”随后宣布自己将担任Lila Voss的独家代理。"
            "Lila Voss当场签下女主角合同。Maya Reed回到公寓后吞下过量药物，"
            "呼吸断绝，心脏停止搏动，最终死去。"
        )
        grounded_betrayal_failures = "\n".join(
            _chapter_body_hard_failures(grounded_betrayal, 1, opening_card)
        )
        self.assertNotIn("遗漏核心背叛", grounded_betrayal_failures)
        self.assertNotIn("可见阵营转移", grounded_betrayal_failures)
        self.assertNotIn("遗漏不可逆损失", grounded_betrayal_failures)

        grounded_from_partial = _ground_opening_betrayal_before_home(
            "Maya Reed完成《暗夜之光》试镜，却被一句话淘汰。Maya Reed回到公寓，关上门。",
            opening_card,
        )
        self.assertLess(grounded_from_partial.index("我不再代表你"), grounded_from_partial.index("回到公寓"))
        self.assertIn("Lila Voss看着Maya Reed，当场签下名字", grounded_from_partial)

        already_complete = (
            "旧经纪人走到Lila Voss身边，当众说从这一刻起我不再代表Maya Reed，"
            "接下来《暗夜之光》事务由我全权跟进。Lila Voss接过合同签下名字，"
            "官方通告确认她加盟主演。公寓楼道感应灯亮起，Maya Reed刷卡进门。"
        )
        self.assertEqual(
            already_complete,
            _ground_opening_betrayal_before_home(already_complete, opening_card),
        )

        awakening_card = {
            "chapter_role_v2": "rebirth_awakening_only",
            "this_life_revenge": (
                "Maya Reed解除旧经纪人的代理授权并联系Elena Martinez预约会面"
            ),
            "planned_work_titles": ["暗夜之光"],
            "canonical_cast": cast,
        }
        fake_completion = (
            "Maya Reed猛然惊醒，检查身体、房间和手机日期，确认自己重生回到《暗夜之光》试镜前三天。"
            "她写好解除代理协议，打印后放在桌上。她拨通Elena Martinez的电话，希望预约见面。"
            "对方说会安排。Maya Reed回答越快越好，我在等你的回复。"
        )
        awakening_failures = "\n".join(
            _chapter_body_hard_failures(fake_completion, 2, awakening_card)
        )
        self.assertIn("没有实际解除并送达", awakening_failures)
        self.assertIn("没有完成与固定盟友", awakening_failures)

        setup_card = {
            "chapter_role_v2": "present_setup",
            "planned_work_titles": ["暗夜之光"],
            "canonical_cast": cast,
        }
        repeated_setup = (
            "Maya Reed在《暗夜之光》试镜中开始表演独白，表演结束后，"
            "Elena Martinez宣布接下来是复试环节，请Maya Reed留下。\n\n"
            "Maya走下舞台，脚步依然稳如磐石，她知道这一战赢了，但这只是第一步。\n\n"
            "Lila Voss脸色发白。Elena Martinez再次宣布接下来是复试环节，请Maya Reed留下。"
            "她知道自己又一次失去了主导权，而。\n\n"
            "Maya走下舞台，脚步依然稳如磐石，她知道这一战赢了，但这只是第一步。"
        )
        setup_failures = "\n".join(
            _chapter_body_hard_failures(repeated_setup, 3, setup_card)
        )
        self.assertIn("重复", setup_failures)
        self.assertIn("病句", setup_failures)

        revenge_card = {
            "chapter_role_v2": "present_revenge",
            "this_life_revenge": "Maya Reed即兴演绎关键片段",
            "core_payoff": "Maya Reed获得《暗夜之光》女主角合约，Lila Voss失去该角色",
            "planned_work_titles": ["暗夜之光"],
            "canonical_cast": cast,
        }
        corrupt_payoff = (
            "Maya Reed在《暗夜之光》终选开始即兴演绎，收住最后一个动作。"
            "Elena Martinez宣布由导演饰演女主角，Lila Voss此前签署的合同今日终止。"
            "编剧兼联合导演制片负责人向经纪人选角助理点头。"
        )
        revenge_failures = "\n".join(
            _chapter_body_hard_failures(corrupt_payoff, 4, revenge_card)
        )
        self.assertIn("职位", revenge_failures)
        self.assertIn("凭空补造", revenge_failures)

        english_drift = (
            "Maya Reed stood in the audition room and watched every face turn away. "
            "She knew the role was gone, but the silence hurt more than the verdict. " * 45
        )
        self.assertTrue(any(
            "语言漂移" in failure
            for failure in _chapter_body_hard_failures(english_drift, 3, {})
        ))

    def test_performance_scene_rejects_unplanned_evidence_inventory(self):
        card = {
            "chapter_role_v2": "present_revenge",
            "chapter_goal": "在合作方与独立现场见证人在场时做高强度唱跳连测",
            "this_life_revenge": "麦珂完成高强度唱跳连测",
            "core_payoff": "合作方撤下病弱宣传，麦珂收回训练强度决定权",
            "must_resolve_this_chapter": [
                "完成高强度唱跳连测",
                "合作方撤下病弱宣传",
            ],
            "chapter_must_include": ["卡尔试图降低强度"],
            "cluster_chapter_index": 1,
            "info_gap_from_prev_life": "卡尔会用降低强度坐实病弱形象",
            "canonical_cast": [
                {"name": "麦珂·杰森", "role": "歌手", "alignment": "protagonist"},
                {"name": "卡尔·霍尔特", "role": "巡演总监", "alignment": "opponent"},
            ],
        }
        bad = (
            "麦珂说不热身，要求立刻进行“最终校准”。第一段星轨副歌前奏里，"
            "他全程不换气，靠腹横肌对抗重力。独立见证人架起摄像机，"
            "行政专员从档案室取出密封存档袋和原始交接单。"
            "体能评估报告被投到平板上，同步法务双通道，落点误差只有七厘米。"
            "麦珂完成唱跳，合作方撤下病弱宣传，把训练强度决定权交还给他。"
            "门外物流车送来升降台基座，保险绳卡扣闪着冷光。"
        )
        failures = "\n".join(_chapter_body_hard_failures(bad, 5, card))
        self.assertIn("封闭证据清单", failures)
        self.assertIn("临时命名执行卡未建立", failures)
        self.assertIn("歌曲或表演段落取名", failures)
        self.assertIn("危险特技或伪生理解释", failures)
        self.assertIn("设备、车辆或安全事故支线", failures)

        clean = (
            "麦珂认出卡尔上一世惯用的降配借口，当场要求照原强度连唱带跳。"
            "卡尔抢先说他撑不过整段，合作方的人都站在排练场边。"
            "第一段前奏响起，麦珂从第一拍一直完成到收尾，换气仍稳，最后一个动作干净落定。"
            "独立见证人只说测试通过。合作方立即撤下病弱宣传，"
            "把训练强度决定权交还给麦珂。卡尔嘴硬地合上排程本，却不敢再降强度。"
        )
        clean_failures = "\n".join(_chapter_body_hard_failures(clean, 5, card))
        self.assertNotIn("封闭证据清单", clean_failures)
        self.assertNotIn("临时命名执行卡未建立", clean_failures)
        self.assertTrue(_has_tangible_payoff(clean, card))

        natural_tail = clean.replace(
            "卡尔嘴硬地合上排程本，却不敢再降强度。",
            (
                "\n\n卡尔攥紧控台边缘，低声道：“你早安排好了？”"
                "\n\n麦珂戴正礼帽：“是你总用同一招。”"
                "\n\n卡尔没再反驳。"
            ),
        )
        natural_tail_failures = "\n".join(
            _chapter_body_hard_failures(natural_tail, 5, card)
        )
        self.assertNotIn("多轮反应与离场段落", natural_tail_failures)

        micro_expanded = _insert_closed_scene_micro_expansion(
            (
                "麦珂继续唱跳。\n\n"
                "卡尔忽然喊道：“暂停！”\n\n"
                "麦珂没有停，继续唱到最后一个音，稳稳收势。\n\n"
                "见证人说：“测试通过。”\n\n"
                "训练强度决定权归还麦珂·杰森。"
            ),
            "他在主歌里转身踏步，卡尔的脸色逐渐发紧。",
            card,
        )
        self.assertLess(
            micro_expanded.index("主歌里转身踏步"),
            micro_expanded.index("卡尔忽然喊道"),
        )

        normalized_performance = _normalize_closed_scene_surface_drift(
            clean
            + "那件衣服的褶皱走向和上一章完全一样。"
            + "第七分钟，他唱完剩下十六个小节，又跃起半尺，侧滑半尺，"
            + "踩完三组十六分音符节奏，再完成接下来十六秒动作。"
            + "第三段主歌里，他在第四拍后拖足八拍，十秒后移开三毫米。",
            card,
        )
        self.assertNotIn("上一章", normalized_performance)
        self.assertNotIn("第七分钟", normalized_performance)
        self.assertNotIn("十六个小节", normalized_performance)
        self.assertNotIn("跃起半尺", normalized_performance)
        self.assertNotIn("侧滑半尺", normalized_performance)
        self.assertNotIn("十六分音符", normalized_performance)
        self.assertNotIn("接下来十六秒", normalized_performance)
        self.assertNotIn("第三段主歌", normalized_performance)
        self.assertNotIn("第四拍", normalized_performance)
        self.assertNotIn("拖足八拍", normalized_performance)
        self.assertNotIn("十秒后", normalized_performance)
        self.assertNotIn("三毫米", normalized_performance)
        self.assertIn("表演进行到中段", normalized_performance)
        self.assertIn("余下的乐段", normalized_performance)

        normalized_device_evidence = _normalize_closed_scene_surface_drift(
            clean
            + "控台屏幕跳出一条波形，读数证明他的气息没有偏差。"
            + "见证人盯着显示屏说：“测试通过。”",
            card,
        )
        self.assertNotIn("屏幕", normalized_device_evidence)
        self.assertNotIn("波形", normalized_device_evidence)
        self.assertNotIn("读数", normalized_device_evidence)
        self.assertIn("现场见证人说：“测试通过。”", normalized_device_evidence)
        normalized_device_failures = "\n".join(
            _chapter_body_hard_failures(normalized_device_evidence, 5, card)
        )
        self.assertNotIn("控台屏幕或波形读数", normalized_device_failures)

        normalized_measurement = _normalize_closed_scene_surface_drift(
            clean
            + "\n\n他的膝盖弯到四十五度，落点偏差只有三毫米。"
            + "麦珂踏稳节拍继续唱下去。",
            card,
        )
        self.assertNotIn("四十五度", normalized_measurement)
        self.assertNotIn("三毫米", normalized_measurement)
        self.assertIn("麦珂踏稳节拍继续唱下去", normalized_measurement)
        normalized_measurement_failures = "\n".join(
            _chapter_body_hard_failures(normalized_measurement, 5, card)
        )
        self.assertNotIn("测量精度", normalized_measurement_failures)
        self.assertIn("\n\n", normalized_measurement)

        counted_superhuman = clean + (
            "第三次侧移时他完成九十度转身，每一步都踩在毫厘之间，"
            "全程未喘息，仿佛精确的机械律动。"
        )
        counted_superhuman_failures = "\n".join(
            _chapter_body_hard_failures(counted_superhuman, 5, card)
        )
        self.assertIn("精确轮次、角度或超人生理", counted_superhuman_failures)

        reopened_after_settlement = clean + (
            "卡尔争辩说麦珂侧移时抬脚慢了，音准偏高，换气卡在尾音。"
        )
        reopened_after_settlement_failures = "\n".join(
            _chapter_body_hard_failures(reopened_after_settlement, 5, card)
        )
        self.assertIn("权限归还后又让对手展开技术挑错", reopened_after_settlement_failures)
        human_reject_surface = (
            "麦珂手里捏着旧宣传页，随后开始唱跳。"
            + clean
            + "动作衔接待续接续。卡尔说：“我跳得比他稳，节拍没乱过。”"
            "麦珂说：“你摆臂慢了半拍，换气声太重。”"
        )
        human_reject_surface_failures = "\n".join(
            _chapter_body_hard_failures(human_reject_surface, 5, card)
        )
        self.assertIn("旧宣传页在见证通过前提前", human_reject_surface_failures)
        self.assertIn("拼接病句", human_reject_surface_failures)
        self.assertIn("权限归还后又让对手展开技术挑错", human_reject_surface_failures)
        human_reject_stunts = clean + (
            "麦珂跃起旋身，又单膝点地再暴起，全程无喘息，也没吸气。"
            "卡尔说：“你撑不了三天。”"
            "麦珂说：“那你明天来数我第几组。”"
        )
        human_reject_stunt_failures = "\n".join(
            _chapter_body_hard_failures(human_reject_stunts, 5, card)
        )
        self.assertIn("危险动作、解剖观察", human_reject_stunt_failures)
        self.assertIn("权限归还后又让对手展开技术挑错", human_reject_stunt_failures)

        dangerous_stage_display = clean + (
            "他腾空转体，接三连滑步，又单膝跪地暴起。"
            "卡尔盯着他的肋廓、锁骨和后颈筋络。"
            "麦珂说自己昨天跑完五公里山道。"
        )
        dangerous_stage_failures = "\n".join(
            _chapter_body_hard_failures(dangerous_stage_display, 5, card)
        )
        self.assertIn("危险动作、解剖观察", dangerous_stage_failures)

        normalized_common_anatomy = _normalize_closed_scene_surface_drift(
            clean + "\n\n第二遍唱起时，卡尔喉结滚动，盯着麦珂胸腔与肋廓。",
            card,
        )
        self.assertNotIn("第二遍", normalized_common_anatomy)
        self.assertNotIn("喉结", normalized_common_anatomy)
        self.assertNotIn("胸腔", normalized_common_anatomy)
        self.assertNotIn("肋廓", normalized_common_anatomy)

        cluster_mixed_card = {
            **card,
            "this_life_revenge": "先做体能测试，再核对封签、送货单和领用簿",
        }
        mixed_failures = "\n".join(
            _chapter_body_hard_failures(
                clean + "被撤下的旧海报墨迹新鲜。",
                5,
                cluster_mixed_card,
            )
        )
        self.assertNotIn("伪医学或伪法证", mixed_failures)

        performance_drift = clean + (
            "卡尔说心率没稳，让医护组递来电解质液。第三段副歌里，麦珂旋转多一圈。"
            "合作方又抽出另一份崭新样稿。麦珂在虎口画了一道线。"
            "卡尔承认自己签了我的名字。麦珂露出上个月彩排摔伤留下的浅疤，"
            "接着单膝跪地滚翻，再做三百六十度腾空拧身。"
            "主管确认书压在视觉母版下，胶层拉出细丝。"
            "卡尔盯着麦珂肋廓起伏和肌肉收缩，直到他唱完十六个小节。"
            "见证人看了眼腕表。旧海报上印着一行斜体字。"
            "麦珂单掌撑地旋身而起。"
            "旧宣传单页写着三句文案，墨色浓淡不均。"
            "见证人不记、不数、不掐秒。"
            "麦珂手腕有常年户外彩排留下的晒痕。"
            "昨天签下的主管确认留在桌上。"
            "病弱宣传初稿字体偏软，色调泛青。"
            "麦珂连续踢腿，膝盖提至齐胸。"
            "控台凸钮是卡尔上周亲手抠下来的。"
            "麦珂连跳三组八拍组合，第三段副歌仍未停。"
            "他在第三段主歌的两拍间隙向前滑了半寸。"
            "卡尔先喊“停一下！”，片刻后又喊“暂停！”"
        )
        performance_drift_failures = "\n".join(
            _chapter_body_hard_failures(performance_drift, 5, card)
        )
        self.assertIn("临时医疗史", performance_drift_failures)
        self.assertIn("新增替换样稿", performance_drift_failures)
        self.assertIn("在皮肤写画", performance_drift_failures)
        self.assertIn("冒签或伪造主角签名", performance_drift_failures)
        self.assertIn("危险特技", performance_drift_failures)
        self.assertIn("额外确认文书", performance_drift_failures)
        self.assertIn("宣传物料证据化", performance_drift_failures)
        self.assertIn("解剖观察", performance_drift_failures)
        self.assertIn("见证人用腕表", performance_drift_failures)
        self.assertIn("带文字内容", performance_drift_failures)
        self.assertIn("单掌", performance_drift_failures)
        self.assertIn("创作限制", performance_drift_failures)
        self.assertIn("晒痕", performance_drift_failures)
        self.assertIn("额外确认文书", performance_drift_failures)
        self.assertIn("带文字内容", performance_drift_failures)
        self.assertIn("齐胸", performance_drift_failures)
        self.assertIn("道具前史", performance_drift_failures)
        self.assertIn("精确小节数", performance_drift_failures)
        self.assertIn("重复出现多次口头叫停", performance_drift_failures)

        inflated_payoff = clean + (
            "卡尔望着调度令、排期表和医疗备注单一同坠地，碎成粉末。"
        )
        inflated_payoff_failures = "\n".join(
            _chapter_body_hard_failures(inflated_payoff, 5, card)
        )
        self.assertIn("排期、调度或医疗权限同时失效", inflated_payoff_failures)

        dragged_ending = clean + ("结算后又喝水、叠毛巾、看天气。" * 60)
        dragged_ending_failures = "\n".join(
            _chapter_body_hard_failures(dragged_ending, 5, card)
        )
        self.assertIn("象征性冷却段", dragged_ending_failures)

        prompt = _build_closed_evidence_scene_prompt(
            5,
            {**card, "cluster_chapter_index": 1, "info_gap_from_prev_life": "上一世病弱降配旧招"},
            prev_tail_scene="卡尔的签字仍留在桌上。",
        )
        self.assertIsNotNone(prompt)
        self.assertIn("【事实白名单】", prompt)
        self.assertIn("【八个正向节拍】", prompt)
        self.assertIn("验真依据只有现场听见和看见的唱跳完成度", prompt)
        self.assertIn("麦珂·杰森记得，上一世", prompt)
        self.assertIn("提前”请合作方代表和现场见证人", prompt)
        self.assertIn("卡尔·霍尔特果然", prompt)
        self.assertNotIn("卡尔的签字仍留在桌上", prompt)
        self.assertIn("前场纸面结果已经生效", prompt)
        self.assertIn("不把前场签字、桌面文件、排期表或其他纸面道具带入本场", prompt)
        self.assertIn("卡尔·霍尔特不再有权降低训练强度", prompt)
        self.assertIn("旧宣传页在正文中只称“旧宣传页”", prompt)
        self.assertIn("这些即使出现在情节组的其他章节，也不得提前进入本章", prompt)
        self.assertIn("不得跳跃、腾空、跪地、撑地、翻滚", prompt)
        self.assertIn("上轮草稿已经作废，不提供也不继承其内容", prompt)
        self.assertNotIn("心率", prompt)
        self.assertNotIn("确认书", prompt)
        self.assertNotIn("胶痕", prompt)
        segment_plan = _closed_scene_segment_plan(card)
        self.assertIsNotNone(segment_plan)
        segment_facts, segment_specs = segment_plan
        self.assertEqual(8, len(segment_specs))
        self.assertIn("地点只有排练场", segment_facts)
        self.assertIn("合作方代表一人、现场见证人一人", segment_facts)
        self.assertIn("结果已经在这里", segment_specs[-1][2])
        self.assertIn("本段禁用踏步", segment_specs[-1][2])
        fill_at, validation_index, fill_beat = _segmented_closed_scene_fill_spec(
            card,
            len(segment_specs),
        )
        self.assertEqual(3, fill_at)
        self.assertEqual(3, validation_index)
        self.assertIn("叫停前", fill_beat)
        self.assertIn("不得使用身体部位", fill_beat)
        segment_prompt = _build_closed_scene_segment_prompt(
            5,
            segment_facts,
            3,
            8,
            *segment_specs[2][:2],
            segment_specs[2][2],
            "音乐刚刚响起。",
        )
        self.assertIn("第3/8段", segment_prompt)
        self.assertIn("不写整章", segment_prompt)
        self.assertIn("使用七至九个主谓完整的句子", segment_prompt)
        self.assertIn("不得出现针剂、药品、封签、送货单、领用簿、钥匙", segment_prompt)
        with patch.dict("os.environ", {
            "V2_ENABLE_API_SEGMENT_RECOVERY": "1",
            "V2_ALLOW_TEMPLATE_PROSE_FALLBACK": "0",
        }, clear=True):
            self.assertFalse(_should_use_api_segment_recovery(card, 1))
            self.assertTrue(_should_use_api_segment_recovery(card, 2))
        with patch.dict("os.environ", {
            "V2_ENABLE_API_SEGMENT_RECOVERY": "1",
            "V2_ALLOW_TEMPLATE_PROSE_FALLBACK": "1",
        }, clear=True):
            self.assertFalse(_should_use_api_segment_recovery(card, 2))
        self.assertTrue(_closed_scene_segment_candidate_failure(
            "麦珂腾空倒立，卡尔盯着他的肋骨，十秒后喊停。",
            card,
            3,
        ))
        self.assertTrue(_closed_scene_segment_candidate_failure(
            "第二组节拍里，麦珂气息沉入丹田，胸廓与肋间肌随歌声舒张。",
            card,
            3,
        ))
        self.assertTrue(_closed_scene_segment_candidate_failure(
            "两位现场见证人在三米外看着麦珂。",
            card,
            1,
        ))
        self.assertTrue(_closed_scene_segment_candidate_failure(
            "卡尔·霍尔特记得上一世的排练。",
            card,
            1,
        ))
        self.assertFalse(_closed_scene_segment_candidate_failure(
            "麦珂记得，上一世，卡尔用过降配旧招。"
            "他示意合作方代表和现场见证人在折叠椅上落座。"
            "卡尔站在控台旁，麦珂看向他，排练场里还没有歌声。",
            card,
            1,
        ))
        self.assertFalse(_closed_scene_segment_candidate_failure(
            "麦珂记得，上一世，卡尔用过降配旧招。"
            "他示意合作方代表和现场见证人落座，随后抬起左臂，"
            "掌心向下，指尖对准控台旁的卡尔。",
            card,
            1,
        ))
        self.assertTrue(_closed_scene_segment_candidate_failure(
            "麦珂从第六步开始转身，第七步侧移两尺，音高仍没有变化。",
            card,
            3,
        ))
        self.assertTrue(_closed_scene_segment_candidate_failure(
            "合作方代表翻开记事本，低头写了两行字，笔尖没有停下。",
            card,
            1,
        ))
        self.assertTrue(_closed_scene_segment_candidate_failure(
            "现场见证人说：“测试通过。”合作方代表撤下旧宣传页。"
            "麦珂随后继续踏步转身，歌声仍贴着节拍向前。",
            card,
            6,
        ))
        self.assertTrue(_closed_scene_segment_candidate_failure(
            "卡尔说：“这节拍太赶了。”麦珂说：“结果已经落定。”"
            "卡尔低头不再说话。",
            card,
            8,
        ))
        shaped_performance_close = _shape_closed_scene_segment_candidate(
            "卡尔嘴硬道：“你只是运气好。”"
            "麦珂说：“结果已经在这里。”",
            card,
            120,
            8,
        )
        self.assertIn("你只是运气好", shaped_performance_close)
        self.assertNotIn("决定已经生效", shaped_performance_close)
        self.assertFalse(_closed_scene_segment_candidate_failure(
            shaped_performance_close,
            card,
            8,
        ))
        repaired_motive = _ensure_performance_previous_life_action(
            "卡尔站在控台旁。麦珂要求按原强度开始。",
            card,
        )
        self.assertIn("上一世", repaired_motive)
        self.assertIn("提前请合作方代表和现场见证人", repaired_motive)
        self.assertFalse(any(
            "上一世信息差" in failure
            for failure in _chapter_body_hard_failures(repaired_motive, 5, card)
        ))
        already_grounded = _ensure_performance_previous_life_action(
            repaired_motive,
            card,
        )
        self.assertEqual(repaired_motive, already_grounded)
        explicit_memory_subject = _ensure_performance_previous_life_action(
            "麦珂看向卡尔。卡尔低头调旋钮，他记得清清楚楚，上一世，"
            "卡尔就是这样降配。麦珂提前请合作方代表和现场见证人到了排练场。",
            card,
        )
        self.assertIn("麦珂记得清清楚楚，上一世", explicit_memory_subject)
        self.assertNotIn("他记得清清楚楚，上一世", explicit_memory_subject)
        deterministic_open = _shape_closed_scene_segment_candidate(
            "",
            card,
            195,
            1,
        )
        self.assertIn("麦珂记得，上一世，卡尔用过降配旧招", deterministic_open)
        self.assertIn("提前请合作方代表和现场见证人", deterministic_open)
        self.assertFalse(_closed_scene_segment_candidate_failure(
            deterministic_open,
            card,
            1,
        ))
        deterministic_preparation = _shape_closed_scene_segment_candidate(
            "",
            card,
            175,
            2,
        )
        self.assertIn("慢一点，别勉强", deterministic_preparation)
        self.assertIn("按原强度开始", deterministic_preparation)
        self.assertFalse(_closed_scene_segment_candidate_failure(
            deterministic_preparation,
            card,
            2,
        ))
        deterministic_start = _shape_closed_scene_segment_candidate(
            "",
            card,
            225,
            3,
        )
        self.assertIn("音乐响起", deterministic_start)
        self.assertFalse(_closed_scene_segment_candidate_failure(
            deterministic_start,
            card,
            3,
        ))
        deterministic_performance_segments = [
            _shape_closed_scene_segment_candidate(
                "",
                card,
                segment_spec[1],
                index,
            )
            for index, segment_spec in enumerate(segment_specs, start=1)
        ]
        deterministic_performance = "\n\n".join(deterministic_performance_segments)
        reflowed_performance = _reflow_segmented_scene_paragraphs(
            deterministic_performance_segments,
            card,
        )
        reflowed_paragraphs = [
            paragraph
            for paragraph in reflowed_performance.split("\n\n")
            if paragraph.strip()
        ]
        self.assertGreaterEqual(len(reflowed_paragraphs), 8)
        self.assertLessEqual(len(reflowed_paragraphs), 14)
        self.assertNotEqual(deterministic_performance, reflowed_performance)
        deterministic_performance_failures = "\n".join(
            _chapter_body_hard_failures(deterministic_performance, 5, card)
        )
        self.assertGreaterEqual(len(deterministic_performance), 1000)
        self.assertIn(
            "后续训练按麦珂·杰森本人确认的强度执行",
            deterministic_performance,
        )
        self.assertEqual("", deterministic_performance_failures)
        shaped_performance = _shape_closed_scene_segment_candidate(
            "麦珂踏步转身，歌声稳稳跟住节拍。"
            "他的胸腔发力，肌肉随节奏收缩。"
            "第二组节拍里，他从丹田托起气息，胸廓与肋间肌一同舒张。"
            "卡尔的手离开控台，视线追着他的脚步。",
            card,
            60,
        )
        self.assertNotIn("胸腔", shaped_performance)
        self.assertNotIn("肌肉", shaped_performance)
        self.assertNotIn("丹田", shaped_performance)
        self.assertNotIn("胸廓", shaped_performance)
        self.assertNotIn("肋间肌", shaped_performance)
        self.assertIn("歌声稳稳跟住节拍", shaped_performance)
        self.assertLessEqual(len(shaped_performance), 60)
        clause_cleaned_performance = _shape_closed_scene_segment_candidate(
            "麦珂踏步转身，气息沉入丹田，歌声仍稳稳贴住节拍。",
            card,
            80,
            3,
        )
        self.assertEqual("", clause_cleaned_performance)
        clause_cleaned_stop = _shape_closed_scene_segment_candidate(
            "卡尔的手压住控台，视线盯着麦珂起伏的胸廓，"
            "终于喊道：“停一下！”",
            card,
            100,
            4,
        )
        self.assertNotIn("胸廓", clause_cleaned_stop)
        self.assertIn("停一下", clause_cleaned_stop)
        self.assertFalse(_closed_scene_segment_candidate_failure(
            clause_cleaned_stop,
            card,
            4,
        ))
        deterministic_stop = _shape_closed_scene_segment_candidate(
            "卡尔的手压住控台，脸色一点点沉下去。",
            card,
            100,
            4,
        )
        self.assertIn("卡尔·霍尔特喊道：“停一下！”", deterministic_stop)
        self.assertFalse(_closed_scene_segment_candidate_failure(
            deterministic_stop,
            card,
            4,
        ))
        overdescribed_performance = _shape_closed_scene_segment_candidate(
            "麦珂的汗珠滑过胸膛，脉搏在腕骨下跳动，"
            "歌声仍稳稳贴着节拍向前推进。",
            card,
            100,
            3,
        )
        self.assertNotIn("汗", overdescribed_performance)
        self.assertNotIn("脉搏", overdescribed_performance)
        self.assertEqual("", overdescribed_performance)
        human_reject_v7 = (
            "卡尔忽然想碰耳机，目光落向左前方。"
            "他盯着那套重复三次的踏步，嘴唇一紧了一次。"
            "麦珂唱完最后一个乐句，咽下余韵，双肩沉稳如初。"
        )
        self.assertTrue(_closed_scene_segment_candidate_failure(
            human_reject_v7,
            card,
            4,
        ))
        human_reject_v7_failures = "\n".join(
            _chapter_body_hard_failures(clean + human_reject_v7, 5, card)
        )
        self.assertIn("表演验真出现拼接病句", human_reject_v7_failures)
        self.assertIn("表演验真加入危险动作", human_reject_v7_failures)
        human_reject_v8 = (
            "歌声稳得像钉入地板，麦珂盯着脚掌落点压低重心。"
            "外套下摆扬起，他把麦克风搁回支架，指尖擦过金属外壳。"
        )
        self.assertTrue(_closed_scene_segment_candidate_failure(
            human_reject_v8,
            card,
            5,
        ))
        human_reject_v8_failures = "\n".join(
            _chapter_body_hard_failures(clean + human_reject_v8, 5, card)
        )
        self.assertIn("表演验真加入危险动作", human_reject_v8_failures)
        staged_limb_and_light = _shape_closed_scene_segment_candidate(
            "麦珂双足并拢站定，右手垂在身侧，左手微抬示意结束。"
            "折叠椅在光里投出浅影。",
            card,
            160,
            5,
        )
        self.assertEqual("", staged_limb_and_light)
        micro_prompt = _build_closed_scene_micro_expansion_prompt(
            5,
            clean,
            card,
            120,
        )
        self.assertIsNotNone(micro_prompt)
        self.assertIn("对手口头叫停前", micro_prompt)
        self.assertIn("绝不能提前或重复这些动作", micro_prompt)
        self.assertIn("观众席、聚光灯", micro_prompt)
        self.assertIn("【结构化衔接摘要】", micro_prompt)
        self.assertNotIn("【原章上下文】", micro_prompt)

        natural_dance_motion = clean + (
            "麦珂手臂划开空气，指尖带出利落弧线。"
            "卡尔指甲陷进掌心，却不敢再叫停。"
        )
        natural_motion_failures = "\n".join(
            _chapter_body_hard_failures(natural_dance_motion, 5, card)
        )
        self.assertNotIn("在皮肤写画", natural_motion_failures)

        explicit_skin_mark = clean + "麦珂在虎口画了一道线，又在手臂内侧写下记号。"
        explicit_skin_mark_failures = "\n".join(
            _chapter_body_hard_failures(explicit_skin_mark, 5, card)
        )
        self.assertIn("在皮肤写画", explicit_skin_mark_failures)

        described_promo = clean + (
            "墙上的宣传页画面里是灰色剪影，标题字小而软，整体色调偏灰。"
        )
        described_promo_failures = "\n".join(
            _chapter_body_hard_failures(described_promo, 5, card)
        )
        self.assertIn("带文字内容的新证据或文案", described_promo_failures)

        invented_rehearsal_space = clean + (
            "聚光灯照亮观众席，仿佛十万观众正在屏息。气息沉入丹田。"
        )
        invented_space_failures = "\n".join(
            _chapter_body_hard_failures(invented_rehearsal_space, 5, card)
        )
        self.assertIn("观众席、公众观众或舞台聚光灯", invented_space_failures)
        self.assertIn("解剖观察", invented_space_failures)

    def test_paper_audit_rejects_extra_forensics_and_processes(self):
        card = {
            "chapter_role_v2": "present_revenge",
            "chapter_goal": "当面核对针剂封签、送货单和领用簿并要求更换保管人",
            "this_life_revenge": "核对封签、送货单和领用簿",
            "core_payoff": "康拉德被暂停职务，麦珂获得药品保管权",
            "must_resolve_this_chapter": [
                "核对针剂封签、送货单和领用簿",
                "康拉德被暂停职务，麦珂获得药品保管权",
            ],
            "chapter_must_include": ["康拉德试图辩解"],
            "canonical_cast": [
                {"name": "麦珂·杰森", "role": "歌手", "alignment": "protagonist"},
                {"name": "康拉德·莫里森", "role": "私人医生", "alignment": "opponent"},
            ],
        }
        bad = (
            "康拉德拿出标着“镇静复合制剂A型”的针剂。麦珂嗅了嗅甜腥味，"
            "又从机器压纹判断斜切口角度不对。他调出销毁清单和报废编号，"
            "公开目录写着中枢抑制成分，生理监测仪和值班日志也被搬来。"
            "腕表开启录音，法务邮件同步董事会备案。康拉德身侧露出枪套，"
            "还搬来带专用槽的密码箱，声称双签制度允许豁免。"
            "批号甲乙不符，盖的是三天前日期，签收栏空白，墨迹还没干。"
            "这时侧门推开，行政监察组主角走进来，拿出临时监管授权册并加盖红色公章。"
            "**主角宣布暂停职务。**"
            "麦珂撕开封膜，把针头探入瓶内抽吸药液。"
        )
        failures = "\n".join(_chapter_body_hard_failures(bad, 6, card))
        self.assertIn("封闭证据清单", failures)
        self.assertIn("临时命名执行卡未建立", failures)
        self.assertIn("伪医学或伪法证", failures)
        self.assertIn("未建立的审批或制度", failures)
        self.assertIn("武器或威胁道具", failures)
        self.assertIn("英文词", failures)
        self.assertIn("擅自开封、抽取或操作针剂", failures)
        self.assertIn("多处矛盾维度", failures)
        self.assertIn("权限者突然进门裁决", failures)
        self.assertIn("创作标签或 Markdown", failures)
        self.assertIn("暂停职务", failures)
        self.assertIn("药品保管权", failures)

        clean = (
            "麦珂记得，上一世康拉德总把“先用后补”说成笔误或补记。"
            "现场负责人从开场就站在桌边。麦珂让康拉德把针剂封签、送货单和领用簿并排放在桌上。"
            "麦珂掀开领用簿，未拆针剂的封签始终保持原样。"
            "封签上的编号与送货单一致，领用簿却比送货数量多记一支，"
            "其余内容完全一致。康拉德辩称只是补记失误。"
            "现场负责人说：“即刻暂停你的职务。”康拉德被停职，只能交出药品柜钥匙和领用簿。"
            "负责人确认：“药品保管权归麦珂·杰森。”麦珂接过钥匙。"
            "麦珂说：“没有我的许可，谁也不能碰这些药。”"
            "康拉德伸手想夺，最终只能僵在桌边。"
        )
        clean_failures = "\n".join(_chapter_body_hard_failures(clean, 6, card))
        self.assertNotIn("封闭证据清单", clean_failures)
        self.assertNotIn("伪医学或伪法证", clean_failures)
        self.assertNotIn("未建立的审批或制度", clean_failures)
        self.assertNotIn("多处矛盾维度", clean_failures)
        self.assertNotIn("擅自开封、抽取或操作针剂", clean_failures)
        self.assertNotIn("执行卡要求对手被暂停职务", clean_failures)
        self.assertNotIn("本簇收尾章缺少可见兑现", clean_failures)
        self.assertTrue(_has_tangible_payoff(clean, card))
        alias_handoff_segment = (
            "康拉德将唯一钥匙放在负责人掌心，又交出领用簿。"
            "负责人说：“药品保管权归麦珂·杰森。”"
            "负责人随即把钥匙放到麦珂掌心，麦珂当场接住。"
        )
        self.assertFalse(_closed_scene_segment_candidate_failure(
            alias_handoff_segment,
            card,
            6,
        ))
        self.assertTrue(_closed_scene_segment_candidate_failure(
            alias_handoff_segment + "桌上还摆着七枚未拆封签。",
            card,
            6,
        ))
        self.assertFalse(_closed_scene_segment_candidate_failure(
            alias_handoff_segment.replace("放到麦珂掌心", "置于麦珂掌心"),
            card,
            6,
        ))
        self.assertTrue(_closed_scene_segment_candidate_failure(
            alias_handoff_segment + "康拉德又在领用簿第三栏签下姓名。",
            card,
            6,
        ))
        human_reject_paper = clean + (
            "窗外风声吹动窗帘，康拉德喉结滚动，舌尖抵住上颚。"
            "负责人盯着油墨、撇捺和那一横留下的浅痕。"
            "负责人说：“即刻暂停你的职务。”。"
        )
        human_reject_paper_failures = "\n".join(
            _chapter_body_hard_failures(human_reject_paper, 6, card)
        )
        self.assertIn("环境添景、身体特写或字迹笔画", human_reject_paper_failures)
        self.assertIn("拼接病句", human_reject_paper_failures)
        human_reject_seal_and_key = clean.replace(
            "麦珂掀开领用簿，未拆针剂的封签始终保持原样。",
            "麦珂说：“请现在打开封签。”却未开口。"
            "负责人按住封签边缘，掌中已经垂着一枚铜色钥匙。",
        )
        human_reject_seal_key_failures = "\n".join(
            _chapter_body_hard_failures(human_reject_seal_and_key, 6, card)
        )
        self.assertIn("环境添景、身体特写或字迹笔画", human_reject_seal_key_failures)
        self.assertIn("交接来源断裂", human_reject_seal_key_failures)

        missing_memory = clean.replace(
            "麦珂记得，上一世康拉德总把“先用后补”说成笔误或补记。",
            "",
        )
        missing_memory_failures = "\n".join(
            _chapter_body_hard_failures(missing_memory, 6, card)
        )
        self.assertIn("缺少重生反杀的因果", missing_memory_failures)

        repaired_memory = _ensure_medication_audit_previous_life_motive(
            missing_memory,
            card,
        )
        self.assertIn(
            "麦珂记得，上一世，康拉德也是这样：药先用，记录后补，"
            "出了问题便推成笔误。",
            repaired_memory,
        )
        repaired_memory_failures = "\n".join(
            _chapter_body_hard_failures(repaired_memory, 6, card)
        )
        self.assertNotIn("缺少重生反杀的因果", repaired_memory_failures)

        paper_micro_expanded = _insert_closed_scene_micro_expansion(
            (
                "送货单与领用簿相差一支。\n\n"
                "负责人说：“即刻暂停你的职务。”\n\n"
                "药品保管权归麦珂·杰森。"
            ),
            "康拉德说是笔误，麦珂指出三样材料都由他经手。",
            card,
        )
        self.assertLess(
            paper_micro_expanded.index("三样材料都由他经手"),
            paper_micro_expanded.index("即刻暂停你的职务"),
        )

        echoed_memory = (
            missing_memory
            + "\n\n麦珂想起上一世的事——不是画面，不是触感，只是一个冷硬认知。"
            "这念头不延展，不渲染。"
        )
        repaired_echo = _ensure_medication_audit_previous_life_motive(
            echoed_memory,
            card,
        )
        self.assertNotIn("不是画面", repaired_echo)
        self.assertNotIn("不延展", repaired_echo)
        self.assertIn("药先用，记录后补", repaired_echo)

        normalized_surface = _normalize_closed_scene_surface_drift(
            clean + "领用簿墨迹未干，送货单油墨已经干透。",
            card,
        )
        self.assertNotIn("墨迹未干", normalized_surface)
        self.assertNotIn("油墨已经干透", normalized_surface)
        normalized_failures = "\n".join(
            _chapter_body_hard_failures(normalized_surface, 6, card)
        )
        self.assertNotIn("伪医学或伪法证", normalized_failures)

        normalized_record_and_tail = _normalize_closed_scene_surface_drift(
            clean.replace(
                "麦珂说：“没有我的许可，谁也不能碰这些药。”",
                "负责人翻开领用簿，在空白处写下日期与签名，抬头道："
                "“药品保管权归麦珂·杰森。”"
                "麦珂说：“没有我的许可，谁也不能碰这些药。”",
            ).replace(
                "康拉德伸手想夺，最终只能僵在桌边。",
                "康拉德嘴角抽了一下，转身就走，皮鞋撞上门框。",
            ),
            card,
        )
        self.assertNotIn("写下日期", normalized_record_and_tail)
        self.assertIn("负责人说：“药品保管权归麦珂·杰森。”", normalized_record_and_tail)
        self.assertTrue(normalized_record_and_tail.endswith("康拉德·莫里森嘴角抽了一下。"))
        normalized_record_tail_failures = "\n".join(
            _chapter_body_hard_failures(normalized_record_and_tail, 6, card)
        )
        self.assertNotIn("新增记录", normalized_record_tail_failures)
        self.assertNotIn("收束对白后", normalized_record_tail_failures)
        self.assertNotIn("对白后继续写对手离场", normalized_record_tail_failures)

        key_not_received = clean.replace(
            "负责人确认：“药品保管权归麦珂·杰森。”麦珂接过钥匙。",
            "负责人确认：“药品保管权归麦珂·杰森。”"
            "负责人把钥匙递到麦珂面前，麦珂未伸手。",
        )
        key_not_received_failures = "\n".join(
            _chapter_body_hard_failures(key_not_received, 6, card)
        )
        self.assertIn("钥匙没有实际交到主角手中", key_not_received_failures)

        key_source_missing = clean.replace(
            "康拉德被停职，只能交出药品柜钥匙和领用簿。",
            "康拉德被停职。负责人手里已经握着药品柜钥匙和领用簿。",
        )
        key_source_missing_failures = "\n".join(
            _chapter_body_hard_failures(key_source_missing, 6, card)
        )
        self.assertIn("钥匙在交接段凭空出现在负责人手中", key_source_missing_failures)

        repaired_handover = _ensure_medication_audit_handover(
            key_not_received,
            card,
        )
        self.assertIn("交出药品柜钥匙和领用簿", repaired_handover)
        self.assertIn("把钥匙放进麦珂·杰森掌心", repaired_handover)
        self.assertNotIn("麦珂未伸手", repaired_handover)
        self.assertEqual(
            repaired_handover,
            _ensure_medication_audit_handover(repaired_handover, card),
        )
        repaired_handover_failures = "\n".join(
            _chapter_body_hard_failures(repaired_handover, 6, card)
        )
        self.assertNotIn("钥匙没有实际交到主角手中", repaired_handover_failures)
        self.assertNotIn("钥匙在交接段凭空出现", repaired_handover_failures)

        natural_handover = clean.replace(
            "康拉德被停职，只能交出药品柜钥匙和领用簿。"
            "负责人确认：“药品保管权归麦珂·杰森。”麦珂接过钥匙。",
            "康拉德被停职。他拿出钥匙，覆进负责人掌心，又递出领用簿。"
            "负责人确认：“药品保管权归麦珂·杰森。”"
            "负责人手掌一倾，钥匙滑入麦珂指间。",
        )
        self.assertEqual(
            natural_handover,
            _ensure_medication_audit_handover(natural_handover, card),
        )
        duplicate_handover = natural_handover + (
            "康拉德又交出一次钥匙。负责人又把钥匙放进麦珂掌心。"
        )
        duplicate_handover_failures = "\n".join(
            _chapter_body_hard_failures(duplicate_handover, 6, card)
        )
        self.assertIn("钥匙交接被重复书写", duplicate_handover_failures)

        repaired_source = _ensure_medication_audit_handover(
            key_source_missing,
            card,
        )
        self.assertIn("康拉德交出唯一钥匙和领用簿", repaired_source)

        missing_closing = clean.replace(
            "麦珂说：“没有我的许可，谁也不能碰这些药。”",
            "",
        )
        missing_closing_failures = "\n".join(
            _chapter_body_hard_failures(missing_closing, 6, card)
        )
        self.assertIn("缺少主角的最终收束对白", missing_closing_failures)

        seal_as_second_evidence = clean.replace(
            "麦珂说：“没有我的许可，谁也不能碰这些药。”",
            "\n\n封签边缘印着“柒”，领用簿还有朱砂红圈和洇开的墨点。"
            "康拉德的手停在领用簿上方寸许。\n\n"
            "麦珂说：“没有我的许可，谁也不能碰这些药。”",
        )
        normalized_seal = _normalize_closed_scene_surface_drift(
            seal_as_second_evidence,
            card,
        )
        self.assertNotRegex(normalized_seal, r"封签.{0,12}[柒七]支?")
        self.assertNotIn("朱砂红圈", normalized_seal)
        self.assertNotIn("洇开的墨点", normalized_seal)
        self.assertNotIn("寸许", normalized_seal)
        self.assertIn("\n\n", normalized_seal)

        paper_forensics_and_hidden_drug = clean + (
            "负责人摩挲凹印和凸起油墨，盯着横线末端与纸页褶皱。"
            "麦珂说多出来的一支就在康拉德袖口里。"
        )
        paper_forensics_failures = "\n".join(
            _chapter_body_hard_failures(paper_forensics_and_hidden_drug, 6, card)
        )
        self.assertIn("伪医学或伪法证", paper_forensics_failures)
        self.assertIn("暗示缺少的针剂藏在衣袋中", paper_forensics_failures)

        false_gain = clean + (
            "麦珂想起上次康拉德递给我第一支针剂，又从口袋掏出另一把同款钥匙。"
            "他拉开药柜，闻到一缕苦香。"
        )
        false_gain_failures = "\n".join(
            _chapter_body_hard_failures(false_gain, 6, card)
        )
        self.assertIn("当前时间线的既往针剂交接", false_gain_failures)
        self.assertIn("同款药柜钥匙", false_gain_failures)
        self.assertIn("擅自打开药柜", false_gain_failures)
        self.assertIn("感官鉴定", false_gain_failures)

        false_field = clean + (
            "上一世同一排货架的凹槽和胶痕形状都没变。"
            "上一世康拉德把签字笔搁在桌角，油墨渗进木纹里的旧划痕仍在。"
            "领用簿写七支，送货单写实付数量六支。"
            "康拉德称上周临时加了一次剂量，又指着系统打印的微型编码和骑缝印章。"
            "去年生日时麦珂亲手挑了这件礼物。负责人把食指抵在腕内侧脉搏上数心跳。"
            "领用簿的墨迹未干，另一行墨色略浓，康拉德的顿笔习惯分毫不差。"
            "康拉德说流程允许事后补登，又把手伸进口袋寻找另一份备份。"
            "康拉德又称流程上有权即时调整用量记录。"
            "他袖口有上周擦药棉留下的褐斑，腰侧还有上个月摔出的淤青。"
            "那件衣服的褶皱走向和上一章完全一样。"
            "上一世总是先撕封签，再把针筒推入肌肉。"
            "封签背面小字写着统一封码七支。"
            "负责人翻开领用簿写下一行字。"
            "麦珂想起自己上周被清出团队时已经交走钥匙串。"
            "麦珂左肩缠着绷带，仍有钝感。"
            "麦珂说桌上只有七支实物。"
            "康拉德辩称麦珂上周已经用了九支。"
            "麦珂说：“没有我的许可，谁也不能碰这些药。”"
            "康拉德退后一步，窗外天空蒙着薄雾。"
            "康拉德指腹沾着干涸药液残痕，像一道伏笔。"
            "麦珂抽出封签一角又放回原处。"
            "麦珂说：“全是我经手的。”"
            "麦珂追问为何不重签日期、不注明‘补’字，又指向撕下那页背面的痕迹。"
            "康拉德的手停在离麦珂手腕三寸处。"
            "钥匙柄上的旧划痕是康拉德三年前摔跤磕出来的。"
            "康拉德抬手要撕掉领用簿那页。"
            "桌上整齐排列着七支未拆封的针剂。"
            "上一世那次药量差额曾让麦珂过敏休克。"
            "八支的字迹潦草，与前文工整笔锋不同。"
            "药品柜钥匙从开场就搁在桌上。"
        )
        false_field_failures = "\n".join(
            _chapter_body_hard_failures(false_field, 6, card)
        )
        self.assertIn("精密复原", false_field_failures)
        self.assertIn("实付数量", false_field_failures)
        self.assertIn("既往用药事实", false_field_failures)
        self.assertIn("数字取证设备", false_field_failures)
        self.assertIn("额外校验代码", false_field_failures)
        self.assertIn("审批或制度", false_field_failures)
        self.assertIn("私人往事", false_field_failures)
        self.assertIn("摸脉或数心跳", false_field_failures)
        self.assertIn("伪医学或伪法证", false_field_failures)
        self.assertIn("审批或制度", false_field_failures)
        self.assertIn("备份文件", false_field_failures)
        self.assertIn("旧伤、疤痕、衣物污渍", false_field_failures)
        self.assertIn("章节制作术语", false_field_failures)
        self.assertIn("具体过程", false_field_failures)
        self.assertIn("封签背面小字", false_field_failures)
        self.assertIn("新增记录", false_field_failures)
        self.assertIn("被清出团队", false_field_failures)
        self.assertIn("绷带、旧伤", false_field_failures)
        self.assertIn("清点桌上针剂", false_field_failures)
        self.assertIn("此前已经使用多支针剂", false_field_failures)
        self.assertIn("环境象征", false_field_failures)
        self.assertIn("创作说明", false_field_failures)
        self.assertIn("药液残痕", false_field_failures)
        self.assertIn("封签边角", false_field_failures)
        self.assertIn("错误归到主角名下", false_field_failures)
        self.assertIn("数量差之外", false_field_failures)
        self.assertIn("精确身体距离", false_field_failures)
        self.assertIn("旧损伤来历", false_field_failures)
        self.assertIn("撕毁领用簿", false_field_failures)
        self.assertIn("实物清点", false_field_failures)
        self.assertIn("过敏、休克", false_field_failures)
        self.assertIn("字迹工整、潦草", false_field_failures)
        prompt_echo = clean + (
            "麦珂·杰森原话反击：“没有我的许可，谁也不能碰这些药。”"
        )
        prompt_echo_failures = "\n".join(
            _chapter_body_hard_failures(prompt_echo, 6, card)
        )
        self.assertIn("提示词或创作标签", prompt_echo_failures)

        overlong_close = clean + (
            "\n\n麦珂说：“没有我的许可，谁也不能碰这些药。”"
            "\n\n康拉德咬牙退开。"
            "\n\n麦珂低头又看了一遍钥匙。"
        )
        overlong_close_failures = "\n".join(
            _chapter_body_hard_failures(overlong_close, 6, card)
        )
        self.assertIn("追加多段反应或主角动作", overlong_close_failures)

        long_after_closing = clean + (
            "麦珂说：“没有我的许可，谁也不能碰这些药。”"
            + "康拉德继续望着窗外，负责人整理桌面，屋里只剩风声。" * 30
        )
        long_after_closing_failures = "\n".join(
            _chapter_body_hard_failures(long_after_closing, 6, card)
        )
        self.assertIn("收束对白后继续追加过长", long_after_closing_failures)

        prompt = _build_closed_evidence_scene_prompt(
            6,
            card,
            prev_tail_scene="麦珂离开排练场。",
        )
        self.assertIsNotNone(prompt)
        self.assertIn("【事实白名单】", prompt)
        self.assertIn("【八个正向节拍】", prompt)
        self.assertIn("纸面只读“送达数量七支”和“领用数量八支”", prompt)
        self.assertIn("唯一矛盾是相差一支", prompt)
        self.assertIn("封签、送货单和领用簿都是康拉德·莫里森经手的", prompt)
        self.assertIn("即刻暂停你的职务", prompt)
        self.assertIn("药品保管权归麦珂·杰森", prompt)
        self.assertIn("不得继承前场对手的口袋、钥匙", prompt)
        self.assertIn("对白后只写康拉德·莫里森一个极短反应", prompt)
        self.assertNotIn("墨迹浓淡", prompt)
        self.assertNotIn("摸脉", prompt)
        self.assertNotIn("签名笔势", prompt)
        paper_segment_plan = _closed_scene_segment_plan(card)
        self.assertIsNotNone(paper_segment_plan)
        paper_segment_facts, paper_segment_specs = paper_segment_plan
        self.assertEqual(8, len(paper_segment_specs))
        self.assertIn("离开排练场后直接来到医务室", paper_segment_specs[0][2])
        self.assertIn(
            "唯一纸面事实是送货单写送达七支、领用簿写领用八支",
            paper_segment_facts,
        )
        self.assertIn("即刻暂停你的职务", paper_segment_specs[4][2])
        paper_early_prompt = _build_closed_scene_segment_prompt(
            6,
            paper_segment_facts,
            1,
            8,
            *paper_segment_specs[0][:2],
            paper_segment_specs[0][2],
        )
        paper_handover_prompt = _build_closed_scene_segment_prompt(
            6,
            paper_segment_facts,
            6,
            8,
            *paper_segment_specs[5][:2],
            paper_segment_specs[5][2],
        )
        self.assertNotIn("钥匙", paper_early_prompt)
        self.assertIn("钥匙", paper_handover_prompt)
        deterministic_audit_segments = [
            _shape_closed_scene_segment_candidate(
                "",
                card,
                segment_spec[1],
                index,
            )
            for index, segment_spec in enumerate(paper_segment_specs, start=1)
        ]
        for index, segment in enumerate(deterministic_audit_segments, start=1):
            self.assertTrue(segment)
            self.assertFalse(_closed_scene_segment_candidate_failure(
                segment,
                card,
                index,
            ))
        deterministic_audit = "\n\n".join(deterministic_audit_segments)
        self.assertGreaterEqual(len(deterministic_audit), 1000)
        deterministic_audit_failures = "\n".join(
            _chapter_body_hard_failures(deterministic_audit, 6, card)
        )
        self.assertEqual("", deterministic_audit_failures)
        self.assertNotIn("正文擅自新增或改名人物", deterministic_audit_failures)
        self.assertNotIn("正文存在近似重复段落", deterministic_audit_failures)
        self.assertNotIn("纸面核对用环境添景", deterministic_audit_failures)
        self.assertNotIn("药品柜钥匙在停职宣布前", deterministic_audit_failures)
        audit_critic = _cluster_critic(
            {
                "chapter_span": [6, 6],
                "core_payoff": "康拉德被暂停职务，麦珂获得药品保管权",
                "cluster_outcome": "康拉德被暂停职务，麦珂获得药品保管权",
                "main_opponent": "康拉德·莫里森",
            },
            {6: deterministic_audit},
            chapter_cards={6: card},
        )
        self.assertTrue(any(
            "字数不足" in violation
            for violation in audit_critic["violations"]
        ))
        physical_early_key_failures = "\n".join(
            _chapter_body_hard_failures(
                "桌上摆着药品柜钥匙。" + deterministic_audit,
                6,
                card,
            )
        )
        self.assertIn("药品柜钥匙在停职宣布前", physical_early_key_failures)
        self.assertTrue(_closed_scene_segment_candidate_failure(
            "桌上摆着七支未拆封的针剂，麦珂想起上一世过敏休克。",
            card,
            1,
        ))
        self.assertTrue(_closed_scene_segment_candidate_failure(
            "麦珂·杰森原话反击：“没有我的许可，谁也不能碰这些药。”",
            card,
            7,
        ))
        self.assertTrue(_closed_scene_segment_candidate_failure(
            "负责人向康拉德摊开手掌。",
            card,
            5,
        ))
        self.assertTrue(_closed_scene_segment_candidate_failure(
            "负责人把钥匙递到麦珂面前。",
            card,
            6,
        ))
        self.assertTrue(_closed_scene_segment_candidate_failure(
            "麦珂盯着康拉德，没有再开口。",
            card,
            7,
        ))
        shaped_key_handover = _shape_closed_scene_segment_candidate(
            "负责人看向康拉德，又向麦珂摊开手。",
            card,
            250,
            6,
        )
        self.assertIn("负责人看向康拉德", shaped_key_handover)
        self.assertNotIn("药品保管权归麦珂·杰森", shaped_key_handover)
        self.assertTrue(_closed_scene_segment_candidate_failure(
            shaped_key_handover,
            card,
            6,
        ))
        shaped_paper = _shape_closed_scene_segment_candidate(
            "现场负责人先看送货单，再看领用簿。"
            "桌上清点出七支针剂，字迹也有不同。"
            "现场负责人又在领用簿里写下一行记录。"
            "康拉德伸手想拿回领用簿。",
            card,
            80,
        )
        self.assertNotIn("清点", shaped_paper)
        self.assertNotIn("字迹", shaped_paper)
        self.assertNotIn("写下一行", shaped_paper)
        self.assertIn("康拉德伸手想拿回领用簿", shaped_paper)
        shaped_short_reaction = _shape_closed_scene_segment_candidate(
            "康拉德僵在原地，嘴唇动了许久，最后只把视线压向桌面，"
            "却再也找不到一句能够挽回局面的话。",
            card,
            50,
        )
        self.assertTrue(shaped_short_reaction.endswith("。"))
        self.assertLessEqual(len(shaped_short_reaction), 50)

    def test_medication_motive_repair_does_not_touch_performance_scene(self):
        card = {
            "chapter_role_v2": "present_revenge",
            "chapter_goal": "完成公开唱跳连测并夺回训练强度决定权",
            "this_life_revenge": "现场表演验真",
            "core_payoff": "训练强度决定权归还麦珂·杰森",
            "canonical_cast": [
                {"name": "麦珂·杰森", "role": "歌手", "alignment": "protagonist"},
                {"name": "卡尔·霍尔特", "role": "经纪人", "alignment": "opponent"},
            ],
        }
        text = "麦珂完成唱跳连测，训练强度决定权归还麦珂·杰森。"
        self.assertEqual(
            text,
            _ensure_medication_audit_previous_life_motive(text, card),
        )

    def test_grounded_cast_ignores_cluster_level_opponent_not_named_by_chapter(self):
        card = {
            "chapter_goal": "麦珂当面核对针剂封签、送货单和领用簿",
            "this_life_revenge": "要求康拉德更换药品保管人",
            "core_payoff": "康拉德被暂停职务，麦珂获得药品保管权",
            "main_opponent": "卡尔·霍尔特",
            "canonical_cast": [
                {"name": "麦珂·杰森", "role": "歌手", "alignment": "protagonist"},
                {"name": "康拉德·莫里森", "role": "私人医生", "alignment": "opponent"},
                {"name": "卡尔·霍尔特", "role": "巡演总监", "alignment": "opponent"},
            ],
        }
        selected = [member["name"] for member in _select_grounded_chapter_cast(card)]
        self.assertEqual(["麦珂·杰森", "康拉德·莫里森"], selected)

        cross_domain_card = {
            **card,
            "chapter_id": 6,
            "cluster_name": "体能测试与药品保管审计",
            "cluster_chapter_index": 2,
            "cluster_chapter_total": 2,
            "cluster_outcome": "康拉德被停职，麦珂获得药品保管权",
            "cluster_milestones": [
                {
                    "chapter": 5,
                    "action": "完成高强度唱跳测试",
                    "opponent_reaction": "卡尔试图降低强度",
                    "result": "麦珂收回训练强度决定权",
                },
                {
                    "chapter": 6,
                    "action": "当面核对针剂封签、送货单和领用簿",
                    "opponent_reaction": "康拉德试图辩解",
                    "result": "康拉德被暂停职务，麦珂获得药品保管权",
                },
            ],
            "chapter_milestone": {
                "chapter": 6,
                "action": "当面核对针剂封签、送货单和领用簿",
                "opponent_reaction": "康拉德试图辩解",
                "result": "康拉德被暂停职务，麦珂获得药品保管权",
            },
        }
        cross_domain_contract = _derive_closed_scene_contract(cross_domain_card)
        self.assertEqual(
            "evidence_confrontation",
            cross_domain_contract["scene_archetype"],
        )
        self.assertEqual(
            "康拉德·莫里森",
            cross_domain_contract["opponent_scene_actor"],
        )

        beats = _fallback_chapter_beats(
            {"canonical_cast": card["canonical_cast"], "main_opponent": "卡尔·霍尔特"},
            6,
            {
                **card,
                "chapter_role_v2": "present_revenge",
                "chapter_must_include": ["康拉德试图辩解"],
            },
            open_from_prev="上一章结果已生效",
        )
        beats_text = str(beats)
        self.assertIn("康拉德·莫里森", beats_text)
        self.assertNotIn("卡尔·霍尔特", beats_text)
        self.assertIn("只指出一处", beats_text)
        self.assertIn("从开场就在场", beats_text)

    def test_grounded_cast_includes_people_named_by_milestone(self):
        card = {
            "prev_life_tragedy": "康拉德强行注射，麦珂听见门外众人讨论保险。",
            "chapter_milestone": {
                "opponent_reaction": "维克多在门外催问保险与死后版权何时生效",
            },
            "canonical_cast": [
                {"name": "麦珂·杰森", "alignment": "protagonist"},
                {"name": "康拉德·莫里森", "alignment": "opponent"},
                {"name": "维克多·兰斯", "alignment": "opponent"},
                {"name": "卡尔·霍尔特", "alignment": "opponent"},
            ],
        }
        selected_names = {
            member["name"] for member in _select_grounded_chapter_cast(card)
        }
        self.assertEqual(
            {"麦珂·杰森", "康拉德·莫里森", "维克多·兰斯"},
            selected_names,
        )

    def test_runtime_cards_preserve_per_chapter_milestones(self):
        cluster = {
            "cluster_id": "EC01",
            "name": "最后一针",
            "chapter_span": [1, 1],
            "main_opponent": "康拉德·莫里森",
            "prev_life_tragedy": "康拉德强行注射，麦珂听见门外众人讨论保险。",
            "canonical_cast": [
                {"name": "麦珂·杰森", "role": "歌手", "alignment": "protagonist"},
                {"name": "康拉德·莫里森", "role": "私人医生", "alignment": "opponent"},
                {"name": "维克多·兰斯", "role": "唱片高管", "alignment": "opponent"},
            ],
            "chapter_milestones": [{
                "chapter": 1,
                "action": "麦珂拒绝针剂，康拉德仍强行注射",
                "opponent_reaction": "维克多在门外催问保险何时生效",
                "result": "麦珂听清分赃并死亡",
            }],
        }
        card = _build_cards_from_clusters([cluster])[1]
        self.assertEqual(cluster["chapter_milestones"][0], card["chapter_milestone"])
        outline_card = _build_cards_from_clusters_v2([cluster], total_chapters=1)[1]
        self.assertEqual(
            cluster["chapter_milestones"][0],
            outline_card["chapter_milestone"],
        )
        enriched = _enrich_cards_with_cluster_milestones(
            {1: {"chapter_id": 1, "canonical_cast": cluster["canonical_cast"]}},
            [cluster],
        )
        self.assertEqual(
            cluster["chapter_milestones"][0],
            enriched[1]["chapter_milestone"],
        )

    def test_forced_medication_death_scene_is_closed_and_valid(self):
        cluster = {
            "cluster_id": "EC01",
            "name": "最后一针",
            "chapter_span": [1, 1],
            "main_opponent": "康拉德·莫里森",
            "core_payoff": "麦珂听见死人比活人值钱并明确死亡",
            "prev_life_tragedy": "首演前夜，康拉德违规加量注射，麦珂听见保险与死后版权分赃。",
            "this_life_revenge": "麦珂拒绝加量镇静却被康拉德强行注射",
            "canonical_cast": [
                {"name": "麦珂·杰森", "role": "传奇流行天王", "alignment": "protagonist"},
                {"name": "康拉德·莫里森", "role": "私人医生", "alignment": "opponent"},
                {"name": "维克多·兰斯", "role": "唱片高管", "alignment": "opponent"},
                {"name": "卡尔·霍尔特", "role": "巡演总监", "alignment": "opponent"},
            ],
            "chapter_milestones": [{
                "chapter": 1,
                "action": "麦珂拒绝针剂，康拉德仍强行注射",
                "opponent_reaction": "维克多在门外催问保险与死后版权何时生效",
                "result": "麦珂听见死人比活人值钱并明确死亡",
            }],
        }
        card = _build_cards_from_clusters([cluster])[1]
        scene = _build_forced_medication_death_scene(card)
        self.assertIsNotNone(scene)
        self.assertGreaterEqual(len(scene), 1000)
        self.assertLessEqual(len(scene), 2000)
        self.assertIn("麦珂·杰森", scene)
        self.assertIn("康拉德·莫里森", scene)
        self.assertIn("维克多·兰斯", scene)
        self.assertNotIn("卡尔·霍尔特", scene)
        self.assertFalse(_chapter_body_hard_failures(scene, 1, card))

    def test_performer_medication_fallback_does_not_capture_other_domains(self):
        death_cluster = {
            "cluster_id": "EC01",
            "name": "实验室违规注射",
            "chapter_span": [1, 1],
            "main_opponent": "顾问",
            "core_payoff": "研究员在拒绝违规注射后被强制执行并明确死亡",
            "prev_life_tragedy": "实验室内，研究员拒绝违规注射，顾问仍强行注射并导致死亡。",
            "this_life_revenge": "只完成上一世死亡",
            "canonical_cast": [
                {"name": "林岚", "role": "材料研究员", "alignment": "protagonist"},
                {"name": "周衡", "role": "安全顾问", "alignment": "opponent"},
            ],
            "chapter_milestones": [{
                "chapter": 1,
                "action": "林岚明确拒绝违规注射",
                "opponent_reaction": "周衡仍越过拒绝强行执行",
                "result": "林岚呼吸断绝并明确死亡",
            }],
        }
        death_card = _build_cards_from_clusters([death_cluster])[1]
        self.assertIsNone(_build_forced_medication_death_scene(death_card))
        repair_prompt = _build_death_repair_prompt(
            1, "林岚在实验室倒下。", death_card, ["死亡过程不完整"],
        )
        self.assertIn("周衡仍越过拒绝强行执行", repair_prompt)
        self.assertNotIn("保险", repair_prompt)
        self.assertNotIn("死后版权", repair_prompt)
        self.assertNotIn("舞台", repair_prompt)

        awakening_cluster = {
            "cluster_id": "EC02",
            "name": "实验室医疗双签",
            "chapter_span": [2, 2],
            "main_opponent": "周衡",
            "core_payoff": "建立医疗双签，周衡失去单方注射权",
            "prev_life_tragedy": "上一世被周衡强制注射后死亡",
            "this_life_revenge": "醒来后拒绝针剂并建立医疗双签",
            "canonical_cast": death_cluster["canonical_cast"],
            "chapter_milestones": [{
                "chapter": 2,
                "action": "林岚核对日期后拒绝针剂并要求双签",
                "opponent_reaction": "周衡无法说明用途",
                "result": "值班医师接管第二签字权",
            }],
        }
        awakening_card = _build_cards_from_clusters([awakening_cluster])[2]
        self.assertIsNone(_build_medical_double_sign_awakening_scene(awakening_card))

    def test_medical_double_sign_awakening_scene_is_closed_and_valid(self):
        cluster = {
            "cluster_id": "EC02",
            "name": "重生确认与注射权限争夺",
            "chapter_span": [2, 2],
            "main_opponent": "康拉德·莫里森",
            "core_payoff": "建立医疗双签制度，首次夺回身体控制权",
            "prev_life_tragedy": "被强制注射不明药剂导致虚弱",
            "this_life_revenge": "确认重生后拒绝针剂并提出医疗双签",
            "cluster_outcome": "康拉德失去直接控制权，麦珂获得医疗监督权",
            "canonical_cast": [
                {"name": "麦珂·杰森", "role": "传奇流行天王", "alignment": "protagonist"},
                {"name": "康拉德·莫里森", "role": "私人医生", "alignment": "opponent"},
                {"name": "艾琳·沃特曼", "role": "音乐制作人", "alignment": "ally"},
            ],
            "chapter_milestones": [{
                "chapter": 2,
                "action": "核对日程，确认重生后拒绝针剂并提出医疗双签",
                "opponent_reaction": "康拉德无法解释药名和用量",
                "result": "第三方医疗团队登记药品并接管第二签字权",
            }],
        }
        card = _build_cards_from_clusters([cluster])[2]
        scene = _build_medical_double_sign_awakening_scene(card)
        self.assertIsNotNone(scene)
        self.assertGreaterEqual(len(scene), 1200)
        self.assertLessEqual(len(scene), 2000)
        self.assertIn("麦珂·杰森重生了，回到了那场复出发布会之前", scene)
        self.assertIn("第三方医疗团队正式接管第二签字权", scene)
        self.assertNotIn("艾琳·沃特曼", scene)
        self.assertFalse(
            any(char.isascii() and char.isalnum() for char in scene)
        )
        self.assertFalse(_chapter_body_hard_failures(scene, 2, card))

    def test_schedule_canary_scene_closes_setup_and_reveal_without_digital_forensics(self):
        cluster = {
            "cluster_id": "EC03",
            "name": "三份彩排表与泄密者揭露",
            "chapter_span": [3, 4],
            "main_opponent": "卡尔·霍尔特",
            "core_payoff": "收回排练信息分发权，清除内部叛徒",
            "prev_life_tragedy": "彩排内容被泄露导致演出受制",
            "info_gap_from_prev_life": "记得上一世被针对的方式",
            "this_life_revenge": "制作三份不同彩排表引出泄密者",
            "cluster_outcome": "泄密者被开除，麦珂掌控真实排期",
            "canonical_cast": [
                {"name": "麦珂·杰森", "role": "传奇流行天王", "alignment": "protagonist"},
                {"name": "卡尔·霍尔特", "role": "巡演总监", "alignment": "opponent"},
                {"name": "康拉德·莫里森", "role": "私人医生", "alignment": "opponent"},
            ],
            "chapter_milestones": [
                {
                    "chapter": 3,
                    "action": "发布三份不同彩排表引发混乱",
                    "opponent_reaction": "助理们慌乱应对",
                    "result": "诱饵表锁定接收人，真实彩排表保住并收回群发权限",
                },
                {
                    "chapter": 4,
                    "action": "在排练室当众揭穿泄密者",
                    "opponent_reaction": "泄密者惊恐否认但被证伪",
                    "result": "泄密者被开除并面临法律追责",
                },
            ],
        }
        cards = _build_cards_from_clusters([cluster])
        setup = _build_schedule_canary_scene(cards[3])
        reveal = _build_schedule_canary_scene(cards[4])
        for chapter, scene in ((3, setup), (4, reveal)):
            self.assertIsNotNone(scene)
            self.assertGreaterEqual(len(scene), 1000)
            self.assertLessEqual(len(scene), 2000)
            self.assertIn("卡尔·霍尔特", scene)
            self.assertNotIn("康拉德·莫里森", scene)
            self.assertFalse(
                any(char.isascii() and char.isalnum() for char in scene)
            )
            self.assertFalse(_chapter_body_hard_failures(scene, chapter, cards[chapter]))
        self.assertIn("收回排练群的统一发布权限", setup)
        self.assertIn("调度助理那份是一道蓝色短线", setup)
        self.assertNotIn("明天", setup)
        self.assertIn("调度助理被开除", reveal)
        self.assertIn("仍是巡演总监", reveal)
        self.assertNotIn("上一章", reveal)

    def test_chapter_body_rejects_meta_narration_for_any_scene(self):
        failures = _chapter_body_hard_failures(
            "上一章结束时，众人已经看见了证据。",
            chapter_num=7,
            chapter_card={},
        )
        self.assertTrue(any("章节制作术语" in failure for failure in failures))

    def test_overload_schedule_bait_scene_closes_setup_and_authority_settlement(self):
        cluster = {
            "cluster_id": "EC05",
            "name": "加场诱饵与超负荷排期暴露",
            "chapter_span": [7, 8],
            "main_opponent": "卡尔·霍尔特",
            "core_payoff": "逼迫巡演总监暴露真实排期，夺回排期签批权",
            "prev_life_tragedy": "因疲劳过度倒台",
            "info_gap_from_prev_life": "记得上一世被压缩的日程",
            "this_life_revenge": "提出加场演出诱导排期暴露",
            "cluster_outcome": "卡尔失去排期签批权，麦珂取得恢复日与否决权",
            "canonical_cast": [
                {
                    "name": "麦珂·杰森",
                    "role": "传奇流行天王",
                    "alignment": "protagonist",
                },
                {
                    "name": "卡尔·霍尔特",
                    "role": "巡演总监",
                    "alignment": "opponent",
                },
            ],
            "chapter_milestones": [
                {
                    "chapter": 7,
                    "action": "提出加场演出请求试探排期",
                    "opponent_reaction": "卡尔为抢功交出隐藏总表",
                    "result": "麦珂否决加场并冻结超载排期",
                },
                {
                    "chapter": 8,
                    "action": "当众揭露超负荷排期",
                    "opponent_reaction": "卡尔试图掩盖",
                    "result": "卡尔失去排期签批权，麦珂取得强制恢复日与最终排期否决权",
                },
            ],
        }
        cards = _build_cards_from_clusters([cluster])
        setup = _build_overload_schedule_bait_scene(cards[7])
        settlement = _build_overload_schedule_bait_scene(cards[8])
        for chapter, scene in ((7, setup), (8, settlement)):
            self.assertIsNotNone(scene)
            self.assertGreaterEqual(len(scene), 1000)
            self.assertLessEqual(len(scene), 2000)
            self.assertFalse(
                any(char.isascii() and char.isalnum() for char in scene)
            )
            self.assertFalse(_chapter_body_hard_failures(scene, chapter, cards[chapter]))
        self.assertIn("隐藏总表", setup)
        self.assertIn("后续超载排期全部冻结", setup)
        self.assertIn("仍是巡演总监", setup)
        self.assertIn("失去排期签批权", settlement)
        self.assertIn("强制恢复日当场生效", settlement)
        self.assertIn("取得强制恢复日与最终排期否决权", settlement)
        self.assertNotRegex(setup + settlement, r"服务器|操作日志|协议编号|第[一二三四五六七八九十]+条")
        self.assertNotIn("电子设备", settlement)
        self.assertNotIn("康拉德", setup)

    def test_exec_plan_skips_death_and_awakening_only_chapters(self):
        plan = {"evidence_chain": [{
            "evidence_id": "E1", "acquire_chapter": 2, "verify_chapter": 2, "use_chapter": 5,
        }]}
        cards = {
            2: {"chapter_role_v2": "rebirth_awakening_only"},
            3: {"chapter_role_v2": "present_past_mix"},
            4: {"chapter_role_v2": "present_mid_bridge"},
            5: {"chapter_role_v2": "present_revenge"},
        }
        normalized = _normalize_exec_plan_chapters(plan, [2, 3, 4, 5], cards)
        evidence = normalized["evidence_chain"][0]
        self.assertEqual(3, evidence["acquire_chapter"])
        self.assertEqual(3, evidence["verify_chapter"])
        self.assertEqual(5, evidence["use_chapter"])

    def test_scene_contract_drives_stage_safety_without_chapter_specific_builder(self):
        cluster = {
            "cluster_id": "EC_STAGE",
            "name": "升降机关验收",
            "chapter_span": [9, 10],
            "main_opponent": "卡尔·霍尔特",
            "info_gap_from_prev_life": "记得第三次口令后升降台会提前启动。",
            "this_life_revenge": "先用等重沙袋空载验收，逼对手亲手启动错误程序。",
            "cluster_outcome": "卡尔失去舞台机关指挥权，麦珂取得最终启停否决权。",
            "canonical_cast": [
                {"name": "麦珂·杰森", "role": "歌手", "alignment": "protagonist"},
                {"name": "卡尔·霍尔特", "role": "巡演总监", "alignment": "opponent"},
            ],
            "chapter_milestones": [
                {
                    "chapter": 9,
                    "action": "要求升降台先用等重沙袋完成空载验收",
                    "opponent_reaction": "卡尔抢过控制器按下私改程序",
                    "result": "沙袋提前坠下，麦珂叫停真人登台并保住舞者安全",
                },
                {
                    "chapter": 10,
                    "action": "调出控制器操作日志与未签字验收单重新表决",
                    "opponent_reaction": "卡尔把坠落说成舞台效果",
                    "result": "卡尔失去舞台机关指挥权，麦珂取得最终启停否决权",
                },
            ],
        }
        cards = _build_cards_from_clusters([cluster])
        setup = _derive_closed_scene_contract(cards[9])
        settlement = _derive_closed_scene_contract(cards[10])
        self.assertFalse(_closed_scene_contract_failures(setup))
        self.assertFalse(_closed_scene_contract_failures(settlement))
        self.assertEqual("physical_safety_validation", setup["scene_archetype"])
        self.assertEqual("setup", setup["phase"])
        self.assertEqual("settlement", settlement["phase"])
        self.assertIn("等重沙袋", setup["current_evidence_carriers"])
        self.assertIn("控制器操作日志", settlement["current_evidence_carriers"])
        self.assertIn("未签字验收单", settlement["current_evidence_carriers"])
        self.assertIn("等重沙袋", settlement["established_evidence_carriers"])
        facts, segments = _closed_scene_segment_plan(cards[10])
        self.assertIn("physical_safety_validation", facts)
        self.assertEqual(6, len(segments))
        plan = _fallback_build_exec_plan_for_cluster(cluster, [9, 10], cards)
        evidence_types = [item["evidence_type"] for item in plan["evidence_chain"]]
        self.assertIn("等重沙袋", evidence_types)
        self.assertIn("控制器操作日志", evidence_types)
        self.assertNotIn("本簇信息差对应的主动行动", evidence_types)

    def test_scene_contract_generalizes_to_unrelated_warehouse_safety_cluster(self):
        cluster = {
            "cluster_id": "EC_WAREHOUSE",
            "name": "冷库传送带复验",
            "chapter_span": [31, 32],
            "main_opponent": "罗文·凯德",
            "info_gap_from_prev_life": "林澈记得传送带会在第二次复位后反向运行。",
            "this_life_revenge": "林澈先放测试用配重，逼罗文亲手跳过停机检查。",
            "cluster_outcome": "罗文失去设备调度权，林澈取得停机否决权。",
            "canonical_cast": [
                {"name": "林澈", "role": "仓储经理", "alignment": "protagonist"},
                {"name": "罗文·凯德", "role": "承包主管", "alignment": "opponent"},
            ],
            "chapter_milestones": [
                {
                    "chapter": 31,
                    "action": "要求传送带先用测试用配重完成空载复验",
                    "opponent_reaction": "罗文抢过控制台跳过停机检查",
                    "result": "配重反向滑落，林澈叫停工人上岗并保住现场安全",
                },
                {
                    "chapter": 32,
                    "action": "核对值班记录与未签字验收单",
                    "opponent_reaction": "罗文把反转说成正常试车",
                    "result": "罗文失去设备调度权，林澈取得停机否决权",
                },
            ],
        }
        cards = _build_cards_from_clusters([cluster])
        setup = cards[31]["scene_contract"]
        settlement = cards[32]["scene_contract"]
        self.assertEqual("physical_safety_validation", setup["scene_archetype"])
        self.assertIn("测试用配重", setup["current_evidence_carriers"])
        self.assertIn("未签字验收单", settlement["current_evidence_carriers"])
        facts, segments = _closed_scene_segment_plan(cards[32])
        self.assertIn("罗文·凯德", facts)
        self.assertIn("林澈", facts)
        self.assertEqual(6, len(segments))
        fallback_body = "\n\n".join(
            _generic_contract_segment_fallback(cards[32], index)
            for index in range(1, len(segments) + 1)
        )
        self.assertGreaterEqual(len(fallback_body), 1000)
        fallback_failures = _chapter_body_hard_failures(fallback_body, 32, cards[32])
        self.assertTrue(any(
            "等长" in failure or "兜底模板" in failure
            for failure in fallback_failures
        ))
        self.assertFalse(
            _scene_contract_fulfillment_failures(fallback_body, cards[32])
        )
        self.assertNotIn("情节组已经指定", fallback_body)
        self.assertNotIn("当前允许使用", fallback_body)
        self.assertNotIn("主角", fallback_body)
        self.assertNotIn("对手", fallback_body)

    def test_scene_contract_enforces_ticket_audit_whitelist_and_two_way_payoff(self):
        cluster = {
            "cluster_id": "EC_TICKET",
            "name": "实名核票",
            "chapter_span": [11, 12],
            "main_opponent": "主办方",
            "info_gap_from_prev_life": "主角记得内部预留票会绕过实名名单。",
            "this_life_revenge": "闻溪联合‘星火’歌迷会核对实名名单与异常预留票。",
            "cluster_outcome": "主办方失去私设预留票权限，主角获得票务监督席位。",
            "canonical_cast": [
                {"name": "闻溪", "role": "歌手", "alignment": "protagonist"},
            ],
            "chapter_milestones": [
                {
                    "chapter": 11,
                    "action": "闻溪发动歌迷会核对实名名单",
                    "opponent_reaction": "主办方试图阻挠核票",
                    "result": "异常预留票被冻结，黄牛无法出票获利",
                },
                {
                    "chapter": 12,
                    "action": "闻溪当众展示异常预留票并要求退回票池",
                    "opponent_reaction": "主办方承认私设预留票",
                    "result": "主办方失去私设预留票权限，闻溪获得票务监督席位",
                },
            ],
        }
        cards = _build_cards_from_clusters([cluster])
        stale_cards = {
            chapter: {
                "chapter_id": chapter,
                "chapter_role_v2": (
                    "present_past_mix" if chapter == 11 else "present_revenge"
                ),
                "this_life_revenge": "过期缓存内容",
                "canonical_cast": [],
            }
            for chapter in (11, 12)
        }
        enriched = _enrich_cards_with_cluster_milestones(
            stale_cards,
            [cluster],
        )
        for chapter in (11, 12):
            self.assertEqual(
                next(
                    milestone["action"]
                    for milestone in cluster["chapter_milestones"]
                    if milestone["chapter"] == chapter
                ),
                enriched[chapter]["this_life_revenge"],
            )
            self.assertEqual(
                cluster["this_life_revenge"],
                enriched[chapter]["cluster_this_life_revenge"],
            )
            self.assertEqual(
                cluster["canonical_cast"],
                enriched[chapter]["canonical_cast"],
            )
            self.assertEqual(
                ["星火"],
                enriched[chapter]["scene_contract"]["supporting_organizations"],
            )
        contract = cards[12]["scene_contract"]
        self.assertEqual("public_resource_audit", contract["scene_archetype"])
        self.assertEqual("主办方失去私设预留票权限", contract["opponent_loss"])
        self.assertEqual("闻溪获得票务监督席位", contract["protagonist_gain"])
        self.assertEqual("", contract["authority_gain"])
        clean = (
            "闻溪把前一场冻结的异常预留票摆到主办方面前。"
            "他要求这些票退回票池，主办方当众承认私设预留票。"
            "主办方失去私设预留票权限，闻溪获得票务监督席位。"
        )
        self.assertFalse(_scene_contract_fulfillment_failures(clean, cards[12]))
        contaminated = clean + "随后有人递来后台截图和协议编号。"
        failures = "\n".join(
            _scene_contract_fulfillment_failures(contaminated, cards[12])
        )
        self.assertIn("后台截图", failures)
        self.assertIn("协议编号", failures)
        scaffold = clean + "主角依据情节组已经指定的材料反卡对手，对手无法辩解。"
        scaffold_failures = "\n".join(
            _scene_contract_fulfillment_failures(scaffold, cards[12])
        )
        self.assertIn("模板语言", scaffold_failures)
        self.assertIn("“对手”", scaffold_failures)

        for chapter in (11, 12):
            body = "\n\n".join(
                _generic_contract_segment_fallback(cards[chapter], index)
                for index in range(1, 7)
            )
            self.assertGreaterEqual(len(body), 1000)
            body_failures = _chapter_body_hard_failures(
                body,
                chapter_num=chapter,
                chapter_card=cards[chapter],
            )
            if chapter == 11:
                self.assertTrue(
                    any(
                        "多段回忆" in item or "兜底模板" in item
                        for item in body_failures
                    )
                )
            else:
                self.assertTrue(
                    any(
                        "等长" in item or "兜底模板" in item
                        for item in body_failures
                    )
                )
            self.assertFalse(
                _scene_contract_fulfillment_failures(body, cards[chapter])
            )
            self.assertNotIn("闻溪闻溪", body)
            self.assertNotIn("上一世，上一世", body)
            self.assertNotIn("空白申请", body)
            self.assertNotIn("主角", body)
            self.assertNotIn("对手", body)

    def test_deus_ex_scan_ignores_explicit_rejection_but_catches_actual_use(self):
        rejected = (
            "闻溪不接受匿名爆料，也禁止匿名邮件推动核验，"
            "只核对购票人本人提交的记录。"
        )
        self.assertEqual([], _cluster_detect_deus_ex_machina(rejected))
        used = "核验陷入停滞时，一则匿名爆料突然送来了决定性名单。"
        self.assertEqual(
            ["匿名爆料"],
            _cluster_detect_deus_ex_machina(used),
        )

    def test_closed_scene_archetypes_generalize_across_unrelated_domains(self):
        def cluster(
            cluster_id,
            start,
            name,
            opponent,
            info_gap,
            revenge,
            outcome,
            first,
            second,
        ):
            return {
                "cluster_id": cluster_id,
                "name": name,
                "chapter_span": [start, start + 1],
                "main_opponent": opponent,
                "info_gap_from_prev_life": info_gap,
                "this_life_revenge": revenge,
                "cluster_outcome": outcome,
                "canonical_cast": [
                    {"name": "林澈", "role": "创作者", "alignment": "protagonist"},
                ],
                "chapter_milestones": [
                    {"chapter": start, **first},
                    {"chapter": start + 1, **second},
                ],
            }

        clusters = [
            cluster(
                "RIGHTS_GENERIC",
                41,
                "撤销代签协议并收回独立签署权",
                "顾问方",
                "林澈记得上一世隐藏条款会自动移交签署权。",
                "林澈查阅合同并要求公开复核协议。",
                "代签协议废除，林澈获得独立签署权。",
                {
                    "action": "林澈查阅合同并指出隐藏条款",
                    "opponent_reaction": "顾问方催促签字并试图收走合同",
                    "result": "林澈拒签并触发冷静期，代签授权被冻结",
                },
                {
                    "action": "林澈召集律师团队复核协议",
                    "opponent_reaction": "顾问方试图拖延会议",
                    "result": "代签协议被废除，顾问方失去代签权，林澈获得独立签署权",
                },
            ),
            cluster(
                "LIVE_GENERIC",
                43,
                "公开无修音排练撤销造谣方席位",
                "媒体机构与合作方",
                "林澈记得上一世失实指控的来源。",
                "林澈举办公开无修音排练并开放实时声轨。",
                "合作方撤回指控，林澈取得原声发布权。",
                {
                    "action": "林澈宣布公开无修音排练",
                    "opponent_reaction": "媒体机构继续散布失实消息",
                    "result": "林澈完整唱完作品，实时声轨公开，合作方失去采访席位",
                },
                {
                    "action": "林澈在连续拍摄中完整演唱",
                    "opponent_reaction": "媒体机构试图中断拍摄",
                    "result": "合作方撤回指控并退还预付款，林澈取得原声发布权",
                },
            ),
            cluster(
                "FINANCE_GENERIC",
                45,
                "冻结不当支出并取得基金监管权",
                "亲属与财务代理",
                "林澈记得上一世账单和收款账户的真实去向。",
                "林澈在支付会上核对账单和收款账户。",
                "亲属被停职，林澈获得基金监管权。",
                {
                    "action": "林澈让亲属当面申请接待费",
                    "opponent_reaction": "亲属把私人账单和收款账户投到会议屏幕",
                    "result": "林澈驳回付款并冻结账户，亲属失去单笔支付权",
                },
                {
                    "action": "林澈要求对账单进行双签审计",
                    "opponent_reaction": "亲属试图逃避责任",
                    "result": "亲属被停职，林澈获得基金监管权",
                },
            ),
            cluster(
                "ASSET_GENERIC",
                47,
                "叫停作品资产低价交易并取得优先回购权",
                "版权管理方",
                "林澈记得上一世母带交易的价格和流程。",
                "林澈冻结母带交易并推动独立估值。",
                "管理方失去低价打包权，林澈取得母带优先回购权。",
                {
                    "action": "林澈发现母带被低价打包",
                    "opponent_reaction": "版权管理方试图加快交易",
                    "result": "林澈通知律师并冻结母带交易",
                },
                {
                    "action": "林澈要求第三方完成独立估值",
                    "opponent_reaction": "版权管理方试图阻挠评估",
                    "result": "独立估值生效，管理方失去低价打包权，林澈取得母带优先回购权",
                },
            ),
        ]
        expected = {
            41: "contract_rights_audit",
            43: "live_capability_validation",
            45: "financial_process_audit",
            47: "asset_transaction_audit",
        }
        cards = _enrich_cards_with_cluster_milestones(
            _build_cards_from_clusters(clusters),
            clusters,
        )
        bodies = {}
        for chapter in range(41, 49):
            card = cards[chapter]
            _, specs = _closed_scene_segment_plan(card)
            segments = [
                _shape_closed_scene_segment_candidate(
                    _generic_contract_segment_fallback(card, index),
                    card,
                    target_max,
                    index,
                ).strip()
                for index, (_, target_max, _) in enumerate(specs, 1)
            ]
            body = "\n\n".join(segments)
            bodies[chapter] = body
            self.assertGreaterEqual(len(body), 1000, chapter)
            body_failures = _chapter_body_hard_failures(body, chapter, card)
            self.assertTrue(
                len(body) < _minimum_chapter_chars(chapter, card)
                or any(
                    "等长" in failure or "兜底模板" in failure
                    for failure in body_failures
                ),
                chapter,
            )
            self.assertFalse(
                _scene_contract_fulfillment_failures(body, card),
                chapter,
            )
            self.assertNotIn("主角", body, chapter)
            self.assertNotIn("对手", body, chapter)
        for first_chapter, archetype in expected.items():
            self.assertEqual(
                archetype,
                cards[first_chapter]["scene_contract"]["scene_archetype"],
            )
        self.assertNotIn("预付款", bodies[43])
        self.assertNotIn("原声发布权", bodies[43])
        self.assertIn("素材仍按原有权限封存", bodies[43])
        self.assertIn("预付款", bodies[44])
        self.assertIn("原声发布权", bodies[44])
        self.assertIn("上一场留下的实时声轨", bodies[44])
        self.assertNotIn("首次权限核验", bodies[45])
        self.assertIn("付款冻结状态复核", bodies[45])
        self.assertNotIn("私人收款去向", bodies[47])
        self.assertNotIn("由谁申请", bodies[47])
        self.assertNotIn("资金或资产", bodies[47])
        self.assertNotIn("首次权限核验", bodies[47])
        self.assertIn("交易冻结与资产保全状态复核", bodies[47])
        self.assertIn("估值依据", bodies[47])
        self.assertNotIn("母带、独立估值", bodies[48])
        self.assertIn("围绕母带的打包范围", bodies[48])
        self.assertIn("独立估值结果同步写入会议记录", bodies[48])
        for item in clusters:
            start, end = item["chapter_span"]
            result = _cluster_critic(
                item,
                {chapter: bodies[chapter] for chapter in range(start, end + 1)},
                chapter_cards=cards,
            )
            self.assertFalse(result["payoff_completed"])
            self.assertTrue(any(
                "字数不足" in violation
                for violation in result["violations"]
            ))

    def test_story_memory_receives_canonical_cast_that_acts_in_chapter(self):
        class MemoryProbe:
            known_names = []

            def review_candidate(
                self,
                chapter,
                content,
                known_names=(),
                forced_timeline="",
            ):
                self.known_names = list(known_names)
                return {}, []

        probe = MemoryProbe()
        generator = object.__new__(RebirthRevengeGeneratorV2)
        generator.story_memory = probe
        generator._get_card_for_chapter = lambda chapter: {
            "allowed_roles": ["闻溪", "主办方"],
            "main_opponent": "主办方",
            "canonical_cast": [
                {"name": "闻溪", "alignment": "protagonist"},
                {"name": "林澈", "alignment": "ally"},
                {"name": "顾遥", "alignment": "ally"},
            ],
        }
        generator.review_story_memory(
            11,
            "闻溪示意林澈继续核验，顾遥守在入口记录结果。",
        )
        self.assertIn("闻溪", probe.known_names)
        self.assertIn("林澈", probe.known_names)
        self.assertIn("顾遥", probe.known_names)

    def test_body_prompt_uses_runtime_rebirth_engine(self):
        theme_constraints.configure_theme_contract(
            "欧美娱乐圈重生复仇", "洛杉矶选角与颁奖季", ["Maya Reed"], "不要投资致富"
        )
        prompt = _build_cluster_body_part_prompt(
            cluster={"cluster_id": "EC02", "main_opponent": "Lila Voss", "core_payoff": "夺回角色"},
            cluster_synopsis="Maya在试镜现场抢先改变台词处理。",
            chapter_num=3,
            chapter_beats={"beats": [], "flashback_in_beat_idx": None},
            prev_tail_scene="Lila要求临时换台词。",
            prev_unresolved_hook="试镜即将开始。",
            chapter_card={"chapter_role_v2": "present_setup", "cluster_chapter_index": 1, "cluster_chapter_total": 3},
        )
        self.assertIn("旧局信号出现", prompt)
        self.assertIn("欧美娱乐圈重生复仇", prompt)
        self.assertNotIn("经济危机信号", prompt)

    def test_segment_overlap_guard_rejects_replayed_prior_beat(self):
        prior = (
            "麦珂走进医务室，负责人站在桌边，康拉德坐在对面。"
            "封签、送货单和领用簿并排放在桌上，三个人同时看见两行数量不一致。"
            "负责人抬手示意康拉德先作解释。"
        )
        replayed = (
            "麦珂走进医务室，负责人站在桌边，康拉德坐在对面。"
            "封签、送货单和领用簿并排放在桌上，三个人同时看见两行数量不一致。"
            "康拉德随后把手按在领用簿上。"
        )
        self.assertTrue(
            _segment_prior_prose_overlap_failure(replayed, [prior])
        )

    def test_segment_overlap_guard_allows_new_action_with_same_cast(self):
        prior = (
            "麦珂走进医务室，负责人站在桌边，康拉德坐在对面。"
            "负责人把送货单推到桌面中央，示意两人看清送达数量。"
        )
        advanced = (
            "康拉德先说领用簿只是临时补记，右手却一直压着纸角。"
            "麦珂没有接他的话，只请负责人当面念出两张纸上的不同数量。"
            "负责人读完后收起送货单，要求康拉德立刻交出保管钥匙。"
        )
        self.assertEqual(
            "",
            _segment_prior_prose_overlap_failure(advanced, [prior]),
        )

    def test_segment_overlap_guard_rejects_repeated_short_transition(self):
        prior = "卡尔把手停在控台边缘。音乐即将响起。"
        candidate = "合作方代表坐直身体。音乐即将响起。"
        self.assertTrue(
            _segment_prior_prose_overlap_failure(candidate, [prior])
        )

    def test_segment_semantic_repair_directive_prioritizes_missing_speech(self):
        oral = _segment_semantic_repair_directive(
            "见证节拍缺少口头通过结论"
        )
        dialogue = _segment_semantic_repair_directive(
            "准备节拍缺少对手完整降配对白"
        )
        proactive = _segment_semantic_repair_directive(
            "开场节拍缺少主角明确认出旧招并提前请见证"
        )
        settled = _segment_semantic_repair_directive(
            "收束节拍又开启技术挑错"
        )
        self.assertIn("首句", oral)
        self.assertIn("直接引语", oral)
        self.assertIn("通过", oral)
        self.assertIn("前两句", dialogue)
        self.assertIn("直接引语", dialogue)
        self.assertIn("上一世记忆", proactive)
        self.assertIn("提前请", proactive)
        self.assertIn("既成结果", settled)
        self.assertIn("不得出现任何表演", settled)

    def test_unknown_name_guard_ignores_role_followed_by_action_words(self):
        cast = [{"name": "麦珂·杰森"}, {"name": "卡尔·霍尔特"}]
        natural = (
            "合作方代表没再开口。现场见证人指尖离开椅背，"
            "负责人视线转向桌面。"
        )
        invented = "合作方代表王明走进排练场，径直站到控台旁。"
        self.assertEqual([], _unknown_named_roles_in_synopsis(natural, cast))
        self.assertIn("王明", _unknown_named_roles_in_synopsis(invented, cast))

    def test_generic_prose_guard_rejects_micro_choreography_and_duplicate_sentences(self):
        mechanical = "\n\n".join(
            (
                f"麦珂第{index}次抬手，指尖挪到桌边，脚步向前半步，"
                "气息沉入胸口，视线又移到卡尔手腕上。"
            )
            for index in range(1, 31)
        )
        failures = "\n".join(_generic_prose_quality_failures(mechanical))
        self.assertIn("细碎身体动作", failures)
        self.assertIn("距离、方向和站位", failures)

        duplicated = (
            "麦珂把排期表交给负责人，当场要求冻结超载排期。"
            "卡尔还想辩解。\n\n"
            "麦珂把排期表交给负责人，当场要求冻结超载排期。"
        ) * 12
        duplicate_failures = "\n".join(
            _generic_prose_quality_failures(duplicated)
        )
        self.assertIn("完全重复句", duplicate_failures)

    def test_grounded_prompt_uses_milestone_graph_context_and_only_sample_tags(self):
        card = {
            "chapter_id": 31,
            "cluster_id": "EC_WAREHOUSE",
            "cluster_chapter_index": 1,
            "cluster_chapter_total": 2,
            "chapter_role_v2": "present_setup",
            "chapter_goal": "要求传送带先用测试配重完成空载复验",
            "this_life_revenge": "林澈提前放置测试配重",
            "core_payoff": "罗文的违规复位当场暴露",
            "chapter_ending": "配重反向滑落，林澈叫停工人上岗",
            "chapter_milestone": {
                "chapter": 31,
                "action": "要求传送带先用测试配重完成空载复验",
                "opponent_reaction": "罗文抢过控制台跳过停机检查",
                "result": "配重反向滑落，林澈叫停工人上岗",
            },
            "main_opponent": "罗文·凯德",
            "info_gap_from_prev_life": "林澈记得传送带会反向运行",
            "canonical_cast": [
                {"name": "林澈", "role": "仓储经理", "alignment": "protagonist"},
                {"name": "罗文·凯德", "role": "承包主管", "alignment": "opponent"},
            ],
        }
        card["scene_contract"] = _derive_closed_scene_contract(card)
        prompt = _build_grounded_chapter_prompt(
            31,
            card,
            chapter_beats={"beats": [{"scene_goal": "调用未验收的秘密扫描设备"}]},
            kg_context="既有事实：罗文仍掌握设备调度；上一章没有发生伤亡。",
            rag_samples={
                "revenge": [{
                    "emotion_tags": ["压迫转反击"],
                    "conflict_tags": ["公开阻挠"],
                    "action_tags": ["抢先布置"],
                    "plot_tags": ["即时回报"],
                    "content": "这段样本文字绝不能出现在提示词中。",
                }]
            },
        )
        self.assertIn("唯一事件事实，情节族约束的最高优先级", prompt)
        self.assertIn("罗文抢过控制台跳过停机检查", prompt)
        self.assertIn("由场景类型编译的单一因果脊柱", prompt)
        self.assertIn("场景边界", prompt)
        self.assertIn("设备说明不超过全文三分之一", prompt)
        self.assertIn("本场可写的事实载体只有", prompt)
        self.assertIn("既有事实：罗文仍掌握设备调度", prompt)
        self.assertIn("压迫转反击", prompt)
        self.assertNotIn("调用未验收的秘密扫描设备", prompt)
        self.assertNotIn("这段样本文字绝不能出现在提示词中", prompt)
        self.assertEqual(1, prompt.count("要求传送带先用测试配重完成空载复验"))
        self.assertEqual(1, prompt.count("罗文抢过控制台跳过停机检查"))
        self.assertEqual(1, prompt.count("配重反向滑落，林澈叫停工人上岗"))
        self.assertIn("现实中完全相同", _build_chapter_quality_critic_prompt(
            31,
            "林澈当场叫停设备。",
            card,
        ))

    def test_grounded_prompt_isolates_future_milestone_materials(self):
        card = {
            "chapter_id": 5,
            "cluster_id": "EC_MEDICAL",
            "cluster_chapter_index": 1,
            "cluster_chapter_total": 2,
            "chapter_role_v2": "present_setup",
            "chapter_goal": "在合作方见证下完成现场表演能力测试",
            "this_life_revenge": "林澈提前请合作方见证现场表演能力测试",
            "core_payoff": "合作方撤下不实宣传，林澈收回训练决定权",
            "chapter_ending": "林澈完成测试，合作方撤下不实宣传",
            "main_opponent": "罗文·凯德",
            "info_gap_from_prev_life": "林澈记得上一世被问题药物拖垮",
            "canonical_cast": [
                {"name": "林澈", "role": "表演者", "alignment": "protagonist"},
                {"name": "罗文·凯德", "role": "训练主管", "alignment": "opponent"},
            ],
            "chapter_milestone": {
                "chapter": 5,
                "action": "在合作方见证下完成现场表演能力测试",
                "opponent_reaction": "罗文试图降低测试强度",
                "result": "林澈完成测试，合作方撤下不实宣传",
            },
            "cluster_milestones": [
                {
                    "chapter": 5,
                    "action": "在合作方见证下完成现场表演能力测试",
                    "opponent_reaction": "罗文试图降低测试强度",
                    "result": "林澈完成测试，合作方撤下不实宣传",
                },
                {
                    "chapter": 6,
                    "action": "核对针剂封签、送货单和领用簿",
                    "opponent_reaction": "保管人试图辩解",
                    "result": "保管人被暂停职务，林澈获得药品保管权",
                },
            ],
            "theme_contract": {
                "theme": "表演者重生后夺回职业控制",
                "background": "架空现代演出产业",
                "protagonists": ["林澈"],
                "extra_constraints": "终局将出现秘密母带交易与保险理赔。",
                "hard_constraints": ["已发生事实不得无解释改写。"],
                "forbidden_elements": ["匿名消息解决核心矛盾"],
            },
        }
        card["scene_contract"] = _derive_closed_scene_contract(card)
        future = _future_milestone_materials(5, card)
        self.assertIn("针剂", future)
        self.assertIn("封签", future)
        self.assertIn("送货单", future)
        self.assertIn("领用簿", future)
        self.assertIn("药品保管权", future)

        prompt = _build_grounded_chapter_prompt(
            5,
            card,
            kg_context=(
                "既有事实：问题针剂已经封存。"
                "既有事实：罗文仍负责训练安排。"
            ),
        )
        self.assertIn("未来材料隔离", prompt)
        self.assertIn("隔离 5 项后续里程碑专属材料或权限", prompt)
        self.assertNotIn("针剂", prompt)
        self.assertNotIn("封签", prompt)
        self.assertNotIn("送货单", prompt)
        self.assertNotIn("领用簿", prompt)
        self.assertNotIn("药品保管权", prompt)
        self.assertIn("罗文仍负责训练安排", prompt)
        self.assertIn("能力展示不超过全文四分之一", prompt)
        self.assertNotIn("秘密母带交易与保险理赔", prompt)
        self.assertIn("在开篇三分之一内只写一次私下的旧局识别", prompt)
        self.assertIn("用“提前”或“先一步”", prompt)
        self.assertEqual(
            1,
            prompt.count("在合作方见证下完成现场表演能力测试"),
        )
        failures = "\n".join(
            _chapter_body_hard_failures(
                "林澈完成测试后又拿出针剂封签和送货单，宣布自己获得药品保管权。",
                5,
                card,
            )
        )
        self.assertIn("提前使用后续里程碑", failures)

        over_choreographed = (
            "上一世，罗文也用保护话术降低标准。林澈提前请合作方到场。"
            "第一段里他腾空又跪地，胸廓起伏被见证人逐项观察。"
            "第二段里他撑地翻滚，唱完十六个小节，见证人宣布测试通过。"
            "合作方撤下不实宣传。"
        )
        prose_failures = "\n".join(
            _chapter_body_hard_failures(over_choreographed, 5, card)
        )
        self.assertIn("解剖或医学术语", prose_failures)
        self.assertIn("危险特技", prose_failures)
        self.assertIn("编号式轮次或乐段", prose_failures)

    def test_quality_review_parser_is_strict_and_applies_thresholds(self):
        accepted = _parse_chapter_quality_review(
            """
            {
              "accept": true,
              "scores": {
                "cluster_fidelity": 9,
                "causal_clarity": 8,
                "prose_naturalness": 8,
                "emotional_force": 7,
                "non_repetition": 8,
                "ending_precision": 8,
                "fictional_naming": 9
              },
              "hard_failures": [],
              "summary": "可交付"
            }
            """
        )
        self.assertIsNotNone(accepted)
        self.assertTrue(accepted["accept"])

        low_score = _parse_chapter_quality_review(
            """
            {
              "accept": true,
              "scores": {
                "cluster_fidelity": 7,
                "causal_clarity": 8,
                "prose_naturalness": 8,
                "emotional_force": 7,
                "non_repetition": 8,
                "ending_precision": 8,
                "fictional_naming": 9
              },
              "hard_failures": [],
              "summary": "里程碑仍有缺口"
            }
            """
        )
        self.assertIsNotNone(low_score)
        self.assertFalse(low_score["accept"])
        self.assertIn("cluster_fidelity", low_score["low_scores"])
        self.assertIsNone(_parse_chapter_quality_review("不是 JSON"))

    def test_cluster_critic_fails_closed_on_any_chapter_length_violation(self):
        cluster = {
            "cluster_id": "EC_LENGTH",
            "chapter_span": [5, 6],
            "main_opponent": "卡尔",
            "info_gap_from_prev_life": "",
            "cluster_outcome": "卡尔失去排期权，麦珂获得最终否决权",
            "core_payoff": "卡尔失去排期权，麦珂获得最终否决权",
        }
        short_setup = "卡尔提出超载排期，麦珂当场拒绝。"
        settlement = (
            "卡尔失去排期权，麦珂获得最终否决权。"
            "负责人当场宣布决定生效，卡尔无法撤回安排。"
        ) * 40
        result = _cluster_critic(
            cluster,
            {5: short_setup, 6: settlement},
        )
        self.assertTrue(any("第5章字数不足" in item for item in result["violations"]))
        self.assertFalse(result["payoff_completed"])


if __name__ == "__main__":
    unittest.main()

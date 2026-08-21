from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bert_excitation_train.scripts.v2.pop_king_plan_compiler import (
    apply_state_transitions,
    body_prefix_fingerprints,
    canonical_sha256,
    plan_fingerprints,
    timeline_point,
    validate_full_plan,
    validate_chronology_prefix,
    event_type_semantic_failures,
    validate_event_batch,
)
from bert_excitation_train.scripts.v2.generate_pop_king_500_qwen import (
    CHAPTER_CARD_COMPILER_VERSION,
    _archive_stale_downstream_if_outline_changed,
    _fake_death_failures,
    _chapter_card,
    _compile_chapter_input_from_milestone,
    _merge_continuity_ledger,
    _archive_stale_detail_plan_if_blocks_changed,
    _early_planning_semantic_failures,
    _unavailable_technology,
    _validate_block_backbone,
    _compile_macro_direction_fields,
    _global_semantic_failures,
    _assemble_global_narrative,
    _validate_global_narrative_segment,
    _validate_global_long_arcs,
    _bind_legacy_global_identities,
    GLOBAL_ARC_IDENTITIES,
    _validate_events,
    _call_qwen,
    _validate_macro_core,
    _validate_macro_direction_batch,
    _macro_direction_schema,
    _normalize_locked_macro_direction,
)
from bert_excitation_train.scripts.v2 import generate_pop_king_500_qwen as planner_module


def test_legacy_global_arc_names_compile_to_stable_identities() -> None:
    arcs = []
    legacy_names = [
        "玛莎·杰森", "黛安娜·洛瑞", "昆廷·索恩", "瑟琳娜·瓦尔", "莉薇娅·科尔",
        "艾琳·哈珀", "苏菲亚·陈", "维克多·兰斯", "巴里", "莱昂",
    ]
    for index, name in enumerate(legacy_names):
        arcs.append({
            "character": name,
            "first_active_phase": f"P{min(index + 1, 10):02d}",
            "initial_desire": f"{name}希望守住自己的长期选择",
            "long_term_change": f"{name}在冲突中逐步改变并承担代价",
            "relationship_with_protagonist": f"{name}与麦珂形成持续变化的关系",
            "final_state": f"2009年{name}完成自己的最终选择",
        })
    normalized = _bind_legacy_global_identities({"character_long_arcs": arcs})
    for arc, expected in zip(normalized["character_long_arcs"], GLOBAL_ARC_IDENTITIES):
        assert arc["character_id"] == expected["character_id"]
        assert arc["character"] == expected["character"]
        assert arc["aliases"] == expected["aliases"]
    assert "巴里·布鲁姆·布鲁姆" not in json.dumps(normalized, ensure_ascii=False)


def _card(chapter_id: int, year: int) -> dict:
    return {
        "chapter_id": chapter_id,
        "chapter_role_v2": "rebirth_confirmation" if chapter_id == 2 else "two_chapter_payoff",
        "timeline_years": str(year),
    }


def test_early_backbone_rejects_child_fake_precision_and_legal_engineering() -> None:
    backbone = {
        "block_id": "B001", "chapter_span": [1, 20], "block_title": "重返试镜",
        "timeline_years": "2009→1969", "coarse_story_summary": "舞台成长" * 100,
        "entry_state": {"health_and_location": "2009临终医疗房间，仍有生命体征"},
        "block_goal": "夺回声音主权并开始拆除控制体系" * 3,
        "main_conflict": "奥瑞恩集团试图利用童星机制控制他的作品与家庭" * 3,
        "rebirth_advantage": "麦珂记住阅读停顿毫秒数并亲自手写合同附录" * 3,
        "character_movements": ["玛莎独立拒绝控制", "麦珂取得舞台机会"],
        "rights_health_relationship_changes": {}, "continuity_update": {},
        "block_outcome": "麦珂靠作品获得同期观众认可并保住家庭联系" * 3,
        "handoff_to_next_block": "第一次胜利引来新的市场阻力" * 3,
    }
    failures = _validate_block_backbone(backbone, 1)
    assert any("假精确" in item for item in failures)
    assert any("法律文书" in item for item in failures)


def test_batched_macro_core_keeps_event_directions_out_of_small_request() -> None:
    core = {
        "macro_group_id": "MG003",
        "chapter_span": [21, 30],
        "title": "舞台夺权",
        "timeline_years": "1971—1972",
        "macro_goal": "麦珂用新作品取得现场排练和演出编排的实际主动权",
        "historical_stage": "架空米国七十年代初的巡演排练与地方电视舞台",
        "main_conflict": "旧经纪体系想借临时替换节目压低麦珂的创作与演出话语权",
        "rebirth_advantage": "麦珂记得上一世节目单更换的日期、暗号和负责人临场选择",
        "romance_progression": "麦珂仍未成年，本组只推进家人与伙伴之间的信任",
        "ending_state": "麦珂保住两首作品和主舞台时段，母子决策边界更加清楚",
        "next_group_hook": "公开舞台胜利迫使唱片方改用发行资源制造下一轮压力",
    }
    assert _validate_macro_core(core, 3) == []
    core["five_event_directions"] = []
    assert any("不得提前输出" in item for item in _validate_macro_core(core, 3))


def test_locked_macro_structure_normalization_does_not_rewrite_story_facts() -> None:
    raw = {
        "cluster_id": "wrong", "chapter_span": [99, 100],
        "opposition_type": "wrong", "event_type": "wrong",
        "solution_type": "wrong", "death_chain_role": "wrong",
        "locked_story_brief": "wrong",
        "previous_life_harm": "乔纳上一世截住了决定试镜命运的回函",
    }
    normalized = _normalize_locked_macro_direction(raw, 1, 3)
    expected = _macro_direction_schema(1, 3)
    for field in (
        "cluster_id", "chapter_span", "opposition_type", "event_type",
        "solution_type", "death_chain_role", "locked_story_brief",
    ):
        assert normalized[field] == expected[field]
    assert normalized["previous_life_harm"] == raw["previous_life_harm"]


def test_ec002_macro_direction_rejects_signing_and_wrong_gender() -> None:
    direction = _macro_direction_schema(1, 2)
    direction.update({
        "previous_life_harm": "乔纳上一世用今日截止的谎话催促麦珂马上签约",
        "unique_prev_life_info": "麦珂记得乔纳所谓报名截止日其实还有两周",
        "preemptive_action": "麦珂问玛莎为什么不能带回家看，玛莎决定暂停并请律师审查",
        "chapter_one_small_win": "玛莎收起钢笔，让对方无法当场逼迫速签",
        "chapter_two_showdown": "麦珂只请求对方给出更公平的合同",
        "opponent_permanent_loss": "乔纳失去利用假截止日迫家庭速签的通道",
        "protagonist_concrete_gain": "她签下一份可撤销的合同并获得律师",
        "irreversible_outcome_key": "麦珂完成签约",
        "death_chain_connection": "第一次切断日后死亡控制链的权利入口",
        "direction": "",
    })
    failures = _validate_macro_direction_batch(
        {"macro_group_id": "MG001", "event_directions": [direction]},
        macro_index=1, block_index=1, event_indices=[2], prior_directions=[],
    )
    assert any("不得让麦珂在本事件签下合同" in item for item in failures)
    assert any("不得用“她”" in item for item in failures)


def test_batched_macro_directions_require_distinct_rebirth_information_and_settlement() -> None:
    def direction(event_index: int, info: str, outcome: str) -> dict:
        return {
            "cluster_id": f"EC{event_index:03d}",
            "chapter_span": [event_index * 2 - 1, event_index * 2],
            "opposition_type": "villain",
            "event_type": "performance",
            "solution_type": "performance_proof",
            "death_chain_role": "pressure",
            "previous_life_harm": "上一世节目临时被撤，麦珂失去全国观众与后续机会",
            "unique_prev_life_info": info,
            "preemptive_action": "麦珂先让母亲要求公开节目顺序并准备同期替代曲目",
            "chapter_one_small_win": "第一章麦珂赢得完整彩排并让现场乐队愿意配合",
            "chapter_two_showdown": "第二章对手临场撤歌，麦珂用已排练的新作正面接住",
            "opponent_permanent_loss": "节目主管失去临时撤换主节目单的单方权限",
            "protagonist_concrete_gain": "麦珂取得两首原创歌曲的固定直播演出时段",
            "irreversible_outcome_key": outcome,
            "death_chain_connection": "控制体系失去借舞台排程压迫创作者签权利文件的能力",
            "direction": "",
        }

    first = direction(11, "记得五月三日晚七点主管会用蓝色节目单撤掉压轴曲", "主管临时撤歌权限永久取消")
    second = direction(12, "记得六月九日午后赞助人会要求把独唱换成集体串烧", "赞助方单方换曲权限永久取消")
    payload = {"macro_group_id": "MG003", "event_directions": [first, second]}
    assert _validate_macro_direction_batch(
        payload, macro_index=3, block_index=2,
        event_indices=[11, 12], prior_directions=[],
    ) == []

    second["unique_prev_life_info"] = first["unique_prev_life_info"]
    failures = _validate_macro_direction_batch(
        payload, macro_index=3, block_index=2,
        event_indices=[11, 12], prior_directions=[],
    )
    assert any("前批事件重复" in item for item in failures)

    second["unique_prev_life_info"] = "记得六月九日午后赞助人会要求把独唱换成集体串烧"
    first["opponent_permanent_loss"] = _macro_direction_schema(2, 11)["opponent_permanent_loss"]
    failures = _validate_macro_direction_batch(
        payload, macro_index=3, block_index=2,
        event_indices=[11, 12], prior_directions=[],
    )
    assert any("照抄了JSON字段说明" in item for item in failures)


def test_groq_transient_tpm_window_waits_and_retries_same_model() -> None:
    rate_error = RuntimeError(
        'rate_limit_exceeded: Used 2800, Requested 5700. Please try again in 465ms.'
    )
    response = {
        "choices": [{"message": {"content": "{}"}}],
        "usage": {"prompt_tokens": 100},
    }
    sleeps: list[float] = []
    with mock.patch.dict(
        "os.environ",
        {"GROQ_API_KEY": "test-key", "PLANNER_PROVIDER": "groq"},
        clear=False,
    ), mock.patch.object(
        planner_module, "_GROQ_VISIBLE_MODELS", ["openai/gpt-oss-120b"],
    ), mock.patch.object(
        planner_module, "call_openai_compatible_via_curl",
        side_effect=[rate_error, response],
    ) as transport, mock.patch.object(
        planner_module.time, "sleep", side_effect=lambda seconds: sleeps.append(seconds),
    ):
        raw, metadata = _call_qwen(
            [{"role": "user", "content": "test"}],
            model="unused", temperature=0.7, max_output_tokens=1200,
        )
    assert raw == "{}"
    assert metadata["model"] == "openai/gpt-oss-120b"
    assert transport.call_count == 2
    assert sleeps and sleeps[0] >= 1.0


def test_groq_daily_model_quota_falls_back_to_next_allowed_model() -> None:
    daily_error = RuntimeError(
        'rate_limit_exceeded on tokens per day (TPD): Limit 200000, Used 194972, '
        'Requested 5952. Please try again in 6m39s.'
    )
    response = {"choices": [{"message": {"content": "{}"}}], "usage": {}}
    with mock.patch.dict(
        "os.environ",
        {
            "GROQ_API_KEY": "test-key", "PLANNER_PROVIDER": "groq",
            "GROQ_PLANNER_MODEL": "openai/gpt-oss-120b",
            "GROQ_PLANNER_FALLBACK_MODELS": "openai/gpt-oss-20b",
        },
        clear=False,
    ), mock.patch.object(
        planner_module, "_GROQ_VISIBLE_MODELS",
        ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
    ), mock.patch.object(
        planner_module, "call_openai_compatible_via_curl",
        side_effect=[daily_error, response],
    ) as transport:
        raw, metadata = _call_qwen(
            [{"role": "user", "content": "test"}],
            model="unused", temperature=0.7, max_output_tokens=1200,
        )
    assert raw == "{}"
    assert transport.call_count == 2
    assert metadata["model"] == "openai/gpt-oss-20b"
    assert metadata["capacity_model_fallbacks"] == ["openai/gpt-oss-120b"]


def test_first_block_backbone_rejects_opening_only_summary() -> None:
    backbone = {
        "block_id": "B001", "chapter_span": [1, 20], "block_title": "试镜开端",
        "timeline_years": "1969-1970", "coarse_story_summary": "麦珂在1969试镜后台观察合同" * 40,
        "entry_state": {"health_and_location": "身体健康，身处1969试镜后台"},
        "block_goal": "取得声音自主权并避免再次被控制" * 4,
        "main_conflict": "奥瑞恩集团试图利用童星合约控制他" * 4,
        "rebirth_advantage": "记得上一世谁在何时说了哪些误导性原话" * 4,
        "character_movements": ["玛莎开始思考", "乔纳急于签约"],
        "rights_health_relationship_changes": {}, "continuity_update": {},
        "block_outcome": "麦珂在试镜中获得关注" * 5,
        "handoff_to_next_block": "下一步将是正式签约与合同审核" * 3,
    }
    failures = _validate_block_backbone(backbone, 1)
    assert any("entry_state" in item and "2009" in item for item in failures)
    assert any("不能只写试镜开头" in item for item in failures)
    assert any("拖到下一20章" in item for item in failures)


def test_1969_technology_gate_includes_social_platforms() -> None:
    unavailable = _unavailable_technology("1969-1970")
    assert "社交媒体" in unavailable
    assert "社交平台" in unavailable
    assert "网络上传" in unavailable


def test_early_semantic_gate_rejects_frequency_even_outside_event_details() -> None:
    failures = _early_planning_semantic_failures("麦珂记住母亲手指微颤频率", "B001")
    assert failures and "微颤频率" in failures[0]


def test_macro_direction_is_compiled_losslessly_from_single_source_fields() -> None:
    raw = {"five_event_directions": [{
        "chapter_span": [3, 4], "previous_life_harm": "前世被限时报名谎言催促速签",
        "unique_prev_life_info": "乔纳会在十一月七日重复限时报名谎话",
        "preemptive_action": "麦珂只向玛莎提出为何不能带回家看的问题",
        "chapter_one_small_win": "玛莎暂时收起钢笔并要求带走副本",
        "chapter_two_showdown": "玛莎让成年人律师审查后再与厂牌交锋",
        "opponent_permanent_loss": "控制方永久失去当天速签通道",
        "protagonist_concrete_gain": "麦珂获得受审查的公平谈判机会",
        "irreversible_outcome_key": "当天速签通道关闭",
        "death_chain_connection": "切断死亡控制体系最早的监护入口",
        "direction": "",
    }]}
    compiled = _compile_macro_direction_fields(raw)
    direction = compiled["five_event_directions"][0]["direction"]
    assert "第3章可见小赢" in direction
    assert "第4章新交锋" in direction
    assert raw["five_event_directions"][0]["unique_prev_life_info"] in direction
    assert raw["five_event_directions"][0]["direction"] == ""


def test_global_semantic_gate_rejects_reviewed_bad_solutions_but_allows_negation() -> None:
    failures = _global_semantic_failures(
        "今生他服用镇静剂模拟嗜睡，终局再用声纹锁芯开启证据舱", "全书叙事"
    )
    assert any("镇静剂模拟" in item for item in failures)
    assert any("声纹锁芯" in item for item in failures)
    assert _global_semantic_failures("严禁今生镇静剂模拟；不得采用声纹锁芯", "规则") == []


def test_global_semantic_gate_rejects_real_world_names_and_future_knowledge_leak() -> None:
    failures = _global_semantic_failures(
        "2005年他出版自传，公开还原2009年死亡全过程，并在纽约获Thriller奖", "S3"
    )
    assert any("时间倒置" in item for item in failures)
    assert any("纽约" in item for item in failures)
    assert any("Thriller" in item for item in failures)


def test_global_narrative_segments_assemble_in_order_without_rewriting() -> None:
    core = {
        "story_title": "星火", "one_sentence_premise": "重生后逐步反击",
        "core_rebirth_logic": {"x": 1}, "romance_overview": "关系总线",
        "ending_convergence": "终局现场", "downstream_nonnegotiables": ["事实"],
    }
    segments = [
        {"opening_state": "2009临终后重生1969", "segment_synopsis": "前段正文", "handoff": "前段交接", "romance_progression": "前段关系"},
        {"segment_synopsis": "中段正文", "handoff": "中段交接", "romance_progression": "中段关系"},
        {"segment_synopsis": "后段正文", "handoff": "后段收束", "romance_progression": "后段关系"},
    ]
    assembled = _assemble_global_narrative(core, segments)
    assert assembled["full_story_synopsis"] == (
        "2009临终后重生1969\n\n前段正文\n\n前段交接\n\n"
        "中段正文\n\n中段交接\n\n后段正文\n\n后段收束\n\n终局现场"
    )
    assert assembled["romance_long_arc"].splitlines() == ["关系总线", "前段关系", "中段关系", "后段关系"]
    assert len(assembled["assembled_from_qwen_batches"]) == 4


def test_global_segment_scans_handoff_for_future_media() -> None:
    segment = {
        "segment_id": "S1",
        "opening_state": "2009临终后回到1969十一岁试镜后台，记住第一份合同的日期和原话" * 2,
        "segment_synopsis": (
            "1969年他依靠前世受害记忆避开第一份合同陷阱，以原创歌曲和舞台表演得到观众认可，"
            "玛莎独立寻找成年人帮助，家人也在市场变化中重新选择。" * 20
        ),
        "romance_progression": "未成年时期只建立平等友谊，双方各有事业选择和完整自主权。" * 2,
        "closing_state": "1982年作品、舞台、家庭与市场状态已经改变，并自然进入下一阶段。" * 2,
        "handoff": "1982年公众通过网络留言响应新专辑，引来下一轮竞争压力。" * 2,
    }
    failures = _validate_global_narrative_segment(segment, 1)
    assert any("网络留言" in item for item in failures)


def test_final_appearance_in_authored_handoff_is_part_of_formal_narrative() -> None:
    segment = {
        "segment_id": "S3",
        "opening_state": "1999年，事业与家庭都进入终局压力区，敌人重新合流。" * 2,
        "segment_synopsis": (
            "1999年至2009年，他继续创作作品、完成巡演、陪伴家人、经营公益并保护健康，"
            "观众与市场共同见证其事业成熟。" * 20
        ),
        "romance_progression": "成年人彼此尊重事业与私人选择，在终局压力中保有自主。" * 2,
        "closing_state": "事业、家庭、健康和公众关系完成终局收束，旧利益链失去控制。" * 2,
        "handoff": "麦珂本人走入全球纪念直播现场，把自己的葬礼变成公开审判。" * 2,
    }
    failures = _validate_global_narrative_segment(segment, 3)
    assert not any("正式叙事" in item for item in failures)


def test_global_semantic_gate_rejects_terminal_year_conflicts_and_real_chinese_locations() -> None:
    failures = _global_semantic_failures(
        "1999年他用二维码公开2009年死亡流程，2009年死忌二十周年时从云南前往内蒙古",
        "S3",
    )
    assert any("二维码" in item for item in failures)
    assert any("死亡周年" in item for item in failures)
    assert any("云南" in item for item in failures)


def test_early_life_segment_rejects_enemy_believing_public_star_already_dead() -> None:
    segment = {
        "segment_id": "S2",
        "opening_state": "1983年，麦珂已经是公开演出并持续发行作品的知名歌手。" * 2,
        "segment_synopsis": (
            "他继续创作、巡演、照顾家庭并维护健康，敌人不断在市场上施压，观众支持他。" * 20
        ),
        "romance_progression": "成年关系建立在相互尊重与独立选择上，任何一方都能退出。" * 2,
        "closing_state": "1998年，敌人误以为麦珂已经死去，因此停止关注他的公开演出。" * 2,
        "handoff": "旧控制方准备在2009年利用健康和保险安排实施前世方案。" * 2,
    }
    failures = _validate_global_narrative_segment(segment, 2)
    assert any("敌人认知时间倒置" in item for item in failures)


def test_plan_fingerprints_change_when_a_card_changes() -> None:
    kwargs = {
        "outline": {"title": "x"}, "events": [{"cluster_id": "EC001"}],
        "cards": [{"chapter_id": 1}], "style_samples": [{"sample_id": "S1"}],
    }
    first = plan_fingerprints(**kwargs)
    kwargs["cards"] = [{"chapter_id": 1, "chapter_goal": "changed"}]
    second = plan_fingerprints(**kwargs)
    assert first["chapter_cards_sha256"] != second["chapter_cards_sha256"]
    assert first["plan_bundle_sha256"] != second["plan_bundle_sha256"]


def test_body_prefix_fingerprint_ignores_only_later_appended_events() -> None:
    outline = {"title": "fixed broad outline"}
    style = [{"sample_id": "S1"}]
    first_event = {"cluster_id": "EC001", "fact": "first"}
    first_cards = [{"chapter_id": 1}, {"chapter_id": 2}]
    original = body_prefix_fingerprints(
        outline=outline, events=[first_event], cards=first_cards,
        style_samples=style, through_cluster=1,
    )
    appended = body_prefix_fingerprints(
        outline=outline,
        events=[first_event, {"cluster_id": "EC002", "fact": "later"}],
        cards=first_cards + [{"chapter_id": 3}, {"chapter_id": 4}],
        style_samples=style, through_cluster=1,
    )
    assert appended == original
    changed_prior = body_prefix_fingerprints(
        outline=outline,
        events=[{**first_event, "fact": "changed"}],
        cards=first_cards, style_samples=style, through_cluster=1,
    )
    assert changed_prior["plan_prefix_bundle_sha256"] != original["plan_prefix_bundle_sha256"]


def test_canonical_hash_ignores_dictionary_key_order() -> None:
    assert canonical_sha256({"a": 1, "b": 2}) == canonical_sha256({"b": 2, "a": 1})


def test_state_machine_rejects_duplicate_and_post_irreversible_transition() -> None:
    first = {
        "domain": "job", "entity_id": "CHAR_CONRAD", "state_key": "medical_license",
        "from": "active", "to": "revoked", "irreversible": True, "evidence": "board order",
    }
    state, locked, failures = apply_state_transitions([first])
    assert failures == []
    _, _, duplicate = apply_state_transitions([first], state, locked)
    assert any("重复写入" in item for item in duplicate)
    changed = {**first, "from": "revoked", "to": "active"}
    _, _, reopened = apply_state_transitions([changed], state, locked)
    assert any("不可逆状态" in item for item in reopened)


def test_chronology_allows_rebirth_jump_but_rejects_later_regression() -> None:
    cards = [_card(1, 2009), _card(2, 1969), _card(3, 1970), _card(4, 1968)]
    failures = validate_chronology_prefix(cards)
    assert len(failures) == 1
    assert "第4章" in failures[0]


def test_timeline_point_supports_year_month_day_precision() -> None:
    assert timeline_point("1969-11-04").isoformat() == "1969-11-04"
    assert timeline_point("1969-11", end=True).isoformat() == "1969-11-30"
    assert timeline_point("1969-02-30") is None


def _compiled_event_and_cards(*, future_reference: bool = False) -> tuple[list[dict], list[dict]]:
    prior_artifact = {"artifact_id": "ART_ACCOUNT_001", "timeline_scope": "previous_life", "display_name": "联名账户", "kind": "account"}
    current_artifact = {"artifact_id": "ART_ACCOUNT_001", "timeline_scope": "current", "display_name": "联名账户", "kind": "account"}
    milestones = [
        {
            "chapter_id": 1, "timeline_start": "2009-04-25", "timeline_end": "2009-04-25",
            "scene": "病房", "scenes": [{"sequence": 1, "location": "病房", "is_primary": True}],
            "artifact_creates": [] if future_reference else [prior_artifact],
            "artifact_refs": [{"artifact_id": "ART_ACCOUNT_001", "timeline_scope": "previous_life"}] if future_reference else [],
            "chapter_goal": "确认死亡利益链", "action_sequence": ["听见对话", "确认药物", "失去意识"],
            "visible_payoff": "看清真凶", "ending": "重生",
        },
        {
            "chapter_id": 2, "timeline_start": "1969-11-04", "timeline_end": "1969-11-04",
            "scene": "试镜后台", "scenes": [{"sequence": 1, "location": "试镜后台", "is_primary": True}],
            "artifact_creates": [current_artifact] if future_reference else [],
            "artifact_refs": [] if future_reference else [],
            "chapter_goal": "完成第一次避险", "action_sequence": ["确认重生", "预判陷阱", "提前避开"],
            "visible_payoff": "获得试镜机会", "ending": "进入今生",
        },
    ]
    event = {
        "cluster_id": "EC001", "chapter_span": [1, 2],
        "opposition_type": "villain", "event_type": "performance", "solution_type": "performance_proof",
        "fictional_obstacle": "设备陷阱", "preemptive_avoidance": "提前避开",
        "bait_and_evidence": "现场见证", "villain_loss": "失去控制", "protagonist_gain": "获得机会",
        "cluster_outcome": "完成重生首胜", "two_chapter_structure": milestones,
        "state_transitions": [{
            "domain": "reputation", "entity_id": "CHAR_MAIKE", "state_key": "audition_status",
            "from": "none", "to": "accepted", "irreversible": False, "evidence": "现场通过",
        }],
    }
    cards = []
    for milestone in milestones:
        cid = milestone["chapter_id"]
        cards.append({
            "chapter_id": cid, "cluster_id": "EC001",
            "chapter_role_v2": "previous_life_death" if cid == 1 else "rebirth_confirmation",
            "timeline_years": "2009" if cid == 1 else "1969",
            "timeline_start": milestone["timeline_start"], "timeline_end": milestone["timeline_end"],
            "scene_location": milestone["scene"], "scenes": milestone["scenes"],
            "artifact_creates": milestone["artifact_creates"], "artifact_refs": milestone["artifact_refs"],
            "source_milestone_sha256": canonical_sha256(milestone),
            "source_event_sha256": canonical_sha256(event),
        })
    return [event], cards


def test_artifact_cannot_be_referenced_before_creation() -> None:
    events, cards = _compiled_event_and_cards(future_reference=True)
    failures = validate_full_plan(events, cards)["failures"]
    assert any("提前引用尚未创建" in failure for failure in failures)


def test_rebirth_jump_is_allowed_for_exact_dates() -> None:
    events, cards = _compiled_event_and_cards()
    failures = validate_full_plan(events, cards)["failures"]
    assert not any("精确时间线" in failure for failure in failures)


def test_previous_life_artifact_cannot_cross_rebirth_boundary() -> None:
    events, cards = _compiled_event_and_cards()
    cards[1]["artifact_refs"] = [{
        "artifact_id": "ART_ACCOUNT_001", "timeline_scope": "previous_life",
    }]
    failures = validate_full_plan(events, cards)["failures"]
    assert any("跨到current时间线" in failure for failure in failures)


def test_card_must_bind_complete_event_hash() -> None:
    events, cards = _compiled_event_and_cards()
    cards[1]["source_event_sha256"] = "stale"
    failures = validate_full_plan(events, cards)["failures"]
    assert any("完整事件哈希" in failure for failure in failures)


def test_partial_compiler_accepts_only_expanded_event_prefix() -> None:
    events, cards = _compiled_event_and_cards()
    report = validate_full_plan(events, cards, allow_partial=True)
    assert not any("部分规划也必须" in failure for failure in report["failures"])


def test_global_arc_identity_rejects_renamed_or_abbreviated_character() -> None:
    arcs = []
    for identity in GLOBAL_ARC_IDENTITIES:
        arcs.append({
            **identity, "first_active_phase": "P01", "initial_desire": "希望保护自己和家人",
            "long_term_change": "逐步拥有独立而完整的人生选择权",
            "relationship_with_protagonist": "从相识到能够自主支持麦珂的长期伙伴",
            "final_state": "在2009年终局保有自己的事业和选择",
        })
    arcs[1]["character"] = "黛安娜·洛瑞"
    arcs[-2]["character"] = "巴里"
    causal = [{
        "spine_id": f"CS{i:02d}", "phase_range": "P01→P10",
        "cause": f"第{i}条不同起因推动利益关系发生变化",
        "protagonist_choice": "麦珂依据前世信息差提前选择主动行动",
        "result": "本阶段形成一次不可逆的现实收益和对手损失",
        "later_consequence": "这一结果在后续阶段继续改变人物选择和权利格局",
    } for i in range(1, 16)]
    failures = _validate_global_long_arcs({"character_long_arcs": arcs, "causal_spine": causal})
    assert any("黛安娜·罗文" in failure and "不得改名" in failure for failure in failures)
    assert any("巴里·布鲁姆" in failure and "不得改名" in failure for failure in failures)


def test_outline_aware_compiler_rejects_nonexistent_causal_and_foreshadow_ids() -> None:
    events, cards = _compiled_event_and_cards()
    events[0]["causal_spine_ids"] = ["CS99"]
    events[0]["foreshadow_ids"] = ["FS99"]
    for card in cards:
        card["source_event_sha256"] = canonical_sha256(events[0])
    outline = {
        "causal_spine": [{"spine_id": f"CS{i:02d}", "phase_range": "P01→P10"} for i in range(1, 16)],
        "foreshadow_ledger": [{
            "thread_id": f"FS{i:02d}", "plant_phase": "P01",
            "development_phases": ["P02"], "payoff_phase": "P03",
        } for i in range(1, 13)],
    }
    failures = validate_full_plan(
        events, cards, allow_partial=True, global_outline=outline,
    )["failures"]
    assert any("不存在的CS99" in failure for failure in failures)
    assert any("不存在的FS99" in failure for failure in failures)


def test_event_ids_cannot_escape_macro_locked_causal_and_foreshadow_sets() -> None:
    events, _ = _compiled_event_and_cards()
    template = events[0]
    batch = []
    for index in range(5):
        event = json.loads(json.dumps(template, ensure_ascii=False))
        event["cluster_id"] = f"EC{index + 1:03d}"
        event["chapter_span"] = [index * 2 + 1, index * 2 + 2]
        event["causal_spine_ids"] = ["CS99"]
        event["foreshadow_ids"] = ["FS99"]
        event["two_chapter_structure"] = []
        batch.append(event)
    source_macro = {
        "causal_links_used": ["CS01"],
        "foreshadows_planted_or_advanced": ["FS01在本组种下"],
    }
    failures = _validate_events(
        {"event_clusters": batch}, 1, source_macro=source_macro,
    )
    assert any("实际越界['CS99']" in failure for failure in failures)
    assert any("实际越界['FS99']" in failure for failure in failures)


def test_planner_falls_back_to_groq_when_qwen_reports_quota_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "bert_excitation_train.scripts.v2.generate_pop_king_500_qwen._GROQ_VISIBLE_MODELS", None
    )
    monkeypatch.setattr(
        "bert_excitation_train.scripts.v2.generate_pop_king_500_qwen.list_openai_compatible_models_via_curl",
        lambda **kwargs: ["qwen/qwen3.6-27b"],
    )
    monkeypatch.setattr(
        "bert_excitation_train.scripts.v2.generate_pop_king_500_qwen.API_Key_QW", "qwen-test-key"
    )
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    monkeypatch.delenv("PLANNER_PROVIDER", raising=False)
    monkeypatch.setattr(
        "bert_excitation_train.scripts.v2.generate_pop_king_500_qwen.dashscope.Generation.call",
        lambda **kwargs: {"code": "AllocationQuota.FreeTierExhausted", "message": "quota"},
    )
    monkeypatch.setattr(
        "bert_excitation_train.scripts.v2.generate_pop_king_500_qwen.call_openai_compatible_via_curl",
        lambda *args, **kwargs: {
            "choices": [{"message": {"content": '{"ok":true}'}}], "usage": {},
        },
    )
    raw, meta = _call_qwen(
        [{"role": "user", "content": "test"}], model="qwen-plus", temperature=0.7,
    )
    assert raw == '{"ok":true}'
    assert meta["provider"] == "groq"
    assert "AllocationQuota.FreeTierExhausted" in meta["fallback_from_qwen"]


def test_groq_planner_falls_back_when_requested_model_is_forbidden(monkeypatch) -> None:
    monkeypatch.setattr(
        "bert_excitation_train.scripts.v2.generate_pop_king_500_qwen._GROQ_VISIBLE_MODELS", None
    )
    monkeypatch.setattr(
        "bert_excitation_train.scripts.v2.generate_pop_king_500_qwen.API_Key_QW", ""
    )
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    monkeypatch.setenv("PLANNER_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_PLANNER_MODEL", "restricted-model")
    monkeypatch.setenv("GROQ_PLANNER_FALLBACK_MODELS", "qwen/qwen3.6-27b")
    monkeypatch.setattr(
        "bert_excitation_train.scripts.v2.generate_pop_king_500_qwen.list_openai_compatible_models_via_curl",
        lambda **kwargs: ["restricted-model", "qwen/qwen3.6-27b"],
    )
    calls = []

    def fake_call(*args, **kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == "restricted-model":
            raise RuntimeError('OpenAI-compatible curl transport failed (22): {"error":{"message":"Forbidden"}}')
        return {"choices": [{"message": {"content": '{"ok":true}'}}], "usage": {}}

    monkeypatch.setattr(
        "bert_excitation_train.scripts.v2.generate_pop_king_500_qwen.call_openai_compatible_via_curl",
        fake_call,
    )
    raw, meta = _call_qwen(
        [{"role": "user", "content": "test"}], model="qwen-plus", temperature=0.7,
    )
    assert raw == '{"ok":true}'
    assert calls == ["restricted-model", "qwen/qwen3.6-27b"]
    assert meta["model"] == "qwen/qwen3.6-27b"
    assert meta["forbidden_model_fallbacks"] == ["restricted-model"]


def test_groq_planner_falls_back_when_request_exceeds_model_tpm(monkeypatch) -> None:
    monkeypatch.setattr(
        "bert_excitation_train.scripts.v2.generate_pop_king_500_qwen._GROQ_VISIBLE_MODELS", None
    )
    monkeypatch.setattr(
        "bert_excitation_train.scripts.v2.generate_pop_king_500_qwen.API_Key_QW", ""
    )
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    monkeypatch.setenv("PLANNER_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_PLANNER_MODEL", "small-tpm-model")
    monkeypatch.setenv("GROQ_PLANNER_FALLBACK_MODELS", "large-tpm-model")
    monkeypatch.setattr(
        "bert_excitation_train.scripts.v2.generate_pop_king_500_qwen.list_openai_compatible_models_via_curl",
        lambda **kwargs: ["small-tpm-model", "large-tpm-model"],
    )
    calls = []

    def fake_call(*args, **kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == "small-tpm-model":
            raise RuntimeError(
                'OpenAI-compatible curl transport failed (22): '
                '{"error":{"message":"Request too large for model `small-tpm-model` '
                'on tokens per minute (TPM)","code":"rate_limit_exceeded"}}'
            )
        return {"choices": [{"message": {"content": '{"ok":true}'}}], "usage": {}}

    monkeypatch.setattr(
        "bert_excitation_train.scripts.v2.generate_pop_king_500_qwen.call_openai_compatible_via_curl",
        fake_call,
    )
    raw, meta = _call_qwen(
        [{"role": "user", "content": "test"}], model="qwen-plus", temperature=0.7,
    )
    assert raw == '{"ok":true}'
    assert calls == ["small-tpm-model", "large-tpm-model"]
    assert meta["model"] == "large-tpm-model"
    assert meta["capacity_model_fallbacks"] == ["small-tpm-model"]


def test_chapter_card_is_losslessly_compiled_from_event_milestone() -> None:
    event = {
        "cluster_id": "EC002", "chapter_span": [3, 4], "name": "提前截住假合同",
        "timeline_years": "1970", "main_opponent": "维克多·杰森",
        "main_characters": ["麦珂·杰森", "玛莎·杰森"], "canonical_cast": [],
        "prev_life_tragedy": "上一世假合同夺走版权",
        "info_gap_from_prev_life": "记得签字会在周五下午发生",
        "preemptive_avoidance": "提前让母亲改掉会场",
        "bait_and_evidence": "保留一份无害副本诱使对方露馅",
        "villain_loss": "维克多永久失去代签权限",
        "protagonist_gain": "麦珂保住版权",
        "relationship_change": "玛莎独立决定拒签",
        "cluster_outcome": "假合同失效",
        "state_transitions": [{
            "domain": "rights", "entity_id": "RIGHT_COPYRIGHT",
            "state_key": "代理签字权", "from": "active", "to": "revoked",
            "irreversible": True, "evidence": "玛莎当场拒签",
        }],
    }
    milestones = []
    for chapter_id in (3, 4):
        milestones.append({
            "chapter_id": chapter_id, "timeline_start": "1970-05-01",
            "timeline_end": "1970-05-01", "scene": "唱片公司会客室",
            "scenes": [{"sequence": 1, "location": "唱片公司会客室", "is_primary": True}],
            "artifact_creates": [], "artifact_refs": [],
            "chapter_goal": "截住假合同", "chapter_title": f"第{chapter_id}章标题",
            "participants": ["麦珂·杰森", "玛莎·杰森"],
            "opening_conflict": "维克多突然催促玛莎立刻签字",
            "info_gap_use": "麦珂记得上一世周五下午的催签原话",
            "opponent_reaction": "维克多抢着解释，反而说漏准备代签",
            "action_sequence": ["发现催签", "改变座次", "摆出副本", "迫使对方表态"],
            "visible_payoff": "保住原件" if chapter_id == 3 else "永久撤掉代签权",
            "ending": "对方去找后手" if chapter_id == 3 else "新危机露头",
            "must_include": ["催签", "副本", "玛莎独立选择"],
            "must_not_include": ["公开重生", "万能法律知识"],
            "detailed_synopsis": "麦珂利用上一世记住的周五催签原话，先让玛莎独立决定换座并保管原件。维克多为抢功当众催签，误把代签安排说漏，麦珂顺势摆出无害副本，让在场人亲眼确认他的真实意图。玛莎没有等待儿子命令，而是当场拒绝授权。这个章节只完成眼前一段行动，并在可见结果后留下下一步压力，全部动作都来自同一事件里程碑。",
        })
    event["two_chapter_structure"] = milestones
    macro = {"story_block_id": "B001", "macro_group_id": "MG001"}
    first_input = _compile_chapter_input_from_milestone(event, milestones[0])
    second_input = _compile_chapter_input_from_milestone(event, milestones[1])
    first_card = _chapter_card(first_input, event, macro)
    second_card = _chapter_card(second_input, event, macro)
    assert first_card["exact_action_sequence"] == milestones[0]["action_sequence"]
    assert first_card["scenes"] == milestones[0]["scenes"]
    assert first_card["state_transitions"] == []
    assert second_card["state_transitions"] == event["state_transitions"]
    assert second_card["source_event_sha256"] == canonical_sha256(event)
    assert second_card["source_milestone_sha256"] == canonical_sha256(milestones[1])
    assert second_card["compiled_by"] == CHAPTER_CARD_COMPILER_VERSION


def test_fake_death_validator_allows_constraints_but_rejects_plot_use() -> None:
    assert _fake_death_failures("终局严禁假死，麦珂本人始终清醒存活。", "x") == []
    failures = _fake_death_failures("麦珂安排假死骗过对手，之后复苏。", "x")
    assert any("假死" in failure for failure in failures)


def test_changed_outline_recoverably_isolates_stale_downstream(tmp_path: Path) -> None:
    old_hash = "a" * 64
    new_hash = "b" * 64
    (tmp_path / "qwen_generation_manifest.json").write_text(
        json.dumps({"outline_sha256": old_hash}), encoding="utf-8"
    )
    (tmp_path / "coarse_story_blocks_v5_qwen_500.json").write_text("[]", encoding="utf-8")
    (tmp_path / "body_generation").mkdir()
    (tmp_path / "body_generation" / "chapter_001.txt").write_text("旧正文", encoding="utf-8")
    (tmp_path / "qwen_batches").mkdir()
    (tmp_path / "qwen_batches" / "GLOBAL_narrative.json").write_text("{}", encoding="utf-8")

    archive = _archive_stale_downstream_if_outline_changed(tmp_path, new_hash)

    assert archive is not None
    assert not (tmp_path / "coarse_story_blocks_v5_qwen_500.json").exists()
    assert not (tmp_path / "body_generation").exists()
    assert (archive / "coarse_story_blocks_v5_qwen_500.json").is_file()
    assert (archive / "body_generation" / "chapter_001.txt").is_file()
    assert (tmp_path / "qwen_batches" / "GLOBAL_narrative.json").is_file()
    archive_manifest = json.loads(
        (archive / "archive_manifest.json").read_text(encoding="utf-8")
    )
    assert archive_manifest["previous_outline_sha256"] == old_hash
    assert archive_manifest["replacement_outline_sha256"] == new_hash
    assert archive_manifest["recoverable"] is True


def test_unchanged_outline_does_not_archive_current_downstream(tmp_path: Path) -> None:
    outline_hash = "c" * 64
    (tmp_path / "qwen_generation_manifest.json").write_text(
        json.dumps({"outline_sha256": outline_hash}), encoding="utf-8"
    )
    current = tmp_path / "coarse_story_blocks_v5_qwen_500.json"
    current.write_text("[]", encoding="utf-8")

    archive = _archive_stale_downstream_if_outline_changed(tmp_path, outline_hash)

    assert archive is None
    assert current.is_file()


def test_semantic_preflight_rejects_event_type_label_laundering() -> None:
    event = {
        "cluster_id": "EC004",
        "event_type": "fan_public_welfare",
        "solution_type": "relationship_choice",
        "fictional_obstacle": "档案员用替换胶片盒遮盖原始胶片",
        "preemptive_avoidance": "玛莎检查齿孔、墨迹与印章",
        "villain_loss": "档案员失去胶片保管权限",
        "protagonist_gain": "麦珂获得原始胶片",
        "cluster_outcome": "胶片证据链完成",
        "two_chapter_structure": [{"scene": "档案室"}, {"scene": "档案室"}],
    }
    failures = event_type_semantic_failures(event)
    assert any("event_type=fan_public_welfare与实际剧情不符" in item for item in failures)
    assert any("程序/取证事件" in item for item in failures)


def test_semantic_preflight_rejects_reused_info_gap_and_missing_loss_effect() -> None:
    direction = "麦珂提前要求现场清唱并保住原声，对手失去剪辑权"
    common = {
        "opposition_type": "villain", "event_type": "performance",
        "solution_type": "performance_proof", "death_chain_role": "advance",
        "fictional_obstacle": "对手在试唱时准备切掉主角原声",
        "preemptive_avoidance": "麦珂提前要求现场清唱并由成年人监督设备",
        "villain_loss": "对手失去剪辑权", "protagonist_gain": "麦珂保住原声",
        "cluster_outcome": "原声被认可",
        "two_chapter_structure": [{"scene": "后台"}, {"scene": "舞台"}],
        "source_event_direction": direction,
        "source_event_direction_sha256": canonical_sha256(direction),
        "state_transitions": [{
            "domain": "rights", "entity_id": "CHAR_A", "state_key": "voice_right",
            "from": "none", "to": "protected", "irreversible": True,
            "evidence": "制作人当场取消替唱", "effect_type": "protagonist_gain",
        }],
        "info_gap_from_prev_life": "记得对手会在下午三点切掉主轨原声",
    }
    prior = {**common, "cluster_id": "EC001", "chapter_span": [1, 2]}
    event = {**common, "cluster_id": "EC002", "chapter_span": [3, 4]}
    _, _, failures = validate_event_batch([event], prior_events=[prior])
    assert any("复用了同一段前世信息差" in item for item in failures)
    assert any("没有状态转移结算反派的现实损失" in item for item in failures)


def test_continuity_ledger_accumulates_old_irreversible_facts() -> None:
    previous = {
        "rights_and_assets": ["编曲室权限已获得"],
        "character_states": {"麦珂": "十一岁"},
    }
    update = {
        "rights_and_assets": ["母带控制权已获得"],
        "character_states": {"玛莎": "主动保护者"},
    }
    merged = _merge_continuity_ledger(previous, update)
    assert merged["rights_and_assets"] == ["编曲室权限已获得", "母带控制权已获得"]
    assert merged["character_states"] == {"麦珂": "十一岁", "玛莎": "主动保护者"}


def test_changed_block_bundle_archives_detail_and_prose(tmp_path: Path) -> None:
    (tmp_path / "qwen_generation_manifest.json").write_text(
        json.dumps({"block_plan_bundle_sha256": "old"}), encoding="utf-8"
    )
    (tmp_path / "event_clusters_v2.json").write_text("[]", encoding="utf-8")
    (tmp_path / "chapters").mkdir()
    (tmp_path / "chapters" / "chapter_001.txt").write_text("旧正文", encoding="utf-8")
    archive = _archive_stale_detail_plan_if_blocks_changed(
        tmp_path, [{"block_id": "B001"}], [{"macro_group_id": "MG001"}],
    )
    assert archive is not None
    assert not (tmp_path / "event_clusters_v2.json").exists()
    assert not (tmp_path / "chapters").exists()
    assert (archive / "event_clusters_v2.json").is_file()
    assert (archive / "chapters" / "chapter_001.txt").is_file()

"""Semantic preflight and immutable fingerprints for the pop-king plan.

The Qwen planner is intentionally creative, but its output is not authoritative
until this module has compiled it.  The compiler owns the facts that prose and
Neo4j must agree on: chronology, two-chapter boundaries, character identity,
canonical state transitions and exact input fingerprints.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable


CURRENT_TIMELINE_ROLES = {
    "rebirth_confirmation",
    "two_chapter_setup_and_win",
    "two_chapter_payoff",
}
OPPOSITION_TYPES = {
    "villain", "ally_resistance", "institutional", "technical", "family", "internal",
}
EVENT_TYPES = {
    "performance", "creation", "contract_rights", "finance_business", "family_relationship",
    "media_reputation", "health_safety", "fan_public_welfare", "romance", "legal_procedure",
}
SOLUTION_TYPES = {
    "performance_proof", "creative_breakthrough", "public_confrontation", "negotiation",
    "market_result", "relationship_choice", "safety_preemption", "media_counter",
    "financial_counter", "legal_evidence", "teamwork", "strategic_withdrawal",
}
STATE_DOMAINS = {
    "character", "relationship", "rights", "asset", "job", "health", "enemy_capability",
    "foreshadow", "reputation", "location", "cost",
}
STATE_EFFECT_TYPES = {
    "villain_loss", "protagonist_gain", "relationship_change", "world_state",
    "protagonist_cost", "cost_resolution",
}

# Reject enum-label laundering: a file-room evidence scene cannot call itself
# fan/public-welfare merely to satisfy a diversity counter.
EVENT_TYPE_ANCHORS: dict[str, tuple[str, ...]] = {
    "performance": ("演出", "登台", "舞台", "试唱", "清唱", "排练", "观众", "评委", "唱完"),
    "creation": ("创作", "作曲", "编曲", "旋律", "歌词", "歌曲", "和声", "即兴改编", "专辑"),
    "contract_rights": ("合同", "条款", "版权", "授权", "签约", "所有权", "使用权", "控制权"),
    "finance_business": ("账户", "分成", "收入", "预算", "票房", "销量", "市场", "投资", "资金"),
    "family_relationship": ("母亲", "父亲", "玛莎", "家庭", "亲子", "家人", "监护人", "母子"),
    "media_reputation": ("媒体", "记者", "报纸", "电台", "舆论", "名誉", "报道", "采访"),
    "health_safety": ("健康", "受伤", "药物", "注射", "心跳", "死亡", "医院", "失声", "安全", "危险", "事故", "设备故障"),
    "fan_public_welfare": ("粉丝", "歌迷", "听众", "观众", "公益", "慈善", "社区", "公众", "募捐", "救助"),
    "romance": ("恋人", "恋爱", "约会", "伴侣", "爱意", "感情关系"),
    "legal_procedure": ("公证", "法院", "律师", "听证", "诉讼", "备案", "骑缝章", "法律文书"),
}
SOLUTION_TYPE_ANCHORS: dict[str, tuple[str, ...]] = {
    "performance_proof": ("演出", "登台", "上台", "试唱", "清唱", "唱完", "表演", "评委", "观众"),
    "creative_breakthrough": ("创作", "原创", "作曲", "编曲", "旋律", "歌曲", "歌词", "和声", "即兴", "改编"),
    "public_confrontation": ("当众", "当场", "公开", "现场质问", "要求勘误", "对峙", "发布会", "全场"),
    "negotiation": ("谈判", "协商", "交换条件", "拒签", "补签", "签字", "改签", "让步", "承诺", "附录"),
    "market_result": ("销量", "票房", "点播", "订单", "市场", "榜单", "售罄", "反响", "支持", "投票", "认可"),
    "relationship_choice": ("选择站在", "主动保护", "拒绝服从", "母亲决定", "家人决定", "玛莎", "撕毁", "拒绝签", "关系"),
    "safety_preemption": ("提前", "预判", "避开", "安全", "危险", "事故", "检查设备", "报告故障", "撤离"),
    "media_counter": ("媒体", "记者", "报纸", "电台", "舆论", "报道", "采访"),
    "financial_counter": ("账户", "冻结", "分成", "资金", "预算", "收入", "付款"),
    "legal_evidence": ("公证", "法院", "律师", "证据", "备案", "法律文书", "听证"),
    "teamwork": ("合作", "团队", "共同", "联手", "分工", "伙伴"),
    "strategic_withdrawal": ("退出", "撤回", "暂缓", "暂停", "终止", "不参加", "拒绝进入", "离场"),
}
PROCEDURAL_STORY_ANCHORS = (
    "公证", "合同", "条款", "备案", "印章", "骑缝章", "钢印", "铅封", "登记簿",
    "声纹", "波形", "齿孔", "纸纤维", "墨迹", "编号", "档案", "鉴定", "证据链",
)
EARLY_CHILD_FAKE_PRECISION = (
    "毫秒", "微秒", "微观匹配", "误差小于", "频率完全", "频谱完全", "严丝合缝",
    "生物指标", "声纹基线", "声纹模型", "纤维层", "氧化程度", "压力特征",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_json_sha256(path: Path) -> str:
    return canonical_sha256(json.loads(Path(path).read_text(encoding="utf-8")))


def plan_fingerprints(
    *, outline: dict[str, Any], events: list[dict[str, Any]], cards: list[dict[str, Any]],
    style_samples: list[dict[str, Any]],
) -> dict[str, str]:
    parts = {
        "outline_sha256": canonical_sha256(outline),
        "event_clusters_sha256": canonical_sha256(events),
        "chapter_cards_sha256": canonical_sha256(cards),
        "style_samples_sha256": canonical_sha256(style_samples),
    }
    parts["plan_bundle_sha256"] = canonical_sha256(parts)
    return parts


def body_prefix_fingerprints(
    *, outline: dict[str, Any], events: list[dict[str, Any]], cards: list[dict[str, Any]],
    style_samples: list[dict[str, Any]], through_cluster: int,
) -> dict[str, Any]:
    """Fingerprint only facts that can causally precede one prose cluster.

    Appending later event clusters must not invalidate already accepted prose,
    while changing the outline, style contract, or any plan fact through the
    current cluster must.  The explicit prefix length prevents the same digest
    from being interpreted as a different planning horizon.
    """
    if through_cluster < 1 or through_cluster > len(events):
        raise ValueError("through_cluster must identify an existing event prefix")
    through_chapter = through_cluster * 2
    event_prefix = events[:through_cluster]
    card_prefix = [
        card for card in cards if int(card.get("chapter_id") or 0) <= through_chapter
    ]
    if len(card_prefix) != through_chapter:
        raise ValueError("chapter cards do not completely cover the requested event prefix")
    parts: dict[str, Any] = {
        "fingerprint_scope": "causal_plan_prefix",
        "through_cluster": through_cluster,
        "through_chapter": through_chapter,
        "outline_sha256": canonical_sha256(outline),
        "event_prefix_sha256": canonical_sha256(event_prefix),
        "chapter_card_prefix_sha256": canonical_sha256(card_prefix),
        "style_samples_sha256": canonical_sha256(style_samples),
    }
    parts["plan_prefix_bundle_sha256"] = canonical_sha256(parts)
    return parts


def event_fingerprint(event: dict[str, Any]) -> str:
    return canonical_sha256(event)


def card_fingerprint(card: dict[str, Any]) -> str:
    return canonical_sha256(card)


def timeline_years(value: Any) -> list[int]:
    return [int(item) for item in re.findall(r"(?:19|20)\d{2}", str(value or ""))]


def timeline_bounds(value: Any) -> tuple[int | None, int | None]:
    years = timeline_years(value)
    return (min(years), max(years)) if years else (None, None)


def timeline_point(value: Any, *, end: bool = False) -> date | None:
    """Compile YYYY, YYYY-MM or YYYY-MM-DD into a comparable calendar point."""
    text = str(value or "").strip()
    match = re.fullmatch(r"((?:19|20)\d{2})(?:-(\d{2})(?:-(\d{2}))?)?", text)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2) or (12 if end else 1))
    if match.group(3):
        day = int(match.group(3))
    elif end:
        next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
        day = (next_month - date.resolution).day
    else:
        day = 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def artifact_id(value: Any) -> str:
    return str(value or "").strip()


def character_id_for_name(name: str) -> str:
    normalized = re.sub(r"\s+", "", str(name or "").strip()).casefold()
    return "CHAR_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12].upper()


def state_key(transition: dict[str, Any]) -> str:
    return ":".join(
        str(transition.get(field) or "").strip()
        for field in ("domain", "entity_id", "state_key")
    )


def normalize_transition(transition: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain": str(transition.get("domain") or "").strip(),
        "entity_id": str(transition.get("entity_id") or "").strip(),
        "state_key": str(transition.get("state_key") or "").strip(),
        "from": str(transition.get("from") or "").strip(),
        "to": str(transition.get("to") or "").strip(),
        "irreversible": bool(transition.get("irreversible")),
        "evidence": str(transition.get("evidence") or "").strip(),
        "effect_type": str(transition.get("effect_type") or "").strip(),
    }


def apply_state_transitions(
    transitions: Iterable[dict[str, Any]],
    state: dict[str, str] | None = None,
    irreversible: set[str] | None = None,
) -> tuple[dict[str, str], set[str], list[str]]:
    current = dict(state or {})
    locked = set(irreversible or set())
    failures: list[str] = []
    for raw in transitions:
        if not isinstance(raw, dict):
            failures.append("state_transition必须为对象")
            continue
        item = normalize_transition(raw)
        key = state_key(item)
        if item["domain"] not in STATE_DOMAINS:
            failures.append(f"{key or 'unknown'}使用未知state domain：{item['domain']}")
        if not item["entity_id"] or not item["state_key"] or not item["to"]:
            failures.append("state_transition缺少entity_id/state_key/to")
            continue
        old = current.get(key)
        declared_from = item["from"]
        if key in locked and old != item["to"]:
            failures.append(f"不可逆状态{key}已锁定为{old}，不能再次改为{item['to']}")
            continue
        if old is not None and declared_from not in (old, "current"):
            failures.append(f"状态{key}当前为{old}，转移却声明from={declared_from or '<空>'}")
        if old == item["to"]:
            failures.append(f"状态{key}重复写入同一结果{item['to']}")
        current[key] = item["to"]
        if item["irreversible"]:
            locked.add(key)
    return current, locked, failures


def _ngrams(text: str, size: int = 2) -> set[str]:
    cleaned = re.sub(r"[^\u3400-\u9fffA-Za-z0-9]", "", text)
    return {cleaned[i:i + size] for i in range(max(0, len(cleaned) - size + 1))}


def semantic_similarity(left: Any, right: Any) -> float:
    a, b = _ngrams(canonical_json(left)), _ngrams(canonical_json(right))
    return len(a & b) / len(a | b) if a and b else 0.0


def text_similarity(left: Any, right: Any) -> float:
    """Order-aware similarity used for repeated memories and phrasing."""
    def clean(value: Any) -> str:
        return re.sub(r"[^\u3400-\u9fffA-Za-z0-9]", "", str(value or ""))

    a, b = clean(left), clean(right)
    return SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0


def event_type_semantic_failures(event: dict[str, Any]) -> list[str]:
    """Reject enum-label laundering and procedural plots wearing another label."""
    eid = str(event.get("cluster_id") or "<unknown>")
    event_type = str(event.get("event_type") or "")
    story_text = canonical_json({
        key: event.get(key)
        for key in (
            "direction", "fictional_obstacle", "preemptive_avoidance",
            "villain_loss", "protagonist_gain", "cluster_outcome",
            "two_chapter_structure",
        )
    })
    failures: list[str] = []
    procedural_markers = ("档案", "证据", "胶片", "登记", "签名", "复制", "原始")
    if event_type in {"fan_public_welfare", "public_welfare"} and sum(
        marker in story_text for marker in procedural_markers
    ) >= 3:
        failures.append(f"{eid}.event_type={event_type}与实际剧情不符：程序/取证事件")
    # event_type and solution_type are inherited navigation labels.  Detailed
    # scenes may mix creation, performance, family and evidence work, so keyword
    # counts must not force a creative rewrite merely to satisfy taxonomy.
    # Procedural actions can support family, reputation, performance and other
    # story events without redefining their dramatic center.  Do not reject a
    # usable event merely to police template-diversity labels.
    return failures


def source_direction_recall(direction: Any, event: dict[str, Any]) -> float:
    """How much of the upper-level WHAT survives detailed event expansion."""
    source = re.sub(r"[^\u3400-\u9fffA-Za-z0-9]", "", str(direction or ""))
    target = canonical_json(_event_story_shape(event))
    grams = {source[index:index + 2] for index in range(max(0, len(source) - 1))}
    return len({gram for gram in grams if gram in target}) / len(grams) if grams else 0.0


def _event_story_shape(event: dict[str, Any]) -> dict[str, Any]:
    return {
        key: event.get(key)
        for key in (
            "fictional_obstacle", "preemptive_avoidance", "bait_and_evidence",
            "villain_loss", "protagonist_gain", "cluster_outcome", "two_chapter_structure",
        )
    }


def validate_event_batch(
    events: list[dict[str, Any]], *, prior_events: list[dict[str, Any]] | None = None,
    prior_state: dict[str, str] | None = None, prior_irreversible: set[str] | None = None,
) -> tuple[dict[str, str], set[str], list[str]]:
    failures: list[str] = []
    state = dict(prior_state or {})
    locked = set(prior_irreversible or set())
    history = list(prior_events or [])
    for event in events:
        eid = str(event.get("cluster_id") or "<unknown>")
        opposition = str(event.get("opposition_type") or "")
        event_type = str(event.get("event_type") or "")
        solution_type = str(event.get("solution_type") or "")
        if opposition not in OPPOSITION_TYPES:
            failures.append(f"{eid}.opposition_type非法或缺失")
        if event_type not in EVENT_TYPES:
            failures.append(f"{eid}.event_type非法或缺失")
        if solution_type not in SOLUTION_TYPES:
            failures.append(f"{eid}.solution_type非法或缺失")
        failures.extend(event_type_semantic_failures(event))
        if opposition != "villain" and any(
            token in str(event.get("comic_villain_behavior") or "")
            for token in ("坏人", "反派", "自曝", "丑态")
        ):
            failures.append(f"{eid}不是villain冲突，不得强套反派滑稽模板")
        transitions = event.get("state_transitions")
        if not isinstance(transitions, list) or not transitions:
            failures.append(f"{eid}.state_transitions至少1项")
        else:
            for transition in transitions:
                if isinstance(transition, dict) and str(transition.get("effect_type") or "") not in STATE_EFFECT_TYPES:
                    failures.append(
                        f"{eid}.state_transition缺少合法effect_type，必须说明其结算类型"
                    )
            state, locked, transition_failures = apply_state_transitions(transitions, state, locked)
            failures.extend(f"{eid} {item}" for item in transition_failures)
            effects = {
                str(item.get("effect_type") or "")
                for item in transitions if isinstance(item, dict)
            }
            if opposition == "villain" and "villain_loss" not in effects:
                failures.append(f"{eid}为villain冲突，但没有状态转移结算反派的现实损失")
            if not effects.intersection({"protagonist_gain", "relationship_change"}):
                failures.append(f"{eid}没有状态转移结算主角收益或人物关系变化")
        current_info_gap = str(event.get("info_gap_from_prev_life") or "")
        for prior in history[-10:]:
            prior_info_gap = str(prior.get("info_gap_from_prev_life") or "")
            info_score = text_similarity(current_info_gap, prior_info_gap)
            if current_info_gap and prior_info_gap and info_score >= 0.68:
                failures.append(
                    f"{eid}与{prior.get('cluster_id')}复用了同一段前世信息差（相似度{info_score:.2f}）"
                )
        source_direction = event.get("source_event_direction")
        source_direction_sha = str(event.get("source_event_direction_sha256") or "")
        if not source_direction or source_direction_sha != canonical_sha256(source_direction):
            failures.append(f"{eid}未绑定上层five_event_direction的原文与哈希")
        else:
            recall = source_direction_recall(source_direction, event)
            # Detailed events may realize a terse parent direction with much
            # richer scene language, which makes token recall artificially
            # low.  Keep a meaningful binding floor, while leaving causal,
            # state-transition, chronology and irreversible-loss validators
            # as the real continuity safeguards.
            if recall < 0.18:
                failures.append(
                    f"{eid}只保留上层事件方向{recall:.2%}，下层疑似重新编剧而非细化"
                )
        span = event.get("chapter_span") or [0, 0]
        try:
            end_chapter = int(span[-1])
        except (TypeError, ValueError, IndexError):
            end_chapter = 0
        if 0 < end_chapter <= 90:
            protagonist_actions = canonical_json({
                key: event.get(key)
                for key in (
                    "info_gap_from_prev_life", "preemptive_avoidance",
                    "bait_and_evidence", "two_chapter_structure",
                )
            })
            precision_hits = sorted({
                marker for marker in EARLY_CHILD_FAKE_PRECISION
                if re.search(
                    rf"麦珂(?:亲自|独自|当场|立即|准确|精确)*"
                    rf"(?:测量|计算|鉴定|识别|检测|推算).{{0,16}}{re.escape(marker)}",
                    protagonist_actions,
                )
            })
            decimal_measurements = re.findall(
                r"\d+(?:\.\d+)?\s*(?:Hz|赫兹|毫米|厘米|微米|℃|摄氏度|度)", protagonist_actions,
                flags=re.I,
            )
            protagonist_numeric_measurement = bool(re.search(
                r"麦珂(?:亲自|独自|当场|立即|准确|精确)*(?:测量|计算|鉴定|检测|推算|分析|指出).{0,24}"
                r"\d+(?:\.\d+)?\s*(?:Hz|赫兹|毫米|厘米|微米|℃|摄氏度|度)",
                protagonist_actions,
                flags=re.I,
            ))
            if precision_hits or (len(decimal_measurements) >= 2 and protagonist_numeric_measurement):
                details = precision_hits + decimal_measurements[:3]
                failures.append(
                    f"{eid}把未成年重生者写成假精确的全知技术神童：{'、'.join(details)}；"
                    "应让他凭前世日期/原话/选择抢先，再由有资质成年人完成专业动作"
                )
        current_shape = _event_story_shape(event)
        for prior in history[-10:]:
            score = semantic_similarity(current_shape, _event_story_shape(prior))
            if score >= 0.76:
                failures.append(
                    f"{eid}与{prior.get('cluster_id')}剧情语义相似度{score:.2f}，疑似换皮重演"
                )
        history.append(event)
    if len(events) == 5:
        # Event/solution category quotas were style-diversity heuristics, not
        # continuity guarantees.  They must not block a causally sound rebirth
        # revenge batch merely because several conflicts need evidence or the
        # same effective kind of counterattack.
        death_chain_advances = [
            item for item in events
            if str(item.get("death_chain_role") or "") in {"advance", "pressure", "reveal"}
        ]
        if not death_chain_advances:
            failures.append("每十章至少一个事件必须明确推进2009死亡—保险—版权—医疗控制主线")
    return state, locked, failures


def next_hook_repeat_failures(events: list[dict[str, Any]]) -> list[str]:
    """Reject exact or near-duplicate next hooks in a rolling five-EC window."""
    failures: list[str] = []
    recent: list[tuple[str, str]] = []
    for event in events:
        eid = str(event.get("cluster_id") or "")
        hook = re.sub(r"\s+", "", str(event.get("next_event_hook") or ""))
        if hook:
            count = sum(
                1 for _, previous in recent
                if previous == hook or SequenceMatcher(None, previous, hook).ratio() >= 0.82
            )
            if count >= 2:
                failures.append(f"NEXT_HOOK_REPEAT_FATAL {eid}: 连续三次重复next_hook")
            elif count >= 1:
                failures.append(f"NEXT_HOOK_REPEAT_FATAL {eid}: 连续重复next_hook")
            recent.append((eid, hook))
            recent = recent[-5:]
    return failures


def trial_timeline_failures(chapter_dates: dict[int, Any], *, formal_prior_date: Any | None = None) -> list[str]:
    """Check an isolated trial against the last formal chapter as well as itself."""
    failures: list[str] = []
    parsed: dict[int, date] = {}
    for chapter_id, value in sorted(chapter_dates.items()):
        try:
            current = value if isinstance(value, date) else date.fromisoformat(str(value))
        except (TypeError, ValueError):
            failures.append(f"第{chapter_id}章日期非法：{value}")
            continue
        parsed[int(chapter_id)] = current
    if formal_prior_date is not None and parsed:
        try:
            prior = formal_prior_date if isinstance(formal_prior_date, date) else date.fromisoformat(str(formal_prior_date))
            first_id = min(parsed)
            if parsed[first_id] < prior:
                failures.append(f"第{first_id}章早于正式前章日期，时间线倒退")
        except (TypeError, ValueError):
            failures.append(f"正式前章日期非法：{formal_prior_date}")
    previous: tuple[int, date] | None = None
    for chapter_id, current in parsed.items():
        if previous and current < previous[1]:
            failures.append(f"第{chapter_id}章早于第{previous[0]}章，时间线倒退")
        previous = (chapter_id, current)
    return failures


def _trial_specs(plan: dict[str, Any]) -> dict[int, tuple[str, dict[str, Any]]]:
    result: dict[int, tuple[str, dict[str, Any]]] = {}
    for event in plan.get("event_clusters") or []:
        eid = str(event.get("cluster_id") or "")
        for spec in event.get("chapter_specs") or []:
            result[int(spec["chapter_id"])] = (eid, spec)
    return result


def trial_chapter_binding_failures(
    body: str, cluster_id: str, chapter_id: int, plan: dict[str, Any]
) -> list[str]:
    """Validate a trial chapter against its explicit candidate chapter card."""
    specs = _trial_specs(plan)
    expected = specs.get(int(chapter_id))
    failures: list[str] = []
    if not expected:
        return [f"试写章卡缺失：第{chapter_id}章"]
    expected_cluster, spec = expected
    if expected_cluster != str(cluster_id):
        failures.append(f"第{chapter_id}章绑定错误：期望{expected_cluster}，实际{cluster_id}")
    for marker in spec.get("forbidden_progress") or []:
        if str(marker) and str(marker) in body:
            failures.append(f"PLAN_LEAK_FORWARD 第{chapter_id}章提前消费：{marker}")
    return failures


def trial_forward_consumption_failures(
    body: str, cluster_id: str, plan: dict[str, Any]
) -> list[str]:
    """Catch action-level consumption of the next EC, while allowing a hook mention."""
    events = plan.get("event_clusters") or []
    index = next((i for i, event in enumerate(events) if event.get("cluster_id") == cluster_id), -1)
    if index < 0 or index + 1 >= len(events):
        return []
    next_event = events[index + 1]
    next_id = str(next_event.get("cluster_id") or "")
    # These are actions/results, not mere nouns used to foreshadow the next line.
    action_markers = (
        "签订合同", "签署合同", "合同生效", "自动延长", "制作培训手册",
        "公开展示获准", "对外分发获准", "商业授权获准", "合同谈判完成",
    )
    hits = [marker for marker in action_markers if marker in body]
    return [f"PLAN_LEAK_FORWARD 提前消费{next_id}核心动作：{','.join(hits)}"] if hits else []


def validate_trial_cluster_card(cluster: dict[str, Any], cards: list[dict[str, Any]]) -> list[str]:
    """Validate one candidate EC without promoting it into the formal plan."""
    failures: list[str] = []
    span = [int(value) for value in cluster.get("chapter_span") or []]
    if len(span) != 2 or span[1] != span[0] + 1:
        failures.append("候选事件簇必须恰好绑定连续两章")
    if [int(card.get("chapter_id") or 0) for card in cards] != span:
        failures.append("候选章卡章节范围与事件簇不一致")
    required_signature = {
        "conflict_type", "attack_method", "counter_method", "key_artifact",
        "authority", "reward", "relationship_change",
    }
    signature = cluster.get("structure_signature") or {}
    missing = sorted(required_signature - set(signature))
    if missing:
        failures.append("候选事件簇结构签名缺失：" + ",".join(missing))
    dates: dict[int, Any] = {}
    for card in cards:
        chapter_id = int(card.get("chapter_id") or 0)
        dates[chapter_id] = card.get("timeline_start")
        if not timeline_point(card.get("timeline_start")) or not timeline_point(card.get("timeline_end")):
            failures.append(f"第{chapter_id}章缺少合法起止日期")
        if timeline_point(card.get("timeline_end")) and timeline_point(card.get("timeline_start")) and timeline_point(card.get("timeline_end")) < timeline_point(card.get("timeline_start")):
            failures.append(f"第{chapter_id}章结束日期早于开始日期")
        if not card.get("goal") or not card.get("turning_choice"):
            failures.append(f"第{chapter_id}章缺少人物选择或目标")
    failures.extend(trial_timeline_failures(dates))
    if not cluster.get("irreplaceable_progress_point"):
        failures.append("候选事件簇缺少不可替代推进点")
    return failures


def validate_full_plan(
    events: list[dict[str, Any]], cards: list[dict[str, Any]],
    *, allow_partial: bool = False, global_outline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    if not allow_partial and len(events) != 250:
        failures.append(f"事件簇数量必须为250，实际{len(events)}")
    if not allow_partial and len(cards) != 500:
        failures.append(f"章卡数量必须为500，实际{len(cards)}")
    if allow_partial and len(cards) != len(events) * 2:
        failures.append(f"部分规划也必须每事件2章：事件{len(events)}，章卡{len(cards)}")
    event_by_id = {str(event.get("cluster_id") or ""): event for event in events}
    card_by_id = {int(card.get("chapter_id") or 0): card for card in cards}
    state: dict[str, str] = {}
    locked: set[str] = set()
    seen_losses: dict[str, str] = {}
    seen_gains: dict[str, str] = {}
    last_current_year: int | None = None
    last_current_date: date | None = None
    created_artifacts: dict[tuple[str, str], tuple[int, date | None, dict[str, Any]]] = {}
    transition_count = 0
    character_display_by_id: dict[str, str] = {}
    alias_to_ids: dict[str, set[str]] = defaultdict(set)
    causal_refs: dict[str, set[str]] = defaultdict(set)
    foreshadow_refs: dict[str, set[str]] = defaultdict(set)
    causal_by_id: dict[str, dict[str, Any]] = {}
    foreshadow_by_id: dict[str, dict[str, Any]] = {}
    if global_outline is not None:
        causal_by_id = {
            str(item.get("spine_id") or ""): item
            for item in global_outline.get("causal_spine") or [] if isinstance(item, dict)
        }
        foreshadow_by_id = {
            str(item.get("thread_id") or ""): item
            for item in global_outline.get("foreshadow_ledger") or [] if isinstance(item, dict)
        }
        if len(causal_by_id) != 15:
            failures.append(f"全书总纲causal_spine必须有15个唯一ID，实际{len(causal_by_id)}")
        if len(foreshadow_by_id) != 12:
            failures.append(f"全书总纲foreshadow_ledger必须有12个唯一ID，实际{len(foreshadow_by_id)}")
    for index, event in enumerate(events, 1):
        eid = f"EC{index:03d}"
        span = [index * 2 - 1, index * 2]
        event_phase = f"P{((span[0] - 1) // 50) + 1:02d}"
        allowed_outcomes = {
            "clean_win", "small_win", "partial_win", "costly_win", "stalemate",
            "setback_with_gain", "major_win", "decisive_win",
        }
        if str(event.get("outcome_type") or "") not in allowed_outcomes:
            failures.append(f"{eid}.outcome_type缺失或不合法")
        signature = event.get("resolution_signature")
        signature_fields = ("attack_domain", "counter_method", "resolver", "publicity", "hero_gain_type")
        if not isinstance(signature, dict) or any(not str(signature.get(field) or "").strip() for field in signature_fields):
            failures.append(f"{eid}.resolution_signature缺少结构字段")
        if not isinstance(event.get("death_chain_step"), dict):
            failures.append(f"{eid}.death_chain_step缺失")
        flaw = event.get("character_flaw_beat")
        if isinstance(flaw, dict):
            required_flaw = ("trigger", "protagonist_action", "immediate_benefit", "hidden_cost", "who_pushes_back", "future_payoff_cluster")
            missing_flaw = [field for field in required_flaw if not str(flaw.get(field) or "").strip()]
            who = str(flaw.get("who_pushes_back") or "")
            planned_people = set(map(str, event.get("main_characters") or []))
            for milestone in event.get("two_chapter_structure") or []:
                planned_people.update(map(str, milestone.get("participants") or []))
            if missing_flaw or who not in planned_people:
                failures.append(f"FLAW_BEAT_PARTICIPANT_FATAL {eid}: missing={missing_flaw}, who={who}")
        if event.get("cluster_id") != eid or event.get("chapter_span") != span:
            failures.append(f"{eid}编号/范围必须为{span}")
        event_causal_ids = event.get("causal_spine_ids")
        if not isinstance(event_causal_ids, list) or not event_causal_ids:
            failures.append(f"{eid}.causal_spine_ids至少1项")
            event_causal_ids = []
        event_foreshadow_ids = event.get("foreshadow_ids")
        if not isinstance(event_foreshadow_ids, list):
            failures.append(f"{eid}.foreshadow_ids必须为数组")
            event_foreshadow_ids = []
        if len(set(map(str, event_causal_ids))) != len(event_causal_ids):
            failures.append(f"{eid}.causal_spine_ids不得重复")
        if len(set(map(str, event_foreshadow_ids))) != len(event_foreshadow_ids):
            failures.append(f"{eid}.foreshadow_ids不得重复")
        for raw_id in event_causal_ids:
            ref_id = str(raw_id)
            causal_refs[ref_id].add(event_phase)
            if global_outline is not None and ref_id not in causal_by_id:
                failures.append(f"{eid}.causal_spine_ids引用总纲中不存在的{ref_id}")
                continue
            item = causal_by_id.get(ref_id)
            phase_ids = re.findall(r"P\d{2}", str((item or {}).get("phase_range") or ""))
            if len(phase_ids) >= 2 and not (
                int(phase_ids[0][1:]) <= int(event_phase[1:]) <= int(phase_ids[-1][1:])
            ):
                failures.append(
                    f"{eid}在{event_phase}推进{ref_id}，超出总纲范围{phase_ids[0]}→{phase_ids[-1]}"
                )
        for raw_id in event_foreshadow_ids:
            ref_id = str(raw_id)
            foreshadow_refs[ref_id].add(event_phase)
            if global_outline is not None and ref_id not in foreshadow_by_id:
                failures.append(f"{eid}.foreshadow_ids引用总纲中不存在的{ref_id}")
                continue
            item = foreshadow_by_id.get(ref_id) or {}
            allowed_phases = {
                str(item.get("plant_phase") or ""), str(item.get("payoff_phase") or ""),
                *(str(value) for value in item.get("development_phases") or []),
            }
            allowed_phases.discard("")
            if allowed_phases and event_phase not in allowed_phases:
                failures.append(
                    f"{eid}在{event_phase}推进{ref_id}，但总纲只允许{sorted(allowed_phases)}"
                )
        cast = event.get("canonical_cast")
        if not isinstance(cast, list) or not cast:
            failures.append(f"{eid}.canonical_cast至少1项并使用稳定character_id")
            cast = []
        event_character_ids: set[str] = set()
        event_cast_names: set[str] = set()
        for member in cast:
            if not isinstance(member, dict):
                failures.append(f"{eid}.canonical_cast成员必须为对象")
                continue
            cid = str(member.get("character_id") or "")
            display = str(member.get("display_name") or member.get("name") or "").strip()
            if not re.fullmatch(r"CHAR_[A-F0-9]{12}", cid) or not display:
                failures.append(f"{eid}.canonical_cast缺稳定character_id或display_name")
                continue
            previous_display = character_display_by_id.get(cid)
            if previous_display and previous_display != display:
                failures.append(f"{eid}.{cid}的display_name从{previous_display}漂移为{display}")
            character_display_by_id[cid] = display
            event_character_ids.add(cid)
            aliases = member.get("aliases") or []
            if not isinstance(aliases, list) or display not in aliases:
                failures.append(f"{eid}.{cid}.aliases必须包含display_name")
            for alias in aliases if isinstance(aliases, list) else []:
                if str(alias).strip():
                    alias_to_ids[str(alias).strip()].add(cid)
                    event_cast_names.add(str(alias).strip())
            event_cast_names.add(display)
        main_ids = event.get("main_character_ids")
        if not isinstance(main_ids, list) or not main_ids:
            failures.append(f"{eid}.main_character_ids至少1项")
        elif any(str(cid) not in event_character_ids for cid in main_ids):
            failures.append(f"{eid}.main_character_ids含不在canonical_cast中的ID")
        for field in ("main_characters", "main_opponent"):
            values = event.get(field) if field == "main_characters" else [event.get(field)]
            for value in values or []:
                name = str(value or "").strip()
                if name and name not in event_cast_names:
                    failures.append(f"{eid}.{field}未知全名，无法解析到合法character_id：{name}")
        for milestone in event.get("two_chapter_structure") or []:
            for participant in milestone.get("participants") or []:
                name = str(participant or "").strip()
                if name and name not in event_cast_names and not re.search(r"[（(].*[）)]", name):
                    failures.append(f"{eid}.participants未知全名，无法解析到合法character_id：{name}")
        for transition in event.get("state_transitions") or []:
            entity = str(transition.get("entity_id") or "") if isinstance(transition, dict) else ""
            if entity.startswith("CHAR_") and entity not in event_character_ids:
                failures.append(f"{eid}.state_transition人物{entity}不在canonical_cast")
        state, locked, batch_failures = validate_event_batch(
            [event], prior_events=events[max(0, index - 11):index - 1],
            prior_state=state, prior_irreversible=locked,
        )
        failures.extend(batch_failures)
        transition_count += len(event.get("state_transitions") or [])
        for field, seen in (("villain_loss", seen_losses), ("protagonist_gain", seen_gains)):
            value = re.sub(r"\s+", "", str(event.get(field) or ""))
            if value and value in seen:
                failures.append(f"{eid}.{field}与{seen[value]}完全重复")
            elif value:
                seen[value] = eid
        milestones = event.get("two_chapter_structure") or []
        if not isinstance(milestones, list) or len(milestones) != 2:
            failures.append(f"{eid}.two_chapter_structure必须为2项")
            milestones = []
        for offset, cid in enumerate(span):
            card = card_by_id.get(cid)
            if not card or card.get("cluster_id") != eid:
                failures.append(f"第{cid}章缺失或cluster_id不等于{eid}")
                continue
            if offset < len(milestones):
                milestone = milestones[offset]
                if card.get("source_milestone_sha256") != canonical_sha256(milestone):
                    failures.append(f"第{cid}章未忠实绑定{eid}的源milestone")
            if card.get("source_event_sha256") != canonical_sha256(event):
                failures.append(f"第{cid}章未忠实绑定{eid}的完整事件哈希")
            role = str(card.get("chapter_role_v2") or "")
            exact_start = timeline_point(card.get("timeline_start"))
            exact_end = timeline_point(card.get("timeline_end"))
            if exact_start is None or exact_end is None:
                failures.append(f"第{cid}章必须提供合法timeline_start/timeline_end（YYYY、YYYY-MM或YYYY-MM-DD）")
            elif exact_end < exact_start:
                failures.append(f"第{cid}章timeline_end早于timeline_start")
            event_years = timeline_years(event.get("timeline_years"))
            if event_years and exact_start is not None and exact_start.year not in event_years:
                failures.append(
                    f"第{cid}章timeline_start年份{exact_start.year}不属于{eid}.timeline_years={event_years}"
                )
            if role in CURRENT_TIMELINE_ROLES and cid == 2 and exact_end is not None:
                last_current_date = exact_end
            elif role in CURRENT_TIMELINE_ROLES and exact_start is not None:
                if last_current_date is not None and exact_start < last_current_date:
                    failures.append(
                        f"第{cid}章精确时间线从{last_current_date.isoformat()}倒退到{exact_start.isoformat()}"
                    )
                last_current_date = max(last_current_date or exact_start, exact_end or exact_start)
            scenes = card.get("scenes")
            if not isinstance(scenes, list) or not scenes:
                failures.append(f"第{cid}章scenes至少1项，必须显式标注主场景与转场")
            else:
                sequence = [int(scene.get("sequence") or 0) for scene in scenes if isinstance(scene, dict)]
                if sequence != list(range(1, len(scenes) + 1)):
                    failures.append(f"第{cid}章scenes.sequence必须从1连续递增")
                primaries = [scene for scene in scenes if isinstance(scene, dict) and scene.get("is_primary") is True]
                if len(primaries) != 1:
                    failures.append(f"第{cid}章scenes必须恰好1个is_primary=true")
                scene_locations = {
                    str(scene.get("location") or "").strip()
                    for scene in scenes if isinstance(scene, dict)
                }
                card_location = str(card.get("scene_location") or "").strip()
                location_matches = any(
                    card_location == location
                    or bool(re.match(re.escape(location) + r"[，,。；;（(：:]", card_location))
                    for location in scene_locations if location
                )
                if not location_matches:
                    failures.append(f"第{cid}章scene_location不在结构化scenes中")
            refs = card.get("artifact_refs")
            creates = card.get("artifact_creates")
            if not isinstance(refs, list) or not isinstance(creates, list):
                failures.append(f"第{cid}章artifact_refs/artifact_creates必须为数组")
                refs, creates = [], []
            for created in creates:
                aid = artifact_id(created.get("artifact_id") if isinstance(created, dict) else created)
                scope = str(created.get("timeline_scope") or "") if isinstance(created, dict) else ""
                expected_scope = "previous_life" if cid == 1 else "current"
                key = (scope, aid)
                if not aid:
                    failures.append(f"第{cid}章创建了空artifact_id")
                elif scope != expected_scope:
                    failures.append(f"第{cid}章artifact_id={aid}的timeline_scope必须为{expected_scope}")
                elif key in created_artifacts:
                    failures.append(f"第{cid}章重复创建artifact_id={aid}，首次在第{created_artifacts[key][0]}章")
                else:
                    if isinstance(created, dict):
                        required_contract = ("scope", "signers", "granted_permissions", "does_not_grant", "authority_source")
                        missing_contract = [field for field in required_contract if field not in created]
                        if missing_contract:
                            failures.append(f"ARTIFACT_SCOPE_FATAL 第{cid}章{aid}缺少{missing_contract}")
                    created_artifacts[key] = (cid, exact_start, created if isinstance(created, dict) else {})
            for ref in refs:
                aid = artifact_id(ref.get("artifact_id") if isinstance(ref, dict) else ref)
                scope = str(ref.get("timeline_scope") or "") if isinstance(ref, dict) else ""
                expected_scope = "previous_life" if cid == 1 else "current"
                if scope != expected_scope:
                    failures.append(f"第{cid}章artifact_id={aid or '<空>'}不能从{scope or '<空>'}跨到{expected_scope}时间线")
                elif not aid or (scope, aid) not in created_artifacts:
                    failures.append(f"第{cid}章提前引用尚未创建的artifact_id={aid or '<空>'}")
                else:
                    created = created_artifacts[(scope, aid)][2]
                    permission = str(ref.get("required_permission") or "use_as_evidence_within_scope") if isinstance(ref, dict) else "use_as_evidence_within_scope"
                    grants = {str(value) for value in created.get("granted_permissions") or []}
                    denied = {str(value) for value in created.get("does_not_grant") or []}
                    if permission not in grants or permission in denied:
                        failures.append(
                            f"ARTIFACT_SCOPE_FATAL 第{cid}章{aid}请求{permission}，grants={sorted(grants)}"
                        )
            # `timeline_years` is event-level context and EC001 legitimately
            # reads "2009→1969" on both cards. Current-life ordering must use
            # the exact per-chapter timestamps authored in the milestones.
            start_year = exact_start.year if exact_start is not None else None
            end_year = exact_end.year if exact_end is not None else start_year
            if role in CURRENT_TIMELINE_ROLES and cid != 2 and start_year is not None:
                if last_current_year is not None and start_year < last_current_year:
                    failures.append(
                        f"第{cid}章正常时间线从{last_current_year}倒退到{start_year}"
                    )
                last_current_year = max(last_current_year or start_year, end_year or start_year)
            elif role in CURRENT_TIMELINE_ROLES and cid == 2 and start_year is not None:
                last_current_year = end_year or start_year
    for start in range(max(0, len(events) - 9)):
        window = events[start:start + 10]
        if len(window) < 10:
            continue
        signatures: dict[str, list[str]] = defaultdict(list)
        for event in window:
            signature = event.get("resolution_signature") or {}
            signatures[canonical_json(signature)].append(str(event.get("cluster_id") or ""))
        for ids in signatures.values():
            if len(ids) >= 3:
                failures.append(
                    f"RESOLUTION_SIGNATURE_REPEAT_FATAL {window[0].get('cluster_id')}-{window[-1].get('cluster_id')}: {ids}"
                )
    failures.extend(next_hook_repeat_failures(events))
    # Category-count quotas are intentionally not part of the authoritative
    # full-plan gate; causality, chronology, identities and state changes are.
    ambiguous_aliases = {
        alias: sorted(ids) for alias, ids in alias_to_ids.items() if len(ids) > 1
    }
    if ambiguous_aliases:
        failures.append(
            "人物别名跨character_id歧义："
            + "；".join(f"{alias}={ids}" for alias, ids in sorted(ambiguous_aliases.items()))
        )
    if global_outline is not None and not allow_partial:
        missing_causal = sorted(set(causal_by_id) - set(causal_refs))
        if missing_causal:
            failures.append("250事件未覆盖因果主链：" + "、".join(missing_causal))
        for ref_id, item in sorted(foreshadow_by_id.items()):
            referenced_phases = foreshadow_refs.get(ref_id, set())
            plant = str(item.get("plant_phase") or "")
            payoff = str(item.get("payoff_phase") or "")
            if plant not in referenced_phases:
                failures.append(f"{ref_id}未在种植阶段{plant}被详细事件实际种下")
            if payoff not in referenced_phases:
                failures.append(f"{ref_id}未在回收阶段{payoff}被详细事件实际回收")
    warning_patterns = (
        ("SOURCE_DIRECTION_WARNING", re.compile(r"(?:未绑定上层five_event_direction|只保留上层事件方向)")),
        ("FORESHADOW_COVERAGE_WARNING", re.compile(r"FS\d+未在(?:种植|回收)阶段")),
        ("CAUSAL_COVERAGE_WARNING", re.compile(r"250事件未覆盖因果主链")),
        ("SOURCE_ANCHOR_WARNING", re.compile(r"历史锚点.*(?:覆盖|缺少)")),
    )
    issues: list[dict[str, str]] = []
    for message in failures:
        code = next((code for code, pattern in warning_patterns if pattern.search(str(message))), None)
        issues.append({
            "code": code or "PLAN_VALIDATION_FATAL",
            "severity": "WARNING" if code else "FATAL",
            "message": str(message),
        })
    fatal_failures = [item["message"] for item in issues if item["severity"] == "FATAL"]
    warnings = [item for item in issues if item["severity"] == "WARNING"]
    return {
        "passed": not fatal_failures,
        "failures": fatal_failures,
        "warnings": warnings,
        "issues": issues,
        "evidence": {
            "event_clusters": len(events), "chapter_cards": len(cards),
            "state_transition_count": transition_count,
            "final_state_count": len(state), "irreversible_state_count": len(locked),
            "created_artifact_count": len(created_artifacts),
            "stable_character_count": len(character_display_by_id),
            "referenced_causal_spines": len(causal_refs),
            "referenced_foreshadows": len(foreshadow_refs),
        },
    }


def validate_chronology_prefix(cards: list[dict[str, Any]]) -> list[str]:
    """Validate chronology for partial output, allowing only chapter 1→2 rebirth."""
    failures: list[str] = []
    last_current_year: int | None = None
    for card in sorted(cards, key=lambda item: int(item.get("chapter_id") or 0)):
        cid = int(card.get("chapter_id") or 0)
        role = str(card.get("chapter_role_v2") or "")
        start_year, end_year = timeline_bounds(card.get("timeline_years"))
        if role not in CURRENT_TIMELINE_ROLES or start_year is None:
            continue
        if cid == 2:
            last_current_year = end_year or start_year
            continue
        if last_current_year is not None and start_year < last_current_year:
            failures.append(f"第{cid}章正常时间线从{last_current_year}倒退到{start_year}")
        last_current_year = max(last_current_year or start_year, end_year or start_year)
    return failures


def write_compilation_report(
    path: Path, *, events: list[dict[str, Any]], cards: list[dict[str, Any]],
    fingerprints: dict[str, str] | None = None, allow_partial: bool = False,
    global_outline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = validate_full_plan(
        events, cards, allow_partial=allow_partial, global_outline=global_outline,
    )
    report["scope"] = "contiguous_plan_prefix" if allow_partial else "complete_500_chapter_plan"
    report["fingerprints"] = dict(fingerprints or {})
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return report

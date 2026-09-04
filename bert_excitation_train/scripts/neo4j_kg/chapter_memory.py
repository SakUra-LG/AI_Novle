"""Structured chapter memory and deterministic continuity checks.

The JSON sidecars produced by this module are the rebuildable source of truth.
Neo4j is a projection used for retrieval, not the only copy of story state.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


MEMORY_SCHEMA_VERSION = 3
LIFE_STATUS_VALUES = {"alive", "dead", "missing", "incapacitated", "unknown"}
MENTION_MODES = {"active", "memory", "reported", "dream", "unknown"}
TIMELINES = {"current", "previous_life", "memory", "dream", "mixed", "unknown"}
TERMINAL_LIFE_STATUS = {"dead"}
IMMUTABLE_PREDICATES = {
    "life_status", "birth_date", "date_of_birth", "biological_parent",
    "biological_mother", "biological_father", "identity",
}
STRICT_OLD_VALUE_FIELDS = {"life_status", "location", "health", "occupation", "affiliation"}


@dataclass(frozen=True)
class ContinuityViolation:
    code: str
    message: str
    severity: str = "hard"
    character: str = ""
    evidence: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "character": self.character,
            "evidence": self.evidence,
        }


def _text(value: Any, limit: int = 800) -> str:
    return str(value or "").strip()[:limit]


def _float(value: Any, default: float = 0.7) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _dedupe_dicts(items: Iterable[Dict[str, Any]], keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        key = tuple(_text(item.get(k), 200).casefold() for k in keys)
        if not any(key) or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def canonical_possession_key(value: Any, *context: Any) -> str:
    """Return the durable slot for one independently changing right or asset.

    ``possession`` is a broad extraction field, not a single-valued state.  A
    character may simultaneously hold a rehearsal-table right, a medication
    custody right, and an audio-publication right.  The canonical key keeps
    those dimensions separate in both the JSON ledger and its Neo4j projection.
    Context is deliberately accepted so older sidecars can be upgraded from
    their evidence/reason text without asking an LLM to reinterpret the story.
    """

    text = re.sub(
        r"\s+",
        "",
        "；".join(_text(item, 600) for item in (value, *context) if _text(item, 600)),
    )
    if not text:
        return "unspecified"

    rules: Tuple[Tuple[str, str], ...] = (
        (r"(?:后续)?排练.{0,12}(?:原声|声轨).{0,8}发布|(?:原声|声轨).{0,12}发布权", "rehearsal_audio_publish"),
        (r"(?:排练群|群聊|群发|发布人).{0,18}(?:发布|群发)|(?:发布|群发).{0,18}(?:排练群|群聊|全组)", "rehearsal_group_publish"),
        (r"(?:真实)?(?:排练|彩排)表.{0,16}(?:分发|分发名单)|分发名单.{0,16}(?:排练|彩排|真实)", "rehearsal_table_distribute"),
        (r"(?:真实)?(?:排练|彩排)表.{0,16}(?:确认|签字|签批)", "rehearsal_table_confirm"),
        (r"(?:真实)?(?:排练|彩排)表.{0,16}(?:保管|持有)", "rehearsal_table_custody"),
        (r"训练强度.{0,8}决定权", "training_intensity_decide"),
        (r"(?:药品|针剂|药物).{0,10}保管权", "medication_custody"),
        (r"(?:医疗)?双签|本人同意权|第二签字权", "medical_dual_consent"),
        (r"单方.{0,10}(?:注射|用药).{0,6}权", "medical_unilateral_injection"),
        (r"排期.{0,8}签批权", "overload_schedule_approve"),
        (r"最终排期.{0,6}否决权", "schedule_final_veto"),
        (r"舞台机关.{0,8}指挥权", "stage_mechanism_command"),
        (r"最终启停.{0,6}否决权", "stage_start_stop_veto"),
        (r"(?:独立安全总监|安全).{0,10}停机权|停机权", "stage_emergency_stop"),
        (r"私设.{0,8}预留票.{0,8}权限", "reserved_ticket_private"),
        (r"票务.{0,8}监督席位", "ticket_supervision_seat"),
        (r"代签.{0,8}授权", "proxy_signature_authorization"),
        (r"独立签署权", "independent_sign"),
        (r"独家采访席位", "exclusive_interview_seat"),
        (r"单笔支付权", "single_payment"),
        (r"基金监管权", "charity_fund_supervise"),
        (r"低价打包权", "low_price_bundle"),
        (r"母带.{0,8}优先回购权", "master_priority_repurchase"),
    )
    for pattern, key in rules:
        if re.search(pattern, text):
            return key

    candidates = re.findall(
        r"[\u4e00-\u9fff]{2,30}(?:权限|决定权|否决权|签批权|签字权|签署权|"
        r"保管权|监督权|监管权|调度权|控制权|发布权|分发权|回购权|"
        r"指挥权|停机权|支付权|打包权|授权|席位|票池)",
        text,
    )
    core = candidates[-1] if candidates else _text(value, 120)
    core = re.split(
        r"(?:重新获得|重新取得|重新授予|不再拥有|不再有|获得|取得|拿回|夺回|"
        r"收回|恢复|保住|归还|交还|移交|授予|失去|撤销|冻结|暂停|取消|无)",
        core,
    )[-1]
    core = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_]+", "", core).casefold()
    return f"generic:{core or 'unspecified'}"


def story_state_slot(item: Dict[str, Any]) -> str:
    """Return the independent state dimension represented by a memory item."""

    explicit = _text(item.get("state_key") or item.get("stateKey"), 180)
    field = _text(item.get("field") or item.get("predicate"), 100).lower()
    if explicit:
        return explicit
    if field != "possession":
        return field
    key = canonical_possession_key(
        item.get("new_value") or item.get("newValue") or item.get("object"),
        item.get("old_value") or item.get("oldValue"),
        item.get("evidence"),
        item.get("reason"),
    )
    return f"possession:{key}"


def extract_json_object(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        obj = json.loads(text[start : end + 1])
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


def normalize_memory(raw: Dict[str, Any], chapter: int, content_hash: str = "") -> Dict[str, Any]:
    story_id = _text(raw.get("story_id"), 80) or "default"
    narrative_timeline = _text(raw.get("narrative_timeline"), 30).lower()
    if narrative_timeline not in TIMELINES:
        narrative_timeline = "current"
    characters: List[Dict[str, Any]] = []
    for item in _list(raw.get("characters")):
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict) or not _text(item.get("name"), 120):
            continue
        mode = _text(item.get("mention_mode"), 30).lower()
        characters.append({
            "name": _text(item.get("name"), 120),
            "aliases": [_text(x, 120) for x in _list(item.get("aliases")) if _text(x, 120)],
            "mention_mode": mode if mode in MENTION_MODES else "unknown",
            "evidence": _text(item.get("evidence"), 240),
        })

    state_changes: List[Dict[str, Any]] = []
    for item in _list(raw.get("state_changes") or raw.get("stateChanges")):
        if not isinstance(item, dict):
            continue
        character = _text(item.get("character") or item.get("name"), 120)
        field = _text(item.get("field"), 80).lower()
        new_value = _text(item.get("new_value") or item.get("newValue"), 240)
        if not character or not field or not new_value:
            continue
        if field == "life_status":
            normalized_status = new_value.lower()
            status_map = {
                "存活": "alive", "活着": "alive", "已死亡": "dead", "死亡": "dead",
                "去世": "dead", "身亡": "dead", "失踪": "missing", "昏迷": "incapacitated",
            }
            normalized_status = status_map.get(new_value, normalized_status)
            if normalized_status in LIFE_STATUS_VALUES:
                new_value = normalized_status
        is_permanent = bool(item.get("permanent", False))
        if field == "life_status" and str(new_value).lower() in TERMINAL_LIFE_STATUS:
            is_permanent = True
        timeline = _text(item.get("timeline"), 30).lower()
        if timeline not in TIMELINES:
            timeline = narrative_timeline
        normalized_change = {
            "character": character,
            "field": field,
            "old_value": _text(item.get("old_value") or item.get("oldValue"), 240),
            "new_value": new_value,
            "reason": _text(item.get("reason"), 300),
            "evidence": _text(item.get("evidence"), 300),
            "permanent": is_permanent,
            "confidence": _float(item.get("confidence"), 0.75),
            "timeline": timeline,
        }
        normalized_change["state_key"] = story_state_slot({
            **normalized_change,
            "state_key": item.get("state_key") or item.get("stateKey"),
        })
        state_changes.append(normalized_change)

    facts: List[Dict[str, Any]] = []
    for item in _list(raw.get("facts")):
        if not isinstance(item, dict):
            continue
        subject = _text(item.get("subject"), 160)
        predicate = _text(item.get("predicate"), 100).lower()
        obj = _text(item.get("object"), 300)
        if not subject or not predicate or not obj:
            continue
        normalized_fact = {
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "polarity": _text(item.get("polarity"), 20).lower() or "positive",
            "evidence": _text(item.get("evidence"), 300),
            "confidence": _float(item.get("confidence"), 0.7),
            "permanent": bool(item.get("permanent", False)),
            "timeline": _text(item.get("timeline"), 30).lower() if _text(item.get("timeline"), 30).lower() in TIMELINES else narrative_timeline,
        }
        normalized_fact["state_key"] = story_state_slot(normalized_fact)
        facts.append(normalized_fact)

    relationships: List[Dict[str, Any]] = []
    for item in _list(raw.get("relationships") or raw.get("relations")):
        if not isinstance(item, dict):
            continue
        subject = _text(item.get("subject"), 120)
        obj = _text(item.get("object"), 120)
        if not subject or not obj or subject.casefold() == obj.casefold():
            continue
        relationships.append({
            "subject": subject,
            "object": obj,
            "type": _text(item.get("type") or item.get("relation_type") or item.get("relationType"), 80) or "related",
            "status": _text(item.get("status"), 100) or "established",
            "change": _text(item.get("change"), 120),
            "evidence": _text(item.get("evidence"), 300),
            "confidence": _float(item.get("confidence"), 0.7),
            "timeline": _text(item.get("timeline"), 30).lower() if _text(item.get("timeline"), 30).lower() in TIMELINES else narrative_timeline,
        })

    events: List[Dict[str, Any]] = []
    for index, item in enumerate(_list(raw.get("events"))):
        if isinstance(item, str):
            item = {"summary": item}
        if not isinstance(item, dict):
            continue
        summary = _text(item.get("summary") or item.get("name"), 500)
        if not summary:
            continue
        participants: List[Dict[str, str]] = []
        for p in _list(item.get("participants")):
            if isinstance(p, str):
                p = {"name": p, "mode": "active"}
            if not isinstance(p, dict) or not _text(p.get("name"), 120):
                continue
            mode = _text(p.get("mode"), 30).lower()
            participants.append({
                "name": _text(p.get("name"), 120),
                "mode": mode if mode in MENTION_MODES else "active",
                "role": _text(p.get("role"), 100),
            })
        events.append({
            "event_index": index,
            "type": _text(item.get("type") or item.get("event_type") or item.get("eventType"), 80) or "story_event",
            "summary": summary,
            "story_time": _text(item.get("story_time") or item.get("storyTime"), 120),
            "location": _text(item.get("location"), 160),
            "outcome": _text(item.get("outcome"), 400),
            "participants": participants,
            "caused_by": [_text(x, 240) for x in _list(item.get("caused_by") or item.get("causedBy")) if _text(x, 240)],
            "importance": _float(item.get("importance"), 0.65),
            "timeline": _text(item.get("timeline"), 30).lower() if _text(item.get("timeline"), 30).lower() in TIMELINES else narrative_timeline,
        })

    threads: List[Dict[str, Any]] = []
    for item in _list(raw.get("plot_threads") or raw.get("plotThreadSignals")):
        if isinstance(item, str):
            item = {"title": item, "status": "open"}
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title") or item.get("threadTitle"), 240)
        if not title:
            continue
        status = _text(item.get("status") or item.get("signalType"), 40).lower()
        status_map = {"open": "open", "advance": "open", "active": "open", "resolve": "resolved", "resolved": "resolved", "abandon": "abandoned"}
        threads.append({
            "title": title,
            "status": status_map.get(status, "open"),
            "summary": _text(item.get("summary"), 400),
            "evidence": _text(item.get("evidence"), 300),
        })

    continuity_claims: List[Dict[str, Any]] = []
    for item in _list(raw.get("continuity_claims")):
        if not isinstance(item, dict):
            continue
        subject = _text(item.get("subject"), 160)
        predicate = _text(item.get("predicate"), 100).lower()
        value = _text(item.get("value"), 300)
        if subject and predicate and value:
            continuity_claims.append({
                "subject": subject,
                "predicate": predicate,
                "value": value,
                "temporal_relation": _text(item.get("temporal_relation"), 50).lower() or "current_before_chapter",
                "evidence": _text(item.get("evidence"), 300),
            })

    event_preconditions: List[Dict[str, Any]] = []
    for item in _list(raw.get("event_preconditions")):
        if not isinstance(item, dict):
            continue
        requirement = _text(item.get("required_event"), 400)
        if requirement:
            event_preconditions.append({
                "required_event": requirement,
                "timeline": _text(item.get("timeline"), 30).lower() or "current",
                "evidence": _text(item.get("evidence"), 300),
                "confidence": _float(item.get("confidence"), 0.75),
            })

    return {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "story_id": story_id,
        "chapter": int(chapter),
        "content_hash": content_hash,
        "narrative_timeline": narrative_timeline,
        "summary": _text(raw.get("summary"), 600),
        "characters": _dedupe_dicts(characters, ("name",)),
        "events": events[:8],
        "state_changes": _dedupe_dicts(state_changes, ("character", "field", "new_value")),
        "relationships": _dedupe_dicts(relationships, ("subject", "object", "type", "status")),
        "facts": _dedupe_dicts(facts, ("subject", "predicate", "object")),
        "plot_threads": _dedupe_dicts(threads, ("title", "status")),
        "continuity_claims": _dedupe_dicts(continuity_claims, ("subject", "predicate", "value")),
        "event_preconditions": _dedupe_dicts(event_preconditions, ("required_event",)),
    }


def extraction_prompt(chapter: int, content: str, prior_context: str, known_names: Iterable[str] = ()) -> str:
    canonical_names = "、".join(str(x).strip() for x in known_names if str(x).strip())
    return f"""你是长篇小说连续性信息抽取器。只抽取正文明确发生或明确陈述的事实，不得补写或猜测。

特别规则：
1. 区分角色在当前时间线实际行动(active)，与回忆(memory)、他人转述(reported)、梦境(dream)。
2. 死亡必须写为 state_changes.field=life_status,new_value=dead；昏迷、失踪不可误判为死亡。
3. 重生题材中“上一世死亡”和“今生存活”是不同时间线。上一世事实 timeline=previous_life；今生事实 timeline=current。若正文是回忆，角色 mention_mode=memory，不得据此覆盖当前时间线状态。
4. 把每个可改变后文的事实拆开：生死、位置、健康、职业/职位、阵营、持有物、知晓秘密、目标。
5. events 拆成 1-6 个原子事件，participants 给出 mode。关系变化必须有正文证据。
6. 正文对“本章开始前已经是什么状态”的陈述放入 continuity_claims；不要把本章新造成的变化放进去。
7. 正文若把某件过去事件当成已发生的因果前提（例如“上次签约后”“因某人已被解雇”），放入 event_preconditions，并标 timeline=current；前世或历史背景标 previous_life/history，不确定则不要输出。
8. 优先使用这些规范角色名：{canonical_names or '（无预设）'}。简称应放 aliases，不要另建同名角色。
9. old_value 只有正文明确陈述本章变化前状态时才填写，不得根据上下文猜测。
10. permanent 只用于死亡、出生日期、亲生血缘、真实身份等不可逆事实；权限、目标、调查对象、位置、持有物一律不得标 permanent。

生成第{chapter}章之前已知约束：
{prior_context or '（无）'}

第{chapter}章正文：
{content}

只输出 JSON：
{{
  "narrative_timeline":"current|previous_life|memory|dream|mixed|unknown",
  "summary":"本章因果摘要",
  "characters":[{{"name":"角色规范名","aliases":[],"mention_mode":"active|memory|reported|dream|unknown","evidence":"短证据"}}],
  "events":[{{"type":"事件类型","summary":"原子事件","timeline":"current|previous_life|memory|dream","story_time":"可空","location":"可空","outcome":"结果","participants":[{{"name":"角色","mode":"active|memory|reported|dream","role":"作用"}}],"caused_by":[],"importance":0.0}}],
  "state_changes":[{{"character":"角色","field":"life_status|location|health|occupation|affiliation|goal|knowledge|possession","old_value":"可空","new_value":"值；life_status只用alive/dead/missing/incapacitated/unknown","timeline":"current|previous_life|memory|dream","reason":"原因","evidence":"短证据","permanent":false,"confidence":0.0}}],
  "relationships":[{{"subject":"A","object":"B","type":"关系类型","status":"当前状态","timeline":"current|previous_life|memory|dream","change":"本章变化","evidence":"短证据","confidence":0.0}}],
  "facts":[{{"subject":"主体","predicate":"稳定英文谓词","object":"客体/值","timeline":"current|previous_life|memory|dream","polarity":"positive|negative","evidence":"短证据","confidence":0.0,"permanent":false}}],
  "plot_threads":[{{"title":"剧情线/伏笔","status":"open|resolved|abandoned","summary":"推进情况","evidence":"短证据"}}]
  ,"continuity_claims":[{{"subject":"主体","predicate":"life_status|location|health|occupation|affiliation|goal|knowledge|possession或稳定英文谓词","value":"正文声称的本章前状态","temporal_relation":"current_before_chapter|historical","evidence":"短证据"}}]
  ,"event_preconditions":[{{"required_event":"本章明确假定早已发生的事件","timeline":"current|previous_life|history|memory","evidence":"正文中的承接语句","confidence":0.0}}]
}}"""


def _heuristic_memory(chapter: int, content: str, known_names: Iterable[str]) -> Dict[str, Any]:
    canonical_names = [str(n).strip() for n in known_names if str(n).strip()]
    characters: List[Dict[str, Any]] = []
    state_changes: List[Dict[str, Any]] = []
    rebirth_awakening = bool(
        re.search(
            r"重生了|确认重生|猛然惊醒.{0,500}回到.{0,40}(?:之前|以前)|"
            r"回到了.{0,40}(?:之前|以前)",
            content or "",
            re.S,
        )
    )

    def is_historical_death_match(match: re.Match[str]) -> bool:
        window = (content or "")[
            max(0, match.start() - 120) : min(len(content or ""), match.end() + 120)
        ]
        # Historical death references also occur long after the rebirth
        # chapter (e.g. “上一世……走向死亡，但这一次不同”). They must not
        # depend on the local chapter containing the word “重生”.
        if re.search(r"上一世|前世|生前|死前|临死|历史上", window, re.S):
            return True
        if not rebirth_awakening:
            return False
        return bool(
            re.search(
                r"上一世|前世|死亡的记忆|死前|临死|"
                r"距离.{0,30}死亡.{0,16}(?:还有|尚有)|"
                r"回到.{0,40}(?:死亡|悲剧).{0,20}之前",
                window,
                re.S,
            )
        )

    def aliases_for(name: str) -> set[str]:
        aliases = {name}
        for separator in ("·", "・"):
            if separator in name:
                aliases.update(
                    part.strip()
                    for part in name.split(separator)
                    if len(part.strip()) >= 2
                )
        if " " in name:
            aliases.update(
                part.strip() for part in name.split() if len(part.strip()) >= 2
            )
        return aliases

    for name in sorted(set(canonical_names), key=len, reverse=True):
        aliases = {name}
        if "·" in name:
            aliases.update(part.strip() for part in name.split("·") if len(part.strip()) >= 2)
        if " " in name:
            aliases.update(part.strip() for part in name.split() if len(part.strip()) >= 2)
        mention_matches = [
            match
            for alias in sorted(aliases, key=len, reverse=True)
            for match in re.finditer(re.escape(alias), content or "")
        ]
        if not mention_matches:
            continue
        snippets = [content[max(0, match.start() - 60) : match.end() + 100] for match in mention_matches]
        joined = " ".join(snippets)
        lowered = joined.casefold()
        memory_markers = [
            "回忆", "想起", "梦见", "上一世", "前世", "生前", "遗像", "照片里", "录音里",
            "remembered", "recalled", "dreamed of", "in the previous life", "before his death",
            "before her death", "in the photograph", "in the recording",
        ]
        active_markers = [
            "说道", "走进", "站起", "拿起", "看着", "回答", "拨通", "签下", "赶到", "推开",
            "开口", "说完", "抢过", "按下", "握住", "催促", "伸手", "抬手", "转向",
            "拒绝", "反问", "退开", "停在", "走到", "交出", "宣布", "辩解",
            "said", "walked", "stood", "picked up", "answered", "called", "signed", "arrived", "opened",
        ]
        mode = "memory" if any(k.casefold() in lowered for k in memory_markers) and not any(k.casefold() in lowered for k in active_markers) else "active"
        used_aliases = sorted({match.group(0) for match in mention_matches if match.group(0) != name})
        characters.append({"name": name, "aliases": used_aliases, "mention_mode": mode, "evidence": joined[:240]})
        escaped = re.escape(name)
        death_patterns = [
            rf"{escaped}[^。！？.!?]{{0,60}}(?:去世|死亡|死了|咽气|身亡|断气)",
            rf"(?:宣布|确认)[^。！？]{{0,30}}{escaped}[^。！？]{{0,20}}(?:死亡|去世|身亡)",
            rf"{escaped}[^.!?]{{0,80}}(?:died|was dead|passed away|was killed|was pronounced dead)",
            rf"(?:pronounced|declared|confirmed)[^.!?]{{0,50}}{escaped}[^.!?]{{0,20}}dead",
            rf"(?:pronounced|declared|confirmed)[^.!?]{{0,50}}dead[^.!?]{{0,30}}{escaped}",
        ]
        death_matches = [
            match
            for pattern in death_patterns
            for match in re.finditer(pattern, content or "", flags=re.I)
            if not is_historical_death_match(match)
            and not re.search(
                r"堵死|憋死|累死|吓死|气死|烦死|死死|该死|找死|急死",
                match.group(0),
            )
        ]
        if mode == "active" and death_matches:
            state_changes.append({
                "character": name, "field": "life_status", "old_value": "alive", "new_value": "dead",
                "reason": "正文明确死亡", "evidence": joined[:300], "permanent": True, "confidence": 0.82,
            })
    if not state_changes:
        # A flat audio/signal waveform is common in performance scenes and
        # must not be promoted to a death event. Require explicit ECG/life-
        # sign context for waveform evidence; cardiac arrest phrases remain
        # valid independent signals.
        global_death = re.search(
            r"(?:心电图|心电|监护仪|生命体征).{0,100}(?:拉平|直线|停止)|"
            r"心脏.{0,30}(?:骤停|停跳|停止搏动|不再搏动)|"
            r"呼吸.{0,20}(?:停止(?!键|按钮|开关)|断绝)",
            content or "",
            flags=re.S,
        )
        if global_death and is_historical_death_match(global_death):
            global_death = None
        if global_death:
            nearby: List[Tuple[int, str, str]] = []
            for name in canonical_names:
                aliases = {name}
                if "·" in name:
                    aliases.add(name.split("·", 1)[0])
                if " " in name:
                    aliases.update(part for part in name.split() if len(part) >= 2)
                for alias in aliases:
                    for match in re.finditer(re.escape(alias), content or ""):
                        distance = abs(match.start() - global_death.start())
                        if distance <= 360:
                            nearby.append((distance, name, alias))
            if nearby:
                _, dead_name, alias = min(nearby, key=lambda item: item[0])
                evidence_start = max(0, global_death.start() - 180)
                evidence_end = min(len(content or ""), global_death.end() + 220)
                state_changes.append({
                    "character": dead_name,
                    "field": "life_status",
                    "old_value": "alive",
                    "new_value": "dead",
                    "reason": "正文以生命体征停止明确死亡",
                    "evidence": (content or "")[evidence_start:evidence_end],
                    "permanent": True,
                    "confidence": 0.78,
                })
    for name in canonical_names:
        aliases = {name}
        if "·" in name:
            aliases.add(name.split("·", 1)[0])
        permission_match = None
        for alias in aliases:
            permission_match = re.search(
                rf"{re.escape(alias)}[^。！？\n]{{0,100}}失去[^。！？\n]{{0,28}}"
                rf"(?:单方|单方面|单独)[^。！？\n]{{0,28}}(?:注射|用药)[^。！？\n]{{0,12}}(?:权|权力)",
                content or "",
            )
            if permission_match:
                break
        if permission_match:
            loss_position = permission_match.start() + permission_match.group(0).rfind("失去")
            nearest_candidates: List[Tuple[int, str]] = []
            for candidate_name in canonical_names:
                candidate_aliases = {candidate_name}
                if "·" in candidate_name:
                    candidate_aliases.add(candidate_name.split("·", 1)[0])
                for candidate_alias in candidate_aliases:
                    position = (content or "").rfind(candidate_alias, max(0, loss_position - 140), loss_position)
                    if position >= 0:
                        nearest_candidates.append((position, candidate_name))
            nearest_name = max(nearest_candidates, default=(-1, ""), key=lambda item: item[0])[1]
            if nearest_name and nearest_name != name:
                permission_match = None
        if permission_match and not any(
            item.get("character") == name
            and item.get("field") == "possession"
            and item.get("new_value") == "无单方注射权"
            for item in state_changes
        ):
            state_changes.append({
                "character": name,
                "field": "possession",
                "old_value": "单方注射权",
                "new_value": "无单方注射权",
                "reason": "正文明确撤销单方医疗操作权限",
                "evidence": permission_match.group(0),
                "permanent": False,
                "confidence": 0.84,
            })
    dual_sign_match = re.search(r"双签.{0,30}(?:生效|执行)|(?:第二签字权|双签控制).{0,30}(?:生效|取得)", content or "", re.S)
    if dual_sign_match:
        opening_candidates = [
            ((content or "").find(name), name)
            for name in canonical_names
            if (content or "").find(name) >= 0 and (content or "").find(name) < 500
        ]
        protagonist_name = min(opening_candidates, default=(0, ""), key=lambda item: item[0])[1]
        if protagonist_name and not any(
            item.get("character") == protagonist_name
            and item.get("field") == "possession"
            and item.get("new_value") == "医疗双签与本人同意权"
            for item in state_changes
        ):
            state_changes.append({
                "character": protagonist_name,
                "field": "possession",
                "old_value": "",
                "new_value": "医疗双签与本人同意权",
                "reason": "正文明确医疗双签已经生效",
                "evidence": dual_sign_match.group(0),
                "permanent": False,
                "confidence": 0.82,
            })

    opening_candidates = [
        ((content or "").find(name), name)
        for name in canonical_names
        if 0 <= (content or "").find(name) < 500
    ]
    current_protagonist = min(
        opening_candidates,
        default=(-1, ""),
        key=lambda item: item[0],
    )[1]

    def append_explicit_possession(
        character: str,
        new_value: str,
        evidence_match: Optional[re.Match[str]],
        reason: str,
        *,
        old_value: str = "",
        confidence: float = 0.9,
    ) -> None:
        if not character or evidence_match is None:
            return
        if any(
            item.get("character") == character
            and item.get("field") == "possession"
            and canonical_possession_key(
                item.get("new_value"),
                item.get("old_value"),
                item.get("evidence"),
            ) == canonical_possession_key(
                new_value,
                old_value,
                evidence_match.group(0),
            )
            for item in state_changes
        ):
            return
        state_changes.append({
            "character": character,
            "field": "possession",
            "old_value": old_value,
            "new_value": new_value,
            "reason": reason,
            "evidence": evidence_match.group(0),
            "permanent": False,
            "confidence": confidence,
        })

    group_publish_match = re.search(
        r"(?:当场)?收回(?:排练群|群聊)[^。！？\n]{0,24}(?:发布权限|群发权限)"
        r"[^。！？\n]{0,80}(?:发布人改成(?:他|她)本人|只有(?:他|她)确认的消息可以发)",
        content or "",
    )
    append_explicit_possession(
        current_protagonist,
        "排练群发布权限",
        group_publish_match,
        "正文明确收回排练群发布控制并改为本人确认",
    )
    if group_publish_match:
        for name in canonical_names:
            if name == current_protagonist:
                continue
            group_loss_match = None
            for alias in aliases_for(name):
                group_loss_match = re.search(
                    rf"{re.escape(alias)}[^。！？\n]{{0,80}}失去"
                    r"[^。！？\n]{0,20}(?:发布权限|群发权限)",
                    content or "",
                )
                if group_loss_match:
                    break
            append_explicit_possession(
                name,
                "无排练群发布权限",
                group_loss_match,
                "正文明确排练群发布权已从该人物收回",
                old_value="排练群发布权限",
            )

    table_confirmation_match = re.search(
        r"真实(?:排练|彩排)表由(?:我|本人|[\u4e00-\u9fff·]{2,20})确认",
        content or "",
    )
    append_explicit_possession(
        current_protagonist,
        "真实彩排表确认权",
        table_confirmation_match,
        "正文明确由本人确认真实彩排表",
    )
    table_distribution_match = re.search(
        r"分发名单(?:也)?由(?:我|本人|[\u4e00-\u9fff·]{2,20})决定",
        content or "",
    )
    append_explicit_possession(
        current_protagonist,
        "排练表分发权",
        table_distribution_match,
        "正文明确由本人决定排练表分发名单",
    )
    for name in canonical_names:
        aliases = {name}
        if "·" in name:
            aliases.add(name.split("·", 1)[0])
        for alias in aliases:
            gain_match = re.search(
                rf"{re.escape(alias)}[^。！？\n]{{0,80}}(?:收回|拿回|获得|夺回|接管|取得)"
                rf"[^。！？\n]{{0,20}}?([\u4e00-\u9fff]{{2,18}}(?:权限|决定权|签字权|签批权|否决权|"
                rf"保管权|控制权|指挥权|调度权|停机权|监督权|分发权|发布权|席位|票池))",
                content or "",
            )
            if not gain_match:
                gain_match = re.search(
                    rf"{re.escape(alias)}[^。！？\n]{{0,40}}[。！？]\s*(?:他|她)"
                    rf"[^。！？\n]{{0,80}}(?:收回|拿回|获得|夺回|接管|取得)"
                    rf"[^。！？\n]{{0,20}}?([\u4e00-\u9fff]{{2,18}}(?:权限|决定权|签字权|签批权|否决权|"
                    rf"保管权|控制权|指挥权|调度权|停机权|监督权|分发权|发布权|席位|票池))",
                    content or "",
                )
            if gain_match and "注射" not in gain_match.group(1):
                gained_right = re.sub(r"^(?:了|到)", "", gain_match.group(1))
                state_changes.append({
                    "character": name,
                    "field": "possession",
                    "old_value": "",
                    "new_value": gained_right,
                    "reason": "正文明确取得或收回权限",
                    "evidence": gain_match.group(0),
                    "permanent": False,
                    "confidence": 0.8,
                })
                break
        for alias in aliases:
            loss_match = re.search(
                rf"{re.escape(alias)}[^。！？\n]{{0,80}}失去[^。！？\n]{{0,20}}?"
                rf"([\u4e00-\u9fff]{{2,18}}(?:权限|决定权|签字权|签批权|否决权|保管权|"
                rf"控制权|指挥权|调度权|停机权|监督权|分发权|发布权|席位|票池))",
                content or "",
            )
            if not loss_match:
                loss_match = re.search(
                    rf"{re.escape(alias)}[^。！？\n]{{0,40}}[。！？]\s*(?:他|她)"
                    rf"[^。！？\n]{{0,80}}失去[^。！？\n]{{0,20}}?"
                    rf"([\u4e00-\u9fff]{{2,18}}(?:权限|决定权|签字权|签批权|否决权|保管权|"
                    rf"控制权|指挥权|调度权|停机权|监督权|分发权|发布权|席位|票池))",
                    content or "",
                )
            if loss_match and "注射" not in loss_match.group(1):
                if re.search(
                    rf"{re.escape(alias)}[^。！？\n]{{0,12}}被开除"
                    r"[^。！？\n]{0,16}也失去",
                    loss_match.group(0),
                ):
                    continue
                lost_right = re.sub(r"^(?:掉了?|了)", "", loss_match.group(1))
                if (
                    re.fullmatch(r"(?:发布权限|发布权|群发权限)", lost_right)
                    and any(
                        item.get("character") == name
                        and story_state_slot(item)
                        == "possession:rehearsal_group_publish"
                        for item in state_changes
                    )
                ):
                    break
                state_changes.append({
                    "character": name,
                    "field": "possession",
                    "old_value": lost_right,
                    "new_value": "无" + lost_right,
                    "reason": "正文明确失去权限",
                    "evidence": loss_match.group(0),
                    "state_key": "possession:" + canonical_possession_key(
                        lost_right,
                        loss_match.group(0),
                        content or "",
                    ),
                    "permanent": False,
                    "confidence": 0.8,
                })
                break
    for name in canonical_names:
        for alias in aliases_for(name):
            assigned_right = re.search(
                rf"(?P<right>[\u4e00-\u9fff]{{2,20}}(?:权|票池))"
                rf"[^。！？\n]{{0,10}}?(?:归还|交还|移交|归)(?:给|至)?"
                rf"[^。！？\n]{{0,8}}{re.escape(alias)}",
                content or "",
            )
            if not assigned_right:
                assigned_right = re.search(
                    rf"(?:归还|交还|移交|交给)(?:给|至)?{re.escape(alias)}"
                    rf"[^。！？\n]{{0,10}}?(?P<right>[\u4e00-\u9fff]{{2,20}}(?:权|票池))",
                    content or "",
                )
            if not assigned_right:
                continue
            right = assigned_right.group("right")
            if "注射" in right:
                continue
            state_changes.append({
                "character": name,
                "field": "possession",
                "old_value": "",
                "new_value": right,
                "reason": "正文由现场权限者明确归还或移交权限",
                "evidence": assigned_right.group(0),
                "permanent": False,
                "confidence": 0.88,
            })
            break

    suspension_matches: Dict[str, re.Match[str]] = {}
    for name in canonical_names:
        for alias in aliases_for(name):
            named_suspension = re.search(
                rf"{re.escape(alias)}[^。！？\n]{{0,28}}(?:被)?(?:停职|暂停职务)|"
                rf"(?:停职|暂停职务)[^。！？\n]{{0,28}}{re.escape(alias)}",
                content or "",
            )
            if named_suspension:
                suspension_matches[name] = named_suspension
                break
    direct_suspension = re.search(
        r"(?:即刻|现在|当场)暂停你的职务|你的职务(?:即刻|现在|当场)暂停|你被停职",
        content or "",
    )
    if direct_suspension and not suspension_matches:
        nearby_names: List[Tuple[int, str]] = []
        for name in canonical_names:
            for alias in aliases_for(name):
                position = (content or "").rfind(
                    alias,
                    max(0, direct_suspension.start() - 320),
                    direct_suspension.start(),
                )
                if position >= 0:
                    nearby_names.append((position, name))
        if nearby_names:
            _, target_name = max(nearby_names, key=lambda item: item[0])
            suspension_matches[target_name] = direct_suspension
    for name, suspension_match in suspension_matches.items():
        state_changes.append({
            "character": name,
            "field": "occupation",
            "old_value": "在职",
            "new_value": "停职",
            "reason": "正文由现场负责人明确宣布停职",
            "evidence": suspension_match.group(0),
            "permanent": False,
            "confidence": 0.86 if suspension_match is not direct_suspension else 0.78,
        })

    def ensure_active_character(name: str, evidence: str) -> None:
        if not name or any(item.get("name") == name for item in characters):
            return
        characters.append({
            "name": name,
            "aliases": [],
            "mention_mode": "active",
            "evidence": evidence[:240],
        })

    def resolve_subject(raw_subject: str) -> str:
        subject = re.sub(
            r"^(?:这名|那名|该名|一名|这位|那位|该位|最听话的)",
            "",
            (raw_subject or "").strip(),
        )
        for canonical_name in canonical_names:
            if subject == canonical_name or subject in aliases_for(canonical_name):
                return canonical_name
        return subject

    termination_patterns = (
        r"收回(?P<subject>[\u4e00-\u9fff·]{2,30})的工作证"
        r"[^。！？\n]{0,40}(?:宣布)?解除其职务",
        r"(?:宣布|决定)(?:当场|立即)?(?:开除|解雇|辞退)"
        r"(?P<subject>[\u4e00-\u9fff·]{2,30}(?:助理|主管|经理|总监|医生|"
        r"律师|经纪人|联络人|负责人))",
    )
    terminated_subjects: set[str] = set()
    for pattern in termination_patterns:
        for termination_match in re.finditer(pattern, content or ""):
            subject = resolve_subject(termination_match.group("subject"))
            if not subject or subject in terminated_subjects:
                continue
            terminated_subjects.add(subject)
            evidence = termination_match.group(0)
            ensure_active_character(subject, evidence)
            state_changes.append({
                "character": subject,
                "field": "occupation",
                "old_value": "在职",
                "new_value": "开除",
                "reason": "正文明确收回工作凭证并解除职务",
                "evidence": evidence,
                "permanent": False,
                "confidence": 0.9,
            })

    retention_pattern = re.compile(
        r"你仍是(?P<occupation>[\u4e00-\u9fff]{2,18}(?:总监|经理|主管|负责人|"
        r"医生|律师|经纪人|制作人|歌手|演员|助理))"
    )
    for retention_match in retention_pattern.finditer(content or ""):
        nearby_names: List[Tuple[int, str]] = []
        for name in canonical_names:
            for alias in aliases_for(name):
                position = (content or "").rfind(
                    alias,
                    max(0, retention_match.start() - 320),
                    retention_match.start(),
                )
                if position >= 0:
                    nearby_names.append((position, name))
        if not nearby_names:
            continue
        _, retained_name = max(nearby_names, key=lambda item: item[0])
        occupation = retention_match.group("occupation")
        if any(
            item.get("character") == retained_name
            and item.get("field") == "occupation"
            and item.get("new_value") == occupation
            for item in state_changes
        ):
            continue
        state_changes.append({
            "character": retained_name,
            "field": "occupation",
            "old_value": occupation,
            "new_value": occupation,
            "reason": "正文明确确认该人物继续任职",
            "evidence": retention_match.group(0),
            "permanent": False,
            "confidence": 0.82,
        })

    compact = re.sub(r"\s+", "", content or "")
    sentences = [
        item.strip()
        for item in re.split(r"(?<=[。！？!?])", compact)
        if item.strip()
    ]
    opening = sentences[0] if sentences else compact[:240]
    ending = sentences[-1] if sentences else compact[-240:]
    payoff_sentences = [
        sentence for sentence in sentences
        if re.search(
            r"当场(?:宣布|收回|失去|取消|开除)|解除.{0,20}(?:职务|合作|权限)|"
            r"取消.{0,20}(?:资格|权限|通行)|双签.{0,20}生效|被开除|被停职|"
            r"被否决|全部冻结|标为暂停|恢复日.{0,12}生效|"
            r"(?:失去|取得|获得).{0,30}(?:权限|决定权|签字权|签批权|否决权|"
            r"保管权|控制权|指挥权|调度权|停机权|监督权|席位|票池)|"
            r"叫停.{0,20}真人(?:登台|使用)|保住.{0,24}(?:舞者|人员|现场).{0,8}安全|"
            r"(?:即刻|现在|当场)暂停你的职务|拿回(?!扣)|夺回|收回.{0,20}权限|"
            r"[\u4e00-\u9fff]{2,20}(?:权|票池).{0,12}(?:归还|交还|移交|归)",
            sentence,
        )
        and not re.search(r"(?:试图|想|想要|伸手.{0,6})拿回", sentence)
    ]
    state_payoff_facts: List[str] = []
    for state_change in state_changes:
        character = str(state_change.get("character") or "").strip()
        field = str(state_change.get("field") or "").strip()
        new_value = str(state_change.get("new_value") or "").strip()
        reason = str(state_change.get("reason") or "").strip()
        if not character or not new_value:
            continue
        if field == "occupation" and new_value == "开除":
            state_payoff_facts.append(f"{character}已被开除")
        elif field == "occupation" and "继续任职" in reason:
            state_payoff_facts.append(f"{character}仍任{new_value}")
        elif field == "possession" and new_value.startswith("无") and len(new_value) > 1:
            state_payoff_facts.append(f"{character}失去{new_value[1:]}")
        elif field == "possession":
            state_payoff_facts.append(f"{character}取得{new_value}")
    state_payoff_facts = list(dict.fromkeys(state_payoff_facts))

    summary_parts = [opening]
    summary_parts.extend(payoff_sentences[-3:])
    summary_parts.extend(state_payoff_facts)
    if ending and ending not in summary_parts:
        summary_parts.append(ending)
    summary = _text("；".join(part.strip("”\"'") for part in summary_parts if part), 600)
    dead_names = [
        str(item.get("character") or "").strip()
        for item in state_changes
        if str(item.get("field") or "") == "life_status"
        and str(item.get("new_value") or "").casefold() == "dead"
    ]
    outcome = (
        "、".join(dead_names) + "在本章明确死亡"
        if dead_names else _text(
            "；".join(list(dict.fromkeys(payoff_sentences[-3:] + state_payoff_facts)))
            if payoff_sentences or state_payoff_facts else ending,
            400,
        ).strip("”\"'")
    )
    participants = [
        {"name": item["name"], "mode": item.get("mention_mode", "active"), "role": "正文参与者"}
        for item in characters
    ]
    events = []
    if summary and participants:
        events.append({
            "type": "death_event" if dead_names else "chapter_event",
            "summary": summary,
            "outcome": outcome,
            "participants": participants,
            "importance": 0.9 if dead_names else 0.65,
        })
    return normalize_memory(
        {
            "summary": summary,
            "characters": characters,
            "events": events,
            "state_changes": state_changes,
        },
        chapter,
        content_hash(content),
    )


def content_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def extract_chapter_memory(
    chapter: int,
    content: str,
    prior_context: str = "",
    known_names: Iterable[str] = (),
    llm_call: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    content_hash_value = content_hash(content)
    best_memory: Optional[Dict[str, Any]] = None
    rules_only = os.getenv("STORY_MEMORY_RULES_ONLY", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if llm_call is not None and not rules_only:
        try:
            llm_attempts = max(1, min(3, int(os.getenv("STORY_MEMORY_LLM_ATTEMPTS", "1"))))
        except ValueError:
            llm_attempts = 1
        for _ in range(llm_attempts):
            try:
                parsed = extract_json_object(llm_call(extraction_prompt(chapter, content, prior_context, known_names)))
                if parsed:
                    memory = normalize_memory(parsed, chapter, content_hash_value)
                    best_memory = memory
                    if memory.get("characters") and memory.get("events"):
                        if not memory.get("summary"):
                            memory["summary"] = _text(memory["events"][0].get("summary"), 800)
                        memory["extraction_status"] = "llm_complete"
                        return memory
            except Exception:
                continue
    if best_memory is not None:
        best_memory["extraction_status"] = "llm_incomplete"
        return best_memory
    memory = _heuristic_memory(chapter, content, known_names)
    memory["extraction_status"] = (
        "heuristic_complete"
        if memory.get("characters") and memory.get("events")
        else "heuristic_incomplete"
    )
    return memory


def load_memory_files(
    memory_dir: Path,
    before_chapter: Optional[int] = None,
    *,
    strict: bool = False,
) -> List[Dict[str, Any]]:
    if not memory_dir.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for path in sorted(memory_dir.glob("chapter_*_memory.json")):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(obj, dict):
                raise ValueError("chapter memory root must be an object")
            ch = int(obj.get("chapter", 0))
            suffix = path.stem.removeprefix("chapter_").removesuffix("_memory")
            if ch <= 0 or not suffix.isdigit() or int(suffix) != ch:
                raise ValueError("chapter memory filename/chapter mismatch")
            if before_chapter is None or ch < before_chapter:
                out.append(
                    normalize_memory(obj, ch, _text(obj.get("content_hash"), 80))
                )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            if strict:
                raise RuntimeError(f"invalid chapter memory ledger: {path}") from exc
            continue
    return sorted(out, key=lambda x: int(x.get("chapter", 0)))


def save_memory_file(memory_dir: Path, memory: Dict[str, Any]) -> Path:
    memory_dir.mkdir(parents=True, exist_ok=True)
    chapter = int(memory["chapter"])
    path = memory_dir / f"chapter_{chapter:03d}_memory.json"
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        with tmp.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(memory, ensure_ascii=False, indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def _canonical(name: str, aliases: Dict[str, str]) -> str:
    return aliases.get(name.casefold(), name)


def _story_time_key(value: Any) -> Optional[Tuple[int, int, int]]:
    text = _text(value, 120)
    if not text:
        return None
    match = re.search(r"\b((?:18|19|20)\d{2})[-/.年](\d{1,2})?(?:[-/.月](\d{1,2}))?", text)
    if match:
        return int(match.group(1)), int(match.group(2) or 1), int(match.group(3) or 1)
    match = re.search(r"\b((?:18|19|20)\d{2})\b", text)
    if match:
        return int(match.group(1)), 1, 1
    return None


def _event_terms(value: Any) -> set[str]:
    text = _text(value, 500).casefold()
    latin = set(re.findall(r"[a-z0-9]{3,}", text))
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", text)
    cjk = {run[i : i + 2] for run in cjk_runs for i in range(max(0, len(run) - 1))}
    return latin | cjk


def _event_similarity(left: Any, right: Any) -> float:
    a, b = _event_terms(left), _event_terms(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))


def _event_action_buckets(value: Any) -> set[str]:
    text = _text(value, 500).casefold()
    groups = {
        "audition_performance": ("试镜", "试戏", "表演", "演绎", "台词", "独白", "audition", "perform"),
        "contract_signing": ("签约", "签署", "合同", "合约", "contract", "signing", "signed"),
        "role_award": ("获得角色", "拿下角色", "出演", "女主角", "主演", "cast as", "wins the role"),
        "representation_end": ("解除代理", "终止代理", "撤销代理", "解约", "terminate representation"),
        "appointment": ("预约", "约定会面", "确认会面", "appointment", "meeting confirmed"),
        "rebirth": ("重生", "回到过去", "再活一次", "reborn", "returned to"),
    }
    return {
        bucket for bucket, markers in groups.items()
        if any(marker in text for marker in markers)
    }


def _state_values_equal(field: Any, left: Any, right: Any) -> bool:
    a = re.sub(r"\s+", "", _text(left, 300).casefold())
    b = re.sub(r"\s+", "", _text(right, 300).casefold())
    if a == b:
        return True
    if _text(field, 100).lower() == "occupation":
        occupation_a = re.sub(r"[（(][^）)]*[）)]", "", a)
        occupation_b = re.sub(r"[（(][^）)]*[）)]", "", b)
        if occupation_a == occupation_b:
            return True
    if _text(field, 100).lower() == "health":
        aliases = {
            "stable": "stable", "稳定": "stable", "状况稳定": "stable", "健康稳定": "stable",
            "healthy": "healthy", "健康": "healthy", "良好": "healthy", "身体良好": "healthy",
            "injured": "injured", "受伤": "injured", "重伤": "injured",
        }
        return aliases.get(a, a) == aliases.get(b, b)
    return False


def build_story_state(memories: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    aliases: Dict[str, str] = {}
    states: Dict[Tuple[str, str], Dict[str, Any]] = {}
    relationships: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    threads: Dict[str, Dict[str, Any]] = {}
    events: List[Dict[str, Any]] = []
    characters: Dict[str, Dict[str, Any]] = {}
    for memory in sorted(memories, key=lambda x: int(x.get("chapter", 0))):
        chapter = int(memory.get("chapter", 0))
        for c in _list(memory.get("characters")):
            name = _text(c.get("name"), 120)
            if not name:
                continue
            characters.setdefault(name, {"name": name, "aliases": []})
            if "·" in name:
                for short in (x.strip() for x in name.split("·") if x.strip()):
                    aliases.setdefault(short.casefold(), name)
            for alias in _list(c.get("aliases")):
                alias_text = _text(alias, 120)
                if alias_text:
                    aliases[alias_text.casefold()] = name
        for s in _list(memory.get("state_changes")):
            if _text(s.get("timeline"), 30).lower() not in {"current", "unknown"}:
                continue
            name = _canonical(_text(s.get("character"), 120), aliases)
            if name:
                state_key = story_state_slot(s)
                states[(name.casefold(), state_key)] = {
                    **s,
                    "character": name,
                    "state_key": state_key,
                    "chapter": chapter,
                }
        for f in _list(memory.get("facts")):
            if _text(f.get("timeline"), 30).lower() not in {"current", "unknown"}:
                continue
            subject = _canonical(_text(f.get("subject"), 160), aliases)
            if subject:
                state_key = story_state_slot(f)
                states[(subject.casefold(), state_key)] = {
                    "character": subject, "field": _text(f.get("predicate"), 100).lower(),
                    "new_value": _text(f.get("object"), 300), "chapter": chapter,
                    "evidence": _text(f.get("evidence"), 300), "confidence": _float(f.get("confidence")),
                    "permanent": bool(f.get("permanent", False)),
                    "state_key": state_key,
                }
        for r in _list(memory.get("relationships")):
            if _text(r.get("timeline"), 30).lower() not in {"current", "unknown"}:
                continue
            a = _canonical(_text(r.get("subject"), 120), aliases)
            b = _canonical(_text(r.get("object"), 120), aliases)
            if a and b:
                relationships[(a.casefold(), b.casefold(), _text(r.get("type"), 80).lower())] = {**r, "subject": a, "object": b, "chapter": chapter}
        for t in _list(memory.get("plot_threads")):
            title = _text(t.get("title"), 240)
            if title:
                threads[title.casefold()] = {**t, "chapter": chapter}
        for e in _list(memory.get("events")):
            events.append({**e, "chapter": chapter})
    return {
        "characters": list(characters.values()),
        "states": list(states.values()),
        "relationships": list(relationships.values()),
        "plot_threads": list(threads.values()),
        "events": events,
        "aliases": aliases,
    }


def validate_transition(prior_state: Dict[str, Any], candidate: Dict[str, Any]) -> List[ContinuityViolation]:
    aliases: Dict[str, str] = prior_state.get("aliases", {}) or {}
    current: Dict[Tuple[str, str], Dict[str, Any]] = {
        (_text(x.get("character"), 120).casefold(), story_state_slot(x)): x
        for x in _list(prior_state.get("states"))
    }
    dead = {
        name: value
        for (name, _state_key), value in current.items()
        if _text(value.get("field"), 80).lower() == "life_status"
        and _text(value.get("new_value"), 40).lower() in TERMINAL_LIFE_STATUS
        and re.search(r"(?:\u53bb\u4e16|\u6b7b\u4ea1|\u6b7b\u4e86|\u54bd\u6c14|\u8eab\u4ea1|\u65ad\u6c14|pronounced dead|was dead)", _text(value.get("evidence"), 400), re.I)
    }
    violations: List[ContinuityViolation] = []

    modes: Dict[str, str] = {}
    evidence: Dict[str, str] = {}
    if _text(candidate.get("narrative_timeline"), 30).lower() in {"current", "unknown", "mixed"}:
        for c in _list(candidate.get("characters")):
            name = _canonical(_text(c.get("name"), 120), aliases)
            modes[name.casefold()] = _text(c.get("mention_mode"), 30).lower()
            evidence[name.casefold()] = _text(c.get("evidence"), 240)
    for event in _list(candidate.get("events")):
        if _text(event.get("timeline"), 30).lower() not in {"current", "unknown"}:
            continue
        for p in _list(event.get("participants")):
            name = _canonical(_text(p.get("name"), 120), aliases)
            if _text(p.get("mode"), 30).lower() == "active":
                modes[name.casefold()] = "active"
                evidence[name.casefold()] = _text(event.get("summary"), 240)

    for name_key, old in dead.items():
        if modes.get(name_key) == "active":
            display = _text(old.get("character"), 120)
            violations.append(ContinuityViolation(
                code="DEAD_CHARACTER_ACTIVE",
                message=f"{display} 已于第{int(old.get('chapter', 0))}章死亡，本章只能出现在回忆、梦境或转述中，不能在当前时间线行动。",
                character=display,
                evidence=evidence.get(name_key, ""),
            ))

    for change in _list(candidate.get("state_changes")):
        if _text(change.get("timeline"), 30).lower() not in {"current", "unknown"}:
            continue
        name = _canonical(_text(change.get("character"), 120), aliases)
        field = _text(change.get("field"), 80).lower()
        new_value = _text(change.get("new_value"), 240)
        old = current.get((name.casefold(), story_state_slot(change)))
        if old and field in IMMUTABLE_PREDICATES and bool(old.get("permanent", False)) and not _state_values_equal(field, old.get("new_value"), new_value):
            violations.append(ContinuityViolation(
                code="IMMUTABLE_FACT_CHANGED",
                message=f"{name}.{field}=“{old.get('new_value')}”已被标记为永久事实，不能改成“{new_value}”。",
                character=name,
                evidence=_text(change.get("evidence"), 240),
            ))
        # Occupation is frequently duplicated across this plan's alias-heavy
        # functional roles (e.g. Barry's several representative labels). Do
        # not let a stale merged occupation block otherwise valid prose;
        # life/location/health remain strict continuity gates.
        if old and field in (STRICT_OLD_VALUE_FIELDS - {"occupation"}) and _text(change.get("old_value"), 240):
            declared_old = _text(change.get("old_value"), 240).casefold()
            actual_old = _text(old.get("new_value"), 240).casefold()
            if not _state_values_equal(field, declared_old, actual_old):
                violations.append(ContinuityViolation(
                    code="STATE_OLD_VALUE_MISMATCH",
                    message=f"{name} 的 {field} 现状是“{old.get('new_value')}”，候选正文却以“{change.get('old_value')}”为旧值。",
                    character=name,
                    evidence=_text(change.get("evidence"), 240),
                ))
        if field == "life_status" and name.casefold() in dead and new_value.lower() == "alive":
            violations.append(ContinuityViolation(
                code="ILLEGAL_RESURRECTION",
                message=f"{name} 已死亡，当前项目没有允许复活的世界规则，不能恢复为 alive。",
                character=name,
                evidence=_text(change.get("evidence"), 240),
            ))

    for claim in _list(candidate.get("continuity_claims")):
        if _text(claim.get("temporal_relation"), 50) != "current_before_chapter":
            continue
        name = _canonical(_text(claim.get("subject"), 160), aliases)
        predicate = _text(claim.get("predicate"), 100).lower()
        old = (
            current.get((name.casefold(), story_state_slot({
                "predicate": predicate,
                "object": claim.get("value"),
                "evidence": claim.get("evidence"),
            })))
            if predicate in STRICT_OLD_VALUE_FIELDS | IMMUTABLE_PREDICATES
            else None
        )
        if old and not _state_values_equal(predicate, old.get("new_value"), claim.get("value")):
            violations.append(ContinuityViolation(
                code="PRIOR_STATE_CLAIM_CONFLICT",
                message=f"正文声称 {name}.{predicate}=“{claim.get('value')}”，但第{old.get('chapter')}章后有效状态是“{old.get('new_value')}”。",
                character=name,
                evidence=_text(claim.get("evidence"), 240),
            ))

    for fact in _list(candidate.get("facts")):
        if _text(fact.get("timeline"), 30).lower() not in {"current", "unknown"}:
            continue
        subject = _canonical(_text(fact.get("subject"), 160), aliases)
        predicate = _text(fact.get("predicate"), 100).lower()
        old = current.get((subject.casefold(), story_state_slot(fact)))
        if old and predicate in IMMUTABLE_PREDICATES and bool(old.get("permanent", False)) and not _state_values_equal(predicate, old.get("new_value"), fact.get("object")):
            violations.append(ContinuityViolation(
                code="IMMUTABLE_FACT_CONTRADICTION",
                message=f"永久事实 {subject}.{predicate}=“{old.get('new_value')}”与本章“{fact.get('object')}”冲突。",
                character=subject,
                evidence=_text(fact.get("evidence"), 240),
            ))

    prior_relationships: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for item in sorted(_list(prior_state.get("relationships")), key=lambda x: int(x.get("chapter", 0))):
        pair = (_text(item.get("subject"), 120).casefold(), _text(item.get("object"), 120).casefold())
        prior_relationships[pair] = item
    for rel in _list(candidate.get("relationships")):
        if _text(rel.get("timeline"), 30).lower() not in {"current", "unknown"}:
            continue
        key = (_text(rel.get("subject"), 120).casefold(), _text(rel.get("object"), 120).casefold())
        old = prior_relationships.get(key)
        old_status = _text((old or {}).get("status"), 100).lower()
        new_status = _text(rel.get("status"), 100).lower()
        if old_status in {"conflict", "rupture", "hostile", "敌对", "决裂"} and new_status in {"trust", "intimacy", "allied", "信任", "亲密", "同盟"}:
            if len(_text(rel.get("change"), 120)) < 8 or len(_text(rel.get("evidence"), 300)) < 8:
                violations.append(ContinuityViolation(
                    code="ABRUPT_RELATIONSHIP_REVERSAL",
                    message=f"{rel.get('subject')} 与 {rel.get('object')} 从“{old_status}”直接跳到“{new_status}”，缺少足够的转变事件与证据。",
                    evidence=_text(rel.get("evidence"), 240),
                ))

    prior_threads = {_text(x.get("title"), 240).casefold(): x for x in _list(prior_state.get("plot_threads"))}
    for thread in _list(candidate.get("plot_threads")):
        old = prior_threads.get(_text(thread.get("title"), 240).casefold())
        if old and _text(old.get("status"), 30) in {"resolved", "abandoned"} and _text(thread.get("status"), 30) == "open":
            violations.append(ContinuityViolation(
                code="CLOSED_THREAD_REOPENED",
                message=f"剧情线“{thread.get('title')}”已于第{old.get('chapter')}章结束，不能无解释地重新标记为未决。",
                evidence=_text(thread.get("evidence"), 240),
            ))

    prior_times = [
        (_story_time_key(e.get("story_time")), e)
        for e in _list(prior_state.get("events"))
        if _text(e.get("timeline"), 30).lower() in {"current", "unknown"}
    ]
    prior_times = [(key, event) for key, event in prior_times if key is not None]
    latest_prior_time = max(prior_times, key=lambda pair: pair[0]) if prior_times else None
    previous_candidate_time: Optional[Tuple[int, int, int]] = None
    for event in _list(candidate.get("events")):
        if _text(event.get("timeline"), 30).lower() not in {"current", "unknown"}:
            continue
        event_time = _story_time_key(event.get("story_time"))
        if event_time is None:
            continue
        if latest_prior_time and event_time < latest_prior_time[0]:
            violations.append(ContinuityViolation(
                code="TIMELINE_REGRESSION",
                message=(
                    f"当前时间线从 {latest_prior_time[1].get('story_time')} 倒退到 {event.get('story_time')}，"
                    "若这是回忆必须标记 timeline=previous_life/memory。"
                ),
                evidence=_text(event.get("summary"), 240),
            ))
        if previous_candidate_time and event_time < previous_candidate_time:
            violations.append(ContinuityViolation(
                code="INTRA_CHAPTER_TIME_REVERSAL",
                message=f"本章当前线事件时间从 {previous_candidate_time} 倒退到 {event.get('story_time')}，但未标记为回忆。",
                evidence=_text(event.get("summary"), 240),
            ))
        previous_candidate_time = event_time

    prior_event_texts = [
        f"{e.get('summary', '')} {e.get('outcome', '')}"
        for e in _list(prior_state.get("events"))
        if _text(e.get("timeline"), 30).lower() in {"current", "unknown"}
    ]
    prior_life_event_texts = [
        f"{e.get('summary', '')} {e.get('outcome', '')}"
        for e in _list(prior_state.get("events"))
        if _text(e.get("timeline"), 30).lower() in {"previous_life", "history", "memory", "dream"}
    ]
    candidate_event_texts = [
        f"{e.get('summary', '')} {e.get('outcome', '')}"
        for e in _list(candidate.get("events"))
        if _text(e.get("timeline"), 30).lower() in {"current", "unknown"}
    ]
    for precondition in _list(candidate.get("event_preconditions")):
        if int(candidate.get("chapter", 0)) <= 1:
            continue
        if _text(precondition.get("timeline"), 30).lower() not in {"current", "unknown"}:
            continue
        required = _text(precondition.get("required_event"), 400)
        confidence = _float(precondition.get("confidence"), 0.75)
        best = max((_event_similarity(required, prior) for prior in prior_event_texts), default=0.0)
        # Chapter 2 commonly awakens while explicitly recalling the death scene
        # from chapter 1. Extractors sometimes label that reference as current
        # because the remembering happens now, so allow an actual previous-life
        # event to satisfy the precondition without weakening later chapters.
        if int(candidate.get("chapter", 0)) == 2 and best < 0.20:
            best = max(
                best,
                max((_event_similarity(required, prior) for prior in prior_life_event_texts), default=0.0),
            )
        # The extractor can occasionally label the event that is visibly
        # happening in this chapter as its own precondition. If the candidate
        # also records that same event as current, it is not a missing prior.
        same_chapter_best = max(
            (_event_similarity(required, current) for current in candidate_event_texts),
            default=0.0,
        )
        if same_chapter_best >= 0.35:
            continue
        required_buckets = _event_action_buckets(required)
        same_chapter_semantic_match = any(
            required_buckets & _event_action_buckets(current)
            and _event_similarity(required, current) >= 0.12
            for current in candidate_event_texts
        )
        if same_chapter_semantic_match:
            continue
        # Extraction paraphrases are often short ("准备反击" vs
        # "准备采取措施对抗某人"). A 0.34 bigram threshold rejected valid
        # continuations; 0.20 still keeps unrelated event chains at zero.
        if confidence >= 0.8 and best < 0.20:
            violations.append(ContinuityViolation(
                code="MISSING_EVENT_PRECONDITION",
                message=f"本章把“{required}”当作已发生前提，但此前事件账本中没有对应事件。",
                evidence=_text(precondition.get("evidence"), 240),
            ))
    return violations


def render_story_constraints(state: Dict[str, Any], target_chapter: int, max_chars: int = 2400) -> str:
    lines = [f"【第{target_chapter}章生成前的连续性事实（硬约束优先）】"]
    states = sorted(_list(state.get("states")), key=lambda x: (0 if _text(x.get("field")) == "life_status" else 1, -int(x.get("chapter", 0))))
    for item in states[:28]:
        name, field, value, chapter = item.get("character"), item.get("field"), item.get("new_value"), item.get("chapter")
        prefix = "禁止违反" if field == "life_status" and str(value).lower() == "dead" else "当前事实"
        suffix = "；只能以回忆/梦境/转述出现" if field == "life_status" and str(value).lower() == "dead" else ""
        lines.append(f"- [{prefix}] {name}.{field} = {value}（第{chapter}章确立）{suffix}")
    relationships = sorted(_list(state.get("relationships")), key=lambda x: -int(x.get("chapter", 0)))
    for rel in relationships[:12]:
        lines.append(f"- [当前关系] {rel.get('subject')} --{rel.get('type')}/{rel.get('status')}--> {rel.get('object')}（更新于第{rel.get('chapter')}章）")
    open_threads = [x for x in _list(state.get("plot_threads")) if _text(x.get("status"), 30) == "open"]
    for thread in sorted(open_threads, key=lambda x: -int(x.get("chapter", 0)))[:10]:
        lines.append(f"- [未决剧情线] {thread.get('title')}（最近推进：第{thread.get('chapter')}章）")
    recent_events = sorted(
        [x for x in _list(state.get("events")) if _text(x.get("timeline"), 30).lower() in {"current", "unknown"}],
        key=lambda x: -int(x.get("chapter", 0)),
    )
    for event in recent_events[:10]:
        time_note = f"，故事时间={event.get('story_time')}" if event.get("story_time") else ""
        lines.append(f"- [今生已发生事件] 第{event.get('chapter')}章{time_note}：{event.get('summary')}；结果={event.get('outcome') or '未明确'}")
    historical_events = sorted(
        [x for x in _list(state.get("events")) if _text(x.get("timeline"), 30).lower() in {"previous_life", "memory", "dream"}],
        key=lambda x: -int(x.get("chapter", 0)),
    )
    for event in historical_events[:4]:
        lines.append(f"- [仅历史/回忆，不是今生活动] 第{event.get('chapter')}章记录：{event.get('summary')}")
    return "\n".join(lines)[:max_chars]

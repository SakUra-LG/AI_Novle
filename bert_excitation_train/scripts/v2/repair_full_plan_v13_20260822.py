"""Deterministically repair and audit the complete 250-cluster/500-card plan.

This migration is intentionally conservative.  It keeps cluster/chapter IDs and
the existing plot, but compiles identity, lifecycle, outcome, cost, flaw,
artifact, death-chain and repetition contracts into the authoritative files.
Run without ``--apply`` for a read-only audit; use ``--apply`` to write atomically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs_pop_king_v6_compiled_story_first_500"
EVENTS_PATH = OUT / "event_clusters_v2.json"
CARDS_PATH = OUT / "master_ctx_cards_v2.json"
SYNOPSES_PATH = OUT / "chapter_synopses_v5_qwen_500.json"
OUTLINE_PATH = OUT / "global_story_outline_v5_qwen_500.json"
BIBLE_PATH = ROOT / "data" / "pop_king_character_bible_v1.json"
REPORT_PATH = OUT / "full_plan_v13_audit_20260822.json"

BIRTH_DATE = date(1958, 8, 29)
OUTCOMES = {
    "clean_win", "small_win", "partial_win", "costly_win", "stalemate",
    "setback_with_gain", "major_win", "decisive_win",
}
RESOLUTION_SIGNATURE_OVERRIDES = {
    "EC047": {"attack_domain": "copyright_authorship", "counter_method": "physical_master_provenance", "resolver": "rights_custodian", "publicity": "public", "hero_gain_type": "evidence"},
    "EC050": {"attack_domain": "minor_contract", "counter_method": "judicial_injunction", "resolver": "court", "publicity": "public", "hero_gain_type": "new_right"},
    "EC052": {"attack_domain": "stage_hydraulics", "counter_method": "manual_pressure_log", "resolver": "audience_safety_team", "publicity": "public", "hero_gain_type": "safety"},
    "EC221": {"attack_domain": "technical_data_injection", "counter_method": "microfilm_physical_isolation", "resolver": "archive_team", "publicity": "private", "hero_gain_type": "evidence"},
    "EC226": {"attack_domain": "medical_data_falsification", "counter_method": "analog_heartbeat_recording", "resolver": "independent_monitor", "publicity": "public", "hero_gain_type": "safety"},
    "EC227": {"attack_domain": "legal_management_vacuum", "counter_method": "delegated_authority", "resolver": "court", "publicity": "public", "hero_gain_type": "new_right"},
}
REAL_WORLD_REPLACEMENTS = {
    "昆廷·索恩": "昆廷·琼斯",
    "瑟琳娜·瓦尔": "瑟琳娜·凯德",
    "莉薇娅·科尔": "莉薇娅·普莱斯",
    "黛安娜·洛瑞": "黛安娜·罗文",
    "苏菲亚·陈": "苏菲亚·罗德里格斯",
    "旧金山": "海湾城",
    "联邦调查局": "国家调查署",
    "联邦通信委员会": "广播频谱管理局",
    "FCC": "广播频谱管理局",
    "IBM Selectric": "奥瑞恩电动排字机",
    "IBM电动打字机": "奥瑞恩电动排字机",
    "加州法院": "海湾州高等法院",
    "加州": "海湾州",
    "纽约": "新港城",
    "洛杉矶": "星湾城",
    "芝加哥": "湖风城",
    "美国": "米国",
    "上传至加密电台频段": "以加密短波副载波分时播送",
    "流媒体播放量": "广播点播与授权播放累计次数",
    "工坊实时影像流": "工坊按月寄送的照片档案",
    "实时影像流": "定期更新的照片档案",
    "ART_489_GEAR_ROTATION": "ART_489_FINAL_CHAIN",
    "麦珂风": "麦克风",
    "更换医疗监护人": "强行更换医疗代理人",
    "指定临时监护人": "指定临时医疗代理人",
    "家族监护人身份": "家庭信托共同签署人身份",
    "放弃监护权的文件": "放弃医疗代理选择权的文件",
    "监护权收益": "医疗与版权代理收益",
    "情绪失控的未成年罪犯": "精神失常且无行为能力的危险人物",
    "1979年河湾镇法院监护权确认": "1979年河湾镇法院家庭信托代理权确认",
    "1979年监护权办理": "1979年家庭信托代理权办理",
    "1979年监护权时间线": "1979年家庭信托代理权时间线",
    "处理监护权确认": "处理家庭信托代理权确认",
    "当年由监护人代签": "当年由代理人代签",
    "从“被监护人”转变为“独立合伙人”": "从“被代管者”转变为“独立合伙人”",
    "前世的音乐指导临时换调令麦珂失声并落选，导致她错过": "前世的音乐指导临时换调令麦珂失声并落选，导致他错过",
    "今生她在试唱前记得": "今生他在试唱前记得",
    "证明了她的实力": "证明了他的实力",
    "维克多·兰斯的目光投向了她": "维克多·兰斯的目光投向了他",
    "麦珂早已洞悉一切，她": "麦珂早已洞悉一切，他",
    "麦珂早有准备，她": "麦珂早有准备，他",
    "麦珂早已预料到这一步，她": "麦珂早已预料到这一步，他",
    "麦珂早已洞悉这是针对昆廷生理弱点的陷阱，她": "麦珂早已洞悉这是针对昆廷生理弱点的陷阱，他",
    "麦珂手中的那份旧票据让她意识到": "麦珂手中的那份旧票据让他意识到",
    "麦珂未做任何干预，媒体头条将判决解读为“奇迹康复”，公众误以为她": "麦珂未做任何干预，媒体头条将判决解读为“奇迹康复”，公众误以为他",
    "麦珂的远程通讯通道被切断，外界以为她": "麦珂的远程通讯通道被切断，外界以为他",
    "麦珂意识到这是敌人针对她的": "麦珂意识到这是敌人针对他的",
    "麦珂心中一凛，意识到敌人已经不再满足于法律层面的攻击，而是开始针对她的": "麦珂心中一凛，意识到敌人已经不再满足于法律层面的攻击，而是开始针对他的",
    "她已死，别信她": "他已死，别信他",
    "公众误以为她在胡言乱语": "公众误以为他在胡言乱语",
    "前世麦珂未回应抹黑，导致公众认知长期停留在‘她是否痊愈’": "前世麦珂未回应抹黑，导致公众认知长期停留在‘他是否痊愈’",
    "公众不再关心麦珂是否痊愈，只关心她是否清醒": "公众不再关心麦珂是否痊愈，只关心他是否清醒",
    "声称她已无法控制自己的思维": "声称他已无法控制自己的思维",
    "莉薇娅站在她身旁": "莉薇娅站在他身旁",
    "瑟琳娜握住她的手": "瑟琳娜握住他的手",
    "走向等待她的瑟琳娜": "走向等待他的瑟琳娜",
    "麦珂走出法院，阳光洒在他身上，她": "麦珂走出法院，阳光洒在他身上，他",
    "麦珂与艾琳携手走出会场，面对媒体镜头，她": "麦珂与艾琳携手走出会场，面对媒体镜头，他",
    "利用前世记忆中对1983年酸性墨水配方的了解，她": "利用前世记忆中对1983年酸性墨水配方的了解，他",
    "根据前世记忆，她": "根据前世记忆，他",
    "艾琳·沃特曼凭借重生记忆，早已预料到这一招": "艾琳·沃特曼依据麦珂交给她的当前证据，提前判断出这一招",
    "黛安娜深知前世麦珂因时间差而受害的惨痛教训，她": "黛安娜从麦珂反复核对时间戳的现实动作中看出风险，她",
    "她引用前世麦珂遭遇的惨痛教训": "她引用麦珂公开保存的旧案记录",
    "涉嫌侵犯未成年人权益": "涉嫌侵犯成年人的教育与职业自主权",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def atomic_write(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def walk_replace(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: walk_replace(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [walk_replace(item, replacements) for item in value]
    if isinstance(value, str):
        for old, new in replacements.items():
            value = value.replace(old, new)
    return value


FEMALE_NAMES = ("玛莎", "黛安娜", "瑟琳娜", "莉薇娅", "苏菲亚", "艾琳", "克莱尔", "维拉", "露西")


def repair_protagonist_pronouns(value: Any) -> Any:
    """Repair feminine pronouns only when the local discourse focus is Ma Ke.

    The plan contains many legitimate feminine pronouns for its female leads, so
    a global 她→他 replacement would be destructive.  Focus is updated at every
    punctuation-delimited clause; object forms such as “替她/给她/让她” are kept.
    """
    if isinstance(value, dict):
        return {key: repair_protagonist_pronouns(item) for key, item in value.items()}
    if isinstance(value, list):
        return [repair_protagonist_pronouns(item) for item in value]
    if not isinstance(value, str) or "她" not in value:
        return value
    parts = re.split(r"([，,；;。！？!?\n])", value)
    focus = "unknown"
    result: list[str] = []
    for part in parts:
        if not part or re.fullmatch(r"[，,；;。！？!?\n]", part):
            result.append(part)
            continue
        protagonist_positions = [match.start() for match in re.finditer(r"麦珂(?!风)", part)]
        female_positions = [part.rfind(name) for name in FEMALE_NAMES if name in part]
        last_protagonist = max(protagonist_positions, default=-1)
        last_female = max(female_positions, default=-1)
        if last_protagonist >= 0 or last_female >= 0:
            focus = "protagonist" if last_protagonist > last_female else "female"
        if focus == "protagonist":
            part = re.sub(r"(?<![替给让向对把将为跟与])她", "他", part)
        result.append(part)
    return "".join(result)


def parse_day(value: Any) -> date:
    text = str(value or "").strip()
    match = re.search(r"((?:19|20)\d{2})(?:[-年](\d{1,2}))?(?:[-月](\d{1,2}))?", text)
    if not match:
        raise ValueError(f"无法解析日期：{text!r}")
    year = int(match.group(1))
    month = int(match.group(2) or 1)
    day = int(match.group(3) or 1)
    return date(year, month, day)


def age_at(value: Any) -> int:
    current = parse_day(value)
    return current.year - BIRTH_DATE.year - ((current.month, current.day) < (BIRTH_DATE.month, BIRTH_DATE.day))


def lifecycle(card: dict[str, Any]) -> dict[str, Any]:
    current = parse_day(card.get("timeline_start") or card.get("timeline_years"))
    age = age_at(current.isoformat())
    adult = age >= 18
    return {
        "protagonist_character_id": "CHAR_026AC753E27A",
        "protagonist": "麦珂·杰森",
        "birth_date": BIRTH_DATE.isoformat(),
        "current_date": current.isoformat(),
        "current_year": current.year,
        "current_age": age,
        "life_stage": "adult" if adult else "minor",
        "legal_capacity": "full" if adult else "limited",
        "guardian_required": not adult,
        "allowed_conflict_domains": (
            ["copyright", "management_rights", "medical_proxy", "business_control", "public_reputation", "relationship", "insurance", "asset_ownership"]
            if adult else
            ["parental_guardianship", "school_transfer_by_parent", "minor_contract_protection", "child_performance_permission"]
        ),
        "forbidden_conflict_domains": (
            ["parental_guardianship", "school_transfer_by_parent", "minor_contract_protection", "child_performance_permission"]
            if adult else []
        ),
    }


def build_registry(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, str]]:
    displays: dict[str, Counter[str]] = defaultdict(Counter)
    roles: dict[str, Counter[str]] = defaultdict(Counter)
    aliases: dict[str, set[str]] = defaultdict(set)
    first: dict[str, int] = {}
    alignments: dict[str, Counter[str]] = defaultdict(Counter)
    for event in events:
        chapter = int((event.get("chapter_span") or [9999])[0])
        for member in event.get("canonical_cast") or []:
            if not isinstance(member, dict) or not member.get("character_id"):
                continue
            cid = str(member["character_id"])
            display = str(member.get("display_name") or member.get("name") or "").strip()
            if display:
                displays[cid][display] += 1
                aliases[cid].add(display)
            aliases[cid].update(str(item).strip() for item in member.get("aliases") or [] if str(item).strip())
            roles[cid][str(member.get("role") or "")] += 1
            alignments[cid][str(member.get("alignment") or "")] += 1
            first[cid] = min(first.get(cid, chapter), chapter)
    registry = []
    by_id: dict[str, dict[str, Any]] = {}
    alias_to_id: dict[str, str] = {}
    birth_dates = {"CHAR_026AC753E27A": BIRTH_DATE.isoformat()}
    for cid in sorted(displays, key=lambda item: (first[item], item)):
        canonical = displays[cid].most_common(1)[0][0]
        row = {
            "character_id": cid,
            "canonical_name": canonical,
            "aliases": sorted(aliases[cid] | {canonical}),
            "sex": "male" if cid == "CHAR_026AC753E27A" else "unspecified",
            "birth_date": birth_dates.get(cid),
            "role": roles[cid].most_common(1)[0][0],
            "alignment": alignments[cid].most_common(1)[0][0],
            "first_appearance_chapter": first[cid],
        }
        registry.append(row)
        by_id[cid] = row
        for alias in row["aliases"]:
            alias_to_id.setdefault(alias, cid)
    return registry, by_id, alias_to_id


def canonicalize_cast(container: dict[str, Any], registry: dict[str, dict[str, Any]]) -> None:
    for member in container.get("canonical_cast") or []:
        if not isinstance(member, dict):
            continue
        row = registry.get(str(member.get("character_id") or ""))
        if not row:
            continue
        member["name"] = row["canonical_name"]
        member["display_name"] = row["canonical_name"]
        member["aliases"] = list(row["aliases"])


def outcome_for(index: int, event: dict[str, Any]) -> str:
    existing = str(event.get("outcome_type") or "")
    if existing in OUTCOMES:
        return existing
    if index == 250:
        return "decisive_win"
    if index % 10 == 0:
        return "major_win"
    if index % 8 in {3, 7}:
        return "partial_win"
    if index % 4 == 0:
        return "small_win"
    return "clean_win"


def soften_absolutes(text: Any) -> str:
    value = str(text or "")
    for old, new in {
        "彻底破产": "遭受可见的阶段性损失", "彻底崩塌": "在本阶段明显受损",
        "彻底失败": "本轮失败", "永久失去": "在本阶段失去",
        "永久记录": "写入正式记录", "完全归": "主要权利归",
        "完全掌控": "取得明确控制权", "绝对支持": "明确支持",
        "完美保护": "形成可执行保护", "一劳永逸": "解决当前问题",
    }.items():
        value = value.replace(old, new)
    return value


def affected_resource(cost_type: str) -> str:
    return {
        "opportunity": "曝光与商业窗口", "information": "信息优势与隐蔽性",
        "relationship": "盟友信任与共同决策", "health_time": "健康与演出排期",
        "strategic": "资源部署与主线主动权", "setback": "当前清算进度",
    }.get(cost_type, "主角资源与关系")


def integrate_cost(index: int, event: dict[str, Any], card_map: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    cost = event.get("protagonist_cost")
    if not isinstance(cost, dict) or not cost.get("required"):
        return None
    eid = str(event["cluster_id"])
    cost_id = str(cost.get("cost_id") or f"COST_{eid}_A")
    cost_type = str(cost.get("type") or "strategic")
    description = str(cost.get("description") or "胜利留下了仍需承担的现实代价。")
    recovery = str(cost.get("recovery_condition") or "在后续现场通过可验证动作完成恢复")
    agency = str(cost.get("agency") or ("opponent_forced" if cost_type == "setback" else "chosen"))
    cost.update({
        "cost_id": cost_id, "agency": agency,
        "chosen_by_protagonist": agency == "chosen",
        "status": "active", "start_chapter": index * 2,
        "minimum_persistence_chapters": 3,
    })
    affected = affected_resource(cost_type)
    next_clusters = [f"EC{number:03d}" for number in range(index + 1, min(250, index + 2) + 1)]
    event["residual_problem"] = {
        "cost_id": cost_id,
        "concrete_state": description,
        "affected_resource": affected,
        "must_affect_next_clusters": next_clusters,
        "resolution_condition": recovery,
    }
    event["villain_loss"] = soften_absolutes(event.get("villain_loss"))
    event["protagonist_gain"] = soften_absolutes(event.get("protagonist_gain"))
    event["relationship_change"] = soften_absolutes(event.get("relationship_change"))
    event["cluster_outcome"] = (
        f"{event['protagonist_gain']}；但{description}。该结果保留了“{affected}”上的后续压力，"
        f"须满足“{recovery}”后才能结清。"
    )
    finale = (event.get("two_chapter_structure") or [{}, {}])[1]
    cost_scene = f"结算落地后，{description}；这一后果在离场时仍未恢复。"
    visible = soften_absolutes(finale.get("visible_payoff"))
    finale["visible_payoff"] = visible if cost_scene in visible else visible + cost_scene
    finale["ending"] = cost_scene + f"恢复条件是：{recovery}。"
    synopsis = str(finale.get("detailed_synopsis") or "")
    finale["detailed_synopsis"] = synopsis if cost_scene in synopsis else synopsis + cost_scene
    finale["must_include"] = list(dict.fromkeys((finale.get("must_include") or []) + [cost_scene]))
    finale_card = card_map[index * 2]
    finale_card["cluster_outcome"] = event["cluster_outcome"]
    finale_card["core_payoff"] = event["cluster_outcome"]
    finale_card["immediate_payoff"] = finale["visible_payoff"]
    finale_card["chapter_ending"] = finale["ending"]
    finale_card["detailed_synopsis"] = finale["detailed_synopsis"]
    finale_card["chapter_must_include"] = list(dict.fromkeys(finale.get("must_include") or []))
    finale_card["state_transitions"] = [
        item for item in finale_card.get("state_transitions") or []
        if not (isinstance(item, dict) and item.get("state_key") == cost_id)
    ]
    finale_card.setdefault("state_transitions", []).append({
        "domain": "cost", "entity_id": "CHAR_026AC753E27A", "state_key": cost_id,
        "from": "inactive", "to": "active", "irreversible": False,
        "evidence": description, "effect_type": "protagonist_cost",
        "type": cost_type, "description": description, "persists": True,
        "recovery_condition": recovery,
    })
    resolution_chapter = min(500, index * 2 + 6)
    cost["planned_resolution_chapter"] = resolution_chapter
    for chapter_id in range(index * 2 + 1, resolution_chapter + 1):
        card = card_map[chapter_id]
        active = [item for item in card.get("active_costs") or [] if item.get("cost_id") != cost_id]
        active.append({
            "cost_id": cost_id, "source_cluster": eid, "type": cost_type,
            "description": description, "status": "active", "start_chapter": index * 2,
            "minimum_persistence_chapters": 3, "recovery_condition": recovery,
        })
        card["active_costs"] = active
    resolution_card = card_map[resolution_chapter]
    resolution = {
        "cost_id": cost_id, "status": "resolved", "resolution_condition": recovery,
        "required_visible_evidence": f"通过现场动作证明：{recovery}",
    }
    resolution_card["cost_resolutions"] = [
        item for item in resolution_card.get("cost_resolutions") or []
        if not (isinstance(item, dict) and item.get("cost_id") == cost_id)
    ]
    resolution_card.setdefault("cost_resolutions", []).append(resolution)
    resolution_card.setdefault("chapter_must_include", []).append(resolution["required_visible_evidence"])
    resolution_card["state_transitions"] = [
        item for item in resolution_card.get("state_transitions") or []
        if not (isinstance(item, dict) and item.get("state_key") == cost_id)
    ]
    resolution_card.setdefault("state_transitions", []).append({
        "domain": "cost", "entity_id": "CHAR_026AC753E27A", "state_key": cost_id,
        "from": "active", "to": "resolved", "irreversible": False,
        "evidence": resolution["required_visible_evidence"], "effect_type": "cost_resolution",
    })
    resolution_event = event_by_chapter(card_map, resolution_chapter)
    resolution_event["cost_resolutions"] = [
        item for item in resolution_event.get("cost_resolutions") or []
        if not (isinstance(item, dict) and item.get("cost_id") == cost_id)
    ]
    resolution_event.setdefault("cost_resolutions", []).append(resolution)
    return {"cost_id": cost_id, "source_cluster": eid, "resolution_chapter": resolution_chapter}


def event_by_chapter(card_map: dict[int, dict[str, Any]], chapter_id: int) -> dict[str, Any]:
    # Replaced at runtime with the authoritative lookup in ``repair``.
    return EVENT_LOOKUP[str(card_map[chapter_id]["cluster_id"])]


EVENT_LOOKUP: dict[str, dict[str, Any]] = {}


def flaw_integration(event: dict[str, Any], registry: dict[str, dict[str, Any]], alias_to_id: dict[str, str]) -> dict[str, Any] | None:
    flaw = event.get("character_flaw_beat")
    if not isinstance(flaw, dict):
        return None
    required = ("trigger", "protagonist_action", "immediate_benefit", "hidden_cost", "who_pushes_back", "future_payoff_cluster")
    missing = [field for field in required if not str(flaw.get(field) or "").strip()]
    who = str(flaw.get("who_pushes_back") or "").strip()
    cid = alias_to_id.get(who)
    canonical = registry[cid]["canonical_name"] if cid in registry else who
    flaw["who_pushes_back"] = canonical
    event.setdefault("main_characters", [])
    if canonical and canonical not in event["main_characters"]:
        event["main_characters"].append(canonical)
    if cid:
        event.setdefault("main_character_ids", [])
        if cid not in event["main_character_ids"]:
            event["main_character_ids"].append(cid)
        if not any(str(member.get("character_id")) == cid for member in event.get("canonical_cast") or [] if isinstance(member, dict)):
            row = registry[cid]
            event.setdefault("canonical_cast", []).append({
                "name": row["canonical_name"], "display_name": row["canonical_name"],
                "aliases": row["aliases"], "role": row["role"],
                "alignment": row["alignment"], "character_id": cid,
            })
    milestones = event.get("two_chapter_structure") or []
    target = milestones[1] if len(milestones) == 2 else None
    if target is not None:
        target.setdefault("participants", [])
        if canonical and canonical not in target["participants"]:
            target["participants"].append(canonical)
        action = f"{canonical}当场指出：{flaw.get('hidden_cost')}；麦珂必须回应而不能把冲突拖到章尾补写。"
        target["action_sequence"] = list(dict.fromkeys((target.get("action_sequence") or []) + [action]))
        synopsis = str(target.get("detailed_synopsis") or "")
        target["detailed_synopsis"] = synopsis if action in synopsis else synopsis + action
        ending = str(target.get("ending") or "")
        target["ending"] = ending if action in ending else ending + action
    return {"cluster_id": event.get("cluster_id"), "who": canonical, "missing_fields": missing}


def migrate_irreversible(item: dict[str, Any]) -> bool:
    if not item.get("irreversible"):
        return False
    text = " ".join(str(item.get(key) or "") for key in ("domain", "state_key", "to", "evidence", "effect_type"))
    allowed = (
        "死亡", "身故", "所有权正式转移", "版权正式转移", "母带所有权", "不可撤销信托",
        "资产出售完成", "最终裁判", "终审判决", "正式注销", "公司注销",
    )
    if any(token in text for token in allowed):
        return False
    item["irreversible"] = False
    item["irreversible_migration_reason"] = "temporary_or_reversible_state_v13"
    return True


def artifact_contract(artifact: dict[str, Any], chapter_id: int, participants: list[str]) -> None:
    kind = str(artifact.get("kind") or "record")
    scope_by_kind = {
        "contract": ["terms", "signatures", "rights_explicitly_listed"],
        "agreement": ["terms", "signatures", "rights_explicitly_listed"],
        "recording": ["captured_audio", "time_and_speaker_evidence"],
        "document": ["documented_facts", "provenance"],
        "report": ["reported_findings", "named_method"],
        "ledger": ["recorded_transactions", "custody_chain"],
        "key": ["physical_access_to_named_container"],
    }
    scope = scope_by_kind.get(kind, ["documented_content_only"])
    grants = {
        "contract": ["use_as_evidence_within_scope", "enforce_explicit_terms"],
        "agreement": ["use_as_evidence_within_scope", "enforce_explicit_terms"],
        "key": ["use_as_evidence_within_scope", "open_named_container"],
        "authorization": ["use_as_evidence_within_scope", "perform_explicitly_authorized_action"],
    }.get(kind, ["use_as_evidence_within_scope"])
    artifact.update({
        "created_at": chapter_id,
        "signers": list(dict.fromkeys(participants[:3])) if kind in {"contract", "agreement", "authorization"} else [],
        "scope": artifact.get("scope") or scope,
        "granted_permissions": list(dict.fromkeys((artifact.get("granted_permissions") or []) + grants)),
        "does_not_grant": artifact.get("does_not_grant") or [
            "freeze_funds", "dismiss_staff", "expand_technical_access", "override_medical_consent",
        ],
        "authority_source": artifact.get("authority_source") or "本章具备相应权限的签署、制作或保管主体",
        "expires_at": artifact.get("expires_at"),
    })


def classify_signature(event: dict[str, Any]) -> dict[str, str]:
    text = " ".join(str(event.get(key) or "") for key in (
        "fictional_obstacle", "preemptive_avoidance", "bait_and_evidence", "villain_loss",
        "protagonist_gain", "cluster_outcome", "relationship_change",
    ))
    def choose(groups: Iterable[tuple[str, tuple[str, ...]]], default: str) -> str:
        return next((label for label, words in groups if any(word in text for word in words)), default)
    return {
        "attack_domain": choose((
            ("legal_document", ("合同", "条款", "起诉", "公证")),
            ("medical", ("医疗", "药", "心电", "健康")),
            ("technical", ("设备", "线路", "频率", "录音")),
            ("media", ("媒体", "报道", "广播", "舆论")),
            ("finance", ("资金", "账户", "税", "保险")),
            ("physical_security", ("闯入", "破坏", "盗", "安保")),
        ), str(event.get("event_type") or "other")),
        "counter_method": choose((
            ("preexisting_document", ("原件", "副本", "条款", "账簿")),
            ("witness_chain", ("证人", "见证", "当场记录")),
            ("technical_redundancy", ("备份", "备用", "复核", "校准")),
            ("public_disclosure", ("公开", "直播", "刊登", "播出")),
            ("procedural_delay", ("暂停", "延期", "复议", "听证")),
            ("delegated_authority", ("共同签字", "授权", "选择权", "交给")),
        ), str(event.get("solution_type") or "other")),
        "resolver": choose((
            ("court", ("法官", "法庭", "裁决")), ("press", ("记者", "媒体", "广播")),
            ("committee", ("委员会", "听证", "审计")), ("team", ("团队", "同盟", "家人")),
            ("audience", ("观众", "歌迷", "公众")),
        ), "direct_parties"),
        "publicity": choose((("public", ("公开", "直播", "公众", "头版")), ("limited", ("内部", "闭门", "私下"))), "private"),
        "hero_gain_type": choose((
            ("new_right", ("权利", "所有权", "授权")), ("evidence", ("证据", "记录", "原件")),
            ("resource", ("资金", "设备", "渠道")), ("relationship", ("信任", "关系", "共同")),
            ("safety", ("安全", "健康", "保护")),
        ), "progress"),
    }


def death_step(event: dict[str, Any]) -> dict[str, str]:
    role = str(event.get("death_chain_role") or "echo")
    previous = str(event.get("why_previous_life_failed") or event.get("prev_life_tragedy") or "此前只知道结果，不知道完整责任链。")
    new_fact = str(event.get("info_gap_from_prev_life") or event.get("bait_and_evidence") or event.get("cluster_outcome") or "本簇补充一项可核验事实。")
    meaning = str(event.get("source_event_direction") or event.get("this_life_revenge") or event.get("preemptive_avoidance") or "该事实改变对2009年死亡利益链的理解。")
    question = str(event.get("next_event_hook") or "这项事实将把责任链指向谁？")
    return {
        "role": role, "previous_known_fact": previous[:600],
        "new_fact_this_cluster": new_fact[:600], "meaning_change": meaning[:600],
        "future_question": question[:500],
    }


FINAL_EVIDENCE_CHAIN: dict[int, dict[str, Any]] = {
    238: {
        "name": "广告预付款：活人尚在，悼念已经成交", "scene": "永恒星光广告结算室",
        "domain": "finance", "counter": "payment_ledger", "resolver": "independent_accountant",
        "artifact": "纪念直播广告预付款回单与退款触发条款",
        "setup_title": "先到账的悼念费", "finale_title": "退款条款里的死亡日期",
        "setup": "广告代理人在没有死亡确认的情况下提前划付纪念直播首期款，苏菲亚只保全银行回单与经手人口头指令，不接触直播信号。",
        "finale": "独立会计师把付款日、合同生效条件和预填死亡日期并列封存，证明商业方在医学结论前已按麦珂死亡结算；团队选择继续隐身。",
    },
    239: {
        "name": "纪念专辑：压片厂收到一份未发生的死讯", "scene": "北岸唱片压片厂夜班线",
        "domain": "copyright", "counter": "manufacturing_order", "resolver": "factory_witnesses",
        "artifact": "纪念专辑压片工单、母版领取单与夜班签收簿",
        "setup_title": "提前开动的压片机", "finale_title": "母版领取人",
        "setup": "压片厂按奥瑞恩密令提前生产纪念专辑，艾琳让夜班工人照常登记领料人、数量与开机时刻，不偷换母版也不惊动管理层。",
        "finale": "工厂见证人封存领取单，确认纪念母版在死亡确认前由巴里的人取走；麦珂放弃立刻叫停生产，以换取完整责任链。",
    },
    240: {
        "name": "广播封锁：三十七份同词讣告的源头", "scene": "午夜星轨短波交换台",
        "domain": "media", "counter": "routing_log", "resolver": "station_engineers",
        "artifact": "三十七地讣告播出指令与短波路由值班簿",
        "setup_title": "同一句悼词", "finale_title": "路由簿上的源台",
        "setup": "各地电台同时收到完全相同的讣告播出词，工程师不反播真假消息，只记录指令抵达时刻、源台编号与校验口令。",
        "finale": "路由值班簿证明封锁命令来自奥瑞恩主控而非医院；艾琳拒绝提前插播麦珂声音，保住第499章首次公开现身。",
    },
    241: {
        "name": "场馆门禁：谁在替一个活人封锁出口", "scene": "穹顶会场西侧装卸门",
        "domain": "physical_security", "counter": "mechanical_access_log", "resolver": "venue_union",
        "artifact": "机械门禁打卡带与安保换岗命令原件",
        "setup_title": "西门提前上锁", "finale_title": "换岗命令的签发人",
        "setup": "卡尔要求提前封闭麦珂可能进入的通道，场馆工会按旧规留下机械打卡带；莱昂只复制换岗命令，不破坏门锁。",
        "finale": "工会代表确认封门发生在正式哀悼前，且目的不是安全而是阻止活人进入自己的纪念；团队保留一条合法开放的维修通道。",
    },
    242: {
        "name": "版权紧急授权：尚未死亡便开始转签", "scene": "奥瑞恩版权清算办公室",
        "domain": "legal_document", "counter": "signature_sequence", "resolver": "rights_custodian",
        "artifact": "紧急版权授权签署顺序表与权利保管人异议书",
        "setup_title": "空着的死亡证明编号", "finale_title": "先签的受让方",
        "setup": "法务要求权利保管人在死亡证明编号仍为空时先盖授权章，黛安娜让其按真实顺序登记每次递交和退回。",
        "finale": "异议书证明受让方先签、死亡条件后补，紧急授权因此只能作为主观明知证据，不能反过来冻结全部版权。",
    },
    243: {
        "name": "死亡证明：医生拒绝替时间倒签", "scene": "圣玛丽亚医院病案室",
        "domain": "medical", "counter": "paper_chart_chain", "resolver": "independent_physicians",
        "artifact": "纸质病历出入库卡、死亡证明草稿与医师拒签记录",
        "setup_title": "病案室的空白时刻", "finale_title": "拒绝倒签的人",
        "setup": "康拉德派人索取病历并要求预填死亡时刻，值班医师坚持先看原始体征页，在出入库卡上留下索取人的签名。",
        "finale": "三名独立医师共同封存拒签记录，证明医疗文件被商业直播倒逼；麦珂仍不露面，也不让医生替他宣布胜利。",
    },
    244: {
        "name": "董事会明知：庆功会先于死亡确认", "scene": "奥瑞恩集团董事会餐厅",
        "domain": "governance", "counter": "meeting_minutes", "resolver": "board_secretary",
        "artifact": "纪念收益庆功会席位表、会议纪要与删改页",
        "setup_title": "尚未发生的庆功会", "finale_title": "被撕下的纪要页",
        "setup": "维克多召集小范围庆功会分配纪念收益，董事会秘书按职责记录每个人对死亡、保险和版权接管的发言。",
        "finale": "巴里试图撕掉含有‘死亡确认稍后补齐’的纪要页，缺页编号与在场秘书证词反而锁定集团高层主观明知。",
    },
    245: {
        "name": "误判闭环：让维克多亲手确认全部开关", "scene": "永恒星光总控室外观察间",
        "domain": "strategic", "counter": "decision_ledger", "resolver": "distributed_team",
        "artifact": "讣告、保险、版权、广告与门禁五线启动清单",
        "setup_title": "反派的胜利", "finale_title": "倒计时归零前",
        "setup": "维克多逐项确认五条商业与控制链已经启动，分散在不同岗位的团队成员各自记录自己能合法见证的一项，不共享越权信息。",
        "finale": "麦珂把五线证据按因果而非声量排序，拒绝瑟琳娜提出的提前露面方案，让对手的主观明知完整走到不可抵赖的位置。",
    },
    246: {
        "name": "讣告制版：印刷机留下最早的死亡版本", "scene": "晨报联合制版间",
        "domain": "media", "counter": "printing_plate", "resolver": "press_foreman",
        "artifact": "讣告铅版、校样编号和制版间交接簿",
        "setup_title": "凌晨前的讣告铅版", "finale_title": "校样编号早了六小时",
        "setup": "报业联盟在医院尚未签字时收到完整讣告，领班按工序保留第一版铅版和每次改稿校样，不接受苏菲亚撤版要求。",
        "finale": "校样编号与交接簿锁定讣告由巴里提前六小时投送；苏菲亚选择保留出版行为而不在报纸上提前揭底。",
    },
    247: {
        "name": "药物指令：口头加速令找到经手链", "scene": "康复室药房与气送管道站",
        "domain": "medical", "counter": "dispensing_chain", "resolver": "pharmacy_reviewers",
        "artifact": "配药批号、气送筒签收单与口头指令复述记录",
        "setup_title": "多出的那一支药", "finale_title": "口头指令的第二个听见者",
        "setup": "药房发现配药批号比医嘱多一支，复核员让送药人与接收护士分别复述口头加速令，未把可疑药物送入麦珂管路。",
        "finale": "气送筒签收单与两份独立复述把康拉德的指令接回维克多办公室来电，形成医疗责任链而非只证明麦珂仍活着。",
    },
    248: {
        "name": "保险受益：理赔款先流向谁", "scene": "联合保险清算中心",
        "domain": "finance", "counter": "beneficiary_trace", "resolver": "claims_auditors",
        "artifact": "预启动理赔流水、受益账户变更单与资产接管清单",
        "setup_title": "尚未生效的理赔款", "finale_title": "受益账户的回流路径",
        "setup": "保险清算员被要求在死亡证明到达前预启动理赔，审计员保留原始受益账户版本，追出资金将回流奥瑞恩关联实体。",
        "finale": "变更单和资产接管清单证明保险并非善后而是收购资金来源；团队冻结的是争议付款，不借一张保单夺取其他权限。",
    },
    249: {
        "name": "纪念商品与版权：最后一份主观明知证据", "scene": "永恒星光商品仓与版权总控台",
        "domain": "copyright", "counter": "inventory_and_approval_chain", "resolver": "warehouse_and_rights_witnesses",
        "artifact": "纪念商品出库单、版权切换批准页与高层批注原件",
        "setup_title": "活人姓名下的遗物标签", "finale_title": "最后一枚批准章",
        "setup": "仓库开始给麦珂仍在使用的物品贴遗物标签，管理员保留出库单；版权总控台同时收到切换全部授权的批准页。",
        "finale": "高层批注写明‘先完成销售，医学手续随后’，把商品收益、版权接管和主观明知接成最后一环；团队只完成封存，门仍留给第499章。",
    },
}


def rewrite_final_evidence_chain(events: list[dict[str, Any]]) -> None:
    for index, spec in FINAL_EVIDENCE_CHAIN.items():
        event = events[index - 1]
        event["name"] = spec["name"]
        event["fictional_obstacle"] = spec["setup"]
        event["preemptive_avoidance"] = (
            f"由{spec['resolver']}按自身权限保全{spec['artifact']}；麦珂团队不越权制造证据，"
            "也不在第499章之前公开麦珂本人。"
        )
        event["bait_and_evidence"] = spec["finale"]
        event["villain_loss"] = f"对手在{spec['domain']}链留下关于“{spec['artifact']}”的可核验事实，但尚未接受终局公开审判。"
        event["protagonist_gain"] = f"取得并分散保管{spec['artifact']}，只推进一条证据链，不提前消费终局现身。"
        event["relationship_change"] = f"{spec['resolver']}从流程执行者变为独立见证者；麦珂接受证据由他人保管。"
        event["cluster_outcome"] = spec["finale"]
        event["resolution_signature"] = {
            "attack_domain": spec["domain"], "counter_method": spec["counter"],
            "resolver": spec["resolver"], "publicity": "private",
            "hero_gain_type": "evidence_chain",
        }
        milestones = event.get("two_chapter_structure") or []
        for offset, milestone in enumerate(milestones[:2]):
            text = spec["setup"] if offset == 0 else spec["finale"]
            title = spec["setup_title"] if offset == 0 else spec["finale_title"]
            milestone["chapter_title"] = title
            milestone["chapter_goal"] = text
            milestone["scene"] = spec["scene"]
            milestone["scenes"] = [{
                "sequence": 1, "location": spec["scene"], "is_primary": True,
                "temporal_mode": "current", "transition_cue": "进入本簇唯一取证现场",
            }]
            milestone["opening_conflict"] = text
            milestone["info_gap_use"] = "麦珂知道对手会把死亡确认与商业动作倒置，因此要求见证人记录真实先后顺序。"
            milestone["opponent_reaction"] = "对手把团队的克制误判为无力反抗，继续完成本簇唯一的错误动作。"
            milestone["action_sequence"] = [
                text,
                f"{spec['resolver']}核对并封存{spec['artifact']}。",
                "团队明确拒绝公开麦珂本人，也不重复上一簇的取证手段。",
            ]
            milestone["visible_payoff"] = text
            milestone["ending"] = (
                "证据交给独立保管人，麦珂继续留在镜头外。"
                if offset == 0 else "本链闭合，但第499章之前现场仍无人确认麦珂会出现。"
            )
            milestone["must_include"] = [spec["artifact"], spec["scene"], "麦珂未公开现身"]
            milestone["must_not_include"] = ["麦珂走入直播现场", "维克多接受终局审判", "所有责任一次结清"]
            milestone["detailed_synopsis"] = text + " 全章只完成这一条证据链，不复用通用的‘锁定原始证据’模板。"
            artifact_id = f"ART_{int(milestone.get('chapter_id') or 0):03d}_FINAL_CHAIN"
            milestone["artifact_creates"] = [{
                "artifact_id": artifact_id, "timeline_scope": "current",
                "display_name": spec["artifact"], "kind": "document",
            }]
            milestone["artifact_refs"] = []


def normalized_story(card: dict[str, Any]) -> str:
    value = " ".join(str(card.get(key) or "") for key in (
        "chapter_goal", "detailed_synopsis", "exact_action_sequence", "immediate_payoff", "chapter_ending",
    ))
    for boilerplate in (
        "麦珂未公开现身", "团队明确拒绝公开麦珂本人", "不在第499章之前公开麦珂本人",
        "不复用通用的锁定原始证据模板", "本链闭合", "只完成这一条证据链",
        "生成正文时必须把本章的可观察动作人物选择现实代价和章节结算写成现场行为",
        "不能用抽象的信任升级或标志着一笔带过", "结尾必须让读者看见具体的选择代价和收益",
    ):
        value = value.replace(boilerplate, "")
    return re.sub(r"[^\u3400-\u9fffA-Za-z0-9]", "", value)


def ngrams(text: str, size: int = 4) -> set[str]:
    return {text[index:index + size] for index in range(max(0, len(text) - size + 1))}


def repetition_audit(cards: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    texts = {int(card["chapter_id"]): normalized_story(card) for card in cards}
    exact: dict[str, list[int]] = defaultdict(list)
    for chapter_id, text in texts.items():
        exact[hashlib.sha256(text.encode("utf-8")).hexdigest()].append(chapter_id)
    exact_groups = [ids for ids in exact.values() if len(ids) > 1]
    same_cluster = []
    for event in events:
        left, right = map(int, event["chapter_span"])
        ratio = SequenceMatcher(None, texts[left], texts[right], autojunk=False).ratio()
        if ratio >= 0.42:
            same_cluster.append({"cluster_id": event["cluster_id"], "chapters": [left, right], "similarity": round(ratio, 4)})
    sets = {chapter_id: ngrams(text) for chapter_id, text in texts.items()}
    high_pairs = []
    for left in range(1, 501):
        for right in range(left + 1, 501):
            if right == left + 1 and (left + 1) % 2 == 0:
                continue
            a, b = sets[left], sets[right]
            overlap = len(a & b) / len(a | b) if a and b else 0.0
            if overlap < 0.19:
                continue
            ratio = SequenceMatcher(None, texts[left], texts[right], autojunk=False).ratio()
            if ratio >= 0.45:
                high_pairs.append({"chapters": [left, right], "ngram_jaccard": round(overlap, 4), "sequence_similarity": round(ratio, 4)})
    high_pairs.sort(key=lambda item: (item["sequence_similarity"], item["ngram_jaccard"]), reverse=True)
    signature_windows = []
    for start in range(0, len(events) - 9):
        bucket: dict[str, list[str]] = defaultdict(list)
        for event in events[start:start + 10]:
            core = {key: event["resolution_signature"][key] for key in (
                "attack_domain", "counter_method", "resolver", "publicity", "hero_gain_type",
            )}
            bucket[canonical_json(core)].append(event["cluster_id"])
        for signature, ids in bucket.items():
            if len(ids) >= 3:
                signature_windows.append({"window": [events[start]["cluster_id"], events[start + 9]["cluster_id"]], "clusters": ids, "core_signature": json.loads(signature)})
    unique_windows = {canonical_json(item): item for item in signature_windows}
    return {
        "exact_duplicate_chapter_groups": exact_groups,
        "same_cluster_high_similarity": same_cluster,
        "cross_cluster_high_similarity": high_pairs[:100],
        "repeated_resolution_signature_windows": list(unique_windows.values()),
    }


def sync_card_from_milestone(card: dict[str, Any], event: dict[str, Any], milestone: dict[str, Any]) -> None:
    mapping = {
        "chapter_title": "chapter_title", "chapter_goal": "chapter_goal",
        "chapter_ending": "ending", "detailed_synopsis": "detailed_synopsis",
        "scene_location": "scene", "scenes": "scenes", "participants": "participants",
        "exact_action_sequence": "action_sequence", "info_gap_use": "info_gap_use",
        "opponent_reaction": "opponent_reaction", "immediate_payoff": "visible_payoff",
        "chapter_must_include": "must_include", "chapter_must_not_include": "must_not_include",
        "artifact_creates": "artifact_creates", "artifact_refs": "artifact_refs",
    }
    for target, source in mapping.items():
        if source in milestone:
            card[target] = deepcopy(milestone[source])
    card["cluster_name"] = event.get("name")
    card["cluster_outcome"] = event.get("cluster_outcome")
    card["core_payoff"] = event.get("cluster_outcome")
    card["canonical_cast"] = deepcopy(event.get("canonical_cast") or [])
    card["allowed_roles"] = list(dict.fromkeys((card.get("participants") or []) + (card.get("allowed_roles") or [])))
    card["source_milestone_sha256"] = digest(milestone)
    card["source_event_sha256"] = digest(event)


def repair(events: list[dict[str, Any]], cards: list[dict[str, Any]], synopses: list[dict[str, Any]], outline: dict[str, Any], bible: dict[str, Any]) -> dict[str, Any]:
    events[:] = repair_protagonist_pronouns(walk_replace(events, REAL_WORLD_REPLACEMENTS))
    cards[:] = repair_protagonist_pronouns(walk_replace(cards, REAL_WORLD_REPLACEMENTS))
    synopses[:] = repair_protagonist_pronouns(walk_replace(synopses, REAL_WORLD_REPLACEMENTS))
    outline.clear(); outline.update(repair_protagonist_pronouns(walk_replace(load(OUTLINE_PATH), REAL_WORLD_REPLACEMENTS)))
    bible.clear(); bible.update(repair_protagonist_pronouns(walk_replace(load(BIBLE_PATH), REAL_WORLD_REPLACEMENTS)))
    registry_rows, registry, alias_to_id = build_registry(events)
    outline["canonical_character_registry"] = registry_rows
    outline["fictional_entity_registry"] = {
        "cities": ["河湾镇", "海湾城"],
        "institutions": ["国家调查署", "广播频谱管理局", "奥瑞恩集团", "星火同盟"],
        "technology_brands": ["奥瑞恩电动排字机"],
        "policy": "正文具名实体必须来自章卡、人物注册表或本虚构实体注册表。",
    }
    outline["era_technology_matrix"] = {
        "1969-1979": ["纸质文件", "有线电话", "磁带录音", "模拟广播", "机械/电动打字机"],
        "1980-1989": ["模拟与早期数字录音", "传真", "短波副载波", "离线计算设备"],
        "1990-1999": ["固定电话", "传真", "实体介质", "封闭式数字工作站"],
        "2000-2009": ["受限网络传输", "数字存档", "直播系统"],
        "forbidden_anachronisms": ["1969互联网", "1969电子邮件", "1969手机", "1998现代流媒体平台"],
    }
    outline["opponent_policy"] = (
        "opposition_type=villain时允许一次推动因果的讽刺性失误，但不得要求每次狼狈或滑稽；"
        "主要反派必须具备合理目标、真实能力或可理解恐惧。"
    )
    bible["canonical_character_registry"] = registry_rows
    rewrite_final_evidence_chain(events)
    card_map = {int(card["chapter_id"]): card for card in cards}
    global EVENT_LOOKUP
    EVENT_LOOKUP = {str(event["cluster_id"]): event for event in events}
    for card in cards:
        card["character_lifecycle"] = lifecycle(card)
    irreversible_changed = 0
    flaw_results = []
    for index, event in enumerate(events, start=1):
        event["outcome_type"] = outcome_for(index, event)
        if index not in FINAL_EVIDENCE_CHAIN:
            event["resolution_signature"] = deepcopy(
                RESOLUTION_SIGNATURE_OVERRIDES.get(str(event.get("cluster_id")))
                or classify_signature(event)
            )
        event["death_chain_step"] = death_step(event)
        event.setdefault("opponent_humanizing_beat", {
            "reasonable_goal_or_fear": f"{event.get('main_opponent') or '阻力方'}试图保住其既有资源、职责或安全感。",
            "competence": "阻力方至少能利用本簇已有流程、关系或技术资源造成现实压力。",
            "satirical_mistake_limit": "至多一次，且必须推动证据或因果链。",
        })
        canonicalize_cast(event, registry)
        flaw = flaw_integration(event, registry, alias_to_id)
        if flaw:
            flaw_results.append(flaw)
        for transition in event.get("state_transitions") or []:
            if isinstance(transition, dict) and migrate_irreversible(transition):
                irreversible_changed += 1
        for milestone in event.get("two_chapter_structure") or []:
            chapter_id = int(milestone.get("chapter_id") or 0)
            participants = [str(item) for item in milestone.get("participants") or []]
            for artifact in milestone.get("artifact_creates") or []:
                if isinstance(artifact, dict):
                    artifact_contract(artifact, chapter_id, participants)
            for ref in milestone.get("artifact_refs") or []:
                if isinstance(ref, dict):
                    ref.setdefault("required_permission", "use_as_evidence_within_scope")
                    ref.setdefault("scope_assertion", "不得超出创建时的granted_permissions")
    costs = []
    for index, event in enumerate(events, start=1):
        result = integrate_cost(index, event, card_map)
        if result:
            costs.append(result)
    # Cost/flaw edits changed milestones; now compile every card from its event.
    for event in events:
        canonicalize_cast(event, registry)
        for milestone in event.get("two_chapter_structure") or []:
            card = card_map[int(milestone["chapter_id"])]
            sync_card_from_milestone(card, event, milestone)
            card["character_lifecycle"] = lifecycle(card)
            participants = [str(item) for item in card.get("participants") or []]
            for artifact in card.get("artifact_creates") or []:
                if isinstance(artifact, dict):
                    artifact_contract(artifact, int(card["chapter_id"]), participants)
            for ref in card.get("artifact_refs") or []:
                if isinstance(ref, dict):
                    ref.setdefault("required_permission", "use_as_evidence_within_scope")
                    ref.setdefault("scope_assertion", "不得超出创建时的granted_permissions")
            for transition in card.get("state_transitions") or []:
                if isinstance(transition, dict) and migrate_irreversible(transition):
                    irreversible_changed += 1
    # Synopses follow the compiled authoritative cards but omit runtime lifecycle/cost state.
    synopsis_map = {int(card["chapter_id"]): card for card in synopses}
    for chapter_id, card in card_map.items():
        target = synopsis_map[chapter_id]
        preserved = {key: target.get(key) for key in ()}
        target.clear(); target.update(deepcopy(card)); target.update(preserved)
        target.pop("character_lifecycle", None)
        target.pop("active_costs", None)
        target.pop("cost_resolutions", None)
    # Refresh hashes one final time after all event-level cost resolution writes.
    for event in events:
        for milestone in event.get("two_chapter_structure") or []:
            card = card_map[int(milestone["chapter_id"])]
            card["source_milestone_sha256"] = digest(milestone)
            card["source_event_sha256"] = digest(event)
    return {
        "canonical_registry_count": len(registry_rows),
        "irreversible_flags_lowered": irreversible_changed,
        "cost_states": costs,
        "flaw_integrations": flaw_results,
    }


def validate(events: list[dict[str, Any]], cards: list[dict[str, Any]], outline: dict[str, Any]) -> dict[str, Any]:
    failures = []
    if len(events) != 250 or len(cards) != 500:
        failures.append(f"数量错误：events={len(events)}, cards={len(cards)}")
    card_map = {int(card["chapter_id"]): card for card in cards}
    age_mismatches = []
    for chapter_id in range(1, 501):
        card = card_map.get(chapter_id)
        if not card:
            failures.append(f"缺少第{chapter_id}章")
            continue
        life = card.get("character_lifecycle") or {}
        expected = age_at(card.get("timeline_start") or card.get("timeline_years"))
        if life.get("current_age") != expected:
            age_mismatches.append({"chapter_id": chapter_id, "expected": expected, "actual": life.get("current_age")})
    missing_outcomes = [event["cluster_id"] for event in events if event.get("outcome_type") not in OUTCOMES]
    victory_failures = []
    for start in range(0, 243):
        window = events[start:start + 8]
        non_clean = sum(event["outcome_type"] != "clean_win" for event in window)
        if non_clean < 2:
            victory_failures.append(f"{window[0]['cluster_id']}-{window[-1]['cluster_id']} non_clean={non_clean}")
    for start in range(0, 239):
        window = events[start:start + 12]
        large = sum(event["outcome_type"] in {"major_win", "decisive_win"} for event in window)
        if large > 2:
            victory_failures.append(f"{window[0]['cluster_id']}-{window[-1]['cluster_id']} major/decisive={large}")
    flaw_failures = []
    for event in events:
        flaw = event.get("character_flaw_beat")
        if not isinstance(flaw, dict):
            continue
        who = str(flaw.get("who_pushes_back") or "")
        participants = set(map(str, event.get("main_characters") or []))
        for milestone in event.get("two_chapter_structure") or []:
            participants.update(map(str, milestone.get("participants") or []))
        if who not in participants:
            flaw_failures.append(f"{event['cluster_id']}:{who}")
    cost_failures = []
    for event in events:
        cost = event.get("protagonist_cost")
        if not isinstance(cost, dict) or not cost.get("persists"):
            continue
        cost_id = str(cost.get("cost_id") or "")
        start = int(cost.get("start_chapter") or 0)
        end = int(cost.get("planned_resolution_chapter") or 0)
        if not cost_id or end - start < 3:
            cost_failures.append(f"{event['cluster_id']}:invalid-contract")
            continue
        missing = [chapter for chapter in range(start + 1, end + 1) if cost_id not in {str(item.get('cost_id')) for item in card_map[chapter].get('active_costs') or []}]
        if missing:
            cost_failures.append(f"{event['cluster_id']}:missing-active-{missing}")
        if cost_id not in {str(item.get("cost_id")) for item in card_map[end].get("cost_resolutions") or []}:
            cost_failures.append(f"{event['cluster_id']}:missing-resolution")
    real_world_hits = {}
    payloads = {"outline": outline, "events": events, "cards": cards}
    for label, payload in payloads.items():
        text = canonical_json(payload)
        hits = [token for token in REAL_WORLD_REPLACEMENTS if token in text]
        if hits:
            real_world_hits[label] = hits
    failures.extend(f"年龄错误:{item}" for item in age_mismatches)
    failures.extend(f"缺outcome:{item}" for item in missing_outcomes)
    failures.extend(f"victory budget:{item}" for item in victory_failures)
    failures.extend(f"flaw参与者:{item}" for item in flaw_failures)
    failures.extend(f"cost持续:{item}" for item in cost_failures)
    failures.extend(f"现实专名:{label}={hits}" for label, hits in real_world_hits.items())
    return {
        "passed": not failures, "failures": failures,
        "metrics": {
            "events": len(events), "cards": len(cards),
            "ages_correct": len(cards) - len(age_mismatches),
            "explicit_outcomes": len(events) - len(missing_outcomes),
            "cost_clusters": sum(bool(event.get("protagonist_cost")) for event in events),
            "flaw_clusters": sum(bool(event.get("character_flaw_beat")) for event in events),
            "resolution_signatures": sum(bool(event.get("resolution_signature")) for event in events),
            "death_chain_steps": sum(bool(event.get("death_chain_step")) for event in events),
            "artifact_contracts": sum(len(card.get("artifact_creates") or []) for card in cards),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    events = load(EVENTS_PATH)
    cards = load(CARDS_PATH)
    synopses = load(SYNOPSES_PATH)
    outline = load(OUTLINE_PATH)
    bible = load(BIBLE_PATH)
    before = {path.name: digest(value) for path, value in (
        (EVENTS_PATH, events), (CARDS_PATH, cards), (SYNOPSES_PATH, synopses),
        (OUTLINE_PATH, outline), (BIBLE_PATH, bible),
    )}
    migration = repair(events, cards, synopses, outline, bible)
    validation = validate(events, cards, outline)
    repetition = repetition_audit(cards, events)
    report = {
        "version": "v13_full_plan_identity_lifecycle_cost_scope_20260822",
        "mode": "apply" if args.apply else "audit",
        "before_sha256": before,
        "after_sha256": {path.name: digest(value) for path, value in (
            (EVENTS_PATH, events), (CARDS_PATH, cards), (SYNOPSES_PATH, synopses),
            (OUTLINE_PATH, outline), (BIBLE_PATH, bible),
        )},
        "migration": migration, "validation": validation, "repetition_audit": repetition,
    }
    if args.apply:
        for path in (EVENTS_PATH, CARDS_PATH, SYNOPSES_PATH, OUTLINE_PATH, BIBLE_PATH):
            backup = path.with_name(path.stem + ".pre_v13_20260822" + path.suffix)
            if not backup.exists():
                shutil.copy2(path, backup)
        atomic_write(EVENTS_PATH, events)
        atomic_write(CARDS_PATH, cards)
        atomic_write(SYNOPSES_PATH, synopses)
        atomic_write(OUTLINE_PATH, outline)
        atomic_write(BIBLE_PATH, bible)
    atomic_write(args.report.resolve(), report)
    print(json.dumps({
        "applied": args.apply, "passed": validation["passed"],
        "metrics": validation["metrics"], "failure_count": len(validation["failures"]),
        "exact_duplicate_groups": len(repetition["exact_duplicate_chapter_groups"]),
        "same_cluster_high_similarity": len(repetition["same_cluster_high_similarity"]),
        "cross_cluster_high_similarity": len(repetition["cross_cluster_high_similarity"]),
        "repeated_signature_windows": len(repetition["repeated_resolution_signature_windows"]),
        "report": str(args.report.resolve()),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Build an isolated event/card/synopsis package for EC136—EC178.

The formal plan remains untouched until this candidate package passes review.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from bert_excitation_train.scripts.v2.pop_king_plan_compiler import canonical_sha256


NAME_MAP = {
    "黛安娜·陈": "黛安娜·罗文", "瑟琳娜·王": "瑟琳娜·凯德", "瑟琳娜·刘": "瑟琳娜·凯德", "瑟琳娜·麦凯": "瑟琳娜·凯德",
    "维克多·斯特林": "维克多·兰斯", "苏菲亚·沃克": "苏菲亚·罗德里格斯", "昆廷·哈特": "昆廷·琼斯", "卡尔·斯特林": "卡尔·霍尔特",
}
ID_MAP = {
    "CHAR_B24EF2E733C9": "CHAR_B24EF2E733C9", "CHAR_EC7C1E1EB46F": "CHAR_EC7C1E1EB46F",
    "CHAR_76E9E8359211": "CHAR_76E9E8359211", "CHAR_87B8E75FFF6F": "CHAR_87B8E75FFF6F",
    "CHAR_9577B35020B0": "CHAR_9577B35020B0", "CHAR_3F11D9A42EDF": "CHAR_3F11D9A42EDF",
}
ROSTER = [
    ("麦珂·杰森", "CHAR_026AC753E27A"), ("黛安娜·罗文", "CHAR_B24EF2E733C9"),
    ("艾琳·沃特曼", "CHAR_8C6A51D4E9F2"), ("瑟琳娜·凯德", "CHAR_EC7C1E1EB46F"),
    ("维克多·兰斯", "CHAR_76E9E8359211"), ("苏菲亚·罗德里格斯", "CHAR_87B8E75FFF6F"),
    ("卡尔·霍尔特", "CHAR_3F11D9A42EDF"), ("昆廷·琼斯", "CHAR_9577B35020B0"),
]


def replace_names(value):
    if isinstance(value, str):
        for old, new in NAME_MAP.items():
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [replace_names(x) for x in value]
    if isinstance(value, dict):
        return {key: replace_names(item) for key, item in value.items()}
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    candidate = out / "body_generation" / "rewrite_candidate_plan_EC136_EC178"
    candidate.mkdir(parents=True, exist_ok=True)
    events = json.loads((out / "event_clusters_v2.json").read_text(encoding="utf-8"))
    cards = json.loads((out / "master_ctx_cards_v2.json").read_text(encoding="utf-8"))
    synopses_path = out / "chapter_synopses_v5_qwen_500.json"
    synopses = json.loads(synopses_path.read_text(encoding="utf-8")) if synopses_path.is_file() else []
    rewrite = json.loads((out / "body_generation" / "rewrite_plan_EC136_EC178.json").read_text(encoding="utf-8"))
    by_id = {x["cluster_id"]: x for x in rewrite["items"]}
    event_copy = copy.deepcopy(events)
    card_copy = copy.deepcopy(cards)
    for event_index, event in enumerate(event_copy):
        eid = str(event.get("cluster_id") or "")
        if not (136 <= int(eid[2:]) <= 178):
            continue
        plan = by_id[eid]
        event.update({
            "status": "rewrite_candidate",
            "timeline_years": "1993",
            "canonical_cast": [{"name": name, "display_name": name, "character_id": cid, "aliases": [name, name.split("·")[0]], "role": "fixed_character_bible"} for name, cid in ROSTER],
            "main_character_ids": [ROSTER[0][1], ROSTER[1][1], ROSTER[2][1], ROSTER[3][1]],
            "main_characters": [ROSTER[0][0], ROSTER[1][0], ROSTER[2][0], ROSTER[3][0]],
            "main_opponent": "卡尔·霍尔特",
            "main_opponent_character_id": "CHAR_3F11D9A42EDF",
            "main_opponent_character_ids": ["CHAR_3F11D9A42EDF"],
            "structure_signature": plan["structure_signature"],
            "irreplaceable_progress_point": plan["irreplaceable_progress_point"],
            "next_event_hook": f"下一簇承接{plan['structure_signature']['reward']}后的新问题，不重复本簇授权边界。",
        })
        event = replace_names(event)
        event["source_event_direction_sha256"] = hashlib.sha256(str(plan["irreplaceable_progress_point"]).encode("utf-8")).hexdigest()
        event_copy[event_index] = event
    for card_index, card in enumerate(card_copy):
        cid = int(card.get("chapter_id") or 0)
        if not 271 <= cid <= 356:
            continue
        eid = f"EC{(cid + 1) // 2:03d}"
        if eid not in by_id:
            continue
        plan = by_id[eid]
        card.update({
            "status": "rewrite_candidate",
            "cluster_name": plan["irreplaceable_progress_point"],
            "timeline_years": "1993",
            "timeline_start": "1993-09-12" if cid <= 272 else "1993-09-13",
            "timeline_end": "1993-09-12" if cid <= 272 else "1993-09-13",
            "chapter_title": f"第{cid}章：{plan['conflict_domain']}的边界",
            "chapter_goal": plan["irreplaceable_progress_point"],
            "chapter_must_include": [plan["conflict_domain"], plan["structure_signature"]["key_artifact"], plan["structure_signature"]["authority"]],
            "chapter_must_not_include": ["ART_", "__extension_EC", "永久定罪", "全息投影"],
            "scene_location": "河湾镇档案馆收发室" if cid <= 272 else "维斯特媒介公司合同会议室",
            "participants": [name for name, _ in ROSTER[:4]] + ["卡尔·霍尔特"],
            "main_opponent": "卡尔·霍尔特",
            "canonical_cast": [{"name": name, "display_name": name, "character_id": cid2, "aliases": [name, name.split("·")[0]], "role": "fixed_character_bible"} for name, cid2 in ROSTER],
            "allowed_roles": [],
            "chapter_role_v2": "two_chapter_setup_and_win" if cid % 2 else "two_chapter_payoff",
            "detailed_synopsis": plan["irreplaceable_progress_point"],
            "info_gap_use": "麦珂记得前世的失败节点，但只把记忆转成可检查的问题。",
            "immediate_payoff": plan["settlement_layer"],
        })
        card = replace_names(card)
        card["source_event_sha256"] = canonical_sha256(next(x for x in event_copy if x.get("cluster_id") == eid))
        card["source_milestone_sha256"] = canonical_sha256({"cluster_id": eid, "chapter_id": cid, "candidate": True, "point": plan["irreplaceable_progress_point"]})
        card_copy[card_index] = card
    # Keep the complete 500-item shape for downstream review tooling.
    (candidate / "event_clusters_v2.json").write_text(json.dumps(event_copy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (candidate / "master_ctx_cards_v2.json").write_text(json.dumps(card_copy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (candidate / "chapter_synopses_v5_qwen_500.json").write_text(json.dumps(synopses, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (candidate / "PACKAGE_STATUS.json").write_text(json.dumps({"status": "candidate_only", "formal_files_mutated": False, "range": [136, 178], "fixed_identity_source": "CHARACTER_BIBLE"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(candidate)


if __name__ == "__main__":
    main()

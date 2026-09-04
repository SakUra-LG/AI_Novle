import argparse
import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(path, data):
    fd, name = tempfile.mkstemp(prefix=path.stem + "_", suffix=".json", dir=path.parent)
    os.close(fd)
    temp = Path(name)
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        json.loads(temp.read_text(encoding="utf-8"))
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("architecture", type=Path)
    parser.add_argument("synopses", type=Path)
    parser.add_argument("clusters", type=Path)
    args = parser.parse_args()

    architecture = json.loads(args.architecture.read_text(encoding="utf-8"))
    all_chapter_ids = [int(ch["id"]) for cluster in architecture for ch in cluster["chapters"]]
    range_label = f"{min(all_chapter_ids):03d}_{max(all_chapter_ids):03d}"
    synopses = json.loads(args.synopses.read_text(encoding="utf-8"))
    synopsis_by_id = {int(item["chapter_id"]): item for item in synopses}

    for cluster in architecture:
        locations = cluster["location"].split("／")
        for index, chapter_plan in enumerate(cluster["chapters"]):
            chapter = synopsis_by_id[int(chapter_plan["id"])]
            is_first = index == 0
            location = locations[min(index, len(locations) - 1)]
            detailed = "。".join([
                cluster["obstacle"], chapter_plan["goal"],
                cluster["cost"] if is_first else cluster["outcome"],
                chapter_plan["ending"],
            ]).replace("。。", "。")
            chapter.update({
                "chapter_title": chapter_plan["title"],
                "timeline_years": cluster["date"][:4],
                "timeline_start": cluster["date"],
                "timeline_end": cluster["date"],
                "chapter_role_v2": "two_chapter_setup_and_win" if is_first else "two_chapter_resolution",
                "structure_template": "MANUAL_FAMILY_MUSIC_EVENT_V18",
                "chapter_goal": chapter_plan["goal"],
                "chapter_must_include": chapter_plan["must"],
                "chapter_must_not_include": [
                    "用律师念法条代替人物选择", "把乔纳写成纯粹小丑或突然洗白",
                    "非麦珂人物拥有前世记忆", "把一次胜利写成关系永久治愈",
                ],
                "chapter_ending": chapter_plan["ending"],
                "must_resolve_this_chapter": [] if is_first else [cluster["outcome"]],
                "detailed_synopsis": detailed,
                "scene_location": location,
                "scenes": [{
                    "sequence": 1, "location": location, "is_primary": True,
                    "temporal_mode": "current", "transition_cue": chapter_plan["goal"],
                }],
                "artifact_creates": [],
                "artifact_refs": [],
                "participants": cluster["participants"],
                "allowed_roles": cluster["participants"],
                "forbidden_roles": ["未铺垫的终极反派", "万能律师", "突然出现的神秘证人"],
                "exact_action_sequence": [
                    cluster["obstacle"], chapter_plan["goal"],
                    cluster["cost"] if is_first else cluster["outcome"],
                ],
                "info_gap_use": cluster.get("info_gap_use", "前世记忆只让麦珂警惕控制与透支，今生必须通过可观察行动重新判断。"),
                "opponent_reaction": cluster.get("opponent_reaction", "阻力方把真实机会、金钱压力与控制权捆绑，局面反转后仍须承担具体损失。"),
                "immediate_payoff": chapter_plan["ending"] if is_first else cluster["outcome"],
                "state_changes": [],
                "state_transitions": [],
                "core_payoff": cluster["outcome"],
                "cluster_outcome": cluster["outcome"],
                "main_opponent": cluster["opponent"],
                "prev_life_tragedy": cluster.get("prev_life_tragedy", "前世麦珂把厂牌、媒体和观众的期待都当成必须服从的命令，逐步失去创作与人生决定权。"),
                "info_gap_from_prev_life": cluster.get("info_gap_from_prev_life", "麦珂记得伤害方向与关键话术，但不能预知今生所有事实，证据与选择必须在当下形成。"),
                "this_life_revenge": chapter_plan["goal"],
                "romance_state": cluster.get("romance_state", "关系线服务于人物边界，不用一次胜利宣告永久治愈。"),
                "target_chinese_chars": 1200,
                "generated_by": "manual_rearchitecture",
                "compiled_by": f"v18_manual_rearchitecture_{range_label}_20260829",
                "manual_edits": [cluster.get("manual_edit", "replace repetitive procedural takedowns with music, performance, public image, and real-cost choices")],
                "planning_version": f"v18_manual_rearchitecture_{range_label}_20260829",
            })

    clusters_raw = json.loads(args.clusters.read_text(encoding="utf-8"))
    cluster_list = clusters_raw
    if isinstance(clusters_raw, dict):
        cluster_list = clusters_raw.get("event_clusters", clusters_raw.get("clusters", clusters_raw.get("data", [])))
    cluster_by_id = {item["cluster_id"]: item for item in cluster_list}
    for cluster in architecture:
        item = cluster_by_id[cluster["cluster_id"]]
        item.update({
            "name": cluster["name"],
            "chapter_span": cluster["span"],
            "timeline_years": cluster["date"][:4],
            "main_opponent": cluster["opponent"],
            "fictional_obstacle": cluster["obstacle"],
            "preemptive_avoidance": cluster["chapters"][0]["goal"],
            "bait_and_evidence": cluster.get("bait_and_evidence", "不靠万能证据翻盘；用公开作品、现场选择、真实账目和具名证言限定责任。"),
            "comic_villain_behavior": cluster.get("comic_villain_behavior", "对手把控制包装成机会，因急于抢功或定性而留下可公开核验的矛盾。"),
            "villain_loss": cluster["outcome"],
            "protagonist_gain": cluster["outcome"],
            "relationship_change": cluster.get("relationship_change", "麦珂与合作者在真实分歧中重划边界，胜利不自动修复关系。"),
            "cluster_outcome": f"{cluster['outcome']}；同时承担：{cluster['cost']}。结果不外推为亲情永久修复。",
            "next_event_hook": cluster["next_hook"],
        })

    atomic_write_json(args.synopses, synopses)
    atomic_write_json(args.clusters, clusters_raw)
    print(json.dumps({
        "chapters_updated": [min(all_chapter_ids), max(all_chapter_ids)],
        "count": len(all_chapter_ids),
        "clusters_updated": [architecture[0]["cluster_id"], architecture[-1]["cluster_id"]],
        "cluster_count": len(architecture),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

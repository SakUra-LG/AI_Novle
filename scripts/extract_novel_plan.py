from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("synopses", type=Path)
    parser.add_argument("clusters", type=Path)
    parser.add_argument("--chapters", required=True)
    parser.add_argument("--mode", choices=("map", "detail"), default="detail")
    args = parser.parse_args()
    lo, hi = (int(v) for v in args.chapters.split("-", 1))
    synopses = json.loads(args.synopses.read_text(encoding="utf-8"))
    clusters = json.loads(args.clusters.read_text(encoding="utf-8"))
    by_chapter = {int(item["chapter_id"]): item for item in synopses}
    by_cluster = {item["cluster_id"]: item for item in clusters}

    if args.mode == "map":
        payload = []
        for chapter in range(lo, hi + 1):
            item = by_chapter[chapter]
            payload.append({
                "chapter_id": chapter,
                "title": item.get("chapter_title"),
                "date": item.get("timeline_start"),
                "cluster_id": item.get("cluster_id"),
                "goal": item.get("chapter_goal"),
                "ending": item.get("chapter_ending") or item.get("chapter_ending"),
            })
    else:
        payload = []
        cluster_ids = []
        for chapter in range(lo, hi + 1):
            item = by_chapter[chapter]
            cluster_ids.append(item.get("cluster_id"))
            payload.append({
                "chapter_id": chapter,
                "chapter_title": item.get("chapter_title"),
                "timeline_start": item.get("timeline_start"),
                "timeline_end": item.get("timeline_end"),
                "cluster_id": item.get("cluster_id"),
                "chapter_goal": item.get("chapter_goal"),
                "scene_location": item.get("scene_location"),
                "participants": item.get("participants"),
                "must_include": item.get("chapter_must_include"),
                "must_not_include": item.get("chapter_must_not_include"),
                "action_sequence": item.get("exact_action_sequence"),
                "opponent_reaction": item.get("opponent_reaction"),
                "payoff": item.get("immediate_payoff"),
                "ending": item.get("chapter_ending"),
                "synopsis": item.get("detailed_synopsis"),
            })
        cluster_payload = []
        for cluster_id in dict.fromkeys(cluster_ids):
            cluster = by_cluster.get(cluster_id, {})
            cluster_payload.append({
                "cluster_id": cluster_id,
                "name": cluster.get("name"),
                "chapter_span": cluster.get("chapter_span"),
                "timeline_years": cluster.get("timeline_years"),
                "main_opponent": cluster.get("main_opponent"),
                "fictional_obstacle": cluster.get("fictional_obstacle"),
                "preemptive_avoidance": cluster.get("preemptive_avoidance"),
                "bait_and_evidence": cluster.get("bait_and_evidence"),
                "comic_villain_behavior": cluster.get("comic_villain_behavior"),
                "villain_loss": cluster.get("villain_loss"),
                "protagonist_gain": cluster.get("protagonist_gain"),
                "relationship_change": cluster.get("relationship_change"),
                "cluster_outcome": cluster.get("cluster_outcome"),
                "next_event_hook": cluster.get("next_event_hook"),
            })
        payload = {"chapters": payload, "clusters": cluster_payload}
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

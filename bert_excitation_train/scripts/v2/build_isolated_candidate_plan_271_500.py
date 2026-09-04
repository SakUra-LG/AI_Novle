from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs_pop_king_v6_compiled_story_first_500"
BASE = OUT / "body_generation"

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def main() -> None:
    cluster_by_span = {}
    for f in BASE.glob("rewrite_trial_*/EC*_candidate_cards.json"):
        data = read_json(f)
        span = tuple(int(x) for x in data.get("chapter_span", []))
        if not span:
            span = tuple(int(x.get("chapter_id")) for x in data.get("chapter_cards", [])[:2])
        if span == (271, 272) or span == (273, 274):
            continue
        if 275 <= (span[0] if span else 0) <= 499:
            cluster_by_span[span] = (data, f)
    plan_file = BASE / "rewrite_trial_271_274" / "trial_plan_ec136_ec137.json"
    trial = read_json(plan_file)
    events = []
    cards = []
    for raw in trial["event_clusters"][:2]:
        event = {"cluster_id": raw["cluster_id"], "chapter_span": raw["chapter_span"], "status": "candidate_only", "formal_promotion": False, "story_memory_write": False, "neo4j_write": False, "conflict_domain": "来源与授权链" if raw["cluster_id"] == "EC136" else "档案访问权限", "irreplaceable_progress_point": raw["irreplaceable_progress_point"], "structure_signature": {"conflict_type": "source_authorization_trace" if raw["cluster_id"] == "EC136" else "permission_scope_review", "attack_method": "incomplete_chain_is_treated_as_conclusion", "counter_method": "match_register_transfer_and_authority", "key_artifact": "BA-83-11 and CR-41 records", "authority": "档案馆与项目资料室", "reward": raw["irreplaceable_progress_point"], "relationship_change": "麦珂坚持按证据范围行动"}, "main_character_ids": raw["main_character_ids"], "participant_ids": raw["participant_ids"]}
        events.append(event)
        for spec in raw["chapter_specs"]:
            cards.append({"chapter_id": spec["chapter_id"], "event_cluster_id": raw["cluster_id"], "timeline_start": spec["date"], "timeline_end": spec["date"], "goal": spec["progress"], "turning_choice": "按责任链继续核对", "status": "candidate_only", "formal_promotion": False})
    for span, (data, source) in sorted(cluster_by_span.items()):
        event = {k: data[k] for k in ("cluster_id", "chapter_span", "conflict_domain", "irreplaceable_progress_point", "structure_signature", "main_character_ids", "participant_ids") if k in data}
        event.setdefault("chapter_span", list(span))
        event.update({"status":"candidate_only", "formal_promotion":False, "story_memory_write":False, "neo4j_write":False, "source_candidate_card":str(source.relative_to(OUT))})
        events.append(event)
        for card in data.get("chapter_cards", []):
            c = dict(card)
            c.update({"event_cluster_id": data["cluster_id"], "status":"candidate_only", "formal_promotion":False, "source_candidate_card":str(source.relative_to(OUT))})
            cards.append(c)
    events.sort(key=lambda x: int(x["cluster_id"][2:]))
    cards.sort(key=lambda x: int(x["chapter_id"]))
    synopses = [{"chapter_id": c["chapter_id"], "event_cluster_id": c["event_cluster_id"], "timeline_start": c.get("timeline_start"), "timeline_end": c.get("timeline_end"), "synopsis": c.get("goal", "") + "；" + c.get("turning_choice", ""), "status":"candidate_only"} for c in cards]
    report = {"status":"candidate_only", "formal_promotion":False, "story_memory_write":False, "neo4j_write":False, "external_semantic_critic":"not_run", "continuity_anchor":{"formal_last_chapter":270,"formal_last_date":"1993-09-17"}, "event_clusters":events, "chapter_cards":cards, "chapter_synopses":synopses}
    (OUT / "isolated_candidate_plan_271_500.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"events":len(events),"cards":len(cards),"synopses":len(synopses),"status":report["status"]}, ensure_ascii=False))

if __name__ == "__main__":
    main()

from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs_pop_king_v6_compiled_story_first_500"

def walk_replace(value, replacements):
    if isinstance(value, dict):
        return {k: walk_replace(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [walk_replace(v, replacements) for v in value]
    if isinstance(value, str):
        for old, new in replacements:
            value = value.replace(old, new)
    return value

cards_path = OUT / "master_ctx_cards_v2.json"
cards = json.loads(cards_path.read_text(encoding="utf-8"))
for index, card in enumerate(cards):
    chapter = int(card.get("chapter_id") or 0)
    if chapter in (201, 202):
        cards[index] = walk_replace(card, [("1986-12-21", "1987-03-14")])
        card = cards[index]
    if chapter in (207, 208):
        for key in ("info_gap_use", "detailed_synopsis", "chapter_goal"):
            if isinstance(card.get(key), str):
                card[key] = card[key].replace("苏菲亚利用重生记忆", "麦珂利用重生记忆，并让苏菲亚执行")
    if chapter in (209, 210):
        for key in ("info_gap_use", "detailed_synopsis", "chapter_goal"):
            if isinstance(card.get(key), str):
                card[key] = card[key].replace("苏菲亚利用前世记忆", "麦珂利用前世记忆，并让苏菲亚执行")
    if chapter == 210:
        cards[index] = walk_replace(cards[index], [("1989年6月20日", "1991年10月21日"), ("1989-06-20", "1991-10-21")])
cards_path.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")

events_path = OUT / "event_clusters_v2.json"
events = json.loads(events_path.read_text(encoding="utf-8"))
for event in events:
    if event.get("cluster_id") == "EC105":
        event["timeline_years"] = "1989—1991"
        event["name"] = event.get("name", "").replace("1987", "1989")
events_path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")

for chapter in (205, 206):
    path = OUT / "chapters" / f"chapter_{chapter:03d}.txt"
    text = path.read_text(encoding="utf-8")
    text = text.replace("她清楚记得前世莉薇娅因为一次误触而遭受的羞辱，所以这一次", "麦珂提前提醒她，莉薇娅曾因一次误触遭受羞辱，所以这一次")
    text = text.replace("她记得前世莉薇娅因为一次误触而遭受的羞辱，所以这一次", "麦珂提前提醒她，莉薇娅曾因一次误触遭受羞辱，所以这一次")
    path.write_text(text, encoding="utf-8", newline="\n")

print("manual S-level planning/body repair applied for 201-210")

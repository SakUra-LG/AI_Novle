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
    if chapter == 201:
        cards[index] = walk_replace(card, [
            ("医生、经纪人、技术总监", "医疗负责人、经纪人、技术负责人"),
            ("‘医生、经纪人、技术总监’", "‘医疗负责人、经纪人、技术负责人’"),
            ("1987年3月14日 03:00", "1987年3月14日 03:14"),
        ])
    if chapter == 209:
        cards[index] = walk_replace(card, [("1987年3月15日", "1989年7月15日"), ("1987-03-15", "1989-07-15")])
        cards[index]["timeline_years"] = "1989"
    if chapter in (211, 212):
        cards[index] = walk_replace(card, [
            ("1987-11-15", "1991-10-22" if chapter == 211 else "1991-10-23"),
            ("1987-11-16", "1991-10-23"),
            ("1987年11月15日", "1991年10月22日"),
            ("1987年11月16日", "1991年10月23日"),
            ("莉薇娅", "苏菲亚"),
            ("苏菲亚医生", "苏菲亚"),
        ])
        cards[index]["timeline_years"] = "1991"
        if chapter == 212:
            cards[index] = walk_replace(cards[index], [("1991-10-23", "1991-10-22"), ("1991年10月23日", "1991年10月22日")])
        unique_cast = []
        seen_ids = set()
        for item in cards[index].get("canonical_cast", []):
            key = item.get("character_id") or json.dumps(item, ensure_ascii=False)
            if key == "CHAR_89E90D63A7E8":
                continue
            if key not in seen_ids:
                unique_cast.append(item); seen_ids.add(key)
        cards[index]["canonical_cast"] = unique_cast
    if chapter in (203, 204):
        cards[index] = walk_replace(cards[index], [("莉薇娅", "苏菲亚")])
        cards[index]["participants"] = [v for v in cards[index].get("participants", []) if v != "莉薇娅"]
        cards[index]["canonical_cast"] = [
            item for item in cards[index].get("canonical_cast", [])
            if item.get("character_id") != "CHAR_89E90D63A7E8"
        ]
    if chapter in (207, 208):
        for key in ("info_gap_use", "detailed_synopsis", "chapter_goal"):
            if isinstance(card.get(key), str):
                card[key] = card[key].replace("苏菲亚利用重生记忆", "麦珂利用重生记忆，并让苏菲亚执行")
    if chapter in (209, 210):
        for key in ("info_gap_use", "detailed_synopsis", "chapter_goal"):
            if isinstance(card.get(key), str):
                card[key] = card[key].replace("苏菲亚利用前世记忆", "麦珂利用前世记忆，并让苏菲亚执行")
    # 203章之后莉薇娅已死亡；后续行动只能由苏菲亚执行，不能让已死亡角色
    # 继续出现在参与者、卡司或当前时态的情节中。
    if chapter in (205, 206, 207, 208, 209, 210):
        cards[index] = walk_replace(cards[index], [("莉薇娅", "苏菲亚")])
        cards[index]["participants"] = [v for v in cards[index].get("participants", []) if v != "莉薇娅"]
        cards[index]["canonical_cast"] = [
            item for item in cards[index].get("canonical_cast", [])
            if item.get("character_id") != "CHAR_89E90D63A7E8"
        ]
        if chapter in (205, 206, 207, 208):
            cards[index]["timeline_years"] = "1989"
        for key in ("detailed_synopsis", "info_gap_use", "chapter_goal"):
            if isinstance(cards[index].get(key), str):
                cards[index][key] = cards[index][key].replace("十一岁", "三十一岁").replace("十二岁", "三十二岁")
    if chapter == 210:
        cards[index] = walk_replace(card, [
            ("1989年6月20日", "1991年10月21日"),
            ("1989 年 6 月 20 日", "1991 年 10 月 21 日"),
            ("1989-06-20", "1991-10-21"),
            ("1989/06/20", "1991/10/21"),
        ])
        cards[index]["timeline_years"] = "1991"
cards_path.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")

events_path = OUT / "event_clusters_v2.json"
events = json.loads(events_path.read_text(encoding="utf-8"))
for index, event in enumerate(events):
    if event.get("cluster_id") == "EC105":
        events[index] = walk_replace(event, [("1987—1989", "1987—1991"), ("1989年6月20日", "1991年10月21日")])
    if event.get("cluster_id") == "EC106":
        events[index] = walk_replace(event, [
            ("1987—1988", "1991"),
            ("1987年11月", "1991年10月"),
            ("1987-11-15", "1991-10-22"),
            ("莉薇娅", "苏菲亚"),
        ])
        unique_cast = []
        seen_ids = set()
        for item in events[index].get("canonical_cast", []):
            key = item.get("character_id") or json.dumps(item, ensure_ascii=False)
            if key == "CHAR_89E90D63A7E8":
                continue
            if key not in seen_ids:
                unique_cast.append(item); seen_ids.add(key)
        events[index]["main_character_ids"] = [
            value for value in events[index].get("main_character_ids", [])
            if value != "CHAR_89E90D63A7E8"
        ]
        events[index]["canonical_cast"] = unique_cast
    if event.get("cluster_id") == "EC102":
        events[index] = walk_replace(event, [("莉薇娅", "苏菲亚")])
        events[index]["canonical_cast"] = [
            item for item in events[index].get("canonical_cast", [])
            if item.get("character_id") != "CHAR_89E90D63A7E8"
        ]
        events[index]["main_character_ids"] = [
            value for value in events[index].get("main_character_ids", [])
            if value != "CHAR_89E90D63A7E8"
        ]
    if event.get("cluster_id") in {"EC103", "EC104", "EC105"}:
        events[index] = walk_replace(events[index], [("莉薇娅", "苏菲亚")])
        events[index]["canonical_cast"] = [
            item for item in events[index].get("canonical_cast", [])
            if item.get("character_id") != "CHAR_89E90D63A7E8"
        ]
        events[index]["main_character_ids"] = [
            value for value in events[index].get("main_character_ids", [])
            if value != "CHAR_89E90D63A7E8"
        ]
events_path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")

for chapter in (205, 206):
    path = OUT / "chapters" / f"chapter_{chapter:03d}.txt"
    text = path.read_text(encoding="utf-8")
    text = text.replace("她清楚记得前世莉薇娅因为一次误触而遭受的羞辱，所以这一次", "麦珂提前提醒她，莉薇娅曾因一次误触遭受羞辱，所以这一次")
    text = text.replace("她记得前世莉薇娅因为一次误触而遭受的羞辱，所以这一次", "麦珂提前提醒她，莉薇娅曾因一次误触遭受羞辱，所以这一次")
    path.write_text(text, encoding="utf-8", newline="\n")

path = OUT / "chapters" / "chapter_201.txt"
text = path.read_text(encoding="utf-8")
text = text.replace(
    "她没有说话，只是默默地在“医生”那一栏签下了名字，虽然她并非专业医师，但在这种生死关头，她的签字代表的是母亲的绝对权威。",
    "她没有冒充医生，而是在“监护人／家属见证”一栏签下名字；这份签字确认的是知情、陪同和紧急联络，不是医疗判断。",
)
text = text.replace("医生、经纪人、技术总监，缺一不可", "医疗负责人、经纪人、技术负责人，缺一不可")
text = text.replace("1987年3月14日 03:00", "1987年3月14日 03:14")
path.write_text(text, encoding="utf-8", newline="\n")

path = OUT / "chapters" / "chapter_210.txt"
text = path.read_text(encoding="utf-8")
text = text.replace(
    "却发现自己手中的起诉书早已被苏菲亚替换成了伪造的“自愿放弃版权声明”。",
    "却发现自己手中的起诉书早已被一份来历不明的“自愿放弃版权声明”替换；苏菲亚当场指出了文件编号、见证签名和卷宗登记不一致。",
)
text = text.replace(
    "法官敲响了法槌，声音沉闷而有力，仿佛一锤定音：“奥瑞恩集团未能提供有效证据证明其主张，反而被证实存在伪造证据、恶意诉讼的行为。”",
    "法官敲响了法槌，声音沉闷而有力，仿佛一锤定音：“奥瑞恩集团未能提供有效证据证明其主张，反而被证实提交了来源不明、登记不一致的材料，存在恶意诉讼的行为。”",
)
path.write_text(text, encoding="utf-8", newline="\n")

print("manual S-level planning/body repair applied for 201-210")

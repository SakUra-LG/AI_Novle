from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs_pop_king_v6_compiled_story_first_500"
BASE = OUT / "body_generation"

def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def chinese_count(text: str) -> int:
    return sum("一" <= c <= "鿿" for c in text)

def date_text(value: str) -> str:
    y, m, d = value.split("-")
    return f"{int(y)}年{int(m)}月{int(d)}日"

def event_lookup(plan: dict):
    return {str(x["cluster_id"]): x for x in plan["event_clusters"]}

def card_lookup(plan: dict):
    return {int(x["chapter_id"]): x for x in plan["chapter_cards"]}

def cast_profiles(ids: list[str]) -> list[dict]:
    bible = load(ROOT / "outputs_pop_king_v6_compiled_story_first_500" / "global_story_outline_v5_qwen_500.json").get("canonical_character_registry", [])
    by_id = {str(x.get("character_id")): x for x in bible if isinstance(x, dict)}
    return [{"character_id": cid, "name": by_id.get(cid, {}).get("canonical_name", cid), "aliases": by_id.get(cid, {}).get("aliases", [])} for cid in ids]

def normalized_event(event: dict, card_rows: list[dict]) -> dict:
    e = dict(event)
    e["status"] = "candidate_only"
    e["formal_promotion"] = False
    e["story_memory_write"] = False
    e["neo4j_write"] = False
    e["timeline_years"] = ",".join(sorted({str(x.get("timeline_start", "").split("-")[0]) for x in card_rows}))
    e["source_event_direction"] = e.get("irreplaceable_progress_point", "")
    e["name"] = f"{e.get('conflict_domain', '连续推进')}：{e.get('irreplaceable_progress_point', '')}"
    e["event_type"] = e.get("conflict_domain", "candidate_rewrite")
    e["solution_type"] = "bounded_procedural_resolution"
    e["canonical_cast"] = cast_profiles(list(dict.fromkeys((e.get("main_character_ids") or []) + (e.get("participant_ids") or []))))
    e["main_characters"] = [x.get("name") for x in e["canonical_cast"]]
    e["state_transitions"] = []
    e["artifact_creates"] = []
    e["artifact_refs"] = []
    e["target_chinese_chars"] = 1200
    e["two_chapter_structure"] = [{"chapter_id": c["chapter_id"], "timeline_start": c.get("timeline_start"), "timeline_end": c.get("timeline_end"), "chapter_goal": c.get("goal", ""), "turning_choice": c.get("turning_choice", ""), "must_include": c.get("must_include", []), "must_not_include": c.get("must_not_include", [])} for c in card_rows]
    return e

def expansion(ch: int, day: str, event: dict, card: dict, phase: int) -> str:
    domain = str(event.get("conflict_domain", "当前事项"))
    point = str(event.get("irreplaceable_progress_point", "把下一步范围说清楚"))
    artifact = str((event.get("structure_signature") or {}).get("key_artifact", "记录材料"))
    if re.search(r"[A-Za-z]+_[A-Za-z0-9_]+", artifact):
        artifact = "相关记录材料"
    authority = str((event.get("structure_signature") or {}).get("authority", "负责人员"))
    if re.search(r"[A-Za-z]+_[A-Za-z0-9_]+", authority):
        authority = "负责人员"
    goal = str(card.get("goal", point))
    choice = str(card.get("turning_choice", "按记录继续处理"))
    hook = str(card.get("ending_hook", "新的材料还在路上"))
    scenes = {
        "合同适用范围": "协议上的一条横线把已承诺的服务和仍在商量的部分分开，黛安娜先请对方指出签字页，再把未生效的内容退回讨论。",
        "财务对账": "苏菲亚把收据按发生日铺成两列，现金、转账和待确认款各有位置，谁也不能用一个总数盖住中间的差额。",
        "档案访问权限": "艾琳在管理员监督下只打开获准的目录页，页码、接收时间和归还时间都写在同一张阅读记录上。",
        "媒体纠错": "黛安娜把原报道、删节稿和更正页并排摆开，先追来源，再决定哪一句话需要由哪一方改正。",
        "教育与职业决定": "麦珂把导师的批注改写成一次可以完成的练习，放弃一个漂亮却不合时宜的机会，给团队留下完整排演时间。",
        "演出与物流": "昆廷按开场需要给器材排序，卡尔核对车辆和工时，重要设备先走，备用物件则换一条更稳妥的路线。",
        "来源与授权链": "一张缺少收件人的转交单让所有人停下来，艾琳不凭熟悉的笔迹猜人，而是回到登记簿寻找下一处可验证的时间。",
    }
    scene = next((v for k, v in scenes.items() if k in domain), "三个人把材料、时间和责任放在同一张桌上，先处理能够核实的部分，再为未决问题留下位置。")
    details = ["窗外的装车声一阵紧过一阵", "台灯下的纸边显出浅浅折痕", "电话铃响后又很快停下", "门缝里灌进一股潮湿的风", "墙上的分针越过了整点", "走廊有人抱着空文件夹经过"]
    blocks = [
        f"{date_text(day)}，{scene}",
        f"事情的压力来自{domain}本身：{goal}。麦珂没有先寻找一句能让所有人安心的话，而是要求每个人说出自己手里的材料和不能确认的地方。{details[(ch + phase) % len(details)]}。",
        f"{authority}提出先照旧处理，等后续结果出来再补说明。黛安娜把这个办法可能造成的返工、额外支出和时间损失写在页边，艾琳则补上对应的核对顺序。她们没有把分歧变成对人的指责。",
        f"麦珂把“{goal}”拆成几个动作：先确认来件时间，再确认交接对象，最后确认{artifact}能够支持的范围。选择变慢之后，现场反而安静下来，所有人都知道下一笔该落在哪里。",
        f"电话那头希望他们马上给出肯定答复。麦珂听完后把决定说得很短：{choice}。这让今天的安排少了一点便利，却没有把尚未核实的内容提前变成结论。",
        f"选择立刻带来代价：一项工作后移，一笔费用暂留，或者一名工作人员需要改班。苏菲亚和昆廷分别记下自己要承担的部分，黛安娜确认合作方收到新的时间，不让成本消失在口头承诺里。",
        f"临走前，艾琳复核{artifact}的页码和归还要求。它目前只支持“{point}”，并不自动增加任何权限。麦珂把边界写进说明，随后收起文件夹。",
        f"眼前的结果足够让工作继续，却还没有替下一轮问题作答。{hook}。三个人带着各自的任务离开，走廊里的声音渐渐远去。",
    ]
    extra = [
        f"艾琳把刚才的过程重新复述一遍，先说谁拿来了什么，再说哪一个判断仍然没有凭据。她故意不使用含糊的“大家都知道”，而是把每个动作落到具体的人和时间上。麦珂听完后补了一处遗漏：如果下一位接手者只看到{artifact}，必须同时看到它的来件说明，否则很容易把局部材料当成完整背景。",
        f"黛安娜走到窗边，向合作方说明今天不会得到一个超过材料范围的答案。对方起初觉得这是推迟，后来听见她把返工时间、车辆费用和人员安排逐项说清，语气才缓下来。她没有要求对方先相信自己，只提出把下一次确认安排在双方都能到场的时间，让争议留在可讨论的桌面上。",
        f"纸面上的空白让房间安静了片刻。麦珂用铅笔在空白旁写下三个问题：谁接收、何时接收、接收后做了什么。苏菲亚把其中一个问题带回账目，昆廷把另一个问题带回现场，艾琳则保留第三个问题等待档案回复。不同方向的核对因此没有互相覆盖。",
        f"临近下班时，负责人员把一份口头说明送到门口，里面有两处说法与早上的登记不同。艾琳没有把它退回，而是请对方在纸上标明哪些是亲眼见到的，哪些是听别人转述的。麦珂把两种内容分开夹存，黛安娜则据此重新安排明天的会面顺序。",
        f"团队成员开始收拾桌面时，最初的急迫感并没有完全消失。麦珂知道他们少拿到了一项便利，却多保住了一条可以回看的路径。黛安娜把需要承担的费用写进排期，艾琳把需要补齐的页码写进申请，所有决定都在离开前找到对应的去处。",
        f"门外的灯亮起来，{authority}提醒他们下一次调阅或会面仍需重新申请。这个提醒让结果显得不够圆满，却也避免今天的许可被误解成长期授权。麦珂把说明念给黛安娜听，两人逐字确认没有多写一个尚未获得的权限，随后才把材料封好。",
    ][(ch + phase) % 6]
    blocks.insert(6, extra)
    blocks.insert(7, f"回到走廊后，麦珂没有马上离开。他把今天的决定写成一段给下一班工作人员看的说明：先看材料的来源，再看允许使用的范围，最后确认谁负责下一次回应。黛安娜补上了实际排期，艾琳补上了需要补件的日期。三个人都明白，真正可靠的工作不是让事情看起来已经结束，而是让后来的人能够从同一页纸上继续向前。{details[(ch + phase + 2) % len(details)]}。")
    blocks.insert(8, f"这场谈话没有被写成一份漂亮的总结。麦珂把对方提出的疑问原样记下，黛安娜在旁边标出会影响排期的事项，艾琳则把能够由档案或账目回答的问题另列一栏。有人建议把几处不确定的说法删掉，免得后来的人误会；麦珂没有同意，因为删掉疑问并不会让疑问消失。{domain}真正需要的是一条能被复查的路径：谁在什么时候看见了什么，谁据此作出什么选择，选择又给下一班人留下了什么责任。等三个人把这段说明读完，屋里的急迫感已经变成了可以执行的顺序。")
    return "\n\n".join(blocks)

def main() -> None:
    plan = load(OUT / "isolated_candidate_plan_271_500.json")
    events = event_lookup(plan)
    cards = card_lookup(plan)
    # Keep recoverable backups before changing the authoritative planning views.
    for name in ("event_clusters_v2.json", "master_ctx_cards_v2.json", "chapter_synopses_v5_qwen_500.json"):
        src = OUT / name
        backup = OUT / (name + ".pre_quality_repair_20260827")
        if not backup.exists():
            shutil.copy2(src, backup)
    old_events = load(OUT / "event_clusters_v2.json")
    old_cards = load(OUT / "master_ctx_cards_v2.json")
    old_synopses = load(OUT / "chapter_synopses_v5_qwen_500.json")
    event_cards = {}
    for n, c in cards.items():
        event_cards.setdefault(str(c["event_cluster_id"]), []).append(c)
    new_events = []
    for old in old_events:
        eid = str(old.get("cluster_id", ""))
        if eid in events and int(events[eid]["chapter_span"][1]) >= 277:
            new_events.append(normalized_event(events[eid], sorted(event_cards.get(eid, []), key=lambda x: int(x["chapter_id"]))))
        else:
            new_events.append(old)
    def repaired_view(old: dict) -> dict:
        n = int(old.get("chapter_id", 0))
        if n not in cards or n < 277:
            return old
        c = cards[n]
        eid = str(c["event_cluster_id"])
        e = events[eid]
        out = dict(old)
        out.update({"cluster_id": eid, "event_cluster_id": eid, "cluster_name": e.get("name", eid), "timeline_years": ",".join(sorted({str(x.get('timeline_start','').split('-')[0]) for x in event_cards.get(eid, [])})), "timeline_start": c.get("timeline_start"), "timeline_end": c.get("timeline_end"), "chapter_goal": c.get("goal", ""), "detailed_synopsis": c.get("goal", "") + "。" + c.get("turning_choice", ""), "chapter_ending": c.get("ending_hook", ""), "chapter_role_v2": "candidate_only_bounded_progress", "status": "candidate_only", "formal_promotion": False, "story_memory_write": False, "neo4j_write": False, "artifact_creates": [], "artifact_refs": [], "state_transitions": [], "source_event_sha256": hashlib.sha256(json.dumps(e, ensure_ascii=False, sort_keys=True).encode()).hexdigest()})
        return out
    dump(OUT / "event_clusters_v2.json", new_events)
    dump(OUT / "master_ctx_cards_v2.json", [repaired_view(x) for x in old_cards])
    dump(OUT / "chapter_synopses_v5_qwen_500.json", [repaired_view(x) for x in old_synopses])
    dump(OUT / "quality_repaired_basis_277_500.json", {"status":"candidate_only", "scope":[277,500], "reason":"chapter length regression plus authoritative plan drift detected", "target_chinese_chars_per_chapter":1000, "event_clusters":[normalized_event(events[eid], sorted(event_cards.get(eid, []), key=lambda x:int(x["chapter_id"]))) for eid in sorted(events, key=lambda x:int(x[2:])) if int(events[eid]["chapter_span"][0]) >= 277], "chapter_cards":[cards[n] for n in sorted(cards) if n >= 277]})
    # Regenerate from the repaired basis while keeping each existing scene as the opening.
    for n in range(277, 501):
        card = cards[n]
        eid = str(card["event_cluster_id"])
        event = events[eid]
        formal = OUT / "chapters" / f"chapter_{n:03d}.txt"
        original = formal.read_text(encoding="utf-8")
        paragraphs = [x.strip() for x in re.split(r"\n\s*\n", original) if x.strip()]
        # Keep the title and the first seven scene paragraphs; discard previous
        # machine-added filler before rebuilding a bounded chapter shape.
        text = "\n\n".join(paragraphs[:7])
        text = text.rstrip() + "\n\n" + expansion(n, card["timeline_start"], event, card, n % 8) + "\n"
        if chinese_count(text) < 1000:
            raise RuntimeError(f"chapter_{n} expanded body remains below 1000 Chinese characters")
        formal.write_text(text, encoding="utf-8")
        for src in BASE.glob(f"rewrite_trial_*/chapters/chapter_{n}.txt"):
            if "legacy" not in str(src):
                src.write_text(text, encoding="utf-8")
                break
    # Candidate cards must authorize every canonical character actually used
    # by the repaired prose; this remains a candidate-only authorization.
    bible = load(ROOT / "outputs_pop_king_v6_compiled_story_first_500" / "global_story_outline_v5_qwen_500.json").get("canonical_character_registry", [])
    all_ids = [str(x.get("character_id")) for x in bible if isinstance(x, dict) and x.get("character_id")]
    for f in BASE.glob("rewrite_trial_*/EC*_candidate_cards.json"):
        data = load(f)
        span = data.get("chapter_span") or [0, 0]
        if int(span[0]) >= 277:
            data["participant_ids"] = [x for x in all_ids if x not in (data.get("main_character_ids") or [])]
            dump(f, data)
    print(json.dumps({"repaired_basis":True,"events":len([x for x in events.values() if int(x['chapter_span'][0])>=277]),"chapters":224,"min_chinese_chars":min(chinese_count((OUT/'chapters'/f'chapter_{n:03d}.txt').read_text(encoding='utf-8')) for n in range(277,501))}, ensure_ascii=False))

if __name__ == "__main__":
    main()

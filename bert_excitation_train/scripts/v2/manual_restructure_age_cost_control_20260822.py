"""Human-directed continuity repair for the first 210 chapters.

This pass is deliberately conservative: it corrects adult-age language and
adult legal semantics in existing prose, then moves durable cost/control-flaw
signals into the authoritative event and chapter planning data.  It does not
regenerate prose or alter the 1969-1975 minor arc.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs_pop_king_v6_compiled_story_first_500"
BODY_DIR = OUT / "chapters"
CARDS_PATH = OUT / "master_ctx_cards_v2.json"
EVENTS_PATH = OUT / "event_clusters_v2.json"
LIFECYCLE_PATH = ROOT / "data" / "pop_king_character_lifecycle_v1.json"


def year_of(card: dict) -> int:
    for key in ("timeline_start", "timeline_years"):
        match = re.search(r"(\d{4})", str(card.get(key) or ""))
        if match:
            return int(match.group(1))
    return 1969


def age_of(card: dict) -> int:
    return year_of(card) - 1958


def walk_replace(value, replacements):
    if isinstance(value, dict):
        return {k: walk_replace(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [walk_replace(v, replacements) for v in value]
    if isinstance(value, str):
        for old, new in replacements:
            value = value.replace(old, new)
    return value


def repair_protagonist_paragraph(text: str, age: int) -> str:
    direct = any(token in text for token in ("麦珂", "他", "自己的身体", "身体", "嗓音", "手腕"))
    replacements = [
        ("十一岁的身体特有的单薄感", "成年身体长期透支后的薄弱感"),
        ("十二岁的身体特有的单薄感", "成年身体长期透支后的薄弱感"),
        ("十一岁的身体", f"{age}岁的成年身体"),
        ("十二岁的身体", f"{age}岁的成年身体"),
        ("少年身体", "成年身体"),
        ("孩童身体", "成年人的身体"),
        ("孩子的身体", "成年人的身体"),
        ("十一岁的身躯", f"{age}岁的成年身躯"),
        ("十二岁的身躯", f"{age}岁的成年身躯"),
        ("十一岁的麦珂", f"{age}岁的麦珂"),
        ("十二岁的麦珂", f"{age}岁的麦珂"),
    ]
    if direct:
        replacements.extend([
            ("未成年人", "成年艺人"),
            ("未成年人的", "成年艺人的"),
            ("童星", "艺人"),
            ("儿童保护", "艺人保护"),
            ("监护权", "医疗代理权"),
            ("监护人", "医疗代理人"),
            ("父母替他", "父母试图越过他的授权替他"),
            ("母亲替他", "母亲试图越过他的授权替他"),
            ("妈妈替他", "妈妈试图越过他的授权替他"),
        ])
    for old, new in replacements:
        text = text.replace(old, new)
    # Standalone age references in adult protagonist paragraphs are also stale.
    if direct:
        text = text.replace("十一岁", f"{age}岁").replace("十二岁", f"{age}岁")
    return text


def repair_body(path: Path, card: dict) -> tuple[str, int]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if year_of(card) < 1976:
        return text, 0
    age = age_of(card)
    paragraphs = text.split("\n")
    changed = 0
    repaired = []
    for paragraph in paragraphs:
        new = repair_protagonist_paragraph(paragraph, age)
        if new != paragraph:
            changed += 1
        repaired.append(new)
    result = "\n".join(repaired)
    path.write_text(result, encoding="utf-8", newline="\n")
    return result, changed


def han_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))


def replace_finale(path: Path, replacement: str) -> bool:
    parts = [part.strip() for part in path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n") if part.strip()]
    if not parts:
        return False
    parts[-1] = replacement
    generic = ("这一战", "这只是开始", "未来的路", "真正的挑战", "掌握了主动权", "赢定了", "属于自己的力量")
    while han_count("\n\n".join(parts)) > 2000 and len(parts) > 3:
        candidate = parts[-2]
        if any(token in candidate for token in generic) or len(candidate) < 220:
            parts.pop(-2)
        else:
            break
    path.write_text("\n\n".join(parts) + "\n", encoding="utf-8", newline="\n")
    return True


def add_lifecycle(card: dict) -> None:
    year = year_of(card)
    age = age_of(card)
    adult = year >= 1976
    card["character_lifecycle"] = {
        "protagonist": "麦珂·杰森",
        "birth_year": 1958,
        "current_year": year,
        "current_age_approx": age,
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


def add_cost(cluster: dict, kind: str, description: str, recovery: str) -> None:
    cluster["outcome_type"] = "costly_win" if kind != "setback" else "setback_with_gain"
    cluster["protagonist_cost"] = {
        "required": True,
        "type": kind,
        "description": description,
        "chosen_by_protagonist": True,
        "visible_this_cluster": True,
        "persists": True,
        "recovery_condition": recovery,
    }
    cluster["residual_problem"] = cluster.get("residual_problem") or "这次结算没有清空主线压力，下一簇必须承接该代价。"


def add_flaw(cluster: dict, mode: str, trigger: str, action: str, benefit: str, harm: str, who: str, future: str) -> None:
    cluster["character_flaw_beat"] = {
        "character": "麦珂",
        "trait": "control_need",
        "mode": mode,
        "trigger": trigger,
        "protagonist_action": action,
        "why_he_thinks_it_is_right": "他经历过身体、作品和人生被别人决定的结局，因此把提前安排误认为唯一的保护。",
        "immediate_benefit": benefit,
        "hidden_cost": harm,
        "who_pushes_back": who,
        "relationship_effect": "trust_down" if mode in {"warning", "overreach", "consequence"} else "trust_up",
        "future_payoff_cluster": future,
    }


def main():
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    events = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
    card_map = {int(c["chapter_id"]): c for c in cards}
    body_changes = {}
    for chapter in range(1, 211):
        card = card_map[chapter]
        add_lifecycle(card)
        _, changed = repair_body(BODY_DIR / f"chapter_{chapter:03d}.txt", card)
        if changed:
            body_changes[chapter] = changed

    # Replace a selected set of clean-win epilogues with durable, visible
    # consequences.  These are manual scene-level edits, not a prose generator
    # instruction, so the current 1-210 manuscript already shows the new slope.
    cost_endings = {
        30: "乔纳的项目被暂停，麦珂却没有接受庆功宴上的掌声。他把下一场演出的名额让给了受牵连的乐手，自己失去了一次登台机会；玛莎第一次问他，胜利是不是也可以不靠一个人承担全部后果。",
        40: "麦珂拒绝了奥瑞恩的邀请，保住了发行自由，却失去了最快进入主流市场的通道。邀请函被他放进档案袋，而不是撕掉：他知道这份拒绝会让维克多更早把他列为必须处理的对象。",
        50: "承诺书生效后，麦珂没有立刻回到训练室。医生要求他暂停一周，错过原定的公开试听；他盯着空白的排期表，第一次承认保护嗓音也意味着主动放弃掌声。",
        60: "卡尔被挡在流程之外，巡演却因此少了一场关键演出。麦珂把取消通知亲自交给观众代表，承认这次安全胜利的代价不是卡尔丢脸，而是团队必须承受收入和声誉的短期损失。",
        70: "公约签完，麦珂把家庭账簿交给玛莎共同保管，没有再要求她只执行自己的安排。可乔纳留下的债务仍在，下一轮发行款被冻结，眼前的自由并没有立刻带来宽裕。",
        80: "免责协议保住了身体主权，却让维克多看见麦珂对攻击节点的准备过于精确。麦珂收起报告时没有庆祝：从今天起，对手会先查他为什么知道，而不是只查文件哪里有错。",
        90: "三秒停顿被写进执行备忘录，麦珂却错过了当晚的庆祝演出。瑟琳娜看着他把钥匙交给共同保管人，提醒他：规则可以保护人，也会让他失去独自决定速度的便利。",
        100: "合同保住了，麦珂却把一场原定的媒体专访让给苏菲亚。公众只看见他退后一步，维克多却看见了更危险的东西：麦珂开始把决定权分给别人，而不是把所有胜利都写成自己的名字。",
        110: "墨渍从桌面擦掉后，瑟琳娜没有跟麦珂一起离开。她要求先拿到完整的风险说明再签下一份共同协议；麦珂第一次没有催她，只把原始记录推过去，接受这场胜利必须等待她自己同意。",
        120: "铜齿轮编号被保住，林克却带走了一份尚未归档的副本。麦珂没有追出去抢回，而是承认自己的单点保管方案留下了漏洞；团队因此多花三个月补做交叉备份，发行计划被迫延后。",
        130: "观众的欢呼没有按麦珂预设的节奏发生。瑟琳娜删掉了他写好的引导词，现场反而更真实；麦珂脸色难看，却没有夺回麦克风，任由这次不受控制的回应留在公开记录里。",
        140: "巴里的说法被拆穿，公众却没有立刻全部站到麦珂一边。有人认为他过度操控现场，苏菲亚要求他公开完整原始记录；麦珂保住了证据，也必须接受一部分人暂时不相信自己。",
        150: "底片进入金库后，麦珂把其中一把钥匙交给苏菲亚，自己失去随时调取原件的便利。安全边界变厚了，行动速度却变慢；下一次反击，他必须先说服共同保管人，而不是直接开门。",
        160: "医疗审计委员会成立，但麦珂没有任命自己主持。维克多留下的旧账仍让合作方暂停付款，团队连续两个月只能缩减巡演；制度赢下第一步，现实却逼他们为独立支付账单。",
        170: "健康标准被暂时认可，光学组件项目却因资金断裂停在半成品。麦珂看着莱昂收起未完成的图纸，没有承诺马上补钱，只承认自己把安全优先级排在商业速度之前，必须承受项目延期。",
        180: "审计代表签字后，麦珂没有再把所有钥匙收回自己手里。代价是他无法随时改动方案，莱昂也明确表示下一次会投反对票；麦珂第一次把‘不同意’当成合作仍然存在的证据。",
        190: "演出保住了，麦珂却主动暂停下一周的巡演，把异常记录交给团队共同复核。维克多没有被当场击垮，反而获得了更长的调查时间；这次胜利只换来一个窗口，而不是终局。",
    }
    for chapter, ending in cost_endings.items():
        path = BODY_DIR / f"chapter_{chapter:03d}.txt"
        if replace_finale(path, ending):
            body_changes[chapter] = body_changes.get(chapter, 0) + 1

    control_endings = {
        146: "麦珂把撤销瑟琳娜现场权限的通知放回桌上，没有递出去。瑟琳娜问他是不是又想替她决定，麦珂承认自己记得一场她会受伤的旧结局，却只把风险记录推到她面前：‘方案由我提出，去不去由你决定。’",
        156: "瑟琳娜盯着他提前排好的路线图，声音很轻：‘这和乔纳当年说保护你时，有什么区别？’麦珂的手停在纸边。他确实避开了事故，却也把她变成了自己预案里的一个变量；这一次他没有辩解，只收回了命令式的红线。",
        176: "设备安全下来以后，麦珂把最终启动按钮推到瑟琳娜面前。她可以拒绝，也可以修改他的方案。麦珂仍然害怕她选错，却没有伸手拦住她；他第一次让保护停在提供信息，而不是替对方做决定。",
        188: "苏菲亚没有替麦珂盖章，而是要求把暂停演出的权力写成团队共同授权。麦珂看了很久，最终在自己的名字旁边留出三个签字位置。失去单独拍板的速度让他不安，但他知道这不是削弱，而是让别人真正拥有选择。",
    }
    for chapter, ending in control_endings.items():
        path = BODY_DIR / f"chapter_{chapter:03d}.txt"
        if replace_finale(path, ending):
            body_changes[chapter] = body_changes.get(chapter, 0) + 1

    # Normalize stale age/legal language in authoritative plan text only after
    # the chapter lifecycle is attached; minor-era chapters remain untouched.
    for card in cards:
        if year_of(card) < 1976:
            continue
        age = age_of(card)
        replacement = [
            ("十一岁的身体特有的单薄感", "成年身体长期透支后的薄弱感"),
            ("十一岁的身体", f"{age}岁的成年身体"),
            ("十二岁的身体", f"{age}岁的成年身体"),
            ("少年身体", "成年身体"),
            ("孩童身体", "成年人的身体"),
            ("未成年人监护权", "成年人的医疗代理权"),
            ("未成年人", "成年艺人"),
            ("监护权", "医疗代理权"),
            ("监护人", "医疗代理人"),
            ("童星", "成名艺人"),
            ("儿童表演许可", "艺人演出许可"),
        ]
        for key in ("chapter_goal", "detailed_synopsis", "exact_action_sequence", "info_gap_use", "opponent_reaction", "immediate_payoff", "chapter_ending", "chapter_must_include", "chapter_must_not_include"):
            if key in card:
                card[key] = walk_replace(card[key], replacement)
        cards[card["chapter_id"] - 1] = walk_replace(cards[card["chapter_id"] - 1], replacement)

    cost_specs = {
        15: ("opportunity", "保住现场控制权，但主动放弃一次能快速扩大曝光的商业合作。", "建立不受单一集团控制的公开发行渠道"),
        20: ("opportunity", "保住作品的独立发行窗口，但主动放弃一次能迅速扩大声量的黄金演出。", "重新取得不受集团控制的发行渠道"),
        25: ("information", "反击成功，却让对手确认麦珂对关键流程熟悉得不合常理。", "用可公开核验的现实证据解释准备来源"),
        30: ("information", "反击成功，却让维克多确认麦珂掌握了异常精确的提前信息。", "用新的公开证据解释准备来源并转移对手注意力"),
        35: ("relationship", "赢下合同争议，但麦珂隐瞒了部分风险，玛莎不再默认替他签字。", "让家人参与下一次授权并承担共同决策责任"),
        40: ("relationship", "赢下市场入口，但麦珂没有提前告知玛莎关键决定，家庭信任出现裂缝。", "让家人参与下一次授权并公开承担风险"),
        45: ("health_time", "保住声音和作品，但必须减少公开演出，错过一次重要行业亮相。", "完成医学复核并恢复安全排期"),
        50: ("health_time", "保住训练边界，但必须暂停一段时间，错过一次重要公开演出。", "完成医学复核并恢复安全排期"),
        55: ("strategic", "逼退眼前的对手，却让维克多提前接管发行与保险两条资源线。", "把个人防守升级为团队共同的资产机制"),
        60: ("strategic", "阻止卡尔继续透支巡演，却迫使维克多提前接管更大的资源链。", "建立独立巡演与医疗决策机制"),
        65: ("opportunity", "拿到关键技术记录，却放弃一次能立刻扩大市场的合作报价。", "完成独立复制与发行"),
        70: ("opportunity", "拿到铜齿轮资产证据，但失去一次与主流发行商合作的窗口。", "找到不依赖奥瑞恩的发行伙伴"),
        75: ("information", "守住档案，但一次过早的预案暴露了麦珂对敌方动作的熟悉程度。", "让多人共同保管证据并分散风险"),
        80: ("information", "成功保住档案，却暴露了麦珂对未来攻击方式的熟悉程度。", "让团队共同保管证据而非由麦珂独占"),
        85: ("relationship", "赢下技术争议，但麦珂越过瑟琳娜替她安排现场权限，关系出现裂缝。", "公开风险并把最终选择权交还瑟琳娜"),
        90: ("relationship", "赢下关键谈判，但瑟琳娜发现麦珂替她安排了安全路线，拒绝被代替决定。", "麦珂公开风险信息并把最终选择权交还瑟琳娜"),
        95: ("health_time", "保住健康决策权，却必须接受团队共同否决并暂停一场演出。", "在共同授权下恢复演出"),
        100: ("setback", "本次程序反击未能立即终结维克多的控制，只拿到健康控制链的关键证人名单。", "追查证人名单并补足正式证据链"),
    }
    for index, cluster in enumerate(events, start=1):
        if index in cost_specs:
            add_cost(cluster, *cost_specs[index])
            final_card = card_map[index * 2]
            cost_type, description, recovery = cost_specs[index]
            final_card["state_transitions"] = [
                item for item in final_card.get("state_transitions", [])
                if not (isinstance(item, dict) and item.get("state_key") == f"PROTAGONIST_COST_EC{index:03d}")
            ]
            final_card.setdefault("state_transitions", []).append({
                "state_key": f"PROTAGONIST_COST_EC{index:03d}",
                "from": "unpaid",
                "to": "active",
                "type": cost_type,
                "description": description,
                "persists": True,
                "recovery_condition": recovery,
                "irreversible": False,
            })
            if index * 2 + 1 in card_map:
                next_card = card_map[index * 2 + 1]
                next_card["active_costs"] = [
                    item for item in next_card.get("active_costs", [])
                    if not (isinstance(item, dict) and item.get("source_cluster") == f"EC{index:03d}")
                ]
                next_card.setdefault("active_costs", []).append({
                    "source_cluster": f"EC{index:03d}",
                    "type": cost_type,
                    "description": description,
                    "recovery_condition": recovery,
                })

    flaw_specs = {
        61: ("strength", "设备出现异常且瑟琳娜准备独自排查", "麦珂提前封存现场并替她安排排查顺序", "避免了即时设备事故", "瑟琳娜开始意识到自己的专业判断被绕过", "瑟琳娜", "EC074"),
        67: ("warning", "玛莎要求自己核对一份代理文件", "麦珂未经说明先把文件交给律师并取消她的签字权限", "阻止了一处条款漏洞", "玛莎认为他把家人也当成风险变量", "玛莎", "EC074"),
        74: ("overreach", "瑟琳娜准备独立处理高风险设备", "麦珂未经她同意撤销现场权限并替她排好路线", "当天没有发生设备伤害", "瑟琳娜指出这和乔纳以保护为名控制他的做法相似", "瑟琳娜", "EC082"),
        82: ("consequence", "团队拒绝执行麦珂未解释的紧急指令", "麦珂先把全部证据锁进个人保险箱", "短期避免证据被夺", "团队不再完全信任他的单人预案，现场响应变慢", "瑟琳娜", "EC089"),
        89: ("repair", "瑟琳娜要求知道风险而不是接受命令", "麦珂公开能够公开的前世线索和现实证据，并把选择交给她", "团队重新形成双向授权", "麦珂必须承受她可能拒绝最安全方案的恐惧", "瑟琳娜", "EC097"),
        97: ("growth", "健康风险再次要求他选择是否独自承担", "麦珂提出方案但不再替团队签字，允许苏菲亚和瑟琳娜共同否决", "决策获得更强的现实合法性", "他失去独自控制结算速度的便利", "苏菲亚", "EC105"),
    }
    for index, cluster in enumerate(events, start=1):
        if index in flaw_specs:
            add_flaw(cluster, *flaw_specs[index])

    CARDS_PATH.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
    EVENTS_PATH.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "version": "manual_restructure_age_cost_control_20260822",
        "body_changed_chapters": body_changes,
        "adult_age_chapters": [n for n in range(1, 211) if year_of(card_map[n]) >= 1976],
        "cost_clusters": sorted(cost_specs),
        "control_flaw_clusters": sorted(flaw_specs),
    }
    (OUT / "manual_restructure_age_cost_control_20260822.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"body_changed": len(body_changes), "cost_clusters": sorted(cost_specs), "control_flaw_clusters": sorted(flaw_specs)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

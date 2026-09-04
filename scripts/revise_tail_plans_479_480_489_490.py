from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN_DIR = ROOT / "bert_excitation_train" / "outputs_pop_king_v6_compiled_story_first_500"
SYN_PATH = PLAN_DIR / "chapter_synopses_v5_qwen_500.json"
CLUSTER_PATH = PLAN_DIR / "event_clusters_v2.json"


def dump(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chapter_payloads() -> dict[int, dict[str, object]]:
    return {
        479: {
            "chapter_title": "讣告禁发令前的十秒·上",
            "chapter_goal": "北湾地方电台收到预置讣告并切入片头，值班编辑在完整播出前发现禁发状态未解除，强行切断信号",
            "chapter_must_include": [
                "讣告片头音乐与十几秒异常黑场",
                "值班编辑喊出禁发状态未解除并阻断完整播出",
                "地点为北湾地方电台",
            ],
            "chapter_must_not_include": [
                "公开宣布麦珂死亡或播出完整生平回顾",
                "让公众形成完整死亡叙事",
                "输出结构化状态字段",
                "非麦珂人物拥有前世记忆",
            ],
            "chapter_ending": "完整讣告被阻断，公众只听见片头与短暂黑场；值班编辑却发现稿件已经处在只差一次确认即可播出的状态。",
            "detailed_synopsis": "2009年7月7日早晨，北湾地方电台的自动播控台收到一份预置讣告。主持人按提示切入，片头音乐已经响起，屏幕随即黑了十几秒。值班编辑核对禁发栏，发现状态根本没有解除，当场拔掉自动切换并恢复正常节目。公众没有听见死亡结论，也没有形成完整讣告叙事。瑟琳娜压住工作人员主动解释死讯的冲动，不发动粉丝围堵，只让监管人员封存片头、播控日志、稿件编号和接收时间。节目恢复后，值班编辑在稿件属性页发现：这份讣告已具备播出条件，只差最后一次人工确认。",
            "scene_location": "北湾地方电台播控室",
            "exact_action_sequence": [
                "自动播控台收到预置讣告，主持人切入片头音乐并出现十几秒黑场",
                "值班编辑发现禁发状态未解除，拔掉自动切换，阻断完整讣告播出",
                "瑟琳娜不发动粉丝围堵，团队封存播控日志并确认稿件只差一次人工确认",
            ],
            "immediate_payoff": "完整死亡叙事没有公开，预置稿却被保全在只差一个按钮的位置",
            "opponent_reaction": "巴里·布鲁姆把异常解释成普通测试，催促电台删除黑场记录，反而暴露他知道稿件所在。",
            "core_payoff": "完整讣告被阻断，同时保全了预置稿已进入一键播出位置的证据。",
            "cluster_outcome": "团队承担十几秒黑场造成的疑问，阻止完整死亡叙事公开，并保全预置讣告的播控路径。",
        },
        480: {
            "chapter_title": "讣告禁发令前的十秒·下",
            "chapter_goal": "广播监管委员会追查预置讣告为何进入一键播出位置，锁定巴里的内容分发名单、纪念承包商和自动推送接口",
            "chapter_must_include": [
                "内容分发名单、纪念承包商与自动推送接口",
                "确认没有完整讣告公开播出",
                "广播监管委员会",
            ],
            "chapter_must_not_include": [
                "死亡谣言扩散或公众开始悼念",
                "重复第479章的播控室阻断场面",
                "永久封杀或绝对控制权",
                "输出ART编号或snake_case字段",
            ],
            "chapter_ending": "委员会确认完整死亡叙事从未公开，巴里的预置网络却已被锁定；真正的首次全球死亡误信仍留待第491章爆发。",
            "detailed_synopsis": "广播监管委员会调取地方台接收列表、纪念承包商的交付单和自动推送接口记录。调查发现，巴里的内容分发名单把预置讣告推给多家合作媒体，纪念承包商又把内部测试状态误设为可调用，地方台因此只差一次人工确认就能完整播出。巴里辩称这是名人新闻的速度预案，却无法解释为何禁发状态未解除时稿件仍进入播控队列。委员会暂停该自动接口，要求死亡快讯必须同时取得医院或家属确认。最终日志证明：当天只有片头音乐和十几秒黑场，没有播出姓名、死亡结论或生平回顾，公众没有形成完整死亡叙事；但可在同一时点推送多家媒体的预置网络已经暴露。",
            "scene_location": "广播监管委员会取证室",
            "exact_action_sequence": [
                "委员会比对地方台接收列表、纪念承包商交付单和自动推送接口记录",
                "巴里的内容分发名单被锁定，自动接口被暂停并增加医院或家属确认",
                "播控日志确认只有片头和短暂黑场，没有完整讣告及公共死亡叙事",
            ],
            "immediate_payoff": "预置分发网络被暴露并暂停，而第491章仍保留第一次真实全球死亡误信",
            "opponent_reaction": "巴里·布鲁姆把一键播出称作效率设计，却在追问下承认名单由他的办公室维护。",
            "core_payoff": "巴里的预置分发名单、纪念承包商和自动推送接口被锁定，完整讣告未曾公开。",
            "cluster_outcome": "团队阻止完整死亡叙事公开，承担短暂黑场造成的疑问，并让巴里的预置分发网络失去无确认直达播控台的能力。",
        },
        489: {
            "chapter_title": "他们以为他不能说话·上",
            "chapter_goal": "托马斯依据麦珂真实的虚弱表现申请紧急失能接管，法院只审查是否先冻结部分权限，并把正式能力听证安排到次日",
            "chapter_must_include": [
                "消瘦、需人搀扶、排练暂停、助眠药调整与家属劝停",
                "麦珂因疲劳反应变慢，现场一度不利",
                "地点为银湾遗产法院临时审查室",
            ],
            "chapter_must_not_include": [
                "完成正式能力测试或给出最终能力结论",
                "提前展示全部终局证据",
                "输出结构化状态字段",
                "非麦珂人物拥有前世记忆",
            ],
            "chapter_ending": "法官拒绝全面失能，却把正式能力听证排到第二天；托马斯临走前说：‘明天你最好还能像今天这么清醒。’",
            "detailed_synopsis": "2009年8月18日，托马斯向银湾遗产法院提出紧急失能接管。他没有依赖荒唐伪证，而是摆出一组真实且危险的事实：麦珂明显消瘦、走路需要搀扶、排练屡次暂停、近期调整助眠药，连家属都要求他停演。麦珂出庭时脸色苍白，因为前夜失眠，对法官的第一个问题反应慢了几秒，托马斯立刻要求先冻结作品、治疗和直播决定权。麦珂没有靠终局证据反杀，只说明自己听懂了申请，并请求由独立医生在休息后进行正式测试。法官拒绝全面失能，也不在信息不足时彻底驳回申请，只维持有限协助并把正式能力听证安排到次日。散庭时，托马斯看着麦珂说：‘明天你最好还能像今天这么清醒。’",
            "scene_location": "银湾遗产法院临时审查室",
            "exact_action_sequence": [
                "托马斯用麦珂真实的消瘦、搀扶、停排、药物调整和家属劝停申请紧急接管",
                "麦珂因疲劳反应缓慢，托马斯要求先冻结部分权限，现场一度对麦珂不利",
                "法官拒绝全面失能，维持有限协助并安排第二天正式能力听证",
            ],
            "immediate_payoff": "全面接管没有成立，但正式能力决战被推到第二天",
            "opponent_reaction": "托马斯不夸张事实，只把身体虚弱包装成不能决定，并用次日状态的不确定性施压。",
            "core_payoff": "麦珂保住当日决定权，却必须在次日以普通问题证明自己仍有能力。",
            "cluster_outcome": "团队承担麦珂真实虚弱带来的法律风险，阻止当日全面接管，并把能力判断交给次日正式听证。",
        },
        490: {
            "chapter_title": "他们以为他不能说话·下",
            "chapter_goal": "独立医生与法官用普通问题测试麦珂的理解、权衡与守约能力，正式确认身体虚弱不等于失去决定能力",
            "chapter_must_include": [
                "在哪里、取消或继续演出的后果、拒绝深度镇静的原因",
                "若达到提前约好的停演条件，麦珂接受医生叫停",
                "法官密封确认麦珂具备决定能力，最终行动窗口形成",
            ],
            "chapter_must_not_include": [
                "重复第489章的紧急申请过程",
                "用背诵专业术语代替能力证明",
                "永久封杀或绝对控制权",
                "输出ART编号或snake_case字段",
            ],
            "chapter_ending": "正式评估确认虚弱不等于失能；密封决定保住麦珂的选择权，也让维克多和巴里继续误判终局窗口。",
            "detailed_synopsis": "第二天的正式能力听证不讨论庞大证据链。独立医生和法官只问普通问题：麦珂知道自己在哪里吗；取消演出会造成什么后果；继续演出又会承担什么风险；为什么拒绝深度镇静；如果医生明天要求停演，他是否接受。麦珂承认取消会让歌迷失望并带来违约损失，继续则可能伤害身体；他拒绝深度镇静，是因为需要保持清醒作决定，而不是拒绝一切治疗。面对最后一问，他没有说‘我会自己判断’，而是回答：‘如果达到我们提前约好的停演条件，我接受。’这句话把此前建立的医疗边界和人物成长全部收回。独立医生确认他能理解信息、权衡后果并遵守预先约定。法官撤销即时接管，密封能力评估；麦珂仍不公开全部利益链，使维克多与巴里继续误判他即将失去表达能力。",
            "scene_location": "银湾遗产法院正式能力听证室",
            "exact_action_sequence": [
                "独立医生与法官询问地点、取消与继续演出的后果以及拒绝深度镇静的原因",
                "麦珂说明利害，并承诺达到提前约好的停演条件时接受医生叫停",
                "法官撤销即时接管并密封能力评估，维克多与巴里仍误判终局窗口",
            ],
            "immediate_payoff": "虚弱不等于失能，麦珂凭理解后果和遵守医疗边界保住决定权",
            "opponent_reaction": "托马斯试图把停顿和搀扶当作失能证据，却无法推翻麦珂对后果与边界的清楚回答。",
            "core_payoff": "法官密封确认麦珂具备决定能力，终局行动窗口形成。",
            "cluster_outcome": "麦珂以普通问题证明理解、权衡和守约能力；法院撤销即时接管并密封结论，对手仍会继续启动纪念方案。",
        },
    }


def update_scene(ch: dict[str, object], cue: str) -> None:
    ch["scenes"] = [{
        "sequence": 1,
        "location": ch["scene_location"],
        "is_primary": True,
        "temporal_mode": "current",
        "transition_cue": cue,
    }]


def update_nested_milestone(m: dict[str, object], payload: dict[str, object]) -> None:
    m["chapter_title"] = payload["chapter_title"]
    m["chapter_goal"] = payload["chapter_goal"]
    m["opening_conflict"] = payload["exact_action_sequence"][0]
    m["scene"] = payload["scene_location"]
    m["scenes"] = [{
        "sequence": 1,
        "location": payload["scene_location"],
        "is_primary": True,
        "temporal_mode": "current",
        "transition_cue": payload["exact_action_sequence"][0],
    }]
    m["action_sequence"] = payload["exact_action_sequence"]
    m["visible_payoff"] = payload["immediate_payoff"]
    m["ending"] = payload["chapter_ending"]
    m["must_include"] = payload["chapter_must_include"]
    m["must_not_include"] = payload["chapter_must_not_include"]
    m["detailed_synopsis"] = payload["detailed_synopsis"]
    m["opponent_reaction"] = payload["opponent_reaction"]


def main() -> None:
    synopses = json.loads(SYN_PATH.read_text(encoding="utf-8"))
    clusters = json.loads(CLUSTER_PATH.read_text(encoding="utf-8"))
    payloads = chapter_payloads()

    for chapter_id, payload in payloads.items():
        ch = synopses[chapter_id - 1]
        assert ch["chapter_id"] == chapter_id
        for key, value in payload.items():
            ch[key] = copy.deepcopy(value)
        update_scene(ch, str(payload["exact_action_sequence"][0]))
        ch["manual_edits"] = sorted(set(ch.get("manual_edits", []) + ["2026-08-29 S-level continuity rewrite"]))
        ch["planning_version"] = "v17_tail_continuity_rewrite_20260829"
        ch["source_milestone_sha256"] = sha(str(payload["detailed_synopsis"]))

    # EC240: no complete obituary or public death belief before chapter 491.
    ec240 = next(x for x in clusters if x["cluster_id"] == "EC240")
    ec240.update({
        "name": "讣告禁发令前的十秒",
        "story_block_outcome": "预置讣告的一键分发路径被暴露，完整死亡叙事未公开",
        "macro_ending_state": "预置讣告的一键分发路径被暴露，完整死亡叙事未公开",
        "source_event_direction": "地方台收到预置讣告并切入片头，但值班编辑发现禁发状态未解除，在完整播出前强行切断。随后监管方沿内容分发名单、纪念承包商和自动推送接口追查，确认稿件已到一键播出位置，却没有形成完整公共死亡叙事，从而保护第491章作为世界第一次真正相信麦珂死亡的爆点。",
        "fictional_obstacle": "预置讣告在禁发状态未解除时仍进入地方台一键播出队列",
        "prev_life_tragedy": "前世完整讣告与利益链几乎同时启动，麦珂已经无法阻止世界用过去时分配他的一切。",
        "info_gap_from_prev_life": "麦珂记得前世死亡快讯一旦完整公开就会迅速成为共同事实，因此今生优先守住第一次完整播出的闸门，同时保全自然形成的播控记录。",
        "why_previous_life_failed": "前世没有人能在完整讣告公开前核对禁发状态，也没有留下预置分发路径的独立记录。",
        "preemptive_avoidance": "阻断完整讣告，不用粉丝围堵制造二次伤害",
        "bait_and_evidence": "不伪造死亡；保全片头、黑场、接收列表和自动推送记录，证明稿件已进入一键播出位置。",
        "villain_loss": "巴里失去让预置讣告在无医院或家属确认时直达地方台播控队列的路径。",
        "protagonist_gain": "麦珂团队阻止完整死亡叙事公开，并锁定巴里、纪念承包商与自动推送接口的连接。",
        "relationship_change": "瑟琳娜压住公开反击，先保护无辜听众与值班人员。",
        "cluster_outcome": payloads[480]["cluster_outcome"],
        "core_payoff": payloads[480]["core_payoff"],
        "resolves": ["预置讣告进入一键播出位置，但完整公共死亡叙事被阻断"],
        "manual_edits": sorted(set(ec240.get("manual_edits", []) + ["2026-08-29 protect chapter 491 first-death-belief climax"])),
        "planning_version": "v17_tail_continuity_rewrite_20260829",
    })
    ec240["death_chain_step"] = {
        "step": "预置讣告进入地方台一键播出队列但被值班编辑阻断",
        "evidence_boundary": "预置讣告阻断日志",
        "future_use": "第491章首次完整死亡快讯公开时，比对同一内容分发网络",
    }
    ec240["rebirth_flywheel"] = {
        "memory": ec240["info_gap_from_prev_life"],
        "present_action": ec240["preemptive_avoidance"],
        "evidence": "预置讣告阻断日志",
        "cost": "听众听见片头和十几秒黑场，地方台承担停播调查",
        "gain": "完整死亡叙事未公开，预置网络被锁定",
    }

    # EC245: chapter 489 is emergency review; chapter 490 is the actual test.
    ec245 = next(x for x in clusters if x["cluster_id"] == "EC245")
    ec245.update({
        "source_event_direction": "托马斯用麦珂真实的虚弱表现申请紧急失能接管。第489章只决定是否临时冻结权限，法官拒绝全面失能并安排次日正式听证；第490章才用普通问题检验理解、权衡和守约能力，以‘达到提前约好的停演条件，我接受’完成虚弱不等于失能的结算。",
        "fictional_obstacle": "托马斯把麦珂真实的消瘦、搀扶、停排、助眠药调整和家属劝停组合成紧急失能申请",
        "info_gap_from_prev_life": "麦珂知道对手会把身体虚弱偷换成没有决定能力，因此不靠逞强证明自己，而是依靠此前建立的停演条件与独立评估证明他能理解后果并遵守边界。",
        "why_previous_life_failed": "前世的虚弱被别人解释，麦珂既没有清醒表达机会，也没有预先约定的医疗停演条件可供核验。",
        "preemptive_avoidance": "不逞强、不提前倾倒终局证据，以正式能力测试证明理解、权衡和守约",
        "bait_and_evidence": "让托马斯依据真实表象提出申请，再由独立医生和法官记录麦珂对普通问题及停演条件的回答。",
        "villain_loss": "托马斯无法再把需要搀扶和反应缓慢直接等同于法律失能。",
        "protagonist_gain": "法官密封确认麦珂具备决定能力，且此前建立的医疗边界成为能力证据。",
        "relationship_change": "麦珂接受医生按预先条件叫停，完成从独自硬撑到信任共同边界的成长。",
        "cluster_outcome": payloads[490]["cluster_outcome"],
        "core_payoff": payloads[490]["core_payoff"],
        "resolves": ["真实身体虚弱是否等于失去决定能力"],
        "manual_edits": sorted(set(ec245.get("manual_edits", []) + ["2026-08-29 separate emergency review from capacity test"])),
        "planning_version": "v17_tail_continuity_rewrite_20260829",
    })
    ec245["rebirth_flywheel"] = {
        "memory": ec245["info_gap_from_prev_life"],
        "present_action": ec245["preemptive_avoidance"],
        "evidence": "清醒能力独立评估",
        "cost": "麦珂必须在真实疲劳和次日状态不确定的压力下接受公开于法庭的测试",
        "gain": "虚弱不等于失能，决定权获得密封司法确认",
    }

    for cluster, ids in [(ec240, (479, 480)), (ec245, (489, 490))]:
        for collection_name in ("two_chapter_structure", "chapter_milestones"):
            for milestone in cluster.get(collection_name, []):
                cid = milestone.get("chapter_id")
                if cid in ids:
                    update_nested_milestone(milestone, payloads[cid])
        cluster["source_event_direction_sha256"] = sha(cluster["source_event_direction"])
        for cid in ids:
            synopses[cid - 1]["source_event_sha256"] = cluster["source_event_direction_sha256"]

    # Move the capacity assessment artifact from chapter 489 to 490.
    ch489, ch490 = synopses[488], synopses[489]
    old_artifacts = ch489.get("artifact_creates", [])
    assessment = copy.deepcopy(old_artifacts[0]) if old_artifacts else {
        "artifact_id": "ART_489_8F7496AF",
        "timeline_scope": "current",
        "display_name": "《清醒能力独立评估》",
        "kind": "documented_record",
        "signers": ["独立能力评估医生与法官"],
        "granted_permissions": ["use_as_evidence_within_scope"],
        "does_not_grant": ["freeze_all_assets", "dismiss_staff", "override_medical_consent", "transfer_copyright"],
        "authority_source": "独立能力评估医生与法官",
        "expires_at": None,
    }
    assessment["created_at"] = 490
    assessment["display_name"] = "《清醒能力独立评估》"
    assessment["scope"] = ["麦珂能理解地点、治疗与演出选择的后果，并接受按预先约定的停演条件由医生叫停"]
    ch489["artifact_creates"] = []
    ch490["artifact_creates"] = [assessment]
    ch490["artifact_refs"] = []
    for collection_name in ("two_chapter_structure", "chapter_milestones"):
        entries = ec245.get(collection_name, [])
        m489 = next(m for m in entries if m["chapter_id"] == 489)
        m490 = next(m for m in entries if m["chapter_id"] == 490)
        m489["artifact_creates"] = []
        m490["artifact_creates"] = [copy.deepcopy(assessment)]
        m490["artifact_refs"] = []

    dump(SYN_PATH, synopses)
    dump(CLUSTER_PATH, clusters)
    print("updated chapter plans: 479, 480, 489, 490")
    print("updated clusters: EC240, EC245")


if __name__ == "__main__":
    main()

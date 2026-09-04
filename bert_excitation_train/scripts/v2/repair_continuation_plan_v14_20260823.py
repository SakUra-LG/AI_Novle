"""Repair the EC105→EC106 handoff before continuing body generation."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from bert_excitation_train.scripts.v2.repair_full_plan_v13_20260822 import (
    artifact_contract,
    digest,
    lifecycle,
    sync_card_from_milestone,
)


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "bert_excitation_train" / "outputs_pop_king_v6_compiled_story_first_500"
EVENTS_PATH = OUT / "event_clusters_v2.json"
CARDS_PATH = OUT / "master_ctx_cards_v2.json"
SYNOPSES_PATH = OUT / "chapter_synopses_v5_qwen_500.json"
REPORT_PATH = OUT / "continuation_plan_v14_repairs_20260823.json"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def milestone(event: dict[str, Any], chapter_id: int) -> dict[str, Any]:
    return next(item for item in event["two_chapter_structure"] if int(item["chapter_id"]) == chapter_id)


def artifact(
    artifact_id: str, chapter_id: int, display_name: str, kind: str,
    scope: list[str], permissions: list[str], participants: list[str],
) -> dict[str, Any]:
    value = {
        "artifact_id": artifact_id,
        "timeline_scope": "current",
        "display_name": display_name,
        "kind": kind,
        "created_at": chapter_id,
        "signers": [],
        "scope": scope,
        "granted_permissions": permissions,
        "does_not_grant": [
            "freeze_funds", "dismiss_staff", "expand_technical_access",
            "override_medical_consent",
        ],
        "authority_source": "本章具备相应权限的制作、签署或保管主体",
        "expires_at": None,
    }
    artifact_contract(value, chapter_id, participants)
    return value


def repair_ec105(event: dict[str, Any]) -> None:
    event["timeline_years"] = "1991"
    event["protagonist_gain"] = (
        "麦珂取得《今日健康备忘录》标准文本的无偿复制许可，并通过法院临时裁定阻止奥瑞恩继续垄断解释；"
        "苏菲亚作为首席证据官获得正式的证据保管职责。"
    )
    event["villain_loss"] = (
        "奥瑞恩关于健康协议的独家许可主张被法院停止执行，且其提交材料的来源与登记矛盾被记入庭审记录。"
    )
    event["cluster_outcome"] = (
        "纸质健康协议标准包获准无偿印刷和改编，奥瑞恩的单方解释与独家许可主张被法院停止执行。"
    )
    event["state_transitions"] = [
        {
            "domain": "rights", "entity_id": "RIGHT_VL_011",
            "state_key": "health_protocol_distribution_status",
            "from": "corporation_exclusive_claim", "to": "open_print_license",
            "irreversible": False, "evidence": "ART_209_OPEN_SOURCE_DECREE",
            "effect_type": "protagonist_gain",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
        {
            "domain": "rights", "entity_id": "ORG_ORION_REVENUE",
            "state_key": "exclusive_health_protocol_license",
            "from": "exclusive_claim_asserted", "to": "claim_enjoined",
            "irreversible": False, "evidence": "ART_210_INTERIM_RULING",
            "effect_type": "villain_loss",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
        {
            "domain": "character", "entity_id": "CHAR_87B8E75FFF6F",
            "state_key": "evidence_office_role",
            "from": "audit_and_ticketing_lead", "to": "chief_evidence_officer",
            "irreversible": False, "evidence": "ART_210_SCROLL_SUBMISSION",
            "effect_type": "protagonist_gain",
            "source_entity_label": "CHAR_87B8E75FFF6F",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
    ]

    first = milestone(event, 209)
    first.update({
        "timeline_start": "1991-10-20", "timeline_end": "1991-10-20",
        "chapter_title": "纸质许可与审计触发",
        "chapter_goal": "公布可无偿印刷、抄录和改编的纸质健康协议标准包，并触发对奥瑞恩独家许可主张的第三方审计。",
        "opening_conflict": "奥瑞恩法务总监以独家许可为由要求扣下全部标准包，混淆协议文本与个人病历数据。",
        "opponent_reaction": "法务总监试图指控麦珂公开私人病历，却被文本首页的隐私边界和审计触发条款反证。",
        "action_sequence": [
            "麦珂展示纸质许可页，明确允许复制标准文本但禁止传播任何人的病历数据。",
            "奥瑞恩法务总监要求没收标准包，并声称公开文本等于泄露健康数据。",
            "瑟琳娜逐页展示空白模板和隐私遮蔽栏，证明公开内容不含个人记录。",
            "苏菲亚登记到场机构领取的编号副本，并向独立审计员递交触发通知。",
        ],
        "visible_payoff": "首批带编号的纸质标准包由多家场馆领取，奥瑞恩无法再把协议文本与个人病历混为一谈。",
        "ending": "审计员收下触发通知，奥瑞恩法务总监只能带着未能扣押的空箱离场。",
        "must_include": ["纸质许可边界", "编号副本登记", "第三方审计触发"],
        "must_not_include": ["下载", "公开个人病历", "法律诉讼结果", "奥瑞恩破产"],
        "detailed_synopsis": (
            "1991年10月20日，雾河城巡演发布会。麦珂公布《今日健康备忘录》的纸质标准包，许可场馆无偿印刷、"
            "抄录和改编空白流程，但首页明确写明个人病历、签名和当日体征不在公开范围。奥瑞恩法务总监企图以独家许可"
            "扣下纸箱，又故意把标准文本说成私人健康数据。瑟琳娜拆开一份空白模板逐栏说明隐私遮蔽设计，苏菲亚则给每个"
            "领取机构登记纸质副本编号，并将奥瑞恩的阻挠动作写入第三方审计触发通知。法务总监没能制造泄密丑闻，反而当众"
            "证明了奥瑞恩仍试图垄断规则文本。审计员收下通知，第一批标准包由场馆代表带走。"
        ),
    })
    first["artifact_creates"] = [artifact(
        "ART_209_OPEN_SOURCE_DECREE", 209, "健康协议纸质开放许可页", "document",
        ["blank_protocol_text", "print_and_adaptation_terms", "privacy_exclusions"],
        ["print_blank_protocol", "adapt_blank_protocol", "use_as_evidence_within_scope"],
        list(first["participants"]),
    )]

    second = milestone(event, 210)
    second.update({
        "timeline_start": "1991-10-21", "timeline_end": "1991-10-21",
        "chapter_title": "卷轴入卷与临时裁定",
        "chapter_goal": "在听证会上证明奥瑞恩独家许可主张缺乏一致来源，取得停止其单方解释的临时裁定。",
        "opening_conflict": "奥瑞恩申请紧急禁令，要求法院扣押纸质标准包并恢复其独家解释权。",
        "info_gap_use": "麦珂记得奥瑞恩会在附件编号上沿用旧版卷宗格式，苏菲亚据此提前核对今生取得的登记簿和证人签名。",
        "opponent_reaction": "奥瑞恩律师质疑卷轴证词的可采性，却无法解释起诉附件与法院登记副本的编号差异。",
        "action_sequence": [
            "奥瑞恩申请紧急禁令，声称纸质许可造成不可逆商业损失。",
            "苏菲亚提交敌情图谱索引和证人签名册，逐一对应证物保管编号。",
            "法院书记员比对起诉附件与登记副本，确认奥瑞恩材料存在来源矛盾。",
            "法官拒绝扣押标准包，并临时停止奥瑞恩执行独家许可和单方健康解释条款。",
        ],
        "visible_payoff": "紧急禁令被拒，奥瑞恩的独家许可与单方解释条款在后续审理前停止执行。",
        "ending": "苏菲亚接过盖有收讫章的证物目录，正式承担后续证据保管职责。",
        "must_include": ["敌情图谱索引", "证物编号比对", "临时裁定边界"],
        "must_not_include": ["董事被捕", "行业终身禁入", "奥瑞恩破产清算", "再次宣读开放许可"],
        "detailed_synopsis": (
            "1991年10月21日，雾河城高等法院举行紧急禁令听证。奥瑞恩要求扣押前一日发出的纸质健康协议标准包。"
            "苏菲亚没有把十米卷轴当作煽情道具，而是提交卷轴索引、证人签名册和逐件证物保管号；法院书记员据此比对出"
            "奥瑞恩起诉附件与登记副本的编号矛盾。律师质疑证词可采性，却无法说明自己的材料来源。法官只就本次禁令作出"
            "有限裁定：拒绝扣押标准包，并在后续审理前停止奥瑞恩执行独家许可和单方健康解释条款，不涉及破产、刑罚或行业"
            "禁入。苏菲亚接过盖有收讫章的证物目录，正式成为团队的首席证据官。"
        ),
    })
    second["artifact_creates"] = [
        artifact("ART_210_SCROLL_SUBMISSION", 210, "敌情图谱证物索引", "evidence",
                 ["indexed_testimony", "custody_numbers"], ["submit_to_court", "use_as_evidence_within_scope"], list(second["participants"])),
        artifact("ART_210_INTERIM_RULING", 210, "紧急禁令听证临时裁定", "legal_document",
                 ["deny_seizure", "enjoin_exclusive_license_pending_review"], ["enforce_stated_interim_relief", "use_as_evidence_within_scope"], list(second["participants"])),
    ]
    second["artifact_refs"] = [{
        "artifact_id": "ART_209_OPEN_SOURCE_DECREE", "timeline_scope": "current",
        "display_name": "健康协议纸质开放许可页",
        "purpose": "界定被申请扣押的标准文本及其隐私边界",
        "required_permission": "use_as_evidence_within_scope",
        "scope_assertion": "不得超出创建时的granted_permissions",
    }]


def repair_ec106(event: dict[str, Any]) -> None:
    event["name"] = "回声谷盲选风暴与医疗执行页"
    event["timeline_years"] = "1991"
    event["source_event_direction"] = event["source_event_direction"].replace(
        "1991年10月暴雨夜穹顶投影失焦的具体时刻", "1987年11月暴雨夜穹顶投影失焦的具体时刻"
    )
    event["prev_life_tragedy"] = "1987年11月暴雨夜，VIP通道拥堵延误医疗支援，麦珂病情恶化。"
    event["info_gap_from_prev_life"] = "1987年11月暴雨夜19:42的投影失焦时刻与声压阈值，以及奥瑞恩会提前印好隔离令的流程习惯。"
    event["preemptive_avoidance"] = (
        "麦珂要求瑟琳娜将七套备用光路转为实战待机并附机械校准证书；苏菲亚提前登记法务文件编号；"
        "观众入场券背面印有自愿安全协作者承诺卡。"
    )
    event["bait_and_evidence"] = (
        "奥瑞恩在医生检查前便拿出预先填好编号的隔离令，暴露隔离决定早于健康判断；"
        "备用光路和观众协作网络则保证医疗通道不被VIP分流堵塞。"
    )
    event["protagonist_gain"] = "既有医疗自主权首次在大型演出现场形成可执行记录，并获得随机座次流程的场馆使用许可。"
    event["villain_loss"] = "奥瑞恩预设隔离的流程被当场记录，失去借暴雨清洗后台人员和强制分流观众的现场借口。"
    event["cluster_outcome"] = "盲选座次与备用光路经受暴雨检验，既有医疗自主权完成首次场馆执行，且无人被强制隔离。"
    event["main_characters"] = list(dict.fromkeys(event.get("main_characters") or []))
    event["state_transitions"] = [
        {
            "domain": "rights", "entity_id": "RIGHT_AUDIENCE_COLLAB_01",
            "state_key": "audience_collaborator_status", "from": "passive_spectator",
            "to": "active_safety_collaborator", "irreversible": False,
            "evidence": "ART_211_PROMISE_CARD", "effect_type": "protagonist_gain",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
        {
            "domain": "asset", "entity_id": "ASSET_EQUIP_OPTICAL_01",
            "state_key": "optical_lens_calibration_status", "from": "unverified_test_mode",
            "to": "certified_practice_ready", "irreversible": False,
            "evidence": "ART_211_CALIBRATION_CERT", "effect_type": "protagonist_gain",
            "source_entity_label": "EQUIP_OPTICAL_01",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
        {
            "domain": "health", "entity_id": "RIGHT_MEDICAL_CONTROL_01",
            "state_key": "medical_decision_protocol_status", "from": "legally_recognized_not_field_tested",
            "to": "venue_execution_recorded", "irreversible": False,
            "evidence": "ART_212_HEALTH_EXECUTION_LOG", "effect_type": "villain_loss",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
    ]

    first = milestone(event, 211)
    first.update({
        "timeline_start": "1991-10-22", "timeline_end": "1991-10-22",
        "chapter_title": "承诺卡与七路校准",
        "chapter_goal": "以随机座次和自愿承诺卡建立观众安全协作网络，并完成七套备用光路的现场校准。",
        "info_gap_use": "麦珂只公开天气风险，不透露前世；他按记忆中的19:42失焦点要求瑟琳娜提前完成七路切换演练。",
        "action_sequence": [
            "麦珂在入口说明随机座次规则，明确取消VIP专用通道。",
            "观众阅读票根背面的自愿承诺卡，按分区组成人墙并保持医疗通道畅通。",
            "瑟琳娜展示七套光路的逐路机械校准记录，拒绝奥瑞恩接管控制台。",
            "苏菲亚在法务文件桌登记一批尚未填写观察结果的隔离令编号。",
        ],
        "visible_payoff": "观众在不接受强制隔离的前提下维持入口秩序，七套备用光路全部通过现场切换。",
        "ending": "19:41，第一阵暴雨击中穹顶，瑟琳娜的手停在第二路机械切换杆上。",
        "must_include": ["承诺卡自愿边界", "七路校准记录", "医疗通道保持畅通"],
        "must_not_include": ["承诺卡授予医疗决定权", "现代通讯工具", "未来科技词汇", "色带证据"],
        "detailed_synopsis": (
            "1991年10月22日傍晚，星港市回声谷体育馆入口。奥瑞恩安保总监坚持按票价划分VIP专用通道，麦珂则启用"
            "机械抽签形成的随机座次。票根背面的承诺卡只约定自愿协助疏散、保持医疗通道和服从现场安全员指引，不授予任何"
            "医疗或执法权。观众按分区形成疏导人墙，VIP通道无法单独封闭。后台，瑟琳娜逐路完成七套备用光路的机械校准，"
            "把签字记录钉在控制台旁；苏菲亚则在法务文件桌发现一批已经编好号、却尚未填写现场观察结果的隔离令。她只登记"
            "编号并请场馆文书员见证，没有擅自扣押。19:41，暴雨击中穹顶，入口秩序和医疗通道仍保持畅通。"
        ),
    })
    first["participants"] = list(dict.fromkeys(first.get("participants") or []))
    first["artifact_creates"] = [
        artifact("ART_211_PROMISE_CARD", 211, "观众自愿安全协作者承诺卡", "document",
                 ["voluntary_evacuations", "keep_medical_lane_clear", "follow_venue_safety_staff"],
                 ["coordinate_voluntary_evacuations", "use_as_evidence_within_scope"], list(first["participants"])),
        artifact("ART_211_CALIBRATION_CERT", 211, "七路光学机械校准记录", "critical_evidence",
                 ["seven_optical_routes", "mechanical_switch_test", "signed_calibration_results"],
                 ["operate_certified_optical_routes", "use_as_evidence_within_scope"], list(first["participants"])),
    ]

    second = milestone(event, 212)
    second.update({
        "chapter_title": "暴雨执行页与预印隔离令",
        "chapter_goal": "在暴雨峰值完成既有医疗自主协议的首次场馆执行，并证明奥瑞恩的隔离决定早于医学观察。",
        "participants": ["麦珂", "瑟琳娜", "苏菲亚", "玛莎", "巡演独立医师", "奥瑞恩法务代表"],
        "opening_conflict": "备用光路切换成功后，奥瑞恩法务代表仍拿出预印隔离令，要求在医生检查前带走麦珂。",
        "info_gap_use": "麦珂知道19:42是前世系统失焦与通道堵塞的重合点，因此要求医生、文书和光路切换同时留下纸面时间记录。",
        "opponent_reaction": "法务代表声称隔离令是临时填写，却无法解释观察栏空白时就已连续编号并盖章。",
        "action_sequence": [
            "19:42暴雨达到峰值，瑟琳娜切入第二备用光路，舞台画面保持清晰。",
            "奥瑞恩法务代表在医生检查前展示预印隔离令，要求立即终止演出。",
            "巡演独立医师完成现场体征检查，麦珂、医师和见证人苏菲亚签署既有备忘录的雨夜执行页。",
            "苏菲亚用前一章登记的连续编号证明隔离决定早于医学观察，场馆文书员将隔离令封入证物袋。",
            "观众协作者保持医疗通道畅通，演出按医师记录继续，无人遭到强制隔离。",
        ],
        "visible_payoff": "既有医疗自主协议留下首份场馆执行记录，预印隔离令进入证物链，暴雨演出零强制隔离完成。",
        "ending": "苏菲亚在敌情图谱上新增的不是人名，而是一条从预印编号通向法务文件桌的流程线。",
        "must_include": ["19:42备用光路切换", "雨夜健康执行页", "预印隔离令编号链", "医疗通道畅通"],
        "must_not_include": ["重新取得医疗自主权", "观众决定医疗事项", "现代法律术语", "未来医疗技术", "色带样本"],
        "detailed_synopsis": (
            "1991年10月22日19:42，暴雨达到峰值，瑟琳娜将穹顶投影切入第二备用光路，画面没有失焦。奥瑞恩法务代表"
            "仍在医生检查前拿出盖章隔离令，要求强制带走麦珂。巡演独立医师当场完成体征检查，确认没有触发停止演出的医学"
            "条件；麦珂、医师和见证人苏菲亚在已经获得法院承认的《今日健康备忘录》雨夜执行页上签字，玛莎只以家属身份"
            "在场，不冒充医生。苏菲亚拿出前一章由场馆文书员见证的编号记录，证明这批隔离令在观察栏空白时就已连续编号并"
            "盖章。法务代表无法解释，场馆文书员将原件封入证物袋。观众协作者始终保持医疗通道畅通，演出继续且无人被强制"
            "隔离。苏菲亚在敌情图谱上补入一条预设隔离流程线。"
        ),
    })
    second["artifact_creates"] = [
        artifact("ART_212_HEALTH_EXECUTION_LOG", 212, "今日健康备忘录雨夜执行页", "medical_record",
                 ["current_vitals", "medical_stop_threshold", "continue_or_stop_decision", "signing_times"],
                 ["record_current_medical_decision", "use_as_evidence_within_scope"], list(second["participants"])),
        artifact("ART_212_PREPRINTED_ISOLATION_ORDER", 212, "预印隔离令原件", "critical_evidence",
                 ["serial_number", "blank_observation_field", "preexisting_stamp"],
                 ["preserve_in_evidence_custody", "use_as_evidence_within_scope"], list(second["participants"])),
    ]
    second["artifact_refs"] = [
        {
            "artifact_id": "ART_211_PROMISE_CARD", "timeline_scope": "current",
            "display_name": "观众自愿安全协作者承诺卡",
            "purpose": "证明观众只承担自愿疏散和保持医疗通道职责",
            "required_permission": "use_as_evidence_within_scope",
            "scope_assertion": "不得扩张为医疗决定或执法权限",
        },
        {
            "artifact_id": "ART_211_CALIBRATION_CERT", "timeline_scope": "current",
            "display_name": "七路光学机械校准记录",
            "purpose": "证明备用光路已经完成逐路机械测试并由授权技术员操作",
            "required_permission": "use_as_evidence_within_scope",
            "scope_assertion": "不得扩张为非技术人员的控制台操作权",
        },
        {
            "artifact_id": "ART_209_OPEN_SOURCE_DECREE", "timeline_scope": "current",
            "display_name": "健康协议纸质开放许可页",
            "purpose": "引用既有健康协议标准文本及隐私边界",
            "required_permission": "use_as_evidence_within_scope",
            "scope_assertion": "不得超出创建时的granted_permissions",
        },
    ]


def repair_ec107(event: dict[str, Any]) -> None:
    event.update({
        "name": "灰桥转运清单与四点保管链",
        "timeline_years": "1991",
        "main_opponent": "奥瑞恩集团法务部总监 维克多·克伦威尔",
        "event_type": "legal_procedure",
        "solution_type": "legal_evidence",
        "prev_life_tragedy": "前世奥瑞恩在隔离争议后四十八小时内集中销毁法务废件，麦珂团队只留下口头指控，无法证明文件来自哪个部门和转运批次。",
        "info_gap_from_prev_life": "只有麦珂记得废件车会在暴雨演出散场后的深夜提前到达灰桥仓储区，以及旧转运单使用的双字母批次前缀。",
        "preemptive_avoidance": "麦珂只向苏菲亚提供仓储区、时间窗口和批次前缀；苏菲亚以今生取得的预印隔离令编号独立核验旧件行留底联和纸浆厂预约回执。",
        "bait_and_evidence": "麦珂提出用观众票根夹层藏证据诱使对手搜查，苏菲亚拒绝把观众卷入保管风险，改用旧件行老板、场馆文书员、独立档案库和封存回执组成四点保管链。",
        "villain_loss": "维克多的紧急收回令因缺少合同要求的双签和批次授权被拒，奥瑞恩失去在四十八小时窗口内取回并销毁该批法务废件的机会。",
        "protagonist_gain": "苏菲亚取得隔离令批次的今生转运留底联和纸浆预约回执，并建立可复核的四点证物保管链。",
        "relationship_change": "苏菲亚公开否决麦珂把证据藏入观众票根的诱饵方案；麦珂接受她对证据保管和公众风险的专业决定。",
        "cluster_outcome": "废件转运批次被锁定，紧急收回失败，隔离令来源从推测升级为有留底联、预约回执和连续封存号支撑的保管链。",
        "next_event_hook": "转运清单上的付款账户指向奥瑞恩的场外短期信贷工具，迫使团队转向下一簇财务做空线索。",
        "resolution_signature": {
            "attack_domain": "evidence_destruction",
            "counter_method": "independent_custody_chain",
            "resolver": "苏菲亚",
            "publicity": "institutional",
            "hero_gain_type": "traceable_provenance",
        },
    })
    event["source_event_direction"] = (
        "前世具体受害：奥瑞恩在隔离争议后四十八小时内集中销毁法务废件，团队因缺乏来源与转运记录而败诉；"
        "本事件独有的信息差：只有麦珂记得灰桥仓储区、提前到达的废件车和双字母批次前缀；"
        "今生提前动作：苏菲亚用今生取得的隔离令编号核验旧件行留底联与纸浆预约回执，并建立四点保管链；"
        "第213章可见小赢：转运留底联与预约回执完成编号对应；第214章新交锋：维克多持缺少双签的收回令抢件失败；"
        "阻力方现实损失：失去四十八小时内取回销毁该批废件的机会；主角现实收益：获得可复核的转运来源和独立保管链；"
        "不可逆结算键：废件批次进入独立档案库且生成连续封存回执；接回死亡控制主线：清除医疗隔离文件的销毁通道。"
    )
    event["state_transitions"] = [
        {
            "domain": "rights", "entity_id": "RIGHT_EVIDENCE_CHAIN_01",
            "state_key": "isolation_order_origin", "from": "suspected_preprinted_batch",
            "to": "matched_to_orion_transfer_batch", "irreversible": False,
            "evidence": "ART_213_TRANSFER_LEDGER_COPY", "effect_type": "protagonist_gain",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
        {
            "domain": "asset", "entity_id": "ASSET_INTANGIBLE_01",
            "state_key": "evidence_custody_chain", "from": "single_location_vulnerable",
            "to": "four_point_independent_custody", "irreversible": False,
            "evidence": "ART_214_FOUR_POINT_CUSTODY", "effect_type": "protagonist_gain",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
        {
            "domain": "rights", "entity_id": "RIGHT_LEGAL_CORP_OREON_01",
            "state_key": "destruction_window_access", "from": "pickup_still_possible",
            "to": "reclaim_rejected_and_batch_sealed", "irreversible": False,
            "evidence": "ART_214_REJECTED_RECLAIM_ORDER", "effect_type": "villain_loss",
            "source_entity_label": "LEGAL_CORP_OREON_01",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
    ]

    first = milestone(event, 213)
    first.update({
        "timeline_start": "1991-10-22", "timeline_end": "1991-10-22",
        "scene": "星港市灰桥办公旧件行仓库",
        "chapter_title": "留底联与四十八小时",
        "chapter_goal": "用预印隔离令编号核对法务废件转运留底联和纸浆预约回执，在销毁车到达前锁定批次来源。",
        "participants": ["苏菲亚", "麦珂", "灰桥旧件行老板", "场馆文书员"],
        "opening_conflict": "纸浆厂废件车将提前到达，旧件行老板担心违约，不愿让苏菲亚查看留底联。",
        "info_gap_use": "麦珂只提供前世记得的灰桥仓储区、四十八小时窗口和双字母前缀；全部证据由苏菲亚用今生编号取得。",
        "opponent_reaction": "维克多得知有人核对批次，命人把原定次日的废件车提前到当天下午。",
        "action_sequence": [
            "麦珂提出把关键留底联藏入观众承诺卡夹层，苏菲亚当面拒绝让观众承担搜查风险。",
            "苏菲亚用第212章预印隔离令的连续编号，与旧件行依法保存的转运留底联逐项核对。",
            "灰桥旧件行老板按合同出示纸浆厂预约回执，场馆文书员记录查看过程但不擅自扣押原件。",
            "三方确认双字母批次前缀、件数与法务文件桌来源一致，并制作带见证签名的留底联副本。",
        ],
        "visible_payoff": "隔离令编号与奥瑞恩法务废件批次完成今生纸面对应，销毁车到达前已有两处独立留档。",
        "ending": "仓库外传来货车换挡声，原定次日的废件车提前停在卷帘门前。",
        "must_include": ["苏菲亚拒绝票根藏证", "双字母批次前缀", "纸浆厂预约回执", "两处独立留档"],
        "must_not_include": ["苏菲亚拥有前世记忆", "色带证据", "现代电子设备", "擅自扣押原件"],
        "detailed_synopsis": (
            "1991年10月22日深夜，暴雨演出散场后，苏菲亚带着第212章预印隔离令的编号记录来到星港市灰桥办公旧件行仓库。"
            "麦珂只提供自己前世记得的灰桥仓储区、四十八小时窗口和双字母批次前缀，并提议把关键副本藏进观众承诺卡。"
            "苏菲亚明确拒绝让普通观众承担被搜查和保管失败的风险。她在场馆文书员见证下，与旧件行依法保存的奥瑞恩法务"
            "废件转运留底联逐项核对，确认隔离令编号落在同一批次；老板随后出示纸浆厂预约回执。原件仍由店方按合同保管，"
            "苏菲亚只制作见证副本并登记去向。批次、件数、来源桌位形成今生证据对应时，维克多已把废件车提前到当夜。"
        ),
    })
    first["scenes"] = [{
        "sequence": 1, "location": first["scene"], "is_primary": True,
        "temporal_mode": "current", "transition_cue": "卷帘门外传来提前到达的货车声",
    }]
    first["artifact_creates"] = [
        artifact("ART_213_TRANSFER_LEDGER_COPY", 213, "奥瑞恩法务废件转运留底联见证副本", "critical_evidence",
                 ["batch_prefix", "serial_range", "item_count", "source_desk", "witness_signatures"],
                 ["compare_document_batch", "use_as_evidence_within_scope"], list(first["participants"])),
        artifact("ART_213_PULP_BOOKING_RECEIPT", 213, "纸浆厂废件预约回执", "business_record",
                 ["scheduled_pickup", "batch_prefix", "contracting_department"],
                 ["verify_scheduled_transfer", "use_as_evidence_within_scope"], list(first["participants"])),
    ]
    first["artifact_refs"] = [{
        "artifact_id": "ART_212_PREPRINTED_ISOLATION_ORDER", "timeline_scope": "current",
        "display_name": "预印隔离令原件", "purpose": "提供连续编号以核对废件批次",
        "required_permission": "use_as_evidence_within_scope", "scope_assertion": "只用于编号和来源核对",
    }]

    second = milestone(event, 214)
    second.update({
        "timeline_start": "1991-10-22", "timeline_end": "1991-10-22",
        "scene": "灰桥办公旧件行装卸区",
        "chapter_title": "收回令与四点保管链",
        "chapter_goal": "核验并拒绝缺少双签的紧急收回令，把转运证据送入四点独立保管链。",
        "participants": ["苏菲亚", "麦珂", "维克多·克伦威尔", "灰桥旧件行老板", "场馆文书员", "独立档案员"],
        "opening_conflict": "维克多随提前到达的废件车出示紧急收回令，要求把留底联、预约回执和整批废件一并带走。",
        "info_gap_use": "麦珂只识别出前世常用的双字母批次前缀；苏菲亚依靠今生合同条款和签署栏核验收回令。",
        "opponent_reaction": "维克多催促司机先装车后补签，并试图用新盖的部门章替代缺失的资产保管人签名。",
        "action_sequence": [
            "苏菲亚按旧件行合同核对收回令，指出只有法务签名而缺少资产保管人第二签。",
            "维克多急于补盖部门章，印台粘在袖口，在未授权收回令背面留下反向印记和新的时间痕迹。",
            "旧件行老板拒绝放行，场馆文书员登记拒收理由，独立档案员为见证副本和预约回执生成连续封存号。",
            "苏菲亚建立店方原件、场馆登记、独立档案封存、团队只读副本四点保管链，并让麦珂签知悉而非控制授权。",
        ],
        "visible_payoff": "废件车空载离开，奥瑞恩错过四十八小时销毁窗口；转运来源和收回失败进入可复核保管链。",
        "ending": "苏菲亚在流程图上画出四个保管节点，转运清单的付款账户则指向下一条财务线。",
        "must_include": ["收回令缺少双签", "袖口反向印章", "废件车空载离开", "四点独立保管链"],
        "must_not_include": ["当场定罪", "终身监禁", "集团彻底崩塌", "色带磨损比对", "观众保管核心证据"],
        "detailed_synopsis": (
            "当天下午，维克多随提前到达的废件车闯入灰桥旧件行装卸区，出示紧急收回令，要求连同留底联和整批废件带走。"
            "苏菲亚按店方合同核对，发现文件只有法务签名，缺少资产保管人第二签。维克多命令司机先装车，又急着补盖部门章，"
            "印台粘住袖口，在收回令背面留下反向印记和新的时间痕迹。老板据此拒绝放行；场馆文书员记录理由，独立档案员为"
            "见证副本和预约回执生成连续封存号。苏菲亚建立店方原件、场馆登记、独立档案封存、团队只读副本四点保管链，"
            "拒绝让麦珂或观众单点控制证据。废件车空载离开，奥瑞恩错过销毁窗口。付款账户把调查引向下一簇财务做空线。"
        ),
    })
    second["scenes"] = [{
        "sequence": 1, "location": second["scene"], "is_primary": True,
        "temporal_mode": "current", "transition_cue": "提前到达的废件车倒入装卸区",
    }]
    second["artifact_creates"] = [
        artifact("ART_214_FOUR_POINT_CUSTODY", 214, "四点独立证物保管链登记", "custody_record",
                 ["store_original", "venue_witness_log", "independent_archive_seal", "team_read_only_copy"],
                 ["preserve_evidence_custody", "use_as_evidence_within_scope"], list(second["participants"])),
        artifact("ART_214_REJECTED_RECLAIM_ORDER", 214, "缺少双签的紧急收回令", "critical_evidence",
                 ["missing_second_signature", "reverse_stamp", "new_timestamp"],
                 ["document_rejected_pickup", "use_as_evidence_within_scope"], list(second["participants"])),
    ]
    second["artifact_refs"] = [
        {
            "artifact_id": "ART_213_TRANSFER_LEDGER_COPY", "timeline_scope": "current",
            "display_name": "奥瑞恩法务废件转运留底联见证副本", "purpose": "核验被要求收回的批次和店方原件",
            "required_permission": "use_as_evidence_within_scope", "scope_assertion": "不得替代店方原件",
        },
        {
            "artifact_id": "ART_213_PULP_BOOKING_RECEIPT", "timeline_scope": "current",
            "display_name": "纸浆厂废件预约回执", "purpose": "证明原定销毁取件时间和委托部门",
            "required_permission": "use_as_evidence_within_scope", "scope_assertion": "只证明预约记录",
        },
    ]


def repair_ec108(event: dict[str, Any]) -> None:
    """Replace the third repeated storm/medical-rights event with the EC107 finance hook."""
    event.update({
        "name": "运费账户回拨与短期信贷留痕",
        "timeline_years": "1991",
        "main_opponent": "奥瑞恩集团财务办公室",
        "opposition_type": "villain",
        "event_type": "finance_business",
        "solution_type": "financial_counter",
        "prev_life_tragedy": "前世清理法务废件的运费由一笔次日即展期的场外短期信贷支付；付款被迅速回拨后，团队只剩无法追索的账户尾号。",
        "info_gap_from_prev_life": "只有麦珂记得该信贷工具会在次日上午九点前办理展期，以及付款附言使用‘场地风险处置’而非废件运输。",
        "preemptive_avoidance": "苏菲亚不凭账户尾号指控所有人，而是请实际收款的灰桥旧件行依法授权清算行核对今生运费路径，并由独立审计员限定查询范围。",
        "bait_and_evidence": "奥瑞恩财务代理为抹去付款路径，谎称运费被重复支付并要求店方补签昨日日期的错误声明；回拨申请反而留下财务办公室印章、提交时点和错误的交易用途。",
        "villain_loss": "奥瑞恩未能以‘重复付款’名义收回并改写运费记录，其财务办公室与场外短期信贷工具的交易关联被保留下来。",
        "protagonist_gain": "苏菲亚取得仅限本笔运费的付款路径核对单、回拨拒绝联和短期信贷关联表，为后续调查建立可复核起点。",
        "relationship_change": "麦珂想凭前世账户尾号直接扩大调查，苏菲亚坚持先取得收款方授权；麦珂接受查询不得越过本笔交易的边界。",
        "cluster_outcome": "运费付款从可随时撤回的匿名尾号，变成由收款方、清算行和独立审计员共同见证的单笔交易链；尚未证明整个信贷工具违法。",
        "next_event_hook": "回拨申请把这笔信贷标注为‘场地设备风险处置’，指向奥瑞恩正在制造的下一次技术停演索赔。",
        "resolution_signature": {
            "attack_domain": "payment_record_recall",
            "counter_method": "payee_authorized_transaction_trace",
            "resolver": "苏菲亚",
            "publicity": "confidential_audit",
            "hero_gain_type": "documented_finance_link",
        },
        "continuity_writes": [
            "承接EC107纸浆预约回执上的付款账户，只核验同一笔运费。",
            "为EC109的场地设备风险索赔留下财务动机，但不提前处理光路证据。",
        ],
        "historical_anchor_ids": [],
    })
    event["source_event_direction"] = (
        "前世具体受害：销毁法务废件的运费经场外短期信贷支付并迅速回拨，付款路径消失；"
        "本事件独有信息差：只有麦珂记得次日上午九点展期窗口和‘场地风险处置’附言；"
        "今生提前动作：苏菲亚取得实际收款方授权，只核验第214章预约回执对应的单笔运费；"
        "第215章可见小赢：清算行确认付款路径与短期信贷结算席关联；"
        "第216章新交锋：奥瑞恩以重复付款为由要求补签倒签声明，回拨因用途和金额不符被拒；"
        "阻力方现实损失：无法撤回并改写本笔付款记录；主角现实收益：取得三方可复核的交易链；"
        "结算边界：只证明本笔交易关联，不冻结账户、不推定整个工具违法。"
    )
    event["main_characters"] = ["苏菲亚", "麦珂", "灰桥旧件行老板", "独立审计员"]
    event["canonical_cast"] = [
        item for item in event.get("canonical_cast") or []
        if item.get("character_id") in {"CHAR_87B8E75FFF6F", "CHAR_026AC753E27A"}
    ]
    event["main_character_ids"] = [item["character_id"] for item in event["canonical_cast"]]
    event["main_opponent_character_ids"] = []
    event.pop("main_opponent_character_id", None)
    event["state_transitions"] = [
        {
            "domain": "asset", "entity_id": "ASSET_214_DISPOSAL_PAYMENT_01",
            "state_key": "disposal_freight_payment_origin", "from": "unverified_account_suffix",
            "to": "matched_to_off_venue_credit_settlement_desk", "irreversible": False,
            "evidence": "ART_215_REMITTANCE_TRACE", "effect_type": "protagonist_gain",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
        {
            "domain": "rights", "entity_id": "RIGHT_ORION_PAYMENT_RECALL_01",
            "state_key": "single_transaction_recall_status", "from": "recall_requested",
            "to": "recall_rejected_record_preserved", "irreversible": False,
            "evidence": "ART_216_RECALL_REJECTION", "effect_type": "villain_loss",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
        {
            "domain": "asset", "entity_id": "ASSET_OFF_VENUE_CREDIT_01",
            "state_key": "credit_tool_investigation_status", "from": "unattributed_hint",
            "to": "single_payment_link_documented", "irreversible": False,
            "evidence": "ART_216_SHORT_CREDIT_LINK", "effect_type": "protagonist_gain",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
    ]

    first = milestone(event, 215)
    first.update({
        "timeline_start": "1991-10-23", "timeline_end": "1991-10-23",
        "scene": "灰港清算行企业付款柜台",
        "chapter_title": "收款授权与运费路径",
        "chapter_goal": "凭灰桥旧件行的收款方授权，只核验预约回执对应的单笔运费路径和付款附言。",
        "participants": ["苏菲亚", "麦珂", "灰桥旧件行老板", "独立审计员", "灰港清算行值班经理"],
        "opening_conflict": "清算行以客户保密为由拒绝透露付款人资料，麦珂提供的前世账户尾号也不能替代今生授权。",
        "info_gap_use": "麦珂只提示上午九点展期窗口和‘场地风险处置’附言；苏菲亚必须用今生预约回执、收款账簿和店方授权完成核验。",
        "opponent_reaction": "奥瑞恩财务办公室在核验过程中来电，声称付款可能重复并要求柜台停止出具书面回执。",
        "action_sequence": [
            "灰桥旧件行老板签署仅限本笔运费的收款方查询授权，独立审计员划掉账户余额和其他交易范围。",
            "值班经理以预约回执金额、收款日期和批次号核对清算底单，不接受麦珂单独提供的前世尾号。",
            "底单显示付款附言为‘场地风险处置’，结算席来自次日即需展期的场外短期信贷工具。",
            "苏菲亚取得带查询边界、底单页码和见证签名的运费付款路径核对单。",
        ],
        "visible_payoff": "第214章的运费账户与场外短期信贷结算席形成今生纸面关联，查询仍严格限于一笔交易。",
        "ending": "柜台电话再次响起，对方改称运费重复支付，要求店方立即签署退款声明。",
        "must_include": ["收款方限定授权", "场地风险处置附言", "九点展期窗口", "单笔运费路径核对单"],
        "must_not_include": ["再次夺取医疗权", "暴雨演出重演", "冻结整个账户", "前世记忆直接成为证据"],
        "detailed_synopsis": (
            "1991年10月23日上午，苏菲亚、麦珂和灰桥旧件行老板来到灰港清算行企业付款柜台。清算行拒绝凭账户尾号"
            "透露客户资料，苏菲亚也阻止麦珂把前世记忆当成查询权。老板签署仅限第214章纸浆预约回执所载运费的授权，"
            "独立审计员划去余额和其他交易。值班经理凭金额、日期和QF批次核对纸质清算底单，确认付款附言写成‘场地风险"
            "处置’，结算席来自当日上午九点需要展期的场外短期信贷工具。苏菲亚取得注明查询范围、底单页码和见证人的"
            "《单笔运费付款路径核对单》。这只证明一笔交易的路径，不能冻结账户或推定整个信贷工具违法。"
        ),
    })
    first["scenes"] = [{
        "sequence": 1, "location": first["scene"], "is_primary": True,
        "temporal_mode": "current", "transition_cue": "企业付款柜台开始核对纸质清算底单",
    }]
    first["artifact_creates"] = [
        artifact("ART_215_PAYEE_AUTHORIZATION", 215, "单笔运费收款方查询授权", "authorization",
                 ["one_freight_payment", "amount_date_batch_only"],
                 ["query_single_received_payment", "use_as_evidence_within_scope"], list(first["participants"])),
        artifact("ART_215_REMITTANCE_TRACE", 215, "单笔运费付款路径核对单", "business_record",
                 ["freight_amount", "settlement_desk", "payment_memo", "ledger_page"],
                 ["verify_single_payment_path", "use_as_evidence_within_scope"], list(first["participants"])),
    ]
    first["artifact_refs"] = [{
        "artifact_id": "ART_213_PULP_BOOKING_RECEIPT", "timeline_scope": "current",
        "display_name": "纸浆厂废件预约回执", "purpose": "提供单笔运费金额、日期和批次核验范围",
        "required_permission": "use_as_evidence_within_scope", "scope_assertion": "不得扩张查询其他账户交易",
    }]

    second = milestone(event, 216)
    second.update({
        "timeline_start": "1991-10-23", "timeline_end": "1991-10-23",
        "scene": "灰港清算行企业付款柜台",
        "chapter_title": "倒签退款声明与回拨拒绝联",
        "chapter_goal": "拒绝奥瑞恩以重复付款名义倒签退款声明，保住单笔交易记录并限定财务关联结论。",
        "participants": ["苏菲亚", "麦珂", "灰桥旧件行老板", "独立审计员", "灰港清算行值班经理", "奥瑞恩财务代理"],
        "opening_conflict": "奥瑞恩财务代理带来已填昨日日期的退款声明，要求店方承认运费重复并允许原路回拨。",
        "info_gap_use": "麦珂记得前世回拨会赶在展期前完成，但今生是否重复付款只能由店方账簿和清算底单证明。",
        "opponent_reaction": "财务代理先说两笔付款，核对时却把纸浆预约金额与另一笔场地设备费用相加，暴露所谓重复款用途不同。",
        "action_sequence": [
            "旧件行老板拒绝签署预填昨日日期的退款声明，值班经理分别核对两笔金额和用途。",
            "独立审计员确认第二笔属于场地设备风险费用，不能冲销废件运费，并记录代理前后矛盾的口径。",
            "清算行在回拨申请上盖拒绝章，保留财务办公室提交印章、时间和交易用途。",
            "苏菲亚把付款路径核对单与回拨拒绝联编成场外短期信贷关联表，注明结论只限本笔交易。",
        ],
        "visible_payoff": "运费记录未被撤回，奥瑞恩财务办公室与短期信贷结算席的单笔关联进入三方见证文件。",
        "ending": "另一笔‘场地设备风险处置费’的编号，把调查引向下一次技术停演索赔。",
        "must_include": ["预填昨日日期的退款声明", "两笔用途不同", "回拨申请被拒", "单笔关联边界"],
        "must_not_include": ["认定整个信贷工具违法", "冻结账户", "集团破产", "医疗抢救", "备用光路反杀"],
        "detailed_synopsis": (
            "同日上午，奥瑞恩财务代理赶到清算行，递出一张已经填成十月二十二日的退款声明，要求旧件行承认运费重复。"
            "老板拒绝倒签。值班经理逐笔核对后发现，代理所谓的第二笔款项金额不同，用途是场地设备风险处置，不能冲销"
            "废件运费；代理却把两笔金额相加来制造重复付款。独立审计员记录其前后口径，清算行在回拨申请上盖拒绝章，"
            "保留奥瑞恩财务办公室的提交印章和时点。苏菲亚将付款路径核对单、回拨拒绝联编成《场外短期信贷单笔关联表》，"
            "明确它只证明本笔运费与结算席有关，不代表整个工具违法。另一笔场地设备费用成为下一簇的技术索赔线索。"
        ),
    })
    second["scenes"] = [{
        "sequence": 1, "location": second["scene"], "is_primary": True,
        "temporal_mode": "current", "transition_cue": "奥瑞恩财务代理把倒填日期的退款声明推过柜台",
    }]
    second["artifact_creates"] = [
        artifact("ART_216_RECALL_REJECTION", 216, "重复付款回拨申请拒绝联", "business_record",
                 ["rejected_recall", "submission_stamp", "submission_time", "transaction_purpose"],
                 ["preserve_recall_result", "use_as_evidence_within_scope"], list(second["participants"])),
        artifact("ART_216_SHORT_CREDIT_LINK", 216, "场外短期信贷单笔关联表", "audit_record",
                 ["single_freight_payment", "settlement_desk", "limited_conclusion"],
                 ["investigate_documented_single_link", "use_as_evidence_within_scope"], list(second["participants"])),
    ]
    second["artifact_refs"] = [
        {
            "artifact_id": "ART_215_PAYEE_AUTHORIZATION", "timeline_scope": "current",
            "display_name": "单笔运费收款方查询授权", "purpose": "限制继续核验的交易范围",
            "required_permission": "query_single_received_payment", "scope_assertion": "不得查询余额或其他交易",
        },
        {
            "artifact_id": "ART_215_REMITTANCE_TRACE", "timeline_scope": "current",
            "display_name": "单笔运费付款路径核对单", "purpose": "与回拨申请的金额和用途逐项比较",
            "required_permission": "use_as_evidence_within_scope", "scope_assertion": "只证明该笔运费路径",
        },
    ]


def repair_ec109(event: dict[str, Any]) -> None:
    """Turn the repeated storm/light switch into an inspection-record investigation."""
    event.update({
        "name": "RV检验费与错位透镜序号",
        "timeline_years": "1991",
        "main_opponent": "奥瑞恩设备索赔办公室及灰港光学检测站主管",
        "opposition_type": "technical",
        "event_type": "legal_procedure",
        "solution_type": "legal_evidence",
        "prev_life_tragedy": "前世奥瑞恩凭一份湿度不合格证书扣走回声谷光学组件，并以设备风险为由拒付演出结算；团队没有核对证书所写组件是否真正送检。",
        "info_gap_from_prev_life": "只有麦珂记得旧证书固定写着RH-61、十四点十分和六孔底座；这些只能作为寻找今生记录的方向。",
        "preemptive_avoidance": "苏菲亚以第216章RV付款编号定位收款检测站，瑟琳娜和场馆设备主管则用今生库存卡、铅封和收发簿核对组件是否离场。",
        "bait_and_evidence": "检测站主管想把未执行的送检单补成‘现场巡检’，却在证书上沿用六孔底座和不存在的收件铅封号，暴露费用、序号与实物不对应。",
        "villain_loss": "奥瑞恩无法凭错位序号的湿度证书扣走回声谷组件或启动本次设备索赔，检测站的未执行服务被记入独立复核。",
        "protagonist_gain": "团队取得RV服务单、场馆组件库存卡、拒收湿度证书和独立复校预约，证明一笔已付款检验并未按单执行。",
        "relationship_change": "麦珂接受瑟琳娜对设备实物和检验结论的专业主导，不再把前世记住的阈值当作当前测量值。",
        "cluster_outcome": "RV付款对应的检验服务被证明未按送检单执行，错位序号证书被场馆拒收；光路没有再次切换，争议转入独立复校。",
        "next_event_hook": "被拒证书的紧急联系人栏出现玛莎姓名缩写和一枚未经本人确认的家属章，引出下一簇家属签署边界。",
        "resolution_signature": {
            "attack_domain": "false_equipment_inspection",
            "counter_method": "physical_serial_and_receiving_ledger_match",
            "resolver": "瑟琳娜",
            "publicity": "technical_record",
            "hero_gain_type": "rejected_mismatched_certificate",
        },
        "continuity_writes": [
            "承接EC108的RV场地设备风险处置费，只调查该笔检验服务。",
            "不重复EC106的暴雨切光；七路校准仍保持已完成状态。",
        ],
        "historical_anchor_ids": [],
    })
    event["source_event_direction"] = (
        "前世具体受害：湿度不合格证书导致光学组件被扣和演出结算被拒；"
        "本事件独有信息差：麦珂只记得RH-61、十四点十分和六孔底座；"
        "今生提前动作：苏菲亚用RV付款编号找服务单，瑟琳娜用库存卡、实物底座和收发簿独立核对；"
        "第217章可见小赢：确认收费服务单存在但组件从未出库送检；"
        "第218章新交锋：对方持湿度证书要求扣件，因序号、孔位和铅封号错位被拒；"
        "阻力方现实损失：无法用该证书扣件或启动本次索赔；主角现实收益：取得未执行检验的可复核记录；"
        "结算边界：只否定本证书，不宣称所有设备永不出故障。"
    )
    event["main_characters"] = ["瑟琳娜", "苏菲亚", "麦珂", "场馆设备主管"]
    event["canonical_cast"] = [
        item for item in event.get("canonical_cast") or []
        if item.get("character_id") in {"CHAR_4E24DD1EEE76", "CHAR_87B8E75FFF6F", "CHAR_026AC753E27A"}
    ]
    event["main_character_ids"] = [item["character_id"] for item in event["canonical_cast"]]
    event["main_opponent_character_ids"] = []
    event.pop("main_opponent_character_id", None)
    event["state_transitions"] = [
        {
            "domain": "asset", "entity_id": "ASSET_RV_INSPECTION_SERVICE_01",
            "state_key": "rv_inspection_performance_status", "from": "paid_but_unverified",
            "to": "service_not_received_by_lab", "irreversible": False,
            "evidence": "ART_217_RV_SERVICE_ORDER", "effect_type": "protagonist_gain",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
        {
            "domain": "rights", "entity_id": "RIGHT_ORION_EQUIPMENT_CLAIM_01",
            "state_key": "humidity_certificate_enforcement", "from": "certificate_asserted",
            "to": "rejected_for_serial_mismatch", "irreversible": False,
            "evidence": "ART_218_REJECTED_HUMIDITY_CERT", "effect_type": "villain_loss",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
        {
            "domain": "asset", "entity_id": "ASSET_EQUIP_OPTICAL_01",
            "state_key": "independent_recalibration_status", "from": "not_scheduled",
            "to": "venue_requested_and_seal_recorded", "irreversible": False,
            "evidence": "ART_218_RECALIBRATION_BOOKING", "effect_type": "protagonist_gain",
            "source_entity_label": "EQUIP_OPTICAL_01",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
    ]

    first = milestone(event, 217)
    first.update({
        "timeline_start": "1991-10-23", "timeline_end": "1991-10-23",
        "scene": "灰港光学检测站档案室",
        "chapter_title": "RV服务单与空白收件栏",
        "chapter_goal": "以RV付款编号核对检测站服务单、收件簿和场馆库存卡，判断光学组件是否真正送检。",
        "participants": ["瑟琳娜", "苏菲亚", "麦珂", "场馆设备主管", "灰港光学检测站档案员"],
        "opening_conflict": "检测站承认收到费用，却以委托方保密为由拒绝让场馆设备所有人查看具体组件的收件记录。",
        "info_gap_use": "麦珂只提示前世证书上的RH-61、十四点十分和六孔底座；瑟琳娜坚持先从今生实物序号与收发簿查起。",
        "opponent_reaction": "检测站主管把‘送检’改口为‘现场巡检’，试图解释收件栏和铅封号为何空白。",
        "action_sequence": [
            "场馆设备主管出示所有权和库存卡，只授权核对RV服务单所列组件。",
            "苏菲亚用第216章RV付款编号找到已结算服务单，记录其组件序号、六孔底座和十四点十分完成时点。",
            "瑟琳娜比对场馆库存卡与当日钥匙领用簿，确认对应四孔组件未离开回声谷设备间。",
            "检测站收件簿没有该序号或铅封号，档案员制作空白收件栏见证副本。",
        ],
        "visible_payoff": "RV服务已收费结算，但服务单所称组件没有进入检测站，‘已送检’无法与收发记录对应。",
        "ending": "检测站主管改称检验在场馆完成，并通知奥瑞恩把湿度证书直接送到回声谷。",
        "must_include": ["RV付款编号", "空白收件栏", "四孔实物与六孔服务单", "组件未离开场馆"],
        "must_not_include": ["再次切换备用光路", "暴雨重演", "麦珂记忆充当测量值", "认定全部检测造假"],
        "detailed_synopsis": (
            "1991年10月23日上午，苏菲亚凭第216章RV付款编号来到灰港光学检测站。场馆设备主管以设备所有人身份只授权"
            "核对该笔服务，检测站档案员找到一张已经结算的服务单：组件代号RH-61、六孔底座、十四点十分完成。瑟琳娜"
            "带来的今生库存卡却显示回声谷组件为四孔底座，当日钥匙和出库栏均无人签领；检测站收件簿也没有对应序号和"
            "铅封号。麦珂记得的三个词只帮助定位记录，不被当作测量结果。主管于是改口称做的是现场巡检，准备让奥瑞恩"
            "把湿度证书直接送到场馆。档案员依法制作服务单和空白收件栏的限定见证副本。"
        ),
    })
    first["scenes"] = [{
        "sequence": 1, "location": first["scene"], "is_primary": True,
        "temporal_mode": "current", "transition_cue": "档案员翻到RV编号对应的纸质服务单",
    }]
    first["artifact_creates"] = [
        artifact("ART_217_RV_SERVICE_ORDER", 217, "RV光学检验服务单见证副本", "business_record",
                 ["rv_payment_reference", "component_serial", "mount_type", "claimed_completion_time", "blank_receiving_fields"],
                 ["verify_paid_inspection_scope", "use_as_evidence_within_scope"], list(first["participants"])),
        artifact("ART_217_LENS_INVENTORY", 217, "回声谷光学组件库存核对卡", "inventory_record",
                 ["actual_serial", "four_hole_mount", "key_checkout", "outbound_log"],
                 ["verify_venue_component_identity", "use_as_evidence_within_scope"], list(first["participants"])),
    ]
    first["artifact_refs"] = [{
        "artifact_id": "ART_216_SHORT_CREDIT_LINK", "timeline_scope": "current",
        "display_name": "场外短期信贷单笔关联表", "purpose": "提供RV场地设备费用的付款编号和收款检测站",
        "required_permission": "investigate_documented_single_link", "scope_assertion": "只调查RV对应服务",
    }]

    second = milestone(event, 218)
    second.update({
        "timeline_start": "1991-10-23", "timeline_end": "1991-10-23",
        "scene": "回声谷体育馆设备验收间",
        "chapter_title": "六孔证书与四孔实物",
        "chapter_goal": "现场核对奥瑞恩湿度证书与实物序号，拒绝错位证书扣件并预约独立复校。",
        "participants": ["瑟琳娜", "苏菲亚", "麦珂", "场馆设备主管", "检测站主管", "奥瑞恩设备索赔代表", "独立实验室检视员"],
        "opening_conflict": "奥瑞恩持湿度不合格证书要求立即拆走组件，并以不交件就启动设备索赔相威胁。",
        "info_gap_use": "麦珂认出RH-61和十四点十分是前世旧证书特征，但由瑟琳娜测量孔位、序号和现存铅封。",
        "opponent_reaction": "检测站主管发现证书写六孔后，试图贴上四孔更正签并把变更说成排版错误。",
        "action_sequence": [
            "场馆设备主管把证书置于验收台，不允许奥瑞恩在核验前拆件。",
            "瑟琳娜展示四孔实物、库存卡和未破坏的场馆铅封，逐项对照证书的六孔底座与不存在的收件铅封号。",
            "检测站主管临时粘贴更正签，复写底页却保留更正发生在提交后的压痕和时点。",
            "场馆拒收该证书，保留限定复写联；另一家独立实验室登记原地复校预约，并先出具无源结构独立检视单。",
        ],
        "visible_payoff": "错位湿度证书不能用于本次扣件或索赔，组件留在场馆封存等待独立复校。",
        "ending": "苏菲亚在证书紧急联系人栏发现玛莎姓名缩写和一枚未经核验的家属章。",
        "must_include": ["六孔证书与四孔实物", "不存在的收件铅封号", "提交后更正压痕", "无源结构独立检视单"],
        "must_not_include": ["现场证明设备永不故障", "再次表演反杀", "永久禁止全部索赔", "玛莎已经授权家属章"],
        "detailed_synopsis": (
            "当日下午，奥瑞恩设备索赔代表把湿度不合格证书送到回声谷设备验收间，要求立即拆走组件。瑟琳娜在场馆"
            "设备主管见证下展示四孔实物、库存卡和未破坏的场馆铅封；证书却写六孔底座，并引用一个从未进入检测站收件簿"
            "的铅封号。检测站主管慌忙贴四孔更正签，复写底页留下提交后才书写的压痕和时间。场馆据此拒收本证书，但不"
            "宣称设备永不故障；组件原地封存，由另一家实验室登记独立复校，并先出具只确认无源光学结构、不评价性能的"
            "独立检视单。奥瑞恩无法用这份错位证书扣件或启动本次索赔。"
            "苏菲亚随后发现紧急联系人栏出现玛莎缩写和一枚未经本人确认的家属章。"
        ),
    })
    second["scenes"] = [{
        "sequence": 1, "location": second["scene"], "is_primary": True,
        "temporal_mode": "current", "transition_cue": "湿度证书被放上设备验收台",
    }]
    second["artifact_creates"] = [
        artifact("ART_218_REJECTED_HUMIDITY_CERT", 218, "错位序号湿度证书拒收联", "technical_record",
                 ["six_hole_claim", "four_hole_actual", "missing_receiving_seal", "post_submission_correction"],
                 ["reject_this_certificate_for_claim", "use_as_evidence_within_scope"], list(second["participants"])),
        artifact("ART_218_RECALIBRATION_BOOKING", 218, "光学组件原地独立复校预约", "technical_record",
                 ["actual_serial", "existing_venue_seal", "independent_lab", "on_site_recalibration"],
                 ["perform_independent_recalibration", "use_as_evidence_within_scope"], list(second["participants"])),
        artifact("ART_218_PASSIVE_OPTICS_INSPECTION", 218, "无源光学结构独立检视单", "technical_record",
                 ["actual_serial", "passive_optical_structure", "no_electronic_component", "no_performance_conclusion"],
                 ["verify_passive_optical_structure", "use_as_evidence_within_scope"], list(second["participants"])),
    ]
    second["artifact_refs"] = [
        {
            "artifact_id": "ART_217_RV_SERVICE_ORDER", "timeline_scope": "current",
            "display_name": "RV光学检验服务单见证副本", "purpose": "核对证书所称组件和收件铅封",
            "required_permission": "use_as_evidence_within_scope", "scope_assertion": "只核对RV服务记录",
        },
        {
            "artifact_id": "ART_217_LENS_INVENTORY", "timeline_scope": "current",
            "display_name": "回声谷光学组件库存核对卡", "purpose": "证明今生实物序号、孔位和出库状态",
            "required_permission": "verify_venue_component_identity", "scope_assertion": "不代表设备性能结论",
        },
    ]


def repair_ec110(event: dict[str, Any]) -> None:
    """Give Martha an independent boundary-setting arc without granting proxy control."""
    event.update({
        "name": "家属联络章的边界与停用回执",
        "timeline_years": "1991",
        "main_opponent": "奥瑞恩巡演合同联络办公室",
        "opposition_type": "institutional",
        "event_type": "family_relationship",
        "solution_type": "relationship_choice",
        "prev_life_tragedy": "前世奥瑞恩一面说玛莎‘只是保姆、无权过问’，一面又在需要背书时冒用她的家属章，令她既被排除又被迫承担责任。",
        "info_gap_from_prev_life": "只有麦珂记得对方曾使用‘你没有签字权’羞辱玛莎，也记得椭圆家属章最初只为巡演紧急联络制作。",
        "preemptive_avoidance": "麦珂想赋予玛莎最终否决权以补偿前世，玛莎拒绝替成年儿子作单方决定，改为盘点今生印章流转并声明家属签署只确认身份和联络。",
        "bait_and_evidence": "奥瑞恩联络员以为玛莎会接受‘最终家属权’，主动拿出盖章证书要求她追认；章面缺口和领用清册却证明该章超范围使用且未归还。",
        "villain_loss": "奥瑞恩无法再用这枚家属联络章为设备证书或处置决定背书，本次家属同意主张被场馆记录处拒绝。",
        "protagonist_gain": "玛莎建立家属签署范围声明、印章使用清册、停用回执和双人身份回拨登记，获得发声与核验权而非替代麦珂同意权。",
        "relationship_change": "麦珂承认保护母亲不等于把自己的决定责任转交给她；玛莎从被动亲属转为能独立设定边界的家庭成员。",
        "cluster_outcome": "被冒用的椭圆家属章完成停用，既有盖章文件须逐件回拨核验；家属身份不再被奥瑞恩选择性放大或抹去。",
        "next_event_hook": "家属背书失效后，奥瑞恩转而向海关举报无源光学组件含电子元件，触发下一簇入境查验。",
        "resolution_signature": {
            "attack_domain": "misused_family_stamp",
            "counter_method": "scope_declaration_and_stamp_revocation",
            "resolver": "玛莎",
            "publicity": "records_office",
            "hero_gain_type": "family_identity_boundary",
        },
        "continuity_writes": [
            "承接EC109湿度证书上的玛莎缩写与未经核验家属章。",
            "不重复医疗自主权；家属章明确不授予替代医疗、技术或合同同意。",
        ],
        "historical_anchor_ids": [],
    })
    event["source_event_direction"] = (
        "前世具体受害：玛莎被排除于知情之外，却又被冒用家属身份承担责任；"
        "本事件独有信息差：麦珂记得羞辱原话和椭圆章原本仅供紧急联络；"
        "今生提前动作：玛莎拒绝最终否决权，亲自核对章面、领用人和使用范围；"
        "第219章可见小赢：查明联络章未归还并签署家属范围声明；"
        "第220章新交锋：奥瑞恩要求追认设备证书，场馆凭停用回执和双人回拨规则拒绝；"
        "阻力方现实损失：本次家属背书失效；主角现实收益：获得身份核验和知情边界；"
        "结算边界：玛莎不替成年麦珂作医疗、技术或合同决定。"
    )
    event["main_characters"] = ["玛莎", "麦珂", "苏菲亚", "奥瑞恩巡演合同联络员"]
    event["canonical_cast"] = [
        item for item in event.get("canonical_cast") or []
        if item.get("character_id") in {"CHAR_0037905289BB", "CHAR_026AC753E27A", "CHAR_87B8E75FFF6F"}
    ]
    event["main_character_ids"] = [item["character_id"] for item in event["canonical_cast"]]
    event["main_opponent_character_ids"] = []
    event.pop("main_opponent_character_id", None)
    event["state_transitions"] = [
        {
            "domain": "rights", "entity_id": "RIGHT_MARSHA_FAMILY_IDENTITY_01",
            "state_key": "family_signature_scope", "from": "ambiguous_blanket_proxy",
            "to": "identity_and_contact_only", "irreversible": False,
            "evidence": "ART_219_HEALTH_MEMO_CERTIFIED", "effect_type": "protagonist_gain",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
        {
            "domain": "character", "entity_id": "CHAR_0037905289BB",
            "state_key": "family_boundary_role", "from": "identity_used_by_others",
            "to": "independent_scope_setter", "irreversible": False,
            "evidence": "ART_220_STAMP_REVOCATION", "effect_type": "relationship_change",
            "source_entity_label": "CHAR_0037905289BB",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
        {
            "domain": "rights", "entity_id": "RIGHT_ORION_FAMILY_ENDORSEMENT_01",
            "state_key": "family_stamp_reliance", "from": "asserted_on_equipment_certificate",
            "to": "stamp_revoked_and_this_endorsement_rejected", "irreversible": False,
            "evidence": "ART_220_FAMILY_ENDORSEMENT_REJECTION", "effect_type": "villain_loss",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
    ]

    first = milestone(event, 219)
    first.update({
        "timeline_start": "1991-10-23", "timeline_end": "1991-10-23",
        "scene": "回声谷巡演家属联络室",
        "chapter_title": "椭圆章与拒绝代替同意",
        "chapter_goal": "让玛莎本人核对湿度证书上的家属章，盘点领用记录并明确家属签署范围。",
        "participants": ["玛莎", "麦珂", "苏菲亚", "场馆文书员", "奥瑞恩巡演合同联络员"],
        "opening_conflict": "奥瑞恩联络员声称椭圆家属章等同玛莎全面同意，并要求她补签确认设备处置决定。",
        "info_gap_use": "麦珂记得该章原为紧急联络而制，也因前世创伤想给母亲最终否决权；是否接受由玛莎今生自行决定。",
        "opponent_reaction": "联络员刻意赞美玛莎是‘最终家属决策者’，试图诱使她追认已经盖章的文件。",
        "action_sequence": [
            "苏菲亚展示湿度证书家属章的限定复写联，玛莎先比对章面缺口和姓名缩写。",
            "麦珂提出授予玛莎最终否决权，玛莎拒绝替成年儿子作单方医疗、技术或合同决定。",
            "场馆文书员调取家属联络章使用清册，确认章交给奥瑞恩巡演行政员后未登记归还。",
            "玛莎签署经公证的家属签署范围声明，只确认身份、接收通知和要求回拨核验。",
        ],
        "visible_payoff": "家属章被证明原本只供身份联络，玛莎亲自划清不替代本人同意和专业判断的边界。",
        "ending": "奥瑞恩联络员拿出另一份盖有同章的追认表，要求玛莎在记录处当场确认。",
        "must_include": ["椭圆章缺口比对", "麦珂提出最终否决权", "玛莎拒绝代替同意", "家属联络章使用清册"],
        "must_not_include": ["家属拥有绝对医疗控制权", "再次签署健康备忘录", "观众阻拦", "色带证据"],
        "detailed_synopsis": (
            "1991年10月23日下午，苏菲亚把湿度证书家属章的复写联带到回声谷巡演家属联络室。奥瑞恩联络员称该章"
            "代表玛莎全面同意，并诱导她补签。麦珂因前世母亲被排除的创伤，提出给她最终否决权；玛莎明确拒绝成为另一"
            "个能替成年麦珂单方决定的人。她比对章面缺口和姓名缩写，再由场馆文书员调出使用清册，确认椭圆章原本只供"
            "紧急联络，交给奥瑞恩行政员后未归还。玛莎签署经公证的家属签署范围声明：她可确认身份、接收通知、要求回拨，"
            "但不能替代本人同意、医生判断、技术验收或合同签署。"
        ),
    })
    first["scenes"] = [{
        "sequence": 1, "location": first["scene"], "is_primary": True,
        "temporal_mode": "current", "transition_cue": "湿度证书的椭圆家属章复写联被放上桌",
    }]
    first["artifact_creates"] = [
        artifact("ART_219_FAMILY_STAMP_INVENTORY", 219, "家属联络章使用清册见证页", "custody_record",
                 ["stamp_purpose", "checkout_holder", "checkout_date", "missing_return"],
                 ["verify_family_stamp_custody", "use_as_evidence_within_scope"], list(first["participants"])),
        # Retain the legacy ID because later source-plan clusters depend on it;
        # its display name and permissions are deliberately narrowed.
        artifact("ART_219_HEALTH_MEMO_CERTIFIED", 219, "经公证的家属签署范围声明", "legal_document",
                 ["identity_confirmation", "notice_receipt", "callback_request", "no_proxy_consent"],
                 ["verify_family_identity", "request_identity_callback", "use_as_evidence_within_scope"], list(first["participants"])),
    ]
    first["artifact_refs"] = [{
        "artifact_id": "ART_218_REJECTED_HUMIDITY_CERT", "timeline_scope": "current",
        "display_name": "错位序号湿度证书拒收联", "purpose": "核对紧急联系人栏的玛莎缩写和椭圆家属章",
        "required_permission": "use_as_evidence_within_scope", "scope_assertion": "不得据此推定玛莎已授权",
    }]

    second = milestone(event, 220)
    second.update({
        "timeline_start": "1991-10-23", "timeline_end": "1991-10-23",
        "scene": "回声谷体育馆记录处",
        "chapter_title": "停用回执与双人身份回拨",
        "chapter_goal": "在记录处拒绝追认冒用家属章的设备文件，停用旧章并建立双人身份回拨规则。",
        "participants": ["玛莎", "麦珂", "苏菲亚", "场馆记录员", "奥瑞恩巡演合同联络员"],
        "opening_conflict": "奥瑞恩联络员提交盖有椭圆章的追认表，声称旧章在停用前已代表玛莎同意设备处置。",
        "info_gap_use": "麦珂只记得前世玛莎被否认身份的原话；今生由玛莎本人决定如何验证身份和处理旧章。",
        "opponent_reaction": "联络员先说章等同签名，见玛莎拒绝后又改称章只用于通知，前后口径被记录员并列写入受理日志。",
        "action_sequence": [
            "玛莎当场写出自己的姓名缩写，与追认表笔迹和椭圆章缺口逐项比较，不追认旧文件。",
            "场馆记录员核对家属联络章使用清册和范围声明，受理旧章遗失停用申请。",
            "奥瑞恩联络员试图把旧章效力转移到新表，记录员因缺少玛莎本人签名和回拨记录拒收本次家属背书。",
            "玛莎指定本人和苏菲亚为身份双人回拨点，明确回拨只核验身份与通知，不产生代理同意。",
        ],
        "visible_payoff": "旧家属章停用，本次设备证书的家属背书被拒；今后既有盖章文件须逐件向两个登记点核验身份。",
        "ending": "奥瑞恩失去家属章捷径后，把无源光学组件资料转交海关并改称其中藏有电子元件。",
        "must_include": ["本人缩写现场样本", "旧章停用回执", "本次家属背书被拒", "双人身份回拨"],
        "must_not_include": ["玛莎替麦珂作医疗决定", "联络章追溯作废所有文件", "当场逮捕", "家属绝对控制权"],
        "detailed_synopsis": (
            "同日下午，奥瑞恩联络员在回声谷体育馆记录处提交另一份盖有椭圆章的追认表，声称旧章在停用前已经代表"
            "玛莎同意。玛莎现场写出姓名缩写，与文件笔迹和章面缺口比对，拒绝追认。记录员核对使用清册与经公证的范围"
            "声明，受理旧章遗失停用；停用不追溯抹掉所有文件，而是要求既有盖章文件逐件回拨核验。联络员先说章等同签名，"
            "又改口说只用于通知，前后口径进入日志。本次设备证书因缺本人签名和回拨记录被拒。玛莎指定自己与苏菲亚为"
            "双人身份回拨点，但回拨只确认身份和通知，不替代任何医疗、技术或合同同意。"
        ),
    })
    second["scenes"] = [{
        "sequence": 1, "location": second["scene"], "is_primary": True,
        "temporal_mode": "current", "transition_cue": "盖有旧椭圆章的追认表进入场馆记录处受理台",
    }]
    second["artifact_creates"] = [
        artifact("ART_220_STAMP_REVOCATION", 220, "家属联络章遗失停用回执", "legal_document",
                 ["revoked_stamp_impression", "effective_time", "case_by_case_callback"],
                 ["reject_future_stamp_only_reliance", "use_as_evidence_within_scope"], list(second["participants"])),
        artifact("ART_220_FAMILY_ENDORSEMENT_REJECTION", 220, "设备证书家属背书拒收记录", "legal_record",
                 ["missing_personal_signature", "missing_callback", "contradictory_scope_claim"],
                 ["reject_this_family_endorsement", "use_as_evidence_within_scope"], list(second["participants"])),
        artifact("ART_220_TWO_PERSON_CALLBACK", 220, "家属身份双人回拨登记", "registry",
                 ["martha_identity_point", "sophia_identity_point", "identity_only", "no_proxy_consent"],
                 ["verify_family_identity", "use_as_evidence_within_scope"], list(second["participants"])),
    ]
    second["artifact_refs"] = [
        {
            "artifact_id": "ART_219_FAMILY_STAMP_INVENTORY", "timeline_scope": "current",
            "display_name": "家属联络章使用清册见证页", "purpose": "证明旧章用途、领用人和未归还状态",
            "required_permission": "verify_family_stamp_custody", "scope_assertion": "不自动否定全部历史文件",
        },
        {
            "artifact_id": "ART_219_HEALTH_MEMO_CERTIFIED", "timeline_scope": "current",
            "display_name": "经公证的家属签署范围声明", "purpose": "界定玛莎身份核验与通知范围",
            "required_permission": "verify_family_identity", "scope_assertion": "不得替代本人或专业人员同意",
        },
    ]


def repair_ec111(event: dict[str, Any]) -> None:
    """Make customs, not a press conference or X-ray myth, resolve the shipment."""
    event.update({
        "name": "错配X光旧片与无源组件通关",
        "timeline_years": "1991",
        "main_opponent": "奥瑞恩报关代理与投诉人巴里·布鲁姆",
        "opposition_type": "institutional",
        "event_type": "legal_procedure",
        "solution_type": "legal_evidence",
        "prev_life_tragedy": "前世巡演组件因一张没有箱号的旧X光片被误作隐藏发射设备扣留，团队越过查验程序与媒体争辩，最终错过首站转运窗口。",
        "info_gap_from_prev_life": "麦珂只记得投诉附件会沿用左开铰链旧箱照片和缺少一枚角铆钉的影像；海关是否放行必须由今生实物查验决定。",
        "preemptive_avoidance": "团队如实申报无源光学组件，提交第218章独立检视单作为结构说明，并预留海关开箱与重新封志时间，不把检视单冒充放行证。",
        "bait_and_evidence": "巴里拿错配旧片煽动立即扣押，却反复强调片中左开铰链；当前箱体为右开双铰且角铆钉完整，使投诉附件先失去同一性基础。",
        "villain_loss": "巴里的这次投诉因附件无法对应当前箱号和箱体结构被标注为不可靠，奥瑞恩无法用该旧片无限期扣住本票货物。",
        "protagonist_gain": "海关完成独立开箱、结构核验和重新封志，签发只针对本票无源光学组件的查验放行单。",
        "relationship_change": "麦珂克制当场公开反击的冲动，接受海关官员独立决定；苏菲亚只提交范围内文书，不向官员施压。",
        "cluster_outcome": "错配旧片被排除，当前组件经海关技术查验确认申报结构一致并在新封志下放行；不推导设备性能或其他货物结论。",
        "next_event_hook": "投诉保证金的代缴机构指向一项面向年轻艺人的评审基金，带出下一簇初声基金资格争议。",
        "resolution_signature": {
            "attack_domain": "customs_misdeclaration_complaint",
            "counter_method": "crate_identity_and_official_physical_inspection",
            "resolver": "海关查验官",
            "publicity": "official_customs_record",
            "hero_gain_type": "shipment_specific_release",
        },
        "continuity_writes": [
            "承接EC110联络员抄走的无源结构检视单与组件序号。",
            "检视单只作申报附件，海关独立查验后才决定放行。",
        ],
        "historical_anchor_ids": [],
    })
    event["source_event_direction"] = (
        "前世具体受害：错配旧X光片导致巡演组件被扣并错过转运；"
        "本事件独有信息差：麦珂只记得左开铰链和缺角铆钉；"
        "今生提前动作：团队如实申报、预留开箱时间并提交范围受限的无源结构检视单；"
        "第221章可见小赢：当前箱体与投诉旧片在箱号、铰链和铆钉上不对应，货物转入技术查验而非直接扣留；"
        "第222章新交锋：巴里要求把光学玻璃阴影解释为发射器，海关独立开箱后确认无电路与供电部件；"
        "阻力方现实损失：本次投诉附件被标不可靠；主角现实收益：取得本票货物放行单；"
        "结算边界：只处理本箱本票货物，不评价设备性能和其他申报。"
    )
    event["main_characters"] = ["麦珂", "苏菲亚", "巴里·布鲁姆", "海关查验官"]
    event["canonical_cast"] = [
        item for item in event.get("canonical_cast") or []
        if item.get("character_id") in {"CHAR_026AC753E27A", "CHAR_87B8E75FFF6F", "CHAR_F618A85B98BB"}
    ]
    event["main_character_ids"] = [item["character_id"] for item in event["canonical_cast"]]
    event["state_transitions"] = [
        {
            "domain": "asset", "entity_id": "ASSET_SOUND_VISUALIZATION_SYSTEM",
            "state_key": "customs_clearance_status", "from": "complaint_pending_examination",
            "to": "shipment_specific_release_after_inspection", "irreversible": False,
            "evidence": "ART_222_CUSTOMS_RELEASE", "effect_type": "protagonist_gain",
            "source_entity_label": "sound_visualization_system",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
        {
            "domain": "reputation", "entity_id": "CHAR_F618A85B98BB",
            "state_key": "current_customs_complaint_reliability", "from": "pending_review",
            "to": "attachment_mismatched_and_unreliable", "irreversible": False,
            "evidence": "ART_221_MISMATCHED_XRAY", "effect_type": "villain_loss",
            "source_entity_label": "CHAR_F618A85B98BB",
            "irreversible_migration_reason": "temporary_or_reversible_state_v13",
        },
    ]

    first = milestone(event, 221)
    first.update({
        "timeline_start": "1991-10-23", "timeline_end": "1991-10-23",
        "scene": "星港机场海关货运查验通道",
        "chapter_title": "左开旧片与右开箱体",
        "chapter_goal": "完成如实申报并比对投诉旧片与当前箱体同一性，避免在附件未核验时直接长期扣留。",
        "participants": ["麦珂", "苏菲亚", "巴里·布鲁姆", "海关查验官", "场馆设备主管"],
        "opening_conflict": "巴里提交匿名投诉附件，声称货箱藏有未申报发射设备，报关代理要求海关立即无限期扣留。",
        "info_gap_use": "麦珂只提示前世旧片的左开铰链与缺角铆钉；当前货箱身份由箱号、封志和实物结构证明。",
        "opponent_reaction": "巴里不断强调旧片中左开铰链的阴影，却没发现当前箱为右开双铰且角铆钉完整。",
        "action_sequence": [
            "苏菲亚提交无源组件申报单、装箱清单和第218章无源结构检视单，明确后者不是海关放行证。",
            "海关查验官登记投诉附件来源、旧片箱号空白和影像可见结构，不接受现场围观者作技术结论。",
            "场馆设备主管展示当前箱号、原地复校后的转运封志、右开双铰和四枚完整角铆钉。",
            "查验官制作错配旧片比对记录，将货箱转入当日技术开箱而非直接无限期扣留。",
        ],
        "visible_payoff": "投诉旧片无法证明与当前货箱同一，组件保留当日查验与转运窗口。",
        "ending": "巴里指着X光片中的深色玻璃阴影，要求技术室把它认定为隐藏发射器。",
        "must_include": ["无源结构检视单不是放行证", "旧片缺少箱号", "左开铰链与右开双铰", "技术开箱登记"],
        "must_not_include": ["X光确认无电子信号", "海关官员赞赏麦珂", "当场完全放行", "媒体发布会"],
        "detailed_synopsis": (
            "1991年10月23日晚，巡演组件在星港机场海关货运通道办理下一站转运。巴里带来一张无箱号旧X光片，要求"
            "无限期扣留。苏菲亚如实提交申报、装箱单和无源结构检视单，并声明检视单不替海关作结论。麦珂只提醒旧片"
            "左开铰链和缺角铆钉两个前世特征。查验官核对今生箱号、封志和实物，发现当前箱为右开双铰且四枚角铆钉完整，"
            "投诉附件无法先证明同一性。官员制作错配旧片比对记录，把货物转入当日技术开箱，而非直接放行或无限期扣留。"
        ),
    })
    first["scenes"] = [{
        "sequence": 1, "location": first["scene"], "is_primary": True,
        "temporal_mode": "current", "transition_cue": "投诉旧X光片与当前货箱并列进入查验台",
    }]
    first["artifact_creates"] = [
        artifact("ART_221_MISMATCHED_XRAY", 221, "投诉旧X光片同一性比对记录", "customs_record",
                 ["missing_crate_number", "left_hinge_image", "right_double_hinge_actual", "corner_rivets"],
                 ["exclude_attachment_as_current_crate_identity", "use_as_evidence_within_scope"], list(first["participants"])),
        artifact("ART_221_TECH_EXAM_REGISTRATION", 221, "无源光学组件技术开箱登记", "customs_record",
                 ["current_crate_number", "incoming_seal", "declared_component", "exam_slot"],
                 ["perform_official_customs_examination", "use_as_evidence_within_scope"], list(first["participants"])),
    ]
    first["artifact_refs"] = [{
        "artifact_id": "ART_218_PASSIVE_OPTICS_INSPECTION", "timeline_scope": "current",
        "display_name": "无源光学结构独立检视单", "purpose": "作为如实申报的结构说明附件",
        "required_permission": "verify_passive_optical_structure", "scope_assertion": "不得替代海关查验或放行决定",
    }]

    second = milestone(event, 222)
    second.update({
        "timeline_start": "1991-10-23", "timeline_end": "1991-10-23",
        "scene": "星港机场海关技术查验室",
        "chapter_title": "玻璃阴影与本票放行单",
        "chapter_goal": "由海关独立开箱核对申报结构和投诉附件，完成新封志并取得仅限本票货物的放行。",
        "participants": ["麦珂", "苏菲亚", "巴里·布鲁姆", "海关查验官", "海关技术员", "场馆设备主管"],
        "opening_conflict": "巴里坚持把X光中的高密度玻璃阴影解释为电子发射器，要求跳过开箱直接认定违禁。",
        "info_gap_use": "麦珂知道前世争辩媒体会错过窗口，因此不演示设备，只要求海关按登记独立查验。",
        "opponent_reaction": "巴里在官员拆箱后又改称电子元件可能藏在镜架内部，反复扩大投诉范围。",
        "action_sequence": [
            "海关官员核对技术开箱登记和入场封志，在独立技术员见证下拆开货箱与组件检视盖。",
            "技术员逐件比对装箱单，确认透镜、机械调节环、无源导光件及包装材料，没有申报外电路、导线或电源。",
            "巴里要求继续破坏性拆解，查验官因投诉旧片已失去同一性且现有检查完成而拒绝扩大。",
            "海关重新封志，签发本票货物技术查验记录和限本箱放行单，并登记投诉保证金代缴机构。",
        ],
        "visible_payoff": "当前货箱在新封志下按期放行；巴里的旧片投诉只在本案被标注附件错配和不可靠。",
        "ending": "放行单背面的投诉保证金栏，出现一家面向年轻艺人的评审基金代缴机构。",
        "must_include": ["海关独立开箱", "玻璃阴影不是电子信号结论", "新封志", "本票货物限范围放行"],
        "must_not_include": ["新闻发布会", "巴里信誉首次受损", "全行业安全标准", "设备性能永久合格"],
        "detailed_synopsis": (
            "同日晚间，海关技术查验室按登记拆开货箱。巴里把旧X光片的高密度玻璃阴影说成电子发射器，麦珂没有"
            "对媒体演示或替官员判断。技术员逐件核对装箱单和实物，确认只有透镜、机械调节环、无源导光件及包装材料，"
            "没有申报外电路、导线或电源；X光阴影本身不被写成‘电子信号测试’。巴里又要求破坏性拆解，查验官因旧片"
            "不能对应当前箱体、既定检查已经完成而拒绝扩张。海关重新封志，签发只针对当前箱号和本票货物的放行单。"
            "投诉保证金代缴机构则指向一项年轻艺人评审基金。"
        ),
    })
    second["scenes"] = [{
        "sequence": 1, "location": second["scene"], "is_primary": True,
        "temporal_mode": "current", "transition_cue": "当前货箱按技术开箱登记进入海关查验室",
    }]
    second["artifact_creates"] = [
        artifact("ART_222_CUSTOMS_TECH_EXAM", 222, "本票无源组件海关技术查验记录", "customs_record",
                 ["crate_number", "examined_contents", "no_undeclared_electronics", "new_seal"],
                 ["document_official_customs_exam", "use_as_evidence_within_scope"], list(second["participants"])),
        artifact("ART_222_CUSTOMS_RELEASE", 222, "本票货物限范围放行单", "customs_record",
                 ["current_crate_only", "current_waybill_only", "new_seal", "complaint_bond_payer"],
                 ["release_current_shipment", "use_as_evidence_within_scope"], list(second["participants"])),
    ]
    second["artifact_refs"] = [
        {
            "artifact_id": "ART_221_MISMATCHED_XRAY", "timeline_scope": "current",
            "display_name": "投诉旧X光片同一性比对记录", "purpose": "界定投诉附件无法对应当前箱体",
            "required_permission": "use_as_evidence_within_scope", "scope_assertion": "不替代当前实物查验",
        },
        {
            "artifact_id": "ART_221_TECH_EXAM_REGISTRATION", "timeline_scope": "current",
            "display_name": "无源光学组件技术开箱登记", "purpose": "限定海关查验的当前箱号、封志与内容",
            "required_permission": "perform_official_customs_examination", "scope_assertion": "只适用于本次海关查验",
        },
        {
            "artifact_id": "ART_218_PASSIVE_OPTICS_INSPECTION", "timeline_scope": "current",
            "display_name": "无源光学结构独立检视单", "purpose": "作为结构说明与官方查验结果比对",
            "required_permission": "verify_passive_optical_structure", "scope_assertion": "不得替代海关最终决定",
        },
    ]


def repair_ec112(event: dict[str, Any]) -> None:
    event.update({
        "name": "投诉保证金与初声基金回避席",
        "timeline_years": "1991",
        "main_opponent": "初声青年艺人评审基金财务秘书与奥瑞恩观察员",
        "opposition_type": "institutional",
        "event_type": "finance_business",
        "solution_type": "financial_counter",
        "prev_life_tragedy": "前世初声基金把申请人缴纳的评审保证金用于外部投诉，事后再以资金缺口为由取消年轻艺人资格，麦珂团队只看见结果，没有追到支出授权。",
        "info_gap_from_prev_life": "麦珂只记得投诉保证金与评审池使用相同的FS-9批次前缀，以及财务秘书会用‘风险保护’掩盖外部支出。",
        "preemptive_avoidance": "苏菲亚以海关公开受理栏的代缴编号申请基金监督委员核验，只追查该笔保证金；麦珂拒绝接受能让他追认支出的荣誉职务。",
        "bait_and_evidence": "财务秘书把外部投诉包装成保护申请人，并拿出倒填日期的理事决议；会议登记簿与纸张领用号证明决议在海关放行后才制作。",
        "villain_loss": "财务秘书失去以申请人保证金池支付外部投诉的权限，本笔支出被要求补回并进入利益冲突复核。",
        "protagonist_gain": "申请人保证金池获得补回令、外部支出禁用条款和评审回避登记，年轻艺人的申请资格不因本笔缺口受损。",
        "relationship_change": "麦珂拒绝以个人荣誉席控制基金；苏菲亚作为申请人记录代表主导财务核验，双方把制度修复置于个人报复之前。",
        "cluster_outcome": "海关投诉保证金被追溯到申请人评审池，倒填授权未获追认，本笔资金须补回且奥瑞恩观察员退出相关评审。",
        "next_event_hook": "回避登记显示同一观察员还在下一轮舞台安全资助评分中持有双重票，引出评分票拆分争议。",
        "resolution_signature": {"attack_domain": "applicant_bond_pool_misuse", "counter_method": "single_payment_trace_and_board_recusal", "resolver": "基金独立监督委员", "publicity": "board_record", "hero_gain_type": "pool_reimbursement_and_recusal"},
        "continuity_writes": ["承接EC111放行单背面的初声基金投诉保证金代缴编号。", "不再使用打字机、色带或精神评估报告证据家族。"],
        "historical_anchor_ids": [],
    })
    event["source_event_direction"] = (
        "前世具体受害：申请人保证金被挪作外部投诉并导致年轻艺人资格取消；"
        "本事件独有信息差：麦珂只记得FS-9批次前缀和‘风险保护’话术；"
        "今生提前动作：苏菲亚凭海关代缴编号只核验一笔支出；"
        "第223章可见小赢：代缴款与申请人评审保证金池形成纸面对应；"
        "第224章新交锋：财务秘书提交倒填理事决议，因会议登记和纸张领用时点不符未获追认；"
        "阻力方现实损失：外部投诉支出权限暂停且须补款；主角现实收益：保证金池与评审回避规则被保护；"
        "结算边界：只处理本笔支出，不宣称整个基金违法。"
    )
    event["main_characters"] = ["苏菲亚", "麦珂", "基金独立监督委员", "基金财务秘书"]
    event["canonical_cast"] = [item for item in event.get("canonical_cast") or [] if item.get("character_id") in {"CHAR_87B8E75FFF6F", "CHAR_026AC753E27A"}]
    event["main_character_ids"] = [item["character_id"] for item in event["canonical_cast"]]
    event["main_opponent_character_ids"] = []
    event.pop("main_opponent_character_id", None)
    event["state_transitions"] = [
        {"domain": "asset", "entity_id": "ASSET_FIRST_VOICE_APPLICANT_BOND_POOL", "state_key": "customs_complaint_payment_origin", "from": "public_payer_name_only", "to": "matched_to_applicant_review_bond_pool", "irreversible": False, "evidence": "ART_223_BOND_PAYMENT_TRACE", "effect_type": "protagonist_gain", "irreversible_migration_reason": "temporary_or_reversible_state_v13"},
        {"domain": "rights", "entity_id": "RIGHT_FIRST_VOICE_EXTERNAL_SPEND", "state_key": "external_complaint_spending", "from": "secretary_discretion_claimed", "to": "suspended_and_reimbursement_required", "irreversible": False, "evidence": "ART_224_POOL_REIMBURSEMENT", "effect_type": "villain_loss", "irreversible_migration_reason": "temporary_or_reversible_state_v13"},
        {"domain": "rights", "entity_id": "RIGHT_FIRST_VOICE_REVIEW_01", "state_key": "orion_observer_conflict_status", "from": "undisclosed_dual_role", "to": "disclosed_and_recused_for_related_scores", "irreversible": False, "evidence": "ART_224_CONFLICT_RECUSAL", "effect_type": "protagonist_gain", "irreversible_migration_reason": "temporary_or_reversible_state_v13"},
    ]

    first = milestone(event, 223)
    first.update({
        "timeline_start": "1991-10-23", "timeline_end": "1991-10-23", "scene": "初声青年艺人评审基金夜间登记室",
        "chapter_title": "FS-9代缴号与申请人保证金池", "chapter_goal": "凭海关代缴编号核对单笔投诉保证金的支出批次、资金池和授权栏。",
        "participants": ["苏菲亚", "麦珂", "基金登记员", "基金独立监督委员", "基金财务秘书"],
        "opening_conflict": "财务秘书以捐赠者保密为由拒绝解释海关保证金来源，并声称当夜登记室已经闭门。",
        "info_gap_use": "麦珂只提示FS-9批次前缀与‘风险保护’话术；苏菲亚用今生海关缴款号、基金支出簿和申请人规则核验。",
        "opponent_reaction": "财务秘书提出给麦珂荣誉主席席位，条件是承认投诉支出属于保护年轻艺人的合理费用。",
        "action_sequence": [
            "独立监督委员依申请人规则开放仅限该笔代缴款的登记页，遮蔽无关申请人姓名。",
            "苏菲亚用海关缴款号匹配FS-9支出批次，确认借方为申请人评审保证金池而非基金运营费。",
            "登记员核对支出授权栏，发现只有财务秘书签名，缺少监督委员复核号。",
            "麦珂拒绝荣誉主席席位，不以个人职务追认支出；苏菲亚取得限定范围的付款路径见证单。",
        ],
        "visible_payoff": "本笔海关保证金与申请人评审保证金池完成纸面对应，且授权栏缺少规则要求的独立复核号。",
        "ending": "财务秘书通知理事紧急到场，并拿出一份日期写成前一日的支出授权决议。",
        "must_include": ["FS-9批次前缀", "申请人保证金池", "缺少独立复核号", "麦珂拒绝荣誉主席"],
        "must_not_include": ["打字机色带", "精神评估报告", "冻结整个基金", "公开申请人隐私"],
        "detailed_synopsis": "1991年10月23日晚，苏菲亚凭海关放行单上的代缴编号进入初声基金夜间登记室。独立监督委员只开放该笔支出页，并遮蔽申请人姓名。海关编号对应FS-9批次，借方却是申请人评审保证金池，授权栏只有财务秘书签名，缺独立复核号。财务秘书以‘风险保护’解释，并提出给麦珂荣誉主席席位换取追认。麦珂拒绝，苏菲亚取得只限该笔付款的路径见证单。财务秘书随即拿出倒填前一日日期的理事决议。",
    })
    first["scenes"] = [{"sequence": 1, "location": first["scene"], "is_primary": True, "temporal_mode": "current", "transition_cue": "海关代缴号进入基金夜间登记页核对"}]
    first["artifact_creates"] = [
        artifact("ART_223_BOND_PAYMENT_TRACE", 223, "海关投诉保证金单笔付款路径见证单", "audit_record", ["customs_payment_number", "fs9_batch", "applicant_bond_pool", "missing_oversight_number"], ["verify_single_bond_payment", "use_as_evidence_within_scope"], list(first["participants"])),
        artifact("ART_223_APPLICANT_POOL_RULES", 223, "申请人评审保证金池支出规则摘录", "governance_record", ["permitted_uses", "oversight_approval", "privacy_redactions"], ["review_applicant_pool_spending_rules", "use_as_evidence_within_scope"], list(first["participants"])),
    ]
    first["artifact_refs"] = [{"artifact_id": "ART_222_CUSTOMS_RELEASE", "timeline_scope": "current", "display_name": "本票货物限范围放行单", "purpose": "提供投诉保证金代缴机构和公开缴款编号", "required_permission": "use_as_evidence_within_scope", "scope_assertion": "只核验该笔保证金"}]

    second = milestone(event, 224)
    second.update({
        "timeline_start": "1991-10-23", "timeline_end": "1991-10-23", "scene": "初声青年艺人评审基金紧急理事复核室",
        "chapter_title": "倒填决议与回避席", "chapter_goal": "核验倒填支出决议，要求补回申请人保证金并让利益冲突观察员退出相关评分。",
        "participants": ["苏菲亚", "麦珂", "基金独立监督委员", "基金财务秘书", "奥瑞恩观察员", "基金登记员"],
        "opening_conflict": "财务秘书提交日期为前一日的理事决议，声称它已经授权用申请人保证金支付海关投诉。",
        "info_gap_use": "麦珂知道‘风险保护’是前世话术，但决议是否倒填由今生会议登记、纸张领用号和到场签名证明。",
        "opponent_reaction": "奥瑞恩观察员既为投诉出资方提供意见又持有下一轮评分票，试图以观察员身份回避利益披露。",
        "action_sequence": [
            "登记员比对决议纸张领用号和会议簿，确认纸张本日晚间才领取，前一日没有理事会议。",
            "独立监督委员拒绝追认倒填决议，要求财务秘书从运营费补回申请人保证金池。",
            "苏菲亚提交申请人池规则，指出奥瑞恩观察员同时参与投诉与相关艺人评分。",
            "理事复核记录暂停外部投诉支出，并登记观察员退出相关评分和移交双重票。",
        ],
        "visible_payoff": "本笔保证金获得补回令，奥瑞恩观察员退出相关评分；年轻艺人资格不因资金缺口被取消。",
        "ending": "移交的评分票显示，同一观察员在下一轮舞台安全资助中占有两张不同席位的票。",
        "must_include": ["纸张领用号晚于决议日期", "申请人保证金补回", "奥瑞恩观察员回避", "双重评分票"],
        "must_not_include": ["认定整个基金违法", "麦珂接管基金", "巴里发布会", "集团彻底分裂"],
        "detailed_synopsis": "同日晚间，初声基金举行紧急理事复核。财务秘书提交日期倒填为前一日的授权决议；登记员核对纸张领用号和会议簿，发现该纸本日晚间才领取，前一日无会议。独立监督委员拒绝追认，命令财务秘书从运营费补回申请人保证金，并暂停用该池支付外部投诉。苏菲亚进一步指出奥瑞恩观察员既参与投诉又持相关艺人评分票，理事会登记其回避并移交票据。移交时发现他在下一轮舞台安全资助中持有两张不同席位的票。",
    })
    second["scenes"] = [{"sequence": 1, "location": second["scene"], "is_primary": True, "temporal_mode": "current", "transition_cue": "倒填日期的支出决议进入紧急理事复核"}]
    second["artifact_creates"] = [
        artifact("ART_224_POOL_REIMBURSEMENT", 224, "申请人保证金池补回令", "governance_record", ["single_payment_reimbursement", "operations_fund_source", "external_spend_suspension"], ["restore_single_payment_to_applicant_pool", "use_as_evidence_within_scope"], list(second["participants"])),
        artifact("ART_224_CONFLICT_RECUSAL", 224, "奥瑞恩观察员利益冲突回避登记", "governance_record", ["complaint_role", "review_role", "related_score_recusal", "ballot_transfer"], ["enforce_related_review_recusal", "use_as_evidence_within_scope"], list(second["participants"])),
    ]
    second["artifact_refs"] = [
        {"artifact_id": "ART_223_BOND_PAYMENT_TRACE", "timeline_scope": "current", "display_name": "海关投诉保证金单笔付款路径见证单", "purpose": "证明本笔支出来自申请人保证金池且缺复核号", "required_permission": "verify_single_bond_payment", "scope_assertion": "只处理该笔支出"},
        {"artifact_id": "ART_223_APPLICANT_POOL_RULES", "timeline_scope": "current", "display_name": "申请人评审保证金池支出规则摘录", "purpose": "核验允许用途、复核要求和隐私边界", "required_permission": "review_applicant_pool_spending_rules", "scope_assertion": "不得公开无关申请人资料"},
    ]


def repair_ec113(event: dict[str, Any]) -> None:
    event.update({
        "name": "舞台安全资助的双重评分票与盲审拆席", "timeline_years": "1991",
        "main_opponent": "奥瑞恩观察员与初声基金评分秘书", "opposition_type": "institutional",
        "event_type": "fan_public_welfare", "solution_type": "teamwork",
        "prev_life_tragedy": "前世同一奥瑞恩观察员以两个席位投出不同权重，挤掉基层场馆的安全资助；缺少疏散设备的场馆后来发生通道拥堵。",
        "info_gap_from_prev_life": "麦珂只记得两张票会出现相同的七十三点五分和同一句‘商业转化不足’，不能据此认定今生谁投了票。",
        "preemptive_avoidance": "苏菲亚在计分前要求隐藏申请人名称并核对席位授权、通信地址和笔迹；重复票先隔离，不提前改分。",
        "bait_and_evidence": "评分秘书声称两个机构可共享同一观察员，却在权重表上同时保留两票；盲编号拆开后，两票授权均来自奥瑞恩财务办公室。",
        "villain_loss": "奥瑞恩观察员失去相关项目的重复评分权，一张重复席位票被作废，另一席移交无利益关系候补评审。",
        "protagonist_gain": "舞台安全资助完成盲审重算，申请人不因公司关系被识别，基层场馆的安全项目按有效票获得资助。",
        "relationship_change": "麦珂不要求公开受益申请人或指定赢家；苏菲亚与申请人记录代表共同监督规则，接受独立评审结果。",
        "cluster_outcome": "双重评分票在计分前被拆席，相关项目使用有效独立票重算并发出限用途资助通知。",
        "next_event_hook": "获资助项目采购清单中出现两套互相矛盾的暴雨灯光备件规格，引出下一簇采购验收争议。",
        "resolution_signature": {"attack_domain": "duplicate_weighted_ballots", "counter_method": "blind_identity_separation_and_authorization_audit", "resolver": "独立评审主持人", "publicity": "confidential_review", "hero_gain_type": "valid_ballot_recalculation"},
        "continuity_writes": ["承接EC112封存的双重评分票和利益冲突回避登记。", "不重复三方急救令、晕厥或观众人墙。"], "historical_anchor_ids": [],
    })
    event["source_event_direction"] = "前世具体受害：同一观察员双重投票挤掉基层安全资助；本事件独有信息差：麦珂只记得七十三点五分和固定评语；今生提前动作：苏菲亚要求申请人盲编号、核对席位授权并在计分前隔离重复票；第225章可见小赢：两票授权和地址对应同一奥瑞恩办公室；第226章新交锋：评分秘书要求保留两种权重，独立主持人拆席后重算；阻力方现实损失：重复票作废且相关席回避；主角现实收益：有效票决定限用途安全资助；结算边界：不公开申请人身份、不由麦珂指定赢家。"
    event["main_characters"] = ["苏菲亚", "麦珂", "独立评审主持人", "申请人记录代表"]
    event["canonical_cast"] = [item for item in event.get("canonical_cast") or [] if item.get("character_id") in {"CHAR_87B8E75FFF6F", "CHAR_026AC753E27A"}]
    event["main_character_ids"] = [item["character_id"] for item in event["canonical_cast"]]
    event["main_opponent_character_ids"] = []; event.pop("main_opponent_character_id", None)
    event["state_transitions"] = [
        {"domain": "rights", "entity_id": "RIGHT_FIRST_VOICE_SAFETY_GRANT_REVIEW", "state_key": "duplicate_ballot_status", "from": "two_weighted_votes_same_observer", "to": "duplicate_voided_and_related_seat_recused", "irreversible": False, "evidence": "ART_225_DUPLICATE_BALLOT_MATCH", "effect_type": "villain_loss", "irreversible_migration_reason": "temporary_or_reversible_state_v13"},
        {"domain": "asset", "entity_id": "ASSET_FIRST_VOICE_SAFETY_GRANTS", "state_key": "current_round_scoring", "from": "uncounted_with_conflict", "to": "blind_recalculation_completed", "irreversible": False, "evidence": "ART_226_BLIND_RECALCULATION", "effect_type": "protagonist_gain", "irreversible_migration_reason": "temporary_or_reversible_state_v13"},
        {"domain": "rights", "entity_id": "RIGHT_APPLICANT_PRIVACY_01", "state_key": "review_identity_exposure", "from": "names_visible_to_observers", "to": "blind_codes_only_until_award", "irreversible": False, "evidence": "ART_226_LIMITED_GRANT_NOTICE", "effect_type": "protagonist_gain", "irreversible_migration_reason": "temporary_or_reversible_state_v13"},
    ]
    first = milestone(event, 225)
    first.update({"timeline_start": "1991-10-24", "timeline_end": "1991-10-24", "scene": "初声基金盲审票据室", "chapter_title": "七十三点五分与同址委任函", "chapter_goal": "在计分前隔离双重票，以盲编号核对两席授权来源、通信地址和权重。", "participants": ["苏菲亚", "麦珂", "独立评审主持人", "申请人记录代表", "基金评分秘书", "奥瑞恩观察员"], "opening_conflict": "评分秘书要求立即计入两张不同权重票，声称产业观察席和公共安全赞助席属于不同机构。", "info_gap_use": "麦珂只提示前世七十三点五分和固定评语；苏菲亚不按分数找人，而先对全部评分票统一盲编号。", "opponent_reaction": "观察员承认两票由自己填写，却坚持一人代表两个机构就应拥有两种权重。", "action_sequence": ["申请人记录代表遮住项目名称和申请人身份，只保留盲编号、分数与评语。", "苏菲亚在未计分票中发现两张七十三点五分及同句评语，先分别封套而不宣布重复。", "主持人核对两席委任函，确认签收人、通信地址和出具方均为同一奥瑞恩财务办公室。", "评分秘书提交权重表，暴露同一观察员被同时配置两票；主持人制作重复席位匹配记录。"], "visible_payoff": "两张冲突票在进入总分前被隔离，同一人和同一授权来源的双重权重形成纸面记录。", "ending": "评分秘书坚持只作废一张低权重票、保留高权重票原评分，要求直接宣布结果。", "must_include": ["申请人盲编号", "两张七十三点五分", "相同评语", "同址委任函"], "must_not_include": ["医疗晕厥", "三方急救令", "公开申请人姓名", "麦珂指定获奖者"], "detailed_synopsis": "1991年10月24日上午，初声基金在计分前复核上一夜封存的双重评分票。申请人记录代表遮蔽名称，只保留盲编号。麦珂只提示前世记得的七十三点五分和固定评语；苏菲亚对全部票统一编号后发现两张相同分数与评语。独立主持人核对委任函，确认两个席位的签收人、地址和出具方均相同。两票在计分前隔离，形成重复席位匹配记录，尚未改变任何申请人的分数。"})
    first["scenes"] = [{"sequence": 1, "location": first["scene"], "is_primary": True, "temporal_mode": "current", "transition_cue": "封存的双重评分票进入盲编号复核"}]
    first["artifact_creates"] = [artifact("ART_225_BLIND_BALLOT_LEDGER",225,"舞台安全资助盲编号票据簿","review_record",["blind_codes","scores","comments","sealed_identity_key"],["review_blind_ballots","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_225_DUPLICATE_BALLOT_MATCH",225,"同址双重评分席位匹配记录","review_record",["same_voter","same_issuer","same_address","two_weights"],["quarantine_duplicate_ballots","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"] = [{"artifact_id":"ART_224_CONFLICT_RECUSAL","timeline_scope":"current","display_name":"奥瑞恩观察员利益冲突回避登记","purpose":"触发相关项目双重评分票复核","required_permission":"enforce_related_review_recusal","scope_assertion":"不得公开申请人身份"}]
    second = milestone(event, 226)
    second.update({"timeline_start":"1991-10-24","timeline_end":"1991-10-24","scene":"初声基金独立评审室","chapter_title":"拆席重算与限用途资助","chapter_goal":"确定有效席位、由候补评审补票并在盲态下重算舞台安全资助。","participants":["苏菲亚","麦珂","独立评审主持人","申请人记录代表","候补评审","基金评分秘书","奥瑞恩观察员"],"opening_conflict":"评分秘书主张保留奥瑞恩两票中权重更高的一张原评分，避免重算改变结果。","info_gap_use":"本章不再使用前世分数决定结果，只依赖席位规则、候补顺序和封存盲编号。","opponent_reaction":"观察员试图在退出前向候补评审透露申请人背景，被主持人收回身份钥匙并要求分室补票。","action_sequence":["主持人按规则作废重复席位票，并让相关观察席退出本轮项目。","申请人记录代表保管身份钥匙，候补评审只看到盲编号、预算和安全项目说明。","候补票封存后与其他有效票统一开封，登记员按原权重表重新计算并双人复核。","理事会向有效盲编号发出限用途资助通知，身份只在结果锁定后由记录代表单独解封。"],"visible_payoff":"舞台安全资助按无冲突有效票重算，重复票没有进入总分，受益项目获得只用于安全采购的通知。","ending":"一份获资助采购清单同时列出两套互不兼容的暴雨灯光备件规格。","must_include":["重复席位票作废","候补评审分室补票","盲态重算","限用途资助通知"],"must_not_include":["公开落选者","主角接管评审","观众人墙","绝对授权"],"detailed_synopsis":"同日上午，独立主持人拒绝保留高权重原票，按规则作废重复席位票并让相关观察席回避。申请人身份钥匙由记录代表单独保管，候补评审只看盲编号、预算和安全说明，在分室完成补票。全部有效票统一开封并双人重算，身份只在结果锁定后解封。基金发出限用途安全资助通知，不公开落选者。获资助采购清单却同时列出两套互不兼容的暴雨灯光备件规格。"})
    second["scenes"] = [{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"重复席位被拆除后候补评审进入分室补票"}]
    second["artifact_creates"] = [artifact("ART_226_BLIND_RECALCULATION",226,"舞台安全资助盲态重算表","review_record",["valid_ballots","replacement_ballot","double_check","locked_results"],["finalize_blind_recalculation","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_226_LIMITED_GRANT_NOTICE",226,"舞台安全项目限用途资助通知","grant_record",["awarded_blind_code","safety_use_only","identity_release_after_lock"],["fund_awarded_safety_scope","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"] = [{"artifact_id":"ART_225_BLIND_BALLOT_LEDGER","timeline_scope":"current","display_name":"舞台安全资助盲编号票据簿","purpose":"在不泄露身份的前提下统一重算","required_permission":"review_blind_ballots","scope_assertion":"结果锁定前不得解封身份"},{"artifact_id":"ART_225_DUPLICATE_BALLOT_MATCH","timeline_scope":"current","display_name":"同址双重评分席位匹配记录","purpose":"证明重复席位应隔离和回避","required_permission":"quarantine_duplicate_ballots","scope_assertion":"只适用于相关项目"}]


def repair_ec114(event: dict[str, Any]) -> None:
    event.update({
        "name": "舞台安全备件的双规格插入与到货拒收", "timeline_years": "1991",
        "main_opponent": "初声基金采购秘书与灰港舞台设备供应商", "opposition_type": "institutional",
        "event_type": "finance_business", "solution_type": "technical_validation",
        "prev_life_tragedy": "前世基层场馆把六孔电控备件装进四孔机械机架，临时转接件松脱后占用疏散照明维修预算，真正需要的机械备件一直未到货。",
        "info_gap_from_prev_life": "麦珂只记得错误批次以六孔底座和尾号61出现；今生哪份规格获批、谁改过采购行，必须由申请附件、修订链和实物验收证明。",
        "preemptive_avoidance": "场馆设备主管在拨付争议采购行前冻结该行，苏菲亚分别核对申请原件、资助通知、采购修订页和供应商报价，不停止通道改造与人员训练。",
        "bait_and_evidence": "采购秘书声称六孔电控件是免费升级，却拿不出场馆设备主管签署的规格变更；供应商随后按插入页送来六孔批次并推销未经核准的转接板。",
        "villain_loss": "采购秘书失去单方改写该采购行的权限，供应商的六孔批次被拒收且不得以到货为由请款。",
        "protagonist_gain": "基层场馆锁定四孔机械备件核准基线，争议采购行重新询价，其余安全资助继续执行。",
        "relationship_change": "麦珂接受场馆设备主管对兼容性的最终验收判断；苏菲亚只维护文书链，不替技术人员签收。",
        "cluster_outcome": "双规格被追溯为未经场馆确认的采购插页，六孔电控批次在入库前拒收，四孔机械备件采购行依法重启询价。",
        "next_event_hook": "拒收批次所附的紧急联络铭牌样张仍使用已注销的家属联络章和过期岗位名称，引出下一簇现场联络标识复核。",
        "resolution_signature": {"attack_domain": "grant_purchase_spec_insertion", "counter_method": "approved_baseline_and_physical_receiving_check", "resolver": "基层场馆设备主管", "publicity": "procurement_record", "hero_gain_type": "compatible_rebid_without_freezing_other_grant_lines"},
        "continuity_writes": ["承接EC113采购清单中的四孔机械式与六孔电控式冲突。", "不再安排暴雨演出、七路切光、色带伪证或媒体羞辱。"], "historical_anchor_ids": [],
    })
    event["source_event_direction"] = "前世具体受害：不兼容备件挤占安全预算；本事件独有信息差：麦珂只记得六孔与尾号61；今生提前动作：场馆在拨款前锁住争议采购行并核对原始申请；第227章可见小赢：四孔机械核准基线与未经签署的六孔插页被拆开；第228章新交锋：供应商送来六孔件并推销转接板，场馆按实物验收拒收；阻力方现实损失：插页失效且本批不得请款；主角现实收益：四孔采购行重启询价、其余资助继续；结算边界：不认定全部供应商或基金采购违法。"
    event["main_characters"] = ["苏菲亚", "麦珂", "基层场馆设备主管", "基金独立采购监督员"]
    event["canonical_cast"] = [item for item in event.get("canonical_cast") or [] if item.get("character_id") in {"CHAR_87B8E75FFF6F", "CHAR_026AC753E27A"}]
    event["main_character_ids"] = [item["character_id"] for item in event["canonical_cast"]]
    event["main_opponent_character_ids"] = []; event.pop("main_opponent_character_id", None)
    event["state_transitions"] = [
        {"domain":"asset","entity_id":"ASSET_FIRST_VOICE_SAFETY_GRANT_PURCHASE","state_key":"approved_spare_specification","from":"conflicting_four_hole_and_six_hole_specs","to":"four_hole_mechanical_baseline_confirmed","irreversible":False,"evidence":"ART_227_APPROVED_PURCHASE_BASELINE","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"rights","entity_id":"RIGHT_FIRST_VOICE_PURCHASE_AMENDMENT","state_key":"spec_change_authority","from":"procurement_secretary_unilateral_insertion","to":"venue_acceptance_required","irreversible":False,"evidence":"ART_227_UNAUTHORIZED_SPEC_INSERTION","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"asset","entity_id":"ASSET_VENUE_RAIN_LIGHT_SPARES","state_key":"delivery_status","from":"six_hole_batch_tendered","to":"incompatible_batch_refused_and_line_reopened","irreversible":False,"evidence":"ART_228_DELIVERY_ACCEPTANCE","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first = milestone(event, 227)
    first.update({"timeline_start":"1991-10-24","timeline_end":"1991-10-24","scene":"基层场馆设备档案室","chapter_title":"四孔原件与第七码插页","chapter_goal":"以获批申请原件和完整修订链确定采购基线，隔离未经场馆签署的六孔电控规格。","participants":["苏菲亚","麦珂","基层场馆设备主管","基金独立采购监督员","基金采购秘书"],"opening_conflict":"基金采购秘书要求按清单最后一页拨款，称六孔电控件是无需重新签署的等价升级。","info_gap_use":"麦珂只提示前世记得六孔底座和尾号61；苏菲亚从今生申请原件、页码、修订登记和签收栏核验。","opponent_reaction":"采购秘书把缺少场馆签名解释为抄送遗漏，并要求先付款、到货后再解决安装问题。","action_sequence":["设备主管取出获资助申请原件，确认机架孔距、承重和动力条件只对应四孔机械备件。","苏菲亚逐页核对资助附件，发现六孔电控规格位于没有场馆签收的第七码插页。","独立采购监督员核对修订登记，确认插页只有采购秘书和供应商报价章，缺设备主管变更同意。","监督员锁住争议采购行，制作核准规格表和插入比对记录，其余通道改造与训练款继续。"],"visible_payoff":"四孔机械规格成为本采购行核准基线，六孔插页在拨款前被隔离且不能先行请款。","ending":"供应商来电称货车已到侧门，并坚持按六孔插页卸货即可视为履约。","must_include":["四孔机械核准规格","第七码插页","缺少场馆签收","只锁争议采购行"],"must_not_include":["暴雨演出","七套光路切换","打字机色带","宣布全行业标准"],"detailed_synopsis":"1991年10月24日下午，场馆设备主管以获资助申请原件核对采购清单。原件只批准四孔机械备件，六孔电控规格却出现在未由场馆签收的第七码插页。苏菲亚以页码、修订登记和报价章确认插页只有基金采购秘书与供应商往来，不能证明场馆接受变更。独立监督员只锁住争议采购行，制作核准规格表和插入比对记录；通道改造与训练款照常执行。供应商随即通知六孔批次已经到门。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"互相冲突的采购页进入申请原件与修订链核对"}]
    first["artifact_creates"]=[artifact("ART_227_APPROVED_PURCHASE_BASELINE",227,"获资助场馆四孔机械备件核准规格表","procurement_record",["four_hole_mount","mechanical_drive","approved_load","venue_signature"],["verify_approved_purchase_baseline","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_227_UNAUTHORIZED_SPEC_INSERTION",227,"六孔电控规格插入比对记录","procurement_record",["inserted_page_seven","missing_venue_acceptance","supplier_quote_stamp","disputed_line_only"],["quarantine_unapproved_specification","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_226_LIMITED_GRANT_NOTICE","timeline_scope":"current","display_name":"舞台安全项目限用途资助通知","purpose":"限定本次采购只能执行获批安全用途和规格","required_permission":"fund_awarded_safety_scope","scope_assertion":"只核对获资助场馆采购附件"}]
    second = milestone(event, 228)
    second.update({"timeline_start":"1991-10-24","timeline_end":"1991-10-24","scene":"基层场馆侧门验收区","chapter_title":"六孔到货与拒收红签","chapter_goal":"在不让不兼容货物入库或形成付款依据的前提下完成实物验收并重启争议采购行。","participants":["苏菲亚","麦珂","基层场馆设备主管","基金独立采购监督员","供应商代表","仓库保管员"],"opening_conflict":"供应商代表要求先卸下六孔电控件，声称免费转接板可让它们安装到四孔机械机架。","info_gap_use":"麦珂只用尾号61提醒核对箱签；兼容与否由设备主管依据核准规格、量规和现场机架判断。","opponent_reaction":"供应商代表以滞车费施压，并试图让仓库保管员先在送货单签‘数量已收’。","action_sequence":["仓库保管员在车门未全开前把送货单标为待验，不签数量已收。","设备主管核对箱签、底座孔位、动力接口和额定载荷，确认整批为六孔电控件。","供应商展示转接板，设备主管因它未经核准且改变承重与检修空间而拒绝替代验收。","独立监督员签发拒收记录和争议采购行重启询价通知，保留合格供应商重新报价权。"],"visible_payoff":"不兼容批次未入库、未形成请款依据，四孔机械备件采购重新询价且其他资助项目不受影响。","ending":"拒收货箱附带的紧急联络铭牌样张使用已注销的家属联络章，并把设备主管写成已经撤销的岗位名称。","must_include":["送货单标为待验","六孔电控批次","未经核准的转接板","拒收入库并重启询价"],"must_not_include":["供应商永久禁业","麦珂亲自签收","媒体围堵","绝对技术权"],"detailed_synopsis":"同日下午，供应商把六孔电控件运到场馆侧门，要求仓库先签收数量并接受免费转接板。保管员只标待验。设备主管按四孔机械核准规格用量规检查箱签、孔位、接口和载荷，确认整批不兼容；转接板未经核准且会改变承重和检修空间，不能视为等价替代。独立采购监督员签发到货拒收记录和重启询价通知，本批不得请款，供应商仍可按正确规格重新报价。货箱所附联络铭牌样张则出现已注销家属章和过期岗位名。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"六孔电控批次到达侧门并进入待验区"}]
    second["artifact_creates"]=[artifact("ART_228_DELIVERY_ACCEPTANCE",228,"舞台安全备件到货拒收记录","receiving_record",["delivery_pending","six_hole_batch","adapter_not_approved","no_receipt_no_payment"],["refuse_incompatible_delivery","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_228_DISPUTED_LINE_REOPENING",228,"争议采购行重启询价通知","procurement_record",["four_hole_mechanical_baseline","open_requote","other_grant_lines_unaffected"],["reopen_disputed_purchase_line","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_227_APPROVED_PURCHASE_BASELINE","timeline_scope":"current","display_name":"获资助场馆四孔机械备件核准规格表","purpose":"作为到货孔位、动力与载荷验收基线","required_permission":"verify_approved_purchase_baseline","scope_assertion":"只适用于本采购行"},{"artifact_id":"ART_227_UNAUTHORIZED_SPEC_INSERTION","timeline_scope":"current","display_name":"六孔电控规格插入比对记录","purpose":"证明六孔插页没有取得场馆变更同意","required_permission":"quarantine_unapproved_specification","scope_assertion":"不推定供应商其他交易无效"}]


def repair_ec115(event: dict[str, Any]) -> None:
    event.update({
        "name":"过期联络铭牌与值守岗位逐点复核","timeline_years":"1991","main_opponent":"场馆行政联络员与供应商制牌员","opposition_type":"institutional","event_type":"health_welfare","solution_type":"procedural_counter",
        "prev_life_tragedy":"前世场馆把个人姓名和家属联络章当作紧急责任链，岗位轮换后铭牌无人更新；一次夜班事故中，电话接到已离岗人员家中，现场值守席反而没有收到通知。",
        "info_gap_from_prev_life":"麦珂只记得过期岗位会出现在西侧急救点，不能据此断言今生全部铭牌错误；每一点位须以当前排班、功能分机和实际回拨测试核验。",
        "preemptive_avoidance":"场馆值守主管先隔离随拒收货箱到来的样张，再由行政联络员、独立医师和设备主管分别确认职责，不动员观众围查，也不公开私人号码。",
        "bait_and_evidence":"行政联络员称旧家属章能提高可信度并要求批量印刷；逐点清册却显示该章已停用，‘巡演医疗总管’岗位不存在，夜班分机也未接入当前值守台。",
        "villain_loss":"行政联络员失去凭旧样张批量印制和以家属章代替岗位确认的权限，错误样张全部盖停用并退回制牌员。",
        "protagonist_gain":"场馆建立按功能岗位、值守时段和回拨分机管理的联络标识，六个点位在开场前完成逐点测试。",
        "relationship_change":"麦珂接受独立医师拒绝把莉薇娅个人姓名挂作医疗负责人；苏菲亚只核对章与版本，不替值守岗位承担职责。",
        "cluster_outcome":"旧家属章和过期岗位样张未被批量安装，当前岗位矩阵、替换回执和逐点回拨记录共同形成场馆内的可维护联络链。",
        "next_event_hook":"逐点回拨时，器材交接台发现SG-271仍挂着海关开箱前的蓝白旧封志，而放行单要求红白新封志，引出下一簇当前货物交接链复核。",
        "resolution_signature":{"attack_domain":"obsolete_emergency_contact_signage","counter_method":"current_role_matrix_and_point_by_point_callback","resolver":"场馆值守主管","publicity":"internal_safety_record","hero_gain_type":"maintainable_contact_chain"},
        "continuity_writes":["承接EC114拒收货箱附件中的旧家属章和过期岗位样张。","不再使用观众任务卡、全民围查、全国宣言或主角一票否决。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：个人姓名与家属章在岗位轮换后造成夜班通知落空；本事件独有信息差：麦珂只记得西侧急救点；今生提前动作：样张先隔离、逐点以当前岗位和回拨测试核验；第229章可见小赢：旧章、废止岗位和断开的夜班分机形成清册；第230章新交锋：行政联络员要求沿用个人名，值守主管用岗位矩阵替换并逐点回拨；阻力方现实损失：失去批量印制权；主角现实收益：六点联络链可用；结算边界：只治理本场馆，不公开私人号码。"
    event["main_characters"]=["苏菲亚","麦珂","场馆值守主管","独立医师"]
    event["canonical_cast"]=[item for item in event.get("canonical_cast") or [] if item.get("character_id") in {"CHAR_87B8E75FFF6F","CHAR_026AC753E27A"}]
    event["main_character_ids"]=[item["character_id"] for item in event["canonical_cast"]]; event["main_opponent_character_ids"]=[]; event.pop("main_opponent_character_id",None)
    event["state_transitions"]=[
        {"domain":"asset","entity_id":"ASSET_VENUE_EMERGENCY_SIGNAGE","state_key":"sample_status","from":"obsolete_stamp_and_role_ready_to_print","to":"isolated_and_marked_void","irreversible":False,"evidence":"ART_229_SIGNAGE_INVENTORY","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"rights","entity_id":"RIGHT_FAMILY_CONTACT_STAMP_01","state_key":"signage_use_scope","from":"reused_as_duty_authority","to":"blocked_from_operational_signage","irreversible":False,"evidence":"ART_230_SIGNAGE_REPLACEMENT","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"asset","entity_id":"ASSET_VENUE_CONTACT_CHAIN","state_key":"current_shift_reachability","from":"obsolete_names_and_unverified_extensions","to":"functional_roles_and_callbacks_verified","irreversible":False,"evidence":"ART_230_WALKTHROUGH_LOG","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,229)
    first.update({"timeline_start":"1991-10-24","timeline_end":"1991-10-24","scene":"场馆值守与急救联络台","chapter_title":"旧椭圆章与空接夜班分机","chapter_goal":"隔离待印样张，并以当前排班和逐点清册确认旧章、过期岗位及断开分机。","participants":["苏菲亚","麦珂","场馆值守主管","独立医师","场馆行政联络员","供应商制牌员"],"opening_conflict":"行政联络员要求当晚把随货样张批量安装，称家属联络章和莉薇娅姓名比功能岗位更能让观众安心。","info_gap_use":"麦珂只提示前世西侧急救点曾拨错；值守主管从全部六个点位开始，不按记忆预设其他点也有错。","opponent_reaction":"行政联络员称岗位表经常变化，保留名人姓名和旧章反而更稳定。","action_sequence":["苏菲亚核对旧椭圆章停用回执，确认它只能追溯身份联系，不能证明现场值守权限。","值守主管按六个点位登记样张、现牌、功能岗位、白班分机和夜班回拨去向。","独立医师拒绝把莉薇娅个人姓名写成医疗负责人，要求使用当班独立医师与急救协调席。","西侧急救点夜班分机回拨到空接线路，行政联络员的批量印制单被暂停。"],"visible_payoff":"错误不再停留在拼写争论：旧章、废止岗位和一条空接夜班分机形成逐点纸面清册。","ending":"行政联络员提出只改夜班号码，仍保留旧章与个人姓名，以免整批样张作废。","must_include":["旧家属联络章已停用","六个点位逐点登记","独立医师拒绝个人挂名","西侧夜班分机空接"],"must_not_include":["入场券任务","观众围堵","拼写字母游戏","全国统一行动"],"detailed_synopsis":"1991年10月24日傍晚，值守台隔离拒收货箱所附铭牌样张。行政联络员要求保留旧家属章和莉薇娅姓名，苏菲亚以停用回执说明旧章只曾用于身份联系。值守主管不按麦珂前世记忆只查一点，而是登记六个点位的功能岗位、时段和分机。独立医师拒绝个人挂名；回拨测试发现西侧急救点夜班分机空接。批量印制被暂停，但尚未完成替换。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"拒收货箱附带样张进入场馆值守台逐点登记"}]
    first["artifact_creates"]=[artifact("ART_229_SIGNAGE_INVENTORY",229,"场馆紧急联络标识逐点清册","safety_record",["six_locations","sample_versions","current_roles","day_and_night_extensions"],["inventory_venue_contact_signage","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_229_CURRENT_ROLE_MATRIX",229,"场馆值守岗位与联络范围表","duty_record",["functional_roles","shift_windows","callback_extensions","no_private_numbers"],["verify_current_duty_roles","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_219_HEALTH_MEMO_CERTIFIED","timeline_scope":"current","display_name":"经公证的家属签署范围声明","purpose":"证明旧家属章不授予现场医疗或设备值守权","required_permission":"use_as_evidence_within_scope","scope_assertion":"只用于身份与联络范围核验"},{"artifact_id":"ART_228_DELIVERY_ACCEPTANCE","timeline_scope":"current","display_name":"舞台安全备件到货拒收记录","purpose":"确认铭牌样张来自拒收货箱附件","required_permission":"use_as_evidence_within_scope","scope_assertion":"不把铭牌问题并入设备性能结论"}]
    second=milestone(event,230)
    second.update({"timeline_start":"1991-10-24","timeline_end":"1991-10-24","scene":"场馆六点联络标识巡检路线","chapter_title":"岗位替换与六点回拨","chapter_goal":"停用错误样张，按功能岗位更换六点铭牌并完成白班、夜班回拨验收。","participants":["苏菲亚","麦珂","场馆值守主管","独立医师","场馆行政联络员","供应商制牌员","安保值班员"],"opening_conflict":"行政联络员主张只修西侧分机，旧章和个人姓名继续沿用，避免承担整批重制费用。","info_gap_use":"本章不再依靠前世地点决定结论，只按岗位矩阵和逐点清册完成所有回拨。","opponent_reaction":"行政联络员试图让麦珂以艺人身份签字确认个人名更醒目，麦珂拒绝替值守主管作决定。","action_sequence":["值守主管在所有旧样张盖停用章，供应商制牌员按功能岗位和分机制作临时更正牌。","独立医师核对急救协调席职责，苏菲亚确认家属章与私人号码未进入新版。","安保值班员沿六点路线分别拨打白班、夜班分机，由不同接线席复述位置与职责。","两次空接被修正后重新回拨，值守主管签替换回执和逐点验收记录。"],"visible_payoff":"六个点位均能按时段接通正确功能席，错误样张失去批量印制依据，私人身份不再替代岗位责任。","ending":"器材交接台回拨确认位置时，发现SG-271仍挂蓝白旧封志，与海关放行单登记的红白新封志不符。","must_include":["旧样张逐张停用","按功能岗位制牌","白班夜班分别回拨","六点验收记录"],"must_not_include":["麦珂一票否决","公众三方签字","媒体羞辱","全球巡演标配"],"detailed_synopsis":"同日晚间，行政联络员要求只改一条分机，被值守主管拒绝。旧样张逐张盖停用，制牌员按当前功能岗位、时段和内部分机制作更正牌，不印私人号码。独立医师核对医疗职责，麦珂拒绝以艺人身份替值守岗位签字。安保值班员沿六点路线分别测试白班和夜班回拨，两处首次空接在交换台修线后复测通过。替换回执与逐点验收记录锁定版本。器材台随后发现SG-271仍挂海关开箱前的蓝白旧封志，而放行单要求红白新封志。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"停用样张后按岗位矩阵开始六点替换与回拨"}]
    second["artifact_creates"]=[artifact("ART_230_SIGNAGE_REPLACEMENT",230,"过期联络铭牌停用与替换回执","safety_record",["voided_samples","replacement_versions","functional_roles","no_family_stamp"],["retire_obsolete_signage","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_230_WALKTHROUGH_LOG",230,"场馆联络标识六点回拨验收记录","safety_record",["six_locations","day_callbacks","night_callbacks","retests"],["verify_contact_chain_reachability","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_229_SIGNAGE_INVENTORY","timeline_scope":"current","display_name":"场馆紧急联络标识逐点清册","purpose":"提供六点样张与分机差异","required_permission":"inventory_venue_contact_signage","scope_assertion":"仅限本场馆"},{"artifact_id":"ART_229_CURRENT_ROLE_MATRIX","timeline_scope":"current","display_name":"场馆值守岗位与联络范围表","purpose":"确定新版功能岗位、时段和回拨目标","required_permission":"verify_current_duty_roles","scope_assertion":"不得公开私人号码"}]


def repair_ec116(event: dict[str, Any]) -> None:
    event.update({
        "name":"SG-271旧封志与中转仓异常单","timeline_years":"1991","main_opponent":"灰港保税中转仓主管与承运代理","opposition_type":"institutional","event_type":"logistics_evidence","solution_type":"procedural_counter",
        "prev_life_tragedy":"前世转运仓以‘封线磨损’为由自行重封巡演器材，既没有通知货主也没有保留旧封志；到场短件后，承运方反用场馆签收证明交接完整。",
        "info_gap_from_prev_life":"麦珂只记得异常代码S-14和傍晚五点后的短暂中转窗口；当前封志何时被换、箱内是否有变化，必须由今生交接联、称重和官方复验回答。",
        "preemptive_avoidance":"场馆在发现蓝白封志后不拆箱、不签收，苏菲亚以海关红白新封志登记倒查各段交接，要求保税查验人员到场。",
        "bait_and_evidence":"中转仓主管称蓝白封志只是同等级替换并要求场馆补签；承运异常单却显示更换发生在仓内三十六分钟窗口，缺货主通知、双人见证和原封志留存。",
        "villain_loss":"中转仓主管失去自行重封本项目货物的权限，本次异常费不能凭场馆签收转嫁，相关操作进入承运复核。",
        "protagonist_gain":"SG-271在官方监督下完成开箱、清点、复称与再次封志，确认本票无源组件齐全后才进入场馆器材库。",
        "relationship_change":"麦珂接受设备主管拒绝立即开箱的判断；苏菲亚只追交接链，不把封志异常预写成盗窃。",
        "cluster_outcome":"红白新封志在保税中转仓被未经授权替换的断点得到定位，箱内组件经官方复验齐全，中转仓重封权限被收窄。",
        "next_event_hook":"承运异常费账单误用了已重启询价的舞台安全备件采购行代码，引出下一簇费用归属与预算隔离复核。",
        "resolution_signature":{"attack_domain":"bonded_transfer_seal_replacement","counter_method":"handoff_slip_trace_and_official_reinspection","resolver":"保税查验员","publicity":"custody_record","hero_gain_type":"verified_contents_and_restricted_reseal_authority"},
        "continuity_writes":["承接EC115末尾SG-271蓝白旧封志与海关红白新封志不符。","不重复海关X光误判、无源结构初次通关、监控黑屏或巴里首次失信。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：承运仓自行重封后用场馆签收掩盖短件；本事件独有信息差：麦珂只记得S-14与五点后窗口；今生提前动作：到场不拆不签，以红白新封志倒查交接；第231章可见小赢：断点缩到中转仓三十六分钟并取得缺双签异常单；第232章新交锋：仓方要求直接补签，保税查验员监督开箱复称；阻力方现实损失：失去本项目自行重封权且异常费不得转嫁；主角现实收益：组件齐全后合法入库；结算边界：不因封志异常预先认定盗窃。"
    event["main_characters"]=["苏菲亚","麦珂","场馆设备主管","保税查验员"]
    event["canonical_cast"]=[item for item in event.get("canonical_cast") or [] if item.get("character_id") in {"CHAR_87B8E75FFF6F","CHAR_026AC753E27A"}]
    event["main_character_ids"]=[item["character_id"] for item in event["canonical_cast"]]; event["main_opponent_character_ids"]=[]; event.pop("main_opponent_character_id",None)
    event["state_transitions"]=[
        {"domain":"asset","entity_id":"ASSET_SG271_SHIPMENT","state_key":"seal_continuity","from":"red_white_customs_seal_expected_blue_white_found","to":"break_narrowed_to_bonded_depot_window","irreversible":False,"evidence":"ART_231_SEAL_HANDOFF_COMPARISON","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"asset","entity_id":"ASSET_SG271_CONTENTS","state_key":"post_break_inventory","from":"unknown_pending_reinspection","to":"officially_reinspected_complete_and_resealed","irreversible":False,"evidence":"ART_232_CUSTOMS_REINSPECTION","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"rights","entity_id":"RIGHT_BONDED_DEPOT_RESEAL","state_key":"reseal_authority","from":"supervisor_unilateral_exception_claim","to":"customs_notice_and_dual_witness_required","irreversible":False,"evidence":"ART_232_CARRIER_RESEAL_RESTRICTION","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,231)
    first.update({"timeline_start":"1991-10-24","timeline_end":"1991-10-24","scene":"场馆保税器材待验区","chapter_title":"红白记录与蓝白到场封志","chapter_goal":"在不拆箱、不签收的前提下对照海关放行联和三段承运交接，定位封志替换窗口。","participants":["苏菲亚","麦珂","场馆设备主管","场馆器材保管员","承运代理","保税中转仓主管"],"opening_conflict":"承运代理要求场馆先签数量收讫，称蓝白封志与红白封志同等级，不影响箱内器材。","info_gap_use":"麦珂只提示S-14异常代码和傍晚五点后的窗口；苏菲亚按每段时间、重量、封志颜色与号码核验。","opponent_reaction":"中转仓主管承认换封，却称原封线磨损，仓规允许主管单签异常单。","action_sequence":["设备主管按放行单核对SG-271箱体特征与红白新封志预期，拒绝剪断蓝白到场封志。","苏菲亚比对机场装车、保税仓入仓、出仓和场馆到达四张交接联。","入仓联仍记红白封志，出仓联改记蓝白封志；异常单代码S-14，缺货主通知与第二见证。","场馆把货箱留在待验线，制作封志交接断点比对表并申请保税官方复验。"],"visible_payoff":"封志替换断点被缩到保税仓内三十六分钟，场馆没有用签收把异常链洗成完整交接。","ending":"中转仓主管送来补签声明，要求场馆承认箱体外观完好并承担复验与滞留费用。","must_include":["红白新封志记录","蓝白到场封志","S-14异常单缺双签","待验不拆不签"],"must_not_include":["X光误判","遥控炸弹","铅盒透镜","监控恰好黑屏"],"detailed_synopsis":"1991年10月24日晚，SG-271以蓝白封志到达场馆，但海关放行联登记的是红白新封志。承运代理要求先签数量，设备主管拒绝拆箱。苏菲亚按四段交接联追查：保税仓入仓仍为红白，三十六分钟后的出仓变为蓝白；S-14异常单只有仓主管单签，缺货主通知、第二见证与旧封志留存。货箱留在待验线，场馆申请官方复验，不预先断言短件或盗窃。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"蓝白到场封志与红白放行记录进入逐段交接核对"}]
    first["artifact_creates"]=[artifact("ART_231_SEAL_HANDOFF_COMPARISON",231,"SG-271封志交接断点比对表","custody_record",["customs_red_white_seal","arrival_blue_white_seal","four_handoffs","thirty_six_minute_window"],["locate_seal_custody_break","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_231_CARRIER_EXCEPTION_SLIP",231,"保税中转仓S-14封志更换异常单","carrier_record",["s14_code","single_signature","missing_owner_notice","missing_old_seal"],["review_carrier_reseal_exception","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_222_CUSTOMS_RELEASE","timeline_scope":"current","display_name":"本票货物限范围放行单","purpose":"提供SG-271红白新封志与当前运单基线","required_permission":"use_as_evidence_within_scope","scope_assertion":"只核对本票货箱与封志"},{"artifact_id":"ART_230_WALKTHROUGH_LOG","timeline_scope":"current","display_name":"场馆联络标识六点回拨验收记录","purpose":"确认异常在器材交接台回拨时被发现且未拆箱","required_permission":"use_as_evidence_within_scope","scope_assertion":"不把标识验收扩张为器材结论"}]
    second=milestone(event,232)
    second.update({"timeline_start":"1991-10-24","timeline_end":"1991-10-24","scene":"场馆保税复验隔离间","chapter_title":"三箱清点与绿色复封签","chapter_goal":"由保税查验员监督开箱、复称与逐件清点，决定本票货物能否入库并收窄重封权限。","participants":["苏菲亚","麦珂","场馆设备主管","保税查验员","承运复核员","保税中转仓主管","场馆器材保管员"],"opening_conflict":"中转仓主管要求只验外观并让场馆补签，反对打开箱体，称开箱会使承运责任更难划分。","info_gap_use":"本章不以麦珂记忆判断短件，只比较海关装箱清单、开箱记录、出仓重量和当前实物。","opponent_reaction":"仓主管把三磅重量差解释为封线与包装变化，却拿不出被替换封材的留存重量。","action_sequence":["保税查验员登记蓝白封志号码并剪封入袋，三方分别记录开箱前重量。","设备主管按海关清单逐件读序号，保管员复核透镜、机械调节环、无源导光件和包装垫。","查验员把三磅差异对应到缺失的旧木托和新增泡棉，确认组件数量与序号齐全。","查验员使用绿色复验封签闭箱，承运复核员签发重封权限限制与异常费用隔离。"],"visible_payoff":"SG-271组件经官方复验齐全后入库，封志断点仍作为程序违规保留，不因未短件而消失。","ending":"异常费用隔离页显示，承运代理把复验费挂到了刚刚重启询价的舞台安全备件采购行。","must_include":["保税监督开箱","逐件序号与复称","三磅差异找到包装原因","绿色复验封签"],"must_not_include":["黑屏帮助主角","巴里信誉首次受损","海关初次放行","全行业设备标准"],"detailed_synopsis":"同日晚间，保税查验员在场馆隔离间登记并剪下蓝白到场封志。各方复称后发现比海关记录轻三磅；设备主管与保管员按原清单逐件核对，组件数量和序号齐全。差异最终对应中转仓未保留的旧木托与新增泡棉，不被写成盗窃。查验员以绿色复验封签闭箱，SG-271方可入库；仓主管失去单方重封权，今后须海关通知和双人见证。复验费却被错误挂入舞台安全备件采购行。"})
    second["chapter_title"] = "三磅差异与绿色复封签"
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"保税查验员到场后SG-271进入隔离间官方复验"}]
    second["artifact_creates"]=[artifact("ART_232_CUSTOMS_REINSPECTION",232,"SG-271保税开箱复验与绿色封签记录","customs_record",["pre_open_weight","item_serials","packaging_weight_difference","green_reinspection_seal"],["release_after_official_reinspection","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_232_CARRIER_RESEAL_RESTRICTION",232,"保税中转仓重封权限限制与费用隔离单","carrier_record",["customs_notice_required","dual_witness","owner_notification","exception_fee_separated"],["restrict_unilateral_reseal","separate_exception_fee","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_231_SEAL_HANDOFF_COMPARISON","timeline_scope":"current","display_name":"SG-271封志交接断点比对表","purpose":"限定复验针对中转仓内封志断点","required_permission":"locate_seal_custody_break","scope_assertion":"不预断箱内短件"},{"artifact_id":"ART_231_CARRIER_EXCEPTION_SLIP","timeline_scope":"current","display_name":"保税中转仓S-14封志更换异常单","purpose":"核对重封理由、签名与缺失留存","required_permission":"review_carrier_reseal_exception","scope_assertion":"只处理本次S-14异常"},{"artifact_id":"ART_222_CUSTOMS_TECH_EXAM","timeline_scope":"current","display_name":"本票无源组件海关技术查验记录","purpose":"提供海关开箱时的组件序号与称重基线","required_permission":"document_official_customs_exam","scope_assertion":"不重新评价设备性能"}]


def repair_ec117(event: dict[str, Any]) -> None:
    event.update({
        "name":"S-14复验费错挂与四孔采购预算隔离","timeline_years":"1991","main_opponent":"承运计费代理与初声基金采购记账员","opposition_type":"institutional","event_type":"finance_business","solution_type":"financial_counter",
        "prev_life_tragedy":"前世承运异常费被混入场馆安全设备采购，基层场馆为补足账面超支取消了真正需要的机械备件，承运方责任却没有进入争议程序。",
        "info_gap_from_prev_life":"麦珂只记得错挂行代码PL-4和‘现场处置附加费’名目；本次费用是否应由谁承担，必须依承运合同、S-14责任记录和预算用途判断。",
        "preemptive_avoidance":"苏菲亚在账单入账前把正常运费、封志异常复验费和四孔备件预算拆成三栏，设备主管锁定采购余额而不自行裁定承运责任。",
        "bait_and_evidence":"计费代理称复验保障了器材安全，应由安全资助承担；账单却使用四孔备件采购行PL-4，且附件没有场馆费用同意，S-14限制单明确异常费须隔离。",
        "villain_loss":"承运代理失去把S-14异常费直接记入场馆资助的路径，采购记账员失去跨类别手工改码权限。",
        "protagonist_gain":"四孔机械备件预算全额保留，正常运费按合同支付，异常复验费转入承运争议准备金等待内部归责。",
        "relationship_change":"麦珂要求立刻拒付全部运输费用，被苏菲亚和设备主管否决后接受正常运费与异常费分开处理。",
        "cluster_outcome":"S-14复验费在入账前从PL-4采购行剥离，安全采购余额不受侵蚀，跨类费用改码须独立复核。",
        "next_event_hook":"费用归属决定的审批栏出现PX-14代码，而同一代码也出现在一份密封法务文件的收件回执上，引出下一簇授权来源核验。",
        "resolution_signature":{"attack_domain":"carrier_exception_fee_crosscharge","counter_method":"three_bucket_cost_allocation_and_budget_code_guard","resolver":"独立费用复核员","publicity":"accounting_record","hero_gain_type":"purchase_budget_preserved"},
        "continuity_writes":["承接EC116复验费误挂舞台安全备件采购行。","不重复观众查牌、三方急救签字、媒体曝光或全国纠错。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：承运异常费侵蚀机械备件预算；本事件独有信息差：麦珂只记得PL-4与附加费名目；今生提前动作：苏菲亚在入账前拆分正常运费、异常费和采购预算；第233章可见小赢：错挂账单缺场馆同意且PL-4余额被保留；第234章新交锋：计费代理主张安全受益原则，独立复核员按合同与S-14责任分配；阻力方现实损失：失去跨类直记路径；主角现实收益：四孔预算全额保留；结算边界：正常运费照付，异常费进入承运内部争议而非直接没收。"
    event["main_characters"]=["苏菲亚","麦珂","场馆设备主管","独立费用复核员"]
    event["canonical_cast"]=[item for item in event.get("canonical_cast") or [] if item.get("character_id") in {"CHAR_87B8E75FFF6F","CHAR_026AC753E27A"}]; event["main_character_ids"]=[item["character_id"] for item in event["canonical_cast"]]; event["main_opponent_character_ids"]=[]; event.pop("main_opponent_character_id",None)
    event["state_transitions"]=[
        {"domain":"asset","entity_id":"ASSET_FIRST_VOICE_PL4_PURCHASE_BUDGET","state_key":"exception_fee_charge","from":"carrier_reinspection_fee_pending_crosscharge","to":"crosscharge_rejected_and_budget_reserved","irreversible":False,"evidence":"ART_233_EXCEPTION_FEE_CROSSCHARGE","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"asset","entity_id":"ASSET_S14_EXCEPTION_COST","state_key":"cost_allocation","from":"venue_safety_grant_claimed","to":"carrier_dispute_reserve_pending_internal_allocation","irreversible":False,"evidence":"ART_234_FEE_ALLOCATION_DECISION","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"rights","entity_id":"RIGHT_GRANT_LEDGER_RECODE","state_key":"cross_category_recode","from":"procurement_clerk_manual_override","to":"independent_approval_required","irreversible":False,"evidence":"ART_234_BUDGET_CODE_GUARD","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,233)
    first.update({"timeline_start":"1991-10-24","timeline_end":"1991-10-24","scene":"场馆与初声基金联合记账台","chapter_title":"PL-4错挂行与三栏费用表","chapter_goal":"在入账前拆分正常运费、S-14复验费和四孔备件采购余额，确认错挂路径与授权缺口。","participants":["苏菲亚","麦珂","场馆设备主管","基金采购记账员","承运计费代理","基金监督会计"],"opening_conflict":"计费代理要求当夜从PL-4安全采购行扣除复验和等待费，称器材最终安全入库就是场馆受益。","info_gap_use":"麦珂只提示PL-4和现场处置附加费；苏菲亚以当前账单、资助通知、重启询价通知和承运限制单核验。","opponent_reaction":"采购记账员称所有与舞台设备有关的费用都可归入同一安全代码，无需场馆再次同意。","action_sequence":["监督会计在过账前冻结单张账单，不冻结整个资助账户。","苏菲亚把合同正常运费、S-14复验等待费和PL-4四孔备件余额列成三栏。","设备主管确认PL-4用途只有四孔机械备件，未签承运异常费同意。","监督会计制作错挂比对单和采购余额保留单，等待独立费用复核。"],"visible_payoff":"S-14异常费未进入PL-4，四孔备件余额在询价期间保持全额，正常运费也未被无故扣留。","ending":"计费代理提交‘安全受益者承担’条款，要求独立复核员把异常费重新归给场馆。","must_include":["PL-4采购行","正常运费异常费采购预算三栏","缺少场馆费用同意","四孔备件余额保留"],"must_not_include":["观众查铭牌","三方急救签字","冻结整个基金","拒付全部运输费"],"detailed_synopsis":"1991年10月24日深夜，承运代理把S-14复验和等待费挂入PL-4四孔备件采购行。监督会计只暂停该账单。苏菲亚将正常运费、异常费和采购预算拆成三栏；设备主管确认PL-4只用于四孔机械备件，从未同意承运异常费。错挂比对单与采购余额保留单形成，正常运费不受影响，争议交由独立复核。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"承运账单在过账前进入场馆与基金联合记账台"}]
    first["artifact_creates"]=[artifact("ART_233_EXCEPTION_FEE_CROSSCHARGE",233,"S-14复验费与PL-4错挂比对单","accounting_record",["normal_freight","s14_exception_fee","pl4_purchase_line","missing_venue_consent"],["isolate_crosscharged_exception_fee","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_233_PURCHASE_LINE_RESERVATION",233,"四孔机械备件采购余额保留单","grant_record",["full_pl4_balance","four_hole_spares_only","rebid_pending","other_costs_excluded"],["reserve_purchase_line_balance","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_228_DISPUTED_LINE_REOPENING","timeline_scope":"current","display_name":"争议采购行重启询价通知","purpose":"确认PL-4只用于四孔机械备件重新询价","required_permission":"reopen_disputed_purchase_line","scope_assertion":"不得支付运输异常费"},{"artifact_id":"ART_232_CARRIER_RESEAL_RESTRICTION","timeline_scope":"current","display_name":"保税中转仓重封权限限制与费用隔离单","purpose":"证明S-14复验费须与正常运输和场馆采购隔离","required_permission":"separate_exception_fee","scope_assertion":"费用最终归责仍待独立复核"}]
    second=milestone(event,234)
    second.update({"timeline_start":"1991-10-24","timeline_end":"1991-10-24","scene":"承运合同独立费用复核室","chapter_title":"安全受益条款与异常费隔离","chapter_goal":"按承运合同、S-14责任和场馆受益边界决定三类费用归属，并建立跨类改码门禁。","participants":["苏菲亚","麦珂","场馆设备主管","独立费用复核员","承运计费代理","基金监督会计","基金采购记账员"],"opening_conflict":"计费代理援引安全受益条款，主张即使仓方手续有缺陷，复验让场馆获益，费用就应从安全资助支付。","info_gap_use":"本章不以麦珂前世记忆决定归责，只读合同中的正常运输、承运可控异常和货主额外要求三类费用。","opponent_reaction":"采购记账员提出先从PL-4垫付，待承运内部处理后再补回，以免账单逾期。","action_sequence":["复核员确认正常机场至场馆运费符合合同并批准支付。","S-14换封由中转仓单方操作且缺必要见证，相关复验费进入承运争议准备金。","设备主管拒绝PL-4垫付，监督会计确认采购余额继续全额保留。","复核员签费用归属决定和跨类费用拦截规则，取消采购记账员单方改码。"],"visible_payoff":"正常服务获得付款，责任未决的异常费有独立承接账户，四孔备件采购不再为承运程序错误垫资。","ending":"费用归属决定的审批栏出现PX-14代码；法务收件簿显示同一代码还盖在一份密封文件回执上。","must_include":["正常运费照付","S-14费用进入承运争议准备金","PL-4不垫付","跨类改码须独立复核"],"must_not_include":["宣布承运方欺诈","没收全部运费","媒体发布会","麦珂取得财务控制权"],"detailed_synopsis":"同夜，独立复核员区分合同正常运输、承运可控异常和货主额外要求。正常运费获批；S-14由仓方单方换封引起，复验与等待费先进入承运争议准备金，不从PL-4垫付。监督会计保留四孔采购全额余额，并建立跨类别改码须独立批准的门禁。决定书审批栏出现PX-14代码，与一份密封法务文件回执相同。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"三栏费用表进入承运合同独立复核"}]
    second["artifact_creates"]=[artifact("ART_234_FEE_ALLOCATION_DECISION",234,"S-14复验与等待费归属决定","accounting_record",["normal_freight_paid","exception_fee_dispute_reserve","no_pl4_advance","appeal_path"],["allocate_s14_exception_cost","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_234_BUDGET_CODE_GUARD",234,"舞台安全资助跨类费用拦截规则","governance_record",["pl4_allowed_category","cross_category_review","independent_approval","audit_trail"],["block_unapproved_cross_category_recode","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_233_EXCEPTION_FEE_CROSSCHARGE","timeline_scope":"current","display_name":"S-14复验费与PL-4错挂比对单","purpose":"区分正常运费、异常费与采购预算","required_permission":"isolate_crosscharged_exception_fee","scope_assertion":"只处理当前承运账单"},{"artifact_id":"ART_233_PURCHASE_LINE_RESERVATION","timeline_scope":"current","display_name":"四孔机械备件采购余额保留单","purpose":"确认PL-4余额和允许用途","required_permission":"reserve_purchase_line_balance","scope_assertion":"不替代承运合同归责"}]


def repair_ec118(event: dict[str, Any]) -> None:
    event.update({
        "name":"PX-14共享路由码与密封收件边界","timeline_years":"1991","main_opponent":"法务收件管理员与基金采购记账员","opposition_type":"institutional","event_type":"legal_governance","solution_type":"procedural_counter",
        "prev_life_tragedy":"前世法务路由码被当作实质批准号复制到财务与人事文件，麦珂团队只追文件内容，未发现同一编号联单在部门间流转造成的授权混淆。",
        "info_gap_from_prev_life":"麦珂只记得PX-14常出现在文件右下角，不能据此认定密封件内容或制作人；今生须核对编号联单领用簿、用途说明和实际签署权。",
        "preemptive_avoidance":"苏菲亚只比对密封件外封元数据，不拆内容；独立档案监督员把‘送到哪里’的路由码与‘谁批准’的签署号分栏核验。",
        "bait_and_evidence":"收件管理员称PX-14等同法务批准，采购记账员借此为费用决定增加权威；领用簿却显示PX-14只是共享收件联单编号，曾被采购席借走且逾期未归还。",
        "villain_loss":"采购记账员失去用法务路由码补足财务批准的路径，收件管理员失去无登记外借编号联单的权限。",
        "protagonist_gain":"密封法务文件保持未拆，费用决定的独立签署仍按真实权限有效，路由码与批准号从此分离管理。",
        "relationship_change":"麦珂要求立即拆封查内容，被苏菲亚否决后接受先核元数据；团队保护不利于自己的保密边界。",
        "cluster_outcome":"PX-14被确认是共享路由编号而非批准权，跨部门外借断点形成记录，密封件内容未被越权公开。",
        "next_event_hook":"PX-14联单归还袋中夹着一张未被场馆签收的静态声学勘测发票，引出下一簇服务范围与现场基线核验。",
        "resolution_signature":{"attack_domain":"routing_code_misrepresented_as_approval","counter_method":"metadata_only_scope_check_and_numbered_pad_custody","resolver":"独立档案监督员","publicity":"confidential_archive_record","hero_gain_type":"approval_and_routing_separated"},
        "continuity_writes":["承接EC117费用决定与密封法务回执共用PX-14代码。","不重复打字机、色带、精神报告、强制隔离或媒体定伪。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：共享路由码被冒充批准号；本事件独有信息差：麦珂只记得PX-14位置；今生提前动作：苏菲亚只核外封元数据和领用簿；第235章可见小赢：确认同码不等于同内容，密封件保持未拆；第236章新交锋：采购记账员主张路由码补强批准，领用簿证明编号联单被跨部门借用；阻力方现实损失：失去外借与补签路径；主角现实收益：真实签署效力和保密边界同时保留；结算边界：不凭代码认定密封件伪造。"
    event["main_characters"]=["苏菲亚","麦珂","独立档案监督员","基金监督会计"]
    event["canonical_cast"]=[item for item in event.get("canonical_cast") or [] if item.get("character_id") in {"CHAR_87B8E75FFF6F","CHAR_026AC753E27A"}]; event["main_character_ids"]=[item["character_id"] for item in event["canonical_cast"]]; event["main_opponent_character_ids"]=[]; event.pop("main_opponent_character_id",None)
    event["state_transitions"]=[
        {"domain":"rights","entity_id":"RIGHT_PX14_CODE","state_key":"authority_meaning","from":"shared_routing_code_claimed_as_approval","to":"routing_only_not_substantive_approval","irreversible":False,"evidence":"ART_235_PX14_CODE_USAGE_MAP","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"asset","entity_id":"ASSET_SEALED_LEGAL_PACKET_PX14","state_key":"confidentiality_status","from":"opening_requested_due_to_code_match","to":"metadata_verified_contents_sealed","irreversible":False,"evidence":"ART_235_SEALED_RECEIPT_SCOPE","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"rights","entity_id":"RIGHT_NUMBERED_ROUTING_PAD_CUSTODY","state_key":"cross_department_borrowing","from":"unlogged_shared_access","to":"logged_checkout_and_dual_return","irreversible":False,"evidence":"ART_236_CODE_SEPARATION_RULE","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,235)
    first.update({"timeline_start":"1991-10-25","timeline_end":"1991-10-25","scene":"独立档案室密封收件台","chapter_title":"同码不同权与未拆封元数据","chapter_goal":"在不打开法务密封件的前提下核对PX-14在费用决定和收件回执中的位置、用途与签署字段。","participants":["苏菲亚","麦珂","独立档案监督员","基金监督会计","法务收件管理员","基金采购记账员"],"opening_conflict":"麦珂看到同一PX-14后要求立即拆封，采购记账员则称该代码证明费用决定经过法务批准。","info_gap_use":"麦珂只提示前世PX-14常在右下角；苏菲亚不推测内容，先检查外封发件部门、收件时间、封口号和代码字段名。","opponent_reaction":"收件管理员称编号联单长期兼作批准凭证，没必要区分路由和授权。","action_sequence":["档案监督员拒绝无文件所有人或有效命令的拆封请求。","苏菲亚对照费用决定与密封回执，确认一个字段名为审批号，另一个明确写收件路由。","监督会计核对费用决定真实签署，确认独立复核员签名不依赖PX-14仍然有效。","档案监督员制作代码使用比对表与密封回执范围核验单。"],"visible_payoff":"同码只证明编号联单被复用，不证明两份文件内容同源；密封件未被越权打开，费用决定也没有被无根据撤销。","ending":"领用簿显示PX-14所在编号联单本曾由基金采购席借走三日，归还栏为空。","must_include":["密封件不拆封","外封元数据核验","路由码不等于批准号","费用决定真实签署仍有效"],"must_not_include":["精神评估报告","打字机色带","强制医疗隔离","媒体分发密件"],"detailed_synopsis":"1991年10月25日凌晨，团队在独立档案室核对PX-14。麦珂因前世记忆要求拆封，被苏菲亚与档案监督员拒绝。外封元数据显示法务件上的PX-14是收件路由，费用决定却把它预印在审批栏；独立复核员真实签名本身有效。同码不证明同内容或伪造，密封件继续封存。领用簿则显示编号联单本曾被基金采购席借走且未登记归还。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"费用决定与密封回执的PX-14进入元数据范围核验"}]
    first["artifact_creates"]=[artifact("ART_235_PX14_CODE_USAGE_MAP",235,"PX-14跨部门代码使用比对表","archive_record",["fee_decision_field","sealed_receipt_field","routing_vs_approval","real_signatures"],["distinguish_routing_from_approval","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_235_SEALED_RECEIPT_SCOPE",235,"PX-14密封法务收件元数据核验单","archive_record",["sender_department","received_time","seal_number","contents_not_opened"],["verify_sealed_packet_metadata","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_234_FEE_ALLOCATION_DECISION","timeline_scope":"current","display_name":"S-14复验与等待费归属决定","purpose":"核对审批字段、真实签署与PX-14预印位置","required_permission":"allocate_s14_exception_cost","scope_assertion":"不重新审理费用归属"}]
    second=milestone(event,236)
    second.update({"timeline_start":"1991-10-25","timeline_end":"1991-10-25","scene":"独立档案室编号联单保管柜","chapter_title":"三日外借与双人归还袋","chapter_goal":"核对PX-14编号联单本的领用、跨部门外借和归还断点，建立路由码与批准号分离规则。","participants":["苏菲亚","麦珂","独立档案监督员","基金监督会计","法务收件管理员","基金采购记账员","档案保管员"],"opening_conflict":"采购记账员承认借过联单本，却称跨部门共用能减少手续，PX-14足以作为财务补充批准。","info_gap_use":"本章不再使用前世代码推断，只检查联单存根、借出时间、使用页号、归还袋和真实授权名单。","opponent_reaction":"收件管理员试图补写三日前归还日期，并把空白联单页撕下分别交给两个部门。","action_sequence":["档案保管员按页号清点PX-14联单本，确认三页用于法务收件、一页被预印到费用表。","苏菲亚比对碳纸压痕和存根，只证明页源相同，不评价文件内容真假。","档案监督员拒绝倒填归还，要求采购席交回剩余页并装双人归还袋。","监督会计与档案监督员签路由码和批准号分离规则，财务表不得再预印法务路由码。"],"visible_payoff":"PX-14联单本完成逐页回收，采购席不能再借路由码补强批准；密封文件与费用决定各按自己的真实权限存续。","ending":"归还袋夹层里发现一张静态声学勘测发票，服务接收栏没有场馆签名。","must_include":["联单逐页清点","三日外借未归还","拒绝倒填归还日期","路由码批准号分离"],"must_not_include":["公证人认定伪造","抢夺文件","吊销执业资格","麦珂完全控制巡演"],"detailed_synopsis":"同日凌晨，档案保管员逐页清点PX-14联单本，三页用于法务收件，一页被采购席预印到费用表，外借已三日且归还栏为空。碳纸压痕只能证明页源相同，不能证明内容真假。管理员试图倒填日期被拒；剩余页进入双人归还袋。新规则将法务路由码与财务批准号分离。袋内还夹着一张未获场馆签收的静态声学勘测发票。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"PX-14联单本从保管柜取出逐页清点"}]
    second["artifact_creates"]=[artifact("ART_236_ROUTING_PAD_CUSTODY",236,"PX-14编号联单领用与双人归还记录","archive_record",["page_numbers","three_day_checkout","used_pages","dual_return_bag"],["recover_numbered_routing_pad","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_236_CODE_SEPARATION_RULE",236,"法务路由码与财务批准号分离规则","governance_record",["routing_only","approval_signer_registry","no_cross_department_preprint","logged_checkout"],["separate_routing_and_approval_codes","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_235_PX14_CODE_USAGE_MAP","timeline_scope":"current","display_name":"PX-14跨部门代码使用比对表","purpose":"提供两处代码字段用途差异","required_permission":"distinguish_routing_from_approval","scope_assertion":"不评价密封内容真假"},{"artifact_id":"ART_235_SEALED_RECEIPT_SCOPE","timeline_scope":"current","display_name":"PX-14密封法务收件元数据核验单","purpose":"保护密封件内容并核对联单页号","required_permission":"verify_sealed_packet_metadata","scope_assertion":"不得据此拆封"}]


def repair_ec119(event: dict[str, Any]) -> None:
    event.update({
        "name":"未签收声学勘测发票与六点空场基线","timeline_years":"1991","main_opponent":"声学顾问公司项目经理与巡演采购席","opposition_type":"institutional","event_type":"technical_validation","solution_type":"independent_verification",
        "prev_life_tragedy":"前世顾问把建筑图纸桌面估算包装成现场声学勘测，团队按错误基线调校扩声；空调和防火门状态变化后出现反馈，责任被推给现场技术员。",
        "info_gap_from_prev_life":"麦珂只记得发票名目和西侧看台附近的异常频段，不能据此证明今生顾问未到场；须核对出入记录、仪器序号、原始读数和点位图。",
        "preemptive_avoidance":"苏菲亚在发票入账前核对服务接收链；场馆声学主管安排独立工程师在空场、固定声源和两种通风状态下建立六点基线。",
        "bait_and_evidence":"顾问经理称勘测已完成并提交漂亮摘要，却没有场馆签收、点位时刻或仪器序号；后承认数据来自建筑图纸与旧模型，只能算桌面估算。",
        "villain_loss":"顾问公司失去按现场勘测全额请款的资格，采购席失去用摘要代替服务接收的权限。",
        "protagonist_gain":"场馆取得含点位、设备、环境状态和重复测量的六点空场基线，桌面估算费与现场服务费被正确分开。",
        "relationship_change":"麦珂要求直接在演出音量下测试，被独立工程师以空场安全和变量控制否决；他接受先基线、后彩排验证。",
        "cluster_outcome":"未签收发票被还原为桌面估算而非现场勘测，独立六点实测建立可复现基线，付款只覆盖实际交付范围。",
        "next_event_hook":"六点复测显示空调开关状态会产生稳定但非零的测量偏差，引出下一簇误差记录、复测触发与责任边界协议。",
        "resolution_signature":{"attack_domain":"desktop_acoustic_estimate_billed_as_site_survey","counter_method":"service_acceptance_audit_and_controlled_six_point_measurement","resolver":"独立声学工程师","publicity":"technical_record","hero_gain_type":"reproducible_venue_baseline"},
        "continuity_writes":["承接EC118归还袋中的未签收静态声学勘测发票。","不重复暴雨、七路光路、观众敲击抵消共振或演出零秒切换。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：桌面估算冒充现场基线导致调校错误；本事件独有信息差：麦珂只记得西侧频段；今生提前动作：苏菲亚在付款前查服务接收链并安排受控实测；第237章可见小赢：发票缺签收、仪器与原始点位，顾问承认只做桌面估算；第238章新交锋：麦珂要求演出音量实测，独立工程师坚持受控六点空场测试；阻力方现实损失：失去现场勘测全额请款；主角现实收益：取得可重复基线；结算边界：桌面估算若有交付价值可按正确类别支付。"
    event["main_characters"]=["苏菲亚","麦珂","场馆声学主管","独立声学工程师"]
    event["canonical_cast"]=[item for item in event.get("canonical_cast") or [] if item.get("character_id") in {"CHAR_87B8E75FFF6F","CHAR_026AC753E27A"}]; event["main_character_ids"]=[item["character_id"] for item in event["canonical_cast"]]; event["main_opponent_character_ids"]=[]; event.pop("main_opponent_character_id",None)
    event["state_transitions"]=[
        {"domain":"asset","entity_id":"ASSET_ACOUSTIC_SURVEY_SERVICE","state_key":"delivered_scope","from":"site_survey_claimed_on_invoice","to":"desktop_estimate_only_no_site_acceptance","irreversible":False,"evidence":"ART_237_ACOUSTIC_SERVICE_SCOPE_GAP","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"asset","entity_id":"ASSET_VENUE_ACOUSTIC_BASELINE","state_key":"measurement_status","from":"unverified_summary_only","to":"six_point_controlled_baseline_recorded","irreversible":False,"evidence":"ART_238_ACTUAL_ACOUSTIC_BASELINE","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"rights","entity_id":"RIGHT_ACOUSTIC_SERVICE_BILLING","state_key":"invoice_classification","from":"full_site_survey_fee_claimed","to":"desktop_estimate_reclassified_site_fee_rejected","irreversible":False,"evidence":"ART_238_INVOICE_RECLASSIFICATION","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,237)
    first.update({"timeline_start":"1991-10-25","timeline_end":"1991-10-25","scene":"中央体育馆技术服务接收台","chapter_title":"空白接收栏与没有序号的摘要","chapter_goal":"核对静态声学勘测发票、出入记录、工作单、仪器序号和原始点位，界定实际交付范围。","participants":["苏菲亚","麦珂","场馆声学主管","独立声学工程师","声学顾问项目经理","采购席记录员"],"opening_conflict":"顾问经理要求按现场六区勘测全额付款，称摘要图已足够证明服务完成。","info_gap_use":"麦珂只提示前世西侧看台异常频段；苏菲亚不从结果倒推到场，而是核对今生接收链。","opponent_reaction":"项目经理称工程师夜间自行进场，不留场馆签名是为了避免打扰排练。","action_sequence":["苏菲亚核对发票服务接收栏、场馆出入簿和技术钥匙登记，均找不到顾问进场。","声学主管要求工作单、仪器序号、校准日期、六点时刻和原始读数，摘要未包含。","独立工程师比对摘要点位与建筑图纸，发现编号完全沿用旧图层且没有现场障碍修订。","顾问经理承认交付是图纸和旧模型桌面估算，接收台制作服务范围差异单。"],"visible_payoff":"发票不再被当作已完成现场勘测；桌面估算与未交付的现场测量在付款前分开。","ending":"顾问经理要求至少按原价支付，称没有实测也不妨碍摘要为演出提供足够基线。","must_include":["场馆接收栏空白","没有仪器序号与原始读数","出入簿无进场","承认桌面估算"],"must_not_include":["暴雨突至","零秒光路切换","观众敲击抵消共振","全场演出继续"],"detailed_synopsis":"1991年10月25日凌晨，团队核对归还袋中的静态声学勘测发票。场馆接收栏为空，出入簿和技术钥匙登记无顾问进场，摘要也缺仪器序号、校准日期、点位时刻与原始读数。其点位编号直接沿用建筑旧图。顾问经理最终承认只做图纸和旧模型桌面估算。服务范围差异单将它与未交付的现场勘测分开。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"未签收声学勘测发票进入技术服务接收核验"}]
    first["artifact_creates"]=[artifact("ART_237_ACOUSTIC_SERVICE_SCOPE_GAP",237,"静态声学勘测服务范围差异单","technical_service_record",["invoice_claim","desktop_estimate","missing_site_acceptance","missing_raw_measurements"],["classify_delivered_acoustic_scope","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_237_VENUE_ACCESS_LOG",237,"场馆勘测时段出入与技术钥匙核验联","access_record",["venue_entries","technical_key_checkout","claimed_time_window","no_consultant_entry"],["verify_survey_site_access","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_236_ROUTING_PAD_CUSTODY","timeline_scope":"current","display_name":"PX-14编号联单领用与双人归还记录","purpose":"证明发票发现于归还袋夹层并保持来源记录","required_permission":"recover_numbered_routing_pad","scope_assertion":"不把发票内容并入PX-14结论"}]
    second=milestone(event,238)
    second.update({"timeline_start":"1991-10-25","timeline_end":"1991-10-25","scene":"中央体育馆空场六点声学测试路线","chapter_title":"固定声源与两种通风状态","chapter_goal":"由独立工程师在受控条件下完成六点重复测量，建立可复现基线并按实际交付重分类发票。","participants":["苏菲亚","麦珂","场馆声学主管","独立声学工程师","声学顾问项目经理","场馆设备员","基金费用复核员"],"opening_conflict":"麦珂要求直接用演出音量测试西侧异常频段，顾问经理则主张无需再测、摘要已经足够。","info_gap_use":"麦珂只提供前世异常区域作为附加观察点，测试顺序、声源、环境与判断由独立工程师决定。","opponent_reaction":"顾问经理在首轮读数接近摘要时要求立即终止，避免第二通风状态改变结果。","action_sequence":["独立工程师校准声级计，固定声源位置、测试信号、空场门位和六个点位。","六点先在通风关闭状态各测三次，再在通风开启状态按同序复测。","工程师记录西侧与其他点的重复差、环境状态和不确定度，不把单一峰值写成演出故障。","费用复核员按实际交付把旧发票改为桌面估算，现场勘测全额费拒绝，独立实测另行验收。"],"visible_payoff":"场馆获得可复现的六点空场基线；顾问摘要可按桌面估算价值结算，却不能继续领取现场服务全价。","ending":"通风开关造成的稳定偏差被写入附页，需要明确谁记录环境、何时复测、何种差异触发暂停。","must_include":["声级计校准与固定声源","六点各测三次","通风关闭开启分别复测","桌面估算现场勘测费用重分类"],"must_not_include":["万人同频敲击","声波瞬间抵消","巴里瘫坐","永久行业标准"],"detailed_synopsis":"同日凌晨，独立工程师拒绝麦珂直接上演出音量，先建立受控空场基线。固定声源、门位和六点后，声级计校准；通风关闭与开启状态各按同一顺序测三次。西侧数据被作为附加观察但不由前世记忆决定结论。六点基线记录点位、仪器、环境、重复差与不确定度。费用决定把顾问交付重分类为桌面估算，拒绝未完成的现场勘测全价。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"服务范围差异确认后开始受控六点空场测试"}]
    second["artifact_creates"]=[artifact("ART_238_ACTUAL_ACOUSTIC_BASELINE",238,"中央体育馆六点静态声学实测基线","technical_record",["calibrated_meter","fixed_source","six_points","ventilation_states","repeatability"],["establish_reproducible_acoustic_baseline","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_238_INVOICE_RECLASSIFICATION",238,"声学桌面估算与现场勘测费用重分类决定","accounting_record",["desktop_estimate_value","site_survey_not_delivered","independent_measurement_separate","appeal_path"],["reclassify_acoustic_service_invoice","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_237_ACOUSTIC_SERVICE_SCOPE_GAP","timeline_scope":"current","display_name":"静态声学勘测服务范围差异单","purpose":"界定顾问实际交付为桌面估算","required_permission":"classify_delivered_acoustic_scope","scope_assertion":"不否定摘要全部参考价值"},{"artifact_id":"ART_237_VENUE_ACCESS_LOG","timeline_scope":"current","display_name":"场馆勘测时段出入与技术钥匙核验联","purpose":"证明原发票没有对应现场进场记录","required_permission":"verify_survey_site_access","scope_assertion":"仅限所称勘测时段"}]


def repair_ec120(event: dict[str, Any]) -> None:
    event.update({
        "name":"六点基线的不确定度与限次复测规程","timeline_years":"1991","main_opponent":"声学顾问项目经理与场馆流程惯性","opposition_type":"institutional","event_type":"performance","solution_type":"teamwork",
        "prev_life_tragedy":"前世团队把环境偏差写成共同责任，技术、场馆、演出和医疗岗位彼此代签；一次无效测试被当成事故结论，瑟琳娜承担了不属于她的场馆设备责任。",
        "info_gap_from_prev_life":"麦珂记得模糊的共担条款最终让瑟琳娜背责，但今生的复测阈值与责任人必须由六点基线、当前设备状态和各岗位真实权限确定。",
        "preemptive_avoidance":"团队在白天彩排前先制定环境记录、测量不确定度、复测触发和暂停权限矩阵，再按同一声源、点位与通风状态执行有限复测。",
        "bait_and_evidence":"顾问经理要求各方先签笼统共担声明，并在首个超阈值读数后直接认定西侧故障；独立工程师依规发现服务门状态与基线不一致，纠正条件后完成复测。",
        "villain_loss":"顾问经理失去用笼统共担签名替代环境记录、以单次读数直接归责或把独立数据并入旧服务的权限。",
        "protagonist_gain":"中央体育馆获得仅适用于本场馆两次彩排的测量与复测规程，各岗位边界明确且首轮匹配条件复测通过。",
        "relationship_change":"麦珂撤回让独立医师对所有技术异常拥有总否决权的提议，接受瑟琳娜与工程师在各自范围内判断；瑟琳娜不再替场馆设备状态背书。",
        "cluster_outcome":"稳定偏差被转化为可复现的环境记录和复测门槛；一次条件不匹配的超阈值结果被标为无效，条件复原后的有限彩排复测通过。",
        "next_event_hook":"复测附件收到一份声称来自旧案卷的声学数据复印件；团队在回应内容前，先要求核验纸张来源、原始载体和保管链。",
        "resolution_signature":{"attack_domain":"vague_shared_liability_for_measurement_error","counter_method":"role_matrix_and_condition_matched_retest","resolver":"独立声学工程师","publicity":"closed_technical_record","hero_gain_type":"limited_venue_retest_protocol"},
        "continuity_writes":["承接EC119通风开关导致的稳定非零偏差。","不签民事伴侣协议，不建立全球巡演标准，不作媒体统一口径。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：模糊共担条款让瑟琳娜替场馆设备背责；本事件独有信息差：麦珂只记得共担条款的伤害；今生提前动作：先按六点基线制定岗位矩阵与复测门槛；第239章可见小赢：四类岗位拒绝互相代签并形成限次规程；第240章新交锋：首个超阈值读数因服务门状态不匹配被判无效，复原条件后复测通过；阻力方现实损失：顾问不得用笼统签名或单次读数归责；主角现实收益：获得本场馆两次彩排适用的有限规程；结算边界：不推定全球标准或设备永久安全。"
    event["main_characters"]=["麦珂","瑟琳娜","苏菲亚","独立声学工程师","场馆声学主管"]
    event["canonical_cast"]=[item for item in event.get("canonical_cast") or [] if item.get("character_id") in {"CHAR_026AC753E27A","CHAR_4E24DD1EEE76","CHAR_87B8E75FFF6F"}]
    event["main_character_ids"]=[item["character_id"] for item in event["canonical_cast"]]
    event["main_opponent_character_ids"]=[]; event.pop("main_opponent_character_id",None)
    event["state_transitions"]=[
        {"domain":"rights","entity_id":"PROCESS_CENTRAL_ARENA_ACOUSTIC_RETEST","state_key":"measurement_protocol","from":"baseline_deviation_without_retest_owner","to":"condition_matched_limited_retest_protocol_active","irreversible":False,"evidence":"ART_240_LIMITED_PROTOCOL_ACCEPTANCE","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"rights","entity_id":"RIGHT_ACOUSTIC_TEST_RESPONSIBILITY","state_key":"technical_signoff_scope","from":"vague_shared_liability_requested","to":"role_specific_signoff_only","irreversible":False,"evidence":"ART_239_ACOUSTIC_RESPONSIBILITY_MATRIX","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,239)
    first.update({"timeline_start":"1991-10-25","timeline_end":"1991-10-25","scene":"中央体育馆技术协调室","chapter_title":"四类签字与复测门槛","chapter_goal":"依据六点基线写明环境记录、技术测量、演出操作与健康停演的不同责任，形成限次复测草案。","participants":["麦珂","瑟琳娜","苏菲亚","独立声学工程师","场馆声学主管","场馆设备员","巡演独立医师","声学顾问项目经理"],"opening_conflict":"顾问经理递交笼统的误差共担声明，要求所有人在白天彩排前共同承担任何读数与停演后果。","info_gap_use":"麦珂只说明前世模糊共担让瑟琳娜替他人背责；阈值和岗位由当前基线与专业人员决定。","opponent_reaction":"顾问经理主张只有全员同签才能避免无人负责，并要求独立医师对所有技术偏差拥有最终否决。","action_sequence":["独立工程师从六点基线提取仪器、点位、通风、门位、重复差和校准字段。","场馆设备员只签通风、门位与设备状态，瑟琳娜只签演出信号、音量级和操作时点。","独立医师只定义症状与健康停演条件，拒绝判断声学设备是否合格。","各方约定环境不匹配时本轮无效，匹配条件下偏离基线超过三分贝或重复差超过一点五分贝即复测；两次仍超限才由工程师暂停技术升级。"],"visible_payoff":"笼统共担声明被退回，岗位矩阵和测量不确定度草案明确谁记录、谁判断、谁不得代签。","ending":"白天首轮彩排按草案启动，P4第一个读数便偏离匹配基线三点八分贝。","must_include":["六点基线作为输入","环境不匹配本轮无效","三分贝或一点五分贝复测门槛","医疗只判断健康停演"],"must_not_include":["民事伴侣登记","全球巡演标准","媒体统一口径","共同承担一切责任"],"detailed_synopsis":"1991年10月25日上午，顾问经理要求各方签笼统共担声明。团队以六点基线拆出四类责任：工程师负责仪器和技术判读，场馆岗位负责通风门位与设备状态，瑟琳娜负责演出信号和操作时点，独立医师只负责症状与健康停演。麦珂撤回让医师总否决的提议。草案规定环境不匹配时本轮无效；匹配条件下偏离基线超过三分贝或重复差超过一点五分贝才触发复测。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"EC119稳定偏差进入复测职责协调"}]
    first["artifact_creates"]=[artifact("ART_239_MEASUREMENT_UNCERTAINTY_PROTOCOL",239,"六点声学测量不确定度与复测草案","technical_protocol",["baseline_reference","matched_conditions","three_db_trigger","repeat_spread_trigger"],["trigger_condition_matched_retest","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_239_ACOUSTIC_RESPONSIBILITY_MATRIX",239,"声学复测四类岗位责任矩阵","responsibility_record",["measurement_owner","venue_environment_owner","performance_operation_owner","health_stop_owner"],["enforce_role_specific_signoff","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_238_ACTUAL_ACOUSTIC_BASELINE","timeline_scope":"current","display_name":"中央体育馆六点静态声学实测基线","purpose":"提供匹配条件与复测比较基线","required_permission":"establish_reproducible_acoustic_baseline","scope_assertion":"空场基线不能直接等同满场安全结论"}]
    second=milestone(event,240)
    second.update({"timeline_start":"1991-10-25","timeline_end":"1991-10-25","scene":"中央体育馆白天有限彩排测试区","chapter_title":"三点八分贝与未闭服务门","chapter_goal":"依草案处理一次环境不匹配的超阈值读数，并在复原条件后完成可审计的有限复测。","participants":["麦珂","瑟琳娜","苏菲亚","独立声学工程师","场馆声学主管","场馆设备员","巡演独立医师","声学顾问项目经理"],"opening_conflict":"P4首值偏离匹配基线三点八分贝，顾问经理要求立刻认定设备故障并让所有签字人共同承担停演损失。","info_gap_use":"麦珂没有用前世异常覆盖现场程序，只要求执行刚写下的环境核对和复测顺序。","opponent_reaction":"顾问经理试图把未闭服务门称作无关细节，并要求把首值并入顾问旧报告。","action_sequence":["工程师暂停升高测试级别，逐项核对通风、门位、声源和仪器校准。","场馆设备员发现西侧服务门未回到基线闭合位置，本轮被标为条件不匹配、不得用于故障归责。","服务门关闭并稳定环境后，P4按原顺序重测三次，平均值只比匹配基线高零点七分贝且重复差合格。","各岗位分别签署执行记录；规程只对本场馆后续两次彩排生效，期满复核，不并入顾问旧发票。"],"visible_payoff":"首个超阈值数没有被删除，却被正确标为条件不匹配；复原条件后的三次复测通过当前升级门槛。","ending":"复测附件夹入一份声称来自旧案卷的声学数据复印件，来源栏与原始载体均为空。","must_include":["P4偏离三点八分贝","服务门状态不匹配","复原条件后三次复测","只适用本场馆两次彩排"],"must_not_include":["永久安全认证","顾问旧报告追认","新闻发布会","奥瑞恩彻底败退"],"detailed_synopsis":"白天彩排首测中，P4偏离匹配基线三点八分贝。工程师没有直接判故障，而是按草案暂停升级并检查环境，发现西侧服务门未闭。该轮保留但标为条件不匹配，不用于归责。服务门复原后P4重测三次，均值仅高零点七分贝且重复差合格。岗位分别签署执行记录，有限规程仅覆盖本场馆后续两次彩排并在期满复核。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"复测草案在白天有限彩排中执行"}]
    second["artifact_creates"]=[artifact("ART_240_RETEST_EXECUTION_LOG",240,"P4环境匹配复测执行记录","technical_record",["initial_three_point_eight_db","door_mismatch","three_repeats","matched_result"],["record_condition_matched_retest","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_240_LIMITED_PROTOCOL_ACCEPTANCE",240,"中央体育馆两次彩排有限复测规程","technical_protocol",["venue_only","two_rehearsals","role_specific_signatures","expiry_review"],["activate_limited_retest_protocol","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_239_MEASUREMENT_UNCERTAINTY_PROTOCOL","timeline_scope":"current","display_name":"六点声学测量不确定度与复测草案","purpose":"决定首轮是否有效与何时复测","required_permission":"trigger_condition_matched_retest","scope_assertion":"不得以单次读数直接归责"},{"artifact_id":"ART_239_ACOUSTIC_RESPONSIBILITY_MATRIX","timeline_scope":"current","display_name":"声学复测四类岗位责任矩阵","purpose":"约束各岗位签署范围","required_permission":"enforce_role_specific_signoff","scope_assertion":"各岗位不得互相代签"}]


def repair_ec121(event: dict[str, Any]) -> None:
    event.update({
        "name":"无来源声学复印件与本次动议的基础审查","timeline_years":"1991","main_opponent":"奥瑞恩法务代理人与无来源旧案卷复印件","opposition_type":"institutional","event_type":"legal_procedure","solution_type":"legal_evidence",
        "prev_life_tragedy":"前世团队急于用纸张和墨迹猜测攻击一份复印件，反而忽略了谁制作、谁保管、如何转换和原始载体在哪里，争议被拖进无法验证的技术口水战。",
        "info_gap_from_prev_life":"麦珂记得对手会把来源空白的旧数据包装成历史原件；今生只能提前要求保管人、目录号、复制方法与原始载体，不能凭前世记忆断定伪造。",
        "preemptive_avoidance":"苏菲亚先将复印件独立套封并查档案目录、移交登记和复印申请号；法务席在证据基础会议只争取本次动议的可采范围，不要求法官排斥所有电子资料。",
        "bait_and_evidence":"奥瑞恩代理人以页眉年份和曲线外观主张复印件来自旧案卷，却不能提供保管人、目录登记、复制时点、转换方法或可比对的原始载体。",
        "villain_loss":"无来源复印件不得用于本次临时动议，代理人失去以页眉年份和曲线外观替代来源基础的路径；若以后补齐来源仍可另行申请。",
        "protagonist_gain":"团队保住EC120原始执行记录作为当前可验证材料，并取得一份对纸质、模拟和电子资料同样适用的有限基础命令。",
        "relationship_change":"麦珂接受黛安娜和苏菲亚拒绝凭复印纸面猜测墨水年代，不再要求把可疑直接写成伪造。",
        "cluster_outcome":"复印件因缺保管人与原始载体基础被排除于本次动议，而不是被宣布永久伪造；法院要求任何媒介先说明来源、转换与核验方法。",
        "next_event_hook":"复印件页角可见的调档申请号对应一项资产档案查询，但查询范围、申请人权限与费用来源仍需下一簇单独核验。",
        "resolution_signature":{"attack_domain":"unsourced_acoustic_copy_tendered_as_historical_record","counter_method":"custodian_index_conversion_and_original_medium_foundation","resolver":"证据基础会议法官","publicity":"sealed_motion_record","hero_gain_type":"current_motion_scope_exclusion"},
        "continuity_writes":["承接EC120资料夹内来源栏和原始载体编号为空的复印件。","不凭复印件鉴定墨水年份，不排斥全部电子证据，不在本簇办理民事伴侣登记。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：团队因猜测复印件墨水年代而错过来源基础；本事件独有信息差：麦珂只记得对手会包装无来源旧数据；今生提前动作：先查保管人、目录、复制方法和原始载体；第241章可见小赢：档案检索确认页眉年份与入档事实不是同一件事；第242章新交锋：法官要求各媒介一视同仁说明来源基础；阻力方现实损失：复印件不得用于本次动议；主角现实收益：原始执行记录保留为当前可核材料；结算边界：允许以后补齐基础另行申请，不认定永久伪造或彻底败诉。"
    event["main_characters"]=["麦珂","苏菲亚","黛安娜","证据基础会议法官"]
    event["main_opponent_character_ids"]=["CHAR_B6BBF0D9B359"] if any(item.get("character_id")=="CHAR_B6BBF0D9B359" for item in event.get("canonical_cast") or []) else []
    event["state_transitions"]=[
        {"domain":"rights","entity_id":"RIGHT_UNSOURCED_ACOUSTIC_COPY","state_key":"evidentiary_status","from":"tendered_for_temporary_motion","to":"excluded_from_current_motion_without_prejudice","irreversible":False,"evidence":"ART_242_CURRENT_MOTION_EXCLUSION","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"rights","entity_id":"RIGHT_MEDIA_FOUNDATION_REVIEW","state_key":"foundation_rule","from":"medium_label_and_visual_claim","to":"custodian_source_conversion_and_verification_required","irreversible":False,"evidence":"ART_242_EVIDENCE_FOUNDATION_ORDER","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,241)
    first.update({"timeline_start":"1991-10-25","timeline_end":"1991-10-25","scene":"中央体育馆资料接收室与市档案馆电话检索台","chapter_title":"页眉年份不等于入档年份","chapter_goal":"登记无来源复印件的可见字段并核查保管人、目录号、复制申请和原始载体，不对墨水或曲线真伪越级下结论。","participants":["麦珂","苏菲亚","黛安娜","巡演档案员","市档案馆检索员","奥瑞恩法务代理人"],"opening_conflict":"奥瑞恩代理人要求把资料夹中的复印件当作旧案卷原始数据，理由只有页眉年份和手写曲线。","info_gap_use":"麦珂只提醒前世对手曾用旧年份包装材料；苏菲亚和黛安娜拒绝让记忆替代目录与保管链。","opponent_reaction":"代理人要求从复印纸纤维和深浅判断墨迹年代，并称没有目录只是旧档案常见疏漏。","action_sequence":["档案员记录发现位置、纸面页眉、复印缺损和空白来源栏，不拆EC120执行记录的原始装订。","黛安娜指出复印件不能保留原件纸张与墨水材料特征，拒绝作年代鉴定。","市档案馆按页眉案名、日期和可见申请号检索，未找到对应目录项、借阅人或复制登记。","苏菲亚分别形成收件记录和目录检索回执，只写当前未能建立来源，不写伪造结论。"],"visible_payoff":"页眉年份与真实入档被拆开；复印件进入待基础审查状态，EC120原始执行记录仍保持独立来源。","ending":"奥瑞恩代理人提交临时动议，要求次日上午直接用该复印件否定场馆复测。","must_include":["复印件不能鉴定原件墨水年份","无保管人和目录号","未找到复制登记","只写来源尚未建立"],"must_not_include":["墨水年份当场定伪","三十七位医师日志","算法绝不可能篡改","民事伴侣登记"],"detailed_synopsis":"1991年10月25日下午，团队登记EC120资料夹中多出的声学复印件。黛安娜拒绝从复印件判断原件纸张或墨水年代。档案员与市档案馆按页眉、日期和可见申请号查找，均无对应保管人、目录号、借阅或复制登记。苏菲亚只写来源尚未建立，不把缺项升级为伪造；EC120原始执行记录保持独立装订。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"无来源复印件从技术附件转入来源登记"}]
    first["artifact_creates"]=[artifact("ART_241_UNSOURCED_COPY_INTAKE",241,"无来源声学复印件可见字段收件记录","evidence_intake",["discovery_location","visible_header","copy_defects","blank_source_fields"],["quarantine_unsourced_copy","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_241_ARCHIVE_INDEX_SEARCH",241,"旧案卷目录与复制登记检索回执","archive_search",["searched_terms","custodian_result","catalog_result","copy_request_result"],["record_archive_search_result","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_240_RETEST_EXECUTION_LOG","timeline_scope":"current","display_name":"P4环境匹配复测执行记录","purpose":"保持原始执行记录与后来出现的复印件来源分离","required_permission":"record_condition_matched_retest","scope_assertion":"复印件不得并入原始装订"}]
    second=milestone(event,242)
    second.update({"timeline_start":"1991-10-25","timeline_end":"1991-10-25","scene":"市法院证据基础会议室","chapter_title":"保管人缺席与本次动议排除","chapter_goal":"让法院按来源、保管、复制或转换方法与原始载体审查复印件，只决定本次临时动议的使用范围。","participants":["麦珂","苏菲亚","黛安娜","证据基础会议法官","法院书记员","奥瑞恩法务代理人","市档案馆检索员"],"opening_conflict":"代理人称纸质复印件比电子执行记录更可靠，要求法官仅凭页眉年份在临时动议中采纳。","info_gap_use":"麦珂不预判法官偏好，只让法务席提交今生收件、目录检索和EC120原始记录的来源差异。","opponent_reaction":"代理人无法指定保管人或原始载体，转而声称历史曲线无需像现代数据一样说明复制过程。","action_sequence":["法官分别询问谁保管原件、目录号是什么、何时由谁复制、曲线是否经过模拟转数字或其他转换。","档案馆检索员证明当前目录和复制登记均无对应项，但不证明世界上绝无原件。","法院确认EC120执行记录有制作人、仪器号、原始值和逐栏落款，可在自身范围内使用。","复印件被排除于本次临时动议；命令允许代理人以后找到保管人和可核原始载体后另行申请。"],"visible_payoff":"媒介标签不替代来源基础，无来源复印件不能推翻当前可追溯的复测执行记录。","ending":"书记员在复印件页角辨出一段调档申请号，它指向资产档案查询而非声学案卷目录。","must_include":["询问保管人与原始载体","纸质电子同样需要来源基础","本次临时动议排除","允许补齐基础后另行申请"],"must_not_include":["全部电子证据拒绝","奥瑞恩彻底败诉","永久认定伪造","民事伴侣登记"],"detailed_synopsis":"同日傍晚的证据基础会议中，代理人以纸质形式优越为由要求采纳复印件。法官对纸质、模拟和电子材料统一询问保管人、目录号、复制或转换方法及原始载体。检索员只能证明当前目录无记录，不能证明原件永不存在。法院允许EC120可追溯执行记录按自身范围使用，把无来源复印件排除于本次临时动议，并允许以后补齐基础另行申请。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"代理人以无来源复印件提出临时动议"}]
    second["artifact_creates"]=[artifact("ART_242_EVIDENCE_FOUNDATION_ORDER",242,"纸质模拟与电子资料统一来源基础命令","court_order",["custodian","catalog_id","copy_or_conversion_method","original_medium","verification_path"],["require_media_neutral_evidence_foundation","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_242_CURRENT_MOTION_EXCLUSION",242,"无来源声学复印件本次动议排除决定","court_order",["current_motion_only","without_prejudice","refiling_on_foundation","traceable_record_preserved"],["exclude_unsourced_copy_from_current_motion","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_241_UNSOURCED_COPY_INTAKE","timeline_scope":"current","display_name":"无来源声学复印件可见字段收件记录","purpose":"说明复印件发现状态和缺失字段","required_permission":"quarantine_unsourced_copy","scope_assertion":"不作为真伪鉴定"},{"artifact_id":"ART_241_ARCHIVE_INDEX_SEARCH","timeline_scope":"current","display_name":"旧案卷目录与复制登记检索回执","purpose":"证明本次检索未找到来源基础","required_permission":"record_archive_search_result","scope_assertion":"不证明原件永不存在"}]


def repair_ec122(event: dict[str, Any]) -> None:
    event.update({
        "name":"R-8资产调档与共同债务误标更正","timeline_years":"1991","main_opponent":"奥瑞恩法务代理人与资产档案承办商","opposition_type":"institutional","event_type":"finance_business","solution_type":"financial_counter",
        "prev_life_tragedy":"前世一张把麦珂与瑟琳娜误列为共同债务人的资产调档表被反复复制，后来查询方借模板误标扩大检索范围，关系与资产安排都被外部期限绑架。",
        "info_gap_from_prev_life":"麦珂记得维克多会在证据争议后转查资产，也记得瑟琳娜因仓促文件承担过他人债务；今生仍须由R-8申请、签名、收费码和档案权限证明谁查了什么。",
        "preemptive_avoidance":"团队先核对R-8残号对应的申请原件、查询主体、共同债务分类、授权签名和费用账户；不在十分钟内签伴侣登记或复杂信托。",
        "bait_and_evidence":"承办商把无签名的共同债务框称为普通模板，要求先交付两人的完整资产汇总；申请费用却记在奥瑞恩法务客户码，且没有税务机关通知或司法调取令。",
        "villain_loss":"承办商失去把两名独立主体合并检索、取得非公开余额或用税务字样扩大权限的本次通道；奥瑞恩只能按公开目录分别申请并承担自己的费用。",
        "protagonist_gain":"麦珂与瑟琳娜各自账户、债务与档案查询范围得到书面分列，任何真实税务或司法程序仍须按自己的法定来源另行送达。",
        "relationship_change":"麦珂因前世恐惧提出立即登记与设立双轨信托，瑟琳娜拒绝在外部威胁下作终身选择；他撤回期限，双方约定各自独立律师审阅后再决定。",
        "cluster_outcome":"R-8被确认是收费给奥瑞恩的资产档案查询而非税务冻结令；共同债务误标被更正，公开索引查询可分别继续，非公开数据不得交付。",
        "next_event_hook":"承办商已经合法取得的一份公开目录只显示1983年初声基金捐赠票据影印权发生过一次转让，具体受让人和原件基础仍待下一簇核查。",
        "resolution_signature":{"attack_domain":"joint_debtor_mislabel_expands_asset_archive_request","counter_method":"request_signature_billing_and_access_scope_audit","resolver":"市资产档案监督员","publicity":"closed_records_conference","hero_gain_type":"separate_subject_limited_public_index_access"},
        "continuity_writes":["承接EC121页角R-8资产调档申请号。","不以仓促伴侣登记或万能信托抵御税务程序，不宣告资产物理分散。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：共同债务误标被外部查询方反复利用；本事件独有信息差：麦珂记得资产调查与瑟琳娜仓促背责；今生提前动作：核对R-8申请主体、签名、费用和权限；第243章可见小赢：确认两人从未签共同债务栏且费用属于奥瑞恩客户码；第244章新交锋：承办商以税务字样索要完整汇总，监督员只准分别查询公开索引；阻力方现实损失：合并检索和非公开数据通道被取消；主角现实收益：账户、债务和查询范围书面分列；关系变化：拒绝被外部期限逼迫登记或设信托；结算边界：真实税务或司法程序仍可依法另行送达。"
    event["main_characters"]=["麦珂","瑟琳娜","苏菲亚","独立资产律师","市资产档案监督员"]
    event["state_transitions"]=[
        {"domain":"rights","entity_id":"RIGHT_R8_ASSET_ARCHIVE_REQUEST","state_key":"archive_access_scope","from":"joint_subject_full_asset_summary_requested","to":"separate_subject_public_index_only","irreversible":False,"evidence":"ART_244_LIMITED_ARCHIVE_ACCESS_ORDER","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"relationship","entity_id":"REL_MIKE_SELENA_FINANCIAL_LIABILITY","state_key":"debt_assumption_status","from":"unsigned_joint_debtor_template_label","to":"no_mutual_debt_assumption_without_separate_consent","irreversible":False,"evidence":"ART_244_SEPARATE_ACCOUNT_NONASSUMPTION","effect_type":"relationship_change","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,243)
    first.update({"timeline_start":"1991-10-26","timeline_end":"1991-10-26","scene":"市资产档案局R-8申请复核窗","chapter_title":"共同债务框与奥瑞恩收费码","chapter_goal":"查明R-8调档申请的主体、签名、分类与费用来源，隔离未经本人同意的共同债务误标。","participants":["麦珂","瑟琳娜","苏菲亚","独立资产律师","资产档案承办商代表","市资产档案登记员"],"opening_conflict":"承办商代表称R-8只是公开资产汇总申请，却要求麦珂与瑟琳娜按共同家庭债务人补签空白栏。","info_gap_use":"麦珂只用前世资产调查时点要求抢在交付前查原表；谁申请和谁付费由今生窗口存根证明。","opponent_reaction":"代表把共同债务框解释为便于检索的模板，并以即将到来的税务审查催促两人立即设立伴侣与信托关系。","action_sequence":["登记员按R-8残号调出申请原件和收费存根，确认查询对象被合并但两人的授权签名均为空。","苏菲亚核对客户收费码，确认申请费由奥瑞恩法务账户预付，不来自麦珂或瑟琳娜。","麦珂提出立即登记和设立双轨信托，瑟琳娜与独立律师拒绝在外部期限下签长期安排，麦珂撤回。","律师制作申请范围审计与共同债务误标异议，只暂停合并交付，不阻止依法分别查询公开索引。"],"visible_payoff":"R-8被确定为奥瑞恩付费的档案申请而非税务冻结令；无签名共同债务框进入更正程序。","ending":"承办商代表主张表头写有税务复核字样，仍要求次日交付两人的完整资产汇总。","must_include":["R-8申请原件","共同债务栏无本人签名","奥瑞恩法务客户码付费","拒绝仓促伴侣与信托签署"],"must_not_include":["十分钟完成信托","民事伴侣立即登记","自动免税","资产物理分散"],"detailed_synopsis":"1991年10月26日上午，R-8复核窗调出申请原件：麦珂和瑟琳娜被合并列为共同债务人，两人的授权签名均空白，费用则由奥瑞恩法务客户码预付。承办商以税务审查催促补签并建议立即登记伴侣、设立信托。麦珂因前世恐惧一度同意抢签，瑟琳娜与独立律师拒绝后他撤回。团队只暂停合并交付，分别查询公开索引的合法路径保留。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"EC121残号进入R-8申请原件复核"}]
    first["artifact_creates"]=[artifact("ART_243_R8_REQUEST_SCOPE_AUDIT",243,"R-8资产调档申请主体与收费范围审计","access_audit",["request_subjects","authorization_signatures","billing_client_code","requested_data_scope"],["audit_r8_asset_request_scope","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_243_JOINT_DEBT_MISLABEL",243,"无签名共同债务分类异议单","correction_request",["unsigned_joint_debtor_box","separate_subjects","delivery_hold_scope","correction_requested"],["challenge_unsigned_joint_debt_label","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_242_CURRENT_MOTION_EXCLUSION","timeline_scope":"current","display_name":"无来源声学复印件本次动议排除决定","purpose":"引用页角R-8残号的发现和有限记录范围","required_permission":"exclude_unsourced_copy_from_current_motion","scope_assertion":"不得把证据排除决定扩成资产调档权限"}]
    second=milestone(event,244)
    second.update({"timeline_start":"1991-10-26","timeline_end":"1991-10-26","scene":"市资产档案局封闭范围听证室","chapter_title":"公开索引与非公开余额的界线","chapter_goal":"审查R-8表头税务字样的真实权限，分别确定公开索引、非公开数据和共同债务分类的处理。","participants":["麦珂","瑟琳娜","苏菲亚","独立资产律师","市资产档案监督员","资产档案承办商代表","奥瑞恩法务代理人"],"opening_conflict":"承办商与奥瑞恩代理人以税务复核表头为由，要求一次性交付两人的账户余额、债务和资产变动。","info_gap_use":"麦珂不以未来调查时点证明越权，只要求出示税务机关通知、司法命令或两名主体分别签署的授权。","opponent_reaction":"代理人无法提交公权力文书，转而称公开目录与完整余额只是同一汇总的不同栏目。","action_sequence":["监督员区分公开产权与转让索引、局内非公开申报附件、银行账户余额三类来源。","代理人只能证明私人委托与费用支付，不能取得税务机关或法院权限，也没有两名主体授权。","监督员更正共同债务分类，允许按姓名分别交付已公开目录，拒绝非公开附件和余额。","麦珂与瑟琳娜各自确认不替对方承担债务；未来伴侣或信托安排须经各自律师审阅，不在本次听证生效。"],"visible_payoff":"奥瑞恩得到的最多是任何人可依法申请的分列公开索引，无法取得合并资产画像或非公开余额。","ending":"公开索引中出现1983年初声基金捐赠票据影印权转让，但受让人栏只显示一个待核代码。","must_include":["税务或司法权限文书缺失","公开索引与非公开余额分开","分别交付不合并画像","真实程序仍可另行送达"],"must_not_include":["彻底粉碎税务稽查","信托自动挡回冻结","永久免于调查","宣布伴侣关系生效"],"detailed_synopsis":"同日下午，封闭范围听证区分公开产权转让索引、局内非公开申报附件和银行余额。奥瑞恩只能证明私人委托和付费，没有税务机关通知、司法命令或两人的分别授权。监督员更正共同债务误标，只准按两名主体分别交付公开索引，拒绝非公开附件和余额；真实税务或司法程序仍可依法送达。双方确认互不代担债务，伴侣或信托选择留给独立律师审阅。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"R-8合并交付争议进入封闭范围听证"}]
    second["artifact_creates"]=[artifact("ART_244_LIMITED_ARCHIVE_ACCESS_ORDER",244,"R-8分列公开索引有限交付令","access_order",["separate_subject_delivery","public_index_only","no_private_balance","lawful_process_preserved"],["limit_r8_delivery_to_public_index","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_244_SEPARATE_ACCOUNT_NONASSUMPTION",244,"独立账户与债务不代担确认","financial_scope_record",["separate_accounts","no_mutual_debt_assumption","future_independent_counsel","no_relationship_registration_effect"],["record_no_mutual_debt_assumption","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_243_R8_REQUEST_SCOPE_AUDIT","timeline_scope":"current","display_name":"R-8资产调档申请主体与收费范围审计","purpose":"证明私人申请的主体、付费与请求范围","required_permission":"audit_r8_asset_request_scope","scope_assertion":"私人付费不产生公权力查询权限"},{"artifact_id":"ART_243_JOINT_DEBT_MISLABEL","timeline_scope":"current","display_name":"无签名共同债务分类异议单","purpose":"处理未经本人同意的合并分类","required_permission":"challenge_unsigned_joint_debt_label","scope_assertion":"不妨碍依法分别查询公开索引"}]


def repair_ec123(event: dict[str, Any]) -> None:
    event.update({
        "name":"HV-19缩微库位与影印权范围核验","timeline_years":"1991","main_opponent":"海港缩微资料库承包商与奥瑞恩法务代理人","opposition_type":"institutional","event_type":"contract_rights","solution_type":"legal_evidence",
        "prev_life_tragedy":"前世团队把一项影印服务权误当成捐赠票据所有权，追错资产主体；对手则借一卷无帧号复制品宣称掌握全部原件，真实转让附件长期无人核对。",
        "info_gap_from_prev_life":"麦珂记得1983年影印环节后来被用来遮蔽票据来源，但HV-19究竟是公司、库位还是权利代码，必须由现行目录、卷片盒签和转让摘要证明。",
        "preemptive_avoidance":"团队依法申请查看公开索引对应的缩微目录卡和监督阅片，不携带所谓1977原版磁带，也不让新闻发布会替代权利范围核验。",
        "bait_and_evidence":"承包商与奥瑞恩代理人把HV-19称为受让实体，要求按商业秘密拒绝查看；库位卡却显示HV为海港库区、19为格位，1983文书只授予制作保管副本的有限影印许可。",
        "villain_loss":"奥瑞恩失去用HV-19代码和复制卷片宣称持有捐赠票据原件、债权或全部内容版权的本次主张；承包商须按帧号保留监督阅片记录。",
        "protagonist_gain":"团队取得影印许可的真实范围和可复现帧号，确认公开索引指向保管服务而非资产所有权，并定位尚未调取的附表B库号。",
        "relationship_change":"麦珂接受艾琳只记录可见帧与操作条件、不替他向媒体下定伪结论；瑟琳娜继续保留独立资产决定，不在本簇重签任何关系文件。",
        "cluster_outcome":"HV-19被还原为海港缩微库位；监督阅片证明1983许可只覆盖一套保管母片和服务副本，票据所有权与实际控制人仍须查附表B。",
        "next_event_hook":"卷片末帧引用附表B库号SB-83-6；该附表的调取费被记入一笔来源不明的初声基金服务预付款，引出下一簇费用与授权核验。",
        "resolution_signature":{"attack_domain":"microfilm_locator_laundered_as_asset_ownership","counter_method":"locator_card_frame_log_and_transfer_scope_abstract","resolver":"市缩微资料监督员","publicity":"supervised_reading_record","hero_gain_type":"reproduction_permission_distinguished_from_note_ownership"},
        "continuity_writes":["承接EC122公开索引中的HV-19代码和1983年影印权转让。","不重复声波污染审判、医师日志、新闻发布会或伴侣信托签署。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：团队把影印服务权误当票据所有权而追错主体；本事件独有信息差：麦珂只记得1983影印环节异常；今生提前动作：核验HV-19目录卡、盒签、帧号和转让摘要；第245章可见小赢：确认HV-19是海港库区第19格而非受让公司；第246章新交锋：监督阅片区分保管母片、服务副本与票据原件；阻力方现实损失：不能再以代码和复制卷主张原件、债权或全部版权；主角现实收益：取得可复现帧号并定位附表B；结算边界：尚未确定票据实际控制人。"
    event["main_characters"]=["麦珂","苏菲亚","艾琳","市缩微资料监督员"]
    event["state_transitions"]=[
        {"domain":"asset","entity_id":"ASSET_HV19_MICROFILM_LOCATOR","state_key":"code_identity","from":"ambiguous_transferee_code","to":"harbor_vault_bay_19_locator","irreversible":False,"evidence":"ART_245_HV19_LOCATOR_DECODING","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"rights","entity_id":"RIGHT_1983_FIRST_VOICE_REPRODUCTION","state_key":"transferred_scope","from":"claimed_note_ownership_and_full_content_rights","to":"one_custody_master_and_service_copy_permission_only","irreversible":False,"evidence":"ART_246_RIGHTS_SCOPE_DETERMINATION","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,245)
    first.update({"timeline_start":"1991-10-26","timeline_end":"1991-10-26","scene":"市海港缩微资料库目录卡室","chapter_title":"HV不是公司名，19不是受让人","chapter_goal":"以公开卷号查验HV-19目录卡、库位盒签与1983转让摘要，先确定代码身份和可查看范围。","participants":["麦珂","苏菲亚","艾琳","市缩微资料监督员","资料库承包商经理","奥瑞恩法务代理人"],"opening_conflict":"代理人称HV-19是受让影印权的商业实体，目录细节属于商业秘密，不应允许团队查看。","info_gap_use":"麦珂只说明前世记得1983影印环节；他不把HV-19预设成离岸公司或奥瑞恩别名。","opponent_reaction":"承包商经理试图只提供一张自制摘要，把库位卡和盒签留在封闭柜中。","action_sequence":["监督员按公开索引卷号调出同年代目录卡，解释HV是Harbor Vault库区缩写、19是物理格位。","苏菲亚核对卡片修订日期、盒签、卷号与取用簿，确认代码稳定指向保管位置。","艾琳只记录可见字段和查看条件，不拍摄其他客户目录。","监督员允许次章在封闭阅片室查看相关卷和1983转让摘要，不开放无关格位。"],"visible_payoff":"HV-19从模糊受让人代码还原为海港库区第19格，团队取得一卷一摘要的有限阅片许可。","ending":"承包商经理称卷片首帧写有全部影印权，仍主张它等于票据资产所有权。","must_include":["HV为海港库区缩写","19为物理格位","盒签卷号取用簿三方核对","只获相关卷有限阅片"],"must_not_include":["离岸公司当场定论","播放1977磁带","三十七位医师日志","新闻发布会"],"detailed_synopsis":"1991年10月26日下午，团队凭R-8公开索引卷号进入市海港缩微资料库目录卡室。奥瑞恩称HV-19为商业受让实体，监督员却以同年代目录卡、物理盒签和取用簿确认HV是Harbor Vault库区缩写、19是格位。艾琳只记录相关可见字段。团队获准在封闭阅片室查看一卷缩微片及1983转让摘要，不开放其他客户资料。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"HV-19公开索引代码进入实体目录卡核验"}]
    first["artifact_creates"]=[artifact("ART_245_HV19_LOCATOR_DECODING",245,"HV-19缩微库位代码核验卡","archive_record",["harbor_vault_prefix","bay_19","box_label","reel_number","access_log"],["decode_hv19_locator","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_245_REPRODUCTION_SCOPE_ABSTRACT",245,"1983影印许可转让摘要调阅联","access_record",["transfer_date","document_title","reel_scope","supervised_viewing_only"],["authorize_scoped_microfilm_viewing","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_244_LIMITED_ARCHIVE_ACCESS_ORDER","timeline_scope":"current","display_name":"R-8分列公开索引有限交付令","purpose":"证明团队合法取得HV-19公开索引条目","required_permission":"limit_r8_delivery_to_public_index","scope_assertion":"公开索引不证明代码含义或资产所有权"}]
    second=milestone(event,246)
    second.update({"timeline_start":"1991-10-26","timeline_end":"1991-10-26","scene":"市海港缩微资料库封闭阅片室","chapter_title":"母片一套与附表B库号","chapter_goal":"在监督阅片中记录帧号、拼接和1983许可文字，区分影印服务、票据原件与债权所有权。","participants":["麦珂","苏菲亚","艾琳","市缩微资料监督员","资料库承包商经理","奥瑞恩法务代理人","缩微设备操作员"],"opening_conflict":"承包商经理以首帧的全部影印字样主张HV-19持有票据原件、债权和全部内容权，要求停止逐帧查看。","info_gap_use":"麦珂不凭前世记忆指出哪一帧是真相，只要求按许可顺序记录首帧、正文、附注和末帧。","opponent_reaction":"代理人试图只投影首帧标题并跳过限定制作数量与用途的正文。","action_sequence":["操作员在监督下核对卷号、起止帧与拼接记录，任何停片和倒片均写入日志。","艾琳记录首帧标题、正文许可对象和末帧引用，不将屏幕照片当作原件。","监督员确认许可仅含一套保管母片与必要服务副本，不转让票据原件、债权或未列内容版权。","末帧引用附表B库号SB-83-6；本章只定位，不在未调取前猜测实际控制人。"],"visible_payoff":"复制卷的可用范围和可复现帧号被锁定，奥瑞恩无法继续用首帧标题扩张为资产所有权。","ending":"附表B调取卡显示费用已由初声基金服务预付款垫付，授权人栏却只有一个不完整缩写。","must_include":["卷号起止帧与拼接记录","首帧标题不能覆盖正文限定","一套保管母片与服务副本","附表B库号SB-83-6"],"must_not_include":["算法生成定伪","公信力彻底破产","观众成为调查者","民事伴侣或信托签署"],"detailed_synopsis":"同日下午，封闭阅片室按卷号、起止帧和拼接记录监督操作。代理人试图以首帧全部影印标题主张资产所有权，正文却只许可制作一套保管母片和必要服务副本，不转让票据原件、债权或未列版权。艾琳只记录帧号和可见文字。末帧引用附表B库号SB-83-6，实际控制人仍待调取；调取卡费用栏出现初声基金服务预付款。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"目录卡核验后进入相关卷监督阅片"}]
    second["artifact_creates"]=[artifact("ART_246_MICROFILM_FRAME_LOG",246,"HV-19相关卷监督阅片帧号日志","technical_record",["reel_number","start_frame","end_frame","splice_log","operator_actions"],["record_supervised_microfilm_frames","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_246_RIGHTS_SCOPE_DETERMINATION",246,"1983影印许可与票据所有权范围决定","rights_record",["one_custody_master","service_copies","no_note_title_transfer","schedule_b_locator"],["separate_reproduction_permission_from_note_ownership","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_245_HV19_LOCATOR_DECODING","timeline_scope":"current","display_name":"HV-19缩微库位代码核验卡","purpose":"定位唯一相关格位和卷号","required_permission":"decode_hv19_locator","scope_assertion":"库位代码不是受让人身份"},{"artifact_id":"ART_245_REPRODUCTION_SCOPE_ABSTRACT","timeline_scope":"current","display_name":"1983影印许可转让摘要调阅联","purpose":"限定监督阅片对象和范围","required_permission":"authorize_scoped_microfilm_viewing","scope_assertion":"不开放无关客户资料"}]


def repair_ec124(event: dict[str, Any]) -> None:
    event.update({
        "name":"SB-83-6调取费与S.R.路由栏核验","timeline_years":"1991","main_opponent":"海港缩微资料库收费承包商与无授权预付款扣记","opposition_type":"institutional","event_type":"finance_business","solution_type":"financial_counter",
        "prev_life_tragedy":"前世基金预付款被缩微资料承包商当成通用零钱账户，路由缩写被误认作批准人签名；多笔小额调取费绕过授权，最终让外部查询者借基金自己的钱翻查基金档案。",
        "info_gap_from_prev_life":"麦珂记得附表费用曾从基金账户流出，却不知道S.R.代表谁；今生必须用收费栏图例、同批票据、银行日结与基金授权册判断它是人名、部门还是路由代码。",
        "preemptive_avoidance":"团队在查看SB-83-6内容前先核验十八美元调取费的付款来源、申请人、路由栏和批准栏，并拒绝用已经扣款的事实倒推访问已获授权。",
        "bait_and_evidence":"承包商称S.R.是基金授权人缩写，收费完成即代表调阅同意；同批空白票据的印刷图例却把S.R.定义为Service Retrieval服务检索路由，真正批准栏为空。",
        "villain_loss":"承包商退回十八美元至初声基金服务预付款，失去凭路由码单方扣记和释放附表的权限；外部申请方须以自己的费用和明确范围重新申请。",
        "protagonist_gain":"基金预付款恢复，SB-83-6继续密封；团队取得收费、路由、批准和交付四栏分离的调取规则，为后续独立授权阅片保留干净入口。",
        "relationship_change":"麦珂接受苏菲亚拒绝先看附表再补授权，不把自己对资金流出的前世记忆升级成内容访问权。",
        "cluster_outcome":"S.R.被确认是印刷路由码而非个人签名；无授权十八美元扣记原路退回，附表B未交付，后续只能由基金独立席位按限定帧范围重新申请。",
        "next_event_hook":"11月15日初声基金独立席位将审查SB-83-6的限定调阅申请；申请附件里出现一张纸张批次与1983原件不匹配的后制封面，但正文帧仍须分别核验。",
        "resolution_signature":{"attack_domain":"routing_code_laundered_as_prepaid_archive_authorization","counter_method":"printed_legend_batch_slip_and_bank_posting_reconciliation","resolver":"基金独立会计与资料库出纳","publicity":"cashier_and_bank_records","hero_gain_type":"prepayment_restored_and_schedule_sealed"},
        "continuity_writes":["承接EC123附表B库号SB-83-6、初声基金服务预付款和S.R.残缺栏。","不再安排暴雨、观众敲击、建筑共振、噪音诉讼或州级安全立法。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：基金预付款被路由码冒充授权连续扣费；本事件独有信息差：麦珂只记得附表费用从基金流出；今生提前动作：在阅片前核验收费图例、同批票据、批准栏和银行日结；第247章可见小赢：S.R.被确认是Service Retrieval路由码而非人名签署；第248章新交锋：承包商以已扣费要求交付附表，团队拒绝倒填授权并完成十八美元原路退回；阻力方现实损失：失去单方扣记和释放附表权限；主角现实收益：预付款恢复且附表保持密封；结算边界：外部申请人仍可自费按范围申请。"
    event["main_characters"]=["麦珂","苏菲亚","基金独立会计","市缩微资料监督员"]
    event["state_transitions"]=[
        {"domain":"asset","entity_id":"ASSET_FIRST_VOICE_ARCHIVE_PREPAYMENT","state_key":"sb83_6_retrieval_fee","from":"eighteen_dollars_charged_without_approval","to":"eighteen_dollars_restored_to_fund","irreversible":False,"evidence":"ART_248_PREPAYMENT_REIMBURSEMENT","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"rights","entity_id":"RIGHT_SB83_6_SCHEDULE_ACCESS","state_key":"release_authority","from":"routing_code_treated_as_authorization","to":"independent_fund_approval_and_scoped_request_required","irreversible":False,"evidence":"ART_248_SCHEDULE_B_ACCESS_HOLD","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,247)
    first.update({"timeline_start":"1991-10-26","timeline_end":"1991-10-26","scene":"海港缩微资料库收费笼与日结票据台","chapter_title":"十八美元与印刷在格内的S.R.","chapter_goal":"在调阅附表内容前核对十八美元扣记的申请、路由、批准与银行入账，确定S.R.字段类型。","participants":["麦珂","苏菲亚","基金独立会计","市缩微资料监督员","资料库出纳","收费承包商经理"],"opening_conflict":"出纳称SB-83-6调取费已由初声基金预付款支付，S.R.就是授权人缩写，附表可以立即出库。","info_gap_use":"麦珂只提醒前世见过基金支付这笔小额费用；苏菲亚不据此猜测S.R.是谁。","opponent_reaction":"承包商经理要求先收附表再补签批准栏，声称小额服务费向来只看路由缩写。","action_sequence":["出纳调出1983收费联、当日日结页和同批未用票据，分别核对申请人、金额、路由和批准栏。","票据底端印刷图例显示S.R.为Service Retrieval服务检索路由，同批每张都有，不是手写姓名。","基金独立会计核对授权册，确认十八美元扣记没有对应基金批准号，银行日结只证明钱已划出。","监督员冻结附表交付并制作费用链与路由字段核验记录，不打开SB-83-6。"],"visible_payoff":"S.R.从可疑人名还原为印刷路由码；已付款与已授权被拆开，附表仍在密封格。","ending":"承包商经理主张服务已经完成，拒绝把十八美元退回基金预付款。","must_include":["十八美元调取费","S.R.为Service Retrieval路由码","批准栏为空","已扣款不等于已授权"],"must_not_include":["把S.R.指认为苏菲亚","先看附表后补授权","暴雨演出","观众敲击"],"detailed_synopsis":"1991年10月26日傍晚，收费笼调出SB-83-6的1983收费联、银行日结和同批空白票据。S.R.印在同批每张票据的路由格，图例为Service Retrieval，不是个人签名；真正批准栏为空，基金授权册无对应号。十八美元已从基金预付款划出只能证明过账，不证明调阅获准。监督员冻结附表交付，不打开密封格。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"附表B调取卡进入收费与授权字段核验"}]
    first["artifact_creates"]=[artifact("ART_247_SB83_6_FEE_CHAIN",247,"SB-83-6十八美元调取费过账链","accounting_record",["requester","prepayment_account","eighteen_dollars","bank_posting","blank_approval"],["audit_schedule_b_retrieval_fee","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_247_SR_ROUTE_CODE",247,"S.R.服务检索路由字段核验记录","form_schema_record",["printed_legend","same_batch_slips","route_field","separate_approval_field"],["classify_sr_as_routing_code","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_246_MICROFILM_FRAME_LOG","timeline_scope":"current","display_name":"HV-19相关卷监督阅片帧号日志","purpose":"证明SB-83-6库号来自获准卷片末帧","required_permission":"record_supervised_microfilm_frames","scope_assertion":"末帧定位不授予附表内容访问"}]
    second=milestone(event,248)
    second.update({"timeline_start":"1991-10-26","timeline_end":"1991-10-26","scene":"海港缩微资料库出纳窗与基金往来银行柜台","chapter_title":"原路退回与附表继续密封","chapter_goal":"处理承包商已完成服务的抗辩，完成十八美元账面退回并建立附表B重新申请边界。","participants":["麦珂","苏菲亚","基金独立会计","市缩微资料监督员","资料库出纳","收费承包商经理","银行柜员"],"opening_conflict":"承包商经理称检索人员已经定位附表，服务成本已发生，即使批准栏空白也不得退款。","info_gap_use":"麦珂不把前世损失当成退款依据，只要求区分承包商内部定位成本、谁委托服务和谁的账户被扣。","opponent_reaction":"经理提出让奥瑞恩补签申请但保留基金付款，把附表直接交给双方共享。","action_sequence":["独立会计拒绝倒填基金批准，出纳撤销基金预付款扣记并向实际外部申请方重开收费联。","银行柜员按原日结追踪号把十八美元贷回基金预付款，出具前后余额回单。","监督员确认SB-83-6封签未动，建立独立基金席位批准、限定帧范围和自付费用三项条件。","外部申请方可自费查公开范围；基金将在11月15日独立审查是否提出自己的限定申请。"],"visible_payoff":"十八美元真实回到账上，附表未因错误扣款交付；路由、批准、收费和释放不再互相替代。","ending":"11月15日申请草案附着一张后制封面，纸张批次与1983登记册不符，正文内容仍未核验。","must_include":["拒绝倒填基金批准","十八美元原路贷回","SB-83-6封签未动","独立基金席位限定范围重申"],"must_not_include":["没收承包商全部收入","公开附表内容","全国法规","观众证言"],"detailed_synopsis":"同日晚间，承包商以定位成本已发生拒绝退款。基金独立会计区分服务成本与错误付款人，拒绝让奥瑞恩补签却保留基金垫付。出纳撤销扣记，银行按原追踪号把十八美元贷回基金预付款。SB-83-6封签未动；未来须由基金独立席位按限定帧范围、自付费用重新申请，外部申请人仍可按自身权限自费申请。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"无授权扣记从收费笼进入银行原路退回"}]
    second["artifact_creates"]=[artifact("ART_248_PREPAYMENT_REIMBURSEMENT",248,"初声基金十八美元预付款原路退回回单","bank_record",["original_trace","reversal_entry","restored_balance","external_rebilling"],["restore_fund_archive_prepayment","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_248_SCHEDULE_B_ACCESS_HOLD",248,"SB-83-6密封状态与限定申请规则","access_rule",["seal_intact","independent_fund_approval","scoped_frames","requester_pays"],["require_scoped_schedule_b_request","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_247_SB83_6_FEE_CHAIN","timeline_scope":"current","display_name":"SB-83-6十八美元调取费过账链","purpose":"沿原追踪号完成错误付款人更正","required_permission":"audit_schedule_b_retrieval_fee","scope_assertion":"退款不免除实际申请方服务成本"},{"artifact_id":"ART_247_SR_ROUTE_CODE","timeline_scope":"current","display_name":"S.R.服务检索路由字段核验记录","purpose":"证明路由字段不能替代基金批准","required_permission":"classify_sr_as_routing_code","scope_assertion":"不把S.R.指认为具体个人"}]


def repair_ec125(event: dict[str, Any]) -> None:
    event.update({
        "name":"SB-83-6限定阅片与服务副本接收方","timeline_years":"1991","main_opponent":"奥瑞恩法务代理人与影印服务接收方权利扩张主张","opposition_type":"institutional","event_type":"contract_rights","solution_type":"legal_evidence",
        "prev_life_tragedy":"前世基金把后来加订的封面当作整份附表伪造，又把境外服务副本接收方直接当成票据所有人，错误结论使真正的原件保管与复制链无人继续追查。",
        "info_gap_from_prev_life":"麦珂记得1983年影印服务接收方与后来纪录片财务有关，但今生只能先核定封面年代、正文帧、接收方权限和原件保管者，不能凭注册地认定洗钱或奥瑞恩控制。",
        "preemptive_avoidance":"基金独立席位把全部调阅改成明确帧范围，麦珂回避表决；阅片时将1991后制封面与1983正文分套记录，并逐帧读取授予与排除项。",
        "bait_and_evidence":"奥瑞恩代理人一面以封面纸张较晚攻击整份附表，一面又以服务副本接收方代码主张票据资产；监督记录显示封面后制不改变正文帧，接收方只获限定档案服务副本。",
        "villain_loss":"代理人失去用晚制封面排除全部正文、或用服务副本接收方主张票据原件与收益权的两条本次路径；资料库不得再按全表范围释放附表副本。",
        "protagonist_gain":"基金取得SB-83-6可复现帧号、服务副本接收方和原件保管栏的有限事实，并建立后续副本释放须独立批准的规则。",
        "relationship_change":"麦珂接受在基金申请表决中回避，只作为前世风险提示人和阅片观察者；艾琳与苏菲亚拒绝把服务公司注册地写成奥瑞恩控制定论。",
        "cluster_outcome":"晚制封面与1983正文被分离；附表只证明海湾文档服务公司接收限定服务副本，票据原件、债权和收益仍留在所列保管链，实际控制关系未定。",
        "next_event_hook":"SB-83-6服务费发票引用SF-27纪录片制作账户；11月18日收到的发票副本使用较晚纸张，但须从采购订单、印刷批次与原始存根核验，而非仅做墨水猜测。",
        "resolution_signature":{"attack_domain":"late_cover_and_service_copy_recipient_laundered_into_total_forgery_or_note_ownership","counter_method":"independent_scoped_vote_and_frame_by_frame_schedule_review","resolver":"初声基金独立席位与市缩微资料监督员","publicity":"sealed_fund_review","hero_gain_type":"limited_recipient_and_custody_chain_facts"},
        "continuity_writes":["承接EC124的11月15日独立申请、后制封面与SB-83-6密封状态。","不宣称离岸即洗钱，不移交所谓离线系统，不让维克多承认彻底失败。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：团队把晚制封面当整份附表伪造，又把服务副本接收方当票据所有人；本事件独有信息差：麦珂只记得1983影印服务与后来纪录片财务有关；今生提前动作：基金独立席位限定帧范围，麦珂回避表决；第249章可见小赢：后制封面与1983正文分套且限定申请获准；第250章新交锋：代理人以服务接收方主张资产，正文排除项确认只获服务副本；阻力方现实损失：两种越级主张失效且不得全表释放；主角现实收益：取得帧号、接收方与原件保管链有限事实；结算边界：不认定洗钱、奥瑞恩控制或基金绝对安全。"
    event["main_characters"]=["麦珂","苏菲亚","艾琳","基金独立会计","市缩微资料监督员"]
    event["state_transitions"]=[
        {"domain":"rights","entity_id":"RIGHT_SB83_6_FUND_REVIEW","state_key":"viewing_scope","from":"all_frames_requested_with_late_cover","to":"approved_specific_frames_with_cover_separated","irreversible":False,"evidence":"ART_249_SB83_6_SCOPED_APPROVAL","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"rights","entity_id":"RIGHT_1983_SCHEDULE_B_COPY_RECIPIENT","state_key":"recipient_scope","from":"claimed_note_and_revenue_ownership","to":"limited_archive_service_copy_recipient_only","irreversible":False,"evidence":"ART_250_REPRODUCTION_RECIPIENT_SCOPE","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,249)
    first.update({"timeline_start":"1991-11-15","timeline_end":"1991-11-15","scene":"初声基金独立档案申请席","chapter_title":"划掉全部与后制封面分套","chapter_goal":"由独立席位审查SB-83-6限定申请、回避关系、封面纸张和必要帧范围，决定是否准许监督阅片。","participants":["麦珂","苏菲亚","艾琳","基金独立会计","基金独立申请主持人","基金记录代表","奥瑞恩观察员"],"opening_conflict":"申请草案仍要求调阅全部附表，奥瑞恩观察员又以封面纸张较晚主张整盒内容必然伪造。","info_gap_use":"麦珂只提示前世服务接收方与纪录片财务可能有关；因自身利益与前世判断，他回避投票和范围批准。","opponent_reaction":"观察员要求二选一：要么把晚制封面当真实原件，要么整份附表都不得查看。","action_sequence":["记录代表核对封面纸张批次、装订孔与1983格位卡，确认封面在1991年后加订但盒内卷片封签连续。","独立主持人把封面独立套封，禁止用封面年代推断正文帧年代或真伪。","基金独立会计把全部改为列明标题、定义、接收方、原件保管、排除项与费用引用的具体帧段。","麦珂在回避栏签名，独立席位表决通过自付费用、监督阅片且不复制无关票据的限定申请。"],"visible_payoff":"晚制封面没有污染正文判断，基金以独立表决取得只覆盖必要帧的合法阅片入口。","ending":"奥瑞恩代理人通知阅片室，将以附表中的境外服务接收方名称主张票据资产已经转让。","must_include":["麦珂回避表决","后制封面与正文分套","全部改为具体帧段","独立席位限定申请获准"],"must_not_include":["纸张较晚即整份伪造","离线存档系统","离岸即洗钱","基金控制权绝对安全"],"detailed_synopsis":"1991年11月15日，基金独立席位审查SB-83-6申请。封面纸张与装订孔显示其在1991年后制，但盒内卷片封签连续；记录代表将封面独立套封，不以封面年代推断正文。申请从全部改为标题、定义、接收方、原件保管、排除项和费用引用等具体帧段。麦珂回避表决，独立席位批准自付费用、监督阅片和不复制无关票据。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"EC124等待期届满后独立席位审查限定申请"}]
    first["artifact_creates"]=[artifact("ART_249_SB83_6_SCOPED_APPROVAL",249,"SB-83-6独立席位限定阅片批准","access_approval",["recusal","specific_frames","fund_pays_approved_fee","supervised_viewing","no_unrelated_copies"],["approve_scoped_schedule_b_viewing","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_249_LATE_COVER_SEPARATION",249,"SB-83-6后制封面与正文分套记录","evidence_scope_record",["cover_paper_batch","binding_holes","separate_sleeve","no_inference_to_body_frames"],["separate_late_cover_from_schedule_frames","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_248_SCHEDULE_B_ACCESS_HOLD","timeline_scope":"current","display_name":"SB-83-6密封状态与限定申请规则","purpose":"确定独立批准、自付费用和必要帧条件","required_permission":"require_scoped_schedule_b_request","scope_assertion":"不得以基金身份申请全部内容"}]
    second=milestone(event,250)
    second.update({"timeline_start":"1991-11-15","timeline_end":"1991-11-15","scene":"海港缩微资料库SB-83-6监督阅片室","chapter_title":"服务副本接收方不是票据所有人","chapter_goal":"按批准帧段读取SB-83-6接收方、原件保管与排除项，限定1983影印服务事实。","participants":["麦珂","苏菲亚","艾琳","基金独立会计","市缩微资料监督员","缩微设备操作员","奥瑞恩法务代理人"],"opening_conflict":"代理人以海湾文档服务公司列为副本接收方，主张票据原件、债权和收益权已一并转让。","info_gap_use":"麦珂不以注册地和前世记忆指认奥瑞恩控制，只要求操作员按独立批准帧段阅读定义、接收和排除栏。","opponent_reaction":"代理人试图只展示接收方名称，跳过其后的服务用途与原件保管栏。","action_sequence":["操作员核验SB卷号、封签、起止帧和本次批准页，封面不进入投影序列。","监督阅片记录海湾文档服务公司只接收一套编号服务副本，用于灾损恢复和授权查阅。","原件保管栏仍列基金受托银行保管室；排除项不转让票据、债权、收益或再许可权。","费用帧引用SF-27纪录片制作账户，团队只登记发票号与服务用途，留待下一簇核验来源。"],"visible_payoff":"附表正文的接收、保管和排除栏被可复现记录；服务公司名称不能继续替代票据资产转让证据。","ending":"SF-27发票副本使用较晚纸张且无采购订单号，原始存根位于市政采购档案。","must_include":["封面不进入投影序列","限定服务副本接收方","原件仍列基金受托银行","不转让债权收益与再许可"],"must_not_include":["维克多承认失败","基金洗钱定论","彻底阻断控制权","公开全部附表"],"detailed_synopsis":"同日，SB-83-6按限定帧段监督阅片，后制封面不进入投影序列。海湾文档服务公司只被列为一套编号服务副本接收方，用于灾损恢复和授权查阅；原件仍列基金受托银行保管室，排除项不转让票据、债权、收益或再许可权。费用帧引用SF-27纪录片制作账户，当前只登记发票号与用途，不认定奥瑞恩控制或洗钱。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"独立限定申请获准后进入SB-83-6监督阅片"}]
    second["artifact_creates"]=[artifact("ART_250_SCHEDULE_B_FRAME_LOG",250,"SB-83-6限定帧监督阅片日志","technical_record",["approved_frames","cover_excluded","copy_recipient","original_custodian","exclusion_terms","fee_reference"],["record_scoped_schedule_b_frames","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_250_REPRODUCTION_RECIPIENT_SCOPE",250,"1983服务副本接收方与票据权利范围决定","rights_record",["numbered_service_copy","disaster_recovery_use","original_bank_custody","no_note_or_revenue_transfer","no_relicense"],["limit_reproduction_recipient_rights","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_249_SB83_6_SCOPED_APPROVAL","timeline_scope":"current","display_name":"SB-83-6独立席位限定阅片批准","purpose":"限定本次可投影帧和费用来源","required_permission":"approve_scoped_schedule_b_viewing","scope_assertion":"不得投影或复制无关帧"},{"artifact_id":"ART_249_LATE_COVER_SEPARATION","timeline_scope":"current","display_name":"SB-83-6后制封面与正文分套记录","purpose":"保持后制封面与正文证据范围分离","required_permission":"separate_late_cover_from_schedule_frames","scope_assertion":"封面年代不证明正文真伪"}]


def repair_ec126(event: dict[str, Any]) -> None:
    event.update({
        "name":"SF-27发票副本与采购三联存根核验","timeline_years":"1991","main_opponent":"奥瑞恩法务代理人与市政采购研究副本混标","opposition_type":"institutional","event_type":"finance_business","solution_type":"financial_counter",
        "prev_life_tragedy":"前世团队把一张后来制作的研究封面当成1983原始发票，又把其中改写的服务说明视为影印费用铁证；真正采购订单与供应商三联存根无人核对。",
        "info_gap_from_prev_life":"麦珂记得SF-27与纪录片项目有关，但不知道发票是否支付附表影印；今生必须从采购交叉索引、订单号、三联存根和供应商账册确认服务范围。",
        "preemptive_avoidance":"团队不做墨水色谱猜测，也不在市政厅外公开定伪；先按SF-27-118查采购年度索引，再调取原始三联存根和供应商同日账页。",
        "bait_and_evidence":"奥瑞恩代理人以1991研究副本上的档案图像准备说明，主张1983发票支付了SB-83-6服务；采购索引与原存根却指向P07纪录片提案用五张研究剧照。",
        "villain_loss":"代理人失去用SF-27-118证明基金支付附表影印或服务公司取得票据权利的本次主张；较晚研究封面不得再冒充原始发票正文。",
        "protagonist_gain":"团队取得PO-83-441、原始三联与供应商账册的可复核链，保留合法纪录片剧照费用，同时隔离错误的档案影印归类。",
        "relationship_change":"麦珂接受黛安娜拒绝凭纸色与墨迹肉眼定年，只让采购管理员与供应商保管员说明各自记录。",
        "cluster_outcome":"1991纸张被确认是研究调阅封面而非1983发票原件；SF-27-118真实服务为P07纪录片提案五张研究剧照，不能支持SB-83-6影印费或票据权利转让。",
        "next_event_hook":"PO-83-441的P07交付清单引用一份演员影像使用同意表，签署范围被后来的家庭联合声明覆盖，引出下一簇同意范围与职业独立核验。",
        "resolution_signature":{"attack_domain":"later_research_cover_laundered_as_original_archive_service_invoice","counter_method":"purchase_cross_index_original_triplicate_and_vendor_ledger","resolver":"市政采购档案主管与供应商账册保管员","publicity":"closed_procurement_record","hero_gain_type":"documentary_stills_cost_preserved_archive_claim_rejected"},
        "continuity_writes":["承接EC125的SF-27-118、较晚纸张、空采购订单号和市政采购存根定位。","不使用墨水色谱、医师日志、媒体停刊、法官突袭或1977录音。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：后制研究封面被当成1983发票，服务范围由此错归；本事件独有信息差：麦珂只记得SF-27与纪录片项目有关；今生提前动作：核验采购年度索引、订单号、原始三联和供应商账册；第251章可见小赢：定位PO-83-441并确认较晚纸张只是1991调阅封面；第252章新交锋：代理人以封面服务说明主张档案影印，原存根与账册确认真实交付为P07五张研究剧照；阻力方现实损失：SF-27不能再证明SB-83-6费用或票据权利；主角现实收益：合法剧照费用保留、错误归类隔离；结算边界：不认定整张发票伪造或整个供应商失信。"
    event["main_characters"]=["麦珂","苏菲亚","黛安娜","市政采购档案主管"]
    event["state_transitions"]=[
        {"domain":"asset","entity_id":"ASSET_SF27_118_INVOICE_COPY","state_key":"document_identity","from":"later_copy_treated_as_1983_original_invoice","to":"1991_research_retrieval_cover_linked_to_po83_441","irreversible":False,"evidence":"ART_251_SF27_COPY_SOURCE_GAP","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"rights","entity_id":"RIGHT_SF27_118_SERVICE_SCOPE","state_key":"paid_service_scope","from":"claimed_schedule_b_archive_imaging","to":"p07_documentary_pitch_five_research_stills_only","irreversible":False,"evidence":"ART_252_SF27_SERVICE_SCOPE_DECISION","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,251)
    first.update({"timeline_start":"1991-11-18","timeline_end":"1991-11-18","scene":"市政采购档案馆年度索引台","chapter_title":"空订单号与PO-83-441","chapter_goal":"确定SF-27-118现存副本的制作层级，并从年度索引定位1983原订单与三联存根。","participants":["麦珂","苏菲亚","黛安娜","市政采购档案主管","采购索引员","奥瑞恩法务代理人"],"opening_conflict":"代理人要求直接采用1991纸张副本上的档案图像准备说明，称较晚纸张只是发票重印、不影响服务结论。","info_gap_use":"麦珂只提示SF-27可能属于纪录片项目；他不依据前世记忆填写缺失订单号。","opponent_reaction":"代理人提议由黛安娜凭纸色和墨迹判断哪一栏是后写，跳过采购索引。","action_sequence":["黛安娜拒绝材料鉴定，只描述副本有1991调阅批次、采购订单栏空白和存根定位号。","索引员按发票号、供应商前缀和1983日期三路查找，定位PO-83-441及P07项目分类。","档案主管核对1991调阅登记，确认较晚纸张是研究副本封面，服务说明由调阅人填写，不是原发票行。","主管发出原三联与供应商账册调阅单；当前只隔离封面说明，不定原发票真伪。"],"visible_payoff":"SF-27-118从无订单号研究副本追到PO-83-441，晚制封面与1983发票正文分层。","ending":"奥瑞恩代理人坚持PO索引里的P07可能只是档案影印项目简称，要求把研究封面继续作为服务说明。","must_include":["1991调阅批次封面","采购订单栏空白","三路索引定位PO-83-441","黛安娜拒绝凭纸色墨迹定年"],"must_not_include":["墨水色谱实验","公开媒体展示","三十七份医师日志","当场认定伪造"],"detailed_synopsis":"1991年11月18日，市政采购档案馆核验SF-27-118现存副本。黛安娜拒绝凭纸色墨迹定年，只记录其1991调阅批次、空订单栏和存根定位号。索引员按发票号、供应商前缀与日期三路查到PO-83-441、P07项目。调阅登记证明较晚纸张是研究封面，服务说明由1991调阅人填写；原三联与供应商账册另行调取。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"SF-27研究副本进入年度采购索引反查"}]
    first["artifact_creates"]=[artifact("ART_251_SF27_COPY_SOURCE_GAP",251,"SF-27-118研究副本与原发票层级差异单","document_scope_record",["1991_retrieval_cover","blank_po_field","stub_locator","no_material_age_opinion"],["separate_research_cover_from_original_invoice","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_251_PURCHASE_ORDER_CROSS_INDEX",251,"SF-27-118至PO-83-441三路采购索引联","procurement_index",["invoice_number","vendor_prefix","service_date","po83_441","p07_project"],["locate_original_purchase_records","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_250_SCHEDULE_B_FRAME_LOG","timeline_scope":"current","display_name":"SB-83-6限定帧监督阅片日志","purpose":"证明SF-27-118来自获准费用引用帧","required_permission":"record_scoped_schedule_b_frames","scope_assertion":"费用引用不证明服务范围"}]
    second=milestone(event,252)
    second.update({"timeline_start":"1991-11-20","timeline_end":"1991-11-20","scene":"市政采购档案馆三联存根核验室","chapter_title":"五张研究剧照与错误影印归类","chapter_goal":"以原始三联、采购订单、交付签收与供应商账册确定SF-27-118真实服务，不让后制封面扩张。","participants":["麦珂","苏菲亚","黛安娜","市政采购档案主管","供应商账册保管员","奥瑞恩法务代理人","项目交付记录员"],"opening_conflict":"代理人主张P07就是票据影印代号，1991封面上的档案图像准备应覆盖原始发票。","info_gap_use":"麦珂不以纪录片记忆解释P07，要求四份今生记录在编号、数量、金额和签收上互证。","opponent_reaction":"代理人试图只引用发票标题中的图像准备，忽略订单明细和交付数量。","action_sequence":["档案主管核对采购联、供应商联、付款联的页号、碳印与骑页编号，三联服务行一致。","PO-83-441明细为P07纪录片提案五张研究剧照，交付记录逐张列出底片号与接收人。","供应商账册同日记载五张放大与一套联系样，不含缩微附表或票据复制。","主管保留原剧照费用有效，签发服务范围决定并标记SB-83-6费用引用待查。"],"visible_payoff":"SF-27-118真实服务被锁定为P07研究剧照，合法费用保留，档案影印归类失去依据。","ending":"P07交付清单附有演员影像使用同意表，后来的家庭联合声明似乎扩大了原签署范围。","must_include":["原始三联页号碳印一致","PO-83-441五张研究剧照","供应商账册与交付记录互证","保留合法费用隔离错误归类"],"must_not_include":["法官要求墨水鉴定","1977录音列核心证据","供应商整体造假","奥瑞恩行政调查彻底失效"],"detailed_synopsis":"11月20日，三联存根核验室比对采购联、供应商联、付款联、PO-83-441、交付清单和供应商账册。三联碳印与服务行一致：P07纪录片提案五张研究剧照，交付记录有底片号与接收人；供应商账册无缩微附表或票据复制。主管保留合法剧照费用，隔离1991封面造成的档案影印误归，SB-83-6真实费用来源继续待查。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"PO-83-441索引命中后调取原始三联与供应商账册"}]
    second["artifact_creates"]=[artifact("ART_252_ORIGINAL_TRIPLICATE_COMPARISON",252,"SF-27-118原始三联与供应商账册比对","procurement_record",["purchase_copy","vendor_copy","payment_copy","carbon_alignment","delivery_list","vendor_ledger"],["verify_original_sf27_triplicate","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_252_SF27_SERVICE_SCOPE_DECISION",252,"SF-27-118纪录片剧照服务范围决定","accounting_record",["po83_441","p07_five_research_stills","valid_cost_preserved","schedule_b_cost_unproven"],["classify_sf27_documentary_stills_scope","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_251_SF27_COPY_SOURCE_GAP","timeline_scope":"current","display_name":"SF-27-118研究副本与原发票层级差异单","purpose":"防止1991封面说明覆盖1983发票正文","required_permission":"separate_research_cover_from_original_invoice","scope_assertion":"较晚封面不等于原发票伪造"},{"artifact_id":"ART_251_PURCHASE_ORDER_CROSS_INDEX","timeline_scope":"current","display_name":"SF-27-118至PO-83-441三路采购索引联","purpose":"定位原三联、P07项目和供应商账册","required_permission":"locate_original_purchase_records","scope_assertion":"索引命中仍须原记录核验"}]


def repair_ec127(event: dict[str, Any]) -> None:
    event.update({
        "name":"P07演员影像同意范围与未来使用更正","timeline_years":"1991","main_opponent":"P07制作档案的家庭联合声明扩权记录","opposition_type":"institutional","event_type":"contract_rights","solution_type":"legal_evidence",
        "prev_life_tragedy":"前世档案人员用一份后来形成的家庭联合声明覆盖瑟琳娜本人签署的演员影像同意表，使最初仅供纪录片提案研究的剧照被不断用于宣传；麦珂出于保护替她处理撤回，也再次夺走她的选择。",
        "info_gap_from_prev_life":"麦珂记得某次未授权宣传从P07剧照开始，却不知道原同意表究竟允许哪些载体；今生只能核对签署人、所附底片号、用途、份数、期限和修改权限。",
        "preemptive_avoidance":"团队不再仓促登记伴侣或签署万能信托，也不援引虚构法条；先将1983演员同意表与后来家庭声明分层，再由瑟琳娜本人决定尚未发行宣传物的处理。",
        "bait_and_evidence":"档案权利管理员以家庭联合声明中的所有家庭影像与未来传播主张无限使用；原表却只列P07提案册、五张研究剧照和一次内部展示，后来声明没有瑟琳娜签名，也没有修改演员同意的授权栏。",
        "villain_loss":"制作档案失去以家庭联合声明替代瑟琳娜逐次同意的路径；尚未发行的节庆宣传册撤下她的剧照，未来外部使用须直接向她提出具体申请。",
        "protagonist_gain":"原P07提案研究用途和已授权的档案保管继续有效，瑟琳娜重新掌握自己影像未来是否使用、用于何处及采用何种版本的决定权。",
        "relationship_change":"麦珂起初想签署一份由他统一撤回所有未来使用的保护声明；瑟琳娜拒绝由另一份总括文书替她决定，麦珂撤回提议并接受逐项由她本人选择。",
        "cluster_outcome":"1983原同意限定于P07提案册、五张研究剧照和一次内部展示；后来家庭声明不能扩张表演者授权。未发行宣传册完成替换，未来使用改为瑟琳娜逐次书面决定。",
        "next_event_hook":"宣传册撤换申请引用FR-12影像权登记台账；其中一张共用路由页把表演者同意与基金票据影印申请并列，下一簇须先确认字段类型与权利对象，不能据共页认定票据影印权已经转让。",
        "resolution_signature":{"attack_domain":"later_family_declaration_expands_original_performer_image_consent","counter_method":"document_layer_and_signer_scope_comparison_then_specific_pending_use_correction","resolver":"P07制作档案权利主管与瑟琳娜本人","publicity":"closed_archive_rights_review","hero_gain_type":"performer_specific_future_choice_restored"},
        "continuity_writes":["承接EC126的P07交付清单、五张研究剧照和演员影像使用同意表。","不重复民事伴侣登记或信托，不虚构法条，不宣称私人文书阻断合法冻结。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：后来家庭声明覆盖瑟琳娜本人有限演员同意，剧照被持续扩用；本事件独有信息差：麦珂只记得未授权宣传始于P07，今生须核签署人、底片号、用途和修改权；今生提前动作：分层比对原同意表与后来声明；第253章可见小赢：确认原范围及后来声明无权扩张；第254章新交锋：档案方欲发行含剧照宣传册，瑟琳娜选择撤图并建立逐次申请；阻力方现实损失：失去总括声明扩用路径；主角现实收益：保留合法研究用途并恢复本人未来选择；结算边界：不撤销既有合法P07材料、不禁止一切未来申请。"
    event["main_characters"]=["麦珂","瑟琳娜","苏菲亚","P07制作档案权利主管"]
    event["state_transitions"]=[
        {"domain":"rights","entity_id":"RIGHT_P07_PERFORMER_IMAGE_CONSENT","state_key":"usage_scope","from":"later_family_declaration_claimed_all_family_images_and_future_media","to":"original_p07_pitch_five_stills_one_internal_showing_only","irreversible":False,"evidence":"ART_253_P07_ORIGINAL_IMAGE_CONSENT_SCOPE","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"relationship","entity_id":"REL_4E24DD1EEE76__DBD820C705DB","state_key":"image_choice_authority","from":"mike_proposes_blanket_protective_withdrawal","to":"selena_direct_specific_use_choice","irreversible":False,"evidence":"ART_254_FUTURE_PERFORMER_CONSENT_RULE","effect_type":"relationship_change","source_entity_label":"RELATIONSHIP_MAGO_SELENA","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,253)
    first.update({"timeline_start":"1991-11-21","timeline_end":"1991-11-21","scene":"P07制作档案演员授权核验台","chapter_title":"五张剧照与一次内部展示","chapter_goal":"分层核对1983演员影像同意表与后来家庭联合声明，确定原签署范围及谁有权修改。","participants":["麦珂","瑟琳娜","苏菲亚","P07制作档案权利主管","原项目接收记录员"],"opening_conflict":"权利主管称后来家庭联合声明已把P07演员同意扩为所有家庭影像及未来传播，原表用途栏无需再读。","info_gap_use":"麦珂只提示前世第一次外部扩用与P07有关，不替瑟琳娜解释或撤回今生文件。","opponent_reaction":"权利主管主张家庭成员签过总括声明即可代表瑟琳娜修改早年的演员授权。","action_sequence":["苏菲亚按PO-83-441交付清单调出原同意表，核对签署页、五个底片号和骑页附件。","权利主管逐栏读出用途：P07提案册、五张研究剧照和一次内部展示；广播、广告、未来项目与再许可栏均未勾选。","团队把后来家庭联合声明单独套封，确认其形成日期较晚、没有瑟琳娜签名，也没有引用或修改原演员同意表的授权栏。","麦珂提出由自己签一份总括撤回以保护她；瑟琳娜拒绝新的代决文书，他收回并只要求暂停未明确授权的外部使用。"],"visible_payoff":"原同意表的对象、数量和用途被锁定；后来家庭声明不能再自动扩张瑟琳娜的演员影像授权。","ending":"权利主管承认一份尚未付印的节庆宣传册已选用其中一张剧照，要求次日决定是否更换。","must_include":["五个底片号逐项对应","P07提案册与一次内部展示","后来声明无瑟琳娜签名","麦珂撤回总括代决提议"],"must_not_include":["民事伴侣登记","双轨信托","海湾州民事伴侣法第14条","一纸声明永久禁止合法程序"],"detailed_synopsis":"1991年11月21日，P07制作档案按PO-83-441调出演员影像同意表。签署页和骑页附件逐一对应五个底片号，允许范围只有P07提案册、五张研究剧照和一次内部展示；广播、广告、未来项目与再许可均未勾选。后来家庭联合声明日期更晚，既无瑟琳娜签名，也无修改原表的授权栏。麦珂想以总括撤回保护她，被她拒绝后撤回提议，只暂停范围外使用。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"EC126交付清单所附演员同意表进入签署与用途核验"}]
    first["artifact_creates"]=[artifact("ART_253_P07_ORIGINAL_IMAGE_CONSENT_SCOPE",253,"P07演员影像原同意范围核验表","rights_record",["signer","five_negative_ids","pitch_book","research_stills","one_internal_showing","unchecked_external_uses"],["verify_original_performer_image_scope","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_253_FAMILY_DECLARATION_AUTHORITY_GAP",253,"家庭联合声明与演员同意修改权限差异单","document_scope_record",["later_creation_date","missing_selena_signature","no_original_consent_amendment_field"],["separate_family_declaration_from_performer_consent","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_252_ORIGINAL_TRIPLICATE_COMPARISON","timeline_scope":"current","display_name":"SF-27-118原始三联与供应商账册比对","purpose":"沿PO-83-441交付附件定位演员同意表与五个底片号","required_permission":"verify_original_sf27_triplicate","scope_assertion":"采购交付不自动授予外部影像使用"}]
    second=milestone(event,254)
    second.update({"timeline_start":"1991-11-22","timeline_end":"1991-11-22","scene":"P07制作档案封闭权利更正室与印刷校样台","chapter_title":"未付印校样与逐次选择权","chapter_goal":"处理尚未发行的节庆宣传册剧照，落实瑟琳娜本人对未来具体使用的决定并修正档案流程。","participants":["麦珂","瑟琳娜","苏菲亚","P07制作档案权利主管","节庆宣传册编辑","印刷联络员"],"opening_conflict":"宣传册编辑称校样已排版且家庭联合声明允许使用，临时撤图会损失一个版面并产生改版费。","info_gap_use":"麦珂记得前世这张图后来被反复复制，却不替瑟琳娜作永久禁止；他只要求在付印前保留真实选择。","opponent_reaction":"编辑提出本次默认放行、以后再逐项申请，试图把尚未发生的发行变成既成事实。","action_sequence":["权利主管依据前章核验表比对校样图号，确认所选照片属于五张研究剧照但节庆宣传册不在原用途内。","瑟琳娜查看裁切与说明文字后选择撤下本次照片，以P07场记板照片替代；她接受失去本期显著曝光，但改版费由未核授权即排版的制作账户承担。","印刷联络员回收旧校样、注销版次和出片编号，新校样由瑟琳娜核对不再含其演员剧照。","权利主管修改申请流程：档案可保管原有P07材料，任何新的外部载体须列明照片、版本、用途、期限并由瑟琳娜本人决定。"],"visible_payoff":"未发行宣传册在付印前完成实物换版；瑟琳娜取得可观察的逐次选择权，原P07合法研究与保管范围不被抹除。","ending":"撤换申请的路由附件出现FR-12台账号，该页还并列一项基金票据影印申请，但二者是否属于同一权利尚未核验。","must_include":["校样图号核对原同意范围","瑟琳娜本人选择撤图","旧校样回收注销并完成换版","未来外部使用逐项申请"],"must_not_include":["法院替私人同意表自动生效","永久禁止所有影像使用","已授权P07材料全部销毁","奥瑞恩资产被冻结"],"detailed_synopsis":"11月22日，封闭权利更正室核对尚未付印的节庆宣传册校样。所选照片虽属于五张P07研究剧照，节庆宣传却不在原用途内。瑟琳娜亲自决定撤图，以场记板照片换版，接受失去本期显著曝光；改版费由未核授权即排版的制作账户承担。旧校样和出片编号回收注销，新流程要求未来每种外部载体列明照片、版本、用途与期限，由她本人逐次决定；原P07档案保管和已授权研究用途继续有效。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"原同意范围核定后处理尚未发行的具体宣传校样"}]
    second["artifact_creates"]=[artifact("ART_254_PROSPECTUS_IMAGE_WITHDRAWAL",254,"P07节庆宣传册剧照撤换与校样注销单","production_record",["old_proof_number","withdrawn_still_id","replacement_slate_image","new_proof_number","revision_cost_allocated_to_production"],["replace_unreleased_prospectus_image","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_254_FUTURE_PERFORMER_CONSENT_RULE",254,"P07未来演员影像逐次申请规则","access_rule",["specific_image","specific_version","stated_medium","purpose","term","performer_direct_choice","archive_retention_preserved"],["require_direct_specific_performer_consent","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_253_P07_ORIGINAL_IMAGE_CONSENT_SCOPE","timeline_scope":"current","display_name":"P07演员影像原同意范围核验表","purpose":"判断节庆宣传册是否落在1983原授权用途内","required_permission":"verify_original_performer_image_scope","scope_assertion":"原研究剧照不等于所有未来宣传授权"},{"artifact_id":"ART_253_FAMILY_DECLARATION_AUTHORITY_GAP","timeline_scope":"current","display_name":"家庭联合声明与演员同意修改权限差异单","purpose":"禁止用无本人签名的总括声明替代本次选择","required_permission":"separate_family_declaration_from_performer_consent","scope_assertion":"不妨碍瑟琳娜本人作新的具体授权"}]


def repair_ec128(event: dict[str, Any]) -> None:
    event.update({
        "name":"FR-12共页登记与基金三张索引校对副本","timeline_years":"1991","main_opponent":"P07与基金档案共页登记造成的权利混同主张","opposition_type":"institutional","event_type":"contract_rights","solution_type":"legal_evidence",
        "prev_life_tragedy":"前世团队看到表演者影像申请与基金票据影印申请出现在同一FR-12路由页，便把共页登记误当成同一授权和影印权转让；真正的原申请、批准范围与交付对象无人核验。",
        "info_gap_from_prev_life":"麦珂只记得FR-12后来被用来主张奥瑞恩取得基金资料，却不知道它是权利代码、账户还是收件批次；今生必须从表头、行号、撕票和原申请定位其字段类型。",
        "preemptive_avoidance":"团队不向联邦机构申请冻结账户，也不让黛安娜撰写法律瑕疵报告；先分开同页两行申请，再到基金受托银行核对1983原申请、批准碳联、工单和交付回执。",
        "bait_and_evidence":"档案研究代理人以FR-12共页和影印字样主张家庭影像授权与基金票据权利一并转给外部服务商；路由簿与原记录证明FR-12只是第十二收件台，同页两行有不同申请号、申请人、标的和附件袋。",
        "villain_loss":"研究代理人失去用FR-12共页证明统一授权或票据影印权转让的路径；外部服务商不能把有限校对工单扩为历史数据控制权。",
        "protagonist_gain":"团队取得FND-RP-83-09原申请链，确认合法交付仅为三张遮蔽票面信息的索引校对工作副本，基金原件、债权、收益和继续复制决定未转移。",
        "relationship_change":"麦珂不再让黛安娜承担法律或档案鉴定；她只从服装制作记录角度确认P07-N21版本差异，FR-12和基金票据由各自保管人说明。",
        "cluster_outcome":"FR-12被确定为共用收件台号而非权利代码；1983工单只批准三张遮蔽票面副本用于索引校对，合法副本保留，票据原件与经济权利未转让。",
        "next_event_hook":"三张校对副本之一的索引栏引用圣保罗音乐厅SRH-28通风改造返还款，但缺少场馆接收日期；下一簇须从施工验收、通风运行和付款条件核验该返还款，不能再以暴雨和观众敲击证明建筑声学。",
        "resolution_signature":{"attack_domain":"shared_intake_page_laundered_into_unified_rights_transfer","counter_method":"row_level_application_separation_then_original_request_approval_work_order_delivery_comparison","resolver":"P07档案登记员与基金受托银行文书主管","publicity":"closed_records_review","hero_gain_type":"limited_redacted_index_copy_scope_confirmed"},
        "continuity_writes":["承接EC127撤换申请中的FR-12共页与基金票据影印行。","不使用FTC冻结、五日联邦庭审、胶片绝对优先、黛安娜法律鉴定或永久夺回所有数据。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：FR-12共页被误当统一授权和票据影印权转让；本事件独有信息差：麦珂只记得FR-12被用来主张资料控制，今生须先确定字段类型；今生提前动作：逐行分离申请并核原申请、批准、工单和交付；第255章可见小赢：确认FR-12为收件台且定位FND-RP-83-09；第256章新交锋：外部服务商扩张有限影印，原记录锁定三张遮蔽索引校对副本；阻力方现实损失：共页与工单不能再证明权利转让；主角现实收益：合法副本保留且票据权利边界明确；结算边界：不冻结账户、不否认实际复制、不认定整体非法。"
    event["main_characters"]=["麦珂","苏菲亚","瑟琳娜","P07制作档案登记员","基金受托银行文书主管"]
    event["state_transitions"]=[
        {"domain":"rights","entity_id":"RIGHT_FR12_SHARED_ROUTING_PAGE","state_key":"routing_inference","from":"shared_page_claimed_unified_rights_authorization","to":"separate_applications_at_common_intake_desk","irreversible":False,"evidence":"ART_255_FR12_SHARED_ROUTING_SEPARATION","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"rights","entity_id":"RIGHT_FND_RP_83_09_REPRODUCTION","state_key":"copy_scope","from":"claimed_historical_note_reproduction_rights_transfer","to":"three_redacted_index_reconciliation_work_copies_no_assignment","irreversible":False,"evidence":"ART_256_FUND_COPY_SCOPE_DECISION","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,255)
    first.update({"timeline_start":"1991-11-23","timeline_end":"1991-11-23","scene":"P07制作档案路由登记核对台","chapter_title":"同一页上的两个申请号","chapter_goal":"确认FR-12字段类型，将影像撤换与基金票据影印两行申请按申请人、标的和附件分离。","participants":["麦珂","苏菲亚","瑟琳娜","P07制作档案登记员","档案研究代理人","路由簿保管员"],"opening_conflict":"研究代理人以两行都盖FR-12为由，主张表演者影像和基金票据影印经过同一授权入口，属于可统一使用的资料权。","info_gap_use":"麦珂只说明前世FR-12曾被解释成权利转让码，不替档案员决定它的真实含义。","opponent_reaction":"代理人要求只复印路由页，不调两只原申请袋，称共用印章已经足够。","action_sequence":["登记员核对路由簿表头、台号图例、当日行号与撕票存根，确认FR-12为Film Records第十二收件台。","影像撤换行为P07-IMG-91-42，申请人瑟琳娜、标的FP-07校样；基金影印行为FND-RP-83-09，申请人为1983档案服务承包席。","两行分别引用R-421和R-422附件袋，页内没有合并授权、交叉签名或权利转让栏。","苏菲亚制作共页分离记录，并沿R-422封面上的保管回执定位基金受托银行原申请链。"],"visible_payoff":"FR-12从可疑权利代码还原为共用收件台；同页两项申请按行号、撕票和附件袋彻底分开。","ending":"R-422封面写有三张索引校对副本，但研究代理人主张校对只是委婉说法，实际转让了全部票据影印权。","must_include":["FR-12为第十二收件台","P07-IMG-91-42与FND-RP-83-09分行","R-421与R-422附件袋分开","共页登记不等于统一授权"],"must_not_include":["FR-12直接认定奥瑞恩公司","联邦账户冻结","黛安娜撰写法律报告","共页即票据权利转让"],"detailed_synopsis":"1991年11月23日，P07档案核对FR-12共页。表头与同日路由簿证明FR-12是Film Records第十二收件台；本次影像撤换P07-IMG-91-42与1983基金影印FND-RP-83-09分占两行，申请人、标的、撕票和R-421/R-422附件袋均不同。共页只表示同台收件，不产生统一授权。R-422保管回执将下一步指向基金受托银行原申请链。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"EC127撤换申请的FR-12附件进入逐行路由核验"}]
    first["artifact_creates"]=[artifact("ART_255_FR12_SHARED_ROUTING_SEPARATION",255,"FR-12共页两项申请分离记录","routing_record",["intake_desk_12","separate_row_numbers","p07_img_91_42","fnd_rp_83_09","separate_requesters","separate_subjects"],["separate_shared_routing_applications","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_255_FUND_REQUEST_SOURCE_LOCATOR",255,"FND-RP-83-09原申请保管定位联","custody_locator",["r422_envelope","custodian_receipt","trustee_bank_archive","no_content_access"],["locate_original_fund_reproduction_request","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_254_PROSPECTUS_IMAGE_WITHDRAWAL","timeline_scope":"current","display_name":"P07节庆宣传册剧照撤换与校样注销单","purpose":"确认P07-IMG-91-42当前申请的图号、申请人与附件袋","required_permission":"replace_unreleased_prospectus_image","scope_assertion":"当前撤换申请不授予基金票据访问"}]
    second=milestone(event,256)
    second.update({"timeline_start":"1991-11-25","timeline_end":"1991-11-25","scene":"初声基金受托银行文书服务核验室","chapter_title":"三张遮蔽票面与索引校对工单","chapter_goal":"核对FND-RP-83-09原申请、批准碳联、复制工单与交付回执，限定1983票据副本的实际范围。","participants":["麦珂","苏菲亚","基金独立会计","基金受托银行文书主管","1983复制工单保管员","档案研究代理人"],"opening_conflict":"研究代理人称R-422写有票据影印，说明承包席取得基金全部历史票据的持续复制与处分权。","info_gap_use":"麦珂不以纸质记录绝对优先或前世记忆决定结论，只要求申请、批准、执行和接收四个阶段互证。","opponent_reaction":"代理人只展示申请标题，试图跳过三张数量、遮蔽要求、一次性工单号与交付接收栏。","action_sequence":["文书主管核对FND-RP-83-09原申请与银行批准碳联，批准对象为三个指定票据编号的索引校对副本。","复制工单列明遮蔽姓名、地址、票面金额和签名，仅保留日期、系列号与场馆用途索引；数量为三张、一次执行。","交付回执由基金档案核对席签收，外部承包席只完成制作，不取得继续复制、处分、债权或收益。","主管保留三张合法工作副本，签发范围决定；其中一张用途索引的SRH-28返还款缺场馆接收日期，留待施工与付款核验。"],"visible_payoff":"FND-RP-83-09从全部历史影印权主张收窄为三张遮蔽索引校对工作副本，真实复制不被否认、经济权利不被扩张。","ending":"SRH-28行同时写有通风改造和声学返还款，却没有接收日期；下一步需核对圣保罗音乐厅是否完成对应改造。","must_include":["原申请与批准碳联互证","三个指定票据编号","姓名金额签名遮蔽","合法校对副本保留且不转让票据权利"],"must_not_include":["五日内联邦庭审","纸质证据绝对优先","奥瑞恩全部账户冻结","永久夺回所有历史数据"],"detailed_synopsis":"11月25日，基金受托银行核对FND-RP-83-09。原申请、批准碳联、一次性复制工单和交付回执共同证明：只制作三个指定票据编号的索引校对副本，姓名、地址、金额和签名均遮蔽，仅保留日期、系列号与场馆用途索引。副本由基金档案核对席接收，外部承包席没有继续复制、处分、债权或收益。三张合法工作副本保留，其中SRH-28通风改造返还款缺接收日期，转入下一簇核验。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"FR-12共页分离后沿R-422保管回执调取原申请链"}]
    second["artifact_creates"]=[artifact("ART_256_FND_RP_83_09_CHAIN",256,"FND-RP-83-09申请批准工单交付四段链","document_chain",["original_request","approval_carbon","one_time_work_order","delivery_receipt","three_ticket_ids","redaction_fields"],["verify_fund_index_reconciliation_copies","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_256_FUND_COPY_SCOPE_DECISION",256,"基金三张票据索引校对副本范围决定","rights_record",["three_redacted_work_copies","fund_archive_recipient","valid_copying_preserved","no_continuing_copy_right","no_note_debt_or_revenue_transfer"],["limit_fund_ticket_copy_scope","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_255_FR12_SHARED_ROUTING_SEPARATION","timeline_scope":"current","display_name":"FR-12共页两项申请分离记录","purpose":"排除以共页登记替代FND-RP-83-09原申请范围","required_permission":"separate_shared_routing_applications","scope_assertion":"FR-12只定位收件台不证明权利"},{"artifact_id":"ART_255_FUND_REQUEST_SOURCE_LOCATOR","timeline_scope":"current","display_name":"FND-RP-83-09原申请保管定位联","purpose":"沿R-422回执合法调取银行原申请链","required_permission":"locate_original_fund_reproduction_request","scope_assertion":"定位联不直接授权查看其他基金票据"}]


def repair_ec129(event: dict[str, Any]) -> None:
    event.update({
        "name":"SRH-28通风改造返还款与历史接收边界","timeline_years":"1991","main_opponent":"圣保罗音乐厅旧改造记录的付款即验收主张","opposition_type":"institutional","event_type":"finance_business","solution_type":"financial_counter",
        "prev_life_tragedy":"前世团队把W-52索引副本上的SRH-28返还款当成场馆已经完成通风和声学验收，演出异常后又把所有付款写成虚假；设备交付、旧件返还、调试和最终接收从未拆开。",
        "info_gap_from_prev_life":"麦珂记得圣保罗音乐厅回风系统曾在演出前出问题，却不知道1983改造究竟交付到哪一步；今生只能从采购单、到货簿、旧件退回贷项、调试单、序列号和维护记录重建。",
        "preemptive_avoidance":"团队不在暴雨演出中用观众敲击验证建筑，也不召开新闻发布会；先核W-52款项性质，再做当前停机检查，并明确当前状态不能倒填1983最终验收。",
        "bait_and_evidence":"旧财务摘要把SRH-28返还款写成工程完成证明；原采购包显示该笔只是两只旧风阀退回后的设备贷项，到货与后续维护能支持部件安装，但缺场馆最终性能接收。",
        "villain_loss":"档案研究代理人失去用W-52付款证明1983场馆完成声学验收的路径，也不能把接收栏空白扩大为整项改造虚假。",
        "protagonist_gain":"团队保留真实设备贷项和部件交付，取得现存序列号与后续维护链；当前排练仅按新的停机检视结果决定，历史最终性能验收继续标为未证明。",
        "relationship_change":"麦珂一度想以空接收栏追回全部工程款；瑟琳娜要求把真实旧件贷项与缺失的性能接收分开，他撤回全额追缴并接受有限结论。",
        "cluster_outcome":"W-52被确定为两只旧风阀返还贷项，不是最终验收款；现存部件与1983后续维护记录相符，但历史最终声学性能接收无来源。当前机械卡滞经具名维修与复检后只支持本次低档排练。",
        "next_event_hook":"1983维护簿PL-83-28的纸页与1986缩微服务副本在一条更正注记上不同；下一簇须核复制批次、勘误单和原页保管，不能预设纸张或胶片天然优先。",
        "resolution_signature":{"attack_domain":"equipment_return_credit_laundered_into_final_venue_acceptance","counter_method":"payment_classification_delivery_serial_maintenance_chain_and_current_limited_inspection","resolver":"场馆设施工程师与基金独立会计","publicity":"closed_facility_review","hero_gain_type":"current_limited_rehearsal_condition_and_historical_scope_boundary"},
        "continuity_writes":["承接EC128的W-52、SRH-28通风改造返还款与空场馆接收日期。","不重复暴雨、万人敲击、媒体实时数据、墨水定年、全国法规或作品法律地位。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：W-52返还款被误当场馆最终验收，事后又被整体写成虚假；本事件独有信息差：麦珂只记得回风系统曾出问题，不知1983完成范围；今生提前动作：拆分采购、到货、旧件贷项、调试、序列号和维护；第257章可见小赢：确认返还款性质与两只部件到货，隔离空最终接收；第258章新交锋：当前卡滞被夸张成旧工程全假，序列与维护链支持安装但不补造最终验收；阻力方现实损失：付款即验收和空栏即全假两种越级失效；主角现实收益：保留真实贷项并取得本次低档排练条件；结算边界：不追缴全部工程款、不认证历史声学性能。"
    event["main_characters"]=["麦珂","瑟琳娜","苏菲亚","基金独立会计","圣保罗音乐厅设施工程师"]
    event["state_transitions"]=[
        {"domain":"asset","entity_id":"ASSET_SRH28_W52_CREDIT","state_key":"payment_classification","from":"claimed_final_ventilation_and_acoustic_acceptance_payment","to":"two_returned_dampers_equipment_credit_with_blank_final_acceptance","irreversible":False,"evidence":"ART_257_SRH28_PAYMENT_DELIVERY_SPLIT","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"asset","entity_id":"ASSET_SRH28_VENTILATION_INSTALLATION","state_key":"historical_completion_scope","from":"either_fully_accepted_or_wholly_fake","to":"parts_and_post_install_maintenance_supported_final_acoustic_acceptance_unproven","irreversible":False,"evidence":"ART_258_SRH28_HISTORICAL_SCOPE_DECISION","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,257)
    first.update({"timeline_start":"1991-11-28","timeline_end":"1991-11-28","scene":"圣保罗音乐厅设施档案室与设备收货台","chapter_title":"两只旧风阀的返还贷项","chapter_goal":"按采购、到货、旧件退回与付款条件确定W-52返还款性质，分离设备交付和最终接收。","participants":["麦珂","瑟琳娜","苏菲亚","基金独立会计","圣保罗音乐厅设施档案员","原设备供应商账务代表","档案研究代理人"],"opening_conflict":"研究代理人称W-52已有付款日期，足以证明SRH-28改造和场馆声学在1983年完成最终验收。","info_gap_use":"麦珂只提醒前世回风系统曾在演出前出问题，不以记忆断定当年设备未装或工程欺诈。","opponent_reaction":"代理人要求用财务摘要替代缺失的场馆接收日期，并把返还款解释成总工程尾款。","action_sequence":["设施档案员核对SRH-28采购单，拆出新风阀供货、安装调试、旧件返还贷项和最终接收四栏。","到货簿与序列卡确认两只新风阀进入场馆；旧件转运联和供应商贷项通知确认W-52是旧件返还抵扣。","付款登记只把贷项冲回设备行，不勾选调试与最终性能接收；场馆接收日期仍为空。","基金会计保留贷项并拒绝用其证明最终验收，也拒绝因空栏追回全部采购款。"],"visible_payoff":"W-52从总工程验收款还原为两只旧风阀返还贷项；真实到货与未证明的最终接收各归其位。","ending":"设备序列卡指向1983年后的维护簿PL-83-28，但当前机房报告其中一只执行器在低档切换时卡滞。","must_include":["SRH-28采购四栏分开","两只新风阀到货序列","W-52为旧件返还贷项","最终性能接收日期仍空"],"must_not_include":["暴雨演出","三千观众敲击","付款即声学验收","空接收栏即整项欺诈"],"detailed_synopsis":"1991年11月28日，圣保罗音乐厅设施档案室核对SRH-28。采购单把新风阀供货、安装调试、旧件返还贷项和最终接收分为四栏；到货簿与序列卡证明两只新部件入场，旧件转运联和供应商通知证明W-52只是旧风阀返还抵扣。付款登记未勾选调试与最终性能接收，接收日期仍空。团队保留真实贷项，不用付款证明最终验收，也不因空栏追回全部采购款。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"W-52用途索引转入SRH-28采购与场馆收货核验"}]
    first["artifact_creates"]=[artifact("ART_257_SRH28_PAYMENT_DELIVERY_SPLIT",257,"SRH-28供货调试返还贷项与接收分栏表","accounting_record",["new_damper_supply","installation_commissioning","old_unit_return_credit","final_acceptance","blank_acceptance_date"],["separate_srh28_payment_delivery_acceptance","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_257_SRH28_SERIAL_DELIVERY_CHAIN",257,"SRH-28两只风阀序列号到货与旧件退回链","asset_record",["two_new_serials","venue_delivery_log","old_units_returned","vendor_credit_notice"],["verify_srh28_parts_delivery_and_return_credit","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_256_FND_RP_83_09_CHAIN","timeline_scope":"current","display_name":"FND-RP-83-09申请批准工单交付四段链","purpose":"确认W-52只保留付款日期、系列号和SRH-28用途索引","required_permission":"verify_fund_index_reconciliation_copies","scope_assertion":"遮蔽副本付款索引不证明施工验收"}]
    second=milestone(event,258)
    second.update({"timeline_start":"1991-11-28","timeline_end":"1991-11-28","scene":"圣保罗音乐厅回风机房与设施维护记录台","chapter_title":"现存序列与不能倒填的最终验收","chapter_goal":"结合现存设备、1983后续维护记录和当前有限检视，确认安装范围并保持历史最终性能接收边界。","participants":["麦珂","瑟琳娜","苏菲亚","圣保罗音乐厅设施工程师","原设备供应商维修技师","基金独立会计","档案研究代理人"],"opening_conflict":"代理人看到当前执行器卡滞，反向主张1983两只风阀从未安装，所有供货、贷项和维护记录都是虚假。","info_gap_use":"麦珂没有把当前故障倒推八年前；他要求序列号、维护日期、零件更换与现状分别留痕。","opponent_reaction":"代理人要求维修后补签1983最终接收，或把整项改造认定未发生。","action_sequence":["设施工程师停机挂牌，读取两只现存风阀序列，与到货链和PL-83-28维护簿逐项核对。","维护簿记录1983安装后的皮带张力、执行器润滑和一次连杆更换，支持部件持续在场但不等于最终声学验收。","维修技师处理当前B阀连杆卡滞，工程师在空场低档完成三次开闭与风量复核，只决定本次低档排练。","团队拒绝倒填1983接收，签发历史范围决定；PL-83-28纸页与1986缩微副本的更正差异转入下一簇。"],"visible_payoff":"当前卡滞得到具名维修和有限复检；两只部件安装与维护链保留，1983最终声学性能仍明确未证明。","ending":"PL-83-28原纸把更正写在页边，1986缩微副本却把该行并入正文；复制批次和勘误来源需要独立核验。","must_include":["现存两只序列号匹配","PL-83-28后续维护链","B阀连杆维修与三次低档复核","当前复检不倒填1983最终验收"],"must_not_include":["观众同步动作","媒体发布会","建立全国标准","永久认定场馆绝对安全"],"detailed_synopsis":"同日，回风机房停机挂牌后核对现存两只风阀序列号，与到货链和PL-83-28维护簿相符。1983后的润滑、皮带张力与连杆更换支持部件持续在场，但不补足最终声学性能接收。维修技师处理当前B阀连杆卡滞，设施工程师在空场低档完成三次开闭与风量复核，只放行本次低档排练。团队拒绝倒填1983接收，并发现原纸页边更正与1986缩微副本位置不同。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"SRH-28到货序列与空最终接收进入现存设备和后续维护核验"}]
    second["artifact_creates"]=[artifact("ART_258_SRH28_CURRENT_LOW_MODE_CHECK",258,"SRH-28当前低档停机维修与三次复核记录","technical_record",["lockout_tagout","serial_match","linkage_repair","three_low_mode_cycles","current_rehearsal_only"],["approve_current_low_mode_rehearsal_only","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_258_SRH28_HISTORICAL_SCOPE_DECISION",258,"SRH-28部件安装维护与历史最终接收范围决定","evidence_scope_record",["parts_delivery_supported","serials_present","post_install_maintenance","final_1983_acoustic_acceptance_unproven","no_retroactive_signature"],["preserve_srh28_historical_scope_boundary","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_257_SRH28_PAYMENT_DELIVERY_SPLIT","timeline_scope":"current","display_name":"SRH-28供货调试返还贷项与接收分栏表","purpose":"防止当前维修或历史维护倒填最终接收栏","required_permission":"separate_srh28_payment_delivery_acceptance","scope_assertion":"付款分类与当前检视不能代替1983最终验收"},{"artifact_id":"ART_257_SRH28_SERIAL_DELIVERY_CHAIN","timeline_scope":"current","display_name":"SRH-28两只风阀序列号到货与旧件退回链","purpose":"将现存设备序列与1983到货记录逐项核对","required_permission":"verify_srh28_parts_delivery_and_return_credit","scope_assertion":"序列匹配支持部件在场不认证历史声学性能"}]


def repair_ec130(event: dict[str, Any]) -> None:
    event.update({
        "name":"PL-83-28页边更正与1986缩微摘要来源核验","timeline_years":"1991","main_opponent":"原维护页与缩微服务摘要的层级混同","opposition_type":"institutional","event_type":"legal_procedure","solution_type":"legal_evidence",
        "prev_life_tragedy":"前世团队把1986缩微卷里的打字维护摘要称作1983原页影像，又在发现原纸页边更正后反向宣布整卷伪造；实际更正授权与复制批次无人核验。",
        "info_gap_from_prev_life":"麦珂记得PL-83-28曾被用来夸大执行器更换，却不知道页边更正何时、由谁、依据什么形成，也不知道缩微卷拍摄的是原页还是转换摘要。",
        "preemptive_avoidance":"团队不把纸张或胶片设为绝对证据，不做墨水定年或法庭表演；先核页边更正、勘误登记和零件领用，再重建1986缩微服务批次的输入文件与拍摄目标。",
        "bait_and_evidence":"档案研究代理人选择缩微摘要中并入正文的更正，主张1983原记录本来就写连杆销套；原页与勘误链证明原正文曾误写执行器总成，页边更正有效，而1986卷片拍的是应用更正后的打字摘要。",
        "villain_loss":"代理人失去把1986摘要冒充1983原页影像、或以载体差异宣称一方整体伪造的路径；摘要必须随批次说明引用。",
        "protagonist_gain":"团队确认历史维修对象是B阀连杆销套，并取得原页、勘误、零件领用、摘要制作与缩微拍摄的可复核层级链。",
        "relationship_change":"麦珂起初想要求今后只信原纸，苏菲亚指出原纸也可能含待更正错误；他撤回介质优先要求，改为每种表示都说明来源与转换方法。",
        "cluster_outcome":"PL-83-28原正文误写执行器总成，1983具名页边更正和零件领用链将其改为连杆销套；1986缩微卷保存的是应用更正后的打字摘要，不是原页影像。两者均保留并按层级使用。",
        "next_event_hook":"比对过程中发现基金档案仍沿用一份只写原件优先的MV-4验证草案；在1993外部审计前需改成同时记录来源、复制或转换方法、核验人和用途范围的媒介中立清单。",
        "resolution_signature":{"attack_domain":"typed_microfilm_service_abstract_laundered_into_original_page_image_or_whole_reel_forgery","counter_method":"correction_authority_chain_and_1986_conversion_batch_input_target_reconstruction","resolver":"场馆设施档案主管与市缩微服务监督员","publicity":"closed_conversion_audit","hero_gain_type":"layered_original_correction_and_service_abstract_provenance"},
        "continuity_writes":["承接EC129的PL-83-28原纸页边更正与1986缩微副本位置差异。","不使用1977录音、医师日志、湿布冲庭、墨水报告、资产转移暗示或胶片天然无篡改。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：1986打字维护摘要被当成1983原页影像，原纸出现更正后又被写成整卷伪造；本事件独有信息差：麦珂只记得维修项目被夸大，不知更正与复制层级；今生提前动作：核页边更正、勘误登记、零件领用及1986批次输入；第259章可见小赢：确认具名更正有效且维修对象为连杆销套；第260章新交锋：代理人坚持卷片就是原页，批次清单证明拍摄对象为应用更正后的打字摘要；阻力方现实损失：失去冒充原页或整体定伪路径；主角现实收益：取得两层表示的完整来源链；结算边界：两种载体均保留、不设绝对优先。"
    event["main_characters"]=["麦珂","苏菲亚","瑟琳娜","圣保罗音乐厅设施档案主管","市缩微服务监督员"]
    event["state_transitions"]=[
        {"domain":"asset","entity_id":"ASSET_PL83_28_MAINTENANCE_PAGE","state_key":"corrected_maintenance_item","from":"body_text_actuator_assembly_vs_margin_linkage_bushing_unclear","to":"authorized_1983_correction_linkage_bushing_supported_by_parts_issue","irreversible":False,"evidence":"ART_259_PL83_28_MARGIN_CORRECTION_CHAIN","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"asset","entity_id":"ASSET_PL83_28_1986_MICROFILM_COPY","state_key":"representation_type","from":"claimed_photographic_copy_of_1983_original_page","to":"microfilmed_1986_typed_service_abstract_with_correction_applied","irreversible":False,"evidence":"ART_260_PL83_28_REPRESENTATION_SCOPE","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,259)
    first.update({"timeline_start":"1991-11-29","timeline_end":"1991-11-29","scene":"圣保罗音乐厅设施档案原始维护簿核验台","chapter_title":"页边那句不是原正文","chapter_goal":"核对PL-83-28原页正文、页边更正、勘误登记与零件领用，确认真实维修对象及更正权限。","participants":["麦珂","苏菲亚","瑟琳娜","圣保罗音乐厅设施档案主管","1983设施班记录员","档案研究代理人"],"opening_conflict":"代理人以页边更正与正文笔迹位置不同为由，主张原纸被1991团队改写；同时又引用1986缩微摘要中的更正文字。","info_gap_use":"麦珂只提示前世有人把维修对象说成整个执行器，不根据记忆决定哪一行真实。","opponent_reaction":"代理人要求只比较字形与纸色，不调勘误簿和零件领用卡。","action_sequence":["档案主管记录原页装订、页码、正文和页边位置，不对墨水或纸张定年。","勘误簿C-83-19引用PL-83-28页码，由原记录员和设施主管签名，注明误写执行器总成、应为B阀连杆销套。","零件领用卡和退件袋只出现销套件号，没有整套执行器出库或退回，独立支持更正内容。","主管保留原错误正文与具名页边更正，制作更正授权链；麦珂撤回只信原纸的要求。"],"visible_payoff":"页边更正从可疑后加字变成有勘误号、具名签署和零件链支持的1983更正；维修对象锁定为连杆销套。","ending":"1986缩微卷把更正后的说法打进正文，代理人据此声称卷片就是原页的无差别摄影副本。","must_include":["PL-83-28原错误正文保留","C-83-19具名勘误","零件领用只有连杆销套","不以墨水纸色判断更正年份"],"must_not_include":["1977录音波形","黛安娜演示胶片","墨水成分鉴定","原纸天然绝对真实"],"detailed_synopsis":"1991年11月29日，圣保罗音乐厅核PL-83-28原页。正文曾写更换B阀执行器总成，页边改为连杆销套；档案主管不凭墨水纸色定年，而由C-83-19勘误簿的原记录员与主管签名、零件领用卡和退件袋确认1983更正有效。原错误正文不涂除，页边更正随授权链保留。麦珂撤回只信原纸的要求，下一步核1986缩微批次为何把更正并入正文。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"EC129发现的原纸与缩微文字位置差异进入原页更正权限核验"}]
    first["artifact_creates"]=[artifact("ART_259_PL83_28_MARGIN_CORRECTION_CHAIN",259,"PL-83-28页边更正与C-83-19勘误授权链","correction_record",["original_error_preserved","margin_correction","c83_19","original_recorder_signature","facility_supervisor_signature","linkage_bushing_parts_issue"],["verify_pl83_28_authorized_correction","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_259_PL83_28_SOURCE_PAGE_RECORD",259,"PL-83-28原页正文页边与装订位置记录","source_record",["bound_page","body_text_position","margin_note_position","no_material_dating"],["record_pl83_28_source_page_layout","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_258_SRH28_HISTORICAL_SCOPE_DECISION","timeline_scope":"current","display_name":"SRH-28部件安装维护与历史最终接收范围决定","purpose":"限定本次只核维护项目更正，不补足历史最终接收","required_permission":"preserve_srh28_historical_scope_boundary","scope_assertion":"维修项目更正不等于最终性能验收"}]
    second=milestone(event,260)
    second.update({"timeline_start":"1991-11-30","timeline_end":"1991-11-30","scene":"市缩微资料服务中心1986批次重建台","chapter_title":"卷片拍到的是打字摘要","chapter_goal":"重建1986缩微批次的输入件、转换说明、拍摄目标和帧日志，确定卷片表示层级。","participants":["麦珂","苏菲亚","瑟琳娜","圣保罗音乐厅设施档案主管","市缩微服务监督员","1986批次打字员","档案研究代理人"],"opening_conflict":"代理人坚持缩微帧就是PL-83-28原纸的直接摄影，因更正位于正文，原纸页边注必为后来伪造。","info_gap_use":"麦珂不因卷片稳定或原纸可触摸而选择一方，只要求先找1986批次输入清单和拍摄靶标。","opponent_reaction":"代理人只要求投影文字内容，反对查看片头靶标和批次制作说明。","action_sequence":["监督员核对卷号、片头批次靶标与输入清单，确认拍摄对象标为设施维护检索摘要，不是原始维护簿。","1986打字员依据当时转换说明，将正文与具名有效更正合成为检索摘要，并在来源栏引用PL-83-28和C-83-19。","帧日志、摘要页码和缩微帧逐项一致；卷片准确保存1986摘要，但不复制原页装订、字位或书写层次。","团队签发表示层级决定，两种记录均保留；MV-4原件优先草案被标记待1993审计前修订。"],"visible_payoff":"1986卷片的真实身份从原页影像更正为打字服务摘要；其文字内容可按摘要用途检索，不能冒充原页物理布局。","ending":"基金档案的MV-4草案仍写无原件即排除副本，若不修订，将在1993外部审计时重演介质绝对化错误。","must_include":["1986批次靶标为维护检索摘要","打字摘要引用PL-83-28与C-83-19","卷片不复制原页装订字位","两种表示按来源用途保留"],"must_not_include":["湿布冲向法官","胶片绝对无篡改","奥瑞恩当庭败诉","维克多信誉彻底扫地"],"detailed_synopsis":"11月30日，市缩微服务中心重建1986批次。片头靶标和输入清单把拍摄对象写成“设施维护检索摘要”，不是原始维护簿。打字员按转换说明将正文与C-83-19有效更正合成摘要，来源栏同时引用PL-83-28；帧日志与摘要页码相符。卷片准确保存1986摘要文字，却不复制原页装订、字位和更正层次。原页与摘要均保留并按用途引用，基金MV-4原件优先草案转入后续修订。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"原页更正授权确认后进入1986缩微转换批次来源重建"}]
    second["artifact_creates"]=[artifact("ART_260_1986_SERVICE_ABSTRACT_PROVENANCE",260,"1986设施维护检索摘要输入与缩微批次来源链","conversion_record",["batch_target","typed_service_abstract","pl83_28_source","c83_19_correction","frame_log","not_original_page_photograph"],["verify_1986_microfilmed_service_abstract","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_260_PL83_28_REPRESENTATION_SCOPE",260,"PL-83-28原页与1986缩微摘要表示层级决定","evidence_scope_record",["original_page_layout","authorized_margin_correction","typed_corrected_abstract","microfilm_of_abstract","both_preserved_by_scope"],["preserve_layered_pl83_28_representations","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_259_PL83_28_MARGIN_CORRECTION_CHAIN","timeline_scope":"current","display_name":"PL-83-28页边更正与C-83-19勘误授权链","purpose":"确认1986摘要应用的是已经具名授权的更正","required_permission":"verify_pl83_28_authorized_correction","scope_assertion":"有效更正不把摘要变成原页摄影"},{"artifact_id":"ART_259_PL83_28_SOURCE_PAGE_RECORD","timeline_scope":"current","display_name":"PL-83-28原页正文页边与装订位置记录","purpose":"比较原页布局与缩微拍摄对象的表示差异","required_permission":"record_pl83_28_source_page_layout","scope_assertion":"布局差异不自动证明任一载体伪造"}]


def repair_ec131(event: dict[str, Any]) -> None:
    event.update({
        "name":"MV-4媒介中立验证清单与BX-17当前审计范围","timeline_years":"1993","main_opponent":"外部审计中原件绝对化与无来源复印件即时入账两种主张","opposition_type":"institutional","event_type":"legal_procedure","solution_type":"legal_evidence",
        "prev_life_tragedy":"前世基金用无原件即排除副本的规则自保，既误伤有来源的合法工作副本，也没能阻止对手把另一张无来源复印件直接放进税务调整计算。",
        "info_gap_from_prev_life":"麦珂记得1993外部审计会出现一张被用来主张资金流向不明的影印凭单，却不知道它是否伪造；今生只能提前建立对纸张、缩微、复印和转换摘要均适用的来源门槛。",
        "preemptive_avoidance":"在1993审计前把MV-4从原件优先改为来源、复制或转换方法、核验人、完整性和用途范围清单；审计现场不由麦珂拒收材料，而由审计主管决定当前使用状态。",
        "bait_and_evidence":"档案研究代理人一面要求基金的合法副本全部失效，一面要求BX-17无来源复印件立即证明未明转款；媒介中立清单让两种材料接受同一基础审查。",
        "villain_loss":"代理人不能让BX-17在缺保管人、原记录定位、复制方法和缺页说明时直接进入本轮调整计算，也不能借原件绝对规则排除基金所有合法副本。",
        "protagonist_gain":"基金取得经试行验证的MV-4清单；有完整来源的原页、缩微摘要和遮蔽工作副本均可按范围使用，BX-17保留补充来源机会但当前不计入调整。",
        "relationship_change":"麦珂接受自己不能在审计席拒收不利材料，只能要求同一清单平等审查；苏菲亚负责记录状态而不代替审计主管裁定。",
        "cluster_outcome":"MV-4改为媒介中立并通过三类既有材料试行；BX-17因基础字段缺失被列为待补来源、暂不进入当前调整计算，不被永久定伪，基金也不获得复印件豁免。",
        "next_event_hook":"代理人在补充期内提交BX-17复印作业票CT-17，但作业票登记四页、现件只有三页，且第二次曝光时点晚于其声称的复制时间；下一簇须核作业队列、原稿页数和缺失页，而不是使用声波扫描。",
        "resolution_signature":{"attack_domain":"original_only_rule_and_ungrounded_copy_used_asymmetricly_in_tax_audit","counter_method":"media_neutral_foundation_checklist_pilot_then_current_sample_scope_decision","resolver":"基金独立档案审查组与联邦税务审计主管","publicity":"closed_audit_intake","hero_gain_type":"equal_foundation_standard_and_no_current_adjustment_from_bx17"},
        "continuity_writes":["承接EC130发现的MV-4原件优先草案，并在开章明确从1991年11月跳到1993年9月。","不虚构第45天原件规则、声学保险柜、信托会议、复印件永久失效、基金审计豁免或代表资格暂停。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：原件绝对规则误伤合法副本，无来源复印件却被直接用于税务调整；本事件独有信息差：麦珂只记得1993审计会出现不利影印凭单，不知其真假；今生提前动作：把MV-4改为媒介中立并试行；第261章可见小赢：原页、缩微摘要和遮蔽工作副本按各自来源通过；第262章新交锋：代理人要求BX-17立即入账，审计主管因基础缺口列为待补来源；阻力方现实损失：不能形成当前调整，也不能排除基金全部副本；主角现实收益：取得平等来源标准；结算边界：材料不永久定伪、可在补充期重提、基金仍接受正常审计。"
    event["main_characters"]=["麦珂","苏菲亚","瑟琳娜","基金独立会计","联邦税务审计主管"]
    event["state_transitions"]=[
        {"domain":"rights","entity_id":"RIGHT_MV4_FOUNDATION_REVIEW","state_key":"media_rule","from":"original_only_copy_excluded","to":"media_neutral_source_conversion_verification_and_scope_check","irreversible":False,"evidence":"ART_261_MV4_MEDIA_NEUTRAL_CHECKLIST","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"asset","entity_id":"ASSET_BX17_PHOTOCOPY","state_key":"current_audit_use","from":"claimed_immediate_unexplained_fund_adjustment_evidence","to":"pending_foundation_excluded_from_current_calculation_without_prejudice","irreversible":False,"evidence":"ART_262_BX17_CURRENT_SCOPE_DECISION","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,261)
    first.update({"timeline_start":"1993-09-10","timeline_end":"1993-09-10","scene":"初声基金独立档案政策审查室","chapter_title":"二十一个月后的MV-4重写","chapter_goal":"在外部审计前将MV-4改为媒介中立来源清单，并用已核三类材料试行。","participants":["麦珂","苏菲亚","瑟琳娜","基金独立会计","基金档案主管","外部审计联络员"],"opening_conflict":"旧MV-4第一条要求无原件即排除副本；联络员指出这会把有来源的1986摘要和三张遮蔽校对副本一起拒绝。","info_gap_use":"相隔二十一个月，麦珂只提前提醒1993审计会出现不利复印凭单，不写入其真假结论。","opponent_reaction":"基金内部保守席要求保留原件一票否决，认为这样最容易保护基金。","action_sequence":["审查组把MV-4拆成记录身份、保管来源、复制或转换方法、完整性核对、核验人和本次用途六栏。","原件无法取得时须写原因与替代核验路径，不自动通过或排除；状态分为范围内可用、待补来源和当前范围外。","审查组以PL-83-28原页、1986缩微摘要和FND-RP-83-09三张遮蔽工作副本试填，三者按不同用途通过。","麦珂撤回原件优先要求，独立组签发试行版与逐项结果，不建立信托或基金豁免。"],"visible_payoff":"MV-4从一句原件优先改为六栏可复核清单，三种不同表示均按自己的来源和用途获得明确状态。","ending":"两天后的联邦税务审计收件目录列出BX-17影印凭单，来源、复制方法和页数栏均空。","must_include":["明确交代相隔二十一个月","MV-4六栏媒介中立","三类材料分别试填","原件缺失不自动通过或排除"],"must_not_include":["信托协议草案","声学锚定保险柜","第45天原件规则","复印件法律上彻底失效"],"detailed_synopsis":"1993年9月10日，距PL-83-28核验二十一个月，初声基金为外部审计重写MV-4。旧稿的无原件即排除被改为记录身份、保管来源、复制或转换方法、完整性、核验人和用途六栏；原件缺失时记录原因与替代路径，不自动通过或拒绝。PL-83-28原页、1986缩微摘要和FND-RP-83-09遮蔽副本分别按范围试填通过。麦珂撤回原件优先要求，清单不产生信托或审计豁免。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"从1991年11月的MV-4待修订标记推进到1993年9月外部审计准备"}]
    first["artifact_creates"]=[artifact("ART_261_MV4_MEDIA_NEUTRAL_CHECKLIST",261,"MV-4媒介中立来源与转换验证清单试行版","audit_rule",["record_identity","custody_source","copy_or_conversion_method","completeness","verifier","use_scope","missing_original_reason","alternative_verification"],["apply_media_neutral_foundation_review","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_261_MV4_PILOT_MATRIX",261,"MV-4原页缩微摘要与遮蔽副本试填矩阵","audit_record",["original_page_case","microfilmed_abstract_case","redacted_work_copy_case","separate_use_statuses"],["document_mv4_pilot_results","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_260_PL83_28_REPRESENTATION_SCOPE","timeline_scope":"current","display_name":"PL-83-28原页与1986缩微摘要表示层级决定","purpose":"为MV-4原页与转换摘要两种试填提供已核来源","required_permission":"preserve_layered_pl83_28_representations","scope_assertion":"试填不把任一介质设为唯一凭证"},{"artifact_id":"ART_256_FUND_COPY_SCOPE_DECISION","timeline_scope":"current","display_name":"基金三张票据索引校对副本范围决定","purpose":"为有来源遮蔽工作副本试填提供既定范围","required_permission":"limit_fund_ticket_copy_scope","scope_assertion":"合法副本可用不扩张票据权利"}]
    second=milestone(event,262)
    second.update({"timeline_start":"1993-09-12","timeline_end":"1993-09-12","scene":"联邦税务审计资料收件与范围会议室","chapter_title":"BX-17不是立即调整也不是永久定伪","chapter_goal":"用MV-4审查BX-17复印凭单的来源基础，决定其在本轮税务调整计算中的当前状态。","participants":["麦珂","苏菲亚","基金独立会计","联邦税务审计主管","审计记录员","档案研究代理人"],"opening_conflict":"代理人提交BX-17，称其显示基金有未说明转款，要求立即加入本轮调整计算；麦珂则想当场拒收一切复印件。","info_gap_use":"麦珂只记得前世类似影印件触发不利调整，今生仍让审计主管按相同六栏检查，不自行裁定。","opponent_reaction":"代理人要求以画面可读替代来源栏，并把缺页称为无关背页。","action_sequence":["审计主管接收并编号BX-17，不把接收等同采信；记录现件三页、来源保管人空白、原记录箱号空白。","MV-4检查发现复制设备与作业票未知，第二页页码跳接，签署页只剩局部，无法核完整性和制作方法。","主管将BX-17列为待补来源，在本轮调整计算中暂不采用，给代理人按审计日程提交保管与复制链的补充期。","基金继续提交普通账目并接受抽样，麦珂撤回自行拒收；材料密封保存、不永久定伪。"],"visible_payoff":"BX-17没有触发即时税务调整；同一清单既保护有来源副本，也要求不利复印件补足基础。","ending":"代理人补交的CT-17复印作业票登记四页，现件却只有三页，且第二次曝光时点晚于其声称复制时间。","must_include":["接收编号不等于采信","BX-17现件三页且基础字段空","待补来源并暂不进入当前计算","基金继续普通审计抽样"],"must_not_include":["麦珂当场拒绝接收","奥瑞恩代表资格暂停","基金豁免提交复印件","复印件永久定伪"],"detailed_synopsis":"9月12日，联邦税务审计收件BX-17影印凭单。主管先编号接收，再用MV-4审查：现件三页，保管人、原记录箱号、复制设备与作业票未知，页码跳接且签署页不完整。材料被列为待补来源，在本轮调整计算中暂不采用；代理人获得按审计日程补足来源的机会。基金继续普通账目抽样，麦珂无权自行拒收，BX-17密封保存且不被永久定伪。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"MV-4试行版完成后进入联邦税务审计的具体材料收件与范围决定"}]
    second["artifact_creates"]=[artifact("ART_262_BX17_FOUNDATION_GAP",262,"BX-17三页复印凭单来源与完整性缺口表","audit_record",["three_pages_present","custodian_blank","source_box_blank","copy_method_unknown","page_jump","partial_signature_page"],["record_bx17_foundation_gaps","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_262_BX17_CURRENT_SCOPE_DECISION",262,"BX-17待补来源与本轮调整计算范围决定","audit_decision",["received_not_admitted","pending_foundation","excluded_current_adjustment_calculation","supplement_window","sealed_preservation","not_forgery_finding"],["set_bx17_current_audit_status","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_261_MV4_MEDIA_NEUTRAL_CHECKLIST","timeline_scope":"current","display_name":"MV-4媒介中立来源与转换验证清单试行版","purpose":"以与基金有利材料相同的六栏审查BX-17","required_permission":"apply_media_neutral_foundation_review","scope_assertion":"清单决定当前基础状态不永久定伪"},{"artifact_id":"ART_261_MV4_PILOT_MATRIX","timeline_scope":"current","display_name":"MV-4原页缩微摘要与遮蔽副本试填矩阵","purpose":"证明清单不因介质类型预设通过或排除","required_permission":"document_mv4_pilot_results","scope_assertion":"试填结果不替BX-17自身来源"}]


def repair_ec132(event: dict[str, Any]) -> None:
    event.update({
        "name":"CT-17四页作业票与BX-17缺失第二页核验","timeline_years":"1993","main_opponent":"BX-17三页摘录被当成完整付款凭单","opposition_type":"institutional","event_type":"legal_procedure","solution_type":"legal_evidence",
        "prev_life_tragedy":"前世BX-17三页摘录省去资金用途分配页，媒体与审计据此把基金内部调拨写成未明外流；团队沉迷纸张纹理争辩，没有核复印作业队列和四页源包。",
        "info_gap_from_prev_life":"麦珂记得缺失页会改变转款解释，却不知道谁在何时重印、遗漏是否故意或源包内容；今生必须核CT-17作业票、机械计数、操作员、交付封和原保管包。",
        "preemptive_avoidance":"不使用声波扫描、刺耳警报或纹理终审；先重建CT-17两次曝光，再由审计主管从原保管人调取FV-83-204四页源包。",
        "bait_and_evidence":"代理人用CT-17首次四页记录为BX-17来源辩护，却提交背面盖CT-17-B的第二批三页；作业队列显示第二批只重印一、三、四页，四页源包的第二页是用途分配表。",
        "villain_loss":"代理人失去把BX-17三页摘录当完整凭单并据此主张未明外流的当前路径；不完整摘录不能进入该项调整计算。",
        "protagonist_gain":"审计取得FV-83-204四页源包、内部场馆储备调拨用途和完整签署权限，当前项目不产生未明转款调整。",
        "relationship_change":"麦珂没有把缺页直接称为伪造；他接受第二次三页复印可能存在正常解释，直到原包与队列共同确认其不完整影响。",
        "cluster_outcome":"CT-17第一次复制四页，第二次CT-17-B只复制一、三、四页且晚于所称时点；BX-17是选择性三页摘录。FV-83-204完整包证明款项为基金内部场馆储备调拨，本项当前不调整，但不作刑事伪造认定。",
        "next_event_hook":"CT-17队列显示PR-19新闻简报作业在审计前取得一套BX-17-B三页摘录，已有记者据此准备报道；下一簇须以来源包、缺页说明和可核更正通知处理公共信息，不能做声学指纹直播。",
        "resolution_signature":{"attack_domain":"three_page_recopy_excerpt_laundered_into_complete_four_page_disbursement_voucher","counter_method":"copy_job_queue_reconstruction_and_custodian_produced_full_source_packet_reconciliation","resolver":"复印服务主管与联邦税务审计主管","publicity":"closed_copy_operations_and_audit_reconciliation","hero_gain_type":"no_current_unexplained_transfer_adjustment_for_fv83_204"},
        "continuity_writes":["承接EC131的CT-17四页/三页、两次曝光时点和BX-17待补来源状态。","不使用纸张声波、便携扫描警报、纹理唯一鉴定、黛安娜财务晋升、重点稽查名单或信誉瞬间崩塌。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：BX-17省去用途页后被当完整凭单，基金内部调拨被写成未明外流；本事件独有信息差：麦珂只记得缺页改变解释，不知复印时点与源包；今生提前动作：重建CT-17两次曝光并由保管人调四页源包；第263章可见小赢：确认现件属于晚间三页CT-17-B而非下午四页首批；第264章新交锋：代理人称第二页无关，原包证明其为用途分配表；阻力方现实损失：三页摘录不能支撑当前调整；主角现实收益：完整内部调拨链进入审计；结算边界：不认定刑事伪造、不排除对完整包提出其他质疑。"
    event["main_characters"]=["麦珂","苏菲亚","基金独立会计","联邦税务审计主管","复印服务主管"]
    event["state_transitions"]=[
        {"domain":"asset","entity_id":"ASSET_CT17_COPY_JOB","state_key":"copy_sequence","from":"single_four_page_copy_claimed_as_bx17_source","to":"first_four_page_batch_and_later_three_page_ct17_b_recopy_distinguished","irreversible":False,"evidence":"ART_263_CT17_COPY_QUEUE_RECONSTRUCTION","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"asset","entity_id":"ASSET_BX17_PHOTOCOPY","state_key":"completeness_and_adjustment_use","from":"three_page_excerpt_claimed_complete_unexplained_transfer_voucher","to":"incomplete_excerpt_reconciled_to_four_page_internal_reserve_transfer_no_current_adjustment","irreversible":False,"evidence":"ART_264_FV83_204_RECONCILIATION_DECISION","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,263)
    first.update({"timeline_start":"1993-09-13","timeline_end":"1993-09-13","scene":"联邦审计签约复印服务室作业队列核验台","chapter_title":"下午四页与晚间三页","chapter_goal":"核对CT-17作业票、队列、机械计数、操作员和交付封，确定BX-17属于哪次复印。","participants":["麦珂","苏菲亚","联邦税务审计记录员","复印服务主管","CT-17操作员","档案研究代理人"],"opening_conflict":"代理人以CT-17登记四页为由，声称BX-17虽只有三页仍来自同一次完整复制，第二页只是未提交的空白背页。","info_gap_use":"麦珂只提醒缺失页可能改变解释，不先断定操作员或代理人故意删页。","opponent_reaction":"代理人只交作业票首页，反对查看队列背页、机械计数和两只交付封。","action_sequence":["主管核对CT-17下午首批：四页原稿、四次有效曝光、一次废样、四页成品装入CT-17-A封。","队列背页记录晚间重开作业，只复制页一、三、四，三次有效曝光，装入CT-17-B封。","BX-17三页背面均有CT-17-B收讫小章，裁切和页序与晚间三页批次相合；声称的下午复制时点不适用于现件。","苏菲亚制作队列重建记录；当前只确认选择性重印与时点，不判断遗漏动机或凭单内容。"],"visible_payoff":"BX-17从下午四页首批分离，锁定为晚间CT-17-B三页重印；第二页是否关键转入源包核验。","ending":"原保管回执将四页源文件定位为FV-83-204，联邦审计主管向基金受托银行发出直接调取令。","must_include":["CT-17-A下午四页","CT-17-B晚间只印一三四页","机械计数与两只交付封","现件三页背面对应CT-17-B"],"must_not_include":["声波扫描警报","纸张纹理定伪","奥瑞恩列重点稽查","黛安娜晋升财务岗位"],"detailed_synopsis":"1993年9月13日，签约复印服务室重建CT-17。下午首批由四页原稿完成四次有效曝光，装入CT-17-A；晚间作业重开，只印一、三、四页，装入CT-17-B。BX-17三页背面的小章、页序与裁切对应晚间批次，因此不适用代理人所称下午复制时点。当前只确认选择性重印与时点，不判断遗漏动机；四页源文件FV-83-204由审计主管直接向保管人调取。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"BX-17待补来源决定中的CT-17页数与曝光时点矛盾进入作业队列核验"}]
    first["artifact_creates"]=[artifact("ART_263_CT17_COPY_QUEUE_RECONSTRUCTION",263,"CT-17下午四页与晚间三页复印作业队列重建","copy_job_record",["ct17_a_four_pages","afternoon_time","ct17_b_pages_1_3_4","later_time","mechanical_counter","operator","delivery_envelopes"],["distinguish_ct17_copy_batches","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_263_BX17_CT17B_MATCH",263,"BX-17现件与CT-17-B三页批次对应记录","evidence_match",["three_present_pages","ct17_b_receipt_marks","page_order","crop_alignment","no_motive_finding"],["match_bx17_to_ct17_b_batch","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_262_BX17_FOUNDATION_GAP","timeline_scope":"current","display_name":"BX-17三页复印凭单来源与完整性缺口表","purpose":"限定本次只补复制作业和缺页来源字段","required_permission":"record_bx17_foundation_gaps","scope_assertion":"缺口表不预设BX-17伪造"}]
    second=milestone(event,264)
    second.update({"timeline_start":"1993-09-15","timeline_end":"1993-09-15","scene":"联邦税务审计FV-83-204原包限定核对室","chapter_title":"第二页写的是资金去向","chapter_goal":"比较FV-83-204四页原保管包与BX-17三页摘录，决定该笔款项的当前审计处理。","participants":["麦珂","苏菲亚","基金独立会计","联邦税务审计主管","基金受托银行保管人","档案研究代理人"],"opening_conflict":"代理人承认CT-17-B只印三页，却坚持第二页是无关说明，不影响第一页金额与第四页签名对未明转款的证明。","info_gap_use":"麦珂不凭前世记忆描述缺页内容，等待保管人按审计调取令开四页原包。","opponent_reaction":"代理人试图只比第一页金额，不读取第二页用途分配和第四页完整权限说明。","action_sequence":["保管人核FV-83-204封签、四页目录和连续页码，在限定室逐页展示，不让基金自行带入替代文件。","第二页为用途分配表，列款项从基金运营户转入同一基金的场馆储备子账；银行对账与子账入账相合。","完整第四页显示签署人为有额度权限的独立会计，BX-17裁切掉的是职务和授权号；三页摘录无法独立承担完整解释。","审计主管对该项不作未明转款调整，保留完整包的其他合规审查与对摘录形成原因的另行调查。"],"visible_payoff":"缺失第二页恢复款项用途，BX-17当前未明外流主张失去基础；完整四页链进入审计而非被主角单方宣告真相。","ending":"CT-17队列中的PR-19新闻简报作业曾取得一套BX-17-B三页摘录，一名记者已据此准备未明转款报道。","must_include":["FV-83-204四页连续源包","第二页为同基金场馆储备用途","第四页完整职务与授权号","本项不作未明转款调整但保留其他审查"],"must_not_include":["物理原件唯一法律效力","伪造票据死刑时刻","公开晋升仪式","信誉瞬间崩塌"],"detailed_synopsis":"9月15日，基金受托银行保管人依审计令展示FV-83-204四页连续源包。第二页用途分配表证明款项从基金运营户转入同一基金的场馆储备子账，银行和子账记录相合；完整第四页保留签署人的职务与额度授权号，BX-17裁掉了这些说明。审计主管对该项不作未明转款调整，但保留对完整包其他合规问题及三页摘录形成原因的审查。PR-19新闻简报已取得摘录，引出公共更正。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"CT-17-B三页批次锁定后由审计主管直接调取FV-83-204四页源包"}]
    second["artifact_creates"]=[artifact("ART_264_FV83_204_FULL_PACKET_COMPARISON",264,"FV-83-204四页源包与BX-17三页摘录比对","audit_record",["four_continuous_pages","missing_page_two","internal_venue_reserve_allocation","bank_and_subledger_match","full_role_and_authority"],["reconcile_bx17_with_fv83_204","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_264_FV83_204_RECONCILIATION_DECISION",264,"FV-83-204本轮未明转款调整决定","audit_decision",["no_unexplained_transfer_adjustment_current_item","internal_fund_transfer","other_compliance_review_preserved","excerpt_origin_review_preserved","no_criminal_forgery_finding"],["set_fv83_204_current_adjustment_scope","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_263_CT17_COPY_QUEUE_RECONSTRUCTION","timeline_scope":"current","display_name":"CT-17下午四页与晚间三页复印作业队列重建","purpose":"解释BX-17为何缺第二页并区分两次复制时点","required_permission":"distinguish_ct17_copy_batches","scope_assertion":"作业差异不单独证明遗漏动机"},{"artifact_id":"ART_263_BX17_CT17B_MATCH","timeline_scope":"current","display_name":"BX-17现件与CT-17-B三页批次对应记录","purpose":"将现件与晚间三页摘录对应后再比较源包","required_permission":"match_bx17_to_ct17_b_batch","scope_assertion":"现件对应不替源包说明资金用途"}]
    # Keep the copy-room reconstruction and same-day custodian production
    # inside the already-open September 12 audit session.  This avoids forcing
    # unrepaired downstream events to regress from September 15 to September 12.
    first["timeline_start"] = first["timeline_end"] = "1993-09-12"
    first["detailed_synopsis"] = first["detailed_synopsis"].replace("1993年9月13日", "1993年9月12日下午")
    second["timeline_start"] = second["timeline_end"] = "1993-09-12"
    second["detailed_synopsis"] = second["detailed_synopsis"].replace("9月15日", "同日晚些时候")


def repair_ec133(event: dict[str, Any]) -> None:
    event.update({
        "name":"PR-19三页新闻摘录与独立核源更正","timeline_years":"1993","main_opponent":"PR-19新闻简报对BX-17三页摘录的完整凭单包装","opposition_type":"institutional","event_type":"media_reputation","solution_type":"media_counter",
        "prev_life_tragedy":"前世媒体收到BX-17三页摘录后直接刊出基金未明转款标题，后来即使补到完整用途页，也只能被当成危机公关；原始简报、核源请求和更正去向没有保留。",
        "info_gap_from_prev_life":"麦珂记得艾琳会收到PR-19，却不知道她是否已刊发或其他编辑台拿到什么版本；今生只能尽快提供可公开核验的来源包，不能要求她按团队口径发声。",
        "preemptive_avoidance":"团队不举行声学指纹直播或公开原始账户细节；艾琳先暂停未刊标题，独立核CT-17-B、审计当前决定和银行公开遮蔽说明，再按PR-19分发清单逐家更正。",
        "bait_and_evidence":"PR-19把三页BX-17称为完整付款凭单并省去审计待补状态；核源矩阵确认摘录缺第二页，公开遮蔽说明只证明同基金场馆储备调拨，不证明基金整体无误。",
        "villain_loss":"PR-19发送方失去让未明转款标题以完整凭单名义继续传播的路径；收到材料的编辑台获得同一更正包和原简报留档。",
        "protagonist_gain":"基金取得一条可追踪的公共更正记录，特定未明外流指控被收窄；审计进行中、场馆支出仍待抽样的边界同时公开。",
        "relationship_change":"艾琳拒绝麦珂预写标题和真相广播安排，只接受有来源材料并保留代理人的回应；麦珂接受她可能继续报道基金其他问题。",
        "cluster_outcome":"艾琳暂停尚未刊发的未明转款标题，PR-19六个接收台均收到来源更正包；已发的一则短讯刊出更正。公开记录确认BX-17缺用途页且本项不作未明外流调整，但不宣布基金全面清白或奥瑞恩永无回应权。",
        "next_event_hook":"PR-19分发附件还夹带MG-6混合担保账户提案，试图以新闻质疑促使基金把场馆储备与艺人个人资产互相担保；下一簇须审查担保对象、表决权限、退出条件和利益冲突，而非授予任何人绝对否决权。",
        "resolution_signature":{"attack_domain":"three_page_bx17_excerpt_packaged_as_complete_voucher_for_press_distribution","counter_method":"independent_editorial_source_matrix_public_safe_correction_packet_and_distribution_acknowledgments","resolver":"艾琳·沃特曼与各编辑台核源负责人","publicity":"source_scoped_newspaper_correction","hero_gain_type":"specific_unexplained_transfer_claim_corrected_with_audit_boundary"},
        "continuity_writes":["承接EC132的PR-19新闻简报去向、CT-17-B三页摘录和FV-83-204有限审计决定。","删除无来源的维克多·斯特林姓名，不做声学指纹、公证直播、记者群嘲、银行争抢托管或公众永久倒向。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：BX-17三页摘录被媒体当完整凭单刊出，后续来源只能被视作公关；本事件独有信息差：麦珂只知艾琳会收到PR-19，不知刊发与分发状态；今生提前动作：提供公开安全来源并让记者独立核查；第265章可见小赢：艾琳暂停未刊标题并形成核源矩阵；第266章新交锋：发送方称更正包泄密，公开遮蔽字段和审计范围允许逐台更正；阻力方现实损失：完整凭单包装和未明外流标题失去来源；主角现实收益：特定公共记录得到可追踪修正；结算边界：审计仍在进行、保留对方回应、不宣布全面清白。"
    event["main_characters"]=["麦珂","苏菲亚","艾琳·沃特曼","基金独立会计","档案研究代理人"]
    event["state_transitions"]=[
        {"domain":"asset","entity_id":"ASSET_PR19_NEWS_BRIEF","state_key":"editorial_status","from":"unverified_unexplained_transfer_headline_scheduled","to":"headline_held_and_source_matrix_completed","irreversible":False,"evidence":"ART_265_PR19_EDITORIAL_SOURCE_MATRIX","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"rights","entity_id":"RIGHT_PR19_PUBLIC_RECORD","state_key":"public_claim_scope","from":"three_page_excerpt_circulating_as_complete_unexplained_transfer_proof","to":"source_scoped_correction_with_audit_and_reply_preserved","irreversible":False,"evidence":"ART_266_PR19_DISTRIBUTION_CORRECTION_LOG","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,265)
    first.update({"timeline_start":"1993-09-12","timeline_end":"1993-09-12","scene":"《海湾纪事》调查编辑部夜间核源桌","chapter_title":"标题先停在排字架上","chapter_goal":"由艾琳独立核对PR-19、BX-17三页摘录和公开可用来源，决定尚未刊发标题状态。","participants":["麦珂","苏菲亚","艾琳·沃特曼","调查编辑","档案研究代理人","报社法务编辑"],"opening_conflict":"PR-19称BX-17是完整付款凭单，编辑部已排出“初声基金未明转款”标题，代理人要求赶午夜版。","info_gap_use":"麦珂只告知前世报道风险，不声称艾琳已经被收买或命令她采用基金标题。","opponent_reaction":"代理人要求只核金额和局部签名，称审计待补状态与缺失第二页是基金拖延话术。","action_sequence":["艾琳登记PR-19原简报、三页附件、发送封和拟刊标题，确认尚未付印。","她比较CT-17-B对应记录、FV-83-204公开遮蔽说明和审计当前范围决定，将事实分为已核、待核与不可公开三栏。","麦珂提出预写反击标题，被艾琳拒绝；她同时向代理人发出具体问题和回应时限。","编辑部签发标题暂停单，保留原排字样与来件，不把暂停写成基金获胜或材料伪造。"],"visible_payoff":"未明转款标题在午夜版付印前暂停，新闻判断从三页摘录转入有记录的独立核源。","ending":"PR-19分发回执显示简报还送往五个编辑台，其中一则下午短讯已经刊出未明转款说法。","must_include":["PR-19原简报与三页附件登记","标题尚未付印先暂停","已核待核不可公开三栏","艾琳向双方独立提问"],"must_not_include":["真相广播预案","记者当场识破群嘲","维克多·斯特林","艾琳按麦珂口径发稿"],"detailed_synopsis":"1993年9月12日晚，《海湾纪事》核源桌收到PR-19三页摘录，未明转款标题已排字但尚未付印。艾琳登记原简报、发送封与附件，比较CT-17-B对应记录、公开遮蔽说明和审计范围，把材料分为已核、待核、不可公开三栏。她拒绝麦珂预写反击标题，也向代理人发问题单。标题暂停，原样与来件保留；分发回执显示另有五个编辑台收到材料，一则短讯已发。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"PR-19取得CT-17-B三页摘录后进入独立编辑核源"}]
    first["artifact_creates"]=[artifact("ART_265_PR19_EDITORIAL_SOURCE_MATRIX",265,"PR-19三页摘录新闻核源矩阵","editorial_record",["original_brief","three_page_attachment","ct17_b_match","public_safe_source_note","audit_scope","verified_pending_not_public"],["document_independent_pr19_source_review","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_265_PR19_HEADLINE_HOLD",265,"PR-19未明转款标题付印前暂停单","editorial_hold",["original_headline_preserved","not_yet_printed","specific_source_questions","reply_deadline","no_forgery_finding"],["hold_unverified_pr19_headline","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_264_FV83_204_FULL_PACKET_COMPARISON","timeline_scope":"current","display_name":"FV-83-204四页源包与BX-17三页摘录比对","purpose":"只向编辑部说明被省略字段和公开可核来源","required_permission":"reconcile_bx17_with_fv83_204","scope_assertion":"不得公开未获准账户或场馆细节"},{"artifact_id":"ART_264_FV83_204_RECONCILIATION_DECISION","timeline_scope":"current","display_name":"FV-83-204本轮未明转款调整决定","purpose":"准确表述本项当前不调整及其他审查保留","required_permission":"set_fv83_204_current_adjustment_scope","scope_assertion":"不等于基金全面合规"}]
    second=milestone(event,266)
    second.update({"timeline_start":"1993-09-12","timeline_end":"1993-09-12","scene":"《海湾纪事》更正与分发确认台","chapter_title":"六个接收台与一则已发短讯","chapter_goal":"制作公开安全的来源更正包，按PR-19分发回执逐台送达并处理已发短讯。","participants":["麦珂","苏菲亚","艾琳·沃特曼","调查编辑","报社法务编辑","PR-19分发管理员","档案研究代理人"],"opening_conflict":"代理人称公开任何第二页信息都会泄露基金账户，要求各编辑台继续沿用三页简报直到审计结束。","info_gap_use":"麦珂不要求公开完整四页或审计密封材料，只支持由保管人与审计公开信息席确认的遮蔽说明。","opponent_reaction":"代理人提交回应，承认三页摘录但坚持内部调拨仍可能掩盖后续滥用，要求全文刊载。","action_sequence":["艾琳与法务编辑制作来源包：三页现件页序、缺失第二页功能、同基金调拨的公开遮蔽说明和审计仍在继续的范围。","来源包保留代理人回应摘要与查阅编号，不披露金额、账户号、场馆限额或未决抽样内容。","分发管理员按六张PR-19回执逐台签收；四台暂停、一天后核源，一台退稿，一台已发短讯刊出同版位更正。","艾琳发表来源说明而非胜利宣言，原简报、暂停标题、回应和更正均留档；麦珂接受继续被调查。"],"visible_payoff":"六个PR-19接收台都有可追踪更正状态，已发短讯的读者能在同版位看到缺页与当前审计范围。","ending":"PR-19附件中的MG-6混合担保账户提案要求基金场馆储备与艺人个人资产互保，准备进入下一次理事会。","must_include":["公开安全来源更正包","六个PR-19接收台逐台签收","已发短讯同版位更正","审计进行中与对方回应保留"],"must_not_include":["声学指纹演示","全程直播","银行争抢托管","公众永久倒向麦珂"],"detailed_synopsis":"同日晚间，艾琳和法务编辑以三页页序、缺失第二页功能、同基金调拨的公开遮蔽说明及审计继续边界制作更正包，保留代理人回应但不泄露金额和账户。PR-19六个接收台逐台签收：四台暂停核源、一台退稿、一台对已发短讯作同版位更正。艾琳刊发来源说明，不宣布基金全面清白。分发附件中的MG-6混合担保账户提案转入下一簇。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"标题暂停后沿PR-19六张分发回执执行公开安全更正"}]
    second["artifact_creates"]=[artifact("ART_266_PR19_PUBLIC_SOURCE_PACKET",266,"PR-19公开安全来源与审计范围更正包","public_record",["three_page_sequence","missing_page_function","same_fund_transfer_public_note","audit_ongoing","reply_summary","privacy_redactions"],["distribute_public_safe_pr19_correction","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_266_PR19_DISTRIBUTION_CORRECTION_LOG",266,"PR-19六个接收台送达与更正状态日志","distribution_log",["six_receipts","four_holds","one_rejection","one_same_placement_correction","source_ids","reply_preserved"],["track_pr19_correction_delivery","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_265_PR19_EDITORIAL_SOURCE_MATRIX","timeline_scope":"current","display_name":"PR-19三页摘录新闻核源矩阵","purpose":"限定更正包只使用已核且可公开字段","required_permission":"document_independent_pr19_source_review","scope_assertion":"待核与不可公开信息不进入更正包"},{"artifact_id":"ART_265_PR19_HEADLINE_HOLD","timeline_scope":"current","display_name":"PR-19未明转款标题付印前暂停单","purpose":"保留未刊标题与停止付印时点","required_permission":"hold_unverified_pr19_headline","scope_assertion":"暂停标题不等于永久禁止报道"}]


def repair_ec134(event: dict[str, Any]) -> None:
    event.update({
        "name":"MG-6混合担保对象与利益冲突表决",
        "timeline_years":"1993",
        "main_opponent":"借PR-19新闻质疑推动基金储备与艺人个人资产交叉担保的MG-6提案方",
        "opposition_type":"institutional",
        "event_type":"finance_business",
        "solution_type":"financial_counter",
        "prev_life_tragedy":"前世基金在舆论压力下仓促签署交叉担保，把场馆周转风险传导到艺人个人资产；董事既是受益人又参与表决，失败后责任与退出边界无人说清。",
        "info_gap_from_prev_life":"麦珂记得混合担保会放大一次场馆违约，却不知道本次MG-6的真实费率、债权人接受范围或提案方是否愿意缩限；今生只能逐项拆出债务、担保物、期限、违约触发和受益关系。",
        "preemptive_avoidance":"不授予瑟琳娜或麦珂个人绝对否决权；两人作为受影响方先披露利益并回避表决，由无利益冲突理事和独立财务顾问比较原案与限额替代案。",
        "bait_and_evidence":"提案方把PR-19未明转款报道风险写成自动违约触发，并用降低场馆授信成本包装全资产交叉担保；范围矩阵显示个人录音版税、住宅权益和基金长期储备均被覆盖，且退出条件只由债权人决定。",
        "villain_loss":"MG-6不能借未经终结的新闻质疑取得基金储备与个人资产交叉追索，也不能让受影响当事人以私人否决替代独立表决。",
        "protagonist_gain":"基金保留真实融资需求，改获仅针对单一场馆履约储备、设金额上限与九十日到期的试行额度；不含个人担保，但额度较小且费用更高。",
        "relationship_change":"麦珂与瑟琳娜共同放弃用彼此的绝对否决保护资产，转而公开自己的受益与风险并回避；两人的信任落实为接受独立决定和显性成本。",
        "cluster_outcome":"独立席否决MG-6全资产交叉担保，并批准不含个人资产、只限单一场馆履约储备、设上限和九十日到期的替代额度。新闻指控不得自动触发违约，提案方可日后提交范围明确的新方案。",
        "next_event_hook":"替代额度要求基金在资料室提供场馆储备的只读核验目录；首次访问申请列出一名无授权技术承包商并要求导出历史票据全集，下一簇须处理访问身份、数据最小化和可追踪导出，而不是设计空壳服务器诱捕黑客。",
        "resolution_signature":{"attack_domain":"publicity_pressure_used_to_cross_collateralize_fund_reserves_and_artist_personal_assets","counter_method":"guarantee_object_matrix_conflict_recusal_independent_vote_and_capped_venue_specific_alternative","resolver":"初声基金无利益冲突理事与独立财务顾问","publicity":"closed_board_financing_review","hero_gain_type":"scoped_venue_facility_without_personal_cross_guarantee"},
        "continuity_writes":["承接EC133的MG-6附件、PR-19新闻质疑和审计仍在进行的边界。","不虚构第45条、双轨信托绝对否决、不可逆防线、夫妻自动共权或维克多·斯特林；新闻质疑不能直接成为金融违约事实。"],
        "historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：舆论压力下仓促交叉担保把场馆风险传给个人资产；本事件独有信息差：麦珂不知道真实费率与债权人可接受边界；今生提前动作：拆解担保对象、债务、期限、触发与受益关系；第267章可见小赢：全资产覆盖和单方退出条款被范围矩阵暴露，受影响双方回避；第268章新交锋：提案方以撤回低费率相逼，独立席比较否决与缩限融资；阻力方现实损失：不能取得交叉追索；主角现实收益：保留一项有上限的场馆额度；结算边界：额度更小、费用更高、九十日到期，未来明确方案仍可重提。"
    event["main_characters"]=["麦珂","瑟琳娜","苏菲亚","基金无利益冲突理事","独立财务顾问"]
    event["state_transitions"]=[
        {"domain":"rights","entity_id":"RIGHT_MG6_GOVERNANCE","state_key":"affected_party_decision_rule","from":"mike_or_selena_claimed_absolute_personal_veto","to":"affected_parties_disclose_and_recuse_independent_directors_vote","irreversible":False,"evidence":"ART_267_MG6_CONFLICT_RECUSAL","effect_type":"relationship_change","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"asset","entity_id":"ASSET_MG6_FINANCING","state_key":"guarantee_scope","from":"fund_reserve_and_artist_personal_assets_cross_guaranteed","to":"cross_guarantee_rejected_capped_single_venue_reserve_facility_approved","irreversible":False,"evidence":"ART_268_MG6_BOARD_DECISION","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,267)
    first.update({"timeline_start":"1993-09-13","timeline_end":"1993-09-13","scene":"初声基金理事会MG-6预审室","chapter_title":"先把担保物写全","chapter_goal":"把MG-6的债务、担保物、受益人、期限、退出和违约触发逐项展开，并确定利益冲突表决规则。","participants":["麦珂","瑟琳娜","苏菲亚","基金无利益冲突理事","独立财务顾问","MG-6提案联络人","基金记录秘书"],"opening_conflict":"提案联络人称PR-19质疑可能令场馆授信随时收紧，要求当日以一页原则批准基金储备与艺人个人资产互保。","info_gap_use":"麦珂只说明前世交叉担保曾放大风险，不把记忆当成费率或违约事实，要求顾问读取完整条款和附表。","opponent_reaction":"联络人主张担保物细目可签后再补，并暗示瑟琳娜若反对可行使私人否决，无须拖入独立席。","action_sequence":["财务顾问把MG-6拆成主债务、债权人、担保物、额度、期限、收费、违约触发、追索顺序和退出条件九栏。","附表显示场馆储备之外还覆盖个人录音版税、住宅权益与基金长期储备；新闻负面报道被列为无需核实的自动违约触发。","麦珂和瑟琳娜分别申报自己在版税、储备与融资中的利益，只能回答事实问题，随后退出讨论与表决席。","无利益冲突理事签署回避记录，要求次日同时比较原案、无担保和限额场馆储备三种方案。"],"visible_payoff":"模糊的混合账户被还原为可追索的全资产交叉担保；私人绝对否决主张转为披露、回避和独立表决。","ending":"提案方撤回最低费率报价，声称若不接受全资产覆盖，基金只能承担更小额度和更高手续费。","must_include":["MG-6九栏范围矩阵","个人版税住宅权益与长期储备被覆盖","新闻报道被写成自动违约触发","麦珂瑟琳娜披露并回避"],"must_not_include":["第45条绝对否决","双轨信托永久防线","维克多·斯特林","夫妻关系自动赋权"],"detailed_synopsis":"1993年9月13日，初声基金预审MG-6。财务顾问把一页原则拆为债务、债权人、担保物、额度、期限、费用、触发、追索与退出九栏，发现原案除场馆储备外还覆盖个人版税、住宅权益和基金长期储备，并把未经终结的新闻质疑列为自动违约触发。麦珂与瑟琳娜披露各自利益、回答事实后回避；无利益冲突理事决定次日比较三种融资方案，不让私人否决代替表决。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"PR-19更正包夹带的MG-6提案进入理事会融资范围预审"}]
    first["artifact_creates"]=[artifact("ART_267_MG6_GUARANTEE_SCOPE_MATRIX",267,"MG-6债务担保物触发与退出九栏范围矩阵","finance_review",["principal_debt","creditor","collateral","cap","term","fee","default_trigger","recourse_order","exit_condition","personal_assets_included"],["review_mg6_guarantee_scope","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_267_MG6_CONFLICT_RECUSAL",267,"MG-6受影响方利益披露与回避记录","governance_record",["mike_interest_disclosure","selena_interest_disclosure","fact_questions_only","recusal","independent_vote"],["enforce_mg6_conflict_recusal","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_266_PR19_PUBLIC_SOURCE_PACKET","timeline_scope":"current","display_name":"PR-19公开安全来源与审计范围更正包","purpose":"核对MG-6不得把新闻质疑误写为已经成立的审计违约","required_permission":"distribute_public_safe_pr19_correction","scope_assertion":"审计进行中和回应保留不得被改写为自动违约事实"}]
    second=milestone(event,268)
    second.update({"timeline_start":"1993-09-14","timeline_end":"1993-09-14","scene":"初声基金无利益冲突理事特别表决室","chapter_title":"额度缩小，资产不混在一起","chapter_goal":"比较三种融资路径，由独立席决定是否拒绝交叉担保并保留范围明确的场馆周转价值。","participants":["苏菲亚","基金无利益冲突理事","独立财务顾问","MG-6提案联络人","场馆运营财务经理","基金记录秘书","麦珂","瑟琳娜"],"opening_conflict":"提案方将最低费率与全资产交叉担保捆绑，警告基金若拒绝就会失去即将到期的场馆周转额度。","info_gap_use":"麦珂与瑟琳娜只提交书面事实答复，不返回表决席；独立顾问用实际现金缺口和报价决定可接受上限。","opponent_reaction":"联络人拒绝原费率适用于缩限方案，并要求至少保留新闻质疑触发和个人版税第二顺位追索。","action_sequence":["运营经理证明未来九十日现金缺口只与一座场馆的履约保证有关，不需要长期基金储备或个人资产覆盖。","顾问比较无担保短贷、MG-6原案和限额储备方案；限额方案费用较原案高、额度较小，但最坏损失可计量。","独立席否决原案，删除个人担保和新闻自动违约条款，批准仅以单一场馆履约储备为对象、九十日到期且不得循环续展的试行额度。","决定书保留提案方以后提交明确债权人、用途和退出条件的新案；麦珂与瑟琳娜在表决完成后回席接受成本。"],"visible_payoff":"基金没有把个人资产与长期储备押进同一追索链，同时保住一项满足近期场馆缺口的有限额度。","ending":"放款前资料核验清单出现一名无授权技术承包商，申请从只读资料室导出全部历史票据，身份和最小访问范围待核。","must_include":["三种融资方案比较","仅一座场馆九十日现金缺口","原案否决且无个人担保","替代额度更小费用更高九十日到期"],"must_not_include":["防御体系固若金汤","奥瑞恩阴谋彻底破产","不可逆否决权","基金以后永不受追索"],"detailed_synopsis":"9月14日，无利益冲突理事比较无担保短贷、MG-6全资产原案和限额场馆储备方案。运营数据表明九十日缺口只来自一座场馆的履约保证。独立席否决基金储备与个人资产交叉担保，删除新闻自动违约与个人版税追索，批准额度更小、费用更高、仅以该场馆履约储备为对象且九十日到期的试行额度。受影响双方未投票，日后范围明确的新案仍可提交。放款核验清单中的无授权技术承包商引出下一簇访问控制问题。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"MG-6范围矩阵和利益回避完成后进入独立融资方案比较与表决"}]
    second["artifact_creates"]=[artifact("ART_268_MG6_SCOPED_ALTERNATIVE",268,"MG-6单一场馆九十日限额储备融资替代案","financing_term_sheet",["single_venue","performance_reserve_only","capped_amount","ninety_day_expiry","higher_fee","smaller_facility","no_personal_guarantee","no_news_default"],["offer_scoped_mg6_alternative","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_268_MG6_BOARD_DECISION",268,"MG-6交叉担保否决与限额替代额度表决决定","board_decision",["cross_guarantee_rejected","independent_vote","affected_parties_recused","scoped_facility_approved","no_automatic_renewal","future_scoped_proposal_allowed"],["set_mg6_financing_scope","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_267_MG6_GUARANTEE_SCOPE_MATRIX","timeline_scope":"current","display_name":"MG-6债务担保物触发与退出九栏范围矩阵","purpose":"比较原案与替代案的追索范围和最坏损失","required_permission":"review_mg6_guarantee_scope","scope_assertion":"范围矩阵不替代理事表决"},{"artifact_id":"ART_267_MG6_CONFLICT_RECUSAL","timeline_scope":"current","display_name":"MG-6受影响方利益披露与回避记录","purpose":"证明麦珂与瑟琳娜未参与MG-6结果表决","required_permission":"enforce_mg6_conflict_recusal","scope_assertion":"回避不等于永久剥夺一般理事权"}]


def repair_ec135(event: dict[str, Any]) -> None:
    event.update({
        "name":"AR-22贷前资料访问身份与最小化导出",
        "timeline_years":"1993","main_opponent":"AR-22访问申请中无授权技术承包商与全历史票据导出要求",
        "opposition_type":"institutional","event_type":"contract_rights","solution_type":"legal_evidence",
        "prev_life_tragedy":"前世基金为证明没有隐匿资料，向贷前核验开放整库导出；来访者取得与单一场馆融资无关的艺人、票据和账户索引，后来再以截取字段制造新质疑。",
        "info_gap_from_prev_life":"麦珂记得一次过宽导出造成二次利用，却不知道本次技术承包商真实身份或债权人最低需要哪些字段；今生必须向申请发起人直接核授权并做字段用途映射。",
        "preemptive_avoidance":"不布置空壳服务器、不诱使来访者越权；未完成身份、授权、目的和字段审批前不建账户。获准核验只在监督席使用只读目录，导出有页数、字段、介质和交付回执。",
        "bait_and_evidence":"申请把技术承包商写成核验员助手并索要全部历史票据；债权人书面回复只授权自己的储备核验员，实际需要海湾剧院储备类别、限额、入账日与可用余额四类字段。",
        "villain_loss":"无授权承包商不能取得账户或整库导出，也不能把“完整性核验”扩成所有历史票据访问；申请发起方必须保留原始过宽请求和修订原因。",
        "protagonist_gain":"债权人完成单一场馆储备的可追踪贷前核验，MG-6替代额度不因资料争议停摆；基金保留其他场馆、个人资产和历史票据的访问边界。",
        "relationship_change":"麦珂放弃用陷阱证明来访者恶意，接受身份不全可能是委托链错误；苏菲亚获得记录和暂停权限，但不能自行判定商业必要性。",
        "cluster_outcome":"AR-22先经直接回函删除无授权承包商和全库字段，再由具名核验员在监督下查看四类只读数据并取得编号纸质摘录。全过程留访问、字段、页数和交付日志，不宣称数据库不可侵入。",
        "next_event_hook":"四类字段核验时，BA-83-11场馆设备收购付款索引的一条复印件引用显示原箱号为空、复制申请CR-41只有批准页没有申请页；下一簇须核原记录定位、复制授权和现件用途，不能靠紫外墨迹或纸张纤维直接定伪。",
        "resolution_signature":{"attack_domain":"unauthorized_contractor_and_all_history_export_hidden_inside_lender_due_diligence_request","counter_method":"direct_sponsor_identity_confirmation_field_purpose_mapping_supervised_read_only_review_and_counted_delivery","resolver":"债权人授权主管与基金资料访问管理员","publicity":"closed_lender_due_diligence_room","hero_gain_type":"financing_review_completed_without_unrelated_archive_export"},
        "continuity_writes":["承接EC134放款前只读资料核验、无授权技术承包商和整库导出要求。","不写黑客闯入、空壳服务器、核心资料提前迁空、微缩胶片天然不可篡改、技术对手惨败或黛安娜越权晋升。"],"historical_anchor_ids":[],
    })
    event["source_event_direction"]="前世具体受害：为自证透明开放整库导出后无关资料被二次利用；本事件独有信息差：麦珂不知道承包商身份或债权人最低字段；今生提前动作：直接核授权并建立字段用途矩阵；第269章可见小赢：发起人确认承包商未获授权、整库要求被暂停；第270章新交锋：核验员担心字段不足，监督席用四类字段和可核汇总完成核验；阻力方现实损失：不能取得全库；主角现实收益：有限融资核验继续；结算边界：访问日志只证明本次操作，不证明系统绝对安全。"
    event["main_characters"]=["麦珂","苏菲亚","瑟琳娜","基金资料访问管理员","债权人授权主管"]
    event["state_transitions"]=[
        {"domain":"rights","entity_id":"RIGHT_AR22_ACCESS","state_key":"access_authorization","from":"unnamed_contractor_and_all_history_export_requested","to":"named_lender_reviewer_only_with_four_field_purpose_scope","irreversible":False,"evidence":"ART_269_AR22_IDENTITY_SCOPE_DECISION","effect_type":"villain_loss","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
        {"domain":"asset","entity_id":"ASSET_AR22_DUE_DILIGENCE_EXPORT","state_key":"delivery_scope","from":"full_historical_ticket_export_requested","to":"supervised_read_only_review_and_numbered_four_field_extract_delivered","irreversible":False,"evidence":"ART_270_AR22_ACCESS_EXPORT_LOG","effect_type":"protagonist_gain","irreversible_migration_reason":"temporary_or_reversible_state_v14"},
    ]
    first=milestone(event,269)
    first.update({"timeline_start":"1993-09-15","timeline_end":"1993-09-15","scene":"初声基金资料访问管理台与债权人授权回函席","chapter_title":"申请名单里多出的承包商","chapter_goal":"向访问申请发起人直接核身份、授权、任务和最低字段，决定AR-22能否建立账户。","participants":["麦珂","苏菲亚","基金资料访问管理员","债权人授权主管","债权人储备核验员","MG-6提案联络人","无授权技术承包商"],"opening_conflict":"AR-22要求当日下午创建两只账户并导出全部历史票据，联络人称技术承包商只是核验员助手，无须另附授权。","info_gap_use":"麦珂不把身份缺口解释成预谋入侵，只要求绕过转交人向债权人授权主管核对原始委托。","opponent_reaction":"联络人以放款时限施压，要求先开临时只读账户，身份文件以后补。","action_sequence":["管理员冻结建号而不设置诱饵账户，保存原申请、名单、请求字段和到达时点。","债权人授权主管回函确认只委托一名具名储备核验员，未聘请或转授权技术承包商。","双方把融资目的映射为海湾剧院储备类别、批准限额、入账日期和可用余额四类字段，整库票据与其他场馆均无必要。","管理员签发身份范围决定；承包商可补正式委托后另提申请，当前不得进入资料室。"],"visible_payoff":"过宽申请被缩为一名具名核验员和四类融资字段，未授权者没有获得临时账户。","ending":"核验员担心四类字段无法判断余额是否由真实记录汇总，要求次日查看汇总来源目录和抽样索引。","must_include":["原AR-22申请和建号暂停","债权人直接回函只授权一人","四类最低融资字段","承包商可补授权后重提"],"must_not_include":["空壳服务器诱捕","黑客团队闯入","斯特林颜面尽失","核心数据迁空"],"detailed_synopsis":"1993年9月15日，AR-22申请多列一名技术承包商并索要全历史票据。管理员暂停建号、保存原申请；债权人授权主管直接回函，确认只委托具名储备核验员。融资目的只需要海湾剧院储备类别、批准限额、入账日期和可用余额四类字段。无授权者当前不得进入，可在取得正式委托后重提；具名核验员要求查看汇总来源目录。"})
    first["scenes"]=[{"sequence":1,"location":first["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"EC134原则接受的贷前核验清单进入身份与最小字段审批"}]
    first["artifact_creates"]=[artifact("ART_269_AR22_IDENTITY_AUTH_CHAIN",269,"AR-22申请发起人与核验员身份授权回函链","access_record",["original_request","request_sender","named_reviewer","unauthorized_contractor","direct_sponsor_reply","resubmission_allowed"],["verify_ar22_access_identity","use_as_evidence_within_scope"],list(first["participants"])),artifact("ART_269_AR22_IDENTITY_SCOPE_DECISION",269,"AR-22具名核验员与四字段访问范围决定","access_decision",["account_creation_held","named_reviewer_only","venue_reserve_category","approved_cap","posting_date","available_balance","no_full_archive"],["set_ar22_access_scope","use_as_evidence_within_scope"],list(first["participants"]))]
    first["artifact_refs"]=[{"artifact_id":"ART_268_MG6_SCOPED_ALTERNATIVE","timeline_scope":"current","display_name":"MG-6单一场馆九十日限额储备融资替代案","purpose":"从获准融资对象反推贷前核验所需最低字段","required_permission":"offer_scoped_mg6_alternative","scope_assertion":"融资授权不产生全部历史票据访问权"}]
    second=milestone(event,270)
    second.update({"timeline_start":"1993-09-17","timeline_end":"1993-09-17","scene":"初声基金贷前资料只读核验室","chapter_title":"四类字段也要看见来源","chapter_goal":"在不开放整库的前提下，让具名核验员验证四类字段的汇总来源并留下完整访问与交付记录。","participants":["麦珂","苏菲亚","基金资料访问管理员","债权人储备核验员","基金独立会计","资料室监督员"],"opening_conflict":"核验员接受四字段范围，却认为只看基金打印的余额等于相信自报数字，要求进入历史票据目录自由抽样。","info_gap_use":"麦珂不以离线介质天然可信回应，而让独立会计提供四字段的分层汇总来源与限定抽样路径。","opponent_reaction":"核验员要求保存屏幕副本和整表文件，以便回去复算；管理员拒绝不可追踪复制但提供编号摘录。","action_sequence":["监督员用一次性时段账号打开只读目录，屏幕只含四字段、汇总批次号和来源索引号，其他场馆与个人字段不显示。","核验员从当期入账中抽三笔，沿索引查看银行入账确认和批准限额页的遮蔽工作副本，复算后与可用余额一致。","系统打印编号字段摘录和抽样结果；管理员核纸张页数、字段列、账号时段和打印计数，核验员签交付回执。","账号在时段结束后关闭，日志记录查询和打印，不把未发生的攻击写成失败，也不证明资料库绝对安全。"],"visible_payoff":"债权人取得足以复核额度的四字段摘录，贷前核验继续；基金没有交付全部历史票据或无关账户数据。","ending":"抽样索引中BA-83-11引用一份旧复印件，原箱号为空，CR-41只有批准页没有申请页，转入下一簇来源核验。","must_include":["一次性时段只读账号","四字段汇总批次与来源索引","三笔限定抽样复算","编号摘录页数打印计数与交付回执"],"must_not_include":["微缩胶片不可篡改","原始物理介质唯一有效","黛安娜晋升首席架构师","常规网络攻击彻底失效"],"detailed_synopsis":"9月17日，具名核验员在监督下使用一次性时段只读账号查看四字段、汇总批次号和来源索引。他限定抽三笔银行入账及批准限额遮蔽副本，复算可用余额；资料室只交付带编号的字段摘录，记录页数、打印计数、账号时段和签收。日志只证明本次操作，不证明系统绝对安全。抽样发现BA-83-11旧复印件的原箱号与CR-41申请页缺口。"})
    second["scenes"]=[{"sequence":1,"location":second["scene"],"is_primary":True,"temporal_mode":"current","transition_cue":"身份与四字段范围获批后进入受监督只读核验"}]
    second["artifact_creates"]=[artifact("ART_270_AR22_FOUR_FIELD_SAMPLE",270,"AR-22四字段汇总来源与三笔限定抽样复算表","due_diligence_record",["four_fields","batch_id","source_index","three_samples","bank_posting","approved_cap","balance_recalculation"],["verify_ar22_four_field_summary","use_as_evidence_within_scope"],list(second["participants"])),artifact("ART_270_AR22_ACCESS_EXPORT_LOG",270,"AR-22只读访问打印计数与编号摘录交付日志","access_log",["named_reviewer","session_window","queries","print_counter","page_count","numbered_extract","delivery_receipt","account_closed"],["record_ar22_scoped_delivery","use_as_evidence_within_scope"],list(second["participants"]))]
    second["artifact_refs"]=[{"artifact_id":"ART_269_AR22_IDENTITY_SCOPE_DECISION","timeline_scope":"current","display_name":"AR-22具名核验员与四字段访问范围决定","purpose":"限制账号身份、字段和禁止整库导出","required_permission":"set_ar22_access_scope","scope_assertion":"只读访问不产生继续持有整库副本的权利"},{"artifact_id":"ART_268_MG6_BOARD_DECISION","timeline_scope":"current","display_name":"MG-6交叉担保否决与限额替代额度表决决定","purpose":"确认贷前核验仅服务获准的单一场馆融资","required_permission":"set_mg6_financing_scope","scope_assertion":"不得扩张到个人资产或其他场馆"}]


def main() -> None:
    events = load(EVENTS_PATH)
    cards = load(CARDS_PATH)
    synopses = load(SYNOPSES_PATH)
    for path in (EVENTS_PATH, CARDS_PATH, SYNOPSES_PATH):
        backup = path.with_suffix(path.suffix + ".pre_v14_20260823")
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
    event_map = {item["cluster_id"]: item for item in events}
    repair_ec105(event_map["EC105"])
    repair_ec106(event_map["EC106"])
    card_map = {int(item["chapter_id"]): item for item in cards}
    synopsis_map = {int(item["chapter_id"]): item for item in synopses}
    repair_ec107(event_map["EC107"])
    repair_ec108(event_map["EC108"])
    repair_ec109(event_map["EC109"])
    repair_ec110(event_map["EC110"])
    repair_ec111(event_map["EC111"])
    repair_ec112(event_map["EC112"])
    repair_ec113(event_map["EC113"])
    repair_ec114(event_map["EC114"])
    repair_ec115(event_map["EC115"])
    repair_ec116(event_map["EC116"])
    repair_ec117(event_map["EC117"])
    repair_ec118(event_map["EC118"])
    repair_ec119(event_map["EC119"])
    repair_ec120(event_map["EC120"])
    repair_ec121(event_map["EC121"])
    repair_ec122(event_map["EC122"])
    repair_ec123(event_map["EC123"])
    repair_ec124(event_map["EC124"])
    repair_ec125(event_map["EC125"])
    repair_ec126(event_map["EC126"])
    repair_ec127(event_map["EC127"])
    repair_ec128(event_map["EC128"])
    repair_ec129(event_map["EC129"])
    repair_ec130(event_map["EC130"])
    repair_ec131(event_map["EC131"])
    repair_ec132(event_map["EC132"])
    repair_ec133(event_map["EC133"])
    repair_ec134(event_map["EC134"])
    repair_ec135(event_map["EC135"])
    canonical_pool = {
        item.get("character_id"): deepcopy(item)
        for source_event in events
        for item in source_event.get("canonical_cast") or []
        if item.get("character_id")
    }
    event_map["EC120"]["canonical_cast"] = [
        canonical_pool[character_id]
        for character_id in ("CHAR_026AC753E27A", "CHAR_4E24DD1EEE76", "CHAR_87B8E75FFF6F")
        if character_id in canonical_pool
    ]
    event_map["EC120"]["main_character_ids"] = [
        item["character_id"] for item in event_map["EC120"]["canonical_cast"]
    ]
    event_map["EC133"]["canonical_cast"] = [
        canonical_pool[character_id]
        for character_id in ("CHAR_026AC753E27A", "CHAR_87B8E75FFF6F", "CHAR_B04A992A7F99")
        if character_id in canonical_pool
    ]
    event_map["EC133"]["main_character_ids"] = [
        item["character_id"] for item in event_map["EC133"]["canonical_cast"]
    ]
    event_map["EC134"]["canonical_cast"] = [
        canonical_pool[character_id]
        for character_id in ("CHAR_026AC753E27A", "CHAR_4E24DD1EEE76", "CHAR_87B8E75FFF6F")
        if character_id in canonical_pool
    ]
    event_map["EC134"]["main_character_ids"] = [
        item["character_id"] for item in event_map["EC134"]["canonical_cast"]
    ]
    event_map["EC135"]["canonical_cast"] = [
        canonical_pool[character_id]
        for character_id in ("CHAR_026AC753E27A", "CHAR_4E24DD1EEE76", "CHAR_87B8E75FFF6F")
        if character_id in canonical_pool
    ]
    event_map["EC135"]["main_character_ids"] = [item["character_id"] for item in event_map["EC135"]["canonical_cast"]]
    # Keep repaired clusters inside the compiler's closed taxonomies.  These
    # labels describe the dominant narrative function, while the more exact
    # technical procedure remains in resolution_signature and artifacts.
    enum_normalizations = {
        "EC114": ("finance_business", "financial_counter"),
        "EC115": ("health_safety", "teamwork"),
        "EC116": ("legal_procedure", "legal_evidence"),
        "EC118": ("legal_procedure", "legal_evidence"),
        "EC119": ("finance_business", "financial_counter"),
        "EC120": ("performance", "teamwork"),
    }
    for cluster_id, (event_type, solution_type) in enum_normalizations.items():
        event_map[cluster_id]["event_type"] = event_type
        event_map[cluster_id]["solution_type"] = solution_type
    # Migrate stale downstream references to the scoped artifacts that now
    # actually exist; never leave deleted万能协议/光学日志 IDs dangling.
    artifact_migrations = {
        "ART_237_OPTICAL_LOG": ("ART_238_ACTUAL_ACOUSTIC_BASELINE", "中央体育馆六点静态声学实测基线"),
        "ART_231_ERROR_SHARING_AGREEMENT": ("ART_240_LIMITED_PROTOCOL_ACCEPTANCE", "中央体育馆两次彩排有限复测规程"),
        "ART_247_SILENT_WAVELOG": ("ART_238_ACTUAL_ACOUSTIC_BASELINE", "中央体育馆六点静态声学实测基线"),
        "ART_249_PAPER_BATCH_REPORT": ("ART_249_LATE_COVER_SEPARATION", "SB-83-6后制封面与正文分套记录"),
        "ART_255_MICROFILM_COPY": ("ART_256_FND_RP_83_09_CHAIN", "FND-RP-83-09申请批准工单交付四段链"),
        "ART_256_HANDWRITTEN_NOTE": ("ART_256_FUND_COPY_SCOPE_DECISION", "基金三张票据索引校对副本范围决定"),
        "ART_259_MICROFILM_BATCH": ("ART_260_PL83_28_REPRESENTATION_SCOPE", "PL-83-28原页与1986缩微摘要表示层级决定"),
        "ART_269_OFFLINE_LOG": ("ART_270_AR22_ACCESS_EXPORT_LOG", "AR-22只读访问打印计数与编号摘录交付日志"),
        "ART_270_PROMOTION_CERTIFICATE": ("ART_270_AR22_ACCESS_EXPORT_LOG", "AR-22只读访问打印计数与编号摘录交付日志"),
    }
    artifact_migration_clusters: set[str] = set()
    for downstream_event in events:
        for milestone_item in downstream_event.get("two_chapter_structure") or []:
            for ref in milestone_item.get("artifact_refs") or []:
                old_id = ref.get("artifact_id")
                if old_id in artifact_migrations:
                    artifact_migration_clusters.add(str(downstream_event["cluster_id"]))
                    new_id, display_name = artifact_migrations[old_id]
                    ref["artifact_id"] = new_id
                    ref["display_name"] = display_name
                    ref["scope_assertion"] = "仅按新文书明示范围引用，不恢复旧万能权限"
                    if old_id == "ART_249_PAPER_BATCH_REPORT":
                        ref["purpose"] = "只证明后制封面与正文需分套评价，不主张纸质介质绝对优先"
                    if old_id == "ART_255_MICROFILM_COPY":
                        ref["purpose"] = "只证明FND-RP-83-09的申请、批准、一次工单与交付范围，不主张物理介质绝对优先"
                    if old_id == "ART_256_HANDWRITTEN_NOTE":
                        ref["purpose"] = "只引用三张遮蔽索引校对副本的既定范围，不把手写批注当成万能定伪依据"
                    if old_id == "ART_259_MICROFILM_BATCH":
                        ref["purpose"] = "只引用PL-83-28原页与1986缩微摘要的层级边界，不主张胶片或原纸天然优先"
                    if old_id == "ART_269_OFFLINE_LOG":
                        ref["purpose"] = "只引用AR-22本次具名只读访问、打印计数和交付范围，不证明资料库绝对安全"
                    if old_id == "ART_270_PROMOTION_CERTIFICATE":
                        ref["purpose"] = "只引用AR-22本次访问交付日志，不证明黛安娜或任何人员获得晋升与财务任命"
    # Preserve the downstream customs dependency with the newly created,
    # correctly scoped passive-structure inspection rather than the deleted
    # all-purpose optical certificate.
    for item in event_map["EC111"].get("two_chapter_structure") or []:
        for ref in item.get("artifact_refs") or []:
            if ref.get("artifact_id") == "ART_217_OPTICAL_CERTIFICATE":
                ref.update({
                    "artifact_id": "ART_218_PASSIVE_OPTICS_INSPECTION",
                    "display_name": "无源光学结构独立检视单",
                    "purpose": "只证明该组件为无源光学结构且不含电子元件",
                    "required_permission": "verify_passive_optical_structure",
                    "scope_assertion": "不得扩张为性能、湿度或海关最终结论",
                })
    # EC108 correctly advances to the following business day.  The source plan
    # had left seven subsequent current-timeline cards on 10-22; lift only those
    # stale exact-date fields so the authoritative chronology does not regress.
    date_lift_clusters: set[str] = set()
    for event in events:
        for item in event.get("two_chapter_structure") or []:
            chapter_id = int(item.get("chapter_id") or 0)
            if 217 <= chapter_id <= 223 and item.get("timeline_start") == "1991-10-22":
                item["timeline_start"] = "1991-10-23"
                if item.get("timeline_end") == "1991-10-22":
                    item["timeline_end"] = "1991-10-23"
                if isinstance(item.get("detailed_synopsis"), str):
                    item["detailed_synopsis"] = item["detailed_synopsis"].replace(
                        "1991年10月22日", "1991年10月23日"
                    )
                date_lift_clusters.add(str(event["cluster_id"]))
            if 227 <= chapter_id <= 239 and item.get("timeline_start") == "1991-10-23":
                item["timeline_start"] = "1991-10-24"
                if item.get("timeline_end") == "1991-10-23": item["timeline_end"] = "1991-10-24"
                if isinstance(item.get("detailed_synopsis"), str): item["detailed_synopsis"] = item["detailed_synopsis"].replace("1991年10月23日", "1991年10月24日")
                date_lift_clusters.add(str(event["cluster_id"]))
            if 241 <= chapter_id <= 247 and item.get("timeline_start") == "1991-10-24":
                item["timeline_start"] = "1991-10-25"
                if item.get("timeline_end") == "1991-10-24": item["timeline_end"] = "1991-10-25"
                if isinstance(item.get("detailed_synopsis"), str): item["detailed_synopsis"] = item["detailed_synopsis"].replace("1991年10月24日", "1991年10月25日")
                date_lift_clusters.add(str(event["cluster_id"]))
            if 245 <= chapter_id <= 248 and item.get("timeline_start") == "1991-10-25":
                item["timeline_start"] = "1991-10-26"
                if item.get("timeline_end") == "1991-10-25": item["timeline_end"] = "1991-10-26"
                if isinstance(item.get("detailed_synopsis"), str): item["detailed_synopsis"] = item["detailed_synopsis"].replace("1991年10月25日", "1991年10月26日")
                date_lift_clusters.add(str(event["cluster_id"]))
    repaired_cluster_ids = (
        "EC105", "EC106", "EC107", "EC108", "EC109", "EC110", "EC111", "EC112", "EC113", "EC114", "EC115", "EC116", "EC117", "EC118", "EC119", "EC120", "EC121", "EC122", "EC123", "EC124", "EC125", "EC126", "EC127", "EC128", "EC129", "EC130", "EC131", "EC132", "EC133", "EC134", "EC135",
        *sorted(artifact_migration_clusters),
        *sorted(date_lift_clusters - {"EC109", "EC110", "EC111", "EC112", "EC113", "EC114", "EC115", "EC116", "EC117", "EC118", "EC119", "EC120"}),
    )
    for cluster_id in repaired_cluster_ids:
        event = event_map[cluster_id]
        for item in event["two_chapter_structure"]:
            chapter_id = int(item["chapter_id"])
            sync_card_from_milestone(card_map[chapter_id], event, item)
            card_map[chapter_id]["timeline_start"] = item["timeline_start"]
            card_map[chapter_id]["timeline_end"] = item["timeline_end"]
            card_map[chapter_id]["timeline_years"] = str(event.get("timeline_years") or item["timeline_start"][:4])
            card_map[chapter_id]["character_lifecycle"] = lifecycle(card_map[chapter_id])
            card_map[chapter_id]["state_transitions"] = deepcopy(event["state_transitions"] if chapter_id % 2 == 0 else [])
            card_map[chapter_id]["state_changes"] = deepcopy(card_map[chapter_id]["state_transitions"])
            card_map[chapter_id]["must_resolve_this_chapter"] = deepcopy(card_map[chapter_id]["state_transitions"])
            card_map[chapter_id]["source_milestone_sha256"] = digest(item)
            card_map[chapter_id]["source_event_sha256"] = digest(event)
            target = synopsis_map[chapter_id]
            target.clear()
            target.update(deepcopy(card_map[chapter_id]))
            target.pop("character_lifecycle", None)
            target.pop("active_costs", None)
            target.pop("cost_resolutions", None)
    # Event hashes changed after card compilation only if cards are embedded nowhere;
    # refresh all four cards against the final event object.
    for cluster_id in repaired_cluster_ids:
        event = event_map[cluster_id]
        for item in event["two_chapter_structure"]:
            card = card_map[int(item["chapter_id"])]
            card["source_milestone_sha256"] = digest(item)
            card["source_event_sha256"] = digest(event)
            synopsis_map[int(item["chapter_id"])]["source_milestone_sha256"] = card["source_milestone_sha256"]
            synopsis_map[int(item["chapter_id"])]["source_event_sha256"] = card["source_event_sha256"]
    write(EVENTS_PATH, events)
    write(CARDS_PATH, cards)
    write(SYNOPSES_PATH, synopses)
    report = {
        "version": "continuation_plan_v14_20260823",
        "repaired_clusters": ["EC105", "EC106", "EC107", "EC108", "EC109", "EC110", "EC111", "EC112", "EC113", "EC114", "EC115", "EC116", "EC117", "EC118", "EC119", "EC120", "EC121", "EC122", "EC123", "EC124", "EC125", "EC126", "EC127", "EC128", "EC129", "EC130", "EC131", "EC132", "EC133", "EC134", "EC135"],
        "repaired_chapters": [209, 210, 211, 212, 213, 214, 215, 216, 217, 218, 219, 220, 221, 222, 223, 224, 225, 226, 227, 228, 229, 230, 231, 232, 233, 234, 235, 236, 237, 238, 239, 240, 241, 242, 243, 244, 245, 246, 247, 248, 249, 250, 251, 252, 253, 254, 255, 256, 257, 258, 259, 260, 261, 262, 263, 264, 265, 266, 267, 268, 269, 270],
        "issues": [
            "EC105与EC106重复取得医疗自主权",
            "EC105/EC106日期出现1987、1989、1991冲突",
            "苏菲亚被误写为医生且参与者重复",
            "承诺卡被扩权为医疗授权",
            "色带证据在相邻事件重复使用",
            "1991年出现下载、开源代码等年代错位",
            "EC105角色晋升错误绑定到麦珂character_id",
            "EC107把苏菲亚误写成拥有重生记忆",
            "EC107重复第207章色带证据且敌情图谱从127人倒退为50人",
            "EC107日期在1987、1988、1991之间冲突",
            "EC108第三次重复暴雨、备用光路和医疗权夺回",
            "EC108让非医师莉薇娅实施急救并把前世录音细节当成今生证据",
            "EC108引用错号文书且从EC107财务钩子无故跳回已结算医疗权",
            "EC109再次重复EC106的暴雨切光与永久叫停权结算",
            "EC109未承接RV设备费用且把前世阈值直接当今生技术证明",
            "EC110第四次重复医疗控制权夺回并把家属写成成年主角的绝对决定者",
            "EC110再次扩权观众承诺卡、重复色带证据且冒用不存在的卫生行政权限",
            "EC111误写X光机可确认电子信号且把结构检视单当作海关放行证",
            "EC111让已多次失信的巴里到此才首次信誉受损并重复媒体羞辱会",
            "EC112再次重复打字机色带证据、精神污名与新闻会公开羞辱",
            "EC112未承接初声基金代缴保证金且包含远程望远镜等不可信动作",
            "EC113第五次重复三方急救令、舞台晕厥和观众通道反杀",
            "EC113遗漏上一簇双重评分票且再次把关系推到绝对授权",
            "EC114重复暴雨、七路光路切换、打字机色带、媒体羞辱和永久标准",
            "EC114未承接上一簇双规格采购钩子且错误让主角取得绝对技术权",
            "EC115用入场券强迫观众围查并从单个拼写错误夸大为全国纠错",
            "EC115重复公众承诺卡和医疗控制权，且错误授予麦珂一票否决与绝对权威",
            "EC116重复EC111的海关X光、无源光学通关与巴里首次失信",
            "EC116依赖监控线路恰好黑屏帮助主角且未承接SG-271封志异常钩子",
            "EC117第三次重复公众查牌、三方急救签字和全国纠错行动",
            "EC117未承接承运异常费错挂采购行且把局部错误夸张成全场危机",
            "EC118再次重复打字机色带、伪造精神报告、强制隔离和媒体清算",
            "EC118把公证人意见夸张为刑事定伪与执业吊销且未承接PX-14授权钩子",
            "EC119再次重复暴雨、备用光路与演出零秒切换",
            "EC119使用万人敲击抵消建筑共振的不可信声学反杀且未承接未签收勘测发票",
            "EC120以情绪压力签署笼统误差共担协议并错误绑定民事伴侣关系",
            "EC120把局部场馆流程夸大为全球巡演标准、依赖媒体统一口径且未处理测量不确定度",
            "EC121试图从复印件纸张与墨迹直接鉴定原件年份并把可疑越级写成伪造",
            "EC121让法官排斥全部电子证据、因缺1977载体判对手彻底败诉且无关插入民事伴侣登记",
            "EC122在十分钟内完成民事伴侣登记与复杂双轨信托，缺少独立审阅和真实同意",
            "EC122把私人信托写成自动挡回税务冻结的万能盾牌并宣称资产物理分散",
            "EC123再次重复1977磁带、声波污染定伪、三十七位医师日志和新闻发布会公信力清算",
            "EC123把影印代码直接当受让实体和票据所有权，并在第246章重复EC122伴侣信托签署",
            "EC124重复EC119的暴雨、万人敲击抵消建筑共振和局部流程上升州级法规",
            "EC124依靠观众证言粉碎噪音诉讼且未承接SB-83-6预付款与S.R.授权钩子",
            "EC125把后制封面直接当正文伪造、把境外服务副本接收方直接认定为洗钱壳公司",
            "EC125以离线存档和维克多承认失败宣称基金控制权彻底安全，结算越界",
            "EC126再次重复墨水定年、三十七份医师日志、公开展示、媒体停刊和法官当场定伪",
            "EC126未承接SF-27发票副本、采购订单与原始存根钩子，并把黛安娜写成材料鉴定人",
            "EC127重复EC122的伴侣登记和双轨信托，并虚构海湾州法第14条与两周期限",
            "EC127在一天内宣称完成瑞士、开曼资产物理转移且任何实体无法冻结，成本与法律边界失真",
            "EC127未承接P07演员影像同意表及后来家庭联合声明扩权钩子",
            "EC128把FR-12共页直接当成统一权利转让，并再次把有限影印服务夸张为历史数据控制权",
            "EC128让黛安娜撰写联邦法律瑕疵报告，以缺授权书在五日内冻结账户并完成永久裁决",
            "EC128重复纸质介质绝对优先叙事，未核原申请、批准、工单和实际交付范围",
            "EC129重复EC119的暴雨、万人敲击和建筑共振反杀，并把观众动作当成声学验证",
            "EC129依赖媒体实时数据、墨水未干和市政发布会宣告作品法律地位，结算层级失真",
            "EC129未承接W-52、SRH-28返还款与场馆接收日期空白钩子",
            "EC130再次重复1977录音、医师日志、墨水鉴定和联邦听证会定胜负",
            "EC130把微缩胶片写成天然无篡改的绝对证据，并让黛安娜越权演示声学与证据鉴定",
            "EC130依赖维克多持湿布冲庭的滑稽失控，未承接PL-83-28原页与1986缩微副本差异",
            "EC131虚构审计第45天必须提交原件规则和声学锚定保险柜，并在家庭会议重复信托协议",
            "EC131宣称复印件法律上彻底失效、基金获得复印件豁免且代理资格暂停，程序结算越界",
            "EC131没有明确1991至1993时间跳跃，也没有承接MV-4原件优先草案的媒介中立修订",
            "EC132虚构纸张声波频率归档测试和刺耳警报，以不存在的扫描程序替代复印作业链",
            "EC132再次宣称物理原件唯一法律效力、官方定性伪造和对方信誉瞬间崩塌",
            "EC132把黛安娜错误晋升为基金财务合规负责人，未承接CT-17四页三页与两次曝光钩子",
            "EC133再次虚构声学指纹比对和全程直播，并用对手不懂技术制造群嘲",
            "EC133把媒体更正夸张为公众永久倒向、奥瑞恩永无洗白机会和银行争抢托管",
            "EC133把维克多·兰斯无来源改名为维克多·斯特林，且未承接PR-19三页摘录公共更正",
            "EC134第三次重复伴侣登记与双轨信托，并虚构第45条赋予瑟琳娜不可逆绝对否决权",
            "EC134把舆论风险直接变成全资产交叉担保理由，未拆出担保对象、期限、追索和退出条件",
            "EC134再次使用无来源的维克多·斯特林，并把现实融资选择写成奥瑞恩阴谋彻底破产与基金永久安全",
            "EC135依赖黑客团队闯入预设空壳服务器的诱捕桥段，把权限错误写成对手公开受辱",
            "EC135再次把微缩胶片和物理介质写成天然不可篡改、唯一法律有效，违背MV-4媒介中立规则",
            "EC135让黛安娜越权接管基金财务合规并再次使用无来源的维克多·斯特林，未承接AR-22访问申请",
        ],
    }
    write(REPORT_PATH, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

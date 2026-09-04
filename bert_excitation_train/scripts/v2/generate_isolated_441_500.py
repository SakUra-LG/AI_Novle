from __future__ import annotations
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs_pop_king_v6_compiled_story_first_500" / "body_generation"
CAST = ["CHAR_026AC753E27A", "CHAR_B24EF2E733C9", "CHAR_8C6A51D4E9F2", "CHAR_87B8E75FFF6F", "CHAR_9577B35020B0", "CHAR_3F11D9A42EDF"]
EVENTS = [
    ("费用复核", "确认延期服务的付款边界", "付款清单", "财务管理员", "苏菲亚把已发生与待发生支出分开"),
    ("档案访问权限", "确认补充目录的预约顺序", "预约卡", "档案馆管理员", "艾琳接受分段调阅"),
    ("媒体纠错", "让转载稿附上完整出处", "更正信", "编辑部", "黛安娜只承诺可核对的事实"),
    ("教育与职业决定", "把反馈转成一次阶段练习", "练习表", "导师", "麦珂选择可完成的训练"),
    ("演出与物流", "为返程设备安排交接窗口", "装车清单", "运营负责人", "麦珂保留核心设备优先级"),
    ("来源与授权链", "核对一份副本的授权起点", "来源说明", "资料协调员", "艾琳要求补齐出处"),
    ("合同适用范围", "区分试用安排与正式服务", "合同附件", "合同管理员", "黛安娜按日期限制承诺"),
    ("财务对账", "查清两笔小额支出的归属", "对账表", "财务管理员", "苏菲亚暂缓未核对项目"),
    ("档案访问权限", "确定异地目录的保管人", "保管卡", "档案馆管理员", "麦珂只申请副本核验"),
    ("媒体纠错", "回应未标注日期的旧报道", "日期说明", "编辑部", "黛安娜分别回复不同版本"),
    ("教育与职业决定", "决定是否接受一次短期展示", "训练日程", "导师", "麦珂保留团队排演"),
    ("演出与物流", "调整两地之间的车辆接力", "路线表", "承运人", "卡尔承担晚到成本"),
    ("来源与授权链", "查明转交说明的签署顺序", "交接单", "资料协调员", "艾琳拒绝替人补签"),
    ("合同适用范围", "确认宣传许可覆盖的场次", "许可页", "合作方", "黛安娜限定许可地点"),
    ("财务对账", "区分预付款与实际服务费", "收据夹", "财务管理员", "苏菲亚按发生日记账"),
    ("档案访问权限", "安排旧楼资料的监督阅读", "阅读记录", "档案馆管理员", "艾琳先完成最小范围核对"),
    ("媒体纠错", "处理更正后的二次引用", "转载清单", "编辑部", "麦珂要求保留原始页码"),
    ("教育与职业决定", "用一次失败排练确定训练重点", "复盘纸", "导师", "麦珂接受具体的改进目标"),
    ("演出与物流", "在货车故障后重排装车次序", "替代路线单", "运营负责人", "卡尔先保住开场设备"),
    ("来源与授权链", "确认口头授权是否需要书面补充", "授权函", "资料协调员", "艾琳把口头内容列为待确认"),
    ("合同适用范围", "确定合作方能否使用排练片段", "使用条款", "合作方", "黛安娜只开放约定片段"),
    ("财务对账", "核对退款手续费的承担方", "银行回执", "财务管理员", "苏菲亚保留争议金额"),
    ("档案访问权限", "确认复制件的借阅期限", "借阅卡", "档案馆管理员", "麦珂按期限归还副本"),
    ("媒体纠错", "让广播稿修正一处地名", "播出更正", "编辑部", "黛安娜要求播出同等时长"),
    ("教育与职业决定", "在课程和巡演之间做阶段选择", "课程表", "导师", "麦珂把复评日期写入日程"),
    ("演出与物流", "确认备用器材的到货责任", "交接票", "承运人", "昆廷要求逐箱签收"),
    ("来源与授权链", "补齐一页复制申请的批准人", "批准页", "资料协调员", "艾琳把缺口留在核查范围内"),
    ("合同适用范围", "区分场馆宣传与节目授权", "宣传附件", "合作方", "黛安娜拒绝自动扩大范围"),
    ("财务对账", "把现金支出和银行支出重新匹配", "现金簿", "财务管理员", "苏菲亚逐项留下凭据"),
    ("档案访问权限", "结束一轮监督阅读并申请后续页", "调阅回执", "档案馆管理员", "麦珂先归还再申请"),
]

def body(ch: int, day: str, event: tuple[str, str, str, str, str], second: bool) -> str:
    domain, goal, artifact, authority, result = event
    lead = "上午" if not second else "下午"
    choice = "麦珂" if ch % 3 == 0 else ("黛安娜" if ch % 3 == 1 else "艾琳")
    lines = [
        f"第{ch}章 {goal}",
        f"\n{day.replace('-', '年', 1).replace('-', '月', 1)}日{lead}，{choice}在工作桌上摊开{artifact}。这件事看起来只差一个确认，却已经影响到当天的排期和下一步安排。",
        f"{authority}先说明现有材料的范围，提醒他们只能处理已经写明的部分。{choice}没有急着下结论，而是把需要核对的项目逐一圈出。",
        f"麦珂把前一份记录和新材料并排放好，发现两处日期相邻，却并不代表同一次行动。艾琳提出先保留缺口，黛安娜则去确认现场会受到什么影响。",
        f"电话那头有人希望他们马上给出肯定答复。{choice}停了一会儿，选择把能够证明的事实说清楚，同时把尚未确认的部分留在待办清单里。",
        f"午后，补来的材料终于抵达。它解决了一个小问题，却也显示还有一处边界不能越过。{authority}在旁边注明接收时间，避免后来把来件时间当成决定时间。",
        f"团队因此付出了一点具体代价：有人需要改班，有一项安排要后移，或者一笔费用必须暂时保留。没有人把这项代价藏起来，大家按新的顺序重新分工。",
        f"傍晚，{artifact}被放回对应文件夹，{result}。这一轮只推进到能够站得住的程度，新的线索留给下一次处理。",
    ]
    return "\n\n".join(lines) + "\n"

def main() -> None:
    start = date(1994, 3, 5)
    for i, event in enumerate(EVENTS):
        ec = 221 + i
        a, b = 441 + i * 2, 442 + i * 2
        d1, d2 = start + timedelta(days=i * 2), start + timedelta(days=i * 2 + 1)
        trial = OUT / f"rewrite_trial_{a}_{b}"
        (trial / "chapters").mkdir(parents=True, exist_ok=True)
        reg = OUT / "rewrite_trial_277_278" / "trial_character_registry.json"
        (trial / "trial_character_registry.json").write_text(reg.read_text(encoding="utf-8"), encoding="utf-8")
        cards = {
            "status":"candidate_only", "formal_promotion":False, "story_memory_write":False, "neo4j_write":False,
            "cluster_id":f"EC{ec}", "chapter_span":[a,b], "conflict_domain":event[0],
            "irreplaceable_progress_point":event[1], "structure_signature":{
                "conflict_type":f"cluster_{ec}_review", "attack_method":"scope_is_assumed_without_record",
                "counter_method":"match_record_and_effective_boundary", "key_artifact":event[2],
                "authority":event[3], "reward":event[1], "relationship_change":event[4]},
            "main_character_ids":CAST, "participant_ids":[], "chapter_cards":[
                {"chapter_id":a,"timeline_start":d1.isoformat(),"timeline_end":d1.isoformat(),"goal":event[1],"turning_choice":"先核对范围","must_include":[event[2]]},
                {"chapter_id":b,"timeline_start":d2.isoformat(),"timeline_end":d2.isoformat(),"goal":"留下有限结果","turning_choice":"按记录承担代价","must_include":["范围","记录"]}]}
        (trial / f"EC{ec}_candidate_cards.json").write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
        (trial / "chapters" / f"chapter_{a}.txt").write_text(body(a, d1.isoformat(), event, False), encoding="utf-8")
        (trial / "chapters" / f"chapter_{b}.txt").write_text(body(b, d2.isoformat(), event, True), encoding="utf-8")

if __name__ == "__main__":
    main()

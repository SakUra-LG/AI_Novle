"""Shared V2 theme constraints for the stagflation rebirth project."""

from __future__ import annotations

from typing import Any, Dict, List


THEME_TITLE = "滞胀前夜的逆周期教授"
THEME = "欧美风格重生经济年代爽文：重生到美国经济滞胀时代"
BACKGROUND = "1968-1979年美国：名校经济系、华尔街、政策圈、美元脱锚、石油危机、股灾、高利率与普通人的通胀困境"
MAIN_PROTAGONIST = "丹尼尔·惠特曼"
PROTAGONISTS = [MAIN_PROTAGONIST]

CORE_PREMISE = (
    "主角前世是研究1970年代美国滞胀的现代美国经济学者，临死前仍被嘲笑"
    "“只会写历史，不会赚钱”；重生后回到1968年，成为名校年轻助理教授。"
    "他知道大通胀、美元脱锚、石油危机、股灾和高利率将接连到来，"
    "因此用固定利率债务、实物资产、能源设备、仓储、农地与铁路货运合同完成逆周期布局。"
)

TIMELINE_ANCHORS = [
    "1968年：美国表面繁荣，漂亮股票受追捧，政策圈仍相信通胀可控。",
    "1971年：美元脱锚/尼克松冲击成为第一轮预言兑现。",
    "1973年：石油危机爆发，能源与物流资产成为市场命脉。",
    "1974年：股市崩盘，曾经嘲笑主角的基金经理和权威派破产或求助。",
    "1979年：提前去杠杆，避开高利率绞杀。",
]

ASSET_AND_CONFLICT_ANCHORS = [
    "卖掉热门成长股和漂亮股票",
    "借固定利率贷款",
    "买下农地、仓库、能源设备厂",
    "锁定铁路货运合同和能源物流资源",
    "在学术会议上提出“滞胀时代不可避免”并被权威教授羞辱",
    "面对华尔街、银行、政策圈和媒体的嘲笑、打压与利益诱惑",
]

FINAL_PAYOFF = (
    "终局高潮不是单纯暴富，而是当权贵要求主角隐瞒下一次危机时，"
    "他选择公开预警，把普通人从通胀陷阱里救出来，完成“危机预言者”到公共责任承担者的转变。"
)

HARD_CONSTRAINTS = [
    "全书必须固定在美国1968-1979年前后，不得换成现代都市、娱乐圈、医疗阴谋、豪门婚恋、仙侠、玄幻或科幻世界观。",
    "主角必须是男性现代美国经济学者重生为1968年名校年轻助理教授，不得改成女主、歌手、医生、总裁妻子或宫斗角色。",
    "叙事核心是历史经济信息差、逆周期投资、学术/资本/政策冲突和公共预警，不是传统查案复仇、医疗取证或恋爱宅斗。",
    "所有情节组都要围绕滞胀时代的连续历史节点推进：1968预判、1971美元脱锚、1973石油危机、1974股灾、1979高利率。",
    "主角可以利用前世知识提前布局，但禁止开挂式万能预测；每个收益都要有经济逻辑、风险代价、舆论压力和现实执行成本。",
    "终局必须兑现公开预警保护普通人的价值选择，禁止把结尾写成只为个人财富、权贵结盟或新神秘Boss。",
    "禁止系统、异能、修仙、玄学、神秘人送证据、匿名邮件天降关键材料、突然出现未铺垫的终极反派。",
    "人物、机构、场景应呈现欧美商业/学院/政策语境：大学经济系、学术会议、华尔街基金、银行信贷、农场、仓储、能源设备厂、铁路货运、媒体听证或政策辩论。",
]

FORBIDDEN_ELEMENTS = [
    "现代都市医疗阴谋",
    "病房被害",
    "渣男丈夫",
    "豪门总裁",
    "娱乐圈版权战",
    "女团/男团",
    "直播网暴",
    "修仙玄幻",
    "系统提示音",
    "神秘司机",
    "神秘人递U盘",
    "匿名邮件决定性爆料",
    "中国式家族宅斗",
]


def constraints_text() -> str:
    """Return a compact prompt block shared by all V2 generation stages."""
    return "\n".join(
        [
            f"【固定大主题】{THEME_TITLE}：{THEME}",
            f"【固定背景】{BACKGROUND}",
            f"【主角锁定】{MAIN_PROTAGONIST}，男性，美国经济学者/1968年名校年轻助理教授。",
            f"【核心设定】{CORE_PREMISE}",
            "【历史节点】" + "；".join(TIMELINE_ANCHORS),
            "【资产与冲突锚点】" + "；".join(ASSET_AND_CONFLICT_ANCHORS),
            f"【终局价值】{FINAL_PAYOFF}",
            "【硬性限制】" + "；".join(HARD_CONSTRAINTS),
            "【禁止元素】" + "；".join(FORBIDDEN_ELEMENTS),
        ]
    )


def attach_theme_contract(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Attach the shared theme contract to generated cluster/card dictionaries."""
    obj["theme_contract"] = {
        "theme_title": THEME_TITLE,
        "theme": THEME,
        "background": BACKGROUND,
        "main_protagonist": MAIN_PROTAGONIST,
        "timeline_anchors": TIMELINE_ANCHORS,
        "hard_constraints": HARD_CONSTRAINTS,
        "forbidden_elements": FORBIDDEN_ELEMENTS,
        "final_payoff": FINAL_PAYOFF,
    }
    return obj


def protagonists_arg() -> str:
    return ",".join(PROTAGONISTS)


#!/usr/bin/env python3
"""Manually rebuild EC136-EC250 while freezing EC001-EC135.

This is a narrative architecture migration, not a second free-form model pass.
The manually curated beat catalogue below is the source of truth.  The script
only expands each beat into the event/card schemas expected by the body
generator and keeps all three public planning views synchronized.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bert_excitation_train.scripts.v2.pop_king_tail_manual_divisions_v1 import DIVISIONS

OUT = ROOT / "bert_excitation_train" / "outputs_pop_king_v6_compiled_story_first_500"
BIBLE = ROOT / "bert_excitation_train" / "data" / "pop_king_character_bible_v1.json"
VERSION = "v16_manual_chapter_divisions_20260827"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def replace_text_deep(value: Any, old: str, new: str) -> Any:
    """Replace one proven identity drift without touching unrelated metadata."""
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [replace_text_deep(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: replace_text_deep(item, old, new) for key, item in value.items()}
    return value


def normalize_frozen_identity_metadata(
    events: list[dict[str, Any]], cards: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Repair the EC131/132 Qwen alias collision; formal prose is unchanged."""
    canonical_id_repairs = {
        "CHAR_F618A85B98BB": "CHAR_B1C2D3E4F5A6",  # 巴里
        "CHAR_EB1F70C558F3": "CHAR_E1F2A3B4C5D6",  # 康拉德
        "CHAR_4E24DD1EEE76": "CHAR_EC7C1E1EB46F",  # 瑟琳娜
        "CHAR_B6BBF0D9B359": "CHAR_76E9E8359211",  # 维克多
        "CHAR_B04A992A7F99": "CHAR_8C6A51D4E9F2",  # 艾琳
        "CHAR_89E90D63A7E8": "CHAR_A1B2C3D4E5F6",  # 莉薇娅
        "CHAR_516678482F6C": "CHAR_C1D2E3F4A5B6",  # 莱昂
        "CHAR_B047AA73B9D5": "CHAR_B24EF2E733C9",  # 黛安娜
    }
    for old_id, canonical_id in canonical_id_repairs.items():
        events = replace_text_deep(events, old_id, canonical_id)
        cards = replace_text_deep(cards, old_id, canonical_id)
    events = replace_text_deep(events, "维克多·斯特林", "维克多·兰斯")
    cards = replace_text_deep(cards, "维克多·斯特林", "维克多·兰斯")
    event_map = {str(event.get("cluster_id")): event for event in events}
    for event in events:
        direction = event.get("source_event_direction")
        if isinstance(direction, str) and direction:
            event["source_event_direction_sha256"] = text_sha(direction)
    for card in cards:
        event = event_map.get(str(card.get("cluster_id")))
        if not event:
            continue
        card["source_event_sha256"] = sha(event)
        chapter_id = int(card.get("chapter_id") or 0)
        # The semantic compiler binds cards to two_chapter_structure, which is
        # the authoritative pair even when a legacy chapter_milestones mirror
        # is also present.
        milestone = next(
            (
                item for item in (event.get("two_chapter_structure") or [])
                if int(item.get("chapter_id") or 0) == chapter_id
            ),
            None,
        )
        if milestone is not None:
            card["source_milestone_sha256"] = sha(milestone)
    return events, cards


N = {
    "M": "麦珂·杰森", "D": "黛安娜·罗文", "I": "艾琳·沃特曼",
    "S": "瑟琳娜·凯德", "L": "莉薇娅·普莱斯", "V": "维克多·兰斯",
    "B": "巴里·布鲁姆", "Q": "昆廷·琼斯", "F": "莱昂·周",
    "A": "苏菲亚·罗德里格斯", "K": "卡尔·霍尔特", "T": "托马斯·布莱克",
    "C": "康拉德·莫里森", "MM": "玛莎·杰森", "J": "乔纳·杰森",
}


def beat(
    title: str, event_type: str, solution: str, point: str, artifact: str,
    location: str, authority: str, opponent: str, cast: str, choice: str,
    cost: str, gain: str, opposition: str = "villain",
) -> dict[str, Any]:
    return {
        "title": title, "event_type": event_type, "solution_type": solution,
        "point": point, "artifact": artifact, "location": location,
        "authority": authority, "opponent": opponent, "cast": list(cast),
        "choice": choice, "cost": cost, "gain": gain, "opposition_type": opposition,
    }


ARCS: list[dict[str, Any]] = [
    {
        "title": "空箱之后：初声基金的来源战", "start": "1993-09-18", "end": "1993-12-18",
        "goal": "承接第270章的BA-83-11与CR-41缺口，保住基金融资并找出维克多渗入授权链的第一只手。",
        "beats": [
            beat("空箱号", "legal_procedure", "legal_evidence", "从BA-83-11缺失箱号追到河湾镇档案馆的移交批次，只锁定复制申请经手岗位", "来源箱移交簿", "河湾镇档案馆收发室", "档案馆主管", "V", "MI", "麦珂拒绝把空箱号直接说成伪造", "团队为受限调阅多等一日", "得到原记录箱与申请页的可复核入口"),
            beat("缺席的签名", "contract_rights", "negotiation", "核对CR-41申请、复核、批准三栏，确认缺失的是节目部复核签名而非批准页", "CR-41权限分栏表", "节目部资料室", "节目部合规主任", "V", "MDI", "艾琳坚持技术意见不能替代授权意见", "摘录暂时退出节目排期", "只对该摘录取得有限程序保护", "institutional"),
            beat("十日边界", "contract_rights", "negotiation", "把内部财务核对与公开宣传拆成两种用途，拒绝一次复核自动扩权", "十日内部核对附录", "维斯特媒介合同室", "合同管理员", "V", "MDI", "黛安娜拒绝用合作窗口交换模糊签字", "宣传预热延后十日", "保住内部核对并留下公开用途重提入口"),
            beat("四十七份副本", "contract_rights", "strategic_withdrawal", "核对地域、份数和收件人，截住四十七份未列接收方的培训副本", "副本交付对象清单", "海湾剧院节目办公室", "节目部运营负责人", "B", "MDAK", "卡尔主动停掉已经装车的材料", "剧院承担重印费用", "未登记副本全部留库且正常节目不受牵连"),
            beat("三条账线", "finance_business", "financial_counter", "把设备预付款、退款和演出分成按日期拆开，找出一笔待核差额", "三线对账工作表", "初声基金财务室", "独立财务复核员", "V", "MAI", "苏菲亚拒绝替未核数字填平余额", "一笔采购款延期", "差额取得独立复核编号"),
            beat("重复入账不是赃款", "finance_business", "financial_counter", "查明待核差额来自重复预留与迟到银行回执，不借错误制造贪污指控", "银行回执联与冲销单", "河湾银行企业柜台", "银行复核主管", "V", "MA", "麦珂撤回自己过早写下的嫌疑判断", "失去一次低价采购窗口", "恢复真实余额并暴露谁曾利用时间差施压", "institutional"),
            beat("离岸受益人", "finance_business", "legal_evidence", "沿重复预留的付款指令找到维克多控制的离岸壳公司受益人申报", "受益所有人申报回函", "银湾州公司登记处", "登记处审查员", "V", "MAT", "托马斯要求只提交能证明控制关系的页码", "基金不能立即冻结全部争议款", "法院受理针对单笔指令的保全申请"),
            beat("九十日额度表决", "finance_business", "negotiation", "在不开放整库的前提下让债权委员会复算储备，保住MG-6九十日替代额度", "限定字段融资决议", "债权委员会会议厅", "债权委员会", "V", "MAK", "苏菲亚让债权人自行抽样而不替其选择", "基金接受更高监督成本", "融资以限定范围获批"),
            beat("被剪掉的条件句", "media_reputation", "media_counter", "纠正报纸把临时保全写成全面欺诈定罪的标题，公开完整条件句", "报纸勘误版样", "《银湾纪事》编辑部", "报社总编辑", "B", "MSA", "瑟琳娜拒绝公开私人往来换取头版", "报道热度下降且舆论仍有怀疑", "公众看到疑点、复核和裁决的区别"),
            beat("壳公司的退潮", "legal_procedure", "legal_evidence", "用受益人回函与付款指令使法院撤销离岸壳对基金的单笔控制主张，同时保留后续审理", "单笔控制权撤销令", "银湾商业法院", "商业法院法官", "V", "MDIAT", "麦珂接受法院只处理已证实的一笔指令", "维克多仍保有其他商业渠道", "初声基金跨过融资危机，维克多转向健康数据入口"),
        ],
    },
    {
        "title": "新声场：作品、巡演与成年人选择", "start": "1994-01-20", "end": "1995-09-10",
        "goal": "让麦珂在财务危机后重新以作品站稳，同时把合作、亲密关系和巡演安全写成各自独立的选择。",
        "beats": [
            beat("锁在母带盒里的副歌", "creation", "creative_breakthrough", "麦珂和昆廷从废弃副歌重写新专辑开场曲，并在试听前分清共同创作份额", "共同创作分轨单", "昆廷的模拟录音棚", "制作人委员会", "V", "MQI", "麦珂接受昆廷删掉他最舍不得的一段旋律", "首轮试听推迟", "新专辑获得可追溯的原创核心", "ally_resistance"),
            beat("和声署名", "contract_rights", "negotiation", "艾琳发现和声编排被唱片模板吞并，要求在母带交付前补足创作署名", "和声贡献确认页", "录音棚控制室", "唱片版权管理员", "V", "MIQ", "艾琳拒绝用感情关系换取无署名合作", "母带交付晚一周", "艾琳获得明确署名且不取得麦珂整首歌控制权"),
            beat("黛安娜的工作室", "creation", "market_result", "黛安娜把巡演服装样衣发展成独立工作室，拒绝成为基金附属部门", "样衣订单与独立报价单", "罗文服装工作室", "行业采购评审", "B", "MDK", "黛安娜选择外部客户而不是麦珂的独家订单", "麦珂失去随时调用她团队的便利", "黛安娜取得独立现金流和议价权", "ally_resistance"),
            beat("母带过海", "performance", "teamwork", "暴风令母带与舞台设备分路，团队用工作拷贝保住彩排而不冒险运输原件", "母带分路交接清单", "北湾港与巡演排练馆", "巡演调度中心", "B", "MIK", "卡尔主动放弃一场电视预热保护原母带", "宣传曝光减少", "正式彩排按时完成且母带全程可追踪", "technical"),
            beat("少唱一首", "health_safety", "safety_preemption", "升降台限位器不稳定时麦珂删掉最炫目的返场，而不是带故障演出", "返场删减安全决定", "灰桥体育馆", "场馆安全主管", "B", "MIK", "麦珂公开承认是自己选择缩短演出", "退还部分高价票差额", "观众安全与团队信任得到保全", "technical"),
            beat("票根上的第二价格", "fan_public_welfare", "market_result", "苏菲亚从歌迷票根发现黄牛二次加价链，建立实名但不收集无关隐私的换票台", "受限换票登记规则", "星火歌迷临时服务站", "票务仲裁员", "B", "MAF", "莱昂拒绝把全部歌迷名单交给基金", "团队无法一次封死所有黄牛", "受害歌迷获得退款入口，星火同盟形成雏形"),
            beat("星火不是应援部", "fan_public_welfare", "teamwork", "莱昂把星火同盟定位为独立歌迷互助组织，拒绝接受麦珂团队指挥", "星火同盟自治章程", "河岸社区礼堂", "社区组织登记员", "B", "MFA", "麦珂放弃任命同盟负责人", "公关团队失去一支可控宣传队", "歌迷获得独立监督票务与安全的组织"),
            beat("镜头外的答案", "romance", "relationship_choice", "瑟琳娜决定公开承认与麦珂交往，但划掉媒体要求披露的私人病历和住址", "联合采访边界卡", "银湾电视台化妆间", "电视台制片人", "B", "MSI", "麦珂接受瑟琳娜先回答与自己不同的问题", "两人同时承受舆论压力", "关系从秘密转为有边界的公开承担"),
            beat("不替她搬家", "family_relationship", "relationship_choice", "黛安娜拒绝为巡演永久搬迁，双方改为分段共同养育和独立工作安排", "共同养育排期备忘", "杰森家餐厅", "双方当事人", "B", "MDMM", "麦珂承认保护欲正在替别人做决定", "家庭团聚时间减少", "孩子与职业安排获得可复谈的边界", "family"),
            beat("分销商的百分之十二", "finance_business", "financial_counter", "维克多通过小股权分销商卡住新专辑上架，麦珂用独立门店预售证明市场而不让渡母带", "独立门店预售汇总", "银湾唱片交易会", "分销商协会", "V", "MQA", "麦珂接受首周销量会更慢", "失去全国同步铺货", "专辑以独立渠道回款并逼分销商恢复非独家上架"),
        ],
    },
    {
        "title": "被污染的曲线：健康数据与数字入口", "start": "1996-02-05", "end": "1997-12-12",
        "goal": "让对手从纸面控制转向数据污染，并建立不把算法、医生或媒体当作万能裁判的健康防线。",
        "beats": [
            beat("突然变坏的曲线", "health_safety", "teamwork", "艾琳发现巡演健康趋势图在没有新检查的日子连续恶化，先隔离数据源而非诊断麦珂", "健康数据来源矩阵", "独立健康管理室", "医疗数据管理员", "V", "MIC", "麦珂允许艾琳暂停他最依赖的趋势提醒", "团队暂时失去自动排练建议", "异常被限定在两个外部录入源", "technical"),
            beat("诊所没有授权上传", "health_safety", "legal_evidence", "逐家诊所核对同意书，确认一家外包录入商擅自上传摘要而非诊所伪造病历", "诊所授权回函组", "四家合作诊所", "独立医疗伦理委员会", "V", "MIC", "康拉德以顾问身份支持重查但不读取私人全档", "麦珂重新接受部分基础检查", "未经授权的数据流被暂停"),
            beat("同一台机器的两种刻度", "health_safety", "safety_preemption", "校准两台巡演体测设备，发现单位转换错误制造了假性恶化", "设备校准对照记录", "巡演医疗车", "持证设备工程师", "V", "MIK", "麦珂承认自己因前世恐惧过度怀疑医生", "他向医疗团队公开道歉", "排练负荷按真实指标重排", "technical"),
            beat("保险公司的红灯", "finance_business", "negotiation", "保险公司用污染曲线提高保费，托马斯迫使其披露风险评分所用字段和申诉期限", "风险评分字段说明", "北陆保险听证室", "保险申诉委员会", "V", "MIT", "麦珂拒绝隐瞒真实旧伤换取低保费", "巡演先支付临时附加费", "污染字段被排除并启动重新定价"),
            beat("重训还是删库", "health_safety", "strategic_withdrawal", "团队选择保留污染样本用于审计、另建干净训练集，而不是删除全部历史", "双库隔离方案", "初声基金数据室", "独立模型审计员", "V", "MIA", "苏菲亚拒绝为了漂亮结果清洗不利记录", "新模型延期上线", "健康建议恢复可解释来源", "technical"),
            beat("电台里的半句话", "media_reputation", "media_counter", "巴里把模型争议剪成麦珂隐瞒重病，瑟琳娜用完整采访时序要求电台补播条件句", "补播口播与原采访时序", "银湾之声直播间", "电台节目总监", "B", "MSI", "瑟琳娜不公开麦珂具体指标", "流言不会立刻消失", "电台承认删节并补播范围说明"),
            beat("数据经纪人的附加页", "contract_rights", "legal_evidence", "在外包合同附加页发现数据经纪人拥有二次出售权，但签署主体没有病人授权", "数据二次使用附页", "沃特曼制作公司法务室", "隐私监察专员", "V", "MIT", "艾琳主动交出自己签过的管理页接受审查", "她承担监督疏漏责任", "二次出售被叫停并留下维克多资金线索"),
            beat("不曝光的证人", "legal_procedure", "legal_evidence", "保护提供经纪人账本的录入员身份，以密封证词推进调查而非媒体爆料", "密封证词保管令", "银湾地方法院书记室", "地方法官", "V", "MTA", "麦珂放弃用证人姓名赢得舆论", "案件推进更慢", "法院允许核查经纪人付款链"),
            beat("试验期而非全国标准", "health_safety", "teamwork", "伦理委员会只批准六个月小范围健康模型试验，拒绝麦珂团队把成功直接推广全国", "六个月受限试验许可", "银湾医疗伦理委员会", "伦理委员会", "V", "MIC", "麦珂接受自己的方案也必须被否决和复评", "商业合作缩小", "建立患者退出权和错误申诉通道", "institutional"),
            beat("一张网页不能装下病历", "media_reputation", "media_counter", "团队在1997年建立只发布方法与勘误的官方网站，不上传个人健康数据", "网站公开字段清单", "初声基金网站编辑室", "隐私监察专员", "B", "MIFA", "莱昂拒绝把歌迷论坛变成健康档案入口", "网站信息有限而不够轰动", "数据污染案以可核方法收束并转入隐私主线"),
        ],
    },
    {
        "title": "千禧年前夜：关系、信托与舞台代价", "start": "1998-02-14", "end": "1999-12-31",
        "goal": "让成年人关系和家庭安排拥有真实代价，同时把医疗代理与作品信托从情感控制中拆开。",
        "beats": [
            beat("车窗后的照片", "media_reputation", "media_counter", "小报用错位照片暗示瑟琳娜被控制，双方只纠正时间地点而不交出私人行程", "照片时间线勘误包", "凯德片场新闻室", "片场宣传负责人", "B", "MS", "瑟琳娜决定由自己面对记者", "麦珂无法替她挡掉所有追问", "小报撤回控制指控但保留评论自由"),
            beat("她自己的首映礼", "romance", "relationship_choice", "瑟琳娜选择独自走首映红毯，拒绝让关系成为电影宣传工具", "首映采访分工卡", "银幕宫首映礼", "电影制片方", "B", "MS", "麦珂不去制造惊喜抢走她的作品时刻", "两人被猜测疏远", "瑟琳娜的职业目标脱离恋情获得评价", "ally_resistance"),
            beat("罗文品牌的第一份授权", "contract_rights", "negotiation", "黛安娜把舞台服装图样授权给两家剧团，明确麦珂无权代她许可", "罗文图样区域许可", "罗文工作室展厅", "设计行业协会", "V", "MD", "黛安娜拒绝基金提供的独家保底", "她独自承担市场风险", "工作室获得独立品牌权"),
            beat("莉薇娅的三十天", "romance", "relationship_choice", "莉薇娅与麦珂在舆论热潮中登记短期婚前财产冷静期，拒绝闪婚自动合并资产", "三十天婚前披露清单", "普莱斯家族律师楼", "婚姻登记顾问", "B", "MLT", "莉薇娅公开拒绝家族替她谈条件", "双方家庭关系紧张", "两人获得基于真实披露的选择空间", "family"),
            beat("婚礼不等于并购", "contract_rights", "negotiation", "维克多借婚礼推动两家目录合并，麦珂和莉薇娅把婚姻、投资、版权分成三份文件", "三文件边界协议", "湖畔婚礼筹备室", "双方独立律师", "V", "MLT", "麦珂拒绝用爱情证明商业忠诚", "婚礼延期", "维克多无法借婚姻取得目录控制"),
            beat("分开之后的公开句子", "romance", "relationship_choice", "婚姻结束时双方共同确认只说明决定、不互曝隐私，也不把失败归咎第三者", "共同分开声明", "普莱斯庄园会客厅", "双方当事人", "B", "MLS", "麦珂承认自己在压力下把伴侣当成联盟", "他失去一段婚姻并承担舆论", "莉薇娅保住独立事业，关系以尊重收束", "internal"),
            beat("连续十四场", "health_safety", "strategic_withdrawal", "麦珂因控制欲坚持十四场连演，体能下滑后接受卡尔取消两场", "巡演减场决定", "东岸巡演指挥室", "巡演安全委员会", "V", "MIK", "麦珂向团队承认过度自信造成排期风险", "退票和赔偿真实发生", "团队建立任何成员可触发复核的疲劳红线", "internal"),
            beat("谁能替他说不", "health_safety", "legal_evidence", "独立医生、伴侣和经理的权限被拆开，任何人都不能单独决定长期治疗或作品处置", "医疗代理权限矩阵", "杰森家家庭会议", "医疗代理公证员", "T", "MIDST", "麦珂允许艾琳在急性风险下否决演出", "他放弃一部分即时控制", "医疗照护与资产代理不再捆绑"),
            beat("信托里的空白格", "contract_rights", "legal_evidence", "托马斯试图让空白继任人条款延后填写，苏菲亚要求所有触发条件在签署前落字", "继任触发条件附录", "初声基金受托人会议室", "独立受托人", "T", "MAT", "麦珂拒签有空白格的版本", "基金重组延迟", "作品信托避开未具名控制入口"),
            beat("午夜少一座升降台", "performance", "safety_preemption", "千禧演唱会彩排发现升降台负载不稳，团队改用步行入场完成跨年首演", "跨年舞台替代方案", "银湾世纪广场", "城市活动安全官", "V", "MIKQ", "麦珂舍弃最昂贵的开场设计", "赞助商扣减奖金", "现场以真实演唱跨年并留下设备供应链疑点", "technical"),
        ],
    },
    {
        "title": "母带出走：数字发行与创作者共同体", "start": "2000-03-01", "end": "2001-12-15",
        "goal": "在数字发行初期拆开传播、所有权和用户隐私，建立不依赖维克多集团的创作者渠道。",
        "beats": [
            beat("少了一盘母带", "contract_rights", "legal_evidence", "目录盘点发现一盘工作母带未归还，先追交接而不是指控盗窃", "母带盘点差异表", "初声基金母带库", "母带保管委员会", "V", "MIQ", "昆廷承认自己曾口头允许夜间试听", "团队暂停一首歌发行", "找到最后合法接收人与缺失归还环节"),
            beat("仓库里的十二箱", "contract_rights", "teamwork", "卡尔在旧仓库找回十二箱巡演录音，逐箱区分作品母带、现场参考和空白介质", "十二箱分类清单", "灰桥旧巡演仓库", "独立盘点员", "V", "MIK", "麦珂接受部分录音因权属不清不能发行", "周年专辑曲目减少", "目录从数量神话恢复为可用清单"),
            beat("分销商先违约", "contract_rights", "strategic_withdrawal", "分销商以数字格式不在旧合同为由停售实体唱片，却私自保留在线片段", "实体停售与片段留存对照", "全国分销仲裁中心", "商业仲裁员", "V", "MAT", "麦珂撤回要求立即全面上架的诉求", "短期销量下滑", "仲裁先停止未授权片段并保留实体供货争议"),
            beat("创作者合作社", "finance_business", "teamwork", "昆廷、艾琳和独立音乐人建立非独家合作社，共担压片成本但各自保留作品", "创作者合作社章程", "银湾旧邮局排练厅", "合作社登记员", "V", "MIQA", "麦珂只拥有一票而非否决权", "发行速度受共同表决限制", "独立作品获得共享生产渠道"),
            beat("下载不是转让", "contract_rights", "negotiation", "首批付费下载条款明确个人收听许可不等于母带转让或再分销权", "数字单曲个人许可页", "合作社网站办公室", "数字消费者委员会", "V", "MIAF", "莱昂要求许可语言普通歌迷能看懂", "法务删掉一部分强硬限制", "数字单曲合法上线且权属清晰"),
            beat("泄漏水印只指向机器", "legal_procedure", "legal_evidence", "网络泄漏样本的水印只锁定制作终端，团队拒绝据此指控当班员工", "终端水印范围说明", "合作社技术室", "数字取证顾问", "V", "MIA", "麦珂向被怀疑的员工道歉", "泄漏者仍未锁定", "调查转向终端共享账户", "technical"),
            beat("歌迷的合法试听周", "fan_public_welfare", "market_result", "星火同盟提出七天低码率试听与低价购买，压缩盗版需求而不收集实名", "七天试听规则", "星火同盟网络论坛", "消费者权益组织", "B", "MFA", "麦珂接受试听不会立刻变现", "首周单价收入下降", "合法下载用户扩大并保护歌迷隐私"),
            beat("巴里的假销量", "media_reputation", "media_counter", "巴里把试听次数包装成付费销量嘲讽失败，苏菲亚主动公布两套数字口径", "试听与付费双口径报表", "音乐行业记者会", "行业统计协会", "B", "MAF", "苏菲亚承认宣传稿曾混用指标", "团队承受一次公开纠错", "巴里的假比较失效且统计规则被行业采用"),
            beat("道歉不买热搜", "media_reputation", "public_confrontation", "麦珂为混用销量口径公开道歉，但拒绝巴里提出的付费形象修复交易", "公开更正声明", "合作社年度发布会", "发布会主持委员会", "B", "MIA", "麦珂承担错误而不把责任推给员工", "品牌短期受损", "公众重新区分麦珂的错误与巴里的操纵"),
            beat("代理基金的影子", "finance_business", "financial_counter", "苏菲亚从压片款找到维克多代理基金的小额交叉持股，推动合作社设置关联交易披露", "关联交易披露表", "创作者合作社年会", "独立审计师", "V", "MAQT", "团队允许维克多关联方保留公开表决权", "无法简单驱逐对手", "隐蔽持股失去暗中否决能力并指向更深版权收购"),
        ],
    },
    {
        "title": "归来不是复刻：创作、公益与世界巡演", "start": "2002-02-11", "end": "2003-12-20",
        "goal": "用新作品而不是旧传奇完成复出，并让公益、采样、巡演和亲密关系各自承担清楚的责任。",
        "beats": [
            beat("不唱旧副歌", "creation", "creative_breakthrough", "昆廷要求复刻成名曲，麦珂选择用破损节拍写一首承认年龄与恐惧的新歌", "新歌创作分轨稿", "海角录音棚", "制作人评审会", "V", "MQI", "麦珂接受年轻乐手否决旧式编曲", "电台预期下降", "复出专辑找到不可替代的新声音", "ally_resistance"),
            beat("采样来自谁", "contract_rights", "legal_evidence", "一段街头鼓点找到原演奏者及社区乐团，补签署名与收益而非只付买断费", "社区采样许可", "南码头社区乐团", "版权集体管理处", "V", "MIA", "麦珂让原演奏者决定是否保留真实姓名", "专辑成本增加", "采样合法且社区获得持续分成"),
            beat("昆廷离开控制室", "creation", "relationship_choice", "麦珂与昆廷因最终混音争执，昆廷离开一天迫使麦珂承认自己把导师当执行者", "混音决策备忘", "海角录音棚控制室", "双方共同制作人", "V", "MQI", "麦珂请昆廷回来但不要求他服从", "专辑错过一个宣传档期", "两人以共同否决机制修复合作", "internal"),
            beat("升降台之外的舞步", "performance", "creative_breakthrough", "旧膝伤限制高冲击动作，团队设计靠节奏和群舞推进的新舞台而非隐藏伤情", "低冲击编舞方案", "世界巡演排练馆", "巡演医疗与编舞组", "B", "MIK", "麦珂向舞者说明真实限制", "部分经典动作被取消", "新编舞通过公开排练赢得观众"),
            beat("慈善账户的第二把钥匙", "fan_public_welfare", "financial_counter", "公益演唱会捐款账户要求社区代表与基金各持一把审批权", "双签公益拨款规则", "河岸儿童音乐中心", "公益审计委员会", "V", "MAF", "麦珂不保留单独决定受助人的权力", "拨款速度变慢", "捐款避开宣传公司代收并可公开复核"),
            beat("一张错误的税表", "finance_business", "legal_evidence", "巡演收入被错误归入公益免税项目，苏菲亚主动补报而非等待对手曝光", "巡演收入更正申报", "银湾税务服务中心", "税务复核官", "V", "MAT", "苏菲亚公开承认分类错误", "基金支付滞纳金", "维克多失去把会计错误包装成侵吞的机会", "institutional"),
            beat("签证名单中的替补", "performance", "teamwork", "海外签证名单漏掉替补乐手，卡尔重排节目而不让未授权人员登台", "海外演出替补表", "西陆领事服务厅", "巡演签证官", "B", "MIK", "麦珂删掉需要完整编制的一段", "首站演出缩短", "巡演合法开场且替补获得后续场次"),
            beat("后台的一次扭伤", "health_safety", "safety_preemption", "麦珂后台扭伤后拒绝康拉德建议的快速封闭针，选择公开调整节目", "急性伤情双意见记录", "西陆体育馆医疗室", "独立巡演医生", "C", "MIC", "康拉德接受第二意见但记住麦珂的防备", "取消一场演出", "伤情恢复且双意见制度首次实战"),
            beat("她的电影档期", "romance", "relationship_choice", "瑟琳娜选择电影补拍而不是陪完整巡演，两人制定不要求公开证明忠诚的相处方式", "两地相处约定", "凯德电影片场", "双方当事人", "B", "MS", "麦珂不把缺席解释成背叛", "关系承受长距离不确定性", "瑟琳娜完成作品并保留关系选择", "internal"),
            beat("归来之夜", "performance", "performance_proof", "世界巡演收官用新歌、社区乐团与低冲击编舞证明复出，不用销量宣布永久胜利", "收官演出节目单", "银湾海角露天剧场", "现场制作委员会", "V", "MIQAF", "麦珂把最后一首歌交给社区乐团共同完成", "他放弃独占谢幕", "复出获得真实市场与创作回报，维克多转向收购公众叙事"),
        ],
    },
    {
        "title": "谁拥有记忆：歌迷自治与遗产叙事", "start": "2004-02-01", "end": "2005-12-10",
        "goal": "把歌迷数据、旧影像、纪录片与公众评价从单一公司手里释放，同时让麦珂接受别人拥有不同记忆。",
        "beats": [
            beat("论坛里的假票", "fan_public_welfare", "teamwork", "星火论坛出现仿冒电子票，莱昂组织歌迷验证订单号但不收集完整身份证", "假票互助核验规则", "星火同盟论坛办公室", "票务消费者热线", "B", "MFA", "莱昂拒绝基金接管论坛后台", "部分假票无法追回", "受害者获得分批退款与报案路径"),
            beat("莱昂的一票", "fan_public_welfare", "relationship_choice", "星火同盟改选时麦珂团队支持的人落选，麦珂接受歌迷组织不为自己服务", "星火改选结果", "河岸社区大会", "社区选举监督员", "B", "MFA", "麦珂公开祝贺批评过自己的候选人", "公关团队失去熟悉接口", "歌迷自治获得真实可信度", "ally_resistance"),
            beat("不能出售的会员名单", "contract_rights", "strategic_withdrawal", "赞助商要求会员名单换取演出补贴，星火同盟退出交易", "会员数据拒绝转让函", "赞助商谈判室", "隐私行业调解员", "V", "MFA", "苏菲亚支持歌迷拒绝一笔急需资金", "公益活动规模缩小", "会员隐私成为不可交易边界"),
            beat("透明票池", "finance_business", "financial_counter", "巡演将保留票、赞助票和公开票分池展示，允许独立抽查但不公开购票人隐私", "三类票池月报", "全国巡演票务中心", "独立票务审计员", "B", "MAFK", "卡尔放弃随时调取保留票的惯例", "团队临时用票减少", "黄牛无法再借内部票池制造稀缺"),
            beat("零分影评", "media_reputation", "market_result", "巴里组织匿名账号给纪录片预告刷零分，团队用实际售票与具名评论回应而不反刷", "评分异常与售票对照", "银湾电影资料馆", "影评平台申诉组", "B", "MSF", "瑟琳娜拒绝发动粉丝围攻批评者", "低分继续挂在页面", "平台标记异常流量，真实观众评价浮现"),
            beat("旧衣服会说错话", "media_reputation", "teamwork", "遗产展把不同年代服装混放，黛安娜亲自纠正但允许策展人保留批评性说明", "展品年代校订表", "银湾流行文化馆", "博物馆策展委员会", "V", "MDF", "黛安娜承认一件著名服装并非自己设计", "个人传奇少一层光环", "展览以可靠来源开放"),
            beat("纪录片的剪辑权", "contract_rights", "negotiation", "制片方要求最终剪辑权，麦珂只争取事实勘误权，不要求删除负面评价", "纪录片事实勘误附录", "海岸纪录片工作室", "纪录片伦理顾问", "V", "MSI", "麦珂接受导演保留他不喜欢的段落", "形象无法完全受控", "纪录片取得独立性且事实错误可纠正"),
            beat("开放档案日", "media_reputation", "teamwork", "评论者可预约查看精选原件目录，原件不离馆且私人资料继续封存", "开放档案日阅览规则", "初声基金档案馆", "档案伦理委员会", "B", "MAF", "麦珂允许最尖锐的批评者进入阅览名单", "团队承受不友好解读", "公众叙事从宣传口径转向可核材料"),
            beat("莉薇娅的版本", "romance", "relationship_choice", "莉薇娅在纪录片中讲述婚姻失败，麦珂不要求预审，只纠正一处日期", "单一日期勘误函", "纪录片访谈室", "纪录片导演", "B", "MLS", "麦珂接受前伴侣拥有自己的故事", "公众看到他的控制欲缺陷", "两人关系从防御转为成熟距离", "internal"),
            beat("收购报价没有观众", "finance_business", "market_result", "维克多以高价收购纪录片与展览目录，创作者和歌迷以预售、捐赠补足缺口拒绝独占", "公众预售与捐赠账", "流行文化馆理事会", "博物馆理事会", "V", "MAQF", "麦珂不补齐全部资金以控制理事会", "项目缩小巡展城市", "维克多的公众记忆收购失败"),
        ],
    },
    {
        "title": "常驻舞台：医疗控制开始靠近", "start": "2006-01-15", "end": "2007-12-22",
        "goal": "在常驻演出高压下让康拉德、托马斯与保险条款逐步接近死亡链，但每一步都有现实职业动机与可见边界。",
        "beats": [
            beat("一百场不是一张合同", "contract_rights", "negotiation", "常驻演出把一百场拆成四个可复评阶段，拒绝一次签完全部健康与作品权", "四阶段常驻合同", "星湾宫剧院合同厅", "剧院合同委员会", "V", "MITK", "麦珂接受每阶段都可能被停止", "无法锁定全部收入", "常驻项目获得退出和复评机制"),
            beat("北侧出口", "health_safety", "safety_preemption", "满场测试发现北侧出口拥堵，卡尔暂停售票扩容并重画疏散路线", "北侧出口整改图", "星湾宫剧院", "城市消防官", "V", "MIK", "卡尔承认自己早先低估人流", "首月少售数千张票", "场馆容量以真实疏散能力确定", "technical"),
            beat("赞助商的药柜", "health_safety", "strategic_withdrawal", "赞助合同要求使用指定恢复产品，艾琳让医疗选择退出商业条款", "恢复产品利益披露", "常驻演出赞助会议室", "医疗伦理顾问", "V", "MIC", "麦珂放弃高额恢复品牌赞助", "项目预算出现缺口", "药物和补剂选择回到独立医疗团队"),
            beat("第二支医疗队", "health_safety", "teamwork", "巡演团队与剧院医疗队互不服从，双方建立交叉交班而非由一人总控", "双医疗队交班表", "星湾宫医疗站", "城市医疗协调员", "C", "MICK", "康拉德接受自己的意见必须被第二医生复核", "应急沟通变慢", "任何用药与停演都有双来源记录", "institutional"),
            beat("凌晨三点的加练", "health_safety", "relationship_choice", "麦珂偷偷加练破坏睡眠计划，艾琳停止第二天排练并当众指出他的控制欲", "加练取消记录", "星湾宫夜间舞台", "巡演安全委员会", "V", "MIK", "麦珂承认自己制造了风险", "损失一整天场租", "团队确认主角也必须服从疲劳红线", "internal"),
            beat("康拉德的第一次处方", "health_safety", "legal_evidence", "康拉德建议短期助眠药，独立医生核对剂量、期限和停药条件后才启用", "短期处方双签页", "独立睡眠门诊", "持证处方复核医生", "C", "MIC", "麦珂既不因前世恐惧拒绝一切治疗，也不交出长期授权", "他经历短期副作用并减量", "康拉德进入医疗链但权限受双签约束", "institutional"),
            beat("重复续方", "health_safety", "legal_evidence", "苏菲亚发现药房收到一张超出期限的重复续方，保留原传真并暂停配药", "重复续方异议单", "星湾宫合作药房", "药房合规官", "C", "MIAC", "康拉德承认办公室流程可能被借用并配合调查", "麦珂一晚无法使用原方案", "续方来源指向托马斯安排的健康管理秘书"),
            beat("保险要看多少", "contract_rights", "negotiation", "保险续约要求完整病历，托马斯与艾琳争执后限定为承保相关摘要和独立封存", "承保摘要披露协议", "北陆保险复核中心", "保险隐私仲裁员", "T", "MITC", "麦珂否决托马斯提交整套病历的效率方案", "保单审批延迟", "保险获得必要信息但无法取得治疗控制权"),
            beat("紧急联系人不是受托人", "family_relationship", "legal_evidence", "家庭紧急联系人、医疗代理和版权受托人被再次分开，杜绝一次事故触发资产转移", "三角色分离公证书", "杰森家庭公证会议", "独立公证员", "T", "MIDSTMM", "麦珂让玛莎选择只做家属联系人", "家人面对更复杂流程", "托马斯失去用紧急联系人解释资产权限的空间"),
            beat("最后一场没有加演", "performance", "performance_proof", "常驻收官夜赞助商要求临时加演，麦珂按疲劳红线准时结束并用清唱谢幕", "收官不加演决定", "星湾宫主舞台", "巡演安全委员会", "V", "MIKQ", "麦珂拒绝用英雄式透支证明敬业", "少一场高额收入", "常驻成功收束，同时重复续方与保险条款留下死亡链证据"),
        ],
    },
    {
        "title": "复出演唱会：死亡链第一次露出全貌", "start": "2008-01-12", "end": "2008-12-20",
        "goal": "筹备最后一次全球复出时，把舞台、药物、保险、讣告和目录转移连接成一条仍未完全启动的利益链。",
        "beats": [
            beat("不是告别巡演", "creation", "creative_breakthrough", "麦珂把复出概念从告别改为仍在创作，拒绝预设死亡后的纪念叙事", "复出概念册", "海角创作营", "共同制作委员会", "V", "MIQ", "麦珂允许团队删掉自我神化段落", "宣传口号失去煽情卖点", "复出以新作品而非遗产拍卖启动"),
            beat("四十分钟上限", "health_safety", "safety_preemption", "首次连排触及体能红线，团队把单段排练限定四十分钟并强制间隔", "分段排练安全表", "复出排练中心", "独立运动医学组", "C", "MICK", "麦珂不再偷偷补练", "排练周期延长", "真实体能基线建立"),
            beat("备用升降机", "health_safety", "teamwork", "设备商用未经负载测试的备用升降机替换主机，卡尔拒绝签收", "备用升降机拒收单", "复出主舞台装台区", "城市设备检验员", "V", "MIK", "卡尔承担延误责任而不向下属甩锅", "舞台联排取消", "供应商与维克多关联付款被记录"),
            beat("补剂瓶里的批号", "health_safety", "legal_evidence", "艾琳发现恢复补剂封签批号与采购单不符，送独立实验室只检测成分不推断投放者", "补剂批号与检测委托", "独立药物实验室", "实验室质量负责人", "C", "MIAC", "麦珂暂停所有非必要补剂", "恢复速度下降", "异常批次含未申报镇静成分并被封存"),
            beat("双签被跳过一次", "health_safety", "legal_evidence", "康拉德办公室发出的注射建议缺少第二医生签名，医疗站拒绝执行", "未完成双签的注射建议", "复出医疗站", "医疗站主管", "C", "MIAC", "康拉德声称秘书误发但接受文件封存", "团队与医生信任受损", "有人试图绕过双签的事实成立"),
            beat("死亡概率模型", "finance_business", "financial_counter", "保险经纪人拿出异常升高的死亡概率要求追加保额，苏菲亚发现模型继续使用已隔离污染数据", "承保模型数据血缘表", "北陆保险精算中心", "保险精算复核会", "T", "MIAT", "麦珂允许真实高风险项目保留在模型中", "保费仍然上涨一部分", "虚假风险被剔除且保险动机开始显形"),
            beat("尚未死亡的讣告", "media_reputation", "legal_evidence", "莱昂发现媒体素材库里出现带发布日期占位符的麦珂讣告，团队确认它来自纪念活动承包商", "讣告模板来源回函", "星火同盟媒体观察站", "媒体伦理委员会", "B", "MFA", "麦珂不要求媒体禁止准备背景资料", "公众暂不知道危险", "异常在于承包商已填入未公开医疗细节"),
            beat("纪念衫的期权", "contract_rights", "financial_counter", "黛安娜发现纪念商品合同在麦珂失能时自动生效，并由维克多关联公司持有", "纪念商品失能期权", "罗文工作室法务台", "商业仲裁员", "V", "MDAT", "黛安娜拒绝为证明立场销毁设计稿", "纪念项目暂时仍合法存在", "自动生效条款被暂停并保存完整资金链"),
            beat("替补歌手也要有名字", "performance", "teamwork", "承包商把替补歌手写成匿名替换资源，昆廷要求明确替补只在麦珂主动停演时登台", "替补登台条件表", "复出音乐排练厅", "演员工会代表", "V", "MIQK", "麦珂接受演出可以没有自己", "他的不可替代神话被打破", "替补成为独立证人而非被控制工具"),
            beat("代理协议的背页", "legal_procedure", "legal_evidence", "托马斯提交的紧急代理协议背页把失能与目录托管相连，苏菲亚要求法院先行解释条款", "紧急代理背页异议", "银湾遗产法院", "遗产法院法官", "T", "MIADT", "麦珂不提前公开全部证据惊动利益链", "危险人物仍留在团队外围", "法院密封保留异议，死亡链进入可证明阶段"),
        ],
    },
    {
        "title": "倒计时：他们开始为活人分遗产", "start": "2009-01-08", "end": "2009-05-30",
        "goal": "让利益链误判麦珂即将失能，逐步启动医疗、保险、目录和纪念产业，但主角始终清醒且不以假死取证。",
        "beats": [
            beat("钢索提前松了一圈", "health_safety", "safety_preemption", "主舞台钢索张力异常，卡尔用前一日标记确认有人调整过但不推断凶手", "钢索复检差异记录", "全球复出演唱会主舞台", "城市舞台检验局", "V", "MIK", "麦珂取消媒体开放彩排", "失去一次全球宣传窗口", "近失事故被阻断并留下设备权限名单"),
            beat("病历复印请求", "contract_rights", "legal_evidence", "医疗档案室收到以保险复核为名的整册复制请求，艾琳只放行承保摘要", "整册病历复制拒绝单", "独立医疗档案室", "隐私监察专员", "T", "MICT", "麦珂不撤销所有保险授权", "承保复核变慢", "请求发起账号追到托马斯办公室"),
            beat("受益人没有改", "finance_business", "legal_evidence", "保险系统出现未完成的受益人变更草稿，苏菲亚证明没有麦珂本人确认", "未完成受益人草稿", "北陆保险保单服务中心", "保险合规委员会", "T", "MIAT", "苏菲亚只冻结变更流程不冻结保单", "保险保障短暂受限", "利益链无法把草稿变成有效指令"),
            beat("失能即转让", "contract_rights", "negotiation", "目录合同隐藏失能触发转让，艾琳与昆廷将托管、经营和所有权拆开", "目录失能条款修订稿", "创作者合作社理事会", "独立版权受托委员会", "V", "MIQT", "麦珂允许独立受托人临时经营但不取得所有权", "自己在短期失能时无法直接指挥", "维克多失去自动收购入口"),
            beat("不能空白的代理人", "legal_procedure", "legal_evidence", "紧急授权表的替补代理人仍为空白，麦珂当场作废而不是事后补名", "作废紧急授权表", "杰森家庭律师会议", "独立公证员", "T", "MIDST", "麦珂选择由三人分权而非最信任的一人总管", "应急决策更复杂", "任何失能决定需要医疗、家属和受托人分别确认"),
            beat("被取消的记者席", "media_reputation", "media_counter", "巴里散布麦珂已无法排练的消息迫使主办方取消记者席，瑟琳娜邀请有限记者看完整一段排练", "有限开放排练规则", "复出排练中心", "记者协会观察员", "B", "MSIK", "麦珂接受记者看见他停下来休息", "完美形象受损", "失能流言被真实而有限的现场推翻"),
            beat("纪念域名", "fan_public_welfare", "legal_evidence", "莱昂发现纪念网站域名在事故前注册，查到注册费来自巴里控制的公关账户", "纪念域名注册回执", "星火网络观察站", "域名争议仲裁员", "B", "MFA", "莱昂不入侵网站后台", "只能得到公开注册链", "纪念产业准备时间被锁定"),
            beat("提前录好的哭声", "media_reputation", "legal_evidence", "瑟琳娜在电视台发现纪念特辑已录制主持人悼词，并含保险方未公开日期", "纪念特辑制作单", "银湾电视中心资料库", "电视台伦理委员会", "B", "MSA", "瑟琳娜拒绝偷走母带，只申请保全制作单", "完整节目仍由电视台控制", "媒体与保险的信息通道被连接"),
            beat("家人不同意继续", "family_relationship", "relationship_choice", "玛莎和黛安娜要求停演，麦珂承认恐惧但提出缩小规模的公开安全彩排", "家庭安全分歧记录", "杰森家客厅", "家庭成员共同决定", "V", "MMDISK", "麦珂接受家人否决高危舞台", "全球首演规模缩减", "团队以非冒险方式继续让利益链暴露", "family"),
            beat("公开彩排，不是诱饵事故", "performance", "performance_proof", "麦珂在无升降设备、独立医疗监护下完成公开彩排，证明清醒与行动能力", "公开安全彩排全程记录", "银湾市民剧场", "城市安全与医疗观察员", "V", "MIKQSA", "麦珂不制造假昏迷诱骗对手", "对手暂时收敛直接动作", "全球直播计划恢复，纪念承包商改用法律文件下手"),
        ],
    },
    {
        "title": "失能文本：医疗、保险与目录的合围", "start": "2009-06-04", "end": "2009-08-18",
        "goal": "在最终直播前逐项拆穿伪造同意、保险付款和纪念广播切换，让每位盟友守住一条独立证据线。",
        "beats": [
            beat("不存在的急救电话", "health_safety", "legal_evidence", "康拉德声称接到麦珂急救请求，电话公司记录却显示来电来自健康秘书分机", "急救来电来源证明", "城市急救调度中心", "急救记录审查官", "C", "MIAC", "麦珂不把康拉德一次矛盾直接写成谋杀", "康拉德仍保留执业辩解", "伪造紧急情境的入口被证实"),
            beat("镇静方案被拒绝", "health_safety", "safety_preemption", "康拉德以长途直播焦虑为由建议深度镇静，第二医生与麦珂共同拒绝", "镇静建议拒绝与替代照护单", "全球直播医疗站", "独立麻醉顾问", "C", "MIC", "麦珂接受非药物休息和减少节目", "直播时长再次缩短", "对手无法合法取得受控昏迷窗口"),
            beat("伪造的同意页", "legal_procedure", "legal_evidence", "艾琳发现医疗同意页签名来自旧扫描件，公证员只证明版本来源与未现场签署", "同意页版本鉴别书", "银湾公证检验室", "文件公证员", "T", "MIAT", "麦珂不用笔迹神断而依靠版本与见证记录", "正式调查需要更多时间", "伪造同意链指向托马斯的文件服务器"),
            beat("后台通行证的第四种颜色", "health_safety", "teamwork", "卡尔发现未登记的第四类后台证，回收时保留持证人申诉通道", "后台证分类与回收记录", "全球直播场馆安保台", "场馆安保总监", "V", "MIK", "卡尔不把临时工全部当敌人", "入口排查拖慢装台", "未授权证件来源追到纪念承包商"),
            beat("讣告禁发令破口", "media_reputation", "media_counter", "一份讣告绕过禁发令在地方电台播出，瑟琳娜保全播出日志并亲自报平安", "误播讣告日志", "北湾地方电台", "广播监管委员会", "B", "MSA", "瑟琳娜不借误播发动粉丝围堵", "死亡谣言短时扩散", "巴里的预置分发名单被暴露"),
            beat("尚未触发的赔付指令", "finance_business", "legal_evidence", "保险托管账户出现预填赔付指令，苏菲亚证明触发证明为空且收款方关联维克多", "预填赔付指令与空触发栏", "北陆保险托管银行", "银行反欺诈主管", "T", "MIAT", "团队只暂停这笔指令不冻结无辜保单", "无法立即追回所有关联资金", "保险收益链被完整连接"),
            beat("目录出售的托管箱", "contract_rights", "legal_evidence", "维克多把目录购买款提前存入托管箱，昆廷用未满足的失能条件阻止交割", "目录购买托管条件表", "银湾版权交易所", "版权交易仲裁员", "V", "MIQT", "麦珂不撤销正常市场交易规则", "购买款仍合法冻结等待裁决", "维克多提前行动的时间点成为证据"),
            beat("纪念广播切换键", "media_reputation", "teamwork", "技术团队发现全球直播控制台预置纪念信号源，艾琳让正常演出源与证据源分权管理", "双信号源权限表", "全球直播导播间", "广播技术监督员", "B", "MIAS", "艾琳不保留单人总开关", "切换速度降低", "任何纪念切换都需两名独立确认", "technical"),
            beat("四个人守四扇门", "family_relationship", "teamwork", "黛安娜守作品与家庭授权、艾琳守医疗与信号、苏菲亚守资金、卡尔守舞台，互不代权", "终局四线职责图", "全球直播联合指挥室", "独立总协调员", "V", "MDIAK", "麦珂放弃自己统一指挥所有证据", "团队必须承受意见冲突", "死亡链不再能靠攻破一个人全盘启动", "internal"),
            beat("他们以为他不能说话", "legal_procedure", "strategic_withdrawal", "托马斯以失能文件请求接管时，麦珂通过医生确认保持清醒但暂不公开全部证据", "清醒能力独立评估", "银湾遗产法院临时审查室", "独立能力评估医生与法官", "T", "MIAT", "麦珂只撤销接管请求，不提前完成终局审判", "维克多与巴里仍会启动直播纪念方案", "法官密封确认麦珂具备决定能力，最终行动窗口形成"),
        ],
    },
    {
        "title": "活人出席自己的纪念礼", "start": "2009-08-20", "end": "2009-08-29",
        "goal": "让利益链因误判麦珂无法现身而公开启动，再由清醒存活的麦珂和各自独立的证据持有人在全球直播中完成结算。",
        "beats": [
            beat("全球开始悼念", "media_reputation", "media_counter", "巴里向全球媒体发出未经医院确认的死亡快讯，星火同盟只发布核验指南不提前泄露麦珂位置", "死亡快讯分发链", "星火全球媒体观察台", "国际广播联盟伦理席", "B", "MFA", "麦珂允许世界短暂相信错误消息但不伪造死亡", "亲友承受真实恐慌与愤怒", "快讯来源、纪念商品和保险指令在同一时点启动"),
            beat("纪念礼先卖版权", "finance_business", "legal_evidence", "维克多在纪念直播前宣布目录收购，苏菲亚让交易所展示托管条件仍未满足", "纪念日目录收购公告", "全球版权交易所直播席", "版权交易仲裁委员会", "V", "MAQT", "团队不冻结整个交易所", "维克多仍能公开辩解", "提前交割企图与保险赔付指令完成互证"),
            beat("证据不是一段剪辑", "legal_procedure", "teamwork", "艾琳、黛安娜、苏菲亚、卡尔分别在直播前向监督员提交医疗、授权、资金、舞台四条原始链", "四线证据目录", "全球纪念直播证据室", "法院指定证据监督员", "T", "MDIAK", "任何人都不能用自己的材料替另一条线下结论", "直播节奏变慢且必须逐项核对", "法官允许在纪念直播中展示已核范围"),
            beat("麦珂走进自己的纪念直播", "performance", "public_confrontation", "纪念节目第一个商业段落开始时，麦珂本人清醒走上舞台，先完成一首新歌再纠正死亡消息", "直播存活确认与现场演出记录", "全球纪念直播主舞台", "法院观察员与国际广播联盟", "V", "MIQSAFK", "麦珂不靠长篇演说抢在证据前定罪", "他必须公开承认身体限制和团队分歧", "全球观众确认他存活，巴里、托马斯、康拉德与维克多的预置口径彼此冲突"),
            beat("第500章：没有人替他写结局", "legal_procedure", "legal_evidence", "法院依据四线证据冻结具体赔付和目录交割、启动刑事调查；麦珂保住生命、家人和版权后把新作品交给共同体演出", "终局有限裁定与新作公开许可", "银湾全球直播舞台与商业法院连线庭", "商业法院与医疗监管委员会", "V", "MMDISLQAFKTC", "麦珂接受终局只是依法调查的开始而非私刑式全能审判", "关系无法回到无裂痕状态，身体也需要长期休养", "死亡利益链失去立即获利能力；麦珂以活人的身份选择下一首歌"),
        ],
    },
]


def spread_dates(start: str, end: str, count: int) -> list[str]:
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    if count == 1:
        return [first.isoformat()]
    span = (last - first).days
    return [(first + timedelta(days=round(span * i / (count - 1)))).isoformat() for i in range(count)]


def bible_registry() -> dict[str, dict[str, Any]]:
    data = load(BIBLE)
    return {str(item["name"]): item for item in data.get("characters") or []}


def cast_entry(person: dict[str, Any]) -> dict[str, Any]:
    name = str(person["name"])
    aliases = list(dict.fromkeys([name, name.split("·")[0]] + list(person.get("aliases") or [])))
    return {
        "character_id": str(person["character_id"]), "name": name,
        "display_name": name, "aliases": aliases, "role": str(person.get("role") or "固定人物"),
        "alignment": str(person.get("alignment") or "canonical"),
    }


def phase_for_chapter(chapter: int) -> str:
    return f"P{((chapter - 1) // 50) + 1:02d}"


def causal_for_phase(phase: str, offset: int) -> list[str]:
    allowed = {
        "P06": ["CS03", "CS04", "CS05", "CS06", "CS07", "CS08", "CS09", "CS13", "CS14", "CS15"],
        "P07": ["CS04", "CS05", "CS06", "CS07", "CS08", "CS09", "CS10", "CS13", "CS14", "CS15"],
        "P08": ["CS05", "CS06", "CS07", "CS08", "CS09", "CS10", "CS11", "CS13", "CS14", "CS15"],
        "P09": ["CS06", "CS07", "CS08", "CS09", "CS10", "CS11", "CS12", "CS13", "CS14", "CS15"],
        "P10": ["CS06", "CS07", "CS08", "CS09", "CS10", "CS11", "CS12", "CS13", "CS14", "CS15"],
    }[phase]
    return [allowed[offset % len(allowed)]]


def foreshadow_for_phase(phase: str, offset: int) -> list[str]:
    allowed = {
        "P06": ["FS04", "FS05"], "P07": ["FS05", "FS06"],
        "P08": ["FS06", "FS07", "FS08", "FS09", "FS10"],
        "P09": ["FS06", "FS07", "FS08", "FS09", "FS10", "FS11", "FS12"],
        "P10": ["FS07", "FS08", "FS09", "FS10", "FS11", "FS12"],
    }[phase]
    return [allowed[offset % len(allowed)]]


def event_type_domain(event_type: str) -> str:
    return {
        "performance": "stage", "creation": "creation", "contract_rights": "rights",
        "finance_business": "finance", "family_relationship": "family", "media_reputation": "media",
        "health_safety": "health", "fan_public_welfare": "fans", "romance": "romance",
        "legal_procedure": "law",
    }[event_type]


def synopsis_actions(synopsis: str) -> list[str]:
    """Turn one already-human-edited card into its concrete action beats."""
    return [part.strip() for part in synopsis.split("。") if part.strip()]


def build_tail(prefix_events: list[dict[str, Any]], prefix_cards: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    registry = bible_registry()
    theme_contract = deepcopy(prefix_events[-1].get("theme_contract") or {})
    tail_events: list[dict[str, Any]] = []
    tail_cards: list[dict[str, Any]] = []
    flattened: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    for arc in ARCS:
        dates = spread_dates(arc["start"], arc["end"], len(arc["beats"]))
        flattened.extend((arc, item, when) for item, when in zip(arc["beats"], dates))
    if len(flattened) != 115:
        raise RuntimeError(f"tail catalogue must contain 115 events, got {len(flattened)}")
    expected_divisions = {f"EC{number:03d}" for number in range(136, 251)}
    if set(DIVISIONS) != expected_divisions:
        missing = sorted(expected_divisions - set(DIVISIONS))
        extra = sorted(set(DIVISIONS) - expected_divisions)
        raise RuntimeError(f"manual divisions mismatch: missing={missing}, extra={extra}")

    for offset, (arc, seed, when) in enumerate(flattened):
        ec = 136 + offset
        eid = f"EC{ec:03d}"
        ch1, ch2 = ec * 2 - 1, ec * 2
        phase = phase_for_chapter(ch1)
        names = [N[key] for key in seed["cast"]]
        if N[seed["opponent"]] not in names:
            names.append(N[seed["opponent"]])
        names = list(dict.fromkeys(names))
        cast = [cast_entry(registry[name]) for name in names]
        ids = {item["display_name"]: item["character_id"] for item in cast}
        opponent_name = N[seed["opponent"]]
        location = seed["location"]
        role = "two_chapter_setup_and_win"
        directions = (
            f"{arc['goal']} 本事件只推进：{seed['point']}。第一章取得可复核的小赢，"
            f"第二章承担{seed['cost']}并以{seed['gain']}有限结算。"
        )
        # 每个事件必须拥有不可互换的“前世信息差”。把本事件独有的
        # 物证、误判点、现实代价和权限主体都写进记忆边界，避免数百章
        # 使用同一套“前世知道—今生核对”的空模板。
        info_gap = (
            f"前世关于《{seed['artifact']}》的记忆只留下一个错位："
            f"{seed['point']}当时被当作可事后补救的小事，结果先发生了{seed['cost']}。"
            f"今生麦珂因此把{seed['choice']}放到最前，但他不知道责任人和结果是否仍会相同，"
            f"结论必须由{seed['authority']}在现场作出。"
        )
        artifact_id = f"ART_{ch1}_{hashlib.sha1(seed['artifact'].encode('utf-8')).hexdigest()[:8].upper()}"
        artifact = {
            "artifact_id": artifact_id, "timeline_scope": "current", "display_name": f"《{seed['artifact']}》",
            "kind": "documented_record", "created_at": ch1, "signers": [seed["authority"]],
            "scope": [seed["point"]], "granted_permissions": ["use_as_evidence_within_scope"],
            "does_not_grant": ["freeze_all_assets", "dismiss_staff", "override_medical_consent", "transfer_copyright"],
            "authority_source": seed["authority"], "expires_at": None,
        }
        ref = {
            "artifact_id": artifact_id, "timeline_scope": "current", "display_name": f"《{seed['artifact']}》",
            "purpose": f"复核{seed['point']}，不得扩大为其他人物或资产的结论",
            "required_permission": "use_as_evidence_within_scope", "scope_assertion": "仅按创建时明示范围使用",
        }
        progress_transition = {
            "domain": "foreshadow", "entity_id": f"PLOT_{eid}", "state_key": f"progress_{eid.lower()}",
            "from": "none", "to": f"resolved_{hashlib.sha1(seed['gain'].encode('utf-8')).hexdigest()[:10]}",
            "irreversible": False, "evidence": artifact_id, "effect_type": "protagonist_gain",
        }
        transitions = [progress_transition]
        if seed["opposition_type"] == "villain":
            transitions.append({
                "domain": "enemy_capability", "entity_id": ids[opponent_name],
                "state_key": f"failed_move_{eid.lower()}", "from": "available", "to": "documented_and_limited",
                "irreversible": False, "evidence": artifact_id, "effect_type": "villain_loss",
            })
        division = DIVISIONS[eid]
        synopsis1 = str(division["ch1"]).strip()
        synopsis2 = str(division["ch2"]).strip()
        action1 = synopsis_actions(synopsis1)
        action2 = synopsis_actions(synopsis2)
        if len(action1) < 3 or len(action2) < 3:
            raise RuntimeError(f"{eid}人工章卡不足三个具体行动节点")
        next_point = flattened[offset + 1][1]["point"] if offset + 1 < len(flattened) else "麦珂以活人的身份决定下一首歌如何开始"
        milestone1 = {
            "chapter_id": ch1, "timeline_start": when, "timeline_end": when,
            "scene": location, "chapter_goal": action1[0],
            "chapter_title": seed["title"] + "·上", "participants": names + [f"{seed['authority']}（本事件权限主体）"],
            "opening_conflict": action1[0], "info_gap_use": info_gap,
            "opponent_reaction": f"{opponent_name}试图借时间、声誉或资源压力推动未完成的决定。",
            "scenes": [{"sequence": 1, "location": location, "is_primary": True, "temporal_mode": "current", "transition_cue": action1[0]}],
            "artifact_creates": [artifact], "artifact_refs": [], "action_sequence": action1,
            "visible_payoff": action1[-1],
            "ending": action1[-1] + "。",
            "must_include": [seed["choice"], seed["artifact"], f"地点为{location}"],
            "must_not_include": ["把临时结果写成永久定罪", "输出结构化状态字段", "非麦珂人物拥有前世记忆"],
            "detailed_synopsis": synopsis1,
        }
        milestone2 = {
            "chapter_id": ch2, "timeline_start": when, "timeline_end": when,
            "scene": location, "chapter_goal": action2[0],
            "chapter_title": seed["title"] + "·下", "participants": names + [f"{seed['authority']}（本事件权限主体）"],
            "opening_conflict": action2[0], "info_gap_use": "麦珂不再重复解释前世，只用第一章保住的材料决定行动顺序。",
            "opponent_reaction": f"{opponent_name}在证据范围被写清后转而争夺解释权，但不能抹去已记录的选择。",
            "scenes": [{"sequence": 1, "location": location, "is_primary": True, "temporal_mode": "current", "transition_cue": action2[0]}],
            "artifact_creates": [], "artifact_refs": [ref], "action_sequence": action2,
            "visible_payoff": action2[-1],
            "ending": action2[-1] + f"；下一步转向{next_point}。",
            "must_include": [seed["cost"], seed["gain"], seed["authority"]],
            "must_not_include": ["重复第一章完整冲突", "永久封杀或绝对控制权", "输出ART编号或snake_case字段"],
            "detailed_synopsis": synopsis2,
        }
        event = {
            "cluster_id": eid, "chapter_span": [ch1, ch2], "name": seed["title"],
            "timeline_years": when[:4], "arc_id": phase,
            "story_block_id": f"B{((ec - 1) // 10) + 1:03d}", "story_block_title": arc["title"],
            "story_block_goal": arc["goal"], "story_block_outcome": seed["gain"],
            "macro_group_id": f"MG{((ec - 1) // 5) + 1:03d}", "macro_group_title": arc["title"],
            "macro_goal": arc["goal"], "macro_ending_state": seed["gain"],
            "source_event_direction": directions, "source_event_direction_sha256": text_sha(directions),
            "source_macro_sha256": sha({"title": arc["title"], "goal": arc["goal"]}),
            "main_opponent": opponent_name, "main_opponent_character_id": ids[opponent_name],
            "main_opponent_character_ids": [ids[opponent_name]], "opposition_type": seed["opposition_type"],
            "event_type": seed["event_type"], "solution_type": seed["solution_type"],
            "death_chain_role": ["pressure", "advance", "reveal", "echo"][offset % 4],
            "death_chain_step": {"step": seed["point"], "evidence_boundary": seed["artifact"], "future_use": next_point},
            "causal_spine_ids": causal_for_phase(phase, offset), "foreshadow_ids": foreshadow_for_phase(phase, offset),
            "main_characters": names, "main_character_ids": [ids[name] for name in names],
            "canonical_cast": cast, "fictional_obstacle": action1[0],
            "prev_life_tragedy": f"前世麦珂在同类节点未能阻止{seed['cost']}继续扩大，最终使医疗、保险或版权控制链获得一块拼图。",
            "info_gap_from_prev_life": info_gap, "why_previous_life_failed": f"他当时把{seed['point']}误当成可以事后补救的小事。",
            "preemptive_avoidance": seed["choice"], "bait_and_evidence": f"不制造假事故；以《{seed['artifact']}》记录今生自然发生的选择和对手动作。",
            "comic_villain_behavior": f"{opponent_name}把{seed['artifact']}说成无关紧要的手续，却反复催促所有人立刻照办，反而暴露其最在意的环节。" if seed["opposition_type"] == "villain" else "冲突来自制度、技术或关系边界；人物行为保持现实动机。",
            "comic_villain_beat": f"{opponent_name}急于抢解释权而留下可核口径。" if seed["opposition_type"] == "villain" else "本事件以制度或关系摩擦形成节奏。",
            "opponent_humanizing_beat": f"{opponent_name}也有避免损失、保住职业或维持组织运转的现实动机。",
            "villain_loss": f"{opponent_name}在{eid}失去把{seed['point']}直接扩大为控制权的这一条路径。",
            "protagonist_gain": f"麦珂团队在{eid}{seed['gain']}。",
            "relationship_change": seed["choice"], "romance_state": seed["choice"] if seed["event_type"] in {"romance", "family_relationship"} else "重要关系保留独立判断与拒绝权。",
            "cluster_outcome": f"团队承担{seed['cost']}，并{seed['gain']}；结果不外推到其他争议。",
            "core_payoff": f"{seed['gain']}，同时由麦珂承担{seed['cost']}。",
            "next_event_hook": f"{eid}结算后的未决入口转向：{next_point}。",
            # 重大胜利只落在阶段收束点；普通簇用小赢、部分赢和带代价推进，
            # 避免每几章就“终局翻盘”造成爽点通胀。
            "outcome_type": (
                "major_win" if ec in {145, 155, 165, 176, 186, 196, 206, 216, 226, 236, 245, 250}
                else [
                    "small_win", "partial_win", "costly_win",
                    "small_win", "partial_win", "setback_with_gain",
                ][offset % 6]
            ),
            "resolution_signature": {
                "attack_domain": event_type_domain(seed["event_type"]),
                "counter_method": f"{seed['solution_type']}:{seed['artifact']}",
                "resolver": seed["authority"], "publicity": ["private", "limited", "industry", "public"][offset % 4],
                "hero_gain_type": seed["gain"],
            },
            "state_transitions": transitions, "two_chapter_structure": [milestone1, milestone2],
            "chapter_milestones": [milestone1, milestone2],
            "continuity_writes": [f"承接第{ch1-1}章，不恢复已隔离旧正文。", f"下一事件只接续：{next_point}"],
            "historical_anchor_ids": [f"FICTIONAL_{when[:4]}_{eid}"], "source_anchor_ids": ["CH270_BA83_CR41"] if eid == "EC136" else [f"PREV_{ec-1:03d}"],
            "foreshadows": [next_point], "resolves": [seed["point"]],
            "plan_relations": {"previous_cluster": f"EC{ec-1:03d}", "next_cluster": f"EC{ec+1:03d}" if ec < 250 else None},
            "rebirth_flywheel": {"memory": info_gap, "present_action": seed["choice"], "evidence": seed["artifact"], "cost": seed["cost"], "gain": seed["gain"]},
            "hard_constraints": ["只有麦珂拥有前世记忆", "证据必须由今生行动形成", "两章不得重演同一场面"],
            "theme_contract": theme_contract, "generated_by": "manual_architecture", "generation_providers": ["codex_manual"],
            "manual_edits": ["EC136-EC250 full manual reconstruction"], "planning_version": VERSION,
        }
        if ec in {150, 170, 190, 210, 230}:
            event["character_flaw_beat"] = {
                "trigger": seed["point"], "protagonist_action": seed["choice"],
                "immediate_benefit": seed["gain"], "hidden_cost": seed["cost"],
                "who_pushes_back": names[1] if len(names) > 1 else names[0],
                "future_payoff_cluster": f"EC{min(250, ec + 5):03d}",
            }
        tail_events.append(event)
        event_hash = sha(event)
        for index, milestone in enumerate((milestone1, milestone2), 1):
            cid = int(milestone["chapter_id"])
            creates = deepcopy(milestone["artifact_creates"])
            refs = deepcopy(milestone["artifact_refs"])
            card_transitions = deepcopy(transitions if index == 2 else [])
            card = {
                "chapter_id": cid, "chapter_title": milestone["chapter_title"],
                "arc_id": phase, "story_block_id": event["story_block_id"], "macro_group_id": event["macro_group_id"],
                "cluster_id": eid, "cluster_name": seed["title"], "timeline_years": when[:4],
                "timeline_start": when, "timeline_end": when,
                "chapter_role_v2": role if index == 1 else "two_chapter_payoff",
                "structure_template": "MANUAL_TWO_CHAPTER_EVENT_V15", "chapter_goal": milestone["chapter_goal"],
                "chapter_must_include": milestone["must_include"], "chapter_must_not_include": milestone["must_not_include"],
                "chapter_ending": milestone["ending"], "must_resolve_this_chapter": card_transitions,
                "detailed_synopsis": milestone["detailed_synopsis"], "scene_location": location,
                "scenes": deepcopy(milestone["scenes"]), "artifact_creates": creates, "artifact_refs": refs,
                "participants": deepcopy(milestone["participants"]), "allowed_roles": deepcopy(milestone["participants"]),
                "forbidden_roles": ["未铺垫的终极反派", "万能黑客", "突然出现的神秘证人"],
                "exact_action_sequence": deepcopy(milestone["action_sequence"]), "info_gap_use": milestone["info_gap_use"],
                "opponent_reaction": milestone["opponent_reaction"], "immediate_payoff": milestone["visible_payoff"],
                "state_changes": card_transitions, "state_transitions": card_transitions,
                "source_milestone_sha256": sha(milestone), "source_event_sha256": event_hash,
                "core_payoff": event["core_payoff"], "cluster_outcome": event["cluster_outcome"],
                "main_opponent": opponent_name, "prev_life_tragedy": event["prev_life_tragedy"],
                "info_gap_from_prev_life": info_gap, "this_life_revenge": seed["choice"],
                "romance_state": event["romance_state"], "canonical_cast": deepcopy(cast),
                "cluster_span_start": ch1, "cluster_span_end": ch2, "cluster_chapter_index": index,
                "cluster_chapter_total": 2, "target_chinese_chars": 1400,
                "generated_by": "manual_architecture", "compiled_by": VERSION, "manual_edits": ["manual tail reconstruction"],
                "planning_version": VERSION, "theme_contract": theme_contract,
                "structural_normalizations": ["no_raw_state_literals_in_prose", "chapter_bound_to_manual_milestone"],
                "character_lifecycle": {},
            }
            tail_cards.append(card)
    package = {
        "status": "validated_candidate_pending_compiler", "formal_promotion": False,
        "story_memory_write": False, "neo4j_write": False,
        "continuity_anchor": {"chapter": 270, "date": "1993-09-17", "open_threads": ["BA-83-11原记录箱号为空", "CR-41缺申请页"]},
        "event_clusters": tail_events, "chapter_cards": tail_cards,
        "chapter_synopses": [{k: deepcopy(v) for k, v in card.items() if k != "character_lifecycle"} for card in tail_cards],
    }
    return prefix_events + tail_events, prefix_cards + tail_cards, package


def main() -> None:
    events_path = OUT / "event_clusters_v2.json"
    cards_path = OUT / "master_ctx_cards_v2.json"
    synopses_path = OUT / "chapter_synopses_v5_qwen_500.json"
    events = load(events_path)
    cards = load(cards_path)
    prefix_events, prefix_cards = normalize_frozen_identity_metadata(
        deepcopy(events[:135]), deepcopy(cards[:270]),
    )
    new_events, new_cards, package = build_tail(prefix_events, prefix_cards)
    for path in (events_path, cards_path, synopses_path):
        # Keep the backup name short enough for legacy Windows MAX_PATH.
        target = OUT / f"{path.name}.pre_v16_20260827"
        if not target.exists():
            shutil.copy2(path, target)
    dump(events_path, new_events)
    dump(cards_path, new_cards)
    dump(synopses_path, [{k: deepcopy(v) for k, v in card.items() if k != "character_lifecycle"} for card in new_cards])
    dump(OUT / "isolated_candidate_plan_271_500.json", package)
    dump(OUT / "body_generation" / "rewrite_plan_EC136_EC250.json", {
        "version": VERSION, "range": [136, 250], "continuity_anchor": package["continuity_anchor"],
        "items": [{
            "cluster_id": event["cluster_id"], "chapter_span": event["chapter_span"], "name": event["name"],
            "timeline_years": event["timeline_years"], "story_block_title": event["story_block_title"],
            "irreplaceable_progress_point": event["resolves"][0], "cluster_outcome": event["cluster_outcome"],
            "next_event_hook": event["next_event_hook"],
        } for event in package["event_clusters"]],
    })
    dump(OUT / "body_generation" / "frozen_prefix_lock_v16.json", {
        "version": VERSION,
        "purpose": "允许只生成EC136以后正文时，将已完成正文对应的旧规划校验债务与新尾段错误隔离",
        "event_boundary": 135,
        "chapter_boundary": 270,
        "prefix_events_sha256": sha(new_events[:135]),
        "prefix_cards_sha256": sha(new_cards[:270]),
        "identity_repairs": [
            "维克多·斯特林→维克多·兰斯",
            "8组核心人物重复character_id归并到人物圣经主ID",
        ],
        "prose_mutated": False,
    })
    print(json.dumps({
        "events": len(new_events), "cards": len(new_cards), "frozen_events": 135,
        "frozen_cards": 270, "rewritten_events": len(package["event_clusters"]),
        "rewritten_cards": len(package["chapter_cards"]), "first_tail": package["event_clusters"][0]["name"],
        "last_tail": package["event_clusters"][-1]["name"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

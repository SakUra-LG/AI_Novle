#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V2 事件簇生成（迁移版，支持人工输入题材约束）。

目标：
1) 保持原 V2 输出结构不变（event_clusters_v2.json / global_seed_plan_v2.txt）；
2) 在生成前允许人工输入：
   - 主题/题材
   - 简要背景（如：歌手、娱乐圈）
   - 主角名字约束（可多个，不要求区分女主/男主）
   - 额外限制
"""

import argparse
from difflib import SequenceMatcher
import hashlib
import os
import json
import re
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bert_excitation_train.scripts.smart_sample_search import search_and_adapt_samples
import bert_excitation_train.scripts.generate_event_clusters_v2 as legacy_v2
from bert_excitation_train.scripts.v2.theme_constraints import (
    BACKGROUND as DEFAULT_BACKGROUND,
    MAIN_PROTAGONIST,
    THEME as DEFAULT_THEME,
    attach_theme_contract,
    configure_theme_contract,
    constraints_text,
    protagonists_arg,
)

OUTPUT_DIR = os.getenv("V2_OUTPUT_DIR", legacy_v2.OUTPUT_DIR)
legacy_v2.OUTPUT_DIR = OUTPUT_DIR

SPECIFIC_DEATH_METHOD_PATTERN = (
    r"车祸|交通事故|坠楼|跳楼|从.{0,8}跳下|溺水|"
    r"服药自杀|吞药自杀|服药过量|吞药过量|药物过量|"
    r"被注射|强行注射|注射.{0,12}(?:致死|死亡|身亡)|针剂.{0,12}(?:致死|死亡|身亡)|"
    r"中毒|枪杀|病逝|事故身亡|心脏骤停"
)


def generate_global_seed_plan_v2() -> str:
    """兼容旧调用：委托给旧实现。"""
    return legacy_v2.generate_global_seed_plan_v2()


def _parse_protagonists(raw: str) -> List[str]:
    """
    将用户输入的主角名字约束解析为列表。
    支持逗号/顿号/分号/换行分隔；忽略空项；去重但保序。
    """
    if not raw:
        return []
    parts: List[str] = []
    for chunk in raw.replace("，", ",").replace("、", ",").replace("；", ",").replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    # 换行进一步拆分
    expanded: List[str] = []
    for p in parts:
        expanded.extend([x.strip() for x in p.splitlines() if x.strip()])
    seen: set[str] = set()
    out: List[str] = []
    for name in expanded:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _pick_legacy_leads(protagonists: List[str], fallback_heroine: str, fallback_hero: str) -> tuple[str, str]:
    """
    legacy 模块仍依赖 HEROINE_NAME / HERO_NAME 两个占位名做 prompt 锚点。
    这里从主角列表里取前两个做兼容映射；若不足两个则用 fallback 补齐。
    """
    heroine = protagonists[0] if len(protagonists) >= 1 else fallback_heroine
    hero = protagonists[1] if len(protagonists) >= 2 else fallback_hero
    return heroine, hero

def _ask_interactive(defaults: Dict[str, str]) -> Dict[str, str]:
    print("\n=== V2 题材输入（可直接回车使用默认值）===")
    theme = input(f"主题/题材 [{defaults['theme']}]: ").strip() or defaults["theme"]
    background = input(f"简要背景 [{defaults['background']}]: ").strip() or defaults["background"]
    default_protag = defaults.get("protagonists", "") or f"{defaults.get('heroine_name','')},{defaults.get('hero_name','')}".strip(",")
    protagonists_raw = input(f"主角名字约束（可多个，用逗号/顿号分隔）[{default_protag}]: ").strip() or default_protag
    extra = input("额外限制（可空，示例：禁穿越系统、禁玄幻元素）: ").strip()
    return {
        "theme": theme,
        "background": background,
        "protagonists": protagonists_raw,
        "extra_constraints": extra,
    }


def _load_extra_constraints(path: str | None) -> str:
    if not path:
        return ""
    if not os.path.exists(path):
        print(f"⚠️ 额外限制文件不存在，已忽略：{path}")
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _contains_unnegated_rebirth_disclosure(text: str) -> bool:
    pattern = re.compile(r"(?:告诉|告知|坦白|透露|承认).{0,24}(?:自己)?(?:已经|是|曾经)?重生")
    value = str(text or "")
    for match in pattern.finditer(value):
        prefix = value[max(0, match.start() - 12):match.start()]
        if re.search(r"(?:不|未|没有|并未|不得|不能|不会|绝不|禁止|避免)[^，。；,\n]{0,8}$", prefix):
            continue
        return True
    return False


def _seed_plan_chapter_sections(text: str) -> Dict[int, str]:
    chinese_numbers = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
        "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
    }
    matches = list(re.finditer(r"(?:【)?第\s*(\d+|十二|十一|十|[一二三四五六七八九])\s*章", str(text or "")))
    sections: Dict[int, str] = {}
    for idx, match in enumerate(matches):
        raw_number = match.group(1)
        chapter = int(raw_number) if raw_number.isdigit() else chinese_numbers.get(raw_number)
        if chapter is None:
            continue
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sections[chapter] = text[match.start():end]
    return sections


def _seed_section_field(section: str, label: str) -> str:
    match = re.search(
        rf"(?:\*\*)?{re.escape(label)}[：:](?:\*\*)?\s*([^\r\n]+)",
        str(section or ""),
    )
    return match.group(1).strip(" -*") if match else ""


def _actor_authority_failures(
    text: str,
    cast: List[Dict[str, Any]],
    *,
    scope: str,
) -> List[str]:
    """Reject company powers and employment states that conflict with an actor-only role."""
    value = str(text or "")
    failures: List[str] = []
    for member in cast:
        if not isinstance(member, dict):
            continue
        name = str(member.get("name") or "").strip()
        role = str(member.get("role") or "")
        if not name or not re.search(r"演员|艺人|影后|影帝", role):
            continue
        if re.search(r"制片人|片方负责人|公司高管|选角导演|导演|编剧", role):
            continue
        aliases = [name]
        first_name = name.split()[0] if name.split() else ""
        if first_name and first_name != name:
            aliases.append(first_name)
        actor_pattern = "(?:" + "|".join(re.escape(alias) for alias in aliases) + ")"
        same_clause = r"[^，。；,;\n\r{}\[\]\"]"

        if re.search(
            rf"{actor_pattern}{same_clause}{{0,20}}(?:提议|要求|决定|宣布|推动|下令|安排)"
            rf"{same_clause}{{0,16}}(?:更换|撤换|替换|解雇|开除|任免|调动|调任)"
            rf"{same_clause}{{0,20}}(?:编剧|导演|制片|制作团队|工作人员|部门|人员)",
            value,
            re.S,
        ):
            failures.append(
                f"{scope}让固定演员{name}行使编剧/导演团队或公司人员任免权；"
                "演员可以争取剧本提案权，但不能更换团队、调动人员或决定公司人事"
            )
        if re.search(
            rf"{actor_pattern}{same_clause}{{0,24}}(?:被)?(?:调往|调入|调至|降职到){same_clause}{{0,16}}(?:部门|岗位)|"
            rf"{actor_pattern}{same_clause}{{0,24}}(?:被剥夺|失去){same_clause}{{0,12}}(?:原有职位|公司职位|部门职位|管理职位)",
            value,
            re.S,
        ):
            failures.append(
                f"{scope}把固定演员{name}写成可调岗或降职的公司员工；"
                "演员的损失只能是角色、演员合约、项目合作资格或片方优先合作机会"
            )
        if re.search(
            rf"{actor_pattern}{same_clause}{{0,24}}(?:失去|被剥夺|被撤销){same_clause}{{0,16}}"
            r"(?:项目控制权|项目主导权|编剧任免权|人事权|部门管理权)",
            value,
            re.S,
        ):
            failures.append(
                f"{scope}给固定演员{name}虚构了未在角色表建立的项目管理权；"
                "改成角色、演员合约、项目合作资格或续作谈判机会的得失"
            )
        if re.search(
            rf"{actor_pattern}{same_clause}{{0,24}}(?:退出|失去|被取消|被迫退出)"
            rf"{same_clause}{{0,18}}(?:项目竞标|竞标资格|项目投标|投标资格)",
            value,
            re.S,
        ):
            failures.append(
                f"{scope}把固定演员{name}写成参与项目竞标/投标的公司主体；"
                "演员只能失去试镜、角色、演员合约或片方合作谈判机会"
            )
        if re.search(
            rf"{actor_pattern}{same_clause}{{0,24}}(?:失去|被取消|被剥夺)"
            rf"{same_clause}{{0,16}}(?:剧本参与权|剧本参与资格|剪辑参与权|创作参与权|项目顾问资格|幕后顾问资格)|"
            rf"{actor_pattern}{same_clause}{{0,24}}(?:提出|争取|要求|申请)"
            rf"{same_clause}{{0,18}}(?:项目顾问|幕后顾问|剧本顾问|制作顾问|加入(?:剧本)?创作(?:小组|团队)|加入编剧(?:组|团队))",
            value,
            re.S,
        ):
            failures.append(
                f"{scope}给固定演员{name}虚构了角色表未建立的剧本创作权或项目顾问职位；"
                "演员的后续得失应是演员合约、试镜资格或片方合作谈判机会"
            )
        if re.search(
            rf"{actor_pattern}{same_clause}{{0,24}}(?:要求|申请|争取|加入|进入|获得)"
            rf"{same_clause}{{0,18}}(?:制片委员会|制作委员会|项目委员会|决策委员会)(?:席位)?",
            value,
            re.S,
        ):
            failures.append(
                f"{scope}让固定演员{name}加入制片/项目决策委员会；"
                "演员只能谈判自己的表演合约与有限剧本提案条款，不能取得片方治理席位"
            )
    return failures


def _contains_vague_past_accusation(text: str) -> bool:
    return bool(re.search(
        r"(?:揭露|指出|指控|质疑|暗示|直指).{0,55}(?:"
        r"(?:过去|过往|曾经|当年|过去一年).{0,35}"
        r"(?:拒绝合作|阻碍|打压|排挤|操控|违规|黑幕|不当操作|不当行为|操作|口碑|声誉|信誉|新人发展)|"
        r"(?:拒绝合作|阻碍新人|打压新人|排挤新人).{0,18}(?:旧事|旧账))",
        str(text or ""),
        re.S,
    ) or re.search(
        r"(?:揭露|指出|指控|质疑|暗示|声称).{0,35}(?:曾|私下|暗中)"
        r".{0,24}(?:接触|接洽|争取).{0,24}(?:剧组|电影|项目|主演位置|角色)",
        str(text or ""),
        re.S,
    ))


def _contains_hearsay_payoff(text: str) -> bool:
    return bool(re.search(
        r"(?:利用|借助|援引|提及|散布|抓住).{0,30}(?:违约|负面|丑闻|不和|耍大牌).{0,10}(?:传闻|传言|爆料|风声)|"
        r"(?:违约|负面|丑闻|不和|耍大牌).{0,10}(?:传闻|传言|爆料|风声)",
        str(text or ""),
        re.S,
    ))


def _has_authorized_business_loss(text: str, authority_names: Optional[List[str]] = None) -> bool:
    authority_terms = [r"片方", r"制片公司", r"制片人", r"公司高层", r"项目方", r"工作室"]
    for name in authority_names or []:
        clean = str(name or "").strip()
        if not clean:
            continue
        authority_terms.append(re.escape(clean))
        first_name = clean.split()[0] if clean.split() else ""
        if first_name and first_name != clean:
            authority_terms.append(re.escape(first_name))
    authority = "(?:" + "|".join(dict.fromkeys(authority_terms)) + ")"
    decision = r"(?:宣布|决定|取消|终止|拒绝|驳回|不再续约|不予续约|撤销|收回|结束)"
    resource = r"(?:演员合约|合作|签约|续作|谈判|优先权|优先资格|项目资格|项目机会)"
    value = str(text or "")
    return bool(
        re.search(rf"{authority}.{{0,45}}{decision}.{{0,65}}{resource}", value, re.S)
        or re.search(rf"{resource}.{{0,35}}(?:被|由){authority}.{{0,25}}{decision}", value, re.S)
    )


def _has_actual_acting_action(text: str) -> bool:
    value = str(text or "")
    return bool(re.search(
        r"(?:完成|进行|开始|当场|现场|主动要求).{0,24}(?:表演|试戏|角色演绎|台词演绎|独白)|"
        r"即兴.{0,12}(?:表演|演绎|独白|台词)|"
        r"(?:表演|演绎|试演|饰演|演出).{0,18}(?:角色|台词|独白|情绪|片段|场景)",
        value,
        re.S,
    ))


def _seed_plan_semantic_failures(
    plan: str,
    *,
    total_chapters: int,
    extra_constraints: str = "",
) -> List[str]:
    """Catch blueprint choices that inevitably push later stages into the wrong genre."""
    text = str(plan or "").strip()
    failures: List[str] = []
    if not text:
        return ["主线蓝图为空"]
    if "【固定角色表】" in text:
        text = text[text.index("【固定角色表】"):]
    text = text.split("【人工约束】", 1)[0].strip()

    parsed_seed_cast = _canonical_cast_from_seed_plan(text)
    parsed_alignments = {member.get("alignment") for member in parsed_seed_cast}
    if "固定角色表" in text and not {"protagonist", "opponent", "ally"}.issubset(parsed_alignments):
        failures.append("固定角色表无法解析为主角、核心对手和关键盟友三项；每项必须有唯一姓名与明确身份")
    failures.extend(_actor_authority_failures(text, parsed_seed_cast, scope="蓝图"))
    first_chapter_marker = re.search(r"(?:【)?第\s*1\s*章", text)
    fixed_cast_context = text[:first_chapter_marker.start()] if first_chapter_marker else text
    for member in parsed_seed_cast:
        role = str(member.get("role") or "")
        name = str(member.get("name") or "")
        if (
            str(member.get("alignment") or "").casefold() == "opponent"
            and re.search(r"影后|演员", role)
            and "助理" in role
        ):
            failures.append(
                f"固定对手身份自相矛盾：{member.get('name')}不能同时是演员/影后与助理；"
                "保留一个主要身份，其他对手职能交给不命名的职位角色"
            )
        if (
            name
            and str(member.get("alignment") or "").casefold() == "opponent"
            and re.search(r"影后|演员", role)
            and not re.search(r"制片人|片方负责人", role)
            and re.search(
                rf"{re.escape(name)}.{{0,35}}(?:签署.{{0,12}}(?:协议|合同|合约)|决定合同条款|批准合约)",
                text,
                re.S,
            )
        ):
            failures.append(
                f"固定对手{name}只是演员/影后，无权签署或批准主角合约；合同必须由片方或制片方决定"
            )
        if (
            name
            and str(member.get("alignment") or "").casefold() == "protagonist"
            and re.search(r"演员|艺人", role)
            and re.search(
                rf"{re.escape(name)}.{{0,35}}(?:独立执导|执导邀约|成为导演|导演职位|制片人职位)",
                text,
                re.S,
            )
        ):
            failures.append(
                f"主角{name}的固定身份是演员，蓝图却让其突然转任导演/制片人；收益必须仍是演员合约、项目选择权或创作参与权"
            )
        if name and str(member.get("alignment") or "").casefold() == "ally":
            ally_pattern = re.escape(name)
            alignment_context = re.sub(
                r"(?:从未|没有|并未|绝未|不曾)[^，。；\n]{0,45}",
                "",
                fixed_cast_context,
            )
            if re.search(
                rf"{ally_pattern}.{{0,40}}(?:背叛|毁掉|陷害|合谋|联手|联合|勾结)|"
                rf"(?:击败|摧毁|复仇|清算|对付).{{0,35}}{ally_pattern}",
                alignment_context,
                re.S,
            ):
                failures.append(
                    f"固定角色表阵营冲突：关键盟友{name}同时被写成前世合谋者、背叛者或主角复仇目标；"
                    "盟友不能与核心对手共用同一反派身份"
                )
    if re.search(r"欲望[：:].{0,45}(?:摧毁|毁掉).{0,16}(?:声誉|名誉|口碑)", fixed_cast_context, re.S):
        failures.append("固定角色表把主角目标写成摧毁声誉/名誉，容易滑向舆论线；目标必须是夺回角色、合约与当前职业资源")

    if total_chapters <= 12:
        chapter_sections = _seed_plan_chapter_sections(text)
        opponent_member = next(
            (
                member for member in parsed_seed_cast
                if str(member.get("alignment") or "").casefold() == "opponent"
            ),
            {},
        )
        opponent_name = str(opponent_member.get("name") or "")
        opponent_role = str(opponent_member.get("role") or "")
        for chapter, section in chapter_sections.items():
            failures.extend(_actor_authority_failures(
                section,
                parsed_seed_cast,
                scope=f"短篇第{chapter}章",
            ))
            if (
                opponent_name
                and re.search(r"影后|影帝|演员|艺人", opponent_role)
                and not re.search(r"选角导演|导演|制片人|片方负责人", opponent_role)
                and re.search(
                    rf"{re.escape(opponent_name)}.{{0,35}}(?:宣布|决定|指定).{{0,28}}"
                    r"(?:取消.{0,8}资格|淘汰|换角|出演|接替|角色归属|将角色交给|把角色交给)",
                    section,
                    re.S,
                )
            ):
                failures.append(
                    f"短篇第{chapter}章让演员/影后对手越权宣布淘汰或分配角色；"
                    "她只能施压、争抢或嘲讽，决定必须由选角导演、导演、制片人或片方作出"
                )
            if chapter >= 3 and _contains_vague_past_accusation(section):
                failures.append(
                    f"短篇第{chapter}章靠概括对手过去拒绝合作、打压新人或影响口碑来清算；"
                    "必须改用本章现场表演、当前合同条款、公开规则或对手当场动作"
                )
            if chapter >= 3 and _contains_hearsay_payoff(section):
                failures.append(
                    f"短篇第{chapter}章依赖未经当场证实的旧传闻或爆料翻盘；"
                    "必须只使用当前表演、公开规则、现有合同条款或对手当场动作"
                )
            if chapter >= 2 and re.search(
                r"(?:怎么|为何|为什么).{0,8}(?:还没死|没有死|还活着)|"
                r"(?:你|她|他).{0,8}(?:本该|应该|明明已经).{0,8}(?:死|身亡)",
                section,
                re.S,
            ):
                failures.append(
                    f"短篇第{chapter}章让对手或配角知道主角前世死亡；"
                    "除重生主角外，今生人物不能拥有上一条时间线的记忆"
                )
        first_match = re.search(r"(?:第一章|第\s*1\s*章)[\s\S]*?(?=第二章|第\s*2\s*章)", text)
        second_match = re.search(r"(?:第二章|第\s*2\s*章)[\s\S]*?(?=第三章|第\s*3\s*章)", text)
        first = first_match.group(0) if first_match else ""
        second = second_match.group(0) if second_match else ""
        first_section = chapter_sections.get(1, first)
        first_body = re.sub(
            r"^(?:【)?第\s*(?:1|一)\s*章(?:[^】\n]*】)?\s*[：:]?\s*",
            "",
            str(first_section or ""),
            count=1,
        )
        first_result = _seed_section_field(first_section, "本章结果")
        if not first_body or not re.search(r"死亡|身亡|死于|生命结束|心跳停止|咽气|自杀", first_result or first_body):
            failures.append("短篇第1章必须明确写到上一世死亡，不能从重生后试镜开篇")
        if first_body and not re.search(SPECIFIC_DEATH_METHOD_PATTERN, first_body):
            failures.append("短篇第1章正文没有写明具体死亡方式；章节标题中的‘死亡’不算实际发生")
        death_method_categories = [
            label for label, pattern in (
                ("traffic", r"车祸|交通事故"),
                ("fall", r"坠楼|跳楼|从.{0,8}跳下"),
                ("drown", r"溺水"),
                ("overdose", r"服药自杀|吞药自杀|服药过量|吞药过量"),
                ("poison", r"中毒"),
                ("shooting", r"枪杀"),
                ("illness", r"病逝|心脏骤停"),
            )
            if re.search(pattern, first_body)
        ]
        if len(death_method_categories) > 1:
            failures.append("短篇第1章出现两种互相冲突的死亡方式；全书只能保留一种明确死法")
        if re.search(r"(?:联手|联合|合谋|勾结).{0,12}经纪人|经纪人.{0,12}(?:联手|联合|合谋|勾结)", text, re.S):
            if not re.search(
                r"经纪人.{0,35}(?:撤回|解除|终止|抛弃|背叛|切断|取消|拒绝|威胁|逼迫|"
                r"转签|交给|站队|倒向|删除|封锁|抢走|夺走)",
                first_body,
                re.S,
            ):
                failures.append(
                    "短篇第1章未兑现题材中的合谋：经纪人与核心对手联手毁掉主角，"
                    "但本章没有让经纪人实施具体背叛动作"
                )
        if first and re.search(r"重生(?:后|醒来|回到)|确认重生", first):
            failures.append("短篇第1章不得进入重生后的当前时间线")
        if not second or not re.search(r"重生|回到.{0,12}(?:前|那天)|上一世", second):
            failures.append("短篇第2章必须明确确认重生")
        if re.search(r"(?:联手|联合|合谋|勾结).{0,12}经纪人|经纪人.{0,12}(?:联手|联合|合谋|勾结)", text, re.S):
            if not re.search(
                r"(?:解除|终止|撤销|取消).{0,16}(?:经纪|代理)(?:合同|关系|授权)?|"
                r"(?:经纪|代理)(?:合同|关系|授权)?.{0,16}(?:解除|终止|撤销|取消)",
                second,
                re.S,
            ):
                failures.append(
                    "短篇第2章没有切断前世背叛经纪人的代理权；确认重生后应立即解除旧代理，再直联关键盟友完成首次部署"
                )
        if second and re.search(r"试镜现场|进入试镜|正式签约|当场反杀|开始复仇", second):
            failures.append("短篇第2章只能觉醒和首次部署，不得进入正式试镜或反杀")
        if second and re.search(r"终选|复试|晋级|获得.{0,12}(?:角色|资格|合约)|签约", second):
            failures.append("短篇第2章不得提前获得终选、复试、角色或合约；只能确认重生并完成首次部署")
        structured_results = [
            _seed_section_field(section, "本章结果")
            for chapter, section in chapter_sections.items()
            if chapter >= 3
            and _seed_section_field(section, "本章结果")
        ]
        if structured_results:
            present_timeline = "\n".join(structured_results)
        else:
            present_start = re.search(r"(?:第三章|第\s*3\s*章)", text)
            present_timeline = text[present_start.start():] if present_start else text
            present_timeline = re.split(r"【终局回收】|终局回收[：:]", present_timeline, maxsplit=1)[0]
        role_gain_hits = re.findall(
            r"(?:获得|拿下|签下|成为|正式接替|成功接替).{0,18}(?:女主角|主演)(?:角色|合约|位置)?",
            present_timeline,
        )
        role_gain_hits = [
            hit for hit in role_gain_hits
            if not re.search(r"(?:多部|[两三四五六七八九十\d]+部)(?:电影|影片)", hit)
        ]
        role_loss_hits = re.findall(
            r"(?:失去|退出|调离|剥夺|换下|撤下).{0,18}(?:女主角|主演|角色位置|角色)",
            present_timeline,
        )
        if len(role_gain_hits) > 1 or len(role_loss_hits) > 1:
            failures.append(
                "短篇多章重复结算同一主演角色；阶段收益必须从复试/选择权/条件优势逐级升级，"
                "同一角色或合约只能正式授予一次，已退出项目的对手不得后章无解释回场"
            )
        if "固定角色表" in text:
            core_resource_chapter = total_chapters - 2 if total_chapters >= 5 else total_chapters
            protagonist_role = next(
                (
                    str(member.get("role") or "")
                    for member in parsed_seed_cast
                    if str(member.get("alignment") or "").casefold() == "protagonist"
                ),
                "",
            )
            authority_names = [
                str(member.get("name") or "")
                for member in parsed_seed_cast
                if re.search(r"制片人|片方负责人|公司高层", str(member.get("role") or ""))
            ]
            opponent_aliases = [opponent_name] if opponent_name else []
            if opponent_name and opponent_name.split()[0] != opponent_name:
                opponent_aliases.append(opponent_name.split()[0])
            opponent_alias_pattern = "(?:" + "|".join(
                re.escape(alias) for alias in opponent_aliases
            ) + ")" if opponent_aliases else r"(?:固定对手|对手)"
            for chapter in range(3, total_chapters + 1):
                section = chapter_sections.get(chapter, "")
                if not section:
                    failures.append(f"短篇蓝图缺少第{chapter}章完整规划")
                    continue
                result_field = _seed_section_field(section, "本章结果")
                reaction_field = _seed_section_field(section, "对手反应")
                action_field = _seed_section_field(section, "主角行动")
                scene_field = _seed_section_field(section, "场景")
                loss_field = "\n".join((reaction_field, result_field))
                if re.search(r"演员|艺人", protagonist_role) and re.search(
                    r"(?:提议|要求|决定|宣布|推动|下令|安排).{0,18}"
                    r"(?:更换|撤换|替换|解雇|开除|任免|调动|调任).{0,20}"
                    r"(?:编剧|导演|制片|制作团队|工作人员|部门|人员)",
                    action_field,
                ):
                    failures.append(
                        f"短篇第{chapter}章让固定演员主角行使团队或公司人事权；"
                        "演员只能提出剧本内容建议，不能更换团队或调动人员"
                    )
                if re.search(r"演员|艺人", protagonist_role) and re.search(
                    rf"(?:要求|提议|推动).{{0,24}}(?:{opponent_alias_pattern}|固定对手|对手)"
                    r".{0,18}(?:旧合同|合同|合约).{0,14}(?:重新评估|重审|审查|取消|终止)|"
                    rf"(?:要求|提议|推动).{{0,24}}(?:重新评估|重审|审查|取消|终止)"
                    rf".{{0,18}}(?:{opponent_alias_pattern}|固定对手|对手).{{0,12}}(?:合同|合约)",
                    action_field,
                    re.S,
                ):
                    failures.append(
                        f"短篇第{chapter}章让固定演员主角要求重审或取消对手合同；"
                        "主角只能谈判自己的演员合约，对手是否续约必须由片方基于当前席位决策自行决定"
                    )
                if re.search(r"演员|艺人", protagonist_role) and re.search(
                    rf"(?:要求|提议|推动).{{0,22}}(?:将|把)?{opponent_alias_pattern}"
                    r".{0,16}(?:剔除|移出|排除|踢出).{0,18}(?:系列片|后续项目|项目|剧组)",
                    action_field,
                    re.S,
                ):
                    failures.append(
                        f"短篇第{chapter}章让固定演员主角要求把对手剔出系列片/项目；"
                        "主角只能争取自己的合约，片方必须自行决定不再与对手合作"
                    )
                has_gain = bool(re.search(
                    r"进入终选|进入复试|签约|正式出演|"
                    r"(?:获得|拿下|赢得|争取到|获准|取得)[^，。；,\n]{0,18}"
                    r"(?:角色|合约|资格|职位|合作|项目|控制权|选择权|发言权|创作权|参与权|自主权|提案权|剪辑权|谈判权|优先权|机会|权限|席位)",
                    result_field,
                ))
                has_loss = bool(re.search(
                    r"被制止|无法干预|提议被拒|被排除|被撤出|终止合作|退出项目|"
                    r"(?:失去|错失|丧失)[^，。；,\n]{0,18}"
                    r"(?:角色|合约|资格|职位|合作|项目|控制权|选择权|发言权|创作权|参与权|自主权|提案权|剪辑权|谈判权|优先权|机会|权限|席位|干预权|主导权)",
                    loss_field,
                ))
                if not (has_gain and has_loss):
                    failures.append(
                        f"短篇第{chapter}章没有双向职业结果；必须明确主角新增的资格/合约/权限/合作，"
                        "以及固定对手当章失去的职业利益"
                    )
                stage_input = "\n".join((scene_field, action_field))
                if (
                    re.search(r"(?:获得|拿到|赢得|进入).{0,10}复试(?:资格)?", result_field)
                    and re.search(r"复试现场|完成复试|参加复试|进入复试|第二轮复试|准备.{0,8}复试", stage_input)
                ):
                    failures.append(
                        f"短篇第{chapter}章阶段倒置：行动已经在复试，却到结果才获得复试资格；"
                        "应由初试/试镜行动赢得复试资格，或由复试行动赢得终选资格"
                    )
                if (
                    re.search(r"(?:获得|拿到|赢得|进入).{0,10}终选(?:资格)?", result_field)
                    and re.search(r"终选现场|完成终选|参加终选|进入终选", stage_input)
                ):
                    failures.append(
                        f"短篇第{chapter}章阶段倒置：行动已经在终选，却到结果才获得终选资格"
                    )
                if chapter == 3 and re.search(r"复试现场|参加复试|完成复试|终选现场|参加终选|完成终选", stage_input):
                    failures.append(
                        "短篇第3章必须从今生第一轮正式试镜/初试开始，不能跳过入口过程直接出现在复试或终选"
                    )
                formal_role_gain = bool(re.search(
                    r"(?:获得|拿下|成为|正式出演|正式签约).{0,18}(?:女主角|主演|核心角色|角色合约)|"
                    r"(?:女主角|主演|核心角色).{0,12}(?:归属|合约)|"
                    r"(?:正式获得|正式拿下).{0,12}(?:该角色|这个角色|角色合约)",
                    result_field,
                ))
                if re.search(r"试镜资格|终选资格|复试资格", result_field):
                    formal_role_gain = False
                if re.search(
                    r"(?:多部|[两三四五六七八九十\d]+部)(?:电影|影片)(?:主演|演员)合约",
                    result_field,
                ):
                    formal_role_gain = False
                if chapter == core_resource_chapter and not formal_role_gain:
                    failures.append(
                        f"短篇第{chapter}章必须完成全书唯一一次核心角色/角色合约正式授予，不能仍停在复试或终选"
                    )
                if chapter == core_resource_chapter and not _has_actual_acting_action(action_field):
                    failures.append(
                        f"短篇第{chapter}章核心角色授予缺少实际试戏/表演；演员不能只靠剧本建议或口头主张拿到角色"
                    )
                if chapter == core_resource_chapter and re.search(
                    r"(?:宣布|公布).{0,12}(?:最终人选|主演名单|女主角人选)",
                    scene_field,
                ):
                    failures.append(
                        f"短篇第{chapter}章场景在主角表演前就宣布最终人选，因果顺序倒置；"
                        "场景只能写最终试戏开始，角色决定必须放在本章结果"
                    )
                if (
                    chapter == 3
                    and re.search(r"演员|艺人", protagonist_role)
                    and not _has_actual_acting_action(action_field)
                ):
                    failures.append(
                        "短篇第3章首次职业反击缺少实际试戏/表演；"
                        "必须让演员在镜头前完成表演并凭当前实力拿到入口资格"
                    )
                if chapter == core_resource_chapter and re.search(
                    r"退居配角|改演配角|转为配角|获得配角|出演配角",
                    "\n".join((reaction_field, result_field)),
                ):
                    failures.append(
                        f"短篇第{chapter}章夺回核心角色后立刻补偿对手一个配角，削弱反杀；"
                        "本章应让对手明确退出该项目的角色竞争"
                    )
                if chapter > core_resource_chapter:
                    if formal_role_gain:
                        failures.append(
                            f"短篇第{chapter}章重复或延迟授予核心角色；第{core_resource_chapter}章后必须升级到不同合约权限、项目席位或新合作"
                        )
                    if re.search(r"复试|终选|试镜资格|第二轮试镜", result_field):
                        failures.append(
                            f"短篇第{chapter}章收益层级倒退到复试/终选；必须升级到合约权限、项目席位或新合作"
                        )
                    if opponent_name and re.search(
                        rf"(?:避免|错开).{{0,12}}(?:与)?{opponent_alias_pattern}.{{0,12}}(?:行程|拍摄|排练)|"
                        rf"{opponent_alias_pattern}.{{0,24}}(?:继续|仍).{{0,10}}(?:参与|留在).{{0,10}}(?:剧组|拍摄|排练)",
                        "\n".join((scene_field, action_field, reaction_field)),
                        re.S,
                    ):
                        failures.append(
                            f"短篇第{chapter}章让已失去核心角色的对手无解释继续留在同一项目拍摄/排练；"
                            "后续冲突应转入片方合约或新项目合作层级"
                        )
                    if re.search(
                        r"(?:失去|取消|终止|撤销).{0,24}(?:演员合约|合作|签约|续作|谈判|优先|项目资格|项目机会)",
                        loss_field,
                    ) and not _has_authorized_business_loss(
                        "\n".join((scene_field, action_field, reaction_field, result_field)),
                        authority_names,
                    ):
                        failures.append(
                            f"短篇第{chapter}章只宣称对手失去合作/谈判利益，却没有片方、制片公司或制片人当场作出取消决定"
                        )
                    first_chapter_marker = re.search(r"(?:【)?第\s*1\s*章", text)
                    fixed_context = text[:first_chapter_marker.start()] if first_chapter_marker else ""
                    prior_context = fixed_context + "\n" + "\n".join(
                        chapter_sections.get(prior_chapter, "")
                        for prior_chapter in range(1, chapter)
                    )
                    established_context = prior_context + "\n" + scene_field
                    result_loss_clause = re.split(r"[；;]", result_field, maxsplit=1)
                    actual_loss_field = reaction_field + "\n" + (
                        result_loss_clause[1] if len(result_loss_clause) > 1 else result_field
                    )
                    late_resource_patterns = (
                        (r"演员.{0,4}合约", "演员合约"),
                        (r"优先.{0,6}合作", "优先合作资格"),
                        (r"续作.{0,6}谈判", "续作谈判资格"),
                        (r"项目.{0,6}合作.{0,4}资格", "项目合作资格"),
                        (r"(?:宣传|推广).{0,8}(?:席位|资格|合作)", "宣传合作席位"),
                    )
                    missing_late_resources = [
                        label for pattern, label in late_resource_patterns
                        if re.search(pattern, actual_loss_field) and not re.search(pattern, established_context)
                    ]
                    if missing_late_resources:
                        failures.append(
                            f"短篇第{chapter}章凭空剥夺尚未建立的对手资源：{'、'.join(missing_late_resources)}；"
                            "必须先在固定角色表、前文或本章场景议程中明确该资源原本存在"
                        )
                if chapter == total_chapters and not re.search(
                    r"(?:获得|拿下|签下|签署|得到).{0,18}"
                    r"(?:长期演员合约|长期合作合约|"
                    r"(?:多部|[两三四五六七八九十\d]+部)(?:电影|影片)(?:主演|演员)合约|"
                    r"制片公司长期合作(?:合约)?)",
                    result_field,
                ):
                    failures.append(
                        f"短篇第{chapter}章终局没有实际签下长期演员合约或制片公司长期合作；"
                        "‘签约权、签约机会、候选资格’都不算已经兑现的终局收益"
                    )
                if chapter == total_chapters and re.search(r"颁奖晚宴|颁奖礼|庆功宴|红毯|酒会", scene_field):
                    failures.append(
                        f"短篇第{chapter}章把终局放在颁奖/晚宴等仪式场景；"
                        "改为制片公司签约会议或片方合同会议，让双方职业得失在同一决策中生效"
                    )
                if chapter == total_chapters and re.search(
                    r"(?:失去|取消|终止|撤销).{0,24}(?:优先合作|续作谈判|长期片约|多片约)",
                    loss_field,
                ):
                    first_chapter_marker = re.search(r"(?:【)?第\s*1\s*章", text)
                    fixed_context = text[:first_chapter_marker.start()] if first_chapter_marker else ""
                    prior_story = fixed_context + "\n" + "\n".join(
                        chapter_sections.get(prior_chapter, "")
                        for prior_chapter in range(1, chapter)
                    )
                    resource_patterns = (
                        r"优先.{0,6}合作",
                        r"续作.{0,6}谈判",
                        r"长期.{0,4}片约",
                        r"多片约",
                    )
                    required_resources = [
                        pattern for pattern in resource_patterns
                        if re.search(pattern, loss_field)
                    ]
                    if any(not re.search(pattern, prior_story) for pattern in required_resources):
                        failures.append(
                            f"短篇第{chapter - 1}章没有提前建立第{chapter}章要清算的对手优先合作/续作谈判资源；"
                            "应在固定角色表或本章场景中先明确该演员现有资源，终章才能剥夺"
                        )
            if total_chapters >= 5:
                penultimate_loss = "\n".join((
                    _seed_section_field(chapter_sections.get(total_chapters - 1, ""), "对手反应"),
                    _seed_section_field(chapter_sections.get(total_chapters - 1, ""), "本章结果"),
                ))
                final_loss = "\n".join((
                    _seed_section_field(chapter_sections.get(total_chapters, ""), "对手反应"),
                    _seed_section_field(chapter_sections.get(total_chapters, ""), "本章结果"),
                ))
                for resource_pattern in (
                    r"优先.{0,6}合作",
                    r"续作.{0,6}谈判",
                    r"长期.{0,4}片约",
                    r"多片约",
                ):
                    if re.search(resource_pattern, penultimate_loss) and re.search(resource_pattern, final_loss):
                        failures.append(
                            f"短篇第{total_chapters - 1}章提前结算了终章才应剥夺的优先合作/续作谈判资源；"
                            "本章只能在场景中建立该资源，实际损失必须换成另一项当章职业利益"
                        )
                        break
                if (
                    re.search(r"失去.{0,24}合作.{0,12}谈判", penultimate_loss)
                    and re.search(r"失去.{0,24}(?:优先.{0,8}合作|续作.{0,8}谈判)", final_loss)
                ):
                    failures.append(
                        f"短篇第{total_chapters - 1}章用模糊的‘合作谈判’提前结算了终章‘优先合作’资源；"
                        "前章损失必须改成明确不同的当前项目利益"
                    )

    impossible_memory = bool(re.search(
        r"(?:前世|上一世|临死前).{0,40}(?:录音|视频|文件|截图|邮件).{0,30}"
        r"(?:带回|保留|恢复|还原|播放|提交|作为证据)",
        text,
        re.S,
    ))
    if impossible_memory:
        failures.append("蓝图把前世记忆或材料变成今生可直接使用的物证")

    if _contains_unnegated_rebirth_disclosure(text):
        failures.append("蓝图让主角向盟友或他人直接自曝重生；重生只能作为主角内心信息差")

    if re.search(
        r"经纪人.{0,24}(?:宣布|决定|指定).{0,24}(?:淘汰|替换|换角|角色归属|由.{0,8}出演|退出(?:片方)?项目)",
        text,
        re.S,
    ):
        failures.append("蓝图让经纪人越权宣布淘汰或角色归属；必须由选角导演、导演、制片人或片方负责人决定")

    if re.search(
        r"(?:指出|质疑|暗示|直指|隐喻).{0,40}(?:过往争议|过去.{0,12}行为|曾经.{0,12}违规|曾违规|行为模式|违规操作)",
        text,
        re.S,
    ):
        failures.append("蓝图仍靠泛指对手过往争议或违规行为翻盘；改用当前合同条款、公开试镜规则或当场动作")
    if _contains_vague_past_accusation(text):
        failures.append(
            "蓝图仍靠概括对手过去拒绝合作、打压新人或影响口碑来清算；"
            "必须改用本章现场表演、当前合同条款、公开规则或对手当场动作"
        )
    if _contains_hearsay_payoff(text):
        failures.append("蓝图依赖未经当场证实的旧传闻或爆料翻盘；必须只使用当前表演、公开规则、现有合同条款或对手当场动作")
    if re.search(
        r"(?:利用|借助).{0,24}(?:提供|交给|递交|给出).{0,12}(?:资料|材料|文件|记录|证据)",
        text,
        re.S,
    ):
        failures.append("蓝图依赖盟友或他人临时提供的模糊资料；主角必须靠当前公开规则、现场表演或当场可见条款行动")
    if re.search(
        r"(?:通过|借助|利用).{0,40}(?:帮助|资料|材料|文件|内部记录|证据).{0,45}(?:提交|审查|指控|揭露|证明)",
        text,
        re.S,
    ):
        failures.append("蓝图依赖盟友帮助或旧记录提交审查的证据链；终局必须由当前合同、现场规则或对手当场动作落锤")

    constraint_text = str(extra_constraints or "")
    if "投资" in constraint_text and re.search(
        r"投资人|投资方|拉拢.{0,12}投资|投资.{0,12}(?:施压|介入|撤资|加码)|"
        r"资本.{0,10}(?:施压|介入|撤资|加码)",
        "\n".join(_seed_plan_chapter_sections(text).values()),
        re.S,
    ):
        failures.append("蓝图违反人工限制，仍让投资人、投资方或资本施压参与核心推进")
    if any(token in constraint_text for token in ("调查", "搜证", "匿名爆料", "媒体搜证链")):
        if re.search(
            r"(?:出示|提交|拿出|展示|提供).{0,24}(?:证据|记录|材料)|"
            r"(?:证据|记录|材料).{0,24}(?:证明|揭露|显示).{0,24}(?:私下接触|暗中接触|违规|操控)",
            text,
            re.S,
        ):
            failures.append(
                "蓝图违反人工限制，仍让主角出示或提交对手私下接触、违规操作的证据；"
                "改用当前表演、合同条款或对手当场动作"
            )
        drift_markers = re.findall(
            r"调查|搜证|私密录音|秘密录音|私人邮件|私密邮件|内部邮件|偷拍视频|隐藏文件|匿名爆料|证据打包|舆论压力|"
            r"(?:媒体|采访).{0,24}(?:证据|录音|视频)|播放一段(?:录音|视频)|"
            r"伪造.{0,18}(?:声明|合同|文件|证据)|虚假证据|媒体拍下|登上热搜|热搜|媒体曝光|媒体围攻|"
            r"(?:递出|提交|出示).{0,18}(?:文件|记录).{0,24}(?:不合适|表现|资格|取消)",
            text,
            re.S,
        )
        if drift_markers:
            failures.append(
                "蓝图违反人工限制，仍以调查、录音、视频或媒体证据链推进："
                + "、".join(dict.fromkeys(drift_markers[:5]))
            )
        if re.search(r"发布会|首映礼|媒体采访|媒体关注|媒体追问|记者追问|舆论施压|公众信任|行业信誉", text):
            failures.append(
                "蓝图把发布会、媒体或舆论变化当作核心清算；终局必须在选角、合同或片方会议中落下职业得失"
            )
        if re.search(
            r"(?:揭露|指出|暗示).{0,30}(?:当年|过去|过往).{0,24}(?:操作|行为|操控|黑幕)",
            text,
            re.S,
        ):
            failures.append("蓝图仍靠泛指对手当年操作或过往行为清算；必须用当前合同条款、公开规则或当场动作落锤")
        if re.search(
            r"(?:揭露|公开|曝光|提交).{0,50}(?:贿赂|黑幕|操纵选角|过往记录|过去.{0,12}记录)|"
            r"(?:通过|利用).{0,18}人脉.{0,24}(?:间接证据|记录|揭示真相)",
            text,
            re.S,
        ):
            failures.append(
                "蓝图仍靠无当前来源的贿赂指控、过往记录或人脉间接证据翻盘；"
                "改为表演、合同条款、公开试镜规则或对手当场动作"
            )

    tail = text[-2200:]
    has_loss = bool(re.search(
        r"换角|解约|取消资格|停职|开除|终止合作|被迫退出|"
        r"(?:失去|错失|丧失)[^，。；,\n]{0,16}(?:角色|合约|职位|资格|合作|项目|控制权|干预权|主导权|资源|机会|权限)",
        tail,
    ))
    has_gain = bool(re.search(
        r"签约|恢复资格|角色归属|正式出演|"
        r"(?:拿下|获得|赢得).{0,16}(?:角色|合约|资格|合作|项目|自主权|资源|机会|权限)",
        tail,
    ))
    if not (has_loss and has_gain):
        failures.append("蓝图终局必须同时写明固定对手的现实损失和主角的现实收益")
    return failures[:8]


def _long_seed_plan_semantic_failures(
    plan: str,
    *,
    protagonists: List[str],
) -> List[str]:
    """Validate a runtime long-form blueprint without domain assumptions."""
    text = str(plan or "").strip()
    if not text:
        return ["主线蓝图为空"]
    failures: List[str] = []
    cast = _canonical_cast_from_seed_plan(text)
    alignments = {str(member.get("alignment") or "") for member in cast}
    if not {"protagonist", "opponent", "ally"}.issubset(alignments):
        failures.append(
            "固定角色表必须使用可解析格式，至少逐行写出主角、核心对手、关键盟友及各自身份"
        )
    expected_protagonist = protagonists[0] if protagonists else ""
    parsed_protagonists = {
        str(member.get("name") or "").strip()
        for member in cast if member.get("alignment") == "protagonist"
    }
    if expected_protagonist and expected_protagonist not in parsed_protagonists:
        failures.append(f"固定主角必须是{expected_protagonist}，不得改名")
    names = [str(member.get("name") or "").strip() for member in cast]
    if len(names) != len(set(names)):
        failures.append("固定角色表存在一人多名或重名，所有固定人物必须使用唯一姓名")
    if len([m for m in cast if m.get("alignment") == "opponent"]) < 2:
        failures.append("长篇固定角色表至少需要核心对手与一名分层反派")
    if len([m for m in cast if m.get("alignment") == "ally"]) < 1:
        failures.append("长篇固定角色表至少需要一名具备明确行动能力的盟友")
    has_opening_death = bool(
        re.search(SPECIFIC_DEATH_METHOD_PATTERN, text)
        and re.search(r"死亡|身亡|断气|心跳停止|生命.{0,6}结束|明确死去", text)
    )
    if not has_opening_death:
        failures.append("蓝图没有按本题材写明上一世的具体死亡方式与生命结束")
    has_rebirth_deployment = bool(
        re.search(r"重生|醒来|回到.{0,24}(?:之前|以前|前|当天)|再活一次", text, re.S)
        and re.search(
            r"部署|联系|预约|撤销|取消|收回|拒绝|改掉|切断|更换|冻结|限制|准备",
            text,
        )
    )
    if not has_rebirth_deployment:
        failures.append("蓝图没有明确建立核对现实、确认重生与一个可见的首次部署")
    if not re.search(r"滑稽|自作聪明|嘴硬|黑色幽默|抢功|可笑|荒唐|丑态|自打脸", text):
        failures.append("蓝图缺少坏得滑稽、自作聪明且会亲手留下把柄的反派设计")
    if not re.search(r"八段主线推进|第一段|阶段一", text):
        failures.append("蓝图缺少八段主线推进")
    if not re.search(r"终局回收清单|终局回收", text):
        failures.append("蓝图缺少终局条件回收清单")
    tail = text[-2600:]
    has_final_loss = bool(re.search(
        r"失去|撤销|冻结|终止|退出|交出|剥夺|停职|解约|赔偿|归还",
        tail,
    ))
    has_final_gain = bool(re.search(
        r"拿回|收回|获得|恢复|保住|掌控|签下|取得|赢得|接管",
        tail,
    ))
    if not (has_final_loss and has_final_gain):
        failures.append("终局回收必须同时写明对手最终损失和主角最终收益")
    if re.search(
        r"(?:匿名短信|匿名邮件|神秘人|陌生人).{0,30}(?:给|递|发送|提供).{0,20}(?:关键|决定性|全部).{0,12}(?:证据|文件|真相)",
        text,
        re.S,
    ):
        failures.append("蓝图使用匿名或神秘人物递交决定性证据")
    if re.search(
        r"(?:前世|上一世|临死前).{0,45}(?:录音|视频|文件|截图|邮件).{0,30}"
        r"(?:带回|保留|恢复|还原|播放|提交|作为证据)",
        text,
        re.S,
    ):
        failures.append("蓝图把前世记忆或材料变成今生可直接使用的物证")
    if _contains_unnegated_rebirth_disclosure(text):
        failures.append("蓝图让主角向公众或盟友直接自曝重生")
    return failures[:8]


def _replace_seed_plan_chapter(plan: str, chapter: int, replacement: str) -> str:
    markers = list(re.finditer(r"(?:【)?第\s*(\d+)\s*章", str(plan or "")))
    target_idx = next(
        (idx for idx, marker in enumerate(markers) if int(marker.group(1)) == int(chapter)),
        None,
    )
    if target_idx is None:
        return ""
    start = markers[target_idx].start()
    if target_idx + 1 < len(markers):
        end = markers[target_idx + 1].start()
    else:
        terminal = re.search(r"【终局回收】", plan[start:])
        end = start + terminal.start() if terminal else len(plan)
    cleaned = str(replacement or "").strip()
    cleaned = re.sub(r"^(?:```(?:markdown)?\s*)|(?:```\s*)$", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"(?:\r?\n)?\s*---\s*$", "", cleaned).strip()
    if not re.search(rf"(?:【)?第\s*{int(chapter)}\s*章", cleaned):
        return ""
    return plan[:start] + cleaned + "\n\n---\n\n" + plan[end:].lstrip()


def _normalize_short_seed_terminal_summary(plan: str) -> str:
    """Rebuild the terminal summary from accepted chapter results only."""
    text = str(plan or "")
    marker = "【终局回收】"
    if marker not in text:
        return text
    sections = _seed_plan_chapter_sections(text)
    result_lines = [
        f"- 章节{chapter}已验收结果：{_seed_section_field(section, '本章结果')}"
        for chapter, section in sorted(sections.items())
        if chapter >= 3 and _seed_section_field(section, "本章结果")
    ]
    if not result_lines:
        return text
    start = text.index(marker)
    artificial = text.find("【人工约束】", start)
    end = artificial if artificial >= 0 else len(text)
    summary = marker + "\n" + "\n".join(result_lines) + "\n"
    return text[:start] + summary + text[end:]


def _normalize_short_seed_rebirth_deployment(plan: str) -> str:
    """Make the rebirth chapter close the unnamed-agent betrayal without changing later plot."""
    text = str(plan or "")
    if not re.search(
        r"(?:联手|联合|合谋|勾结).{0,12}经纪人|经纪人.{0,12}(?:联手|联合|合谋|勾结)|"
        r"职位角色[^\n]{0,15}背叛经纪人|背叛经纪人（不命名）",
        text,
        re.S,
    ):
        return text
    sections = _seed_plan_chapter_sections(text)
    section = sections.get(2, "")
    if not section:
        return text
    cast = _canonical_cast_from_seed_plan(text)
    protagonist_name = next(
        (member["name"] for member in cast if member.get("alignment") == "protagonist"),
        "主角",
    )
    opponent_name = next(
        (member["name"] for member in cast if member.get("alignment") == "opponent"),
        "固定对手",
    )
    ally_name = next(
        (member["name"] for member in cast if member.get("alignment") == "ally"),
        "关键盟友",
    )
    title_match = re.search(r"第\s*2\s*章[：:]?([^】\n]*)", section)
    title = (title_match.group(1).strip() if title_match else "") or "重生确认"
    scene = _seed_section_field(section, "场景") or f"{protagonist_name}的公寓，关键试镜前数日"
    replacement = (
        f"【第2章：{title}】\n"
        f"场景：{scene}\n"
        f"主角行动：{protagonist_name}核对手机日期与房间环境，确认自己重生回到关键试镜前；"
        "立即向旧经纪人发出解除代理授权的书面通知，随后绕开旧代理，"
        f"直接联系{ally_name}预约试镜准备会面\n"
        f"对手反应：旧经纪人收到通知后失去代理权；{opponent_name}尚未察觉{protagonist_name}已经改变行动路线\n"
        f"本章结果：{protagonist_name}确认重生，解除旧经纪人的代理授权，并完成与{ally_name}的会面预约"
    )
    return _replace_seed_plan_chapter(text, 2, replacement) or text


def _normalize_short_seed_opening_death(plan: str) -> str:
    """Ensure chapter 1 carries one concrete death method before semantic repair."""
    text = str(plan or "")
    section = _seed_plan_chapter_sections(text).get(1, "")
    if not section:
        return text
    cast = _canonical_cast_from_seed_plan(text)
    protagonist_name = next(
        (member["name"] for member in cast if member.get("alignment") == "protagonist"),
        "主角",
    )
    opponent_name = next(
        (member["name"] for member in cast if member.get("alignment") == "opponent"),
        "固定对手",
    )
    title_match = re.search(r"第\s*1\s*章[：:]?([^】\n]*)", section)
    title = (title_match.group(1).strip() if title_match else "") or "上一世死亡"
    scene = _seed_section_field(section, "场景") or "上一世最后一次关键职业机会现场"
    action = _seed_section_field(section, "主角行动") or f"{protagonist_name}完成最后一次职业争取"
    reaction = _seed_section_field(section, "对手反应") or f"{opponent_name}当场压下{protagonist_name}的机会"
    result = _seed_section_field(section, "本章结果")
    if not re.search(SPECIFIC_DEATH_METHOD_PATTERN, result + "\n" + section):
        result = result.rstrip("。；; ") + f"；{protagonist_name}回到公寓后服药过量自杀，呼吸停止"
    replacement = (
        f"【第1章：{title}】\n"
        f"场景：{scene}\n"
        f"主角行动：{action}\n"
        f"对手反应：{reaction}\n"
        f"本章结果：{result}"
    )
    return _replace_seed_plan_chapter(text, 1, replacement) or text


def _short_seed_chapter_repair_contract(chapter: int, total_chapters: int) -> str:
    core_chapter = total_chapters - 2 if total_chapters >= 5 else total_chapters
    if chapter == 1:
        return (
            "只写上一世职业打击、公开受辱、不可逆损失和具体死亡；禁止重生。"
            "若题材写明经纪人与核心对手联手，经纪人必须在本章实施解除代理、撤回支持、转签角色等具体背叛动作。"
        )
    if chapter == 2:
        return "只写核对日期/环境、内心确认重生并完成联系或预约；禁止进入试镜，禁止获得任何资格、角色或合约，也不向任何人自曝重生。"
    if chapter < core_chapter:
        return (
            "主角必须在镜头前完成真实表演，只获得复试/终选等入口资格；"
            "对手同章失去一次具体干预机会；禁止正式授予核心角色。"
        )
    if chapter == core_chapter:
        return "通过真实试戏、表演、台词演绎或即兴发挥完成全书唯一一次核心角色/角色合约正式授予；主角拿到角色，对手同章失去该角色并退出该项目角色竞争，不能补偿对手配角，也不能只靠剧本建议或口头主张。"
    if chapter == total_chapters - 1:
        return (
            "守住既有角色并新增剧本提案权、合同选择权或演员项目席位；演员可谈判剧本提案条款，但不得加入编剧组或剧本创作团队；"
            "若对手是演员，只能失去演员合约、项目合作资格或续作谈判机会，不能失去项目控制权，禁止再次授予角色。"
            "本章场景要建立对手现有的优先合作/续作谈判资源供终章清算，但本章opponent_loss不得提前写她失去该资源，必须另选当前项目利益。"
        )
    return (
        "终局必须实际签下长期演员合约、多部影片演员合约或制片公司长期演员合作合约；签约权、机会、候选资格不算兑现；"
        "若对手是演员，只能失去片方优先合作、演员项目资格或续作谈判机会，"
        "不能被调岗、降职、参加项目竞标或失去项目管理权；禁止再次授予角色或退回复试/终选。"
    )


def _repair_short_seed_plan_chapters(
    plan: str,
    *,
    total_chapters: int,
    extra_constraints: str,
) -> str:
    candidate = _normalize_short_seed_opening_death(str(plan or ""))
    candidate = _normalize_short_seed_rebirth_deployment(candidate)
    max_repair_rounds = max(8, total_chapters + 3)
    for repair_round in range(1, max_repair_rounds + 1):
        failures = _seed_plan_semantic_failures(
            candidate,
            total_chapters=total_chapters,
            extra_constraints=extra_constraints,
        )
        if not failures:
            return _normalize_short_seed_terminal_summary(candidate)
        if any(
            failure.startswith("固定角色表")
            or failure.startswith("固定对手身份")
            for failure in failures
        ):
            return ""
        chapter_targets = [
            int(match.group(1))
            for failure in failures
            for match in [re.search(r"短篇第(\d+)章", failure)]
            if match
        ]
        if chapter_targets:
            target = chapter_targets[0]
        elif any("重复结算同一主演角色" in failure for failure in failures):
            target = total_chapters
        else:
            return ""
        current_section = _seed_plan_chapter_sections(candidate).get(target, "")
        if not current_section:
            return ""
        seed_cast = _canonical_cast_from_seed_plan(candidate)
        protagonist_name = next(
            (member["name"] for member in seed_cast if member.get("alignment") == "protagonist"),
            "主角",
        )
        opponent_name = next(
            (member["name"] for member in seed_cast if member.get("alignment") == "opponent"),
            "固定对手",
        )
        ally_name = next(
            (member["name"] for member in seed_cast if member.get("alignment") == "ally"),
            "关键盟友",
        )
        fixed_context = candidate.split("【第1章", 1)[0][-2600:]
        chapter_results = {
            chapter: re.sub(r"\s+", " ", section)[:420]
            for chapter, section in _seed_plan_chapter_sections(candidate).items()
            if chapter != target
        }
        relevant = [failure for failure in failures if f"第{target}章" in failure]
        if not relevant:
            relevant = failures
        prompt = f"""
你只修复一部{total_chapters}章重生复仇爽文蓝图中的第{target}章，其他章节与固定角色表都已锁定。

固定角色与题材上下文：
{fixed_context}

其他章节已生效结果，不得重复：
{json.dumps(chapter_results, ensure_ascii=False)}

当前第{target}章：
{current_section}

本章硬职责：{_short_seed_chapter_repair_contract(target, total_chapters)}
当前必须修正：
- {chr(10).join(relevant)}

只输出一个合法JSON对象，不要章节正文、其他章节、解释或代码围栏。字段严格为：
{{"title":"短标题","scene":"具体场景","protagonist_action":"主角主动行动","opponent_reaction":"对手当场反应","result":"第1-2章结果；第3章后可留空","protagonist_gain":"第3章后主角新增的具体职业收益，只写名词短语","opponent_loss":"第3章后对手失去的具体职业利益，只写名词短语"}}
第3章起 protagonist_gain 只能是资格、角色、合约、权限、项目席位或合作；opponent_loss 只能是角色、资格、合约、职位、项目权限、席位或合作机会，禁止写影响力、信任、名誉、尴尬或被边缘化。
  固定主角 {protagonist_name} 的身份不得改变；若她是演员，第5-6章收益只能从“剧本提案权、长期演员合约、新项目签约选择权、制片公司长期合作”中按本章层级选择，禁止剪辑参与权、委员会席位、导演邀约、独立执导或制片人职位。
演员只能提出剧本内容建议，不能更换编剧/导演/制作团队或调动公司人员。若固定对手是演员，她不能被调往部门、剥夺公司职位、参加项目竞标，也不能凭空拥有剧本参与权、剪辑权或幕后/项目顾问职位；她只能失去角色、演员合约、项目合作资格、片方优先合作或续作谈判机会。
演员/影后对手只能施压、争抢或嘲讽，不能宣布取消资格、淘汰、换角或把角色交给别人；这些决定必须由选角导演、导演、制片人或片方作出。
主角是演员，只能谈判和签署自己的合约，不能要求重审、取消对手旧合同或把对手剔出系列片/项目；对手失去核心角色后，不得无解释继续留在同一剧组拍摄/排练，也不要写主角调整日程去避开她。
第5-6章若对手失去合作、续作谈判或片方优先权，opponent_reaction必须写片方、制片公司或制片人当场宣布取消/终止/不再续约，不能只在result凭空宣称失去。第5章场景要提前建立终章拟清算的演员优先合作或续作谈判资源，但第5章opponent_loss不得提前结算这项终章资源，必须失去另一项当前项目利益。
不得使用调查、录音、邮件、内部记录、盟友提供资料、匿名爆料、媒体舆论、过往违规指控、投资人/投资方/资本施压或投资手段；不得出示对手私下接触其他剧组、违规或操控的证据；也不得靠“揭露过去拒绝合作、指出过去一年打压新人、质疑过往不当操作、影响公司口碑”等概括性旧账清算。
""".strip()
        raw = legacy_v2.call_qianwen_api(
            [
                {"role": "system", "content": "你只重写短篇重生爽文蓝图的一个指定章节。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.34,
            top_p=0.68,
        )
        repair_obj = _extract_json_object_maybe(raw)
        title = str(repair_obj.get("title") or "").strip() if repair_obj else ""
        scene = str(repair_obj.get("scene") or "").strip() if repair_obj else ""
        action = str(repair_obj.get("protagonist_action") or "").strip() if repair_obj else ""
        reaction = str(repair_obj.get("opponent_reaction") or "").strip() if repair_obj else ""
        if target <= 2 and not reaction:
            reaction = f"{opponent_name}尚未介入当前行动"
        if repair_obj and title and scene and action and reaction:
            if target == 1:
                aliases = [opponent_name]
                if opponent_name.split()[0] != opponent_name:
                    aliases.append(opponent_name.split()[0])
                opponent_pattern = "(?:" + "|".join(re.escape(alias) for alias in aliases) + ")"
                authority_drift = re.compile(
                    rf"({opponent_pattern}.{{0,24}})(?:宣布|决定|指定)(.{{0,24}}"
                    r"(?:出演|接替|角色归属|由她出演|取消.{0,8}资格|淘汰|换角|将角色交给|把角色交给))",
                    re.S,
                )
                action = authority_drift.sub(r"\1施压要求\2", action)
                reaction = authority_drift.sub(r"\1施压要求\2", reaction)
                if (
                    re.search(r"(?:联手|联合|合谋|勾结).{0,12}经纪人|经纪人.{0,12}(?:联手|联合|合谋|勾结)", candidate, re.S)
                    and not re.search(
                        r"经纪人.{0,35}(?:撤回|解除|终止|抛弃|背叛|切断|取消|拒绝|威胁|逼迫|"
                        r"转签|交给|站队|倒向|删除|封锁|抢走|夺走)",
                        action + "\n" + reaction,
                        re.S,
                    )
                ):
                    reaction = (
                        reaction.rstrip("。；; ")
                        + f"；{protagonist_name}的经纪人当场撤回代理支持，并转而站到{opponent_name}一边"
                    )
            if target == 2:
                scene = f"{protagonist_name}的公寓，关键试镜前数日"
                if re.search(r"(?:联手|联合|合谋|勾结).{0,12}经纪人|经纪人.{0,12}(?:联手|联合|合谋|勾结)", candidate, re.S):
                    action = (
                        f"{protagonist_name}核对手机日期与房间环境，确认自己重生回到关键试镜前；"
                        "立即向旧经纪人发出解除代理授权的书面通知，随后绕开旧代理，"
                        f"直接联系{ally_name}预约会面"
                    )
                else:
                    action = (
                        f"{protagonist_name}核对手机日期与房间环境，确认自己重生回到关键试镜前；"
                        f"随后联系{ally_name}预约会面"
                    )
                reaction = f"{opponent_name}尚未介入当前行动"
            if target >= 3:
                gain = str(repair_obj.get("protagonist_gain") or "").strip()
                loss = str(repair_obj.get("opponent_loss") or "").strip()
                gain = re.sub(
                    rf"^(?:{re.escape(protagonist_name)}|主角)\s*(?:获得|拿下|赢得|取得|争取到)?",
                    "",
                    gain,
                ).strip(" ：:，,；;。")
                loss = re.sub(
                    rf"^(?:{re.escape(opponent_name)}|固定对手|对手)\s*(?:失去|错失|丧失|被移出|被剥夺)?",
                    "",
                    loss,
                ).strip(" ：:，,；;。")
                core_chapter = total_chapters - 2 if total_chapters >= 5 else total_chapters
                protagonist_role = next(
                    (member.get("role", "") for member in seed_cast if member.get("alignment") == "protagonist"),
                    "",
                )
                actor_short = bool(re.search(
                    r"演员|艺人|影后|试镜|选角|好莱坞新星",
                    str(protagonist_role) + "\n" + candidate[:6000],
                ))
                project_match = re.search(r"《[^》]{1,30}》", candidate)
                project_name = project_match.group(0) if project_match else "核心项目"
                if actor_short and target == 3 and target < core_chapter:
                    scene = f"{project_name}初试现场，选角导演与{ally_name}在场"
                    action = (
                        f"{protagonist_name}主动要求追加即兴片段，并在镜头前完成台词表演与情绪爆发"
                    )
                    reaction = (
                        f"{opponent_name}试图抢先打断试镜；选角导演当场制止，确认按表演结果推进"
                    )
                    gain = "复试资格"
                    loss = "一次抢先干预试镜流程的机会"
                if target in {3, core_chapter} and not _has_actual_acting_action(action):
                    action = action.rstrip("。；; ") + "；随后在镜头前完成一段高难度台词表演与即兴独白"
                if target == core_chapter:
                    if actor_short:
                        scene = f"{project_name}最终试戏现场，导演、选角负责人和{ally_name}到场"
                        action = (
                            f"{protagonist_name}在最终试戏中完成高难度独白与即兴对戏，"
                            "用当前实力赢得全场确认"
                        )
                        reaction = (
                            f"{opponent_name}当场质疑新人资格；{ally_name}以制片人身份拒绝施压，"
                            f"片方当场确认{protagonist_name}为主演"
                        )
                        gain = f"{project_name}主演合约"
                        loss = f"{project_name}主演角色"
                    if gain in {"角色", "女主", "女主角色", "主演角色"}:
                        gain = f"{project_name}女主角合约"
                    if loss in {"角色", "女主", "女主角色", "主演角色"}:
                        loss = f"{project_name}女主角资格"
                    gain = gain.replace("女主合约", "女主角合约")
                    loss = loss.replace("女主角色", "女主角角色").replace("女主资格", "女主角资格")
                    if re.search(r"(?:宣布|公布).{0,12}(?:最终人选|主演名单|女主角人选)", scene):
                        scene = "核心项目最终试戏现场，导演、选角负责人和制片人到场"
                if actor_short and target == total_chapters - 1:
                    final_section = _seed_plan_chapter_sections(candidate).get(total_chapters, "")
                    gain = "剧本提案权"
                    loss = "当前影片宣传合作席位"
                    action = (
                        f"{protagonist_name}围绕已经拿到的核心角色提出三项可执行的角色弧光与台词修改方案，"
                        "并把有限剧本提案条款写入自己的演员合约"
                    )
                    reaction = (
                        f"{opponent_name}要求片方撤回该条款并继续把宣传资源绑定给自己；"
                        f"片方负责人当场拒绝，并取消{opponent_name}的当前影片宣传合作席位"
                    )
                    scene_parts = [
                        part.strip() for part in re.split(r"[；;]", scene)
                        if part.strip() and not (
                            "会议议程" in part
                            and re.search(r"续作.{0,6}谈判|优先.{0,6}合作|(?:宣传|推广).{0,8}(?:席位|资格|合作)", part)
                        )
                    ]
                    scene = "；".join(scene_parts)
                    scene += f"；会议议程确认{opponent_name}原本持有当前影片宣传合作席位"
                    if re.search(r"续作.{0,6}谈判", final_section):
                        if not re.search(r"续作.{0,6}谈判", scene):
                            scene += f"；会议议程列明{opponent_name}仍持有片方续作优先谈判条款"
                    elif not re.search(r"优先.{0,6}合作", scene):
                        scene += f"；会议议程列明{opponent_name}仍持有片方优先合作条款"
                if actor_short and target == total_chapters:
                    prior_story = candidate[:candidate.find(current_section)] if current_section in candidate else candidate
                    if re.search(r"续作.{0,6}谈判", prior_story):
                        loss = "片方续作优先谈判资格"
                    else:
                        loss = "片方优先合作资格"
                    gain = "三部影片演员合约"
                    scene = "制片公司合同会议室，片方负责人、导演与法务代表到场"
                    action = (
                        f"{protagonist_name}逐条确认三部影片的表演档期、片酬与角色选择条款，"
                        "并当场签署三部影片演员合约"
                    )
                    reaction = (
                        f"{opponent_name}试图把自己的既有优先条款与新系列绑定；"
                        f"片方负责人当场拒绝，并宣布取消{opponent_name}的{loss}"
                    )
                gain_is_concrete = bool(re.search(
                    r"角色|合约|资格|职位|合作|项目|机会|席位|权限|选择权|发言权|创作权|参与权|自主权|提案权|剪辑权|谈判权|优先权",
                    gain,
                ))
                loss_is_concrete = bool(re.search(
                    r"角色|合约|资格|职位|合作|项目|机会|席位|权限|选择权|发言权|创作权|参与权|自主权|提案权|剪辑权|谈判权|优先权|干预权|主导权|控制权",
                    loss,
                ))
                stage_valid = True
                if target < core_chapter:
                    stage_valid = not bool(re.search(r"女主角|主演|正式角色|角色合约", gain))
                elif target == core_chapter:
                    stage_valid = bool(re.search(r"女主角|主演|正式角色|角色合约|该角色|这个角色", gain))
                else:
                    stage_valid = not bool(re.search(r"女主角|主演|角色|复试|终选|试镜", gain))
                    if re.search(r"演员|艺人", str(protagonist_role)) and re.search(r"导演|执导|制片人", gain):
                        stage_valid = False
                    if target == total_chapters and not re.search(
                        r"长期演员合约|长期合作合约|"
                        r"(?:多部|[两三四五六七八九十\d]+部)(?:电影|影片)(?:主演|演员)合约|"
                        r"制片公司长期合作(?:合约)?",
                        gain,
                    ):
                        stage_valid = False
                if target == total_chapters - 1 and not actor_short:
                    final_section = _seed_plan_chapter_sections(candidate).get(total_chapters, "")
                    if any(
                        re.search(pattern, loss) and re.search(pattern, final_section)
                        for pattern in (r"优先.{0,6}合作", r"续作.{0,6}谈判", r"长期.{0,4}片约", r"多片约")
                    ):
                        stage_valid = False
                    if re.search(r"续作.{0,6}谈判", final_section) and not re.search(r"续作.{0,6}谈判", scene):
                        scene += f"；会议议程列明{opponent_name}仍持有片方续作优先谈判条款"
                    if re.search(r"优先.{0,6}合作", final_section) and not re.search(r"优先.{0,6}合作", scene):
                        scene += f"；会议议程列明{opponent_name}仍持有片方优先合作条款"
                if target > core_chapter:
                    for resource_pattern, resource_label in (
                        (r"演员.{0,4}合约", "演员合约"),
                        (r"优先.{0,6}合作", "片方优先合作资格"),
                        (r"续作.{0,6}谈判", "片方续作谈判资格"),
                        (r"项目.{0,6}合作.{0,4}资格", "项目合作资格"),
                        (r"(?:宣传|推广).{0,8}(?:席位|资格|合作)", "当前影片宣传合作席位"),
                    ):
                        if re.search(resource_pattern, loss) and not re.search(resource_pattern, scene):
                            scene += f"；会议议程确认{opponent_name}原本持有{resource_label}"
                if not (gain and loss and gain_is_concrete and loss_is_concrete and stage_valid):
                    print(
                        f"⚠️ 蓝图第{target}章定向修复第 {repair_round}/{max_repair_rounds} 次结构化得失不合格："
                        f"gain={gain[:60]}；loss={loss[:60]}",
                        flush=True,
                    )
                    replacement = ""
                    result = ""
                else:
                    if target > core_chapter and re.search(
                        r"演员合约|合作|签约|续作|谈判|优先|项目资格|项目机会",
                        loss,
                    ):
                        authority_names = [
                            str(member.get("name") or "")
                            for member in seed_cast
                            if re.search(r"制片人|片方负责人|公司高层", str(member.get("role") or ""))
                        ]
                        if not _has_authorized_business_loss(reaction + "\n" + loss, authority_names):
                            reaction = (
                                reaction.rstrip("。；; ")
                                + f"；片方负责人当场宣布取消{opponent_name}的{loss}"
                            )
                    result = f"{protagonist_name}获得{gain}；{opponent_name}失去{loss}"
            else:
                result = str(repair_obj.get("result") or "").strip()
                if target == 1 and not re.search(SPECIFIC_DEATH_METHOD_PATTERN, result):
                    result = result.rstrip("。；; ") + f"；{protagonist_name}回到公寓后服药自杀身亡"
                if target == 2:
                    if re.search(r"(?:联手|联合|合谋|勾结).{0,12}经纪人|经纪人.{0,12}(?:联手|联合|合谋|勾结)", candidate, re.S):
                        result = (
                            f"{protagonist_name}确认重生，解除旧经纪人的代理授权，"
                            f"并完成与{ally_name}的会面预约"
                        )
                    else:
                        result = f"{protagonist_name}确认重生并完成与{ally_name}的会面预约"
            if target < 3 or result:
                replacement = (
                    f"【第{target}章：{title}】\n"
                    f"场景：{scene}\n"
                    f"主角行动：{action}\n"
                    f"对手反应：{reaction}\n"
                    f"本章结果：{result}"
                )
        else:
            replacement = ""
        repaired = _replace_seed_plan_chapter(candidate, target, replacement)
        if not repaired:
            print(f"⚠️ 蓝图第{target}章定向修复第 {repair_round}/{max_repair_rounds} 次无法解析。", flush=True)
            continue
        candidate = repaired
        remaining = _seed_plan_semantic_failures(
            candidate,
            total_chapters=total_chapters,
            extra_constraints=extra_constraints,
        )
        if not remaining:
            return _normalize_short_seed_terminal_summary(candidate)
        print(
            f"⚠️ 蓝图第{target}章定向修复第 {repair_round}/{max_repair_rounds} 次后仍有问题：{remaining[0]}",
            flush=True,
        )
    return ""


def _build_seed_plan_with_user_input(cfg: Dict[str, str]) -> str:
    """基于人工输入先生成全书唯一主线蓝图。"""
    theme = cfg["theme"]
    background = cfg["background"]
    protagonists = _parse_protagonists(cfg.get("protagonists", ""))
    heroine, hero = _pick_legacy_leads(
        protagonists=protagonists,
        fallback_heroine=cfg.get("heroine_name", MAIN_PROTAGONIST),
        fallback_hero=cfg.get("hero_name", ""),
    )
    extra = cfg.get("extra_constraints", "").strip()
    total_chapters = int(cfg.get("total_chapters", "100"))

    protag_hint = f"主角：{ '、'.join(protagonists) }。" if protagonists else ""
    base_query = f"{theme}，背景：{background}。{protag_hint}".strip()
    adapted_samples = search_and_adapt_samples(
        user_input=base_query,
        target_context=f"{theme}，{background}，长篇小说，人物关系，事件因果，跨章节一致性",
        top_k=5,
        min_similarity=0.3,
    )
    sample_texts: List[str] = []
    for i, s in enumerate(adapted_samples or [], 1):
        sample_texts.append(
            f"【样本{i}的情绪技法标签】情绪：{', '.join(s.get('emotion_tags', []))}；"
            f"节奏/结构：{', '.join(s.get('plot_tags', []))}。"
            "只能借鉴压迫、期待、反转和即时回报的技法，不得借用样本人物、职业、证据或具体事件。"
        )
    samples_block = "\n\n".join(sample_texts) if sample_texts else ""

    short_blueprint_contract = ""
    if 3 <= total_chapters <= 12:
        chapter_lines = [
            "【第1章：上一世死亡】只写上一世最后一次事业打击、公开受辱、不可逆损失和明确死亡；禁止重生。",
            "【第2章：重生确认】只写惊醒、身体/房间/手机日期核对、确认回到关键事件前，并实际完成一个小部署；禁止进入试镜。",
        ]
        for chapter in range(3, total_chapters):
            if total_chapters >= 5 and chapter == total_chapters - 2:
                duty = (
                    "完成第一次核心资源反杀：主角拿回上一世被抢的核心机会/角色/职位，"
                    "对手第一次失去该资源；这是全书唯一一次正式授予该核心资源。"
                )
            elif chapter == 3:
                duty = (
                    "只赢得进入终选、复试资格、发言权或同等级入口收益；"
                    "对手失去一次干预机会，但本章不得正式授予最终角色/合约。"
                )
            elif chapter == total_chapters - 1:
                duty = (
                    "守住上一章已经获得的资源，同时新增一项具体的剧本提案权、合同选择权或演员项目席位，"
                    "并拆掉对手尚未结算的演员合约、项目合作资格、片方优先合作或续作谈判机会；"
                    "不得再次换角或重新授予同一合约；本章场景同时提前建立对手现有的片方优先合作或续作谈判资源，供终章清算，但本章不得提前剥夺该终章资源。"
                )
            else:
                duty = (
                    "设计不同于前章的连续职业冲突：主角主动出招、对手当场失算，"
                    "阶段收益升级但不重复已获得资源。"
                )
            chapter_lines.append(f"【第{chapter}章：由你按本题材命名】{duty}")
        chapter_lines.append(
            f"【第{total_chapters}章：终局清算】在比前章更高且不同的利益层级清算："
            "固定对手失去尚未结算的演员合约、行业资格、片方优先合作或续作谈判机会，主角实际签下不同于前章核心资源的长期演员合约、多部影片演员合约或制片公司长期合作合约；签约权、签约机会不算；"
            "禁止再次宣布同一角色归属。"
        )
        short_blueprint_contract = (
            "\n【短篇蓝图输出骨架：标题逐字保留，内容由你填写】\n"
            "先输出【固定角色表】，随后严格按以下标题顺序逐章输出；不得合并、跳过或改成阶段编号：\n"
            + "\n".join(chapter_lines)
            + "\n最后输出【终局回收】。每章只写场景、主角行动、对手反应和本章结果，不写正文。\n"
        )

    theme_contract = constraints_text()
    system_prompt = (
        "你是长篇小说的大纲总策划，需要先设计唯一的最大主线蓝图。"
        "本题材的背叛经纪人与关键盟友是两个不同角色：经纪人不命名，关键盟友必须是从未背叛主角的选角导演或独立制片人。"
    )
    user_prompt = (
        f"请围绕本次题材设计一条贯穿全书{total_chapters}章的唯一主线蓝图。\n\n"
        f"{theme_contract}\n\n"
        f"本次人工指定题材：{theme}\n"
        f"本次人工指定背景：{background}\n"
        + (f"主角名字约束（不要求区分男女主，允许多个主角）：{'、'.join(protagonists)}\n" if protagonists else "")
        + f"（兼容占位名）主角占位：{heroine}\n"
        + (f"（兼容占位名）辅助角色占位：{hero}\n" if hero else "")
        + (
            f"本轮辅助姓名硬锁定：{hero}只能是从未担任{heroine}旧经纪人、从未参与前世合谋或背叛的盟友/支持者；"
            "背叛经纪人只能写成不命名的职位角色。\n"
            if hero else ""
        )
        + (f"额外限制：{extra}\n" if extra else "")
        + "\n要求：\n"
        "- 第一段必须给出【固定角色表】：主角、核心对手、关键盟友各自使用唯一姓名，并写明身份、欲望、与主角关系；正式姓名后续不得变体或更换；\n"
        "- 固定角色表还必须单列“职位角色：背叛经纪人（不命名）”，身份只写主角的旧经纪人；这个职位角色负责前世撤回代理、今生被主角解除授权，绝不能兼任关键盟友；\n"
        "- 关键盟友绝不能同时是前世背叛主角的经纪人、核心对手的合谋者或主角要击败的复仇目标；人工给定的辅助姓名必须保持盟友阵营，前世背叛经纪人使用不命名职位称呼；\n"
        "- 关键盟友的身份只能选择‘选角导演’或‘独立制片人’，并明确写‘从未担任主角经纪人、从未参与前世合谋’；不要写前经纪人、现经纪人、代理人或曾经背叛；\n"
        "- 固定角色每人只写一个权限清晰的主要身份；演员/影后不得同时写成助理、经纪人或选角导演，题材需要的第二种对手职能可由不命名的‘经纪人’等职位角色承担；\n"
        "- 固定演员不得更换编剧/导演/制作团队、调动人员或决定公司人事；演员对手不能被调往部门、剥夺公司职位、参加项目竞标，也不能凭空拥有剧本参与权、剪辑权或幕后/项目顾问职位，只能失去角色、演员合约、项目合作资格或片方优先合作机会；\n"
        "- 演员可以在自己的合约中争取剧本提案条款，但不得申请加入编剧组、剧本创作小组或制作团队；提建议也不能代替核心角色章的真实表演；\n"
        "- 演员/影后对手只能施压、争抢或嘲讽，不能宣布取消试镜资格、淘汰、换角或把角色交给别人；所有角色决定必须由选角导演、导演、制片人或片方作出；\n"
        f"- {heroine}是全书唯一主要行动者；其他人工给定姓名只能按角色表设为盟友或辅助人物，除非题材明确要求双主角；不得把女演员写成男演员、男主角等错误身份；\n"
        + (
            f"- 本轮特别禁止把{hero}写成{heroine}的前经纪人、背叛者、合谋者、反派或复仇目标；"
            f"{hero}只能保持关键盟友阵营，旧经纪人不得拥有{hero}这个姓名；\n"
            if hero else ""
        )
        + "- 明确主角的核心失败或创伤、当前最大目标和分阶段推进方式；\n"
        "- 开篇结构固定：第1章只写上一世最后一次事业打击及具体死亡方式，‘上一世死亡’标题不算剧情发生，本章结果必须明确生命结束；第2章只写惊醒、核对日期、确认重生和完成第一次小部署，不进入试镜或正式反杀；第3章起才进入今生职业反击；\n"
        "- 每一阶段都必须符合本次背景的现实规则、人物动机和事件因果；\n"
        "- 每一阶段至少设计一个章内可兑现的小胜利或小反杀，以及对手当场可见的情绪反应和实际损失；\n"
        "- 第3章起每章的‘本章结果’都要明确形成双向职业落锤：主角新增资格、合约、权限或合作，对手同章失去角色、资格、项目权限或合作机会；只写巩固地位、失去影响、脸色难看不算；\n"
        "- 第3章首次反击也必须写主角在镜头前真实表演、试戏、台词演绎或独白，不能只写情绪控制力、台词理解、剧本建议或专业判断；\n"
        "- 各章收益必须逐级升级且不能重复结算同一资源：可按复试资格→优先选择权/条件优势→正式角色合约→更高层清算推进；同一角色或合约只能正式授予一次，对手一旦退出项目，后章不得无解释继续干预该项目；\n"
        "- 核心角色被主角夺回后，不得立刻给对手配角作为安慰性补偿；第5-6章若对手失去演员合约、优先合作或续作谈判，必须由片方/制片公司/制片人当场宣布取消、终止或不再续约，不能只在结果栏凭空宣称；\n"
        "- 主角演员只能谈判和签署自己的合约，不能要求重审、取消对手旧合同或把对手剔出系列片/项目；对手失去核心角色后不得无解释继续留在同一剧组拍摄/排练，也不要让主角调整日程去避开她；\n"
        "- 第5章必须提前建立对手原本持有的片方优先合作或续作谈判资源，终章才可清算；第5章自己的对手损失必须是另一项当前项目利益，不得提前失去终章资源；终章只能在制片公司签约会议或片方合同会议，不得使用颁奖晚宴、庆功宴、红毯或酒会；\n"
        "- 第5-6章取消对手的任何演员合约、优先合作、续作谈判、项目合作或宣传席位前，都必须在固定角色表、前文或本章场景议程中明确该资源原本存在；不得在结果栏凭空创造后再剥夺；\n"
        "- 不得先写主角已经完成复试/终选，再在本章结果中获得复试/终选资格；入口行动与阶段结果必须严格按初试→复试资格→复试→正式角色推进；\n"
        "- 前世信息差只能是记忆中的日期、规则、话术和人物选择；不能把前世录音、文件、截图或邮件带回今生，也不能凭记忆恢复为物证；\n"
        "- 主角不得向盟友、对手或公众直接说自己重生；盟友只能从主角当前专业判断与行动中决定是否协助；\n"
        "- 除重生主角外，任何今生人物都不知道上一世发生过什么；对手不得说‘你怎么还没死’‘你本该死了’等泄露前世认知的话；\n"
        "- 第2章结果只能是确认重生并完成一次联系、预约、改约或准备动作，绝不能提前获得复试、终选、角色、资格或合约；\n"
        "- 若前世由经纪人与核心对手合谋，第2章首次部署必须先解除旧经纪人的代理合同/授权，再绕开旧代理直接联系盟友，确保两名合谋者都付出代价；\n"
        "- 推进重点是主角在当前场景主动抢角色、改条件、拒陷阱和迫使对手失算，不得把主线写成调查、搜证、匿名爆料、媒体舆论或投资谈判；\n"
        "- 禁止用揭露贿赂、公开过往操纵记录、托人脉寻找间接证据来完成反杀；也禁止暗示对手曾私下接触其他剧组/电影，或用‘过去拒绝合作的旧事’‘过去一年阻碍新人’‘质疑过往不当操作’‘影响公司口碑’等概括性指控清算；冲突必须由当前场景可见的表演、合同条款、公开规则或对手亲自做出的动作解决；\n"
        "- 不要在前世创伤里增加伪造退赛声明、虚假证据或神秘文件；经纪人的背叛用解除代理、撤回支持或转向对手直接呈现，主角目标也不得写成摧毁声誉/名誉；\n"
        "- 禁止利用另一部电影的违约传闻、负面传言、丑闻风声或任何未经当场证实的旧闻迫使片方翻脸；\n"
        "- 本次若人工限制写了不要投资，则投资人、投资方、资本施压、撤资或加码均不得参与冲突；终章必须实际签下长期演员合约或制片公司长期合作合约，不能只获得签约权、机会或候选资格；\n"
        "- 禁止盟友或他人临时提供来源模糊的资料、材料、文件、记录或证据替主角解决冲突；主角也不得出示对手私下接触其他剧组、违规或操控的证据；\n"
        "- 禁止通过盟友帮助把旧记录、内部资料或证据提交公司审查；第2章以后不得再写‘本簇不进入今生’；\n"
        "- 禁止让经纪人宣布淘汰、换角、角色归属或演员退出片方项目；经纪人只能解除自己的代理关系，片方职业决定必须由选角导演、导演、制片人或片方负责人落锤；禁止用‘过往争议/曾经违规/行为模式’等无来源旧账或发布会媒体追问清算；\n"
        "- 核心角色正式授予章必须由主角完成真实试戏、表演、台词演绎或即兴发挥后赢得，不能只靠剧本建议或口头主张；首映礼、媒体采访和记者追问不得承担终局清算；\n"
        "- 若题材明确经纪人与核心对手联手毁掉主角，第1章必须让经纪人实施解除代理、撤回支持、转签角色或切断资源等具体背叛动作，不能只在人物关系说明里提一句；\n"
        "- 终局必须明确写出核心对手失去的角色、合约、职位或资格，以及主角当场拿到的角色、合约、资格或资源，不能只写丑闻曝光、道歉、声望提升或公众支持；\n"
        "- 后续事件簇只能沿这条主线补细节，不得无解释地换世界观、主角身份或终极主线。\n\n"
        f"{short_blueprint_contract}\n"
        "如有样本可参考风格，不要抄袭剧情：\n"
        f"{samples_block}\n\n"
        "只输出蓝图本身。"
    )
    if total_chapters > 12:
        # The original prompt below this branch was tuned for a six-chapter
        # actress/audition smoke test.  A runtime long-form theme needs a clean
        # contract or those fixed roles and payoffs leak into unrelated books.
        user_prompt = f"""请围绕本次题材设计一条贯穿全书{total_chapters}章的唯一重生复仇主线蓝图。

{theme_contract}

【人工主题】{theme}
【背景】{background}
【固定主角】{'、'.join(protagonists) if protagonists else heroine}
【额外限制】{extra or '无'}

这是高情绪、快节奏的短剧式爽文。请只输出规划，不写小说正文，并严格满足：
1. 开头必须给出可解析的【固定角色表】。至少包含主角、核心对手、关键盟友与两名分层反派；可按人工主题增加必要角色。每个人只能有一个固定姓名、单一身份、明确权限、欲望、与主角关系和阵营，不得套用其他题材的职业。
2. 对手层级、组织关系和资源类型全部从【人工主题】【背景】【额外限制】推导。反派必须组成可理解的利益链或冲突链，但不能全员同一种脸谱；至少一名善于用合理外衣掩盖恶意，至少一名自作聪明并会因具体行动留下把柄。
3. 第1章只写上一世或旧阶段的核心失败、不可逆代价与明确死亡/终止，不进入重生后行动；第2章只写醒来、核对时间地点身份、确认重生并完成一个可见的首次部署，不提前完成正式反杀。具体死法、地点、职业和首次部署必须来自本次主题。
4. 第3章起采用1-2章一个闭环的小故事。每个故事都要完成“认出旧局或风险→主角主动改变现场条件→既定对手照旧出招并暴露→当场现实损失+主角现实收益”，不得连续压抑三章才回报。
5. 每个小故事的争夺对象、证据载体、规则和有权者必须来自本次题材的职业逻辑；场景和反杀手段需要轮换，不能连续依赖调查、录音、直播、热搜、匿名材料或万能技术。
6. 调查只能附着在主动冲突中，并在当前1-2章闭环内转化为具体得失；不得写成长期查账、匿名线索、神秘人递证据或警方突然收网。
7. 每约10章完成一次阶段升级，并回收一项蓝图终局真正需要的关系、权限、资源、公开规则或合法证据；阶段回收不能替代当章小复仇。反派一旦被永久清退，不能无解释复职。
8. 终局机制、最终对手损失和主角最终收益必须从人工主题推导，并在最后一段前逐步取得必要条件；不得套用假死、葬礼、保险、遗产、版权、直播审判等其他题材终局。
9. 全书情绪曲线以愤怒、紧张、解气为主，幽默和温暖只能来自本题材已经建立的人物关系；主角始终聪明、主动、有边界，不靠全知外挂。
10. 最后给出【八段主线推进】和【终局回收清单】，说明各阶段新增筹码、阶段对手、即时复仇类型及终局用途。不要逐章写全部梗概，章节级拆分由下一步事件簇完成。
11. 所有现实决定必须由当前题材中确有权限的人物或机构作出；职业操作符合基本逻辑。所有人物、地点、机构、作品与产品使用虚构称呼，可形成文化指代，但不得出现现实原名。

只输出蓝图本身。"""
        system_prompt = (
            "你是擅长百章短剧爽文的总策划。你要建立稳定人物、分层反派、"
            "高密度即时复仇与可回收终局伏笔，不得套用其他题材模板。"
        )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    plan = ""
    last_failures: List[str] = []
    max_seed_attempts = max(1, int(os.getenv("V2_SEED_MAX_ATTEMPTS", "7")))
    for attempt in range(1, max_seed_attempts + 1):
        candidate = legacy_v2.call_qianwen_api(
            messages,
            temperature=0.72 if attempt == 1 else 0.45,
            top_p=0.82 if attempt == 1 else 0.72,
        )
        if candidate and not str(candidate).startswith("通义千问"):
            if total_chapters > 12:
                diagnostics_dir = os.path.join(OUTPUT_DIR, "planning_diagnostics")
                os.makedirs(diagnostics_dir, exist_ok=True)
                with open(
                    os.path.join(diagnostics_dir, f"seed_candidate_attempt_{attempt:02d}.txt"),
                    "w",
                    encoding="utf-8",
                ) as diagnostics_file:
                    diagnostics_file.write(str(candidate))
            if total_chapters > 12:
                failures = _long_seed_plan_semantic_failures(
                    str(candidate), protagonists=protagonists
                )
            else:
                failures = _seed_plan_semantic_failures(
                    str(candidate),
                    total_chapters=total_chapters,
                    extra_constraints=extra,
                )
            if not failures:
                plan = str(candidate)
                if attempt > 1:
                    print(f"✅ 主线蓝图在第 {attempt} 次 Qwen 调用通过结构与题材审稿。", flush=True)
                break
            if 3 <= total_chapters <= 12:
                repaired_plan = _repair_short_seed_plan_chapters(
                    str(candidate),
                    total_chapters=total_chapters,
                    extra_constraints=extra,
                )
                if repaired_plan:
                    plan = repaired_plan
                    print(
                        f"✅ 主线蓝图第 {attempt} 次整稿已通过逐章定向修复完成审稿。",
                        flush=True,
                    )
                    break
            last_failures = failures
            print(
                f"⚠️ Qwen 主线蓝图第 {attempt}/{max_seed_attempts} 次未通过结构与题材审稿：{failures[0]}",
                flush=True,
            )
            messages[-1]["content"] = (
                user_prompt
                + "\n\n上一次蓝图存在以下硬问题，必须全部修正后重新输出完整蓝图：\n- "
                + "\n- ".join(failures)
                + "\n不要解释修改过程。"
            )
    if not plan:
        detail = "；".join(last_failures[:3]) if last_failures else "Qwen API 未返回有效蓝图"
        raise RuntimeError(f"连续 {max_seed_attempts} 次未生成通过审稿的主线蓝图：{detail}")
    return str(plan).strip()


def _extract_json_array_maybe(text: str) -> List[Dict[str, Any]]:
    """尽量从模型输出中抽取 JSON 数组。"""
    if not text:
        return []
    raw = str(text).strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        return []
    return []


def _canonical_cast_from_seed_plan(plan: str) -> List[Dict[str, str]]:
    """Parse the Qwen-authored fixed cast table so later stages cannot mutate it."""
    text = str(plan or "")
    cast: List[Dict[str, str]] = []
    def alignment_for_label(label: str) -> str:
        if label == "主角":
            return "protagonist"
        if label == "核心对手" or label.startswith("分层反派"):
            return "opponent"
        return "ally"

    cast_label = r"主角|核心对手|关键盟友|分层反派\s*\d*|辅助盟友\s*\d*|粉丝骨干\s*\d*"
    pattern = re.compile(
        rf"(?:\*\*)?({cast_label})(?:\*\*)?[：:]\s*(?:\*\*)?([^*\r\n]+?)(?:\*\*)?\s*\r?\n"
        r"\s*身份[：:]\s*([^\r\n]+)",
        re.M,
    )
    for match in pattern.finditer(text):
        label, name, role = match.groups()
        clean_name = re.sub(r"[\s　]+$", "", name).strip(" -*")
        clean_name = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", clean_name).strip()
        clean_role = role.strip().rstrip("  ").strip(" -*")
        if clean_name and clean_role and clean_name not in {item["name"] for item in cast}:
            cast.append({
                "name": clean_name,
                "role": clean_role,
                "alignment": alignment_for_label(label),
            })
    multiline_pattern = re.compile(
        rf"\*\*({cast_label})[：:]\*\*\s*\r?\n"
        r"\s*\*\*([^*\r\n]+)\*\*\s*(?:[（(]([^）)\r\n]+)[）)])?",
        re.M,
    )
    for match in multiline_pattern.finditer(text):
        label, name, parenthetical_role = match.groups()
        clean_name = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", name).strip(" -*")
        if not clean_name or clean_name in {item["name"] for item in cast}:
            continue
        tail = text[match.end():]
        boundary = re.search(
            rf"\*\*(?:{cast_label})[：:]|\r?\n---|【第\s*\d+\s*章|【第一章",
            tail,
        )
        block = tail[:boundary.start()] if boundary else tail[:600]
        identity_match = re.search(
            r"(?:\*\*)?身份[：:](?:\*\*)?\s*([^\r\n]+)",
            block,
        )
        clean_role = (
            identity_match.group(1).strip(" -*")
            if identity_match
            else str(parenthetical_role or "").strip(" -*")
        )
        if clean_role:
            cast.append({
                "name": clean_name,
                "role": clean_role,
                "alignment": alignment_for_label(label),
            })
    return cast


def _apply_seed_cast_to_clusters(
    clusters: List[Dict[str, Any]], global_seed_plan: str
) -> List[Dict[str, Any]]:
    seed_cast = _canonical_cast_from_seed_plan(global_seed_plan)
    if not seed_cast:
        return clusters
    normalized: List[Dict[str, Any]] = []
    for original in clusters:
        cluster = dict(original)
        cluster["canonical_cast"] = json.loads(json.dumps(seed_cast, ensure_ascii=False))
        normalized.append(cluster)
    return normalized


def _event_cluster_semantic_failures(
    clusters: List[Dict[str, Any]], *, total_chapters: int
) -> List[str]:
    """Reject planning shortcuts that later force the prose into mystery/investigation logic."""
    failures: List[str] = []
    if not clusters:
        return ["事件簇数组为空"]

    milestone_text_by_chapter: Dict[int, str] = {}
    for source_cluster in clusters:
        for source_milestone in source_cluster.get("chapter_milestones") or []:
            if not isinstance(source_milestone, dict):
                continue
            try:
                source_chapter = int(source_milestone.get("chapter"))
            except (TypeError, ValueError):
                continue
            milestone_text_by_chapter[source_chapter] = json.dumps(source_milestone, ensure_ascii=False)

    canonical_opponents: set[str] = set()
    for cluster in clusters:
        cast = cluster.get("canonical_cast") or []
        for member in cast if isinstance(cast, list) else []:
            if not isinstance(member, dict):
                continue
            if str(member.get("alignment") or "").casefold() == "opponent":
                name = str(member.get("name") or "").strip()
                if name:
                    canonical_opponents.add(name)

    expected_cast_names: Optional[set[str]] = None
    for idx, cluster in enumerate(clusters, 1):
        cid = str(cluster.get("cluster_id") or f"第{idx}簇")
        cast = cluster.get("canonical_cast") or []
        cast = cast if isinstance(cast, list) else []
        cast_names = {
            str(member.get("name") or "").strip()
            for member in cast
            if isinstance(member, dict) and str(member.get("name") or "").strip()
        }
        cast_alignments = {
            str(member.get("alignment") or "").casefold()
            for member in cast if isinstance(member, dict)
        }
        if not cast_names or "protagonist" not in cast_alignments or "opponent" not in cast_alignments:
            failures.append(
                f"{cid}缺少完整 canonical_cast；每个簇都必须重复固定角色表，至少包含 protagonist 与 opponent"
            )
        elif expected_cast_names is None:
            expected_cast_names = cast_names
        elif cast_names != expected_cast_names:
            failures.append(
                f"{cid}的 canonical_cast 与前簇不一致：{sorted(cast_names)}；固定姓名不得跨簇增删或更换"
            )
        failures.extend(_actor_authority_failures(
            json.dumps(cluster, ensure_ascii=False),
            cast,
            scope=cid,
        ))
        for member in cast:
            if not isinstance(member, dict):
                continue
            member_role = str(member.get("role") or "")
            alignment = str(member.get("alignment") or "").casefold()
            if alignment == "opponent" and re.search(r"影后|演员", member_role) and "助理" in member_role:
                failures.append(
                    f"{cid}固定对手身份自相矛盾：{member.get('name')} 被同时写成演员/影后与助理；"
                    "应保留一个符合娱乐产业权限的主要身份"
                )
        info_gap = str(cluster.get("info_gap_from_prev_life") or "")
        revenge = str(cluster.get("this_life_revenge") or "")
        core = str(cluster.get("core_payoff") or "")
        outcome = str(cluster.get("cluster_outcome") or "")
        final_payoff = str(cluster.get("final_payoff") or "")
        combined = "\n".join((info_gap, revenge, core, outcome, final_payoff))
        full_cluster_text = json.dumps(cluster, ensure_ascii=False)
        cluster_constraints = str(cluster.get("user_extra_constraints") or "")
        if not cluster_constraints and isinstance(cluster.get("theme_contract"), dict):
            cluster_constraints = str(cluster["theme_contract"].get("extra_constraints") or "")
        story_only_text = json.dumps(
            {
                key: value for key, value in cluster.items()
                if key not in {
                    "theme_contract", "user_extra_constraints", "user_theme",
                    "user_background", "user_protagonists", "user_heroine_name", "user_hero_name",
                }
            },
            ensure_ascii=False,
        )
        if "投资" in cluster_constraints and re.search(
            r"投资人|投资方|拉拢.{0,12}投资|投资.{0,12}(?:施压|介入|撤资|加码)|"
            r"资本.{0,10}(?:施压|介入|撤资|加码)",
            story_only_text,
            re.S,
        ):
            failures.append(f"{cid}违反人工限制，仍让投资人、投资方或资本施压参与核心推进")
        if any(token in cluster_constraints for token in ("调查", "搜证", "匿名爆料", "媒体搜证链")) and re.search(
            r"(?:出示|提交|拿出|展示|提供).{0,24}(?:证据|记录|材料)|"
            r"(?:证据|记录|材料).{0,24}(?:证明|揭露|显示).{0,24}(?:私下接触|暗中接触|违规|操控)",
            story_only_text,
            re.S,
        ):
            failures.append(
                f"{cid}违反人工限制，仍让主角出示或提交对手私下接触、违规操作的证据"
            )
        for member in cast:
            if not isinstance(member, dict):
                continue
            member_name = str(member.get("name") or "")
            member_role = str(member.get("role") or "")
            if (
                member_name
                and str(member.get("alignment") or "").casefold() == "opponent"
                and re.search(r"影后|演员", member_role)
                and not re.search(r"制片人|片方负责人", member_role)
                and re.search(
                    rf"{re.escape(member_name)}.{{0,35}}(?:签署.{{0,12}}(?:协议|合同|合约)|决定合同条款|批准合约)",
                    full_cluster_text,
                    re.S,
                )
            ):
                failures.append(
                    f"{cid}让演员/影后对手签署或批准主角合约；合同必须由片方或制片方决定"
                )
            if (
                member_name
                and str(member.get("alignment") or "").casefold() == "protagonist"
                and re.search(r"演员|艺人", member_role)
                and re.search(
                    rf"{re.escape(member_name)}.{{0,35}}(?:独立执导|执导邀约|成为导演|导演职位|制片人职位)",
                    full_cluster_text,
                    re.S,
                )
            ):
                failures.append(
                    f"{cid}让固定演员主角突然转任导演/制片人；收益必须仍是演员合约、项目选择权或创作参与权"
                )

        impossible_carried_evidence = bool(
            re.search(
                r"(?:上一世|前世|临死前|曾经).{0,30}(?:录下|保存|拿到|藏好|留下|持有)"
                r".{0,30}(?:录音|音频|视频|文件|邮件|截图|U盘|证据)",
                info_gap,
            )
        ) and not bool(
            re.search(
                r"(?:今生|这一世|本世|重生后).{0,45}(?:重新|再次|当场|提前).{0,20}"
                r"(?:录下|取得|生成|制作|保存|备份)",
                revenge,
            )
        )
        if impossible_carried_evidence or re.search(
            r"(?:从脑海|凭记忆|根据记忆).{0,24}(?:还原|恢复|生成|制作).{0,16}"
            r"(?:录音|音频|视频|文件|截图|证据)",
            combined,
        ):
            failures.append(
                f"{cid}把前世记忆当成可携带或可凭空还原的现实物证；信息差只能是记忆，"
                "如需材料必须在今生由主角主动布置并现场产生。"
            )
        if re.search(r"私人邮件|私密邮件|私密录音|秘密录音|偷拍视频|隐藏文件|内部文件", combined):
            failures.append(
                f"{cid}依赖来源不透明的私密材料推进；改成当前场景中的表演、合同条款、公开规则或对手当场动作"
            )
        if _contains_unnegated_rebirth_disclosure(full_cluster_text):
            failures.append(
                f"{cid}让主角向盟友或他人直接自曝重生；重生只能作为主角内心信息差，"
                "盟友应因当前可见的专业判断和行动提供帮助"
            )
        if re.search(
            r"(?:揭露|公开|曝光|提交).{0,55}(?:贿赂|黑幕|操纵选角|过往记录|过去.{0,12}记录)|"
            r"(?:通过|利用).{0,18}人脉.{0,24}(?:间接证据|记录|揭示真相)|"
            r"虽未带回.{0,20}物证.{0,45}(?:证据|记录|揭示真相)",
            full_cluster_text,
            re.S,
        ):
            failures.append(
                f"{cid}仍靠无当前来源的贿赂指控、过往记录或人脉间接证据翻盘；"
                "改成当前场景可见的表演、合同条款、公开规则或对手亲自做出的动作"
            )
        if re.search(
            r"(?:指出|质疑|暗示|直指|隐喻).{0,45}(?:过往争议|过去.{0,12}行为|曾经.{0,12}违规|曾违规|行为模式|违规操作)",
            full_cluster_text,
            re.S,
        ):
            failures.append(
                f"{cid}靠泛指对手过往争议或违规行为翻盘；必须改用当前合同条款、公开试镜规则或当场动作"
            )
        if _contains_vague_past_accusation(full_cluster_text):
            failures.append(
                f"{cid}靠概括对手过去拒绝合作、打压新人或影响口碑来清算；"
                "必须改用当前现场表演、合同条款、公开规则或对手当场动作"
            )
        if re.search(
            r"(?:利用|借助).{0,24}(?:提供|交给|递交|给出).{0,12}(?:资料|材料|文件|记录|证据)",
            full_cluster_text,
            re.S,
        ):
            failures.append(
                f"{cid}依赖盟友或他人临时提供的模糊资料；改成主角依据当前公开规则、现场表演或当场可见条款行动"
            )
        if re.search(
            r"(?:通过|借助|利用).{0,40}(?:帮助|资料|材料|文件|内部记录|证据).{0,45}(?:提交|审查|指控|揭露|证明)",
            full_cluster_text,
            re.S,
        ):
            failures.append(
                f"{cid}依赖盟友帮助或旧记录提交审查的证据链；改成当前合同、现场规则或对手当场动作"
            )
        if re.search(r"发布会|首映礼|媒体采访|媒体关注|媒体追问|记者追问|舆论施压|公众信任|行业信誉", full_cluster_text):
            failures.append(
                f"{cid}把发布会、媒体或舆论变化当作核心清算；改成选角、合同或片方会议中的职业得失"
            )
        if re.search(
            r"(?:揭露|指出|暗示).{0,30}(?:当年|过去|过往).{0,24}(?:操作|行为|操控|黑幕)",
            full_cluster_text,
            re.S,
        ):
            failures.append(
                f"{cid}靠泛指对手当年操作或过往行为清算；改成当前合同条款、公开规则或当场动作"
            )
        if re.search(
            r"经纪人.{0,24}(?:宣布|决定|指定).{0,24}(?:淘汰|替换|换角|角色归属|由.{0,8}出演|退出(?:片方)?项目)",
            full_cluster_text,
            re.S,
        ):
            failures.append(
                f"{cid}让经纪人越权宣布淘汰或角色归属；必须由选角导演、导演、制片人或片方负责人决定"
            )

        span = cluster.get("chapter_span") or []
        is_awakening_only = span == [2, 2]
        opponent = str(cluster.get("main_opponent") or "").strip()
        if not is_awakening_only:
            if canonical_opponents and not any(name in opponent for name in canonical_opponents):
                failures.append(f"{cid}的 main_opponent 未使用 canonical_cast 中的固定对手姓名：{opponent}")
            if re.search(r"[&＆]|(?:以及|和|与).{0,8}(?:公司|集团|平台)$", opponent):
                failures.append(f"{cid}的 main_opponent 混入泛称机构；应填写一个固定姓名并在正文中由其代表机构行动。")

        try:
            start, end = int(span[0]), int(span[1])
        except (TypeError, ValueError, IndexError):
            failures.append(f"{cid}缺少有效 chapter_span")
            continue
        if start < 1 or end < start or end > total_chapters:
            failures.append(f"{cid}的 chapter_span 越界或倒置：{span}")
        if [start, end] != [1, 1] and re.search(r"(?:本事件簇|本簇)?不进入今生", full_cluster_text):
            failures.append(
                f"{cid}位于今生时间线却写‘不进入今生’；该句只允许第1章旧阶段失败簇使用"
            )

        if 5 <= total_chapters <= 12 and len(clusters) >= 4:
            milestones = cluster.get("chapter_milestones") or []
            milestone_chapters: List[int] = []
            milestone_complete = isinstance(milestones, list) and bool(milestones)
            for milestone in milestones if isinstance(milestones, list) else []:
                if not isinstance(milestone, dict):
                    milestone_complete = False
                    continue
                try:
                    milestone_chapters.append(int(milestone.get("chapter")))
                except (TypeError, ValueError):
                    milestone_complete = False
                if not str(milestone.get("action") or "").strip() or not str(milestone.get("result") or "").strip():
                    milestone_complete = False
            expected_milestone_chapters = list(range(start, end + 1))
            if not milestone_complete or milestone_chapters != expected_milestone_chapters:
                failures.append(
                    f"{cid}的 chapter_milestones 未逐章覆盖 {expected_milestone_chapters}；"
                    "每章必须有 action、opponent_reaction、result，不能压缩丢章"
                )
            for milestone in milestones if isinstance(milestones, list) else []:
                if not isinstance(milestone, dict):
                    continue
                try:
                    milestone_chapter = int(milestone.get("chapter"))
                except (TypeError, ValueError):
                    continue
                action_text = str(milestone.get("action") or "")
                reaction_text = str(milestone.get("opponent_reaction") or "")
                result_text = str(milestone.get("result") or "")
                milestone_text = "\n".join((action_text, reaction_text, result_text))
                protagonist_role = next(
                    (
                        str(member.get("role") or "")
                        for member in cast
                        if isinstance(member, dict)
                        and str(member.get("alignment") or "").casefold() == "protagonist"
                    ),
                    "",
                )
                milestone_opponent_names = [
                    str(member.get("name") or "").strip()
                    for member in cast
                    if isinstance(member, dict)
                    and str(member.get("alignment") or "").casefold() == "opponent"
                    and str(member.get("name") or "").strip()
                ]
                milestone_opponent_pattern = "|".join(
                    re.escape(name) + "|" + re.escape(name.split()[0])
                    for name in milestone_opponent_names
                )
                if re.search(r"演员|艺人", protagonist_role) and re.search(
                    r"(?:提议|要求|决定|宣布|推动|下令|安排).{0,18}"
                    r"(?:更换|撤换|替换|解雇|开除|任免|调动|调任).{0,20}"
                    r"(?:编剧|导演|制片|制作团队|工作人员|部门|人员)",
                    action_text,
                ):
                    failures.append(
                        f"{cid}第{milestone_chapter}章让固定演员主角行使团队或公司人事权；"
                        "演员只能提出剧本内容建议，不能更换团队或调动人员"
                    )
                if (
                    milestone_opponent_pattern
                    and re.search(r"演员|艺人", protagonist_role)
                    and re.search(
                        rf"(?:要求|提议|推动).{{0,24}}(?:{milestone_opponent_pattern})"
                        r".{0,18}(?:旧合同|合同|合约).{0,14}(?:重新评估|重审|审查|取消|终止)",
                        action_text,
                        re.I | re.S,
                    )
                ):
                    failures.append(
                        f"{cid}第{milestone_chapter}章让固定演员主角要求重审或取消对手合同；"
                        "主角只能谈判自己的演员合约"
                    )
                if (
                    milestone_opponent_pattern
                    and re.search(r"演员|艺人", protagonist_role)
                    and re.search(
                        rf"(?:要求|提议|推动).{{0,22}}(?:将|把)?(?:{milestone_opponent_pattern})"
                        r".{0,16}(?:剔除|移出|排除|踢出).{0,18}(?:系列片|后续项目|项目|剧组)",
                        action_text,
                        re.I | re.S,
                    )
                ):
                    failures.append(
                        f"{cid}第{milestone_chapter}章让固定演员主角要求把对手剔出系列片/项目；"
                        "片方必须自行作出不合作决定"
                    )
                if milestone_chapter == 1 and not re.search(
                    r"死亡|身亡|死去|生命结束|心跳停止|咽气|自杀",
                    milestone_text,
                ):
                    failures.append(
                        f"{cid}第1章里程碑没有明确写到上一世死亡；不能只停在事业崩塌"
                    )
                if milestone_chapter == 1 and not re.search(
                    SPECIFIC_DEATH_METHOD_PATTERN,
                    full_cluster_text,
                ):
                    failures.append(
                        f"{cid}第1章没有写明上一世死亡方式；必须从职业打击自然延伸到一个具体死因并保持全书一致"
                    )
                if milestone_chapter == 2:
                    if not re.search(r"重生|确认.{0,10}(?:日期|时间)|回到.{0,12}(?:前|那天)", milestone_text):
                        failures.append(
                            f"{cid}第2章里程碑没有明确完成重生确认；必须核对日期/环境后确认回到关键事件前"
                        )
                    if re.search(r"终选|复试|晋级|获得.{0,12}(?:角色|资格|合约)|签约", milestone_text):
                        failures.append(
                            f"{cid}第2章提前获得终选、复试、角色或合约；本章只能确认重生并完成一次首次部署"
                        )
                if milestone_chapter >= 3:
                    milestone_gain = bool(re.search(
                        r"拿下|获得|签约|赢得|进入终选|晋级|正式出演|取得.{0,10}(?:资格|权|机会)|"
                        r"争取到|获邀|恢复",
                        result_text,
                    ))
                    milestone_loss = bool(re.search(
                        r"取消|撤下|换角|终止|退出|被拒|被制止|无法干预|被移出|被剥夺|"
                        r"(?:失去|错失|丧失)[^，。；,\n]{0,14}(?:权|权限|机会|角色|合约|资格|职位|合作|项目|资源|席位)|"
                        r"提议被拒|被迫离场|调离|开除|解约",
                        "\n".join((reaction_text, result_text)),
                    ))
                    if not (milestone_gain and milestone_loss):
                        failures.append(
                            f"{cid}第{milestone_chapter}章里程碑未形成双向阶段结果；"
                            "result/opponent_reaction 必须明确主角得到什么、固定对手当场失去什么；"
                        f"当前 reaction={reaction_text[:70]}；result={result_text[:100]}"
                    )
                    if (
                        re.search(r"(?:获得|拿到|赢得|进入).{0,10}复试(?:资格)?", result_text)
                        and re.search(r"复试现场|完成复试|参加复试|进入复试|第二轮复试|准备.{0,8}复试", action_text)
                    ):
                        failures.append(
                            f"{cid}第{milestone_chapter}章阶段倒置：行动已经在复试，结果才获得复试资格；"
                            "应由初试赢得复试资格，或由复试赢得终选资格"
                        )
                    if (
                        re.search(r"(?:获得|拿到|赢得|进入).{0,10}终选(?:资格)?", result_text)
                        and re.search(r"终选现场|完成终选|参加终选|进入终选", action_text)
                    ):
                        failures.append(
                            f"{cid}第{milestone_chapter}章阶段倒置：行动已经在终选，结果才获得终选资格"
                        )
                    core_resource_chapter = total_chapters - 2 if total_chapters >= 5 else total_chapters
                    authority_names = [
                        str(member.get("name") or "")
                        for member in cast
                        if isinstance(member, dict)
                        and re.search(r"制片人|片方负责人|公司高层", str(member.get("role") or ""))
                    ]
                    formal_role_gain = bool(re.search(
                        r"(?:获得|拿下|成为|正式出演|正式签约).{0,18}(?:女主角|主演|核心角色|角色合约)|"
                        r"(?:女主角|主演|核心角色).{0,12}(?:归属|合约)|"
                        r"(?:正式获得|正式拿下).{0,12}(?:该角色|这个角色|角色合约)",
                        result_text,
                    ))
                    if re.search(r"试镜资格|终选资格|复试资格", result_text):
                        formal_role_gain = False
                    if re.search(
                        r"(?:多部|[两三四五六七八九十\d]+部)(?:电影|影片)(?:主演|演员)合约",
                        result_text,
                    ):
                        formal_role_gain = False
                    if milestone_chapter == core_resource_chapter and not formal_role_gain:
                        failures.append(
                            f"{cid}第{milestone_chapter}章未完成全书唯一一次核心角色/角色合约正式授予"
                        )
                    if milestone_chapter == core_resource_chapter and not _has_actual_acting_action(action_text):
                        failures.append(
                                f"{cid}第{milestone_chapter}章核心角色授予缺少实际试戏/表演；不能只靠剧本建议或口头主张拿到角色"
                            )
                    if milestone_chapter == core_resource_chapter and re.search(
                        r"退居配角|改演配角|转为配角|获得配角|出演配角",
                        "\n".join((reaction_text, result_text)),
                    ):
                        failures.append(
                            f"{cid}第{milestone_chapter}章夺回核心角色后立刻补偿对手一个配角，削弱反杀；"
                            "应让对手明确退出该项目角色竞争"
                        )
                    if milestone_chapter > core_resource_chapter:
                        if formal_role_gain:
                            failures.append(
                                f"{cid}第{milestone_chapter}章重复或延迟授予核心角色；后续必须升级为不同合约权限、项目席位或新合作"
                            )
                        if re.search(r"复试|终选|试镜资格|第二轮试镜", milestone_text):
                            failures.append(
                                f"{cid}第{milestone_chapter}章收益倒退到复试/终选；后续必须升级为合约权限、项目席位或新合作"
                            )
                        if milestone_opponent_pattern and re.search(
                            rf"(?:避免|错开).{{0,12}}(?:与)?(?:{milestone_opponent_pattern}).{{0,12}}(?:行程|拍摄|排练)|"
                            rf"(?:{milestone_opponent_pattern}).{{0,24}}(?:继续|仍).{{0,10}}(?:参与|留在).{{0,10}}(?:剧组|拍摄|排练)",
                            milestone_text,
                            re.I | re.S,
                        ):
                            failures.append(
                                f"{cid}第{milestone_chapter}章让已失去核心角色的对手无解释继续留在同一项目拍摄/排练"
                            )
                        if re.search(
                            r"(?:失去|取消|终止|撤销).{0,24}(?:演员合约|合作|签约|续作|谈判|优先|项目资格|项目机会)",
                            "\n".join((reaction_text, result_text)),
                        ) and not _has_authorized_business_loss(milestone_text, authority_names):
                            failures.append(
                                f"{cid}第{milestone_chapter}章只宣称对手失去合作/谈判利益，"
                                "却没有片方、制片公司或制片人当场作出取消决定"
                            )
                    if milestone_chapter == total_chapters and not re.search(
                        r"(?:获得|拿下|签下|签署|得到).{0,18}"
                        r"(?:长期演员合约|长期合作合约|"
                        r"(?:多部|[两三四五六七八九十\d]+部)(?:电影|影片)(?:主演|演员)合约|"
                        r"制片公司长期合作(?:合约)?)",
                        result_text,
                    ):
                        failures.append(
                            f"{cid}第{milestone_chapter}章终局没有实际签下长期演员合约或制片公司长期合作；"
                            "签约权、签约机会或候选资格不算兑现"
                        )
                    if milestone_chapter == total_chapters and re.search(
                        r"颁奖晚宴|颁奖礼|庆功宴|红毯|酒会",
                        "\n".join((full_cluster_text, milestone_text)),
                    ):
                        failures.append(
                            f"{cid}第{milestone_chapter}章把终局放在颁奖/晚宴等仪式场景；"
                            "改为制片公司签约会议或片方合同会议"
                        )
                    if milestone_chapter == total_chapters and re.search(
                        r"(?:失去|取消|终止|撤销).{0,24}(?:优先合作|续作谈判|长期片约|多片约)",
                        "\n".join((reaction_text, result_text)),
                    ):
                        prior_story = "\n".join(
                            milestone_text_by_chapter.get(prior_chapter, "")
                            for prior_chapter in range(1, milestone_chapter)
                        )
                        cast_context = json.dumps(cast, ensure_ascii=False)
                        resource_patterns = (
                            r"优先.{0,6}合作",
                            r"续作.{0,6}谈判",
                            r"长期.{0,4}片约",
                            r"多片约",
                        )
                        current_loss_text = "\n".join((reaction_text, result_text))
                        required_resources = [
                            pattern for pattern in resource_patterns
                            if re.search(pattern, current_loss_text)
                        ]
                        if any(
                            not re.search(pattern, cast_context + prior_story)
                            for pattern in required_resources
                        ):
                            failures.append(
                                f"{cid}第{milestone_chapter}章才首次发明对手的优先合作/续作谈判资源并立刻剥夺；"
                                "必须在固定角色表或前面章节先建立"
                            )

                opponent_role = next(
                    (
                        str(member.get("role") or "")
                        for member in cast
                        if isinstance(member, dict)
                        and str(member.get("alignment") or "").casefold() == "opponent"
                    ),
                    "",
                )
                opponent_names = [
                    str(member.get("name") or "").strip()
                    for member in cast
                    if isinstance(member, dict)
                    and str(member.get("alignment") or "").casefold() == "opponent"
                    and str(member.get("name") or "").strip()
                ]
                opponent_pattern = "|".join(
                    re.escape(name) + "|" + re.escape(name.split()[0])
                    for name in opponent_names
                )
                if opponent_pattern and re.search(
                    rf"(?:{opponent_pattern}).{{0,35}}(?:宣布|决定|指定).{{0,28}}"
                    r"(?:接替|出演|角色归属|由她出演|取消.{0,8}资格|淘汰|换角|将角色交给|把角色交给)",
                    milestone_text,
                    re.I | re.S,
                ) and (
                    "助理" in opponent_role
                    or not re.search(r"选角导演|导演|制片人|片方负责人", opponent_role)
                ):
                    failures.append(
                        f"{cid}让无选角决策权的固定对手亲自宣布角色归属；"
                        "角色必须由现场已有的选角导演、导演、制片人或片方决定"
                    )

        if start >= 3 and not bool(cluster.get("is_final_arc")):
            payoff_text = "\n".join((core, outcome))
            has_stage_loss = bool(re.search(
                r"取消资格|撤下|换角|终止合作|退出|被拒绝入场|被迫让出|"
                r"(?:失去|错失|丧失)[^，。；,\n]{0,14}(?:权|权限|机会|角色|合约|资格|职位|合作|项目|资源|席位)",
                payoff_text,
            ))
            has_stage_gain = bool(re.search(
                r"拿下|获得|签约|赢得|确认出演|取得优先权|进入终选|获得正式合约",
                payoff_text,
            ))
            if not (has_stage_loss and has_stage_gain):
                failures.append(
                    f"{cid}未闭合首次今生资源反杀；结尾必须明确固定对手失去一项当前利益，"
                    "主角同时获得一项可继续升级的职业资源，不能只写关注、认可或首次受挫"
                )

        if bool(cluster.get("is_final_arc")):
            payoff_text = "\n".join((core, outcome, final_payoff))
            core_resource_chapter = total_chapters - 2 if total_chapters >= 5 else total_chapters
            if start > core_resource_chapter and re.search(
                r"(?:获得|拿下|签下|正式出演).{0,18}(?:女主角|主演|核心角色|角色合约)|"
                r"(?:失去|退出|换下|撤下).{0,18}(?:女主角|主演|核心角色|角色资格)",
                payoff_text,
            ):
                failures.append(
                    f"{cid}终局簇的core_payoff/cluster_outcome仍重复结算前簇已经完成的核心角色归属；"
                    "终局字段必须只总结新的演员合约、项目合作资格或长期合作得失"
                )
            has_loss = bool(re.search(
                r"取消资格|撤销|解约|停职|开除|换角|终止合作|赔偿|退出|被迫离场|"
                r"(?:失去|错失|丧失)[^，。；,\n]{0,16}(?:权|权限|机会|角色|合约|资格|职位|合作|项目|资源|席位|主导权)",
                payoff_text,
            ))
            has_gain = bool(re.search(
                r"拿回|拿下|获得|恢复|签约|洗清|赢得|确认出演|得到赔偿|重获",
                payoff_text,
            ))
            if not (has_loss and has_gain):
                failures.append(
                    f"{cid}终局只写舆论或形象变化；必须同时明确对手失去的现实利益和主角拿回的现实收益。"
                )

    if total_chapters >= 5:
        penultimate_milestone = milestone_text_by_chapter.get(total_chapters - 1, "")
        final_milestone = milestone_text_by_chapter.get(total_chapters, "")
        for resource_pattern in (
            r"优先.{0,6}合作",
            r"续作.{0,6}谈判",
            r"长期.{0,4}片约",
            r"多片约",
        ):
            penultimate_loss = bool(
                re.search(rf"(?:失去|取消|终止|撤销|剥夺).{{0,24}}{resource_pattern}", penultimate_milestone)
                or re.search(rf"{resource_pattern}.{{0,18}}(?:被)?(?:取消|终止|撤销|剥夺)", penultimate_milestone)
            )
            final_loss = bool(
                re.search(rf"(?:失去|取消|终止|撤销|剥夺).{{0,24}}{resource_pattern}", final_milestone)
                or re.search(rf"{resource_pattern}.{{0,18}}(?:被)?(?:取消|终止|撤销|剥夺)", final_milestone)
            )
            if penultimate_loss and final_loss:
                failures.append(
                    f"第{total_chapters - 1}章提前结算了终章才应剥夺的优先合作/续作谈判资源；"
                    "前章只能建立资源，实际损失必须换成另一项职业利益"
                )
                break

    milestone_results = [
        str(milestone.get("result") or "")
        for cluster in clusters
        for milestone in (cluster.get("chapter_milestones") or [])
        if isinstance(milestone, dict)
        and str(milestone.get("chapter") or "").isdigit()
        and int(milestone.get("chapter")) >= 2
    ]
    role_gain_chapters = [
        result for result in milestone_results
        if re.search(
            r"(?:获得|拿下|签下|成为|正式接替|正式获|成功争取到).{0,18}"
            r"(?:女主角|主演|正式角色|角色(?:合约)?|这个角色|该角色)",
            result,
        )
        and "试镜资格" not in result and "终选资格" not in result
        and not re.search(
            r"(?:多部|[两三四五六七八九十\d]+部)(?:电影|影片)(?:主演|演员)合约",
            result,
        )
    ]
    role_loss_chapters = [
        result for result in milestone_results
        if re.search(
            r"(?:失去|退出|调离|剥夺|换下|撤下).{0,18}(?:女主角|主演|角色位置|角色(?:合约)?)",
            result,
        )
    ]
    if len(role_gain_chapters) > 1 or len(role_loss_chapters) > 1:
        failures.append(
            "chapter_milestones 在多章重复结算同一主演角色；角色归属只能正式改变一次，"
            "后续必须升级为不同的合作、职位、资格或自主权得失"
        )
    return failures[:12]


def _normalize_cluster_names_from_seed_plan(
    clusters: List[Dict[str, Any]], global_seed_plan: str
) -> List[Dict[str, Any]]:
    """Repair obvious one-letter model typos against the fixed names established in the seed plan."""
    def _collapse_terminal_runs(value: str) -> str:
        return re.sub(r"([A-Za-z])\1{2,}(?=\b)", lambda match: match.group(1) * 2, value or "")

    obvious_replacements: Dict[str, str] = {}
    for cluster in clusters:
        candidate_names = [str(cluster.get("main_opponent") or "").strip()]
        candidate_names.extend(
            str(member.get("name") or "").strip()
            for member in (cluster.get("canonical_cast") or [])
            if isinstance(member, dict)
        )
        for name in candidate_names:
            collapsed = _collapse_terminal_runs(name)
            if name and collapsed != name:
                obvious_replacements[name] = collapsed

    def _replace_recursive(value: Any, replacements: Dict[str, str]) -> Any:
        if isinstance(value, str):
            result = value
            for wrong, fixed in replacements.items():
                result = result.replace(wrong, fixed)
            return result
        if isinstance(value, list):
            return [_replace_recursive(item, replacements) for item in value]
        if isinstance(value, dict):
            return {key: _replace_recursive(item, replacements) for key, item in value.items()}
        return value

    if obvious_replacements:
        clusters = [_replace_recursive(cluster, obvious_replacements) for cluster in clusters]
    normalized_seed_plan = _collapse_terminal_runs(global_seed_plan or "")
    seed_names = list(dict.fromkeys(re.findall(
        r"(?<![A-Za-z])([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2})(?![A-Za-z])",
        normalized_seed_plan,
    )))
    if not seed_names:
        return clusters

    generated_names: set[str] = set()
    for cluster in clusters:
        opponent = str(cluster.get("main_opponent") or "").strip()
        if re.fullmatch(r"[A-Za-z]+(?:\s+[A-Za-z]+){1,2}", opponent):
            generated_names.add(opponent)
        for member in cluster.get("canonical_cast") or []:
            if isinstance(member, dict):
                name = str(member.get("name") or "").strip()
                if re.fullmatch(r"[A-Za-z]+(?:\s+[A-Za-z]+){1,2}", name):
                    generated_names.add(name)

    replacements: Dict[str, str] = {}
    for generated in generated_names:
        generated_first = generated.split()[0].casefold()
        candidates = [name for name in seed_names if name.split()[0].casefold() == generated_first]
        if not candidates:
            continue
        best = max(candidates, key=lambda name: SequenceMatcher(None, generated.casefold(), name.casefold()).ratio())
        ratio = SequenceMatcher(None, generated.casefold(), best.casefold()).ratio()
        if generated != best and ratio >= 0.88:
            replacements[generated] = best
    if not replacements:
        return clusters

    return [_replace_recursive(cluster, replacements) for cluster in clusters]


def _normalize_short_event_milestones_from_seed_plan(
    clusters: List[Dict[str, Any]],
    global_seed_plan: str,
) -> List[Dict[str, Any]]:
    sections = _seed_plan_chapter_sections(global_seed_plan)
    if not sections:
        return clusters
    cast = _canonical_cast_from_seed_plan(global_seed_plan)
    protagonist_name = next(
        (str(member.get("name") or "") for member in cast if member.get("alignment") == "protagonist"),
        "主角",
    )
    opponent_name = next(
        (str(member.get("name") or "") for member in cast if member.get("alignment") == "opponent"),
        "固定对手",
    )
    ally_name = next(
        (str(member.get("name") or "") for member in cast if member.get("alignment") == "ally"),
        "关键盟友",
    )
    total_chapters = max(sections)
    core_chapter = total_chapters - 2 if total_chapters >= 5 else total_chapters
    planned_work_titles = list(dict.fromkeys(re.findall(r"《([^》\n]{1,40})》", global_seed_plan)))
    normalized = json.loads(json.dumps(clusters, ensure_ascii=False))
    for cluster in normalized:
        cluster["planned_work_titles"] = planned_work_titles
        milestones = cluster.get("chapter_milestones") or []
        for milestone in milestones if isinstance(milestones, list) else []:
            if not isinstance(milestone, dict):
                continue
            try:
                chapter = int(milestone.get("chapter"))
            except (TypeError, ValueError):
                continue
            section = sections.get(chapter, "")
            seed_action = _seed_section_field(section, "主角行动")
            seed_reaction = _seed_section_field(section, "对手反应")
            seed_result = _seed_section_field(section, "本章结果")
            seed_scene = _seed_section_field(section, "场景")
            action = str(milestone.get("action") or "").strip()
            reaction = str(milestone.get("opponent_reaction") or "").strip()
            result = str(milestone.get("result") or "").strip()
            if chapter == 1:
                action = seed_action or action
                reaction = seed_reaction or reaction
                result = seed_result or result
            elif chapter == 2:
                if re.search(r"试镜现场|进入试镜|完成试镜|复试|终选", action):
                    action = ""
                action = seed_action or action
                if not re.search(r"重生|确认.{0,10}(?:日期|时间)|回到.{0,12}(?:前|那天)", action + result):
                    action = (
                        f"{protagonist_name}核对手机日期与公寓环境，确认自己重生回到关键试镜前；"
                        + (action or f"联系{ally_name}预约会面")
                    )
                result = seed_result or f"预约与{ally_name}会面"
                if "确认重生并完成首次部署" not in result:
                    result = f"{protagonist_name}确认重生并完成首次部署：{result}"
                reaction = seed_reaction or reaction or f"{opponent_name}尚未介入当前行动"
            elif chapter >= 3:
                action = seed_action or action
                reaction = seed_reaction or reaction
                result = seed_result or result
                if chapter == total_chapters - 1:
                    if re.search(r"续作.{0,6}谈判", seed_scene) and not re.search(r"续作.{0,6}谈判", reaction):
                        reaction = reaction.rstrip("。；; ") + f"；会议议程确认{opponent_name}仍持有片方续作优先谈判条款"
                    elif re.search(r"优先.{0,6}合作", seed_scene) and not re.search(r"优先.{0,6}合作", reaction):
                        reaction = reaction.rstrip("。；; ") + f"；会议议程确认{opponent_name}仍持有片方优先合作条款"
            milestone["action"] = action or seed_action
            milestone["opponent_reaction"] = reaction or seed_reaction
            milestone["result"] = result or seed_result
        cluster["main_opponent"] = opponent_name
        normalized_milestones = [
            milestone for milestone in milestones
            if isinstance(milestone, dict)
        ] if isinstance(milestones, list) else []
        milestone_actions = [
            str(milestone.get("action") or "").strip()
            for milestone in normalized_milestones
            if str(milestone.get("action") or "").strip()
        ]
        milestone_results = [
            str(milestone.get("result") or "").strip()
            for milestone in normalized_milestones
            if str(milestone.get("result") or "").strip()
        ]
        chapter_numbers = {
            int(milestone.get("chapter"))
            for milestone in normalized_milestones
            if str(milestone.get("chapter") or "").isdigit()
        }
        first_section = sections.get(1, "")
        cluster["prev_life_tragedy"] = "；".join(filter(None, (
            _seed_section_field(first_section, "主角行动"),
            _seed_section_field(first_section, "对手反应"),
            _seed_section_field(first_section, "本章结果"),
        )))
        cluster["info_gap_from_prev_life"] = (
            f"{protagonist_name}只保留对试镜日期、公开流程、{opponent_name}当场话术和旧经纪人选择的记忆；"
            "这些记忆只用于调整今生行动，不是可提交的物证"
        )
        if chapter_numbers == {1}:
            cluster["this_life_revenge"] = "本簇只写上一世失败与死亡，不进入今生行动"
        else:
            cluster["this_life_revenge"] = "；".join(milestone_actions)
        if milestone_results:
            cluster["core_payoff"] = milestone_results[-1]
            cluster["cluster_outcome"] = milestone_results[-1]
            cluster["summary"] = "；".join(milestone_results)
            if bool(cluster.get("is_final_arc")):
                cluster["final_goal"] = milestone_results[-1]
                cluster["final_payoff"] = "；".join(milestone_results)
        cluster["notes"] = [
            "章节行动、对手反应与结果均以已验收主线蓝图为准，不新增证据、角色权限或未建立资源"
        ]
    return normalized


def _normalize_event_cluster_shape(
    clusters: List[Dict[str, Any]],
    global_seed_plan: str = "",
) -> List[Dict[str, Any]]:
    """Normalize harmless Qwen schema drift before judging story semantics."""
    cast_template = next(
        (
            cluster.get("canonical_cast")
            for cluster in clusters
            if isinstance(cluster.get("canonical_cast"), list)
            and any(
                isinstance(member, dict)
                and str(member.get("alignment") or "").casefold() == "protagonist"
                for member in cluster.get("canonical_cast")
            )
            and any(
                isinstance(member, dict)
                and str(member.get("alignment") or "").casefold() == "opponent"
                for member in cluster.get("canonical_cast")
            )
        ),
        None,
    )
    normalized: List[Dict[str, Any]] = []
    for original in clusters:
        cluster = dict(original)
        current_cast = cluster.get("canonical_cast")
        current_cast = current_cast if isinstance(current_cast, list) else []
        current_names = {
            str(member.get("name") or "").strip()
            for member in current_cast
            if isinstance(member, dict) and str(member.get("name") or "").strip()
        }
        template_names = {
            str(member.get("name") or "").strip()
            for member in cast_template or []
            if isinstance(member, dict) and str(member.get("name") or "").strip()
        }
        current_alignments = {
            str(member.get("alignment") or "").casefold()
            for member in current_cast if isinstance(member, dict)
        }
        incomplete_cast = not {"protagonist", "opponent"}.issubset(current_alignments)
        omitted_known_members = bool(current_names) and current_names < template_names
        if (
            cast_template
            and (incomplete_cast or omitted_known_members)
            and current_names.issubset(template_names)
        ):
            cluster["canonical_cast"] = json.loads(json.dumps(cast_template, ensure_ascii=False))
        raw_span = cluster.get("chapter_span")
        if isinstance(raw_span, str):
            try:
                parsed_span = json.loads(raw_span)
            except json.JSONDecodeError:
                parsed_span = [int(x) for x in re.findall(r"\d+", raw_span)[:2]]
            if isinstance(parsed_span, list) and len(parsed_span) >= 2:
                try:
                    cluster["chapter_span"] = [int(parsed_span[0]), int(parsed_span[1])]
                except (TypeError, ValueError):
                    pass

        if cluster.get("chapter_span") != [2, 2]:
            cast_opponents = [
                str(member.get("name") or "").strip()
                for member in (cluster.get("canonical_cast") or [])
                if isinstance(member, dict)
                and str(member.get("alignment") or "").casefold() == "opponent"
                and str(member.get("name") or "").strip()
            ]
            current_opponent = str(cluster.get("main_opponent") or "").strip()
            matching = next((name for name in cast_opponents if name in current_opponent), "")
            if matching and current_opponent != matching:
                cluster["main_opponent"] = matching
        normalized.append(cluster)
    max_span_end = max(
        (
            int(cluster.get("chapter_span", [0, 0])[1])
            for cluster in normalized
            if isinstance(cluster.get("chapter_span"), (list, tuple))
            and len(cluster.get("chapter_span")) == 2
        ),
        default=0,
    )
    if global_seed_plan and max_span_end <= 12:
        normalized = _normalize_short_event_milestones_from_seed_plan(
            normalized,
            global_seed_plan,
        )
    return normalized


def _failures_target_only_final_cluster(
    clusters: List[Dict[str, Any]], failures: List[str]
) -> bool:
    """Return whether replacing the one final cluster can resolve every failure."""
    final_clusters = [cluster for cluster in clusters if bool(cluster.get("is_final_arc"))]
    if len(final_clusters) != 1 or not failures:
        return False
    final_id = str(final_clusters[0].get("cluster_id") or "").strip()
    if not final_id:
        return False
    return all(
        failure.startswith(final_id)
        or failure.startswith("chapter_milestones 在多章重复结算同一主演角色")
        for failure in failures
    )


def _failures_target_only_opening_cluster(
    clusters: List[Dict[str, Any]], failures: List[str]
) -> bool:
    opening = next(
        (cluster for cluster in clusters if cluster.get("chapter_span") == [1, 1]),
        None,
    )
    if not opening or not failures:
        return False
    opening_id = str(opening.get("cluster_id") or "").strip()
    return bool(opening_id) and all(failure.startswith(opening_id) for failure in failures)


def _long_form_cluster_spans(
    total_chapters: int, final_arc_len: int
) -> List[List[int]]:
    """Build short-drama spans while reserving one explicit final arc."""
    final_start = total_chapters - final_arc_len + 1
    spans: List[List[int]] = [[1, 1], [2, 2]]
    chapter = 3
    while chapter < final_start:
        end = min(chapter + 1, final_start - 1)
        spans.append([chapter, end])
        chapter = end + 1
    spans.append([final_start, total_chapters])
    return spans


def _long_form_cluster_failures(
    clusters: List[Dict[str, Any]], expected_spans: List[List[int]]
) -> List[str]:
    """Validate long-form one-to-two-chapter event clusters and the final arc."""
    failures: List[str] = []
    actual_spans = [cluster.get("chapter_span") for cluster in clusters]
    if actual_spans != expected_spans:
        failures.append(f"事件簇跨度必须严格为 {expected_spans}，实际为 {actual_spans}")
        return failures
    required_fields = (
        "name", "arc_id", "core_payoff", "main_opponent", "prev_life_tragedy",
        "info_gap_from_prev_life", "this_life_revenge", "cluster_outcome", "summary",
    )
    for index, cluster in enumerate(clusters, 1):
        cid = str(cluster.get("cluster_id") or f"EC{index:02d}")
        missing = [field for field in required_fields if not str(cluster.get(field) or "").strip()]
        if missing:
            failures.append(f"{cid} 缺少字段内容：{'、'.join(missing)}")
        start, end = expected_spans[index - 1]
        milestones = [m for m in (cluster.get("chapter_milestones") or []) if isinstance(m, dict)]
        milestone_chapters: List[int] = []
        for milestone in milestones:
            try:
                milestone_chapters.append(int(milestone.get("chapter")))
            except (TypeError, ValueError):
                pass
            for field in ("action", "opponent_reaction", "result"):
                if not str(milestone.get(field) or "").strip():
                    failures.append(f"{cid} chapter_milestones 缺少 {field}")
                    break
        if milestone_chapters != list(range(start, end + 1)):
            failures.append(
                f"{cid} chapter_milestones 必须逐章覆盖 {list(range(start, end + 1))}，"
                f"实际为 {milestone_chapters}"
            )
    final_flags = [bool(cluster.get("is_final_arc")) for cluster in clusters]
    if final_flags != [False] * (len(clusters) - 1) + [True]:
        failures.append("只能由最后一个事件簇标记 is_final_arc=true")
    return failures


def _fill_long_cluster_causal_fields(
    cluster: Dict[str, Any],
    protagonist_name: str = "主角",
) -> Dict[str, Any]:
    """Fill a compact model omission without inventing a new plot branch."""
    result = dict(cluster)
    span = result.get("chapter_span") or [0, 0]
    try:
        start = int(span[0])
    except (TypeError, ValueError, IndexError):
        start = 0
    opponent = str(result.get("main_opponent") or "既有对手").strip()
    info_gap = str(result.get("info_gap_from_prev_life") or "").strip()
    revenge = str(result.get("this_life_revenge") or "").strip()
    if not str(result.get("prev_life_tragedy") or "").strip():
        causal_detail = (
            info_gap
            or revenge
            or str(result.get("cluster_outcome") or "").strip()
            or str(result.get("summary") or "").strip()
            or str(result.get("core_payoff") or "").strip()
        )
        if start == 1:
            tragedy = (
                f"上一世，{opponent}推动了本题材已经规划的核心失败，"
                f"{protagonist_name}付出不可逆代价后才看清关键因果：{causal_detail[:100]}"
            )
        elif start == 2:
            tragedy = (
                f"{protagonist_name}仍清楚记得上一世的核心失败与不可逆代价，"
                f"并记得足以改变当前选择的关键细节：{causal_detail[:100]}"
            )
        else:
            tragedy = (
                f"上一世在同一冲突环节，{opponent}利用信息差或既有权限推进旧局；"
                f"{protagonist_name}直到受损后才看清关键流程：{causal_detail[:100]}"
            )
        result["prev_life_tragedy"] = tragedy
    return result


def _long_form_focus_specs(
    specs: List[Dict[str, Any]],
    final_span: List[int],
) -> List[Dict[str, Any]]:
    """Describe structural duties without injecting a domain-specific plot."""
    focus_specs: List[Dict[str, Any]] = []
    for spec in specs:
        span = list(spec.get("chapter_span") or [])
        start = int(span[0]) if span else 0
        if start == 1:
            focus = (
                "只完成蓝图中的上一世核心失败、不可逆代价与明确死亡/终止；"
                "不得进入重生后的行动"
            )
        elif start == 2:
            focus = (
                "只完成核对时间地点身份、确认重生与一个首次部署；"
                "不得提前兑现正式反杀"
            )
        elif span == final_span:
            focus = (
                "逐章回收蓝图的终局条件并完成最终双向结算；"
                "不得临时增加题材、角色、证据或终局机制"
            )
        else:
            focus = (
                "严格服从蓝图中覆盖该章节区间的阶段目标，完成一个1-2章即时闭环；"
                "不得重复前簇冲突或收益"
            )
        focus_specs.append({
            "cluster_id": spec.get("cluster_id"),
            "chapter_span": span,
            "focus": focus,
        })
    return focus_specs


def _long_seed_excerpt(global_seed_plan: str) -> str:
    """Keep the authored cast/arcs while dropping repeated runtime contracts."""
    text = str(global_seed_plan or "")
    text = text.split("【人工约束】", 1)[0]
    markers = ["**【固定角色表】**", "【固定角色表】"]
    starts = [text.find(marker) for marker in markers if text.find(marker) >= 0]
    if starts:
        text = text[min(starts):]
    return text[-16000:]


def _matching_cached_long_cluster_batch(
    cached_payload: Any,
    *,
    seed_fingerprint: str,
    specs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return a cache batch only when both story identity and requested spans match."""
    if (
        not isinstance(cached_payload, dict)
        or cached_payload.get("seed_fingerprint") != seed_fingerprint
    ):
        return []
    cached = cached_payload.get("clusters")
    if not isinstance(cached, list) or not all(isinstance(item, dict) for item in cached):
        return []
    cached_specs = [
        {
            "cluster_id": str(item.get("cluster_id") or ""),
            "chapter_span": item.get("chapter_span"),
            "is_final_arc": bool(item.get("is_final_arc")),
        }
        for item in cached
    ]
    return cached if cached_specs == specs else []


def _generate_long_event_clusters_in_batches(
    global_seed_plan: str,
    *,
    final_arc_len: int,
    total_chapters: int,
) -> List[Dict[str, Any]]:
    """Generate compact event clusters in batches to avoid long JSON truncation."""
    spans = _long_form_cluster_spans(total_chapters, final_arc_len)
    seed_excerpt = _long_seed_excerpt(global_seed_plan)
    seed_fingerprint = hashlib.sha256(seed_excerpt.encode("utf-8")).hexdigest()
    seed_cast = _canonical_cast_from_seed_plan(global_seed_plan)
    protagonist_name = next(
        (
            str(member.get("name") or "").strip()
            for member in seed_cast
            if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "protagonist"
            and str(member.get("name") or "").strip()
        ),
        MAIN_PROTAGONIST or "主角",
    )
    assembled: List[Dict[str, Any]] = []
    batch_size = 6
    total_batches = (len(spans) + batch_size - 1) // batch_size
    for batch_index in range(total_batches):
        batch_spans = spans[batch_index * batch_size:(batch_index + 1) * batch_size]
        first_id = batch_index * batch_size + 1
        specs = [
            {
                "cluster_id": f"EC{first_id + offset:02d}",
                "chapter_span": span,
                "is_final_arc": span == spans[-1],
            }
            for offset, span in enumerate(batch_spans)
        ]
        diagnostics_dir = os.path.join(OUTPUT_DIR, "planning_diagnostics")
        diagnostics_path = os.path.join(
            diagnostics_dir, f"event_cluster_batch_v3_{batch_index + 1:02d}.json"
        )
        if os.path.isfile(diagnostics_path):
            try:
                with open(diagnostics_path, "r", encoding="utf-8") as diagnostics_file:
                    cached_payload = json.load(diagnostics_file)
                cached = _matching_cached_long_cluster_batch(
                    cached_payload,
                    seed_fingerprint=seed_fingerprint,
                    specs=specs,
                )
                if cached:
                    assembled.extend(
                        _fill_long_cluster_causal_fields(cluster, protagonist_name)
                        for cluster in cached
                    )
                    print(
                        f"✅ 复用长篇事件簇第 {batch_index + 1}/{total_batches} 批："
                        f"{batch_spans[0][0]}-{batch_spans[-1][1]}章",
                        flush=True,
                    )
                    continue
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        focus_specs = _long_form_focus_specs(specs, spans[-1])
        prior_summary = [
            {
                "cluster_id": item.get("cluster_id"),
                "chapter_span": item.get("chapter_span"),
                "name": item.get("name"),
                "result": item.get("cluster_outcome"),
            }
            for item in assembled[-8:]
        ]
        prompt = f"""下面是已经验收的全书主线蓝图精简稿：

{seed_excerpt}

请只为下列指定跨度生成事件簇 JSON 数组：
{json.dumps(specs, ensure_ascii=False)}

【本批逐簇题眼，不得互换、合并或重复前簇】
{json.dumps(focus_specs, ensure_ascii=False)}

【紧邻的已完成事件簇，禁止重复其冲突与收益】
{json.dumps(prior_summary, ensure_ascii=False)}

【本批硬规则】
1. 顶层必须是 JSON 数组，对象数量、cluster_id、chapter_span、is_final_arc 与上方清单逐项完全一致，不增删跨度。
2. 每个对象必须包含：cluster_id,name,arc_id,core_payoff,chapter_span,main_opponent,escalation_level,prev_life_tragedy,info_gap_from_prev_life,this_life_revenge,cluster_outcome,summary,notes,canonical_cast,chapter_milestones,is_final_arc；终局对象另含 final_goal 与 final_payoff。
3. canonical_cast 统一输出 []，程序会从蓝图固定角色表复制。main_opponent 使用蓝图里的唯一固定姓名或机构称呼。
4. 第1章只写蓝图已经建立的上一世核心失败、不可逆代价与明确死亡/终止；第2章只写核对现实、确认重生和一个首次部署。具体死法、职业、地点和部署均服从蓝图，不得套用其他题材。除此之外，每个1-2章簇必须独立完成一次即时复仇：主角主动改变现场条件，对手亲自出招并暴露，当场失去一项具体利益或权限，主角同时获得具体收益。
5. 每个对象的 chapter_milestones 必须逐章覆盖 chapter_span，每项严格为 {{"chapter":整数,"action":"本章主动动作","opponent_reaction":"可见反应","result":"本章已经生效的双向结果"}}。即使是两章簇，第一章也必须先有一个小胜，不得只受压。
6. 前世信息差只能是主角记住的日期、原话、流程、条款和人物选择；现实证据必须由今生主动布局产生。禁止匿名线索、神秘人递证、黑客万能破解、长期查账和连续调查。
7. 反杀手段与场景要轮换；盟友、支持者、组织或群体只有在蓝图建立后才能参与，并必须通过本题材合理的公开行动发挥作用。滑稽反派可以嘴硬、自作聪明并亲手暴露，但不能把威胁降成纯喜剧。
8. 非终局对象每个字符串尽量不超过90个汉字，summary不超过120字，notes最多3条。只输出合法 JSON，不输出 Markdown 或解释。
9. 最后终局簇虽跨多章，但每章 milestone 都必须兑现一个即时小反杀，并按蓝图依次回收终局清单；不得等最后一章才统一回报，也不得临时增加假死、葬礼、直播审判或其他蓝图未建立的机制。
10. 第{spans[-1][0]}章以前不得执行蓝图的最终行动或完成最终结算，只能逐步取得终局所需的关系、权限、资源、规则或合法证据；最终行动只能在跨度{spans[-1]}内发生。
11. 不得重复夺回同一种资源或权限；题眼相近时必须落到不同且递进的具体对象，并与紧邻已完成事件簇的结果区分。
"""
        messages = [
            {
                "role": "system",
                "content": "你是百章高情绪重生短剧的事件簇设计师，擅长1-2章闭环与分批保持全书一致。",
            },
            {"role": "user", "content": prompt},
        ]
        batch: List[Dict[str, Any]] = []
        last_error = ""
        for attempt in range(1, 4):
            raw = legacy_v2.call_qianwen_api(
                messages,
                temperature=0.68 if attempt == 1 else 0.42,
                top_p=0.82 if attempt == 1 else 0.72,
            )
            candidate = _extract_json_array_maybe(raw)
            actual_specs = [
                {
                    "cluster_id": str(item.get("cluster_id") or ""),
                    "chapter_span": item.get("chapter_span"),
                    "is_final_arc": bool(item.get("is_final_arc")),
                }
                for item in candidate
            ]
            if actual_specs == specs:
                batch = candidate
                break
            last_error = f"期待 {specs}，实际 {actual_specs}"
            messages[-1]["content"] = (
                prompt + "\n\n上次输出的对象清单不合格：" + last_error
                + "。请完整重写本批，只输出合法 JSON 数组。"
            )
        if not batch:
            raise RuntimeError(
                f"长篇事件簇第 {batch_index + 1}/{total_batches} 批生成失败：{last_error or '无法解析JSON'}"
            )
        batch = [
            _fill_long_cluster_causal_fields(cluster, protagonist_name)
            for cluster in batch
        ]
        os.makedirs(diagnostics_dir, exist_ok=True)
        with open(
            diagnostics_path,
            "w",
            encoding="utf-8",
        ) as diagnostics_file:
            json.dump(
                {
                    "seed_fingerprint": seed_fingerprint,
                    "clusters": batch,
                },
                diagnostics_file,
                ensure_ascii=False,
                indent=2,
            )
        assembled.extend(batch)
        print(
            f"✅ 长篇事件簇第 {batch_index + 1}/{total_batches} 批完成："
            f"{batch_spans[0][0]}-{batch_spans[-1][1]}章",
            flush=True,
        )

    assembled = _apply_seed_cast_to_clusters(assembled, global_seed_plan)
    assembled = _normalize_cluster_names_from_seed_plan(assembled, global_seed_plan)
    assembled = _normalize_event_cluster_shape(assembled, global_seed_plan)
    failures = _long_form_cluster_failures(assembled, spans)
    if failures:
        raise RuntimeError("分批事件簇统一验收失败：" + "；".join(failures[:5]))
    return assembled


def _generate_event_clusters_v2_with_final_arc(
    global_seed_plan: str,
    *,
    final_arc_len: int,
    total_chapters: int = 100,
) -> List[Dict[str, Any]]:
    """
    生成事件簇（V2），并强制要求包含“终局大情节族”。
    注意：终局目标不硬编码，由模型基于 global_seed_plan 自行设定。
    """
    max_final_arc_len = max(1, total_chapters - 3) if 5 <= total_chapters <= 12 else max(1, total_chapters - 1)
    final_arc_len = max(1, min(int(final_arc_len), max_final_arc_len))
    final_start = total_chapters - final_arc_len + 1
    final_end = total_chapters

    if total_chapters > 12:
        return _generate_long_event_clusters_in_batches(
            global_seed_plan,
            final_arc_len=final_arc_len,
            total_chapters=total_chapters,
        )

    base_prompt = legacy_v2.build_event_cluster_prompt(global_seed_plan)
    base_prompt = base_prompt.replace("1~100", f"1~{total_chapters}").replace(
        "100 章", f"{total_chapters} 章"
    )
    short_run_contract = ""
    expected_short_spans: List[List[int]] = []
    if 5 <= total_chapters <= 12:
        expected_short_spans = [[1, 1], [2, 2], [3, final_start - 1], [final_start, final_end]]
        short_run_contract = f"""

【短篇输出规模合同，优先级高于上文“建议10-25个事件簇”】
- 本次只有 {total_chapters} 章，必须恰好输出 4 个对象，chapter_span 依次且只能是：{json.dumps(expected_short_spans, ensure_ascii=False)}。
- EC01只写上一世死亡；EC02只写重生确认；EC03连续完成首次今生资源反杀；EC04是终局清算。不得按章拆成更多簇。
- 为减少重复和截断，4个对象的 canonical_cast 都写 []；程序会从主线蓝图解析唯一固定角色表，复制到每个对象并再次校验。
- 每个字符串字段尽量控制在80个汉字内，summary不超过120个汉字；除必需的 chapter_milestones 外，不要输出 chapter_plan、解释或额外字段，以免JSON截断。
"""

    extra = f"""

【本次主题硬锁定：不得偏离】
{constraints_text()}

【新增硬性结构要求：必须有终局大情节族（final arc）】
1) 你的输出必须包含且仅包含 1 个“终局大情节族”，建议放在数组最后一个元素。
2) 终局大情节族必须满足：
   - is_final_arc: true
   - chapter_span: [{final_start}, {final_end}]（必须严格一致）
   - final_goal: 用 1 句中文写清“本书最终复仇目标/终局清算结果”（必须具体可执行，不能写成‘更大风暴即将来临’）
   - final_payoff: 用 1-2 句写清终局兑现方式（公众/法律/资本/行业层面如何落锤）
3) 终局大情节族的目标（final_goal）必须从「最大复仇主线蓝图」自然推出，不允许额外引入全新世界观、全新终极Boss、或天降决定性证据。
4) 在终局大情节族之前的所有事件簇，chapter_span 的 end 不得大于 {final_start - 1}。
5) 除终局大情节族外，其余簇不要写泛泛的“更大风暴”；每个簇必须在簇内闭合一个小复仇故事。
6) 所有 chapter_span 必须落在 1~{total_chapters}，合计覆盖本次测试的 {total_chapters} 章，不得生成范围外章节。
7) 每个事件簇都必须保留 canonical_cast 字段；短篇模式统一写 []，程序从主线蓝图锁定角色表。main_opponent 必须只填写其中一个固定对手姓名，不得用斜杠、&或泛称拼接第二个对手。
8) 除第1章“旧阶段失败”与第2章“重生确认”外，每个簇都必须写出至少一个章内小爽点：主角主动出招、对手当场失算、旁观者态度反转、主角获得具体收益或对手承受具体损失；不能把所有爽点都拖到终局。
9) info_gap_from_prev_life 只能是主角脑中保留的时间、话术、规则、人物选择或事件顺序。前世录音、文件、手机、截图、邮件等实体不会随重生携带；绝对禁止“凭记忆还原录音/文件”。若需要物证，只能写主角今生根据记忆提前布置，让对手在当前时间线亲自留下。
10) 快节奏爽文的主推进必须是“抢角色、改试镜条件、拒绝陷阱合同、逼对手当场失算、拿回职业资源”。录音、媒体、热搜和调查只能是极少量辅助，不能把一个事件簇设计成“找证据→联系媒体→公开爆料”；不得用私人邮件、私密录音、偷拍视频、隐藏文件或来源不明的内部材料解决冲突。
11) core_payoff、cluster_outcome 以及终局 final_payoff 必须同时写清：对手当场失去什么现实利益，主角当场拿回什么现实收益。只写名誉扫地、公众愤怒、舆论崩塌、获得尊重，不算兑现。
12) 第1章只负责完整写到上一世生命结束；对应事件簇的 this_life_revenge 必须明确写“本簇不进入今生”，不得提前塞入试镜翻盘或递交材料。
13) 短篇测试也要遵守现实权限：选角导演只能决定角色，品牌只能决定代言，电影节不能凭一段录音让人立刻获得虚构奖项。惩罚与奖励必须由现场已有且有权的人作出，并与冲突规模相称。
14) 每个对象必须包含 chapter_milestones 数组，严格逐章覆盖其 chapter_span；元素格式为 {{"chapter":章号,"action":"主角本章主动动作","opponent_reaction":"固定对手可见反应（第2章可写不出场）","result":"本章已经生效的阶段结果"}}。多章簇不得只概括首章或末章。
15) 主角不得向盟友、对手或公众直接说自己重生；重生只作为主角内心的信息差，盟友只能因她当前可见的专业判断和行动选择协助。
16) 禁止用“揭露贿赂、公开过往操纵记录、托人脉寻找间接证据”完成反杀；必须由当前场景可见的表演、合同条款、公开规则或对手亲自做出的动作解决冲突。
17) 第1章 chapter_milestones.result 必须明确写到上一世死亡，不能只写事业崩塌。
18) 第3章起每章里程碑都必须形成双向阶段结果：主角得到一项现实收益，固定对手当场失去一项利益、权限或机会；不能只写主角获认可。
19) canonical_cast 身份必须现实且权限一致：演员/影后不能同时写成助理；无选角决策权的人不能宣布角色归属。任何“角色/角色合约”无论是否写女主角，只能正式授予一次。
20) 第1章必须写明具体死亡方式（如车祸身亡），并在后续簇保持一致；第2章只确认重生和完成首次部署，绝不能获得复试、终选、角色、资格或合约。
21) 经纪人不能宣布淘汰、换角或角色归属；这类决定只能由选角导演、导演、制片人或片方负责人作出。
22) 禁止用“过往争议、曾经违规、行为模式、违规操作”等无来源旧账反杀，也禁止把发布会、媒体追问、舆论或公众信任变化当作清算。
23) 第3章起对手每章必须失去角色、合约、职位、资格、项目权限、合作机会或同级职业利益；“名誉受损、尴尬、沉默、失去公众信任”不算损失。
24) 核心角色正式授予章必须有主角真实试戏、表演、台词演绎或即兴发挥；不能只靠剧本建议、口头主张或盟友偏爱拿到角色。
25) 首映礼、媒体采访、记者追问、揭露当年操作都不能承担终局；终局必须发生在当前合同或片方决策场景。
26) 固定演员不得更换编剧/导演/制作团队、调动人员或决定公司人事；演员对手不能被调往部门、剥夺公司职位、参加项目竞标，也不能凭空拥有剧本参与权、剪辑权或幕后/项目顾问职位，只能失去角色、演员合约、项目合作资格或片方优先合作机会。
27) 不得先完成复试/终选，再在result中获得复试/终选资格；终局簇的core_payoff、cluster_outcome、final_payoff也不得重复总结前簇已经结算的核心角色归属。
28) 演员/影后对手只能施压、争抢或嘲讽，不能宣布取消资格、淘汰、换角或把角色交给别人；禁止用“过去拒绝合作、过去一年阻碍新人、质疑过往不当操作、影响公司口碑”等概括性旧账完成第5-6章清算。
29) 若人工限制包含“不要投资”，不得让投资人、投资方或资本施压参与推进；终章result必须写主角实际签下长期演员合约、多部影片演员合约或制片公司长期合作合约，签约权/机会不算。
30) 核心角色授予章不得给对手补偿配角；第5-6章合作/谈判损失必须由片方、制片公司或制片人当场宣布取消/终止/不再续约。第5章先建立对手现有优先合作或续作谈判资源但不得提前让她失去，本章另损失一项当前项目利益，终章才剥夺前述资源；终章不得使用颁奖晚宴、庆功宴、红毯或酒会。
31) 主角演员只能谈判和签署自己的合约，不能要求重审、取消对手旧合同或把对手剔出系列片/项目；对手失去核心角色后不得无解释继续留在同一剧组拍摄/排练，也不得让主角调整日程去避开她。
32) 第1章result正文必须明确具体死亡方式，不能只在簇名/章节标题写“死亡”；不得出示对手私下接触其他剧组、违规或操控的证据。
{short_run_contract}
"""
    user_prompt = base_prompt + extra
    messages = [
        {
            "role": "system",
            "content": "你是长篇重生题材小说的结构设计师，需要在给定主线蓝图下设计事件簇，并以 JSON 数组输出。",
        },
        {"role": "user", "content": user_prompt},
    ]
    max_attempts = 5
    short_object_fallback_attempted = False
    parse_failure_count = 0
    semantic_failure_count = 0
    for attempt in range(1, max_attempts + 1):
        raw = legacy_v2.call_qianwen_api(
            messages,
            temperature=0.7 if attempt == 1 else 0.45,
            top_p=0.85 if attempt == 1 else 0.75,
        )
        clusters = _extract_json_array_maybe(raw)
        if clusters:
            clusters = _apply_seed_cast_to_clusters(clusters, global_seed_plan)
            clusters = _normalize_cluster_names_from_seed_plan(clusters, global_seed_plan)
            clusters = _normalize_event_cluster_shape(clusters, global_seed_plan)
            semantic_failures = _event_cluster_semantic_failures(
                clusters, total_chapters=total_chapters
            )
            if expected_short_spans:
                actual_spans = [cluster.get("chapter_span") for cluster in clusters]
                if actual_spans != expected_short_spans:
                    semantic_failures.insert(
                        0,
                        f"短篇必须恰好使用固定4簇跨度 {expected_short_spans}，实际为 {actual_spans}",
                    )
            if semantic_failures:
                semantic_failure_count += 1
                if _failures_target_only_opening_cluster(clusters, semantic_failures):
                    repaired = _repair_opening_cluster_only(
                        clusters,
                        global_seed_plan=global_seed_plan,
                        total_chapters=total_chapters,
                        semantic_failures=semantic_failures,
                    )
                    if repaired:
                        print(
                            f"✅ 事件簇第 {attempt} 次仅开篇对象不合格，已通过单对象定向重写修复。",
                            flush=True,
                        )
                        return repaired
                if _failures_target_only_final_cluster(clusters, semantic_failures):
                    repaired = _repair_final_cluster_only(
                        clusters,
                        global_seed_plan=global_seed_plan,
                        total_chapters=total_chapters,
                        semantic_failures=semantic_failures,
                    )
                    if repaired:
                        print(
                            f"✅ 事件簇第 {attempt} 次仅终局不合格，已通过单对象定向重写修复。",
                            flush=True,
                        )
                        return repaired
                if (
                    expected_short_spans
                    and semantic_failure_count >= 2
                    and not short_object_fallback_attempted
                ):
                    short_object_fallback_attempted = True
                    print(
                        "⚠️ 短篇整数组连续语义失败，改为逐个生成4个事件对象并统一校验。",
                        flush=True,
                    )
                    assembled = _generate_short_event_clusters_one_by_one(
                        global_seed_plan,
                        total_chapters=total_chapters,
                        final_start=final_start,
                        final_end=final_end,
                    )
                    if assembled:
                        print("✅ 短篇4个事件对象已逐个生成并通过统一语义校验。", flush=True)
                        return assembled
                    print("⚠️ 逐对象事件簇仍未通过，继续尝试完整数组生成。", flush=True)
                print(
                    f"⚠️ Qwen 事件簇第 {attempt}/{max_attempts} 次未通过因果/爽点合同："
                    f"{semantic_failures[0]}",
                    flush=True,
                )
                messages[-1]["content"] = (
                    user_prompt
                    + "\n\n上一次输出虽可解析，但存在以下硬问题，必须全部修正后重新输出完整 JSON 数组：\n- "
                    + "\n- ".join(semantic_failures)
                    + "\n只输出合法 JSON 数组。"
                )
                continue
            if attempt > 1:
                print(f"✅ 事件簇 JSON 在第 {attempt} 次 Qwen 调用解析成功。", flush=True)
            return clusters
        parse_failure_count += 1
        snippet = re.sub(r"\s+", " ", str(raw or ""))[:240]
        print(
            f"⚠️ Qwen 事件簇响应第 {attempt}/{max_attempts} 次无法解析为 JSON 数组：{snippet}",
            flush=True,
        )
        if (
            expected_short_spans
            and parse_failure_count >= 2
            and not short_object_fallback_attempted
        ):
            short_object_fallback_attempted = True
            print(
                "⚠️ 短篇整数组连续截断，改为逐个生成4个事件对象并统一校验。",
                flush=True,
            )
            assembled = _generate_short_event_clusters_one_by_one(
                global_seed_plan,
                total_chapters=total_chapters,
                final_start=final_start,
                final_end=final_end,
            )
            if assembled:
                print("✅ 短篇4个事件对象已逐个生成并通过统一语义校验。", flush=True)
                return assembled
            print("⚠️ 逐对象事件簇仍未通过，继续尝试完整数组生成。", flush=True)
        messages[-1]["content"] = (
            user_prompt
            + "\n\n上一次输出无法被 JSON 解析。请严格只输出合法 JSON 数组，所有字符串使用双引号，"
              "不得使用 Markdown 代码围栏、注释、前言或后记。"
        )
    return []


def _extract_json_object_maybe(text: Any) -> Dict[str, Any]:
    if not text:
        return {}
    raw = str(text).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _short_event_object_specs(
    *, total_chapters: int, final_start: int, final_end: int
) -> List[Dict[str, Any]]:
    """Return the fixed four-object skeleton used by short-run Qwen generation."""
    if not (5 <= total_chapters <= 12) or final_start <= 3 or final_end != total_chapters:
        return []
    return [
        {
            "cluster_id": "EC01",
            "arc_id": "A01",
            "chapter_span": [1, 1],
            "is_final_arc": False,
            "role": "上一世死亡",
            "role_contract": (
                "只写上一世最后一次事业打击、公开受辱、不可逆损失和明确死亡；"
                "绝不进入重生或今生，this_life_revenge只写‘本簇不进入今生’。"
                "chapter_milestones只有第1章且result必须出现‘死亡/身亡/生命结束’。"
                "演员对手只能施压或嘲讽，淘汰/角色决定必须由不命名的选角导演或片方负责人作出。"
            ),
        },
        {
            "cluster_id": "EC02",
            "arc_id": "A02",
            "chapter_span": [2, 2],
            "is_final_arc": False,
            "role": "重生确认与首次部署",
            "role_contract": (
                "只写主角醒来确认重生，并在同一天完成一个可见的首次部署；"
                "不得进入正式试镜、换角或终局反杀，不得向任何人自曝重生。"
            ),
        },
        {
            "cluster_id": "EC03",
            "arc_id": "A03",
            "chapter_span": [3, final_start - 1],
            "is_final_arc": False,
            "role": "首次今生资源反杀",
            "role_contract": (
                "逐章推进当前时间线的试镜、合同或角色资源反杀；每章主角主动行动，"
                "并同时获得现实收益、让固定对手当场失去利益或干预权。正式角色只能授予一次。"
            ),
        },
        {
            "cluster_id": "EC04",
            "arc_id": "A04",
            "chapter_span": [final_start, final_end],
            "is_final_arc": True,
            "role": "终局升级清算",
            "role_contract": (
                "逐章完成比前簇更高层且不同种类的职业清算；不得重复授予同一角色。"
                "终局必须让固定对手失去现实职业利益，并让主角实际签下长期演员合约、多部影片演员合约或制片公司长期合作合约；签约权或机会不算。"
                "若双方是演员，不得更换编剧/导演团队、调动人员、写公司部门职位或虚构项目管理权；"
                "对手应失去片方优先合作、演员项目资格或续作谈判机会。"
            ),
        },
    ]


def _short_event_object_shape_failures(
    cluster: Dict[str, Any], spec: Dict[str, Any]
) -> List[str]:
    failures: List[str] = []
    if not cluster:
        return ["没有输出可解析的JSON对象"]
    milestones = cluster.get("chapter_milestones")
    actual_chapters: List[int] = []
    complete = isinstance(milestones, list) and bool(milestones)
    for milestone in milestones if isinstance(milestones, list) else []:
        if not isinstance(milestone, dict):
            complete = False
            continue
        try:
            actual_chapters.append(int(milestone.get("chapter")))
        except (TypeError, ValueError):
            complete = False
        if not all(str(milestone.get(key) or "").strip() for key in ("action", "opponent_reaction", "result")):
            complete = False
    start, end = spec["chapter_span"]
    expected_chapters = list(range(int(start), int(end) + 1))
    if not complete or actual_chapters != expected_chapters:
        failures.append(f"chapter_milestones必须逐章覆盖{expected_chapters}且每项字段完整")
    if spec["cluster_id"] == "EC01":
        cast = cluster.get("canonical_cast")
        alignments = {
            str(member.get("alignment") or "").casefold()
            for member in cast if isinstance(cast, list) and isinstance(member, dict)
        }
        if not {"protagonist", "opponent"}.issubset(alignments):
            failures.append("EC01必须输出蓝图中的完整固定角色表，至少含protagonist与opponent")
    return failures


def _generate_one_short_event_object(
    global_seed_plan: str,
    *,
    spec: Dict[str, Any],
    other_clusters: List[Dict[str, Any]],
    semantic_failures: Optional[List[str]] = None,
) -> Dict[str, Any]:
    seed_cast = _canonical_cast_from_seed_plan(global_seed_plan)
    protagonist_name = next(
        (member["name"] for member in seed_cast if member.get("alignment") == "protagonist"),
        "主角",
    )
    opponent_name = next(
        (member["name"] for member in seed_cast if member.get("alignment") == "opponent"),
        "固定对手",
    )
    prior_results = [
        {
            "cluster_id": cluster.get("cluster_id"),
            "chapter": milestone.get("chapter"),
            "result": milestone.get("result"),
        }
        for cluster in other_clusters
        for milestone in (cluster.get("chapter_milestones") or [])
        if isinstance(milestone, dict)
    ]
    fixed_identity = {
        "cluster_id": spec["cluster_id"],
        "arc_id": spec["arc_id"],
        "is_final_arc": spec["is_final_arc"],
        "chapter_span": spec["chapter_span"],
        "canonical_cast": "输出[]；程序从蓝图锁定角色表",
    }
    failure_block = ""
    if semantic_failures:
        failure_block = "\n【上次对象的硬问题，必须全部修正】\n- " + "\n- ".join(semantic_failures)
    prompt = f"""
下面是全书蓝图：
{global_seed_plan}

你正在单独生成四对象短篇规划中的 {spec['cluster_id']}（{spec['role']}）。
固定结构身份：{json.dumps(fixed_identity, ensure_ascii=False)}
本对象职责：{spec['role_contract']}

其他对象已经生效或预定的逐章结果如下；不得重复结算同一角色或收益：
{json.dumps(prior_results, ensure_ascii=False)}
{failure_block}

只输出一个完整合法JSON对象，不要数组、代码围栏、前言或解释。对象必须包含：
cluster_id、name、arc_id、is_final_arc、chapter_span、canonical_cast、main_opponent、
escalation_level、prev_life_tragedy、info_gap_from_prev_life、this_life_revenge、core_payoff、
cluster_outcome、summary、final_goal、final_payoff、notes、chapter_milestones。

硬约束：
1. 只使用蓝图固定英文姓名，不新增命名人物，不更改身份；canonical_cast统一写[]，程序从蓝图锁定角色表。
2. chapter_milestones逐章覆盖{list(range(spec['chapter_span'][0], spec['chapter_span'][1] + 1))}，每项只含chapter、action、opponent_reaction、result。
3. 第3章起每章result必须直接使用双分句格式：“{protagonist_name}获得具体职业收益；{opponent_name}失去具体职业利益。”职业利益只能是角色、合约、职位、资格、项目权限或合作机会。
4. 不得向任何人自曝重生；不使用贿赂指控、过往操纵记录、人脉间接证据、私人邮件、秘密录音、偷拍视频、隐藏文件、匿名爆料或媒体搜证。
4a. 盟友或他人不得临时提供来源模糊的资料、材料、文件、记录或证据替主角解决冲突。
4b. 不得通过盟友帮助把旧记录、内部资料或证据提交公司审查；“本簇不进入今生”只允许EC01使用。
5. 冲突只靠当前可见的表演、合同条款、公开规则和对手当场动作；决定由当前场景中有权的选角、导演、制片或片方人员作出。
6. 前世信息差只能是脑中记忆，不能成为今生物证。正式角色只能授予一次，后续收益必须升级为不同合作、资格、合约权或自主权。
7. core_payoff与cluster_outcome写清双方已经生效的现实得失；终局另在final_goal、final_payoff写清最终落锤，非终局字段可写空字符串。
8. 经纪人不得宣布淘汰或角色归属；不用过往争议、曾经违规、行为模式、发布会、媒体追问、舆论或公众信任清算。
9. 第3章起对手每章必须失去角色、合约、职位、资格、项目权限、合作机会等职业利益；尴尬、沉默、名誉受损不算损失。
10. 核心角色授予章必须有真实试戏/表演/台词演绎；终局不得使用首映礼、媒体采访、记者追问或揭露当年操作。
11. 固定演员不得更换编剧/导演/制作团队、调动公司人员或决定公司人事；演员对手不得被调往部门、剥夺公司职位、参加项目竞标，也不能凭空拥有剧本参与权、剪辑权或幕后/项目顾问职位，只能失去角色、演员合约、项目合作资格、片方优先合作或续作谈判机会。
12. 不得先完成复试/终选，再在result中获得复试/终选资格；EC04的core_payoff、cluster_outcome、final_payoff不得重复前簇已结算的核心角色归属。
13. 演员/影后对手不能宣布取消资格、淘汰、换角或把角色交给别人；不得靠“过去拒绝合作、过去一年阻碍新人、质疑过往不当操作、影响公司口碑”等概括性旧账清算。
14. 若人工限制包含不要投资，不得让投资人、投资方或资本施压参与推进；终章必须实际签下长期演员合约、多部影片演员合约或制片公司长期合作合约，签约权/机会不算。
15. 核心角色授予章不得给对手补偿配角；第5-6章合作/谈判损失必须由片方、制片公司或制片人当场宣布取消/终止/不再续约。第5章先建立对手现有优先合作或续作谈判资源但不得提前让她失去，本章另损失一项当前项目利益，终章才剥夺前述资源；终章不得用颁奖晚宴、庆功宴、红毯或酒会。
16. 主角演员只能谈判和签署自己的合约，不能要求重审、取消对手旧合同或把对手剔出系列片/项目；对手失去核心角色后不得无解释继续留在同一剧组拍摄/排练，也不得调整日程去避开她。
17. 第1章result正文必须明确具体死亡方式，不能只在对象名写“死亡”；不得出示对手私下接触其他剧组、违规或操控的证据。
18. 每个字符串尽量短于80个汉字，summary短于120个汉字。
""".strip()
    messages = [
        {
            "role": "system",
            "content": "你逐个设计快节奏高情绪重生爽文事件对象，并严格只输出单个JSON对象。",
        },
        {"role": "user", "content": prompt},
    ]
    last_failures = list(semantic_failures or [])
    for attempt in range(1, 4):
        raw = legacy_v2.call_qianwen_api(
            messages,
            temperature=0.5 if attempt == 1 else 0.32,
            top_p=0.74,
        )
        cluster = _extract_json_object_maybe(raw)
        if cluster:
            cluster.update({
                "cluster_id": spec["cluster_id"],
                "arc_id": spec["arc_id"],
                "is_final_arc": spec["is_final_arc"],
                "chapter_span": list(spec["chapter_span"]),
            })
            if seed_cast:
                cluster["canonical_cast"] = json.loads(json.dumps(seed_cast, ensure_ascii=False))
        shape_failures = _short_event_object_shape_failures(cluster, spec)
        if not shape_failures:
            return cluster
        last_failures = shape_failures
        print(
            f"⚠️ {spec['cluster_id']} 单对象第 {attempt}/3 次结构不合格：{shape_failures[0]}",
            flush=True,
        )
        messages[-1]["content"] = (
            prompt
            + "\n\n上次对象存在以下结构问题，全部修正后重新输出完整单个JSON对象：\n- "
            + "\n- ".join(last_failures)
        )
    return {}


def _generate_short_event_clusters_one_by_one(
    global_seed_plan: str,
    *,
    total_chapters: int,
    final_start: int,
    final_end: int,
) -> List[Dict[str, Any]]:
    specs = _short_event_object_specs(
        total_chapters=total_chapters,
        final_start=final_start,
        final_end=final_end,
    )
    if not specs:
        return []
    clusters: List[Dict[str, Any]] = []
    for spec in specs:
        cluster = _generate_one_short_event_object(
            global_seed_plan,
            spec=spec,
            other_clusters=clusters,
        )
        if not cluster:
            return []
        clusters.append(cluster)

    for repair_round in range(3):
        clusters = _apply_seed_cast_to_clusters(clusters, global_seed_plan)
        clusters = _normalize_cluster_names_from_seed_plan(clusters, global_seed_plan)
        clusters = _normalize_event_cluster_shape(clusters, global_seed_plan)
        failures = _event_cluster_semantic_failures(
            clusters, total_chapters=total_chapters
        )
        if not failures:
            return clusters
        print(
            f"⚠️ 逐对象事件簇统一校验第 {repair_round + 1}/3 轮未通过：{failures[0]}",
            flush=True,
        )
        if _failures_target_only_opening_cluster(clusters, failures):
            repaired = _repair_opening_cluster_only(
                clusters,
                global_seed_plan=global_seed_plan,
                total_chapters=total_chapters,
                semantic_failures=failures,
            )
            if repaired:
                return repaired
        target_ids = {
            spec["cluster_id"]
            for spec in specs
            if any(failure.startswith(spec["cluster_id"]) for failure in failures)
        }
        if any(failure.startswith("chapter_milestones 在多章重复结算") for failure in failures):
            target_ids.add("EC04")
        if not target_ids:
            return []
        for target_id in sorted(target_ids):
            idx = next(i for i, spec in enumerate(specs) if spec["cluster_id"] == target_id)
            relevant_failures = [
                failure for failure in failures
                if failure.startswith(target_id)
                or failure.startswith("chapter_milestones 在多章重复结算")
            ]
            replacement = _generate_one_short_event_object(
                global_seed_plan,
                spec=specs[idx],
                other_clusters=[cluster for i, cluster in enumerate(clusters) if i != idx],
                semantic_failures=relevant_failures,
            )
            if not replacement:
                return []
            clusters[idx] = replacement
    return []


def _repair_opening_cluster_only(
    clusters: List[Dict[str, Any]],
    *,
    global_seed_plan: str,
    total_chapters: int,
    semantic_failures: List[str],
) -> List[Dict[str, Any]]:
    """Rewrite only EC01 when the parsed array's sole defects are in chapter 1."""
    opening_idx = next(
        (idx for idx, cluster in enumerate(clusters) if cluster.get("chapter_span") == [1, 1]),
        None,
    )
    if opening_idx is None:
        return []
    current = clusters[opening_idx]
    fixed_identity = {
        "cluster_id": current.get("cluster_id") or "EC01",
        "arc_id": current.get("arc_id") or "A01",
        "chapter_span": [1, 1],
        "canonical_cast": current.get("canonical_cast") or [],
    }
    base_prompt = f"""
下面是全书蓝图：
{global_seed_plan}

当前第1章事件簇对象：
{json.dumps(current, ensure_ascii=False)}

该对象存在以下硬问题：
- {chr(10).join(semantic_failures)}

请只重写这一个第1章事件簇，并只输出单个合法 JSON 对象，不要数组、代码围栏或解释。
固定身份字段必须逐字照抄：
{json.dumps(fixed_identity, ensure_ascii=False)}

必须保留事件簇完整字段，并满足：
1. 第1章只写上一世最后一次事业打击、公开受辱、不可逆损失和明确死亡，绝不进入重生或今生反击。
2. chapter_milestones 必须且只能有一项，chapter=1；action 场景化写主角最后争取，opponent_reaction 写固定对手当场压制，result 必须明确写主角死亡或生命结束。
3. 死亡必须从已有职业打击自然延伸，并明确写出与蓝图一致的具体死因；不新增神秘人、幕后组织、匿名消息、决定性录音/文件或死后物证钩子。
4. canonical_cast 姓名、身份、阵营不改；main_opponent 只能使用其中一个固定 opponent 姓名。
5. this_life_revenge只写“本簇不进入今生”；任何字段都不得写重生后的计划、部署或向他人透露重生。
6. 若固定对手是演员/影后，她只能施压、嘲讽或争抢；淘汰和角色归属必须由不命名的选角导演、导演或片方负责人决定。
7. 每个字符串尽量短于80个汉字，summary短于120个汉字。
""".strip()
    messages = [
        {
            "role": "system",
            "content": "你只修复商业重生爽文的第1章上一世死亡事件簇，并严格输出单个 JSON 对象。",
        },
        {"role": "user", "content": base_prompt},
    ]
    for repair_attempt in range(1, 4):
        raw = legacy_v2.call_qianwen_api(
            messages,
            temperature=0.4 if repair_attempt == 1 else 0.28,
            top_p=0.7,
        )
        repaired_opening = _extract_json_object_maybe(raw)
        if not repaired_opening:
            messages[-1]["content"] = base_prompt + "\n\n上次无法解析，只输出完整合法的单个 JSON 对象。"
            continue
        repaired_opening.update(fixed_identity)
        normalized = _normalize_cluster_names_from_seed_plan(
            [repaired_opening], global_seed_plan
        )
        normalized = _normalize_event_cluster_shape(normalized, global_seed_plan)
        candidate = list(clusters)
        candidate[opening_idx] = normalized[0]
        remaining = _event_cluster_semantic_failures(
            candidate, total_chapters=total_chapters
        )
        if not remaining:
            return candidate
        if any(not failure.startswith(str(fixed_identity["cluster_id"])) for failure in remaining):
            return []
        messages[-1]["content"] = (
            base_prompt
            + "\n\n上次对象仍有以下问题，全部修正后重写单个完整 JSON 对象：\n- "
            + "\n- ".join(remaining)
        )
    return []


def _repair_final_cluster_only(
    clusters: List[Dict[str, Any]],
    *,
    global_seed_plan: str,
    total_chapters: int,
    semantic_failures: List[str],
) -> List[Dict[str, Any]]:
    """Ask Qwen to rewrite only the failed final object, preserving prior clusters."""
    final_idx = next(
        (idx for idx, cluster in enumerate(clusters) if bool(cluster.get("is_final_arc"))),
        None,
    )
    if final_idx is None:
        return []
    current_final = clusters[final_idx]
    span = current_final.get("chapter_span") or []
    try:
        final_start, final_end = int(span[0]), int(span[1])
    except (TypeError, ValueError, IndexError):
        return []

    canonical_cast = current_final.get("canonical_cast") or next(
        (cluster.get("canonical_cast") for cluster in clusters if cluster.get("canonical_cast")),
        [],
    )
    protagonist_name = next(
        (
            str(member.get("name") or "")
            for member in canonical_cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "protagonist"
        ),
        "主角",
    )
    opponent_name = next(
        (
            str(member.get("name") or "")
            for member in canonical_cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "opponent"
        ),
        "固定对手",
    )
    prior_results = [
        {
            "chapter": milestone.get("chapter"),
            "result": milestone.get("result"),
        }
        for cluster in clusters[:final_idx]
        for milestone in (cluster.get("chapter_milestones") or [])
        if isinstance(milestone, dict)
    ]
    fixed_identity = {
        "cluster_id": current_final.get("cluster_id") or "EC_FINAL",
        "arc_id": current_final.get("arc_id") or "A_FINAL",
        "is_final_arc": True,
        "chapter_span": [final_start, final_end],
        "canonical_cast": canonical_cast,
    }
    base_prompt = f"""
下面是一部重生复仇爽文的全书蓝图：
{global_seed_plan}

已有前三簇已经通过校验，绝对不要重写。它们已经生效的逐章结果如下：
{json.dumps(prior_results, ensure_ascii=False)}

当前终局对象存在硬问题：
- {chr(10).join(semantic_failures)}

请只重写最后一个终局事件簇，并且只输出一个合法 JSON 对象，不要数组、代码围栏或解释。
固定身份字段必须逐字照抄：
{json.dumps(fixed_identity, ensure_ascii=False)}

对象必须包含：cluster_id、name、arc_id、is_final_arc、chapter_span、canonical_cast、
main_opponent、escalation_level、prev_life_tragedy、info_gap_from_prev_life、
this_life_revenge、core_payoff、cluster_outcome、summary、final_goal、final_payoff、notes、chapter_milestones。
chapter_milestones 必须逐章覆盖 {list(range(final_start, final_end + 1))}，每项只含 chapter、action、
opponent_reaction、result。每章都要有主角主动行动和已经生效的结果。

硬约束：
1. 终局必须同时写清固定对手失去的一项现实职业利益，以及主角获得的一项更高层、不同于前文的现实收益。
2. 不得重复结算前文已经正式改变过的同一主演角色；应升级到不同合作、职位、资格、合约控制权或自主权。
3. 只用 canonical_cast 中的固定英文姓名，不新增命名人物，不更换人物身份。
4. 不使用私人邮件、秘密录音、隐藏文件、匿名爆料、媒体搜证或前世携带物证。
5. 决定必须由当前场景中已有且有权的选角、制片或片方人员作出，收益和损失要符合其权限。
6. 不用过往争议、曾经违规、行为模式、发布会、媒体追问、舆论或公众信任变化清算；每章对手损失必须是职业利益。
7. 每章result直接采用双分句：“{protagonist_name}获得具体职业收益；{opponent_name}失去具体职业利益。”职业利益必须是合约、职位、资格、项目权限或合作机会，不能重复前文角色归属。
8. 若固定角色是演员，主角不得更换编剧/导演/制作团队或调动人员；对手不得被调往部门、剥夺公司职位、参加项目竞标或失去未建立的项目控制权，只能失去演员合约、项目合作资格、片方优先合作或续作谈判机会。
9. core_payoff、cluster_outcome、final_payoff只能总结本终局新增的得失，不得再写前簇已经完成的角色归属。
10. 演员/影后对手不能宣布取消资格、淘汰、换角或把角色交给别人；不得靠“过去拒绝合作、过去一年阻碍新人、质疑过往不当操作、影响公司口碑”等概括性旧账清算。
11. 若人工限制包含不要投资，不得让投资人、投资方或资本施压参与推进；终章result必须写实际签下长期演员合约、多部影片演员合约或制片公司长期合作合约，签约权/机会不算。
12. 第5-6章合作/谈判损失必须由片方、制片公司或制片人当场宣布取消/终止/不再续约；前文必须已经建立对手的优先合作或续作谈判资源。终章不得使用颁奖晚宴、庆功宴、红毯或酒会。
13. 每个字符串尽量短于80个汉字，summary短于120个汉字。
""".strip()
    messages = [
        {
            "role": "system",
            "content": "你只修复商业重生爽文的最后一个事件簇，并严格输出单个 JSON 对象。",
        },
        {"role": "user", "content": base_prompt},
    ]
    last_failures = list(semantic_failures)
    for repair_attempt in range(1, 4):
        raw = legacy_v2.call_qianwen_api(
            messages,
            temperature=0.42 if repair_attempt == 1 else 0.3,
            top_p=0.72,
        )
        repaired_final = _extract_json_object_maybe(raw)
        if not repaired_final:
            print(
                f"⚠️ 终局单对象修复第 {repair_attempt}/3 次无法解析。",
                flush=True,
            )
            messages[-1]["content"] = base_prompt + "\n\n上次无法解析。只输出完整合法的单个 JSON 对象。"
            continue

        repaired_final.update(fixed_identity)
        normalized = _normalize_event_cluster_shape([repaired_final], global_seed_plan)
        normalized = _normalize_cluster_names_from_seed_plan(normalized, global_seed_plan)
        candidate = list(clusters)
        candidate[final_idx] = normalized[0]
        last_failures = _event_cluster_semantic_failures(
            candidate, total_chapters=total_chapters
        )
        if not last_failures:
            return candidate
        print(
            f"⚠️ 终局单对象修复第 {repair_attempt}/3 次仍未通过：{last_failures[0]}",
            flush=True,
        )
        messages[-1]["content"] = (
            base_prompt
            + "\n\n上次对象仍有以下问题，全部修正后重新输出一个完整 JSON 对象：\n- "
            + "\n- ".join(last_failures)
        )
    return []


def _synthesize_final_arc_cluster(
    global_seed_plan: str,
    *,
    final_start: int,
    final_end: int,
    existing_clusters: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    当模型未按要求给出终局簇时，二次调用模型只生成一个终局簇对象。
    终局目标由模型根据 global_seed_plan 自行设定（不硬编码）。
    """
    # 压缩已有簇信息，作为“不得天降”的约束背景
    lines: List[str] = []
    for c in existing_clusters[:35]:
        cid = str(c.get("cluster_id", "") or "")
        name = str(c.get("name", "") or "")
        opp = str(c.get("main_opponent", "") or "")
        payoff = str(c.get("core_payoff", "") or "")
        span = c.get("chapter_span") or []
        lines.append(f"- {cid}《{name}》 span={span} opp={opp} payoff={payoff}")
    clusters_brief = "\n".join(lines[:25])

    prompt = f"""
下面是全书最大复仇主线蓝图：
{global_seed_plan}

下面是已经生成的前置事件簇（摘要），终局不得引入“全新Boss/全新世界观/天降决定性证据”，只能把前面积累的优势集中落锤：
{clusters_brief}

请只输出 1 个 JSON 对象（不是数组），表示“终局大情节族（final arc）”，字段要求：
- cluster_id: 例如 "EC_FINAL"
- name: 终局标题（中文）
- arc_id: 例如 "A05"（可自定）
- is_final_arc: true
- chapter_span: [{final_start}, {final_end}]（必须严格一致）
- final_goal: 1 句，明确最终清算目标（具体，不要空泛）
- final_payoff: 1-2 句，明确如何兑现（公众/法律/资本/行业等落锤方式）
- core_payoff / main_opponent / escalation_level / prev_life_tragedy / info_gap_from_prev_life / this_life_revenge / cluster_outcome / summary / notes：按 V2 事件簇字段风格补齐

重要限制：
- 禁止写成“调查推理追线索小说”，终局推进依然以“记忆信息差 + 现实筹码落锤”驱动。
- 禁止出现：匿名邮件突然给全部真相、加密邮箱弹出决定性附件、陌生人突然递关键材料。
- 前世记忆不是可播放的录音或可提交的文件；若使用材料，必须由主角在当前时间线提前布置并让对手亲自留下。
- final_payoff 必须同时明确对手失去的现实利益与主角拿回的现实收益，不能只写舆论崩塌。
- 只输出 JSON 对象本身，不要解释。
""".strip()
    messages = [
        {
            "role": "system",
            "content": "你是擅长快节奏、高情绪、强回收的商业重生爽文结构策划，只生成终局事件簇 JSON。",
        },
        {"role": "user", "content": prompt},
    ]
    raw = legacy_v2.call_qianwen_api(messages, temperature=0.75, top_p=0.85)
    if raw:
        txt = str(raw).strip()
        start = txt.find("{")
        end = txt.rfind("}")
        if start != -1 and end != -1 and end > start:
            txt = txt[start : end + 1]
        try:
            obj = json.loads(txt)
            if isinstance(obj, dict):
                obj["is_final_arc"] = True
                obj["chapter_span"] = [int(final_start), int(final_end)]
                return obj
        except Exception:
            pass

    # 极端兜底（仍不硬编码终局目标，只给占位，后续可手工/再跑生成）
    return {
        "cluster_id": "EC_FINAL",
        "name": "终局清算（占位）",
        "arc_id": "A05",
        "is_final_arc": True,
        "chapter_span": [int(final_start), int(final_end)],
        "core_payoff": "终局大清算落锤（占位）",
        "final_goal": "终局清算目标（占位，建议重跑生成）",
        "final_payoff": "通过公众+法律+资本多线落锤完成清算（占位）",
        "main_opponent": "终局对手（占位）",
        "escalation_level": 3,
        "prev_life_tragedy": "上一世终局失败前提（占位）",
        "info_gap_from_prev_life": "上一世留下的信息差（占位）",
        "this_life_revenge": "今生终局反击方式（占位）",
        "cluster_outcome": "终局后果（占位）",
        "summary": "终局推进（占位）",
        "notes": ["需要重跑以生成更具体终局目标与兑现方式"],
    }


def _ensure_final_arc_cluster(
    clusters: List[Dict[str, Any]],
    global_seed_plan: str,
    *,
    final_arc_len: int,
    total_chapters: int = 100,
) -> List[Dict[str, Any]]:
    """
    强制保证“终局大情节族”存在且覆盖最后 N 章，并自动修正前置簇的 chapter_span 重叠。
    """
    max_final_arc_len = max(1, total_chapters - 3) if 5 <= total_chapters <= 12 else max(1, total_chapters - 1)
    final_arc_len = max(1, min(int(final_arc_len), max_final_arc_len))
    final_start = total_chapters - final_arc_len + 1
    final_end = total_chapters

    # 1) 查找现有终局簇
    final_idx = None
    for i, c in enumerate(clusters):
        if bool(c.get("is_final_arc")):
            final_idx = i
            break

    if final_idx is None:
        # 允许通过 id/name 兜底识别
        for i, c in enumerate(clusters):
            cid = str(c.get("cluster_id", "") or "").upper()
            name = str(c.get("name", "") or "")
            if "FINAL" in cid or "终局" in name:
                final_idx = i
                c["is_final_arc"] = True
                break

    if final_idx is None:
        final_cluster = _synthesize_final_arc_cluster(
            global_seed_plan,
            final_start=final_start,
            final_end=final_end,
            existing_clusters=clusters,
        )
        clusters = list(clusters) + [final_cluster]
        final_idx = len(clusters) - 1
    else:
        clusters[final_idx]["is_final_arc"] = True
        clusters[final_idx]["chapter_span"] = [int(final_start), int(final_end)]

    # 2) 终局簇必须含 final_goal/final_payoff（由模型给；缺失就补占位提示重跑）
    fc = clusters[final_idx]
    if not str(fc.get("final_goal", "") or "").strip():
        fc["final_goal"] = "终局清算目标（缺失，建议重跑事件簇生成以让模型补齐）"
    if not str(fc.get("final_payoff", "") or "").strip():
        fc["final_payoff"] = "终局兑现方式（缺失，建议重跑事件簇生成以让模型补齐）"

    # 3) 修正其他簇：不允许覆盖到终局区间
    for i, c in enumerate(clusters):
        if i == final_idx:
            continue
        span = c.get("chapter_span") or c.get("chapterRange") or c.get("chapters")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            continue
        try:
            s, e = int(span[0]), int(span[1])
        except Exception:
            continue
        if e >= final_start:
            e2 = final_start - 1
            if e2 < s:
                # 完全落在终局区间内的簇，直接压缩成 1 章占位（后续可人工重跑）
                c["chapter_span"] = [max(1, final_start - 2), max(1, final_start - 2)]
            else:
                c["chapter_span"] = [s, e2]

    # 4) 把终局簇放在最后，便于阅读/后续处理
    final_cluster = clusters.pop(final_idx)
    clusters.append(final_cluster)
    return clusters


def _limit_clusters_to_run(clusters: List[Dict[str, Any]], total_chapters: int) -> List[Dict[str, Any]]:
    """Produce one continuous, non-overlapping cluster cover for this run."""
    valid: List[Dict[str, Any]] = []
    for cluster in clusters:
        span = cluster.get("chapter_span")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            continue
        try:
            start, end = int(span[0]), int(span[1])
        except (TypeError, ValueError):
            continue
        start, end = max(1, start), min(total_chapters, end)
        if start > end:
            continue
        cluster["chapter_span"] = [start, end]
        valid.append(cluster)

    final = next((c for c in valid if bool(c.get("is_final_arc"))), None)
    if final is None:
        final = valid[-1] if valid else None
    final_start = int((final or {}).get("chapter_span", [total_chapters, total_chapters])[0])
    result: List[Dict[str, Any]] = []
    next_chapter = 1
    for cluster in sorted((c for c in valid if c is not final), key=lambda c: int(c["chapter_span"][0])):
        if next_chapter >= final_start:
            break
        original_end = int(cluster["chapter_span"][1])
        end = min(final_start - 1, max(next_chapter, original_end))
        cluster["chapter_span"] = [next_chapter, end]
        result.append(cluster)
        next_chapter = end + 1
    if next_chapter < final_start:
        if result:
            result[-1]["chapter_span"][1] = final_start - 1
        elif final is not None:
            final["chapter_span"][0] = 1
    if final is not None:
        final["chapter_span"] = [max(next_chapter, final_start), total_chapters]
        if final["chapter_span"][0] <= total_chapters:
            result.append(final)

    # A model planning for a long novel often returns many event clusters. Merely
    # squeezing those spans into a 4-12 chapter test turns every chapter into a
    # standalone arc and makes chapter 2's awakening look like a finale. For a
    # short run, preserve chapter 1 and the final arc, but combine all intervening
    # conflicts into one continuous escalation arc.
    if total_chapters <= 12 and len(result) >= 4:
        opening = result[0] if result[0].get("chapter_span") == [1, 1] else None
        ending = result[-1] if bool(result[-1].get("is_final_arc")) else None
        middle_start = 1 if opening is not None else 0
        middle_end = len(result) - 1 if ending is not None else len(result)
        middle = result[middle_start:middle_end]
        if len(middle) > 1:
            merged = dict(middle[0])
            merged["chapter_span"] = [
                int(middle[0]["chapter_span"][0]),
                int(middle[-1]["chapter_span"][1]),
            ]
            names = [str(c.get("name") or "").strip() for c in middle if str(c.get("name") or "").strip()]
            merged["name"] = "连环反击：" + "→".join(names[:3])
            active_opponents = [
                str(c.get("main_opponent") or "").strip()
                for c in middle
                if str(c.get("main_opponent") or "").strip().casefold()
                not in {"", "无", "暂无", "none", "不出场"}
            ]
            if active_opponents:
                merged["main_opponent"] = active_opponents[0]
            for field in (
                "core_payoff", "prev_life_tragedy", "info_gap_from_prev_life",
                "this_life_revenge", "cluster_outcome", "summary",
            ):
                values = [str(c.get(field) or "").strip() for c in middle if str(c.get(field) or "").strip()]
                merged[field] = "；".join(dict.fromkeys(values))
            cast_by_name: Dict[str, Dict[str, Any]] = {}
            for cluster in middle:
                for member in cluster.get("canonical_cast") or []:
                    if isinstance(member, dict) and str(member.get("name") or "").strip():
                        cast_by_name.setdefault(str(member["name"]).strip(), member)
            if cast_by_name:
                merged["canonical_cast"] = list(cast_by_name.values())
            merged_milestones = [
                milestone
                for cluster in middle
                for milestone in (cluster.get("chapter_milestones") or [])
                if isinstance(milestone, dict)
            ]
            if merged_milestones:
                merged["chapter_milestones"] = sorted(
                    merged_milestones,
                    key=lambda item: int(item.get("chapter") or 0),
                )
            merged["notes"] = [
                "本簇由短篇测试中的连续冲突合并而成；章节之间必须直接承接，不得每章重新开局。",
                "第2章仍只负责重生确认；试镜、合同和会议反卡从后续章节依次兑现。",
            ]
            result = ([opening] if opening is not None else []) + [merged] + ([ending] if ending is not None else [])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 事件簇生成（支持人工输入题材/背景/主角名）")
    parser.add_argument("--project-config", type=str, default=None)
    parser.add_argument("--generation-config", type=str, default=None)
    parser.add_argument("--theme", type=str, default=DEFAULT_THEME)
    parser.add_argument("--background", type=str, default=DEFAULT_BACKGROUND)
    parser.add_argument(
        "--protagonists",
        type=str,
        default=protagonists_arg(),
        help="主角名字约束（可多个，不要求区分女主/男主；支持逗号/顿号/分号/换行分隔）",
    )
    # 兼容旧参数：仍可传，但交互默认不再询问
    parser.add_argument("--heroine-name", type=str, default=MAIN_PROTAGONIST, help=argparse.SUPPRESS)
    parser.add_argument("--hero-name", type=str, default="", help=argparse.SUPPRESS)
    parser.add_argument("--extra-constraints", type=str, default="")
    parser.add_argument("--extra-constraints-file", type=str, default=None)
    parser.add_argument(
        "--final-arc-len",
        type=int,
        default=8,
        help="终局大情节族覆盖章节数（建议 5-12，默认 8）",
    )
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument(
        "--reuse-seed-plan",
        action="store_true",
        help="Reuse the existing global_seed_plan_v2.txt in V2_OUTPUT_DIR.",
    )
    parser.add_argument("--total-chapters", type=int, default=100)
    args = parser.parse_args()

    cfg: Dict[str, str] = {
        "theme": args.theme,
        "background": args.background,
        "protagonists": args.protagonists,
        "heroine_name": args.heroine_name,
        "hero_name": args.hero_name,
        "extra_constraints": args.extra_constraints,
        "total_chapters": str(max(2, args.total_chapters)),
    }

    if not args.non_interactive:
        cfg = _ask_interactive(cfg)

    file_constraints = _load_extra_constraints(args.extra_constraints_file)
    if file_constraints:
        merged = cfg.get("extra_constraints", "").strip()
        cfg["extra_constraints"] = f"{merged}\n{file_constraints}".strip() if merged else file_constraints

    # 将人工输入覆盖到 legacy 模块全局名，以便后续 prompt 与章节计划统一使用
    protagonists = _parse_protagonists(cfg.get("protagonists", ""))
    configure_theme_contract(
        cfg.get("theme", ""), cfg.get("background", ""), protagonists,
        cfg.get("extra_constraints", ""),
    )
    heroine, hero = _pick_legacy_leads(protagonists, cfg.get("heroine_name", MAIN_PROTAGONIST), cfg.get("hero_name", ""))
    legacy_v2.HEROINE_NAME = heroine
    legacy_v2.HERO_NAME = hero

    print("\n" + "=" * 60)
    print("事件簇生成脚本 V2（迁移版）：先人工设定题材，再生成主线与事件簇")
    print("=" * 60)
    print(f"题材: {cfg['theme']}")
    print(f"背景: {cfg['background']}")
    if protagonists:
        print(f"主角名字约束: {'、'.join(protagonists)}")
    print(f"（兼容占位）主角占位: {heroine}" + (f" | 辅助角色占位: {hero}" if hero else ""))
    if cfg.get("extra_constraints"):
        print(f"额外限制: {cfg['extra_constraints'][:200]}")

    os.makedirs(legacy_v2.OUTPUT_DIR, exist_ok=True)
    seed_path = os.path.join(legacy_v2.OUTPUT_DIR, "global_seed_plan_v2.txt")
    if args.reuse_seed_plan and os.path.isfile(seed_path):
        with open(seed_path, "r", encoding="utf-8") as f:
            global_seed_plan = f.read().strip()
        print(f"✅ 已复用最大主线蓝图：{seed_path}")
    else:
        global_seed_plan = _build_seed_plan_with_user_input(cfg)
        fixed_constraints = constraints_text()
        merged_constraints = "\n".join(
            x for x in [fixed_constraints, cfg.get("extra_constraints", "").strip()] if x
        )
        if merged_constraints:
            global_seed_plan = (
                f"{global_seed_plan}\n\n"
                f"【人工约束】题材={cfg['theme']}；背景={cfg['background']}；"
                f"额外限制={merged_constraints}"
            )
        with open(seed_path, "w", encoding="utf-8") as f:
            f.write(f"题材：{cfg['theme']}\n")
            f.write(f"背景：{cfg['background']}\n")
            if protagonists:
                f.write(f"主角名字约束：{'、'.join(protagonists)}\n")
            f.write(f"（兼容占位）主角：{heroine}\n")
            if hero:
                f.write(f"（兼容占位）辅助角色：{hero}\n")
            f.write("\n")
            f.write(f"{fixed_constraints}\n\n")
            f.write(global_seed_plan)
        print(f"✅ 最大主线蓝图已写入：{seed_path}")

    clusters = _generate_event_clusters_v2_with_final_arc(
        global_seed_plan,
        final_arc_len=args.final_arc_len,
        total_chapters=max(2, args.total_chapters),
    )
    if not clusters:
        raise RuntimeError("连续 5 次 Qwen 调用均未生成通过合同的事件簇 JSON，终止流水线。")

    clusters = _ensure_final_arc_cluster(
        clusters,
        global_seed_plan,
        final_arc_len=args.final_arc_len,
        total_chapters=max(2, args.total_chapters),
    )
    clusters = _normalize_event_cluster_shape(clusters, global_seed_plan)
    clusters = _normalize_cluster_names_from_seed_plan(clusters, global_seed_plan)
    clusters = _limit_clusters_to_run(clusters, max(2, args.total_chapters))
    if clusters and clusters[0].get("chapter_span") == [1, 1]:
        first = clusters[0]
        first["name"] = "旧阶段失败与未竟目标"
        first["core_payoff"] = "完整建立主角旧阶段的失败、代价与未竟目标，为新阶段行动提供因果动机。"
        first["cluster_outcome"] = "旧阶段以不可挽回的失败收束，主角带着明确遗憾进入新的选择机会。"
        first["summary"] = "第一章仅建立旧阶段失败，不提前展开新阶段反击。"
        first["this_life_revenge"] = "本事件簇不进入今生，只写旧阶段失败直至生命结束；重生确认与首次行动留到下一簇。"
    for c in clusters:
        # The legacy post-processor hard-codes a medical-conspiracy story.
        # V2 builds theme-aware chapter plans in the outline stage instead.
        c.pop("chapter_plan", None)
        c["user_theme"] = cfg["theme"]
        c["user_background"] = cfg["background"]
        attach_theme_contract(c)
        if protagonists:
            c["user_protagonists"] = protagonists
        c["user_heroine_name"] = heroine
        c["user_hero_name"] = hero
        if cfg.get("extra_constraints"):
            c["user_extra_constraints"] = cfg["extra_constraints"]

    ts = legacy_v2.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(legacy_v2.OUTPUT_DIR, f"event_clusters_v2_{ts}.json")
    stable_path = os.path.join(legacy_v2.OUTPUT_DIR, "event_clusters_v2.json")
    with open(backup_path, "w", encoding="utf-8") as f:
        legacy_v2.json.dump(clusters, f, ensure_ascii=False, indent=2)
    with open(stable_path, "w", encoding="utf-8") as f:
        legacy_v2.json.dump(clusters, f, ensure_ascii=False, indent=2)

    print(f"✅ 事件簇 V2 已写入：{backup_path}")
    print(f"✅ 稳定引用文件已写入：{stable_path}")


if __name__ == "__main__":
    main()

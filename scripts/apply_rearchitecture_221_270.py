import argparse
import json
import os
import tempfile
from pathlib import Path


PARTICIPANTS = {
    "EC111": ["麦珂·杰森", "苏菲亚·罗德里格斯", "昆廷·琼斯", "卡尔·霍尔特", "巴里·布鲁姆", "海关查验官"],
    "EC112": ["麦珂·杰森", "昆廷·琼斯", "卡尔·霍尔特", "奥瑞恩关联供应商", "场馆安全主管"],
    "EC113": ["麦珂·杰森", "苏菲亚·罗德里格斯", "奥瑞恩基金观察员", "候补评审", "青年乐队成员"],
    "EC114": ["麦珂·杰森", "昆廷·琼斯", "卡尔·霍尔特", "奥瑞恩关联设备商", "场馆安全主管"],
    "EC115": ["麦珂·杰森", "艾琳·沃特曼", "卡尔·霍尔特", "巡演行政联络员", "舞者与医疗人员"],
    "EC116": ["麦珂·杰森", "昆廷·琼斯", "苏菲亚·罗德里格斯", "年轻摄影师", "承运代理"],
    "EC117": ["麦珂·杰森", "苏菲亚·罗德里格斯", "卡尔·霍尔特", "工会代表", "承运计费代理"],
    "EC118": ["麦珂·杰森", "艾琳·沃特曼", "昆廷·琼斯", "巡演电影制片方", "电影节选片人"],
    "EC119": ["麦珂·杰森", "昆廷·琼斯", "卡尔·霍尔特", "声学顾问公司", "独立声学工程师"],
    "EC120": ["麦珂·杰森", "昆廷·琼斯", "卡尔·霍尔特", "场馆运营主管", "观众与安全员"],
    "EC121": ["麦珂·杰森", "苏菲亚·罗德里格斯", "卡尔·霍尔特", "奥瑞恩代理人", "场馆安全审查员"],
    "EC122": ["麦珂·杰森", "苏菲亚·罗德里格斯", "玛莎·杰森", "奥瑞恩融资承办商", "工会代表"],
    "EC123": ["麦珂·杰森", "昆廷·琼斯", "艾琳·沃特曼", "海湾影像服务商", "电影资料馆保管人"],
    "EC124": ["麦珂·杰森", "黛安娜·罗文", "艾琳·沃特曼", "档案承包商", "照片拍摄对象"],
    "EC125": ["麦珂·杰森", "瑟琳娜·凯德", "黛安娜·罗文", "节庆宣传委员会", "影像权利主管"],
    "EC126": ["麦珂·杰森", "瑟琳娜·凯德", "艾琳·沃特曼", "海湾影像服务商", "电影资料馆保管人"],
    "EC127": ["麦珂·杰森", "诺亚（舞者）", "昆廷·琼斯", "巡演电影发行方", "字幕编辑"],
    "EC128": ["麦珂·杰森", "玛莎·杰森", "瑟琳娜·凯德", "艾琳·沃特曼", "电视纪录片制片方"],
    "EC129": ["麦珂·杰森", "昆廷·琼斯", "艾琳·沃特曼", "巴里·布鲁姆", "深夜电台主持人"],
    "EC130": ["麦珂·杰森", "昆廷·琼斯", "艾琳·沃特曼", "奥瑞恩合作报业", "现场观众"],
    "EC131": ["麦珂·杰森", "苏菲亚·罗德里格斯", "艾琳·沃特曼", "奥瑞恩审计代理人", "联邦审计主管"],
    "EC132": ["麦珂·杰森", "苏菲亚·罗德里格斯", "奥瑞恩审计代理人", "联邦审计主管", "受托银行保管人"],
    "EC133": ["麦珂·杰森", "艾琳·沃特曼", "苏菲亚·罗德里格斯", "奥瑞恩新闻简报网", "报社编辑"],
    "EC134": ["麦珂·杰森", "瑟琳娜·凯德", "苏菲亚·罗德里格斯", "奥瑞恩关联贷款方", "独立理事"],
    "EC135": ["麦珂·杰森", "苏菲亚·罗德里格斯", "奥瑞恩关联技术承包商", "具名贷款核验员", "资料室管理员"],
}


def atomic_write_json(path, data):
    fd, name = tempfile.mkstemp(prefix=path.stem + "_", suffix=".json", dir=path.parent)
    os.close(fd)
    temp = Path(name)
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        json.loads(temp.read_text(encoding="utf-8"))
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("architecture", type=Path)
    parser.add_argument("synopses", type=Path)
    parser.add_argument("clusters", type=Path)
    args = parser.parse_args()

    architecture = json.loads(args.architecture.read_text(encoding="utf-8"))
    synopses = json.loads(args.synopses.read_text(encoding="utf-8"))
    synopsis_by_id = {int(item["chapter_id"]): item for item in synopses}

    for cluster in architecture:
        locations = cluster["location"].split("／")
        for index, chapter_plan in enumerate(cluster["chapters"]):
            chapter = synopsis_by_id[int(chapter_plan["id"])]
            is_first = index == 0
            location = locations[min(index, len(locations) - 1)]
            action_sequence = [
                cluster["obstacle"] if is_first else cluster["cost"],
                chapter_plan["goal"],
                cluster["cost"] if is_first else cluster["outcome"],
            ]
            detailed = "。".join([
                cluster["obstacle"], chapter_plan["goal"],
                cluster["cost"] if is_first else cluster["outcome"],
                chapter_plan["ending"],
            ]).replace("。。", "。")
            chapter.update({
                "chapter_title": chapter_plan["title"],
                "timeline_years": cluster["date"][:4],
                "timeline_start": cluster["date"],
                "timeline_end": cluster["date"],
                "chapter_role_v2": "two_chapter_setup_and_win" if is_first else "two_chapter_resolution",
                "structure_template": "MANUAL_ENTERTAINMENT_EVENT_V17",
                "chapter_goal": chapter_plan["goal"],
                "chapter_must_include": chapter_plan["must"],
                "chapter_must_not_include": [
                    "输出结构化状态字段", "非麦珂人物拥有前世记忆",
                    "把本次结果写成永久定罪或全行业绝对控制权"
                ],
                "chapter_ending": chapter_plan["ending"],
                "must_resolve_this_chapter": [] if is_first else [cluster["outcome"]],
                "detailed_synopsis": detailed,
                "scene_location": location,
                "scenes": [{
                    "sequence": 1, "location": location, "is_primary": True,
                    "temporal_mode": "current", "transition_cue": chapter_plan["goal"]
                }],
                "artifact_creates": [],
                "artifact_refs": [],
                "participants": PARTICIPANTS[cluster["cluster_id"]],
                "allowed_roles": PARTICIPANTS[cluster["cluster_id"]],
                "forbidden_roles": ["未铺垫的终极反派", "万能黑客", "突然出现的神秘证人"],
                "exact_action_sequence": action_sequence,
                "info_gap_use": "前世记忆只提供危险方向，今生结论必须由现场表演、具名人员和可核记录形成。",
                "opponent_reaction": f"{cluster['opponent']}借时间、金钱或舆论压力催促团队接受扩大权限的方案。",
                "immediate_payoff": chapter_plan["ending"] if is_first else cluster["outcome"],
                "state_changes": [],
                "state_transitions": [],
                "core_payoff": cluster["outcome"],
                "cluster_outcome": cluster["outcome"],
                "main_opponent": cluster["opponent"],
                "prev_life_tragedy": "前世同类节点让音乐、身体或资产决定权被逐步夺走。",
                "info_gap_from_prev_life": "麦珂只记得同类伤害的日期与流程，不能把记忆直接当成今生证据。",
                "this_life_revenge": chapter_plan["goal"],
                "romance_state": "重要关系保留独立判断与拒绝权。",
                "target_chinese_chars": 1200,
                "generated_by": "manual_rearchitecture",
                "compiled_by": "v17_manual_rearchitecture_221_270_20260829",
                "manual_edits": ["replace procedural carrier with music, stage, media, relationship, or major asset conflict"],
                "planning_version": "v17_manual_rearchitecture_221_270_20260829",
            })

    clusters_raw = json.loads(args.clusters.read_text(encoding="utf-8"))
    cluster_list = clusters_raw
    if isinstance(clusters_raw, dict):
        cluster_list = clusters_raw.get("event_clusters", clusters_raw.get("clusters", clusters_raw.get("data", [])))
    cluster_by_id = {item["cluster_id"]: item for item in cluster_list}
    for cluster in architecture:
        item = cluster_by_id[cluster["cluster_id"]]
        item.update({
            "name": cluster["name"],
            "chapter_span": cluster["span"],
            "timeline_years": cluster["date"][:4],
            "main_opponent": cluster["opponent"],
            "fictional_obstacle": cluster["obstacle"],
            "preemptive_avoidance": cluster["chapters"][0]["goal"],
            "bait_and_evidence": "不制造假事故；用现场表演、具名证言和本事件范围内的可核记录留下证据。",
            "comic_villain_behavior": f"{cluster['opponent']}先把风险说成无关紧要，局面反转后又急着抢功或改口，亲自暴露最在意的利益。",
            "villain_loss": cluster["outcome"],
            "protagonist_gain": cluster["outcome"],
            "relationship_change": "麦珂必须承认自己的决定会给乐手、工人、家人或合作伙伴带来真实代价，并允许他们说不。",
            "cluster_outcome": f"{cluster['outcome']}；同时承担：{cluster['cost']}。结果不外推到其他争议。",
            "next_event_hook": cluster["next_hook"],
        })

    atomic_write_json(args.synopses, synopses)
    atomic_write_json(args.clusters, clusters_raw)
    print(json.dumps({"chapters_updated": [221, 270], "count": 50, "clusters_updated": ["EC111", "EC135"], "cluster_count": 25}, ensure_ascii=False))


if __name__ == "__main__":
    main()

import argparse
import json
import os
import tempfile
from pathlib import Path


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
    parser.add_argument("synopses", type=Path)
    parser.add_argument("clusters", type=Path)
    args = parser.parse_args()

    synopses = json.loads(args.synopses.read_text(encoding="utf-8"))
    by_id = {int(item["chapter_id"]): item for item in synopses}
    c499 = by_id[499]
    c500 = by_id[500]

    c499.update({
        "chapter_title": "没有人替他写结局·上",
        "scene_location": "银湾商业法院紧急听证庭",
        "chapter_must_include": [
            "麦珂接受终局只是依法调查的开始而非私刑式全能审判",
            "保险赔付暂停、目录交割停止、调查启动",
            "法院拒绝把所有关联人一并定罪"
        ],
        "exact_action_sequence": [
            "直播后的紧急听证只处理已经形成的赔付、目录交割、医疗同意和广播权限证据",
            "法院区分已经发生的动作与尚待调查的动机",
            "法官冻结具体赔付和目录交割，把伪造与未授权行为移交调查",
            "麦珂拒绝向媒体宣布彻底胜利"
        ],
        "immediate_payoff": "保险赔付暂停、目录交割停止、扩权文件不能生效，相关调查正式启动。",
        "chapter_ending": "终局裁定只让已经发生的动作停下；最后一章回到麦珂的身体、家人与仍无法修复的关系。"
    })

    c500.update({
        "chapter_title": "没有人替他写结局·下",
        "scene_location": "河湾镇旧屋",
        "chapter_goal": "调查启动后，麦珂没有宣布所有伤害已经痊愈；身体仍需长期休养，家人与伙伴的裂痕也不能靠胜诉复原。",
        "chapter_must_include": [
            "关系无法回到无裂痕状态，身体也需要长期休养",
            "死亡利益链失去立即获利能力",
            "麦珂以活人的身份选择下一首歌"
        ],
        "exact_action_sequence": [
            "麦珂拒绝庆功宴，按医生要求回到旧屋休养",
            "家人和伙伴保留各自生活，已受伤的关系不被胜诉强行复原",
            "麦珂承认自己也曾用控制欲伤害别人",
            "他坐回旧钢琴前，以写给活着的人作为下一首歌的起点"
        ],
        "immediate_payoff": "死亡利益链失去即时获利能力；麦珂保住生命、家人与版权后，不再靠证明自己不会输来活着。",
        "chapter_ending": "麦珂按下下一首歌的第二个和弦，这一次没有人替他写结局。"
    })

    clusters = json.loads(args.clusters.read_text(encoding="utf-8"))
    cluster_list = clusters
    if isinstance(clusters, dict):
        cluster_list = clusters.get("event_clusters", clusters.get("clusters", clusters.get("data", [])))
    ec250 = next(item for item in cluster_list if item.get("cluster_id") == "EC250")
    ec250.update({
        "name": "没有人替他写结局",
        "fictional_obstacle": "直播后的紧急听证只能冻结具体利益动作并启动调查，无法用一纸判决修复麦珂的身体、家庭和所有关系。",
        "preemptive_avoidance": "麦珂接受终局只是依法调查的开始，不把直播和听证变成私刑式全能审判。",
        "protagonist_gain": "具体赔付和目录交割被停止，死亡利益链失去立即获利能力；麦珂以活人的身份选择下一首歌。",
        "relationship_change": "家人与伙伴仍然在场，却保留各自选择；道歉不强迫任何关系恢复原状。",
        "cluster_outcome": "法院只完成赔付暂停、目录交割停止和调查启动；麦珂长期休养并面对无法抹平的关系裂痕，最后在旧钢琴前决定下一首歌如何开始。",
        "next_event_hook": "故事在麦珂按下下一首歌的第二个和弦时收束。"
    })

    atomic_write_json(args.synopses, synopses)
    atomic_write_json(args.clusters, clusters)
    print({"chapters_updated": [499, 500], "cluster_updated": "EC250"})


if __name__ == "__main__":
    main()

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
    c41 = by_id[41]
    c42 = by_id[42]

    c41.update({
        "scene_location": "银湾公共电视台一号演播厅",
        "participants": [
            "麦珂·杰森", "玛莎·杰森", "黛安娜·罗文", "乔纳·杰森",
            "雷蒙·克里夫（节目制作人）", "托比（鼓手）"
        ],
        "allowed_roles": [
            "麦珂·杰森", "玛莎·杰森", "黛安娜·罗文", "乔纳·杰森",
            "雷蒙·克里夫（节目制作人）", "托比（鼓手）"
        ],
        "opponent_reaction": "制作人雷蒙原本等着麦珂在直播中出丑，救场成功后却立刻向记者宣称三秒停顿是自己的创意。",
        "immediate_payoff": "观众把事故当成全场最炸的即兴段落；麦珂用现场创造赢得欢呼，但嗓子过度用力并失去原定高音返场。",
        "chapter_ending": "制作人公开抢功，麦珂要求查清究竟是谁写下这三秒。",
        "main_opponent": "雷蒙·克里夫"
    })
    c42.update({
        "scene_location": "银湾公共电视台剪辑室",
        "participants": [
            "麦珂·杰森", "玛莎·杰森", "黛安娜·罗文",
            "雷蒙·克里夫（节目制作人）", "托比（鼓手）",
            "电视台节目主管（本事件权限主体）", "巴里·布鲁姆"
        ],
        "allowed_roles": [
            "麦珂·杰森", "玛莎·杰森", "黛安娜·罗文",
            "雷蒙·克里夫（节目制作人）", "托比（鼓手）",
            "电视台节目主管（本事件权限主体）", "巴里·布鲁姆"
        ],
        "opponent_reaction": "雷蒙先宣称三秒停顿由自己设计，被乐手指出他曾要求绝不能停拍后，又为抢功亲口承认伴奏延迟由他安排。",
        "immediate_payoff": "节目保留未剪辑版本，三秒即兴署名归麦珂与现场乐队，制作人失去单方面剪辑和宣传署名权。",
        "chapter_ending": "麦珂取得版本确认权；巴里随即以口头承诺可以事后补手续为诱饵接近他。",
        "main_opponent": "雷蒙·克里夫"
    })

    clusters = json.loads(args.clusters.read_text(encoding="utf-8"))
    cluster_list = clusters
    if isinstance(clusters, dict):
        cluster_list = clusters.get("event_clusters", clusters.get("clusters", clusters.get("data", [])))
    ec021 = next(item for item in cluster_list if item.get("cluster_id") == "EC021")
    ec021.update({
        "timeline_years": "1971",
        "main_opponent": "雷蒙·克里夫",
        "relationship_change": "玛莎从侧幕里的担忧者变成主动阻止剪辑母带的保护者；乔纳第一次没有冲上台替麦珂做决定。",
        "cluster_outcome": "麦珂牺牲高音返场并停唱两天，却保住完整演出版本，取得与现场乐队共同署名及版本确认权；制作人失去单方面剪辑与抢占创意的权力。",
        "next_event_hook": "巴里·布鲁姆见舞台版本无法被夺走，转而用‘口头承诺即可生效、书面手续以后再补’诱导麦珂确认资产划转。"
    })

    atomic_write_json(args.synopses, synopses)
    atomic_write_json(args.clusters, clusters)
    print({"chapters_updated": [41, 42], "cluster_updated": "EC021"})


if __name__ == "__main__":
    main()

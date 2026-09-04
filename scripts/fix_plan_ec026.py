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
    c51 = by_id[51]
    c52 = by_id[52]

    c51.update({
        "scene_location": "银湾广播电台三号直播间",
        "participants": [
            "麦珂·杰森", "玛莎·杰森", "巴里·布鲁姆",
            "电台主持人", "直播导播与总机接线员（本事件权限主体）"
        ],
        "allowed_roles": [
            "麦珂·杰森", "玛莎·杰森", "巴里·布鲁姆",
            "电台主持人", "直播导播与总机接线员（本事件权限主体）"
        ],
        "chapter_must_include": [
            "厂牌删掉副歌两拍", "麦珂在采访中清唱被删掉的两拍", "听众来电追问完整版"
        ],
        "chapter_must_not_include": [
            "笔压陷阱", "圆珠笔", "公证先行", "麦珂无视医生限制演唱完整歌曲"
        ],
        "exact_action_sequence": [
            "麦珂在直播前听见厂牌剪掉最有辨识度的两拍",
            "主持人按厂牌采访卡提问，麦珂只清唱被删两拍",
            "总机来电迅速涌入，听众主动追问完整版本",
            "厂牌撤下当日完整播放并声称来电只是猎奇"
        ],
        "opponent_reaction": "巴里先说两拍没有价值，听众来电后又要求切广告，并把热度解释成厂牌制造的猎奇。",
        "immediate_payoff": "主持人被迫承认完整版本存在，听众来电记录成为市场反应；麦珂失去当日完整曝光。",
        "chapter_ending": "第一叠来电记录都在追问被删掉的两拍何时回来。",
        "main_opponent": "巴里·布鲁姆"
    })

    c52.update({
        "scene_location": "银湾广播电台监听室",
        "participants": [
            "麦珂·杰森", "昆廷·琼斯", "巴里·布鲁姆",
            "电台节目主任", "导播与点播员（本事件权限主体）"
        ],
        "allowed_roles": [
            "麦珂·杰森", "昆廷·琼斯", "巴里·布鲁姆",
            "电台节目主任", "导播与点播员（本事件权限主体）"
        ],
        "chapter_must_include": [
            "原始母带与播出记录", "来电时点证明听众追问源于被删副歌",
            "厂牌恢复完整版并给予麦珂版本确认权"
        ],
        "chapter_must_not_include": [
            "笔压记录", "圆珠笔", "连续公证戏", "厂牌永久失去全部发行权"
        ],
        "exact_action_sequence": [
            "工作人员对照原始母带、厂牌剪辑版与播出记录",
            "来电记录显示第一轮追问发生在清唱两拍之后",
            "巴里试图把热度归功于厂牌剪辑却被内线录音反驳",
            "厂牌恢复完整版并同意今后删改须由麦珂确认"
        ],
        "opponent_reaction": "巴里把听众追问说成厂牌刻意制造的悬念，却被自己要求隐藏删改的内线录音戳穿。",
        "immediate_payoff": "完整版恢复，麦珂取得版本确认权；厂牌同时撤掉黄金轮播预算作为现实代价。",
        "chapter_ending": "完整版点播获得真实市场回声，但归还母带的封条异常，为下一次调包企图留下钩子。",
        "main_opponent": "巴里·布鲁姆"
    })

    clusters = json.loads(args.clusters.read_text(encoding="utf-8"))
    cluster_list = clusters
    if isinstance(clusters, dict):
        cluster_list = clusters.get("event_clusters", clusters.get("clusters", clusters.get("data", [])))
    ec026 = next(item for item in cluster_list if item.get("cluster_id") == "EC026")
    ec026.update({
        "timeline_years": "1971",
        "main_opponent": "巴里·布鲁姆",
        "comic_villain_behavior": "巴里先断言两拍无人记得，热线亮满后又抢着说这是厂牌策划；他为压住追问误按通话键，反而让隐藏删改的命令留下播出记录。",
        "relationship_change": "玛莎支持麦珂在医生限制内只唱两拍；昆廷从保护母带音质进一步转为支持麦珂的创作决定权。",
        "cluster_outcome": "厂牌恢复完整版并承认麦珂的版本确认权；麦珂以失去三周黄金轮播为代价，证明听众真正追问的正是被删掉的两拍。",
        "next_event_hook": "完整版恢复后，归还母带的封条出现异常；巴里随即以设备升级为名带来一盘替换磁带。"
    })

    atomic_write_json(args.synopses, synopses)
    atomic_write_json(args.clusters, clusters)
    print({"chapters_updated": [51, 52], "cluster_updated": "EC026"})


if __name__ == "__main__":
    main()

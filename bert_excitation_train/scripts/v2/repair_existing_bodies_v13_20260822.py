"""Targeted, reviewable identity/world-name repairs for accepted chapters 1-210."""
from __future__ import annotations

import json
from pathlib import Path


OUT = Path(__file__).resolve().parents[2] / "outputs_pop_king_v6_compiled_story_first_500"
CHAPTERS = OUT / "chapters"
REPORT = OUT / "existing_body_v13_repairs_20260822.json"


REPLACEMENTS: dict[int, tuple[tuple[str, str], ...]] = {
    30: (("联邦调查局", "联邦特别调查署"),),
    35: (("乔纳看着母亲，又看了看女儿和妻子", "乔纳看着玛莎，又看了看麦珂和黛安娜"),),
    37: (("他看着女儿和妻子站在一起", "他看着妻子和黛安娜站在一起"),),
    47: (("她没抬头", "他没抬头"), ("让她成年后", "让他成年后"),
         ("她记得这个时间点", "他记得这个时间点"), ("她想起前世", "他想起前世"),
         ("她不再是那个只会哭泣的孩子", "他不再是那个只会哭泣的孩子"),
         ("她是一个懂得利用规则", "他是一个懂得利用规则")),
    48: (("麦珂没有看父亲，她正", "麦珂没有看父亲，他正"), ("她记得过去那次", "他记得过去那次"),
         ("吞掉了她所有的版权", "吞掉了他所有的版权"), ("这一次，她没有给父亲", "这一次，他没有给父亲"),
         ("但她脸上依旧", "但他脸上依旧"), ("女儿冷静得可怕", "儿子冷静得可怕"),
         ("搭在女儿的肩头", "搭在儿子的肩头"), ("她转过身，看着母亲", "他转过身，看着母亲"),
         ("一把抱住女儿", "一把抱住儿子"), ("让她窒息的", "让他窒息的")),
    51: (("和女儿争执", "和儿子争执"), ("但女儿那种", "但儿子那种"),
         ("看着女儿认真的模样", "看着儿子认真的模样"), ("看着女儿专注的样子", "看着儿子专注的样子"),
         ("女儿成了那个掌控一切的人", "儿子成了那个掌控一切的人")),
    52: (("看着女儿那双", "看着儿子那双"),),
    65: (("她知道，这只是第一步", "他知道，这只是第一步"), ("她转身看向", "他转身看向"),
         ("“我们还有时间，”她说", "“我们还有时间，”他说")),
    71: (("联邦调查局", "联邦特别调查署"),),
    87: (("麦珂终于动了，她放下", "麦珂终于动了，他放下"), ("那是一份她昨晚", "那是一份他昨晚"),
         ("她微笑着将文件", "他微笑着将文件"), ("她知道，这只是第一步", "他知道，这只是第一步"),
         ("但她已经准备好了", "但他已经准备好了"), ("将是她最锋利的武器", "将是他最锋利的武器"),
         ("她知道自己赢了这一局", "他知道自己赢了这一局")),
    88: (("麦珂没有看父亲，她伸手", "麦珂没有看父亲，他伸手"), ("麦珂看着这一切，心中并没有", "麦珂看着这一切，他心中并没有"),
         ("她知道，这一战", "他知道，这一战"), ("她站起身", "他站起身"), ("她的语气礼貌", "他的语气礼貌"),
         ("麦珂深吸了一口气，感觉", "麦珂深吸了一口气，他感觉"), ("她看向母亲", "他看向母亲"),
         ("这一刻，她不再是", "这一刻，他不再是")),
    149: (("联邦调查局", "联邦特别调查署"),),
    151: (("麦珂没有立刻伸手去拿笔，她假装", "麦珂没有立刻伸手去拿笔，他假装"),
          ("但她的右手", "但他的右手"), ("麦珂看着巴里那滑稽又绝望的挣扎", "麦珂看着巴里那滑稽又绝望的挣扎"),
          ("。她并没有因为胜利", "。他并没有因为胜利"), ("。她知道，这只是开始", "。他知道，这只是开始"),
          ("但今天，她必须守住底线", "但今天，他必须守住底线"), ("。她站起身", "。他站起身"),
          ("“巴里先生，”她的声音", "“巴里先生，”他的声音")),
    178: (("去纽约读最好的音乐学院", "去海岬城读最好的音乐学院"),),
    181: (("她记得清楚", "他记得清楚"), ("麦珂没有动，她只是", "麦珂没有动，他只是"),
          ("她们没有回头去看", "他们没有回头去看"), ("。她摸了摸口袋", "。他摸了摸口袋"),
          ("。她知道维克多", "。他知道维克多"), ("。她不再是被动的受害者", "。他不再是被动的受害者")),
    182: (("。她看着巴里", "。他看着巴里"), ("拍了拍她的肩膀", "拍了拍他的肩膀"),
          ("。她知道，苏菲亚", "。他知道，苏菲亚"), ("递给她一瓶水", "递给他一瓶水")),
    201: (("玛莎站在门口，看着女儿坚定的背影", "玛莎站在门口，看着莉薇娅坚定的背影"),),
    203: (("聚光灯还没完全打亮，她低头", "聚光灯还没完全打亮，他低头"),
          ("而她只能隔着", "而他只能隔着"), ("这一世，她没等", "这一世，他没等"),
          ("属于29岁少年的腿", "属于二十八岁成年人的腿")),
    204: (("麦珂没有像前世那样躲在后台瑟瑟发抖，她穿着", "麦珂没有像前世那样躲在后台瑟瑟发抖，他穿着"),
          ("。她没急着辩解", "。他没急着辩解"), ("这一次，她们不仅", "这一次，他们不仅"),
          ("前方等着她们", "前方等着他们"), ("在这个阳光明媚的清晨，她们已经", "在这个阳光明媚的清晨，他们已经"),
          ("但她不再是一个人面对", "但他不再是一个人面对"), ("直视索恩", "直视昆廷·琼斯"),
          ("巨石终于落地。她知道", "巨石终于落地。他知道")),
    207: (("IBM Selectric II型号", "辉轮二型电动球形字模机"),
          ("IBM Selectric II打字机", "辉轮二型电动球形字模机")),
}


def main() -> None:
    changed: list[dict[str, object]] = []
    missing: list[dict[str, object]] = []
    for chapter_id, replacements in REPLACEMENTS.items():
        path = CHAPTERS / f"chapter_{chapter_id:03d}.txt"
        text = path.read_text(encoding="utf-8")
        original = text
        applied = 0
        for old, new in replacements:
            if old == new:
                continue
            count = text.count(old)
            if count:
                text = text.replace(old, new)
                applied += count
            elif new not in text:
                missing.append({"chapter_id": chapter_id, "old": old, "new": new})
        if text != original:
            backup = path.with_suffix(path.suffix + ".pre_v13_20260822")
            if not backup.exists():
                backup.write_text(original, encoding="utf-8")
            path.write_text(text, encoding="utf-8")
            changed.append({"chapter_id": chapter_id, "replacements": applied})
    report = {
        "version": "v13_body_repairs_20260822",
        "verified_repair_chapters": sorted(REPLACEMENTS),
        "changed_this_run": changed,
        "unresolved_replacements": missing,
        "passed": not missing,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

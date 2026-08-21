"""Apply the reviewed small root-plan repairs found during the first-50 audit."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = (
    PROJECT_ROOT
    / "bert_excitation_train"
    / "outputs_pop_king_v5_qwen_story_first_500"
)


REPAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    "EC022": (),
    "EC023": (
        ("LED红灯", "红色指示灯"),
    ),
    "EC012": (
        ("打印键", "走纸键"),
        ("屏幕倏然亮起绿色波形", "示波管倏然亮起绿色波形"),
        (
            "奥瑞恩邮件系统标记其账号",
            "奥瑞恩纸质风险名册将其登记为",
        ),
    ),
    "EC014": (
        (
            "用ChronoBadge胸牌拍下签字瞬间",
            "用黄铜双秒针机械秒表卡定签字瞬间",
        ),
        (
            "举起ChronoBadge胸牌，LED灯应声爆闪绿光",
            "按停黄铜双秒针机械秒表，双秒针同时停住",
        ),
        (
            "举起ChronoBadge对准签名，LED灯闪烁绿光",
            "按停黄铜双秒针机械秒表，双秒针同时停住",
        ),
        (
            "提前调试ChronoBadge胸牌，设定14:17自动闪光",
            "提前校准黄铜双秒针机械秒表，并约定14:17按停",
        ),
        (
            "ChronoBadge绿光与十六块面板绿灯同频闪烁",
            "机械秒表的双秒针同时停在14:17:02",
        ),
        ("ChronoBadge时间戳", "机械秒表停针时刻"),
        ("ChronoBadge收回口袋", "机械秒表收回口袋"),
        ("ChronoBadge胸牌", "黄铜双秒针机械秒表"),
        ("ChronoBadge", "黄铜双秒针机械秒表"),
        ("LED灯", "白炽指示灯"),
    ),
    "EC024": (
        (
            "ChronoBadge正微微发烫，红光缓慢脉动",
            "ChronoBadge因过热而发烫，铜箔边缘的热显色层缓慢转红",
        ),
        (
            "浅红印记正随呼吸微微发亮",
            "浅红烫痕在蒸汽里格外刺目",
        ),
        (
            "系统已注销CB-19700917-01胸牌编号",
            "纸质装备名册已注销CB-19700917-01胸牌编号",
        ),
        ("被系统注销", "从纸质装备名册注销"),
        ("昨日上午D-7槽", "三天前D-7槽"),
        ("那是D-7槽高温留下的烙印", "那是三天前D-7槽高温留下的烙印"),
    ),
}


MUST_NOT: dict[int, tuple[str, ...]] = {
    23: ("电子邮件", "邮件系统", "全员邮箱", "打印机"),
    24: ("电子邮件", "邮件系统", "全员邮箱", "打印机"),
    27: ("ChronoBadge", "LED灯", "电子屏", "绿光闪烁"),
    28: ("ChronoBadge", "LED灯", "电子屏", "绿光闪烁"),
    31: ("LED灯",),
    32: ("LED灯",),
    43: ("麦珂使用女性代词",),
    44: ("麦珂使用女性代词",),
    45: ("麦珂使用女性代词", "LED"),
    46: ("麦珂使用女性代词", "LED"),
    47: ("麦珂使用女性代词", "ChronoBadge发出红光", "电子注销系统"),
    48: (
        "麦珂使用女性代词",
        "ChronoBadge发出红光",
        "电子注销系统",
        "昨日上午D-7槽",
    ),
}


def repair_value(value: Any, replacements: tuple[tuple[str, str], ...]) -> Any:
    if isinstance(value, str):
        for old, new in replacements:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [repair_value(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: repair_value(item, replacements) for key, item in value.items()}
    return value


def save_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    event_path = OUTPUT_DIR / "event_clusters_v2.json"
    card_path = OUTPUT_DIR / "master_ctx_cards_v2.json"
    events = json.loads(event_path.read_text(encoding="utf-8"))
    cards = json.loads(card_path.read_text(encoding="utf-8"))

    event_ids = {str(event.get("cluster_id") or "") for event in events}
    if set(REPAIRS) - event_ids:
        raise RuntimeError("目标事件簇不存在：" + ",".join(sorted(set(REPAIRS) - event_ids)))

    repaired_events = []
    for event in events:
        cluster_id = str(event.get("cluster_id") or "")
        repaired_event = repair_value(event, REPAIRS.get(cluster_id, ()))
        if cluster_id == "EC022":
            repaired_event = repair_value(repaired_event, (("她", "他"),))
        repaired_events.append(repaired_event)
    repaired_cards = []
    for card in cards:
        chapter_id = int(card.get("chapter_id") or 0)
        cluster_id = str(card.get("cluster_id") or "")
        body_contract = dict(card)
        existing_guards = list(body_contract.pop("chapter_must_not_include", []) or [])
        repaired = repair_value(body_contract, REPAIRS.get(cluster_id, ()))
        if cluster_id in ("EC022", "EC023") and chapter_id in (43, 44, 45, 46):
            repaired = repair_value(repaired, (("她", "他"),))
        if cluster_id == "EC024" and chapter_id in (47, 48):
            repaired = repair_value(repaired, (("她", "他"),))
        if chapter_id in MUST_NOT:
            managed_variants = set(MUST_NOT[chapter_id])
            for old, new in REPAIRS.get(cluster_id, ()):
                managed_variants.update(
                    anchor.replace(old, new) for anchor in MUST_NOT[chapter_id]
                )
            anchors = [
                anchor for anchor in existing_guards if anchor not in managed_variants
            ]
            for anchor in MUST_NOT[chapter_id]:
                if anchor not in anchors:
                    anchors.append(anchor)
            repaired["chapter_must_not_include"] = anchors
        else:
            repaired["chapter_must_not_include"] = existing_guards
        repaired_cards.append(repaired)

    event_text = json.dumps(repaired_events, ensure_ascii=False)
    card_text = json.dumps(repaired_cards, ensure_ascii=False)
    forbidden_by_cluster = {
        "EC012": ("奥瑞恩邮件系统",),
        "EC014": ("ChronoBadge", "LED灯"),
        "EC023": ("LED",),
    }
    for cluster_id, forbidden in forbidden_by_cluster.items():
        scoped_event = next(
            event for event in repaired_events if event.get("cluster_id") == cluster_id
        )
        scoped_cards = []
        for card in repaired_cards:
            if card.get("cluster_id") != cluster_id:
                continue
            body_contract = dict(card)
            # The explicit negative guard intentionally names the forbidden
            # object/technology; it is not a positive planning leak.
            body_contract.pop("chapter_must_not_include", None)
            scoped_cards.append(body_contract)
        scoped_text = json.dumps([scoped_event, *scoped_cards], ensure_ascii=False)
        leaked = [term for term in forbidden if term in scoped_text]
        if leaked:
            raise RuntimeError(f"{cluster_id}仍含根规划旧错误：{leaked}")
    repaired_47_48 = [
        card for card in repaired_cards if int(card.get("chapter_id") or 0) in (47, 48)
    ]
    repaired_47_48_text = json.dumps(repaired_47_48, ensure_ascii=False)
    if len(repaired_47_48) != 2 or "她" in repaired_47_48_text:
        raise RuntimeError("章卡性别修复后结构异常")
    repaired_43_46 = [
        card for card in repaired_cards if int(card.get("chapter_id") or 0) in (43, 44, 45, 46)
    ]
    repaired_43_46_text = json.dumps(repaired_43_46, ensure_ascii=False)
    event_22_text = json.dumps(
        next(event for event in repaired_events if event.get("cluster_id") == "EC022"),
        ensure_ascii=False,
    )
    if len(repaired_43_46) != 4 or "她" in repaired_43_46_text or "她" in event_22_text:
        raise RuntimeError("第43—46章根规划性别修复后结构异常")

    save_json(event_path, repaired_events)
    save_json(OUTPUT_DIR / "event_clusters_v5_qwen_500.json", repaired_events)
    save_json(card_path, repaired_cards)
    save_json(OUTPUT_DIR / "chapter_synopses_v5_qwen_500.json", repaired_cards)
    print("已修复EC012、EC014、EC024根规划；权威文件与归档同步。")


if __name__ == "__main__":
    main()

"""Validate the isolated full-shape candidate package before any promotion."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

# Permit direct execution from the repository root as well as ``python -m``.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bert_excitation_train.scripts.v2.generate_pop_king_body_v5 import _load_character_bible
from bert_excitation_train.scripts.v2.pop_king_plan_compiler import canonical_sha256, timeline_years


WRONG_NAMES = ("黛安娜·陈", "瑟琳娜·王", "瑟琳娜·刘", "瑟琳娜·麦凯", "维克多·斯特林", "苏菲亚·沃克", "昆廷·哈特", "卡尔·斯特林")


def validate(package: Path) -> list[str]:
    failures: list[str] = []
    try:
        events = json.loads((package / "event_clusters_v2.json").read_text(encoding="utf-8"))
        cards = json.loads((package / "master_ctx_cards_v2.json").read_text(encoding="utf-8"))
        synopses = json.loads((package / "chapter_synopses_v5_qwen_500.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"候选规划包不可读：{exc}"]
    if len(events) != 250 or len(cards) != 500 or len(synopses) != 500:
        failures.append(f"候选包形状错误：events={len(events)}, cards={len(cards)}, synopses={len(synopses)}")
    event_by_id = {str(x.get("cluster_id")): x for x in events}
    card_by_id = {int(x.get("chapter_id") or 0): x for x in cards}
    points: set[str] = set()
    signatures: set[str] = set()
    previous_date: date | None = None
    for number in range(136, 179):
        eid = f"EC{number:03d}"
        event = event_by_id.get(eid)
        if not event:
            failures.append(f"缺少{eid}")
            continue
        point = str(event.get("irreplaceable_progress_point") or "")
        signature = json.dumps(event.get("structure_signature") or {}, ensure_ascii=False, sort_keys=True)
        if not point or point in points:
            failures.append(f"{eid}不可替代推进点缺失或重复")
        points.add(point)
        if len((event.get("structure_signature") or {})) < 7 or signature in signatures:
            failures.append(f"{eid}结构签名缺失或重复")
        signatures.add(signature)
        cast = event.get("canonical_cast") or []
        ids = {str(x.get("character_id")) for x in cast if isinstance(x, dict)}
        if len(ids) != len(cast) or any(not re.fullmatch(r"CHAR_[A-F0-9]{12}", x) for x in ids):
            failures.append(f"{eid}canonical_cast存在非法或重复character_id")
        if any(name in json.dumps(event, ensure_ascii=False) for name in WRONG_NAMES):
            failures.append(f"{eid}仍含漂移姓名")
        years = timeline_years(event.get("timeline_years"))
        for chapter_id in event.get("chapter_span") or []:
            card = card_by_id.get(int(chapter_id))
            if not card:
                failures.append(f"{eid}缺少第{chapter_id}章卡")
                continue
            if card.get("source_event_sha256") != canonical_sha256(event):
                failures.append(f"第{chapter_id}章卡事件哈希未绑定{eid}")
            start = str(card.get("timeline_start") or "")
            try:
                current = date.fromisoformat(start)
            except ValueError:
                failures.append(f"第{chapter_id}章日期非法：{start}")
                continue
            if years and current.year not in years:
                failures.append(f"第{chapter_id}章年份不属于{eid}.timeline_years")
            if previous_date and current < previous_date:
                failures.append(f"第{chapter_id}章日期倒退")
            previous_date = current
            if any(name in json.dumps(card, ensure_ascii=False) for name in WRONG_NAMES):
                failures.append(f"第{chapter_id}章卡仍含漂移姓名")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    failures = validate(args.package.resolve())
    if failures:
        raise SystemExit("\n".join(failures))
    print(json.dumps({"passed": True, "checked_events": 43, "checked_chapters": 86, "formal_promotion": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()

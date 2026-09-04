#!/usr/bin/env python3
"""Audit the human-authored EC136-EC250 two-chapter divisions."""
from __future__ import annotations

from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bert_excitation_train.scripts.v2.pop_king_tail_manual_divisions_v1 import DIVISIONS


OUT = ROOT / "bert_excitation_train" / "outputs_pop_king_v6_compiled_story_first_500"
BAD_NAMES = ("维克多·斯特林", "卡尔·斯特林", "麦克·杰克逊", "迈克尔·杰克逊", "塞雷娜")


def load(name: str) -> Any:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。！？!?]", text) if part.strip()]


def trigrams(text: str) -> set[str]:
    compact = re.sub(r"[\s，。；：、“”‘’（）《》！？!?]", "", text)
    return {compact[index:index + 3] for index in range(max(0, len(compact) - 2))}


def jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / max(1, len(left | right))


def main() -> None:
    events = load("event_clusters_v2.json")
    cards = load("master_ctx_cards_v2.json")
    synopses = load("chapter_synopses_v5_qwen_500.json")
    failures: list[str] = []
    if (len(events), len(cards), len(synopses)) != (250, 500, 500):
        failures.append(f"正式文件数量异常：events={len(events)}, cards={len(cards)}, synopses={len(synopses)}")
    synopsis_view = [{key: value for key, value in card.items() if key != "character_lifecycle"} for card in cards]
    if synopsis_view != synopses:
        failures.append("master_ctx_cards_v2与chapter_synopses正式视图不一致")

    expected_ids = {f"EC{number:03d}" for number in range(136, 251)}
    if set(DIVISIONS) != expected_ids:
        failures.append("人工分章源未精确覆盖EC136—EC250")

    pair_rows: list[dict[str, Any]] = []
    all_tail: list[tuple[int, str]] = []
    completion_words = ("确认", "完成", "获得", "保住", "恢复", "限制", "拒绝", "失去", "形成", "进入", "通过", "冻结", "移交", "公开", "达成", "转为", "留下", "批准", "生效", "解除", "撤销", "暂停", "承担", "换得", "停止", "重置", "找到", "取得", "撤回", "同意", "允许")
    for number in range(136, 251):
        eid = f"EC{number:03d}"
        event = events[number - 1]
        ch1_id, ch2_id = number * 2 - 1, number * 2
        ch1, ch2 = cards[ch1_id - 1], cards[ch2_id - 1]
        left = str(ch1.get("detailed_synopsis") or "")
        right = str(ch2.get("detailed_synopsis") or "")
        left_sentences, right_sentences = sentences(left), sentences(right)
        shared = sorted(set(left_sentences) & set(right_sentences))
        ratio = SequenceMatcher(None, left, right).ratio()
        tri = jaccard(trigrams(left), trigrams(right))
        issues: list[str] = []
        if event.get("cluster_id") != eid or event.get("chapter_span") != [ch1_id, ch2_id]:
            issues.append("情节族编号或章节跨度不一致")
        if ch1.get("cluster_id") != eid or ch2.get("cluster_id") != eid:
            issues.append("章卡未绑定对应情节族")
        if ch1.get("chapter_title") != f"{event.get('name')}·上" or ch2.get("chapter_title") != f"{event.get('name')}·下":
            issues.append("章名与情节族名不一致")
        if left != DIVISIONS[eid]["ch1"] or right != DIVISIONS[eid]["ch2"]:
            issues.append("正式梗概与人工分章源不一致")
        if len(left_sentences) < 3 or len(right_sentences) < 3:
            issues.append("任一章少于三个具体场景节点")
        if shared:
            issues.append("两章存在完全相同的梗概句")
        if ratio >= 0.45 or tri >= 0.35:
            issues.append("两章文本近似度过高")
        if ch1.get("chapter_goal") == ch2.get("chapter_goal"):
            issues.append("两章目标相同")
        if ch1.get("chapter_ending") == ch2.get("chapter_ending"):
            issues.append("两章结尾相同")
        if not any(word in right for word in completion_words):
            issues.append("下章未写出可识别的推进或结算动作")
        if str(ch1.get("timeline_start")) > str(ch2.get("timeline_start")):
            issues.append("同组时间线倒退")
        artifact_names = [
            str(item.get("display_name") or "").strip("《》")
            for item in ch1.get("artifact_creates") or [] if isinstance(item, dict)
        ]
        if artifact_names and not any(name and name in left + right for name in artifact_names):
            issues.append("人工梗概未落入本情节族核心物证")
        if issues:
            failures.extend(f"{eid}: {issue}" for issue in issues)
        pair_rows.append({
            "cluster_id": eid,
            "chapters": [ch1_id, ch2_id],
            "name": event.get("name"),
            "sequence_similarity": round(ratio, 4),
            "trigram_jaccard": round(tri, 4),
            "shared_sentences": shared,
            "ch1_action_nodes": len(left_sentences),
            "ch2_action_nodes": len(right_sentences),
            "issues": issues,
        })
        all_tail.extend(((ch1_id, left), (ch2_id, right)))

    cross_near_duplicates: list[dict[str, Any]] = []
    for index, (left_id, left) in enumerate(all_tail):
        left_tri = trigrams(left)
        for right_id, right in all_tail[index + 1:]:
            score = jaccard(left_tri, trigrams(right))
            if score >= 0.42:
                cross_near_duplicates.append({"chapters": [left_id, right_id], "trigram_jaccard": round(score, 4)})
    if cross_near_duplicates:
        failures.append(f"第271—500章存在{len(cross_near_duplicates)}组跨情节族近似梗概")

    identity_by_id: dict[str, str] = {}
    identity_conflicts: list[str] = []
    for payload in events + cards:
        for member in payload.get("canonical_cast") or []:
            if not isinstance(member, dict):
                continue
            cid = str(member.get("character_id") or "")
            name = str(member.get("display_name") or member.get("name") or "")
            if cid and cid in identity_by_id and identity_by_id[cid] != name:
                identity_conflicts.append(f"{cid}: {identity_by_id[cid]} / {name}")
            elif cid:
                identity_by_id[cid] = name
    corpus = json.dumps({"events": events, "cards": cards}, ensure_ascii=False)
    bad_name_hits = [name for name in BAD_NAMES if name in corpus]
    failures.extend(f"人物ID对应多个姓名：{item}" for item in sorted(set(identity_conflicts)))
    failures.extend(f"发现禁用旧姓名：{name}" for name in bad_name_hits)

    report = {
        "version": "v16_manual_chapter_divisions_20260827",
        "scope": {"event_clusters": [136, 250], "chapters": [271, 500]},
        "counts": {"event_clusters": len(events), "chapter_cards": len(cards), "audited_pairs": len(pair_rows)},
        "summary": {
            "passed": not failures,
            "pairs_with_exact_shared_sentences": sum(bool(row["shared_sentences"]) for row in pair_rows),
            "pairs_with_similarity_ge_045": sum(row["sequence_similarity"] >= 0.45 for row in pair_rows),
            "maximum_within_pair_similarity": max(row["sequence_similarity"] for row in pair_rows),
            "cross_cluster_near_duplicate_pairs": len(cross_near_duplicates),
            "same_character_id_multiple_names": len(set(identity_conflicts)),
            "bad_name_hits": bad_name_hits,
        },
        "failures": failures,
        "pairs": pair_rows,
        "cross_near_duplicates": cross_near_duplicates,
    }
    json_path = OUT / "body_generation" / "manual_tail_division_audit_v16.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 第271—500章人工分章审查（v16）", "",
        f"- 结果：{'通过' if not failures else '需修改'}",
        f"- 审查情节族：{len(pair_rows)}组（EC136—EC250）",
        f"- 同组完全重复句：{report['summary']['pairs_with_exact_shared_sentences']}组",
        f"- 同组相似度≥0.45：{report['summary']['pairs_with_similarity_ge_045']}组",
        f"- 同组最高相似度：{report['summary']['maximum_within_pair_similarity']}",
        f"- 跨情节族近似章卡：{len(cross_near_duplicates)}组",
        f"- 人物ID一对多姓名：{len(set(identity_conflicts))}项",
        f"- 禁用旧姓名命中：{len(bad_name_hits)}项", "",
        "| 情节族 | 章节 | 名称 | 文本相似度 | 三元组相似度 | 上/下动作节点 | 结果 |",
        "|---|---:|---|---:|---:|---:|---|",
    ]
    for row in pair_rows:
        lines.append(
            f"| {row['cluster_id']} | {row['chapters'][0]}—{row['chapters'][1]} | {row['name']} | "
            f"{row['sequence_similarity']:.4f} | {row['trigram_jaccard']:.4f} | "
            f"{row['ch1_action_nodes']}/{row['ch2_action_nodes']} | {'通过' if not row['issues'] else '；'.join(row['issues'])} |"
        )
    if failures:
        lines.extend(("", "## 未通过项", "", *(f"- {item}" for item in failures)))
    md_path = OUT / "body_generation" / "MANUAL_TAIL_DIVISION_AUDIT_V16.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

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
import os
import json
import sys
from pathlib import Path
from typing import Dict, Any, List

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bert_excitation_train.scripts.smart_sample_search import search_and_adapt_samples
import bert_excitation_train.scripts.generate_event_clusters_v2 as legacy_v2

OUTPUT_DIR = legacy_v2.OUTPUT_DIR


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


def _build_seed_plan_with_user_input(cfg: Dict[str, str]) -> str:
    """基于人工输入先生成全书唯一主线蓝图。"""
    theme = cfg["theme"]
    background = cfg["background"]
    protagonists = _parse_protagonists(cfg.get("protagonists", ""))
    heroine, hero = _pick_legacy_leads(
        protagonists=protagonists,
        fallback_heroine=cfg.get("heroine_name", "沈清欢"),
        fallback_hero=cfg.get("hero_name", "顾寒川"),
    )
    extra = cfg.get("extra_constraints", "").strip()

    protag_hint = f"主角：{ '、'.join(protagonists) }。" if protagonists else ""
    base_query = f"{theme}，背景：{background}。{protag_hint}".strip()
    adapted_samples = search_and_adapt_samples(
        user_input=base_query,
        target_context=f"{theme}，{background}，重生，复仇，短剧",
        top_k=5,
        min_similarity=0.3,
    )
    sample_texts: List[str] = []
    for i, s in enumerate(adapted_samples or [], 1):
        sample_texts.append(
            f"【样本{i}】情绪：{', '.join(s.get('emotion_tags', []))}；"
            f"情节：{', '.join(s.get('plot_tags', []))}；"
            f"节选：{(s.get('content') or '')[:120]}..."
        )
    samples_block = "\n\n".join(sample_texts) if sample_texts else ""

    system_prompt = "你是重生复仇短剧的大纲总策划，需要先设计唯一的最大主线蓝图。"
    user_prompt = (
        f"请为一部《重生题材小说》设计一条贯穿全书100章的唯一主线蓝图（3-6句）。\n\n"
        f"本次人工指定题材：{theme}\n"
        f"本次人工指定背景：{background}\n"
        + (f"主角名字约束（不要求区分男女主，允许多个主角）：{'、'.join(protagonists)}\n" if protagonists else "")
        + f"（兼容占位名）女主占位：{heroine}\n"
        + f"（兼容占位名）男主占位：{hero}\n"
        + (f"额外限制：{extra}\n" if extra else "")
        + "\n要求：\n"
        "- 需明确上一世核心悲剧链（谁害她、怎么害）；\n"
        "- 需明确今生最大复仇目标与推进阶段；\n"
        "- 后续事件簇只能沿这条主线补细节，不得中途换世界观或换终极主线。\n\n"
        "如有样本可参考风格，不要抄袭剧情：\n"
        f"{samples_block}\n\n"
        "只输出蓝图本身。"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    plan = legacy_v2.call_qianwen_api(messages)
    if not plan or str(plan).startswith("通义千问"):
        plan = (
            f"占位蓝图：上一世，{heroine}在{background}场域被关键对手链条联手害死；"
            f"今生她将围绕“{theme}”主线逐层反击，最终在公众层面完成真相揭露与整体清算。"
        )
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
    final_arc_len = int(final_arc_len)
    final_arc_len = max(5, min(12, final_arc_len))
    final_start = total_chapters - final_arc_len + 1
    final_end = total_chapters

    base_prompt = legacy_v2.build_event_cluster_prompt(global_seed_plan)
    extra = f"""

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
"""
    user_prompt = base_prompt + extra
    messages = [
        {
            "role": "system",
            "content": "你是重生复仇短剧的结构设计师，需要在给定主线蓝图下设计事件簇，并以 JSON 数组输出。",
        },
        {"role": "user", "content": user_prompt},
    ]
    raw = legacy_v2.call_qianwen_api(messages, temperature=0.85, top_p=0.9)
    clusters = _extract_json_array_maybe(raw)
    return clusters


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
- 只输出 JSON 对象本身，不要解释。
""".strip()
    messages = [
        {"role": "system", "content": "你是重生复仇短剧的终局结构策划，只生成终局事件簇 JSON。"},
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
    final_arc_len = max(5, min(12, int(final_arc_len)))
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


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 事件簇生成（支持人工输入题材/背景/主角名）")
    parser.add_argument("--project-config", type=str, default=None)
    parser.add_argument("--generation-config", type=str, default=None)
    parser.add_argument("--theme", type=str, default="重生复仇短剧")
    parser.add_argument("--background", type=str, default="现代都市+医疗阴谋+职场反杀")
    parser.add_argument(
        "--protagonists",
        type=str,
        default="沈清欢,顾寒川",
        help="主角名字约束（可多个，不要求区分女主/男主；支持逗号/顿号/分号/换行分隔）",
    )
    # 兼容旧参数：仍可传，但交互默认不再询问
    parser.add_argument("--heroine-name", type=str, default="沈清欢", help=argparse.SUPPRESS)
    parser.add_argument("--hero-name", type=str, default="顾寒川", help=argparse.SUPPRESS)
    parser.add_argument("--extra-constraints", type=str, default="")
    parser.add_argument("--extra-constraints-file", type=str, default=None)
    parser.add_argument(
        "--final-arc-len",
        type=int,
        default=8,
        help="终局大情节族覆盖章节数（建议 5-12，默认 8，即 93-100）",
    )
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args()

    cfg: Dict[str, str] = {
        "theme": args.theme,
        "background": args.background,
        "protagonists": args.protagonists,
        "heroine_name": args.heroine_name,
        "hero_name": args.hero_name,
        "extra_constraints": args.extra_constraints,
    }

    if not args.non_interactive:
        cfg = _ask_interactive(cfg)

    file_constraints = _load_extra_constraints(args.extra_constraints_file)
    if file_constraints:
        merged = cfg.get("extra_constraints", "").strip()
        cfg["extra_constraints"] = f"{merged}\n{file_constraints}".strip() if merged else file_constraints

    # 将人工输入覆盖到 legacy 模块全局名，以便后续 prompt 与章节计划统一使用
    protagonists = _parse_protagonists(cfg.get("protagonists", ""))
    heroine, hero = _pick_legacy_leads(protagonists, cfg.get("heroine_name", "沈清欢"), cfg.get("hero_name", "顾寒川"))
    legacy_v2.HEROINE_NAME = heroine
    legacy_v2.HERO_NAME = hero

    print("\n" + "=" * 60)
    print("事件簇生成脚本 V2（迁移版）：先人工设定题材，再生成主线与事件簇")
    print("=" * 60)
    print(f"题材: {cfg['theme']}")
    print(f"背景: {cfg['background']}")
    if protagonists:
        print(f"主角名字约束: {'、'.join(protagonists)}")
    print(f"（兼容占位）女主占位: {heroine} | 男主占位: {hero}")
    if cfg.get("extra_constraints"):
        print(f"额外限制: {cfg['extra_constraints'][:200]}")

    global_seed_plan = _build_seed_plan_with_user_input(cfg)
    if cfg.get("extra_constraints"):
        global_seed_plan = (
            f"{global_seed_plan}\n\n"
            f"【人工约束】题材={cfg['theme']}；背景={cfg['background']}；"
            f"额外限制={cfg['extra_constraints']}"
        )

    os.makedirs(legacy_v2.OUTPUT_DIR, exist_ok=True)
    seed_path = os.path.join(legacy_v2.OUTPUT_DIR, "global_seed_plan_v2.txt")
    with open(seed_path, "w", encoding="utf-8") as f:
        f.write(f"题材：{cfg['theme']}\n")
        f.write(f"背景：{cfg['background']}\n")
        if protagonists:
            f.write(f"主角名字约束：{'、'.join(protagonists)}\n")
        f.write(f"（兼容占位）女主：{heroine}\n")
        f.write(f"（兼容占位）男主：{hero}\n\n")
        f.write(global_seed_plan)
    print(f"✅ 最大主线蓝图已写入：{seed_path}")

    clusters = _generate_event_clusters_v2_with_final_arc(
        global_seed_plan,
        final_arc_len=args.final_arc_len,
        total_chapters=100,
    )
    if not clusters:
        print("⚠️ 未生成任何事件簇，流程结束。")
        return

    clusters = legacy_v2._post_process_clusters(clusters)
    clusters = _ensure_final_arc_cluster(
        clusters,
        global_seed_plan,
        final_arc_len=args.final_arc_len,
        total_chapters=100,
    )
    for c in clusters:
        c["chapter_plan"] = legacy_v2._build_chapter_plan_for_cluster(c)
        c["user_theme"] = cfg["theme"]
        c["user_background"] = cfg["background"]
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


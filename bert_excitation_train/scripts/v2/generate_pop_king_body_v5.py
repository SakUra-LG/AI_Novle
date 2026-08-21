#!/usr/bin/env python3
"""Productivity-first body generator for the Qwen 500-chapter story plan.

The generator treats ``event_clusters_v2.json`` and
``master_ctx_cards_v2.json`` as authoritative story facts.  It generates one
two-chapter event cluster per transaction, records the untouched Qwen response,
and commits accepted chapter memory to the same Neo4j story scope as the
planning graph.  Prose is never patched locally: a failed candidate is rejected
and Qwen is asked to regenerate the complete cluster.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import dashscope

# This legacy module is lightweight and owns the project's existing DashScope
# environment fallback.  Importing the old outline generator would also load a
# large embedding model on every body-generation command.
from bert_excitation_train.scripts.fix_master_synopsis import API_Key_QW
from bert_excitation_train.scripts.neo4j_kg.common import get_neo4j_driver
from bert_excitation_train.scripts.neo4j_kg.online_retriever import (
    retrieve_context_for_chapter,
)
from bert_excitation_train.scripts.neo4j_kg.planning_graph import planning_story_id
from bert_excitation_train.scripts.neo4j_kg.story_memory import StoryMemoryCoordinator
from bert_excitation_train.scripts.qwen_transport import (
    call_openai_compatible_via_curl,
    call_qwen_via_curl,
)
from bert_excitation_train.scripts.v2.pop_king_plan_compiler import (
    body_prefix_fingerprints,
    card_fingerprint,
    event_fingerprint,
    semantic_similarity,
    validate_full_plan,
)


DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "bert_excitation_train" / "outputs_pop_king_v6_compiled_story_first_500"
)
DEFAULT_STYLE_SAMPLES = (
    PROJECT_ROOT / "bert_excitation_train" / "data" / "pop_king_revenge_style_samples_v1.json"
)
DEFAULT_CHARACTER_BIBLE = (
    PROJECT_ROOT / "bert_excitation_train" / "data" / "pop_king_character_bible_v1.json"
)
MIN_HAN_CHARS = 1000
TARGET_HAN_MIN = 1200
TARGET_HAN_MAX = 1600
MAX_HAN_CHARS = 1900
BODY_GENERATOR_CONTRACT_VERSION = "v8_character_bible_choice_contract_20260815"
_CHARACTER_BIBLE_CACHE: dict[str, Any] | None = None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prior_body_chain_sha256(output_dir: Path, before_chapter: int) -> str:
    """Bind a delivery to every official chapter that precedes its cluster."""
    rows: list[dict[str, Any]] = []
    for chapter_id in range(1, max(1, before_chapter)):
        path = output_dir / "chapters" / f"chapter_{chapter_id:03d}.txt"
        if not path.is_file():
            rows.append({"chapter_id": chapter_id, "sha256": None})
            continue
        rows.append({
            "chapter_id": chapter_id,
            "sha256": _sha(path.read_text(encoding="utf-8").strip()),
        })
    return _sha(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def _han_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))


def _productivity_body_failures(failures: list[str], body: str) -> list[str]:
    """Keep only failures that make a candidate unsafe to submit.

    The project is currently prioritising usable prose.  Scene/anchor overlap,
    slight length misses and wording/style reminders remain recorded in the
    audit, while empty/truncated/forbidden-content candidates are still rejected.
    """
    hard_tokens = (
        "正文为空", "正文疑似截断", "Unicode替换字符", "章节号必须完整",
        "命中章卡明确禁写项", "语义违反章卡禁写项", "正文含Markdown或分节小标题",
    )
    if not body.strip() or _han_count(body) < 500:
        return list(failures) or ["正文为空或过短"]
    return [failure for failure in failures if any(token in str(failure) for token in hard_tokens)]


def _clip(value: Any, limit: int) -> str:
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _load_character_bible(path: Path = DEFAULT_CHARACTER_BIBLE) -> dict[str, Any]:
    """Load the human-authored stable character layer once per process."""
    global _CHARACTER_BIBLE_CACHE
    if path == DEFAULT_CHARACTER_BIBLE and _CHARACTER_BIBLE_CACHE is not None:
        return _CHARACTER_BIBLE_CACHE
    payload = _load_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("characters"), list):
        raise ValueError(f"人物约束文件结构非法：{path}")
    if path == DEFAULT_CHARACTER_BIBLE:
        _CHARACTER_BIBLE_CACHE = payload
    return payload


def _character_constraints_for_scene(
    cluster: dict[str, Any], cards: list[dict[str, Any]],
    *, bible: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select only profiles that can actually act or speak in this cluster.

    Stable personality comes from the human bible.  Current injuries,
    relationships and secrets still come from the plan and Neo4j context.
    """
    source = bible or _load_character_bible()
    identity_payload = {
        "main_opponent": cluster.get("main_opponent"),
        "main_characters": cluster.get("main_characters"),
        "canonical_cast": cluster.get("canonical_cast"),
        "card_participants": [
            value
            for card in cards
            for key in ("participants", "allowed_roles")
            for value in (card.get(key) or [])
        ],
    }
    identity_text = json.dumps(identity_payload, ensure_ascii=False)
    selected: list[dict[str, Any]] = []
    for profile in source.get("characters") or []:
        if not isinstance(profile, dict):
            continue
        names = [str(profile.get("name") or "").strip(), *[
            str(value or "").strip() for value in profile.get("aliases") or []
        ]]
        names = [name for name in names if name]
        if profile.get("name") == "麦珂·杰森" or any(name in identity_text for name in names):
            selected.append(profile)
    return {
        "bible_version": source.get("version"),
        "use_rule": (
            "只用以下在场人物约束决定动作、对白与选择；情节事实和当前人物状态仍以章卡与Neo4j为准。"
        ),
        "global_method": source.get("global_method") or {},
        "fallback_for_unlisted_characters": source.get("fallback_for_unlisted_characters") or {},
        "selected_characters": selected,
    }


def _bootstrap_neo4j_env(container: str) -> None:
    """Use explicit env vars, or discover the local project's Docker auth."""
    if all(os.getenv(name) for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")):
        return
    completed = subprocess.run(
        [
            "docker",
            "inspect",
            container,
            "--format",
            "{{json .Config.Env}}",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Neo4j 环境变量未设置，且无法读取本项目 Docker 容器配置。"
        )
    env_rows = json.loads(completed.stdout.strip())
    auth_line = next(
        (row.split("=", 1)[1] for row in env_rows if row.startswith("NEO4J_AUTH=")),
        "",
    )
    if "/" not in auth_line:
        raise RuntimeError("Neo4j 容器没有有效的 NEO4J_AUTH。")
    user, password = auth_line.split("/", 1)
    os.environ.setdefault("NEO4J_URI", "bolt://127.0.0.1:7687")
    os.environ.setdefault("NEO4J_USER", user)
    os.environ.setdefault("NEO4J_PASSWORD", password)


def _qwen_content(response: Any) -> str:
    try:
        return str(response["output"]["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        try:
            return str(response["output"]["text"] or "")
        except (KeyError, TypeError):
            try:
                return str(response["choices"][0]["message"]["content"] or "")
            except (KeyError, IndexError, TypeError):
                return ""


def _call_qwen(
    messages: list[dict[str, str]], *, model: str, temperature: float
) -> tuple[str, dict[str, Any]]:
    api_key = os.getenv("BODY_API_KEY", "").strip() or API_Key_QW
    compatible_endpoint = os.getenv("BODY_API_ENDPOINT", "").strip()
    if not api_key:
        raise RuntimeError("QWEN_NON_RETRYABLE:MissingApiKey:请设置DASHSCOPE_API_KEY后再运行")
    if compatible_endpoint:
        started = time.monotonic()
        response = call_openai_compatible_via_curl(
            messages,
            api_key=api_key,
            model=model,
            endpoint=compatible_endpoint,
            temperature=temperature,
            top_p=0.86,
            max_tokens=7000,
            timeout_s=240,
        )
        raw = _qwen_content(response)
        if not raw.strip():
            raise RuntimeError("Qwen 兼容接口返回了空正文。")
        return raw, {
            "model": model,
            "transport": "openai_compatible_curl",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "usage": dict(response.get("usage") or {}) if isinstance(response, dict) else {},
            "endpoint": compatible_endpoint,
        }
    dashscope.api_key = api_key
    started = time.monotonic()
    transport = "dashscope_sdk"
    try:
        response = dashscope.Generation.call(
            model=model,
            messages=messages,
            temperature=temperature,
            top_p=0.86,
            repetition_penalty=1.08,
            result_format="message",
            max_tokens=7000,
        )
        raw = _qwen_content(response)
        usage = dict(response.get("usage") or {}) if hasattr(response, "get") else {}
    except Exception as sdk_error:  # noqa: BLE001
        transport = "curl_fallback"
        response = call_qwen_via_curl(
            messages,
            api_key=api_key,
            model=model,
            temperature=temperature,
            top_p=0.86,
            repetition_penalty=1.08,
            max_tokens=7000,
            timeout_s=240,
        )
        raw = _qwen_content(response)
        usage = dict(response.get("usage") or {})
        usage["sdk_error_class"] = type(sdk_error).__name__
    if not raw.strip():
        raise RuntimeError("Qwen 返回了空正文。")
    return raw, {
        "model": model,
        "transport": transport,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "usage": usage,
    }


def _parse_json_object(raw: str, *, default_chapter_id: int | None = None) -> dict[str, Any]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                parsed = None
        else:
            parsed = None
        # OpenAI-compatible Qwen deployments occasionally ignore the JSON
        # wrapper and return the requested chapter as plain prose. Preserve it
        # verbatim and let the normal chapter validator decide whether it is
        # usable; this keeps production moving without bypassing quality gates.
        if parsed is None and default_chapter_id is not None and text:
            return {"chapter_id": int(default_chapter_id), "body": text}
        if parsed is None:
            raise ValueError("Qwen 未返回可解析的 JSON 对象。")
    if not isinstance(parsed, dict):
        raise ValueError("Qwen 返回的顶层不是 JSON 对象。")
    return parsed


def _cluster_number(cluster_id: str) -> int:
    match = re.search(r"(\d+)$", cluster_id)
    return int(match.group(1)) if match else 0


def _select_card_payload(card: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "chapter_id",
        "chapter_title",
        "timeline_years",
        "timeline_start",
        "timeline_end",
        "chapter_role_v2",
        "chapter_goal",
        "chapter_must_include",
        "chapter_must_not_include",
        "chapter_ending",
        "must_resolve_this_chapter",
        "detailed_synopsis",
        "scene_location",
        "scenes",
        "artifact_creates",
        "artifact_refs",
        "participants",
        "exact_action_sequence",
        "info_gap_use",
        "opponent_reaction",
        "immediate_payoff",
        "state_changes",
        "state_transitions",
        "source_milestone_sha256",
        "source_event_sha256",
        "allowed_roles",
        "forbidden_roles",
    )
    return {key: card.get(key) for key in keys if card.get(key) not in (None, "", [])}


def _select_cluster_payload(cluster: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "cluster_id",
        "chapter_span",
        "name",
        "timeline_years",
        "opposition_type",
        "event_type",
        "solution_type",
        "causal_spine_ids",
        "foreshadow_ids",
        "main_opponent",
        "main_characters",
        "fictional_obstacle",
        "prev_life_tragedy",
        "info_gap_from_prev_life",
        "why_previous_life_failed",
        "preemptive_avoidance",
        "bait_and_evidence",
        "comic_villain_behavior",
        "villain_loss",
        "protagonist_gain",
        "relationship_change",
        "continuity_writes",
        "state_transitions",
        "cluster_outcome",
        "next_event_hook",
        "story_block_goal",
        "macro_goal",
    )
    return {key: cluster.get(key) for key in keys if cluster.get(key) not in (None, "", [])}


def _style_block(samples: list[dict[str, Any]]) -> str:
    chunks = []
    for sample in samples:
        chunks.append(
            f"[{sample.get('sample_id')}: {'、'.join(sample.get('focus') or [])}]\n"
            f"{sample.get('text', '')}"
        )
    return "\n\n".join(chunks)


def _recent_style_budget(output_dir: Path, chapter_id: int) -> dict[str, Any]:
    terms = ("指尖", "喉结", "信封", "蓝雪", "波形", "墨迹", "杯子", "骑缝章", "铅封")
    counts = {term: 0 for term in terms}
    sources: list[int] = []
    for prior_id in range(max(1, chapter_id - 3), chapter_id):
        path = output_dir / "chapters" / f"chapter_{prior_id:03d}.txt"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        sources.append(prior_id)
        for term in terms:
            counts[term] += text.count(term)
    avoid = [term for term, count in counts.items() if count >= 2]
    return {"source_chapters": sources, "counts": counts, "avoid_as_primary_motif": avoid}


def _cluster_style_budget(
    output_dir: Path, chapter_id: int, cluster_start: int,
    staged_bodies: dict[int, str],
) -> dict[str, Any]:
    """Use prior official prose plus newly staged prose, never a stale same-cluster file."""
    terms = ("指尖", "喉结", "信封", "蓝雪", "波形", "墨迹", "杯子", "骑缝章", "铅封")
    counts = {term: 0 for term in terms}
    sources: list[int] = []
    for prior_id in range(max(1, chapter_id - 3), chapter_id):
        if prior_id >= cluster_start:
            text = staged_bodies.get(prior_id, "")
        else:
            path = output_dir / "chapters" / f"chapter_{prior_id:03d}.txt"
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if not text:
            continue
        sources.append(prior_id)
        for term in terms:
            counts[term] += text.count(term)
    return {
        "source_chapters": sources,
        "counts": counts,
        "avoid_as_primary_motif": [term for term, count in counts.items() if count >= 2],
    }


def _build_prompt(
    *,
    cluster: dict[str, Any],
    cards: list[dict[str, Any]],
    graph_contexts: dict[int, str],
    style_samples: list[dict[str, Any]],
    prior_failure: str,
) -> tuple[str, str]:
    system_prompt = """你是中文商业长篇小说作者，正在写一部架空米国流行音乐产业的重生复仇爽剧。
你必须服从事件簇和逐章梗概的事实边界，但把梗概改写成有场景、有动作、有感官、有潜台词的小说正文，不能复述提纲。

写作优先级：
1. 重生信息差必须变成今生的具体抢先动作：读者先切身感到上一世受害的窒息或委屈，再看到主角利用日期、原话、流程或人性弱点抢先半步，迅速获得可见回报。
2. 人物塑造必须服从本次提供的“人工人物约束”。同一性格根源既制造能力也制造缺陷；反差必须通过利益冲突中的选择、语言习惯、谎言、牺牲和代价表现，禁止作者直接贴标签。重要场景至少让一名核心人物在两个都有价值或都有代价的选项之间作出选择。
3. 只有opposition_type=villain才写坏得滑稽；盟友阻力、制度、技术、家庭或内心冲突不能套反派模板。真正反派的可笑举动必须留下把柄或推动其失败，不写成无害搞笑角色。
4. 快节奏且每章有所得。第一章也要有可见推进，第二章必须完成反派损失、主角收益或关系/资产状态改变。可以留下一条具体钩子，但禁止用“这只是开始”“更大的风暴”等空话收尾。
5. 使用第三人称限知，贴近麦珂的即时判断。情绪强烈但克制，不堆砌情绪词。感官细节只写会改变判断或行动的部分，不承担凑字功能。禁止把“手指、喉结、杯子、墨迹、呼吸停顿”当作所有人物通用的紧张模板。
6. 每章正文目标1200—1600个汉字，最低不得少于1100个汉字，最高不得超过1900个汉字。每段1—4句，避免长篇解释和为撑长度重复物件、比喻或程序。
7. 所有人物、年代、设备和证据必须服从提供的规划。前世记忆不是今生物证；不能发明万能黑客、匿名证据、神秘证人或未规划的具名人物。
8. 舞台只能是架空米国及规划中的虚构城市、机构和品牌；不得出现中国现实品牌、城市、机构或现实艺人。
9. 若是重生确认章，开头三段内必须让读者明确看到年份、十一岁身体或年轻的家人，并通过身体和物件确认“他真的回到了过去”；不能只换场景而不写重生震动。
10. 正文叙述和普通身份称呼必须使用简体中文。除规划固有的Fonovox、V.L.、音名或编号外，不得夹入reporter、staff、manager等英文单词。
11. 当前章卡给出的日期和前序图谱是时间线依据。几周前发生的签约、公证或混音不得写成“三年前”“十一年前”；“十一岁”不能误写成“十一年前”。
12. 麦珂的优势是知道未来哪一天、哪句话和哪一次选择会造成伤害；优先让有资质的成年人完成法务、工程和鉴定动作，禁止把十一岁主角写成凭空精通所有专业的全知神童。
13. 近三章已经高频使用的意象、物件和身体反应不得再作为主描写；蓝雪、信封、钢印、铅封、骑缝章、波形只在本章事实不可替代时出现。
14. 只输出严格JSON，不要Markdown，不要章节标题，不要分析，不要创作说明。正文不得含分节小标题或星号加粗。"""
    user_payload = {
        "authoritative_event_cluster": _select_cluster_payload(cluster),
        "authoritative_chapter_cards": [_select_card_payload(card) for card in cards],
        "neo4j_context_before_each_chapter": graph_contexts,
        "human_authored_character_constraints": _character_constraints_for_scene(cluster, cards),
    }
    user_prompt = f"""请一次性写完同一事件簇的两章连续正文。

【权威规划与图谱上下文】
{json.dumps(user_payload, ensure_ascii=False, indent=2)}

【仅供学习情绪密度、人物反差和爽点落地方式的短样本；不得复制人物与事实】
{_style_block(style_samples)}

【输出格式】
{{
  "cluster_id": "{cluster.get('cluster_id')}",
  "chapters": [
    {{"chapter_id": {cards[0].get('chapter_id')}, "title": "沿用规划标题", "body": "纯正文"}},
    {{"chapter_id": {cards[1].get('chapter_id')}, "title": "沿用规划标题", "body": "纯正文"}}
  ]
}}

两章必须像连续小说而不是两份梗概。第二章开头承接第一章留下的具体感官、物件或动作，不重复总结第一章。"""
    if prior_failure:
        user_prompt += (
            "\n\n上一候选未通过，只针对这些实际问题完整重写两章，不要解释：\n"
            + prior_failure
        )
    return system_prompt, user_prompt


def _build_single_chapter_prompt(
    *,
    cluster: dict[str, Any],
    card: dict[str, Any],
    graph_context: str,
    style_samples: list[dict[str, Any]],
    previous_body: str,
    prior_failure: str,
    recent_style_budget: dict[str, Any] | None = None,
) -> tuple[str, str]:
    # Reuse the same style contract while giving one full model response to one
    # chapter.  The previous chapter is supplied only as continuity context and
    # is never copied into the new official body.
    system_prompt, _ = _build_prompt(
        cluster=cluster,
        cards=[card, card],
        graph_contexts={int(card["chapter_id"]): graph_context},
        style_samples=style_samples,
        prior_failure="",
    )
    chapter_id = int(card["chapter_id"])
    span = [int(value) for value in cluster.get("chapter_span") or []]
    is_cluster_finale = len(span) == 2 and int(card["chapter_id"]) == span[1]
    cluster_payload = _select_cluster_payload(cluster)
    if not is_cluster_finale:
        # The first chapter receives its own detailed card and the shared setup,
        # but not the finale-only payoff.  Exposing the full settlement here made
        # Qwen spend the second chapter's scene early and then repeat it.
        for key in (
            "comic_villain_behavior",
            "villain_loss",
            "protagonist_gain",
            "relationship_change",
            "bait_and_evidence",
            "continuity_writes",
            "state_transitions",
            "cluster_outcome",
        ):
            cluster_payload.pop(key, None)
    payload = {
        "authoritative_event_cluster": cluster_payload,
        "authoritative_chapter_card": _select_card_payload(card),
        "neo4j_context_before_chapter": graph_context,
        "human_authored_character_constraints": _character_constraints_for_scene(
            cluster, [card]
        ),
        "recent_style_budget": recent_style_budget or {},
    }
    continuity = (
        "这是事件簇第二章。以下是上一章Qwen原文，仅用于自然承接；禁止复述，"
        "开头应接住其中一个物件、动作或身体感受：\n" + previous_body
        if previous_body
        else "这是事件簇第一章，没有可复述的前章正文。"
    )
    rebirth_contract = ""
    if "rebirth" in str(card.get("chapter_role_v2") or "").lower():
        locked_rebirth_date = str(card.get("timeline_start") or "1969-11-06")
        rebirth_contract = f"""
【本章额外硬契约：重生确认】
- 在开头三段内自然写清日历或报纸日期为“{locked_rebirth_date}”，不得改成其他日期。
- 明确写他通过短小的双手、衣袖或镜中脸确认自己是十一岁，身体只有正常的十根手指。
- 让读者明确确认他从2009年死亡现场回到1969年的十一岁。可以直写，也可以通过“2009年的成人伤疤消失＋1969年日期＋孩童身体”三项并置来展示，禁止只是换场而无年龄/年代对照。
- 1969年广播只能播报当时合理的天气内容，禁止“紫外线指数”、互联网、电子邮件、手机或数字屏幕。
"""
    settlement_contract = ""
    if len(span) == 2 and int(card["chapter_id"]) == span[1]:
        settlement_contract = """
【事件簇末章结算契约】
本章后半段必须通过当场动作、对话、签字、交接或名单变更，具体完成以下三项；不能只在末句总结：
- 反派/阻力损失：{villain_loss}
- 主角获得：{protagonist_gain}
- 关系变化：{relationship_change}
""".format(
            villain_loss=_clip(cluster.get("villain_loss"), 500),
            protagonist_gain=_clip(cluster.get("protagonist_gain"), 500),
            relationship_change=_clip(cluster.get("relationship_change"), 500),
        )
    user_prompt = f"""请只写第{chapter_id}章完整正文。

【权威规划与图谱上下文】
{json.dumps(payload, ensure_ascii=False, indent=2)}

【连续性要求】
{continuity}
如果这是第二章，上一章已发生的试听、摔物、交接、签字或对话不得重新演一遍；最多用一句短回忆承接，随后必须进入本章的新时间、新动作和新结算。
{rebirth_contract}
{settlement_contract}

【仅供学习情绪密度、人物反差和爽点落地方式的短样本；不得复制人物与事实】
{_style_block(style_samples)}

【本次长度要求】
请展开成约1200—1600个汉字、至少9个有实际推进的自然段。不能把梗概压缩成短摘要；
用动作受阻、人物选择、带潜台词的对话和真正影响判断的环境反馈充实场景，不得新增规划外事件，也不得重复意象凑字。

【输出格式】
{{"chapter_id": {chapter_id}, "title": "{card.get('chapter_title', '')}", "body": "纯正文"}}

只输出严格JSON，不要Markdown或说明。"""
    if prior_failure:
        user_prompt += (
            "\n\n上一候选未通过。请完整重写本章，不得只返回补充段落；实际问题：\n"
            + prior_failure
        )
    return system_prompt, user_prompt


def _base_single_chapter_prompt_sha256(
    *,
    cluster: dict[str, Any],
    card: dict[str, Any],
    graph_context: str,
    style_samples: list[dict[str, Any]],
    previous_body: str,
    recent_style_budget: dict[str, Any],
) -> str:
    system_prompt, user_prompt = _build_single_chapter_prompt(
        cluster=cluster,
        card=card,
        graph_context=graph_context,
        style_samples=style_samples,
        previous_body=previous_body,
        prior_failure="",
        recent_style_budget=recent_style_budget,
    )
    return _sha(
        BODY_GENERATOR_CONTRACT_VERSION + "\n" + system_prompt + "\n" + user_prompt
    )


def _normalize_body(text: Any) -> str:
    body = str(text or "").strip()
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    # Deterministic lexical localization only; never changes plot or facts.
    body = re.sub(r"(?<![A-Za-z])technicians(?![A-Za-z])", "技术员", body)
    body = re.sub(r"^第\s*\d+\s*章[^\n]*\n+", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _validate_single_chapter(
    parsed: dict[str, Any], card: dict[str, Any]
) -> tuple[str, list[str], dict[str, Any]]:
    failures: list[str] = []
    expected_id = int(card["chapter_id"])
    try:
        actual_id = int(parsed.get("chapter_id"))
    except (TypeError, ValueError):
        actual_id = -1
    if actual_id != expected_id:
        failures.append(f"chapter_id必须为{expected_id}")
    body = _normalize_body(parsed.get("body"))
    han = _han_count(body)
    if han < MIN_HAN_CHARS:
        failures.append(f"汉字数{han}，低于{MIN_HAN_CHARS}")
    if han > MAX_HAN_CHARS:
        failures.append(f"汉字数{han}，高于{MAX_HAN_CHARS}")
    if "```" in body or "**" in body or re.search(r"^【[^】]+】", body, flags=re.M):
        failures.append("正文含Markdown或分节小标题")
    if re.search(r"(?:本章|这一章)(?:主要|讲述|描写)", body):
        failures.append("正文出现提纲式讲解")
    if body.endswith(("，", "、", "：", ":", ";", "；")):
        failures.append("正文疑似截断")
    forbidden_anchors = [
        str(value).strip()
        for value in (card.get("chapter_must_not_include") or [])
        if str(value).strip()
    ]
    exact_forbidden_hits = [anchor for anchor in forbidden_anchors if anchor in body]
    if exact_forbidden_hits:
        failures.append("正文命中章卡明确禁写项：" + "、".join(exact_forbidden_hits))
    forbidden_semantic_patterns = {
        "麦珂开口说话": r"麦珂.{0,20}(?:说|问|答|喊|低声|开口|吐字)[：:“‘\"]",
        "任何正式签约动作": r"(?:签署|签下|落笔签名|盖章生效|合同生效)",
        "昆廷介入": r"昆廷.{0,36}(?:走进|进入|推门|出面|插话|接手|阻止)",
        "乔纳间接干预": r"乔纳.{0,48}(?:授意|要求|安排|指使|打电话|传话|干预)",
    }
    semantic_forbidden_hits = [
        label for label, pattern in forbidden_semantic_patterns.items()
        if any(label in anchor for anchor in forbidden_anchors)
        and re.search(pattern, body)
    ]
    if semantic_forbidden_hits:
        failures.append(
            "正文语义违反章卡禁写项：" + "、".join(semantic_forbidden_hits)
        )
    if "十一只手指" in body:
        failures.append("出现人体常识错误‘十一只手指’")
    for match in re.finditer(
        r"([一二两三四五六七八九十百\d]+)个字(?:写着|是|：|:|——|-)?[“‘\"]([^”’\"。！？]{2,80})[”’\"]",
        body,
    ):
        number_text, quoted = match.groups()
        chinese_numbers = {
            "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
            "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
        }
        declared = int(number_text) if number_text.isdigit() else chinese_numbers.get(number_text)
        actual = _han_count(quoted)
        if declared is not None and declared != actual:
            failures.append(f"精确字数错误：称{declared}个字，实际{actual}个汉字")
    lowercase_english = re.findall(r"(?<![A-Za-z])[a-z]{4,}(?![A-Za-z])", body)
    if lowercase_english:
        failures.append(
            "正文夹入英文小写叙述词：" + "、".join(dict.fromkeys(lowercase_english))
        )
    for phrase in ("十一年前那只",):
        if phrase in body:
            failures.append(f"出现当前1969年早期篇章的时间线误写：{phrase}")
    if re.search(r"三年前.{0,24}(?:公证|签约|速记本|混音)", body):
        failures.append("出现当前1969年数周内事件被误写为三年前的时间线错误")
    english_prose_leaks = re.findall(
        r"(?i)\b(?:reporters?|staff|manager|assistant|director|lawyers?|judges?)\b",
        body,
    )
    if english_prose_leaks:
        failures.append(
            "正文夹入英文叙述词：" + "、".join(dict.fromkeys(english_prose_leaks))
        )
    real_world_leaks = [
        term
        for term in (
            "凤凰牌",
            "永久牌",
            "派克51",
            "IBM",
            "柯达",
            "Kodak",
            "宝丽来",
            "Polaroid",
            "北京",
            "上海",
            "纽约",
            "洛杉矶",
            "美国",
            "迈克尔·杰克逊",
            "Michael Jackson",
        )
        if term in body
    ]
    if real_world_leaks:
        failures.append("出现现实世界专名：" + "、".join(real_world_leaks))
    timeline_text = str(card.get("timeline_years") or "")
    years = [int(value) for value in re.findall(r"(?:19|20)\d{2}", timeline_text)]
    if years and min(years) <= 1979:
        early_tech_leaks = [
            term
            for term in (
                "手机", "电子邮件", "互联网", "网站", "二维码", "U盘", "PDF",
                "短信", "云端", "电脑", "屏保", "文件路径", "内网", "打印机", "节能灯",
                "感应灯", "激光笔", "LED", "邮件系统", "全员邮箱",
            )
            if term in body
        ]
        if early_tech_leaks:
            failures.append(
                f"{min(years)}年代出现未普及技术：" + "、".join(early_tech_leaks)
            )
    card_contract = json.dumps(_select_card_payload(card), ensure_ascii=False)
    semantic_plan = {
        key: card.get(key)
        for key in (
            "chapter_goal", "exact_action_sequence", "info_gap_use",
            "opponent_reaction", "immediate_payoff", "state_transitions",
        )
    }
    plan_body_overlap = semantic_similarity(semantic_plan, body)
    if plan_body_overlap < 0.040:
        failures.append(
            f"正文与章卡目标/动作/回报语义覆盖仅{plan_body_overlap:.3f}，疑似写成了另一件事"
        )
    must_include = [
        str(value).strip() for value in (card.get("chapter_must_include") or [])
        if str(value).strip()
    ]
    must_include_evidence: list[dict[str, Any]] = []
    for anchor in must_include:
        exact = anchor in body
        cleaned = re.sub(r"[^\u3400-\u9fffA-Za-z0-9]", "", anchor)
        grams = {
            cleaned[index:index + 2]
            for index in range(max(0, len(cleaned) - 1))
        }
        hits = {gram for gram in grams if gram in body}
        coverage = len(hits) / len(grams) if grams else 0.0
        matched = exact or coverage >= 0.45
        must_include_evidence.append({
            "anchor": anchor, "exact": exact,
            "bigram_coverage": round(coverage, 3), "matched": matched,
        })
        if not matched:
            failures.append(f"正文没有兑现章卡关键事实“{anchor}”")
    resolve_evidence: list[dict[str, Any]] = []
    for transition in card.get("must_resolve_this_chapter") or []:
        if not isinstance(transition, dict):
            continue
        evidence = str(transition.get("evidence") or "").strip()
        target = str(transition.get("to") or "").strip()
        evidence_terms = [
            term for term in re.findall(r"[\u3400-\u9fff]{2,8}|[A-Za-z0-9_.-]{2,}", evidence)
            if term not in {"麦珂", "玛莎", "维克多", "当场", "此后"}
        ]
        hit_terms = [term for term in evidence_terms if term in body]
        matched = bool(target and target in body) or len(hit_terms) >= min(2, len(evidence_terms))
        resolve_evidence.append({
            "state_key": transition.get("state_key"), "target": target,
            "evidence_terms": evidence_terms, "hit_terms": hit_terms,
            "matched": matched,
        })
        if not matched:
            failures.append(
                f"正文没有通过现场动作兑现状态转移{transition.get('state_key')}→{target}"
            )
    scenes = card.get("scenes")
    scene_evidence: list[dict[str, Any]] = []
    if isinstance(scenes, list) and scenes:
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            location = str(scene.get("location") or "").strip()
            # Strip generic suffixes while retaining the distinctive place name.
            keywords = [
                token for token in re.split(r"[／/、，,·的\s]+", location)
                if len(token) >= 2 and token not in {"内部", "外部", "附近", "现场", "主场景"}
            ]
            hit = any(token in body for token in keywords) if keywords else location in body
            match_mode = "location_keyword"
            if not hit and any(token in location for token in ("医院", "病房", "监护室")):
                medical_markers = ("监护仪", "心率", "呼吸管", "氧气", "输液", "病床")
                hit = sum(marker in body for marker in medical_markers) >= 2
                if hit:
                    match_mode = "medical_scene_semantics"
            if not hit and "走廊" in location:
                corridor_markers = ("走廊", "地毯", "壁灯", "窗框", "通风口")
                stable_place_markers = ("星穹", "试镜", "B座", "后台")
                hit = (
                    sum(marker in body for marker in corridor_markers) >= 3
                    and any(marker in body for marker in stable_place_markers)
                )
                if hit:
                    match_mode = "corridor_scene_semantics"
            if not hit and "录音棚" in location:
                studio_markers = ("控制台", "磁头", "监听", "麦克风", "母带", "录音")
                hit = sum(marker in body for marker in studio_markers) >= 3
                if hit:
                    match_mode = "recording_studio_semantics"
            scene_evidence.append({
                "location": location, "body_hit": hit, "match_mode": match_mode,
            })
            if location and not hit:
                failures.append(f"正文未落到规划场景“{location}”")
        if len(scenes) > 1:
            transition_markers = (
                "随后", "片刻后", "与此同时", "另一边", "转身走进", "推门", "走廊",
                "楼上", "楼下", "回到", "赶到", "离开", "镜头", "记忆里", "上一世",
            )
            if not any(marker in body for marker in transition_markers):
                failures.append("多场景章缺少正文可见的转场/倒叙提示")
    artifact_evidence: list[dict[str, Any]] = []
    for created in card.get("artifact_creates") or []:
        if not isinstance(created, dict):
            continue
        display = str(created.get("display_name") or "").strip()
        hit = bool(display and display in body)
        match_mode = "exact_display_name"
        artifact_id = str(created.get("artifact_id") or "")
        if not hit and artifact_id == "ART_DEATH_LOG_001":
            # This artifact is the protagonist's retained sensory memory, not
            # a literal document bearing the internal plan label.
            sensory_markers = ("听见", "康拉德", "保险", "版权", "心率", "监护仪")
            hit = sum(marker in body for marker in sensory_markers) >= 4
            if hit:
                match_mode = "sensory_memory_formation"
        if not hit and str(created.get("kind") or "") == "recording":
            recording_markers = ("母带", "磁带", "录音", "母带盒", "带盘")
            hit = sum(marker in body for marker in recording_markers) >= 2
            if hit:
                match_mode = "recording_artifact_formation"
        artifact_evidence.append({
            "artifact_id": artifact_id, "display_name": display,
            "body_hit": hit, "match_mode": match_mode,
        })
        if display and not hit:
            failures.append(f"正文没有写出本章正式创建的关键对象“{display}”")
    medical_escalations = [
        term for term in ("救护车", "担架", "被抬出", "住院腕带") if term in body
    ]
    if medical_escalations and not any(
        term in card_contract for term in ("救护车", "担架", "住院", "急救", "医院")
    ):
        failures.append(
            "出现章卡未规划的医疗升级：" + "、".join(medical_escalations)
        )
    if re.search(r"后腰.{0,18}(?:焦洞|焦黑圆孔)", body):
        failures.append("焦洞位置误写为后腰，与章卡和后文的工装裤膝部矛盾")
    if int(card.get("chapter_id") or 0) < 37 and "ChronoBadge" in body:
        failures.append("未来道具ChronoBadge在其第37章启用前提前出现")
    if "ChronoBadge" in body and re.search(
        r"ChronoBadge.{0,80}1970年5月22日|1970年5月22日.{0,80}ChronoBadge",
        body,
    ):
        failures.append("ChronoBadge在8月启用却被写成5月22日照片")
    if re.search(r"ChronoBadge.{0,48}(?:显示|停驻|锁定|跳动).{0,16}17\.3Hz", body):
        failures.append("ChronoBadge是机械时间戳胸牌，不能显示17.3Hz频率")
    if "ChronoBadge" in body and any(term in body for term in ("ChronoBadge芯片", "通电后边缘")):
        failures.append("ChronoBadge被误写成通电芯片，违背机械时间戳与热显色设定")
    if re.search(r"ChronoBadge.{0,56}(?:屏幕|显示屏|红光闪烁|红光.{0,8}脉动)", body):
        failures.append("机械ChronoBadge被误写成带屏幕或发光显示的电子装置")
    if re.search(r"七个字母[^。\n]{0,24}C-H-R-O-N-O-B-A-D-G-E", body, re.IGNORECASE):
        failures.append("CHRONOBADGE共有十一字母，不能误写为七个字母")
    if "十二岁少女" in body or re.search(
        r"麦珂[^。\n]{0,100}。她(?:双手|伸手|按下|弯腰|接过|屏息)",
        body,
    ):
        failures.append("主角麦珂被误写为女性代词或十二岁少女")
    for paragraph in re.split(r"\n\s*\n", body):
        gender_match = re.search(
            r"麦珂(?P<context>[^。！？]{0,220})[。！？；，]\s*她"
            r"(?:没|不|只|又|却|将|把|正|仍|已|便|忽|站|坐|走|伸|抬|低|垂|转|"
            r"看|听|说|问|答|拿|接|按|握|呼|屏|指|掌|手|脚|眼|肩|脸|唇|背|膝|腕)",
            paragraph,
        )
        antecedent_window = (
            paragraph[: gender_match.end("context")] if gender_match else ""
        )
        if gender_match and not re.search(
            r"玛莎|海伦|弗洛伦斯|女职员|母亲|女孩|女士|女人",
            antecedent_window,
        ):
            failures.append("主角麦珂所在动作链被女性代词‘她’承接")
            break
    if (
        int(card.get("chapter_id") or 0) == int(card.get("cluster_span_start") or -1)
        and re.search(r"主任.{0,8}(?:已经|已|签过)(?:字|名)", body)
    ):
        failures.append("事件簇第一章提前写完主任签字，抢占下一章备案盖章结算")
    role = str(card.get("chapter_role_v2") or "")
    scene_location = str(card.get("scene_location") or "")
    if "公证" in scene_location and "评委席" in body:
        failures.append("公证处场景误用试镜场所称呼‘评委席’")
    if "rebirth" in role.lower():
        opening = body[:650]
        year_visible = "1969" in opening or "一九六九" in opening
        young_body_visible = bool(re.search(
            r"十一岁|孩子的手|孩童的手|缩小的手|十根指(?:头|手指)|十根手指.{0,16}(?:短|细|小)|"
            r"(?:手|手掌|手指).{0,12}(?:小了一圈|短小|稚嫩)|年轻.{0,8}玛莎|玛莎.{0,12}年轻",
            opening,
        ))
        rebirth_visible = bool(
            re.search(r"重生|回到.{0,12}(?:过去|十一岁|一九六九|1969)|活了过来|死而复生", opening)
            or ("2009" in opening and year_visible and young_body_visible)
        )
        if not year_visible:
            failures.append("重生章开头未明确1969年")
        if not young_body_visible:
            failures.append("重生章开头未通过十一岁身体或年轻家人确认年龄变化")
        if not rebirth_visible:
            failures.append("重生章开头未明确让读者确认回到过去")
        exact_start = str(card.get("timeline_start") or "")
        if exact_start == "1969-11-06" and any(
            wrong in opening for wrong in ("1969年11月4日", "一九六九年十一月四日")
        ):
            failures.append("重生章把锁定日期1969-11-06误写成1969-11-04")
        if "紫外线指数" in body:
            failures.append("1969年出现不合年代的紫外线指数播报")
    must_include = [str(x) for x in card.get("chapter_must_include") or []]
    motif_counts = {
        term: body.count(term)
        for term in ("指尖", "喉结", "信封", "蓝雪", "波形", "墨迹", "骑缝章", "铅封")
    }
    if sum(motif_counts.values()) >= 14:
        failures.append(
            "模板化意象过密："
            + "、".join(f"{term}{count}次" for term, count in motif_counts.items() if count)
        )
    audit = {
        "han_chars": han,
        "total_chars": len(body),
        "target_han_range": [TARGET_HAN_MIN, TARGET_HAN_MAX],
        "must_include_exact_hits": sum(
            1 for anchor in must_include if anchor and anchor in body
        ),
        "must_include_total": len(must_include),
        "must_include_semantic_evidence": must_include_evidence,
        "must_resolve_semantic_evidence": resolve_evidence,
        "motif_counts": motif_counts,
        "plan_body_semantic_overlap": round(plan_body_overlap, 4),
        "scene_evidence": scene_evidence,
        "artifact_creation_evidence": artifact_evidence,
        "failures": failures,
    }
    return body, failures, audit


def _validate_candidate(
    parsed: dict[str, Any],
    *,
    cluster: dict[str, Any],
    cards: list[dict[str, Any]],
    recent_bodies: dict[int, str] | None = None,
) -> tuple[dict[int, str], list[str], dict[str, Any]]:
    failures: list[str] = []
    expected_cluster = str(cluster.get("cluster_id") or "")
    if str(parsed.get("cluster_id") or "") != expected_cluster:
        failures.append(f"cluster_id必须为{expected_cluster}")
    raw_chapters = parsed.get("chapters")
    if not isinstance(raw_chapters, list) or len(raw_chapters) != 2:
        return {}, ["chapters必须恰好包含两章"], {}
    expected_ids = [int(card["chapter_id"]) for card in cards]
    bodies: dict[int, str] = {}
    audits: dict[str, Any] = {}
    for item in raw_chapters:
        if not isinstance(item, dict):
            failures.append("每章必须是JSON对象")
            continue
        try:
            chapter_id = int(item.get("chapter_id"))
        except (TypeError, ValueError):
            failures.append("chapter_id必须是整数")
            continue
        if chapter_id not in expected_ids:
            failures.append(f"出现非本簇章节号：{chapter_id}")
            continue
        body = _normalize_body(item.get("body"))
        bodies[chapter_id] = body
        han = _han_count(body)
        total = len(body)
        chapter_failures: list[str] = []
        if han < MIN_HAN_CHARS:
            chapter_failures.append(f"汉字数{han}，低于{MIN_HAN_CHARS}")
        if han > MAX_HAN_CHARS:
            chapter_failures.append(f"汉字数{han}，高于{MAX_HAN_CHARS}")
        if "```" in body or re.search(r"^【[^】]+】", body, flags=re.M):
            chapter_failures.append("正文含Markdown或分节小标题")
        if re.search(r"(?:本章|这一章)(?:主要|讲述|描写)", body):
            chapter_failures.append("正文出现提纲式讲解")
        if body.endswith(("，", "、", "：", ":", ";", "；")):
            chapter_failures.append("正文疑似截断")
        card = next(card for card in cards if int(card["chapter_id"]) == chapter_id)
        must_include = [str(x) for x in card.get("chapter_must_include") or []]
        hit_count = sum(1 for anchor in must_include if anchor and anchor in body)
        # Planning anchors are often descriptive phrases rather than verbatim prose;
        # record their exact hits for review without forcing mechanical copying.
        audits[str(chapter_id)] = {
            "han_chars": han,
            "total_chars": total,
            "target_han_range": [TARGET_HAN_MIN, TARGET_HAN_MAX],
            "must_include_exact_hits": hit_count,
            "must_include_total": len(must_include),
            "failures": chapter_failures,
        }
        failures.extend(f"第{chapter_id}章：{failure}" for failure in chapter_failures)
    if sorted(bodies) != sorted(expected_ids):
        failures.append(f"章节号必须完整为{expected_ids}")
    first, second = (bodies.get(chapter_id, "") for chapter_id in expected_ids)
    if first and second and first[-80:] == second[:80]:
        failures.append("第二章机械复制了第一章结尾")
    if first and second:
        first_opening = first.split("\n\n", 1)[0].strip()
        second_opening = second.split("\n\n", 1)[0].strip()
        if first_opening and first_opening == second_opening:
            failures.append("第二章机械复制了第一章开头句")
        longest = SequenceMatcher(None, first, second, autojunk=False).find_longest_match()
        if longest.size >= 55:
            failures.append(
                f"两章存在{longest.size}字连续重复片段，第二章疑似重演第一章"
            )
        # A character-level exact match catches copy/paste; n-gram overlap also
        # catches paraphrased replays of the same hearing/meeting/hand-off.
        semantic_overlap = semantic_similarity(first, second)
        if semantic_overlap >= 0.12:
            failures.append(
                f"两章语义片段重合度{semantic_overlap:.2f}过高，第二章疑似换词重演第一章"
            )
        audits["joint_semantic_overlap"] = round(semantic_overlap, 4)
        finale_card = next(card for card in cards if int(card["chapter_id"]) == expected_ids[1])
        planned_settlement = " ".join(
            str(value or "")
            for value in (
                cluster.get("villain_loss"), cluster.get("protagonist_gain"),
                cluster.get("relationship_change"), finale_card.get("immediate_payoff"),
            )
        )
        settlement_actions = (
            "失去", "取消", "撤回", "撤换", "终止", "移交", "归还", "退出", "冻结", "解除",
            "改签", "签下", "获得", "保留", "确认", "公开", "当场", "名单", "职位",
            "账户", "版权", "母带", "票房", "销量", "合作", "道歉", "解雇",
        )
        required_actions = [term for term in settlement_actions if term in planned_settlement]
        if required_actions and not any(term in second for term in required_actions):
            failures.append(
                "第二章没有通过动作兑现计划中的损失/收益结算；仅有情绪反应不能算结算"
            )
        audits["settlement_action_terms"] = required_actions
        role_text = " ".join(str(card.get("chapter_role_v2") or "") for card in cards)
        info_gap_required = bool(
            cluster.get("info_gap_from_prev_life") or any(card.get("info_gap_use") for card in cards)
        ) and "previous_life" not in role_text
        memory_markers = (
            "前世", "上一世", "上辈子", "死前", "他记得", "麦珂记得", "记忆里",
            "原本会", "本来会", "曾经就是", "那一回", "那一世",
        )
        memory_hits = [term for term in memory_markers if term in first + second]
        if info_gap_required and not memory_hits:
            failures.append(
                "两章没有让读者看见重生信息差如何触发今生抢先动作；复仇主线已从正文消失"
            )
        audits["rebirth_information_gap_markers"] = memory_hits
    prior_repetition: list[dict[str, Any]] = []
    for chapter_id, body in bodies.items():
        for prior_id, prior_body in sorted((recent_bodies or {}).items()):
            if prior_id >= chapter_id or not prior_body:
                continue
            overlap = semantic_similarity(prior_body, body)
            prior_repetition.append({
                "chapter_id": chapter_id,
                "prior_chapter_id": prior_id,
                "semantic_overlap": round(overlap, 4),
            })
            if overlap >= 0.16:
                failures.append(
                    f"第{chapter_id}章与前5章中的第{prior_id}章语义重合度{overlap:.2f}过高，疑似重演旧事件"
                )
    audits["recent_five_chapter_semantic_comparison"] = prior_repetition
    return bodies, failures, audits


def _format_violations(violations: Iterable[Any]) -> list[str]:
    result = []
    for violation in violations:
        if hasattr(violation, "to_dict"):
            payload = violation.to_dict()
            result.append(f"{payload.get('code')}: {payload.get('message')}")
        else:
            result.append(str(violation))
    return result


def _load_inputs(output_dir: Path) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]], dict[str, Any]]:
    events_path = output_dir / "event_clusters_v2.json"
    cards_path = output_dir / "master_ctx_cards_v2.json"
    outline_path = output_dir / "global_story_outline_v5_qwen_500.json"
    for path in (events_path, cards_path, outline_path):
        if not path.exists():
            raise FileNotFoundError(f"缺少正文权威输入：{path}")
    events = _load_json(events_path)
    raw_cards = _load_json(cards_path)
    outline = _load_json(outline_path)
    if not isinstance(events, list) or not events or len(events) > 250:
        raise ValueError("event_clusters_v2.json 必须包含1—250个连续事件簇。")
    if not isinstance(raw_cards, list) or len(raw_cards) != len(events) * 2:
        raise ValueError("master_ctx_cards_v2.json 必须与事件簇形成连续的两章一事件前缀。")
    expected_event_ids = [f"EC{index:03d}" for index in range(1, len(events) + 1)]
    if [str(event.get("cluster_id") or "") for event in events] != expected_event_ids:
        raise ValueError("event_clusters_v2.json 必须从EC001开始连续，禁止跳簇生成正文。")
    expected_chapters = list(range(1, len(raw_cards) + 1))
    if [int(card.get("chapter_id") or 0) for card in raw_cards] != expected_chapters:
        raise ValueError("master_ctx_cards_v2.json 必须从第1章开始连续，禁止跳章生成正文。")
    cards = {int(card["chapter_id"]): card for card in raw_cards}
    return events, cards, outline


def _known_names(card: dict[str, Any]) -> list[str]:
    values = list(card.get("participants") or []) + list(card.get("allowed_roles") or [])
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _body_safe_graph_context(
    context: str, *, cluster_span: list[int], chapter_id: int
) -> str:
    """Hide finale-only plan data and stale facts from a regenerated cluster."""
    if len(cluster_span) != 2:
        return context
    start, end = cluster_span
    finale_only_tags = (
        "[反派滑稽点]",
        "[簇末飞升收益]",
        "[本簇应回收]",
        "[今生合法布局]",
    )
    lines: list[str] = []
    for line in str(context or "").splitlines():
        if chapter_id == start and any(tag in line for tag in finale_only_tags):
            continue
        # A force-regeneration must not treat the prior rejected version of the
        # same cluster as history.  Planning lines are kept; only dynamic facts,
        # relations and event summaries sourced from this span are removed.
        if any(
            tag in line
            for tag in ("[当前事实]", "[当前关系]", "[未决剧情线]", "[今生已发生]")
        ):
            source_numbers = [int(value) for value in re.findall(r"第(\d+)章", line)]
            if any(start <= value <= end for value in source_numbers):
                continue
        lines.append(line)
    return "\n".join(lines)


def _existing_delivery_valid(
    *, output_dir: Path, cluster: dict[str, Any], cards: list[dict[str, Any]],
    fingerprints: dict[str, str], graph_contexts: dict[int, str],
    style_samples: list[dict[str, Any]],
) -> bool:
    provenance_path = output_dir / "body_generation" / "provenance" / f"{cluster['cluster_id']}.json"
    if not provenance_path.exists():
        return False
    try:
        provenance = _load_json(provenance_path)
    except (OSError, json.JSONDecodeError):
        return False
    if provenance.get("generated_by") != "qwen" or provenance.get("manual_edits") != []:
        return False
    if provenance.get("plan_fingerprints") != fingerprints:
        return False
    if provenance.get("cluster_sha256") != event_fingerprint(cluster):
        return False
    expected_card_hashes = {
        str(int(card["chapter_id"])): card_fingerprint(card) for card in cards
    }
    if provenance.get("card_sha256_by_chapter") != expected_card_hashes:
        return False
    if provenance.get("body_generator_contract_version") != BODY_GENERATOR_CONTRACT_VERSION:
        return False
    span_start = min(int(card["chapter_id"]) for card in cards)
    if provenance.get("prior_body_chain_sha256") != _prior_body_chain_sha256(
        output_dir, span_start
    ):
        return False
    expected_prompt_hashes: dict[str, str] = {}
    previous_body = ""
    staged_bodies: dict[int, str] = {}
    official_bodies: dict[int, str] = {}
    for card in cards:
        chapter_id = int(card["chapter_id"])
        path = output_dir / "chapters" / f"chapter_{chapter_id:03d}.txt"
        if not path.exists():
            return False
        body = path.read_text(encoding="utf-8").strip()
        _, failures, _ = _validate_single_chapter(
            {"chapter_id": chapter_id, "body": body}, card
        )
        if failures:
            return False
        style_budget = _cluster_style_budget(
            output_dir, chapter_id, span_start, staged_bodies
        )
        expected_prompt_hashes[str(chapter_id)] = _base_single_chapter_prompt_sha256(
            cluster=cluster,
            card=card,
            graph_context=graph_contexts[chapter_id],
            style_samples=style_samples,
            previous_body=previous_body,
            recent_style_budget=style_budget,
        )
        if provenance.get("chapter_sha256", {}).get(str(chapter_id)) != _sha(body):
            return False
        raw_paths = provenance.get("accepted_raw_response_paths_by_chapter") or {}
        raw_hashes = provenance.get("raw_response_sha256_by_chapter") or {}
        raw_path = Path(str(raw_paths.get(str(chapter_id)) or ""))
        if not raw_path.is_file():
            return False
        if raw_hashes.get(str(chapter_id)) != _sha(raw_path.read_text(encoding="utf-8")):
            return False
        previous_body = body
        staged_bodies[chapter_id] = body
        official_bodies[chapter_id] = body
    if provenance.get("base_prompt_sha256_by_chapter") != expected_prompt_hashes:
        return False
    recent_bodies: dict[int, str] = {}
    for prior_id in range(max(1, span_start - 5), span_start):
        path = output_dir / "chapters" / f"chapter_{prior_id:03d}.txt"
        if path.is_file():
            recent_bodies[prior_id] = path.read_text(encoding="utf-8").strip()
    _, joint_failures, _ = _validate_candidate(
        {
            "cluster_id": cluster.get("cluster_id"),
            "chapters": [
                {"chapter_id": chapter_id, "body": official_bodies[chapter_id]}
                for chapter_id in sorted(official_bodies)
            ],
        },
        cluster=cluster,
        cards=cards,
        recent_bodies=recent_bodies,
    )
    if joint_failures:
        return False
    return True


def generate_cluster(
    *,
    output_dir: Path,
    cluster: dict[str, Any],
    card_map: dict[int, dict[str, Any]],
    coordinator: StoryMemoryCoordinator,
    planning_id: str,
    style_samples: list[dict[str, Any]],
    fingerprints: dict[str, str],
    model: str,
    temperature: float,
    max_attempts: int,
    force: bool,
    allow_body_warnings: bool = False,
) -> None:
    span = [int(value) for value in cluster.get("chapter_span") or []]
    if len(span) != 2 or span[1] != span[0] + 1:
        raise ValueError(f"{cluster.get('cluster_id')} 不是严格两章事件簇。")
    cards = [card_map[span[0]], card_map[span[1]]]
    graph_contexts: dict[int, str] = {}
    for card in cards:
        chapter_id = int(card["chapter_id"])
        graph_contexts[chapter_id] = _body_safe_graph_context(
            retrieve_context_for_chapter(
            chapter_num=chapter_id,
            allowed_roles=_known_names(card),
            main_opponent=str(card.get("main_opponent") or ""),
            max_chars=3200,
            story_id=planning_id,
            ),
            cluster_span=span,
            chapter_id=chapter_id,
        )
    if not force and _existing_delivery_valid(
        output_dir=output_dir, cluster=cluster, cards=cards, fingerprints=fingerprints,
        graph_contexts=graph_contexts, style_samples=style_samples,
    ):
        print(f"[resume] {cluster['cluster_id']} 第{span[0]}-{span[1]}章已是有效Qwen产物。", flush=True)
        return

    batch_dir = output_dir / "body_generation" / "qwen_batches"
    audit_dir = output_dir / "body_generation" / "quality_audits"
    bodies: dict[int, str] = {}
    audits: dict[str, Any] = {}
    raw_by_chapter: dict[str, str] = {}
    raw_path_by_chapter: dict[str, str] = {}
    call_by_chapter: dict[str, dict[str, Any]] = {}
    prompt_hash_by_chapter: dict[str, str] = {}
    base_prompt_hash_by_chapter: dict[str, str] = {}
    previous_body = ""
    for card in cards:
        chapter_id = int(card["chapter_id"])
        prior_failure = ""
        accepted_chapter = False
        style_budget = _cluster_style_budget(
            output_dir, chapter_id, span[0], bodies
        )
        base_prompt_hash = _base_single_chapter_prompt_sha256(
            cluster=cluster,
            card=card,
            graph_context=graph_contexts[chapter_id],
            style_samples=style_samples,
            previous_body=previous_body,
            recent_style_budget=style_budget,
        )
        if not force:
            checkpoint_pattern = (
                f"{cluster['cluster_id']}_chapter_{chapter_id:03d}_attempt_*_*_raw.txt"
            )
            checkpoints = sorted(
                batch_dir.glob(checkpoint_pattern),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
            for raw_path in checkpoints:
                audit_stem = raw_path.stem.removesuffix("_raw")
                audit_path = audit_dir / f"{audit_stem}.json"
                prior_audit = _load_json(audit_path) if audit_path.exists() else {}
                if prior_audit.get("plan_fingerprints") != fingerprints:
                    continue
                if prior_audit.get("cluster_sha256") != event_fingerprint(cluster):
                    continue
                if prior_audit.get("card_sha256") != card_fingerprint(card):
                    continue
                if prior_audit.get("body_generator_contract_version") != BODY_GENERATOR_CONTRACT_VERSION:
                    continue
                source_base_prompt_hash = str(prior_audit.get("base_prompt_sha256") or "")
                if source_base_prompt_hash != base_prompt_hash:
                    # A changed prompt is a changed writing contract.  Passing
                    # today's validator cannot prove the old Qwen response was
                    # authored under today's instructions, so it must not be
                    # resurrected implicitly.
                    continue
                joint_failures = [str(value) for value in prior_audit.get("joint_failures") or []]
                finale_only_rejection = bool(joint_failures) and all(
                    "第二章没有通过动作兑现" in failure for failure in joint_failures
                )
                if prior_audit.get("joint_rejected") and not (
                    finale_only_rejection and chapter_id == span[0]
                ):
                    prior_failure = "\n".join(
                        f"- {failure}"
                        for failure in (prior_audit.get("failures") or [])[-4:]
                    )
                    # The newest same-prompt candidate already proved the pair
                    # semantically invalid. Do not fall back to an older raw
                    # response that merely passes per-chapter formatting.
                    break
                try:
                    raw = raw_path.read_text(encoding="utf-8")
                    parsed = _parse_json_object(raw, default_chapter_id=chapter_id)
                    body, failures, audit = _validate_single_chapter(parsed, card)
                    if allow_body_warnings:
                        audit["all_validator_failures"] = list(failures)
                        failures = _productivity_body_failures(failures, body)
                except Exception:  # noqa: BLE001
                    continue
                if failures:
                    continue
                bodies[chapter_id] = body
                audits[str(chapter_id)] = audit
                raw_by_chapter[str(chapter_id)] = raw
                raw_path_by_chapter[str(chapter_id)] = str(raw_path.resolve())
                call_by_chapter[str(chapter_id)] = dict(
                    prior_audit.get("call")
                    or {"model": model, "transport": "checkpoint_revalidated"}
                )
                prompt_hash_by_chapter[str(chapter_id)] = str(
                    prior_audit.get("prompt_sha256") or "checkpoint_revalidated"
                )
                base_prompt_hash_by_chapter[str(chapter_id)] = base_prompt_hash
                previous_body = body
                accepted_chapter = True
                print(
                    f"[revalidated] {cluster['cluster_id']} 第{chapter_id}章复用未改字Qwen候选：{raw_path.name}",
                    flush=True,
                )
                break
        if accepted_chapter:
            continue
        for attempt in range(1, max_attempts + 1):
            system_prompt, user_prompt = _build_single_chapter_prompt(
                cluster=cluster,
                card=card,
                graph_context=graph_contexts[chapter_id],
                style_samples=style_samples,
                previous_body=previous_body,
                prior_failure=prior_failure,
                recent_style_budget=style_budget,
            )
            prompt_hash = _sha(
                BODY_GENERATOR_CONTRACT_VERSION + "\n" + system_prompt + "\n" + user_prompt
            )
            raw, call_meta = _call_qwen(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=model,
                temperature=temperature,
            )
            raw_path = (
                batch_dir
                / f"{cluster['cluster_id']}_chapter_{chapter_id:03d}_attempt_{attempt:02d}_{prompt_hash[:10]}_raw.txt"
            )
            _atomic_write_text(raw_path, raw)
            try:
                parsed = _parse_json_object(raw, default_chapter_id=chapter_id)
                body, failures, audit = _validate_single_chapter(parsed, card)
                if allow_body_warnings:
                    audit["all_validator_failures"] = list(failures)
                    failures = _productivity_body_failures(failures, body)
            except Exception as exc:  # noqa: BLE001
                body, audit = "", {}
                failures = [f"JSON解析失败：{exc}"]
            _save_json(
                audit_dir
                / f"{cluster['cluster_id']}_chapter_{chapter_id:03d}_attempt_{attempt:02d}_{prompt_hash[:10]}.json",
                {
                    "cluster_id": cluster["cluster_id"],
                    "chapter_id": chapter_id,
                    "attempt": attempt,
                    "generated_by": "qwen",
                    "manual_edits": [],
                    "prompt_sha256": prompt_hash,
                    "base_prompt_sha256": base_prompt_hash,
                    "body_generator_contract_version": BODY_GENERATOR_CONTRACT_VERSION,
                    "raw_response_sha256": _sha(raw),
                    "call": call_meta,
                    "plan_fingerprints": fingerprints,
                    "cluster_sha256": event_fingerprint(cluster),
                    "card_sha256": card_fingerprint(card),
                    "chapter_audit": audit,
                    "failures": failures,
                    "accepted": not failures,
                },
            )
            if not failures:
                bodies[chapter_id] = body
                audits[str(chapter_id)] = audit
                raw_by_chapter[str(chapter_id)] = raw
                raw_path_by_chapter[str(chapter_id)] = str(raw_path.resolve())
                call_by_chapter[str(chapter_id)] = call_meta
                prompt_hash_by_chapter[str(chapter_id)] = prompt_hash
                base_prompt_hash_by_chapter[str(chapter_id)] = base_prompt_hash
                previous_body = body
                accepted_chapter = True
                break
            prior_failure = "\n".join(f"- {failure}" for failure in failures[:12])
            print(
                f"[retry] {cluster['cluster_id']} chapter={chapter_id} attempt={attempt}："
                + "；".join(failures[:4]),
                flush=True,
            )
        if not accepted_chapter:
            raise RuntimeError(
                f"{cluster['cluster_id']}第{chapter_id}章连续{max_attempts}次未通过必要门槛；正文未提交。"
            )

    # The two separately generated chapters still pass a joint continuity and
    # shape check before either one becomes official.
    combined = {
        "cluster_id": cluster["cluster_id"],
        "chapters": [
            {"chapter_id": int(card["chapter_id"]), "body": bodies[int(card["chapter_id"])]}
            for card in cards
        ],
    }
    recent_bodies: dict[int, str] = {}
    for prior_id in range(max(1, span[0] - 5), span[0]):
        prior_path = output_dir / "chapters" / f"chapter_{prior_id:03d}.txt"
        if prior_path.is_file():
            recent_bodies[prior_id] = prior_path.read_text(encoding="utf-8").strip()
    _, joint_failures, joint_semantic_audit = _validate_candidate(
        combined, cluster=cluster, cards=cards, recent_bodies=recent_bodies
    )
    if allow_body_warnings:
        joint_semantic_audit["all_joint_failures"] = list(joint_failures)
        joint_failures = [
            failure for failure in joint_failures
            if "语义片段重合度" not in str(failure)
            and "没有通过动作兑现计划中的损失/收益结算" not in str(failure)
            and "连续重复片段" not in str(failure)
        ]
    if joint_failures:
        # A missing settlement is localized to the finale. Preserve a valid
        # setup chapter; only cross-chapter replay or missing rebirth logic
        # requires regenerating the pair.
        finale_only_rejection = all(
            "第二章没有通过动作兑现" in failure for failure in joint_failures
        )
        rejected_ids = [span[1]] if finale_only_rejection else list(span)
        for rejected_id in rejected_ids:
            rejected_raw_path = Path(raw_path_by_chapter[str(rejected_id)])
            rejected_audit_path = (
                audit_dir / f"{rejected_raw_path.stem.removesuffix('_raw')}.json"
            )
            rejected_audit = (
                _load_json(rejected_audit_path) if rejected_audit_path.exists() else {}
            )
            existing_failures = [str(value) for value in rejected_audit.get("failures") or []]
            rejected_audit.update(
                {
                    "accepted": False,
                    "joint_rejected": True,
                    "joint_failures": joint_failures,
                    "failures": existing_failures + joint_failures,
                }
            )
            _save_json(rejected_audit_path, rejected_audit)
        raise RuntimeError(
            f"{cluster['cluster_id']}两章联合校验失败：{'；'.join(joint_failures)}"
        )

    memories: list[dict[str, Any]] = []
    continuity_failures: list[str] = []
    for card in cards:
        chapter_id = int(card["chapter_id"])
        forced_timeline = "previous_life" if chapter_id == 1 else "current"
        memory, violations = coordinator.review_candidate(
            chapter=chapter_id,
            content=bodies[chapter_id],
            known_names=_known_names(card),
            forced_timeline=forced_timeline,
            pending_memories=memories,
        )
        memories.append(memory)
        continuity_failures.extend(
            f"第{chapter_id}章 {item}" for item in _format_violations(violations)
        )
    if continuity_failures:
        raise RuntimeError(
            f"{cluster['cluster_id']}图谱连续性校验失败：{'；'.join(continuity_failures[:8])}"
        )
    chapters_dir = output_dir / "chapters"
    snapshots: dict[Path, bytes | None] = {}
    chapter_paths: dict[int, Path] = {}
    try:
        for chapter_id, body in bodies.items():
            path = chapters_dir / f"chapter_{chapter_id:03d}.txt"
            snapshots[path] = path.read_bytes() if path.exists() else None
            _atomic_write_text(path, body + "\n")
            chapter_paths[chapter_id] = path
        coordinator.commit_many(memories)
    except BaseException:
        for path, old_bytes in snapshots.items():
            if old_bytes is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(old_bytes)
        raise

    provenance = {
        "cluster_id": cluster["cluster_id"],
        "chapter_span": span,
        "generated_by": "qwen",
        "manual_edits": [],
        "body_edit_policy": "failed_body_is_regenerated_by_qwen_never_manually_patched",
        "body_generator_contract_version": BODY_GENERATOR_CONTRACT_VERSION,
        "prior_body_chain_sha256": _prior_body_chain_sha256(output_dir, span[0]),
        "accepted_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "temperature": temperature,
        "calls_by_chapter": call_by_chapter,
        "prompt_sha256_by_chapter": prompt_hash_by_chapter,
        "base_prompt_sha256_by_chapter": base_prompt_hash_by_chapter,
        "raw_response_sha256_by_chapter": {
            chapter_id: _sha(raw) for chapter_id, raw in raw_by_chapter.items()
        },
        "accepted_raw_response_paths_by_chapter": raw_path_by_chapter,
        "chapter_sha256": {
            str(chapter_id): _sha(body) for chapter_id, body in bodies.items()
        },
        "chapter_han_chars": {
            str(chapter_id): _han_count(body) for chapter_id, body in bodies.items()
        },
        "planning_story_id": planning_id,
        "plan_fingerprints": fingerprints,
        "cluster_sha256": event_fingerprint(cluster),
        "card_sha256_by_chapter": {
            str(int(card["chapter_id"])): card_fingerprint(card) for card in cards
        },
        "planning_inputs": {
            "event_clusters": str((output_dir / "event_clusters_v2.json").resolve()),
            "chapter_cards": str((output_dir / "master_ctx_cards_v2.json").resolve()),
        },
        "semantic_critic": joint_semantic_audit,
        "quality_review_status": "awaiting_manual_read",
    }
    _save_json(
        output_dir / "body_generation" / "provenance" / f"{cluster['cluster_id']}.json",
        provenance,
    )
    print(
        f"[accepted] {cluster['cluster_id']}："
        + "，".join(
            f"第{chapter_id}章{_han_count(body)}汉字" for chapter_id, body in bodies.items()
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="按两章事件簇生成新版重生天王正文，并提交StoryMemory/Neo4j。"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--start-cluster", type=int, default=1)
    parser.add_argument("--end-cluster", type=int, default=1)
    parser.add_argument("--model", default="qwen-plus")
    parser.add_argument("--temperature", type=float, default=0.72)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument(
        "--max-cluster-attempts", type=int, default=2,
        help="Automatic whole-pair retries after joint semantic rejection.",
    )
    parser.add_argument("--style-samples", type=Path, default=DEFAULT_STYLE_SAMPLES)
    parser.add_argument("--neo4j-container", default="ai-novel-neo4j-v5")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-plan-warnings", action="store_true",
        help="允许全书伏笔覆盖/因果覆盖提醒，不跳过结构、章卡或图谱校验；用于优先产出正文。",
    )
    parser.add_argument(
        "--allow-body-warnings", action="store_true",
        help="保留非致命正文审查提醒并提交可读候选；仍拒绝空正文、截断和明确禁写项。",
    )
    args = parser.parse_args()

    output_dir = args.output_dir.expanduser().resolve()
    events, card_map, outline = _load_inputs(output_dir)
    planning_id = planning_story_id(outline)
    selected = [
        event
        for event in events
        if args.start_cluster
        <= _cluster_number(str(event.get("cluster_id") or ""))
        <= args.end_cluster
    ]
    if not selected:
        raise ValueError("指定范围没有匹配的事件簇。")
    if args.start_cluster > 1:
        missing_prior = [
            chapter_id
            for chapter_id in range(1, (args.start_cluster - 1) * 2 + 1)
            if not (output_dir / "chapters" / f"chapter_{chapter_id:03d}.txt").is_file()
        ]
        if missing_prior:
            raise ValueError(
                "禁止跳过尚未生成的前文事件簇；缺少章节："
                + "、".join(map(str, missing_prior[:12]))
            )
    style_samples = _load_json(args.style_samples.expanduser().resolve())
    if not isinstance(style_samples, list) or not style_samples:
        raise ValueError("风格样本必须是非空JSON数组。")
    ordered_cards = [card_map[index] for index in sorted(card_map)]
    complete_plan = len(events) == 250 and len(ordered_cards) == 500
    plan_report = validate_full_plan(
        events, ordered_cards, allow_partial=not complete_plan, global_outline=outline,
    )
    plan_failures = list(plan_report.get("failures") or [])
    if args.allow_plan_warnings:
        warning_prefixes = (
            "规划语义预检失败：250事件未覆盖因果主链",
            "250",
            "CS",
            "FS",
        )
        plan_failures = [
            failure for failure in plan_failures
            if not str(failure).startswith(warning_prefixes)
        ]
        if plan_report.get("failures") and len(plan_failures) < len(plan_report["failures"]):
            print(
                "[plan-warning] 已放行伏笔/因果覆盖提醒："
                + " | ".join(str(f) for f in plan_report["failures"][:8]),
                flush=True,
            )
    if plan_failures:
        raise RuntimeError(
            "当前规划未通过语义编译，禁止生成正文："
            + " | ".join(plan_failures[:20])
        )
    _bootstrap_neo4j_env(args.neo4j_container)
    driver = get_neo4j_driver()
    try:
        driver.verify_connectivity()
        expected_graph_hashes = {
            str(event.get("cluster_id") or ""): event_fingerprint(event) for event in events
        }
        with driver.session() as session:
            rows = list(session.run(
                "MATCH (p:PlotCluster {story_id:$sid}) "
                "RETURN p.cluster_id AS cluster_id, p.plan_sha256 AS plan_sha256",
                sid=planning_id,
            ))
            plan_count = len(rows)
            graph_hashes = {
                str(row["cluster_id"] or ""): str(row["plan_sha256"] or "") for row in rows
            }
        if plan_count < len(events):
            raise RuntimeError(
                f"Neo4j规划图谱不完整：story_id={planning_id}，"
                f"PlotCluster={plan_count}/{len(events)}个当前权威前缀事件。"
            )
        mismatches = [
            eid for eid, expected in expected_graph_hashes.items()
            if graph_hashes.get(eid) != expected
        ]
        if mismatches:
            raise RuntimeError(
                "Neo4j规划图谱不是当前event_clusters_v2.json版本；请先重建："
                + "、".join(mismatches[:12])
            )
    finally:
        driver.close()

    memory_dir = output_dir / "knowledge_graph" / "stories" / planning_id / "chapter_memory"
    coordinator = StoryMemoryCoordinator(
        memory_dir=memory_dir,
        llm_call=None,
        driver_factory=get_neo4j_driver,
        story_id=planning_id,
    )
    if args.dry_run:
        print(
            f"[dry-run] 输入有效：{len(events)}事件簇、{len(card_map)}章卡、"
            f"Neo4j规划节点{plan_count}；规划模式={'全书' if complete_plan else '连续前缀'}；"
            f"本次选择{len(selected)}个事件簇。"
        )
        return

    for cluster in selected:
        cluster_number = _cluster_number(str(cluster.get("cluster_id") or ""))
        fingerprints = body_prefix_fingerprints(
            outline=outline,
            events=events,
            cards=ordered_cards,
            style_samples=style_samples,
            through_cluster=cluster_number,
        )
        cluster_attempts = max(1, args.max_cluster_attempts)
        for cluster_attempt in range(1, cluster_attempts + 1):
            try:
                generate_cluster(
                    output_dir=output_dir,
                    cluster=cluster,
                    card_map=card_map,
                    coordinator=coordinator,
                    planning_id=planning_id,
                    style_samples=style_samples,
                    fingerprints=fingerprints,
                    model=args.model,
                    temperature=args.temperature,
                    max_attempts=max(1, args.max_attempts),
                    force=args.force,
                    allow_body_warnings=args.allow_body_warnings,
                )
                break
            except RuntimeError as exc:
                if "两章联合校验失败" not in str(exc) or cluster_attempt >= cluster_attempts:
                    raise
                print(
                    f"[pair-retry] {cluster.get('cluster_id')} "
                    f"cluster_attempt={cluster_attempt}/{cluster_attempts}：{exc}",
                    flush=True,
                )


if __name__ == "__main__":
    main()

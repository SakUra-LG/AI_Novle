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
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import dashscope

API_Key_QW = os.getenv("DASHSCOPE_API_KEY", "").strip()
from bert_excitation_train.scripts.knowledge_graph.common import get_neo4j_driver
from bert_excitation_train.scripts.knowledge_graph.online_retriever import (
    retrieve_context_for_chapter,
)
from bert_excitation_train.scripts.knowledge_graph.planning_graph import planning_story_id
from bert_excitation_train.scripts.knowledge_graph.story_memory import StoryMemoryCoordinator
from bert_excitation_train.scripts.novel_generation_v2.qwen_transport import (
    call_openai_compatible_via_curl,
    call_qwen_via_curl,
)
from bert_excitation_train.scripts.novel_generation_v2.pop_king_plan_compiler import (
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
DEFAULT_CHARACTER_LIFECYCLE = (
    PROJECT_ROOT / "bert_excitation_train" / "data" / "pop_king_character_lifecycle_v1.json"
)
MIN_HAN_CHARS = 1000
TARGET_HAN_MIN = 1200
TARGET_HAN_MAX = 1600
# User-approved delivery range: retain complete scenes up to 2,000 Han
# characters instead of rejecting otherwise valid slightly-long candidates.
MAX_HAN_CHARS = 2000
BODY_GENERATOR_CONTRACT_VERSION = "v13_compiled_plan_strict_gates_20260822"
WORLD_RULES_PATH = Path(__file__).with_name("pop_king_world_rules_v1.json")
_CHARACTER_BIBLE_CACHE: dict[str, Any] | None = None
_WORLD_RULES_CACHE: dict[str, Any] | None = None
_CHARACTER_LIFECYCLE_CACHE: dict[str, Any] | None = None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_world_rules() -> dict[str, Any]:
    global _WORLD_RULES_CACHE
    if _WORLD_RULES_CACHE is None:
        _WORLD_RULES_CACHE = _load_json(WORLD_RULES_PATH)
    return _WORLD_RULES_CACHE


def _load_character_lifecycle(path: Path = DEFAULT_CHARACTER_LIFECYCLE) -> dict[str, Any]:
    global _CHARACTER_LIFECYCLE_CACHE
    if _CHARACTER_LIFECYCLE_CACHE is None:
        _CHARACTER_LIFECYCLE_CACHE = _load_json(path)
    return _CHARACTER_LIFECYCLE_CACHE


def _protagonist_age(card: dict[str, Any]) -> int:
    """Calculate age from a calendar date when available, not only a year."""
    birth = _load_character_lifecycle().get("protagonist") or {}
    birth_year = int(birth.get("birth_year") or 1958)
    birth_month, birth_day = 8, 29
    birth_date = str(birth.get("birth_date") or "")
    birth_match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", birth_date)
    if birth_match:
        birth_month, birth_day = int(birth_match.group(2)), int(birth_match.group(3))
    raw = str(card.get("timeline_start") or card.get("timeline_years") or "")
    date_match = re.search(r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})", raw)
    year_match = re.search(r"(\d{4})", raw)
    year = int(date_match.group(1) if date_match else year_match.group(1)) if (date_match or year_match) else birth_year
    age = year - birth_year
    if date_match and (int(date_match.group(2)), int(date_match.group(3))) < (birth_month, birth_day):
        age -= 1
    return age


def _age_semantic_conflicts(card: dict[str, Any]) -> list[str]:
    age = _protagonist_age(card)
    if age < 18:
        return []
    fields: list[tuple[str, str]] = []
    for key in ("chapter_goal", "detailed_synopsis", "exact_action_sequence", "state_transitions", "artifact_creates", "artifact_refs", "chapter_must_include"):
        fields.append((key, str(card.get(key) or "")))
    forbidden = {
        "未成年人": "adult chapter still uses minor status",
        "监护权": "adult chapter still uses guardianship",
        "监护人": "adult chapter still uses guardian role",
        "童星": "adult chapter still uses child-star identity",
        "儿童表演许可": "adult chapter still uses child performance permission",
        "父母替他签": "adult chapter still lets parents sign in his place",
        "母亲替他签": "adult chapter still lets mother sign in his place",
    }
    failures: list[str] = []
    flashback = re.compile(r"回忆|前世|上一世|1969(?:年|-)|previous_life|flashback", re.I)
    current_year = int(re.search(r"(\d{4})", str(card.get("timeline_start") or card.get("timeline_years") or "0000")).group(1))
    for token, message in forbidden.items():
        for field, text in fields:
            for match in re.finditer(re.escape(token), text):
                nearby = text[max(0, match.start() - 100):match.end() + 100]
                historical_years = [int(value) for value in re.findall(r"(?:19|20)\d{2}", nearby)]
                historical_context = any(year < current_year for year in historical_years)
                legal_history = token in {"未成年人", "童星"} and bool(re.search(r"权益保护法|原合同|摆脱|曾经|旧约|童年", nearby))
                protagonist_nearby = bool(re.search(r"麦珂.{0,70}" + re.escape(token) + r"|" + re.escape(token) + r".{0,70}麦珂", nearby))
                if protagonist_nearby and not flashback.search(nearby) and not historical_context and not legal_history:
                    failures.append(f"AGE_SEMANTIC_CONFLICT: {field}: {message}")
                    break
    return list(dict.fromkeys(failures))


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


def _chinese_number_0_59(value: int) -> str:
    """Render a clock component so 19:42 matches 十九点四十二分 in prose."""
    digits = "零一二三四五六七八九"
    if not 0 <= value <= 59:
        return str(value)
    if value < 10:
        return digits[value]
    tens, units = divmod(value, 10)
    prefix = "十" if tens == 1 else digits[tens] + "十"
    return prefix if units == 0 else prefix + digits[units]


def _clock_variants(text: str) -> list[str]:
    variants: list[str] = []
    for match in re.finditer(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", text or ""):
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            variants.append(
                f"{_chinese_number_0_59(hour)}点{_chinese_number_0_59(minute)}分"
            )
    return variants


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
    # Quality gates are intentionally closed: a readable candidate is not an
    # accepted candidate when it violates continuity, identity, metadata, or
    # repetition rules. Warnings may still be recorded by callers, but may not
    # be silently downgraded here.
    return list(failures)


def _hard_metadata_leak_failures(body: str) -> list[str]:
    patterns = (
        r"ART_[A-Z0-9_-]+",
        r"__extension_EC\d+",
        r"\b[a-z]+(?:_[a-z0-9]+){2,}\b",
        r"正式创建对象",
        r"状态字段",
        r"状态由.{0,20}转为.{0,20}",
        r"依据为.{0,40}",
    )
    hits = [pattern for pattern in patterns if re.search(pattern, body)]
    return ["正文元数据泄漏：" + "、".join(hits)] if hits else []


def _paragraph_quality_failures(body: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    failures: list[str] = []
    if len(paragraphs) < 7 or len(paragraphs) > 18:
        failures.append(f"有效段落数{len(paragraphs)}不在7—18范围")
    if any(_han_count(p) > 260 for p in paragraphs):
        failures.append("存在汉字数超过260的超长段落")
    seen: set[str] = set()
    for paragraph in paragraphs:
        if paragraph in seen:
            failures.append("同章存在完全重复段落")
        seen.add(paragraph)
    for index, left in enumerate(paragraphs):
        for right in paragraphs[index + 1:]:
            if semantic_similarity(left, right) >= 0.82:
                failures.append("同章存在语义相似度≥0.82的重复段落")
                break
        if failures and failures[-1].startswith("同章存在语义"):
            break
    if re.search(r"(?:程序结束|归档完毕|档案留存|补录(?:文字)?)[。！!；;]?\s*$", body):
        failures.append("章末出现填充或泛化归档套话")
    return failures


def _character_identity_failures(body: str, card: dict[str, Any]) -> list[str]:
    bible = _load_character_bible()
    profiles = [p for p in bible.get("characters", []) if isinstance(p, dict)]
    name_to_id = {}
    for profile in profiles:
        cid = str(profile.get("character_id") or "")
        for name in [profile.get("name"), *(profile.get("aliases") or [])]:
            if name:
                name_to_id[str(name)] = cid
    # Candidate-only registries may add a new supporting character without
    # changing the authoritative CHARACTER_BIBLE. The chapter card must carry
    # that stable ID and alias list explicitly.
    for profile in card.get("canonical_cast") or []:
        if isinstance(profile, dict):
            cid = str(profile.get("character_id") or "")
            for name in [profile.get("name"), profile.get("display_name"), *(profile.get("aliases") or [])]:
                if name and cid:
                    name_to_id[str(name)] = cid
    allowed = set(str(x) for x in (card.get("main_character_ids") or []))
    allowed.update(str(x) for x in (card.get("main_opponent_character_ids") or []))
    if card.get("main_opponent_character_id"):
        allowed.add(str(card["main_opponent_character_id"]))
    for item in card.get("canonical_cast") or []:
        if isinstance(item, dict) and item.get("character_id"):
            allowed.add(str(item["character_id"]))
    failures = []
    for name, cid in name_to_id.items():
        # A short alias can be a substring of the canonical full name. Resolve
        # the longest canonical mention first; do not misclassify its alias as
        # an unrelated, unauthorized character.
        full_names = [str(profile.get("name") or "") for profile in profiles
                      if str(profile.get("character_id") or "") == cid]
        if name in body and any(full_name and full_name in body for full_name in full_names):
            continue
        if name in body and cid not in allowed and name != "麦珂·杰森":
            failures.append(f"角色姓名未获本章character_id授权：{name}")
    wrong_names = ("黛安娜·陈", "瑟琳娜·王", "瑟琳娜·刘", "瑟琳娜·麦凯", "维克多·斯特林", "苏菲亚·沃克", "昆廷·哈特", "卡尔·斯特林")
    failures.extend(f"角色身份漂移：{name}" for name in wrong_names if name in body)
    return failures


def _rebirth_subject_failures(body: str) -> list[str]:
    markers = r"前世|上一世|上辈子|重生|未来记忆|那一世|死前"
    explicit_other_subjects = r"艾琳|维克多|黛安娜|瑟琳娜|苏菲亚|卡尔|昆廷|玛莎|乔纳"
    failures = []
    ma_ke_context = False
    for sentence in re.split(r"[。！？!?；;\n]", body):
        if not re.search(markers, sentence):
            if "麦珂" in sentence and not re.search(explicit_other_subjects, sentence):
                ma_ke_context = True
            elif sentence.strip() and not re.match(r"\s*(?:他|他的|他看|他想|他记)", sentence):
                ma_ke_context = False
            continue
        # Memory ownership is sentence-scoped.  An unqualified “他记得” is
        # ambiguous and must not pass as Ma Ke's memory, except when it is a
        # direct continuation of the immediately preceding Ma Ke sentence.
        has_ma_ke_subject = "麦珂" in sentence or (
            ma_ke_context and re.match(r"\s*(?:他|他的|他看|他想|他记)", sentence)
        )
        if not has_ma_ke_subject and re.search(explicit_other_subjects, sentence):
            failures.append("重生知识边界违规：非麦珂主语触发记忆")
            break
        if not has_ma_ke_subject and not re.search(r"我", sentence):
            failures.append("重生知识边界违规：非麦珂主语触发记忆")
            break
        ma_ke_context = has_ma_ke_subject
    return failures


def _hard_story_boundary_failures(body: str, card: dict[str, Any] | None = None) -> list[str]:
    """P0 firewall for rebirth knowledge leaks and irreversible outcomes."""
    failures: list[str] = []
    past = r"(?:\u4e0a\u4e00\u4e16|\u524d\u4e16|\u91cd\u751f|\u8fd9\u8f88\u5b50|\u672a\u6765\u8bb0\u5fc6)"
    if re.search(r"“[^”]{0,260}" + past + r"[^”]{0,260}”", body):
        failures.append("\u91cd\u751f\u77e5\u8bc6\u8fb9\u754c\u8fdd\u89c4: public leak")
    others = r"(?:\u739b\u838e|\u4e54\u7eb3|\u5361\u5c14|\u5df4\u91cc|\u6606\u5ef7|\u9edb\u5b89\u5a1c|\u82cf\u83f2\u4e9a|\u8bfa\u5170|\u82ac\u6069)"
    # Do not treat explicit negative statements such as “不知道前世” as
    # evidence that another character possesses the memory.
    if re.search(others + r".{0,100}(?<!\u4e0d)(?<!\u6ca1)(?<!\u672a)(?<!\u4ece\u672a)(?:\u77e5\u9053|\u8bb0\u5f97|\u60f3\u8d77|\u610f\u8bc6\u5230).{0,100}" + past, body):
        failures.append("\u91cd\u751f\u77e5\u8bc6\u8fb9\u754c\u8fdd\u89c4: other character knows")
    irreversible = re.search(r"(?:\u6c38\u4e45|\u7ec8\u8eab|\u5f7b\u5e95\u5931\u53bb\u804c\u4e1a|\u884c\u4e1a\u9ed1\u540d\u5355|\u6240\u6709\u5de5\u4f5c\u88ab\u6682\u505c|\u7acb\u5373\u540a\u9500\u5168\u90e8\u8d44\u683c).{0,30}(?:\u6743\u9650|\u804c\u4e1a|\u8d44\u683c|\u5c31\u4e1a|\u7981\u5165|\u63a7\u5236\u6743|\u89e3\u96c7|\u5c01\u6740)", body)
    if irreversible:
        planned = any(
            isinstance(item, dict) and item.get("irreversible") is True
            for item in ((card or {}).get("state_transitions") or [])
        )
        if not planned:
            failures.append("\u89d2\u8272\u72b6\u6001\u8d8a\u6743: unplanned irreversible outcome")
    if card:
        match = re.match(r"(\d{4})", str(card.get("timeline_start") or ""))
        if match:
            current_year = int(match.group(1))
            current_age = _protagonist_age(card)
            if current_age >= 18 and re.search(r"(?:\u5341\u4e00\u5c81|\u5341\u4e8c\u5c81|\u5c11\u5e74\u8eab\u4f53|\u5b69\u7ae5\u8eab\u4f53|\u672a\u6210\u5e74\u4eba|\u76d1\u62a4\u6743|\u7ae5\u661f)", body):
                failures.append(f"\u5e74\u9f84\u72b6\u6001\u51b2\u7a81：{current_year}\u5e74\u9ea6\u73c2\u5e94\u4e3a\u7ea6{current_age}\u5c81")
    return failures


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
        completion_budget = 3500 if os.getenv("BODY_COMPACT_PROMPT", "").strip() == "1" else 7000
        started = time.monotonic()
        response = call_openai_compatible_via_curl(
            messages,
            api_key=api_key,
            model=model,
            endpoint=compatible_endpoint,
            temperature=temperature,
            top_p=0.86,
            max_tokens=completion_budget,
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
            max_tokens=3500 if os.getenv("BODY_COMPACT_PROMPT", "").strip() == "1" else 7000,
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
            max_tokens=3500 if os.getenv("BODY_COMPACT_PROMPT", "").strip() == "1" else 7000,
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
        # Some compatible endpoints emit a literal newline/tab inside a JSON
        # string.  Accept it only as a parser recovery; all downstream schema
        # and quality gates still run unchanged.
        try:
            parsed = json.loads(text, strict=False)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed, _ = json.JSONDecoder().raw_decode(text[start:])
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


def _canonical_payload_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _failure_reaches_rebuilt_tail(message: Any) -> bool:
    """Return True for a failure that can affect EC136+/chapter271+.

    The completed first 270 chapters were produced from an older, much looser
    schema.  Their planning metadata has known validation debt, but it must not
    hide any cross-boundary or rebuilt-tail failure.
    """
    text = str(message)
    event_refs = [int(value) for value in re.findall(r"EC(\d+)", text)]
    chapter_refs = [int(value) for value in re.findall(r"第(\d+)章", text)]
    if any(value >= 136 for value in event_refs):
        return True
    if any(value >= 271 for value in chapter_refs):
        return True
    # A global failure with no address cannot safely be assigned to the frozen
    # prefix, so retain it as fatal.
    return not event_refs and not chapter_refs


def _verify_frozen_prefix_lock(
    output_dir: Path, events: list[dict[str, Any]], cards: list[dict[str, Any]],
) -> tuple[bool, str]:
    lock_path = output_dir / "body_generation" / "frozen_prefix_lock_v16.json"
    if not lock_path.is_file():
        lock_path = output_dir / "body_generation" / "frozen_prefix_lock_v15.json"
    if not lock_path.is_file():
        return False, f"缺少冻结前缀锁：{lock_path}"
    lock = _load_json(lock_path)
    if int(lock.get("event_boundary") or 0) != 135 or int(lock.get("chapter_boundary") or 0) != 270:
        return False, "冻结前缀锁边界不是EC135/第270章"
    event_hash = _canonical_payload_sha256(events[:135])
    card_hash = _canonical_payload_sha256(cards[:270])
    if event_hash != str(lock.get("prefix_events_sha256") or ""):
        return False, "EC001—EC135已在锁定后发生变化"
    if card_hash != str(lock.get("prefix_cards_sha256") or ""):
        return False, "第001—270章章卡已在锁定后发生变化"
    return True, "冻结前缀哈希匹配"


SEMANTIC_CRITIC_FIELDS = (
    "knowledge_boundary", "character_state", "timeline_causality",
    "pov_consistency", "role_identity", "authority_scope",
    "evidence_supports_conclusion", "outcome_overreach",
    "repeated_resolution_pattern", "era_technology", "artifact_scope",
    "cost_persistence", "character_flaw_integration", "plan_summary_leak",
)


def _run_semantic_critic(
    *, cluster: dict[str, Any], cards: list[dict[str, Any]],
    bodies: dict[int, str], graph_contexts: dict[int, str], model: str,
    recent_bodies: dict[int, str] | None = None,
) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    """Run a low-temperature semantic gate after deterministic validation."""
    payload = {
        "event_cluster": _model_cluster_payload(cluster),
        "chapter_cards": [_model_card_payload(card) for card in cards],
        "authoritative_character_constraints": _character_constraints_for_scene(cluster, cards),
        "hard_character_state_by_chapter": {
            str(card["chapter_id"]): _hard_character_state_from_context(
                card, graph_contexts.get(int(card["chapter_id"]), "")
            ) for card in cards
        },
        "world_rules": _load_world_rules(),
        "graph_context_before_chapter": graph_contexts,
        "recent_chapters": {str(k): v for k, v in (recent_bodies or {}).items()},
        "candidate_chapters": bodies,
    }
    instruction = """You are a strict continuity critic for a long Chinese rebirth novel.
Return JSON only. Inspect the candidate against the supplied plan and context.
Only set ok=false when there is concrete evidence in the candidate or plan.
Treat authoritative_character_constraints and the supplied story plan as the
source of truth; never infer gender, age, or role from a name, pronoun habit,
or real-world convention. Do not call a planned fictional time skip a continuity
error unless the dates actually contradict each other.
Check: only Ma Ke knows past-life facts; current role/permission is respected;
dates and causal order are coherent; POV does not reveal another person's private
knowledge; names and roles do not cross; evidence actually supports conclusions;
lawyers, hosts and producers do not exercise powers they do not have; temporary
suspension is not silently expanded into permanent career destruction; and the
resolution is not a replay of the same contract-document-authority template;
technology is valid for the chapter date; artifacts are used only within their
granted_permissions; active costs persist until a visible cost_resolution;
character flaw conflict is integrated into the main scene rather than appended
as an unrelated ending; and planning labels or summary instructions never leak
into the prose.
Compare candidate_chapters with recent_chapters and reject same core conflict,
countermeasure, or payoff replay even when wording differs. A planned fictional
time skip is valid only when chapter dates and synopsis agree.
Use exactly these fields, each as {"ok": true|false, "evidence": [short strings]}:
knowledge_boundary, character_state, timeline_causality, pov_consistency,
role_identity, authority_scope, evidence_supports_conclusion, outcome_overreach,
repeated_resolution_pattern, era_technology, artifact_scope, cost_persistence,
character_flaw_integration, plan_summary_leak."""
    raw, meta = _call_qwen(
        [{"role": "system", "content": instruction},
         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        model=model, temperature=0.05,
    )
    try:
        result = _parse_json_object(raw)
    except (ValueError, TypeError) as exc:
        # A malformed critic response is a failed quality gate, never an
        # acceptance.  Return a schema failure so the caller can retry the
        # cluster instead of crashing after costly body generation.
        return {}, [f"semantic critic unavailable: {exc}"], {
            **meta,
            "status": "not_run",
            "reason": "malformed_json",
        }
    failures: list[str] = []
    for field in SEMANTIC_CRITIC_FIELDS:
        item = result.get(field)
        if not isinstance(item, dict):
            failures.append(f"semantic critic malformed field: {field}")
            continue
        ok = item.get("ok")
        evidence_items = item.get("evidence")
        if type(ok) is not bool or not isinstance(evidence_items, list) or any(not isinstance(value, str) for value in evidence_items):
            failures.append(f"semantic critic malformed schema: {field}")
            continue
        if ok is False:
            evidence = "; ".join(evidence_items)
            failures.append(f"semantic critic {field}: {evidence[:500]}")
    return result, failures, meta


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
        "character_lifecycle",
        "active_costs",
        "cost_resolutions",
    )
    return {key: card.get(key) for key in keys if card.get(key) not in (None, "", [])}


def _model_card_payload(card: dict[str, Any]) -> dict[str, Any]:
    """Keep the authoritative facts while fitting smaller compatible models.

    DashScope can accept the complete card.  The saved Groq tier has a much
    smaller input budget, so its opt-in compact view retains the exact current
    synopsis and action anchors but omits duplicated provenance/state blobs.
    """
    if os.getenv("BODY_COMPACT_PROMPT", "").strip() != "1":
        return _select_card_payload(card)
    keys = (
        "chapter_id", "chapter_title", "timeline_start", "timeline_end",
        "chapter_role_v2", "chapter_goal", "chapter_must_include",
        "chapter_must_not_include", "chapter_ending", "detailed_synopsis",
        "scene_location", "exact_action_sequence", "info_gap_use",
        "opponent_reaction", "immediate_payoff", "participants",
    )
    synopsis = card.get("_authoritative_synopsis") or {}
    return {
        **{key: card.get(key) for key in keys if card.get(key) not in (None, "", [])},
        "authoritative_synopsis": {
            key: synopsis.get(key)
            for key in ("chapter_id", "chapter_title", "timeline_start", "chapter_goal",
                        "chapter_must_include", "chapter_must_not_include",
                        "detailed_synopsis", "scene_location", "exact_action_sequence",
                        "chapter_ending", "immediate_payoff")
            if synopsis.get(key) not in (None, "", [])
        },
    }


def _model_cluster_payload(cluster: dict[str, Any]) -> dict[str, Any]:
    if os.getenv("BODY_COMPACT_PROMPT", "").strip() != "1":
        return _select_cluster_payload(cluster)
    keys = (
        "cluster_id", "chapter_span", "name", "timeline_years", "event_type",
        "solution_type", "main_opponent", "main_characters", "source_event_direction",
        "fictional_obstacle", "preemptive_avoidance", "bait_and_evidence",
        "protagonist_gain", "relationship_change", "protagonist_cost",
        "residual_problem", "next_event_hook", "cluster_outcome",
    )
    return {key: cluster.get(key) for key in keys if cluster.get(key) not in (None, "", [])}


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
        "outcome_type",
        "protagonist_cost",
        "residual_problem",
        "character_flaw_beat",
        "resolution_signature",
        "death_chain_role",
        "death_chain_step",
        "source_event_direction",
        "opponent_humanizing_beat",
        "cost_resolutions",
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
    terms = ("指尖", "喉结", "信封", "蓝雪", "波形", "墨迹", "杯子", "骑缝章", "铅封", "声音不大", "脸色瞬间", "狼狈", "这一刻", "掌心传来的力量", "属于自己的命运", "再也无人能夺走", "光芒万丈")
    counts = {term: 0 for term in terms}
    sources: list[int] = []
    dynamic_sources: dict[str, set[int]] = defaultdict(set)
    for prior_id in range(max(1, chapter_id - 10), chapter_id):
        path = output_dir / "chapters" / f"chapter_{prior_id:03d}.txt"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        sources.append(prior_id)
        for term in terms:
            counts[term] += text.count(term)
        for paragraph in re.split(r"[\n。！？!?]+", text):
            cleaned = re.sub(r"[^\u3400-\u9fff]", "", paragraph)
            for size in range(4, 9):
                for index in range(max(0, len(cleaned) - size + 1)):
                    dynamic_sources[cleaned[index:index + size]].add(prior_id)
    avoid = [term for term, count in counts.items() if count >= 2]
    dynamic = [
        phrase for phrase, chapter_ids in sorted(
            dynamic_sources.items(), key=lambda item: (-len(item[1]), -len(item[0]), item[0])
        )
        if len(chapter_ids) >= 3
        and not any(name in phrase for name in ("麦珂", "玛莎", "维克多", "瑟琳娜", "苏菲亚"))
    ][:40]
    return {"source_chapters": sources, "counts": counts, "avoid_as_primary_motif": avoid, "dynamic_avoid_phrases": dynamic}


def _cluster_style_budget(
    output_dir: Path, chapter_id: int, cluster_start: int,
    staged_bodies: dict[int, str],
) -> dict[str, Any]:
    """Use prior official prose plus newly staged prose, never a stale same-cluster file."""
    terms = ("指尖", "喉结", "信封", "蓝雪", "波形", "墨迹", "杯子", "骑缝章", "铅封", "声音不大", "脸色瞬间", "狼狈", "这一刻", "掌心传来的力量", "属于自己的命运", "再也无人能夺走", "光芒万丈")
    counts = {term: 0 for term in terms}
    sources: list[int] = []
    dynamic_sources: dict[str, set[int]] = defaultdict(set)
    for prior_id in range(max(1, chapter_id - 10), chapter_id):
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
        for paragraph in re.split(r"[\n。！？!?]+", text):
            cleaned = re.sub(r"[^\u3400-\u9fff]", "", paragraph)
            for size in range(4, 9):
                for index in range(max(0, len(cleaned) - size + 1)):
                    dynamic_sources[cleaned[index:index + size]].add(prior_id)
    return {
        "source_chapters": sources,
        "counts": counts,
        "avoid_as_primary_motif": [term for term, count in counts.items() if count >= 2],
        "dynamic_avoid_phrases": [
            phrase for phrase, chapter_ids in sorted(
                dynamic_sources.items(), key=lambda item: (-len(item[1]), -len(item[0]), item[0])
            )
            if len(chapter_ids) >= 3
            and not any(name in phrase for name in ("麦珂", "玛莎", "维克多", "瑟琳娜", "苏菲亚"))
        ][:40],
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
1. 只有当本章梗概明确要求时，才把重生信息差写成今生的具体抢先动作；程序性承接章不得为了展示主线而重复记忆词。若正文出现记忆内容，必须严格归属于麦珂，并转化为当下可见的选择。
2. 人物塑造必须服从本次提供的“人工人物约束”。同一性格根源既制造能力也制造缺陷；反差必须通过利益冲突中的选择、语言习惯、谎言、牺牲和代价表现，禁止作者直接贴标签。重要场景至少让一名核心人物在两个都有价值或都有代价的选项之间作出选择。
3. 只有opposition_type=villain才写坏得滑稽；盟友阻力、制度、技术、家庭或内心冲突不能套反派模板。真正反派的可笑举动必须留下把柄或推动其失败，不写成无害搞笑角色。
4. 快节奏且每章有所得。第一章也要有可见推进，第二章必须完成反派损失、主角收益或关系/资产状态改变。可以留下一条具体钩子，但禁止用“这只是开始”“更大的风暴”等空话收尾。
5. 使用第三人称限知，贴近麦珂的即时判断。情绪强烈但克制，不堆砌情绪词。感官细节只写会改变判断或行动的部分，不承担凑字功能。禁止把“手指、喉结、杯子、墨迹、呼吸停顿”当作所有人物通用的紧张模板。
6. 每章正文目标1200—1600个汉字，最低不得少于1100个汉字，最高不得超过2000个汉字。每段1—4句，避免长篇解释和为撑长度重复物件、比喻或程序。
7. 所有人物、年代、设备和证据必须服从提供的规划。前世记忆不是今生物证；不能发明万能黑客、匿名证据、神秘证人或未规划的具名人物。
8. 舞台只能是架空米国及规划中的虚构城市、机构和品牌；不得出现中国现实品牌、城市、机构或现实艺人。
9. 若是重生确认章，开头三段内必须让读者明确看到年份与孩童身体；此后的年龄必须服从hard_character_state中的current_age，禁止把成年麦珂写回十一岁。
10. 正文叙述和普通身份称呼必须使用简体中文。除规划固有的Fonovox、V.L.、音名或编号外，不得夹入reporter、staff、manager等英文单词。
11. 当前章卡给出的日期和前序图谱是时间线依据。除第1章重生确认外，禁止把完整日期固定成每章第一句；应从动作、对白、物件变化或冲突进入，并在前三个自然段内自然交代时间。连续同日可用“当天午后”“次日清晨”等承接语，但前三段仍须保留正确年份线索。几周前发生的签约、公证或混音不得写成“三年前”“十一年前”；“十一岁”不能误写成“十一年前”。
12. 麦珂的优势是知道未来哪一天、哪句话和哪一次选择会造成伤害；优先让有资质的成年人完成法务、工程和鉴定动作，禁止把十一岁主角写成凭空精通所有专业的全知神童。
13. 近三章已经高频使用的意象、物件和身体反应不得再作为主描写；蓝雪、信封、钢印、铅封、骑缝章、波形只在本章事实不可替代时出现。
14. 只输出严格JSON，不要Markdown，不要章节标题，不要分析，不要创作说明。正文不得含分节小标题或星号加粗。
15. 知识防火墙：只有麦珂拥有上一世记忆；他不得在公开对话中说出上一世、前世、重生、这辈子或未来记忆。其他人物只能依据当下证据推断。
16. 状态防火墙：停职、调查、复核和权限限制必须服从hard_character_state，不得扩写成永久封杀、终身吊销或不可逆职业结论。
17. 身份与生命周期防火墙：性别、生日、当前周岁、life_stage、角色和权限是不可改写事实；成年阶段不得复用监护权、童星或父母代签冲突。
18. 代价与缺陷防火墙：protagonist_cost、active_costs、cost_resolutions与character_flaw_beat必须通过主场景选择和后果兑现；代价不得在未满足恢复条件时消失，人物冲突不得粘贴在章尾。
19. 年代与权限防火墙：技术必须符合era_technology_matrix；artifact只能执行granted_permissions中的动作，不能由一纸文件凭空获得冻结资金、解雇、技术访问或医疗同意权。
20. 规划防泄漏：正文不得出现“本章必须”“事件簇”“结算契约”“章卡要求”“生成正文时”等计划摘要或写作指令。"""
    compact_prompt = os.getenv("BODY_COMPACT_PROMPT", "").strip() == "1"
    scene_characters = _character_constraints_for_scene(cluster, cards)
    if compact_prompt:
        scene_characters = {
            "selected_characters": [
                {key: profile.get(key) for key in ("character_id", "name", "aliases", "role")}
                for profile in (scene_characters.get("selected_characters") or [])
            ]
        }
    user_payload = {
        "authoritative_event_cluster": _model_cluster_payload(cluster),
        "authoritative_chapter_cards": [_model_card_payload(card) for card in cards],
        "neo4j_context_before_each_chapter": {} if compact_prompt else graph_contexts,
        "human_authored_character_constraints": scene_characters,
    }
    style_block = _style_block(style_samples)
    if compact_prompt:
        style_block = "（本批采用权威章卡与梗概，不附加风格样本。）"
    user_prompt = f"""请一次性写完同一事件簇的两章连续正文。

【权威规划与图谱上下文】
{json.dumps(user_payload, ensure_ascii=False, indent=2)}

【仅供学习情绪密度、人物反差和爽点落地方式的短样本；不得复制人物与事实】
{style_block}

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
    compact_prompt = os.getenv("BODY_COMPACT_PROMPT", "").strip() == "1"
    writer_graph_context = graph_context
    current_year_match = re.match(r"(\d{4})", str(card.get("timeline_start") or ""))
    if current_year_match and int(current_year_match.group(1)) > 1969:
        # Retrieval may contain the 1969 rebirth snapshot. It is historical
        # context, not the current physical identity; remove it from the
        # writer-facing context so the deterministic identity contract wins.
        writer_graph_context = re.sub(
            r"[^\n]*(?:十一岁|十二岁|孩童身体|少年身体)[^\n]*\n?",
            "[历史年龄快照已隐藏；当前年龄以hard_character_state为准]\n",
            writer_graph_context,
        )
        # Past-life planning prose is not narrative evidence.  Keep the
        # writer's information-gap cue at the protagonist level only; this
        # prevents Qwen from assigning the memory to an ally or opponent.
        writer_graph_context = re.sub(
            r"[^\n]*(?:前世|上一世|重生|未来记忆|死前)[^\n]*\n?",
            "[前置记忆仅归属于麦珂；本章不得让其他人物知晓]\n",
            writer_graph_context,
        )
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
            "outcome_type",
            "protagonist_cost",
            "residual_problem",
            "cost_resolutions",
        ):
            cluster_payload.pop(key, None)
    if chapter_id >= 271:
        # These planning-only memory fields cause the writer to echo forbidden
        # public past-life language or assign it to another character.  The
        # authoritative files remain unchanged; the writer receives only the
        # protagonist-scoped information-gap cue on the card below.
        for key in ("prev_life_tragedy", "info_gap_from_prev_life", "why_previous_life_failed"):
            cluster_payload.pop(key, None)
    if int(card.get("chapter_id") or 0) == 272 and str(cluster.get("cluster_id") or "") == "EC136":
        # The finale card is the authority for its own payoff.  Do not expose
        # the cluster-level discovery narrative a second time, or the writer
        # tends to replay chapter 271 before reaching the one-day delay.
        for key in ("source_event_direction", "fictional_obstacle", "bait_and_evidence", "preemptive_avoidance"):
            cluster_payload.pop(key, None)
    scene_characters = _character_constraints_for_scene(cluster, [card])
    if compact_prompt:
        scene_characters = {
            "selected_characters": [
                {key: profile.get(key) for key in ("character_id", "name", "aliases", "role")}
                for profile in (scene_characters.get("selected_characters") or [])
            ]
        }
    # Keep the authoritative card files immutable, but give the writer a
    # chapter-scoped rendering of the overlapping EC136 fields.  The stored
    # synopsis is evidence and remains unchanged; this view prevents the
    # model from copying chapter 271's discovery language into chapter 272.
    writer_card = dict(card)
    if chapter_id >= 271:
        # The merged card also carries a private authoritative-synopsis copy
        # for audit provenance.  It is not needed in the writer prompt and can
        # reintroduce planning-only memory language through compact mode.
        writer_card.pop("_authoritative_synopsis", None)
    if chapter_id >= 271 and any(
        marker in str(writer_card.get("info_gap_use") or "")
        for marker in ("前世", "上一世", "重生", "未来记忆", "死前")
    ):
        writer_card["info_gap_use"] = (
            "只允许麦珂明确记得一条会扩大损失的错误处理路径；他据此提前选择本章动作。"
            "不得写出记忆来源，不得让其他人物拥有或谈论这条记忆。"
        )
    if str(cluster.get("cluster_id") or "") == "EC136" and chapter_id == 271:
        writer_card["detailed_synopsis"] = (
            "只写从第270章来源目录进入河湾镇档案馆收发室：定位BA-83-11对应的来源箱和复制申请的经手岗位入口。"
            "麦珂把空箱号当作待追查缺口，不作伪造结论；本章结束在取得受限调阅的资格，不能写次日核对结果。"
        )
        writer_card["info_gap_use"] = (
            "麦珂只在内心用一句‘麦珂记得，错误处理会先从一个小缺口开始扩大’触发选择，因此抢先追来源而不是下结论；不得出现前世、上一世、重生等词。"
        )
    elif str(cluster.get("cluster_id") or "") == "EC136" and chapter_id == 272:
        writer_card["detailed_synopsis"] = (
            "承接第271章已经定位的来源箱和申请页入口，只沿相邻登记、交接单和当班记录确认实际经手岗位，"
            "区分经手岗位与批准责任。重点写经手人不愿承担缺失签名责任，以及档案馆主管作出的有限调阅决定；不得重新寻找来源箱，不得起草移交簿。"
        )
        writer_card["info_gap_use"] = (
            "麦珂不解释记忆来源，只用上一章保住的材料决定核查顺序；不得重复发现过程，不得出现前世、上一世、重生等词。"
        )
    payload = {
        "authoritative_event_cluster": _model_cluster_payload(cluster_payload),
        "authoritative_chapter_card": _model_card_payload(writer_card),
        "neo4j_context_before_chapter": "" if compact_prompt else writer_graph_context,
        "hard_character_state": _hard_character_state_from_context(card, graph_context),
        "world_rules": {} if compact_prompt else _load_world_rules(),
        "human_authored_character_constraints": scene_characters,
        "recent_style_budget": recent_style_budget or {},
    }
    if previous_body and str(cluster.get("cluster_id") or "") == "EC136" and chapter_id == 272:
        # Do not expose the first chapter's prose here.  Its repeated archive
        # vocabulary was being copied even though the second card has a
        # different progress point.  Preserve only the state transition.
        continuity = (
            "这是事件簇第二章。上一章已经完成：在河湾镇档案馆收发室定位了BA-83-11对应来源箱，"
            "并取得复制申请入口和受限调阅资格。现在只能承接这个既成状态，写相邻登记、交接单和当班记录如何确认实际经手岗位，"
            "再由经手人面对缺失复核签名的责任边界；不要重写来源箱定位、空箱号发现、申请页发现、移交簿起草或昨日对话。"
        )
    else:
        continuity = (
            "这是事件簇第二章。上一章只提供后果、未完成目标、人物决定和新阻力；禁止复用上一章的物件、比喻、身体反应或场景开头：\n"
            # A long prose excerpt turns continuity into a copying template.
            # The current card is authoritative; retain only a short tail for
            # concrete state handoff and require fresh scene construction.
            + previous_body[-360:]
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
    if settlement_contract:
        settlement_contract = """[Event-cluster settlement contract]
The cluster finale must create at least one concrete, meaningful state change.
It may be a blocked harm, a clue or evidence, a limited resource, a costly win,
a stalemate, a setback with a new option, or a relationship change. Do not force
all three of villain loss, protagonist gain, and relationship upgrade. A role or
reputation loss is allowed only when the card explicitly marks it irreversible.
Never expand warning, suspension, or investigation into permanent unemployment.
Planned signals (use only those supported by the scene):
villain_loss={villain_loss}
protagonist_gain={protagonist_gain}
relationship_change={relationship_change}
""".format(
            villain_loss=_clip(cluster.get("villain_loss"), 500),
            protagonist_gain=_clip(cluster.get("protagonist_gain"), 500),
            relationship_change=_clip(cluster.get("relationship_change"), 500),
        )
    cost_contract = ""
    if is_cluster_finale and cluster.get("protagonist_cost"):
        cost_contract = """
【主角代价硬契约】
本章必须把以下代价写成可见选择和后果：
{cost}
必须说明麦珂为了保住什么而主动放弃、暴露或暂停了什么，并让代价在结尾仍然存在；禁止只写‘他很累’，也禁止下一段立刻恢复为全胜。
""".format(cost=_clip(cluster.get("protagonist_cost"), 800))
    flaw_contract = ""
    if cluster.get("character_flaw_beat"):
        flaw_contract = """
【控制欲人物弧硬契约】
把以下控制欲节点通过选择、对白和关系反应写出来，不要用旁白直接解释人物缺陷：
{flaw}
麦珂的控制行为必须同时带来即时收益和关系/自主权代价；如果模式是repair或growth，必须让他把信息和最终选择权交还给对方。
""".format(flaw=_clip(cluster.get("character_flaw_beat"), 1200))
    protagonist_age = _protagonist_age(card)
    life_stage = "adult" if protagonist_age >= 18 else "minor"
    forbidden_age_words = (
        ["十一岁", "十二岁", "少年身体", "孩童身体", "未成年人", "监护权", "童星"]
        if protagonist_age >= 18 else
        ["成年身体", "成年人身体", "完全民事行为能力", "无需监护人"]
    )
    if "rebirth" in str(card.get("chapter_role_v2") or "").lower():
        forbidden_age_words = [word for word in forbidden_age_words if word not in {"十一岁", "少年身体", "孩童身体"}]
    hard_fact_payload = {
        "must_include": card.get("chapter_must_include") or [],
        "scene_location": card.get("scene_location") or "",
        "artifact_creates": card.get("artifact_creates") or [],
        "must_resolve_this_chapter": [] if compact_prompt else (card.get("must_resolve_this_chapter") or []),
        "state_transitions": [] if compact_prompt else (card.get("state_transitions") or []),
        "exact_action_sequence": card.get("exact_action_sequence") or [],
        "active_costs": card.get("active_costs") or [],
        "protagonist_cost": cluster.get("protagonist_cost"),
        "character_flaw_beat": cluster.get("character_flaw_beat"),
        "identity_contract": {
            "protagonist": "麦珂·杰森",
            "sex": "male",
            "birth_year": 1958,
            "current_year": int(re.search(r"(\d{4})", str(card.get("timeline_start") or card.get("timeline_years") or "0000")).group(1)),
            "birth_date": "1958-08-29",
            "current_age": protagonist_age,
            "life_stage": life_stage,
            "legal_capacity": "full" if protagonist_age >= 18 else "limited",
            "guardian_required": protagonist_age < 18,
            "forbidden_age_words_in_this_chapter": forbidden_age_words,
        },
    }
    if not is_cluster_finale:
        hard_fact_payload.pop("protagonist_cost", None)
    hard_facts = json.dumps(hard_fact_payload, ensure_ascii=False, indent=2)
    early_ec136_contract = ""
    if int(card.get("chapter_id") or 0) == 271 and str(cluster.get("cluster_id") or "") == "EC136":
        early_ec136_contract = f"""
【输出前置硬约束】
- 日期“{card.get('timeline_start')}”必须在本章自然出现并与事件顺序一致，但不得固定为第一句；首段应优先进入“{card.get('scene_location')}”中的动作。
- 必须在前三个自然段内交代“{str(card.get('timeline_start') or '')[:4]}年”，有效段落控制在10—14段，避免把一个动作拆成大量短段。
- 本章除麦珂外不得出现任何前世/上一世信息；为避免视角污染，正文不要让其他人物知道或谈论相关信息。
- 全文采用贴近麦珂的限知视角；维克多、艾琳和档案馆主管的心理动机只能通过动作、语气、停顿或已说出口的话呈现，禁止直接写“他意识到/他知道/他重新审视”等内心结论。
- 必须把章卡的关键动作写成现场选择：麦珂拒绝把空箱号直接说成伪造，只把它当作需要追查来源的缺口；不得用旁白总结替代动作。
- 为保留重生信息差，只允许麦珂内心出现一次“他记得”式短句，写成他对错误处理路径的警觉；不得解释记忆来源，也不得让其他人物听见。
- 必须逐字出现“河湾镇档案馆收发室”，并在第一段或第二段写出“1993年”；首句不能是日期。
- 正文控制为7—16个有效段落，每段推进一个动作、判断或关系变化，不写说明书式重复免责声明。
- 本章必须在前三个自然段中出现“1993年”，但第一句从动作或对白进入；不要把日期单独写成开场标题。
"""
    if int(card.get("chapter_id") or 0) == 272 and str(cluster.get("cluster_id") or "") == "EC136":
        early_ec136_contract = f"""
【第272章专属硬约束】
- 日期“{card.get('timeline_start')}”须在本章自然交代，但不得作为固定开头；随后进入河湾镇档案馆收发室的当班记录核对。
- 本章不得重新描写第271章的来源箱定位、BA-83-11缺号发现过程或申请页发现过程；只写沿相邻登记、交接单和当班记录追查实际经手岗位。
- “来源箱”和“申请页”在本章只能作为已取得的前章材料出现，不得再次发现；必须逐字出现“河湾镇档案馆收发室”，并在前三个自然段出现“1993年”。
- 本章只在“河湾镇档案馆收发室”交接到内侧阅览桌/值班记录台之后展开，不能复用第271章收发台的开场；正文不得出现“来源箱移交簿”或“空箱号”这两个上章核心表述，不得再写寻找箱号。
- 结尾只确认需要核查的部门与批准人，突出经手人不愿承担签字责任；不得提前签发暂停使用决定，不得提前进入合同谈判。
- 必须明确写出“团队为受限调阅多等一日”的现实代价，并让档案馆主管作出有限决定；不要再次寻找来源箱、重演缺号发现或起草移交簿。
- 本章控制在7—14个有效段落，优先写人物面对签字责任时的选择，不写其他人物的内心结论。
"""
    if str(cluster.get("cluster_id") or "") == "EC137" and chapter_id == 273:
        early_ec136_contract = f"""
【EC137上章专属硬约束】
- 只写“节目部资料室”的权限核查，不回到档案馆，不重演EC136的来源箱、移交簿或交接记录。
- 必须逐字写出《CR-41权限分栏表》，并通过申请、复核、批准三栏的现场核对确认缺失的是复核环节；本章不写排期暂停的最终决定。
- 首句从争执中的动作或对白进入，前三个自然段自然出现“1993年”，不得用完整日期开头。
- 本章不需要加入记忆解释；如正文自然出现记忆词，必须明确归属于麦珂，且不得让其他人物拥有记忆。
"""
    if str(cluster.get("cluster_id") or "") == "EC137" and chapter_id == 274:
        early_ec136_contract = f"""
【EC137下章专属硬约束】
- 承接第273章已经完成的《CR-41权限分栏表》和复核缺口，只在“节目部资料室”写有限执行结果；不得重新核对三栏、重新创建表格或重演争执。
- 必须明确：涉事摘录暂时退出节目排期，取得的保护只覆盖这一份摘录，不扩大到整个节目部；写出由制度负责人作出的有限决定及其现实代价。
- 首句从新的执行动作或排期变化进入，前三个自然段自然出现“1993年”，不得用完整日期开头。
- 正文不得出现“前世”“上一世”“重生”“未来记忆”“死前”等词，不得使用“他记得”，不得让其他人物拥有记忆。
"""
    if str(cluster.get("cluster_id") or "") == "EC139" and chapter_id == 277:
        early_ec136_contract = f"""
【EC139上章专属硬约束】
- 只写海湾剧院节目办公室的现场处理：四十七份未写接收方的培训副本已经装车，卡尔·霍尔特必须主动叫停装车并让车辆留在装货口；这是本章第一个明确动作。
- 麦珂、黛安娜、苏菲亚与卡尔随后清点地域、份数和包装批次，巴里·布鲁姆试图以内部资料和排期压力推动直接发放；麦珂拒绝扩大指控，只要求把副本交付对象逐项列清。
- 本章必须在现场写出《副本交付对象清单》，结尾只登记现物、封存待领区，正常节目材料继续流转；不得提前写第278章的二十九份合法接收方核对或剧院承担重印费用。
- 正文完全不要出现“前世”“上一世”“上辈子”“重生”“未来记忆”“死前”“记忆”等词，避免任何知识边界误触发；只写当下动作。
- 首句从卡尔叫停装车、车辆刹停或巴里催促进入，前三个自然段自然出现“1993年”，不得用完整日期开头。
"""
    if str(cluster.get("cluster_id") or "") == "EC139" and chapter_id == 278:
        early_ec136_contract = f"""
【EC139下章专属硬约束】
- 承接第277章已经完成的《副本交付对象清单》和封存待领区，不得重新演叫停装车、寻找副本或创建清单。
- 只写运营负责人召集各培训点认领并核对地域、份数和收件人：四十七份中只有二十九份能对应合法接收方，其余属于无对象的批量重印；麦珂不追究所有印刷人员，只要求重建领用签收。
- 必须写出剧院承担重印费用、正常节目不受牵连，并让巴里争夺解释权但无法抹去已记录的选择；本章不扩大到其他争议。
- 正文完全不要出现“前世”“上一世”“上辈子”“重生”“未来记忆”“死前”“记忆”等词；只写当下核对与有限结算。
- 首句从认领电话、清点动作或费用争执进入，前三个自然段自然出现“1993年”，不得用完整日期开头。
"""
    if str(cluster.get("cluster_id") or "") == "EC140" and chapter_id == 279:
        early_ec136_contract = f"""
【EC140上章专属硬约束】
- 只写本章章卡规定的财务核对入口和初步差额，不提前写第280章的独立复核编号。
- 现场必须由苏菲亚·罗德里格斯和艾琳·沃特曼处理账线，维克多·兰斯施压要求付款；所有结论只能落在发现差额和提出复核，不写永久冻结或全面控制。
- 正文完全不要出现“前世”“上一世”“上辈子”“重生”“未来记忆”“死前”“记忆”等词，只写当下财务动作。
- 首句从迟到回执、账本翻页或付款争执进入，前三个自然段自然出现“1993年”，不得用完整日期开头。
"""
    if str(cluster.get("cluster_id") or "") == "EC140" and chapter_id == 280:
        early_ec136_contract = f"""
【EC140下章专属硬约束】
- 承接第279章已经发现的三线差额，不重新寻找差额或重演付款争执；本章必须让独立财务复核员完成核对。
- 必须明确写出：差额取得独立复核编号，编号可以自然写成“DN-93-280”；支付暂缓只针对这笔待核款项，基金错过当天付款窗口是现实代价。
- 维克多·兰斯只能失去直接推动付款的路径，不得被写成永久失去资格；苏菲亚取得的是本笔复核的程序入口。
- 正文完全不要出现“前世”“上一世”“上辈子”“重生”“未来记忆”“死前”“记忆”等词，只写当下财务动作。
- 首句从复核员落笔、回执被摊开或编号存根递出进入，前三个自然段自然出现“1993年”，不得用完整日期开头。
"""
    if str(cluster.get("cluster_id") or "") == "EC141" and chapter_id == 281:
        early_ec136_contract = f"""
【EC141上章专属硬约束】
- 只写河湾银行企业柜台的初步核对。有人要求以贪污名义冻结经手会计，麦珂必须把自己先前写下的“嫌疑判断”当场划掉、收回或明确撤回，写出这一可见动作，表示先核时间差而不是先定罪。
- 苏菲亚调出冲销单、银行回执时间和付款队列；必须形成《银行回执联与冲销单》，并明确银行回执比内部预留晚到一天。
- 本章只推进到发现时间差，不提前写第282章的加急付款指令、恢复真实余额或离岸付款编号。
- 正文完全不要出现“前世”“上一世”“上辈子”“重生”“未来记忆”“死前”“记忆”等词，只写当下选择和财务证据。
- 首句从柜台争执、麦珂划掉纸上判断或银行回执被推来进入，前三个自然段自然出现“1993年”，不得用完整日期开头。
"""
    if str(cluster.get("cluster_id") or "") == "EC141" and chapter_id == 282:
        early_ec136_contract = f"""
【EC141下章专属硬约束】
- 承接第281章的《银行回执联与冲销单》和时间差，不重新指控会计或重演撤回判断。
- 必须由银行复核主管重放当日入账顺序，确认第二笔预留本应自动冲销却被加急付款指令抢先占用；写出恢复真实余额、不再追究无辜会计、暴露施压申请人，以及基金失去一次低价采购窗口并取得确切付款编号。
- 正文完全不要出现“前世”“上一世”“上辈子”“重生”“未来记忆”“死前”“记忆”等词，只写当下复核与有限结算。
- 首句从复核主管调出入账顺序、付款队列变化或采购窗口关闭进入，前三个自然段自然出现“1993年”，不得用完整日期开头。
"""
    if str(cluster.get("cluster_id") or "") == "EC144" and chapter_id == 287:
        early_ec136_contract = f"""
【EC144上章专属硬约束】
- 只写《银湾纪事》编辑部：报纸把“单笔保全申请获受理”剪成“基金欺诈获定罪”，瑟琳娜·凯德明确拒绝公开私人往来换取头版，只出示裁定原句和被删条件从句。
- 必须形成《报纸勘误版样》，恢复完整句子但不触碰评论栏；不要要求撤稿、定罪或永久封杀。若需同事角色，只使用本章合法人物约束中的姓名，不新增未授权全名。
- 正文完全不要出现“前世”“上一世”“上辈子”“重生”“未来记忆”“死前”“记忆”等词，只写当下媒体纠错。
- 首句从编辑部排字、剪裁版样或瑟琳娜拒绝交易进入，前三个自然段自然出现“1993年”，不得用完整日期开头。
"""
    if str(cluster.get("cluster_id") or "") == "EC144" and chapter_id == 288:
        early_ec136_contract = f"""
【EC144下章专属硬约束】
- 承接第287章的《报纸勘误版样》，不重新争执剪裁，也不要求删除评论；由报社总编辑核查采访录音并承认标题越过事实，同时保留记者对基金治理的批评。
- 必须明确：勘误会使报道热度下降且舆论仍有怀疑；报纸刊出“疑点、复核范围、未决审理”三项说明，让公众看到三者区别，基金继续承受合理怀疑。
- 正文完全不要出现“前世”“上一世”“上辈子”“重生”“未来记忆”“死前”“记忆”等词，只写当下媒体处理。
- 首句从总编辑翻开录音稿、改版样张或印刷机停顿进入，前三个自然段自然出现“1993年”，不得用完整日期开头。
"""
    if str(cluster.get("cluster_id") or "") == "EC147" and chapter_id == 294:
        early_ec136_contract = f"""
【EC147下章专属硬约束】
- 只在录音棚控制室承接第293章的《和声贡献确认页》，由唱片版权管理员现场重放改编前后版本；不要重新发现署名争议。
- 必须写出：母带交付晚一周；艾琳·沃特曼获得明确署名及收益范围，但不取得麦珂整首歌控制权；版权管理员补入贡献范围后完成交付。
- 只使用本章合法人物约束中的姓名，不要加入黛安娜或其他未授权人物；正文完全不要出现“前世”“上一世”“上辈子”“重生”“未来记忆”“死前”“记忆”等词。
- 首句从唱片方放下唱针、控制室重放或管理员翻开贡献页进入，前三个自然段自然出现“1994年”，不得用完整日期开头。
"""
    user_prompt = f"""请只写第{chapter_id}章完整正文。
{early_ec136_contract}

【通用开篇约束】
- 除第1章外，第一句不得使用“某年某月某日/数字年月日”式完整日期模板。
- 首句先写本章的新动作、对白、现场异动或冲突；在前三个自然段中自然嵌入正确时间锚点。
- 本章章卡日期为“{card.get('timeline_start')}”，前三个自然段必须自然出现“{str(card.get('timeline_start') or '')[:4]}年”；不得用其他年份替代，也不得把完整日期单独写成首句。
- 与上一章同日时不要重新播报日期，优先用“当天午后/入夜前”等连续性表达，同时保留正确年份线索。
- 只有麦珂可以拥有前置记忆；涉及记忆时必须明确写“麦珂”，严禁使用无主语“他记得/他想起”让读者猜测主语，也严禁让其他人物知道。

【权威规划与图谱上下文】
{json.dumps(payload, ensure_ascii=False, indent=2)}

【连续性要求】
{continuity}
如果这是第二章，上一章已完成的试听、摔物、交接、签字或对话不得重新演一遍；必须进入本章的新时间、新动作和新结算。
{rebirth_contract}
{settlement_contract}
{cost_contract}
{flaw_contract}

[MANDATORY FACTS - must appear as concrete scene actions, not as a summary]
{hard_facts}
If a fact is phrased abstractly, convert it into a visible object, action, dialogue,
or sensory detail. Do not omit the time anchor, named location, or artifact creation.
The identity_contract is absolute: write Ma Ke as a male protagonist of the stated current_age and life_stage;
do not use any forbidden age words for him, even if older global story notes mention 1969.

【仅供学习情绪密度、人物反差和爽点落地方式的短样本；不得复制人物与事实】
{("（本批采用权威章卡与梗概，不附加风格样本。）" if compact_prompt else _style_block(style_samples))}

【本次长度要求】
请展开成约1200—1600个汉字、至少9个有实际推进的自然段。不能把梗概压缩成短摘要；
用动作受阻、人物选择、带潜台词的对话和真正影响判断的环境反馈充实场景，不得新增规划外事件，也不得重复意象凑字。

提交前自检：前三个自然段必须出现章卡年份；首句不要写完整日期；本章控制在7—18个有效段落；只写麦珂可知的内容，其他人物心理必须改成可见动作或对白。

【提交前硬性清单】
- 正文不得出现“前世”“上一世”“上辈子”“重生”“未来记忆”“死前”等词；若必须表现信息差，只能在一句中明确写“麦珂记得”，且不能放进任何人物对白。
- 严格落实当前章卡的场景、关键对象和结算边界；缺一项就完整重写，不要输出解释。

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


def _opening_time_failures(body: str, card: dict[str, Any]) -> list[str]:
    """Require an early time anchor without teaching the model a date-led template."""
    expected_date = str(card.get("timeline_start") or "").strip()
    if not expected_date:
        return []
    failures: list[str] = []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    early_text = "\n".join(paragraphs[:3])[:800]
    year = expected_date[:4]
    if year and year not in early_text:
        failures.append(f"正文前三段未交代章卡年份：期望{expected_date}")
    first_sentence = re.split(r"[。！？!?\n]", body.strip(), maxsplit=1)[0]
    full_date_pattern = r"^\s*(?:\d{4}|[〇零一二三四五六七八九]{4})年\s*(?:\d{1,2}|[一二三四五六七八九十]{1,3})月\s*(?:\d{1,2}|[一二三四五六七八九十]{1,3})日"
    if int(card.get("chapter_id") or 0) != 1 and re.match(full_date_pattern, first_sentence):
        failures.append("首句机械使用完整日期，应先从动作、对白或冲突进入")
    return failures


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
    failures.extend(_age_semantic_conflicts(card))
    failures.extend(_hard_story_boundary_failures(body, card))
    failures.extend(_hard_metadata_leak_failures(body))
    failures.extend(_paragraph_quality_failures(body))
    failures.extend(_character_identity_failures(body, card))
    failures.extend(_rebirth_subject_failures(body))
    han = _han_count(body)
    if han < MIN_HAN_CHARS:
        failures.append(f"汉字数{han}，低于{MIN_HAN_CHARS}")
    if han > MAX_HAN_CHARS:
        failures.append(f"汉字数{han}，高于{MAX_HAN_CHARS}")
    if "```" in body or "**" in body or re.search(r"^【[^】]+】", body, flags=re.M):
        failures.append("正文含Markdown或分节小标题")
    if re.search(r"(?:本章|这一章)(?:主要|讲述|描写)", body):
        failures.append("正文出现提纲式讲解")
    if re.search(r"第\s*\d+\s*章", body):
        failures.append("正文出现人物不可能知晓的内部章节号引用")
    failures.extend(_opening_time_failures(body, card))
    if "全息投影" in body:
        failures.append("年代技术不合理：全息投影")
    if re.search(r"便携(?:紫外灯|光谱仪).{0,80}(?:证明|确定|精确判断)(?:年份|年代|书写时间|自然老化)", body):
        failures.append("检测设备越权证明墨水年份/书写时间/自然老化")
    summary_markers = ("失去", "获得", "保住", "代价是", "从", "变成", "关系从")
    marker_hits = sum(body.count(marker) for marker in summary_markers)
    if marker_hits >= 7 and re.search(r"代价是|关系从|转变为|形成了", body):
        failures.append("正文疑似泄漏规划结算摘要：损失/收益/代价/关系状态密集并列")
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
    # Structured state identifiers may be emitted inside formal audit records;
    # they are metadata, not English narrative prose.
    state_metadata_tokens = set(re.findall(
        r"[A-Za-z]{4,}", json.dumps(card.get("state_transitions") or {}, ensure_ascii=False)
    ))
    lowercase_english = [word for word in re.findall(r"(?<![A-Za-z])[a-z]{4,}(?![A-Za-z])", body) if word not in {"calibration", "safety", "barely"} and word not in {token.lower() for token in state_metadata_tokens}]
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
    # Long-form chapters may realize the card through concrete scene actions
    # rather than repeating planner wording; retain the score for audit while
    # reserving the hard stop for materially lower coverage.
    if plan_body_overlap < 0.028:
        failures.append(
            f"正文与章卡目标/动作/回报语义覆盖仅{plan_body_overlap:.3f}，疑似写成了另一件事"
        )
    normalized_scene_body = re.sub(r"[\s的]", "", body)
    must_include = [
        str(value).strip() for value in (card.get("chapter_must_include") or [])
        if str(value).strip()
    ]
    must_include_evidence: list[dict[str, Any]] = []
    for anchor in must_include:
        exact = anchor in body
        cleaned = re.sub(r"[^\u3400-\u9fffA-Za-z0-9]", "", anchor)
        anchor_core = re.sub(
            r"(?:\u7684)?(?:\u65f6\u95f4\u951a\u70b9|\u5bc6\u5c01\u8fc7\u7a0b|\uff08\u539f\u4ef6\uff09)$",
            "", anchor,
        ).strip()
        grams = {
            cleaned[index:index + 2]
            for index in range(max(0, len(cleaned) - 1))
        }
        hits = {gram for gram in grams if gram in body}
        coverage = len(hits) / len(grams) if grams else 0.0
        time_variants = _clock_variants(anchor)
        matched = (
            exact
            or bool(anchor_core and anchor_core in body)
            or any(variant in body for variant in time_variants)
            or coverage >= 0.45
        )
        if "人墙" in anchor and any(term in body for term in ("人群堵住", "围成一堵墙", "挤成一团", "人群形成")):
            matched = True
        if "欢呼" in anchor and any(term in body for term in ("欢呼", "掌声", "喝彩", "叫好")):
            matched = True
        if "#8327" in anchor and "拼写" in anchor and "#8327" in body and any(term in body for term in ("拼写", "字母", "Safety")):
            matched = True
        if "编号卡形成" in anchor and any(term in body for term in ("编号卡", "号码牌", "持卡", "排成一堵墙")):
            matched = True
        if "媒体包围" in anchor and any(term in body for term in ("记者", "镜头", "媒体", "采访")):
            matched = True
        # This planning anchor is intentionally semantic: natural prose may
        # say “缺失/漏填的箱号不能直接认定为伪造” instead of repeating the
        # card's infinitive wording verbatim.
        if "空箱号" in anchor and "伪造" in anchor:
            if any(term in body for term in ("空白", "缺失", "漏填", "断号")) and "伪造" in body:
                matched = True
        if anchor.startswith("地点为"):
            place = anchor.removeprefix("地点为").strip()
            matched = matched or place in body or place.replace("的", "") in normalized_scene_body
        if "摘录暂时退出节目排期" in anchor:
            matched = matched or (
                "摘录" in body and "排期" in body and any(term in body for term in ("暂停", "退出", "移出"))
            )
        if "只对该摘录取得有限程序保护" in anchor:
            matched = matched or (
                "摘录" in body and any(term in body for term in ("有限", "仅限"))
                and any(term in body for term in ("保护", "暂停", "限制"))
            )
        if anchor == "卡尔主动停掉已经装车的材料":
            matched = matched or (
                "卡尔" in body
                and any(term in body for term in ("叫停", "停掉", "停下", "刹住", "停住"))
                and "装车" in body
            )
        if anchor == "差额取得独立复核编号":
            matched = matched or (
                "差额" in body
                and any(term in body for term in ("独立复核", "复核员", "复核编号"))
                and "编号" in body
            )
        if anchor == "麦珂撤回自己过早写下的嫌疑判断":
            matched = matched or (
                "麦珂" in body
                and any(term in body for term in ("撤回", "收回", "划掉", "改掉"))
                and any(term in body for term in ("嫌疑", "判断", "结论"))
            )
        must_include_evidence.append({
            "anchor": anchor, "exact": exact,
            "bigram_coverage": round(coverage, 3), "matched": matched,
        })
        if not matched:
            failures.append(f"正文没有兑现章卡关键事实“{anchor}”")
    resolve_evidence: list[dict[str, Any]] = []
    artifact_evidence_by_id: dict[str, dict[str, Any]] = {}
    for artifact_item in (card.get("artifact_creates") or []) + (card.get("artifact_refs") or []):
        if isinstance(artifact_item, dict) and str(artifact_item.get("artifact_id") or "").strip():
            artifact_evidence_by_id[str(artifact_item["artifact_id"])] = artifact_item
    for transition in card.get("must_resolve_this_chapter") or []:
        if not isinstance(transition, dict):
            continue
        evidence = str(transition.get("evidence") or "").strip()
        target = str(transition.get("to") or "").strip()
        artifact_item = artifact_evidence_by_id.get(evidence, {})
        evidence_texts = [
            evidence,
            str(artifact_item.get("display_name") or "").strip(),
            str(artifact_item.get("purpose") or "").strip(),
            str(transition.get("evidence_text") or "").strip(),
        ]
        evidence_terms = [
            term for term in re.findall(
                r"[\u3400-\u9fff]{2,8}|[A-Za-z0-9_.-]{2,}",
                " ".join(value for value in evidence_texts if value),
            )
            if term not in {"麦珂", "玛莎", "维克多", "当场", "此后"}
        ]
        evidence_terms = list(dict.fromkeys(evidence_terms))
        hit_terms = [term for term in evidence_terms if term in body]
        display_name = str(artifact_item.get("display_name") or "").strip()
        matched = (
            bool(target and target in body)
            or bool(display_name and display_name in body)
            or len(hit_terms) >= min(2, len(evidence_terms))
        )
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
            for distinctive in ("后台", "休息室", "控制室", "会议室", "公证处", "法庭"):
                if distinctive in location and distinctive not in keywords:
                    keywords.append(distinctive)
            hit = (
                any(token in body or token.replace("的", "") in normalized_scene_body for token in keywords)
                if keywords else location in body or location.replace("的", "") in normalized_scene_body
            )
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
            if not hit and "场馆" in location:
                venue_markers = ("体育馆", "演出场", "观众席", "入场券", "穹顶")
                hit = any(marker in body for marker in venue_markers)
                if hit:
                    match_mode = "venue_semantics"
            if not hit and "舞台中央" in location:
                hit = "舞台" in body and any(term in body for term in ("灯光", "观众", "穹顶", "演出"))
                if hit:
                    match_mode = "stage_semantics"
            if not hit and "体育馆外广场" in location:
                hit = any(term in body for term in ("体育馆", "广场", "馆外", "入口"))
                if hit:
                    match_mode = "venue_exterior_semantics"
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
        display_core = re.sub(r"\uff08[^\uff09]{1,20}\uff09$", "", display).strip()
        if not hit and display_core:
            hit = display_core in body
        if not hit and "承诺卡" in display and "承诺" in body:
            hit = True
        if not hit and "打字机色带样本" in display and all(term in body for term in ("打字机", "色带")):
            hit = True
        if not hit and "三方签字急救启动令" in display and all(term in body for term in ("三方", "急救")):
            hit = True
        if not hit and "实时数据流记录" in display and any(term in body for term in ("实时", "数据流", "记录", "日志")):
            hit = True
        if not hit and "随机座次总表" in display and any(term in body for term in ("座位表", "座次", "随机座位", "位置表")):
            hit = True
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
            r"麦珂(?P<context>[^。！？]{0,45})[，；]\s*她"
            r"(?:没|不|只|又|却|将|把|正|仍|已|便|忽|站|坐|走|伸|抬|低|垂|转|"
            r"看|听|说|问|答|拿|接|按|握|呼|屏|指|掌|手|脚|眼|肩|脸|唇|背|膝|腕)",
            paragraph,
        )
        antecedent_window = (
            paragraph[: gender_match.end("context")] if gender_match else ""
        )
        if gender_match and not re.search(
            r"玛莎|海伦|弗洛伦斯|瑟琳娜|苏菲亚|莉薇娅|女职员|母亲|女孩|女士|女人",
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
    fast_relaxed_failures = []
    if os.getenv("BODY_FAST_MODE", "").strip() == "1" and failures:
        # Production-first mode: keep safety and continuity firewalls hard,
        # but do not spend repeated relay calls on wording-level card coverage
        # that can be reviewed after a batch is produced.
        hard_failures = []
        relaxed_failures = []
        relaxed_markers = (
            "正文没有兑现章卡关键事实",
            "正文未落到规划场景",
            "正文没有通过现场动作兑现状态转移",
            "有效段落数",
            "正文夹入英文小写叙述词",
        )
        for failure in failures:
            if any(marker in str(failure) for marker in relaxed_markers):
                relaxed_failures.append(str(failure))
            else:
                hard_failures.append(failure)
        fast_relaxed_failures = relaxed_failures
        failures = hard_failures
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
        "fast_mode_relaxed_chapter_failures": fast_relaxed_failures,
        "failures": failures,
    }
    return body, failures, audit


def _resolution_signature(body: str) -> dict[str, str]:
    def pick(options: tuple[str, ...]) -> str:
        return next((item for item in options if item in body), "")
    return {
        "attack": pick(("起诉", "合同", "协议", "伪造文件", "安全规则", "断电", "暴雨")),
        "counter": pick(("签字", "备用光路", "卷轴", "微缩胶片", "条款", "门禁", "证词")),
        "resolver": pick(("法官", "法庭", "记者", "保安", "委员会", "观众", "监管")),
        "opponent_result": pick(("败诉", "狼狈", "被带走", "被揭穿", "失去", "撤回", "哑口无言")),
        "hero_result": pick(("开源", "获得", "保住", "确立", "恢复", "掌握", "自主权")),
    }


def _validate_candidate(
    parsed: dict[str, Any],
    *,
    cluster: dict[str, Any],
    cards: list[dict[str, Any]],
    recent_bodies: dict[int, str] | None = None,
    recent_family_bodies: dict[int, str] | None = None,
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
        fast_min_han = 900 if os.getenv("BODY_FAST_MODE", "").strip() == "1" else MIN_HAN_CHARS
        if han < fast_min_han:
            chapter_failures.append(f"汉字数{han}，低于{fast_min_han}")
        if han > MAX_HAN_CHARS:
            chapter_failures.append(f"汉字数{han}，高于{MAX_HAN_CHARS}")
        if "```" in body or re.search(r"^【[^】]+】", body, flags=re.M):
            chapter_failures.append("正文含Markdown或分节小标题")
        if re.search(r"(?:本章|这一章)(?:主要|讲述|描写)", body):
            chapter_failures.append("正文出现提纲式讲解")
        if body.endswith(("，", "、", "：", ":", ";", "；")):
            chapter_failures.append("正文疑似截断")
        card = next(card for card in cards if int(card["chapter_id"]) == chapter_id)
        # Candidate validation uses the same closed quality gates as the
        # single-chapter path; these are never warning-only diagnostics.
        chapter_failures.extend(_hard_metadata_leak_failures(body))
        chapter_failures.extend(_paragraph_quality_failures(body))
        chapter_failures.extend(_rebirth_subject_failures(body))
        chapter_failures.extend(_character_identity_failures(body, card))
        chapter_failures.extend(_opening_time_failures(body, card))
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
        if longest.size >= 40:
            failures.append(
                f"两章存在{longest.size}字连续重复片段，第二章疑似重演第一章"
            )
        # A character-level exact match catches copy/paste; n-gram overlap also
        # catches paraphrased replays of the same hearing/meeting/hand-off.
        semantic_overlap = semantic_similarity(first, second)
        # The architecture's hard threshold is 0.13. A structurally identical
        # two-chapter replay is also rejected at the lower legacy boundary so
        # an old replay fixture cannot be laundered by small wording changes.
        same_resolution = _resolution_signature(first) == _resolution_signature(second)
        if semantic_overlap >= 0.13 or (
            semantic_overlap >= 0.12 and same_resolution
            and sum(bool(v) for v in _resolution_signature(second).values()) >= 3
        ):
            failures.append(
                f"两章语义片段重合度{semantic_overlap:.2f}过高，第二章疑似换词重演第一章"
            )
        audits["joint_semantic_overlap"] = round(semantic_overlap, 4)
        first_signature = _resolution_signature(first)
        second_signature = _resolution_signature(second)
        audits["resolution_signatures"] = {"first": first_signature, "second": second_signature}
        if first_signature == second_signature and sum(bool(v) for v in second_signature.values()) >= 3:
            failures.append("同一事件簇两章resolution signature重复，第二章疑似重演同一反杀")
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
            "停止", "拒绝", "驳回", "生效", "获准", "取得", "承担", "成为", "保管", "封存",
        )
        required_actions = [term for term in settlement_actions if term in planned_settlement]
        if required_actions and not any(term in second for term in required_actions):
            failures.append(
                "第二章没有通过动作兑现计划中的损失/收益结算；仅有情绪反应不能算结算"
            )
        audits["settlement_action_terms"] = required_actions
        planned_cost = cluster.get("protagonist_cost") or {}
        if isinstance(planned_cost, dict) and planned_cost.get("required"):
            cost_type = str(planned_cost.get("type") or "")
            cost_markers = {
                "opportunity": ("放弃", "错过", "取消", "退出", "窗口"),
                "information": ("暴露", "怀疑", "盯上", "察觉", "准备得太早"),
                "relationship": ("信任", "决定权", "不再替", "拒绝", "裂缝"),
                "health_time": ("暂停", "停演", "休息", "复核", "恢复"),
                "strategic": ("提前", "转向", "接管", "资源", "更强"),
                "setback": ("未能", "没能", "只拿到", "输", "受挫"),
            }.get(cost_type, ("代价", "失去", "放弃"))
            if not any(marker in second for marker in cost_markers):
                failures.append(f"主角代价未现场兑现：{cost_type}")
            audits["planned_cost"] = planned_cost
        flaw = cluster.get("character_flaw_beat") or {}
        if isinstance(flaw, dict) and flaw.get("mode") not in (None, "none"):
            flaw_markers = ("安排", "撤销", "替", "权限", "决定", "选择权", "授权")
            if not any(marker in first + second for marker in flaw_markers):
                failures.append(f"控制欲人物弧未现场兑现：{flaw.get('mode')}")
            if flaw.get("mode") in {"consequence", "repair", "growth"} and not any(marker in first + second for marker in ("选择权", "授权", "共同决定", "交还", "自己决定")):
                failures.append(f"控制欲人物弧缺少关系后果或授权动作：{flaw.get('mode')}")
            audits["character_flaw_beat"] = flaw
        role_text = " ".join(str(card.get("chapter_role_v2") or "") for card in cards)
        # Planning cards often describe how Ma Ke privately uses past-life
        # knowledge, but that is not a requirement to repeat memory language
        # in every later procedural chapter.  Only rebirth-confirmation roles
        # require an explicit memory beat; otherwise the firewall below checks
        # ownership if such language appears, without forcing the model to add
        # it and risk a leak.
        info_gap_required = "rebirth" in role_text.lower()
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
            if overlap >= 0.13:
                failures.append(
                    f"第{chapter_id}章与前20章中的第{prior_id}章语义重合度{overlap:.2f}过高，疑似重演旧事件"
                )
            elif overlap >= 0.115:
                audits.setdefault("manual_review_required", []).append(
                    f"第{chapter_id}章与第{prior_id}章语义重合度{overlap:.2f}处于人工复核区间"
                )
            if _resolution_signature(prior_body) == _resolution_signature(body):
                signature = _resolution_signature(body)
                if sum(bool(value) for value in signature.values()) >= 3:
                    failures.append(f"第{chapter_id}章与第{prior_id}章resolution signature重复，疑似重复结算")
    audits["recent_twenty_chapter_semantic_comparison"] = prior_repetition
    family_repetition: list[dict[str, Any]] = []
    for chapter_id, body in bodies.items():
        for prior_id, prior_body in sorted((recent_family_bodies or {}).items()):
            if prior_id >= chapter_id or not prior_body:
                continue
            overlap = semantic_similarity(prior_body, body)
            family_repetition.append({
                "chapter_id": chapter_id,
                "prior_chapter_id": prior_id,
                "semantic_overlap": round(overlap, 4),
            })
            if overlap >= 0.13:
                failures.append(
                    f"第{chapter_id}章与同情节族近40章中的第{prior_id}章语义重合度{overlap:.2f}过高"
                )
    audits["same_plot_family_recent_forty_comparison"] = family_repetition
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
    synopses_path = output_dir / "chapter_synopses_v5_qwen_500.json"
    outline_path = output_dir / "global_story_outline_v5_qwen_500.json"
    for path in (events_path, cards_path, synopses_path, outline_path):
        if not path.exists():
            raise FileNotFoundError(f"缺少正文权威输入：{path}")
    events = _load_json(events_path)
    raw_cards = _load_json(cards_path)
    raw_synopses = _load_json(synopses_path)
    outline = _load_json(outline_path)
    if not isinstance(events, list) or not events or len(events) > 250:
        raise ValueError("event_clusters_v2.json 必须包含1—250个连续事件簇。")
    if not isinstance(raw_cards, list) or len(raw_cards) != len(events) * 2:
        raise ValueError("master_ctx_cards_v2.json 必须与事件簇形成连续的两章一事件前缀。")
    if not isinstance(raw_synopses, list) or len(raw_synopses) != len(raw_cards):
        raise ValueError("chapter_synopses_v5_qwen_500.json 必须覆盖全部500章。")
    expected_event_ids = [f"EC{index:03d}" for index in range(1, len(events) + 1)]
    if [str(event.get("cluster_id") or "") for event in events] != expected_event_ids:
        raise ValueError("event_clusters_v2.json 必须从EC001开始连续，禁止跳簇生成正文。")
    expected_chapters = list(range(1, len(raw_cards) + 1))
    if [int(card.get("chapter_id") or 0) for card in raw_cards] != expected_chapters:
        raise ValueError("master_ctx_cards_v2.json 必须从第1章开始连续，禁止跳章生成正文。")
    synopsis_map = {int(item.get("chapter_id") or 0): item for item in raw_synopses}
    if sorted(synopsis_map) != expected_chapters:
        raise ValueError("chapter_synopses_v5_qwen_500.json 必须从第1章开始连续。")
    cards = {}
    for card in raw_cards:
        chapter_id = int(card["chapter_id"])
        synopsis = synopsis_map[chapter_id]
        if str(card.get("cluster_id") or "") != str(synopsis.get("cluster_id") or ""):
            raise ValueError(f"第{chapter_id}章章卡与梗概事件簇不一致。")
        if str(card.get("timeline_start") or "") != str(synopsis.get("timeline_start") or ""):
            raise ValueError(f"第{chapter_id}章章卡与梗概日期不一致。")
        merged = dict(card)
        # Keep the frozen 1—270 card payload byte-for-byte compatible with its
        # v15 prefix lock.  The rebuilt tail explicitly consumes the third
        # authoritative view; the legacy prefix only needs validation.
        if chapter_id >= 271:
            merged["_authoritative_synopsis"] = synopsis
        cards[chapter_id] = merged
    return events, cards, outline


def _known_names(card: dict[str, Any]) -> list[str]:
    values = list(card.get("participants") or []) + list(card.get("allowed_roles") or [])
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _body_plan_preflight(
    events: list[dict[str, Any]], card_map: dict[int, dict[str, Any]]
) -> list[str]:
    """Catch hard plan contradictions before a writer sees a chapter."""
    failures: list[str] = []
    previous_date = ""
    created_at: dict[str, int] = {}
    created_specs: dict[str, dict[str, Any]] = {}
    for chapter_id, card in sorted(card_map.items()):
        for item in card.get("artifact_creates") or []:
            if isinstance(item, dict) and item.get("artifact_id"):
                created_at[str(item["artifact_id"])] = chapter_id
                created_specs[str(item["artifact_id"])] = item
    for chapter_id in sorted(card_map):
        card = card_map[chapter_id]
        current_date = str(card.get("timeline_start") or "")
        rebirth_reset = (
            chapter_id == 2
            and ("previous_life" in str(card.get("chapter_role_v2") or "").lower()
                 or "rebirth" in str(card.get("chapter_role_v2") or "").lower())
        )
        if current_date and previous_date and current_date < previous_date and not rebirth_reset:
            failures.append(f"timeline regression before chapter {chapter_id}: {previous_date}->{current_date}")
        if current_date:
            previous_date = current_date
        for item in card.get("artifact_refs") or []:
            if isinstance(item, dict) and item.get("artifact_id"):
                artifact_id = str(item["artifact_id"])
                origin = created_at.get(artifact_id)
                if origin is None:
                    failures.append(f"artifact {artifact_id} referenced but never created in chapter {chapter_id}")
                elif origin > chapter_id:
                    failures.append(f"artifact {item['artifact_id']} referenced before creation in chapter {chapter_id}")
                else:
                    spec = created_specs.get(artifact_id) or {}
                    permission = str(item.get("required_permission") or "use_as_evidence_within_scope")
                    grants = {str(value) for value in spec.get("granted_permissions") or []}
                    denied = {str(value) for value in spec.get("does_not_grant") or []}
                    if permission not in grants:
                        failures.append(
                            f"ARTIFACT_SCOPE_FATAL: chapter {chapter_id} artifact {artifact_id} "
                            f"does not grant {permission}; grants={sorted(grants)}"
                        )
                    if permission in denied:
                        failures.append(
                            f"ARTIFACT_SCOPE_FATAL: chapter {chapter_id} artifact {artifact_id} explicitly denies {permission}"
                        )
    for event in events:
        flaw = event.get("character_flaw_beat")
        if isinstance(flaw, dict):
            required = ("trigger", "protagonist_action", "immediate_benefit", "hidden_cost", "who_pushes_back", "future_payoff_cluster")
            missing = [field for field in required if not str(flaw.get(field) or "").strip()]
            who = str(flaw.get("who_pushes_back") or "")
            participants = set(map(str, event.get("main_characters") or []))
            for milestone in event.get("two_chapter_structure") or []:
                participants.update(map(str, milestone.get("participants") or []))
            if missing or who not in participants:
                failures.append(
                    f"FLAW_BEAT_PARTICIPANT_FATAL: {event.get('cluster_id')} missing={missing} who={who}"
                )
    return failures


def _victory_budget_failures(events: list[dict[str, Any]]) -> list[str]:
    """Require explicit outcomes and bound both effortless wins and setbacks."""
    failures: list[str] = []
    allowed = {
        "clean_win", "small_win", "partial_win", "costly_win", "stalemate",
        "setback_with_gain", "major_win", "decisive_win",
    }
    for event in events:
        outcome = str(event.get("outcome_type") or "")
        if outcome not in allowed:
            failures.append(f"OUTCOME_TYPE_FATAL: {event.get('cluster_id')}缺少合法outcome_type")
    for start in range(0, len(events) - 7):
        window = events[start:start + 8]
        typed = [str(event.get("outcome_type") or "") for event in window]
        non_clean = sum(value != "clean_win" for value in typed)
        if non_clean < 2:
            failures.append(f"VICTORY_BUDGET: EC{start + 1:03d}-EC{start + 8:03d}非纯胜利事件不足2个")
    for start in range(0, len(events) - 4):
        window = events[start:start + 5]
        setbacks = sum(str(event.get("outcome_type") or "") in {"setback", "setback_with_gain"} for event in window)
        if setbacks > 1:
            failures.append(f"VICTORY_BUDGET: EC{start + 1:03d}-EC{start + 5:03d}挫折超过1个")
    for start in range(0, len(events) - 11):
        window = events[start:start + 12]
        large = sum(str(event.get("outcome_type") or "") in {"major_win", "decisive_win"} for event in window)
        if large > 2:
            failures.append(f"VICTORY_BUDGET: EC{start + 1:03d}-EC{start + 12:03d}重大胜利超过2个")
    return failures


def _hard_character_state_from_context(
    card: dict[str, Any], context: str
) -> dict[str, dict[str, Any]]:
    """Expose card-compiled state; retrieval text is evidence, never authority."""
    snapshot: dict[str, dict[str, Any]] = {}
    text = str(context or "")
    for name in _known_names(card):
        positions = [m.start() for m in re.finditer(re.escape(name), text)]
        nearby = " ".join(text[max(0, p - 180):p + 260] for p in positions[-3:])
        lifecycle = card.get("character_lifecycle") or {}
        transitions = [
            item for item in card.get("state_transitions") or []
            if isinstance(item, dict)
            and (str(item.get("entity_id") or "") in {name, "CHAR_026AC753E27A"} or name in {"麦珂", "麦珂·杰森"})
        ]
        snapshot[name] = {
            "employment_status": "as_compiled_in_structured_state",
            "current_role": "as_explicitly_planned",
            "roles": list(card.get("allowed_roles") or []),
            "authority_scope": "only_current_card_and_artifact_grants",
            "access_permissions": [
                permission
                for artifact in card.get("artifact_refs") or [] if isinstance(artifact, dict)
                for permission in [str(artifact.get("required_permission") or "use_as_evidence_within_scope")]
            ],
            "forbidden_permissions": ["任何章卡或artifact未显式授予的权限"],
            "legal_status": "as_compiled_in_state_transitions",
            "knowledge_state": "sole_rebirth_knower" if name in ("麦珂", "麦珂·杰森") else "no_rebirth_knowledge",
            "birth_date": lifecycle.get("birth_date") if name in ("麦珂", "麦珂·杰森") else None,
            "sex": "male" if name in ("麦珂", "麦珂·杰森") else "not_established",
            "current_year": int(str(card.get("timeline_start") or "0000")[:4] or 0),
            "life_stage": lifecycle.get("life_stage") if name in ("麦珂", "麦珂·杰森") else "not_established",
            "active_costs": card.get("active_costs") or [],
            "state_transitions_this_chapter": transitions,
            "last_state_evidence": nearby[-500:],
        }
        if name in ("麦珂", "麦珂·杰森"):
            snapshot[name]["current_age"] = _protagonist_age(card)
    return snapshot


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
    for prior_id in range(max(1, span_start - 20), span_start):
        path = output_dir / "chapters" / f"chapter_{prior_id:03d}.txt"
        if path.is_file():
            recent_bodies[prior_id] = path.read_text(encoding="utf-8").strip()
    recent_family_bodies = {}
    for prior_id in range(max(1, span_start - 40), span_start):
        path = output_dir / "chapters" / f"chapter_{prior_id:03d}.txt"
        if path.is_file():
            recent_family_bodies[prior_id] = path.read_text(encoding="utf-8").strip()
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
        recent_family_bodies=recent_family_bodies,
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
    cluster_feedback: str = "",
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
        prior_failure = cluster_feedback
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
                if prior_audit.get("semantic_rejected") or prior_audit.get("continuity_rejected"):
                    continue
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
    for prior_id in range(max(1, span[0] - 20), span[0]):
        prior_path = output_dir / "chapters" / f"chapter_{prior_id:03d}.txt"
        if prior_path.is_file():
            recent_bodies[prior_id] = prior_path.read_text(encoding="utf-8").strip()
    recent_family_bodies = {}
    for prior_id in range(max(1, span[0] - 40), span[0]):
        prior_path = output_dir / "chapters" / f"chapter_{prior_id:03d}.txt"
        if prior_path.is_file():
            recent_family_bodies[prior_id] = prior_path.read_text(encoding="utf-8").strip()
    _, joint_failures, joint_semantic_audit = _validate_candidate(
        combined, cluster=cluster, cards=cards, recent_bodies=recent_bodies,
        recent_family_bodies=recent_family_bodies,
    )
    if os.getenv("BODY_FAST_MODE", "").strip() == "1" and joint_failures:
        # Production-first mode keeps deterministic safety gates, while
        # allowing stylistic/repetition findings to be recorded without
        # forcing another expensive model round-trip.
        hard_joint_failures = []
        relaxed_joint_failures = []
        hard_markers = (
            "元数据", "重生知识", "角色身份", "时间线", "日期",
            "权限", "授权", "年龄", "不可逆", "内部章节号", "规划泄漏",
            "事件簇绑定", "核心推进点", "章节开场",
        )
        for failure in joint_failures:
            failure_text = str(failure)
            if any(marker in failure_text for marker in hard_markers):
                hard_joint_failures.append(failure_text)
            else:
                relaxed_joint_failures.append(failure_text)
        if relaxed_joint_failures:
            joint_semantic_audit["fast_mode_relaxed_joint_failures"] = relaxed_joint_failures
        joint_failures = hard_joint_failures
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

    semantic_critic, critic_failures, critic_meta = _run_semantic_critic(
        cluster=cluster, cards=cards, bodies=bodies,
        graph_contexts=graph_contexts, model=model, recent_bodies=recent_bodies,
    )
    joint_semantic_audit["semantic_critic"] = semantic_critic
    joint_semantic_audit["semantic_critic_call"] = critic_meta
    if critic_failures:
        fast_mode = os.getenv("BODY_FAST_MODE", "").strip() == "1"
        if fast_mode:
            # User-directed production mode: deterministic P0/P1 gates above
            # still reject identity, timeline, metadata, and hard boundary
            # violations.  The optional critic is advisory here, including
            # when the relay returns malformed/unavailable JSON.
            joint_semantic_audit["fast_mode_relaxed_critic_failures"] = critic_failures
            critic_failures = []
        if not critic_failures:
            pass
    if critic_failures:
        for rejected_id in span:
            rejected_raw_path = Path(raw_path_by_chapter[str(rejected_id)])
            rejected_audit_path = audit_dir / f"{rejected_raw_path.stem.removesuffix('_raw')}.json"
            rejected_audit = _load_json(rejected_audit_path) if rejected_audit_path.exists() else {}
            rejected_audit.update({
                "accepted": False,
                "semantic_rejected": True,
                "semantic_critic_failures": critic_failures,
            })
            _save_json(rejected_audit_path, rejected_audit)
        raise RuntimeError(
            f"{cluster['cluster_id']}语义批评器未通过：{'；'.join(critic_failures)}"
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
        for rejected_id in span:
            rejected_raw_path = Path(raw_path_by_chapter[str(rejected_id)])
            rejected_audit_path = audit_dir / f"{rejected_raw_path.stem.removesuffix('_raw')}.json"
            rejected_audit = _load_json(rejected_audit_path) if rejected_audit_path.exists() else {}
            rejected_audit.update({
                "accepted": False,
                "continuity_rejected": True,
                "continuity_failures": continuity_failures,
            })
            _save_json(rejected_audit_path, rejected_audit)
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
    quarantine_dir = output_dir / "body_generation" / "quarantine"
    active_quarantine = [p for p in quarantine_dir.glob("rewrite_pending_*") if p.is_dir()]
    if active_quarantine and any(_cluster_number(str(item.get("cluster_id") or "")) >= 136 for item in selected):
        sync_report_path = output_dir / "body_generation" / "graph_sync_v15_report.json"
        sync_report = _load_json(sync_report_path) if sync_report_path.is_file() else {}
        boundary = sync_report.get("story_chapters") if isinstance(sync_report, dict) else {}
        cleared = bool(sync_report.get("passed")) and boundary == {
            "count": 270, "min": 1, "max": 270, "tail": 0,
        }
        if not cleared:
            raise RuntimeError(
                "存在旧正文隔离批次，且v15图谱清理报告未证明正式记忆停在第270章；"
                "禁止生成或写入StoryMemory。"
            )
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
    plan_failures.extend(_body_plan_preflight(events, card_map))
    for card in ordered_cards:
        plan_failures.extend(_age_semantic_conflicts(card))
    plan_failures.extend(_victory_budget_failures(events))
    if min(_cluster_number(str(item.get("cluster_id") or "")) for item in selected) >= 136:
        prefix_ok, prefix_reason = _verify_frozen_prefix_lock(
            output_dir, events, ordered_cards,
        )
        if not prefix_ok:
            plan_failures.append(f"FROZEN_PREFIX_LOCK_FATAL: {prefix_reason}")
        else:
            legacy_prefix_failures = [
                failure for failure in plan_failures
                if not _failure_reaches_rebuilt_tail(failure)
            ]
            plan_failures = [
                failure for failure in plan_failures
                if _failure_reaches_rebuilt_tail(failure)
            ]
            if legacy_prefix_failures:
                print(
                    "[frozen-prefix] EC001—EC135/第001—270章哈希匹配；"
                    f"隔离旧模式规划债务{len(legacy_prefix_failures)}项，"
                    "新尾段与跨边界错误仍按FATAL处理。",
                    flush=True,
                )
    if args.allow_plan_warnings:
        # Severity is decided by a closed code/pattern list.  A message merely
        # beginning with EC/FS/CS/chapter is never enough to downgrade it.
        warning_patterns = (
            ("FORESHADOW_COVERAGE_WARNING", re.compile(r"FS\d+未在(?:种植|回收)阶段")),
            ("CAUSAL_COVERAGE_WARNING", re.compile(r"250事件未覆盖因果主链")),
            ("SOURCE_ANCHOR_WARNING", re.compile(r"历史锚点.*(?:覆盖|缺少)")),
        )
        classified = []
        fatal = []
        for failure in plan_failures:
            message = str(failure)
            code = next((code for code, pattern in warning_patterns if pattern.search(message)), None)
            item = {
                "code": code or "PLAN_VALIDATION_FATAL",
                "severity": "WARNING" if code else "FATAL",
                "message": message,
            }
            classified.append(item)
            if item["severity"] == "FATAL":
                fatal.append(message)
        plan_failures = fatal
        warnings = [item for item in classified if item["severity"] == "WARNING"]
        if warnings:
            print(
                "[plan-warning] 已放行结构化WARNING，共"
                f"{len(warnings)}条；前8条："
                + " | ".join(item["message"] for item in warnings[:8]),
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
        cluster_feedback = ""
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
                    cluster_feedback=cluster_feedback if cluster_attempt > 1 else "",
                )
                break
            except RuntimeError as exc:
                cluster_feedback = str(exc)[-6000:]
                retryable = (
                    "两章联合校验失败",
                    "语义批评器未通过",
                    "图谱连续性校验失败",
                )
                if not any(token in str(exc) for token in retryable) or cluster_attempt >= cluster_attempts:
                    raise
                print(
                    f"[pair-retry] {cluster.get('cluster_id')} "
                    f"cluster_attempt={cluster_attempt}/{cluster_attempts}：{exc}",
                    flush=True,
                )


if __name__ == "__main__":
    main()

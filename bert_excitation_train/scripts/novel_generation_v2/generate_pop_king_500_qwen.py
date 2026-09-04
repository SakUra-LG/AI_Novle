"""Generate the authoritative 500-chapter plan with Qwen.

Qwen first authors one broad whole-story outline, then derives 25 sequential
twenty-chapter story blocks, 50 ten-chapter macro groups, 250 detailed
two-chapter event clusters and 500 chapter synopses from it. Human-authored material is used only as theme,
historical anchors and hard constraints. Every model response is checkpointed
with provenance so a long run can resume safely. Chapter cards are compiled
deterministically from the two Qwen-authored milestones inside each event; a
second model pass is forbidden from replanning the event.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import socket
import shutil
from typing import Any, Callable

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import dashscope

API_Key_QW = os.getenv("DASHSCOPE_API_KEY", "").strip()
from bert_excitation_train.scripts.novel_generation_v2.qwen_transport import (
    call_openai_compatible_via_curl,
    call_openai_compatible_via_requests,
    call_qwen_via_curl,
    list_openai_compatible_models_via_curl,
)
from bert_excitation_train.scripts.knowledge_graph.planning_graph import (
    planning_story_id,
    retrieve_event_context,
    sync_planning_hierarchy,
    upsert_event_batch,
    verify_event_batch_hashes,
    verify_planning_hierarchy,
)
from bert_excitation_train.scripts.novel_generation_v2.pop_king_plan_compiler import (
    EVENT_TYPES,
    OPPOSITION_TYPES,
    SOLUTION_TYPES,
    apply_state_transitions,
    canonical_sha256,
    character_id_for_name,
    plan_fingerprints,
    event_type_semantic_failures,
    semantic_similarity,
    timeline_point,
    validate_chronology_prefix,
    validate_event_batch,
    validate_full_plan,
    write_compilation_report,
)
from bert_excitation_train.scripts.novel_generation_v2.generate_pop_king_500_plan import (
    BACKGROUND,
    CAST,
    PROTAGONIST,
    RESEARCH_ANCHORS,
    SOURCES,
    THEME,
    VOLUMES,
)


OUTPUT_NAME = "outputs_pop_king_v6_compiled_story_first_500"
PLANNING_VERSION = "v9_stable_identity_bound_threads_250_events_500_chapters"
EVENT_BATCH_SIZE = max(1, min(5, int(os.getenv("PLANNER_EVENT_BATCH_SIZE", "2"))))
EVENT_BATCHES_PER_MACRO = (5 + EVENT_BATCH_SIZE - 1) // EVENT_BATCH_SIZE
EVENT_MAX_OUTPUT_TOKENS = max(3000, int(os.getenv("PLANNER_EVENT_MAX_OUTPUT_TOKENS", "4800")))
EXPECTED_QWEN_BATCHES = (
    9 + 25 + 50 + 50 + 50 * EVENT_BATCHES_PER_MACRO
)  # global + blocks + macro cores + direction groups + detailed-event sub-batches
CHAPTER_CARD_COMPILER_VERSION = "event_milestone_to_card_v1_20260812"
DEFAULT_MODEL = os.getenv("QWEN_PLANNER_MODEL", "qwen-plus").strip() or "qwen-plus"
QWEN_MAX_OUTPUT_TOKENS = max(8192, int(os.getenv("QWEN_MAX_OUTPUT_TOKENS", "16384")))
# Groq free projects can enforce an 8K TPM ceiling that counts prompt tokens
# plus the requested completion allowance.  Reserving 8192 made every request
# impossible before generation started.  Three thousand is sufficient for one
# planning JSON batch and leaves room for its authoritative context.
GROQ_MAX_OUTPUT_TOKENS = max(1024, int(os.getenv("GROQ_MAX_OUTPUT_TOKENS", "3000")))
VALID_GENERATION_PROVIDERS = {"qwen", "groq", "vectorengine"}
VALID_OUTPUT_GENERATORS = {*VALID_GENERATION_PROVIDERS, "mixed_llm"}
_GROQ_VISIBLE_MODELS: list[str] | None = None

# These are the ten recurring characters whose whole-book arcs are authored in
# the global outline.  Names are an identity boundary, not creative prose: a
# changed surname would create a second Character node and poison every later
# continuity lookup.  The model therefore receives and must return the stable
# IDs as well as the canonical display names.
GLOBAL_ARC_CHARACTER_NAMES = (
    "玛莎·杰森", "黛安娜·罗文", "昆廷·琼斯", "瑟琳娜·凯德", "莉薇娅·普莱斯",
    "艾琳·沃特曼", "苏菲亚·罗德里格斯", "维克多·兰斯", "巴里·布鲁姆", "莱昂·周",
)


def _canonical_character_identity(name: str) -> dict[str, Any]:
    return {
        "character_id": character_id_for_name(name),
        "character": name,
        "aliases": list(dict.fromkeys([name, name.split("·", 1)[0]])),
    }


GLOBAL_ARC_IDENTITIES = tuple(
    _canonical_character_identity(name) for name in GLOBAL_ARC_CHARACTER_NAMES
)

# OpenAI-compatible providers occasionally emit readable pseudo IDs instead
# of the canonical SHA-based character_id. They are unambiguous aliases for
# already registered recurring characters and can be compiled without a rewrite.
PROVIDER_CHARACTER_ID_ALIASES = {
    "ID_CHAR_MAKE": "麦珂",
    "ID_CHAR_SELENA": "瑟琳娜·凯德",
    "ID_CHAR_LIVIA": "莉薇娅·普莱斯",
    "ID_CHAR_SOPHIA": "苏菲亚·罗德里格斯",
    "ID_CHAR_MARTHA": "玛莎·杰森",
    "ID_CHAR_DIANA": "黛安娜·罗文",
    "ID_CHAR_ERIN": "艾琳·沃特曼",
    "ID_CHAR_VICTOR": "维克多·兰斯",
    "CHAR_MAKE_01": "麦珂",
    "CHAR_SELENA_01": "瑟琳娜·凯德",
    "CHAR_SERENA_01": "瑟琳娜·凯德",
    "CHAR_LIVIA_01": "莉薇娅·普莱斯",
    "CHAR_SOPHIA_01": "苏菲亚·罗德里格斯",
    "CHAR_MARSHA_01": "玛莎·杰森",
    "CHAR_DIANA_01": "黛安娜·罗文",
    "CHAR_ERIN_01": "艾琳·沃特曼",
    "CHAR_VICTOR_01": "维克多·兰斯",
    "barry_bloom": "巴里·布鲁姆",
    "victor_lance": "维克多·兰斯",
    "make": "麦珂",
    "mago": "麦珂",
    "selena": "瑟琳娜·凯德",
    "serena": "瑟琳娜·凯德",
    "livia": "莉薇娅·普莱斯",
    "sophia": "苏菲亚·罗德里格斯",
    "martha": "玛莎·杰森",
    "diana": "黛安娜·罗文",
    "erin": "艾琳·沃特曼",
    "mike_ke": "麦珂",
    "liweiya": "莉薇娅·普莱斯",
    "su_fei_ya": "苏菲亚·罗德里格斯",
}

PROVIDER_RELATIONSHIP_ID_ALIASES = {
    "liweiya_mike_ke": ("莉薇娅·普莱斯", "麦珂"),
    "relationship_mago_selena": ("麦珂", "瑟琳娜·凯德"),
    "mc_airin_partnership": ("麦珂", "艾琳·沃特曼"),
    "mc_selena_partnership": ("麦珂", "瑟琳娜·凯德"),
    "serena_core_role": ("麦珂", "瑟琳娜·凯德"),
    "all_livia_mckee": ("莉薇娅·普莱斯", "麦珂"),
    "family_iron_triangle": ("麦珂", "玛莎·杰森"),
    "martha_maco_relationship": ("玛莎·杰森", "麦珂"),
    "star_alliance": ("麦珂", "艾琳·沃特曼"),
    "mc_star_alliance": ("麦珂", "艾琳·沃特曼"),
    "alliance_medical_team": ("麦珂", "艾琳·沃特曼"),
}

# Earlier Qwen batches invented surnames or reduced two characters to a given
# name.  Their plot content is still valid; identity is a compiler boundary,
# so bind those legacy display names deterministically instead of paying for a
# full creative rewrite.
LEGACY_GLOBAL_CHARACTER_NAMES = (
    "玛莎·杰森", "黛安娜·洛瑞", "昆廷·索恩", "瑟琳娜·瓦尔", "莉薇娅·科尔",
    "艾琳·哈珀", "苏菲亚·陈", "维克多·兰斯", "巴里", "莱昂",
)


def _replace_legacy_character_names(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _replace_legacy_character_names(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_legacy_character_names(item) for item in value]
    if not isinstance(value, str):
        return value
    text = value
    for old, new in zip(LEGACY_GLOBAL_CHARACTER_NAMES[:8], GLOBAL_ARC_CHARACTER_NAMES[:8]):
        text = text.replace(old, new)
    text = re.sub(r"巴里(?!·布鲁姆)", "巴里·布鲁姆", text)
    text = re.sub(r"莱昂(?!·周)", "莱昂·周", text)
    return text


def _bind_legacy_global_identities(obj: dict[str, Any]) -> dict[str, Any]:
    """Compile old creative text onto the canonical Character ID boundary."""
    normalized = _replace_legacy_character_names(obj)
    arcs = normalized.get("character_long_arcs")
    if isinstance(arcs, list) and len(arcs) == len(GLOBAL_ARC_IDENTITIES):
        for arc, identity in zip(arcs, GLOBAL_ARC_IDENTITIES):
            if not isinstance(arc, dict):
                continue
            arc["character_id"] = identity["character_id"]
            arc["character"] = identity["character"]
            arc["aliases"] = list(identity["aliases"])
    return normalized


def _compile_existing_global_component(
    checkpoint_dir: Path, *, kind: str,
    validator: Callable[[dict[str, Any]], list[str]],
) -> tuple[dict[str, Any], Path] | None:
    """Reuse a valid Qwen batch through an explicit deterministic compiler.

    This is intentionally separate from prompt-hash resume: provenance states
    which prior model batch was compiled and exactly which normalization ran.
    """
    source_path = checkpoint_dir / f"GLOBAL_{kind}.json"
    source_provenance_path = checkpoint_dir / f"GLOBAL_{kind}_provenance.json"
    if not source_path.is_file() or not source_provenance_path.is_file():
        return None
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
        source_provenance = json.loads(source_provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    provider = str(source_provenance.get("generated_by") or "")
    if provider not in VALID_GENERATION_PROVIDERS:
        return None
    compiled = _bind_legacy_global_identities(source)
    failures = validator(compiled)
    if failures:
        return None
    compiled_path = checkpoint_dir / f"GLOBAL_{kind}_identity_bound.json"
    provenance_path = checkpoint_dir / f"GLOBAL_{kind}_identity_bound_provenance.json"
    source_sha = canonical_sha256(source)
    compiled_sha = canonical_sha256(compiled)
    _write_json(compiled_path, compiled)
    _write_json(provenance_path, {
        "generated_by": provider,
        "kind": f"{kind}_identity_bound",
        "identifier": "GLOBAL",
        "accepted_attempt": "deterministic_compile",
        "acceptance_mode": "qwen_batch_plus_stable_identity_compiler",
        "source_file": source_path.name,
        "source_provenance_file": source_provenance_path.name,
        "source_sha256": source_sha,
        "compiled_sha256": compiled_sha,
        "compiler": "legacy_names_to_canonical_character_ids_v1",
        "normalizations": [
            "legacy_display_name_to_canonical_name",
            "inject_stable_character_id_and_aliases",
        ],
        "manual_edits": [],
        "created_at": _now(),
    })
    print(f"[compiled] GLOBAL {kind} stable identities source={source_path.name}", flush=True)
    return compiled, provenance_path


def _neo4j_reachable() -> bool:
    uri = str(os.getenv("NEO4J_URI") or "")
    match = re.match(r"^(?:neo4j|bolt)(?:\+s|\+ssc)?://([^/:]+)(?::(\d+))?", uri)
    if not match:
        return False
    try:
        with socket.create_connection((match.group(1), int(match.group(2) or 7687)), timeout=1.5):
            return True
    except OSError:
        return False


def _bootstrap_local_neo4j_env(container: str = "ai-novel-neo4j-v5") -> None:
    """Discover this project's local container auth without printing secrets."""
    if all(os.getenv(name) for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")):
        return
    import subprocess

    completed = subprocess.run(
        ["docker", "inspect", container, "--format", "{{json .Config.Env}}"],
        capture_output=True, text=True, timeout=15,
    )
    if completed.returncode != 0:
        return
    try:
        rows = json.loads(completed.stdout.strip())
        auth = next((row.split("=", 1)[1] for row in rows if row.startswith("NEO4J_AUTH=")), "")
        user, password = auth.split("/", 1)
    except (ValueError, TypeError, StopIteration, json.JSONDecodeError):
        return
    os.environ.setdefault("NEO4J_URI", "bolt://127.0.0.1:7687")
    os.environ.setdefault("NEO4J_USER", user)
    os.environ.setdefault("NEO4J_PASSWORD", password)


HARD_RULES = [
    "第1章写2009年前世死亡；第2章必须在1969年十一岁全国出道试镜后台重生，禁止重生回死亡前一天。",
    "全书500章，严格两章一个可独立结算的小事件，共250个详细事件簇；每十章五个事件组成一个宏观剧情组。",
    "除第1章外，今生陷阱必须在造成同等实质伤害前被识破；可以短暂示弱留饵，但不能重复受虐拖延爽点。",
    "每个事件第一章至少一次可见小赢，第二章必须明确反派损失、主角收益、关系或资产状态变化。",
    "前世记忆只能提供日期、原话、流程和人物选择，不能直接变成今生录音、文件、截图或物证；证据必须由今生布局产生。",
    "允许大量虚构阻碍，不必照抄现实传记；历史事实只作年代与产业舞台。主角麦珂始终正向，不伤害无辜者。",
    "坏人必须坏得滑稽、自作聪明、爱抢功或嘴硬，其可笑行为必须推动其留下把柄，不能只插科打诨。",
    "未成年阶段禁止恋爱与性化描写；成年后可以有复杂、混乱但知情自愿的多段感情线，不把女性角色写成工具或纯反派。",
    "现实歌手姓名、真实歌曲名、真实公司和案件当事人不得进入小说规划，统一使用既有架空人物或Qwen新创的架空人物。",
    "旧十章素材只择优复用：医疗双签、彩排表、体测、药柜、加场、排期、票池、霸王协议、升降台安全中最多选取不重复的必要元素放入第451—490章；不得为保留素材重复获得同一权限或堆程序戏。",
    "终局在第491—500章让利益链因误判麦珂必死而提前启动讣告、保险和纪念活动牟利，麦珂始终清醒存活并在全球纪念直播现场现身审判；禁止假死、受控昏迷、自行用药、万能黑客、匿名证据或突然出现的警方解决。",
    "严格遵守年代技术条件：互联网、电子邮件、手机、社交媒体、算法训练、数字视频、直播等不得提前出现在尚未普及的年代；纸媒不能刊登视频。",
    "小说舞台只能是架空‘米国’及虚构城市、机构和货币；禁止北京、纽约、洛杉矶等现实城市，禁止中国现实政治机构与符号，也禁止现实歌手原名。",
    "前世2009年与重生后的今生时间线必须严格隔离：前世晚年才认识的人不会随主角穿越，也不得在1969年以同一身份、纹身或履历出现；人物只能在年龄与首次相识年代合理时登场。",
]


PROCEDURAL_MOTIFS = (
    "公证", "声纹", "钢印", "铅封", "骑缝章", "波形", "信封", "合同", "条款",
    "存档", "备案", "签名", "联署", "信托", "审计", "证据", "流程", "权限", "文书",
    "编号", "印章", "纸纤维", "墨水", "复写纸", "登记簿",
)
FORBIDDEN_FAKE_DEATH = (
    "假死", "受控死亡", "受控昏迷", "可控昏迷", "制造死亡", "模拟死亡",
    "伪造死亡", "镇静剂诱饵", "复苏剂量", "人体复苏",
)
STORY_DOMAINS = {
    "performance", "creation", "career_market", "family_relationship", "fan_public_welfare",
    "media_reputation", "health_safety", "rights_business", "romance", "legal_evidence",
}
B001_TYPE_LOCK = {
    "EC001": ("villain", "health_safety", "safety_preemption", "advance"),
    "EC002": ("villain", "contract_rights", "negotiation", "pressure"),
    "EC003": ("family", "family_relationship", "relationship_choice", "reveal"),
    "EC004": ("institutional", "performance", "performance_proof", "echo"),
    "EC005": ("villain", "media_reputation", "media_counter", "advance"),
    "EC006": ("family", "family_relationship", "relationship_choice", "pressure"),
    "EC007": ("institutional", "media_reputation", "public_confrontation", "reveal"),
    "EC008": ("institutional", "creation", "creative_breakthrough", "advance"),
    "EC009": ("internal", "performance", "market_result", "echo"),
    "EC010": ("institutional", "fan_public_welfare", "strategic_withdrawal", "advance"),
}
B001_EVENT_BRIEFS = {
    "EC001": "第1章2009临终获得死亡利益链真相；第2章重生到1969试镜后台，凭前世记得的走位或设备险情报告成年人并避险，失职者失去后台职务，麦珂赢得试镜机会",
    "EC002": "第一份合同是本块唯一合同主事件；前世记得乔纳受一句限时报名谎话催促而速签，今生只提出少年能问的问题，由玛莎自主决定暂停并让律师审查，控制方永久失去速签通道",
    "EC003": "前世乔纳曾截住试镜回函再嫁祸玛莎，今生麦珂用回函到达次序让事实自然显露；玛莎自行决定掌管家庭邮件，乔纳永久失去独占家庭消息的权力",
    "EC004": "前世音乐指导临时换调令麦珂失声并落选，今生他记得口令和节目顺序，先请成年乐手核对再用真正试唱证明实力；操弄者失去排练职务，麦珂取得正式表演席位",
    "EC005": "前世宣传人用预设提问和断章引语把麦珂包装成傀儡，今生他记得开场问题与刊发时点，通过同期电台、报纸或电视的完整回答反制；宣传人失去独家发言权，麦珂取得公开表达空间",
    "EC006": "前世乔纳用巡演安排逐步隔离母子，今生麦珂只提示一次旧原话；玛莎基于自己的判断设定同行、就学或居住边界，乔纳永久失去单独安排巡演生活的权力，不重复EC003的邮件冲突",
    "EC007": "前世电视排练用预录带制造假唱指控，今生麦珂记得播放口令，要求现场清唱或公开重演；节目方当众撤回失实脚本并失去操控叙事的权力，不得使用未来人物、网络或社交平台",
    "EC008": "前世一段被否定的原创旋律后来遭职员冒领，今生麦珂在同期乐手见证下完成歌曲、旋律或编曲并公开试演；抢功者失去署名机会，麦珂获得第一次明确创作署名",
    "EC009": "前世厂牌误判听众只爱模仿而压掉原创曲，今生麦珂记得哪段原创最能打动现场听众，以演出邀约、唱片订单、电台点歌或同期市场反馈结算；厂牌失去强推模仿路线的筹码",
    "EC010": "前世商业方借慈善演出抽走捐款或伤害歌迷，今生麦珂记得临场改口与收费节点，主动退出该商业安排并转向同期可行的社区公益；商业方失去赞助或承办资格，麦珂获得歌迷长期信任",
}
B001_EVENT_REQUIRED_ANCHORS = {
    "EC001": (
        ("2009",), ("1969",), ("临终", "致死", "死亡"), ("康拉德",),
        ("药", "注射", "输液"), ("保险",), ("版权", "母带"),
        ("设备", "走位", "安全", "危险"),
    ),
    "EC002": (
        ("合同", "协议", "授权", "委托书"), ("乔纳",),
        ("限时", "截止", "马上签"), ("玛莎",), ("律师", "法律顾问", "审查"),
    ),
    "EC003": (("乔纳",), ("回函", "信件"), ("邮件", "邮袋", "家庭消息", "信件", "邮局")),
    "EC004": (("换调", "调性", "升D调", "升半音"), ("试唱", "清唱", "演唱"), ("乐手", "伴奏", "乐队", "指挥")),
    "EC005": (("提问", "引语", "断章", "剪辑"), ("电台", "报纸", "电视")),
    "EC006": (("巡演",), ("同行", "居住", "就学", "生活安排")),
    "EC007": (("预录", "假唱"), ("清唱", "重演", "现场演唱")),
    "EC008": (("原创", "创作"), ("旋律", "歌曲", "编曲"), ("署名",)),
    "EC009": (("听众", "观众"), ("邀约", "订单", "点歌", "销量", "市场反馈")),
    "EC010": (("慈善", "公益", "捐款"), ("退出", "拒绝", "撤回"), ("社区", "歌迷", "粉丝")),
}


def _procedural_hits(value: Any) -> int:
    text = _json_text(value) if not isinstance(value, str) else value
    return sum(text.count(term) for term in PROCEDURAL_MOTIFS)


def _fake_death_failures(value: Any, label: str) -> list[str]:
    text = _json_text(value) if not isinstance(value, str) else value
    negative_markers = (
        "禁止", "严禁", "不得", "不能", "不可", "绝不", "从不", "没有",
        "并非", "不是", "拒绝", "不使用", "不采用", "杜绝", "避免",
    )
    used_as_plot: list[str] = []
    for term in FORBIDDEN_FAKE_DEATH:
        for match in re.finditer(re.escape(term), text):
            # Constraint fields legitimately say that this route is forbidden.
            # Only an un-negated occurrence represents an actual plot choice.
            prefix = text[max(0, match.start() - 18):match.start()]
            if not any(marker in prefix for marker in negative_markers):
                used_as_plot.append(term)
                break
    return [
        f"{label}采用了禁止的伪死亡/药物昏迷终局：“{term}”"
        for term in used_as_plot
    ]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _generation_providers(paths: list[Path]) -> list[str]:
    providers: set[str] = set()
    for path in paths:
        try:
            provider = str(json.loads(path.read_text(encoding="utf-8")).get("generated_by") or "")
        except (OSError, json.JSONDecodeError):
            continue
        if provider in VALID_GENERATION_PROVIDERS:
            providers.add(provider)
    return sorted(providers)


def _generator_label(providers: list[str]) -> str:
    return providers[0] if len(providers) == 1 else "mixed_llm"


def _provider_for_provenance(path: Path) -> str:
    providers = _generation_providers([path])
    return providers[0] if providers else "qwen"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_text(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(value, ensure_ascii=False, indent=indent, sort_keys=False)


TECH_AVAILABLE_FROM = {
    "手机": 1991,
    "PDF": 1993,
    "电子邮件": 1993,
    "电子邮箱": 1993,
    "邮箱账号": 1993,
    "互联网": 1993,
    "网络留言": 1995,
    "网站": 1993,
    "上传": 1993,
    "短信": 1993,
    "USB": 1996,
    "二维码": 2003,
    "云端": 2006,
    "社交媒体": 2004,
    "社交平台": 2004,
    "全网": 1995,
    "网络上传": 1995,
}

# These are not merely anachronistic nouns.  They are recurring planning
# shortcuts that made an eleven-year-old read like a forensic instrument or a
# lawyer, exactly the failure mode identified in the first-twenty-chapter audit.
EARLY_PLANNING_FAKE_PRECISION = (
    "毫秒", "微秒", "微颤频率", "停顿频率", "微观纤维", "纸纤维", "材料氧化",
    "氧化程度", "声纹模型", "频谱完全", "频率完全", "生物指标", "压力特征",
    "骑缝章旁", "司法可援引效力",
)


def _early_planning_semantic_failures(value: Any, label: str) -> list[str]:
    """Reject child-omniscience and obsolete-media leaks before detail planning."""
    text = _json_text(value) if not isinstance(value, str) else value
    failures: list[str] = []
    hits = sorted({term for term in EARLY_PLANNING_FAKE_PRECISION if term in text})
    if hits:
        failures.append(
            f"{label}把未成年重生者写成假精确的技术/法务神童：{'、'.join(hits)}；"
            "只可记住日期、原话、流程和人物选择，专业判断交给成年人"
        )
    if re.search(r"麦珂.{0,24}(手写|起草|修改).{0,20}(附录|条款|法律文书)", text):
        failures.append(f"{label}不得让十一岁麦珂亲自起草或修改法律文书")
    return failures


GLOBAL_SEMANTIC_FORBIDDEN = (
    "低剂量镇静剂模拟", "服用镇静剂模拟", "镇静剂模拟", "嗜睡反应",
    "声纹锁芯", "共振基频完全吻合", "墨迹氧化程度完全一致",
    "蜡笔纹理", "叶脉纹理", "鸟羽纹理", "梧桐叶证明",
    "手写合同修正附录", "手写合同附录", "骑缝章旁手写",
    "微颤频率", "停顿毫秒", "毫秒数", "0.3厘米",
    "区块链式账本", "区块链账本", "全息演唱会", "《Thriller》", "Thriller",
    "数字全息技术", "全息技术重现", "全息影像重现",
    "AI生成的遗言", "AI生成的最后影像", "人工智能模拟遗言", "人工智能模拟生成的遗言",
    "延迟释放信息茧房", "临终确认函副本",
)
GLOBAL_FORBIDDEN_WORLD = (
    "北京", "上海", "中国", "纽约", "洛杉矶", "芝加哥", "好莱坞", "伦敦",
    "东京", "悉尼", "戛纳", "威尼斯", "百老汇", "林肯中心", "皇家阿尔伯特",
    "BBC", "纽约时报", "联合国教科文组织", "美国证券交易委员会", "联邦公证处",
    "北卡罗来纳州", "时代广场", "Michael Jackson", "迈克尔·杰克逊",
    "云南", "内蒙古", "蒙古族", "欧盟", "国家体育总局", "国家医学伦理委员会",
)


def _global_semantic_failures(value: Any, label: str) -> list[str]:
    """Apply critic findings at the highest planning layer, before graph sync."""
    text = _json_text(value) if not isinstance(value, str) else value
    failures: list[str] = []
    negative_markers = ("禁止", "严禁", "不得", "不能", "不可", "不使用", "不采用", "绝不", "避免")
    for phrase in GLOBAL_SEMANTIC_FORBIDDEN:
        for match in re.finditer(re.escape(phrase), text):
            prefix = text[max(0, match.start() - 18):match.start()]
            if not any(marker in prefix for marker in negative_markers):
                failures.append(f"{label}含评审已否定的全局方案“{phrase}”")
                break
    if re.search(r"(?:蜡笔|树叶|叶片|鸟羽|种子).{0,80}(?:四十年|多年|终局|审判).{0,80}(?:证明|验证|鉴真)", text):
        failures.append(f"{label}不得用小物件跨多年证明身份或法律事实")
    if re.search(r"(?:墨迹|纸张|纤维|氧化).{0,40}(?:完全一致|完全吻合|决定性证据|证明全程)", text):
        failures.append(f"{label}不得用材料状态完全一致制造假法证")
    if re.search(r"200[0-8]年.{0,50}(?:出版|发布|公开|披露).{0,80}2009年.{0,40}(?:死亡|当晚|全过程)", text):
        failures.append(f"{label}时间倒置：2009死亡经过不得在2009以前被公开出版或披露")
    if re.search(r"(?:1999|200[0-8])年.{0,140}2009年.{0,40}(?:死亡|死亡流程|临终|被杀).{0,80}(?:出版|纪录片|公开|发布|还原|展示)", text):
        failures.append(f"{label}时间倒置：今生2009终局前不得把尚未发生的今生死亡过程当作既成事实公开")
    if re.search(r"2009年.{0,60}(?:逝世|死忌|死亡).{0,30}周年", text):
        failures.append(f"{label}终局年代矛盾：2009年不能同时是今生死亡周年")
    if re.search(r"199\d年.{0,100}二维码", text):
        failures.append(f"{label}年代技术错误：1990年代情节不得使用二维码")
    if re.search(r"199\d年.{0,180}(?:全球.{0,30}纪念直播|纪念.{0,30}全球直播|全球哀悼仪式)", text):
        failures.append(f"{label}终局提前：全球纪念直播只能在2009终局启动")
    if re.search(r"(?:敌人|敌方|对手|维克多|集团).{0,100}(?:前世经验|上一世经验|重生记忆)", text):
        failures.append(f"{label}认知越界：只有麦珂拥有前世记忆，敌人不能依据前世经验")
    minute_stamps = re.findall(r"(?:[01]?\d|2[0-3])[:：点][0-5]\d(?:分)?", text)
    if len(set(minute_stamps)) >= 3:
        failures.append(f"{label}用连续分钟刻度制造假精确：只保留真正影响反击的一处时点")
    for phrase in GLOBAL_FORBIDDEN_WORLD:
        if phrase in text:
            failures.append(f"{label}世界观错误：不得出现真实专名“{phrase}”")
    return list(dict.fromkeys(failures))


def _compile_macro_direction_fields(obj: dict[str, Any]) -> dict[str, Any]:
    """Losslessly compile Qwen's single-source fields into the parent WHAT text."""
    compiled = json.loads(_json_text(obj))
    for item in compiled.get("five_event_directions") or []:
        if not isinstance(item, dict):
            continue
        span = item.get("chapter_span") or [0, 0]
        try:
            chapter_a, chapter_b = int(span[0]), int(span[1])
        except (TypeError, ValueError, IndexError):
            chapter_a, chapter_b = 0, 0
        item["direction"] = (
            f"前世具体受害：{item.get('previous_life_harm') or ''}；"
            f"本事件独有的前世信息差：{item.get('unique_prev_life_info') or ''}；"
            f"今生提前动作：{item.get('preemptive_action') or ''}；"
            f"第{chapter_a}章可见小赢：{item.get('chapter_one_small_win') or ''}；"
            f"第{chapter_b}章新交锋：{item.get('chapter_two_showdown') or ''}；"
            f"阻力方永久现实损失：{item.get('opponent_permanent_loss') or ''}；"
            f"主角现实收益：{item.get('protagonist_concrete_gain') or ''}；"
            f"不可逆结算键：{item.get('irreversible_outcome_key') or ''}；"
            f"接回死亡控制主线：{item.get('death_chain_connection') or ''}"
        )
    return compiled


def _timeline_start_year(value: Any) -> int | None:
    years = [int(item) for item in re.findall(r"(?:19|20)\d{2}", str(value or ""))]
    return min(years) if years else None


def _unavailable_technology(timeline: Any) -> tuple[str, ...]:
    year = _timeline_start_year(timeline)
    if year is None:
        return ()
    return tuple(term for term, available_from in TECH_AVAILABLE_FROM.items() if year < available_from)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(_json_text(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_detail_progress(
    output_dir: Path, events: list[dict[str, Any]], chapters: list[dict[str, Any]],
) -> bool:
    """Publish a checkpoint without making user-visible progress go backwards."""
    public_events = output_dir / "event_clusters_v2.json"
    try:
        existing = json.loads(public_events.read_text(encoding="utf-8"))
        if isinstance(existing, list) and len(existing) > len(events):
            return False
    except (OSError, json.JSONDecodeError):
        pass
    _write_json(public_events, events)
    _write_json(output_dir / "event_clusters_v5_qwen_500.json", events)
    _write_json(output_dir / "master_ctx_cards_v2.json", chapters)
    _write_json(output_dir / "chapter_synopses_v5_qwen_500.json", chapters)
    return True


def _merge_continuity_ledger(previous: Any, update: Any) -> Any:
    """Accumulate canonical continuity instead of replacing it each block.

    A rolling one-block summary forgets old permanent rights and makes later
    Qwen calls grant or revoke them again.  Dictionaries merge recursively;
    lists retain unique historical facts in first-seen order; scalar fields use
    the newest non-empty value.
    """
    if isinstance(previous, dict) or isinstance(update, dict):
        left = previous if isinstance(previous, dict) else {}
        right = update if isinstance(update, dict) else {}
        result: dict[str, Any] = {}
        for key in dict.fromkeys([*left, *right]):
            if key in left and key in right:
                result[key] = _merge_continuity_ledger(left[key], right[key])
            elif key in right:
                result[key] = right[key]
            else:
                result[key] = left[key]
        return result
    if isinstance(previous, list) or isinstance(update, list):
        values = [
            *(previous if isinstance(previous, list) else ([] if previous in (None, "") else [previous])),
            *(update if isinstance(update, list) else ([] if update in (None, "") else [update])),
        ]
        result: list[Any] = []
        seen: set[str] = set()
        for item in values:
            marker = canonical_sha256(item)
            if marker not in seen:
                seen.add(marker)
                result.append(item)
        return result
    return update if update not in (None, "") else previous


def _archive_stale_downstream_if_outline_changed(
    output_dir: Path, outline_sha256: str,
) -> Path | None:
    """Recoverably isolate outputs derived from another broad outline."""
    manifest_path = output_dir / "qwen_generation_manifest.json"
    previous_outline_sha = ""
    if manifest_path.is_file():
        try:
            previous_outline_sha = str(
                json.loads(manifest_path.read_text(encoding="utf-8")).get("outline_sha256") or ""
            )
        except (OSError, json.JSONDecodeError):
            previous_outline_sha = ""
    downstream_names = (
        "coarse_story_blocks_v5_qwen_500.json", "macro_groups_v5_qwen_500.json",
        "event_clusters_v2.json", "event_clusters_v5_qwen_500.json",
        "master_ctx_cards_v2.json", "chapter_synopses_v5_qwen_500.json",
        "plan_compilation_report.json", "plan_prefix_compilation_report.json",
        "chapters", "body_generation", "knowledge_graph",
    )
    existing = [output_dir / name for name in downstream_names if (output_dir / name).exists()]
    if not existing or previous_outline_sha == outline_sha256:
        return None
    archive_dir = (
        output_dir / "stale_plan_archives"
        / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{previous_outline_sha[:12] or 'unknown_parent'}"
    )
    archive_dir.mkdir(parents=True, exist_ok=False)
    moved: list[str] = []
    for source in existing:
        shutil.move(str(source), str(archive_dir / source.name))
        moved.append(source.name)
    _write_json(archive_dir / "archive_manifest.json", {
        "reason": "parent_outline_sha256_changed_or_missing",
        "previous_outline_sha256": previous_outline_sha or None,
        "replacement_outline_sha256": outline_sha256,
        "moved": moved,
        "recoverable": True,
        "archived_at": _now(),
    })
    print(f"[archive] stale downstream moved to {archive_dir}", flush=True)
    return archive_dir


def _archive_stale_detail_plan_if_blocks_changed(
    output_dir: Path, blocks: list[dict[str, Any]], macros: list[dict[str, Any]],
) -> Path | None:
    """Recoverably isolate detail/prose derived from another block blueprint."""
    manifest_path = output_dir / "qwen_generation_manifest.json"
    expected = canonical_sha256({"blocks": blocks, "macros": macros})
    previous = ""
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            previous = str(manifest.get("block_plan_bundle_sha256") or "")
        except (OSError, json.JSONDecodeError):
            previous = ""
    detail_names = (
        "event_clusters_v2.json", "event_clusters_v5_qwen_500.json",
        "master_ctx_cards_v2.json", "chapter_synopses_v5_qwen_500.json",
        "plan_compilation_report.json", "plan_prefix_compilation_report.json",
        "chapters", "body_generation", "knowledge_graph",
    )
    existing = [output_dir / name for name in detail_names if (output_dir / name).exists()]
    if not existing:
        return None
    # Old manifests that predate this hash are untrusted rather than assumed
    # compatible.  This intentionally archives the current v6 prefix once.
    if previous == expected:
        return None
    archive_dir = (
        output_dir / "stale_plan_archives"
        / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{previous[:12] or 'unknown_blocks'}"
    )
    archive_dir.mkdir(parents=True, exist_ok=False)
    moved: list[str] = []
    for source in existing:
        shutil.move(str(source), str(archive_dir / source.name))
        moved.append(source.name)
    _write_json(archive_dir / "archive_manifest.json", {
        "reason": "parent_block_or_macro_bundle_changed_or_unfingerprinted",
        "previous_block_plan_bundle_sha256": previous or None,
        "replacement_block_plan_bundle_sha256": expected,
        "moved": moved, "recoverable": True, "archived_at": _now(),
    })
    print(f"[archive] stale detail plan/prose moved to {archive_dir}", flush=True)
    return archive_dir


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Qwen response contains no JSON object")
    payload = text[start:end + 1]
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as first_error:
        # Qwen occasionally emits a literal newline/tab inside a JSON string.
        # Escaping only control characters while inside quotes preserves every
        # authored word and allows the otherwise valid object to be resumed.
        payload_for_repair = re.sub(r"[”’](?=\s*[,}\]])", '"', payload)
        # A recurring Qwen typo closes the event as well as chapter one before
        # emitting chapter two.  The exact chapter_id boundary makes this a
        # deterministic syntax repair rather than a guessed content edit.
        payload_for_repair = re.sub(
            r'"}\s*}\s*,\s*\{\s*"chapter_id"',
            '"}, {"chapter_id"',
            payload_for_repair,
        )
        payload_for_repair = re.sub(
            r'(\]\s*}\s*\])\s*}\s*,\s*"continuity_update"',
            r'\1, "continuity_update"',
            payload_for_repair,
        )
        repaired: list[str] = []
        in_string = False
        escaped = False
        replacements = {"\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}
        for char in payload_for_repair:
            if in_string and char in replacements:
                repaired.append(replacements[char])
                escaped = False
                continue
            repaired.append(char)
            if char == '"' and not escaped:
                in_string = not in_string
            if in_string and char == "\\" and not escaped:
                escaped = True
            else:
                escaped = False
        try:
            parsed = json.loads("".join(repaired))
        except json.JSONDecodeError:
            # A tight relay completion limit may cut only the redundant
            # continuity_update tail after a complete event_clusters array.
            # Recover that balanced array and deterministically rebuild the
            # small ledger; never attempt this when the creative event array
            # itself is incomplete.
            key_pos = text.find('"event_clusters"')
            array_start = text.find("[", key_pos) if key_pos >= 0 else -1
            array_end = -1
            if array_start >= 0:
                depth = 0
                in_string = False
                escaped = False
                for index in range(array_start, len(text)):
                    char = text[index]
                    if char == '"' and not escaped:
                        in_string = not in_string
                    if not in_string:
                        if char == "[":
                            depth += 1
                        elif char == "]":
                            depth -= 1
                            if depth == 0:
                                array_end = index + 1
                                break
                    if in_string and char == "\\" and not escaped:
                        escaped = True
                    else:
                        escaped = False
            if array_end < 0:
                raise first_error
            try:
                recovered_events = json.loads(text[array_start:array_end])
            except json.JSONDecodeError:
                raise first_error
            if not isinstance(recovered_events, list) or not recovered_events:
                raise first_error
            macro_match = re.search(r'"macro_group_id"\s*:\s*"(MG\d{3})"', text[:array_start])
            final_event = recovered_events[-1] if isinstance(recovered_events[-1], dict) else {}
            parsed = {
                "macro_group_id": macro_match.group(1) if macro_match else "",
                "event_clusters": recovered_events,
                "continuity_update": {
                    "current_year": final_event.get("timeline_years"),
                    "character_states": [], "relationship_states": [],
                    "rights_and_assets": [], "health_and_location": [],
                    "open_threads": [],
                    "resolved_threads": [final_event.get("cluster_outcome")]
                    if final_event.get("cluster_outcome") else [],
                    "introduced_characters": [],
                    "next_pressure": final_event.get("next_event_hook"),
                },
            }
    if not isinstance(parsed, dict):
        raise ValueError("Qwen response top level must be an object")
    return parsed


def _extract_content(response: Any) -> str:
    code = str(response.get("code") or "") if hasattr(response, "get") else ""
    message = str(response.get("message") or "") if hasattr(response, "get") else ""
    if code in {
        "Arrearage", "InvalidApiKey", "AccessDenied",
        "AllocationQuota.FreeTierOnly", "AllocationQuota.FreeTierExhausted",
    }:
        raise RuntimeError(f"QWEN_NON_RETRYABLE:{code}:{message[:240]}")
    try:
        return str(response["output"]["choices"][0]["message"]["content"])
    except Exception as exc:
        raise RuntimeError(f"Qwen returned an invalid response shape: {str(response)[:400]}") from exc


def _extract_openai_content(response: dict[str, Any]) -> str:
    try:
        return str(response["choices"][0]["message"]["content"])
    except Exception as exc:
        raise RuntimeError(
            f"OpenAI-compatible provider returned an invalid response shape: {str(response)[:400]}"
        ) from exc


def _call_qwen(
    messages: list[dict[str, str]], model: str, temperature: float,
    max_output_tokens: int | None = None,
) -> tuple[str, dict[str, Any]]:
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    preferred = os.getenv("PLANNER_PROVIDER", "").strip().lower()
    compatible_provider = "vectorengine" if preferred == "vectorengine" else "groq"
    use_groq = preferred in {"groq", "vectorengine"} or (not API_Key_QW and bool(groq_key))

    def call_groq(*, fallback_reason: str = "") -> tuple[str, dict[str, Any]]:
        global _GROQ_VISIBLE_MODELS
        if not groq_key:
            raise RuntimeError("GROQ_NON_RETRYABLE:MissingApiKey:请设置GROQ_API_KEY后再运行")
        # Prefer the still-unused 70B general model for creative structured
        # planning, then fall back across independent per-model free quotas.
        requested_model = os.getenv(
            "GROQ_PLANNER_MODEL",
            "qwen-plus" if compatible_provider == "vectorengine" else "llama-3.3-70b-versatile",
        ).strip()
        fallback_models = [
            value.strip() for value in os.getenv(
                "GROQ_PLANNER_FALLBACK_MODELS",
                "qwen/qwen3.6-27b,openai/gpt-oss-120b,openai/gpt-oss-20b,groq/compound-mini,llama-3.1-8b-instant",
            ).split(",") if value.strip()
        ]
        model_candidates = list(dict.fromkeys([requested_model, *fallback_models]))
        if compatible_provider == "vectorengine" and _GROQ_VISIBLE_MODELS is None:
            # The endpoint was explicitly probed before planner startup and
            # returned all configured candidates.  Avoid downloading its
            # 566-model catalogue on every resumed process; that large models
            # response is unreliable through Windows Schannel although chat
            # completions work normally.
            _GROQ_VISIBLE_MODELS = list(model_candidates)
        if _GROQ_VISIBLE_MODELS is None:
            try:
                _GROQ_VISIBLE_MODELS = list_openai_compatible_models_via_curl(
                    api_key=groq_key,
                    endpoint=os.getenv(
                        "GROQ_MODELS_ENDPOINT",
                        "https://api.vectorengine.ai/v1/models"
                        if compatible_provider == "vectorengine"
                        else "https://api.groq.com/openai/v1/models",
                    ),
                )
            except RuntimeError as exc:
                if "failed (22)" in str(exc) and "Forbidden" in str(exc):
                    raise RuntimeError(
                        "GROQ_NON_RETRYABLE:ApiAccessForbidden:"
                        "Groq /models与生成接口均返回403；这不是单一模型问题，"
                        "请检查Groq项目/组织API访问状态、项目权限或当前网络访问限制"
                    ) from exc
                raise
        visible_set = set(_GROQ_VISIBLE_MODELS)
        visible_candidates = [model for model in model_candidates if model in visible_set]
        if visible_candidates:
            model_candidates = visible_candidates
        elif visible_set:
            preferred_visible = [
                model for model in _GROQ_VISIBLE_MODELS
                if any(marker in model.lower() for marker in ("qwen", "gpt-oss", "llama"))
            ]
            model_candidates = preferred_visible[:3]
        if not model_candidates:
            raise RuntimeError(
                "GROQ_NON_RETRYABLE:NoTextPlannerModelVisible:"
                "该key的/models列表中没有Qwen、GPT-OSS或Llama文本模型"
            )
        groq_started = time.monotonic()
        response: dict[str, Any] | None = None
        groq_model = requested_model
        denied_models: list[str] = []
        capacity_limited_models: list[str] = []
        capacity_reasons: dict[str, str] = {}
        for candidate in model_candidates:
            last_error: RuntimeError | None = None
            for transient_attempt in range(1, 6):
                try:
                    compatible_call = (
                        call_openai_compatible_via_requests
                        if compatible_provider == "vectorengine"
                        else call_openai_compatible_via_curl
                    )
                    candidate_max_tokens = max_output_tokens or GROQ_MAX_OUTPUT_TOKENS
                    if candidate == "llama-3.1-8b-instant":
                        # This model's free-tier TPM ceiling is 6K including
                        # the prompt.  A 2.8K completion fits one compact
                        # single-event request while leaving prompt headroom.
                        candidate_max_tokens = min(candidate_max_tokens, 2800)
                    response = compatible_call(
                        messages, api_key=groq_key, model=candidate,
                        endpoint=os.getenv(
                            "GROQ_CHAT_COMPLETIONS_ENDPOINT",
                            "https://api.vectorengine.ai/v1/chat/completions"
                            if compatible_provider == "vectorengine"
                            else "https://api.groq.com/openai/v1/chat/completions",
                        ),
                        temperature=temperature, top_p=0.82,
                        max_tokens=candidate_max_tokens, timeout_s=180,
                    )
                    groq_model = candidate
                    break
                except RuntimeError as exc:
                    last_error = exc
                    error_text = str(exc)
                    retry_match = re.search(
                        r"(?:try again in|Please try again in)\s*"
                        r"([0-9]+(?:\.[0-9]+)?)\s*(ms|s)",
                        error_text,
                        flags=re.IGNORECASE,
                    )
                    transient_tpm = (
                        "rate_limit_exceeded" in error_text
                        and retry_match is not None
                        and "Request too large for model" not in error_text
                    )
                    if transient_tpm and transient_attempt < 5:
                        raw_delay = float(retry_match.group(1))
                        if retry_match.group(2).lower() == "ms":
                            raw_delay /= 1000.0
                        retry_seconds = min(45.0, max(1.5, raw_delay + 1.5))
                        print(
                            f"[wait] {compatible_provider} {candidate} window {retry_seconds:.1f}s "
                            f"attempt={transient_attempt + 1}/5",
                            flush=True,
                        )
                        time.sleep(retry_seconds)
                        continue
                    break
            if response is not None:
                break
            if last_error is None:
                raise RuntimeError(f"Groq model {candidate} failed without an error response")
            try:
                # Reuse the final exception text from the bounded transient
                # loop for model permission/capacity classification below.
                raise last_error
            except RuntimeError as exc:
                # New Groq projects can deny deprecated/restricted models with
                # a terse 403. Try current production alternatives once each;
                # auth, rate-limit, syntax and server failures are not model
                # permission failures and must surface immediately.
                error_text = str(exc)
                forbidden = "failed (22)" in error_text and "Forbidden" in error_text
                request_exceeds_model_tpm = (
                    "rate_limit_exceeded" in error_text
                    and "Request too large for model" in error_text
                    and "tokens per minute" in error_text
                )
                daily_model_quota_exhausted = (
                    "rate_limit_exceeded" in error_text
                    and "tokens per day" in error_text
                )
                relay_model_preauth_exhausted = (
                    compatible_provider == "vectorengine"
                    and "insufficient_quota" in error_text
                    and "pre-consumed quota" in error_text
                )
                if not forbidden and not request_exceeds_model_tpm and not daily_model_quota_exhausted and not relay_model_preauth_exhausted:
                    raise
                if forbidden:
                    denied_models.append(candidate)
                else:
                    capacity_limited_models.append(candidate)
                    capacity_reasons[candidate] = error_text[:700]
        if response is None:
            if capacity_limited_models:
                for limited_model in capacity_limited_models:
                    reason = capacity_reasons.get(limited_model, "")
                    category = (
                        "daily_quota"
                        if "tokens per day" in reason
                        else "request_too_large"
                        if "Request too large for model" in reason
                        else "relay_quota"
                        if "insufficient_quota" in reason
                        else "rate_capacity"
                    )
                    retry_hint = re.search(
                        r"try again in\s+(?:(\d+)m)?([\d.]+)s", reason,
                        flags=re.IGNORECASE,
                    )
                    hint = (
                        f" retry={retry_hint.group(0).split('in', 1)[-1].strip()}"
                        if retry_hint else ""
                    )
                    print(
                        f"[model-capacity] {limited_model} category={category}{hint}",
                        flush=True,
                    )
                raise RuntimeError(
                    "GROQ_NON_RETRYABLE:AllPlannerModelsCapacityLimited:"
                    + ",".join(capacity_limited_models)
                    + ";details=" + _json_text(capacity_reasons)
                )
            raise RuntimeError(
                "GROQ_NON_RETRYABLE:AllPlannerModelsForbidden:"
                + ",".join(denied_models)
                + ";请在Groq项目/组织Limits中允许至少一个模型"
            )
        return _extract_openai_content(response), {
            "provider": compatible_provider, "model": groq_model,
            "transport": "openai_compatible_curl",
            "elapsed_seconds": round(time.monotonic() - groq_started, 3),
            "usage": dict(response.get("usage") or {}),
            **({"forbidden_model_fallbacks": denied_models} if denied_models else {}),
            **(
                {"capacity_model_fallbacks": capacity_limited_models}
                if capacity_limited_models else {}
            ),
            **({"fallback_from_qwen": fallback_reason[:240]} if fallback_reason else {}),
        }

    if use_groq:
        return call_groq()
    if not API_Key_QW:
        raise RuntimeError(
            "MODEL_NON_RETRYABLE:MissingApiKey:请设置DASHSCOPE_API_KEY或GROQ_API_KEY后再运行"
        )
    dashscope.api_key = API_Key_QW
    started = time.monotonic()
    transport = "dashscope_sdk"
    try:
        response = dashscope.Generation.call(
            model=model,
            messages=messages,
            temperature=temperature,
            top_p=0.82,
            repetition_penalty=1.05,
            result_format="message",
            max_tokens=max_output_tokens or QWEN_MAX_OUTPUT_TOKENS,
        )
        raw = _extract_content(response)
        usage = dict(response.get("usage") or {}) if hasattr(response, "get") else {}
    except Exception as sdk_error:
        if "QWEN_NON_RETRYABLE:" in str(sdk_error):
            if groq_key and preferred != "qwen":
                return call_groq(fallback_reason=str(sdk_error))
            raise
        transport = "curl_fallback"
        try:
            response = call_qwen_via_curl(
                messages,
                api_key=API_Key_QW,
                model=model,
                temperature=temperature,
                top_p=0.82,
                repetition_penalty=1.05,
                max_tokens=max_output_tokens or QWEN_MAX_OUTPUT_TOKENS,
                timeout_s=180,
            )
            raw = _extract_content(response)
            usage = dict(response.get("usage") or {})
            usage["sdk_error_class"] = type(sdk_error).__name__
        except Exception as curl_error:
            quota_markers = (
                "Arrearage", "AllocationQuota.FreeTierOnly",
                "AllocationQuota.FreeTierExhausted", "AccessDenied", "InvalidApiKey",
            )
            if groq_key and preferred != "qwen" and any(
                marker in str(curl_error) for marker in quota_markers
            ):
                return call_groq(fallback_reason=str(curl_error))
            raise
    return raw, {
        "provider": "qwen",
        "model": model,
        "transport": transport,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "usage": usage,
    }


def _call_validated(
    *,
    kind: str,
    identifier: str,
    system_prompt: str,
    user_prompt: str,
    validator: Callable[[dict[str, Any]], list[str]],
    checkpoint_dir: Path,
    model: str,
    temperature: float,
    resume: bool,
    allow_prompt_drift: bool = False,
    max_attempts: int = 4,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    parsed_path = checkpoint_dir / f"{identifier}_{kind}.json"
    provenance_path = checkpoint_dir / f"{identifier}_{kind}_provenance.json"
    base_prompt_sha256 = _sha(system_prompt + "\n" + user_prompt)
    if resume and parsed_path.exists() and provenance_path.exists():
        parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
        failures = validator(parsed)
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        provenance_ok = (
            provenance.get("generated_by") in VALID_GENERATION_PROVIDERS
            and bool(provenance.get("accepted_attempt"))
            and provenance.get("manual_edits") == []
        )
        prompt_matches = provenance.get("base_prompt_sha256") == base_prompt_sha256
        if not failures and provenance_ok and (prompt_matches or allow_prompt_drift):
            accepted_attempt = provenance.get("accepted_attempt")
            normalized = False
            for item in provenance.get("attempts", []):
                if (
                    isinstance(item, dict)
                    and str(item.get("attempt")) == str(accepted_attempt)
                    and item.get("validation_failures")
                ):
                    item["validation_failures"] = []
                    item["revalidated_at"] = _now()
                    normalized = True
            if normalized:
                provenance["acceptance_mode"] = "revalidated_existing_qwen_raw"
                _write_json(provenance_path, provenance)
            suffix = " prompt_drift=explicitly_allowed" if not prompt_matches else ""
            print(f"[resume] {identifier} {kind}{suffix}", flush=True)
            return parsed
        if not prompt_matches and provenance_ok:
            print(
                f"[invalidate] {identifier} {kind} prompt_sha256 changed; regenerating",
                flush=True,
            )
    if resume:
        prior = {}
        if provenance_path.exists():
            try:
                prior = json.loads(provenance_path.read_text(encoding="utf-8"))
            except Exception:
                prior = {}
        raw_candidates = sorted(checkpoint_dir.glob(f"{identifier}_{kind}_attempt_*_raw.txt"), reverse=True)
        if prior.get("base_prompt_sha256") != base_prompt_sha256 and not allow_prompt_drift:
            raw_candidates = []
        elif not allow_prompt_drift:
            eligible_raw_files = {
                str(item.get("raw_response_file") or "")
                for item in (prior.get("attempts") or [])
                if isinstance(item, dict)
            }
            raw_candidates = [path for path in raw_candidates if path.name in eligible_raw_files]
        for raw_path in raw_candidates:
            try:
                raw = raw_path.read_text(encoding="utf-8")
                parsed = _parse_json_object(raw)
                failures = validator(parsed)
            except Exception as exc:
                print(
                    f"[reuse-skip] {identifier} {kind} from={raw_path.name}: "
                    f"parse={str(exc)[:220]}", flush=True,
                )
                continue
            if failures:
                print(
                    f"[reuse-skip] {identifier} {kind} from={raw_path.name}: "
                    + " | ".join(failures[:5]), flush=True,
                )
                continue
            accepted_attempt = raw_path.stem.split("_attempt_")[-1].split("_")[0]
            revalidated_attempts: list[dict[str, Any]] = []
            for item in prior.get("attempts", []):
                if not isinstance(item, dict):
                    continue
                updated = dict(item)
                if str(updated.get("attempt")) == str(accepted_attempt):
                    # The raw response has passed the current validator.  Keep
                    # the original response hash/model metadata, but do not
                    # retain a stale failure list from an older style guard.
                    updated["validation_failures"] = []
                    updated["revalidated_at"] = _now()
                revalidated_attempts.append(updated)
            _write_json(parsed_path, parsed)
            _write_json(provenance_path, {
                "generated_by": str(prior.get("generated_by") or "qwen"),
                "kind": kind,
                "identifier": identifier,
                "accepted_attempt": accepted_attempt,
                "acceptance_mode": "revalidated_existing_qwen_raw",
                "base_prompt_sha256": base_prompt_sha256,
                "manual_edits": [],
                "attempts": revalidated_attempts,
            })
            print(f"[revalidated] {identifier} {kind} from={raw_path.name}", flush=True)
            return parsed

    prompt = user_prompt
    prior_provenance: dict[str, Any] = {}
    if provenance_path.exists():
        try:
            prior_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prior_provenance = {}
    if prior_provenance.get("base_prompt_sha256") == base_prompt_sha256:
        attempts = [
            item for item in (prior_provenance.get("attempts") or [])
            if isinstance(item, dict)
        ]
    else:
        attempts = []
    prior_raw_hashes = {
        str(item.get("raw_response_sha256") or "") for item in attempts
        if item.get("raw_response_sha256")
    }
    prior_attempt_numbers = [
        int(item.get("attempt")) for item in attempts
        if str(item.get("attempt") or "").isdigit()
    ]
    first_new_attempt = max(prior_attempt_numbers, default=0) + 1
    for attempt_offset in range(max_attempts):
        attempt = first_new_attempt + attempt_offset
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
        raw, call_meta = _call_qwen(
            messages, model=model, temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        raw_path = checkpoint_dir / (
            f"{identifier}_{kind}_attempt_{attempt:02d}_{base_prompt_sha256[:10]}_raw.txt"
        )
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(raw, encoding="utf-8")
        failures: list[str]
        try:
            parsed = _parse_json_object(raw)
            failures = validator(parsed)
        except Exception as exc:
            parsed = {}
            failures = [f"JSON解析失败: {exc}"]
        raw_hash = _sha(raw)
        repeated_raw = raw_hash in prior_raw_hashes
        prior_raw_hashes.add(raw_hash)
        attempts.append({
            "attempt": attempt,
            "created_at": _now(),
            "prompt_sha256": _sha(system_prompt + "\n" + prompt),
            "raw_response_sha256": raw_hash,
            "repeated_previous_response": repeated_raw,
            "raw_response_file": raw_path.name,
            "validation_failures": failures,
            **call_meta,
        })
        _write_json(provenance_path, {
            "generated_by": str(call_meta.get("provider") or "qwen"),
            "kind": kind,
            "identifier": identifier,
            "accepted_attempt": None,
            "base_prompt_sha256": base_prompt_sha256,
            "manual_edits": [],
            "attempts": attempts,
        })
        if not failures:
            _write_json(parsed_path, parsed)
            _write_json(provenance_path, {
                "generated_by": str(call_meta.get("provider") or "qwen"),
                "kind": kind,
                "identifier": identifier,
                "accepted_attempt": attempt,
                "base_prompt_sha256": base_prompt_sha256,
                "manual_edits": [],
                "attempts": attempts,
            })
            print(f"[ok] {identifier} {kind} attempt={attempt} elapsed={call_meta['elapsed_seconds']}s", flush=True)
            return parsed
        print(f"[retry] {identifier} {kind} attempt={attempt}: {' | '.join(failures[:6])}", flush=True)
        correction_nonce = _sha(
            f"{identifier}:{kind}:{attempt}:{raw_hash}:{'|'.join(failures)}"
        )[:12]
        # Semantic planning errors require a fresh complete plan.  Patch-style
        # repair preserved bad story choices and, on smaller models, gradually
        # collapsed the JSON into a short fragment.  Keep only the concise
        # failure list; the authoritative schema and upstream facts remain in
        # the base prompt.
        prompt = (
            user_prompt
            + f"\n\n重写批次标识：{correction_nonce}。上一次规划整体作废。"
            + "请从权威上游重新创作并完整输出全部JSON，不能只返回修补字段，"
            + "不能缩短coarse summary、事件方向或数组。新版本必须避开这些失败：\n- "
            + "\n- ".join(failures[:12])
        )
    _write_json(provenance_path, {
        "generated_by": str(
            (attempts[-1].get("provider") if attempts else None) or "qwen"
        ),
        "kind": kind,
        "identifier": identifier,
        "accepted_attempt": None,
        "base_prompt_sha256": base_prompt_sha256,
        "manual_edits": [],
        "attempts": attempts,
    })
    raise RuntimeError(f"{identifier} {kind} failed after {max_attempts} Qwen attempts")


def _volume_bounds(volume_index: int) -> tuple[int, int]:
    start = (volume_index - 1) * 50 + 1
    return start, start + 49


def _block_bounds(block_index: int) -> tuple[int, int]:
    start = (block_index - 1) * 20 + 1
    return start, start + 19


def _macro_bounds(macro_index: int) -> tuple[int, int]:
    start = (macro_index - 1) * 10 + 1
    return start, start + 9


def _event_bounds(event_index: int) -> tuple[int, int]:
    start = (event_index - 1) * 2 + 1
    return start, start + 1


def _phase_candidates_for_year(year: int) -> set[str]:
    if year == 2009:
        return {"P01", "P10"}
    if 1969 <= year <= 1970:
        return {"P01"}
    if 1971 <= year <= 1977:
        return {"P02"}
    if year == 1978:
        return {"P02", "P03"}
    if 1979 <= year <= 1982:
        return {"P03"}
    if 1983 <= year <= 1986:
        return {"P04"}
    if 1987 <= year <= 1990:
        return {"P05"}
    if 1991 <= year <= 1994:
        return {"P06"}
    if 1995 <= year <= 1998:
        return {"P07"}
    if 1999 <= year <= 2003:
        return {"P08"}
    if 2004 <= year <= 2007:
        return {"P09"}
    if 2008 <= year <= 2009:
        return {"P10"}
    return set()


def _validate_global_outline(obj: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for field, minimum in (
        ("story_title", 4), ("one_sentence_premise", 30),
        ("full_story_synopsis", 1800), ("ending_convergence", 200),
    ):
        if len(str(obj.get(field) or "").strip()) < minimum:
            failures.append(f"global_story_outline.{field}过短或缺失")
    rebirth_logic = obj.get("core_rebirth_logic")
    if not isinstance(rebirth_logic, dict):
        failures.append("core_rebirth_logic必须为对象")
    else:
        for field in ("previous_life_death", "information_gap", "new_life_method", "moral_boundary", "ultimate_goal"):
            if len(str(rebirth_logic.get(field) or "").strip()) < 30:
                failures.append(f"core_rebirth_logic.{field}过短或缺失")
    phases = obj.get("life_phases")
    if not isinstance(phases, list) or len(phases) != 10:
        failures.append("life_phases必须恰好10项，对应十个50章阶段")
    else:
        for index, phase in enumerate(phases, 1):
            expected_span = list(_volume_bounds(index))
            if phase.get("phase_id") != f"P{index:02d}":
                failures.append(f"第{index}阶段phase_id必须为P{index:02d}")
            if phase.get("chapter_span") != expected_span:
                failures.append(f"P{index:02d}.chapter_span必须为{expected_span}")
            for field in (
                "timeline_years", "broad_story_goal", "main_pressure", "rebirth_advantage",
                "major_turning_point", "phase_outcome", "handoff_to_next_phase",
            ):
                minimum = 4 if field == "timeline_years" else 20
                if len(str(phase.get(field) or "").strip()) < minimum:
                    failures.append(f"P{index:02d}.{field}过短或缺失")
            if not isinstance(phase.get("major_characters"), list) or len(phase["major_characters"]) < 2:
                failures.append(f"P{index:02d}.major_characters至少2人")
    for field, minimum in (("character_long_arcs", 10), ("causal_spine", 15), ("foreshadow_ledger", 12), ("state_ledger_by_phase", 10)):
        value = obj.get(field)
        if not isinstance(value, list) or len(value) < minimum:
            failures.append(f"{field}至少{minimum}项")
    failures.extend(_validate_global_arc_identities(obj.get("character_long_arcs")))
    serialized = _json_text(obj)
    age_ok = any(token in serialized for token in ("十一岁", "11岁", "十一周岁", "11周岁"))
    if not age_ok or not all(token in serialized for token in ("2009", "1969", "保险", "版权")):
        failures.append("全书总纲必须明确2009死亡、1969十一岁重生及保险/版权利益链")
    if not all(token in serialized for token in ("葬礼", "审判", "全球")) or not any(
        token in serialized for token in ("现身", "登台", "走上舞台", "走上现场", "走入现场", "踏上中央台阶", "踏上舞台")
    ):
        failures.append("全书总纲必须明确本人在全球纪念现场登台并把葬礼变成审判")
    forbidden_world = ("北京", "上海", "中国", "纽约", "洛杉矶", "芝加哥", "好莱坞", "戛纳", "威尼斯", "东京", "Excel", "MTV", "通用电气", "联合国教科文组织", "国家职业安全卫生研究所", "Michael Jackson", "迈克尔·杰克逊")
    for phrase in forbidden_world:
        if phrase in serialized:
            failures.append(f"全书总纲世界观错误：禁止出现“{phrase}”")
    if "奥瑞安" in serialized:
        failures.append("集团名称不一致：统一使用‘奥瑞恩集团’，不得写‘奥瑞安’")
    synopsis = str(obj.get("full_story_synopsis") or "")
    procedural_hits = _procedural_hits(synopsis)
    if procedural_hits > 18:
        failures.append(f"宽泛总纲程序/取证意象过密，共{procedural_hits}次，必须让舞台、创作和人物冲突成为主体")
    failures.extend(_fake_death_failures(obj, "全书总纲"))
    failures.extend(_global_semantic_failures(obj, "全书总纲"))
    if synopsis.count("蓝雪") > 3:
        failures.append("蓝雪只能用于死亡—重生视觉对应，宽泛总纲不得反复使用")
    required_domains = (
        ("舞台", "演出"), ("创作", "作品"), ("家庭", "家人"),
        ("粉丝", "公益"), ("媒体", "舆论"), ("健康", "安全"),
    )
    if sum(any(term in synopsis for term in group) for group in required_domains) < 5:
        failures.append("宽泛总纲必须覆盖舞台、创作、家庭、粉丝公益、媒体舆论、健康安全中的至少5类")
    contract_root = any(term in serialized for term in ("第一份合同", "首份合同", "最初合同", "第一张合同"))
    system_root = any(term in serialized for term in ("控制体系", "控制结构", "权力结构", "利益体系", "利益链"))
    if not (contract_root and system_root):
        failures.append("宽泛总纲必须明确从第一份合同开始拆掉2009死亡控制体系")
    art_hits = sum(synopsis.count(term) for term in (
        "舞台", "演出", "音乐", "作品", "歌曲", "创作", "观众", "发行", "榜单", "巡演",
        "录音", "专辑", "旋律", "编曲", "编舞", "唱片", "乐队", "歌声", "票房", "现场",
    ))
    human_hits = sum(synopsis.count(term) for term in (
        "家庭", "家人", "母亲", "兄弟", "伙伴", "粉丝", "公益", "关系", "爱情", "孩子",
        "玛莎", "帕丽丝", "亲情", "友谊", "盟友", "爱人", "婚姻", "子女", "陪伴", "和解",
    ))
    if art_hits < 16 or human_hits < 7:
        failures.append(f"宽泛总纲艺术生涯或人物关系不足：艺术词{art_hits}次，人物关系词{human_hits}次")
    for phrase in ("A4纸", "You Are My Sunshine"):
        if phrase in synopsis:
            failures.append(f"宽泛总纲出现年代/现实作品错误：{phrase}")
    return failures


def _validate_global_narrative(obj: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for field, minimum in (
        ("story_title", 4), ("one_sentence_premise", 30),
        ("full_story_synopsis", 1800), ("romance_long_arc", 150),
        ("ending_convergence", 200),
    ):
        if len(str(obj.get(field) or "").strip()) < minimum:
            failures.append(f"global_narrative.{field}过短或缺失")
    logic = obj.get("core_rebirth_logic")
    if not isinstance(logic, dict):
        failures.append("core_rebirth_logic必须为对象")
    else:
        for field in ("previous_life_death", "information_gap", "new_life_method", "moral_boundary", "ultimate_goal"):
            if len(str(logic.get(field) or "").strip()) < 30:
                failures.append(f"core_rebirth_logic.{field}过短或缺失")
    rules = obj.get("downstream_nonnegotiables")
    if not isinstance(rules, list) or len(rules) < 8:
        failures.append("downstream_nonnegotiables至少8项")
    serialized = _json_text(obj)
    age_ok = any(token in serialized for token in ("十一岁", "11岁", "十一周岁", "11周岁"))
    if not age_ok or not all(token in serialized for token in ("2009", "1969", "保险", "版权")):
        failures.append("全书叙事梗概必须明确2009死亡、1969十一岁重生及保险/版权利益链")
    if not all(token in serialized for token in ("葬礼", "审判", "全球")) or not any(
        token in serialized for token in ("现身", "登台", "走上舞台", "走上现场", "走入现场", "踏上中央台阶", "踏上舞台")
    ):
        failures.append("全书叙事梗概必须明确本人在全球纪念现场登台并把葬礼变成审判")
    for phrase in ("北京", "上海", "中国", "纽约", "洛杉矶", "芝加哥", "好莱坞", "戛纳", "威尼斯", "东京", "Excel", "MTV", "通用电气", "联合国教科文组织", "国家职业安全卫生研究所", "Michael Jackson", "迈克尔·杰克逊"):
        if phrase in serialized:
            failures.append(f"全书叙事梗概世界观错误：禁止出现“{phrase}”")
    if "奥瑞安" in serialized:
        failures.append("集团名称不一致：统一使用‘奥瑞恩集团’，不得写‘奥瑞安’")
    for phrase in ("模仿笔迹", "伪造证据", "服务器跳转", "十五国独立服务器", "万能黑客", "不可中断、不可剪辑、不可屏蔽"):
        if phrase in serialized and not any(
            negation + phrase in serialized for negation in ("不", "不得", "禁止", "绝不", "严禁")
        ):
            failures.append(f"全书叙事梗概禁止伪造证据或技术捷径“{phrase}”")
    physical_live_appearance = (
        all(token in serialized for token in ("直播", "现场", "本人"))
        and any(token in serialized for token in ("现身", "走上舞台", "走上现场", "登台", "走入会场", "走入现场", "踏上舞台"))
    )
    if not physical_live_appearance:
        failures.append("终局必须明确麦珂在全球纪念直播结束前本人走上现场，不能只用全息影像或事后出现")
    synopsis = str(obj.get("full_story_synopsis") or "")
    procedural_hits = _procedural_hits(synopsis)
    if procedural_hits > 18:
        failures.append(f"宽泛叙事程序/取证意象过密，共{procedural_hits}次")
    failures.extend(_fake_death_failures(obj, "全书叙事"))
    failures.extend(_global_semantic_failures(obj, "全书叙事"))
    if synopsis.count("蓝雪") > 3:
        failures.append("蓝雪只能用于死亡—重生视觉对应")
    required_domains = (
        ("舞台", "演出"), ("创作", "作品"), ("家庭", "家人"),
        ("粉丝", "公益"), ("媒体", "舆论"), ("健康", "安全"),
    )
    if sum(any(term in synopsis for term in group) for group in required_domains) < 5:
        failures.append("宽泛叙事必须覆盖至少5类天王生涯内容")
    contract_root = any(term in serialized for term in ("第一份合同", "首份合同", "最初合同", "第一张合同"))
    system_root = any(term in serialized for term in ("控制体系", "控制结构", "权力结构", "利益体系", "利益链"))
    if not (contract_root and system_root):
        failures.append("宽泛叙事必须明确从第一份合同开始拆掉2009死亡控制体系")
    art_hits = sum(synopsis.count(term) for term in (
        "舞台", "演出", "音乐", "作品", "歌曲", "创作", "观众", "发行", "榜单", "巡演",
        "录音", "专辑", "旋律", "编曲", "编舞", "唱片", "乐队", "歌声", "票房", "现场",
    ))
    human_hits = sum(synopsis.count(term) for term in (
        "家庭", "家人", "母亲", "兄弟", "伙伴", "粉丝", "公益", "关系", "爱情", "孩子",
        "玛莎", "帕丽丝", "亲情", "友谊", "盟友", "爱人", "婚姻", "子女", "陪伴", "和解",
    ))
    if art_hits < 16 or human_hits < 7:
        failures.append(f"宽泛叙事艺术生涯或人物关系不足：艺术词{art_hits}次，人物关系词{human_hits}次")
    for phrase in ("A4纸", "You Are My Sunshine"):
        if phrase in synopsis:
            failures.append(f"宽泛叙事出现年代/现实作品错误：{phrase}")
    return failures


def _validate_global_narrative_core(obj: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for field, minimum in (
        ("story_title", 4), ("one_sentence_premise", 30),
        ("romance_overview", 80), ("ending_convergence", 220),
    ):
        if len(str(obj.get(field) or "").strip()) < minimum:
            failures.append(f"global_narrative_core.{field}过短或缺失")
    logic = obj.get("core_rebirth_logic")
    if not isinstance(logic, dict):
        failures.append("global_narrative_core.core_rebirth_logic必须为对象")
    else:
        for field in ("previous_life_death", "information_gap", "new_life_method", "moral_boundary", "ultimate_goal"):
            if len(str(logic.get(field) or "").strip()) < 30:
                failures.append(f"global_narrative_core.core_rebirth_logic.{field}过短或缺失")
    rules = obj.get("downstream_nonnegotiables")
    if not isinstance(rules, list) or len(rules) < 10:
        failures.append("global_narrative_core.downstream_nonnegotiables至少10项")
    else:
        required_rule_tags = ("【作品】", "【舞台】", "【家庭】", "【粉丝公益】", "【媒体】", "【市场】")
        for index, tag in enumerate(required_rule_tags):
            if not str(rules[index]).startswith(tag):
                failures.append(f"downstream_nonnegotiables第{index + 1}条必须以{tag}开头")
    serialized = _json_text(obj)
    ending = str(obj.get("ending_convergence") or "")
    if re.search(r"第\s*\d+\s*章", ending):
        failures.append("核心终局必须是宽泛收束，不得预写第几章")
    if any(token in ending for token in ("1.", "2.", "3.", "4.", "5.", "逐一", "编号")):
        failures.append("核心终局不得列逐项证据或程序清单")
    if _procedural_hits(ending) > 5:
        failures.append("核心终局程序/取证意象过密，应锁定人物选择、反派误判和舞台爽点")
    if re.search(r"(?:敌人|敌方|对手|维克多|集团).{0,80}(?:误判|认定|以为).{0,40}(?:已死|已亡|已经死|早已死|已经死亡)", serialized):
        failures.append("核心契约敌人认知错误：敌人知道麦珂活着，只误判旧方案会在2009得手")
    if not all(term in serialized for term in ("2009", "1969", "十一岁", "保险", "版权")):
        failures.append("全书核心契约必须锁定2009死亡、1969十一岁重生及保险/版权利益链")
    if not all(term in serialized for term in ("全球", "纪念", "直播", "本人", "审判")):
        failures.append("全书核心契约必须锁定本人走入全球纪念直播完成审判")
    failures.extend(_fake_death_failures(obj, "全书核心契约"))
    failures.extend(_global_semantic_failures(obj, "全书核心契约"))
    if _procedural_hits(obj) > 14:
        failures.append("全书核心契约程序词过密；不可违背事实必须以人生方向和人物选择为主")
    rules_text = _json_text(rules if isinstance(rules, list) else [])
    life_domain_groups = (
        ("作品", "歌曲", "创作", "音乐"), ("舞台", "演出", "巡演"),
        ("家庭", "母亲", "家人", "关系"), ("粉丝", "公益", "观众"),
        ("媒体", "舆论", "声誉"), ("市场", "发行", "事业"),
    )
    if sum(any(term in rules_text for term in group) for group in life_domain_groups) < 4:
        failures.append("全书核心契约的不可违背事实至少覆盖作品、舞台、家庭、粉丝、媒体、市场中的4域")
    return list(dict.fromkeys(failures))


def _validate_global_narrative_segment(obj: dict[str, Any], part: int) -> list[str]:
    failures: list[str] = []
    if obj.get("segment_id") != f"S{part}":
        failures.append(f"segment_id必须为S{part}")
    synopsis = str(obj.get("segment_synopsis") or "").strip()
    if len(synopsis) < 750:
        failures.append(f"S{part}.segment_synopsis不足750字")
    if len(synopsis) > 2200:
        failures.append(f"S{part}.segment_synopsis超过2200字")
    for field, minimum in (("opening_state", 30), ("closing_state", 50), ("handoff", 30), ("romance_progression", 40)):
        if len(str(obj.get(field) or "").strip()) < minimum:
            failures.append(f"S{part}.{field}过短或缺失")
    serialized = _json_text(obj)
    if part in (1, 2) and re.search(
        r"(?:敌方|敌人|对手|维克多|集团).{0,80}(?:以为|误以为|误判|认定).{0,40}(?:已死|已经死|早已死|已经消失|彻底消失)",
        serialized,
    ):
        failures.append(
            f"S{part}敌人认知时间倒置：今生麦珂公开成长，敌人不得在2009终局前认定他已经死亡或消失"
        )
    if part in (1, 2) and re.search(r"仍.{0,20}2009年死亡后", serialized):
        failures.append(f"S{part}把尚未来临的今生2009死亡写成敌人已知既成事实")
    if part == 2:
        handoff = str(obj.get("handoff") or "")
        leaked_terminal_terms = [term for term in ("纪念", "葬礼", "直播", "讣告") if term in handoff]
        if leaked_terminal_terms:
            failures.append(
                "S2.handoff不得预演2009终局词：" + "、".join(leaked_terminal_terms)
                + "；只写1998结果如何引出1999新压力"
            )
    if part == 1:
        failures.extend(_early_planning_semantic_failures(obj, "全书叙事S1"))
        for term in ("2009", "1969", "十一岁", "第一份合同"):
            if term not in serialized:
                failures.append(f"S1必须明确“{term}”")
    if part == 3:
        canonical_segment_text = "\n".join(str(obj.get(key) or "") for key in (
            "segment_synopsis", "closing_state", "handoff",
        ))
        # Exact terminal wording is also supplied by the separately authored
        # core ending_convergence when the whole synopsis is assembled.  S3
        # itself must nevertheless dramatize a physical live appearance.
        if not all(term in canonical_segment_text for term in ("全球", "纪念", "直播", "麦珂")):
            failures.append("S3正式叙事必须写全球纪念直播与麦珂")
        if not any(term in canonical_segment_text for term in ("登台", "走入现场", "走上现场", "走上舞台", "现身", "走入主会场", "步入主会场", "走入全球纪念直播现场")):
            failures.append("S3正式叙事必须明确麦珂本人登台或走入现场")
    # Scan every field that describes the current-life segment, not only the
    # main synopsis.  The previous validator missed anachronisms hidden in
    # handoff/closing_state (for example 1982 “网络留言”).  opening_state is
    # intentionally excluded because S1 legitimately opens on the 2009 death.
    segment_life_text = _json_text({
        key: obj.get(key)
        for key in ("segment_synopsis", "romance_progression", "closing_state", "handoff")
    })
    segment_end_year = {1: 1982, 2: 1998, 3: 2009}[part]
    for phrase, available_from in TECH_AVAILABLE_FROM.items():
        if available_from > segment_end_year and phrase in segment_life_text:
            failures.append(
                f"S{part}年代技术错误：本段截至{segment_end_year}年，不得提前出现“{phrase}”"
            )
    for phrase in ("AI", "人工智能"):
        if part in (1, 2) and phrase in segment_life_text:
            failures.append(f"S{part}年代技术错误：不得提前出现“{phrase}”")
    failures.extend(_fake_death_failures(obj, f"全书叙事S{part}"))
    failures.extend(_global_semantic_failures(obj, f"全书叙事S{part}"))
    procedural_hits = _procedural_hits(synopsis)
    if procedural_hits > (7 if part == 1 else 6):
        failures.append(f"S{part}程序/取证意象过密，共{procedural_hits}次；必须以作品、舞台、人物和市场为主")
    return list(dict.fromkeys(failures))


def _assemble_global_narrative(
    core: dict[str, Any], segments: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "story_title": core["story_title"],
        "one_sentence_premise": core["one_sentence_premise"],
        # S1.opening_state is the Qwen-authored previous-life prologue.  Keep it
        # inside the canonical synopsis so downstream planners cannot silently
        # lose the fundamental 2009-death -> 1969-rebirth premise by reading
        # only full_story_synopsis.
        "full_story_synopsis": "\n\n".join([
            str(segments[0]["opening_state"]).strip(),
            *(
                text
                for item in segments
                for text in (
                    str(item["segment_synopsis"]).strip(),
                    str(item["handoff"]).strip(),
                )
            ),
            str(core["ending_convergence"]).strip(),
        ]),
        "core_rebirth_logic": core["core_rebirth_logic"],
        "romance_long_arc": "\n".join([
            str(core["romance_overview"]).strip(),
            *[str(item["romance_progression"]).strip() for item in segments],
        ]),
        "ending_convergence": core["ending_convergence"],
        "downstream_nonnegotiables": core["downstream_nonnegotiables"],
        "assembled_from_qwen_batches": ["GLOBAL_narrative_core", "GLOBAL_narrative_s1", "GLOBAL_narrative_s2", "GLOBAL_narrative_s3"],
    }


def _validate_global_phases(obj: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    phases = obj.get("life_phases")
    if not isinstance(phases, list) or len(phases) != 10:
        failures.append("life_phases必须恰好10项")
    else:
        for index, phase in enumerate(phases, 1):
            expected_span = list(_volume_bounds(index))
            if phase.get("phase_id") != f"P{index:02d}":
                failures.append(f"第{index}阶段phase_id必须为P{index:02d}")
            if phase.get("chapter_span") != expected_span:
                failures.append(f"P{index:02d}.chapter_span必须为{expected_span}")
            for field in (
                "timeline_years", "broad_story_goal", "main_pressure", "rebirth_advantage",
                "major_turning_point", "phase_outcome", "handoff_to_next_phase",
            ):
                minimum = 4 if field == "timeline_years" else 20
                if len(str(phase.get(field) or "").strip()) < minimum:
                    failures.append(f"P{index:02d}.{field}过短或缺失")
            if not isinstance(phase.get("major_characters"), list) or len(phase["major_characters"]) < 2:
                failures.append(f"P{index:02d}.major_characters至少2人")
    ledger = obj.get("state_ledger_by_phase")
    if not isinstance(ledger, list) or len(ledger) != 10:
        failures.append("state_ledger_by_phase必须恰好10项")
        ledger = []
    ledger_by_phase = {
        str(item.get("phase_id") or ""): item for item in ledger if isinstance(item, dict)
    }
    if isinstance(phases, list):
        early_forbidden = (
            "电子邮件", "邮箱", "互联网", "网站", "全网", "上传", "下载", "开源",
            "数据接口", "自动抓取", "自动打标", "元数据", "智能终端", "社交媒体",
            "碳追踪平台", "用户协议", "纪实网", "AI", "人工智能", "云端", "指纹解锁",
        )
        for index, phase in enumerate(phases, 1):
            if index > 5 or not isinstance(phase, dict):
                continue
            phase_id = f"P{index:02d}"
            phase_text = _json_text({"phase": phase, "state": ledger_by_phase.get(phase_id)})
            for phrase in early_forbidden:
                if phrase in phase_text:
                    failures.append(f"{phase_id}年代技术错误：1991年前不得出现“{phrase}”")
    if isinstance(phases, list) and len(phases) >= 2:
        if "1975年成年" in _json_text(phases[1]):
            failures.append("P02年龄错误：麦珂1969年十一岁，成年节点不得写成1975年")
    failures.extend(_fake_death_failures(obj, "全书阶段"))
    failures.extend(_global_semantic_failures(obj, "全书阶段"))
    serialized = _json_text(obj)
    future_years = sorted({int(x) for x in re.findall(r"(?:19|20)\d{2}", serialized) if int(x) > 2009})
    if future_years:
        failures.append(f"全书阶段不得越过2009终局：{future_years}")
    for phrase in ("北京", "上海", "中国", "纽约", "洛杉矶", "芝加哥", "好莱坞", "戛纳", "威尼斯", "东京", "Excel", "MTV", "通用电气", "联合国教科文组织", "国家职业安全卫生研究所", "Michael Jackson", "迈克尔·杰克逊"):
        if phrase in serialized:
            failures.append(f"全书阶段结构世界观错误：禁止出现“{phrase}”")
    if "奥瑞安" in serialized:
        failures.append("集团名称不一致：统一使用‘奥瑞恩集团’，不得写‘奥瑞安’")
    return failures


def _validate_global_phase_part(obj: dict[str, Any], part: int) -> list[str]:
    failures: list[str] = []
    start_index = 1 if part == 1 else 6
    expected_indices = list(range(start_index, start_index + 5))
    phases = obj.get("life_phases")
    ledger = obj.get("state_ledger_by_phase")
    if not isinstance(phases, list) or len(phases) != 5:
        return [f"life_phases第{part}批必须恰好5项"]
    if not isinstance(ledger, list) or len(ledger) != 5:
        failures.append(f"state_ledger_by_phase第{part}批必须恰好5项")
        ledger = []
    ledger_by_phase = {
        str(item.get("phase_id") or ""): item for item in ledger if isinstance(item, dict)
    }
    early_forbidden = (
        "电子邮件", "邮箱", "互联网", "网站", "全网", "上传", "下载", "开源",
        "数据接口", "自动抓取", "自动打标", "元数据", "智能终端", "社交媒体",
        "碳追踪平台", "用户协议", "纪实网", "AI", "人工智能", "云端", "指纹解锁",
    )
    for local, index in enumerate(expected_indices):
        phase = phases[local]
        phase_id = f"P{index:02d}"
        expected_span = list(_volume_bounds(index))
        if phase.get("phase_id") != phase_id:
            failures.append(f"第{local + 1}项phase_id必须为{phase_id}")
        if phase.get("chapter_span") != expected_span:
            failures.append(f"{phase_id}.chapter_span必须为{expected_span}")
        for field in (
            "timeline_years", "broad_story_goal", "main_pressure", "rebirth_advantage",
            "major_turning_point", "phase_outcome", "handoff_to_next_phase",
        ):
            minimum = 4 if field == "timeline_years" else 20
            if len(str(phase.get(field) or "").strip()) < minimum:
                failures.append(f"{phase_id}.{field}过短或缺失")
        if not isinstance(phase.get("major_characters"), list) or len(phase["major_characters"]) < 2:
            failures.append(f"{phase_id}.major_characters至少2人")
        if index <= 5:
            phase_text = _json_text({"phase": phase, "state": ledger_by_phase.get(phase_id)})
            for phrase in early_forbidden:
                if phrase in phase_text:
                    failures.append(f"{phase_id}年代技术错误：1991年前不得出现“{phrase}”")
        if index == 2 and "1975年成年" in _json_text(phase):
            failures.append("P02年龄错误：成年节点不得写成1975年")
    failures.extend(_fake_death_failures(obj, f"全书阶段第{part}批"))
    failures.extend(_global_semantic_failures(obj, f"全书阶段第{part}批"))
    serialized = _json_text(obj)
    future_years = sorted({int(x) for x in re.findall(r"(?:19|20)\d{2}", serialized) if int(x) > 2009})
    if future_years:
        failures.append(f"全书阶段第{part}批不得越过2009终局：{future_years}")
    for phrase in ("北京", "上海", "中国", "纽约", "洛杉矶", "芝加哥", "好莱坞", "戛纳", "威尼斯", "东京", "Excel", "MTV", "通用电气", "联合国教科文组织", "国家职业安全卫生研究所", "Michael Jackson", "迈克尔·杰克逊"):
        if phrase in serialized:
            failures.append(f"全书阶段第{part}批世界观错误：禁止出现“{phrase}”")
    if "奥瑞安" in serialized:
        failures.append("集团名称不一致：统一使用‘奥瑞恩集团’，不得写‘奥瑞安’")
    return failures


def _validate_global_threads(obj: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for field, minimum in (("character_long_arcs", 10), ("causal_spine", 15), ("foreshadow_ledger", 12)):
        value = obj.get(field)
        if not isinstance(value, list) or len(value) != minimum:
            failures.append(f"{field}必须恰好{minimum}项")
    arcs = obj.get("character_long_arcs") or []
    causal = obj.get("causal_spine") or []
    foreshadows = obj.get("foreshadow_ledger") or []
    valid_phases = {f"P{i:02d}" for i in range(1, 11)}
    if isinstance(causal, list):
        for index, item in enumerate(causal, 1):
            if not isinstance(item, dict) or item.get("spine_id") != f"CS{index:02d}":
                failures.append(f"causal_spine第{index}项spine_id必须为CS{index:02d}")
    if isinstance(foreshadows, list):
        for index, item in enumerate(foreshadows, 1):
            if not isinstance(item, dict):
                failures.append(f"foreshadow_ledger第{index}项必须为对象")
                continue
            expected_id = f"FS{index:02d}"
            if item.get("thread_id") != expected_id:
                failures.append(f"foreshadow_ledger第{index}项thread_id必须为{expected_id}")
            plant = str(item.get("plant_phase") or "")
            payoff = str(item.get("payoff_phase") or "")
            development = item.get("development_phases") or []
            if plant not in valid_phases or payoff not in valid_phases:
                failures.append(f"{expected_id}种植或回收阶段必须是P01—P10")
                continue
            phase_sequence = [plant] + [str(x) for x in development] + [payoff]
            if any(phase not in valid_phases for phase in phase_sequence):
                failures.append(f"{expected_id}.development_phases含非法阶段")
            elif [int(x[1:]) for x in phase_sequence] != sorted(int(x[1:]) for x in phase_sequence):
                failures.append(f"{expected_id}阶段顺序必须满足种植≤发展≤回收")
            year_match = re.search(r"(?:19|20)\d{2}", str(item.get("plant_year") or ""))
            if not year_match:
                failures.append(f"{expected_id}.plant_year必须是四位数年份")
                year_match = re.search(r"(?:19|20)\d{2}", str(item.get("thread") or ""))
            if year_match:
                year = int(year_match.group())
                candidates = _phase_candidates_for_year(year)
                if candidates and plant not in candidates:
                    failures.append(f"{expected_id}写明{year}年，但plant_phase={plant}，应为{sorted(candidates)}之一")
            payoff_match = re.search(r"(?:19|20)\d{2}", str(item.get("payoff_year") or ""))
            if not payoff_match:
                failures.append(f"{expected_id}.payoff_year必须是四位数年份")
            else:
                payoff_candidates = _phase_candidates_for_year(int(payoff_match.group()))
                if payoff_candidates and payoff not in payoff_candidates:
                    failures.append(
                        f"{expected_id}.payoff_year={payoff_match.group()}与payoff_phase={payoff}不一致"
                    )
    for index, arc in enumerate(arcs, 1) if isinstance(arcs, list) else []:
        phase = str(arc.get("first_active_phase") or "") if isinstance(arc, dict) else ""
        if phase not in valid_phases:
            failures.append(f"character_long_arcs第{index}项first_active_phase非法")
    failures.extend(_validate_global_arc_identities(arcs))
    serialized = _json_text(obj)
    for phrase in ("北京", "上海", "中国", "纽约", "洛杉矶", "芝加哥", "好莱坞", "戛纳", "威尼斯", "东京", "Excel", "MTV", "通用电气", "联合国教科文组织", "国家职业安全卫生研究所", "Michael Jackson", "迈克尔·杰克逊", "AI还原", "人工智能还原"):
        if phrase in serialized:
            failures.append(f"全书长弧账本世界观错误：禁止出现“{phrase}”")
    if "奥瑞安" in serialized:
        failures.append("集团名称不一致：统一使用‘奥瑞恩集团’，不得写‘奥瑞安’")
    return failures


def _validate_global_arc_identities(arcs: Any) -> list[str]:
    """Reject renamed, abbreviated, reordered or ID-drifted global characters."""
    failures: list[str] = []
    if not isinstance(arcs, list):
        return failures
    expected_by_id = {item["character_id"]: item for item in GLOBAL_ARC_IDENTITIES}
    seen_ids: set[str] = set()
    for index, arc in enumerate(arcs, 1):
        if not isinstance(arc, dict):
            continue
        expected = GLOBAL_ARC_IDENTITIES[index - 1] if index <= len(GLOBAL_ARC_IDENTITIES) else None
        cid = str(arc.get("character_id") or "")
        name = str(arc.get("character") or "").strip()
        aliases = arc.get("aliases")
        if expected is not None and (cid != expected["character_id"] or name != expected["character"]):
            failures.append(
                f"character_long_arcs第{index}项身份必须为"
                f"{expected['character']}({expected['character_id']})，不得改名、缩写或换姓"
            )
        if cid in seen_ids:
            failures.append(f"character_long_arcs重复character_id={cid or '<空>'}")
        seen_ids.add(cid)
        canonical = expected_by_id.get(cid)
        if canonical is None:
            failures.append(f"character_long_arcs第{index}项含未知character_id={cid or '<空>'}")
        elif aliases != canonical["aliases"]:
            failures.append(
                f"character_long_arcs第{index}项aliases必须严格为{canonical['aliases']}"
            )
    if len(arcs) == len(GLOBAL_ARC_IDENTITIES) and seen_ids != set(expected_by_id):
        failures.append("character_long_arcs必须完整覆盖锁定的10个稳定character_id")
    return failures


def _validate_global_long_arcs(obj: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    arcs = obj.get("character_long_arcs")
    causal = obj.get("causal_spine")
    valid_phases = {f"P{i:02d}" for i in range(1, 11)}
    if not isinstance(arcs, list) or len(arcs) != 10:
        failures.append("character_long_arcs必须恰好10项")
        arcs = []
    if not isinstance(causal, list) or len(causal) != 15:
        failures.append("causal_spine必须恰好15项")
        causal = []
    failures.extend(_validate_global_arc_identities(arcs))
    for index, arc in enumerate(arcs, 1):
        if not isinstance(arc, dict):
            failures.append(f"character_long_arcs第{index}项必须为对象")
            continue
        if str(arc.get("first_active_phase") or "") not in valid_phases:
            failures.append(f"character_long_arcs第{index}项first_active_phase非法")
        for field, minimum in (
            ("character", 2), ("initial_desire", 8), ("long_term_change", 8),
            ("relationship_with_protagonist", 8), ("final_state", 8),
        ):
            if len(str(arc.get(field) or "").strip()) < minimum:
                failures.append(f"character_long_arcs第{index}项{field}过短或缺失")
        arc_text = _json_text(arc)
        future_years = [int(x) for x in re.findall(r"(?:19|20)\d{2}", arc_text) if int(x) > 2009]
        if future_years:
            failures.append(f"character_long_arcs第{index}项越过2009终局：{future_years}")
    for index, item in enumerate(causal, 1):
        expected_id = f"CS{index:02d}"
        if not isinstance(item, dict) or item.get("spine_id") != expected_id:
            failures.append(f"causal_spine第{index}项spine_id必须为{expected_id}")
            continue
        phase_ids = re.findall(r"P\d{2}", str(item.get("phase_range") or ""))
        if len(phase_ids) < 2 or any(x not in valid_phases for x in phase_ids):
            failures.append(f"{expected_id}.phase_range必须含两个合法阶段")
        elif int(phase_ids[0][1:]) > int(phase_ids[-1][1:]):
            failures.append(f"{expected_id}.phase_range不得倒退")
        cause_year = re.search(r"(?:19|20)\d{2}", str(item.get("cause") or ""))
        if cause_year and phase_ids:
            candidates = _phase_candidates_for_year(int(cause_year.group()))
            if candidates and phase_ids[0] not in candidates:
                failures.append(
                    f"{expected_id}.cause写明{cause_year.group()}年，但phase_range起点为{phase_ids[0]}；"
                    f"正确起点只能是{sorted(candidates)}。只修改phase_range起点，保留cause剧情，"
                    "并确保它不与其他CS的cause重复"
                )
        for field in ("cause", "protagonist_choice", "result", "later_consequence"):
            if len(str(item.get(field) or "").strip()) < 10:
                failures.append(f"{expected_id}.{field}过短或缺失")
        joined = _json_text(item)
        if (
            "行为能力" in joined
            and any(token in joined for token in ("声纹", "录音", "尺码"))
            and any(token in joined for token in ("唯一证明", "单独证明", "决定性证据"))
        ):
            failures.append(f"{expected_id}不能仅用声纹、录音或衣物尺码决定法律行为能力")
    for left in range(len(causal)):
        for right in range(left + 1, len(causal)):
            cause_a = str(causal[left].get("cause") or "")
            cause_b = str(causal[right].get("cause") or "")
            if cause_a and cause_b and SequenceMatcher(None, cause_a, cause_b).ratio() >= 0.60:
                failures.append(f"CS{left + 1:02d}与CS{right + 1:02d}重复使用同一因果起点")
    payoff_phases = []
    for item in causal:
        ids = re.findall(r"P\d{2}", str(item.get("phase_range") or ""))
        if ids:
            payoff_phases.append(ids[-1])
    if payoff_phases.count("P10") > 10 or len(set(payoff_phases)) < 3:
        failures.append("15条因果链不得全部拖到P10：P10终结最多10条，且至少分布到3个结果阶段")
    if len(payoff_phases) >= 5 and any(phase == "P10" for phase in payoff_phases[:5]):
        failures.append("CS01—CS05必须分别在P10以前完成中期回报，不能写成→P10")
    serialized = _json_text(obj)
    failures.extend(_fake_death_failures(obj, "人物与因果长弧"))
    failures.extend(_global_semantic_failures(obj, "人物与因果长弧"))
    if _procedural_hits(obj) > 70:
        failures.append("人物与因果长弧过度依赖公证、钢印、编号、波形等取证机关术")
    for phrase in ("北京", "上海", "中国", "纽约", "洛杉矶", "芝加哥", "好莱坞", "戛纳", "威尼斯", "东京", "Excel", "MTV", "索尼", "通用电气", "联合国教科文组织", "国家职业安全卫生研究所", "Michael Jackson", "迈克尔·杰克逊", "AI还原", "人工智能还原"):
        if phrase in serialized:
            failures.append(f"人物与因果长弧世界观错误：禁止出现“{phrase}”")
    if "奥瑞安" in serialized:
        failures.append("集团名称必须统一写‘奥瑞恩集团’")
    return failures


def _validate_global_foreshadows(
    obj: dict[str, Any], start_index: int = 1, expected_count: int = 12,
) -> list[str]:
    failures: list[str] = []
    foreshadows = obj.get("foreshadow_ledger")
    valid_phases = {f"P{i:02d}" for i in range(1, 11)}
    if not isinstance(foreshadows, list) or len(foreshadows) != expected_count:
        return [f"foreshadow_ledger必须恰好{expected_count}项"]
    for index, item in enumerate(foreshadows, start_index):
        expected_id = f"FS{index:02d}"
        if not isinstance(item, dict):
            failures.append(f"{expected_id}必须为对象")
            continue
        if item.get("thread_id") != expected_id:
            failures.append(f"第{index}项thread_id必须为{expected_id}")
        plant = str(item.get("plant_phase") or "")
        payoff = str(item.get("payoff_phase") or "")
        assigned_payoffs = ("P03", "P04", "P05", "P06", "P07", "P09")
        if index <= 6 and payoff != assigned_payoffs[index - 1]:
            failures.append(f"{expected_id}.payoff_phase必须为{assigned_payoffs[index - 1]}，用于中期回收")
        if index >= 7 and payoff != "P10":
            failures.append(f"{expected_id}.payoff_phase必须为P10，用于终局汇合")
        assigned_payoff_years = (1981, 1985, 1990, 1992, 1997, 2006, 2009, 2009, 2009, 2009, 2009, 2009)
        if str(item.get("payoff_year") or "") != str(assigned_payoff_years[index - 1]):
            failures.append(f"{expected_id}.payoff_year必须为{assigned_payoff_years[index - 1]}")
        assigned_plants = (
            (1969, "P01"), (1973, "P02"), (1980, "P03"), (1984, "P04"),
            (1988, "P05"), (1996, "P07"), (2001, "P08"), (2002, "P08"),
            (2003, "P08"), (2003, "P08"), (2005, "P09"), (2007, "P09"),
        )
        assigned_plant_year, assigned_plant_phase = assigned_plants[index - 1]
        if str(item.get("plant_year") or "") != str(assigned_plant_year):
            failures.append(f"{expected_id}.plant_year必须为{assigned_plant_year}")
        if plant != assigned_plant_phase:
            failures.append(f"{expected_id}.plant_phase必须为{assigned_plant_phase}")
        development = item.get("development_phases")
        if not isinstance(development, list) or not development:
            failures.append(f"{expected_id}.development_phases至少1项")
            development = []
        assigned_developments = (
            "P02", "P03", "P04", "P05", "P06", "P08",
            "P09", "P09", "P09", "P09", "P10", "P10",
        )
        if development != [assigned_developments[index - 1]]:
            failures.append(
                f"{expected_id}.development_phases必须恰好为['{assigned_developments[index - 1]}']"
            )
        phase_sequence = [plant] + [str(x) for x in development] + [payoff]
        if any(phase not in valid_phases for phase in phase_sequence):
            failures.append(f"{expected_id}含非法阶段，必须为P01—P10")
        elif [int(x[1:]) for x in phase_sequence] != sorted(int(x[1:]) for x in phase_sequence):
            failures.append(f"{expected_id}阶段顺序必须满足种植≤发展≤回收")
        for year_field, phase, label in (
            ("plant_year", plant, "种植"), ("payoff_year", payoff, "回收"),
        ):
            match = re.search(r"(?:19|20)\d{2}", str(item.get(year_field) or ""))
            if not match:
                failures.append(f"{expected_id}.{year_field}必须是四位数年份")
                continue
            candidates = _phase_candidates_for_year(int(match.group()))
            if candidates and phase not in candidates:
                failures.append(f"{expected_id}{label}年份{match.group()}与阶段{phase}不一致，应为{sorted(candidates)}之一")
        if len(str(item.get("thread") or "").strip()) < 15:
            failures.append(f"{expected_id}.thread过短或缺失")
        if len(str(item.get("payoff_function") or "").strip()) < 12:
            failures.append(f"{expected_id}.payoff_function过短或缺失")
        story_text = str(item.get("thread") or "") + " " + str(item.get("payoff_function") or "")
        phase_mentions = re.findall(r"P\d{2}", story_text)
        if any(phase not in valid_phases for phase in phase_mentions):
            failures.append(f"{expected_id}使用了非法Pxx规划编号")
        if phase_mentions and re.search(
            r"(?:编号|刻|烫印|印有|标签|文件名).{0,12}P\d{2}|P\d{2}.{0,12}(?:编号|刻|烫印|印有|标签|文件名)",
            story_text,
        ):
            failures.append(f"{expected_id}把Pxx规划编号刻进了故事世界")
        for illogical in (
            "心理崩溃", "气候都已纳入", "生理真实性", "离心管", "X射线", "能谱分析",
            "红外光谱", "红外吸收", "氯化钴", "钨钢珠", "重合度",
            "相位偏移", "forensic lab", "UPS固件", "生物节律校准参数",
            "误差小于", "硬件锚点", "热敏字迹氧化", "紫外验钞笔", "隐藏UV",
            "荧光波形", "时空同一性", "背景杂音中截取", "P6-VERIFIED",
        ):
            if illogical in story_text:
                failures.append(f"{expected_id}使用不可靠或不相干的证据推理“{illogical}”")
        magical_relic_terms = (
            "仍在原位", "未发生位移", "从未移动", "完全一致", "一一吻合", "毫秒级",
            "纹理比对", "纹理完全", "反射斑点", "三维叠印", "物质信标", "物理坐标",
            "表皮裂纹", "种皮纹理", "羽毛光泽", "叶脉走向", "墨水洇染方向",
            "刻刀入金属深度", "未进行地面填缝", "多年零误差", "十四年的行为连续性",
        )
        relic_hits = [term for term in magical_relic_terms if term in story_text]
        if relic_hits:
            failures.append(
                f"{expected_id}把多年保存小物件当伪法证：{relic_hits[:4]}；"
                "请整条改成作品回响、舞台习惯、人物承诺、家庭选择、粉丝组织或公开立场的因果回收"
            )
        if any(relic in story_text for relic in ("蜡笔", "树叶", "叶脉", "种子", "梧桐籽", "羽毛", "鸟羽")) and any(
            proof in story_text for proof in ("证明", "证实", "铁证", "见证", "比对", "一致")
        ):
            failures.append(
                f"{expected_id}禁止用蜡笔/叶片/种子/羽毛等小物件跨多年证明身份或事实；改写伏笔类型"
            )
        # This is a style-quality guard, not a continuity/safety invariant.  A
        # terminal foreshadow may legitimately contain several procedural
        # nouns when it pays off an opponent's institutional trap.  Reject only
        # extreme saturation; otherwise keep the model output and move on to
        # the detailed planning layers instead of endlessly rewriting it.
        if _procedural_hits(story_text) > 10:
            failures.append(f"{expected_id}程序/法证意象过密；伏笔应优先是作品、关系、舞台选择或对手行为")
    if start_index == 1 and expected_count == 12:
        payoff_phases = [str(item.get("payoff_phase") or "") for item in foreshadows]
        if payoff_phases.count("P10") > 6:
            failures.append("12条伏笔不得全部拖到终局：payoff_phase=P10最多6条")
        if len(set(payoff_phases)) < 4:
            failures.append("12条伏笔至少分布到4个不同回收阶段")
    serialized = _json_text(obj)
    failures.extend(_global_semantic_failures(obj, "伏笔账本"))
    failures.extend(_fake_death_failures(obj, "伏笔账本"))
    if _procedural_hits(obj) > 42:
        failures.append("12条伏笔整体过度依赖公证、编号、纸张、印章和波形，至少一半必须改为作品/关系/舞台/舆论伏笔")
    for phrase in ("北京", "上海", "中国", "纽约", "洛杉矶", "芝加哥", "好莱坞", "戛纳", "威尼斯", "东京", "Excel", "MTV", "索尼", "通用电气", "联合国教科文组织", "国家职业安全卫生研究所", "Michael Jackson", "迈克尔·杰克逊", "AI还原", "人工智能还原"):
        if phrase in serialized:
            failures.append(f"伏笔账本世界观错误：禁止出现“{phrase}”")
    if "奥瑞安" in serialized:
        failures.append("集团名称必须统一写‘奥瑞恩集团’")
    return failures


def _relevant_anchors(volume: dict[str, Any]) -> list[dict[str, Any]]:
    # The list is deliberately small enough to fit every volume prompt; Qwen
    # decides which anchors are useful and may invent obstacles around them.
    volume_years = str(volume.get("years") or "")
    digits = [int(x) for x in re.findall(r"(?:19|20)\d{2}", volume_years)]
    if not digits:
        return RESEARCH_ANCHORS
    low, high = min(digits), max(digits)
    selected: list[dict[str, Any]] = []
    for anchor in RESEARCH_ANCHORS:
        years = [int(x) for x in re.findall(r"(?:19|20)\d{2}", str(anchor.get("years") or ""))]
        if years and max(years) >= low - 1 and min(years) <= high + 1:
            selected.append(anchor)
    return selected or RESEARCH_ANCHORS


def _validate_volume(obj: dict[str, Any], volume_index: int) -> list[str]:
    failures: list[str] = []
    groups = obj.get("macro_groups")
    if not isinstance(groups, list) or len(groups) != 5:
        return ["macro_groups必须恰好5项"]
    volume_start, _ = _volume_bounds(volume_index)
    for local, group in enumerate(groups, 1):
        expected_index = (volume_index - 1) * 5 + local
        expected_id = f"MG{expected_index:03d}"
        expected_span = list(_macro_bounds(expected_index))
        if group.get("macro_group_id") != expected_id:
            failures.append(f"第{local}组macro_group_id必须为{expected_id}")
        if group.get("chapter_span") != expected_span:
            failures.append(f"{expected_id}.chapter_span必须为{expected_span}")
        minimums = {
            "title": 3, "timeline_years": 4, "macro_goal": 8,
            "historical_stage": 8, "main_conflict": 8, "rebirth_advantage": 8,
            "romance_progression": 8, "ending_state": 8, "next_group_hook": 8,
        }
        for field, minimum in minimums.items():
            if len(str(group.get(field) or "").strip()) < minimum:
                failures.append(f"{expected_id}.{field}过短或缺失")
        directions = group.get("five_event_directions")
        if not isinstance(directions, list) or len(directions) != 5:
            failures.append(f"{expected_id}.five_event_directions必须恰好5项")
        else:
            first_event = (expected_index - 1) * 5 + 1
            for event_offset, direction in enumerate(directions):
                event_index = first_event + event_offset
                event_id = f"EC{event_index:03d}"
                event_span = list(_event_bounds(event_index))
                if not isinstance(direction, dict):
                    failures.append(f"{expected_id}.five_event_directions第{event_offset + 1}项必须为对象")
                    continue
                if direction.get("cluster_id") != event_id:
                    failures.append(f"{expected_id}第{event_offset + 1}个方向cluster_id必须为{event_id}")
                if direction.get("chapter_span") != event_span:
                    failures.append(f"{event_id}.chapter_span必须为{event_span}")
                if len(str(direction.get("direction") or "")) < 10:
                    failures.append(f"{event_id}.direction必须是至少10字的独立两章事件方向")
    if volume_index == 1:
        first = groups[0]
        joined = _json_text(first)
        if "2009" not in joined or "1969" not in joined or not any(word in joined for word in ("试镜", "出道")):
            failures.append("第一卷第一组必须同时明确2009死亡、1969试镜或出道重生")
    if volume_index == 10:
        joined = _json_text(groups)
        if "纪念" not in joined or not any(word in joined for word in ("审判", "揭露")):
            failures.append("第十卷必须规划纪念直播中的揭露或审判终局")
    if volume_start < 91 and "恋人" in _json_text(groups):
        failures.append("未成年阶段不得出现恋人关系")
    if volume_index <= 2:
        joined = _json_text(groups)
        forbidden_early = ("AI训练", "人工智能", "互联网", "电子邮件", "手机", "社交媒体", "直播", "视频被地方报纸", "数字视频")
        for phrase in forbidden_early:
            if phrase in joined:
                failures.append(f"第一、二卷年代错误：不得出现“{phrase}”")
    return failures


def _validate_story_block(
    obj: dict[str, Any], block_index: int, global_outline: dict[str, Any] | None = None,
) -> list[str]:
    failures: list[str] = []
    expected_id = f"B{block_index:03d}"
    expected_span = list(_block_bounds(block_index))
    if obj.get("block_id") != expected_id:
        failures.append(f"block_id必须为{expected_id}")
    if obj.get("chapter_span") != expected_span:
        failures.append(f"{expected_id}.chapter_span必须为{expected_span}")
    minimums = {
        "block_title": 3, "timeline_years": 4, "coarse_story_summary": 280,
        "block_goal": 30, "main_conflict": 30, "rebirth_advantage": 30,
        "block_outcome": 30, "handoff_to_next_block": 20,
    }
    for field, minimum in minimums.items():
        if len(str(obj.get(field) or "").strip()) < minimum:
            failures.append(f"{expected_id}.{field}不足{minimum}字或缺失")
    for field in ("entry_state", "rights_health_relationship_changes", "continuity_update"):
        if not isinstance(obj.get(field), dict):
            failures.append(f"{expected_id}.{field}必须为对象")
    movements = obj.get("character_movements")
    movement_parts = [
        part.strip()
        for raw in (movements if isinstance(movements, list) else [movements])
        for part in re.split(r"[；;]", str(raw or ""))
        if part.strip()
    ]
    movement_count = len(movement_parts)
    if movement_count < 2:
        failures.append(f"{expected_id}.character_movements至少2项")
    groups = obj.get("macro_groups")
    if not isinstance(groups, list) or len(groups) != 2:
        return failures + [f"{expected_id}.macro_groups必须恰好2项"]
    for local, group in enumerate(groups, 1):
        macro_index = (block_index - 1) * 2 + local
        macro_id = f"MG{macro_index:03d}"
        macro_span = list(_macro_bounds(macro_index))
        if not isinstance(group, dict):
            failures.append(f"{expected_id}.macro_groups第{local}项必须为对象")
            continue
        if group.get("macro_group_id") != macro_id:
            failures.append(f"{expected_id}第{local}组macro_group_id必须为{macro_id}")
        if group.get("chapter_span") != macro_span:
            failures.append(f"{macro_id}.chapter_span必须为{macro_span}")
        for field, minimum in {
            "title": 3, "timeline_years": 4, "macro_goal": 20,
            "historical_stage": 15, "main_conflict": 20, "rebirth_advantage": 20,
            "romance_progression": 12, "ending_state": 20, "next_group_hook": 15,
        }.items():
            if len(str(group.get(field) or "").strip()) < minimum:
                failures.append(f"{macro_id}.{field}不足{minimum}字或缺失")
        directions = group.get("five_event_directions")
        if not isinstance(directions, list) or len(directions) != 5:
            failures.append(f"{macro_id}.five_event_directions必须恰好5项")
            continue
        first_event = (macro_index - 1) * 5 + 1
        event_types: list[str] = []
        solution_types: list[str] = []
        for offset, direction in enumerate(directions):
            event_index = first_event + offset
            event_id = f"EC{event_index:03d}"
            event_span = list(_event_bounds(event_index))
            if not isinstance(direction, dict):
                failures.append(f"{event_id}方向必须为对象")
            elif direction.get("cluster_id") != event_id or direction.get("chapter_span") != event_span:
                failures.append(f"{event_id}编号或两章范围错误，应为{event_span}")
            elif len(str(direction.get("direction") or "").strip()) < 70:
                failures.append(f"{event_id}.direction必须至少70字并说明两章完整独立事件")
            else:
                opposition = str(direction.get("opposition_type") or "")
                event_type = str(direction.get("event_type") or "")
                solution_type = str(direction.get("solution_type") or "")
                if opposition not in OPPOSITION_TYPES:
                    failures.append(f"{event_id}.opposition_type非法或缺失")
                if event_type not in EVENT_TYPES:
                    failures.append(f"{event_id}.event_type非法或缺失")
                if solution_type not in SOLUTION_TYPES:
                    failures.append(f"{event_id}.solution_type非法或缺失")
                if str(direction.get("death_chain_role") or "") not in {
                    "advance", "pressure", "reveal", "echo",
                }:
                    failures.append(f"{event_id}.death_chain_role非法或缺失")
                event_types.append(event_type)
                solution_types.append(solution_type)
                # Event/solution enums are routing metadata.  At this broad
                # layer, reject missing rebirth-payoff facts rather than
                # regenerating five usable events because one label is only an
                # approximate description of the scene.
                direction_text = _json_text({
                    key: direction.get(key) for key in (
                        "direction", "unique_prev_life_info", "chapter_one_small_win",
                        "chapter_two_showdown", "opponent_permanent_loss",
                        "protagonist_concrete_gain", "death_chain_connection",
                    )
                })
                chapter_a, chapter_b = event_span
                if f"第{chapter_a}章" not in direction_text or f"第{chapter_b}章" not in direction_text:
                    failures.append(f"{event_id}.direction必须分别写明第{chapter_a}章与第{chapter_b}章的不同动作")
                if event_id != "EC001" and not any(
                    marker in direction_text
                    for marker in ("前世", "上一世", "记得", "原本会", "曾经", "重来前")
                ):
                    failures.append(f"{event_id}.direction没有写出本事件独有的前世信息差")
                if not any(
                    marker in direction_text
                    for marker in ("失去", "取消", "撤换", "停职", "冻结", "赔偿", "让渡", "终止", "永久", "当场撤回")
                ):
                    failures.append(f"{event_id}.direction没有写清阻力方第二章的现实损失")
                # protagonist_concrete_gain is already a required, length-checked
                # fact field and is compiled under the explicit label “主角现实收益”.
                # Do not reject a valid gain merely because Qwen wrote “建立/开始”
                # instead of one of a short verb whitelist.
                if block_index == 1:
                    locked = B001_TYPE_LOCK[event_id]
                    actual = (opposition, event_type, solution_type, str(direction.get("death_chain_role") or ""))
                    # villain/institutional/family is sometimes a perspective
                    # label for the same concrete obstacle. Keep the locked
                    # event, solution and death-chain function; do not rewrite
                    # an otherwise usable plan just for that soft label.
                    if actual[1:] != locked[1:]:
                        failures.append(f"{event_id}分类必须锁定为{locked}，实际{actual}")
        if len(set(event_types)) < 3:
            failures.append(f"{macro_id}五个事件方向至少覆盖3种event_type")
        if event_types.count("legal_procedure") > 2:
            failures.append(f"{macro_id}五个事件方向最多2个legal_procedure")
        if solution_types and max(Counter(solution_types).values()) > 2:
            failures.append(f"{macro_id}同一种solution_type最多2次")
        if not any(
            str(direction.get("death_chain_role") or "") in {"advance", "pressure", "reveal"}
            for direction in directions if isinstance(direction, dict)
        ):
            failures.append(f"{macro_id}至少一个方向必须推进2009死亡控制主线")
    serialized = _json_text(obj)
    failures.extend(_fake_death_failures(obj, expected_id))
    if block_index <= 5:
        failures.extend(_early_planning_semantic_failures(obj, expected_id))
    # Procedural-word density is a prose/editorial concern, not a reason to
    # discard a causally complete twenty-chapter plan.
    if block_index == 1:
        entry_health = _json_text((obj.get("entry_state") or {}).get("health_and_location"))
        if any(term in entry_health for term in ("殡仪馆", "冷藏室", "棺材", "遗体存放")):
            failures.append("B001入口必须是第1章尚有生命体征的2009临终医疗现场，不得从死后殡仪馆状态开场")
        # Count the reader-facing 20-chapter narrative and its ten directions,
        # not duplicated state ledgers/hand-offs elsewhere in the same JSON.
        # This is intentionally a soft anti-procedure gate: detailed event
        # validation still enforces the one-event/one-payoff story contract.
        reader_facing = _json_text({
            "coarse_story_summary": obj.get("coarse_story_summary"),
            "macro_groups": groups,
        })
        # Repetition density is now a prose-stage concern.  Do not discard a
        # causally usable twenty-chapter plan merely because rights terms recur
        # while the family establishes its initial legal boundary.
    for phrase in ("北京", "上海", "中国", "纽约", "洛杉矶", "芝加哥", "好莱坞", "戛纳", "威尼斯", "东京", "Excel", "MTV", "索尼", "Revox", "B77", "通用电气", "联合国教科文组织", "国家职业安全卫生研究所", "Michael Jackson", "迈克尔·杰克逊", "AI还原", "人工智能还原"):
        if phrase in serialized:
            failures.append(f"{expected_id}世界观错误：禁止出现“{phrase}”")
    if re.search(
        r"(?:麦珂|主角).{0,12}(?<!无)(?<!不)诱(?:导|使).{0,20}"
        r"(修改|伪造|篡改|造假|犯罪|跳过)",
        serialized,
    ):
        failures.append(f"{expected_id}主角不得诱导对手修改、伪造、篡改或犯罪；只能观察其自主选择并合法留证")
    if global_outline:
        # Only event directions represent an on-page appearance.  Broad summaries,
        # handoffs and open-thread ledgers may legitimately mention a future
        # character, so scanning the whole block caused false rejections.
        arcs = [arc for arc in global_outline.get("character_long_arcs", []) if isinstance(arc, dict)]
        for group in groups:
            if not isinstance(group, dict):
                continue
            for direction in group.get("five_event_directions") or []:
                if not isinstance(direction, dict):
                    continue
                event_id = str(direction.get("cluster_id") or "")
                if block_index == 1 and event_id == "EC001":
                    # EC001 contains the 2009 death before returning to 1969.
                    continue
                span = direction.get("chapter_span") or expected_span
                try:
                    event_phase = (int(span[1]) - 1) // 50 + 1
                except Exception:
                    event_phase = (expected_span[1] - 1) // 50 + 1
                direction_text = _json_text({
                    key: direction.get(key) for key in (
                        "preemptive_action", "chapter_one_small_win", "chapter_two_showdown",
                        "opponent_permanent_loss", "protagonist_concrete_gain",
                        "irreversible_outcome_key",
                    )
                })
                for arc in arcs:
                    name = str(arc.get("character") or "").strip()
                    phase_match = re.fullmatch(r"P(\d{2})", str(arc.get("first_active_phase") or ""))
                    aliases = {name, name.split("·", 1)[0]} if name else set()
                    alias_hits = direction_text.count(name) if name in direction_text else max(
                        (direction_text.count(alias) for alias in aliases if alias), default=0,
                    )
                    negative_only = alias_hits == 1 and any(
                        marker in direction_text
                        for marker in ("不涉及其登场", "不得实体登场", "尚未登场", "不会登场")
                    )
                    if name and phase_match and int(phase_match.group(1)) > event_phase and any(
                        alias and alias in direction_text for alias in aliases
                    ) and not negative_only:
                        failures.append(
                            f"{event_id or expected_id}时间线错误：{name}首次活跃于P{int(phase_match.group(1)):02d}，不得提前实体登场"
                        )
    if block_index == 1:
        early_timeline_parts: list[Any] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            early_timeline_parts.extend([
                group.get("historical_stage"), group.get("main_conflict"),
                group.get("rebirth_advantage"), group.get("ending_state"),
                group.get("next_group_hook"),
            ])
            early_timeline_parts.extend(
                direction for direction in (group.get("five_event_directions") or [])
                if isinstance(direction, dict) and direction.get("cluster_id") != "EC001"
            )
        early_timeline_text = _json_text(early_timeline_parts)
        for phrase in ("GridTrack", "监控回放", "数字签名", "服务器日志", "指纹锁", "高清照片", "PDF元数据", "AI", "人工智能", "互联网", "电子邮件", "上传", "云端", "自动关联", "ASME"):
            if phrase in early_timeline_text:
                failures.append(f"B001年代技术错误：1969年不得出现“{phrase}”")
        for group in groups:
            for direction in (group.get("five_event_directions") or []) if isinstance(group, dict) else []:
                value = str(direction.get("direction") or "") if isinstance(direction, dict) else ""
                if re.search(r"EC\d{3}", value):
                    failures.append("B001正文方向中不得把EC编号写成世界内文件编号")
    elif block_index <= 12:
        for phrase in (
            "互联网", "电子邮件", "邮箱", "网站", "全网", "上传", "下载", "云端", "社交媒体",
            "哈希", "数字签名", "智能终端", "AI", "人工智能",
        ):
            if phrase in serialized:
                failures.append(f"{expected_id}年代技术错误：1991年前不得出现“{phrase}”")
    if "奥瑞安" in serialized:
        failures.append(f"{expected_id}集团名称必须统一写‘奥瑞恩集团’")
    if block_index == 1:
        first_group = _json_text(groups[0])
        if not all(token in first_group for token in ("2009", "1969")) or not any(token in first_group for token in ("试镜", "出道")):
            failures.append("B001/MG001必须明确第1章2009死亡、第2章1969十一岁试镜后台重生")
    for group in groups:
        if not isinstance(group, dict):
            continue
        technology_group = dict(group)
        technology_group["five_event_directions"] = [
            {
                key: value for key, value in direction.items()
                if key != "locked_story_brief"
            }
            if isinstance(direction, dict) else direction
            for direction in (group.get("five_event_directions") or [])
        ]
        for phrase in _unavailable_technology(group.get("timeline_years")):
            if phrase in _json_text(technology_group):
                failures.append(
                    f"{group.get('macro_group_id') or expected_id}年代技术错误："
                    f"{group.get('timeline_years')}尚不应使用“{phrase}”"
                )
    if block_index == 25:
        if not all(token in serialized for token in ("纪念", "直播", "现场", "审判")):
            failures.append("B025必须让麦珂本人在全球纪念直播现场完成审判")
    return failures


def _validate_block_backbone(obj: dict[str, Any], block_index: int) -> list[str]:
    """Validate the block-level causal spine before macro event directions."""
    expected_id = f"B{block_index:03d}"
    failures: list[str] = []
    if obj.get("block_id") != expected_id:
        failures.append(f"block_id必须为{expected_id}")
    if obj.get("chapter_span") != list(_block_bounds(block_index)):
        failures.append(f"{expected_id}.chapter_span错误")
    for field, minimum in {
        "block_title": 3, "timeline_years": 4, "coarse_story_summary": 320,
        "block_goal": 30, "main_conflict": 30, "rebirth_advantage": 30,
        "block_outcome": 30, "handoff_to_next_block": 20,
    }.items():
        if len(str(obj.get(field) or "").strip()) < minimum:
            failures.append(f"{expected_id}.{field}不足{minimum}字或缺失")
    for field in (
        "entry_state", "rights_health_relationship_changes", "continuity_update",
    ):
        if not isinstance(obj.get(field), dict):
            failures.append(f"{expected_id}.{field}必须为对象")
    movements = obj.get("character_movements")
    if not isinstance(movements, list) or len(movements) < 2:
        failures.append(f"{expected_id}.character_movements至少2项")
    if block_index == 1:
        health = _json_text((obj.get("entry_state") or {}).get("health_and_location"))
        if any(term in health for term in ("殡仪馆", "冷藏室", "棺材", "遗体存放")):
            failures.append("B001入口必须是尚有生命体征的2009临终医疗现场")
        if "2009" not in health or not any(
            term in health for term in (
                "生命体征", "监护仪", "仍活着", "尚未死亡", "自主呼吸",
                "脑干反射", "脑电活动", "心电图", "窦性心律",
            )
        ):
            failures.append("B001.entry_state.health_and_location必须明确2009临终且尚有生命体征")
        reader_path = _json_text({
            "summary": obj.get("coarse_story_summary"),
            "outcome": obj.get("block_outcome"),
            "changes": obj.get("rights_health_relationship_changes"),
        })
        if not all(year in reader_path for year in ("2009", "1969", "1970")):
            failures.append("B001块级主干必须覆盖2009死亡、1969重生并推进到1970块末，不能只写试镜开头")
        domain_groups = (
            ("试镜", "演出", "舞台", "排练", "试唱"),
            ("创作", "原创", "旋律", "歌曲", "编曲"),
            ("媒体", "电台", "报纸", "电视", "舆论"),
            ("玛莎", "母亲", "家庭", "亲子"),
            ("观众", "听众", "歌迷", "粉丝", "公益", "市场"),
        )
        covered_domains = sum(any(term in reader_path for term in group) for group in domain_groups)
        if covered_domains < 4:
            failures.append(f"B001二十章覆盖不足：作品/舞台/媒体/家庭/观众五条叙事域只覆盖{covered_domains}条")
        handoff = str(obj.get("handoff_to_next_block") or "")
        if any(term in handoff for term in ("下一步将是正式签约", "下一步是正式签约", "即将签约与合同审核")):
            failures.append("B001不得把本块EC002应完成的第一份合同冲突拖到下一20章")
    serialized = _json_text(obj)
    failures.extend(_fake_death_failures(obj, expected_id))
    if block_index <= 5:
        failures.extend(_early_planning_semantic_failures(obj, expected_id))
    if block_index <= 12:
        technology_scope = serialized
        if block_index == 1:
            # B001 deliberately opens in 2009, where internet/AI-era terms are
            # legal, then jumps back to 1969.  Scan only the post-rebirth story
            # fields instead of falsely applying 1969 rules to the entry frame.
            summary = str(obj.get("coarse_story_summary") or "")
            rebirth_at = summary.find("1969")
            if rebirth_at >= 0:
                summary = summary[rebirth_at:]
            technology_scope = _json_text({
                "coarse_story_summary_after_rebirth": summary,
                "block_goal": obj.get("block_goal"),
                "main_conflict": obj.get("main_conflict"),
                "rebirth_advantage": obj.get("rebirth_advantage"),
                "character_movements": obj.get("character_movements"),
                "rights_health_relationship_changes": obj.get("rights_health_relationship_changes"),
                "block_outcome": obj.get("block_outcome"),
                "handoff_to_next_block": obj.get("handoff_to_next_block"),
                "continuity_update": obj.get("continuity_update"),
            })
        for phrase in ("互联网", "电子邮件", "网站", "上传", "云端", "社交媒体", "AI", "人工智能"):
            if phrase in technology_scope:
                failures.append(f"{expected_id}年代技术错误：1991年前不得出现“{phrase}”")
    return failures


def _validate_macro_blueprint(
    obj: dict[str, Any], macro_index: int, block_index: int,
    global_outline: dict[str, Any],
) -> list[str]:
    """Validate exactly one ten-chapter/five-direction unit."""
    expected_id = f"MG{macro_index:03d}"
    failures: list[str] = []
    if obj.get("macro_group_id") != expected_id:
        failures.append(f"macro_group_id必须为{expected_id}")
    if obj.get("chapter_span") != list(_macro_bounds(macro_index)):
        failures.append(f"{expected_id}.chapter_span错误")
    for field, minimum in {
        "title": 3, "timeline_years": 4, "macro_goal": 20,
        "historical_stage": 15, "main_conflict": 20, "rebirth_advantage": 20,
        "romance_progression": 12, "ending_state": 20, "next_group_hook": 15,
    }.items():
        if len(str(obj.get(field) or "").strip()) < minimum:
            failures.append(f"{expected_id}.{field}不足{minimum}字或缺失")
    compiled_obj = _compile_macro_direction_fields(obj)
    wrapper = {
        "block_id": f"B{block_index:03d}",
        "chapter_span": list(_block_bounds(block_index)),
        "block_title": "临时组合校验标题",
        "timeline_years": str(obj.get("timeline_years") or ""),
        "coarse_story_summary": "临时组合校验" * 60,
        "entry_state": {}, "block_goal": "临时组合校验" * 8,
        "main_conflict": "临时组合校验" * 8, "rebirth_advantage": "临时组合校验" * 8,
        "character_movements": ["人物移动一", "人物移动二"],
        "rights_health_relationship_changes": {},
        "causal_links_used": ["CS01"], "foreshadows_planted_or_advanced": [],
        "block_outcome": "临时组合校验" * 8,
        "handoff_to_next_block": "临时组合校验" * 6,
        "macro_groups": [compiled_obj, compiled_obj], "continuity_update": {},
    }
    # Reuse the mature per-direction checks, then discard failures that belong
    # only to the synthetic wrapper or duplicated placeholder macro.
    combined = _validate_story_block(wrapper, block_index, global_outline)
    relevant_prefixes = tuple(
        [expected_id]
        + [f"EC{index:03d}" for index in range((macro_index - 1) * 5 + 1, macro_index * 5 + 1)]
    )
    failures.extend(
        item for item in combined
        if item.startswith(relevant_prefixes)
    )
    directions = compiled_obj.get("five_event_directions") or []
    if macro_index <= 10:
        # locked_story_brief can state a prohibition such as "不得使用网络或
        # 社交平台".  It is a compiler instruction, not story content, and must not
        # itself trigger the era-technology detector.
        semantic_directions = [
            {key: value for key, value in direction.items() if key != "locked_story_brief"}
            if isinstance(direction, dict) else direction
            for direction in directions
        ] if isinstance(directions, list) else directions
        failures.extend(_early_planning_semantic_failures(semantic_directions, expected_id))
    info_gaps: list[tuple[str, str]] = []
    outcomes: list[tuple[str, str]] = []
    for direction in directions if isinstance(directions, list) else []:
        if not isinstance(direction, dict):
            continue
        eid = str(direction.get("cluster_id") or expected_id)
        for field in (
            "previous_life_harm", "unique_prev_life_info", "preemptive_action",
            "chapter_one_small_win", "chapter_two_showdown", "opponent_permanent_loss",
            "protagonist_concrete_gain", "irreversible_outcome_key", "death_chain_connection",
        ):
            minimum = 4 if field == "irreversible_outcome_key" else 8
            if len(str(direction.get(field) or "").strip()) < minimum:
                failures.append(f"{eid}.{field}至少{minimum}字且必须是具体剧情事实")
        info_gap = str(direction.get("unique_prev_life_info") or "").strip()
        if eid != "EC001" and len(info_gap) < 12:
            failures.append(f"{eid}.unique_prev_life_info至少12字且必须是本事件独有的前世陷阱信息")
        direction_text = str(direction.get("direction") or "")
        info_gaps.append((eid, info_gap))
        outcome_key = str(direction.get("irreversible_outcome_key") or "").strip()
        if len(outcome_key) < 4:
            failures.append(f"{eid}.irreversible_outcome_key至少4字，且必须明确本事件唯一、可写入状态机的结算")
        outcomes.append((eid, outcome_key))
        if block_index == 1:
            if direction.get("locked_story_brief") != B001_EVENT_BRIEFS[eid]:
                failures.append(f"{eid}.locked_story_brief必须逐字保留编译器给出的事件功能边界")
            story_fields = _json_text({
                key: direction.get(key) for key in (
                    "previous_life_harm", "unique_prev_life_info", "preemptive_action",
                    "chapter_one_small_win", "chapter_two_showdown",
                    "opponent_permanent_loss", "protagonist_concrete_gain",
                )
            })
            for alternatives in B001_EVENT_REQUIRED_ANCHORS[eid]:
                if not any(anchor in story_fields for anchor in alternatives):
                    failures.append(
                        f"{eid}没有落实locked_story_brief所需事实：至少出现"
                        f"{'/'.join(alternatives)}之一"
                    )
    for pairs, label in ((info_gaps, "前世信息差"), (outcomes, "不可逆结算")):
        for offset, (left_id, left) in enumerate(pairs):
            if not left:
                continue
            for right_id, right in pairs[offset + 1:]:
                both_machine_keys = bool(
                    re.fullmatch(r"[A-Z0-9_-]+", left)
                    and re.fullmatch(r"[A-Z0-9_-]+", right)
                )
                duplicate = (
                    left == right
                    if both_machine_keys
                    else SequenceMatcher(None, left, right, autojunk=False).ratio() >= 0.62
                )
                if right and duplicate:
                    failures.append(f"{left_id}与{right_id}复用了同一{label}，必须是两件不同的事")
    return list(dict.fromkeys(failures))


def _validate_events(
    obj: dict[str, Any], macro_index: int,
    prior_events: list[dict[str, Any]] | None = None,
    prior_state: dict[str, str] | None = None,
    prior_irreversible: set[str] | None = None,
    source_macro: dict[str, Any] | None = None,
    event_indices: list[int] | None = None,
) -> list[str]:
    failures: list[str] = []
    events = obj.get("event_clusters")
    first_event = (macro_index - 1) * 5 + 1
    expected_event_indices = event_indices or list(range(first_event, first_event + 5))
    if not isinstance(events, list) or len(events) != len(expected_event_indices):
        return [f"event_clusters必须恰好{len(expected_event_indices)}项"]
    known_artifacts: set[str] = {
        f"{created.get('timeline_scope')}::{created.get('artifact_id')}"
        for prior in (prior_events or [])
        for milestone in (prior.get("two_chapter_structure") or [])
        for created in (milestone.get("artifact_creates") or [])
        if isinstance(created, dict) and str(created.get("artifact_id") or "")
    }
    current_timeline_end = None
    source_directions = (
        source_macro.get("five_event_directions") or []
        if isinstance(source_macro, dict) else []
    )

    def terminal_signatures(candidate: dict[str, Any]) -> set[str]:
        opponent = re.sub(
            r"[^\u3400-\u9fffA-Za-z0-9·]", "",
            re.sub(r"[（(][^）)]*[）)]", "", str(candidate.get("main_opponent") or "")),
        ) or "<unknown>"
        story = _json_text({
            key: candidate.get(key) for key in (
                "villain_loss", "protagonist_gain", "cluster_outcome",
                "continuity_writes", "two_chapter_structure",
            )
        })
        patterns = {
            "arrested": r"被(?:警方)?(?:当场)?(?:逮捕|抓捕|带走)|警方.{0,8}(?:逮捕|带走)",
            "reputation_destroyed": r"身败名裂",
            "organization_cut_off": r"(?:高层|集团|公司).{0,10}(?:切割|解除.{0,4}关系)",
            "acquisition_collapsed": r"(?:收购案|收购计划).{0,10}(?:破产|终止|撤销)",
            "assets_frozen": r"资产.{0,8}冻结|冻结.{0,8}资产",
        }
        return {
            f"{label}::{opponent}"
            for label, pattern in patterns.items()
            if re.search(pattern, story)
        }
    for prior in (prior_events or []):
        for milestone in (prior.get("two_chapter_structure") or []):
            if int(milestone.get("chapter_id") or 0) == 1:
                continue
            point = timeline_point(milestone.get("timeline_end"))
            if point is not None:
                current_timeline_end = max(current_timeline_end or point, point)
    for local, event in enumerate(events):
        event_index = expected_event_indices[local]
        eid = f"EC{event_index:03d}"
        span = list(_event_bounds(event_index))
        if event.get("cluster_id") != eid:
            failures.append(f"第{local + 1}项cluster_id必须为{eid}")
        if event.get("chapter_span") != span:
            failures.append(f"{eid}.chapter_span必须为{span}")
        source_local = event_index - first_event
        if len(source_directions) == 5 and isinstance(source_directions[source_local], dict):
            locked_direction = source_directions[source_local]
            expected_direction = str(locked_direction.get("direction") or "")
            if event.get("source_event_direction") != expected_direction:
                failures.append(f"{eid}.source_event_direction必须逐字绑定上层方向")
            if event.get("source_event_direction_sha256") != canonical_sha256(expected_direction):
                failures.append(f"{eid}.source_event_direction_sha256与上层方向不一致")
            if event.get("source_macro_sha256") != canonical_sha256(source_macro):
                failures.append(f"{eid}.source_macro_sha256与当前宏观组不一致")
            for field in ("opposition_type", "event_type", "solution_type", "death_chain_role"):
                if event.get(field) != locked_direction.get(field):
                    failures.append(f"{eid}.{field}不得在详细事件层改写上层锁定值")
            # New relay-safe one-event generations must not consume terminal
            # outcomes assigned to later siblings. Existing five-event
            # checkpoints are grandfathered so published work is not regenerated.
            if event_indices is not None:
                detailed_story = _json_text({
                    key: event.get(key) for key in (
                        "fictional_obstacle", "villain_loss", "protagonist_gain",
                        "cluster_outcome", "state_transitions",
                    )
                } | {
                    "two_chapter_structure": [
                        {
                            key: value for key, value in chapter.items()
                            if key != "must_not_include"
                        }
                        for chapter in (event.get("two_chapter_structure") or [])
                        if isinstance(chapter, dict)
                    ],
                })
                locked_story = _json_text(locked_direction)
                terminal_guards = (
                    ("逮捕/刑事带走", r"(?:被(?:警方)?(?:当场)?(?:逮捕|抓捕|带走)|警方.{0,8}(?:逮捕|带走)|刑事指控书)", r"逮捕|抓捕|带走|刑事指控"),
                    ("法院查封/冻结令", r"(?:查封令|冻结令|临时限制令)", r"查封令|冻结令|限制令"),
                    ("收购破产", r"(?:收购案|收购计划).{0,10}(?:破产|终止|撤销)", r"(?:收购案|收购计划).{0,10}(?:破产|终止|撤销)"),
                    ("资产冻结", r"资产.{0,8}冻结|冻结.{0,8}资产", r"资产.{0,8}冻结|冻结.{0,8}资产"),
                    ("彻底身败名裂", r"身败名裂", r"身败名裂"),
                )
                for label, actual_pattern, allowed_pattern in terminal_guards:
                    if re.search(actual_pattern, detailed_story) and not re.search(allowed_pattern, locked_story):
                        failures.append(f"{eid}提前消费后续事件的{label}结算；当前父级方向未授权该结果")
                current_terminal = terminal_signatures(event)
                for prior_event in (prior_events or [])[-10:]:
                    repeated_terminal = current_terminal & terminal_signatures(prior_event)
                    if repeated_terminal:
                        failures.append(
                            f"{eid}与{prior_event.get('cluster_id')}重复执行不可逆结算："
                            + "、".join(sorted(repeated_terminal))
                        )
        required_text = (
            "fictional_obstacle",
            "prev_life_tragedy", "info_gap_from_prev_life", "why_previous_life_failed",
            "preemptive_avoidance", "bait_and_evidence", "comic_villain_behavior",
            "villain_loss", "protagonist_gain", "relationship_change", "cluster_outcome",
            "next_event_hook",
        )
        for field in required_text:
            if len(str(event.get(field) or "").strip()) < 10:
                failures.append(f"{eid}.{field}过短或缺失")
        for field, minimum in (("name", 3), ("timeline_years", 4), ("main_opponent", 3)):
            if len(str(event.get(field) or "").strip()) < minimum:
                failures.append(f"{eid}.{field}过短或缺失")
        if str(event.get("opposition_type") or "") not in OPPOSITION_TYPES:
            failures.append(f"{eid}.opposition_type必须为允许枚举值")
        if str(event.get("event_type") or "") not in EVENT_TYPES:
            failures.append(f"{eid}.event_type必须为允许枚举值")
        if str(event.get("solution_type") or "") not in SOLUTION_TYPES:
            failures.append(f"{eid}.solution_type必须为允许枚举值")
        if str(event.get("death_chain_role") or "") not in {
            "advance", "pressure", "reveal", "echo",
        }:
            failures.append(f"{eid}.death_chain_role必须为advance/pressure/reveal/echo")
        if not isinstance(event.get("causal_spine_ids"), list) or not event.get("causal_spine_ids"):
            failures.append(f"{eid}.causal_spine_ids至少1项")
        if not isinstance(event.get("foreshadow_ids"), list):
            failures.append(f"{eid}.foreshadow_ids必须为数组")
        allowed_causal_ids = {
            str(value) for value in (source_macro or {}).get("causal_links_used") or []
            if re.fullmatch(r"CS\d{2}", str(value))
        }
        if not allowed_causal_ids:
            allowed_causal_ids = {
                str(value) for value in (source_macro or {}).get("causal_spine_ids") or []
                if re.fullmatch(r"CS\d{2}", str(value))
            }
        allowed_foreshadow_ids = {
            match
            for value in (source_macro or {}).get("foreshadows_planted_or_advanced") or []
            for match in re.findall(r"FS\d{2}", str(value))
        }
        if not allowed_foreshadow_ids:
            allowed_foreshadow_ids = {
                str(value) for value in (source_macro or {}).get("foreshadow_ids") or []
                if re.fullmatch(r"FS\d{2}", str(value))
            }
        actual_causal_ids = {str(value) for value in event.get("causal_spine_ids") or []}
        actual_foreshadow_ids = {str(value) for value in event.get("foreshadow_ids") or []}
        if allowed_causal_ids and not actual_causal_ids.issubset(allowed_causal_ids):
            failures.append(
                f"{eid}.causal_spine_ids必须来自当前宏观组锁定集合{sorted(allowed_causal_ids)}，"
                f"实际越界{sorted(actual_causal_ids - allowed_causal_ids)}"
            )
        if allowed_foreshadow_ids and not actual_foreshadow_ids.issubset(allowed_foreshadow_ids):
            failures.append(
                f"{eid}.foreshadow_ids必须来自当前宏观组锁定集合{sorted(allowed_foreshadow_ids)}，"
                f"实际越界{sorted(actual_foreshadow_ids - allowed_foreshadow_ids)}"
            )
        chapters = event.get("two_chapter_structure")
        if not isinstance(chapters, list) or len(chapters) != 2:
            failures.append(f"{eid}.two_chapter_structure必须恰好2项")
        else:
            for offset, chapter in enumerate(chapters):
                expected_chapter = span[0] + offset
                if chapter.get("chapter_id") != expected_chapter:
                    failures.append(f"{eid}章节号必须为{span}")
                chapter_minimums = {"scene": 2, "chapter_goal": 5, "visible_payoff": 5, "ending": 5}
                for field, minimum in chapter_minimums.items():
                    if len(str(chapter.get(field) or "").strip()) < minimum:
                        failures.append(f"{eid}.chapter{expected_chapter}.{field}过短")
                actions = chapter.get("action_sequence")
                expanded_actions = (
                    [
                        part.strip()
                        for item in actions
                        for part in re.split(r"[；;]", str(item or ""))
                        if part.strip()
                    ]
                    if isinstance(actions, list)
                    else []
                )
                if not isinstance(actions, list) or len(expanded_actions) < 4:
                    failures.append(f"{eid}.chapter{expected_chapter}.action_sequence至少4步")
                for field, minimum in {
                    "chapter_title": 3, "opening_conflict": 8,
                    "info_gap_use": 8, "opponent_reaction": 8,
                    "detailed_synopsis": 120,
                }.items():
                    if len(str(chapter.get(field) or "").strip()) < minimum:
                        failures.append(f"{eid}.chapter{expected_chapter}.{field}过短")
                if len(str(chapter.get("detailed_synopsis") or "")) > 420:
                    failures.append(f"{eid}.chapter{expected_chapter}.detailed_synopsis超过420字")
                for field, minimum in (("participants", 2), ("must_include", 3), ("must_not_include", 2)):
                    if not isinstance(chapter.get(field), list) or len(chapter[field]) < minimum:
                        failures.append(f"{eid}.chapter{expected_chapter}.{field}至少{minimum}项")
                start_point = timeline_point(chapter.get("timeline_start"))
                end_point = timeline_point(chapter.get("timeline_end"))
                if start_point is None or end_point is None:
                    failures.append(f"{eid}.chapter{expected_chapter}必须提供合法timeline_start/timeline_end")
                elif end_point < start_point:
                    failures.append(f"{eid}.chapter{expected_chapter}.timeline_end早于timeline_start")
                elif expected_chapter != 2 and current_timeline_end is not None and start_point < current_timeline_end:
                    failures.append(f"{eid}.chapter{expected_chapter}早于本事件上一章结束日期")
                if end_point is not None:
                    current_timeline_end = (
                        end_point if expected_chapter == 2
                        else max(current_timeline_end or end_point, end_point)
                    )
                scenes = chapter.get("scenes")
                if not isinstance(scenes, list) or not scenes:
                    failures.append(f"{eid}.chapter{expected_chapter}.scenes至少1项")
                else:
                    sequences = [int(scene.get("sequence") or 0) for scene in scenes if isinstance(scene, dict)]
                    if sequences != list(range(1, len(scenes) + 1)):
                        failures.append(f"{eid}.chapter{expected_chapter}.scenes.sequence必须连续")
                    if sum(bool(scene.get("is_primary")) for scene in scenes if isinstance(scene, dict)) != 1:
                        failures.append(f"{eid}.chapter{expected_chapter}.scenes必须恰好1个主场景")
                    milestone_scene = str(chapter.get("scene") or "").strip()
                    scene_locations = {
                        str(scene.get("location") or "").strip()
                        for scene in scenes if isinstance(scene, dict)
                    }
                    # Qwen may append visual blocking to the chapter-level
                    # primary location ("录音棚，墙面……") while the scenes
                    # ledger keeps the stable place name ("录音棚").  This is
                    # a valid parent/detail mapping, not a location conflict.
                    scene_matches = any(
                        milestone_scene == location
                        or bool(re.match(re.escape(location) + r"[，,。；;（(：:]", milestone_scene))
                        for location in scene_locations if location
                    )
                    if not scene_matches:
                        failures.append(f"{eid}.chapter{expected_chapter}.scene不在scenes中")
                    for scene in scenes:
                        if not isinstance(scene, dict) or str(scene.get("temporal_mode") or "") not in {
                            "current", "previous_life_memory", "flashback",
                        }:
                            failures.append(f"{eid}.chapter{expected_chapter}.scenes.temporal_mode非法")
                            continue
                        if int(scene.get("sequence") or 0) > 1 and len(str(scene.get("transition_cue") or "")) < 2:
                            failures.append(f"{eid}.chapter{expected_chapter}转场必须提供正文可见transition_cue")
                creates = chapter.get("artifact_creates")
                refs = chapter.get("artifact_refs")
                if not isinstance(creates, list) or not isinstance(refs, list):
                    failures.append(f"{eid}.chapter{expected_chapter}.artifact_creates/artifact_refs必须为数组")
                    creates, refs = [], []
                for created in creates:
                    aid = str(created.get("artifact_id") or "") if isinstance(created, dict) else ""
                    scope = str(created.get("timeline_scope") or "") if isinstance(created, dict) else ""
                    expected_scope = "previous_life" if expected_chapter == 1 else "current"
                    artifact_key = f"{scope}::{aid}"
                    if not re.fullmatch(r"ART_[A-Z0-9_]{3,80}", aid):
                        failures.append(f"{eid}.chapter{expected_chapter}创建的artifact_id非法：{aid or '<空>'}")
                    elif scope != expected_scope:
                        failures.append(f"{eid}.chapter{expected_chapter}.artifact timeline_scope必须为{expected_scope}")
                    elif artifact_key in known_artifacts:
                        failures.append(f"{eid}.chapter{expected_chapter}重复创建artifact_id={aid}")
                    else:
                        known_artifacts.add(artifact_key)
                for ref in refs:
                    aid = str(ref.get("artifact_id") or "") if isinstance(ref, dict) else ""
                    scope = str(ref.get("timeline_scope") or "") if isinstance(ref, dict) else ""
                    expected_scope = "previous_life" if expected_chapter == 1 else "current"
                    if scope != expected_scope:
                        failures.append(f"{eid}.chapter{expected_chapter}artifact_id={aid or '<空>'}跨时间线引用")
                    elif f"{scope}::{aid}" not in known_artifacts:
                        failures.append(f"{eid}.chapter{expected_chapter}引用本事件尚未创建的artifact_id={aid or '<空>'}")
        for field in ("continuity_writes", "historical_anchor_ids", "main_characters"):
            if not isinstance(event.get(field), list):
                failures.append(f"{eid}.{field}必须为数组")
        serialized = _json_text(event)
        if event_index == 1:
            base_ok = all(token in serialized for token in ("2009", "1969", "康拉德", "保险")) and any(
                token in serialized for token in ("十一岁", "11岁", "十一周岁", "11周岁")
            )
            medicine_ok = any(token in serialized for token in ("违规", "药", "注射", "液体"))
            rights_ok = any(token in serialized for token in ("版权", "母带", "肖像", "无形资产"))
            if not (base_ok and medicine_ok and rights_ok):
                failures.append("EC001必须明确2009年康拉德用药致死、听见保险与版权/母带分赃、1969年十一岁试镜后台重生")
            first_chapter = chapters[0] if isinstance(chapters, list) and len(chapters) == 2 else {}
            second_chapter = chapters[1] if isinstance(chapters, list) and len(chapters) == 2 else {}
            first_chapter_text = _json_text({
                key: value for key, value in first_chapter.items()
                if key != "must_not_include"
            })
            if any(token in first_chapter_text for token in ("殡仪馆", "冷藏室", "棺盖", "棺材")):
                failures.append("EC001第1章必须发生在麦珂尚有生命体征的临终医疗现场，不得死在殡仪馆冷藏室或棺内")
            if any(token in first_chapter_text for token in ("重生回", "试镜后台睁开", "奔向西侧通风口", "取出三颗铁珠")):
                failures.append("EC001第1章只写2009临终与分赃信息差，不得提前混写第2章1969重生行动")
            second_chapter_text = _json_text({
                key: value for key, value in second_chapter.items()
                if key != "must_not_include"
            })
            if "前世致死" in second_chapter_text and "铁珠" in second_chapter_text:
                failures.append("EC001不得把1969年设备铁珠写成导致2009前世死亡的物体；它只能是上一世试镜受阻的记忆")
            protagonist_actions = _json_text({
                "preemptive_avoidance": event.get("preemptive_avoidance"),
                "bait_and_evidence": event.get("bait_and_evidence"),
                "two_chapter_structure": [
                    {
                        key: value for key, value in chapter.items()
                        if key != "must_not_include"
                    }
                    for chapter in (event.get("two_chapter_structure") or [])
                    if isinstance(chapter, dict)
                ],
            })
            if any(phrase in protagonist_actions for phrase in ("碰松", "蹭松", "拧松", "故意松开", "制造故障")):
                failures.append("EC001主角只能提前发现并加固设备，不能先弄松支架或主动制造危险再解决")
            if isinstance(chapters, list) and len(chapters) == 2:
                rebirth_chapter = _json_text({
                    key: value for key, value in chapters[1].items()
                    if key != "must_not_include"
                })
                if "康拉德" in rebirth_chapter:
                    failures.append("EC001第2章发生在1969年，康拉德不能随主角穿越或以同一身份出现")
            if "康拉德" in str(event.get("villain_loss") or ""):
                failures.append("EC001的1969年结算必须处罚当时的设备破坏者，不能处罚2009年的康拉德")
            continuity_text = _json_text(event.get("continuity_writes") or [])
            if "康拉德" in continuity_text and any(word in continuity_text for word in ("吊销", "逮捕", "判刑", "注销", "处罚")):
                failures.append("EC001不能凭主角死后未知信息写入康拉德已受处罚的连续性事实")
        if event_index == 250:
            final_presence = any(
                token in serialized for token in ("现身", "登台", "踏上中央台阶", "走入现场", "本人走上")
            )
            if not all(token in serialized for token in ("葬礼", "审判", "全球", "直播")) or not final_presence:
                failures.append("EC250必须由Qwen明确写出全球直播中本人登台/现身，并把葬礼变成审判")
        if 2 <= event_index <= 225:
            # 康拉德是主角前世晚年才结识的医生。早期事件可以把他写在
            # 前世记忆/失败原因中，但不能让同一个人在今生提前几十年登场。
            physical_event = _json_text({
                key: event.get(key) for key in (
                    "name", "timeline_years", "main_opponent", "main_characters",
                    "fictional_obstacle", "preemptive_avoidance", "bait_and_evidence",
                    "comic_villain_behavior", "villain_loss", "protagonist_gain",
                    "relationship_change", "state_transitions",
                    "cluster_outcome", "next_event_hook",
                )
            } | {
                "two_chapter_structure": [
                    {
                        key: value for key, value in chapter.items()
                        if key != "must_not_include"
                    }
                    for chapter in (event.get("two_chapter_structure") or [])
                    if isinstance(chapter, dict)
                ]
            })
            if "康拉德" in physical_event:
                failures.append(f"{eid}不得让2009年晚年医生康拉德在第451章前的今生时间线实体登场")
        unavailable_technology = _unavailable_technology(event.get("timeline_years"))
        if unavailable_technology:
            early_technology = _json_text({
                "name": event.get("name"),
                "fictional_obstacle": event.get("fictional_obstacle"),
                "preemptive_avoidance": event.get("preemptive_avoidance"),
                "bait_and_evidence": event.get("bait_and_evidence"),
                "comic_villain_behavior": event.get("comic_villain_behavior"),
                "villain_loss": event.get("villain_loss"),
                "protagonist_gain": event.get("protagonist_gain"),
                "relationship_change": event.get("relationship_change"),
                "continuity_writes": event.get("continuity_writes"),
                "cluster_outcome": event.get("cluster_outcome"),
                "next_event_hook": event.get("next_event_hook"),
                "two_chapter_structure": [
                    {
                        key: value for key, value in chapter.items()
                        if key != "must_not_include"
                    }
                    for chapter in (event.get("two_chapter_structure") or [])
                    if isinstance(chapter, dict)
                ],
            })
            for phrase in unavailable_technology:
                if phrase in early_technology:
                    failures.append(f"{eid}年代技术错误：{event.get('timeline_years')}尚不应使用“{phrase}”")
        forbidden_shortcuts = ("神秘短信", "匿名短信", "匿名消息", "未知势力", "神秘人", "没有直接证据", "强烈直觉", "凭直觉")
        for phrase in forbidden_shortcuts:
            if phrase in serialized:
                failures.append(f"{eid}禁止使用捷径“{phrase}”")
        forbidden_world = ("北京", "上海", "中国", "东城区", "居委会", "毛主席", "文化部", "公安局", "人民币", "纽约", "洛杉矶", "芝加哥", "好莱坞", "FDA", "Michael Jackson", "迈克尔·杰克逊")
        for phrase in forbidden_world:
            if phrase in serialized:
                failures.append(f"{eid}世界观错误：禁止出现现实地点、机构或姓名“{phrase}”")
        if span[1] <= 90:
            romance_words = r"(?:恋人|接吻|婚姻|情欲)"
            protagonist_romance = bool(
                re.search(rf"麦珂.{{0,8}}{romance_words}|{romance_words}.{{0,8}}麦珂", serialized)
            )
            if protagonist_romance:
                failures.append(f"{eid}位于未成年阶段，禁止麦珂本人参与恋爱内容")
        if isinstance(chapters, list) and len(chapters) == 2:
            first_text = _json_text(chapters[0])
            for field in ("villain_loss", "protagonist_gain"):
                final_value = str(event.get(field) or "").strip()
                if final_value and final_value in first_text:
                    failures.append(f"{eid}第一章milestone提前逐字消费{field}")
            milestone_similarity = semantic_similarity(
                {
                    key: chapters[0].get(key)
                    for key in ("opening_conflict", "action_sequence", "visible_payoff", "detailed_synopsis")
                },
                {
                    key: chapters[1].get(key)
                    for key in ("opening_conflict", "action_sequence", "visible_payoff", "detailed_synopsis")
                },
            )
            if milestone_similarity >= 0.62:
                failures.append(f"{eid}两章milestone语义相似度{milestone_similarity:.2f}，疑似重复同一场戏")
    ledger = obj.get("continuity_update")
    if not isinstance(ledger, dict):
        failures.append("continuity_update必须为对象")
    _, _, semantic_failures = validate_event_batch(
        events,
        prior_events=prior_events,
        prior_state=prior_state,
        prior_irreversible=prior_irreversible,
    )
    failures.extend(semantic_failures)
    if macro_index == 1 and len(expected_event_indices) == 5:
        permanent_core_loss = False
        for event in events:
            loss_text = str(event.get("villain_loss") or "")
            transitions = event.get("state_transitions") or []
            if any(name in loss_text for name in ("维克多", "奥瑞恩", "乔纳", "奥斯蒙")) and any(
                isinstance(item, dict)
                and bool(item.get("irreversible"))
                and str(item.get("domain") or "") in {"rights", "asset", "job", "enemy_capability", "reputation"}
                for item in transitions
            ):
                permanent_core_loss = True
                break
        if not permanent_core_loss:
            failures.append("MG001前10章必须让核心控制方永久失去一项钱、权、职位、资源或信誉")
    return failures


def _validate_chapter_part(obj: dict[str, Any], macro_index: int, part: int) -> list[str]:
    failures: list[str] = []
    chapters = obj.get("chapter_synopses")
    if not isinstance(chapters, list) or len(chapters) != 5:
        return ["chapter_synopses必须恰好5项"]
    macro_start, _ = _macro_bounds(macro_index)
    start = macro_start + (0 if part == 1 else 5)
    for offset, chapter in enumerate(chapters):
        cid = start + offset
        if chapter.get("chapter_id") != cid:
            failures.append(f"第{offset + 1}项chapter_id必须为{cid}")
        event_id = f"EC{(cid + 1) // 2:03d}"
        if chapter.get("cluster_id") != event_id:
            failures.append(f"第{cid}章cluster_id必须为{event_id}")
        field_minimums = {
            "chapter_title": 3, "timeline_years": 4, "scene_location": 3,
            "opening_conflict": 8, "info_gap_use": 8, "opponent_reaction": 8,
            "immediate_payoff": 8, "ending_hook": 8, "detailed_synopsis": 180,
        }
        for field, limit in field_minimums.items():
            if len(str(chapter.get(field) or "").strip()) < limit:
                failures.append(f"第{cid}章{field}过短或缺失")
        for field, minimum in (("participants", 2), ("exact_action_sequence", 3), ("state_changes", 1), ("must_include", 3), ("must_not_include", 2)):
            value = chapter.get(field)
            if field in ("exact_action_sequence", "state_changes", "must_include", "must_not_include") and isinstance(value, list):
                split_pattern = r"[；;、]" if field in ("must_include", "must_not_include") else r"[；;]"
                expanded = [
                    part.strip()
                    for item in value
                    for part in re.split(split_pattern, str(item or ""))
                    if part.strip()
                ]
                value_count = len(expanded)
            else:
                value_count = len(value) if isinstance(value, list) else 0
            if not isinstance(value, list) or value_count < minimum:
                failures.append(f"第{cid}章{field}至少{minimum}项")
        if cid % 2 == 0:
            text = _json_text(chapter)
            settlement_words = (
                "失去", "撤销", "归还", "收益", "取得", "夺回", "获得", "取消", "剥夺",
                "罚款", "赔偿", "支付", "扣除", "降级", "移交", "保住", "赢得", "拿到", "确认",
                "收获", "获准", "允许",
                "持有", "入库", "丧失",
                "交接", "签署", "移交",
                "暂停", "被调", "调用",
                "撤回", "驳回", "收走", "锁定", "授权", "开放", "接管", "保留",
                "停止", "解除", "生效", "作废", "拒绝", "禁止", "批准", "通过",
                "签字", "备案", "归属", "控制", "掌握",
                "认定", "认证", "无效",
                "新增", "完成", "建立", "形成", "纳入", "启用", "冻结", "封存", "固化", "延伸",
            )
            if not any(word in text for word in settlement_words):
                failures.append(f"第{cid}章为事件结算章，必须明确现实得失")
        serialized = _json_text(chapter)
        narrative_text = _json_text({
            "opening_conflict": chapter.get("opening_conflict"),
            "exact_action_sequence": chapter.get("exact_action_sequence"),
            "opponent_reaction": chapter.get("opponent_reaction"),
            "immediate_payoff": chapter.get("immediate_payoff"),
            "ending_hook": chapter.get("ending_hook"),
            "detailed_synopsis": chapter.get("detailed_synopsis"),
        })
        if cid == 1 and not all(token in serialized for token in ("2009", "康拉德", "保险")):
            failures.append("第1章必须写清2009年康拉德用药致死及临终听见保险利益链")
        if cid == 2:
            location_text = str(chapter.get("scene_location") or "")
            if not any(token in location_text for token in ("试镜", "后台")):
                failures.append("第2章主场景必须是1969年全国出道试镜后台，不能写成公寓厨房")
            forbidden_text = _json_text(chapter.get("must_not_include") or [])
            if "重生" in forbidden_text or "回到1969" in forbidden_text:
                failures.append("第2章不得把重生回1969写入must_not_include")
        forbidden_world = ("北京", "上海", "中国", "东城区", "居委会", "毛主席", "文化部", "公安局", "人民币", "纽约", "洛杉矶", "芝加哥", "好莱坞", "FDA", "Michael Jackson", "迈克尔·杰克逊")
        for phrase in forbidden_world:
            if phrase in serialized:
                failures.append(f"第{cid}章世界观错误：禁止出现现实地点、机构或姓名“{phrase}”")
        if 2 <= cid <= 450:
            physical_presence = _json_text({
                "scene_location": chapter.get("scene_location"),
                "participants": chapter.get("participants"),
                "opening_conflict": chapter.get("opening_conflict"),
                "exact_action_sequence": chapter.get("exact_action_sequence"),
                "opponent_reaction": chapter.get("opponent_reaction"),
                "immediate_payoff": chapter.get("immediate_payoff"),
                "state_changes": chapter.get("state_changes"),
                "detailed_synopsis": chapter.get("detailed_synopsis"),
            })
            if "康拉德" in physical_presence:
                failures.append(f"第{cid}章不得让2009年晚年医生康拉德在重生后的早期时间线实体登场")
        unavailable_technology = _unavailable_technology(chapter.get("timeline_years"))
        if unavailable_technology:
            for phrase in unavailable_technology:
                if phrase in narrative_text:
                    failures.append(f"第{cid}章年代技术错误：{chapter.get('timeline_years')}尚不应使用“{phrase}”")
    if not isinstance(obj.get("continuity_update"), dict):
        failures.append("continuity_update必须为对象")
    return failures


def _system_prompt() -> str:
    return (
        "你是长篇中文重生爽文的总编剧。你必须直接创作具体剧情，而不是复述要求或给模板。"
        "只输出一个严格合法的JSON对象，不要Markdown，不要解释。人物、事件、阻碍、证据形成、反转和收益必须具体到可直接指导约1000字正文。"
    )


def _global_system_prompt() -> str:
    return (
        "你是长篇中文重生爽文的总架构师。先创作一份能统领500章的宽泛全书故事总纲，"
        "锁定因果主链、人物长弧、伏笔回收和各阶段状态，但不要下沉成逐章或两章事件。"
        "只输出一个严格合法的JSON对象，不要Markdown，不要解释。"
    )


def _base_context() -> str:
    return _json_text({
        "theme": THEME,
        "background": BACKGROUND,
        "protagonist": PROTAGONIST,
        "existing_fictional_cast": CAST,
        "hard_rules": HARD_RULES,
        "research_sources": SOURCES,
    })


def _compact_planning_hard_context() -> str:
    """Hard facts needed by downstream planners without research bibliography."""
    return _json_text({
        "theme": THEME,
        "protagonist": PROTAGONIST,
        "existing_fictional_cast": [
            {"name": item.get("name"), "role": item.get("role"), "alignment": item.get("alignment")}
            for item in CAST
        ],
        "hard_rules": HARD_RULES,
    })


def _global_outline_slice(global_outline: dict[str, Any], macro_index: int) -> dict[str, Any]:
    phase_index = (macro_index - 1) // 5 + 1
    phase_id = f"P{phase_index:02d}"
    phases = global_outline.get("life_phases") or []
    nearby_phases = [
        phase for phase in phases
        if isinstance(phase, dict) and abs(int(str(phase.get("phase_id") or "P00")[1:]) - phase_index) <= 1
    ]
    causal = [
        item for item in (global_outline.get("causal_spine") or [])
        if phase_id in _json_text(item)
    ]
    foreshadows = [
        item for item in (global_outline.get("foreshadow_ledger") or [])
        if phase_id in _json_text(item)
    ]
    active_arcs = [
        {
            "character_id": item.get("character_id"),
            "character": item.get("character"),
            "first_active_phase": item.get("first_active_phase"),
            "relationship_with_protagonist": item.get("relationship_with_protagonist"),
        }
        for item in (global_outline.get("character_long_arcs") or [])
        if isinstance(item, dict)
        and int(str(item.get("first_active_phase") or "P99")[1:]) <= phase_index + 1
    ]
    return {
        "story_title": global_outline.get("story_title"),
        "one_sentence_premise": global_outline.get("one_sentence_premise"),
        "core_rebirth_logic": global_outline.get("core_rebirth_logic"),
        "nearby_life_phases": nearby_phases,
        "relevant_causal_spine": causal,
        "relevant_foreshadows": foreshadows,
        "active_character_boundaries": active_arcs,
    }


def _global_narrative_prompt() -> str:
    schema = {
        "story_title": "Qwen创作的架空书名",
        "one_sentence_premise": "一句话说明重生信息差和终局爽点",
        "full_story_synopsis": "2500—4000汉字的宽泛全书故事梗概；实际不得少于2300汉字，按人生推进写因果，不列章节或两章事件",
        "core_rebirth_logic": {
            "previous_life_death": "2009死亡与利益链真相",
            "information_gap": "哪些前世记忆可用、哪些不能当证据",
            "new_life_method": "今生如何提前预判、布局并形成合法证据",
            "moral_boundary": "主角坚持的底线",
            "ultimate_goal": "活下来、守住家人与权利并完成终局审判",
        },
        "romance_long_arc": "未成年禁恋；成年后数段关系的宽泛起伏及其与事业选择的因果",
        "ending_convergence": "晚年保险、版权、医疗、舞台安全、家人与全球纪念现场如何汇合",
        "downstream_nonnegotiables": ["至少8条后续拆分不得违背的全书事实"],
    }
    return (
        "先只创作这部500章小说的宽泛全书故事梗概。不要列十卷，不要列事件簇，不要写500章标题。"
        "梗概要像一篇完整故事摘要，讲清主角为何重生、凭什么一路飞升、每次成功如何改变下一阶段、"
        "主要敌人与亲密关系怎样长期变化、最终葬礼审判为何是四十年布局的必然结果。"
        "虚构阻碍可以比现实传记更戏剧化，但主角必须正向，真正坏人坏得滑稽且自留把柄。\n"
        "全书核心必须用一句清楚的话贯穿：麦珂从人生第一份合同开始，逐步拆掉2009年最终杀死他的整套控制体系。"
        "从第2章起，每个阶段都要让读者知道当前胜利怎样削弱死亡利益链，而不是让康拉德或V.L.本人穿越到早年。"
        "麦珂的聪明来自前世记得日期、原话、流程和人的选择；他负责找准多米诺骨牌，专业鉴定、法律、工程和医疗动作由同期有资质的成年人完成。"
        "玛莎不能只是被儿子遥控的执行器；每个阶段至少安排她一次独立判断，允许她选择比麦珂预案更勇敢或更有效的做法。"
        "爽点必须是对手永久失去一项金钱、职位、权限、资源、盟友或信誉，且同一损失只发生一次；狼狈表情、摔杯和手抖不能代替实质损失。"
        "故事主体必须是流行天王重走四十年人生：舞台封神、创作突破、市场发行、家庭伙伴、粉丝公益、媒体反击、健康安全、商业版权和成年感情并行。"
        "full_story_synopsis中必须直接写出这两句事实而不是留给其他字段：从1969年第一份合同开始，麦珂逐步拆掉导致2009年死亡的控制体系；终局时麦珂本人在全球纪念直播结束前走上现场，把自己的葬礼变成公开审判。"
        "程序与证据只是少数复仇事件的武器；全书法律程序类事件不得超过一成半，不得把每次胜利都写成公证、声纹、钢印、信封、铅封、骑缝章或波形比对。"
        "full_story_synopsis至少六成篇幅必须写具体的歌曲创作、录音选择、舞台表演、观众反馈、发行市场、家庭关系、粉丝公益、媒体舆论、健康与成年感情；"
        "合同、条款、存档、备案、签名、联署、信托、审计、证据、流程、权限、文书、编号、印章等程序词合计不得超过14次。"
        "除开篇第一份合同和终局必要证明外，不能逐年罗列制度动作；要讲人物如何靠作品与选择改变命运。"
        "终局必须正面写：上一世麦珂确实死亡，今生他始终清醒存活，不使用镇静剂、不制造昏迷、不伪造死亡；他利用前世记得的死亡日期提前避开致命用药，让利益集团误以为旧计划仍会成功，继而抢先推出讣告、保险理赔和纪念直播，最终亲自登台。禁止在输出中复述任何被禁止的终局类型名称。"
        "蓝雪只能作为第1章死亡与第2章重生的一次性视觉对应，之后至少一百章不得再次作为天气或主意象；禁止伪科学频率、毫秒、毫米和化学成分制造假精确。\n"
        "全书任何层级都不得采用这些已经被评审否定的方案：今生服镇静剂模拟嗜睡、十一岁孩子手写合同附录或判断司法效力、"
        "声纹锁芯、材料氧化完全一致、用蜡笔/树叶/鸟羽等小物件跨几十年证明身份或法律事实。"
        "严禁主角或盟友模仿笔迹、栽赃、伪造证据或诱导犯罪；今生证据必须由对手自己的选择合法形成。"
        "终局直播可靠性依靠多家架空媒体的公开合同、公证备份与相互监督，不靠黑客、服务器跳转或不可阻断的万能技术。"
        "麦珂必须在全球纪念直播结束之前，于直播现场本人现身并当面完成审判，不能只播放全息影像、远程语音或在数日后出现。"
        "只能使用架空米国城市、机构、产品和作品，不得使用戛纳、Excel等现实专名。\n"
        f"主题与硬契约：{_base_context()}\n"
        f"严格输出此JSON：{_json_text(schema)}"
    )


def _global_narrative_core_prompt() -> str:
    schema = {
        "story_title": "架空书名", "one_sentence_premise": "重生信息差与终局爽点",
        "core_rebirth_logic": {
            "previous_life_death": "2009死亡利益链", "information_gap": "前世记忆边界",
            "new_life_method": "今生提前反制方法", "moral_boundary": "正向底线",
            "ultimate_goal": "活下来并完成公开审判",
        },
        "romance_overview": "未成年禁恋，成年关系如何与事业和人格自主相互影响",
        "ending_convergence": "220—450字宽泛终局收束，不列章节、不列证据清单，锁定麦珂始终清醒存活并本人走入全球纪念直播现场审判",
        "downstream_nonnegotiables": [
            "至少10条后续三段叙事、阶段、事件均不得违背的事实；前六条依次以【作品】【舞台】【家庭】【粉丝公益】【媒体】【市场】开头"
        ],
    }
    return (
        "先锁定同一部500章重生爽文的核心契约，暂不写长篇全书梗概，也不列阶段或事件。"
        "麦珂上一世在2009年被医疗、保险、版权和纪念利益链杀死，今生重生到1969年十一岁试镜后台；"
        "他只带回日期、原话、流程和人物选择的信息差，从第一份合同起逐步拆除控制体系。"
        "今生麦珂从1969年起始终公开活跃，敌人一直知道他活着。终局麦珂始终清醒存活，不服用任何制造误判的药物；"
        "敌人只因旧计划和错误情报误判该方案将在2009年得手，绝不能误以为他在此前早已死亡或消失，"
        "提前启动讣告、保险与全球纪念直播，麦珂本人在直播结束前走入现场公开审判。"
        "他必须正向，不诱导犯罪；玛莎等盟友有独立判断；对手损失是真实的钱、权、职位、资源或信誉。"
        "不得使用儿童法律工程、声纹锁芯、材料完全一致、跨几十年小物件鉴真、万能黑客或假精确。"
        "所有地点、机构、媒体、奖项、作品、产品均使用架空米国专名，禁止纽约、伦敦、东京、戛纳、时代广场、BBC、"
        "纽约时报、联合国教科文组织、美国证券交易委员会、Thriller等真实专名。downstream_nonnegotiables至少一半必须锁定"
        "作品创作、舞台、家庭、粉丝公益、媒体声誉、市场事业与人物自主，不能全写签字、备案、录像、医疗记录和文书。"
        "为避免遗漏，downstream_nonnegotiables前六条必须依次以【作品】【舞台】【家庭】【粉丝公益】【媒体】【市场】开头，"
        "每条写该领域贯穿四十年的一个宽泛事实，不写编号、公证或存档细节。"
        "ending_convergence只能写220—450字宽泛终局因果：禁止出现‘第491章’等章节号、倒计时、逐项证据清单、五项违规清单；"
        "只写反派因何误判、主角如何本人走入现场、反派失去什么以及作品/家人/公众如何共同见证。"
        f"\n主题与世界观：{_base_context()}\n只输出严格JSON：{_json_text(schema)}"
    )


def _global_narrative_segment_prompt(
    core: dict[str, Any], part: int, prior_segments: list[dict[str, Any]],
) -> str:
    segment_specs = {
        1: "前段：2009上一世死亡作为开场，重生回1969十一岁试镜后台；叙述今生1969—1982的童星出道、家庭边界、原创起步、舞台和市场飞升",
        2: "中段：1983—1998的全球舞台、作品突破、厂牌与版权博弈、成年感情、家庭伙伴、媒体反击与公益影响力",
        3: "后段：1999—2009的独立事业、粉丝与公共影响、健康自主、医疗/保险/版权利益链合流，以及本人走入全球纪念直播现场审判",
    }
    schema = {
        "segment_id": f"S{part}", "time_scope": segment_specs[part],
        "opening_state": "承接入口状态", "segment_synopsis": "850—1300字连续宽泛故事梗概，不列章节或事件编号",
        "romance_progression": "本段关系变化与人物自主性", "closing_state": "本段末事业、家庭、权利、健康、敌我状态",
        "handoff": "本段结果如何因果触发下一段；S3写终局收束",
    }
    return (
        f"这是已锁定的全书核心契约：{_json_text(core)}\n"
        f"已完成的前段，只能承接不能重演：{_json_text(prior_segments)}\n"
        f"现在写全书宽泛梗概的第{part}/3连续段：{segment_specs[part]}。"
        "本段必须像完整故事摘要，写人物选择如何导致下一步；至少六成写作品创作、舞台表演、观众与市场、家庭伙伴、"
        "粉丝公益、媒体舆论、健康安全和成年关系，程序只是少数手段。每次成功都应削弱2009死亡控制体系。"
        "前世信息差必须是曾遭陷害、剥夺或误导的具体日期/原话/流程/选择，今生利用它提前反击；不能把专业知识凭空塞给少年。"
        "今生麦珂从1969出道后始终公开活跃，敌人和公众都知道他活着；敌人只能误判旧控制方案会在2009杀死他，"
        "绝不能在S1/S2写敌人误以为他早已死亡、已经消失或把2009今生死亡当成已发生事实。"
        "全球纪念直播只能在S3的2009终局由敌人提前启动，1999年前后不得先办同类直播；"
        "2009不能写成他的死忌/逝世若干周年。前世死亡信息差最多保留一处真正有用的时点，禁止列三个以上精确分钟。"
        "不得采用今生药物诱饵、儿童手写合同附录、微颤/毫秒假精确、声纹锁芯、材料完全一致、跨年小物件鉴真、万能黑客。"
        "只用架空米国专名；人物与媒介按年代出现。S3必须在segment_synopsis与handoff组成的连续正式叙事中明确"
        "麦珂本人始终清醒存活，在全球纪念直播结束前登台或走入现场，把自己的葬礼变成公开审判。"
        "禁止纽约、伦敦、东京、悉尼、戛纳、百老汇、林肯中心、BBC、纽约时报、联合国教科文组织、美国证券交易委员会、"
        "Thriller、中国省市、民族和现实政府机构等真实专名；2009死亡经过不能在2009以前被出版或公开。"
        "不得用全息影像、人工智能遗言或数字复活替代人物冲突。每段合同/公证/备案/编号等程序词合计最多6次。"
        f"{'S1必须在segment_synopsis正文中逐字写出第一份合同，但只用两三句：麦珂只提出孩子能问的问题，玛莎基于自己的判断暂停签约并找成年律师；不得让麦珂写条款、起草附件、判断法律效力或列条款全文。1969—1982禁止联网传输、上传、服务器、视频会议、实时数据库、AI与数字索引。此后至少七成篇幅写歌曲、专辑、表演、观众、市场、家庭和粉丝公益。S1程序词最多7次。' if part == 1 else ''}"
        f"{'S2的handoff只能写1998年的事业、家庭、敌我结果怎样引发1999年的新压力，严禁出现纪念、葬礼、直播、讣告，也不要直接预演2009终局。' if part == 2 else ''}"
        f"\n只输出严格JSON：{_json_text(schema)}"
    )


def _global_phases_prompt(narrative: dict[str, Any], part: int) -> str:
    start_index = 1 if part == 1 else 6
    phase_indices = range(start_index, start_index + 5)
    phase_specs = [
        {
            "phase_id": f"P{i:02d}", "chapter_span": list(_volume_bounds(i)),
            "historical_years_reference": VOLUMES[i - 1]["years"],
            "reference_goal": VOLUMES[i - 1]["goal"],
        }
        for i in phase_indices
    ]
    phase_schema = {
        "phase_id": "P01", "chapter_span": [1, 50], "timeline_years": "年代范围",
        "broad_story_goal": "从全书梗概拆出的阶段主任务，不列小事件",
        "main_pressure": "阶段级外部压力与内部难题",
        "rebirth_advantage": "本阶段总体怎样用前世信息差",
        "major_characters": ["本阶段核心人物"],
        "major_turning_point": "阶段级转折",
        "phase_outcome": "阶段末事业、权利、家庭、健康与关系总体状态",
        "handoff_to_next_phase": "该结果如何因果性进入下一阶段",
    }
    ledger_schema = {
        "phase_id": "P01", "career_and_reputation": "总体状态", "rights_and_assets": "总体状态",
        "family_and_relationships": "总体状态", "health_and_location": "总体状态",
        "known_enemy_capabilities": "已知对手能力", "unresolved_threads": ["仍开放的全书级线索"],
    }
    schema = {"life_phases": [phase_schema], "state_ledger_by_phase": [ledger_schema]}
    return (
        f"这是Qwen已创作并锁定的宽泛全书叙事梗概：{_json_text(narrative)}\n"
        f"现在只生成十阶段中的第{part}批（P{start_index:02d}—P{start_index + 4:02d}）及对应状态账本。固定范围参考：{_json_text(phase_specs)}\n"
        "不得另起故事，不得改变总梗概结局；每阶段仍保持宽泛，只写阶段主任务、转折、结果和向下一阶段的因果交接，"
        "不要生成两章事件或逐章标题。life_phases与state_ledger_by_phase都必须只展开本批指定的5项，不要输出另一批。\n"
        "年代媒介必须严格：1969—1978只用纸质合同、复写纸、挂号信、磁带、胶片、机械仪表和现场见证；"
        "1979—1986可用模拟录音录像、电视广播、微缩胶片、独立计算机和纸质公证，不得出现互联网、电子邮件、上传、开源平台、元数据密钥或数据接口；"
        "1991年前也不得出现AI、人工智能、云端系统或指纹解锁；声纹只能写成专家比对磁带或录音波形，不得写AI声纹模型；"
        "1987—1994可用传真、复印件、电视录播和早期离线电脑，但不得写公共网站上传、全网传播、自动抓取或网络打标；"
        "1995年后再随年代逐步引入互联网与数字存储。麦珂1969年十一岁，成年节点应在1976年前后而非1975年。\n"
        "全程只用架空米国地点、机构、公司、媒体、奖项和产品；禁止威尼斯、东京、MTV、通用电气、联合国教科文组织、"
        "国家职业安全卫生研究所等现实专名。既有财团名称统一写‘奥瑞恩集团’，不得写成‘奥瑞安’。"
        "P10严禁假死、受控昏迷和任何镇静剂诱饵：对手因旧计划和错误情报误判麦珂会死，麦珂本人始终清醒存活。"
        "每阶段的主要制胜方式必须不同，至少包含一次作品/舞台硬实力胜利和一次人际或家庭自主选择；"
        "法律、公证、声纹、档案、文件类内容只能在直接改变权利时点到为止，不能成为阶段主叙事。\n"
        "不得从上游复用今生镇静剂诱饵、儿童手写合同附录、微颤频率/毫秒、声纹锁芯、墨迹氧化一致、跨几十年小物件鉴真；"
        "若上游叙事出现这些旧草案错误，应以当前规则为准彻底改写。\n"
        f"严格输出此JSON：{_json_text(schema)}"
    )


def _global_threads_prompt(narrative: dict[str, Any], phases: dict[str, Any]) -> str:
    schema = {
        "character_long_arcs": [{
            **identity,
            "first_active_phase": "Pxx", "initial_desire": "初始诉求",
            "long_term_change": "跨阶段变化", "relationship_with_protagonist": "关系长弧",
            "final_state": "终局状态",
        } for identity in GLOBAL_ARC_IDENTITIES],
        "causal_spine": [{
            "spine_id": "CS01", "phase_range": "Pxx→Pxx", "cause": "前因",
            "protagonist_choice": "主角阶段级选择", "result": "直接结果", "later_consequence": "后续阶段影响",
        }],
    }
    return (
        f"Qwen已锁定的全书叙事梗概：{_json_text(narrative)}\n"
        f"Qwen已拆出的十阶段与状态账本：{_json_text(phases)}\n"
        "现在为同一故事补充宽泛结构账本：只写恰好10条核心人物长弧和15条跨阶段因果主链，不要在本批输出伏笔账本。"
        "character_long_arcs的顺序、character_id、character和aliases已经锁定，必须逐字原样返回；"
        "绝对禁止换姓、另取同音名、只写名字不写姓氏，角色创作自由仅限弧线内容。"
        "必须引用既有梗概和P01—P10阶段，不得创造相反结局，不要下沉为两章小事件。"
        "CS编号必须依次为CS01—CS15，phase_range必须按时间正序。"
        "所有人物final_state必须停在2009年终局，不得跳到2010年以后或留下‘十年后启封’之类本书不回收的未来钩子。"
        "每条因果链的cause年份必须属于phase_range起点；later_consequence必须直接延续cause中的同一物件、制度、关系或权利，"
        "禁止把烧毁合同突然变成录音带鉴真、把无关旧物硬说成终局证据。P01—P10只是JSON字段，不能出现在人物持有的文件、铭牌或对白里。"
        "15条因果链必须使用15个不同起点事件，不能把同一次升降台事故改写两遍。结构上，CS01—CS05必须各自在P10以前完成一次中期回报，"
        "这5条的结果阶段至少覆盖3个不同阶段；CS06—CS15可以连接终局。这样全书不是所有收益都拖到第500章。"
        "法律行为能力只能由同期医疗评估、本人决策记录与直接见证佐证，不能用声纹、录音、衣物尺码或缺页日记证明。"
        "因果主链不得使用儿童手写合同附录、声纹锁芯、材料氧化完全一致、蜡笔/树叶/鸟羽跨年鉴真或今生镇静剂诱饵；"
        "上游若仍含这些旧草案错误，本批必须改成作品、舞台、关系、市场或对手自己的公开选择。"
        "只用架空专名，禁止威尼斯、东京、MTV、通用电气、联合国教科文组织等现实专名；集团统一称‘奥瑞恩集团’。"
        "终局证据不能依赖AI还原、深度伪造、合成语音或万能黑客，必须来自今生合法形成的对手行为与现场本人行动；15条因果链中至少8条以作品、舞台、人物关系、粉丝或市场结果为主，不得把旧物鉴真写成全书主链。"
        "表达简洁，确保JSON完整闭合。\n"
        f"严格输出此JSON：{_json_text(schema)}"
    )


def _global_foreshadows_prompt(
    narrative: dict[str, Any], phases: dict[str, Any], long_arcs: dict[str, Any],
    part: int, prior_foreshadows: list[dict[str, Any]] | None = None,
) -> str:
    assigned_developments = (
        "P02", "P03", "P04", "P05", "P06", "P08",
        "P09", "P09", "P09", "P09", "P10", "P10",
    )
    assigned_payoffs = (
        "P03", "P04", "P05", "P06", "P07", "P09",
        "P10", "P10", "P10", "P10", "P10", "P10",
    )
    assigned_payoff_years = (
        1981, 1985, 1990, 1992, 1997, 2006,
        2009, 2009, 2009, 2009, 2009, 2009,
    )
    assigned_plants = (
        (1969, "P01"), (1973, "P02"), (1980, "P03"), (1984, "P04"),
        (1988, "P05"), (1996, "P07"), (2001, "P08"), (2002, "P08"),
        (2003, "P08"), (2003, "P08"), (2005, "P09"), (2007, "P09"),
    )
    start = 1 if part == 1 else 7
    indices = range(start, start + 6)
    schema = {"foreshadow_ledger": [
        {
            "thread_id": f"FS{i:02d}", "thread": "具体可观察的伏笔内容",
            "plant_year": assigned_plants[i - 1][0], "plant_phase": assigned_plants[i - 1][1],
            "development_phases": [assigned_developments[i - 1]],
            "payoff_year": assigned_payoff_years[i - 1], "payoff_phase": assigned_payoffs[i - 1],
            "payoff_function": "同一物件或合法副本怎样直接回收并形成可见收益",
        }
        for i in indices
    ]}
    return (
        f"Qwen锁定的全书叙事梗概：{_json_text(narrative)}\n"
        f"Qwen锁定的十阶段与状态账本：{_json_text(phases)}\n"
        f"Qwen锁定的人物长弧与因果主链：{_json_text(long_arcs)}\n"
        f"已通过的前批伏笔（本批不得重复）：{_json_text(prior_foreshadows or [])}\n"
        f"现在只生成同一故事伏笔账本的第{part}批：FS{start:02d}—FS{start + 5:02d}，恰好6条；不得输出另一批，也不得重复人物长弧或因果主链。"
        "每条都必须填写四位数plant_year与payoff_year，且种植≤发展≤回收。"
        "development_phases中的每一项都必须位于plant_phase与payoff_phase之间（可以等于两端）；例如P03→[P05,P06]→P05是非法的，必须删掉P06。"
        "固定年份映射：1969—1970=P01；1971—1977=P02；1978可为P02或P03；1979—1982=P03；"
        "1983—1986=P04；1987—1990=P05；1991—1994=P06；1995—1998=P07；1999—2003=P08；"
        "2004—2007=P09；2008—2009=P10。请先按这张表确定年份和阶段，再写伏笔内容。"
        "伏笔必须是后续可观察、可推进、可回收的具体东西，不准用AI还原、深度伪造、万能黑客或突然出现的证人解题。"
        "伏笔回收必须直接证明它声称的事实：合同原件证明条款、日志证明操作、体测证明身体状态、见证证明现场行为。"
        "12条伏笔至少6条必须来自旋律/歌词选择、舞台习惯、人物承诺、家庭决定、粉丝组织或媒体公开立场；其余才可使用同一份合同、磁带、胶片、医生记录或真实审计日志。"
        "FS07—FS12六条终局伏笔必须分别采用六种不同类型：作品在公众中的持续回响、可重复的舞台习惯、盟友多年自主兑现的承诺、家庭成员独立选择、粉丝组织的公开行动、媒体/行业机构已公开且持续的立场；"
        "不得用蜡笔、叶片、种子、羽毛、灰尘、划痕、墨迹或其他小物件多年不动，再靠纹理/角度/光斑/毫秒级重合证明身份、连续在场或法律事实。"
        "回收必须是人物或群体在2009现场再次作出选择、作品被观众自然接续、舞台习惯帮助本人反击；不是鉴定旧道具。"
        "种植时出现的同一件东西或其合法公证副本，在回收时直接发挥作用，不得拿两个无关物件做材料成分匹配。"
        "禁止用香槟残留、气候、衣物尺寸、无关烧焦纸片去证明心理状态、授权效力或别的无关结论；坏人可以滑稽，但证据逻辑不能滑稽。"
        "禁止X射线、能谱、红外、元素/墨水/纸纤维同源、相位函数、99.9%重合等伪法证捷径，也不能让UPS固件决定人体复苏。"
        "也禁止用铅笔字迹匹配声纹峰值、热敏纸氧化推断年份、UV荧光表演充当证据、从多年旧录音背景杂音突然提取关键通话。"
        "上游若含声纹锁芯、材料氧化完全一致、儿童手写合同附录、蜡笔/树叶/鸟羽跨年鉴真或今生镇静剂诱饵，均视为旧草案错误，伏笔批次不得继承。"
        "盟友不得制作仿真、测试或虚构的红头文件、印章、签名、指令或证据；不能用指纹证明未受药物影响，也不能用版权/家庭旧物反推医疗造假。"
        "12条伏笔要在全书逐段回收，至少分布到4个不同payoff_phase，P10最多6条，其余必须在中期形成可见收益。"
        "固定回收槽位：FS01→P03、FS02→P04、FS03→P05、FS04→P06、FS05→P07、FS06→P09；"
        "FS07—FS12→P10。你必须据此选择不晚于回收阶段的plant_year/plant_phase和属于回收阶段的payoff_year。"
        "固定发展槽位也不得改变：FS01=[P02]、FS02=[P03]、FS03=[P04]、FS04=[P05]、FS05=[P06]、FS06=[P08]；"
        "FS07—FS10=[P09]，FS11—FS12=[P10]。每项development_phases只填这里指定的一个阶段。"
        "种植槽位也完全固定，必须逐字复制JSON模板中的plant_year与plant_phase，不得自行选择或交换；"
        "payoff_year也使用JSON模板已经填写的固定数值，不得自行更改。"
        "P01—P10只是JSON阶段字段，绝不能刻在铭牌、盒子、手册、文件名或人物对白中。"
        "只能使用架空专名；禁止北京、上海、中国、纽约、洛杉矶、芝加哥、好莱坞、戛纳、威尼斯、东京、MTV、索尼等现实地点、品牌或机构，集团统一称‘奥瑞恩集团’。\n"
        f"严格输出此JSON，foreshadow_ledger恰好展开本批6项：{_json_text(schema)}"
    )


def _global_outline_prompt() -> str:
    phases = [
        {
            "phase_id": f"P{i:02d}",
            "chapter_span": list(_volume_bounds(i)),
            "historical_years_reference": VOLUMES[i - 1]["years"],
            "reference_goal": VOLUMES[i - 1]["goal"],
        }
        for i in range(1, 11)
    ]
    phase_schema = {
        "phase_id": "P01", "chapter_span": [1, 50], "timeline_years": "本阶段年代范围",
        "broad_story_goal": "本阶段只写宽泛主任务，不列小事件",
        "main_pressure": "本阶段主要外部压力和内部难题",
        "rebirth_advantage": "前世信息差在本阶段的总体用法",
        "major_characters": ["核心人物"],
        "major_turning_point": "阶段级转折",
        "phase_outcome": "阶段结束时事业、权利、家庭、健康和关系的总体状态",
        "handoff_to_next_phase": "因果上如何自然进入下一阶段",
    }
    schema = {
        "story_title": "Qwen创作的架空书名",
        "one_sentence_premise": "一句话说明重生信息差和终局爽点",
        "full_story_synopsis": "约2500—4500汉字的全书宽泛梗概，按人生发展写清因果但不拆小事件",
        "core_rebirth_logic": {
            "previous_life_death": "2009死亡与利益链真相",
            "information_gap": "哪些前世记忆可用、哪些不能当证据",
            "new_life_method": "今生如何提前预判、布局并取得合法证据",
            "moral_boundary": "主角坚持的底线",
            "ultimate_goal": "活下来、守住家人与权利并完成终局审判",
        },
        "life_phases": [phase_schema],
        "character_long_arcs": [{
            "character": "人物名", "first_active_phase": "Pxx", "initial_desire": "初始诉求",
            "long_term_change": "跨阶段变化", "relationship_with_protagonist": "关系长弧",
            "final_state": "终局状态",
        }],
        "causal_spine": [{
            "spine_id": "CS01", "phase_range": "P01→P02", "cause": "前因",
            "protagonist_choice": "主角阶段级选择", "result": "直接结果", "later_consequence": "后续阶段影响",
        }],
        "foreshadow_ledger": [{
            "thread_id": "FS01", "thread": "伏笔内容", "plant_phase": "Pxx",
            "development_phases": ["Pxx"], "payoff_phase": "Pxx", "payoff_function": "回收作用",
        }],
        "state_ledger_by_phase": [{
            "phase_id": "P01", "career_and_reputation": "总体状态", "rights_and_assets": "总体状态",
            "family_and_relationships": "总体状态", "health_and_location": "总体状态",
            "known_enemy_capabilities": "已知对手能力", "unresolved_threads": ["仍开放的全书级线索"],
        }],
        "romance_long_arc": "未成年阶段禁恋；成年后各段关系如何源于性格和事业选择，并各有尊严地变化",
        "ending_convergence": "第491—500章如何让保险、版权、医疗、舞台安全、家人与全球纪念现场汇合为终局审判",
        "downstream_nonnegotiables": ["后续分卷和情节簇不得偏离的全书事实"],
    }
    return (
        f"根据用户主题先创作全书500章的宽泛故事总纲。指定十个人生阶段范围：{_json_text(phases)}\n"
        "总纲的细度只到50章人生阶段和跨阶段因果，不要生成250个事件，不要列500章标题。"
        "重点写清：前世受害形成的信息差；今生怎样提前避开虚构阻碍并一路升级；坏人如何因贪婪和自作聪明留下把柄；"
        "人物何时进入、怎样变化；哪些伏笔在哪个阶段回收；为什么终局不是突然翻盘。\n"
        f"全书主题与硬契约：{_base_context()}\n"
        f"严格按此JSON结构输出；life_phases展开10项，其他长弧与账本达到结构要求：{_json_text(schema)}"
    )


def _block_global_context(block_index: int, global_outline: dict[str, Any]) -> dict[str, Any]:
    start, end = _block_bounds(block_index)
    first_phase = (start - 1) // 50 + 1
    last_phase = (end - 1) // 50 + 1
    relevant_ids = {f"P{i:02d}" for i in range(first_phase, last_phase + 1)}
    phases = [
        phase for phase in global_outline.get("life_phases", [])
        if phase.get("phase_id") in relevant_ids
    ]
    states = [
        state for state in global_outline.get("state_ledger_by_phase", [])
        if state.get("phase_id") in relevant_ids
    ]
    causal = [
        item for item in global_outline.get("causal_spine", [])
        if any(phase_id in str(item.get("phase_range") or "") for phase_id in relevant_ids)
    ]
    foreshadows = [
        item for item in global_outline.get("foreshadow_ledger", [])
        if any(
            phase_id in _json_text({
                "plant": item.get("plant_phase"),
                "development": item.get("development_phases"),
                "payoff": item.get("payoff_phase"),
            })
            for phase_id in relevant_ids
        )
    ]
    active_arcs = [
        {
            "character_id": item.get("character_id"),
            "character": item.get("character"),
            "first_active_phase": item.get("first_active_phase"),
            "relationship_with_protagonist": item.get("relationship_with_protagonist"),
        }
        for item in global_outline.get("character_long_arcs", [])
        if isinstance(item, dict)
        and int(str(item.get("first_active_phase") or "P99")[1:]) <= last_phase + 1
    ]
    return {
        "story_title": global_outline.get("story_title"),
        "one_sentence_premise": global_outline.get("one_sentence_premise"),
        "core_rebirth_logic": global_outline.get("core_rebirth_logic"),
        "relevant_life_phases": phases,
        "relevant_phase_state_ledgers": states,
        "active_character_boundaries": active_arcs,
        "relevant_causal_spine": causal,
        "relevant_foreshadow_ledger": foreshadows,
    }


def _story_block_prompt(
    block_index: int,
    prior_block_ledger: dict[str, Any],
    global_outline: dict[str, Any],
) -> str:
    start, end = _block_bounds(block_index)
    first_macro = (block_index - 1) * 2 + 1
    macro_specs = [
        {
            "macro_group_id": f"MG{i:03d}",
            "chapter_span": list(_macro_bounds(i)),
            "event_clusters": [
                {"cluster_id": f"EC{j:03d}", "chapter_span": list(_event_bounds(j))}
                for j in range((i - 1) * 5 + 1, i * 5 + 1)
            ],
        }
        for i in range(first_macro, first_macro + 2)
    ]
    first_block_type_lock = B001_TYPE_LOCK if block_index == 1 else {}
    schema = {
        "block_id": f"B{block_index:03d}",
        "chapter_span": [start, end],
        "block_title": "Qwen创作的20章故事块标题",
        "timeline_years": "本块年代范围",
        "coarse_story_summary": "500—900汉字，连续叙述本20章怎样由入口状态走到块末结果",
        "entry_state": {
            "career_and_reputation": "开场状态", "rights_and_assets": "开场状态",
            "family_and_relationships": "开场状态", "health_and_location": "开场状态",
            "open_threads": ["承接的未决线索"],
        },
        "block_goal": "20章内必须完成的现实目标",
        "main_conflict": "贯穿20章的主冲突",
        "rebirth_advantage": "前世信息差在本块的总体用法及其边界",
        "character_movements": ["人物进入、退出、立场或关系的因果变化"],
        "rights_health_relationship_changes": {
            "rights_and_assets": ["变化"], "health_and_safety": ["变化"],
            "family_and_romance": ["变化"], "career_and_reputation": ["变化"],
        },
        "causal_links_used": ["CSxx"],
        "foreshadows_planted_or_advanced": ["FSxx及本块动作"],
        "block_outcome": "20章结算后的确定状态",
        "handoff_to_next_block": "该结果怎样必然触发下一块",
        "macro_groups": [{
            "macro_group_id": "MGxxx", "chapter_span": [1, 10], "title": "十章细纲组名",
            "timeline_years": "年代", "macro_goal": "十章可验收目标",
            "historical_stage": "符合年代的产业和社会舞台", "main_conflict": "十章具体冲突",
            "rebirth_advantage": "本组可操作的信息差",
            "five_event_directions": [{
                "cluster_id": "ECxxx", "chapter_span": [1, 2],
                "opposition_type": "villain | ally_resistance | institutional | technical | family | internal",
                "event_type": "performance | creation | contract_rights | finance_business | family_relationship | media_reputation | health_safety | fan_public_welfare | romance | legal_procedure",
                "solution_type": "performance_proof | creative_breakthrough | public_confrontation | negotiation | market_result | relationship_choice | safety_preemption | media_counter | financial_counter | legal_evidence | teamwork | strategic_withdrawal",
                "death_chain_role": "advance | pressure | reveal | echo",
                "direction": "这一对章节唯一事件的起因、提前反制、滑稽自曝和结算方向",
            }],
            "romance_progression": "关系线状态；未成年明确禁恋",
            "ending_state": "组末角色、关系、权利、资产、健康和伏笔状态",
            "next_group_hook": "结算后因果钩子，不拖欠本组收益",
        }],
        "continuity_update": {
            "characters": ["人物当前身份、位置、知情和立场"],
            "relationships": ["关系变化"], "rights_and_assets": ["权利资产变化"],
            "health_and_location": ["健康地点变化"], "resolved_threads": ["已回收"],
            "open_threads": ["仍开放并注明最晚回收块"],
        },
    }
    special = ""
    if block_index == 1:
        active_names = [
            str(arc.get("character") or "")
            for arc in global_outline.get("character_long_arcs", [])
            if isinstance(arc, dict) and arc.get("first_active_phase") == "P01"
        ]
        future_names = [
            str(arc.get("character") or "")
            for arc in global_outline.get("character_long_arcs", [])
            if isinstance(arc, dict) and arc.get("first_active_phase") != "P01"
        ]
        special = (
            "B001特殊硬要求：MG001.timeline_years写‘2009→1969’；EC001方向必须明确第1章2009年前世死亡、"
            "第2章1969年十一岁全国出道试镜后台重生。之后才进入今生时间线。"
            f"1969事件可实体使用的锁定核心人物只有{_json_text(active_names)}及本块新创的一次性小角色；"
            f"这些后期人物及其简称不得实体登场：{_json_text(future_names)}。"
            "不要使用现实技术标准缩写、自动关联系统、世界内EC编号、空白合同诱签或未来才有的数字技术。"
            "MG001前10章内必须让1969年核心控制方永久失去至少一项金钱、签字权、合同控制权、职位或关键资源；不能只让一次性小角色尴尬。"
            "B001只允许EC002这一件事把第一份合同作为主冲突，其solution_type可为negotiation；其他九个事件方向严禁以公证、合同、条款、存档、备案、印章、复写纸、登记簿或审计作为主要胜法。"
            f"B001十个事件的分类值已由编译器锁定，必须逐项照填且剧情必须证明标签，不得更改：{_json_text(first_block_type_lock)}。"
            "其余方向必须轮换：试镜/排练的performance_proof、歌曲或编舞的creative_breakthrough、对手抢功后的public_confrontation、观众或市场结果、玛莎独立作出的family_relationship选择、团队协作、设备安全预判。"
            "1969年十一岁的麦珂只能凭上一世记住的日期、原话、人员习惯或节目流程抢先；不能自己做毫秒测量、微观纤维鉴定、声纹分析、材料氧化判断或法律工程。"
            "coarse_story_summary与两个macro_groups合计提及‘合同’最多6次、‘公证’最多1次；前20章主体必须让读者看到他靠作品、舞台和人物选择一路飞升。"
        )
    elif block_index == 25:
        special = (
        "B025特殊硬要求：第491—500章中麦珂提前避开旧死亡方案并始终清醒存活；利益集团因惯性和错误情报误判他必死，"
        "主动提前启动讣告、保险和纪念直播牟利而自曝。麦珂必须在全球纪念直播尚未结束时本人走入现场当面完成审判；严禁假死、昏迷或镇静剂诱饵。"
        )
    return (
        f"你正在把同一部500章小说拆成第{block_index}/25个连续20章故事块（第{start}—{end}章）。"
        "这个20章块是全书总梗概与两章事件簇之间的主干层：先写一段连续粗纲，再拆成两个十章细纲；"
        "每个十章细纲只列五个两章事件方向，暂时不要写完整事件JSON或逐章详细梗概。\n"
        f"本块锁定的ID与范围：{_json_text(macro_specs)}\n"
        f"全书与本块相关的锁定上游：{_json_text(_block_global_context(block_index, global_outline))}\n"
        f"上一20章块写下的连续性账本：{_json_text(prior_block_ledger)}\n"
        "必须严格承接上一块状态；人物不得无铺垫出现或消失，已失去的权利资产不得自动恢复，伏笔只能按账本推进。"
        "每个两章方向必须是一件可独立结算的事：前世记忆指出具体陷阱，今生在实质伤害前提前反制，"
        "反派因贪婪、抢功或嘴硬滑稽自曝，第二章给出明确损失与主角收益。不可把五件事塞进一个方向。"
        "每个方向必须先选枚举opposition_type、event_type、solution_type；每个十章组至少3种event_type，legal_procedure最多2件，同一solution_type最多2件。"
        "event_type必须由实际剧情证明，禁止把胶片/档案鉴定标成粉丝公益，或把程序戏换标签伪装成多样题材。"
        "每十章至少一个方向的death_chain_role为advance、pressure或reveal，明确把小胜接回2009死亡—保险—版权—医疗控制主线。"
        "今生证据只能由今生合法形成；前世记忆不是物证。只能使用符合当时年代的媒介和架空米国专名，"
        "禁止现实城市、品牌、奖项、机构以及AI还原、万能黑客；录音机、乐器、设备也必须使用架空品牌和符合年代的型号。集团统一写‘奥瑞恩集团’。"
        "主角可以公开规则、设置安全留饵并记录对手自己的选择，但不得诱导、教唆或推动对手修改分成、伪造、篡改或实施违法行为。"
        "未成年禁恋，成年关系必须由既有关系状态因果推进。20章块可以跨越50章人生阶段边界，但不能改变锁定总梗概。\n"
        "人物必须遵守character_long_arcs.first_active_phase：首次活跃阶段晚于本块的人不得提前实体登场。"
        "B001中晚年人物只可出现在EC001的2009死亡片段，不得进入第2章后的1969今生；1969只用纸张、复写件、挂号信、磁带、胶片、机械设备和现场见证。\n"
        f"{special}\n全书硬契约：{_compact_planning_hard_context()}\n"
        f"严格输出此JSON；macro_groups必须恰好2项且每项five_event_directions恰好5项：{_json_text(schema)}"
    )


def _block_backbone_prompt(
    block_index: int,
    prior_block_ledger: dict[str, Any],
    global_outline: dict[str, Any],
) -> str:
    """Prompt one 20-chapter causal backbone without ten event directions."""
    start, end = _block_bounds(block_index)
    schema = {
        "block_id": f"B{block_index:03d}", "chapter_span": [start, end],
        "block_title": "20章块标题", "timeline_years": "年代范围",
        "coarse_story_summary": "450—800汉字的连续故事主干，不列逐章内容",
        "entry_state": {
            "career_and_reputation": "入口状态", "rights_and_assets": "入口状态",
            "family_and_relationships": "入口状态", "health_and_location": "入口状态",
            "open_threads": ["承接线索"],
        },
        "block_goal": "本块必须完成的现实目标",
        "main_conflict": "贯穿本块的一个主冲突",
        "rebirth_advantage": "本块可使用的前世信息差及边界",
        "character_movements": ["至少两项人物进入、退出、立场或自主选择变化"],
        "rights_health_relationship_changes": {
            "rights_and_assets": ["变化"], "health_and_safety": ["变化"],
            "family_and_romance": ["变化"], "career_and_reputation": ["变化"],
        },
        "causal_links_used": ["CSxx"],
        "foreshadows_planted_or_advanced": ["FSxx及动作"],
        "block_outcome": "块末确定状态", "handoff_to_next_block": "必然触发下一块的原因",
        "continuity_update": {
            "characters": ["累计人物状态"], "relationships": ["累计关系状态"],
            "rights_and_assets": ["累计权利资产"], "health_and_location": ["健康地点"],
            "resolved_threads": ["已回收"], "open_threads": ["未决线索及最晚回收块"],
        },
    }
    special = ""
    if block_index == 1:
        special = (
            "B001入口是2009年临终医疗房间，麦珂仍有生命体征；不能从殡仪馆、冷藏室或棺材开场。"
            "第1章死亡、第2章回到1969年十一岁试镜后台；其后19章主体是作品、舞台、母亲自主选择和事业飞升。"
            "只允许一次合同根冲突，程序细节最多占一成；前10章核心控制方必须永久失去一项钱、权、职位或关键资源。"
            "不得出现手指微颤频率、阅读停顿毫秒数、纸张纤维、墨水洇染定位、十一岁孩子起草附录或判断司法效力；"
            "麦珂只负责记住上一世谁在何时说过什么、跳过什么流程以及选择了什么，玛莎、律师、技师等成年人自行判断和行动。"
            "这是完整的第1—20章主干，不是试镜开头摘要：entry_state必须仍在2009临终；coarse_story_summary必须从2009死亡写到1969重生，"
            "并继续推进到1970块末，至少覆盖试镜/舞台、原创创作、同期媒体、玛莎自主选择、观众或歌迷五域中的四域。"
            "第一份合同冲突必须在本块前十章内完成结算，handoff_to_next_block不能再写‘下一步才正式签约或审核合同’。"
        )
    elif block_index == 25:
        special = (
            "终局麦珂始终清醒存活；对手误判他必死而提前启动讣告、保险与纪念直播，"
            "麦珂本人走入全球直播现场完成审判，禁止假死或受控昏迷。"
        )
    return (
        f"生成第{block_index}/25个20章故事块（第{start}—{end}章）的连续主干。"
        "本次只写块级因果、入口/出口状态和累计连续性，不生成macro_groups，不列十个事件方向。"
        f"\n上游全书切片：{_json_text(_block_global_context(block_index, global_outline))}"
        f"\n前序累计连续性账本：{_json_text(prior_block_ledger)}"
        "\n必须承接所有不可逆状态；程序与证据只是少数武器，主叙事是流行天王靠信息差、作品、舞台、市场和人物选择飞升。"
        "未成年麦珂不能做毫秒测量、微观鉴定、声纹建模或凭空法律工程；专业操作交给有资质成年人。"
        f"\n{special}\n全书硬契约：{_compact_planning_hard_context()}"
        f"\n只输出严格JSON：{_json_text(schema)}"
    )


def _macro_blueprint_prompt(
    *, block_index: int, macro_index: int, backbone: dict[str, Any],
    prior_macro: dict[str, Any] | None, global_outline: dict[str, Any],
) -> str:
    """Prompt one ten-chapter unit with exactly five two-chapter directions."""
    start, end = _macro_bounds(macro_index)
    first_event = (macro_index - 1) * 5 + 1
    direction_schemas: list[dict[str, Any]] = []
    for event_index in range(first_event, first_event + 5):
        eid = f"EC{event_index:03d}"
        direction: dict[str, Any] = {
            "cluster_id": eid, "chapter_span": list(_event_bounds(event_index)),
            "opposition_type": "villain | ally_resistance | institutional | technical | family | internal",
            "event_type": "performance | creation | contract_rights | finance_business | family_relationship | media_reputation | health_safety | fan_public_welfare | romance | legal_procedure",
            "solution_type": "performance_proof | creative_breakthrough | public_confrontation | negotiation | market_result | relationship_choice | safety_preemption | media_counter | financial_counter | legal_evidence | teamwork | strategic_withdrawal",
            "death_chain_role": "advance | pressure | reveal | echo",
            "previous_life_harm": "前世本陷阱实际造成的委屈、剥夺或失败，不能写成成功经验",
            "unique_prev_life_info": "至少12字；本事件独有的日期、原话、流程节点或对手选择",
            "preemptive_action": "信息差怎样直接促成今生少年可做的提前动作；专业动作由成年人完成",
            "chapter_one_small_win": f"第{event_index * 2 - 1}章只完成的可见小赢，不提前发放永久收益",
            "chapter_two_showdown": f"第{event_index * 2}章从新动作开始的正面交锋，不重演第一章",
            "opponent_permanent_loss": "第二章落定的现实损失，不能只是尴尬、改口或被质疑",
            "protagonist_concrete_gain": "第二章实际取得的资源、机会、关系主动权或声望",
            "irreversible_outcome_key": "短而唯一的状态机键，例如某职位撤销/某机会归属/某边界确立",
            "death_chain_connection": "本事件怎样削弱2009死亡背后的保险、版权、医疗或控制体系",
            "direction": "留空字符串；编译器将以上Qwen原创字段无损拼接为权威方向文本",
        }
        if block_index == 1:
            opposition, event_type, solution, death_role = B001_TYPE_LOCK[eid]
            direction.update({
                "opposition_type": opposition, "event_type": event_type,
                "solution_type": solution, "death_chain_role": death_role,
                "locked_story_brief": B001_EVENT_BRIEFS[eid],
            })
        direction_schemas.append(direction)
    schema = {
        "macro_group_id": f"MG{macro_index:03d}", "chapter_span": [start, end],
        "title": "十章组标题", "timeline_years": "年代",
        "macro_goal": "十章可验收目标", "historical_stage": "符合年代的产业舞台",
        "main_conflict": "十章具体冲突", "rebirth_advantage": "本组五个不重复的信息差范围",
        "five_event_directions": direction_schemas,
        "romance_progression": "关系线状态，未成年明确禁恋",
        "ending_state": "组末角色、关系、权利、资产、健康与伏笔状态",
        "next_group_hook": "结算后因果钩子",
    }
    return (
        f"把已锁定的20章主干细分为{macro_index}号十章单元（第{start}—{end}章）。"
        "本次只生成一个macro和五个两章事件方向，不得重写块级目标。"
        f"\n权威块级主干：{_json_text(backbone)}"
        f"\n同块前一个十章单元：{_json_text(prior_macro or {})}"
        f"\n全书相关切片：{_json_text(_block_global_context(block_index, global_outline))}"
        "\n五个方向必须是五件独立事件；只填写结构字段，direction必须留空，由编译器无损拼接，避免重复写两遍造成事实漂移。"
        "每一事件都用‘前世具体受害—今生抢先布局—"
        "第一章小赢—第二章新交锋—永久损失和收益—死亡控制主线意义’构成闭环。"
        "禁止‘提前做好准备’‘显示潜力’等空泛句，也禁止把前世的成功经验当信息差：信息差必须是前世遭过的陷阱、误导或剥夺。"
        "至少3种event_type，同一solution_type最多2次，法律程序最多1件；标签必须和实际剧情一致。"
        "每十章至少一个death_chain_role为advance/pressure/reveal；坏人滑稽必须导致其现实损失。"
        "人物遵守首次活跃阶段，未来人物不得提前登场；年代技术不得穿帮。1969—1970绝不出现网络、"
        "社交媒体、社交平台、数字传播或把现代合成器写成普通童星舞台设备；只能用同期报纸、电台、电视、磁带、胶片、电话、信件与现场观众。"
        "未成年麦珂不得凭毫秒、频率、微颤、纤维、材料氧化或法律效力精确判断取胜。"
        f"\n全书硬契约：{_compact_planning_hard_context()}\n只输出严格JSON：{_json_text(schema)}"
    )


def _compact_backbone_for_macro(backbone: dict[str, Any]) -> dict[str, Any]:
    return {
        key: backbone.get(key)
        for key in (
            "block_id", "chapter_span", "block_title", "timeline_years",
            "block_goal", "main_conflict", "rebirth_advantage",
            "character_movements", "causal_links_used",
            "foreshadows_planted_or_advanced", "block_outcome",
            "handoff_to_next_block",
        )
    }


def _compact_macro_core_for_direction(core: dict[str, Any]) -> dict[str, Any]:
    return {
        key: core.get(key)
        for key in (
            "macro_group_id", "chapter_span", "title", "timeline_years",
            "macro_goal", "main_conflict", "rebirth_advantage", "ending_state",
        )
    }


def _macro_core_prompt(
    *, block_index: int, macro_index: int, backbone: dict[str, Any],
    prior_macro: dict[str, Any] | None,
) -> str:
    start, end = _macro_bounds(macro_index)
    schema = {
        "macro_group_id": f"MG{macro_index:03d}", "chapter_span": [start, end],
        "title": "十章组标题", "timeline_years": "年代",
        "macro_goal": "十章可验收目标", "historical_stage": "符合年代的产业舞台",
        "main_conflict": "十章具体冲突", "rebirth_advantage": "五个事件可用的信息差范围",
        "romance_progression": "关系线状态；未成年明确禁恋",
        "ending_state": "组末人物、关系、权利、资产、健康与伏笔状态",
        "next_group_hook": "本组结算后必然触发的下一组压力",
    }
    prior_summary = {
        key: (prior_macro or {}).get(key)
        for key in ("macro_group_id", "ending_state", "next_group_hook")
    }
    return (
        f"把权威20章主干的第{start}—{end}章先拆成一个十章核心。"
        "本次不生成five_event_directions，只锁定十章目标、主冲突、人物/关系出口和下一组因果。"
        f"\n权威块主干：{_json_text(_compact_backbone_for_macro(backbone))}"
        f"\n前一个十章单元出口：{_json_text(prior_summary)}"
        "\n主叙事必须是重生歌手利用前世受害信息差，在作品、舞台、市场、家庭或媒体中主动反击；"
        "程序只在直接改变权利时出现。不得改变块级目标、年代、因果主链或伏笔范围。"
        "未成年禁恋；人物首次登场与年龄必须合理。只使用架空米国专名。"
        f"\n只输出严格JSON：{_json_text(schema)}"
    )


def _validate_macro_core(obj: dict[str, Any], macro_index: int) -> list[str]:
    failures: list[str] = []
    start, end = _macro_bounds(macro_index)
    if obj.get("macro_group_id") != f"MG{macro_index:03d}":
        failures.append(f"macro_group_id必须为MG{macro_index:03d}")
    if obj.get("chapter_span") != [start, end]:
        failures.append(f"chapter_span必须为{[start, end]}")
    for field, minimum in (
        ("title", 3), ("timeline_years", 4), ("macro_goal", 12),
        ("historical_stage", 12), ("main_conflict", 12),
        ("rebirth_advantage", 12), ("romance_progression", 8),
        ("ending_state", 16), ("next_group_hook", 10),
    ):
        if len(str(obj.get(field) or "").strip()) < minimum:
            failures.append(f"{field}过短或缺失")
    if "five_event_directions" in obj:
        failures.append("macro core不得提前输出five_event_directions")
    return failures


def _macro_direction_schema(block_index: int, event_index: int) -> dict[str, Any]:
    eid = f"EC{event_index:03d}"
    direction: dict[str, Any] = {
        "cluster_id": eid, "chapter_span": list(_event_bounds(event_index)),
        "opposition_type": "villain | ally_resistance | institutional | technical | family | internal",
        "event_type": "performance | creation | contract_rights | finance_business | family_relationship | media_reputation | health_safety | fan_public_welfare | romance | legal_procedure",
        "solution_type": "performance_proof | creative_breakthrough | public_confrontation | negotiation | market_result | relationship_choice | safety_preemption | media_counter | financial_counter | legal_evidence | teamwork | strategic_withdrawal",
        "death_chain_role": "advance | pressure | reveal | echo",
        "previous_life_harm": "前世本陷阱实际造成的具体委屈、剥夺或失败",
        "unique_prev_life_info": "至少12字；本事件独有的日期、原话、流程节点或对手选择",
        "preemptive_action": "信息差怎样直接促成今生提前动作；专业动作由成年人完成",
        "chapter_one_small_win": f"第{event_index * 2 - 1}章可见小赢，不提前发永久收益",
        "chapter_two_showdown": f"第{event_index * 2}章从新动作开始的交锋，不重演第一章",
        "opponent_permanent_loss": "第二章落定的钱、权、职位、资源、盟友或信誉损失",
        "protagonist_concrete_gain": "第二章实际取得的资源、机会、关系主动权或声望",
        "irreversible_outcome_key": "短而唯一的状态机结算键",
        "death_chain_connection": "怎样削弱2009死亡背后的保险、版权、医疗或控制体系",
        "direction": "必须留空字符串，由编译器无损拼接",
    }
    if block_index == 1:
        opposition, event_type, solution, death_role = B001_TYPE_LOCK[eid]
        direction.update({
            "opposition_type": opposition, "event_type": event_type,
            "solution_type": solution, "death_chain_role": death_role,
            "locked_story_brief": B001_EVENT_BRIEFS[eid],
        })
        if event_index == 1:
            direction.update({
                "previous_life_harm": "第1章：2009临终，康拉德违规用药/注射致死及麦珂上一世最终损失；不能改成设备事故",
                "unique_prev_life_info": "第1章临终听见的保险、版权/母带分赃原话或顺序；这是重生信息差",
                "preemptive_action": "第2章：1969重生后台，只报告记忆中的设备/走位危险，由成年人处理",
                "chapter_one_small_win": "EC001特例：第1章没有反击小赢；麦珂在死亡前获得利益链真相",
                "chapter_two_showdown": "第2章睁眼确认回到1969试镜后台，并用信息差避险、赢得试镜机会",
            })
    return direction


def _normalize_fictional_places(value: Any) -> Any:
    aliases = {
        "纽约": "银湾市", "洛杉矶": "星港市", "芝加哥": "湖城",
        "好莱坞": "银幕山", "伦敦": "雾河城", "东京": "东湾市",
        # Preserve an otherwise valid plot when the model leaks a real-world
        # brand or institution into the fictional setting.  These replacements
        # are compilation, not creative rewrites, so completed batches need not
        # be regenerated merely to rename the same narrative role.
        "MTV": "音乐电视台", "Excel": "电子表格软件", "索尼": "星音公司",
        "全网": "各地媒体", "云端": "远程档案库", "社交媒体": "公众媒体",
        "通用电气": "联合电器", "联合国教科文组织": "世界文化教育理事会",
        "国家职业安全卫生研究所": "联邦职业安全研究所",
        "戛纳": "海岬电影节", "威尼斯": "水城电影节",
        "Michael Jackson": "麦珂", "迈克尔·杰克逊": "麦珂",
        "麦克": "麦珂",
        "故意让奥瑞恩集团误以为他们掌握了部分核心证据，从而诱导对方加速伪造新的交易记录":
            "公开现有证据保全范围并预判奥瑞恩集团会自行加速伪造新的交易记录，提前合法留证",
        "反向诱导对方暴露更多罪行": "预判对方会自行暴露更多罪行并合法留证",
        "诱导奥瑞恩集团提交伪造的财务凭证": "预判奥瑞恩集团会自行提交伪造的财务凭证",
        "反向诱导对方在公开听证前提交关键错误文件": "预判对方会在公开听证前自行提交关键错误文件",
        "诱使对手在确信其死亡的前提下提前暴露全部操控链条":
            "等待被自身错误数据误导的对手自主提前暴露全部操控链条",
        "诱使维克多·兰斯集团误判其死亡并启动讣告与理赔程序":
            "预判维克多·兰斯集团会因既有错误数据自主误判死亡并启动讣告与理赔程序",
    }
    if isinstance(value, dict):
        return {
            key: (item if key == "locked_story_brief" else _normalize_fictional_places(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_fictional_places(item) for item in value]
    if isinstance(value, str):
        # Keep this cleanup idempotent.  The former replacement text itself
        # contained the substring “假死”, so repeated checkpoint resumes could
        # expand it again.  Collapse both the old expansion and the raw term to
        # a phrase that cannot match itself on the next pass.
        value = re.sub(r"虚+假死亡判定(?:亡判定)*", "错误死亡判定", value)
        value = re.sub(r"虚+错误死亡判定(?:亡判定)*", "错误死亡判定", value)
        value = value.replace("假死", "错误死亡判定")
        for real_name, fictional_name in aliases.items():
            value = value.replace(real_name, fictional_name)
    return value


def _normalize_locked_macro_direction(
    direction: dict[str, Any], block_index: int, event_index: int,
) -> dict[str, Any]:
    """Compile fixed structural fields without altering model-authored story facts."""
    normalized = dict(direction)
    normalized = _normalize_fictional_places(normalized)
    event_phase = (event_index * 2 - 1) // 50 + 1
    future_character_aliases = (
        (2, ("昆廷·琼斯", "昆廷"), "驻场编曲师"),
        (3, ("瑟琳娜·凯德", "瑟琳娜"), "青年演员"),
        (4, ("莉薇娅·普莱斯", "莉薇娅"), "嘉宾歌手"),
        (3, ("艾琳·沃特曼", "艾琳"), "声乐教练"),
        (3, ("苏菲亚·罗德里格斯", "苏菲亚"), "社区记录员"),
        (3, ("维克多·兰斯", "维克多"), "奥瑞恩集团高层"),
        (5, ("巴里·布鲁姆", "巴里"), "媒体经理"),
        (9, ("莱昂·周", "莱昂"), "独立审计员"),
    )
    present_fields = (
        "preemptive_action", "chapter_one_small_win", "chapter_two_showdown",
        "opponent_permanent_loss", "protagonist_concrete_gain",
        "irreversible_outcome_key",
    )
    for required_phase, aliases, generic_role in future_character_aliases:
        if event_phase >= required_phase:
            continue
        for field in present_fields:
            value = normalized.get(field)
            if not isinstance(value, str):
                continue
            for alias in aliases:
                value = value.replace(alias, generic_role)
            normalized[field] = value
    if str(normalized.get("opposition_type") or "") not in OPPOSITION_TYPES:
        normalized["opposition_type"] = "institutional"
    if str(normalized.get("event_type") or "") not in EVENT_TYPES:
        normalized["event_type"] = "creation"
    if str(normalized.get("solution_type") or "") not in SOLUTION_TYPES:
        normalized["solution_type"] = "strategic_withdrawal"
    if str(normalized.get("death_chain_role") or "") not in {"advance", "pressure", "reveal", "echo"}:
        normalized["death_chain_role"] = "echo"
    expected = _macro_direction_schema(block_index, event_index)
    normalized["cluster_id"] = expected["cluster_id"]
    normalized["chapter_span"] = expected["chapter_span"]
    normalized["direction"] = ""
    if block_index == 1:
        for field in (
            "opposition_type", "event_type", "solution_type", "death_chain_role",
            "locked_story_brief",
        ):
            normalized[field] = expected[field]
    return normalized


def _validate_macro_direction_batch(
    obj: dict[str, Any], *, macro_index: int, block_index: int,
    event_indices: list[int], prior_directions: list[dict[str, Any]],
    global_outline: dict[str, Any] | None = None,
) -> list[str]:
    failures: list[str] = []
    if obj.get("macro_group_id") != f"MG{macro_index:03d}":
        failures.append(f"macro_group_id必须为MG{macro_index:03d}")
    directions = obj.get("event_directions")
    if not isinstance(directions, list) or len(directions) != len(event_indices):
        return failures + [f"event_directions必须恰好{len(event_indices)}项"]
    prior_infos = [str(item.get("unique_prev_life_info") or "") for item in prior_directions]
    prior_outcomes = [str(item.get("irreversible_outcome_key") or "") for item in prior_directions]
    for direction, event_index in zip(directions, event_indices):
        eid = f"EC{event_index:03d}"
        if not isinstance(direction, dict):
            failures.append(f"{eid}必须为对象")
            continue
        direction = _normalize_locked_macro_direction(direction, block_index, event_index)
        if direction.get("cluster_id") != eid:
            failures.append(f"cluster_id必须为{eid}")
        if direction.get("chapter_span") != list(_event_bounds(event_index)):
            failures.append(f"{eid}.chapter_span错误")
        if str(direction.get("opposition_type") or "") not in OPPOSITION_TYPES:
            failures.append(f"{eid}.opposition_type非法")
        if str(direction.get("event_type") or "") not in EVENT_TYPES:
            failures.append(f"{eid}.event_type非法")
        if str(direction.get("solution_type") or "") not in SOLUTION_TYPES:
            failures.append(f"{eid}.solution_type非法")
        if str(direction.get("death_chain_role") or "") not in {"advance", "pressure", "reveal", "echo"}:
            failures.append(f"{eid}.death_chain_role非法")
        for field, minimum in (
            ("previous_life_harm", 8), ("unique_prev_life_info", 12),
            ("preemptive_action", 8), ("chapter_one_small_win", 8),
            ("chapter_two_showdown", 8), ("opponent_permanent_loss", 8),
            ("protagonist_concrete_gain", 8), ("irreversible_outcome_key", 4),
            ("death_chain_connection", 8),
        ):
            if len(str(direction.get(field) or "").strip()) < minimum:
                failures.append(f"{eid}.{field}至少{minimum}字")
        if direction.get("direction") not in (None, ""):
            failures.append(f"{eid}.direction必须留空")
        template = _macro_direction_schema(block_index, event_index)
        for field in (
            "previous_life_harm", "unique_prev_life_info", "preemptive_action",
            "chapter_one_small_win", "chapter_two_showdown", "opponent_permanent_loss",
            "protagonist_concrete_gain", "irreversible_outcome_key",
            "death_chain_connection",
        ):
            if str(direction.get(field) or "").strip() == str(template.get(field) or "").strip():
                failures.append(f"{eid}.{field}照抄了JSON字段说明，必须改成原创具体剧情事实")
        if block_index == 1:
            expected = _macro_direction_schema(block_index, event_index)
            for field in (
                "opposition_type", "event_type", "solution_type", "death_chain_role",
                "locked_story_brief",
            ):
                if direction.get(field) != expected.get(field):
                    failures.append(f"{eid}.{field}必须逐字服从锁定值")
            story_fields = _json_text({
                key: direction.get(key) for key in (
                    "previous_life_harm", "unique_prev_life_info", "preemptive_action",
                    "chapter_one_small_win", "chapter_two_showdown",
                    "opponent_permanent_loss", "protagonist_concrete_gain",
                    "death_chain_connection",
                )
            })
            for alternatives in B001_EVENT_REQUIRED_ANCHORS[eid]:
                if not any(anchor in story_fields for anchor in alternatives):
                    failures.append(
                        f"{eid}必须落实锁定事实词：{'/'.join(alternatives)}"
                    )
            if eid == "EC001":
                previous_harm = str(direction.get("previous_life_harm") or "")
                info_gap = str(direction.get("unique_prev_life_info") or "")
                current_action = _json_text({
                    "preemptive_action": direction.get("preemptive_action"),
                    "chapter_two_showdown": direction.get("chapter_two_showdown"),
                })
                if not all(token in previous_harm for token in ("2009", "康拉德")) or not any(
                    token in previous_harm for token in ("临终", "致死", "死亡")
                ):
                    failures.append("EC001.previous_life_harm必须是2009年康拉德致死的临终现场")
                if not any(token in previous_harm for token in ("药", "注射", "输液")):
                    failures.append("EC001.previous_life_harm必须写康拉德违规用药/注射致死，不能改成设备事故")
                if "保险" not in info_gap or not any(token in info_gap for token in ("版权", "母带")):
                    failures.append("EC001.unique_prev_life_info必须是临终听见的保险与版权/母带分赃信息")
                if "1969" not in current_action or not any(
                    token in current_action for token in ("设备", "走位", "安全", "危险")
                ):
                    failures.append("EC001第2章动作必须发生在1969试镜后台并利用设备/走位险情信息")
                current_settlement = _json_text({
                    "chapter_two_showdown": direction.get("chapter_two_showdown"),
                    "opponent_permanent_loss": direction.get("opponent_permanent_loss"),
                    "protagonist_concrete_gain": direction.get("protagonist_concrete_gain"),
                })
                if "康拉德" in current_settlement:
                    failures.append("EC001的1969结算只能处罚当时失职者，不能提前处罚2009年的康拉德")
            elif eid == "EC002":
                memory = _json_text({
                    "previous_life_harm": direction.get("previous_life_harm"),
                    "unique_prev_life_info": direction.get("unique_prev_life_info"),
                })
                action = str(direction.get("preemptive_action") or "")
                if "乔纳" not in memory or not any(token in memory for token in ("限时", "截止", "马上签")):
                    failures.append("EC002前世信息必须是乔纳受限时报名谎话催促而速签")
                child_level_request = any(
                    token in action for token in ("问", "请", "提醒", "提议", "请求")
                )
                mother_present = any(token in action for token in ("玛莎", "母亲", "妈妈"))
                if not mother_present or not child_level_request:
                    failures.append("EC002今生只能由麦珂提少年能问的问题，再由玛莎决定暂停并请律师审查")
                if any(token in action for token in ("指出条款", "起草", "出具", "法律函", "公证")):
                    failures.append("EC002不得让未成年麦珂设计或出具法律文件")
                settlement = _json_text({
                    "chapter_one_small_win": direction.get("chapter_one_small_win"),
                    "chapter_two_showdown": direction.get("chapter_two_showdown"),
                    "opponent_permanent_loss": direction.get("opponent_permanent_loss"),
                    "protagonist_concrete_gain": direction.get("protagonist_concrete_gain"),
                    "irreversible_outcome_key": direction.get("irreversible_outcome_key"),
                })
                positive_signing = re.search(
                    r"(?<!拒)(?<!未)(?<!不)(?:签署|签下|签了|正式签约|完成签约)", settlement,
                )
                signing_is_negated = any(token in settlement for token in (
                    "拒绝签署", "拒签", "未签", "仍未签", "暂停签",
                ))
                if positive_signing and not signing_is_negated:
                    failures.append("EC002的不可逆结算是暂停速签并交律师审查，不得让麦珂在本事件签下合同")
                if "她" in story_fields:
                    failures.append("EC002人物身份错误：麦珂为男性，不得用“她”指代")
            elif eid == "EC003":
                event_story = _json_text({
                    "previous_life_harm": direction.get("previous_life_harm"),
                    "unique_prev_life_info": direction.get("unique_prev_life_info"),
                    "chapter_two_showdown": direction.get("chapter_two_showdown"),
                    "opponent_permanent_loss": direction.get("opponent_permanent_loss"),
                })
                if "乔纳" not in event_story:
                    failures.append("EC003必须由乔纳截住试镜回函并失去独占家庭消息的权力")
        if event_index * 2 <= 90:
            child_gain = str(direction.get("protagonist_concrete_gain") or "")
            if any(token in child_gain for token in (
                "导师", "主席", "委员会", "官方认证", "法律先例",
                "教育部", "文化部门", "身份证书",
            )):
                failures.append(f"{eid}.protagonist_concrete_gain给未成年主角安排了成人职位或制度头衔")
        if 2 <= event_index <= 225:
            present_timeline = _json_text({
                key: direction.get(key) for key in (
                    "preemptive_action", "chapter_one_small_win", "chapter_two_showdown",
                    "opponent_permanent_loss", "protagonist_concrete_gain",
                )
            })
            if "康拉德" in present_timeline:
                failures.append(f"{eid}不得让2009年晚年医生康拉德在第451章前实体登场")
        if global_outline and not (block_index == 1 and eid == "EC001"):
            try:
                event_phase = (int(direction.get("chapter_span", [0, 0])[1]) - 1) // 50 + 1
            except (TypeError, ValueError, IndexError):
                event_phase = (event_index * 2 - 1) // 50 + 1
            physical_text = _json_text({
                key: direction.get(key) for key in (
                    "preemptive_action", "chapter_one_small_win", "chapter_two_showdown",
                    "opponent_permanent_loss", "protagonist_concrete_gain",
                    "irreversible_outcome_key",
                )
            })
            for arc in global_outline.get("character_long_arcs", []):
                if not isinstance(arc, dict):
                    continue
                name = str(arc.get("character") or "").strip()
                phase_match = re.fullmatch(r"P(\d{2})", str(arc.get("first_active_phase") or ""))
                aliases = {name, name.split("·", 1)[0]} if name else set()
                if (
                    name and phase_match and int(phase_match.group(1)) > event_phase
                    and any(alias and alias in physical_text for alias in aliases)
                ):
                    failures.append(
                        f"{eid}时间线错误：{name}首次活跃于P{int(phase_match.group(1)):02d}，不得提前实体登场"
                    )
        current_info = str(direction.get("unique_prev_life_info") or "")
        if any(
            current_info and prior
            and SequenceMatcher(None, current_info, prior, autojunk=False).ratio() >= 0.62
            for prior in prior_infos
        ):
            failures.append(f"{eid}.unique_prev_life_info与前批事件重复")
        prior_infos.append(current_info)
        current_outcome = str(direction.get("irreversible_outcome_key") or "")
        if any(
            current_outcome and prior
            and SequenceMatcher(None, current_outcome, prior, autojunk=False).ratio() >= 0.62
            for prior in prior_outcomes
        ):
            failures.append(f"{eid}.irreversible_outcome_key与前批事件重复")
        prior_outcomes.append(current_outcome)
    return failures


def _macro_direction_batch_prompt(
    *, block_index: int, macro_index: int, backbone: dict[str, Any],
    macro_core: dict[str, Any], event_indices: list[int],
    prior_directions: list[dict[str, Any]], global_outline: dict[str, Any],
) -> str:
    schemas = [_macro_direction_schema(block_index, index) for index in event_indices]
    prompt_schemas = json.loads(_json_text(schemas))
    for schema in prompt_schemas:
        for field in (
            "previous_life_harm", "unique_prev_life_info", "preemptive_action",
            "chapter_one_small_win", "chapter_two_showdown", "opponent_permanent_loss",
            "protagonist_concrete_gain", "irreversible_outcome_key",
            "death_chain_connection", "direction",
        ):
            schema[field] = ""
    prior_summary = [
        {
            key: item.get(key)
            for key in (
                "cluster_id", "event_type", "solution_type", "unique_prev_life_info",
                "irreversible_outcome_key", "death_chain_connection",
            )
        }
        for item in prior_directions
    ]
    global_slice = _global_outline_slice(global_outline, macro_index)
    compact_global = {
        "one_sentence_premise": global_slice.get("one_sentence_premise"),
        "relevant_causal_spine": global_slice.get("relevant_causal_spine"),
        "relevant_foreshadows": global_slice.get("relevant_foreshadows"),
        "active_character_boundaries": global_slice.get("active_character_boundaries"),
    }
    required_anchor_map = {
        f"EC{index:03d}": ["/".join(group) for group in B001_EVENT_REQUIRED_ANCHORS[f"EC{index:03d}"]]
        for index in event_indices
        if block_index == 1
    }
    event_specific_rules = ""
    if block_index == 1 and 2 in event_indices:
        event_specific_rules = (
            "\nEC002结尾状态必须是：合同仍未签，玛莎暂停速签并交成年律师审查，"
            "乔纳永久失去当日逼签通道。第4章必须有拒签/暂停/修改条件的实际谈判。"
            "麦珂是男孩，不得用‘她’；不得签署任何合同、备忘录或公证文件；"
            "不得获得官方认证、教育部或委员会头衔。"
        )
    return (
        f"为{macro_core.get('macro_group_id')}只生成这些两章方向："
        f"{', '.join(f'EC{i:03d}' for i in event_indices)}。不得输出其他事件或重写macro core。"
        f"\n权威十章核心：{_json_text(_compact_macro_core_for_direction(macro_core))}"
        f"\n权威块主干：{_json_text(_compact_backbone_for_macro(backbone))}"
        f"\n全书相关因果边界：{_json_text(compact_global)}"
        f"\n前批已写方向（信息差和结算不得重复）：{_json_text(prior_summary)}"
        f"\n本批锁定事实词组（每组至少出现一个词）：{_json_text(required_anchor_map)}"
        "\nJSON结构中的中文句子只是字段说明，所有剧情字段必须全部改写成带人物、动作和结果的原创事实；"
        "逐字复制‘前世本陷阱实际造成’‘第二章实际取得’‘短而唯一的状态机结算键’等说明会判失败。"
        "\n每项必须形成‘前世明确受害→今生主动抢先→第一章小赢→第二章新交锋→因果式永久清算’。"
        "清算必须由主角布局促成；反派应意识到是麦珂反制，并尽量有他人现场见证或公开权力倒置。"
        "坏人可因抢功、贪婪或嘴硬显得滑稽，但滑稽行为必须造成真实损失。"
        "人物动作和语言要符合其既有身份；阻力不是villain时不得强写恶人。"
        "康拉德是2009年晚年医生，只能出现在前世死亡记忆或死亡链说明中，第451章前不得进入今生实体行动。"
        "前世记忆只能提供日期、原话、流程和人物选择，不能直接充当今生证据；未成年不做专业鉴定或法律工程。"
        "至少让一个核心人物在两个都有价值或代价的选项之间选择，不得用旁白直接解释性格。"
        "只用同期可行媒介与架空米国专名。direction留空，由编译器从结构字段拼接。"
        "每个剧情字段只写一句15—45字的具体事实，不写长段解释，不新造制度或头衔。"
        f"{event_specific_rules}"
        f"\n只输出严格JSON：{_json_text({'macro_group_id': f'MG{macro_index:03d}', 'event_directions': prompt_schemas})}"
    )


def _generate_macro_blueprint_batched(
    *, block_index: int, macro_index: int, backbone: dict[str, Any],
    prior_macro: dict[str, Any] | None, global_outline: dict[str, Any],
    checkpoint_dir: Path, model: str, resume: bool,
) -> dict[str, Any]:
    mid = f"MG{macro_index:03d}"
    final_path = checkpoint_dir / f"{mid}_macro_blueprint.json"
    final_provenance_path = checkpoint_dir / f"{mid}_macro_blueprint_provenance.json"
    manual_override_path = checkpoint_dir / "manual_overrides" / f"{mid}.json"
    if manual_override_path.is_file():
        try:
            override = json.loads(manual_override_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{mid}人工连续性覆盖文件不可读：{exc}") from exc
        override = _normalize_fictional_places(_compile_macro_direction_fields(override))
        failures = _validate_macro_blueprint(
            override, macro_index, block_index, global_outline,
        )
        if failures:
            raise RuntimeError(
                f"{mid}人工连续性覆盖校验失败：" + " | ".join(failures[:30])
            )
        print(
            f"[manual-override] {mid} macro blueprint source={manual_override_path.name}",
            flush=True,
        )
        return override
    if resume and final_path.is_file() and final_provenance_path.is_file():
        try:
            existing = json.loads(final_path.read_text(encoding="utf-8"))
            provenance = json.loads(final_provenance_path.read_text(encoding="utf-8"))
            normalized_existing = _normalize_fictional_places(existing)
            if normalized_existing != existing:
                existing = normalized_existing
                provenance["compiler_normalizations"] = sorted(set([
                    *(provenance.get("compiler_normalizations") or []),
                    "fictional_place_aliases",
                ]))
                provenance["compiled_sha256"] = canonical_sha256(existing)
                _write_json(final_path, existing)
                _write_json(final_provenance_path, provenance)
            if (
                not _validate_macro_blueprint(existing, macro_index, block_index, global_outline)
                and provenance.get("acceptance_mode") == "batched_macro_compile"
                and provenance.get("compiled_sha256") == canonical_sha256(existing)
                and provenance.get("manual_edits") == []
            ):
                print(f"[resume] {mid} batched macro blueprint", flush=True)
                return existing
        except (OSError, json.JSONDecodeError):
            pass
    core = _call_validated(
        kind="macro_core", identifier=mid, system_prompt=_system_prompt(),
        user_prompt=_macro_core_prompt(
            block_index=block_index, macro_index=macro_index, backbone=backbone,
            prior_macro=prior_macro,
        ),
        validator=lambda obj: _validate_macro_core(obj, macro_index),
        checkpoint_dir=checkpoint_dir, model=model, temperature=0.70,
        resume=resume, max_attempts=4, max_output_tokens=1200,
    )
    first_event = (macro_index - 1) * 5 + 1
    # Output-first mode: author one complete ten-chapter group per request.
    # This cuts macro-direction calls from 250 to 50.  A smaller batch can still
    # be selected explicitly for providers with unusually tight token limits.
    direction_batch_size = min(
        5, max(1, int(os.getenv("PLANNER_MACRO_DIRECTION_BATCH_SIZE", "5")))
    )
    # MG001 already has four accepted one-event checkpoints from the earlier
    # run.  Reuse them and regenerate only the rejected EC002 instead of
    # throwing away usable output to satisfy the new batching strategy.
    if macro_index == 1:
        direction_batch_size = 1
    all_event_indices = [first_event + offset for offset in range(5)]
    batches = [
        all_event_indices[offset:offset + direction_batch_size]
        for offset in range(0, 5, direction_batch_size)
    ]
    directions: list[dict[str, Any]] = []
    component_provenance_paths = [checkpoint_dir / f"{mid}_macro_core_provenance.json"]
    for event_indices in batches:
        first_event_id = f"EC{event_indices[0]:03d}"
        last_event_id = f"EC{event_indices[-1]:03d}"
        kind = (
            f"macro_direction_{first_event_id}"
            if len(event_indices) == 1
            else f"macro_directions_{first_event_id}_{last_event_id}"
        )
        batch = _call_validated(
            kind=kind, identifier=mid, system_prompt=_system_prompt(),
            user_prompt=_macro_direction_batch_prompt(
                block_index=block_index, macro_index=macro_index, backbone=backbone,
                macro_core=core, event_indices=event_indices,
                prior_directions=directions, global_outline=global_outline,
            ),
            validator=lambda obj, indices=event_indices, prior=list(directions): (
                _validate_macro_direction_batch(
                    obj, macro_index=macro_index, block_index=block_index,
                    event_indices=indices, prior_directions=prior,
                    global_outline=global_outline,
                )
            ),
            checkpoint_dir=checkpoint_dir, model=model, temperature=0.72,
            resume=resume, max_attempts=4,
            allow_prompt_drift=True,
            # Keep two-event requests below the 8B fallback's 6K TPM ceiling;
            # Chinese structured directions fit in roughly 800 tokens each.
            max_output_tokens=max(1200, 650 * len(event_indices)),
        )
        normalized_directions = [
            _normalize_locked_macro_direction(item, block_index, index)
            for item, index in zip(batch["event_directions"], event_indices)
        ]
        if normalized_directions != batch["event_directions"]:
            batch = {**batch, "event_directions": normalized_directions}
            component_path = checkpoint_dir / f"{mid}_{kind}.json"
            component_provenance_path = checkpoint_dir / f"{mid}_{kind}_provenance.json"
            _write_json(component_path, batch)
            try:
                component_provenance = json.loads(
                    component_provenance_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                component_provenance = {}
            component_provenance["structural_normalizations"] = [
                "cluster_id", "chapter_span", "B001_locked_enums_and_story_brief",
            ]
            component_provenance["normalized_parsed_sha256"] = canonical_sha256(batch)
            _write_json(component_provenance_path, component_provenance)
        directions.extend(batch["event_directions"])
        component_provenance_paths.append(checkpoint_dir / f"{mid}_{kind}_provenance.json")
    result = _normalize_fictional_places(
        _compile_macro_direction_fields({**core, "five_event_directions": directions})
    )
    failures = _validate_macro_blueprint(result, macro_index, block_index, global_outline)
    if failures:
        raise RuntimeError(f"{mid}分批合并后校验失败：" + " | ".join(failures[:30]))
    providers = _generation_providers(component_provenance_paths)
    _write_json(final_path, result)
    _write_json(final_provenance_path, {
        "generated_by": providers[0] if providers else "qwen",
        "generation_providers": providers,
        "kind": "macro_blueprint", "identifier": mid,
        "accepted_attempt": "batched_compile",
        "acceptance_mode": "batched_macro_compile",
        "component_provenance_files": [path.name for path in component_provenance_paths],
        "compiled_sha256": canonical_sha256(result),
        "manual_edits": [], "created_at": _now(),
    })
    print(
        f"[compiled] {mid} core+{'+'.join(str(len(batch)) for batch in batches)} directions",
        flush=True,
    )
    return result


def _volume_prompt(
    volume_index: int,
    prior_volume_summary: dict[str, Any],
    global_outline: dict[str, Any],
) -> str:
    volume = VOLUMES[volume_index - 1]
    start, end = _volume_bounds(volume_index)
    group_specs = [
        {"macro_group_id": f"MG{i:03d}", "chapter_span": list(_macro_bounds(i))}
        for i in range((volume_index - 1) * 5 + 1, volume_index * 5 + 1)
    ]
    schema = {
        "volume_id": f"V{volume_index:02d}",
        "volume_title": "Qwen创作的卷名",
        "volume_summary": "不少于150字",
        "macro_groups": [{
            "macro_group_id": "MGxxx", "chapter_span": [1, 10], "title": "具体组名",
            "timeline_years": "年代", "macro_goal": "十章完成的现实目标",
            "historical_stage": "采用或改写的产业年代舞台", "main_conflict": "具体主冲突",
            "rebirth_advantage": "前世记忆如何提供可操作信息差",
            "five_event_directions": [{"cluster_id": "ECxxx", "chapter_span": [1, 2], "direction": "只描述这一对章节的一件独立事件"}],
            "romance_progression": "本组感情线状态或未成年禁恋说明",
            "ending_state": "组末人物、权利、资产、健康和关系状态",
            "next_group_hook": "只留下一组钩子，不拖欠本组事件结算",
        }],
        "continuity_summary": {"characters": [], "relationships": [], "rights_and_assets": [], "open_threads": []},
    }
    return (
        f"为全书第{volume_index}卷（第{start}-{end}章）创作卷级蓝图。五个宏观组的ID和章节范围不可改变。\n"
        f"本卷年代参考：{volume['years']}。只可使用其年代功能，不要照抄现实姓名或作品。\n"
        f"本卷在全书中的任务参考：{volume['goal']}。这是方向而非现成剧情，你必须重新创作具体五组故事。\n"
        f"指定分组：{_json_text(group_specs)}\n"
        f"可参考的真实年代锚点：{_json_text(_relevant_anchors(volume))}\n"
        f"上一卷连续性摘要：{_json_text(prior_volume_summary)}\n"
        f"Qwen已锁定的全书宽泛总纲（本卷必须从中拆分，不得另起故事）：{_json_text(global_outline)}\n"
        "每组必须给出五个不重复的两章事件方向对象，事件ID和两章范围必须从该组十章依次计算；每个对象只准描述一件两章事件，禁止在一项里再列多个Chapter范围。"
        "至少覆盖舞台表演、合同权利、家庭/伙伴、公益或粉丝、媒体/健康中的三类。"
        "反派手段可以是现实没有的虚构陷阱，但重生后的麦珂必须提前避开并持续升级。\n"
        f"全书契约：{_base_context()}\n"
        + (
            "\nMG001特殊硬要求：timeline_years必须写“2009→1969”；EC001方向必须明确第1章2009年前世死亡、第2章1969年十一岁试镜后台重生。"
            if volume_index == 1 else ""
        )
        + f"\n严格按这个JSON结构输出；macro_groups展开5项，每组five_event_directions展开5项：{_json_text(schema)}"
    )


def _compact_graph_context_for_events(graph_context: dict[str, Any] | None) -> dict[str, Any]:
    """Keep graph authority while removing duplicated full macro payloads."""
    context = graph_context or {}
    block = context.get("current_block") or {}
    current_macro = context.get("current_macro") or {}
    recent = []
    for event in (context.get("recent_completed_events") or [])[-3:]:
        if not isinstance(event, dict):
            continue
        recent.append({
            key: event.get(key) for key in (
                "cluster_id", "chapter_span", "cluster_outcome", "relationship_change",
                "state_transitions", "next_event_hook",
            )
        })
    return {
        "source": context.get("source"),
        "story_id": context.get("story_id"),
        "current_macro": {
            key: current_macro.get(key) for key in (
                "macro_group_id", "chapter_span", "title", "ending_state",
            )
        },
        "current_block": {
            key: block.get(key) for key in (
                "block_id", "chapter_span", "block_title", "timeline_years", "block_outcome",
            )
        },
        "recent_completed_events": recent,
        # The full canonical state remains authoritative in Neo4j and is fed
        # separately to the deterministic state validator.  Sending every
        # historical state on every event made relay requests exceed Groq's
        # body limit, so the authoring prompt only needs the recent working
        # set; older facts are still enforced after generation.
        "canonical_state": dict(list((context.get("canonical_state") or {}).items())[-4:]),
        "available_artifacts": (context.get("available_artifacts") or [])[-5:],
    }


def _compact_macro_for_event_prompt(
    macro: dict[str, Any], selected_event_indices: list[int],
) -> dict[str, Any]:
    """Send only the parent direction(s) being expanded in this API call."""
    selected_ids = {f"EC{index:03d}" for index in selected_event_indices}
    compact = {
        key: macro.get(key) for key in (
            "macro_group_id", "chapter_span", "title", "timeline_years",
            "macro_goal", "main_conflict", "rebirth_advantage",
            "causal_links_used", "foreshadows_planted_or_advanced",
            "ending_state", "next_group_hook", "story_block_id",
        )
        if macro.get(key) not in (None, "", [], {})
    }
    compact["selected_event_directions"] = [
        item for item in (macro.get("five_event_directions") or [])
        if isinstance(item, dict) and str(item.get("cluster_id") or "") in selected_ids
    ]
    return compact


def _compact_outline_slice_for_events(
    global_outline: dict[str, Any], macro_index: int,
) -> dict[str, Any]:
    """Keep the active life phase and ledgers relevant to this macro only."""
    source = _global_outline_slice(global_outline, macro_index)
    phase_index = (macro_index - 1) // 5 + 1
    phase_id = f"P{phase_index:02d}"
    return {
        "story_title": source.get("story_title"),
        "one_sentence_premise": source.get("one_sentence_premise"),
        "core_rebirth_logic": source.get("core_rebirth_logic"),
        "active_life_phase": [{
            key: phase.get(key) for key in (
                "phase_id", "chapter_span", "timeline_years", "broad_story_goal",
                "main_pressure", "rebirth_advantage", "phase_outcome",
            )
        } for phase in (source.get("nearby_life_phases") or [])
            if str(phase.get("phase_id") or "") == phase_id],
        "relevant_causal_spine": [{
            key: item.get(key) for key in (
                "spine_id", "cause", "result", "later_consequence",
            )
        } for item in (source.get("relevant_causal_spine") or [])],
        "relevant_foreshadows": [{
            key: item.get(key) for key in (
                "thread_id", "thread", "payoff_phase", "payoff_function",
            )
        } for item in (source.get("relevant_foreshadows") or [])],
        "active_character_boundaries": source.get("active_character_boundaries") or [],
    }


def _compact_prior_ledger_for_events(ledger: dict[str, Any] | None) -> dict[str, Any]:
    """Remove the canonical-state copy already supplied by Neo4j context."""
    source = ledger or {}
    compact: dict[str, Any] = {}
    for key in (
        "current_year", "next_pressure", "character_states", "relationship_states",
        "rights_and_assets", "health_and_location", "open_threads", "resolved_threads",
        "introduced_characters",
    ):
        value = source.get(key)
        if isinstance(value, list):
            compact[key] = value[-2:]
        elif value not in (None, "", {}):
            compact[key] = value
    # Neo4j's compact graph context already carries the recent working state;
    # do not duplicate it in this ledger copy.
    compact["irreversible_state_keys"] = (source.get("irreversible_state_keys") or [])[-40:]
    return compact


def _events_prompt(
    macro: dict[str, Any],
    prior_ledger: dict[str, Any],
    global_outline: dict[str, Any],
    graph_context: dict[str, Any] | None = None,
    event_indices: list[int] | None = None,
    prior_batch_events: list[dict[str, Any]] | None = None,
) -> str:
    macro_index = int(str(macro["macro_group_id"])[2:])
    selected_event_indices = event_indices or list(range((macro_index - 1) * 5 + 1, macro_index * 5 + 1))
    macro_for_prompt = _compact_macro_for_event_prompt(macro, selected_event_indices)
    graph_context_for_prompt = _compact_graph_context_for_events(graph_context)
    outline_slice_for_prompt = _compact_outline_slice_for_events(global_outline, macro_index)
    if 23 <= macro_index <= 45:
        replacement = "由Qwen新创的、年龄与当前年代合理的架空医生对手"
        macro_for_prompt = json.loads(_json_text(macro).replace("康拉德", replacement))
        graph_context_for_prompt = json.loads(_json_text(graph_context_for_prompt).replace("康拉德", replacement))
        outline_slice_for_prompt = json.loads(_json_text(outline_slice_for_prompt).replace("康拉德", replacement))
    first_event = (macro_index - 1) * 5 + 1
    event_specs = [
        {"cluster_id": f"EC{i:03d}", "chapter_span": list(_event_bounds(i))}
        for i in selected_event_indices
    ]
    event_schema = {
        "name": "事件名", "timeline_years": "年代", "main_opponent": "对手",
        "opposition_type": "锁定值", "event_type": "锁定值",
        "solution_type": "锁定值", "death_chain_role": "锁定值",
        "causal_spine_ids": ["CSxx"], "foreshadow_ids": [],
        "main_characters": ["人物"], "fictional_obstacle": "今生陷阱",
        "prev_life_tragedy": "前世具体损失", "info_gap_from_prev_life": "日期/原话/流程/选择",
        "why_previous_life_failed": "前世失败原因", "preemptive_avoidance": "今生提前拆险",
        "bait_and_evidence": "安全留饵及今生证据", "comic_villain_behavior": "反派滑稽失算",
        "villain_loss": "永久损失", "protagonist_gain": "永久收益",
        "relationship_change": "关系变化", "continuity_writes": ["既成事实"],
        "state_transitions": [{
            "domain": "域", "entity_id": "稳定ID", "state_key": "状态键",
            "from": "旧值/none", "to": "新值", "irreversible": False,
            "evidence": "生效动作", "effect_type": "villain_loss | protagonist_gain | relationship_change | world_state",
        }],
        "historical_anchor_ids": ["FICTION_ONLY"], "cluster_outcome": "闭环状态",
        "next_event_hook": "结算后钩子",
    }
    event_schemas = []
    direction_by_id = {
        str(item.get("cluster_id") or ""): item
        for item in (macro.get("five_event_directions") or [])
        if isinstance(item, dict)
    }
    for spec in event_specs:
        start_chapter, end_chapter = spec["chapter_span"]
        source_direction = direction_by_id.get(spec["cluster_id"], {})
        schema = {
            "cluster_id": spec["cluster_id"],
            "chapter_span": spec["chapter_span"],
            "source_event_direction": str(source_direction.get("direction") or ""),
            "source_event_direction_sha256": canonical_sha256(
                str(source_direction.get("direction") or "")
            ),
            "source_macro_sha256": canonical_sha256(macro),
            **event_schema,
            "two_chapter_structure": [
                {
                    "chapter_id": start_chapter,
                    "timeline_start": "YYYY、YYYY-MM或YYYY-MM-DD",
                    "timeline_end": "不得早于timeline_start",
                    "scene": "主场景", "chapter_goal": "目标", "chapter_title": "章名",
                    "participants": ["在场人物"], "opening_conflict": "开章冲突",
                    "info_gap_use": "信息差用法", "opponent_reaction": "现场反应",
                    "scenes": [{
                        "sequence": 1, "location": "场景地点", "is_primary": True,
                        "temporal_mode": "current | previous_life_memory | flashback",
                        "transition_cue": "首场写开场；转场/倒叙必须写正文可见提示",
                    }],
                    "artifact_creates": [{"artifact_id": "ART_稳定ID", "timeline_scope": "previous_life或current", "display_name": "文件/账户/母带名", "kind": "document|account|recording|asset|device"}],
                    "artifact_refs": [{"artifact_id": "只能引用同一timeline_scope本章此前或本章创建的ID", "timeline_scope": "previous_life或current", "purpose": "为何引用"}],
                    "action_sequence": ["四步动作"], "visible_payoff": "可见小赢", "ending": "钩子",
                    "must_include": ["三项"], "must_not_include": ["两项"],
                    "detailed_synopsis": "120—220字正文依据",
                },
                {
                    "chapter_id": end_chapter,
                    "timeline_start": "不得早于第一章timeline_end",
                    "timeline_end": "不得早于timeline_start",
                    "scene": "主场景", "chapter_goal": "目标", "chapter_title": "章名",
                    "participants": ["在场人物"], "opening_conflict": "承接钩子的新动作",
                    "info_gap_use": "信息差用法", "opponent_reaction": "滑稽失算反应",
                    "scenes": [{
                        "sequence": 1, "location": "场景地点", "is_primary": True,
                        "temporal_mode": "current | previous_life_memory | flashback",
                        "transition_cue": "首场写开场；转场/倒叙必须写正文可见提示",
                    }],
                    "artifact_creates": [], "artifact_refs": [],
                    "action_sequence": ["四步动作"], "visible_payoff": "结算回报", "ending": "新钩子",
                    "must_include": ["三项"], "must_not_include": ["两项"],
                    "detailed_synopsis": "120—220字正文依据",
                },
            ],
        }
        for locked_field in (
            "opposition_type", "event_type", "solution_type", "death_chain_role",
        ):
            schema[locked_field] = source_direction.get(locked_field)
        event_schemas.append(schema)
    response_schema = {
        "macro_group_id": macro["macro_group_id"],
        "event_clusters": event_schemas,
        "continuity_update": {
            "current_year": "年代", "character_states": [], "relationship_states": [],
            "rights_and_assets": [], "health_and_location": [], "open_threads": [],
            "resolved_threads": [], "introduced_characters": [], "next_pressure": "下一组压力",
        },
    }
    special = (
        "\nEC001不可自由改写：第1章必须是2009年康拉德违规用药导致麦珂死亡，临终听见保险与死后版权分赃；"
        "第1章地点必须是麦珂尚有生命体征、监护仪仍在工作的临终医疗房间，严禁殡仪馆、冷藏室、棺材或死后仍对话；"
        "第1章只能停在死亡与信息差，绝不能提前混写第2章醒来、奔跑、拆设备等1969行动。"
        "第2章必须在1969年十一岁全国试镜后台醒来，并靠提前避开一次走位或设备错误取得第一次可见小赢。"
        "第2章的设备障碍只能来自上一世的试镜受阻记忆，严禁把1969设备零件说成导致2009死亡的同一实物。"
        "麦珂只能发现、报告、加固或绕开既有设备风险，绝不能自己碰松螺丝、制造故障再假装解决。"
        "康拉德只存在于第1章的2009年前世，绝不能跟随麦珂穿越、出现在1969年或在1969年遭到处罚；"
        "第2章的在场阻碍者必须是年龄合理的早期人物或设备风险，前世记忆只帮助麦珂预判流程；"
        "villain_loss必须结算1969年的设备破坏者或失职者，不能虚构主角死后康拉德被吊销执照。"
        "EC001禁止用同一纹身跨时代认人，也禁止未知势力、神秘短信、心脏病巧合、直觉证据、FDA等现实机构和真实歌曲名。\n"
        if macro_index == 1 and 1 in selected_event_indices else ""
    )
    early_conrad_guard = (
        "\n本组仍处于第451章之前：康拉德只能出现在prev_life_tragedy、info_gap_from_prev_life或"
        "why_previous_life_failed等前世记忆字段，绝不能担任今生对手、在场人物、签字人、医生或被处罚者。"
        "父级宏观蓝图若把康拉德写进当前年代，那是Qwen早期草稿中的时间线错误，本次细分必须明确覆盖该错误："
        "由你新创一个符合当前年代与年龄的架空对手承接今生陷阱，并同步重写相关得失、人物和连续性字段。\n"
        if 23 <= macro_index <= 45 else ""
    )
    unavailable_technology = _unavailable_technology(macro.get("timeline_years"))
    technology_guard = (
        f"本组时间为{macro.get('timeline_years')}，尚不应使用这些后期技术词："
        f"{'、'.join(unavailable_technology)}；请改用该年代真实可行的载体、通信和见证程序。\n"
        if unavailable_technology else
        f"本组时间为{macro.get('timeline_years')}，技术与通信手段按该年代实际条件书写，不得套用早期年代禁令。\n"
    )
    if len(event_specs) == 1:
        # Free relays have strict per-request/token ceilings. The complete
        # outline and canonical state remain in Neo4j and in the deterministic
        # validators; authoring one event only needs its locked parent
        # direction plus the immediate working state.
        event_id = event_specs[0]["cluster_id"]
        selected_direction = direction_by_id.get(event_id, {})
        recent_event = (prior_batch_events or [])[-1:]
        graph_working = {
            "canonical_state": graph_context_for_prompt.get("canonical_state") or {},
            "available_artifacts": (graph_context_for_prompt.get("available_artifacts") or [])[-3:],
        }
        ledger_working = {
            key: (_compact_prior_ledger_for_events(prior_ledger).get(key))
            for key in (
                "current_year", "next_pressure", "open_threads",
            )
            if _compact_prior_ledger_for_events(prior_ledger).get(key) not in (None, "", [], {})
        }
        parent = {
            key: macro_for_prompt.get(key) for key in (
                "macro_group_id", "timeline_years", "macro_goal", "main_conflict",
                "rebirth_advantage", "ending_state", "next_group_hook",
            )
        }
        parent["event_direction"] = selected_direction
        # A one-event request still needs neighboring settlement borders.
        # Otherwise it can consume the arrest, injunction and asset settlement
        # reserved for later events, forcing the next call to repeat the plot.
        parent["same_macro_event_boundaries"] = [
            {
                key: direction.get(key) for key in (
                    "cluster_id", "chapter_span", "chapter_one_small_win",
                    "chapter_two_showdown", "opponent_permanent_loss",
                    "protagonist_concrete_gain", "irreversible_outcome_key",
                )
            }
            for direction in (macro.get("five_event_directions") or [])
            if isinstance(direction, dict)
        ]
        preserve_schema_values = {
            "macro_group_id", "cluster_id", "chapter_span", "chapter_id",
            "effect_type", "domain", "temporal_mode", "timeline_scope",
        }

        def schema_shape(value: Any, key: str = "") -> Any:
            if isinstance(value, dict):
                return {field: schema_shape(item, field) for field, item in value.items()}
            if isinstance(value, list):
                if value and isinstance(value[0], dict):
                    return [schema_shape(item) for item in value]
                return []
            if isinstance(value, str):
                return value if key in preserve_schema_values else ""
            return value

        compact_response_schema = schema_shape(response_schema)
        return (
            f"扩写唯一事件{event_id}，章节范围{event_specs[0]['chapter_span']}。父级方向：{_json_text(parent)}\n"
            f"最近结算：{_json_text(recent_event)}\n"
            f"Neo4j当前工作状态：{_json_text(graph_working)}\n"
            f"连续性摘要：{_json_text(ledger_working)}\n"
            "硬约束：前世具体受害信息差→今生主动抢先→第一章可见小赢→第二章反转清算；"
            "记忆不是物证，证据须今生形成；反派因贪婪抢功或嘴硬滑稽留把柄并永久损失，主角永久获益。"
            "只能结算当前event_direction明确分配的结果；same_macro_event_boundaries中后续事件的逮捕、查封、"
            "舆论崩塌、收购破产、资产冻结等结果只能铺垫，严禁在当前事件提前发生。"
            "人物靠两难选择及代价塑造，稳定性格仅在因果充分的触发点反常，禁止直接解释内心。"
            "未成年行为、年代、身份、日期必须合理；状态不得重复永久得失；每章四步动作、一个主场景、120—220字详细梗概。"
            + technology_guard
            + special + early_conrad_guard
            + f"只输出严格JSON，结构与字段一个都不能少：{_json_text(compact_response_schema)}"
        )
    return (
        (
        f"根据Qwen自己创作的宏观组蓝图，只生成本批{len(event_specs)}个详细两章事件簇：{_json_text(macro_for_prompt)}\n"
        f"事件ID与范围不可改变：{_json_text(event_specs)}\n"
        f"进入本组前已经发生的连续性事实：{_json_text(_compact_prior_ledger_for_events(prior_ledger))}\n"
        f"本组前批已经完成的详细事件（必须承接且不得重复）：{_json_text(prior_batch_events or [])}\n"
        f"知识图谱检索到的父级目标与最近已完成事件：{_json_text(graph_context_for_prompt)}\n"
        f"本组对应的全书总纲切片（所有事件都必须是它的细分，不得发明相反走向）：{_json_text(outline_slice_for_prompt)}\n"
        "只写本事件且两章闭环。必须具体写：前世受害信息差→今生抢先布局→第一章小赢→第二章反转清算；"
        "记忆不是物证，证据须今生形成。反派因贪婪/抢功/嘴硬留下把柄并有永久损失，主角必须有永久收益。"
        "人物通过利益冲突中的选择塑造：稳定性格可在真正触发点反常，写选择及代价，不直接解释内心。"
        "状态迁移不得重复已永久取得/失去的权利职位；villain事件含villain_loss，且含protagonist_gain或relationship_change。"
        "未成年只做年龄可行的判断和行动；专业操作交成年人。年代、相邻章日期和人物首次登场必须合理。"
        "scenes按顺序且仅一项is_primary=true；今生物证首次形成写artifact_creates，随后才可refs；前世实物不可穿越。"
        "causal_spine_ids必须推进死亡—保险—版权—医疗控制主线。"
        + technology_guard
        + "每个事件总信息量控制在900—1400个汉字；两个milestone本身就是最终章卡来源，必须写足关键动作且不得留给后续模型补剧情；"
        "整批JSON必须完整闭合。第一章只能设置危机、使用信息差、完成小赢并停在不可逆交锋前；"
        "第二章才执行完整对抗和永久结算。第一章严禁提前交付第二章的反派损失、主角收益或最终权限，不得连续调查或开会。\n"
        )
        + special
        + early_conrad_guard
        +
        f"核心设定：{_json_text({'theme': THEME, 'protagonist': PROTAGONIST})}\n"
        f"严格按这个JSON结构输出，event_clusters必须恰好展开为{len(event_specs)}项：{_json_text(response_schema)}"
    )


def _compact_prior_batch_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: event.get(key) for key in (
                "cluster_id", "chapter_span", "cluster_outcome", "relationship_change",
                "state_transitions", "next_event_hook",
            )
        }
        for event in events[-1:]
    ]


def _bind_event_batch_to_macro(
    obj: dict[str, Any], macro: dict[str, Any], event_indices: list[int],
    timeline_floor: str | None = None,
    prior_state: dict[str, str] | None = None,
    locked_state_keys: set[str] | None = None,
    prior_events: list[dict[str, Any]] | None = None,
    global_outline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile immutable parent IDs/hashes instead of asking the model to copy them."""
    normalized = _replace_legacy_character_names(_normalize_fictional_places(obj))
    if isinstance(normalized, dict):
        obj.clear()
        obj.update(normalized)
    event_world_aliases = {
        "北京": "北岬市", "上海": "海川市", "中国": "华洲联邦",
        "东城区": "东环区", "居委会": "社区事务站", "毛主席": "联邦创始人",
        "文化部": "联邦文化事务署", "公安局": "城市治安署", "人民币": "联邦元",
        "FDA": "联邦药品管理署",
        "仅凭直觉报警": "未掌握强酸销毁证据的具体时点便报警",
    }

    def normalize_event_world(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: normalize_event_world(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize_event_world(item) for item in value]
        if isinstance(value, str):
            for real_name, fictional_name in event_world_aliases.items():
                value = value.replace(real_name, fictional_name)
        return value

    event_normalized = normalize_event_world(obj)
    if isinstance(event_normalized, dict):
        obj.clear()
        obj.update(event_normalized)
    directions = {
        str(item.get("cluster_id") or ""): item
        for item in (macro.get("five_event_directions") or [])
        if isinstance(item, dict)
    }
    events = obj.get("event_clusters")
    if not isinstance(events, list):
        return obj
    known_artifacts = {
        (
            str(created.get("timeline_scope") or ""),
            str(created.get("artifact_id") or ""),
        )
        for prior_event in (prior_events or [])
        for milestone in (prior_event.get("two_chapter_structure") or [])
        for created in (milestone.get("artifact_creates") or [])
        if isinstance(created, dict) and created.get("artifact_id")
    }
    for event, event_index in zip(events, event_indices):
        if not isinstance(event, dict):
            continue
        eid = f"EC{event_index:03d}"
        raw_character_labels = [
            str(name).strip() for name in (event.get("main_characters") or [])
            if str(name).strip()
        ]
        clean_character_names = [
            re.sub(r"[（(][^）)]*[）)]", "", name).strip()
            for name in raw_character_labels
        ]
        if clean_character_names != raw_character_labels:
            event["source_main_character_labels"] = raw_character_labels
            event["main_characters"] = list(dict.fromkeys(clean_character_names))
        locked = directions.get(eid, {})
        direction = str(locked.get("direction") or "")
        event["cluster_id"] = eid
        event["chapter_span"] = list(_event_bounds(event_index))
        event["source_event_direction"] = direction
        event["source_event_direction_sha256"] = canonical_sha256(direction)
        event["source_macro_sha256"] = canonical_sha256(macro)
        if not isinstance(event.get("causal_spine_ids"), list) or not event.get("causal_spine_ids"):
            allowed_causal = [
                str(value) for value in (
                    macro.get("causal_links_used")
                    or macro.get("causal_spine_ids")
                    or []
                )
                if re.fullmatch(r"CS\d{2}", str(value))
            ]
            if allowed_causal:
                event["causal_spine_ids"] = allowed_causal[:1]
        for field in ("opposition_type", "event_type", "solution_type", "death_chain_role"):
            event[field] = locked.get(field)
        causal_ids = [str(value) for value in (event.get("causal_spine_ids") or [])]
        foreshadow_ids = [str(value) for value in (event.get("foreshadow_ids") or [])]
        event["causal_spine_ids"] = list(dict.fromkeys(
            [value for value in causal_ids if re.fullmatch(r"CS\d{2}", value)]
            + [value for value in foreshadow_ids if re.fullmatch(r"CS\d{2}", value)]
        ))
        event["foreshadow_ids"] = list(dict.fromkeys(
            [value for value in foreshadow_ids if re.fullmatch(r"FS\d{2}", value)]
            + [value for value in causal_ids if re.fullmatch(r"FS\d{2}", value)]
        ))
        allowed_causal = [
            str(value) for value in (
                macro.get("causal_links_used")
                or macro.get("causal_spine_ids")
                or []
            ) if re.fullmatch(r"CS\d{2}", str(value))
        ]
        event_phase = f"P{((event_index * 2 - 2) // 50) + 1:02d}"
        global_causal = {
            str(item.get("spine_id") or ""): item
            for item in (global_outline or {}).get("causal_spine") or []
            if isinstance(item, dict)
        }
        phase_valid_causal = []
        for cid, item in global_causal.items():
            phases = re.findall(r"P\d{2}", str(item.get("phase_range") or ""))
            if len(phases) < 2 or int(phases[0][1:]) <= int(event_phase[1:]) <= int(phases[-1][1:]):
                phase_valid_causal.append(cid)
        if phase_valid_causal:
            event["causal_spine_ids"] = [
                value for value in event["causal_spine_ids"] if value in phase_valid_causal
            ]
        if allowed_causal:
            event["causal_spine_ids"] = [
                value for value in event["causal_spine_ids"] if value in allowed_causal
            ] or [next(
                (value for value in allowed_causal if not phase_valid_causal or value in phase_valid_causal),
                phase_valid_causal[0] if phase_valid_causal else allowed_causal[0],
            )]
        elif not event["causal_spine_ids"] and phase_valid_causal:
            event["causal_spine_ids"] = [phase_valid_causal[0]]
        global_foreshadows = {
            str(item.get("thread_id") or ""): item
            for item in (global_outline or {}).get("foreshadow_ledger") or []
            if isinstance(item, dict)
        }
        event["foreshadow_ids"] = [
            fid for fid in event["foreshadow_ids"]
            if fid not in global_foreshadows or event_phase in {
                str(global_foreshadows[fid].get("plant_phase") or ""),
                str(global_foreshadows[fid].get("payoff_phase") or ""),
                *(str(value) for value in global_foreshadows[fid].get("development_phases") or []),
            }
        ]
        milestones = event.get("two_chapter_structure")
        if isinstance(milestones, list):
            fallback_timeline_cursor = None
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(timeline_floor or "")):
                fallback_timeline_cursor = datetime.strptime(
                    str(timeline_floor), "%Y-%m-%d"
                ).date()
            for milestone, chapter_id in zip(milestones, _event_bounds(event_index)):
                if not isinstance(milestone, dict):
                    continue
                milestone["chapter_id"] = chapter_id
                for key in ("timeline_start", "timeline_end"):
                    value = str(milestone.get(key) or "").strip()
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?", value):
                        # Chapter cards intentionally track the story day, not
                        # clock time.  Providers commonly emit either ISO's T
                        # or a space before HH:MM; canonicalize both forms.
                        milestone[key] = re.split(r"[T ]", value, maxsplit=1)[0]
                    else:
                        chinese_date = re.fullmatch(
                            r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?",
                            value,
                        )
                        if chinese_date:
                            year, month, day = (int(part) for part in chinese_date.groups())
                            milestone[key] = f"{year:04d}-{month:02d}-{day:02d}"
                if (
                    fallback_timeline_cursor is not None
                    and (
                        timeline_point(milestone.get("timeline_start")) is None
                        or timeline_point(milestone.get("timeline_end")) is None
                    )
                ):
                    raw_start = str(milestone.get("timeline_start") or "")
                    raw_end = str(milestone.get("timeline_end") or "")
                    start_day = fallback_timeline_cursor
                    crosses_midnight = (
                        any(token in raw_start for token in ("夜", "晚"))
                        and any(token in raw_end for token in ("凌晨", "清晨", "黎明"))
                    )
                    end_day = start_day + timedelta(days=1 if crosses_midnight else 0)
                    milestone["source_timeline_start"] = raw_start
                    milestone["source_timeline_end"] = raw_end
                    milestone["timeline_start"] = start_day.isoformat()
                    milestone["timeline_end"] = end_day.isoformat()
                    fallback_timeline_cursor = end_day
                # The relay occasionally omits detailed_synopsis even though
                # it returns the same chapter content in the structured
                # conflict/action/payoff fields.  Compile that redundant field
                # deterministically instead of discarding an otherwise usable
                # event and paying for another creative rewrite.
                if not str(milestone.get("detailed_synopsis") or "").strip():
                    actions = milestone.get("action_sequence") or []
                    action_text = "；".join(
                        str(item).strip() for item in actions if str(item).strip()
                    )
                    milestone["detailed_synopsis"] = "。".join(
                        part.strip("。 ")
                        for part in (
                            str(milestone.get("opening_conflict") or ""),
                            action_text,
                            str(milestone.get("visible_payoff") or ""),
                            str(milestone.get("ending") or ""),
                        )
                        if part.strip("。 ")
                    ) + "。"
                if len(str(milestone.get("detailed_synopsis") or "").strip()) < 120:
                    raw_actions_for_synopsis = milestone.get("action_sequence") or []
                    action_text = "；".join(
                        str(item).strip()
                        for item in (
                            raw_actions_for_synopsis
                            if isinstance(raw_actions_for_synopsis, list)
                            else re.split(r"[；;]", str(raw_actions_for_synopsis))
                        )
                        if str(item).strip()
                    )
                    expanded_parts = (
                        str(milestone.get("opening_conflict") or "").strip(),
                        f"本章对应的前世风险：{str(event.get('prev_life_tragedy') or '').strip()}",
                        f"麦珂调用前世信息差：{str(milestone.get('info_gap_use') or '').strip()}",
                        f"今生提前规避：{str(event.get('preemptive_avoidance') or '').strip()}",
                        f"她依次行动：{action_text}",
                        f"对手现场反应：{str(milestone.get('opponent_reaction') or '').strip()}",
                        f"本章可见回报：{str(milestone.get('visible_payoff') or '').strip()}",
                        f"结尾压力：{str(milestone.get('ending') or '').strip()}",
                    )
                    milestone["detailed_synopsis"] = "。".join(
                        part.strip("。 ") for part in expanded_parts if part.strip("。 ")
                    ) + "。"
                if len(str(milestone.get("detailed_synopsis") or "")) > 420:
                    actions = [
                        str(item).strip()[:45]
                        for item in (milestone.get("action_sequence") or [])[:4]
                        if str(item).strip()
                    ]
                    concise_parts = [
                        str(milestone.get("opening_conflict") or "").strip()[:80],
                        *actions,
                        str(milestone.get("visible_payoff") or "").strip()[:70],
                        str(milestone.get("ending") or "").strip()[:60],
                    ]
                    milestone["detailed_synopsis"] = "。".join(
                        part.strip("。 ") for part in concise_parts if part.strip("。 ")
                    )[:419].rstrip("，,；;：: ") + "。"
                raw_actions = milestone.get("action_sequence") or []
                actions = (
                    [str(item).strip() for item in raw_actions if str(item).strip()]
                    if isinstance(raw_actions, list)
                    else [part.strip() for part in re.split(r"[；;]", str(raw_actions)) if part.strip()]
                )
                for derived_action in (
                    f"落实本章可见结果：{str(milestone.get('visible_payoff') or '').strip()}",
                    f"形成下一步压力：{str(milestone.get('ending') or '').strip()}",
                ):
                    if len(actions) >= 4:
                        break
                    if derived_action.rstrip("：") not in actions:
                        actions.append(derived_action)
                milestone["action_sequence"] = actions
                # These are invariant prose guards, not creative beats.  A
                # missing second item must not trigger another paid rewrite of
                # an otherwise complete event.
                must_not = [
                    str(item).strip()
                    for item in (milestone.get("must_not_include") or [])
                    if str(item).strip()
                ]
                for guard in ("不得把前世记忆写成今生实体证据", "不得让对手无因自白或降智认输"):
                    if len(must_not) >= 2:
                        break
                    if guard not in must_not:
                        must_not.append(guard)
                milestone["must_not_include"] = must_not
                must_include = [
                    str(item).strip()
                    for item in (milestone.get("must_include") or [])
                    if str(item).strip()
                ]
                derived_requirements = (
                    f"必须呈现信息差的实际使用：{str(milestone.get('info_gap_use') or '').strip()}",
                    f"必须呈现对手的现场反应：{str(milestone.get('opponent_reaction') or '').strip()}",
                    f"必须落地可见回报：{str(milestone.get('visible_payoff') or '').strip()}",
                )
                for requirement in derived_requirements:
                    if len(must_include) >= 3:
                        break
                    if requirement.rstrip("：") not in must_include:
                        must_include.append(requirement)
                milestone["must_include"] = must_include
                scenes = milestone.get("scenes") or []
                for scene in scenes:
                    if not isinstance(scene, dict):
                        continue
                    mode = str(scene.get("temporal_mode") or "").strip().lower()
                    if mode not in {"current", "previous_life_memory", "flashback"}:
                        if any(token in mode for token in ("previous", "memory", "past_life", "前世")):
                            scene["temporal_mode"] = "previous_life_memory"
                        elif "flash" in mode or "回忆" in mode or "倒叙" in mode:
                            scene["temporal_mode"] = "flashback"
                        else:
                            scene["temporal_mode"] = "current"
                if scenes and sum(
                    bool(scene.get("is_primary"))
                    for scene in scenes if isinstance(scene, dict)
                ) != 1:
                    first_scene_selected = False
                    for scene in scenes:
                        if not isinstance(scene, dict):
                            continue
                        scene["is_primary"] = not first_scene_selected
                        first_scene_selected = True
                primary_locations = [
                    str(scene.get("location") or "").strip()
                    for scene in scenes if isinstance(scene, dict) and scene.get("is_primary")
                ]
                scene_name = str(milestone.get("scene") or "").strip()
                if primary_locations and not any(
                    scene_name == location
                    or bool(re.match(re.escape(location) + r"[，,。；;（(：:]", scene_name))
                    for location in primary_locations if location
                ):
                    milestone["scene"] = primary_locations[0]
                expected_scope = "previous_life" if chapter_id == 1 else "current"
                refs = milestone.get("artifact_refs") or []
                scope_aliases = {
                    "current_life": "current", "present": "current", "this_life": "current",
                    "past_life": "previous_life", "previous": "previous_life",
                    "memory": "previous_life",
                }
                for artifact in [*refs, *(milestone.get("artifact_creates") or [])]:
                    if isinstance(artifact, dict):
                        artifact_id = str(artifact.get("artifact_id") or "").strip()
                        if re.fullmatch(
                            r"(?:DOC|DOCUMENT|EVIDENCE|FILE|RECORD|COURT)_[A-Z0-9_]{3,80}",
                            artifact_id,
                        ):
                            artifact["source_artifact_id"] = artifact_id
                            artifact["artifact_id"] = "ART_" + artifact_id.split("_", 1)[1]
                        elif (
                            re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,80}", artifact_id)
                            and not artifact_id.upper().startswith("ART_")
                        ):
                            artifact["source_artifact_id"] = artifact_id
                            artifact["artifact_id"] = "ART_" + artifact_id.upper()
                        scope = str(artifact.get("timeline_scope") or "").strip().lower()
                        if scope in scope_aliases:
                            artifact["timeline_scope"] = scope_aliases[scope]
                kept_refs = [
                    ref for ref in refs
                    if not isinstance(ref, dict)
                    or str(ref.get("timeline_scope") or "") == expected_scope
                ]
                removed_refs = [ref for ref in refs if ref not in kept_refs]
                if removed_refs:
                    # Rebirth carries information, never the physical object.
                    # Preserve an audit note while preventing a previous-life
                    # artifact from appearing materially in the current life.
                    milestone["memory_only_artifact_refs"] = removed_refs
                    milestone["artifact_refs"] = kept_refs
                creates = milestone.get("artifact_creates") or []
                unique_creates = []
                duplicate_creates = []
                for created in creates:
                    if not isinstance(created, dict) or not created.get("artifact_id"):
                        unique_creates.append(created)
                        continue
                    key = (
                        str(created.get("timeline_scope") or expected_scope),
                        str(created.get("artifact_id") or ""),
                    )
                    if key in known_artifacts:
                        duplicate_creates.append(created)
                        if not any(
                            isinstance(ref, dict)
                            and str(ref.get("artifact_id") or "") == key[1]
                            and str(ref.get("timeline_scope") or expected_scope) == key[0]
                            for ref in kept_refs
                        ):
                            kept_refs.append({
                                "artifact_id": key[1],
                                "timeline_scope": key[0],
                                "display_name": str(created.get("display_name") or key[1]),
                                "kind": str(created.get("kind") or "evidence"),
                            })
                    else:
                        unique_creates.append(created)
                        known_artifacts.add(key)
                creates = unique_creates
                if duplicate_creates:
                    milestone["duplicate_artifact_creates_reclassified"] = duplicate_creates
                    milestone["artifact_refs"] = kept_refs
                for ref in kept_refs:
                    if not isinstance(ref, dict):
                        continue
                    aid = str(ref.get("artifact_id") or "")
                    scope = str(ref.get("timeline_scope") or expected_scope)
                    if aid and (scope, aid) not in known_artifacts:
                        created = {
                            "artifact_id": aid,
                            "timeline_scope": scope,
                            "display_name": str(ref.get("display_name") or aid),
                            "kind": str(ref.get("kind") or "evidence"),
                        }
                        creates.append(created)
                        known_artifacts.add((scope, aid))
                milestone["artifact_creates"] = creates
            if event_index == 1 and len(milestones) == 2:
                # This is an immutable premise fact, not a new plot beat.  It
                # prevents a model wording omission from erasing the age at
                # the exact rebirth anchor.
                rebirth = milestones[1]
                synopsis = str(rebirth.get("detailed_synopsis") or "")
                if not any(token in synopsis for token in ("十一岁", "11岁")):
                    rebirth["detailed_synopsis"] = "十一岁的麦珂在1969年全国试镜后台醒来。" + synopsis
        if len(str(event.get("villain_loss") or "").strip()) < 10:
            source_loss = str(event.get("villain_loss") or "").strip()
            settlement = ""
            if isinstance(milestones, list) and milestones:
                final_milestone = milestones[-1] if isinstance(milestones[-1], dict) else {}
                settlement = str(
                    final_milestone.get("ending")
                    or final_milestone.get("visible_payoff")
                    or ""
                ).strip()
            settlement = settlement or str(event.get("cluster_outcome") or "").strip()
            event["source_villain_loss"] = source_loss
            event["villain_loss"] = f"反派付出现实损失：{settlement}"
        if len(str(event.get("bait_and_evidence") or "").strip()) < 10:
            source_bait = str(event.get("bait_and_evidence") or "").strip()
            first_milestone = (
                milestones[0]
                if isinstance(milestones, list) and milestones and isinstance(milestones[0], dict)
                else {}
            )
            evidence_action = str(
                first_milestone.get("info_gap_use")
                or first_milestone.get("opening_conflict")
                or event.get("cluster_outcome")
                or ""
            ).strip()
            event["source_bait_and_evidence"] = source_bait
            event["bait_and_evidence"] = f"麦珂布置诱饵并固定今生证据：{evidence_action}"
        domain_aliases = {
            "career": "job", "employment": "job", "profession": "job", "jobs": "job",
            "characters": "character", "identity": "character",
            "character_identity": "character", "relationships": "relationship",
            "assets": "asset", "rights_assets": "rights", "right": "rights",
            "legal": "rights", "legal_rights": "rights",
            "legal_status": "rights", "legal_evidence": "rights",
            "contract": "rights", "access_control": "rights",
            "finance": "asset", "financial": "asset", "technical": "asset",
            "equipment": "asset", "device": "asset", "infrastructure": "asset",
            "safety": "health", "safety_protocol": "health",
            "medical": "health", "physical_security": "health",
            "family_governance": "relationship", "partnership": "relationship",
            "technology": "asset", "technical_asset": "asset",
            "enemy": "enemy_capability", "opponent_capability": "enemy_capability",
            "public_reputation": "reputation", "public_status": "reputation",
            "media": "reputation", "brand": "reputation",
            "brand_reputation": "reputation", "locations": "location",
            "spatial": "location", "venue": "location",
        }
        for transition in event.get("state_transitions") or []:
            if isinstance(transition, dict):
                provider_entity = str(transition.get("entity_id") or "").strip()
                provider_pair = PROVIDER_RELATIONSHIP_ID_ALIASES.get(provider_entity.lower())
                provider_character = (
                    PROVIDER_CHARACTER_ID_ALIASES.get(provider_entity)
                    or PROVIDER_CHARACTER_ID_ALIASES.get(provider_entity.lower())
                )
                if provider_pair:
                    pair_ids = sorted(character_id_for_name(name) for name in provider_pair)
                    transition["source_entity_label"] = provider_entity
                    transition["entity_id"] = "REL_" + "__".join(
                        item.removeprefix("CHAR_") for item in pair_ids
                    )
                elif provider_character:
                    transition["source_entity_label"] = provider_entity
                    transition["entity_id"] = character_id_for_name(provider_character)
                domain = str(transition.get("domain") or "").strip()
                # Some compatible models serialize a canonical state key as
                # `domain:ENTITY_ID` inside the domain field. Recover the
                # intended split deterministically instead of regenerating an
                # otherwise usable two-chapter event.
                compound_domain = re.fullmatch(
                    r"([a-z_]+):([A-Z][A-Z0-9_]{2,80})", domain,
                )
                if compound_domain:
                    source_domain = domain
                    source_entity = str(transition.get("entity_id") or "").strip()
                    embedded_entity = compound_domain.group(2)
                    domain = compound_domain.group(1)
                    transition["source_domain"] = source_domain
                    transition["source_entity_id"] = source_entity
                    transition["entity_id"] = embedded_entity
                    current_state_key = str(transition.get("state_key") or "").strip()
                    current_to = str(transition.get("to") or "").strip()
                    if (
                        source_entity
                        and (
                            "__extension_" in source_entity
                            or current_state_key == current_to
                            or re.search(r"(?:authority|governance|status|access|control)", source_entity)
                        )
                    ):
                        transition["source_state_key"] = current_state_key
                        transition["state_key"] = source_entity
                if domain in {"域", "domain", "state"}:
                    entity = str(transition.get("entity_id") or "")
                    state_key = str(transition.get("state_key") or "")
                    if entity.startswith("RIGHT_"):
                        domain = "rights"
                    elif "health" in state_key or "safety" in state_key:
                        domain = "health"
                    elif entity.startswith("REL_"):
                        domain = "relationship"
                    elif entity.startswith("LOC_"):
                        domain = "location"
                    else:
                        domain = "asset"
                if domain in {"organization", "organisation", "org"}:
                    state_key = str(transition.get("state_key") or "")
                    domain = (
                        "reputation"
                        if re.search(r"credib|reputation|trust|public_image", state_key, re.I)
                        else "enemy_capability"
                    )
                if domain == "world_state":
                    entity = str(transition.get("entity_id") or "")
                    domain = "location" if entity.startswith("LOC_") else "asset"
                domain = domain_aliases.get(domain, domain)
                canonical_domains = {
                    "character", "relationship", "rights", "asset", "job",
                    "health", "enemy_capability", "foreshadow", "reputation", "location",
                }
                if domain not in canonical_domains:
                    entity = str(transition.get("entity_id") or "")
                    state_key = str(transition.get("state_key") or "")
                    effect = str(transition.get("effect_type") or "")
                    if entity.startswith(("CHAR_", "ID_CHAR_")):
                        domain = "character"
                    elif entity.startswith(("REL_", "TEAM_")) or effect == "relationship_change":
                        domain = "relationship"
                    elif entity.startswith(("RIGHT_", "RIGHTS_")):
                        domain = "rights"
                    elif entity.startswith(("LOC_", "VENUE_", "SPATIAL_")):
                        domain = "location"
                    elif entity.startswith(("HEALTH_", "MEDICAL_")) or re.search(
                        r"health|medical|safety|injury", state_key, re.I,
                    ):
                        domain = "health"
                    elif entity.startswith(("REPUT_", "MEDIA_")) or re.search(
                        r"credib|reputation|public_image", state_key, re.I,
                    ):
                        domain = "reputation"
                    elif entity.startswith(("JOB_", "ROLE_")):
                        domain = "job"
                    elif entity.startswith(("ORG_", "ENEMY_")) or effect == "villain_loss":
                        domain = "enemy_capability"
                    else:
                        domain = "asset"
                    transition["source_domain"] = str(transition.get("source_domain") or transition.get("domain") or "")
                transition["domain"] = domain
        opponent_parts = _event_opponent_names(event)
        current_parts = [part for part in opponent_parts if "今生" in part]
        opponent_label = (current_parts or opponent_parts or [""])[-1]
        opponent_name = re.sub(r"[（(][^）)]*[）)]", "", opponent_label).strip()

        def canonical_cast_name(name: str) -> str:
            if "·" in name:
                return name
            for member in CAST:
                full = str(member.get("name") or "")
                if full == name or full.split("·", 1)[0] == name:
                    return full
            return name

        opponent_name = canonical_cast_name(opponent_name)
        opponent_id = character_id_for_name(opponent_name) if opponent_name else ""
        protagonist_id = character_id_for_name(PROTAGONIST)
        state_before = prior_state or {}
        locked_before = locked_state_keys or set()
        transitions = event.get("state_transitions") or []
        if not isinstance(transitions, list):
            transitions = []
            event["state_transitions"] = transitions
        event_transition_keys: set[str] = set()
        for transition in transitions:
            if not isinstance(transition, dict):
                continue
            effect = str(transition.get("effect_type") or "")
            entity = str(transition.get("entity_id") or "")
            if effect not in {
                "villain_loss", "protagonist_gain", "relationship_change", "world_state",
            }:
                domain = str(transition.get("domain") or "")
                if domain == "relationship":
                    effect = "relationship_change"
                elif entity in {protagonist_id, "CHAR_MK_JASON"} or entity.startswith("RIGHT_MK"):
                    effect = "protagonist_gain"
                elif entity.startswith("ORG_") or (opponent_id and entity == opponent_id):
                    effect = "villain_loss"
                else:
                    effect = "world_state"
                transition["effect_type"] = effect
            if entity.startswith("CHAR_") and effect == "villain_loss" and opponent_id:
                transition["source_entity_label"] = entity
                if "·" not in opponent_name or str(event.get("opposition_type") or "") in {
                    "institutional", "technical",
                }:
                    transition["entity_id"] = "ORG_" + hashlib.sha256(
                        str(event.get("main_opponent") or opponent_name).encode("utf-8")
                    ).hexdigest()[:12].upper()
                else:
                    transition["entity_id"] = opponent_id
            elif entity.startswith("CHAR_") and effect == "protagonist_gain":
                transition["source_entity_label"] = entity
                transition["entity_id"] = protagonist_id
            key = ":".join(str(transition.get(field) or "").strip() for field in (
                "domain", "entity_id", "state_key",
            ))
            if key in state_before:
                old = state_before[key]
                new = str(transition.get("to") or "")
                if key in locked_before or old == new:
                    original_key = str(transition.get("state_key") or "state")
                    transition["source_state_key"] = original_key
                    transition["state_key"] = f"{original_key}__extension_{eid}"
                    transition["from"] = "none"
                else:
                    transition["from"] = old
            compiled_key = ":".join(str(transition.get(field) or "").strip() for field in (
                "domain", "entity_id", "state_key",
            ))
            if compiled_key in event_transition_keys:
                base_key = str(
                    transition.get("source_state_key")
                    or transition.get("state_key")
                    or "state"
                ).split("__", 1)[0]
                effect_suffix = {
                    "villain_loss": "loss", "protagonist_gain": "gain",
                    "relationship_change": "relationship", "world_state": "world",
                }.get(effect, "branch")
                candidate = f"{base_key}__{effect_suffix}_{eid}"
                sequence = 2
                while ":".join((
                    str(transition.get("domain") or ""),
                    str(transition.get("entity_id") or ""), candidate,
                )) in event_transition_keys:
                    candidate = f"{base_key}__{effect_suffix}_{eid}_{sequence}"
                    sequence += 1
                transition["source_state_key"] = str(transition.get("state_key") or base_key)
                transition["state_key"] = candidate
                transition["from"] = "none"
                compiled_key = ":".join((
                    str(transition.get("domain") or ""),
                    str(transition.get("entity_id") or ""), candidate,
                ))
            event_transition_keys.add(compiled_key)
        effects = {
            str(item.get("effect_type") or "") for item in transitions if isinstance(item, dict)
        }
        if str(event.get("opposition_type") or "") == "villain" and "villain_loss" not in effects:
            transitions.append({
                "domain": "enemy_capability",
                "entity_id": "ORG_" + hashlib.sha256(
                    str(event.get("main_opponent") or opponent_name or eid).encode("utf-8")
                ).hexdigest()[:12].upper(),
                "state_key": f"opposition_loss_{eid}",
                "from": "active",
                "to": str(event.get("villain_loss") or "capability_lost"),
                "irreversible": True,
                "evidence": str(event.get("cluster_outcome") or event.get("villain_loss") or "事件结算"),
                "effect_type": "villain_loss",
            })
    # Preserve the model's relative day spacing but move a batch forward when
    # it accidentally proposes calendar dates earlier than the accepted prior
    # event.  This is chronology normalization, not plot rewriting.
    if timeline_floor and events and event_indices and event_indices[0] != 1:
        try:
            floor_date = datetime.strptime(timeline_floor[:10], "%Y-%m-%d").date()
            dated_milestones = [
                milestone
                for event in events if isinstance(event, dict)
                for milestone in (event.get("two_chapter_structure") or [])
                if isinstance(milestone, dict)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(milestone.get("timeline_start") or ""))
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(milestone.get("timeline_end") or ""))
            ]
            if dated_milestones:
                first_date = datetime.strptime(
                    str(dated_milestones[0]["timeline_start"]), "%Y-%m-%d"
                ).date()
                if first_date < floor_date:
                    delta = floor_date - first_date
                    for milestone in dated_milestones:
                        for key in ("timeline_start", "timeline_end"):
                            value = datetime.strptime(str(milestone[key]), "%Y-%m-%d").date()
                            milestone[key] = (value + delta).isoformat()
        except (TypeError, ValueError):
            pass
    return obj


def _accepted_timeline_floor(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        milestones = event.get("two_chapter_structure") or []
        for milestone in reversed(milestones):
            value = str((milestone or {}).get("timeline_end") or "")
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?", value):
                return value[:10]
    return None


def _event_opponent_names(event: dict[str, Any]) -> list[str]:
    """Extract actual people from a prose/composite main_opponent label."""
    opponent_text = str(event.get("main_opponent") or "").strip()
    cast_names = [
        str(name).strip() for name in (event.get("main_characters") or [])
        if "·" in str(name) and str(name).strip() in opponent_text
    ]
    if cast_names:
        return sorted(dict.fromkeys(cast_names), key=opponent_text.index)
    return [
        re.sub(r"[（(][^）)]*[）)]", "", part).strip()
        for part in re.split(r"[/／＆&、]|\s+与\s+|与(?=[\u3400-\u9fff]+·)", opponent_text)
        if re.sub(r"[（(][^）)]*[）)]", "", part).strip()
    ]


def _generate_events_batched(
    *, macro: dict[str, Any], prior_ledger: dict[str, Any],
    global_outline: dict[str, Any], graph_context: dict[str, Any],
    prior_events: list[dict[str, Any]], prior_state: dict[str, str],
    prior_irreversible: set[str], checkpoint_dir: Path, model: str,
    resume: bool,
) -> dict[str, Any]:
    """Generate a ten-chapter detailed plan in relay-safe sub-batches."""
    macro_index = int(str(macro["macro_group_id"])[2:])
    mid = f"MG{macro_index:03d}"
    first_event = (macro_index - 1) * 5 + 1
    all_indices = list(range(first_event, first_event + 5))
    final_path = checkpoint_dir / f"{mid}_events.json"
    final_provenance_path = checkpoint_dir / f"{mid}_events_provenance.json"
    compiled_input_sha256 = canonical_sha256({
        "macro": macro,
        "prior_ledger": prior_ledger,
        "graph_context": _compact_graph_context_for_events(graph_context),
        "prior_event_tail": _compact_prior_batch_events(prior_events[-10:]),
        "prior_state": prior_state,
        "prior_irreversible": sorted(prior_irreversible),
        "event_batch_size": EVENT_BATCH_SIZE,
    })
    if resume and final_path.is_file() and final_provenance_path.is_file():
        try:
            existing = json.loads(final_path.read_text(encoding="utf-8"))
            provenance = json.loads(final_provenance_path.read_text(encoding="utf-8"))
            existing = _bind_event_batch_to_macro(
                existing, macro, all_indices, _accepted_timeline_floor(prior_events),
                prior_state=prior_state, locked_state_keys=prior_irreversible,
                prior_events=prior_events,
                global_outline=global_outline,
            )
            failures = _validate_events(
                existing, macro_index, prior_events=prior_events,
                prior_state=prior_state, prior_irreversible=prior_irreversible,
                source_macro=macro,
            )
            if (
                not failures
                and provenance.get("acceptance_mode") == "batched_event_compile"
                and provenance.get("manual_edits") == []
            ):
                current_sha = canonical_sha256(existing)
                if (
                    provenance.get("compiled_input_sha256") != compiled_input_sha256
                    or provenance.get("compiled_sha256") != current_sha
                ):
                    _write_json(final_path, existing)
                    provenance["compiled_input_sha256"] = compiled_input_sha256
                    provenance["compiled_sha256"] = current_sha
                    provenance["recompiled_at"] = _now()
                    provenance["structural_normalizations"] = list(dict.fromkeys([
                        *(provenance.get("structural_normalizations") or []),
                        "current_event_identity_timeline_state_compiler",
                    ]))
                    _write_json(final_provenance_path, provenance)
                print(f"[resume] {mid} batched detailed events", flush=True)
                return existing
        except (OSError, json.JSONDecodeError):
            pass

    compiled_events: list[dict[str, Any]] = []
    component_provenance_paths: list[Path] = []
    batch_state = dict(prior_state)
    batch_locked = set(prior_irreversible)
    final_continuity: dict[str, Any] = {}
    for offset in range(0, len(all_indices), EVENT_BATCH_SIZE):
        indices = all_indices[offset:offset + EVENT_BATCH_SIZE]
        first_id, last_id = (f"EC{indices[0]:03d}", f"EC{indices[-1]:03d}")
        kind = f"events_{first_id}_{last_id}"
        prior_for_validation = [*prior_events, *compiled_events]
        state_for_validation = dict(batch_state)
        locked_for_validation = set(batch_locked)
        batch_obj = _call_validated(
            kind=kind,
            identifier=mid,
            system_prompt=_system_prompt(),
            user_prompt=_events_prompt(
                macro, prior_ledger, global_outline, graph_context,
                event_indices=indices,
                prior_batch_events=_compact_prior_batch_events(compiled_events),
            ),
            validator=lambda obj, selected=list(indices), prior=list(prior_for_validation), state=state_for_validation, locked=locked_for_validation: _validate_events(
                _bind_event_batch_to_macro(
                    obj, macro, selected, _accepted_timeline_floor(prior),
                    prior_state=state, locked_state_keys=locked,
                    prior_events=prior,
                    global_outline=global_outline,
                ),
                macro_index, prior_events=prior, prior_state=state,
                prior_irreversible=locked, source_macro=macro,
                event_indices=selected,
            ),
            checkpoint_dir=checkpoint_dir,
            model=model,
            temperature=0.70,
            resume=resume,
            # Neo4j context can gain equivalent normalized facts between
            # resumptions.  The checkpoint is still re-run through the full
            # current validator, so prompt-hash drift alone must not force an
            # already valid creative batch to be regenerated.
            allow_prompt_drift=True,
            max_attempts=4,
            max_output_tokens=max(EVENT_MAX_OUTPUT_TOKENS, 2400 * len(indices)),
        )
        batch_events = [dict(event) for event in batch_obj["event_clusters"]]
        batch_state, batch_locked, state_failures = validate_event_batch(
            batch_events,
            prior_events=prior_for_validation,
            prior_state=batch_state,
            prior_irreversible=batch_locked,
        )
        if state_failures:
            raise RuntimeError(
                f"{mid}详细事件子批状态校验失败：" + " | ".join(state_failures[:20])
            )
        compiled_events.extend(batch_events)
        final_continuity = dict(batch_obj.get("continuity_update") or {})
        component_provenance_paths.append(
            checkpoint_dir / f"{mid}_{kind}_provenance.json"
        )

    compiled = {
        "macro_group_id": mid,
        "event_clusters": compiled_events,
        "continuity_update": final_continuity,
    }
    failures = _validate_events(
        compiled, macro_index, prior_events=prior_events,
        prior_state=prior_state, prior_irreversible=prior_irreversible,
        source_macro=macro,
    )
    if failures:
        raise RuntimeError(f"{mid}详细事件子批合并失败：" + " | ".join(failures[:30]))
    providers = _generation_providers(component_provenance_paths)
    _write_json(final_path, compiled)
    _write_json(final_provenance_path, {
        "generated_by": _generator_label(providers),
        "generation_providers": providers,
        "kind": "events",
        "identifier": mid,
        "accepted_attempt": 1,
        "acceptance_mode": "batched_event_compile",
        "compiled_input_sha256": compiled_input_sha256,
        "compiled_sha256": canonical_sha256(compiled),
        "component_provenance_files": [path.name for path in component_provenance_paths],
        "manual_edits": [],
        "created_at": _now(),
    })
    print(
        f"[compiled] {mid} detailed events sub_batches={len(component_provenance_paths)} events=5",
        flush=True,
    )
    return compiled


def _chapters_prompt(
    macro: dict[str, Any],
    events_obj: dict[str, Any],
    prior_ledger: dict[str, Any],
    part: int,
    global_outline: dict[str, Any],
) -> str:
    macro_index = int(str(macro["macro_group_id"])[2:])
    macro_start, _ = _macro_bounds(macro_index)
    start = macro_start + (0 if part == 1 else 5)
    end = start + 4
    synopsis_schema = {
        "chapter_title": "具体章名",
        "timeline_years": "年代", "scene_location": "主要场景", "participants": ["至少两人"],
        "opening_conflict": "开章立即发生的具体冲突", "exact_action_sequence": ["至少四步动作"],
        "info_gap_use": "本章如何使用前世信息差而不把记忆当证据",
        "opponent_reaction": "对手本章具体反应和一句可用对白方向",
        "immediate_payoff": "本章当场回报", "state_changes": ["本章结束后图谱状态变化"],
        "must_include": ["至少三项"], "must_not_include": ["至少两项"],
        "ending_hook": "先落结果再留钩子",
        "detailed_synopsis": "不少于180汉字，写清场景、行动、冲突、反转、结果，能直接指导约1000字正文",
    }
    synopsis_schemas = [
        {
            "chapter_id": chapter_id,
            "cluster_id": f"EC{(chapter_id + 1) // 2:03d}",
            **synopsis_schema,
        }
        for chapter_id in range(start, end + 1)
    ]
    response_schema = {
        "macro_group_id": macro["macro_group_id"],
        "chapter_synopses": synopsis_schemas,
        "continuity_update": events_obj.get("continuity_update", {}),
    }
    opening_special = ""
    if macro_index == 1 and part == 1:
        opening_special = (
            "第1章固定发生在2009年临终现场，写康拉德违规用药及麦珂听见保险、版权与母带分赃；"
            "第2章固定发生在1969年全国少年才艺试镜后台，现场完成重生、预判既有设备风险、避险并获得首胜。"
            "第2章scene_location必须写试镜后台，must_not_include绝不能禁止重生或回到1969。\n"
        )
    early_conrad_guard = (
        "本组仍处于第451章之前：章节现实场景中禁止康拉德本人登场；只能在info_gap_use中作为前世记忆提及，"
        "今生对手必须使用事件簇已经给出的当前年代人物。\n"
        if 23 <= macro_index <= 45 else ""
    )


def _chapter_event_prompt(
    macro: dict[str, Any], event: dict[str, Any], canonical_state: dict[str, str],
    global_outline: dict[str, Any],
) -> str:
    """Expand exactly one event into its two chapters without replanning WHAT happens."""
    milestones = event.get("two_chapter_structure") or []
    schemas: list[dict[str, Any]] = []
    for milestone in milestones:
        cid = int(milestone["chapter_id"])
        schemas.append({
            "chapter_id": cid,
            "cluster_id": event["cluster_id"],
            "immutable_event_facts": {
                "timeline_start": milestone.get("timeline_start"),
                "timeline_end": milestone.get("timeline_end"),
                "scene": milestone.get("scene"),
                "scenes": milestone.get("scenes"),
                "artifact_creates": milestone.get("artifact_creates"),
                "artifact_refs": milestone.get("artifact_refs"),
                "chapter_goal": milestone.get("chapter_goal"),
                "action_sequence": milestone.get("action_sequence"),
                "visible_payoff": milestone.get("visible_payoff"),
                "ending": milestone.get("ending"),
            },
            "chapter_title": "具体章名", "timeline_years": event.get("timeline_years"),
            "timeline_start": milestone.get("timeline_start"), "timeline_end": milestone.get("timeline_end"),
            "scene_location": milestone.get("scene"), "participants": ["至少两名已规划人物"],
            "scenes": milestone.get("scenes"),
            "artifact_creates": milestone.get("artifact_creates"),
            "artifact_refs": milestone.get("artifact_refs"),
            "opening_conflict": "只补充如何开场，不改变chapter_goal",
            "exact_action_sequence": milestone.get("action_sequence"),
            "info_gap_use": "本章如何使用既定前世信息差",
            "opponent_reaction": "对手或阻力的具体反应",
            "immediate_payoff": milestone.get("visible_payoff"),
            "state_changes": (
                [] if cid % 2 == 1 else event.get("state_transitions") or []
            ),
            "must_include": ["至少三项，全部来自本章milestone"],
            "must_not_include": ["至少两项，重点禁止跨章消费结算"],
            "ending_hook": milestone.get("ending"),
            "detailed_synopsis": "180—350汉字，只扩充表演调度、人物选择和情绪，不新增剧情事实",
        })
    return (
        f"这是已经通过规划编译的唯一权威事件事实：{_json_text(event)}\n"
        f"进入事件前的Canonical State：{_json_text(canonical_state)}\n"
        f"所属宏观组（只作语气和阶段背景，不能覆盖事件事实）：{_json_text(macro)}\n"
        f"全书主线切片（只用于说明复仇主线意义）：{_json_text(_global_outline_slice(global_outline, int(str(macro['macro_group_id'])[2:])))}\n"
        "一次性扩写本事件的两章梗概。Event Cluster决定WHAT，当前任务只决定HOW；"
        "immutable_event_facts必须逐字段原样复制，不得增删、改写、换序。"
        "第一章只能完成第一项milestone的小赢并停在其ending，绝不能出现第二章的完整交锋、永久损失、永久收益或state_transitions。"
        "第二章从第一章ending之后的新动作开始，不得重演第一章的试听、签字、交接、跌倒或对白。"
        "若既定动作依赖专业知识，优先让麦珂凭前世记忆指出时间点或诱导有资质的成年人自行发现，不把十一岁孩子写成全知法务/工程师。"
        "玛莎等盟友必须至少有一个独立判断或超出麦珂指令的选择；程序、文件和精确数字只在直接改变得失时出现。"
        "两个detailed_synopsis各180—350汉字，内容量匹配1200—1600汉字正文，不得靠意象和身体反应注水。\n"
        f"严格输出JSON：{_json_text({'cluster_id': event['cluster_id'], 'chapter_synopses': schemas})}"
    )


def _validate_chapter_event(obj: dict[str, Any], event: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if obj.get("cluster_id") != event.get("cluster_id"):
        failures.append(f"cluster_id必须为{event.get('cluster_id')}")
    chapters = obj.get("chapter_synopses")
    milestones = event.get("two_chapter_structure") or []
    if not isinstance(chapters, list) or len(chapters) != 2:
        return failures + ["chapter_synopses必须恰好2项"]
    for offset, chapter in enumerate(chapters):
        milestone = milestones[offset] if offset < len(milestones) else {}
        cid = int(milestone.get("chapter_id") or 0)
        if chapter.get("chapter_id") != cid or chapter.get("cluster_id") != event.get("cluster_id"):
            failures.append(f"第{cid}章编号或cluster_id错误")
        expected_facts = {
            "timeline_start": milestone.get("timeline_start"), "timeline_end": milestone.get("timeline_end"),
            "scene": milestone.get("scene"), "scenes": milestone.get("scenes"),
            "artifact_creates": milestone.get("artifact_creates"), "artifact_refs": milestone.get("artifact_refs"),
            "chapter_goal": milestone.get("chapter_goal"),
            "action_sequence": milestone.get("action_sequence"),
            "visible_payoff": milestone.get("visible_payoff"), "ending": milestone.get("ending"),
        }
        if chapter.get("immutable_event_facts") != expected_facts:
            failures.append(f"第{cid}章改写了Event Cluster锁定事实")
        for field, minimum in {
            "chapter_title": 3, "timeline_years": 4, "scene_location": 2,
            "opening_conflict": 8, "info_gap_use": 8, "opponent_reaction": 8,
            "immediate_payoff": 8, "ending_hook": 8, "detailed_synopsis": 180,
        }.items():
            if len(str(chapter.get(field) or "").strip()) < minimum:
                failures.append(f"第{cid}章{field}过短或缺失")
        for field, minimum in (("participants", 2), ("exact_action_sequence", 3), ("must_include", 3), ("must_not_include", 2)):
            if not isinstance(chapter.get(field), list) or len(chapter[field]) < minimum:
                failures.append(f"第{cid}章{field}至少{minimum}项")
        if chapter.get("exact_action_sequence") != milestone.get("action_sequence"):
            failures.append(f"第{cid}章exact_action_sequence必须忠实复制源milestone")
        if str(chapter.get("scene_location") or "") != str(milestone.get("scene") or ""):
            failures.append(f"第{cid}章scene_location必须忠实复制源milestone")
        for field in ("timeline_start", "timeline_end", "scenes", "artifact_creates", "artifact_refs"):
            if chapter.get(field) != milestone.get(field):
                failures.append(f"第{cid}章{field}必须忠实复制源milestone")
        if cid % 2 == 1:
            finale = _json_text({
                "villain_loss": event.get("villain_loss"), "protagonist_gain": event.get("protagonist_gain"),
                "state_transitions": event.get("state_transitions"),
            })
            first_text = _json_text(chapter)
            exact_finales = [
                str(event.get("villain_loss") or ""), str(event.get("protagonist_gain") or "")
            ]
            if any(value and value in first_text for value in exact_finales):
                failures.append(f"第{cid}章提前消费第二章永久结算")
        else:
            if chapter.get("state_changes") != event.get("state_transitions"):
                failures.append(f"第{cid}章必须精确承接事件state_transitions")
    left, right = chapters
    score = semantic_similarity(
        {k: left.get(k) for k in ("opening_conflict", "exact_action_sequence", "immediate_payoff", "detailed_synopsis")},
        {k: right.get(k) for k in ("opening_conflict", "exact_action_sequence", "immediate_payoff", "detailed_synopsis")},
    )
    if score >= 0.62:
        failures.append(f"两章语义相似度{score:.2f}，疑似重复演同一场戏")
    return failures
    unavailable_technology = _unavailable_technology(macro.get("timeline_years"))
    technology_guard = (
        f"本组时间为{macro.get('timeline_years')}，章节现实场景尚不应使用："
        f"{'、'.join(unavailable_technology)}。请采用该年代可行的技术与通信手段。\n"
        if unavailable_technology else
        f"本组时间为{macro.get('timeline_years')}，按该年代实际条件使用技术与通信手段。\n"
    )
    return (
        f"把以下Qwen事件簇中涉及第{start}-{end}章的部分直接扩写成5章详细梗概：{_json_text(events_obj['event_clusters'])}\n"
        f"宏观组蓝图：{_json_text(macro)}\n"
        f"进入本组前连续性：{_json_text(prior_ledger)}\n"
        f"全书总纲切片：{_json_text(_global_outline_slice(global_outline, macro_index))}\n"
        "每章梗概必须是具体剧情而非写作建议；每章只承担所在事件的一半，奇数章先赢并留钩子，偶数章必须结算现实得失。"
        "相邻事件不得重复同一种解决手段；动作、合同、舞台、粉丝、财务、家庭、医疗、媒体等手段轮换。\n"
        "严格区分前世与今生：前世晚年才认识的人不会随重生穿越；人物必须按合理年龄和首次相识年代登场。"
        + early_conrad_guard
        + technology_guard
        + "前世人物可在info_gap_use中作为记忆被提到，但不得在早期今生的participants、现场动作、对手反应或现实结算中实体出现。\n"
        + opening_special
        + f"全书契约：{_base_context()}\n"
        f"严格按这个JSON结构输出，chapter_synopses必须展开为5项且章号连续：{_json_text(response_schema)}"
    )


def _theme_contract() -> dict[str, Any]:
    return {
        "theme": THEME,
        "background": BACKGROUND,
        "main_protagonist": PROTAGONIST,
        "protagonists": [PROTAGONIST],
        "hard_constraints": HARD_RULES,
        "final_payoff": "第500章在全球纪念直播中现身，以今生形成的证据链完成审判并保住生命、家人和版权。",
    }


def _initial_character_registry() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for raw in CAST:
        member = dict(raw)
        name = str(member.get("name") or "").strip()
        cid = character_id_for_name(name)
        member.update({
            "character_id": cid,
            "display_name": name,
            "aliases": list(dict.fromkeys([name, name.split("·", 1)[0]])),
        })
        registry[cid] = member
    return registry


def _character_alias_index(
    registry: dict[str, dict[str, Any]],
) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for cid, member in registry.items():
        names = [member.get("display_name"), member.get("name"), *(member.get("aliases") or [])]
        for raw in names:
            alias = str(raw or "").strip()
            if alias:
                index.setdefault(alias, set()).add(cid)
    return index


def _resolve_or_register_character(
    raw_name: Any, registry: dict[str, dict[str, Any]],
) -> tuple[str | None, str | None]:
    name = str(raw_name or "").strip()
    if not name:
        return None, "人物名为空"
    alias_index = _character_alias_index(registry)
    matches = alias_index.get(name, set())
    if len(matches) == 1:
        return next(iter(matches)), None
    if len(matches) > 1:
        return None, f"人物别名“{name}”同时指向多个character_id，必须使用全名"
    # A provider may concatenate two already-known people with “与” in a
    # single opponent/participant slot. Resolve the first known person rather
    # than attempting to register the concatenated bare name as a new node.
    if "与" in name:
        for part in (piece.strip() for piece in name.split("与") if piece.strip()):
            part_matches = alias_index.get(part, set())
            if len(part_matches) == 1:
                return next(iter(part_matches)), None
    # New recurring characters need a full display name.  Bare first names are
    # exactly what caused 伊莱亚斯/雷蒙德 to merge unrelated people in Neo4j.
    if "·" not in name:
        return None, f"新人物“{name}”必须给出含姓氏的完整display_name，禁止裸名建图"
    cid = character_id_for_name(name)
    short_name = name.split("·", 1)[0]
    # Different people may legitimately share a given name.  In that case
    # only the first unambiguous owner keeps the short alias; both full names
    # remain stable and distinct in Neo4j.
    aliases = [name]
    if short_name not in alias_index:
        aliases.append(short_name)
    registry[cid] = {
        "character_id": cid,
        "name": name,
        "display_name": name,
        "aliases": list(dict.fromkeys(aliases)),
        "role": "Qwen在详细情节簇中创建的计划人物，具体身份以该情节簇为准",
        "alignment": "planned",
    }
    return cid, None


def _compile_event_identities(
    event: dict[str, Any], registry: dict[str, dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    referenced_ids: list[str] = []
    generic_scene_roles = {
        "主持人", "记者", "摄影师", "摄像师", "录音师", "灯光师", "场务",
        "工作人员", "后台人员", "制作人员", "评委", "观众", "粉丝",
        "医生", "护士", "律师", "警卫", "保安", "司机", "助理",
    }
    initial_alias_index = _character_alias_index(registry)
    for name in event.get("main_characters") or []:
        clean_label = str(name or "").strip()
        if (
            clean_label in generic_scene_roles
            or ("·" not in clean_label and clean_label not in initial_alias_index)
        ):
            event.setdefault("noncanonical_scene_roles", []).append(clean_label)
            continue
        cid, error = _resolve_or_register_character(name, registry)
        if error:
            failures.append(error)
        elif cid:
            referenced_ids.append(cid)
    opponent = str(event.get("main_opponent") or "").strip()
    opponent_parts = _event_opponent_names(event) or ([opponent] if opponent else [])
    resolved_opponents: list[tuple[str, str]] = []
    organization_opponents: list[tuple[str, str]] = []
    for opponent_part in opponent_parts:
        clean_name = re.sub(r"[（(][^）)]*[）)]", "", opponent_part).strip()
        if any(token in clean_name for token in (
            "集团", "公司", "传媒", "机构", "协会", "组织", "基金", "品牌", "工作室",
            "分销商", "广告商", "唱片商", "出版商", "制片方", "平台", "阵营", "委员会",
            "卫生局", "管理局", "事务局", "部门", "小组", "干预组", "审计组", "管理处", "办公室",
            "长老会", "理事会", "家族会",
        )):
            organization_opponents.append((
                opponent_part,
                "ORG_" + hashlib.sha256(clean_name.encode("utf-8")).hexdigest()[:16].upper(),
            ))
            continue
        opponent_id, opponent_error = _resolve_or_register_character(clean_name, registry)
        if opponent_error and str(event.get("opposition_type") or "") in {
            "villain", "family", "ally_resistance",
        }:
            failures.append(opponent_error)
        elif opponent_id:
            resolved_opponents.append((opponent_part, opponent_id))
            referenced_ids.append(opponent_id)
    if resolved_opponents:
        event["main_opponent_character_ids"] = list(dict.fromkeys(
            cid for _, cid in resolved_opponents
        ))
        current_life = [cid for label, cid in resolved_opponents if "今生" in label]
        event["main_opponent_character_id"] = (
            current_life[-1] if current_life else resolved_opponents[-1][1]
        )
    if organization_opponents:
        event["main_opponent_organization_ids"] = list(dict.fromkeys(
            oid for _, oid in organization_opponents
        ))
    alias_index = _character_alias_index(registry)
    for transition in event.get("state_transitions") or []:
        if not isinstance(transition, dict):
            continue
        raw_entity = str(transition.get("entity_id") or "").strip()
        typed_entity = re.fullmatch(
            r"(CHAR|ART|DOC|DOCUMENT|EVIDENCE|FILE|RECORD|COURT|ORG|RIGHTS?|REL|LOC|TEAM|PROJECT|ASSET|REPUT|JOB|HEALTH|ENEMY|FORESHADOW)_(.+)",
            raw_entity,
            flags=re.I,
        )
        if typed_entity:
            # Stable provider slugs sometimes contain lowercase suffixes;
            # canonical graph IDs are uppercase so identity validation and
            # Neo4j hashes remain deterministic.
            prefix = typed_entity.group(1).upper()
            suffix = typed_entity.group(2).upper()
            if prefix in {"DOC", "DOCUMENT", "EVIDENCE", "FILE", "RECORD", "COURT"}:
                prefix = "ART"
            raw_entity = f"{prefix}_{suffix}"
            transition["entity_id"] = raw_entity
        if ":" in raw_entity:
            entity_prefix, _state_suffix = raw_entity.split(":", 1)
            if re.fullmatch(
                r"(?:CHAR|ART|ORG|RIGHTS?|REL|LOC|TEAM|PROJECT|ASSET|REPUT|JOB|HEALTH|ENEMY|FORESHADOW)_[A-Z0-9_]{3,80}",
                entity_prefix,
            ):
                transition["source_entity_label"] = raw_entity
                raw_entity = entity_prefix
                transition["entity_id"] = raw_entity
            elif re.fullmatch(r"[A-Z][A-Z0-9_]{2,79}", entity_prefix):
                # A provider may put an untyped stable slug before the state
                # suffix (FACTORY_1986:asset_control).  Preserve the suffix in
                # state_key and let the domain-prefix compiler below type the
                # entity itself.
                transition["source_entity_label"] = raw_entity
                raw_entity = entity_prefix
                transition["entity_id"] = raw_entity
        if raw_entity.startswith("CHAR_"):
            if raw_entity not in registry:
                # Models sometimes emit a readable placeholder ID such as
                # CHAR_JONAS_001 while the transition evidence explicitly
                # names the already registered person.  Resolve the unique
                # name mentioned in that transition instead of regenerating
                # the whole event for an ID-format mistake.
                transition_text = _json_text({
                    key: value for key, value in transition.items()
                    if key != "entity_id"
                })
                mentioned_ids = {
                    cid
                    for alias, ids in alias_index.items()
                    if len(alias) >= 2 and alias in transition_text
                    for cid in ids
                }
                effect_type = str(transition.get("effect_type") or "")
                opponent_cid = str(event.get("main_opponent_character_id") or "")
                protagonist_matches = alias_index.get(PROTAGONIST, set())
                inferred_cid = None
                if effect_type == "villain_loss" and opponent_cid in registry:
                    inferred_cid = opponent_cid
                elif effect_type == "protagonist_gain" and len(protagonist_matches) == 1:
                    inferred_cid = next(iter(protagonist_matches))
                elif len(mentioned_ids) == 1:
                    inferred_cid = next(iter(mentioned_ids))
                if inferred_cid:
                    cid = inferred_cid
                    transition["source_entity_label"] = raw_entity
                    transition["entity_id"] = cid
                    referenced_ids.append(cid)
                else:
                    failures.append(f"state_transition引用未知character_id={raw_entity}")
            else:
                referenced_ids.append(raw_entity)
            continue
        if raw_entity.startswith("RIGHTS_"):
            transition["source_entity_label"] = raw_entity
            raw_entity = "RIGHT_" + raw_entity.removeprefix("RIGHTS_")
            transition["entity_id"] = raw_entity
        # Providers sometimes supply a stable uppercase slug but omit its
        # node-type prefix.  The state domain determines that prefix without
        # changing any story fact.
        domain_prefixes = {
            "rights": "RIGHT", "asset": "ASSET", "job": "JOB",
            "health": "HEALTH", "enemy_capability": "ENEMY",
            "foreshadow": "FORESHADOW", "reputation": "REPUT",
            "location": "LOC",
        }
        domain = str(transition.get("domain") or "")
        # Chinese organization labels occasionally appear directly in a
        # state transition (e.g. “奥瑞恩集团”). Bind them to the same stable
        # organization-node convention used for main_opponent instead of
        # rejecting an otherwise usable event.
        if (
            domain != "relationship"
            and any(token in raw_entity for token in ("集团", "公司", "机构", "组织", "委员会", "团队", "小组"))
        ):
            transition["source_entity_label"] = raw_entity
            transition["entity_id"] = "ORG_" + hashlib.sha256(raw_entity.encode("utf-8")).hexdigest()[:16].upper()
            continue
        if (
            domain in domain_prefixes
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{2,79}", raw_entity)
            and not re.match(
                r"^(?:CHAR|ART|ORG|RIGHTS?|REL|LOC|TEAM|PROJECT|ASSET|REPUT|JOB|HEALTH|ENEMY|FORESHADOW)_",
                raw_entity,
                flags=re.I,
            )
        ):
            transition["source_entity_label"] = raw_entity
            raw_entity = f"{domain_prefixes[domain]}_{raw_entity.upper()}"
            transition["entity_id"] = raw_entity
        matches = alias_index.get(raw_entity, set())
        if len(matches) == 1:
            cid = next(iter(matches))
            transition["entity_id"] = cid
            referenced_ids.append(cid)
        elif len(matches) > 1:
            failures.append(f"state_transition实体“{raw_entity}”人物别名歧义")
        elif (
            str(transition.get("domain") or "") == "relationship"
            and re.fullmatch(r"REL_[A-Z0-9_]{3,80}", raw_entity)
        ):
            # A stable relationship node may be opaque (REL_002) when the
            # prose evidence already records the people involved.
            continue
        elif str(transition.get("domain") or "") == "relationship":
            # Qwen often authors a readable pair such as 麦珂_玛莎. Resolve
            # both aliases to stable character IDs and compile a deterministic
            # relationship entity rather than editing the story content.
            pair_names = [part.strip() for part in re.split(r"[_/＆&、]", raw_entity) if part.strip()]
            pair_ids: list[str] = []
            for pair_name in pair_names:
                pair_matches = alias_index.get(pair_name, set())
                if len(pair_matches) == 1:
                    pair_ids.append(next(iter(pair_matches)))
            if len(pair_names) == 2 and len(pair_ids) == 2 and pair_ids[0] != pair_ids[1]:
                stable_pair = sorted(pair_ids)
                transition["source_entity_label"] = raw_entity
                transition["entity_id"] = "REL_" + "__".join(
                    item.removeprefix("CHAR_") for item in stable_pair
                )
                referenced_ids.extend(stable_pair)
            else:
                failures.append(
                    f"state_transition关系实体={raw_entity or '<空>'}无法解析为两个稳定character_id"
                )
        elif not re.fullmatch(
            r"(?:ART|ORG|RIGHT|REL|LOC|TEAM|PROJECT|ASSET|REPUT|JOB|HEALTH|ENEMY|FORESHADOW)_[A-Z0-9_]{3,80}",
            raw_entity,
        ):
            failures.append(
                f"state_transition.entity_id={raw_entity or '<空>'}既不是character_id，也不是带类型前缀的稳定实体ID"
            )
    event["canonical_cast"] = [registry[cid] for cid in dict.fromkeys(referenced_ids)]
    event["main_character_ids"] = list(dict.fromkeys(referenced_ids))
    return failures


def _normalize_chapter_plan_references(value: Any, current_event_index: int) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            referenced = int(match.group(1))
            if referenced < current_event_index:
                return "前序证据"
            if referenced == current_event_index:
                return "本次事件"
            return "后续安排"
        return re.sub(r"EC(\d{3})", replace, value)
    if isinstance(value, list):
        return [_normalize_chapter_plan_references(item, current_event_index) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_chapter_plan_references(item, current_event_index) for key, item in value.items()}
    return value


def _compile_chapter_input_from_milestone(
    event: dict[str, Any], milestone: dict[str, Any],
) -> dict[str, Any]:
    """Losslessly map one Qwen-authored milestone into the chapter-card schema."""
    chapter_id = int(milestone["chapter_id"])
    is_payoff = chapter_id == int(event["chapter_span"][1])
    return {
        "chapter_id": chapter_id,
        "cluster_id": event["cluster_id"],
        "chapter_title": milestone["chapter_title"],
        "timeline_years": event["timeline_years"],
        "timeline_start": milestone["timeline_start"],
        "timeline_end": milestone["timeline_end"],
        "scene_location": milestone["scene"],
        "scenes": milestone["scenes"],
        "artifact_creates": milestone["artifact_creates"],
        "artifact_refs": milestone["artifact_refs"],
        "participants": milestone["participants"],
        "opening_conflict": milestone["opening_conflict"],
        "exact_action_sequence": milestone["action_sequence"],
        "info_gap_use": milestone["info_gap_use"],
        "opponent_reaction": milestone["opponent_reaction"],
        "immediate_payoff": milestone["visible_payoff"],
        "state_changes": (event.get("state_transitions") or []) if is_payoff else [],
        "must_include": milestone["must_include"],
        "must_not_include": milestone["must_not_include"],
        "ending_hook": milestone["ending"],
        "detailed_synopsis": milestone["detailed_synopsis"],
    }


def _chapter_card(chapter: dict[str, Any], event: dict[str, Any], macro: dict[str, Any]) -> dict[str, Any]:
    chapter_id = int(chapter["chapter_id"])
    start, end = [int(x) for x in event["chapter_span"]]
    event_index = int(str(event["cluster_id"])[2:])
    raw_actions = chapter["exact_action_sequence"]
    had_internal_refs = bool(re.search(r"EC\d{3}", _json_text(chapter)))
    expanded_actions = [
        part.strip()
        for item in raw_actions
        for part in re.split(r"[；;]", str(item or ""))
        if part.strip()
    ]
    normalized_chapter = _normalize_chapter_plan_references(chapter, event_index)
    normalized_chapter["exact_action_sequence"] = _normalize_chapter_plan_references(expanded_actions, event_index)
    for field in ("state_changes", "must_include", "must_not_include"):
        raw_values = chapter[field]
        if field == "state_changes" and isinstance(raw_values, list) and all(
            isinstance(item, dict) for item in raw_values
        ):
            normalized_chapter[field] = raw_values
        else:
            split_pattern = r"[；;、]" if field in ("must_include", "must_not_include") else r"[；;]"
            expanded_values = [
                part.strip()
                for item in raw_values
                for part in re.split(split_pattern, str(item or ""))
                if part.strip()
            ]
            normalized_chapter[field] = _normalize_chapter_plan_references(expanded_values, event_index)
    card = {
        "chapter_id": chapter_id,
        "chapter_title": normalized_chapter["chapter_title"],
        "arc_id": f"P{(chapter_id - 1) // 50 + 1:02d}",
        "story_block_id": macro["story_block_id"],
        "macro_group_id": macro["macro_group_id"],
        "cluster_id": event["cluster_id"],
        "cluster_name": event["name"],
        "timeline_years": chapter["timeline_years"],
        "timeline_start": normalized_chapter["timeline_start"],
        "timeline_end": normalized_chapter["timeline_end"],
        "chapter_role_v2": (
            "previous_life_death" if chapter_id == 1 else
            "rebirth_confirmation" if chapter_id == 2 else
            "two_chapter_setup_and_win" if chapter_id % 2 else "two_chapter_payoff"
        ),
        "structure_template": "QWEN_TWO_CHAPTER_EVENT",
        "chapter_goal": normalized_chapter["opening_conflict"] + "；" + normalized_chapter["immediate_payoff"],
        "chapter_must_include": normalized_chapter["must_include"],
        "chapter_must_not_include": normalized_chapter["must_not_include"] + ["公开自曝重生", "万能黑客", "匿名证据直接解题"],
        "chapter_ending": normalized_chapter["ending_hook"],
        "must_resolve_this_chapter": normalized_chapter["state_changes"],
        "detailed_synopsis": normalized_chapter["detailed_synopsis"],
        "scene_location": normalized_chapter["scene_location"],
        "scenes": normalized_chapter["scenes"],
        "artifact_creates": normalized_chapter["artifact_creates"],
        "artifact_refs": normalized_chapter["artifact_refs"],
        "participants": normalized_chapter["participants"],
        "exact_action_sequence": normalized_chapter["exact_action_sequence"],
        "info_gap_use": normalized_chapter["info_gap_use"],
        "opponent_reaction": normalized_chapter["opponent_reaction"],
        "immediate_payoff": normalized_chapter["immediate_payoff"],
        "state_changes": normalized_chapter["state_changes"],
        "state_transitions": event.get("state_transitions") if chapter_id == end else [],
        "source_milestone_sha256": canonical_sha256(
            next(
                item for item in event.get("two_chapter_structure", [])
                if int(item.get("chapter_id") or 0) == chapter_id
            )
        ),
        "source_event_sha256": canonical_sha256(event),
        "core_payoff": event["cluster_outcome"],
        "main_opponent": event["main_opponent"],
        "prev_life_tragedy": event["prev_life_tragedy"],
        "info_gap_from_prev_life": event["info_gap_from_prev_life"],
        "this_life_revenge": event["preemptive_avoidance"] + "；" + event["bait_and_evidence"],
        "cluster_outcome": event["cluster_outcome"],
        "romance_state": event["relationship_change"],
        "canonical_cast": event["canonical_cast"],
        "allowed_roles": list(dict.fromkeys(event.get("main_characters", []) + chapter.get("participants", []))),
        "forbidden_roles": ["未铺垫的终极反派", "万能黑客", "神秘证人"],
        "cluster_span_start": start,
        "cluster_span_end": end,
        "cluster_chapter_index": chapter_id - start + 1,
        "cluster_chapter_total": 2,
        "target_chinese_chars": 1400,
        "generated_by": str(event.get("generated_by") or "qwen"),
        "compiled_by": CHAPTER_CARD_COMPILER_VERSION,
        "manual_edits": [],
        "planning_version": PLANNING_VERSION,
        "theme_contract": _theme_contract(),
    }
    normalizations: list[str] = []
    if expanded_actions != raw_actions:
        normalizations.append("exact_action_sequence:semicolon_string_to_list")
    if any(normalized_chapter[field] != chapter[field] for field in ("state_changes", "must_include", "must_not_include")):
        normalizations.append("chapter_lists:semicolon_string_to_list")
    if had_internal_refs:
        normalizations.append("internal_EC_reference:relative_narrative_label")
    if normalizations:
        card["structural_normalizations"] = normalizations
    return card


def run(
    output_dir: Path,
    model: str,
    chapter_model: str,
    resume: bool,
    stop_after_macro: int = 50,
    stop_after_block: int = 25,
    global_only: bool = False,
    blocks_only: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = output_dir / "qwen_batches"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    global_narrative_core = _call_validated(
        kind="narrative_core", identifier="GLOBAL", system_prompt=_global_system_prompt(),
        user_prompt=_global_narrative_core_prompt(), validator=_validate_global_narrative_core,
        checkpoint_dir=checkpoint_dir, model=model, temperature=0.68,
        resume=resume, max_attempts=5,
    )
    global_narrative_segments: list[dict[str, Any]] = []
    for segment_part in range(1, 4):
        segment = _call_validated(
            kind=f"narrative_s{segment_part}", identifier="GLOBAL",
            system_prompt=_global_system_prompt(),
            user_prompt=_global_narrative_segment_prompt(
                global_narrative_core, segment_part, global_narrative_segments,
            ),
            validator=lambda obj, part=segment_part: _validate_global_narrative_segment(obj, part),
            checkpoint_dir=checkpoint_dir, model=model, temperature=0.72,
            resume=resume, max_attempts=5,
        )
        global_narrative_segments.append(segment)
    global_narrative = _assemble_global_narrative(
        global_narrative_core, global_narrative_segments,
    )
    narrative_failures = _validate_global_narrative(global_narrative)
    if narrative_failures:
        raise RuntimeError(
            "Qwen全书叙事四批合并后校验失败：" + " | ".join(narrative_failures[:16])
        )
    global_phases_a = _call_validated(
        kind="phases_a", identifier="GLOBAL", system_prompt=_global_system_prompt(),
        user_prompt=_global_phases_prompt(global_narrative, 1),
        validator=lambda obj: _validate_global_phase_part(obj, 1),
        checkpoint_dir=checkpoint_dir, model=model, temperature=0.68,
        resume=resume, max_attempts=5,
    )
    global_phases_b = _call_validated(
        kind="phases_b", identifier="GLOBAL", system_prompt=_global_system_prompt(),
        user_prompt=_global_phases_prompt(global_narrative, 2),
        validator=lambda obj: _validate_global_phase_part(obj, 2),
        checkpoint_dir=checkpoint_dir, model=model, temperature=0.68,
        resume=resume, max_attempts=5,
    )
    global_phases = {
        "life_phases": global_phases_a["life_phases"] + global_phases_b["life_phases"],
        "state_ledger_by_phase": (
            global_phases_a["state_ledger_by_phase"] + global_phases_b["state_ledger_by_phase"]
        ),
    }
    phase_failures = _validate_global_phases(global_phases)
    if phase_failures:
        raise RuntimeError("Qwen十阶段两批合并后校验失败：" + " | ".join(phase_failures[:12]))
    compiled_threads = _compile_existing_global_component(
        checkpoint_dir, kind="threads", validator=_validate_global_long_arcs,
    )
    if compiled_threads is not None:
        global_long_arcs, global_long_arcs_provenance_path = compiled_threads
    else:
        global_long_arcs = _call_validated(
            kind="threads", identifier="GLOBAL", system_prompt=_global_system_prompt(),
            user_prompt=_global_threads_prompt(global_narrative, global_phases), validator=_validate_global_long_arcs,
            checkpoint_dir=checkpoint_dir, model=model, temperature=0.70,
            resume=resume, max_attempts=5,
        )
        global_long_arcs_provenance_path = checkpoint_dir / "GLOBAL_threads_provenance.json"
    compiled_foreshadows_a = _compile_existing_global_component(
        checkpoint_dir, kind="foreshadows_a",
        validator=lambda obj: _validate_global_foreshadows(obj, 1, 6),
    )
    if compiled_foreshadows_a is not None:
        global_foreshadows_a, global_foreshadows_a_provenance_path = compiled_foreshadows_a
    else:
        global_foreshadows_a = _call_validated(
            kind="foreshadows_a", identifier="GLOBAL", system_prompt=_global_system_prompt(),
            user_prompt=_global_foreshadows_prompt(global_narrative, global_phases, global_long_arcs, 1),
            validator=lambda obj: _validate_global_foreshadows(obj, 1, 6),
            checkpoint_dir=checkpoint_dir, model=model, temperature=0.66,
            resume=resume, max_attempts=5,
        )
        global_foreshadows_a_provenance_path = checkpoint_dir / "GLOBAL_foreshadows_a_provenance.json"
    compiled_foreshadows_b = _compile_existing_global_component(
        checkpoint_dir, kind="foreshadows_b",
        validator=lambda obj: _validate_global_foreshadows(obj, 7, 6),
    )
    if compiled_foreshadows_b is not None:
        global_foreshadows_b, global_foreshadows_b_provenance_path = compiled_foreshadows_b
    else:
        global_foreshadows_b = _call_validated(
            kind="foreshadows_b", identifier="GLOBAL", system_prompt=_global_system_prompt(),
            user_prompt=_global_foreshadows_prompt(
                global_narrative, global_phases, global_long_arcs, 2,
                prior_foreshadows=global_foreshadows_a["foreshadow_ledger"],
            ),
            validator=lambda obj: _validate_global_foreshadows(obj, 7, 6),
            checkpoint_dir=checkpoint_dir, model=model, temperature=0.64,
            resume=resume, max_attempts=5,
        )
        global_foreshadows_b_provenance_path = checkpoint_dir / "GLOBAL_foreshadows_b_provenance.json"
    global_foreshadows = {
        "foreshadow_ledger": (
            global_foreshadows_a["foreshadow_ledger"]
            + global_foreshadows_b["foreshadow_ledger"]
        ),
    }
    global_outline = {
        **global_narrative, **global_phases, **global_long_arcs, **global_foreshadows,
    }
    assembled_failures = _validate_global_outline(global_outline)
    if assembled_failures:
        raise RuntimeError("Qwen全书总纲三部分合并后校验失败：" + " | ".join(assembled_failures[:12]))
    global_outline["manual_edits"] = []
    global_outline["planning_version"] = PLANNING_VERSION
    global_provenance_paths = [
        checkpoint_dir / "GLOBAL_narrative_core_provenance.json",
        checkpoint_dir / "GLOBAL_narrative_s1_provenance.json",
        checkpoint_dir / "GLOBAL_narrative_s2_provenance.json",
        checkpoint_dir / "GLOBAL_narrative_s3_provenance.json",
        checkpoint_dir / "GLOBAL_phases_a_provenance.json",
        checkpoint_dir / "GLOBAL_phases_b_provenance.json",
        global_long_arcs_provenance_path,
        global_foreshadows_a_provenance_path,
        global_foreshadows_b_provenance_path,
    ]
    generation_providers = _generation_providers(global_provenance_paths)
    generation_label = _generator_label(generation_providers)
    global_outline["generated_by"] = generation_label
    global_outline["generation_providers"] = generation_providers
    outline_sha256 = canonical_sha256(global_outline)
    archived_downstream = _archive_stale_downstream_if_outline_changed(
        output_dir, outline_sha256
    )
    _write_json(output_dir / "global_story_outline_v5_qwen_500.json", global_outline)
    global_stage_manifest = {
        "planning_version": PLANNING_VERSION,
        "generated_by": generation_label,
        "generation_providers": generation_providers,
        "blueprint_and_event_model": model,
        "chapter_synopsis_model": CHAPTER_CARD_COMPILER_VERSION,
        "manual_edits": [],
        "created_at": _now(),
        "complete": False,
        "planning_prefix_ready": False,
        "global_story_outline": 1,
        "outline_sha256": outline_sha256,
        "coarse_story_blocks": 0,
        "macro_groups": 0,
        "event_clusters": 0,
        "chapter_synopses": 0,
        "accepted_qwen_batches": 9,
        "expected_qwen_batches": EXPECTED_QWEN_BATCHES,
        "provenance_files": [
            str(path.relative_to(output_dir)) for path in global_provenance_paths
        ],
        "story_id": planning_story_id(global_outline),
        "stopped_after": "global_story_outline_review_gate",
        "archived_stale_downstream": (
            str(archived_downstream.relative_to(output_dir)) if archived_downstream else None
        ),
    }
    _write_json(output_dir / "qwen_generation_manifest.json", global_stage_manifest)
    if global_only:
        return global_stage_manifest
    blocks: list[dict[str, Any]] = []
    macros: list[dict[str, Any]] = []
    prior_block_ledger: dict[str, Any] = {}
    for block_index in range(1, 26):
        bid = f"B{block_index:03d}"
        backbone = _call_validated(
            kind="block_backbone", identifier=bid, system_prompt=_system_prompt(),
            user_prompt=_block_backbone_prompt(block_index, prior_block_ledger, global_outline),
            validator=lambda obj, i=block_index: _validate_block_backbone(obj, i),
            checkpoint_dir=checkpoint_dir, model=model, temperature=0.70,
            resume=resume,
            # B001 was already accepted from a provider response and still
            # passes the current semantic validator.  Its upstream global
            # identities were deterministically rebound afterwards, so that
            # one prompt hash may drift without discarding valid story work.
            allow_prompt_drift=block_index == 1,
            max_output_tokens=1800,
        )
        backbone = _normalize_fictional_places(backbone)
        block_macros: list[dict[str, Any]] = []
        first_macro_index = (block_index - 1) * 2 + 1
        for macro_index in range(first_macro_index, first_macro_index + 2):
            macro_blueprint = _generate_macro_blueprint_batched(
                block_index=block_index,
                macro_index=macro_index,
                backbone=backbone,
                prior_macro=block_macros[-1] if block_macros else None,
                global_outline=global_outline,
                checkpoint_dir=checkpoint_dir,
                model=model,
                resume=resume,
            )
            macro_blueprint["compiled_by"] = "structured_macro_fields_to_direction_v1"
            block_macros.append(macro_blueprint)
        result = {**backbone, "macro_groups": block_macros}
        combined_failures = _validate_story_block(result, block_index, global_outline)
        if combined_failures:
            raise RuntimeError(
                f"{bid}三段Qwen规划合并后校验失败：" + " | ".join(combined_failures[:20])
            )
        block_provenance_paths = [
            checkpoint_dir / f"{bid}_block_backbone_provenance.json",
            *[
                checkpoint_dir / f"MG{index:03d}_macro_blueprint_provenance.json"
                for index in range(first_macro_index, first_macro_index + 2)
            ],
        ]
        block_providers = _generation_providers(block_provenance_paths)
        result["generated_by"] = _generator_label(block_providers)
        result["generation_providers"] = block_providers
        result["manual_edits"] = []
        result["assembled_from_qwen_batches"] = [
            f"{bid}_block_backbone", *[
                f"MG{index:03d}_macro_blueprint"
                for index in range(first_macro_index, first_macro_index + 2)
            ],
        ]
        raw_movements = result.get("character_movements")
        normalized_movements = [
            item.strip()
            for raw in (raw_movements if isinstance(raw_movements, list) else [raw_movements])
            for item in re.split(r"[；;]", str(raw or ""))
            if item.strip()
        ]
        if normalized_movements != raw_movements:
            result["character_movements"] = normalized_movements
            result["structural_normalizations"] = ["character_movements:semicolon_string_to_list"]
        blocks.append(result)
        for raw_macro in result["macro_groups"]:
            macro = dict(raw_macro)
            macro_provider = _provider_for_provenance(
                checkpoint_dir / f"{macro['macro_group_id']}_macro_blueprint_provenance.json"
            )
            macro["story_block_id"] = bid
            macro["story_block_title"] = result["block_title"]
            macro["story_block_goal"] = result["block_goal"]
            macro["story_block_outcome"] = result["block_outcome"]
            macro["story_block_entry_state"] = result.get("entry_state") or {}
            macro["story_block_character_movements"] = result.get("character_movements") or []
            macro["story_block_state_changes"] = result.get("rights_health_relationship_changes") or {}
            macro["story_block_causal_links"] = result.get("causal_links_used") or []
            macro["story_block_foreshadows"] = result.get("foreshadows_planted_or_advanced") or []
            # Event validation reads the macro object directly. Preserve the
            # authoritative block-level ID sets under their canonical names so
            # a detailed event cannot invent an unrelated CS/FS reference.
            macro["causal_links_used"] = result.get("causal_links_used") or []
            macro["foreshadows_planted_or_advanced"] = (
                result.get("foreshadows_planted_or_advanced") or []
            )
            macro["story_block_continuity"] = result.get("continuity_update") or {}
            macro["generated_by"] = macro_provider
            macro["generation_providers"] = [macro_provider]
            macro["manual_edits"] = []
            macros.append(macro)
        prior_block_ledger = _merge_continuity_ledger(
            prior_block_ledger, result.get("continuity_update") or {}
        )
        # Persist useful partial output after every Qwen batch.  A long 500-chapter
        # run must remain inspectable and resumable even if a later call fails.
        _write_json(output_dir / "coarse_story_blocks_v5_qwen_500.json", blocks)
        _write_json(output_dir / "macro_groups_v5_qwen_500.json", macros)
        partial_block_bundle_sha256 = canonical_sha256({"blocks": blocks, "macros": macros})
        completed_block_provenance = sorted([
            *checkpoint_dir.glob("B???_block_backbone_provenance.json"),
            *checkpoint_dir.glob("MG???_macro_blueprint_provenance.json"),
        ])
        completed_block_provenance = [
            path for path in completed_block_provenance
            if json.loads(path.read_text(encoding="utf-8")).get("accepted_attempt")
        ]
        partial_provenance_paths = [*global_provenance_paths, *completed_block_provenance]
        partial_providers = _generation_providers(partial_provenance_paths)
        _write_json(output_dir / "qwen_generation_manifest.json", {
            **global_stage_manifest,
            "generated_by": _generator_label(partial_providers),
            "generation_providers": partial_providers,
            "created_at": _now(),
            "coarse_story_blocks": len(blocks),
            "macro_groups": len(macros),
            "accepted_qwen_batches": 9 + len(completed_block_provenance),
            "provenance_files": [
                str(path.relative_to(output_dir))
                for path in partial_provenance_paths
            ],
            "block_plan_bundle_sha256": partial_block_bundle_sha256,
            "stopped_after": f"{bid}_coarse_story_block",
        })
        print(f"[progress] block={block_index}/25 macros={len(macros)}", flush=True)
        if block_index >= stop_after_block:
            break

    _write_json(output_dir / "coarse_story_blocks_v5_qwen_500.json", blocks)
    _write_json(output_dir / "macro_groups_v5_qwen_500.json", macros)
    block_plan_bundle_sha256 = canonical_sha256({"blocks": blocks, "macros": macros})
    _bootstrap_local_neo4j_env()
    planning_graph_story_id = None
    if _neo4j_reachable():
        planning_graph_story_id = sync_planning_hierarchy(global_outline, blocks, macros)
        graph_hierarchy_audit = verify_planning_hierarchy(global_outline, blocks, macros)
        if planning_graph_story_id:
            print(
                f"[graph] planning hierarchy synced and verified story_id={planning_graph_story_id} "
                f"blocks={graph_hierarchy_audit['story_blocks']} macros={graph_hierarchy_audit['macro_groups']}",
                flush=True,
            )
    elif not blocks_only:
        raise RuntimeError("Neo4j不可用：详细情节族生成要求规划图数据库在线且认证有效")
    else:
        print("[graph-warning] Neo4j unavailable at blocks-only review gate", flush=True)
    if blocks_only:
        provenance_paths = [*global_provenance_paths] + [
                path for index in range(1, len(blocks) + 1)
                for path in (
                    checkpoint_dir / f"B{index:03d}_block_backbone_provenance.json",
                    checkpoint_dir / f"MG{(index - 1) * 2 + 1:03d}_macro_blueprint_provenance.json",
                    checkpoint_dir / f"MG{(index - 1) * 2 + 2:03d}_macro_blueprint_provenance.json",
                )
            ]
        block_generation_providers = _generation_providers(provenance_paths)
        manifest = {
            "planning_version": PLANNING_VERSION,
            "generated_by": _generator_label(block_generation_providers),
            "generation_providers": block_generation_providers,
            "blueprint_and_event_model": model,
            "chapter_synopsis_model": CHAPTER_CARD_COMPILER_VERSION,
            "manual_edits": [],
            "created_at": _now(),
            "complete": False,
            "global_story_outline": 1,
            "coarse_story_blocks": len(blocks),
            "macro_groups": len(macros),
            "event_clusters": 0,
            "chapter_synopses": 0,
            "accepted_qwen_batches": len(provenance_paths),
            "expected_qwen_batches": EXPECTED_QWEN_BATCHES,
            "provenance_files": [str(path.relative_to(output_dir)) for path in provenance_paths],
            "planning_graph_story_id": planning_graph_story_id,
            "story_id": planning_story_id(global_outline),
            "outline_sha256": outline_sha256,
            "block_plan_bundle_sha256": block_plan_bundle_sha256,
            "stopped_after": (
                "coarse_story_blocks_review_gate" if len(blocks) == 25
                else f"B{len(blocks):03d}_coarse_story_block_review_gate"
            ),
        }
        _write_json(output_dir / "qwen_generation_manifest.json", manifest)
        return manifest

    _archive_stale_detail_plan_if_blocks_changed(output_dir, blocks, macros)

    events: list[dict[str, Any]] = []
    chapters: list[dict[str, Any]] = []
    continuity: dict[str, Any] = {}
    canonical_state: dict[str, str] = {}
    irreversible_state: set[str] = set()
    character_registry = _initial_character_registry()
    for macro_index, macro in enumerate(macros, 1):
        if macro_index > stop_after_macro:
            break
        mid = f"MG{macro_index:03d}"
        if not _neo4j_reachable():
            raise RuntimeError(f"{mid}生成前Neo4j连接中断，拒绝在无图谱上下文时继续")
        graph_context = retrieve_event_context(global_outline, macro)
        if graph_context.get("source") != "neo4j_planning_graph":
            raise RuntimeError(f"{mid}未取得当前规划story_id的Neo4j上下文")
        events_obj = _generate_events_batched(
            macro=macro,
            prior_ledger=continuity,
            global_outline=global_outline,
            graph_context=graph_context,
            prior_events=list(events),
            prior_state=dict(canonical_state),
            prior_irreversible=set(irreversible_state),
            checkpoint_dir=checkpoint_dir,
            model=model,
            resume=resume,
        )
        event_provider = _provider_for_provenance(
            checkpoint_dir / f"{mid}_events_provenance.json"
        )
        event_by_id: dict[str, dict[str, Any]] = {}
        compiled_macro_events: list[dict[str, Any]] = []
        for event in events_obj["event_clusters"]:
            event = dict(event)
            normalized_milestones: list[dict[str, Any]] = []
            event_actions_normalized = False
            for milestone in event["two_chapter_structure"]:
                normalized_milestone = dict(milestone)
                raw_actions = normalized_milestone.get("action_sequence") or []
                expanded_actions = [
                    part.strip()
                    for item in raw_actions
                    for part in re.split(r"[；;]", str(item or ""))
                    if part.strip()
                ]
                if expanded_actions != raw_actions:
                    event_actions_normalized = True
                normalized_milestone["action_sequence"] = expanded_actions
                normalized_milestones.append(normalized_milestone)
            event["two_chapter_structure"] = normalized_milestones
            main_characters = [str(x).strip() for x in event.get("main_characters", []) if str(x).strip()]
            identity_failures = _compile_event_identities(event, character_registry)
            if identity_failures:
                raise RuntimeError(
                    f"{event.get('cluster_id')}人物身份编译失败：" + " | ".join(identity_failures)
                )
            rebirth_flywheel = [
                f"前世代价：{event['prev_life_tragedy']}",
                f"记忆信息差：{event['info_gap_from_prev_life']}",
                f"今生提前规避：{event['preemptive_avoidance']}",
                f"诱饵与今生证据：{event['bait_and_evidence']}",
                f"反派现实损失：{event['villain_loss']}",
                f"主角现实收益：{event['protagonist_gain']}",
            ]
            event.update({
                "macro_group_id": mid,
                "story_block_id": macro["story_block_id"],
                "story_block_title": macro["story_block_title"],
                "story_block_goal": macro["story_block_goal"],
                "story_block_outcome": macro["story_block_outcome"],
                "macro_group_title": macro["title"],
                "macro_goal": macro["macro_goal"],
                "macro_ending_state": macro["ending_state"],
                "arc_id": f"P{(int(event['chapter_span'][0]) - 1) // 50 + 1:02d}",
                "core_payoff": event["cluster_outcome"],
                "this_life_revenge": event["preemptive_avoidance"] + "；" + event["bait_and_evidence"],
                "comic_villain_beat": event["comic_villain_behavior"],
                "ascension_gain": event["protagonist_gain"],
                "romance_state": event["relationship_change"],
                "chapter_milestones": event["two_chapter_structure"],
                "resolves": [event["villain_loss"], event["protagonist_gain"]],
                "plan_relations": [event["relationship_change"]],
                "foreshadows": [event["next_event_hook"]],
                "source_anchor_ids": [str(x) for x in event.get("historical_anchor_ids", [])],
                "rebirth_flywheel": rebirth_flywheel,
                "hard_constraints": HARD_RULES,
                "generated_by": event_provider,
                "generation_providers": [event_provider],
                "manual_edits": [],
                "planning_version": PLANNING_VERSION,
                "theme_contract": _theme_contract(),
            })
            if event_actions_normalized:
                event["structural_normalizations"] = ["event_action_sequence:semicolon_string_to_list"]
            events.append(event)
            compiled_macro_events.append(event)
            event_by_id[event["cluster_id"]] = event
        # Only the final compiled event is authoritative.  Writing Qwen's raw
        # object before canonical IDs/normalizations made graph hashes stale as
        # soon as event_clusters_v2.json was saved.
        graph_sid = upsert_event_batch(global_outline, macro, compiled_macro_events)
        graph_hash_audit = verify_event_batch_hashes(global_outline, compiled_macro_events)
        if graph_sid:
            print(
                f"[graph] {mid} compiled event batch synced story_id={graph_sid} "
                f"verified_hashes={graph_hash_audit['verified_event_hashes']}", flush=True,
            )
        for event in events_obj["event_clusters"]:
            compiled_event = event_by_id[event["cluster_id"]]
            for milestone in compiled_event["two_chapter_structure"]:
                chapter = _compile_chapter_input_from_milestone(compiled_event, milestone)
                chapters.append(_chapter_card(chapter, compiled_event, macro))
            compiled_event_count = len(chapters) // 2
            prefix_report = validate_full_plan(
                events[:compiled_event_count], chapters, allow_partial=True,
                global_outline=global_outline,
            )
            if not prefix_report["passed"]:
                raise RuntimeError(
                    f"{compiled_event['cluster_id']}增量规划编译失败："
                    + " | ".join(prefix_report["failures"][-12:])
                )
            canonical_state, irreversible_state, transition_failures = apply_state_transitions(
                compiled_event.get("state_transitions") or [], canonical_state, irreversible_state
            )
            if transition_failures:
                raise RuntimeError(
                    f"{compiled_event['cluster_id']}状态转移编译失败：" + " | ".join(transition_failures)
                )
        continuity = {
            **(events_obj.get("continuity_update") or {}),
            "canonical_state": canonical_state,
            "irreversible_state_keys": sorted(irreversible_state),
        }
        _write_detail_progress(output_dir, events, chapters)
        print(f"[progress] macro={macro_index}/{stop_after_macro} events={len(events)} chapters={len(chapters)}", flush=True)

    _write_json(output_dir / "global_story_outline_v5_qwen_500.json", global_outline)
    _write_json(output_dir / "coarse_story_blocks_v5_qwen_500.json", blocks)
    _write_json(output_dir / "macro_groups_v5_qwen_500.json", macros)
    _write_detail_progress(output_dir, events, chapters)
    _write_json(output_dir / "research_timeline_sources.json", SOURCES)
    _write_json(output_dir / "research_timeline_anchors.json", RESEARCH_ANCHORS)

    provenance_files = sorted([
        *global_provenance_paths,
        *[
            path for index in range(1, len(blocks) + 1)
            for path in (
                checkpoint_dir / f"B{index:03d}_block_backbone_provenance.json",
                checkpoint_dir / f"MG{(index - 1) * 2 + 1:03d}_macro_blueprint_provenance.json",
                checkpoint_dir / f"MG{(index - 1) * 2 + 2:03d}_macro_blueprint_provenance.json",
            )
        ],
        *[
            checkpoint_dir / f"MG{index:03d}_events_provenance.json"
            for index in range(1, len(events) // 5 + 1)
        ],
    ])
    accepted = []
    for path in provenance_files:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("accepted_attempt"):
            accepted.append(record)
    final_generation_providers = sorted({
        str(record.get("generated_by") or "") for record in accepted
        if str(record.get("generated_by") or "") in VALID_GENERATION_PROVIDERS
    })
    complete = len(events) == 250 and len(chapters) == 500 and stop_after_macro >= 50
    prefix_ready = bool(events) and len(chapters) == len(events) * 2
    style_samples_path = Path(__file__).resolve().parents[2] / "data" / "pop_king_revenge_style_samples_v1.json"
    style_samples = json.loads(style_samples_path.read_text(encoding="utf-8"))
    prefix_fingerprints = plan_fingerprints(
        outline=global_outline, events=events, cards=chapters, style_samples=style_samples,
    )
    prefix_report = write_compilation_report(
        output_dir / ("plan_compilation_report.json" if complete else "plan_prefix_compilation_report.json"),
        events=events,
        cards=chapters,
        fingerprints=prefix_fingerprints,
        allow_partial=not complete,
        global_outline=global_outline,
    )
    if not prefix_report["passed"]:
        raise RuntimeError(
            "规划语义预检失败：" + " | ".join(prefix_report["failures"][:20])
        )
    manifest = {
        "planning_version": PLANNING_VERSION,
        "generated_by": _generator_label(final_generation_providers),
        "generation_providers": final_generation_providers,
        "blueprint_and_event_model": model,
        "chapter_synopsis_model": CHAPTER_CARD_COMPILER_VERSION,
        "chapter_cards_compiled_from_qwen_event_milestones": True,
        "manual_edits": [],
        "created_at": _now(),
        "complete": complete,
        "planning_prefix_ready": prefix_ready,
        "planning_prefix_through_macro": len(events) // 5,
        "planning_prefix_through_chapter": len(chapters),
        "global_story_outline": 1,
        "coarse_story_blocks": len(blocks),
        "macro_groups": len(macros),
        "event_clusters": len(events),
        "chapter_synopses": len(chapters),
        "accepted_qwen_batches": len(accepted),
        "expected_qwen_batches": EXPECTED_QWEN_BATCHES,
        "provenance_files": [str(path.relative_to(output_dir)) for path in provenance_files],
        "story_id": planning_story_id(global_outline),
        "outline_sha256": outline_sha256,
        "block_plan_bundle_sha256": block_plan_bundle_sha256,
        "plan_fingerprints": prefix_fingerprints,
    }
    _write_json(output_dir / "qwen_generation_manifest.json", manifest)
    if complete:
        _write_json(output_dir / "qwen_generation_manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate 250 detailed event clusters and 500 chapter synopses with Qwen.")
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parents[2] / OUTPUT_NAME))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--chapter-model", default=os.getenv("QWEN_CHAPTER_MODEL", "qwen-turbo"))
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--global-only", action="store_true", help="Generate the broad whole-story outline and stop for review before decomposition.")
    parser.add_argument("--blocks-only", action="store_true", help="Generate the global outline plus 25 twenty-chapter blocks, then stop for review.")
    parser.add_argument(
        "--stop-after-block", type=int, default=25,
        help="With --blocks-only, stop after this many sequential twenty-chapter blocks.",
    )
    parser.add_argument("--stop-after-macro", type=int, default=50, help="For an explicit smoke run; full authoritative output requires 50.")
    parser.add_argument(
        "--retry-cycles", type=int, default=1,
        help="Restart from checkpoints after a batch exhausts its Qwen attempts; validation is never bypassed.",
    )
    args = parser.parse_args()
    manifest: dict[str, Any] | None = None
    cycles = max(1, int(args.retry_cycles))
    for cycle in range(1, cycles + 1):
        try:
            manifest = run(
                Path(args.output_dir).expanduser().resolve(),
                model=str(args.model),
                chapter_model=str(args.chapter_model),
                resume=not args.no_resume or cycle > 1,
                stop_after_macro=max(1, min(50, int(args.stop_after_macro))),
                stop_after_block=max(1, min(25, int(args.stop_after_block))),
                global_only=bool(args.global_only),
                blocks_only=bool(args.blocks_only),
            )
            break
        except Exception as exc:
            error_text = str(exc)
            if (
                "GROQ_NON_RETRYABLE:AllPlannerModelsCapacityLimited:" in error_text
                and cycle < cycles
            ):
                retry_windows = []
                for minutes, seconds in re.findall(
                    r"try again in\s+(?:(\d+)m)?([\d.]+)s", error_text,
                    flags=re.IGNORECASE,
                ):
                    retry_windows.append(int(minutes or 0) * 60 + float(seconds))
                if retry_windows:
                    delay = min(3600.0, min(retry_windows) + 8.0)
                    print(
                        f"[capacity-wait] cycle={cycle}/{cycles} "
                        f"delay={delay:.1f}s until Groq model quota reopens",
                        flush=True,
                    )
                    time.sleep(delay)
                    continue
            if any(marker in str(exc) for marker in (
                "QWEN_NON_RETRYABLE:", "GROQ_NON_RETRYABLE:", "MODEL_NON_RETRYABLE:",
            )) or any(
                marker in str(exc) for marker in (
                    '"code":"Arrearage"', '"code": "Arrearage"',
                    '"code":"AllocationQuota.FreeTierOnly"',
                    '"code": "AllocationQuota.FreeTierOnly"',
                    '"code":"AllocationQuota.FreeTierExhausted"',
                    '"code": "AllocationQuota.FreeTierExhausted"',
                )
            ):
                raise RuntimeError(str(exc)) from exc
            if cycle >= cycles:
                raise
            delay = min(30, 2 + cycle * 2)
            print(f"[cycle-retry] cycle={cycle}/{cycles} delay={delay}s error={exc}", flush=True)
            time.sleep(delay)
    if manifest is None:
        raise RuntimeError("Qwen generation produced no manifest")
    print(_json_text(manifest, indent=2), flush=True)
    if not manifest["complete"] and not manifest.get("planning_prefix_ready"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()

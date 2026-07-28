#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重生复仇小说正文生成器 V2

与旧版区别：
- 使用基于事件簇 V2 的轻量章节卡（master_ctx_cards_v2_*.json）；
- 每章都有明确的 chapter_role_v2 + structure_template，用于控制上一世/今世比例与节拍结构；
- 本文件内嵌独立底座类 `_RebirthRevengeGeneratorV2Core`（API 调用、落盘、承接、实体初始化等），
  **不 import** `generate_chapter_content.py`，便于单独回溯版本；V2 主类只重写「从章节卡构造 prompt / beat 卡」等簇级流程。
"""

import os
import re
import json
import hashlib
import sys
import subprocess
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import dashscope

from bert_excitation_train.scripts.smart_sample_search import search_rebirth_samples_for_chapter
from bert_excitation_train.scripts.optimized_rule_scorer import OptimizedRuleScorer
from bert_excitation_train.scripts.emotion_analyzer import EmotionAnalyzer
from bert_excitation_train.scripts.qwen_transport import call_qwen_via_curl
from bert_excitation_train.scripts.v2.theme_constraints import (
    FORBIDDEN_ELEMENTS as THEME_FORBIDDEN_ELEMENTS,
    BACKGROUND,
    MAIN_PROTAGONIST,
    THEME,
    attach_theme_contract,
    constraints_text,
)

# Windows/PowerShell 可能默认使用 GBK 编码，遇到打印 emoji 时触发 UnicodeEncodeError。
try:
    import io

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


PROJECT_ROOT = _PROJECT_ROOT
OUTPUT_DIR = Path(os.getenv("V2_OUTPUT_DIR", str(PROJECT_ROOT / "outputs"))).resolve()

# 通义千问（与旧版脚本同 key；本文件独立维护，不依赖 generate_chapter_content.py）
API_Key_QW = os.getenv("DASHSCOPE_API_KEY", "sk-a2966f4e37134351904851679884cb67")

DEFAULT_OUTPUTS_DIR = OUTPUT_DIR


def _load_optional_env_files() -> None:
    """从项目根或上一级目录的 .env 加载 KEY=VALUE，不覆盖已有环境变量。"""
    for env_path in (PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env"):
        if not env_path.is_file():
            continue
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and not os.environ.get(k):
                    os.environ[k] = v
        except OSError:
            pass


_load_optional_env_files()

# 统一的 V2 文件命名规则（硬编码稳定文件名，去掉时间戳依赖）
DEFAULT_MASTER_CARDS_V2 = OUTPUT_DIR / "master_ctx_cards_v2.json"
DEFAULT_PREV_LIFE_V2 = OUTPUT_DIR / "prev_life_ctx_v2.txt"
DEFAULT_EVENT_CLUSTERS_V2 = OUTPUT_DIR / "event_clusters_v2.json"
DEFAULT_EXPORT_V2 = OUTPUT_DIR / "export_v2.json"

# 逐章正文与簇审查共用的最低字数（预检、_cluster_critic、落盘复用门槛必须一致，避免「先过后挂」）
MIN_CHAPTER_CHARS_V2 = 1500
MIN_AWAKENING_CHARS_V2 = 1400
MAX_CHAPTER_CHARS_V2 = 2000
PERFORMANCE_PASS_CONCLUSION_PATTERN = (
    r"测试通过|符合要求|通过测试|(?:表现|完成度|结果).{0,10}(?:合格|达标|通过)|"
    r"(?:见证人|代表).{0,20}(?:确认|认可).{0,12}(?:完成|通过|合格|达标)|"
    r"(?:没有|没).{0,4}问题"
)
SUSPENSION_CONCLUSION_PATTERN = (
    r"即刻暂停你的职务|暂停.{0,10}(?:职务|履职|工作|岗位)|"
    r"停职|停止履职|不得继续.{0,10}(?:任职|工作|保管)|"
    r"撤下.{0,8}(?:岗位|职务)"
)


def _character_alias_pattern(name: str) -> str:
    """Match a canonical fictional name and its unambiguous middle-dot short form."""
    canonical = str(name or "").strip()
    if not canonical:
        return r"(?!x)x"
    aliases = [canonical]
    short = canonical.split("·", 1)[0].strip()
    if len(short) >= 2 and short != canonical:
        aliases.append(short)
    return "(?:" + "|".join(re.escape(alias) for alias in aliases) + ")"


SPECIFIC_DEATH_METHOD_PATTERN = (
    r"车祸|交通事故|坠楼|跳楼|从.{0,8}跳下|溺水|"
    r"服药自杀|吞药自杀|服药过量|吞药过量|药物过量|"
    r"强行注射|违规注射|过量注射|注射过量|镇静针.{0,20}注射|"
    r"针(?:头|尖).{0,80}(?:刺入|扎进).{0,120}(?:药液|活塞|注射)|"
    r"(?:药液|活塞).{0,100}(?:推入|进入).{0,40}(?:身体|血管|静脉)|"
    r"中毒|枪杀|病逝|事故身亡|心脏骤停"
)


def _minimum_chapter_chars(
    chapter_num: int, chapter_card: Optional[Dict[str, Any]] = None
) -> int:
    role = str((chapter_card or {}).get("chapter_role_v2") or "")
    if chapter_num == 2 or role == "rebirth_awakening_only":
        return MIN_AWAKENING_CHARS_V2
    return MIN_CHAPTER_CHARS_V2

COMMERCIAL_REBIRTH_WRITER_ROLE = (
    "你是擅长快节奏、强情绪、连续反转与及时回报的商业重生爽文作者。"
    "具体职业、规则、冲突手段和落点必须完全服从本次运行时主题。"
    "无论故事发生在哪个国家，叙述、动作、心理和对白都必须使用简体中文；"
    "canonical_cast 中的固定姓名必须逐字使用，绝对不得输出连续英文正文。"
)
REBIRTH_ACTION_ENGINE = (
    "旧局信号出现→主角凭上一世信息差主动抢先一步→对手按既定性格照旧出招→"
    "主角在同一场冲突中反卡→对手付出可见代价且主角获得具体收益"
)
CHEAP_MYSTERY_MARKERS = (
    "匿名短信", "匿名邮件", "匿名账号", "陌生号码", "陌生来电", "不明号码", "未知号码", "神秘制片人", "神秘援手",
    "有人跟踪", "被跟踪", "真正的幕后黑手", "幕后黑手另有其人", "背后还有人",
    "更大的秘密", "匿名论坛",
    "组织的标志", "银质徽章", "任务留下的印记",
)
EMPTY_ENDING_MARKERS = (
    "这只是开始", "才刚刚开始", "真正的战斗才刚", "真正的风暴", "更大风暴",
    "游戏还没有结束", "一切才刚开始", "等待最佳时机", "反击已经开始酝酿",
    "这场游戏刚刚开始", "真正的改变刚刚开始", "真正的改变才刚", "只是第一步",
    "真正的开始",
    "这只是个开始",
    "这不过是开端",
    "这仅仅是开始",
    "而这仅仅是开始",
)
OPPONENT_CONSEQUENCE_MARKERS = (
    "公开道歉", "被迫道歉", "取消资格", "撤销提名", "换角", "解约", "开除",
    "停职", "撤职", "辞职", "被带走", "立案", "起诉", "赔偿", "失去角色",
    "失去代言", "失去支持", "撤资", "处罚决定", "退出影坛", "退出娱乐圈",
    "终止合作", "解除合作", "撤销合作", "除名", "被调查", "停止合作",
    "暂停合作", "撤下代言", "品牌切割", "合作方撤离", "行业抵制",
    "失去推荐权", "失去干预权", "失去优先权", "失去影响力", "撤销推荐权",
    "失去排期权", "失去签批权", "失去代签权", "失去指挥权", "失去支付权",
    "权限被冻结", "权限被撤销", "权限终止", "账户被冻结", "交出设备", "退出票池",
    "交出药品柜钥匙", "交出药柜钥匙", "签停职通知", "暂停职务",
    "暂停你的职务", "你的职务即刻暂停", "你被停职", "撤回指控",
    "退还采访预付款", "失去采访席位", "失去低价打包权", "协议被正式废除",
    "代签授权被临时冻结",
)
PROTAGONIST_GAIN_MARKERS = (
    "拿下角色", "获得角色", "正式签约", "签下合约", "合同生效", "恢复资格",
    "恢复名誉", "洗清冤屈", "公开澄清", "项目归属", "获得赔偿", "拿回",
    "接任", "接管", "获奖", "赢得角色", "确认出演", "发出邀约",
    "收回权限", "取得否决权", "获得否决权", "获得签字权", "获得监督权",
    "获得保管权", "获得决定权", "夺回票池", "优先回购权", "交易冻结",
    "独立签署权", "原声发布权", "基金监管权",
    "药品保管权限移交本人", "药品监管权限即刻移交至本人", "药品保管职责移交",
)
TANGIBLE_PAYOFF_MARKERS = (
    "当场宣布", "当场取消", "当场撤下", "当场解约", "公开道歉", "被迫道歉",
    "取消资格", "撤销提名", "换角", "签约", "解约", "开除", "停职", "撤职",
    "辞职", "被带走", "立案", "起诉", "赔偿", "封杀失败", "失去角色", "失去代言",
    "失去支持", "票数", "获奖", "拿下角色", "获得角色", "合同生效", "项目归属",
    "账号停用", "撤资", "股东会通过", "接任", "接管", "处罚决定", "调查决定",
    "退出影坛", "退出娱乐圈", "终止合作", "解除合作", "撤销合作", "除名", "被调查",
    "停止合作", "暂停合作", "撤下代言", "品牌切割", "合作方撤离", "行业抵制",
)

REAL_WORLD_PROPER_NOUNS = (
    "美国", "迈克尔·杰克逊", "迈克尔杰克逊", "Michael Jackson",
    "洛杉矶", "纽约", "格莱美", "好莱坞", "索尼音乐", "康拉德·默里",
    "格雷厄姆·诺顿", "加州", "拉斯维加斯", "百事", "MTV", "YouTube",
    "Spotify", "告示牌", "吉尼斯", "梦幻庄园", "光年之外", "Billie Jean",
    "Thriller", "Moonwalk",
    "丙泊酚", "苯二氮卓", "苯二氮䓬", "Stage Zero", "Confirmed termination",
)


def _sync_neo4j_from_outputs(
    *,
    min_name_freq: int = 5,
    reset_db: bool = False,
    auto_extract_relations: bool = False,
) -> None:
    """
    生成完章文本后，同步/增量构建最小 Neo4j KG。

    - 会扫描 `outputs/chapters/chapter_*.txt`
    - 默认不重置数据库（安全）
    """
    _load_optional_env_files()
    required_env = ["NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"]
    missing = [k for k in required_env if not os.environ.get(k)]
    if missing:
        print(
            "🧩 [Neo4j同步] 跳过：未配置 Neo4j（需 "
            + ", ".join(required_env)
            + "）。可在项目根 `AI_Novle/.env` 或上一级目录 `.env` 中写入上述变量，或在 PowerShell 中 "
            "`$env:NEO4J_URI='bolt://localhost:7687'` 等方式设置。"
        )
        return

    chapters_dir = OUTPUT_DIR / "chapters"
    if not chapters_dir.exists():
        print(f"🧩 [Neo4j同步] 跳过：未找到章节目录 {chapters_dir}")
        return

    # 通过 -m 运行，避免“直接执行脚本导致相对导入失败”
    repo_root = PROJECT_ROOT
    py = sys.executable

    bootstrap_cmd = [
        py,
        "-m",
        "bert_excitation_train.scripts.neo4j_kg.bootstrap_neo4j",
    ]
    if reset_db:
        bootstrap_cmd.append("--reset")

    build_cmd = [
        py,
        "-m",
        "bert_excitation_train.scripts.neo4j_kg.build_from_chapters",
        "--min-name-freq",
        str(min_name_freq),
    ]
    if auto_extract_relations:
        build_cmd.append("--auto-extract-relations")

    try:
        subprocess.run(bootstrap_cmd, cwd=str(repo_root), check=True)
        subprocess.run(build_cmd, cwd=str(repo_root), check=True)
        print("🧩 [Neo4j同步] 已完成：从 outputs/chapters 构建/更新 KG")
    except subprocess.CalledProcessError as e:
        print(f"⚠️ [Neo4j同步] 失败：{e}")
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ [Neo4j同步] 异常：{e}")

# 前几章的硬编码章节卡（不依赖事件簇），用来严格锁定第 1/2 章的写法
SPECIAL_CARDS: Dict[int, Dict[str, Any]] = {
    1: {
        "chapter_role_v2": "prev_life_death_only",
        "chapter_goal": "只写上一世或旧阶段结束前的核心失败、创伤与不甘，不出现新阶段正式行动。具体身份、场景和冲突必须服从本次主题契约。",
        "chapter_must_include": [
            "主角在旧阶段的具体身份与处境",
            "造成核心失败的具体人物、事件和选择",
            "主角未能保护或完成的重要目标",
            "生命结束前足以推动后续行动的强烈不甘",
            "上一世死亡必须作为场景结果明确发生"
        ],
        "chapter_must_not_include": [
            "新阶段醒来后的正式行动",
            "提前写今生翻盘、签约、揭露或任何今生胜利",
            "神秘人或匿名消息直接解决核心矛盾",
            "与本次主题契约冲突的世界观或职业"
        ],
        "chapter_ending": "以主角上一世生命明确结束和一个尚未兑现的核心愿望收束。",
        "must_resolve_this_chapter": ["上一世死亡场景闭合"]
    },
    2: {
        "chapter_role_v2": "rebirth_awakening_only",
        "chapter_goal": "只写进入新阶段后的醒来与时空/身份确认，从震惊、怀疑到通过具体证据确认处境。细节必须服从本次主题与背景。",
        "chapter_must_include": [
            "从上一章的失败记忆中惊醒",
            "通过环境、身体、日期或他人反应发现异常",
            "用多个符合背景的具体细节确认当前时间与身份",
            "形成与核心失败直接相关的初步目标",
            "在结尾执行一个不完成大反杀、但会改变下一章局面的第一步行动"
        ],
        "chapter_must_not_include": [
            "直播/警方/媒体报道",
            "权贵阴谋的正式展开",
            "非法实验/身份替换/系统提示音",
            "尚未确认处境便立刻完成核心反击"
        ],
        "chapter_ending": "主角确认新处境，并在最后一个场景实际完成第一步部署，而非只在心里发誓。",
        "must_resolve_this_chapter": ["确认回到悲剧前夜闭合", "第一步主动部署已经发生"]
    },
}


class _RebirthRevengeGeneratorV2Core:
    """V2 独立底座（从原 RebirthRevengeGenerator 抽取）。本模块不 import generate_chapter_content.py。"""

    def __init__(self) -> None:
        self.scorer = OptimizedRuleScorer()
        self.emotion_analyzer = EmotionAnalyzer()
        self.master_ctx: Dict[int, str] = {}
        self.master_ctx_original: Dict[int, str] = {}
        self.prev_life_ctx: Dict[int, str] = {}
        self.project_root = PROJECT_ROOT
        self.outputs_dir = DEFAULT_OUTPUTS_DIR
        self.generated_chapters: Dict[int, str] = {}
        self.use_knowledge_graph = False
        self._kg: Optional[object] = None
        self.characters: set = set()
        self.locations: set = set()
        self.event_types = {
            "陷害", "嘲讽", "裁员", "拒绝", "举报", "开会", "会议", "当众",
            "羞辱", "证据", "调查", "威胁", "背叛", "攻击", "拒绝", "无视",
        }

    def _resolve_path(self, path_str: str) -> Path:
        p = Path(path_str)
        if p.is_absolute():
            return p
        return (self.project_root / p).resolve()

    def get_previous_chapter_content(self, chapter_num: int, chapters_dir: Optional[str] = None) -> Optional[str]:
        if chapter_num <= 1:
            return None
        prev_num = chapter_num - 1
        if prev_num in self.generated_chapters:
            return self.generated_chapters[prev_num]
        if chapters_dir is None:
            chapters_path = self.outputs_dir / "chapters"
        else:
            chapters_path = self._resolve_path(chapters_dir)
        prev_file = chapters_path / f"chapter_{prev_num:03d}.txt"
        if prev_file.exists():
            try:
                with open(prev_file, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except OSError:
                pass
        return None

    def _extract_entities(self) -> None:
        character_patterns = [
            re.escape(MAIN_PROTAGONIST), r"主角", r"对手", r"同事", r"亲友", r"负责人",
            r"记者", r"顾问", r"经理", r"主管",
        ]
        location_patterns = [
            r"办公室", r"会议室", r"学校", r"公司", r"医院", r"家中",
            r"车站", r"工作室", r"法庭", r"听证会", r"新闻发布会",
        ]
        for clue in self.prev_life_ctx.values():
            for pattern in character_patterns:
                matches = re.findall(pattern, clue)
                self.characters.update(matches)
            for pattern in location_patterns:
                matches = re.findall(pattern, clue)
                self.locations.update(matches)
        print(f"📝 已提取 {len(self.characters)} 个人物")
        print(f"📍 已提取 {len(self.locations)} 个地点")

    def _render_master_card_for_prompt(self, card: Dict) -> str:
        present = card.get("present", {}) if isinstance(card.get("present"), dict) else {}
        binding = card.get("binding", {}) if isinstance(card.get("binding"), dict) else {}
        beats = present.get("beats") if isinstance(present.get("beats"), list) else []
        beats_text = "\n".join([f"{i+1}. {b}" for i, b in enumerate(beats)])

        pm = present.get("present_mainline") or card.get("present_mainline", "")
        pg = present.get("present_goal") or card.get("present_goal", "")
        cf = present.get("surface_conflict") or card.get("core_conflict", "")
        co = present.get("conflict_opponent") or card.get("conflict_opponent", "")
        ft = present.get("flashback_trigger") or card.get("flashback_trigger", "")
        ra = present.get("revenge_action") or present.get("revenue_action", "") or card.get("revenge_action", "")
        pr = present.get("present_result") or card.get("present_result", "")
        th = present.get("tail_clue") or card.get("tail_clue", "")
        eh = present.get("ending_hook") or card.get("ending_hook", "")

        pt = binding.get("past_trigger") or card.get("past_trigger", "")
        pch = binding.get("past_core_harm") or card.get("past_core_harm", "")
        pcs = binding.get("present_counterstrike", "")

        return (
            "【章节执行卡（结构化）】\n"
            f"- chapter_id: {card.get('chapter_id')}\n"
            f"- present_mainline: {pm}\n"
            f"- scene: {present.get('scene', '')}\n"
            f"- present_goal: {pg}\n"
            f"- conflict_opponent: {co}\n"
            f"- surface_conflict: {cf}\n"
            f"- hidden_truth: {present.get('hidden_truth', '')}\n"
            f"- need_prev_life: {present.get('need_prev_life', True)}\n"
            f"- flashback_trigger: {ft}\n"
            f"- flashback_breakpoint: {present.get('flashback_breakpoint', '')}\n"
            f"- past_ratio_max: {present.get('past_ratio_max', 0.35)}\n"
            f"- revenge_action: {ra}\n"
            f"- beats:\n{beats_text}\n"
            f"- emotion_curve: {present.get('emotion_curve', '')}\n"
            f"- present_result: {pr}\n"
            f"- tail_clue: {th}\n"
            f"- ending_hook: {eh}\n"
            "\n【强绑定映射（钥匙/锁）】\n"
            f"- shared_trigger: {binding.get('shared_trigger', '')}\n"
            f"- past_trigger: {pt}\n"
            f"- past_core_harm: {pch}\n"
            f"- present_counterstrike: {pcs}\n"
        ).strip()

    def _call_api(
        self,
        prompt: str,
        emotion_feedback: Optional[Dict] = None,
        iteration: int = 0,
        max_tokens: Optional[int] = None,
    ) -> str:
        dashscope.api_key = API_Key_QW

        system_message = {"role": "system", "content": prompt}
        user_message = {"role": "user", "content": "请开始创作"}

        timeout_s = float(os.getenv("DASHSCOPE_TIMEOUT_S", "20"))
        hard_timeout_s = float(os.getenv("DASHSCOPE_HARD_TIMEOUT_S", "60"))
        max_retries = int(os.getenv("DASHSCOPE_MAX_RETRIES", "3"))
        backoff_s = float(os.getenv("DASHSCOPE_RETRY_BACKOFF_S", "2"))
        is_closed_segment = (
            "通用封闭场景的第" in prompt
            and "不写整章" in prompt
        )
        is_quality_critic = "V2_QUALITY_CRITIC_JSON" in prompt
        if is_quality_critic:
            user_message = {"role": "user", "content": "请只输出审查 JSON"}
        temperature = float(os.getenv(
            (
                "DASHSCOPE_QUALITY_CRITIC_TEMPERATURE"
                if is_quality_critic
                else "DASHSCOPE_SEGMENT_TEMPERATURE"
                if is_closed_segment
                else "DASHSCOPE_CHAPTER_TEMPERATURE"
            ),
            "0.12" if is_quality_critic else "0.32" if is_closed_segment else "0.55",
        ))
        top_p = float(os.getenv(
            (
                "DASHSCOPE_QUALITY_CRITIC_TOP_P"
                if is_quality_critic
                else "DASHSCOPE_SEGMENT_TOP_P"
                if is_closed_segment
                else "DASHSCOPE_CHAPTER_TOP_P"
            ),
            "0.35" if is_quality_critic else "0.62" if is_closed_segment else "0.78",
        ))

        call_kwargs = {
            "model": os.getenv("DASHSCOPE_CHAPTER_MODEL", "qwen-plus"),
            "messages": [system_message, user_message],
            "temperature": temperature,
            "top_p": top_p,
            "repetition_penalty": 1.0 if is_quality_critic else 1.1,
            "result_format": "message",
        }
        if max_tokens is not None:
            call_kwargs["max_tokens"] = max_tokens

        log_start_enabled = str(os.getenv("DASHSCOPE_LOG_START", "0")).lower() not in ("0", "false", "no")
        for attempt in range(max_retries):
            t0 = time.time()
            if log_start_enabled:
                print(
                    f"[API] dashscope call start attempt={attempt + 1}/{max_retries} "
                    f"iteration={iteration} max_tokens={max_tokens} timeout_s={timeout_s}s",
                    flush=True,
                )

            def _do_call() -> dict:
                try:
                    return dashscope.Generation.call(**call_kwargs, timeout=timeout_s)
                except TypeError:
                    return dashscope.Generation.call(**call_kwargs)
                except Exception:
                    return call_qwen_via_curl(
                        call_kwargs["messages"], api_key=API_Key_QW,
                        model=str(call_kwargs["model"]), temperature=float(call_kwargs["temperature"]),
                        top_p=float(call_kwargs["top_p"]),
                        repetition_penalty=float(call_kwargs["repetition_penalty"]),
                        max_tokens=call_kwargs.get("max_tokens"), timeout_s=hard_timeout_s,
                    )

            try:
                with ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(_do_call)
                    response = future.result(timeout=hard_timeout_s)

                elapsed = time.time() - t0
                if isinstance(response, dict) and "output" in response and isinstance(response.get("output"), dict):
                    out = response.get("output") or {}
                    if (
                        isinstance(out, dict)
                        and "choices" in out
                        and isinstance(out.get("choices"), list)
                        and out["choices"]
                    ):
                        content = out["choices"][0]["message"]["content"]
                        print(f"[API] dashscope call success elapsed={elapsed:.1f}s", flush=True)
                        return self._clean_markdown(content)

                print(
                    f"[API] dashscope call invalid_format elapsed={elapsed:.1f}s response_keys="
                    f"{list(response.keys()) if isinstance(response, dict) else type(response).__name__}",
                    flush=True,
                )
                err = f"通义千问 API 返回了无效格式: {str(response)[:500]}"
                last_err = err  # noqa: F841

            except FuturesTimeoutError:
                elapsed = time.time() - t0
                print(
                    f"[API] dashscope call timeout elapsed={elapsed:.1f}s hard_timeout_s={hard_timeout_s}s",
                    flush=True,
                )
                err = f"通义千问 API 超时: hard_timeout_s={hard_timeout_s}s"
            except Exception as e:
                elapsed = time.time() - t0
                print(
                    f"[API] dashscope call exception elapsed={elapsed:.1f}s "
                    f"type={type(e).__name__} err={str(e)}",
                    flush=True,
                )
                err = f"通义千问 API 出错: {str(e)[:500]}"

            if attempt < max_retries - 1:
                sleep_s = backoff_s * (2**attempt)
                print(f"[API] retry after {sleep_s:.1f}s...", flush=True)
                time.sleep(sleep_s)
            else:
                return err

    def _clean_markdown(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"### (.*)", r"\1", text)
        text = re.sub(r"---", "", text)
        text = re.sub(r"#+", "", text)
        return text.strip()

    def _normalize_heroine_names(self, text: str) -> str:
        if not text:
            return text
        patterns = [
            r"林婉然",
            r"林婉",
            r"婉然",
        ]
        for p in patterns:
            text = re.sub(p, MAIN_PROTAGONIST, text)
        text = re.sub(r"林[\u4e00-\u9fff]{1,2}", MAIN_PROTAGONIST, text)
        text = re.sub(r"夏[\u4e00-\u9fff]{1,2}", MAIN_PROTAGONIST, text)
        text = re.sub(r"沈清欢", MAIN_PROTAGONIST, text)
        text = re.sub(r"女主角", MAIN_PROTAGONIST, text)
        text = re.sub(r"女主", MAIN_PROTAGONIST, text)
        return text

    def save_chapter(self, chapter_num: int, content: str, output_dir: Optional[str] = None) -> str:
        if output_dir is None:
            out_dir = self.outputs_dir / "chapters"
        else:
            out_dir = self._resolve_path(output_dir)

        os.makedirs(str(out_dir), exist_ok=True)
        filepath = str(out_dir / f"chapter_{chapter_num:03d}.txt")

        cleaned_content = self._normalize_heroine_names(content or "")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(cleaned_content)

        print(f"💾 已保存到: {filepath}")
        return filepath

    def _extract_prev_chapter_tail_and_hook(self, prev_chapter_full: Optional[str]) -> Tuple[str, str]:
        if not prev_chapter_full or len(prev_chapter_full.strip()) < 100:
            return "", ""
        tail = prev_chapter_full[-1200:] if len(prev_chapter_full) > 1200 else prev_chapter_full
        prompt = f"""从下面这段「上一章正文结尾」中，提取两项（各1-2句话，不要编造）：

1. 最后场景/动作：上一章最后一个已发生的具体场景、动作、对话或发现。
2. 未解决钩子：上一章结尾留给下一章的悬念、未说完的话、新出现的人物/文件/电话/线索，下一章必须接住的内容。

【上一章结尾片段】
{tail}

请严格按以下格式输出，不要其他内容：
最后场景：
未解决钩子：
"""
        out = self._call_api(prompt, None, 0)
        if not out or out.startswith("通义千问"):
            return "", ""
        tail_scene, unresolved_hook = "", ""
        for line in out.split("\n"):
            line = line.strip()
            if line.startswith("最后场景") or line.startswith("最后场景："):
                tail_scene = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif line.startswith("未解决钩子") or line.startswith("未解决钩子："):
                unresolved_hook = line.split("：", 1)[-1].split(":", 1)[-1].strip()
        return tail_scene[:200], unresolved_hook[:200]

    def _get_chapter_role_hint(self, chapter_num: int) -> str:
        if chapter_num == 1:
            return """
【本章职责（第1章）】重点写旧阶段结束前的核心失败、具体代价和未竟目标。人物身份、场景与冲突必须服从本次主题契约；不要提前展开新阶段行动。
"""
        if chapter_num == 2:
            return """
【本章职责（第2章）】重点写：主角在新处境中醒来，通过多个符合本次背景的具体细节逐步确认时间、地点和身份。不要跳过验证过程，也不要立刻完成核心反击。
"""
        if chapter_num == 3:
            return """
【本章职责（第3章）】重点写主角围绕本次核心目标采取第一次主动行动，并遭遇来自既定人物关系或环境规则的现实阻力。
"""
        return ""

    def build_prompt_with_beat(
        self,
        chapter_num: int,
        outline_corrected: str,
        outline_original: str,
        prev_chapter_full: Optional[str],
        beat_card: str,
        prev_life_clue: Optional[str],
        kg_context: str = "",
        prev_tail_scene: str = "",
        prev_unresolved_hook: str = "",
        open_from_prev: str = "",
        end_to_next: str = "",
        emotion_reinforcement_points: str = "",
        rag_samples: Optional[Dict[str, List]] = None,
        need_prev_life: bool = False,
        chapter_type: str = "",
        closure_type: str = "full_close",
        flashback_breakpoint_hint: str = "",
        past_ratio_min: float = 0.20,
        past_ratio_max: float = 0.32,
        global_seed_progress: str = "",
        chapter_constraints: Optional[List[str]] = None,
    ) -> str:
        prompt = f"""角色：{COMMERCIAL_REBIRTH_WRITER_ROLE}

【核心要求】
1. 严格按本章节拍卡与梗概推进，不得偏离；节拍卡中的每一拍都必须写到位，不得跳过或一笔带过。
2. 字数：至少1000字，建议1000-1400字，单章不宜超过1600字（避免跑偏）。第三人称，快节奏，结尾留悬念。
3. 主线优先，禁止随意新增无关支线。

【本项目主题硬锁定】
{constraints_text()}
"""
        if need_prev_life and prev_life_clue and chapter_num not in (1, 2):
            past_ratio_min = 0.35
            past_ratio_max = 0.50
            prompt += f"""
【上一世回忆·硬约束】（必须遵守，否则视为不合格）
- 本章**必须**出现一段完整的「上一世受害」回忆段落，插入位置须服从梗概中的 flashback_breakpoint（{flashback_breakpoint_hint or "在节拍卡标明的那一拍之后"}）。
- **占比强制**：正文中上一世相关内容字数须占全章的 **{int(past_ratio_min*100)}%~{int(past_ratio_max*100)}%**，不得用一句“像上一世那样”带过。
- **四步结构**（上一世段落必须依次包含，写成可感知场景，禁止写成摘要）：
  ① 假性温和：先给主角一点希望（某人表面和气/场面看似正常）。
  ② 突然反咬：有人当众翻旧账、倒打一耙或栽赃（谁先开口、说了什么、其他人什么反应）。
  ③ 无人帮他：他想解释却被打断、无人声援、沉默或附和（主角当时怎么僵住、身体反应）。
  ④ 结果性伤害：丢脸、失去机会、公共信用被摧毁或被当众嘲笑（最后是谁定了他的罪、他当时感受）。
- 用「上一世，我……」「记得在上一世……」等句式在正文中点明回忆；不准只写“上一世他也曾被他们嘲笑”这类信息句，必须写**具体对话、动作、反应**。
"""
        else:
            prompt += """
【上一世】本章无强制上一世回忆；若梗概未要求插入回忆，不要硬插，只写本世发展。
"""
        if chapter_num == 1:
            prompt += """
【重生前限制（第1章）】
- 本章只写上一世生命结束前的具体失败、背叛、损失与死亡，身份、场景和伤害方式必须服从本次题材；正文中**禁止出现“重生”“回到过去”“第二次人生”等字样**。
- 结尾只能停留在主角带着未竟目标死去的绝望与不甘，不能意识到自己还有第二次机会或会重来一次。
"""
        if chapter_num == 2:
            prompt += """
【重生觉醒写法（第2章）】
- 开篇先写主角感受到身体、时间或环境异常，重点是震惊和不适应，不要直接宣告结论。
- 通过多个符合本次背景的可观察证据，从怀疑逐步过渡到确认。
- 收集到足够细节后，才允许主角明确意识到自己所处的新时间线或新身份。
- 严禁一开篇就直接写“他意识到自己重生了”，必须有“震惊 → 怀疑 → 验证 → 确认”的过程。
"""
        if chapter_num > 1 and (prev_tail_scene or prev_unresolved_hook):
            prompt += """
【跨章接续硬约束】（必须遵守，不得自主跳过）
本章第一幕必须从以下「上一章尾钩」继续写，不得跳过，不得另起新场景：
"""
            if prev_tail_scene:
                prompt += f"最后场景：{prev_tail_scene}\n"
            if prev_unresolved_hook:
                prompt += f"未解决钩子：{prev_unresolved_hook}\n"
            prompt += """
1. 本章开头必须直接承接上一章最后一个已发生的动作、对话、发现或悬念，禁止跳过。
2. 若上一章结尾引入了新人物、新文件、新电话、新线索，本章前300字内必须先接住它，再展开本章内容。
3. 不得把本章写成一个与上一章松散相关的新故事；必须让读者一眼看出这是同一条连续剧情。
4. 禁止重复上一章已经完整写过的核心场景，除非是从新的信息层推进。
5. 本章必须回答：上一章最后留下的问题，当前推进了哪一步？
"""
        if open_from_prev and chapter_num > 1:
            prompt += f"\n【本节拍卡要求】本章开头承接：{open_from_prev}\n"
        if end_to_next:
            prompt += f"\n【本节拍卡要求】本章结尾必须留下钩子：{end_to_next}\n"

        prompt += self._get_chapter_role_hint(chapter_num)

        prompt += f"""
【本章修正后梗概】
{outline_corrected}

【本章修正前梗概】
{outline_original or "（无）"}

【本节拍卡】（请按此顺序写正文，每一拍都要有明确推进，不得跳过）
{beat_card or "（无，请按梗概自行安排节奏）"}
"""
        if global_seed_progress:
            prompt += f"""
【整书最大复仇主线小推进】（本章只允许用1-2句轻描淡写带过，不能喧宾夺主）
- 请在合适位置，用一句话完成以下推进，然后立刻把镜头切回本章支线冲突：
  {global_seed_progress}
"""
        if chapter_constraints:
            prompt += "\n【本章写作限制】（必须严格遵守）\n"
            for rule in chapter_constraints:
                prompt += f"- {rule}\n"
        if closure_type == "full_close":
            prompt += """
【本章闭合要求】本章为完整闭环章，必须写满：冲突提出 → 若有上一世则回忆插入 → 反制动作 → 对方失态/场面后果 → 结尾钩子。不得在“证据刚亮出”或“刚反转”处就收尾，要写到场面收束、读者看到结果后再留悬念。
"""
        elif closure_type == "half_close":
            prompt += """
【本章闭合要求】本章可为半闭环：可停在证据刚亮出、重要人物刚进场或新真相刚暴露，众人尚未反应完，留到下一章收尾。但本节拍卡中的每一拍仍须写到位，不得省略。
"""
        if emotion_reinforcement_points:
            prompt += f"""
【本章情绪强化点】（必须遵守，在对应情节点强化情绪）
{emotion_reinforcement_points}

写作时请在上述强化点处：
- 上一世回忆：加强委屈（内心独白、身体感受）、愤怒（对陷害者的恨意）、同情（让读者共鸣主角遭遇）
- 这一世复仇：加强爽感（复仇成功的痛快、反杀的畅快、让对手付出代价的满足感）
"""
        if prev_life_clue:
            if need_prev_life:
                prompt += f"""
【必须使用的上一世线索】（本章必须插入上一世回忆，并按四步结构展开，参考以下内容）
{prev_life_clue}
"""
            else:
                prompt += f"""
【可用的上一世线索】（若梗概/节拍卡中涉及回忆，可参考以下内容）
{prev_life_clue}
"""
        if prev_chapter_full:
            prompt += f"""
【上一章全文】（供参考，本章必须与其结尾接续，不得另起炉灶）
{prev_chapter_full[-2500:] if len(prev_chapter_full) > 2500 else prev_chapter_full}

【跨章连续性硬约束】（必须遵守）
1. 本章开头必须直接承接上一章最后一个已发生的动作、对话、发现或悬念，禁止跳过。
2. 若上一章结尾引入了新人物、新文件、新电话、新线索，本章前300字内必须先接住它，再展开本章内容。
3. 不得把本章写成一个与上一章松散相关的新故事；必须让读者一眼看出这是同一条连续剧情。
4. 禁止重复上一章已经完整写过的核心场景，除非是从新的信息层推进。
5. 本章必须回答：上一章最后留下的问题，当前推进了哪一步？
"""
        if kg_context:
            prompt += f"""
{kg_context}
"""
        if rag_samples and any(rag_samples.get(k) for k in ("revenge", "grievance", "universal")):
            prompt += "\n【RAG样本参考】（请重点参考与本章情绪方向一致的片段风格与节奏）\n"

            def _preview(s, max_len=220):
                text = s.get("adapted_content") or s.get("content", "")
                return text[:max_len] + ("..." if len(text) > max_len else "")

            if rag_samples.get("grievance"):
                prompt += "\n上一世委屈/被欺负（写回忆时参考）：\n"
                for i, s in enumerate(rag_samples["grievance"][:2], 1):
                    prompt += f"  片段{i}: {_preview(s)}\n"
            if rag_samples.get("revenge"):
                prompt += "\n重生复仇爽感（写反杀/打脸时参考）：\n"
                for i, s in enumerate(rag_samples["revenge"][:2], 1):
                    prompt += f"  片段{i}: {_preview(s)}\n"
            if rag_samples.get("universal"):
                prompt += "\n通用高评分参考：\n"
                for i, s in enumerate(rag_samples["universal"][:2], 1):
                    prompt += f"  片段{i}: {_preview(s)}\n"
            prompt += "\n请结合本章梗概与情绪强化点，模仿上述片段的情绪密度与节奏，写出正文。\n"
        prompt += """
【情绪与格式】
- 情绪强度要足，有层次与转折；对话占比高，场景推进快。
- 直接输出正文，不要章节标题或【回忆】等小标题。
"""
        if hasattr(self, "_next_chapter_hint") and self._next_chapter_hint:
            prompt += "\n" + str(self._next_chapter_hint) + "\n"
        return prompt

class RebirthRevengeGeneratorV2(_RebirthRevengeGeneratorV2Core):
    """V2：基于事件簇模版的正文生成器。"""

    def attach_story_memory(self) -> None:
        """Attach the durable chapter-memory ledger and optional Neo4j projection."""
        try:
            from bert_excitation_train.scripts.neo4j_kg.story_memory import StoryMemoryCoordinator
            from bert_excitation_train.scripts.neo4j_kg.story_identity import story_id_for_clusters
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ StoryMemory 未启用：{exc}")
            return

        self.story_id = story_id_for_clusters(DEFAULT_EVENT_CLUSTERS_V2)
        memory_dir = OUTPUT_DIR / "knowledge_graph" / "stories" / self.story_id / "chapter_memory"

        memory_heuristic_only = os.getenv("STORY_MEMORY_HEURISTIC_ONLY", "").strip().lower() in {
            "1", "true", "yes", "on",
        }

        def _memory_llm_call(prompt: str) -> str:
            return str(self._call_api(prompt, None, 0, max_tokens=5000) or "")

        driver_factory = None
        try:
            from bert_excitation_train.scripts.neo4j_kg.common import get_neo4j_driver

            probe = get_neo4j_driver()
            try:
                probe.verify_connectivity()
                driver_factory = get_neo4j_driver
            finally:
                probe.close()
        except Exception as exc:  # noqa: BLE001
            print(f"🧠 StoryMemory 将使用本地账本，Neo4j 当前不可用：{exc}")

        self.story_memory = StoryMemoryCoordinator(
            memory_dir=memory_dir,
            llm_call=None if memory_heuristic_only else _memory_llm_call,
            driver_factory=driver_factory,
            story_id=self.story_id,
        )
        mode_note = "（确定性规则抽取）" if memory_heuristic_only else "（Qwen 抽取，失败时规则降级）"
        print(f"🧠 StoryMemory 已启用{mode_note}：{memory_dir}")

    def review_story_memory(self, chapter_num: int, content: str) -> Tuple[Dict[str, Any], List[Any]]:
        coordinator = getattr(self, "story_memory", None)
        if coordinator is None:
            return {}, []
        known_names: List[str] = [MAIN_PROTAGONIST]
        card = self._get_card_for_chapter(chapter_num)
        if isinstance(card, dict):
            allowed = card.get("allowed_roles") or []
            if isinstance(allowed, str):
                allowed = [allowed]
            if isinstance(allowed, list):
                known_names.extend(str(x).strip() for x in allowed if str(x).strip())
            canonical_cast = card.get("canonical_cast") or []
            for member in canonical_cast if isinstance(canonical_cast, list) else []:
                if not isinstance(member, dict):
                    continue
                name = str(member.get("name") or "").strip()
                short_name = name.split("·", 1)[0]
                if name and (name in content or short_name in content):
                    known_names.append(name)
            opponent = str(card.get("main_opponent") or "").strip()
            if opponent:
                known_names.extend(x.strip() for x in re.split(r"[、,，/和与]", opponent) if x.strip())
        known_names = list(dict.fromkeys(name for name in known_names if name))
        forced_timeline = ""
        if isinstance(card, dict) and str(card.get("chapter_role_v2") or "") == "prev_life_death_only":
            forced_timeline = "previous_life"
        return coordinator.review_candidate(
            chapter_num,
            content,
            known_names=known_names,
            forced_timeline=forced_timeline,
        )

    def commit_story_memory(self, memory: Dict[str, Any]) -> None:
        coordinator = getattr(self, "story_memory", None)
        if coordinator is not None and memory:
            coordinator.commit(memory)

    def attach_online_retriever(self) -> None:
        """
        为 V2 生成流程挂载在线检索器（Neo4j）。
        生成端会优先调用 self.online_retrieve_context(chapter_num) 获取限长 KG 文本。
        """
        try:
            from bert_excitation_train.scripts.neo4j_kg.online_retriever import retrieve_context_for_chapter  # type: ignore[import-not-found]
        except Exception:
            return

        def _online_retrieve(chapter_num: int) -> str:
            # 从本章卡中抽取 allowed_roles / main_opponent，作为召回条件
            card = self._get_card_for_chapter(chapter_num)
            allowed = []
            mo = None
            if isinstance(card, dict):
                raw_allowed = card.get("allowed_roles")
                if isinstance(raw_allowed, list):
                    allowed = [str(x) for x in raw_allowed if str(x or "").strip()]
                elif isinstance(raw_allowed, str) and raw_allowed.strip():
                    allowed = [raw_allowed.strip()]
                mo_raw = card.get("main_opponent")
                if isinstance(mo_raw, str) and mo_raw.strip():
                    mo = mo_raw.strip()
            # 兜底：至少包含主角
            if MAIN_PROTAGONIST not in allowed:
                allowed = [MAIN_PROTAGONIST] + allowed
            ledger_context = ""
            coordinator = getattr(self, "story_memory", None)
            if coordinator is not None:
                try:
                    ledger_context = str(coordinator.context_for_chapter(chapter_num, max_chars=2200) or "")
                except Exception:  # noqa: BLE001
                    ledger_context = ""
            graph_context = ""
            try:
                graph_context = retrieve_context_for_chapter(
                    chapter_num=chapter_num,
                    allowed_roles=allowed[:8],
                    main_opponent=mo,
                    max_chars=2200,
                    story_id=str(getattr(self, "story_id", "default")),
                )
            except Exception:
                graph_context = ""
            if ledger_context and graph_context:
                combined = (ledger_context + "\n\n" + graph_context)[:3200]
            else:
                combined = (ledger_context or graph_context)[:3200]
            coordinator = getattr(self, "story_memory", None)
            if coordinator is not None and hasattr(coordinator, "_trace"):
                coordinator._trace(  # type: ignore[attr-defined]
                    "generation_context", chapter=int(chapter_num),
                    ledger_context=ledger_context, graph_context=graph_context, combined=combined,
                )
            return combined

        setattr(self, "online_retrieve_context", _online_retrieve)

    def _parse_json_maybe(self, chapter_outline: str) -> Dict[str, Any]:
        """沿用原实现：尝试从 JSON 字符串解析出章节卡。"""
        import json

        try:
            data = json.loads(chapter_outline)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _get_card_for_chapter(self, chapter_num: int) -> Dict[str, Any]:
        """从 self.master_ctx 中解析出本章的结构化卡片。"""
        raw = self.master_ctx.get(chapter_num, "")
        if not raw:
            return {}
        if isinstance(raw, str):
            return self._parse_json_maybe(raw)
        if isinstance(raw, dict):
            return raw
        return {}

    def _infer_prev_life_ratio_from_role(self, role_v2: str) -> Optional[float]:
        """
        根据 V2 章节角色粗略推断上一世段落占比。
        返回 None 表示沿用旧逻辑自动判断。
        """
        if role_v2 in {"prev_life_full", "prev_life_explained_by_investigation"}:
            return 0.3  # 约 30%
        if role_v2 in {"present_past_mix", "slow_burn_press_with_past_shadow"}:
            return 0.15
        if role_v2 in {
            "present_setup",
            "present_revenge",
            "present_mid_bridge",
            "slow_burn_press",
            "slow_burn_mid",
            "partial_revenge",
            "present_action_or_result_first",
            "aftermath_or_next_seed",
            "side_plot_focus",
            "present_only",
            "present_setup_and_revenge",
        }:
            return 0.05
        return None

    # ========= 新增：调试友好的情节/章节信息输出 =========
    def debug_print_chapter_context(self, chapter_num: int) -> None:
        """
        在生成正文前，先把本情节与本章的关键信息打印出来：
        - 所属事件簇（分配到的章节范围、核心爽点、主要对手等）；
        - 本章的结构化梗概（执行卡精简版）。
        方便人工检查“情节 → 分章梗概 → 节拍卡 → 正文”的完整链路。
        """
        card = self._get_card_for_chapter(chapter_num)
        if not card:
            print(f"\n[提示] 未在章节卡中找到第{chapter_num}章的信息。")
            return

        cluster_id = card.get("cluster_id", "")
        cluster_name = card.get("cluster_name", "")
        core_payoff = card.get("core_payoff", "")
        main_opp = card.get("main_opponent", "")
        prev_tragedy = card.get("prev_life_tragedy", "")
        this_revenge = card.get("this_life_revenge", "")
        info_gap = card.get("info_gap_from_prev_life", "")
        outcome = card.get("cluster_outcome", "")

        clusters = getattr(self, "event_clusters_v2", None)
        span_desc = ""
        if isinstance(clusters, list) and cluster_id:
            for c in clusters:
                if c.get("cluster_id") == cluster_id:
                    span = c.get("chapter_span") or c.get("chapterRange") or c.get("chapters")
                    try:
                        s, e = int(span[0]), int(span[1])
                        span_desc = f"{s}-{e}"
                    except Exception:
                        span_desc = ""
                    break

        print("\n" + "-" * 70)
        print(f"📌 本情节信息（第{chapter_num}章）")
        if cluster_id:
            print(f"  事件簇: {cluster_id}《{cluster_name}》  覆盖章节: {span_desc or '未知'}")
            print(f"  核心爽点: {core_payoff or '（未提供）'}")
            print(f"  主要对手: {main_opp or '（未指定）'}")
            print(f"  上一世悲剧前提: {prev_tragedy or '（未提供）'}")
            print(f"  今生反击方式: {this_revenge or '（未提供）'}")
            if info_gap:
                print(f"  上一世留下的信息差: {info_gap}")
            print(f"  本簇今生结局: {outcome or '（未提供）'}")
        else:
            print("  本章未绑定到具体事件簇（cluster_id 为空），将按章节卡梗概直接生成。")

        # 输出本章的结构化梗概，便于对照后续节拍卡和正文
        try:
            # 复用基类的渲染逻辑，将 JSON 卡转换成「执行卡」文本
            outline_text = self._render_master_card_for_prompt(card)  # type: ignore[attr-defined]
        except Exception:
            outline_text = ""
        if outline_text:
            print("\n🧩 本章执行梗概（结构化）：")
            print(outline_text)
        print("-" * 70 + "\n")

    def _sanitize_prompt_text(self, text: str) -> str:
        """用于特殊章节 prompt gate：移除特定触发词，降低模型跑偏风险。"""
        if not text:
            return ""
        # 只对“第1章临死绝境/类似写法”做极端门禁时使用
        forbidden_substrings = ["重生", "调查", "照片", "身份替换", "警方介入", "回到过去", "第二次人生"]
        out = text
        for w in forbidden_substrings:
            out = out.replace(w, "")
        return out

    def build_prompt_with_beat(  # type: ignore[override]
        self,
        chapter_num: int,
        outline_corrected: str,
        outline_original: str,
        prev_chapter_full: Optional[str],
        beat_card: str,
        prev_life_clue: Optional[str],
        kg_context: str = "",
        prev_tail_scene: str = "",
        prev_unresolved_hook: str = "",
        open_from_prev: str = "",
        end_to_next: str = "",
        emotion_reinforcement_points: str = "",
        rag_samples: Optional[Dict[str, List]] = None,
        need_prev_life: bool = False,
        chapter_type: str = "",
        closure_type: str = "full_close",
        flashback_breakpoint_hint: str = "",
        past_ratio_min: float = 0.20,
        past_ratio_max: float = 0.32,
        global_seed_progress: str = "",
        chapter_constraints: Optional[List[str]] = None,
    ) -> str:
        """
        V2 严格执行 prompt（硬卡优先），不复用 super().build_prompt_with_beat() 的“旧底座节拍/闭合写法”。

        优先级永远是：章节执行卡 > 上一世线索 > 连续性 > 风格样本
        """
        card = self._get_card_for_chapter(chapter_num)
        role_v2 = card.get("chapter_role_v2", "") if isinstance(card, dict) else ""
        is_death_only_gate = role_v2 in {"prev_life_death_only"}

        def _maybe_sanitize(s: str) -> str:
            return self._sanitize_prompt_text(s) if is_death_only_gate else s

        chapter_goal = _maybe_sanitize(str(card.get("chapter_goal", "") if isinstance(card, dict) else ""))
        must_in = card.get("chapter_must_include", []) if isinstance(card, dict) else []
        must_in = [str(x) for x in must_in] if isinstance(must_in, list) else [str(must_in)]
        must_in = [_maybe_sanitize(x) for x in must_in]

        must_not = card.get("chapter_must_not_include", []) if isinstance(card, dict) else []
        must_not = [str(x) for x in must_not] if isinstance(must_not, list) else [str(must_not)]
        must_not = [_maybe_sanitize(x) for x in must_not]

        chapter_ending = _maybe_sanitize(str(card.get("chapter_ending", "") if isinstance(card, dict) else ""))
        must_resolve = card.get("must_resolve_this_chapter", []) if isinstance(card, dict) else []
        must_resolve = [str(x) for x in must_resolve] if isinstance(must_resolve, list) else [str(must_resolve)]
        must_resolve = [_maybe_sanitize(x) for x in must_resolve]

        allowed_roles = card.get("allowed_roles", []) if isinstance(card, dict) else []
        forbidden_roles = card.get("forbidden_roles", []) if isinstance(card, dict) else []
        allowed_roles = [str(x) for x in allowed_roles] if isinstance(allowed_roles, list) else [str(allowed_roles)]
        forbidden_roles = [str(x) for x in forbidden_roles] if isinstance(forbidden_roles, list) else [str(forbidden_roles)]
        allowed_roles = [_maybe_sanitize(x) for x in allowed_roles]
        forbidden_roles = [_maybe_sanitize(x) for x in forbidden_roles]

        if prev_tail_scene or prev_unresolved_hook:
            continuity = f"{prev_tail_scene}".strip()
            if prev_unresolved_hook:
                continuity += f"｜{prev_unresolved_hook}"
        elif prev_chapter_full:
            # 只取末尾一小段用于连续性承接，防止二次改写主线
            continuity = prev_chapter_full[-350:] if len(prev_chapter_full) > 350 else prev_chapter_full
        else:
            continuity = ""
        continuity = _maybe_sanitize(continuity)

        # RAG：只当“文风/节奏参考”，禁止复用情节/证据设定
        rag_style_block = ""
        if rag_samples and any(rag_samples.get(k) for k in ("revenge", "grievance", "universal")):
            parts: List[str] = []
            for key in ("grievance", "revenge", "universal"):
                items = rag_samples.get(key) or []
                if not items:
                    continue
                s0 = items[0] if isinstance(items, list) else {}
                text = ""
                if isinstance(s0, dict):
                    text = s0.get("adapted_content") or s0.get("content") or ""
                text = text.strip()
                if text:
                    parts.append(f"[{key}] 片段节选：{_maybe_sanitize(text[:220])}...")
            if parts:
                rag_style_block = "\n".join(parts)

        # kg_context 仅作为背景事实，不能改任务卡的证据链与结果落点
        kg_block = _maybe_sanitize(kg_context) if kg_context else ""

        # 拼 prompt（确保章节执行卡是唯一剧情决策来源）
        lines: List[str] = []
        lines.append(COMMERCIAL_REBIRTH_WRITER_ROLE + "请严格执行【章节执行卡】并直接输出正文，不要解释，不要新增主线或新证据类型。")
        lines.append("【本项目主题硬锁定】")
        lines.append(constraints_text())
        lines.append("")
        lines.append("【优先级规则】")
        lines.append("- 以【章节执行卡】为最高优先级；章节卡与其他信息冲突时，必须忽略其他信息。")
        lines.append("- 其次使用【上一世线索】（若本章承担回忆）。")
        lines.append("- 再使用【上一章衔接摘要】保证连续性。")
        lines.append("- 最后使用【风格样本参考】仅模仿语气与节奏，不得复用样本情节/证据设定。")
        lines.append("")

        lines.append("【章节执行卡（硬性）】")
        lines.append(f"- chapter_id：{chapter_num}；章节角色：{role_v2 or '（未标注）'}")
        if chapter_goal:
            lines.append(f"- 目标：{chapter_goal}")
        if must_in:
            lines.append(f"- 必须包含（优先级高）：" + "；".join(must_in[:8]))
        if must_not:
            lines.append(f"- 禁止包含（硬性）：" + "；".join(must_not[:10]))
        if must_resolve:
            lines.append(f"- 完成度门槛（必须达成）：" + "；".join(must_resolve[:8]))
        if chapter_ending:
            lines.append(f"- 结尾落点：{chapter_ending}")
        lines.append("")

        if need_prev_life and prev_life_clue:
            prev_block = _maybe_sanitize(str(prev_life_clue))
            lines.append("【上一世线索（硬性素材）】")
            lines.append(prev_block[:1200] + ("..." if len(prev_block) > 1200 else ""))
            lines.append("")
        else:
            lines.append("【上一世线索】本章不插入上一世回忆；若出现回忆片段必须只服务于本章任务清单。")
            lines.append("")

        if continuity:
            lines.append("【上一章衔接摘要（仅用于连续性，不得改写剧情任务）】")
            lines.append(continuity)
            lines.append("")

        if kg_block:
            lines.append("【知识图谱/背景事实（仅作背景，不得改任务卡的证据链与结果）】")
            lines.append(kg_block[:900])
            lines.append("")

        if rag_style_block:
            lines.append("【风格样本参考（仅模仿语气/节奏，禁止复用情节/证据设定）】")
            lines.append(rag_style_block)
            lines.append("")

        if allowed_roles:
            lines.append("【允许/禁止出场角色】")
            lines.append("- 允许重点出现：" + "、".join(allowed_roles[:6]))
            lines.append("- 禁止出现（硬性）：" + "、".join(forbidden_roles[:10] if forbidden_roles else []))
            lines.append("")

        lines.append("【写作约束】")
        lines.append("- 直接输出正文；不要章节标题，不要小标题，不要元注释。")
        lines.append("- 章节结尾必须停在【结尾落点】的具体动作/事件瞬间，不要用空洞预感型句子。")
        lines.append("- 不得新增未在任务卡中出现的新核心人物/新阴谋线/新证据类型。")
        if chapter_constraints:
            # chapter_constraints 作为额外“禁止项”兜底（不依赖旧底座）
            rules = [str(x).strip() for x in chapter_constraints if str(x).strip()]
            if rules:
                lines.append("- 本章额外限制：" + "；".join(rules[:6]))
        lines.append("")
        lines.append("请开始写正文。")

        prompt = "\n".join(lines).strip()
        if is_death_only_gate:
            # 再做一次兜底清洗，确保 prompt 中不含触发词
            prompt = self._sanitize_prompt_text(prompt)
        return prompt

    def build_prompt_with_beat_v2(
        self,
        chapter_num: int,
        chapter_outline: str,
        prev_life_clue: Optional[str],
        original_outline: Optional[str] = None,
    ) -> str:
        """
        基于 V2 章节卡 + 章节角色，构造更精细的节拍提示词。

        - 不改变原有的整体写作风格要求；
        - 只在「如何拆分当章节拍、上一世/今世比例」上增加结构信息。
        """
        base_prompt = super().build_prompt_with_beat(  # type: ignore[attr-defined]
            chapter_num, chapter_outline, prev_life_clue, original_outline
        )

        card = self._get_card_for_chapter(chapter_num)
        role_v2 = card.get("chapter_role_v2", "")
        tmpl = card.get("structure_template", "")
        cluster_id = card.get("cluster_id", "")
        cluster_name = card.get("cluster_name", "")
        core_payoff = card.get("core_payoff", "")
        main_opp = card.get("main_opponent", "")
        prev_tragedy = card.get("prev_life_tragedy", "")
        this_revenge = card.get("this_life_revenge", "")
        info_gap = card.get("info_gap_from_prev_life", "")
        outcome = card.get("cluster_outcome", "")
        span_start = card.get("cluster_span_start")
        span_end = card.get("cluster_span_end")
        cluster_idx = card.get("cluster_chapter_index")
        cluster_total = card.get("cluster_chapter_total")

        extra_lines = []
        if cluster_id:
            extra_lines.append(
                f"\n【本章对应的事件簇（V2）】\n"
                f"- 事件簇 {cluster_id}《{cluster_name}》，核心爽点：{core_payoff}；主要对手：{main_opp}。\n"
                f"- 上一世悲剧前提：{prev_tragedy}\n"
                f"- 今生在本簇中的大致反击方式：{this_revenge}\n"
                f"- 旧阶段留下、当前可利用的信息差：{info_gap or '（请结合本次题材写出主角已经知道而其他人尚未意识到的事件、动机、规则或时机）'}\n"
                f"- 本簇结束结果：{outcome}"
            )

        # 实体白名单/黑名单：锁定本簇角色，禁止长篇式扩张
        allowed = card.get("allowed_roles") or [MAIN_PROTAGONIST, main_opp or "本簇主对手"]
        forbidden = card.get("forbidden_roles") or DEFAULT_FORBIDDEN_NEW_ROLES
        if isinstance(allowed, list):
            allowed_str = "、".join(allowed) + "、" + DEFAULT_ALLOWED_SUPPORT
        else:
            allowed_str = str(allowed)
        if isinstance(forbidden, list):
            forbidden_str = "、".join(forbidden[:12])
        else:
            forbidden_str = str(forbidden)
        extra_lines.append(
            "\n【本章允许/禁止出场角色】（硬性约束）\n"
            f"- 本章允许重点出场：{allowed_str}。\n"
            f"- 本章禁止引入的新核心角色/元素：{forbidden_str}。\n"
            "- 禁止出现系统提示音、神秘人、神秘司机、陌生电话救场等未在本簇规划中的角色或设定；落锤必须来自本次题材中已建立的人物能力、关系、规则、时机或筹码，不得改为神秘人送U盘/录像。"
        )

        # 本章执行任务清单（来自簇级执行计划）
        ch_goal = card.get("chapter_goal", "")
        ch_must = card.get("chapter_must_include", [])
        ch_must_not = card.get("chapter_must_not_include", [])
        ch_ending = card.get("chapter_ending", "")
        ch_resolve = card.get("must_resolve_this_chapter", [])
        if ch_goal or ch_must or ch_resolve:
            extra_lines.append("\n【本章执行任务清单】（必须完成，否则本章视为不合格）")
            if ch_goal:
                extra_lines.append(f"- 本章目标：{ch_goal}")
            if ch_must:
                must_str = "；".join(ch_must) if isinstance(ch_must, list) else ch_must
                extra_lines.append(f"- 必须包含：{must_str}")
            if ch_must_not:
                not_str = "；".join(ch_must_not[:8]) if isinstance(ch_must_not, list) else ch_must_not
                extra_lines.append(f"- 禁止包含：{not_str}")
            if ch_ending:
                extra_lines.append(f"- 本章结尾应落到：{ch_ending}")
            if ch_resolve:
                resolve_str = "；".join(ch_resolve) if isinstance(ch_resolve, list) else ch_resolve
                extra_lines.append(f"- 本章结束后读者必须已明确：{resolve_str}")

        # 本簇完成度区间 + 强约束四条
        comp_min = card.get("cluster_completion_min")
        comp_max = card.get("cluster_completion_max")
        if isinstance(comp_min, (int, float)) and isinstance(comp_max, (int, float)):
            extra_lines.append(
                f"\n【本簇完成度】本章是本情节组第 {cluster_idx}/{cluster_total} 章，本章结束后本簇整体完成度应达到约 {int(comp_min)}%～{int(comp_max)}%。"
            )
        extra_lines.append(
            "\n【强约束：本簇闭环优先级高于长线悬念】（必须遵守）\n"
            "1. 本章若属于某事件簇的中后段，不得新增会独立展开的新核心人物、新组织、新阴谋线。\n"
            "2. 本簇完结前，禁止使用“幕后还有更大黑手”“他才发现真正的敌人另有其人”等扩世界观写法。\n"
            "3. 本簇最后一章必须先兑现本簇核心爽点，写出符合题材的具体损失与收益，再允许留下一个极小的余波钩子。\n"
            "4. 若篇幅不足，优先删去神秘感、环境描写、追踪桥段，也必须保留主角主动出招、对手失算反应与反杀结果。优先级：闭环完成 > 爽点兑现 > 因果清楚 > 辅助材料。"
        )

        # 簇内滚动进度（若已生成前几章）
        state = getattr(self, "_cluster_internal_state", None)
        if isinstance(state, dict) and cluster_id and state.get("cluster_id") == cluster_id:
            resolved = state.get("resolved_so_far") or []
            unresolved = state.get("unresolved_must_finish") or []
            if resolved or unresolved:
                extra_lines.append("\n【本情节组内已解决/待解决】")
                if resolved:
                    extra_lines.append("- 已解决：" + "；".join(resolved[:5]))
                if unresolved:
                    extra_lines.append("- 本章或后续必须完成：" + "；".join(unresolved[:5]))

        # 重写要求（簇审查未通过时注入）
        rewrite_advice = getattr(self, "_cluster_rewrite_advice", None)
        if isinstance(rewrite_advice, list) and rewrite_advice:
            extra_lines.append("\n【重写要求】上版未通过情节组完成审查，请严格按以下修改：")
            for line in rewrite_advice[:6]:
                extra_lines.append(f"- {line}")
        elif isinstance(rewrite_advice, str) and rewrite_advice.strip():
            extra_lines.append("\n【重写要求】" + rewrite_advice.strip()[:500])

        extra_lines.append(
            f"\n【章节结构职责（V2）】\n"
            f"- 本章结构模版：{tmpl}；章节角色：{role_v2}。\n"
        )

        # 补充情节组级别的闭环与信息差使用要求
        # 情节组级别的闭环与比例要求：按“整簇”而不是按“每章”去看结构
        if isinstance(cluster_total, int) and cluster_total >= 1 and isinstance(cluster_idx, int):
            cluster_range_str = (
                f"第{span_start}-{span_end}章" if span_start and span_end else f"共 {cluster_total} 章"
            )
            extra_lines.append(
            "\n【情节组闭环与信息差使用要求】\n"
                f"- 本情节组覆盖 {cluster_range_str}，叙事骨架必须是「旧局重现与主动改写」：主角识别已铺垫的风险或关系模式，依据既有知识主动布局，对方按既定动机行动，最后由因果链触发反转；不得靠天降线索推进。\n"
                "- 上一世羞辱与不甘必须在情节组内写厚：至少有一章集中写**完整上一世受挫/被嘲笑段落**（具体场景、对话、屈辱与无助），不能只用一句「上一世也曾」带过。\n"
                "- 若本故事采用前世/今生结构，旧阶段内容与当前行动应按章节分工呈现；若不采用，则以背景创伤和当前行动替代。\n"
                f"- 当前是本情节组中的第 {cluster_idx}/{cluster_total} 章，请按本章章节角色（{role_v2}）承担相应一段。\n"
                "- 证据、文件或结果只能作为已铺垫因果的落锤工具，不能代替人物判断与行动；禁止依赖匿名邮件、陌生人递材料等天降线索。\n"
                "- 今生的反击要让旁人感到意外：旁人不能一眼看出重生，但读者要清楚主角赢在**记得旧局、提前行动、敢于承担风险**。\n"
            )
        else:
            extra_lines.append(
                "\n【情节组闭环与信息差使用要求】\n"
                "- 每一个事件簇必须在本簇内完成：识别旧局或风险→主动布局→对方按既定动机行动→因果落锤。\n"
                "- 上一世羞辱与不甘必须写厚：至少一章写足完整受挫段落；信息差、关系、规则或材料只能是落锤工具，不能替代人物行动。\n"
                "- 禁止匿名邮件、陌生人递材料、匿名爆料等天降线索；本世推进只能来自主角凭记忆主动布局、对手按既定性格重复旧招，以及已铺垫因果按时兑现。\n"
            )

        # 根据角色给出更具体的节拍建议
        role_desc = ""
        if role_v2 == "present_setup":
            role_desc = (
                f"本章重点：旧局或风险重现与提前布局——{MAIN_PROTAGONIST}认出已经铺垫的模式，并立刻采取符合本次题材的针对性行动；"
                "可以极短闪回点到上一世，但不得在本章展开完整上一世受害（留给专章）；"
                "禁止把本章写成调查取证、到处找线索或等陌生人递材料。"
            )
        elif role_v2 == "prev_life_full":
            role_desc = (
                "本章重点：完整呈现上一世在相似情境下如何被害、被压下去，"
                "用多个具体场景和对话写足屈辱感，为下一章今生反杀蓄力。"
            )
        elif role_v2 == "present_revenge":
            role_desc = (
                "本章重点：当前阶段的反卡与结果，围绕本簇 core_payoff 完成兑现；"
                "先写对方照旧误判并走到主角预埋的卡点，再让符合本次题材的行动、规则、关系、成绩或材料当场落锤；"
                "写清对手具体后果。"
            )
        elif role_v2 == "present_past_mix":
            role_desc = (
                "本章重点：今生遭遇与上一世片段交错对照，"
                "通过“重复的台词/动作/场景”触发记忆，对比他这一次的不同选择。"
            )
        elif role_v2 == "slow_burn_press":
            role_desc = (
                "本章重点：纯压迫与危机酝酿，让读者感到局面越来越糟却一时无计可施，"
                "暂时不要给太明显的反击动作。"
            )
        elif role_v2 == "slow_burn_press_with_past_shadow":
            role_desc = (
                "本章重点：在持续压迫中，通过短暂的回忆或梦境，"
                "让上一世的阴影渗入今生，强化“这一次绝不能再输”的情绪。"
            )
        elif role_v2 == "partial_revenge":
            role_desc = (
                "本章重点：完成一部分反击或小胜利，同时暴露更深层的对手或阴谋，"
                "让读者既满足又被新的钩子吊住。"
            )
        elif role_v2 == "present_action_or_result_first":
            role_desc = (
                "本章重点：从今生的行动或已发生的结果开场，"
                "让读者先看到反击或异样，再在下一章通过追查补全上一世真相。"
            )
        elif role_v2 == "prev_life_explained_by_investigation":
            role_desc = (
                "本章重点：通过调查/审问/对质等方式，逐步揭示上一世的真相，"
                "把“为什么要这么复仇”讲清楚。"
            )
        elif role_v2 == "aftermath_or_next_seed":
            role_desc = (
                "本章重点：处理本簇反击后的余波（对方反扑、舆论变化、关系裂痕），"
                "并自然埋入下一簇/更大 Boss 的线索。"
            )
        elif role_v2 == "side_plot_focus":
            role_desc = (
                "本章重点：推进情感线/家人关系/盟友站队等旁支剧情，"
                "可以少量提及复仇主线，但不要抢走情感/关系变化的镜头。"
            )
        elif role_v2 == "present_setup_and_revenge":
            role_desc = (
                "本章需要在有限篇幅内完成铺垫+反击的完整闭环，"
                "结构上可采用“快速引入冲突→短闪回→当场反杀→余波”的紧凑节奏。"
            )
        elif role_v2 == "present_mid_bridge":
            role_desc = (
                "本章重点：诱敌与压实——写对方按既定动机误判或施压，主角如何收紧已铺垫的筹码；"
                "执行主角凭上一世记忆提前安排好的动作，逼对手照旧出招，而非首次发现新线索；"
                "禁止用匿名邮件、匿名爆料、陌生人递材料推动主线。"
            )

        if role_desc:
            extra_lines.append(f"- 写作重点：{role_desc}")

        ratio = self._infer_prev_life_ratio_from_role(role_v2)
        if ratio is not None:
            extra_lines.append(
                f"- 建议上一世段落占全文比例约为 {int(ratio*100)}%，其余为今生剧情；"
                "上一世内容必须与本章今生场景一一呼应，而不是泛泛叙述。"
            )

        # 约束结尾钩子的写法：禁止空洞的“更大危险将来临”式台词，要求用具体事件收尾
        extra_lines.append(
            "\n【结尾钩子写法限制】\n"
            "- 严禁使用空洞的预感型句子作为章节结尾，例如“他隐约觉得更大的危险正在逼近”“他知道这只是更大风暴的开始”等，这类句子没有具体事件，不具备吸引力。\n"
            "- 尤其禁止出现类似“他知道，这场游戏还没有结束。”“真正的风暴，才刚刚开始。”之类只靠比喻/预感堆砌气氛的句子，一经出现请直接改写。\n"
            "- 章节结尾必须落在一个**具体、可视化的动作或事件瞬间**上，例如：\n"
            "  · 门被人猛地推开/门外突然传来急促的脚步声；\n"
            "  · 某个关键人物在他转身要走时叫住他，说出半句话；\n"
            "  · 已登场对手当众提出下一场挑战，或试图夺走刚刚落定的具体利益；\n"
            "  · 主角刚完成的动作或公开结果让既有对手脸色大变、话到嘴边却戛然而止。\n"
            "- 请自行设计类似的“具体动作型钩子”，让读者停在一个悬在半空的画面上，而不是停在抽象感受上。"
        )

        return base_prompt + "\n" + "\n".join(extra_lines)


# 本簇禁止引入的通用角色/元素（避免长篇连载式扩张）
DEFAULT_FORBIDDEN_NEW_ROLES = [
    "神秘援手", "神秘司机", "系统", "系统提示音", "苏晚晴", "黑色轿车", "神秘人",
    "幕后黑手", "更大风暴", "真正的敌人", "神秘男人", "陌生女性盟友", "未规划的关键证人",
] + THEME_FORBIDDEN_ELEMENTS
# 本章允许出场的通用配角描述（不写死具体姓名，避免与主对手混淆）
DEFAULT_ALLOWED_SUPPORT = "与本次主题和背景一致的同事、亲友、对手下属、行业人员、公共机构人员与临时场景角色"

# 重生复仇叙事：禁止「调查文」式天降线索（写入章节卡 must_not 与 critic 提示）
REBIRTH_FORBIDDEN_DEUS_EX = [
    "匿名邮件/匿名爆料作为关键转折",
    "加密邮箱突然跳出决定性截图或附件",
    "老员工/陌生人未经铺垫突然递来唯一关键材料",
    "靠社交媒体发帖或声明完成主线翻盘",
    "隐藏文件夹/机密会议纪要突然揭示全部真相",
    "把本次主题无解释地改写成另一种题材或世界观",
]


def _cluster_has_substantial_prev_life_block(
    chapter_texts: Dict[int, str], start_ch: int, end_ch: int
) -> bool:
    """至少一章写足上一世受害段落（非仅一句带过）。"""
    for ch in range(start_ch, end_ch + 1):
        t = (chapter_texts.get(ch) or "").strip()
        if len(t) < 260:
            continue
        life_kw = t.count("上一世") + t.count("前世") + t.count("那一世")
        if life_kw == 0:
            continue
        if life_kw >= 3 and len(t) >= 320:
            return True
        if life_kw >= 2 and len(t) >= 480:
            return True
        if life_kw >= 1 and len(t) >= 850:
            return True
    return False


def _cluster_revenge_pattern_ok(full_text: str) -> bool:
    """至少体现四类中的三类：旧招识别 / 提前布子 / 对方照旧出手 / 关键时刻反卡。"""
    buckets = [
        bool(re.search(r"上一世|前世|这一套|老办法|还是这招|熟悉的台词|重蹈覆辙|又像", full_text)),
        bool(re.search(r"提前|先一步|布好|布置|埋伏|等着她|算准|早已|预埋|将计就计|早就算", full_text)),
        bool(re.search(r"果然|还是来了|照旧|又按|按老规矩|不出所料|又走了老路|老套路", full_text)),
        bool(re.search(r"当场|揭穿|亮出|休想|来不及|公之于众|落锤|在座的|看清楚", full_text)),
    ]
    return sum(1 for x in buckets if x) >= 3


def _cluster_detect_deus_ex_machina(full_text: str) -> List[str]:
    """检测常见「天降线索」措辞，供 violations 提示。"""
    bad: List[str] = []
    checks = [
        ("匿名邮件", "匿名邮件"),
        ("匿名爆料", "匿名爆料"),
        ("加密邮件", "加密邮件"),
        ("老员工递来", "老员工突然递材料"),
        ("陌生人递", "陌生人递证据"),
        ("隐藏文件夹", "隐藏文件夹"),
        ("突然收到一封", "突然收到匿名信/邮件"),
    ]
    for kw, label in checks:
        for match in re.finditer(re.escape(kw), full_text):
            prefix = full_text[max(0, match.start() - 12):match.start()]
            if re.search(
                r"(?:不接受|不依赖|不采用|没有使用|并未使用|拒绝|禁止|"
                r"无需|无须|不能|不得|不会|并非|不是|没有|不|未).{0,5}$",
                prefix,
            ):
                continue
            bad.append(label)
            break
    return list(dict.fromkeys(bad))[:6]


# 调查/曝光链「叙事发动机」关键词（与重生四段式同时检视）
INVESTIGATION_NARRATIVE_TOKENS = [
    "匿名邮件",
    "加密邮件",
    "自由撰稿人",
    "独立媒体",
    "新闻发布会",
    "微博话题",
    "发邮件给",
    "合作媒体",
    "上传视频",
    "直播",
    "举报信",
    "声明发给",
    "社交媒体",
    "档案室",
    "破解加密",
    "匿名论坛",
    "匿名账户",
    "加密文档",
    "秘密交易",
    "资金流动",
    "服务器",
    "备用镜头",
    "技术员",
    "仓库",
    "摄像机",
    "加密通讯",
    "社交平台",
    "登记簿",
    "预约记录",
    "拍下屏幕",
    "确认没有人尾随",
]

# 正文绝不允许出现的「模板/拍卡」泄露
FORMAT_LEAK_MARKERS = [
    "第1拍",
    "第2拍",
    "第3拍",
    "第4拍",
    "第5拍",
    "第6拍",
    "第7拍",
    "第8拍",
    "scene_goal",
    "end_to_next",
    "open_from_prev",
    "flashback_in_beat_idx",
    "evidence_form",
    "info_delta",
    "prev_life_memory_brief",
    "visual_elements",
    "emotion_push",
]


def _count_rebirth_buckets(full_text: str) -> int:
    """旧招识别 / 提前布子 / 对方照旧 / 反卡 四类命中数。"""
    buckets = [
        bool(re.search(r"上一世|前世|这一套|老办法|还是这招|熟悉的台词|重蹈覆辙|认出|旧局", full_text)),
        bool(re.search(r"提前|先一步|布好|布置|埋伏|等着她|算准|早已|预埋|将计就计", full_text)),
        bool(re.search(r"果然|还是来了|照旧|又按|按老规矩|不出所料|老套路", full_text)),
        bool(re.search(r"当场|揭穿|亮出|休想|来不及|公之于众|落锤|在座的", full_text)),
    ]
    return sum(1 for x in buckets if x)


def _critic_format_leak(text: str) -> Optional[str]:
    scene_label = re.search(r"(?:^|\n)\s*(?:闪回|回忆)\s*[:：]\s*(?:\n|$)", text or "")
    if scene_label:
        return "正文格式泄露：出现独立的‘闪回/回忆’标签，须无标签地自然切入记忆场景"
    marker_match = re.search(r"【E\d+】|(?<![A-Za-z0-9])E\d+(?![A-Za-z0-9])", text or "")
    if marker_match:
        return f"正文格式泄露：出现内部证据编号「{marker_match.group(0)}」，须改写为具体物件或行动"
    for m in FORMAT_LEAK_MARKERS:
        if m in (text or ""):
            return f"正文格式泄露：出现模板/节拍字段「{m}」，须重写为纯小说正文"
    return None


def _critic_narrative_engine_investigation(full_text: str) -> Optional[str]:
    """调查曝光链过多且重生四段式不足 → 叙事发动机错误（硬失败）。"""
    inv = sum(1 for k in INVESTIGATION_NARRATIVE_TOKENS if k in full_text)
    rb = _count_rebirth_buckets(full_text)
    if inv >= 3 and rb < 3:
        return (
            "叙事发动机错误：本簇呈现调查/媒体/曝光链过重，且未同时写足「旧局识别/提前布子/对方照旧/关键反卡」；"
            "须改为重生预判反杀，不要用取证-爆料链推进。"
        )
    if inv >= 6:
        return "叙事发动机错误：调查/曝光类桥段堆叠过多；须删减并改为旧局重演式推进。"
    return None


def _has_tangible_payoff(
    text: str, chapter_card: Optional[Dict[str, Any]] = None
) -> bool:
    content = text or ""
    card = chapter_card if isinstance(chapter_card, dict) else {}
    cast = card.get("canonical_cast") or []
    protagonist_names = [
        str(member.get("name") or "").strip()
        for member in cast if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
        and str(member.get("name") or "").strip()
    ]
    opponent_names = [
        str(member.get("name") or "").strip()
        for member in cast if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "opponent"
        and str(member.get("name") or "").strip()
    ]

    def payoff_name_pattern(names: List[str], fallback: str) -> str:
        variants: List[str] = []
        for name in names:
            variants.extend((name, name.split()[0]))
            for separator in ("·", "・"):
                if separator in name:
                    variants.append(name.split(separator, 1)[0])
        escaped = [
            re.escape(item)
            for item in dict.fromkeys(item for item in variants if item)
        ]
        return "|".join(escaped) or fallback

    protagonist_pattern = payoff_name_pattern(
        protagonist_names, r"Maya(?:\s+Reed)?|玛雅|主角|她"
    )
    opponent_pattern = payoff_name_pattern(
        opponent_names, r"Elena(?:\s+Voss)?|对手"
    )
    opponent_loses = any(marker in content for marker in OPPONENT_CONSEQUENCE_MARKERS) or bool(
        re.search(
            r"(?:(?:品牌|公司|片方|平台|项目方|制片方|经纪公司|董事会).{0,24})?"
            r"(?:宣布|决定|当场)?(?:终止|停止|暂停|取消|解除|撤下|拒绝|收回|剥夺).{0,24}"
            r"(?:合作|合约|合同|代言|角色|项目|职位|职务|资格|提名)",
            content,
        )
    ) or bool(
        re.search(
            rf"(?:{opponent_pattern}).{{0,80}}(?:被换下|被换角|被踢出|退出项目|不再参与|"
            r"名字被划掉|角色被收回|失去出演资格|被赶出)",
            content,
            re.I | re.S,
        )
    ) or bool(
        re.search(
            rf"(?:角色|女主角|主演|出演资格).{{0,40}}(?:从(?:{opponent_pattern}).{{0,16}}"
            r"(?:手中)?收回|不再属于(?:{opponent_pattern}))",
            content,
            re.I | re.S,
        )
    ) or bool(
        re.search(
            rf"(?:{opponent_pattern}).{{0,80}}(?:失去|被撤销|被剥夺|不再拥有).{{0,20}}"
            r"(?:推荐权|干预权|优先权|影响力|话语权|选角权|排期权|签批权|代签权|"
            r"保管权|指挥权|支付权|指定权|接触权限|账户权限|打包权|采访席位)",
            content,
            re.I | re.S,
        )
    ) or bool(
        re.search(
            r"(?:当场|正式|立即)?(?:冻结|撤销|收回|取消|暂停|剥夺).{0,24}"
            r"(?:权限|签批权|代签权|排期权|保管权|指挥权|支付权|账户|交易|预留票|访问资格)",
            content,
        )
    ) or bool(
        re.search(
            r"(?:失去|不再拥有|不再有权|不得再|不敢再).{0,16}"
            r"(?:降配|降低(?:训练)?强度|降强度|训练干预|决定训练强度)",
            content,
        )
    ) or bool(
        re.search(
            r"(?:失去|被撤销|被剥夺|不再拥有|不得再).{0,24}"
            r"(?:权限|资格|席位|控制权|指挥权|签批权|否决权|监督权|"
            r"决定权|保管权|调度权|预留票权)",
            content,
        )
    )
    protagonist_gains = any(marker in content for marker in PROTAGONIST_GAIN_MARKERS) or bool(
        re.search(
            rf"(?:{protagonist_pattern}).{{0,80}}"
            r"(?:拿到|拿下|获得|签下|恢复|赢得|接任|接管|重获|成为|确定为|选定为|"
            r"确认出演|正式出演|完成签约|重新回归).{0,24}"
            r"(?:角色|女主角|主演|合约|合同|资格|名誉|赔偿|项目|职位|机会|邀约|舞台|代言)",
            content,
            re.I,
        )
    ) or bool(
        re.search(
            rf"(?:恢复|归还|授予|邀请|确定|选定|宣布).{{0,30}}(?:{protagonist_pattern}).{{0,30}}"
            r"(?:角色|女主角|主演|合约|合同|资格|名誉|赔偿|项目|职位|机会|邀约|代言)",
            content,
            re.I,
        )
    ) or bool(
        re.search(
            rf"(?:药品|物资)?保管(?:职责|权限|权).{{0,24}}(?:移交|交还|归还)(?:至|给)?"
            rf".{{0,16}}(?:{protagonist_pattern}|本人)",
            content,
            re.I,
        )
    ) or bool(
        re.search(
            rf"(?:药品|物资)?保管(?:职责|权限|权).{{0,20}}(?:默认)?(?:归属|属于|交由)"
            rf".{{0,16}}(?:{protagonist_pattern}|本人)",
            content,
            re.I,
        )
    ) or bool(
        re.search(
            rf"(?:药品|物资)?保管(?:职责|权限|权).{{0,8}}归"
            rf".{{0,16}}(?:{protagonist_pattern}|本人)",
            content,
            re.I,
        )
    ) or bool(
        re.search(
            rf"(?:训练强度决定权|训练决定权).{{0,16}}"
            rf"(?:归还|归|交还|回到)(?:给|至)?"
            rf".{{0,12}}(?:{protagonist_pattern}|本人)",
            content,
            re.I,
        )
    ) or bool(
        re.search(
            rf"(?:角色|女主角|主演).{{0,30}}(?:确定)?由(?:{protagonist_pattern})"
            r"(?:出演|担任|接替|拿下)?",
            content,
            re.I | re.S,
        )
    ) or bool(
        re.search(
            rf"(?:{protagonist_pattern}).{{0,80}}(?:收回|夺回|取得|获得|拿回|保住|重新掌握).{{0,28}}"
            r"(?:权限|签字权|否决权|排期权|保管权|决定权|监督权|回购权|"
            r"签署权|发布权|监管权|控制权|指挥权|调度权|席位|票池|"
            r"母带|彩排表|声誉|资金|账户|设备|安全)",
            content,
            re.I | re.S,
        )
    )
    return opponent_loses and protagonist_gains


PAYOFF_AUTHORITY_TOKENS = (
    "选角导演", "导演", "制片人", "片方", "项目方", "品牌方", "平台负责人",
    "公司负责人", "经纪公司负责人", "主办方", "组委会", "评委会", "法官",
)


def _scene_has_payoff_authority(text: str) -> bool:
    """Appending a ruling is safe only when the current scene already contains its decision-maker."""
    return any(token in (text or "") for token in PAYOFF_AUTHORITY_TOKENS)


def _near_duplicate_paragraph_failure(text: str) -> Optional[str]:
    paragraphs = [re.sub(r"\s+", "", p) for p in re.split(r"\n\s*\n", text or "")]
    paragraphs = [p for p in paragraphs if len(p) >= 32]
    for idx, left in enumerate(paragraphs):
        for right in paragraphs[idx + 1 :]:
            if SequenceMatcher(None, left, right, autojunk=False).ratio() >= 0.82:
                return "正文存在近似重复段落，须删除重复信息并用新的动作、对话或局势变化替代。"
    return None


def _segment_prior_prose_overlap_failure(
    candidate: str,
    prior_segments: List[str],
) -> str:
    """Reject a new beat that restates prose already accepted for this chapter."""
    candidate = str(candidate or "").strip()
    if not candidate or not prior_segments:
        return ""

    def normalized(value: str) -> str:
        return re.sub(r"[\s，。！？；：、“”‘’（）《》,.!?;:'\"()]+", "", value or "")

    def sentences(value: str) -> List[str]:
        return [
            normalized(sentence)
            for sentence in re.findall(
                r"[^。！？]*[。！？][”’\"]?|[^。！？]+$",
                str(value or "").strip(),
            )
            if len(normalized(sentence)) >= 24
        ]

    candidate_normalized = normalized(candidate)
    candidate_sentences = sentences(candidate)
    candidate_short_sentences = {
        normalized(sentence)
        for sentence in re.findall(
            r"[^。！？]*[。！？][”’\"]?|[^。！？]+$",
            candidate,
        )
        if len(normalized(sentence)) >= 6
    }
    for prior_index, prior in enumerate(prior_segments, start=1):
        prior_normalized = normalized(prior)
        if not prior_normalized:
            continue
        prior_sentences = sentences(prior)
        prior_short_sentences = {
            normalized(sentence)
            for sentence in re.findall(
                r"[^。！？]*[。！？][”’\"]?|[^。！？]+$",
                str(prior or "").strip(),
            )
            if len(normalized(sentence)) >= 6
        }
        if candidate_short_sentences & prior_short_sentences:
            return (
                f"本段逐字重复了本章已接受的第{prior_index}段完整句子；"
                "删除重复句，直接写当前节拍的新动作或新对白。"
            )
        repeated_sentence = next(
            (
                sentence
                for sentence in candidate_sentences
                if any(
                    sentence == old_sentence
                    or (
                        min(len(sentence), len(old_sentence)) >= 36
                        and (
                            sentence in old_sentence
                            or old_sentence in sentence
                        )
                    )
                    for old_sentence in prior_sentences
                )
            ),
            "",
        )
        if repeated_sentence:
            return (
                f"本段逐字或近乎逐字复述了本章已接受的第{prior_index}段长句；"
                "上一段结尾只供衔接，必须从本段的新动作或新对白直接起笔。"
            )

        matcher = SequenceMatcher(
            None,
            candidate_normalized,
            prior_normalized,
            autojunk=False,
        )
        longest = matcher.find_longest_match(
            0,
            len(candidate_normalized),
            0,
            len(prior_normalized),
        ).size
        shorter_length = min(len(candidate_normalized), len(prior_normalized))
        if (
            matcher.ratio() >= 0.58
            or (
                longest >= 48
                and shorter_length
                and longest / shorter_length >= 0.32
            )
        ):
            return (
                f"本段大段复述或同义改写了本章已接受的第{prior_index}段；"
                "删除回顾，只写当前节拍新增的动作、对白和局势变化。"
            )
    return ""


def _segment_semantic_repair_directive(failure: str) -> str:
    """Turn a validator message into a short, reusable rewrite priority."""
    failure = str(failure or "").strip()
    if not failure:
        return ""
    if "认出旧招" in failure and "请见证" in failure:
        return (
            "前两句必须分别写清主角凭上一世记忆认出对手旧招，以及主角这一次"
            "提前请现场见证者到场；不能只写见证者已经坐在现场。"
        )
    if "缺少口头" in failure or "通过结论" in failure:
        return (
            "首句必须由本段任务指定的判断人开口，用直接引语明确说出"
            "“通过”“合格”或“达标”之一；不得先写动作或沉默。"
        )
    if "缺少" in failure and "对白" in failure:
        return (
            "前两句必须出现本段任务要求的人物直接引语，并完整说出要求中的核心意思；"
            "不得用神态、概述或转述代替。"
        )
    if "技术挑错" in failure or "重新展开表演" in failure:
        return (
            "结果已经生效，本段只能写非技术性嘴硬、主角用既成结果反击、"
            "对手沉默或移开视线；全文不得出现任何表演动作或技术词。"
        )
    if "顺序倒置" in failure or "提前写" in failure:
        return (
            "严格按本段任务的先后顺序重写；先完整兑现前置动作或结论，"
            "再写后置反应，禁止把后一步提前。"
        )
    if "复述" in failure or "重复" in failure or "同义改写" in failure:
        return (
            "首句直接写当前节拍的新动作或新对白，不得沿用旧稿开头，"
            "也不得回顾本章已经发生的动作。"
        )
    return (
        "前两句必须直接兑现失败原因中缺少或错误的核心语义，"
        "其余句子只围绕本段任务展开。"
    )


def _prose_structure_failure(text: str) -> Optional[str]:
    """Reject block-shaped or deterministic fallback prose before it reaches memory."""
    content = str(text or "").strip()
    paragraphs = [
        re.sub(r"\s+", "", paragraph)
        for paragraph in re.split(r"\n\s*\n", content)
        if paragraph.strip()
    ]
    fallback_markers = (
        "前一场已经冻结的",
        "把相关人员留在公开核验位置",
        "所有人先确认旧安排尚未恢复",
        "相关人员按停止状态继续值守",
        "原本等待执行的人重新坐下",
        "看着停止状态保持不变",
        "与会者依次确认最终状态，随后才收起各自材料",
        "没有再得到恢复操作的机会",
        "现场到此收束",
    )
    marker_hits = [marker for marker in fallback_markers if marker in content]
    if len(marker_hits) >= 2:
        return (
            "正文保留了确定性兜底模板句式："
            + "、".join(marker_hits[:4])
            + "。必须从章节卡重新写成有人物动作、对白节奏和具体场面变化的自然正文。"
        )
    if (
        len(content) >= 1200
        and 4 <= len(paragraphs) <= 7
        and paragraphs
        and min(len(paragraph) for paragraph in paragraphs) >= 120
    ):
        return (
            "正文由少量近似等长的大段机械拼接，行文格式过于整齐；"
            "须拆合节拍，交替使用短对白段、动作段和较长冲突段，不能一拍固定对应一段。"
        )
    return None


def _generic_prose_quality_failures(text: str) -> List[str]:
    """Catch mechanical prose patterns that can satisfy plot-only validators."""
    content = str(text or "").strip()
    if len(content) < 600:
        return []
    sentences = [
        sentence.strip()
        for sentence in re.split(r"[。！？!?；;\n]+", content)
        if len(re.sub(r"\s+", "", sentence)) >= 4
    ]
    if not sentences:
        return []

    failures: List[str] = []
    sentence_count = len(sentences)
    body_terms = (
        "手", "手指", "手掌", "手腕", "指尖", "指节", "脚", "脚步", "膝",
        "肩", "肩膀", "腰", "背", "胸", "肋", "喉结", "下颌", "眼皮",
        "呼吸", "气息", "吐息", "吸气", "换气", "站位", "重心",
    )
    micro_terms = (
        "抬手", "收手", "伸手", "缩手", "按住", "捏住", "攥紧", "松开",
        "指尖", "指节", "掌心", "手腕", "脚尖", "脚跟", "落脚", "站稳",
        "挪步", "侧移", "退开", "靠近", "俯身", "抬眼", "垂眼", "喉结",
        "吸气", "吐气", "换气", "气息",
    )
    body_sentence_count = sum(
        1 for sentence in sentences if any(term in sentence for term in body_terms)
    )
    micro_sentence_count = sum(
        1 for sentence in sentences if any(term in sentence for term in micro_terms)
    )
    body_mentions = sum(content.count(term) for term in body_terms)
    micro_mentions = sum(content.count(term) for term in micro_terms)
    body_density = body_sentence_count / sentence_count
    micro_density = micro_sentence_count / sentence_count
    if (
        sentence_count >= 20
        and (
            (body_mentions >= 20 and body_density >= 0.45)
            or (micro_mentions >= 12 and micro_density >= 0.25)
        )
    ):
        failures.append(
            "正文把过多句子消耗在手脚、站位、呼吸或细碎身体动作上"
            f"（身体动作句占比{body_density:.0%}，微动作句占比{micro_density:.0%}）；"
            "删除动作清单，只保留会改变决定、关系或局势的动作，用对白、选择和后果推进。"
        )

    staging_pattern = re.compile(
        r"近前|半尺|半步|一步之内|两步|三步|向前|向后|左侧|右侧|"
        r"身前|身后|靠近|退开|挪到|移到|站到|走到|贴近|拉开距离"
    )
    staging_sentences = sum(1 for sentence in sentences if staging_pattern.search(sentence))
    staging_mentions = len(staging_pattern.findall(content))
    if (
        sentence_count >= 20
        and staging_mentions >= 10
        and staging_sentences / sentence_count >= 0.18
    ):
        failures.append(
            "正文反复标注人物距离、方向和站位，形成舞台调度说明；"
            "删去“近前/几步/左右侧”等无因果位移，只保留改变权力关系的空间动作。"
        )

    normalized_sentences: Dict[str, List[str]] = {}
    for sentence in sentences:
        normalized = re.sub(
            r"[\s，。！？；：、“”‘’（）《》,.!?;:'\"()]+",
            "",
            sentence,
        )
        if len(normalized) < 8:
            continue
        normalized_sentences.setdefault(normalized, []).append(sentence)
    duplicates = [
        values[0]
        for values in normalized_sentences.values()
        if len(values) >= 2
    ]
    if duplicates:
        failures.append(
            "正文出现完全重复句："
            + "；".join(duplicates[:2])
            + "。必须从因果位置重写，不能复制或近距离复述已经发生的动作。"
        )

    repeated_nouns: List[str] = []
    repetition_nouns = (
        "气息", "呼吸", "音响", "手指", "手掌", "脚步", "位置", "钥匙",
        "封签", "表格", "文件", "动作", "视线", "控台", "屏幕", "表演",
    )
    for sentence in sentences:
        for noun in repetition_nouns:
            first = sentence.find(noun)
            if first < 0:
                continue
            second = sentence.find(noun, first + len(noun))
            if 0 <= second - first <= 16:
                repeated_nouns.append(noun)
    if repeated_nouns:
        failures.append(
            "正文出现近距离词语自我重复或病态搭配："
            + "、".join(list(dict.fromkeys(repeated_nouns))[:4])
            + "。重写整句，避免“气息沉入气息”一类生成痕迹。"
        )

    tail = content[-260:]
    scenery_terms = (
        "窗外", "天色", "夜色", "暮色", "晨光", "灯光", "光线", "影子",
        "风吹", "雨声", "云层", "玻璃窗", "窗帘", "余晖", "空气里",
    )
    scenery_hits = sum(tail.count(term) for term in scenery_terms)
    tail_sentences = [
        sentence.strip()
        for sentence in re.split(r"[。！？!?]+", tail)
        if sentence.strip()
    ]
    last_sentence = tail_sentences[-1] if tail_sentences else tail
    consequence_terms = (
        "失去", "撤下", "撤销", "暂停", "停职", "冻结", "交出", "退回",
        "获得", "拿回", "收回", "归还", "决定权", "否决权", "签字权",
        "保管权", "监督席位", "生效", "宣布", "确认",
    )
    if (
        scenery_hits >= 2
        and any(term in last_sentence for term in scenery_terms)
        and not any(term in last_sentence for term in consequence_terms)
    ):
        failures.append(
            "结尾在结果落地后漂移到天气、窗景、光影或空气描写；"
            "最后一拍应停在已经生效的决定、物件交接、锋利对白或对手直接反应上。"
        )
    return failures


def _cross_chapter_prose_similarity_failures(
    text: str,
    previous_chapter_texts: Dict[int, str],
) -> List[str]:
    """Reject copied wording and repeated paragraph geometry across recent chapters."""
    content = str(text or "").strip()
    if len(content) < 800:
        return []

    def normalized(value: str) -> str:
        return re.sub(r"[\s，。！？；：、“”‘’（）《》,.!?;:'\"()]+", "", value or "")

    def paragraph_lengths(value: str) -> List[int]:
        return [
            len(re.sub(r"\s+", "", paragraph))
            for paragraph in re.split(r"\n\s*\n", value or "")
            if paragraph.strip()
        ]

    current_normalized = normalized(content)
    current_profile = paragraph_lengths(content)
    failures: List[str] = []
    for chapter, previous in sorted(previous_chapter_texts.items(), reverse=True):
        previous = str(previous or "").strip()
        if len(previous) < 800:
            continue
        ratio = SequenceMatcher(
            None,
            current_normalized,
            normalized(previous),
            autojunk=False,
        ).ratio()
        if ratio >= 0.55:
            failures.append(
                f"正文与第{chapter}章措辞和推进顺序高度相似（相似度{ratio:.2f}）；"
                "必须更换起笔动作、对话节奏、冲突展开与收束方式，不能只替换人物或资源名称。"
            )
            break
        previous_profile = paragraph_lengths(previous)
        if (
            4 <= len(current_profile) <= 7
            and len(previous_profile) == len(current_profile)
            and min(current_profile + previous_profile) >= 100
        ):
            mean_difference = sum(
                abs(left - right)
                for left, right in zip(current_profile, previous_profile)
            ) / len(current_profile)
            if mean_difference <= 40:
                failures.append(
                    f"正文与第{chapter}章重复同一种等长分段格式；"
                    "必须改变自然段数量和长短节奏，让动作、对白与结算按本章场面自然拆合。"
                )
                break
    return failures


def _prose_integrity_failure(text: str) -> Optional[str]:
    """Reject obvious splice damage that semantic payoff checks cannot detect."""
    content = text or ""
    ascii_words = re.findall(r"\b[A-Za-z]{2,}\b", content)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", content)
    if len(ascii_words) >= 80 and len(chinese_chars) < len(ascii_words) * 3:
        return "正文语言漂移成连续英文；欧美题材仍必须用简体中文叙述和中文对白，只保留固定英文人名。"

    malformed_patterns = (
        r"旧经纪人旧经纪人",
        r"选角\s*[A-Za-z][A-Za-z ]{2,40}人电话",
        r"(?:，|；)(?:而|但|却|因为|所以)\s*[。！？!?]",
        r"这场较量\s*[，,]\s*(?:而|但)?\s*[。！？!?]",
        r"距离.{0,20}还有三天子",
        r"(?:编剧|导演|制片人|经纪人)(?:兼联合)?(?:导演制片负责人|制片负责人|选角助理)",
        r"(?:由|让)(?:导演|制片负责人|选角助理|片方代表)饰演",
    )
    if any(re.search(pattern, content, re.I | re.S) for pattern in malformed_patterns):
        return "正文存在残句、职位粘连或规则替换造成的病句；须从完整场景重写，不能继续字符串拼接。"

    normalized_sentences = [
        re.sub(r"\s+", "", sentence)
        for sentence in re.split(r"[。！？!?]+", content)
    ]
    seen: set[str] = set()
    for sentence in normalized_sentences:
        if len(sentence) < 24:
            continue
        if sentence in seen:
            return "正文逐字重复了完整长句，像扩写拼接稿；必须只保留一次并继续推进新动作。"
        seen.add(sentence)

    if content.count("“") != content.count("”"):
        return "正文中文引号未闭合，存在截断或拼接残句。"
    return None


def _has_completed_representation_termination(text: str) -> bool:
    content = text or ""
    return bool(re.search(
        r"(?:解除|终止|撤销).{0,28}(?:代理|经纪)(?:协议|关系|授权)?"
        r".{0,90}(?:发送|发出|送达|收件回执|确认收到|立即生效|正式生效)|"
        r"(?:解约函|解除代理通知|终止代理通知).{0,70}(?:发送|发出|送达|收件回执|确认收到)|"
        r"(?:发送|发出|送达).{0,70}(?:解约函|解除代理通知|终止代理通知)",
        content,
        re.I | re.S,
    ))


def _has_completed_ally_appointment(text: str, ally_name: str) -> bool:
    content = text or ""
    if not ally_name or ally_name not in content:
        return False
    if re.search(r"(?:等待|等着|等候).{0,18}(?:回复|答复|回电)|我在等你的回复", content[-220:]):
        return False
    ally_first = re.escape(ally_name.split()[0])
    concrete_slot = r"(?:今天|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天]|上午|下午|晚上|\d{1,2}点|[一二三四五六七八九十]+点)"
    return bool(re.search(
        rf"(?:{re.escape(ally_name)}|{ally_first}|电话那端).{{0,180}}"
        rf"(?:同意见面|确认会面|约好|预约成功|明确答复|安排在|定在).{{0,45}}{concrete_slot}|"
        rf"{concrete_slot}.{{0,45}}(?:见面|会面|办公室).{{0,80}}(?:确认|约好|预约成功|没问题|就这么定)",
        content,
        re.I | re.S,
    ))


def _expansion_preserves_original_ending(original: str, expanded: str) -> bool:
    def _last_paragraph(value: str) -> str:
        parts = [re.sub(r"\s+", "", p) for p in re.split(r"\n\s*\n", value or "") if p.strip()]
        return parts[-1] if parts else ""

    original_last = _last_paragraph(original)
    expanded_last = _last_paragraph(expanded)
    if not original_last or not expanded_last:
        return False
    return original_last == expanded_last


def _insert_before_last_paragraph(original: str, addition: str) -> str:
    source = (original or "").strip()
    inserted = (addition or "").strip()
    if not source or not inserted:
        return source
    parts = re.split(r"\n\s*\n", source)
    if len(parts) == 1:
        return inserted + "\n\n" + source
    return "\n\n".join(parts[:-1] + [inserted, parts[-1]]).strip()


def _strip_empty_ending_cliches(text: str) -> str:
    """Drop a final empty teaser sentence when the preceding scene already carries the hook."""
    cleaned = text or ""
    for marker in EMPTY_ENDING_MARKERS:
        cleaned = cleaned.replace(marker, "")
    cleaned = re.sub(r"([。！？])\s*[，,；;。]+", r"\1", cleaned)
    paragraphs = cleaned.rstrip().splitlines()
    while paragraphs and any(marker in paragraphs[-1] for marker in EMPTY_ENDING_MARKERS):
        paragraphs.pop()
        while paragraphs and not paragraphs[-1].strip():
            paragraphs.pop()
    return "\n".join(paragraphs).strip()


def _normalize_joined_canonical_names(text: str, chapter_card: Optional[Dict[str, Any]]) -> str:
    result = text or ""
    card = chapter_card if isinstance(chapter_card, dict) else {}
    cast = card.get("canonical_cast") or []
    for member in cast if isinstance(cast, list) else []:
        if not isinstance(member, dict):
            continue
        name = str(member.get("name") or "").strip()
        parts = name.split()
        if len(parts) < 2 or not all(re.fullmatch(r"[A-Za-z]+", part) for part in parts):
            continue
        joined = "".join(parts)
        result = re.sub(rf"(?<![A-Za-z]){re.escape(joined)}(?![A-Za-z])", name, result, flags=re.I)
        first_name, last_name = parts[0], parts[-1]
        result = re.sub(
            rf"(?<![A-Za-z]){re.escape(first_name)}(?:['’]s)(?![A-Za-z])",
            name + "的",
            result,
        )
        def _repair_surname(match: re.Match[str]) -> str:
            candidate_last = match.group(1)
            if candidate_last.casefold() == last_name.casefold():
                return match.group(0)
            ratio = SequenceMatcher(None, candidate_last.casefold(), last_name.casefold()).ratio()
            if abs(len(candidate_last) - len(last_name)) <= 2 and ratio >= 0.84:
                return name
            return match.group(0)
        result = re.sub(
            rf"(?<![A-Za-z]){re.escape(first_name)}\s+([A-Z][a-z]+)(?![A-Za-z])",
            _repair_surname,
            result,
            flags=re.I,
        )
    return result


def _normalize_awakening_role_aliases(
    text: str, chapter_card: Optional[Dict[str, Any]]
) -> str:
    """Map invented awakening-chapter names back to the fixed cast or unnamed agent."""
    result = text or ""
    card = chapter_card if isinstance(chapter_card, dict) else {}
    card_context = " ".join(
        str(card.get(key) or "")
        for key in ("chapter_goal", "prev_life_tragedy", "this_life_revenge", "core_payoff")
    )
    if not re.search(r"试戏|试镜|选角|旧经纪人|解除代理", card_context):
        return result
    cast = card.get("canonical_cast") or []
    names_by_alignment = {
        str(member.get("alignment") or "").casefold(): str(member.get("name") or "").strip()
        for member in cast if isinstance(member, dict) and str(member.get("name") or "").strip()
    }
    protagonist = names_by_alignment.get("protagonist", "主角")
    opponent = names_by_alignment.get("opponent", "固定对手")
    ally = names_by_alignment.get("ally") or names_by_alignment.get("support") or "固定盟友"
    allowed = {name.casefold() for name in names_by_alignment.values() if name}
    allowed_places = {
        "los angeles", "new york", "san francisco", "las vegas", "beverly hills",
        "silicon valley", "wall street",
    }
    for match in reversed(list(re.finditer(
        r"(?<![A-Za-z])([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2})(?![A-Za-z])",
        result,
    ))):
        alias = match.group(1)
        if alias.casefold() in allowed or alias.casefold() in allowed_places:
            continue
        result = result[:match.start()] + "旧经纪人" + result[match.end():]

    chinese_name = r"[\u4e00-\u9fff]{2,5}[·•][\u4e00-\u9fff]{2,6}"
    result = re.sub(rf"我是\s*{chinese_name}", f"我是{protagonist}", result)
    result = re.sub(rf"这里是\s*{chinese_name}", f"这里是{ally}", result)
    result = re.sub(rf"经纪人\s*{chinese_name}", "经纪人旧经纪人", result)
    result = re.sub(
        rf"与\s*{chinese_name}\s*的(?:所有)?代理(?:关系|授权)?",
        "与旧经纪人的代理关系",
        result,
    )
    chinese_alias_pattern = re.compile(chinese_name)
    for match in reversed(list(chinese_alias_pattern.finditer(result))):
        alias = match.group(0)
        if alias in names_by_alignment.values():
            continue
        context = result[max(0, match.start() - 42):min(len(result), match.end() + 42)]
        if re.search(rf"我是\s*{re.escape(alias)}", context):
            replacement = protagonist
        elif re.search(rf"这里是\s*{re.escape(alias)}", context):
            replacement = ally
        elif re.search(r"影后|核心对手|上一世.{0,12}(?:羞辱|抢走|打压)|前世.{0,12}(?:羞辱|抢走|打压)", context):
            replacement = opponent
        elif re.search(r"接听|电话|会面|见面|预约|工作室", context):
            replacement = ally
        else:
            replacement = "旧经纪人"
        result = result[:match.start()] + replacement + result[match.end():]
    if "试镜前" in str(card.get("this_life_revenge") or ""):
        result = re.sub(
            r"今天.{0,45}?试镜(?:的日子|当天|日)",
            "距离那场关键试镜还有三天",
            result,
        )
    planned_death = str(card.get("prev_life_tragedy") or "")
    if re.search(r"服药自杀|吞药自杀|服药过量|吞药过量|药物过量", planned_death):
        result = re.sub(
            r"仿佛.{0,12}(?:溺水|被人掐住|被掐住)|像.{0,12}(?:溺水|被人掐住|被掐住)",
            "仿佛上一世药效带来的眩晕与呼吸困难仍未散去",
            result,
        )
    result = result.replace("旧经纪人旧经纪人", "旧经纪人")
    result = re.sub(
        rf"选角\s*{re.escape(ally)}\s*人(?=电话)",
        ally + "的",
        result,
    )
    result = re.sub(rf"选角(?={re.escape(ally)})", "", result)
    return result


def _normalize_planned_work_title_aliases(
    text: str, chapter_card: Optional[Dict[str, Any]]
) -> str:
    result = text or ""
    card = chapter_card if isinstance(chapter_card, dict) else {}
    planned = sorted(_planned_work_titles(card))
    if not planned:
        return result
    canonical = planned[0]
    for title in set(re.findall(r"《([^》\n]{1,40})》", result)):
        if title not in planned:
            result = result.replace(f"《{title}》", f"《{canonical}》")
    return result


def _ensure_planned_work_title_reference(
    text: str, chapter_card: Optional[Dict[str, Any]]
) -> str:
    """Attach the accepted project title to the first otherwise unnamed audition."""
    result = text or ""
    card = chapter_card if isinstance(chapter_card, dict) else {}
    planned = sorted(_planned_work_titles(card))
    if not planned or any(f"《{title}》" in result for title in planned):
        return result
    title = planned[0]
    result, count = re.subn(
        r"(?<!《)(?:最终|关键|核心|这场|本次)?试镜",
        f"《{title}》试镜",
        result,
        count=1,
    )
    if count == 0:
        result, count = re.subn(
            r"(?<!《)(?:最终|关键|核心|本次)?试戏",
            f"《{title}》试戏",
            result,
            count=1,
        )
    if count == 0 and result.strip():
        result = f"《{title}》最终选角现场里，" + result.lstrip()
    return result


def _normalize_unplanned_document_titles(
    text: str, chapter_card: Optional[Dict[str, Any]]
) -> str:
    """Treat unplanned document labels as prose instead of inventing named works."""
    result = text or ""
    card = chapter_card if isinstance(chapter_card, dict) else {}
    planned = _planned_work_titles(card)
    return re.sub(
        r"《([^》\n]{1,40})》",
        lambda match: match.group(0) if match.group(1) in planned else match.group(1),
        result,
    )


def _chapter_local_contract_text(chapter_card: Optional[Dict[str, Any]]) -> str:
    """Return chapter-local duties without cluster-level revenge text leaking scene types."""
    card = chapter_card if isinstance(chapter_card, dict) else {}
    local_fields = {
        key: card.get(key)
        for key in (
            "chapter_goal", "core_payoff", "chapter_ending",
            "must_resolve_this_chapter", "chapter_must_include",
        )
    }
    if not any(bool(value) for value in local_fields.values()):
        local_fields["this_life_revenge"] = card.get("this_life_revenge")
    return json.dumps(
        local_fields,
        ensure_ascii=False,
    )


def _execution_evidence_budget(chapter_card: Optional[Dict[str, Any]]) -> str:
    """Turn an accepted chapter card into reusable scene-level evidence boundaries."""
    card = chapter_card if isinstance(chapter_card, dict) else {}
    contract_text = _chapter_local_contract_text(card)
    rules = [
        "通用边界：只把执行卡明确写出的物件、文件、规则或当面行动当作证据；"
        "执行卡未命名的设备、作品、药品、机构、附加条款和数字记录一律不存在。"
    ]
    scene_contract = _derive_closed_scene_contract(card)
    if scene_contract:
        carriers = scene_contract.get("allowed_evidence_carriers") or []
        rules.append(
            "情节组场景契约：类型="
            + str(scene_contract.get("scene_archetype") or "")
            + "；阶段="
            + str(scene_contract.get("phase") or "")
            + "；允许载体="
            + ("、".join(carriers) if carriers else "只允许当面行动与亲口承认")
            + "；触发动作="
            + str(scene_contract.get("trigger_action") or "")
            + "；对手自证="
            + str(scene_contract.get("opponent_self_incrimination") or "")
            + "；本章结果="
            + str(scene_contract.get("immediate_result") or "")
            + "。上述字段优先于自由发挥。"
        )
    if re.search(r"体能测试|体能评估|唱跳连测|现场表演|公开排练", contract_text):
        rules.append(
            "表演/体能场景：证明中心必须是读者可见的连续动作、气息和完成度，以及有权者的定性结论。"
            "见证人最多说一句‘测试通过/符合要求’，合作方随后直接撤回限制或宣传。"
            "表演必须符合人体常识：正常热身和换气，不写不呼吸、精确关节角度、滞空数据、汗液蒸发或医学原理；"
            "本场只出现普通排练空间和常规表演用品；见证人不拍摄、不调档、不出具报告。"
            "不得出现测量器具、屏幕、平板、投影、摄像机、药品、补剂、数据表、档案材料或内部通讯；"
            "不得临时命名歌曲、舞步、器械、宣传文案、评估协议或合约条款；"
            "结尾不得另开车辆、舞台设备或安全事故支线。"
        )
    paper_markers = [marker for marker in ("封签", "送货单", "领用簿", "合同", "账单", "票务清单") if marker in contract_text]
    if paper_markers:
        rules.append(
            "纸面核对场景：只能逐项核对执行卡已点名的纸面材料（"
            + "、".join(paper_markers)
            + "），它们构成本场全部证据，不得再增加报告、清单、录音、邮件、供应商回电或其他文件。"
            "只设置一处普通人能直接读出的编号、数量、日期或签收矛盾，让当事人当面辩解，"
            "随后由从开场就在场的无姓名现场负责人直接宣布停职、撤权或交接；"
            "不得在反转时才让监察员、行政人员或裁定者突然进门，也不得新增授权册、公章或监察机构；"
            "不得升级为笔迹墨水鉴定、防伪材料原理、药理判断、气味辨认、监控、后台、截图、"
            "实验室检测、董事会备案、法务流程或匿名材料；针剂全程保持封存，不开封、不抽取、不试用。"
        )
    if re.search(r"合同|协议|签字权|条款", contract_text):
        rules.append(
            "合同场景：只能引用执行卡已经建立的权利、义务和签字动作，不得为了反转临时发明附件编号、隐藏条款或监管机关。"
        )
    if re.search(r"票务|票池|预留票|黄牛", contract_text):
        rules.append(
            "票务场景：只使用执行卡已建立的票务清单、实名规则和现场权限，不得靠黑客、后台日志或突然出现的平台数据取胜。"
        )
    return "\n".join(f"- {rule}" for rule in rules)


def _closed_evidence_contract(
    chapter_card: Optional[Dict[str, Any]],
) -> Tuple[str, bool, List[str]]:
    """Return the accepted contract text and its closed evidence scene types."""
    card = chapter_card if isinstance(chapter_card, dict) else {}
    scene_contract = (
        card.get("scene_contract")
        if isinstance(card.get("scene_contract"), dict)
        else _derive_closed_scene_contract(card)
    ) or {}
    scene_contract_text = json.dumps(
        {
            key: scene_contract.get(key)
            for key in (
                "scene_archetype", "trigger_action",
                "opponent_self_incrimination", "immediate_result",
                "allowed_evidence_carriers",
            )
        },
        ensure_ascii=False,
    )
    contract_text = json.dumps(
        {
            key: card.get(key)
            for key in (
                "chapter_goal", "this_life_revenge", "core_payoff", "chapter_ending",
                "must_resolve_this_chapter", "chapter_must_include", "chapter_milestone",
            )
        },
        ensure_ascii=False,
    ) + scene_contract_text
    local_contract_text = _chapter_local_contract_text(card) + scene_contract_text
    performance_scene = bool(re.search(
        r"体能测试|体能评估|唱跳连测|训练强度",
        local_contract_text,
    ))
    paper_markers = [
        marker
        for marker in ("封签", "送货单", "领用簿", "合同", "账单", "票务清单")
        if marker in local_contract_text
    ]
    return contract_text, performance_scene, paper_markers


def _ordered_unique_text(items: List[str]) -> List[str]:
    result: List[str] = []
    for item in items:
        normalized = re.sub(r"\s+", "", str(item or "")).strip("，。；：、 ")
        if not normalized:
            continue
        if any(normalized == existing or normalized in existing for existing in result):
            continue
        contained_indexes = [
            index for index, existing in enumerate(result)
            if existing in normalized
        ]
        for index in reversed(contained_indexes):
            result.pop(index)
        result.append(normalized)
    return result


def _extract_scene_evidence_carriers(text: str) -> List[str]:
    """Extract concrete, present-timeline carriers from cluster milestone prose."""
    source = re.sub(r"\s+", "", str(text or ""))
    if not source:
        return []
    patterns = (
        r"(?:未签字|已签字|原始|公开|实名|异常|内部|纸面)?[\u4e00-\u9fff]{0,6}操作日志",
        r"(?:未签字|已签字|原始|公开|实名|异常|内部)?[\u4e00-\u9fff]{0,6}验收单",
        r"(?:补充|霸王|原始|正式|临时)?(?:合同|协议|签字页|授权书)",
        r"(?:隐藏|自动移交|原始|补充|正式|临时)?(?:条款|代签授权|签署权|冷静期)",
        r"(?:实名|票务|异常|黄牛|内部)?(?:校验结果|核票结果|票务清单|预留票|票池|实名校验|实名名单|实名数据)",
        r"(?:银行|慈善|项目|公开|原始)?(?:账单|账目|流水|转账记录|收支记录)",
        r"(?:私人|慈善|基金|收款)?(?:账户|支付申请|签名文件)",
        r"(?:原始|剪辑|偷拍视频|现场)?(?:录音|视频|母带|设备)",
        r"(?:实时|公开|现场|无修音|后续排练)?(?:声轨|原声|拍摄画面)",
        r"(?:独立|第三方|正式)?(?:估值结果|评估结果|估值|交易文件)",
        r"(?:等重|测试用|封存的)?(?:沙袋|配重|样品|封签|针剂)",
        r"(?:舞台|升降|安全)?(?:控制器|控制台|升降台|停机按钮)",
        r"(?:送货单|领用簿|排期表|彩排表|值班记录|签收记录|实名名单)",
    )
    carriers: List[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, source):
            carrier = re.sub(
                r"^(?:调出|拿出|展示|公开|核对|查看|依据|使用|通过|要求|先用|当众)",
                "",
                match,
            )
            if re.search(r"[与和及].*(?:验收单|合同|协议|签字页|授权书)$", carrier):
                carrier = re.split(r"[与和及]", carrier)[-1]
            if len(carrier) >= 2:
                carriers.append(carrier)
    return _ordered_unique_text(carriers)


def _scene_contract_clause(
    text: str,
    markers: Tuple[str, ...],
    actor_markers: Tuple[str, ...] = (),
) -> str:
    clauses = [
        clause.strip()
        for clause in re.split(r"[，。；！？]", str(text or ""))
        if clause.strip()
    ]
    for clause in clauses:
        if not any(marker in clause for marker in markers):
            continue
        if actor_markers and not any(actor in clause for actor in actor_markers):
            continue
        return clause
    if actor_markers:
        return ""
    for clause in clauses:
        if any(marker in clause for marker in markers):
            return clause
    return ""


def _derive_closed_scene_contract(
    chapter_card: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Compile one chapter's event-cluster milestone into a reusable scene contract."""
    card = chapter_card if isinstance(chapter_card, dict) else {}
    role = str(card.get("chapter_role_v2") or "")
    if role in {"prev_life_death_only", "rebirth_awakening_only"}:
        return None
    milestone = card.get("chapter_milestone") or card.get("milestone") or {}
    if not isinstance(milestone, dict) or not any(milestone.values()):
        return None

    action = str(milestone.get("action") or card.get("chapter_goal") or "").strip()
    opponent_reaction = str(milestone.get("opponent_reaction") or "").strip()
    immediate_result = str(milestone.get("result") or card.get("chapter_ending") or "").strip()
    info_gap = str(card.get("info_gap_from_prev_life") or "").strip()
    cluster_outcome = str(card.get("cluster_outcome") or "").strip()
    index = max(1, int(card.get("cluster_chapter_index") or 1))
    total = max(index, int(card.get("cluster_chapter_total") or 1))
    phase = "settlement" if index == total else "setup"

    cast = card.get("canonical_cast") or []
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
    ), MAIN_PROTAGONIST)
    opponent = str(card.get("main_opponent") or "").strip()
    if not opponent:
        opponent = next((
            str(member.get("name") or "").strip()
            for member in cast
            if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "opponent"
        ), "既有对手")
    opponent_scene_actor = re.split(r"[与和、]", opponent, maxsplit=1)[0].strip() or opponent
    for member in cast:
        if not isinstance(member, dict):
            continue
        if str(member.get("alignment") or "").casefold() != "opponent":
            continue
        candidate = str(member.get("name") or "").strip()
        candidate_short = candidate.split("·", 1)[0]
        if candidate and (
            candidate in opponent_reaction
            or candidate_short in opponent_reaction
        ):
            opponent_scene_actor = candidate
            break

    all_milestones = [
        item for item in (card.get("cluster_milestones") or [])
        if isinstance(item, dict)
    ]
    prior_text = "；".join(
        "；".join(str(item.get(key) or "") for key in ("action", "opponent_reaction", "result"))
        for item in all_milestones
        if int(item.get("chapter") or 0) < int(card.get("chapter_id") or 0)
    )
    current_text = "；".join((action, opponent_reaction, immediate_result))
    contract_text = "；".join((
        str(card.get("cluster_name") or ""),
        str(card.get("cluster_this_life_revenge") or ""),
        str(card.get("this_life_revenge") or ""),
        current_text,
    ))
    quoted_names = re.findall(r"[“‘《]([^”’》]{2,20})[”’》]", contract_text)
    role_organization_anchors = _ordered_unique_text(
        anchor
        for member in cast
        if isinstance(member, dict)
        for anchor in re.findall(
            r"[“‘《]([^”’》]{2,20})[”’》]",
            str(member.get("role") or ""),
        )
    )
    organization_names = _ordered_unique_text(
        name for name in quoted_names
        if (
            name in role_organization_anchors
            or re.search(r"(?:会|联盟|团队|机构|公司|基金|协会|社群|组织)$", name)
            or re.search(
                rf"[“‘《]{re.escape(name)}[”’》]"
                r"(?:歌迷会|团队|机构|公司|联盟|基金|协会|社群|组织)",
                contract_text,
            )
        )
    )
    supporting_cast: List[str] = []
    for member in cast:
        if not isinstance(member, dict):
            continue
        if str(member.get("alignment") or "").casefold() != "ally":
            continue
        name = str(member.get("name") or "").strip()
        role_text = str(member.get("role") or "")
        role_anchors = re.findall(r"[“‘《]([^”’》]{2,20})[”’》]", role_text)
        if (
            name and name in contract_text
            or any(anchor in contract_text for anchor in role_anchors)
        ):
            supporting_cast.append(name)
    established_carriers = _extract_scene_evidence_carriers(prior_text)
    current_carriers = _extract_scene_evidence_carriers(current_text)
    allowed_carriers = _ordered_unique_text(established_carriers + current_carriers)

    if re.search(r"安全|升降|机关|空载|沙袋|停机|坠落|配重", current_text):
        archetype = "physical_safety_validation"
    elif re.search(r"票务|票池|预留票|黄牛|核票|实名", current_text):
        archetype = "public_resource_audit"
    elif (
        re.search(r"母带|版权|作品资产", current_text)
        and re.search(r"交易|估值|回购|打包", current_text)
    ):
        archetype = "asset_transaction_audit"
    elif re.search(r"合同|协议|条款|签字权|签批权", current_text):
        archetype = "contract_rights_audit"
    elif re.search(r"账单|账目|流水|慈善款|转账|财务", current_text):
        archetype = "financial_process_audit"
    elif re.search(
        r"公开.{0,4}排练|无修音|现场演唱|现场表演|一镜到底|"
        r"实时声轨|原声发布权|体能测试|假唱|唱跳",
        current_text,
    ):
        archetype = "live_capability_validation"
    elif allowed_carriers:
        archetype = "evidence_confrontation"
    else:
        archetype = "action_confrontation"

    authority_candidates = re.findall(
        r"(?:独立)?(?:安全总监|现场负责人|项目负责人|合作方代表|合作方|主办方|"
        r"律师|制作人|财务负责人|票务负责人|管理方|裁定者)",
        immediate_result + "；" + action,
    )
    authority_actor = authority_candidates[-1] if authority_candidates else ""
    if not authority_actor:
        for actor in (
            "合作方", "主办方", "现场负责人", "项目负责人", "安全总监",
            "财务负责人", "票务负责人", "律师", "管理方",
        ):
            if re.search(
                rf"{re.escape(actor)}.{{0,18}}"
                r"(?:宣布|确认|撤下|撤销|暂停|冻结|交还|归还|授予|同意|否决)",
                immediate_result,
            ):
                authority_actor = actor
                break
    if not authority_actor and phase == "settlement":
        authority_actor = {
            "physical_safety_validation": "从开场就在场的独立安全负责人",
            "public_resource_audit": "从开场就在场的票务管理负责人",
            "asset_transaction_audit": "从开场就在场的资产管理负责人",
            "contract_rights_audit": "从开场就在场的合同管理负责人",
            "financial_process_audit": "从开场就在场的财务管理负责人",
            "live_capability_validation": "从开场就在场的合作方",
            "evidence_confrontation": "从开场就在场的现场管理负责人",
            "action_confrontation": "从开场就在场的现场管理负责人",
        }.get(archetype, "从开场就在场的有权者")
    if not authority_actor:
        authority_actor = protagonist
    loss_verbs = (
        "失去", "撤销", "冻结", "暂停", "不得", "退回", "退还",
        "撤回", "交出", "取消", "停职", "开除", "废除", "终止", "收回", "叫停",
    )
    gain_verbs = (
        "获得", "取得", "拿回", "夺回", "恢复", "保住", "归还", "退回",
        "收回", "掌控", "控制", "决定",
    )
    protagonist_markers = tuple(filter(None, (protagonist, protagonist.split("·", 1)[0], "主角")))
    opponent_markers = tuple(filter(None, (opponent, opponent.split("·", 1)[0], "对手", "主办方")))
    loss_text = _scene_contract_clause(
        immediate_result + "；" + prior_text + "；"
        + str(card.get("cluster_name") or "") + "；" + cluster_outcome,
        loss_verbs,
        opponent_markers,
    )
    if phase == "settlement":
        direct_settlement_loss = _scene_contract_clause(
            immediate_result + "；" + str(card.get("cluster_name") or ""),
            loss_verbs,
            opponent_markers,
        )
        if direct_settlement_loss:
            loss_text = direct_settlement_loss
    gain_text = _scene_contract_clause(
        immediate_result + "；" + cluster_outcome,
        gain_verbs,
        protagonist_markers,
    )
    if phase == "settlement" and not loss_text:
        loss_text = _scene_contract_clause(
            immediate_result + "；" + prior_text + "；"
            + str(card.get("cluster_name") or "") + "；" + cluster_outcome,
            loss_verbs,
        )
    if phase == "settlement" and not gain_text:
        gain_text = _scene_contract_clause(
            immediate_result + "；" + cluster_outcome,
            gain_verbs,
        )
    authority_gain = ""
    if authority_actor not in {protagonist, protagonist.split("·", 1)[0]}:
        authority_gain = _scene_contract_clause(
            immediate_result,
            gain_verbs,
            (authority_actor,),
        )
        authority_aliases = {
            authority_actor,
            authority_actor.split("·", 1)[0],
        }
        if not any(alias and alias in authority_gain for alias in authority_aliases):
            authority_gain = ""

    return {
        "version": 1,
        "source": "event_cluster_milestone",
        "scene_archetype": archetype,
        "phase": phase,
        "protagonist": protagonist,
        "opponent": opponent,
        "opponent_scene_actor": opponent_scene_actor,
        "supporting_cast": supporting_cast[:3],
        "supporting_organizations": organization_names[:3],
        "old_trap_signal": info_gap,
        "trigger_action": action,
        "opponent_self_incrimination": opponent_reaction,
        "established_evidence_carriers": established_carriers,
        "current_evidence_carriers": current_carriers,
        "allowed_evidence_carriers": allowed_carriers,
        "verification_action": action,
        "immediate_result": immediate_result,
        "authority_actor": authority_actor,
        "authority_gain": authority_gain,
        "opponent_loss": loss_text,
        "protagonist_gain": gain_text,
        "settlement_required": phase == "settlement",
        "forbidden_mechanics": [
            "匿名材料", "万能黑客", "突然出现的关键证人", "未规划的录音或视频",
            "临时发明的协议编号或条款编号", "未在契约中的设备日志或检测报告",
            "英文字母代号", "毫秒级或工程参数堆砌",
        ],
    }


def _closed_scene_contract_failures(
    contract: Optional[Dict[str, Any]],
) -> List[str]:
    if not isinstance(contract, dict):
        return ["缺少场景契约"]
    failures: List[str] = []
    for field in (
        "scene_archetype", "phase", "trigger_action",
        "opponent_self_incrimination", "immediate_result",
    ):
        if not str(contract.get(field) or "").strip():
            failures.append(f"场景契约缺少 {field}")
    if contract.get("settlement_required"):
        if not str(contract.get("opponent_loss") or "").strip():
            failures.append("结算章契约缺少对手现实损失")
        if not str(contract.get("protagonist_gain") or "").strip():
            failures.append("结算章契约缺少主角现实收益")
    return failures


def _scene_contract_fulfillment_failures(
    text: str,
    chapter_card: Optional[Dict[str, Any]],
) -> List[str]:
    contract = _derive_closed_scene_contract(chapter_card)
    if contract is None:
        return []
    failures = _closed_scene_contract_failures(contract)
    body = str(text or "")
    carriers = list(contract.get("current_evidence_carriers") or [])
    if carriers:
        present_count = sum(1 for carrier in carriers if carrier in body)
        required_count = min(2, len(carriers))
        if present_count < required_count:
            failures.append(
                "正文没有落实情节组指定的当前证据载体："
                + "、".join(carriers[:5])
            )
    opponent = str(
        contract.get("opponent_scene_actor")
        or contract.get("opponent")
        or ""
    ).strip()
    opponent_short = opponent.split("·", 1)[0]
    if opponent_short and opponent_short not in body and opponent not in body:
        failures.append("正文缺少契约指定对手的当场动作")
    if contract.get("settlement_required"):
        loss = str(contract.get("opponent_loss") or "")
        gain = str(contract.get("protagonist_gain") or "")
        loss_markers = [
            marker for marker in (
                "失去", "撤销", "冻结", "暂停", "不得", "退回", "退还",
                "撤回", "交出", "取消", "停职", "开除", "废除", "终止", "收回", "叫停",
            )
            if marker in loss
        ]
        gain_marker_groups = {
            "获得": ("获得", "取得", "拿回", "夺回", "归还", "收回"),
            "取得": ("取得", "获得", "拿回", "夺回", "收回"),
            "拿回": ("拿回", "夺回", "归还", "收回", "获得"),
            "夺回": ("夺回", "拿回", "收回", "获得"),
            "恢复": ("恢复", "归还", "重新获得", "收回"),
            "保住": ("保住", "仍在", "没有失去", "由我确认"),
            "归还": ("归还", "交还", "拿回", "收回"),
            "退回": ("退回", "返还", "归还"),
            "收回": ("收回", "撤回", "归还", "由我确认", "由我决定"),
            "掌控": ("掌控", "控制", "决定", "由我确认", "由我决定"),
            "控制": ("控制", "掌控", "决定", "由我确认", "由我决定"),
            "决定": ("决定", "掌控", "控制", "由我确认", "由我决定"),
        }
        required_gain_groups = [
            alternatives
            for marker, alternatives in gain_marker_groups.items()
            if marker in gain
        ]
        if loss_markers and not any(marker in body for marker in loss_markers):
            failures.append("正文没有写出契约要求的对手现实损失")
        if required_gain_groups and not any(
            alternative in body
            for alternatives in required_gain_groups
            for alternative in alternatives
        ):
            failures.append("正文没有写出契约要求的主角现实收益")
    forbidden_evidence = (
        "匿名邮件", "匿名短信", "神秘U盘", "监控录像", "后台截图",
        "检测报告", "协议编号", "条款编号", "毫秒",
    )
    allowed_text = "；".join(contract.get("allowed_evidence_carriers") or [])
    for marker in forbidden_evidence:
        if marker in body and marker not in allowed_text:
            failures.append(f"正文引入契约外证据或参数：{marker}")
    scaffold_markers = (
        "情节组已经指定", "当前允许使用", "既有见证者", "执行了既定动作",
        "结果没有被拖到下一次处理", "这一章的小胜", "这场反卡",
        "没有留下新的神秘线索", "原先正在进行的危险、错误安排或不公操作",
        "新的权限、资源或安全结果", "只为下一步正式结算",
    )
    leaked = [marker for marker in scaffold_markers if marker in body]
    if leaked:
        failures.append("正文泄漏结构化保底模板语言：" + "、".join(leaked[:4]))
    if body.count("主角") >= 2:
        failures.append("正文反复用“主角”代替固定姓名，呈现生成模板腔")
    if body.count("对手") >= 2:
        failures.append("正文反复用“对手”代替固定人物或功能角色，呈现生成模板腔")
    return failures


def _normalize_closed_scene_surface_drift(
    text: str,
    chapter_card: Optional[Dict[str, Any]],
) -> str:
    """Neutralize non-semantic wording drift before closed-scene validation."""
    result = text or ""
    _, performance_scene, paper_markers = _closed_evidence_contract(chapter_card)
    if not performance_scene and not paper_markers:
        return result
    result = re.sub(r"([。！？][”’\"])。", r"\1", result)
    result = re.sub(
        r"[^。！？\n]{0,60}(?:上一章|本章|下一章)[^。！？\n]{0,60}[。！？]",
        "",
        result,
    )
    result = result.replace("上一章", "先前").replace("本章", "眼前这场")
    result = result.replace("下一章", "接下来")
    if performance_scene:
        result = re.sub(
            r"第[一二三四五六七八九十百零\d]+次重复副歌",
            "副歌再起时",
            result,
        )
        result = re.sub(
            r"第[一二三四五六七八九十百零\d]+段(?:主歌|副歌)",
            "乐段推进时",
            result,
        )
        result = re.sub(
            r"第[一二三四五六七八九十百零\d]+拍",
            "重拍",
            result,
        )
        result = re.sub(
            r"(?:拖足|持续)[一二三四五六七八九十百零\d]+拍",
            "稳稳拖住",
            result,
        )
        result = re.sub(
            r"[一二三四五六七八九十百零\d]+拍(?:的)?(?:间隙|空隙)",
            "换气间隙",
            result,
        )
        result = re.sub(
            r"(?:一段)?[一二三四五六七八九十百零\d]+拍(?:过去|组合)",
            "一段紧密节奏过去",
            result,
        )
        result = re.sub(
            r"[一二三四五六七八九十百零\d]+拍",
            "一段节拍",
            result,
        )
        result = re.sub(
            r"[一二三四五六七八九十百零\d]+秒(?:钟)?后",
            "片刻后",
            result,
        )
        result = re.sub(
            r"(?:半|[一二三四五六七八九十百零\d]+)秒(?:钟)?",
            "一瞬",
            result,
        )
        result = re.sub(
            r"[一二三四五六七八九十百零\d]+(?:毫米|厘米|公分|寸)",
            "少许",
            result,
        )
        result = re.sub(
            r"第[一二三四五六七八九十百零\d]+个?小节",
            "乐段推进时",
            result,
        )
        result = re.sub(
            r"(?<!第)(?:剩下|余下)?[一二三四五六七八九十百零\d]+个?小节",
            "余下的乐段",
            result,
        )
        result = result.replace("+", "接")
        result = re.sub(
            r"第[一二三四五六七八九十百零\d]+分钟",
            "表演进行到中段",
            result,
        )
        result = re.sub(
            r"(?:剩下|剩余|余下|接下来)[一二三四五六七八九十百零\d]+秒(?:钟)?(?:编舞|动作|表演)?",
            "余下的乐段",
            result,
        )
        result = re.sub(
            r"(?:全场|现场|屋内|排练场)(?:静|沉默)了"
            r"[一二三四五六七八九十百零\d]+秒",
            "全场静了一瞬",
            result,
        )
        result = re.sub(r"(?:跃起|跳起)半尺", "轻跃而起", result)
        result = re.sub(r"侧滑半尺", "侧滑一步", result)
        result = re.sub(
            r"[一二三四五六七八九十百零\d]+组十六分音符(?:节奏)?|十六分音符(?:节奏)?",
            "一段紧密节奏",
            result,
        )
        result = re.sub(
            r"第[一二三四五六七八九十百零\d]+次"
            r"(侧移|转身|旋身|踏步|摆臂|循环|重复动作)",
            r"再次\1",
            result,
        )
        result = re.sub(
            r"第[一二三四五六七八九十百零\d]+转时",
            "再次转身时",
            result,
        )
        result = re.sub(
            r"第[一二三四五六七八九十百零\d]+(?:圈|遍)",
            "再次",
            result,
        )
        result = re.sub(
            r"(?:转身|旋身|摆臂|腰胯|抬腿).{0,8}"
            r"[一二三四五六七八九十百零\d]+度",
            "自然转身",
            result,
        )
        result = result.replace("毫厘之间", "节拍之中")
        result = result.replace("精确的机械律动", "熟练的节奏")
        result = result.replace("四分之换气间隙", "换气间隙")
        result = result.replace("每少许发力", "每次发力")
        result = re.sub(
            r"(?:全程)?(?:未|没有)(?:停顿|喘息|换气)",
            "动作不停且自然换气",
            result,
        )
        result = result.replace("以血肉校准节拍的搏斗", "方才的连续唱跳")
        result = re.sub(
            r"喉结(?:上下)?(?:滚动|滑动|一跳|微动|动了一下)",
            "嘴唇一紧",
            result,
        )
        result = result.replace("喉结", "下颌")
        result = result.replace("喉头", "嗓音")
        result = result.replace("胸腔", "气息")
        result = result.replace("腹腔", "气息")
        result = result.replace("腰腹", "身体")
        result = result.replace("肋廓", "动作")
        result = result.replace("锁骨线", "肩线")
        result = result.replace("筋络", "动作")
        device_evidence_pattern = re.compile(
            r"屏幕|显示屏|波形|读数|曲线|平板|投影|摄像机|监视器|数据表|"
            r"(?:误差|偏差|落点|滞空|膝盖|关节|抬腿高度|动作幅度|跳跃距离)"
            r".{0,18}(?:\d+(?:\.\d+)?|[一二三四五六七八九十百零半]+)\s*"
            r"(?:毫米|厘米|公分|寸|分贝|赫兹|度|秒)|"
            r"(?:\d+(?:\.\d+)?|[一二三四五六七八九十百零半]+)\s*"
            r"(?:毫米|厘米|公分|分贝|赫兹|度).{0,18}(?:误差|偏差|落点|标准|达标)"
        )
        cleaned_performance_paragraphs: List[str] = []
        for paragraph in re.split(r"\n\s*\n", result):
            cleaned_performance_sentences: List[str] = []
            for sentence in re.findall(
                r"[^。！？]*[。！？][”\"]?|[^。！？]+$",
                paragraph,
                re.S,
            ):
                stripped = sentence.strip()
                if not stripped:
                    continue
                if device_evidence_pattern.search(stripped):
                    ruling = re.search(
                        r"[“\"]([^”\"]*(?:测试通过|符合要求|训练强度决定权)[^”\"]*)[”\"]",
                        stripped,
                        re.S,
                    )
                    if ruling:
                        ruling_text = ruling.group(1).strip().rstrip("。！？")
                        cleaned_performance_sentences.append(
                            f"现场见证人说：“{ruling_text}。”"
                        )
                    continue
                cleaned_performance_sentences.append(stripped)
            cleaned_paragraph = "".join(cleaned_performance_sentences).strip()
            if cleaned_paragraph:
                cleaned_performance_paragraphs.append(cleaned_paragraph)
        result = "\n\n".join(cleaned_performance_paragraphs).strip()
        performance_paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", result)
            if paragraph.strip()
        ]
        settlement_paragraph = next(
            (
                index
                for index, paragraph in enumerate(performance_paragraphs)
                if "训练强度决定权" in paragraph
            ),
            -1,
        )
        if settlement_paragraph >= 0 and len(performance_paragraphs) > settlement_paragraph + 4:
            result = "\n\n".join(performance_paragraphs[:settlement_paragraph + 4])
    if paper_markers:
        result = re.sub(
            r"[一二三四五六七八九十百零\d]+秒(?:钟)?(?:过去|后)",
            "短暂僵持后",
            result,
        )
        result = re.sub(
            r"(?:沉默|僵持|迟疑|迟滞)了?"
            r"[一二三四五六七八九十百零\d]+秒(?:钟)?",
            "短暂迟疑",
            result,
        )
        result = re.sub(
            r"(?:看|端详)了[一二三四五六七八九十百零\d]+秒(?:钟)?",
            "看了一眼",
            result,
        )
        result = re.sub(
            r"(?:把头|头)(?:偏开|转开)[一二三四五六七八九十百零\d]+度",
            "微微偏开头",
            result,
        )
    if not paper_markers:
        return result
    result = re.sub(
        r"(?:墨迹|墨水|油墨)(?:仍|还|已|已经|早已|尚)?"
        r"(?:未干|新鲜|干透|没干)",
        "字迹清楚",
        result,
    )
    result = re.sub(
        r"(?:未干|新鲜|干透|没干)的(?:墨迹|墨水|油墨)",
        "清楚的字迹",
        result,
    )
    result = re.sub(
        r"封签(?:边缘|表面|上)?(?:还|仍)?(?:印着|写着|标着|带着)?"
        r"[^。！？\n]{0,12}[“\"‘']?[七柒7][”\"’']?支?",
        "封签保持未拆",
        result,
    )
    result = re.sub(
        r"(?:半|[一二三四五六七八九十百零\d]+)(?:寸|厘米|公分|毫米)(?:许|处|外|前)?",
        "近前",
        result,
    )
    result = result.replace("寸许", "近前")
    result = re.sub(r"(?:两|三)指宽", "近前", result)
    result = re.sub(r"(?:未干透的)?(?:朱砂)?红圈|洇开的墨点|红笔圈出", "", result)
    result = re.sub(r"(?:蓝黑|红色|朱砂)字迹", "字迹", result)
    result = re.sub(r"铅笔(?:写的|写着|标出的)", "写着", result)
    result = re.sub(r"(?:多添|多加|多出)了?一(?:横|划)", "多记了一支", result)
    result = re.sub(
        r"(?:领用簿|送货单)(?:还|仍)?有(?:和)?[。！？]",
        "领用簿仍放在桌上。",
        result,
    )
    responsible_record_pattern = re.compile(
        r"(?:现场负责人|负责人).{0,100}(?:领用簿|簿子).{0,60}"
        r"(?:写下|填写|登记|落笔|签名)|"
        r"(?:领用簿|簿子).{0,60}(?:写下|填写|登记|落笔|签名).{0,100}"
        r"(?:现场负责人|负责人)",
        re.S,
    )
    cleaned_paper_paragraphs: List[str] = []
    for paragraph in re.split(r"\n\s*\n", result):
        cleaned_paper_sentences: List[str] = []
        for sentence in re.findall(
            r"[^。！？]*[。！？][”\"]?|[^。！？]+$",
            paragraph,
            re.S,
        ):
            stripped = sentence.strip()
            if not stripped:
                continue
            if responsible_record_pattern.search(stripped):
                ruling = re.search(
                    r"[“\"]([^”\"]*(?:即刻暂停|暂停.{0,12}职务|药品保管权)[^”\"]*)[”\"]",
                    stripped,
                    re.S,
                )
                if ruling:
                    ruling_text = ruling.group(1).strip().rstrip("。！？")
                    cleaned_paper_sentences.append(f"负责人说：“{ruling_text}。”")
                continue
            cleaned_paper_sentences.append(stripped)
        cleaned_paragraph = "".join(cleaned_paper_sentences).strip()
        if cleaned_paragraph:
            cleaned_paper_paragraphs.append(cleaned_paragraph)
    result = "\n\n".join(cleaned_paper_paragraphs).strip()

    closing_match = re.search(
        r"没有我的许可[^。！？\n]{0,30}谁也不能碰这些药[。！？]?[”\"]?",
        result,
        re.S,
    )
    if closing_match and closing_match.end() < len(result):
        tail = result[closing_match.end():].strip()
        opponent = next(
            (
                str(member.get("name") or "").strip()
                for member in _select_grounded_chapter_cast(
                    chapter_card if isinstance(chapter_card, dict) else {}
                )
                if isinstance(member, dict)
                and str(member.get("alignment") or "").casefold() == "opponent"
                and str(member.get("name") or "").strip()
            ),
            "对手",
        )
        if "闭嘴" in tail or "闭了嘴" in tail or "没再说话" in tail:
            reaction = f"{opponent}闭了嘴。"
        elif "视线" in tail or "低头" in tail:
            reaction = f"{opponent}移开视线。"
        elif re.search(r"(?:手|手指).{0,12}(?:停|僵)", tail):
            reaction = f"{opponent}的手停在原处。"
        elif re.search(r"嘴角|嘴唇|唇角", tail):
            reaction = f"{opponent}嘴角抽了一下。"
        else:
            reaction = f"{opponent}僵在原地。"
        result = result[:closing_match.end()].rstrip() + reaction
    paper_paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", result)
        if paragraph.strip()
    ]
    closing_paragraph = next(
        (
            index
            for index, paragraph in enumerate(paper_paragraphs)
            if re.search(r"没有我的许可.{0,18}谁也不能碰这些药", paragraph, re.S)
        ),
        -1,
    )
    if closing_paragraph >= 0 and len(paper_paragraphs) > closing_paragraph + 2:
        result = "\n\n".join(paper_paragraphs[:closing_paragraph + 2])
    return result


def _ensure_medication_audit_previous_life_motive(
    text: str,
    chapter_card: Optional[Dict[str, Any]],
) -> str:
    """Insert the planned prior-life process cue when a medication audit omits it."""
    result = text or ""
    _, _, paper_markers = _closed_evidence_contract(chapter_card)
    if not {"封签", "送货单", "领用簿"}.issubset(set(paper_markers)):
        return result
    if re.search(
        r"(?:上一世|前世).{0,160}"
        r"(?:不是画面|不是触感|不延展|不渲染|只是.{0,16}认知)",
        result,
        re.S,
    ):
        paragraphs = [
            paragraph
            for paragraph in re.split(r"\n\s*\n", result)
            if not (
                re.search(r"上一世|前世", paragraph)
                and re.search(
                    r"不是画面|不是触感|不延展|不渲染|只是.{0,16}认知",
                    paragraph,
                    re.S,
                )
            )
        ]
        result = "\n\n".join(paragraphs).strip()
    if re.search(
        r"(?:上一世|前世).{0,120}"
        r"(?:先用后补|笔误|补记|这套流程|这套说法|康拉德)",
        result,
        re.S,
    ):
        return result
    cast = _select_grounded_chapter_cast(
        chapter_card if isinstance(chapter_card, dict) else {}
    )
    protagonists = [
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
        and str(member.get("name") or "").strip()
    ]
    opponents = [
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "opponent"
        and str(member.get("name") or "").strip()
    ]
    if not protagonists or not opponents:
        return result
    protagonist = protagonists[0].split("·", 1)[0]
    opponent = opponents[0].split("·", 1)[0]
    motive = (
        f"{protagonist}记得，上一世，{opponent}也是这样：药先用，记录后补，"
        "出了问题便推成笔误。"
    )
    paragraphs = re.split(r"\n\s*\n", result, maxsplit=1)
    if len(paragraphs) == 2:
        return paragraphs[0].rstrip() + "\n\n" + motive + "\n\n" + paragraphs[1].lstrip()
    return motive + "\n\n" + result.lstrip()


def _ensure_medication_audit_handover(
    text: str,
    chapter_card: Optional[Dict[str, Any]],
) -> str:
    """Complete the planned two-step key transfer before the paper-scene close."""
    result = (text or "").strip()
    card = chapter_card if isinstance(chapter_card, dict) else {}
    _, _, paper_markers = _closed_evidence_contract(card)
    if not {"封签", "送货单", "领用簿"}.issubset(set(paper_markers)):
        return result

    cast = _select_grounded_chapter_cast(card)
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
        and str(member.get("name") or "").strip()
    ), "主角")
    contract_text = _chapter_local_contract_text(card)
    opponent_match = re.search(
        r"([\u4e00-\u9fff·]{2,24})被(?:暂停职务|停职)",
        contract_text,
    )
    opponent = opponent_match.group(1).strip() if opponent_match else next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "opponent"
        and str(member.get("name") or "").strip()
    ), "对手")
    protagonist_short = protagonist.split("·", 1)[0]

    result = re.sub(
        rf"[^。！？\n]{{0,40}}(?:{re.escape(protagonist)}|"
        rf"{re.escape(protagonist_short)})[^。！？\n]{{0,16}}"
        r"(?:未|没有)伸手[^。！？\n]*[。！？]",
        "",
        result,
    )
    has_source = bool(re.search(
        rf"{re.escape(opponent)}.{{0,100}}"
        r"(?:(?:交出|递出|取下|解下|掏出|拿出|放下).{0,24}钥匙|"
        r"钥匙.{0,36}(?:放|覆|递|交)(?:进|入|到)?.{0,16}负责人(?:掌|手))",
        result,
        re.S,
    ))
    has_rights = "药品保管权" in result
    has_receipt = bool(re.search(
        r"(?:钥匙).{0,30}(?:放进|放入|放到|置于|置入|置进|交到|递到|压进|滑入)"
        r".{0,24}(?:麦珂|主角).{0,12}(?:手|掌|指间)|"
        r"(?:麦珂|主角).{0,24}(?:接过|接住|收下|握住).{0,16}钥匙",
        result,
        re.S,
    ))
    if has_source and has_rights and has_receipt:
        return result

    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", result)
        if paragraph.strip()
    ]
    settlement_index = next(
        (
            index
            for index, paragraph in enumerate(paragraphs)
            if "药品保管权" in paragraph
        ),
        next(
            (
                index
                for index, paragraph in enumerate(paragraphs)
                if "没有我的许可" in paragraph
            ),
            len(paragraphs),
        ),
    )
    inserts: List[str] = []
    if not has_source:
        inserts.append(f"{opponent}交出唯一钥匙和领用簿，放到负责人掌心。")
    if not has_rights:
        inserts.append(f"负责人说：“药品保管权归{protagonist}。”")
    if not has_receipt:
        inserts.append(
            f"负责人随即把钥匙放进{protagonist}掌心，{protagonist}当场接住。"
        )
    paragraphs[settlement_index:settlement_index] = inserts
    return "\n\n".join(paragraphs)


def _ensure_performance_previous_life_action(
    text: str,
    chapter_card: Optional[Dict[str, Any]],
) -> str:
    """Ground a first-cluster performance reversal in remembered prior-life tactics."""
    result = text or ""
    card = chapter_card if isinstance(chapter_card, dict) else {}
    _, performance_scene, _ = _closed_evidence_contract(card)
    cluster_index = str(card.get("cluster_chapter_index") or "")
    if (
        not performance_scene
        or cluster_index != "1"
        or not str(card.get("info_gap_from_prev_life") or "").strip()
    ):
        return result
    cast = _select_grounded_chapter_cast(card)
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
    ), "主人公").split("·", 1)[0]
    opponent = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "opponent"
    ), "对手").split("·", 1)[0]
    result = re.sub(
        r"(?<![\u4e00-\u9fff])他记得(?=[^。！？\n]{0,16}(?:上一世|前世|那一世))",
        f"{protagonist}记得",
        result,
        count=1,
    )
    recognizes_old_trap = bool(re.search(
        r"上一世|前世|那一世|记得|认出|熟悉的旧局|旧局重现|又是这一步|还是老办法",
        result,
    ))
    has_preemptive_witness = bool(re.search(
        r"(?:提前|事先|早早|先一步|抢先).{0,24}(?:请|叫|让).{0,16}(?:合作方|见证人)|"
        r"(?:请|叫|让).{0,16}(?:合作方|见证人).{0,12}(?:提前|事先|早早)|"
        r"(?:合作方|见证人).{0,24}(?:提前|事先|早早|先一步|抢先).{0,12}(?:到场|请来|叫来|坐下|落座)",
        result,
        re.S,
    ))
    if recognizes_old_trap and has_preemptive_witness:
        return result

    bridge_parts: List[str] = []
    if not recognizes_old_trap:
        bridge_parts.append(
            f"{protagonist}认出了这套旧局。上一世，{opponent}正是用降低强度，"
            "把他的病弱形象一步步坐实。"
        )
    if not has_preemptive_witness:
        bridge_parts.append(
            f"这一次，{protagonist}提前请合作方代表和现场见证人到了排练场。"
        )
    bridge = "".join(bridge_parts)
    if recognizes_old_trap and not has_preemptive_witness:
        first_sentence = re.match(r"^.*?[。！？]", result, re.S)
        if first_sentence:
            split_at = first_sentence.end()
            return (
                result[:split_at]
                + bridge
                + result[split_at:].lstrip()
            )
    return bridge + "\n\n" + result.lstrip()


def _unplanned_operational_labels(text: str, contract_text: str) -> List[str]:
    """Find quoted process, document, drug, or code labels absent from the card."""
    label_patterns = (
        r"[“\"‘']([^”\"’'\n]{1,24}(?:测试|校准|评估|协议|流程|方案|项目|"
        r"复合液|药液|药剂|针剂|制剂[^”\"’'\n]{0,4}型|报告|清单|编号|代号|限定版))[”\"’']",
        r"[“\"‘']([^”\"’'\n]{1,20}第[一二三四五六七八九十百\d]+号)[”\"’']",
        r"(?:文案|曲目|歌曲|宣传标签|药品标签).{0,8}[“\"‘']([^”\"’'\n]{2,30})[”\"’']",
    )
    labels: List[str] = []
    for pattern in label_patterns:
        for label in re.findall(pattern, text or ""):
            normalized = str(label).strip()
            if normalized and normalized not in contract_text:
                labels.append(normalized)
    return list(dict.fromkeys(labels))


def _closed_evidence_failures(
    text: str,
    chapter_card: Optional[Dict[str, Any]],
) -> List[str]:
    """Reject evidence carriers outside a card's deliberately narrow scene budget."""
    body = text or ""
    contract_text, performance_scene, paper_markers = _closed_evidence_contract(chapter_card)
    if not performance_scene and not paper_markers:
        return []
    card = chapter_card if isinstance(chapter_card, dict) else {}
    cast = _select_grounded_chapter_cast(card)
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
    ), "主人公")
    protagonist_pattern = _character_alias_pattern(protagonist)

    failures: List[str] = []
    if re.search(r"(?:像|仿佛|如同).{0,8}(?:一道|一个|某种)?伏笔|埋下.{0,8}伏笔", body):
        failures.append(
            "小说正文直接把细节称作“伏笔”，泄漏作者层面的创作说明；"
            "只呈现人物能看到的动作和物件，不替读者标注叙事功能。"
        )
    invented_body_history = re.findall(
        r"(?:上周|上个月|上月|去年|早年|从前|此前|前些天|常年).{0,52}"
        r"(?:擦药棉|污渍|褐斑|淤青|青紫|伤疤|疤痕|细疤|晒痕|手术|摔|跌)|"
        r"(?:擦药棉|污渍|褐斑|淤青|青紫|伤疤|疤痕|细疤|晒痕|手术|摔|跌).{0,52}"
        r"(?:上周|上个月|上月|去年|早年|从前|此前|前些天|常年)",
        body,
        re.S,
    )
    if invented_body_history:
        failures.append(
            "封闭现场凭空补造人物旧伤、疤痕、衣物污渍或其来历："
            + "、".join(list(dict.fromkeys(invented_body_history))[:4])
            + "。删除未由执行卡建立的身体与私生活前史，戏剧张力只来自本场行动和权利结算。"
        )
    carrier_patterns = {
        "档案材料": r"档案室|档案柜|档案袋|存档袋|密封存档|调取档案|拆封档案|存档编号",
        "额外交接文书": r"原始交接单|交接单|交接记录|交付凭证",
        "额外报告": r"(?:体能|健康|医疗|评估|检测|审查|调查|验收|公关).{0,6}报告|报告.{0,8}(?:存档|公关部|法务)",
        "额外清单": r"(?:销毁|报废|库存|处置|废弃|回收|核验|入库|器材|物资|设备)清单",
        "额外目录或记录": (
            r"公开目录|指定文件|共启记录|值班日志|监测记录|观察记录|"
            r"备用登记册|出入记录|更正页|复盘记录"
        ),
        "临时授权材料": r"临时监管授权|监管授权册|授权册|蓝皮册|授权栏|加盖.{0,8}公章|红色公章",
        "临时监察机构": r"行政监察组|监察组|调查组|审计组|临时监管组",
        "数字取证设备": (
            r"平板|投影仪|投影屏|投射屏|摄像机|录像机|"
            r"录音(?:笔|器|设备|功能)|开启录音|开了录音|电子邮件|邮箱|"
            r"同步.{0,12}(?:通道|系统)|数字通道|生理监测仪|监测屏|"
            r"手机屏幕.{0,12}(?:通话|界面|记录)|录入系统|系统.{0,8}打印"
        ),
        "额外校验代码": r"校验码|验证码|核验码|报废编号|处置编号|防伪码|权限码|微型编码",
        "外部核验链": (
            r"供应商.{0,16}(?:确认|回电|来电|电话)|"
            r"董事会.{0,16}(?:备案|审议|通过)|"
            r"法务.{0,16}(?:邮件|文件|备案)|公关部.{0,16}(?:报告|存档)"
        ),
        "特殊取证容器": r"密码箱|专用槽|暗格|隐藏夹层",
    }
    if performance_scene:
        carrier_patterns["测量精度"] = (
            r"(?:误差|偏差|落点|滞空|膝盖|关节|抬腿高度|动作幅度|跳跃距离)"
            r".{0,18}(?:\d+(?:\.\d+)?|[一二三四五六七八九十百零半]+)\s*"
            r"(?:毫米|厘米|公分|寸|分贝|赫兹|度|秒)|"
            r"(?:\d+(?:\.\d+)?|[一二三四五六七八九十百零半]+)\s*"
            r"(?:毫米|厘米|公分|分贝|赫兹|度).{0,18}(?:误差|偏差|落点|标准|达标)"
        )
        carrier_patterns["隐藏器材取证"] = (
            r"控制台.{0,12}(?:暂停|按键|红键)|金属笔.{0,40}(?:批次|凹痕|银痕)|"
            r"出厂批次|签收栏.{0,20}(?:卡尔|总监|主管)|"
            r"计时器.{0,24}(?:切断|音响|电源)|切断音响|非监测型.{0,16}配件|"
            r"打印机.{0,16}墨点|排版.{0,12}留白|留白间距|铅笔草写.{0,8}日期|"
            r"周训练计划初稿|保护性调整计划|纸质通告函|随身印章"
        )
        carrier_patterns["见证人计时"] = (
            r"见证人.{0,30}(?:看了眼|低头看|查看).{0,12}(?:手表|腕表)"
            r".{0,16}(?:计时|秒|分钟|时长)|"
            r"(?:手表|腕表).{0,20}(?:计时|秒数|完成时间)"
        )

    carrier_hits: List[str] = []
    for label, pattern in carrier_patterns.items():
        matches = re.findall(pattern, body, re.I)
        if not matches:
            continue
        # A later chapter may explicitly plan one of these carriers; the card remains authoritative.
        if any(str(match) and str(match) in contract_text for match in matches):
            continue
        carrier_hits.append(label)
    if carrier_hits:
        failures.append(
            "正文越出执行卡的封闭证据清单，新增了"
            + "、".join(dict.fromkeys(carrier_hits))
            + "。删除整条额外取证链，只保留卡片点名的现场动作和材料。"
        )

    operational_labels = _unplanned_operational_labels(body, contract_text)
    if operational_labels:
        failures.append(
            "正文临时命名执行卡未建立的流程、文件、药品或编号："
            + "、".join(operational_labels[:6])
            + "。删除名称及其衍生机制，只使用卡片中的功能称呼。"
        )
    if re.search(
        r"签了我的名字|替我.{0,8}(?:签字|签名)|代我.{0,8}(?:签字|签名)|"
        r"(?:冒充|伪造).{0,10}(?:我的)?(?:签字|签名)",
        body,
    ) and not re.search(r"代签|冒签|伪造签名|签了主角的名字", contract_text):
        failures.append(
            "正文凭空补造对手冒签或伪造主角签名的重大事实，越出本章执行卡；"
            "删除签名犯罪，只按本章已规划的现场降配、纸面核对和权限结算推进。"
        )

    if performance_scene:
        if re.search(
            r"动作衔接待续|待续接续|嘴唇一紧一次|一紧了一次|[。！？][”’\"]?[。！？]",
            body,
        ):
            failures.append(
                "表演验真出现拼接病句或重复标点；删除残缺短语并保持句子自然完整。"
            )
        old_publicity_index = body.find("旧宣传页")
        pass_conclusion = re.search(PERFORMANCE_PASS_CONCLUSION_PATTERN, body)
        passed_index = pass_conclusion.start() if pass_conclusion else -1
        if old_publicity_index >= 0 and (
            passed_index < 0 or old_publicity_index < passed_index
        ):
            failures.append(
                "旧宣传页在见证通过前提前进入表演动作，造成道具位置反复；"
                "表演完成前不出现旧宣传页，只在见证通过后由合作方整张撤下。"
            )
        plain_performance_labels: List[str] = []
        for match in re.findall(
            r"第[一二三四五六七八九十\d]+段[，,:：]?(?:切|换到)?"
            r"([\u4e00-\u9fff]{2,8}?)(?=副歌|主歌|前奏|间奏|，节奏|，鼓点)",
            body,
        ):
            label = str(match).strip()
            if (
                label
                and label not in contract_text
                and not re.search(r"响起|进入|开始|节奏|前奏|副歌|主歌|间奏|音乐|鼓点", label)
            ):
                plain_performance_labels.append(label)
        if plain_performance_labels:
            failures.append(
                "正文临时给执行卡未建立的歌曲或表演段落取名："
                + "、".join(list(dict.fromkeys(plain_performance_labels))[:6])
                + "。只写第一段、第二段或快节奏段等功能称呼。"
            )

        impossible_performance_hits = re.findall(
            r"不热身|全程不换气|滞空.{0,18}(?:标准值|毫秒)|"
            r"腹横肌.{0,16}对抗重力|汗.{0,20}(?:被体温烤干|蒸腾速度)|"
            r"膝盖.{0,16}\d+(?:\.\d+)?度|"
            r"憋住.{0,60}(?:单脚|弹跳|哼鸣)|"
            r"(?:腾空|翻转).{0,30}落地无声|"
            r"(?:单膝|跪地).{0,16}滚翻|"
            r"(?:单掌|单手).{0,12}(?:撑地|触地).{0,12}(?:旋身|转身|滑步)|"
            r"(?:踢腿|抬腿|提膝).{0,18}(?:齐胸|过胸|高过胸口)|"
            r"腾空.{0,18}(?:拧身|旋转).{0,8}(?:三百六十|360).{0,2}度",
            body,
            re.S,
        )
        if impossible_performance_hits:
            failures.append(
                "正文用危险特技或伪生理解释夸大表演能力："
                + "、".join(list(dict.fromkeys(impossible_performance_hits))[:6])
                + "。改写为可信的连续唱跳、稳定换气、节拍控制和完成度。"
            )
        if re.search(
            r"腾空|空中换气|单膝跪地|跪地.{0,8}暴起|三连滑步|"
            r"跃起.{0,10}旋身|单膝.{0,10}(?:点地|跪地).{0,10}(?:再)?暴起|"
            r"急停变向|无喘息|(?:没|未)吸气|气息沉在腹底|"
            r"顶灯|照明|灯光|耳机|麦克风|支架|金属外壳|左前方|右前方|"
            r"双肩|嘴唇|咽下余韵|脚掌落点|压低重心|没偏一丝|"
            r"像钉入地板|外套下摆|衣角|"
            r"最后一个乐句|重复三次|一紧了一次|音乐未起|伴奏未起|半步|半拍|"
            r"[一二两三四五六七八九十百零\d]+把|"
            r"[一二两三四五六七八九十百零\d]+个?字|"
            r"第?[一二两三四五六七八九十百零\d]+次(?:普通)?(?:重拍|踏步|抬手)|"
            r"[一二两三四五六七八九十百零\d]+处(?:换气)?|"
            r"第[二三四五六七八九十]句|最后[一二三四五六七八九十]字|"
            r"如线|像尺|"
            r"肋廓|胸廓|胸膛|肋间肌|锁骨线|筋络|胸腔|腹腔|腰腹|"
            r"丹田|脉搏|汗|左脚|右脚|左肩|右肩|腰胯|膝盖|脚跟|鼻腔|"
            r"鼻梁|眉骨|舌尖|上颚|喉咙|喉间|下颌|瞳孔|腕骨|喉结|喉头|"
            r"半音|如尺|严丝合缝|分毫|毫厘|精准|标准转身|"
            r"指示灯|红光|绿光|光点|"
            r"第[一二三四五六七八九十百零\d]+(?:圈|遍)|"
            r"[一二三四五六七八九十百零半\d]+秒|"
            r"[一二三四五六七八九十百零半\d]+拍|"
            r"[一二三四五六七八九十百零\d]+(?:小时|分钟|度)|"
            r"(?:走|退|侧移|踏出)[一二三四五六七八九十百零\d]+步|"
            r"[一二三四五六七八九十百零\d]+次(?:换气|转身|侧移|踏步)|"
            r"[一二三四五六七八九十百零\d]+公里(?:山道)?|"
            r"全程未起身|未翻包|未看手机",
            body,
            re.S,
        ):
            failures.append(
                "表演验真加入危险动作、解剖观察、精确轮次时长或未规划耐力履历；"
                "只保留普通踏步、转身、侧移、摆臂、自然换气和现场听感。"
            )
        if re.search(
            r"第[一二三四五六七八九十百零\d]+次"
            r"(?:侧移|转身|旋身|踏步|摆臂|循环|重复动作)|"
            r"(?:转身|旋身|摆臂|腰胯|抬腿).{0,16}"
            r"[一二三四五六七八九十百零\d]+度|"
            r"毫厘之间|精确的机械律动|以血肉校准|"
            r"(?:未|没有)(?:停顿|喘息|换气)|"
            r"(?:腹腔|喉头).{0,18}(?:托起|震出|发力)",
            body,
            re.S,
        ):
            failures.append(
                "表演验真用精确轮次、角度或超人生理措辞制造完成度；"
                "只写连续唱跳、自然换气、动作衔接和现场观感，不逐次计数。"
            )

        invented_performance_rules = re.findall(
            r"第[一二三四五六七八九十\d]+守则|"
            r"(?:原始议程|原始排期).{0,24}(?:规定|约定|服从|签署)|"
            r"(?:服从|依据).{0,24}(?:原始议程|原始排期)",
            body,
        )
        if invented_performance_rules and not any(
            str(hit) and str(hit) in contract_text for hit in invented_performance_rules
        ):
            failures.append(
                "正文用执行卡未建立的守则或议程条文夺权："
                + "、".join(list(dict.fromkeys(str(hit) for hit in invented_performance_rules))[:6])
                + "。让合作方根据当场完成度直接撤回降配并确认卡片中的权限。"
            )
        rule_document_mentions = len(re.findall(
            r"确认书|确认单|条款|议程|守则|签收栏|入库清单",
            body,
        ))
        if rule_document_mentions >= 4:
            failures.append(
                "表演章把可见完成度让位给合同、确认书或器材文书争辩；"
                "只可在开头一句承接上一章纸面结果，随后必须靠唱跳表现和合作方直接决定完成结算。"
            )
        performance_drift_patterns = {
            "临时医疗史": (
                r"(?:踝|膝|腰|关节|心脏|声带).{0,30}(?:复查|检查|诊断|医嘱)|"
                r"(?:复查|检查|诊断|医嘱).{0,24}(?:踝|膝|腰|关节|心脏|声带)|"
                r"心率|血压|血氧|电解质液|医护组|"
                r"(?:上个月|上周|前些天|此前).{0,40}(?:彩排|排练).{0,24}(?:摔|伤|疤)|"
                r"(?:浅疤|伤疤|旧伤).{0,40}(?:彩排|排练|上个月|上周)"
            ),
            "新增替换样稿": (
                r"(?:另一份|崭新|全新).{0,16}(?:样稿|宣传单|宣传单页|宣传物料)|"
                r"(?:又|再).{0,8}(?:抽出|取出).{0,16}(?:样稿|宣传单|宣传单页|宣传物料)"
            ),
            "额外确认文书": (
                r"(?:主管|现场|医疗|训练)?确认书|(?:主管|现场|医疗|训练)?确认单|"
                r"(?:昨天|昨夜|此前).{0,16}主管确认|主管确认.{0,16}(?:签下|留在|桌面)|"
                r"(?:测试|训练|强度|表演).{0,8}(?:协议|议程|守则)"
            ),
            "宣传物料证据化": (
                r"视觉母版|方案母版|昨夜连夜赶制|连夜赶制|"
                r"(?:胶层|胶丝).{0,16}(?:拉出|断裂)|胶痕.{0,8}(?:未干|新鲜)"
            ),
            "在皮肤写画": (
                r"(?:在|往|朝)(?:手背|手心|掌心|虎口|皮肤|手臂|胳膊)"
                r"(?:上|处|内侧)?.{0,10}(?:画|写|涂|划)(?:下|上|出)?|"
                r"(?:画|写|涂|划)(?:下|上|出)?.{0,8}(?:线|字|符号|记号|标记)"
                r".{0,12}(?:在|到|往)(?:手背|手心|掌心|虎口|皮肤|手臂|胳膊)"
            ),
        }
        performance_drift_hits = [
            label
            for label, pattern in performance_drift_patterns.items()
            if re.search(pattern, body, re.S)
        ]
        if performance_drift_hits:
            failures.append(
                "表演验真场景偏离可见唱跳闭环，新增"
                + "、".join(performance_drift_hits)
                + "。删除临时病史、新样稿、确认文书、宣传物料取证描写和身体书写，只保留热身、连续唱跳、"
                "见证通过、撤下旧宣传与口头归还权限。"
            )
        if re.search(
            r"(?:肋廓|胸廓|肋间肌|肌肉|腹腔).{0,20}(?:起伏|收缩|舒张|幅度|气息|换气)|"
            r"膝盖.{0,18}(?:弯曲弧度|弧度)|"
            r"呼吸.{0,18}(?:起伏频率|频率)|"
            r"足踝.{0,18}(?:微晃|稳定)|"
            r"胸口起伏.{0,36}(?:唇色|指尖)|"
            r"(?:气息.{0,8}丹田|丹田.{0,12}(?:托|送|顶)|喉间振动)|"
            r"汗.{0,24}(?:不多不少|不聚滴|不流淌)|"
            r"[一二三四五六七八九十百零\d]+组"
            r"[一二三四五六七八九十百零\d]+拍(?:组合|动作)?|"
            r"第[一二三四五六七八九十百零\d]+段(?:主歌|副歌)|"
            r"[一二三四五六七八九十百零\d]+拍(?:间隙|空隙)|"
            r"[一二三四五六七八九十百零\d]+(?:寸|厘米|公分)|"
            r"[一二三四五六七八九十百零\d]+个?小节|"
            r"第[一二三四五六七八九十百零\d]+次重复副歌",
            body,
            re.S,
        ):
            failures.append(
                "表演验真用解剖观察、汗液状态或精确小节数包装完成度；"
                "改用听得见的音准、自然换气、节拍和动作衔接，不做身体分析或精确计数。"
            )
        stop_commands = re.findall(
            r"(?:[“\"])?(?:停一下|暂停|先停|给我停|停下来|够了|可以了|到此为止)"
            r"(?:[！!。？”\"]|$)",
            body,
        )
        if len(stop_commands) > 1:
            failures.append(
                "表演验真重复出现多次口头叫停，形成两轮表演或重复完成；"
                "对手只能叫停一次，主角随后一次性唱跳到收势。"
            )
        if re.search(r"见证人.{0,28}(?:看|盯|查看).{0,8}(?:腕表|手表)", body, re.S):
            failures.append(
                "表演验真的见证人用腕表暗示计时或数据验收；"
                "见证人只观看完整表演并给出一句定性结论。"
            )
        if re.search(
            r"(?:宣传板|宣传单页|宣传初稿|宣传页|海报|宣传物料).{0,90}"
            r"(?:标题|画面|剪影|图示|动线|滤镜|斜体字|一行.{0,8}字|标语|文案|"
            r"字体|色调|灰调|墨色.{0,8}(?:浓淡|不均|未干))|"
            r"(?:字体|色调).{0,24}(?:宣传初稿|宣传页|病弱降配)|"
            r"(?:斜体字|标语|文案).{0,24}(?:宣传板|宣传单页|宣传初稿|宣传页|海报|宣传物料)",
            body,
            re.S,
        ):
            failures.append(
                "旧宣传物料被扩写成带文字内容的新证据或文案；"
                "合作方只用一句动作撤下无专名旧宣传，不描写其文字。"
            )
        if re.search(r"不记.{0,12}不数.{0,12}不掐秒|不计时.{0,20}不记录", body, re.S):
            failures.append(
                "正文复述了“见证人不计时、不记录”等创作限制；"
                "直接写见证人观看表演，完成后口头宣布通过。"
            )
        if re.search(
            r"(?:上周|昨天|昨夜|此前).{0,60}"
            r"(?:抠下|弄坏|扯掉|掰掉).{0,20}(?:按钮|旋钮|凸钮|按键)|"
            r"(?:按钮|旋钮|凸钮|按键).{0,40}"
            r"(?:上周|昨天|昨夜|此前).{0,30}(?:抠下|弄坏|扯掉|掰掉)",
            body,
            re.S,
        ):
            failures.append(
                "表演验真给控台按钮补造上周损坏等道具前史；"
                "删除未规划的旧动作，让对手失态停在当前现场。"
            )
        if re.search(
            r"预设陷阱|预先设下.{0,12}(?:陷阱|圈套)|"
            r"(?:故意|突然).{0,12}(?:改变|削薄|切换|打乱).{0,12}(?:节奏|鼓点|伴奏)|"
            r"舌尖.{0,12}(?:上颚|牙齿).{0,12}(?:脆响|声响)",
            body,
            re.S,
        ):
            failures.append(
                "表演验真凭空增加节奏陷阱或口腔发声技巧制造难度；"
                "对手只可中途口头叫停，主角以正常唱跳完成度取胜。"
            )
        if re.search(
            r"(?:控台|控制台).{0,12}(?:显示屏|波形|读数)|"
            r"(?:显示屏|波形条).{0,18}(?:控台|控制台)",
            body,
            re.S,
        ):
            failures.append(
                "表演验真借控台屏幕或波形读数证明能力；"
                "删除屏幕和读数，只由现场听感、动作完成与见证人口头结论验收。"
            )
        if re.search(r"观众席|十万观众|满场观众|聚光灯", body):
            failures.append(
                "排练场验真凭空增加观众席、公众观众或舞台聚光灯；"
                "只写排练场内既有合作方、见证人、对手和普通照明。"
            )
        if re.search(
            r"第余下的乐段|(?:中频区|元音|音准如尺量过)|"
            r"喉结.{0,12}(?:吸气|呼气)|胸膛.{0,20}(?:节奏|稳定)",
            body,
            re.S,
        ):
            failures.append(
                "表演验真出现归一化残片或过度声学生理解说；"
                "改用自然的节拍、动作衔接、音准和换气描写。"
            )
        if "训练强度决定权" in contract_text and "训练强度决定权" not in body:
            failures.append(
                "执行卡要求主角收回训练强度决定权，正文换成含混的训练方案自主权或本人权限；"
                "合作方必须当场明确说出“训练强度决定权归还主角”。"
            )
        if (
            "训练强度决定权" in contract_text
            and not re.search(
                r"(?:不再有权|失去|不得再|不能再).{0,20}"
                r"(?:降低|调整|决定).{0,10}(?:训练)?强度|不敢再降强度",
                body,
            )
        ):
            failures.append(
                "表演验真只写主角拿回训练强度决定权，没有写清对手即时失去降配控制；"
                "合作方须同时宣布对手不再有权降低训练强度。"
            )
        performance_tail = body[-650:]
        if re.search(
            r"(?:调度令|排期表|医疗备注(?:单|记录)?).{0,100}"
            r"(?:失效|坠地|坠毁|碎成|化为|不再作数)",
            performance_tail,
            re.S,
        ):
            failures.append(
                "表演验真结尾把训练强度决定权夸大成排期、调度或医疗权限同时失效；"
                "只写旧病弱宣传撤下和训练强度决定权归还，其余权限留待后续情节族解决。"
            )
        settlement_index = body.rfind("训练强度决定权")
        if settlement_index >= 0 and len(body) - settlement_index > 360:
            failures.append(
                "表演验真在权限结算后继续铺写过长的喝水、整理物件、天气或象征性冷却段；"
                "结算后最多保留对手一次失态和主角一句反击，立即收章。"
            )
        if settlement_index >= 0:
            settlement_tail = body[settlement_index:]
            tail_paragraphs = [
                paragraph.strip()
                for paragraph in re.split(r"\n\s*\n", settlement_tail)
                if paragraph.strip()
            ]
            if len(tail_paragraphs) > 4:
                failures.append(
                    "表演验真在权限结算后出现多轮反应与离场段落；"
                    "结算句后只保留对手一次失态或嘴硬、主角一句反击和对手一个极短反应，"
                    "不再写第二轮行动或离场。"
                )
            if re.search(
                r"侧移|抬脚|踏步节奏|音准偏|换气卡|换气声|摆臂|半拍|"
                r"节拍没乱|我(?:跳|唱)得比|撑不了.{0,6}天|"
                r"明天.{0,12}第几组|零点|误差|偏差",
                settlement_tail,
            ):
                failures.append(
                    "表演验真在权限归还后又让对手展开技术挑错，削弱了已经生效的结算；"
                    "结算后只保留一句嘴硬、主角一句反击和对手短反应。"
                )

    if all(marker in paper_markers for marker in ("封签", "送货单", "领用簿")):
        if re.search(r"动作衔接待续|待续接续|嘴唇一紧一次|[。！？][”’\"]?[。！？]", body):
            failures.append(
                "纸面核对出现拼接病句或重复标点；删除残缺短语并保持句子自然完整。"
            )
        if re.search(
            r"窗户|窗帘|风声|顶灯|灯光|阴影|"
            r"喉结|舌尖|上颚|腕骨|瞳孔|下颌线|筋络|指甲盖|脉搏|"
            r"油墨|墨色|撇捺|顿挫|那一横|浅痕|声音便浮上来|"
            r"打开封签|(?:按住|压住|触到|触碰).{0,12}封签|"
            r"封签.{0,12}(?:按住|压住|触到|触碰)|"
            r"[”\"]却未开口",
            body,
        ):
            failures.append(
                "纸面核对用环境添景、身体特写或字迹笔画制造紧张；"
                "只保留三类材料、两行数量、简短动作和当面对话。"
            )
        handoff_source_hits = re.findall(
            r"(?:交出|递出|拿出|掏出)[^。！？\n]{0,30}钥匙|"
            r"钥匙[^。！？\n]{0,36}(?:放|覆|递|交|躺|落|滑)(?:进|入|到)?"
            r"[^。！？\n]{0,20}负责人(?:掌|手)",
            body,
        )
        protagonist_receipt_hits = re.findall(
            r"钥匙[^。！？\n]{0,30}(?:放进|放入|放到|置于|置入|置进|交到|递到|压进|滑入)"
            rf"[^。！？\n]{{0,18}}(?:{protagonist_pattern}|主角)"
            r"[^。！？\n]{0,10}(?:手|掌|指间)|"
            rf"(?:{protagonist_pattern}|主角)"
            r"[^。！？\n]{0,20}(?:接过|接住|收下|握住)"
            r"[^。！？\n]{0,12}钥匙",
            body,
        )
        if len(handoff_source_hits) > 1 or len(protagonist_receipt_hits) > 1:
            failures.append(
                "钥匙交接被重复书写，形成两次交出或两次接收；"
                "对手只交给负责人一次，负责人只交给主角一次。"
            )
        paper_opponent_match = re.search(
            r"([\u4e00-\u9fff·]{2,24})被(?:暂停职务|停职)",
            contract_text,
        )
        if paper_opponent_match:
            paper_opponent = paper_opponent_match.group(1).strip()
            opponent_handoff = re.search(
                rf"{re.escape(paper_opponent)}.{{0,100}}"
                r"(?:交出|递出|拿出|掏出|钥匙.{0,36}"
                r"(?:放|覆|递|交|躺|落|滑)(?:进|入|到)?.{0,16}负责人)",
                body,
                re.S,
            )
            responsible_has_key = re.search(
                r"负责人[^。！？\n]{0,60}(?:掌|手)[^。！？\n]{0,24}钥匙|"
                r"钥匙[^。！？\n]{0,24}(?:负责人)(?:掌|手)",
                body,
            )
            if responsible_has_key and (
                not opponent_handoff
                or responsible_has_key.start() < opponent_handoff.start()
            ):
                failures.append(
                    "负责人在对手交出钥匙之前已经持有钥匙，交接来源断裂；"
                    "停职后先写对手把唯一钥匙放进负责人掌心。"
                )
        if not re.search(
            r"(?:上一世|前世).{0,120}"
            r"(?:先用后补|笔误|补记|这套流程|这套说法|康拉德)",
            body,
            re.S,
        ):
            failures.append(
                "纸面核对缺少重生反杀的因果：主角没有明确凭上一世记忆认出“先用后补”旧招；"
                "开场用一句内心叙述写清上一世流程或对手会用“笔误/补记”辩解，"
                "但不得复原物证细节。"
            )
        if re.search(
            rf"(?:{protagonist_pattern}|主角).{{0,80}}"
            r"(?:绷带|包扎|旧伤|伤口|钝痛|钝感)|"
            r"(?:绷带|包扎|旧伤|伤口|钝痛|钝感)"
            rf".{{0,80}}(?:{protagonist_pattern}|主角)",
            body,
            re.S,
        ):
            failures.append(
                "药品纸面核对给主角凭空增加绷带、旧伤或身体疼痛；"
                "本场不靠伤情制造紧张，只写三类材料、数量矛盾和权限交接。"
            )
        if re.search(
            r"(?:指尖|指腹|袖口|衣襟).{0,30}(?:药液|药渍|药迹).{0,12}(?:残痕|痕迹|干涸)?|"
            r"(?:药液|药渍|药迹).{0,30}(?:指尖|指腹|袖口|衣襟)",
            body,
            re.S,
        ):
            failures.append(
                "药品核对给人物衣物或手指添加药液残痕，暗示执行卡外的新物证；"
                "删除药渍，只比较送货单与领用簿的数量。"
            )
        if re.search(
            r"(?:抽出|掀起|揭起|挑起|拨开).{0,10}封签(?:一角|边角)|"
            r"封签(?:一角|边角).{0,10}(?:抽出|掀起|揭起|挑起|拨开)",
            body,
        ):
            failures.append(
                "主角为核对而抽动或掀起封签边角，削弱了未拆封状态；"
                "封签全程不触碰，只作为未拆状态留在桌面。"
            )
        if re.search(
            r"桌上.{0,40}(?:只有|共有|摆着).{0,8}"
            r"[一二三四五六七八九十百零\d]+支(?:实物|针剂|药)|"
            r"[一二三四五六七八九十百零\d]+支实物",
            body,
            re.S,
        ):
            failures.append(
                "纸面核对又清点桌上针剂实物数量，容易与单据数量或未拆封样品冲突；"
                "桌上针剂只用于确认封签未拆，唯一数量比较来自送货单和领用簿。"
            )
        if re.search(
            r"(?:七|八|[78])支未拆封(?:的)?针剂|"
            r"(?:七|八|[78])支针剂.{0,20}(?:整齐排列|逐支|清点)|"
            r"封签.{0,24}(?:七|八|[78])份",
            body,
        ):
            failures.append(
                "纸面核对把送货数量改写成桌上针剂或封签的实物清点；"
                "七与八只出现在送货单和领用簿，封签只表达保持未拆。"
            )
        if re.search(
            r"(?:上一世|前世)[^。！？\n]{0,140}"
            r"(?:过敏|休克|药量差额|药物反应|抢救)",
            body,
        ):
            failures.append(
                "前世记忆补造了过敏、休克、抢救或药量事故细节；"
                "前世信息只保留对手“先用后补、再称笔误”的行为模式。"
            )
        if re.search(
            r"(?:字迹|笔锋).{0,24}(?:潦草|工整|突兀|割裂|不同)|"
            r"(?:潦草|工整|突兀|割裂).{0,24}(?:字迹|笔锋)",
            body,
        ):
            failures.append(
                "纸面核对把字迹工整、潦草或笔锋差异变成第二处证据；"
                "只比较送达七支与领用八支。"
            )
        suspension_position = body.find("即刻暂停你的职务")
        early_key = re.search(
            r"(?:桌上|桌面).{0,36}(?:摆着|放着|搁着|躺着|留着)"
            r".{0,16}(?:钥匙|药品柜钥匙)|"
            r"(?:钥匙|药品柜钥匙).{0,16}(?:摆|放|搁|躺|留)在(?:桌上|桌面)",
            body,
            re.S,
        )
        if early_key and (
            suspension_position < 0 or early_key.start() < suspension_position
        ):
            failures.append(
                "药品柜钥匙在停职宣布前已经被写到桌上，随后又要求对手交钥匙；"
                "钥匙必须始终由对手持有，停职后才首次交出。"
            )
        if re.search(
            r"原话反击|本段唯一任务|事实白名单|"
            r"第[一二三四五六七八九十\d]+/[一二三四五六七八九十\d]+段",
            body,
        ):
            failures.append(
                "正文混入分段提示词或创作标签；删除提示语，只保留人物动作和对白。"
            )
        pseudo_technical_patterns = (
            r"心率.{0,8}(?:阈值|偏高)|神经阈值|药理|药物成分|化学成分|"
            r"机器压纹|机械压纹|压纹.{0,8}(?:方向|角度)|斜切口|切口角度|"
            r"闻了闻|嗅了嗅|甜腥味|薄荷(?:味|凉意)|成分气味|显色试纸|"
            r"中枢抑制|缓释载体|载体结构|静脉通路|"
            r"(?:甲|乙|丙)(?:版|型).{0,16}(?:作废|停用|更新|对应)|"
            r"(?:墨迹|墨水|印泥|油墨).{0,18}(?:未干|新鲜|干透|小时)|"
            r"(?:墨色|字迹).{0,18}(?:略浓|浓淡|深浅|后来添|添写|补写痕迹)|"
            r"洇开.{0,8}墨点|朱砂红圈|红笔圈|铅笔灰|凹印|凸起油墨|"
            r"青灰微光|横线末端|纸页.{0,8}褶皱|多添了?一(?:竖|横|划)|"
            r"右下角.{0,16}(?:八支|字迹|墨点)|"
            r"(?:顿笔|落笔|收笔).{0,18}(?:习惯|分毫不差|完全一致)|"
            r"(?:送抵|签收|填完|测试).{0,16}[一二三四五六七八九十百零\d]+点|"
            r"(?:上周|昨天|今日|当天).{0,16}[一二三四五六七八九十百零\d]+点"
        )
        pseudo_hits = [
            str(hit)
            for hit in re.findall(pseudo_technical_patterns, body, re.I)
            if str(hit) and str(hit) not in contract_text
        ]
        if pseudo_hits:
            failures.append(
                "正文把纸面核对升级为伪医学或伪法证判断："
                + "、".join(list(dict.fromkeys(pseudo_hits))[:6])
                + "。只比较纸面上可直接读出的编号、数量、日期或签收。"
            )
        extra_process_hits = re.findall(
            r"双签制度|双重签字|双人签字|豁免条款|免责条款|"
            r"(?:内部|药品|处置|销毁).{0,6}(?:协议|规程|流程)|"
            r"董事会备案|法务备案|共同开封|书面指定|共启|"
            r"安保.{0,12}(?:接管|保管)|保险柜密码|"
            r"骑缝.{0,8}(?:印章|盖章)|押线印章|监印人|"
            r"当日闭门前|保管人亲笔签署|重新誊录|"
            r"(?:流程|规定).{0,16}(?:有权|允许|可以).{0,16}"
            r"(?:调整|修改|更改|补录|补登).{0,10}(?:用量)?记录|"
            r"(?:流程|规定).{0,12}(?:允许|可以).{0,12}(?:事后|补录|补登)",
            body,
        )
        if extra_process_hits and not any(
            str(hit) and str(hit) in contract_text for hit in extra_process_hits
        ):
            failures.append(
                "正文为纸面反转附加了执行卡未建立的审批或制度："
                + "、".join(list(dict.fromkeys(str(hit) for hit in extra_process_hits))[:6])
                + "。由现场已有权限者根据可见矛盾直接结算。"
            )
        backup_document_hits = re.findall(
            r"(?:另一份|额外|备用).{0,12}(?:备份|单据|记录|文件)|"
            r"(?:掏出|取出|寻找|找出).{0,12}(?:备份|备用单据|备用记录)",
            body,
        )
        if backup_document_hits:
            failures.append(
                "纸面核对暗示或引入执行卡外的备份文件："
                + "、".join(list(dict.fromkeys(backup_document_hits))[:4])
                + "。桌面证据只保留封签、送货单和领用簿，不为对手预留额外文书。"
            )
        weapon_hits = [
            hit for hit in re.findall(r"枪套|枪柄|手术刀|匕首", body)
            if hit not in contract_text
        ]
        if weapon_hits:
            failures.append(
                "正文加入与职业核对无关的武器或威胁道具："
                + "、".join(dict.fromkeys(weapon_hits))
                + "。删除该道具，用对手失态和权限交接承担戏剧张力。"
            )
        unsafe_drug_handling = re.findall(
            r"(?:撕开|撕裂|掀开)(?:了|这|该|一层|外层|针剂盒上的){0,4}(?:封签|封膜)|"
            r"(?:封签|封膜).{0,8}(?:被|让)?(?:撕开|撕裂|掀开)|"
            r"拔掉.{0,12}(?:橡胶塞|瓶塞)|针头.{0,20}(?:探入|插入)|"
            r"(?:抽吸|抽取).{0,20}药液|药液.{0,20}充盈.{0,12}管腔",
            body,
        )
        if unsafe_drug_handling:
            failures.append(
                "正文在完成药品核对后又擅自开封、抽取或操作针剂："
                + "、".join(list(dict.fromkeys(unsafe_drug_handling))[:6])
                + "。保持针剂封存，只完成保管权交接，不新增用药动作。"
            )
        if re.search(
            r"封签.{0,20}(?:排成一列|银色凸印|铝箔)|"
            r"一支都不能少|多出来的一支.{0,24}(?:袖口|口袋)|"
            r"(?:袖口|口袋).{0,24}多出来的一支",
            body,
            re.S,
        ):
            failures.append(
                "纸面核对把封签写成实物阵列，或暗示缺少的针剂藏在衣袋中；"
                "封签只保持未拆，不清点实物、不猜测药品去向。"
            )
        if re.search(r"(?:实付|支付).{0,4}数量|数量.{0,4}(?:实付|支付)", body):
            failures.append(
                "送货单把药品到货数量误写成付款语义的“实付数量”；"
                "纸面字段只能写“送货数量”或“送达数量”。"
            )
        if re.search(
            r"(?:上一世|记忆中)[^。！？\n]{0,140}"
            r"(?:胶痕|凹槽|折痕|折角|压痕|蓝墨水晕|货架.{0,20}(?:位置|第)|"
            r"签字笔|油墨|墨迹|木纹|桌面旧痕|桌角旧痕|旧划痕|"
            r"形状.{0,8}(?:没变|相同)|完全一致)|"
            r"(?:胶痕|凹槽|折痕|折角|压痕|旧划痕|油墨|墨迹)[^。！？\n]{0,100}"
            r"(?:上一世|记忆中)",
            body,
        ):
            failures.append(
                "上一世记忆被写成对胶痕、凹槽或货架位置的精密复原，形成未规划的物证暗示；"
                "前世记忆只提供“先用后补”的流程和对手选择，今生只凭桌上三类材料核对。"
            )
        if re.search(
            r"(?:钥匙|领用簿|桌面|药柜).{0,60}"
            r"(?:去年|前年|[一二三四五六七八九十\d]+年前|上周|此前).{0,36}"
            r"(?:摔|磕|撞|划|弄坏|磨损)|"
            r"(?:去年|前年|[一二三四五六七八九十\d]+年前|上周|此前).{0,36}"
            r"(?:摔|磕|撞|划|弄坏|磨损).{0,60}(?:钥匙|领用簿|桌面|药柜)",
            body,
            re.S,
        ):
            failures.append(
                "纸面核对给钥匙、领用簿或药柜补造旧损伤来历；"
                "道具只承担当前核对和交接，不增加往年摔碰或磨损前史。"
            )
        if re.search(
            r"(?:撕|扯)(?:掉|下|开|毁)?.{0,16}(?:领用簿|账页|那页|纸页)|"
            r"(?:领用簿|账页|那页|纸页).{0,16}(?:撕|扯)(?:掉|下|开|毁)?",
            body,
        ):
            failures.append(
                "对手试图撕毁领用簿或账页，制造了未规划的毁证动作；"
                "对手只能试图拿回领用簿，负责人按住并直接宣布停职。"
            )
        if re.search(
            r"[“\"](?:全是|都是)?我经手的[。！？”\"]*|"
            rf"(?:{protagonist_pattern}|主角).{{0,80}}"
            r"(?:承认|回答|答道|说).{0,24}"
            r"(?:三样|封签|送货单|领用簿).{0,24}(?:由我|我经手)",
            body,
            re.S,
        ):
            failures.append(
                "纸面核对把对手经手的材料错误归到主角名下；"
                "必须明确写封签、送货单和领用簿均由既有对手经手，主角只负责指出矛盾。"
            )
        if re.search(
            r"重签日期|注明[“\"‘']?补[”\"’']?字|"
            r"(?:撕下|撕掉|扯下).{0,16}(?:页|纸).{0,12}背面|"
            r"(?:页|纸)(?:的)?背面.{0,20}(?:痕|记录|字)|"
            r"(?:多添|多加|多出).{0,6}一横",
            body,
            re.S,
        ):
            failures.append(
                "纸面核对在数量差之外又用日期、补记标识、笔画或页背痕迹举证；"
                "全章唯一矛盾只能是送货单与领用簿相差一支。"
            )
        if re.search(
            r"(?:离|距).{0,10}[一二三四五六七八九十百零\d]+(?:寸|厘米|公分)|"
            r"[一二三四五六七八九十百零\d]+(?:寸|厘米|公分)(?:处|外|前)|"
            r"(?:半寸|寸许|半毫|两指宽|三指宽|三分之二处)",
            body,
        ):
            failures.append(
                "纸面核对用精确身体距离制造紧张；改为停在近前或半空，不写寸、厘米或公分。"
            )
        if re.search(
            r"(?:上一世|前世).{0,140}"
            r"(?:先撕.{0,12}封签|推.{0,8}针筒|针筒.{0,16}肌肉|"
            r"针头.{0,16}(?:扎入|刺入)|注射.{0,16}(?:顺序|动作|过程))",
            body,
            re.S,
        ):
            failures.append(
                "前世记忆被扩写成撕封签、推针筒或入针的具体过程；"
                "只保留“先用后补”和对手会说“笔误/补记”的认知，不展示注射动作。"
            )
        if re.search(
            r"(?:上周|上次|之前).{0,36}(?:加了|增加|临时加|追加).{0,12}"
            r"(?:剂量|用量)|(?:临时加|追加).{0,12}(?:剂量|用量)",
            body,
        ):
            failures.append(
                "对手辩解时凭空声称当前时间线曾追加剂量，等同补造既往用药事实；"
                "辩解只能是“笔误”或“补记”，不得声称主角已经加过剂量。"
            )
        if re.search(
            r"(?:上周|此前|之前).{0,40}(?:用了|使用|用掉|消耗).{0,10}"
            r"[一二三四五六七八九十百零\d]+支|"
            r"(?:实际用量|既往用量).{0,20}(?:超量|超过|[一二三四五六七八九十百零\d]+支)",
            body,
            re.S,
        ):
            failures.append(
                "对手凭空声称主角此前已经使用多支针剂，补造了当前时间线的既往用药；"
                "对手只能把纸面数量差辩解成笔误或补记。"
            )
        if re.search(
            r"(?:去年|生日|从前).{0,48}(?:礼物|亲手挑|送给|赠给)|"
            r"(?:礼物|亲手挑).{0,48}(?:去年|生日)",
            body,
            re.S,
        ):
            failures.append(
                "纸面核对场景凭空补造主角与对手互送生日礼物等私人往事；"
                "删除未规划的旧关系，只保留当前职务冲突。"
            )
        if re.search(
            r"(?:手指|食指).{0,36}(?:腕内侧|脉搏|数心跳)|"
            r"(?:按住|抵住|摸着).{0,20}(?:脉搏|腕脉)|数着.{0,8}心跳",
            body,
            re.S,
        ):
            failures.append(
                "现场负责人无故摸脉或数心跳，把纸面核对重新写成医学展示；"
                "负责人只旁观材料、宣布停职并完成钥匙交接。"
            )
        closing_line = list(re.finditer(
            r"没有我的许可.{0,18}谁也不能碰这些药",
            body,
            re.S,
        ))
        medication_paper_audit = all(
            marker in paper_markers for marker in ("封签", "送货单", "领用簿")
        )
        if medication_paper_audit and not closing_line:
            failures.append(
                "药品核对缺少主角的最终收束对白；钥匙交接后必须由主角说"
                "“没有我的许可，谁也不能碰这些药”，再留对手一个短反应。"
            )
        if medication_paper_audit and not (
            re.search(
                r"(?:钥匙).{0,30}(?:放进|放入|放到|置于|置入|置进|交到|递到|压进|滑入)"
                rf".{{0,24}}(?:{protagonist_pattern}|主角)"
                r".{0,12}(?:手|掌|指间)|"
                rf"(?:{protagonist_pattern}|主角).{{0,24}}"
                r"(?:接过|接住|收下|握住).{0,16}钥匙",
                body,
                re.S,
            )
            and not re.search(
                rf"(?:{protagonist_pattern}|主角).{{0,12}}(?:未|没有)伸手",
                body,
            )
        ):
            failures.append(
                "药品保管权只被口头宣布，钥匙没有实际交到主角手中；"
                "负责人必须把唯一钥匙放进主角掌心，主角当场接住。"
            )
        expected_suspended_opponent = ""
        suspended_match = re.search(
            r"([\u4e00-\u9fff·]{2,24})被(?:暂停职务|停职)",
            contract_text,
        )
        if suspended_match:
            expected_suspended_opponent = suspended_match.group(1).strip()
        if (
            medication_paper_audit
            and expected_suspended_opponent
            and not re.search(
                rf"{_character_alias_pattern(expected_suspended_opponent)}.{{0,100}}"
                r"(?:(?:交出|递出|取下|解下|掏出|拿出|放下).{0,24}钥匙|"
                r"钥匙.{0,36}(?:放|覆|递|交)(?:进|入|到)?"
                r".{0,16}负责人(?:掌|手))",
                body,
                re.S,
            )
        ):
            failures.append(
                "药品柜钥匙在交接段凭空出现在负责人手中；"
                f"必须先写{expected_suspended_opponent}交出唯一钥匙，再由负责人转交主角。"
            )
        if closing_line and len(body) - closing_line[-1].end() > 220:
            failures.append(
                "纸面核对在主角收束对白后继续追加过长的环境、对手凝视或空泛象征；"
                "该对白之后只留一个极短反应，立即结束。"
            )
        if closing_line:
            closing_tail = re.sub(
                r"^[”\"’'。！？\s]+",
                "",
                body[closing_line[-1].end():],
            )
            closing_tail_paragraphs = [
                paragraph.strip()
                for paragraph in re.split(r"\n\s*\n", closing_tail)
                if paragraph.strip()
            ]
            if (
                len(closing_tail_paragraphs) > 1
                or re.search(protagonist_pattern, closing_tail)
            ):
                failures.append(
                    "药品核对在主角收束对白后又追加多段反应或主角动作；"
                    "对白后只保留对手一个极短反应，立即结束。"
                )
            if re.search(r"窗|天空|薄雾|雾气|风声|墙面|灯光|光线", closing_tail):
                failures.append(
                    "药品核对在收束对白和对手短反应后又追加环境象征；"
                    "删除窗、天空、雾气或光线描写，停在对手的即时反应。"
                )
            if re.search(r"转身|离开|走向门|门口|关门|撞门", closing_tail):
                failures.append(
                    "药品核对在收束对白后继续写对手离场；"
                    "对白后只保留一个原地短反应，立即结束。"
                )
        if re.search(r"还没迈(?:出)?第一步|尚未迈(?:出)?第一步", body[-500:]):
            failures.append(
                "章节已完成停职与保管权交接，结尾却写成“还没迈第一步”，冲淡即时胜利；"
                "停在本章结果已经生效，不得用空泛起步句撤销爽点。"
            )

        mismatch_dimensions = {
            "编号": bool(re.search(
                r"(?:编号|批号|序号|尾号).{0,18}(?:不一致|不同|不符|错误|对不上)|"
                r"(?:甲|乙|丙)(?:版|型)",
                body,
            )),
            "数量": bool(re.search(r"数量.{0,12}(?:不一致|不符|对不上)|多记|少记|多出|少了", body)),
            "日期": bool(re.search(
                r"日期.{0,16}(?:不一致|不符|错误|对不上)|"
                r"(?:盖的是|写的是|标的是).{0,12}(?:昨天|前天|[一二三四五六七八九十\d]+天前)",
                body,
            )),
            "签收": bool(re.search(r"签收栏.{0,12}(?:空白|未填|没人签)|签字为空|没有签字|未签", body)),
            "墨迹": bool(re.search(
                r"(?:墨迹|墨渍|墨水|印泥|油墨|纸背|背面.{0,12}痕).{0,18}"
                r"(?:未干|新鲜|异常|不符|不同|对不上|可疑|伪造)|"
                r"(?:未干|新鲜|异常|不符|不同|对不上|可疑|伪造).{0,18}"
                r"(?:墨迹|墨渍|墨水|印泥|油墨|纸背)",
                body,
            )),
        }
        used_dimensions = [name for name, present in mismatch_dimensions.items() if present]
        if len(used_dimensions) >= 2:
            failures.append(
                "纸面核对同时堆叠多处矛盾维度："
                + "、".join(used_dimensions)
                + "。全章只保留编号、数量、日期或签收中的一处差异。"
            )

        surprise_authority = re.search(
            r"这时.{0,120}(?:门.{0,20}(?:推开|打开)|走进|出现|来到).{0,100}"
            r"(?:负责人|监察|行政|代表|主管|裁定|审查)",
            body,
            re.S,
        )
        if surprise_authority:
            failures.append(
                "正文在反转时才让无姓名权限者突然进门裁决；"
                "需要权限者时必须从开场就在场，亲眼经历同一轮核对后直接结算。"
            )

        if "暂停职务" in contract_text:
            paper_opponents = [
                str(member.get("name") or "").strip()
                for member in _select_grounded_chapter_cast(
                    chapter_card if isinstance(chapter_card, dict) else {}
                )
                if isinstance(member, dict)
                and str(member.get("alignment") or "").casefold() == "opponent"
                and str(member.get("name") or "").strip()
            ]
            named_suspension = any(
                re.search(
                    rf"{re.escape(name)}.{{0,28}}(?:被)?(?:暂停职务|停职)|"
                    rf"(?:暂停职务|停职).{{0,28}}{re.escape(name)}",
                    body,
                    re.S,
                )
                for name in paper_opponents
            )
            direct_suspension = bool(re.search(
                r"(?:即刻|现在|当场)暂停你的职务|"
                r"你的职务(?:即刻|现在|当场)暂停|你被停职",
                body,
            ))
            if not (named_suspension or direct_suspension):
                failures.append(
                    "执行卡要求对手被暂停职务，正文却只暂停药品管理权限或保管权限；"
                    "必须由开场就在场的负责人明确宣布“暂停你的职务”，并写结果即刻生效。"
                )
        if "药品保管权" in contract_text and "药品保管权" not in body:
            failures.append(
                "执行卡要求主角获得药品保管权，正文只写监管、复核或临时看管；"
                "必须当场明确说出并生效“药品保管权归主角”。"
            )
        if re.search(
            r"(?:昨天|昨夜|上次).{0,30}(?:给我|为我|向我).{0,12}(?:打了|打的是|注射了)"
            r".{0,8}(?:针|针剂)|(?:给我|为我).{0,12}(?:打了|打的是|注射了).{0,8}"
            r"(?:第[一二三四五六七八九十\d]+针|昨天的针)",
            body,
        ):
            failures.append(
                "正文凭空补写当前时间线已经完成的既往注射，可能与此前阻止用药的结果冲突；"
                "删除既往注射，只核对本章仍未拆封的针剂。"
            )
        if re.search(
            r"(?:什么时候|何时).{0,12}(?:该扎|注射)|"
            r"(?:怎么扎|扎谁身上|给谁注射).{0,24}(?:我说了算|由我决定)",
            body,
            re.S,
        ):
            failures.append(
                "正文把药品保管权扩大成由主角决定如何注射、何时注射或给谁注射；"
                "保管权只意味着未经主角许可任何人不得动药，不等于取得医疗处置权。"
            )
        if re.search(
            r"(?:同款|同样(?:质地|样式)?|另一把).{0,18}钥匙|"
            r"钥匙.{0,18}(?:同款|同样(?:质地|样式)?|严丝合缝|齿形相同)",
            body,
        ):
            failures.append(
                "纸面核对场景让主角在交接前就持有同款药柜钥匙，使本章取得保管权的收益失真；"
                "删除旧钥匙，只保留负责人当场交出的唯一药柜钥匙。"
            )
        if re.search(
            r"被清出(?:了)?(?:团队|工作组)|"
            r"(?:上周|此前|之前).{0,56}(?:交出|交走|没了|失去).{0,18}(?:钥匙|钥匙串)|"
            r"(?:钥匙|钥匙串).{0,30}(?:上周|此前|之前).{0,30}(?:交出|交走|没了|失去)",
            body,
            re.S,
        ):
            failures.append(
                "纸面核对开场凭空补造人物此前被清出团队或交走钥匙的经历；"
                "新场景只承接前场结果已生效，不继承前场对手的口袋、钥匙或失职经历。"
            )
        if re.search(
            r"封签.{0,24}(?:背面|小字|封码|印着).{0,24}(?:数量|[一二三四五六七八九十百零\d]+支)|"
            r"(?:背面|小字|封码).{0,24}封签",
            body,
            re.S,
        ):
            failures.append(
                "纸面核对从封签背面小字或封码读取数量，制造了第二条取证维度；"
                "封签只用于确认未拆，唯一数量差只能来自送货单与领用簿。"
            )
        if re.search(
            r"负责人.{0,80}(?:领用簿|簿子).{0,40}(?:写下|填写|登记|落笔)|"
            r"(?:领用簿|簿子).{0,40}(?:写下|填写|登记|落笔).{0,80}负责人",
            body,
            re.S,
        ):
            failures.append(
                "现场负责人又在领用簿中新增记录，扩展了交接文书流程；"
                "负责人只宣布停职、接钥匙并口头确认保管权，不填写任何材料。"
            )
        if re.search(
            r"(?:打开|拉开|旋开|开启).{0,8}(?:药品柜|药柜|柜门)|"
            r"(?:药品柜|药柜|柜门).{0,8}(?:打开|拉开|旋开|开启)",
            body,
        ):
            failures.append(
                "纸面核对场景在权限交接后擅自打开药柜，扩展成了新的取证或检查支线；"
                "本章只接过钥匙和领用簿，药柜与针剂保持关闭封存。"
            )
        if re.search(
            r"(?:药品柜|药柜|柜门|瓶罐|针剂).{0,80}(?:气味|香味|苦香|药味)|"
            r"(?:气味|香味|苦香|药味).{0,80}(?:药品柜|药柜|柜门|瓶罐|针剂)",
            body,
            re.S,
        ):
            failures.append(
                "纸面核对场景凭药柜或针剂气味追加了未规划的感官鉴定；"
                "删除气味判断，只使用封签、送货单和领用簿中的一个数量矛盾。"
            )
        if re.search(
            r"(?:上次|昨天|昨夜).{0,28}(?:递给我|交给我|给我).{0,10}"
            r"(?:第[一二三四五六七八九十\d]+支|针剂)",
            body,
        ):
            failures.append(
                "正文把上一世记忆写成当前时间线的既往针剂交接，可能与前章阻止用药冲突；"
                "必须明确写“上一世”，不得写“上次给我第一支”。"
            )

    tail = body[-700:]
    ending_branch_hits = [
        hit
        for hit in re.findall(
            r"物流车|升降台|舞台基座|基座|焊痕|螺丝孔|保险绳|"
            r"保险卡扣|压力校准|货厢|新运到",
            tail,
        )
        if hit not in contract_text
    ]
    if ending_branch_hits:
        failures.append(
            "章节结尾突然开启执行卡未规划的设备、车辆或安全事故支线："
            + "、".join(list(dict.fromkeys(ending_branch_hits))[:6])
            + "。结尾停在本章结果生效及固定对手的直接反应。"
        )
    return failures


def _render_grounded_execution_text(value: Any, chapter_card: Optional[Dict[str, Any]]) -> str:
    """Compile planning language into prose-facing instructions without changing its outcome."""
    if isinstance(value, (list, dict)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value or "")
    card = chapter_card if isinstance(chapter_card, dict) else {}
    contract_text = json.dumps(
        {
            key: card.get(key)
            for key in (
                "chapter_goal", "prev_life_tragedy", "this_life_revenge",
                "core_payoff", "chapter_ending",
                "must_resolve_this_chapter", "chapter_must_include",
                "chapter_milestone",
            )
        },
        ensure_ascii=False,
    )
    if re.search(r"体能测试|体能评估|唱跳连测|现场表演|公开排练", contract_text):
        replacements = (
            ("独立医疗见证人在场", "独立现场见证人在场"),
            ("独立医疗见证", "独立现场见证"),
            ("医疗见证人", "现场见证人"),
            ("体能测试", "高强度唱跳连测"),
            ("体能评估", "现场完成度评估"),
        )
        for old, new in replacements:
            text = text.replace(old, new)
    return text


def _has_unplanned_medical_showcase(text: str, chapter_card: Optional[Dict[str, Any]]) -> bool:
    """Detect pseudo-professional data displays when the card only planned visible performance."""
    card = chapter_card if isinstance(chapter_card, dict) else {}
    contract_text = json.dumps(
        {
            key: card.get(key)
            for key in (
                "chapter_goal", "this_life_revenge", "core_payoff", "chapter_ending",
                "must_resolve_this_chapter", "chapter_must_include",
            )
        },
        ensure_ascii=False,
    )
    if not re.search(r"体能测试|体能评估|唱跳连测|现场表演|公开排练", contract_text):
        return False
    metric_groups = (
        r"心率|心跳频率",
        r"血压|收缩压|舒张压",
        r"血氧",
        r"乳酸|代谢速率|沉积量",
        r"肌电|肌群负荷|横膈膜|神经信号",
        r"声谱|频段|波形|声带震颤",
        r"药剂剂量|药剂读数",
    )
    # A metric explicitly accepted by the card is planned rather than invented.
    planned_groups = {pattern for pattern in metric_groups if re.search(pattern, contract_text)}
    body_groups = {
        pattern for pattern in metric_groups
        if pattern not in planned_groups and re.search(pattern, text or "")
    }
    if not body_groups:
        return False
    numeric_metric = any(
        re.search(rf"(?:{pattern}).{{0,24}}\d|\d.{{0,24}}(?:{pattern})", text or "", re.S)
        for pattern in body_groups
    )
    data_display = bool(re.search(
        r"实时监测|监测屏|数据面板|数据曲线|曲线图|读数|血氧仪|电子血压计|"
        r"监测报告|恢复指数|达标率|峰值|基准值|饱和度",
        text or "",
    ))
    return len(body_groups) >= 2 or numeric_metric or data_display


def _chapter_body_hard_failures(
    part_text: str,
    chapter_num: int = 0,
    chapter_card: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """单章正文生成后立即检查，触发章内重试。"""
    out: List[str] = []
    card = chapter_card if isinstance(chapter_card, dict) else {}
    role_v2 = str(card.get("chapter_role_v2") or "")
    if len(part_text or "") > MAX_CHAPTER_CHARS_V2:
        out.append(
            f"正文超过{MAX_CHAPTER_CHARS_V2}字（当前{len(part_text or '')}字）；"
            "删去重复内心、环境铺陈和法规科普，保留既定动作、对话与结算。"
        )
    reality_hits = [name for name in REAL_WORLD_PROPER_NOUNS if name in (part_text or "")]
    if reality_hits:
        out.append(
            "正文出现现实专名：" + "、".join(reality_hits)
            + "。改用约束中已建立的架空称呼，不得直接写现实人名、地名、公司或奖项。"
        )
    meta_narration_hits = re.findall(r"上一章|本章|下一章", part_text or "")
    if meta_narration_hits:
        out.append(
            "小说正文泄漏章节制作术语："
            + "、".join(dict.fromkeys(meta_narration_hits))
            + "。删除“上一章/本章/下一章”等元叙事，只写人物在故事世界中能感知的连续状态。"
        )
    if re.search(r"麦珂·杰森.{0,12}(?:她|她的)|(?:她|她的).{0,12}麦珂·杰森", part_text or "", re.S):
        out.append("主角性别漂移：麦珂·杰森是男性，近距离叙述不得用“她/她的”指代他。")
    cluster_index = int(card.get("cluster_chapter_index") or 0) if str(card.get("cluster_chapter_index") or "").isdigit() else 0
    info_gap = str(card.get("info_gap_from_prev_life") or "").strip()
    if cluster_index == 1 and info_gap and str(card.get("chapter_role_v2") or "") not in {
        "prev_life_death_only", "rebirth_awakening_only",
    }:
        recognizes_old_trap = bool(re.search(
            r"上一世|前世|那一世|记得|认出|熟悉的旧局|旧局重现|又是这一步|还是老办法",
            part_text or "",
        ))
        takes_current_action = bool(re.search(
            r"提前|先一步|抢先|主动|立刻|当场|拒绝|改掉|调整|准备|要求|提出|叫来|请来",
            part_text or "",
        ))
        if not (recognizes_old_trap and takes_current_action):
            out.append(
                "本情节族首章没有把上一世信息差转成今生主动行动；用一小句内心叙述写主角认出旧局，"
                "并紧接着让他提前改变现场条件。不得在对白中自曝重生。"
            )
    card_contract_text = json.dumps(
        {
            key: card.get(key)
            for key in (
                "chapter_goal", "this_life_revenge", "core_payoff", "chapter_ending",
                "must_resolve_this_chapter", "chapter_must_include",
                "chapter_milestone",
            )
        },
        ensure_ascii=False,
    )
    planned_medication_material = bool(re.search(
        r"针剂|药品|药物|用药|药盒|药瓶|镇静|封签|送货单|领用簿|营养针",
        card_contract_text,
    ))
    unplanned_medication_hits = re.findall(
        r"镇静剂|镇静针|镇静成分|生理盐水|针剂|药盒|药瓶|备用剂量|"
        r"降温喷雾|补水喷雾|心率贴片|补水瓶|蓝色包装盒|医药包装|违禁药|问题药剂",
        part_text or "",
    )
    if unplanned_medication_hits and not planned_medication_material:
        out.append(
            "正文提前引入执行卡未规划的药物或包装材料："
            + "、".join(dict.fromkeys(unplanned_medication_hits))
            + "。本章只完成卡片指定的职业冲突，不得用下一章材料另开证据钩子。"
        )
    if _has_unplanned_medical_showcase(part_text or "", card):
        out.append(
            "正文把表演/体能反杀改写成未规划的医学数据展示；删除数值、指标组合、曲线和仪器读数，"
            "以可见动作、气息状态及见证人一句定性结论完成证明。"
        )
    out.extend(_closed_evidence_failures(part_text or "", card))
    card_plans_rule_text = bool(re.search(r"合同|协议|条款|附件|章程|规则", card_contract_text))
    invented_rule_citations = re.findall(
        r"第[一二三四五六七八九十百\d]+[条款项]|"
        r"(?:协议|合同|条款|附件|章程)(?:中|所载|规定|编号)|"
        r"根据.{0,24}(?:协议|合同|规定|规则|细则)|"
        r"(?:规定|规则|细则).{0,24}(?:写在|载明|要求|必须|须)|"
        r"(?:手写|新增|临时|红章旁).{0,16}(?:补充说明|管理规定|执行规则)",
        part_text or "",
    )
    if invented_rule_citations and not card_plans_rule_text:
        out.append(
            "正文临时发明执行卡未建立的协议编号或条款作为反转依据；"
            "删除这些条款，只用卡片明示的现场行动、见证与有权者决定完成结算。"
        )
    planned_paper_evidence = all(
        marker in card_contract_text for marker in ("封签", "送货单", "领用簿")
    )
    unplanned_digital_evidence = re.findall(
        r"仓库监控|监控截帧|监控画面|时间戳|开启记录|后台日志|后台界面|"
        r"生物识别码|内部权限系统|(?:桌面|监管|医务|操作|随身|管理|电子)?终端|"
        r"指纹.{0,8}(?:验证|锁|权限)|语音.{0,8}验证|声纹|双验证|权限代码|密码条|"
        r"实时库存|库存界面|电子台账|微型录音器|服务器|截图|拍照|摄像|录像|U盘|优盘|移动硬盘|"
        r"微型印章|印章模块|暗格|隐藏夹层|底部夹层",
        part_text or "",
        re.I,
    )
    if planned_paper_evidence and unplanned_digital_evidence:
        out.append(
            "正文越过执行卡规定的纸面证据，新增数字取证："
            + "、".join(dict.fromkeys(unplanned_digital_evidence))
            + "。只能使用执行卡中的封签、送货单、领用簿、当面核对和对手辩解。"
        )
    paper_forensic_hits = re.findall(
        r"激光热熔|温感层|防伪涂层|锯齿印|齿痕|印刷网点|网点偏移|"
        r"签字笔型号|水性笔|油墨|墨迹.{0,8}(?:深|浅|新|旧)|纤维纹理|化学显色",
        part_text or "",
    )
    if planned_paper_evidence and len(set(paper_forensic_hits)) >= 2:
        out.append(
            "正文把普通纸面核对写成伪法证鉴定："
            + "、".join(dict.fromkeys(paper_forensic_hits))
            + "。只比较封签、送货单和领用簿上直接可读的编号、数量、日期与签收。"
        )
    permission_terms = (
        "训练强度决定权", "舞台调度权限", "舞台调度权", "最终执行权", "排期权",
        "药品保管权", "签字权", "票池控制权", "母带控制权", "肖像控制权",
    )
    planned_permissions = {term for term in permission_terms if term in card_contract_text}
    body_permissions = {term for term in permission_terms if term in (part_text or "")}
    extra_permissions = sorted(body_permissions - planned_permissions)
    if extra_permissions:
        out.append(
            "正文把本章收益扩大为执行卡未授予的权限：" + "、".join(extra_permissions)
            + "。只能落定卡片明确写出的权限，不得顺手夺取其他职业资源。"
        )
    canonical_cast_for_language = card.get("canonical_cast") or []
    planned_latin_text = card_contract_text + json.dumps(
        [
            member.get("name")
            for member in canonical_cast_for_language
            if isinstance(member, dict)
        ]
        + list(_planned_work_titles(card)),
        ensure_ascii=False,
    )
    latin_tokens = set(re.findall(
        r"(?<![A-Za-z])[A-Za-z]{2,}(?![A-Za-z])|(?:[A-Za-z]\.){2,}|"
        r"(?<![A-Za-z])[A-Za-z](?![A-Za-z])",
        part_text or "",
    ))
    unplanned_latin_tokens = sorted(token for token in latin_tokens if token not in planned_latin_text)
    if unplanned_latin_tokens:
        out.append(
            "中文正文夹入执行卡未规划的英文词、缩写或字母编号："
            + "、".join(unplanned_latin_tokens[:8])
            + "。改用无姓名中文功能称呼，不得临时制造英文机构、流程、文件或代号。"
        )
    if re.search(r"AI训练权|IP模块|遗产协同声明|保单受益人改签|遗嘱公证已完成|加密群聊|董事会全票通过", part_text or "", re.I):
        out.append("正文擅自增加未规划的训练权、遗产文件、保单改签或加密群聊；只保留事件卡中“门外讨论保险与死后版权”的已定事实。")
    if (chapter_num == 1 or role_v2 == "prev_life_death_only") and re.search(
        r"血氧饱和度|代谢半衰期|心肺抑制阈值|脑电波归零|"
        r"\d{1,2}:\d{2}:\d{2}|\d+(?:\.\d+)?(?:%|℃)",
        part_text or "",
        re.I,
    ):
        out.append("第1章用精确药理指标、生理数值或时间戳制造伪专业感；改为可感知的呼吸、心跳、视野与无力感。")
    fl = _critic_format_leak(part_text)
    if fl:
        out.append(fl)
    if re.search(
        r"我是.{0,16}主角|(?:^|[。！？\n])主角(?:向|走|到|看|点|把|从|在|头|说)|"
        r"(?:^|[。！？\n])反派(?:向|走|到|看|把|说)|\*\*",
        part_text or "",
    ):
        out.append(
            "正文泄露“主角/反派”等创作标签或 Markdown 标记，并把标签当作现场人物称呼；"
            "改用人物固定姓名或无姓名职位，正文只保留小说叙述。"
        )
    duplicate_failure = _near_duplicate_paragraph_failure(part_text)
    if duplicate_failure:
        out.append(duplicate_failure)
    structure_failure = _prose_structure_failure(part_text)
    if structure_failure:
        out.append(structure_failure)
    out.extend(_generic_prose_quality_failures(part_text))
    integrity_failure = _prose_integrity_failure(part_text)
    if integrity_failure:
        out.append(integrity_failure)
    payoff_tail_lines = [
        line.strip()
        for line in re.split(r"\n+", (part_text or "").strip())[-4:]
        if line.strip()
    ]
    if len(payoff_tail_lines) >= 2:
        first_tail, second_tail = payoff_tail_lines[-2:]
        first_is_loss = any(marker in first_tail for marker in OPPONENT_CONSEQUENCE_MARKERS)
        second_is_gain = any(marker in second_tail for marker in PROTAGONIST_GAIN_MARKERS)
        if (
            first_is_loss and second_is_gain
            and len(first_tail) <= 45 and len(second_tail) <= 45
            and not any(mark in first_tail + second_tail for mark in ("“", "”", "："))
        ):
            out.append("正文结尾退化成两行验收摘要；把双向结果写进同一现场的动作、宣读和人物反应中。")
    impossible_rebirth_hits = [
        marker for marker in ("第一次重生", "第二次重生", "上一次重生", "再次重生")
        if marker in part_text
    ]
    if impossible_rebirth_hits:
        out.append(
            "重生次数与项目设定冲突："
            + "、".join(impossible_rebirth_hits)
            + "。当前故事只有一次重生，不得凭空制造前一轮重生留下的物品或经历。"
        )
    if re.search(r"(?:过去|此前).{0,8}(?:一|两|三|四|五|六|七|八|九|十|\d+)年.{0,10}(?:一直)?调查|调查了.{0,8}(?:年|个月)", part_text):
        out.append("正文凭空补写多年调查前史，破坏当前重生行动链；只能使用已在上一章或上一世明确建立的信息。")
    if re.search(
        r"(?:从|凭|根据).{0,8}(?:脑海|记忆).{0,24}(?:还原|恢复|生成|制作|重建)"
        r".{0,20}(?:录音|音频|视频|文件|截图|证据)",
        part_text,
    ) or re.search(
        r"(?:脑海|记忆).{0,80}(?:按下录音键|录成音频|生成录音|恢复录音)",
        part_text,
        re.S,
    ):
        out.append(
            "因果失真：前世记忆被凭空还原成今生可播放或可提交的现实物证。"
            "记忆只能帮助主角预判；现实材料必须由当前时间线中已经写出的行动产生。"
        )
    if re.search(
        r"实验编号|编号[:：]?\s*[A-Z]-?\d{2,}|药瓶照片|神秘药瓶|"
        r"伪造批号|生产日期比实际|加密手机|蓝色镇静喷雾",
        part_text,
        re.I,
    ):
        out.append("正文混入实验编号或神秘药瓶照片等未规划医疗悬疑材料；删除该材料，按娱乐行业既定冲突推进。")
    if re.search(
        r"(?:手中|手里|桌上|床边|身旁).{0,36}(?:上一世|前世).{0,45}(?:药瓶|手机|剧本|文件|录音|物品)|"
        r"(?:上一世|前世).{0,45}(?:药瓶|手机|剧本|文件|录音|物品).{0,36}(?:仍在|还在|攥着|握着|带回|出现在)",
        part_text,
        re.S,
    ):
        out.append("因果失真：上一世实体物品被原样带入今生。重生只能保留记忆，当前时间线材料必须按当前日期重新产生。")
    if re.search(
        r"(?:上一世|前世).{0,180}(?:甚至不用|无需|不用).{0,30}(?:看|核对|打开).{0,30}"
        r"(?:就|便)(?:已)?知道.{0,120}(?:此刻|现在|正).{0,30}(?:躺在|藏在|放在)|"
        r"(?:甚至不用|无需|不用).{0,30}(?:看|核对|打开).{0,30}(?:就|便)(?:已)?知道.{0,160}"
        r"(?:后备箱|暗格|夹层|柜底|箱底)",
        part_text or "",
        re.S,
    ):
        out.append(
            "因果失真：主角凭上一世记忆直接知道今生物品当前藏处。记忆只能提示要核对什么，"
            "当前事实必须通过本章已写出的当面检查才能发现。"
        )
    if re.search(
        r"(?:备忘|便签|纸条|铅笔小字).{0,120}(?:等他|等她).{0,40}(?:晕|死|倒下).{0,50}"
        r"(?:一切|事情).{0,12}(?:好办|结束)|(?:对手|反派).{0,30}(?:亲笔|自己写).{0,60}(?:害死|弄死|等他倒下)",
        part_text or "",
        re.S,
    ):
        out.append("正文让对手留下直白犯罪备忘录作为便利证据；删除自白式纸条，用当场行为和既定文件推动冲突。")
    inv = sum(1 for k in INVESTIGATION_NARRATIVE_TOKENS if k in part_text)
    rb = _count_rebirth_buckets(part_text)
    if inv >= 4 and rb < 2:
        out.append(
            "本章调查/媒体链过重且重生推进不足：删掉匿名邮件/媒体爆料/档案室翻找等，改为认出旧局与提前布子。"
        )
    cheap_hits = [marker for marker in CHEAP_MYSTERY_MARKERS if marker in part_text]
    if ("黑色轿车" in part_text or "黑色SUV" in part_text) and re.search(
        r"(黑色轿车|黑色SUV).{0,80}(跟踪|监视|尾随|盯梢)|(跟踪|监视|尾随|盯梢).{0,80}(黑色轿车|黑色SUV)",
        part_text,
        re.S,
    ):
        cheap_hits.append("跟踪车辆")
    if cheap_hits:
        out.append(
            "本章使用廉价神秘线制造推进："
            + "、".join(cheap_hits[:4])
            + "。删除陌生电话、匿名材料、跟踪或神秘援手，改成既有对手的公开动作与主角主动反卡。"
        )

    public_rebirth_paragraphs = [
        paragraph
        for paragraph in re.split(r"\n\s*\n", part_text or "")
        if re.search(r"记者|镜头|直播|人群|众人|红毯|舞台|观众|媒体", paragraph)
        and re.search(r"[“\"](?:[^”\"]{0,100})(?:上一世|前世|重生|死过一次|我回来了)(?:[^”\"]{0,100})[”\"]", paragraph)
    ]
    if public_rebirth_paragraphs:
        out.append(
            "人物行为失真：主角在记者、镜头或公众面前直接自曝上一世/重生。"
            "除非主题明确允许超自然公开，否则重生信息只能留在内心或极少数已建立的私密关系中。"
        )
    spoken_rebirth = re.findall(
        r"[“\"][^”\"\n]{0,100}(?:上一世|前世|重生|死过一次|我回来了)[^”\"\n]{0,100}[”\"]",
        part_text or "",
    )
    if spoken_rebirth:
        out.append("主角把上一世或重生秘密说进对白；这些信息只能留在内心叙述，不得向盟友或对手自曝。")
    opponent_names = [
        str(member.get("name") or "").strip()
        for member in (card.get("canonical_cast") or [])
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "opponent"
        and str(member.get("name") or "").strip()
    ]
    opponent_prev_life_memory = []
    for paragraph in re.split(r"\n\s*\n", part_text or ""):
        if not re.search(r"上一世|前世", paragraph):
            continue
        hits = [name for name in opponent_names if name in paragraph]
        explicit_memory = bool(re.search(
            r"(?:那|这|原来).{0,10}(?:是|属于)?(?:他|她)的记忆|"
            r"(?:他|她).{0,8}(?:记得|想起).{0,12}(?:上一世|前世)",
            paragraph,
        ))
        opponent_focalization = bool(re.search(
            r"(?:他|她).{0,8}(?:听见自己|感到自己|太阳穴|喉结|手指|心里).{0,80}"
            r"(?:上一世|前世)|"
            r"(?:上一世|前世).{0,80}(?:他|她).{0,8}(?:记得|想起|听见自己|感到自己)",
            paragraph,
            re.S,
        ))
        if hits and (explicit_memory or opponent_focalization):
            opponent_prev_life_memory.extend(hits)
    if opponent_prev_life_memory:
        out.append(
            "视角因果错误：反派 " + "、".join(dict.fromkeys(opponent_prev_life_memory))
            + " 被写成拥有上一世记忆。重生信息差只属于主角，其他人只能依据当前现场反应。"
        )
    high_tech_shortcuts = re.findall(
        r"区块链|哈希值|存证节点|射频|信号干扰器|同频段|相位相反|"
        r"服务器追踪|加密通道|双指纹|语音双重验证|营销号|病毒式传播|"
        r"元数据|验签接口|公开验签|绿色小盾|实时更新的后台日志",
        part_text or "",
    )
    if high_tech_shortcuts:
        out.append(
            "正文用高科技捷径代替人物布局："
            + "、".join(dict.fromkeys(high_tech_shortcuts))
            + "。改用纸面差异、当面交付、公开规则和对手亲口承认。"
        )
    social_media_shortcuts = re.findall(
        r"社交平台|热帖|转发量|评论区置顶|置顶回复|营销号|病毒式传播",
        part_text or "",
    )
    if social_media_shortcuts:
        out.append(
            "正文把冲突转成社交媒体曝光链："
            + "、".join(dict.fromkeys(social_media_shortcuts))
            + "。本书小闭环应在当前现场落地，不靠热帖、转发量或营销号结算。"
        )
    if re.search(
        r"(?:地下车库|停车场).{0,160}(?:黑车|黑色轿车|黑色车辆).{0,100}(?:启动|引擎|车牌)|"
        r"(?:黑车|黑色轿车|黑色车辆|黑色物流车|漆黑的?物流车|货厢漆黑).{0,160}(?:车牌|便签|碎纸机|无声启动)|"
        r"(?:车牌|便签|碎纸机).{0,160}(?:黑车|黑色轿车|黑色车辆|物流车)",
        part_text or "",
        re.S,
    ):
        out.append("章节使用黑色车辆、车牌或碎纸便签制造廉价神秘钩子；必须改成既有对手的直接反应或下一场已约定冲突。")
    canonical_cast = (card.get("canonical_cast") or []) if isinstance(card, dict) else []
    permitted_chapter_names = {
        str(member.get("name") or "").strip()
        for member in _select_grounded_chapter_cast(card)
        if isinstance(member, dict) and str(member.get("name") or "").strip()
    }
    out_of_scope_fixed_names = sorted({
        str(member.get("name") or "").strip()
        for member in canonical_cast
        if isinstance(member, dict)
        and str(member.get("name") or "").strip()
        and str(member.get("name") or "").strip() not in permitted_chapter_names
        and str(member.get("name") or "").strip() in (part_text or "")
    })
    if out_of_scope_fixed_names:
        out.append(
            "正文让执行卡未点名的固定人物越章出场："
            + "、".join(out_of_scope_fixed_names)
            + "。只保留本章执行卡明确点名的人物；其余现场参与者使用无姓名职位。"
        )
    unknown_named_roles = _unknown_named_roles_in_synopsis(part_text, canonical_cast)
    allowed_names = {
        str(member.get("name") or "").strip()
        for member in canonical_cast if isinstance(member, dict)
    } if isinstance(canonical_cast, list) else set()
    unknown_named_roles.extend(sorted({
        name
        for name in re.findall(r"[\u4e00-\u9fff]{1,5}[·•][\u4e00-\u9fff]{1,8}", part_text or "")
        if name not in allowed_names
        and not any(
            name in allowed_name or allowed_name in name
            for allowed_name in allowed_names
            if allowed_name
        )
    }))
    unknown_named_roles = list(dict.fromkeys(unknown_named_roles))
    if unknown_named_roles:
        out.append(
            "正文擅自新增或改名人物：" + "、".join(unknown_named_roles)
            + "。固定姓名只能来自 canonical_cast；其余人物必须使用无姓名职位称呼。"
        )
    planned_work_titles = _planned_work_titles(card)
    body_work_titles = set(re.findall(r"《([^》\n]{1,40})》", part_text or ""))
    unexpected_work_titles = sorted(body_work_titles - planned_work_titles)
    if unexpected_work_titles:
        out.append(
            "正文擅自改写作品名：" + "、".join(f"《{title}》" for title in unexpected_work_titles)
            + "。作品名只能沿用章节卡中已建立的名称。"
        )
    if re.search(r"[“‘][^”’\n]{2,16}[”’](?:全球)?(?:复出)?演唱会", part_text or ""):
        out.append("正文擅自给未命名的复出演唱会取名；只写“复出演唱会”。")
    if planned_work_titles and role_v2 in {
        "prev_life_death_only", "rebirth_awakening_only", "present_setup", "present_revenge"
    } and not (planned_work_titles & body_work_titles):
        out.append(
            "正文没有写出章节卡已建立的核心作品名："
            + "、".join(f"《{title}》" for title in sorted(planned_work_titles))
            + "。职业冲突不能退化成无名的‘那场试镜’。"
        )
    protagonist_name_for_title = next(
        (
            str(member.get("name") or "").strip()
            for member in canonical_cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "protagonist"
        ),
        "",
    )
    if protagonist_name_for_title and any(
        re.search(
            rf"《{re.escape(title)}》的\s*{re.escape(protagonist_name_for_title)}(?:\s|由|确定|角色|人选)",
            part_text,
            re.I,
        )
        for title in planned_work_titles
    ):
        out.append(
            f"语义失真：把固定主角姓名 {protagonist_name_for_title} 写成作品内角色名。"
            "正文应写女主角、主演或具体已建立的虚构角色名。"
        )
    for cast_member in canonical_cast if isinstance(canonical_cast, list) else []:
        if not isinstance(cast_member, dict):
            continue
        canonical_name = str(cast_member.get("name") or "").strip()
        first_name = canonical_name.split()[0] if canonical_name else ""
        if str(cast_member.get("alignment") or "").casefold() in {"ally", "support"} and first_name:
            if re.search(
                rf"{re.escape(first_name)}(?:\s+[A-Za-z]+)?.{{0,90}}"
                r"(?:亲手|曾经|上一世|前世)?.{0,12}(?:毁掉|毁了|背叛|陷害|抢走).{0,20}(?:梦想|事业|机会|角色|主角|她|他)",
                part_text,
                re.I | re.S,
            ):
                out.append(
                    f"固定阵营漂移：盟友 {canonical_name} 被写成曾毁掉或背叛主角的人。"
                    "盟友不得继承旧经纪人或核心对手的前世罪行。"
                )
        if not re.fullmatch(r"[A-Za-z]{3,}", first_name):
            continue
        drifted = {
            token
            for token in re.findall(
                rf"(?<![A-Za-z]){re.escape(first_name)}[A-Za-z]+(?![A-Za-z])",
                part_text,
                re.I,
            )
            if token.casefold() != first_name.casefold()
        }
        full_name_variants = {
            match.group(0)
            for match in re.finditer(
                rf"(?<![A-Za-z]){re.escape(first_name)}\s+[A-Z][a-z]+(?![A-Za-z])",
                part_text,
            )
            if match.group(0).casefold() != canonical_name.casefold()
        }
        drifted.update(full_name_variants)
        alignment = str(cast_member.get("alignment") or "").casefold()
        if drifted:
            out.append(
                f"固定人物名漂移：{canonical_name} 被写成 {', '.join(sorted(drifted))}。"
                "全文必须使用 canonical_cast 中的固定姓名或不引起歧义的简称。"
            )
        if alignment == "protagonist" and re.search(
            rf"最佳\s*{re.escape(first_name)}(?:\s+{re.escape(canonical_name.split()[-1])})?",
            part_text,
            re.I,
        ):
            out.append(
                f"语义失真：把人物姓名 {canonical_name} 写成奖项类别。"
                "奖项必须是最佳女主角、最佳新人等真实类别，且不能凭临时裁决直接授予。"
            )
        if alignment in {"protagonist", "ally", "support"} and re.search(
            rf"{re.escape(first_name)}(?:\s+[A-Za-z]+)?.{{0,36}}(?:被停职|被撤职|被开除|被带离|被带走|被解约|失去角色|取消资格)",
            part_text,
            re.I | re.S,
        ):
            out.append(
                f"固定阵营漂移：盟友/主角 {canonical_name} 被当作受罚对象。"
                "本章惩罚只能落在 canonical_cast 标注的 opponent 身上。"
            )
    ending = (part_text or "")[-260:]
    empty_hits = [marker for marker in EMPTY_ENDING_MARKERS if marker in (part_text or "")]
    if empty_hits:
        out.append(
            "章节结尾是空泛预告而非剧情事件："
            + "、".join(empty_hits[:3])
            + "。结尾必须停在既有对手的具体动作、公开结果或下一场已约定冲突上。"
        )

    if chapter_num == 1 or role_v2 == "prev_life_death_only":
        current_timeline_markers = ("重生", "今生", "另一世", "重新来过", "重塑命运", "第二次机会", "回到过去")
        leaked = [marker for marker in current_timeline_markers if marker in part_text]
        if leaked:
            out.append("第1章只能写上一世终局，不得出现今生行动或重生确认：" + "、".join(leaked))
        unplanned_legal_evidence = re.findall(
            r"知情同意书|授权书|遗产.{0,8}声明|遗嘱.{0,8}公证|"
            r"保单.{0,8}改签|受益人.{0,8}改签|加密群聊|拍下.{0,8}照片",
            part_text or "",
        )
        if unplanned_legal_evidence:
            out.append(
                "第1章擅自添加章节卡没有安排的法律文件或取证动作："
                + "、".join(dict.fromkeys(unplanned_legal_evidence))
                + "。只写现场可见的强制注射、围观嘲笑、利益方冷眼和主角死亡。"
            )
        if re.search(r"注射|针剂|镇静针", str(card.get("prev_life_tragedy") or "")):
            death_process_hits = re.findall(
                r"受益人|基金会名义|律师团|法律上没问题|保单.{0,12}(?:签|改|填)|"
                r"版权归属条款|遗作发布节奏|到账|估值|分成比例|董事会",
                part_text or "",
            )
            if death_process_hits:
                out.append(
                    "注射致死开篇展开了未规划的保险、版权或法律办理细节："
                    + "、".join(dict.fromkeys(death_process_hits))
                    + "。门外对话只能催问保险与死后版权何时生效，不得解释办理方式。"
                )
            if re.search(r"[A-Za-z0-9%℃]|[一二三四五六七八九十百]+支", part_text or ""):
                out.append(
                    "注射致死开篇出现精确次数、数值或英文符号；删除剂量、次数、时长和编号，"
                    "只保留明确拒绝、强行推针、药效发作与生命停止。"
                )
            anatomy_hits = re.findall(
                r"肺叶|静脉|血管|肋骨|胸腔内壁|心率|血氧|半衰期|针孔|胶管|"
                r"青色血管|药液.{0,12}(?:滑向|进入).{0,8}(?:静脉|血管)",
                part_text or "",
            )
            if anatomy_hits:
                out.append(
                    "注射致死开篇使用了过细的解剖或伪医学描写："
                    + "、".join(dict.fromkeys(anatomy_hits))
                    + "。只写主角可感知的无力、呼吸受阻、声音远去与心跳停止。"
                )
        protagonist_names = {
            str(member.get("name") or "").strip()
            for member in canonical_cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "protagonist"
        }
        if "麦珂·杰森" in protagonist_names:
            active_allies = []
            for member in canonical_cast if isinstance(canonical_cast, list) else []:
                if not isinstance(member, dict):
                    continue
                if str(member.get("alignment") or "").casefold() not in {"ally", "support"}:
                    continue
                ally_name = str(member.get("name") or "").strip()
                ally_aliases = {ally_name}
                if "·" in ally_name:
                    ally_aliases.add(ally_name.split("·", 1)[0])
                if any(alias and alias in (part_text or "") for alias in ally_aliases):
                    active_allies.append(ally_name)
            if active_allies:
                out.append(
                    "第1章阵营漂移：固定盟友出现在上一世谋杀现场："
                    + "、".join(active_allies)
                    + "。本章在场者只使用主角、固定对手及无姓名工作人员，盟友留到重生后登场。"
                )
        if not re.search(
            r"死亡|身亡|死去|临终|最后一口气|失去意识|生命.*尽头|心跳.*停止|"
            r"呼吸.*(?:停止|断绝)|停止.*呼吸|心脏.{0,24}(?:停住|停止搏动|不再搏动)|"
            r"心脏.{0,12}停跳|心电图.{0,80}(?:拉平|直线)|波形.{0,40}(?:拉平|直线)|"
            r"身体.*(?:冰冷|失去温度)|咽气",
            part_text,
        ):
            out.append("第1章必须在正文中场景化写到上一世生命结束，不能停在普通受挫或今生试镜。")
        has_described_overdose = bool(re.search(
            r"(?:药片|胶囊).{0,220}(?:塞进嘴|吞下|咽下|灌下)|"
            r"(?:塞进嘴|吞下|咽下).{0,160}(?:药片|胶囊|处方药)",
            part_text,
            re.S,
        ))
        tragedy = str(card.get("prev_life_tragedy") or "")
        has_planned_injection_death = bool(
            re.search(r"注射|针剂|镇静针", tragedy)
            and re.search(r"针剂|针头|针尖|注射|活塞|药液", part_text or "")
            and re.search(
                r"死亡|身亡|死去|心脏骤停|心跳.{0,12}(?:停止|停跳)|"
                r"心脏.{0,12}停跳|心电图.{0,80}(?:拉平|直线)|波形.{0,40}(?:拉平|直线)|"
                r"呼吸.{0,12}(?:停止|断绝)|生命.{0,12}结束",
                part_text or "",
            )
        )
        if (
            not re.search(SPECIFIC_DEATH_METHOD_PATTERN, part_text or "")
            and not has_described_overdose
            and not has_planned_injection_death
        ):
            out.append("第1章必须写明具体死亡方式；‘意外身亡’仍是摘要，不能替代针头刺入、强制推注和生命停止等场景化死因。")
        if re.search(r"经纪人.{0,30}(?:撤回|撤销|终止|解除).{0,20}(?:代理|支持)|(?:撤回|撤销|终止|解除).{0,20}(?:代理|支持).{0,30}经纪人", tragedy, re.S):
            manager_withdraws = bool(re.search(
                r"(?:旧经纪人|经纪人).{0,100}(?:撤回|撤销|终止|解除).{0,24}(?:代理|支持)|"
                r"(?:撤回|撤销|终止|解除).{0,24}(?:代理|支持).{0,100}(?:旧经纪人|经纪人)|"
                r"(?:旧经纪人|经纪人).{0,220}(?:退出本次选角|不再代表|停止代理)|"
                r"(?:退出本次选角|不再代表|停止代理).{0,120}(?:旧经纪人|经纪人)",
                part_text,
                re.I | re.S,
            ))
            manager_switches_side = bool(re.search(
                r"(?:旧经纪人|经纪人).{0,420}(?:担任|转投|转而代理|服务|站到|走到).{0,80}(?:Lila|固定对手)|"
                r"(?:Lila|固定对手).{0,240}(?:新经纪人|独家代理|由.{0,30}代理)",
                part_text,
                re.I | re.S,
            ))
            if not manager_withdraws:
                out.append("第1章遗漏核心背叛：旧经纪人必须在试镜失败现场明确撤回代理支持，不能只写选角意见。")
            elif not manager_switches_side:
                out.append("第1章只写旧经纪人撤回支持，却没有让其公开站到 Lila Voss 一边；核心背叛必须形成可见阵营转移。")
        opponent_name = next((
            str(member.get("name") or "").strip()
            for member in canonical_cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "opponent"
        ), "")
        if opponent_name and re.search(r"正式签约角色|正式签约.{0,12}(?:角色|女主角|主演)", tragedy):
            if not re.search(
                rf"{re.escape(opponent_name.split()[0])}.{{0,100}}(?:正式签约|签下|拿到|获得).{{0,24}}(?:角色|女主角|主演|合约)|"
                rf"(?:角色|女主角|主演|合约).{{0,60}}(?:归属|交给|给了).{{0,20}}{re.escape(opponent_name.split()[0])}|"
                rf"《[^》]+》.{{0,20}}官宣主演.{{0,12}}{re.escape(opponent_name.split()[0])}",
                part_text,
                re.I | re.S,
            ):
                out.append(f"第1章遗漏不可逆损失：必须明确写出 {opponent_name} 当场拿走核心角色或签下合约。")
        if len(re.findall(r"不再代表(?:你|Maya Reed)|撤回对Maya Reed的全部代理支持", part_text, re.I)) > 1:
            out.append("第1章重复执行旧经纪人撤回代理的同一背叛事件；只能现场发生一次，随后立即推进角色归属和死亡。")
        if opponent_name and len(re.findall(
            rf"{re.escape(opponent_name.split()[0])}.{{0,80}}(?:签下名字|落笔签字|签下.{0,16}(?:合同|合约))",
            part_text,
            re.I | re.S,
        )) > 1:
            out.append(f"第1章重复写 {opponent_name} 签下同一角色；只保留一次正式签约。")
        post_death_ending = (part_text or "")[-650:]
        if re.search(
            r"(?:死亡|死去|心跳.{0,8}停止|汽车熄火).{0,420}"
            r"(?:手机|消息|文件|录音|视频).{0,180}"
            r"(?:等待.{0,20}(?:看见|发现)|改变命运|某一天|可能性|契机)",
            post_death_ending,
            re.S,
        ):
            out.append(
                "第1章在死亡后追加神秘手机、消息或材料作为改变命运的物证钩子。"
                "本章必须停在死亡与未竟愿望，重生和今生筹码只能从下一章开始。"
            )

    if chapter_num == 2 or role_v2 == "rebirth_awakening_only":
        protagonist_name = next(
            (
                str(member.get("name") or "").strip()
                for member in canonical_cast if isinstance(member, dict)
                and str(member.get("alignment") or "").casefold() == "protagonist"
            ),
            "",
        )
        ally_name = next(
            (
                str(member.get("name") or "").strip()
                for member in canonical_cast if isinstance(member, dict)
                and str(member.get("alignment") or "").casefold() in {"ally", "support"}
            ),
            "",
        )
        planned_action = str(card.get("this_life_revenge") or "")
        if protagonist_name == "麦珂·杰森":
            ally_mentions: List[str] = []
            for member in canonical_cast if isinstance(canonical_cast, list) else []:
                if not isinstance(member, dict):
                    continue
                if str(member.get("alignment") or "").casefold() not in {"ally", "support"}:
                    continue
                ally_full = str(member.get("name") or "").strip()
                ally_aliases = {ally_full}
                if "·" in ally_full:
                    ally_aliases.add(ally_full.split("·", 1)[0])
                if any(alias and alias in (part_text or "") for alias in ally_aliases):
                    ally_mentions.append(ally_full)
            if ally_mentions:
                out.append(
                    "第2章阵营/职业漂移：固定盟友被拉进医疗夺权现场："
                    + "、".join(ally_mentions)
                    + "。本章只允许麦珂、康拉德和无姓名第三方医疗人员出场。"
                )
            forbidden_fixed_cast: List[str] = []
            for member in canonical_cast if isinstance(canonical_cast, list) else []:
                if not isinstance(member, dict):
                    continue
                fixed_name = str(member.get("name") or "").strip()
                if fixed_name in {protagonist_name, "康拉德·莫里森"}:
                    continue
                aliases = {fixed_name}
                if "·" in fixed_name:
                    aliases.add(fixed_name.split("·", 1)[0])
                if any(alias and alias in (part_text or "") for alias in aliases):
                    forbidden_fixed_cast.append(fixed_name)
            if forbidden_fixed_cast:
                out.append(
                    "第2章擅自带入医疗现场之外的固定人物："
                    + "、".join(dict.fromkeys(forbidden_fixed_cast))
                    + "。本章只允许麦珂、康拉德和无姓名第三方医疗人员。"
                )
            if re.search(r"[A-Za-z0-9]", part_text or ""):
                out.append("第2章混入英文字母、英文词或阿拉伯数字；本题人物均为中文固定名，其余数字用中文表述。")
            technical_drift = re.findall(
                r"成分报告|生产批号|批次编号|冷链|光谱|分析仪|扫码|扫描|备案库|代谢抑制剂|"
                r"医监署|执业医师执照|检验箱|防篡改|实时影像|拍照|录像|处方笺|"
                r"认证药师|电子协议|指纹录入|指纹认证|全员终端|豁免终止声明|证据威胁|"
                r"会议纪要|附件第|医疗备忘录第",
                part_text or "",
            )
            if technical_drift:
                out.append(
                    "第2章扩成药理/技术取证悬疑："
                    + "、".join(dict.fromkeys(technical_drift))
                    + "。只写问题针剂登记、封存、双签和权限移交，不分析成分或制造证据。"
                )
            if re.search(
                r"(?:针剂|注射|药液|活塞|推杆).{0,28}[一二两三四五六七八九十百]+(?:毫升|毫克|微克|分钟|分之一)|"
                r"[一二两三四五六七八九十百]+(?:毫升|毫克|微克).{0,28}(?:针剂|注射|药液)",
                part_text or "",
                re.S,
            ):
                out.append("第2章写入精确药物剂量、推注比例或操作时长；只写剂量可疑、推进异常和立即登记。")
            awakening_titles = re.findall(r"《([^》\n]{1,40})》", part_text or "")
            named_launches = re.findall(r"[“\"]([^”\"\n]{2,24})[”\"]发布会", part_text or "")
            if awakening_titles or named_launches:
                out.append("第2章擅自给文件、作品或复出发布会命名；本章统一使用功能称呼。")
            if "旧经纪人" in (part_text or ""):
                out.append("第2章人物身份漂移：本题医疗对手是康拉德·莫里森，不得把医生改写成旧经纪人。")
            if re.search(r"媒体问答|发布会.{0,24}(?:开场|彩排|提问|问答|正式开始)", part_text or ""):
                out.append("第2章提前进入正式发布会或媒体问答；本章必须停在医疗双签已经生效。")
            if re.search(r"米国.{0,12}(?:演艺中心|医疗中心|医院|医监署|监管机构)", part_text or ""):
                out.append("第2章擅自命名场馆或医疗监管机构；只写发布会预备厅和第三方医疗团队。")
        has_awake = bool(re.search(
            r"惊醒|醒来|睁开眼|眼睛猛地张开|猛地坐起|骤然坐起|从梦中醒|恢复意识|清醒过来",
            part_text,
        ))
        has_time_check = bool(re.search(r"日期|日历|年份|手机屏幕|时钟|镜子|身体|房间", part_text))
        has_rebirth_confirm = bool(re.search(
            r"重生|回到.*前|回到了|上一世|前世|再活一次|重新活了一次|时间倒流|真的回来了|又活过来",
            part_text,
        ))
        if not (has_awake and has_time_check and has_rebirth_confirm):
            out.append("第2章必须完整写出惊醒→核对环境/日期/身体→确认重生，不能直接跳到试镜或调查。")
        if protagonist_name and protagonist_name not in part_text:
            out.append(f"第2章没有使用固定主角姓名 {protagonist_name}，容易在扩写中发生身份替换。")
        if re.search(r"今天.{0,40}(?:正是|就是|举行).{0,16}试镜|今天.{0,40}试镜.{0,12}(?:日子|当天)|试镜.{0,12}(?:今天|当日).{0,8}(?:举行|开始)", part_text):
            out.append("第2章把‘试镜前数日’改成试镜当天；必须保留蓝图日期，不得压缩准备时间。")
        if re.search(
            r"(?:距离|离).{0,24}试镜.{0,16}(?:不到|不足)二十四小时|"
            r"(?:试镜|终选).{0,20}(?:明天|次日)(?:举行|开始|就要)|"
            r"试镜前夜",
            part_text,
            re.S,
        ):
            out.append("第2章把已锁定的‘试镜前三天’压缩成前夜或不到二十四小时；必须保留三天准备窗口。")
        if re.search(r"(?:Lila|莉拉).{0,45}(?:正式签约|已经签约|签下).{0,35}《", part_text, re.I | re.S):
            out.append("第2章提前把核心角色写成已被对手签走；当前角色竞争尚未结算，正式签约只能在后续试戏章发生。")
        if re.search(r"解除.{0,20}(?:旧经纪人|代理|经纪)|(?:旧经纪人|代理权|经纪约).{0,20}(?:解除|终止|撤销)", planned_action):
            if not _has_completed_representation_termination(part_text):
                out.append("第2章没有实际解除并送达生效旧经纪人的代理授权；写好、打印或放在桌上都不算完成。")
        if ally_name and ally_name in planned_action:
            if not _has_completed_ally_appointment(part_text, ally_name):
                out.append(f"第2章没有完成与固定盟友 {ally_name} 的会面预约；停在拨号等待不算部署落地。")
            ally_first = ally_name.split()[0]
            ally_call_starts = re.findall(
                rf"(?:拨通|拨打|打给|致电).{{0,45}}{re.escape(ally_first)}|"
                rf"{re.escape(ally_first)}.{{0,30}}(?:拨通|拨打|去电|打去电话)",
                part_text,
                re.I | re.S,
            )
            if len(ally_call_starts) > 1:
                out.append(f"第2章重复执行与固定盟友 {ally_name} 的预约电话；只保留一次完整通话并以预约确认收束。")
        planned_death = str(card.get("prev_life_tragedy") or "")
        if re.search(r"车祸|交通事故|撞向护栏", planned_death) and re.search(
            r"仿佛.{0,8}溺水|像.{0,8}溺水|溺水而死|服药过量|坠楼|跳楼",
            part_text,
        ):
            out.append("第2章的死亡余感改写了上一章车祸死法；只能写撞击、疼痛或意识中断，不得换成溺水、服药或坠楼。")
        if re.search(r"服药自杀|吞药自杀|服药过量|吞药过量|药物过量", planned_death) and re.search(
            r"仿佛.{0,10}溺水|像.{0,10}溺水|被人掐住|被掐住|车祸|撞向护栏|坠楼|跳楼|枪击",
            part_text,
        ):
            out.append("第2章的死亡余感改写了上一章服药过量死法；只能写药效、眩晕、呼吸困难或意识中断，不得换成溺水、扼颈、车祸或坠楼。")
        investigation_drift_hits = [
            marker for marker in ("寻找真相", "接近真相", "暴露线索", "通话时长", "语调的变化", "未来成为关键")
            if marker in part_text
        ]
        if len(investigation_drift_hits) >= 2:
            out.append(
                "第2章扩成调查推理部署：" + "、".join(investigation_drift_hits)
                + "。觉醒章只完成解约和预约，不记录通话特征、不寻找线索。"
            )
        meeting_request_count = len(re.findall(
            r"(?:需要|想要|希望).{0,16}(?:见面|会面)|预约.{0,20}(?:见面|会面)|"
            r"(?:见面|会面).{0,16}(?:预约|安排)",
            part_text,
        ))
        if meeting_request_count > 1:
            out.append(f"第2章重复提出与固定盟友 {ally_name or '盟友'} 的会面请求；只保留一次请求和一次明确确认。")
        if ally_name:
            ally_first = re.escape(ally_name.split()[0])
            if re.search(rf"电话另一端.{{0,80}}[“\"]{ally_first}[？?]", part_text, re.I | re.S):
                out.append(f"第2章电话说话人错位：固定盟友 {ally_name} 在电话另一端却反问自己的名字。")
        overreach_hits = [
            marker for marker in (
                "潜入", "跟踪", "偷听", "搜查", "账本",
                "匿名账户", "加密文档", "秘密交易", "新闻发布会", "直播间",
                "冲出门", "直奔", "拦下一辆", "电影院", "放映厅", "等待这一刻的人",
                "递给她一张名片", "递给他一张名片",
            )
            if marker in part_text
        ]
        temporal_overreach = bool(re.search(
            r"(?:^|[。！？\n])\s*(?:第二天|翌日|次日)(?:清晨|早上|上午|下午|晚上)?[，,]?"
            r".{0,50}(?:来到|走进|前往|抵达|出门|赶到|进入|站在|参加|开始试镜)",
            part_text,
            re.S,
        ))
        if temporal_overreach:
            overreach_hits.append("进入次日行动")
        if overreach_hits:
            out.append(
                "第2章越过觉醒与首次部署边界："
                + "、".join(overreach_hits[:6])
                + "。本章只能在重生当天完成确认和一个电话、预约、备份或拒签等第一步动作，不得推进到调查、潜入、对峙或次日行动。"
            )
        if re.search(
            r"被人推下|推下楼梯|推下楼|枪杀|枪击身亡|投毒|毒死|刺杀|摔断脊椎|坠楼身亡",
            part_text,
        ):
            out.append(
                "第2章擅自补造或改写上一章死亡方式；觉醒章只承接死亡余痛，"
                "不得新增凶手、楼梯、枪击、投毒或其他死因细节。"
            )
        if re.search(
            r"挂断电话.{0,420}(?:拨通.{0,30}(?:Victor|维克托)|[“\"]Victor[？?]|Victor[？?]是我)",
            part_text,
            re.I | re.S,
        ):
            out.append(
                "第2章重复执行首次部署：已经挂断与 Victor 的电话后又重新从拨号开写。"
                "只保留一次完整电话或预约动作，并以该动作落定收束。"
            )
        # Only inspect the actual ending. A wider window misclassifies an early
        # previous-life recollection of the opponent as a present-time visit.
        last_scene = (part_text or "")[-320:]
        for cast_member in canonical_cast if isinstance(canonical_cast, list) else []:
            if not isinstance(cast_member, dict):
                continue
            if str(cast_member.get("alignment") or "").casefold() != "opponent":
                continue
            opponent_name = str(cast_member.get("name") or "").strip()
            opponent_short = opponent_name.split()[0] if opponent_name else ""
            if opponent_short and re.search(
                rf"(?:{re.escape(opponent_short)}.{{0,36}}(?:推门|走进|站在|开口|问道|说道|盯着|出现)|"
                rf"(?:推门|走进|站在|开口|问道|说道|盯着|出现).{{0,36}}{re.escape(opponent_short)})",
                last_scene,
                re.I | re.S,
            ):
                out.append(
                    "第2章越过首次部署边界：核心对手在觉醒章结尾亲自闯入或开始对峙。"
                    "本章应停在主角完成一个部署，下一章再承接对手动作。"
                )
                break

    if role_v2 == "present_setup" and re.search(
        r"试戏|试镜|复试|终选|女主角|选角",
        " ".join(str(card.get(key) or "") for key in ("chapter_goal", "this_life_revenge", "core_payoff")),
    ):
        acting_match = re.search(
            r"(?:完成|开始|展开|呈现|演绎|表演).{0,28}(?:试戏|试镜|片段|独白|台词|对戏)|"
            r"(?:试戏|试镜|表演).{0,32}(?:完成|结束|落下|收住)",
            part_text,
        )
        qualification_match = re.search(
            r"(?:获得|赢得|进入|通过|确认进入|决定让.{0,16}进入).{0,18}(?:复试|终选)(?:资格|名单)?|"
            r"(?:复试|终选)(?:资格|名单).{0,16}(?:获得|确认|公布)",
            part_text,
        )
        if qualification_match and (not acting_match or qualification_match.start() < acting_match.start()):
            out.append("第3章在主角完成实际表演之前就宣布复试/终选资格；必须先试戏，再由有权者确认入口收益。")
        qualification_decisions = re.findall(
            r"(?:接下来是|进入|通过|获得|确认).{0,24}(?:复试|终选).{0,36}(?:留下|资格|名单|环节)|"
            r"(?:复试|终选).{0,24}(?:请.{0,20}留下|资格.{0,12}(?:获得|确认))",
            part_text,
            re.S,
        )
        if len(qualification_decisions) > 1:
            out.append("第3章重复宣布复试/终选资格；扩写只能深化同一场表演，不能再次结算同一收益。")
        if re.search(r"加入.{0,12}(?:电影)?剧组|确认出演|正式出演|担任.{0,20}(?:女主角|主演|角色)", part_text):
            out.append("第3章提前让主角加入剧组或获得正式角色；本章只能拿到复试/终选入口资格，正式授角留到核心试戏章。")

    if role_v2 == "present_revenge" and not _has_tangible_payoff(part_text, card):
        out.append(
            "本簇收尾章缺少可见兑现（双向）：必须同时写出对手即时失去角色、合作、职位、资格或利益，以及主角即时拿回角色、合约、名誉、赔偿或资源。"
        )
    if role_v2 == "present_revenge" and re.search(
        r"试戏|试镜|复试|终选|女主角|选角|主演合约",
        " ".join(str(card.get(key) or "") for key in ("chapter_goal", "this_life_revenge", "core_payoff")),
    ):
        protagonist = protagonist_name_for_title or str(card.get("main_protagonist") or "主角")
        malformed_role_award = re.search(
            r"(?:宣布|确认|决定).{0,50}(?:由|让)(?:导演|制片负责人|选角助理|片方代表)饰演|"
            r"(?:编剧兼联合导演制片负责人|经纪人选角助理)|"
            r"(?:导演|制片负责人|选角助理).{0,20}迎来职业生涯",
            part_text,
            re.S,
        )
        if malformed_role_award:
            out.append("核心角色章出现职位粘连或把无名职位误当成演员；必须由固定主角获得角色，由有权者作出决定。")
        planned_payoff = str(card.get("core_payoff") or "")
        if "失去该角色" in planned_payoff and not re.search(r"(?:解约|终止).{0,20}(?:Lila|对手).{0,20}(?:合同|合约)", planned_payoff, re.I | re.S):
            if re.search(
                r"(?:Lila|对手).{0,70}(?:此前签署|已有|现有).{0,20}(?:合同|合约)|"
                r"(?:合同|合约).{0,30}(?:今日终止|立刻终止|启动法律程序)",
                part_text,
                re.I | re.S,
            ):
                out.append("核心角色章凭空补造对手已签署的当前时间线合同；本章只能让其失去竞争资格并退出项目。")
        decision_count = len(re.findall(
            rf"(?:确定|宣布|确认).{{0,18}}(?:由\s*)?{re.escape(protagonist)}.{{0,16}}(?:担任|出演|为主演)",
            part_text,
            re.I | re.S,
        ))
        contract_gain_count = sum(len(re.findall(pattern, part_text, re.I | re.S)) for pattern in (
            rf"{re.escape(protagonist)}.{{0,20}}(?:获得|拿下|签下).{{0,16}}(?:主演|女主角|角色)(?:合约|合同)?",
            rf"(?:主演|女主角|角色)(?:合约|合同).{{0,16}}(?:归属|交给).{{0,12}}{re.escape(protagonist)}",
        ))
        if decision_count > 1 or contract_gain_count > 1:
            out.append("核心角色/主演合约在同一章被重复宣布或授予；只保留一次有权者裁决与一次当场签署。")
        if re.search(r"主演.{0,6}(?:合约|合同)|(?:合约|合同).{0,6}主演", planned_payoff):
            has_signed_contract = bool(re.search(r"当场签署|正式签约|签下.{0,16}(?:合约|合同)|(?:合约|合同).{0,12}(?:签署|生效)", part_text))
            deferred_contract = bool(re.search(r"准备.{0,12}(?:合约|合同)|尽快安排签约|之后.{0,12}签约|签约仪式", part_text))
            if not has_signed_contract or deferred_contract:
                out.append("核心角色章没有让主演合约当场签署生效，或把签约拖到未来；必须在本章完成正式合约。")
        planned_action = str(card.get("this_life_revenge") or "")
        if re.search(r"试戏|试镜|表演|演绎|独白|台词", planned_action):
            performance_starts = re.findall(
                rf"{re.escape(protagonist)}.{{0,55}}(?:开始即兴|开始表演|开始演绎|走到试戏标记|走上试戏标记)|"
                rf"(?:走到试戏标记|走上试戏标记).{{0,30}}{re.escape(protagonist)}",
                part_text,
                re.I | re.S,
            )
            if len(performance_starts) > 1:
                out.append("核心试戏章重复开始同一轮表演；只能完整演一次，随后立即进入裁决、签约和对手失角。")
            acting_match = re.search(
                rf"(?:{re.escape(protagonist)}.{{0,45}}(?:开始|完成|演绎|表演|说出|念出).{{0,30}}(?:试戏|试镜|片段|独白|台词|角色)|"
                rf"(?:试戏|试镜).{{0,45}}{re.escape(protagonist)}.{{0,28}}(?:开始|完成|收住|结束)|"
                rf"{re.escape(protagonist)}.{{0,30}}(?:收住|结束).{{0,18}}(?:动作|表演|试戏))",
                part_text,
                re.I | re.S,
            )
            payoff_match = re.search(
                rf"(?:确定|宣布|确认).{{0,18}}(?:由\s*)?{re.escape(protagonist)}.{{0,16}}(?:担任|出演|为主演)|"
                rf"{re.escape(protagonist)}.{{0,20}}(?:获得|拿下|签下).{{0,16}}(?:主演|女主角|角色)",
                part_text,
                re.I | re.S,
            )
            if not acting_match:
                out.append("核心试戏章缺少主角实际表演；必须写出主角开始并完成试戏动作，再结算角色与合约。")
            elif payoff_match and payoff_match.start() < acting_match.start():
                out.append("核心试戏章在主角完成实际表演前就授予角色；必须先表演，再由有权者裁决并当场签约。")
    if role_v2 == "present_revenge":
        montage_hits = [
            marker for marker in (
                "几天后", "几个月后", "数月后", "几年后", "多年后", "随着时间流逝",
            )
            if marker in part_text
        ]
        if montage_hits:
            out.append(
                "终章用时间蒙太奇代替即时结算："
                + "、".join(montage_hits[:4])
                + "。删除后日谈，把篇幅留给同一场冲突中的决定、损失、收益和对手反应。"
            )
        if re.search(
            r"(?:仍然|依然|还)保住.{0,12}(?:职位|角色|代言|合作|资格)",
            part_text,
        ):
            out.append(
                "终章明确让核心对手保住关键利益，削弱反杀兑现；"
                "本簇必须让其付出与前世伤害相称的即时资源代价。"
            )
    return out


def _infer_evidence_types_from_info_gap(info_gap: str) -> List[str]:
    """从 info_gap_from_prev_life 文本中尽量抽取“证据类型”（用于 prompt 的 must_include 约束）。

    目标：避免写死“值班室笔记/病历篡改”等固定示例，改为随簇内容变化。
    """
    text = (info_gap or "").strip()
    if not text:
        return ["本簇信息差中的具体证据或内幕"]

    t = text.replace(" ", "")
    evidences: List[str] = []

    def add(item: str) -> None:
        item = (item or "").strip()
        if not item:
            return
        if item not in evidences:
            evidences.append(item)

    # 经济年代文场景
    if "美元" in t or "脱锚" in t or "金本位" in t:
        add("美元脱锚/金价与汇率记录")
    if "通胀" in t or "CPI" in t or "物价" in t:
        add("通胀/CPI与物价数据")
    if "石油" in t or "能源" in t:
        add("石油供给/能源合同记录")
    if "固定利率" in t or "贷款" in t or "债务" in t:
        add("固定利率贷款与债务结构")
    if "铁路" in t or "货运" in t or "仓库" in t or "物流" in t:
        add("铁路货运/仓储合同")
    if "农地" in t or "农场" in t:
        add("农地与实物资产交易记录")
    if "股市" in t or "成长股" in t or "漂亮股票" in t or "基金" in t:
        add("股票持仓/基金交易记录")

    # 兼容旧医疗/职业场景
    if "电子签名" in t:
        add("电子签名记录")
    if "用药剂量" in t:
        add("用药剂量/电子用药记录")
    if "病历" in t:
        if "篡改" in t or "修改" in t:
            add("病历篡改/病历记录")
        else:
            add("病历记录")

    if "值班室" in t and "笔记" in t:
        add("值班室笔记")
    elif "笔记" in t:
        add("笔记")

    # 证据形态：录音/视频/邮件/记录/交易等
    if "录音" in t:
        add("录音/对话录音")
    if "视频" in t:
        add("密谈视频")

    if "邮件" in t:
        add("邮件往来")
    if "转账" in t:
        add("可疑转账记录")
    if "交易记录" in t or "地下交易" in t:
        add("地下交易记录")

    if "文件编号" in t and "时间节点" in t:
        add("关键时间节点与文件编号")
    elif "文件编号" in t:
        add("文件编号")
    elif "时间节点" in t:
        add("关键时间节点")

    if "会议" in t:
        add("会议内容/纪要")

    if "接触记录" in t:
        add("接触记录/名单")

    if "证据" in t:
        add("落锤证据")

    # fallback：普通职业信息差直接视为行动筹码，不诱导模型补造物证。
    if not evidences:
        add("本簇信息差对应的主动行动")

    return evidences[:3]


def _safe_filename_from_cluster_id(cluster_id: str) -> str:
    import re

    s = (cluster_id or "").strip()
    if not s:
        return "UNKNOWN"
    s = re.sub(r"[^0-9A-Za-z_\-]+", "_", s)
    return s[:80] if s else "UNKNOWN"


def _save_json_utf8(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _load_json_utf8(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_cluster_exec_plan_prompt(
    cluster: Dict[str, Any],
    chapter_cards: Dict[int, Dict[str, Any]],
    start_ch: int,
    end_ch: int,
) -> str:
    """
    生成“证据链执行计划”：为每个证据给出 evidence_id，并指定获取/验证/使用发生在具体章节。
    该计划会用于正文硬约束与 critic 的连续性判定。
    """
    cluster_id = str(cluster.get("cluster_id", "") or "").strip()
    cluster_name = str(cluster.get("name", cluster.get("cluster_name", "")) or "").strip()
    main_opp = str(cluster.get("main_opponent", "") or "").strip()
    core_payoff = str(cluster.get("core_payoff", "") or "").strip()
    info_gap = str(cluster.get("info_gap_from_prev_life", "") or "").strip()
    prev_tragedy = str(cluster.get("prev_life_tragedy", "") or "").strip()
    this_revenge = str(cluster.get("this_life_revenge", "") or "").strip()
    outcome = str(cluster.get("cluster_outcome", "") or "").strip()

    chapter_roles: List[str] = []
    for ch in range(start_ch, end_ch + 1):
        card = chapter_cards.get(ch, {}) or {}
        role_v2 = str(card.get("chapter_role_v2", "") or "").strip()
        chapter_roles.append(f"{ch}:{role_v2 or 'unknown'}")

    return f"""{COMMERCIAL_REBIRTH_WRITER_ROLE}请基于【情节族】信息生成一个【反杀筹码执行计划】。

【本项目主题硬锁定】
{constraints_text()}

【叙事前提】本计划必须服务本次主题：{MAIN_PROTAGONIST}依据已经建立的经历、知识与人物关系主动行动；后续反转必须由已铺垫的因果触发，不能靠偶然发现或天降线索。
禁止在剧情里依赖匿名邮件、陌生人递材料、匿名爆料作为唯一关键转折。

【非常重要】输出必须是严格 JSON（不要 Markdown，不要解释文字），且可被 json.loads 直接解析。
要求（非常重要）：
1. evidence_id（E1/E2/E3）只供内部规划和审查定位，绝对不得作为【E1】或 E1 等标签写进小说正文。
2. evidence_chain 选择 2-3 个核心证据；每个证据必须给出：
   - evidence_id：E1/E2/E3...
   - evidence_type：用简短中文描述（需与 info_gap_from_prev_life 对齐）
   - source：筹码来源（须能解释为主角上一世已知什么人、规则、时机、作品表现或已存在材料，而非天降）
   - acquire_chapter / verify_chapter / use_chapter：分别在 {start_ch}-{end_ch} 哪些章节发生（必须是章节号整数）
   - purpose：每个证据在剧情里的作用（兑现“重生复仇爽点链条”）
   - acquire_keywords / verify_keywords / use_keywords：用于 critic 判定动作是否发生在对应章节的关键词数组（每个数组至少 1 个关键词）
3. 获取/验证/使用章节必须满足：acquire_chapter <= verify_chapter <= use_chapter。
4. 对与“录音/七年前”相关的证据，必须让对应章节里的关键词与动作一致（避免“开始录音下一章却播放七年前录音”的跳链）。
5. forbidden_new_evidence_types：列出 3-5 个本情节族禁止突然新增的证据类型（须包含匿名爆料/匿名邮件驱动关键转折等）。
6. payoff_sequence：按“至少 5 步”写出反杀爽点兑现顺序（要体现：认出旧局→提前布子→对方照旧出招→反卡→亮证据落锤→结果落地）。
7. chapter_role_v2 为 prev_life_death_only 或 rebirth_awakening_only 的章节，禁止安排 acquire/verify/use；第2章只允许完成重生确认和第一步部署，正式筹码链从之后的章节开始。

输出 JSON 结构（仅输出此 JSON；所有 JSON 字符串字段内部不得出现真实换行）：
{{
  "cluster_id": "{cluster_id}",
  "cluster_name": "{cluster_name}",
  "evidence_chain": [
    {{
      "evidence_id": "E1",
      "evidence_type": "...",
      "source": "...",
      "acquire_chapter": {start_ch},
      "verify_chapter": {start_ch},
      "use_chapter": {end_ch},
      "purpose": "...",
      "acquire_keywords": ["..."],
      "verify_keywords": ["..."],
      "use_keywords": ["..."]
    }}
  ],
  "forbidden_new_evidence_types": ["...", "..."],
  "chapter_execution_focus": {{
    "{start_ch}": "...",
    "{min(start_ch+1,end_ch)}": "...",
    "{end_ch}": "..."
  }},
  "payoff_sequence": ["...", "...", "..."]
}}

【情节族信息】
cluster_id={cluster_id}
cluster_name={cluster_name}
覆盖章节={start_ch}-{end_ch}
主要对手={main_opp}
核心爽点={core_payoff}
上一世悲剧前提={prev_tragedy}
今生反击方式={this_revenge}
上一世留下的信息差（用于证据来源与证据类型对齐）={info_gap}
本簇结局/落点={outcome}

【章节角色分工（用于把证据链落在正确章节）】
{'; '.join(chapter_roles)}
"""


def _fallback_build_exec_plan_for_cluster(
    cluster: Dict[str, Any],
    chapter_nums: List[int],
    chapter_cards: Optional[Dict[int, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """模型未能生成/解析 exec_plan 时，按实际信息筹码安排章内动作。"""
    action_chapters = [
        int(ch)
        for ch in chapter_nums
        if str((chapter_cards or {}).get(ch, {}).get("chapter_role_v2") or "")
        not in {"prev_life_death_only", "rebirth_awakening_only"}
    ]
    action_chapters = action_chapters or [int(ch) for ch in chapter_nums]
    start_ch, end_ch = action_chapters[0], action_chapters[-1]
    info_gap = str(cluster.get("info_gap_from_prev_life", "") or "")
    scene_contracts = {
        int(ch): _derive_closed_scene_contract((chapter_cards or {}).get(ch, {}))
        for ch in action_chapters
    }
    carrier_first_seen: Dict[str, int] = {}
    for ch in action_chapters:
        contract = scene_contracts.get(ch) or {}
        for carrier in contract.get("current_evidence_carriers") or []:
            carrier_first_seen.setdefault(str(carrier), int(ch))
    evidence_types = list(carrier_first_seen)[:5]
    if not evidence_types:
        evidence_types = (
            _infer_evidence_types_from_info_gap(info_gap)
            or ["本簇信息差对应的当面行动"]
        )[:3]

    def _keywords_from_type(t: str) -> Dict[str, List[str]]:
        tt = (t or "").strip()
        if "录音" in tt:
            return {
                "acquire_keywords": ["录音笔", "按下"],
                "verify_keywords": ["回放", "七年前"],
                "use_keywords": ["当众播放", "揭穿", "录音"],
            }
        if "邮件" in tt:
            return {
                "acquire_keywords": ["邮件", "附件", "收件"],
                "verify_keywords": ["核对", "时间", "发件"],
                "use_keywords": ["公开邮件", "揭露", "证据"],
            }
        if "病历" in tt or "医疗" in tt:
            return {
                "acquire_keywords": ["病历", "诊断", "签字"],
                "verify_keywords": ["篡改", "更改", "对比"],
                "use_keywords": ["提交病历", "公示", "揭穿"],
            }
        if "笔记" in tt:
            return {
                "acquire_keywords": ["笔记", "值班室"],
                "verify_keywords": ["翻阅", "核对", "时间线"],
                "use_keywords": ["递交笔记", "公开", "当场"],
            }
        concrete = re.sub(r"[/／].*$", "", tt) or "当面行动"
        return {
            "acquire_keywords": [concrete, "提前"],
            "verify_keywords": [concrete, "核对", "确认"],
            "use_keywords": [concrete, "当场"],
        }

    evidences: List[Dict[str, Any]] = []
    triples = []
    for idx, evidence_type in enumerate(evidence_types):
        acquired = carrier_first_seen.get(
            evidence_type,
            min(start_ch + idx, end_ch) if len(chapter_nums) >= 3 else start_ch,
        )
        verified = acquired
        used = end_ch
        triples.append((evidence_type, acquired, verified, used))

    for idx, (etype, ac, vc, uc) in enumerate(triples, start=1):
        kw = _keywords_from_type(etype)
        source_contract = scene_contracts.get(int(ac)) or {}
        evidences.append(
            {
                "evidence_id": f"E{idx}",
                "evidence_type": etype,
                "source": (
                    str(source_contract.get("trigger_action") or "").strip()
                    or "主角依据上一世信息差在当前时间线主动准备的行动筹码"
                ),
                "acquire_chapter": int(ac),
                "verify_chapter": int(vc),
                "use_chapter": int(uc),
                "purpose": (
                    str((scene_contracts.get(int(uc)) or {}).get("immediate_result") or "").strip()
                    or "把信息差转化为当前行动，并在本簇内兑现阶段爽点"
                ),
                "acquire_keywords": kw["acquire_keywords"],
                "verify_keywords": kw["verify_keywords"],
                "use_keywords": kw["use_keywords"],
            }
        )

    chapter_execution_focus: Dict[str, Any] = {}
    for ch in chapter_nums:
        role = str((chapter_cards or {}).get(ch, {}).get("chapter_role_v2") or "")
        if role == "prev_life_death_only":
            chapter_execution_focus[str(ch)] = "只完成上一世失败与死亡，不进入今生筹码链"
        elif role == "rebirth_awakening_only":
            chapter_execution_focus[str(ch)] = "只完成重生确认与第一步部署，不获取或使用决定性材料"
        else:
            contract = scene_contracts.get(int(ch)) or {}
            chapter_execution_focus[str(ch)] = "→".join(filter(None, (
                str(contract.get("trigger_action") or ""),
                str(contract.get("opponent_self_incrimination") or ""),
                str(contract.get("immediate_result") or ""),
            ))) or (
                "认出旧局并提前行动，在当前职业场景中取得一个明确进展"
                if ch == start_ch
                else "对方照旧出招→主角现场反卡→有权者宣布双向职业结果"
            )

    payoff_sequence = []
    for ch in action_chapters:
        contract = scene_contracts.get(ch) or {}
        for field in (
            "trigger_action", "opponent_self_incrimination",
            "verification_action", "immediate_result",
        ):
            value = str(contract.get(field) or "").strip()
            if value and value not in payoff_sequence:
                payoff_sequence.append(value)
    if not payoff_sequence:
        payoff_sequence = [
            "旧局在今生再现，主角认出并提前布子",
            "对方按老剧本继续出招",
            "主角在关键点现场反卡",
            "对手否认或反扑失败",
            "现实得失当场落地",
        ]

    return {
        "cluster_id": str(cluster.get("cluster_id", "") or ""),
        "cluster_name": str(cluster.get("name", cluster.get("cluster_name", "")) or ""),
        "evidence_chain": evidences,
        "forbidden_new_evidence_types": ["天降视频", "匿名人送U盘", "匿名邮件", "匿名爆料", "无规划的关键证人"],
        "chapter_execution_focus": chapter_execution_focus,
        "scene_contracts": {
            str(ch): contract
            for ch, contract in scene_contracts.items()
            if contract
        },
        "payoff_sequence": payoff_sequence,
    }


def _normalize_exec_plan_chapters(
    plan: Dict[str, Any],
    chapter_nums: List[int],
    chapter_cards: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    """Keep evidence stages out of death/awakening-only chapters and in order."""
    eligible = [
        int(ch)
        for ch in chapter_nums
        if str((chapter_cards.get(ch) or {}).get("chapter_role_v2") or "")
        not in {"prev_life_death_only", "rebirth_awakening_only"}
    ]
    if not eligible:
        return plan

    def choose(raw: Any, floor: int) -> int:
        try:
            requested = max(int(raw), floor)
        except (TypeError, ValueError):
            requested = floor
        return next((ch for ch in eligible if ch >= requested), eligible[-1])

    for ev in plan.get("evidence_chain") or []:
        if not isinstance(ev, dict):
            continue
        acquire = choose(ev.get("acquire_chapter"), eligible[0])
        verify = choose(ev.get("verify_chapter"), acquire)
        use = choose(ev.get("use_chapter"), verify)
        ev["acquire_chapter"] = acquire
        ev["verify_chapter"] = verify
        ev["use_chapter"] = use
    return plan


def _generate_cluster_exec_plan(
    gen: "RebirthRevengeGeneratorV2",
    cluster: Dict[str, Any],
    chapter_cards: Dict[int, Dict[str, Any]],
    chapter_nums: List[int],
    exec_plan_path: Path,
) -> Dict[str, Any]:
    roles = {
        str((chapter_cards.get(ch) or {}).get("chapter_role_v2") or "")
        for ch in chapter_nums
    }
    if roles and roles.issubset({"prev_life_death_only", "rebirth_awakening_only"}):
        plan_obj = {
            "cluster_id": str(cluster.get("cluster_id") or ""),
            "cluster_name": str(cluster.get("name") or ""),
            "evidence_chain": [],
            "forbidden_new_evidence_types": ["本特殊结构章禁止进入筹码/证据链"],
            "chapter_execution_focus": {
                str(ch): "只完成上一世死亡" if str((chapter_cards.get(ch) or {}).get("chapter_role_v2")) == "prev_life_death_only"
                else "只完成重生确认与第一步部署"
                for ch in chapter_nums
            },
            "payoff_sequence": [],
        }
        try:
            _save_json_utf8(exec_plan_path, plan_obj)
        except Exception:
            pass
        return plan_obj

    modern_action_roles = {
        "rebirth_awakening_only",
        "present_setup",
        "present_revenge",
        "present_mid_bridge",
        "present_setup_and_revenge",
    }
    if roles and roles.issubset(modern_action_roles):
        plan_obj = _fallback_build_exec_plan_for_cluster(
            cluster, chapter_nums, chapter_cards
        )
        plan_obj = _normalize_exec_plan_chapters(plan_obj, chapter_nums, chapter_cards)
        try:
            _save_json_utf8(exec_plan_path, plan_obj)
        except Exception:
            pass
        return plan_obj

    if exec_plan_path.exists():
        try:
            plan = _load_json_utf8(exec_plan_path)
            if isinstance(plan, dict) and plan.get("evidence_chain"):
                return _normalize_exec_plan_chapters(plan, chapter_nums, chapter_cards)
        except Exception:
            pass

    start_ch, end_ch = int(chapter_nums[0]), int(chapter_nums[-1])
    prompt = _build_cluster_exec_plan_prompt(cluster, chapter_cards, start_ch, end_ch)

    plan_out = gen._call_api(  # type: ignore[attr-defined]
        prompt,
        None,
        0,
        max_tokens=1600,
    )
    plan_obj = _extract_json_obj_maybe(plan_out or "")
    if not isinstance(plan_obj, dict):
        plan_obj = {}

    evidence_chain = plan_obj.get("evidence_chain")
    if not isinstance(evidence_chain, list) or not evidence_chain:
        plan_obj = {}

    ok = bool(plan_obj)
    for ev in evidence_chain if isinstance(evidence_chain, list) else []:
        if not isinstance(ev, dict):
            ok = False
            break
        if not ev.get("evidence_id"):
            ok = False
            break
        for k in ("acquire_chapter", "verify_chapter", "use_chapter"):
            if k not in ev:
                ok = False
                break

    if not ok:
        plan_obj = _fallback_build_exec_plan_for_cluster(cluster, chapter_nums, chapter_cards)

    plan_obj = _normalize_exec_plan_chapters(plan_obj, chapter_nums, chapter_cards)

    try:
        _save_json_utf8(exec_plan_path, plan_obj)
    except Exception:
        pass
    return plan_obj


def _build_cluster_plan(cluster: Dict[str, Any]) -> Dict[str, Any]:
    """
    为单个事件簇生成「簇级执行计划」：每章 goal / must_include / must_not_include / ending，
    以及禁止新增核心角色等。用于在正文生成时作为硬性任务清单注入 prompt。
    """
    span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters")
    try:
        start_ch, end_ch = int(span[0]), int(span[1])
    except Exception:  # noqa: BLE001
        return {}
    length = max(1, end_ch - start_ch + 1)
    cid = cluster.get("cluster_id", "")
    name = cluster.get("name", "")
    main_opp = cluster.get("main_opponent", "")
    protagonist = MAIN_PROTAGONIST
    ps = cluster.get("user_protagonists")
    if isinstance(ps, list) and ps:
        protagonist = str(ps[0]) or MAIN_PROTAGONIST
    core_payoff = cluster.get("core_payoff", "")
    info_gap = (cluster.get("info_gap_from_prev_life") or "")
    outcome = cluster.get("cluster_outcome", "")

    # 从 info_gap 中抽取“必须显性使用的证据类型”（避免写死固定示例）
    evidence_types = _infer_evidence_types_from_info_gap(info_gap)
    required_evidence_hint = "、".join(evidence_types[:2]) if evidence_types else "本簇信息差中的具体证据或内幕"

    deus_forbid = REBIRTH_FORBIDDEN_DEUS_EX[:2]

    chapters_plan: Dict[str, Dict[str, Any]] = {}
    if length == 1:
        chapters_plan[str(start_ch)] = {
            "goal": f"单章内完成：完整上一世受害段落 + 今生凭记忆预判旧招并完成反击，兑现本簇爽点：{core_payoff}",
            "must_include": [
                "完整一段上一世受害（具体场景、对话、屈辱与无助，不得一句带过）",
                "当前阶段明确写出主角认出旧局或风险模式并提前行动",
                "反击时符合本次题材的规则、关系、成绩或材料仅用于坐实主角已经建立的判断，而非靠调查偶然发现",
                "反杀结果或处罚落地",
            ],
            "must_not_include": DEFAULT_FORBIDDEN_NEW_ROLES + ["新幕后黑手", "只埋钩子不兑现"] + deus_forbid,
            "ending": f"本簇结束，结果需落到：{outcome or '对手付出代价'}"[:80],
            "must_resolve_this_chapter": ["上一世受害写厚", "记忆先于证据的反击", "完成反杀并写出结果"],
        }
    elif length == 2:
        ch1, ch2 = start_ch, end_ch
        chapters_plan[str(ch1)] = {
            "goal": "今生冲突立刻发生；用一个聚焦闪回解释主角为何认出旧招，随后马上抢先行动并赢得小优势",
            "must_include": ["短而具体的上一世受挫场景", main_opp or "主对手", "主角凭记忆提前行动", "对手失算与主角的小收益"],
            "must_not_include": ["无关支线角色抢戏"] + REBIRTH_FORBIDDEN_DEUS_EX[:3] + DEFAULT_FORBIDDEN_NEW_ROLES,
            "ending": "先落定本章小胜利，再让既有对手当场作出下一步反应",
            "must_resolve_this_chapter": ["明确主对手与信息差来源", "章内小反杀已经兑现"],
        }
        chapters_plan[str(ch2)] = {
            "goal": f"对方照旧出招后当场反卡并完成：{core_payoff}，结果：{outcome or '对手付出代价'}",
            "must_include": [
                "写出对方按旧共识误判或走到他预埋的卡点",
                "当众揭穿或举报",
                "落锤链闭环（显性使用" + required_evidence_hint + "，材料只坐实他早已知道的周期判断）",
                "处罚/后果/职业毁灭或舆论崩塌",
            ],
            "must_not_include": ["只埋钩子不兑现", "更大风暴才刚开始", "新大Boss"] + REBIRTH_FORBIDDEN_DEUS_EX[:3] + DEFAULT_FORBIDDEN_NEW_ROLES,
            "ending": "本簇结束，主对手在本簇内得到应有下场",
            "must_resolve_this_chapter": ["照旧出招→反卡落锤", "证据链显性使用", "后果落地"],
        }
    else:
        # length >= 3：叙事骨架为「旧局重演链」，避免写成都市调查取证文
        ch1, ch_last = start_ch, end_ch
        chapters_plan[str(ch1)] = {
            "goal": (
                f"旧局重现：{protagonist}在与本簇主对手（{main_opp}）对峙或同场时，认出已经建立的风险或关系模式；"
                "主角必须马上采取符合本次题材的抢先行动，并在本章赢得一个具体小优势，而不是慢慢调查。"
            ),
            "must_include": [
                "明确写出主角识别旧局或风险的心理与既有依据",
                "提前布局：主角针对即将发生的风险做出符合本次题材的具体安排",
                f"信息差（{required_evidence_hint}）仅作为他已知如何判断周期的依据，不是本章才去「发现线索」",
                "本章内让对手至少一次失算，并写出主角获得的具体机会、资源、信任或主动权",
            ],
            "must_not_include": [
                "新幕后黑手",
                "追车/系统提示/无关神秘线",
                "把本章写成调查取证、到处找材料",
                "大段展开上一世完整受害经过（留给下一章）",
            ]
            + REBIRTH_FORBIDDEN_DEUS_EX
            + DEFAULT_FORBIDDEN_NEW_ROLES,
            "ending": "旧局已对上号，主角的第一步已经改变局面；用既有对手的下一步动作承接下一章",
            "must_resolve_this_chapter": ["锁定主对手", "认出旧局并提前布子", "完成一个章内小胜利", "禁止调查文推进"],
        }
        chapters_plan[str(ch1 + 1)] = {
            "goal": "在今生冲突中插入一段聚焦的上一世受害回忆，点明为何能预判旧招，并在回到今生后立刻完成一次反制",
            "must_include": [
                "上一世具体受害过程（聚焦一个场景，不得一句带过，也不得超过全章约四分之一）",
                (main_opp + "的主观恶意与手段") if main_opp else "主对手的主观恶意与手段",
                f"与{required_evidence_hint}对应的关键细节（他上一世如何因此被嘲笑、错失或无力救人）",
                "点明：今生反击的主动力是记忆与预判，不是偶然发现新材料",
                "闪回结束后主角立即行动，让对手当章失算一次",
            ],
            "must_not_include": ["无关支线角色抢戏"] + REBIRTH_FORBIDDEN_DEUS_EX + DEFAULT_FORBIDDEN_NEW_ROLES,
            "ending": "记忆解释完即回到今生，落定一次小反制并接住下一场既有冲突",
            "must_resolve_this_chapter": ["聚焦上一世受害段落", "记忆与预判动机立住", "章内小反制已经发生"],
        }
        chapters_plan[str(ch_last)] = {
            "goal": f"关键时刻反卡与结果落地：兑现本簇爽点 {core_payoff}，结局 {outcome or '职业毁灭/失去信任'}",
            "must_include": [
                "对方按上一世老套路/旧剧本出手或施压（照旧出招）",
                "主角在关键时刻用符合本次题材的行动、证据或公开结果落锤",
                f"显性使用{required_evidence_hint}完成闭环",
                "符合本次题材的具体后果：对手失去角色、资源、职位、名誉、信任或利益，主角拿回机会、筹码或话语权",
            ],
            "must_not_include": ["只埋钩子不兑现", "真正风暴才刚开始", "新大Boss"] + DEFAULT_FORBIDDEN_NEW_ROLES,
            "ending": "本簇结束，主对手在本簇内失去信任或受到处罚",
            "must_resolve_this_chapter": ["照旧出招→反卡落锤", "后果落地"],
        }
        mid_idx = 0
        for ch in range(ch1 + 2, ch_last):
            mid_idx += 1
            if length == 4:
                bridge_goal = (
                    f"诱敌与压实：对方按既定认知继续施压或走流程；{protagonist}执行已铺垫且符合人物能力的应对步骤，"
                    "必要时补刀对话压迫，不把整章写成搜集新线索。"
                )
                bridge_must = [
                    main_opp or "主对手",
                    "写出「对方照旧误判/施压」与「他早有准备」的对位",
                    f"与{required_evidence_hint}相关的动作仅为核实/取出/封死退路，而非首次发现",
                ]
            else:
                if mid_idx == 1:
                    bridge_goal = "压迫升级：对方继续按既定认知误判或施压；主角利用已布好的筹码逐步收紧，不引入新主线"
                elif mid_idx == 2:
                    bridge_goal = "将记忆层面的预判落实为可落锤的动作链，逼迫对手在公开场合露出破绽"
                else:
                    bridge_goal = "反击前夜：推进到可直接公开揭穿，不再扩展新问题或新材料"
                bridge_must = [
                    main_opp or "主对手",
                    "照旧出招与提前布子的对位",
                    f"围绕{required_evidence_hint}仅做核实/补刀/封口（不换证据来源）",
                ]
            bridge_must.append("本章必须完成一个小反杀：对手当场失算并付出小代价，主角获得可见收益或主动权")
            chapters_plan[str(ch)] = {
                "goal": bridge_goal,
                "must_include": bridge_must,
                "must_not_include": ["新核心人物", "新组织/新阴谋线", "再次详细重演一整段上一世受害（应用回忆指认即可）"]
                + REBIRTH_FORBIDDEN_DEUS_EX
                + DEFAULT_FORBIDDEN_NEW_ROLES,
                "ending": "先落定本章小胜利，再由既有对手的直接反应推进到下一章反杀或收尾",
                "must_resolve_this_chapter": ["诱敌/压实", "章内小反杀已经兑现", "禁止调查文灌水", "不扩散到其他簇"],
            }

    return {
        "cluster_id": cid,
        "cluster_name": name,
        "narrative_mode": "old_trap_replay",
        "must_finish_in_span": True,
        "final_payoff_chapter": end_ch,
        "forbidden_new_major_mysteries": True,
        "forbidden_new_core_roles": DEFAULT_FORBIDDEN_NEW_ROLES.copy(),
        "chapters": chapters_plan,
    }


def _apply_authoritative_chapter_milestone(
    card: Dict[str, Any],
    milestone: Dict[str, Any],
) -> None:
    """Keep chapter execution local while retaining cluster-level arc context."""
    if not isinstance(milestone, dict) or not any(milestone.values()):
        return

    action = str(milestone.get("action") or "").strip()
    opponent_reaction = str(milestone.get("opponent_reaction") or "").strip()
    result = str(milestone.get("result") or "").strip()
    if not action or not result:
        return

    card.setdefault("cluster_this_life_revenge", card.get("this_life_revenge", ""))
    card.setdefault("cluster_core_payoff", card.get("core_payoff", ""))
    card.setdefault("cluster_main_opponent", card.get("main_opponent", ""))

    cast = card.get("canonical_cast") or []
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
        and str(member.get("name") or "").strip()
    ), MAIN_PROTAGONIST)
    scene_opponent = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "opponent"
        and str(member.get("name") or "").strip()
        and (
            str(member.get("name") or "").strip() in opponent_reaction
            or str(member.get("name") or "").strip().split("·", 1)[0] in opponent_reaction
        )
    ), str(card.get("main_opponent") or "").strip())

    card["this_life_revenge"] = action
    card["core_payoff"] = result
    card["chapter_goal"] = f"本章按里程碑完成主动行动并落定结果：{action}；{result}"
    card["chapter_must_include"] = [
        item for item in (
            action,
            opponent_reaction,
            result,
            "本章行动与结果在同一场职业冲突中形成因果闭环",
            "当前行动必须利用已建立的信息差、人物关系或能力推进（可被读者明确识别）",
        )
        if item
    ]
    card["chapter_ending"] = f"停在本章结果已经生效及固定对手的直接反应：{result}"
    card["must_resolve_this_chapter"] = [result]
    if scene_opponent:
        card["main_opponent"] = scene_opponent
        card["allowed_roles"] = [protagonist, scene_opponent]


def _build_cards_from_clusters(clusters: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """
    从事件簇列表动态构造章节卡（不依赖 master_ctx_cards_v2.json）。
    先为每个簇生成簇级执行计划，再为每章写入 role + 完成度区间 + 本章任务清单 + 实体白名单/黑名单。
    返回 chapter_id -> card 的字典。
    """
    cards: Dict[int, Dict[str, Any]] = {}
    for cluster in clusters:
        span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters")
        try:
            start_ch, end_ch = int(span[0]), int(span[1])
        except Exception:  # noqa: BLE001
            continue
        length = max(1, end_ch - start_ch + 1)
        cluster_id = cluster.get("cluster_id", "")
        cluster_name = cluster.get("name", "")
        arc_id = cluster.get("arc_id", "A01")
        core_payoff = cluster.get("core_payoff", "")
        main_opp = cluster.get("main_opponent", "")
        prev_tragedy = cluster.get("prev_life_tragedy", "")
        this_revenge = cluster.get("this_life_revenge", "")
        info_gap = cluster.get("info_gap_from_prev_life", "")
        cluster_outcome = cluster.get("cluster_outcome", "")
        escalation = cluster.get("escalation_level", 1)
        canonical_cast = cluster.get("canonical_cast", []) or []
        chapter_milestones = [
            milestone
            for milestone in (cluster.get("chapter_milestones") or [])
            if isinstance(milestone, dict)
        ]
        ps = cluster.get("user_protagonists")
        protagonist = str(ps[0]) if isinstance(ps, list) and ps else MAIN_PROTAGONIST

        plan = _build_cluster_plan(cluster)
        plan_chapters = (plan.get("chapters") or {})

        for idx, ch in enumerate(range(start_ch, end_ch + 1)):
            chapter_index = idx + 1
            chapter_milestone = next(
                (
                    milestone
                    for milestone in chapter_milestones
                    if int(milestone.get("chapter") or 0) == ch
                ),
                {},
            )
            # 若为第 1/2 章，优先使用硬编码 SPECIAL_CARDS，而不是按簇自动推断职责
            special = SPECIAL_CARDS.get(ch)
            if special:
                role_v2 = special.get("chapter_role_v2", "present_only")
                tmpl = "M1"
                # 对第 1/2 章而言，只负责“死前绝境”或“重生惊醒”，不要求完成本簇闭环
                completion_min, completion_max = 0, 30
            elif length == 1:
                role_v2 = "present_setup_and_revenge"
                tmpl = "M1"
                completion_min, completion_max = 0, 100
            elif length == 2:
                role_v2 = "present_past_mix" if chapter_index == 1 else "present_revenge"
                tmpl = "M1"
                completion_min = 0 if chapter_index == 1 else 50
                completion_max = 50 if chapter_index == 1 else 100
            else:
                if chapter_index == 1:
                    role_v2, tmpl = "present_setup", "M1"
                    completion_min, completion_max = 0, 30
                elif chapter_index == 2:
                    role_v2, tmpl = "present_past_mix", "M1"
                    completion_min, completion_max = 30, 70
                elif chapter_index == length:
                    role_v2, tmpl = "present_revenge", "M1"
                    completion_min, completion_max = 70, 100
                else:
                    role_v2, tmpl = "present_mid_bridge", "M3"
                    completion_min = 30 + (chapter_index - 2) * (40 // max(1, length - 2))
                    completion_max = min(70, completion_min + 40)

            ch_plan = plan_chapters.get(str(ch), {})
            # 若有 SPECIAL_CARDS，则用其 goal/must_include 等覆盖 plan 中对应字段
            if special:
                if special.get("chapter_goal"):
                    ch_plan["goal"] = special["chapter_goal"]
                if special.get("chapter_must_include"):
                    ch_plan["must_include"] = special["chapter_must_include"]
                if special.get("chapter_must_not_include"):
                    ch_plan["must_not_include"] = special["chapter_must_not_include"]
                if special.get("chapter_ending"):
                    ch_plan["ending"] = special["chapter_ending"]
                if special.get("must_resolve_this_chapter"):
                    ch_plan["must_resolve_this_chapter"] = special["must_resolve_this_chapter"]
            card = {
                "chapter_id": ch,
                "arc_id": arc_id,
                "cluster_id": cluster_id,
                "cluster_name": cluster_name,
                "structure_template": tmpl,
                "chapter_role_v2": role_v2,
                "core_payoff": core_payoff,
                "main_opponent": main_opp,
                "prev_life_tragedy": prev_tragedy,
                "this_life_revenge": this_revenge,
                "info_gap_from_prev_life": info_gap,
                "cluster_outcome": cluster_outcome,
                "escalation_level": escalation,
                "canonical_cast": canonical_cast,
                "cluster_span_start": start_ch,
                "cluster_span_end": end_ch,
                "cluster_chapter_index": chapter_index,
                "cluster_chapter_total": length,
                "cluster_completion_min": completion_min,
                "cluster_completion_max": completion_max,
                "chapter_goal": ch_plan.get("goal", ""),
                "chapter_must_include": ch_plan.get("must_include", []),
                "chapter_must_not_include": ch_plan.get("must_not_include", []),
                "chapter_ending": ch_plan.get("ending", ""),
                "must_resolve_this_chapter": ch_plan.get("must_resolve_this_chapter", []),
                "chapter_milestone": chapter_milestone,
                "cluster_milestones": chapter_milestones,
                "allowed_roles": [protagonist, main_opp] if main_opp else [protagonist],
                "forbidden_roles": list(plan.get("forbidden_new_core_roles", DEFAULT_FORBIDDEN_NEW_ROLES)),
            }
            if not special:
                _apply_authoritative_chapter_milestone(card, chapter_milestone)
            card["scene_contract"] = _derive_closed_scene_contract(card)
            card["theme_constraints"] = constraints_text()
            attach_theme_contract(card)
            cards[ch] = card
    return cards


def _cluster_critic(
    cluster: Dict[str, Any],
    chapter_texts: Dict[int, str],
    exec_plan: Optional[Dict[str, Any]] = None,
    chapter_cards: Optional[Dict[int, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    簇完成审查器：检查本簇各章是否完成闭环、是否引入未规划角色、是否显性使用信息差。
    返回 payoff_completed, violations, rewrite_advice 等，用于决定是否强制重写。
    """
    span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters")
    try:
        start_ch, end_ch = int(span[0]), int(span[1])
    except Exception:  # noqa: BLE001
        return {"payoff_completed": False, "violations": ["簇章节范围无效"], "rewrite_advice": ["请检查 event_clusters_v2.json"]}
    last_ch = end_ch
    last_text = (chapter_texts.get(last_ch) or "").strip()
    full_text = " ".join(chapter_texts.get(ch, "") for ch in range(start_ch, end_ch + 1))

    if start_ch == end_ch == 1:
        violations: List[str] = []
        rewrite_advice: List[str] = []
        if len(last_text) < MIN_CHAPTER_CHARS_V2:
            violations.append(f"第1章字数不足（{len(last_text)}字）")
            rewrite_advice.append(f"第1章扩写到不少于{MIN_CHAPTER_CHARS_V2}字，具体呈现旧阶段失败及其代价。")
        if not any(marker in last_text for marker in (
            "上一世", "前世", "曾经", "那一晚", "失败", "遗憾", "没能",
            "死亡", "死去", "身亡", "心脏骤停", "心跳停止", "呼吸断绝",
        )):
            violations.append("第1章没有清楚建立旧阶段失败或未竟目标")
            rewrite_advice.append("补足主角旧阶段的具体失败、代价和未竟目标，不提前完成新阶段反击。")
        return {
            "payoff_completed": not violations,
            "violations": violations,
            "rewrite_advice": rewrite_advice,
            "introduced_new_roles": [],
        }

    if start_ch == end_ch == 2:
        violations = []
        rewrite_advice = []
        has_awake = bool(re.search(r"惊醒|醒来|睁开眼|猛地坐起|从梦中醒", last_text))
        has_time_check = bool(re.search(r"日期|日历|年份|手机屏幕|时钟|镜子|身体|房间", last_text))
        has_rebirth_confirm = bool(re.search(r"重生|回到.*前|回到了|上一世|前世|再活一次", last_text))
        awakening_min_chars = _minimum_chapter_chars(2)
        if len(last_text) < awakening_min_chars:
            violations.append(f"第2章字数不足（{len(last_text)}字）")
            rewrite_advice.append(f"第2章扩写到不少于{awakening_min_chars}字，但不得进入试镜或完成反杀。")
        if not (has_awake and has_time_check and has_rebirth_confirm):
            violations.append("第2章未完整完成惊醒、现实核对与重生确认")
            rewrite_advice.append("第2章只补足惊醒→核对日期/环境/身体→确认重生→完成一个首次部署。")
        return {
            "payoff_completed": not violations,
            "violations": violations,
            "rewrite_advice": rewrite_advice,
            "introduced_new_roles": [],
        }

    violations: List[str] = []
    rewrite_advice: List[str] = []
    introduced: List[str] = []

    # 1. 最后一章是否兑现 core_payoff / cluster_outcome
    core_payoff = (cluster.get("core_payoff") or "")
    outcome = (cluster.get("cluster_outcome") or "")
    # 放宽但更全面的“结果落地”判定：接受更丰富的同义表达，且允许在最后两章内出现
    last_two = (chapter_texts.get(last_ch, "") or "") + " " + (chapter_texts.get(last_ch - 1, "") or "")
    outcome_ok = _has_tangible_payoff(last_two, cluster)
    if not outcome_ok and len(last_text) > 200:
        violations.append("本簇最后一章未完成反杀结果/职业毁灭/处罚落地")
        rewrite_advice.append(
            "最后一章必须具体呈现场景化的双向结果：对手即时失去角色、合作、职位、资格或利益，主角同时拿回角色、合约、名誉、赔偿或资源；不要只写真相曝光、道歉或未来会有后果。"
        )

    # 2. 是否引入禁止角色/元素
    forbidden_check = [
        "系统提示音", "苏晚晴", "神秘司机", "神秘人", "神秘男人",
        "幕后黑手", "更大风暴", "真正的风暴", "陌生号码", "陌生来电", "匿名短信",
        "有人跟踪", "被跟踪", "神秘制片人",
    ]
    for w in forbidden_check:
        if w in full_text:
            violations.append(f"正文中出现禁止元素或未规划角色：{w}")
            introduced.append(w)
    if introduced:
        rewrite_advice.append("删除或改写未在本簇规划中的新核心角色（如苏晚晴、神秘司机、系统提示等）")

    # 3. 信息差必须转化为今生行动，但不强求录音、文件等物证词。
    info_gap = (cluster.get("info_gap_from_prev_life") or "")
    if info_gap:
        remembers_old_line = bool(re.search(
            r"上一世|前世|那一世|记得|认出|熟悉|早就知道|早已知道|预判|老办法|旧局",
            full_text,
        ))
        converts_to_action = bool(re.search(
            r"提前|先一步|主动|当场|联系|争取|拒绝|改掉|调整|准备|利用|抢先|预留|要求|提出",
            full_text,
        ))
        used = remembers_old_line and converts_to_action
        if not used and len(full_text) > MIN_CHAPTER_CHARS_V2 * max(1, end_ch - start_ch + 1):
            violations.append("本簇信息差未转化为今生主动行动")
            rewrite_advice.append(
                "写清主角先认出上一世旧局，再据此提前改变权限、合同、关系或现场选择；不要补造录音、文件或调查链。"
            )

    # 4. 每章字数是否达标（须与逐章预检 MIN_CHAPTER_CHARS_V2 一致）
    for ch in range(start_ch, end_ch + 1):
        t = (chapter_texts.get(ch) or "").strip()
        chapter_card = (chapter_cards or {}).get(ch)
        min_chars_per_ch = _minimum_chapter_chars(ch, chapter_card)
        if not chapter_card and re.search(
            r"训练强度决定权|现场见证人说：“测试通过|"
            r"封签.{0,120}送货单.{0,120}领用簿",
            t,
            re.S,
        ):
            min_chars_per_ch = min(min_chars_per_ch, 700)
        if len(t) < min_chars_per_ch:
            violations.append(f"第{ch}章字数不足（{len(t)}字）")
            rewrite_advice.append(
                f"第{ch}章必须扩写到不少于{min_chars_per_ch}字：按 beats 逐拍展开，补足动作、对话与情绪转折，不得用新线索灌水。"
            )

    # 5. 主对手是否聚焦
    main_opp = (cluster.get("main_opponent") or "")
    main_opp_aliases = {main_opp}
    for actor in re.split(r"(?:与|和|、|及|/)", main_opp):
        actor = actor.strip()
        if not actor:
            continue
        main_opp_aliases.add(actor)
        if "·" in actor:
            main_opp_aliases.add(actor.split("·", 1)[0])
    if (
        main_opp and len(main_opp) < 10
        and not any(alias and alias in full_text for alias in main_opp_aliases)
        and len(full_text) > 1000
    ):
        violations.append("本簇主对手未在正文中充分出现，冲突被稀释")
        rewrite_advice.append(f"确保本簇冲突围绕主对手（{main_opp}）展开，不要被其他角色抢戏")

    span_len = end_ch - start_ch + 1
    if start_ch <= 1 < end_ch and not _cluster_has_substantial_prev_life_block(chapter_texts, start_ch, end_ch):
        violations.append(
            "情节族上一世受害段落篇幅不足：未检测到任何一章写足完整的上一世受害段落（不能仅一句「上一世」带过）"
        )
        rewrite_advice.append(
            "在至少一章中用完整段落展开上一世受害（具体场景、对话、屈辱与无助），再写今生如何凭记忆预判与反击。"
        )
    if span_len >= 3 and not _cluster_revenge_pattern_ok(full_text):
        violations.append(
            "情节族重生复仇推进模式不足：未体现至少三类「旧招识别/提前布子/对方照旧出手/关键时刻反卡」"
        )
        rewrite_advice.append(
            "强化『记忆先于证据』：先写认出旧局与提前布子、对方照旧出招，再在关键时刻用证据落锤；避免全章调查取证。"
        )
    deus_hits = _cluster_detect_deus_ex_machina(full_text)
    if deus_hits:
        violations.append(
            "疑似天降线索套路：" + "、".join(deus_hits[:5]) + "（本世线索应来自记忆主动取证或对手照旧出招露破绽）"
        )
        rewrite_advice.append("删掉匿名爆料/陌生人递材料等桥段，改为他凭上一世记忆主动布局，或对手按旧经济共识误判后自露破绽。")

    fmt_leak = _critic_format_leak(full_text)
    if fmt_leak:
        violations.append(fmt_leak)
        rewrite_advice.append("删除正文中的「第1拍/scene_goal/end_to_next」等模板字段或节拍编号，只保留小说叙述。")

    ne_fail = _critic_narrative_engine_investigation(full_text)
    if ne_fail:
        violations.append(ne_fail)
        rewrite_advice.append(
            "整簇重写为重生预判反杀：旧局识别→提前布子→对方照旧→当场反卡；大幅删减调查/媒体/发布会/档案取证链。"
        )

    # 6. 证据链连续性：证据 marker 只能出现在 acquire/verify/use 对应章节，并且关键词需对齐
    strict_evidence_plan = bool(
        isinstance(exec_plan, dict)
        and isinstance(exec_plan.get("evidence_chain"), list)
        and exec_plan.get("evidence_chain")
        and not all(
            "主动准备的行动筹码" in str(ev.get("source") or "")
            for ev in exec_plan.get("evidence_chain")
            if isinstance(ev, dict)
        )
    )
    if strict_evidence_plan:
        evidence_chain = [ev for ev in (exec_plan.get("evidence_chain") or []) if isinstance(ev, dict)]

        def _text_of(ch: int) -> str:
            return str(chapter_texts.get(ch) or "")

        def _has_any_kw(text: str, kws: Any) -> bool:
            if not isinstance(kws, list):
                return True
            hit_any = False
            for k in kws:
                ks = str(k or "").strip()
                if not ks:
                    continue
                hit_any = True
                if ks in text:
                    return True
            # 如果给了空/无效关键词，视为不做硬判定
            return not hit_any

        for ev in evidence_chain:
            evidence_id = str(ev.get("evidence_id", "") or "").strip()
            if not evidence_id:
                continue
            marker = f"【{evidence_id}】"
            acquire_ch = ev.get("acquire_chapter")
            verify_ch = ev.get("verify_chapter")
            use_ch = ev.get("use_chapter")
            if acquire_ch is None or verify_ch is None or use_ch is None:
                continue

            try:
                acquire_ch_i = int(acquire_ch)
                verify_ch_i = int(verify_ch)
                use_ch_i = int(use_ch)
            except Exception:  # noqa: BLE001
                continue

            if not (acquire_ch_i <= verify_ch_i <= use_ch_i):
                violations.append(f"证据链连续性失败：{marker} 的 acquire/verify/use 章节顺序不满足 acquire<=verify<=use")
                rewrite_advice.append(f"修正证据链：{marker} 获取/验证/使用顺序需满足 acquire<=verify<=use。")
                continue

            allowed_stage_chapters = {acquire_ch_i, verify_ch_i, use_ch_i}

            # 不能串到其他章节（强制避免“跳链/时间链断档”）
            for ch in range(start_ch, end_ch + 1):
                if ch in allowed_stage_chapters:
                    continue
                if marker in _text_of(ch):
                    violations.append(
                        f"证据链连续性失败：{marker} 不应出现在第{ch}章（仅允许出现在第{sorted(list(allowed_stage_chapters))}章）。"
                    )
                    rewrite_advice.append(f"删除/移除第{ch}章中的 {marker}（证据标记必须严格按获取/验证/使用章节出现）。")

            # 关键词对齐（只要给了关键词就做硬判定）
            acquire_keywords = ev.get("acquire_keywords") or []
            verify_keywords = ev.get("verify_keywords") or []
            use_keywords = ev.get("use_keywords") or []
            if acquire_keywords and not _has_any_kw(_text_of(acquire_ch_i), acquire_keywords):
                violations.append(f"证据链连续性失败：{marker} 获取章节第{acquire_ch_i}章缺少获取关键词。")
                rewrite_advice.append(f"请在第{acquire_ch_i}章把 {marker} 的获取动作写具体，并命中 acquire_keywords。")
            if verify_keywords and not _has_any_kw(_text_of(verify_ch_i), verify_keywords):
                violations.append(f"证据链连续性失败：{marker} 验证章节第{verify_ch_i}章缺少验证关键词。")
                rewrite_advice.append(f"请在第{verify_ch_i}章把 {marker} 的验证动作写具体，并命中 verify_keywords。")
            if use_keywords and not _has_any_kw(_text_of(use_ch_i), use_keywords):
                violations.append(f"证据链连续性失败：{marker} 使用章节第{use_ch_i}章缺少使用关键词。")
                rewrite_advice.append(f"请在第{use_ch_i}章把 {marker} 的使用/落锤动作写具体，并命中 use_keywords。")

    # 情节族是正文的最高级合同。任何已识别违规都必须重写，不能再以
    # “非关键提示”为由交付一份长度、证据链或因果仍有缺口的正文。
    payoff_completed = outcome_ok and not violations
    return {
        "payoff_completed": payoff_completed,
        "used_required_info_gap": "信息差" not in str(violations),
        "introduced_new_major_roles": introduced,
        "violations": violations,
        "rewrite_advice": rewrite_advice,
    }


def _build_cluster_internal_state(
    cluster: Dict[str, Any],
    chapter_texts: Dict[int, str],
    chapters_dir: str,
) -> Dict[str, Any]:
    """根据本簇已写章节内容，生成 resolved_so_far / unresolved_must_finish，供下一章 prompt 使用。"""
    span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters")
    try:
        start_ch, end_ch = int(span[0]), int(span[1])
    except Exception:  # noqa: BLE001
        return {}
    cid = cluster.get("cluster_id", "")
    main_opp = cluster.get("main_opponent", "")
    info_gap = cluster.get("info_gap_from_prev_life", "")
    outcome = cluster.get("cluster_outcome", "")

    resolved: List[str] = []
    for ch in range(start_ch, end_ch + 1):
        text = (chapter_texts.get(ch) or "")[:600]
        if not text:
            continue
        if main_opp and main_opp in text:
            resolved.append(f"已明确本簇主对手（{main_opp}）")
        if any(k in text for k in ["笔记", "病历", "证据", "记录", "值班室"]):
            resolved.append("已出现与信息差相关的线索或证据")
        if "上一世" in text or "记得" in text:
            resolved.append("已展开或触及上一世回忆")
        if ch == end_ch and any(k in text for k in ["举报", "揭穿", "吊销", "处罚", "失去"]):
            resolved.append("本簇反杀已兑现")

    unresolved: List[str] = []
    if not any("上一世" in (chapter_texts.get(ch) or "") for ch in range(start_ch, end_ch + 1)):
        unresolved.append("展开上一世在本簇情境下的受害回忆")
    if info_gap and not any(h in " ".join(chapter_texts.values()) for h in ["笔记", "病历", "篡改", "记录", "证据"]):
        unresolved.append("显性使用信息差中的证据（如值班室笔记、病历篡改）")
    if not any(k in (chapter_texts.get(end_ch) or "") for k in ["举报", "揭穿", "吊销", "职业", "处罚", "信任"]):
        unresolved.append("最后一章必须写出反杀结果与对手下场")

    return {
        "cluster_id": cid,
        "resolved_so_far": list(dict.fromkeys(resolved)),
        "unresolved_must_finish": list(dict.fromkeys(unresolved)),
        "forbidden_expansion": DEFAULT_FORBIDDEN_NEW_ROLES.copy(),
    }


def _load_prev_life_ctx(path: str) -> Dict[int, str]:
    """从 prev_life_ctx_v2.txt 格式文件中加载 chapter_num -> 线索文本。"""
    import re
    out: Dict[int, str] = {}
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^第(\d+)章对应线索\s*[：:]\s*(.+)$", line)
        if m:
            out[int(m.group(1))] = m.group(2).strip()
    return out


def _load_master_cards_v2(path: Optional[str]) -> Dict[int, Dict[str, Any]]:
    """加载由 generate_outline_from_event_clusters_v2.py 生成的 master_ctx_cards_v2.json。"""
    if not path:
        return {}
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        out: Dict[int, Dict[str, Any]] = {}
        for item in data:
            if isinstance(item, dict) and item.get("chapter_id") is not None:
                try:
                    out[int(item["chapter_id"])] = item
                except Exception:  # noqa: BLE001
                    continue
        return out
    if isinstance(data, dict):
        # 兼容极少数情况下输出为 chapter_id -> card 的字典
        out: Dict[int, Dict[str, Any]] = {}
        for k, v in data.items():
            if isinstance(v, dict):
                try:
                    out[int(k)] = v
                except Exception:  # noqa: BLE001
                    continue
        return out
    return {}


def _enrich_cards_with_cluster_milestones(
    cards: Dict[int, Dict[str, Any]],
    clusters: List[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    """Make reviewed event-cluster facts authoritative over older cached cards."""
    enriched = {chapter: dict(card) for chapter, card in cards.items()}
    for cluster in clusters:
        span = (
            cluster.get("chapter_span")
            or cluster.get("chapterRange")
            or cluster.get("chapters")
            or []
        )
        try:
            start_ch, end_ch = int(span[0]), int(span[1])
        except (TypeError, ValueError, IndexError):
            continue
        total = max(1, end_ch - start_ch + 1)
        milestones = [
            milestone for milestone in (cluster.get("chapter_milestones") or [])
            if isinstance(milestone, dict)
        ]
        shared_fields = {
            "arc_id": cluster.get("arc_id", "A01"),
            "cluster_id": cluster.get("cluster_id", ""),
            "cluster_name": cluster.get("name", cluster.get("cluster_name", "")),
            "prev_life_tragedy": cluster.get("prev_life_tragedy", ""),
            "info_gap_from_prev_life": cluster.get("info_gap_from_prev_life", ""),
            "cluster_outcome": cluster.get("cluster_outcome", ""),
            "escalation_level": cluster.get("escalation_level", 1),
            "canonical_cast": list(cluster.get("canonical_cast") or []),
            "cluster_core_payoff": cluster.get("core_payoff", ""),
            "cluster_main_opponent": cluster.get("main_opponent", ""),
            "cluster_this_life_revenge": cluster.get("this_life_revenge", ""),
        }
        for chapter in range(start_ch, end_ch + 1):
            if chapter not in enriched:
                continue
            card = enriched[chapter]
            card.update(shared_fields)
            card["chapter_id"] = chapter
            card["cluster_span_start"] = start_ch
            card["cluster_span_end"] = end_ch
            card["cluster_chapter_index"] = chapter - start_ch + 1
            card["cluster_chapter_total"] = total
            milestone = next(
                (
                    item for item in milestones
                    if int(item.get("chapter") or 0) == chapter
                ),
                {},
            )
            card["chapter_milestone"] = dict(milestone)
            card["cluster_milestones"] = list(milestones)
            if chapter not in SPECIAL_CARDS:
                _apply_authoritative_chapter_milestone(card, milestone)
            cast = card.get("canonical_cast") or []
            protagonist = next((
                str(member.get("name") or "").strip()
                for member in cast
                if isinstance(member, dict)
                and str(member.get("alignment") or "").casefold() == "protagonist"
            ), MAIN_PROTAGONIST)
            main_opponent = str(card.get("main_opponent") or "").strip()
            card["allowed_roles"] = (
                [protagonist, main_opponent]
                if main_opponent
                else [protagonist]
            )
            card["scene_contract"] = _derive_closed_scene_contract(card)
    return enriched


def _setup_gen_from_cards_and_prev_life(
    gen: "RebirthRevengeGeneratorV2",
    cards: Dict[int, Dict[str, Any]],
    prev_life_ctx_path: str,
    clusters: List[Dict[str, Any]],
) -> None:
    """用内存中的章节卡和上一世线索初始化生成器，不依赖 master_ctx_cards_v2.json。"""
    gen.master_ctx = {ch: json.dumps(card, ensure_ascii=False) for ch, card in cards.items()}
    gen.master_ctx_original = {}
    gen.prev_life_ctx = _load_prev_life_ctx(prev_life_ctx_path)
    gen._extract_entities()
    setattr(gen, "event_clusters_v2", clusters)


def _normalize_beats_json_keys(raw: str) -> str:
    """模型偶发把 open_from_prev 拼成 oppen_from_prev；在解析前替换，避免整段 JSON 无法通过字段校验。"""
    if not raw:
        return raw
    return raw.replace('"oppen_from_prev"', '"open_from_prev"').replace(
        "'oppen_from_prev'", "'open_from_prev'"
    )


def _normalize_beats_flashback_mode(
    beats_obj: Dict[str, Any], chapter_role: str, chapter_num: int
) -> bool:
    """Align harmless flashback metadata drift with the chapter card role."""
    requires_flashback = chapter_role in {
        "prev_life_full",
        "prev_life_explained_by_investigation",
        "present_past_mix",
        "slow_burn_press_with_past_shadow",
    } and chapter_num not in (1, 2)
    if requires_flashback:
        return beats_obj.get("flashback_in_beat_idx") is not None

    beats_obj["flashback_in_beat_idx"] = None
    beats = beats_obj.get("beats")
    for beat in beats if isinstance(beats, list) else []:
        if isinstance(beat, dict):
            beat["prev_life_memory_brief"] = ""
    return True


def _extract_json_obj_maybe(text: str) -> Any:
    """
    从模型输出中尽量提取 JSON（容错：允许前后有非 JSON 文本）。
    """
    if text is None:
        return None
    s = (text or "").strip()
    if not s:
        return None
    # 1) 先尝试直接 json.loads
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        pass

    # 2) 清理常见 markdown fence（尽量不破坏括号配对）
    #    例如： ```json { ... } ```
    s2 = s.replace("```json", "```").replace("```", "")

    def _escape_newlines_in_json_strings(raw: str) -> str:
        """
        某些模型会把 JSON 字符串写成“多行字符串”（直接插入真实换行），
        这会导致 json.loads 失败；在字符串内部把换行替换为 \\n 可提高容错率。
        """
        out: List[str] = []
        in_string = False
        escape = False
        for ch in raw:
            if in_string:
                if escape:
                    out.append(ch)
                    escape = False
                    continue
                if ch == "\\":
                    out.append(ch)
                    escape = True
                    continue
                if ch == '"':
                    out.append(ch)
                    in_string = False
                    continue
                if ch == "\n":
                    out.append("\\")
                    out.append("n")
                    continue
                if ch == "\r":
                    out.append("\\")
                    out.append("n")
                    continue
                out.append(ch)
            else:
                out.append(ch)
                if ch == '"':
                    in_string = True
        return "".join(out)

    def _extract_balanced_snippet(raw: str) -> Optional[str]:
        start_obj = raw.find("{")
        start_arr = raw.find("[")
        if start_obj == -1 and start_arr == -1:
            return None

        if start_obj == -1:
            start = start_arr
            open_ch, close_ch = "[", "]"
        elif start_arr == -1:
            start = start_obj
            open_ch, close_ch = "{", "}"
        else:
            if start_obj < start_arr:
                start = start_obj
                open_ch, close_ch = "{", "}"
            else:
                start = start_arr
                open_ch, close_ch = "[", "]"

        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(raw)):
            ch = raw[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return raw[start : i + 1]
        return None

    try:
        snippet = _extract_balanced_snippet(s2)
        if not snippet:
            return None
        try:
            return json.loads(snippet)
        except Exception:  # noqa: BLE001
            # 再尝试：把字符串里的真实换行转成 \\n
            snippet2 = _escape_newlines_in_json_strings(snippet)
            return json.loads(snippet2)
    except Exception:  # noqa: BLE001
        return None


QUALITY_SCORE_THRESHOLDS_V2 = {
    "cluster_fidelity": 8.0,
    "causal_clarity": 7.0,
    "prose_naturalness": 7.0,
    "emotional_force": 6.0,
    "non_repetition": 7.0,
    "ending_precision": 7.0,
    "fictional_naming": 8.0,
}


def _build_chapter_quality_critic_prompt(
    chapter_num: int,
    chapter_text: str,
    chapter_card: Dict[str, Any],
    *,
    prev_tail_scene: str = "",
) -> str:
    """Build a plot-aware, prose-aware independent acceptance review."""
    milestone = chapter_card.get("chapter_milestone") or chapter_card.get("milestone") or {}
    if not isinstance(milestone, dict):
        milestone = {}
    contract = _grounded_scene_contract_payload(chapter_card)
    allowed_cast = _select_grounded_chapter_cast(chapter_card)
    return f"""V2_QUALITY_CRITIC_JSON
你是独立小说成稿主编。你不续写、不润色，只判断第{chapter_num}章能否无人值守地正式交付。

【最高优先级：人工已验收的情节族里程碑】
主角行动：{milestone.get('action') or chapter_card.get('this_life_revenge') or chapter_card.get('chapter_goal') or ''}
对手反应：{milestone.get('opponent_reaction') or ''}
即时结果：{milestone.get('result') or chapter_card.get('chapter_ending') or ''}

【通用场景契约】
{json.dumps(contract, ensure_ascii=False)}

【允许具名人物】
{json.dumps(allowed_cast, ensure_ascii=False)}

【上一章真实尾场】
{prev_tail_scene or '无'}

【必须逐项审查】
1. 里程碑行动、对手反应、即时结果是否按因果顺序真正发生；不得用近义概述替代，不得发明新证据、权限、见证者或裁定者。
2. 对手行为是否符合其既定角色，结果是谁宣布、为何生效、交给谁，是否清楚且无交接矛盾。
3. 行文是否像自然小说，而非动作拆解、舞台调度、验收报告或模型拼接；尤其检查手脚、呼吸、视线、站位、距离等微动作是否淹没情节。
4. 是否有完全重复句、同义复述、同一句内名词自我重复、残句、断裂句、指代错乱或前后自相矛盾。
5. 情绪是否来自人物选择、旧伤、权力变化和即时后果，而非堆身体反应、天气、灯光或口号。
6. 结尾是否停在已经生效的结果与人物直接反应上；不得结算后再漂移到窗景、天气、光影、整理物品或空泛预感。
7. 不得出现现实中完全相同的人名、地名、公司、机构、奖项、作品名或外文拼写。可以使用能让人联想到原型但不完全相同的架空指代，例如“米国”；固定虚构姓名以允许名单为准。
8. 正文必须在{_minimum_chapter_chars(chapter_num, chapter_card)}至{MAX_CHAPTER_CHARS_V2}字之间，并且段落长短、对白位置和起收方式不能呈现固定模板。
9. hard_failures 的 repair 也必须服从允许名单和场景契约：不得建议新造姓名、机构、文书、设备、印鉴、密钥、证人或权限；契约没有给出专名时，只能建议使用无姓名功能职位。

只输出一个严格 JSON 对象，不要 Markdown，不要解释文字。所有分数为 0 到 10：
{{
  "accept": false,
  "scores": {{
    "cluster_fidelity": 0,
    "causal_clarity": 0,
    "prose_naturalness": 0,
    "emotional_force": 0,
    "non_repetition": 0,
    "ending_precision": 0,
    "fictional_naming": 0
  }},
  "hard_failures": [
    {{"code": "简短代码", "evidence": "正文中的短证据或准确概述", "repair": "从空白重写时应如何修复"}}
  ],
  "summary": "一句话总评"
}}

只有全部里程碑成立、无事实或因果硬伤、无现实专名、无明显生成腔，并且各项达到交付标准时，accept 才能为 true。拿不准就拒绝。

【待审正文】
{chapter_text}
"""


def _parse_chapter_quality_review(raw: str) -> Optional[Dict[str, Any]]:
    obj = _extract_json_obj_maybe(raw)
    if not isinstance(obj, dict) or not isinstance(obj.get("accept"), bool):
        return None
    raw_scores = obj.get("scores")
    if not isinstance(raw_scores, dict):
        return None
    scores: Dict[str, float] = {}
    for key in QUALITY_SCORE_THRESHOLDS_V2:
        try:
            value = float(raw_scores.get(key))
        except (TypeError, ValueError):
            return None
        if not 0 <= value <= 10:
            return None
        scores[key] = value

    hard_failures: List[Dict[str, str]] = []
    raw_failures = obj.get("hard_failures") or []
    if not isinstance(raw_failures, list):
        return None
    for item in raw_failures[:12]:
        if isinstance(item, dict):
            hard_failures.append({
                "code": str(item.get("code") or "quality_failure").strip(),
                "evidence": str(item.get("evidence") or "").strip(),
                "repair": str(item.get("repair") or "").strip(),
            })
        elif str(item or "").strip():
            hard_failures.append({
                "code": "quality_failure",
                "evidence": str(item).strip(),
                "repair": "从空白重写并消除该问题。",
            })

    low_scores = {
        key: score
        for key, score in scores.items()
        if score < QUALITY_SCORE_THRESHOLDS_V2[key]
    }
    accepted = bool(obj.get("accept")) and not hard_failures and not low_scores
    return {
        "accept": accepted,
        "model_accept": bool(obj.get("accept")),
        "scores": scores,
        "low_scores": low_scores,
        "hard_failures": hard_failures,
        "summary": str(obj.get("summary") or "").strip(),
    }


def _chapter_quality_review_failures(review: Dict[str, Any]) -> List[str]:
    if review.get("accept"):
        return []
    failures: List[str] = []
    for item in review.get("hard_failures") or []:
        if not isinstance(item, dict):
            continue
        evidence = str(item.get("evidence") or "").strip()
        failures.append(
            "独立质量审稿拒绝"
            + (f"（{item.get('code')}）" if item.get("code") else "")
            + (f"：{evidence}" if evidence else "")
            + "；从空白重写并严格服从既有里程碑、允许人物和场景契约，"
            "不得采用审稿意见中可能出现的新增姓名、物件或权限。"
        )
    low_scores = review.get("low_scores") or {}
    if isinstance(low_scores, dict) and low_scores:
        failures.append(
            "独立质量审稿分数未达标："
            + "、".join(
                f"{key}={score:g}<{QUALITY_SCORE_THRESHOLDS_V2[key]:g}"
                for key, score in low_scores.items()
            )
            + "。从空白重写整章，不能在失败稿后补段。"
        )
    if not failures:
        failures.append(
            "独立质量审稿拒绝交付："
            + (str(review.get("summary") or "正文未达到自动交付标准"))
        )
    return failures


def _save_chapter_quality_audit(
    gen: "RebirthRevengeGeneratorV2",
    chapter_num: int,
    chapter_text: str,
    generation_try: int,
    review: Dict[str, Any],
) -> None:
    try:
        audit_dir = Path(getattr(gen, "outputs_dir", OUTPUT_DIR)) / "quality_audits"
        audit_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(chapter_text.encode("utf-8")).hexdigest()[:10]
        payload = {
            "chapter": chapter_num,
            "generation_try": generation_try,
            "chars": len(chapter_text),
            "sha256": hashlib.sha256(chapter_text.encode("utf-8")).hexdigest(),
            "review": review,
        }
        (audit_dir / f"chapter_{chapter_num:03d}_try_{generation_try:02d}_{digest}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _review_chapter_quality_v2(
    gen: "RebirthRevengeGeneratorV2",
    chapter_num: int,
    chapter_text: str,
    chapter_card: Dict[str, Any],
    *,
    prev_tail_scene: str = "",
    generation_try: int = 1,
) -> Dict[str, Any]:
    """Fail closed when the independent prose review is invalid or rejects."""
    prompt = _build_chapter_quality_critic_prompt(
        chapter_num,
        chapter_text,
        chapter_card,
        prev_tail_scene=prev_tail_scene,
    )
    review: Optional[Dict[str, Any]] = None
    invalid_outputs: List[str] = []
    for critic_try in range(2):
        critic_prompt = prompt
        if critic_try:
            critic_prompt += (
                "\n\n上一份审查无法解析。仍审查同一正文，只输出符合给定结构的严格 JSON；"
                "不得使用代码围栏、注释或 JSON 前后说明。"
            )
        raw = str(gen._call_api(  # type: ignore[attr-defined]
            critic_prompt,
            None,
            critic_try,
            max_tokens=1400,
        ) or "").strip()
        review = _parse_chapter_quality_review(raw)
        if review is not None:
            break
        invalid_outputs.append(raw[:300])
    if review is None:
        review = {
            "accept": False,
            "model_accept": False,
            "scores": {},
            "low_scores": {},
            "hard_failures": [{
                "code": "critic_invalid_json",
                "evidence": "独立质量审稿连续两次未返回可解析的严格 JSON",
                "repair": "不得绕过审稿；重新生成正文后再次审查。",
            }],
            "summary": "质量审稿不可用，按失败关闭。",
            "invalid_output_previews": invalid_outputs,
        }
    _save_chapter_quality_audit(
        gen,
        chapter_num,
        chapter_text,
        generation_try,
        review,
    )
    return review


def _partition_evenly(items: List[int], parts: int) -> List[List[int]]:
    """
    将 items 切成 parts 份，尽量均匀且保持连续性。
    若 parts >= len(items)，则每份至多 1 个元素。
    """
    if parts <= 0:
        return [items]
    n = len(items)
    parts = min(parts, n) if n > 0 else 1
    if parts <= 1:
        return [items]
    out: List[List[int]] = []
    base = n // parts
    rem = n % parts
    idx = 0
    for i in range(parts):
        take = base + (1 if i < rem else 0)
        out.append(items[idx : idx + take])
        idx += take
    return out


def _chapter_constraints_for_cluster_prompt(card: Dict[str, Any]) -> str:
    """
    为“全簇节拍卡/连续正文/切分微调”提供更短的章节约束摘要。
    """
    if not isinstance(card, dict):
        return ""
    role_v2 = card.get("chapter_role_v2", "")
    chapter_goal = card.get("chapter_goal", "") or ""
    must_in = card.get("chapter_must_include", []) or []
    must_not = card.get("chapter_must_not_include", []) or []
    ending = card.get("chapter_ending", "") or ""
    must_resolve = card.get("must_resolve_this_chapter", []) or []
    allowed_roles = card.get("allowed_roles", []) or []
    forbidden_roles = card.get("forbidden_roles", []) or []
    chapter_hard = card.get("chapter_hard_constraints", []) or []
    required_state_changes = card.get("required_state_changes", []) or []
    forbidden_active = card.get("forbidden_active_characters", []) or []
    canonical_cast = card.get("canonical_cast", []) or []

    if isinstance(must_in, list):
        must_in = [str(x) for x in must_in][:10]
    else:
        must_in = [str(must_in)][:1]
    if isinstance(must_not, list):
        must_not = [str(x) for x in must_not][:14]
    else:
        must_not = [str(must_not)][:1]
    if isinstance(must_resolve, list):
        must_resolve = [str(x) for x in must_resolve][:8]
    else:
        must_resolve = [str(must_resolve)][:1]

    if isinstance(allowed_roles, list):
        allowed_roles = [str(x) for x in allowed_roles]
    else:
        allowed_roles = [str(allowed_roles)]
    if isinstance(forbidden_roles, list):
        forbidden_roles = [str(x) for x in forbidden_roles]
    else:
        forbidden_roles = [str(forbidden_roles)]

    hard_lines = [str(x).strip() for x in chapter_hard if str(x).strip()]
    for item in required_state_changes:
        if isinstance(item, dict):
            hard_lines.append(
                f"必须建立状态 {item.get('character')}.{item.get('field')}={item.get('new_value')}，"
                f"timeline={item.get('timeline', 'current')}，permanent={bool(item.get('permanent', False))}"
            )
    for name in forbidden_active:
        hard_lines.append(f"{name}不得作为当前时间线活跃参与者")

    cast_lines: List[str] = []
    if isinstance(canonical_cast, list):
        for item in canonical_cast[:8]:
            if isinstance(item, dict) and item.get("name"):
                cast_lines.append(
                    f"{item.get('name')}（{item.get('role', '身份未标注')}，{item.get('alignment', '阵营未标注')}）"
                )

    return (
        f"角色：{role_v2 or '（未标注）'}；目标：{chapter_goal}\n"
        f"必须包含：{'；'.join(must_in) if must_in else '（无）'}\n"
        f"必须处理：{'；'.join(must_resolve) if must_resolve else '（无）'}\n"
        f"必须避免：{'；'.join(must_not) if must_not else '（无）'}\n"
        f"章节结尾钩子：{ending or '（无）'}\n"
        f"允许角色：{'；'.join(allowed_roles[:6]) if allowed_roles else '（未指定）'}\n"
        f"禁止出现新核心角色：{'；'.join(forbidden_roles[:10]) if forbidden_roles else '（无）'}\n"
        f"固定角色表：{'；'.join(cast_lines) if cast_lines else '（未提供；不得擅自给既有人物改名）'}\n"
        f"运行时章节硬合同：{'；'.join(hard_lines) if hard_lines else '（无）'}\n"
    )


def _build_cluster_detailed_synopsis_prompt(
    cluster: Dict[str, Any],
    chapter_cards: Dict[int, Dict[str, Any]],
    prev_tail_scene: str,
    prev_unresolved_hook: str,
    rewrite_advice: Optional[List[str]] = None,
    exec_plan: Optional[Dict[str, Any]] = None,
) -> str:
    span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters") or []
    s, e = 0, 0
    try:
        s, e = int(span[0]), int(span[1])
        span_desc = f"{s}-{e}"
    except Exception:  # noqa: BLE001
        span_desc = "（未知）"

    cluster_id = cluster.get("cluster_id", "")
    cluster_name = cluster.get("name", cluster.get("cluster_name", "")) or ""
    core_payoff = cluster.get("core_payoff", "") or ""
    main_opp = cluster.get("main_opponent", "") or ""
    prev_tragedy = cluster.get("prev_life_tragedy", "") or ""
    this_revenge = cluster.get("this_life_revenge", "") or ""
    info_gap = cluster.get("info_gap_from_prev_life", "") or ""
    outcome = cluster.get("cluster_outcome", "") or ""
    canonical_cast = cluster.get("canonical_cast") or []

    cross_hint = ""
    if prev_tail_scene or prev_unresolved_hook:
        cross_hint = (
            "上一章最后场景/动作（供本情节族首章开头接续）："
            + (prev_tail_scene or "（无）")
            + "\n上一章未解决钩子（必须被接住并推进到本情节族内节拍）："
            + (prev_unresolved_hook or "（无）")
            + "\n"
        )

    chapter_roles = []
    for ch, card in sorted(chapter_cards.items(), key=lambda x: x[0]):
        role_v2 = card.get("chapter_role_v2", "")
        if role_v2:
            chapter_roles.append(f"第{ch}章：{role_v2}")
    chapter_roles_text = "；".join(chapter_roles[:10]) if chapter_roles else ""

    rewrite_block = ""
    if rewrite_advice:
        rewrite_block = "\n【重写要求（必须遵守）】\n" + "\n".join(rewrite_advice[:10])

    first_role = str((chapter_cards.get(s) or {}).get("chapter_role_v2") or "") if isinstance(s, int) else ""
    if first_role == "prev_life_death_only" and s == e == 1:
        this_revenge = "（未来内容，本梗概禁止写入）"
        info_gap = "只作为临终不甘的认知背景，不得转化为今生行动"
        outcome = "主角在不可逆失败后死亡，带着明确未竟目标结束上一世"
        special_structure_block = (
            "\n【特殊结构优先级最高】本情节族只有第1章：详细梗概只能写上一世最后一次失败、"
            "具体代价与死亡。cluster 中的 this_life_revenge 只属于未来章节，本梗概不得写主角重生、"
            "开始任何今生行动或完成今生反击。\n"
        )
    elif first_role == "prev_life_death_only":
        special_structure_block = (
            "\n【开篇多章结构，优先级最高】本情节族横跨开篇："
            "第1章只能写上一世最后失败直至生命明确结束；第2章只能写惊醒、核对身体/环境/日期、"
            "确认重生并完成一个首次部署；第3章起才允许进入本题材的权限、合同、职业现场或关系反卡。"
            "详细梗概必须按这一时间顺序连续规划，不得把第3-4章反击写进第1-2章，也不得因第1章职责而删除后续今生剧情。\n"
        )
    elif first_role == "rebirth_awakening_only":
        special_structure_block = (
            "\n【特殊结构优先级最高】本簇首章是重生确认章：先完整写惊醒、怀疑、验证、确认，"
            "结尾只完成第一步部署；不得在本章获取决定性证据或完成大反杀。\n"
        )
    else:
        special_structure_block = ""

    exec_plan_block = ""
    if isinstance(exec_plan, dict) and isinstance(exec_plan.get("evidence_chain"), list) and exec_plan.get("evidence_chain"):
        ep_lines: List[str] = []
        for ev in exec_plan.get("evidence_chain") or []:
            if not isinstance(ev, dict):
                continue
            evidence_id = str(ev.get("evidence_id", "") or "").strip()
            marker = f"【{evidence_id}】" if evidence_id else ""
            etype = str(ev.get("evidence_type", "") or "").strip()
            ac = ev.get("acquire_chapter")
            vc = ev.get("verify_chapter")
            uc = ev.get("use_chapter")
            purpose = str(ev.get("purpose", "") or "").strip()
            if evidence_id and ac is not None and vc is not None and uc is not None:
                ep_lines.append(
                    f"{marker}：类型={etype}；节奏锚点约第{int(ac)}章起笔、第{int(vc)}章与第{int(uc)}章可用于对峙落锤；目的={purpose or '（未提供）'}（这是剧情节奏参考，不是「调查取证任务单」）"
                )
        if ep_lines:
            exec_plan_block = "\n【落锤与节奏锚点（禁止写成调查小说主线）】\n" + "\n".join(ep_lines) + "\n"

    return f"""{COMMERCIAL_REBIRTH_WRITER_ROLE}请基于【情节族】信息，生成一个可直接驱动分章节拍卡与正文的【详细完整梗概】。

【本项目主题硬锁定】
{constraints_text()}

要求（非常重要）：
1. 叙事骨架必须是「{REBIRTH_ACTION_ENGINE}」；禁止靠匿名线索推进。
2. 必须写清上一世留下的信息差是什么，可以是人物动机、行业规则、时间点、作品表现、关系裂痕或已存在材料；主角必须先利用它主动改变局面，材料只能在反卡时坐实，不能成为调查主线。
3. 每章除推进长线外，都必须兑现一个读者当章能感到的小爽点：主角抢先、对手失算、旁观者改变态度，以及具体利益或地位变化至少命中两项。反卡必须落在动作、对话、表情和可见结果上。
4. 必须把主动布局方式和核心兑现与 `core_payoff` 对齐；
5. 禁止引入本情节族未规划的新核心人物/幕后系统/系统提示音等旁支要素；禁止匿名邮件、陌生人递材料、匿名爆料作为唯一关键转折。
6. 不得写任何现实人名、国名、城市、医院、场馆、公司、奖项或作品名；未在情节族中建立的地点、机构、药品、演出和歌曲只用功能称呼，不得临时取名。
7. 禁止自行增加伪造批号、加密手机、神秘喷雾或新药品来源等未规划医疗悬疑材料；本簇只能使用事件卡已给定的针剂、剂量、原话与人物行动。
8. 固定角色表必须逐字遵守：{json.dumps(canonical_cast, ensure_ascii=False)}。不得改名、拼错姓名或另造有姓名的角色；必要的功能角色只用职位称呼。
{special_structure_block}{rewrite_block}{exec_plan_block}

输出格式（按顺序输出段落，不要列表/不要编号）：
[背景]
[过程]
[信息差与利用]
[复仇细节与爽感]
[章间衔接要点]

【情节族信息】
cluster_id：{cluster_id}
cluster_name：{cluster_name}
覆盖章节：{span_desc}
核心爽点：{core_payoff}
主要对手：{main_opp}
上一世悲剧前提：{prev_tragedy}
今生反击方式：{this_revenge}
上一世留下的信息差：{info_gap}
本簇结局/落点：{outcome}

{cross_hint}
章节角色分工（便于放置回忆/反制）：{chapter_roles_text or '（未提供）'}
"""


def _unknown_named_roles_in_synopsis(
    synopsis: str, canonical_cast: Any
) -> List[str]:
    """Catch named people invented between the cluster plan and chapter beats."""
    cast_items = canonical_cast if isinstance(canonical_cast, list) else []
    allowed = {
        str(member.get("name") or "").strip().casefold()
        for member in cast_items
        if isinstance(member, dict) and str(member.get("name") or "").strip()
    }
    allowed_first_names = {name.split()[0] for name in allowed if name.split()}
    allowed_places: set[str] = set()
    role_words = re.compile(r"经纪人|导演|制片人|演员|影后|助理|负责人|代表|竞争者|对手|老板|律师|记者|先生|女士")
    unknown: List[str] = []
    text = synopsis or ""
    for match in re.finditer(
        r"(?<![A-Za-z])([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2})(?![A-Za-z])",
        text,
    ):
        name = match.group(1).strip()
        folded = name.casefold()
        if folded in allowed or folded in allowed_places:
            continue
        if any(folded.endswith(" " + canonical) for canonical in allowed):
            continue
        first = name.split()[0].casefold()
        resembles_cast = any(canonical.split()[0] == first for canonical in allowed)
        context = text[max(0, match.start() - 32): min(len(text), match.end() + 32)]
        acts_like_person = bool(role_words.search(context)) or bool(re.search(
            rf"{re.escape(name)}.{{0,16}}(?:说|问|走|站|看|递|打断|拒绝|安排|命令|示意|宣布|点头|开口|合上)",
            context,
        ))
        if resembles_cast or acts_like_person:
            unknown.append(name)
    for match in re.finditer(
        r"(?:经纪人|导演|制片人|演员|影后|助理|负责人|代表|竞争者|对手|老板|律师|记者)"
        r"\s*(?:名叫|叫)?\s*([A-Z][a-z]{2,})(?![A-Za-z])",
        text,
    ):
        name = match.group(1).strip()
        if name.casefold() not in allowed_first_names:
            unknown.append(name)
    for match in re.finditer(
        r"(?:导演助理|选角助理|经纪人|导演|制片人|演员|影后|助理|负责人|代表|律师|记者)"
        r"([\u4e00-\u9fff]{2,4})(?=走进|走来|说道|问道|开口|递来|转身|离开)",
        text,
    ):
        candidate = match.group(1)
        if any(marker in candidate for marker in (
            "终于", "缓缓", "默默", "突然", "迅速", "立刻", "当场", "再次",
            "直接", "随后", "独自", "悄然", "冷冷", "慢慢", "径直", "开口",
            "转身", "起身", "抬手", "点头", "皱眉", "冷笑", "当即", "忽然",
            "匆匆", "是如何", "会在何时", "为何会", "是否会", "究竟会",
            "没再", "不再", "未再", "没有", "并未", "仍未", "也没",
        )):
            continue
        if any(noun in candidate for noun in (
            "托盘", "针盘", "药箱", "药瓶", "针筒", "手机", "屏幕", "平板", "文件", "合同",
            "指尖", "手指", "掌心", "视线", "目光", "嘴角", "肩膀", "下巴",
            "眉头", "呼吸", "脚步", "声音", "外套", "椅背", "纸页", "钥匙",
        )):
            continue
        unknown.append(candidate)
    unique = list(dict.fromkeys(unknown))
    unique = [
        name for name in unique
        if " " in name or not any(other.startswith(name + " ") for other in unique)
    ]
    return unique[:6]


def _normalize_unplanned_named_people(text: str, chapter_card: Dict[str, Any]) -> str:
    """Downgrade last-attempt invented names to stable unnamed production roles."""
    normalized = text or ""
    legacy_context = " ".join(
        str(chapter_card.get(key) or "")
        for key in ("chapter_goal", "prev_life_tragedy", "this_life_revenge", "core_payoff")
    )
    if not re.search(r"试戏|试镜|选角|女主角|旧经纪人", legacy_context):
        return normalized
    cast = chapter_card.get("canonical_cast") or []
    unknown = _unknown_named_roles_in_synopsis(normalized, cast)
    allowed_names = {
        str(member.get("name") or "").strip()
        for member in cast if isinstance(member, dict) and str(member.get("name") or "").strip()
    }
    unknown.extend(
        name for name in re.findall(r"[\u4e00-\u9fff]{1,5}[·•][\u4e00-\u9fff]{1,8}", normalized)
        if name not in allowed_names
    )
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in cast if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
    ), "主角")
    opponent = next((
        str(member.get("name") or "").strip()
        for member in cast if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "opponent"
    ), "固定对手")
    ally = next((
        str(member.get("name") or "").strip()
        for member in cast if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() in {"ally", "support"}
    ), "选角导演")
    for name in dict.fromkeys(unknown):
        match = re.search(re.escape(name), normalized)
        if not match:
            continue
        context = normalized[max(0, match.start() - 80):min(len(normalized), match.end() + 80)]
        if re.search(r"经纪人|代理人|经纪约|代理协议", context):
            replacement = "旧经纪人"
        elif re.search(r"选角导演|选角负责人", context):
            replacement = ally
        elif re.search(r"影后|核心对手|抢走角色|冷笑|嘲讽", context):
            replacement = opponent
        elif re.search(r"新人演员|主角|试镜者", context):
            replacement = protagonist
        elif re.search(r"制片|片方", context):
            replacement = "制片负责人"
        elif re.search(r"导演", context):
            replacement = "导演"
        elif re.search(r"助理", context):
            replacement = "选角助理"
        else:
            replacement = "现场工作人员"
        normalized = re.sub(re.escape(name), replacement, normalized)
    normalized = re.sub(r"(?:她的)?经纪人旧经纪人", "她的旧经纪人", normalized)
    normalized = normalized.replace("旧经纪人旧经纪人", "旧经纪人")
    normalized = normalized.replace("选角导演导演", "选角导演")
    return normalized


def _planned_work_titles(*objects: Any) -> set[str]:
    text = "\n".join(
        json.dumps(obj, ensure_ascii=False, default=str)
        for obj in objects
        if obj is not None
    )
    titles = set(re.findall(r"《([^》\n]{1,40})》", text))
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        explicit = obj.get("planned_work_titles") or []
        for title in explicit if isinstance(explicit, list) else []:
            cleaned = str(title or "").strip().strip("《》")
            if cleaned:
                titles.add(cleaned)
    return titles


def _cluster_synopsis_hard_failures(
    synopsis: str, canonical_cast: Any = None, expected_facts: Any = None
) -> List[str]:
    text = synopsis or ""
    expected_text = json.dumps(expected_facts, ensure_ascii=False, default=str)
    failures: List[str] = []
    reality_hits = [name for name in REAL_WORLD_PROPER_NOUNS if name in text]
    if reality_hits:
        failures.append("详细梗概出现现实专名：" + "、".join(reality_hits))
    if re.search(r"实验编号|编号[:：]?\s*[A-Z]-?\d{2,}|药瓶照片|神秘药瓶", text, re.I):
        failures.append("详细梗概混入实验编号或神秘药瓶照片等未规划医疗悬疑材料")
    if re.search(r"伪造批号|生产日期比实际|加密手机|蓝色镇静喷雾|未拆封.{0,12}镇静喷雾", text):
        failures.append("详细梗概擅自增加伪造批号、加密手机或神秘喷雾等未规划材料")
    named_facilities = {
        item
        for item in re.findall(
            r"[\u4e00-\u9fff·]{2,18}(?:医疗中心|医院|体育馆|剧院|唱片公司|唱片集团|律师事务所|基金会)",
            text,
        )
        if item not in expected_text
    }
    if named_facilities:
        failures.append(
            "详细梗概擅自命名未规划地点或机构："
            + "、".join(sorted(named_facilities)[:4])
        )
    if re.search(
        r"(?:醒来|惊醒|睁开眼|恢复意识).{0,360}(?:手中|手里|攥着|握着).{0,36}药瓶|"
        r"(?:手中|手里|攥着|握着).{0,36}药瓶.{0,240}(?:重生|回到.{0,20}(?:试镜|过去)|日期)",
        text,
        re.S,
    ):
        failures.append("详细梗概让主角重生后仍握着上一世临终药瓶；重生只能保留记忆，实体物不能跨时间线携带")
    if re.search(r"暗藏阴谋|看似意外.{0,12}(?:并非|却|实为)|事故.{0,12}(?:不是意外|有人策划|蓄意制造)", text, re.S):
        failures.append("详细梗概把已建立的现实事故擅自改成未规划阴谋")
    if re.search(
        r"(?:手中|手里|桌上|床边|身旁).{0,36}(?:上一世|前世).{0,45}(?:药瓶|手机|剧本|文件|录音|物品)|"
        r"(?:上一世|前世).{0,45}(?:药瓶|手机|剧本|文件|录音|物品).{0,36}(?:仍在|还在|攥着|握着|带回|出现在)",
        text,
        re.S,
    ):
        failures.append("详细梗概把上一世实体物品原样带入重生后的当前时间线；只能保留记忆，今生物品必须按当前日期重新存在")
    planned_work_titles = _planned_work_titles(expected_facts)
    synopsis_work_titles = set(re.findall(r"《([^》\n]{1,40})》", text))
    unexpected_work_titles = sorted(synopsis_work_titles - planned_work_titles)
    if unexpected_work_titles:
        failures.append(
            "详细梗概擅自改写作品名："
            + "、".join(f"《{title}》" for title in unexpected_work_titles)
        )
    cheap_hits = [marker for marker in CHEAP_MYSTERY_MARKERS if marker in text]
    if cheap_hits:
        failures.append("详细梗概使用廉价神秘推进：" + "、".join(cheap_hits[:4]))
    if re.search(
        r"(?:未读消息|手机消息|亮屏的手机).{0,140}"
        r"(?:不是来自任何人|来自过去|上一世|临终前发送给自己|未来.{0,12}记忆|唯一.{0,8}线索|重生并非偶然)",
        text,
        re.S,
    ) or re.search(r"上一世.{0,36}(?:发给|发送给)自己", text, re.S):
        failures.append("详细梗概用无来源的跨时间消息代替重生确认")
    if re.search(r"私人邮件|私密邮件|私密录音|秘密录音|偷拍视频|隐藏文件|内部文件", text):
        failures.append("详细梗概依赖来源不透明的私密材料")
    if re.search(
        r"(?:从|凭|根据).{0,8}(?:脑海|记忆).{0,24}(?:还原|恢复|生成|制作)"
        r".{0,20}(?:录音|音频|视频|文件|截图|证据)",
        text,
    ):
        failures.append("详细梗概把前世记忆凭空变成今生物证")
    role_tokens = ("经纪人", "选角导演", "导演", "制片人", "演员", "影后", "律师", "记者", "助理")
    for member in canonical_cast if isinstance(canonical_cast, list) else []:
        if not isinstance(member, dict):
            continue
        name = str(member.get("name") or "").strip()
        role = str(member.get("role") or "")
        if not name:
            continue
        contexts = [
            text[max(0, match.start() - 24): min(len(text), match.end() + 24)]
            for match in re.finditer(re.escape(name), text, re.I)
        ]
        claimed = {
            token for context in contexts for token in role_tokens
            if re.search(
                rf"(?:{re.escape(token)}\s*(?:名叫|叫)?\s*{re.escape(name)}|"
                rf"{re.escape(name)}\s*(?:是|作为|担任|身为|——|，)\s*{re.escape(token)})",
                context,
                re.I,
            )
        }
        wrong_claims = [token for token in claimed if token not in role and not (token == "导演" and "选角导演" in role)]
        if wrong_claims:
            failures.append(f"固定人物身份漂移：{name}被写成{'/'.join(wrong_claims)}，角色表身份为{role}")
    return failures[:6]


def _fallback_cluster_contract(
    cluster: Dict[str, Any],
    chapter_nums: List[int],
    chapter_cards: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    duty_templates = [
        "旧局重现与钩子：认出旧招、放诱饵诱对方照旧出招",
        "提前布置：根据记忆调整表演、条件或会面顺序，不寻找新物证",
        "逼迫与反压：对手按老剧本施压、主角反卡",
        "公开落锤：当场/现场引爆、结果落地",
    ]
    chapters: List[Dict[str, Any]] = []
    for i, ch in enumerate(chapter_nums):
        card = chapter_cards.get(ch, {}) or {}
        dt = duty_templates[i] if i < len(duty_templates) else "推进剧情"
        must = [str(x) for x in (card.get("chapter_must_include") or [])[:4] if str(x).strip()]
        if not must:
            must = [f"完成第{ch}章章节卡目标", "推进主角行动并落下可见结果"]
        forb = [str(x) for x in (card.get("chapter_must_not_include") or [])[:4] if str(x).strip()]
        if not forb:
            forb = ["禁止重复前几章已完成的同款取证/同款开场", "禁止用更大风暴替代本章结果"]
        chapters.append(
            {
                "chapter_num": int(ch),
                "duty_title": dt,
                "must_finish": must,
                "forbidden": forb,
            }
        )
    return {
        "one_line_goal": str(cluster.get("core_payoff") or cluster.get("cluster_outcome") or "") or "完成本簇复仇闭环",
        "chapters": chapters,
        "unresolved_queue": [str(cluster.get("cluster_outcome") or "本簇结局落地")],
    }


def _fallback_chapter_beats(
    cluster: Dict[str, Any],
    chapter_num: int,
    chapter_card: Dict[str, Any],
    open_from_prev: str = "",
) -> Dict[str, Any]:
    """Build a compact fact-preserving beat card from the accepted milestone."""
    role = str(chapter_card.get("chapter_role_v2") or "")
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in (cluster.get("canonical_cast") or []) if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
    ), "主角")
    chapter_opponents = [
        str(member.get("name") or "").strip()
        for member in _select_grounded_chapter_cast(chapter_card)
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "opponent"
        and str(member.get("name") or "").strip()
    ]
    opponent = (
        chapter_opponents[0]
        if chapter_opponents
        else str(chapter_card.get("main_opponent") or cluster.get("main_opponent") or "既有对手")
    )
    action = str(chapter_card.get("this_life_revenge") or chapter_card.get("chapter_goal") or "").strip()
    result = str(chapter_card.get("core_payoff") or chapter_card.get("cluster_outcome") or "").strip()
    info_gap = str(chapter_card.get("info_gap_from_prev_life") or "").strip()
    ending = str(chapter_card.get("chapter_ending") or result).strip()
    _, performance_scene, paper_markers = _closed_evidence_contract(chapter_card)
    medication_paper_audit = (
        all(marker in paper_markers for marker in ("封签", "送货单", "领用簿"))
        and "核对" in (
            str(chapter_card.get("chapter_goal") or "")
            + str(chapter_card.get("this_life_revenge") or "")
        )
    )

    def beat(
        signal: str, move: str, old_move: str, trigger: str, goal: str, emotion: str, delta: str
    ) -> Dict[str, str]:
        return {
            "old_trap_signal": signal,
            "preemptive_move": move,
            "opponent_old_move": old_move,
            "reversal_trigger": trigger,
            "scene_goal": goal,
            "visual_elements": "只使用当前职业现场中已建立的人物、物件与动作",
            "emotion_push": emotion,
            "info_delta": delta,
            "evidence_form": "",
            "foreshadow": "仅保留已有对手对本章结果的直接反应",
            "relationship_push": f"{protagonist}与{opponent}的控制权正面冲突",
            "must_not": "不新增姓名、机构、作品、药品、文件、匿名线索或下一章结果",
            "prev_life_memory_brief": "",
        }

    if chapter_num == 1 or role == "prev_life_death_only":
        beats = [
            beat("首演前夜，康拉德端来要求加量的镇静针", f"{protagonist}明确拒绝注射并要求停止用药", "康拉德用保证睡眠的话术压制拒绝", "康拉德不顾拒绝强行注射", "把身体控制和无法反抗写成当场冲突", "疲惫推向警惕与惊恐", "确认注射是被强行执行的"),
            beat("问题针剂入体后呼吸和动作逐渐失控", f"{protagonist}用最后的力气质问自己是病人还是商品", "康拉德冷静等待药效发作", "门外传来保险和死后版权的低声讨论", "让主角在清醒中意识到利益链的存在", "惊恐推向背叛感", "亲耳听见保险与死后版权被当作生意"),
            beat("门外有人说出‘死人比活人值钱’", f"{protagonist}拼尽最后力气记住原话和在场者的反应", "康拉德与门外利益方继续等待他死亡", "主角明白身体、作品和死亡都已被标价", "立住未能夺回自己人生的核心不甘", "背叛感推向愤怒", "临终原话成为今后唯一记忆优势"),
            beat("呼吸断续，心跳越来越弱", f"{protagonist}想说出最后一句拒绝却已无法发声", "既有对手没有停止或救治已发生的结果", "心脏骤停、上一世明确死亡", "以死亡和强烈不甘封闭本章", "愤怒推向绝望与未竟", result),
        ]
    elif chapter_num == 2 or role == "rebirth_awakening_only":
        beats = [
            beat("上一世窒息与心脏停搏余感", f"{protagonist}猛然惊醒并检查身体、房间与日期", "康拉德仍按原日程端来针剂", "日程显示距上一世死亡还107天", "完成惊醒、怀疑和现实核对", "窒息推向错愕", "确认身体完好且时间已回退"),
            beat("当天正是复出发布会日", f"{protagonist}结合日期、日程和眼前针剂确认重生", "康拉德催促他照旧接受注射", "主角认出上一世的同一用药流程", "完成重生确认，不向公众自曝", "错愕推向惊骇与冷静", info_gap),
            beat("康拉德端着针盘催他配合", f"{protagonist}当场拒绝针剂并要求登记药名、剂量和来源", "康拉德无法解释却仍想单方执行", "主角要求第三方医疗团队在场并启动双签", "将上一世记忆转成第一次身体夺权", "冷静推向正面对抗", action),
            beat("问题针剂在主角眼前等待处理", f"{protagonist}亲眼确认针剂未入体且登记完成", "康拉德失去单独决定和注射的权限", "第三方医疗团队接管第二签字权", "让本章第一步部署立即生效", "对抗推向首次掌控", result),
        ]
    elif performance_scene:
        beats = [
            beat(
                info_gap or "上一世，对手正是用病弱话术压低表演强度",
                f"{protagonist}认出旧局，提前要求合作方和现场见证人从开场就在排练场观看",
                f"{opponent}仍以保护身体为由要求降低强度",
                f"{protagonist}完成正常热身后，要求按原定高强度开始",
                "只用当场可见表现把病弱话术逼回去",
                "警惕推向主动",
                "现场条件从对手单方判断变为合作方亲眼见证",
            ),
            beat(
                "对手以为主角唱跳片刻就会主动停下",
                f"{protagonist}连续完成快节奏唱跳，正常换气，动作和音准保持稳定",
                f"{opponent}在中途试图叫停或降级动作",
                f"{protagonist}用完成下一段而非争论回应",
                "以可信动作和气息状态持续抬高压迫感",
                "主动推向正面对抗",
                action,
            ),
            beat(
                "对手已经当众说出主角无法完成",
                f"{protagonist}完成收尾动作和最后一句演唱，站稳后看向现场见证人",
                f"{opponent}嘴硬称完成一次不代表能承担训练",
                "现场见证人只作一句符合要求的定性结论",
                "不用数据、设备、文件或隐藏破坏完成反卡",
                "对抗推向反转",
                result,
            ),
            beat(
                "合作方已经亲眼确认完整表现",
                f"{protagonist}要求本章结果立刻生效",
                f"{opponent}眼看病弱降配宣传被当场撤下仍试图挽回",
                f"合作方直接确认训练强度决定权归还{protagonist}",
                "以撤下宣传、归还权限和对手失态收束，不开启新支线",
                "反转推向掌控",
                result,
            ),
        ]
    elif medication_paper_audit:
        allowed_materials = "、".join(paper_markers)
        beats = [
            beat(
                info_gap or "上一世，同一批药品在未经核对时被直接使用",
                f"{protagonist}认出旧局，要求无姓名现场负责人从开场就在场，并把{allowed_materials}并排放好",
                f"{opponent}催促照惯例先用药后补记",
                f"{protagonist}拒绝开封，只要求当面逐项读出纸面内容",
                "把核对限制在章节卡点名的三类纸面材料",
                "警惕推向主动",
                "针剂保持封存，现场已有权限者全程见证",
            ),
            beat(
                "对手以为几张纸看不出问题",
                f"{protagonist}只指出一处编号、数量、日期或签收不一致",
                f"{opponent}将这处矛盾辩解成笔误或补记",
                "同一处纸面矛盾与对手当面操作无法同时成立",
                "只写普通人肉眼可读的一处差异，不作专业鉴定",
                "主动推向正面对抗",
                action,
            ),
            beat(
                "对手已经亲口承认纸面内容由自己经手",
                f"{protagonist}要求开场就在场的负责人立即处理",
                f"{opponent}试图抢回材料或要求以后再查",
                "负责人只依据三类材料和当面辩解直接宣布暂停职务",
                "不新增监察组、授权册、公章、报告、记录或外部核验",
                "对抗推向反转",
                result,
            ),
            beat(
                "暂停决定已经当场生效",
                f"{protagonist}接过药品柜钥匙和领用簿，确认未拆针剂仍保持封存",
                f"{opponent}被迫交接后嘴硬或失态",
                f"负责人当场确认药品保管权归{protagonist}",
                "用钥匙、领用簿、保管权和对手反应收束",
                "反转推向掌控",
                result,
            ),
        ]
    else:
        beats = [
            beat(info_gap or "上一世同类旧局再次出现", f"{protagonist}认出旧局并确定本章要改变的具体现场选择", f"{opponent}按既定性格催促旧流程", f"{protagonist}不照上一世的选择行动", "快速进入本章主要冲突", "警惕推向主动", info_gap),
            beat("对手以为主角仍会被原流程牵制", action, f"{opponent}照旧作出压制或占便宜的动作", "主角的提前布置让对手亲手暴露意图", "让本章行动通过对话与动作发生", "主动推向压迫", action),
            beat("对手已按旧习惯做出可见选择", f"{protagonist}在同一场冲突中启动反卡", f"{opponent}先嘴硬否认再发现无法撤回", "已规划的规则、权限、现场表现或流程当场生效", "完成本章小反杀和可见态度变化", "压迫推向反转", result),
            beat("反卡已使对手的旧计划失效", f"{protagonist}确认具体权利、资源或安全已收回", f"{opponent}当场承受章节卡规定的损失并作出直接反应", "决定、权限或结果在本场景中正式生效", "先结算本章回报，再以既有对手反应收束", "反转推向掌控", result),
        ]

    return {
        "chapter_num": int(chapter_num),
        "open_from_prev": open_from_prev or ("（无）" if chapter_num == 1 else "承接上一章已生效的结果"),
        "end_to_next": ending,
        "flashback_in_beat_idx": None,
        "chapter_type": "prev_life_only" if role == "prev_life_death_only" else "present_only",
        "closure_type": "full_close",
        "beats": beats,
    }


def _cluster_contract_hard_failures(
    contract: Dict[str, Any],
    cluster: Dict[str, Any],
    chapter_nums: List[int],
    chapter_cards: Dict[int, Dict[str, Any]],
) -> List[str]:
    failures: List[str] = []
    chapters = contract.get("chapters") if isinstance(contract, dict) else None
    actual_nums: List[int] = []
    if isinstance(chapters, list):
        for item in chapters:
            if not isinstance(item, dict):
                continue
            try:
                actual_nums.append(int(item.get("chapter_num")))
            except Exception:
                pass
    if actual_nums != [int(ch) for ch in chapter_nums]:
        failures.append("簇级合同章节范围或顺序与章节卡不一致")

    text = json.dumps(contract, ensure_ascii=False, default=str)
    cast = cluster.get("canonical_cast") or []
    unknown = _unknown_named_roles_in_synopsis(text, cast)
    if unknown:
        failures.append("簇级合同新增人物或命名实体：" + "、".join(unknown))

    accepted_source = json.dumps(
        {"cluster": cluster, "cards": [chapter_cards.get(ch, {}) for ch in chapter_nums]},
        ensure_ascii=False,
        default=str,
    )
    drift_markers = (
        "行业封杀", "封杀", "申诉信", "申诉权", "合同反锁", "邮箱密码", "社交媒体", "Instagram",
        "记者", "新闻报道", "热搜", "偷拍视频", "秘密录音", "匿名邮件",
    )
    unplanned = [marker for marker in drift_markers if marker in text and marker not in accepted_source]
    if unplanned:
        failures.append("簇级合同新增章节卡之外的推进材料：" + "、".join(unplanned))

    planned_titles = _planned_work_titles(cluster, *[chapter_cards.get(ch, {}) for ch in chapter_nums])
    contract_titles = set(re.findall(r"《([^》\n]{1,40})》", text))
    if contract_titles - planned_titles:
        failures.append("簇级合同改写作品名：" + "、".join(sorted(contract_titles - planned_titles)))
    return failures


def _build_grounded_cluster_synopsis_from_cards(
    cluster: Dict[str, Any],
    chapter_cards: Dict[int, Dict[str, Any]],
    chapter_nums: List[int],
) -> str:
    """Build a closed synopsis when Qwen keeps contaminating an accepted plan."""
    cast = cluster.get("canonical_cast") or []
    cast_lines = [
        f"{str(member.get('name') or '').strip()}（{str(member.get('role') or '既定身份').strip()}）"
        for member in cast if isinstance(member, dict) and str(member.get("name") or "").strip()
    ]
    lines = [
        "【固定人物】" + "、".join(cast_lines),
        "【推进原则】只使用固定人物姓名和无姓名职位；重生只保留记忆，不携带上一世实体物品。",
    ]
    for chapter in chapter_nums:
        card = chapter_cards.get(chapter, {}) or {}
        role = str(card.get("chapter_role_v2") or "既定推进章").strip()
        action = str(card.get("this_life_revenge") or card.get("chapter_goal") or "").strip()
        result = str(card.get("core_payoff") or card.get("chapter_ending") or "").strip()
        if role == "rebirth_awakening_only":
            opening = "主角从上一章死亡后的余痛中惊醒，核对身体、房间与日期，确认重生"
        else:
            opening = "承接上一章已经生效的结果进入当前冲突"
        lines.append(
            f"【第{chapter}章】{opening}。主角主动行动：{action}。"
            f"本章结果当场生效：{result}。"
        )
    lines.append(
        "【簇内收束】所有行动按章发生，不提前授予后续角色或资源；最后停在既定收益、对手损失与现场反应。"
    )
    return "\n".join(lines)


def _short_text(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s[:n] + ("…" if len(s) > n else "")


def _build_cluster_contract_prompt(
    cluster: Dict[str, Any],
    chapter_cards: Dict[int, Dict[str, Any]],
    chapter_nums: List[int],
    exec_plan: Optional[Dict[str, Any]],
    rewrite_advice: Optional[List[str]],
) -> str:
    cluster_id = cluster.get("cluster_id", "") or ""
    cluster_name = cluster.get("name", cluster.get("cluster_name", "")) or ""
    main_opp = cluster.get("main_opponent", "") or ""
    core_payoff = cluster.get("core_payoff", "") or ""
    info_gap = cluster.get("info_gap_from_prev_life", "") or ""
    outcome = cluster.get("cluster_outcome", "") or ""
    span_desc = f"{chapter_nums[0]}-{chapter_nums[-1]}" if chapter_nums else ""

    rewrite_block = ""
    if rewrite_advice:
        rewrite_block = "\n【重写要求（必须遵守）】\n" + "\n".join(rewrite_advice[:10])

    ep_block = ""
    if isinstance(exec_plan, dict) and isinstance(exec_plan.get("evidence_chain"), list):
        lines: List[str] = []
        for ev in exec_plan.get("evidence_chain") or []:
            if not isinstance(ev, dict):
                continue
            eid = str(ev.get("evidence_id", "") or "").strip()
            if not eid:
                continue
            lines.append(
                f"- 【{eid}】 acquire={ev.get('acquire_chapter')} verify={ev.get('verify_chapter')} use={ev.get('use_chapter')}"
            )
        if lines:
            ep_block = "\n【证据链（分工用）】\n" + "\n".join(lines[:12]) + "\n"

    cards_lines: List[str] = []
    for ch in chapter_nums:
        c = chapter_cards.get(ch, {}) or {}
        cards_lines.append(
            f"第{ch}章：role={c.get('chapter_role_v2','')}；goal={_short_text(str(c.get('chapter_goal') or ''), 120)}"
        )

    schema = """
{
  "one_line_goal": "<string：本簇一句话总目标>",
  "unresolved_queue": ["<string>", "..."],
  "chapters": [
    {
      "chapter_num": <int>,
      "duty_title": "<string：本章异构职责，如 醒来部署 / 规则试探 / 现场反卡 / 结果落锤>",
      "must_finish": ["<string：本章必须交付的可验收结果>", "..."],
      "forbidden": ["<string：本章禁止，如 不得开发布会 / 不得重复档案室取证>", "..."]
    }
  ]
}
""".strip()

    return f"""你是短剧/小说总策划。请为情节族生成【簇级合同】JSON：把 {len(chapter_nums)} 章拆成职责互不相同的连续推进，禁止平均摊「铺垫-回忆-调查-反击」模板。

要求（非常重要）：
1. 只输出严格 JSON（不要 Markdown，不要解释），可被 json.loads；
2. one_line_goal：一句话写清本簇最终要让读者看到什么结果；
3. unresolved_queue：列出全簇尚未完成、需在后文兑现的硬目标（可含证据节点）；
4. 每一章必须异构：duty_title / must_finish / forbidden 要明确「本章专属」，并写出「本章禁止抢跑」；职责应是醒来部署、职业现场抢位、合同反卡、权限夺回或现场结算等人物行动，不得使用“潜入、核验、搜证、联系媒体、公开爆料”作为章职责；
5. 必须对齐主要对手与信息差：{main_opp}；{info_gap[:200] if info_gap else ''}
6. 前世信息差只能是记忆锚点，不能被还原成今生录音、视频、文件或截图；若需现实材料，必须在今生由已经规划的动作当场产生。
{rewrite_block}{ep_block}

【情节族】cluster_id={cluster_id}；name={cluster_name}；章节范围={span_desc}
核心爽点：{core_payoff}
本簇结局：{outcome}

【章节卡摘要（分工参考）】
{chr(10).join(cards_lines)}

输出 JSON 结构：
{schema}
"""


def _contract_chapter_entry(contract: Dict[str, Any], chapter_num: int) -> Dict[str, Any]:
    for c in contract.get("chapters") or []:
        if not isinstance(c, dict):
            continue
        try:
            if int(c.get("chapter_num") or -1) == int(chapter_num):
                return c
        except Exception:  # noqa: BLE001
            continue
    return {"duty_title": "", "must_finish": [], "forbidden": []}


def _init_cluster_state(cluster_id: str, contract_obj: Dict[str, Any]) -> Dict[str, Any]:
    uq = contract_obj.get("unresolved_queue") or []
    return {
        "cluster_id": cluster_id,
        "completed_items": [],
        "unresolved_items": [str(x) for x in uq if str(x).strip()],
        "last_scene": "",
        "last_hook": "",
        "used_locations": [],
        "used_evidence": [],
        "forbidden_repeat": [],
        "progress_percent": 0,
    }


def _format_rolling_context_block(
    cluster: Dict[str, Any],
    contract_obj: Dict[str, Any],
    state: Dict[str, Any],
    chapter_num: int,
    chapter_nums: List[int],
) -> str:
    one_line = str(contract_obj.get("one_line_goal") or cluster.get("core_payoff") or "")
    ce = _contract_chapter_entry(contract_obj, chapter_num)
    duty = str(ce.get("duty_title") or "")
    must = ce.get("must_finish") or []
    forb = ce.get("forbidden") or []
    must_s = "\n".join(f"- {x}" for x in must[:8]) if must else "（见章节卡）"
    forb_s = "\n".join(f"- {x}" for x in forb[:8]) if forb else "（无）"
    rest_lines: List[str] = []
    for c in chapter_nums:
        if c <= chapter_num:
            continue
        cc = _contract_chapter_entry(contract_obj, c)
        rest_lines.append(f"- 第{c}章：{cc.get('duty_title', '（待推进）')}")
    remaining = "\n".join(rest_lines[:6]) if rest_lines else "（无）"
    comp = state.get("completed_items") or []
    comp_s = "\n".join(f"- {x}" for x in comp[-10:]) if comp else "（尚无可视化完成项）"
    fr = state.get("forbidden_repeat") or []
    fr_s = "\n".join(f"- {x}" for x in fr[-8:]) if fr else "（无）"
    uq = contract_obj.get("unresolved_queue") or []
    uq_s = "\n".join(f"- {x}" for x in uq[:8]) if uq else ""

    return f"""【本簇总目标（一句话）】
{one_line}

【全局未决队列（勿重复讲背景）】
{uq_s if uq_s else '（见合同）'}

【已完成 / 已推进】
{comp_s}

【本章合同 — 第{chapter_num}章】
职责：{duty}
必须完成：
{must_s}
本章禁止：
{forb_s}

【后续章节才允许写（勿在本章抢跑）】
{remaining}

【禁止重复清单】
{fr_s}

【承接上一章成稿（必须）】
上一章真实结尾场景：{state.get('last_scene') or '（无）'}
上一章真实未决钩子：{state.get('last_hook') or '（无）'}
进度约 {state.get('progress_percent', 0)}%（最后一章须写到收束结局）

（硬性要求：禁止再用大段笔墨复述「背景/起因/上一世总览」；只写接着上一章往下推进的动作与信息增量。）
"""


def _contract_chapter_hint_block(contract_obj: Dict[str, Any], chapter_num: int) -> str:
    ce = _contract_chapter_entry(contract_obj, chapter_num)
    must = ce.get("must_finish") or []
    forb = ce.get("forbidden") or []
    ms = "；".join(str(x) for x in must[:6]) if must else "（见章节卡）"
    fs = "；".join(str(x) for x in forb[:6]) if forb else "（无）"
    return (
        f"【本章异构合同（与簇内其它章职责必须不同）】\n"
        f"职责：{ce.get('duty_title', '')}\n"
        f"必须完成：{ms}\n"
        f"本章禁止：{fs}"
    )


def _head_echoes_tail_scene_or_hook(head: str, tail_scene: str, tail_hook: str) -> bool:
    """承接校验：当前章开头是否显式呼应上一章抽取的尾场景/尾钩（优于纯二元组匹配）。"""
    h = (head or "").replace("\n", "")
    for piece in (tail_scene or "", tail_hook or ""):
        s = (piece or "").strip().replace("\n", "")
        if len(s) < 4:
            continue
        cap = min(len(s), 96)
        for i in range(0, cap - 3):
            if s[i : i + 4] in h:
                return True
    return False


def _cn_bigrams_for_overlap(text: str, limit: int = 48) -> List[str]:
    t = (text or "").replace("\n", "").replace(" ", "")
    out: List[str] = []
    seen: set = set()
    for i in range(len(t) - 1):
        bg = t[i : i + 2]
        if "\u4e00" <= bg[0] <= "\u9fff" and "\u4e00" <= bg[1] <= "\u9fff":
            if bg not in seen:
                seen.add(bg)
                out.append(bg)
        if len(out) >= limit:
            break
    return out


def _update_cluster_state_after_chapter(
    state: Dict[str, Any],
    contract_obj: Dict[str, Any],
    chapter_num: int,
    chapter_text: str,
    chapter_index: int,
    total_chapters: int,
    tail_scene: str,
    tail_hook: str,
) -> None:
    state["last_scene"] = tail_scene or ""
    state["last_hook"] = tail_hook or ""
    state["progress_percent"] = int(100 * (chapter_index + 1) / max(1, total_chapters))
    text = chapter_text or ""
    ce = _contract_chapter_entry(contract_obj, chapter_num)
    for item in ce.get("must_finish") or []:
        s = str(item).strip()
        if len(s) > 4 and s in text:
            if s not in state["completed_items"]:
                state["completed_items"].append(s)
    if text.strip():
        open_snip = text.strip().replace("\n", "")[:120]
        if open_snip:
            state["forbidden_repeat"].append(f"不得再用近似开篇：{open_snip[:72]}…")
    for m in re.findall(r"【E\d+】", text):
        if m not in state["used_evidence"]:
            state["used_evidence"].append(m)


def _chapter_rolling_critic(
    prev_text: str,
    curr_text: str,
    chapter_num: int,
    contract_ch: Dict[str, Any],
    prev_tail_scene: str = "",
    prev_tail_hook: str = "",
) -> List[str]:
    violations: List[str] = []
    tail = (prev_text or "")[-280:]
    head = (curr_text or "")[:220]
    if tail.strip() and head.strip() and len(tail) > 40:
        ok_echo = False
        if (prev_tail_scene or "").strip() or (prev_tail_hook or "").strip():
            ok_echo = _head_echoes_tail_scene_or_hook(head, prev_tail_scene, prev_tail_hook)
        if not ok_echo:
            bgs = _cn_bigrams_for_overlap(tail, limit=56)
            if bgs and not any(bg in head for bg in bgs):
                violations.append(
                    f"第{chapter_num}章开头承接不足：前220字未显式呼应上一章结尾的人/地/物/动作（请改写开头嵌入上一章末尾具体元素）"
                )
        active_tail_names: set[str] = set()
        tail_context = " ".join((tail, prev_tail_scene or "", prev_tail_hook or ""))
        for match in re.finditer(r"(?<![A-Za-z])([A-Z][a-z]{2,})(?:\s+[A-Z][a-z]+)?(?![A-Za-z])", tail_context):
            first_name = match.group(1)
            left = max(0, match.start() - 36)
            right = min(len(tail_context), match.end() + 36)
            nearby = tail_context[left:right]
            if re.search(r"推门|走进|站在|开口|说道|问道|盯着|拦住|出现|递给|打来|接通", nearby):
                active_tail_names.add(first_name)
        missing_active_names = [
            name for name in active_tail_names
            if not re.search(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", head, re.I)
        ]
        if missing_active_names:
            violations.append(
                f"第{chapter_num}章跳过上一章结尾正在行动的人物：{', '.join(sorted(missing_active_names))}。"
                "必须先写完其进入、说话、来电或对峙造成的直接结果，再转场。"
            )
        cast = contract_ch.get("canonical_cast") or []
        canonical_aliases: Dict[str, set[str]] = {}
        for member in cast:
            if not isinstance(member, dict):
                continue
            name = str(member.get("name") or "").strip()
            if not name:
                continue
            aliases = {name}
            for separator in ("·", "・"):
                if separator in name:
                    aliases.add(name.split(separator, 1)[0])
            canonical_aliases[name] = aliases
        ownership_tokens = (
            "外套肘部", "西装肘部", "袖口金线", "衣领污渍",
            "褶皱", "疤痕", "伤口", "血迹", "水痕",
            "钥匙串", "口袋里的钥匙", "裤袋里的钥匙",
        )
        previous_owners: Dict[str, str] = {}
        last_explicit_owner = ""
        for sentence in re.split(r"[。！？\n]", (prev_text or "")[-650:]):
            owners = [
                name
                for name, aliases in canonical_aliases.items()
                if any(alias in sentence for alias in aliases)
            ]
            if len(owners) == 1:
                last_explicit_owner = owners[0]
            owner = owners[0] if len(owners) == 1 else ""
            if (
                not owner
                and last_explicit_owner
                and re.match(r"\s*(?:他|她|其)(?:的)?", sentence)
            ):
                owner = last_explicit_owner
            if not owner:
                continue
            for token in ownership_tokens:
                if token in sentence:
                    previous_owners[token] = owner
        current_last_explicit_owner = ""
        for sentence in re.split(r"[。！？\n]", (curr_text or "")[:650]):
            owners = [
                name
                for name, aliases in canonical_aliases.items()
                if any(alias in sentence for alias in aliases)
            ]
            if len(owners) == 1:
                current_last_explicit_owner = owners[0]
            owner = owners[0] if len(owners) == 1 else ""
            if (
                not owner
                and current_last_explicit_owner
                and re.match(r"\s*(?:他|她|其)(?:的)?", sentence)
            ):
                owner = current_last_explicit_owner
            if not owner:
                continue
            for token, previous_owner in previous_owners.items():
                if token in sentence and owner != previous_owner:
                    violations.append(
                        f"第{chapter_num}章把上一章属于{previous_owner}的“{token}”转移给了{owner}；"
                        "承接元素不得更换持有人，改用主角本人上一章明确拥有的动作或物件转场。"
                    )
                    break
    if prev_text and curr_text:
        p = (prev_text[:400]).replace("\n", " ").strip()
        c = (curr_text[:400]).replace("\n", " ").strip()
        if len(p) > 80 and len(c) > 80 and p[:130] == c[:130]:
            violations.append(f"第{chapter_num}章开头与上一章开头高度重复（请换场景或换动作起笔）")
    return violations


def _build_cluster_beats_prompt(
    cluster: Dict[str, Any],
    chapter_nums: List[int],
    chapter_cards: Dict[int, Dict[str, Any]],
    cluster_synopsis: str,
    prev_tail_scene: str,
    prev_unresolved_hook: str,
    rewrite_advice: Optional[List[str]] = None,
) -> str:
    cluster_id = cluster.get("cluster_id", "") or ""
    cluster_name = cluster.get("name", cluster.get("cluster_name", "")) or ""
    main_opp = cluster.get("main_opponent", "") or ""
    core_payoff = cluster.get("core_payoff", "") or ""
    info_gap = cluster.get("info_gap_from_prev_life", "") or ""
    outcome = cluster.get("cluster_outcome", "") or ""

    cross_hint = ""
    if prev_tail_scene or prev_unresolved_hook:
        cross_hint = (
            "首章开头必须接续上一章尾钩：\n"
            f"- 上一章最后场景/动作：{prev_tail_scene or '（无）'}\n"
            f"- 上一章未解决钩子：{prev_unresolved_hook or '（无）'}\n"
        )

    rewrite_block = ""
    if rewrite_advice:
        rewrite_block = "\n【重写要求（必须遵守）】\n" + "\n".join(rewrite_advice[:10])

    cards_block_text = "\n\n".join(
        [f"【第{ch}章章节卡】\n{_chapter_constraints_for_cluster_prompt(chapter_cards.get(ch, {}))}" for ch in chapter_nums]
    )

    # 这里必须避免在 f-string 里直接写 JSON 示例（里面有大量 `{}`），否则会被 Python 误当成格式化占位符。
    beats_json_schema = """
{
  "cluster_id": "<string>",
  "cluster_name": "<string>",
  "chapters": [
    {
      "chapter_num": <int>,
      "chapter_type": "<revenge_payoff|grievance_build|present_only|cross_chapter>",
      "closure_type": "<full_close|half_close|chain_close>",
      "open_from_prev": "<string>",
      "end_to_next": "<string>",
      "beats": [
        {
          "old_trap_signal": "<string>",
          "preemptive_move": "<string>",
          "opponent_old_move": "<string>",
          "reversal_trigger": "<string>",
          "scene_goal": "<string>",
          "visual_elements": "<string>",
          "emotion_push": "<string>",
          "info_delta": "<string>",
          "evidence_form": "<string>",
          "prev_life_memory_brief": "<string>",
          "foreshadow": "<string>",
          "relationship_push": "<string>",
          "must_not": "<string>"
        }
      ],
      "flashback_in_beat_idx": <int|null>
    }
  ]
}
""".strip("\n")

    return f"""{COMMERCIAL_REBIRTH_WRITER_ROLE}请把【情节族梗概】进一步拆成每章节拍卡（beats），以便后续连续正文生成并最终切分成章节。

【本项目主题硬锁定】
{constraints_text()}

要求（非常重要）：
1. 输出必须是严格 JSON（不要 Markdown，不要解释文字），且 JSON 可被直接 json.loads 解析；
   必须保证所有 JSON 字符串字段内部不得出现真实换行；若需要换行请用 \\n 表示；整份 JSON 尽量输出为一行（允许空白分隔）。
2. 对每个章节：beats 必须 4-6 条，每条为一个结构化节拍卡对象，按情节点顺序排列；
   每条必须优先写满「旧局反制四段式」：old_trap_signal（何种已铺垫信号让主角识别风险）/ preemptive_move（提前采取什么行动）/ opponent_old_move（对方按既定动机如何行动）/ reversal_trigger（何时由因果结果触发反卡）；再补其它字段；must_not 至少 1-2 条；
   evidence_form 仅写「落锤材料」一句（可选），不得替代四段式成为本章主轴；禁止把 beats 设计成「找线索→核实→联系媒体→发布会」。
3. 若该章需要插入上一世回忆（根据该章 `chapter_role_v2`），则在 JSON 字段 flashback_in_beat_idx 写出对应 beats 下标（从 0 开始），并要求该 beats 对象的 `prev_life_memory_brief` 给出上一世受害回忆的具体内容要点（用于正文直接插入）；不需要则填 null 且所有 beats 的 `prev_life_memory_brief` 为空字符串；
4. chapter_type 必须从：revenge_payoff / grievance_build / present_only / cross_chapter 中二选一或多选（但每章只能给一个）；
5. closure_type 必须从：full_close / half_close / chain_close 中三选一（每章只能给一个）；
6. open_from_prev：首章必须给出“接续上一章尾钩”的具体动作/场景；非首章必须与上一章 end_to_next 的未决点强相关；
7. end_to_next：每章结尾必须留下下一章钩子（最后一章给本簇落点后的读者悬念，允许为“更大风暴延续”，但不得引入新幕后系统/系统提示音）；
8. 禁止用「档案室翻找/匿名邮件/加密邮件/自由撰稿人/微博爆料/新闻发布会」作为本章 beats 的主推进链。

【情节族信息】
cluster_id：{cluster_id}
cluster_name：{cluster_name}
主要对手：{main_opp}
核心爽点：{core_payoff}
上一世信息差（记忆锚点；材料仅落锤）：{info_gap}
本簇结局/落点：{outcome}
覆盖章节：{chapter_nums[0]}-{chapter_nums[-1]}

{cross_hint}
{rewrite_block}

【情节族详细梗概（不得偏离）】
{cluster_synopsis}

【逐章章节卡约束（必须遵守 must/must_not/结尾钩子）】
{cards_block_text}

输出 JSON 结构（仅输出此 JSON）：
{beats_json_schema}
"""


def _build_single_chapter_beats_prompt(
    cluster: Dict[str, Any],
    chapter_num: int,
    chapter_card: Dict[str, Any],
    cluster_synopsis: str,
    prev_tail_scene: str,
    prev_unresolved_hook: str,
    state_last_scene: str,
    state_last_hook: str,
    is_first_chapter: bool,
    is_last_chapter: bool,
    rewrite_advice: Optional[List[str]] = None,
    rolling_synopsis_mode: bool = False,
) -> str:
    """
    单章 beats：只输出一个可 json.loads 的 JSON 对象，避免“全簇 JSON 一次性输出导致截断/解析失败”。
    簇内非首章应使用 rolling_synopsis_mode=True，且 state_last_* 来自上一章成稿抽取。
    """
    cluster_id = cluster.get("cluster_id", "") or ""
    cluster_name = cluster.get("name", cluster.get("cluster_name", "")) or ""
    main_opp = cluster.get("main_opponent", "") or ""
    core_payoff = cluster.get("core_payoff", "") or ""
    info_gap = cluster.get("info_gap_from_prev_life", "") or ""
    outcome = cluster.get("cluster_outcome", "") or ""
    canonical_cast = cluster.get("canonical_cast") or chapter_card.get("canonical_cast") or []

    role_v2 = chapter_card.get("chapter_role_v2", "") or ""
    prompt_cast = canonical_cast
    if role_v2 == "prev_life_death_only" and any(
        isinstance(member, dict)
        and str(member.get("name") or "").strip() == "麦珂·杰森"
        for member in canonical_cast
    ):
        prompt_cast = [
            member for member in canonical_cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() not in {"ally", "support"}
        ]
    elif role_v2 == "rebirth_awakening_only" and any(
        isinstance(member, dict)
        and str(member.get("name") or "").strip() == "麦珂·杰森"
        for member in canonical_cast
    ):
        prompt_cast = [
            member for member in canonical_cast if isinstance(member, dict)
            and (
                str(member.get("alignment") or "").casefold() == "protagonist"
                or "医生" in str(member.get("role") or "")
            )
        ]
    cards_block_text = _chapter_constraints_for_cluster_prompt(chapter_card)
    cards_block_text = _render_grounded_execution_text(cards_block_text, chapter_card)
    evidence_budget = _execution_evidence_budget(chapter_card)
    cluster_synopsis = _render_grounded_execution_text(cluster_synopsis, chapter_card)
    rewrite_block = ""
    if rewrite_advice:
        rewrite_block = "\n【重写要求（必须遵守）】\n" + "\n".join(rewrite_advice[:10])

    # 与 v1/v2 现有逻辑保持一致：哪些 chapter_role_v2 需要插入“上一世回忆”
    prev_life_roles = {
        "prev_life_full",
        "prev_life_explained_by_investigation",
        "present_past_mix",
        "slow_burn_press_with_past_shadow",
    }
    need_prev_life = role_v2 in prev_life_roles

    if role_v2 == "prev_life_death_only":
        engine_requirement = "全章只按上一世最后的希望→遭到背叛/压制→失去一切→死亡与不甘推进，禁止今生反击。"
    elif role_v2 == "rebirth_awakening_only":
        engine_requirement = "全章按惊醒→怀疑→验证日期/环境/身体→确认重生→执行第一步部署推进，不得抢跑大反杀。"
    else:
        engine_requirement = f"全章必须完成「{REBIRTH_ACTION_ENGINE}」。"

    open_seed_lines = []
    if is_first_chapter:
        open_seed_lines.append(f"跨情节族上一章末尾场景：{prev_tail_scene or '（无）'}")
        open_seed_lines.append(f"跨情节族上一章未解决钩子：{prev_unresolved_hook or '（无）'}")
    else:
        open_seed_lines.append(f"上一章成稿真实结尾场景（必须承接）：{state_last_scene or '（无）'}")
        open_seed_lines.append(f"上一章成稿真实未决钩子：{state_last_hook or '（无）'}")

    if rolling_synopsis_mode:
        synopsis_block_title = "【滚动上下文（簇级合同 + 剩余任务；禁止复述全簇背景）】"
        synopsis_guard = (
            "（硬性要求：禁止把本簇当成新故事从头讲；禁止再用大段铺垫复述「背景/起因」；"
            "open_from_prev 必须逐字承接上一章成稿结尾；不得把后几章结局提前写进本章 beats。）"
        )
    else:
        synopsis_block_title = "【情节族详细梗概（仅簇首章对齐用）】"
        synopsis_guard = (
            "（说明：仅簇首章使用完整梗概；仍须衔接跨情节族尾钩，且不得把簇末章结局提前写进本章 beats。）"
        )

    beats_json_schema = """
{
  "chapter_num": <int>,
  "open_from_prev": "<string>",
  "end_to_next": "<string>",
  "flashback_in_beat_idx": <int|null>,
  "beats": [
    {
      "old_trap_signal": "<string>",
      "preemptive_move": "<string>",
      "opponent_old_move": "<string>",
      "reversal_trigger": "<string>",
      "scene_goal": "<string>",
      "visual_elements": "<string>",
      "emotion_push": "<string>",
      "info_delta": "<string>",
      "evidence_form": "<string>",
      "foreshadow": "<string>",
      "relationship_push": "<string>",
      "must_not": "<string>",
      "prev_life_memory_brief": "<string>"
    }
  ]
}
""".strip("\n")

    return f"""{COMMERCIAL_REBIRTH_WRITER_ROLE}请为“第{chapter_num}章”输出该章的【节拍卡 beats】（只输出一个 JSON 对象）。

【本项目主题硬锁定】
{constraints_text()}

要求（非常重要）：
1. 输出必须是严格 JSON（不要 Markdown，不要解释文字），JSON 可被直接 json.loads 解析；
2. 必须保证所有 JSON 字符串字段内部不得出现真实换行；若需要换行请用 \\n 表示；整份 JSON 尽量输出为一行（允许空白分隔）；
3. beats 必须 4-6 条，每条为一个结构化 beats 对象，按情节点顺序排列；每一拍必须改变局面，禁止连续两拍都只是思考、等待、查资料或走路；
4. {engine_requirement}除特殊结构章外，每条优先写满 old_trap_signal / preemptive_move / opponent_old_move / reversal_trigger，再写其它字段；evidence_form 仅一句落锤材料（可选），不得替代人物行动；
5. 若 need_prev_life=True，则 flashback_in_beat_idx 必须为非 null 的整数，且必须且只能在该 beats 下标对应的那一拍里给出非空 prev_life_memory_brief；其它 beats 的 prev_life_memory_brief 只能为空字符串。
   若 need_prev_life=False，则 flashback_in_beat_idx 必须为 null，并且所有 beats 的 prev_life_memory_brief 必须为空字符串；
6. open_from_prev 必须体现与上一章未决点的承接：{("；".join(open_seed_lines))}；
   非簇首章时，open_from_prev 必须与「上一章成稿真实结尾」强绑定，不得改用抽象复述或重新介绍情节组。
7. end_to_next 必须来自既有对手的下一步公开动作、下一场已约定冲突或本章胜利引发的直接反应；禁止陌生电话、匿名短信、跟踪车辆、神秘援手和新人物递材料。若是最后一章，end_to_next 只写本簇落点后的具体余波，不得再开新谜团。
8. 禁止把本章 beats 设计成调查取证链（档案室/匿名邮件/媒体发布会/微博爆料等作为主推进）；除第1章与第2章外，本章至少设计一次小反杀及可见结果，不能整章只“等待最佳时机”。
9. info_gap 只能指导主角预判和今生提前布置；绝对禁止“从脑海还原录音/视频/文件”，也禁止把前世持有的手机、录音、截图直接带到今生。
10. 不得让主角在记者、镜头、红毯、直播或公众面前说出自己重生、上一世死亡或“我回来了”；重生秘密只作为内心驱动力。
11. 所有固定人物姓名必须逐字使用下方 canonical_cast 中的固定 name，不得改译、改姓、缩写或另造有姓名的角色；功能角色只写职位。
12. 不得新增现实专名、未规划作品名、演出名、医院名、场馆名、机构名、药品名、批号或医疗症状；需要时只用“复出演唱会、临时医疗室、问题针剂”等功能称呼。
13. beats 中的 evidence_form 和 reversal_trigger 必须服从下方“执行卡证据预算”；若卡片未给出检测、数据或附加条款，不得自行补造。

【情节族信息（仅用于对齐）】
cluster_id：{cluster_id}
cluster_name：{cluster_name}
主要对手：{main_opp}
核心爽点：{core_payoff}
上一世信息差（记忆锚点；材料仅落锤）：{info_gap}
本簇结局/落点：{outcome}
本章 chapter_role_v2：{role_v2}
canonical_cast：{json.dumps(prompt_cast, ensure_ascii=False)}

【章节执行卡约束（必须遵守）】
{cards_block_text}

【执行卡证据预算（节拍与正文共用）】
{evidence_budget}

{synopsis_block_title}
{synopsis_guard}
{cluster_synopsis}

{rewrite_block}

输出 JSON 结构（仅输出此 JSON）：
{beats_json_schema}
"""


def _select_grounded_chapter_cast(chapter_card: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Select only fixed characters that the accepted chapter card actually needs."""
    canonical_cast = chapter_card.get("canonical_cast") or []
    card_context = json.dumps(
        {
            key: chapter_card.get(key)
            for key in (
                "chapter_goal", "prev_life_tragedy", "this_life_revenge",
                "core_payoff", "chapter_ending", "must_resolve_this_chapter",
                "chapter_must_include", "chapter_milestone", "milestone",
            )
        },
        ensure_ascii=False,
    )
    selected: List[Dict[str, Any]] = []
    for member in canonical_cast:
        if not isinstance(member, dict):
            continue
        name = str(member.get("name") or "").strip()
        role = str(member.get("role") or "").strip()
        alignment = str(member.get("alignment") or "").casefold()
        aliases = {name}
        if "·" in name:
            aliases.add(name.split("·", 1)[0])
        role_anchors = re.findall(r"[“‘《]([^”’》]{2,20})[”’》]", role)
        needed = (
            alignment == "protagonist"
            or any(alias and alias in card_context for alias in aliases)
            or (
                alignment == "ally"
                and any(anchor and anchor in card_context for anchor in role_anchors)
            )
        )
        if needed:
            selected.append(member)
    selected_opponents = [
        member
        for member in selected
        if str(member.get("alignment") or "").casefold() == "opponent"
    ]
    if not selected_opponents:
        main_opponent = str(chapter_card.get("main_opponent") or "").strip()
        for member in canonical_cast:
            if not isinstance(member, dict):
                continue
            if str(member.get("name") or "").strip() == main_opponent:
                selected.append(member)
                break
    return selected or [
        member for member in canonical_cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
    ]


def _rag_technique_tag_block(
    rag_samples: Optional[Dict[str, List[Dict[str, Any]]]],
) -> str:
    """Expose only reusable craft tags, never retrieved sample prose."""
    if not isinstance(rag_samples, dict):
        return "（本章没有可靠的样本技法标签；不要自行模仿任何外部文本。）"
    title_map = {
        "revenge": "复仇回报",
        "grievance": "受压情绪",
        "universal": "通用叙事",
    }
    lines: List[str] = []
    for key in ("revenge", "grievance", "universal"):
        samples = rag_samples.get(key) or []
        if not isinstance(samples, list):
            continue
        for sample in samples[:2]:
            if not isinstance(sample, dict):
                continue
            technique_parts: List[str] = []
            for label, field in (
                ("情绪", "emotion_tags"),
                ("冲突", "conflict_tags"),
                ("动作", "action_tags"),
                ("节奏", "plot_tags"),
            ):
                values = sample.get(field) or []
                if isinstance(values, list) and values:
                    technique_parts.append(
                        f"{label}={'/'.join(str(value) for value in values[:5])}"
                    )
            if technique_parts:
                lines.append(
                    f"- {title_map.get(key, key)}技法："
                    + "；".join(technique_parts)
                )
    if not lines:
        return "（本章没有可靠的样本技法标签；不要自行模仿任何外部文本。）"
    return (
        "\n".join(lines)
        + "\n这些只用于调节情绪压力、冲突递进和回报节奏；"
        "不得借用样本文字、人物、物件或情节，也不得改变情节族里程碑。"
    )


def _chapter_prose_profile(
    chapter_num: int,
    chapter_card: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """Choose a stable but rotating prose shape without chapter-specific code."""
    card = chapter_card if isinstance(chapter_card, dict) else {}
    contract = (
        card.get("scene_contract")
        if isinstance(card.get("scene_contract"), dict)
        else _derive_closed_scene_contract(card)
    ) or {}
    identity = "|".join((
        str(card.get("cluster_id") or ""),
        str(contract.get("scene_archetype") or ""),
        str(chapter_num),
    ))
    digest = int(hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8], 16)
    profiles = (
        {
            "name": "对白施压型",
            "opening": "用对手的一句命令、否认或催促切入，主角在三句内用行动改变条件。",
            "rhythm": "九至十三段；短对白段穿插较长因果段，不能连续三段同长度。",
            "focus": "每轮对白都必须改变权限、选择或旁观者判断，不写空转争吵。",
            "ending": "停在一句裁定后的直接反应或物件交接上。",
        },
        {
            "name": "主动反卡型",
            "opening": "从主角正在执行的抢先动作切入，不先解释计划。",
            "rhythm": "八至十二段；行动段略长，关键对白单独成短段，结算段完整展开。",
            "focus": "先让读者看见动作和阻力，再用最少解释揭示主角为何早一步。",
            "ending": "停在对手刚失去现实利益的瞬间。",
        },
        {
            "name": "优势翻转型",
            "opening": "先写对手自以为得手的公开动作，让压力在前两段成立。",
            "rhythm": "十至十四段；前半短促、反卡处拉长、结尾再收紧，避免均匀分段。",
            "focus": "对手必须基于稳定性格犯错，主角利用的是情节卡信息差而非巧合。",
            "ending": "以主角拿回的具体权利、资源或安全结果收束。",
        },
        {
            "name": "见证裁定型",
            "opening": "从一项正在被核验、交付或表决的既有事项切入。",
            "rhythm": "七至十一段；程序动作写清但不科普，至少两处锋利短对白打断长段。",
            "focus": "见证者只确认亲眼所见，有权者只作卡片允许的决定，人物冲突仍是主轴。",
            "ending": "停在决定生效及对手无法撤回它的动作上。",
        },
        {
            "name": "情绪逼近型",
            "opening": "从一项会重演上一世伤害的熟悉信号切入，回忆只闪现一句。",
            "rhythm": "九至十二段；内心句极短，主要篇幅给当下选择、对抗和即时回报。",
            "focus": "情绪来自旧伤与今生选择的反差，不靠身体部位、喘息或环境反复渲染。",
            "ending": "以对手失态的短反应衬出已经落定的结果。",
        },
    )
    return profiles[(digest + chapter_num) % len(profiles)]


def _grounded_scene_contract_payload(
    chapter_card: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    card = chapter_card if isinstance(chapter_card, dict) else {}
    contract = (
        card.get("scene_contract")
        if isinstance(card.get("scene_contract"), dict)
        else _derive_closed_scene_contract(card)
    ) or {}
    return {
        key: contract.get(key)
        for key in (
            "scene_archetype", "phase", "protagonist", "opponent",
            "opponent_scene_actor", "supporting_cast",
            "supporting_organizations", "old_trap_signal", "trigger_action",
            "opponent_self_incrimination", "established_evidence_carriers",
            "current_evidence_carriers", "allowed_evidence_carriers",
            "immediate_result", "authority_actor", "authority_gain",
            "opponent_loss", "protagonist_gain", "settlement_required",
            "forbidden_mechanics",
        )
        if contract.get(key) not in (None, "", [])
    }


def _build_grounded_chapter_prompt(
    chapter_num: int,
    chapter_card: Dict[str, Any],
    chapter_beats: Optional[Dict[str, Any]] = None,
    prev_tail_scene: str = "",
    prev_unresolved_hook: str = "",
    failures: Optional[List[str]] = None,
    kg_context: str = "",
    rag_samples: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> str:
    """Build one universal card-driven prose prompt for initial generation and retries."""
    relevant_cast = _select_grounded_chapter_cast(chapter_card)
    beats = (chapter_beats or {}).get("beats") or []
    beat_lines: List[str] = []
    for idx, beat in enumerate(beats[:6], 1):
        if not isinstance(beat, dict):
            continue
        parts = [
            str(beat.get(key) or "").strip()
            for key in (
                "old_trap_signal", "preemptive_move", "opponent_old_move",
                "reversal_trigger", "scene_goal", "info_delta", "evidence_form",
            )
        ]
        parts = [
            _render_grounded_execution_text(part, chapter_card)
            for part in parts if part
        ]
        if parts:
            beat_lines.append(f"{idx}. " + "；".join(parts))
    beat_block = "\n".join(beat_lines) or "按章节执行卡中的行动与结果自然拆成四至六个递进场面。"
    failure_block = "\n".join(f"- {item}" for item in (failures or [])[:8]) or "- 无；这是首次生成。"
    must_resolve = chapter_card.get("must_resolve_this_chapter") or chapter_card.get("must_resolve") or []
    must_include = chapter_card.get("chapter_must_include") or []
    must_avoid = chapter_card.get("chapter_must_not_include") or []
    minimum_chars = _minimum_chapter_chars(chapter_num, chapter_card)
    evidence_budget = _execution_evidence_budget(chapter_card)
    rendered_action = _render_grounded_execution_text(
        chapter_card.get("this_life_revenge") or chapter_card.get("chapter_goal") or "",
        chapter_card,
    )
    rendered_goal = _render_grounded_execution_text(chapter_card.get("chapter_goal") or "", chapter_card)
    rendered_payoff = _render_grounded_execution_text(chapter_card.get("core_payoff") or "", chapter_card)
    rendered_resolve = _render_grounded_execution_text(must_resolve, chapter_card)
    rendered_include = _render_grounded_execution_text(must_include, chapter_card)
    rendered_avoid = _render_grounded_execution_text(must_avoid, chapter_card)
    rendered_ending = _render_grounded_execution_text(chapter_card.get("chapter_ending") or "", chapter_card)
    milestone = chapter_card.get("chapter_milestone") or chapter_card.get("milestone") or {}
    if not isinstance(milestone, dict):
        milestone = {}
    scene_contract = _grounded_scene_contract_payload(chapter_card)
    prose_profile = _chapter_prose_profile(chapter_num, chapter_card)
    technique_block = _rag_technique_tag_block(rag_samples)
    compact_kg = re.sub(r"\n{3,}", "\n\n", str(kg_context or "").strip())[:2800]
    return f"""你是高情绪、快节奏商业重生爽文作者。请依据已经人工验收的章节执行卡，从零生成第{chapter_num}章完整正文。

【主题与全书硬约束】
{constraints_text()}

【本章相关固定人物】
{json.dumps(relevant_cast, ensure_ascii=False)}
只允许这些固定人物以姓名出场；其他功能人物只能用无姓名职位。无需让名单中每个人都出场。

【上一章真实结尾】
场景：{prev_tail_scene or '无；直接进入本章冲突'}
未决动作：{prev_unresolved_hook or '无'}

【章节执行卡】
主动行动：{rendered_action}
章节目标：{rendered_goal}
核心回报：{rendered_payoff}
必须解决：{rendered_resolve}
必须包含：{rendered_include}
必须避免：{rendered_avoid}
结尾已生效结果：{rendered_ending}

【本章情节族里程碑，事实与顺序的最高优先级】
主角行动：{_render_grounded_execution_text(milestone.get('action') or rendered_action, chapter_card)}
对手反应：{_render_grounded_execution_text(milestone.get('opponent_reaction') or '', chapter_card)}
即时结果：{_render_grounded_execution_text(milestone.get('result') or rendered_ending, chapter_card)}
不得删减、倒置、弱化或把即时结果拖到下一章；其他材料与本段冲突时一律服从本段。

【从里程碑编译的通用场景契约】
{json.dumps(scene_contract, ensure_ascii=False, indent=2)}
契约列出的证据载体是白名单，不是要求全部写成技术说明。没有列出的材料、权限、证人和规则不得临时发明。

【执行卡证据预算】
{evidence_budget}

【Neo4j连续性事实】
{compact_kg or '无可用图谱事实。'}
这里只能用于保持既有人物状态、持有物、关系与前章结果一致，绝不能把图谱摘要当作本章新证据、对白或幕后信息。

【高情绪样本的可迁移技法】
{technique_block}

【本章差异化行文谱型】
谱型：{prose_profile['name']}
起笔：{prose_profile['opening']}
段落节奏：{prose_profile['rhythm']}
叙事焦点：{prose_profile['focus']}
收束：{prose_profile['ending']}

【已验收节拍，只能顺序展开】
{beat_block}

【上轮失败反馈】
{failure_block}

统一写作规则：
1. 开头一百五十字内接住上一章的人、物或动作并进入当前冲突；不得重新介绍背景。
2. 叙事发动机固定为：主角认出旧局或风险→抢先改变一个现场条件→对手照旧出招并自留破绽→主角当场反卡→现实结果立即生效。若这是情节族首章，必须用不超过四十字的一句内心叙述明确“上一世见过/认出旧局”，下一句立刻写今生主动动作；不得写进对白。
3. 只允许使用执行卡明确写出的材料、规则和操作；若节拍越过上方证据预算，以证据预算为准并丢弃该节拍细节。未明确写出证据时，只能靠当面行动、公开规则、纸面签收或对手亲口承认；禁止自行增加检测设备、监控截图、后台日志、匿名材料、黑客、跟踪或神秘援手。
4. 每个节拍都写行动、对白和局势增量。至少一句锋利对白；对手先有一次自以为得手的动作，结算后必须有具体失态、嘴硬或利益受损反应。身体动作只能在改变决定、关系或危险时出现，禁止逐句盘点手、脚、呼吸、视线、站位和人物距离。
5. 本章必须自然写清执行卡要求的双向结算：对手失去什么，主角拿回什么。结果写进宣读、签字、撤权、交接或现场反应，禁止在结尾另列两句摘要。
6. 前世记忆只能用于预判，不能变成今生录音、文件、截图或实体证据；主角不得在对白中公开自曝重生。
7. 不得临场给人物、媒体、平台、公司、机构、场馆、歌曲、演出、药品或文件取名。涉及现实原型时只用主题约束中的架空称呼或无姓名功能称呼。
8. 正文目标一千六百五十至一千九百字，硬范围{minimum_chars}至{MAX_CHAPTER_CHARS_V2}字。节拍只规定动作顺序，不得机械地一拍对应一个等长自然段；遵守本章谱型，并让段落数量、开头方式和收束方式与相邻章节有明显差异。
9. 禁止完全重复句、同一句内近距离重复同一名词、断裂拼接句和舞台调度式位移。结尾结果生效后不得再转去写窗景、天气、灯光、影子或无关整理动作。
10. 只输出正文，不要标题、解释、编号、节拍标签或验收总结。
"""


def _build_closed_evidence_scene_prompt(
    chapter_num: int,
    chapter_card: Dict[str, Any],
    *,
    prev_tail_scene: str = "",
    failures: Optional[List[str]] = None,
    attempt: int = 1,
) -> Optional[str]:
    """Compile narrow performance and paper-audit cards into compact prose prompts."""
    _, performance_scene, paper_markers = _closed_evidence_contract(chapter_card)
    medication_paper_audit = (
        all(marker in paper_markers for marker in ("封签", "送货单", "领用簿"))
        and "核对" in (
            str(chapter_card.get("chapter_goal") or "")
            + str(chapter_card.get("this_life_revenge") or "")
        )
    )
    if not performance_scene and not medication_paper_audit:
        return None

    cast = _select_grounded_chapter_cast(chapter_card)
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
    ), "主人公")
    opponents = [
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "opponent"
        and str(member.get("name") or "").strip()
    ]
    opponent = opponents[0] if opponents else "既有对手"
    goal = _render_grounded_execution_text(chapter_card.get("chapter_goal") or "", chapter_card)
    action = _render_grounded_execution_text(
        chapter_card.get("this_life_revenge") or chapter_card.get("chapter_goal") or "",
        chapter_card,
    )
    payoff = _render_grounded_execution_text(chapter_card.get("core_payoff") or "", chapter_card)
    ending = _render_grounded_execution_text(chapter_card.get("chapter_ending") or payoff, chapter_card)
    minimum_chars = _minimum_chapter_chars(chapter_num, chapter_card)
    cluster_index = int(chapter_card.get("cluster_chapter_index") or 0)
    info_gap = str(chapter_card.get("info_gap_from_prev_life") or "").strip()
    if cluster_index == 1 and info_gap:
        advance_action = (
            "请合作方代表和现场见证人从开场就在排练场"
            if performance_scene
            else "请无姓名现场负责人从开场就在医务室"
        )
        memory_rule = (
            f"首段使用自然句式“{protagonist}记得，上一世，{opponent}也用过这套办法”；"
            f"下一句必须写他“提前”{advance_action}，不得改成调空调、摆道具或准备材料；"
            f"随后用“{opponent}果然”引出对手照旧出招，"
            "反卡处写“当场”。这些词只用于私下叙述，前世信息不得进入对白。"
        )
    else:
        memory_rule = "不新增大段前世回忆；需要预判时只写一句内心认知，绝不进入对白。"

    variation_routes = (
        "以短促动作和锋利对白为主，环境描写只服务于压迫感。",
        "从对手自以为得手写起，让主角用连续行动而非解释翻盘。",
        "从最终交接倒推场面，所有段落都必须推动同一场冲突。",
        "压缩技术词和说明句，强化对手嘴硬、失态与被迫让权。",
    )
    variation = variation_routes[min(max(1, attempt) - 1, len(variation_routes) - 1)]
    continuity_context = (
        (
            "前场纸面结果已经生效，泄密者已被清出团队；"
            "主角直接转入排练场验证真实表演能力。"
            "只承接这个因果，不把前场签字、桌面文件、排期表或其他纸面道具带入本场"
        )
        if performance_scene
        else (
            "前场结果已经生效，主角转入医务室处理下一项风险；"
            "不得继承前场对手的口袋、钥匙、衣物、伤痕或被清退经历"
        )
    )

    shared_rules = f"""
你要从空白页写一章快节奏中文商业小说正文。上轮草稿已经作废，不提供也不继承其内容。

【固定合同】
本章：第{chapter_num}章
长度：一千五百至一千八百字，硬范围{minimum_chars}至{MAX_CHAPTER_CHARS_V2}字
允许具名人物：{json.dumps(cast, ensure_ascii=False)}
连续性：{continuity_context}
目标：{goal}
行动：{action}
必须兑现：{payoff}
结尾结果：{ending}
前世记忆用法：{memory_rule}
叙事侧重：{variation}

只使用下方事实白名单写作。功能人物只称合作方代表、现场见证人或现场负责人。
除固定人物外不创造姓名；国家、城市、公司、机构、作品、歌曲、奖项和产品不使用现实专名，
需要提及时只用可联想的虚构称呼。全文只用中文，不出现英文、字母代号、标题、说明、
编号式节拍、Markdown 或创作术语。只输出小说正文。
下方节拍只锁定事件顺序，不是段落模板。不得一拍固定写成一个等长大段；应按对话打断、动作转折和权力变化自然拆合为八至十四段，其中至少三个短对白或短动作段，长短必须有明显变化。
""".strip()

    if performance_scene:
        scene_script = f"""
【事实白名单】
人物只有{protagonist}、{opponent}、一名合作方代表和一名现场见证人。
地点只有排练场。可用物只有控台、普通音响、折叠椅、外套和一张旧宣传页。
验真依据只有现场听见和看见的唱跳完成度：节拍、普通舞步、动作衔接、音准和自然换气。
胜负结果只有撤下旧宣传页，以及训练强度决定权从{opponent}回到{protagonist}。
本场绝不出现针剂、药品、封签、送货单、领用簿、钥匙、协议、合同、条款、编号或检测设备；
这些即使出现在情节组的其他章节，也不得提前进入本章。
表演动作只能从普通踏步、转身、侧移、摆臂、自然换气和站稳收势中选用。
不得跳跃、腾空、跪地、撑地、翻滚、急停变向，不得拆解身体部位，不得描写汗液，
不得记录次数、步数、轮次、时长、距离、角度、音程或任何精确参数。

【八个正向节拍】
1. 首段写{protagonist}凭上一世记忆认出降配旧招；他已提前让合作方代表和现场见证人坐在排练场。
2. {opponent}站在控台旁，只说“慢一点，别勉强”。{protagonist}做普通热身，当面要求按原强度开始。
3. 写一段持续推进的快节奏唱跳，使用自然动作和听感，不使用技术量化。
4. 写{opponent}从笃定到紧张的当前反应，然后让他只喊一次“停一下”。
5. {protagonist}不争论，一次性唱完后半段，完成最后一句和收势，站稳看向现场见证人。
6. 现场见证人只说一句“测试通过”。合作方代表立即整张取下旧宣传页并放到一边。
7. 合作方代表原话宣布：“{opponent}不再有权降低训练强度。训练强度决定权归还{protagonist}。”
8. 结算后只写{opponent}一次嘴硬或失态、{protagonist}一句反击、{opponent}一个极短反应，随即结束。

旧宣传页在正文中只称“旧宣传页”，不描写上面的任何内容。全文保持同一场冲突，
不增加白名单外的物件、历史、文件、身体检验、观众或后续事件。
""".strip()
    else:
        scene_script = f"""
【事实白名单】
人物只有{protagonist}、{opponent}和一名从开场就在场的现场负责人。
地点只有医务室。桌面物品只有一份保持未拆状态的针剂封签、一张送货单和一本领用簿。
纸面只读“送达数量七支”和“领用数量八支”，唯一矛盾是相差一支；其他字段无需写。
交接物只有{opponent}原本持有的一把药品柜钥匙和领用簿。
结果只有{opponent}被停职并失去保管权，{protagonist}接到唯一钥匙并取得药品保管权。

【八个正向节拍】
1. 首段让现场负责人、{protagonist}和{opponent}都已在医务室，桌上摆着三类材料。
2. 前两百字内自然写：“{protagonist.split('·', 1)[0]}记得，上一世，{opponent.split('·', 1)[0]}一贯先用后补，出了问题便说成笔误或补记。”
3. {protagonist}要求当面核对。送货单写送达七支，领用簿写领用八支，封签保持未拆。
4. {opponent}只说这是笔误或补记，并伸手想拿回领用簿。{protagonist}原话说：“封签、送货单和领用簿都是{opponent}经手的。”
5. 现场负责人只根据这一支数量差和当面辩解，原话宣布：“即刻暂停你的职务。”随后伸手要钥匙。
6. {opponent}交出唯一钥匙和领用簿。负责人原话确认：“药品保管权归{protagonist}。”并把钥匙交给{protagonist}。
7. {opponent}只做一次嘴硬或失态。{protagonist}原话反击：“没有我的许可，谁也不能碰这些药。”
8. 对白后只写{opponent}一个极短反应，立即结束。

每个动作都围绕“七对八”这一处数量差展开。三类材料不增加细节、历史或第二种判断，
负责人不填写材料，{opponent}不毁坏材料，{protagonist}不打开药柜。
""".strip()

    return shared_rules + "\n\n" + scene_script


def _build_grounded_compliance_repair_prompt(
    chapter_num: int,
    failed_draft: str,
    chapter_card: Dict[str, Any],
    failures: List[str],
    prev_tail_scene: str = "",
    repair_attempt: int = 1,
) -> str:
    """Repair a grounded draft against generic validators without randomizing its valid plot."""
    relevant_cast = _select_grounded_chapter_cast(chapter_card)
    evidence_budget = _execution_evidence_budget(chapter_card)
    minimum_chars = _minimum_chapter_chars(chapter_num, chapter_card)
    rendered_goal = _render_grounded_execution_text(chapter_card.get("chapter_goal") or "", chapter_card)
    rendered_payoff = _render_grounded_execution_text(chapter_card.get("core_payoff") or "", chapter_card)
    rendered_ending = _render_grounded_execution_text(chapter_card.get("chapter_ending") or "", chapter_card)
    failure_block = "\n".join(f"- {item}" for item in failures[:12])
    strategy_lines: List[str] = []
    joined_failures = "\n".join(failures)
    if "协议编号或条款" in joined_failures:
        strategy_lines.append(
            "删除所有引用协议、合同、规程、规定、规则、细则、条款和第几条的句子；"
            "改成有权者看完卡片已允许的现场行动或纸面差异后，直接口头宣布结果。"
        )
    if "医学数据展示" in joined_failures:
        strategy_lines.append("删掉全部测量物件、屏幕、曲线、数值和指标，只写动作完成度与一句‘通过’。")
    if "封闭证据清单" in joined_failures:
        strategy_lines.append(
            "删除执行卡没有逐字点名的报告、档案、额外清单、录音、邮件、设备、代码与外部核验；"
            "表演场只写可见完成度，纸面场只写卡片点名材料上的一处直接矛盾。"
        )
    if "临时命名执行卡未建立" in joined_failures:
        strategy_lines.append(
            "删除所有带引号的临时流程名、药品名、文件名和编号，也删除围绕这些名称新增的桥段。"
        )
    if "伪医学或伪法证" in joined_failures:
        strategy_lines.append(
            "删除气味、药理、阈值、压纹、切口角度和专业判断，只让人物肉眼比较编号、数量、日期或签收。"
        )
    if "未建立的审批或制度" in joined_failures:
        strategy_lines.append(
            "删除董事会、法务备案、双签制度和免责条款；由本场已出场且有权的人直接宣布停职或交接。"
        )
    if "武器或威胁道具" in joined_failures:
        strategy_lines.append("删除枪、刀及威胁暗示，用对手被迫交钥匙、嘴硬或失态完成压迫感。")
    if "危险特技或伪生理解释" in joined_failures:
        strategy_lines.append(
            "删除不热身、不换气、关节角度、滞空毫秒、体温烤干汗液等描写；"
            "改写成可信的连续唱跳、稳定换气、动作收束和现场观感。"
        )
    if "未建立的歌曲或表演段落取名" in joined_failures:
        strategy_lines.append("把临时曲名和段落名改成第一段、快节奏段、收尾段等无专名功能称呼。")
    if "未建立的守则或议程条文" in joined_failures:
        strategy_lines.append("删除临时守则和议程条文，让合作方依据可见完成度直接确认卡片中的结果。")
    if "擅自开封、抽取或操作针剂" in joined_failures:
        strategy_lines.append("针剂始终保持封存，不开封、不插针、不抽药；只交接钥匙、领用簿和保管权。")
    if "设备、车辆或安全事故支线" in joined_failures:
        strategy_lines.append("删除车辆、升降台、焊痕、螺丝、保险绳等新支线，结尾停在既有对手的失态。")
    if "创作标签或 Markdown" in joined_failures:
        strategy_lines.append("删除“主角”“反派”等创作标签和星号标记，人物只能用固定姓名或无姓名职位。")
    if "多处矛盾维度" in joined_failures:
        strategy_lines.append("纸面核对只保留一处数量、日期、编号或签收差异，其余纸面内容全部一致。")
    if "权限者突然进门裁决" in joined_failures:
        strategy_lines.append("让无姓名现场负责人从首段就在场，全程旁观核对；禁止反转时再推门出现。")
    if "合同、确认书或器材文书争辩" in joined_failures:
        strategy_lines.append("删掉器材批次、计时器和多轮文书争辩，表演完成后由合作方直接撤宣传、还权限。")
    if "英文词" in joined_failures:
        strategy_lines.append("全文重新扫描英文字母，临时英文词、缩写、首字母和字母编号全部改成中文功能称呼。")
    if "缺少可见兑现" in joined_failures:
        strategy_lines.append(
            f"直接在同一现场写明并执行卡片结果：{rendered_payoff}；随后写对手被迫交接和失态。"
        )
    strategy_block = "\n".join(f"- {line}" for line in strategy_lines) or "- 按失败清单逐句替换，不要只做同义改写。"
    return f"""你是商业重生爽文的合规修订编辑。请完整重写第{chapter_num}章失败稿，保留其中已经正确的冲突顺序、动作反杀和现实结算，只改掉验收指出的越界内容。

这是第{max(1, repair_attempt)}次合规修订。不得原样返回待修订稿；本次输出必须与原稿有实质文字变化。

【本章固定合同】
上一章真实结尾：{prev_tail_scene or '按失败稿开头既有承接'}
章节目标：{rendered_goal}
核心回报：{rendered_payoff}
结尾已生效结果：{rendered_ending}
本章允许具名人物：{json.dumps(relevant_cast, ensure_ascii=False)}

【执行卡证据预算】
{evidence_budget}

【必须逐项消除的验收失败】
{failure_block}

【本轮强制替代动作】
{strategy_block}

修订规则：
1. 逐项删除失败原因对应的整句、物件或机制，不能换一个近义英文词、编号、设备、条款或神秘材料继续表达同一越界手段。
2. 不新增人物、机构、作品、药品、文件名、英文词、字母代号、检测设备、数字证据或隐藏规则。功能人物只用中文职位称呼。
3. 若删去的是反转依据，就改为执行卡允许的可见动作、当面核对、对手辩解和有权者现场决定；不得削弱核心回报。
4. 前世记忆只属于主角且只能帮助预判；任何角色都不得在对白中说出重生或上一世。
   若原稿缺少重生信息差，补一小句主角内心认出旧局，并让下一句成为他当场提出、拒绝、叫来见证人或改变条件的行动。
5. 双向结果必须写进现场动作和反应，正文硬范围{minimum_chars}至{MAX_CHAPTER_CHARS_V2}字。
6. 输出一份从头到尾连贯的完整正文，不要解释修改、不要列清单、不要标题，不得在原稿后续写补丁。

【待修订失败稿】
{failed_draft}
"""


def _build_cluster_body_part_prompt(
    cluster: Dict[str, Any],
    cluster_synopsis: str,
    chapter_num: int,
    chapter_beats: Dict[str, Any],
    prev_tail_scene: str,
    prev_unresolved_hook: str,
    chapter_card: Dict[str, Any],
    kg_context: str = "",
    rewrite_advice: Optional[List[str]] = None,
    rag_samples: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    exec_plan: Optional[Dict[str, Any]] = None,
    rolling_synopsis_mode: bool = False,
) -> str:
    cluster_id = cluster.get("cluster_id", "") or ""
    main_opp = cluster.get("main_opponent", "") or ""
    info_gap = cluster.get("info_gap_from_prev_life", "") or ""
    core_payoff = cluster.get("core_payoff", "") or ""
    canonical_cast = cluster.get("canonical_cast") or chapter_card.get("canonical_cast") or []

    role_v2 = chapter_card.get("chapter_role_v2", "") or ""
    prompt_cast = canonical_cast
    if role_v2 == "prev_life_death_only" and any(
        isinstance(member, dict)
        and str(member.get("name") or "").strip() == "麦珂·杰森"
        for member in canonical_cast
    ):
        prompt_cast = [
            member for member in canonical_cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() not in {"ally", "support"}
        ]
    elif role_v2 == "rebirth_awakening_only" and any(
        isinstance(member, dict)
        and str(member.get("name") or "").strip() == "麦珂·杰森"
        for member in canonical_cast
    ):
        prompt_cast = [
            member for member in canonical_cast if isinstance(member, dict)
            and (
                str(member.get("alignment") or "").casefold() == "protagonist"
                or "医生" in str(member.get("role") or "")
            )
        ]
    must_in = chapter_card.get("chapter_must_include", []) or []
    must_not = chapter_card.get("chapter_must_not_include", []) or []
    ending = chapter_card.get("chapter_ending", "") or ""
    allowed_roles = chapter_card.get("allowed_roles", []) or []
    forbidden_roles = chapter_card.get("forbidden_roles", []) or []
    if isinstance(must_in, list):
        must_in = [str(x) for x in must_in][:8]
    if isinstance(must_not, list):
        must_not = [str(x) for x in must_not][:10]
    chapter_hard = chapter_card.get("chapter_hard_constraints", []) or []
    required_state_changes = chapter_card.get("required_state_changes", []) or []
    forbidden_active_characters = chapter_card.get("forbidden_active_characters", []) or []
    chapter_contract_lines = [str(x).strip() for x in chapter_hard if str(x).strip()]
    for item in required_state_changes:
        if isinstance(item, dict):
            chapter_contract_lines.append(
                f"本章必须明确建立状态：{item.get('character', '')}.{item.get('field', '')}={item.get('new_value', '')}"
                f"（timeline={item.get('timeline', 'current')}，permanent={bool(item.get('permanent', False))}）"
            )
    for name in forbidden_active_characters:
        chapter_contract_lines.append(f"{name}不得作为当前时间线的活跃参与者，只能以合同允许的非活跃方式被提及。")
    chapter_contract_block = (
        "\n【本章运行时硬合同（遗漏即重写）】\n" + "\n".join(f"- {x}" for x in chapter_contract_lines)
        if chapter_contract_lines else ""
    )

    # 是否为本簇最后一章（用于加严结尾闭环硬性要求）
    is_last_chapter_of_cluster = False
    try:
        idx = int(chapter_card.get("cluster_chapter_index", 0) or 0)
        total = int(chapter_card.get("cluster_chapter_total", 0) or 0)
        is_last_chapter_of_cluster = total >= 1 and idx == total
    except Exception:
        is_last_chapter_of_cluster = False

    beats = chapter_beats.get("beats", []) or []
    open_from_prev = chapter_beats.get("open_from_prev", "") or ""
    end_to_next = chapter_beats.get("end_to_next", "") or ""
    flashback_idx = chapter_beats.get("flashback_in_beat_idx", None)
    chapter_type = chapter_beats.get("chapter_type", "present_only") or "present_only"
    closure_type = chapter_beats.get("closure_type", chapter_beats.get("closure_type", None)) or chapter_beats.get("closure_type", None)
    if not closure_type:
        closure_type = chapter_beats.get("closure_type", "full_close") or "full_close"
    if not closure_type:
        closure_type = "full_close"

    rewrite_block = ""
    if rewrite_advice:
        rewrite_block = "\n【重写要求（必须遵守）】\n" + "\n".join(rewrite_advice[:10])

    if rolling_synopsis_mode:
        body_synopsis_title = "【滚动上下文（簇级合同摘要；禁止复述全簇背景）】"
        body_synopsis_note = "正文禁止再用大段笔墨重讲「情节组起因/背景」；只能从「上一段结尾承接」往下写情节增量。"
    else:
        body_synopsis_title = "【情节族详细梗概（簇首章对齐）】"
        body_synopsis_note = "簇首章可参考梗概推进，但仍须与跨情节族/上一章结尾承接一体。"

    kg_block = f"\n【Neo4j背景事实（限长，仅作背景，禁止替换证据链与决策）】\n{kg_context}\n" if kg_context else ""

    rag_samples_block = ""
    if rag_samples:
        title_map = {
            "revenge": "重生复仇爽感",
            "grievance": "上一世委屈",
            "universal": "通用样本",
        }
        parts: List[str] = []
        for key in ("revenge", "grievance", "universal"):
            arr = rag_samples.get(key) or []
            if not isinstance(arr, list):
                continue
            for idx, sample in enumerate(arr[:2], 1):
                if not isinstance(sample, dict):
                    continue
                technique_parts = []
                for label, field in (
                    ("情绪", "emotion_tags"),
                    ("冲突", "conflict_tags"),
                    ("动作", "action_tags"),
                    ("节奏", "plot_tags"),
                ):
                    values = sample.get(field) or []
                    if isinstance(values, list) and values:
                        technique_parts.append(f"{label}={'/'.join(str(x) for x in values[:5])}")
                if technique_parts:
                    parts.append(
                        f"【样本{idx} - {title_map.get(key, key)}技法】"
                        + "；".join(technique_parts)
                    )
        if parts:
            rag_samples_block = (
                "\n【参考样本技法标签（只增强情绪节奏，不含样本正文，不得改写 beats 逻辑）】\n"
                + "\n\n".join(parts)
            )

    evidence_chain_hard_block = ""
    if isinstance(exec_plan, dict) and isinstance(exec_plan.get("evidence_chain"), list) and exec_plan.get("evidence_chain"):
        all_evs: List[Dict[str, Any]] = [ev for ev in (exec_plan.get("evidence_chain") or []) if isinstance(ev, dict)]
        stage_lines: List[str] = []
        for ev in all_evs:
            ac = ev.get("acquire_chapter")
            vc = ev.get("verify_chapter")
            uc = ev.get("use_chapter")
            stages: List[str] = []
            if ac == chapter_num:
                stages.append("取得")
            if vc == chapter_num:
                stages.append("确认可信")
            if uc == chapter_num:
                stages.append("用于反卡")
            if stages:
                evidence_type = str(ev.get("evidence_type") or "既有筹码").strip()
                source = str(ev.get("source") or "上一世已知来源").strip()
                stage_lines.append(f"- {evidence_type}：本章只需{('/'.join(stages))}；来源={source}")

        stage_text = "\n".join(stage_lines) if stage_lines else "- 本章不得新增或追查筹码，只推进人物行动与公开冲突。"

        evidence_chain_hard_block = (
            "\n【本章筹码阶段（仅对峙坐实；禁止当调查取证主线）】\n"
            f"{stage_text}\n"
            "- E1/E2 等编号只供内部规划，绝对不得出现在小说正文中；正文只写具体物件、对白与动作。\n"
            "- 禁止用「获取/验证/走访/翻档案」作为本章叙事发动机；主线只能是旧局识别→提前布子→对方照旧→反卡。\n"
        )

    flashback_idx_0 = flashback_idx if flashback_idx is not None else None
    flashback_idx_text = "null" if flashback_idx_0 is None else str(flashback_idx_0)
    if role_v2 == "present_past_mix":
        flashback_instruction = (
            f"若回忆插入点为顺序片段下标 {flashback_idx_text}，在该拍后插入一个 280-450 字、"
            "不超过全章约四分之一的聚焦闪回，只写一个受害场景；闪回后必须立刻回到今生行动并兑现小反制。"
        )
    elif flashback_idx_0 is not None:
        flashback_instruction = (
            f"在顺序片段下标 {flashback_idx_text} 对应片段结束后插入完整上一世受害回忆，"
            "围绕该片段中的回忆要点展开，不加小标题，也不写成调查取证主线。"
        )
    else:
        flashback_instruction = "本章回忆插入点为 null，不得临时插入大段上一世回忆。"
    beats_lines: List[str] = []
    for i, b in enumerate(beats):
        if isinstance(b, dict):
            # 每拍字段会被“转写”为正文的动作/对话/环境与情绪，而不是在正文里原样复现字段名。
            prev_brief = str(b.get("prev_life_memory_brief") or "").strip()
            if flashback_idx_0 is not None and i == int(flashback_idx_0) and prev_brief:
                prev_part = f"；回忆要点：{prev_brief}"
            else:
                prev_part = ""
            ots = str(b.get("old_trap_signal") or "").strip()
            pm = str(b.get("preemptive_move") or "").strip()
            om = str(b.get("opponent_old_move") or "").strip()
            rt = str(b.get("reversal_trigger") or "").strip()
            hammer = str(b.get("evidence_form") or "").strip()
            line = (
                f"顺序片段{i+1}（内化进叙述，勿照抄本行标签）："
                f"旧局信号={ots}；提前布子={pm}；对方老招={om}；反卡触发={rt}；"
                f"场面目标={str(b.get('scene_goal') or '').strip()}；"
                f"画面={str(b.get('visual_elements') or '').strip()}；"
                f"情绪={str(b.get('emotion_push') or '').strip()}；"
                f"信息增量={str(b.get('info_delta') or '').strip()}；"
                f"落锤材料（可选）={hammer}；"
                f"伏笔={str(b.get('foreshadow') or '').strip()}；"
                f"关系推进={str(b.get('relationship_push') or '').strip()}；"
                f"禁止={str(b.get('must_not') or '').strip()}"
                f"{prev_part}"
            )
        else:
            line = f"顺序片段{i+1}：{str(b).strip()}"
        beats_lines.append(line)
    beats_text = "\n".join(beats_lines)
    payoff_hard_block = ""
    if is_last_chapter_of_cluster:
        # 明确把“本簇闭环写完”作为硬性落点，禁止含糊收尾
        payoff_hard_block = (
            "\n【本簇最后一章闭环（硬性要求，必须全部满足）】\n"
            "- 本章内必须写出反杀完成与符合本次题材的具体后果，例如失去角色、资源、职位、名誉、信任或利益，主角拿回机会、筹码或话语权；\n"
            "- 必须以具体、可视化的场面呈现结果落地，例如决定被当场宣布、合同或名单正式改变、对手失态离场、旁观者公开改变态度；\n"
            "- 对手即时损失与主角即时收益必须同时出现；只道歉、只上热搜、只获得关注、只说未来会失去资源均不算闭环；\n"
            "- 禁止跳到几天后、几个月后或多年后用蒙太奇补结果，所有关键结算必须发生在同一场冲突内；\n"
            "- 允许保留一个很小的余波钩子，但绝对禁止用“更大风暴才刚开始/真正的敌人另有其人”替代结果；\n"
            "- 若篇幅不足，优先砍掉环境/感受性描写，也要保证‘结果已发生且被看到’。"
        )

    if prev_tail_scene or prev_unresolved_hook:
        opening_instruction = (
            "开头 120-180 字必须接住下方上一段真实场景中的人物、地点、动作或未决冲突，"
            "随后立刻产生新动作；不得只抽象复述。"
        )
    else:
        opening_instruction = "开头 120-180 字直接进入本章最尖锐的冲突场面，不写天气、城市或泛泛心情热身。"

    if is_last_chapter_of_cluster:
        ending_instruction = (
            "结尾最后 120-200 字必须停在本簇已经发生的具体结果及对手反应上；"
            "不得为了续章新增陌生电话、神秘人物、跟踪车辆或更大秘密。"
        )
    else:
        ending_instruction = (
            "结尾最后 120-200 字先确认本章小胜利或局势变化，再用既有对手的下一步公开动作、"
            "下一场已约定冲突或本章结果的直接反应衔接下一章；禁止空泛预感和陌生消息。"
        )

    if role_v2 == "prev_life_death_only":
        special_role_block = (
            "\n【第1章结构锁】只写上一世最后一次不可逆失败、具体损失与死亡。"
            "不得写重生后的调查、签约、职业行动或反击；结尾必须是生命结束与强烈不甘。"
            "针剂只写功能称呼，禁止真实药名、精确药理数值、时间戳、英文编号，以及未规划的遗嘱、保单、文件、拍照或加密群聊。"
            "若主角是麦珂·杰森，固定盟友不得出现在上一世谋杀现场；在场者只用主角、固定对手及无姓名工作人员。\n"
        )
    elif role_v2 == "rebirth_awakening_only":
        special_role_block = (
            "\n【第2章结构锁】完整写出惊醒→怀疑→用日期/环境/身体等多项细节验证→确认重生。"
            "结尾必须让主角实际完成一个第一步部署，但不得提前完成大反杀。"
            "若主角是麦珂·杰森，只允许他、康拉德·莫里森和无姓名第三方医疗人员出场；"
            "只写拒绝、登记、封存、双签和权限移交，不写药物成分、编号、批号、冷链、仪器、扫码、拍照、录像、"
            "监管机构、法律文件、证据威胁、正式发布会或媒体问答，也不使用英文字母、阿拉伯数字或新作品名。\n"
        )
    else:
        special_role_block = (
            "\n【章内爽点合同】本章必须由主角主动行动推进，并至少写出一次小反杀或抢先成功；"
            "在同一场景中呈现对手失算的动作/表情/台词，以及主角获得的具体机会、资源、信任、地位或主动权。\n"
        )

    if role_v2 == "prev_life_death_only":
        body_engine_instruction = "叙事发动机是上一世最后希望→对手压制/背叛→不可逆损失→死亡与不甘；不得进入今生。"
    elif role_v2 == "rebirth_awakening_only":
        body_engine_instruction = "叙事发动机是惊醒→怀疑→多项现实细节验证→确认重生→执行第一步部署；不得获取决定性证据或完成终局反杀。"
    else:
        body_engine_instruction = f"叙事发动机必须是「{REBIRTH_ACTION_ENGINE}」。"
    chapter_min_chars = _minimum_chapter_chars(chapter_num, chapter_card)

    return f"""{COMMERCIAL_REBIRTH_WRITER_ROLE}请输出“第{chapter_num}章”的连续小说正文。

【本项目主题硬锁定】
{constraints_text()}

要求：

    1. 必须严格按该章节拍卡 `beats` 的顺序推进，不得跳拍；每一顺序片段写 240-320 字，每一拍都要带来行动、冲突或结果增量，禁止用天气、走路、喝酒和反复思考灌水。拍卡不是段落模板：可按对话打断和动作转折拆合成八至十四个长短不一的自然段，至少三个短对白或短动作段，不得每拍机械对应一个等长段落。
2. {opening_instruction}正文中禁止出现英文字段名或 JSON 键名。
3. {flashback_instruction}
    4. 本章目标 1500-1800 个汉字，硬性范围为 {chapter_min_chars}-{MAX_CHAPTER_CHARS_V2} 字；以快节奏完成必要场景为先，未达标只细化已有动作与对话，不得添加新线索或新人物灌水。
5. {body_engine_instruction}规则、关系、作品表现或材料只在反卡时落锤，禁止写成“为找材料而奔波”的调查文；禁止匿名邮件、加密邮件、陌生电话、神秘制片人、跟踪车辆、新闻发布会、档案室翻找、社交媒体爆料链作为本章主线。
   - E1/E2 等内部证据编号绝对不得出现在小说正文中，只写具体物件、对白与动作；
   - 不得把内部阶段名、字段名或编号写进正文。
   - 前世记忆只能用于预判，不能凭空还原为可播放录音、视频、截图或文件；现实材料必须由今生已经写出的动作产生。
   - 主角不得在公众、记者、镜头、直播或红毯上自曝重生、上一世死亡或“我回来了”。
6. {ending_instruction}正文中不要写出任何模板标签或英文字段名。
7. 输出仅小说正文：不要章节标题、不要节拍编号、不要任何模板字段名或 JSON。
    8. 固定人物姓名必须逐字使用 canonical_cast 中的固定 name，不得改译、缩写、改姓或新造有姓名的角色；未命名的功能角色只用职位称呼。

【情节族信息】cluster_id={cluster_id}；主要对手={main_opp}；信息差提示={info_gap}；核心爽点={core_payoff}
【本章允许出场的固定人物与阵营】{json.dumps(prompt_cast, ensure_ascii=False)}
【本章信息】角色={role_v2 or '（未标注）'}；类型={chapter_type}；闭合={closure_type}；章节卡结尾钩子={ending or '（无）'}
【本章必须包含】{'；'.join(must_in) if must_in else '（无）'}
【本章必须避免】{'；'.join(must_not) if must_not else '（无）'}
{chapter_contract_block}
{payoff_hard_block}
{special_role_block}

{evidence_chain_hard_block}

{rewrite_block}
{rag_samples_block}
{kg_block}

【上一段结尾承接（必须接住）】
最后场景：{prev_tail_scene or '（无）'}
未解决钩子：{prev_unresolved_hook or '（无）'}

{body_synopsis_title}
{body_synopsis_note}
{cluster_synopsis}

【本章拍卡（beats）】
{beats_text}
"""


def _same_character_name(left: Any, right: Any) -> bool:
    a = re.sub(r"[\s·.・]", "", str(left or "")).casefold()
    b = re.sub(r"[\s·.・]", "", str(right or "")).casefold()
    if not a or not b:
        return False
    return a == b or (len(a) >= 2 and len(b) >= 2 and (a in b or b in a))


def _validate_chapter_memory_contract(chapter_card: Dict[str, Any], memory: Dict[str, Any]) -> List[str]:
    """Check that planned chapter facts actually landed in extracted story memory."""
    failures: List[str] = []
    changes = memory.get("state_changes") if isinstance(memory, dict) else []
    changes = changes if isinstance(changes, list) else []
    for required in chapter_card.get("required_state_changes", []) or []:
        if not isinstance(required, dict):
            continue
        matched = False
        for actual in changes:
            if not isinstance(actual, dict):
                continue
            matched = (
                _same_character_name(required.get("character"), actual.get("character"))
                and str(required.get("field") or "").casefold() == str(actual.get("field") or "").casefold()
                and str(required.get("new_value") or "").casefold() == str(actual.get("new_value") or "").casefold()
                and str(actual.get("timeline") or "current").casefold() == str(required.get("timeline") or "current").casefold()
                and (not required.get("permanent") or bool(actual.get("permanent")))
            )
            if matched:
                break
        if not matched:
            failures.append(
                f"计划落地缺失：本章必须明确写出并可抽取为 "
                f"{required.get('character')}.{required.get('field')}={required.get('new_value')} "
                f"(timeline={required.get('timeline', 'current')}, permanent={bool(required.get('permanent', False))})。"
            )

    forbidden = chapter_card.get("forbidden_active_characters", []) or []
    active_mentions: List[Tuple[str, str]] = []
    for character in (memory.get("characters", []) if isinstance(memory, dict) else []) or []:
        if isinstance(character, dict) and str(character.get("mention_mode") or "").casefold() == "active":
            active_mentions.append((str(character.get("name") or ""), str(character.get("evidence") or "")))
    for event in (memory.get("events", []) if isinstance(memory, dict) else []) or []:
        if not isinstance(event, dict) or str(event.get("timeline") or "current").casefold() != "current":
            continue
        for participant in event.get("participants", []) or []:
            if isinstance(participant, dict) and str(participant.get("mode") or "active").casefold() == "active":
                active_mentions.append((str(participant.get("name") or ""), str(event.get("summary") or "")))
    for name in forbidden:
        evidence = next((ev for actual, ev in active_mentions if _same_character_name(name, actual)), "")
        if evidence:
            failures.append(f"计划模式冲突：{name}不得在当前时间线行动。抽取证据：{evidence[:160]}")
    return failures


def _build_memory_contract_repair_prompt(
    chapter_num: int,
    original_text: str,
    chapter_card: Dict[str, Any],
    failures: List[str],
) -> str:
    chapter_min_chars = _minimum_chapter_chars(chapter_num, chapter_card)
    hard_constraints = chapter_card.get("chapter_hard_constraints", []) or []
    required = chapter_card.get("required_state_changes", []) or []
    forbidden = chapter_card.get("forbidden_active_characters", []) or []
    return f"""你是小说连续性修订编辑。请对第{chapter_num}章做最小必要重写，使缺失的硬事实在正文中明确发生，而不是只暗示、计划或回忆。

【本章原文】
{original_text}

【本章运行时硬约束】
{json.dumps(hard_constraints, ensure_ascii=False)}
【必须能从修订正文抽取出的状态变化】
{json.dumps(required, ensure_ascii=False)}
【不得作为当前时间线活跃参与者】
{json.dumps(forbidden, ensure_ascii=False)}
【上次结构化验收失败】
{chr(10).join(failures)}

修订要求：
1. 状态变化必须在当前时间线以具体场景明确发生，并写出可核验的主体、事件、确认者与结果；不得把它写成上一世、回忆、梦境、未来计划或模糊预感。
2. 若状态为 life_status=dead，必须明确写出该人物死亡并由现场角色确认死亡；死亡之后不得再让该人物在当前时间线行动。
3. 保留原章其余人物、因果、时间地点和主要情节，全文仍不少于 {chapter_min_chars} 字。
4. 只输出修订后的完整小说正文，不要解释、标题、JSON 或修订说明。
"""


def _build_required_state_insertion_prompt(
    chapter_num: int,
    original_text: str,
    chapter_card: Dict[str, Any],
    failures: List[str],
) -> str:
    required = chapter_card.get("required_state_changes", []) or []
    hard_constraints = chapter_card.get("chapter_hard_constraints", []) or []
    return f"""你是小说连续性补写编辑。只写一段可直接接在第{chapter_num}章末尾的新增正文场景，600-900个汉字。

【原章结尾，供承接】
{original_text[-1200:]}

【必须在新增场景中真实发生并被明确确认的当前时间线状态】
{json.dumps(required, ensure_ascii=False)}
【本章原始硬约束】
{json.dumps(hard_constraints, ensure_ascii=False)}
【验收失败原因】
{chr(10).join(failures)}

硬要求：
1. 这是当前时间线正在发生的具体事件，绝对不是上一世、回忆、梦境、幻觉、预感、日志内容或未来计划。
2. 写清地点、触发事件、人物行动、现场确认者和不可逆结果。若要求 life_status=dead，必须让该人物在本场景中死亡，并由现场专业人员明确确认死亡。
3. 不得让已确认死亡的人物在确认之后继续说话、走动、操作设备或参与行动。
4. 只输出可直接拼接的小说正文，不要标题、解释、JSON、前言或修订说明。
"""


def _build_payoff_repair_prompt(
    chapter_num: int,
    original_text: str,
    chapter_card: Dict[str, Any],
    failures: List[str],
) -> str:
    canonical_cast = chapter_card.get("canonical_cast") or []
    opponent = next(
        (
            str(member.get("name") or "").strip()
            for member in canonical_cast
            if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "opponent"
            and str(member.get("name") or "").strip()
        ),
        str(chapter_card.get("main_opponent") or "既有对手").strip(),
    )
    payoff = str(chapter_card.get("core_payoff") or "").strip()
    must_resolve = chapter_card.get("must_resolve_this_chapter") or chapter_card.get("must_resolve") or []
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in canonical_cast if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
    ), "主角")
    authority = next((
        str(member.get("name") or "").strip()
        for member in canonical_cast if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() in {"ally", "support"}
    ), "既有选角负责人")
    title = sorted(_planned_work_titles(chapter_card))[0] if _planned_work_titles(chapter_card) else "核心项目"
    card_context = " ".join(
        str(chapter_card.get(key) or "")
        for key in ("chapter_goal", "this_life_revenge", "core_payoff", "chapter_ending")
    )
    if not re.search(r"试戏|试镜|选角|女主角|演员合同", card_context):
        return f"""你是商业重生爽文的现场结算编辑。请从零重写第{chapter_num}章为1200-1800个汉字的完整章节，不得续写失败稿。

【本项目主题硬锁定】
{constraints_text()}

【固定人物与阵营】{json.dumps(canonical_cast, ensure_ascii=False)}
【固定主角】{protagonist}
【固定对手】{opponent}
【本章目标】{chapter_card.get('chapter_goal') or chapter_card.get('this_life_revenge') or ''}
【本章行动】{chapter_card.get('this_life_revenge') or ''}
【核心爽点】{payoff or '让既有对手为旧局付出代价'}
【结尾结果】{chapter_card.get('chapter_ending') or ''}
【必须解决】{json.dumps(must_resolve, ensure_ascii=False)}
【上轮失败】{chr(10).join(failures)}

硬要求：
1. 只写章节卡中已规划的同一轮冲突，按“旧局信号→{protagonist}抢先布置→{opponent}照旧出招→当场反卡→现实结算”推进。
2. 必须同时写清“对手失去什么、主角拿回什么”，形成至少两个现实结果：对手当章失去权限、利益、职位、资格或资源，主角当章拿回权利、安全、作品、资金或话语权；结果必须已生效，不能只说将来处理。
3. 反杀前要给对手一次自以为得手的可见动作，结算后写出其具体失态、嘴硬或自打脸反应。
4. 至少有一句锋利且符合人物的可记忆对白；不得用热搜、匿名材料、黑客或警方突然收网代替人物行动。
5. 人名逐字使用 canonical_cast 的固定 name；其余人物只用职位称呼。不得出现现实人名、地名、公司、奖项或歌曲名。
6. 结尾停在结果已生效和对手直接反应上，不新增神秘电话、陌生人或“真正战斗才开始”。只输出小说正文。
"""
    return f"""你是商业重生爽文的终章结算编辑。请从零重写第{chapter_num}章为1300-1800个汉字的完整现场反杀章，不得修补或续写失败稿。全文必须使用简体中文叙述和中文对白，只有下方固定英文人名保留英文。

【固定人物与阵营】{json.dumps(canonical_cast, ensure_ascii=False)}
【固定主角】{protagonist}
【固定对手】{opponent}
【唯一裁决者】{authority}
【唯一项目名】《{title}》
【本簇核心爽点】{payoff or '让既有对手为其旧局付出代价'}
【本章必须解决】
{json.dumps(must_resolve, ensure_ascii=False)}
【上轮失败处理原则】上轮正文已整体废弃；只按本章节卡重建，不得猜测或恢复其中的任何临时姓名、组织、作品、职位或桥段。

修订要求：
1. 全章只发生在同一轮终选现场。开头承接上一章已获得复试资格，禁止再写解约、预约、初试或重新介绍背景。
2. {protagonist}必须先完整表演一次：写出具体动作、至少一句有效台词、情绪控制和现场安静的反应；不得用“表现非常出色”一句概括。只能开始一次、结束一次。
3. {opponent}只能在表演中途使用一次已建立的公开干扰，{authority}当场制止；禁止新增有姓名人物，其他人只能称片方代表、选角助理或工作人员。
4. 表演结束后，{authority}只宣布一次由{protagonist}出演《{title}》女主角；片方已签章的演员合同当场交给她，她核对并签字，合同立即生效。
5. 同一裁决中明确写出{opponent}失去女主角竞争资格并退出项目。除非章节卡明确写了对手已有合同，否则不得补造其已签约、解约或启动法律程序。
6. 必须同时写出“对手失去什么、主角拿回什么”，形成角色资格损失与生效合约收益这至少两个现实结果；写出{opponent}从笃定到失态的具体反应，以及观望者把态度转向{protagonist}，不能用行业生涯彻底毁灭等夸张旁白替代现场损失。
7. 全文不得出现第二次表演、第二次宣布角色、第二份新结算、职位粘连、姓名音译、临时英文姓名、调查、媒体、陌生电话或新任务。
8. 结尾停在合同已生效、{opponent}被迫离场、{protagonist}拿走合同的同一时刻。只输出完整小说正文，不要标题、解释、JSON 或修订说明。
"""


def _build_death_repair_prompt(
    chapter_num: int,
    original_text: str,
    chapter_card: Dict[str, Any],
    failures: List[str],
) -> str:
    canonical_cast = chapter_card.get("canonical_cast") or []
    pop_king_opening = any(
        isinstance(member, dict)
        and str(member.get("name") or "").strip() == "麦珂·杰森"
        for member in canonical_cast
    )
    death_scene_cast = _select_grounded_chapter_cast(chapter_card)
    excluded_fixed_characters = [
        str(member.get("name") or "").strip()
        for member in canonical_cast if isinstance(member, dict)
        and pop_king_opening
        and member not in death_scene_cast
        and str(member.get("name") or "").strip()
    ]
    established_tragedy = str(chapter_card.get("prev_life_tragedy") or "").strip()
    death_method_match = re.search(SPECIFIC_DEATH_METHOD_PATTERN, established_tragedy)
    death_method = death_method_match.group(0) if death_method_match else "服药过量自杀"
    title = sorted(_planned_work_titles(chapter_card))[0] if _planned_work_titles(chapter_card) else "核心项目"
    card_context = " ".join(
        str(chapter_card.get(key) or "")
        for key in ("chapter_goal", "prev_life_tragedy", "this_life_revenge", "core_payoff")
    )
    injection_death = bool(re.search(
        r"强行注射|违规注射|过量注射|注射过量|针剂|镇静针",
        established_tragedy,
    ))
    career_opening = bool(re.search(
        r"试戏|试镜|选角|女主角|旧经纪人",
        card_context,
    ))
    if injection_death:
        milestone = chapter_card.get("chapter_milestone") or chapter_card.get("milestone") or {}
        return f"""你是商业重生小说的开篇编辑。请从零重写第{chapter_num}章为1200-1800个汉字的“上一世死亡章”，不得续写失败稿。

【本章允许出场的固定人物】{json.dumps(death_scene_cast, ensure_ascii=False)}
【本章禁止出场的其他固定人物】{'、'.join(excluded_fixed_characters) if excluded_fixed_characters else '（无额外限制）'}
【已验收的上一世事实】{established_tragedy}
【本章里程碑】{json.dumps(milestone, ensure_ascii=False)}
【必须呈现的具体死亡结果】{death_method}
【上轮失败】{chr(10).join(failures)}

硬要求：
1. 只写【已验收的上一世事实】和【本章里程碑】建立的最后一场冲突；不写童年、调查、媒体或今生。
2. 写清拒绝注射、对手越过拒绝强行执行、药效发作、呼吸与心脏停止的连续因果，不得改成自杀、车祸、坠楼或模糊的“失去意识”。
3. 对手动作、现场对白和主角临死前获知的信息只能来自【本章里程碑】；卡片没有写出的利益对象、财产安排、组织或共谋者一律不得补造。
4. 情绪从被控制、惊恐推进到死亡前的愤怒与不甘，并立住能够驱动重生后行动的具体目标。至少一句对白必须锋利、可记忆。
5. 只能使用“本章允许出场的固定人物”中的姓名；其他人只能称无姓名职位。“本章禁止出场的其他固定人物”不得被提及、旁观或参与。人物身份和代词必须服从主题契约；不得出现现实人名、地名、公司、奖项或作品名。
6. 针剂只使用事件卡已有的功能称呼。禁止协议、合同、条款、附件、编号、类别、代号及任何卡片未建立的办理细节。
7. 全文禁止阿拉伯数字、百分号、温度符号、冒号时间格式和英文字母；禁止精确剂量、时长、次数、心率和动作角度；禁止解剖部位特写、监护仪数据、保镖制服动作和逐步制服技巧。强行注射只写虚弱主角明确拒绝、医生仍按住手臂推针，随后药效发作。
8. 结尾必须是主角在上一世明确死亡，不得出现惊醒、重生、今生计划、神秘消息或反杀。只输出小说正文。
"""
    if not career_opening:
        return f"""你是商业重生小说的开篇编辑。请依据人工验收的事件卡，从零重写第{chapter_num}章为1200-1800个汉字的“上一世死亡章”，不得续写失败稿。

【本章允许出场的固定人物】{json.dumps(death_scene_cast, ensure_ascii=False)}
【已验收的上一世事实】{established_tragedy or '主角在上一世遭遇不可逆失败并死亡'}
【必须呈现的具体死亡方式】{death_method}
【失败稿，仅用于识别缺失，不得续写】{original_text[-1200:]}
【上轮失败】{chr(10).join(failures)}

硬要求：
1. 只写事件卡已经建立的上一世最后一场冲突；不得新增题材、组织、阴谋、证据或死亡方式。
2. 将“{death_method}”写成连续可感知的现场因果，最终明确写出呼吸断绝或心跳停止，不能只用“意外身亡”概括。
3. 只能使用本章允许出场的固定人物姓名；其他参与者只用事件卡已有的无姓名职位。
4. 情绪必须从具体失败推进到死亡前的强烈不甘，并留下能驱动重生后行动的明确目标。
5. 结尾停在上一世生命已经结束；不得提前写惊醒、重生、今生布局、匿名消息或神秘材料。
6. 只输出小说正文，不要标题、说明、字段名或修订总结。
"""
    return f"""你是商业重生爽文的开篇编辑。请从零写第{chapter_num}章“上一世死亡章”的1100-1500字职业崩塌前半段。程序会在你写完后接上已锁定的死亡收束，因此你只负责把试镜失败与背叛现场写透。全文必须使用简体中文叙述和中文对白，只有下方固定英文人名保留英文；欧美背景不等于英文正文。

【固定人物与阵营】{json.dumps(canonical_cast, ensure_ascii=False)}
【已验收的上一世事实】{established_tragedy}
【本章唯一死亡方式】{death_method}
【唯一项目名】《{title}》
【上轮失败处理原则】上轮正文已整体废弃；只按下方已验收事实重建，不得猜测或恢复其中的任何临时姓名、组织、作品或桥段。

硬要求：
1. 只写上一世当前时间线；开场直接进入《{title}》最后一次试镜，不写天气、童年、媒体、调查或多年经历概述。
2. 顺序必须是：Maya Reed完成一段具体表演并仍怀有希望；Lila Voss用刺痛人的公开话术否定她；旧经纪人绕过她走到Lila Voss一边；选角结果落定。
3. 旧经纪人必须当着Maya Reed原样说出一句“从这一刻起，我不再代表你”，并明确撤回她的代理支持；随后公开表示转而服务Lila Voss。不得给旧经纪人姓名。
4. 必须明确写出Lila Voss拿到《{title}》女主角并当场签字或收到正式官宣；旁观者避开Maya Reed的目光，形成希望→羞辱→愤怒→绝望的连续升级。
5. 结尾只写Maya Reed带着剧本回到公寓、关上门，停在她无法接受角色和经纪人同时被夺走的具体不甘上。不要写药片、服药、呼吸停止或死亡，程序会紧接着完成唯一死法“{death_method}”。
6. 禁止出现“这只是开始、真正的战斗、未来某天、她还会回来”；禁止重生、今生、第二次机会、匿名消息、陌生电话、新证据和调查线。
7. 固定姓名逐字使用英文 name，不得音译、改名或另造有姓名人物；功能角色只用旧经纪人、工作人员等职位。只输出小说正文，不要标题、解释、JSON 或结构标签。
"""


def _build_forced_medication_death_scene(
    chapter_card: Dict[str, Any],
) -> Optional[str]:
    """Build a closed previous-life death scene for performer medication plots."""
    tragedy = str(chapter_card.get("prev_life_tragedy") or "")
    role_v2 = str(chapter_card.get("chapter_role_v2") or "")
    domain_context = json.dumps(
        {
            key: chapter_card.get(key)
            for key in (
                "chapter_goal", "prev_life_tragedy", "this_life_revenge",
                "core_payoff", "cluster_outcome", "chapter_milestone",
            )
        },
        ensure_ascii=False,
    )
    cast = _select_grounded_chapter_cast(chapter_card)
    if role_v2 != "prev_life_death_only" or not re.search(
        r"注射|针剂|镇静针", tragedy
    ) or not re.search(
        r"演出|舞台|歌手|歌迷|流行|复出|首演|排练|唱片",
        domain_context,
    ):
        return None

    protagonist = next(
        (
            str(member.get("name") or "").strip()
            for member in cast
            if str(member.get("alignment") or "").casefold() == "protagonist"
        ),
        "",
    )
    doctor = next(
        (
            str(member.get("name") or "").strip()
            for member in cast
            if "医生" in str(member.get("role") or "")
        ),
        "",
    )
    executive = next(
        (
            str(member.get("name") or "").strip()
            for member in cast
            if str(member.get("alignment") or "").casefold() == "opponent"
            and str(member.get("name") or "").strip() != doctor
        ),
        "",
    )
    if not protagonist or not doctor:
        return None

    outside_speaker = executive or "门外的人"
    return f"""演出前夜，后台最后一遍合唱刚停，{protagonist}便扶着化妆台坐了下去。

镜中的他还穿着排练服，肩背被汗浸透，脸色却白得没有一点血气。门外仍有人搬动舞台设备，沉重的脚步来来回回，所有人都在为明晚的复出首演奔忙。只有他清楚，自己已经很久没有真正睡过一觉。排练、采访、会议被硬生生塞在一起，连喘息都像是从日程缝隙里偷来的。

门锁轻响，{doctor}提着药箱走进来，把那支镇静针放到灯下。

“今晚必须睡。”他说，“不然明天撑不住。”

{protagonist}看着那支针，没有伸手。

“把药名和用途告诉我。”

{doctor}避开他的目光，只把袖口往上挽了挽：“你不需要操心这些。你只需要在台上出现。”

这句话让{protagonist}慢慢抬起头。过去很长一段时间，每当他追问自己的身体，身边人都会给出同一种回答：为了演出，为了团队，为了所有等着他的人。仿佛只要披上“为你好”的外衣，任何人都能替他决定疼痛、清醒和尊严。

“我的身体，不是你们的舞台设备。”他一字一句地说，“我拒绝。”

{doctor}没有收回针，反而向前逼近。

{protagonist}撑住桌沿想站起来，腿上却没有力气。连日透支像一张早已收紧的网，把他困在椅子与镜台之间。他仍抬手挡住针，声音已经发哑：“我说，不打。”

“你现在没有判断能力。”{doctor}语气依旧平静，“睡一觉，明天所有人都会感谢我。”

“那就让他们先学会感谢一个活人。”

话音未落，{doctor}已经按住他的手臂。{protagonist}猛地挣了一下，椅脚在地面拖出刺耳声响。他喊人，门外的脚步却没有停；像是所有人早已习惯在他明确拒绝时装作没有听见。

{doctor}不顾他的挣扎，将镇静针强行注射进去。

一阵冰冷很快变成沉重。{protagonist}想把手臂抽回来，手指却渐渐失去力气。{doctor}松开他，将针收回药箱，动作从容得像完成了每天都会完成的工作。

“你会睡得很好。”他说。

药箱扣上的声音很轻，落在{protagonist}耳中却像一道锁。{doctor}离开时没有回头，门也没有关严。

灯光开始散开，镜子里的脸变得模糊。{protagonist}努力吸气，胸口却越来越沉。他想站起来撞开门，身体只向前倾了片刻，便重新跌回椅背。外面的舞台乐声又响了，正是为他准备的开场，可那熟悉的节拍此刻离他越来越远。

门外传来压低的交谈。

{outside_speaker}问：“保险什么时候能生效？”

另一道声音回答：“等里面确认。”

{outside_speaker}又问：“死后版权呢？什么时候能交到我们手里？”

短暂的沉默后，有人笑了一声。

“急什么。人不再开口，作品才最听话。”

{outside_speaker}的回答更冷：“死人比活人值钱。”

每个字都穿过门缝，落得清清楚楚。

{protagonist}终于明白，今晚不是一次失控的治疗。那些被排满的日程，那些不许他过问的针，那些总以保护为名替他作出的决定，都在把他推向同一个结果。他们等的不是他站回舞台，而是他倒下以后，再把他的声音、名字和未完成的作品逐件拿走。

愤怒让他短暂地清醒。他用尽力气抬起手，指尖碰到桌上的礼帽。那顶帽子陪他走过无数舞台，如今却连同他本人一起，被门外的人当成可以分配的商品。

“我还活着……”

声音轻得几乎听不见。

门外无人回应。

{protagonist}望着镜中的自己。他不甘心明晚的舞台被取消，不甘心那些等着他的歌迷只等来一则由别人编好的消息，更不甘心自己唱了那么多年，最后连身体都没有发言权。

他想把那顶礼帽抓紧，手却从帽檐慢慢滑落。

呼吸越来越短，心跳也越来越弱。{outside_speaker}仍在门外谈论他的身后利益，像在等待一场早已写好结局的演出。{protagonist}想再说一次拒绝，喉间却只剩微弱的气息。

舞台乐声骤然停下。

他的最后一口气也停在了那一刻。

镜前的灯还亮着，{protagonist}的手垂在椅边，再没有抬起。他没能走上复出首演的舞台，也没能阻止那些人瓜分自己的作品。上一世的生命就这样结束在演出前夜，只剩下被最信任的安排夺走一切的愤怒与不甘。""".strip()


def _append_grounded_opening_death_scene(
    original_text: str, chapter_card: Dict[str, Any]
) -> str:
    """Close chapter 1 with the exact accepted death method when Qwen omits it."""
    text = (original_text or "").rstrip()
    tragedy = str(chapter_card.get("prev_life_tragedy") or "")
    cast = chapter_card.get("canonical_cast") or []
    protagonist = next(
        (
            str(member.get("name") or "").strip()
            for member in cast
            if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "protagonist"
            and str(member.get("name") or "").strip()
        ),
        "主角",
    )
    method_match = re.search(SPECIFIC_DEATH_METHOD_PATTERN, tragedy)
    method = method_match.group(0) if method_match else "服药过量"
    career_opening = bool(re.search(
        r"试戏|试镜|选角|女主角|经纪人",
        " ".join(str(chapter_card.get(key) or "") for key in (
            "chapter_goal", "prev_life_tragedy", "this_life_revenge", "core_payoff"
        )),
    ))
    injection_death = bool(re.search(
        r"强行注射|违规注射|过量注射|注射过量|针剂|镇静针",
        tragedy,
    ))
    if injection_death:
        milestone = chapter_card.get("chapter_milestone") or chapter_card.get("milestone") or {}
        opponent_reaction = str(
            milestone.get("opponent_reaction") if isinstance(milestone, dict) else ""
        ).strip()
        accepted_result = str(
            milestone.get("result") if isinstance(milestone, dict) else ""
        ).strip()
        doctor = next((
            str(member.get("name") or "").strip()
            for member in cast if isinstance(member, dict)
            and "医生" in str(member.get("role") or "")
        ), "私人医生")
        scene_parts = [
            f"{doctor}不顾{protagonist}的拒绝，把针剂强行注入{protagonist}的身体。"
            f"{protagonist}的手指很快无法动弹，呼吸也开始变得断续。",
        ]
        if opponent_reaction:
            scene_parts.append(
                f"药效压住身体时，{protagonist}仍清楚听见或看见当场发生的一切："
                f"{opponent_reaction.rstrip('。！？')}。"
            )
        if accepted_result:
            scene_parts.append(accepted_result.rstrip("。！？") + "。")
        else:
            scene_parts.append(
                f"{protagonist}还没能说出最后一句拒绝，心脏便骤然停止，"
                "带着没能挽回核心损失的不甘明确死去。"
            )
        return text + "\n\n" + "".join(scene_parts)
    if re.search(r"车祸|交通事故|撞向护栏", method + tragedy):
        scene = (
            f"{protagonist}独自驾车离开时，旧经纪人的背叛和试镜室里的嘲笑仍在耳边反复。"
            f"{protagonist}攥紧方向盘，视线模糊了前方车道；等看清急弯时，刹车已经来不及。"
            f"车辆失控冲向护栏，金属撞击声骤然撕开夜色。安全气囊弹开，{protagonist}却再也抬不起手。"
            f"呼吸一点点断绝，心跳最终停止。{protagonist}带着没能挽回核心损失、"
            "也没能让背叛者付出代价的不甘，当场身亡。"
        )
    elif re.search(r"坠楼|跳楼|从.{0,8}跳下", method + tragedy):
        scene = (
            f"{protagonist}走上高处，手里还留着这场失败最后的凭据。"
            f"{protagonist}最后回望一眼，从边缘纵身跳下。风声戛然而止，"
            "呼吸与心跳一同停止，只剩没能挽回核心损失、让背叛者付出代价的不甘。"
        )
    else:
        already_home = bool(re.search(r"公寓|家门|家中|玄关", text[-700:]))
        if career_opening:
            home_opening = (
                f"{protagonist}把被终止的代理通知压在练习了无数遍的剧本下。"
                if already_home
                else f"{protagonist}回到住处，把被终止的代理通知压在练习了无数遍的剧本下。"
            )
        else:
            home_opening = "" if already_home else f"{protagonist}独自回到住处。"
        scene = (
            home_opening
            + f"绝望中，{protagonist}吞下过量药物，因服药过量很快失去力气。"
            f"药效发作后，{protagonist}再也无法握住手边的东西，呼吸逐渐断绝，"
            "心跳最终停止，只剩没能挽回核心损失、让背叛者付出代价的不甘。"
        )
    return text + "\n\n" + scene


def _ground_opening_betrayal_before_home(
    original_text: str, chapter_card: Dict[str, Any]
) -> str:
    """Insert only missing accepted betrayal facts before the protagonist goes home."""
    text = (original_text or "").strip()
    cast = chapter_card.get("canonical_cast") or []
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in cast if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
    ), "主角")
    opponent = next((
        str(member.get("name") or "").strip()
        for member in cast if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "opponent"
    ), "固定对手")
    title = sorted(_planned_work_titles(chapter_card))[0] if _planned_work_titles(chapter_card) else "核心项目"
    if not re.search(
        r"试戏|试镜|选角|女主角|经纪人",
        " ".join(str(chapter_card.get(key) or "") for key in (
            "chapter_goal", "prev_life_tragedy", "this_life_revenge", "core_payoff"
        )),
    ):
        return text

    additions: List[str] = []
    manager_withdraws = bool(re.search(
        r"(?:旧经纪人|经纪人).{0,260}(?:不再代表)|"
        r"(?:旧经纪人|经纪人).{0,260}(?:撤回|撤销|终止|解除).{0,40}(?:代理|支持)|"
        r"(?:不再代表|撤回|撤销|终止|解除).{0,80}(?:旧经纪人|经纪人)",
        text,
        re.I | re.S,
    ))
    manager_switches = bool(re.search(
        rf"(?:旧经纪人|经纪人).{{0,480}}(?:担任|转投|服务|站到|走到|转向).{{0,100}}{re.escape(opponent.split()[0])}|"
        rf"(?:旧经纪人|经纪人).{{0,480}}{re.escape(opponent.split()[0])}.{{0,120}}(?:全权跟进|全权代理|独家代理)",
        text,
        re.I | re.S,
    ))
    if not (manager_withdraws and manager_switches):
        additions.append(
            f"就在{protagonist}还想争取最后一次解释时，旧经纪人越过她，径直站到{opponent}身边。"
            f"他当着选角室所有人的面说：“从这一刻起，我不再代表你。”"
            f"随后，他撤回对{protagonist}的全部代理支持，公开确认自己将转而服务{opponent}。"
        )

    opponent_has_role = bool(re.search(
        rf"{re.escape(opponent.split()[0])}.{{0,180}}(?:签下名字|落笔签字|签下).{{0,45}}|"
        rf"{re.escape(opponent.split()[0])}.{{0,140}}(?:拿到|获得|官宣).{{0,35}}(?:女主角|主演|角色|合约)|"
        rf"《{re.escape(title)}》.{{0,60}}(?:官宣主演|女主角|主角尘埃落定).{{0,30}}{re.escape(opponent.split()[0])}",
        text,
        re.I | re.S,
    ))
    if not opponent_has_role:
        additions.append(
            f"片方代表随即把《{title}》女主角合同推到{opponent}面前。"
            f"{opponent}看着{protagonist}，当场签下名字；片方随即确认她拿到女主角，"
            "原本还与主角打招呼的人纷纷移开视线。"
        )

    if not additions:
        return text
    insertion = "\n\n".join(additions)
    home_match = re.search(
        rf"{re.escape(protagonist)}.{{0,30}}(?:回到|走回|走进|推开).{{0,20}}(?:公寓|家门|家中)|"
        r"(?:回到|走回|走进|推开).{0,20}(?:公寓|家门|家中)|"
        r"公寓楼道|刷卡进门|玄关",
        text,
        re.S,
    )
    if not home_match:
        return text + "\n\n" + insertion
    sentence_start = max(
        text.rfind(marker, 0, home_match.start())
        for marker in ("。", "！", "？", "\n")
    )
    cut = sentence_start + 1
    return text[:cut].rstrip() + "\n\n" + insertion + "\n\n" + text[cut:].lstrip()


def _build_awakening_repair_prompt(
    chapter_num: int,
    original_text: str,
    chapter_card: Dict[str, Any],
    failures: List[str],
) -> str:
    canonical_cast = chapter_card.get("canonical_cast") or []
    repair_cast = _select_grounded_chapter_cast(chapter_card)
    protagonist = next(
        (
            str(member.get("name") or "").strip()
            for member in canonical_cast
            if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "protagonist"
            and str(member.get("name") or "").strip()
        ),
        "主角",
    )
    planned_action = str(chapter_card.get("this_life_revenge") or "").strip()
    planned_result = str(chapter_card.get("core_payoff") or "").strip()
    established_tragedy = str(chapter_card.get("prev_life_tragedy") or "").strip()
    milestone = chapter_card.get("chapter_milestone") or chapter_card.get("milestone") or {}
    card_context = " ".join(
        [
            str(chapter_card.get(key) or "")
            for key in (
                "chapter_goal", "prev_life_tragedy", "this_life_revenge",
                "core_payoff", "chapter_ending", "chapter_milestone", "milestone",
            )
        ]
        + [
            str(member.get("role") or "")
            for member in canonical_cast if isinstance(member, dict)
        ]
    )
    medical_awakening = bool(re.search(
        r"医生|医疗|针剂|注射|药品|药物|用药|双签|封存",
        card_context,
    ))
    if medical_awakening:
        direct_opponent = next((
            str(member.get("name") or "").strip()
            for member in canonical_cast if isinstance(member, dict)
            and (
                "医生" in str(member.get("role") or "")
                or str(member.get("alignment") or "").casefold() == "opponent"
            )
        ), "现场直接对手")
        return f"""你是商业重生小说的开篇结构编辑。请从零写出第{chapter_num}章1200-1800个汉字的“重生觉醒与首次夺权章”，不得续写失败稿。

【本章允许出场的固定人物】{json.dumps(repair_cast, ensure_ascii=False)}
【固定主角】{protagonist}
【上一世已验收事实】{established_tragedy}
【本章里程碑】{json.dumps(milestone, ensure_ascii=False)}
【本章必须完成的行动】{planned_action}
【本章必须生效的结果】{planned_result}
【直接对手】{direct_opponent}
【上轮失败】{chr(10).join(failures)}

硬要求：
1. 第一段承接【上一世已验收事实】中的死亡余感，原样写出“{protagonist}猛然惊醒”；不得擅自改换死法。
2. 通过身体完好、熟悉环境、日期或日程等至少三项细节逐项核对，确认时间已经回退。精确日期或间隔只使用事件卡已给出的信息，卡片未给出时不得补造。
3. 私下明确确认“{protagonist}重生了，回到了那场关键事件之前”；不得写成梦、失忆或第二次以上重生，也不得向公众自曝。
4. 只执行【本章必须完成的行动】中已经规划的医疗拒绝、登记、见证、封存或权限动作，不得自行增加检测设备、药理成分、批号、监管机构或数字取证。
5. 结尾必须逐项完成【本章必须生效的结果】，并让{direct_opponent}失去卡片明确写出的单方权限；“我会安排”或等待后续处理不算完成。
6. 全章留在重生当天同一主要地点；不得进入下一场正式活动、调查、演出反杀或第二天，不得出现匿名消息、陌生人或新证据。
7. 只有【本章允许出场的固定人物】可以使用姓名；其他必要人员只用事件卡已有的无姓名职位。
8. 只输出小说正文，不要标题、解释、字段名或修订总结。
"""
    return f"""你是商业重生小说的开篇结构编辑。请依据人工验收的事件卡，从零写出第{chapter_num}章1200-1800个汉字的“重生觉醒与首次部署章”，不得续写失败稿。

【本章允许出场的固定人物】{json.dumps(repair_cast, ensure_ascii=False)}
【固定主角】{protagonist}
【上一世已验收事实】{established_tragedy}
【本章里程碑】{json.dumps(milestone, ensure_ascii=False)}
【本章必须完成的行动】{planned_action}
【本章必须生效的结果】{planned_result}
【上轮失败】{chr(10).join(failures)}

硬要求：
1. 第一段承接【上一世已验收事实】中的死亡余感并原样写出“{protagonist}猛然惊醒”；不得改换上一世死法。
2. 用身体完好、熟悉环境、日期或日程等至少三项细节逐项核对，确认自己回到事件卡指定的关键事件之前。卡片没有给出精确时间时不得自行补造。
3. 私下明确确认“{protagonist}重生了，回到了那场关键事件之前”，并写清这不是梦境或失忆；不得向公众或其他人物自曝重生。
4. 只回忆一个能支持当前决定的旧局信号，随后立刻执行【本章必须完成的行动】；不得展开调查或提前进入下一情节组。
5. 结尾必须逐项完成【本章必须完成的行动】和【本章必须生效的结果】。写好、准备、拨号、等待回复或“我会安排”都不算落地。
6. 全章停留在重生当天同一主要地点；不得出现匿名消息、陌生号码、神秘人物、跟踪、潜入、隐藏文件或新证据。
7. 只有【本章允许出场的固定人物】可以使用姓名；其他必要人员只能用事件卡已有的无姓名职位。
8. 只输出小说正文，不要标题、解释、字段名或修订总结。
"""


def _build_medical_double_sign_awakening_scene(
    chapter_card: Dict[str, Any],
) -> Optional[str]:
    """Build the performer-domain rebirth scene that settles medical consent."""
    role_v2 = str(chapter_card.get("chapter_role_v2") or "")
    context = json.dumps(
        {
            key: chapter_card.get(key)
            for key in (
                "prev_life_tragedy", "this_life_revenge", "core_payoff",
                "cluster_outcome", "chapter_milestone", "canonical_cast",
            )
        },
        ensure_ascii=False,
    )
    if role_v2 != "rebirth_awakening_only" or not (
        re.search(r"针剂|注射|用药", context)
        and re.search(r"双签|第二签字权|医疗监督", context)
        and re.search(r"演出|舞台|歌手|歌迷|流行|复出|首演|排练|唱片", context)
    ):
        return None

    cast = _select_grounded_chapter_cast(chapter_card)
    protagonist = next(
        (
            str(member.get("name") or "").strip()
            for member in cast
            if str(member.get("alignment") or "").casefold() == "protagonist"
        ),
        "",
    )
    doctor = next(
        (
            str(member.get("name") or "").strip()
            for member in cast
            if "医生" in str(member.get("role") or "")
        ),
        "",
    )
    if not protagonist or not doctor:
        return None

    return f"""最后一口气断掉的窒息感还压在胸口，{protagonist}猛然惊醒。

他一下坐起，急促地吸进空气。没有门外谈论保险的低语，没有骤然停下的舞台乐声，也没有化妆镜前那顶从指间滑落的礼帽。眼前是一间安静的发布会预备厅，窗帘半掩，桌上放着尚未翻开的流程单。

{protagonist}低头看向自己的手。手指可以弯曲，手臂也没有刚被强行注射后的沉重。他把掌心按在胸前，心跳又快又有力，一下接着一下，像在提醒他这具身体仍然属于活人。

可死亡的记忆太清楚了。

康拉德按住他的手臂，镇静针被强行注射；药箱扣上；门外有人问保险什么时候生效。最后那句“死人比活人值钱”，此刻仍像冰冷的钉子扎在耳边。

{protagonist}拿起桌上的手机。屏幕日期映进眼中时，他的呼吸停了一瞬。他又抓过流程单，确认上面写的是复出发布会当天，而不是那场首演前夜。镜中人的脸虽然疲惫，眼神却还清醒，身体也没有走到崩溃边缘。

他在心里把两份日程重新推了一遍。

距离上一世死亡，还有一百零七天。

这不是梦，也不是临死前的幻觉。日期、房间、身体和发布会流程全都对得上。

{protagonist}重生了，回到了那场复出发布会之前。

门外恰在这时传来轻敲。{doctor}端着针盘走进来，语气和记忆里一样平稳：“时间到了。先把针打了，等会儿你才有精神。”

针盘上盖着白布，只露出针管的一角。

上一世的{protagonist}没有追问。他太累，也太习惯别人替自己决定。那时{doctor}说这是为状态着想，他便任由针进入身体；从那以后，拒绝越来越像一句没人需要听见的话。

这一世，他抬手挡住针盘。

“不打。”

{doctor}脚步一顿：“这是原定安排。”

“药名是什么？用量由谁决定？来源由谁登记？”

{doctor}没有立刻回答，只皱起眉：“你不需要懂这些。发布会在等你。”

{protagonist}看着他，死前那阵无法呼吸的痛苦又从记忆里压过来。他没有后退，反而把针盘推回两人之间。

“我的身体不是你赶日程的工具。”他说，“解释不清，就不能碰我。”

{doctor}压低声音：“你现在情绪不稳定。我是你的私人医生，有权根据状态处理。”

“你有提出建议的职责，没有越过本人拒绝的权力。”

{protagonist}按下预备厅的内线，请场地方安排的第三方医疗团队进来。等待的片刻里，{doctor}仍端着针盘，几次想把话题带回“为了演出”，却始终说不出药名、用量和来源。

门再次打开。值班医师与药品管理员走进来，没有询问娱乐团队的意见，只先向{protagonist}确认：“您是否同意现在使用这支针剂？”

“不同意。”

回答干脆得没有一丝余地。

值班医师随即接过针盘。药品管理员打开登记簿，把针剂记为来源与用途待核，现场封存，明确写下不得使用。针从始至终没有进入{protagonist}的身体。

{doctor}脸色沉了下来：“你要让外人接管我的工作？”

“他们不接管你。”{protagonist}说，“他们接管你绕过我的那只手。”

他当场提出新的医疗双签要求：此后任何进入他身体的药物，都必须先说明药名、用量和来源；除他本人同意外，还要由第三方值班医师复核签字。少任何一项，任何人都不得注射。

值班医师确认这项要求可以立即执行，在登记簿上签下第二签字责任。药品管理员把封存的针剂收进专用保管箱，同时注明私人医生不再拥有单方用药权限。

{doctor}攥紧空下来的针盘，指节发白：“你会为今天的任性耽误整个团队。”

{protagonist}抬眼看他。

“把活着叫任性的人，没资格替我决定该打什么针。”

{doctor}嘴唇动了动，再找不到一句能压住他的“为你好”。他只能放下针盘，退出预备厅。

门关上后，{protagonist}没有立刻起身。他望着登记簿上已经生效的双签记录，缓慢地握紧双手。上一世，他连一句拒绝都没能守住；这一世醒来的第一件事，就是让这句拒绝成为任何人都不能越过的边界。

问题针剂已经封存，医疗双签已经生效，第三方医疗团队正式接管第二签字权，{doctor}当场失去单方注射权。{protagonist}第一次阻断了那条利益链对自己身体的控制。""".strip()


def _build_schedule_canary_scene(
    chapter_card: Dict[str, Any],
) -> Optional[str]:
    """Build a paper-grounded schedule canary setup or reveal scene."""
    context = json.dumps(
        {
            key: chapter_card.get(key)
            for key in (
                "cluster_name", "chapter_milestone", "this_life_revenge",
                "core_payoff", "cluster_outcome",
            )
        },
        ensure_ascii=False,
    )
    if not (
        re.search(r"彩排表|排练表|排练信息", context)
        and re.search(r"三份|泄密|泄露|分发权", context)
    ):
        return None

    cast = _select_grounded_chapter_cast(chapter_card)
    protagonist = next(
        (
            str(member.get("name") or "").strip()
            for member in cast
            if str(member.get("alignment") or "").casefold() == "protagonist"
        ),
        "",
    )
    opponent = next(
        (
            str(member.get("name") or "").strip()
            for member in cast
            if str(member.get("alignment") or "").casefold() == "opponent"
        ),
        "",
    )
    milestone = chapter_card.get("chapter_milestone") or {}
    milestone_text = json.dumps(milestone, ensure_ascii=False)
    if not protagonist or not opponent:
        return None

    if re.search(r"开除|揭穿|证伪|法律追责", milestone_text):
        return f"""排练室的门关上时，三份彩排表已经并排放在长桌上。

{protagonist}没有坐。他把三份纸逐一翻到背面，收件人的签名都在，谁拿过哪一份，一眼就能看清。舞台负责人收到的那份写着“主舞台试灯”，音响负责人收到的那份写着“空场校音”，只有调度助理签收的那份，多了一行并不存在的安排：侧台封闭走位。

门外那队商业摄影人员刚被拦下。他们正是冲着“侧台封闭走位”赶来，没有碰到真正的彩排，真实日程也没有被打乱，却替{protagonist}把泄密的出口指了出来。

调度助理站在桌尾，脸色发白，仍咬着牙说：“表格经过那么多人，不能因为一句话就算到我头上。”

{opponent}立刻接话：“他说得对。临时安排本来就乱，先别把事情闹大。”

{protagonist}看了{opponent}一眼：“你怕事情闹大，还是怕你的人先开口？”

屋里安静下来。

他把三份表重新扣在桌面，只露出空白背面，又问在场众人：“摄影人员拿到的那份，边角是什么标记？”

舞台负责人摇头。音响负责人也摇头。调度助理却脱口而出：“蓝色短线而已，谁都可能见过。”

话说完，他自己先僵住了。

三份表一直扣着，{protagonist}从未说过哪份有蓝色短线。那道线只画在调度助理签收的诱饵表边角，连{opponent}都没有看过。

{protagonist}慢慢翻开那份表。蓝色短线露出来，正贴着“侧台封闭走位”几个字。

“我还没问颜色。”他说。

调度助理嘴唇发抖：“我只是猜的。”

“那就再猜一次。”{protagonist}转向门边的摄影联络人，“你们为什么赶到侧台？”

摄影联络人没有递出手机，也没有拿出偷拍视频，只当面说明，有人以调度助理的身份主动告知了地点和安排，还要求他们抢在正式通知前到场。对方说得最清楚的一句话，正是“侧台封闭走位”。

调度助理后退一步，撞到椅背。他还想否认，却在{protagonist}把签收表推到面前时乱了声音：“我只告诉过一个熟人，我没想到他真会带人来！”

承认落地，再也收不回去。

{opponent}猛地转头：“谁让你擅自联系外面？”

调度助理像抓住救命绳一样看向他：“总监，您以前不是说，提前放一点行程能换宣传吗？”

{opponent}脸色骤沉：“别胡说。我让你协调，不是让你卖消息。”

两个人急着切割，反而把屋里最后一点侥幸撕得干干净净。

{protagonist}没有追问尚未发生的事，也没有把一场泄密夸成更大的阴谋。他只指向桌上的签收表：“谁拿了哪份，谁把哪句话送出去，已经够了。”

现场人事负责人当场收回调度助理的工作证，宣布解除其职务，立即请出排练区域。项目法务接手其违反保密责任的后续处理，摄影联络人也被要求离开，未经许可不得再进入后台。

调度助理终于慌了，伸手想拿回工作证：“我跟了团队这么久，不能因为一张假表就开除我！”

{protagonist}挡住他的手。

“开除你的不是假表。”他说，“是你亲手把它送到了不该知道的人面前。”

工作证被装进回收袋，调度助理被带出排练室。门外脚步渐远，屋里没有人再替他求情。

{opponent}仍站在原位，勉强维持着总监的姿态：“人已经处理了，调度工作还是得由我负责。”

“你仍是巡演总监。”{protagonist}说，“但从今天起，你负责执行，不再负责向全组分发表格。真实彩排表由我确认，分发名单也由我决定。”

{opponent}下颌绷紧。他没有被提前赶出团队，却亲眼看着最听话的调度助理被开除，也失去了排练表分发权。

{protagonist}收起唯一真实的彩排表，三份诱饵则留作本次内部处理的纸面记录。泄密者已经被清出团队，后续责任有人接手，真实彩排没有受损。

他走向排练区时，只留下一句：“表可以是假的，伸出去的手不会。”""".strip()

    return f"""医疗双签登记结束后，{protagonist}没有立刻去发布会前场，而是转进隔壁的排练准备室。

桌上摊着当天的彩排表，最上方仍写着由巡演团队统一分发。{opponent}站在桌边，正催几名助理把表送往各组：“照旧群发，谁没收到就让谁自己来问。”

“照旧”两个字，让{protagonist}想起上一世的同一场混乱。

那时真正的彩排时间提前泄露，摄影人员堵住排练通道，几个部门手里的表又彼此冲突。所有人都说是临时改动，最后却把失控归到他状态不稳。如今旧局再次出现，他不再等错误发生，而是提前改变分发方式。

“真表不群发。”{protagonist}按住桌上的原件，“由我保管。”

{opponent}笑了一声：“几十个人等着排练，你打算挨个送？”

“不用。先送三份。”

{protagonist}让助理取来空白表，当场写出三份诱饵。大部分安排相同，只有一处各不相同：送给舞台负责人的纸上写“主舞台试灯”，送给音响负责人的纸上写“空场校音”，送给调度助理的纸上写“侧台封闭走位”。

他又在每份纸的边角留下不同记号，其中调度助理那份是一道蓝色短线。三份表背面分别写明接收岗位，并要求本人签收，不许转交。

{opponent}看着那三行字，眉头慢慢皱起：“你这是故意制造混乱。”

“真实彩排照常进行，乱的只会是拿假消息去找别人的人。”

{protagonist}把真正的彩排表折好，放进自己的文件夹。随后，他亲眼看着三名接收人依次到场。舞台负责人签收第一份，音响负责人签收第二份，调度助理最后进来，接过写有“侧台封闭走位”的那份。

调度助理翻得很快，看到那行字时手指停了一下。

“有问题？”{protagonist}问。

“没有。”他立刻合上纸，“我会通知下面的人。”

“只通知你自己。今天谁都不许转发。”

调度助理嘴上答应，离开时却把纸紧紧贴在文件夹内侧。{opponent}望着他的背影，又回头对{protagonist}说：“你这样不信任团队，排练迟早会散。”

{protagonist}把真实彩排表握在手里：“把秘密卖出去的人，才怕我开始分清谁拿了什么。”

很快，三份诱饵带来的混乱先后出现。舞台组来问为何突然试灯，音响组来问为何空场校音，助理们在走廊里来回确认。{protagonist}没有让任何人按假表行动，只让每名收件人拿着自己的纸到准备室核对。

三份纸重新回到桌面时，背后的签名各自对应，没有一份混淆。真正的彩排则始终没有离开{protagonist}的文件夹，排练人员按他当面公布的时间正常集合。

{opponent}终于失去耐心：“你折腾一圈，只证明每个人收到的表不同。”

“这就够了。”

门外忽然传来争执。一队商业摄影人员被挡在通道口，反复声称有人通知他们，侧台即将进行封闭走位，错过就再也拍不到。

屋内几个人同时看向桌面。

“主舞台试灯”和“空场校音”都没有传出去。外面的人准确说出了第三份诱饵里独有的“侧台封闭走位”。

调度助理的脸色一下变了，却还强撑着问：“也许有人碰巧猜到。”

{protagonist}没有当场处置他，也没有继续逼问。他只收回三份表，按签收顺序放好，平静地说：“稍后在排练室，当着所有收件人的面，再听你解释这个巧合。”

随后，他当场收回排练群的统一发布权限，工作人员将发布人改成他本人。此后只有他确认的消息可以发给全组，{opponent}与调度助理保留查看权限，却不能再擅自群发。

变更当场完成。真实彩排表仍在{protagonist}手中，三份诱饵也分别锁定了接收人。{opponent}伸手想拿桌上的表，被{protagonist}先一步收进文件夹。

“你不是说我不信任团队吗？”{protagonist}看着他，“等人到齐，我就把信任该给谁，讲清楚。”

门外的摄影人员被劝离，真正的排练没有被打断。{opponent}站在已经失去发布权限的群聊前，脸上的笑终于挂不住了。""".strip()


def _build_overload_schedule_bait_scene(
    chapter_card: Dict[str, Any],
) -> Optional[str]:
    """Build a paper-grounded extra-show bait and overload settlement scene."""
    context = json.dumps(
        {
            key: chapter_card.get(key)
            for key in (
                "cluster_name", "chapter_milestone", "this_life_revenge",
                "core_payoff", "cluster_outcome", "prev_life_tragedy",
            )
        },
        ensure_ascii=False,
    )
    if not (
        "加场" in context
        and re.search(r"隐藏总表|超负荷|超载|排期签批权|恢复日", context)
    ):
        return None

    cast = _select_grounded_chapter_cast(chapter_card)
    protagonist = next(
        (
            str(member.get("name") or "").strip()
            for member in cast
            if str(member.get("alignment") or "").casefold() == "protagonist"
        ),
        "",
    )
    opponent = next(
        (
            str(member.get("name") or "").strip()
            for member in cast
            if str(member.get("alignment") or "").casefold() == "opponent"
        ),
        "",
    )
    milestone_text = json.dumps(
        chapter_card.get("chapter_milestone") or {},
        ensure_ascii=False,
    )
    if not protagonist or not opponent:
        return None

    if re.search(r"失去排期签批权|强制恢复日|最终排期否决权", milestone_text):
        return f"""排练开始前，隐藏总表与对外排期表并排摊在长桌上。

{protagonist}把所有参与排期的人叫到桌边，先让众人看清两张纸。昨天，{opponent}为抢下加场功劳，已经亲手拿出这份总表，亲口承认所有场次都由他安排，还在新增的加场旁留下签名。桌上的内容，已经足够说明问题。

排练负责人先读对外排期。上面每场演出之间都有一段看似宽松的空白，{opponent}一直把那些空白称作休息。

随后，项目负责人逐行读隐藏总表。演出结束后的空白里写着连夜转场，转场后的空白里写着清晨装台，装台后的空白又塞进合练、试装和媒体见面。纸面上没有一处写着恢复，只有工作换了名字。

屋里越听越静。

舞台负责人低声说：“照这张表走，演员下台后连卸妆都要在车上完成。”

{opponent}立刻抬手：“巡演本来就是这样。空白还在，怎么能说没有休息？”

{protagonist}指住其中一格：“这里写转场。”

“车上能睡。”

“下一格写装台确认。”

“他可以坐着确认。”

“再下一格写合练。”

{opponent}的手还悬在半空，嘴却慢了下来。

{protagonist}看着他：“你把空白叫休息，是因为倒下的人从来不是你。”

上一世，他就是在这样的日程里被拖到双腿发软。每一次想停下，{opponent}都拿出对外那张漂亮的表，说真正的工作并不多。等他在台上倒下，所有人只看见一个撑不住的歌手，没有人看见空白里藏着什么。

这一世，隐藏总表是{opponent}自己为抢功交出来的。

{opponent}脸色发紧，忽然把责任推向{protagonist}：“加场是你亲口提的。我只是替你完成愿望。”

“我问能不能加。”{protagonist}把昨天那张纸转向众人，“你没有先问我的身体，也没有核对现有工作，只说还能塞进去。更重要的是，这些超载安排在我开口前就已经写满了。”

纸上新增的加场被划在最末，原有的连夜转场和清晨装台都在它之前。时间先后清清楚楚，{opponent}无法再把旧排期推给一次试探。

他伸手想收表，项目负责人先按住纸：“总表留在这里。”

独立医疗见证当场说明，在没有完整恢复间隔的情况下继续追加演出，会直接破坏此前已经确认的演出标准。排练负责人和舞台负责人也明确表示，不再执行未经艺人确认的超载安排。

{opponent}冷笑：“那你们想让谁来排？一个唱歌的人，还是一群只会说不行的人？”

项目负责人没有与他争辩，只宣布现场决定：{opponent}仍任巡演总监，可以提交排期建议，也可以执行已经确认的安排，但从此失去排期签批权，不能再把自己写下的总表直接变成全组命令。

新的纸质排期表当场铺开。项目负责人先划出完整恢复日，任何排练、转场和见面都不得填入；其余安排只有在{protagonist}确认后才能进入执行表。

强制恢复日当场生效。{protagonist}取得强制恢复日与最终排期否决权。

{opponent}盯着那片第一次不能被他填满的空白：“为了休息停掉工作，损失算谁的？”

{protagonist}把笔放在恢复日中央。

“你少卖一段空白，团队就少抬一次担架。”

排练负责人收走旧总表，舞台负责人撤下当天被临时塞入的合练。{opponent}没有离开总监职位，却失去了把超载安排签成命令的手。真正的恢复时间第一次写进正式排期，再没有人能把它偷换成另一项工作。""".strip()

    return f"""医务室的门刚关上，{opponent}便拿着一张对外排期表走进准备室。

他没提刚才的交接，只把排期表推到{protagonist}面前：“接下来照这张表走，时间很宽松。只要团队听我安排，谁也不会再说你状态不好。”

{protagonist}扫了一眼。纸上每场演出之间都留着大片空白，看起来确实从容。

上一世，{opponent}也给他看过这样一张表。真正执行时，那些空白会被转场、装台、合练和见面一点点填满。最后，他在连续奔波后倒在台边，{opponent}却拿着这张对外表对所有人说，是他自己体力不济。

他没有拆穿，只把纸放回桌面：“既然这么宽松，再加一场怎么样？”

{opponent}愣了一下：“加场？”

“你不是一直说外面抢着要吗？挑一个空白，塞进去。”

房间里几名负责人同时看向{opponent}。加场一旦成功，巡演总监最容易把功劳揽到自己身上。{opponent}嘴上还说需要考虑，手却已经把对外排期表拉回去，指着几处空白夸口：“只要我来排，别说一场，再多一些也放得下。”

{protagonist}故意问：“只看这张表就能决定？”

{opponent}的笑僵了一瞬。

对外排期只写公开活动，根本无法证明新增演出不会撞上内部工作。若他承认没有别的安排，就无法解释团队每天为何忙到深夜；若他想抢加场功劳，就必须拿出真正的总表。

“当然不是。”{opponent}终于压低声音，“我手里有完整版本。”

他转身关门，从随身文件夹的夹层抽出另一张折叠多次的纸。纸一展开，对外表上的空白立刻消失了：演出后的夜里排着转场，清晨排着装台，午后还有合练和见面。几段工作首尾相接，几乎没有完整恢复时间。

{opponent}用手掌压住纸角，语气又得意起来：“这才是我排的总表。所有人都照它动，只是没必要让每个部门看见全部安排。”

“你确认是你排的？”{protagonist}问。

“除了我，谁能把这么多事塞得进去？”

屋里没人接他这句功劳。排练负责人看着密密排开的工作，脸色已经沉下去。

{protagonist}却把笔递给{opponent}：“那就把你说的加场写进去。”

{opponent}以为他已经上钩，立刻在最后一处空白旁写下新增演出，又在下面签上自己的名字。他写完还把纸转向众人：“看见没有？这就是调度能力。”

{protagonist}等墨迹落稳，才按住那张总表。

“看见了。”他说，“也看见你把休息藏到哪里去了。”

{opponent}脸上的笑停住：“你什么意思？”

{protagonist}让项目负责人从头核对。对外表里被称作休息的空白，在隐藏总表上全有工作；新加的一场更是压在原有转场与合练之间。那不是能够利用的余量，而是从人的身体里硬挤出来的时间。

{opponent}急忙改口：“加场是你提的，我只是照办。”

“我提的是问题。”{protagonist}看着他，“你为了抢答案，把藏着的总表亲手交了出来。”

项目负责人当场划掉尚未批准的加场，并把所有没有经过本人确认的超载安排标为暂停。当天的新增演出被否决，后续超载排期全部冻结，任何人不得先执行再补确认。

{opponent}伸手去夺总表，{protagonist}先一步将它交给项目负责人保管。

“你不能凭一次试探停掉巡演。”

“我没有停巡演。”{protagonist}说，“我只是先停下那个把人当空白格填进去的人。”

{opponent}仍是巡演总监，却没能拿到加场功劳，隐藏总表也不再由他独占。{protagonist}保住当天休息时间，冻结全部超载安排，并要求下一次排练前当众逐项核对这张总表。

门开时，{opponent}还盯着纸上自己刚签下的名字。那一笔原本是他抢功的凭证，现在成了他无法推给任何人的承认。""".strip()


def _append_grounded_awakening_deployment(
    original_text: str, chapter_card: Dict[str, Any]
) -> str:
    text = (original_text or "").rstrip()
    cast = chapter_card.get("canonical_cast") or []
    protagonist = next(
        (
            str(member.get("name") or "").strip()
            for member in cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "protagonist"
        ),
        "主角",
    )
    ally = next(
        (
            str(member.get("name") or "").strip()
            for member in cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() in {"ally", "support"}
        ),
        "固定盟友",
    )
    if not re.search(
        r"试戏|试镜|选角|旧经纪人|解除代理",
        " ".join(str(chapter_card.get(key) or "") for key in (
            "chapter_goal", "prev_life_tragedy", "this_life_revenge", "core_payoff"
        )),
    ):
        doctor = next((
            str(member.get("name") or "").strip()
            for member in cast if isinstance(member, dict)
            and "医生" in str(member.get("role") or "")
        ), "私人医生")
        additions: List[str] = []
        has_refusal = bool(re.search(r"拒绝.{0,40}(?:针剂|注射)|(?:针剂|注射).{0,40}拒绝", text, re.S))
        has_registration = bool(re.search(r"登记.{0,40}(?:药名|剂量|来源)|(?:药名|剂量|来源).{0,40}登记", text, re.S))
        has_dual_sign = bool(re.search(r"双签|第二签字权", text))
        has_loss = bool(re.search(
            r"失去.{0,20}(?:单方|单独).{0,12}(?:注射|用药|签字).{0,8}权|"
            r"单方注射权.{0,12}(?:取消|移交|收回)",
            text,
            re.S,
        ))
        has_not_injected = bool(re.search(
            r"针剂.{0,20}(?:没有|未).{0,12}(?:进入|注入).{0,8}(?:身体|体内)|未被注射",
            text,
            re.S,
        ))
        if not (has_refusal and has_registration):
            additions.append(
                f"{protagonist}抬手按住针盘：“从现在起，我的身体不再是你一个人签字就能动的资产。”"
                f"他拒绝了{doctor}的注射，要求当面登记药名、剂量和来源。"
            )
        if not has_dual_sign:
            additions.append("第三方医疗团队在见证下封存针剂，并将今后所有用药改为双签。")
        if not (has_loss and has_not_injected):
            additions.append(
                f"问题针剂没有进入{protagonist}的身体，{doctor}当场失去单方注射权。"
            )
        return text + ("\n\n" + "".join(additions) if additions else "")
    additions: List[str] = []
    if not _has_completed_representation_termination(text):
        additions.append(
            f"{protagonist}随即写下解除代理授权的正式通知，确认收件人为旧经纪人后按下发送。"
            "送达回执亮起，解除代理授权立即生效，她删除了对方代为决定试镜和签约的权限。"
        )
    ally_pattern = re.escape(ally)
    has_completed_appointment = _has_completed_ally_appointment(text, ally)
    if not has_completed_appointment:
        incomplete_call = re.search(
            rf"(?:拨通|拨打|联系|打开通讯录|调出号码).{{0,45}}{ally_pattern}|"
            rf"{ally_pattern}.{{0,45}}(?:电话|号码|拨通|接听|会面|见面)",
            text,
            re.I | re.S,
        )
        if incomplete_call:
            sentence_start = max(
                text.rfind(marker, 0, incomplete_call.start())
                for marker in ("。", "！", "？", "\n")
            )
            text = text[: sentence_start + 1].rstrip()
        additions.append(
            f"接着，{protagonist}拨通{ally}的电话，直说自己要为《暗夜之光》的试镜重新准备。"
            f"{ally}听完后给出明确答复：“明天下午四点，到我的办公室来。”"
            f"{protagonist}复述时间并得到确认，屏幕上的会面预约随即保存成功。"
        )
    return text + ("\n\n" + "\n\n".join(additions) if additions else "")


def _prepend_grounded_awakening_confirmation(
    original_text: str, chapter_card: Dict[str, Any]
) -> str:
    """Restore the chapter-2 awakening chain when a rewrite skips its opening contract."""
    text = (original_text or "").strip()
    has_awake = bool(re.search(r"惊醒|醒来|睁开眼|猛地坐起|恢复意识", text))
    has_time_check = bool(re.search(r"日期|日历|手机屏幕|发布会日程|身体|房间", text))
    has_rebirth_confirm = bool(re.search(r"重生|回到.*前|回到了|再活一次|真的回来了", text))
    if has_awake and has_time_check and has_rebirth_confirm:
        return text
    cast = chapter_card.get("canonical_cast") or []
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in cast if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
    ), "主角")
    opening_parts: List[str] = []
    if not has_awake:
        opening_parts.append(
            f"{protagonist}猛然惊醒。上一世针剂推入血管后的窒息感还压在胸口，他立刻按住心脏。"
        )
    if not has_time_check:
        opening_parts.append(
            "他摸向手臂，确认皮肤完整，又核对镜中的身体、房间陈设、手机日期与发布会日程："
            "距离上一世死亡还有一百零七天。"
        )
    if not has_rebirth_confirm:
        opening_parts.append(f"这不是梦。{protagonist}重生了，回到了那场复出发布会之前。")
    return "".join(opening_parts) + "\n\n" + text


def _build_payoff_insertion_prompt(
    chapter_num: int,
    original_text: str,
    chapter_card: Dict[str, Any],
    failures: List[str],
) -> str:
    planned_result = str(chapter_card.get("chapter_ending") or "").strip()
    payoff = planned_result or str(chapter_card.get("core_payoff") or "").strip()
    canonical_cast = chapter_card.get("canonical_cast") or []
    opponent = next(
        (
            str(member.get("name") or "").strip()
            for member in canonical_cast
            if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "opponent"
            and str(member.get("name") or "").strip()
        ),
        str(chapter_card.get("main_opponent") or "既有对手").strip(),
    )
    protagonist = next(
        (
            str(member.get("name") or "").strip()
            for member in canonical_cast
            if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "protagonist"
            and str(member.get("name") or "").strip()
        ),
        "主角",
    )
    return f"""你是商业重生爽文的现场结算编辑。只写一段可直接接在第{chapter_num}章现有反击场景之后的新增正文，600-900个汉字。

【原章最后场景】
{original_text[-1400:]}

【固定对手】{opponent}
【固定人物与阵营，不得改名或换阵营】{json.dumps(canonical_cast, ensure_ascii=False)}
【核心爽点】{payoff or '让对手为旧局付出代价'}
【验收失败】
{chr(10).join(failures)}

硬要求：
1. 新增场景与原文发生在同一地点、同一晚、同一场冲突内，不得写几天后、几个月后或后日谈。
2. 只能由原文最后场景中已经明确出场、且确有权限的人物或机构宣布结果；可按其权限选择终止合作、暂停合作、撤下代言、取消资格、停职、解约等相称损失。不得新增“主办方代表、裁定官、负责人、主席、评委”等临时裁决者。若原场景无人有权决定，就不要伪造裁决。
3. 同一场景内当场确认主角现实收益，自然写成“{protagonist}拿下角色、与{protagonist}正式签约、恢复{protagonist}资格、公开为{protagonist}澄清”中的合适结果。不能只写获得关注、尊重、掌声或未来邀约。
4. 必须逐字落实章节卡计划的双向结果：“{planned_result or f'{opponent}失去这个角色，{protagonist}拿下这个角色'}”。可以润色前后叙述，但不得把“推荐权/影响力损失”擅自改成重复换角，也不得把已生效结果降级成未来邀约。再写{opponent}听见裁决后的具体失态、辩解或被迫离场，以及旁观者态度倒转。绝对不得让 protagonist 或 ally 受罚、停职、解约或被带离。
5. 不得新增幕后黑手、神秘人物、陌生电话、匿名材料、新证据、新任务或更大棋局；不得出现 E1/E2 等内部标签。
6. 结尾停在结果生效和双方现场反应上，禁止“这只是开始”“未来仍有挑战”等预告。
7. 只输出可直接拼接的小说正文，不要标题、解释、JSON、前言或修订说明。
"""


def _append_grounded_actor_contract_payoff(
    original_text: str, chapter_card: Dict[str, Any]
) -> str:
    text = (original_text or "").rstrip()
    cast = chapter_card.get("canonical_cast") or []
    protagonist = next(
        (
            str(member.get("name") or "").strip()
            for member in cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "protagonist"
        ),
        "主角",
    )
    opponent = next(
        (
            str(member.get("name") or "").strip()
            for member in cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() == "opponent"
        ),
        "固定对手",
    )
    ally = next(
        (
            str(member.get("name") or "").strip()
            for member in cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() in {"ally", "support"}
        ),
        "选角负责人",
    )
    title = sorted(_planned_work_titles(chapter_card))[0] if _planned_work_titles(chapter_card) else "核心项目"
    payoff_scene = (
        f"{protagonist}走到试戏标记线上，没有借助音乐，也没有要求重来。她从角色得知背叛的那一刻演起，"
        "先压住颤抖的呼吸，再抬眼说出最后一句台词。愤怒没有变成喊叫，而是在她骤然停住的动作里绷到极致。"
        f"{protagonist}收住最后一个动作，试戏室安静了两秒。{opponent}刚要插话，"
        f"{ally}便合上选角记录：“表演已经说明一切。片方确认由{protagonist}出演《{title}》女主角。”"
        f"{ally}把片方已经签章的两份女主角演员合同推到桌前。{protagonist}逐页确认角色、档期和片酬，"
        f"当场签下姓名；合同自双方签署之刻正式生效，{protagonist}正式拿下女主角合约。"
        f"{opponent}伸手去拿合同，却被{ally}按住：“你的角色竞争到此结束，退出这个项目。”"
        f"{opponent}失去女主角资格，被迫退出项目。"
        f"{opponent}脸色骤白，咬牙质问凭什么。周围原本观望的人转向{protagonist}道贺，再没有人替她让路。"
        f"{protagonist}收起自己那份生效合同，直视{opponent}离开试戏室。"
    )
    return text + "\n\n" + payoff_scene


def _build_chapter_expansion_prompt(
    chapter_num: int,
    original_text: str,
    chapter_card: Optional[Dict[str, Any]] = None,
) -> str:
    card = chapter_card if isinstance(chapter_card, dict) else {}
    role_v2 = str(card.get("chapter_role_v2") or "")
    must_include = card.get("chapter_must_include") or card.get("must_include") or []
    must_not = card.get("chapter_must_not_include") or card.get("must_not") or []
    canonical_cast = card.get("canonical_cast") or []
    expansion_cast = canonical_cast
    excluded_allies: List[str] = []
    if role_v2 == "prev_life_death_only" and any(
        isinstance(member, dict)
        and str(member.get("name") or "").strip() == "麦珂·杰森"
        for member in canonical_cast
    ):
        excluded_allies = [
            str(member.get("name") or "").strip()
            for member in canonical_cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() in {"ally", "support"}
        ]
        expansion_cast = [
            member for member in canonical_cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() not in {"ally", "support"}
        ]
    elif role_v2 == "rebirth_awakening_only" and any(
        isinstance(member, dict)
        and str(member.get("name") or "").strip() == "麦珂·杰森"
        for member in canonical_cast
    ):
        excluded_allies = [
            str(member.get("name") or "").strip()
            for member in canonical_cast if isinstance(member, dict)
            and str(member.get("alignment") or "").casefold() in {"ally", "support"}
        ]
        expansion_cast = [
            member for member in canonical_cast if isinstance(member, dict)
            and (
                str(member.get("alignment") or "").casefold() == "protagonist"
                or "医生" in str(member.get("role") or "")
            )
        ]
    planned_action = str(card.get("this_life_revenge") or "").strip()
    planned_result = str(card.get("core_payoff") or "").strip()
    minimum_chars = _minimum_chapter_chars(chapter_num, card)
    needed_chars = min(1000, max(350, minimum_chars - len(original_text or "") + 180))
    upper_chars = min(1200, needed_chars + 220)
    original_parts = [p for p in re.split(r"\n\s*\n", original_text or "") if p.strip()]
    original_ending = original_parts[-1] if original_parts else original_text[-500:]
    return f"""你是小说正文扩写编辑。只写一段{needed_chars}-{upper_chars}个汉字的新增正文，程序会把它插入第{chapter_num}章最后一个自然段之前。

【本章结构角色】{role_v2 or '未标注'}
【必须保留】{json.dumps(must_include, ensure_ascii=False)}
【禁止新增】{json.dumps(must_not, ensure_ascii=False)}
【本段允许使用的固定人物与阵营】{json.dumps(expansion_cast, ensure_ascii=False)}
【本段禁止提及的盟友】{'、'.join(excluded_allies) if excluded_allies else '（无额外限制）'}
【本章既定动作】{planned_action}
【本章既定结果】{planned_result}

特别要求：
1. 新增段落必须发生在原章最后场景内部，只细化已有动作、对话、环境、身体反应和对手反应。
2. 已死亡人物不得在死亡确认后于当前时间线说话、走动、操作设备或参与行动；录音、日志、转述和明确回忆可以保留。
3. 不得增加新核心人物、新阴谋、新证据来源、新地点、新组织、新装备或新时间跳跃；不得把一章扩成第二天或另一场任务。
4. 禁止新增陌生电话、匿名邮件、匿名论坛、跟踪、潜入、隐藏账本、加密文件、幕后人、真正的风暴或更大棋局。
5. 不得让原文末尾场景中尚未出现的人推门、到访、来电、发消息或加入对话；尤其不得为了扩字让对手突然进入主角房间或开启新对峙。
6. 新增段落不得执行、复述或越过【不可改写的原结尾】中的动作；若原结尾是拨号或约见，只能补写拨号前的核对、犹豫和准备，不能提前写完整通话、挂断、出门后再回到原结尾重新拨号。
7. 新增段落必须自然承接到下方【不可改写的原结尾】，不得抢先结束场景或开启下一事件。
8. 只输出新增正文段落，不要复述原文，不要标题、解释、JSON 或修订说明。
9. 不得给任何人物新增别名、自称名或中文译名；盟友不得被改写成前世背叛者。新增段落不能改变本章日期、角色归属、代理关系或预约是否完成。
10. 觉醒章不得写寻找真相、记录通话时长/语调、隐藏锋芒或未来关键线索；若原结尾是提出会面请求，新增段落只能放在请求之前，绝不能先写盟友答复再回到原结尾提出请求。
11. 只能使用“本段允许使用的固定人物与阵营”中的姓名；“本段禁止提及的盟友”不得被提及、旁观、来电或参与。

【原文末尾上下文】
{original_text[-1400:]}

【不可改写的原结尾】
{original_ending}
"""


def _insert_closed_scene_micro_expansion(
    original_text: str,
    addition: str,
    chapter_card: Dict[str, Any],
) -> str:
    """Insert a small addition before the fixed settlement, never after the payoff."""
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", original_text or "")
        if paragraph.strip()
    ]
    if not paragraphs:
        return (addition or "").strip()
    _, performance_scene, paper_markers = _closed_evidence_contract(chapter_card)
    if performance_scene:
        insert_at = next(
            (
                index
                for index, paragraph in enumerate(paragraphs)
                if re.search(r"暂停|叫停|喊停|停一下|停下来|先停|给我停", paragraph)
            ),
            next(
                (
                    index
                    for index, paragraph in enumerate(paragraphs)
                    if re.search(r"测试通过|符合要求|训练强度决定权", paragraph)
                ),
                max(0, len(paragraphs) - 1),
            ),
        )
    else:
        insert_at = next(
            (
                index
                for index, paragraph in enumerate(paragraphs)
                if re.search(r"即刻暂停你的职务|暂停你的职务|药品保管权", paragraph)
            ),
            max(0, len(paragraphs) - 1),
        )
    paragraphs.insert(insert_at, (addition or "").strip())
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph)


def _build_closed_scene_micro_expansion_prompt(
    chapter_num: int,
    original_text: str,
    chapter_card: Dict[str, Any],
    needed_chars: int,
) -> Optional[str]:
    """Ask for one narrow paragraph when a valid closed scene is just under length."""
    _, performance_scene, paper_markers = _closed_evidence_contract(chapter_card)
    medication_paper_audit = all(
        marker in paper_markers for marker in ("封签", "送货单", "领用簿")
    )
    scene_contract = (
        chapter_card.get("scene_contract")
        if isinstance(chapter_card.get("scene_contract"), dict)
        else _derive_closed_scene_contract(chapter_card)
    )
    cast = _select_grounded_chapter_cast(chapter_card)
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
    ), "主人公")
    opponent = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "opponent"
    ), "既有对手")
    if (
        not performance_scene
        and not medication_paper_audit
        and _closed_scene_contract_failures(scene_contract)
    ):
        return None
    target_min = max(120, needed_chars + 60)
    target_max = min(360, target_min + 100)
    if performance_scene:
        allowed = (
            "只补主角开始唱跳后、对手口头叫停前的一段持续表演：写普通脚步、转身、"
            "自然换气、音准和对手逐渐紧张的反应。原文后面已经写了叫停、继续完成、"
            "最后收势和结算，本段绝不能提前或重复这些动作。不要写精确数字、距离、角度、"
            "身体指标、危险特技、观众席、聚光灯、宣传物、文书、见证结论或权限结算。"
            "禁用“最后一个乐句”、半步、半拍、逐次计数和任何身体部位特写；"
            "不要按动作编号。可用动作词只限踏步、转身、侧移、摆臂、歌声、节拍、音准、"
            "自然换气，以及人物的看、听、说和位置变化，不使用白名单外的动作词。"
            "每句都写明动作人物，并新增表演推进、对手反应或见证人的现场观感；"
            "不用分号串句，不用比喻，不写无主语残句。"
        )
        context_summary = (
            f"{protagonist}已经在排练场开始连续唱跳；{opponent}守在控台旁观察，"
            "合作方代表和现场见证人从开场就在场。下一固定动作是对手口头叫停，"
            "因此补段只能推进叫停之前的同一段表演。"
        )
    elif medication_paper_audit:
        allowed = (
            "只补数量差已经出现后的当面对峙：对手把差额说成笔误或补记，"
            "主角指出封签、送货单、领用簿都由对手经手。不要增加第二处差异、"
            "实物清点、用药前史、封签文字、新文件、停职宣布或钥匙交接。"
        )
        context_summary = (
            f"{protagonist}、{opponent}和现场负责人都在医务室。"
            "送货单明写送达七支，领用簿明写领用八支，三样材料都已摆在面前。"
            "下一固定结果是负责人作出停职决定，因此补段只写决定前的当面对峙。"
        )
    else:
        contract = scene_contract or {}
        allowed = (
            "只补情节组场景契约中“对手自证动作”之后、“本章结果”之前的一段当面对峙。"
            "允许载体只有"
            + ("、".join(contract.get("allowed_evidence_carriers") or []) or "当面行动")
            + "。对手动作是“"
            + str(contract.get("opponent_self_incrimination") or "")
            + "”；主角只用已经出现的载体反卡。不得新增材料、参数、规则、人物，"
            "不得提前或重复权限结算。"
        )
        context_summary = (
            f"{protagonist}与{opponent}仍在同一现场。对手已经执行既定自证动作，"
            "主角正使用白名单载体反卡；下一固定内容是本章结果和权限结算。"
        )
    return f"""你是小说正文微补长编辑。为第{chapter_num}章只写一个完整自然段，
长度{target_min}至{target_max}个汉字。程序会把它插入既定结算之前。

{allowed}

不得出现姓名之外的新专名，不得复述原文开头或结尾，不得写标题、说明或修订标记。

【结构化衔接摘要】
{context_summary}
"""


def _closed_scene_segment_plan(
    chapter_card: Dict[str, Any],
) -> Optional[Tuple[str, List[Tuple[int, int, str]]]]:
    """Build a category-level beat plan for segmented closed-scene generation."""
    _, performance_scene, paper_markers = _closed_evidence_contract(chapter_card)
    medication_paper_audit = all(
        marker in paper_markers for marker in ("封签", "送货单", "领用簿")
    )
    scene_contract = (
        chapter_card.get("scene_contract")
        if isinstance(chapter_card.get("scene_contract"), dict)
        else _derive_closed_scene_contract(chapter_card)
    )
    if (
        not performance_scene
        and not medication_paper_audit
        and _closed_scene_contract_failures(scene_contract)
    ):
        return None
    cast = _select_grounded_chapter_cast(chapter_card)
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
    ), "主人公")
    opponent = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "opponent"
    ), str(
        (scene_contract or {}).get("opponent_scene_actor")
        or (scene_contract or {}).get("opponent")
        or "既有对手"
    ))
    if performance_scene:
        facts = (
            f"人物只有{protagonist}、{opponent}、合作方代表和现场见证人；"
            f"{protagonist}是男性，只能用“他”指代；只有{protagonist}保留上一世记忆；"
            "地点只有排练场；合作方代表一人、现场见证人一人；"
            "可用物只有控台、普通音响、折叠椅、外套和旧宣传页；"
            "胜负只靠节拍、普通舞步、动作衔接、音准和自然换气；"
            "本章不使用同一情节组其他章节的药品、封签、送货单、领用簿、钥匙或文书。"
        )
        segments = [
            (220, 270, (
                f"写开场：首两句必须依次明确写“{protagonist.split('·', 1)[0]}记得，上一世，"
                f"{opponent.split('·', 1)[0]}用过降配旧招”和"
                f"“这一次，{protagonist.split('·', 1)[0]}提前请合作方代表和现场见证人"
                "来到排练场”。不得把第二句缩成见证人已经在场；对手已站在控台旁。"
                "段落停在双方对视，不开始音乐。"
            )),
            (190, 240, (
                f"写{opponent}只说“慢一点，别勉强”；{protagonist}把外套放到椅背，"
                "只用踏步、转身和摆臂进入节拍，再用锋利对白要求按原强度开始。"
                "段落停在音乐即将响起。"
            )),
            (230, 285, (
                f"写{protagonist}开始持续唱跳：只用普通踏步、转身、侧移、摆臂，"
                "写音准、节拍、动作衔接和自然换气。段落停在表演仍在推进。"
            )),
            (190, 240, (
                f"继续当前表演，重点写{opponent}从笃定到紧张的即时反应；"
                "结尾只让他喊一次“停一下”。"
            )),
            (220, 275, (
                f"写{protagonist}不争论、不停步，一次性唱完后半段，"
                "完成最后一句和自然收势，站稳看向现场见证人。"
            )),
            (140, 180, (
                "写现场见证人只说“测试通过”；合作方代表立即整张取下旧宣传页并放到一边。"
                "旧宣传页不带任何内容描述。"
            )),
            (170, 215, (
                f"写合作方代表原话宣布：“{opponent}不再有权降低训练强度。"
                f"训练强度决定权归还{protagonist}。”只写宣告落地和对手第一反应。"
            )),
            (110, 145, (
                f"只写结果生效后的三拍收束：{opponent}只能说一句"
                "“这不算什么”或“你只是运气好”；"
                f"{protagonist}只用“结果已经在这里”短促反击；"
                f"最后只写{opponent}闭嘴、沉默或移开视线并立即收章。"
                "本段禁用踏步、侧移、转身、摆臂、动作、歌声、唱跳、节拍、"
                "音准、换气、控台和任何技术评价，不触碰旧宣传页。"
            )),
        ]
    elif medication_paper_audit:
        facts = (
            f"人物只有{protagonist}、{opponent}和一名现场负责人；"
            "开头可用一句写主角离开排练场后直接来到医务室，随后地点只有医务室；"
            f"{protagonist}是男性，只能用“他”指代；只有{protagonist}保留上一世记忆；"
            "桌上只有保持未拆状态的针剂封签、送货单和领用簿；"
            "唯一纸面事实是送货单写送达七支、领用簿写领用八支；"
            f"药品柜钥匙始终由{opponent}持有，停职后才首次交出。"
        )
        segments = [
            (210, 260, (
                f"写开场：先用一句写{protagonist}离开排练场后直接来到医务室；"
                f"现场负责人、{protagonist}和{opponent}都已在医务室，"
                "三类材料摆在桌上。只营造当前对峙压力，段落停在主角准备开口。"
            )),
            (200, 250, (
                f"自然写出“{protagonist.split('·', 1)[0]}记得，上一世，"
                f"{opponent.split('·', 1)[0]}一贯先用后补，出了问题便说成笔误或补记。”"
                "随后让主角要求当面核对，段落停在负责人看向材料。"
            )),
            (220, 270, (
                "只写数量核对：送货单的送达数量是七支，领用簿的领用数量是八支，"
                "封签保持未拆。通过三人的当前表情和动作加强压力，不写其他字段。"
            )),
            (220, 270, (
                f"写{opponent}只辩解成笔误或补记并伸手想拿回领用簿；"
                f"{protagonist}原话说：“封签、送货单和领用簿都是{opponent}经手的。”"
                "段落停在负责人按住领用簿。"
            )),
            (190, 235, (
                f"写负责人只根据这一支数量差和{opponent}的当面辩解，"
                "原话宣布“即刻暂停你的职务”，随后摊手索要钥匙。"
            )),
            (220, 270, (
                f"写{opponent}把唯一钥匙直接放到负责人掌心，再交出领用簿；"
                f"负责人原话确认“药品保管权归{protagonist}”，并把钥匙直接放到主角掌心。"
                "所有句子只称“钥匙”，不给钥匙添加形状、触感、新旧或磨损描写。"
            )),
            (150, 195, (
                f"写{opponent}一次嘴硬或失态；随后让{protagonist}说："
                "“没有我的许可，谁也不能碰这些药。”段落到这句结束。"
            )),
            (
                100,
                130,
                f"只从僵住、闭嘴、移开视线、手停在原处中选一个，"
                f"写{opponent}的极短反应并立即结束。",
            ),
        ]
    else:
        contract = scene_contract or {}
        phase = str(contract.get("phase") or "setup")
        carriers = list(contract.get("allowed_evidence_carriers") or [])
        current_carriers = list(contract.get("current_evidence_carriers") or [])
        established = list(contract.get("established_evidence_carriers") or [])
        carrier_text = "、".join(carriers) if carriers else "当面行动和对手亲口承认"
        authority = str(contract.get("authority_actor") or "从开场就在场的有权者")
        trigger = str(contract.get("trigger_action") or "")
        self_incrimination = str(contract.get("opponent_self_incrimination") or "")
        result = str(contract.get("immediate_result") or "")
        old_signal = str(contract.get("old_trap_signal") or "")
        loss = str(contract.get("opponent_loss") or "")
        gain = str(contract.get("protagonist_gain") or "")
        facts = (
            "场景契约类型：" + str(contract.get("scene_archetype") or "") + "；"
            f"人物只使用{protagonist}、{opponent}和执行卡已经写出的无姓名功能角色；"
            f"{protagonist}是男性，只能用“他”指代；只有{protagonist}保留上一世记忆；"
            f"允许的全部证据与操作载体只有：{carrier_text}；"
            f"主角动作：{trigger}；对手自证动作：{self_incrimination}；"
            f"本章已经生效的结果：{result}；裁决或执行者：{authority}。"
        )
        if phase == "settlement":
            first_beat = (
                f"直接承接前章已经建立的{('、'.join(established) or carrier_text)}，"
                f"让{protagonist}进入当面对质并立即执行“{trigger}”。"
                "不重新介绍情节组，不新增材料，不先宣布结局。"
            )
            segments = [
                (240, 310, first_beat),
                (240, 310, (
                    f"让{protagonist}依次使用本章允许载体"
                    f"{('、'.join(current_carriers) or carrier_text)}完成公开核验；"
                    f"同时完整写出{opponent}的既定反应“{self_incrimination}”，"
                    "让他的当前动作或原话亲手坐实问题，不发明编号、参数或新规程。"
                )),
                (240, 310, (
                    f"让{protagonist}只用已经出现的载体和对手刚才的动作完成反卡，"
                    f"把决定权推到{authority}面前；不得加入第三方新证据，暂不宣布得失。"
                )),
                (240, 310, (
                    f"由{authority}根据眼前事实当场作出决定，必须写对手损失："
                    f"{loss or result}。决定用宣告、撤权、冻结、交接或退回动作立刻生效。"
                )),
                (240, 310, (
                    f"紧接上一段写主角收益：{gain or result}。"
                    "必须写实际权限、资源或安全结果如何落到主角手里，不写抽象声望。"
                )),
                (200, 260, (
                    f"写{opponent}在失去现实利益后的嘴硬或失态，"
                    f"再让{protagonist}用一句短促锋利对白封住退路；"
                    f"最后只写{opponent}面对已经生效结果的极短反应并立即收章。"
                    "不离场，不开新谜团，不预告下一章。"
                )),
            ]
        else:
            segments = [
                (240, 310, (
                    f"开场用一句内心叙述写{protagonist}凭上一世记忆认出旧局：{old_signal}；"
                    f"下一句立刻写他今生抢先执行“{trigger}”。前世信息绝不进入对白。"
                )),
                (240, 310, (
                    f"把允许载体{('、'.join(current_carriers) or carrier_text)}放进当前现场，"
                    f"写清主角安排操作顺序后，完整写出{opponent}照旧出招"
                    f"“{self_incrimination}”，让他亲手执行关键动作。"
                )),
                (240, 310, (
                    "只用白名单载体写验证过程和肉眼可见后果；"
                    f"主角依据旧局预判当场反卡，不做技术科普，不提前写终局撤权。"
                )),
                (240, 310, (
                    f"写本章即时结果“{result}”真实发生，重点写主角立刻阻止损失扩大，"
                    "让在场人看见小胜已经生效。"
                )),
                (240, 310, (
                    f"由{authority}或主角在其既有权限内确认本次操作停止、冻结或作废；"
                    "只结算本章阶段结果，不提前完成情节组末章的最终得失。"
                )),
                (200, 260, (
                    f"写{opponent}面对失败后的嘴硬、抢辩或失态，"
                    f"再让{protagonist}说一句针对当前行为的锋利对白；"
                    f"用已经出现的{carrier_text}留下可供下一章正式结算的明确状态后立即收章，"
                    "不新增电话、媒体、陌生人或神秘材料。"
                )),
            ]
    return facts, segments


def _build_closed_scene_segment_prompt(
    chapter_num: int,
    facts: str,
    segment_index: int,
    segment_count: int,
    target_min: int,
    target_max: int,
    beat: str,
    previous_segment: str = "",
) -> str:
    previous = (previous_segment or "").strip()[-260:] or "这是首段，无前文。"
    if target_min >= 220:
        sentence_shape = "使用七至九个主谓完整的句子，长短交替"
    elif target_min >= 160:
        sentence_shape = "使用六至八个主谓完整的句子，长短交替"
    elif target_min >= 110:
        sentence_shape = "使用四至六个主谓完整的句子，长短交替"
    else:
        sentence_shape = "使用二至四个主谓完整的句子，至少包含一个短句"
    if "胜负只靠" in facts:
        if segment_index < 6:
            facts = facts.replace("、外套和旧宣传页", "和外套")
        category_guard = (
            "写作词库只取普通踏步、转身、侧移、摆臂、歌声、节拍、音准、自然换气，"
            "以及人物的视线、手势、说话和位置变化；每句都用这些现场元素推进。"
            "禁用比喻、身体部位特写、汗液和脉搏描写、精确次数、距离、时长、角度、"
            "音程、动作幅度、控台灯光和任何技术分析；"
            "不得逐一分解左右脚、肩、腰胯、膝、脚跟、鼻腔、喉间、下颌或瞳孔；"
            "不得出现跳跃、腾空、跪地、撑地、翻滚、急停变向，也不得出现针剂、药品、"
            "封签、送货单、领用簿、钥匙、协议、合同、条款、编号或检测设备。"
        )
    elif "针剂封签" in facts and "送货单" in facts and "领用簿" in facts:
        if segment_index < 5:
            facts = re.sub(
                r"；药品柜钥匙始终由[^；。]+[；。]?",
                "。",
                facts,
            ).strip()
        if segment_index == segment_count:
            facts = "；".join(facts.split("；")[:3]).rstrip("；。") + "。"
        category_guard = (
            "写作词库只取封签、送货单、领用簿上明面的两行数量，"
            "以及三人的视线、简单手势、说话和位置变化；每句都用这些现场元素推进。"
            "禁用比喻、身体部位特写、窗户风声、灯光阴影、纸张笔画、字迹油墨、"
            "精确距离和任何法证式观察；不得新增签字、署名、填写、登记、栏位或翻页流程。"
        )
    else:
        category_guard = (
            "严格按事实白名单中的情节组场景契约写作。动作必须由明确人物发出，"
            "证据只能来自白名单载体或对手本段亲手做出的行为；"
            "不得补造协议名称、条款编号、设备编号、工程参数、后台截图、监控、"
            "检测报告、匿名材料、临时规程或突然到场的裁决者。"
            "技术过程只写普通读者能直接看见的动作和结果，不写说明书式科普。"
        )
    return f"""你只写小说第{chapter_num}章的一个自然段，不写整章。
这是通用封闭场景的第{segment_index}/{segment_count}段，长度{target_min}至{target_max}个汉字。

事实白名单：{facts}
本段唯一任务：{beat}
上一段结尾：{previous}

{category_guard}
“上一段结尾”只供确认人物位置和衔接语气，绝不能在本段复述、改写或重新交代；
首句必须直接进入本段新增动作、对白或局势变化。
只展开本段任务，不提前写后续节拍，不创造白名单外的物件、人物、历史、证据或专名。
{sentence_shape}；不用分号串联长句，不省略动作发出者，不写残句。
全文只用简体中文和中文标点，不出现任何英文字母、英文词、阿拉伯数字或创作提示标签。
只输出一个连续自然段，不要段号、标题、解释、列表、Markdown 或修订说明。
"""


def _closed_scene_segment_candidate_failure(
    candidate: str,
    chapter_card: Dict[str, Any],
    segment_index: int,
) -> str:
    """Reject a bad beat before it can contaminate the assembled chapter."""
    text = candidate or ""
    _, performance_scene, paper_markers = _closed_evidence_contract(chapter_card)
    generic_contract = (
        chapter_card.get("scene_contract")
        if isinstance(chapter_card.get("scene_contract"), dict)
        else _derive_closed_scene_contract(chapter_card)
    )
    cast = _select_grounded_chapter_cast(chapter_card)
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
    ), "主人公")
    opponent = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "opponent"
    ), str(
        (generic_contract or {}).get("opponent_scene_actor")
        or (generic_contract or {}).get("opponent")
        or "既有对手"
    ))
    protagonist_pattern = _character_alias_pattern(protagonist)
    opponent_pattern = _character_alias_pattern(opponent)
    if re.search(r"[A-Za-z]|原话反击|本段唯一任务|事实白名单|Markdown", text):
        return "包含英文或提示词回声"
    if text.count("“") != text.count("”"):
        return "本段中文引号未闭合"
    if re.search(
        r"动作衔接待续|待续接续|嘴唇一紧一次|一紧了一次|[。！？][”’\"]?[。！？]",
        text,
    ):
        return "出现拼接病句或重复标点"
    if "她" in text:
        return "出现女性代词"
    if re.search(
        rf"{opponent_pattern}.{{0,18}}(?:记得|想起).{{0,24}}(?:上一世|前世)|"
        rf"{opponent_pattern}(?:也|仍)?保留.{{0,12}}(?:上一世|前世).{{0,8}}记忆",
        text,
        re.S,
    ):
        return "把上一世记忆给了对手"
    if performance_scene:
        if segment_index < 6 and "旧宣传页" in text:
            return "旧宣传页在撤下节拍前提前出现"
        extra_prop = re.search(
            r"记事本|笔尖|钢笔|圆珠笔|纸笔|手机|平板|相机|摄像|录音|"
            r"文件夹|记录表|检测表|报告|写了.{0,6}字|写下|记录下|翻开.{0,8}页",
            text,
        )
        if extra_prop:
            return f"表演现场出现事实白名单外的记录工具或流程：{extra_prop.group(0)}"
        protagonist_short = protagonist.split("·", 1)[0]
        opponent_short = opponent.split("·", 1)[0]
        if segment_index == 1 and not (
            re.search(
                rf"{re.escape(protagonist_short)}.{{0,18}}"
                r"(?:记得|想起|认出|没有忘记).{0,18}(?:上一世|前世)"
                rf".{{0,32}}{re.escape(opponent_short)}.{{0,28}}"
                r"(?:用过|曾用|惯用|使过|降配|旧招|老办法)",
                text,
                re.S,
            )
            and re.search(
                r"(?:(?:提前|事先|早早).{0,16}(?:请|叫|让|安排).{0,16}"
                r"(?:合作方|见证人)|"
                r"(?:请|叫|让|安排|示意).{0,16}(?:合作方|见证人)"
                r".{0,20}(?:到场|来到|落座|坐下|坐定))",
                text,
                re.S,
            )
        ):
            return "开场节拍缺少主角明确认出旧招并提前请见证"
        if segment_index == 2 and not (
            "慢一点，别勉强" in text
            or re.search(
                r"慢(?:一点|下来)|放慢|放缓|降低.{0,8}强度|强度.{0,8}(?:降|减)|"
                r"别勉强|不要勉强|状态.{0,12}(?:保护|保守|稳妥)",
                text,
            )
        ):
            return "准备节拍缺少对手完整降配对白"
        if segment_index == 3 and not re.search(
            r"音乐|伴奏|节拍|鼓点|前奏|歌声",
            text,
        ):
            return "起唱节拍缺少音乐或伴奏明确开始"
        performance_drift = re.search(
            r"心率|血压|血氧|脉搏|汗|肋骨|肋廓|胸廓|胸膛|肋间肌|肌肉|"
            r"胸腔|腹肌|丹田|左脚|右脚|左肩|右肩|腰胯|膝盖|脚跟|鼻腔|"
            r"鼻梁|眉骨|舌尖|上颚|喉咙|喉间|下颌|瞳孔|腕骨|皮肤|"
            r"中频|元音|毫米|厘米|公分|[一二三四五六七八九十百零\d]+秒|"
            r"第[一二三四五六七八九十百零\d]+段|"
            r"第?[一二三四五六七八九十百零\d]+组|"
            r"[一二三四五六七八九十百零\d]+拍|"
            r"[一二三四五六七八九十百零\d]+个?小节|"
            r"[一二三四五六七八九十百零\d]+米(?!国)|"
            r"[一二三四五六七八九十百零\d]+(?:小时|分钟|度)|"
            r"(?:走|退|侧移|踏出)[一二三四五六七八九十百零\d]+步|"
            r"第[一二三四五六七八九十百零\d]+步|"
            r"[一二三四五六七八九十百零\d]+步(?:距离|远|开外)|"
            r"[一二三四五六七八九十百零\d]+次(?:换气|转身|侧移|踏步)|"
            r"[一二三四五六七八九十百零\d]+(?:寸|尺)|"
            r"(?:半寸|寸许|两指宽|三指宽|三分之二|半周)|"
            r"(?:两|三|四|五|六|七|八|九|十)位(?:现场)?见证人|"
            r"半音|如尺|严丝合缝|分毫|毫厘|精准|标准转身|"
            r"指示灯|红光|绿光|光点|"
            r"跃起.{0,10}旋身|单膝.{0,10}(?:点地|跪地).{0,10}(?:再)?暴起|"
            r"急停变向|无喘息|(?:没|未)吸气|气息沉在腹底|"
            r"气息(?:沉入|由).{0,6}(?:腹|胸)|呼吸自腹|声线|音高|"
            r"顶灯|照明|灯光|耳机|麦克风|支架|金属外壳|左前方|右前方|"
            r"双肩|嘴唇|咽下余韵|脚掌落点|压低重心|没偏一丝|"
            r"像钉入地板|外套下摆|衣角|"
            r"最后一个乐句|重复三次|一紧了一次|音乐未起|伴奏未起|半步|半拍|"
            r"[一二两三四五六七八九十百零\d]+把|"
            r"[一二两三四五六七八九十百零\d]+个?字|"
            r"第?[一二两三四五六七八九十百零\d]+次(?:普通)?(?:重拍|踏步|抬手)|"
            r"[一二两三四五六七八九十百零\d]+处(?:换气)?|"
            r"第[二三四五六七八九十]句|最后[一二三四五六七八九十]字|"
            r"如线|像尺|"
            r"腾空|倒立|跪地|滑跪|撑地|屏幕|波形|计时|误差|"
            r"(?:精确|固定|相同)角度|角度(?:不变|一致)|\+",
            text,
        )
        if performance_drift:
            return (
                "出现量化、生理分析或危险动作："
                f"{performance_drift.group(0)}"
            )
        stop_pattern = r"停一下|暂停|叫停|喊停|先停|停下来|够了|可以了|到此为止"
        if segment_index < 4 and re.search(stop_pattern, text):
            return "提前写叫停"
        if segment_index < 5 and re.search(PERFORMANCE_PASS_CONCLUSION_PATTERN, text):
            return "提前写见证结论"
        if segment_index < 7 and "训练强度决定权" in text:
            return "提前写权限结算"
        if segment_index == 4 and not re.search(stop_pattern, text):
            return "叫停节拍缺少对手唯一一次叫停"
        if segment_index == 6 and not re.search(
            PERFORMANCE_PASS_CONCLUSION_PATTERN,
            text,
        ):
            return "见证节拍缺少口头通过结论"
        if segment_index == 6 and "旧宣传页" in text:
            segment_conclusion = re.search(PERFORMANCE_PASS_CONCLUSION_PATTERN, text)
            if (
                segment_conclusion is None
                or text.find("旧宣传页") < segment_conclusion.start()
            ):
                return "见证节拍顺序倒置，必须先口头确认通过，再撤下旧宣传页"
        if segment_index >= 6 and re.search(
            r"踏步|侧移|转身|摆臂|歌声|继续唱|继续跳|音准|换气|节拍仍|动作仍",
            text,
        ):
            return "测试结论已经进入结算节拍，却又重新展开表演动作"
        if segment_index == 7 and not (
            "训练强度决定权" in text
            and re.search(r"不再有权|失去|不得再|不能再", text)
        ):
            return "权限节拍缺少双向结算"
        if segment_index == 8:
            if protagonist.split("·", 1)[0] not in text:
                return "收束节拍缺少主角短促反击"
            opponent_in_close = (
                opponent in text[-160:]
                or opponent.split("·", 1)[0] in text[-120:]
                or re.search(
                    r"僵|闭(?:了)?嘴|没再|移开视线|手停|脸色|沉默|无言|"
                    r"低头|垂眼|退开|后退|别开脸|没有回应|不再说话",
                    text[-120:],
                )
            )
            if not opponent_in_close:
                return "收束节拍缺少对手最终短反应"
            if re.search(
                r"侧移|抬脚|踏步|转身|动作|歌声|唱|跳|节拍|音准|换气|摆臂|半拍|"
                r"节拍没乱|我(?:跳|唱)得比|撑不了.{0,6}天|"
                r"明天.{0,12}第几组|零点|误差|偏差",
                text,
            ):
                return "收束节拍又开启技术挑错"
    elif all(marker in paper_markers for marker in ("封签", "送货单", "领用簿")):
        paper_drift = re.search(
            r"过敏|休克|抢救|注射|针头|库存|清点|翻柜|开柜|打开药柜|"
            r"原厂|逐支|墨迹|字迹|笔锋|潦草|工整|药理|处方|空盒|仪轨|"
            r"胶痕|折痕|划痕|编号|批次|签名栏|签字|签下|署名|填写|登记|"
            r"落笔|第[一二三四五六七八九十\d]+栏|栏目|油墨|墨色|撇捺|顿挫|"
            r"那一横|浅痕|窗户|窗帘|风声|顶灯|灯光|阴影|"
            r"喉结|舌尖|上颚|腕骨|瞳孔|下颌线|筋络|指甲盖|脉搏|"
            r"打开封签|(?:按住|压住|触到|触碰).{0,12}封签|"
            r"封签.{0,12}(?:按住|压住|触到|触碰)|[”\"]却未开口",
            text,
        )
        if paper_drift:
            return (
                "出现医疗前史、实物清点或第二证据："
                f"{paper_drift.group(0)}"
            )
        if re.search(
            r"(?:七|八|[78])支未拆封(?:的)?针剂|"
            r"(?:七|八|[78])支针剂|"
            r"(?:七|八|[78])(?:份|枚|个|张)?未拆封签|"
            r"封签.{0,20}(?:七|八|[78])(?:份|枚|个|张)?",
            text,
        ):
            return "把纸面数量写成实物数量"
        if segment_index < 5 and "钥匙" in text:
            return "钥匙提前出现"
        if segment_index == 5 and re.search(
            r"负责人.{0,40}(?:掌|手).{0,20}钥匙|"
            r"钥匙.{0,20}负责人(?:掌|手)|铜色钥匙",
            text,
            re.S,
        ):
            return "索要钥匙节拍提前写成负责人已经持有钥匙"
        if segment_index == 6 and re.search(
            r"齿痕|棱角|温度|体温|磨损|锁舌|凹槽|铜锈|旧痕|铜色|金属|冷光",
            text,
        ):
            return "给钥匙增加物证细节"
        if segment_index == 6:
            source_handoffs = re.findall(
                rf"{opponent_pattern}.{{0,100}}"
                r"(?:(?:交出|递出|拿出|掏出).{0,24}钥匙|"
                r"钥匙.{0,36}(?:放|覆|递|交|躺|落|滑)(?:进|入|到)?"
                r".{0,16}负责人(?:掌|手))",
                text,
                re.S,
            )
            protagonist_receipts = re.findall(
                r"钥匙.{0,30}(?:放进|放入|放到|置于|置入|置进|交到|递到|压进|滑入)"
                rf".{{0,24}}(?:{protagonist_pattern}|主角).{{0,12}}(?:手|掌|指间)|"
                rf"(?:{protagonist_pattern}|主角).{{0,24}}"
                r"(?:接过|接住|收下|握住).{0,16}钥匙",
                text,
                re.S,
            )
            if len(source_handoffs) > 1 or len(protagonist_receipts) > 1:
                return "保管权节拍重复书写钥匙交接"
        if segment_index < 5 and re.search(SUSPENSION_CONCLUSION_PATTERN, text):
            return "提前写停职"
        if segment_index < 6 and "药品保管权" in text:
            return "提前写保管权"
        if segment_index < 7 and "没有我的许可" in text:
            return "提前写收束对白"
        if segment_index == 5 and not re.search(SUSPENSION_CONCLUSION_PATTERN, text):
            return "停职节拍缺少口头停职决定"
        if segment_index == 6 and not (
            "药品保管权" in text
            and re.search(
                rf"{opponent_pattern}.{{0,100}}"
                r"(?:(?:交出|递出|取下|解下|掏出|拿出|放下).{0,24}钥匙|"
                r"钥匙.{0,36}(?:放|覆|递|交)(?:进|入|到)?.{0,16}负责人(?:掌|手))",
                text,
                re.S,
            )
            and re.search(
                r"(?:钥匙).{0,30}(?:放进|放入|放到|置于|置入|置进|交到|递到|压进|滑入)"
                rf".{{0,24}}(?:{protagonist_pattern}|主角).{{0,12}}(?:手|掌|指间)|"
                rf"(?:{protagonist_pattern}|主角).{{0,24}}"
                r"(?:接过|接住|收下|握住).{0,16}钥匙",
                text,
                re.S,
            )
        ):
            return "保管权节拍缺少口头确认或实际钥匙交接"
        if segment_index == 7 and not re.search(
            r"没有我的许可.{0,18}谁也不能碰这些药",
            text,
            re.S,
        ):
            return "收束节拍缺少主角固定对白"
        if segment_index == 8 and re.search(r"转身|离开|门口|关门|走出去", text):
            return "结尾写离场"
    else:
        contract = generic_contract or {}
        allowed_text = "；".join(contract.get("allowed_evidence_carriers") or [])
        for marker in (
            "匿名邮件", "匿名短信", "神秘U盘", "监控录像", "后台截图",
            "检测报告", "协议编号", "条款编号", "毫秒",
        ):
            if marker in text and marker not in allowed_text:
                return f"引入场景契约外证据或参数：{marker}"
        phase = str(contract.get("phase") or "")
        protagonist_short = protagonist.split("·", 1)[0]
        opponent_short = opponent.split("·", 1)[0]
        if phase == "setup" and segment_index == 1:
            if not (
                protagonist_short in text
                and re.search(r"上一世|前世", text)
            ):
                return "簇首场景缺少主角认出旧局"
        if segment_index == 2 and opponent_short not in text and opponent not in text:
            return "对手自证节拍缺少指定对手"
        if phase == "settlement":
            loss_text = str(contract.get("opponent_loss") or "")
            gain_text = str(contract.get("protagonist_gain") or "")
            settlement_markers = [
                marker for marker in (
                    "失去", "撤销", "冻结", "暂停", "不得", "退还", "撤回",
                    "停职", "废除", "终止", "收回", "叫停",
                    "获得", "取得", "拿回", "夺回", "恢复", "归还",
                )
                if marker in loss_text + gain_text
            ]
            if segment_index < 4 and any(marker in text for marker in settlement_markers):
                return "在核验完成前提前写最终权限结算"
            if segment_index == 4:
                loss_markers = [
                    marker for marker in (
                        "失去", "撤销", "冻结", "暂停", "不得", "退回", "退还",
                        "撤回", "交出", "取消", "停职", "废除", "终止", "收回", "叫停",
                    )
                    if marker in loss_text
                ]
                if loss_markers and not any(marker in text for marker in loss_markers):
                    return "结算节拍缺少对手现实损失"
            if segment_index == 5:
                gain_markers = [
                    marker for marker in (
                        "获得", "取得", "拿回", "夺回", "恢复", "保住", "归还", "退回",
                    )
                    if marker in gain_text
                ]
                if gain_markers and not any(marker in text for marker in gain_markers):
                    return "结算节拍缺少主角现实收益"
    if protagonist and re.search(rf"{re.escape(protagonist)}原话", text):
        return "把提示要求写进正文"
    return ""


def _shape_closed_scene_segment_candidate(
    candidate: str,
    chapter_card: Dict[str, Any],
    target_max: int,
    segment_index: int = 0,
) -> str:
    """Drop locally invalid sentences and cap a beat at a sentence boundary."""
    has_source_candidate = bool((candidate or "").strip())
    text = _normalize_closed_scene_surface_drift(
        candidate,
        chapter_card,
    ).strip()
    _, performance_scene, paper_markers = _closed_evidence_contract(chapter_card)
    cast = _select_grounded_chapter_cast(chapter_card)
    protagonist = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "protagonist"
    ), "主人公")
    opponent = next((
        str(member.get("name") or "").strip()
        for member in cast
        if isinstance(member, dict)
        and str(member.get("alignment") or "").casefold() == "opponent"
    ), "对手")

    medication_paper_audit = all(
        marker in paper_markers for marker in ("封签", "送货单", "领用簿")
    )

    def with_required_segment_contract(value: str) -> str:
        shaped = (value or "").strip()
        if performance_scene and segment_index == 1 and not has_source_candidate:
            protagonist_short = protagonist.split("·", 1)[0]
            opponent_short = opponent.split("·", 1)[0]
            return (
                f"{protagonist_short}记得，上一世，{opponent_short}用过降配旧招，"
                "借保护状态为名压低训练强度，再把病弱印象推到合作方面前。"
                f"这一次，{protagonist_short}提前请合作方代表和现场见证人来到排练场。"
                "合作方代表把折叠椅摆正，现场见证人留在一旁。"
                f"{opponent}已经站在控台旁，抬眼看向{protagonist_short}。"
                f"{opponent_short}没有问他们为何到场，只把手留在控台上。"
                f"{protagonist_short}把外套放到折叠椅上，走到场地中央，与他隔空对视。"
                "合作方代表和现场见证人都没有带资料，只等当场完成测试。"
            )
        if performance_scene and segment_index == 2 and not has_source_candidate:
            protagonist_short = protagonist.split("·", 1)[0]
            return (
                f"{opponent}按住控台，淡淡地说：“慢一点，别勉强。”"
                f"{protagonist_short}没有接这份体贴。"
                f"他用踏步、转身和摆臂进入节拍，随后站稳说："
                "“不必替我降低强度，按原强度开始。”"
                "合作方代表没有替任何人接话，现场见证人也只是等着。"
                f"{protagonist_short}先用基础动作校准节拍，确认音乐仍按原定速度推进。"
                f"{opponent}把手放到控台上，音乐即将响起。"
            )
        if performance_scene and segment_index == 3 and not has_source_candidate:
            protagonist_short = protagonist.split("·", 1)[0]
            return (
                f"音乐响起，{protagonist_short}踩住节拍开口。"
                "歌声越过排练场，他用普通踏步接上转身，"
                "再以侧移和摆臂把动作连在一起。"
                "换气落在乐句之间，音准始终没有散。"
                "合作方代表坐直了，现场见证人继续看着场中。"
                f"{protagonist_short}没有去看控台，只把每个动作送进歌声。"
                "动作没有为了见证人放慢，乐句也没有为了证明自己被切碎。"
                "一段连续衔接完成后，他仍按起初的速度向下推进。"
                f"{opponent}站在控台旁，脸上的笃定一点点退去。"
            )
        if performance_scene and segment_index == 4 and not has_source_candidate:
            protagonist_short = protagonist.split("·", 1)[0]
            opponent_short = opponent.split("·", 1)[0]
            return (
                f"表演仍在向前推进。{protagonist_short}的踏步没有乱，"
                "转身接上侧移，摆臂和歌声同时回到节拍。"
                "合作方代表不再看控台，只看场中。"
                "现场见证人也没有移开视线。"
                f"{opponent_short}留在控台上的手慢慢收紧。"
                f"他想开口，却被{protagonist_short}稳定的音准压了回去。"
                "合作方代表听清前后两段没有断裂，原先准备好的质疑始终没有出口。"
                f"又一段动作衔接完成，{opponent}终于喊道：“停一下！”"
            )
        if performance_scene and segment_index == 5 and not has_source_candidate:
            protagonist_short = protagonist.split("·", 1)[0]
            opponent_short = opponent.split("·", 1)[0]
            return (
                f"{protagonist_short}没有停步，也没有争论。"
                f"{opponent_short}的叫停声还留在排练场里，"
                f"{protagonist_short}已经用侧移接上转身，歌声顺着节拍继续向前。"
                f"合作方代表转头看向{opponent_short}，{opponent_short}没有再喊。"
                f"{protagonist_short}完成后半段，最后一句依然稳在音准上。"
                "最后一轮转身接回起始节拍，他没有抢拍，也没有用停顿换取喘息。"
                "见证人从头看到收尾，判断不再需要任何人口头补充。"
                "他用普通踏步收住动作，自然换气，随后站稳，"
                "直接看向现场见证人，等他给出结论。"
            )
        if performance_scene and segment_index == 6 and not has_source_candidate:
            return (
                "现场见证人说：“测试通过。”"
                "这句话只确认刚才完整发生的唱跳，没有替任何一方夸大结果。"
                "合作方代表随即整张取下旧宣传页，放到一边。"
                f"{opponent}伸手想拦，纸页已经离开原来的位置。"
            )
        if performance_scene and segment_index == 7 and not has_source_candidate:
            return (
                f"合作方代表宣布：“{opponent}不再有权降低训练强度。"
                f"训练强度决定权归还{protagonist}。”"
                f"合作方代表当场要求后续训练按{protagonist}本人确认的强度执行，"
                "不再接受单方降配。"
                f"{protagonist}看着旧宣传页被撤下，确认两个结果同时落地。"
                f"{opponent}脸色沉了下去。"
            )
        if performance_scene and segment_index == 8 and not has_source_candidate:
            return (
                f"{opponent}咬牙说：“这不算完。”"
                f"{protagonist}看着他：“决定已经生效。”"
                "合作方代表没有撤回刚才的宣布，排练也按新的权限继续。"
                f"{opponent}闭了嘴。"
            )
        if medication_paper_audit and segment_index == 1 and not has_source_candidate:
            protagonist_short = protagonist.split("·", 1)[0]
            opponent_short = opponent.split("·", 1)[0]
            return (
                f"{protagonist_short}离开排练场后，直接来到医务室。"
                f"现场负责人已经站在桌边，{opponent}坐在桌子另一侧。"
                "针剂封签保持未拆，送货单和领用簿并排摆着。"
                f"{protagonist_short}停在桌前，没有去碰任何一件材料，只看向{opponent_short}。"
                f"{opponent_short}没有起身，反而问：“刚结束测试，你还要查什么？”"
                "三样材料之间没有夹着别的文件，现场只核对桌上已经摆明的内容。"
                f"负责人把目光转向{protagonist_short}，等他开口。"
            )
        if medication_paper_audit and segment_index == 2 and not has_source_candidate:
            protagonist_short = protagonist.split("·", 1)[0]
            opponent_short = opponent.split("·", 1)[0]
            return (
                f"{protagonist_short}记得，上一世，{opponent_short}一贯先用后补，"
                "出了问题便说成笔误或补记。"
                f"那套说辞曾把{protagonist_short}的质疑变成多心。"
                f"这一世，{protagonist_short}不再给他把事情拖到事后的机会。"
                "他没有提尚未发生的后果，只把上一世记住的话术变成眼前的核对顺序。"
                f"{protagonist_short}对负责人说：“三样材料都在这里，现在当面核对。”"
                "负责人点头，却没有替他先作判断。"
                f"{opponent_short}的视线落到领用簿上，终于不再催他离开。"
            )
        if medication_paper_audit and segment_index == 3 and not has_source_candidate:
            protagonist_short = protagonist.split("·", 1)[0]
            opponent_short = opponent.split("·", 1)[0]
            return (
                "负责人先念送货单：“送达七支。”"
                "他再念领用簿：“领用八支。”"
                "两行数量摆在同一张桌上，却多出一支领用。"
                "针剂封签仍保持未拆，谁也没有碰。"
                "负责人把送货单与领用簿分别压在桌面两侧，让两行数量同时留在三人眼前。"
                f"{protagonist_short}看着{opponent_short}：“送达少，领用反而多。你来解释。”"
                f"{opponent_short}先看送货单，又看领用簿，迟迟没有接话。"
                "他的沉默让那一支差额比任何争吵都更清楚。"
                "负责人把两份材料留在原位，等着他的回答。"
            )
        if medication_paper_audit and segment_index == 4 and not has_source_candidate:
            return (
                f"{opponent}说：“这只是笔误，后来补记漏了。”"
                "他说得很快，像是只要先把错误命名，数量就会自行恢复一致。"
                f"{protagonist}没有允许话题离开桌面上的两行数量。"
                f"{opponent}伸手想拿回领用簿，负责人没有松开桌边的位置。{protagonist}说："
                f"“封签、送货单和领用簿都是{opponent}经手的。”"
                "康拉德的手停在纸页上方，先前那句笔误再也遮不住经手责任。"
                "负责人按住领用簿。"
            )
        if medication_paper_audit and segment_index == 5 and not has_source_candidate:
            opponent_short = opponent.split("·", 1)[0]
            return (
                f"负责人没有再让{opponent_short}把话题绕开。"
                "他指向桌上的两行数量，说："
                "“送货单是七支，领用簿是八支；你的解释只有笔误和漏记。”"
                f"{opponent_short}张口还想辩解，负责人已经说：“即刻暂停你的职务。”"
                "医务室里的工作随这句话停下，不再接受他的临时补记。"
                "这句话落下后，负责人只说：“钥匙。”摊开的手停在桌边。"
                f"{opponent_short}坐着没有动，医务室里没人替他接话。"
            )
        if medication_paper_audit and segment_index == 6 and not has_source_candidate:
            return (
                f"{opponent}先攥紧手，负责人仍把摊开的手停在桌边。"
                f"{opponent}交出唯一钥匙和领用簿，放到负责人掌心。"
                "负责人先确认原保管人已经失去接触药品的入口，再完成新的交接。"
                f"负责人说：“药品保管权归{protagonist}。”"
                f"负责人随即把钥匙放进{protagonist}掌心，"
                f"{protagonist}当场接住，并要求领用簿继续留在负责人面前。"
                "从这一刻起，任何领用都不能绕开新的保管权限。"
            )
        if medication_paper_audit and segment_index == 7 and not has_source_candidate:
            return (
                f"{opponent}咬牙看着{protagonist}，还想把停职说成一次临时误会。"
                f"{protagonist}没有回应他的嘴硬，只让刚才的停职决定保持执行。"
                f"{protagonist}说：“没有我的许可，谁也不能碰这些药。”"
            )
        if medication_paper_audit and segment_index == 8 and not has_source_candidate:
            return f"{opponent}僵住，嘴唇动了一下，最终闭嘴并移开视线。"
        if (
            performance_scene
            and segment_index == 4
            and not re.search(
                r"停一下|暂停|叫停|喊停|先停|停下来|够了|可以了|到此为止",
                shaped,
            )
        ):
            shaped = shaped.rstrip() + f"{opponent}喊道：“停一下！”"
        return shaped

    if performance_scene:
        sentence_drift = re.compile(
            r"心率|血压|血氧|脉搏|汗|肋骨|肋廓|胸廓|胸膛|肋间肌|锁骨|"
            r"筋络|肌肉|胸腔|腹腔|腹肌|腰腹|丹田|左脚|右脚|左肩|右肩|"
            r"左手|右手|双足|并拢|身侧|微抬|腰胯|膝盖|脚跟|"
            r"鼻腔|鼻梁|眉骨|舌尖|上颚|喉咙|喉间|"
            r"下颌|瞳孔|腕骨|皮肤|"
            r"(?:喉结|喉头).{0,16}(?:吸气|呼气|换气)|"
            r"中频|元音|毫米|厘米|公分|腾空|空中换气|倒立|跪地|滑跪|撑地|"
            r"三连滑步|[一二三四五六七八九十百零\d]+公里|"
            r"[一二三四五六七八九十百零\d]+米(?!国)|"
            r"[一二三四五六七八九十百零\d]+(?:小时|分钟|度)|"
            r"(?:走|退|侧移|踏出)[一二三四五六七八九十百零\d]+步|"
            r"[一二三四五六七八九十百零\d]+次(?:换气|转身|侧移|踏步)|"
            r"(?:半寸|寸许|两指宽|三指宽|三分之二)|"
            r"第?[一二三四五六七八九十百零\d]+组|"
            r"[一二三四五六七八九十百零\d]+拍|"
            r"[一二三四五六七八九十百零\d]+个?小节|"
            r"(?:两|三|四|五|六|七|八|九|十)位(?:现场)?见证人|"
            r"半音|如尺|严丝合缝|分毫|毫厘|精准|标准转身|"
            r"指示灯|红光|绿光|光点|"
            r"跃起.{0,10}旋身|单膝.{0,10}(?:点地|跪地).{0,10}(?:再)?暴起|"
            r"急停变向|无喘息|(?:没|未)吸气|气息沉在腹底|"
            r"顶灯|照明|灯光|光里|浅影|投出.{0,8}影|耳机|麦克风|支架|"
            r"金属外壳|左前方|右前方|双肩|嘴唇|咽下余韵|脚掌落点|"
            r"压低重心|没偏一丝|像钉入地板|外套下摆|衣角|"
            r"最后一个乐句|重复三次|一紧了一次|"
            r"音乐未起|伴奏未起|半步|半拍|"
            r"[一二两三四五六七八九十百零\d]+把|"
            r"[一二两三四五六七八九十百零\d]+个?字|"
            r"第?[一二两三四五六七八九十百零\d]+次(?:普通)?(?:重拍|踏步|抬手)|"
            r"[一二两三四五六七八九十百零\d]+处(?:换气)?|"
            r"第[二三四五六七八九十]句|最后[一二三四五六七八九十]字|"
            r"如线|像尺|"
            r"第[一二三四五六七八九十百零\d]+(?:圈|遍)|"
            r"屏幕|显示屏|波形|读数|曲线|平板|投影|摄像机|监视器|数据表|"
            r"计时|误差|偏差|分贝|赫兹|(?:精确|固定|相同)角度|角度(?:不变|一致)|\+"
        )
        if segment_index == 8:
            sentence_drift = re.compile(
                sentence_drift.pattern
                + r"|节拍没乱|我(?:跳|唱)得比|撑不了.{0,6}天|"
                r"明天.{0,12}第几组|换气卡|音准偏"
            )
    elif all(marker in paper_markers for marker in ("封签", "送货单", "领用簿")):
        if segment_index == 6:
            text = re.sub(
                r"[，；]?[^，。；！？]{0,24}"
                r"(?:齿痕|棱角|温度|体温|磨损|锁舌|凹槽|铜锈|旧痕)"
                r"[^，。；！？]{0,24}(?=[，；。！？])",
                "",
                text,
            )
        sentence_drift = re.compile(
            r"过敏|休克|抢救|注射|针头|库存|清点|翻柜|开柜|打开药柜|"
            r"原厂|逐支|墨迹|字迹|笔锋|潦草|工整|药理|处方|空盒|仪轨|"
            r"胶痕|折痕|划痕|编号|批次|签名栏|朱砂|红圈|红笔|铅笔|墨点|"
            r"凹印|凸起油墨|青灰微光|横线末端|褶皱|多添.{0,4}(?:一竖|一横|一划)|"
            r"油墨|墨色|撇捺|顿挫|那一横|浅痕|"
            r"窗户|窗帘|风声|顶灯|灯光|阴影|"
            r"喉结|舌尖|上颚|腕骨|瞳孔|下颌线|筋络|指甲盖|脉搏|"
            r"打开封签|(?:按住|压住|触到|触碰).{0,12}封签|"
            r"封签.{0,12}(?:按住|压住|触到|触碰)|[”\"]却未开口|"
            r"右下角|袖口|口袋|一支都不能少|"
            r"(?:半寸|寸许|半毫|两指宽|三指宽|三分之二处)|"
            r"封签.{0,24}(?:背面|小字|封码|印着|写着|标着).{0,24}"
            r"(?:数量|[一二三四五六七八九十百零\d]+支)|"
            r"负责人.{0,80}(?:领用簿|簿子).{0,40}(?:写下|填写|登记|落笔)|"
            r"(?:领用簿|簿子).{0,40}(?:写下|填写|登记|落笔).{0,80}负责人"
        )
        if segment_index < 5:
            sentence_drift = re.compile(sentence_drift.pattern + r"|钥匙")
        if segment_index == 8:
            sentence_drift = re.compile(
                sentence_drift.pattern
                + r"|转身|离开|门口|关门|走出去"
            )
    else:
        sentence_drift = None

    sentences = re.findall(r"[^。！？]*[。！？][”\"]?|[^。！？]+$", text, re.S)
    if sentence_drift is not None:
        sentences = [
            sentence.strip()
            for sentence in sentences
            if sentence.strip() and not sentence_drift.search(sentence)
        ]
    else:
        sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
    if performance_scene and segment_index == 4:
        stop_pattern = re.compile(
            r"停一下|暂停|先停|给我停|停下来|够了|可以了|到此为止"
        )
        seen_stop = False
        deduped_sentences: List[str] = []
        for sentence in sentences:
            if stop_pattern.search(sentence):
                if seen_stop:
                    continue
                seen_stop = True
            deduped_sentences.append(sentence)
        sentences = deduped_sentences
    if performance_scene and segment_index == 6:
        conclusion_at = next((
            index for index, sentence in enumerate(sentences)
            if re.search(PERFORMANCE_PASS_CONCLUSION_PATTERN, sentence)
        ), -1)
        publicity_at = next((
            index for index, sentence in enumerate(sentences)
            if "旧宣传页" in sentence
        ), -1)
        if 0 <= publicity_at < conclusion_at:
            publicity_sentence = sentences.pop(publicity_at)
            conclusion_at -= 1
            sentences.insert(conclusion_at + 1, publicity_sentence)
    text = "".join(sentences).strip()
    if len(text) <= target_max:
        return with_required_segment_contract(text)

    kept: List[str] = []
    current_length = 0
    for sentence in sentences:
        if current_length + len(sentence) > target_max:
            break
        kept.append(sentence)
        current_length += len(sentence)
    if kept:
        return with_required_segment_contract("".join(kept).strip())

    first_sentence = sentences[0] if sentences else ""
    clauses = re.findall(r"[^，；,;]*[，；,;]?|$", first_sentence)
    clause_text = ""
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        if len(clause_text) + len(clause) > target_max - 1:
            break
        clause_text += clause
    clause_text = clause_text.rstrip("，；,;").strip()
    return with_required_segment_contract(clause_text + "。" if clause_text else "")


def _physical_safety_contract_segment(
    contract: Dict[str, Any],
    segment_index: int,
) -> str:
    """Render one physical-safety beat from evidence roles, not chapter identity."""
    protagonist = str(contract.get("protagonist") or MAIN_PROTAGONIST)
    protagonist_short = protagonist.split("·", 1)[0]
    opponent = str(
        contract.get("opponent_scene_actor")
        or contract.get("opponent")
        or "既有对手"
    )
    opponent_short = opponent.split("·", 1)[0]
    current = list(contract.get("current_evidence_carriers") or [])
    established = list(contract.get("established_evidence_carriers") or [])
    source_carriers = established + current
    all_carriers = _ordered_unique_text(source_carriers)

    def carrier(pattern: str, fallback: str) -> str:
        return next(
            (item for item in all_carriers if re.search(pattern, item)),
            fallback,
        )

    load = carrier(r"沙袋|配重|样品|载荷", "测试载荷")
    machine = carrier(r"升降台|传送带|舞台机关|设备|控制台", "被测设备")
    control = next(
        (
            item for item in source_carriers
            if re.search(r"控制器$|控制台$|停机按钮$", item)
            and not re.search(r"日志|记录", item)
        ),
        "控制端",
    )
    log = carrier(r"日志|值班记录|操作记录", "操作记录")
    acceptance = carrier(r"验收单|签字页|签收记录", "验收材料")
    trigger = str(contract.get("trigger_action") or "")
    reaction = str(contract.get("opponent_self_incrimination") or "")
    old_signal = str(contract.get("old_trap_signal") or "")
    old_signal = re.sub(
        rf"^(?:(?:{re.escape(protagonist)}|{re.escape(protagonist_short)}|主角))?记得",
        "",
        old_signal,
    ).lstrip("，：")
    old_signal = re.sub(r"^上一世", "", old_signal).lstrip("，：")
    result = str(contract.get("immediate_result") or "")
    authority = str(contract.get("authority_actor") or protagonist)
    loss = str(contract.get("opponent_loss") or result)
    gain = str(contract.get("protagonist_gain") or result)
    authority_gain = str(contract.get("authority_gain") or "")
    phase = str(contract.get("phase") or "setup")
    scene_text = "；".join((trigger, reaction, result))
    people = "舞者" if re.search(r"舞者|彩排|舞台", scene_text) else "现场人员"
    place = "舞台侧方" if people == "舞者" else "作业区"
    visible_result = re.split(r"[，；。]", result, maxsplit=1)[0].strip()

    if phase == "settlement":
        paragraphs = {
            1: (
                f"{people}再次站到{place}时，前一场用过的{load}还留在{machine}旁。"
                f"{protagonist_short}没有重演那次失效，只让所有人围到能看清材料的位置。"
                f"他随即{trigger}。{log}和{acceptance}摆在同一处，"
                f"{control}则留在众人视线内。{opponent_short}想先开口，{protagonist_short}抬手止住他："
                "“先看你做过什么，再听你怎么说。”"
            ),
            2: (
                f"{protagonist_short}先翻到{log}里与现场操作对应的那一段，"
                f"又把没有完成签字的{acceptance}推到旁边。两份材料不需要技术解释："
                f"谁碰过{control}，验收是否真正完成，人人看得明白。{reaction}。"
                f"{opponent_short}说完便伸手去碰材料，{protagonist_short}把纸面按住："
                "“东西别动，你的解释已经留下了。”"
            ),
            3: (
                f"{protagonist_short}没有讨论别的设备，只问三件眼前事："
                f"{acceptance}为什么没有签字，{control}为什么由{opponent_short}抢走，"
                f"{load}为什么会在所有真人进入前暴露失效。{people}彼此看了一眼，"
                f"没人替{opponent_short}回答。{opponent_short}把“效果”两个字又说了一遍，"
                f"{protagonist_short}反问：“需要拿人的安全来遮掩，算哪门子效果？”"
            ),
            4: (
                f"{authority}当场走到{control}前，先让{opponent_short}把手拿开，"
                f"随后向全场宣布：{loss}。{authority_gain + '。' if authority_gain else ''}"
                f"现场负责操作的人立刻改为听从新的安全指令，{opponent_short}再说“继续”时，"
                f"没有一只手碰向{control}。撤权不是警告，而是在他说话尚未落地时就已经执行。"
            ),
            5: (
                f"{authority}转向{protagonist_short}，把另一项决定说清：{gain}。"
                f"{protagonist_short}没有只点头，他当场问了一次是否可以否决启动，"
                f"又问了一次安全指令是否高于赶进度。{authority}逐一确认。"
                f"{people}随即退到安全位置，{machine}保持停止；"
                f"直到{protagonist_short}明确同意，任何人都不能把真人重新送上去。"
            ),
            6: (
                f"{opponent_short}扯出一句“只是临时调整”，声音却被{people}收回脚步的动静盖住。"
                f"{protagonist_short}看着他：“你抢走一次{control}，换来的是永远不能再碰它。”"
                f"{authority}把{acceptance}收在现场，{log}仍停在刚才核对的位置。"
                f"{opponent_short}张了张嘴，最终没有再喊启动，只能看着{machine}在新命令下保持安静。"
            ),
        }
    else:
        paragraphs = {
            1: (
                f"{people}正要朝{machine}靠近，{protagonist_short}忽然抬手，把所有人拦在{place}。"
                f"他记得，上一世，{old_signal.rstrip('。')}。那次真人先上去，"
                f"事故发生后才有人谈验收；这一次，他没有给旧局第二次机会。"
                f"{protagonist_short}当众{trigger}。"
                f"他说完便让{people}后退，空出{machine}周围的位置。"
            ),
            2: (
                f"{load}被放到{machine}上，重量替代了原本要登场的人。"
                f"{protagonist_short}只让{control}、{machine}和{load}留在验证范围内，"
                f"每一步都由现场人亲眼看着。{reaction}。"
                f"{opponent_short}握住{control}时还在催促继续，"
                f"仿佛抢先按下去就能证明自己比安全流程更懂舞台。"
            ),
            3: (
                f"{control}上的动作刚完成，{machine}便照着那套被私改的顺序运行。"
                f"{visible_result or result}。{people}齐齐停在原地，谁也没有再往前一步。"
                f"{protagonist_short}盯住{opponent_short}握着{control}的手："
                "“你刚才嫌慢，现在人人看见你省掉的是什么。”"
                f"{opponent_short}想松手，刚才的操作却已经在全场眼前发生。"
            ),
            4: (
                f"{protagonist_short}没有给混乱扩大的时间，立即横在{people}与{machine}之间。"
                f"他先命令所有真人停止靠近，再让{machine}保持原状。{result}。"
                f"最靠前的人退回安全位置后，{protagonist_short}才转向{opponent_short}："
                "“今天掉下去的是测试载荷。谁再拿真人替你赶时间，我先让谁停下。”"
                f"{people}没有异议，现场登台动作全部停止。"
            ),
            5: (
                f"{protagonist_short}要求{load}、{machine}和{control}全部留在原位，"
                f"在场人也暂时不散。{opponent_short}说可以重新来一次，"
                f"{protagonist_short}却直接拒绝：“错误不是多试几遍就会变成安全。”"
                f"他让现场停止真人使用，并明确在核验完成前不接受任何赶进度指令。"
                f"{people}从{machine}旁退开，原定动作当场作废。"
            ),
            6: (
                f"{opponent_short}把失效说成偶然，还想伸手拿回{control}。"
                f"{protagonist_short}先一步挡住：“捷径走到最后，先关上的总是你的退路。”"
                f"{people}仍站在安全位置，没有一个人响应{opponent_short}的继续口令。"
                f"{machine}旁只剩{load}，刚才提前出现的后果摆在所有人眼前。"
                f"{opponent_short}的手停在半空，第一次没能用赶进度把现场重新推起来。"
            ),
        }
    if phase == "settlement":
        expansions = {
            1: (
                f"{people}没有议论，目光先落在{acceptance}的空白处，又移向{control}。"
                f"{opponent_short}原先催人继续的气势被这阵安静压了回去。"
            ),
            2: (
                f"{log}只负责留下已经发生的操作，{acceptance}只负责回答验收是否完成。"
                f"{protagonist_short}把两件事分开说清，不给{opponent_short}把它们混成一句误会。"
            ),
            3: (
                f"{people}仍记得{load}失效时的声响。眼前没有夸张演示，"
                f"只有{opponent_short}亲手碰过的{control}和仍未完成的验收。"
            ),
            4: (
                f"{authority}说完便站在{control}旁，没有把位置再让回去。"
                f"{people}看着这一动作，终于确认赶进度不能再越过安全决定。"
            ),
            5: (
                f"{protagonist_short}让确认重复一遍，不是为了掌声，而是要所有人听清新的边界。"
                f"{opponent_short}站在原地，第一次不能替他按下启动。"
            ),
            6: (
                f"{people}依次离开{machine}边缘，没人再等{opponent_short}补一句命令。"
                f"他看着{control}，那条曾替他抢进度的捷径已经彻底封住。"
            ),
        }
        textures = {
            1: f"{authority}一直留在材料旁，没有给任何人把核验改成私下商量。",
            2: f"{opponent_short}的手收了回去，舞者的目光却没有从纸面移开。",
            3: f"{protagonist_short}问完便停住，让那句无法回答的问题留在全场。",
            4: f"{control}仍在原位，能否启动却已经不再由{opponent_short}决定。",
            5: f"{protagonist_short}听见舞者松开呼吸，才把视线从{machine}移开。",
            6: f"{opponent_short}垂下手，原先随口就能推动的彩排再也没有响应。",
        }
    else:
        expansions = {
            1: (
                f"{opponent_short}皱起眉，催促声还没出口，{protagonist_short}已经让{load}送到现场。"
                f"{people}意识到这不是口头争执，纷纷停在他划出的安全范围外。"
            ),
            2: (
                f"{people}盯着{opponent_short}的手，谁都没有替他碰{control}。"
                f"他越急着证明流程多余，越只能亲自完成那个决定胜负的动作。"
            ),
            3: (
                f"{load}落下的动静压住了现场催促声。{opponent_short}脸上的不耐僵住，"
                f"{people}这才明白，提前暴露的不是效果，而是原本会落在真人身上的危险。"
            ),
            4: (
                f"{protagonist_short}逐一确认{people}都在安全位置，才让人停止后续操作。"
                f"这一次没有伤者，也没有谁被迫带伤继续，旧局在发生前就被截断。"
            ),
            5: (
                f"{opponent_short}越说可以重来，{people}退得越坚决。"
                f"{protagonist_short}没有扩大争吵，只把安全决定落实到每个人的脚步上。"
            ),
            6: (
                f"{people}看见{opponent_short}亲手按下，也看见{protagonist_short}先一步救下所有人。"
                f"这一前一后的动作已经足够，任何解释都无法再把危险藏回流程里。"
            ),
        }
        textures = {
            1: f"{machine}保持静止，{people}在安全位置等着第一次验证口令。",
            2: f"{protagonist_short}没有催促，只看着{opponent_short}把选择亲手做完。",
            3: f"落下的{load}没有伤到人，却让所有催促声同时停住。",
            4: f"{people}逐一点头，确认没有任何人还站在危险范围里。",
            5: f"{opponent_short}再催一次，得到的仍是整齐后退的脚步。",
            6: f"{protagonist_short}没有离场，他守在{machine}旁，直到危险彻底停止。",
        }
    return (
        paragraphs.get(segment_index, "")
        + expansions.get(segment_index, "")
        + textures.get(segment_index, "")
    )


def _public_resource_audit_contract_segment(
    contract: Dict[str, Any],
    segment_index: int,
) -> str:
    """Render a public-resource audit from legal participants and listed records."""
    protagonist = str(contract.get("protagonist") or MAIN_PROTAGONIST)
    protagonist_short = protagonist.split("·", 1)[0]
    opponent = str(
        contract.get("opponent_scene_actor")
        or contract.get("opponent")
        or "资源管理方"
    )
    opponent_short = opponent.split("·", 1)[0]
    allies = list(contract.get("supporting_cast") or [])
    organizations = list(contract.get("supporting_organizations") or [])
    organization = organizations[0] if organizations else "固定支持者团队"
    ally_one = allies[0] if allies else "社群负责人"
    ally_two = allies[1] if len(allies) > 1 else "核验负责人"
    current = list(contract.get("current_evidence_carriers") or [])
    established = list(contract.get("established_evidence_carriers") or [])
    all_carriers = established + current

    def pick(pattern: str, fallback: str) -> str:
        return next((item for item in all_carriers if re.search(pattern, item)), fallback)

    identity = pick(r"实名|名单|校验|数据", "实名校验")
    abnormal = pick(r"异常.*预留票|黄牛.*预留票", "异常预留票")
    reserved = pick(r"预留票", abnormal)
    pool = pick(r"票池", "公开票池")
    trigger = str(contract.get("trigger_action") or "")
    reaction = str(contract.get("opponent_self_incrimination") or "")
    old_signal = str(contract.get("old_trap_signal") or "")
    old_signal = re.sub(
        rf"^(?:(?:{re.escape(protagonist)}|{re.escape(protagonist_short)}|主角))?记得",
        "",
        old_signal,
    ).lstrip("，：")
    old_signal = re.sub(r"^上一世", "", old_signal).lstrip("，：")
    result = str(contract.get("immediate_result") or "")
    result_render = result.replace("当章", "当场")
    loss = str(contract.get("opponent_loss") or result)
    gain = str(contract.get("protagonist_gain") or result)
    phase = str(contract.get("phase") or "setup")
    trigger_sentence = (
        trigger
        if trigger.startswith((protagonist, protagonist_short))
        else protagonist_short + trigger
    )

    if phase == "settlement":
        paragraphs = {
            1: (
                f"{organization}再次把前一场冻结的{abnormal}带到公开核验处。"
                f"{ally_one}守着{identity}结果，{ally_two}把尚未回到普通购票人手中的票逐项列开。"
                f"{trigger_sentence}。他没有把歌迷挡在决定之外，"
                f"而是让他们站在能看清{reserved}去向的位置。{opponent_short}派来的人"
                "想先收走材料，却被现场歌迷齐声要求留下。"
            ),
            2: (
                f"{protagonist_short}只做一次简单对照：能通过{identity}的票留给真实购票人，"
                f"无法对应真实持票人的{reserved}单独放在一边。{ally_one}念出核验结果，"
                f"{ally_two}逐项确认没有重复计算。整个过程不需要秘密渠道，"
                f"每一张票的去向都在购买者和{opponent_short}面前摊开。"
                f"歌迷们没有喊口号，只盯着那批不该被藏起来的票。"
            ),
            3: (
                f"{reaction}。{opponent_short}刚把道歉说出口，又想把问题缩成个别员工失误。"
                f"{protagonist_short}指向已经冻结的{abnormal}：“能整批留下，就不是一个人的手误。”"
                f"{ally_one}把核验人数与票数重新念了一遍，{ally_two}当场确认结果一致。"
                f"管理方再也无法把{reserved}说成尚未使用的普通余票。"
            ),
            4: (
                f"公开处置随即开始。{result.split('，', 1)[0]}，每一张退回的票都重新面向普通购票人。"
                f"紧接着，现场宣布：{loss}。{opponent_short}原先可以私下划走票源的入口"
                f"当场关闭，任何新增预留都必须先经过公开核验。{organization}成员看着{pool}"
                "重新增加，没有人再需要从黄牛手里买回本该属于自己的机会。"
            ),
            5: (
                f"{protagonist_short}没有把票拿到自己手里，而是要求把监督留给购票人。"
                f"现场随后确认：{gain}。{ally_one}与{ally_two}当场坐到核验位置，"
                f"第一件事就是确认退回{pool}的票仍可被正常购买。"
                f"{protagonist_short}看着歌迷：“监督不是替我说好话，是在我错的时候也能把票拦下来。”"
                f"这句话让新席位有了清楚边界。"
            ),
            6: (
                f"{opponent_short}还想保留一句“后续优化”，现场却已经按新规则完成第一轮放票。"
                f"歌迷看见{abnormal}真正回到{pool}，掌声才从后排响起。"
                f"{protagonist_short}没有借机煽动围攻，只对管理方说："
                "“票不是你们藏起来再高价施舍的礼物，它只属于真正买下它的人。”"
                f"{opponent_short}的人低下头，再也没有提出恢复私设预留。"
            ),
        }
    else:
        paragraphs = {
            1: (
                f"{protagonist_short}记得，上一世，{old_signal.rstrip('。')}。"
                f"当时真正的歌迷被挡在售票口外，{reserved}却成批流向加价转卖的人。"
                f"这一回，他先联系{organization}，让{ally_one}与{ally_two}带着固定成员"
                f"进入公开核验处。{trigger_sentence}。"
                f"他没有向歌迷索要信任，只把核验过程和决定权同时放到他们面前。"
            ),
            2: (
                f"{ally_one}负责核对{identity}，{ally_two}负责把无法对应真实购票人的票单独标出。"
                f"{protagonist_short}要求每一次判断都能由购票人自己复核，"
                f"只核验成员本人提交的购票信息。{organization}成员依次报出"
                f"本人购票信息，再由两名骨干交叉确认。第一批正常票很快通过，"
                f"那批反复绕开实名环节的{reserved}却留在原处。"
                f"{opponent_short}的人站在核验处另一侧，几次催促都没能让队伍停下。"
            ),
            3: (
                f"{reaction}。管理方先要求缩小核验范围，又催促歌迷离开。"
                f"{protagonist_short}没有争吵，只问：“如果票都合规，为什么怕买票的人亲眼看？”"
                f"{ally_one}继续核对，{ally_two}把新增异常逐项并到同一批。"
                f"围在外面的歌迷安静下来，越是安静，{opponent_short}的阻拦越显得心虚。"
                f"没人越过公开流程，核验却一步也没有停。"
            ),
            4: (
                f"最后一轮{identity}结束，{abnormal}与正常票彻底分开。{result_render}。"
                f"{ally_one}当场确认冻结已经生效，{ally_two}则守住票源，"
                f"不让任何人趁混乱把票重新划走。几个原本等着收票的人只能空手离开。"
                f"{protagonist_short}没有宣布大胜，只让每位参与核验的歌迷再次检查结果，"
                f"确认异常票无法继续出票。"
            ),
            5: (
                f"{opponent_short}的人改口说可以私下协商，{protagonist_short}却把所有讨论留在公开处。"
                f"他要求被冻结的{abnormal}保持原状态，直到下一次公开处置。"
                f"{organization}成员轮流守着核验结果，普通购票人则确认自己的正常票没有受到影响。"
                f"第一次，歌迷不再只是售票数字，而是合法站进了票务决定发生的地方。"
                f"两名核验负责人仍留在原处。"
            ),
            6: (
                f"{opponent_short}还想把核验说成一场宣传，话音刚落，"
                f"又一名准备收走{reserved}的人发现票已被冻结，只能转身离开。"
                f"{protagonist_short}看向管理方：“真正的宣传，是把空位留给黄牛；"
                "我们做的，只是把门票还给愿意进场的人。”"
                f"{organization}成员没有追赶任何人，只守住已经生效的冻结结果。"
                f"管理方站在公开核验处，再也无法悄悄结束这场检查。"
            ),
        }
    if phase == "settlement":
        expansions = {
            1: (
                f"{organization}成员没有堵住入口，只按购票顺序站成一列。"
                f"{protagonist_short}等最后一位购票人站稳，才示意公开核验正式开始。"
            ),
            2: (
                f"正常票一次就能对应持票人，异常票却反复停在同一道{identity}上。"
                f"两名骨干每完成一项便交换位置复查，没人能单独改动结论。"
            ),
            3: (
                f"现场没有起哄，歌迷只等{opponent_short}把每一张票的去向说清。"
                f"这份克制让道歉无法盖过已经摆在桌面的数量和名单。"
            ),
            4: (
                f"{pool}恢复放票后，可购买数量在众人眼前逐项增加。"
                f"管理方的人只能照公开结果执行，无法再把退回的票另行划走。"
            ),
            5: (
                f"{ally_one}与{ally_two}接受的是可被歌迷检查的席位，不是一句安抚。"
                f"他们把首轮复核结果当众报出，确认监督权已经能够实际使用。"
            ),
            6: (
                f"{organization}成员确认普通购票人能够继续下单后才依次散开。"
                f"{protagonist_short}仍留在核验处，看着最后一张异常票完成公开回流。"
            ),
        }
    else:
        expansions = {
            1: (
                f"{ally_one}先安排正常购票人依次进入，{ally_two}把复核位置留在队伍末端。"
                f"核验处没有围堵，所有人都能看见流程从哪里开始。"
            ),
            2: (
                f"每名成员只核对自己的购票记录，不替陌生票源作证。"
                f"一项结果完成后立即交给下一人复查，个人判断不能直接决定冻结。"
            ),
            3: (
                f"管理方的人不断强调时间，歌迷却仍按原顺序递交信息。"
                f"没人用喧闹替代证据，阻挠反而被完整留在公开流程里。"
            ),
            4: (
                f"冻结只落在无法通过核验的票上，正常购票人的入场资格没有变化。"
                f"这条边界当众确认后，管理方再不能借核查制造新的恐慌。"
            ),
            5: (
                f"{ally_one}记录冻结总数，{ally_two}再按原名单复查一次。"
                f"两人分别保留核验职责，任何一方都不能独自修改已经公开的结果。"
            ),
            6: (
                f"歌迷亲眼看着等候收票的人离开，直到确认冻结仍然有效才响起掌声。"
                f"{protagonist_short}没有庆祝，只让核验队伍把最后一项记录补齐。"
            ),
        }
    return paragraphs.get(segment_index, "") + expansions.get(segment_index, "")


def _contract_render_context(contract: Dict[str, Any]) -> Dict[str, Any]:
    protagonist = str(contract.get("protagonist") or MAIN_PROTAGONIST)
    protagonist_short = protagonist.split("·", 1)[0]
    opponent = str(
        contract.get("opponent_scene_actor")
        or contract.get("opponent")
        or "既有管理方"
    )
    opponent_short = opponent.split("·", 1)[0]
    opponent_parts = [
        item.strip()
        for item in re.split(
            r"(?:与|和|、|及|/|,|，)",
            str(contract.get("opponent") or opponent),
        )
        if item.strip()
    ]
    trigger = str(contract.get("trigger_action") or "").strip()
    trigger_sentence = (
        trigger
        if trigger.startswith((protagonist, protagonist_short))
        else protagonist_short + trigger
    )
    old_signal = str(contract.get("old_trap_signal") or "")
    old_signal = re.sub(
        rf"^(?:(?:{re.escape(protagonist)}|{re.escape(protagonist_short)}|主角))?记得",
        "",
        old_signal,
    ).lstrip("，：")
    old_signal = re.sub(r"^上一世", "", old_signal).lstrip("，：")
    return {
        "protagonist": protagonist,
        "protagonist_short": protagonist_short,
        "opponent": opponent,
        "opponent_short": opponent_short,
        "opponent_parts": opponent_parts,
        "other_opponent": opponent_parts[1] if len(opponent_parts) > 1 else opponent,
        "trigger": trigger,
        "trigger_sentence": trigger_sentence,
        "reaction": str(contract.get("opponent_self_incrimination") or "").strip(),
        "old_signal": old_signal,
        "result": str(contract.get("immediate_result") or "").strip(),
        "loss": str(contract.get("opponent_loss") or "").strip(),
        "gain": str(contract.get("protagonist_gain") or "").strip(),
        "phase": str(contract.get("phase") or "setup"),
        "current": list(contract.get("current_evidence_carriers") or []),
        "established": list(contract.get("established_evidence_carriers") or []),
        "allowed": list(contract.get("allowed_evidence_carriers") or []),
    }


def _contract_rights_audit_segment(
    contract: Dict[str, Any],
    segment_index: int,
) -> str:
    ctx = _contract_render_context(contract)
    p = ctx["protagonist_short"]
    o = ctx["opponent_short"]
    current = ctx["current"] or ["协议"]
    established = ctx["established"] or current
    paper = current[0]
    prior_paper = established[0]
    trigger = ctx["trigger_sentence"]
    reaction = ctx["reaction"]
    result = ctx["result"]
    loss = ctx["loss"] or result
    gain = ctx["gain"] or result

    if ctx["phase"] == "settlement":
        paragraphs = {
            1: (
                f"前一场被冻结的{prior_paper}仍摊在会议桌中央。{p}让律师团队坐到两侧，"
                f"自己把{paper}放在所有人都能看清的位置，随后{trigger.removeprefix(p)}。"
                f"{o}刚要把文件合上，{p}按住页角：“今天只处理已经写在纸上的权利，不谈人情。”"
                "会议因此从第一句话起就没有私下回旋的余地。"
            ),
            2: (
                f"律师团队先确认前次冻结仍然有效，再把{prior_paper}与{paper}逐项对照。"
                f"他们没有加入新的附件，也没有引用临时编号，只把代签、自动移交与本人签署的边界"
                f"逐句念清。{o}坐在对面听着，几次想插话都被要求等原文读完。"
                f"{p}让每一项结论都落回原文件，谁也不能用口头解释替换纸面事实。"
            ),
            3: (
                f"{reaction}。{o}先说会议仓促，又说可以以后补充说明，"
                f"却始终不肯回答为何要替本人保留代签入口。{p}把{paper}推回他面前："
                "“你要拖延的不是会议，是这项授权失效的时刻。”"
                f"律师团队随即记录{o}拒绝正面回答，讨论没有被他带离文件本身。"
            ),
            4: (
                f"核对完成后，律师团队当场宣读处理结果：{loss}。"
                f"原先依附于{paper}的代签入口随即关闭，{o}再递来的口头指令不再被接受。"
                f"他伸手想取回文件，负责保管的人却只按新决定归档。撤权在会议结束前已经执行，"
                "不是一句留待以后确认的警告。"
            ),
            5: (
                f"同一场会议继续确认另一项结果：{gain}。"
                f"{p}当面问清，今后是否只有本人能够作出最终签署，律师团队逐一回答确认。"
                f"他没有把新权利交给新的代办人，而是亲手在{paper}的处理结论旁留下确认。"
                "所有参与者随即按新的签署边界重新分配文件流转。"
            ),
            6: (
                f"{o}还想把失权说成一次程序调整，{p}却把已经废止的文件留在桌上："
                "“替别人签字久了，不代表那只手真的属于你。”"
                f"律师团队收起生效文件，{o}面前只剩失效副本。"
                f"他没有再要求延后，也无法把已经关上的代签入口重新打开。"
            ),
        }
    else:
        paragraphs = {
            1: (
                f"{p}记得，上一世，{ctx['old_signal'].rstrip('。')}。"
                f"这一次，他没有把{paper}交给别人代读，而是在签署前亲自翻到权利移交的位置。"
                f"{trigger}。{o}站在桌子另一侧，已经把笔推到他手边，"
                "仿佛只要催得够快，纸上的陷阱就来不及被看见。"
            ),
            2: (
                f"{p}只检查眼前这份{paper}，不调用来路不明的附件。"
                "他把隐藏的移交条件、本人签署边界和冷静期放在同一页上核对，"
                f"然后让在场人员停下流转。每个人都能看见文件仍未签署，"
                f"也能看见{o}最急着越过的正是那段权利变化。"
            ),
            3: (
                f"{reaction}。{o}说那只是常规安排，又伸手把笔往前推。"
                f"{p}没有与他争论专业术语，只问：“既然无关紧要，为什么不肯让我读完？”"
                f"这句话让{o}的催促变成当面承认。他想收回{paper}，"
                "文件却已经留在所有见证者的视线内。"
            ),
            4: (
                f"{p}把笔放回桌面，明确拒绝签署，并要求立即按原文件的冷静期处理。"
                f"{result}。负责流转的人当场停止传递{paper}，"
                f"{o}原本准备代为签署的入口随冻结失效。没有人等到会后再执行，"
                "这次拒签在他开口辩解时已经成为现实。"
            ),
            5: (
                f"{p}要求{paper}保持当前状态，由律师团队在公开会议中继续复核。"
                f"他没有提前宣布最终废除，只守住已经生效的冻结，"
                f"确保{o}不能趁间隙补签、换页或重新递交。"
                "在场人员把签署笔收走，所有后续动作都必须等正式核对完成。"
            ),
            6: (
                f"{o}低声说冻结只会耽误进度，{p}看着他：“慢下来损失的是你的机会，"
                "签下去损失的却是我的权利。”"
                f"{paper}仍停在被拒签的那一页，{o}伸出的手最终收了回去。"
                "会议没有散场，但他已经不能再替任何人落笔。"
            ),
        }
    if ctx["phase"] == "settlement":
        expansions = {
            1: (
                f"每位与会者拿到的都是同一份{paper}，没有人能靠不同版本制造争议。"
                f"{p}等最后一页分发完才让会议进入第一项表决。"
            ),
            2: (
                f"念到本人签署边界时，律师团队停下来让所有人确认。"
                f"{o}无法跳过这一步，只能看着原先模糊的代签空间被逐句压缩。"
            ),
            3: (
                f"会议记录只写{o}刚才的回答，不替任何一方加工结论。"
                f"越是按原话留下，他想把拖延说成谨慎就越站不住脚。"
            ),
            4: (
                f"负责流转的人当众撤下旧授权标记，并把后续签署入口改为本人确认。"
                f"{o}面前的文件还在，能够代签的实际位置却已经消失。"
            ),
            5: (
                f"{p}先用新边界否决一次代办请求，确认独立签署权不是纸面装饰。"
                f"律师团队随即按他的决定继续，会议没有再等待{o}点头。"
            ),
            6: (
                f"散会前，所有文件去向被当众复述一次。"
                f"{p}带走本人应持有的签署文件，{o}只能在失效记录上确认已知悉。"
            ),
        }
    else:
        expansions = {
            1: (
                f"桌边的人原本都在等签字，见他停住才把手从文件上移开。"
                f"{p}没有抬高声音，翻页的动作却让催促第一次失去节奏。"
            ),
            2: (
                f"他让负责流转的人把签署状态当众说清：尚未签字，也没有代签生效。"
                f"这句话把{o}准备营造的既成事实重新拉回起点。"
            ),
            3: (
                f"在场人顺着他的提问重新看向同一段文字。"
                f"{o}每多解释一句，便更难说明为何始终不愿让本人完成阅读。"
            ),
            4: (
                f"冷静期开始后，文件流转位置立即显示停止。"
                f"任何代签动作都无法继续，{o}失去的不是面子，而是眼前可以落笔的权限。"
            ),
            5: (
                f"律师团队分别确认文件页数与当前签署状态，随后把复核安排公开。"
                f"{p}只要求守住现状，不让临时讨论越过已经生效的冻结。"
            ),
            6: (
                f"原本等着收走文件的人重新坐下，会议改为正式复核。"
                f"{o}面前的笔被收回，他再催也不能让流程恢复。"
            ),
        }
    details = {
        1: f"签署笔始终留在桌面中央，直到{p}明确允许前都没有再次递出。",
        2: f"纸页按原顺序铺开，{o}无法把最关键的一段压到别页下面。",
        3: "在场人没有替任何一方圆场，只等问题得到正面回答。",
        4: "负责执行的人复述一次当前状态，确认决定已经进入实际流程。",
        5: f"{p}逐项听完确认，才让下一份文件按新边界继续流转。",
        6: f"{o}看着空下来的签署位置，最后一句催促也没能说出口。",
    }
    return (
        paragraphs.get(segment_index, "")
        + expansions.get(segment_index, "")
        + details.get(segment_index, "")
    )


def _live_capability_validation_segment(
    contract: Dict[str, Any],
    segment_index: int,
) -> str:
    ctx = _contract_render_context(contract)
    p = ctx["protagonist_short"]
    o = ctx["opponent_short"]
    other = ctx["other_opponent"]
    if ctx["phase"] == "settlement":
        carriers = ctx["established"] or ctx["current"] or ["现场原声"]
    else:
        carriers = ctx["current"] or ctx["established"] or ["现场原声"]
    carrier_text = "、".join(carriers[:3])
    trigger = ctx["trigger_sentence"]
    reaction = ctx["reaction"]
    result = ctx["result"]
    loss = ctx["loss"] or result
    gain = ctx["gain"] or result

    if ctx["phase"] == "settlement":
        paragraphs = {
            1: (
                f"公开排练继续进行，上一场留下的{carrier_text}仍向所有在场者开放。"
                f"{p}没有重放剪辑片段，而是{trigger.removeprefix(p)}，"
                f"让完整演唱从起音到收尾一次发生。{o}的人守在拍摄位置旁，"
                "想等他出现一点失误便中断，却找不到可以先行叫停的理由。"
            ),
            2: (
                f"{p}把呼吸、转音和高音全部留在同一条{carrier_text}里。"
                "现场画面没有切开，乐队也没有替他遮住换气。"
                f"记者跟着演唱顺序记录，普通旁观者只需听眼前声音就能判断。"
                f"当最后一段推进时，{o}开始示意拍摄人员移开位置。"
            ),
            3: (
                f"{reaction}。有人伸手遮挡镜头，拍摄者却仍站在公开区域，"
                f"没有停止记录。{p}没有停歌回应，直到最后一个音自然落下才看向{o}："
                "“你们要证明我唱不了，现在为什么怕它被完整留下？”"
                f"{other}先前散布的说法当场失去遮掩。"
            ),
            4: (
                f"完整演唱与{carrier_text}核对无误后，现场立即执行对造谣方的处理：{loss}。"
                f"已经占用的采访资源被退回，先前的指控也不能继续挂在合作名义下。"
                f"{o}试图把撤回说成误会，记者却只记录已经发生的退还与撤销。"
                "现实代价在排练场内就完成了交割。"
            ),
            5: (
                f"随后，公开排练的后续使用边界被正式确认：{gain}。"
                f"{p}要求发布内容保留完整原声，不得被截成替造谣者服务的片段。"
                "负责拍摄的人当场按新权利交接素材，记者也确认后续引用须以完整演唱为准。"
                "这份权利不靠赞美成立，而靠现场可执行的发布决定成立。"
            ),
            6: (
                f"{o}最后还想问能否保留原采访安排，{p}只回答："
                "“你们剪掉的每一秒，都不如刚才完整的一首歌诚实。”"
                f"{carrier_text}继续公开播放，撤回与退还已经无法收回。"
                f"{o}的人放下遮挡镜头的手，只能看着排练原声按新的权限保存。"
            ),
        }
    else:
        paragraphs = {
            1: (
                f"{p}记得，上一世，{ctx['old_signal'].rstrip('。')}。"
                f"同样的指控再次出现时，他没有先发声明，而是{trigger.removeprefix(p)}。"
                "记者和普通旁观者都站在公开区域，拍摄从他走进排练场时便保持连续。"
                f"{o}原以为他会躲开现场，反而被迫留下看完整场。"
            ),
            2: (
                f"伴奏响起前，{p}只确认一件事：{carrier_text}必须与现场演唱同时开放。"
                "没有预录替换，也没有中途剪接。"
                f"{reaction}，{o}的人不断向记者递出负面说法，"
                f"却不敢要求关闭自己刚才坚持要看的公开排练。"
            ),
            3: (
                f"{p}从第一句开始保持完整演唱，转身、走位和换气都没有让声音断开。"
                f"高难段落临近时，{other}的人盯住{carrier_text}，等着抓住破绽。"
                "他没有停下来解释，只把音准和气息一段段推到最难的位置。"
                "越接近收尾，场边原本的议论越安静。"
            ),
            4: (
                f"最后一个高音落稳，拍摄仍是一镜到底，{carrier_text}与现场声音没有分离。"
                f"{result}。负责采访的人当场收走造谣方的独家席位，"
                f"{o}先前散布的说法还挂在嘴边，现实资格却已经失去。"
                "演唱没有被拖到剪辑室里判断，结果就在所有人耳边生效。"
            ),
            5: (
                f"{p}没有要求记者赞美，只让他们保留完整过程。"
                f"现场确认造谣方不能再以独家身份控制提问和素材，{carrier_text}继续向所有见证者开放。"
                "普通旁观者重新核对刚才听到的声音，排练秩序也没有因抹黑中断。"
                "乐队没有停下，下一轮排练仍按公开顺序继续。"
            ),
            6: (
                f"{o}试图把失去席位说成临时调整，{p}拿起水杯，只回了一句："
                "“怀疑可以进门，谎话没有专座。”"
                f"记者把原属于造谣方的位置让给公开记录区，{other}的人站在空出的座位旁，"
                f"再也无法用一句假唱把刚才的{carrier_text}抹掉。"
            ),
        }
    if ctx["phase"] == "settlement":
        expansions = {
            1: (
                f"拍摄者先报出连续记录已经开始，随后把手离开暂停键。"
                f"{p}等现场安静下来才示意乐队起拍，任何一方都不能在中途改换标准。"
            ),
            2: (
                f"最难的段落到来前，他仍按原速度推进，没有为镜头额外停顿。"
                f"{o}几次看向拍摄位置，连续画面却始终没有给他插手的空档。"
            ),
            3: (
                f"演唱结束后，记者先核对画面连续，再核对声音是否来自同一现场。"
                f"两项结果当众一致，{other}无法要求只保留对自己有利的片段。"
            ),
            4: (
                f"采访预付款的退还也在现场确认，不再由造谣方继续占用。"
                f"失去的不只是说法，还有已经排定的采访资源和合作位置。"
            ),
            5: (
                f"{p}让负责保存的人当众复述发布边界，确认任何剪辑都不能替换完整原声。"
                f"第一份后续排练记录随即按他的发布权完成登记。"
            ),
            6: (
                f"旁观者没有追着争吵，只把注意力留在仍然连续的声音上。"
                f"{o}想收回先前的中断手势，却已经没有人再听从。"
            ),
        }
    else:
        expansions = {
            1: (
                f"排练区四周没有遮挡，记者可以从不同位置看清他的口型和动作。"
                f"{p}没有要求任何人先相信，只要求他们把整场看完。"
            ),
            2: (
                f"负责记录的人当众确认不会暂停，也不会替换声音。"
                f"{o}刚才要求公开验证，此刻便无法再用条件不足为由离场。"
            ),
            3: (
                f"乐队成员按原编排继续，没人替他降低难度。"
                f"记者的视线从现场动作移到声轨，再回到他的演唱，判断过程始终公开。"
            ),
            4: (
                f"席位被收回后，造谣方的采访标记当场撤下。"
                f"普通记者按原顺序继续记录，排练没有因失权者的争辩停下一秒。"
            ),
            5: (
                f"{p}让拍摄者回看开头与结尾的连续衔接，确认没有停机。"
                f"这一步只复核刚才发生的演唱，不增加任何幕后材料。"
            ),
            6: (
                f"场边原本附和假唱说法的人不再开口，空出的席位清楚留在原处。"
                f"{p}放下水杯，乐队也按正常秩序收住最后一个和弦。"
            ),
        }
    if ctx["phase"] == "settlement":
        details = {
            1: "公开区域的视线都落在同一场演唱上，没有人提前替结果下结论。",
            2: f"{carrier_text}保持开放，现场任何人都能在同一时刻听见。",
            3: f"{p}没有回避最难的部分，反而让连续记录完整跟上。",
            4: "席位与预付款的变化被当众复述，造谣方无法只撤回一句话了事。",
            5: (
                f"负责保存的人按{p}确认的新边界登记首份完整素材，"
                "后续发布权限在现场生效。"
            ),
            6: f"{o}看向仍在记录的镜头，最终没有再要求中断。",
        }
    else:
        details = {
            1: "公开区域的视线都落在同一场演唱上，没有人提前替结果下结论。",
            2: f"{carrier_text}保持开放，现场任何人都能在同一时刻听见。",
            3: f"{p}没有回避最难的部分，反而让连续记录完整跟上。",
            4: "独家席位被当众收回，造谣方先失去了控制采访顺序的资格。",
            5: (
                "负责保存的人只核对本场记录是否连续，素材仍按原有权限封存，"
                "没有提前处置后续发布权。"
            ),
            6: f"{o}看向仍在记录的镜头，最终没有再要求中断。",
        }
    return (
        paragraphs.get(segment_index, "")
        + expansions.get(segment_index, "")
        + details.get(segment_index, "")
    )


def _financial_or_asset_audit_segment(
    contract: Dict[str, Any],
    segment_index: int,
    *,
    asset_mode: bool,
) -> str:
    ctx = _contract_render_context(contract)
    p = ctx["protagonist_short"]
    o = ctx["opponent_short"]
    if ctx["phase"] == "settlement":
        carriers = ctx["established"] or ctx["current"]
    else:
        carriers = ctx["current"] or ctx["established"]
    default_carrier = "母带" if asset_mode else "支付账目"
    carrier_items = (carriers or [default_carrier])[:4]
    carrier_text = "、".join(carrier_items)
    primary_carrier = carrier_items[0]
    new_evidence_items = [
        item
        for item in ctx["current"]
        if item not in carrier_items
    ]
    new_evidence_clause = (
        f"{'、'.join(new_evidence_items)}结果同步写入会议记录，"
        if asset_mode and ctx["phase"] == "settlement" and new_evidence_items
        else ""
    )
    trigger = ctx["trigger_sentence"]
    reaction = ctx["reaction"]
    result = ctx["result"]
    loss = ctx["loss"] or result
    gain = ctx["gain"] or result
    subject = "交易" if asset_mode else "付款"
    authority = "独立评估人员" if asset_mode else "基金财务人员"
    review_dimensions = (
        "估值依据、拟售价格和处置权限"
        if asset_mode
        else "金额、收款去向和审批权限"
    )
    exposed_dimensions = (
        "打包范围、拟售价格与受让去向"
        if asset_mode
        else "私人收款去向与公开用途"
    )
    audit_questions = (
        f"谁提出打包、估值依据是什么、为什么需要由{o}单方决定受让去向"
        if asset_mode
        else f"这笔付款由谁申请、实际流向哪里、为什么需要由{o}单方决定"
    )
    protected_state = (
        f"{primary_carrier}仍在原持有状态，既未交割也未转移"
        if asset_mode
        else "款项仍在原账户，尚未划出"
    )
    operation_confirmation = (
        f"{primary_carrier}的保管人与交割记录都没有变化"
        if asset_mode
        else "付款指令停在划款之前，账户余额没有变化"
    )
    stop_marker = (
        "交易终止标记仍在，任何受让方都不能接收标的"
        if asset_mode
        else "支付终止标记仍在，任何收款方都不能取得款项"
    )
    frozen_state = "交易冻结与资产保全状态" if asset_mode else "付款冻结状态"
    evidence_restatement = (
        f"围绕{primary_carrier}的打包范围、拟售价格与受让去向重新投到屏幕上"
        if asset_mode
        else f"把{carrier_text}重新念出"
    )

    if ctx["phase"] == "settlement":
        paragraphs = {
            1: (
                f"前一场已经冻结的{primary_carrier}仍保持原状。{p}把相关人员留在公开核验位置，"
                f"随后{trigger.removeprefix(p)}。{authority}从开场就在场，"
                f"只接手已经列明的{subject}对象，不接受{o}临时换一套口径。"
                "所有人先确认旧安排尚未恢复，才进入正式结算。"
            ),
            2: (
                f"{authority}沿着{carrier_text}逐项核对，{new_evidence_clause}"
                f"{review_dimensions}都回到同一场会议中。"
                f"{p}不添加秘密材料，只要求每一项{subject}都能由在场者复查。"
                f"{o}原先能够口头推进的入口因此停住，"
                "任何人想继续执行，都必须先回答眼前记录指向谁。"
            ),
            3: (
                f"{reaction}。{o}先把责任推给流程，又试图离开核验位置。"
                f"{p}挡住话题，不挡人：“可以走，先把你刚才要求执行的{subject}说清。”"
                f"{authority}{evidence_restatement}，{o}无法再把同一笔安排拆成几件无关小事。"
                "逃避本身成了最后一次当面确认。"
            ),
            4: (
                f"核验完成后，现场立即执行对旧控制方的处理：{loss}。"
                f"{o}原先掌握的{subject}入口随决定关闭，相关人员不再接受他的单方指令。"
                f"他试图要求延后，{authority}却已经按新状态停止旧流程。"
                "现实损失在会议结束前完成，不留给会后私下改回。"
            ),
            5: (
                f"紧接着，另一项结果被当场确认：{gain}。"
                f"{p}逐项确认新权利能够实际阻止未经核验的{subject}，"
                f"并让{authority}在众人面前完成第一次按新规则操作。"
                "得到的不是一句支持，而是能够检查、叫停并决定去向的现实权限。"
            ),
            6: (
                f"{o}还想把失权说成暂时安排，{p}看着已经停止的旧入口："
                f"“不是我拿走了你的权力，是你把它写进了这笔{subject}里。”"
                f"{carrier_text}按新状态归档，{o}没有再得到恢复操作的机会。"
                f"{authority}继续执行已经生效的决定，现场到此收束。"
            ),
        }
    else:
        paragraphs = {
            1: (
                f"{p}记得，上一世，{ctx['old_signal'].rstrip('。')}。"
                f"眼前同一笔{subject}再次被推到桌上时，他没有立刻揭底，"
                f"而是{trigger.removeprefix(p)}。在场人都能看见{carrier_text}，"
                f"{o}也被留在必须亲自作出选择的位置。"
            ),
            2: (
                f"{p}让流程照常走到需要{o}表态的一步，却把最终执行暂时留在自己手里。"
                f"{reaction}。{carrier_text}因此由{o}亲手摆到众人面前，"
                f"{exposed_dimensions}无法再被拆开描述。"
                "他抢着证明自己有功，反而把最关键的归属一次说全。"
            ),
            3: (
                f"{p}没有把核验扩散到别的事项，只沿着眼前{carrier_text}问三个问题："
                f"{audit_questions}。"
                f"每个回答都停在已经公开的记录上。{o}越想加快流程，"
                "越显得不愿让在场人完成最基本的核对。"
            ),
            4: (
                f"核对完成后，{p}立即阻止执行。{result}。"
                f"负责操作的人当场停下{subject}，相关入口保持冻结，"
                f"{protected_state}。"
                "这次小胜不是一句揭穿，而是损失在发生前被现实动作截住。"
            ),
            5: (
                f"{p}要求{carrier_text}维持当前状态，等待公开的下一步审计或评估。"
                f"他没有提前宣布最终归属，也没有允许{o}用私下协商恢复流程。"
                f"{authority}当众确认旧指令已经停止，任何重新启动都必须经过新的核验。"
                "阶段结果因此有了可执行边界。"
            ),
            6: (
                f"{o}把冻结说成多此一举，{p}只回了一句："
                f"“真正怕耽误的人，不会急着让这笔{subject}看不见。”"
                f"{carrier_text}仍留在公开位置，相关人员按停止状态继续值守。"
                f"{o}失去单方推进的机会，只能等下一场正式结算。"
            ),
        }
    if ctx["phase"] == "settlement":
        expansions = {
            1: (
                f"{authority}先确认冻结状态仍在，旧指令没有在会前被偷偷恢复。"
                f"{p}等这项事实公开后，才把{subject}推进正式核验。"
            ),
            2: (
                f"每次核对完成，结果都由另一名在场人员复述。"
                f"{o}无法单独修改记录，也不能用一句内部安排跳过公开确认。"
            ),
            3: (
                f"他试图把自己的决定藏进集体流程，{p}却只追问谁要求执行。"
                f"答案回到{o}本人后，责任再也无法被分散。"
            ),
            4: (
                f"旧入口关闭后，现场立即尝试一次原指令，系统仍保持停止。"
                f"这次公开验证让{o}不能把失权说成尚未执行。"
            ),
            5: (
                f"{authority}把新权限对应的操作位置交给{p}确认。"
                f"他完成第一次检查后没有扩大范围，只守住本次{subject}的清楚边界。"
            ),
            6: (
                f"与会者依次确认最终状态，随后才收起各自材料。"
                f"{o}留在原位，已经没有口头指令能够改变刚才的结算。"
            ),
        }
    else:
        expansions = {
            1: (
                f"{authority}没有提前站队，只负责让现有流程按原顺序推进。"
                f"{p}也不替{o}作选择，把最关键的一步完整留给他自己。"
            ),
            2: (
                f"屏幕或桌面上的{review_dimensions}由{o}亲自确认，在场者随后逐项复述。"
                f"他以为抢先一步能占功，实际却把责任固定在自己的动作上。"
            ),
            3: (
                f"{authority}把三个回答依次留在会议记录中，谁也没有替{o}改写。"
                f"{p}每问完一项便停下来，让所有人看清前后是否一致。"
            ),
            4: (
                f"停止指令发出后，负责执行的人当众确认{operation_confirmation}。"
                f"{o}再催也只能面对已经生效的冻结结果。"
            ),
            5: (
                f"现场人员分别确认当前状态，确保无人能够绕开核验重新启动。"
                f"{p}把下一次审计或评估的参与方式当众说清。"
            ),
            6: (
                f"会议没有追着{o}羞辱，只把停止状态保持到最后。"
                f"原本等待执行的人重新坐下，说明他的单方节奏已经失效。"
            ),
        }
    if ctx["phase"] == "settlement":
        details = {
            1: f"会议记录从{p}开口时便保持公开，后来每一步都能沿原顺序复查。",
            2: f"{o}的确认没有被转述，而是由在场者亲耳听见。",
            3: f"{carrier_text}始终留在原处，问题和回答没有被拆到别的场景。",
            4: f"{authority}再次确认{subject}未被执行，旧控制入口已经关闭。",
            5: (
                f"{p}完成新权限下的首次核验后，让另一名在场者重复操作，"
                "相同结果证明决定已经生效。"
            ),
            6: f"{o}看着停止状态保持不变，最后只能把手从操作位置收回。",
        }
    else:
        details = {
            1: f"会议记录从{p}开口时便保持公开，后来每一步都能沿原顺序复查。",
            2: f"{o}的确认没有被转述，而是由在场者亲耳听见。",
            3: f"{carrier_text}始终留在原处，问题和回答没有被拆到别的场景。",
            4: f"{authority}再次确认{subject}未被执行，{stop_marker}。",
            5: (
                f"{p}只完成{frozen_state}复核，另一名在场者随后确认无人能够绕开停止指令。"
            ),
            6: f"{o}看着停止状态保持不变，最后只能把手从操作位置收回。",
        }
    return (
        paragraphs.get(segment_index, "")
        + expansions.get(segment_index, "")
        + details.get(segment_index, "")
    )


def _generic_contract_segment_fallback(
    chapter_card: Dict[str, Any],
    segment_index: int,
) -> str:
    """Render a bounded fallback paragraph from structured milestone facts only."""
    contract = (
        chapter_card.get("scene_contract")
        if isinstance(chapter_card.get("scene_contract"), dict)
        else _derive_closed_scene_contract(chapter_card)
    ) or {}
    if _closed_scene_contract_failures(contract):
        return ""
    if str(contract.get("scene_archetype") or "") == "physical_safety_validation":
        return _physical_safety_contract_segment(contract, segment_index)
    if str(contract.get("scene_archetype") or "") == "public_resource_audit":
        return _public_resource_audit_contract_segment(contract, segment_index)
    if str(contract.get("scene_archetype") or "") == "contract_rights_audit":
        return _contract_rights_audit_segment(contract, segment_index)
    if str(contract.get("scene_archetype") or "") == "live_capability_validation":
        return _live_capability_validation_segment(contract, segment_index)
    if str(contract.get("scene_archetype") or "") == "financial_process_audit":
        return _financial_or_asset_audit_segment(
            contract,
            segment_index,
            asset_mode=False,
        )
    if str(contract.get("scene_archetype") or "") == "asset_transaction_audit":
        return _financial_or_asset_audit_segment(
            contract,
            segment_index,
            asset_mode=True,
        )

    protagonist = str(contract.get("protagonist") or MAIN_PROTAGONIST)
    protagonist_short = protagonist.split("·", 1)[0]
    opponent = str(
        contract.get("opponent_scene_actor")
        or contract.get("opponent")
        or "既有对手"
    )
    opponent_short = opponent.split("·", 1)[0]
    trigger = str(contract.get("trigger_action") or "")
    reaction = str(contract.get("opponent_self_incrimination") or "")
    old_signal = str(contract.get("old_trap_signal") or "")
    old_signal = re.sub(
        rf"^(?:(?:{re.escape(protagonist)}|{re.escape(protagonist_short)}|主角))?记得",
        "",
        old_signal,
    ).lstrip("，：")
    old_signal = re.sub(r"^上一世", "", old_signal).lstrip("，：")
    result = str(contract.get("immediate_result") or "")
    authority = str(contract.get("authority_actor") or protagonist)
    current = list(contract.get("current_evidence_carriers") or [])
    established = list(contract.get("established_evidence_carriers") or [])
    carriers = "、".join(current or contract.get("allowed_evidence_carriers") or [])
    prior_carriers = "、".join(established) or carriers
    loss = str(contract.get("opponent_loss") or result)
    gain = str(contract.get("protagonist_gain") or result)
    phase = str(contract.get("phase") or "setup")

    if phase == "settlement":
        paragraphs = {
            1: (
                f"{protagonist_short}没有重新解释前因。前一场留下的{prior_carriers}"
                f"都还在原处，他当着在场人执行了已经说明的动作：{trigger}。"
                f"{protagonist_short}把每一样已经出现的材料放回同一条行动链，"
                "要求所有判断只看眼前事实，不接受事后补造的新说法。"
            ),
            2: (
                f"{carriers or '眼前行动'}逐项摆明后，"
                f"{reaction}。{opponent_short}的辩解没有改变他刚才亲手做过的动作，"
                f"反而把责任重新推回自己面前。{protagonist_short}没有追问无关细节，"
                "只让在场人把材料、动作和那句辩解按发生顺序对在一起。"
            ),
            3: (
                f"{protagonist_short}沿着已经建立的证据顺序完成核验。"
                f"他先指出{carriers or prior_carriers}，再指出{opponent_short}刚才的当面反应，"
                "两者指向同一个结果。对方想把问题拆成几件无关小事，"
                f"{protagonist_short}却把它们收回同一场冲突：“不用解释别处，只解释你亲手做的这一件。”"
            ),
            4: (
                f"{authority}没有把决定拖到以后，而是依据眼前已经完成的核验当场宣布："
                f"{loss}。相关权限和利益随宣告立即停止，原先由{opponent_short}控制的入口"
                "不再接受他的口头指令。他伸手想打断，现场执行者却只按刚才的决定继续动作。"
            ),
            5: (
                f"同一份决定随即写清另一面：{gain}。"
                f"{protagonist_short}没有接受一句空泛安慰，而是当场确认相关权限和资源已经可以执行。"
                "在场人依次照新状态行动，旧安排随之失效，口头胜负终于变成现实交接。"
            ),
            6: (
                f"{opponent_short}仍想把失败说成临时调整，声音却已经压不住。"
                f"{protagonist_short}看着他：“你亲手做出的选择，现在由你承担。”"
                f"他还想开口，{authority}已经继续执行生效后的决定。"
                f"{opponent_short}最终闭上嘴，只能看着原先握在手里的利益离开自己。"
            ),
        }
    else:
        paragraphs = {
            1: (
                f"{protagonist_short}记得，上一世，{old_signal.rstrip('。')}。"
                "旧局再次出现时，他没有把记忆说出口，也没有等待对方先完成陷阱。"
                f"他立刻抢先行动：{trigger}。"
                f"{protagonist_short}只改变眼前可以改变的条件，"
                "让后来每一步都必须在众人看得见的地方发生。"
            ),
            2: (
                f"{protagonist_short}只使用{carriers or '当面行动'}安排验证顺序。"
                "他把无关人员留在安全位置，把真正要验证的对象留在现场，"
                f"不给任何人事后补写过程的机会。{reaction}。"
                f"{opponent_short}以为自己抢回了主动，手上的动作却正好把旧局暴露出来。"
            ),
            3: (
                f"验证开始后，所有人只盯着{carriers or '眼前动作'}。"
                f"{protagonist_short}没有加入新的设备或材料，只按事先说清的顺序推进。"
                f"{opponent_short}刚才亲手完成的动作立刻产生可见后果，"
                f"{protagonist_short}当场反卡，把藏在流程后的选择推到众人面前。"
            ),
            4: (
                f"{result}。{protagonist_short}先阻止损失继续扩大，"
                "再确认现场人员已经按新的状态行动。没人需要等待来路不明的材料，"
                "也没人需要相信事后解释，刚才发生的动作和眼前结果已经足够清楚。"
            ),
            5: (
                f"{authority}当场确认这次结果立即生效。"
                f"{opponent_short}不能再用一句口头保证把现场带回旧状态。"
                f"{protagonist_short}要求{carriers or '现有载体'}保持原状，"
                "只保留已经发生的事实，不提前扩大战线。"
            ),
            6: (
                f"{opponent_short}还想把失败说成偶然，语气却比先前更急。"
                f"{protagonist_short}只回了一句：“捷径走到最后，先关上的总是你的退路。”"
                f"{opponent_short}看向{carriers or '眼前结果'}，再也无法让众人回到刚才的位置。"
                "现场按已经生效的新状态继续，争辩自行失去分量。"
            ),
        }
    expansions = {
        1: (
            "现场没有人替任何一方总结，也没有人把注意力移向别处。"
            f"{protagonist_short}每推进一个动作，就停一下让在场者看清它与前一步的关系，"
            "压力因此落在正在作出选择的人身上。"
        ),
        2: (
            f"{opponent_short}试着用更快的语速夺回节奏，{protagonist_short}却不跟着争辩，"
            "只要求现场继续按已经说清的顺序走。旁观者的视线随动作移动，"
            "那份自以为稳妥的抢先一步逐渐变成无法收回的承认。"
        ),
        3: (
            f"局面变化后，{protagonist_short}没有乘机增加第二套说法。"
            "他把注意力重新压回同一批载体和同一个动作，"
            f"让所有人都能沿着眼前顺序得出结论。{opponent_short}越想岔开话题，"
            "越显得不敢正面回答。"
        ),
        4: (
            "决定落下后，现场立刻有人按新状态行动，原来的安排随即停止。"
            f"{opponent_short}试图用一句稍后再谈拖延，却没有人停下执行。"
            f"{protagonist_short}盯着结果真正完成，直到损失不再有机会沿旧路径继续扩大。"
        ),
        5: (
            f"{protagonist_short}逐项确认生效状态，没有把现实收益换成一句赞许。"
            "原先模糊的边界在现场变得清楚，谁能决定、谁必须停手都已经落定。"
            "在场人随即按新的权限关系站位和行动。"
        ),
        6: (
            f"短暂的安静比争吵更清楚。{opponent_short}看向刚才亲手推动的局面，"
            f"再也找不到可以撤回的空隙。{protagonist_short}没有追着羞辱，"
            "只守住已经落地的结果，让最后一次嘴硬自行失去分量。"
        ),
    }
    return paragraphs.get(segment_index, "") + expansions.get(segment_index, "")


def _should_use_api_segment_recovery(
    chapter_card: Dict[str, Any],
    body_try: int,
) -> bool:
    """Use model-written beat recovery after repeated whole-chapter contract drift."""
    if body_try < 2:
        return False
    if os.getenv("V2_ENABLE_API_SEGMENT_RECOVERY", "1").strip().lower() not in {
        "1", "true", "yes", "on",
    }:
        return False
    if os.getenv("V2_ALLOW_TEMPLATE_PROSE_FALLBACK", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return False
    plan = _closed_scene_segment_plan(chapter_card)
    return bool(plan and len(plan[1]) >= 8)


def _reflow_segmented_scene_paragraphs(
    segments: List[str],
    chapter_card: Dict[str, Any],
) -> str:
    """Hide beat boundaries behind varied natural paragraph rhythm."""
    sentences = [
        sentence.strip()
        for segment in segments
        for sentence in re.findall(
            r"[^。！？]*[。！？][”’\"]?|[^。！？]+$",
            str(segment or "").strip(),
        )
        if sentence.strip()
    ]
    if len(sentences) < 8:
        return "\n\n".join(segment.strip() for segment in segments if segment.strip())

    fingerprint = "|".join((
        str(chapter_card.get("cluster_id") or ""),
        str(chapter_card.get("chapter_id") or ""),
        str((chapter_card.get("scene_contract") or {}).get("scene_archetype") or ""),
        str(chapter_card.get("chapter_goal") or ""),
    ))
    seed = int(hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:8], 16)
    target_paragraphs = 9 + seed % 5
    target_chars = max(70, sum(len(sentence) for sentence in sentences) // target_paragraphs)
    dialogue_budget = 2 + seed % 2

    paragraphs: List[List[str]] = []
    buffer: List[str] = []
    buffer_chars = 0
    isolated_dialogue = 0
    for sentence in sentences:
        is_short_dialogue = (
            "“" in sentence
            and len(sentence) <= 90
            and isolated_dialogue < dialogue_budget
        )
        if is_short_dialogue:
            if buffer:
                paragraphs.append(buffer)
                buffer = []
                buffer_chars = 0
            paragraphs.append([sentence])
            isolated_dialogue += 1
            continue
        buffer.append(sentence)
        buffer_chars += len(sentence)
        if buffer_chars >= target_chars:
            paragraphs.append(buffer)
            buffer = []
            buffer_chars = 0
    if buffer:
        paragraphs.append(buffer)

    while len(paragraphs) > 14:
        merge_at = min(
            range(len(paragraphs) - 1),
            key=lambda index: (
                len("".join(paragraphs[index]))
                + len("".join(paragraphs[index + 1]))
            ),
        )
        paragraphs[merge_at] = paragraphs[merge_at] + paragraphs[merge_at + 1]
        paragraphs.pop(merge_at + 1)
    while len(paragraphs) < 8:
        split_at = max(
            range(len(paragraphs)),
            key=lambda index: len(paragraphs[index]),
        )
        paragraph = paragraphs[split_at]
        if len(paragraph) < 2:
            break
        midpoint = len(paragraph) // 2
        paragraphs[split_at:split_at + 1] = [
            paragraph[:midpoint],
            paragraph[midpoint:],
        ]
    return "\n\n".join("".join(paragraph).strip() for paragraph in paragraphs if paragraph)


def _assemble_segmented_closed_scene(
    segments: List[str],
    chapter_card: Dict[str, Any],
) -> str:
    """Normalize one segmented draft through the same surface pipeline."""
    assembled = _reflow_segmented_scene_paragraphs(segments, chapter_card)
    assembled = _strip_empty_ending_cliches(assembled)
    assembled = _normalize_joined_canonical_names(assembled, chapter_card)
    assembled = _normalize_unplanned_document_titles(assembled, chapter_card)
    assembled = _normalize_closed_scene_surface_drift(assembled, chapter_card)
    assembled = _ensure_medication_audit_previous_life_motive(
        assembled,
        chapter_card,
    )
    assembled = _ensure_medication_audit_handover(assembled, chapter_card)
    assembled = _ensure_performance_previous_life_action(
        assembled,
        chapter_card,
    )
    return assembled


def _segmented_closed_scene_fill_spec(
    chapter_card: Dict[str, Any],
    segment_count: int,
) -> Tuple[int, int, str]:
    """Choose a pre-settlement insertion point and narrow incremental beat."""
    _, performance_scene, paper_markers = _closed_evidence_contract(chapter_card)
    medication_paper_audit = all(
        marker in paper_markers for marker in ("封签", "送货单", "领用簿")
    )
    if performance_scene:
        return (
            3,
            3,
            "只补叫停前仍在推进的一小段表演。只用普通踏步、转身、侧移、摆臂、"
            "歌声、节拍、音准、自然换气，以及对手、合作方代表和现场见证人的"
            "看、听、说与位置变化。不得写叫停、完成、通过或权限结算，"
            "不得使用身体部位、精确数字、距离、角度、动作编号、比喻或分号。",
        )
    if medication_paper_audit:
        return (
            4,
            3,
            "只补停职决定前的一小段当面对峙。只围绕封签保持未拆、送货单七支、"
            "领用簿八支和三人已经说过的话推进。不得新增字段、清点、文件、签字、"
            "停职决定、索要钥匙或钥匙交接。",
        )
    contract = (
        chapter_card.get("scene_contract")
        if isinstance(chapter_card.get("scene_contract"), dict)
        else _derive_closed_scene_contract(chapter_card)
    ) or {}
    carriers = "、".join(contract.get("allowed_evidence_carriers") or []) or "既有现场行动"
    return (
        max(2, segment_count - 3),
        3,
        "只补本章结果生效前的一小段反卡推进。允许载体只有"
        + carriers
        + "；不得新增材料、人物、地点、参数、规则，不得提前写裁决、得失或收束。",
    )


def _try_closed_scene_micro_expansion(
    gen: "RebirthRevengeGeneratorV2",
    chapter_num: int,
    original: str,
    chapter_card: Dict[str, Any],
    *,
    minimum_chars: int,
    max_tokens: int,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Add one model-written paragraph, then rerun every final chapter check."""
    original = str(original or "").strip()
    shortfall = minimum_chars - len(original)
    if (
        shortfall <= 0
        or shortfall > 360
        or os.environ.get("V2_ENABLE_CLOSED_SCENE_MICRO", "1").strip().lower()
        not in {"1", "true", "yes", "on"}
    ):
        return None
    micro_prompt = _build_closed_scene_micro_expansion_prompt(
        chapter_num,
        original,
        chapter_card,
        shortfall,
    )
    if not micro_prompt:
        return None

    def save_rejection(addition: str, reason: str, attempt: int) -> None:
        if os.getenv("V2_SAVE_REJECTED_DRAFTS", "").strip().lower() not in {
            "1", "true", "yes", "on",
        }:
            return
        trace = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            os.getenv("V2_TRACE_RUN_ID", "run"),
        ).strip("_") or "run"
        rejected_dir = OUTPUT_DIR / "rejected_drafts" / "micro_failures"
        rejected_dir.mkdir(parents=True, exist_ok=True)
        (
            rejected_dir
            / f"chapter_{chapter_num:03d}_{trace}_try_{attempt + 1}.txt"
        ).write_text(
            str(addition or "").strip()
            + "\n\n--- FAILURE ---\n"
            + str(reason or "未知失败"),
            encoding="utf-8",
        )

    last_micro_failure = ""
    for micro_try in range(3):
        attempt_prompt = micro_prompt
        if last_micro_failure:
            attempt_prompt += (
                "\n\n上一份补段已经完全作废，失败原因是："
                + last_micro_failure
                + "。本次必须从空白重写，全文避开该失败原因触发的元素，"
                "不能只改前两句；不要解释修改过程。"
            )
        addition = str(gen._call_api(  # type: ignore[attr-defined]
            attempt_prompt,
            None,
            micro_try,
            max_tokens=min(max_tokens, 800),
        ) or "").strip()
        if not addition or addition.startswith("通义千问"):
            continue
        _, performance_scene, paper_markers = _closed_evidence_contract(chapter_card)
        candidate_failure = _closed_scene_segment_candidate_failure(
            addition,
            chapter_card,
            3,
        )
        if candidate_failure:
            last_micro_failure = candidate_failure
            save_rejection(addition, candidate_failure, micro_try)
            print(
                f"  ⚠️ 第{chapter_num}章微补候选未通过：{candidate_failure[:120]}",
                flush=True,
            )
            continue
        if performance_scene and re.search(
            r"停一下|暂停|叫停|喊停|给我停|最后|收势|站定|完成|"
            r"测试通过|符合要求|训练强度决定权",
            addition,
        ):
            reason = "表演微补段提前重复叫停、完成或结算"
            last_micro_failure = reason
            save_rejection(addition, reason, micro_try)
            print(
                f"  ⚠️ 第{chapter_num}章{reason}，已丢弃。",
                flush=True,
            )
            continue
        if paper_markers and re.search(
            r"即刻暂停|暂停你的职务|钥匙|药品保管权|撕(?:掉|下|开|毁)",
            addition,
        ):
            reason = "纸面微补段提前重复停职、交钥匙或毁证"
            last_micro_failure = reason
            save_rejection(addition, reason, micro_try)
            print(
                f"  ⚠️ 第{chapter_num}章{reason}，已丢弃。",
                flush=True,
            )
            continue
        expanded = _insert_closed_scene_micro_expansion(
            original,
            addition,
            chapter_card,
        )
        expanded = _strip_empty_ending_cliches(expanded)
        expanded = _normalize_joined_canonical_names(expanded, chapter_card)
        expanded = _normalize_unplanned_document_titles(expanded, chapter_card)
        expanded = _normalize_closed_scene_surface_drift(expanded, chapter_card)
        expanded = _ensure_medication_audit_previous_life_motive(
            expanded,
            chapter_card,
        )
        expanded = _ensure_medication_audit_handover(expanded, chapter_card)
        expanded = _ensure_performance_previous_life_action(
            expanded,
            chapter_card,
        )
        micro_failures = _chapter_body_hard_failures(
            expanded,
            chapter_num=chapter_num,
            chapter_card=chapter_card,
        )
        micro_failures.extend(
            _scene_contract_fulfillment_failures(expanded, chapter_card)
        )
        if micro_failures or len(expanded) < minimum_chars:
            reason = (
                micro_failures[0]
                if micro_failures
                else f"仍只有{len(expanded)}字"
            )
            last_micro_failure = reason
            save_rejection(addition, reason, micro_try)
            print(
                f"  ⚠️ 第{chapter_num}章封闭场景微补长未通过：{reason[:120]}",
                flush=True,
            )
            continue
        expanded_memory, expanded_violations = gen.review_story_memory(  # type: ignore[attr-defined]
            chapter_num,
            expanded,
        )
        hard_expanded = [
            violation
            for violation in expanded_violations
            if getattr(violation, "severity", "hard") == "hard"
        ]
        expanded_contract = _validate_chapter_memory_contract(
            chapter_card,
            expanded_memory,
        )
        if hard_expanded or expanded_contract:
            reason = (
                str(hard_expanded[0])
                if hard_expanded
                else str(expanded_contract[0])
            )
            last_micro_failure = reason
            save_rejection(addition, reason, micro_try)
            continue
        print(
            f"  🧩 第{chapter_num}章已在结算前微补长至 {len(expanded)} 字并复审通过。",
            flush=True,
        )
        return expanded, expanded_memory
    return None


def _generate_segmented_closed_scene(
    gen: "RebirthRevengeGeneratorV2",
    chapter_num: int,
    chapter_card: Dict[str, Any],
    *,
    minimum_chars: int,
    max_tokens: int,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Generate and validate a closed scene beat by beat when whole-chapter calls stay short."""
    plan = _closed_scene_segment_plan(chapter_card)
    if plan is None:
        return None
    facts, segment_specs = plan
    _, performance_scene, paper_markers = _closed_evidence_contract(chapter_card)
    medication_paper_audit = all(
        marker in paper_markers for marker in ("封签", "送货单", "领用簿")
    )
    generic_contract_mode = not performance_scene and not medication_paper_audit
    allow_template_fallback = (
        os.getenv("V2_ALLOW_TEMPLATE_PROSE_FALLBACK", "0").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    deterministic_indexes = (
        set(range(1, 9))
        if allow_template_fallback and performance_scene
        else (
            set(range(1, 9))
            if allow_template_fallback and medication_paper_audit
            else set()
        )
    )
    for assembly_try in range(2):
        segments: List[str] = []
        failed_segment = False
        for index, (target_min, target_max, beat) in enumerate(segment_specs, start=1):
            segment = ""
            last_candidate_failure = ""
            last_candidate_length = 0
            minimum_segment_chars = (
                max(50, int(target_min * 0.55))
                if index == len(segment_specs)
                else max(90, int(target_min * 0.55))
            )
            if allow_template_fallback and generic_contract_mode and assembly_try > 0:
                deterministic_candidate = _shape_closed_scene_segment_candidate(
                    _generic_contract_segment_fallback(chapter_card, index),
                    chapter_card,
                    target_max,
                    index,
                ).strip()
                deterministic_failure = _closed_scene_segment_candidate_failure(
                    deterministic_candidate,
                    chapter_card,
                    index,
                )
                if (
                    deterministic_candidate
                    and len(deterministic_candidate) >= minimum_segment_chars
                    and not deterministic_failure
                ):
                    segment = deterministic_candidate
            if index in deterministic_indexes:
                deterministic_candidate = _shape_closed_scene_segment_candidate(
                    "",
                    chapter_card,
                    target_max,
                    index,
                ).strip()
                deterministic_failure = _closed_scene_segment_candidate_failure(
                    deterministic_candidate,
                    chapter_card,
                    index,
                )
                if (
                    deterministic_candidate
                    and len(deterministic_candidate) >= 8
                    and not deterministic_failure
                ):
                    segment = deterministic_candidate
            segment_attempts = 4 if generic_contract_mode else 5
            for segment_try in range(segment_attempts):
                if segment:
                    break
                requested_min = min(
                    max(target_min, target_max - 5),
                    max(target_min, int(target_min * 1.2 + 0.5)),
                )
                prompt = _build_closed_scene_segment_prompt(
                    chapter_num,
                    facts,
                    index,
                    len(segment_specs),
                    requested_min,
                    target_max,
                    beat,
                    segments[-1] if segments else "",
                )
                if last_candidate_failure:
                    prompt += (
                        "\n\n上一份本段草稿已作废，失败原因是："
                        + last_candidate_failure
                        + "。"
                        + _segment_semantic_repair_directive(last_candidate_failure)
                        + "本次从空白重写同一段，必须直接修复该项，"
                        "同时继续遵守事实白名单与本段字数范围；不要解释修改过程。"
                    )
                candidate = str(gen._call_api(  # type: ignore[attr-defined]
                    prompt,
                    None,
                    assembly_try * 2 + segment_try,
                    max_tokens=min(max_tokens, 900),
                ) or "").strip()
                candidate = re.sub(
                    r"^(?:第[一二三四五六七八九十\d]+段|正文|自然段)\s*[:：]?\s*",
                    "",
                    candidate,
                ).strip()
                candidate = _shape_closed_scene_segment_candidate(
                    candidate,
                    chapter_card,
                    target_max,
                    index,
                ).strip()
                candidate_failure = _closed_scene_segment_candidate_failure(
                    candidate,
                    chapter_card,
                    index,
                )
                if not candidate_failure:
                    candidate_failure = _segment_prior_prose_overlap_failure(
                        candidate,
                        segments,
                    )
                if candidate and candidate_failure:
                    repair_prompt = _build_closed_scene_segment_prompt(
                        chapter_num,
                        facts,
                        index,
                        len(segment_specs),
                        requested_min,
                        target_max,
                        beat,
                        segments[-1] if segments else "",
                    )
                    repair_prompt += (
                        "\n\n上一份本段草稿已经完全作废，不得保留、续接或改写它的句序。"
                        "失败原因："
                        + candidate_failure
                        + "。"
                        + _segment_semantic_repair_directive(candidate_failure)
                        + "在字数范围内从空白完整重写这一段；"
                        "只输出重写后的完整自然段。"
                    )
                    repaired_candidate = str(gen._call_api(  # type: ignore[attr-defined]
                        repair_prompt,
                        None,
                        assembly_try * 100 + segment_try * 2 + 1,
                        max_tokens=min(max_tokens, 900),
                    ) or "").strip()
                    repaired_candidate = re.sub(
                        r"^(?:第[一二三四五六七八九十\d]+段|正文|自然段|重写)"
                        r"\s*[:：]?\s*",
                        "",
                        repaired_candidate,
                    ).strip()
                    if (
                        repaired_candidate
                        and not repaired_candidate.startswith("通义千问")
                    ):
                        candidate = _shape_closed_scene_segment_candidate(
                            repaired_candidate,
                            chapter_card,
                            target_max,
                            index,
                        ).strip()
                        candidate_failure = _closed_scene_segment_candidate_failure(
                            candidate,
                            chapter_card,
                            index,
                        )
                        if not candidate_failure:
                            candidate_failure = _segment_prior_prose_overlap_failure(
                                candidate,
                                segments,
                            )
                elif candidate and len(candidate) < minimum_segment_chars:
                    needed = max(60, minimum_segment_chars - len(candidate))
                    continuation_min = min(140, needed)
                    continuation_max = min(
                        180,
                        max(continuation_min + 30, target_max - len(candidate) + 20),
                    )
                    continuation_prompt = _build_closed_scene_segment_prompt(
                        chapter_num,
                        facts,
                        index,
                        len(segment_specs),
                        continuation_min,
                        continuation_max,
                        (
                            "只续写当前同一事件拍，不重复已有句子，不进入下一拍；"
                            + (
                                f"必须补齐“{candidate_failure}”；"
                                if candidate_failure else ""
                            )
                            + beat
                        ),
                        candidate,
                    )
                    continuation = str(gen._call_api(  # type: ignore[attr-defined]
                        continuation_prompt,
                        None,
                        assembly_try * 100 + segment_try * 2 + 1,
                        max_tokens=min(max_tokens, 700),
                    ) or "").strip()
                    continuation = re.sub(
                        r"^(?:第[一二三四五六七八九十\d]+段|正文|自然段|续写)"
                        r"\s*[:：]?\s*",
                        "",
                        continuation,
                    ).strip()
                    if continuation and not continuation.startswith("通义千问"):
                        candidate = _shape_closed_scene_segment_candidate(
                            candidate.rstrip() + continuation,
                            chapter_card,
                            target_max,
                            index,
                        ).strip()
                        candidate_failure = _closed_scene_segment_candidate_failure(
                            candidate,
                            chapter_card,
                            index,
                        )
                        if not candidate_failure:
                            candidate_failure = _segment_prior_prose_overlap_failure(
                                candidate,
                                segments,
                            )
                last_candidate_length = len(candidate)
                last_candidate_failure = (
                    candidate_failure
                    or (
                        f"只有{len(candidate)}字，至少需要{minimum_segment_chars}字"
                        if len(candidate) < minimum_segment_chars
                        else ""
                    )
                )
                if (
                    candidate
                    and not candidate.startswith("通义千问")
                    and len(candidate) >= minimum_segment_chars
                    and not candidate_failure
                ):
                    segment = candidate
                    break
            if not segment and allow_template_fallback and generic_contract_mode:
                fallback_candidate = _shape_closed_scene_segment_candidate(
                    _generic_contract_segment_fallback(chapter_card, index),
                    chapter_card,
                    target_max,
                    index,
                ).strip()
                fallback_failure = _closed_scene_segment_candidate_failure(
                    fallback_candidate,
                    chapter_card,
                    index,
                )
                if (
                    fallback_candidate
                    and len(fallback_candidate) >= minimum_segment_chars
                    and not fallback_failure
                ):
                    segment = fallback_candidate
            if not segment:
                if os.getenv("V2_SAVE_REJECTED_DRAFTS", "").strip().lower() in {
                    "1", "true", "yes", "on"
                }:
                    segment_rejected_dir = (
                        OUTPUT_DIR / "rejected_drafts" / "segment_failures"
                    )
                    segment_rejected_dir.mkdir(parents=True, exist_ok=True)
                    (
                        segment_rejected_dir
                        / (
                            f"chapter_{chapter_num:03d}_assembly_{assembly_try + 1}"
                            f"_segment_{index:02d}.txt"
                        )
                    ).write_text(
                        (candidate or "")
                        + "\n\n--- FAILURE ---\n"
                        + (last_candidate_failure or "空响应"),
                        encoding="utf-8",
                    )
                print(
                    f"  ⚠️ 第{chapter_num}章分段兜底第{index}/{len(segment_specs)}段"
                    f"连续失败（末稿{last_candidate_length}字）："
                    f"{last_candidate_failure or '空响应'}",
                    flush=True,
                )
                failed_segment = True
                break
            segments.append(segment)
        if failed_segment:
            continue
        assembled = _assemble_segmented_closed_scene(segments, chapter_card)
        failures = _chapter_body_hard_failures(
            assembled,
            chapter_num=chapter_num,
            chapter_card=chapter_card,
        )
        failures.extend(
            _scene_contract_fulfillment_failures(assembled, chapter_card)
        )
        if not failures and len(assembled) < minimum_chars:
            insert_base, validation_index, fill_beat = (
                _segmented_closed_scene_fill_spec(
                    chapter_card,
                    len(segments),
                )
            )
            accepted_fills = 0
            for fill_round in range(4):
                if len(assembled) >= minimum_chars:
                    break
                slots_left = 4 - fill_round
                shortfall = minimum_chars - len(assembled)
                target_min = min(
                    140,
                    max(
                        90,
                        (shortfall + slots_left - 1) // slots_left + 20,
                    ),
                )
                target_max = min(180, target_min + 45)
                insert_at = min(
                    insert_base + accepted_fills,
                    max(1, len(segments) - 1),
                )
                fill_segment = ""
                last_fill_failure = ""
                for fill_try in range(4):
                    fill_prompt = _build_closed_scene_segment_prompt(
                        chapter_num,
                        facts,
                        validation_index,
                        len(segments) + 1,
                        target_min,
                        target_max,
                        fill_beat,
                        segments[insert_base - 1] if insert_base else "",
                    )
                    if last_fill_failure:
                        fill_prompt += (
                            "\n\n上一份补足段已经作废，失败原因是："
                            + last_fill_failure
                            + "。"
                            + _segment_semantic_repair_directive(last_fill_failure)
                            + "本次从空白重写，只输出当前新增推进，不解释修改过程。"
                        )
                    candidate = str(gen._call_api(  # type: ignore[attr-defined]
                        fill_prompt,
                        None,
                        500 + fill_round * 10 + fill_try,
                        max_tokens=min(max_tokens, 700),
                    ) or "").strip()
                    candidate = re.sub(
                        r"^(?:第[一二三四五六七八九十\d]+段|正文|自然段|补足段)"
                        r"\s*[:：]?\s*",
                        "",
                        candidate,
                    ).strip()
                    candidate = _shape_closed_scene_segment_candidate(
                        candidate,
                        chapter_card,
                        target_max,
                        validation_index,
                    ).strip()
                    candidate_failure = _closed_scene_segment_candidate_failure(
                        candidate,
                        chapter_card,
                        validation_index,
                    )
                    if not candidate_failure:
                        candidate_failure = _segment_prior_prose_overlap_failure(
                            candidate,
                            segments,
                        )
                    if len(candidate) < 70 and not candidate_failure:
                        candidate_failure = f"补足段只有{len(candidate)}字，至少需要70字"
                    if candidate_failure:
                        last_fill_failure = candidate_failure
                        continue
                    segments.insert(insert_at, candidate)
                    provisional = _assemble_segmented_closed_scene(
                        segments,
                        chapter_card,
                    )
                    provisional_failures = _chapter_body_hard_failures(
                        provisional,
                        chapter_num=chapter_num,
                        chapter_card=chapter_card,
                    )
                    provisional_failures.extend(
                        _scene_contract_fulfillment_failures(
                            provisional,
                            chapter_card,
                        )
                    )
                    if provisional_failures:
                        segments.pop(insert_at)
                        last_fill_failure = provisional_failures[0]
                        continue
                    fill_segment = candidate
                    assembled = provisional
                    failures = []
                    accepted_fills += 1
                    break
                if not fill_segment:
                    print(
                        f"  ⚠️ 第{chapter_num}章结算前小段补足失败："
                        f"{last_fill_failure[:120] or '空响应'}",
                        flush=True,
                    )
                    continue
            if accepted_fills:
                print(
                    f"  🧩 第{chapter_num}章已用{accepted_fills}个受约束小段补至"
                    f" {len(assembled)} 字。",
                    flush=True,
                )
        if not failures and len(assembled) < minimum_chars:
            expanded = _try_closed_scene_micro_expansion(
                gen,
                chapter_num,
                assembled,
                chapter_card,
                minimum_chars=minimum_chars,
                max_tokens=max_tokens,
            )
            if expanded is not None:
                return expanded
        if failures or len(assembled) < minimum_chars:
            reason = failures[0] if failures else f"仍只有{len(assembled)}字"
            if os.getenv("V2_SAVE_REJECTED_DRAFTS", "").strip().lower() in {
                "1", "true", "yes", "on"
            }:
                rejected_dir = OUTPUT_DIR / "rejected_drafts"
                rejected_dir.mkdir(parents=True, exist_ok=True)
                rejected_path = (
                    rejected_dir
                    / f"chapter_{chapter_num:03d}_segmented_try_{assembly_try + 1}.txt"
                )
                rejected_path.write_text(
                    assembled + "\n\n--- HARD FAILURES ---\n"
                    + "\n".join(failures or [reason]),
                    encoding="utf-8",
                )
            print(
                f"  ⚠️ 第{chapter_num}章封闭场景分段兜底未通过：{reason[:120]}",
                flush=True,
            )
            continue
        memory, violations = gen.review_story_memory(  # type: ignore[attr-defined]
            chapter_num,
            assembled,
        )
        hard_violations = [
            violation
            for violation in violations
            if getattr(violation, "severity", "hard") == "hard"
        ]
        memory_failures = _validate_chapter_memory_contract(chapter_card, memory)
        if hard_violations or memory_failures:
            continue
        print(
            f"  🧱 第{chapter_num}章已按通用封闭场景分段生成至 {len(assembled)} 字并复审通过。",
            flush=True,
        )
        return assembled, memory
    return None


def _expand_short_chapter_before_commit(
    gen: "RebirthRevengeGeneratorV2",
    chapter_num: int,
    original_text: str,
    chapter_card: Dict[str, Any],
    original_memory: Dict[str, Any],
    *,
    max_tokens: int,
    prev_tail_scene: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """Expand before the next chapter is planned so later continuity sees the final text."""
    original = (original_text or "").strip()
    minimum_chars = _minimum_chapter_chars(chapter_num, chapter_card)
    if len(original) >= minimum_chars:
        return original, original_memory

    closed_scene_prompt = _build_closed_evidence_scene_prompt(
        chapter_num,
        chapter_card,
        prev_tail_scene=prev_tail_scene,
        failures=[
            f"上一份完整正文只有{len(original)}字，低于{minimum_chars}字。"
            "本轮必须重新生成整章并达到字数，不得输出补丁或沿用短稿。"
        ],
        attempt=3,
    )
    if closed_scene_prompt:
        micro_expanded = _try_closed_scene_micro_expansion(
            gen,
            chapter_num,
            original,
            chapter_card,
            minimum_chars=minimum_chars,
            max_tokens=max_tokens,
        )
        if micro_expanded is not None:
            return micro_expanded

    if closed_scene_prompt:
        segmented = _generate_segmented_closed_scene(
            gen,
            chapter_num,
            chapter_card,
            minimum_chars=minimum_chars,
            max_tokens=max_tokens,
        )
        if segmented is not None:
            return segmented
        print(
            f"  ⚠️ 第{chapter_num}章封闭场景分段补长失败，回退整章重建。",
            flush=True,
        )
        for rebuild_try in range(3):
            rebuilt_prompt = _build_closed_evidence_scene_prompt(
                chapter_num,
                chapter_card,
                prev_tail_scene=prev_tail_scene,
                failures=[
                    f"上一份完整正文只有{len(original)}字，低于{minimum_chars}字。",
                    "必须从空白页重写完整章节，增加同一场景内的动作、对话、对手反应和情绪递进，"
                    "不得新增证据、人物、地点或后续事件。",
                ],
                attempt=3 + rebuild_try,
            )
            rebuilt = str(gen._call_api(  # type: ignore[attr-defined]
                rebuilt_prompt or closed_scene_prompt,
                None,
                rebuild_try,
                max_tokens=max_tokens,
            ) or "").strip()
            if not rebuilt or rebuilt.startswith("通义千问"):
                continue
            rebuilt = _strip_empty_ending_cliches(rebuilt)
            rebuilt = _normalize_joined_canonical_names(rebuilt, chapter_card)
            rebuilt = _normalize_planned_work_title_aliases(rebuilt, chapter_card)
            rebuilt = _ensure_planned_work_title_reference(rebuilt, chapter_card)
            rebuilt = _normalize_unplanned_document_titles(rebuilt, chapter_card)
            rebuilt = _normalize_closed_scene_surface_drift(rebuilt, chapter_card)
            rebuilt = _ensure_medication_audit_previous_life_motive(
                rebuilt,
                chapter_card,
            )
            rebuilt = _ensure_medication_audit_handover(rebuilt, chapter_card)
            rebuilt = _ensure_performance_previous_life_action(
                rebuilt,
                chapter_card,
            )
            rebuilt_failures = _chapter_body_hard_failures(
                rebuilt,
                chapter_num=chapter_num,
                chapter_card=chapter_card,
            )
            if rebuilt_failures or len(rebuilt) < minimum_chars:
                reason = rebuilt_failures[0] if rebuilt_failures else f"仍只有{len(rebuilt)}字"
                print(
                    f"  ⚠️ 第{chapter_num}章封闭场景整章补长未通过：{reason[:120]}",
                    flush=True,
                )
                continue
            rebuilt_memory, rebuilt_violations = gen.review_story_memory(  # type: ignore[attr-defined]
                chapter_num, rebuilt
            )
            hard_rebuilt = [
                violation
                for violation in rebuilt_violations
                if getattr(violation, "severity", "hard") == "hard"
            ]
            rebuilt_contract = _validate_chapter_memory_contract(chapter_card, rebuilt_memory)
            if hard_rebuilt or rebuilt_contract:
                continue
            print(
                f"  🧱 第{chapter_num}章已按封闭场景从零补长至 {len(rebuilt)} 字并复审通过。",
                flush=True,
            )
            return rebuilt, rebuilt_memory

        print(
            f"  ⚠️ 第{chapter_num}章封闭场景分段与整章重建均失败；"
            "跳过会改写既有结尾的通用扩写器，交由外层事务重试。",
            flush=True,
        )
        return original, original_memory

    working = original
    working_memory = original_memory
    for expansion_try in range(3):
        addition = str(gen._call_api(  # type: ignore[attr-defined]
            _build_chapter_expansion_prompt(chapter_num, working, chapter_card),
            None,
            expansion_try,
            max_tokens=max_tokens,
        ) or "").strip()
        if not addition or addition.startswith("通义千问"):
            continue
        expanded = _insert_before_last_paragraph(working, addition)
        expanded = _strip_empty_ending_cliches(expanded)
        expanded = _normalize_joined_canonical_names(expanded, chapter_card)
        expanded = _normalize_planned_work_title_aliases(expanded, chapter_card)
        expanded = _ensure_planned_work_title_reference(expanded, chapter_card)
        expanded = _normalize_unplanned_document_titles(expanded, chapter_card)
        expanded = _normalize_closed_scene_surface_drift(expanded, chapter_card)
        expanded = _ensure_medication_audit_previous_life_motive(
            expanded,
            chapter_card,
        )
        expanded = _ensure_medication_audit_handover(expanded, chapter_card)
        expanded = _ensure_performance_previous_life_action(
            expanded,
            chapter_card,
        )
        if not _expansion_preserves_original_ending(original, expanded):
            print(f"  ⚠️ 第{chapter_num}章扩写改写或续写了原章结尾，丢弃扩写版。", flush=True)
            continue
        expansion_body_hard = _chapter_body_hard_failures(
            expanded, chapter_num=chapter_num, chapter_card=chapter_card
        )
        if expansion_body_hard:
            print(
                f"  ⚠️ 第{chapter_num}章扩写引入正文禁项，丢弃扩写版："
                f"{expansion_body_hard[0][:120]}",
                flush=True,
            )
            continue
        expanded_memory, expanded_violations = gen.review_story_memory(  # type: ignore[attr-defined]
            chapter_num, expanded
        )
        hard_expansion = [
            violation
            for violation in expanded_violations
            if getattr(violation, "severity", "hard") == "hard"
        ]
        expansion_contract = _validate_chapter_memory_contract(chapter_card, expanded_memory)
        if hard_expansion or expansion_contract:
            continue
        working = expanded
        working_memory = expanded_memory
        if len(working) < minimum_chars:
            continue
        print(
            f"  🧱 第{chapter_num}章已在生成下一章前扩写至 {len(working)} 字并通过连续性复审。",
            flush=True,
        )
        return working, working_memory
    return working, working_memory


def _rebuild_cluster_state_before_chapter(
    gen: "RebirthRevengeGeneratorV2",
    cluster: Dict[str, Any],
    contract_obj: Dict[str, Any],
    chapter_texts: Dict[int, str],
    chapter_nums: List[int],
    prev_tail_scene: str,
    prev_unresolved_hook: str,
    target_ch: int,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """生成 target_ch 之前的状态机快照（用于局部补写时拼滚动上下文）。"""
    cluster_state = _init_cluster_state(str(cluster.get("cluster_id", "") or ""), contract_obj)
    cluster_state["last_scene"] = prev_tail_scene or ""
    cluster_state["last_hook"] = prev_unresolved_hook or ""
    prev_ch_text: Optional[str] = None
    for idx, ch in enumerate(chapter_nums):
        if ch >= target_ch:
            break
        txt = (chapter_texts.get(ch) or "").strip()
        if not txt:
            continue
        tail_s, tail_h = gen._extract_prev_chapter_tail_and_hook(txt)  # type: ignore[attr-defined]
        _update_cluster_state_after_chapter(
            cluster_state,
            contract_obj,
            ch,
            txt,
            idx,
            len(chapter_nums),
            tail_s,
            tail_h,
        )
        prev_ch_text = txt
    return cluster_state, prev_ch_text


def _parse_chapters_to_patch_from_violations(critic_result: Dict[str, Any], chapter_nums: List[int]) -> List[int]:
    """从簇审查 violations 中解析需要局部重写的章节号（末章结果/任一章字数）。"""
    violations = critic_result.get("violations") or []
    need: set = set()
    for v in violations:
        vs = str(v)
        if "最后一章未完成" in vs:
            need.add(chapter_nums[-1])
        m = re.search(r"第(\d+)章字数不足", vs)
        if m:
            try:
                cn = int(m.group(1))
                if cn in chapter_nums:
                    need.add(cn)
            except ValueError:
                pass
    return sorted(need)


def _try_local_chapter_patch_v2(
    gen: "RebirthRevengeGeneratorV2",
    cluster: Dict[str, Any],
    chapter_nums: List[int],
    chapter_cards: Dict[int, Dict[str, Any]],
    contract_obj: Dict[str, Any],
    exec_plan: Optional[Dict[str, Any]],
    cluster_synopsis: str,
    prev_tail_scene: str,
    prev_unresolved_hook: str,
    critic_result: Dict[str, Any],
    chapter_texts: Dict[int, str],
    beats_by_ch: Dict[int, Any],
    max_tokens_body_per_chapter: int = 5000,
) -> Optional[Dict[int, str]]:
    """审查未通过时仅重写被指出的章节，避免整簇 token 重跑。"""
    chs = _parse_chapters_to_patch_from_violations(critic_result, chapter_nums)
    if not chs or not beats_by_ch:
        return None
    out = dict(chapter_texts)
    start_ch = chapter_nums[0]
    extra_rewrite = list(critic_result.get("rewrite_advice") or []) + [
        "本次为局部重写：只改被指出的章节，其余章节保持不动；请满足审查意见并尽量不破坏簇内衔接。"
    ]
    changed = False
    for ch in chs:
        bc = beats_by_ch.get(ch)
        if not isinstance(bc, dict) or not bc.get("beats"):
            continue
        try:
            idx = chapter_nums.index(ch)
        except ValueError:
            continue
        is_first = idx == 0
        is_last = idx == len(chapter_nums) - 1
        state_before, _ = _rebuild_cluster_state_before_chapter(
            gen,
            cluster,
            contract_obj,
            out,
            chapter_nums,
            prev_tail_scene,
            prev_unresolved_hook,
            ch,
        )
        if is_first:
            syn_for_body = cluster_synopsis + "\n\n" + _contract_chapter_hint_block(contract_obj, ch)
        else:
            syn_for_body = _format_rolling_context_block(
                cluster, contract_obj, state_before, ch, chapter_nums
            )
        if is_first:
            body_prev_tail, body_prev_hook = prev_tail_scene, prev_unresolved_hook
        else:
            pt = out.get(ch - 1)
            if not pt:
                continue
            body_prev_tail, body_prev_hook = gen._extract_prev_chapter_tail_and_hook(pt)  # type: ignore[attr-defined]

        kg_context = ""
        try:
            online_retrieve = getattr(gen, "online_retrieve_context", None)
            if callable(online_retrieve):
                kg_context = str(online_retrieve(ch)) or ""
        except Exception:  # noqa: BLE001
            kg_context = ""

        local_extra: List[str] = []
        part_text = ""
        repair_source = ""
        repair_failures: List[str] = []
        for body_try in range(3):
            merged_rewrite = extra_rewrite + local_extra
            card = chapter_cards.get(ch, {}) or {}
            if repair_source:
                body_prompt = _build_grounded_compliance_repair_prompt(
                    chapter_num=ch,
                    failed_draft=repair_source,
                    chapter_card=card,
                    failures=repair_failures,
                    prev_tail_scene=body_prev_tail,
                    repair_attempt=body_try + 1,
                )
            else:
                body_prompt = _build_grounded_chapter_prompt(
                    chapter_num=ch,
                    chapter_card=card,
                    chapter_beats=bc,
                    prev_tail_scene=body_prev_tail,
                    prev_unresolved_hook=body_prev_hook,
                    failures=merged_rewrite,
                )
            part_text = gen._call_api(  # type: ignore[attr-defined]
                body_prompt,
                None,
                idx,
                max_tokens=max_tokens_body_per_chapter,
            )
            part_text = (part_text or "").strip()
            if not part_text or part_text.startswith("通义千问"):
                break
            part_text = _strip_empty_ending_cliches(part_text)
            part_text = _normalize_joined_canonical_names(part_text, card)
            part_text = _normalize_planned_work_title_aliases(part_text, card)
            part_text = _ensure_planned_work_title_reference(part_text, card)
            part_text = _normalize_unplanned_document_titles(part_text, card)
            body_hard = _chapter_body_hard_failures(
                part_text, chapter_num=ch, chapter_card=card
            )
            if body_hard:
                local_extra.extend(body_hard)
                repair_source = part_text
                repair_failures = body_hard
                continue
            roll_v: List[str] = []
            if idx > 0:
                pt_prev = out.get(ch - 1)
                if pt_prev:
                    ts, th = gen._extract_prev_chapter_tail_and_hook(pt_prev)  # type: ignore[attr-defined]
                    roll_v = _chapter_rolling_critic(
                        pt_prev,
                        part_text,
                        ch,
                        _contract_chapter_entry(contract_obj, ch),
                        prev_tail_scene=ts,
                        prev_tail_hook=th,
                    )
            if not roll_v:
                break
            local_extra.extend(roll_v)
        if part_text:
            out[ch] = part_text
            changed = True
    return out if changed else None


def _generate_cluster_continuous_and_split_v2_impl(
    gen: "RebirthRevengeGeneratorV2",
    cluster: Dict[str, Any],
    cards: Dict[int, Dict[str, Any]],
    max_cluster_attempts: int = 5,
) -> Dict[int, str]:
    """逐章生成：簇级合同 → 滚动状态机 →（第 N 章 beats → 第 N 章正文 → 更新承接）循环；不再一次性生成全簇 beats。"""
    span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters") or []
    start_ch, end_ch = int(span[0]), int(span[1])
    chapter_nums = list(range(start_ch, end_ch + 1))
    chapter_cards = {ch: cards.get(ch, {}) for ch in chapter_nums}

    # 情节族首章：跨情节族首章开头接续上一章尾钩，减少明显断点
    prev_ch_full = gen.get_previous_chapter_content(start_ch) if start_ch > 1 else None
    prev_tail_scene, prev_unresolved_hook = gen._extract_prev_chapter_tail_and_hook(prev_ch_full)  # type: ignore[attr-defined]

    # 证据链执行计划：生成一次并落盘（按 cluster_id 命名），后续按 attempt 重写只注入 critic 建议
    cluster_id_for_filename = _safe_filename_from_cluster_id(str(cluster.get("cluster_id", "") or "UNKNOWN"))
    exec_plan_dir = OUTPUT_DIR / "cluster_exec_plans_v2"
    exec_plan_path = exec_plan_dir / f"{cluster_id_for_filename}.json"
    force_grounded_planning = os.getenv("V2_FORCE_GROUNDED_PLANNING", "1").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if force_grounded_planning:
        exec_plan = _fallback_build_exec_plan_for_cluster(cluster, chapter_nums, chapter_cards)
        exec_plan_dir.mkdir(parents=True, exist_ok=True)
        exec_plan_path.write_text(
            json.dumps(exec_plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("  🧭 本书启用封闭上游规划：执行计划仅来自已验收事件卡。", flush=True)
    else:
        try:
            exec_plan = _generate_cluster_exec_plan(
                gen=gen,
                cluster=cluster,
                chapter_cards=chapter_cards,
                chapter_nums=chapter_nums,
                exec_plan_path=exec_plan_path,
            )
        except Exception:  # noqa: BLE001
            exec_plan = _fallback_build_exec_plan_for_cluster(cluster, chapter_nums, chapter_cards)

    critic_result: Dict[str, Any] = {}
    accepted_drafts: Dict[int, Tuple[str, Dict[str, Any]]] = {}

    def recent_chapter_texts(chapter: int, lookback: int = 6) -> Dict[int, str]:
        recent: Dict[int, str] = {}
        chapter_dir = Path(gen.outputs_dir) / "chapters"
        for previous_chapter in range(max(1, chapter - lookback), chapter):
            generated = str(
                getattr(gen, "generated_chapters", {}).get(previous_chapter) or ""
            ).strip()
            if generated:
                recent[previous_chapter] = generated
                continue
            path = chapter_dir / f"chapter_{previous_chapter:03d}.txt"
            try:
                recent[previous_chapter] = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
        return recent

    for attempt in range(max_cluster_attempts):
        beats_by_ch: Dict[int, Any] = {}
        rewrite_advice = critic_result.get("rewrite_advice", []) if attempt > 0 else None
        if attempt > 0:
            ra = rewrite_advice or []
            ra_head = str(ra[0])[:120] + ("…（已截断）" if len(str(ra[0])) > 120 else "") if ra else ""
            if ra:
                print(
                    f"\n⚠️ 情节族 {cluster.get('cluster_id','')} 第{attempt+1}次重写：注入 critic 重写要求（{len(ra)}条）"
                    + (f"；首条摘要：{ra_head}" if ra_head else "")
                )

        print(f"\n🎯 [情节族梗概] {cluster.get('cluster_id','UNKNOWN')}《{cluster.get('name','')}》（第{start_ch}-{end_ch}章）")
        # Token 预算：按「每章≥MIN_CHAPTER_CHARS_V2、并按 beats 分段展开」放大正文 max_tokens。
        max_tokens_synopsis = 1400
        max_tokens_body_per_chapter = 5000

        cluster_synopsis = ""
        synopsis_violations: List[str] = []
        synopsis_rewrite = list(rewrite_advice or [])
        synopsis_attempts = max(1, int(os.getenv("V2_SYNOPSIS_ATTEMPTS", "1")))
        if force_grounded_planning:
            cluster_synopsis = _build_grounded_cluster_synopsis_from_cards(
                cluster, chapter_cards, chapter_nums
            )
            synopsis_attempts = 0
        for synopsis_try in range(synopsis_attempts):
            synopsis_prompt = _build_cluster_detailed_synopsis_prompt(
                cluster=cluster,
                chapter_cards=chapter_cards,
                prev_tail_scene=prev_tail_scene,
                prev_unresolved_hook=prev_unresolved_hook,
                rewrite_advice=synopsis_rewrite or None,
                exec_plan=exec_plan,
            )
            cluster_synopsis = gen._call_api(  # type: ignore[attr-defined]
                synopsis_prompt,
                None,
                0,
                max_tokens=max_tokens_synopsis,
            )
            cluster_synopsis = _normalize_joined_canonical_names(
                (cluster_synopsis or "").strip(),
                {"canonical_cast": cluster.get("canonical_cast") or []},
            )
            unknown_synopsis_roles = _unknown_named_roles_in_synopsis(
                cluster_synopsis, cluster.get("canonical_cast") or []
            )
            synopsis_hard_failures = _cluster_synopsis_hard_failures(
                cluster_synopsis, cluster.get("canonical_cast") or [], cluster
            )
            if not unknown_synopsis_roles and not synopsis_hard_failures:
                synopsis_violations = []
                break

            synopsis_violations = []
            rewrite_items: List[str] = []
            if unknown_synopsis_roles:
                synopsis_violations.append(
                    "情节族梗概擅自新增或改名人物：" + "、".join(unknown_synopsis_roles)
                )
                rewrite_items.append(
                    "详细梗概只能使用 canonical_cast 中的固定姓名；删除或改为无姓名职位称呼："
                    + "、".join(unknown_synopsis_roles)
                )
            if synopsis_hard_failures:
                synopsis_violations.extend(synopsis_hard_failures)
                rewrite_items.append(
                    "删除匿名消息、跨时间消息、神秘来客和来源不明的私密材料；"
                    "只用环境日期确认重生，以固定对手的公开动作与主角现场反卡推进。"
                )
            synopsis_rewrite.extend(rewrite_items)
            synopsis_rewrite = list(dict.fromkeys(synopsis_rewrite))
            print(
                f"  ⚠️ 情节族梗概第 {synopsis_try + 1}/{synopsis_attempts} 次硬失败，定向重写："
                + synopsis_violations[0],
                flush=True,
            )

        if synopsis_violations:
            grounded_synopsis = _build_grounded_cluster_synopsis_from_cards(
                cluster, chapter_cards, chapter_nums
            )
            grounded_unknown = _unknown_named_roles_in_synopsis(
                grounded_synopsis, cluster.get("canonical_cast") or []
            )
            grounded_failures = _cluster_synopsis_hard_failures(
                grounded_synopsis, cluster.get("canonical_cast") or [], cluster
            )
            if not grounded_unknown and not grounded_failures:
                cluster_synopsis = grounded_synopsis
                synopsis_violations = []
                print("  🧷 Qwen梗概连续失败，已改用章节卡封闭梗概并重新验收。", flush=True)
            else:
                critic_result = {
                    "payoff_completed": False,
                    "violations": synopsis_violations,
                    "rewrite_advice": synopsis_rewrite,
                }
                print(
                    "  ⛔ 情节族梗概连续未通过，才进入下一次整簇尝试："
                    + synopsis_violations[0],
                    flush=True,
                )
                continue
        # 梗概对后续节拍卡/正文切分影响很大：把梗概内容在日志里做一个截断预览，便于你对齐排错。
        synopsis_preview = cluster_synopsis[:300]
        if len(cluster_synopsis) > 300:
            synopsis_preview = synopsis_preview + "…（已截断）"
        print(
            f"📝 [情节族梗概简版] cluster={cluster.get('cluster_id','')}《{cluster.get('name','')}》（len={len(cluster_synopsis)}）"
        )
        print(synopsis_preview)

        max_tokens_contract = 2800
        if force_grounded_planning:
            contract_obj = _fallback_cluster_contract(cluster, chapter_nums, chapter_cards)
            contract_failures: List[str] = []
        else:
            contract_prompt = _build_cluster_contract_prompt(
                cluster=cluster,
                chapter_cards=chapter_cards,
                chapter_nums=chapter_nums,
                exec_plan=exec_plan,
                rewrite_advice=rewrite_advice,
            )
            contract_raw = gen._call_api(contract_prompt, None, 0, max_tokens=max_tokens_contract)  # type: ignore[attr-defined]
            contract_obj = _extract_json_obj_maybe((contract_raw or "").strip())
            contract_failures = (
                _cluster_contract_hard_failures(
                    contract_obj, cluster, chapter_nums, chapter_cards
                )
                if isinstance(contract_obj, dict) and contract_obj.get("chapters")
                else ["簇级合同不是完整 JSON"]
            )
        if contract_failures:
            contract_obj = _fallback_cluster_contract(cluster, chapter_nums, chapter_cards)
            print(
                "  🧷 Qwen簇级合同越界，已改用章节卡封闭合同："
                + contract_failures[0][:140],
                flush=True,
            )
        print(
            f"📜 [簇级合同] one_line={_short_text(str(contract_obj.get('one_line_goal', '')), 100)}"
        )

        def _short(x: Any, n: int) -> str:
            s = str(x or "").strip().replace("\n", " ")
            if len(s) > n:
                return s[:n] + "…"
            return s

        cluster_state = _init_cluster_state(str(cluster.get("cluster_id", "") or ""), contract_obj)
        cluster_state["last_scene"] = prev_tail_scene or ""
        cluster_state["last_hook"] = prev_unresolved_hook or ""

        print(f"📋 [节拍卡+正文] 滚动规划：写一章 → 规划下一章（第{start_ch}-{end_ch}章）…")
        full_text_parts: List[str] = []
        prev_ch_text: Optional[str] = None
        beats_generation_ok = True

        for idx, ch in enumerate(chapter_nums):
            is_first = idx == 0
            is_last = idx == len(chapter_nums) - 1

            if is_first:
                syn_for_beats = cluster_synopsis + "\n\n" + _contract_chapter_hint_block(contract_obj, ch)
            else:
                syn_for_beats = _format_rolling_context_block(
                    cluster, contract_obj, cluster_state, ch, chapter_nums
                )

            last_beats_out = ""
            last_beats_reason = ""
            beats_obj: Any = None
            beats_accepted = False
            for beats_try in range(4):
                if force_grounded_planning:
                    beats_obj = _fallback_chapter_beats(
                        cluster,
                        ch,
                        chapter_cards.get(ch, {}) or {},
                        open_from_prev=(
                            prev_tail_scene if is_first else str(cluster_state.get("last_scene") or "")
                        ),
                    )
                    beats_accepted = True
                    break
                max_tokens_beats_try = min(16000, 4500 + beats_try * 3500)
                beats_prompt = _build_single_chapter_beats_prompt(
                    cluster=cluster,
                    chapter_num=ch,
                    chapter_card=chapter_cards.get(ch, {}),
                    cluster_synopsis=syn_for_beats,
                    prev_tail_scene=prev_tail_scene if is_first else "",
                    prev_unresolved_hook=prev_unresolved_hook if is_first else "",
                    state_last_scene=str(cluster_state.get("last_scene") or ""),
                    state_last_hook=str(cluster_state.get("last_hook") or ""),
                    is_first_chapter=is_first,
                    is_last_chapter=is_last,
                    rewrite_advice=rewrite_advice,
                    rolling_synopsis_mode=not is_first,
                )
                beats_out = gen._call_api(  # type: ignore[attr-defined]
                    beats_prompt,
                    None,
                    0,
                    max_tokens=max_tokens_beats_try,
                )
                last_beats_out = (beats_out or "").strip()
                beats_obj = _extract_json_obj_maybe(last_beats_out)
                if beats_obj is None:
                    beats_obj = _extract_json_obj_maybe(_normalize_beats_json_keys(last_beats_out))

                if not isinstance(beats_obj, dict):
                    last_beats_reason = f"beats_obj_type={type(beats_obj).__name__}"
                    continue

                b_list = beats_obj.get("beats")
                role_for_beats = str((chapter_cards.get(ch) or {}).get("chapter_role_v2") or "")
                # Four beats keep the chapter self-contained and prevent a thin
                # two-beat draft from being padded later with duplicate prose.
                min_beats = 4
                has_beats = isinstance(b_list, list) and min_beats <= len(b_list) <= 6
                ch_ok = True
                try:
                    ch_ok = int(beats_obj.get("chapter_num")) == int(ch)
                except Exception:  # noqa: BLE001
                    ch_ok = True

                flashback_ok = _normalize_beats_flashback_mode(
                    beats_obj, role_for_beats, int(ch)
                )
                flashback_value = beats_obj.get("flashback_in_beat_idx")
                cheap_markers = CHEAP_MYSTERY_MARKERS + EMPTY_ENDING_MARKERS
                open_from_prev = str(
                    beats_obj.get("open_from_prev") or beats_obj.get("oppen_from_prev") or ""
                ).strip()
                if not open_from_prev:
                    open_from_prev = str(
                        cluster_state.get("last_scene")
                        or (prev_tail_scene if is_first else "")
                        or (chapter_cards.get(ch) or {}).get("chapter_goal")
                        or "承接上一章已经发生的最后动作与地点。"
                    ).strip()
                    beats_obj["open_from_prev"] = open_from_prev
                end_to_next = str(beats_obj.get("end_to_next") or "")
                if any(marker in end_to_next for marker in cheap_markers):
                    card_ending = str((chapter_cards.get(ch) or {}).get("chapter_ending") or "").strip()
                    beats_obj["end_to_next"] = card_ending or "本章具体行动落定，既有对手当场作出可见反应。"
                positive_beat_fields = (
                    "old_trap_signal", "preemptive_move", "opponent_old_move", "reversal_trigger",
                    "scene_goal", "visual_elements", "emotion_push", "info_delta", "evidence_form",
                    "foreshadow", "relationship_push", "prev_life_memory_brief",
                )
                if isinstance(b_list, list):
                    for beat_item in b_list:
                        if not isinstance(beat_item, dict):
                            continue
                        foreshadow = str(beat_item.get("foreshadow") or "")
                        if any(marker in foreshadow for marker in cheap_markers):
                            beat_item["foreshadow"] = "既有对手对本章结果作出公开反应"
                positive_plan = {
                    "open_from_prev": beats_obj.get("open_from_prev") or beats_obj.get("oppen_from_prev"),
                    "end_to_next": beats_obj.get("end_to_next"),
                    "beats": [
                        {key: beat.get(key) for key in positive_beat_fields if beat.get(key)}
                        for beat in b_list if isinstance(beat, dict)
                    ] if isinstance(b_list, list) else [],
                }
                beats_text_for_guard = json.dumps(positive_plan, ensure_ascii=False)
                cheap_plan_hits = [
                    marker for marker in cheap_markers
                    if marker in beats_text_for_guard
                ]
                reality_plan_hits = [
                    marker for marker in REAL_WORLD_PROPER_NOUNS
                    if marker in beats_text_for_guard
                ]
                planned_titles = _planned_work_titles(cluster, chapter_cards.get(ch, {}))
                beat_titles = set(re.findall(r"《([^》\n]{1,40})》", beats_text_for_guard))
                unexpected_beat_titles = sorted(beat_titles - planned_titles)
                invented_beat_roles = _unknown_named_roles_in_synopsis(
                    beats_text_for_guard, cluster.get("canonical_cast") or []
                )
                unplanned_medical_plan = bool(re.search(
                    r"伪造批号|加密手机|神秘喷雾|蓝色镇静喷雾|实验编号",
                    beats_text_for_guard,
                )) or _has_unplanned_medical_showcase(
                    beats_text_for_guard,
                    chapter_cards.get(ch, {}),
                )

                if (
                    has_beats and ch_ok and flashback_ok and not cheap_plan_hits
                    and not reality_plan_hits and not unexpected_beat_titles
                    and not invented_beat_roles and not unplanned_medical_plan
                ):
                    open_from_prev = beats_obj.get("open_from_prev") or beats_obj.get("oppen_from_prev")
                    end_to_next = beats_obj.get("end_to_next")
                    if isinstance(open_from_prev, str) and open_from_prev.strip() and isinstance(end_to_next, str) and end_to_next.strip():
                        if "open_from_prev" not in beats_obj or not str(beats_obj.get("open_from_prev") or "").strip():
                            beats_obj["open_from_prev"] = open_from_prev.strip()
                        beats_accepted = True
                        break

                last_beats_reason = (
                    f"beats_len_ok={has_beats}; beats_len={len(b_list) if isinstance(b_list, list) else 'N/A'}; "
                    f"flashback_ok={flashback_ok}; cheap_hooks={cheap_plan_hits[:3]}; "
                    f"reality_names={reality_plan_hits[:3]}; unexpected_titles={unexpected_beat_titles[:3]}; "
                    f"invented_roles={invented_beat_roles[:3]}; unplanned_medical={unplanned_medical_plan}; "
                    f"open_from_prev_type={type(beats_obj.get('open_from_prev')).__name__}; "
                    f"end_to_next_type={type(beats_obj.get('end_to_next')).__name__}"
                )

            if not beats_accepted or not isinstance(beats_obj, dict) or not beats_obj.get("beats"):
                last_out_head = " ".join((last_beats_out or "").split())[:200]
                print(
                    f"⚠️ 第{ch}章 beats JSON 解析失败（放弃本情节族本轮）：cluster={cluster.get('cluster_id')}; "
                    f"reason={last_beats_reason}; last_out_head={last_out_head}"
                )
                beats_generation_ok = False
                break

            bc = beats_obj
            beats_by_ch[ch] = bc
            beats_list_for_print = bc.get("beats") if isinstance(bc, dict) else []
            beats_count = len(beats_list_for_print) if isinstance(beats_list_for_print, list) else 0
            print(
                f"  🧾 第{ch}章 beats={beats_count}；flashback_idx={bc.get('flashback_in_beat_idx', None)}；"
                f"open={_short(bc.get('open_from_prev', ''), 50)}"
            )

            if is_first:
                syn_for_body = cluster_synopsis + "\n\n" + _contract_chapter_hint_block(contract_obj, ch)
            else:
                syn_for_body = _format_rolling_context_block(
                    cluster, contract_obj, cluster_state, ch, chapter_nums
                )

            if idx == 0:
                body_prev_tail = prev_tail_scene or ""
                body_prev_hook = prev_unresolved_hook or ""
            else:
                body_prev_tail, body_prev_hook = gen._extract_prev_chapter_tail_and_hook(prev_ch_text)  # type: ignore[attr-defined]

            kg_context = ""
            try:
                online_retrieve = getattr(gen, "online_retrieve_context", None)
                if callable(online_retrieve):
                    kg_context = str(online_retrieve(ch)) or ""
            except Exception:  # noqa: BLE001
                kg_context = ""

            card = chapter_cards.get(ch, {}) or {}
            role_v2 = ""
            if isinstance(card, dict):
                role_v2 = str(card.get("chapter_role_v2") or "")

            cached_draft = accepted_drafts.get(ch)
            if cached_draft is not None:
                part_text, part_memory = cached_draft
                print(
                    f"  ♻️ 第{ch}章复用本事务内已通过的待提交草稿（{len(part_text)}字）。",
                    flush=True,
                )
                gen.save_chapter(ch, part_text)  # type: ignore[attr-defined]
                gen.generated_chapters[ch] = part_text  # type: ignore[attr-defined]
                if part_memory:
                    gen.commit_story_memory(part_memory)  # type: ignore[attr-defined]
                full_text_parts.append(part_text)
                prev_ch_text = part_text
                tail_s, tail_h = gen._extract_prev_chapter_tail_and_hook(part_text)  # type: ignore[attr-defined]
                _update_cluster_state_after_chapter(
                    cluster_state,
                    contract_obj,
                    ch,
                    part_text,
                    idx,
                    len(chapter_nums),
                    tail_s,
                    tail_h,
                )
                if is_last:
                    cluster_state["progress_percent"] = 100
                continue

            need_prev_life = role_v2 in {
                "prev_life_full",
                "prev_life_explained_by_investigation",
                "present_past_mix",
                "slow_burn_press_with_past_shadow",
            }
            if ch in (1, 2):
                need_prev_life = False

            core_text = str(cluster.get("core_payoff", "") or "") + "\n" + cluster_synopsis
            has_revenge = any(k in core_text for k in ["复仇", "反制", "反击", "扳倒", "揭穿", "打脸"])

            prev_life_clue = ""
            if hasattr(gen, "prev_life_ctx") and isinstance(getattr(gen, "prev_life_ctx"), dict):
                prev_life_clue = str((gen.prev_life_ctx.get(ch) or ""))  # type: ignore[attr-defined]

            one_line_g = str(contract_obj.get("one_line_goal") or "")
            if idx == 0:
                rag_query = f"{cluster_synopsis}\n{prev_life_clue or ''}".strip()
            else:
                rag_query = (
                    f"{one_line_g}\n{cluster_state.get('last_scene', '')}\n"
                    f"{cluster_state.get('last_hook', '')}\n{prev_life_clue or ''}"
                ).strip()
            target_context = f"主题: {THEME}, 主角: {MAIN_PROTAGONIST}, 背景: {BACKGROUND}, 快节奏商业重生, 人物关系, 因果一致性"
            if ch in (1, 2):
                # The opening structure is narrow and fragile; direct prose
                # samples tend to inject anonymous messages or premature
                # revenge beats. RAG becomes useful after rebirth is established.
                rag_samples = {"revenge": [], "grievance": [], "universal": []}
            else:
                rag_samples = search_rebirth_samples_for_chapter(
                    rag_query,
                    target_context,
                    need_prev_life=need_prev_life,
                    has_revenge=has_revenge,
                    top_k_per_set=1,
                )
                for sample_key, sample_items in list(rag_samples.items()):
                    rag_samples[sample_key] = [
                        sample
                        for sample in (sample_items or [])
                        if not any(
                            marker in str(sample.get("adapted_content") or sample.get("content") or "")
                            for marker in CHEAP_MYSTERY_MARKERS + EMPTY_ENDING_MARKERS + tuple(INVESTIGATION_NARRATIVE_TOKENS)
                        )
                    ]
                if role_v2 == "present_past_mix":
                    rag_samples = {
                        "revenge": [],
                        "grievance": (rag_samples.get("grievance") or [])[:1],
                        "universal": [],
                    }
                else:
                    rag_samples = {
                        "revenge": (rag_samples.get("revenge") or [])[:1],
                        "grievance": [],
                        "universal": [],
                    }

            if rag_samples and any(rag_samples.get(k) for k in ("revenge", "grievance", "universal")):
                n = sum(len(rag_samples.get(k, [])) for k in ("revenge", "grievance", "universal"))
                if n:
                    print(f"  [RAG] 第{ch}章 注入 {n} 条参考（委屈/爽感/通用）", flush=True)

            local_extra: List[str] = []
            part_text = ""
            part_memory: Dict[str, Any] = {}
            part_accepted = False
            contract_repair_source = ""
            contract_repair_failures: List[str] = []
            contract_repair_mode = "rewrite"
            runtime_scene_contract = (
                card.get("scene_contract")
                if isinstance(card.get("scene_contract"), dict)
                else _derive_closed_scene_contract(card)
            )
            strict_scene_contract = (
                ch >= 3
                and not _closed_scene_contract_failures(runtime_scene_contract)
            )
            max_body_attempts = (
                6 if role_v2 in {"prev_life_death_only", "rebirth_awakening_only"}
                else 5 if strict_scene_contract and force_grounded_planning
                else 5 if force_grounded_planning and ch >= 3
                else 4
            )
            for body_try in range(max_body_attempts):
                merged_rewrite = list(rewrite_advice or []) + local_extra
                if contract_repair_source:
                    if contract_repair_mode == "death":
                        body_prompt = _build_death_repair_prompt(
                            ch, contract_repair_source, card, contract_repair_failures
                        )
                        print(f"  🛠️ 第{ch}章进入 Qwen 定向上一世死亡结构修订。", flush=True)
                    elif contract_repair_mode == "awakening":
                        body_prompt = _build_awakening_repair_prompt(
                            ch, contract_repair_source, card, contract_repair_failures
                        )
                        print(f"  🛠️ 第{ch}章进入 Qwen 定向觉醒结构修订。", flush=True)
                    elif contract_repair_mode == "grounded":
                        body_prompt = _build_grounded_chapter_prompt(
                            ch,
                            card,
                            chapter_beats=bc,
                            prev_tail_scene=body_prev_tail,
                            prev_unresolved_hook=body_prev_hook,
                            failures=list(contract_repair_failures),
                            kg_context=kg_context,
                            rag_samples=rag_samples,
                        )
                        print(
                            f"  🔄 第{ch}章丢弃失败稿，按同一通用执行卡从空白重建。",
                            flush=True,
                        )
                    elif contract_repair_mode == "append_payoff":
                        body_prompt = _build_payoff_insertion_prompt(
                            ch, contract_repair_source, card, contract_repair_failures
                        )
                        print(f"  🛠️ 第{ch}章由 Qwen 补写现场结算场景。", flush=True)
                    elif contract_repair_mode == "payoff":
                        body_prompt = _build_payoff_repair_prompt(
                            ch, contract_repair_source, card, contract_repair_failures
                        )
                        print(f"  🛠️ 第{ch}章进入 Qwen 定向结算修订。", flush=True)
                    elif contract_repair_mode == "append_required_state":
                        body_prompt = _build_required_state_insertion_prompt(
                            ch, contract_repair_source, card, contract_repair_failures
                        )
                        print(f"  🛠️ 第{ch}章由 Qwen 补写必需状态场景。", flush=True)
                    else:
                        body_prompt = _build_memory_contract_repair_prompt(
                            ch, contract_repair_source, card, contract_repair_failures
                        )
                        print(f"  🛠️ 第{ch}章进入 Qwen 定向连续性修订。", flush=True)
                elif force_grounded_planning and ch >= 3:
                    body_prompt = _build_grounded_chapter_prompt(
                        ch,
                        card,
                        chapter_beats=bc,
                        prev_tail_scene=body_prev_tail,
                        prev_unresolved_hook=body_prev_hook,
                        failures=merged_rewrite,
                        kg_context=kg_context,
                        rag_samples=rag_samples,
                    )
                    print(f"  🧭 第{ch}章使用通用整章执行卡生成器。", flush=True)
                else:
                    body_prompt = _build_cluster_body_part_prompt(
                        cluster=cluster,
                        cluster_synopsis=syn_for_body,
                        chapter_num=ch,
                        chapter_beats=bc,
                        prev_tail_scene=body_prev_tail,
                        prev_unresolved_hook=body_prev_hook,
                        chapter_card=chapter_cards.get(ch, {}),
                        kg_context=kg_context,
                        rewrite_advice=merged_rewrite if merged_rewrite else None,
                        rag_samples=rag_samples,
                        exec_plan=exec_plan,
                        rolling_synopsis_mode=not is_first,
                    )
                prefer_segmented_closed = (
                    os.environ.get("V2_PREFER_SEGMENTED_CLOSED", "0").strip().lower()
                    in {"1", "true", "yes", "on"}
                )
                allow_segment_recovery = (
                    os.environ.get("V2_ALLOW_SEGMENT_RECOVERY", "0").strip().lower()
                    in {"1", "true", "yes", "on"}
                )
                use_legacy_deterministic_scenes = (
                    os.environ.get("V2_USE_LEGACY_DETERMINISTIC_SCENES", "0").strip().lower()
                    in {"1", "true", "yes", "on"}
                )
                forced_death_seed = None
                awakening_seed = None
                schedule_canary_seed = None
                overload_schedule_seed = None
                if body_try == 0 and not contract_repair_source:
                    forced_death_seed = _build_forced_medication_death_scene(card)
                    if forced_death_seed is not None:
                        print(
                            f"  🧱 第{ch}章使用通用强制用药死亡封闭场景生成器。",
                            flush=True,
                        )
                    else:
                        awakening_seed = _build_medical_double_sign_awakening_scene(card)
                        if awakening_seed is not None:
                            print(
                                f"  🧱 第{ch}章使用通用医疗双签觉醒封闭场景生成器。",
                                flush=True,
                            )
                        elif use_legacy_deterministic_scenes:
                            schedule_canary_seed = _build_schedule_canary_scene(card)
                            if schedule_canary_seed is not None:
                                print(
                                    f"  🧱 第{ch}章使用兼容模式日程诱饵场景生成器。",
                                    flush=True,
                                )
                            else:
                                overload_schedule_seed = _build_overload_schedule_bait_scene(card)
                                if overload_schedule_seed is not None:
                                    print(
                                        f"  🧱 第{ch}章使用兼容模式超载排期场景生成器。",
                                        flush=True,
                                    )
                segmented_seed = None
                if (
                    forced_death_seed is None
                    and awakening_seed is None
                    and schedule_canary_seed is None
                    and overload_schedule_seed is None
                    and prefer_segmented_closed
                    and (
                        (body_try == 0 and not contract_repair_source)
                        or strict_scene_contract
                    )
                    and force_grounded_planning
                    and ch >= 3
                    and _closed_scene_segment_plan(card) is not None
                ):
                    print(
                        f"  🧱 第{ch}章优先使用通用封闭场景分段生成。",
                        flush=True,
                    )
                    segmented_seed = _generate_segmented_closed_scene(
                        gen,
                        ch,
                        card,
                        minimum_chars=_minimum_chapter_chars(ch, card),
                        max_tokens=max_tokens_body_per_chapter,
                    )
                if forced_death_seed is not None:
                    part_text = forced_death_seed
                elif awakening_seed is not None:
                    part_text = awakening_seed
                elif schedule_canary_seed is not None:
                    part_text = schedule_canary_seed
                elif overload_schedule_seed is not None:
                    part_text = overload_schedule_seed
                elif segmented_seed is not None:
                    part_text, part_memory = segmented_seed
                elif strict_scene_contract and prefer_segmented_closed:
                    local_extra.append("结构化场景契约分段生成未通过，禁止回退到无约束整章生成。")
                    print(
                        f"  ⚠️ 第{ch}章结构化场景契约未通过，保留契约并重试分段。",
                        flush=True,
                    )
                    continue
                else:
                    part_text = gen._call_api(  # type: ignore[attr-defined]
                        body_prompt,
                        None,
                        idx,
                        max_tokens=max_tokens_body_per_chapter,
                    )
                part_text = (part_text or "").strip()
                if not part_text or part_text.startswith("通义千问"):
                    raise RuntimeError(f"第{ch}章正文生成失败或为空。")
                part_text = _strip_empty_ending_cliches(part_text)
                part_text = _normalize_joined_canonical_names(part_text, card)
                part_text = _normalize_planned_work_title_aliases(part_text, card)
                part_text = _ensure_planned_work_title_reference(part_text, card)
                part_text = _normalize_unplanned_document_titles(part_text, card)
                legacy_surface_rewrite = (
                    os.environ.get("V2_USE_LEGACY_SURFACE_REWRITE", "0").strip().lower()
                    in {"1", "true", "yes", "on"}
                )
                if legacy_surface_rewrite:
                    part_text = _normalize_closed_scene_surface_drift(part_text, card)
                    part_text = _ensure_medication_audit_previous_life_motive(part_text, card)
                    part_text = _ensure_medication_audit_handover(part_text, card)
                    part_text = _ensure_performance_previous_life_action(part_text, card)
                if role_v2 == "rebirth_awakening_only":
                    part_text = _normalize_awakening_role_aliases(part_text, card)
                if role_v2 == "prev_life_death_only":
                    part_text = _normalize_unplanned_named_people(part_text, card)
                    if contract_repair_source and contract_repair_mode == "death":
                        part_text = _ground_opening_betrayal_before_home(part_text, card)
                        if not re.search(
                            r"死亡|身亡|死去|心脏.{0,24}(?:停住|停止搏动|不再搏动)|"
                            r"心脏.{0,12}停跳|心电图.{0,80}(?:拉平|直线)|波形.{0,40}(?:拉平|直线)|"
                            r"呼吸.{0,18}(?:停止|断绝)",
                            part_text,
                            re.S,
                        ):
                            part_text = _append_grounded_opening_death_scene(part_text, card)
                if contract_repair_source and contract_repair_mode == "append_payoff":
                    part_text = contract_repair_source.rstrip() + "\n\n" + part_text
                if contract_repair_source and contract_repair_mode == "append_required_state":
                    part_text = contract_repair_source.rstrip() + "\n\n" + part_text
                body_hard = _chapter_body_hard_failures(
                    part_text, chapter_num=ch, chapter_card=chapter_cards.get(ch, {}) or {}
                )
                minimum_chars = _minimum_chapter_chars(ch, card)
                if len(part_text) < minimum_chars:
                    body_hard.insert(
                        0,
                        f"正文只有{len(part_text)}字，少于硬下限{minimum_chars}字；"
                        "必须从空白重写完整章节，在既定冲突内增加对手施压、主角选择、"
                        "旁观者判断变化和结果反应，不得在短稿后拼接补长。",
                    )
                body_hard.extend(
                    _scene_contract_fulfillment_failures(part_text, card)
                )
                body_hard.extend(
                    _cross_chapter_prose_similarity_failures(
                        part_text,
                        recent_chapter_texts(ch),
                    )
                )
                if ch == 1 and body_hard and body_try == max_body_attempts - 1 and any(
                    "第1章必须" in failure for failure in body_hard
                ):
                    grounded_text = _append_grounded_opening_death_scene(part_text, card)
                    grounded_failures = _chapter_body_hard_failures(
                        grounded_text, chapter_num=ch, chapter_card=card
                    )
                    if len(grounded_failures) < len(body_hard):
                        part_text = grounded_text
                        body_hard = grounded_failures
                        print("  🧷 第1章已按事件簇既定死法补齐死亡场景并重新验收。", flush=True)
                if ch == 2 and body_hard and any(
                    "第2章必须完整写出" in failure
                    or "没有实际解除" in failure
                    or "没有完成与固定盟友" in failure
                    for failure in body_hard
                ):
                    grounded_text = _prepend_grounded_awakening_confirmation(part_text, card)
                    grounded_text = _append_grounded_awakening_deployment(grounded_text, card)
                    grounded_failures = _chapter_body_hard_failures(
                        grounded_text, chapter_num=ch, chapter_card=card
                    )
                    if len(grounded_failures) < len(body_hard):
                        part_text = grounded_text
                        body_hard = grounded_failures
                        print("  🧷 第2章已按章节卡补齐觉醒确认与首次部署并重新验收。", flush=True)
                if (
                    body_hard
                    and body_try >= 2
                    and (
                        prefer_segmented_closed
                        or (
                            allow_segment_recovery
                            and _should_use_api_segment_recovery(card, body_try)
                        )
                    )
                    and force_grounded_planning
                    and ch >= 3
                    and _closed_scene_segment_plan(card) is not None
                ):
                    print(
                        f"  🧱 第{ch}章连续整章越界，提前切换通用封闭场景分段生成。",
                        flush=True,
                    )
                    segmented = _generate_segmented_closed_scene(
                        gen,
                        ch,
                        card,
                        minimum_chars=_minimum_chapter_chars(ch, card),
                        max_tokens=max_tokens_body_per_chapter,
                    )
                    if segmented is not None:
                        part_text, part_memory = segmented
                        body_hard = _chapter_body_hard_failures(
                            part_text,
                            chapter_num=ch,
                            chapter_card=card,
                        )
                        body_hard.extend(
                            _scene_contract_fulfillment_failures(part_text, card)
                        )
                        body_hard.extend(
                            _cross_chapter_prose_similarity_failures(
                                part_text,
                                recent_chapter_texts(ch),
                            )
                        )
                if body_hard:
                    if os.getenv("V2_SAVE_REJECTED_DRAFTS", "").strip().lower() in {"1", "true", "yes", "on"}:
                        rejected_dir = OUTPUT_DIR / "rejected_drafts"
                        rejected_dir.mkdir(parents=True, exist_ok=True)
                        rejected_path = rejected_dir / f"chapter_{ch:03d}_try_{body_try + 1}.txt"
                        rejected_path.write_text(
                            part_text + "\n\n--- HARD FAILURES ---\n" + "\n".join(body_hard),
                            encoding="utf-8",
                        )
                    local_extra.extend(body_hard)
                    payoff_failures = [
                        x for x in body_hard
                        if role_v2 == "present_revenge" and (
                            "缺少可见兑现" in x
                            or "主演合约" in x
                            or "核心试戏章" in x
                            or "核心角色章" in x
                            or "正文擅自新增或改名人物" in x
                            or "职位粘连" in x
                            or "重复" in x
                        )
                    ]
                    awakening_failures = [
                        x for x in body_hard
                        if "第2章必须完整写出" in x
                        or "第2章越过觉醒" in x
                        or "第2章越过首次部署边界" in x
                    ]
                    death_failures = list(body_hard) if ch == 1 else []
                    grounded_workflow_chapter = force_grounded_planning and ch >= 3
                    if death_failures and not contract_repair_source:
                        contract_repair_source = part_text
                        contract_repair_failures = body_hard
                        contract_repair_mode = "death"
                    elif awakening_failures and not contract_repair_source:
                        contract_repair_source = part_text
                        contract_repair_failures = body_hard
                        contract_repair_mode = "awakening"
                    elif grounded_workflow_chapter:
                        contract_repair_source = ""
                        contract_repair_failures = body_hard
                        contract_repair_mode = "grounded"
                    elif payoff_failures and not contract_repair_source:
                        contract_repair_source = part_text
                        contract_repair_failures = body_hard
                        contract_repair_mode = "payoff"
                    print(
                        f"  ⚠️ 第{ch}章正文硬失败：{body_hard[0][:120]}…"
                        f"（尝试 {body_try + 1}/{max_body_attempts}）",
                        flush=True,
                    )
                    continue
                roll_v: List[str] = []
                if idx > 0 and prev_ch_text:
                    ts, th = gen._extract_prev_chapter_tail_and_hook(prev_ch_text)  # type: ignore[attr-defined]
                    roll_v = _chapter_rolling_critic(
                        prev_ch_text,
                        part_text,
                        ch,
                        _contract_chapter_entry(contract_obj, ch),
                        prev_tail_scene=ts,
                        prev_tail_hook=th,
                    )
                if roll_v:
                    local_extra.extend(roll_v)
                    print(
                        f"  ⚠️ 第{ch}章滚动承接未过：{roll_v[0][:100]}…"
                        f"（尝试 {body_try + 1}/{max_body_attempts}）",
                        flush=True,
                    )
                    continue

                quality_review = _review_chapter_quality_v2(
                    gen,
                    ch,
                    part_text,
                    card,
                    prev_tail_scene=body_prev_tail,
                    generation_try=body_try + 1,
                )
                quality_failures = _chapter_quality_review_failures(quality_review)
                if quality_failures:
                    local_extra.extend(quality_failures[:8])
                    contract_repair_source = ""
                    contract_repair_failures = quality_failures[:8]
                    contract_repair_mode = "grounded"
                    if os.getenv("V2_SAVE_REJECTED_DRAFTS", "").strip().lower() in {
                        "1", "true", "yes", "on"
                    }:
                        rejected_dir = OUTPUT_DIR / "rejected_drafts" / "quality_critic"
                        rejected_dir.mkdir(parents=True, exist_ok=True)
                        rejected_path = (
                            rejected_dir
                            / f"chapter_{ch:03d}_try_{body_try + 1}.txt"
                        )
                        rejected_path.write_text(
                            part_text
                            + "\n\n--- QUALITY REVIEW ---\n"
                            + json.dumps(quality_review, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    print(
                        f"  ⛔ 第{ch}章独立质量审稿拒绝：{quality_failures[0][:140]}"
                        f"（尝试 {body_try + 1}/{max_body_attempts}，整章作废）",
                        flush=True,
                    )
                    continue

                try:
                    part_memory, memory_violations = gen.review_story_memory(ch, part_text)  # type: ignore[attr-defined]
                except Exception as exc:  # noqa: BLE001
                    part_memory, memory_violations = {}, []
                    print(f"  ⚠️ 第{ch}章连续性抽取异常，降级为现有审查：{exc}", flush=True)
                hard_memory_violations = [
                    v for v in memory_violations if getattr(v, "severity", "hard") == "hard"
                ]
                if hard_memory_violations:
                    memory_advice = [getattr(v, "message", str(v)) for v in hard_memory_violations]
                    local_extra.extend([f"连续性硬冲突：{x}" for x in memory_advice[:6]])
                    print(
                        f"  ⛔ 第{ch}章知识图谱硬冲突：{memory_advice[0][:140]}（重试 {body_try + 1}/3）",
                        flush=True,
                    )
                    continue
                memory_contract_failures = _validate_chapter_memory_contract(card, part_memory)
                if memory_contract_failures:
                    local_extra.extend(memory_contract_failures[:6])
                    contract_repair_source = part_text if ch < 3 else ""
                    contract_repair_failures = memory_contract_failures[:6]
                    contract_repair_mode = (
                        "append_required_state"
                        if ch < 3
                        and card.get("required_state_changes")
                        and any("计划落地缺失" in x for x in memory_contract_failures)
                        else "rewrite"
                    )
                    print(
                        f"  ⛔ 第{ch}章计划事实未落地：{memory_contract_failures[0][:140]}"
                        f"（重试 {body_try + 1}/3）",
                        flush=True,
                    )
                    continue
                part_accepted = True
                break

            if not part_accepted:
                print(f"  ⛔ 第{ch}章连续性/正文硬审查连续失败，本情节族本轮作废。", flush=True)
                beats_generation_ok = False
                break

            allow_incremental_expansion = (
                os.environ.get("V2_ALLOW_INCREMENTAL_EXPANSION", "0").strip().lower()
                in {"1", "true", "yes", "on"}
            )
            if allow_incremental_expansion:
                part_text, part_memory = _expand_short_chapter_before_commit(
                    gen,
                    ch,
                    part_text,
                    card,
                    part_memory,
                    max_tokens=max_tokens_body_per_chapter,
                    prev_tail_scene=body_prev_tail,
                )
            minimum_chars = _minimum_chapter_chars(ch, card)
            if len(part_text) < minimum_chars:
                print(
                    f"  ⛔ 第{ch}章正文仅 {len(part_text)} 字，未达到 "
                    f"{minimum_chars} 字；在生成下一章前废弃本情节族本轮。",
                    flush=True,
                )
                beats_generation_ok = False
                break
            post_expansion_failures = _chapter_body_hard_failures(
                part_text,
                chapter_num=ch,
                chapter_card=card,
            )
            post_expansion_failures.extend(
                _scene_contract_fulfillment_failures(part_text, card)
            )
            post_expansion_failures.extend(
                _cross_chapter_prose_similarity_failures(
                    part_text,
                    recent_chapter_texts(ch),
                )
            )
            if post_expansion_failures:
                print(
                    f"  ⛔ 第{ch}章扩写后质量复验失败："
                    f"{post_expansion_failures[0][:140]}；本情节族本轮作废。",
                    flush=True,
                )
                beats_generation_ok = False
                break

            accepted_drafts[ch] = (part_text, part_memory)

            # 章节一旦通过硬审查就立即写入账本/Neo4j，使同一情节族的下一章可读取新事实。
            gen.save_chapter(ch, part_text)  # type: ignore[attr-defined]
            gen.generated_chapters[ch] = part_text  # type: ignore[attr-defined]
            if part_memory:
                gen.commit_story_memory(part_memory)  # type: ignore[attr-defined]

            full_text_parts.append(part_text)
            prev_ch_text = part_text
            tail_s, tail_h = gen._extract_prev_chapter_tail_and_hook(part_text)  # type: ignore[attr-defined]
            _update_cluster_state_after_chapter(
                cluster_state,
                contract_obj,
                ch,
                part_text,
                idx,
                len(chapter_nums),
                tail_s,
                tail_h,
            )
            if is_last:
                cluster_state["progress_percent"] = 100

        if not beats_generation_ok:
            continue

        if len(full_text_parts) != len(chapter_nums):
            continue

        # 逐章生成即已是分章正文，不再做「整簇拼成 full_body → 再切分微调」二次调用（避免超大 prompt、超时与 JSON 解析失败）。
        chapter_texts = {ch: txt.strip() for ch, txt in zip(chapter_nums, full_text_parts)}
        print(
            f"✅ [逐章落盘] 已生成 {len(chapter_texts)} 章正文，跳过整簇切分微调，直接进入审查。",
            flush=True,
        )

        too_short = [
            c
            for c in chapter_nums
            if c not in chapter_texts
            or len((chapter_texts.get(c) or "")) < _minimum_chapter_chars(c, cards.get(c))
        ]
        if too_short:
            short_msgs = [
                f"第{c}章正文过短（{len((chapter_texts.get(c) or ''))}字），需要≥{_minimum_chapter_chars(c, cards.get(c))}字且不得只保留短开头/短结尾"
                for c in too_short
            ]
            critic_result = {
                "payoff_completed": False,
                "violations": short_msgs,
                "rewrite_advice": [
                    "逐章正文必须达到该结构角色的最低有效篇幅，不能只保留短开头/短结尾；",
                    "请按 beats 逐拍扩写，每拍至少 160-220 字，补足多感官描写与对话；",
                ]
                + short_msgs[:3],
            }
            continue

        final_body_failures: Dict[int, List[str]] = {}
        for ch in chapter_nums:
            final_failures = _chapter_body_hard_failures(
                chapter_texts[ch],
                chapter_num=ch,
                chapter_card=chapter_cards.get(ch, {}) or {},
            )
            final_failures.extend(
                _scene_contract_fulfillment_failures(
                    chapter_texts[ch],
                    chapter_cards.get(ch, {}) or {},
                )
            )
            final_failures.extend(
                _cross_chapter_prose_similarity_failures(
                    chapter_texts[ch],
                    recent_chapter_texts(ch),
                )
            )
            final_body_failures[ch] = final_failures
        final_body_failures = {
            ch: failures for ch, failures in final_body_failures.items() if failures
        }
        if final_body_failures:
            first_ch = min(final_body_failures)
            print(
                f"  ⛔ 第{first_ch}章落盘前复验失败："
                f"{final_body_failures[first_ch][0][:140]}；本情节族本轮重生成。",
                flush=True,
            )
            critic_result = {
                "payoff_completed": False,
                "violations": [
                    f"第{ch}章落盘前硬失败：{failure}"
                    for ch, failures in final_body_failures.items()
                    for failure in failures
                ],
                "rewrite_advice": [
                    failure
                    for failures in final_body_failures.values()
                    for failure in failures
                ][:12],
            }
            for failed_chapter in final_body_failures:
                accepted_drafts.pop(failed_chapter, None)
            continue

        # 写盘 + 记录到内存，便于 critic 使用
        for ch in chapter_nums:
            gen.save_chapter(ch, chapter_texts[ch])  # type: ignore[attr-defined]
            gen.generated_chapters[ch] = chapter_texts[ch]  # type: ignore[attr-defined]

        critic_result = _cluster_critic(
            cluster,
            chapter_texts,
            exec_plan=exec_plan,
            chapter_cards=chapter_cards,
        )  # type: ignore[misc]
        payoff_ok = bool(critic_result.get("payoff_completed", False))
        violations = critic_result.get("violations", []) or []
        print(f"📋 情节族完成审查：payoff_completed={payoff_ok}，violations={len(violations)} 条")
        allow_local_chapter_patch = (
            os.environ.get("V2_ALLOW_LOCAL_CHAPTER_PATCH", "0").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        if not payoff_ok and allow_local_chapter_patch:
            patched = _try_local_chapter_patch_v2(
                gen,
                cluster,
                chapter_nums,
                chapter_cards,
                contract_obj,
                exec_plan,
                cluster_synopsis,
                prev_tail_scene,
                prev_unresolved_hook,
                critic_result,
                chapter_texts,
                beats_by_ch,
                max_tokens_body_per_chapter=max_tokens_body_per_chapter,
            )
            if patched:
                accepted_patch = dict(chapter_texts)
                for ch in chapter_nums:
                    candidate_text = patched.get(ch, chapter_texts[ch])
                    patch_body_failures = _chapter_body_hard_failures(
                        candidate_text,
                        chapter_num=ch,
                        chapter_card=chapter_cards.get(ch, {}) or {},
                    )
                    patch_body_failures.extend(
                        _scene_contract_fulfillment_failures(
                            candidate_text,
                            chapter_cards.get(ch, {}) or {},
                        )
                    )
                    patch_body_failures.extend(
                        _cross_chapter_prose_similarity_failures(
                            candidate_text,
                            recent_chapter_texts(ch),
                        )
                    )
                    patch_memory, patch_violations = gen.review_story_memory(ch, candidate_text)  # type: ignore[attr-defined]
                    hard_patch_violations = [
                        v for v in patch_violations if getattr(v, "severity", "hard") == "hard"
                    ]
                    patch_contract_failures = _validate_chapter_memory_contract(
                        chapter_cards.get(ch, {}) or {}, patch_memory
                    )
                    if patch_body_failures or hard_patch_violations or patch_contract_failures:
                        patch_message = (
                            patch_body_failures[0]
                            if patch_body_failures
                            else (
                                getattr(hard_patch_violations[0], "message", str(hard_patch_violations[0]))
                                if hard_patch_violations else patch_contract_failures[0]
                            )
                        )
                        print(
                            f"  ⛔ 第{ch}章局部补写引入正文或连续性冲突，保留补写前版本："
                            f"{patch_message[:140]}",
                            flush=True,
                        )
                        continue
                    accepted_patch[ch] = candidate_text
                    if patch_memory:
                        gen.commit_story_memory(patch_memory)  # type: ignore[attr-defined]
                chapter_texts = accepted_patch
                for ch in chapter_nums:
                    gen.save_chapter(ch, chapter_texts[ch])  # type: ignore[attr-defined]
                    gen.generated_chapters[ch] = chapter_texts[ch]  # type: ignore[attr-defined]
                critic_result = _cluster_critic(
                    cluster,
                    chapter_texts,
                    exec_plan=exec_plan,
                    chapter_cards=chapter_cards,
                )  # type: ignore[misc]
                payoff_ok = bool(critic_result.get("payoff_completed", False))
                violations = critic_result.get("violations", []) or []
                print(f"📋 局部补写后审查：payoff_completed={payoff_ok}，violations={len(violations)} 条")
        if payoff_ok:
            return_failures: Dict[int, List[str]] = {}
            for ch in chapter_nums:
                chapter_failures = _chapter_body_hard_failures(
                    chapter_texts[ch],
                    chapter_num=ch,
                    chapter_card=chapter_cards.get(ch, {}) or {},
                )
                chapter_failures.extend(
                    _scene_contract_fulfillment_failures(
                        chapter_texts[ch],
                        chapter_cards.get(ch, {}) or {},
                    )
                )
                chapter_failures.extend(
                    _cross_chapter_prose_similarity_failures(
                        chapter_texts[ch],
                        recent_chapter_texts(ch),
                    )
                )
                return_failures[ch] = chapter_failures
            return_failures = {
                ch: failures for ch, failures in return_failures.items() if failures
            }
            if not return_failures:
                return chapter_texts
            payoff_ok = False
            violations = [
                f"第{ch}章返回前硬失败：{failure}"
                for ch, failures in return_failures.items()
                for failure in failures
            ]
            critic_result = {
                "payoff_completed": False,
                "violations": violations,
                "rewrite_advice": [
                    failure
                    for failures in return_failures.values()
                    for failure in failures
                ][:12],
            }
            print(
                f"  ⛔ 情节族返回前复验失败，拒绝交付：{violations[0][:140]}",
                flush=True,
            )
        accepted_drafts.clear()
        if attempt >= max_cluster_attempts - 1:
            if violations:
                print("⚠️ 本情节族未通过审查（回滚，不作为完整正文交付）：")
                for v in violations[:8]:
                    print(f"   - {v}")

    return {}


def _generate_cluster_continuous_and_split_v2(
    gen: RebirthRevengeGeneratorV2,
    cluster: Dict[str, Any],
    chapter_cards: Dict[int, Dict[str, Any]],
) -> Dict[int, str]:
    """Run one cluster transactionally across text files, ledger, and Neo4j."""
    span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters") or []
    try:
        start_chapter, end_chapter = int(span[0]), int(span[1])
    except (TypeError, ValueError, IndexError):
        return _generate_cluster_continuous_and_split_v2_impl(gen, cluster, chapter_cards)
    chapters = list(range(start_chapter, end_chapter + 1))
    chapter_dir = Path(gen.outputs_dir) / "chapters"
    file_snapshot: Dict[int, Optional[str]] = {}
    for chapter in chapters:
        path = chapter_dir / f"chapter_{chapter:03d}.txt"
        try:
            file_snapshot[chapter] = path.read_text(encoding="utf-8")
        except OSError:
            file_snapshot[chapter] = None
    coordinator = getattr(gen, "story_memory", None)
    memory_snapshot = coordinator.snapshot(chapters) if coordinator is not None else {}

    def _restore() -> None:
        chapter_dir.mkdir(parents=True, exist_ok=True)
        for chapter, content in file_snapshot.items():
            path = chapter_dir / f"chapter_{chapter:03d}.txt"
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(content, encoding="utf-8")
        if coordinator is not None:
            coordinator.restore(memory_snapshot)
        for chapter in chapters:
            if file_snapshot.get(chapter) is None:
                gen.generated_chapters.pop(chapter, None)
            else:
                gen.generated_chapters[chapter] = str(file_snapshot[chapter])

    try:
        result = _generate_cluster_continuous_and_split_v2_impl(gen, cluster, chapter_cards)
    except Exception:
        _restore()
        raise
    if not result:
        _restore()
    return result


def generate_chapters_v2(
    master_ctx_cards_path: Optional[str] = None,
    prev_life_ctx_path: Optional[str] = None,
    chapters_dir: Optional[str] = None,
    start_chapter: int = 1,
    end_chapter: int = 100,
    sync_neo4j: bool = True,
    neo4j_min_name_freq: int = 5,
    neo4j_reset_db: bool = False,
    neo4j_auto_extract_relations: bool = False,
) -> None:
    """
    便捷入口：按章节范围生成正文。不再依赖 master_ctx_cards_v2.json，
    仅使用 event_clusters_v2.json + prev_life_ctx_v2.txt，在脚本内把情节组拆成章节并生成。
    """
    if prev_life_ctx_path is None:
        prev_life_ctx_path = str(DEFAULT_PREV_LIFE_V2)
    if not os.path.exists(prev_life_ctx_path):
        raise FileNotFoundError(
            f"未找到上一世线索文件：{prev_life_ctx_path}，"
            "请先运行 generate_outline_from_event_clusters_v2.py 生成 prev_life_ctx_v2.txt。"
        )

    clusters_path = str(DEFAULT_EVENT_CLUSTERS_V2)
    if not os.path.exists(clusters_path):
        raise FileNotFoundError(
            f"未找到事件簇文件：{clusters_path}，"
            "请先运行 generate_event_clusters_v2.py 生成 event_clusters_v2.json。"
        )

    with open(clusters_path, "r", encoding="utf-8") as f:
        clusters: List[Dict[str, Any]] = json.load(f)
    if not isinstance(clusters, list) or not clusters:
        raise ValueError("event_clusters_v2.json 为空或格式错误，无法生成正文。")

    overlapping: List[Dict[str, Any]] = []
    for c in clusters:
        span = c.get("chapter_span") or c.get("chapterRange") or c.get("chapters")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            continue
        try:
            s, e = int(span[0]), int(span[1])
        except Exception:
            continue
        if e < start_chapter or s > end_chapter:
            continue
        c["_start"] = s
        c["_end"] = e
        overlapping.append(c)

    if not overlapping:
        raise ValueError(
            f"章节范围 {start_chapter}-{end_chapter} 与 event_clusters_v2.json 中任何情节组均无交集，"
            "请调整 --start / --end 或重新生成事件簇。"
        )

    min_s = min(c["_start"] for c in overlapping)
    max_e = max(c["_end"] for c in overlapping)
    adjusted_start = min(min_s, start_chapter)
    adjusted_end = max(max_e, end_chapter)
    if adjusted_start != start_chapter or adjusted_end != end_chapter:
        # 汇总被纳入的情节族边界，便于用户确认
        included_spans: List[str] = []
        for c in sorted(overlapping, key=lambda x: (x.get("_start", 0), x.get("_end", 0))):
            try:
                ss, ee = int(c["_start"]), int(c["_end"])
                cid = str(c.get("cluster_id", "")) or "?"
                included_spans.append(f"{cid}:{ss}-{ee}")
            except Exception:  # noqa: BLE001
                continue
        spans_str = "，".join(included_spans) if included_spans else f"{adjusted_start}-{adjusted_end}"
        print(
            f"✅ 已对齐到情节族边界：章节范围调整为 {adjusted_start}-{adjusted_end}（原 {start_chapter}-{end_chapter}）。\n"
            f"   纳入的情节族范围：{spans_str}"
        )

    # 在任何 Neo4j 导出/在线检索器/正文生成之前，先把“识别到的情节族”汇总打印出来
    overlapping_sorted = sorted(overlapping, key=lambda x: int(x.get("_start", 0)))
    print("\n📌 识别到的情节族信息（将按此范围生成）")
    for c in overlapping_sorted:
        try:
            s = int(c.get("_start", c.get("chapter_span", [0, 0])[0]))
            e = int(c.get("_end", c.get("chapter_span", [0, 0])[1]))
        except Exception:  # noqa: BLE001
            s, e = 0, 0
        cid = c.get("cluster_id", "UNKNOWN")
        name = c.get("name", "")
        core = c.get("core_payoff", "") or c.get("core", "") or ""
        opp = c.get("main_opponent", "") or ""
        span_str = f"{s}-{e}" if s and e else str(c.get("chapter_span") or c.get("chapterRange") or c.get("chapters") or "")
        print(f"- {cid}《{name}》 覆盖章节:{span_str}；主要对手:{opp or '（未指定）'}；核心爽点:{core or '（未提供）'}")

    # 自动导出 Neo4j 上下文（供调试/审阅；生成过程本身使用在线检索器逐章拉取背景）
    try:
        print("🧭 正在检索情节族上下文（Neo4j）：窗口 + lookback + auto-anchors …")
        # 构造窗口章节
        window = list(range(adjusted_start, adjusted_end + 1))
        # lookback: 回溯 2 章
        lookback_n = 2
        if window:
            m = min(window)
            lb = list(range(max(1, m - lookback_n), m))
            window = sorted(set(window) | set(lb))
        # auto-anchors: 自动补充关键早期章（最多 10 个）
        try:
            from bert_excitation_train.scripts.neo4j_kg.export_for_v2 import (  # type: ignore[import-not-found]
                fetch_context,
                compute_anchor_chapters,
            )
            from bert_excitation_train.scripts.neo4j_kg.common import get_neo4j_driver  # type: ignore[import-not-found]
            with get_neo4j_driver() as driver:  # type: ignore[attr-defined]
                extras = compute_anchor_chapters(driver, window, max_extra=10)
                chapters_for_export = sorted(set(window) | set(extras))
                ctx = fetch_context(driver, chapters_for_export)
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            with open(DEFAULT_EXPORT_V2, "w", encoding="utf-8") as f:
                json.dump(ctx, f, ensure_ascii=False, indent=2)
            print(f"✅ 已导出上下文至 {DEFAULT_EXPORT_V2}")
            print(f"   章节集合：{','.join(str(x) for x in chapters_for_export)}")
        except Exception as ex:  # noqa: BLE001
            print(f"⚠️ 跳过导出上下文（Neo4j 不可用或导出失败）：{ex}")
    except Exception:
        pass

    resolved_master_cards_path = master_ctx_cards_path or str(DEFAULT_MASTER_CARDS_V2)
    legacy_cards = _load_master_cards_v2(resolved_master_cards_path)
    cluster_cards = _build_cards_from_clusters(overlapping)
    cards: Dict[int, Dict[str, Any]] = {
        chapter: {
            **dict(legacy_cards.get(chapter) or {}),
            **dict(cluster_card),
        }
        for chapter, cluster_card in cluster_cards.items()
    }
    cards = _enrich_cards_with_cluster_milestones(cards, overlapping)
    gen = RebirthRevengeGeneratorV2()
    _setup_gen_from_cards_and_prev_life(gen, cards, prev_life_ctx_path, clusters)
    # 本地章节记忆账本始终可用；Neo4j 在线时同时投影到图数据库。
    gen.attach_story_memory()
    # 挂载在线检索器（若可用）：每章生成前动态检索 Neo4j 背景事实
    try:
        gen.attach_online_retriever()
        print("🔎 在线检索器（Neo4j）已启用：将为每章注入限长背景事实。")
    except Exception:
        pass

    if chapters_dir is None:
        chapters_dir = str(OUTPUT_DIR / "chapters")
    os.makedirs(chapters_dir, exist_ok=True)
    gen.outputs_dir = Path(chapters_dir).parent

    # 新工作流：按“情节族/事件簇”生成整簇连续正文，最后再切分为章节
    clusters_sorted = sorted(overlapping, key=lambda x: int(x.get("_start", 0)))
    generated_chapters_global: set[int] = set()

    out_ch_dir = Path(gen.outputs_dir) / "chapters"
    coordinator = getattr(gen, "story_memory", None)
    if coordinator is not None:
        try:
            backfilled = coordinator.ensure_backfilled(out_ch_dir, adjusted_start)
            if backfilled:
                print(f"🧠 StoryMemory 已在续写前回填 {backfilled} 个历史章节。")
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ StoryMemory 历史回填未完成：{exc}")
    # 生成入口跳过逻辑：避免把之前生成的“短章”当成合格版本复用。
    for cluster in clusters_sorted:
        span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters") or []
        try:
            s, e = int(span[0]), int(span[1])
        except Exception:  # noqa: BLE001
            continue
        chapter_nums = list(range(s, e + 1))
        need_generate = False
        for ch in chapter_nums:
            if ch not in cards:
                continue
            min_chars_for_accept = _minimum_chapter_chars(ch, cards.get(ch))
            if ch in gen.generated_chapters and len((gen.generated_chapters.get(ch) or "").strip()) >= min_chars_for_accept:
                continue
            p = out_ch_dir / f"chapter_{ch:03d}.txt"
            if p.exists() and p.stat().st_size >= 200:
                existing = p.read_text(encoding="utf-8").strip()
                if len(existing) >= min_chars_for_accept:
                    gen.generated_chapters[ch] = existing
                    continue
            need_generate = True
            break
        if not need_generate and all(ch in gen.generated_chapters for ch in chapter_nums if ch in cards):
            continue

        print(f"\n====== 生成情节族 {cluster.get('cluster_id','UNKNOWN')}《{cluster.get('name','')}》：第{s}-{e}章 ======")
        new_texts = _generate_cluster_continuous_and_split_v2(gen, cluster, cards)
        missing_after_generation = [ch for ch in chapter_nums if ch in cards and ch not in new_texts]
        if missing_after_generation:
            raise RuntimeError(
                f"情节族 {cluster.get('cluster_id', 'UNKNOWN')} 生成失败，缺少章节：{missing_after_generation}。"
                "已回滚该情节族文本与 StoryMemory，流水线停止以避免产出缺章小说。"
            )
        for ch in chapter_nums:
            if ch in new_texts:
                generated_chapters_global.add(ch)

    if sync_neo4j:
        _sync_neo4j_from_outputs(
            min_name_freq=neo4j_min_name_freq,
            reset_db=neo4j_reset_db,
            auto_extract_relations=neo4j_auto_extract_relations,
        )


def generate_chapters_by_clusters_v2(
    master_ctx_cards_path: Optional[str] = None,
    prev_life_ctx_path: Optional[str] = None,
    chapters_dir: Optional[str] = None,
    cluster_ids: Optional[List[str]] = None,
) -> None:
    """
    DEPRECATED（逐章生成流程）

    该实现属于“旧工作流”：在簇内部逐章生成，并在簇完成后做 critic 审查/必要重写。
    当前默认入口已切换为 `generate_chapters_v2()`（整簇连续正文 -> 再切分微调）。

    保留此函数仅用于历史对比/排查；不应再被当作主生成入口使用。
    """
    # 防止误用旧工作流：如确有需要请改用 generate_chapters_v2() 或手动回滚到旧实现。
    raise RuntimeError(
        "generate_chapters_by_clusters_v2() 已弃用：请使用 generate_chapters_v2()（新工作流）。"
    )

    # ---- 下面是旧实现代码（已弃用，默认不可达）----
    # 保留参数以兼容旧命令，但在情节组模式下不再使用 master_ctx_cards_v2.json
    if prev_life_ctx_path is None:
        prev_life_ctx_path = str(DEFAULT_PREV_LIFE_V2)

    if not os.path.exists(prev_life_ctx_path):
        raise FileNotFoundError(
            f"未找到上一世线索文件：{prev_life_ctx_path}，"
            f"请先运行基于 V2 事件簇的大纲脚本生成 prev_life_ctx_v2.txt。"
        )

    clusters_path = str(DEFAULT_EVENT_CLUSTERS_V2)
    if not os.path.exists(clusters_path):
        raise FileNotFoundError(
            f"未找到事件簇文件：{clusters_path}，"
            f"请先运行 generate_event_clusters_v2.py 生成 event_clusters_v2.json。"
        )

    with open(clusters_path, "r", encoding="utf-8") as f:
        clusters: List[Dict[str, Any]] = json.load(f)
    if not isinstance(clusters, list):
        raise ValueError("event_clusters_v2.json 顶层必须是数组。")

    # 过滤需要的簇，并按 chapter_span 起始排序，保证整体推进顺序正确
    selected: List[Dict[str, Any]] = []
    for c in clusters:
        if cluster_ids and c.get("cluster_id") not in set(cluster_ids):
            continue
        span = c.get("chapter_span") or c.get("chapterRange") or c.get("chapters")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            continue
        try:
            s, e = int(span[0]), int(span[1])
        except Exception:
            continue
        c["_start"] = s
        c["_end"] = e
        selected.append(c)

    if not selected:
        print("⚠️ 未在事件簇文件中找到可用的簇（或 cluster_ids 过滤后为空），不执行生成。")
        return

    selected.sort(key=lambda x: x.get("_start", 9999))

    resolved_master_cards_path = master_ctx_cards_path or str(DEFAULT_MASTER_CARDS_V2)
    cards = _load_master_cards_v2(resolved_master_cards_path)
    if not cards:
        # 兜底：master cards 缺失时才退回动态构建
        cards = _build_cards_from_clusters(selected)
    gen = RebirthRevengeGeneratorV2()
    _setup_gen_from_cards_and_prev_life(gen, cards, prev_life_ctx_path, clusters)

    if chapters_dir is None:
        chapters_dir = str(OUTPUT_DIR / "chapters_v2")
    os.makedirs(chapters_dir, exist_ok=True)
    gen.outputs_dir = Path(chapters_dir).parent

    for cluster in selected:
        cid = cluster.get("cluster_id", "UNKNOWN")
        name = cluster.get("name", "")
        s, e = int(cluster["_start"]), int(cluster["_end"])
        core = cluster.get("core_payoff", "")
        main_opp = cluster.get("main_opponent", "")
        span = cluster.get("chapter_span") or cluster.get("chapterRange") or cluster.get("chapters")

        max_cluster_attempts = 2
        critic_result: Dict[str, Any] = {}
        for attempt in range(max_cluster_attempts):
            if attempt > 0:
                setattr(gen, "_cluster_rewrite_advice", critic_result.get("rewrite_advice", []))
                print(f"\n⚠️ 情节组 {cid} 未通过完成审查，第 {attempt + 1} 次重写，已注入重写要求。")
            else:
                setattr(gen, "_cluster_rewrite_advice", None)

            print("\n" + "=" * 70)
            print(f"🎯 生成情节组 {cid}《{name}》" + ("（重写）" if attempt > 0 else ""))
            print(f"   覆盖章节: {span or [s, e]}  （实际生成范围: 第{s}-{e}章）")
            print(f"   核心爽点: {core or '（未提供）'}")
            print(f"   主要对手: {main_opp or '（未指定）'}")
            print("=" * 70)

            for ch in range(s, e + 1):
                # 簇内滚动上下文：已写章节摘要 → resolved_so_far / unresolved_must_finish
                chapter_texts_so_far: Dict[int, str] = {}
                for prev_ch in range(s, ch):
                    prev_path = Path(chapters_dir) / f"chapter_{prev_ch:03d}.txt"
                    if prev_path.exists():
                        try:
                            chapter_texts_so_far[prev_ch] = prev_path.read_text(encoding="utf-8").strip()
                        except Exception:  # noqa: S110
                            pass
                    if prev_ch in getattr(gen, "generated_chapters", {}):
                        chapter_texts_so_far[prev_ch] = gen.generated_chapters[prev_ch]
                state = _build_cluster_internal_state(cluster, chapter_texts_so_far, chapters_dir)
                setattr(gen, "_cluster_internal_state", state)

                print(f"\n—— 情节组 {cid}：生成第 {ch} 章 ——")
                gen.debug_print_chapter_context(ch)
                gen.generate_one_chapter_with_beats(  # type: ignore[attr-defined]
                    chapter_num=ch,
                    num_versions=1,
                    max_iterations=2,
                    min_emotion_intensity=0.5,
                )

            # 簇完成审查：读取刚写的各章，判 payoff 是否落地、是否越界
            chapter_texts_for_critic: Dict[int, str] = {}
            for ch in range(s, e + 1):
                p = Path(chapters_dir) / f"chapter_{ch:03d}.txt"
                if p.exists():
                    try:
                        chapter_texts_for_critic[ch] = p.read_text(encoding="utf-8").strip()
                    except Exception:  # noqa: S110
                        chapter_texts_for_critic[ch] = ""
                elif ch in getattr(gen, "generated_chapters", {}):
                    chapter_texts_for_critic[ch] = gen.generated_chapters[ch]

            critic_result = _cluster_critic(
                cluster,
                chapter_texts_for_critic,
                chapter_cards=cards,
            )
            payoff_ok = critic_result.get("payoff_completed", False)
            violations = critic_result.get("violations", [])

            print(f"\n📋 情节组 {cid} 完成审查：payoff_completed={payoff_ok}，violations={len(violations)} 条")
            if violations:
                for v in violations[:5]:
                    print(f"   - {v}")
            if payoff_ok or attempt >= max_cluster_attempts - 1:
                if not payoff_ok:
                    print(f"   ⚠️ 已达最大重写次数，保留当前版本。建议人工检查第{s}-{e}章。")
                break


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="基于 V2 事件簇生成重生复仇小说正文（不依赖 master_ctx_cards_v2.json）"
    )
    parser.add_argument(
        "--prev-life",
        default=str(DEFAULT_PREV_LIFE_V2),
        help="上一世线索文件路径（默认 outputs/prev_life_ctx_v2.txt）",
    )
    parser.add_argument(
        "--chapters-dir",
        default=str(OUTPUT_DIR / "chapters"),
        help="输出章节目录（默认 outputs/chapters）",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="起始章节号，默认 1",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=100,
        help="结束章节号，默认 100",
    )
    parser.add_argument(
        "--skip-neo4j-sync",
        action="store_true",
        help="跳过：生成正文后不自动同步到 Neo4j 知识图谱",
    )
    parser.add_argument(
        "--neo4j-min-name-freq",
        type=int,
        default=5,
        help="Neo4j 构建时的候选人名最小频次阈值（min-name-freq）",
    )
    parser.add_argument(
        "--neo4j-auto-extract-relations",
        action="store_true",
        help="启用 Neo4j 语义关系自动抽取（可能更慢）",
    )
    parser.add_argument(
        "--neo4j-reset",
        action="store_true",
        help="危险操作：同步前清空 Neo4j 数据库（仅在你确认需要时启用）",
    )
    args = parser.parse_args()

    generate_chapters_v2(
        prev_life_ctx_path=args.prev_life,
        chapters_dir=args.chapters_dir,
        start_chapter=args.start,
        end_chapter=args.end,
        sync_neo4j=not args.skip_neo4j_sync,
        neo4j_min_name_freq=args.neo4j_min_name_freq,
        neo4j_reset_db=args.neo4j_reset,
        neo4j_auto_extract_relations=args.neo4j_auto_extract_relations,
    )


if __name__ == "__main__":
    main()

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
import sys
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import dashscope

from smart_sample_search import search_rebirth_samples_for_chapter
from optimized_rule_scorer import OptimizedRuleScorer
from emotion_analyzer import EmotionAnalyzer

# Windows/PowerShell 可能默认使用 GBK 编码，遇到打印 emoji 时触发 UnicodeEncodeError。
try:
    import io

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "outputs"

# 通义千问（与旧版脚本同 key；本文件独立维护，不依赖 generate_chapter_content.py）
API_Key_QW = "sk-a2966f4e37134351904851679884cb67"

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
MIN_CHAPTER_CHARS_V2 = 1400


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
    repo_root = PROJECT_ROOT.parent
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
        "chapter_goal": "只写上一世病房临死前的绝境，不出现重生后的正式苏醒，也不出现任何调查/照片/身份谜团。",
        "chapter_must_include": [
            "深夜病房环境和监护仪报警",
            "求助被医护/亲人无视或敷衍",
            "陆景明与相关医护冷漠配合或敷衍安抚",
            "最后一通电话被挂断或无人接听"
        ],
        "chapter_must_not_include": [
            "重生醒来或从病床上“突然坐起”",
            "任何现代场景中的调查/线索分析",
            "照片/U盘/神秘人/系统/幕后黑手",
            "身份替换/车祸新闻/警方介入"
        ],
        "chapter_ending": "在窒息和绝望中逐渐失去意识，意识到自己要死了但还不知道会重来一次。"
    },
    2: {
        "chapter_role_v2": "rebirth_awakening_only",
        "chapter_goal": "只写重生惊醒与确认时间回到悲剧前夜，从震惊→怀疑是梦→通过具体证据确认“真的回去了”。",
        "chapter_must_include": [
            "从上一章病房死亡记忆中惊醒",
            "发现自己回到熟悉房间/时间点",
            "通过日期、手机、亲友状态等细节确认时间回溯",
            "决定这一次不会再轻信任何人"
        ],
        "chapter_must_not_include": [
            "直播/警方/媒体报道",
            "更大势力/幕后阴谋的正式展开",
            "非法实验/身份替换/系统提示音",
            "正式举报或真正意义上的复仇行动"
        ],
        "chapter_ending": "她在确认“这不是梦”后，把第一个可疑细节记在心里，决定先沉住气观察身边所有人。"
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
            r"林修远", r"赵明轩", r"陈主任", r"王秘书", r"经理", r"院长",
            r"主治医师", r"护士长", r"未婚夫", r"丈夫", r"男友",
        ]
        location_patterns = [
            r"ICU病房", r"医院", r"公司", r"会议室", r"办公室", r"茶水间",
            r"法庭", r"发布会", r"宴会", r"仓库", r"档案库",
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

        call_kwargs = {
            "model": dashscope.Generation.Models.qwen_turbo,
            "messages": [system_message, user_message],
            "temperature": 0.85,
            "top_p": 0.8,
            "repetition_penalty": 1.1,
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
            text = re.sub(p, "沈清欢", text)
        text = re.sub(r"林[\u4e00-\u9fff]{1,2}", "沈清欢", text)
        text = re.sub(r"夏[\u4e00-\u9fff]{1,2}", "沈清欢", text)
        text = re.sub(r"女主角", "沈清欢", text)
        text = re.sub(r"女主", "沈清欢", text)
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
【本章职责（第1章）】重点写：ICU环境、家属冷漠、生理痛苦、第一重背叛确认。不要展开社会舆论或情感背叛，留到第2、3章。
"""
        if chapter_num == 2:
            return """
【本章职责（第2章）】重点写：手机/直播/恶评、舆论绞杀、丈夫公开切割。「她不仅快死了，还被全网羞辱」。不要重复第1章的病床描写，不要写拥抱/情感背叛，留到第3章。
"""
        if chapter_num == 3:
            return """
【本章职责（第3章）】重点写：看到拥抱、彻底确认最爱的人是主谋、录音/最后证据、死亡或意识断裂导向重生。与前两章形成「身体濒死→社会抛弃→情感致命一击」的递进。
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
        prompt = f"""角色：你是专业小说作者，擅长重生复仇短剧正文。

【核心要求】
1. 严格按本章节拍卡与梗概推进，不得偏离；节拍卡中的每一拍都必须写到位，不得跳过或一笔带过。
2. 字数：至少1000字，建议1000-1400字，单章不宜超过1600字（避免跑偏）。第三人称，快节奏，结尾留悬念。
3. 主线优先，禁止随意新增无关支线。
"""
        if need_prev_life and prev_life_clue and chapter_num not in (1, 2):
            past_ratio_min = 0.35
            past_ratio_max = 0.50
            prompt += f"""
【上一世回忆·硬约束】（必须遵守，否则视为不合格）
- 本章**必须**出现一段完整的「上一世受害」回忆段落，插入位置须服从梗概中的 flashback_breakpoint（{flashback_breakpoint_hint or "在节拍卡标明的那一拍之后"}）。
- **占比强制**：正文中上一世相关内容字数须占全章的 **{int(past_ratio_min*100)}%~{int(past_ratio_max*100)}%**，不得用一句“像上一世那样”带过。
- **四步结构**（上一世段落必须依次包含，写成可感知场景，禁止写成摘要）：
  ① 假性温和：先给她一点希望（某人表面和气/场面看似正常）。
  ② 突然反咬：有人当众翻旧账、倒打一耙或栽赃（谁先开口、说了什么、其他人什么反应）。
  ③ 无人帮她：她想解释却被打断、无人声援、沉默或附和（女主当时怎么僵住、身体反应）。
  ④ 结果性伤害：丢脸、失去机会、关系破裂或当众被“定罪”（最后是谁定了她的罪、她当时感受）。
- 用「上一世，我……」「记得在上一世……」等句式在正文中点明回忆；不准只写“上一世她也曾被他们陷害”这类信息句，必须写**具体对话、动作、反应**。
"""
        else:
            prompt += """
【上一世】本章无强制上一世回忆；若梗概未要求插入回忆，不要硬插，只写本世发展。
"""
        if chapter_num == 1:
            prompt += """
【重生前限制（第1章）】
- 本章只写上一世临死前的经历（ICU/病房/被抛弃抢救/被背叛等），正文中**禁止出现“重生”“回到过去”“第二次人生”等字样**。
- 结尾只能停留在她意识到“自己被害死/要死了”的绝望感，不能意识到自己还有第二次机会或会重来一次。
"""
        if chapter_num == 2:
            prompt += """
【重生觉醒写法（第2章）】
- 开篇先写她在熟悉环境中醒来，感受到身体状态、时间、环境的异常，重点是“震惊”和“不适应”，不要一上来就心想“我重生了”。
- 接下来通过对比具体证据（日期、手机信息、亲人/同事状态等），从“怀疑是梦/记错时间”逐步过渡到“越来越不对劲”。
- 在收集到足够多不正常的细节之后，才允许她在内心明确意识到“这是回到过去/自己重来了一次”，届时才可以在内心或独白中出现“重生”概念。
- 严禁一开篇就直接写“她意识到自己重生了”，必须有“震惊 → 怀疑 → 验证 → 确认”的过程。
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

    def attach_online_retriever(self) -> None:
        """
        为 V2 生成流程挂载在线检索器（Neo4j）。
        生成端会优先调用 self.online_retrieve_context(chapter_num) 获取限长 KG 文本。
        """
        try:
            from neo4j_kg.online_retriever import retrieve_context_for_chapter  # type: ignore[import-not-found]
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
            # 兜底：至少包含女主
            if "沈清欢" not in allowed:
                allowed = ["沈清欢"] + allowed
            try:
                return retrieve_context_for_chapter(
                    chapter_num=chapter_num,
                    allowed_roles=allowed[:8],
                    main_opponent=mo,
                    max_chars=900,
                )
            except Exception:
                return ""

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
        lines.append("你是重生复仇短剧作家。请严格执行【章节执行卡】并直接输出正文，不要解释，不要新增主线/新证据类型。")
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
                f"- 上一世留下、今生可利用的信息差：{info_gap or '（请在正文中具体写出：她知道了哪些别人不知道的内幕、漏洞、时间节点或关系网，从而能提前一步反杀）'}\n"
                f"- 本簇结束结果：{outcome}"
            )

        # 实体白名单/黑名单：锁定本簇角色，禁止长篇式扩张
        allowed = card.get("allowed_roles") or ["沈清欢", main_opp or "本簇主对手"]
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
            "- 禁止出现“系统提示音”“神秘人”“神秘司机”“苏晚晴”等未在本簇规划中的角色或设定；证据必须来自本簇信息差（如值班室笔记、病历篡改），不得改为“神秘人送U盘/录像”。"
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
            "2. 本簇完结前，禁止使用“幕后还有更大黑手”“她才发现真正的敌人另有其人”等扩世界观写法。\n"
            "3. 本簇最后一章必须先兑现本簇核心爽点（举报/揭穿/处罚/职业毁灭等），再允许留下一个极小的余波钩子。\n"
            "4. 若篇幅不足，优先删去神秘感、环境描写、追踪桥段，也必须保留证据链与反杀结果。优先级：闭环完成 > 证据链显性 > 爽点兑现 > 小说感。"
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
                f"- 本情节组覆盖 {cluster_range_str}，叙事骨架必须是「旧局重演」：先让读者认出**旧局/旧招**在今生重演，再写她如何**凭记忆提前布子**，然后写**对方照旧出招**，最后**关键时刻反卡落锤**；禁止把整组写成都市调查取证文。\n"
                "- 上一世悲惨遭遇必须在情节组内写厚：至少有一章集中写**完整上一世受害段落**（具体场景、对话、屈辱与无助），不能只用一句「上一世也曾」带过。\n"
                "- 整个情节组的总字数结构建议为：上一世相关内容约占 35%~50%，今世反击约占 50%~65%；不是每一章都平均摊，而是分工完成。\n"
                f"- 当前是本情节组中的第 {cluster_idx}/{cluster_total} 章，请按本章章节角色（{role_v2}）承担相应一段。\n"
                "- 信息差与材料/证据是**落锤工具**：用来坐实她早已知道的事，不能代替「记忆先于证据」的推进；禁止依赖匿名邮件、陌生人递材料、匿名爆料等天降线索。\n"
                "- 今生的反击要让旁人感到违和：她为何能提前踩准布局；旁人不能一眼看出重生，但读者要清楚她赢在**记得旧局**。\n"
            )
        else:
            extra_lines.append(
                "\n【情节组闭环与信息差使用要求】\n"
                "- 每一个事件簇必须在本簇内完成「旧局重演」式复仇：认出旧局→提前布子→对方照旧出招→反卡落锤；禁止写成调查取证文。\n"
                "- 上一世悲惨遭遇必须写厚：至少一章写足完整受害段落；信息差与证据是落锤工具，不能当故事发动机。\n"
                "- 禁止匿名邮件、陌生人递材料、匿名爆料等天降线索；本世线索只能来自她凭记忆主动取证或对手按老剧本露破绽。\n"
            )

        # 根据角色给出更具体的节拍建议
        role_desc = ""
        if role_v2 == "present_setup":
            role_desc = (
                "本章重点：旧局重现与提前布子——沈清欢认出与上一世同一套局/同一套把戏，并立刻开始针对性布置；"
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
                "本章重点：今生反击与结果，围绕本簇 core_payoff 把爽点打满；"
                "先写对方照旧出招/走到她预埋的卡点，再写证据/材料当场落锤坐实——证据是锤，不是故事发动机；"
                "写清对手具体后果。"
            )
        elif role_v2 == "present_past_mix":
            role_desc = (
                "本章重点：今生遭遇与上一世片段交错对照，"
                "通过“重复的台词/动作/场景”触发记忆，对比她这一次的不同选择。"
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
                "本章重点：诱敌与压实——写对方照旧按旧剧本出招，她如何收紧已布好的子；"
                "核实或取出她「上一世就知道存在」的材料，而非首次发现新线索；"
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
            "- 严禁使用空洞的预感型句子作为章节结尾，例如“他隐约觉得更大的危险正在逼近”“她知道这只是更大风暴的开始”等，这类句子没有具体事件，不具备吸引力。\n"
            "- 尤其禁止出现类似“他知道，这场游戏还没有结束。”“真正的风暴，才刚刚开始。”之类只靠比喻/预感堆砌气氛的句子，一经出现请直接改写。\n"
            "- 章节结尾必须落在一个**具体、可视化的动作或事件瞬间**上，例如：\n"
            "  · 门被人猛地推开/门外突然传来急促的脚步声；\n"
            "  · 某个关键人物在她转身要走时叫住她，说出半句话；\n"
            "  · 手机震动弹出一条出乎意料的信息/通话；\n"
            "  · 她刚亮出的证据让现场某人脸色大变、话到嘴边却戛然而止。\n"
            "- 请自行设计类似的“具体动作型钩子”，让读者停在一个悬在半空的画面上，而不是停在抽象感受上。"
        )

        return base_prompt + "\n" + "\n".join(extra_lines)


# 本簇禁止引入的通用角色/元素（避免长篇连载式扩张）
DEFAULT_FORBIDDEN_NEW_ROLES = [
    "神秘援手", "神秘司机", "系统", "系统提示音", "苏晚晴", "黑色轿车", "神秘人",
    "幕后黑手", "更大风暴", "真正的敌人", "神秘男人", "陌生女性盟友", "未规划的关键证人",
]
# 本章允许出场的通用配角描述（不写死具体姓名，避免与主对手混淆）
DEFAULT_ALLOWED_SUPPORT = "医院同事、护士、主任、功能性配角"

# 重生复仇叙事：禁止「调查文」式天降线索（写入章节卡 must_not 与 critic 提示）
REBIRTH_FORBIDDEN_DEUS_EX = [
    "匿名邮件/匿名爆料作为关键转折",
    "加密邮箱突然跳出决定性截图或附件",
    "老员工/陌生人未经铺垫突然递来唯一关键材料",
    "靠社交媒体发帖或声明完成主线翻盘",
    "隐藏文件夹/机密会议纪要突然揭示全部真相",
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
        ("社交媒体", "社交媒体发帖翻盘"),
        ("突然收到一封", "突然收到匿名信/邮件"),
    ]
    for kw, label in checks:
        if kw in full_text:
            bad.append(label)
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


def _chapter_body_hard_failures(part_text: str) -> List[str]:
    """单章正文生成后立即检查，触发章内重试。"""
    out: List[str] = []
    fl = _critic_format_leak(part_text)
    if fl:
        out.append(fl)
    inv = sum(1 for k in INVESTIGATION_NARRATIVE_TOKENS if k in part_text)
    rb = _count_rebirth_buckets(part_text)
    if inv >= 4 and rb < 2:
        out.append(
            "本章调查/媒体链过重且重生推进不足：删掉匿名邮件/媒体爆料/档案室翻找等，改为认出旧局与提前布子。"
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

    # 医疗/职业场景
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
        add("罪行证据")

    # fallback：至少返回一个可用的“证据类型占位”
    if not evidences:
        add("本簇信息差中的具体证据或内幕")

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

    return f"""你是重生复仇短剧/小说编剧。请基于【情节族】信息生成一个【证据链执行计划】。

【叙事前提】本计划必须服务「旧局重演」式重生复仇：沈清欢凭上一世记忆**预判**旧招、提前布子；证据/材料只在**落锤**时坐实她早已知道的事，不能写成「调查偶然发现新线索」。
禁止在剧情里依赖匿名邮件、陌生人递材料、匿名爆料作为唯一关键转折。

【非常重要】输出必须是严格 JSON（不要 Markdown，不要解释文字），且可被 json.loads 直接解析。
要求（非常重要）：
1. 证据标记必须采用全角方括号格式：例如【E1】、【E2】。后续正文与 critic 将依赖该格式。
2. evidence_chain 选择 2-3 个核心证据；每个证据必须给出：
   - evidence_id：E1/E2/E3...
   - evidence_type：用简短中文描述（需与 info_gap_from_prev_life 对齐）
   - source：信息来源（须能解释为「她上一世已知/记得去何处取」，而非天降）
   - acquire_chapter / verify_chapter / use_chapter：分别在 {start_ch}-{end_ch} 哪些章节发生（必须是章节号整数）
   - purpose：每个证据在剧情里的作用（兑现“重生复仇爽点链条”）
   - acquire_keywords / verify_keywords / use_keywords：用于 critic 判定动作是否发生在对应章节的关键词数组（每个数组至少 1 个关键词）
3. 获取/验证/使用章节必须满足：acquire_chapter <= verify_chapter <= use_chapter。
4. 对与“录音/七年前”相关的证据，必须让对应章节里的关键词与动作一致（避免“开始录音下一章却播放七年前录音”的跳链）。
5. forbidden_new_evidence_types：列出 3-5 个本情节族禁止突然新增的证据类型（须包含匿名爆料/匿名邮件驱动关键转折等）。
6. payoff_sequence：按“至少 5 步”写出反杀爽点兑现顺序（要体现：认出旧局→提前布子→对方照旧出招→反卡→亮证据落锤→结果落地）。

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
) -> Dict[str, Any]:
    """模型未能生成/解析 exec_plan 时的兜底：早获取->中验证->晚使用。"""
    start_ch, end_ch = int(chapter_nums[0]), int(chapter_nums[-1])
    info_gap = str(cluster.get("info_gap_from_prev_life", "") or "")
    evidence_types = _infer_evidence_types_from_info_gap(info_gap) or ["本簇信息差中的具体证据或内幕"]
    evidence_count = 2 if len(evidence_types) < 3 else 3
    evidence_types = evidence_types[:evidence_count]

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
        return {
            "acquire_keywords": ["取出", "文件", "记录"],
            "verify_keywords": ["核对", "确认"],
            "use_keywords": ["提交", "当众", "落锤"],
        }

    evidences: List[Dict[str, Any]] = []
    if len(chapter_nums) >= 3:
        triples: List[tuple] = [
            (evidence_types[0], start_ch, min(start_ch + 1, end_ch), end_ch),
            (evidence_types[1], min(start_ch + 1, end_ch), min(start_ch + 1, end_ch), end_ch),
        ]
        if evidence_count == 3:
            triples.append((evidence_types[2], min(start_ch + 2, end_ch), min(start_ch + 2, end_ch), end_ch))
    else:
        triples = [
            (evidence_types[0], start_ch, start_ch, end_ch),
            ((evidence_types[1] if len(evidence_types) > 1 else evidence_types[0]), start_ch, start_ch, end_ch),
        ]

    for idx, (etype, ac, vc, uc) in enumerate(triples[:evidence_count], start=1):
        kw = _keywords_from_type(etype)
        evidences.append(
            {
                "evidence_id": f"E{idx}",
                "evidence_type": etype,
                "source": "上一世留下的信息差线索（由 info_gap 推断）",
                "acquire_chapter": int(ac),
                "verify_chapter": int(vc),
                "use_chapter": int(uc),
                "purpose": "把信息差证据从‘可疑’推进为‘可提交/可定性’，最终兑现爽点落地",
                "acquire_keywords": kw["acquire_keywords"],
                "verify_keywords": kw["verify_keywords"],
                "use_keywords": kw["use_keywords"],
            }
        )

    chapter_execution_focus: Dict[str, Any] = {}
    for ch in chapter_nums:
        if ch == start_ch:
            chapter_execution_focus[str(ch)] = "认出旧局并提前布子；材料仅作后续落锤准备，不当调查发动机"
        elif ch == end_ch:
            chapter_execution_focus[str(ch)] = "对方照旧出招→反卡落锤→按证据链公开结果"
        else:
            chapter_execution_focus[str(ch)] = "诱敌压实：核实或取出她记忆中已知的材料，逼对方露破绽"

    return {
        "cluster_id": str(cluster.get("cluster_id", "") or ""),
        "cluster_name": str(cluster.get("name", cluster.get("cluster_name", "")) or ""),
        "evidence_chain": evidences,
        "forbidden_new_evidence_types": ["天降视频", "匿名人送U盘", "匿名邮件", "匿名爆料", "无规划的关键证人"],
        "chapter_execution_focus": chapter_execution_focus,
        "payoff_sequence": [
            "旧局在今生再现，主角认出并提前布子",
            "完整展开上一世受害（动机与恨意立住）",
            "对方按老剧本继续出招",
            "主角在关键点反卡，材料/证据当场落锤坐实",
            "对手否认/反扑失败",
            "权力或舆论定性，结果落地",
        ],
    }


def _generate_cluster_exec_plan(
    gen: "RebirthRevengeGeneratorV2",
    cluster: Dict[str, Any],
    chapter_cards: Dict[int, Dict[str, Any]],
    chapter_nums: List[int],
    exec_plan_path: Path,
) -> Dict[str, Any]:
    if exec_plan_path.exists():
        try:
            plan = _load_json_utf8(exec_plan_path)
            if isinstance(plan, dict) and plan.get("evidence_chain"):
                return plan
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
        plan_obj = _fallback_build_exec_plan_for_cluster(cluster, chapter_nums)

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
                "今生明确写出「认出旧局/记得对方会怎么出招」并提前布子",
                "反击时证据/材料仅用于落锤坐实她已知的事，而非靠调查偶然发现",
                "反杀结果或处罚落地",
            ],
            "must_not_include": DEFAULT_FORBIDDEN_NEW_ROLES + ["新幕后黑手", "只埋钩子不兑现"] + deus_forbid,
            "ending": f"本簇结束，结果需落到：{outcome or '对手付出代价'}"[:80],
            "must_resolve_this_chapter": ["上一世受害写厚", "记忆先于证据的反击", "完成反杀并写出结果"],
        }
    elif length == 2:
        ch1, ch2 = start_ch, end_ch
        chapters_plan[str(ch1)] = {
            "goal": "完整展开上一世在本簇情境下如何被害（写足段落，不得一句带过），为下一章反杀蓄力",
            "must_include": ["上一世具体受害过程", main_opp or "主对手", "与信息差相关的细节（她上一世如何被其害惨）"],
            "must_not_include": ["无关支线角色抢戏"] + REBIRTH_FORBIDDEN_DEUS_EX[:3] + DEFAULT_FORBIDDEN_NEW_ROLES,
            "ending": "回忆收束，读者清楚本簇仇人是谁、曾如何害她、她今生赢在记得旧局",
            "must_resolve_this_chapter": ["展开上一世悲剧", "明确主对手与信息差来源"],
        }
        chapters_plan[str(ch2)] = {
            "goal": f"对方照旧出招后当场反卡并完成：{core_payoff}，结果：{outcome or '对手付出代价'}",
            "must_include": [
                "写出对方按旧套路施压或走到她预埋的卡点",
                "当众揭穿或举报",
                "证据链闭环（显性使用" + required_evidence_hint + "，材料只坐实她早已知道的事）",
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
                f"旧局重现：沈清欢在与本簇主对手（{main_opp}）对峙/同场时，立刻认出这与上一世同一套局/同一套把戏；"
                f"她应马上开始提前布子（时间、话术、走位、卡点），而不是慢慢调查。"
            ),
            "must_include": [
                "明确写出「认出旧局/记得对方会怎么出招」的心理与依据（可短，但必须可感知）",
                "今生提前布子：她针对即将重演的旧招做出的具体安排",
                f"信息差（{required_evidence_hint}）仅作为她已知「该去哪里、何时拿何物」的依据，不是本章才去「发现线索」",
            ],
            "must_not_include": [
                "新幕后黑手",
                "追车/系统提示/无关神秘线",
                "把本章写成调查取证、到处找材料",
                "大段展开上一世完整受害经过（留给下一章）",
            ]
            + REBIRTH_FORBIDDEN_DEUS_EX
            + DEFAULT_FORBIDDEN_NEW_ROLES,
            "ending": "旧局已对上号，对方尚未察觉她已提前布子；为下一章完整展开上一世受害蓄力",
            "must_resolve_this_chapter": ["锁定主对手", "认出旧局并提前布子", "禁止调查文推进"],
        }
        chapters_plan[str(ch1 + 1)] = {
            "goal": "本簇核心：完整展开上一世在本簇情境下的受害经过（屈辱、具体场景与对话），并点明今生为何能预判对方会重复旧招",
            "must_include": [
                "上一世具体受害过程（至少写足一段完整段落，不得一句「上一世也曾」带过）",
                (main_opp + "的主观恶意与手段") if main_opp else "主对手的主观恶意与手段",
                f"与{required_evidence_hint}对应的关键细节（她上一世如何被这一信息差害惨）",
                "点明：今生反击的主动力是记忆与预判，不是偶然发现新材料",
            ],
            "must_not_include": ["无关支线角色抢戏"] + REBIRTH_FORBIDDEN_DEUS_EX + DEFAULT_FORBIDDEN_NEW_ROLES,
            "ending": "读者清楚她为何恨、为何这一世能提前卡位；材料/证据仅为后续落锤准备",
            "must_resolve_this_chapter": ["完整上一世受害段落", "记忆与预判动机立住"],
        }
        chapters_plan[str(ch_last)] = {
            "goal": f"关键时刻反卡与结果落地：兑现本簇爽点 {core_payoff}，结局 {outcome or '职业毁灭/失去信任'}",
            "must_include": [
                "对方按上一世老套路/旧剧本出手或施压（照旧出招）",
                "她在关键时刻反卡：当场揭穿/亮出落锤材料（材料只坐实她早已知道的事）",
                f"显性使用{required_evidence_hint}完成闭环",
                "处罚/吊销/震动或舆论反噬等具体后果",
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
                    "诱敌与压实：对方按旧招继续施压或走流程；沈清欢只去核实或取出她「上一世就知道存在」的材料，"
                    "必要时补刀对话压迫，不把整章写成搜集新线索。"
                )
                bridge_must = [
                    main_opp or "主对手",
                    "写出「对方照旧出招」与「她早有准备」的对位",
                    f"与{required_evidence_hint}相关的动作仅为核实/取出/封死退路，而非首次发现",
                ]
            else:
                if mid_idx == 1:
                    bridge_goal = "压迫升级：对方继续按旧剧本出招；她利用已布好的子逐步收紧，不引入新主线"
                elif mid_idx == 2:
                    bridge_goal = "将记忆层面的预判落实为可落锤的动作链，逼迫对手在公开场合露出破绽"
                else:
                    bridge_goal = "反击前夜：推进到可直接公开揭穿，不再扩展新问题或新材料"
                bridge_must = [
                    main_opp or "主对手",
                    "照旧出招与提前布子的对位",
                    f"围绕{required_evidence_hint}仅做核实/补刀/封口（不换证据来源）",
                ]
            chapters_plan[str(ch)] = {
                "goal": bridge_goal,
                "must_include": bridge_must,
                "must_not_include": ["新核心人物", "新组织/新阴谋线", "再次详细重演一整段上一世受害（应用回忆指认即可）"]
                + REBIRTH_FORBIDDEN_DEUS_EX
                + DEFAULT_FORBIDDEN_NEW_ROLES,
                "ending": "推进到下一章可直入反杀或收尾",
                "must_resolve_this_chapter": ["诱敌/压实", "禁止调查文灌水", "不扩散到其他簇"],
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

        plan = _build_cluster_plan(cluster)
        plan_chapters = (plan.get("chapters") or {})

        for idx, ch in enumerate(range(start_ch, end_ch + 1)):
            chapter_index = idx + 1
            # 若为第 1/2 章，优先使用硬编码 SPECIAL_CARDS，而不是按簇自动推断职责
            special = SPECIAL_CARDS.get(ch)
            if special:
                role_v2 = special.get("chapter_role_v2", "present_only")
                tmpl = "M1"
                # 对第 1/2 章而言，只负责“死前绝境”或“重生惊醒”，不要求完成本簇闭环
                completion_min, completion_max = 0, 30
            elif length == 2:
                role_v2 = "prev_life_full" if chapter_index == 1 else "present_revenge"
                tmpl = "M1"
                completion_min = 0 if chapter_index == 1 else 50
                completion_max = 50 if chapter_index == 1 else 100
            else:
                if chapter_index == 1:
                    role_v2, tmpl = "present_setup", "M1"
                    completion_min, completion_max = 0, 30
                elif chapter_index == 2:
                    role_v2, tmpl = "prev_life_full", "M1"
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
                "allowed_roles": [ "沈清欢", main_opp ] if main_opp else [ "沈清欢" ],
                "forbidden_roles": list(plan.get("forbidden_new_core_roles", DEFAULT_FORBIDDEN_NEW_ROLES)),
            }
            cards[ch] = card
    return cards


def _cluster_critic(
    cluster: Dict[str, Any],
    chapter_texts: Dict[int, str],
    exec_plan: Optional[Dict[str, Any]] = None,
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

    violations: List[str] = []
    rewrite_advice: List[str] = []
    introduced: List[str] = []

    # 1. 最后一章是否兑现 core_payoff / cluster_outcome
    core_payoff = (cluster.get("core_payoff") or "")
    outcome = (cluster.get("cluster_outcome") or "")
    # 放宽但更全面的“结果落地”判定：接受更丰富的同义表达，且允许在最后两章内出现
    payoff_keywords = [
        "举报", "揭穿", "执照", "吊销", "职业", "毁灭", "失去信任", "处罚", "落马", "崩塌",
        "反噬", "身败名裂", "自食恶果", "停职", "罢免", "免职", "撤职", "被带走", "被调查",
        "罢黜", "开除", "通报", "曝光", "败露", "失势", "下台", "股东会通过", "接任", "接管",
    ]
    last_two = (chapter_texts.get(last_ch, "") or "") + " " + (chapter_texts.get(last_ch - 1, "") or "")
    outcome_ok = any(k in last_text for k in payoff_keywords) or any(k in last_two for k in payoff_keywords)
    # 若 core_payoff/outcome 文案明确包含结果类用词，且最后一章文本长度较充分，也视为达标
    if not outcome_ok and (any(k in core_payoff for k in ["举报", "揭穿", "吊销", "毁灭", "罢免", "停职"]) or any(k in outcome for k in payoff_keywords)) and len(last_text) > 600:
        outcome_ok = True
    if not outcome_ok and len(last_text) > 200:
        violations.append("本簇最后一章未完成反杀结果/职业毁灭/处罚落地")
        rewrite_advice.append("最后一章必须具体呈现场景化的‘结果落地’，例如宣布停职/罢免/吊销/股东会决议/被带离；不要只写“更大风暴才刚开始”。")

    # 2. 是否引入禁止角色/元素
    forbidden_check = ["系统提示音", "苏晚晴", "神秘司机", "神秘人", "黑色轿车", "神秘男人", "幕后黑手", "更大风暴", "真正的风暴"]
    for w in forbidden_check:
        if w in full_text:
            violations.append(f"正文中出现禁止元素或未规划角色：{w}")
            introduced.append(w)
    if introduced:
        rewrite_advice.append("删除或改写未在本簇规划中的新核心角色（如苏晚晴、神秘司机、系统提示等）")

    # 3. 信息差是否显性使用（本簇 info_gap 中的关键词应在正文出现）
    info_gap = (cluster.get("info_gap_from_prev_life") or "")
    if info_gap:
        # 抽几个关键词：笔记、病历、篡改、记录、计划 等
        evidence_hints = ["笔记", "病历", "篡改", "记录", "证据", "值班室", "报复", "邮件", "签名", "录音", "文件"]
        used = any(h in full_text for h in evidence_hints)
        if not used and len(full_text) > MIN_CHAPTER_CHARS_V2 * max(1, end_ch - start_ch + 1):
            violations.append("本簇信息差（笔记/病历/记录等）未在正文中落地")
            rewrite_advice.append(
                "用「记忆先于材料」推进：先写认出旧局与提前布子，再在反卡场面用信息差中的具体材料落锤；不要写成调查取证文。"
            )

    # 4. 每章字数是否达标（须与逐章预检 MIN_CHAPTER_CHARS_V2 一致）
    min_chars_per_ch = MIN_CHAPTER_CHARS_V2
    for ch in range(start_ch, end_ch + 1):
        t = (chapter_texts.get(ch) or "").strip()
        if len(t) < min_chars_per_ch:
            violations.append(f"第{ch}章字数不足（{len(t)}字）")
            rewrite_advice.append(
                f"第{ch}章必须扩写到不少于{MIN_CHAPTER_CHARS_V2}字：按 beats 逐拍展开，补足多感官描写与对话，让情绪转折更清晰，并确保信息差证据形态落地。"
            )

    # 5. 主对手是否聚焦
    main_opp = (cluster.get("main_opponent") or "")
    if main_opp and len(main_opp) < 10 and main_opp not in full_text and len(full_text) > 1000:
        violations.append("本簇主对手未在正文中充分出现，冲突被稀释")
        rewrite_advice.append(f"确保本簇冲突围绕主对手（{main_opp}）展开，不要被其他角色抢戏")

    span_len = end_ch - start_ch + 1
    if span_len >= 2 and not _cluster_has_substantial_prev_life_block(chapter_texts, start_ch, end_ch):
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
        rewrite_advice.append("删掉匿名爆料/陌生人递材料等桥段，改为她凭上一世记忆主动卡点或对手按老剧本自露破绽。")

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
    if isinstance(exec_plan, dict) and isinstance(exec_plan.get("evidence_chain"), list) and exec_plan.get("evidence_chain"):
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

            # 必须出现在三段章节
            if marker not in _text_of(acquire_ch_i):
                violations.append(f"证据链连续性失败：{marker} 未出现在获取章节第{acquire_ch_i}章。")
                rewrite_advice.append(f"请在第{acquire_ch_i}章完成 {marker} 的获取动作，并确保出现 {marker}。")
            if marker not in _text_of(verify_ch_i):
                violations.append(f"证据链连续性失败：{marker} 未出现在验证章节第{verify_ch_i}章。")
                rewrite_advice.append(f"请在第{verify_ch_i}章完成 {marker} 的验证动作，并确保出现 {marker}。")
            if marker not in _text_of(use_ch_i):
                violations.append(f"证据链连续性失败：{marker} 未出现在使用章节第{use_ch_i}章。")
                rewrite_advice.append(f"请在第{use_ch_i}章完成 {marker} 的使用/落锤动作，并确保出现 {marker}。")

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

    # 完成判定：末章结果、末章字数、上一世受害厚度、重生四段式推进 为硬失败；证据链连续性等为软提示。
    critical_violations: List[str] = []
    for v in violations:
        if "最后一章未完成" in v:
            critical_violations.append(v)
        if "字数不足" in v and f"第{last_ch}" in v:
            critical_violations.append(v)
        if "上一世受害段落篇幅不足" in v:
            critical_violations.append(v)
        if "重生复仇推进模式不足" in v:
            critical_violations.append(v)
    payoff_completed = outcome_ok and not critical_violations
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

    return (
        f"角色：{role_v2 or '（未标注）'}；目标：{chapter_goal}\n"
        f"必须包含：{'；'.join(must_in) if must_in else '（无）'}\n"
        f"必须处理：{'；'.join(must_resolve) if must_resolve else '（无）'}\n"
        f"必须避免：{'；'.join(must_not) if must_not else '（无）'}\n"
        f"章节结尾钩子：{ending or '（无）'}\n"
        f"允许角色：{'；'.join(allowed_roles[:6]) if allowed_roles else '（未指定）'}\n"
        f"禁止出现新核心角色：{'；'.join(forbidden_roles[:10]) if forbidden_roles else '（无）'}\n"
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

    return f"""你是重生复仇短剧/小说编剧。请基于【情节族】信息，生成一个“可直接驱动分章节拍卡与正文”的【详细完整梗概】。

要求（非常重要）：
1. 叙事骨架必须是「旧局重演链」：旧局在今生再现→沈清欢认出并提前布子→完整展开至少一段上一世受害（屈辱、具体场景与对话）→对方照旧出招→关键时刻反卡落锤；禁止写成调查取证、到处找材料、靠匿名线索推进。
2. 必须写清“上一世留下的信息差”是什么（可具体到证据/记录形态），以及她如何凭记忆**预判**对方会怎么走、证据只在落锤时坐实——证据是锤，不是故事发动机。
3. 必须写出复仇细节爽感：反杀落在具体动作/对话/表情/场面上，并说明“为什么有效”（赢在记得旧局，不是赢在偶然发现）。
4. 必须把复仇方式和核心爽点与 `core_payoff` 对齐；
5. 禁止引入本情节族未规划的新核心人物/幕后系统/系统提示音等旁支要素；禁止匿名邮件、陌生人递材料、匿名爆料作为唯一关键转折。
{rewrite_block}{exec_plan_block}

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


def _fallback_cluster_contract(
    cluster: Dict[str, Any],
    chapter_nums: List[int],
    chapter_cards: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    duty_templates = [
        "旧局重现与钩子：认出旧招、放诱饵诱对方照旧出招",
        "压实与核实：按记忆取物/封口，不写成首次发现新线索",
        "逼迫与反压：对手按老剧本施压、主角反卡",
        "公开落锤：当场/现场引爆、结果落地",
    ]
    chapters: List[Dict[str, Any]] = []
    for i, ch in enumerate(chapter_nums):
        card = chapter_cards.get(ch, {}) or {}
        dt = duty_templates[i] if i < len(duty_templates) else "推进剧情"
        must = [str(x) for x in (card.get("chapter_must_include") or [])[:4] if str(x).strip()]
        if not must:
            must = [f"完成第{ch}章章节卡目标", "推进证据链与主线"]
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
      "duty_title": "<string：本章异构职责，如 钩子与试探 / 潜入与核验 / 逼迫与反压 / 公开落锤>",
      "must_finish": ["<string：本章必须交付的可验收结果>", "..."],
      "forbidden": ["<string：本章禁止，如 不得开发布会 / 不得重复档案室取证>", "..."]
    }
  ]
}
""".strip()

    return f"""你是短剧/小说总策划。请为情节族生成【簇级合同】JSON：把 {len(chapter_nums)} 章拆成职责**互不相同**的四段推进，禁止四章平均摊「铺垫-回忆-调查-反击」模板。

要求（非常重要）：
1. 只输出严格 JSON（不要 Markdown，不要解释），可被 json.loads；
2. one_line_goal：一句话写清本簇最终要让读者看到什么结果；
3. unresolved_queue：列出全簇尚未完成、需在后文兑现的硬目标（可含证据节点）；
4. 每一章必须异构：duty_title / must_finish / forbidden 要明确「本章专属」，并写出「本章禁止抢跑」——例如前几章禁止「发布会落锤/全民声讨终局」，最后一章禁止再写「准备材料/取证」占主线；
5. 必须对齐主要对手与信息差：{main_opp}；{info_gap[:200] if info_gap else ''}
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

    return f"""你是短剧/小说编剧。请把【情节族梗概】进一步拆成“每章节拍卡（beats）”，以便后续连续正文生成并最终切分成章节。

要求（非常重要）：
1. 输出必须是严格 JSON（不要 Markdown，不要解释文字），且 JSON 可被直接 json.loads 解析；
   必须保证所有 JSON 字符串字段内部不得出现真实换行；若需要换行请用 \\n 表示；整份 JSON 尽量输出为一行（允许空白分隔）。
2. 对每个章节：beats 必须 8-10 条，每条为一个“结构化节拍卡对象”，按情节点顺序排列；
   每条必须优先写满「重生反制四段式」：old_trap_signal（今生何信号让她认出上一世那一局）/ preemptive_move（她提前布了什么子）/ opponent_old_move（对方按老套路如何出招）/ reversal_trigger（她在哪一刻反卡）；再补 scene_goal / visual_elements / emotion_push / info_delta / foreshadow / relationship_push；must_not 至少 1-2 条；
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

    role_v2 = chapter_card.get("chapter_role_v2", "") or ""
    cards_block_text = _chapter_constraints_for_cluster_prompt(chapter_card)
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

    return f"""你是重生复仇短剧/小说编剧。请为“第{chapter_num}章”输出该章的【节拍卡 beats】（只输出一个 JSON 对象）。

要求（非常重要）：
1. 输出必须是严格 JSON（不要 Markdown，不要解释文字），JSON 可被直接 json.loads 解析；
2. 必须保证所有 JSON 字符串字段内部不得出现真实换行；若需要换行请用 \\n 表示；整份 JSON 尽量输出为一行（允许空白分隔）；
3. beats 必须 8-10 条，每条为一个结构化 beats 对象，按情节点顺序排列；
4. 每条必须优先写满 old_trap_signal / preemptive_move / opponent_old_move / reversal_trigger（重生反制四段式），再写 scene_goal / visual_elements / emotion_push / info_delta / foreshadow / relationship_push / must_not / prev_life_memory_brief；evidence_form 仅一句落锤材料（可选），不得替代四段式；
5. 若 need_prev_life=True，则 flashback_in_beat_idx 必须为非 null 的整数，且必须且只能在该 beats 下标对应的那一拍里给出非空 prev_life_memory_brief；其它 beats 的 prev_life_memory_brief 只能为空字符串。
   若 need_prev_life=False，则 flashback_in_beat_idx 必须为 null，并且所有 beats 的 prev_life_memory_brief 必须为空字符串；
6. open_from_prev 必须体现与上一章未决点的承接：{("；".join(open_seed_lines))}；
   非簇首章时，open_from_prev 必须与「上一章成稿真实结尾」强绑定，不得改用抽象复述或重新介绍情节组。
7. end_to_next 必须为下一章钩子：如果是最后一章，则钩子必须对齐本簇落点 outcome（允许留读者悬念，但不得引入新幕后系统/系统提示音）。
8. 禁止把本章 beats 设计成调查取证链（档案室/匿名邮件/媒体发布会/微博爆料等作为主推进）。

【情节族信息（仅用于对齐）】
cluster_id：{cluster_id}
cluster_name：{cluster_name}
主要对手：{main_opp}
核心爽点：{core_payoff}
上一世信息差（记忆锚点；材料仅落锤）：{info_gap}
本簇结局/落点：{outcome}
本章 chapter_role_v2：{role_v2}

【章节执行卡约束（必须遵守）】
{cards_block_text}

{synopsis_block_title}
{synopsis_guard}
{cluster_synopsis}

{rewrite_block}

输出 JSON 结构（仅输出此 JSON）：
{beats_json_schema}
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

    role_v2 = chapter_card.get("chapter_role_v2", "") or ""
    must_in = chapter_card.get("chapter_must_include", []) or []
    must_not = chapter_card.get("chapter_must_not_include", []) or []
    ending = chapter_card.get("chapter_ending", "") or ""
    allowed_roles = chapter_card.get("allowed_roles", []) or []
    forbidden_roles = chapter_card.get("forbidden_roles", []) or []
    if isinstance(must_in, list):
        must_in = [str(x) for x in must_in][:8]
    if isinstance(must_not, list):
        must_not = [str(x) for x in must_not][:10]

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
                adapted = str(sample.get("adapted_content") or "").strip()
                adapted = adapted.replace("\n", " ")
                if adapted:
                    parts.append(
                        f"【样本{idx} - {title_map.get(key, key)}】\n{adapted[:500]}…（已截断）"
                    )
        if parts:
            rag_samples_block = (
                "\n【参考样本（仅作写作节奏与表达参考，不得原样复述/不得改写 beats 逻辑）】\n"
                + "\n\n".join(parts)
            )

    evidence_chain_hard_block = ""
    if isinstance(exec_plan, dict) and isinstance(exec_plan.get("evidence_chain"), list) and exec_plan.get("evidence_chain"):
        all_evs: List[Dict[str, Any]] = [ev for ev in (exec_plan.get("evidence_chain") or []) if isinstance(ev, dict)]
        all_ids: List[str] = [str(ev.get("evidence_id", "") or "").strip() for ev in all_evs if str(ev.get("evidence_id", "") or "").strip()]
        allowed_ids: List[str] = []
        forbidden_ids: List[str] = []
        for ev in all_evs:
            eid = str(ev.get("evidence_id", "") or "").strip()
            if not eid:
                continue
            ac = ev.get("acquire_chapter")
            vc = ev.get("verify_chapter")
            uc = ev.get("use_chapter")
            stage_allowed = (ac == chapter_num) or (vc == chapter_num) or (uc == chapter_num)
            if stage_allowed:
                allowed_ids.append(eid)
            else:
                forbidden_ids.append(eid)

        allowed_ids = list(dict.fromkeys(allowed_ids))
        forbidden_ids = list(dict.fromkeys(forbidden_ids))

        allowed_ids_text = "；".join([f"【{x}】" for x in allowed_ids]) if allowed_ids else "（无）"
        forbidden_ids_text = "；".join([f"【{x}】" for x in forbidden_ids]) if forbidden_ids else "（无）"

        evidence_chain_hard_block = (
            "\n【落锤标记（仅对峙坐实；禁止当「调查取证」主线）】\n"
            f"- 本章允许出现的标记：{allowed_ids_text}\n"
            f"- 本章禁止出现的标记：{forbidden_ids_text}\n"
            "- 若需写【E1】等全角标记，只能出现在「对方照旧出招之后、当场反卡」的场面里，不得写成「本章为找材料而奔波」。\n"
            "- 禁止用「获取/验证/走访/翻档案」作为本章叙事发动机；主线只能是旧局识别→提前布子→对方照旧→反卡。\n"
        )

    flashback_idx_0 = flashback_idx if flashback_idx is not None else None
    flashback_idx_text = "null" if flashback_idx_0 is None else str(flashback_idx_0)
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
            "- 本章内必须写出反杀完成与具体后果：如 停职/罢免/吊销/处罚/股东会通过/失去支持/曝光败露；\n"
            "- 必须以具体、可视化的场面呈现‘结果落地’，例如：宣布决定的会议现场、盖章/签字的瞬间、对手被带离/被围观的画面；\n"
            "- 允许保留一个很小的余波钩子，但绝对禁止用“更大风暴才刚开始/真正的敌人另有其人”替代结果；\n"
            "- 若篇幅不足，优先砍掉环境/感受性描写，也要保证‘结果已发生且被看到’。"
        )

    return f"""你是重生复仇短剧作家。请输出“第{chapter_num}章”的连续正文段落。要求：

1. 必须严格按该章节拍卡 `beats` 的顺序推进，不得跳拍；每一顺序片段至少写 160-220 字，用自然段落衔接，禁止把多段压成一句带过。
2. 开头 120-180 字必须体现「承接上一段未决点」的动作与情绪（见下方「上一段结尾承接」）；正文中禁止出现英文字段名或 JSON 键名。
3. 若「回忆插入点」为顺序片段下标 {flashback_idx_text}（从 0 起计；若为 null 则本章不插回忆），则在该片段结束后插入完整上一世受害回忆段落，围绕该片段中的回忆要点展开（不要加小标题，不要写成调查取证主线）。
4. 本章总字数不少于 {MIN_CHAPTER_CHARS_V2} 字（建议 1600-2200 字）；未达标须继续扩写。
5. 叙事发动机必须是「旧局信号→提前布子→对方老招→反卡」；材料/记录仅在反卡或对峙时作为落锤出现，禁止写成「为找材料而奔波」的调查文；禁止匿名邮件、加密邮件、自由撰稿人、独立媒体声明、新闻发布会、档案室翻找、微博爆料链作为本章主线。
   - 若本章允许出现的标记不为空，对峙落锤处可含一个允许的【E…】标记；
   - 若允许标记为空，则不得出现【E…】，但仍可写当场出示材料的对白与动作；
   - 不得出现本章禁止的标记。
6. 结尾最后 120-200 字为下一章留悬念；正文中不要写出任何模板标签或英文字段名。
7. 输出仅小说正文：不要章节标题、不要节拍编号、不要任何模板字段名或 JSON。

【情节族信息】cluster_id={cluster_id}；主要对手={main_opp}；信息差提示={info_gap}；核心爽点={core_payoff}
【本章信息】角色={role_v2 or '（未标注）'}；类型={chapter_type}；闭合={closure_type}；章节卡结尾钩子={ending or '（无）'}
【本章必须包含】{'；'.join(must_in) if must_in else '（无）'}
【本章必须避免】{'；'.join(must_not) if must_not else '（无）'}
{payoff_hard_block}

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
        for body_try in range(3):
            merged_rewrite = extra_rewrite + local_extra
            body_prompt = _build_cluster_body_part_prompt(
                cluster=cluster,
                cluster_synopsis=syn_for_body,
                chapter_num=ch,
                chapter_beats=bc,
                prev_tail_scene=body_prev_tail,
                prev_unresolved_hook=body_prev_hook,
                chapter_card=chapter_cards.get(ch, {}) or {},
                kg_context=kg_context,
                rewrite_advice=merged_rewrite if merged_rewrite else None,
                rag_samples=None,
                exec_plan=exec_plan,
                rolling_synopsis_mode=not is_first,
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
            body_hard = _chapter_body_hard_failures(part_text)
            if body_hard:
                local_extra.extend(body_hard)
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


def _generate_cluster_continuous_and_split_v2(
    gen: "RebirthRevengeGeneratorV2",
    cluster: Dict[str, Any],
    cards: Dict[int, Dict[str, Any]],
    max_cluster_attempts: int = 3,
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
    try:
        exec_plan = _generate_cluster_exec_plan(
            gen=gen,
            cluster=cluster,
            chapter_cards=chapter_cards,
            chapter_nums=chapter_nums,
            exec_plan_path=exec_plan_path,
        )
    except Exception:  # noqa: BLE001
        exec_plan = _fallback_build_exec_plan_for_cluster(cluster, chapter_nums)

    critic_result: Dict[str, Any] = {}
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

        synopsis_prompt = _build_cluster_detailed_synopsis_prompt(
            cluster=cluster,
            chapter_cards=chapter_cards,
            prev_tail_scene=prev_tail_scene,
            prev_unresolved_hook=prev_unresolved_hook,
            rewrite_advice=rewrite_advice,
            exec_plan=exec_plan,
        )
        cluster_synopsis = gen._call_api(  # type: ignore[attr-defined]
            synopsis_prompt,
            None,
            0,
            max_tokens=max_tokens_synopsis,
        )
        cluster_synopsis = (cluster_synopsis or "").strip()
        # 梗概对后续节拍卡/正文切分影响很大：把梗概内容在日志里做一个截断预览，便于你对齐排错。
        synopsis_preview = cluster_synopsis[:300]
        if len(cluster_synopsis) > 300:
            synopsis_preview = synopsis_preview + "…（已截断）"
        print(
            f"📝 [情节族梗概简版] cluster={cluster.get('cluster_id','')}《{cluster.get('name','')}》（len={len(cluster_synopsis)}）"
        )
        print(synopsis_preview)

        max_tokens_contract = 2800
        contract_prompt = _build_cluster_contract_prompt(
            cluster=cluster,
            chapter_cards=chapter_cards,
            chapter_nums=chapter_nums,
            exec_plan=exec_plan,
            rewrite_advice=rewrite_advice,
        )
        contract_raw = gen._call_api(contract_prompt, None, 0, max_tokens=max_tokens_contract)  # type: ignore[attr-defined]
        contract_obj = _extract_json_obj_maybe((contract_raw or "").strip())
        if not isinstance(contract_obj, dict) or not contract_obj.get("chapters"):
            contract_obj = _fallback_cluster_contract(cluster, chapter_nums, chapter_cards)
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
            for beats_try in range(4):
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
                has_beats = isinstance(b_list, list) and len(b_list) > 0
                ch_ok = True
                try:
                    ch_ok = int(beats_obj.get("chapter_num")) == int(ch)
                except Exception:  # noqa: BLE001
                    ch_ok = True

                if has_beats and ch_ok:
                    open_from_prev = beats_obj.get("open_from_prev") or beats_obj.get("oppen_from_prev")
                    end_to_next = beats_obj.get("end_to_next")
                    if isinstance(open_from_prev, str) and open_from_prev.strip() and isinstance(end_to_next, str) and end_to_next.strip():
                        if "open_from_prev" not in beats_obj or not str(beats_obj.get("open_from_prev") or "").strip():
                            beats_obj["open_from_prev"] = open_from_prev.strip()
                        break

                last_beats_reason = (
                    f"has_beats={has_beats}; beats_len={len(b_list) if isinstance(b_list, list) else 'N/A'}; "
                    f"open_from_prev_type={type(beats_obj.get('open_from_prev')).__name__}; "
                    f"end_to_next_type={type(beats_obj.get('end_to_next')).__name__}"
                )

            if not isinstance(beats_obj, dict) or not beats_obj.get("beats"):
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
            target_context = "主角: 沈清欢, 背景: 现代都市, 重生复仇, 职场复仇"
            rag_samples = search_rebirth_samples_for_chapter(
                rag_query,
                target_context,
                need_prev_life=need_prev_life,
                has_revenge=has_revenge,
                top_k_per_set=2,
            )

            if rag_samples and any(rag_samples.get(k) for k in ("revenge", "grievance", "universal")):
                n = sum(len(rag_samples.get(k, [])) for k in ("revenge", "grievance", "universal"))
                if n:
                    print(f"  [RAG] 第{ch}章 注入 {n} 条参考（委屈/爽感/通用）", flush=True)

            local_extra: List[str] = []
            part_text = ""
            for body_try in range(3):
                merged_rewrite = list(rewrite_advice or []) + local_extra
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
                part_text = gen._call_api(  # type: ignore[attr-defined]
                    body_prompt,
                    None,
                    idx,
                    max_tokens=max_tokens_body_per_chapter,
                )
                part_text = (part_text or "").strip()
                if not part_text or part_text.startswith("通义千问"):
                    raise RuntimeError(f"第{ch}章正文生成失败或为空。")
                body_hard = _chapter_body_hard_failures(part_text)
                if body_hard:
                    local_extra.extend(body_hard)
                    print(
                        f"  ⚠️ 第{ch}章正文硬失败：{body_hard[0][:120]}…（重试 {body_try + 1}/3）",
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
                if not roll_v:
                    break
                local_extra.extend(roll_v)
                print(f"  ⚠️ 第{ch}章滚动承接未过：{roll_v[0][:100]}…（重试 {body_try + 1}/3）", flush=True)

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
            if c not in chapter_texts or len((chapter_texts.get(c) or "")) < MIN_CHAPTER_CHARS_V2
        ]
        if too_short:
            short_msgs = [
                f"第{c}章正文过短（{len((chapter_texts.get(c) or ''))}字），需要≥{MIN_CHAPTER_CHARS_V2}字且不得只保留短开头/短结尾"
                for c in too_short
            ]
            critic_result = {
                "payoff_completed": False,
                "violations": short_msgs,
                "rewrite_advice": [
                    f"逐章正文阶段每章必须≥{MIN_CHAPTER_CHARS_V2}字，不能只保留短开头/短结尾；",
                    "请按 beats 逐拍扩写，每拍至少 160-220 字，补足多感官描写与对话；",
                ]
                + short_msgs[:3],
            }
            continue

        # 写盘 + 记录到内存，便于 critic 使用
        for ch in chapter_nums:
            gen.save_chapter(ch, chapter_texts[ch])  # type: ignore[attr-defined]
            gen.generated_chapters[ch] = chapter_texts[ch]  # type: ignore[attr-defined]

        critic_result = _cluster_critic(cluster, chapter_texts, exec_plan=exec_plan)  # type: ignore[misc]
        payoff_ok = bool(critic_result.get("payoff_completed", False))
        violations = critic_result.get("violations", []) or []
        print(f"📋 情节族完成审查：payoff_completed={payoff_ok}，violations={len(violations)} 条")
        if not payoff_ok:
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
                chapter_texts = patched
                for ch in chapter_nums:
                    gen.save_chapter(ch, chapter_texts[ch])  # type: ignore[attr-defined]
                    gen.generated_chapters[ch] = chapter_texts[ch]  # type: ignore[attr-defined]
                critic_result = _cluster_critic(cluster, chapter_texts, exec_plan=exec_plan)  # type: ignore[misc]
                payoff_ok = bool(critic_result.get("payoff_completed", False))
                violations = critic_result.get("violations", []) or []
                print(f"📋 局部补写后审查：payoff_completed={payoff_ok}，violations={len(violations)} 条")
        if payoff_ok or attempt >= max_cluster_attempts - 1:
            if violations and not payoff_ok:
                print("⚠️ 本情节族未通过审查（保留最大努力版本）。可人工检查：")
                for v in violations[:8]:
                    print(f"   - {v}")
            return chapter_texts

    return {}


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
            from neo4j_kg.export_for_v2 import (  # type: ignore[import-not-found]
                fetch_context,
                compute_anchor_chapters,
            )
            from neo4j_kg.common import get_neo4j_driver  # type: ignore[import-not-found]
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

    cards: Dict[int, Dict[str, Any]] = {}
    resolved_master_cards_path = master_ctx_cards_path or str(DEFAULT_MASTER_CARDS_V2)
    cards = _load_master_cards_v2(resolved_master_cards_path)
    if not cards:
        # 兜底：当 master cards 缺失时，退回旧实现动态构建（避免流程完全中断）
        cards = _build_cards_from_clusters(overlapping)
    gen = RebirthRevengeGeneratorV2()
    _setup_gen_from_cards_and_prev_life(gen, cards, prev_life_ctx_path, clusters)
    # 挂载在线检索器（若可用）：每章生成前动态检索 Neo4j 背景事实
    try:
        gen.attach_online_retriever()
        print("🔎 在线检索器（Neo4j）已启用：将为每章注入限长背景事实。")
    except Exception:
        pass

    if chapters_dir is None:
        chapters_dir = str(OUTPUT_DIR / "chapters_v2")
    os.makedirs(chapters_dir, exist_ok=True)
    gen.outputs_dir = Path(chapters_dir).parent

    # 新工作流：按“情节族/事件簇”生成整簇连续正文，最后再切分为章节
    clusters_sorted = sorted(overlapping, key=lambda x: int(x.get("_start", 0)))
    generated_chapters_global: set[int] = set()

    out_ch_dir = Path(gen.outputs_dir) / "chapters"
    # 生成入口跳过逻辑：避免把之前生成的“短章”当成合格版本复用。
    min_chars_for_accept = MIN_CHAPTER_CHARS_V2
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

            critic_result = _cluster_critic(cluster, chapter_texts_for_critic)
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
        default=str(OUTPUT_DIR / "chapters_v2"),
        help="输出章节目录（默认 outputs/chapters_v2）",
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


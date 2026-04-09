#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重生复仇小说正文生成器
整合样本集结构、循环评分、自我训练、生成后评分等技术
"""

import os
import sys
import re
import json
import dashscope
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# Windows/PowerShell 可能默认使用 GBK 编码，遇到打印 emoji 时会触发 UnicodeEncodeError。
# 这里用 buffer 重新包装成 UTF-8（若环境不支持则静默失败），避免脚本因日志输出而中断。
try:
    import io

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# 导入项目模块
from smart_sample_search import search_and_adapt_samples, search_rebirth_samples_for_chapter
from optimized_rule_scorer import OptimizedRuleScorer
from emotion_analyzer import EmotionAnalyzer

# 迁移到 Neo4j：不再使用本地 JSON 知识图谱
_KG_AVAILABLE = False

# 配置API
API_Key_QW = "sk-a2966f4e37134351904851679884cb67"

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # .../bert_excitation_train
DEFAULT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"

class RebirthRevengeGenerator:
    """重生复仇小说正文生成器"""
    
    def __init__(self):
        self.scorer = OptimizedRuleScorer()
        self.emotion_analyzer = EmotionAnalyzer()
        self.master_ctx = {}  # 章节梗概（修正后，主用）
        self.master_ctx_original = {}  # 章节梗概（修正前，供模型对照）
        self.prev_life_ctx = {}  # 上一世线索
        self.project_root = PROJECT_ROOT
        self.outputs_dir = DEFAULT_OUTPUTS_DIR
        # 已生成章节（用于上下文），key 为章节号，value 为正文内容
        self.generated_chapters = {}
        
        # 本地 JSON 知识图谱已弃用，统一改用 Neo4j 在线检索
        self.use_knowledge_graph = False
        self._kg: Optional[object] = None

        # 人物、地点、事件类型提取（用于回忆触发）
        self.characters = set()
        self.locations = set()
        self.event_types = {
            '陷害', '嘲讽', '裁员', '拒绝', '举报', '开会', '会议', '当众', 
            '羞辱', '证据', '调查', '威胁', '背叛', '攻击', '拒绝', '无视'
        }
    
    def _resolve_path(self, path_str: str) -> Path:
        """
        将用户传入的路径解析成绝对路径：
        - 绝对路径：原样使用
        - 相对路径：相对 project_root 解析（避免受当前工作目录影响）
        """
        p = Path(path_str)
        if p.is_absolute():
            return p
        return (self.project_root / p).resolve()

    def load_existing_chapters(self, chapters_dir: Optional[str] = None, max_chapters: int = 30):
        """
        从磁盘加载已生成的章节，用于跨运行保持上下文连贯
        优先加载最近的若干章，避免一次性加载过多内容
        """
        if chapters_dir is None:
            chapters_path = self.outputs_dir / "chapters"
        else:
            chapters_path = self._resolve_path(chapters_dir)

        if not chapters_path.is_dir():
            return
        
        chapter_files = []
        for name in os.listdir(str(chapters_path)):
            if name.startswith("chapter_") and name.endswith(".txt"):
                try:
                    num_part = name[len("chapter_"):-len(".txt")]
                    chapter_num = int(num_part)
                    chapter_files.append((chapter_num, str(chapters_path / name)))
                except ValueError:
                    continue
        
        # 按章节号排序，只保留最近的 max_chapters 章
        chapter_files.sort(key=lambda x: x[0])
        if max_chapters > 0:
            chapter_files = chapter_files[-max_chapters:]
        
        loaded = 0
        for chapter_num, path in chapter_files:
            # 不覆盖当前运行已经生成并写入内存的内容
            if chapter_num in self.generated_chapters:
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        self.generated_chapters[chapter_num] = content
                        loaded += 1
            except Exception:
                continue
        
        if loaded > 0:
            print(f"📖 已从磁盘加载 {loaded} 章历史正文用于上下文衔接")
    
    def get_previous_chapter_content(self, chapter_num: int, chapters_dir: Optional[str] = None) -> Optional[str]:
        """获取上一章完整正文，用于衔接。优先内存，其次磁盘。"""
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
                with open(prev_file, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except Exception:
                pass
        return None
    
    def _load_master_ctx_into(self, file_path: Path, target: Dict[int, str]):
        """将梗概文件解析为 chapter_num -> 原文，写入 target。支持单章与第N-M章。"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        for line in content.split('\n'):
            line = line.strip()
            if not line:
                continue
            # 单章形式：第N章 ...：梗概
            # 允许在“第N章”和冒号之间出现角色/类型等额外说明（例如：第1章（grievance_build）：……）
            m_single = re.match(r'^第(\d+)章.*?[：:]\s*(.+)$', line)
            if m_single:
                chapter_num = int(m_single.group(1))
                target[chapter_num] = m_single.group(2).strip()
                continue
            m_range = re.match(r'^第(\d+)-(\d+)章\s+(.+)$', line)
            if m_range:
                start, end = int(m_range.group(1)), int(m_range.group(2))
                body = m_range.group(3).strip()
                if '：' in body:
                    body = body.split('：', 1)[1].strip()
                elif ':' in body:
                    body = body.split(':', 1)[1].strip()
                for ch in range(start, end + 1):
                    target[ch] = body

    def load_contexts(self, master_ctx_file, prev_life_ctx_file, original_master_ctx_file: Optional[str] = None):
        """加载章节梗概和上一世线索"""
        print("=" * 80)
        print("📚 加载上下文文件")
        print("=" * 80)

        master_path = self._resolve_path(master_ctx_file)
        prev_life_path = self._resolve_path(prev_life_ctx_file)
        
        # 加载章节梗概
        if not master_path.exists():
            raise FileNotFoundError(
                f"未找到章节梗概文件: {master_path}\n"
                f"提示：请确认文件存在，或用 --master-ctx 指定正确路径。"
            )
        # 若传入的是 JSON 章节卡（master_ctx_cards.json），则按 JSON 解析，每章一卡
        if master_path.suffix.lower() == ".json":
            print(f"✅ 检测到 JSON 章节卡文件: {master_path.name}，按结构化方式加载梗概")
            try:
                with open(master_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        ch = item.get("chapter_id")
                        if not isinstance(ch, int):
                            continue
                        # 将整张卡序列化为 JSON 字符串，后续 _parse_json_maybe 会解析出结构化字段
                        self.master_ctx[ch] = json.dumps(item, ensure_ascii=False)
                else:
                    print("⚠️ JSON 梗概内容不是列表，已忽略结构化加载，改用纯文本方式。")
                    self._load_master_ctx_into(master_path, self.master_ctx)
            except Exception as e:
                print(f"⚠️ 解析 JSON 梗概失败: {e}，改用纯文本方式加载")
                self._load_master_ctx_into(master_path, self.master_ctx)
        else:
            self._load_master_ctx_into(master_path, self.master_ctx)
        if original_master_ctx_file:
            orig_path = self._resolve_path(original_master_ctx_file)
            if orig_path.exists():
                self._load_master_ctx_into(orig_path, self.master_ctx_original)
                print(f"✅ 已加载修正前梗概: {orig_path.name} ({len(self.master_ctx_original)} 章)")
        elif "final" in str(master_path).lower() or "final" in master_ctx_file:
            orig_path = master_path.parent / "master_ctx.txt"
            if orig_path.exists():
                self._load_master_ctx_into(orig_path, self.master_ctx_original)
                print(f"✅ 已自动加载修正前梗概: {orig_path.name} ({len(self.master_ctx_original)} 章)")
        
        # 加载上一世线索
        if not prev_life_path.exists():
            print(f"⚠️  未找到上一世线索文件: {prev_life_path}")
            print("   将跳过上一世回忆触发（仍可生成正文，但不会插入回忆段落）")
            self.prev_life_ctx = {}
        else:
            with open(prev_life_path, 'r', encoding='utf-8') as f:
                content = f.read()
                for line in content.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    m = re.match(r'^第(\d+)章对应线索\s*[：:]\s*(.+)$', line)
                    if m:
                        chapter_num = int(m.group(1))
                        self.prev_life_ctx[chapter_num] = m.group(2).strip()
        
        print(f"✅ 已加载 {len(self.master_ctx)} 章章节梗概")
        print(f"✅ 已加载 {len(self.prev_life_ctx)} 条上一世线索")
        
        # 提取人物和地点（从线索中）
        self._extract_entities()
    
    def _extract_entities(self):
        """从线索中提取人物和地点"""
        # 常见人物名（从线索中提取）
        character_patterns = [
            r'林修远', r'赵明轩', r'陈主任', r'王秘书', r'经理', r'院长',
            r'主治医师', r'护士长', r'未婚夫', r'丈夫', r'男友'
        ]
        
        # 常见地点
        location_patterns = [
            r'ICU病房', r'医院', r'公司', r'会议室', r'办公室', r'茶水间',
            r'法庭', r'发布会', r'宴会', r'仓库', r'档案库'
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
    
    def _is_chapter_current_timeline_only(self, chapter_outline: str, prev_life_clue: Optional[str]) -> bool:
        """
        判断本章是否仅为「当前时间线」经历（如濒死、重生瞬间），不写上一世回忆。
        若梗概偏临终/病床/重生瞬间等，视为纯当前经历。
        """
        if not (chapter_outline or "").strip():
            return True
        # 新格式兼容：若章节卡明确标注 need_prev_life:false，则强制视为当前时间线
        if re.search(r'need_prev_life"\s*:\s*false', chapter_outline) or re.search(r'need_prev_life\s*[:=]\s*false', chapter_outline):
            return True
        text = (chapter_outline or "") + " " + (prev_life_clue or "")
        # 当前时间线典型关键词：濒死、病床、ICU、睁不开眼、归零、睁开眼、发现自己躺在、重生、日记本、不能再重蹈覆辙
        current_only_keywords = [
            "被扔在", "ICU", "病床上", "睁不开眼", "归零", "猛地睁开眼", "发现自己躺在",
            "熟悉的房间", "日记本", "不能再重蹈覆辙", "呼吸机", "心跳监测", "氧气面罩"
        ]
        # 若梗概明显在写「上一世回忆+今生反制」，则不是纯当前（“想起昏迷前”等仍属当前时间线）
        revenge_keywords = ["回忆", "反制", "报复", "复仇", "扳倒", "设局", "揭穿", "上一世"]
        has_revenge = any(k in text for k in revenge_keywords)
        has_current_only = any(k in chapter_outline for k in current_only_keywords)
        if has_revenge:
            return False
        return has_current_only

    def _parse_json_maybe(self, text: Optional[str]) -> Optional[Dict]:
        if not text:
            return None
        s = text.strip()
        if not (s.startswith("{") and s.endswith("}")):
            return None
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    def _render_master_card_for_prompt(self, card: Dict) -> str:
        """将 master_ctx_final 的 JSON 章节卡渲染为更适合模型执行的文本梗概"""
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

    def _render_prev_life_card_for_prompt(self, card: Dict) -> str:
        """将 prev_life_ctx_final 的 JSON 受害卡渲染为可插入回忆的素材摘要"""
        vp = card.get("victim_process") if isinstance(card.get("victim_process"), list) else []
        vp_text = "\n".join([f"- {x}" for x in vp])
        binding = card.get("binding", {}) if isinstance(card.get("binding"), dict) else {}
        return (
            "【上一世受害链条（结构化）】\n"
            f"- past_event_title: {card.get('past_event_title', '')}\n"
            f"- past_identity_state: {card.get('past_identity_state', '')}\n"
            f"- setup: {card.get('setup', '')}\n"
            f"- deception: {card.get('deception', '')}\n"
            f"- victim_process:\n{vp_text}\n"
            f"- collapse_point: {card.get('collapse_point', '')}\n"
            f"- humiliation_result: {card.get('humiliation_result', '')}\n"
            f"- emotion_core: {card.get('emotion_core', '')}\n"
            f"- present_relevance: {card.get('present_relevance', '')}\n"
            "\n【绑定】\n"
            f"- shared_trigger: {binding.get('shared_trigger', '')}\n"
            f"- past_core_harm: {binding.get('past_core_harm', '')}\n"
            f"- present_counterstrike: {binding.get('present_counterstrike', '')}\n"
        ).strip()

    def check_trigger_conditions(self, chapter_content: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        检查是否满足回忆触发条件
        返回: (是否触发, 触发类型, 触发内容)
        """
        # 检查人物
        for char in self.characters:
            if char in chapter_content:
                return True, 'character', char
        
        # 检查地点
        for loc in self.locations:
            if loc in chapter_content:
                return True, 'location', loc
        
        # 检查事件类型
        for event_type in self.event_types:
            if event_type in chapter_content:
                return True, 'event', event_type
        
        return False, None, None
    
    def build_generation_prompt(self, chapter_num: int, chapter_outline: str, 
                                prev_life_clue: Optional[str] = None,
                                trigger_info: Optional[Tuple] = None,
                                previous_chapters: List[str] = None) -> str:
        """构建生成提示词"""
        # 基础提示词
        prompt = f"""角色：你是一个专业的小说作者，擅长创作短剧风格的重生复仇小说正文

【核心要求】
1. 主线优先：必须严格按照本章章节梗概推进，不得偏离主线。
2. 字数要求：至少1000字，建议1000-1300字；不足1000字视为未达标，需扩写场景与对话。
3. 第三人称叙事，以场景推进为主，对话占比高，情绪外显。
4. 快节奏（最重要）：题材为重生复仇短剧，快节奏是第一要务。可将一个故事拆成两三章写，但每章都要节奏紧凑、能抓住读者，严禁拖沓。每章内至少有一个明确的情节点或反转。
5. 结尾留悬念或冲突升级。
6. **本书唯一女主姓名为【沈清欢】；禁止在正文中使用其他女主姓名（如林婉然、夏某某等），一律改写为【沈清欢】。**

【本章章节梗概】
{chapter_outline}

【故事展开顺序】
生成时按以下顺序组织内容：先看本章梗概的主要故事线 → 若涉及回忆则看上一世线索中主角曾受到的不公平待遇 → 再写这一世如何复仇或应对。两个强情绪方向：写上一世时突出对欺负者的愤怒憎恨与对主角的委屈同情（负面情绪）；写这一世复仇时重点营造爽感，让读者看完感到痛快、解气。

"""
        # 特殊章节：上一世临死（第1章）与重生觉醒（第2章）限制
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
- 严禁一开篇就直接写“她意识到自己重生了”，必须有“震惊 → 怀疑 →验证 → 确认”的过程。

"""
        
        # 是否有“上一世”内容：根据梗概与线索判断，若梗概偏濒死/临终/重生瞬间等单一时间线，则只写当前经历
        outline_is_current_only = self._is_chapter_current_timeline_only(chapter_outline, prev_life_clue)
        
        if outline_is_current_only or not prev_life_clue:
            prompt += """
【本章类型：当前时间线】
本章梗概以当前时间线为主（如濒死、被冷眼旁观、重生瞬间等），不涉及“回忆上一世再反制”的结构。请只写当前经历，不要插入上一世回忆段落，否则会破坏节奏与逻辑。

"""
        elif trigger_info and prev_life_clue:
            is_triggered, trigger_type, trigger_content = trigger_info
            if is_triggered:
                prompt += f"""
【本章类型：含上一世回忆与今生反制】
检测到与上一世相关的人/地/事：{trigger_type} = {trigger_content}。请在正文中自然融入以下结构（不要输出【触发场景】【上一世回忆】等小标题，直接写正文、用句式点明即可）：

1. 当前情境中出现{trigger_content}时，自然过渡到回忆。
2. 上一世回忆：必须在正文中直接点明是上一世，例如用「上一世，我……」「记得在上一世，我……」「上一世他曾……」等句式，让读者明确知道这是回忆。回忆要写具体场景（对话/动作/结果），体现主角当时被打压、被误解或失败，绝不写上一世成功或胜利。情绪上突出对欺负者的愤怒、憎恨，以及对主角的委屈、同情（负面情绪）。
   - 若【本章章节梗概】中包含 `flashback_breakpoint` / `past_ratio_max`，必须严格遵守：在断点位置插入回忆；回忆段落占比不得超过 `past_ratio_max`（强制 < 40%）。
3. 情绪变化：主角冷静、预判、不再犯错。
4. 今生反制：体现提前准备、反向布局、让对方落入陷阱。这一世复仇部分要重点营造爽感，让读者感到痛快、解气。

【相关上一世线索】
{prev_life_clue}

"""
            else:
                prompt += """
【回忆与反制】
若梗概中未出现与上一世明显对应的人物/地点/事件类型，不要硬插回忆；只按梗概写当前故事线即可。

"""
        else:
            prompt += """
【回忆与反制】
若本章没有可用的上一世线索或触发条件，不要硬插回忆，只按梗概写当前经历。

"""
        
        # 添加前文摘要（最近3章），用于连贯
        if previous_chapters:
            prompt += "\n【前文摘要】（保持连贯性）\n"
            for i, prev_chapter in enumerate(previous_chapters[-3:], 1):
                preview = prev_chapter[:200] + "..." if len(prev_chapter) > 200 else prev_chapter
                prompt += f"前文{i}: {preview}\n"
        
        # 前文已出现的情节与场景——禁止在本章重复（尤其开篇与核心情节点）
        if previous_chapters:
            no_repeat = self._build_no_repeat_summary(previous_chapters)
            if no_repeat:
                prompt += "\n【前文已出现的情节与场景 - 禁止重复】（重要）\n"
                prompt += no_repeat
                prompt += (
                    "\n要求：本章的开头、场景描写、核心情节点必须与上述前文明显区分，"
                    "不得复制或换汤不换药地重复前文已有内容（如相同的开篇环境、相同顺序的对话、相同的情节点）。"
                    "请严格按本章梗概写出本章独有的进展。\n"
                )
        
        # 添加情绪强度要求
        prompt += """
【情绪强度要求】（核心！）
1. 情绪强度要求：文本必须包含强烈的情感表达，情绪强度得分应达到0.6以上
2. 多维度情绪：要包含多种情绪维度（恐惧、紧张、期待、愤怒、悲伤、喜悦等），避免单一情绪
3. 情绪深度：不仅要有表层情绪（直接表达），更要有深层情绪（通过隐喻、转折、对比等隐含表达）
4. 情绪转折：文本中要有明显的情绪变化和转折，制造情绪波动（从压迫→焦灼→冷静→决断等）
5. 情绪密度：每100字至少包含2-3个情绪词汇，情绪句子占比应达到40%以上
6. 情绪渲染技巧：
   - 使用具体细节描写增强情绪感染力（如"心跳仿佛要冲出胸腔"而非"很紧张"）
   - 通过环境描写烘托情绪（如"黑暗的角落"、"急促的脚步声"）
   - 使用短句和断句制造紧张感
   - 通过对比和转折增强情绪冲击
   - 描写身体反应增强代入感（如"手心冒汗"、"呼吸急促"）

【人物基调】
- 女主：冷静、克制、带记忆优势
- 反派：自信、轻视女主，认为她软弱好欺负

【输出格式】
直接输出正文，不要添加章节标题、【触发场景】【上一世回忆】等小标题或总结说明；回忆部分用「上一世，我……」等句式在正文中点明即可。

"""
        
        return prompt
    
    def _build_no_repeat_summary(self, previous_chapters: List[str], 
                                  max_chapters: int = 3,
                                  opening_chars: int = 380) -> str:
        """
        从前文列表中提取每章的开头与关键情节点，用于提示「禁止重复」。
        返回供放入提示词的字符串，便于模型避免与前文雷同的开篇或情节。
        """
        if not previous_chapters:
            return ""
        lines = []
        chunk = previous_chapters[-max_chapters:]
        for i, content in enumerate(chunk, 1):
            if not (content or "").strip():
                continue
            opening = content.strip()[:opening_chars]
            if len(content.strip()) > opening_chars:
                opening += "..."
            label = "上一章（紧接本章）" if i == len(chunk) else f"前文片段{i}（较早）"
            lines.append(f"{label}已写（开头与前半段，请勿在本章重复）：\n{opening}\n")
        return "\n".join(lines) if lines else ""

    def extract_high_score_snippets(self, previous_chapters: Optional[List[str]],
                                    min_score: float = 70,
                                    max_snippets: int = 5) -> List[Dict]:
        """
        从前文中提取高评分片段，用作情绪与节奏的参考样本
        参考 enhanced_rag_generator.extract_high_score_snippets_from_context 的思想
        """
        if not previous_chapters:
            return []
        
        snippets: List[Dict] = []
        
        for content in previous_chapters:
            if not content:
                continue
            # 按段落分割，避免把整章都拿来评分
            paragraphs = content.split("\n\n")
            for para in paragraphs:
                para = para.strip()
                if len(para) <= 50:
                    continue
                try:
                    score = self.scorer.calculate_score(para)
                except Exception:
                    continue
                if score >= min_score:
                    snippets.append({
                        "content": para,
                        "score": score
                    })
        
        # 按评分从高到低排序，取前若干个
        snippets.sort(key=lambda x: x["score"], reverse=True)
        return snippets[:max_snippets]
    
    def build_generation_prompt_v2(self, chapter_num: int, chapter_outline: str,
                                   prev_life_clue: Optional[str],
                                   trigger_info: Optional[Tuple],
                                   previous_chapters: Optional[List[str]],
                                   high_score_snippets: Optional[List[Dict]]) -> str:
        """
        在原有提示词基础上，补充前文高分片段参考，并进一步强调梗概约束和情绪目标
        """
        # 先用原有逻辑构建基础提示词，保持兼容性
        prompt = self.build_generation_prompt(
            chapter_num=chapter_num,
            chapter_outline=chapter_outline,
            prev_life_clue=prev_life_clue,
            trigger_info=trigger_info,
            previous_chapters=previous_chapters or []
        )
        
        # 在核心要求后追加更明确的约束说明
        prompt += """

【主线与上一世约束补充说明】
1. 本章所有事件必须在【本章章节梗概】中能找到对应的基础设定，禁止随意新增无关支线或跳过既定冲突。
2. 上一世内容仅能用于强化今生的对比与反制，不得改写上一世结局为成功或扭转为正向结果。
3. 如需引入新的角色或场景，必须与梗概中已有的矛盾方向高度相关，且规模控制在辅助程度，不能抢主线。
"""
        
        # 添加前文高评分片段参考（情绪与结构示范）
        if high_score_snippets:
            prompt += "\n【前文高评分片段参考】\n"
            for idx, snip in enumerate(high_score_snippets, 1):
                content = snip.get("content", "")
                score = snip.get("score", 0.0)
                preview = content[:150] + "..." if len(content) > 150 else content
                prompt += f"片段{idx} (评分: {score:.1f}): {preview}\n"
            
            prompt += (
                "\n以上片段在情绪密度、冲突设计和节奏控制上表现优异，本章创作时应在这些方面向它们靠近，"
                "尤其是情绪层次、环境烘托和身体反应描写。生成新内容时，请主动模仿这些片段的情绪推进方式。\n"
            )
        
        return prompt
    
    def generate_with_rag(self, chapter_num: int, user_input: str, 
                          num_versions: int = 3, max_iterations: int = 3,
                          min_emotion_intensity: float = 0.6) -> List[Dict]:
        """使用RAG和循环评分生成章节"""
        print(f"\n{'='*80}")
        print(f"📝 生成第{chapter_num}章")
        print(f"{'='*80}")
        
        # 获取章节梗概
        chapter_outline_raw = self.master_ctx.get(chapter_num, "")
        if not chapter_outline_raw:
            print(f"❌ 未找到第{chapter_num}章的章节梗概")
            return []
        
        # 获取上一世线索
        prev_life_clue_raw = self.prev_life_ctx.get(chapter_num)

        # 兼容新格式：JSON 章节卡 / JSON 受害卡
        chapter_outline_card = self._parse_json_maybe(chapter_outline_raw)
        prev_life_card = self._parse_json_maybe(prev_life_clue_raw) if prev_life_clue_raw else None

        if chapter_outline_card:
            chapter_outline = self._render_master_card_for_prompt(chapter_outline_card)
        else:
            chapter_outline = chapter_outline_raw

        if prev_life_card:
            prev_life_clue = self._render_prev_life_card_for_prompt(prev_life_card)
        else:
            prev_life_clue = prev_life_clue_raw
        
        # 检查触发条件（新格式优先用章节卡的 flashback_trigger）
        trigger_info = None
        if chapter_outline_card:
            present = chapter_outline_card.get("present", {}) if isinstance(chapter_outline_card.get("present"), dict) else {}
            need_prev = present.get("need_prev_life", True)
            trig = present.get("flashback_trigger")
            if need_prev and trig and prev_life_clue:
                trigger_info = (True, "card_trigger", str(trig))
            else:
                trigger_info = self.check_trigger_conditions(chapter_outline)
        else:
            trigger_info = self.check_trigger_conditions(chapter_outline)
        
        # 获取前文（最近5章），用于保证章节衔接和高分片段提取
        previous_chapters = []
        for i in range(max(1, chapter_num - 5), chapter_num):
            if i in self.generated_chapters:
                previous_chapters.append(self.generated_chapters[i])
        
        # 从前文中提取高评分片段，作为情绪与结构参考
        high_score_snippets = self.extract_high_score_snippets(previous_chapters)
        
        # RAG检索相似样本（加入上一世线索以便样本更贴近因果线）
        target_context = "主角: 沈清欢, 背景: 现代都市, 重生复仇, 职场复仇"
        rag_query = chapter_outline
        if prev_life_clue:
            rag_query = f"{chapter_outline}\n上一世线索: {prev_life_clue}"
        adapted_samples = search_and_adapt_samples(
            rag_query,
            target_context,
            top_k=3,
            min_similarity=0.3
        )
        
        if adapted_samples:
            print(f"✅ 找到 {len(adapted_samples)} 个RAG样本")
        else:
            print("⚠️  未找到RAG样本，将使用基础生成")
        
        # 生成多个版本
        all_versions = []
        
        for version_num in range(1, num_versions + 1):
            print(f"\n🔄 生成版本 {version_num}/{num_versions}")
            
            # 构建提示词（增强版，整合梗概、上一世线索、前文摘要和高分片段）
            prompt = self.build_generation_prompt_v2(
                chapter_num=chapter_num,
                chapter_outline=chapter_outline,
                prev_life_clue=prev_life_clue,
                trigger_info=trigger_info,
                previous_chapters=previous_chapters,
                high_score_snippets=high_score_snippets
            )
            
            # 添加RAG样本到提示词
            if adapted_samples:
                prompt += "\n【RAG高评分样本参考】\n"
                for i, sample in enumerate(adapted_samples[:2], 1):
                    prompt += f"样本{i} (相似度: {sample['similarity']:.1%}): {sample['adapted_content'][:200]}...\n"
                prompt += "\n请参考以上样本的写作风格和情节设计。\n"
            
            # 循环生成和优化
            best_content = None
            best_score = 0
            best_emotion = 0
            emotion_feedback = None
            
            for iteration in range(max_iterations):
                if iteration > 0:
                    print(f"  🔄 第{iteration + 1}次优化（情绪强度: {emotion_feedback.get('intensity', 0):.3f}）")
                
                # 调用API生成
                content = self._call_api(prompt, emotion_feedback, iteration)
                
                if not content or content.startswith("通义千问 API"):
                    print(f"  ❌ 生成失败: {content}")
                    continue
                
                # 字数检查（中文按字符数，至少1000字）
                char_count = len(content.strip())
                word_short = char_count < 1000
                
                # 评分
                score = self.scorer.calculate_score(content)
                
                # 情绪分析
                emotion_result = self.emotion_analyzer.analyze(content)
                emotion_intensity = emotion_result.intensity
                
                print(f"  📊 评分: {score:.2f}, 情绪: {emotion_intensity:.3f}, 字数: {char_count}", end="")
                
                # 判断是否达标：情绪+评分+字数均达标才通过
                if emotion_intensity >= min_emotion_intensity and score >= 60 and not word_short:
                    print(" ✅")
                    best_content = content
                    best_score = score
                    best_emotion = emotion_intensity
                    break
                else:
                    if word_short:
                        print(" ⚠️ 字数不足")
                    else:
                        print(" ⚠️")
                    # 准备反馈用于下次迭代
                    emotion_feedback = {
                        'intensity': emotion_intensity,
                        'label': emotion_result.label,
                        'emotion_depth': emotion_result.emotion_depth,
                        'emotion_transition': emotion_result.emotion_transition,
                        'emotion_word_density': emotion_result.emotion_word_density,
                        'suggestion': self._get_emotion_suggestion(emotion_result),
                        'char_count': char_count,
                        'word_short': word_short,
                    }
                    
                    # 更新提示词（添加情绪、字数、连续性反馈）
                    if iteration < max_iterations - 1:
                        prompt = self._add_emotion_feedback(prompt, emotion_feedback, iteration + 1)
                    
                    # 记录当前最佳
                    if emotion_intensity > best_emotion or (emotion_intensity == best_emotion and score > best_score):
                        best_content = content
                        best_score = score
                        best_emotion = emotion_intensity
            
            if best_content:
                all_versions.append({
                    'version': version_num,
                    'content': best_content,
                    'score': best_score,
                    'emotion_intensity': best_emotion,
                    'chapter': chapter_num,
                    'generated_at': datetime.now().isoformat()
                })
                print(f"  ✅ 版本{version_num}完成（评分: {best_score:.2f}, 情绪: {best_emotion:.3f}）")
            else:
                print(f"  ❌ 版本{version_num}生成失败")
        
        return all_versions
    
    def _call_api(
        self,
        prompt: str,
        emotion_feedback: Optional[Dict] = None,
        iteration: int = 0,
        max_tokens: Optional[int] = None,
    ) -> str:
        """调用通义千问API"""
        dashscope.api_key = API_Key_QW
        
        system_message = {"role": "system", "content": prompt}
        user_message = {"role": "user", "content": "请开始创作"}

        # 网络/平台偶发卡住时，为了避免“无输出无限等待”，做两层保护：
        # 1) 尝试传入 dashscope 的超时参数（若 SDK 支持）
        # 2) 再用线程硬超时兜底（保证本次调用不会超过 hard_timeout_s）
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
                # 有些 dashscope 版本可能不接受 timeout 参数，因此先尝试，失败则回退到不传 timeout。
                try:
                    return dashscope.Generation.call(**call_kwargs, timeout=timeout_s)
                except TypeError:
                    return dashscope.Generation.call(**call_kwargs)

            try:
                # 用线程硬超时兜底：即便 SDK 不支持 timeout，也不会无限卡死在 result 返回上。
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
                # 非预期返回也视为一次失败，触发重试。
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

            # 还没成功就重试（最后一次直接返回 err）
            if attempt < max_retries - 1:
                sleep_s = backoff_s * (2**attempt)
                print(f"[API] retry after {sleep_s:.1f}s...", flush=True)
                time.sleep(sleep_s)
            else:
                return err
    
    def _clean_markdown(self, text: str) -> str:
        """去除 Markdown 格式符号"""
        if not text:
            return ""
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
        text = re.sub(r'### (.*)', r'\1', text)
        text = re.sub(r'---', '', text)
        text = re.sub(r'#+', '', text)
        return text.strip()

    def _normalize_heroine_names(self, text: str) -> str:
        """
        最后一层兜底：统一正文中的女主姓名为「沈清欢」。
        - 显式错误名：林婉然/林婉/婉然 等
        - 林** / 夏** 两字名（高概率是女主名），以及「女主」「女主角」等泛指
        """
        if not text:
            return text
        # 显式错误名
        patterns = [
            r"林婉然",
            r"林婉",
            r"婉然",
        ]
        for p in patterns:
            text = re.sub(p, "沈清欢", text)
        # 林** / 夏** 两字名
        text = re.sub(r"林[\u4e00-\u9fff]{1,2}", "沈清欢", text)
        text = re.sub(r"夏[\u4e00-\u9fff]{1,2}", "沈清欢", text)
        # 泛指女主
        text = re.sub(r"女主角", "沈清欢", text)
        text = re.sub(r"女主", "沈清欢", text)
        return text
    
    def _get_emotion_suggestion(self, emotion_result) -> str:
        """获取情绪改进建议"""
        suggestions = []
        
        if emotion_result.intensity < 0.6:
            suggestions.append("情绪强度不足，建议增加更多情绪词汇和细节描写")
        
        if emotion_result.emotion_depth < 0.4:
            suggestions.append("情绪深度不足，建议使用隐喻、转折、对比等手法表达深层情绪")
        
        if emotion_result.emotion_transition == 'stable':
            suggestions.append("情绪变化不明显，建议增加情绪转折和波动")
        
        if emotion_result.emotion_word_density < 0.02:
            suggestions.append("情绪词汇密度不足，建议每100字至少包含2-3个情绪词汇")
        
        return "；".join(suggestions) if suggestions else "情绪表达良好"
    
    def _add_emotion_feedback(self, base_prompt: str, emotion_feedback: Dict, 
                              iteration: int) -> str:
        """添加情绪与字数反馈到提示词"""
        parts = ["""
【第{0}次优化要求】
""".format(iteration)]
        
        if emotion_feedback.get('word_short'):
            parts.append(f"""
- 字数不足：上一版仅{emotion_feedback.get('char_count', 0)}字，必须扩写至至少1000字。请增加场景描写、对话与冲突细节，不要删减已有内容。
""")
        
        parts.append(f"""
- 情绪方面：当前情绪强度 {emotion_feedback.get('intensity', 0):.3f}（目标>=0.6），主导情绪 {emotion_feedback.get('label', 'N/A')}，情绪深度 {emotion_feedback.get('emotion_depth', 0):.3f}，情绪转折 {emotion_feedback.get('emotion_transition', 'N/A')}。
- 改进建议：{emotion_feedback.get('suggestion', '请增强情绪表达')}

请根据以上反馈重新创作。若字数不足，优先扩写至1000字以上；同时加强情绪表达与节奏感。
""")
        if emotion_feedback.get('continuity_feedback'):
            parts.append("\n【连续性要求】（必须遵守）\n" + emotion_feedback['continuity_feedback'] + "\n")
        if emotion_feedback.get('structure_feedback'):
            parts.append("\n【上一世结构要求】（必须遵守）\n" + emotion_feedback['structure_feedback'] + "\n")
        return base_prompt + "".join(parts)
    
    def select_best_version(self, versions: List[Dict]) -> Optional[Dict]:
        """选择最佳版本（综合评分和情绪强度）"""
        if not versions:
            return None
        
        # 综合评分 = 规则评分 * 0.4 + 情绪强度 * 100 * 0.6
        for v in versions:
            v['composite_score'] = v['score'] * 0.4 + v['emotion_intensity'] * 100 * 0.6
        
        best = max(versions, key=lambda x: x['composite_score'])
        return best
    
    def save_chapter(self, chapter_num: int, content: str, output_dir: Optional[str] = None):
        """保存章节"""
        if output_dir is None:
            out_dir = self.outputs_dir / "chapters"
        else:
            out_dir = self._resolve_path(output_dir)

        os.makedirs(str(out_dir), exist_ok=True)
        filepath = str(out_dir / f"chapter_{chapter_num:03d}.txt")
        
        # 保存前做一次女主姓名兜底清洗，防止被样本或大模型带歪
        cleaned_content = self._normalize_heroine_names(content or "")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(cleaned_content)
        
        print(f"💾 已保存到: {filepath}")
        return filepath
    
    def _extract_prev_chapter_tail_and_hook(self, prev_chapter_full: Optional[str]) -> Tuple[str, str]:
        """从上一章全文用大模型提取：最后场景、未解决钩子。用于下一章强制接续。"""
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

    def _check_past_block_ratio(self, chapter_content: str, need_prev_life: bool,
                                min_ratio: float = 0.35, max_ratio: float = 0.5,
                                min_chars: int = 350) -> Tuple[float, str]:
        """
        检查上一世回忆段落是否存在且占比达标。仅当 need_prev_life=True 时才有意义。
        返回 (0~1 分数, 反馈说明)。不需要上一世时返回 (1.0, "")。
        """
        if not need_prev_life or not chapter_content:
            return 1.0, ""
        total = len(chapter_content.strip())
        if total < 600:
            return 0.0, "正文过短，无法判断上一世段落"
        start_markers = ["上一世", "记得", "那时", "当时", "那年", "前世", "曾经"]
        first_i = len(chapter_content)
        for m in start_markers:
            i = chapter_content.find(m)
            if i != -1 and i < first_i:
                first_i = i
        if first_i >= len(chapter_content):
            return 0.0, "未检测到上一世回忆段落（需包含“上一世/记得/那时/当时”等并写成可感知场景，占比约20%~32%）"
        end_markers = ["这一世", "今生", "现在", "眼下", "回过神来", "收回思绪"]
        end_i = len(chapter_content)
        for em in end_markers:
            j = chapter_content.find(em, first_i + 80)
            if j != -1:
                end_i = min(end_i, j + 20)
        past_len = min(end_i - first_i, 800)
        if past_len < 0:
            past_len = 200
        ratio = past_len / total if total else 0
        # 低于下限：惩罚
        if ratio < min_ratio and past_len < min_chars:
            return max(0.0, ratio / min_ratio), (
                f"上一世回忆段落过短（约{past_len}字，占比{ratio*100:.0f}%），"
                f"要求至少{min_chars}字，且占比不得低于 {min_ratio*100:.0f}%；"
                "必须写成完整场景，包含四步：假性温和→突然反咬→无人帮她→结果性伤害。"
            )
        # 高于上限：也给出反馈，要求缩短上一世部分，把更多篇幅留给今世复仇
        if ratio > max_ratio:
            return max(0.0, (1.0 - ratio) / (1.0 - max_ratio + 1e-6)), (
                f"上一世回忆段落过长（约{past_len}字，占比{ratio*100:.0f}%），"
                f"要求占比不得高于 {max_ratio*100:.0f}%，"
                "需要压缩回忆篇幅，把更多空间留给这一世的布局、反击和复仇后续影响。"
            )
        # 在目标区间 [min_ratio, max_ratio] 内视为 1.0
        return 1.0, ""

    def _check_continuity(self, chapter_content: str, prev_tail_scene: str, prev_unresolved_hook: str) -> Tuple[float, str]:
        """
        简单连续性审查：本章开头是否接住上一章尾钩。
        返回 (0~1 分数, 反馈说明)。无上一章时返回 (1.0, "")。
        """
        if not prev_tail_scene and not prev_unresolved_hook:
            return 1.0, ""
        head = chapter_content[:400] if len(chapter_content) > 400 else chapter_content
        combined = (prev_tail_scene + " " + prev_unresolved_hook).strip()
        if not combined:
            return 1.0, ""
        # 提取关键词：2字及以上的词
        words = set(re.findall(r'[\u4e00-\u9fff]{2,}', combined))
        words = {w for w in words if len(w) >= 2}
        if not words:
            return 0.5, "无法提取尾钩关键词"
        hit = sum(1 for w in words if w in head)
        score = hit / min(len(words), 8)  # 最多看8个词
        score = min(1.0, score)
        if score < 0.25:
            return score, f"本章开头未接住上一章尾钩（关键词命中{hit}/{len(words)}），请从上一章最后场景/未解决钩子直接续写，禁止另起新场景。"
        if score < 0.5:
            return score, f"本章开头与上一章尾钩衔接较弱（命中{hit}/{len(words)}），请在前300字内明确承接上一章结尾。"
        return score, ""

    def generate_beat_card(self, chapter_num: int, outline_corrected: str, outline_original: str,
                           prev_life_clue: Optional[str] = None) -> Tuple[str, str, str, str, str]:
        """
        生成节拍卡，并解析「本章开头承接」「本章结尾钩子」「章节类型」「闭合类型」。
        返回 (beat_card文本, open_from_prev, end_to_next, chapter_type, closure_type)。
        """
        prompt = f"""你是一位短剧/小说编剧。请根据下面第{chapter_num}章的【修正后梗概】与【修正前梗概】，生成本章的节拍卡（beats），并补充跨章与类型字段。

要求：
1. 节拍卡 5-7 条，每条一句话，按情节点顺序排列；若涉及「上一世回忆」，请在某一条后注明「此处插入上一世回忆」。
2. 判定本章类型（四选一）：
   - revenge_payoff：本章有旧伤且当章要完成一次打脸/反杀（今生冲突→上一世回忆→今生反制爽点）
   - grievance_build：本章重点加深委屈积累，爽点可弱（压迫→上一世更惨→忍住/埋证据）
   - present_only：本章主要推进调查/埋线/搜证，无或极少上一世
   - cross_chapter：本章属于跨章冲突的中段，不要求单章闭环但须局势升级
3. 判定闭合类型（三选一）：
   - full_close：本章必须完成一个小事件闭环（冲突→回忆→反制→对方失态/后果→钩子）
   - half_close：本章可停在爆点（证据刚亮、重要人物刚进场），结果留到下一章
   - chain_close：连续事件中段，不要求单章闭环，但须有局势升级
4. 必须输出：
   - 本章开头必须承接：若为第1章填「无」；否则填上一章结尾留下的具体动作/场景/钩子。
   - 本章结尾必须留下钩子：本章结束时留给下一章的具体悬念/未完成动作。

【修正后梗概】
{outline_corrected}

【修正前梗概】
{outline_original or "（无）"}
"""
        if prev_life_clue:
            prompt += f"""
【本章可用的上一世线索】
{prev_life_clue}
"""
        prompt += """

请严格按以下格式输出（不要其他内容）：
节拍卡：
1. xxx
2. xxx
...
章节类型：
闭合类型：
本章开头必须承接：
本章结尾必须留下钩子：
"""
        out = self._call_api(prompt, emotion_feedback=None, iteration=0)
        if not out or out.startswith("通义千问"):
            return "", "", "", "present_only", "full_close"
        out = out.strip()
        open_from_prev, end_to_next = "", ""
        chapter_type, closure_type = "present_only", "full_close"
        lines = out.split("\n")
        beat_lines = []
        for i, line in enumerate(lines):
            line_strip = line.strip()
            if line_strip.startswith("本章开头必须承接") or "本章开头必须承接" in line_strip:
                open_from_prev = line_strip.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif line_strip.startswith("本章结尾必须留下钩子") or "本章结尾必须留下钩子" in line_strip:
                end_to_next = line_strip.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif line_strip.startswith("章节类型") or "章节类型" in line_strip:
                raw = line_strip.split("：", 1)[-1].split(":", 1)[-1].strip().lower()
                for t in ("revenge_payoff", "grievance_build", "present_only", "cross_chapter"):
                    if t in raw or t.replace("_", " ") in raw:
                        chapter_type = t
                        break
            elif line_strip.startswith("闭合类型") or "闭合类型" in line_strip:
                raw = line_strip.split("：", 1)[-1].split(":", 1)[-1].strip().lower()
                for t in ("full_close", "half_close", "chain_close"):
                    if t in raw or t.replace("_", " ") in raw:
                        closure_type = t
                        break
            elif "节拍卡" in line_strip and "：" not in line_strip:
                continue
            else:
                beat_lines.append(line)
        beat_card = "\n".join(beat_lines).strip()
        if "节拍卡：" in out:
            idx = out.find("节拍卡：")
            rest = out[idx + 4:].strip()
            for sep in ("章节类型", "闭合类型", "本章开头必须承接", "本章结尾必须留下钩子"):
                if sep in rest:
                    beat_card = rest.split(sep)[0].strip()
                    break
        if not open_from_prev:
            m = re.search(r"本章开头必须承接[：:]\s*(\S.+?)(?=\n|本章结尾|$)", out, re.DOTALL)
            if m:
                open_from_prev = m.group(1).strip()[:150]
        if not end_to_next:
            m = re.search(r"本章结尾必须留下钩子[：:]\s*(\S.+?)(?=\n|$)", out, re.DOTALL)
            if m:
                end_to_next = m.group(1).strip()[:150]
        return beat_card, open_from_prev, end_to_next, chapter_type, closure_type

    def generate_emotion_reinforcement_points(
        self, chapter_num: int, outline_corrected: str, outline_original: str,
        prev_life_clue: Optional[str] = None,
    ) -> str:
        """
        在生成正文前，根据梗概列出本章的情绪强化点。
        用于约束：上一世回忆强化委屈/愤怒/同情，这一世复仇强化爽感。
        返回可拼入 prompt 的文本。
        """
        prompt = f"""你是一位重生复仇短剧编剧。请根据下面第{chapter_num}章的【梗概】与【上一世线索】，列出本章的【情绪强化点】。

要求：
1. 若本章涉及「上一世受害」回忆，必须列出：
   - 委屈强化点：在回忆中哪个具体情境需要强化主角被冤枉/被误解的委屈感（1-2句话）
   - 愤怒强化点：在回忆中哪个情境需要强化对陷害者的愤怒、憎恨（1-2句话）
   - 同情强化点：在回忆中哪个情境需要让读者同情主角、憎恶反派（1-2句话）
2. 若本章涉及「这一世复仇」或反制，必须列出：
   - 爽感强化点：在哪个具体情节点需要强化复仇成功的痛快感、反杀快感（1-2句话）
   - 若有多处复仇/反制，每处都要标出
3. 若本章不涉及回忆或复仇，填「本章无上一世回忆/无复仇情节」。
4. 每点要具体到「在xxx时/当xxx时」，便于正文写作时落地。

【本章梗概】
{outline_corrected}

【本章修正前梗概】
{outline_original or "（无）"}
"""
        if prev_life_clue:
            prompt += f"""
【本章可用的上一世线索】
{prev_life_clue}
"""
        prompt += """

请严格按以下格式输出，不要其他内容：
【本章情绪强化点】
- 上一世回忆部分（若有）：
  - 委屈强化点：
  - 愤怒强化点：
  - 同情强化点：
- 这一世复仇部分（若有）：
  - 爽感强化点：
  （可有多条，每条对应一个情节点）
"""
        out = self._call_api(prompt, None, 0)
        if not out or out.startswith("通义千问"):
            return ""
        return out.strip()[:800]

    def _get_chapter_role_hint(self, chapter_num: int) -> str:
        """前3章分工提示，避免都写成病床重复。"""
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

    def build_prompt_with_beat(self, chapter_num: int, outline_corrected: str, outline_original: str,
                               prev_chapter_full: Optional[str], beat_card: str,
                               prev_life_clue: Optional[str], kg_context: str = "",
                               prev_tail_scene: str = "", prev_unresolved_hook: str = "",
                               open_from_prev: str = "", end_to_next: str = "",
                               emotion_reinforcement_points: str = "",
                               rag_samples: Optional[Dict[str, List]] = None,
                               need_prev_life: bool = False,
                               chapter_type: str = "",
                               closure_type: str = "full_close",
                               flashback_breakpoint_hint: str = "",
                               past_ratio_min: float = 0.20,
                               past_ratio_max: float = 0.32,
                               global_seed_progress: str = "",
                               chapter_constraints: Optional[List[str]] = None) -> str:
        """构建正文生成提示：跨章硬约束 + 双梗概 + 节拍卡 + 知识图谱 + 情绪向样本参考 + 上一世硬约束。"""
        prompt = f"""角色：你是专业小说作者，擅长重生复仇短剧正文。

【核心要求】
1. 严格按本章节拍卡与梗概推进，不得偏离；节拍卡中的每一拍都必须写到位，不得跳过或一笔带过。
2. 字数：至少1000字，建议1000-1400字，单章不宜超过1600字（避免跑偏）。第三人称，快节奏，结尾留悬念。
3. 主线优先，禁止随意新增无关支线。
"""
        # 上一世：硬约束（不再“自主判断”）
        # 第1、2章为濒死与重生觉醒阶段，禁止插入形式化的“上一世回忆段落”
        if need_prev_life and prev_life_clue and chapter_num not in (1, 2):
            # 对于你当前的需求，强制把上一世比例锁定在 35%~50% 区间
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
        # 特殊章节：上一世临死（第1章）与重生觉醒（第2章）限制
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
        # 跨章接续硬约束（非第一章且已有尾钩时）
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
        # 若存在“整书最大复仇主线”的小推进提醒，则附加简要说明
        if global_seed_progress:
            prompt += f"""
【整书最大复仇主线小推进】（本章只允许用1-2句轻描淡写带过，不能喧宾夺主）
- 请在合适位置，用一句话完成以下推进，然后立刻把镜头切回本章支线冲突：
  {global_seed_progress}
"""
        # 若章节卡中有针对本章的硬性限制，则作为最高优先级约束写入
        if chapter_constraints:
            prompt += "\n【本章写作限制】（必须严格遵守）\n"
            for rule in chapter_constraints:
                prompt += f"- {rule}\n"
        # 闭合类型：要求本章是否必须写满闭环
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
        # 注入按场景检索的样本参考：重生复仇爽感 / 上一世委屈 / 通用（生成时自动调用）
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
        # 若单章重生成脚本设置了“下一章衔接提示”，在此附加
        if hasattr(self, "_next_chapter_hint") and self._next_chapter_hint:
            prompt += "\n" + str(self._next_chapter_hint) + "\n"
        return prompt

    def generate_one_chapter_with_beats(self, chapter_num: int, num_versions: int = 1,
                                        max_iterations: int = 2, min_emotion_intensity: float = 0.5) -> Optional[str]:
        """单章两步生成：先节拍卡（打日志）→ 再正文 → 立即保存。返回正文内容。"""
        outline_raw = self.master_ctx.get(chapter_num, "")
        if not outline_raw:
            print(f"❌ 未找到第{chapter_num}章梗概")
            return None
        outline_orig = self.master_ctx_original.get(chapter_num, "")
        # 优先尝试按 JSON 章节卡解析，便于读取 chapter_constraints / global_seed_progress 等结构化字段
        print(f"  [梗概] 第{chapter_num}章：尝试按 JSON 章节卡读取...")
        card = self._parse_json_maybe(outline_raw)
        if isinstance(card, dict):
            print("  [梗概] 已成功解析为 JSON 卡，后续将按结构化字段生成正文。")
        else:
            print("  [梗概] 非 JSON 格式，按纯文本梗概处理。")
        outline_corrected = self._render_master_card_for_prompt(card) if card else outline_raw
        # -------- V2：章节任务卡校验所需字段（用于减少正文“自由发挥”）--------
        v2_card = card if isinstance(card, dict) else {}
        v2_must_include = v2_card.get("chapter_must_include", []) if isinstance(v2_card.get("chapter_must_include", []), list) else []
        v2_must_not_include = v2_card.get("chapter_must_not_include", []) if isinstance(v2_card.get("chapter_must_not_include", []), list) else []
        v2_must_resolve = v2_card.get("must_resolve_this_chapter", []) if isinstance(v2_card.get("must_resolve_this_chapter", []), list) else []
        v2_chapter_ending = str(v2_card.get("chapter_ending", "") or "")
        prev_life_raw = self.prev_life_ctx.get(chapter_num)
        prev_life_card = self._parse_json_maybe(prev_life_raw) if prev_life_raw else None
        prev_life_clue = self._render_prev_life_card_for_prompt(prev_life_card) if prev_life_card else prev_life_raw

        prev_chapter_full = self.get_previous_chapter_content(chapter_num)

        prev_tail_scene, prev_unresolved_hook = "", ""
        if prev_chapter_full and chapter_num > 1:
            print(f"  [跨章] 提取上一章尾钩…")
            prev_tail_scene, prev_unresolved_hook = self._extract_prev_chapter_tail_and_hook(prev_chapter_full)
            if prev_tail_scene or prev_unresolved_hook:
                print(f"  [跨章] 最后场景/钩子已注入，本章必须接续")

        kg_context = ""
        # 优先：若挂载了“在线检索器”，动态从 Neo4j 拉取限长背景事实（不改剧情决策权）
        try:
            online_retrieve = getattr(self, "online_retrieve_context", None)
            if callable(online_retrieve):
                # 允许生成端覆盖“是否早期注入”的策略；默认所有章节可用
                kg_context = str(online_retrieve(chapter_num)) or ""
                if kg_context:
                    print(f"  [在线检索] 已注入 Neo4j 背景事实")
        except Exception:
            kg_context = ""
        # 本地 JSON 知识图谱已废弃：不再注入旧 KG 背景

        # 第一步：生成节拍卡（含本章开头承接、结尾钩子、章节类型、闭合类型）
        print(f"\n📋 第{chapter_num}章 生成节拍卡（仅供调试）…")
        beat_card, open_from_prev, end_to_next, chapter_type, closure_type = self.generate_beat_card(
            chapter_num, outline_corrected, outline_orig, prev_life_clue
        )

        # 如上一章已成功抽取尾钩，但节拍卡里开头承接为“无”，则在“同一情节组/同一 cluster”内才允许用尾钩覆盖开头
        if chapter_num > 1 and (prev_tail_scene or prev_unresolved_hook):
            same_cluster = False
            try:
                # 当前章所属 cluster_id（若有）
                card_cur = self._parse_json_maybe(outline_raw) if isinstance(outline_raw, str) else None
                cur_cluster = (card_cur or {}).get("cluster_id")
                # 上一章所属 cluster_id（若有）
                prev_outline_raw = self.master_ctx.get(chapter_num - 1, "")
                card_prev = self._parse_json_maybe(prev_outline_raw) if isinstance(prev_outline_raw, str) else None
                prev_cluster = (card_prev or {}).get("cluster_id")
                same_cluster = bool(cur_cluster and prev_cluster and cur_cluster == prev_cluster)
            except Exception:
                same_cluster = False

            if same_cluster:
                auto_hint = (prev_unresolved_hook or prev_tail_scene or "").strip()
                if auto_hint:
                    raw = (open_from_prev or "").strip()
                    raw_simple = raw.replace("…", "").replace("。", "").strip()
                    if not raw or raw_simple in ("无", "无承接", "无特别承接"):
                        open_from_prev = auto_hint[:150]
                        print(f"  [跨章] 使用上一章尾钩覆盖节拍卡开头承接: {open_from_prev[:60]}…")

        if beat_card:
            print(f"[节拍卡 第{chapter_num}章]\n{beat_card}\n")
            print(f"  章节类型: {chapter_type}, 闭合类型: {closure_type}")
            if open_from_prev:
                print(f"  开头承接: {open_from_prev[:60]}…")
            if end_to_next:
                print(f"  结尾钩子: {end_to_next[:60]}…")
        else:
            print(f"[节拍卡 第{chapter_num}章] 生成失败或为空，将仅用梗概写正文。")

        # 第二步：生成本章情绪强化点（在正文前列出委屈/愤怒/同情/爽感强化点）
        print(f"  [情绪强化] 生成本章情绪强化点…")
        emotion_reinforcement_points = self.generate_emotion_reinforcement_points(
            chapter_num, outline_corrected, outline_orig, prev_life_clue
        )
        if emotion_reinforcement_points:
            print(f"  [情绪强化] 已注入 prompt，将在对应情节点强化情绪")

        # 按本章是否含“上一世回忆”“复仇/反制”自动检索对应样本集并注入 prompt；从章节卡读取上一世占比与插入点
        need_prev_life_infer = not self._is_chapter_current_timeline_only(outline_corrected, prev_life_clue) and bool(prev_life_clue)
        present = (card.get("present") or {}) if isinstance(card, dict) else {}
        if isinstance(present, dict):
            need_prev_life = present.get("need_prev_life", need_prev_life_infer) if present.get("need_prev_life") is not None else need_prev_life_infer
            flashback_breakpoint_hint = present.get("flashback_breakpoint") or ""
            past_ratio_min = 0.35
            past_ratio_max = 0.50
        else:
            need_prev_life = need_prev_life_infer
            flashback_breakpoint_hint = ""
            past_ratio_min, past_ratio_max = 0.35, 0.50
        # 硬性限制：第1、2章不插入上一世回忆（病房绝境 + 重生惊醒，无回忆）
        if chapter_num in (1, 2):
            need_prev_life = False
        # V2 情节组模式：仅当本章角色为“承担上一世回忆”的那一章时才 need_prev_life，单位是情节组而非每章
        elif isinstance(card, dict) and card.get("chapter_role_v2"):
            _prev_life_roles = ("prev_life_full", "prev_life_explained_by_investigation", "present_past_mix", "slow_burn_press_with_past_shadow")
            need_prev_life = card.get("chapter_role_v2") in _prev_life_roles
        # 从 master 章节卡中读取“整书最大复仇主线小推进”和本章写作限制
        global_seed_progress = ""
        chapter_constraints: List[str] = []
        if isinstance(card, dict):
            gsp = card.get("global_seed_progress")
            if isinstance(gsp, str):
                global_seed_progress = gsp.strip()
            cc = card.get("chapter_constraints")
            if isinstance(cc, list):
                chapter_constraints = [str(x).strip() for x in cc if str(x).strip()]
        # 若章节限制中明确禁止出现“上一世/这一世/重生”等字样，则强制视为本章不插入上一世回忆
        if chapter_constraints:
            joined_rules = " ".join(chapter_constraints)
            if ("上一世" in joined_rules) or ("这一世" in joined_rules) or ("重生" in joined_rules):
                need_prev_life = False
        if global_seed_progress:
            print(f"  [主线种子] 第{chapter_num}章 global_seed_progress: {global_seed_progress}")
        if chapter_constraints:
            print(f"  [章节限制] 第{chapter_num}章已设定 chapter_constraints:")
            for rule in chapter_constraints:
                print(f"    - {rule}")
        has_revenge = any(k in outline_corrected for k in ["复仇", "反制", "反击", "扳倒", "揭穿", "打脸"])
        rag_query = f"{outline_corrected}\n{prev_life_clue or ''}"
        target_context = "主角: 沈清欢, 背景: 现代都市, 重生复仇, 职场复仇"
        rag_samples = search_rebirth_samples_for_chapter(
            rag_query, target_context, need_prev_life, has_revenge, top_k_per_set=2
        )
        if any(rag_samples.get(k) for k in ("revenge", "grievance", "universal")):
            n = sum(len(rag_samples.get(k, [])) for k in ("revenge", "grievance", "universal"))
            print(f"  [RAG样本] 已注入 {n} 条参考（委屈/爽感/通用）")
        if chapter_num in (1, 2):
            print(f"  [上一世] 第{chapter_num}章不插入上一世回忆（病房绝境/重生惊醒，无回忆）")
        elif need_prev_life:
            print(f"  [上一世] 本情节组内由本章承担上一世回忆，占比 {int(past_ratio_min*100)}%~{int(past_ratio_max*100)}%")
        elif isinstance(card, dict) and (card.get("chapter_role_v2") or card.get("cluster_id")):
            print(f"  [上一世] 本章不承担上一世回忆（由本情节组其他章节承担）")

        # 第三步：根据节拍卡+梗概+情绪强化点+跨章硬约束+RAG样本+章节类型/闭合类型生成正文
        body_prompt = self.build_prompt_with_beat(
            chapter_num, outline_corrected, outline_orig, prev_chapter_full, beat_card, prev_life_clue, kg_context,
            prev_tail_scene=prev_tail_scene, prev_unresolved_hook=prev_unresolved_hook,
            open_from_prev=open_from_prev, end_to_next=end_to_next,
            emotion_reinforcement_points=emotion_reinforcement_points,
            rag_samples=rag_samples,
            need_prev_life=need_prev_life,
            chapter_type=chapter_type,
            closure_type=closure_type,
            flashback_breakpoint_hint=flashback_breakpoint_hint,
            past_ratio_min=past_ratio_min,
            past_ratio_max=past_ratio_max,
            global_seed_progress=global_seed_progress,
            chapter_constraints=chapter_constraints,
        )

        # 轻量的“任务卡命中校验”：用于过滤忽略 must_include 的跑偏正文（V2 生效）
        def _split_rule_item(item: str) -> List[str]:
            s = (item or "").strip()
            if not s:
                return []
            s = s.replace("（", "/").replace("）", "")
            parts = re.split(r"[\/或，,；;：:、\s]+", s)
            return [p for p in (x.strip() for x in parts) if len(p) >= 2]

        _generic_tokens = {"本章", "今生", "上一世", "信息差"}

        def _rule_item_satisfied(rule_item: str, content: str) -> bool:
            c = content or ""
            rule_item = (rule_item or "").strip()
            if not rule_item:
                return True
            if rule_item in c:
                return True
            tokens = _split_rule_item(rule_item)
            tokens = [t for t in tokens if t not in _generic_tokens and len(t) >= 2]
            if not tokens:
                return rule_item[:6] in c
            return any(t in c for t in tokens)

        def _validate_v2_card_rules(content: str) -> Tuple[bool, List[str]]:
            if not (v2_must_include or v2_must_not_include or v2_must_resolve):
                return True, []

            violations: List[str] = []

            # must_not：用“整项包含”优先（降低误判）
            for mn in v2_must_not_include:
                mn = (mn or "").strip()
                if not mn:
                    continue
                if mn in content:
                    violations.append(f"命中禁止项：{mn}")
                    return False, violations

            # must_include：命中足够数量的规则项（不要要求逐字复刻）
            if v2_must_include:
                satisfied = sum(1 for mi in v2_must_include if _rule_item_satisfied(mi, content))
                need = len(v2_must_include) if len(v2_must_include) <= 3 else 3
                if satisfied < need:
                    violations.append(f"must_include 未命中足够项：{satisfied}/{len(v2_must_include)}（需>= {need}）")
                    return False, violations

            # must_resolve：同样做轻量命中
            if v2_must_resolve:
                satisfied = sum(1 for mr in v2_must_resolve if _rule_item_satisfied(mr, content))
                need = len(v2_must_resolve) if len(v2_must_resolve) <= 2 else 2
                if satisfied < need:
                    violations.append(f"must_resolve 未命中足够项：{satisfied}/{len(v2_must_resolve)}（需>= {need}）")
                    return False, violations

            return True, violations

        best_content = None
        best_score = 0
        best_emotion = 0
        emotion_feedback = None
        for iteration in range(max_iterations):
            if iteration > 0 and emotion_feedback:
                body_prompt = self._add_emotion_feedback(body_prompt, emotion_feedback, iteration)
            content = self._call_api(body_prompt, emotion_feedback, iteration)
            if not content or content.startswith("通义千问"):
                continue
            char_count = len(content.strip())
            score = self.scorer.calculate_score(content)
            emotion_result = self.emotion_analyzer.analyze(content)
            ei = emotion_result.intensity
            cont_score, cont_fb = self._check_continuity(content, prev_tail_scene, prev_unresolved_hook)
            past_score, past_fb = self._check_past_block_ratio(content, need_prev_life, min_ratio=0.15, min_chars=200)
            print(f"  评分: {score:.2f}, 情绪: {ei:.3f}, 字数: {char_count}, 连续性: {cont_score:.2f}, 上一世段落: {past_score:.2f}")
            # 字数改为至少1000；需要上一世时上一世段落须达标
            past_ok = not need_prev_life or past_score >= 0.5
            must_ok, _ = _validate_v2_card_rules(content)
            if ei >= min_emotion_intensity and score >= 50 and char_count >= 1000 and cont_score >= 0.5 and past_ok and must_ok:
                best_content = content
                best_score = score
                best_emotion = ei
                break
            # 统计“上一世”出现次数，用于限制同一回忆块内的反复口头禅
            prev_life_count = content.count("上一世")
            structure_fb_parts = []
            if need_prev_life and past_score < 0.5:
                structure_fb_parts.append(past_fb)
            if prev_life_count > 3:
                structure_fb_parts.append(
                    "上一版正文中多次重复使用“上一世……”口头禅。请调整为：每个上一世回忆段，只在开头 1–2 句用“上一世我……/记得那一世……”点明，"
                    "后面一律用正常过去时（那天/那一夜/当时）写完整场景，禁止在同一段内反复重复“上一世”三个字。"
                )
            structure_feedback = "\n".join([p for p in structure_fb_parts if p])

            emotion_feedback = {
                'intensity': ei, 'label': emotion_result.label, 'emotion_depth': emotion_result.emotion_depth,
                'emotion_transition': emotion_result.emotion_transition,
                'suggestion': self._get_emotion_suggestion(emotion_result),
                'char_count': char_count, 'word_short': char_count < 1000,
                'continuity_score': cont_score, 'continuity_feedback': cont_fb,
                'past_block_score': past_score,
                'structure_feedback': structure_feedback or None,
            }
            if must_ok and (ei > best_emotion or (ei == best_emotion and score > best_score)):
                best_content, best_score, best_emotion = content, score, ei
        if not best_content:
            c = self._call_api(body_prompt, None, 0)
            if c and not c.startswith("通义千问") and len(c.strip()) >= 500:
                best_content = c
        if best_content:
            self.save_chapter(chapter_num, best_content)
            self.generated_chapters[chapter_num] = best_content
            print(f"✅ 第{chapter_num}章生成完成（评分: {best_score:.2f}, 情绪: {best_emotion:.3f}）")
            return best_content
        return None

    def generate_chapter_batch(self, start_chapter: int, batch_size: int = 5, **kwargs) -> List[int]:
        """批量生成：从 start_chapter 起连续生成 batch_size 章，每章生成后立即写入文件。返回成功生成的章节号列表。"""
        succeeded = []
        for i in range(batch_size):
            ch = start_chapter + i
            if not self.master_ctx.get(ch):
                print(f"⚠️ 第{ch}章无梗概，跳过")
                continue
            content = self.generate_one_chapter_with_beats(ch, **kwargs)
            if content:
                succeeded.append(ch)
        return succeeded

    def generate_chapter(self, chapter_num: int, num_versions: int = 3, 
                        max_iterations: int = 3, min_emotion_intensity: float = 0.6) -> Optional[str]:
        """生成单章（完整流程）"""
        # 生成多个版本
        versions = self.generate_with_rag(
            chapter_num, 
            "",  # user_input 可以从章节梗概中获取
            num_versions,
            max_iterations,
            min_emotion_intensity
        )
        
        if not versions:
            return None
        
        # 选择最佳版本
        best = self.select_best_version(versions)
        
        if best:
            # 保存章节
            self.save_chapter(chapter_num, best['content'])
            
            # 记录到已生成章节
            self.generated_chapters[chapter_num] = best['content']
            
            print(f"\n✅ 第{chapter_num}章生成完成！")
            print(f"   评分: {best['score']:.2f}")
            print(f"   情绪强度: {best['emotion_intensity']:.3f}")
            print(f"   综合评分: {best['composite_score']:.2f}")
            
            return best['content']
        
        return None


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='重生复仇小说正文生成器')
    parser.add_argument('--chapter', type=int, required=True, help='起始章节号（例如 6 表示从第6章开始）')
    parser.add_argument('--batch', type=int, default=5, help='连续生成的章数（默认5，即输入6则生成6,7,8,9,10）')
    # 优先使用结构化 JSON 章节卡；若无，则退回文本梗概
    if (DEFAULT_OUTPUTS_DIR / 'master_ctx_cards.json').exists():
        default_master_ctx = 'outputs/master_ctx_cards.json'
    elif (DEFAULT_OUTPUTS_DIR / 'master_ctx_final.txt').exists():
        default_master_ctx = 'outputs/master_ctx_final.txt'
    else:
        default_master_ctx = 'outputs/master_ctx.txt'
    default_prev_life_ctx = 'outputs/prev_life_ctx_final.txt' if (DEFAULT_OUTPUTS_DIR / 'prev_life_ctx_final.txt').exists() else 'outputs/prev_life_ctx.txt'
    parser.add_argument('--master-ctx', type=str, default=default_master_ctx, help='章节梗概文件路径（修正后）')
    parser.add_argument('--original-master-ctx', type=str, default=None, help='修正前梗概路径（默认在 final 时用 master_ctx.txt）')
    parser.add_argument('--prev-life-ctx', type=str, default=default_prev_life_ctx, help='上一世线索文件路径')
    parser.add_argument('--versions', type=int, default=1, help='每章生成版本数（批量时建议1）')
    parser.add_argument('--iterations', type=int, default=2, help='每版本最大迭代次数')
    parser.add_argument('--min-emotion', type=float, default=0.5, help='最小情绪强度')
    parser.add_argument('--no-kg', action='store_true', help='禁用知识图谱')
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("📖 重生复仇小说正文生成器（节拍卡 + 批量 + 双梗概 + 上一章衔接）")
    print("=" * 80)
    print(f"  起始章: {args.chapter}，批量: {args.batch} 章（即 {args.chapter}～{args.chapter + args.batch - 1}）")
    print("=" * 80)
    
    generator = RebirthRevengeGenerator()
    # 本地 JSON KG 已废弃；--no-kg 参数保留但不再产生效果
    generator.load_contexts(args.master_ctx, args.prev_life_ctx, args.original_master_ctx)
    generator.load_existing_chapters()
    
    succeeded = generator.generate_chapter_batch(
        args.chapter,
        batch_size=args.batch,
        num_versions=args.versions,
        max_iterations=args.iterations,
        min_emotion_intensity=args.min_emotion,
    )
    
    if succeeded:
        print(f"\n✅ 批量生成完成：第 {', '.join(map(str, succeeded))} 章已写入 outputs/chapters/")
    else:
        print("\n❌ 未成功生成任何章节。")


if __name__ == "__main__":
    main()

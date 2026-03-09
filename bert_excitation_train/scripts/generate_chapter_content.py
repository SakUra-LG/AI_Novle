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
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 导入项目模块
from smart_sample_search import search_and_adapt_samples
from optimized_rule_scorer import OptimizedRuleScorer
from emotion_analyzer import EmotionAnalyzer

# 配置API
API_Key_QW = "sk-a2966f4e37134351904851679884cb67"

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # .../bert_excitation_train
DEFAULT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"

class RebirthRevengeGenerator:
    """重生复仇小说正文生成器"""
    
    def __init__(self):
        self.scorer = OptimizedRuleScorer()
        self.emotion_analyzer = EmotionAnalyzer()
        self.master_ctx = {}  # 章节梗概
        self.prev_life_ctx = {}  # 上一世线索
        self.project_root = PROJECT_ROOT
        self.outputs_dir = DEFAULT_OUTPUTS_DIR
        # 已生成章节（用于上下文），key 为章节号，value 为正文内容
        self.generated_chapters = {}
        
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
    
    def load_contexts(self, master_ctx_file, prev_life_ctx_file):
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
        with open(master_path, 'r', encoding='utf-8') as f:
            content = f.read()
            for line in content.split('\n'):
                if line.strip() and '章' in line:
                    match = re.search(r'第(\d+)章', line)
                    if match:
                        chapter_num = int(match.group(1))
                        # 提取章节内容（冒号后的部分）
                        if '：' in line:
                            chapter_content = line.split('：', 1)[1].strip()
                        elif ':' in line:
                            chapter_content = line.split(':', 1)[1].strip()
                        else:
                            chapter_content = line
                        self.master_ctx[chapter_num] = chapter_content
        
        # 加载上一世线索
        if not prev_life_path.exists():
            print(f"⚠️  未找到上一世线索文件: {prev_life_path}")
            print("   将跳过上一世回忆触发（仍可生成正文，但不会插入回忆段落）")
            self.prev_life_ctx = {}
        else:
            with open(prev_life_path, 'r', encoding='utf-8') as f:
                content = f.read()
                for line in content.split('\n'):
                    if line.strip() and '章对应线索' in line:
                        match = re.search(r'第(\d+)章对应线索', line)
                        if match:
                            chapter_num = int(match.group(1))
                            # 提取线索内容
                            if '：' in line:
                                clue = line.split('：', 1)[1].strip()
                            elif ':' in line:
                                clue = line.split(':', 1)[1].strip()
                            else:
                                clue = line
                            self.prev_life_ctx[chapter_num] = clue
        
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

【本章章节梗概】
{chapter_outline}

【故事展开顺序】
生成时按以下顺序组织内容：先看本章梗概的主要故事线 → 若涉及回忆则看上一世线索中主角曾受到的不公平待遇 → 再写这一世如何复仇或应对。两个强情绪方向：写上一世时突出对欺负者的愤怒憎恨与对主角的委屈同情（负面情绪）；写这一世复仇时重点营造爽感，让读者看完感到痛快、解气。

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
- 反派：自信、轻视女主（因为不知道她重生）

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
        chapter_outline = self.master_ctx.get(chapter_num, "")
        if not chapter_outline:
            print(f"❌ 未找到第{chapter_num}章的章节梗概")
            return []
        
        # 获取上一世线索
        prev_life_clue = self.prev_life_ctx.get(chapter_num)
        
        # 检查触发条件
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
                    
                    # 更新提示词（添加情绪与字数反馈）
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
    
    def _call_api(self, prompt: str, emotion_feedback: Optional[Dict] = None, 
                  iteration: int = 0) -> str:
        """调用通义千问API"""
        dashscope.api_key = API_Key_QW
        
        system_message = {"role": "system", "content": prompt}
        user_message = {"role": "user", "content": "请开始创作"}
        
        try:
            response = dashscope.Generation.call(
                model=dashscope.Generation.Models.qwen_turbo,
                messages=[system_message, user_message],
                temperature=0.85,
                top_p=0.8,
                repetition_penalty=1.1,
                result_format='message'
            )
            
            if 'output' in response and 'choices' in response['output']:
                content = response['output']['choices'][0]['message']['content']
                return self._clean_markdown(content)
            else:
                return f"通义千问 API 返回了无效格式: {str(response)}"
        except Exception as e:
            return f"调用通义千问 API 出错: {str(e)}"
    
    def _clean_markdown(self, text: str) -> str:
        """去除 Markdown 格式符号"""
        if not text:
            return ""
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
        text = re.sub(r'### (.*)', r'\1', text)
        text = re.sub(r'---', '', text)
        text = re.sub(r'#+', '', text)
        return text.strip()
    
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
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"💾 已保存到: {filepath}")
        return filepath
    
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
    parser.add_argument('--chapter', type=int, required=True, help='章节号')
    parser.add_argument('--master-ctx', type=str, 
                       default='outputs/master_ctx.txt',
                       help='章节梗概文件路径')
    parser.add_argument('--prev-life-ctx', type=str,
                       default='outputs/prev_life_ctx.txt',
                       help='上一世线索文件路径')
    parser.add_argument('--versions', type=int, default=3, help='生成版本数')
    parser.add_argument('--iterations', type=int, default=3, help='每版本最大迭代次数')
    parser.add_argument('--min-emotion', type=float, default=0.6, help='最小情绪强度')
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("📖 重生复仇小说正文生成器")
    print("=" * 80)
    print("\n使用的技术：")
    print("  1. ✅ 样本集结构（RAG检索）")
    print("  2. ✅ 循环评分（情绪反馈循环）")
    print("  3. ✅ 生成后评分（规则评分 + 情绪分析）")
    print("  4. ✅ 回忆触发规则（人物/地点/事件类型匹配）")
    print("=" * 80)
    
    # 初始化生成器
    generator = RebirthRevengeGenerator()
    
    # 加载上下文
    generator.load_contexts(args.master_ctx, args.prev_life_ctx)
    # 尝试从磁盘加载历史章节，用于保证跨运行的章节衔接与高分片段提取
    generator.load_existing_chapters()
    
    # 生成章节
    content = generator.generate_chapter(
        args.chapter,
        args.versions,
        args.iterations,
        args.min_emotion
    )
    
    if content:
        print("\n✅ 生成完成！")
    else:
        print("\n❌ 生成失败！")


if __name__ == "__main__":
    main()

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
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 导入项目模块
from smart_sample_search import search_and_adapt_samples
from optimized_rule_scorer import OptimizedRuleScorer
from emotion_analyzer import EmotionAnalyzer

# 配置API
API_Key_QW = "sk-a2966f4e37134351904851679884cb67"

class RebirthRevengeGenerator:
    """重生复仇小说正文生成器"""
    
    def __init__(self):
        self.scorer = OptimizedRuleScorer()
        self.emotion_analyzer = EmotionAnalyzer()
        self.master_ctx = {}  # 章节梗概
        self.prev_life_ctx = {}  # 上一世线索
        self.generated_chapters = {}  # 已生成章节（用于上下文）
        
        # 人物、地点、事件类型提取（用于回忆触发）
        self.characters = set()
        self.locations = set()
        self.event_types = {
            '陷害', '嘲讽', '裁员', '拒绝', '举报', '开会', '会议', '当众', 
            '羞辱', '证据', '调查', '威胁', '背叛', '攻击', '拒绝', '无视'
        }
    
    def load_contexts(self, master_ctx_file, prev_life_ctx_file):
        """加载章节梗概和上一世线索"""
        print("=" * 80)
        print("📚 加载上下文文件")
        print("=" * 80)
        
        # 加载章节梗概
        with open(master_ctx_file, 'r', encoding='utf-8') as f:
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
        with open(prev_life_ctx_file, 'r', encoding='utf-8') as f:
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
1. 主线优先：必须严格按照本章章节梗概推进，不得偏离主线
2. 字数要求：800-1200字
3. 第三人称叙事
4. 以场景推进为主
5. 结尾留悬念或冲突升级
6. 短剧节奏：每1000字至少1个情绪点或反转
7. 对话占比高
8. 情绪外显

【本章章节梗概】
{chapter_outline}

"""
        
        # 如果有触发条件，添加回忆触发规则
        if trigger_info and prev_life_clue:
            is_triggered, trigger_type, trigger_content = trigger_info
            if is_triggered:
                prompt += f"""
【回忆触发规则】（重要！）
检测到触发条件：{trigger_type} = {trigger_content}

调用流程必须固定为：
1. 【触发场景】→ 出现{trigger_content}的情境
2. 【上一世回忆（50-150字）】→ 必须是具体场景（对话/动作/结果），必须体现失败或被压制，禁止总结式回忆
3. 【情绪变化】→ 突出冷静、提前预判、不再犯错
4. 【今生反制】→ 体现提前准备、反向布局、让对方落入陷阱

【相关上一世线索】
{prev_life_clue}

重要：上一世内容必须满足失败结局（被打压/被误解/证据失效/无人支持），绝不能出现上一世成功、被认可、胜利的情况。

"""
        else:
            prompt += """
【回忆触发规则】
如果没有触发条件（相同人物/地点/事件类型），禁止硬插回忆，否则正文会很乱。

"""
        
        # 添加前文摘要（最近3章）
        if previous_chapters:
            prompt += "\n【前文摘要】（保持连贯性）\n"
            for i, prev_chapter in enumerate(previous_chapters[-3:], 1):
                preview = prev_chapter[:200] + "..." if len(prev_chapter) > 200 else prev_chapter
                prompt += f"前文{i}: {preview}\n"
        
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

要求：直接输出创作的内容，不要添加标题、说明或总结。
"""
        
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
        
        # 获取前文（最近5章）
        previous_chapters = []
        for i in range(max(1, chapter_num - 5), chapter_num):
            if i in self.generated_chapters:
                previous_chapters.append(self.generated_chapters[i])
        
        # RAG检索相似样本
        target_context = "主角: 沈清欢, 背景: 现代都市, 重生复仇, 职场复仇"
        adapted_samples = search_and_adapt_samples(
            chapter_outline,
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
            
            # 构建提示词
            prompt = self.build_generation_prompt(
                chapter_num, chapter_outline, prev_life_clue, 
                trigger_info, previous_chapters
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
                
                # 评分
                score = self.scorer.calculate_score(content)
                
                # 情绪分析
                emotion_result = self.emotion_analyzer.analyze(content)
                emotion_intensity = emotion_result.intensity
                
                print(f"  📊 评分: {score:.2f}, 情绪强度: {emotion_intensity:.3f}", end="")
                
                # 判断是否达标
                if emotion_intensity >= min_emotion_intensity and score >= 60:
                    print(" ✅")
                    best_content = content
                    best_score = score
                    best_emotion = emotion_intensity
                    break
                else:
                    print(" ⚠️")
                    # 准备反馈用于下次迭代
                    emotion_feedback = {
                        'intensity': emotion_intensity,
                        'label': emotion_result.label,
                        'emotion_depth': emotion_result.emotion_depth,
                        'emotion_transition': emotion_result.emotion_transition,
                        'emotion_word_density': emotion_result.emotion_word_density,
                        'suggestion': self._get_emotion_suggestion(emotion_result)
                    }
                    
                    # 更新提示词（添加反馈）
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
        """添加情绪反馈到提示词"""
        feedback_section = f"""

【情绪强度改进建议 - 第{iteration}次优化】
根据上一次生成的情绪分析结果，请特别注意以下方面：
- 当前情绪强度: {emotion_feedback.get('intensity', 0):.3f} (目标 >= 0.6)
- 主导情绪: {emotion_feedback.get('label', 'N/A')}
- 情绪深度: {emotion_feedback.get('emotion_depth', 0):.3f}
- 情绪转折: {emotion_feedback.get('emotion_transition', 'N/A')}
- 情绪密度: {emotion_feedback.get('emotion_word_density', 0):.3f}
- 具体改进建议: {emotion_feedback.get('suggestion', '请增强情绪表达')}

请根据以上反馈，重新创作一个情绪强度更高的版本。重点改进情绪表达，使用更多情绪词汇、细节描写和情绪转折。
"""
        return base_prompt + feedback_section
    
    def select_best_version(self, versions: List[Dict]) -> Optional[Dict]:
        """选择最佳版本（综合评分和情绪强度）"""
        if not versions:
            return None
        
        # 综合评分 = 规则评分 * 0.4 + 情绪强度 * 100 * 0.6
        for v in versions:
            v['composite_score'] = v['score'] * 0.4 + v['emotion_intensity'] * 100 * 0.6
        
        best = max(versions, key=lambda x: x['composite_score'])
        return best
    
    def save_chapter(self, chapter_num: int, content: str, output_dir: str = "outputs/chapters"):
        """保存章节"""
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, f"chapter_{chapter_num:03d}.txt")
        
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

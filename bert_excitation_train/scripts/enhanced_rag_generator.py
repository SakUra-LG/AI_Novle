#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版RAG生成器
真正利用RAG系统防止低分，集成前文上下文和章节梗概
"""

import os
import sys
import json
import re
import dashscope
from datetime import datetime
from smart_sample_search import search_and_adapt_samples, generate_enhanced_prompt
from optimized_rule_scorer import OptimizedRuleScorer
from smart_context_loader import load_novel_context_smart, get_available_chapters
from emotion_analyzer import EmotionAnalyzer

# 配置API
API_Key_QW = "sk-a2966f4e37134351904851679884cb67"

def load_novel_context(max_chapters=20):
    """加载小说上下文信息（使用智能加载器）"""
    return load_novel_context_smart(max_chapters)

def extract_high_score_snippets_from_context(context, min_score=70):
    """从上下文中提取高评分片段作为RAG样本"""
    scorer = OptimizedRuleScorer()
    high_score_snippets = []
    
    for chapter in context['previous_chapters']:
        content = chapter['content']
        # 按段落分割
        paragraphs = content.split('\n\n')
        
        for para in paragraphs:
            para = para.strip()
            if len(para) > 50:  # 只处理较长的段落
                score = scorer.calculate_score(para)
                if score >= min_score:
                    high_score_snippets.append({
                        'content': para,
                        'score': score,
                        'chapter': chapter['chapter'],
                        'source': 'previous_chapter'
                    })
    
    # 按评分排序
    high_score_snippets.sort(key=lambda x: x['score'], reverse=True)
    return high_score_snippets[:10]  # 取前10个最高分片段

def build_enhanced_rag_prompt(chapter_num, user_input, context, adapted_samples):
    """构建增强的RAG提示词"""
    
    # 基础提示词
    base_prompt = f"""
角色：你是一个专业的小说作者，擅长创作高质量、高评分的情节内容
要求：根据下面的要求直接输出创作的情节，不要引入和结局，1000字左右

【章节信息】
- 章节号：第{chapter_num}章
- 用户要求：{user_input}

【前文摘要】
"""
    
    # 添加前文摘要
    if context['previous_chapters']:
        recent_chapters = context['previous_chapters'][-3:]  # 最近3章
        for chapter in recent_chapters:
            base_prompt += f"第{chapter['chapter']}章：{chapter['content'][:200]}...\n"
    
    # 添加章节梗概
    if context['outline']:
        base_prompt += f"\n【章节梗概】\n{context['outline'][:500]}...\n"
    
    # 添加高评分前文片段作为参考
    high_score_snippets = extract_high_score_snippets_from_context(context)
    if high_score_snippets:
        base_prompt += f"\n【前文高评分片段参考】\n"
        for i, snippet in enumerate(high_score_snippets[:3], 1):
            base_prompt += f"片段{i} (第{snippet['chapter']}章, 评分:{snippet['score']:.1f}): {snippet['content'][:150]}...\n"
    
    # 添加RAG样本
    if adapted_samples:
        base_prompt += f"\n【RAG高评分样本参考】\n"
        for i, sample in enumerate(adapted_samples, 1):
            base_prompt += f"样本{i} (类别: {sample['category']}, 相似度: {sample['similarity']:.1%}): {sample['adapted_content'][:150]}...\n"
    
    # 添加生成指导
    base_prompt += f"""
【生成指导 - 高情绪强度要求】
1. 必须与前文情节保持连贯性
2. 参考前文高评分片段的写作风格和情节设计
3. 借鉴RAG样本的结构和技巧
4. 【核心】确保情绪强度足够高（目标>=0.6），避免平淡内容：
   - 包含强烈的情感表达，使用具体细节描写（如"心跳仿佛要冲出胸腔"而非"很紧张"）
   - 包含多种情绪维度（恐惧、紧张、期待、愤怒、悲伤、喜悦等），避免单一情绪
   - 要有深层情绪表达（通过隐喻、转折、对比等隐含表达）
   - 要有明显的情绪变化和转折，制造情绪波动
   - 每100字至少包含2-3个情绪词汇，情绪句子占比应达到40%以上
   - 使用环境描写烘托情绪（如"黑暗的角落"、"急促的脚步声"）
   - 通过身体反应增强代入感（如"手心冒汗"、"呼吸急促"）
   - 使用短句和断句制造紧张感
5. 保持人物性格和关系的一致性
6. 情节要有冲突和张力
"""
    
    return base_prompt

def generate_with_enhanced_rag(chapter_num, user_input, num_versions=3, max_context_chapters=20):
    """使用增强RAG系统生成章节"""
    print(f"开始生成第{chapter_num}章（增强RAG模式）...")
    
    # 加载小说上下文
    context = load_novel_context(max_chapters=max_context_chapters)
    
    if not context['previous_chapters']:
        print("未找到前文内容，将使用基础RAG模式")
        # 回退到基础模式
        from universal_generator import generate_with_universal_samples
        return generate_with_universal_samples("暗河噬城", chapter_num, user_input, num_versions)
    
    print(f"已加载 {len(context['previous_chapters'])} 章前文内容")
    
    # 搜索RAG样本
    target_context = f"主角: 陈雪, 背景: 现代都市, 悬疑推理"
    adapted_samples = search_and_adapt_samples(
        user_input, 
        target_context, 
        top_k=3, 
        min_similarity=0.3
    )
    
    if adapted_samples:
        print(f"找到 {len(adapted_samples)} 个RAG样本")
    else:
        print("未找到RAG样本，将使用前文高评分片段")
    
    generated_versions = []
    scorer = OptimizedRuleScorer()
    emotion_analyzer = EmotionAnalyzer()
    
    for version in range(1, num_versions + 1):
        print(f"生成第{version}个版本...")
        
        # 构建增强提示词
        enhanced_prompt = build_enhanced_rag_prompt(chapter_num, user_input, context, adapted_samples)
        
        # 调用API
        reply = call_qianwen_api(enhanced_prompt, user_input)
        cleaned_reply = clean_markdown(reply)
        
        if cleaned_reply:
            # 评分
            score = scorer.calculate_score(cleaned_reply)
            
            # 情绪分析
            emotion_result = emotion_analyzer.analyze(cleaned_reply)
            
            generated_versions.append({
                'version': version,
                'content': cleaned_reply,
                'chapter': chapter_num,
                'score': score,
                'emotion_intensity': emotion_result.intensity,
                'emotion_label': emotion_result.label,
                'emotion_dimensions': emotion_result.emotion_dimensions,
                'generated_at': datetime.now().isoformat(),
                'rag_samples_used': len(adapted_samples) if adapted_samples else 0,
                'context_chapters_used': len(context['previous_chapters'])
            })
            
            emotion_status = "✓" if emotion_result.intensity >= 0.6 else "⚠"
            print(f"版本{version}生成完成，评分: {score:.2f}, 情绪强度: {emotion_result.intensity:.3f} {emotion_status}")
        else:
            print(f"版本{version}生成失败")
    
    return generated_versions

def call_qianwen_api(system_prompt, user_input):
    """调用通义千问API"""
    dashscope.api_key = API_Key_QW
    
    system_message = {"role": "system", "content": system_prompt}
    user_message = {"role": "user", "content": user_input}
    
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
            return response['output']['choices'][0]['message']['content']
        else:
            return f"通义千问 API 返回了无效格式: {str(response)}"
    except Exception as e:
        return f"调用通义千问 API 出错: {str(e)}"

def clean_markdown(text):
    """去除 Markdown 格式符号"""
    if not text:
        return ""
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'### (.*)', r'\1', text)
    text = re.sub(r'---', '', text)
    return text.strip()

def save_generated_versions(chapter_num, versions, output_dir="data/generated"):
    """保存生成的版本"""
    project_dir = os.path.join(output_dir, "暗河噬城")
    os.makedirs(project_dir, exist_ok=True)
    
    for version in versions:
        filename = f"ch{chapter_num}_v{version['version']}.txt"
        filepath = os.path.join(project_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(version['content'])
        
        print(f"版本{version['version']}已保存到: {filepath}")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='增强版RAG生成器')
    parser.add_argument('--chapter', type=int, required=True, help='章节号')
    parser.add_argument('--prompt', type=str, required=True, help='生成提示词')
    parser.add_argument('--versions', type=int, default=3, help='生成版本数')
    parser.add_argument('--max-context', type=int, default=20, help='最大上下文章节数')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("增强版RAG生成器")
    print("=" * 60)
    
    # 显示可用章节信息
    available_chapters = get_available_chapters()
    print(f"可用章节: {available_chapters}")
    print(f"将使用前 {args.max_context} 章作为上下文")
    
    # 检查样本库是否存在
    if not os.path.exists('data/universal_samples_vectors.npy'):
        print("通用样本库不存在，请先运行: python scripts/handle_universal_samples.py")
        return
    
    # 生成章节
    versions = generate_with_enhanced_rag(
        args.chapter, 
        args.prompt, 
        args.versions,
        args.max_context
    )
    
    if versions:
        # 保存版本
        save_generated_versions(args.chapter, versions)
        
        print(f"\n第{args.chapter}章生成完成！")
        print(f"共生成了 {len(versions)} 个版本")
        
        # 显示版本预览和评分
        for version in versions:
            print(f"\n版本{version['version']} (评分: {version['score']:.2f}):")
            print(f"  RAG样本使用: {version['rag_samples_used']} 个")
            print(f"  前文章节使用: {version['context_chapters_used']} 章")
            print("-" * 40)
            print(version['content'][:200] + "..." if len(version['content']) > 200 else version['content'])
    else:
        print("生成失败！")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版RAG生成器 v2.0
基于评分的针对性生成，支持高分样本优先检索
"""

import sys
import os
import json
import argparse
import numpy as np
from datetime import datetime
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.smart_sample_search import find_similar_samples, adapt_sample_content
from scripts.paragraph_scorer import ParagraphScorer
from scripts.optimized_rule_scorer import OptimizedRuleScorer
from scripts.emotion_analyzer import EmotionAnalyzer

def load_scored_samples():
    """加载已评分的样本"""
    scored_file = "data/universal_samples_scored.txt"
    if not os.path.exists(scored_file):
        print(f"⚠️ 评分样本文件不存在: {scored_file}")
        return []
    
    samples = []
    with open(scored_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 解析评分样本
    lines = content.strip().split('\n')
    current_sample = {}
    
    for line in lines:
        line = line.strip()
        if line.startswith('## 样本'):
            if current_sample:
                samples.append(current_sample)
            current_sample = {}
        elif line.startswith('**标签**'):
            current_sample['tag'] = line.split(':', 1)[1].strip()
        elif line.startswith('**评分**'):
            try:
                current_sample['score'] = float(line.split(':', 1)[1].strip())
            except:
                current_sample['score'] = 0
        elif line.startswith('**内容**'):
            current_sample['content'] = line.split(':', 1)[1].strip()
        elif line.startswith('**添加时间**'):
            current_sample['timestamp'] = line.split(':', 1)[1].strip()
    
    if current_sample:
        samples.append(current_sample)
    
    print(f"📚 加载了 {len(samples)} 个评分样本")
    return samples

def load_sample_vectors():
    """加载样本向量"""
    vectors_file = "data/universal_samples_vectors.npy"
    data_file = "data/universal_samples_data.json"
    
    if not os.path.exists(vectors_file) or not os.path.exists(data_file):
        print("⚠️ 样本向量文件不存在，请先运行 handle_universal_samples.py")
        return None, None
    
    vectors = np.load(vectors_file)
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    return vectors, data

def find_high_score_samples(query, scored_samples, min_score=70, top_k=5, min_emotion_intensity=0.6):
    """查找高分且高情绪强度的样本"""
    if not scored_samples:
        return []
    
    # 过滤高分样本
    high_score_samples = [s for s in scored_samples if s.get('score', 0) >= min_score]
    
    if not high_score_samples:
        print(f"⚠️ 没有找到评分 >= {min_score} 的样本")
        return []
    
    # 使用情绪分析器评估样本的情绪强度
    emotion_analyzer = EmotionAnalyzer()
    emotion_scored_samples = []
    
    for sample in high_score_samples:
        # 分析情绪强度
        emotion_result = emotion_analyzer.analyze(sample['content'])
        emotion_intensity = emotion_result.intensity
        
        # 只保留高情绪强度的样本
        if emotion_intensity >= min_emotion_intensity:
            emotion_scored_samples.append({
                'sample': sample,
                'emotion_intensity': emotion_intensity,
                'emotion_label': emotion_result.label
            })
    
    if not emotion_scored_samples:
        print(f"⚠️ 没有找到情绪强度 >= {min_emotion_intensity} 的高分样本")
        # 如果没有高情绪样本，至少返回高分样本
        emotion_scored_samples = [{'sample': s, 'emotion_intensity': 0.5, 'emotion_label': 'unknown'} 
                                  for s in high_score_samples[:top_k]]
    
    # 简单的关键词匹配（可以后续优化为语义搜索）
    query_words = set(query.lower().split())
    scored_matches = []
    
    for item in emotion_scored_samples:
        sample = item['sample']
        content_words = set(sample['content'].lower().split())
        # 计算词汇重叠度
        overlap = len(query_words.intersection(content_words))
        if overlap > 0 or len(emotion_scored_samples) <= top_k:
            # 综合评分：评分权重0.4，情绪强度权重0.4，重叠度权重0.2
            combined_score = (
                sample.get('score', 0) / 100 * 0.4 +
                item['emotion_intensity'] * 0.4 +
                overlap / max(len(query_words), 1) * 0.2
            )
            scored_matches.append((item, combined_score))
    
    # 按综合得分排序
    scored_matches.sort(key=lambda x: x[1], reverse=True)
    
    # 返回样本（包含情绪信息）
    result = []
    for match in scored_matches[:top_k]:
        item = match[0]
        sample = item['sample'].copy()
        sample['emotion_intensity'] = item['emotion_intensity']
        sample['emotion_label'] = item['emotion_label']
        result.append(sample)
    
    return result

def build_enhanced_prompt(user_input, scored_samples, regular_samples, target_context=""):
    """构建增强版提示词"""
    prompt_parts = []
    
    # 基础提示
    prompt_parts.append("你是一个专业的小说生成器，擅长创作高情绪评分的情节内容。")
    
    # 高分样本指导
    if scored_samples:
        prompt_parts.append("\n## 高分高情绪样本参考 (请学习这些高评分、高情绪强度内容的写作技巧):")
        for i, sample in enumerate(scored_samples, 1):
            emotion_info = f"情绪强度: {sample.get('emotion_intensity', 0):.3f}, 情绪标签: {sample.get('emotion_label', 'N/A')}"
            prompt_parts.append(f"### 高分样本 {i} (评分: {sample['score']:.1f}, {emotion_info})")
            prompt_parts.append(f"内容: {sample['content']}")
            prompt_parts.append(f"特点: 这个样本在情绪渲染、情节张力方面表现优秀，情绪强度高，能够触动读者心弦")
            prompt_parts.append("")
    
    # 常规样本参考
    if regular_samples:
        prompt_parts.append("## 相关样本参考:")
        for i, sample in enumerate(regular_samples, 1):
            adapted_content = adapt_sample_content(sample['content'], target_context)
            prompt_parts.append(f"### 参考样本 {i}")
            prompt_parts.append(f"内容: {adapted_content}")
            prompt_parts.append("")
    
    # 生成要求
    prompt_parts.append("## 生成要求（高情绪强度）:")
    prompt_parts.append("1. 参考上述高分样本的写作技巧和情绪渲染方式，特别是高情绪强度的表达技巧")
    prompt_parts.append("2. 【核心要求】确保情绪强度足够高（目标>=0.6）：")
    prompt_parts.append("   - 包含强烈的情感表达，使用具体细节描写（如'心跳仿佛要冲出胸腔'而非'很紧张'）")
    prompt_parts.append("   - 包含多种情绪维度（恐惧、紧张、期待、愤怒、悲伤、喜悦等），避免单一情绪")
    prompt_parts.append("   - 要有深层情绪表达（通过隐喻、转折、对比等隐含表达）")
    prompt_parts.append("   - 要有明显的情绪变化和转折，制造情绪波动")
    prompt_parts.append("   - 每100字至少包含2-3个情绪词汇，情绪句子占比应达到40%以上")
    prompt_parts.append("   - 使用环境描写烘托情绪（如'黑暗的角落'、'急促的脚步声'）")
    prompt_parts.append("   - 通过身体反应增强代入感（如'手心冒汗'、'呼吸急促'）")
    prompt_parts.append("   - 使用短句和断句制造紧张感")
    prompt_parts.append("3. 保持情节的紧张感和吸引力")
    prompt_parts.append("4. 确保内容连贯，符合上下文")
    prompt_parts.append("5. 目标情绪评分应达到70分以上，情绪强度应达到0.6以上")
    
    # 用户输入
    prompt_parts.append(f"\n## 生成任务:")
    prompt_parts.append(f"{user_input}")
    
    if target_context:
        prompt_parts.append(f"\n## 上下文信息:")
        prompt_parts.append(f"{target_context}")
    
    return "\n".join(prompt_parts)

def generate_with_enhanced_rag(project_name, chapter_num, user_input, num_versions=3, min_score=70, min_emotion_intensity=0.6):
    """使用增强RAG生成章节，优先使用高情绪强度样本"""
    print(f"🚀 启动增强RAG生成器 v2.0（高情绪强度模式）")
    print(f"📖 项目: {project_name}")
    print(f"📄 章节: {chapter_num}")
    print(f"🎯 目标评分: >= {min_score}")
    print(f"🎭 目标情绪强度: >= {min_emotion_intensity}")
    
    # 加载评分样本
    scored_samples = load_scored_samples()
    
    # 加载常规样本向量
    sample_vectors, sample_data = load_sample_vectors()
    
    if sample_vectors is None or sample_data is None:
        print("❌ 无法加载样本数据")
        return False
    
    # 加载项目配置
    config_file = f"config/project_configs.json"
    if os.path.exists(config_file):
        with open(config_file, 'r', encoding='utf-8') as f:
            configs = json.load(f)
        project_config = configs.get(project_name, {})
    else:
        project_config = {}
    
    # 构建目标上下文
    target_context = f"项目: {project_name}\n"
    if project_config:
        target_context += f"主要角色: {', '.join(project_config.get('main_characters', []))}\n"
        target_context += f"背景设定: {project_config.get('background', '')}\n"
        target_context += f"写作风格: {project_config.get('style', '')}\n"
    
    # 查找高分且高情绪强度的样本
    high_score_samples = find_high_score_samples(user_input, scored_samples, min_score, min_emotion_intensity=min_emotion_intensity)
    print(f"🎯 找到 {len(high_score_samples)} 个高分高情绪样本 (评分 >= {min_score}, 情绪强度 >= {min_emotion_intensity})")
    if high_score_samples:
        avg_emotion = sum(s.get('emotion_intensity', 0) for s in high_score_samples) / len(high_score_samples)
        print(f"   平均情绪强度: {avg_emotion:.3f}")
    
    # 查找常规相关样本
    regular_samples = find_similar_samples(user_input, sample_vectors, sample_data, top_k=3)
    print(f"📚 找到 {len(regular_samples)} 个相关样本")
    
    # 生成多个版本
    results = []
    for i in range(num_versions):
        print(f"\n📝 生成版本 {i+1}/{num_versions}")
        
        # 构建提示词
        prompt = build_enhanced_prompt(user_input, high_score_samples, regular_samples, target_context)
        
        # 这里应该调用实际的生成模型
        # 由于没有实际的API，我们生成一个示例
        generated_content = f"""
# 第{chapter_num}章 - 版本{i+1}

基于高分样本参考生成的内容：

{user_input}

[此处应该是AI生成的实际内容，参考了评分{min_score}+的高分样本]

---
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
使用样本: {len(high_score_samples)}个高分样本 + {len(regular_samples)}个相关样本
目标评分: >= {min_score}
"""
        
        results.append({
            'version': i+1,
            'content': generated_content,
            'prompt': prompt,
            'high_score_samples_used': len(high_score_samples),
            'regular_samples_used': len(regular_samples)
        })
    
    # 保存结果
    output_dir = "outputs"
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"{output_dir}/ch{chapter_num}_enhanced_rag_{timestamp}.txt"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"# 增强RAG生成结果\n")
        f.write(f"项目: {project_name}\n")
        f.write(f"章节: {chapter_num}\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"目标评分: >= {min_score}\n")
        f.write(f"使用高分样本: {len(high_score_samples)} 个\n")
        f.write(f"使用相关样本: {len(regular_samples)} 个\n")
        f.write("=" * 60 + "\n\n")
        
        for result in results:
            f.write(result['content'])
            f.write("\n" + "=" * 60 + "\n\n")
    
    print(f"✅ 生成完成，结果保存到: {output_file}")
    return True

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="增强版RAG生成器 v2.0")
    parser.add_argument("--project", default="暗河噬城", help="项目名称")
    parser.add_argument("--chapter", type=int, default=1, help="章节编号")
    parser.add_argument("--prompt", required=True, help="生成提示")
    parser.add_argument("--versions", type=int, default=3, help="生成版本数")
    parser.add_argument("--min_score", type=float, default=70, help="最低样本评分")
    parser.add_argument("--min_emotion", type=float, default=0.6, help="最低情绪强度要求（0-1）")
    
    args = parser.parse_args()
    
    success = generate_with_enhanced_rag(
        args.project, 
        args.chapter, 
        args.prompt, 
        args.versions,
        args.min_score,
        args.min_emotion
    )
    
    if success:
        print("🎉 增强RAG生成完成！")
    else:
        print("❌ 生成失败")

if __name__ == "__main__":
    main()

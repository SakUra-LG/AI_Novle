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
import re
import glob
from datetime import datetime

# 获取脚本所在目录的父目录（bert_excitation_train目录）作为基础路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.append(BASE_DIR)

from scripts.smart_sample_search import find_similar_samples, adapt_sample_content
from scripts.paragraph_scorer import ParagraphScorer
from scripts.optimized_rule_scorer import OptimizedRuleScorer
from scripts.emotion_analyzer import EmotionAnalyzer

def load_scored_samples():
    """加载已评分的样本（优先从JSON文件加载，因为包含真实评分）"""
    data_file = os.path.join(BASE_DIR, "data", "universal_samples_data.json")
    
    # 优先从JSON文件加载（包含真实评分）
    if os.path.exists(data_file):
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        samples = data.get("samples", [])
        
        # 过滤出有评分的样本
        scored_samples = [s for s in samples if s.get('score', 0) > 0]
        print(f"📚 从JSON加载了 {len(samples)} 个样本，其中 {len(scored_samples)} 个有评分")
        return scored_samples if scored_samples else samples
    
    # 如果JSON文件不存在，尝试从txt文件加载（向后兼容）
    scored_file = os.path.join(BASE_DIR, "data", "universal_samples_scored.txt")
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
    
    print(f"📚 从TXT加载了 {len(samples)} 个评分样本")
    return samples

def load_sample_vectors():
    """加载样本向量"""
    vectors_file = os.path.join(BASE_DIR, "data", "universal_samples_vectors.npy")
    data_file = os.path.join(BASE_DIR, "data", "universal_samples_data.json")
    
    if not os.path.exists(vectors_file) or not os.path.exists(data_file):
        print("⚠️ 样本向量文件不存在，请先运行 handle_universal_samples.py")
        return None, None
    
    vectors = np.load(vectors_file)
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 返回向量和样本列表（而不是整个data字典）
    samples = data.get("samples", [])
    if len(samples) != vectors.shape[0]:
        print(f"⚠️ 警告：样本数({len(samples)}) ≠ 向量数({vectors.shape[0]})")
    
    return vectors, samples

def load_chapter_outline(chapter_num, master_ctx_file=None):
    """加载章节梗概"""
    if master_ctx_file is None:
        master_ctx_file = os.path.join(BASE_DIR, "outputs", "master_ctx.txt")
    elif not os.path.isabs(master_ctx_file):
        # 如果是相对路径，基于BASE_DIR解析
        master_ctx_file = os.path.join(BASE_DIR, master_ctx_file)
    
    if not os.path.exists(master_ctx_file):
        print(f"⚠️ 章节梗概文件不存在: {master_ctx_file}")
        return None
    
    with open(master_ctx_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 查找对应章节的梗概
    # 格式：第X章 ：标题……：内容描述
    pattern = rf'第{chapter_num}章\s*[：:]\s*([^：:]+?)[：:]\s*(.+?)(?=\n第|\Z)'
    match = re.search(pattern, content, re.DOTALL)
    
    if match:
        title = match.group(1).strip()
        outline = match.group(2).strip()
        return {
            'chapter': chapter_num,
            'title': title,
            'outline': outline
        }
    
    # 检查是否是范围章节（如第11-15章）
    range_pattern = rf'第(\d+)-(\d+)章\s+(.+?)(?=\n第|\Z)'
    for match in re.finditer(range_pattern, content, re.DOTALL):
        start_ch = int(match.group(1))
        end_ch = int(match.group(2))
        if start_ch <= chapter_num <= end_ch:
            outline = match.group(3).strip()
            return {
                'chapter': chapter_num,
                'title': f"第{start_ch}-{end_ch}章",
                'outline': outline
            }
    
    print(f"⚠️ 未找到第{chapter_num}章的梗概")
    return None

def load_prev_life_clue(chapter_num, prev_life_file=None):
    """加载上一世线索"""
    if prev_life_file is None:
        prev_life_file = os.path.join(BASE_DIR, "outputs", "prev_life_ctx.txt")
    elif not os.path.isabs(prev_life_file):
        # 如果是相对路径，基于BASE_DIR解析
        prev_life_file = os.path.join(BASE_DIR, prev_life_file)
    
    if not os.path.exists(prev_life_file):
        print(f"⚠️ 上一世线索文件不存在: {prev_life_file}")
        return None
    
    with open(prev_life_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 查找对应章节的线索
    # 格式：第X章对应线索：线索内容（对应今生第X章）
    pattern = rf'第{chapter_num}章对应线索[：:]\s*(.+?)(?=\n第|\Z)'
    match = re.search(pattern, content, re.DOTALL)
    
    if match:
        clue = match.group(1).strip()
        # 移除末尾的"（对应今生第X章）"注释
        clue = re.sub(r'\s*\(对应今生第\d+章\)\s*$', '', clue)
        return {
            'chapter': chapter_num,
            'clue': clue
        }
    
    print(f"⚠️ 未找到第{chapter_num}章的上一世线索")
    return None

def extract_pure_content(generated_content):
    """从生成内容中提取纯正文（移除元数据）"""
    # 移除开头的标题和元数据行
    lines = generated_content.split('\n')
    pure_lines = []
    skip_metadata = False
    
    for line in lines:
        # 跳过标题行（以#开头）
        if line.strip().startswith('#'):
            continue
        # 跳过元数据分隔线
        if line.strip().startswith('---') or line.strip().startswith('==='):
            skip_metadata = True
            continue
        # 跳过元数据行（包含"章节梗概"、"上一世线索"、"使用样本"等）
        if skip_metadata or any(keyword in line for keyword in ['章节梗概:', '上一世线索:', '使用样本:', '目标评分:', '生成时间:']):
            continue
        # 跳过空行（如果还没有开始正文）
        if not pure_lines and not line.strip():
            continue
        pure_lines.append(line)
    
    # 移除末尾的空行
    while pure_lines and not pure_lines[-1].strip():
        pure_lines.pop()
    
    return '\n'.join(pure_lines).strip()

def load_previous_chapter(project_name, chapter_num, search_dirs=None):
    """加载上一章正文（如果存在）"""
    if chapter_num <= 1:
        return None
    
    prev_chapter_num = chapter_num - 1
    
    # 默认搜索目录
    if search_dirs is None:
        search_dirs = [
            os.path.join(BASE_DIR, "outputs", "chapters"),
            os.path.join(BASE_DIR, "data", "chapters"),
            os.path.join(BASE_DIR, "data", "generated"),
            os.path.join(BASE_DIR, "data", "generated", project_name),
            os.path.join(BASE_DIR, "outputs")
        ]
    
    # 可能的文件名模式
    patterns = [
        f"ch{prev_chapter_num}_*.txt",
        f"chapter_{prev_chapter_num:03d}.txt",
        f"chapter_{prev_chapter_num}.txt",
        f"ch{prev_chapter_num}_v*.txt",
        f"ch{prev_chapter_num}_enhanced_rag_*.txt"
    ]
    
    for search_dir in search_dirs:
        if not os.path.exists(search_dir):
            continue
        
        for pattern in patterns:
            files = glob.glob(os.path.join(search_dir, pattern))
            if files:
                # 优先选择最新的文件
                files.sort(key=os.path.getmtime, reverse=True)
                try:
                    with open(files[0], 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                    if content:
                        print(f"📖 加载上一章正文: {files[0]}")
                        return {
                            'chapter': prev_chapter_num,
                            'content': content
                        }
                except Exception as e:
                    print(f"⚠️ 读取上一章文件失败: {files[0]}, 错误: {e}")
                    continue
    
    print(f"⚠️ 未找到第{prev_chapter_num}章的正文文件")
    return None

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

def build_enhanced_prompt(user_input, scored_samples, regular_samples, target_context="", 
                         chapter_outline=None, prev_life_clue=None, prev_chapter=None):
    """构建增强版提示词"""
    prompt_parts = []
    
    # 基础提示
    prompt_parts.append("你是一个专业的小说生成器，擅长创作高情绪评分的情节内容，特别是重生复仇类小说。")
    
    # 章节梗概（必须）
    if chapter_outline:
        prompt_parts.append("\n## 📋 本章章节梗概（必须严格遵循）:")
        prompt_parts.append(f"**第{chapter_outline['chapter']}章: {chapter_outline['title']}**")
        prompt_parts.append(f"{chapter_outline['outline']}")
        prompt_parts.append("\n**重要提示**: 生成的内容必须严格符合上述章节梗概，不能偏离主要情节。")
    
    # 上一世线索（必须）
    if prev_life_clue:
        prompt_parts.append("\n## 🔥 上一世对应线索（用于描绘重生复仇场景）:")
        prompt_parts.append(f"{prev_life_clue['clue']}")
        prompt_parts.append("\n**使用要求**:")
        prompt_parts.append("1. 在适当的时候触发上一世的记忆（当遇到相关人物、地点、事件时）")
        prompt_parts.append("2. 通过对比上一世的痛苦和今生的冷静，展现重生复仇的情绪张力")
        prompt_parts.append("3. 使用'她记得'、'她想起'、'脑海中浮现'等自然过渡到回忆")
        prompt_parts.append("4. 回忆要简短有力（50-150字），重点突出情绪对比和复仇动机")
        prompt_parts.append("5. 回忆后立即回到今生，展现主角的冷静预判和提前布局")
    
    # 上一章正文（用于衔接）
    if prev_chapter:
        prompt_parts.append(f"\n## 📖 上一章正文（第{prev_chapter['chapter']}章）:")
        # 只取最后一段或最后500字，避免上下文过长
        prev_content = prev_chapter['content']
        if len(prev_content) > 500:
            # 尝试取最后一段
            lines = prev_content.split('\n')
            last_paragraph = lines[-1] if lines else ""
            if len(last_paragraph) < 200:
                # 如果最后一段太短，取最后500字
                prev_content = prev_content[-500:]
            else:
                prev_content = last_paragraph
        
        prompt_parts.append(f"{prev_content}")
        prompt_parts.append("\n**衔接要求**:")
        prompt_parts.append("1. 本章开头必须与上一章结尾自然衔接，不能出现明显的跳脱")
        prompt_parts.append("2. 保持人物状态、时间、地点的连贯性")
        prompt_parts.append("3. 如果上一章有悬念或未完成的情节，本章要适当呼应")
    
    # 高分样本指导
    if scored_samples:
        prompt_parts.append("\n## 🌟 高分高情绪样本参考 (请学习这些高评分、高情绪强度内容的写作技巧):")
        for i, sample in enumerate(scored_samples, 1):
            emotion_info = f"情绪强度: {sample.get('emotion_intensity', 0):.3f}, 情绪标签: {sample.get('emotion_label', 'N/A')}"
            prompt_parts.append(f"### 高分样本 {i} (评分: {sample['score']:.1f}, {emotion_info})")
            prompt_parts.append(f"内容: {sample['content']}")
            prompt_parts.append(f"特点: 这个样本在情绪渲染、情节张力方面表现优秀，情绪强度高，能够触动读者心弦")
            prompt_parts.append("")
    
    # 常规样本参考
    if regular_samples:
        prompt_parts.append("## 📚 相关样本参考:")
        for i, sample in enumerate(regular_samples, 1):
            adapted_content = adapt_sample_content(sample['content'], target_context)
            prompt_parts.append(f"### 参考样本 {i}")
            prompt_parts.append(f"内容: {adapted_content}")
            prompt_parts.append("")
    
    # 生成要求
    prompt_parts.append("## ✍️ 生成要求（高情绪强度 + 重生复仇风格）:")
    prompt_parts.append("1. **严格遵循章节梗概**: 生成的内容必须符合章节梗概描述的主要情节")
    prompt_parts.append("2. **重生复仇核心要素**:")
    prompt_parts.append("   - 主角是重生者，拥有上一世的记忆和痛苦经历")
    prompt_parts.append("   - 在遇到相关人物/地点/事件时，自然触发上一世记忆")
    prompt_parts.append("   - 通过对比展现：上一世的痛苦 vs 今生的冷静预判")
    prompt_parts.append("   - 展现主角的提前布局和精准反击")
    prompt_parts.append("   - 情绪变化：从痛苦回忆 → 冷静分析 → 果断行动")
    prompt_parts.append("3. **高情绪强度要求（目标>=0.6）**:")
    prompt_parts.append("   - 包含强烈的情感表达，使用具体细节描写（如'心跳仿佛要冲出胸腔'而非'很紧张'）")
    prompt_parts.append("   - 包含多种情绪维度（恐惧、紧张、期待、愤怒、悲伤、喜悦等），避免单一情绪")
    prompt_parts.append("   - 要有深层情绪表达（通过隐喻、转折、对比等隐含表达）")
    prompt_parts.append("   - 要有明显的情绪变化和转折，制造情绪波动")
    prompt_parts.append("   - 每100字至少包含2-3个情绪词汇，情绪句子占比应达到40%以上")
    prompt_parts.append("   - 使用环境描写烘托情绪（如'黑暗的角落'、'急促的脚步声'）")
    prompt_parts.append("   - 通过身体反应增强代入感（如'手心冒汗'、'呼吸急促'）")
    prompt_parts.append("   - 使用短句和断句制造紧张感")
    prompt_parts.append("4. **情节衔接**: 确保与上一章自然衔接，保持故事连贯性")
    prompt_parts.append("5. **字数要求**: 800-1200字，每1000字至少1个情绪点或反转")
    prompt_parts.append("6. **目标评分**: 情绪评分应达到70分以上，情绪强度应达到0.6以上")
    
    # 用户输入（如果提供了额外的提示）
    if user_input and user_input.strip():
        prompt_parts.append(f"\n## 📝 额外生成提示:")
        prompt_parts.append(f"{user_input}")
    
    # 项目上下文
    if target_context:
        prompt_parts.append(f"\n## 📌 项目上下文信息:")
        prompt_parts.append(f"{target_context}")
    
    return "\n".join(prompt_parts)

def generate_with_enhanced_rag(project_name, chapter_num, user_input="", num_versions=3, min_score=70, min_emotion_intensity=0.6, master_ctx_file=None, prev_life_ctx_file=None):
    """使用增强RAG生成章节，优先使用高情绪强度样本，支持章节梗概和上一世线索"""
    print(f"🚀 启动增强RAG生成器 v2.0（高情绪强度模式 + 重生复仇）")
    print(f"📖 项目: {project_name}")
    print(f"📄 章节: {chapter_num}")
    print(f"🎯 目标评分: >= {min_score}")
    print(f"🎭 目标情绪强度: >= {min_emotion_intensity}")
    
    # 加载章节梗概（必须）
    chapter_outline = load_chapter_outline(chapter_num, master_ctx_file)
    if not chapter_outline:
        print("❌ 无法加载章节梗概，生成将无法进行")
        return False
    
    print(f"✅ 加载章节梗概: 第{chapter_num}章 - {chapter_outline['title']}")
    
    # 加载上一世线索（必须）
    prev_life_clue = load_prev_life_clue(chapter_num, prev_life_ctx_file)
    if not prev_life_clue:
        print("⚠️ 未找到上一世线索，将仅使用章节梗概生成")
    else:
        print(f"✅ 加载上一世线索: 第{chapter_num}章")
    
    # 加载上一章正文（用于衔接）
    prev_chapter = load_previous_chapter(project_name, chapter_num)
    if prev_chapter:
        print(f"✅ 找到上一章正文: 第{prev_chapter['chapter']}章")
    else:
        print(f"ℹ️ 未找到上一章正文（可能是第一章）")
    
    # 加载评分样本
    scored_samples = load_scored_samples()
    
    # 加载常规样本向量
    sample_vectors, sample_data = load_sample_vectors()
    
    if sample_vectors is None or sample_data is None:
        print("❌ 无法加载样本数据")
        return False
    
    # 加载项目配置
    config_file = os.path.join(BASE_DIR, "config", "project_configs.json")
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
    
    # 构建查询文本（用于样本检索）
    query_text = chapter_outline['outline']
    if prev_life_clue:
        query_text += " " + prev_life_clue['clue']
    if user_input:
        query_text += " " + user_input
    
    # 查找高分且高情绪强度的样本
    high_score_samples = find_high_score_samples(query_text, scored_samples, min_score, min_emotion_intensity=min_emotion_intensity)
    print(f"🎯 找到 {len(high_score_samples)} 个高分高情绪样本 (评分 >= {min_score}, 情绪强度 >= {min_emotion_intensity})")
    if high_score_samples:
        avg_emotion = sum(s.get('emotion_intensity', 0) for s in high_score_samples) / len(high_score_samples)
        print(f"   平均情绪强度: {avg_emotion:.3f}")
    
    # 查找常规相关样本
    regular_samples = find_similar_samples(query_text, sample_vectors, sample_data, top_k=3)
    print(f"📚 找到 {len(regular_samples)} 个相关样本")
    
    # 生成多个版本
    results = []
    for i in range(num_versions):
        print(f"\n📝 生成版本 {i+1}/{num_versions}")
        
        # 构建提示词（包含章节梗概、上一世线索、上一章正文）
        prompt = build_enhanced_prompt(
            user_input, 
            high_score_samples, 
            regular_samples, 
            target_context,
            chapter_outline=chapter_outline,
            prev_life_clue=prev_life_clue,
            prev_chapter=prev_chapter
        )
        
        # 这里应该调用实际的生成模型
        # 由于没有实际的API，我们生成一个示例
        generated_content = f"""
# 第{chapter_num}章 - {chapter_outline['title']} - 版本{i+1}

[此处应该是AI生成的实际内容，严格遵循章节梗概，融入上一世线索，与上一章自然衔接]

章节梗概: {chapter_outline['outline']}
上一世线索: {prev_life_clue['clue'] if prev_life_clue else '无'}
使用样本: {len(high_score_samples)}个高分样本 + {len(regular_samples)}个相关样本
目标评分: >= {min_score}

---
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        results.append({
            'version': i+1,
            'content': generated_content,
            'prompt': prompt,
            'high_score_samples_used': len(high_score_samples),
            'regular_samples_used': len(regular_samples),
            'chapter_outline': chapter_outline,
            'prev_life_clue': prev_life_clue
        })
    
    # 保存结果
    output_dir = os.path.join(BASE_DIR, "outputs")
    os.makedirs(output_dir, exist_ok=True)
    
    # 同时保存到 chapters 目录（用于后续章节加载）
    chapters_dir = os.path.join(output_dir, "chapters")
    os.makedirs(chapters_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"ch{chapter_num}_enhanced_rag_{timestamp}.txt")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"# 增强RAG生成结果（重生复仇）\n")
        f.write(f"项目: {project_name}\n")
        f.write(f"章节: {chapter_num} - {chapter_outline['title']}\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"目标评分: >= {min_score}\n")
        f.write(f"使用高分样本: {len(high_score_samples)} 个\n")
        f.write(f"使用相关样本: {len(regular_samples)} 个\n")
        if prev_life_clue:
            f.write(f"上一世线索: {prev_life_clue['clue']}\n")
        f.write("=" * 60 + "\n\n")
        
        for result in results:
            f.write(result['content'])
            f.write("\n" + "=" * 60 + "\n\n")
    
    # 保存最佳版本到 chapters 目录（用于后续章节加载）
    # 这里简单选择第一个版本，实际应该根据评分选择最佳版本
    best_version_file = os.path.join(chapters_dir, f"chapter_{chapter_num:03d}.txt")
    # 提取纯正文内容（移除元数据）
    pure_content = extract_pure_content(results[0]['content'])
    if not pure_content:
        # 如果没有提取到纯正文，使用原始内容
        pure_content = results[0]['content']
    
    with open(best_version_file, 'w', encoding='utf-8') as f:
        f.write(pure_content)
    print(f"📁 最佳版本已保存到: {best_version_file}")
    
    print(f"✅ 生成完成，结果保存到: {output_file}")
    return True

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="增强版RAG生成器 v2.0（支持章节梗概和上一世线索）")
    parser.add_argument("--project", default="暗河噬城", help="项目名称")
    parser.add_argument("--chapter", type=int, required=True, help="章节编号（必须）")
    parser.add_argument("--prompt", default="", help="额外生成提示（可选，章节梗概和上一世线索会自动加载）")
    parser.add_argument("--versions", type=int, default=3, help="生成版本数")
    parser.add_argument("--min_score", type=float, default=70, help="最低样本评分")
    parser.add_argument("--min_emotion", type=float, default=0.6, help="最低情绪强度要求（0-1）")
    parser.add_argument("--master_ctx", default=None, help="章节梗概文件路径（默认: outputs/master_ctx.txt）")
    parser.add_argument("--prev_life_ctx", default=None, help="上一世线索文件路径（默认: outputs/prev_life_ctx.txt）")
    
    args = parser.parse_args()
    
    # 处理文件路径：如果提供了相对路径，转换为基于BASE_DIR的绝对路径
    master_ctx_file = args.master_ctx
    if master_ctx_file and not os.path.isabs(master_ctx_file):
        master_ctx_file = os.path.join(BASE_DIR, master_ctx_file)
    
    prev_life_ctx_file = args.prev_life_ctx
    if prev_life_ctx_file and not os.path.isabs(prev_life_ctx_file):
        prev_life_ctx_file = os.path.join(BASE_DIR, prev_life_ctx_file)
    
    success = generate_with_enhanced_rag(
        args.project, 
        args.chapter, 
        args.prompt, 
        args.versions,
        args.min_score,
        args.min_emotion,
        master_ctx_file,
        prev_life_ctx_file
    )
    
    if success:
        print("🎉 增强RAG生成完成！")
        chapters_dir = os.path.join(BASE_DIR, "outputs", "chapters")
        print(f"📝 提示: 生成的内容已保存，最佳版本保存在 {os.path.join(chapters_dir, f'chapter_{args.chapter:03d}.txt')}")
        print(f"📝 提示: 下次生成第{args.chapter+1}章时，会自动加载本章作为上下文")
    else:
        print("❌ 生成失败")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
准备训练数据脚本
将生成的内容转换为训练数据格式
"""

import os
import sys
import pandas as pd
import json
import argparse
from datetime import datetime
from optimized_rule_scorer import OptimizedRuleScorer
from emotion_analyzer import EmotionAnalyzer

def prepare_training_data_from_feedback(feedback_csv="outputs/feedback_log.csv", 
                                      output_file="data/training/high_quality_training_data.csv",
                                      min_score=70, min_emotion_intensity=0.6):
    """从反馈数据中准备训练数据，优先选择高情绪强度样本"""
    
    if not os.path.exists(feedback_csv):
        print(f"[ERROR] 反馈文件不存在: {feedback_csv}")
        return
    
    df = pd.read_csv(feedback_csv)
    
    # 筛选高质量样本
    if 'user_feedback' in df.columns:
        # 优先使用用户反馈
        high_quality = df[
            (df['user_feedback'] >= min_score) | 
            (df['model_score'] >= min_score)
        ]
    else:
        # 只使用模型评分
        high_quality = df[df['model_score'] >= min_score]
    
    print(f"从 {len(df)} 条记录中筛选出 {len(high_quality)} 条高质量样本")
    
    if len(high_quality) == 0:
        print("[WARNING] 没有找到高质量样本")
        return
    
    # 使用情绪分析器评估样本的情绪强度
    print(f"评估样本情绪强度（目标 >= {min_emotion_intensity}）...")
    emotion_analyzer = EmotionAnalyzer()
    training_data = []
    emotion_scores = []
    
    for _, row in high_quality.iterrows():
        # 读取完整内容
        content_file = f"data/candidates/{row['candidate_file']}"
        if os.path.exists(content_file):
            with open(content_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            # 分析情绪强度
            emotion_result = emotion_analyzer.analyze(content)
            emotion_intensity = emotion_result.intensity
            
            training_data.append({
                'text': content,
                'chapter_num': row['chapter_num'],
                'model_score': row['model_score'],
                'user_score': row.get('user_feedback', None),
                'file_name': row['file_name'],
                'emotion_intensity': emotion_intensity,
                'emotion_label': emotion_result.label
            })
            emotion_scores.append(emotion_intensity)
    
    # 按情绪强度排序，优先选择高情绪强度样本
    training_data.sort(key=lambda x: x['emotion_intensity'], reverse=True)
    
    # 筛选高情绪强度样本
    high_emotion_data = [d for d in training_data if d['emotion_intensity'] >= min_emotion_intensity]
    
    print(f"  总样本数: {len(training_data)}")
    print(f"  高情绪强度样本（>= {min_emotion_intensity}）: {len(high_emotion_data)}")
    if emotion_scores:
        print(f"  平均情绪强度: {sum(emotion_scores) / len(emotion_scores):.3f}")
        print(f"  最高情绪强度: {max(emotion_scores):.3f}")
        print(f"  最低情绪强度: {min(emotion_scores):.3f}")
    
    # 优先使用高情绪强度样本，如果不够则补充其他样本
    if len(high_emotion_data) >= 10:
        training_data = high_emotion_data
        print(f"✅ 使用 {len(training_data)} 个高情绪强度样本作为训练数据")
    else:
        # 如果高情绪样本不够，至少保留前50%的高情绪样本
        keep_count = max(len(high_emotion_data), len(training_data) // 2)
        training_data = training_data[:keep_count]
        print(f"⚠️ 高情绪样本不足，使用前 {len(training_data)} 个样本（包含 {len(high_emotion_data)} 个高情绪样本）")
    
    # 保存训练数据
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    # 保存为CSV格式
    df_training = pd.DataFrame(training_data)
    df_training.to_csv(output_file, index=False, encoding='utf-8')
    print(f"训练数据已保存到: {output_file}")
    
    # 保存为JSONL格式
    jsonl_file = output_file.replace('.csv', '.jsonl')
    with open(jsonl_file, 'w', encoding='utf-8') as f:
        for _, row in df_training.iterrows():
            json.dump({'text': row['text']}, f, ensure_ascii=False)
            f.write('\n')
    print(f"JSONL格式已保存到: {jsonl_file}")
    
    return training_data

def prepare_training_data_from_samples(samples_file="data/universal_samples.txt",
                                     output_file="data/training/sample_training_data.csv",
                                     min_emotion_intensity=0.6):
    """从样本库中准备训练数据，优先选择高情绪强度样本"""
    
    if not os.path.exists(samples_file):
        print(f"[ERROR] 样本文件不存在: {samples_file}")
        return
    
    # 读取样本文件
    with open(samples_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 解析样本
    import re
    raw_samples = []
    blocks = re.split(r"\n\d+\.", content)
    
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        
        lines = block.splitlines()
        category = lines[0].strip("：:高评分样本").strip()
        
        paragraphs = re.findall(r'"(.*?)"', block, re.DOTALL)
        for p in paragraphs:
            text = p.strip()
            if text:
                raw_samples.append({
                    'text': text,
                    'category': category,
                    'source': 'sample_library'
                })
    
    print(f"从样本库中提取了 {len(raw_samples)} 个样本")
    
    # 使用情绪分析器评估样本的情绪强度
    print(f"评估样本情绪强度（目标 >= {min_emotion_intensity}）...")
    emotion_analyzer = EmotionAnalyzer()
    samples = []
    emotion_scores = []
    
    for sample in raw_samples:
        # 分析情绪强度
        emotion_result = emotion_analyzer.analyze(sample['text'])
        emotion_intensity = emotion_result.intensity
        
        sample['emotion_intensity'] = emotion_intensity
        sample['emotion_label'] = emotion_result.label
        samples.append(sample)
        emotion_scores.append(emotion_intensity)
    
    # 按情绪强度排序，优先选择高情绪强度样本
    samples.sort(key=lambda x: x['emotion_intensity'], reverse=True)
    
    # 筛选高情绪强度样本
    high_emotion_samples = [s for s in samples if s['emotion_intensity'] >= min_emotion_intensity]
    
    print(f"  总样本数: {len(samples)}")
    print(f"  高情绪强度样本（>= {min_emotion_intensity}）: {len(high_emotion_samples)}")
    if emotion_scores:
        print(f"  平均情绪强度: {sum(emotion_scores) / len(emotion_scores):.3f}")
        print(f"  最高情绪强度: {max(emotion_scores):.3f}")
        print(f"  最低情绪强度: {min(emotion_scores):.3f}")
    
    # 优先使用高情绪强度样本，如果不够则补充其他样本
    if len(high_emotion_samples) >= 10:
        samples = high_emotion_samples
        print(f"✅ 使用 {len(samples)} 个高情绪强度样本作为训练数据")
    else:
        # 如果高情绪样本不够，至少保留前50%的高情绪样本
        keep_count = max(len(high_emotion_samples), len(samples) // 2)
        samples = samples[:keep_count]
        print(f"⚠️ 高情绪样本不足，使用前 {len(samples)} 个样本（包含 {len(high_emotion_samples)} 个高情绪样本）")
    
    # 保存训练数据
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    df_samples = pd.DataFrame(samples)
    df_samples.to_csv(output_file, index=False, encoding='utf-8')
    print(f"样本训练数据已保存到: {output_file}")
    
    # 保存为JSONL格式
    jsonl_file = output_file.replace('.csv', '.jsonl')
    with open(jsonl_file, 'w', encoding='utf-8') as f:
        for _, row in df_samples.iterrows():
            json.dump({'text': row['text']}, f, ensure_ascii=False)
            f.write('\n')
    print(f"JSONL格式已保存到: {jsonl_file}")
    
    return samples

def combine_training_data(feedback_data_file="data/training/high_quality_training_data.csv",
                         sample_data_file="data/training/sample_training_data.csv",
                         output_file="data/training/combined_training_data.csv"):
    """合并训练数据"""
    
    combined_data = []
    
    # 加载反馈数据
    if os.path.exists(feedback_data_file):
        df_feedback = pd.read_csv(feedback_data_file)
        for _, row in df_feedback.iterrows():
            combined_data.append({
                'text': row['text'],
                'source': 'feedback',
                'score': row['model_score'],
                'chapter_num': row['chapter_num']
            })
        print(f"加载了 {len(df_feedback)} 条反馈数据")
    
    # 加载样本数据
    if os.path.exists(sample_data_file):
        df_samples = pd.read_csv(sample_data_file)
        for _, row in df_samples.iterrows():
            combined_data.append({
                'text': row['text'],
                'source': 'samples',
                'score': 85,  # 样本默认高分
                'category': row['category']
            })
        print(f"加载了 {len(df_samples)} 条样本数据")
    
    if not combined_data:
        print("[ERROR] 没有找到任何训练数据")
        return
    
    # 保存合并数据
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    df_combined = pd.DataFrame(combined_data)
    df_combined.to_csv(output_file, index=False, encoding='utf-8')
    print(f"合并训练数据已保存到: {output_file}")
    
    # 保存为JSONL格式
    jsonl_file = output_file.replace('.csv', '.jsonl')
    with open(jsonl_file, 'w', encoding='utf-8') as f:
        for _, row in df_combined.iterrows():
            json.dump({'text': row['text']}, f, ensure_ascii=False)
            f.write('\n')
    print(f"JSONL格式已保存到: {jsonl_file}")
    
    # 统计信息
    print(f"\n训练数据统计:")
    print(f"  总样本数: {len(combined_data)}")
    print(f"  反馈数据: {len([d for d in combined_data if d['source'] == 'feedback'])}")
    print(f"  样本数据: {len([d for d in combined_data if d['source'] == 'samples'])}")
    print(f"  平均评分: {df_combined['score'].mean():.2f}")
    
    return combined_data

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='准备训练数据脚本')
    parser.add_argument('--action', type=str, 
                       choices=['from_feedback', 'from_samples', 'combine', 'all'],
                       default='all', help='执行的操作')
    parser.add_argument('--min_score', type=int, default=70, help='最低评分阈值')
    parser.add_argument('--min_emotion', type=float, default=0.6, help='最低情绪强度要求（0-1）')
    parser.add_argument('--feedback_csv', type=str, default='outputs/feedback_log.csv', help='反馈文件路径')
    parser.add_argument('--samples_file', type=str, default='data/universal_samples.txt', help='样本文件路径')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("准备训练数据脚本")
    print("=" * 60)
    
    if args.action in ['from_feedback', 'all']:
        print("从反馈数据准备训练数据...")
        prepare_training_data_from_feedback(args.feedback_csv, min_score=args.min_score, min_emotion_intensity=args.min_emotion)
    
    if args.action in ['from_samples', 'all']:
        print("从样本库准备训练数据...")
        prepare_training_data_from_samples(args.samples_file, min_emotion_intensity=args.min_emotion)
    
    if args.action in ['combine', 'all']:
        print("合并训练数据...")
        combine_training_data()
    
    print("训练数据准备完成！")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
记录反馈脚本
记录用户反馈和模型评分
"""

import os
import sys
import pandas as pd
import argparse
from datetime import datetime
from optimized_rule_scorer import OptimizedRuleScorer

def record_feedback(chapter_num, candidates_dir, feedback_csv="outputs/feedback_log.csv"):
    """记录章节反馈"""
    
    if not os.path.exists(candidates_dir):
        print(f"[ERROR] 候选目录不存在: {candidates_dir}")
        return
    
    # 初始化评分器
    scorer = OptimizedRuleScorer()
    
    # 读取现有反馈数据
    if os.path.exists(feedback_csv):
        df = pd.read_csv(feedback_csv)
    else:
        df = pd.DataFrame(columns=['timestamp', 'chapter_num', 'file_name', 'model_score', 'user_feedback', 'content_preview'])
    
    # 处理候选文件
    for filename in os.listdir(candidates_dir):
        if filename.endswith('.txt'):
            filepath = os.path.join(candidates_dir, filename)
            
            # 读取文件内容
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            if not content:
                continue
            
            # 计算模型评分
            model_score = scorer.calculate_score(content)
            
            # 获取用户反馈
            print(f"\n文件: {filename}")
            print(f"模型评分: {model_score:.2f}")
            print(f"内容预览: {content[:100]}...")
            
            user_feedback = input("请输入用户评分 (1-100，直接回车跳过): ").strip()
            
            if user_feedback:
                try:
                    user_score = float(user_feedback)
                    if 1 <= user_score <= 100:
                        # 记录反馈
                        new_row = {
                            'timestamp': datetime.now().isoformat(),
                            'chapter_num': chapter_num,
                            'file_name': filename,
                            'model_score': model_score,
                            'user_feedback': user_score,
                            'content_preview': content[:200]
                        }
                        
                        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                        print(f"已记录反馈: 模型评分 {model_score:.2f}, 用户评分 {user_score}")
                    else:
                        print("用户评分必须在1-100之间")
                except ValueError:
                    print("用户评分必须是数字")
            else:
                # 只记录模型评分
                new_row = {
                    'timestamp': datetime.now().isoformat(),
                    'chapter_num': chapter_num,
                    'file_name': filename,
                    'model_score': model_score,
                    'user_feedback': None,
                    'content_preview': content[:200]
                }
                
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                print(f"已记录模型评分: {model_score:.2f}")
    
    # 保存反馈数据
    os.makedirs(os.path.dirname(feedback_csv), exist_ok=True)
    df.to_csv(feedback_csv, index=False, encoding='utf-8')
    print(f"\n反馈数据已保存到: {feedback_csv}")

def analyze_feedback(feedback_csv="outputs/feedback_log.csv"):
    """分析反馈数据"""
    if not os.path.exists(feedback_csv):
        print(f"[ERROR] 反馈文件不存在: {feedback_csv}")
        return
    
    df = pd.read_csv(feedback_csv)
    
    print("=" * 60)
    print("反馈数据分析")
    print("=" * 60)
    
    # 基本统计
    print(f"总记录数: {len(df)}")
    print(f"章节数: {df['chapter_num'].nunique()}")
    
    if 'user_feedback' in df.columns:
        user_feedback_count = df['user_feedback'].notna().sum()
        print(f"用户反馈数: {user_feedback_count}")
        
        if user_feedback_count > 0:
            print(f"平均用户评分: {df['user_feedback'].mean():.2f}")
            print(f"平均模型评分: {df['model_score'].mean():.2f}")
            
            # 计算相关性
            correlation = df['model_score'].corr(df['user_feedback'])
            print(f"模型评分与用户评分相关性: {correlation:.3f}")
    
    # 按章节分析
    print("\n按章节分析:")
    chapter_stats = df.groupby('chapter_num').agg({
        'model_score': ['mean', 'std', 'count'],
        'user_feedback': ['mean', 'count']
    }).round(2)
    
    print(chapter_stats)
    
    # 低分分析
    low_score_threshold = 60
    low_score_count = (df['model_score'] < low_score_threshold).sum()
    print(f"\n低分样本数 (评分 < {low_score_threshold}): {low_score_count}")
    
    if low_score_count > 0:
        print("低分样本:")
        low_score_samples = df[df['model_score'] < low_score_threshold]
        for _, row in low_score_samples.iterrows():
            print(f"  章节 {row['chapter_num']}: {row['file_name']} (评分: {row['model_score']:.2f})")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='记录反馈脚本')
    parser.add_argument('--action', type=str, choices=['record', 'analyze'], 
                       default='record', help='执行的操作')
    parser.add_argument('--chapter', type=int, help='章节号')
    parser.add_argument('--candidates_dir', type=str, help='候选文件目录')
    parser.add_argument('--feedback_csv', type=str, default='outputs/feedback_log.csv', help='反馈文件路径')
    
    args = parser.parse_args()
    
    if args.action == 'record':
        if not args.chapter or not args.candidates_dir:
            print("[ERROR] 记录反馈需要指定章节号和候选文件目录")
            print("使用方法: python scripts/record_feedback.py --action record --chapter 24 --candidates_dir data/candidates")
            return
        
        record_feedback(args.chapter, args.candidates_dir, args.feedback_csv)
        
    elif args.action == 'analyze':
        analyze_feedback(args.feedback_csv)

if __name__ == "__main__":
    main()

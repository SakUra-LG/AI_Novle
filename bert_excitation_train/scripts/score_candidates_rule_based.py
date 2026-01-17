#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用基于规则的评分模型对候选章节进行评分
"""

import os
import sys
import argparse
import shutil
from optimized_rule_scorer import OptimizedRuleScorer

def score_candidates(candidates_dir, output_dir, chapter_num):
    """对候选章节进行评分并选择最佳版本"""
    
    if not os.path.exists(candidates_dir):
        print(f"[ERROR] 候选目录不存在: {candidates_dir}")
        return
    
    scorer = OptimizedRuleScorer()
    best_score = 0
    best_file = None
    results = []
    
    # 遍历所有候选文件
    for filename in os.listdir(candidates_dir):
        if filename.endswith('.txt'):
            filepath = os.path.join(candidates_dir, filename)
            
            # 读取文件内容
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            if not content:
                print(f"[WARNING] 文件为空: {filename}")
                continue
            
            # 计算分数
            score = scorer.calculate_score(content)
            results.append({
                'file': filename,
                'score': score,
                'content': content[:100] + '...' if len(content) > 100 else content
            })
            
            print(f"[INFO] {filename}: {score:.2f}分")
            
            # 更新最佳版本
            if score > best_score:
                best_score = score
                best_file = filename
    
    if not results:
        print("[ERROR] 没有找到有效的候选文件")
        return
    
    # 按分数排序
    results.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"\n[评分结果]")
    print("-" * 50)
    for i, result in enumerate(results, 1):
        print(f"{i}. {result['file']}: {result['score']:.2f}分")
        print(f"   内容预览: {result['content']}")
        print()
    
    # 选择最佳版本
    if best_file:
        print(f"[SUCCESS] 选择最佳版本: {best_file} (分数: {best_score:.2f})")
        
        # 复制到最终目录
        source_path = os.path.join(candidates_dir, best_file)
        target_path = os.path.join(output_dir, f"{chapter_num}.txt")
        
        os.makedirs(output_dir, exist_ok=True)
        shutil.copy2(source_path, target_path)
        
        print(f"[INFO] 最佳版本已保存到: {target_path}")
        
        # 保存评分日志
        log_file = f"outputs/chapter_{chapter_num}_scores_rule_based.csv"
        os.makedirs("outputs", exist_ok=True)
        
        import pandas as pd
        df = pd.DataFrame(results)
        df.to_csv(log_file, index=False, encoding='utf-8')
        print(f"[INFO] 评分日志已保存到: {log_file}")
        
        return best_file, best_score
    else:
        print("[ERROR] 没有找到最佳版本")
        return None, 0

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='使用基于规则的评分模型对候选章节进行评分')
    parser.add_argument('--candidates_dir', type=str, required=True, help='候选文件目录')
    parser.add_argument('--output_dir', type=str, required=True, help='输出目录')
    parser.add_argument('--chapter_num', type=int, required=True, help='章节号')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("基于规则的候选章节评分")
    print("=" * 60)
    print(f"候选目录: {args.candidates_dir}")
    print(f"输出目录: {args.output_dir}")
    print(f"章节号: {args.chapter_num}")
    print()
    
    best_file, best_score = score_candidates(
        args.candidates_dir, 
        args.output_dir, 
        args.chapter_num
    )
    
    if best_file:
        print(f"\n[SUCCESS] 评分完成！最佳版本: {best_file} (分数: {best_score:.2f})")
    else:
        print(f"\n[ERROR] 评分失败！")

if __name__ == "__main__":
    main()

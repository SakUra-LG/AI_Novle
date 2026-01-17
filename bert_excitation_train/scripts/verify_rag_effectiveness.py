#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证RAG系统效果
对比使用RAG和不使用RAG的生成质量
"""

import os
import sys
import json
from datetime import datetime
from optimized_rule_scorer import OptimizedRuleScorer

def test_with_rag(chapter_num, prompt):
    """使用RAG系统生成"""
    print("=" * 60)
    print("使用RAG系统生成")
    print("=" * 60)
    
    # 调用增强RAG生成器
    import subprocess
    result = subprocess.run([
        "python", "scripts/enhanced_rag_generator.py",
        "--chapter", str(chapter_num),
        "--prompt", prompt,
        "--versions", "1"
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        print("RAG生成成功")
        return True
    else:
        print(f"RAG生成失败: {result.stderr}")
        return False

def test_without_rag(chapter_num, prompt):
    """不使用RAG系统生成"""
    print("=" * 60)
    print("不使用RAG系统生成")
    print("=" * 60)
    
    # 调用手动生成器
    import subprocess
    result = subprocess.run([
        "python", "scripts/manual_generator.py"
    ], input=f"{prompt}\nquit\n", text=True, capture_output=True)
    
    if result.returncode == 0:
        print("非RAG生成成功")
        return True
    else:
        print(f"非RAG生成失败: {result.stderr}")
        return False

def analyze_generated_content():
    """分析生成内容的质量"""
    scorer = OptimizedRuleScorer()
    
    # 分析RAG生成的内容
    rag_dir = "data/generated/暗河噬城"
    rag_scores = []
    
    if os.path.exists(rag_dir):
        for filename in os.listdir(rag_dir):
            if filename.endswith('.txt'):
                filepath = os.path.join(rag_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        score = scorer.calculate_score(content)
                        rag_scores.append({
                            'file': filename,
                            'score': score,
                            'content': content[:100] + '...' if len(content) > 100 else content
                        })
    
    # 分析手动生成的内容
    manual_dir = "outputs"
    manual_scores = []
    
    if os.path.exists(manual_dir):
        for filename in os.listdir(manual_dir):
            if filename.startswith('generated_') and filename.endswith('.txt'):
                filepath = os.path.join(manual_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        score = scorer.calculate_score(content)
                        manual_scores.append({
                            'file': filename,
                            'score': score,
                            'content': content[:100] + '...' if len(content) > 100 else content
                        })
    
    return rag_scores, manual_scores

def compare_rag_effectiveness():
    """对比RAG系统效果"""
    print("=" * 60)
    print("RAG系统效果对比分析")
    print("=" * 60)
    
    # 分析生成内容
    rag_scores, manual_scores = analyze_generated_content()
    
    print(f"\nRAG系统生成内容分析:")
    print(f"  生成文件数: {len(rag_scores)}")
    if rag_scores:
        avg_rag_score = sum(s['score'] for s in rag_scores) / len(rag_scores)
        max_rag_score = max(s['score'] for s in rag_scores)
        min_rag_score = min(s['score'] for s in rag_scores)
        print(f"  平均评分: {avg_rag_score:.2f}")
        print(f"  最高评分: {max_rag_score:.2f}")
        print(f"  最低评分: {min_rag_score:.2f}")
        
        print(f"\nRAG生成内容详情:")
        for score_info in rag_scores:
            print(f"  {score_info['file']}: {score_info['score']:.2f}分")
            print(f"    {score_info['content']}")
    
    print(f"\n非RAG系统生成内容分析:")
    print(f"  生成文件数: {len(manual_scores)}")
    if manual_scores:
        avg_manual_score = sum(s['score'] for s in manual_scores) / len(manual_scores)
        max_manual_score = max(s['score'] for s in manual_scores)
        min_manual_score = min(s['score'] for s in manual_scores)
        print(f"  平均评分: {avg_manual_score:.2f}")
        print(f"  最高评分: {max_manual_score:.2f}")
        print(f"  最低评分: {min_manual_score:.2f}")
        
        print(f"\n非RAG生成内容详情:")
        for score_info in manual_scores:
            print(f"  {score_info['file']}: {score_info['score']:.2f}分")
            print(f"    {score_info['content']}")
    
    # 对比分析
    if rag_scores and manual_scores:
        avg_rag = sum(s['score'] for s in rag_scores) / len(rag_scores)
        avg_manual = sum(s['score'] for s in manual_scores) / len(manual_scores)
        
        print(f"\n对比分析:")
        print(f"  RAG平均评分: {avg_rag:.2f}")
        print(f"  非RAG平均评分: {avg_manual:.2f}")
        print(f"  评分提升: {avg_rag - avg_manual:.2f}")
        
        if avg_rag > avg_manual:
            print(f"  ✅ RAG系统有效提升了生成质量！")
        elif avg_rag < avg_manual:
            print(f"  ❌ RAG系统未提升生成质量")
        else:
            print(f"  ⚠️ RAG系统效果不明显")
    
    # 检查RAG样本库使用情况
    print(f"\nRAG样本库使用情况:")
    if os.path.exists('data/universal_samples_vectors.npy'):
        print(f"  ✅ 样本库已初始化")
        
        # 检查样本库内容
        if os.path.exists('data/universal_samples_data.json'):
            with open('data/universal_samples_data.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"  样本总数: {data['count']}")
            print(f"  分类数: {len(data['categories'])}")
            
            # 显示高评分样本
            high_score_samples = [s for s in data['samples'] if s['score'] >= 80]
            print(f"  高评分样本数: {len(high_score_samples)}")
            
            if high_score_samples:
                print(f"  高评分样本示例:")
                for i, sample in enumerate(high_score_samples[:3], 1):
                    print(f"    {i}. [{sample['category']}] {sample['content'][:50]}...")
    else:
        print(f"  ❌ 样本库未初始化")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='验证RAG系统效果')
    parser.add_argument('--chapter', type=int, default=24, help='测试章节号')
    parser.add_argument('--prompt', type=str, default='请写一段悬疑推理的情节', help='测试提示词')
    parser.add_argument('--action', type=str, choices=['test', 'analyze', 'compare'], 
                       default='compare', help='执行的操作')
    
    args = parser.parse_args()
    
    if args.action == 'test':
        # 测试生成
        test_with_rag(args.chapter, args.prompt)
        test_without_rag(args.chapter, args.prompt)
    elif args.action == 'analyze':
        # 分析现有内容
        rag_scores, manual_scores = analyze_generated_content()
        print(f"RAG生成: {len(rag_scores)} 个文件")
        print(f"非RAG生成: {len(manual_scores)} 个文件")
    elif args.action == 'compare':
        # 对比分析
        compare_rag_effectiveness()

if __name__ == "__main__":
    main()

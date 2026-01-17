#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多标签搜索示例
展示如何使用新的多标签系统进行智能检索
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.smart_sample_search import load_universal_samples, find_similar_samples

def example_1_basic_search():
    """示例1：基本语义搜索"""
    print("\n" + "="*60)
    print("示例1：基本语义搜索")
    print("="*60)
    
    # 加载样本库
    sample_vectors, samples = load_universal_samples()
    
    if sample_vectors is None:
        print("错误：请先运行 python scripts/handle_universal_samples.py 初始化样本库")
        return
    
    # 搜索"紧张的追逐场景"
    query = "紧张的追逐场景"
    results = find_similar_samples(query, sample_vectors, samples, top_k=3)
    
    print(f"\n查询: {query}")
    print(f"找到 {len(results)} 个相关样本:\n")
    
    for i, result in enumerate(results, 1):
        print(f"{i}. {result['title']}")
        print(f"   相似度: {result['similarity']:.3f}")
        print(f"   评分: {result['score']}")
        print(f"   情绪标签: {', '.join(result['emotion_tags'])}")
        print(f"   内容: {result['content'][:100]}...")
        print()

def example_2_tag_filtered_search():
    """示例2：基于标签过滤的搜索"""
    print("\n" + "="*60)
    print("示例2：基于标签过滤的搜索")
    print("="*60)
    
    sample_vectors, samples = load_universal_samples()
    
    if sample_vectors is None:
        return
    
    # 搜索"对决场景"，但必须包含"紧张"和"恐惧"情绪
    query = "激烈的对决场景"
    required_tags = {
        'emotion_tags': ['紧张', '恐惧']
    }
    
    results = find_similar_samples(
        query, 
        sample_vectors, 
        samples, 
        top_k=3,
        required_tags=required_tags
    )
    
    print(f"\n查询: {query}")
    print(f"必需标签: {required_tags}")
    print(f"找到 {len(results)} 个匹配样本:\n")
    
    for i, result in enumerate(results, 1):
        print(f"{i}. {result['title']}")
        print(f"   相似度: {result['similarity']:.3f}")
        print(f"   情绪标签: {', '.join(result['emotion_tags'])}")
        print(f"   场景标签: {', '.join(result['scene_tags'])}")
        print(f"   内容: {result['content'][:80]}...")
        print()

def example_3_high_score_search():
    """示例3：只检索高分样本"""
    print("\n" + "="*60)
    print("示例3：只检索高分样本（评分>=90）")
    print("="*60)
    
    sample_vectors, samples = load_universal_samples()
    
    if sample_vectors is None:
        return
    
    # 搜索高评分的危机场景
    query = "生死危机场景"
    
    results = find_similar_samples(
        query, 
        sample_vectors, 
        samples, 
        top_k=5,
        min_score=90  # 只要评分>=90的样本
    )
    
    print(f"\n查询: {query}")
    print(f"最低评分要求: 90分")
    print(f"找到 {len(results)} 个高分样本:\n")
    
    for i, result in enumerate(results, 1):
        print(f"{i}. {result['title']}")
        print(f"   评分: {result['score']} 分 ⭐")
        print(f"   相似度: {result['similarity']:.3f}")
        print(f"   情绪标签: {', '.join(result['emotion_tags'])}")
        print(f"   冲突标签: {', '.join(result['conflict_tags'])}")
        print()

def example_4_complex_search():
    """示例4：复杂组合搜索"""
    print("\n" + "="*60)
    print("示例4：复杂组合搜索")
    print("="*60)
    
    sample_vectors, samples = load_universal_samples()
    
    if sample_vectors is None:
        return
    
    # 搜索：现代都市背景 + 紧张情绪 + 高评分
    query = "城市中的危险场景"
    required_tags = {
        'emotion_tags': ['紧张'],
        'scene_tags': ['现代都市']
    }
    
    results = find_similar_samples(
        query, 
        sample_vectors, 
        samples, 
        top_k=5,
        required_tags=required_tags,
        min_score=85
    )
    
    print(f"\n查询: {query}")
    print(f"必需标签: {required_tags}")
    print(f"最低评分: 85分")
    print(f"找到 {len(results)} 个样本:\n")
    
    for i, result in enumerate(results, 1):
        print(f"{i}. {result['title']} (评分: {result['score']})")
        print(f"   相似度: {result['similarity']:.3f}")
        print(f"   情绪: {', '.join(result['emotion_tags'])}")
        print(f"   场景: {', '.join(result['scene_tags'])}")
        print(f"   冲突: {', '.join(result['conflict_tags'])}")
        print(f"   情节: {', '.join(result['plot_tags'])}")
        print()

def example_5_tag_statistics():
    """示例5：标签统计分析"""
    print("\n" + "="*60)
    print("示例5：样本库标签统计")
    print("="*60)
    
    _, samples = load_universal_samples()
    
    if samples is None:
        return
    
    # 统计各类标签
    from collections import Counter
    
    emotion_counter = Counter()
    scene_counter = Counter()
    conflict_counter = Counter()
    
    for sample in samples:
        emotion_counter.update(sample.get('emotion_tags', []))
        scene_counter.update(sample.get('scene_tags', []))
        conflict_counter.update(sample.get('conflict_tags', []))
    
    print(f"\n样本库总数: {len(samples)}")
    print(f"\n最常见的情绪标签:")
    for tag, count in emotion_counter.most_common(10):
        print(f"  {tag}: {count} 次")
    
    print(f"\n最常见的场景标签:")
    for tag, count in scene_counter.most_common(10):
        print(f"  {tag}: {count} 次")
    
    print(f"\n最常见的冲突标签:")
    for tag, count in conflict_counter.most_common(10):
        print(f"  {tag}: {count} 次")
    
    # 评分分布
    scores = [s.get('score', 0) for s in samples]
    avg_score = sum(scores) / len(scores) if scores else 0
    print(f"\n评分统计:")
    print(f"  平均分: {avg_score:.2f}")
    print(f"  最高分: {max(scores)}")
    print(f"  最低分: {min(scores)}")
    print(f"  90分以上: {sum(1 for s in scores if s >= 90)} 个")
    print(f"  80-89分: {sum(1 for s in scores if 80 <= s < 90)} 个")
    print(f"  70-79分: {sum(1 for s in scores if 70 <= s < 80)} 个")

if __name__ == "__main__":
    print("="*60)
    print("多标签样本检索系统 - 使用示例")
    print("="*60)
    
    # 运行所有示例
    example_1_basic_search()
    example_2_tag_filtered_search()
    example_3_high_score_search()
    example_4_complex_search()
    example_5_tag_statistics()
    
    print("\n" + "="*60)
    print("所有示例运行完毕！")
    print("="*60)


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试深度情绪分析增强功能

展示新的多维度、多层次情绪分析能力
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.emotion_analyzer import EmotionAnalyzer

def test_emotion_analysis():
    """测试深度情绪分析"""
    print("=" * 80)
    print("深度情绪分析测试")
    print("=" * 80)
    
    analyzer = EmotionAnalyzer()
    
    # 测试文本样例
    test_texts = [
        {
            "name": "紧张刺激场景",
            "text": "脚步声越来越近，心跳仿佛要冲出胸腔。他屏住呼吸，躲在黑暗的角落里，只有三分钟了，必须找到出口。"
        },
        {
            "name": "悲伤情感",
            "text": "她看着远去的背影，泪水模糊了视线。那些美好的回忆，如今只剩下痛苦和失落。"
        },
        {
            "name": "复杂情绪转折",
            "text": "虽然心中充满恐惧，但他知道这是唯一的选择。他深吸一口气，推开了那扇门。门后等待他的，是未知的命运。"
        },
        {
            "name": "期待与兴奋",
            "text": "终于要到了！他激动得手都在颤抖，多年的等待即将结束，梦想就要实现。"
        }
    ]
    
    for i, test_case in enumerate(test_texts, 1):
        print(f"\n{'='*80}")
        print(f"测试 {i}: {test_case['name']}")
        print(f"{'='*80}")
        print(f"文本: {test_case['text']}")
        print("-" * 80)
        
        # 深度情绪分析
        result = analyzer.analyze(test_case['text'])
        
        # 显示详细结果
        print("\n【基础情绪】")
        print(f"  标签: {result.label}")
        print(f"  置信度: {result.confidence:.3f}")
        print(f"  强度: {result.intensity:.3f}")
        
        if result.emotion_dimensions:
            print("\n【多维度情绪】")
            emotion_names = {
                'joy': '喜悦', 'sadness': '悲伤', 'anger': '愤怒', 
                'fear': '恐惧', 'surprise': '惊讶', 'disgust': '厌恶',
                'anticipation': '期待', 'tension': '紧张', 'excitement': '激动'
            }
            sorted_emotions = sorted(
                result.emotion_dimensions.items(), 
                key=lambda x: x[1], 
                reverse=True
            )
            for emotion, score in sorted_emotions[:5]:
                if score > 0.05:
                    bar = "█" * int(score * 50)
                    print(f"  {emotion_names.get(emotion, emotion):8s}: {score:.3f} {bar}")
        
        print("\n【情绪深度】")
        print(f"  表层情绪: {result.surface_emotion}")
        print(f"  深层情绪: {result.deep_emotion}")
        print(f"  情绪深度: {result.emotion_depth:.3f}")
        
        if result.emotion_transition:
            print("\n【情绪转折】")
            transition_names = {
                'rising': '上升', 'falling': '下降', 
                'mixed': '混合', 'stable': '稳定'
            }
            print(f"  转折类型: {transition_names.get(result.emotion_transition, result.emotion_transition)}")
            print(f"  转折强度: {result.transition_strength:.3f}")
        
        print("\n【情绪密度与复杂度】")
        print(f"  情绪词汇密度: {result.emotion_word_density:.4f}")
        print(f"  情绪句子密度: {result.emotion_sentence_density:.3f}")
        print(f"  情绪复杂度: {result.emotion_complexity:.3f}")
        
        # 显示摘要
        summary = analyzer.summarize(test_case['text'])
        print(f"\n【情绪摘要】")
        print(f"  {summary}")
        
        # 显示特征向量
        features = analyzer.extract_features(test_case['text'])
        emotion_features = {k: v for k, v in features.items() if k.startswith('emotion_')}
        print(f"\n【情绪特征数量】: {len(emotion_features)} 个特征")
        print(f"  主要特征: {', '.join(list(emotion_features.keys())[:5])}...")
    
    print(f"\n{'='*80}")
    print("测试完成！")
    print("=" * 80)

if __name__ == "__main__":
    test_emotion_analysis()


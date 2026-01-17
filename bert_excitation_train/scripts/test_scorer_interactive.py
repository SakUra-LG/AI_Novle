#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互式评分测试工具
在终端输入文字，让评分模型进行评分
"""

import sys
import os
import json
from datetime import datetime
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.paragraph_scorer import ParagraphScorer
from scripts.optimized_rule_scorer import OptimizedRuleScorer

def save_manual_annotation(text, manual_score, rule_score, ml_score):
    """保存人工标注数据"""
    annotation_file = "data/training/manual_annotations.json"
    
    # 创建标注数据
    annotation = {
        'text': text,
        'manual_score': manual_score,
        'rule_score': rule_score,
        'ml_score': ml_score,
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'category': 'interactive_test'
    }
    
    # 读取现有数据
    annotations = []
    if os.path.exists(annotation_file):
        with open(annotation_file, 'r', encoding='utf-8') as f:
            annotations = json.load(f)
    
    # 添加新标注
    annotations.append(annotation)
    
    # 保存数据
    os.makedirs(os.path.dirname(annotation_file), exist_ok=True)
    with open(annotation_file, 'w', encoding='utf-8') as f:
        json.dump(annotations, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 人工标注已保存到: {annotation_file}")
    return len(annotations)

def retrain_ml_model(ml_scorer):
    """重新训练ML模型"""
    print("\n🔄 正在重新训练ML评分模型...")
    
    # 加载原始训练数据
    original_file = "data/training/paragraph_annotations.json"
    manual_file = "data/training/manual_annotations.json"
    
    annotations = []
    
    # 加载原始数据
    if os.path.exists(original_file):
        with open(original_file, 'r', encoding='utf-8') as f:
            original_data = json.load(f)
            annotations.extend(original_data)
    
    # 加载人工标注数据
    if os.path.exists(manual_file):
        with open(manual_file, 'r', encoding='utf-8') as f:
            manual_data = json.load(f)
            
            # 转换格式
            for item in manual_data:
                # 提取特征
                features = ml_scorer.extract_features(item['text'])
                
                # 创建标注数据
                annotation = {
                    'text': item['text'],
                    'user_score': item['manual_score'],
                    'features': features,
                    'category': item.get('category', 'interactive_test'),
                    'timestamp': item['timestamp']
                }
                annotations.append(annotation)
    
    if len(annotations) < 3:
        print("❌ 训练数据不足，无法重新训练")
        return False
    
    # 重新训练模型
    if ml_scorer.train_model(annotations):
        print(f"✅ ML模型重新训练完成！使用了 {len(annotations)} 个样本")
        return True
    else:
        print("❌ ML模型重新训练失败")
        return False

def test_scorer_interactive():
    """交互式评分测试"""
    
    print("=" * 60)
    print("🎯 评分模型测试工具 (增强版)")
    print("=" * 60)
    print("支持功能：")
    print("1. 规则评分器 (基于关键词和模式匹配)")
    print("2. 机器学习评分器 (基于人工标注训练)")
    print("3. 综合评分 (两种方式的平均值)")
    print("4. 人工调整评分并训练ML模型")
    print("=" * 60)
    
    # 初始化评分器
    rule_scorer = OptimizedRuleScorer()
    ml_scorer = ParagraphScorer()
    
    # 尝试加载训练好的ML模型
    annotations_file = "data/training/paragraph_annotations.json"
    if os.path.exists(annotations_file):
        annotations = ml_scorer.load_annotations(annotations_file)
        if ml_scorer.train_model(annotations):
            print("✅ 成功加载机器学习评分模型")
        else:
            print("⚠️ 机器学习模型加载失败，将只使用规则评分")
            ml_scorer = None
    else:
        print("⚠️ 未找到训练数据，将只使用规则评分")
        ml_scorer = None
    
    print("\n" + "=" * 60)
    print("开始测试！输入 'quit' 或 'exit' 退出")
    print("=" * 60)
    
    # 统计信息
    total_tests = 0
    manual_annotations = 0
    
    while True:
        print("\n" + "-" * 40)
        text = input("请输入要评分的文字: ").strip()
        
        if text.lower() in ['quit', 'exit', '退出']:
            print("👋 测试结束！")
            
            # 显示统计信息
            print(f"\n📊 本次测试统计:")
            print(f"   总测试次数: {total_tests}")
            print(f"   人工标注次数: {manual_annotations}")
            
            # 检查是否有新的人工标注
            manual_file = "data/training/manual_annotations.json"
            if os.path.exists(manual_file):
                with open(manual_file, 'r', encoding='utf-8') as f:
                    manual_data = json.load(f)
                    if len(manual_data) > 0:
                        print(f"   累计人工标注: {len(manual_data)} 个")
                        
                        # 询问是否批量训练
                        batch_retrain = input(f"\n是否使用所有人工标注重新训练ML模型？(y/n): ").strip().lower()
                        if batch_retrain in ['y', 'yes', '是']:
                            if ml_scorer and ml_scorer.model is not None:
                                if retrain_ml_model(ml_scorer):
                                    print("🎉 批量训练完成！ML模型已更新")
                                else:
                                    print("❌ 批量训练失败")
                            else:
                                print("❌ ML模型不可用，无法训练")
                        else:
                            print("💡 人工标注已保存，可稍后手动训练")
            
            print("👋 再见！")
            break
        
        if not text:
            print("❌ 请输入有效的文字")
            continue
        
        total_tests += 1
        print(f"\n📝 输入文字: {text}")
        print("-" * 40)
        
        # 规则评分
        rule_score = rule_scorer.calculate_score(text)
        print(f"📊 规则评分: {rule_score:.1f}")
        
        # 评分解释
        if rule_score <= 30:
            print("   评级: 平淡无奇")
        elif rule_score <= 50:
            print("   评级: 轻微紧张")
        elif rule_score <= 70:
            print("   评级: 明显紧张")
        elif rule_score <= 85:
            print("   评级: 高度紧张")
        else:
            print("   评级: 极度紧张")
        
        # 机器学习评分
        ml_score = None
        if ml_scorer and ml_scorer.model is not None:
            ml_score = ml_scorer.predict_score(text)
            print(f"🤖 ML评分: {ml_score:.1f}")
            
            # 综合评分
            combined_score = (rule_score + ml_score) / 2
            print(f"🎯 综合评分: {combined_score:.1f}")
            
            # 差异分析
            diff = abs(rule_score - ml_score)
            if diff > 20:
                print(f"⚠️ 评分差异较大: {diff:.1f}")
                if ml_score > rule_score:
                    print("   ML模型认为更紧张")
                else:
                    print("   规则模型认为更紧张")
            else:
                print("✅ 两种评分基本一致")
        else:
            print("🤖 ML评分: 不可用")
            print("🎯 综合评分: 不可用")
        
        # 人工调整评分功能
        if ml_scorer and ml_scorer.model is not None:
            print("\n" + "-" * 40)
            adjust_choice = input("是否要人工调整评分以训练ML模型？(y/n): ").strip().lower()
            
            if adjust_choice in ['y', 'yes', '是']:
                print("\n📝 请为这段文字提供更准确的评分:")
                print("评分标准：")
                print("  90-100: 极度紧张，情节高潮")
                print("  80-89:  高度紧张，重要情节") 
                print("  70-79:  明显紧张，有冲突")
                print("  60-69:  轻微紧张，有悬念")
                print("  50-59:  平淡但有内容")
                print("  40-49:  比较平淡")
                print("  30-39:  很平淡")
                print("  20-29:  非常平淡")
                print("  10-19:  极其平淡")
                print("  1-9:    几乎无内容")
                
                while True:
                    try:
                        manual_score = float(input(f"请输入人工评分 (1-100, 当前ML评分: {ml_score:.1f}): ").strip())
                        if 1 <= manual_score <= 100:
                            # 保存人工标注
                            total_annotations = save_manual_annotation(text, manual_score, rule_score, ml_score)
                            manual_annotations += 1
                            
                            print(f"\n📊 评分对比:")
                            print(f"   规则评分: {rule_score:.1f}")
                            print(f"   ML评分: {ml_score:.1f}")
                            print(f"   人工评分: {manual_score:.1f}")
                            
                            # 询问是否重新训练
                            retrain_choice = input(f"\n是否立即重新训练ML模型？(当前有{total_annotations}个标注样本) (y/n): ").strip().lower()
                            if retrain_choice in ['y', 'yes', '是']:
                                if retrain_ml_model(ml_scorer):
                                    print("🎉 ML模型已更新！下次评分将使用新的模型")
                                else:
                                    print("❌ 模型训练失败，请检查数据")
                            else:
                                print("💡 人工标注已保存，可以稍后批量训练模型")
                            break
                        else:
                            print("❌ 评分必须在1-100之间")
                    except ValueError:
                        print("❌ 请输入有效的数字")
            elif adjust_choice in ['n', 'no', '否']:
                print("✅ 跳过人工调整")
            else:
                print("❌ 无效输入，跳过人工调整")
        
        # 特征分析
        print("\n🔍 特征分析:")
        print(f"   文本长度: {len(text)} 字符")
        
        # 简单的关键词统计
        tension_keywords = ['紧张', '心跳', '加快', '跟踪', '可疑', '警觉', '交锋', '四目相对', '空气凝固', '包围', '逃脱', '暴露', '逼近']
        action_keywords = ['跑', '逃', '追', '躲', '藏', '冲', '撞', '摔', '倒', '跌', '闪身', '跌跌撞撞']
        danger_keywords = ['火', '烟', '血', '枪', '刀', '毒', '炸', '爆', '死', '伤', '恐慌', '苍白']
        
        tension_count = sum(1 for keyword in tension_keywords if keyword in text)
        action_count = sum(1 for keyword in action_keywords if keyword in text)
        danger_count = sum(1 for keyword in danger_keywords if keyword in text)
        
        print(f"   紧张度关键词: {tension_count} 个")
        print(f"   动作关键词: {action_count} 个")
        print(f"   危险关键词: {danger_count} 个")
        dialogue_count = text.count('"') + text.count('"') + text.count(''') + text.count(''')
        print(f"   对话内容: {dialogue_count} 处")

if __name__ == "__main__":
    test_scorer_interactive()

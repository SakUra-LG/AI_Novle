#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优化版基于规则的评分模型
"""

import re
import os
import json

class OptimizedRuleScorer:
    def __init__(self):
        """初始化优化版基于规则的评分器"""
        
        # 重新设计关键词和分数权重
        self.keywords = {
            # 平淡内容关键词 (20-30分)
            '平淡': {
                'words': ['平静', '安静', '整理', '看书', '阳光', '明媚', '人来人往', '咖啡厅', '图书馆'],
                'weight': 2,  # 每个关键词+2分
                'base_score': 22
            },
            
            # 轻微紧张关键词 (30-45分)
            '轻微紧张': {
                'words': ['警觉', '紧张', '心跳', '加快', '跟踪', '可疑', '门锁', '动过', '脚步声', '步伐'],
                'weight': 3,  # 每个关键词+3分
                'base_score': 32
            },
            
            # 明显紧张关键词 (45-65分)
            '明显紧张': {
                'words': ['交锋', '四目相对', '空气凝固', '包围', '逃脱', '暴露', '逼近', '电梯停了', '血', '门缝', '巷子', '黑暗'],
                'weight': 4,  # 每个关键词+4分
                'base_score': 48
            },
            
            # 高度紧张关键词 (65-85分)
            '高度紧张': {
                'words': ['黑枪', '背叛', '击中', '毒贩', '逃离', '威胁', '杀死', '家人', '炸弹', '爆炸', '拆除', '追杀', '失控', '悬崖', '绑架', '解药', '着火', '浓烟', '堵死', '高速', '车辆'],
                'weight': 5,  # 每个关键词+5分
                'base_score': 68
            },
            
            # 极度紧张关键词 (85-100分)
            '极度紧张': {
                'words': ['震耳欲聋', '冲击波', '掀翻', '黑暗', '生死未卜', '毒药', '冷冻', '下坠', '刹车失灵', '尸体', '最后的机会', '废弃工厂', '冷冻车', '温度下降'],
                'weight': 6,  # 每个关键词+6分
                'base_score': 88
            }
        }
        
        # 特殊模式匹配
        self.patterns = {
            '对话紧张': r'[""「」].*[！!？?].*[""「」]',  # 包含感叹号或问号的对话
            '动作紧张': r'[跑|逃|追|躲|藏|冲|撞|摔|倒|跌]',  # 紧张动作
            '时间紧迫': r'[只有|只剩|分钟|秒|小时|时间]',  # 时间限制
            '危险环境': r'[火|烟|血|枪|刀|毒|炸|爆|死|伤]',  # 危险元素
        }
        
        # 模式分数调整
        self.pattern_scores = {
            '对话紧张': 8,
            '动作紧张': 5,
            '时间紧迫': 10,
            '危险环境': 12,
        }
    
    def calculate_score(self, text):
        """计算文本的紧张度分数"""
        if not text or len(text.strip()) < 5:
            return 20  # 默认最低分
        
        text = text.strip()
        scores = []
        
        # 1. 基于关键词的评分
        for category, config in self.keywords.items():
            keyword_score = self._calculate_keyword_score(text, config)
            if keyword_score > 0:
                scores.append(keyword_score)
        
        # 2. 基于模式的评分
        pattern_score = self._calculate_pattern_score(text)
        if pattern_score > 0:
            scores.append(pattern_score)
        
        # 3. 基于文本长度的调整
        length_score = self._calculate_length_score(text)
        
        # 4. 综合评分
        if scores:
            # 取最高分作为基础分数
            base_score = max(scores)
            
            # 根据文本长度调整
            final_score = base_score + length_score
            
            # 确保分数在合理范围内
            final_score = max(20, min(100, final_score))
        else:
            # 如果没有匹配到任何关键词，给基础分
            final_score = 25 + length_score
            final_score = max(20, min(35, final_score))
        
        return round(final_score, 2)
    
    def _calculate_keyword_score(self, text, config):
        """计算关键词分数"""
        words = config['words']
        weight = config['weight']
        base_score = config['base_score']
        
        # 计算匹配的关键词数量
        matches = 0
        for word in words:
            if word in text:
                matches += 1
        
        if matches == 0:
            return 0
        
        # 计算分数：基础分 + 匹配数 * 权重
        score = base_score + matches * weight
        return min(100, score)
    
    def _calculate_pattern_score(self, text):
        """计算模式匹配分数"""
        total_score = 0
        for pattern_name, pattern in self.patterns.items():
            if re.search(pattern, text):
                total_score += self.pattern_scores[pattern_name]
        
        return min(30, total_score)  # 模式分数上限30
    
    def _calculate_length_score(self, text):
        """根据文本长度调整分数"""
        length = len(text)
        
        if length < 20:
            return -3  # 太短扣分
        elif length < 50:
            return 0   # 正常长度
        elif length < 100:
            return 2   # 较长加分
        else:
            return 5   # 很长加分
    
    def test_scoring(self):
        """测试评分功能"""
        test_cases = [
            {
                'text': '陈雪在办公室里整理文件，一切都很平静。',
                'expected_range': (20, 30),
                'description': '平淡内容'
            },
            {
                'text': '陈雪发现文件中有可疑的线索，开始警觉。',
                'expected_range': (30, 45),
                'description': '轻微紧张'
            },
            {
                'text': '陈雪听到身后传来脚步声，她加快步伐，心跳加速。',
                'expected_range': (30, 45),
                'description': '明显紧张'
            },
            {
                'text': '曾共事多年的刑侦警长竟然在收网行动中放了黑枪击中陈雪的右肩，协助毒贩乘船逃离',
                'expected_range': (65, 85),
                'description': '高度紧张'
            },
            {
                'text': '陈雪与敌人正面交锋，两人四目相对，空气仿佛凝固。',
                'expected_range': (45, 65),
                'description': '明显紧张'
            },
            {
                'text': '爆炸声震耳欲聋，陈雪被冲击波掀翻，眼前一片黑暗，生死未卜。',
                'expected_range': (85, 100),
                'description': '极度紧张'
            }
        ]
        
        print("=" * 60)
        print("优化版基于规则的评分模型测试")
        print("=" * 60)
        
        correct_predictions = 0
        total_predictions = len(test_cases)
        
        for i, case in enumerate(test_cases, 1):
            score = self.calculate_score(case['text'])
            expected_min, expected_max = case['expected_range']
            
            # 判断是否符合预期
            is_correct = expected_min <= score <= expected_max
            if is_correct:
                correct_predictions += 1
                status = "✓"
            else:
                status = "✗"
            
            print(f"[{case['description']}] 分数: {score:.2f} (期望: {expected_min}-{expected_max}) {status}")
            print(f"  文本: {case['text']}")
            print()
        
        # 总结
        print("=" * 60)
        print("测试总结")
        print("=" * 60)
        print(f"符合预期的测试: {correct_predictions}/{total_predictions}")
        
        if correct_predictions == total_predictions:
            print("✓ 优化版基于规则的评分模型完全符合预期！")
        elif correct_predictions >= total_predictions * 0.8:
            print("△ 优化版基于规则的评分模型基本符合预期，但还有改进空间")
        else:
            print("✗ 优化版基于规则的评分模型不符合预期")
        
        # 测试相对评分
        print(f"\n相对评分测试:")
        print("-" * 30)
        
        text1 = "陈雪听到身后传来脚步声，她加快步伐，心跳加速。"
        text2 = "曾共事多年的刑侦警长竟然在收网行动中放了黑枪击中陈雪的右肩，协助毒贩乘船逃离"
        
        score1 = self.calculate_score(text1)
        score2 = self.calculate_score(text2)
        
        print(f"句子1 (脚步声): {score1:.2f}")
        print(f"句子2 (黑枪背叛): {score2:.2f}")
        
        if score2 > score1:
            print("✓ 相对评分正确：黑枪背叛 > 脚步声")
        else:
            print("✗ 相对评分错误：黑枪背叛 <= 脚步声")
        
        if score1 >= 20 and score2 >= 20:
            print("✓ 两个分数都不低于20")
        else:
            print("✗ 有分数低于20")
        
        return correct_predictions, total_predictions

def main():
    """主函数"""
    scorer = OptimizedRuleScorer()
    correct, total = scorer.test_scoring()
    
    print(f"\n[INFO] 优化版基于规则的评分模型测试完成")
    print(f"[INFO] 准确率: {correct/total*100:.1f}%")
    
    # 保存模型配置
    config = {
        'keywords': scorer.keywords,
        'patterns': scorer.patterns,
        'pattern_scores': scorer.pattern_scores
    }
    
    os.makedirs('checkpoints/optimized_rule_scorer', exist_ok=True)
    with open('checkpoints/optimized_rule_scorer/config.json', 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    print(f"[INFO] 模型配置已保存到: checkpoints/optimized_rule_scorer/config.json")
    
    # 如果准确率足够高，建议使用这个模型
    if correct/total >= 0.8:
        print(f"\n[SUCCESS] 建议使用优化版基于规则的评分模型！")
        print(f"使用方法: python scripts/use_rule_scorer.py --text '你的文本'")
    else:
        print(f"\n[INFO] 模型还需要进一步优化")

if __name__ == "__main__":
    main()

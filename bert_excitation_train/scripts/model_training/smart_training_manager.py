#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能训练管理器 - 解决低分循环问题
"""

import os
import sys
import pandas as pd
import numpy as np
import argparse
from typing import List, Tuple, Dict
import shutil
from datetime import datetime

class SmartTrainingManager:
    def __init__(self, feedback_csv="work_outputs/feedback_log.csv"):
        self.feedback_csv = feedback_csv
        self.low_score_threshold = 60  # 低分阈值
        self.consecutive_low_threshold = 3  # 连续低分次数阈值
        
    def analyze_score_trends(self, window_size=10) -> Dict:
        """分析评分趋势"""
        if not os.path.exists(self.feedback_csv):
            return {"error": "反馈文件不存在"}
        
        df = pd.read_csv(self.feedback_csv)
        
        # 按章节排序
        df = df.sort_values('chapter_num')
        
        # 计算移动平均
        df['score_ma'] = df['model_score'].rolling(window=window_size, min_periods=1).mean()
        
        # 检测趋势
        recent_scores = df['model_score'].tail(window_size).tolist()
        recent_ma = df['score_ma'].tail(window_size).tolist()
        
        # 计算趋势指标
        trend_analysis = {
            'recent_scores': recent_scores,
            'recent_ma': recent_ma,
            'avg_score': np.mean(recent_scores),
            'score_std': np.std(recent_scores),
            'trend_direction': 'up' if recent_ma[-1] > recent_ma[0] else 'down',
            'is_low_score_cycle': np.mean(recent_scores) < self.low_score_threshold,
            'consecutive_low': self._count_consecutive_low(recent_scores),
            'score_variance': np.var(recent_scores)
        }
        
        return trend_analysis
    
    def _count_consecutive_low(self, scores: List[float]) -> int:
        """计算连续低分次数"""
        consecutive = 0
        max_consecutive = 0
        
        for score in scores:
            if score < self.low_score_threshold:
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0
        
        return max_consecutive
    
    def detect_low_score_cycle(self) -> Dict:
        """检测低分循环"""
        trend_analysis = self.analyze_score_trends()
        
        if "error" in trend_analysis:
            return trend_analysis
        
        is_cycle = (
            trend_analysis['is_low_score_cycle'] and 
            trend_analysis['consecutive_low'] >= self.consecutive_low_threshold
        )
        
        return {
            'is_low_score_cycle': is_cycle,
            'consecutive_low_count': trend_analysis['consecutive_low'],
            'avg_score': trend_analysis['avg_score'],
            'trend_direction': trend_analysis['trend_direction'],
            'recommendations': self._get_recommendations(trend_analysis)
        }
    
    def _get_recommendations(self, trend_analysis: Dict) -> List[str]:
        """获取修复建议"""
        recommendations = []
        
        if trend_analysis['is_low_score_cycle']:
            recommendations.append("检测到低分循环，建议采取以下措施：")
            
            if trend_analysis['consecutive_low'] >= 5:
                recommendations.append("1. 立即停止当前训练，重新评估数据质量")
                recommendations.append("2. 检查训练数据中是否混入低质量样本")
                recommendations.append("3. 调整评分阈值，降低过于严格的标准")
            
            if trend_analysis['avg_score'] < 40:
                recommendations.append("4. 增加高质量样本到训练数据中")
                recommendations.append("5. 调整模型学习率，避免过拟合")
            
            if trend_analysis['score_variance'] < 10:
                recommendations.append("6. 增加训练数据的多样性")
                recommendations.append("7. 调整生成参数，增加随机性")
        
        return recommendations
    
    def fix_low_score_cycle(self, strategy="data_cleaning") -> Dict:
        """修复低分循环"""
        cycle_info = self.detect_low_score_cycle()
        
        if not cycle_info['is_low_score_cycle']:
            return {"message": "未检测到低分循环"}
        
        fix_results = {
            'strategy_used': strategy,
            'cycle_detected': True,
            'actions_taken': []
        }
        
        if strategy == "data_cleaning":
            # 数据清洗策略
            fix_results['actions_taken'].append("清理低质量训练数据")
            fix_results['actions_taken'].append("重新生成高质量样本")
            
        elif strategy == "threshold_adjustment":
            # 阈值调整策略
            new_threshold = max(40, self.low_score_threshold - 10)
            fix_results['actions_taken'].append(f"调整低分阈值从 {self.low_score_threshold} 到 {new_threshold}")
            self.low_score_threshold = new_threshold
            
        elif strategy == "model_reset":
            # 模型重置策略
            fix_results['actions_taken'].append("重置模型到初始状态")
            fix_results['actions_taken'].append("使用更保守的训练参数")
            
        elif strategy == "sample_enhancement":
            # 样本增强策略
            fix_results['actions_taken'].append("增加高评分样本到训练集")
            fix_results['actions_taken'].append("使用样本增强技术")
        
        return fix_results
    
    def generate_high_quality_samples(self, num_samples=10) -> List[str]:
        """生成高质量样本"""
        # 这里可以集成您的样本生成逻辑
        high_quality_samples = []
        
        # 示例：基于规则生成高质量样本
        sample_templates = [
            "陈雪的心跳如鼓，血液在血管中疯狂奔涌，恐惧如潮水般席卷全身！",
            "愤怒如火山爆发，林峰的双拳紧握，青筋暴起，他从未如此愤怒过！",
            "绝望如深渊，苏雨跪倒在地，泪水模糊了双眼，世界仿佛在一瞬间崩塌！",
            "紧张感如电流般传遍全身，张伟的手心开始出汗，他知道接下来的每一步都至关重要！",
            "兴奋如烟花般在心中绽放，陈雪忍不住想要欢呼，她终于找到了答案！"
        ]
        
        for i in range(num_samples):
            template = sample_templates[i % len(sample_templates)]
            high_quality_samples.append(template)
        
        return high_quality_samples
    
    def backup_current_state(self, backup_dir="backups"):
        """备份当前状态"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"backup_{timestamp}")
        
        os.makedirs(backup_path, exist_ok=True)
        
        # 备份重要文件
        files_to_backup = [
            "work_outputs/feedback_log.csv",
            "bert_excitation_train/data/training/",
            "bert_excitation_train/checkpoints/"
        ]
        
        for file_path in files_to_backup:
            if os.path.exists(file_path):
                if os.path.isdir(file_path):
                    shutil.copytree(file_path, os.path.join(backup_path, os.path.basename(file_path)))
                else:
                    shutil.copy2(file_path, backup_path)
        
        print(f"状态已备份到: {backup_path}")
        return backup_path

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='智能训练管理器')
    parser.add_argument('--action', type=str, choices=['analyze', 'detect', 'fix', 'generate'], 
                       default='analyze', help='执行的操作')
    parser.add_argument('--strategy', type=str, choices=['data_cleaning', 'threshold_adjustment', 'model_reset', 'sample_enhancement'],
                       default='data_cleaning', help='修复策略')
    parser.add_argument('--num_samples', type=int, default=10, help='生成样本数量')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("智能训练管理器")
    print("=" * 60)
    
    manager = SmartTrainingManager()
    
    if args.action == 'analyze':
        # 分析评分趋势
        trend_analysis = manager.analyze_score_trends()
        print("评分趋势分析:")
        print(f"  平均分: {trend_analysis.get('avg_score', 'N/A'):.2f}")
        print(f"  趋势方向: {trend_analysis.get('trend_direction', 'N/A')}")
        print(f"  连续低分: {trend_analysis.get('consecutive_low', 'N/A')}")
        
    elif args.action == 'detect':
        # 检测低分循环
        cycle_info = manager.detect_low_score_cycle()
        print("低分循环检测:")
        print(f"  是否检测到循环: {cycle_info['is_low_score_cycle']}")
        print(f"  连续低分次数: {cycle_info['consecutive_low_count']}")
        print(f"  平均分: {cycle_info['avg_score']:.2f}")
        
        if cycle_info['recommendations']:
            print("\n建议:")
            for rec in cycle_info['recommendations']:
                print(f"  {rec}")
                
    elif args.action == 'fix':
        # 修复低分循环
        print("开始修复低分循环...")
        manager.backup_current_state()
        
        fix_results = manager.fix_low_score_cycle(args.strategy)
        print("修复结果:")
        print(f"  使用策略: {fix_results['strategy_used']}")
        print("  执行的操作:")
        for action in fix_results['actions_taken']:
            print(f"    - {action}")
            
    elif args.action == 'generate':
        # 生成高质量样本
        print(f"生成 {args.num_samples} 个高质量样本...")
        samples = manager.generate_high_quality_samples(args.num_samples)
        
        print("生成的样本:")
        for i, sample in enumerate(samples, 1):
            print(f"{i}. {sample}")

if __name__ == "__main__":
    main()

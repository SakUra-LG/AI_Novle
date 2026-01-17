#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反馈循环系统
将评分结果反馈给生成模型
"""

import os
import json
import pandas as pd
from datetime import datetime
from paragraph_scorer import ParagraphScorer
from optimized_rule_scorer import OptimizedRuleScorer

class FeedbackLoopSystem:
    def __init__(self):
        self.scorer = OptimizedRuleScorer()
        self.paragraph_scorer = ParagraphScorer()
        self.feedback_file = 'outputs/feedback_log.csv'
        
    def analyze_score_trends(self):
        """分析评分趋势"""
        if not os.path.exists(self.feedback_file):
            print("反馈日志不存在")
            return None
        
        df = pd.read_csv(self.feedback_file)
        
        if len(df) == 0:
            print("没有反馈数据")
            return None
        
        # 分析最近10次的评分趋势
        recent_scores = df['model_score'].tail(10).tolist()
        avg_score = sum(recent_scores) / len(recent_scores)
        
        # 分析低分原因
        low_scores = df[df['model_score'] < 50]
        if len(low_scores) > 0:
            print(f"发现 {len(low_scores)} 个低分样本")
            print("低分原因分析:")
            for _, row in low_scores.iterrows():
                print(f"  - 章节 {row['chapter_num']}: 评分 {row['model_score']}")
        
        return {
            'avg_score': avg_score,
            'trend': 'up' if recent_scores[-1] > recent_scores[0] else 'down',
            'low_score_count': len(low_scores)
        }
    
    def generate_improvement_suggestions(self, analysis):
        """生成改进建议"""
        suggestions = []
        
        if analysis['avg_score'] < 60:
            suggestions.append("平均评分较低，建议增加更多高评分样本到RAG库")
        
        if analysis['trend'] == 'down':
            suggestions.append("评分呈下降趋势，建议调整生成策略")
        
        if analysis['low_score_count'] > 5:
            suggestions.append("低分样本较多，建议优化生成模型")
        
        return suggestions
    
    def update_rag_samples(self, min_score=70):
        """根据评分更新RAG样本库"""
        if not os.path.exists(self.feedback_file):
            return
        
        df = pd.read_csv(self.feedback_file)
        high_score_samples = df[df['model_score'] >= min_score]
        
        if len(high_score_samples) == 0:
            print("没有高评分样本可添加到RAG库")
            return
        
        print(f"找到 {len(high_score_samples)} 个高评分样本")
        
        # 读取现有RAG样本
        rag_file = 'data/universal_samples.txt'
        if os.path.exists(rag_file):
            with open(rag_file, 'r', encoding='utf-8') as f:
                existing_content = f.read()
        else:
            existing_content = ""
        
        # 添加高评分样本
        new_samples = []
        for _, row in high_score_samples.iterrows():
            # 读取生成的内容
            content_file = f"data/generated/暗河噬城/{row['candidate_file']}"
            if os.path.exists(content_file):
                with open(content_file, 'r', encoding='utf-8') as f:
                    content = f.read()[:200] + "..."  # 只取前200字符
            else:
                content = "内容文件不存在"
            
            sample = f"""
## 高评分生成样本
**标签**: 生成, 高评分
**评分**: {row['model_score']}
**内容**: {content}
**添加时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            new_samples.append(sample)
        
        # 保存更新后的样本
        updated_content = existing_content + '\n'.join(new_samples)
        with open(rag_file, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        
        print(f"已添加 {len(new_samples)} 个高评分样本到RAG库")
    
    def generate_enhanced_prompt(self, base_prompt, analysis):
        """根据评分分析生成增强提示"""
        enhanced_prompt = base_prompt
        
        if analysis['avg_score'] < 60:
            enhanced_prompt += "\n\n注意：请确保内容具有足够的张力和冲突，避免平淡的描述。"
        
        if analysis['low_score_count'] > 5:
            enhanced_prompt += "\n\n请参考以下高评分样本的写作风格："
            # 这里可以添加高评分样本的引用
        
        return enhanced_prompt
    
    def run_feedback_loop(self):
        """运行完整的反馈循环"""
        print("反馈循环系统")
        print("=" * 40)
        
        # 1. 分析评分趋势
        analysis = self.analyze_score_trends()
        if not analysis:
            print("无法进行分析")
            return
        
        print(f"平均评分: {analysis['avg_score']:.2f}")
        print(f"趋势: {analysis['trend']}")
        print(f"低分样本数: {analysis['low_score_count']}")
        
        # 2. 生成改进建议
        suggestions = self.generate_improvement_suggestions(analysis)
        print("\n改进建议:")
        for i, suggestion in enumerate(suggestions, 1):
            print(f"  {i}. {suggestion}")
        
        # 3. 更新RAG样本库
        print("\n更新RAG样本库...")
        self.update_rag_samples()
        
        # 4. 生成增强提示示例
        base_prompt = "请生成一个悬疑推理场景"
        enhanced_prompt = self.generate_enhanced_prompt(base_prompt, analysis)
        print(f"\n增强提示示例:")
        print(f"原始: {base_prompt}")
        print(f"增强: {enhanced_prompt}")
        
        return analysis, suggestions

def main():
    """主函数"""
    system = FeedbackLoopSystem()
    system.run_feedback_loop()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
样本收集工具
用于从短剧中收集高评分句子并添加到RAG系统
"""

import os
import sys
import json
from datetime import datetime
from bert_excitation_train.scripts.emotion_scoring.optimized_rule_scorer import OptimizedRuleScorer

class SampleCollector:
    def __init__(self):
        self.scorer = OptimizedRuleScorer()
        self.samples_file = 'bert_excitation_train/data/universal_samples.txt'
        
    def read_existing_samples(self):
        """读取现有样本"""
        if os.path.exists(self.samples_file):
            with open(self.samples_file, 'r', encoding='utf-8') as f:
                return f.read()
        return ""
    
    def save_samples(self, content):
        """保存样本"""
        os.makedirs(os.path.dirname(self.samples_file), exist_ok=True)
        with open(self.samples_file, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"样本已保存到: {self.samples_file}")
    
    def score_text(self, text):
        """评分文本"""
        return self.scorer.calculate_score(text)
    
    def suggest_category(self, text):
        """根据内容建议分类"""
        categories = {
            '武侠对决': ['剑', '刀', '拳', '掌', '内力', '招式', '比武', '决斗', '江湖'],
            '情感互动': ['心', '情', '爱', '恨', '泪', '笑', '拥抱', '亲吻', '思念'],
            '悬疑推理': ['谜', '案', '线索', '证据', '推理', '真相', '秘密', '调查'],
            '动作场面': ['跑', '追', '逃', '躲', '冲', '撞', '摔', '打', '战'],
            '心理描写': ['想', '思', '感', '觉', '心', '脑', '意识', '回忆', '梦'],
            '环境描写': ['风', '雨', '雪', '山', '海', '林', '城', '街', '屋'],
            '对话场景': ['说', '道', '问', '答', '喊', '叫', '笑', '哭', '叹']
        }
        
        scores = {}
        for category, keywords in categories.items():
            score = sum(1 for keyword in keywords if keyword in text)
            if score > 0:
                scores[category] = score
        
        if scores:
            return max(scores, key=scores.get)
        return '其他'
    
    def add_sample(self, text, category=None, tags=None):
        """添加样本"""
        if not text.strip():
            print("文本不能为空")
            return False
        
        # 评分
        score = self.score_text(text)
        print(f"文本评分: {score:.2f}")
        
        if score < 30:
            print("⚠️  评分较低，建议选择更有张力的内容")
            confirm = input("是否仍要添加？(y/n): ").strip().lower()
            if confirm not in ['y', 'yes']:
                return False
        
        # 建议分类
        if not category:
            suggested = self.suggest_category(text)
            print(f"建议分类: {suggested}")
            category = input(f"请输入分类 (直接回车使用建议): ").strip() or suggested
        
        # 建议标签
        if not tags:
            tags_input = input("请输入标签 (用逗号分隔，直接回车跳过): ").strip()
            tags = [tag.strip() for tag in tags_input.split(',')] if tags_input else []
        
        # 读取现有样本
        existing = self.read_existing_samples()
        
        # 添加新样本
        new_sample = f"\n## {category}\n"
        new_sample += f"**评分**: {score:.2f}\n"
        new_sample += f"**内容**: {text}\n"
        
        # 保存
        updated_content = existing + new_sample
        self.save_samples(updated_content)
        
        print(f"✅ 样本已添加到分类: {category}")
        return True
    
    def batch_add_samples(self):
        """批量添加样本"""
        print("批量添加样本模式")
        print("输入多行文本，每行一个样本，输入空行结束")
        print("=" * 60)
        
        samples = []
        while True:
            text = input("请输入样本文本 (空行结束): ").strip()
            if not text:
                break
            samples.append(text)
        
        if not samples:
            print("没有输入任何样本")
            return
        
        print(f"\n准备添加 {len(samples)} 个样本")
        
        for i, text in enumerate(samples, 1):
            print(f"\n处理样本 {i}/{len(samples)}:")
            print(f"内容: {text[:100]}...")
            
            score = self.score_text(text)
            print(f"评分: {score:.2f}")
            
            if score < 30:
                print("⚠️  评分较低")
                add = input("是否添加？(y/n): ").strip().lower()
                if add not in ['y', 'yes']:
                    continue
            
            category = self.suggest_category(text)
            print(f"建议分类: {category}")
            
            self.add_sample(text, category)
    
    def interactive_mode(self):
        """交互模式"""
        print("样本收集工具 - 交互模式")
        print("=" * 60)
        
        while True:
            print("\n请选择操作:")
            print("1. 添加单个样本")
            print("2. 批量添加样本")
            print("3. 查看现有样本")
            print("4. 评分测试")
            print("5. 退出")
            
            choice = input("请输入选择 (1-5): ").strip()
            
            if choice == '1':
                self.add_single_sample()
            elif choice == '2':
                self.batch_add_samples()
            elif choice == '3':
                self.view_samples()
            elif choice == '4':
                self.test_scoring()
            elif choice == '5':
                print("退出程序")
                break
            else:
                print("无效选择")
    
    def add_single_sample(self):
        """添加单个样本"""
        print("\n添加单个样本")
        print("-" * 40)
        
        text = input("请输入样本文本: ").strip()
        if not text:
            print("文本不能为空")
            return
        
        self.add_sample(text)
    
    def view_samples(self):
        """查看现有样本"""
        print("\n现有样本:")
        print("=" * 60)
        
        content = self.read_existing_samples()
        if not content:
            print("暂无样本")
            return
        
        print(content)
    
    def test_scoring(self):
        """测试评分"""
        print("\n评分测试")
        print("-" * 40)
        
        text = input("请输入要评分的文本: ").strip()
        if not text:
            print("文本不能为空")
            return
        
        score = self.score_text(text)
        category = self.suggest_category(text)
        
        print(f"评分: {score:.2f}")
        print(f"建议分类: {category}")
        
        if score >= 80:
            print("🌟 高分样本！")
        elif score >= 60:
            print("👍 中等分数")
        elif score >= 40:
            print("⚠️  分数偏低")
        else:
            print("❌ 分数很低")

def main():
    """主函数"""
    collector = SampleCollector()
    collector.interactive_mode()

if __name__ == "__main__":
    main()

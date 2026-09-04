#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
段落级评分系统
支持人工标注和模型训练
"""

import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime
from bert_excitation_train.scripts.emotion_scoring.optimized_rule_scorer import OptimizedRuleScorer
try:  # 兼容作为脚本或包导入的场景
    from emotion_analyzer import EmotionAnalyzer
except ImportError:  # pragma: no cover - fallback for package import
    from scripts.emotion_analyzer import EmotionAnalyzer
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score
import re

class ParagraphScorer:
    def __init__(self):
        self.scorer = OptimizedRuleScorer()
        self.training_data = []
        self.model = None
        self.feature_names = []
        self.use_emotion = os.environ.get('ENABLE_EMOTION_ANALYZER', '1') != '0'
        self._emotion_analyzer = None
        self._emotion_warned = False
        
    def split_into_paragraphs(self, text, min_length=50):
        """将文本分割成段落"""
        # 按段落分割（双换行符）
        paragraphs = re.split(r'\n\s*\n', text)
        
        # 过滤太短的段落
        valid_paragraphs = []
        for i, para in enumerate(paragraphs):
            para = para.strip()
            if len(para) >= min_length:
                valid_paragraphs.append({
                    'index': i + 1,
                    'content': para,
                    'length': len(para)
                })
        
        return valid_paragraphs
    
    def _get_emotion_analyzer(self):
        if not self.use_emotion:
            return None

        if self._emotion_analyzer is not None:
            return self._emotion_analyzer

        analyzer = EmotionAnalyzer()
        if analyzer.available:
            self._emotion_analyzer = analyzer
            return analyzer

        if not self._emotion_warned:
            print(f"⚠️ 情绪分析模型不可用：{analyzer.last_error or '未知错误'}")
            self._emotion_warned = True
        return None

    def analyze_emotion(self, text):
        analyzer = self._get_emotion_analyzer()
        if not analyzer:
            return None
        return analyzer.analyze(text)

    def get_emotion_summary(self, text):
        analyzer = self._get_emotion_analyzer()
        if not analyzer:
            return None
        return analyzer.summarize(text)

    def extract_features(self, text):
        """提取文本特征"""
        features = {}
        
        # 基础特征
        features['length'] = len(text)
        features['word_count'] = len(text.split())
        features['sentence_count'] = len(re.split(r'[。！？]', text))
        
        # 情绪关键词特征
        emotion_keywords = {
            'tension': ['紧张', '心跳', '加快', '警觉', '可疑', '跟踪', '脚步声'],
            'action': ['跑', '逃', '追', '躲', '藏', '冲', '撞', '摔', '倒'],
            'danger': ['火', '烟', '血', '枪', '刀', '毒', '炸', '爆', '死', '伤'],
            'dialogue': ['"', '"', '「', '」', '！', '？', '！', '？'],
            'time_pressure': ['只有', '只剩', '分钟', '秒', '小时', '时间', '倒计时']
        }
        
        for category, keywords in emotion_keywords.items():
            count = sum(1 for word in keywords if word in text)
            features[f'{category}_count'] = count
            features[f'{category}_density'] = count / len(text) if len(text) > 0 else 0
        
        # 标点符号特征
        features['exclamation_count'] = text.count('！') + text.count('!')
        features['question_count'] = text.count('？') + text.count('?')
        features['ellipsis_count'] = text.count('…') + text.count('...')
        
        # 重复字符特征
        features['repeated_chars'] = len(re.findall(r'(.)\1{2,}', text))
        
        # 对话特征
        features['dialogue_ratio'] = len(re.findall(r'[""「」].*?[""「」]', text)) / len(text) if len(text) > 0 else 0

        # 情绪模型特征
        analyzer = self._get_emotion_analyzer()
        if analyzer:
            try:
                features.update(analyzer.extract_features(text))
            except Exception as exc:
                if not self._emotion_warned:
                    print(f"⚠️ 情绪特征提取失败：{exc}")
                    self._emotion_warned = True
        else:
            # 保证特征矩阵结构稳定
            features.setdefault('emotion_positive_score', 0.0)
            features.setdefault('emotion_negative_score', 0.0)
            features.setdefault('emotion_intensity', 0.0)
            features.setdefault('emotion_polarity', 0.0)
        
        return features
    
    def manual_annotation_interface(self, paragraphs):
        """人工标注界面"""
        print("=" * 80)
        print("段落级人工标注界面")
        print("=" * 80)
        print("请为每个段落评分（1-100分）")
        print("评分标准：")
        print("  90-100: 极度紧张，情节高潮")
        print("  80-89:  高度紧张，重要情节")
        print("  70-79:  明显紧张，有冲突")
        print("  60-69:  轻微紧张，有悬念")
        print("  50-59:  平淡但有内容")
        print("  40-49:  比较平淡")
        print("  30-39:  很平淡")
        print("  20-29:  非常平淡")
        print("  1-19:   极其平淡")
        print("=" * 80)
        
        annotations = []
        
        for i, para in enumerate(paragraphs, 1):
            print(f"\n段落 {i}/{len(paragraphs)}:")
            print("-" * 60)
            print(f"内容: {para['content']}")
            print(f"长度: {para['length']} 字符")
            
            # 显示模型预测分数
            model_score = self.scorer.calculate_score(para['content'])
            print(f"模型预测分数: {model_score:.2f}")

            emotion_summary = self.get_emotion_summary(para['content'])
            if emotion_summary:
                print(f"情绪分析: {emotion_summary}")
            
            while True:
                try:
                    user_score = input(f"请输入您的评分 (1-100, 输入'skip'跳过): ").strip()
                    
                    if user_score.lower() == 'skip':
                        print("跳过此段落")
                        break
                    
                    score = float(user_score)
                    if 1 <= score <= 100:
                        # 提取特征
                        features = self.extract_features(para['content'])
                        
                        annotation = {
                            'paragraph_index': i,
                            'content': para['content'],
                            'user_score': score,
                            'model_score': model_score,
                            'features': features,
                            'timestamp': datetime.now().isoformat()
                        }
                        
                        annotations.append(annotation)
                        print(f"已记录评分: {score}")
                        break
                    else:
                        print("评分必须在1-100之间")
                except ValueError:
                    print("请输入有效的数字")
        
        return annotations
    
    def load_annotations(self, file_path):
        """加载已有标注数据"""
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    
    def save_annotations(self, annotations, file_path):
        """保存标注数据"""
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(annotations, f, ensure_ascii=False, indent=2)
        print(f"标注数据已保存到: {file_path}")
    
    def train_model(self, annotations):
        """训练评分模型"""
        if len(annotations) < 3:
            print(f"标注数据不足（需要至少3条，当前{len(annotations)}条），无法训练模型")
            return False
        
        # 准备训练数据
        X = []
        y = []
        
        for ann in annotations:
            text = ann.get('content') or ann.get('text') or ''
            features = ann.get('features', {})
            if (not features) or (self.use_emotion and not any(k.startswith('emotion_') for k in features.keys())):
                features = self.extract_features(text)
            # 转换为数值向量
            feature_vector = []
            for key in sorted(features.keys()):
                feature_vector.append(features[key])
            
            X.append(feature_vector)
            y.append(ann.get('user_score', ann.get('manual_score', 0)))
        
        X = np.array(X)
        y = np.array(y)
        
        # 获取特征名称
        if annotations:
            self.feature_names = sorted(annotations[0]['features'].keys())
        
        # 分割训练集和测试集
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        # 训练随机森林模型
        self.model = RandomForestRegressor(n_estimators=100, random_state=42)
        self.model.fit(X_train, y_train)
        
        # 评估模型
        y_pred = self.model.predict(X_test)
        mse = mean_squared_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred)
        
        print(f"模型训练完成！")
        print(f"测试集MSE: {mse:.2f}")
        print(f"测试集R2: {r2:.2f}")
        
        # 显示特征重要性
        if hasattr(self.model, 'feature_importances_'):
            print(f"\n特征重要性（前10个）:")
            importance = list(zip(self.feature_names, self.model.feature_importances_))
            importance.sort(key=lambda x: x[1], reverse=True)
            
            for i, (feature, imp) in enumerate(importance[:10]):
                print(f"  {i+1}. {feature}: {imp:.3f}")
        
        return True
    
    def predict_score(self, text):
        """使用训练好的模型预测分数"""
        if self.model is None:
            print("模型未训练，使用规则评分")
            return self.scorer.calculate_score(text)
        
        features = self.extract_features(text)
        feature_vector = []
        for key in self.feature_names:
            feature_vector.append(features.get(key, 0))
        
        score = self.model.predict([feature_vector])[0]
        return max(1, min(100, score))  # 限制在1-100范围内
    
    def evaluate_paragraphs(self, text):
        """评估文本的所有段落"""
        paragraphs = self.split_into_paragraphs(text)
        
        print(f"文本分割为 {len(paragraphs)} 个段落")
        print("=" * 80)
        
        results = []
        for i, para in enumerate(paragraphs, 1):
            model_score = self.scorer.calculate_score(para['content'])
            trained_score = self.predict_score(para['content'])
            
            result = {
                'paragraph_index': i,
                'content': para['content'],
                'length': para['length'],
                'rule_score': model_score,
                'trained_score': trained_score,
                'score_difference': abs(trained_score - model_score)
            }
            
            results.append(result)
            
            print(f"段落 {i}:")
            print(f"  内容: {para['content'][:100]}...")
            print(f"  规则评分: {model_score:.2f}")
            print(f"  训练评分: {trained_score:.2f}")
            print(f"  差异: {result['score_difference']:.2f}")
            print()
        
        return results

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='段落级评分系统')
    parser.add_argument('--action', type=str, 
                       choices=['annotate', 'train', 'evaluate', 'compare'],
                       default='annotate', help='执行的操作')
    parser.add_argument('--text_file', type=str, help='要分析的文本文件')
    parser.add_argument('--annotations_file', type=str, 
                       default='bert_excitation_train/data/training/paragraph_annotations.json',
                       help='标注数据文件')
    
    args = parser.parse_args()
    
    scorer = ParagraphScorer()
    
    if args.action == 'annotate':
        # 人工标注
        if not args.text_file:
            print("请指定要标注的文本文件")
            return
        
        with open(args.text_file, 'r', encoding='utf-8') as f:
            text = f.read()
        
        paragraphs = scorer.split_into_paragraphs(text)
        annotations = scorer.manual_annotation_interface(paragraphs)
        
        # 保存标注
        scorer.save_annotations(annotations, args.annotations_file)
        
    elif args.action == 'train':
        # 训练模型
        annotations = scorer.load_annotations(args.annotations_file)
        if scorer.train_model(annotations):
            # 保存模型
            model_data = {
                'model_type': 'random_forest',
                'feature_names': scorer.feature_names,
                'training_samples': len(annotations),
                'trained_at': datetime.now().isoformat()
            }
            
            model_file = args.annotations_file.replace('.json', '_model.json')
            with open(model_file, 'w', encoding='utf-8') as f:
                json.dump(model_data, f, ensure_ascii=False, indent=2)
            
            print(f"模型信息已保存到: {model_file}")
    
    elif args.action == 'evaluate':
        # 评估段落
        if not args.text_file:
            print("请指定要评估的文本文件")
            return
        
        with open(args.text_file, 'r', encoding='utf-8') as f:
            text = f.read()
        
        # 加载训练好的模型
        model_file = args.annotations_file.replace('.json', '_model.json')
        if os.path.exists(model_file):
            with open(model_file, 'r', encoding='utf-8') as f:
                model_data = json.load(f)
            scorer.feature_names = model_data['feature_names']
            print(f"已加载训练好的模型（{model_data['training_samples']}个训练样本）")
        
        results = scorer.evaluate_paragraphs(text)
        
        # 保存评估结果
        output_file = args.text_file.replace('.txt', '_paragraph_scores.json')
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"评估结果已保存到: {output_file}")
    
    elif args.action == 'compare':
        # 对比规则评分和训练评分
        if not args.text_file:
            print("请指定要对比的文本文件")
            return
        
        with open(args.text_file, 'r', encoding='utf-8') as f:
            text = f.read()
        
        paragraphs = scorer.split_into_paragraphs(text)
        
        print("段落评分对比:")
        print("=" * 80)
        
        for i, para in enumerate(paragraphs, 1):
            rule_score = scorer.scorer.calculate_score(para['content'])
            trained_score = scorer.predict_score(para['content'])
            
            print(f"段落 {i}:")
            print(f"  内容: {para['content'][:100]}...")
            print(f"  规则评分: {rule_score:.2f}")
            print(f"  训练评分: {trained_score:.2f}")
            print(f"  差异: {abs(trained_score - rule_score):.2f}")
            print()

if __name__ == "__main__":
    main()

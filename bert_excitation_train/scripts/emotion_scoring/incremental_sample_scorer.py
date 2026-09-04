#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增量样本评分系统
智能识别新增样本，避免重复评分，支持增量训练
"""

import sys
import os
import json
import re
import hashlib
from datetime import datetime

# 设置标准输出编码为UTF-8（解决Windows终端乱码问题）
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bert_excitation_train.scripts.emotion_scoring.paragraph_scorer import ParagraphScorer
from bert_excitation_train.scripts.emotion_scoring.optimized_rule_scorer import OptimizedRuleScorer

class IncrementalSampleScorer:
    def __init__(self):
        self.scored_file = "bert_excitation_train/data/universal_samples_scored.txt"
        self.scoring_log = "bert_excitation_train/data/training/scoring_log.json"
        self.sample_hashes = {}  # 存储已评分样本的哈希值
        
    def load_scoring_log(self):
        """加载评分日志"""
        if os.path.exists(self.scoring_log):
            with open(self.scoring_log, 'r', encoding='utf-8') as f:
                log_data = json.load(f)
                self.sample_hashes = log_data.get('scored_hashes', {})
                return log_data
        return {'scored_hashes': {}, 'last_update': None}
    
    def save_scoring_log(self, log_data):
        """保存评分日志"""
        os.makedirs(os.path.dirname(self.scoring_log), exist_ok=True)
        log_data['scored_hashes'] = self.sample_hashes
        log_data['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(self.scoring_log, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
    
    def get_sample_hash(self, content):
        """获取样本内容的哈希值"""
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def parse_universal_samples(self, content):
        """解析universal_samples.txt文件（新的多标签格式）"""
        samples = []
        lines = content.strip().split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # 检查是否是样本标题（## 开头）
            if line.startswith('## '):
                sample_title = line[3:].strip()  # 去掉 "## "
                
                # 初始化样本数据
                sample_data = {
                    'title': sample_title,
                    'emotion_tags': [],
                    'scene_tags': [],
                    'conflict_tags': [],
                    'action_tags': [],
                    'plot_tags': [],
                    'score': 0.0,
                    'content': ''
                }
                
                # 读取后续的标签和内容
                i += 1
                while i < len(lines):
                    line = lines[i].strip()
                    
                    if not line:
                        i += 1
                        continue
                    
                    # 如果遇到下一个样本标题，停止
                    if line.startswith('## '):
                        break
                    
                    # 解析各种标签
                    if line.startswith('**情绪标签**:'):
                        tags_str = line.split(':', 1)[1].strip()
                        sample_data['emotion_tags'] = [t.strip() for t in tags_str.split(',')]
                    elif line.startswith('**场景标签**:'):
                        tags_str = line.split(':', 1)[1].strip()
                        sample_data['scene_tags'] = [t.strip() for t in tags_str.split(',')]
                    elif line.startswith('**冲突标签**:'):
                        tags_str = line.split(':', 1)[1].strip()
                        sample_data['conflict_tags'] = [t.strip() for t in tags_str.split(',')]
                    elif line.startswith('**动作标签**:'):
                        tags_str = line.split(':', 1)[1].strip()
                        sample_data['action_tags'] = [t.strip() for t in tags_str.split(',')]
                    elif line.startswith('**情节标签**:'):
                        tags_str = line.split(':', 1)[1].strip()
                        sample_data['plot_tags'] = [t.strip() for t in tags_str.split(',')]
                    elif line.startswith('**评分**:'):
                        score_str = line.split(':', 1)[1].strip()
                        sample_data['score'] = float(score_str)
                    elif line.startswith('**内容**:'):
                        content_str = line.split(':', 1)[1].strip()
                        sample_data['content'] = content_str
                    
                    i += 1
                
                # 只有当内容不为空时才添加到样本列表
                if sample_data['content']:
                    # 只对内容部分计算哈希，忽略标签
                    sample_hash = self.get_sample_hash(sample_data['content'])
                    samples.append({
                        'title': sample_data['title'],
                        'category': sample_data['title'],  # 保持兼容性
                        'content': sample_data['content'],  # 只有这个用于评分
                        'emotion_tags': sample_data['emotion_tags'],
                        'scene_tags': sample_data['scene_tags'],
                        'conflict_tags': sample_data['conflict_tags'],
                        'action_tags': sample_data['action_tags'],
                        'plot_tags': sample_data['plot_tags'],
                        'original_score': sample_data['score'],
                        'hash': sample_hash,
                        'scored': sample_hash in self.sample_hashes
                    })
                continue
            
            i += 1
        
        return samples
    
    def load_existing_scores(self):
        """加载已有的评分数据"""
        existing_scores = {}
        if os.path.exists(self.scored_file):
            with open(self.scored_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            lines = content.strip().split('\n')
            current_sample = {}
            
            for line in lines:
                line = line.strip()
                if line.startswith('## 样本'):
                    if current_sample and 'content' in current_sample:
                        sample_hash = self.get_sample_hash(current_sample['content'])
                        existing_scores[sample_hash] = current_sample
                    current_sample = {}
                elif line.startswith('**标签**'):
                    current_sample['tag'] = line.split(':', 1)[1].strip()
                elif line.startswith('**评分**'):
                    try:
                        current_sample['score'] = float(line.split(':', 1)[1].strip())
                    except:
                        current_sample['score'] = 0
                elif line.startswith('**内容**'):
                    current_sample['content'] = line.split(':', 1)[1].strip()
                elif line.startswith('**添加时间**'):
                    current_sample['timestamp'] = line.split(':', 1)[1].strip()
            
            if current_sample and 'content' in current_sample:
                sample_hash = self.get_sample_hash(current_sample['content'])
                existing_scores[sample_hash] = current_sample
        
        return existing_scores
    
    def score_new_samples(self, samples):
        """只对新增样本进行评分"""
        # 加载评分日志
        log_data = self.load_scoring_log()
        
        # 过滤出未评分的样本
        new_samples = [s for s in samples if not s['scored']]
        existing_samples = [s for s in samples if s['scored']]
        
        print(f"[统计] 样本统计:")
        print(f"   总样本数: {len(samples)}")
        print(f"   已评分: {len(existing_samples)}")
        print(f"   新增待评分: {len(new_samples)}")
        
        if not new_samples:
            print("[完成] 所有样本都已评分，无需重复评分")
            return samples, 0
        
        print(f"\n[开始] 开始为 {len(new_samples)} 个新增样本评分...")
        
        # 初始化评分器
        rule_scorer = OptimizedRuleScorer()
        ml_scorer = ParagraphScorer()
        
        # 尝试加载ML模型
        annotations_file = "bert_excitation_train/data/training/paragraph_annotations.json"
        if os.path.exists(annotations_file):
            annotations = ml_scorer.load_annotations(annotations_file)
            if ml_scorer.train_model(annotations):
                print("[信息] 成功加载机器学习评分模型")
            else:
                print("[警告] 机器学习模型加载失败")
                ml_scorer = None
        else:
            print("[警告] 未找到训练数据")
            ml_scorer = None
        
        scored_count = 0
        
        for i, sample in enumerate(new_samples, 1):
            print(f"\n{'='*60}")
            print(f"新增样本 {i}/{len(new_samples)}")
            print(f"{'='*60}")
            print(f"分类: {sample['category']}")
            print(f"内容: {sample['content']}")
            print("-" * 60)
            
            # 计算规则评分
            rule_score = rule_scorer.calculate_score(sample['content'])
            print(f"[评分] 规则评分: {rule_score:.1f}")
            
            # 计算ML评分
            if ml_scorer and ml_scorer.model is not None:
                ml_score = ml_scorer.predict_score(sample['content'])
                print(f"[ML] ML评分: {ml_score:.1f}")
            else:
                ml_score = None
                print("[ML] ML评分: 不可用")
            
            # 人工评分
            while True:
                try:
                    manual_score = float(input(f"请输入人工评分 (1-100): ").strip())
                    if 1 <= manual_score <= 100:
                        sample['manual_score'] = manual_score
                        sample['rule_score'] = rule_score
                        sample['ml_score'] = ml_score
                        sample['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        sample['scored'] = True
                        
                        # 记录到哈希表
                        self.sample_hashes[sample['hash']] = {
                            'score': manual_score,
                            'timestamp': sample['timestamp'],
                            'category': sample['category']
                        }
                        
                        scored_count += 1
                        break
                    else:
                        print("[错误] 评分必须在1-100之间")
                except ValueError:
                    print("[错误] 请输入有效的数字")
                except KeyboardInterrupt:
                    print("\n\n[中断] 用户中断评分")
                    return samples, scored_count
            
            # 询问是否继续
            if i < len(new_samples):
                continue_choice = input(f"\n继续评分下一个样本？(y/n/s=跳过剩余): ").strip().lower()
                if continue_choice in ['n', 'no', '否']:
                    print("[完成] 评分结束")
                    break
                elif continue_choice in ['s', 'skip', '跳过']:
                    print("[跳过] 跳过剩余样本")
                    break
        
        # 保存评分日志
        self.save_scoring_log(log_data)
        
        return samples, scored_count
    
    def merge_scored_samples(self, samples):
        """合并所有评分样本"""
        # 加载已有评分
        existing_scores = self.load_existing_scores()
        
        # 合并数据
        all_samples = []
        for sample in samples:
            if sample['scored']:
                if sample['hash'] in existing_scores:
                    # 使用已有评分
                    existing = existing_scores[sample['hash']]
                    sample.update({
                        'manual_score': existing.get('score', 0),
                        'tag': existing.get('tag', '未分类'),
                        'timestamp': existing.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                    })
                else:
                    # 使用新评分（已经在score_new_samples中设置）
                    # 确保manual_score存在
                    if 'manual_score' not in sample:
                        sample['manual_score'] = 0
                    if 'tag' not in sample:
                        sample['tag'] = '未分类'
                    if 'timestamp' not in sample:
                        sample['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            all_samples.append(sample)
        
        return all_samples
    
    def save_merged_samples(self, samples):
        """保存合并后的样本"""
        with open(self.scored_file, 'w', encoding='utf-8') as f:
            f.write("# 高情绪评分样本库 (增量更新版本)\n")
            f.write(f"# 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# 总样本数: {len(samples)}\n")
            f.write(f"# 已评分样本: {len([s for s in samples if s.get('scored', False)])}\n\n")
            
            current_category = ""
            for i, sample in enumerate(samples, 1):
                if sample['category'] != current_category:
                    current_category = sample['category']
                    f.write(f"\n{current_category}\n")
                
                f.write(f"## 样本 {i}\n")
                f.write(f"**标签**: {sample.get('tag', '未分类')}\n")
                f.write(f"**评分**: {sample.get('manual_score', 0):.2f}\n")
                f.write(f"**内容**: {sample['content']}\n")
                f.write(f"**添加时间**: {sample.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}\n")
                f.write(f"**样本哈希**: {sample['hash']}\n\n")
    
    def prepare_incremental_training_data(self, samples):
        """准备增量训练数据"""
        print("\n🔄 准备增量训练数据...")
        
        # 处理所有已评分的样本（包括新增和已有的）
        scored_samples = [s for s in samples if s.get('scored', False) and s.get('manual_score', 0) > 0]
        
        if not scored_samples:
            print("[警告] 没有已评分的样本，无需准备训练数据")
            return 0, 0
        
        print(f"[信息] 发现 {len(scored_samples)} 个已评分样本")
        
        # 准备ML评分模型训练数据
        ml_annotations = []
        for sample in scored_samples:
            # 提取特征
            ml_scorer = ParagraphScorer()
            features = ml_scorer.extract_features(sample['content'])
            
            annotation = {
                'text': sample['content'],
                'user_score': sample['manual_score'],
                'features': features,
                'category': sample['category'],
                'timestamp': sample['timestamp'],
                'sample_hash': sample['hash']
            }
            ml_annotations.append(annotation)
        
        # 保存增量ML训练数据
        if ml_annotations:
            ml_file = "bert_excitation_train/data/training/incremental_ml_annotations.json"
            os.makedirs(os.path.dirname(ml_file), exist_ok=True)
            with open(ml_file, 'w', encoding='utf-8') as f:
                json.dump(ml_annotations, f, ensure_ascii=False, indent=2)
            print(f"[保存] 增量ML训练数据已保存: {ml_file} ({len(ml_annotations)} 个样本)")
        
        # 准备生成模型训练数据（只使用高分样本）
        generation_data = []
        for sample in scored_samples:
            if sample.get('manual_score', 0) >= 70:  # 只使用高分样本
                # 创建指令-输出对
                instruction = f"请生成一段{sample['category']}的高情绪评分内容"
                output = sample['content']
                
                generation_data.append({
                    'instruction': instruction,
                    'output': output,
                    'score': sample['manual_score'],
                    'category': sample['category'],
                    'sample_hash': sample['hash']
                })
        
        # 保存增量生成模型训练数据
        if generation_data:
            gen_file = "bert_excitation_train/data/training/incremental_generation_data.jsonl"
            os.makedirs(os.path.dirname(gen_file), exist_ok=True)
            with open(gen_file, 'w', encoding='utf-8') as f:
                for item in generation_data:
                    f.write(json.dumps(item, ensure_ascii=False) + '\n')
            print(f"[保存] 增量生成模型训练数据已保存: {gen_file} ({len(generation_data)} 个样本)")
        
        return len(ml_annotations), len(generation_data)

def main():
    """主函数"""
    print("=== 增量样本评分系统 ===")
    print("=" * 60)
    print("智能识别新增样本，避免重复评分")
    print("=" * 60)
    
    scorer = IncrementalSampleScorer()
    
    # 读取样本文件
    sample_file = "bert_excitation_train/data/universal_samples.txt"
    if not os.path.exists(sample_file):
        print(f"[错误] 样本文件不存在: {sample_file}")
        return
    
    with open(sample_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 解析样本
    samples = scorer.parse_universal_samples(content)
    print(f"[信息] 找到 {len(samples)} 个样本")
    
    if not samples:
        print("[错误] 没有找到可评分的样本")
        return
    
    # 增量评分
    scored_samples, scored_count = scorer.score_new_samples(samples)
    
    if scored_count == 0:
        print("[完成] 没有新增样本需要评分")
    else:
        print(f"\n[完成] 完成评分: {scored_count} 个新增样本")
    
    # 合并所有样本
    all_samples = scorer.merge_scored_samples(scored_samples)
    
    # 保存合并结果
    scorer.save_merged_samples(all_samples)
    print(f"[保存] 样本数据已保存: {scorer.scored_file}")
    
    # 准备增量训练数据
    ml_count, gen_count = scorer.prepare_incremental_training_data(all_samples)
    
    if ml_count > 0 or gen_count > 0:
        print(f"\n[训练数据] 增量训练数据准备完成:")
        print(f"   ML评分模型: {ml_count} 个新样本")
        print(f"   生成模型: {gen_count} 个新样本")
        
        # 询问是否训练
        train_choice = input(f"\n是否使用增量数据训练模型？(y/n): ").strip().lower()
        if train_choice in ['y', 'yes', '是']:
            print("[提示] 可以使用以下命令进行增量训练:")
            print("   python scripts/incremental_model_trainer.py")
    else:
        print("[提示] 没有新的训练数据")
    
    print("\n=== 增量评分完成！ ===")

if __name__ == "__main__":
    main()

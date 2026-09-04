#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Complete Manual Scoring System
Allow manual scoring of all samples and train models
"""

import sys
import os
import json
import re
import hashlib
import io
from datetime import datetime

# Fix encoding issues
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONUTF8'] = '1'

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bert_excitation_train.scripts.emotion_scoring.paragraph_scorer import ParagraphScorer
from bert_excitation_train.scripts.emotion_scoring.optimized_rule_scorer import OptimizedRuleScorer
from bert_excitation_train.scripts.emotion_scoring.emotion_analyzer import EmotionAnalyzer

def load_all_samples():
    """Load all samples from universal_samples.txt"""
    sample_file = "bert_excitation_train/data/universal_samples.txt"
    if not os.path.exists(sample_file):
        print("样本文件不存在")
        return []
    
    with open(sample_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    samples = []
    lines = content.strip().split('\n')
    current_category = ""
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check if it's a category title
        if re.match(r'^\d+\.', line):
            current_category = line
            continue
            
        # Skip already scored samples (## format)
        if line.startswith('## '):
            continue
        if line.startswith('**标签**') or line.startswith('**评分**') or line.startswith('**内容**') or line.startswith('**添加时间**'):
            continue
            
        # Check if it's quoted content
        if line.startswith('"') and line.endswith('"'):
            sample_text = line[1:-1]  # Remove quotes
            if sample_text and current_category:
                sample_hash = hashlib.md5(sample_text.encode('utf-8')).hexdigest()
                samples.append({
                    'category': current_category,
                    'content': sample_text,
                    'hash': sample_hash
                })
    
    return samples

def create_manual_scoring_file(samples):
    """Create a file for manual scoring of all samples"""
    scoring_file = "all_samples_manual_scoring.txt"
    
    content = "# 所有样本人工评分文件\n"
    content += "# 格式：每行一个文本，用引号包围\n"
    content += "# 请为每个样本评分，格式：\"文本内容\" -> 评分(1-100)\n"
    content += "# 示例：\"拳风炸裂，两道刚猛劲力凌空相撞，气浪如涟漪般爆开！\" -> 85\n\n"
    
    for i, sample in enumerate(samples, 1):
        content += f"# 样本 {i}: {sample['category']}\n"
        content += f'"{sample["content"]}" -> \n\n'
    
    with open(scoring_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"已创建所有样本评分文件: {scoring_file}")
    print(f"总共 {len(samples)} 个样本需要评分")
    print("请编辑此文件，为每个样本添加评分，然后重新运行此脚本")
    return scoring_file

def process_manual_scores():
    """Process manual scores from file"""
    scoring_file = "all_samples_manual_scoring.txt"
    if not os.path.exists(scoring_file):
        print(f"评分文件不存在: {scoring_file}")
        return False
    
    # Initialize scorers
    rule_scorer = OptimizedRuleScorer()
    ml_scorer = ParagraphScorer()
    
    # Load existing annotations
    annotation_file = "bert_excitation_train/data/training/manual_annotations.json"
    existing_annotations = []
    if os.path.exists(annotation_file):
        with open(annotation_file, 'r', encoding='utf-8') as f:
            existing_annotations = json.load(f)
        print(f"找到 {len(existing_annotations)} 个现有标注")
    
    # Read scoring file
    with open(scoring_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    new_annotations = []
    processed_count = 0
    
    print(f"\n开始处理评分文件...")
    
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith('#') or not line.startswith('"'):
            continue
        
        # Check if line has a score
        if ' -> ' not in line:
            continue
        
        # Extract text and score
        try:
            text_part, score_part = line.split(' -> ')
            text = text_part[1:-1]  # Remove quotes
            score = float(score_part.strip())
            
            if not (1 <= score <= 100):
                print(f"警告：样本 {i} 的评分 {score} 不在1-100范围内，跳过")
                continue
            
            print(f"\n处理样本 {i}: {text[:50]}...")
            print(f"人工评分: {score}")
            
            # Calculate rule score
            rule_score = rule_scorer.calculate_score(text)
            print(f"规则评分: {rule_score:.1f}")

            # Emotion analysis - 深度情绪分析
            emotion_result = ml_scorer.analyze_emotion(text)
            emotion_payload = None
            if emotion_result:
                # 使用新的深度情绪摘要
                emotion_summary = ml_scorer.get_emotion_summary(text)
                if emotion_summary:
                    print(f"情绪分析: {emotion_summary}")
                else:
                    print(f"情绪分析: {emotion_result.label} (可信度 {emotion_result.confidence:.2f}, 强度 {emotion_result.intensity:.2f})")
                
                # 保存完整的深度情绪数据
                emotion_payload = {
                    'label': emotion_result.label,
                    'confidence': emotion_result.confidence,
                    'intensity': emotion_result.intensity,
                    'scores': emotion_result.scores,
                    'emotion_dimensions': getattr(emotion_result, 'emotion_dimensions', {}),
                    'surface_emotion': getattr(emotion_result, 'surface_emotion', None),
                    'deep_emotion': getattr(emotion_result, 'deep_emotion', None),
                    'emotion_depth': getattr(emotion_result, 'emotion_depth', 0.0),
                    'emotion_transition': getattr(emotion_result, 'emotion_transition', None),
                    'transition_strength': getattr(emotion_result, 'transition_strength', 0.0),
                    'emotion_complexity': getattr(emotion_result, 'emotion_complexity', 0.0),
                    'emotion_word_density': getattr(emotion_result, 'emotion_word_density', 0.0),
                }
            
            # Calculate ML score if model exists
            ml_score = None
            if existing_annotations and ml_scorer:
                try:
                    # Train model with existing data
                    training_data = []
                    for ann in existing_annotations:
                        features = ml_scorer.extract_features(ann['text'])
                        training_data.append({
                            'text': ann['text'],
                            'user_score': ann.get('manual_score', ann.get('user_score', 0)),
                            'features': features
                        })
                    if ml_scorer.train_model(training_data):
                        ml_score = ml_scorer.predict_score(text)
                        print(f"ML评分: {ml_score:.1f}")
                except Exception as e:
                    print(f"ML评分: 错误 - {e}")
                    ml_score = None
            
            # Create annotation
            annotation = {
                'text': text,
                'manual_score': score,
                'rule_score': rule_score,
                'ml_score': ml_score,
                'emotion_analysis': emotion_payload,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'category': 'manual_scoring',
                'text_hash': hashlib.md5(text.encode('utf-8')).hexdigest()
            }
            
            new_annotations.append(annotation)
            processed_count += 1
            
            print(f"已保存标注 {processed_count}")
            
        except Exception as e:
            print(f"处理样本 {i} 时出错: {e}")
            continue
    
    if new_annotations:
        # Save all annotations
        all_annotations = existing_annotations + new_annotations
        os.makedirs(os.path.dirname(annotation_file), exist_ok=True)
        with open(annotation_file, 'w', encoding='utf-8') as f:
            json.dump(all_annotations, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ 成功处理 {processed_count} 个样本")
        print(f"✅ 总标注数: {len(all_annotations)}")
        return True
    else:
        print("❌ 没有找到有效的评分数据")
        return False

def retrain_scoring_model():
    """Retrain ML scoring model with all annotations"""
    print("\n🔄 重新训练评分模型...")
    
    annotation_file = "bert_excitation_train/data/training/manual_annotations.json"
    if not os.path.exists(annotation_file):
        print("没有找到标注数据")
        return False
    
    with open(annotation_file, 'r', encoding='utf-8') as f:
        annotations = json.load(f)
    
    print(f"找到 {len(annotations)} 个标注样本")
    
    # Initialize ML scorer
    ml_scorer = ParagraphScorer()
    
    # Convert to training format
    training_data = []
    for ann in annotations:
        features = ml_scorer.extract_features(ann['text'])
        training_data.append({
            'text': ann['text'],
            'user_score': ann.get('manual_score', ann.get('user_score', 0)),
            'features': features
        })
    
    # Train model
    if ml_scorer.train_model(training_data):
        print("✅ 评分模型重新训练成功")
        return True
    else:
        print("❌ 评分模型训练失败")
        return False

def prepare_generation_training_data():
    """Prepare training data for generation model using high-score samples"""
    print("\n🔄 准备生成模型训练数据...")
    
    annotation_file = "bert_excitation_train/data/training/manual_annotations.json"
    if not os.path.exists(annotation_file):
        print("没有找到标注数据")
        return False
    
    with open(annotation_file, 'r', encoding='utf-8') as f:
        annotations = json.load(f)
    
    # Filter high-score samples (>=70)
    high_score_samples = [ann for ann in annotations if ann.get('manual_score', ann.get('user_score', 0)) >= 70]
    print(f"找到 {len(high_score_samples)} 个高分样本 (>=70分)")
    
    if not high_score_samples:
        print("没有找到高分样本")
        return False
    
    # Analyze emotion intensity and prioritize high-emotion samples
    print("分析样本情绪强度...")
    emotion_analyzer = EmotionAnalyzer()
    emotion_scored_samples = []
    
    for sample in high_score_samples:
        emotion_result = emotion_analyzer.analyze(sample['text'])
        emotion_scored_samples.append({
            'sample': sample,
            'emotion_intensity': emotion_result.intensity,
            'emotion_label': emotion_result.label
        })
    
    # Sort by emotion intensity (descending)
    emotion_scored_samples.sort(key=lambda x: x['emotion_intensity'], reverse=True)
    
    # Filter high-emotion samples (>=0.6) or use top 50% if not enough
    min_emotion = 0.6
    high_emotion_samples = [s for s in emotion_scored_samples if s['emotion_intensity'] >= min_emotion]
    
    if len(high_emotion_samples) >= 10:
        selected_samples = high_emotion_samples
        print(f"✅ 使用 {len(selected_samples)} 个高情绪样本 (情绪强度 >= {min_emotion})")
    else:
        # Use top 50% if not enough high-emotion samples
        keep_count = max(len(high_emotion_samples), len(emotion_scored_samples) // 2)
        selected_samples = emotion_scored_samples[:keep_count]
        print(f"⚠️ 使用前 {len(selected_samples)} 个样本 (包含 {len(high_emotion_samples)} 个高情绪样本)")
    
    avg_emotion = sum(s['emotion_intensity'] for s in selected_samples) / len(selected_samples)
    print(f"平均情绪强度: {avg_emotion:.3f}")
    
    # Create instruction-output pairs
    generation_data = []
    for item in selected_samples:
        sample = item['sample']
        instruction = f"请生成一段{sample.get('category', '高情绪')}的高情绪评分内容（情绪强度目标>=0.6）"
        output = sample['text']
        
        generation_data.append({
            'instruction': instruction,
            'output': output,
            'score': sample.get('manual_score', sample.get('user_score', 0)),
            'category': sample.get('category', '高情绪'),
            'sample_hash': sample.get('text_hash', ''),
            'emotion_intensity': item['emotion_intensity'],
            'emotion_label': item['emotion_label']
        })
    
    # Save generation training data
    gen_file = "bert_excitation_train/data/training/generation_training_data.jsonl"
    os.makedirs(os.path.dirname(gen_file), exist_ok=True)
    with open(gen_file, 'w', encoding='utf-8') as f:
        for item in generation_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"✅ 生成模型训练数据已保存: {gen_file} ({len(generation_data)} 个样本)")
    return True

def retrain_generation_model():
    """Retrain generation model with high-score samples"""
    print("\n🔄 重新训练生成模型...")
    
    # Check if training data exists
    gen_file = "bert_excitation_train/data/training/generation_training_data.jsonl"
    if not os.path.exists(gen_file):
        print("没有找到生成模型训练数据")
        return False
    
    # Load existing LoRA data
    existing_file = "bert_excitation_train/data/training/lora_data.jsonl"
    existing_data = []
    if os.path.exists(existing_file):
        with open(existing_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    existing_data.append(json.loads(line))
        print(f"找到 {len(existing_data)} 个现有LoRA训练样本")
    
    # Load new generation data
    new_data = []
    with open(gen_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                new_data.append(json.loads(line))
    print(f"找到 {len(new_data)} 个新的生成训练样本")
    
    # Merge data
    all_data = existing_data + new_data
    print(f"总训练样本: {len(all_data)}")
    
    # Save merged data
    merged_file = "bert_excitation_train/data/training/merged_generation_data.jsonl"
    with open(merged_file, 'w', encoding='utf-8') as f:
        for item in all_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"✅ 合并后的训练数据已保存: {merged_file}")
    
    # Run LoRA training
    print("开始LoRA训练...")
    import subprocess
    
    try:
        result = subprocess.run([
            'python', 'scripts/lora_training.py',
            '--data_file', merged_file,
            '--output_dir', 'bert_excitation_train/checkpoints/lora_model_high_score',
            '--epochs', '3'
        ], capture_output=True, text=True, encoding='utf-8')
        
        if result.returncode == 0:
            print("✅ 生成模型 (LoRA) 训练成功")
            return True
        else:
            print(f"❌ 生成模型训练失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ 生成模型训练出错: {e}")
        return False

def main():
    """Main function"""
    print("完整的人工评分和模型训练系统")
    print("=" * 60)
    print("目标：让生成模型生成高情绪评分的内容")
    print("=" * 60)
    
    # Step 1: Load all samples
    print("\n📚 步骤1: 加载所有样本")
    samples = load_all_samples()
    print(f"找到 {len(samples)} 个样本")
    
    if not samples:
        print("没有找到样本")
        return
    
    # Step 2: Create manual scoring file
    print("\n📝 步骤2: 创建人工评分文件")
    scoring_file = create_manual_scoring_file(samples)
    
    # Check if scoring file has been edited
    if not os.path.exists(scoring_file):
        print("评分文件不存在，请先创建")
        return
    
    # Check if file has been edited (contains scores)
    with open(scoring_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if ' -> ' not in content:
        print("请先编辑评分文件，为每个样本添加评分")
        print("格式：\"文本内容\" -> 评分(1-100)")
        return
    
    # Step 3: Process manual scores
    print("\n🎯 步骤3: 处理人工评分")
    if not process_manual_scores():
        print("处理人工评分失败")
        return
    
    # Step 4: Retrain scoring model
    print("\n🤖 步骤4: 重新训练评分模型")
    if not retrain_scoring_model():
        print("评分模型训练失败")
        return
    
    # Step 5: Prepare generation training data
    print("\n📊 步骤5: 准备生成模型训练数据")
    if not prepare_generation_training_data():
        print("生成模型训练数据准备失败")
        return
    
    # Step 6: Retrain generation model
    print("\n🔄 步骤6: 重新训练生成模型")
    if not retrain_generation_model():
        print("生成模型训练失败")
        return
    
    print("\n🎉 完整系统训练完成！")
    print("=" * 60)
    print("✅ 所有样本已人工评分")
    print("✅ 评分模型已重新训练")
    print("✅ 生成模型已使用高分样本重新训练")
    print("✅ 生成模型现在会参考高评分样本生成内容")
    print("=" * 60)
    print("现在可以使用生成模型生成高情绪评分的内容了！")

if __name__ == "__main__":
    main()

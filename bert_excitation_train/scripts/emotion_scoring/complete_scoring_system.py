#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Complete Scoring System
Handles manual scoring, model training, and generation model updates
"""

import sys
import os
import json
import re
import hashlib
from datetime import datetime
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bert_excitation_train.scripts.emotion_scoring.paragraph_scorer import ParagraphScorer
from bert_excitation_train.scripts.emotion_scoring.optimized_rule_scorer import OptimizedRuleScorer
from bert_excitation_train.scripts.emotion_scoring.emotion_analyzer import EmotionAnalyzer

def load_universal_samples():
    """Load sample file"""
    sample_file = "bert_excitation_train/data/universal_samples.txt"
    if not os.path.exists(sample_file):
        print("Sample file not found")
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

def save_manual_scores(scores_data):
    """Save manual scores from user input"""
    annotation_file = "bert_excitation_train/data/training/manual_annotations.json"
    
    # Load existing annotations
    annotations = []
    if os.path.exists(annotation_file):
        with open(annotation_file, 'r', encoding='utf-8') as f:
            annotations = json.load(f)
    
    # Add new manual scores
    for score_data in scores_data:
        annotation = {
            'text': score_data['text'],
            'user_score': score_data['manual_score'],
            'rule_score': score_data['rule_score'],
            'ml_score': score_data.get('ml_score'),
            'emotion_analysis': score_data.get('emotion_analysis'),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'text_hash': score_data['text_hash'],
            'category': score_data['category']
        }
        annotations.append(annotation)
    
    # Save annotations
    os.makedirs(os.path.dirname(annotation_file), exist_ok=True)
    with open(annotation_file, 'w', encoding='utf-8') as f:
        json.dump(annotations, f, ensure_ascii=False, indent=2)
    
    print(f"Saved {len(scores_data)} manual scores")
    return len(annotations)

def retrain_ml_model():
    """Retrain ML scoring model with all annotations"""
    print("\n🔄 Retraining ML scoring model...")
    
    # Load all annotations
    annotation_file = "bert_excitation_train/data/training/manual_annotations.json"
    if not os.path.exists(annotation_file):
        print("No annotation data found")
        return False
    
    with open(annotation_file, 'r', encoding='utf-8') as f:
        annotations = json.load(f)
    
    print(f"Found {len(annotations)} total annotations")
    
    # Initialize ML scorer
    ml_scorer = ParagraphScorer()
    
    # Convert to training format
    training_data = []
    for ann in annotations:
        features = ml_scorer.extract_features(ann['text'])
        training_data.append({
            'text': ann['text'],
            'user_score': ann['user_score'],
            'features': features
        })
    
    # Train model
    if ml_scorer.train_model(training_data):
        print("✅ ML scoring model retrained successfully")
        return True
    else:
        print("❌ ML scoring model training failed")
        return False

def prepare_generation_training_data():
    """Prepare training data for generation model"""
    print("\n🔄 Preparing generation model training data...")
    
    # Load all annotations
    annotation_file = "bert_excitation_train/data/training/manual_annotations.json"
    if not os.path.exists(annotation_file):
        print("No annotation data found")
        return False
    
    with open(annotation_file, 'r', encoding='utf-8') as f:
        annotations = json.load(f)
    
    # Filter high-score samples (>=70)
    high_score_samples = [ann for ann in annotations if ann['user_score'] >= 70]
    print(f"Found {len(high_score_samples)} high-score samples (>=70)")
    
    if not high_score_samples:
        print("No high-score samples found for generation training")
        return False
    
    # Analyze emotion intensity and prioritize high-emotion samples
    print("Analyzing emotion intensity of samples...")
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
        print(f"✅ Using {len(selected_samples)} high-emotion samples (emotion intensity >= {min_emotion})")
    else:
        # Use top 50% if not enough high-emotion samples
        keep_count = max(len(high_emotion_samples), len(emotion_scored_samples) // 2)
        selected_samples = emotion_scored_samples[:keep_count]
        print(f"⚠️ Using top {len(selected_samples)} samples (including {len(high_emotion_samples)} high-emotion samples)")
    
    avg_emotion = sum(s['emotion_intensity'] for s in selected_samples) / len(selected_samples)
    print(f"Average emotion intensity: {avg_emotion:.3f}")
    
    # Create instruction-output pairs
    generation_data = []
    for item in selected_samples:
        sample = item['sample']
        instruction = f"请生成一段{sample['category']}的高情绪评分内容（情绪强度目标>=0.6）"
        output = sample['text']
        
        generation_data.append({
            'instruction': instruction,
            'output': output,
            'score': sample['user_score'],
            'category': sample['category'],
            'sample_hash': sample['text_hash'],
            'emotion_intensity': item['emotion_intensity'],
            'emotion_label': item['emotion_label']
        })
    
    # Save generation training data
    gen_file = "bert_excitation_train/data/training/generation_training_data.jsonl"
    os.makedirs(os.path.dirname(gen_file), exist_ok=True)
    with open(gen_file, 'w', encoding='utf-8') as f:
        for item in generation_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"✅ Generation training data saved: {gen_file} ({len(generation_data)} samples)")
    return True

def retrain_generation_model():
    """Retrain generation model with high-score samples"""
    print("\n🔄 Retraining generation model...")
    
    # Check if training data exists
    gen_file = "bert_excitation_train/data/training/generation_training_data.jsonl"
    if not os.path.exists(gen_file):
        print("No generation training data found")
        return False
    
    # Load existing LoRA data
    existing_file = "bert_excitation_train/data/training/lora_data.jsonl"
    existing_data = []
    if os.path.exists(existing_file):
        with open(existing_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    existing_data.append(json.loads(line))
        print(f"Found {len(existing_data)} existing LoRA training samples")
    
    # Load new generation data
    new_data = []
    with open(gen_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                new_data.append(json.loads(line))
    print(f"Found {len(new_data)} new generation training samples")
    
    # Merge data
    all_data = existing_data + new_data
    print(f"Total training samples: {len(all_data)}")
    
    # Save merged data
    merged_file = "bert_excitation_train/data/training/merged_generation_data.jsonl"
    with open(merged_file, 'w', encoding='utf-8') as f:
        for item in all_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"✅ Merged generation data saved: {merged_file}")
    
    # Run LoRA training
    print("Starting LoRA training...")
    import subprocess
    
    try:
        result = subprocess.run([
            'python', 'scripts/lora_training.py',
            '--data_file', merged_file,
            '--output_dir', 'bert_excitation_train/checkpoints/lora_model_updated',
            '--epochs', '3'
        ], capture_output=True, text=True, encoding='utf-8')
        
        if result.returncode == 0:
            print("✅ Generation model (LoRA) training successful")
            return True
        else:
            print(f"❌ Generation model training failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Generation model training error: {e}")
        return False

def main():
    """Main function"""
    print("Complete Scoring and Training System")
    print("=" * 60)
    print("This system will:")
    print("1. Allow manual scoring of samples")
    print("2. Retrain ML scoring model")
    print("3. Prepare generation model training data")
    print("4. Retrain generation model with high-score samples")
    print("=" * 60)
    
    # Load samples
    samples = load_universal_samples()
    print(f"\nFound {len(samples)} samples to score")
    
    if not samples:
        print("No samples found")
        return
    
    # Initialize scorers
    rule_scorer = OptimizedRuleScorer()
    ml_scorer = ParagraphScorer()
    
    # Load existing annotations
    annotation_file = "bert_excitation_train/data/training/manual_annotations.json"
    existing_annotations = []
    if os.path.exists(annotation_file):
        with open(annotation_file, 'r', encoding='utf-8') as f:
            existing_annotations = json.load(f)
        print(f"Found {len(existing_annotations)} existing annotations")
    
    # Manual scoring
    print(f"\n🎯 Manual Scoring Phase")
    print("=" * 40)
    
    scores_data = []
    for i, sample in enumerate(samples, 1):
        print(f"\nSample {i}/{len(samples)}")
        print(f"Category: {sample['category']}")
        print(f"Content: {sample['content']}")
        print("-" * 40)
        
        # Calculate rule score
        rule_score = rule_scorer.calculate_score(sample['content'])
        print(f"Rule Score: {rule_score:.1f}")

        # Emotion analysis - 深度情绪分析
        emotion_result = ml_scorer.analyze_emotion(sample['content'])
        emotion_payload = None
        if emotion_result:
            # 使用新的深度情绪摘要
            emotion_summary = ml_scorer.get_emotion_summary(sample['content'])
            if emotion_summary:
                print(f"情绪分析: {emotion_summary}")
            else:
                print(f"Emotion: {emotion_result.label} (confidence {emotion_result.confidence:.2f}, intensity {emotion_result.intensity:.2f})")
            
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
                        'user_score': ann['user_score'],
                        'features': features
                    })
                if ml_scorer.train_model(training_data):
                    ml_score = ml_scorer.predict_score(sample['content'])
                    print(f"ML Score: {ml_score:.1f}")
            except:
                print("ML Score: Not available")
        
        # Manual scoring
        while True:
            try:
                print(f"\nPlease score this sample (1-100):")
                print("1-20: Low emotion")
                print("21-40: Mild emotion") 
                print("41-60: Moderate emotion")
                print("61-80: High emotion")
                print("81-100: Very high emotion")
                
                manual_score = float(input("Your score: ").strip())
                if 1 <= manual_score <= 100:
                    break
                else:
                    print("Score must be between 1-100")
            except ValueError:
                print("Please enter a valid number")
            except KeyboardInterrupt:
                print("\nScoring interrupted by user")
                return
        
        # Store score data
        scores_data.append({
            'text': sample['content'],
            'manual_score': manual_score,
            'rule_score': rule_score,
            'ml_score': ml_score,
            'emotion_analysis': emotion_payload,
            'text_hash': sample['hash'],
            'category': sample['category']
        })
        
        print(f"✅ Score {manual_score} saved for sample {i}")
        
        # Ask if continue
        if i < len(samples):
            continue_choice = input(f"\nContinue to next sample? (y/n/s=skip remaining): ").strip().lower()
            if continue_choice in ['n', 'no']:
                print("Scoring ended")
                break
            elif continue_choice in ['s', 'skip']:
                print("Skipping remaining samples")
                break
    
    # Save manual scores
    if scores_data:
        total_annotations = save_manual_scores(scores_data)
        print(f"\n✅ Saved {len(scores_data)} manual scores (Total: {total_annotations} annotations)")
        
        # Retrain ML model
        if retrain_ml_model():
            print("✅ ML scoring model updated")
        else:
            print("❌ ML scoring model update failed")
        
        # Prepare generation training data
        if prepare_generation_training_data():
            print("✅ Generation training data prepared")
            
            # Retrain generation model
            if retrain_generation_model():
                print("✅ Generation model updated with high-score samples")
            else:
                print("❌ Generation model update failed")
        else:
            print("❌ Generation training data preparation failed")
    
    print(f"\n🎉 Complete scoring and training system finished!")
    print(f"📊 Total annotations: {len(scores_data)} new + {len(existing_annotations)} existing")
    print(f"🤖 ML scoring model: Updated")
    print(f"📝 Generation model: Updated with high-score samples")

if __name__ == "__main__":
    main()

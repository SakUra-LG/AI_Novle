#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于评分引导的LoRA训练系统
让生成模型学习"什么样的内容能获得高分"，主动向高分特征靠拢
"""

import os
import sys
import json
import torch
import numpy as np
from transformers import (
    AutoTokenizer, 
    AutoModelForCausalLM, 
    TrainingArguments, 
    Trainer,
    DataCollatorForLanguageModeling
)
from peft import LoraConfig, get_peft_model, TaskType
from datasets import Dataset
import argparse
from datetime import datetime

# 设置Windows UTF-8输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

class ScoreGuidedTrainer(Trainer):
    """支持评分引导的训练器"""
    
    def __init__(self, sample_weights=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sample_weights = sample_weights
    
    def compute_loss(self, model, inputs, return_outputs=False):
        """计算加权损失"""
        # 获取样本索引
        idx = inputs.pop("idx", None)
        
        # 计算原始损失
        outputs = model(**inputs)
        loss = outputs.loss
        
        # 应用样本权重
        if self.sample_weights is not None and idx is not None:
            # 获取当前batch的权重
            batch_weights = torch.tensor(
                [self.sample_weights[i.item()] for i in idx],
                device=loss.device,
                dtype=loss.dtype
            )
            # 加权损失
            loss = loss * batch_weights.mean()
        
        return (loss, outputs) if return_outputs else loss

def load_scored_training_data(data_file):
    """
    加载带评分的训练数据
    
    格式：JSONL，每行包含：
    {
        "instruction": "请生成...",
        "output": "实际内容",
        "score": 85  ← 人工评分
    }
    """
    if not os.path.exists(data_file):
        print(f"[错误] 数据文件不存在: {data_file}")
        return None, None
    
    samples = []
    with open(data_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                samples.append(data)
    
    print(f"[信息] 加载了 {len(samples)} 条训练数据")
    
    # 提取文本和评分
    texts = []
    scores = []
    for sample in samples:
        instruction = sample.get('instruction', '')
        output = sample.get('output', '')
        # 构建完整训练文本
        text = f"{instruction}\n{output}"
        
        texts.append(text)
        scores.append(sample.get('score', 70))
    
    return texts, scores

def analyze_score_distribution(scores):
    """分析评分分布"""
    scores = np.array(scores)
    
    print("\n" + "="*60)
    print("评分分布分析")
    print("="*60)
    print(f"样本总数: {len(scores)}")
    print(f"平均分: {scores.mean():.2f}")
    print(f"最低分: {scores.min():.2f}")
    print(f"最高分: {scores.max():.2f}")
    print(f"标准差: {scores.std():.2f}")
    
    # 分数段统计
    print("\n[分数段分布]")
    ranges = [
        (95, 100, "顶级"),
        (90, 94, "优秀"),
        (85, 89, "良好"),
        (80, 84, "中等"),
        (70, 79, "及格"),
        (0, 69, "较低")
    ]
    
    for low, high, label in ranges:
        count = np.sum((scores >= low) & (scores <= high))
        if count > 0:
            percentage = count / len(scores) * 100
            print(f"  {low}-{high}分 ({label}): {count}个 ({percentage:.1f}%)")
    
    print("="*60 + "\n")

def calculate_score_weights(scores, method='quadratic', strength=1.0):
    """
    根据评分计算样本权重
    
    参数:
        scores: 评分列表 (70-100)
        method: 权重计算方法
            - 'linear': 线性权重 (温和)
            - 'quadratic': 平方权重 (推荐)
            - 'exponential': 指数权重 (激进)
        strength: 权重强度系数 (0.5-2.0)
            - 0.5: 温和差异
            - 1.0: 标准差异 (推荐)
            - 2.0: 显著差异
    """
    scores = np.array(scores)
    
    print("\n" + "="*60)
    print(f"权重计算: {method}方法, 强度: {strength}")
    print("="*60)
    
    if method == 'linear':
        # 线性权重: score/100
        weights = scores / 100.0
        
    elif method == 'quadratic':
        # 平方权重: (score/100)^2
        normalized_scores = scores / 100.0
        weights = normalized_scores ** 2
        
    elif method == 'exponential':
        # 指数权重: exp((score-70)/10)
        weights = np.exp((scores - 70) / 10)
        
    else:
        raise ValueError(f"不支持的权重方法: {method}")
    
    # 应用强度系数
    if strength != 1.0:
        # weights = 1 + (weights - 1) * strength
        mean_weight = weights.mean()
        weights = mean_weight + (weights - mean_weight) * strength
    
    # 归一化，使平均权重为1
    weights = weights / weights.mean()
    
    # 显示权重统计
    print(f"\n[权重统计]")
    print(f"  平均权重: {weights.mean():.3f}")
    print(f"  最小权重: {weights.min():.3f}")
    print(f"  最大权重: {weights.max():.3f}")
    print(f"  权重范围: {weights.max() / weights.min():.2f}x")
    
    # 显示典型分数的权重
    print(f"\n[典型分数权重]")
    typical_scores = [70, 75, 80, 85, 90, 95]
    for score in typical_scores:
        mask = np.abs(scores - score) < 0.5
        if mask.any():
            avg_weight = weights[mask].mean()
            print(f"  {score}分样本: 权重 {avg_weight:.3f}")
    
    # 显示权重对比
    weight_70 = weights[np.abs(scores - 70) < 2].mean() if np.any(np.abs(scores - 70) < 2) else weights.min()
    weight_95 = weights[np.abs(scores - 95) < 2].mean() if np.any(np.abs(scores - 95) < 2) else weights.max()
    
    print(f"\n[权重效果]")
    print(f"  95分样本是70分样本的 {weight_95/weight_70:.2f} 倍影响力")
    print(f"  → 模型会更倾向学习95分样本的特征")
    print("="*60 + "\n")
    
    return weights.tolist()

def prepare_weighted_dataset(texts, scores, weights, tokenizer, max_length=512):
    """准备带权重的数据集"""
    def tokenize_function(examples):
        tokenized = tokenizer(
            examples['text'],
            truncation=True,
            padding='max_length',
            max_length=max_length,
            return_tensors="pt"
        )
        tokenized['idx'] = examples['idx']
        return tokenized
    
    dataset = Dataset.from_dict({
        "text": texts,
        "score": scores,
        "weight": weights,
        "idx": list(range(len(texts)))
    })
    
    tokenized_dataset = dataset.map(
        tokenize_function,
        batched=True,
        remove_columns=['text', 'score', 'weight']
    )
    
    return tokenized_dataset

def setup_lora_model(model_name, device):
    """设置LoRA模型"""
    print(f"\n[模型加载] 加载基础模型: {model_name}")
    
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.float16,
        device_map="auto"
    )
    
    # LoRA配置
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=16,  # LoRA秩
        lora_alpha=32,  # 缩放参数
        lora_dropout=0.1,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj", 
                       "gate_proj", "up_proj", "down_proj"]
    )
    
    model = get_peft_model(model, lora_config)
    
    print("\n[可训练参数]")
    model.print_trainable_parameters()
    
    return model

def train_score_guided_model(model, tokenizer, train_dataset, sample_weights,
                            output_dir, epochs=3, batch_size=4):
    """训练评分引导模型"""
    
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=4,
        warmup_steps=100,
        learning_rate=5e-4,
        fp16=True,
        logging_steps=10,
        save_steps=500,
        eval_strategy="no",
        save_total_limit=2,
        remove_unused_columns=False,
        report_to="none",
    )
    
    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer,
        mlm=False,
    )
    
    trainer = ScoreGuidedTrainer(
        sample_weights=sample_weights,
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        data_collator=data_collator,
    )
    
    print("\n" + "="*60)
    print("开始评分引导训练")
    print("="*60)
    print(f"训练轮数: {epochs}")
    print(f"批次大小: {batch_size}")
    print(f"样本总数: {len(train_dataset)}")
    print(f"预计步数: {len(train_dataset) // (batch_size * 4) * epochs}")
    print("="*60 + "\n")
    
    trainer.train()
    
    # 保存模型
    trainer.save_model()
    tokenizer.save_pretrained(output_dir)
    
    print(f"\n[完成] 模型已保存到: {output_dir}")
    return trainer

def main():
    parser = argparse.ArgumentParser(
        description='评分引导的LoRA训练 - 让模型学习如何获得高分'
    )
    parser.add_argument('--data_file', type=str,
                       default='data/training/incremental_generation_data.jsonl',
                       help='训练数据文件（JSONL格式，包含score字段）')
    parser.add_argument('--model_name', type=str,
                       default='Qwen/Qwen2.5-0.5B',
                       help='基础模型')
    parser.add_argument('--output_dir', type=str,
                       default='checkpoints/score_guided_lora',
                       help='输出目录')
    parser.add_argument('--epochs', type=int, default=3,
                       help='训练轮数')
    parser.add_argument('--batch_size', type=int, default=4,
                       help='批次大小')
    parser.add_argument('--max_length', type=int, default=512,
                       help='最大序列长度')
    parser.add_argument('--weight_method', type=str, default='quadratic',
                       choices=['linear', 'quadratic', 'exponential'],
                       help='权重计算方法')
    parser.add_argument('--weight_strength', type=float, default=1.0,
                       help='权重强度 (0.5-2.0)')
    
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("评分引导的生成模型训练系统")
    print("="*60)
    print(f"数据文件: {args.data_file}")
    print(f"基础模型: {args.model_name}")
    print(f"输出目录: {args.output_dir}")
    print(f"训练设置: {args.epochs}轮, 批次{args.batch_size}")
    print(f"权重方法: {args.weight_method}, 强度{args.weight_strength}")
    print("="*60 + "\n")
    
    # 1. 加载数据
    print("[步骤1] 加载训练数据...")
    texts, scores = load_scored_training_data(args.data_file)
    
    if texts is None:
        print("\n[提示] 请先运行评分脚本生成训练数据:")
        print("  python scripts/incremental_sample_scorer.py")
        return
    
    # 2. 分析评分分布
    analyze_score_distribution(scores)
    
    # 3. 计算样本权重
    print("[步骤2] 计算样本权重...")
    sample_weights = calculate_score_weights(
        scores, 
        method=args.weight_method,
        strength=args.weight_strength
    )
    
    # 4. 加载tokenizer
    print("[步骤3] 加载tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    
    # 5. 准备数据集
    print("[步骤4] 准备训练数据集...")
    train_dataset = prepare_weighted_dataset(
        texts, scores, sample_weights, tokenizer, args.max_length
    )
    print(f"  数据集大小: {len(train_dataset)}")
    
    # 6. 设置模型
    print("\n[步骤5] 设置LoRA模型...")
    model = setup_lora_model(
        args.model_name,
        "cuda" if torch.cuda.is_available() else "cpu"
    )
    
    # 7. 训练
    print("\n[步骤6] 开始训练...")
    trainer = train_score_guided_model(
        model, tokenizer, train_dataset, sample_weights,
        args.output_dir, args.epochs, args.batch_size
    )
    
    # 8. 保存训练信息
    training_info = {
        'train_time': datetime.now().isoformat(),
        'data_file': args.data_file,
        'model_name': args.model_name,
        'num_samples': len(texts),
        'weight_method': args.weight_method,
        'weight_strength': args.weight_strength,
        'epochs': args.epochs,
        'batch_size': args.batch_size,
        'score_stats': {
            'min': float(np.min(scores)),
            'max': float(np.max(scores)),
            'mean': float(np.mean(scores)),
            'std': float(np.std(scores))
        },
        'weight_stats': {
            'min': float(np.min(sample_weights)),
            'max': float(np.max(sample_weights)),
            'mean': float(np.mean(sample_weights)),
            'ratio': float(np.max(sample_weights) / np.min(sample_weights))
        }
    }
    
    info_file = os.path.join(args.output_dir, 'training_info.json')
    with open(info_file, 'w', encoding='utf-8') as f:
        json.dump(training_info, f, ensure_ascii=False, indent=2)
    
    print("\n" + "="*60)
    print("训练完成！")
    print("="*60)
    print(f"\n模型位置: {args.output_dir}")
    print(f"训练信息: {info_file}")
    
    print("\n[预期效果]")
    print("  生成的内容会主动向高分特征靠拢")
    print("  - 更紧张刺激的情节")
    print("  - 更饱满的情感表达")
    print("  - 更强烈的冲突感")
    print(f"  预计平均评分提升: 5-15%")
    
    print("\n[下一步]")
    print("  使用训练好的模型生成内容:")
    print(f"  python scripts/enhanced_rag_generator_v2.py \\")
    print(f"    --model {args.output_dir}")

if __name__ == "__main__":
    main()


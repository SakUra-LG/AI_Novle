#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全参数微调脚本
对模型进行全参数微调
"""

import os
import sys
import json
import torch
import pandas as pd
from transformers import (
    AutoTokenizer, 
    AutoModelForCausalLM, 
    TrainingArguments, 
    Trainer,
    DataCollatorForLanguageModeling
)
from datasets import Dataset
import argparse
from datetime import datetime

def load_training_data(data_file):
    """加载训练数据"""
    if data_file.endswith('.csv'):
        df = pd.read_csv(data_file)
        texts = df['text'].tolist()
    elif data_file.endswith('.jsonl'):
        texts = []
        with open(data_file, 'r', encoding='utf-8') as f:
            for line in f:
                data = json.loads(line)
                texts.append(data['text'])
    else:
        raise ValueError("不支持的数据格式，请使用CSV或JSONL格式")
    
    print(f"加载了 {len(texts)} 条训练数据")
    return texts

def prepare_dataset(texts, tokenizer, max_length=512):
    """准备训练数据集"""
    def tokenize_function(examples):
        return tokenizer(
            examples['text'],
            truncation=True,
            padding=True,
            max_length=max_length,
            return_tensors="pt"
        )
    
    # 创建数据集
    dataset = Dataset.from_dict({"text": texts})
    tokenized_dataset = dataset.map(
        tokenize_function,
        batched=True,
        remove_columns=dataset.column_names
    )
    
    return tokenized_dataset

def train_model(model, tokenizer, train_dataset, output_dir, num_epochs=3, batch_size=4):
    """训练模型"""
    # 训练参数
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=num_epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=4,
        warmup_steps=100,
        learning_rate=5e-5,
        fp16=True,
        logging_steps=10,
        save_steps=500,
        evaluation_strategy="no",
        save_total_limit=2,
        remove_unused_columns=False,
    )
    
    # 数据整理器
    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer,
        mlm=False,
    )
    
    # 创建训练器
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        data_collator=data_collator,
    )
    
    # 开始训练
    print("开始全参数微调...")
    trainer.train()
    
    # 保存模型
    trainer.save_model()
    tokenizer.save_pretrained(output_dir)
    
    print(f"模型已保存到: {output_dir}")
    return trainer

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='全参数微调脚本')
    parser.add_argument('--data_file', type=str, required=True, help='训练数据文件')
    parser.add_argument('--model_name', type=str, default='Qwen/Qwen2.5-0.5B', help='基础模型名称')
    parser.add_argument('--output_dir', type=str, default='checkpoints/finetuned_model', help='输出目录')
    parser.add_argument('--epochs', type=int, default=3, help='训练轮数')
    parser.add_argument('--batch_size', type=int, default=4, help='批次大小')
    parser.add_argument('--max_length', type=int, default=512, help='最大序列长度')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("全参数微调脚本")
    print("=" * 60)
    print(f"数据文件: {args.data_file}")
    print(f"基础模型: {args.model_name}")
    print(f"输出目录: {args.output_dir}")
    print(f"训练轮数: {args.epochs}")
    print(f"批次大小: {args.batch_size}")
    print()
    
    # 检查数据文件
    if not os.path.exists(args.data_file):
        print(f"[ERROR] 数据文件不存在: {args.data_file}")
        return
    
    # 加载数据
    texts = load_training_data(args.data_file)
    
    # 加载tokenizer和模型
    print("加载模型和tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    
    model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        torch_dtype=torch.float16,
        device_map="auto"
    )
    
    # 准备数据集
    print("准备训练数据集...")
    train_dataset = prepare_dataset(texts, tokenizer, args.max_length)
    
    # 训练模型
    trainer = train_model(
        model, 
        tokenizer, 
        train_dataset, 
        args.output_dir, 
        args.epochs, 
        args.batch_size
    )
    
    print("全参数微调完成！")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人工样本评分工具
支持对所有样本进行人工评分，用于训练更准确的评分模型
"""

import os
import json
import re
from datetime import datetime
from typing import List, Dict, Tuple

def extract_sentences_from_samples(file_path: str) -> List[Dict]:
    """从样本文件中提取所有句子"""
    sentences = []
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 处理旧格式（前50行）
    lines = content.split('\n')
    current_category = None
    current_score = None
    current_content = None
    
    for i, line in enumerate(lines):
        line = line.strip()
        
        # 跳过空行
        if not line:
            continue
            
        # 检查是否是类别标题（数字开头）
        if re.match(r'^\d+\.', line):
            current_category = line
            continue
            
        # 检查是否是评分行
        if line.startswith('"') and line.endswith('"'):
            current_content = line[1:-1]  # 去掉引号
            
            if current_content and current_category:
                # 将长文本分割成句子
                text_sentences = split_into_sentences(current_content)
                
                for j, sentence in enumerate(text_sentences):
                    if sentence.strip():
                        sentences.append({
                            'category': current_category,
                            'sentence': sentence.strip(),
                            'original_score': None,  # 旧格式没有评分
                            'sentence_index': j,
                            'total_sentences': len(text_sentences)
                        })
    
    # 处理新格式（## 开头的部分）
    new_format_content = content.split('## ')[1:] if '## ' in content else []
    
    for category in new_format_content:
        if not category.strip():
            continue
            
        lines = category.strip().split('\n')
        if len(lines) < 2:
            continue
            
        category_name = lines[0].strip()
        
        # 查找评分和内容
        current_score = None
        current_content = None
        
        for line in lines[1:]:
            if line.startswith('**评分**:'):
                try:
                    current_score = float(line.replace('**评分**:', '').strip())
                except:
                    current_score = None
            elif line.startswith('**内容**:'):
                current_content = line.replace('**内容**:', '').strip()
                
                if current_content:
                    # 将长文本分割成句子
                    text_sentences = split_into_sentences(current_content)
                    
                    for i, sentence in enumerate(text_sentences):
                        if sentence.strip():
                            sentences.append({
                                'category': category_name,
                                'sentence': sentence.strip(),
                                'original_score': current_score,
                                'sentence_index': i,
                                'total_sentences': len(text_sentences)
                            })
    
    return sentences

def split_into_sentences(text: str) -> List[str]:
    """将文本分割成句子"""
    # 使用中文句号、问号、感叹号分割
    sentences = re.split(r'[。！？]', text)
    # 过滤空句子
    sentences = [s.strip() for s in sentences if s.strip()]
    return sentences

def manual_scoring_interface(sentences: List[Dict]) -> List[Dict]:
    """人工评分界面"""
    scored_sentences = []
    total = len(sentences)
    
    print("=" * 60)
    print("人工样本评分工具")
    print("=" * 60)
    print(f"总共需要评分 {total} 个句子")
    print("评分标准：1-100分")
    print("- 1-20分：平淡无奇")
    print("- 21-40分：轻微紧张")
    print("- 41-60分：明显紧张")
    print("- 61-80分：高度紧张")
    print("- 81-100分：极度紧张")
    print("=" * 60)
    
    for i, sentence_data in enumerate(sentences, 1):
        print(f"\n进度: {i}/{total}")
        print(f"类别: {sentence_data['category']}")
        if sentence_data['original_score']:
            print(f"原评分: {sentence_data['original_score']}")
        print(f"句子: {sentence_data['sentence']}")
        
        while True:
            try:
                score_input = input("请输入评分 (1-100, 输入's'跳过, 输入'q'退出): ").strip()
                
                if score_input.lower() == 'q':
                    print("退出评分")
                    return scored_sentences
                elif score_input.lower() == 's':
                    print("跳过此句子")
                    break
                else:
                    score = float(score_input)
                    if 1 <= score <= 100:
                        sentence_data['manual_score'] = score
                        scored_sentences.append(sentence_data)
                        print(f"已记录评分: {score}")
                        break
                    else:
                        print("评分必须在1-100之间")
            except ValueError:
                print("请输入有效的数字")
    
    return scored_sentences

def save_scored_data(scored_sentences: List[Dict], output_file: str):
    """保存评分数据"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"data/training/manual_scores_{timestamp}.json"
    
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(scored_sentences, f, ensure_ascii=False, indent=2)
    
    print(f"\n评分数据已保存到: {output_file}")
    return output_file

def create_training_data(scored_sentences: List[Dict], output_file: str):
    """创建训练数据"""
    training_data = []
    
    for sentence_data in scored_sentences:
        training_data.append({
            'text': sentence_data['sentence'],
            'score': sentence_data['manual_score'],
            'category': sentence_data['category']
        })
    
    # 保存为JSONL格式
    jsonl_file = output_file.replace('.json', '.jsonl')
    with open(jsonl_file, 'w', encoding='utf-8') as f:
        for item in training_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    # 保存为CSV格式
    csv_file = output_file.replace('.json', '.csv')
    import pandas as pd
    df = pd.DataFrame(training_data)
    df.to_csv(csv_file, index=False, encoding='utf-8')
    
    print(f"训练数据已保存到:")
    print(f"- JSONL: {jsonl_file}")
    print(f"- CSV: {csv_file}")
    
    return jsonl_file, csv_file

def main():
    """主函数"""
    sample_file = "data/universal_samples.txt"
    
    if not os.path.exists(sample_file):
        print(f"错误: 样本文件 {sample_file} 不存在")
        return
    
    print("正在提取样本句子...")
    sentences = extract_sentences_from_samples(sample_file)
    
    if not sentences:
        print("没有找到可评分的句子")
        return
    
    print(f"成功提取 {len(sentences)} 个句子")
    
    # 开始人工评分
    scored_sentences = manual_scoring_interface(sentences)
    
    if not scored_sentences:
        print("没有完成任何评分")
        return
    
    print(f"\n完成评分 {len(scored_sentences)} 个句子")
    
    # 保存评分数据
    output_file = save_scored_data(scored_sentences, "data/training/manual_scores.json")
    
    # 创建训练数据
    jsonl_file, csv_file = create_training_data(scored_sentences, output_file)
    
    print("\n" + "=" * 60)
    print("评分完成！")
    print("=" * 60)
    print("接下来可以运行以下命令重新训练评分模型:")
    print(f"python scripts/paragraph_scorer.py --train_data {jsonl_file}")

if __name__ == "__main__":
    main()

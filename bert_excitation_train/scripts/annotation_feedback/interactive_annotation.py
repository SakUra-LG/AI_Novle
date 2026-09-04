#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互式段落标注工具
"""

import os
import sys
import json
import re
from datetime import datetime
from bert_excitation_train.scripts.emotion_scoring.paragraph_scorer import ParagraphScorer

def interactive_annotation():
    """交互式标注"""
    print("=" * 80)
    print("交互式段落标注工具")
    print("=" * 80)
    
    # 选择要标注的文件
    print("请选择要标注的文件:")
    
    # 查找可用的文本文件
    text_files = []
    for root, dirs, files in os.walk('.'):
        for file in files:
            if file.endswith('.txt') and ('generated' in root or 'chapters' in root):
                text_files.append(os.path.join(root, file))
    
    if not text_files:
        print("未找到可标注的文本文件")
        return
    
    print("可用的文本文件:")
    for i, file in enumerate(text_files, 1):
        print(f"  {i}. {file}")
    
    while True:
        try:
            choice = int(input(f"请选择文件 (1-{len(text_files)}): ")) - 1
            if 0 <= choice < len(text_files):
                selected_file = text_files[choice]
                break
            else:
                print("选择超出范围")
        except ValueError:
            print("请输入有效数字")
    
    print(f"已选择文件: {selected_file}")
    
    # 读取文件内容
    with open(selected_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    # 分割段落
    scorer = ParagraphScorer()
    paragraphs = scorer.split_into_paragraphs(text)
    
    print(f"\n文件分割为 {len(paragraphs)} 个段落")
    
    # 开始标注
    annotations = scorer.manual_annotation_interface(paragraphs)
    
    if annotations:
        # 保存标注
        output_file = f"bert_excitation_train/data/training/annotations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        scorer.save_annotations(annotations, output_file)
        
        print(f"\n标注完成！共标注了 {len(annotations)} 个段落")
        print(f"标注数据已保存到: {output_file}")
        
        # 显示标注统计
        scores = [ann['user_score'] for ann in annotations]
        print(f"\n标注统计:")
        print(f"  平均分: {sum(scores)/len(scores):.2f}")
        print(f"  最高分: {max(scores)}")
        print(f"  最低分: {min(scores)}")
        
        # 询问是否训练模型
        train_choice = input("\n是否使用这些标注训练模型？(y/n): ").strip().lower()
        if train_choice in ['y', 'yes']:
            if scorer.train_model(annotations):
                print("模型训练完成！")
            else:
                print("模型训练失败")
    else:
        print("没有进行任何标注")

def batch_annotation():
    """批量标注多个文件"""
    print("=" * 80)
    print("批量标注工具")
    print("=" * 80)
    
    # 查找所有可标注的文件
    text_files = []
    for root, dirs, files in os.walk('.'):
        for file in files:
            if file.endswith('.txt') and ('generated' in root or 'chapters' in root):
                text_files.append(os.path.join(root, file))
    
    if not text_files:
        print("未找到可标注的文本文件")
        return
    
    print(f"找到 {len(text_files)} 个文件")
    
    all_annotations = []
    scorer = ParagraphScorer()
    
    for i, file_path in enumerate(text_files, 1):
        print(f"\n处理文件 {i}/{len(text_files)}: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
        
        paragraphs = scorer.split_into_paragraphs(text)
        
        if len(paragraphs) == 0:
            print("  跳过：没有有效段落")
            continue
        
        print(f"  分割为 {len(paragraphs)} 个段落")
        
        # 只标注前3个段落（避免标注时间过长）
        sample_paragraphs = paragraphs[:3]
        annotations = scorer.manual_annotation_interface(sample_paragraphs)
        
        # 添加文件信息
        for ann in annotations:
            ann['source_file'] = file_path
        
        all_annotations.extend(annotations)
        
        if i < len(text_files):
            continue_choice = input("继续下一个文件？(y/n): ").strip().lower()
            if continue_choice not in ['y', 'yes']:
                break
    
    if all_annotations:
        # 保存所有标注
        output_file = f"bert_excitation_train/data/training/batch_annotations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        scorer.save_annotations(all_annotations, output_file)
        
        print(f"\n批量标注完成！共标注了 {len(all_annotations)} 个段落")
        print(f"标注数据已保存到: {output_file}")
        
        # 显示统计
        scores = [ann['user_score'] for ann in all_annotations]
        print(f"\n总体统计:")
        print(f"  平均分: {sum(scores)/len(scores):.2f}")
        print(f"  最高分: {max(scores)}")
        print(f"  最低分: {min(scores)}")
        
        # 按文件统计
        file_stats = {}
        for ann in all_annotations:
            file_name = os.path.basename(ann['source_file'])
            if file_name not in file_stats:
                file_stats[file_name] = []
            file_stats[file_name].append(ann['user_score'])
        
        print(f"\n按文件统计:")
        for file_name, file_scores in file_stats.items():
            print(f"  {file_name}: 平均分 {sum(file_scores)/len(file_scores):.2f} ({len(file_scores)}个段落)")

def main():
    """主函数"""
    print("段落级评分系统 - 交互式标注工具")
    print("=" * 80)
    
    while True:
        print("\n请选择操作:")
        print("1. 交互式标注单个文件")
        print("2. 批量标注多个文件")
        print("3. 训练评分模型")
        print("4. 评估段落评分")
        print("5. 退出")
        
        choice = input("请输入选择 (1-5): ").strip()
        
        if choice == '1':
            interactive_annotation()
        elif choice == '2':
            batch_annotation()
        elif choice == '3':
            train_model()
        elif choice == '4':
            evaluate_paragraphs()
        elif choice == '5':
            print("退出程序")
            break
        else:
            print("无效选择，请重新输入")

def train_model():
    """训练模型"""
    print("训练评分模型")
    print("=" * 40)
    
    # 查找标注文件
    annotation_files = []
    for root, dirs, files in os.walk('bert_excitation_train/data/training'):
        for file in files:
            if file.startswith('annotations_') and file.endswith('.json'):
                annotation_files.append(os.path.join(root, file))
    
    if not annotation_files:
        print("未找到标注文件")
        return
    
    print("可用的标注文件:")
    for i, file in enumerate(annotation_files, 1):
        print(f"  {i}. {file}")
    
    # 合并所有标注
    all_annotations = []
    scorer = ParagraphScorer()
    
    for file_path in annotation_files:
        annotations = scorer.load_annotations(file_path)
        all_annotations.extend(annotations)
    
    print(f"总共加载了 {len(all_annotations)} 个标注")
    
    if scorer.train_model(all_annotations):
        print("模型训练完成！")
        
        # 保存合并的标注和模型
        merged_file = f"bert_excitation_train/data/training/merged_annotations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        scorer.save_annotations(all_annotations, merged_file)
    else:
        print("模型训练失败")

def evaluate_paragraphs():
    """评估段落"""
    print("评估段落评分")
    print("=" * 40)
    
    # 选择要评估的文件
    text_files = []
    for root, dirs, files in os.walk('.'):
        for file in files:
            if file.endswith('.txt') and ('generated' in root or 'chapters' in root):
                text_files.append(os.path.join(root, file))
    
    if not text_files:
        print("未找到可评估的文本文件")
        return
    
    print("可用的文本文件:")
    for i, file in enumerate(text_files, 1):
        print(f"  {i}. {file}")
    
    try:
        choice = int(input(f"请选择文件 (1-{len(text_files)}): ")) - 1
        if 0 <= choice < len(text_files):
            selected_file = text_files[choice]
        else:
            print("选择超出范围")
            return
    except ValueError:
        print("请输入有效数字")
        return
    
    # 评估段落
    scorer = ParagraphScorer()
    
    with open(selected_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    results = scorer.evaluate_paragraphs(text)
    
    # 保存结果
    output_file = selected_file.replace('.txt', '_evaluation.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"评估结果已保存到: {output_file}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
处理通用样本库，支持多种小说项目
将通用样本向量化并建立检索系统
"""

import os
import torch
import re
import numpy as np
import json
from transformers import AutoTokenizer, AutoModel

# 根目录（以当前脚本所在目录为基准，自动定位到项目根目录）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# 配置：直接使用本机已下载好的 bge_large_zh 模型绝对路径（避免被当作 HuggingFace 仓库名）
model_path = r"D:\Study\College\Scientific research\张颖——AI小说自动生成\张颖——AI小说自动生成\bert_excitation_train\AI_Novle\bge_large_zh"
device = "cuda" if torch.cuda.is_available() else "cpu"

# 加载模型
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModel.from_pretrained(model_path, use_safetensors=True).to(device).eval()

def batch_vectorize(texts, batch_size=32):
    """批量向量化文本"""
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        inputs = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt"
        ).to(device)

        with torch.inference_mode():
            outputs = model(**inputs)
            embeddings = outputs.last_hidden_state[:, 0]
            embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)

        all_embeddings.append(embeddings.cpu().numpy())

    return np.vstack(all_embeddings)

def read_universal_samples(file_path):
    """读取通用样本文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    except FileNotFoundError:
        print(f"错误：文件 {file_path} 不存在")
        exit(1)
    except Exception as e:
        print(f"读取文件时出错: {e}")
        exit(1)

def parse_universal_samples(content):
    """
    解析通用样本文件（新的多标签格式）
    返回: [{"title": "武侠对决-1", "content": "...", "emotion_tags": [...], ...}, ...]
    """
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
                'score': 85.0,  # 默认评分
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
                # 合并所有标签用于兼容性
                all_tags = (sample_data['emotion_tags'] + 
                           sample_data['scene_tags'] + 
                           sample_data['conflict_tags'] + 
                           sample_data['action_tags'] + 
                           sample_data['plot_tags'])
                
                samples.append({
                    "title": sample_data['title'],
                    "category": sample_data['title'],  # 使用标题作为类别
                    "content": sample_data['content'],
                    "score": sample_data['score'],
                    "emotion_tags": sample_data['emotion_tags'],
                    "scene_tags": sample_data['scene_tags'],
                    "conflict_tags": sample_data['conflict_tags'],
                    "action_tags": sample_data['action_tags'],
                    "plot_tags": sample_data['plot_tags'],
                    "tags": list(set(all_tags)),  # 所有标签的集合
                    "is_universal": True
                })
            continue
        
        i += 1
    
    return samples

def extract_tags(text, category):
    """从文本中提取标签"""
    tags = [category]
    
    # 基于内容提取标签
    if any(word in text for word in ['爱', '情', '心', '手', '眼', '笑', '哭', '拥', '抱']):
        tags.append('情感')
    if any(word in text for word in ['悬', '疑', '秘', '密', '线', '索', '推', '理', '侦', '探']):
        tags.append('悬疑')
    if any(word in text for word in ['冒', '险', '探', '索', '寻', '宝', '古', '老', '神', '秘']):
        tags.append('冒险')
    if any(word in text for word in ['朝', '堂', '政', '治', '权', '谋', '阴', '谋', '斗', '争']):
        tags.append('权谋')
    if any(word in text for word in ['修', '炼', '真', '气', '境', '界', '仙', '侠', '法', '术']):
        tags.append('仙侠')
    if any(word in text for word in ['现', '代', '都', '市', '办', '公', '室', '公', '司', '商', '业']):
        tags.append('现代')
    if any(word in text for word in ['古', '装', '宫', '廷', '皇', '帝', '皇', '后', '妃', '子']):
        tags.append('古装')
    if any(word in text for word in ['科', '幻', '未', '来', '太', '空', '外', '星', '飞', '船']):
        tags.append('科幻')
    
    return list(set(tags))  # 去重

# 主流程
if __name__ == "__main__":
    # 读取通用样本内容（路径相对于项目根目录，而不是当前运行目录）
    universal_file_path = os.path.join(DATA_DIR, "universal_samples.txt")
    content = read_universal_samples(universal_file_path)

    # 解析文本 -> 样本列表
    samples = parse_universal_samples(content)

    if not samples:
        print("没有提取到有效的样本，程序退出！")
        exit()

    print(f"成功解析 {len(samples)} 个通用样本")

    # 提取每条的 category+content 作为向量化输入
    texts = [f"{s['category']}：{s['content']}" for s in samples]

    # 批量向量化
    try:
        vectors = batch_vectorize(texts)
        print(f"向量化完成，特征维度: {vectors.shape}")
    except Exception as e:
        print(f"向量化过程中出错: {e}")
        exit(1)

    # 保存结果
    try:
        # 确保 data 目录存在（第一次运行可能还没有）
        os.makedirs(DATA_DIR, exist_ok=True)

        vectors_path = os.path.join(DATA_DIR, 'universal_samples_vectors.npy')
        meta_path = os.path.join(DATA_DIR, 'universal_samples_data.json')

        np.save(vectors_path, vectors)

        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump({
                "samples": samples,
                "count": len(samples),
                "categories": list(set(s['category'] for s in samples)),
                "tags": list(set(tag for s in samples for tag in s['tags']))
            }, f, ensure_ascii=False, indent=4)

        print(f"成功保存通用样本向量和内容")
        print(f"样本分类统计:")
        categories = {}
        for sample in samples:
            cat = sample['category']
            categories[cat] = categories.get(cat, 0) + 1
        
        for cat, count in categories.items():
            print(f"  {cat}: {count} 个样本")
            
        print(f"\n标签统计:")
        all_tags = {}
        for sample in samples:
            for tag in sample['tags']:
                all_tags[tag] = all_tags.get(tag, 0) + 1
        
        for tag, count in sorted(all_tags.items(), key=lambda x: x[1], reverse=True):
            print(f"  {tag}: {count} 次")
            
    except Exception as e:
        print(f"保存结果时出错: {e}")
        exit(1)

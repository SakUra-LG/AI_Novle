#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能样本搜索和修改系统
支持多种小说项目的样本检索和内容适配
"""

import torch
import numpy as np
import json
import re
from transformers import AutoTokenizer, AutoModel
from sklearn.metrics.pairwise import cosine_similarity

# 配置
model_path = "./细节生成资料/bge_large_zh"
device = "cuda" if torch.cuda.is_available() else "cpu"

# 加载模型
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModel.from_pretrained(model_path, use_safetensors=True).to(device).eval()

def vectorize_text(text):
    """将文本转换为向量"""
    inputs = tokenizer(
        text,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt"
    ).to(device)

    with torch.inference_mode():
        outputs = model(**inputs)
        embeddings = outputs.last_hidden_state[:, 0]
        embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)

    return embeddings.cpu().numpy()

def load_universal_samples():
    """加载通用样本库"""
    try:
        # 加载样本向量
        sample_vectors = np.load('data/universal_samples_vectors.npy')

        # 加载样本内容
        with open('data/universal_samples_data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            samples = data.get("samples", [])

        # 验证一致性
        if len(samples) != sample_vectors.shape[0]:
            print(f"数据不匹配：样本数({len(samples)}) ≠ 向量数({sample_vectors.shape[0]})")
            return None, None

        return sample_vectors, samples
    except Exception as e:
        print(f"加载样本库时出错: {e}")
        return None, None

def find_similar_samples(query, sample_vectors, samples, top_k=5, min_similarity=0.3, 
                        required_tags=None, min_score=None):
    """
    查找相似样本（支持多标签过滤）
    
    参数：
        query: 查询文本
        sample_vectors: 样本向量
        samples: 样本列表
        top_k: 返回前k个结果
        min_similarity: 最小相似度阈值
        required_tags: 必需的标签（字典），例如 {'emotion_tags': ['紧张', '恐惧']}
        min_score: 最低评分要求
    """
    # 向量化查询
    query_vector = vectorize_text(query)
    
    # 计算相似度
    similarities = cosine_similarity(query_vector, sample_vectors)[0]
    
    # 筛选相似度大于阈值的样本
    valid_indices = np.where(similarities >= min_similarity)[0]
    
    if len(valid_indices) == 0:
        return []
    
    # 如果指定了标签过滤
    if required_tags:
        filtered_indices = []
        for idx in valid_indices:
            sample = samples[idx]
            match = True
            
            # 检查是否包含必需的标签
            for tag_type, required_values in required_tags.items():
                if tag_type not in sample:
                    match = False
                    break
                
                # 检查是否至少有一个标签匹配
                sample_tags = sample.get(tag_type, [])
                if not any(req_val in sample_tags for req_val in required_values):
                    match = False
                    break
            
            if match:
                filtered_indices.append(idx)
        
        valid_indices = np.array(filtered_indices)
        
        if len(valid_indices) == 0:
            return []
    
    # 如果指定了最低评分
    if min_score is not None:
        filtered_indices = []
        for idx in valid_indices:
            sample = samples[idx]
            if sample.get('score', 0) >= min_score:
                filtered_indices.append(idx)
        
        valid_indices = np.array(filtered_indices)
        
        if len(valid_indices) == 0:
            return []
    
    # 按相似度排序
    sorted_indices = valid_indices[np.argsort(similarities[valid_indices])[::-1]]
    
    results = []
    for idx in sorted_indices[:top_k]:
        sample = samples[idx]
        results.append({
            "similarity": float(similarities[idx]),
            "title": sample.get("title", ""),
            "category": sample.get("category", ""),
            "content": sample["content"],
            "emotion_tags": sample.get("emotion_tags", []),
            "scene_tags": sample.get("scene_tags", []),
            "conflict_tags": sample.get("conflict_tags", []),
            "action_tags": sample.get("action_tags", []),
            "plot_tags": sample.get("plot_tags", []),
            "score": sample.get("score", 0)
        })
    
    return results

def adapt_sample_content(sample_content, target_context):
    """适配样本内容到目标上下文"""
    # 这里可以实现智能的内容适配逻辑
    # 例如：替换人物名字、调整背景设定等
    
    adapted_content = sample_content
    
    # 简单的适配示例（可以根据需要扩展）
    if "陈雪" in adapted_content and "林峰" in target_context:
        adapted_content = adapted_content.replace("陈雪", "林峰")
    elif "林峰" in adapted_content and "陈雪" in target_context:
        adapted_content = adapted_content.replace("林峰", "陈雪")
    
    return adapted_content

def search_and_adapt_samples(user_input, target_context="", top_k=3, min_similarity=0.3):
    """搜索并适配样本"""
    # 加载样本库
    sample_vectors, samples = load_universal_samples()
    if sample_vectors is None:
        print("请先运行 handle_universal_samples.py 初始化样本库")
        return None

    print(f"样本库已加载，包含 {len(samples)} 个通用样本")

    try:
        # 查找相似样本
        similar_samples = find_similar_samples(
            user_input, sample_vectors, samples, top_k, min_similarity
        )
        
        if not similar_samples:
            print("未找到相似度足够高的样本")
            return None

        print(f"找到 {len(similar_samples)} 个相似样本")
        
        # 适配样本内容
        adapted_samples = []
        for sample in similar_samples:
            adapted_content = adapt_sample_content(sample['content'], target_context)
            adapted_samples.append({
                **sample,
                'adapted_content': adapted_content,
                'original_content': sample['content']
            })
        
        return adapted_samples

    except Exception as e:
        print(f"处理过程中出错: {e}")
        return None

def generate_enhanced_prompt(user_input, adapted_samples, target_context=""):
    """生成增强的提示词"""
    base_prompt = f"""
    角色：你是一个专业的小说作者，擅长创作高质量、高评分的情节内容
    要求：根据下面的要求直接输出创作的情节，不要引入和结局，1000字左右
    提示：如果"参考样本"与问题明显无关，可以完全不参考
    
    目标上下文：{target_context}
    用户需求：{user_input}
    """
    
    if adapted_samples:
        sample_guidance = "\n\n=== 参考高评分样本 ===\n"
        for i, sample in enumerate(adapted_samples, 1):
            sample_guidance += f"""
样本{i} (类别: {sample['category']}, 相似度: {sample['similarity']:.1%}, 标签: {', '.join(sample['tags'])}):
原始内容: {sample['original_content']}
适配内容: {sample['adapted_content']}

"""
        
        sample_guidance += """
请参考以上高评分样本的结构、语言风格和情节设计，结合目标上下文，创作出同样高质量的内容。
特别注意：
1. 保持与目标上下文的一致性
2. 借鉴样本的写作技巧和情节结构
3. 确保人物设定和背景设定符合目标项目
"""
        
        base_prompt += sample_guidance
    
    return base_prompt

def main():
    """主函数 - 演示智能样本搜索"""
    print("=" * 60)
    print("智能样本搜索和修改系统")
    print("=" * 60)
    
    # 测试查询
    test_queries = [
        {
            "query": "请写一段武侠对决的情节",
            "context": "主角是林峰，背景是现代都市"
        },
        {
            "query": "创作一个悬疑推理的情节",
            "context": "主角是陈雪，背景是古代宫廷"
        },
        {
            "query": "写一段情感互动的场景",
            "context": "主角是张伟，背景是科幻未来"
        }
    ]
    
    for i, test in enumerate(test_queries, 1):
        print(f"\n测试 {i}: {test['query']}")
        print(f"目标上下文: {test['context']}")
        
        # 搜索和适配样本
        adapted_samples = search_and_adapt_samples(
            test['query'], 
            test['context'], 
            top_k=2, 
            min_similarity=0.3
        )
        
        if adapted_samples:
            print(f"找到 {len(adapted_samples)} 个适配样本")
            
            # 生成增强提示词
            enhanced_prompt = generate_enhanced_prompt(
                test['query'], 
                adapted_samples, 
                test['context']
            )
            
            print("\n增强提示词预览:")
            print("-" * 40)
            print(enhanced_prompt[:500] + "..." if len(enhanced_prompt) > 500 else enhanced_prompt)
        else:
            print("未找到合适的样本")
        
        print("-" * 60)

if __name__ == "__main__":
    main()

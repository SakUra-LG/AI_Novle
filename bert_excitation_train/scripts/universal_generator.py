#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用小说生成器
支持多种小说项目的智能生成
"""

import os
import sys
import json
import re
import dashscope
from datetime import datetime
from smart_sample_search import search_and_adapt_samples, generate_enhanced_prompt

# 配置API
API_Key_QW = "sk-a2966f4e37134351904851679884cb67"
MAX_TOKENS = 8192

def load_project_config(project_name):
    """加载项目配置"""
    try:
        with open('config/project_configs.json', 'r', encoding='utf-8') as f:
            configs = json.load(f)
            return configs['projects'].get(project_name, configs['projects'][configs['default_project']])
    except Exception as e:
        print(f"加载项目配置失败: {e}")
        return None

def clean_markdown(text):
    """去除 Markdown 格式符号"""
    if not text:
        return ""
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'### (.*)', r'\1', text)
    text = re.sub(r'---', '', text)
    return text.strip()

def call_qianwen_api(messages, temperature=0.85, top_p=0.8, repetition_penalty=1.1):
    """调用通义千问API"""
    dashscope.api_key = API_Key_QW
    try:
        response = dashscope.Generation.call(
            model=dashscope.Generation.Models.qwen_turbo,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            result_format='message'
        )

        if 'output' in response and 'choices' in response['output']:
            return response['output']['choices'][0]['message']['content']
        else:
            return f"通义千问 API 返回了无效格式: {str(response)}"
    except Exception as e:
        return f"调用通义千问 API 出错: {str(e)}"

def generate_with_universal_samples(project_name, chapter_num, user_input, num_versions=3):
    """使用通用样本生成章节"""
    print(f"开始为项目 '{project_name}' 生成第{chapter_num}章...")
    
    # 加载项目配置
    project_config = load_project_config(project_name)
    if not project_config:
        print(f"项目 '{project_name}' 配置不存在")
        return []
    
    print(f"项目配置: {project_config['description']}")
    print(f"主角: {project_config['main_character']}")
    print(f"背景: {project_config['background']}")
    
    # 构建目标上下文
    target_context = f"主角: {project_config['main_character']}, 背景: {project_config['background']}, 风格: {project_config['style']}"
    
    # 搜索和适配样本
    adapted_samples = search_and_adapt_samples(
        user_input, 
        target_context, 
        top_k=3, 
        min_similarity=0.3
    )
    
    if adapted_samples:
        print(f"找到 {len(adapted_samples)} 个适配样本")
        for i, sample in enumerate(adapted_samples, 1):
            print(f"  样本{i}: {sample['category']} (相似度: {sample['similarity']:.1%})")
    else:
        print("未找到适配样本，将使用通用生成")
    
    generated_versions = []
    
    for version in range(1, num_versions + 1):
        print(f"生成第{version}个版本...")
        
        # 生成增强提示词
        enhanced_prompt = generate_enhanced_prompt(user_input, adapted_samples, target_context)
        
        # 构建系统消息
        system_message = {
            "role": "system",
            "content": enhanced_prompt
        }
        
        # 用户消息
        user_message = {"role": "user", "content": user_input}
        
        # 调用 API
        reply = call_qianwen_api([system_message, user_message])
        cleaned_reply = clean_markdown(reply)
        
        if cleaned_reply:
            generated_versions.append({
                'version': version,
                'content': cleaned_reply,
                'project': project_name,
                'chapter': chapter_num,
                'generated_at': datetime.now().isoformat()
            })
            print(f"版本{version}生成完成")
        else:
            print(f"版本{version}生成失败")
    
    return generated_versions

def save_generated_versions(project_name, chapter_num, versions, output_dir="data/generated"):
    """保存生成的版本"""
    project_dir = os.path.join(output_dir, project_name)
    os.makedirs(project_dir, exist_ok=True)
    
    for version in versions:
        filename = f"ch{chapter_num}_v{version['version']}.txt"
        filepath = os.path.join(project_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(version['content'])
        
        print(f"版本{version['version']}已保存到: {filepath}")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='通用小说生成器')
    parser.add_argument('--project', type=str, required=True, help='项目名称')
    parser.add_argument('--chapter', type=int, required=True, help='章节号')
    parser.add_argument('--prompt', type=str, required=True, help='生成提示词')
    parser.add_argument('--versions', type=int, default=3, help='生成版本数')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("通用小说生成器")
    print("=" * 60)
    
    # 检查样本库是否存在
    if not os.path.exists('data/universal_samples_vectors.npy'):
        print("通用样本库不存在，请先运行: python scripts/handle_universal_samples.py")
        return
    
    # 生成章节
    versions = generate_with_universal_samples(
        args.project, 
        args.chapter, 
        args.prompt, 
        args.versions
    )
    
    if versions:
        # 保存版本
        save_generated_versions(args.project, args.chapter, versions)
        
        print(f"\n{args.project} 第{args.chapter}章生成完成！")
        print(f"共生成了 {len(versions)} 个版本")
        
        # 显示版本预览
        for version in versions:
            print(f"\n版本{version['version']}预览:")
            print("-" * 40)
            print(version['content'][:200] + "..." if len(version['content']) > 200 else version['content'])
    else:
        print("生成失败！")

if __name__ == "__main__":
    main()

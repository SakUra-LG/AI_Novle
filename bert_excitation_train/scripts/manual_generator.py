#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手动输入生成器
用户手动输入提示词，生成小说内容
"""

import re
import dashscope
from datetime import datetime

# 配置API
API_Key_QW = "sk-a2966f4e37134351904851679884cb67"
MAX_TOKENS = 8192

def clean_markdown(text):
    """去除 Markdown 格式符号"""
    if not text:
        return ""
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # 去除 **
    text = re.sub(r'### (.*)', r'\1', text)       # 去除 ###
    text = re.sub(r'---', '', text)               # 去除 ---
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

def generate_manual(user_input):
    """手动生成内容"""
    print(f"开始生成内容...")
    print(f"用户输入: {user_input}")
    
    # 构建系统提示词
    system_message = {
        "role": "system",
        "content": f"""
        角色：你是一个专业的小说作者，擅长创作高质量、高评分的情节内容
        限制：根据下面的要求直接输出创作的情节，不要引入和结局，1000字左右
        
        要求：{user_input}"""
    }
    
    # 用户消息
    user_message = {"role": "user", "content": user_input}
    
    # 调用 API
    reply = call_qianwen_api([system_message, user_message])
    cleaned_reply = clean_markdown(reply)
    
    return cleaned_reply

def save_generated_content(content, filename=None):
    """保存生成的内容"""
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"generated_{timestamp}.txt"
    
    import os
    os.makedirs('outputs', exist_ok=True)
    filepath = os.path.join('outputs', filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"内容已保存到: {filepath}")
    return filepath

def main():
    """主函数"""
    print("=" * 60)
    print("手动输入生成器")
    print("=" * 60)
    
    while True:
        # 获取用户输入
        print("\n请输入生成要求（输入 'quit' 退出）:")
        user_input = input("> ").strip()
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("退出生成器")
            break
        
        if not user_input:
            print("请输入有效的生成要求")
            continue
        
        try:
            # 生成内容
            content = generate_manual(user_input)
            
            if content:
                print("\n" + "=" * 60)
                print("生成结果:")
                print("=" * 60)
                print(content)
                print("=" * 60)
                
                # 询问是否保存
                save_choice = input("\n是否保存到文件？(y/n): ").strip().lower()
                if save_choice in ['y', 'yes']:
                    filename = input("请输入文件名（留空使用默认名称）: ").strip()
                    if not filename:
                        filename = None
                    save_generated_content(content, filename)
            else:
                print("生成失败，请重试")
                
        except Exception as e:
            print(f"生成过程中出错: {e}")
        
        print("\n" + "-" * 60)

if __name__ == "__main__":
    main()

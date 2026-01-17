#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最终生成脚本
使用训练好的模型生成内容
"""

import os
import sys
import torch
import dashscope
import argparse
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel
import re
from datetime import datetime
from emotion_analyzer import EmotionAnalyzer

# 配置API
API_Key_QW = "sk-a2966f4e37134351904851679884cb67"

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

def load_trained_model(model_path, base_model_name="Qwen/Qwen2.5-0.5B"):
    """加载训练好的模型"""
    print(f"加载基础模型: {base_model_name}")
    tokenizer = AutoTokenizer.from_pretrained(base_model_name)
    
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    
    # 检查是否是LoRA模型
    if os.path.exists(os.path.join(model_path, "adapter_config.json")):
        print("检测到LoRA模型，加载适配器...")
        base_model = AutoModelForCausalLM.from_pretrained(
            base_model_name,
            torch_dtype=torch.float16,
            device_map="auto"
        )
        model = PeftModel.from_pretrained(base_model, model_path)
    else:
        print("加载全参数微调模型...")
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
            device_map="auto"
        )
    
    return model, tokenizer

def generate_with_trained_model(model, tokenizer, prompt, max_length=1000, temperature=0.85):
    """使用训练好的模型生成内容"""
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_length=max_length,
            temperature=temperature,
            top_p=0.8,
            repetition_penalty=1.1,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id
        )
    
    generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
    # 移除输入部分，只返回生成的内容
    generated_text = generated_text[len(prompt):].strip()
    
    return generated_text

def generate_chapter_with_trained_model(chapter_num, prompt, model_path, num_versions=3, use_api=False, min_emotion_intensity=0.6):
    """使用训练好的模型生成章节，确保高情绪强度"""
    print(f"开始生成第{chapter_num}章（目标情绪强度>={min_emotion_intensity}）...")
    
    generated_versions = []
    emotion_analyzer = EmotionAnalyzer()
    
    if use_api:
        # 使用API生成
        print("使用通义千问API生成...")
        for version in range(1, num_versions + 1):
            print(f"生成第{version}个版本...")
            
            system_message = {
                "role": "system",
                "content": f"""
                角色：你是一个专业的小说作者，擅长创作高质量、高评分、高情绪强度的情节内容
                限制：根据下面的要求直接输出创作的情节，不要引入和结局，1000字左右
                
                【核心要求：高情绪强度】
                你必须创作能够"触动心弦"的高情绪强度内容，具体要求：
                1. 情绪强度要求：文本必须包含强烈的情感表达，情绪强度得分应达到0.6以上
                2. 多维度情绪：要包含多种情绪维度（恐惧、紧张、期待、愤怒、悲伤、喜悦等），避免单一情绪
                3. 情绪深度：不仅要有表层情绪（直接表达），更要有深层情绪（通过隐喻、转折、对比等隐含表达）
                4. 情绪转折：文本中要有明显的情绪变化和转折，制造情绪波动（从压迫→焦灼→冷静→决断等）
                5. 情绪密度：每100字至少包含2-3个情绪词汇，情绪句子占比应达到40%以上
                6. 情绪渲染技巧：
                   - 使用具体细节描写增强情绪感染力（如"心跳仿佛要冲出胸腔"而非"很紧张"）
                   - 通过环境描写烘托情绪（如"黑暗的角落"、"急促的脚步声"）
                   - 使用短句和断句制造紧张感
                   - 通过对比和转折增强情绪冲击
                   - 描写身体反应增强代入感（如"手心冒汗"、"呼吸急促"）
                
                要求：{prompt}"""
            }
            
            user_message = {"role": "user", "content": prompt}
            
            reply = call_qianwen_api([system_message, user_message])
            cleaned_reply = clean_markdown(reply)
            
            if cleaned_reply:
                # 评估情绪强度
                emotion_result = emotion_analyzer.analyze(cleaned_reply)
                emotion_intensity = emotion_result.intensity
                
                generated_versions.append({
                    'version': version,
                    'content': cleaned_reply,
                    'generated_at': datetime.now().isoformat(),
                    'emotion_intensity': emotion_intensity,
                    'emotion_label': emotion_result.label
                })
                
                if emotion_intensity >= min_emotion_intensity:
                    print(f"版本{version}生成完成 ✓ 情绪强度: {emotion_intensity:.3f} (达标)")
                else:
                    print(f"版本{version}生成完成 ⚠ 情绪强度: {emotion_intensity:.3f} (未达标，建议重新生成)")
            else:
                print(f"版本{version}生成失败")
    
    else:
        # 使用训练好的模型生成
        print(f"使用训练好的模型生成: {model_path}")
        model, tokenizer = load_trained_model(model_path)
        
        for version in range(1, num_versions + 1):
            print(f"生成第{version}个版本...")
            
            # 构建完整的提示词（加入高情绪强度要求）
            full_prompt = f"""请创作第{chapter_num}章的内容，要求高情绪强度（情绪强度>=0.6，包含多维度情绪，有情绪转折和深度）：

{prompt}

【重要提示】你的创作必须：
1. 包含强烈的情感表达，情绪强度得分应达到0.6以上
2. 包含多种情绪维度（恐惧、紧张、期待、愤怒、悲伤、喜悦等）
3. 有深层情绪表达（通过隐喻、转折、对比等）
4. 有明显的情绪变化和转折
5. 每100字至少包含2-3个情绪词汇
6. 使用具体细节、环境描写、身体反应等技巧增强情绪感染力"""
            
            generated_text = generate_with_trained_model(
                model, tokenizer, full_prompt, max_length=1000, temperature=0.85
            )
            
            if generated_text:
                # 评估情绪强度
                emotion_result = emotion_analyzer.analyze(generated_text)
                emotion_intensity = emotion_result.intensity
                
                generated_versions.append({
                    'version': version,
                    'content': generated_text,
                    'generated_at': datetime.now().isoformat(),
                    'emotion_intensity': emotion_intensity,
                    'emotion_label': emotion_result.label
                })
                
                if emotion_intensity >= min_emotion_intensity:
                    print(f"版本{version}生成完成 ✓ 情绪强度: {emotion_intensity:.3f} (达标)")
                else:
                    print(f"版本{version}生成完成 ⚠ 情绪强度: {emotion_intensity:.3f} (未达标，建议重新生成)")
            else:
                print(f"版本{version}生成失败")
    
    return generated_versions

def save_generated_versions(chapter_num, versions, output_dir="data/candidates"):
    """保存生成的版本"""
    os.makedirs(output_dir, exist_ok=True)
    
    for version in versions:
        filename = f"ch{chapter_num}_v{version['version']}.txt"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(version['content'])
        
        print(f"版本{version['version']}已保存到: {filepath}")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='最终生成脚本')
    parser.add_argument('--chapter', type=int, required=True, help='章节号')
    parser.add_argument('--prompt', type=str, required=True, help='生成提示词')
    parser.add_argument('--model_path', type=str, help='训练好的模型路径')
    parser.add_argument('--versions', type=int, default=3, help='生成版本数')
    parser.add_argument('--use_api', action='store_true', help='使用API而不是训练好的模型')
    parser.add_argument('--min_emotion', type=float, default=0.6, help='最低情绪强度要求（0-1）')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("最终生成脚本")
    print("=" * 60)
    print(f"章节号: {args.chapter}")
    print(f"提示词: {args.prompt}")
    print(f"生成版本数: {args.versions}")
    print(f"使用API: {args.use_api}")
    print()
    
    if not args.use_api and not args.model_path:
        print("[ERROR] 使用训练好的模型需要指定模型路径")
        return
    
    # 生成章节
    versions = generate_chapter_with_trained_model(
        args.chapter, 
        args.prompt, 
        args.model_path, 
        args.versions, 
        args.use_api,
        args.min_emotion
    )
    
    if versions:
        # 保存版本
        save_generated_versions(args.chapter, versions)
        
        print(f"\n第{args.chapter}章生成完成！")
        print(f"共生成了 {len(versions)} 个版本")
        
        # 显示版本预览和情绪分析
        for version in versions:
            print(f"\n版本{version['version']}预览:")
            print("-" * 40)
            emotion_info = f"情绪强度: {version.get('emotion_intensity', 0):.3f}, 情绪标签: {version.get('emotion_label', 'N/A')}"
            print(f"[{emotion_info}]")
            print(version['content'][:200] + "..." if len(version['content']) > 200 else version['content'])
    else:
        print("生成失败！")

if __name__ == "__main__":
    main()

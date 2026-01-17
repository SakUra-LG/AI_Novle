#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
情绪引导生成器
使用情绪分析器实时引导生成过程，确保生成高情绪强度的文本
"""

import os
import sys
import dashscope
import argparse
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

def build_emotion_enhanced_prompt(base_prompt, emotion_feedback=None):
    """构建情绪增强的提示词"""
    prompt = f"""
角色：你是一个专业的小说作者，擅长创作高情绪强度、能够"触动心弦"的情节内容

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

【生成任务】
{base_prompt}
"""
    
    # 如果有情绪反馈，添加改进建议
    if emotion_feedback:
        prompt += f"""
【情绪强度改进建议】
根据上一次生成的情绪分析结果，请特别注意以下方面：
- 当前情绪强度: {emotion_feedback.get('intensity', 0):.3f} (目标 >= 0.6)
- 主导情绪: {emotion_feedback.get('label', 'N/A')}
- 建议: {emotion_feedback.get('suggestion', '请增强情绪表达，使用更多情绪词汇和细节描写')}
"""
    
    return prompt

def analyze_emotion_and_suggest(text, emotion_analyzer):
    """分析情绪并提供改进建议"""
    result = emotion_analyzer.analyze(text)
    
    suggestions = []
    
    # 检查情绪强度
    if result.intensity < 0.6:
        suggestions.append("情绪强度不足，建议增加更多情绪词汇和细节描写")
    
    # 检查情绪维度
    if result.emotion_dimensions:
        dominant_emotions = sorted(result.emotion_dimensions.items(), key=lambda x: x[1], reverse=True)[:3]
        if len(dominant_emotions) < 2:
            suggestions.append("情绪维度单一，建议增加多种情绪的表达")
    
    # 检查情绪深度
    if result.emotion_depth < 0.4:
        suggestions.append("情绪深度不足，建议使用隐喻、转折、对比等手法表达深层情绪")
    
    # 检查情绪转折
    if result.emotion_transition == 'stable':
        suggestions.append("情绪变化不明显，建议增加情绪转折和波动")
    
    # 检查情绪密度
    if result.emotion_word_density < 0.02:
        suggestions.append("情绪词汇密度不足，建议每100字至少包含2-3个情绪词汇")
    
    suggestion = "；".join(suggestions) if suggestions else "情绪表达良好，可以继续保持"
    
    return {
        'intensity': result.intensity,
        'label': result.label,
        'suggestion': suggestion,
        'emotion_dimensions': result.emotion_dimensions,
        'emotion_depth': result.emotion_depth,
        'emotion_transition': result.emotion_transition
    }

def generate_with_emotion_guidance(chapter_num, prompt, num_versions=3, min_emotion_intensity=0.6, max_retries=2):
    """使用情绪引导生成章节"""
    print(f"🎭 启动情绪引导生成器")
    print(f"📄 章节: {chapter_num}")
    print(f"🎯 目标情绪强度: >= {min_emotion_intensity}")
    print(f"🔄 最大重试次数: {max_retries}")
    print("=" * 60)
    
    emotion_analyzer = EmotionAnalyzer()
    generated_versions = []
    
    for version in range(1, num_versions + 1):
        print(f"\n生成版本 {version}/{num_versions}...")
        
        best_result = None
        best_intensity = 0
        emotion_feedback = None
        
        # 尝试生成，如果情绪强度不够就重试
        for attempt in range(max_retries + 1):
            if attempt > 0:
                print(f"  重试 {attempt}/{max_retries} (上次情绪强度: {best_intensity:.3f})...")
            
            # 构建提示词
            system_prompt = build_emotion_enhanced_prompt(
                f"请创作第{chapter_num}章的内容：{prompt}",
                emotion_feedback
            )
            
            system_message = {"role": "system", "content": system_prompt}
            user_message = {"role": "user", "content": prompt}
            
            # 生成内容
            reply = call_qianwen_api([system_message, user_message])
            cleaned_reply = clean_markdown(reply)
            
            if not cleaned_reply:
                print(f"  ❌ 生成失败")
                continue
            
            # 分析情绪
            emotion_feedback = analyze_emotion_and_suggest(cleaned_reply, emotion_analyzer)
            intensity = emotion_feedback['intensity']
            
            print(f"  情绪强度: {intensity:.3f}, 情绪标签: {emotion_feedback['label']}")
            
            # 如果情绪强度达标，或者这是最后一次尝试，保存结果
            if intensity >= min_emotion_intensity or attempt == max_retries:
                if intensity > best_intensity:
                    best_result = {
                        'version': version,
                        'content': cleaned_reply,
                        'emotion_intensity': intensity,
                        'emotion_label': emotion_feedback['label'],
                        'emotion_dimensions': emotion_feedback['emotion_dimensions'],
                        'emotion_depth': emotion_feedback['emotion_depth'],
                        'emotion_transition': emotion_feedback['emotion_transition'],
                        'attempts': attempt + 1,
                        'generated_at': datetime.now().isoformat()
                    }
                    best_intensity = intensity
                
                if intensity >= min_emotion_intensity:
                    print(f"  ✅ 情绪强度达标！")
                    break
            else:
                # 保存当前最佳结果（即使未达标）
                if intensity > best_intensity:
                    best_result = {
                        'version': version,
                        'content': cleaned_reply,
                        'emotion_intensity': intensity,
                        'emotion_label': emotion_feedback['label'],
                        'emotion_dimensions': emotion_feedback['emotion_dimensions'],
                        'emotion_depth': emotion_feedback['emotion_depth'],
                        'emotion_transition': emotion_feedback['emotion_transition'],
                        'attempts': attempt + 1,
                        'generated_at': datetime.now().isoformat()
                    }
                    best_intensity = intensity
        
        if best_result:
            generated_versions.append(best_result)
            status = "✅" if best_intensity >= min_emotion_intensity else "⚠️"
            print(f"版本{version}完成 {status} 最终情绪强度: {best_intensity:.3f} (尝试{best_result['attempts']}次)")
        else:
            print(f"版本{version}生成失败")
    
    return generated_versions

def save_generated_versions(chapter_num, versions, output_dir="data/candidates"):
    """保存生成的版本"""
    os.makedirs(output_dir, exist_ok=True)
    
    for version in versions:
        filename = f"ch{chapter_num}_v{version['version']}_emotion.txt"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(version['content'])
        
        print(f"版本{version['version']}已保存到: {filepath}")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='情绪引导生成器')
    parser.add_argument('--chapter', type=int, required=True, help='章节号')
    parser.add_argument('--prompt', type=str, required=True, help='生成提示词')
    parser.add_argument('--versions', type=int, default=3, help='生成版本数')
    parser.add_argument('--min_emotion', type=float, default=0.6, help='最低情绪强度要求（0-1）')
    parser.add_argument('--max_retries', type=int, default=2, help='每个版本的最大重试次数')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("情绪引导生成器")
    print("=" * 60)
    
    # 生成章节
    versions = generate_with_emotion_guidance(
        args.chapter, 
        args.prompt, 
        args.versions,
        args.min_emotion,
        args.max_retries
    )
    
    if versions:
        # 保存版本
        save_generated_versions(args.chapter, versions)
        
        print(f"\n第{args.chapter}章生成完成！")
        print(f"共生成了 {len(versions)} 个版本")
        
        # 显示版本预览和情绪分析
        for version in versions:
            print(f"\n版本{version['version']} (尝试{version['attempts']}次):")
            print("-" * 60)
            print(f"情绪强度: {version['emotion_intensity']:.3f}")
            print(f"情绪标签: {version['emotion_label']}")
            print(f"情绪深度: {version['emotion_depth']:.3f}")
            print(f"情绪转折: {version['emotion_transition']}")
            print(f"内容预览:")
            print(version['content'][:200] + "..." if len(version['content']) > 200 else version['content'])
    else:
        print("生成失败！")

if __name__ == "__main__":
    main()


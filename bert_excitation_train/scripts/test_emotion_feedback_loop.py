#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
情绪反馈循环测试脚本
用于测试"生成-评估-反馈-优化"流程是否能提升情绪强度

使用方法：
    python scripts/test_emotion_feedback_loop.py
"""

import os
import sys
import dashscope
import re
import json
import pandas as pd
import hashlib
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
    text = re.sub(r'#+', '', text)
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

def build_emotion_enhanced_prompt(base_prompt, emotion_feedback=None, iteration=0):
    """构建情绪增强的提示词"""
    if iteration == 0:
        # 第一次生成，不带反馈
        prompt = f"""
角色：你是一个专业的小说作者，擅长创作高情绪强度、能够"触动心弦"的情节片段

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
请根据以下提示创作一个独立的小说片段（500-800字）：
{base_prompt}

要求：直接输出创作的内容，不要添加标题、说明或总结。
"""
    else:
        # 后续迭代，带反馈
        prompt = f"""
角色：你是一个专业的小说作者，擅长创作高情绪强度、能够"触动心弦"的情节片段

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
请根据以下提示创作一个独立的小说片段（500-800字）：
{base_prompt}

【情绪强度改进建议 - 第{iteration}次优化】
根据上一次生成的情绪分析结果，请特别注意以下方面：
- 当前情绪强度: {emotion_feedback.get('intensity', 0):.3f} (目标 >= 0.6)
- 主导情绪: {emotion_feedback.get('label', 'N/A')}
- 情绪深度: {emotion_feedback.get('emotion_depth', 0):.3f}
- 情绪转折: {emotion_feedback.get('emotion_transition', 'N/A')}
- 情绪密度: {emotion_feedback.get('emotion_word_density', 0):.3f}
- 具体改进建议: {emotion_feedback.get('suggestion', '请增强情绪表达，使用更多情绪词汇和细节描写')}

请根据以上反馈，重新创作一个情绪强度更高的版本。重点改进情绪表达，使用更多情绪词汇、细节描写和情绪转折。

要求：直接输出创作的内容，不要添加标题、说明或总结。
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
        'emotion_transition': result.emotion_transition,
        'emotion_word_density': result.emotion_word_density,
        'emotion_sentence_density': result.emotion_sentence_density,
        'emotion_complexity': result.emotion_complexity,
    }

def test_feedback_loop(user_prompt, max_iterations=3, min_emotion_intensity=0.6):
    """测试反馈循环流程"""
    print("=" * 80)
    print("🎭 情绪反馈循环测试")
    print("=" * 80)
    print(f"📝 用户提示词: {user_prompt}")
    print(f"🎯 目标情绪强度: >= {min_emotion_intensity}")
    print(f"🔄 最大迭代次数: {max_iterations}")
    print("=" * 80)
    
    emotion_analyzer = EmotionAnalyzer()
    all_iterations = []
    
    emotion_feedback = None
    
    for iteration in range(max_iterations):
        print(f"\n{'='*80}")
        print(f"🔄 第 {iteration + 1} 次迭代")
        print(f"{'='*80}")
        
        # 构建提示词
        system_prompt = build_emotion_enhanced_prompt(
            user_prompt,
            emotion_feedback,
            iteration
        )
        
        system_message = {"role": "system", "content": system_prompt}
        user_message = {"role": "user", "content": user_prompt}
        
        # 生成内容
        print("📤 正在生成内容...")
        reply = call_qianwen_api([system_message, user_message])
        cleaned_reply = clean_markdown(reply)
        
        if not cleaned_reply or cleaned_reply.startswith("通义千问 API"):
            print(f"❌ 生成失败: {cleaned_reply}")
            continue
        
        # 分析情绪
        print("🔍 正在分析情绪...")
        emotion_feedback = analyze_emotion_and_suggest(cleaned_reply, emotion_analyzer)
        intensity = emotion_feedback['intensity']
        
        # 保存迭代结果
        iteration_result = {
            'iteration': iteration + 1,
            'content': cleaned_reply,
            'emotion_intensity': intensity,
            'emotion_label': emotion_feedback['label'],
            'emotion_dimensions': emotion_feedback['emotion_dimensions'],
            'emotion_depth': emotion_feedback['emotion_depth'],
            'emotion_transition': emotion_feedback['emotion_transition'],
            'emotion_word_density': emotion_feedback['emotion_word_density'],
            'emotion_sentence_density': emotion_feedback['emotion_sentence_density'],
            'emotion_complexity': emotion_feedback['emotion_complexity'],
            'suggestion': emotion_feedback['suggestion'],
            'generated_at': datetime.now().isoformat()
        }
        all_iterations.append(iteration_result)
        
        # 显示结果
        print(f"\n📊 情绪分析结果:")
        print(f"   情绪强度: {intensity:.3f} {'✅' if intensity >= min_emotion_intensity else '⚠️'}")
        print(f"   情绪标签: {emotion_feedback['label']}")
        print(f"   情绪深度: {emotion_feedback['emotion_depth']:.3f}")
        print(f"   情绪转折: {emotion_feedback['emotion_transition']}")
        print(f"   情绪密度: {emotion_feedback['emotion_word_density']:.3f}")
        print(f"   情绪复杂度: {emotion_feedback['emotion_complexity']:.3f}")
        print(f"   改进建议: {emotion_feedback['suggestion']}")
        
        print(f"\n📄 生成内容预览 (前200字):")
        print("-" * 80)
        preview = cleaned_reply[:200] + "..." if len(cleaned_reply) > 200 else cleaned_reply
        print(preview)
        print("-" * 80)
        
        # 如果达标，可以选择继续或停止
        if intensity >= min_emotion_intensity:
            print(f"\n✅ 情绪强度已达标！")
            if iteration < max_iterations - 1:
                print("💡 提示: 可以继续迭代以进一步提升情绪强度")
        
        # 如果不是最后一次迭代，显示对比
        if iteration > 0:
            prev_intensity = all_iterations[iteration - 1]['emotion_intensity']
            improvement = intensity - prev_intensity
            if improvement > 0:
                print(f"\n📈 情绪强度提升: +{improvement:.3f} (从 {prev_intensity:.3f} 提升到 {intensity:.3f})")
            elif improvement < 0:
                print(f"\n📉 情绪强度下降: {improvement:.3f} (从 {prev_intensity:.3f} 下降到 {intensity:.3f})")
            else:
                print(f"\n➡️ 情绪强度持平: {intensity:.3f}")
    
    # 总结
    print(f"\n{'='*80}")
    print("📊 测试总结")
    print(f"{'='*80}")
    
    if all_iterations:
        intensities = [it['emotion_intensity'] for it in all_iterations]
        best_iteration = max(range(len(all_iterations)), key=lambda i: intensities[i])
        worst_iteration = min(range(len(all_iterations)), key=lambda i: intensities[i])
        
        print(f"总迭代次数: {len(all_iterations)}")
        print(f"最高情绪强度: {intensities[best_iteration]:.3f} (第{best_iteration + 1}次迭代)")
        print(f"最低情绪强度: {intensities[worst_iteration]:.3f} (第{worst_iteration + 1}次迭代)")
        print(f"平均情绪强度: {sum(intensities) / len(intensities):.3f}")
        print(f"情绪强度变化: {intensities[-1] - intensities[0]:.3f} (从 {intensities[0]:.3f} 到 {intensities[-1]:.3f})")
        
        if intensities[-1] > intensities[0]:
            print(f"✅ 反馈循环成功提升了情绪强度！")
        elif intensities[-1] < intensities[0]:
            print(f"⚠️ 反馈循环未能提升情绪强度")
        else:
            print(f"➡️ 情绪强度基本持平")
    
    return all_iterations

def save_test_results(user_prompt, iterations, output_dir="data/test_results"):
    """保存测试结果"""
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 保存JSON格式
    json_file = os.path.join(output_dir, f"test_result_{timestamp}.json")
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump({
            'user_prompt': user_prompt,
            'iterations': iterations,
            'timestamp': timestamp
        }, f, ensure_ascii=False, indent=2)
    
    # 保存文本格式（便于阅读）
    txt_file = os.path.join(output_dir, f"test_result_{timestamp}.txt")
    with open(txt_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("情绪反馈循环测试结果\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"用户提示词: {user_prompt}\n")
        f.write(f"测试时间: {timestamp}\n")
        f.write(f"迭代次数: {len(iterations)}\n\n")
        
        for it in iterations:
            f.write(f"{'='*80}\n")
            f.write(f"第 {it['iteration']} 次迭代\n")
            f.write(f"{'='*80}\n")
            f.write(f"情绪强度: {it['emotion_intensity']:.3f}\n")
            f.write(f"情绪标签: {it['emotion_label']}\n")
            f.write(f"情绪深度: {it['emotion_depth']:.3f}\n")
            f.write(f"情绪转折: {it['emotion_transition']}\n")
            f.write(f"情绪密度: {it['emotion_word_density']:.3f}\n")
            f.write(f"改进建议: {it['suggestion']}\n")
            f.write(f"\n生成内容:\n")
            f.write("-" * 80 + "\n")
            f.write(it['content'] + "\n")
            f.write("-" * 80 + "\n\n")
    
    print(f"\n💾 测试结果已保存:")
    print(f"   JSON: {json_file}")
    print(f"   TXT:  {txt_file}")
    
    return json_file, txt_file

def save_to_feedback_log(iterations, user_prompt, feedback_csv="outputs/feedback_log.csv", 
                         candidates_dir="data/candidates", min_emotion_intensity=0.6):
    """将测试结果保存到反馈日志，用于后续模型训练"""
    print(f"\n{'='*80}")
    print("📝 保存到反馈日志（用于模型训练）")
    print(f"{'='*80}")
    
    # 创建目录
    os.makedirs(os.path.dirname(feedback_csv), exist_ok=True)
    os.makedirs(candidates_dir, exist_ok=True)
    
    # 读取或创建反馈日志
    if os.path.exists(feedback_csv):
        df = pd.read_csv(feedback_csv)
    else:
        df = pd.DataFrame(columns=[
            'timestamp', 'chapter_num', 'candidate_file', 'file_name',
            'model_score', 'user_feedback', 'emotion_intensity', 'emotion_label',
            'source', 'prompt'
        ])
    
    saved_count = 0
    
    for it in iterations:
        # 只保存情绪强度达标的迭代结果
        if it['emotion_intensity'] < min_emotion_intensity:
            print(f"⏭️  跳过第{it['iteration']}次迭代（情绪强度 {it['emotion_intensity']:.3f} < {min_emotion_intensity}）")
            continue
        
        # 生成文件哈希和文件名
        content_hash = hashlib.md5(it['content'].encode('utf-8')).hexdigest()[:8]
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"test_iter{it['iteration']}_{timestamp_str}_{content_hash}.txt"
        candidate_file = file_name
        
        # 保存内容到candidates目录
        content_path = os.path.join(candidates_dir, candidate_file)
        with open(content_path, 'w', encoding='utf-8') as f:
            f.write(it['content'])
        
        # 计算模型评分（基于情绪强度，转换为0-100分）
        model_score = min(100, int(it['emotion_intensity'] * 100))
        
        # 添加到反馈日志
        new_row = {
            'timestamp': it['generated_at'],
            'chapter_num': 0,  # 测试数据没有章节号
            'candidate_file': candidate_file,
            'file_name': file_name,
            'model_score': model_score,
            'user_feedback': None,  # 用户反馈为空，后续可以手动添加
            'emotion_intensity': it['emotion_intensity'],
            'emotion_label': it['emotion_label'],
            'source': 'test_feedback_loop',  # 标记来源
            'prompt': user_prompt
        }
        
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        saved_count += 1
        
        print(f"✅ 已保存第{it['iteration']}次迭代（情绪强度: {it['emotion_intensity']:.3f}, 模型评分: {model_score}）")
    
    # 保存反馈日志
    df.to_csv(feedback_csv, index=False, encoding='utf-8')
    
    print(f"\n📊 统计信息:")
    print(f"   总迭代次数: {len(iterations)}")
    print(f"   保存到反馈日志: {saved_count} 条（情绪强度 >= {min_emotion_intensity}）")
    print(f"   反馈日志路径: {feedback_csv}")
    print(f"\n💡 提示: 可以使用以下命令准备训练数据:")
    print(f"   python scripts/prepare_training_data.py --action from_feedback --min_emotion {min_emotion_intensity}")
    
    return saved_count

def main():
    """主函数"""
    print("=" * 80)
    print("🎭 情绪反馈循环测试工具")
    print("=" * 80)
    print("\n本工具用于测试'生成-评估-反馈-优化'流程是否能提升情绪强度")
    print("=" * 80)
    
    # 获取用户输入
    print("\n请输入你的提示词（描述你想要生成的小说片段场景）:")
    print("例如: '一个年轻人在深夜的废弃工厂里发现了一个秘密'")
    print("提示词: ", end="")
    user_prompt = input().strip()
    
    if not user_prompt:
        print("❌ 提示词不能为空！")
        return
    
    # 获取迭代次数
    print("\n请输入最大迭代次数 (默认3次): ", end="")
    max_iterations_input = input().strip()
    max_iterations = int(max_iterations_input) if max_iterations_input.isdigit() else 3
    
    # 获取目标情绪强度
    print("请输入目标情绪强度 (默认0.6): ", end="")
    min_emotion_input = input().strip()
    min_emotion_intensity = float(min_emotion_input) if min_emotion_input.replace('.', '').isdigit() else 0.6
    
    # 运行测试
    iterations = test_feedback_loop(user_prompt, max_iterations, min_emotion_intensity)
    
    # 保存结果
    if iterations:
        save_test_results(user_prompt, iterations)
        
        # 询问是否保存到反馈日志用于训练
        print("\n" + "=" * 80)
        print("💡 是否将测试结果保存到反馈日志，用于后续模型训练？")
        print("=" * 80)
        print("说明: 只有情绪强度达标的迭代结果会被保存")
        print(f"当前阈值: >= {min_emotion_intensity}")
        print("\n是否保存? (y/n, 默认n): ", end="")
        save_to_feedback = input().strip().lower()
        
        if save_to_feedback == 'y':
            saved_count = save_to_feedback_log(iterations, user_prompt, min_emotion_intensity=min_emotion_intensity)
            if saved_count > 0:
                print(f"\n✅ 已保存 {saved_count} 条记录到反馈日志，可用于模型训练")
            else:
                print(f"\n⚠️  没有符合条件的记录（情绪强度 >= {min_emotion_intensity}）")
        else:
            print("\n⏭️  跳过保存到反馈日志")
    
    print("\n✅ 测试完成！")

if __name__ == "__main__":
    main()


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Demo生成脚本 - 委屈情绪高评分内容
生成3个版本，评分后选择最高分的版本
"""

import sys
import os
import json
import re
from datetime import datetime

# 设置Windows UTF-8输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashscope
from scripts.optimized_rule_scorer import OptimizedRuleScorer
from scripts.paragraph_scorer import ParagraphScorer

# 配置API密钥（从现有脚本读取）
API_Key_QW = "sk-a2966f4e37134351904851679884cb67"

def clean_markdown(text):
    """去除Markdown格式符号"""
    if not text:
        return ""
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'### (.*)', r'\1', text)
    text = re.sub(r'## (.*)', r'\1', text)
    text = re.sub(r'# (.*)', r'\1', text)
    text = re.sub(r'---', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)  # 多个空行合并为两个
    return text.strip()

def call_qianwen_api(messages, temperature=0.85, top_p=0.8, repetition_penalty=1.1):
    """调用通义千问API生成内容"""
    dashscope.api_key = API_Key_QW
    try:
        response = dashscope.Generation.call(
            model=dashscope.Generation.Models.qwen_turbo,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            result_format='message',
            max_tokens=2000
        )

        if 'output' in response and 'choices' in response['output']:
            return response['output']['choices'][0]['message']['content']
        else:
            return f"API返回了无效格式: {str(response)}"
    except Exception as e:
        return f"调用API出错: {str(e)}"

def generate_grievance_content(version_num, temperature=0.85):
    """
    生成委屈情绪的内容
    
    参数:
        version_num: 版本号（1-3）
        temperature: 生成温度（0.7-0.9）
    """
    
    # 系统提示词 - 专门针对委屈情绪的高质量生成
    system_prompt = """你是一个专业的小说作者，擅长创作高质量、高情绪评分的情节内容。

【核心要求】
- 主题：委屈情绪，要求情绪评分达到85分以上
- 字数：800-1200字
- 风格：细腻的心理描写，强烈的情感渲染，强烈的冲突感

【委屈情绪的高评分特征 - 必须包含以下元素】

1. **强烈的冲突和误解**（重要！）
   - 被误解、被冤枉的激烈冲突
   - 想辩解却被压制，想反抗却无能为力
   - 周围人的指责和冷漠

2. **紧张的心理状态**
   - 心跳加速、呼吸困难
   - 内心激烈挣扎
   - 情绪从委屈转向愤怒，再从愤怒转向绝望

3. **强烈的情绪词汇**（必须使用）
   - 紧张、心跳、加快、警觉、可疑
   - 四目相对、空气凝固、包围、逼近
   - 威胁、追杀、失控、最后的机会
   - 这些词汇能帮助获得高评分

4. **冲突场景描写**
   - 对峙、争论、被围攻
   - 前有堵截、后有追兵的压迫感
   - 时间紧迫、必须在有限时间内解释清楚

5. **细腻的心理和生理反应**
   - 眼泪在眼眶打转但强忍着不掉下来
   - 喉咙像被堵住，想说话却发不出声
   - 身体颤抖、拳头紧握、牙齿咬得咯咯响
   - 内心独白：详细描述被误解的痛苦

6. **环境烘托**
   - 昏暗的环境、冷漠的氛围
   - 压抑的空间、窒息的空气
   - 围观者的目光像刀子一样

【高评分写作技巧】
- **必须包含紧张感和冲突感**：虽然是委屈主题，但要有激烈的冲突场景
- **情绪递进**：从困惑→不解→委屈→愤怒→绝望的情感层次
- **对比强烈**：期望与现实的巨大落差
- **细节丰富**：不只是一句话，而是完整的场景和感受
- **使用高评分关键词**：适当使用"紧张"、"心跳"、"威胁"、"逼近"等词汇

【示例结构】
开头：被误解的瞬间，周围人的反应（冲突感）
中段：内心挣扎、想辩解却被压制（紧张感）
高潮：情绪爆发、激烈的心理冲突（强烈情绪）
结尾：委屈但不屈，内心的坚持（留下深刻印象）

【禁止事项】
- 不要写得太简单直白
- 不要缺乏冲突和紧张感
- 不要缺乏细节描写
- 不要情绪表达不够强烈

直接输出创作内容，不要引言和总结。确保情绪评分能达到85分以上！"""

    user_prompt = """请创作一段描写委屈情绪的高质量情节内容。

核心要求：
1. **主角因为被误解或冤枉而感到委屈**，但要包含激烈的冲突场景
2. **必须有紧张感和冲突感**：如被围攻、想辩解却被压制、时间紧迫等
3. **内心感受要细腻深刻**：详细的心理描写，情绪从委屈到愤怒的递进
4. **包含高分元素**：
   - 使用"紧张"、"心跳"、"四目相对"、"逼近"等关键词
   - 冲突场景：对峙、争论、被包围
   - 心理状态：心跳加速、呼吸困难、内心激烈挣扎
   - 生理反应：眼泪、颤抖、咬紧嘴唇、喉咙被堵住
5. **字数800-1200字**
6. **确保情绪评分能够达到85分以上**

请直接输出内容，不需要任何说明。"""

    # 为不同版本调整温度，增加多样性
    if version_num == 1:
        temp = temperature
    elif version_num == 2:
        temp = temperature + 0.05  # 稍微提高随机性
    else:
        temp = temperature - 0.05  # 稍微降低随机性
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    print(f"  正在生成版本{version_num}...")
    generated_text = call_qianwen_api(messages, temperature=temp)
    cleaned_text = clean_markdown(generated_text)
    
    return cleaned_text

def score_content(content, rule_scorer, ml_scorer):
    """对内容进行双重评分"""
    # 规则评分
    rule_score = rule_scorer.calculate_score(content)
    
    # ML评分
    ml_score = None
    if ml_scorer and ml_scorer.model is not None:
        try:
            ml_score = ml_scorer.predict_score(content)
        except:
            ml_score = None
    
    # 综合评分
    if ml_score is not None:
        final_score = (rule_score + ml_score) / 2
        print(f"    规则评分: {rule_score:.1f}, ML评分: {ml_score:.1f}, 综合评分: {final_score:.1f}")
    else:
        final_score = rule_score
        print(f"    规则评分: {rule_score:.1f}, 综合评分: {final_score:.1f} (ML评分不可用)")
    
    return {
        'rule_score': rule_score,
        'ml_score': ml_score,
        'final_score': final_score
    }

def main():
    """主函数"""
    print("="*70)
    print("Demo生成脚本 - 委屈情绪高评分内容")
    print("="*70)
    print()
    
    # 目标设置
    target_score = 85.0  # 目标评分
    num_versions = 3      # 生成3个版本
    
    print(f"目标情绪: 委屈")
    print(f"目标评分: >= {target_score}分")
    print(f"生成版本数: {num_versions}")
    print(f"评分方式: 规则评分 + ML评分")
    print()
    print("="*70)
    print()
    
    # 初始化评分器
    print("[初始化] 加载评分器...")
    rule_scorer = OptimizedRuleScorer()
    
    ml_scorer = ParagraphScorer()
    ml_model_loaded = False
    annotations_file = "data/training/paragraph_annotations.json"
    if os.path.exists(annotations_file):
        try:
            annotations = ml_scorer.load_annotations(annotations_file)
            if ml_scorer.train_model(annotations):
                ml_model_loaded = True
                print("  [成功] ML评分模型已加载")
            else:
                print("  [警告] ML评分模型加载失败，仅使用规则评分")
        except Exception as e:
            print(f"  [警告] ML评分模型加载失败: {e}，仅使用规则评分")
    else:
        print("  [信息] 未找到ML评分模型，仅使用规则评分")
    
    if not ml_model_loaded:
        ml_scorer = None
    
    print()
    
    # 生成多个版本
    versions = []
    
    for i in range(1, num_versions + 1):
        print(f"[生成] 版本 {i}/{num_versions}")
        print("-" * 70)
        
        # 生成内容
        content = generate_grievance_content(i, temperature=0.85)
        
        if "出错" in content or "错误" in content:
            print(f"  [错误] 生成失败: {content[:100]}")
            continue
        
        print(f"  [生成完成] 内容长度: {len(content)} 字符")
        
        # 评分
        print("  [评分中] ...")
        scores = score_content(content, rule_scorer, ml_scorer)
        
        versions.append({
            'version': i,
            'content': content,
            'scores': scores,
            'length': len(content)
        })
        
        print()
    
    if not versions:
        print("[错误] 没有成功生成任何版本，请检查API配置")
        return
    
    # 选择最高分版本
    print("="*70)
    print("[结果] 版本评分汇总")
    print("="*70)
    
    for v in versions:
        print(f"版本{v['version']}: 综合评分 {v['scores']['final_score']:.1f}分 "
              f"(规则{v['scores']['rule_score']:.1f}分" + 
              (f", ML{v['scores']['ml_score']:.1f}分)" if v['scores']['ml_score'] else ")") +
              f" | 字数: {v['length']}")
    
    print()
    
    # 选择最佳版本
    best_version = max(versions, key=lambda x: x['scores']['final_score'])
    
    print("="*70)
    print(f"[选择] 最佳版本: 版本{best_version['version']}")
    print("="*70)
    print(f"综合评分: {best_version['scores']['final_score']:.1f}分")
    print(f"规则评分: {best_version['scores']['rule_score']:.1f}分")
    if best_version['scores']['ml_score']:
        print(f"ML评分: {best_version['scores']['ml_score']:.1f}分")
    print(f"字数: {best_version['length']}字")
    
    # 检查是否达到目标
    if best_version['scores']['final_score'] >= target_score:
        print(f"✅ [达成] 评分达到目标 ({target_score}分以上)")
    else:
        print(f"⚠️  [未达] 评分 {best_version['scores']['final_score']:.1f}分，低于目标 {target_score}分")
    
    print()
    print("="*70)
    print("[内容] 最佳版本内容")
    print("="*70)
    print(best_version['content'])
    print("="*70)
    print()
    
    # 保存结果
    output_dir = "outputs"
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 保存最佳版本
    best_file = os.path.join(output_dir, f"demo_grievance_best_{timestamp}.txt")
    with open(best_file, 'w', encoding='utf-8') as f:
        f.write(f"Demo - 委屈情绪高评分内容\n")
        f.write(f"{'='*70}\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"版本: {best_version['version']}/3\n")
        f.write(f"综合评分: {best_version['scores']['final_score']:.1f}分\n")
        f.write(f"规则评分: {best_version['scores']['rule_score']:.1f}分\n")
        if best_version['scores']['ml_score']:
            f.write(f"ML评分: {best_version['scores']['ml_score']:.1f}分\n")
        f.write(f"字数: {best_version['length']}字\n")
        f.write(f"{'='*70}\n\n")
        f.write(best_version['content'])
    
    print(f"[保存] 最佳版本已保存: {best_file}")
    
    # 保存所有版本（JSON格式，便于查看）
    all_versions_file = os.path.join(output_dir, f"demo_grievance_all_{timestamp}.json")
    with open(all_versions_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'target_emotion': '委屈',
            'target_score': target_score,
            'versions': [
                {
                    'version': v['version'],
                    'final_score': v['scores']['final_score'],
                    'rule_score': v['scores']['rule_score'],
                    'ml_score': v['scores']['ml_score'],
                    'length': v['length'],
                    'content': v['content']
                }
                for v in versions
            ],
            'best_version': best_version['version'],
            'best_score': best_version['scores']['final_score']
        }, f, ensure_ascii=False, indent=2)
    
    print(f"[保存] 所有版本已保存: {all_versions_file}")
    
    print()
    print("="*70)
    print("[完成] Demo生成完成！")
    print("="*70)

if __name__ == "__main__":
    main()


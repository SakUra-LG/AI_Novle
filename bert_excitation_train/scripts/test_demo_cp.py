#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Demo生成脚本 - 男女CP情感起伏高评分内容
生成3个版本，评分后选择最高分的版本
重点：女方情绪跌宕起伏，细腻的感情变化，高情绪分
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

def generate_cp_content(version_num, temperature=0.85):
    """
    生成男女CP情感起伏的内容
    
    参数:
        version_num: 版本号（1-3）
        temperature: 生成温度（0.7-0.9）
    """
    
    # 系统提示词 - 专门针对CP情感起伏的高质量生成
    system_prompt = """你是一个专业的小说作者，擅长创作高质量、高情绪评分的情感情节内容。

【核心要求】
- 题材：男女CP情感互动
- 重点：女方情绪的跌宕起伏，细腻的感情变化
- 字数：1000-1300字
- 风格：细腻的心理描写，强烈的情感渲染，多层次的情绪变化
- 目标：情绪评分达到85分以上

【女方情绪跌宕起伏的高评分特征 - 必须包含以下元素】

1. **复杂的情绪变化链条**（核心！）
   必须包含至少4-5种不同的情绪层次，例如：
   - 第一阶段：期待/欣喜 → 心跳加速、面带微笑、眼神发亮
   - 第二阶段：困惑/不安 → 眉头微皱、脚步放慢、心跳开始不稳
   - 第三阶段：失望/委屈 → 眼眶湿润、声音颤抖、想要逃避
   - 第四阶段：愤怒/抗拒 → 语气变冷、身体紧绷、想要反抗
   - 第五阶段：感动/释然 → 眼泪滑落、内心软化、情绪释放

2. **细腻的心理描写**（必须详细！）
   - 内心独白：每个情绪阶段的内心想法都要写出来
   - 心理斗争：理性与感性的拉扯，想要靠近又害怕受伤
   - 情绪转变的触发点：明确是什么事件或话语导致了情绪变化
   - 心理活动要有层次，不能简单直白

3. **身体和生理反应**（与情绪同步！）
   - 心跳变化：从平稳→加速→狂跳→慢慢平复
   - 呼吸节奏：从轻松→急促→困难→缓和
   - 眼神变化：从明亮→闪烁→躲避→直视
   - 身体语言：手指绞紧衣角、肩膀紧绷、身体微微颤抖、放松
   - 声音变化：从轻快→紧张→哽咽→冷淡→柔和

4. **强烈的情感词汇**（必须使用！）
   - 紧张、心跳、加快、逼近、四目相对
   - 空气凝固、包围、威胁感、最后的机会
   - 这些词汇能帮助获得高评分

5. **冲突和张力场景**
   - 误解产生的瞬间：一句话、一个眼神、一个动作
   - 对话中的暗流涌动：表面平静但内心波澜
   - 情感对峙：两人之间的情绪拉锯
   - 关键时刻：需要做出情感选择的重要时刻

6. **细腻的互动细节**
   - 男方的话语和反应如何影响女方的情绪
   - 女方如何观察和解读男方的一举一动
   - 两人之间的空间距离变化（靠近→远离→重新靠近）
   - 眼神交流、肢体接触的微妙变化

【高评分写作技巧】

- **情绪曲线要清晰**：每个情绪阶段都要有明确的起始和转折
- **转折要自然**：情绪变化要有合理的原因和触发点
- **对比要强烈**：情绪的高峰和低谷形成鲜明对比
- **细节要丰富**：不只是一句话，而是完整的场景和感受
- **内心与外在要呼应**：心理描写和身体反应要匹配
- **使用高评分关键词**：适当使用"紧张"、"心跳"、"逼近"、"四目相对"等词汇
- **冲突感要足够**：虽然是情感题材，但要有足够的冲突和张力

【示例情绪变化结构】
开头：欣喜/期待（心跳加快，眼中带笑） → 男方出现，女方心情愉悦
中段1：困惑/不安（眉头微皱，心跳不稳） → 察觉到不对劲
中段2：失望/委屈（眼眶湿润，声音颤抖） → 误解加深，内心受伤
高潮：愤怒/抗拒（语气变冷，身体紧绷） → 情绪爆发，想要逃离
转折：触动/软化（眼泪滑落，内心动摇） → 男方的某个举动让她动摇
结尾：感动/释然（内心释然，情绪释放） → 误会解开，情感升华

【禁止事项】
- 不要情绪变化过于简单（只有1-2种情绪）
- 不要缺乏细腻的心理描写
- 不要缺乏身体和生理反应的细节
- 不要情绪转变过于突兀，缺乏过渡
- 不要冲突感不够，显得平淡

直接输出创作内容，不要引言和总结。确保女方情绪有清晰的起伏变化，情绪评分能达到85分以上！"""

    user_prompt = """请创作一段男女CP情感互动的高质量情节内容。

核心要求：
1. **女方情绪必须跌宕起伏**：至少包含4-5种不同的情绪层次（如：期待→困惑→失望→愤怒→感动）
2. **每个情绪阶段都要有细腻的心理描写**：
   - 内心想法和独白
   - 身体反应（心跳、呼吸、眼神、身体语言）
   - 声音和语调的变化
3. **情绪变化的触发点要明确**：是什么导致了她情绪的转变
4. **包含高分元素**：
   - 使用"紧张"、"心跳"、"四目相对"、"逼近"、"空气凝固"等关键词
   - 冲突场景：误解、对话中的暗流、情感对峙
   - 强烈的心理状态：内心挣扎、情绪爆发
   - 细腻的生理反应：心跳变化、呼吸节奏、眼神变化
5. **男女互动要自然真实**：男方的话语和反应要影响女方的情绪变化
6. **字数1000-1300字**
7. **确保情绪评分能够达到85分以上**

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
    print("Demo生成脚本 - 男女CP情感起伏高评分内容")
    print("="*70)
    print()
    
    # 目标设置
    target_score = 85.0  # 目标评分
    num_versions = 3      # 生成3个版本
    
    print(f"题材: 男女CP情感互动")
    print(f"重点: 女方情绪跌宕起伏，细腻的感情变化")
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
        content = generate_cp_content(i, temperature=0.85)
        
        # 检查是否是API错误（检查特定的错误消息格式）
        if content.startswith("API返回了无效格式") or content.startswith("调用API出错"):
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
    best_file = os.path.join(output_dir, f"demo_cp_best_{timestamp}.txt")
    with open(best_file, 'w', encoding='utf-8') as f:
        f.write(f"Demo - 男女CP情感起伏高评分内容\n")
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
    all_versions_file = os.path.join(output_dir, f"demo_cp_all_{timestamp}.json")
    with open(all_versions_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'theme': '男女CP情感互动',
            'focus': '女方情绪跌宕起伏，细腻的感情变化',
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


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整工作流程脚本
实现：样本库添加 → 生成 → 防低分策略 → 评分 → 训练
"""

import os
import sys
import argparse
import subprocess
from datetime import datetime

def run_command(command, description):
    """运行命令并显示进度"""
    print(f"\n{'='*60}")
    print(f"正在执行: {description}")
    print(f"命令: {command}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print("执行成功！")
        if result.stdout:
            print("输出:")
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"执行失败: {e}")
        if e.stderr:
            print("错误信息:")
            print(e.stderr)
        return False

def step1_add_samples():
    """步骤1: 添加样本到样本库"""
    print("\n" + "="*60)
    print("步骤1: 添加样本到样本库")
    print("="*60)
    print("请手动编辑 data/universal_samples.txt 文件添加新的高评分样本")
    print("添加完成后按回车继续...")
    input()

def step2_generate_chapters(chapter_num, prompt, num_versions=3):
    """步骤2: 生成章节"""
    print(f"\n步骤2: 生成第{chapter_num}章")
    
    # 使用增强RAG生成器生成
    success = run_command(
        f"python scripts/enhanced_rag_generator.py --chapter {chapter_num} --prompt \"{prompt}\" --versions {num_versions}",
        f"生成第{chapter_num}章，共{num_versions}个版本（增强RAG模式）"
    )
    
    return success

def step3_anti_low_score():
    """步骤3: 防低分策略"""
    print("\n步骤3: 防低分策略")
    
    # 检测低分循环
    success1 = run_command(
        "python scripts/smart_training_manager.py --action detect",
        "检测低分循环"
    )
    
    if success1:
        # 如果检测到低分循环，尝试修复
        success2 = run_command(
            "python scripts/smart_training_manager.py --action fix --strategy data_cleaning",
            "修复低分循环"
        )
        return success2
    
    return success1

def step4_score_candidates(chapter_num):
    """步骤4: 评分候选章节"""
    print(f"\n步骤4: 评分第{chapter_num}章候选章节")
    
    success = run_command(
        f"python scripts/score_candidates_rule_based.py --candidates_dir data/generated/暗河噬城 --output_dir data/final --chapter_num {chapter_num}",
        f"评分第{chapter_num}章候选章节"
    )
    
    return success

def step5_record_feedback(chapter_num):
    """步骤5: 记录反馈"""
    print(f"\n步骤5: 记录第{chapter_num}章反馈")
    
    success = run_command(
        f"python scripts/record_feedback.py --action record --chapter {chapter_num} --candidates_dir data/generated/暗河噬城",
        f"记录第{chapter_num}章反馈"
    )
    
    return success

def step6_prepare_training_data():
    """步骤6: 准备训练数据"""
    print("\n步骤6: 准备训练数据")
    
    success = run_command(
        "python scripts/prepare_training_data.py --action all --min_score 70",
        "准备训练数据"
    )
    
    return success

def step7_train_model(model_type="lora"):
    """步骤7: 训练模型"""
    print(f"\n步骤7: 训练模型 ({model_type})")
    
    if model_type == "lora":
        success = run_command(
            "python scripts/lora_training.py --data_file data/training/combined_training_data.csv --output_dir checkpoints/lora_model_new",
            "LoRA训练"
        )
    elif model_type == "finetune":
        success = run_command(
            "python scripts/finetune_model.py --data_file data/training/combined_training_data.csv --output_dir checkpoints/finetuned_model_new",
            "全参数微调"
        )
    else:
        print(f"不支持的训练类型: {model_type}")
        return False
    
    return success

def complete_workflow(chapter_num, prompt, num_versions=3, model_type="lora"):
    """完整工作流程"""
    print("=" * 60)
    print("完整工作流程")
    print("=" * 60)
    print(f"章节号: {chapter_num}")
    print(f"提示词: {prompt}")
    print(f"版本数: {num_versions}")
    print(f"训练类型: {model_type}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    steps = [
        ("添加样本", step1_add_samples),
        ("生成章节", lambda: step2_generate_chapters(chapter_num, prompt, num_versions)),
        ("防低分策略", step3_anti_low_score),
        ("评分候选", lambda: step4_score_candidates(chapter_num)),
        ("记录反馈", lambda: step5_record_feedback(chapter_num)),
        ("准备训练数据", step6_prepare_training_data),
        ("训练模型", lambda: step7_train_model(model_type))
    ]
    
    results = []
    
    for step_name, step_func in steps:
        print(f"\n{'='*60}")
        print(f"执行步骤: {step_name}")
        print(f"{'='*60}")
        
        try:
            success = step_func()
            results.append((step_name, success))
            
            if success:
                print(f"✅ {step_name} 完成")
            else:
                print(f"❌ {step_name} 失败")
                break
                
        except Exception as e:
            print(f"❌ {step_name} 出错: {e}")
            results.append((step_name, False))
            break
    
    # 总结
    print(f"\n{'='*60}")
    print("工作流程总结")
    print(f"{'='*60}")
    
    completed = sum(1 for _, success in results if success)
    total = len(results)
    
    print(f"完成步骤: {completed}/{total}")
    
    for step_name, success in results:
        status = "✅" if success else "❌"
        print(f"{status} {step_name}")
    
    print(f"\n结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if completed == total:
        print("🎉 完整工作流程执行成功！")
    else:
        print("⚠️ 工作流程未完全完成，请检查失败的步骤")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='完整工作流程脚本')
    parser.add_argument('--chapter', type=int, required=True, help='章节号')
    parser.add_argument('--prompt', type=str, required=True, help='生成提示词')
    parser.add_argument('--versions', type=int, default=3, help='生成版本数')
    parser.add_argument('--model_type', type=str, choices=['lora', 'finetune'], 
                       default='lora', help='训练模型类型')
    parser.add_argument('--step', type=str, 
                       choices=['add_samples', 'generate', 'anti_low', 'score', 'feedback', 'prepare', 'train', 'all'],
                       default='all', help='执行特定步骤或完整流程')
    
    args = parser.parse_args()
    
    if args.step == 'all':
        complete_workflow(args.chapter, args.prompt, args.versions, args.model_type)
    elif args.step == 'add_samples':
        step1_add_samples()
    elif args.step == 'generate':
        step2_generate_chapters(args.chapter, args.prompt, args.versions)
    elif args.step == 'anti_low':
        step3_anti_low_score()
    elif args.step == 'score':
        step4_score_candidates(args.chapter)
    elif args.step == 'feedback':
        step5_record_feedback(args.chapter)
    elif args.step == 'prepare':
        step6_prepare_training_data()
    elif args.step == 'train':
        step7_train_model(args.model_type)

if __name__ == "__main__":
    main()

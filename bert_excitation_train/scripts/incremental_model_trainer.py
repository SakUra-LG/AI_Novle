#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增量模型训练器
只使用新增数据训练模型，避免重复训练
"""

import sys
import os
import json
import subprocess
from datetime import datetime
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.paragraph_scorer import ParagraphScorer

class IncrementalModelTrainer:
    def __init__(self):
        self.ml_incremental_file = "data/training/incremental_ml_annotations.json"
        self.gen_incremental_file = "data/training/incremental_generation_data.jsonl"
        self.ml_full_file = "data/training/paragraph_annotations.json"
        self.gen_full_file = "data/training/lora_data.jsonl"
        self.training_log = "data/training/training_log.json"
        
    def load_training_log(self):
        """加载训练日志"""
        if os.path.exists(self.training_log):
            with open(self.training_log, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            'ml_last_training': None,
            'gen_last_training': None,
            'ml_training_count': 0,
            'gen_training_count': 0,
            'trained_samples': []
        }
    
    def save_training_log(self, log_data):
        """保存训练日志"""
        os.makedirs(os.path.dirname(self.training_log), exist_ok=True)
        log_data['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(self.training_log, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
    
    def check_incremental_data(self):
        """检查增量数据"""
        print("🔍 检查增量训练数据...")
        
        # 检查ML增量数据
        ml_incremental_count = 0
        if os.path.exists(self.ml_incremental_file):
            with open(self.ml_incremental_file, 'r', encoding='utf-8') as f:
                ml_data = json.load(f)
            ml_incremental_count = len(ml_data)
            print(f"✅ ML增量数据: {ml_incremental_count} 个样本")
        else:
            print("❌ ML增量数据不存在")
        
        # 检查生成模型增量数据
        gen_incremental_count = 0
        if os.path.exists(self.gen_incremental_file):
            with open(self.gen_incremental_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        gen_incremental_count += 1
            print(f"✅ 生成模型增量数据: {gen_incremental_count} 个样本")
        else:
            print("❌ 生成模型增量数据不存在")
        
        return ml_incremental_count, gen_incremental_count
    
    def merge_ml_training_data(self):
        """合并ML训练数据"""
        print("\n🔄 合并ML训练数据...")
        
        # 加载现有数据
        existing_data = []
        if os.path.exists(self.ml_full_file):
            with open(self.ml_full_file, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        
        # 加载增量数据
        incremental_data = []
        if os.path.exists(self.ml_incremental_file):
            with open(self.ml_incremental_file, 'r', encoding='utf-8') as f:
                incremental_data = json.load(f)
        
        if not incremental_data:
            print("⚠️ 没有增量ML数据需要合并")
            return existing_data
        
        # 获取已训练的样本哈希
        log_data = self.load_training_log()
        trained_hashes = set(log_data.get('trained_samples', []))
        
        # 过滤出真正新增的样本
        new_samples = []
        for sample in incremental_data:
            sample_hash = sample.get('sample_hash', '')
            if sample_hash and sample_hash not in trained_hashes:
                new_samples.append(sample)
                trained_hashes.add(sample_hash)
        
        if not new_samples:
            print("✅ 所有增量ML数据都已训练过")
            return existing_data
        
        # 合并数据
        merged_data = existing_data + new_samples
        
        # 保存合并后的数据
        with open(self.ml_full_file, 'w', encoding='utf-8') as f:
            json.dump(merged_data, f, ensure_ascii=False, indent=2)
        
        # 更新训练日志
        log_data['trained_samples'] = list(trained_hashes)
        self.save_training_log(log_data)
        
        print(f"✅ ML训练数据合并完成: 新增 {len(new_samples)} 个样本")
        return merged_data
    
    def merge_generation_training_data(self):
        """合并生成模型训练数据"""
        print("\n🔄 合并生成模型训练数据...")
        
        # 加载现有数据
        existing_data = []
        if os.path.exists(self.gen_full_file):
            with open(self.gen_full_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        existing_data.append(json.loads(line))
        
        # 加载增量数据
        incremental_data = []
        if os.path.exists(self.gen_incremental_file):
            with open(self.gen_incremental_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        incremental_data.append(json.loads(line))
        
        if not incremental_data:
            print("⚠️ 没有增量生成数据需要合并")
            return existing_data
        
        # 获取已训练的样本哈希
        log_data = self.load_training_log()
        trained_hashes = set(log_data.get('trained_samples', []))
        
        # 过滤出真正新增的样本
        new_samples = []
        for sample in incremental_data:
            sample_hash = sample.get('sample_hash', '')
            if sample_hash and sample_hash not in trained_hashes:
                new_samples.append(sample)
                trained_hashes.add(sample_hash)
        
        if not new_samples:
            print("✅ 所有增量生成数据都已训练过")
            return existing_data
        
        # 合并数据
        merged_data = existing_data + new_samples
        
        # 保存合并后的数据
        with open(self.gen_full_file, 'w', encoding='utf-8') as f:
            for item in merged_data:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')
        
        # 更新训练日志
        log_data['trained_samples'] = list(trained_hashes)
        self.save_training_log(log_data)
        
        print(f"✅ 生成模型训练数据合并完成: 新增 {len(new_samples)} 个样本")
        return merged_data
    
    def train_ml_model_incremental(self):
        """增量训练ML评分模型"""
        print("\n📊 开始增量训练ML评分模型...")
        
        # 合并训练数据
        merged_data = self.merge_ml_training_data()
        
        if not merged_data:
            print("❌ 没有ML训练数据")
            return False
        
        try:
            ml_scorer = ParagraphScorer()
            print(f"📚 使用 {len(merged_data)} 个样本训练ML模型")
            
            if ml_scorer.train_model(merged_data):
                print("✅ ML评分模型训练完成")
                
                # 更新训练日志
                log_data = self.load_training_log()
                log_data['ml_last_training'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                log_data['ml_training_count'] += 1
                self.save_training_log(log_data)
                
                return True
            else:
                print("❌ ML评分模型训练失败")
                return False
                
        except Exception as e:
            print(f"❌ ML模型训练出错: {e}")
            return False
    
    def train_generation_model_incremental(self):
        """增量训练生成模型"""
        print("\n🤖 开始增量训练生成模型...")
        
        # 合并训练数据
        merged_data = self.merge_generation_training_data()
        
        if not merged_data:
            print("❌ 没有生成模型训练数据")
            return False
        
        print(f"📚 使用 {len(merged_data)} 个样本训练生成模型")
        
        # 选择训练方式
        print("\n选择训练方式:")
        print("1. LoRA训练 (推荐，速度快)")
        print("2. 全参数微调 (效果好，但需要更多资源)")
        
        while True:
            choice = input("请选择 (1/2): ").strip()
            if choice == '1':
                return self.train_lora_incremental()
            elif choice == '2':
                return self.train_full_incremental()
            else:
                print("❌ 无效选择，请输入 1 或 2")
    
    def train_lora_incremental(self):
        """增量LoRA训练"""
        print("🚀 开始增量LoRA训练...")
        
        try:
            # 构建训练命令
            cmd = [
                "python", "scripts/lora_training.py",
                "--data_file", self.gen_full_file,
                "--output_dir", "checkpoints/lora_model_incremental",
                "--num_train_epochs", "2",  # 增量训练使用较少轮次
                "--per_device_train_batch_size", "1",
                "--gradient_accumulation_steps", "4",
                "--learning_rate", "3e-4",  # 增量训练使用较小学习率
                "--warmup_ratio", "0.1"
            ]
            
            print(f"执行命令: {' '.join(cmd)}")
            
            # 执行训练
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
            
            if result.returncode == 0:
                print("✅ 增量LoRA训练完成")
                print("📊 训练输出:")
                print(result.stdout)
                
                # 更新训练日志
                log_data = self.load_training_log()
                log_data['gen_last_training'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                log_data['gen_training_count'] += 1
                self.save_training_log(log_data)
                
                return True
            else:
                print("❌ 增量LoRA训练失败")
                print("错误输出:")
                print(result.stderr)
                return False
                
        except Exception as e:
            print(f"❌ 增量LoRA训练出错: {e}")
            return False
    
    def train_full_incremental(self):
        """增量全参数微调"""
        print("🚀 开始增量全参数微调...")
        
        try:
            # 构建训练命令
            cmd = [
                "python", "scripts/finetune_model.py",
                "--data_file", self.gen_full_file,
                "--output_dir", "checkpoints/finetuned_model_incremental",
                "--num_train_epochs", "1",  # 增量训练使用较少轮次
                "--per_device_train_batch_size", "1",
                "--gradient_accumulation_steps", "8",
                "--learning_rate", "1e-5"  # 增量训练使用较小学习率
            ]
            
            print(f"执行命令: {' '.join(cmd)}")
            
            # 执行训练
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
            
            if result.returncode == 0:
                print("✅ 增量全参数微调完成")
                print("📊 训练输出:")
                print(result.stdout)
                
                # 更新训练日志
                log_data = self.load_training_log()
                log_data['gen_last_training'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                log_data['gen_training_count'] += 1
                self.save_training_log(log_data)
                
                return True
            else:
                print("❌ 增量全参数微调失败")
                print("错误输出:")
                print(result.stderr)
                return False
                
        except Exception as e:
            print(f"❌ 增量全参数微调出错: {e}")
            return False
    
    def cleanup_incremental_files(self):
        """清理增量文件"""
        print("\n🧹 清理增量训练文件...")
        
        if os.path.exists(self.ml_incremental_file):
            os.remove(self.ml_incremental_file)
            print(f"✅ 已删除: {self.ml_incremental_file}")
        
        if os.path.exists(self.gen_incremental_file):
            os.remove(self.gen_incremental_file)
            print(f"✅ 已删除: {self.gen_incremental_file}")
    
    def show_training_summary(self):
        """显示训练总结"""
        log_data = self.load_training_log()
        
        print("\n" + "=" * 60)
        print("📊 训练历史总结:")
        print(f"   ML模型训练次数: {log_data.get('ml_training_count', 0)}")
        print(f"   生成模型训练次数: {log_data.get('gen_training_count', 0)}")
        print(f"   已训练样本数: {len(log_data.get('trained_samples', []))}")
        if log_data.get('ml_last_training'):
            print(f"   上次ML训练: {log_data['ml_last_training']}")
        if log_data.get('gen_last_training'):
            print(f"   上次生成模型训练: {log_data['gen_last_training']}")
        print("=" * 60)

def main():
    """主函数"""
    print("🎯 增量模型训练器")
    print("=" * 60)
    print("只使用新增数据训练模型，避免重复训练")
    print("=" * 60)
    
    trainer = IncrementalModelTrainer()
    
    # 检查增量数据
    ml_count, gen_count = trainer.check_incremental_data()
    
    if ml_count == 0 and gen_count == 0:
        print("❌ 没有找到增量训练数据")
        print("💡 请先运行: python scripts/incremental_sample_scorer.py")
        return
    
    # 询问是否继续
    continue_choice = input(f"\n是否开始增量训练？(ML: {ml_count}个样本, 生成: {gen_count}个样本) (y/n): ").strip().lower()
    if continue_choice not in ['y', 'yes', '是']:
        print("✅ 训练已取消")
        return
    
    # 训练ML模型
    ml_success = False
    if ml_count > 0:
        ml_success = trainer.train_ml_model_incremental()
    else:
        print("⏭️ 跳过ML模型训练（无增量数据）")
    
    # 训练生成模型
    gen_success = False
    if gen_count > 0:
        gen_success = trainer.train_generation_model_incremental()
    else:
        print("⏭️ 跳过生成模型训练（无增量数据）")
    
    # 清理增量文件
    if ml_success or gen_success:
        cleanup_choice = input("\n是否清理增量训练文件？(y/n): ").strip().lower()
        if cleanup_choice in ['y', 'yes', '是']:
            trainer.cleanup_incremental_files()
    
    # 显示训练总结
    trainer.show_training_summary()
    
    # 总结
    print("\n🎉 增量训练完成总结:")
    print(f"   ML评分模型: {'✅ 成功' if ml_success else '❌ 失败'}")
    print(f"   生成模型: {'✅ 成功' if gen_success else '❌ 失败'}")
    
    if ml_success or gen_success:
        print("\n💡 下一步建议:")
        print("   - 使用测试工具验证模型效果")
        print("   - 继续添加新样本进行增量训练")

if __name__ == "__main__":
    main()

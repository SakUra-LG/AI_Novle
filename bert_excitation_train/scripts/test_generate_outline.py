#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本：检查生成梗概脚本的依赖和环境
"""

import sys
import os

# 添加项目根目录到路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

def check_dependencies():
    """检查必要的依赖是否已安装"""
    print("=" * 60)
    print("检查依赖环境...")
    print("=" * 60)
    
    dependencies = {
        "dashscope": "通义千问 API SDK",
        "torch": "PyTorch（用于向量化）",
        "numpy": "NumPy（用于数值计算）",
        "sklearn": "scikit-learn（用于相似度计算）",
        "transformers": "Transformers（用于加载 BGE 模型）",
    }
    
    missing = []
    for module_name, description in dependencies.items():
        try:
            if module_name == "sklearn":
                import sklearn
            else:
                __import__(module_name)
            print(f"✅ {module_name:15s} - {description}")
        except ImportError:
            print(f"❌ {module_name:15s} - {description} (未安装)")
            missing.append(module_name)
    
    print("\n" + "=" * 60)
    if missing:
        print(f"缺少以下依赖，请先安装：")
        print(f"pip install {' '.join(missing)}")
        return False
    else:
        print("✅ 所有依赖已安装，可以运行生成脚本！")
        return True

def check_files():
    """检查必要的文件是否存在"""
    print("\n" + "=" * 60)
    print("检查必要文件...")
    print("=" * 60)
    
    files_to_check = [
        ("scripts/generate_outline_rebirth_revenge.py", "生成脚本"),
        ("scripts/smart_sample_search.py", "样本搜索模块"),
        ("data/universal_samples_data.json", "RAG 样本数据（可选）"),
    ]
    
    all_exist = True
    for file_path, description in files_to_check:
        full_path = os.path.join(PROJECT_ROOT, file_path)
        if os.path.exists(full_path):
            print(f"✅ {file_path:40s} - {description}")
        else:
            print(f"⚠️  {file_path:40s} - {description} (不存在，但可能不影响运行)")
            if "generate_outline" in file_path or "smart_sample_search" in file_path:
                all_exist = False
    
    print("\n" + "=" * 60)
    if all_exist:
        print("✅ 必要文件检查通过！")
    else:
        print("❌ 缺少必要文件，请检查项目结构")
    
    return all_exist

def check_api_key():
    """检查 API Key 是否配置"""
    print("\n" + "=" * 60)
    print("检查 API Key 配置...")
    print("=" * 60)
    
    script_path = os.path.join(PROJECT_ROOT, "scripts", "generate_outline_rebirth_revenge.py")
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
            if 'API_Key_QW = "sk-' in content:
                print("✅ API Key 已配置在脚本中")
                return True
            else:
                print("⚠️  未找到 API Key 配置，请检查脚本中的 API_Key_QW 变量")
                return False
    except Exception as e:
        print(f"❌ 无法读取脚本文件: {e}")
        return False

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("生成梗概脚本 - 环境检查工具")
    print("=" * 60 + "\n")
    
    deps_ok = check_dependencies()
    files_ok = check_files()
    api_ok = check_api_key()
    
    print("\n" + "=" * 60)
    print("检查结果总结")
    print("=" * 60)
    
    if deps_ok and files_ok and api_ok:
        print("\n✅ 环境检查通过！可以运行生成脚本：")
        print("   python scripts/generate_outline_rebirth_revenge.py")
    else:
        print("\n❌ 环境检查未通过，请先解决上述问题")
        if not deps_ok:
            print("   - 安装缺失的依赖包")
        if not files_ok:
            print("   - 检查项目文件结构")
        if not api_ok:
            print("   - 配置通义千问 API Key")
    
    print()

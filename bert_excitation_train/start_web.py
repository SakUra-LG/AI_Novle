#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI小说自动生成系统 - Web服务器启动脚本
"""

import os
import sys
import subprocess
import webbrowser
from pathlib import Path

def check_requirements():
    """检查依赖是否安装"""
    try:
        import flask
        import flask_cors
        print("✅ 依赖检查通过")
        return True
    except ImportError as e:
        print(f"❌ 缺少依赖: {e}")
        print("正在安装依赖...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
            print("✅ 依赖安装完成")
            return True
        except subprocess.CalledProcessError:
            print("❌ 依赖安装失败，请手动运行: pip install -r requirements.txt")
            return False

def ensure_directories():
    """确保必要的目录存在"""
    directories = [
        "data",
        "data/chapters", 
        "data/candidates",
        "outputs"
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"✅ 目录已创建: {directory}")

def start_server():
    """启动Web服务器"""
    print("🚀 启动AI小说自动生成系统Web服务器...")
    print("=" * 50)
    
    # 检查依赖
    if not check_requirements():
        return
    
    # 确保目录存在
    ensure_directories()
    
    # 启动服务器
    try:
        from app import app
        print("🌐 服务器地址: http://localhost:5000")
        print("📱 在浏览器中打开上述地址即可使用")
        print("⏹️  按 Ctrl+C 停止服务器")
        print("=" * 50)
        
        # 自动打开浏览器
        try:
            webbrowser.open('http://localhost:5000')
        except:
            pass
        
        app.run(debug=True, host='0.0.0.0', port=5000)
        
    except Exception as e:
        print(f"❌ 启动服务器失败: {e}")
        print("请检查端口5000是否被占用")

if __name__ == '__main__':
    start_server()

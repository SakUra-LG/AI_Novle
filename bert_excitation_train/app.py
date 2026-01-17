#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI小说自动生成系统 - Web API服务器
"""

import os
import json
import glob
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 配置
DATA_DIR = "data"
CHAPTERS_DIR = os.path.join(DATA_DIR, "chapters")
CANDIDATES_DIR = os.path.join(DATA_DIR, "candidates")
OUTPUTS_DIR = "outputs"

def ensure_directories():
    """确保必要的目录存在"""
    for directory in [DATA_DIR, CHAPTERS_DIR, CANDIDATES_DIR, OUTPUTS_DIR]:
        os.makedirs(directory, exist_ok=True)

def get_chapter_files():
    """获取所有章节文件"""
    chapters = []
    chapter_dict = {}
    
    # 扫描chapters目录 - 支持多种命名格式
    chapter_files = glob.glob(os.path.join(CHAPTERS_DIR, "*.txt"))
    for file_path in chapter_files:
        filename = os.path.basename(file_path)
        chapter_num = None
        
        # 格式1: 第X章.txt
        if filename.startswith("第") and filename.endswith(".txt"):
            try:
                chapter_num = int(filename.split("第")[1].split("章")[0])
            except:
                continue
        # 格式2: XX.txt (如01.txt, 02.txt)
        elif filename.replace(".txt", "").isdigit():
            try:
                chapter_num = int(filename.replace(".txt", ""))
            except:
                continue
        
        if chapter_num:
            chapter_dict[chapter_num] = {
                "id": chapter_num,
                "title": f"第{chapter_num}章",
                "file_path": file_path,
                "has_content": True,
                "last_modified": datetime.fromtimestamp(os.path.getmtime(file_path))
            }
    
    # 扫描candidates目录 - 支持多种命名格式
    candidate_files = glob.glob(os.path.join(CANDIDATES_DIR, "**/*.txt"), recursive=True)
    for file_path in candidate_files:
        filename = os.path.basename(file_path)
        chapter_num = None
        
        # 格式1: X_vY.txt
        if "_v" in filename:
            try:
                chapter_num = int(filename.split("_")[0])
            except:
                continue
        # 格式2: XX_vY.txt (如21_v1.txt)
        elif "_v" in filename and filename.split("_")[0].isdigit():
            try:
                chapter_num = int(filename.split("_")[0])
            except:
                continue
        
        if chapter_num:
            if chapter_num in chapter_dict:
                chapter_dict[chapter_num]["has_candidates"] = True
            else:
                chapter_dict[chapter_num] = {
                    "id": chapter_num,
                    "title": f"第{chapter_num}章",
                    "file_path": file_path,
                    "has_content": False,
                    "has_candidates": True,
                    "last_modified": datetime.fromtimestamp(os.path.getmtime(file_path))
                }
    
    # 转换为列表并排序
    chapters = list(chapter_dict.values())
    return sorted(chapters, key=lambda x: x["id"])

def get_chapter_content(chapter_id):
    """获取章节内容"""
    # 首先尝试从chapters目录获取最终版本 - 支持多种命名格式
    final_files = [
        os.path.join(CHAPTERS_DIR, f"第{chapter_id}章.txt"),
        os.path.join(CHAPTERS_DIR, f"{chapter_id:02d}.txt"),
        os.path.join(CHAPTERS_DIR, f"{chapter_id}.txt")
    ]
    
    for final_file in final_files:
        if os.path.exists(final_file):
            with open(final_file, 'r', encoding='utf-8') as f:
                content = f.read()
            return {
                "title": f"第{chapter_id}章",
                "versions": [{
                    "id": 1,
                    "content": content,
                    "score": 85.0,
                    "method": "最终版本",
                    "timestamp": datetime.fromtimestamp(os.path.getmtime(final_file))
                }]
            }
    
    # 如果没有最终版本，从candidates目录获取候选版本 - 支持多种命名格式
    candidate_patterns = [
        os.path.join(CANDIDATES_DIR, f"{chapter_id}_v*.txt"),
        os.path.join(CANDIDATES_DIR, f"{chapter_id:02d}_v*.txt"),
        os.path.join(CANDIDATES_DIR, f"**/{chapter_id}_v*.txt"),
        os.path.join(CANDIDATES_DIR, f"**/{chapter_id:02d}_v*.txt")
    ]
    
    candidate_files = []
    for pattern in candidate_patterns:
        candidate_files.extend(glob.glob(pattern, recursive=True))
    
    # 去重并排序
    candidate_files = sorted(list(set(candidate_files)))
    
    if not candidate_files:
        return None
    
    versions = []
    for i, file_path in enumerate(candidate_files, 1):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            filename = os.path.basename(file_path)
            if "_v" in filename:
                version_num = filename.split("_v")[1].split(".")[0]
            else:
                version_num = str(i)
            
            versions.append({
                "id": i,
                "content": content,
                "score": 70.0 + (i * 5),
                "method": f"候选版本 {version_num}",
                "timestamp": datetime.fromtimestamp(os.path.getmtime(file_path))
            })
        except Exception as e:
            print(f"读取文件失败 {file_path}: {e}")
            continue
    
    if not versions:
        return None
    
    return {
        "title": f"第{chapter_id}章",
        "versions": versions
    }

@app.route('/')
def index():
    """返回主页"""
    return send_from_directory('.', 'index.html')

@app.route('/api/chapters')
def api_chapters():
    """获取章节列表API"""
    try:
        chapters = get_chapter_files()
        return jsonify({
            "success": True,
            "data": chapters
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/chapters/<int:chapter_id>')
def api_chapter_content(chapter_id):
    """获取章节内容API"""
    try:
        content = get_chapter_content(chapter_id)
        if content:
            return jsonify({
                "success": True,
                "data": content
            })
        else:
            return jsonify({
                "success": False,
                "error": "章节不存在"
            }), 404
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/generate/<int:chapter_id>')
def api_generate_chapter(chapter_id):
    """生成章节API"""
    try:
        # 这里应该调用实际的生成脚本
        # 为了演示，我们返回一个模拟的响应
        return jsonify({
            "success": True,
            "message": f"第{chapter_id}章生成任务已启动",
            "task_id": f"gen_{chapter_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/train')
def api_train_model():
    """训练模型API"""
    try:
        # 这里应该调用实际的训练脚本
        return jsonify({
            "success": True,
            "message": "模型训练任务已启动",
            "task_id": f"train_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/stats')
def api_stats():
    """获取统计信息API"""
    try:
        chapters = get_chapter_files()
        total_chapters = len(chapters)
        completed_chapters = len([c for c in chapters if c.get("has_content", False)])
        
        return jsonify({
            "success": True,
            "data": {
                "total_chapters": total_chapters,
                "completed_chapters": completed_chapters,
                "completion_rate": (completed_chapters / total_chapters * 100) if total_chapters > 0 else 0,
                "last_updated": datetime.now().isoformat()
            }
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

if __name__ == '__main__':
    ensure_directories()
    print("AI小说自动生成系统 - Web服务器启动中...")
    print("访问地址: http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能上下文加载器
动态加载章节文件，支持多种命名格式和配置
"""

import os
import json
import glob
from typing import List, Dict, Optional

def load_generation_config(config_file: str = "config/generation_config.json") -> Dict:
    """加载生成配置"""
    if os.path.exists(config_file):
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        # 默认配置
        return {
            "context_settings": {
                "max_context_chapters": 20,
                "recent_chapters_count": 3,
                "outline_max_length": 500,
                "snippet_max_length": 150,
                "chapter_summary_length": 200
            },
            "file_patterns": {
                "chapter_files": ["*.txt"],
                "exclude_patterns": ["第*章.txt", "*_evaluation.json"],
                "candidate_patterns": ["*_v*.txt"]
            }
        }

def scan_chapter_files(chapters_dir: str, exclude_patterns: List[str] = None) -> List[tuple]:
    """扫描章节文件，返回(章节号, 文件路径)的列表"""
    if exclude_patterns is None:
        exclude_patterns = ["第*章.txt", "*_evaluation.json"]
    
    chapter_files = []
    
    if not os.path.exists(chapters_dir):
        return chapter_files
    
    # 获取所有txt文件
    all_files = glob.glob(os.path.join(chapters_dir, "*.txt"))
    
    for file_path in all_files:
        filename = os.path.basename(file_path)
        
        # 检查是否在排除列表中
        should_exclude = False
        for pattern in exclude_patterns:
            if glob.fnmatch.fnmatch(filename, pattern):
                should_exclude = True
                break
        
        if should_exclude:
            continue
        
        # 尝试提取章节号
        chapter_num = extract_chapter_number(filename)
        if chapter_num is not None:
            chapter_files.append((chapter_num, file_path))
    
    return chapter_files

def extract_chapter_number(filename: str) -> Optional[int]:
    """从文件名中提取章节号"""
    # 移除.txt扩展名
    name_without_ext = filename.replace('.txt', '')
    
    # 尝试直接转换为数字 (如: 01.txt, 24.txt)
    try:
        return int(name_without_ext)
    except ValueError:
        pass
    
    # 尝试其他格式
    # 格式: ch1.txt, ch24.txt
    if name_without_ext.startswith('ch'):
        try:
            return int(name_without_ext[2:])
        except ValueError:
            pass
    
    # 格式: chapter1.txt, chapter24.txt
    if name_without_ext.startswith('chapter'):
        try:
            return int(name_without_ext[7:])
        except ValueError:
            pass
    
    return None

def load_novel_context_smart(max_chapters: int = None, config_file: str = "config/generation_config.json") -> Dict:
    """智能加载小说上下文信息"""
    config = load_generation_config(config_file)
    
    if max_chapters is None:
        max_chapters = config["context_settings"]["max_context_chapters"]
    
    context = {
        'previous_chapters': [],
        'outline': '',
        'characters': {},
        'settings': {},
        'config': config
    }
    
    # 动态读取章节正文
    chapters_dir = "data/chapters"
    exclude_patterns = config["file_patterns"]["exclude_patterns"]
    
    chapter_files = scan_chapter_files(chapters_dir, exclude_patterns)
    
    # 按章节号排序，取前max_chapters章
    chapter_files.sort(key=lambda x: x[0])
    chapter_files = chapter_files[:max_chapters]
    
    print(f"找到 {len(chapter_files)} 个章节文件")
    
    for chapter_num, file_path in chapter_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    context['previous_chapters'].append({
                        'chapter': chapter_num,
                        'content': content,
                        'file_path': file_path
                    })
        except Exception as e:
            print(f"读取章节文件 {file_path} 失败: {e}")
    
    # 读取章节梗概
    outline_file = "outputs/master_ctx.txt"
    if os.path.exists(outline_file):
        with open(outline_file, 'r', encoding='utf-8') as f:
            context['outline'] = f.read()
    
    print(f"成功加载 {len(context['previous_chapters'])} 章前文内容")
    return context

def get_available_chapters(chapters_dir: str = "data/chapters") -> List[int]:
    """获取所有可用的章节号"""
    chapter_files = scan_chapter_files(chapters_dir)
    return [chapter_num for chapter_num, _ in chapter_files]

def print_context_info(context: Dict):
    """打印上下文信息"""
    print("=" * 50)
    print("上下文加载信息")
    print("=" * 50)
    print(f"前文章节数: {len(context['previous_chapters'])}")
    
    if context['previous_chapters']:
        chapters = [ch['chapter'] for ch in context['previous_chapters']]
        print(f"章节范围: {min(chapters)} - {max(chapters)}")
        print(f"章节列表: {chapters}")
    
    print(f"梗概文件: {'已加载' if context['outline'] else '未找到'}")
    print("=" * 50)

if __name__ == "__main__":
    # 测试功能
    context = load_novel_context_smart()
    print_context_info(context)
    
    # 显示所有可用章节
    available_chapters = get_available_chapters()
    print(f"\n所有可用章节: {available_chapters}")

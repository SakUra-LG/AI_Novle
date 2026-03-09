#!/bin/bash
# 增强版RAG生成器 v2.0 使用示例

# 示例1：生成第1章（基础用法）
echo "=== 示例1：生成第1章 ==="
python scripts/enhanced_rag_generator_v2.py --chapter 1

# 示例2：生成第2章（会自动加载第1章作为上下文）
echo "=== 示例2：生成第2章 ==="
python scripts/enhanced_rag_generator_v2.py --chapter 2

# 示例3：生成第3章，带额外提示
echo "=== 示例3：生成第3章，带额外提示 ==="
python scripts/enhanced_rag_generator_v2.py \
  --chapter 3 \
  --prompt "请重点突出主角的冷静预判和提前布局"

# 示例4：生成第4章，调整参数
echo "=== 示例4：生成第4章，调整参数 ==="
python scripts/enhanced_rag_generator_v2.py \
  --chapter 4 \
  --versions 5 \
  --min_score 75 \
  --min_emotion 0.7

# 示例5：生成第5章，指定项目
echo "=== 示例5：生成第5章，指定项目 ==="
python scripts/enhanced_rag_generator_v2.py \
  --project "暗河噬城" \
  --chapter 5

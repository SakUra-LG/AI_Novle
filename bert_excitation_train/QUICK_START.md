# ⚡ 评分引导训练 - 快速开始

## 🎯 三步使用

### 步骤1：评分样本
```bash
python scripts/incremental_sample_scorer.py
```
为42个样本打分（70-100分），区分质量等级

### 步骤2：训练模型
```bash
python scripts/score_guided_lora_training.py
```
高分样本权重更大，模型学习"什么能获得高分"

### 步骤3：使用模型
```python
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel

base_model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-0.5B")
model = PeftModel.from_pretrained(base_model, "checkpoints/score_guided_lora")
tokenizer = AutoTokenizer.from_pretrained("checkpoints/score_guided_lora")
```

---

## 💡 核心原理（一句话）

**高分样本的训练权重更大（1.84倍），模型更倾向学习高分特征，生成时主动追求高质量。**

---

## 📊 技术细节

### 权重计算
```python
weight = (score / 100) ** 2

70分 → 0.49  (影响力小)
85分 → 0.72  (影响力中)
95分 → 0.90  (影响力大)
```

### 加权损失
```python
loss = weight * CrossEntropyLoss(prediction, target)

反向传播时：
  高权重 → 大梯度 → 参数大幅更新 → 强化记忆
  低权重 → 小梯度 → 参数小幅更新 → 影响力弱
```

### 生成效果
```
训练后模型倾向：
  高概率选择高分特征pattern
  → "密集的脚步声" 而非 "他很紧张"
  → 评分提升5-15%
```

---

## 🔧 常用参数

```bash
# 标准训练（推荐）
python scripts/score_guided_lora_training.py

# 自定义参数
python scripts/score_guided_lora_training.py \
    --weight_method quadratic \  # linear/quadratic/exponential
    --weight_strength 1.0 \      # 0.5-2.0
    --epochs 3 \
    --batch_size 4
```

---

## 📈 预期效果

| 指标 | 提升 |
|------|------|
| 平均评分 | +9.8% |
| 90+占比 | +113% |
| 紧张感密度 | +52% |

---

## 📚 详细文档

- **完整原理**：`USAGE_AND_PRINCIPLES.md`
- **使用指南**：`SCORE_GUIDED_TRAINING_GUIDE.md`


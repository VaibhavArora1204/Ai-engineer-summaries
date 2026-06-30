# Pipeline Parallelism — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Multi-node model serving with slow inter-node interconnects.**

When a model spans multiple nodes (e.g., 2 servers, each with 8 GPUs), tensor parallelism's all-reduce communication becomes a bottleneck because inter-node bandwidth (InfiniBand ~400 GB/s) is much slower than intra-node NVLink (600-900 GB/s). Pipeline parallelism minimizes inter-node communication by only passing activations between stages — no all-reduce.

---

## How It Works

### The Mechanism

Assign **different layers** to different GPUs (or groups of GPUs). Data flows through the pipeline stage by stage.

```
80-layer model, 4 GPUs:
  GPU 0: Layers 0-19   (Stage 0)
  GPU 1: Layers 20-39  (Stage 1)
  GPU 2: Layers 40-59  (Stage 2)
  GPU 3: Layers 60-79  (Stage 3)

Forward pass:
  Input → GPU 0 (layers 0-19) → activations → GPU 1 (layers 20-39)
       → activations → GPU 2 (layers 40-59) → activations
       → GPU 3 (layers 60-79) → Output

Communication: only activations between stages
  Size per step: hidden_size × batch_size × seq_len × dtype_bytes
  For Llama-3 70B: 8192 × 1 × 1 × 2 = 16 KB per token per stage boundary
  Much smaller than tensor parallelism's all-reduce.
```

### The Pipeline Bubble Problem

When one GPU is processing its stage, the others are idle:

```
Time →
GPU 0: [FORWARD stage 0] [idle............] [idle............] [idle]
GPU 1: [idle............] [FORWARD stage 1] [idle............] [idle]
GPU 2: [idle............] [idle............] [FORWARD stage 2] [idle]
GPU 3: [idle............] [idle............] [idle............] [FORWARD stage 3]

GPU utilization: ~25% (each GPU active 1/4 of the time)
This is called the "pipeline bubble."
```

### Micro-Batching (GPipe Solution)

Split the mini-batch into smaller **micro-batches** and pipeline them:

```
4 micro-batches (m1, m2, m3, m4), 4 stages:

Time →
GPU 0: [m1] [m2] [m3] [m4] [idle] [idle] [idle]
GPU 1:      [m1] [m2] [m3] [m4]  [idle] [idle]
GPU 2:           [m1] [m2] [m3]  [m4]  [idle]
GPU 3:                [m1] [m2]  [m3]  [m4]

Bubble = (num_stages - 1) out of (num_microbatches + num_stages - 1) steps
With 4 stages, 4 micro-batches: bubble = 3/7 ≈ 43%
With 4 stages, 16 micro-batches: bubble = 3/19 ≈ 16%
With 4 stages, 64 micro-batches: bubble = 3/67 ≈ 4.5%
```

**More micro-batches → smaller bubble → better utilization.** But each micro-batch is smaller, so individual matmuls are less efficient.

### 1F1B Schedule (One-Forward-One-Backward)

For training, interleave forward and backward passes to keep all GPUs busy. For inference (forward only), the schedule simplifies to continuous micro-batch pipelining.

---

## The Numbers

| Setup | Bubble Fraction | GPU Utilization | Use Case |
|-------|----------------|-----------------|----------|
| 2 stages, 8 micro-batches | 11% | ~89% | 2-node deployment |
| 4 stages, 16 micro-batches | 16% | ~84% | 4-node large model |
| 4 stages, 4 micro-batches | 43% | ~57% | Small batch (interactive) |
| 8 stages, 32 micro-batches | 18% | ~82% | Very large model |

**For inference (not training):** Pipeline parallelism is less commonly used because:
1. Interactive serving has batch_size=1 → only 1 micro-batch → maximum bubble
2. Continuous batching (topic 17) helps but each decode step still pipelines through all stages

**Where PP shines for inference:** Offline batch processing where you can fill the pipeline with many micro-batches.

---

## Where It Lives in the Stack

**Layer: Serving framework configuration.**

Like tensor parallelism, pipeline parallelism is configured at deployment time, not in model code.

```bash
# TensorRT-LLM — 2-way pipeline parallelism + 4-way tensor parallelism
# Total: 8 GPUs (2 nodes × 4 GPUs/node)
trtllm-build --model meta-llama/Llama-3-70B-Instruct \
  --tp 4 --pp 2

# vLLM — pipeline parallelism
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3-70B-Instruct \
  --tensor-parallel-size 4 \
  --pipeline-parallel-size 2
```

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| Cross-node model serving | Pipeline bubbles (wasted GPU cycles) |
| Minimal inter-stage communication | Higher latency per request (must traverse all stages) |
| Works with slow interconnects (InfiniBand) | Poor utilization at small batch sizes |
| Can serve arbitrarily large models | Load balancing across stages (stages may have unequal compute) |

**Critical tradeoff for interactive serving:** Pipeline parallelism adds latency because each token must sequentially pass through all stages. For a 4-stage pipeline, minimum latency is 4× the per-stage computation time, regardless of batch size.

---

## What It Combines With

**Stacks well with:**
- **Tensor Parallelism (10):** The standard approach: TP within a node, PP across nodes. Megatron-LM pioneered this combination.
- **Continuous Batching (17):** The scheduler pipelines different requests through different stages. New requests can enter stage 0 while earlier requests are in stage 3.
- **KV Caching (01):** Each stage maintains KV cache only for its layers. Stage 0 has KV cache for layers 0-19, stage 1 for layers 20-39, etc.
- **FlashAttention (03):** Each stage runs FA independently on its layers.
- **Quantized Kernels (09):** Each stage's weights can be quantized independently.

**Conflicts with:**
- **Early Exit Decoding (06):** If a token exits at layer 10 (stage 0), stages 1-3 do nothing for that token. Pipeline bubbles get worse.
- **Speculative Decoding (02):** The verify step must pipeline through all stages, adding latency. Draft model typically fits on one GPU/stage.
- **Sequence Parallelism (12):** SP splits along the sequence dimension within a stage. Combining SP + PP + TP (3D parallelism) is complex but done in Megatron-LM.

---

## Implementation Today

| Framework | Support | Notes |
|-----------|---------|-------|
| **vLLM** | `--pipeline-parallel-size N` | Supported for multi-node serving. |
| **TensorRT-LLM** | `--pp N` | Full support with TP+PP combination. |
| **Megatron-LM** | Reference implementation | Most mature PP implementation. |
| **TGI** | Limited | Basic support. |
| **DeepSpeed** | Full support | Training-focused; inference via DeepSpeed-Inference. |
| **llama.cpp** | Not supported | Single-process, no pipeline parallelism. |

---

## Primary Sources

- **GPipe:** Huang et al. 2019, "GPipe: Efficient Training of Giant Neural Networks using Pipeline Parallelism" — https://arxiv.org/abs/1811.06965
- **Megatron-LM pipeline schedule:** Narayanan et al. 2021 — https://arxiv.org/abs/2104.04473
- **PipeDream (1F1B schedule):** https://arxiv.org/abs/1806.03377
- **Zero Bubble Pipeline Parallelism:** Qi et al. 2024 — https://arxiv.org/abs/2401.10241

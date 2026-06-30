# Tensor Parallelism — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Model too large for a single GPU's VRAM.**

Llama-3 70B at BF16 requires ~140 GB just for weights. An A100 has 80 GB. The model physically cannot fit. Tensor parallelism splits individual weight matrices across multiple GPUs so the model can be served.

---

## How It Works

### The Mechanism

Split each weight matrix **column-wise** or **row-wise** across N GPUs. Each GPU holds 1/N of every layer's weights and computes a partial result. Partial results are combined via **all-reduce** communication.

```
For a linear layer: Y = X × W

Column-wise split across 2 GPUs:
  W = [W₁ | W₂]  (split columns)
  
  GPU 0: Y₀ = X × W₁   (partial result, first half of output columns)
  GPU 1: Y₁ = X × W₂   (partial result, second half of output columns)
  
  Result: Y = [Y₀ | Y₁]  (concatenate — no communication needed for this step)

Row-wise split across 2 GPUs:
  W = [W₁]  (split rows)
      [W₂]
  
  GPU 0: Y₀ = X₁ × W₁  (partial sum)
  GPU 1: Y₁ = X₂ × W₂  (partial sum)
  
  Result: Y = Y₀ + Y₁   (all-reduce — requires communication)
```

### Attention Layer Parallelism (Megatron-LM)

The attention mechanism parallelizes naturally across heads:

```
Multi-head attention with 64 heads, 4 GPUs:
  GPU 0: heads 0-15   (Q₀, K₀, V₀ → Attn₀)
  GPU 1: heads 16-31  (Q₁, K₁, V₁ → Attn₁)
  GPU 2: heads 32-47  (Q₂, K₂, V₂ → Attn₂)
  GPU 3: heads 48-63  (Q₃, K₃, V₃ → Attn₃)
  
Output projection (row-parallel):
  O = concat(Attn₀, Attn₁, Attn₂, Attn₃) × W_o
  Split W_o row-wise → each GPU computes partial sum → all-reduce

FFN layer:
  Gate projection: column-parallel (no communication)
  Up projection:   column-parallel (no communication)  
  Down projection: row-parallel (all-reduce at the end)

Total all-reduce operations per transformer layer: 2
  (one after attention output projection, one after FFN down projection)
```

### Communication Cost

```
All-reduce per layer = 2 × (N-1)/N × hidden_size × batch_size × seq_len × dtype_bytes

For Llama-3 70B (hidden=8192), BF16, batch=1, seq=1, 4 GPUs:
  = 2 × 3/4 × 8192 × 1 × 1 × 2 = 24,576 bytes per layer
  × 80 layers = ~2 MB per decode step (negligible)

For large batches / long sequences:
  batch=64, seq=4096: ~8 GB per decode step
  This becomes significant — interconnect bandwidth matters.
```

**NVLink vs PCIe vs InfiniBand:**
| Interconnect | Bandwidth | Use |
|--------------|-----------|-----|
| NVLink (intra-node, A100) | 600 GB/s | Tensor parallelism within a node. Fast enough. |
| NVLink (intra-node, H100) | 900 GB/s | Even better. |
| PCIe 4.0 | ~32 GB/s | Too slow for tensor parallelism. Avoid. |
| InfiniBand (inter-node) | ~400 GB/s | Marginal for TP. Use pipeline parallelism across nodes instead. |

**Rule:** Tensor parallelism within a node (NVLink). Pipeline parallelism across nodes (InfiniBand).

---

## The Numbers

| GPUs | Model Fits | Throughput | Communication Overhead |
|------|-----------|------------|----------------------|
| 1 (no TP) | ≤40B at BF16 | Baseline | 0% |
| 2 | ≤80B at BF16 | ~1.8× | ~10% |
| 4 | ≤160B at BF16 | ~3.4× | ~15% |
| 8 | ≤320B at BF16 | ~6× | ~25% |

**Scaling efficiency degrades with GPU count** because communication overhead grows. Typical efficiency: 85-95% for 2 GPUs, 70-85% for 4, 60-75% for 8.

---

## Where It Lives in the Stack

**Layer: Serving framework configuration. No model code changes needed.**

vLLM, TGI, and TensorRT-LLM handle tensor parallelism transparently. You specify `tensor_parallel_size=N` and the framework shards the model automatically.

```bash
# vLLM — 4-way tensor parallelism
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3-70B-Instruct \
  --tensor-parallel-size 4
```

Internally, the framework:
1. Loads the full model checkpoint
2. Shards each weight matrix across N GPUs
3. Inserts all-reduce operations between layers
4. Manages per-GPU KV caches

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| Serve models that don't fit on one GPU | Requires fast interconnect (NVLink) |
| Near-linear throughput scaling (2-8 GPUs) | 10-25% overhead from all-reduce communication |
| Lower per-request latency (parallel compute) | All GPUs must be in the same node for efficiency |
| | Cost: N GPUs instead of 1 |

**When tensor parallelism is wrong:** If the model fits on one GPU (e.g., 8B model on A100 80GB), tensor parallelism adds communication overhead with no benefit. Use data parallelism (multiple independent replicas) instead.

---

## What It Combines With

**Stacks well with:**
- **Pipeline Parallelism (11):** Combine TP (intra-node) with PP (inter-node) for very large models across multiple nodes. This is the Megatron-LM approach.
- **KV Caching (01):** Each GPU maintains its shard of the KV cache (only the heads assigned to it).
- **FlashAttention (03):** Each GPU runs FA on its shard of heads. No conflict.
- **PagedAttention (04):** Block tables are per-GPU, managing each GPU's KV cache shard.
- **Continuous Batching (17):** Scheduler manages a single logical batch; each GPU processes its shard of every sequence.
- **Quantized Kernels (09):** Quantized weights are smaller → less data to shard and communicate.
- **Speculative Decoding (02):** The verify forward pass distributes across GPUs via TP normally.

**Conflicts with:**
- **Sequence Parallelism (12):** TP and SP are complementary but operate on different dimensions (hidden vs sequence). Combined in Megatron-LM.
- **Memory Offloading (15):** TP assumes all weight shards are in GPU VRAM. Offloading shards to CPU defeats the purpose.

---

## Implementation Today

| Framework | Support | Notes |
|-----------|---------|-------|
| **vLLM** | `--tensor-parallel-size N` | Automatic sharding. Requires N GPUs with NVLink. |
| **TGI** | `--num-shard N` | Same concept. |
| **TensorRT-LLM** | Built-in | Configured during model build step. |
| **SGLang** | `--tp N` | Same as vLLM. |
| **Megatron-LM** | Reference implementation | Most flexible, lowest-level control. For training + inference. |
| **llama.cpp** | Limited | `--split-mode` for basic model splitting. Not full TP. |
| **DeepSpeed** | Built-in | For training. DeepSpeed-Inference for serving. |

---

## Primary Sources

- **Megatron-LM:** Shoeybi et al. 2019, "Megatron-LM: Training Multi-Billion Parameter Language Models Using Model Parallelism" — https://arxiv.org/abs/1909.08053
- **Megatron-LM v2 (pipeline + tensor):** https://arxiv.org/abs/2104.04473
- **NCCL (NVIDIA Collective Communications Library):** https://developer.nvidia.com/nccl
- **NVLink specification:** https://www.nvidia.com/en-us/data-center/nvlink/

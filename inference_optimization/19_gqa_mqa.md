# Grouped Query Attention / Multi-Query Attention (GQA/MQA) — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: KV cache memory scales linearly with the number of attention heads.**

In standard Multi-Head Attention (MHA), every query head has its own dedicated key head and value head. For a model with 64 attention heads, there are 64 K heads and 64 V heads. The KV cache stores all of them:

```
MHA KV cache: 2 × num_layers × num_heads × head_dim × seq_len × dtype_bytes

For Llama-3 70B with MHA (hypothetical, 64 Q heads = 64 KV heads):
  = 2 × 80 × 64 × 128 × 8192 × 2 = ~160 GB per request

This is more than the model weights themselves.
The KV cache is the dominant memory consumer at long contexts.
```

GQA/MQA reduces the number of K/V heads, shrinking the KV cache while preserving most of MHA's quality.

---

## How It Works

### Multi-Head Attention (MHA) — Baseline

```
Q heads: 64    K heads: 64    V heads: 64
Each Q head has its own dedicated K and V head.
Total KV cache: 64 × head_dim × seq_len × 2 (K and V)
```

### Multi-Query Attention (MQA) — Shazeer 2019

```
Q heads: 64    K heads: 1     V heads: 1
ALL 64 query heads share a SINGLE K head and SINGLE V head.
Total KV cache: 1 × head_dim × seq_len × 2

KV cache reduction: 64×
```

**How it works mechanically:**
```
MHA:  For head i: Attn_i = softmax(Q_i × K_i^T / √d) × V_i
      Each head has unique Q, K, V projections.

MQA:  For head i: Attn_i = softmax(Q_i × K_shared^T / √d) × V_shared
      Each head has unique Q, but ALL share one K and one V.
      K and V projection matrices: [d_model → head_dim] instead of [d_model → num_heads × head_dim]
```

**Quality impact:** MQA degrades quality on some tasks because all heads attend to the same K/V representation. The attention mechanism loses its ability to capture diverse patterns across heads.

### Grouped Query Attention (GQA) — Ainslie et al. 2023

```
Q heads: 64    K heads: 8     V heads: 8
Groups of 8 Q heads share 1 K head and 1 V head.
Total KV cache: 8 × head_dim × seq_len × 2

KV cache reduction: 8× (vs MHA)
Quality: near-MHA
Speed: near-MQA
```

```
GQA with G=8 groups, 64 Q heads:

Group 0: Q heads 0-7   share K₀, V₀
Group 1: Q heads 8-15  share K₁, V₁
Group 2: Q heads 16-23 share K₂, V₂
...
Group 7: Q heads 56-63 share K₇, V₇

Each group's Q heads compute independent attention scores
against the SAME K and V, then produce independent attention outputs.
```

### The Spectrum

```
MHA ←────────── GQA ────────────→ MQA
64 KV heads     8 KV heads        1 KV head
Maximum quality Good quality       Some quality loss
Maximum memory  8× less memory    64× less memory
Slowest decode  Fast decode       Fastest decode
```

GQA is the optimal tradeoff for production. It's what virtually all modern models use.

---

## The Numbers

| Configuration | KV Cache (70B, 8K ctx, BF16) | Decode Speed | Quality (vs MHA) |
|--------------|------------------------------|--------------|-------------------|
| MHA (64 KV heads) | ~160 GB | 1× | Baseline |
| GQA-8 (8 KV heads) | ~20 GB | ~1.7× | -0.1% to -0.5% |
| GQA-4 (4 KV heads) | ~10 GB | ~1.9× | -0.5% to -1% |
| MQA (1 KV head) | ~2.5 GB | ~2× | -1% to -3% |

**Llama-3 70B uses GQA with 8 KV groups:** 64 Q heads, 8 KV heads. The KV cache is 8× smaller than a hypothetical MHA version. This is what makes 128K context feasible on 4 A100s.

**Impact on serving:**
```
GQA-8 at 128K context: KV cache ≈ 20 GB per request
MHA at 128K context:    KV cache ≈ 160 GB per request

On an A100 80GB (after model weights), remaining VRAM for KV cache:
  GQA-8: can serve ~2 concurrent 128K requests
  MHA:   cannot serve even 1 concurrent 128K request
```

---

## Where It Lives in the Stack

**Layer: Model architecture — baked into the model at training time.**

GQA/MQA is a **training-time decision**, not a serving optimization. You cannot convert an MHA model to GQA post-training without retraining. The K/V projection weight matrices have different shapes:

```
MHA:  W_k shape = [d_model, num_heads × head_dim]     = [8192, 8192]
GQA:  W_k shape = [d_model, num_kv_heads × head_dim]  = [8192, 1024]  (8× smaller)
```

**Models using GQA:**
| Model | Q Heads | KV Heads | KV Reduction |
|-------|---------|----------|-------------|
| Llama-3 8B | 32 | 8 | 4× |
| Llama-3 70B | 64 | 8 | 8× |
| Mistral 7B | 32 | 8 | 4× |
| Gemma 2 27B | 32 | 16 | 2× |
| Falcon 40B | 64 (MQA) | 1 | 64× |
| StarCoder | 48 (MQA) | 1 | 48× |

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| N× smaller KV cache (N = Q_heads / KV_heads) | Slight quality degradation (empirically small for GQA) |
| Proportionally faster decode | Must be chosen at training time (cannot retrofit) |
| More concurrent requests in same VRAM | |
| Enables long-context serving | |

**GQA has essentially no downside at moderate group sizes (4-8 KV heads).** The quality difference vs MHA is within noise on most benchmarks. This is why every major model released since mid-2023 uses GQA.

---

## What It Combines With

**Stacks well with:**
- **KV Caching (01):** GQA directly reduces the KV cache that topic 01 describes. Smaller cache = more concurrent requests.
- **PagedAttention (04):** Smaller KV per token = more tokens per block = more efficient paging.
- **FlashAttention (03):** FA supports GQA natively. The kernel handles the Q→KV head mapping internally.
- **Prefix Caching (20):** Smaller KV per token means shared prefix blocks consume less memory.
- **Continuous Batching (17):** Smaller KV cache per request means more requests fit in the running batch.
- **Quantized KV cache (09):** GQA + INT8 KV cache = 16× reduction vs MHA FP16 cache.
- **Tensor Parallelism (10):** KV heads are distributed across GPUs. With GQA, each GPU holds fewer KV heads → less memory per GPU.

**Conflicts with:**
- Nothing. GQA is universally beneficial for serving efficiency. It's a model architecture choice, not a serving decision.

---

## Implementation Today

**You don't "implement" GQA — you select a model that uses it.** All modern models do:

| Framework | GQA Support |
|-----------|-------------|
| **vLLM** | ✅ (automatic detection from model config) |
| **TGI** | ✅ |
| **TensorRT-LLM** | ✅ |
| **SGLang** | ✅ |
| **llama.cpp** | ✅ |
| **HuggingFace Transformers** | ✅ |

The model's `config.json` specifies `num_attention_heads` (Q heads) and `num_key_value_heads` (KV heads). All frameworks read this and handle the GQA logic automatically.

```json
// Llama-3 70B config.json (excerpt)
{
  "num_attention_heads": 64,
  "num_key_value_heads": 8,
  "hidden_size": 8192,
  "num_hidden_layers": 80
}
```

### Converting MHA to GQA (Uptraining)

The GQA paper proposes a method to convert existing MHA checkpoints to GQA:

```
1. Group existing KV heads by similarity
2. Average the weights within each group → new shared KV head
3. Continue training for a small number of steps (5-10% of original)

This is cheaper than training from scratch but still requires
compute. It's been used to create GQA variants of existing models.
```

---

## Primary Sources

- **Multi-Query Attention (MQA):** Shazeer 2019, "Fast Transformer Decoding: One Write-Head is All You Need" — https://arxiv.org/abs/1911.02150
- **Grouped Query Attention (GQA):** Ainslie et al. 2023, "GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints" — https://arxiv.org/abs/2305.13245
- **Llama-3 technical report:** https://arxiv.org/abs/2407.21783

# KV-Caching — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Redundant computation during autoregressive decoding.**

During text generation, an LLM produces one token at a time. At each step, the attention mechanism needs the Key (K) and Value (V) projections of *every previous token* to compute attention scores for the new token. Without caching, the model recomputes K and V for all previous tokens at every single generation step.

For a sequence of length `n`, generating token `n+1` requires computing attention over all `n` previous positions. Generating token `n+2` requires all `n+1`. This means:

- Step 1: compute K, V for 1 token
- Step 2: recompute K, V for tokens 1-2
- Step 3: recompute K, V for tokens 1-3
- ...
- Step n: recompute K, V for tokens 1 through n

Total K/V computations: `n(n+1)/2` — quadratic. For a 4096-token generation, that's ~8.4 million redundant projection operations.

**Without KV caching, autoregressive LLM inference is computationally infeasible at production scale.**

---

## How It Works

### The Mechanism

The Transformer attention block computes three projections from the input hidden states:

```
Q = X × W_q    (Query — what am I looking for?)
K = X × W_k    (Key — what do I contain?)
V = X × W_v    (Value — what information do I carry?)

Attention(Q, K, V) = softmax(Q × K^T / √d_k) × V
```

**With KV caching:**

1. **Prefill phase** (processing the input prompt): Run a single forward pass over all prompt tokens in parallel. Compute K and V for every token at every layer. Store these tensors in a dedicated memory region — the **KV cache**.

2. **Decode phase** (generating tokens one at a time): For each new token:
   - Compute Q, K, V for just the *new* token (one set of projections)
   - Append the new K and V to the existing cache
   - Compute attention: new token's Q attends to *all cached K/V* plus its own
   - No recomputation of previous tokens' K/V

**Before KV caching:**
```
Step t: compute K,V for ALL tokens [0...t-1], then compute attention
Cost per step: O(t × d_model) for projections + O(t²) for attention
Total for n tokens: O(n² × d_model) projections + O(n³) attention
```

**After KV caching:**
```
Step t: compute K,V for token t ONLY, append to cache, compute attention
Cost per step: O(d_model) for projections + O(t) for attention (dot product with cache)
Total for n tokens: O(n × d_model) projections + O(n²) attention
```

The projection cost drops from quadratic to linear. Attention remains quadratic in sequence length but is now bounded by the dot product against the cache rather than full recomputation.

### Data Structures

The KV cache is a tensor of shape:

```
[num_layers, 2, batch_size, num_heads, seq_len, head_dim]
            ^
            K and V stored separately
```

Each layer in the Transformer has its own independent KV cache. During each decode step, new K/V vectors are concatenated along the `seq_len` dimension.

---

## The Numbers

### Memory Cost Formula

```
KV cache size (bytes) = 2 × num_layers × num_heads × head_dim × seq_len × batch_size × bytes_per_element
```

| Model | Params | Layers | Heads | Head Dim | Context | KV Cache (FP16, batch=1) |
|-------|--------|--------|-------|----------|---------|--------------------------|
| Llama-3 8B | 8B | 32 | 32 (8 KV heads, GQA) | 128 | 8,192 | ~2 GB |
| Llama-3 70B | 70B | 80 | 64 (8 KV heads, GQA) | 128 | 8,192 | ~10 GB |
| Llama-3 70B | 70B | 80 | 64 (8 KV heads, GQA) | 128 | 128,000 | ~160 GB |
| GPT-4 (est.) | ~1.8T | 120 | 128 (est.) | 128 | 128,000 | ~500+ GB |

**Critical insight:** At long contexts, the KV cache alone exceeds the model's weight memory. For Llama-3 70B at 128K context in FP16, the KV cache (160 GB) exceeds the model weights (~140 GB). **Memory is the binding constraint for LLM serving, not compute.**

### Speedup

KV caching doesn't change the *throughput* of generation — it eliminates *wasted recomputation*. Without it, generation at 4096 tokens would be ~4096× slower than necessary because every step redundantly recomputes all previous projections.

It is not an "optimization" you toggle on. It is a **mandatory prerequisite** for any viable LLM inference system.

---

## Where It Lives in the Stack

**Layer: Serving framework + model runtime.**

KV caching is implemented at the intersection of the model's forward pass logic and the serving framework's memory manager.

- **Model level:** The model's `forward()` method must accept and return `past_key_values` — a tuple of cached K/V tensors per layer. HuggingFace Transformers, vLLM, and TGI all implement this.
- **Serving level:** The serving framework (vLLM, TGI, TensorRT-LLM) manages cache allocation, eviction, and sharing across requests. This is where PagedAttention (topic 04) and Prefix Caching (topic 20) operate.

You do not implement KV caching yourself. Every modern inference framework has it built in. Your job is to **manage its memory footprint**.

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| Linear projection cost instead of quadratic | GPU VRAM proportional to sequence length × batch size |
| Viable autoregressive generation | Maximum concurrent requests bounded by available KV cache memory |
| Prerequisite for all other serving optimizations | Long contexts (128K+) become memory-dominated, not compute-dominated |

**The fundamental tradeoff of KV caching:** You trade **memory** for **compute**. Every token you generate permanently occupies VRAM until the request completes. This is why serving throughput is ultimately a memory management problem.

**Accuracy:** Zero tradeoff. KV caching produces mathematically identical results to full recomputation. It is not an approximation.

---

## What It Combines With

**Stacks well with:**
- **PagedAttention (04):** Solves the memory fragmentation problem that KV caching creates. Without PagedAttention, KV cache is allocated contiguously per request, wasting 60-80% of reserved memory.
- **GQA/MQA (19):** Reduces the `num_heads` dimension of the KV cache. GQA in Llama-3 uses 8 KV heads instead of 64 Q heads → 8× smaller cache.
- **Prefix Caching (20):** Shares cached K/V blocks across requests with common prefixes. Eliminates redundant prefill for shared system prompts.
- **Continuous Batching (17):** Requires KV caching to work — the scheduler must track per-request cache state to insert/remove requests from running batches.
- **Mixed Precision (08) / Quantized Kernels (09):** Storing KV cache in INT8 instead of FP16 halves cache memory. KIVI achieves 2-bit KV cache with tuning-free asymmetric quantization.

**Conflicts with:**
- Nothing. KV caching is the foundation layer. Every other optimization in this list either builds on it or manages it.

---

## Implementation Today

| Framework | KV Caching | Notes |
|-----------|------------|-------|
| vLLM | Built-in, always on | Managed via PagedAttention. `gpu_memory_utilization` controls how much VRAM is reserved for KV cache. |
| TGI (HuggingFace) | Built-in, always on | Standard HF cache management. |
| TensorRT-LLM | Built-in, always on | Optimized CUDA kernels for cache append. Supports FP8 cache on H100. |
| SGLang | Built-in, always on | RadixAttention for automatic prefix sharing. |
| llama.cpp | Built-in, always on | `--ctx-size` parameter controls maximum cache size. |
| HuggingFace Transformers | Built-in | `model.generate()` uses `past_key_values` internally. `use_cache=True` (default). |

**Entry point:** You don't "enable" KV caching — you manage its limits. The key parameters:
- `max_model_len` (vLLM): Maximum sequence length → determines maximum per-request cache size
- `gpu_memory_utilization` (vLLM): Fraction of GPU VRAM available for KV cache (rest is model weights + overhead)
- `--ctx-size` (llama.cpp): Maximum context window

### KV Cache Compression (Active Research)

When standard KV caching consumes too much memory, compression variants trade slight quality loss for dramatically more concurrent requests:

| Technique | Approach | Compression | Quality Impact |
|-----------|----------|-------------|----------------|
| **KIVI** | 2-bit asymmetric quantization of K/V tensors | 8× | <1% on most benchmarks |
| **KVQuant** | Per-channel quantization, 10-bit | 1.6× | Enables 10M token context |
| **SnapKV** | Evict unimportant KV entries before decode | Variable | Model-aware; preserves quality on attention-heavy tokens |
| **H2O (Heavy Hitter Oracle)** | Keep only high-attention tokens + recent window | 5-10× | Task-dependent; degrades on long-range dependency tasks |
| **MiniCache** | Cross-layer merging in depth dimension | 2-4× | Exploits KV similarity across adjacent layers |

---

## Primary Sources

- **Original attention mechanism:** Vaswani et al. 2017, "Attention Is All You Need" — https://arxiv.org/abs/1706.03762
- **KVQuant (10M context):** https://arxiv.org/abs/2401.18079
- **KIVI 2-bit KV cache:** https://arxiv.org/abs/2402.02750
- **SnapKV (model-aware eviction):** https://arxiv.org/abs/2404.14469
- **H2O (Heavy Hitter Oracle):** https://arxiv.org/abs/2306.14048
- **Comprehensive KV cache survey (2024):** https://arxiv.org/abs/2412.19442
- **vLLM documentation:** https://docs.vllm.ai/

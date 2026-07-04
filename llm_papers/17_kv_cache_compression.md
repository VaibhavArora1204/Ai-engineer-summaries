# Paper 17: KV Cache Compression — A Survey (2024)

## What Existed Before and What Broke

Papers 12 (GQA) and 14 (PagedAttention) significantly reduced KV cache costs through architectural changes (fewer KV heads) and better memory allocation (paging). But context windows kept growing — from 4K to 128K to 1M+ — and at these lengths, the KV cache overwhelms everything else:

```
Llama 3 70B at various context lengths (GQA 8:1, FP16):

  Context     KV cache per request    Model weights    KV/Weights ratio
  4K          1.28 GB                 140 GB           0.9%
  32K         10.24 GB                140 GB           7.3%
  128K        40.96 GB                140 GB           29.3%
  512K        163.84 GB               140 GB           117%  ← KV > model
  1M          327.68 GB               140 GB           234%

At 128K context: KV cache is 29% of model weights per request.
At 512K context: KV cache EXCEEDS model weights for a SINGLE request.
At 1M context: KV cache is 2.3x the model weights.

You literally cannot serve a single 1M-context request on one GPU
because the KV cache alone exceeds VRAM capacity.
```

This is the active wall in LLM serving. The KV cache — not model weights, not compute, not network — is the dominant cost constraint for long-context inference. This survey covers the four research directions attacking this wall.

---

## The Core Mechanism — Four Approaches

### Approach 1: KV Cache Quantization

Compress K and V tensors from FP16 to lower precision, reducing memory per token.

```
Precision   Bits per value   Memory vs FP16   Quality impact
FP16        16 bits          1.0x (baseline)  None
FP8         8 bits           0.5x             Negligible on most tasks
INT8        8 bits           0.5x             Negligible (well-studied)
INT4        4 bits           0.25x            Measurable on precision-sensitive tasks
INT2        2 bits           0.125x           Significant — only with careful calibration
```

**KIVI (2024):** 2-bit asymmetric quantization of KV cache. Tuning-free (no calibration data needed). Achieves near-zero quality loss on most tasks at 2-bit for V cache, 4-bit for K cache. K cache is more sensitive to quantization because attention scores (QK^T) amplify quantization errors.

```
KIVI approach:
  K cache: 4-bit quantization (attention scores are sensitive to K precision)
  V cache: 2-bit quantization (output aggregation is more robust)
  
  Effective compression: ~5x reduction in KV cache size
  Quality: near-lossless on MMLU, HumanEval, and standard benchmarks
  
  Caveat: 2-bit K/V can degrade on tasks requiring precise numerical 
  recall or exact factual matching. Test on YOUR specific task.
```

**Practical entry point today — what you can do right now:**

```python
# vLLM with FP8 KV cache (available in current vLLM):
llm = LLM(
    model="meta-llama/Meta-Llama-3-70B-Instruct",
    kv_cache_dtype="fp8",  # FP8 KV cache quantization
)

# Result: 2x KV cache capacity. Near-zero quality loss for RAG workloads.
# This doubles your max concurrent users or max context length.
# One config change. No model retraining. No quality tuning needed.
```

### Approach 2: Token Eviction (Dropping)

Identify which tokens are less important and drop their KV entries from the cache entirely. The intuition: not all tokens in the context contribute equally to the output. Function words ("the", "is", "and") and repetitive content contribute less than key entities and facts.

**H2O — Heavy Hitter Oracle (Zhang et al., 2023):**
```
Mechanism:
  Track cumulative attention scores for each token across all layers.
  Tokens that receive high attention consistently = "heavy hitters."
  
  Cache policy: keep heavy hitters + recent window. Drop everything else.
  
  Heavy hitters (20% of tokens) receive 80%+ of total attention.
  Dropping the other 80% has minimal quality impact on MOST tasks.
  
  Cache structure:
  [Heavy hitters: ~20% of tokens] + [Recent window: last ~10% of tokens]
  Total: ~30% of original cache size = 3.3x compression
```

**SnapKV (Li et al., 2024):**
```
Mechanism:
  Use a "compression prefix" — the model processes the full context once,
  then identifies which token positions were most important during 
  that processing.
  
  After identification: keep only important positions in the cache.
  Subsequent generation uses the compressed cache.
  
  Advantage over H2O: importance is estimated from the actual attention 
  pattern on THIS specific input, not cumulative statistics.
```

**The danger of eviction — silent quality degradation:**

```
Eviction works for:
  Summarization (model needs gist, not precise details)
  General Q&A (key facts are attended to, filler dropped)
  Classification (only discriminative tokens matter)

Eviction FAILS for:
  Legal analysis: "clause 47(b)(iii)" is a rare token with low attention
    in most layers. Eviction drops it. But it's the answer to the question.
  
  Medical records: "patient denied chest pain" — "denied" is a common word
    that might be dropped, completely changing the meaning.
  
  Code debugging: a specific variable name in a 10,000-line file.
    Low cumulative attention. Evicted. But it's the bug.

The failure mode is SILENT: no error is thrown. The model just 
generates a wrong answer because the critical information was dropped.
You won't know unless you evaluate carefully on YOUR specific task.
```

### Approach 3: KV Cache Merging

Instead of dropping tokens, merge similar tokens' KV entries into representative entries. The resulting cache is smaller but retains more information than eviction.

**CAM — Cache Merging (2024):**
```
Mechanism:
  Identify pairs of KV entries with high cosine similarity.
  Merge them into a single entry (weighted average).
  
  Intuition: tokens in the same semantic region have similar K/V vectors.
  Merging them preserves the "region" while reducing entry count.
  
  Advantage over eviction: no information is completely lost.
  Disadvantage: merged entries are approximations. Fine distinctions 
  between similar-but-different tokens are lost.
```

**MiniCache (2024):**
```
Key insight: deeper layers have more similar KV representations than 
shallow layers. Merging across LAYERS (not within a layer) is more 
effective because deeper representations are more redundant.

Merge KV entries between adjacent layers where representations 
are most similar. Effective compression with minimal quality loss.
```

### Approach 4: KV Cache Offloading

Move KV cache that doesn't fit in GPU VRAM to CPU RAM or NVMe SSD. The GPU holds the "hot" portion (recent tokens, high-attention tokens), and loads the rest from CPU/SSD when needed.

**InfLLM (2024):**
```
Architecture:
  GPU VRAM: model weights + hot KV cache (recent tokens + attention anchors)
  CPU RAM: cold KV cache (older context, lower attention)
  
  When attention needs a cold block:
    1. Check relevance scoring to decide if the block is needed
    2. If needed: transfer from CPU → GPU (PCIe bandwidth: ~32 GB/s)
    3. Compute attention
    4. Evict back to CPU if not needed for subsequent tokens
  
  Enables: 1M+ context on hardware that can only hold 128K in VRAM
  Cost: ~5-10x latency increase for cache-miss tokens
```

**Mooncake (Kimi/Moonshot AI, FAST 2025):**
```
The most ambitious approach: cluster-wide KV cache pool.

Architecture:
  Inference GPUs: model weights + active request KV cache
  Distributed CPU DRAM pool: shared KV cache across all inference nodes
  
  When a request arrives:
    1. Check distributed KV pool: "Is there a cached KV for this prefix?"
    2. If hit: transfer KV cache from pool → GPU (RDMA, ~100 GB/s)
    3. If miss: compute prefill, store result in pool for future reuse
  
  KV cache becomes INFRASTRUCTURE — not ephemeral GPU memory but a 
  persistent, shared, distributed storage layer.
  
  "Trade storage for compute" — hold KV cache longer, avoid recomputation.
  
  This is where hyperscale serving is going:
  KV cache as a first-class distributed system with its own storage,
  replication, eviction policies, and capacity planning.
```

---

## What This Creates for Your System

### The Practical Action Today

For most teams, the actionable takeaway is simple:

```
Step 1 (immediate, zero risk):
  Enable FP8 KV cache in vLLM: kv_cache_dtype="fp8"
  Effect: 2x KV cache capacity. Near-zero quality loss.
  Effort: one config change.
  
Step 2 (if you need more):
  Enable INT8 KV cache if FP8 isn't enough.
  Effect: 2x capacity. Test on your specific tasks for quality.
  
Step 3 (if you're pushing long context):
  Evaluate H2O or SnapKV for your workload.
  CRITICAL: test on your actual production queries, not benchmarks.
  Eviction failure modes are task-dependent and silent.
  
Step 4 (if you're at hyperscale):
  Consider KV cache offloading to CPU or distributed KV pools.
  This is infrastructure engineering, not a config change.
```

### How KV Compression Stacks With Other Optimizations

```
Optimization stack (multiplicative):

  Base: Llama 3 70B, MHA (hypothetical), FP16 KV cache
  KV per token: 2.5 MB
  
  + GQA (8:1):           2.5 MB → 320 KB     (8x reduction)
  + FP8 KV quantization: 320 KB → 160 KB     (2x reduction)
  + PagedAttention:       160 KB → 160 KB     (no per-token change, 
                          but 3-5x better utilization)
  + Token eviction (H2O): 160 KB → 48 KB      (3.3x if keeping 30%)
  
  Combined: 2.5 MB → 48 KB = 52x total reduction
  
  At 128K context:
    Original: 320 GB KV per request (impossible)
    Optimized: 6.14 GB per request (fits on one GPU)
```

---

## What Production Systems Changed After This

**KV cache management became infrastructure.** Before this survey, KV cache was treated as an implementation detail managed by the serving framework. After, it's recognized as a first-class infrastructure concern with its own optimization stack (quantization + eviction + offloading), capacity planning requirements, and quality tradeoffs.

**FP8/INT8 KV cache became a standard vLLM feature.** KV cache quantization moved from research to a production config option in vLLM. Most teams can enable it today with one line of config.

**Long-context serving became a specialized problem.** Serving 128K+ context requires fundamentally different infrastructure than 4K context. The KV cache optimizations in this survey are what make the difference between "can serve one 128K request per GPU" and "can serve ten."

---

## How This Connects to the Other 17 Papers

**Attacks the same wall as Papers 12, 14:** GQA (Paper 12) reduces KV cache at the architecture level. PagedAttention (Paper 14) reduces KV cache waste at the allocation level. KV compression (this paper) reduces KV cache at the representation level. All three are complementary and stack multiplicatively.

**Enabled by Paper 8 (FlashAttention):** FlashAttention made long contexts memory-efficient for attention computation. But the KV cache itself still grows linearly. KV compression addresses the remaining memory cost that FlashAttention doesn't touch.

**Required by Paper 11 (RoPE) context extensions:** RoPE enables 128K+ contexts. But enabling a 128K context without KV cache compression means one request consumes most of GPU VRAM. KV compression makes the extended contexts that RoPE enables actually servable.

**Interacts with Paper 15 (RAG):** RAG stuffs retrieved chunks into context. More chunks = longer context = larger KV cache. KV compression lets you include more chunks without hitting memory limits. The combination of better RAG retrieval (fewer, more relevant chunks) + KV compression (cheaper per-token memory) maximizes the information you can fit in context.

---

## The Honest Take

**1. What most engineers miss when they skip this paper and just use the API:**

KV cache is not an implementation detail — it's the primary cost and capacity constraint for long-context LLM serving. If you self-host, enabling FP8 KV cache in vLLM is the single highest-ROI configuration change for long-context workloads: one line of config, 2x more concurrent users or 2x longer context. Most teams don't know this option exists.

If you use APIs, KV cache management is why providers can (or can't) offer long-context models at reasonable prices. Understanding the constraint helps you make informed decisions about context length tradeoffs: stuffing 100K tokens into context might be technically possible but economically wasteful if only 10K tokens are actually relevant.

**2. The one non-obvious systems implication that blog posts never explain:**

Token eviction (H2O, SnapKV) has a task-dependent failure mode that is fundamentally different from other compression techniques. Quantization and merging preserve all tokens (at reduced precision). Eviction permanently removes tokens. If the evicted token contained the answer to the question, no amount of model quality or prompt engineering can recover it. The failure is silent — the model generates a confident answer from incomplete context.

This means eviction is safe for summarization (model needs gist), dangerous for factual QA (model needs specific details), and catastrophic for tasks where rare, specific tokens are the entire answer (legal clause numbers, medical codes, specific dates). You MUST evaluate eviction on your actual production distribution, not on standard benchmarks.

**3. Essential, useful context, or interesting history?**

**Essential if you self-host long-context models. Useful context otherwise.** If you serve models with 32K+ context, KV cache management is your primary scaling constraint. Understanding the four approaches (quantization, eviction, merging, offloading), their tradeoffs, and which to apply first (quantization: safe and easy; eviction: effective but risky) is directly actionable.

If you use APIs, the practical takeaway is narrower but still valuable: KV cache constraints explain why longer contexts cost more, why prompt caching exists, and why your 128K-context request is more expensive than your 4K-context request by more than 32x (the relationship is not strictly linear due to caching and batching effects).

The field is moving toward Mooncake's vision: KV cache as a first-class distributed storage system. This is where production LLM serving infrastructure is heading — and understanding it now puts you ahead of the curve.

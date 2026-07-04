# Paper 12: MQA + GQA — Multi-Query and Grouped-Query Attention

## What Existed Before and What Broke

Standard Multi-Head Attention (MHA) from Paper 1 gives every attention head its own Q, K, and V projection matrices. During autoregressive generation, the K and V matrices for all past tokens are cached (the KV cache) to avoid recomputation. This cache grows linearly with sequence length, number of layers, number of heads, and head dimension.

The specific problem — the numbers:

```
Llama 2 70B with standard MHA (hypothetical):
  Heads: 64
  Head dimension: 128
  Layers: 80
  Precision: FP16 (2 bytes)
  
  KV cache per token:
    2 (K + V) × 64 heads × 128 dim × 80 layers × 2 bytes
    = 2 × 64 × 128 × 80 × 2
    = 2,621,440 bytes
    = 2.5 MB per token
  
  At 4K context per request:
    2.5 MB × 4,096 = 10.24 GB per request
  
  At 100 concurrent requests:
    10.24 GB × 100 = 1,024 GB = 1 TB of KV cache
  
  The model weights themselves are ~140 GB (70B × 2 bytes).
  The KV cache for 100 concurrent requests is 7x the model weights.
```

This is the KV cache memory wall. At production concurrency levels, the KV cache — not the model weights — becomes the dominant GPU memory consumer. Your maximum concurrent users is determined not by compute capacity but by how many KV caches fit in VRAM alongside the model weights.

---

## The Core Mechanism

### Multi-Query Attention (MQA) — Shazeer, 2019

The observation: during autoregressive generation, the bottleneck is memory bandwidth (loading KV cache from HBM), not compute. The attention computation itself is cheap; loading the K and V tensors for all heads from memory is expensive.

MQA's solution: **all query heads share a single K head and a single V head.**

```
Standard MHA (64 heads):
  64 Q projections × d_head   → 64 different Q vectors per token
  64 K projections × d_head   → 64 different K vectors per token  
  64 V projections × d_head   → 64 different V vectors per token
  
  KV cache: 64 K heads + 64 V heads = 128 vectors per token per layer

MQA (64 Q heads, 1 KV head):
  64 Q projections × d_head   → 64 different Q vectors per token
  1  K projection  × d_head   → 1 K vector shared by all Q heads
  1  V projection  × d_head   → 1 V vector shared by all Q heads
  
  KV cache: 1 K head + 1 V head = 2 vectors per token per layer
  
  Reduction: 128 → 2 = 64x smaller KV cache
```

**The cost:** With only one K and V head, all 64 query heads attend to the same key-value representations. This reduces the diversity of attention patterns — the model has fewer "channels" for capturing different types of relationships. In practice, MQA shows measurable quality degradation on some benchmarks, particularly those requiring nuanced multi-scale attention patterns.

**Used in:** Early PaLM (Google), Falcon 7B/40B, StarCoder.

### Grouped-Query Attention (GQA) — Ainslie et al., 2023

GQA is the compromise between MHA (full diversity, huge KV cache) and MQA (minimal KV cache, reduced diversity):

```
GQA: Group Q heads into G groups. Each group shares one K head and one V head.

Example — 64 Q heads, 8 KV groups (G=8):
  Q heads 1-8   share KV head 1
  Q heads 9-16  share KV head 2
  Q heads 17-24 share KV head 3
  ...
  Q heads 57-64 share KV head 8
  
  KV cache: 8 K heads + 8 V heads = 16 vectors per token per layer
  
  vs MHA: 128 vectors → 16 vectors = 8x reduction
  vs MQA: 2 vectors   → 16 vectors = 8x larger (but much better quality)
```

**Why GQA won:** Quality near MHA, efficiency near MQA. The sweet spot.

```
Quality comparison (from the paper):
  MHA (full):     100% quality baseline
  GQA (8 groups): ~99.5% quality (negligible degradation)
  MQA (1 group):  ~98% quality (measurable degradation)
  
  GQA loses <0.5% quality for 8x KV cache reduction.
  This tradeoff is overwhelmingly favorable for production serving.
```

### Which Models Use What

```
Architecture      Model                Q Heads    KV Heads    KV Ratio
MHA               GPT-3 (175B)         96         96          1:1
MQA               Falcon 7B            71         1           71:1
GQA               Llama 3 8B           32         8           4:1
GQA               Llama 3 70B          64         8           8:1
GQA               Mistral 7B           32         8           4:1
GQA               Gemma 2 27B          32         16          2:1
GQA               DeepSeek-V2          128        -           MLA (different)

GQA with 8 KV heads has become the de facto standard for 2024-2025 models.
```

---

## What This Creates for Your System

### Concurrent Users Per GPU — The Direct Impact

GQA's KV cache reduction directly translates to more concurrent users per GPU:

```
Llama 3 70B (actual GQA configuration):
  Q heads: 64, KV heads: 8 (GQA ratio: 8:1)
  Head dim: 128, Layers: 80, FP16

  KV cache per token (GQA):
    2 × 8 × 128 × 80 × 2 = 327,680 bytes = 320 KB per token
  
  Compare to hypothetical MHA:
    2 × 64 × 128 × 80 × 2 = 2,621,440 bytes = 2.5 MB per token
  
  Reduction: 8x (matching the GQA ratio)
  
  At 4K context per request:
    GQA: 320 KB × 4,096 = 1.28 GB per request
    MHA: 2.5 MB × 4,096 = 10.24 GB per request
  
  Available VRAM for KV cache on 2× A100 80GB:
    160 GB total - 140 GB model weights = 20 GB for KV cache
  
  Max concurrent requests:
    GQA: 20 GB / 1.28 GB = 15 concurrent requests
    MHA: 20 GB / 10.24 GB = 1.9 → 1 concurrent request
    
  GQA enables 15x more concurrent users on the same hardware.
```

This is not a minor optimization. It's the difference between "can serve production traffic" and "can serve one user at a time."

### The Model Selection Metric Nobody Checks

When evaluating models for self-hosting, most engineers look at parameter count and benchmark scores. The KV cache size per token — determined by the number of KV heads — is equally important for serving economics:

```
Model comparison for self-hosting:
  
  Model A: 7B params, 32 KV heads (MHA)
    KV cache/token: 32 × 128 × 2 × 32 layers × 2 bytes = 524 KB
    
  Model B: 7B params, 8 KV heads (GQA)
    KV cache/token: 8 × 128 × 2 × 32 layers × 2 bytes = 131 KB
    
  Same parameter count. Same benchmark score (hypothetically).
  Model B serves 4x more concurrent users.
  
  The GQA ratio is in the model's config.json:
    "num_attention_heads": 32,
    "num_key_value_heads": 8      ← THIS NUMBER MATTERS
  
  If this ratio is not in your model evaluation checklist, add it.
```

### How GQA Interacts With Context Length

Longer context = larger KV cache per request = fewer concurrent users. GQA ratio determines how fast you hit the wall:

```
Llama 3 70B (GQA 8:1), 80 GB available for KV cache:

  Context    KV per request    Max concurrent
  4K         1.28 GB           62 requests
  8K         2.56 GB           31 requests
  16K        5.12 GB           15 requests
  32K        10.24 GB          7 requests
  128K       40.96 GB          1 request (barely)
  
  At 128K context, you can serve exactly ONE concurrent request 
  on an 80GB GPU — even with GQA's 8x reduction.
  
  Without GQA (MHA), you couldn't serve even one 128K request.
```

This table is why context length, GQA ratio, and serving hardware are interdependent. You cannot evaluate any one without the other two.

### API Provider Economics

When you call an LLM API, the provider is batching your request with other users' requests on the same GPU. GQA directly affects their ability to batch:

```
Provider perspective (serving GPT-4-class model):

  With GQA:
    KV cache per user per request: ~1-2 GB
    Users per GPU: 20-40 (at 4K average context)
    Revenue per GPU-hour: 20-40 × requests/hour × price/request
    
  With MHA:
    KV cache per user per request: ~8-16 GB
    Users per GPU: 3-5
    Revenue per GPU-hour: 3-5 × requests/hour × price/request
    
  GQA enables 5-10x more revenue per GPU.
  This is why API prices have dropped despite models getting larger.
  The efficiency gains from GQA (and PagedAttention, Paper 14) 
  directly translate to lower per-token pricing.
```

---

## What Production Systems Changed After This

**GQA became the default.** Every major model released since mid-2023 uses GQA. It's no longer an optimization choice — it's the baseline architecture. MHA is considered legacy for any model intended for production serving.

**Self-hosting became economically viable.** GQA's KV cache reduction, combined with FlashAttention's memory access optimization (Paper 8) and PagedAttention's memory allocation (Paper 14), made it possible to serve 70B-class models on 2 GPUs instead of requiring a cluster. This is what made the "self-host Llama" movement practical.

**Model architecture reports now include KV head counts.** Before GQA, model cards reported attention heads as a single number. After GQA, model configs separate `num_attention_heads` (Q heads) from `num_key_value_heads` (KV heads), and informed evaluation considers both.

---

## How This Connects to the Other 17 Papers

**Directly attacks Paper 1's (Attention) memory cost:** MHA from Paper 1 creates a KV cache that grows linearly with head count. GQA reduces this by sharing KV heads, directly reducing the per-token memory cost of the attention mechanism.

**Complements Paper 8 (FlashAttention):** FlashAttention reduces the memory ACCESS cost (HBM bandwidth). GQA reduces the memory SIZE cost (less KV data to store). They compound: FlashAttention makes accessing the KV cache efficient, GQA makes the cache smaller. Together, they make long-context serving practical.

**Interacts with Paper 14 (PagedAttention):** PagedAttention allocates KV cache in non-contiguous blocks. Smaller KV cache per token (from GQA) means more blocks available, less fragmentation, and more concurrent requests. PagedAttention's efficiency gains multiply with GQA's size reduction.

**Interacts with Paper 5 (Chinchilla):** Chinchilla-style over-trained small models (7B-13B) already have inherently smaller KV caches due to fewer layers and heads. Adding GQA on top makes them exceptionally efficient for serving. A well-trained 7B GQA model is the most cost-effective serving option for most production tasks.

**Interacts with Paper 17 (KV Cache Compression):** GQA reduces KV cache size at the architecture level. KV compression (quantization, eviction, merging) reduces it at the serving level. They're complementary and stack: GQA gives you 4-8x reduction, INT8 KV quantization gives you another 2x, for a total 8-16x reduction vs MHA with FP16.

---

## The Honest Take

**1. What most engineers miss when they skip this paper and just use the API:**

Most engineers evaluate models by benchmark score and parameter count. The number of KV heads — and therefore the KV cache size per token — is the metric that actually determines your serving cost and maximum concurrent users when self-hosting. Two 7B models with identical benchmark scores can have 4x different serving economics if one uses MHA (32 KV heads) and the other uses GQA (8 KV heads). This number is in the model's `config.json` under `num_key_value_heads`. Check it.

Even if you use APIs exclusively, GQA explains why API prices have dropped despite models getting larger and better. The providers can serve 5-10x more users per GPU with GQA, and they pass some of that efficiency to you as lower pricing. Understanding this helps you predict pricing trends and make informed build-vs-buy decisions.

**2. The one non-obvious systems implication that blog posts never explain:**

GQA ratio interacts with context length to determine your concurrency ceiling, and most capacity planning ignores this interaction. If your system has a 4K average context length, GQA gives you 15+ concurrent users per GPU. If a product change increases average context to 32K (adding more RAG chunks, longer conversations), your concurrency drops to ~7 per GPU — a 2x infrastructure cost increase from a product decision that seems unrelated to infrastructure. The connection is: more context → bigger KV cache per request → fewer concurrent requests → more GPUs needed. GQA ratio determines the slope of this relationship. If you're doing capacity planning for a self-hosted model, model the context length × concurrency × GQA interaction explicitly.

**3. Essential, useful context, or interesting history?**

**Essential if you self-host. Useful context if you use APIs.** If you self-host models, GQA ratio is a first-class capacity planning metric alongside parameter count and quantization level. Ignoring it will lead to capacity planning errors of 4-8x (the difference between MHA and GQA KV cache sizes).

If you use APIs, GQA is useful context for understanding provider economics (why prices drop, how batching works) and for evaluating whether to self-host (the serving efficiency of GQA models makes self-hosting more attractive than it was in the MHA era).

Check `num_key_value_heads` in the next model you evaluate. This one number tells you more about serving economics than any benchmark.

# Paper 14: PagedAttention / vLLM (Kwon et al., 2023)

## What Existed Before and What Broke

Before PagedAttention, KV cache memory was allocated contiguously and upfront for each request. When a request arrived with `max_tokens=2048`, the serving system reserved 2048 tokens worth of KV cache immediately — even though the actual generation might produce only 200 tokens. The remaining 1848 tokens of reserved memory sat completely unused.

```
The fragmentation problem:

  Request arrives: max_tokens = 2048
  Serving system: reserves 2048 × KV_size_per_token of contiguous GPU memory
  Actual generation: 200 tokens
  Memory utilization: 200/2048 = 9.8%
  Wasted memory: 90.2%
  
  This is internal fragmentation — the same problem that OS memory 
  allocators solved 50 years ago with virtual memory and paging.
  
  At scale with hundreds of concurrent requests:
  Average utilization of reserved KV cache: 20-40%
  60-80% of GPU VRAM allocated to KV cache is sitting empty.
  
  Your maximum concurrent users is artificially limited by 2-4x 
  because of memory that's reserved but never used.
```

Additionally, contiguous allocation creates external fragmentation: even when total free memory is sufficient for a new request, the free memory is scattered in small non-contiguous chunks that individually aren't large enough for the contiguous allocation a new request requires.

---

## The Core Mechanism

### Virtual Memory for KV Cache

PagedAttention applies the same solution that operating systems applied to RAM fragmentation 50 years ago: paging. Instead of allocating contiguous memory blocks per request, allocate fixed-size pages (blocks) on demand and use a page table to map logical positions to physical memory locations.

```
Traditional KV cache allocation:
  Request 1: [=====contiguous block=====________waste_______]
  Request 2: [==contiguous=____waste____________________________]
  Request 3: [==========contiguous block==========_____waste____]
  
  ████ = used    ____ = reserved but unused

PagedAttention:
  Physical memory: [blk0][blk1][blk2][blk3][blk4][blk5][blk6][blk7]...
  
  Request 1 page table: logical 0→blk2, logical 1→blk5, logical 2→blk0
  Request 2 page table: logical 0→blk3, logical 1→blk7
  Request 3 page table: logical 0→blk1, logical 1→blk4, logical 2→blk6
  
  Each block holds KV cache for a fixed number of tokens (default: 16).
  Blocks are allocated on demand as tokens are generated.
  Blocks can be non-contiguous in physical memory.
  The page table maps logical positions to physical blocks.
  
  Memory utilization: ~98% (only the last partially-filled block is wasted)
  vs traditional: ~20-40%
```

### How It Works Step by Step

```
1. Request arrives. No memory pre-allocated (or minimal: 1 block for prompt).

2. Prompt processing (prefill):
   Process the prompt. Allocate blocks for KV cache as needed.
   1000-token prompt → 1000/16 = 63 blocks allocated.
   Blocks pulled from a free list (like malloc from a free pool).

3. Token generation (decode):
   Generate token 1 → stored in the last block (if space).
   When a block fills up (16 tokens) → allocate a new block from free list.
   Continue until generation completes or max_tokens reached.

4. Request completes:
   All blocks returned to the free list.
   Immediately available for new requests.

Key properties:
  - No pre-allocation waste (blocks allocated on demand)
  - No contiguous requirement (blocks can be anywhere in VRAM)
  - Near-zero internal fragmentation (only last block partially used)
  - No external fragmentation (any free block can serve any request)
```

### Prefix Caching — The Killer Feature

When multiple requests share the same prefix (system prompt, few-shot examples), their KV cache blocks for that prefix are identical. PagedAttention can share these blocks across requests using copy-on-write semantics:

```
Request 1: [system_prompt] + "What is the capital of France?"
Request 2: [system_prompt] + "Explain quantum computing"
Request 3: [system_prompt] + "Write a haiku about cats"

Without prefix caching:
  Each request computes and stores KV cache for system_prompt independently.
  3 copies of the same KV data.
  If system_prompt = 500 tokens: 3 × 500 × KV_per_token = 3x memory

With prefix caching:
  Request 1 computes KV cache for system_prompt → stored in blocks A1-A31
  Request 2 arrives with same prefix → page table points to SAME blocks A1-A31
  Request 3 arrives → same shared blocks
  
  1 copy of system_prompt KV cache shared across 3 requests.
  Memory saving: 67% for the prefix portion.
  Compute saving: system_prompt processed once, not 3 times.
```

**This is the mechanism behind prompt caching APIs.** When Anthropic or OpenAI offer "prompt caching" with 90% cost reduction on cached tokens, this is PagedAttention's prefix sharing exposed as a product feature. The KV cache for your stable system prompt is computed once and reused across subsequent requests.

### Why Prompt Cache Hits Are Probabilistic

Understanding the mechanism explains why cache hits aren't guaranteed:

```
Cache miss conditions:

1. Different server instance:
   Prefix cache is per-GPU. If request 2 is routed to a different GPU 
   than request 1, there's no shared cache. Load balancers must 
   implement prefix-aware routing for optimal hit rates.

2. Cache eviction:
   GPU memory is finite. When memory pressure is high, cached prefixes 
   are evicted (LRU). If your prefix was evicted between requests, 
   it's a cache miss.

3. Prefix changed:
   Even one token difference in the prefix invalidates the cache.
   If your system prompt includes a timestamp, every request has a 
   unique prefix → 0% cache hit rate. Keep prefixes stable.

4. Provider routing:
   API providers route requests across many GPUs. The probability 
   of hitting the same GPU (and therefore the same cache) depends 
   on the provider's routing strategy, which you don't control.

Design implications:
  - Keep system prompts stable (no timestamps, no per-request content)
  - Put dynamic content AFTER the cached prefix
  - Design for cache misses as the baseline, cache hits as optimization
  - Monitor cache hit rates (providers report this in response headers)
```

### Continuous Batching (Orca, 2022) — The Complementary Innovation

PagedAttention is often discussed alongside continuous batching, which vLLM also implements:

```
Static batching (traditional):
  Wait for B requests to arrive → process batch → return all results
  Problem: fast requests wait for slow ones. A 50-token response 
  blocks until all B requests finish their 500-token responses.
  GPU sits idle on the finished requests.

Continuous batching:
  Process requests as they arrive.
  When a request finishes → immediately replace it with a new request.
  The GPU is always working on a full batch.
  
  Result: no request waits for another. Throughput: 10-20x improvement 
  over static batching.
```

PagedAttention + continuous batching is the combination that makes vLLM the dominant serving framework. PagedAttention handles memory efficiency. Continuous batching handles scheduling efficiency. Together: 10-20x throughput improvement over naive HuggingFace `generate()`.

---

## What This Creates for Your System

### Prompt Caching as a Cost Optimization Strategy

If you use LLM APIs with stable system prompts, prompt caching provides significant savings:

```
Anthropic prompt caching pricing (illustrative):
  Uncached input: $3.00 / million tokens
  Cached input:   $0.30 / million tokens (90% reduction)
  Cache write:    $3.75 / million tokens (25% premium on first write)
  
  System prompt: 2,000 tokens
  Per-request dynamic content: 1,000 tokens
  
  Without caching (every request):
    Cost per request: 3,000 tokens × $3.00/M = $0.009
  
  With caching (cache hit):
    Cached: 2,000 tokens × $0.30/M = $0.0006
    Dynamic: 1,000 tokens × $3.00/M = $0.003
    Total: $0.0036 per request (60% savings)
  
  At 100K requests/day:
    Without: $900/day
    With: $360/day
    Savings: $540/day = $16,200/month
```

**Design your prompts for cacheability:**
```
✓ Good (cacheable):
  [Stable system prompt - 2000 tokens]     ← cached
  [Stable few-shot examples - 1000 tokens] ← cached
  [Retrieved chunks - variable]             ← not cached (dynamic)
  [User query - variable]                   ← not cached (dynamic)

✗ Bad (uncacheable):
  [System prompt with timestamp]            ← cache invalidated every second
  [System prompt with user_id]              ← unique per user, never cached
  [Dynamic preamble]                        ← different every request
```

### Self-Hosting Economics

PagedAttention's memory efficiency directly determines self-hosting economics:

```
Without PagedAttention (HuggingFace generate()):
  Llama 3 70B on 2× A100 80GB:
    Model weights: 140 GB
    Available for KV cache: 20 GB
    KV utilization: ~30% (contiguous pre-allocation waste)
    Effective KV capacity: 6 GB
    Concurrent requests (4K context): ~5
    Throughput: ~50 tokens/second total

With PagedAttention (vLLM):
    KV utilization: ~98% (paged allocation)
    Effective KV capacity: 19.6 GB
    Concurrent requests (4K context): ~15
    Throughput: ~500 tokens/second total (with continuous batching)
    
  3x more concurrent users, 10x more throughput.
  Same hardware. Same model. Different memory allocator.
```

---

## What Production Systems Changed After This

**vLLM became the dominant serving framework.** vLLM is built entirely around PagedAttention. It went from a research project (UC Berkeley, 2023) to the most widely deployed open-source LLM serving framework in under a year. If you self-host an open model in 2025, you almost certainly use vLLM.

**Prompt caching became an API product.** Anthropic launched prompt caching (2024). OpenAI followed. Google's Gemini has "context caching." All are productizations of PagedAttention's prefix sharing mechanism. The research paper became a revenue-generating product feature within 18 months.

**HuggingFace generate() became legacy for production.** Before vLLM, most teams served models with `model.generate()` from HuggingFace Transformers. After vLLM demonstrated 10-20x throughput improvement, HuggingFace generate() became a prototyping tool, not a production serving solution.

---

## How This Connects to the Other 17 Papers

**Manages the KV cache from Paper 1 (Attention):** The KV cache exists because of the attention mechanism's property that K and V for past tokens don't change. PagedAttention manages the allocation of this cache efficiently.

**Interacts with Paper 8 (FlashAttention):** FlashAttention assumes contiguous KV cache for its tiling strategy. PagedAttention stores KV cache in non-contiguous blocks. vLLM modified FlashAttention to handle non-contiguous blocks — this required kernel-level changes. The two optimizations are complementary but create an implementation coupling.

**Multiplied by Paper 12 (GQA):** GQA reduces KV cache size per token. PagedAttention reduces KV cache waste per request. They multiply: 8x reduction (GQA) × 3x less waste (PagedAttention) = effectively 24x more concurrent users vs MHA + contiguous allocation.

**Enables Paper 13 (Speculative Decoding) at scale:** Speculative decoding generates draft tokens that may be rejected. PagedAttention handles the dynamic allocation/deallocation of KV cache blocks for draft tokens efficiently — rejected draft tokens' blocks are immediately returned to the free list.

**Complementary to Paper 17 (KV Cache Compression):** KV cache compression reduces the per-token memory cost. PagedAttention reduces the allocation waste. They're independent optimizations that stack.

---

## The Honest Take

**1. What most engineers miss when they skip this paper and just use the API:**

Prompt caching is not magic — it's a memory allocator optimization. Understanding that the cache is per-GPU, that prefix stability determines hit rate, and that even one differing token invalidates the cache changes how you design prompts. Most teams lose significant caching benefits because they include dynamic content (timestamps, request IDs, user-specific data) at the beginning of their prompt instead of at the end. Moving dynamic content after the stable prefix is a zero-cost change that can save 50-90% on input token costs.

**2. The one non-obvious systems implication that blog posts never explain:**

PagedAttention's memory efficiency improvement (3-5x more concurrent users) is essentially free — it's a better memory allocator, not a quality tradeoff. Yet many self-hosting teams still use HuggingFace generate() or poorly configured serving stacks that don't leverage paged allocation. The throughput difference between a well-configured vLLM deployment and a naive generate() loop is 10-20x. This is not a small optimization — it's the difference between needing 2 GPUs and needing 20 GPUs for the same workload. If you're self-hosting and not using vLLM (or TGI/TensorRT-LLM), you're likely overspending on hardware by 5-10x.

**3. Essential, useful context, or interesting history?**

**Essential. One of the top 3 most practically impactful papers in the curriculum.** Not because of conceptual depth (it's a memory allocator — the concept is simple), but because of direct, measurable impact on every system that serves LLMs. If you self-host: use vLLM, it implements PagedAttention. If you use APIs: understand prompt caching, it's PagedAttention's prefix sharing. Either way, this paper directly affects your costs.

The key insight is systems-level: the same virtual memory and paging concepts that solved RAM fragmentation in the 1960s solve GPU VRAM fragmentation in the 2020s. Good systems engineering is often not new ideas — it's applying proven ideas to new domains.

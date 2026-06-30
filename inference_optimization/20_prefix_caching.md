# Prefix Caching (Automatic Prefix Caching/APC) — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Recomputing KV cache for the same prompt prefix across multiple requests.**

In many LLM applications, different requests share a common prefix:
- **System Prompts:** Every request might start with a 1,000-token instruction block.
- **RAG (Retrieval-Augmented Generation):** Multiple users might query against the same retrieved document.
- **Multi-turn Chat:** Turn 10 contains Turns 1-9. Turn 11 contains Turns 1-10. Turns 1-9 are recomputed perfectly redundantly.
- **Agent Loops:** ReAct loops repeatedly pass the same tool descriptions and previous steps.

Without prefix caching, the prefill phase (which is compute-bound) processes these identical prefixes from scratch every time, wasting massive amounts of GPU compute and increasing Time-To-First-Token (TTFT).

---

## How It Works

### The Mechanism

Prefix caching leverages **PagedAttention's** block-based memory management. It maintains a hash tree (typically a Radix Tree) of token sequences and maps them to physical KV cache blocks.

```
Request A: "You are a helpful assistant. What is 2+2?"
Request B: "You are a helpful assistant. What is the capital of France?"

Both requests share: "You are a helpful assistant."

Without Prefix Caching:
  Req A prefill: compute KV for "You are a helpful assistant. What is 2+2?"
  Req B prefill: compute KV for "You are a helpful assistant. What is the capital of France?"
  
With Prefix Caching (APC):
  Req A prefill:
    - Hash "You are a helpful assistant."
    - Compute KV, store in physical blocks [block_0, block_1, block_2]
    - Add to global Radix Tree
    - Compute KV for " What is 2+2?", store in [block_3]
  
  Req B prefill:
    - Search Radix Tree for prefix matches
    - Match found: "You are a helpful assistant."
    - DO NOT COMPUTE KV for prefix. Just map Req B's page table to [block_0, block_1, block_2]
    - Compute KV ONLY for " What is the capital of France?"
    - Store in [block_4, block_5]
```

### RadixAttention (SGLang)

SGLang popularized the Radix Tree approach to prefix caching:
- The KV cache is managed as a Radix Tree of token blocks.
- When a request finishes, its KV cache is NOT immediately freed. It's kept in the tree as a cache.
- When VRAM is full, an LRU (Least Recently Used) eviction policy removes the least accessed blocks to make room.

### Multi-turn Chat Example

```
Turn 1: [System_Prompt] + [User_Msg_1] → Model generates [Asst_Msg_1]
  Cache state: [Sys] → [U1] → [A1]

Turn 2: [System_Prompt] + [User_Msg_1] + [Asst_Msg_1] + [User_Msg_2]
  Cache lookup matches everything up to [A1].
  Prefill only computes [User_Msg_2].
  Time to first token drops from e.g. 1.5s to 0.1s.
```

---

## The Numbers

| Workload | TTFT Improvement | Throughput Improvement |
|----------|------------------|------------------------|
| System prompts (1K tokens) | 2-3× faster | 1.5-2× |
| Multi-turn chat | Up to 10× faster on later turns | 2-3× |
| Tree-of-Thought / Agents | 5-15× faster | 3-5× |
| Unique prompts (No overlap) | None (~1% slower due to lookup) | None |

**KV Cache Reuse Rate:** The most important metric for APC. In agentic workflows, reuse rates can exceed 90%, meaning 90% of the prompt tokens submitted to the API don't require compute.

---

## Where It Lives in the Stack

**Layer: Serving framework memory manager.**

Prefix caching is a scheduling and memory management feature. It wraps around PagedAttention. It requires:
1. A global data structure (Radix Tree) tracking all allocated blocks across all requests.
2. An eviction policy (LRU) to manage the cache when VRAM fills up.
3. A prefill engine capable of starting computation from the middle of a sequence given a pre-populated KV cache.

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| Drastically lower TTFT for shared prefixes | VRAM fragmentation (cached blocks use memory that could be used for generation) |
| Huge compute savings for agents/multi-turn | Small overhead for cache lookup (~1ms) |
| Higher overall throughput | Scheduler complexity |
| | Unpredictable TTFT (depends on cache hit/miss) |

**The VRAM tradeoff:** The LRU cache keeps blocks alive after requests finish. This means less VRAM is available for *new* concurrent generations. However, because memory is shared (copy-on-write), identical concurrent requests actually use *less* total VRAM than without prefix caching.

---

## What It Combines With

**Stacks well with:**
- **PagedAttention (04):** Prefix caching relies entirely on PagedAttention's block-based memory.
- **Continuous Batching (17):** SGLang's RadixAttention integrates the Radix tree directly into the continuous batching scheduler.
- **Prefill-Decode Disaggregation (18):** Mooncake extends prefix caching to a distributed CPU DRAM pool, allowing cache hits across different physical nodes.
- **GQA/MQA (19):** Smaller KV cache per token means more prefix blocks fit in the cache.
- **Quantized KV Cache (09):** INT8 KV cache allows twice as many prefix blocks to be cached.

**Conflicts with:**
- None. It's purely an optimization. It defaults to normal prefill on a cache miss.

---

## Implementation Today

| Framework | Support | Notes |
|-----------|---------|-------|
| **SGLang** | Native (RadixAttention) | Best-in-class implementation. Designed for this. |
| **vLLM** | Native (`--enable-prefix-caching`) | Uses block-level hashing. Very effective. |
| **TGI** | Supported | — |
| **TensorRT-LLM** | Supported | — |
| **llama.cpp** | Supported | `--prompt-cache` (file-based) |

**Usage (vLLM):**
```bash
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3-70B-Instruct \
  --enable-prefix-caching
```
*Note: Prefix caching is so effective that it's becoming the default in most frameworks.*

---

## Primary Sources

- **SGLang (RadixAttention):** Zheng et al. 2023, "Efficient and Effective LLM Serving with SGLang" — https://arxiv.org/abs/2312.07104
- **Prompt Cache:** Gim et al. 2023 — https://arxiv.org/abs/2311.04934
- **vLLM Automatic Prefix Caching blog:** https://blog.vllm.ai/2024/04/04/apc.html

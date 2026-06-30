# PagedAttention — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Memory fragmentation and waste in KV cache allocation.**

Without PagedAttention, KV cache memory is allocated **contiguously** per request. The serving framework must preallocate a contiguous block large enough for the maximum possible sequence length *before the request starts generating*. Here's what goes wrong:

```
Request arrives, max_seq_len = 4096
System allocates: 4096 × KV_size_per_token contiguously in VRAM

Actual generation: 200 tokens
Memory used: 200 × KV_size_per_token
Memory wasted: 3896 × KV_size_per_token (reserved but empty)
Waste: 95%
```

Across many concurrent requests, this fragmentation wastes **60-80%** of KV cache VRAM. This directly limits the number of concurrent requests the GPU can serve.

Additionally, contiguous allocation suffers from the same problem as `malloc` in C: even if total free memory is sufficient, it may be fragmented into non-contiguous chunks too small for a new request's contiguous reservation. Requests get rejected despite available memory.

---

## How It Works

### The Core Idea

Apply **virtual memory** concepts from operating systems to KV cache management. Instead of allocating contiguous memory per request, divide KV cache into fixed-size **pages** (called "blocks" in vLLM). Each request gets a **page table** that maps logical sequence positions to physical memory blocks. Blocks are allocated on demand as tokens are generated.

### Step-by-Step Mechanism

```
SETUP:
  - Divide all KV cache VRAM into fixed-size blocks (e.g., 16 tokens per block)
  - Maintain a free block pool
  - Each request gets a page table (logical block → physical block mapping)

REQUEST ARRIVES:
  - Allocate 0 blocks initially
  - As prefill processes prompt tokens, allocate blocks on demand
  - Page table: [logical_block_0 → physical_block_47,
                  logical_block_1 → physical_block_12,
                  logical_block_2 → physical_block_89]

DECODE (each new token):
  - If current block has room: append K/V to current block
  - If current block is full: allocate new block from free pool,
    update page table
  - Attention kernel uses page table to gather K/V from
    non-contiguous physical blocks

REQUEST COMPLETES:
  - Return all blocks to free pool
  - Zero fragmentation — blocks are uniform size
```

### The Attention Kernel Change

Standard attention expects K and V tensors as contiguous arrays. PagedAttention's kernel accepts a **block table** and gathers K/V values from scattered physical blocks:

```python
# Conceptual (simplified)
def paged_attention(query, key_cache, value_cache, block_table, context_len):
    """
    query:       [num_heads, head_dim]
    key_cache:   [num_blocks, block_size, num_heads, head_dim]  (physical)
    value_cache: [num_blocks, block_size, num_heads, head_dim]  (physical)
    block_table: [max_blocks_per_seq]  (logical → physical mapping)
    """
    output = zeros(num_heads, head_dim)
    
    for logical_block_idx in range(num_blocks_used):
        physical_block = block_table[logical_block_idx]
        
        # Gather K, V from physical location
        k_block = key_cache[physical_block]  # [block_size, num_heads, head_dim]
        v_block = value_cache[physical_block]
        
        # Standard attention computation on this block
        scores = query @ k_block.T / sqrt(head_dim)
        # Accumulate with online softmax (similar to FlashAttention)
        output = update_with_block(output, scores, v_block)
    
    return output
```

### Memory Sharing via Copy-on-Write

Because blocks are referenced by page tables, **multiple requests can share the same physical blocks:**

```
Request A: system prompt "You are a helpful assistant..."
Request B: system prompt "You are a helpful assistant..."

Without PagedAttention:
  Request A KV cache: [system_prompt_KV | generated_KV]  (contiguous)
  Request B KV cache: [system_prompt_KV | generated_KV]  (contiguous, DUPLICATE)

With PagedAttention:
  Physical blocks: [block_0: system tokens 0-15] [block_1: system tokens 16-31] ...
  Request A page table: [→block_0, →block_1, ..., →block_47, →block_48]
  Request B page table: [→block_0, →block_1, ..., →block_47, →block_93]
                          ↑ shared prefix blocks      ↑ diverges after generation starts
```

This is the mechanism behind **Prefix Caching** (topic 20) — shared prefixes share physical KV cache blocks.

---

## The Numbers

| Metric | Before (contiguous) | After (PagedAttention) |
|--------|--------------------|-----------------------|
| KV cache memory waste | 60-80% (fragmentation) | <4% (only last block partially filled) |
| Concurrent requests (same VRAM) | N | 2-4× N |
| Throughput (same hardware) | Baseline | 2-4× (more requests in flight) |
| Prefix sharing overhead | None (no sharing) | Near-zero (shared block references) |

From the vLLM paper: PagedAttention achieves **2-4× throughput improvement** over HuggingFace TGI and the FasterTransformer baseline, solely from better memory utilization. No model change, no algorithmic change to attention quality.

---

## Where It Lives in the Stack

**Layer: Serving framework — memory manager and attention kernel.**

PagedAttention is NOT a model-level change. The model weights, architecture, and training are unchanged. It operates at two levels:

1. **Memory manager (scheduler level):** Tracks the free block pool, allocates blocks to requests on demand, manages page tables, handles block sharing and copy-on-write.

2. **Attention kernel (CUDA level):** Custom attention kernel that reads K/V via block table indirection instead of contiguous array indexing.

```
vLLM Architecture:
  API Server → Scheduler → [Block Manager (PagedAttention)]
                               ↓ allocates blocks
                           Model Executor → [Paged Attention Kernel]
                                               ↓ gathers K/V via block table
                                            Output tokens
```

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| Near-zero memory waste | Custom attention kernel (cannot use vanilla FlashAttention directly) |
| 2-4× more concurrent requests | Block table indirection adds ~2-5% overhead per attention op |
| Prefix sharing (copy-on-write) | Implementation complexity |
| Dynamic allocation (no over-reservation) | Block size tuning (too small → many blocks to manage; too large → internal fragmentation returns) |

**The FlashAttention conflict:** Standard FlashAttention assumes contiguous K/V memory. PagedAttention's non-contiguous blocks break this assumption. vLLM solves this by implementing its own paged variant of the FA kernel. This means vLLM cannot always use the latest upstream FlashAttention release without adaptation.

**vAttention (2024 alternative):** Proposes using the operating system's virtual memory and transparent huge pages to make non-contiguous physical memory appear contiguous to the attention kernel. This means vanilla FlashAttention works unmodified. The tradeoff: relies on OS-level memory management features that may not be available or optimal on all GPU servers.

---

## What It Combines With

**Stacks well with:**
- **KV Caching (01):** PagedAttention IS the memory management system for KV caching. Without KV caching, there's nothing to page.
- **Continuous Batching (17):** PagedAttention enables efficient continuous batching. When a request finishes, its blocks return to the pool immediately. New requests grab blocks as needed. No batch-level memory reallocation.
- **Prefix Caching (20):** Physical block sharing is the mechanism that makes prefix caching work. Requests with shared prefixes point to the same physical blocks.
- **GQA/MQA (19):** Fewer K/V heads means smaller blocks per token, so more tokens fit per block, improving block utilization.
- **Mixed Precision (08):** KV cache blocks can be stored in INT8 or FP8, doubling the number of blocks available in the same VRAM.

**Conflicts/interactions:**
- **FlashAttention (03):** As discussed — requires modified FA kernel. vAttention is the proposed resolution.
- **Memory Offloading (15):** Blocks can be offloaded to CPU RAM when VRAM is full and swapped back in. vLLM supports this for preempted requests (swapped out, swapped in later).

---

## Implementation Today

| Framework | Support | Details |
|-----------|---------|---------|
| **vLLM** | Core architecture | PagedAttention is vLLM's foundational innovation. Always on. Cannot be disabled. |
| **SGLang** | Similar block-based management | RadixAttention (prefix tree + block caching). |
| **TensorRT-LLM** | Block-based KV cache | NVIDIA's implementation. Not identical to vLLM's PagedAttention but same principles. |
| **TGI** | Adopted PagedAttention | HuggingFace integrated vLLM-style paging. |
| **llama.cpp** | Not implemented | Uses contiguous KV cache allocation. Memory management via `--ctx-size` limits. |

**You don't configure PagedAttention directly.** You configure its parameters:
```bash
# vLLM — control block allocation
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3-70B-Instruct \
  --gpu-memory-utilization 0.90 \    # 90% of VRAM for KV cache + model
  --block-size 16 \                  # tokens per block (default: 16)
  --swap-space 4 \                   # GB of CPU RAM for swapped blocks
  --max-num-seqs 256                 # max concurrent sequences
```

---

## Primary Sources

- **vLLM paper:** Kwon et al. 2023, "Efficient Memory Management for Large Language Model Serving with PagedAttention" — https://arxiv.org/abs/2309.06180
- **vLLM repository:** https://github.com/vllm-project/vllm
- **vAttention (alternative approach):** https://arxiv.org/abs/2405.04437
- **vLLM blog post:** https://blog.vllm.ai/2023/06/20/vllm.html

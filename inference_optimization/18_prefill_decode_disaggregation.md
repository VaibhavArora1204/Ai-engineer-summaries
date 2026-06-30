# Prefill-Decode Disaggregation — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Prefill and decode have opposite hardware requirements running on the same GPU.**

Prefill (processing the prompt) is **compute-bound**: all prompt tokens processed in parallel. It fully utilizes tensor cores but doesn't stress memory bandwidth.

Decode (generating tokens) is **memory-bandwidth bound**: one token at a time, entire model weights read from HBM per token. Tensor cores sit mostly idle.

Running both on the same GPU means:
- During prefill: memory bandwidth is underutilized
- During decode: compute is underutilized
- Neither phase runs at peak efficiency

```
Same GPU running both (current default):
  Prefill: GPU compute used 90%, memory bandwidth used 30%
  Decode:  GPU compute used  5%, memory bandwidth used 90%
  
  Average utilization: poor for both dimensions
```

---

## How It Works

### The Architecture

Split the serving infrastructure into two fleets optimized for their respective phase:

```
┌─────────────────────────────────────────────────────────┐
│                    REQUEST ROUTER                        │
└───────────────┬───────────────────────┬─────────────────┘
                │                       │
        ┌───────▼──────────┐   ┌───────▼──────────┐
        │   PREFILL FLEET  │   │   DECODE FLEET   │
        │                  │   │                  │
        │  GPU: H100       │   │  GPU: A100/L40   │
        │  Optimized for:  │   │  Optimized for:  │
        │  - Compute       │   │  - Memory BW     │
        │  - Short bursts  │   │  - Long sessions │
        │  - High FLOPS    │   │  - High VRAM     │
        └────────┬─────────┘   └───────▲──────────┘
                 │                     │
                 │   KV CACHE TRANSFER │
                 └─────────────────────┘
```

### Step-by-Step Flow

```
1. REQUEST ARRIVES → Router sends to Prefill node
2. PREFILL NODE:
   - Processes entire prompt in one forward pass (compute-bound, fast)
   - Produces KV cache for all prompt tokens
   - Transfers KV cache to Decode node via RDMA/network
3. DECODE NODE:
   - Receives KV cache
   - Generates tokens autoregressively (memory-bound)
   - Streams tokens back to client
   - When done, frees KV cache
```

### KV Cache Transfer: The Critical Path

The KV cache must move from prefill to decode node. This is the bottleneck:

```
KV cache size for Llama-3 70B, 4096-token prompt:
  = 2 × 80 layers × 8 KV heads × 128 dim × 4096 tokens × 2 bytes
  ≈ 10 GB

Transfer over 400 Gbps InfiniBand:
  10 GB / 50 GB/s = 200ms

Transfer over RDMA (Remote Direct Memory Access):
  10 GB / 100 GB/s = 100ms

This 100-200ms transfer adds to TTFT. Whether this is acceptable
depends on whether the prefill compute time saved on the decode
fleet outweighs the transfer cost.
```

### DistServe (2024)

First major paper on prefill-decode disaggregation:

```
DistServe key insights:
  1. Separate prefill and decode into different GPU pools
  2. Use placement optimization to assign requests to pools
  3. Result: both pools run at near-peak efficiency for their workload type
  
Performance:
  - Up to 4.48× improvement in meeting SLO (service level objectives)
  - TTFT and ITL SLOs can be set independently
  - Prefill fleet auto-scales based on prompt length distribution
  - Decode fleet auto-scales based on concurrent generation load
```

### Mooncake (Kimi/Moonshot, 2025)

Takes disaggregation further with a distributed KV cache pool:

```
Mooncake architecture:
  - Prefill nodes compute KV cache
  - KV cache stored in a CLUSTER-WIDE CPU DRAM POOL (not just one node)
  - Decode nodes fetch KV cache from the pool on demand
  - Cache PERSISTS across requests with shared prefixes
  - "Trading storage for computation"
  
Innovation: KV cache is no longer per-request ephemeral storage.
It becomes a reusable asset. If 1000 users share the same RAG
context, compute KV cache once, store it, serve 1000 requests
without re-prefilling.
```

---

## The Numbers

| Metric | Co-located (default) | Disaggregated | Improvement |
|--------|---------------------|---------------|-------------|
| SLO attainment (TTFT + ITL) | 1× | 2-4.5× | DistServe paper |
| Prefill throughput | Limited by decode memory | Maximized | Fleet-level |
| Decode throughput | Limited by prefill compute | Maximized | Fleet-level |
| GPU utilization | 40-60% | 75-90% | Hardware efficiency |
| KV cache reuse | Per-request only | Cross-request (Mooncake) | Huge for RAG |

**When disaggregation wins most:**
- High prompt-to-generation ratio (long prompts, short outputs): prefill dominates, dedicated prefill fleet shines
- High concurrency: many simultaneous requests with shared context
- Strict SLOs: TTFT and ITL targets that co-located serving can't meet

---

## Where It Lives in the Stack

**Layer: Infrastructure architecture — multi-fleet serving topology.**

This is not a model change or a kernel change. It's a fundamental redesign of the serving infrastructure:

```
Before: one type of GPU fleet handles everything
After:  two specialized fleets + KV cache transfer layer + router

Components you need:
  1. Request router (decides which prefill node to use)
  2. KV cache transfer service (RDMA or high-speed network)
  3. Prefill fleet (compute-optimized GPUs)
  4. Decode fleet (memory-optimized GPUs)
  5. Potentially: distributed KV cache store (Mooncake-style)
```

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| Both phases run at peak hardware efficiency | Infrastructure complexity (two fleets) |
| Independent scaling of prefill and decode | KV cache transfer latency (100-200ms) |
| Better SLO attainment | Network bandwidth for KV transfer |
| KV cache reuse across requests (Mooncake) | Operational complexity (twice as many failure modes) |
| Cost optimization (different GPU types per fleet) | Distributed systems complexity |

**When NOT to disaggregate:**
- Low request volume (single GPU handles everything fine)
- Simple deployments where operational complexity isn't justified
- Short prompts (prefill is fast, transfer overhead > savings)

---

## What It Combines With

**Stacks well with:**
- **KV Caching (01):** The KV cache IS the data that moves between fleets. Efficient cache format is critical.
- **Prefix Caching (20):** Mooncake's persistent KV cache pool enables massive prefix sharing across requests.
- **Continuous Batching (17):** Each fleet runs its own continuous batching scheduler optimized for its workload.
- **PagedAttention (04):** Both fleets use paged KV cache. Transfer granularity aligns with block size.
- **FlashAttention (03):** Prefill fleet runs FA on the compute-heavy attention. Decode fleet runs decode-optimized attention.
- **Tensor Parallelism (10):** Each fleet can use TP independently (e.g., prefill on 4-GPU TP, decode on 2-GPU TP).
- **Quantized Kernels (09):** Decode fleet can use more aggressive quantization (memory-bound → quantization helps more).

**Conflicts with:**
- Nothing directly. Disaggregation is an infrastructure pattern that wraps around other optimizations.

---

## Implementation Today

| Framework / System | Support | Notes |
|-------------------|---------|-------|
| **DistServe** | Research prototype | Paper + code: https://github.com/LLMServing/DistServe |
| **Mooncake** | Production (Kimi) | Paper published, internal system |
| **TensorRT-LLM** | Experimental (2025) | NVIDIA blog on PD disaggregation |
| **SGLang** | Experimental PD split | Active development |
| **vLLM** | Not yet (as of mid-2025) | Discussed in roadmap |
| **Splitwise** | Microsoft research | https://arxiv.org/abs/2311.18677 |

**Current status:** Prefill-decode disaggregation is the **frontier of production LLM serving** in 2025. Major inference providers (Kimi, likely Anthropic, likely Google) use variants internally. Open-source implementations are maturing but not yet production-ready for most teams.

**This is where the industry is heading.** If you're designing a new large-scale serving system, plan for disaggregation from the start.

---

## Primary Sources

- **DistServe:** Zhong et al. 2024, "DistServe: Disaggregating Prefill and Decoding for Goodput-optimized Large Language Model Serving" — https://arxiv.org/abs/2401.09670
- **Mooncake:** Qin et al. 2025, "Mooncake: A KVCache-centric Disaggregated Architecture for LLM Serving" — https://www.usenix.org/conference/fast25/presentation/qin
- **Splitwise (Microsoft):** https://arxiv.org/abs/2311.18677
- **TensorRT-LLM PD disaggregation blog:** https://developer.nvidia.com/blog/tensorrt-llm-prefill-decode
- **Tetriinfer (ByteDance):** https://arxiv.org/abs/2401.11181

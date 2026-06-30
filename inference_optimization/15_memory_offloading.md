# Memory Offloading — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Model weights and/or KV cache exceed GPU VRAM.**

A 70B model at BF16 = 140 GB. Even with 4-bit quantization = 35 GB. An A100 has 80 GB. After KV cache allocation, you may not have room for the model, or the KV cache may exceed remaining VRAM at long contexts.

Memory offloading moves data that doesn't fit in GPU VRAM to CPU RAM or NVMe SSD, loading it back to GPU on demand.

---

## How It Works

### Weight Offloading (llama.cpp style)

Load some model layers on GPU, keep the rest on CPU. Process tokens layer by layer, transferring weights as needed.

```
70B model, 80 layers, GPU has room for 40 layers:

GPU VRAM: Layers 0-39 (permanently resident)
CPU RAM:  Layers 40-79

Forward pass:
  Layers 0-39: compute on GPU (fast, weights already in VRAM)
  Layer 40:    transfer weights CPU→GPU via PCIe, compute, discard from GPU
  Layer 41:    transfer weights CPU→GPU via PCIe, compute, discard
  ...
  Layer 79:    transfer weights CPU→GPU via PCIe, compute, discard

The "ngl" parameter in llama.cpp: Number of GPU Layers
  ngl=80: all layers on GPU (fastest, needs all VRAM)
  ngl=40: half on GPU, half on CPU (50% speed)
  ngl=0:  all on CPU (slowest, no GPU needed)
```

### KV Cache Offloading

Keep the KV cache for less-active requests in CPU RAM. Swap back to GPU when the request needs to generate.

```
vLLM swap mechanism:
  1. GPU VRAM full, new request arrives
  2. Scheduler identifies lowest-priority request (e.g., longest idle)
  3. SWAP OUT: copy its KV cache blocks from GPU → CPU RAM
  4. Free the GPU blocks for new request
  5. When swapped-out request needs to generate:
     SWAP IN: copy KV cache blocks from CPU → GPU
     
  Configuration:
    --swap-space 4    # 4 GB of CPU RAM reserved for swapped KV cache
```

### Mooncake's Approach (Cluster-Level KV Offloading)

KV cache isn't just offloaded to local CPU — it's distributed across a cluster-wide CPU DRAM pool:

```
Mooncake architecture (Kimi/Moonshot, 2025):
  - Prefill nodes: compute KV cache for prompts
  - KV cache stored in a distributed CPU DRAM pool
  - Decode nodes: pull KV cache from the pool on demand
  - Cache persists across requests (for repeated contexts)
  
"Trading storage for computation" — storing KV cache is cheaper
than recomputing it for every request with the same prefix.
```

### DeepSpeed ZeRO-Infinity

Designed for training but applicable to inference:

```
ZeRO stages (progressive offloading):
  Stage 1: Partition optimizer states across GPUs
  Stage 2: + Partition gradients
  Stage 3: + Partition parameters (model weights)
  Infinity: + Offload everything to CPU/NVMe

For inference: ZeRO-3 + offload enables serving models
that exceed total GPU VRAM across all GPUs by using CPU/NVMe
as overflow storage.
```

---

## The Numbers

| Offload Target | Bandwidth | Latency Impact | Use Case |
|----------------|-----------|----------------|----------|
| GPU VRAM (no offload) | 2-3.35 TB/s (HBM) | Baseline | Production serving |
| CPU RAM (via PCIe 4.0) | 32 GB/s | 4-10× slower | Dev/test, large models on small GPU |
| CPU RAM (via PCIe 5.0) | 64 GB/s | 2-5× slower | Better but still significant |
| NVMe SSD | 5-7 GB/s | 50-100× slower | Last resort, very large models |

**llama.cpp example (Llama-3 70B Q4, single RTX 4090 24GB):**
```
ngl=0 (all CPU):    ~5 tokens/sec
ngl=20 (25% GPU):   ~15 tokens/sec
ngl=40 (50% GPU):   ~25 tokens/sec
ngl=60 (75% GPU):   ~35 tokens/sec (if Q4 fits)
ngl=80 (all GPU):   Won't fit — OOM
```

---

## Where It Lives in the Stack

**Layer: Serving framework memory manager / model loader.**

- **Weight offloading:** Implemented in the model loader. llama.cpp, DeepSpeed, and HuggingFace Accelerate all support this.
- **KV cache offloading:** Implemented in the serving scheduler (vLLM's swap mechanism).

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| Run models that don't fit in VRAM | Significant latency penalty (PCIe is 10-100× slower than HBM) |
| Lower hardware cost (fewer GPUs) | Throughput drops proportionally to offloaded fraction |
| Enable experimentation on consumer hardware | Not viable for latency-sensitive production serving |
| KV cache swap: more concurrent requests | Swap in/out latency when requests resume |

**The fundamental tradeoff:** Offloading trades **latency and throughput** for **capability** (running models that otherwise can't fit). It is not a performance optimization — it is a capability enabler.

**When offloading makes sense:**
- Development and testing (prototype with big models on small GPUs)
- Offline batch processing (latency doesn't matter)
- Consumer/edge deployment (llama.cpp on laptops)
- KV cache swap: maintaining more concurrent sessions than VRAM allows

**When offloading doesn't make sense:**
- Production serving with latency SLAs
- High-throughput online inference

---

## What It Combines With

**Stacks well with:**
- **Quantized Kernels (09):** Quantize to INT4 first (4× smaller), then offload remaining excess. Minimizes what needs offloading.
- **KV Caching (01):** KV cache offloading is specifically about managing the KV cache's memory footprint.
- **PagedAttention (04):** vLLM's swap mechanism offloads entire KV cache blocks. Block granularity makes swap efficient.
- **Mixed Precision (08):** BF16 halves the weight size, reducing what needs offloading.

**Conflicts with:**
- **Tensor Parallelism (10):** TP assumes all weight shards are in GPU VRAM. Offloading a shard defeats TP's purpose — use more GPUs instead.
- **Continuous Batching (17):** Swap latency can stall the continuous batching scheduler when swapping requests back in.

---

## Implementation Today

| Framework | Weight Offload | KV Cache Offload | Notes |
|-----------|---------------|-----------------|-------|
| **llama.cpp** | ✅ (`-ngl` param) | ❌ | Most mature for consumer hardware |
| **vLLM** | ❌ | ✅ (`--swap-space`) | KV cache swap to CPU RAM |
| **HuggingFace Accelerate** | ✅ (`device_map="auto"`) | ❌ | Automatic layer-to-device mapping |
| **DeepSpeed** | ✅ (ZeRO-3 + offload) | ❌ | Training + inference |
| **TGI** | ❌ | ❌ | — |
| **TensorRT-LLM** | ❌ | ❌ | Assumes all weights in VRAM |

**HuggingFace Accelerate (simplest weight offload):**
```python
from transformers import AutoModelForCausalLM

model = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Llama-3-70B-Instruct",
    device_map="auto",     # automatically distributes across GPU + CPU
    torch_dtype=torch.bfloat16,
    offload_folder="./offload"  # NVMe offload for overflow
)
```

---

## Primary Sources

- **llama.cpp:** https://github.com/ggml-org/llama.cpp
- **DeepSpeed ZeRO:** Rajbhandari et al. 2020 — https://arxiv.org/abs/1910.02054
- **DeepSpeed ZeRO-Infinity:** https://arxiv.org/abs/2104.07857
- **HuggingFace Accelerate:** https://github.com/huggingface/accelerate
- **Mooncake (cluster-level KV offload):** https://www.usenix.org/conference/fast25/presentation/qin
- **InfLLM (KV offload to CPU):** https://arxiv.org/abs/2402.04617

# Synthesis: How Inference Optimizations Stack

The previous 20 guides covered individual inference optimization techniques. In production, these techniques do not exist in isolation. Modern serving engines (like vLLM, TensorRT-LLM, SGLang, and TGI) combine them to achieve 10-100× throughput improvements over naive PyTorch eager execution.

This synthesis document maps how these technologies layer together to form the modern AI engineering serving stack.

---

## 1. The Taxonomy of Bottlenecks

Every optimization addresses a specific bottleneck in the LLM generation lifecycle. Understanding what you are bound by dictates which optimization matters.

### Phase 1: Prefill (Processing the Prompt)
**Bottleneck:** Compute (Tensor Cores / FLOPS).
**Why:** The entire prompt is processed in parallel. Matrix multiplications are large (`seq_len × hidden_dim`). The GPU's arithmetic units are fully engaged.
**Optimizations that help:**
- FlashAttention (03)
- Mixed Precision / FP8 (08)
- Tensor Parallelism (10)
- Prefix Caching (20) — bypasses prefill entirely!

### Phase 2: Decode (Generating Tokens)
**Bottleneck:** Memory Bandwidth (HBM to SRAM speed).
**Why:** Generation is autoregressive (one token at a time). For every single token generated, the *entire model's weights* must be loaded from GPU memory to the compute units. The GPU spends ~95% of its time waiting for weights to arrive.
**Optimizations that help:**
- Batch Inference (05) / Continuous Batching (17) — amortizes weight loading across many requests
- Quantized Kernels (09) — makes weights smaller so they load faster
- Speculative Decoding (02) / Parallel Decoding (07) — generates multiple tokens per weight load
- PagedAttention (04) — prevents VRAM fragmentation so you can run larger batches

---

## 2. The Dependency Stack

Optimizations are not just a list of options; they are a dependency stack. You cannot effectively run higher-level scheduler optimizations if the foundational memory structures are missing.

### Layer 1: The Foundation (Model & Precision)
*You must have these.*
- **Mixed Precision (08):** BF16 or FP16. (FP32 is obsolete).
- **GQA/MQA (19):** Built into the model architecture. Shrinks KV cache dramatically.
- **Quantization (09):** INT4/INT8/FP8 weights if memory bandwidth is the severe bottleneck.

### Layer 2: The Core Kernels
*These replace naive PyTorch operations with hardware-aware math.*
- **FlashAttention (03):** Eliminates the O(n²) memory bottleneck of the attention mechanism.
- **Marlin/ExLlama Kernels (09):** Required if using quantized weights; dequantizes in registers.
- **Graph Optimization/TensorRT (13):** Fuses standard operations (LayerNorm, residual adds) to eliminate redundant memory round-trips.

### Layer 3: Memory Management
*These dictate how VRAM is allocated.*
- **KV Caching (01):** The fundamental requirement for autoregressive generation.
- **PagedAttention (04):** Replaces contiguous KV cache allocation with virtual memory pages. Eliminates VRAM fragmentation.

### Layer 4: Scheduling & Orchestration
*These dictate how requests flow through the system.*
- **Continuous Batching (17):** Replaces static batches. Slotting new requests into the pipeline at every iteration.
- **Prefix Caching (20):** Reusing KV cache pages across different requests.

### Layer 5: Algorithmic Decode Acceleration
*Trading extra compute (which is abundant during decode) for lower latency.*
- **Speculative Decoding (02):** Using a draft model.
- **Parallel Decoding (07):** Medusa heads, lookahead decoding.

### Layer 6: Distributed Architecture
*When one GPU isn't enough.*
- **Tensor Parallelism (10):** Splitting weights across GPUs in the same node (NVLink).
- **Pipeline Parallelism (11):** Splitting layers across multiple nodes (InfiniBand).
- **Prefill-Decode Disaggregation (18):** Splitting the prefill compute and decode compute into entirely separate GPU fleets.

---

## 3. The "Standard Production Stack" (2025)

If you deploy vLLM or TensorRT-LLM today out of the box, you are automatically using this stack:

1. **BF16 Weights** (08)
2. **Continuous Batching** (17) with **Chunked Prefill** (16)
3. **PagedAttention** (04) for memory management
4. **FlashAttention-2/3** (03) for the attention computation
5. **Automatic Prefix Caching** (20) for agentic/RAG overlap

*This stack provides roughly 10-20× the throughput of naive PyTorch.*

If you need **maximum throughput** (cost efficiency), you add:
6. **FP8 or AWQ INT4 Quantization** (09)
7. **Tensor Parallelism** (10) across an 8x H100 node

If you need **minimum latency** (interactive chat), you add:
6. **Speculative Decoding** (02) with a matched draft model
7. **Streaming Generation** (16)

---

## 4. Incompatibilities and Tensions

Not everything stacks perfectly. Some optimizations fundamentally conflict or create severe engineering complexities when combined:

1. **Speculative Decoding (02) vs Continuous Batching (17):**
   - Continuous batching wants predictable, uniform step times.
   - Speculative decoding accepts a variable number of tokens per step (1 to K).
   - This makes scheduler implementation extremely difficult (though frameworks like vLLM are solving it).

2. **Early Exit Decoding (06) vs Pipeline Parallelism (11):**
   - If a token exits at layer 10 (GPU 0), the remaining GPUs in the pipeline (layers 11-80) are left with pipeline bubbles. Early exit is practically unusable with pipeline parallelism.

3. **PagedAttention (04) vs Vanilla FlashAttention (03):**
   - FlashAttention assumes contiguous memory blocks.
   - PagedAttention scatters KV cache across fragmented blocks.
   - Requires modified, highly complex FlashAttention kernels (which vLLM maintains).

4. **Prefill-Decode Disaggregation (18) vs Speculative Decoding (02):**
   - Moving KV cache across the network takes time. Adding speculative decoding to a disaggregated setup requires the draft model to sit on the decode node, complicating VRAM allocation.

---

## 5. The Evolution: Where the Bottlenecks Move

Optimization is a game of whack-a-mole. When you solve one bottleneck, the system becomes bound by something else.

1. **Era 1 (Pre-2023): Memory Capacity Bound.**
   - Models didn't fit. You OOM'd.
   - *Solution:* Tensor Parallelism, Memory Offloading, Quantization.
   
2. **Era 2 (2023): Memory Fragmentation Bound.**
   - We fit the models, but batch sizes were tiny because KV cache reserved too much contiguous space.
   - *Solution:* PagedAttention, Continuous Batching.

3. **Era 3 (2024): Memory Bandwidth Bound.**
   - We fixed fragmentation, so we cranked up batch sizes. But loading weights for generation is too slow.
   - *Solution:* Speculative Decoding, AWQ/Marlin kernels, FP8.

4. **Era 4 (2025+): Prefill vs Decode Contention.**
   - At scale, interleaving compute-heavy prefill (RAG context) with bandwidth-heavy decode (generation) on the same GPU destroys efficiency.
   - *Solution:* Prefill-Decode Disaggregation (Mooncake, DistServe).

## Final Takeaway for the AI Engineer

You do not need to write CUDA kernels. But you **must** understand this stack because it dictates your architectural decisions:
- If you use Agent loops with 90% overlapping context, you *must* select a serving framework that supports Prefix Caching (SGLang/vLLM), or your cloud bill will be 5× higher than necessary.
- If you build an interactive coding assistant, you *must* use Speculative Decoding for low latency at batch=1.
- If you run bulk offline data extraction, you *must* maximize Batch Inference with Continuous Batching and ignore Speculative Decoding.

The model is just a matrix of weights. **The serving engine is the actual product.**

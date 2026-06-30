# Batch Inference — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: GPU underutilization when serving one request at a time.**

A single LLM inference request at batch_size=1 uses a tiny fraction of the GPU's compute capacity. The model weights must be loaded from HBM regardless — whether you process 1 token or 256 tokens. At batch=1, the GPU does ~1 TFLOP of useful work while capable of ~300 TFLOPS. Batch inference amortizes the cost of weight loading across multiple requests.

```
Without batching (batch=1):
  Load 140 GB of weights → compute 1 token → repeat
  GPU utilization: ~1-5%
  Throughput: ~30 tokens/sec

With batching (batch=64):
  Load 140 GB of weights → compute 64 tokens → repeat
  GPU utilization: ~40-80%
  Throughput: ~1500 tokens/sec
```

---

## How It Works

### Static Batching (Baseline)

Group multiple independent requests into a single forward pass. All sequences in the batch are processed simultaneously through every layer.

```
Batch = [Request_1, Request_2, ..., Request_B]

Forward pass:
  X = [x_1; x_2; ...; x_B]    (stack inputs along batch dimension)
  For each layer:
    Q, K, V = X × W_q, X × W_k, X × W_v    (one matmul, B sequences)
    Attn = attention(Q, K, V)                 (per-sequence attention)
    X = FFN(Attn)                             (one matmul, B sequences)
  Output = [o_1; o_2; ...; o_B]              (unstack)
```

**The matmul advantage:** Matrix multiplication of `[B × n × d] × [d × d]` has the same memory-read cost as `[1 × n × d] × [d × d]` — the weight matrix is read once and reused across all B sequences. Compute scales linearly with B, but memory bandwidth stays constant. This is why batching works.

### Padding Problem

Sequences in a batch have different lengths. Static batching pads all sequences to the length of the longest:

```
Request 1: "Hello world"          (2 tokens)
Request 2: "Explain quantum physics in detail"  (6 tokens)
Request 3: "Hi"                   (1 token)

Padded batch (pad to max_len=6):
  [Hello, world, PAD,  PAD,  PAD,  PAD ]
  [Explain, quantum, physics, in, detail, PAD]
  [Hi,    PAD,  PAD,  PAD,  PAD,  PAD ]

Wasted compute: 11 out of 18 positions are padding = 61% waste
```

**Solutions to padding waste:**
- **Packed/unpadded attention:** Concatenate all sequences end-to-end, use per-sequence masks. FlashAttention's `varlen` mode supports this — zero padding waste.
- **Length bucketing:** Group requests by similar length to minimize padding.

---

## The Numbers

```
Throughput scaling with batch size (approximate, Llama-3 70B, A100 80GB):

Batch  | Tokens/sec | GPU Util | Latency (per request)
-------|------------|----------|---------------------
1      |     30     |   3%     | 33 ms/token
4      |    110     |  12%     | 36 ms/token
16     |    400     |  40%     | 40 ms/token
64     |   1200     |  75%     | 53 ms/token
128    |   1800     |  85%     | 71 ms/token
256    |   2000     |  90%     | 128 ms/token (KV cache pressure)
```

**The tradeoff is visible:** Throughput scales near-linearly up to the point where KV cache memory saturates VRAM. Beyond that, batch size is capped by memory, not compute. Individual request latency increases with batch size because requests wait for the slowest in the batch.

---

## Where It Lives in the Stack

**Layer: Serving framework scheduler.**

Batching is a scheduling decision, not a model change. The scheduler collects incoming requests, groups them, and submits batched tensors to the model executor.

```
API → Request Queue → [Scheduler: form batch] → Model Executor → Output
                        ↑ decides batch_size,
                          which requests to group,
                          when to start processing
```

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| Near-linear throughput scaling | Individual request latency increases |
| Better GPU utilization | Memory consumption scales with batch size (KV cache × B) |
| Lower cost per token | Padding waste (unless using packed attention) |
| | Maximum batch size bounded by VRAM |

**The core tradeoff: Throughput vs. Latency.**

```
Batch size 1:    Minimum latency, minimum throughput, minimum cost efficiency
Batch size 256:  Maximum throughput, high latency, maximum cost efficiency
```

Production systems tune this per SLA:
- **Interactive (chat):** Batch size 1-8, prioritize time-to-first-token
- **Batch processing (embeddings, eval):** Batch size 64-256, maximize tokens/second/dollar

---

## What It Combines With

**Stacks well with:**
- **KV Caching (01):** Each sequence in the batch maintains its own KV cache. Batch KV cache = sum of all per-sequence caches.
- **PagedAttention (04):** Manages per-sequence KV cache blocks efficiently across the batch. Without it, batching at high concurrency fragments memory.
- **FlashAttention (03):** FA's `varlen` mode enables efficient batching without padding waste.
- **Tensor Parallelism (10):** Batch of sequences distributed across GPUs — each GPU processes its shard of every sequence.
- **Mixed Precision (08):** BF16/FP16 batch processing uses half the memory per sequence, doubling the max batch size.

**Superseded by:**
- **Continuous Batching (17):** Static batching requires all sequences to finish before the next batch starts. Continuous batching replaces sequences individually as they complete. Static batching is now only used for offline/batch workloads; online serving uses continuous batching exclusively.
- **Dynamic Batching (14):** Decides batch composition dynamically based on arrival time and queue depth. Static batching with fixed batch size is naive; dynamic batching adapts.

---

## Implementation Today

| Framework | Approach | Notes |
|-----------|----------|-------|
| **vLLM** | Continuous batching (not static) | Static batching not available; always continuous. |
| **TGI** | Continuous batching | Same — static batching superseded. |
| **TensorRT-LLM** | Continuous batching | Supports both in-flight and static modes. |
| **llama.cpp** | Static batching | `llama_batch` API for batched inference. |
| **HuggingFace Transformers** | Static batching | `model.generate()` accepts batched inputs directly. Padding required. |
| **Triton Inference Server** | Dynamic batching | Configurable `max_batch_size`, `max_queue_delay`. |

**For offline batch processing (embeddings, classification):**
```python
# HuggingFace — simple static batching
inputs = tokenizer(texts, padding=True, return_tensors="pt").to("cuda")
with torch.no_grad():
    outputs = model(**inputs)
```

**For production serving:** Use vLLM or TGI. They handle batching automatically via continuous batching. You configure `max_num_seqs` (max concurrent sequences) and the framework handles the rest.

---

## Primary Sources

- **Orca (continuous batching, supersedes static):** Yu et al. 2022 — https://www.usenix.org/conference/osdi22/presentation/yu
- **FlashAttention varlen (packed batching):** https://github.com/Dao-AILab/flash-attention
- **vLLM scheduler:** https://github.com/vllm-project/vllm/blob/main/vllm/core/scheduler.py
- **Triton dynamic batching:** https://github.com/triton-inference-server/server

# Dynamic Batching — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Requests arrive asynchronously with different sizes; static batch formation wastes time or compute.**

In production, requests don't arrive in neat groups. They trickle in at variable rates. Without dynamic batching, you either:
- Process each request individually (batch=1, low throughput)
- Wait for a fixed batch to fill up (high throughput but added latency for early arrivals)

Dynamic batching intelligently groups requests within a time window, balancing throughput and latency.

---

## How It Works

### The Mechanism

The scheduler maintains a request queue and forms batches based on two thresholds:

```
WHILE serving:
  Wait until EITHER:
    a. Queue size >= max_batch_size, OR
    b. max_queue_delay has elapsed since first queued request
  
  Form batch from queued requests
  Execute batch
  Return results

Parameters:
  max_batch_size:  maximum requests per batch (memory bound)
  max_queue_delay: maximum wait time before forming undersized batch (latency bound)
```

```
Timeline example (max_batch=4, max_delay=50ms):

t=0ms:   Request A arrives → queue: [A]
t=10ms:  Request B arrives → queue: [A, B]
t=30ms:  Request C arrives → queue: [A, B, C]
t=50ms:  max_delay hit     → FORM BATCH [A, B, C] (undersized but timely)
t=51ms:  Batch executing...
t=52ms:  Request D arrives → queue: [D] (next batch)
```

### Handling Variable-Length Sequences

Sequences in a batch have different lengths. Two approaches:

**Padding (naive):**
```
Batch: ["Hello" (1 token), "How are you doing today" (6 tokens)]
Padded: ["Hello PAD PAD PAD PAD PAD", "How are you doing today"]
Waste: 5/12 = 42% compute on padding
```

**Packed/unpadded (efficient):**
```
FlashAttention varlen mode:
  Concatenate: ["Hello", "How", "are", "you", "doing", "today"]
  cu_seqlens: [0, 1, 7]  (cumulative sequence lengths)
  
  Attention computed with sequence boundary masks.
  Zero padding. Zero wasted compute.
```

### Triton Inference Server's Dynamic Batching

NVIDIA's Triton is the most mature dynamic batching implementation:

```protobuf
# config.pbtxt
dynamic_batching {
  preferred_batch_size: [4, 8, 16]
  max_queue_delay_microseconds: 100000  # 100ms
}
```

Features:
- **Preferred batch sizes:** Kernel performance varies with batch size. Triton forms batches at "sweet spot" sizes.
- **Priority levels:** High-priority requests skip the queue.
- **Sequence batching:** For stateful models, groups requests from the same sequence together.

---

## The Numbers

| Configuration | Throughput | Avg Latency | P99 Latency |
|--------------|-----------|-------------|-------------|
| No batching (batch=1) | 30 tok/s | 33 ms | 35 ms |
| Static batch=16 | 400 tok/s | 80 ms | 200 ms |
| Dynamic (delay=10ms) | 350 tok/s | 45 ms | 80 ms |
| Dynamic (delay=50ms) | 420 tok/s | 70 ms | 120 ms |
| Dynamic (delay=100ms) | 450 tok/s | 100 ms | 180 ms |

**The tuning knob:** `max_queue_delay` directly trades latency for throughput. Lower delay = lower latency, lower throughput. Higher delay = more requests batched, higher throughput, but first-queued request waits longer.

---

## Where It Lives in the Stack

**Layer: Serving framework scheduler.**

Dynamic batching is a scheduling policy, not a model change. It sits between the API endpoint and the model executor.

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| Better GPU utilization than batch=1 | Added latency for early arrivals (waiting for batch to form) |
| Lower latency than waiting for full batch | Padding waste if not using packed attention |
| Adapts to variable request rates | Tuning max_batch_size and max_delay per workload |

**Superseded by Continuous Batching for LLMs:** Dynamic batching forms discrete batches. Continuous batching (topic 17) goes further — it doesn't form discrete batches at all. New requests join the in-flight batch at every iteration boundary. For LLM serving, continuous batching is strictly superior.

Dynamic batching is still relevant for:
- Non-LLM models (image classification, embedding models)
- Triton Inference Server deployments with mixed model types
- Embedding generation workloads

---

## What It Combines With

**Stacks well with:**
- **FlashAttention (03):** FA's varlen mode eliminates padding waste in dynamically-formed batches.
- **Mixed Precision (08):** Half-precision doubles the max batch size.
- **Batch Inference (05):** Dynamic batching is the intelligent version of static batching.

**Superseded by:**
- **Continuous Batching (17):** For LLM inference, continuous batching is the production standard. Dynamic batching is for non-autoregressive workloads.

---

## Implementation Today

| Framework | Support | Notes |
|-----------|---------|-------|
| **Triton Inference Server** | Full | Most mature dynamic batching. Configurable via model config. |
| **TorchServe** | Supported | `batch_size` and `max_batch_delay` in config. |
| **vLLM** | N/A | Uses continuous batching instead. |
| **TGI** | N/A | Uses continuous batching instead. |
| **BentoML** | Supported | `@bentoml.api(batchable=True, max_batch_size=32)` |

---

## Primary Sources

- **Triton Inference Server:** https://github.com/triton-inference-server/server
- **Triton dynamic batching docs:** https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/model_configuration.html#dynamic-batcher
- **vLLM scheduler (continuous batching alternative):** https://github.com/vllm-project/vllm/blob/main/vllm/core/scheduler.py

# Continuous Batching (In-Flight Batching) — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Static batching wastes GPU cycles waiting for the longest sequence to finish.**

In static batching, a batch of N requests starts together and the batch doesn't complete until ALL sequences finish generating. If one request generates 500 tokens and another generates 10 tokens, the 10-token request's GPU slot sits idle for 490 decode steps. GPU utilization under static batching at high load: ~30-40%.

---

## How It Works

### The Mechanism

The scheduler operates at **iteration granularity** (every single forward pass / decode step), not at batch granularity:

```
STATIC BATCHING:
  Batch = [R1, R2, R3, R4]
  Step 1: all 4 sequences decode
  Step 2: all 4 sequences decode
  ...
  Step 50: R2 finishes (generates EOS). GPU slot IDLE.
  Step 51-200: R1, R3, R4 still decoding. R2's slot wasted.
  Step 200: R1 finishes. Now R1 + R2 slots wasted.
  Step 500: last sequence finishes. Release batch. Start new batch.

CONTINUOUS BATCHING:
  Running batch: [R1, R2, R3, R4]
  Step 1: all 4 decode
  ...
  Step 50: R2 finishes → IMMEDIATELY replace with R5 from queue
  Running batch: [R1, R5, R3, R4]
  Step 51: all 4 decode (R5 starts its prefill or first decode)
  Step 100: R4 finishes → replace with R6
  Running batch: [R1, R5, R3, R6]
  ...
  
  GPU slots are NEVER idle while the queue has requests.
```

### The Scheduler Loop (Orca-style)

```python
# Simplified continuous batching scheduler
class ContinuousBatchScheduler:
    def __init__(self, max_batch_size):
        self.max_batch = max_batch_size
        self.running = []       # currently generating sequences
        self.waiting = []       # queued requests

    def step(self):
        """Called EVERY forward pass iteration."""
        
        # 1. Remove finished sequences
        finished = [s for s in self.running if s.is_done()]
        for s in finished:
            self.running.remove(s)
            yield s.output  # return result to client
        
        # 2. Fill empty slots with waiting requests
        while len(self.running) < self.max_batch and self.waiting:
            new_seq = self.waiting.pop(0)
            new_seq.run_prefill()  # process prompt
            self.running.append(new_seq)
        
        # 3. Run one decode step for ALL running sequences
        if self.running:
            self.decode_step(self.running)
    
    def decode_step(self, sequences):
        """Single forward pass for all sequences in the batch."""
        # Each sequence generates one token
        # FlashAttention handles variable-length sequences efficiently
        batch_decode(sequences)
```

### Prefill vs Decode in Continuous Batching

A critical detail: new requests need **prefill** (process the entire prompt) before they can start **decoding** (generate tokens). Prefill is compute-heavy; decode is memory-bound. Mixing them in the same batch creates scheduling challenges:

```
Scenario: Running batch has 3 decoding sequences. New request arrives.

Option A: Prefill interrupts decoding
  - Pause all 3 decoding sequences
  - Run prefill for new request
  - Resume decoding (now 4 sequences)
  - Problem: decoding sequences stall during prefill → ITL spike

Option B: Chunked prefill (vLLM approach)
  - Break new request's prompt into chunks
  - Interleave prefill chunks with decode steps
  - Each iteration: decode existing sequences + prefill one chunk
  - Problem: prefill takes longer, but decode isn't disrupted

Option C: Disaggregate prefill and decode (topic 18)
  - Separate hardware for prefill and decode
  - Best of both worlds but requires more infrastructure
```

---

## The Numbers

| Metric | Static Batching | Continuous Batching | Improvement |
|--------|----------------|---------------------|-------------|
| GPU utilization | 30-40% | 80-95% | 2-3× |
| Throughput (tokens/sec) | Baseline | 10-36× (high load) | Dramatic |
| Request wait time | Wait for batch to form | Immediate insertion | Lower latency |
| Slot waste | 60-70% (waiting for longest) | <5% | Near-zero |

**From the Orca paper (2022):** Continuous batching achieved 10-36× throughput improvement over static batching under high request rates. The improvement is largest when:
- Requests have high variance in output length
- Request arrival rate is high (queue is rarely empty)

---

## Where It Lives in the Stack

**Layer: Serving framework scheduler — the core scheduling algorithm.**

Continuous batching is the scheduler's main loop. It determines:
- When to admit new requests
- When to remove finished requests
- How to handle preemption (if memory is full)
- How to interleave prefill and decode

Every modern LLM serving framework uses continuous batching as the default.

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| 10-36× throughput over static | More complex scheduler |
| Near-zero GPU slot waste | Prefill/decode mixing can cause ITL spikes |
| Immediate request admission | Memory management complexity (KV cache grows dynamically) |
| | PagedAttention or equivalent required |

**The prefill/decode tension is the main engineering challenge.** When a new request's prefill is interleaved with ongoing decode, the decode step slows down for all other requests. Solutions:
1. Chunked prefill (vLLM, SGLang) — most common
2. Prefill-decode disaggregation (topic 18) — highest performance

---

## What It Combines With

**Stacks well with:**
- **PagedAttention (04):** Continuous batching requires dynamic KV cache management. PagedAttention provides this — blocks allocated/freed per iteration.
- **KV Caching (01):** Every sequence in the running batch has its own KV cache. The scheduler tracks cache state.
- **FlashAttention (03):** FA's varlen mode handles the variable-length sequences in a continuous batch efficiently.
- **Streaming (16):** Each decode iteration produces tokens that can be streamed immediately.
- **Prefix Caching (20):** Shared prefixes across requests in the batch share KV cache blocks.
- **Tensor Parallelism (10):** Each GPU processes its shard of the continuous batch.

**Conflicts/interactions:**
- **Speculative Decoding (02):** Draft-then-verify creates variable-length accept/reject patterns that complicate the per-iteration scheduler. Active research problem.
- **Pipeline Parallelism (11):** Continuous batching with PP requires micro-batches to flow through pipeline stages. Each stage must handle dynamic batch composition changes.
- **Early Exit Decoding (06):** Sequences exiting at different layers create scheduling inconsistencies within a single iteration.

---

## Implementation Today

| Framework | Status | Notes |
|-----------|--------|-------|
| **vLLM** | Default, always on | Cannot be disabled. Core architecture. |
| **TGI** | Default | HuggingFace implementation. |
| **TensorRT-LLM** | Supported ("in-flight batching") | NVIDIA's term for continuous batching. |
| **SGLang** | Default | With RadixAttention for prefix sharing. |
| **llama.cpp** | Not supported (single-sequence or simple batching) | No continuous batching scheduler. |
| **Triton Inference Server** | Via vLLM/TRT-LLM backend | Triton uses the backend framework's scheduler. |

**You don't configure continuous batching — you configure its parameters:**
```bash
# vLLM
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3-70B-Instruct \
  --max-num-seqs 256 \           # max sequences in running batch
  --max-num-batched-tokens 4096 \ # max tokens processed per iteration
  --enable-chunked-prefill        # interleave prefill with decode
```

---

## Primary Sources

- **Orca:** Yu et al. 2022, "Orca: A Distributed Serving System for Transformer-Based Generative Models" — https://www.usenix.org/conference/osdi22/presentation/yu
- **vLLM (implements Orca-style scheduling):** https://arxiv.org/abs/2309.06180
- **vLLM scheduler source:** https://github.com/vllm-project/vllm/blob/main/vllm/core/scheduler.py
- **SGLang (RadixAttention + continuous batching):** https://arxiv.org/abs/2312.07104

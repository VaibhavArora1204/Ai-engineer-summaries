# LLM Inference Optimization — The Deep Engineering Guide

> Everything you need to know to take an LLM from "it works" to "it runs at scale."  
> Source: Chip Huyen *AI Engineering* Ch. 9, vLLM papers, FlashAttention, production systems.

---

## 1. The Two Phases: Why LLM Inference Is Fundamentally Different

Every LLM inference call has **two distinct computational phases** with completely different hardware bottlenecks:

```
┌───────────────────────────────────────────────────────────┐
│                     LLM INFERENCE                         │
│                                                           │
│  ┌─────────────┐        ┌──────────────────────────────┐  │
│  │   PREFILL    │───────→│           DECODE              │  │
│  │  (prompt)    │        │   (generation, token by token)│  │
│  └─────────────┘        └──────────────────────────────┘  │
│                                                           │
│  Compute-bound           Memory-bandwidth-bound           │
│  Parallelizable          Sequential                       │
│  Measured by: TTFT       Measured by: TPOT                │
│  Idle memory bandwidth   Idle FLOPs                       │
└───────────────────────────────────────────────────────────┘

TTFT = Time To First Token (prefill latency)
TPOT = Time Per Output Token (decode latency per token)
```

**Why this matters for architecture decisions:**

| Phase | Bottleneck | What limits it | Optimization target |
|-------|-----------|----------------|---------------------|
| Prefill | Compute (FLOPS) | GPU math throughput | More FLOPS, tensor parallelism |
| Decode | Memory bandwidth | Speed of reading model weights from VRAM | Smaller model (quantization), KV cache management |

### The Math Behind the Bottleneck

For a transformer model, the number of FLOPs per token during decode:
```
FLOPs_per_token ≈ 2 × P   (where P = model parameters)

For Llama-3 70B: FLOPs_per_token ≈ 140 GFLOPs
```

But the memory that must be loaded per token:
```
Memory_per_token ≈ P × bytes_per_param

For Llama-3 70B in FP16: 70B × 2 bytes = 140 GB
```

**On an A100 (80GB, 2TB/s bandwidth, 312 TFLOPS):**
- Compute time to process one token: 140 GFLOPs / 312 TFLOPS = **0.45 ms**
- Memory time to load weights: 140 GB / 2 TB/s = **70 ms**

The GPU sits idle **99.4% of the time** during decode, just waiting for weights to stream from VRAM. This is why decode is memory-bandwidth-bound — you're paying for FLOPS you can't use.

### Utilization Metrics

```
MFU (Model FLOPS Utilization) = actual_FLOPS / peak_FLOPS
    → Measures compute efficiency. Prefill achieves 30-60% MFU.
    → Decode achieves <1% MFU (because it's not compute-bound).

MBU (Model Bandwidth Utilization) = actual_bandwidth / peak_bandwidth  
    → Measures memory efficiency. Decode achieves 60-80% MBU.
    → This is what you optimize for decode.
```

**Production implication:** If your workload is prefill-heavy (long prompts, short outputs), optimize for compute. If decode-heavy (short prompts, long outputs), optimize for memory bandwidth.

---

## 2. Quantization: The Highest-Impact Single Optimization

> Weight-only quantization is by far the most popular approach since it's easy to use, works out of the box for many models, and is extremely effective. — Huyen

### How Quantization Reduces the Bandwidth Bottleneck

Since decode is memory-bandwidth-bound, reducing the size of weights directly translates to faster decode:

```
FP32 (32 bits) → FP16 (16 bits) : 2× speedup, ~0% quality loss
FP16 (16 bits) → INT8 (8 bits)  : 2× speedup, 0.5-1% quality loss  
INT8 (8 bits)  → INT4 (4 bits)  : 2× speedup, 1-5% quality loss (varies)

Total FP32→INT4: 8× memory reduction, 4-8× throughput improvement
```

### Quantization Techniques Compared

#### Post-Training Quantization (PTQ) — No retraining needed

```python
# GPTQ — Layer-by-layer second-order quantization
# Uses Hessian information to minimize quantization error per layer
# Good quality, slow to quantize (hours for 70B)

from transformers import AutoModelForCausalLM, GPTQConfig

quantization_config = GPTQConfig(
    bits=4,                    # Target precision
    dataset="c4",              # Calibration dataset
    group_size=128,            # Quantize in groups of 128 weights
    desc_act=True,             # Order by activation magnitude (better quality)
    damp_percent=0.1           # Dampening factor for Hessian
)
model = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Llama-3-70B",
    quantization_config=quantization_config,
    device_map="auto"
)
```

#### AWQ (Activation-Aware Weight Quantization) — Best quality at INT4

```python
# AWQ key insight: not all weights are equally important.
# Weights connected to high-activation channels matter more.
# AWQ identifies these "salient" channels via calibration data 
# and scales them up before quantization to preserve precision.

# The algorithm:
# 1. Run calibration data through the model
# 2. For each weight matrix, find channels with highest average activation
# 3. Scale those channels UP (e.g., multiply by s), then quantize
# 4. At inference, divide activations by s to compensate
# 5. Net effect: salient weights lose less precision

from awq import AutoAWQForCausalLM

model = AutoAWQForCausalLM.from_pretrained("meta-llama/Llama-3-70B")
model.quantize(
    tokenizer,
    quant_config={
        "w_bit": 4,           # 4-bit weights
        "q_group_size": 128,  # Group quantization
        "zero_point": True,   # Asymmetric quantization (better for skewed distributions)
        "version": "gemm"     # Optimized GEMM kernel
    }
)
model.save_quantized("llama3-70b-awq")
```

**AWQ vs GPTQ in practice:**
| | AWQ | GPTQ |
|---|---|---|
| Quantization speed | Fast (minutes) | Slow (hours) |
| INT4 quality | Better (activation-aware) | Good (second-order) |
| Inference speed | Faster (fused kernels) | Slightly slower |
| Framework support | vLLM, TGI, llama.cpp | vLLM, TGI, AutoGPTQ |
| **Best for** | **Production serving** | Research, offline batch |

#### FP8 — Near-lossless for Hopper GPUs

```
FP8 (E4M3 format): 4 exponent bits, 3 mantissa bits
  → Better dynamic range than INT8
  → <0.1% quality loss on most benchmarks
  → Requires H100/H200 (Hopper architecture) hardware support
  → The best option if you have the hardware
```

### Quantization Decision Matrix

```
┌──────────────────────────────────────────────────────────┐
│              QUANTIZATION DECISION TREE                   │
│                                                          │
│  Have H100/H200?                                         │
│  ├─ YES → Use FP8 (near-lossless, fastest)              │
│  └─ NO                                                   │
│      ├─ Quality-critical? (medical, legal, finance)      │
│      │  ├─ YES → INT8 (safe, <0.5% quality loss)        │
│      │  └─ NO → AWQ INT4 (best throughput/quality)      │
│      └─ Running locally / edge?                          │
│         └─ Use GGUF Q4_K_M via llama.cpp                │
└──────────────────────────────────────────────────────────┘
```

---

## 3. Speculative Decoding: Breaking the Sequential Bottleneck

> Speculative decoding uses a faster but less powerful model to generate a sequence of tokens, which are then verified by the target model. — Huyen

### How It Works (Step by Step)

```
Input tokens: x₁, x₂, ..., xₜ

Step 1: DRAFT model generates K tokens quickly:
        xₜ₊₁, xₜ₊₂, ..., xₜ₊ₖ    (e.g., K=5)

Step 2: TARGET model verifies all K tokens IN PARALLEL
        (one forward pass, not K sequential passes)

Step 3: Target accepts the longest prefix it agrees with.
        Say it accepts j tokens: xₜ₊₁, ..., xₜ₊ⱼ
        Then generates one additional token: xₜ₊ⱼ₊₁

Step 4: Return to Step 1 with the new prefix.

Best case:  all K accepted → K+1 tokens per iteration (K× speedup)
Worst case: 0 accepted → 1 token per iteration (same as normal)
```

### Why Verification Is Cheap

```
Verification of K tokens = essentially PREFILL (parallel, compute-bound)
Generation of K tokens   = K × DECODE steps (sequential, bandwidth-bound)

Since prefill is 10-100× faster per token than decode,
verifying K tokens costs roughly the same as generating 1 token.
```

### The Three Key Insights

1. **Verification is parallelizable.** The target model can score all K draft tokens simultaneously — it's just a forward pass on a longer sequence (like prefill).

2. **Easy tokens are predictable.** In natural language, 40-70% of tokens are "easy" (articles, prepositions, continuations). A small draft model gets these right, leading to high acceptance rates.

3. **Decode has idle FLOPs.** Since decode is memory-bandwidth-bound, the compute used for verification is essentially "free" — you're using FLOPS that would otherwise be idle.

### Implementation Sketch (Conceptual PyTorch)

```python
import torch

def speculative_decode(target_model, draft_model, input_ids, K=5, max_tokens=100):
    """
    Speculative decoding: draft K tokens, verify with target, accept prefix.
    Mathematically produces IDENTICAL output to target model alone.
    """
    generated = input_ids.clone()
    
    for _ in range(max_tokens // K):  # outer loop
        # Step 1: Draft model generates K tokens autoregressively
        draft_tokens = []
        draft_probs = []
        draft_input = generated.clone()
        
        for _ in range(K):
            with torch.no_grad():
                logits = draft_model(draft_input).logits[:, -1, :]
                probs = torch.softmax(logits, dim=-1)
                token = torch.multinomial(probs, 1)
                draft_tokens.append(token)
                draft_probs.append(probs)
                draft_input = torch.cat([draft_input, token], dim=-1)
        
        # Step 2: Target model verifies ALL K tokens in ONE forward pass
        candidate = torch.cat([generated] + draft_tokens, dim=-1)
        with torch.no_grad():
            target_logits = target_model(candidate).logits
        
        # Step 3: Accept longest matching prefix
        accepted = 0
        for i in range(K):
            pos = generated.shape[-1] + i - 1  # position in target output
            target_probs = torch.softmax(target_logits[:, pos, :], dim=-1)
            draft_token = draft_tokens[i].item()
            
            # Acceptance criterion: 
            # Accept if target probability >= draft probability
            # (ensures output distribution matches target model exactly)
            acceptance_ratio = target_probs[0, draft_token] / draft_probs[i][0, draft_token]
            
            if torch.rand(1) < min(1, acceptance_ratio):
                accepted += 1
            else:
                break
        
        # Step 4: Keep accepted tokens + 1 new token from target
        generated = torch.cat([generated] + draft_tokens[:accepted], dim=-1)
        
        # Sample one corrected token from target model
        pos = generated.shape[-1] - 1
        correction_probs = torch.softmax(target_logits[:, pos, :], dim=-1)
        correction_token = torch.multinomial(correction_probs, 1)
        generated = torch.cat([generated, correction_token], dim=-1)
        
        if correction_token.item() == eos_token_id:
            break
    
    return generated
```

### Speculative Decoding in Production (vLLM)

```bash
# vLLM natively supports speculative decoding
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3-70B-Instruct \
  --speculative-model meta-llama/Llama-3-8B-Instruct \
  --num-speculative-tokens 5 \
  --tensor-parallel-size 4
```

**Choosing a draft model:**
- Same tokenizer/vocabulary as target (required)
- Same model family preferred (shared architecture → higher acceptance)
- 5-10× smaller than target (Llama-3-8B drafting for Llama-3-70B)
- **Acceptance rate target**: 60-80%. Below 50% → net slowdown.

**When NOT to use speculative decoding:**
- Very short outputs (< 20 tokens) — overhead exceeds benefit
- Highly creative tasks (low acceptance rate)
- When draft model loading would push target model to slower GPU memory tiers

---

## 4. KV Cache: The Hidden Memory Monster

### What the KV Cache Stores

```
For each transformer layer, for each attention head:
  - Key vector (K): one per input token
  - Value vector (V): one per input token

These are computed during prefill and REUSED at every decode step.
Without caching: recompute K, V for ALL prior tokens at each step = O(n²)
With caching: compute K, V for only the NEW token, append to cache = O(n)
```

### KV Cache Size Formula

```
KV_cache_bytes = 2 × B × S × L × H × M

Where:
  2 = one Key + one Value
  B = batch size
  S = sequence length (total: prompt + generated so far)
  L = number of transformer layers
  H = hidden dimension (= num_heads × head_dim)
  M = bytes per element (2 for FP16, 1 for INT8)
```

**Example calculations:**

```
Llama-3 8B:   L=32,  H=4096, FP16
  Batch=1,  Seq=4096:  2×1×4096×32×4096×2 =    2 GB
  Batch=32, Seq=4096:  2×32×4096×32×4096×2 =   64 GB  ← exceeds A100 80GB

Llama-3 70B:  L=80,  H=8192, FP16  
  Batch=1,  Seq=4096:  2×1×4096×80×8192×2 =   10.7 GB
  Batch=1,  Seq=128K:  2×1×131072×80×8192×2 = 343 GB  ← impossible on single GPU!

GPT-4 scale (500B+, estimated):
  Batch=512, Seq=2048:  ≈ 3 TB   (3× model weight size!)
```

**This is why you OOM under concurrent load.** Every active request needs its own KV cache. The model weights are shared, but the KV cache is per-request.

### KV Cache Optimization Strategies

#### 1. PagedAttention (vLLM's Core Innovation)

```
Traditional KV cache: pre-allocate contiguous memory for max_seq_len
  → If max_seq_len = 4096 but average = 500, you waste 87.8% of memory
  → Can't share memory between requests

PagedAttention: allocate KV cache in fixed-size PAGES (like OS virtual memory)
  → Pages are 16 tokens each (typically)
  → Allocate pages on-demand as sequence grows
  → Free pages as sequences complete
  → Pages can be non-contiguous in physical memory

Result: 2-4× more concurrent requests on same GPU
```

**The analogy:** Traditional = reserving an entire hotel floor per guest. PagedAttention = giving guests rooms as they need them, anywhere in the building.

#### 2. Prefix Caching

```
Without prefix caching:
  Request 1: [System Prompt] + [User Query A] → compute KV for entire input
  Request 2: [System Prompt] + [User Query B] → recompute KV for SAME system prompt

With prefix caching:
  Request 1: [System Prompt] + [User Query A] → compute KV, CACHE system prompt KV
  Request 2: [System Prompt] + [User Query B] → REUSE cached KV, compute only query B

If system prompt = 1000 tokens:
  1M requests/day × 1000 tokens = 1B tokens of redundant computation saved/day
```

**Cost savings from major providers:**
| Provider | Mechanism | Savings |
|----------|-----------|---------|
| Anthropic | Prompt caching API | Up to 90% cost, 79% latency |
| Google Gemini | Context caching | 75% discount on cached tokens |
| OpenAI | Automatic prefix caching | 50% discount on cached tokens |

**How to maximize prefix cache hit rate:**
- Keep system prompt IDENTICAL across requests (character-for-character)
- Put system prompt FIRST (prefix matching is left-to-right)
- Don't inject timestamps or request IDs into system prompt
- Use long, detailed system prompts (higher savings ratio)

#### 3. KV Cache Quantization

```
Store KV cache in INT8 instead of FP16:
  → 2× capacity (double concurrent requests)
  → Small quality impact (KV values have limited dynamic range)
  → Supported in vLLM via --kv-cache-dtype int8
```

#### 4. Attention Mechanism Redesign (Training-Time Decisions)

These reduce KV cache at the architecture level:

```
Multi-Head Attention (MHA):  Each head has its own K, V  (standard)
Multi-Query Attention (MQA): ALL heads share ONE K, V   (massive reduction)
Grouped-Query Attention (GQA): Groups of heads share K, V (balance)

KV cache comparison for 32-head model:
  MHA: 32 K vectors + 32 V vectors = 64 vectors per layer
  GQA (8 groups): 8 K + 8 V = 16 vectors per layer     → 4× reduction
  MQA: 1 K + 1 V = 2 vectors per layer                  → 32× reduction

Models using GQA: Llama-3 (8 KV heads for 32 query heads)
Models using MQA: Falcon, PaLM
```

**Character.AI case study:** Combined MQA + local/global interleaved attention + cross-layer attention → **20× KV cache reduction**. Memory was no longer the bottleneck for serving large batch sizes.

---

## 5. FlashAttention: The Kernel That Changed Everything

### The Problem It Solves

Standard attention computation:
```python
# Naive attention (pseudocode)
Q, K, V = linear(x)              # Shape: (batch, seq_len, d_model)
scores = Q @ K.T / sqrt(d_k)     # Shape: (batch, seq_len, seq_len)  ← O(n²) MEMORY
attention = softmax(scores)       # Materialize full n×n matrix in HBM
output = attention @ V
```

**The bottleneck:** The `scores` matrix is `seq_len × seq_len`. For seq_len=128K, that's 128K × 128K × 2 bytes = **32 GB** just for the attention scores of ONE layer, ONE head.

The actual compute is fast. The problem is reading/writing this huge matrix to/from GPU HBM (high-bandwidth memory).

### FlashAttention's Trick: Tiled Computation

```
GPU Memory Hierarchy:
  HBM (High Bandwidth Memory): ~80GB, ~2 TB/s       ← slow, large
  SRAM (On-chip):              ~20MB,  ~19 TB/s      ← fast, tiny

Standard attention:
  1. Compute S = QK^T     → write to HBM (slow)
  2. Compute P = softmax(S) → read from HBM, write back (slow)
  3. Compute O = PV        → read from HBM (slow)
  Total HBM accesses: O(N² × d) — dominated by N² materialization

FlashAttention:
  1. Load TILES of Q, K, V from HBM to SRAM
  2. Compute attention for that tile ENTIRELY in SRAM
  3. Write only the OUTPUT tile back to HBM
  4. Never materialize the full N×N attention matrix
  Total HBM accesses: O(N × d²/M)  where M = SRAM size
```

**The key insight:** By computing softmax in tiles using the "online softmax" trick (keeping running max and sum), FlashAttention avoids ever storing the full attention matrix in HBM.

### Real-World Impact

```
                  Standard Attention    FlashAttention    Speedup
Memory usage      O(N²)                O(N)              Critical for long context
A100 training     baseline             1.5-2× faster     
A100 inference    baseline             1.3-1.7× faster   
Enables seq_len   ~8K (memory limit)   128K+             Game-changing
```

**FlashAttention-2** improved parallelism across sequence length and attention heads.  
**FlashAttention-3** (for H100) exploits Hopper's new FP8 tensor cores and asynchronous memory operations → additional 1.5-2× over FA-2.

**In production:** FlashAttention is now the default in PyTorch (via `torch.nn.functional.scaled_dot_product_attention`), Hugging Face Transformers, vLLM, and virtually every modern inference framework.

---

## 6. Parallel Decoding: Beyond Speculation

### Medusa: Multiple Decode Heads

```
Standard transformer: 1 LM head → predicts next token xₜ₊₁
Medusa: 1 LM head + K extra heads → predicts xₜ₊₁, xₜ₊₂, ..., xₜ₊ₖ₊₁

Each Medusa head is a small MLP trained to predict the token at position +k:
  Head 0 (original): predicts xₜ₊₁  
  Head 1 (new):      predicts xₜ₊₂
  Head 2 (new):      predicts xₜ₊₃
  ...

Each head generates top-c candidates → tree of possibilities.
Tree attention mechanism selects the best valid path.

Result: up to 1.9× generation speedup (NVIDIA Llama 3.1 on H200)
```

**Trade-off:** Requires training the Medusa heads (frozen base model + train heads). Not a drop-in optimization.

### Inference with Reference (No Extra Model Needed)

```
When output overlaps with input (code editing, RAG, multi-turn chat):
  → Instead of GENERATING tokens, COPY matching spans from the input
  → Verify copied spans the same way as speculative decoding

Use cases:
  - Code completion (output = input with small edits)
  - RAG answers (output quotes from retrieved docs)  
  - Multi-turn conversation (output repeats user's question)

Result: 2× speedup on overlap-heavy tasks, zero additional model needed
```

---

## 7. Service-Level Optimization

### Batching Strategies

```
Static Batching:
  Wait for batch_size requests → process all → return all
  ✗ First request waits for last to arrive
  ✗ All requests wait for longest generation to finish

Dynamic Batching:
  Process batch when EITHER batch full OR timeout (e.g., 100ms)
  ✓ Limits wait time
  ✗ Still: all wait for longest generation

Continuous Batching (vLLM, TGI):
  As each request FINISHES, its slot is immediately filled by a new request
  Requests are returned AS THEY COMPLETE — no waiting for the batch

  Analogy: 
    Static  = bus waits until every seat is full, all get off at last stop
    Dynamic = bus leaves on schedule or when full
    Continuous = bus picks up and drops off passengers continuously (like Uber Pool)
```

**Continuous batching is the production default.** It's what makes vLLM, TGI, and TensorRT-LLM so much faster than naive implementations.

### Prefill-Decode Disaggregation

```
Problem: Prefill (compute-heavy) and Decode (memory-heavy) compete for GPU resources

When BOTH run on same GPU:
  - New request arrives → prefill computation starves ongoing decode requests
  - TPOT spikes for in-flight requests (bad UX: users see generation "stutter")

Solution: Run prefill and decode on SEPARATE GPU pools

┌─────────────────┐         ┌──────────────────┐
│  Prefill GPUs    │────────→│   Decode GPUs     │
│  (compute-heavy) │  KV     │  (bandwidth-heavy)│
│  Process prompts │ cache   │  Generate tokens   │
│  Compute KV cache│transfer │  Read KV cache     │
└─────────────────┘         └──────────────────┘

Prefill : Decode GPU ratio depends on workload:
  Long prompts, short outputs, TTFT priority → 2:1 to 4:1
  Short prompts, long outputs, TPOT priority → 1:2 to 1:1
```

Papers: DistServe (Zhong et al., 2024), Splitwise (Patel et al., 2024)

---

## 8. The PyTorch Optimization Stack (Real Case Study)

From PyTorch's own benchmark on Llama-7B (A100 80GB):

```
Step 1: Baseline (eager PyTorch)              → 25 tok/s
Step 2: torch.compile (kernel fusion + JIT)   → 65 tok/s  (2.6×)
Step 3: INT8 weight quantization              → 115 tok/s (4.6×)
Step 4: INT4 weight quantization              → 175 tok/s (7.0×)  
Step 5: + Speculative decoding                → 200 tok/s (8.0×)

That's an 8× throughput improvement through pure optimization,
no model quality changes (INT4 has minor impact), same hardware.
```

### The Optimization Stacking Principle

Optimizations are **multiplicative**, not additive:
```
Quantization INT4:        4× memory reduction → 4× more concurrent requests
Continuous batching:      2-3× better GPU utilization  
Prefix caching:           Eliminates 50-90% of redundant prefill
FlashAttention:           1.5-2× attention speedup
Speculative decoding:     1.5-2.5× decode speedup
Prefill/decode disagg.:   30-50% better resource utilization

Combined: 20-50× improvement over naive implementation
```

---

## 9. Choosing What to Optimize: The Decision Framework

### By Workload Type

| Workload | Primary Bottleneck | Top Optimizations |
|----------|-------------------|-------------------|
| Chatbot (short turns) | Decode latency (TPOT) | Quantization, speculative decoding, streaming |
| RAG Q&A (long context) | KV cache memory | PagedAttention, GQA, prefix caching, KV cache quant |
| Batch processing | Throughput (tok/s/$) | Continuous batching, INT4 quantization, large batch |
| Code completion | Decode + overlap | Speculative decoding, inference with reference |
| Long document analysis | Prefill latency (TTFT) | Tensor parallelism, FlashAttention, context parallelism |
| Multi-model serving | GPU memory | Quantization, LoRA adapter merging, replica packing |

### By Budget

```
$0 (software-only):
  → Continuous batching (vLLM)
  → FlashAttention (enabled by default in modern frameworks)
  → Prefix caching
  → torch.compile

Small budget (engineering time):
  → INT4 quantization (AWQ)
  → Speculative decoding setup
  → Separate batch/interactive endpoints

Large budget (hardware):
  → H100/H200 for FP8
  → Tensor parallelism across multiple GPUs
  → Prefill-decode disaggregation
  → Custom kernels for your specific workload
```

---

## 10. Production Serving Architecture: Putting It All Together

```
                         ┌──────────────────────────┐
                         │     API Gateway           │
                         │  Rate limit (by tokens)   │
                         │  Request routing           │
                         └──────────┬───────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ↓               ↓               ↓
            ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
            │ Interactive   │ │ Interactive   │ │   Batch      │
            │ Endpoint      │ │ Endpoint      │ │   Endpoint   │
            │ (low latency) │ │ (low latency) │ │ (high thru)  │
            └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
                   │                │                │
            ┌──────────────────────────────────────────────┐
            │              vLLM Cluster                     │
            │                                              │
            │  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
            │  │ GPU 0+1  │  │ GPU 2+3  │  │ GPU 4+5  │   │
            │  │ Model     │  │ Model     │  │ Model     │   │
            │  │ Replica A │  │ Replica B │  │ Replica C │   │
            │  │ TP=2      │  │ TP=2      │  │ TP=2      │   │
            │  └──────────┘  └──────────┘  └──────────┘   │
            │                                              │
            │  Shared Prefix Cache (system prompts)        │
            │  PagedAttention KV cache management          │
            │  Continuous batching                          │
            │  AWQ INT4 or FP8 quantization                │
            └──────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │  Monitoring Stack  │
                    │  - Tokens/sec      │
                    │  - KV cache util % │
                    │  - Queue depth     │
                    │  - P99 latency     │
                    │  - GPU memory %    │
                    └───────────────────┘
```

**Key design decisions:**
1. **Separate interactive and batch endpoints** — different latency/throughput tradeoffs
2. **Tensor parallelism within node** (TP=2 or TP=4) — not across nodes (network overhead kills latency)
3. **Prefix-aware routing** — route requests with same system prompt to same replica
4. **Token-based rate limiting** — not request-based (a 100-token request ≠ a 10K-token request)
5. **Monitor KV cache utilization** — the leading indicator of OOM before it happens

---

*Guide synthesized from: Chip Huyen "AI Engineering" Ch. 9, vLLM papers (Kwon et al., 2023), FlashAttention (Dao et al., 2022), DistServe (Zhong et al., 2024), Medusa (Cai et al., 2024), PyTorch optimization case study (2023). Last updated: June 2026.*

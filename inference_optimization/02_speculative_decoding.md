# Speculative Decoding — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Memory bandwidth during autoregressive decoding.**

LLM decoding is **memory-bandwidth bound**, not compute bound. Here's why:

During the decode phase, the model generates one token at a time. Each step requires loading the *entire model's weights* from GPU HBM (high-bandwidth memory) to the compute units. For a 70B parameter model at FP16, that's ~140 GB of weight reads per token generated.

The GPU's compute units (tensor cores) can multiply matrices at ~300 TFLOPS on an H100. But the memory bandwidth is ~3.35 TB/s. The arithmetic intensity (FLOPs per byte read) of decode is approximately:

```
Arithmetic intensity = 2 × batch_size / bytes_per_param

For batch=1, FP16: 2 × 1 / 2 = 1 FLOP/byte
H100 can deliver:   ~300 TFLOPS compute, ~3.35 TB/s bandwidth
Compute needs:      ~1 TFLOP (for 70B model, batch=1)
Bandwidth needs:    ~140 GB/s (read all weights)

The GPU spends ~4% of its time computing and ~96% waiting for weight transfers.
```

**The GPU is almost entirely idle during token generation.** Speculative decoding exploits this idle compute.

---

## How It Works

### The Core Idea

Use a small, fast "draft" model to generate `k` candidate tokens cheaply. Then run the large "target" model once in a single forward pass to verify all `k` tokens in parallel. If the target agrees with the draft's predictions, you get `k` tokens for the cost of ~1 large model step.

### Step-by-Step Mechanism

```
1. DRAFT PHASE:
   - Run draft model (e.g., 68M params) autoregressively for k steps
   - Produces k candidate tokens: [t₁, t₂, ..., tₖ]
   - Also produces draft probability distributions: [p₁, p₂, ..., pₖ]
   - Cost: negligible (draft model is 100-1000× smaller than target)

2. VERIFY PHASE:
   - Run target model (e.g., 70B params) ONCE on the full sequence
     including all k draft tokens
   - This is a PREFILL operation (parallel, compute-bound) — NOT
     autoregressive decode. All k positions processed simultaneously.
   - Target model produces probability distributions: [q₁, q₂, ..., qₖ]

3. ACCEPT/REJECT:
   For each position i = 1 to k:
     - If target agrees (acceptance criterion met): accept token tᵢ
     - If target disagrees: reject tᵢ, sample corrected token from
       adjusted distribution, STOP (discard remaining draft tokens)
   
   Acceptance criterion (original paper):
     Accept tᵢ with probability min(1, q(tᵢ)/p(tᵢ))
     If rejected, sample from: norm(max(0, q(x) - p(x)))
   
   This ensures the output distribution is EXACTLY the same as
   running the target model alone. Not approximate — mathematically exact.

4. RESULT:
   - Best case: all k tokens accepted → k+1 tokens per large model step
   - Worst case: first token rejected → 1 token (same as no speculation)
   - Expected: acceptance_rate × k tokens per step
```

### Why Verification is Cheap

The key insight: **verification is a prefill operation, not a decode operation.** When the target model processes `[prompt + t₁ + t₂ + ... + tₖ]`, it processes all positions in parallel. This is compute-bound (not memory-bandwidth bound), so it fully utilizes the GPU's tensor cores. One verify step costs roughly the same wall-clock time as generating 1 token autoregressively.

### Draft Model Variants

| Variant | How it works | Pros | Cons |
|---------|-------------|------|------|
| **Separate small model** (original) | Independent model, same vocabulary | Simple, any compatible model | Must align tokenizers, extra model memory |
| **EAGLE** | Uses target model's penultimate-layer features to predict next token | No separate model needed, very high acceptance rate | Requires training the prediction head |
| **EAGLE-2** | Dynamic draft tree — confidence-aware expansion | Higher acceptance than EAGLE | More complex scheduling |
| **EAGLE-3** (2025, NVIDIA) | Multi-token prediction with improved tree structure | Up to 5× speedup | Latest, less battle-tested |
| **Medusa heads** | Multiple prediction heads on target model | No separate model, multi-branch | Requires training heads |
| **N-gram lookup** | Match recent context against a lookup table | Zero compute cost, lossless | Only works for repetitive patterns |
| **Token trees** (SpecInfer) | Draft multiple branching sequences, verify as tree | Higher acceptance on diverse outputs | Complex tree attention |

---

## The Numbers

| Method | Speedup | Best conditions | Worst conditions |
|--------|---------|-----------------|------------------|
| Original (separate draft) | 2-3× | Code generation, repetitive text | Creative writing, high entropy |
| EAGLE | 2.5-3.5× | General text | Very low acceptance tasks |
| EAGLE-2 | 3-4× | Code, structured output | — |
| EAGLE-3 | Up to 5× | Coding and math tasks | — |
| SpecInfer (tree) | 2-3.5× | Tasks with multiple plausible continuations | — |

**What determines speedup:** The **acceptance rate** — what fraction of draft tokens the target model agrees with.

```
Effective speedup ≈ (1 + α × k) / (1 + c)
  where:
    α = acceptance rate (0 to 1)
    k = number of speculated tokens
    c = relative cost of draft model vs target (usually ~0.01-0.05)

Example: α=0.8, k=5, c=0.03:
  Speedup = (1 + 0.8 × 5) / (1 + 0.03) = 5.0 / 1.03 ≈ 4.85×
  
Example: α=0.4, k=5, c=0.03:
  Speedup = (1 + 0.4 × 5) / (1 + 0.03) = 3.0 / 1.03 ≈ 2.91×
```

**Acceptance rate depends on:**
- Draft/target model alignment (same family → higher acceptance)
- Task predictability (code > prose > creative writing)
- Temperature (low temperature → more predictable → higher acceptance)

---

## Where It Lives in the Stack

**Layer: Serving framework scheduler.**

Speculative decoding modifies the decode loop in the serving framework. It sits between the scheduler and the model execution:

```
Request queue → Scheduler → [Draft model run] → [Target model verify] → Token output
                               ↑ new component       ↑ modified step
```

The model architecture is unchanged. The attention kernels are unchanged. It's purely a **scheduling optimization** — the framework orchestrates two models (or two forward passes) per generation cycle.

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| 2-5× decode speedup | Additional GPU memory for draft model (if using separate model) |
| Mathematically exact output distribution | Implementation complexity |
| Better GPU utilization during decode | Scheduling complexity with continuous batching |
| | Acceptance rate varies per query — unpredictable speedup |

**Critical tradeoff: Speculative decoding helps individual request latency but can HURT throughput.** Here's why:

In a high-throughput scenario (many concurrent requests), the GPU is already busy — the memory bandwidth is saturated by serving many requests in a large batch. Speculative decoding adds overhead (draft model forward passes, verification) without benefit, because the GPU isn't idle anymore.

**Rule:** Speculative decoding is most valuable at **low batch sizes** (interactive, latency-sensitive). At high batch sizes (offline batch processing), it provides diminishing returns or even slows things down.

---

## What It Combines With

**Stacks well with:**
- **KV Caching (01):** Mandatory. Both draft and target models use KV caching. The draft's KV cache is separate and tiny.
- **FlashAttention (03):** The verification step (which is a prefill) benefits from FlashAttention's IO-efficient attention.
- **Quantized Kernels (09):** Draft model can be aggressively quantized (INT4) since it only needs to be "close enough" to the target.
- **Mixed Precision (08):** Target model at FP16/BF16, draft model at INT4/INT8.
- **Prefix Caching (20):** Shared prefix KV states can be reused by both draft and target models.

**Conflicts/interactions:**
- **Continuous Batching (17):** This is an **active research problem**. Draft-then-verify creates variable-length batches because different requests have different numbers of accepted tokens. The scheduler must handle requests that accepted 5 tokens alongside requests that accepted 1 token in the same batch. vLLM and SGLang have implementations, but the scheduling is complex.
- **Pipeline Parallelism (11):** If the target model is split across multiple GPUs via pipeline parallelism, the verify step must pipeline through all stages. The draft model typically fits on one GPU.
- **Tensor Parallelism (10):** Works fine — the verification forward pass distributes across GPUs the same way a normal forward pass does.

---

## Implementation Today

| Framework | Support | Details |
|-----------|---------|---------|
| **vLLM** | Built-in (v0.3+) | `--speculative-model` flag. Supports separate draft model. EAGLE support added in later versions. |
| **SGLang** | Native | Outperforms vLLM on several spec decode benchmarks per SSD paper. |
| **TensorRT-LLM** | Supported | Draft model + Medusa heads. NVIDIA-optimized kernels for tree verification. |
| **TGI** | Supported | `--speculate` flag with configurable draft model. |
| **llama.cpp** | Supported | `--draft` flag. Separate GGUF draft model. |
| **HuggingFace** | `assisted_generation` | `model.generate(assistant_model=draft_model)`. Simplest API. |

**Entry point (simplest):**
```python
# HuggingFace assisted generation
from transformers import AutoModelForCausalLM, AutoTokenizer

target = AutoModelForCausalLM.from_pretrained("meta-llama/Llama-3-70B-Instruct")
draft = AutoModelForCausalLM.from_pretrained("meta-llama/Llama-3-8B-Instruct")
tokenizer = AutoTokenizer.from_pretrained("meta-llama/Llama-3-70B-Instruct")

inputs = tokenizer("Explain KV caching:", return_tensors="pt")
outputs = target.generate(
    **inputs, 
    assistant_model=draft,  # speculative decoding
    max_new_tokens=200
)
```

**Entry point (production, vLLM):**
```bash
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3-70B-Instruct \
  --speculative-model meta-llama/Llama-3-8B-Instruct \
  --num-speculative-tokens 5 \
  --tensor-parallel-size 4
```

---

## Primary Sources

- **Original paper:** Leviathan et al. 2022, "Fast Inference from Transformers via Speculative Decoding" — https://arxiv.org/abs/2211.17192
- **EAGLE:** https://arxiv.org/abs/2401.15077
- **EAGLE-2 (dynamic draft trees):** https://arxiv.org/abs/2406.16858
- **EAGLE-3 (2025, NVIDIA):** https://arxiv.org/abs/2503.01840
- **SpecInfer (token trees):** https://arxiv.org/abs/2305.09781
- **Speculative Speculative Decoding (SSD, 2025):** https://arxiv.org/abs/2603.03251
- **vLLM speculative decoding docs:** https://docs.vllm.ai/en/latest/features/spec_decode.html

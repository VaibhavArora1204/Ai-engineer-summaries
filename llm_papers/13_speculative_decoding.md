# Paper 13: Speculative Decoding (Leviathan et al., 2022)

## What Existed Before and What Broke

Autoregressive generation (Paper 2) produces tokens one at a time. Each token requires a full forward pass through the model. During this forward pass, the GPU is massively underutilized — the bottleneck is loading model weights from HBM (memory-bandwidth bound), not computing (compute-bound). GPU utilization during single-token generation: typically 30-40% of peak FLOPS.

```
The utilization problem:

  A100 GPU specifications:
    Peak compute: 312 TFLOPS (BF16)
    HBM bandwidth: 2 TB/s
    
  During autoregressive decoding of a 70B model:
    Each forward pass loads ~140 GB of model weights from HBM
    Time for weight loading: 140 GB / 2 TB/s = 70 ms
    Time for actual computation: ~10-20 ms
    
    GPU spends 70-80% of each step WAITING for weights to load.
    Compute utilization: ~25-35%
    
    You're renting a $30,000 GPU and using a quarter of it.
```

The fundamental issue: for a single request, each token is generated sequentially, and each generation step is memory-bandwidth bound. You can't parallelize the generation of a single request's tokens (the model needs token N to generate token N+1). Batching multiple requests helps GPU utilization, but doesn't reduce per-request latency.

Speculative decoding breaks through this wall by exploiting one key asymmetry: **verification is cheaper than generation.**

---

## The Core Mechanism

### The Core Insight

Generating tokens autoregressively is sequential and memory-bandwidth bound. But **verifying** whether a sequence of tokens is correct can be done in a single forward pass — because verification is just a standard forward pass over known tokens, which is parallelizable across sequence positions (the same operation as processing a prompt).

```
Generation (sequential):
  Step 1: forward pass → generate token 1
  Step 2: forward pass → generate token 2
  Step 3: forward pass → generate token 3
  
  3 sequential forward passes. Each memory-bandwidth bound.

Verification (parallel):
  Given candidate tokens [1, 2, 3]:
  One forward pass → compute probabilities for ALL positions simultaneously
  Check: does the target model agree with each candidate token?
  
  1 forward pass. Same memory loading as one generation step.
  Verifies 3 tokens in the time it takes to generate 1.
```

### How Speculative Decoding Works

Two models: a small **draft model** (fast, cheap) and a large **target model** (slow, expensive, high-quality).

```
Step 1: Draft phase
  Small model generates k tokens quickly (k = 4-8 typically):
  Draft: [t₁, t₂, t₃, t₄]
  
  Small model forward passes: 4 sequential steps
  Time: ~4 × 5ms = 20ms (small model is fast)

Step 2: Verification phase
  Large model processes the ENTIRE draft sequence in ONE forward pass:
  Input: [prompt, t₁, t₂, t₃, t₄]
  Output: probability distributions at each position
  
  Large model forward passes: 1 parallel step
  Time: ~70ms (one forward pass of the large model)

Step 3: Accept/Reject
  For each position i = 1, 2, 3, 4:
    Compare: P_target(t_i) vs P_draft(t_i)
    
    If target agrees with draft (token is "accepted"):
      Keep this token. Move to next position.
    
    If target disagrees at position j:
      Accept tokens 1 through j-1.
      Sample a corrected token at position j from the target distribution.
      Discard tokens j+1 onwards.
      Resume drafting from position j+1.

Example walkthrough:
  Draft generates: ["The", "cat", "sat", "down"]
  Target verifies:
    Position 1: "The"  → target agrees    → ACCEPT
    Position 2: "cat"  → target agrees    → ACCEPT  
    Position 3: "sat"  → target agrees    → ACCEPT
    Position 4: "down" → target says "on" → REJECT, sample "on" from target
  
  Result: 3 tokens accepted + 1 corrected = 4 tokens in ~90ms total
  Without speculative decoding: 4 × 70ms = 280ms
  Speedup: ~3x
```

### The Mathematical Guarantee — Identical Output Distribution

This is the critical property: **the output distribution of speculative decoding is provably identical to running the target model alone.** Not approximately the same. Exactly the same distribution.

The acceptance/rejection scheme uses a modified rejection sampling algorithm that guarantees the final token distribution matches the target model's distribution. When the draft is rejected, the corrected token is sampled from an adjusted distribution that exactly compensates for the draft model's bias.

This means speculative decoding is a pure latency optimization with zero quality impact. You get the exact same model quality, faster.

### Acceptance Rate — The Performance Determinant

The speedup depends on how often the draft model's tokens are accepted by the target model:

```
Acceptance rate    Effective speedup    When this happens
>90%               3-5x                Structured output, code, formulaic text
70-90%             2-3x                Standard prose, Q&A, summaries
50-70%             1.5-2x              Creative writing, diverse outputs
<50%               1-1.5x              Highly creative/unpredictable text (barely helps)

Acceptance rate depends on:
  1. Draft model quality (bigger draft = higher acceptance, but slower drafting)
  2. Output predictability (structured text = high acceptance)
  3. Task type (RAG responses are structured → high acceptance)
```

---

## What This Creates for Your System

### Free Latency Win for Structured Outputs

RAG systems generate structured, predictable outputs: cited answers, formatted summaries, JSON responses. These have high draft acceptance rates:

```
RAG response pattern:
  "Based on the provided documents, [factual content from chunks]. 
   Specifically, [Document A, Section 3.2] states that [direct quote]. 
   Therefore, [conclusion]."

This format is:
  - Highly predictable (structured template)
  - Grounded in retrieved text (model is "copying" from context)
  - Formulaic connectors ("Based on", "Specifically", "Therefore")
  
  Draft acceptance rate: 80-95%
  Expected speedup: 2.5-4x
  
  A RAG response that takes 10 seconds → 2.5-4 seconds.
  Same quality. Same model. Same output distribution.
```

### Variants — No Separate Draft Model Required

The original paper requires a separate small draft model from the same architecture family. Newer variants eliminate this requirement:

```
EAGLE (Li et al., 2024):
  Uses the target model's OWN penultimate layer features as draft signals.
  No separate draft model needed.
  Trains a lightweight "head" on top of the target model's features.
  Speedup: 3-4x on coding/math tasks.
  Deployment: one model, not two. Simpler ops.

EAGLE-3 (2025, NVIDIA):
  Refined EAGLE with better feature utilization.
  Up to 5x speedup on structured output tasks.
  Best current result for speculative decoding.

Medusa (Cai et al., 2024):
  Adds multiple prediction heads to the target model.
  Each head predicts a future token (head 1 → next token, head 2 → token after, etc.)
  Tokens verified in parallel. Similar to EAGLE but different mechanism.
  
Self-speculative decoding:
  Use the target model's early layers as a draft "model."
  Exit early (after N layers instead of all 80) to get a draft.
  Verify with the full model.
  No additional model or heads needed. Simplest deployment.
```

### Practical Deployment in vLLM

```python
# vLLM speculative decoding configuration
from vllm import LLM, SamplingParams

llm = LLM(
    model="meta-llama/Meta-Llama-3-70B-Instruct",
    speculative_model="meta-llama/Meta-Llama-3-8B-Instruct",  # Draft model
    num_speculative_tokens=5,  # Draft 5 tokens at a time
)

# Or with EAGLE (no separate draft model):
llm = LLM(
    model="meta-llama/Meta-Llama-3-70B-Instruct",
    speculative_model="path/to/eagle-head",
    spec_decoding_method="eagle",
)

# That's it. Same API. Same output quality. 2-4x faster.
```

**The deployment gap:** Most vLLM deployments don't enable speculative decoding. Engineers don't know it's there, or they assume it requires complex setup. For RAG workloads with structured outputs, enabling it is one of the highest-ROI configuration changes available.

---

## What Production Systems Changed After This

**Production serving stacks adopted it.** vLLM, TGI, and TensorRT-LLM all support speculative decoding. It's not experimental — it's a production feature with provably identical output quality.

**EAGLE became the practical standard.** The original speculative decoding required maintaining and deploying a second model with matching tokenizer. EAGLE eliminated this requirement, making adoption significantly simpler. Most new deployments that use speculative decoding use EAGLE or a variant.

**Latency SLAs became achievable.** Before speculative decoding, reducing per-request latency for a single user required either a faster GPU or a smaller model (with quality loss). Speculative decoding provides latency reduction without hardware changes or quality compromise — making latency SLAs achievable without overprovisioning.

---

## How This Connects to the Other 17 Papers

**Directly attacks Paper 2's (GPT-2) sequential generation constraint:** Autoregressive generation is sequential by architecture. Speculative decoding doesn't remove the constraint — it amortizes it by verifying multiple tokens per target model forward pass.

**Requires Paper 1's (Attention) verification property:** Verification works because a forward pass over a known sequence is the same operation as processing a prompt — all positions computed in parallel. This is the attention mechanism's parallelism applied to verification rather than prefill.

**Interacts with Paper 9 (CoT):** CoT generates many more output tokens (reasoning + answer). More tokens = more sequential generation steps = more latency. Speculative decoding's benefit scales with output length — longer outputs benefit more from the speedup. CoT makes speculative decoding more valuable.

**Interacts with Paper 14 (PagedAttention):** Both are vLLM features. PagedAttention handles memory allocation for the KV cache. Speculative decoding handles token generation speed. They're complementary and both run in production vLLM deployments.

**Interacts with Paper 12 (GQA):** The draft model's KV cache adds memory overhead. GQA on the draft model minimizes this overhead, allowing more concurrent speculative decoding requests.

---

## The Honest Take

**1. What most engineers miss when they skip this paper and just use the API:**

If you self-host any open model and your outputs are structured (RAG responses, JSON, formatted text, code), enabling speculative decoding is a configuration change in vLLM that provides 2-4x latency reduction with zero quality tradeoff. It's the closest thing to a free lunch in LLM serving. Most teams don't enable it because (a) they don't know it exists, or (b) they assume the "speculative" in the name means approximate. It's not approximate — the output distribution is provably identical.

**2. The one non-obvious systems implication that blog posts never explain:**

Speculative decoding's speedup is inversely correlated with output diversity. The more predictable your output, the higher the draft acceptance rate, the greater the speedup. This means speculative decoding provides the MOST benefit for the tasks that are MOST common in production (structured responses, formatted outputs, grounded answers) and the LEAST benefit for tasks that are LEAST common (open-ended creative writing). The optimization is most effective exactly where you need it most.

Conversely, if you're benchmarking speculative decoding on creative writing tasks and seeing minimal speedup, that's not representative of production performance. Benchmark on your actual production output distribution.

**3. Essential, useful context, or interesting history?**

**Essential if you self-host. Useful context if you use APIs.** If you self-host, this is a direct, actionable, high-ROI optimization. Enable it. If you use APIs, the provider is likely already using it (or a variant) — understanding the mechanism helps you understand why structured outputs are faster than free-form ones, and why latency varies by task type.

The key insight: speculative decoding is the proof that the autoregressive generation bottleneck (Paper 2) can be significantly mitigated without changing the model or compromising quality. It's a systems-level optimization for an architectural constraint.

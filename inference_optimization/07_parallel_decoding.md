# Parallel Decoding — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Autoregressive decoding generates exactly one token per forward pass.**

Standard LLM decoding is strictly sequential: predict token 1, feed it back, predict token 2, feed it back, ... Each forward pass through the entire model yields a single token. For a 200-token response from a 70B model, that's 200 serial forward passes — each loading 140 GB of weights from HBM.

Parallel decoding attempts to generate **multiple tokens per forward pass** without using a separate draft model (distinguishing it from speculative decoding).

---

## How It Works

### Approach 1: Medusa (2024)

Add multiple prediction heads on top of the base model. Each head predicts a *different* future token position.

```
Standard model:
  Hidden state → LM Head → next token (position t+1)

Medusa (k=3 heads):
  Hidden state → LM Head     → candidate for position t+1
              → Medusa Head 1 → candidate for position t+2
              → Medusa Head 2 → candidate for position t+3
              → Medusa Head 3 → candidate for position t+4

One forward pass → 4 candidate tokens
```

**Verification via tree attention:**
```
The 4 candidates form a tree of possible continuations.
Multiple candidate sequences are verified in a single forward pass
using tree-structured attention masking.

Example tree (2 candidates per position):
         t+1: [A, B]
        /         \
  t+2: [C, D]   [E, F]
  
Verification: run one forward pass with tree attention mask.
Accept the longest prefix that matches the base model's distribution.
```

**Training Medusa heads:** The heads are lightweight (single linear layers). They are trained on text data with the base model frozen — only the heads' parameters are updated. Training cost: a few GPU-hours, not full pretraining.

### Approach 2: Jacobi Decoding

Treat autoregressive generation as a **fixed-point iteration problem.**

```
1. Initialize all output positions with guesses (e.g., random tokens or
   copies of the input)
   
2. Run forward pass on the ENTIRE output sequence simultaneously
   (like prefill, not decode)
   
3. For each position, the model predicts what token should be there
   given all other positions' current values
   
4. Update all positions with new predictions

5. Repeat steps 2-4 until convergence (fixed point — no positions change)

Convergence: guaranteed in at most N iterations (where N = output length)
             In practice, converges much faster (3-10 iterations for 
             typical outputs)
```

**Why it works:** Many tokens are determined by local context, not long-range dependencies. Punctuation, articles, common phrases converge in 1-2 iterations regardless of what's in distant positions.

**Limitation:** In practice, Jacobi decoding provides modest speedups (1.3-2×) because convergence is not fast enough for most text generation. It shines on structured/repetitive outputs.

### Approach 3: Lookahead Decoding (2024)

Combines n-gram prediction with parallel verification.

```
1. Maintain a cache of n-grams from the generation so far
2. At each step, use n-gram matching to predict k future tokens
3. Verify all k+1 candidates in one forward pass
4. Accept the longest matching prefix

Advantage over Medusa: no training needed (uses n-gram lookup)
Disadvantage: lower acceptance rate (n-grams are less accurate than learned heads)
```

---

## The Numbers

| Method | Speedup | Training Required | Model Modification |
|--------|---------|-------------------|--------------------|
| Medusa | 2-3× | Yes (heads only, lightweight) | Add prediction heads |
| Medusa-2 | 2.5-3.5× | Yes | Add heads + tree optimization |
| Jacobi Decoding | 1.3-2× | No | None (algorithm change only) |
| Lookahead Decoding | 1.5-2.5× | No | None |

**Comparison with Speculative Decoding:**

| Aspect | Parallel Decoding (Medusa) | Speculative Decoding |
|--------|---------------------------|---------------------|
| Extra model needed | No (heads on same model) | Yes (draft model) |
| Extra memory | Tiny (few linear layers) | Significant (draft model weights + KV cache) |
| Training | Train heads (~hours) | No training (but need compatible draft) |
| Acceptance rate | Lower (heads less accurate than full model) | Higher (full model generates drafts) |
| Integration complexity | Medium | Medium-High |

---

## Where It Lives in the Stack

**Layer: Model architecture (Medusa) or serving algorithm (Jacobi, Lookahead).**

- **Medusa:** Requires adding heads to the model architecture. The model checkpoint includes Medusa head weights. Serving framework needs tree attention support.
- **Jacobi/Lookahead:** Pure algorithm changes. No model modification. Can be implemented entirely in the serving framework's decode loop.

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| Multiple tokens per forward pass | Medusa: model modification + training |
| No separate draft model needed | Medusa: verification overhead (tree attention) |
| Jacobi/Lookahead: zero training | Jacobi: modest speedup, unpredictable convergence |
| Lower memory than speculative decoding | Lookahead: only works with repetitive patterns |

**Key insight:** Parallel decoding methods are best when you want speculative-decoding-like speedups but cannot afford the memory overhead of a separate draft model. For single-GPU deployments where VRAM is tight, Medusa is often more practical than speculative decoding.

---

## What It Combines With

**Stacks well with:**
- **KV Caching (01):** Tree attention in Medusa requires modified KV cache management (tree-structured rather than linear).
- **FlashAttention (03):** Tree attention variants of FlashAttention exist. Medusa uses custom tree attention kernels.
- **Quantized Kernels (09):** Medusa heads are tiny and can be quantized aggressively.
- **GQA/MQA (19):** Medusa operates on top of the GQA attention output — compatible.

**Conflicts with:**
- **Continuous Batching (17):** Same challenge as speculative decoding — variable number of accepted tokens per request creates scheduling complexity.
- **Pipeline Parallelism (11):** Tree attention verification must flow through all pipeline stages.
- **Speculative Decoding (02):** These are competing approaches to the same problem. Using both simultaneously is theoretically possible but adds extreme complexity.

---

## Implementation Today

| Framework | Medusa | Jacobi | Lookahead |
|-----------|--------|--------|-----------|
| **vLLM** | Supported (Medusa heads) | Not supported | Not supported |
| **TGI** | Supported | Not supported | Not supported |
| **TensorRT-LLM** | Supported (Medusa + tree verify) | Not supported | Not supported |
| **SGLang** | Supported | Not supported | Supported |
| **llama.cpp** | Not supported | Not supported | Supported (`--lookahead`) |

**Medusa usage (vLLM):**
```bash
# Requires a model with trained Medusa heads
python -m vllm.entrypoints.openai.api_server \
  --model FasterDecoding/medusa-vicuna-7b-v1.3 \
  --speculative-model [medusa] \
  --num-speculative-tokens 3
```

---

## Primary Sources

- **Medusa:** Cai et al. 2024, "Medusa: Simple LLM Inference Acceleration Framework with Multiple Decoding Heads" — https://arxiv.org/abs/2401.10774
- **Lookahead Decoding:** Fu et al. 2024 — https://arxiv.org/abs/2402.02057
- **Jacobi Decoding:** Santilli et al. 2023, "Accelerating Transformer Inference for Translation via Parallel Decoding" — https://arxiv.org/abs/2305.10427
- **Medusa-2:** https://arxiv.org/abs/2405.04975

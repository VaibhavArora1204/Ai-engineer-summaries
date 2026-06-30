# Early Exit Decoding — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Every token passes through ALL layers, even when unnecessary.**

In a standard Transformer, every token traverses all N layers (e.g., 80 layers for Llama-3 70B). But not all tokens require the same amount of computation. Consider:

```
"The capital of France is ___"

Token "Paris" is highly predictable. Layer 20 out of 80 already has >99%
confidence. Layers 21-80 are wasted compute — they refine an already-certain
prediction by epsilon.

"The implications of quantum decoherence on ___"

This token genuinely needs all 80 layers. The answer depends on subtle
semantic relationships that only emerge in deep layers.
```

**20-50% of generated tokens are "easy" tokens** (punctuation, common words, predictable continuations) that could exit at intermediate layers without quality loss.

---

## How It Works

### The Mechanism

Add lightweight **classifier heads** (typically a single linear layer + softmax) at intermediate layers. During inference, after each intermediate layer, check the classifier's confidence. If confidence exceeds a threshold, exit early — skip remaining layers.

```
Standard:
  Input → Layer 1 → Layer 2 → ... → Layer N → Prediction Head → Output
  (all tokens go through all layers)

Early Exit:
  Input → Layer 1 → [Exit head: confident?] → NO → Layer 2 → [Exit head] → ...
                          ↓ YES
                      Output token (skip layers 2-N)
```

### Confidence Criterion

```python
def should_exit(logits, threshold=0.9):
    """
    Exit if the model is confident enough at this layer.
    Common criteria:
    """
    probs = softmax(logits)
    
    # Option 1: Top-1 probability exceeds threshold
    if probs.max() > threshold:
        return True
    
    # Option 2: Entropy below threshold (distribution is peaked)
    entropy = -sum(probs * log(probs))
    if entropy < entropy_threshold:
        return True
    
    # Option 3: Softmax margin (gap between top-2 tokens)
    sorted_probs = sorted(probs, reverse=True)
    if sorted_probs[0] - sorted_probs[1] > margin_threshold:
        return True
    
    return False
```

### Variants

**Static early exit:**
- Always exit at layer K for all tokens
- Simpler, no overhead from confidence checks
- Equivalent to using a shallower model
- Useful for: distillation target (train a K-layer model that matches the full model)

**Dynamic early exit (per-token):**
- Each token exits at the earliest layer where confidence is sufficient
- Maximum savings — easy tokens exit early, hard tokens use all layers
- Challenge: batched inference (see below)

**SkipDecode (2023):**
- Key insight: in batched inference, different tokens wanting to exit at different layers is a scheduling nightmare. If token A exits at layer 10 and token B needs layer 40, you can't easily stop processing A without wasting B's compute.
- Solution: batch-consistent exit layers. All tokens in a batch position exit at the same layer, but the exit layer can differ across positions (earlier positions exit earlier since they're more "settled").

---

## The Numbers

| Method | Speedup | Quality Impact | Best For |
|--------|---------|----------------|----------|
| Static exit (layer N/2) | ~2× | 2-5% quality drop | When latency matters more than quality |
| Dynamic (CALM) | 1.5-3× | <1% on easy distributions | Mixed workloads (easy + hard tokens) |
| SkipDecode | 2-5× (on long sequences) | ~1% | Batched serving with long outputs |

**The speedup is highly input-dependent.** Tasks with predictable outputs (code completion with boilerplate, template text) see 3×+ speedup. Tasks with novel outputs (creative writing, complex reasoning) see minimal benefit because most tokens need all layers.

---

## Where It Lives in the Stack

**Layer: Model architecture modification.**

Early exit requires changes to the model itself:
- Additional classifier heads at intermediate layers (small linear projections)
- Modified forward pass with conditional branching
- Training or fine-tuning to make intermediate heads accurate

This is NOT a drop-in serving optimization. It requires model modification and potentially retraining.

```
Standard model: layers are a black box, output only at the end
Early exit model: layers have exit ramps — architectural change

Model file itself must contain the exit heads.
Serving framework must support variable-depth forward passes.
```

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| 20-50% compute reduction on easy tokens | Model modification required (not a serving trick) |
| Lower average latency | Quality degrades on hard tokens if threshold is wrong |
| Proportional energy savings | Batching complexity (different tokens exit at different layers) |
| | Training overhead (exit heads need to be trained) |
| | Incompatible with pipeline parallelism (if layer 10 exits, layers 11-20 on GPU 2 idle) |

**The batching problem is the critical tradeoff.** In production, you're serving batches of sequences. If token A in position 5 exits at layer 15, but token B in position 5 of another sequence needs layer 80, you have two bad options:
1. Keep processing the entire batch until the last token finishes (no speedup)
2. Remove early-exit tokens from the batch (scheduling complexity)

SkipDecode addresses this but adds constraints on exit patterns.

---

## What It Combines With

**Stacks well with:**
- **KV Caching (01):** Early-exit tokens still produce K/V entries that must be cached for future tokens' attention. The KV cache size is unchanged — early exit saves compute, not memory.
- **Speculative Decoding (02):** Conceptually orthogonal. Draft model could use early exit for even faster drafting.
- **Mixed Precision (08):** Exit head can run at lower precision since it's just a linear classifier.

**Conflicts with:**
- **Pipeline Parallelism (11):** If a token exits at layer 10 (GPU 0), the remaining GPUs (layers 11-80) do nothing for that token. Pipeline bubbles get worse.
- **Continuous Batching (17):** Different exit layers per token make the scheduler's job much harder. Each position in the batch may have a different "effective depth."
- **Tensor Parallelism (10):** Works but the exit check requires all-gather across GPUs to evaluate the full logits at intermediate layers.

---

## Implementation Today

| Framework | Support | Notes |
|-----------|---------|-------|
| **HuggingFace Transformers** | Research-grade | Custom model implementations with exit heads. Not built-in. |
| **vLLM** | Not supported | No native early exit support. |
| **TGI** | Not supported | — |
| **TensorRT-LLM** | Not supported | Static graph compilation doesn't support dynamic exit. |
| **llama.cpp** | Not supported | — |

**Current status:** Early exit is primarily a **research technique**, not a production-deployed optimization. The batching problem and model modification requirement have limited adoption. Most production systems prefer speculative decoding (which provides similar speedups without model changes).

**If you want to experiment:**
```python
# Simplified early exit in HuggingFace
class EarlyExitModel(nn.Module):
    def __init__(self, base_model, exit_layers=[10, 20, 30]):
        super().__init__()
        self.base_model = base_model
        self.exit_heads = nn.ModuleDict({
            str(i): nn.Linear(hidden_dim, vocab_size) 
            for i in exit_layers
        })
    
    def forward(self, input_ids, threshold=0.9):
        hidden = self.base_model.embed(input_ids)
        
        for i, layer in enumerate(self.base_model.layers):
            hidden = layer(hidden)
            
            if str(i) in self.exit_heads:
                logits = self.exit_heads[str(i)](hidden)
                confidence = logits.softmax(dim=-1).max(dim=-1).values
                
                if confidence.min() > threshold:  # all tokens confident
                    return logits  # early exit
        
        return self.base_model.lm_head(hidden)  # full depth
```

---

## Primary Sources

- **CALM (Confident Adaptive Language Modeling):** Schuster et al. 2022 — https://arxiv.org/abs/2207.07061
- **SkipDecode (batch-consistent early exit):** https://arxiv.org/abs/2307.02628
- **LayerSkip (Meta, 2024):** https://arxiv.org/abs/2404.16710
- **Adaptive Depth Transformers (survey):** https://arxiv.org/abs/2401.03133

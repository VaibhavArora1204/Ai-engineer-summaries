# Sequence Parallelism — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Long-context attention is memory-prohibitive on a single GPU.**

At 128K tokens, even with FlashAttention (O(n) memory), the KV cache and intermediate activations for attention become enormous. Sequence parallelism splits the sequence across GPUs so each GPU handles a chunk of the sequence.

Additionally, tensor parallelism splits the hidden dimension but leaves **non-tensor-parallelizable operations** (LayerNorm, Dropout, residual connections) fully replicated on all GPUs. These operations consume activation memory proportional to the full sequence length on every GPU — wasted duplication.

---

## How It Works

### Megatron-LM Sequence Parallelism (for LayerNorm/Dropout)

In a tensor-parallel setup, attention and FFN are split across GPUs. But LayerNorm and Dropout operate on the full hidden dimension and cannot be tensor-parallelized. Sequence parallelism splits these operations along the **sequence dimension** instead:

```
Standard TP (without SP):
  LayerNorm: each GPU processes ALL tokens (full sequence replicated)
  Attention: each GPU processes its HEAD SHARD (tensor parallel)
  
With SP:
  LayerNorm: each GPU processes SEQ_LEN/N tokens only
  → all-gather to reconstruct full sequence for attention
  Attention: each GPU processes its HEAD SHARD (tensor parallel)  
  → reduce-scatter to distribute output back to sequence shards
  LayerNorm: each GPU processes its SEQ_LEN/N tokens
```

**Memory saving:** Activation memory for LayerNorm/Dropout/residuals is divided by N GPUs instead of replicated N times.

### Ring Attention (for Long-Context Attention)

For extremely long sequences (128K-1M+ tokens), even the attention computation itself must be distributed. Ring Attention distributes the sequence across GPUs in a ring topology:

```
4 GPUs, 128K token sequence:

GPU 0: tokens 0-32K      (Q₀, K₀, V₀)
GPU 1: tokens 32K-64K    (Q₁, K₁, V₁)
GPU 2: tokens 64K-96K    (Q₂, K₂, V₂)
GPU 3: tokens 96K-128K   (Q₃, K₃, V₃)

Ring communication (each GPU sends K,V to next GPU):
  Round 1: GPU 0 has K₀V₀, GPU 1 has K₁V₁, ...
           Each GPU computes local attention with its own K,V
           
  Round 2: GPU 0 receives K₃V₃ from GPU 3
           GPU 1 receives K₀V₀ from GPU 0
           Each GPU computes attention with received K,V
           Accumulate partial results using online softmax
           
  Round 3: K,V shift again in the ring
  Round 4: K,V shift again
  
After 4 rounds: each GPU has computed full attention over all 128K tokens
                using O(32K) memory per GPU (not O(128K))
```

**Memory per GPU:** O(seq_len / N) — scales linearly with number of GPUs. A 1M-token context on 32 GPUs requires the same per-GPU memory as 32K tokens on 1 GPU.

---

## The Numbers

| Technique | Sequence Length Supported | Memory per GPU | Overhead |
|-----------|--------------------------|----------------|----------|
| No SP (single GPU) | ≤32K (A100 80GB) | O(seq_len) | 0% |
| Megatron SP | Same as TP | Activation memory / N | ~5% (extra comm) |
| Ring Attention | Theoretically unlimited | O(seq_len / N) | 10-20% (ring comm) |
| Striped Attention | Same as Ring | O(seq_len / N) | Similar to Ring |

**Ring Attention enables the "infinite context" dream:** With enough GPUs, you can process arbitrarily long sequences. Google's Gemini 1.5 (1M-10M context) likely uses a variant of this approach.

---

## Where It Lives in the Stack

**Layer: Model architecture + parallelism framework.**

- **Megatron SP:** Integrated into Megatron-LM's tensor parallelism. Requires model code changes (insert all-gather/reduce-scatter around LayerNorm).
- **Ring Attention:** Modifies the attention computation to use ring communication. Requires custom attention kernel or framework support.

Not a "toggle on" feature in most serving frameworks. Requires specialized infrastructure.

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| Handle arbitrarily long sequences | Ring communication overhead (10-20%) |
| Linear memory scaling with GPUs | Implementation complexity |
| Megatron SP: activation memory savings | Requires high-bandwidth interconnect between GPUs |
| | Not widely supported in serving frameworks (research-stage) |

---

## What It Combines With

**Stacks well with:**
- **Tensor Parallelism (10):** Megatron SP is specifically designed to complement TP. They operate on different dimensions (hidden vs sequence).
- **FlashAttention (03):** Ring Attention uses FlashAttention-style tiled computation within each GPU's local attention block.
- **KV Caching (01):** Each GPU caches only its sequence shard's K/V.
- **Pipeline Parallelism (11):** 3D parallelism: TP (intra-layer) + PP (inter-layer) + SP (inter-sequence).

**Conflicts with:**
- **Continuous Batching (17):** Sequence parallelism across GPUs means each request's sequence is distributed. Managing this with continuous batching is complex.
- **PagedAttention (04):** Ring Attention's distributed K/V doesn't map cleanly to vLLM's block-based paging.

---

## Implementation Today

| Framework | Megatron SP | Ring Attention |
|-----------|-------------|----------------|
| **Megatron-LM** | ✅ (reference) | Partial |
| **DeepSpeed** | ✅ (Ulysses) | ✅ |
| **vLLM** | Not directly | Not supported |
| **TGI** | Not supported | Not supported |
| **JAX/XLA** | Ring Attention in Pallas | ✅ |

**Current status:** Sequence parallelism is primarily used for **training** long-context models. For **inference**, most production systems rely on FlashAttention + KV cache compression rather than distributing the sequence across GPUs. Ring Attention for inference is frontier (Google, Anthropic likely use variants internally).

---

## Primary Sources

- **Sequence Parallelism (Megatron):** Korthikanti et al. 2022 — https://arxiv.org/abs/2205.05198
- **Ring Attention:** Liu et al. 2023, "Ring Attention with Blockwise Transformers for Near-Infinite Context" — https://arxiv.org/abs/2310.01889
- **Striped Attention:** Brandon et al. 2023 — https://arxiv.org/abs/2311.09431
- **DeepSpeed Ulysses:** https://arxiv.org/abs/2309.14509

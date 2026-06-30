# FlashAttention — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Memory bandwidth in the attention computation.**

Standard self-attention computes the full `n × n` attention matrix (where `n` is sequence length) and reads/writes it to GPU HBM (High Bandwidth Memory). The attention matrix for a 4096-token sequence with 32 heads at FP16 is:

```
32 heads × 4096 × 4096 × 2 bytes = 1 GB
```

This matrix must be:
1. Written to HBM after `Q × K^T`
2. Read back for softmax
3. Written again after softmax
4. Read back for `× V`

That's 4 GB of HBM transfers for a matrix that's only needed transiently. GPU compute (tensor cores) sits idle waiting for these transfers.

**The fundamental issue:** GPU SRAM (on-chip, ~20 MB on A100) is 10-100× faster than HBM (~2 TB/s on A100). But standard attention doesn't fit the `n × n` matrix in SRAM, so it must repeatedly bounce data through the slow HBM path.

Standard attention is **2-4× slower than it needs to be** because the bottleneck is memory IO, not arithmetic.

---

## How It Works

### The Core Idea

Never materialize the full `n × n` attention matrix in HBM. Instead, tile the computation into blocks that fit entirely in SRAM, compute softmax incrementally using the **online normalizer trick**, and write only the final output to HBM.

### Step-by-Step Mechanism

**Standard Attention (what FlashAttention replaces):**
```
1. Compute S = Q × K^T              → write n×n matrix to HBM
2. Read S from HBM, compute P = softmax(S)  → write n×n matrix to HBM
3. Read P from HBM, compute O = P × V       → write output to HBM

Total HBM reads/writes: O(n² × d) for Q, K, V + O(n²) for S and P
```

**FlashAttention:**
```
1. Divide Q into blocks of size Bq (rows)
2. Divide K, V into blocks of size Bk (columns)
3. For each Q block:
   a. Load Q block into SRAM
   b. For each K, V block:
      - Load K block, V block into SRAM
      - Compute block attention: S_block = Q_block × K_block^T   (in SRAM)
      - Update running softmax statistics using online normalizer
      - Accumulate partial output: O_block += softmax(S_block) × V_block
      - NEVER write S_block or softmax to HBM
   c. Write final O block to HBM (one write per Q block)

Total HBM reads/writes: O(n × d) — reads Q, K, V once each
The n×n attention matrix NEVER exists in HBM.
```

### The Online Softmax Trick

The challenge: softmax requires knowing the maximum value across the entire row (for numerical stability) before computing any output. This normally requires two passes over the data — one to find the max, one to compute.

FlashAttention uses **online softmax** (Milakov & Gimelshein 2018):

```
For each new block of scores:
  1. Compute local max: m_new = max(m_old, max(scores_block))
  2. Rescale previous accumulator: acc = acc × exp(m_old - m_new)
  3. Add new block: acc += exp(scores_block - m_new) × V_block
  4. Update normalizer: l = l × exp(m_old - m_new) + sum(exp(scores_block - m_new))

Final output: O = acc / l
```

This computes the **mathematically exact** softmax in a single pass, block by block, without ever materializing the full row of scores.

### Why the Output is Exact

FlashAttention is **not an approximation.** The output is bit-for-bit identical to standard attention (modulo floating-point ordering, which can cause ~1e-6 differences). It achieves this by reformulating the computation order, not changing the math.

---

## The Numbers

| Version | Year | Hardware | Speedup vs Standard | Memory Reduction | Key Innovation |
|---------|------|----------|---------------------|------------------|----------------|
| FlashAttention-1 | 2022 | A100 | 2-4× wall-clock | 5-20× (no n² matrix) | IO-aware tiling, online softmax |
| FlashAttention-2 | 2023 | A100 | ~2× over FA1 | Same | Better parallelism across heads, reduced non-matmul FLOPs |
| FlashAttention-3 | 2024 | H100 | 1.5-2× over FA2 | Same + FP8 support | H100 asynchronous execution, warp specialization, FP8 |

**Concrete benchmark (FlashAttention-2, A100, seq_len=2048):**
- Standard attention: 14.2 ms
- FlashAttention-2: 3.5 ms (4× speedup)
- Memory: Standard uses 32 MB for attention matrix; FA uses 0 MB (in SRAM only)

**Scaling with sequence length:**
```
Standard attention memory: O(n²)    → at 128K tokens: ~32 GB per head
FlashAttention memory:     O(n)     → at 128K tokens: ~32 MB per head
```

FlashAttention is what makes long-context models (128K+) computationally feasible. Without it, 128K-token attention would require hundreds of GB just for the attention matrices.

---

## Where It Lives in the Stack

**Layer: CUDA kernel — drop-in replacement inside the attention block.**

FlashAttention replaces the attention computation kernel. The model architecture is completely unchanged. You swap out the attention implementation, and everything else (embeddings, FFN, layer norm, KV caching) stays the same.

```
Model Forward Pass:
  Embedding → [Layer 1: Attention → FFN → LayerNorm] → [Layer 2: ...] → ...
                       ↑
                  FlashAttention kernel replaces this
                  (standard attention removed)
```

**Integration path:**
```python
# PyTorch 2.0+ (automatic)
torch.nn.functional.scaled_dot_product_attention(Q, K, V)
# Automatically dispatches to FlashAttention if available

# Direct (manual)
from flash_attn import flash_attn_func
output = flash_attn_func(Q, K, V, causal=True)
```

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| 2-4× attention speedup | Custom CUDA kernel dependency (not portable to non-NVIDIA) |
| 5-20× attention memory reduction | Debugging is harder (fused kernel, no intermediate values) |
| Enables 128K+ context lengths | Backward pass is different (recomputation instead of saved activations) |
| Exact output (not approximate) | Hardware-specific optimizations (FA3 only works on H100) |

**The debugging tradeoff:** Because FlashAttention never materializes the attention matrix, you cannot inspect attention weights for interpretability or debugging. If you need attention maps (e.g., for visualization or attention-based pruning), you must fall back to standard attention for those specific runs.

**Non-contiguous KV blocks:** Standard FlashAttention assumes contiguous memory for K and V. PagedAttention (topic 04) stores KV cache in non-contiguous blocks. This creates a compatibility tension — vLLM's PagedAttention implementation modifies the FA kernel to support block-table lookups, which adds complexity. vAttention (2024) proposes using OS virtual memory to make non-contiguous blocks appear contiguous, preserving vanilla FA compatibility.

---

## What It Combines With

**Stacks well with:**
- **KV Caching (01):** FA operates on the cached K/V tensors. During decode, FA computes attention between new Q and cached K/V.
- **GQA/MQA (19):** FA supports grouped-query attention natively. GQA reduces the number of K/V heads, further reducing memory.
- **Mixed Precision (08):** FA2 works with FP16/BF16. FA3 adds FP8 support on H100, delivering 2× throughput over FP16.
- **Tensor Parallelism (10):** Each GPU runs FA independently on its shard of the attention heads. No conflict.
- **Sequence Parallelism (12):** FlashAttention-2 includes a variable-length mode (`flash_attn_varlen_func`) that works with sequence parallelism's packed sequences.

**Conflicts/interactions:**
- **PagedAttention (04):** Non-contiguous KV blocks require modified FA kernels. vLLM handles this, but it's a source of engineering complexity. vAttention proposes a cleaner solution.
- **Early Exit Decoding (06):** If a token exits early, it doesn't need attention at deeper layers. FA doesn't natively support per-token early exit — the kernel processes all tokens in a block uniformly.

**Flash-Decoding (separate concept):**
During *decode* (not prefill), the sequence is long but the query is a single token. Standard FA parallelizes across batch and heads but not across the KV sequence length. Flash-Decoding (Stanford, 2023) adds parallelism across the KV sequence dimension — splitting the cached K/V across thread blocks and reducing partial attention results. This specifically accelerates long-context inference at the decode phase.

---

## Implementation Today

| Framework | Support | Version |
|-----------|---------|---------|
| **PyTorch 2.0+** | `F.scaled_dot_product_attention()` dispatches to FA automatically | Requires `flash-attn` installed |
| **vLLM** | Uses FlashAttention by default | FA2 on A100, FA3 on H100 |
| **TGI** | Uses FlashAttention by default | — |
| **TensorRT-LLM** | Custom fused attention (similar principles) | NVIDIA-optimized, not vanilla FA |
| **SGLang** | Uses FlashAttention by default | — |
| **llama.cpp** | Own implementation (FlashAttention-like tiling) | GGML kernel, not Dao-AILab FA |
| **JAX/XLA** | Pallas FlashAttention kernel | Different implementation, same algorithm |

**Installation:**
```bash
pip install flash-attn --no-build-isolation
# Requires: CUDA 11.6+, PyTorch 1.12+, Ampere (A100) or Hopper (H100)
```

---

## Primary Sources

- **FlashAttention-1:** Dao et al. 2022, "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness" — https://arxiv.org/abs/2205.14135
- **FlashAttention-2:** https://arxiv.org/abs/2307.08691
- **FlashAttention-3 (H100):** https://arxiv.org/abs/2407.08608
- **GitHub repo:** https://github.com/Dao-AILab/flash-attention
- **Flash-Decoding (long-context decode optimization):** https://crfm.stanford.edu/2023/10/12/flashdecoding.html
- **Online softmax trick:** Milakov & Gimelshein 2018 — https://arxiv.org/abs/1805.02867
- **vAttention (PagedAttention alternative):** https://arxiv.org/abs/2405.04437

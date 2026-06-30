# Quantized Kernels — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Weight quantization alone doesn't guarantee speedup without kernel support.**

Weight quantization (compressing FP16 weights to INT4/INT8) reduces memory. But unless the CUDA kernel *natively operates on quantized data*, the actual execution path is: dequantize INT4 → FP16, multiply in FP16, which can be *slower* than just running FP16 directly due to dequantization overhead.

True quantized kernels perform matrix multiplication directly in the quantized format (or fuse dequantize + matmul into a single kernel so data never touches HBM at full precision). The speedup only materializes at the kernel level.

---

## How It Works

### The Quantization-Kernel Pipeline

```
NAIVE (slow):
  INT4 weights in VRAM → Read → Dequantize to FP16 in registers →
  FP16 matmul → FP16 output → Write to VRAM
  
  Problem: dequantization is an extra step. Weight reads are smaller (INT4),
  but compute is still FP16. Net: memory savings, marginal speed gain.

FUSED KERNEL (fast):
  INT4 weights in VRAM → Read + Dequantize + Multiply in ONE kernel →
  FP16/FP32 accumulator → Write output
  
  The dequantization happens in registers during the same cycle as
  the multiply. No extra memory traffic. Net: memory savings + speed gain.

TRUE INT8/INT4 COMPUTE (fastest, hardware-dependent):
  INT8 weights × INT8 activations → INT32 accumulator → Scale → Output
  
  On hardware with INT8 tensor cores (A100, H100):
  INT8 matmul is 2× faster than FP16 matmul in raw throughput.
```

### AWQ (Activation-Aware Weight Quantization)

**The insight:** Not all weights are equally important. Some weights (1-3% of them) have disproportionately large activation magnitudes. Quantizing these "salient" weights to INT4 causes significant quality loss. Protecting them preserves quality.

```
AWQ Algorithm:
  1. Run calibration data through the model
  2. For each weight matrix, measure the activation magnitude per channel
  3. Identify channels with high activation magnitude (salient weights)
  4. Apply per-channel scaling: scale salient channels UP before quantization
     so they occupy more of the INT4 range (higher precision for important weights)
  5. Quantize all weights to INT4 (salient weights now have effective higher precision)
  6. At inference: the kernel applies inverse scaling during the multiply

Result: INT4 quantization with near-FP16 quality.
```

**AWQ vs naive INT4:**
```
Naive round-to-nearest INT4: 5-10% quality loss on perplexity
AWQ INT4: <1% quality loss on perplexity

The difference is entirely in how salient weights are treated.
```

### GPTQ (Post-Training Quantization)

**The insight:** Use second-order information (the Hessian) to minimize quantization error layer by layer.

```
GPTQ Algorithm (per layer):
  1. Start with FP16 weight matrix W and calibration data
  2. For each column of W:
     a. Quantize the column to INT4
     b. Compute the quantization error
     c. Distribute the error to remaining (unquantized) columns
        using the inverse Hessian to minimize total output error
  3. Result: INT4 weights where each column's quantization error
     is compensated by adjustments to later columns

Time: minutes to hours per model (one-time cost)
```

**GPTQ vs AWQ:**
| Aspect | AWQ | GPTQ |
|--------|-----|------|
| Quality at INT4 | Slightly better on most benchmarks | Very good |
| Quantization speed | Fast (minutes) | Slower (minutes-hours) |
| Kernel support | Marlin, vLLM native | Marlin, ExLlamaV2, AutoGPTQ |
| Inference speed | Comparable | Comparable |
| Activation quantization | Weights only (W4A16) | Weights only (W4A16) |

### SmoothQuant (W8A8)

**The problem SmoothQuant solves:** Quantizing *activations* is much harder than quantizing weights. Activations have outlier channels with magnitudes 100× larger than the median. INT8 can't represent this dynamic range.

```
SmoothQuant Algorithm:
  1. Observe activation distributions during calibration
  2. Identify outlier channels (channels with high activation magnitude)
  3. Apply a mathematically equivalent transformation:
     Y = (X × diag(s)) × (diag(s)⁻¹ × W)
     
     This MOVES the quantization difficulty from activations to weights:
     - Activations are divided by s (smoothed — outliers reduced)
     - Weights are multiplied by s (absorb the difficulty)
  4. Now BOTH activations AND weights are easy to quantize to INT8
  5. Run W8A8: weights INT8, activations INT8, compute in INT8

Result: 2× memory reduction AND 2× compute speedup (INT8 tensor cores)
```

### Marlin Kernel

**The fastest known INT4 inference kernel for NVIDIA GPUs.**

Marlin (Frantar et al. 2024) is a custom CUDA kernel optimized for 4-bit weight matrix multiplication on A100/H100:
- Achieves near-ideal throughput (close to theoretical INT4 peak)
- Supports both AWQ and GPTQ quantized models
- Used by vLLM as the default INT4 kernel

---

## The Numbers

| Method | Precision | Memory (70B) | Speedup vs FP16 | Quality Loss |
|--------|-----------|-------------|-----------------|--------------|
| FP16 baseline | W16A16 | 140 GB | 1× | 0% |
| AWQ | W4A16 | 35 GB | 1.5-2× | <1% perplexity |
| GPTQ | W4A16 | 35 GB | 1.5-2× | <1% perplexity |
| SmoothQuant | W8A8 | 70 GB | 1.5-2× | <0.5% |
| FP8 (H100) | W8A8 (FP8) | 70 GB | 2× | <0.5% |
| Marlin (INT4) | W4A16 | 35 GB | 3.5-4× (on A100) | Same as AWQ/GPTQ |

**Marlin performance:** On A100, Marlin achieves 3.87× speedup over cuBLAS FP16 for batch=1 Llama-2 70B inference. This is close to the theoretical 4× speedup from 4× smaller weight reads.

---

## Where It Lives in the Stack

**Layer: CUDA kernel + quantization tool.**

Two components:
1. **Quantization tool (offline):** Runs once to compress model weights. Outputs a quantized checkpoint.
   - AWQ: `autoawq` Python library
   - GPTQ: `auto-gptq` Python library
   - SmoothQuant: Integrated into TensorRT-LLM

2. **Inference kernel (runtime):** Custom CUDA kernel that operates on quantized weights during serving.
   - Marlin kernel (vLLM, for AWQ/GPTQ)
   - ExLlamaV2 kernel (for GPTQ, used in llama.cpp ecosystem)
   - CUTLASS INT8 kernels (for SmoothQuant)

```
Offline:  FP16 model → [AWQ/GPTQ quantizer] → INT4 model checkpoint
Online:   INT4 model → [Marlin/ExLlama kernel] → Fast inference
```

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| 4× memory reduction (INT4) | 1-5% quality loss (task dependent) |
| 1.5-4× inference speedup | Quantization is not reversible (one-way) |
| Serve large models on fewer GPUs | Calibration data required (small set, ~128-512 samples) |
| | Not all models quantize equally well (reasoning/math tasks more sensitive) |
| | Kernel compatibility (need specific kernel for each quantization scheme) |

**When quantization hurts:** Math reasoning, code generation, and instruction following are more sensitive to quantization than general text generation. Always benchmark on YOUR specific task before deploying quantized models.

**The memory vs quality curve:**
```
FP16  → 0% loss,   140 GB    (baseline)
INT8  → 0.5% loss,  70 GB    (SmoothQuant / FP8)
INT4  → 1-3% loss,  35 GB    (AWQ / GPTQ)
INT3  → 5-10% loss, 26 GB    (research only, not production-ready)
INT2  → significant, 17 GB   (KIVI for KV cache only, not weights)
```

---

## What It Combines With

**Stacks well with:**
- **Mixed Precision (08):** Quantized kernels are an extension of mixed precision. AWQ is W4A16 (4-bit weights, 16-bit activations). SmoothQuant is W8A8.
- **KV Caching (01):** KV cache can be independently quantized (KIVI, KVQuant) for additional memory savings.
- **FlashAttention (03):** FA operates on the attention computation; quantized kernels handle the linear layers. They operate on different parts of the model — no conflict.
- **PagedAttention (04):** Quantized KV cache blocks use less memory per block, allowing more blocks in the same VRAM.
- **Speculative Decoding (02):** Draft model can be aggressively quantized (INT4) since it only needs to approximate the target.
- **Tensor Parallelism (10):** Quantized weights are smaller → less all-reduce communication per layer.

**Conflicts with:**
- **FP8 (specific to H100):** FP8 and INT4 are competing approaches. On H100, FP8 provides ~2× speedup with minimal quality loss. INT4 provides ~4× memory reduction with more quality loss. Choose based on whether you're memory-bound or compute-bound.

---

## Implementation Today

| Framework | AWQ | GPTQ | SmoothQuant | FP8 | Marlin |
|-----------|-----|------|-------------|-----|--------|
| **vLLM** | ✅ | ✅ | ✅ | ✅ (H100) | ✅ (default INT4) |
| **TGI** | ✅ | ✅ | — | Experimental | — |
| **TensorRT-LLM** | ✅ | ✅ | ✅ | ✅ | — (own kernels) |
| **llama.cpp** | — | — | — | — | — (uses GGUF Q4/Q5/Q8) |
| **SGLang** | ✅ | ✅ | — | ✅ | ✅ |

**Quantizing a model (AWQ):**
```python
from awq import AutoAWQForCausalLM
from transformers import AutoTokenizer

model = AutoAWQForCausalLM.from_pretrained("meta-llama/Llama-3-70B-Instruct")
tokenizer = AutoTokenizer.from_pretrained("meta-llama/Llama-3-70B-Instruct")

quant_config = {"zero_point": True, "q_group_size": 128, "w_bit": 4}
model.quantize(tokenizer, quant_config=quant_config)
model.save_quantized("Llama-3-70B-AWQ")
```

**Serving a quantized model (vLLM):**
```bash
python -m vllm.entrypoints.openai.api_server \
  --model Llama-3-70B-AWQ \
  --quantization awq \
  --dtype half
```

---

## Primary Sources

- **AWQ:** Lin et al. 2023, "AWQ: Activation-aware Weight Quantization for LLM Compression and Acceleration" — https://arxiv.org/abs/2306.00978
- **GPTQ:** Frantar et al. 2022, "GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers" — https://arxiv.org/abs/2210.17323
- **SmoothQuant:** Xiao et al. 2022 — https://arxiv.org/abs/2211.10438
- **Marlin kernel:** Frantar et al. 2024 — https://arxiv.org/abs/2408.11743
- **AutoAWQ repo:** https://github.com/casper-hansen/AutoAWQ
- **AutoGPTQ repo:** https://github.com/AutoGPTQ/AutoGPTQ

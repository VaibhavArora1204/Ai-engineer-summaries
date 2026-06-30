# Mixed Precision Inference — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: Memory consumption and compute throughput at full FP32 precision.**

FP32 (32-bit floating point) uses 4 bytes per parameter. A 70B model at FP32 requires 280 GB — it doesn't fit on even four A100 80GB GPUs. Beyond memory, FP32 operations use wider data paths, limiting the number of operations per clock cycle on modern tensor cores.

Modern GPUs have specialized hardware (tensor cores) that operate 2-8× faster on reduced precision formats (FP16, BF16, FP8). Mixed precision uses the lowest precision that maintains acceptable quality for each operation.

---

## How It Works

### The Precision Hierarchy

```
FP32:  1 sign + 8 exponent + 23 mantissa = 32 bits = 4 bytes
       Range: ±3.4 × 10³⁸, Precision: ~7 decimal digits
       
FP16:  1 sign + 5 exponent + 10 mantissa = 16 bits = 2 bytes
       Range: ±65,504, Precision: ~3 decimal digits
       Problem: small exponent → overflow on large activations
       
BF16:  1 sign + 8 exponent + 7 mantissa = 16 bits = 2 bytes
       Range: ±3.4 × 10³⁸ (same as FP32!), Precision: ~2 decimal digits
       Key: same range as FP32, avoids overflow issues of FP16
       
FP8 (E4M3): 1 sign + 4 exponent + 3 mantissa = 8 bits = 1 byte
       Range: ±448, Precision: ~1 decimal digit
       H100 Hopper only. Used in FlashAttention-3.
       
FP8 (E5M2): 1 sign + 5 exponent + 2 mantissa = 8 bits = 1 byte
       Wider range than E4M3, less precision. Used for gradients.
```

### Mixed Precision Strategy

Not all operations tolerate reduced precision equally:

```
Operation          | Precision | Why
-------------------|-----------|------------------------------------
Weight storage     | FP16/BF16 | 2× memory reduction, safe
Matrix multiply    | FP16/BF16 | Tensor cores optimized for this
Attention scores   | FP32      | Softmax needs precision (exp overflow)
LayerNorm          | FP32      | Mean/variance computation needs range
Residual adds      | FP32      | Accumulation errors compound over layers
Loss computation   | FP32      | Numerical stability
```

**The pattern:** Compute-heavy operations (matmul) run at half precision for speed. Numerically sensitive operations (softmax, normalization, accumulation) run at FP32 for stability. Weights are stored at half precision for memory.

### BF16 vs FP16

```
FP16 problem:
  Large activations (>65,504) → overflow → inf → NaN → crash
  Common in: large models, long sequences, high learning rates (training)
  
BF16 solution:
  Same exponent range as FP32 → no overflow risk
  Less mantissa precision → slightly noisier computation
  But: rounding errors are random and cancel out in aggregate
  
Industry consensus (2024+): BF16 for both training and inference.
FP16 is legacy — still works but BF16 is strictly safer.
```

### FP8 on Hopper (H100)

H100 introduces FP8 tensor cores — the first GPU generation to natively compute in 8-bit floating point.

```
FP8 pipeline:
  1. Weights stored in FP8 (E4M3 format)
  2. Activations quantized to FP8 dynamically (per-tensor or per-channel scaling)
  3. Matrix multiply in FP8 → accumulate in FP32
  4. Output dequantized back to FP16/BF16
  
Scaling factors: critical for FP8 quality.
  - Static scaling: calibrated offline on representative data
  - Dynamic scaling: computed per-batch during inference (more accurate, slight overhead)
```

---

## The Numbers

| Precision | Memory (70B model) | Tensor Core Speed (H100) | Quality Impact |
|-----------|-------------------|-------------------------|----------------|
| FP32 | 280 GB | 1× (baseline) | None |
| FP16 | 140 GB | 2× | Negligible (risk of overflow) |
| BF16 | 140 GB | 2× | Negligible |
| FP8 (H100) | 70 GB | 4× | <0.5% on most benchmarks |
| INT8 | 70 GB | 2-4× | 0.5-1% |
| INT4 | 35 GB | 2-4× | 1-5% (task dependent) |

**Throughput gains on A100 (matmul performance):**
```
FP32: ~19.5 TFLOPS
FP16/BF16 Tensor Cores: ~312 TFLOPS (16× over FP32)

FP32 → BF16 gives you: 2× memory + 16× peak matmul throughput
In practice: 2-4× end-to-end speedup (memory bandwidth is often the bottleneck, not compute)
```

**On H100:**
```
FP16/BF16: ~990 TFLOPS
FP8: ~1,979 TFLOPS (2× over FP16)
```

---

## Where It Lives in the Stack

**Layer: Model loading + CUDA kernels.**

Mixed precision is applied at two levels:
1. **Model loading:** Load weights in FP16/BF16 instead of FP32. This is a one-line change in most frameworks.
2. **Kernel level:** CUDA kernels use tensor core instructions for reduced-precision matmul. The framework selects the appropriate kernel automatically.

```python
# PyTorch — load model in BF16
model = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Llama-3-70B-Instruct",
    torch_dtype=torch.bfloat16  # 2× memory reduction
)

# FP8 (H100 with TensorRT-LLM)
# Quantized during TRT-LLM build step, not at load time
```

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| 2× memory reduction (FP32→BF16) | Slight rounding noise in computation |
| 2-4× compute speedup from tensor cores | FP8 requires Hopper (H100) or newer |
| FP8: 4× speedup + 4× memory on H100 | FP8 requires careful scaling factor calibration |
| | FP16 has overflow risk (use BF16 instead) |

**Accuracy:**
- FP32 → BF16: Typically <0.1% quality difference. Safe for all production use.
- FP32 → FP8: ~0.3-0.5% quality difference. Requires validation on your specific task.
- Quality impact is task-dependent: math/reasoning tasks are more sensitive to precision than text generation.

---

## What It Combines With

**Stacks well with:**
- **KV Caching (01):** KV cache stored in BF16 uses half the memory vs FP32. FP8 KV cache on H100 uses quarter memory.
- **FlashAttention (03):** FA2 supports FP16/BF16. FA3 adds native FP8 support on H100.
- **Quantized Kernels (09):** Mixed precision is the foundation — INT4/INT8 quantization goes further in the same direction.
- **Batch Inference (05):** Half-precision doubles the batch size that fits in VRAM.
- **Tensor Parallelism (10):** All-reduce communication volume halved with FP16 vs FP32.
- **Everything else:** Mixed precision is a baseline optimization. Every other technique in this list assumes BF16 or FP16 weights. FP32 inference is not used in any production system.

**Conflicts with:**
- Nothing meaningful. Mixed precision (BF16 minimum) is universal. The only consideration is ensuring numerically sensitive operations (softmax, layernorm) stay at FP32 — all modern frameworks handle this automatically.

---

## Implementation Today

| Framework | Default Precision | FP8 Support |
|-----------|-------------------|-------------|
| **vLLM** | BF16/FP16 auto | FP8 on H100 (`--dtype fp8`) |
| **TGI** | BF16 default | FP8 experimental |
| **TensorRT-LLM** | FP16/BF16, INT8, FP8 | Full FP8 support (H100) |
| **llama.cpp** | Depends on quantization format | FP16 compute with quantized weights |
| **HuggingFace** | `torch_dtype=torch.bfloat16` | Via `bitsandbytes` or TRT-LLM |

**In practice, you do not "enable" mixed precision — you'd have to go out of your way to use FP32.** Every modern framework defaults to FP16 or BF16. The question is whether to go further to FP8 or INT8/INT4 quantization.

---

## Primary Sources

- **NVIDIA Mixed Precision Training Guide:** https://docs.nvidia.com/deeplearning/performance/mixed-precision-training/
- **H100 FP8 whitepaper:** https://resources.nvidia.com/en-us-tensor-core
- **BF16 format:** https://en.wikipedia.org/wiki/Bfloat16_floating-point_format
- **FlashAttention-3 (FP8):** https://arxiv.org/abs/2407.08608
- **FP8 Formats for Deep Learning (NVIDIA/Intel/ARM):** https://arxiv.org/abs/2209.05433

# Graph Optimization (ONNX, TensorRT) — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: PyTorch's eager execution mode is inefficient for inference.**

PyTorch executes operations one at a time ("eager mode"). Each operation: read data from HBM → compute → write result to HBM → launch next kernel. For a Transformer layer with ~20 individual operations, that's ~20 round trips to HBM. Many of these can be fused into fewer kernels.

Graph optimization captures the model's full computational graph, analyzes it, and applies optimizations that are impossible in eager mode.

---

## How It Works

### Three Core Optimizations

**1. Operator Fusion:**
```
Before fusion (5 kernel launches, 5 HBM round trips):
  x = input
  x = x - mean(x)           # kernel 1: mean
  x = x / sqrt(var(x) + ε)  # kernel 2: variance, kernel 3: sqrt+divide
  x = x * γ                 # kernel 4: scale
  x = x + β                 # kernel 5: shift

After fusion (1 kernel launch, 1 HBM round trip):
  x = fused_layer_norm(input, γ, β)
  
5 HBM reads/writes → 1 HBM read/write. Same math.
```

**2. Constant Folding:**
```
Before: y = x * 2.0 * 3.14159
        (runtime multiplies by 2.0, then by 3.14159)
        
After:  y = x * 6.28318
        (compiler precomputes 2.0 × 3.14159 at build time)
```

**3. Kernel Selection:**
```
For matmul [M=1, K=4096, N=4096]:
  Option A: cuBLAS standard GEMM
  Option B: cuBLAS GEMM with CUTLASS backend
  Option C: Custom split-K GEMM for small M
  
TensorRT profiles ALL options on the target GPU and picks the fastest.
Different GPU models, batch sizes, and dtypes → different optimal kernels.
```

### ONNX (Open Neural Network Exchange)

ONNX is a hardware-agnostic intermediate representation:

```
PyTorch Model → torch.onnx.export() → ONNX graph (.onnx file)
                                           ↓
                              ┌────────────┴────────────┐
                              ↓                         ↓
                     ONNX Runtime (CPU/GPU)     TensorRT (NVIDIA GPU)
                              ↓                         ↓
                     Inference on any HW        Maximum NVIDIA perf
```

**ONNX graph optimizations:** graph simplification, constant folding, dead code elimination, shape inference. Hardware-agnostic optimizations that run before any backend-specific compilation.

### TensorRT (NVIDIA-Specific)

TensorRT takes an ONNX graph (or TorchScript) and compiles it for a specific NVIDIA GPU:

```
Input: ONNX graph + target GPU (e.g., A100)
Process:
  1. Layer fusion: merge compatible layers (Conv+BN+ReLU → single kernel)
  2. Precision calibration: profile FP32 → INT8 mapping with calibration data
  3. Kernel auto-tuning: run every candidate kernel, time it, pick fastest
  4. Memory planning: optimize tensor lifetimes, reuse memory
Output: TensorRT engine (.plan file) — maximally optimized for THIS GPU

Build time: minutes to HOURS for large models
Inference time: fastest available on NVIDIA hardware
```

### TensorRT-LLM

NVIDIA's LLM-specific wrapper around TensorRT:

```
TensorRT-LLM provides:
  - Pre-optimized attention kernels (fused multi-head attention)
  - KV cache management (block-based, like PagedAttention)
  - Continuous batching scheduler
  - Tensor/Pipeline parallelism
  - INT4/INT8/FP8 quantization
  - Speculative decoding
  
Unlike generic TensorRT, TRT-LLM understands LLM-specific patterns
and has custom CUDA kernels for them.
```

### torch.compile (PyTorch 2.0+)

PyTorch's built-in graph compiler. Lighter-weight alternative to TensorRT:

```python
model = AutoModelForCausalLM.from_pretrained(...)
model = torch.compile(model, mode="reduce-overhead")
# First call: traces graph + compiles (slow)
# Subsequent calls: uses compiled graph (fast)
```

**Speedup:** 1.3-2× over eager mode for most models. Less than TensorRT but zero build step and no ONNX export needed.

---

## The Numbers

| Optimization | Speedup vs Eager PyTorch | Build Time | Portability |
|-------------|--------------------------|------------|-------------|
| torch.compile | 1.3-2× | Seconds (first call) | Any PyTorch model |
| ONNX Runtime | 1.5-2.5× | Minutes | Cross-hardware |
| TensorRT (FP16) | 2-4× | Minutes-hours | NVIDIA GPUs only |
| TensorRT (INT8) | 3-6× | Hours (calibration) | NVIDIA GPUs only |
| TensorRT-LLM | 3-5× | Minutes-hours | NVIDIA GPUs, LLMs only |

---

## Where It Lives in the Stack

**Layer: Compiler / model optimization — between model training and serving.**

```
Training (PyTorch) → Export (ONNX/TorchScript) → Compile (TensorRT) → Serve (TRT runtime)
                                                       ↑
                                              Offline step (build time)
                                              
Alternative with torch.compile:
Training (PyTorch) → torch.compile() → Serve (PyTorch)
                          ↑
                    JIT at first inference call
```

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| 2-5× inference speedup | Build/compile time (minutes to hours) |
| Automatic kernel selection for your GPU | TensorRT: NVIDIA lock-in |
| Op fusion eliminates HBM round trips | ONNX export may not support all PyTorch ops |
| | TensorRT engine is GPU-specific (rebuild for different GPU) |
| | Debugging compiled graphs is much harder than eager mode |
| | Dynamic shapes require re-compilation or shape profiling |

**The dynamic shape problem:** LLMs have variable sequence lengths. TensorRT traditionally required fixed shapes. TensorRT-LLM solves this with dynamic shape profiles (min, opt, max sequence length specified at build time). But performance is optimized for the "opt" shape — very short or very long sequences may be suboptimal.

---

## What It Combines With

**Stacks well with:**
- **Quantized Kernels (09):** TensorRT's INT8/FP8 calibration + fused quantized kernels = maximum performance.
- **FlashAttention (03):** TensorRT-LLM has its own fused attention implementation (similar principles to FA).
- **Tensor Parallelism (10):** TRT-LLM supports TP natively.
- **Continuous Batching (17):** TRT-LLM includes a continuous batching scheduler.
- **Mixed Precision (08):** TensorRT's precision calibration is the most sophisticated mixed-precision tool available.

**Conflicts with:**
- **torch.compile:** Redundant with TensorRT. Use one or the other. torch.compile for flexibility, TensorRT for maximum performance.
- **vLLM:** vLLM has its own execution engine. Using vLLM with TensorRT-LLM backend is possible but adds complexity.

---

## Implementation Today

| Tool | Best For | Effort |
|------|----------|--------|
| **torch.compile** | Quick wins, prototyping | 1 line of code |
| **ONNX Runtime** | Cross-platform deployment | ONNX export + config |
| **TensorRT** | Non-LLM NVIDIA inference | Export + build + calibrate |
| **TensorRT-LLM** | Production LLM serving on NVIDIA | Model config + build |
| **SGLang** | Uses torch.compile internally | Automatic |

**torch.compile (simplest):**
```python
import torch
model = torch.compile(model, mode="reduce-overhead")
```

**TensorRT-LLM:**
```bash
# Build optimized engine
python build.py --model_dir ./Llama-3-70B \
  --dtype float16 --tp_size 4 \
  --use_fused_mlp --use_flash_attention

# Serve
python run.py --engine_dir ./engine --max_batch_size 64
```

---

## Primary Sources

- **TensorRT-LLM:** https://github.com/NVIDIA/TensorRT-LLM
- **ONNX:** https://onnx.ai/
- **ONNX Runtime:** https://onnxruntime.ai/
- **torch.compile:** https://pytorch.org/docs/stable/torch.compiler.html
- **TensorRT:** https://developer.nvidia.com/tensorrt
- **TorchInductor (torch.compile backend):** https://dev-discuss.pytorch.org/t/torchinductor-a-pytorch-native-compiler/

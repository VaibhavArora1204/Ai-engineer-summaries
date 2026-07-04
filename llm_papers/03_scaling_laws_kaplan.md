# Paper 3: Scaling Laws for Neural Language Models (Kaplan et al., 2020)

## What Existed Before and What Broke

Before this paper, training a large language model was an expensive guessing game. You had a compute budget — say, $2 million worth of GPU-hours. How do you spend it? Do you train a 10B parameter model for 3 months? Or a 1B parameter model for a year? Do you invest in more data or more parameters? Nobody had a principled answer.

The field operated on two unreliable heuristics:

**1. "Bigger is better."** More parameters meant better performance, so people trained the biggest model their hardware could support. But a 10B model trained on too little data might underperform a 3B model trained on more data. Nobody had the math to know when this crossover occurred.

**2. "Train until the loss stops going down."** Practitioners trained until improvement plateaued, which was an inefficient way to discover that the model was either underfitting (not enough parameters) or undertrained (not enough data). Millions of dollars in compute were wasted on training runs that hit a wall the math could have predicted from the beginning.

Kaplan et al. showed that model performance follows predictable power laws across parameters, data, and compute — and that these laws hold over seven orders of magnitude. For the first time, you could predict how a model would perform at scale X before spending the money to train it. You could calculate, before training begins, what the optimal allocation of your compute budget should be between model size and training data.

This paper turned model training from art into engineering — with one critical mistake that Chinchilla (Paper 5) would later expose.

---

## The Core Mechanism

### Power Laws — The Empirical Discovery

Kaplan's team trained models ranging from 768 parameters to 1.5 billion parameters, on datasets from 22 million to 23 billion tokens, and discovered that test loss (a proxy for model quality) follows smooth power-law curves:

```
L(N) ∝ N^(-0.076)    Model performance as a function of parameters (N)
L(D) ∝ D^(-0.095)    Model performance as a function of training data (D)
L(C) ∝ C^(-0.050)    Model performance as a function of compute (C)
```

What "power law" means concretely: performance improves as a smooth, predictable function of scale, with diminishing returns at every step. There are no sudden jumps, no discontinuities, no phase transitions in the loss curve. Doubling parameters always gives you the same fractional improvement in loss, regardless of whether you're going from 1B to 2B or from 100B to 200B.

### What the Exponents Mean for Systems Decisions

The exponents tell you how much each factor matters per unit of investment:

**Parameters (N^-0.076):** Each 10x increase in parameters reduces loss by ~17%. The exponent is relatively flat — you get diminishing returns from model size alone. But the returns are predictable: a 70B model is predictably better than a 7B model, which is predictably better than a 700M model, and you can estimate by how much before training any of them.

**Data (D^-0.095):** Each 10x increase in training data reduces loss by ~20%. Data has a slightly higher exponent than parameters, meaning data is slightly more efficient per unit of investment. Kaplan noted this but drew the wrong conclusion about optimal allocation (more on this below).

**Compute (C^-0.050):** Total compute (FLOPs) combines the effects of parameters and data. The exponent tells you: each 10x increase in training compute reduces loss by ~11%. This is the most directly actionable law — given a fixed compute budget, it predicts the achievable loss.

### Kaplan's Compute-Optimal Allocation — And Why It Was Wrong

Given a fixed compute budget C, Kaplan derived how to split it between model size (N) and training tokens (D):

```
Kaplan's allocation:
  N* ∝ C^0.73    (spend ~73% of compute scaling on model size)
  D* ∝ C^0.27    (spend ~27% of compute scaling on data)
```

This said: **scale model size aggressively, use relatively little data.** The reasoning was that model size had more "headroom" for improvement at the scales Kaplan studied.

This led directly to GPT-3's training configuration: 175B parameters, but only 300B training tokens. By the Chinchilla rule (Paper 5), 175B parameters should have been trained on ~3.5 trillion tokens (20× the parameter count). GPT-3 was trained on less than 1/10th the data it needed for compute-optimal performance.

**The mistake:** Kaplan's experiments didn't train to convergence — they trained for a fixed number of steps. This systematically underestimated the benefit of more data, because the returns to data only fully appear when you train long enough for the model to absorb it. When Chinchilla (Paper 5) re-ran the analysis with training to convergence, the optimal allocation was roughly 50/50 between parameters and data tokens (20 tokens per parameter), not 73/27.

This mistake is worth understanding in detail because it demonstrates how experimental methodology choices — seemingly minor — can propagate into billion-dollar resource allocation decisions.

---

## What This Creates for Your System

### Model Selection Becomes Quantitative

Before scaling laws, picking a model was vibes: "GPT-4 is the best, use it for everything." After scaling laws, model selection can be a quantitative decision:

```
The practical framework:

1. Task complexity determines a minimum capability threshold.
   - Simple classification: 1B-7B parameter models are sufficient
   - Multi-step reasoning: 30B-70B typically required
   - Complex code generation: 70B+ or instruction-tuned specialist
   
2. Power-law degradation is PREDICTABLE, not random.
   - A 7B model doesn't randomly fail. It consistently fails on tasks
     that require capability beyond its scale threshold.
   - You can test where the threshold is for YOUR specific task,
     and know that the boundary is stable — not a flaky test.

3. Cost scales linearly with parameters. Quality scales logarithmically.
   - Going from 7B to 70B (10x cost) improves quality by ~17% (one power-law step)
   - Going from 70B to 700B (10x cost again) improves by another ~17%
   - This tells you exactly when the marginal cost of a larger model
     stops being worth the marginal quality improvement for your use case.
```

### Model Routing Has Mathematical Foundation

When you route requests to different models based on complexity (simple queries → small model, complex queries → large model), scaling laws provide the mathematical justification:

```
Routing decision:

Simple question ("What is the capital of France?"):
  7B model: correct with high probability
  70B model: correct with slightly higher probability
  Cost difference: 10x
  Quality difference: negligible
  → Route to 7B. No question.

Complex reasoning ("Analyze these three contracts for contradictory clauses"):
  7B model: fails consistently (below capability threshold)
  70B model: succeeds reliably
  Cost difference: 10x
  Quality difference: task-critical
  → Route to 70B. The cost is justified.
```

This routing strategy — which every serious production LLM system implements — is ultimately justified by the smooth, predictable power-law relationship between model size and capability. The prediction "this task is below the 7B threshold but above the 70B threshold" is reliable precisely because the scaling relationship is smooth, not noisy.

### Training Cost Estimation Becomes Predictable

If you're considering training or fine-tuning a model, scaling laws let you estimate the outcome before spending the money:

```
You want a model that achieves loss L* on your domain.

Scaling law gives you:
  L* → required N (parameters) → required D (training data)
  N × D → required C (compute FLOPs)
  C → GPU-hours → dollar cost

Example (rough, using Kaplan-era scaling):
  Current loss on your task: L = 2.5 (with a 7B model)
  Target loss: L* = 2.0 (need ~25% improvement)
  
  Scaling law: 25% loss improvement requires ~10x compute
  Current compute: 7B × 300B tokens = X FLOPs
  Required: ~10X FLOPs
  
  Options:
    a) 70B parameters, same data → maybe 3x improvement (not enough)
    b) 7B parameters, 10x data → maybe 2x improvement (not enough)
    c) 20B parameters, 5x data → ~10x compute (right ballpark)
```

This is back-of-envelope — the specific numbers depend on your domain and the precise scaling exponents — but the framework is actionable. Before scaling laws, this calculation was impossible. You just trained and hoped.

---

## What Production Systems Changed After This

**Training became predictable engineering.** Model providers (OpenAI, Google, Anthropic) used scaling laws to plan training runs worth tens of millions of dollars. Instead of "train and see," they could predict the expected loss at target scale, allocate compute accordingly, and have reasonable confidence in the outcome before the first GPU started. This is why the jump from GPT-2 (1.5B) to GPT-3 (175B) happened relatively quickly — scaling laws told OpenAI that the investment would yield specific, predictable capability improvements.

**Model cards started including training details.** Because scaling laws showed that both parameters AND training tokens matter, model releases began reporting training token counts alongside parameter counts. Before Kaplan, a model card would say "13B parameters." After Kaplan (and especially after Chinchilla, Paper 5), a model card says "13B parameters, trained on 2T tokens" — because both numbers are needed to evaluate whether the model is compute-optimal.

**The "emergence" debate.** Scaling laws predict smooth improvement. But some capabilities appear to "emerge" suddenly at certain scales (e.g., few-shot arithmetic works at 175B but not at 13B). The debate: are these genuine phase transitions, or do they appear sudden only because we measure with coarse benchmarks? Scaling laws predict smooth loss improvement, but individual task accuracy can appear step-like because a task either works or doesn't — there's no "halfway" on a specific benchmark question. This distinction matters: smooth scaling means predictable ROI on larger models, while true emergence would mean unpredictable capability jumps.

---

## How This Connects to the Other 17 Papers

**Depends on Paper 1 (Attention) and Paper 2 (GPT-2):** Scaling laws were discovered on Transformer language models. The architecture from Paper 1 and the pretraining paradigm from Paper 2 are what's being scaled. The laws might not apply to fundamentally different architectures (and this is an open question for state-space models like Mamba).

**Directly contradicted by Paper 5 (Chinchilla):** Kaplan said scale model size faster than data (73/27 split). Chinchilla said the split should be roughly 50/50 (20 tokens per parameter). Chinchilla's correction is now the accepted wisdom, but it wouldn't have been possible without Kaplan establishing the scaling law framework in the first place.

**Explains the GPT-3 configuration (Paper 4):** GPT-3's 175B parameters on 300B tokens is a direct application of Kaplan's (incorrect) recommendation. GPT-3 was massively undertrained by Chinchilla standards. This explains why Llama 2 at 70B (trained on 2T tokens, Chinchilla-optimal) competes with GPT-3 at 175B — a smaller model with more data, trained correctly, beats a larger model trained incorrectly.

**Provides the mathematical foundation for Paper 7 (LoRA) decisions:** When deciding between fine-tuning a smaller model or prompting a larger one, scaling laws tell you the quality ceiling of each option. A fine-tuned 7B model can outperform a prompted 70B model on narrow tasks — because fine-tuning injects task-specific patterns, effectively changing the model's loss curve for that specific task.

---

## The Honest Take

**1. What most engineers miss when they skip this paper and just use the API:**

Model selection is not "use the biggest model you can afford." It's a quantitative optimization problem with a smooth tradeoff curve. A 7B model is not "10x worse" than a 70B model — it's predictably worse by a specific, measurable amount that depends on the task complexity. Most engineers either default to the biggest model (burning 10x cost for marginal improvement on simple tasks) or default to the cheapest model (failing on complex tasks that need more capability). The scaling laws give you the tools to place your specific tasks on the curve and make informed routing decisions. Without this framework, model selection is vibes. With it, model selection is engineering.

**2. The one non-obvious systems implication that blog posts never explain:**

The scaling exponents predict that model quality improves *logarithmically* with cost. Going from 7B to 70B (10x cost) gives ~17% quality improvement. Going from 70B to 700B (another 10x cost) gives another ~17%. This means the ROI of larger models is always declining. For most production use cases, there is a clear "good enough" point where the next 10x cost increase provides a quality improvement that users cannot distinguish. Finding that point for your specific use case — rather than defaulting to the frontier model — is one of the highest-leverage cost optimization decisions in production LLM systems. Scaling laws tell you that this point exists, that it's findable by experiment, and that the curve is smooth enough to interpolate between data points you've measured.

**3. Essential, useful context, or interesting history?**

**Useful context, not essential.** Here's the honest ranking: the specific exponents and formulas from Kaplan are superseded by Chinchilla (Paper 5), and the compute-optimal allocation was wrong. What's essential from this paper is the *framework* — the insight that scaling is predictable, that model size and training data have quantifiable effects, and that you can reason about model capability mathematically rather than experimentally for every decision. But the specific numbers you should use come from Chinchilla, not Kaplan.

If you only read one scaling paper, read Chinchilla (Paper 5). But understanding Kaplan's contribution — that smooth power laws exist and can be used for engineering decisions — provides the conceptual foundation that makes Chinchilla's correction meaningful. Without Kaplan's framework, Chinchilla's "20 tokens per parameter" is just a rule of thumb. With Kaplan's framework, you understand *why* that ratio matters, *what happens* when you deviate from it, and *how* to reason about model quality as a function of training configuration. That reasoning ability is what makes this paper useful context — not the specific numbers.

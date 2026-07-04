# Paper 9: Chain-of-Thought Prompting Elicits Reasoning in Large Language Models (Wei et al., 2022)

## What Existed Before and What Broke

Before Chain-of-Thought, LLMs answered questions in a single step: question in, answer out. The model's entire "reasoning" happened implicitly within a single forward pass through the network. For simple factual recall ("What is the capital of France?"), this worked fine. For multi-step reasoning, it failed consistently.

The specific failure:

```
Standard prompting:
  Q: Roger has 5 tennis balls. He buys 2 cans of 3. How many does he have?
  A: 11 ← WRONG (correct answer: 11... actually correct here, but on harder problems:)

  Q: A cafeteria had 23 apples. They used 20 for lunch and bought 6 more. How many?
  A: 27 ← WRONG (correct: 9)
```

The model has to compute intermediate results (23 - 20 = 3, then 3 + 6 = 9) entirely within the hidden activations of a single forward pass. No scratch paper. No intermediate storage. The model must hold partial computations implicitly in its ~12,000-dimensional activation vectors across ~96 layers. For problems requiring 3+ reasoning steps, this implicit computation fails because the model's forward pass doesn't have enough "depth" to chain the steps together without explicit intermediate representation.

The fundamental constraint: **a decoder-only Transformer produces each token in one forward pass.** That forward pass is a fixed computation graph with a fixed number of layers. Complex reasoning requires variable-depth computation — some problems need 3 steps, some need 10. A fixed-depth forward pass cannot dynamically allocate more computation to harder problems.

---

## The Core Mechanism

### The Insight: Use the Context Window as Scratch Paper

Chain-of-Thought (CoT) solves the depth problem by externalizing intermediate reasoning into generated tokens:

```
Standard prompting:
  Q: Roger has 5 tennis balls. He buys 2 cans of 3. How many?
  A: 11

Chain-of-Thought prompting:
  Q: Roger has 5 tennis balls. He buys 2 cans of 3. How many?
  A: Roger started with 5 balls. 2 cans of 3 tennis balls each is 
     2 × 3 = 6 tennis balls. 5 + 6 = 11. The answer is 11.
```

The model generates intermediate reasoning tokens BEFORE the final answer token. Because of autoregressive generation (Paper 2), each subsequent token attends to all previous tokens via the attention mechanism (Paper 1). The intermediate reasoning tokens — "2 × 3 = 6" and "5 + 6 = 11" — become part of the context for the final answer. The model effectively uses its own output as scratch paper.

**Why this works mechanically:**

```
Without CoT (single forward pass):
  Input: [question tokens]
  Forward pass: 96 layers of computation → single answer token
  Total computation: 1 × forward_pass_depth
  
With CoT (multiple forward passes):
  Input: [question tokens]
  Forward pass 1: → generates "Roger started with 5 balls."
  Forward pass 2: → generates "2 cans of 3 is 2 × 3 = 6."
  Forward pass 3: → generates "5 + 6 = 11."
  Forward pass 4: → generates "The answer is 11."
  
  Total computation: 4 × forward_pass_depth
  
  Each intermediate token becomes input context for the next.
  The model gets 4x the computational depth for the same problem.
  And crucially: intermediate results are STORED in the context
  (as generated tokens), not held implicitly in activations.
```

### Few-Shot CoT vs Zero-Shot CoT

**Few-shot CoT:** Provide examples in the prompt that demonstrate step-by-step reasoning:

```
Q: There are 15 trees originally. Tree planters plant 21 more. How many?
A: There are originally 15 trees. Then 21 more were planted. 
   15 + 21 = 36. The answer is 36.

Q: If there are 3 cars and each has 4 wheels, how many wheels total?
A: Each car has 4 wheels. 3 cars × 4 wheels = 12. The answer is 12.

Q: [Your actual question]
A:
```

**Zero-shot CoT:** Simply append "Let's think step by step" to the prompt:

```
Q: [Your question]
A: Let's think step by step.
```

Wei et al. (2022) demonstrated few-shot CoT. Kojima et al. (2022) showed that zero-shot CoT ("Let's think step by step") produces similar improvements with no examples needed. The phrase activates step-by-step reasoning patterns learned during pretraining — the model has seen enough step-by-step explanations in training data to generalize the pattern.

### Where CoT Helps — And Where It Doesn't

**Helps (significant accuracy improvement):**
- Arithmetic and math word problems (GSM8K: 17.9% → 58.1% with CoT on PaLM 540B)
- Multi-step logical reasoning
- Commonsense reasoning requiring inference chains
- Code debugging (trace through execution steps)
- Complex question answering requiring evidence synthesis

**Does NOT help (negligible or negative impact):**
- Simple factual recall ("What year was X born?")
- Classification and sentiment analysis
- Single-step lookups
- Tasks where the answer is pattern-matched, not reasoned

**Scale dependency:** CoT originally required ~100B+ parameter models. At smaller scales, the model generates plausible-looking but incorrect reasoning chains that lead to wrong answers — worse than no CoT at all. With instruction-tuned models (Paper 6), CoT now works at smaller scales (13B+), but the quality of reasoning chains still scales with model size.

### Self-Consistency: The Accuracy Multiplier

Wang et al. (2022) introduced self-consistency: sample multiple CoT reasoning chains and take the majority vote on the final answer:

```
Standard CoT (1 sample):
  Q: Complex math problem
  Chain 1: [reasoning] → Answer: 42
  Final: 42

Self-consistency (5 samples):
  Q: Complex math problem
  Chain 1: [reasoning path A] → Answer: 42
  Chain 2: [reasoning path B] → Answer: 42
  Chain 3: [reasoning path C] → Answer: 37  ← different reasoning, different answer
  Chain 4: [reasoning path D] → Answer: 42
  Chain 5: [reasoning path E] → Answer: 42
  
  Majority vote: 42 (4 out of 5)
  Confidence: 80%
  
  Accuracy improvement: meaningful on hard tasks (GSM8K: 58% → 74% with 40 samples)
  Cost: 5-40x token cost (5-40 separate generations)
```

Self-consistency trades tokens for accuracy. It's one of the few techniques where spending more money on a single question reliably improves accuracy — not just generating more text, but generating multiple independent reasoning paths and voting.

---

## What This Creates for Your System

### Reasoning Tokens Cost Money and Time

CoT generates intermediate reasoning tokens. These tokens are not free:

```
Without CoT:
  Input:  200 tokens (question)
  Output: 20 tokens (answer)
  Total:  220 tokens
  
With CoT:
  Input:  200 tokens (question)
  Output: 200 tokens (reasoning) + 20 tokens (answer) = 220 tokens
  Total:  420 tokens
  
  Cost: ~2x (output tokens are 2-4x more expensive than input)
  Latency: ~10x longer (200 output tokens × sequential generation vs 20)
```

For reasoning models (o1, Claude Extended Thinking), the thinking tokens are even more expensive. o1-preview generates thousands of thinking tokens on hard problems:

```
Simple question with o1:
  Thinking tokens: 50-200 (fast, cheap)
  Output tokens: 50
  
Complex math with o1:
  Thinking tokens: 5,000-50,000 (slow, expensive)
  Output tokens: 200
  
  A single complex query can cost $0.50+ in thinking tokens alone.
```

### The Routing Decision — CoT Is Not Always Worth It

The highest-leverage production decision from this paper: **route by task complexity.**

```
Task complexity classification for CoT routing:

Tier 1 — Don't use CoT:
  Classification, entity extraction, simple lookups, sentiment
  CoT adds cost and latency with no quality improvement
  Route to: small model, direct answer, no reasoning
  
Tier 2 — Optional CoT (measure first):
  Summarization, standard Q&A, data extraction
  CoT may help on complex instances, measure accuracy delta
  Route to: medium model, CoT only if measured improvement > threshold
  
Tier 3 — Always use CoT:
  Math, multi-step logic, legal analysis, financial calculation,
  code generation, complex debugging
  CoT meaningfully improves accuracy
  Route to: large model with CoT, accept the cost
  
Tier 4 — CoT + Self-Consistency:
  High-stakes decisions, medical reasoning, safety-critical analysis
  Accuracy improvement from majority voting justifies 5-40x cost
  Route to: large model, multiple samples, majority vote
```

Most teams either always use CoT ("it makes everything better") or never use it ("we optimize for speed"). Neither is correct. The per-task routing decision — based on measured accuracy improvement — is where the cost optimization lies.

### Structured Output After CoT

A common production pattern: generate reasoning in a scratchpad, then extract the structured answer:

```
Prompt:
  <thinking>
  [Model generates reasoning here — not shown to user]
  </thinking>
  <answer>
  [Structured answer in JSON/specific format]
  </answer>

Post-processing:
  Parse <answer> tags → extract structured output
  Discard <thinking> tags (or log for debugging)
  
Why this matters:
  CoT reasoning is free-form text — hard to parse programmatically.
  Structured output (JSON, specific format) requires precise formatting.
  Generating both in sequence lets the model reason freely, then
  commit to a structured format informed by its reasoning.
  
  If you ask for structured output without reasoning first,
  the model must simultaneously reason AND format — and formatting
  constraints can interfere with reasoning quality.
```

This pattern (think, then format) is used in every reasoning model (o1's thinking tokens, Claude's Extended Thinking). The thinking phase is unconstrained reasoning. The output phase is structured and parseable.

---

## What Production Systems Changed After This

**Reasoning models are trained CoT.** OpenAI's o1, o3, and Claude's Extended Thinking are not "smarter models" — they are models trained to generate CoT reasoning tokens before answering, with the reasoning process optimized via reinforcement learning. The fundamental mechanism is the same as prompting "let's think step by step," but trained in and refined with RL instead of prompted at inference time.

**The thinking/output split became an API feature.** Anthropic and OpenAI now expose thinking tokens as a separate billing category and a separate API field. This is a direct productization of the CoT mechanism — the "thinking" phase is the CoT reasoning, and it's separate from the final "output."

**Cost-quality tradeoff became explicit.** Before CoT, the cost of a query was roughly proportional to the output length. After CoT (and especially after reasoning models), the cost includes variable-length thinking tokens. A simple question might cost 50 thinking tokens; a hard question might cost 50,000. This variable cost per query fundamentally changes how you budget for AI workloads — you can't assume a fixed cost per query anymore.

---

## How This Connects to the Other 17 Papers

**Exploits Paper 1 (Attention) and Paper 2 (GPT-2) directly:** CoT works because (1) the attention mechanism allows later tokens to attend to earlier generated tokens (Paper 1), and (2) autoregressive generation means each new token is conditioned on all prior tokens, including intermediate reasoning (Paper 2). Without these two properties, generating reasoning steps wouldn't help — the model couldn't use them.

**Requires Paper 4 (GPT-3) scale:** In-context learning (Paper 4) is what allows few-shot CoT examples to work — the model generalizes the demonstrated reasoning pattern. At GPT-2 scale, few-shot examples don't reliably transfer. At GPT-3+ scale, they do.

**Interacts with Paper 6 (InstructGPT):** CoT works much better on instruction-tuned models than raw pretrained models. RLHF (Paper 6) trains the model to follow instructions like "think step by step" reliably. Without instruction tuning, the model might generate step-by-step reasoning or might not — it's unpredictable.

**Creates the demand for Paper 13 (Speculative Decoding):** CoT generates many more output tokens (reasoning + answer vs just answer). More output tokens = more sequential forward passes = more latency. Speculative decoding (Paper 13) directly addresses this by accelerating token generation. The longer outputs from CoT make speculative decoding's speedup more valuable.

**Creates the reasoning model paradigm (o1, Claude Thinking):** The leap from "prompt CoT" to "train CoT" is the leap from Paper 9 to reasoning models. o1 is CoT with the reasoning chains optimized via reinforcement learning, generating tokens in a trained thinking phase that the model has learned to use effectively.

---

## The Honest Take

**1. What most engineers miss when they skip this paper and just use the API:**

Most engineers use CoT on every request or no request. The actual production optimization is per-task routing: measure the accuracy improvement of CoT on each task type in your system, and only apply CoT where the measured improvement justifies the 2-10x cost increase. On classification tasks, CoT often adds cost with zero accuracy improvement. On multi-step reasoning, CoT can be the difference between 40% and 80% accuracy. Without measuring, you're either wasting money (CoT everywhere) or leaving quality on the table (CoT nowhere).

The measurement is straightforward: run your evaluation set with and without CoT, compare accuracy, compare cost. The result is a routing table: "task type A → no CoT, task type B → CoT, task type C → CoT + self-consistency." This routing table is one of the highest-ROI artifacts in your system.

**2. The one non-obvious systems implication that blog posts never explain:**

CoT reasoning chains can be factually wrong in their intermediate steps and still produce correct final answers. The model isn't "actually reasoning" in a philosophical sense — it's generating tokens that shift the probability distribution of subsequent tokens toward better answers. A reasoning chain that says "2 + 2 = 5, therefore 5 + 3 = 8" is wrong in the intermediate step but might still arrive at a correct final answer because the generated tokens ("therefore... = 8") were influenced by patterns in training data that associate the question format with the correct answer.

This has a critical systems implication: **you cannot use CoT reasoning chains as explanations.** The reasoning chain is not the model's "actual reasoning" — it's a generated text that correlates with better answers. If you show users the reasoning chain as "here's how the AI arrived at its answer," you're showing them a plausible narrative that may not reflect the actual computational process that produced the answer. For compliance-sensitive domains (medical, legal, financial), this distinction matters enormously.

**3. Essential, useful context, or interesting history?**

**Essential. This is one of the top 5 papers in the curriculum.** Not because the mechanism is complex (it's not — "generate reasoning before answering"), but because it's the foundation of reasoning models (o1, Claude Thinking), the primary technique for improving accuracy on hard tasks, and the source of the most common cost optimization mistake (applying CoT uniformly instead of routing by task complexity).

Every production LLM system needs a CoT routing strategy. Every reasoning model you use is a trained version of this technique. Every time you pay for "thinking tokens," you're paying for CoT. Understanding the mechanism — and especially its limitations (doesn't help on simple tasks, reasoning chains aren't reliable explanations, self-consistency trades cost for accuracy) — is directly actionable for cost optimization, accuracy improvement, and system architecture decisions.

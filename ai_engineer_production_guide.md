# AI Engineer: From Projects to Production
> A production-focused reference for engineers who already know the basics.  
> Focus: System design · Architectural tradeoffs · Production decisions · Optimization

---

## Table of Contents

1. [LLM Fundamentals — The Engineering View](#1-llm-fundamentals--the-engineering-view)
2. [Prompt Engineering — Systematic Design](#2-prompt-engineering--systematic-design)
3. [Fine-Tuning — When, How, and What It Costs](#3-fine-tuning--when-how-and-what-it-costs)
4. [RAG — Production Architectures](#4-rag--production-architectures)
5. [Context Engineering](#5-context-engineering)
6. [AI Agents — Systems Design](#6-ai-agents--systems-design)
7. [Model Context Protocol (MCP)](#7-model-context-protocol-mcp)
8. [LLM Optimization](#8-llm-optimization)
9. [LLM Evaluation](#9-llm-evaluation)
10. [LLM Deployment](#10-llm-deployment)
11. [LLM Observability](#11-llm-observability)

---

# 1. LLM Fundamentals — The Engineering View

> Skip the "what is a token" — here's what matters when you're building systems on top of LLMs.

## 1.1 What Makes a Model "Production-Grade"

Not just parameter count. The real signals:
- **Context window size** (and whether it degrades at long contexts — most do)
- **Latency at P95/P99**, not just average
- **Tool-calling reliability** — does it hallucinate tool arguments?
- **Instruction-following consistency** — does the same prompt yield the same structure?
- **MMLU / coding / reasoning benchmarks** — but treat them as coarse filters, not ground truth

## 1.2 Architecture: Transformers vs. Mixture of Experts (MoE)

### Dense Transformer (GPT-4, Llama)
- All parameters active for every token
- Predictable compute: `O(n²)` attention, linear in parameters
- Memory-bound: entire model must fit on GPU(s)

### Mixture of Experts (MoE) — Mixtral, GPT-4o, Gemini
| Property | Dense | MoE |
|---|---|---|
| Total parameters | = active params | >> active params |
| Active params per token | 100% | 10–25% (e.g., 2 of 8 experts) |
| Inference FLOP/token | High | Lower (sparse activation) |
| Memory footprint | Smaller | Much larger |
| Throughput at scale | Lower | Higher (can shard experts) |
| Fine-tuning complexity | Standard | More complex (router training) |

**Production implication**: MoE models give you GPT-4 quality at GPT-3.5 inference cost *if* you have the VRAM to load the full model. If not, you're paying the memory tax without the throughput gain.

### Routing in MoE
- **Top-K gating**: each token selects K of N experts. Load balancing is not guaranteed.
- **Expert collapse**: a common failure mode where all tokens route to 1–2 experts. Fixed via auxiliary load balancing loss during training.
- **Implication for fine-tuning**: you need to be careful — fine-tuning an MoE with small data can cause router drift.

## 1.3 Generation Parameters: Production Decision Guide

```
Temperature    │ Controls entropy of token distribution
               │ 0 = greedy (deterministic), 1 = sampling, >1 = chaos
               │ Production: 0 for classification/structured output, 0.3–0.7 for generation

Top-P          │ Nucleus sampling: sample from smallest set of tokens summing to P
               │ Works WITH temperature, not instead of it
               │ Production default: 0.9–0.95

Top-K          │ Limit vocabulary to K most likely tokens before sampling
               │ Less nuanced than top-p; use top-p preferably
               │ Exception: local models where top-k is cheaper to compute

Repetition     │ Penalizes repeated token sequences
Penalty        │ > 1.0 reduces loops; don't go above 1.3 or output degrades

Max Tokens     │ HARD limit for cost and latency management
               │ Always set this; never let it default in production

Stop sequences │ Programmatically terminate generation early
               │ Critical for structured output — stop on "```" or "\n\n"
```

**The interaction problem**: Temperature + top-P + top-K + repetition penalty all stack. The behavior of their combination is non-linear and hard to predict. In production, **pick one sampling strategy and fix the others**. Most teams: temperature + top-P only.

## 1.4 Text Generation Strategies

### Greedy Decoding
- Always pick the highest-probability token
- Fast, deterministic, but degrades for long outputs (local optima → repetition)
- Use for: classification heads, short structured outputs

### Beam Search
- Maintain K candidate sequences, pick the globally best
- Better quality than greedy, but: slow (K× compute), mode-seeking (not diverse), penalizes length
- Use for: translation, summarization with hard length constraints
- **Not used by modern chat LLMs** — too slow and too conservative

### Sampling (Temperature / Top-P)
- Stochastic, diverse, fast
- The default for production LLM APIs
- Risk: non-determinism makes testing and debugging hard

### Speculative Decoding
- Small "draft" model generates N tokens, large "verifier" model accepts/rejects in one pass
- Same output distribution as the large model alone
- **2–3× speedup** on long generations
- Requires draft model to be architecturally compatible with target
- Real-world use: used in vLLM, TensorRT-LLM, Hugging Face TGI

### Structured Output / Constrained Decoding
- Grammar-constrained sampling: enforce JSON, regex, or custom grammar at the token level
- Libraries: `outlines`, `llama.cpp` grammar, `guidance`
- **The right architecture for any system requiring machine-parseable output** — not prompt hacking

## 1.5 Training an LLM with Another LLM (Distillation & RLHF)

### Knowledge Distillation
- Teacher model (large) generates soft labels (probability distributions)
- Student model (small) trained to match those distributions, not just the hard label
- Student learns *how* the teacher is uncertain, not just what it predicts
- **Production use**: create domain-specific small models from a large general model

### RLHF (Reinforcement Learning from Human Feedback)
```
Pretrained LLM → SFT (Supervised Fine-Tune on demonstrations)
             → Reward Model training (human preference data)
             → PPO/REINFORCE to maximize reward model signal
```
- The reward model is the critical bottleneck — garbage in, garbage out
- **Reward hacking**: model finds ways to maximize reward model score without actually improving. Classic failure mode.
- Modern alternative: **DPO (Direct Preference Optimization)** — eliminates separate RM, trains directly on preference pairs. Simpler, more stable, used by Llama-3, Mistral.

## 1.6 Running LLMs Locally: Engineering Considerations

| Runtime | Best For | Quantization | Throughput |
|---|---|---|---|
| llama.cpp | CPU/Mac, edge, no GPU | GGUF (Q4, Q5, Q8) | Low-medium |
| Ollama | Developer experience wrapper over llama.cpp | GGUF | Low-medium |
| vLLM | Production GPU serving | AWQ, GPTQ, fp8 | High |
| TGI (Hugging Face) | Research + production | Various | High |
| TensorRT-LLM | NVIDIA-optimized production | INT8, INT4, FP8 | Highest on NVIDIA |

**Quantization tradeoffs**:
- Q4 (4-bit): ~50% memory reduction, 1–3% quality drop on most tasks. Good default.
- Q8 (8-bit): ~25% memory reduction, <0.5% quality drop. Safe for production.
- INT4 with AWQ (Activation-Aware Weight Quantization): smarter than naive Q4, much lower quality degradation. **Best default for GPU inference.**
- FP8: requires Hopper (H100) or newer; near-lossless, best production option for high-end infra.

---

# 2. Prompt Engineering — Systematic Design

> Prompts are software. They need versioning, testing, and the same rigor as code.

## 2.1 Beyond Basics: Prompt Engineering as a System

**The amateur view**: write a prompt, get output, tweak manually.  
**The production view**: prompts are code with:
- Version control (treat prompt templates like source files)
- Evals (automated test suites against ground truth)
- A/B testing (route % of traffic to prompt variant B)
- Observability (log inputs, outputs, latency, cost per prompt)

## 2.2 Prompting Techniques for Reasoning

### Chain-of-Thought (CoT)
- "Think step by step" — forces the model to externalize reasoning
- **Why it works**: transformer next-token prediction is shallow; giving it "scratch space" to generate intermediate tokens dramatically increases compute depth
- **Limitation**: CoT reasoning can be post-hoc rationalization, not actual reasoning

### Few-Shot CoT
- Provide examples *with* reasoning traces, not just answers
- Better than zero-shot CoT for complex multi-step tasks
- Cost: more tokens per call; cache the system prompt to reduce cost

### Self-Consistency
- Sample 5–20 generations at temperature > 0
- Majority-vote on the final answer
- Significantly improves accuracy on math/logic tasks
- **Cost**: N× inference; practical only where accuracy is critical

### Tree of Thoughts (ToT)
- Model generates multiple reasoning *branches*, evaluates them, prunes
- Best for problems with discrete search spaces (puzzles, planning)
- **Production overhead**: requires multi-call orchestration; not a drop-in

### ReAct (Reason + Act)
- Interleaved reasoning + tool calls
- Model: "Thought: I need to search X. Action: search('X'). Observation: [result]. Thought: ..."
- The dominant pattern for agent reasoning loops

### Least-to-Most Prompting
- Decompose complex question → solve subproblems → compose final answer
- Systematically outperforms CoT on compositional tasks
- Good for workflows where you can predict the subproblem structure

## 2.3 Verbalized Sampling (Uncertainty-Aware Prompting)

Instead of asking the model to answer, ask it to produce a *distribution*:
```
"List 5 possible answers to this question with a confidence score for each."
```
- Lets you estimate model uncertainty without sampling many times
- Useful for: routing (low-confidence → human review), calibration, ensembling

**Production use**: combine with self-consistency — take the highest-voted + highest-verbalized-confidence answer.

## 2.4 JSON Prompting — Structured Output in Production

### Approach 1: Prompt-based (fragile)
```python
"Respond ONLY with valid JSON matching this schema: {...}"
```
Problems: model occasionally wraps in markdown, adds commentary, fails on complex schemas.

### Approach 2: Function Calling / Tool Use (better)
- OpenAI, Anthropic, Google all support structured output via tool definitions
- Model is trained to follow schema; much more reliable
- Still not 100% — retry logic is required

### Approach 3: Constrained Decoding (most reliable)
- Use `outlines`, `guidance`, or llama.cpp grammar sampling
- Mathematically guarantees valid output — schema violation is impossible at the token level
- **Use when**: parsing failure has downstream consequences (pipeline-breaking bugs)

### Production Pattern: Schema + Validation + Retry
```python
for attempt in range(3):
    raw = llm.call(prompt, response_format=MySchema)
    try:
        result = MySchema.model_validate_json(raw)
        return result
    except ValidationError as e:
        prompt = add_error_correction(prompt, str(e))  # inject error back
raise MaxRetriesExceeded()
```

---

# 3. Fine-Tuning — When, How, and What It Costs

> Fine-tuning is expensive, slow, and often the wrong answer. Know when it is and isn't.

## 3.1 The Decision: Fine-Tune vs. Not

**Fine-tune when**:
- You need a specific *style*, *format*, or *persona* consistently
- You need to inject domain knowledge not in the base model's training data
- You want to *remove* capability (distill to a smaller, cheaper model)
- You need latency/cost reduction (smaller model, same task performance)
- You have > 1000 high-quality labeled examples

**Don't fine-tune when**:
- You want to "teach facts" — RAG is cheaper and more accurate
- You have < 100 examples — the model will overfit
- You want to fix a failure mode that's really a prompt problem
- The base model already gets the task right with good prompting

## 3.2 Traditional Fine-Tuning: The Real Limitations

- **Catastrophic forgetting**: fine-tuning on task A erases performance on task B
- **Compute cost**: full fine-tune of 7B model requires ~4×80GB A100s minimum
- **Data efficiency**: needs thousands of examples for meaningful gain
- **Static**: once trained, it doesn't update; stale for fast-moving domains

## 3.3 LoRA: How It Actually Works

Low-Rank Adaptation freezes the original weight matrix W and learns two small matrices A and B:

```
W' = W + ΔW = W + B·A

Where:
  W  ∈ R^(d×k)   — original frozen weights
  B  ∈ R^(d×r)   — learned, initialized to 0
  A  ∈ R^(r×k)   — learned, initialized from Gaussian
  r << d, k      — rank (hyperparameter, typically 4–64)
```

**Why it works**:
- Hypothesis: weight updates in fine-tuning are inherently low-rank
- Instead of updating d×k parameters, you update r×(d+k) — often 100–1000× fewer
- During inference, compute W' = W + BA once and merge — **zero inference overhead**

**Rank selection**:
| Rank | Use Case |
|---|---|
| r=4 | Style adaptation, small format changes |
| r=8 | General instruction tuning |
| r=16–32 | Domain adaptation with significant shifts |
| r=64+ | Rarely needed; approaching full fine-tune cost |

### QLoRA
- Quantize the base model to 4-bit (NF4), run LoRA on top
- Fine-tune a 70B model on a single 48GB GPU
- Quality is close to full LoRA; small degradation from quantization
- **The standard approach for resource-constrained teams**

### Where to Apply LoRA Adapters

Not all layers are equal. Common practice:
- Target: `q_proj`, `v_proj` (query and value attention matrices)
- More aggressive: `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`
- More layers = more parameters = better performance + higher cost

## 3.4 Creating Instruction Fine-Tuning (IFT) Datasets

### Data quality >> data quantity
- 1000 clean, diverse, correctly-formatted examples beat 100k noisy ones
- Format: `{"instruction": "...", "input": "...", "output": "..."}`

### Data generation pipeline
```
1. Seed tasks (hand-written, high quality, ~20–200)
2. Self-instruct: use GPT-4 to generate variations
3. Filter: dedup (MinHash), quality score, diversity check
4. Human review: spot check 10%
5. Format: apply chat template for your target model (Llama-3, Mistral, etc.)
```

### Common Failure Modes
- **Format mismatch**: not using the model's native chat template → garbled output
- **Label leakage**: training data contains examples from your test set
- **Homogeneous data**: all examples from one source → poor generalization
- **Wrong loss masking**: computing loss on the instruction tokens, not just the output tokens

## 3.5 SFT vs. RFT (Supervised vs. Reinforcement Fine-Tuning)

| | SFT | RFT (RLHF/GRPO) |
|---|---|---|
| Data | (input, correct output) pairs | (input, reward signal) |
| What it optimizes | Cross-entropy loss on output tokens | Reward function |
| Best for | Format, style, following patterns | Reasoning, complex tasks with verifiable answers |
| Risk | Mode collapse, overfitting | Reward hacking, instability |
| Cost | Lower | Higher (multiple rollouts) |

**RFT wins when the output is verifiable** (code that compiles, math with a correct answer, SQL that executes). If you can write a reward function, prefer RFT over SFT for reasoning tasks.

## 3.6 GRPO — Building a Reasoning LLM

Group Relative Policy Optimization (DeepSeek-R1's approach):
```
1. Sample G outputs for each prompt (group)
2. Score each with reward function r(output)
3. Normalize scores within the group (advantage = (r - mean(r)) / std(r))
4. Update policy to increase probability of high-advantage outputs
5. KL divergence penalty to prevent drift from reference model
```

**Why GRPO over PPO**:
- No separate value/critic network needed
- Uses group statistics as baseline — simpler and more stable
- KL penalty is applied per-token, not globally

**Reinforcement Learning Bottlenecks in Practice**:
- **Reward function design** is the hardest part — poorly designed rewards get exploited
- **Mode collapse**: model finds a single high-reward pattern and repeats it
- **Slow convergence**: needs many rollouts; wall-clock time is 10–100× SFT
- **Compute**: each PPO step requires 4 forward passes (actor, critic, reference, reward model)

---

# 4. RAG — Production Architectures

> You've built a RAG pipeline. Now let's talk about what breaks at scale.

## 4.1 The RAG Stack — Production Components

```
Query → [Query Processing] → [Retrieval] → [Reranking] → [Context Assembly] → [Generation] → [Post-processing]
         - expansion          - dense        - cross-encoder  - dedup             - LLM call      - citation extraction
         - HyDE               - sparse       - LLM rerank     - token budget       - streaming     - hallucination check
         - classification     - hybrid       - MMR            - compression                        
```

Each stage is a decision point with tradeoffs. Most "bad RAG" is bad at retrieval or context assembly, not generation.

## 4.2 Chunking Strategies — The Underrated Bottleneck

**The core tension**: large chunks = more context, more noise. Small chunks = higher precision, missing context.

### Fixed-size chunking
- Simple, predictable, easy to implement
- Breaks semantic units (sentences, paragraphs) mid-thought
- **Only use for**: well-structured, homogeneous text (logs, tabular data)

### Semantic chunking
- Split on sentence boundaries; merge until similarity drops below threshold
- Preserves semantic cohesion
- Requires embedding each sentence: 2–5× more expensive at ingestion

### Hierarchical chunking (Parent-Child)
- Small chunks for retrieval (high precision)
- Return parent chunk for context (high recall)
- Implementation: store `parent_id` on each chunk; on retrieval, fetch parent
- **Best default for most production use cases**

### Late chunking (ColBERT-style)
- Embed the entire document, then pool at chunk boundaries
- Chunk embeddings have full document context → significantly better for long docs
- Requires a model that supports this (e.g., jina-embeddings-v3 with late chunking)

### Recursive character text splitting (LangChain default)
- Tries to split on `\n\n`, then `\n`, then `. `, then ` `
- Preserves structure better than fixed-size
- **Good default for quick prototypes**, not optimal for production

### Chunking for specific document types

| Doc Type | Best Strategy |
|---|---|
| PDFs with tables | Extract tables separately; chunk prose and tables independently |
| Code | Split on function/class boundaries, not character count |
| Markdown | Split on headers (`#`, `##`), preserve code blocks |
| HTML | Strip tags first; chunk on `<p>`, `<section>` |
| Long conversations | Sliding window with overlap; consider summarization chunking |

## 4.3 Vector Databases — Production Decisions

### Choosing a vector database

| DB | Best For | Tradeoffs |
|---|---|---|
| Pinecone | Managed, zero-ops | Expensive, vendor lock-in |
| Weaviate | Hybrid search, rich metadata filtering | More complex to operate |
| Qdrant | High performance, Rust-based, self-hosted | Newer ecosystem |
| pgvector | Already using Postgres | Poor perf at > 1M vectors |
| Chroma | Development, local | Not production-grade |
| Milvus | Large scale (100M+ vectors) | Complex ops overhead |

### The ANN Index Tradeoff
```
HNSW (Hierarchical Navigable Small World):
  + Best recall at high QPS
  + Supports incremental inserts
  - High memory usage (graph stored in RAM)
  - Build time is slow for 100M+ vectors

IVF-PQ (Inverted File + Product Quantization):
  + Lower memory (compressed vectors)
  - Lower recall (compression loses information)
  - Requires full rebuild for major updates

DiskANN:
  + Handles vectors that don't fit in RAM
  - Slower than HNSW for in-memory workloads
  - Best for 100M+ vectors with memory constraints
```

### Metadata Filtering Gotcha
Most vector DBs filter *after* ANN search — not before. This means:
- Query for k=10 with a filter may return < 10 results
- Solution: over-fetch (k=100), then filter in application layer
- Or: use DBs with pre-filtering support (Weaviate, Qdrant native filtering)

## 4.4 Retrieval Strategies: Dense, Sparse, Hybrid

### Dense retrieval (embedding-based)
- Query and documents embedded in same vector space; cosine similarity
- Great for semantic matching ("what is the capital of France" → "Paris is the capital")
- Fails on: exact keyword matching, rare terms, IDs, product codes

### Sparse retrieval (BM25/TF-IDF)
- Keyword overlap scoring with term frequency normalization
- Great for exact match, rare terms, code, entity names
- Fails on: paraphrase matching, synonyms

### Hybrid search (Reciprocal Rank Fusion)
```python
# RRF score: combine rankings from dense + sparse
rrf_score = sum(1 / (k + rank_i) for rank_i in [dense_rank, sparse_rank])
# k=60 is standard default
```
- **Almost always outperforms either alone**
- Weaviate, Qdrant, Elasticsearch support this natively
- If not supported: run both, merge in application with RRF

## 4.5 Reranking — Critical for Precision

First-stage retrieval (dense + sparse) gives you top-100. Reranking gives you top-5.

### Cross-encoder reranker
- Takes (query, document) pair, outputs relevance score
- Much more accurate than bi-encoder but: O(n) inference vs O(1)
- Models: `cross-encoder/ms-marco-MiniLM-L-6-v2`, Cohere Rerank API
- **Always add a reranker** if latency budget allows (~50–200ms add)

### LLM-based reranking
- Use the LLM itself to score or order candidates
- Expensive (full LLM call per candidate), but highest quality
- Use sparingly; good for offline data prep or high-value queries

### Maximal Marginal Relevance (MMR)
- Balances relevance AND diversity: penalize chunks similar to already-selected ones
- Critical when documents repeat the same information
- `λ` parameter controls relevance vs. diversity tradeoff

## 4.6 RAG Architectures

### Naive RAG
```
Query → Embed → ANN Search → Top-K chunks → Prompt + Generate
```
Fails at: complex multi-hop questions, ambiguous queries, long documents.

### Advanced RAG
- **Pre-retrieval**: query expansion, HyDE, query routing
- **During retrieval**: hybrid search, metadata filtering
- **Post-retrieval**: reranking, compression, dedup

### Modular RAG
- Each component (retriever, reranker, generator) is swappable
- A/B test individual components independently
- Use LlamaIndex or custom pipelines; avoid framework lock-in for core logic

### Agentic RAG
- Retrieval is a tool the agent can call multiple times
- Agent decides *when* to retrieve, *what* to search for, and *whether to retry*
- Can do multi-hop: "Find CEO of Company X, then find their LinkedIn profile"
- **Use when**: queries require dynamic multi-step information gathering
- **Don't use when**: simple Q&A; latency overhead not justified

## 4.7 HyDE: Hypothetical Document Embeddings

```
Query: "How does LoRA reduce memory usage?"
Step 1: LLM generates a hypothetical answer (even if wrong)
Step 2: Embed the hypothetical answer (not the query)
Step 3: Use that embedding for ANN search
```

**Why it works**: LLMs generate text in the same distribution as documents. The hypothetical answer is a better embedding signal than the raw query.

**When it fails**: hallucinated hypothetical answers are very wrong → retrieval is worse than regular query embedding. Use a fast/cheap model for hypothesis generation.

## 4.8 RAG vs. CAG (Cache-Augmented Generation)

**CAG (Cache-Augmented Generation)**:
- Load the entire knowledge base into the context window
- Works for small corpora (< 1–2M tokens) and models with long contexts (Gemini 2.0 = 1M tokens)
- Zero retrieval latency, no chunking errors
- **Tradeoffs**: expensive (full context = full cost per query), slower (more tokens = more compute), no filtering

**When to use CAG**: 
- Corpus < 500 documents, updates are rare, maximum accuracy needed
- Domain-specific assistants with a fixed, small knowledge base

**When to use RAG**: 
- Large, dynamic corpus; cost-sensitive; need citations/provenance

## 4.9 RAG vs. REFRAG

REFRAG (Retrieval-Enhanced Fine-tuning with RAG):
- Fine-tune the LLM with retrieval-augmented examples
- Model learns to *use* retrieved context effectively
- Addresses "lost in the middle" problem — model ignores middle chunks
- More expensive than RAG alone, but significantly better utilization of retrieved context

## 4.10 Prompting vs. RAG vs. Fine-Tuning — Decision Matrix

| Scenario | Best Approach |
|---|---|
| Model doesn't know a fact | RAG |
| Model knows the fact but formats it wrong | Prompt engineering or SFT |
| Model needs real-time/dynamic data | RAG |
| You need consistent behavior/persona | SFT (LoRA) |
| You need to compress a large model | Distillation |
| You need to teach reasoning skills | RFT (GRPO) |
| Small knowledge base, high accuracy needed | CAG or SFT |

---

# 5. Context Engineering

> Context is the new prompt. What you put in the context window determines everything.

## 5.1 What Is Context Engineering

Context engineering = the discipline of deciding **what information to include, exclude, and how to structure it** in the model's context window for each request.

It's a superset of prompt engineering. Prompt engineering = the words. Context engineering = the entire information architecture.

## 5.2 Types of Context in AI Agents

```
1. System Context      — persistent instructions, persona, tool descriptions, constraints
2. Conversation Memory — prior turns (verbatim or summarized)
3. Retrieved Knowledge — RAG results, search results
4. Tool Outputs        — results from function calls, API responses
5. Working Memory      — scratchpad, intermediate reasoning steps
6. Environmental State — current time, user state, session metadata
```

**The budget problem**: LLMs have finite context windows. Every token has cost ($$) and quality implications. Context engineering is resource allocation.

## 5.3 Context Engineering for AI Agents

### Context Prioritization (when context overflows)
```
Priority order (highest to lowest):
1. System instructions — never truncate
2. Current turn input — never truncate  
3. Recent tool outputs — truncate oldest first
4. Conversation history — summarize then truncate
5. Retrieved context — filter by recency and relevance score
```

### Conversation Memory Strategies

| Strategy | Pros | Cons |
|---|---|---|
| Full history | Complete context | Expensive, hits window limit |
| Fixed window (last N turns) | Cheap, predictable | Loses early context |
| Summarization | Retains gist, scales | Loses details, lossy |
| Episodic + summary | Best of both | More complex to implement |
| Semantic retrieval | Retrieves relevant past | Retrieval overhead |

**Production default**: Summarize conversations at turn 20+, keep last 5 turns verbatim.

### The "Lost in the Middle" Problem
Research shows LLMs best recall information at the **beginning** and **end** of context. Middle content is ~40% less likely to be utilized.

**Mitigation**:
- Put instructions first, retrieved context second, the question last
- Or: put the question first, instructions and context after ("late instruction following")
- Use compression: summarize middle chunks before inserting
- For critical context: repeat key facts at end of prompt

## 5.4 Context Compression Techniques

### LLMLingua-style compression
- Use a smaller model to score each sentence/token for importance
- Drop low-importance tokens before passing to main model
- 3–5× compression ratio with < 5% quality drop
- **Use for**: long document Q&A, meeting transcripts, legal docs

### Summary-based compression
- Recursively summarize chunks that exceed budget
- Simple but lossy; fine for conversations, bad for technical docs

### Selective retrieval from memory
- Store all context in a vector store
- On each new turn, retrieve only relevant past context
- Best for: long-running agents, multi-session applications

## 5.5 Building a Context Engineering Workflow

```python
class ContextBuilder:
    def __init__(self, max_tokens: int):
        self.budget = max_tokens
        self.slots = {}  # named slots with priority and token counts
    
    def allocate(self, name: str, content: str, priority: int, max_tokens: int):
        """Add a context slot; trim to budget in priority order."""
        tokens = count_tokens(content)
        self.slots[name] = {"content": content, "priority": priority, 
                            "tokens": min(tokens, max_tokens)}
    
    def build(self) -> str:
        # Sort by priority; pack into budget
        sorted_slots = sorted(self.slots.values(), key=lambda x: x["priority"])
        used = 0
        output = []
        for slot in sorted_slots:
            if used + slot["tokens"] <= self.budget:
                output.append(slot["content"])
                used += slot["tokens"]
            else:
                # Truncate or compress to fit remaining budget
                remaining = self.budget - used
                output.append(compress(slot["content"], remaining))
                break
        return "\n\n".join(output)
```

---

# 6. AI Agents — Systems Design

> Agents are not chatbots with tools. They're autonomous systems with control loops, state, and failure modes.

## 6.1 Agent Architecture: The Core Loop

```
┌─────────────────────────────────────────────┐
│                  AGENT LOOP                  │
│                                              │
│  Observe → Plan/Reason → Act → Observe → ... │
│                                              │
│  Observe: environment state, tool outputs   │
│  Plan:    LLM generates next action          │
│  Act:     Execute tool/API/code              │
│  Loop:    Until goal achieved or limit hit   │
└─────────────────────────────────────────────┘
```

The LLM is the **brain** (reasoning), tools are the **hands** (action), memory is the **state**.

## 6.2 Building Blocks of AI Agents

| Component | What It Does | Key Decisions |
|---|---|---|
| LLM Core | Reasoning, planning, decision-making | Model quality vs. cost |
| Tool Registry | What actions the agent can take | Tool granularity, documentation quality |
| Memory | State persistence | Storage type, retrieval strategy |
| Orchestrator | Controls the agent loop | Max iterations, timeout, error handling |
| Executor | Runs tool code safely | Sandboxing, timeout, output sanitization |

## 6.3 Memory Types in AI Agents

```
Sensory Memory     → Current input/observation (seconds)
                     = the current turn's content
                     
Working Memory     → Active reasoning context (current session)
                     = what's in the context window right now
                     
Episodic Memory    → Past events, indexed by time/session
                     = vector store of conversation summaries
                     
Semantic Memory    → General knowledge about the world/domain
                     = RAG knowledge base, facts about entities
                     
Procedural Memory  → How to do things (skills, workflows)
                     = few-shot examples, tool schemas, SOPs
```

**Production implication**: Most "agent memory" implementations only implement working + episodic. Semantic (RAG) and procedural (tool descriptions + examples) are the differentiators.

## 6.4 Agentic Design Patterns

### ReAct (Reasoning + Acting)
```
Thought: I need to find the current stock price of AAPL
Action: search("AAPL stock price today")
Observation: AAPL is trading at $189.42
Thought: Now I have the price. The user asked if it's above $180.
Action: answer("Yes, AAPL is above $180 at $189.42")
```
- Simple, widely adopted, works with most LLMs
- Weakness: can get stuck in loops; needs iteration limits

### Plan-and-Execute
```
Step 1: LLM generates a full plan (list of steps)
Step 2: Execute steps sequentially (or parallel)
Step 3: Each step's output feeds into next
Step 4: Re-plan if a step fails or reveals new info
```
- Better for predictable, structured workflows
- Allows parallelism (steps without dependencies can run concurrently)
- Weakness: initial plan may be wrong; need adaptive re-planning

### Reflection / Self-Critique
```
Act → Generate output → Critique(output) → If not good enough: retry → Final answer
```
- LLM evaluates its own output before returning
- Significant quality improvement on complex tasks
- Cost: 2× minimum (one generation + one critique)
- Can chain: Reflexion architecture loops critique + retry up to N times

### Tool Use Pattern
```python
tools = [
    {"name": "search", "description": "...", "parameters": {...}},
    {"name": "code_exec", "description": "...", "parameters": {...}},
]
# Pass tools to LLM; parse structured tool call from response
# Execute tool; inject result back into context
```

## 6.5 Multi-Agent System Patterns

### Orchestrator-Worker
```
Orchestrator Agent
├── Worker A (research)
├── Worker B (coding)  
└── Worker C (writing)
```
- Orchestrator decomposes task, assigns to specialists
- Workers have narrow, focused capabilities
- **Best for**: complex tasks with parallelizable subtasks
- **Failure mode**: orchestrator context grows unbounded; inject summaries, not full worker outputs

### Debate / Adversarial
```
Agent A: "The answer is X because..."
Agent B: "I disagree because Y..."
Judge:   "Based on the debate, the answer is..."
```
- Improves accuracy on controversial or complex decisions
- 3× inference cost minimum
- Good for: code review, safety evaluation, high-stakes decisions

### Hierarchical
```
CEO Agent
├── Manager Agent A
│   ├── Worker 1
│   └── Worker 2
└── Manager Agent B
    ├── Worker 3
    └── Worker 4
```
- Scales to complex workflows
- Each level has appropriate context and responsibility
- **Critical**: define clear interfaces and output schemas between levels

### Shared Memory / Blackboard
```
All agents read/write to a shared state object
State: {"research": {...}, "code": "...", "status": "review_needed"}
Agents subscribe to state changes and act accordingly
```
- Enables emergent coordination without explicit orchestration
- Complex to implement correctly; race conditions are a risk

## 6.6 Agent2Agent (A2A) Protocol

Google's open protocol for agent interoperability:
- Agents expose an `AgentCard` (capability manifest) at `/.well-known/agent.json`
- Agents communicate via HTTP+JSON or SSE (streaming)
- Support for: tasks (long-running), messages (short interactions), artifacts (file outputs)
- **Key innovation**: standardized discovery — agents can find and delegate to other agents dynamically

### A2A vs. Building Your Own
| Criteria | A2A | Custom |
|---|---|---|
| Ecosystem interop | ✅ | ❌ |
| Learning curve | Medium | Low initially |
| Flexibility | Constrained to spec | Unlimited |
| Production-ready | Maturing | Depends on you |

## 6.7 AG-UI Protocol

Anthropic's protocol for agent-user interaction:
- Standardizes how agents communicate *back to users* (not just agents to agents)
- Supports: streaming text, structured data, UI components, approval requests
- Human-in-the-loop: agent can pause and request user confirmation before acting
- **Use case**: when agent actions have real-world consequences (sending emails, making purchases)

## 6.8 Levels of Agentic AI Systems

```
Level 0: LLM call → response
Level 1: LLM + tools (single turn)
Level 2: LLM + tools (multi-turn, stateful)
Level 3: Multi-agent (orchestrator + workers)
Level 4: Fully autonomous (self-directed, self-correcting, persistent)
```

**Production rule**: only go as high as the task requires. Each level adds latency, cost, and failure surface.

## 6.9 AI Agent Deployment Strategies

### Synchronous Agent (request-response)
- User waits for agent to complete
- Good for: < 30 second tasks, interactive experiences
- Challenge: timeouts at API gateway level (default: 30s for many services)

### Asynchronous Agent (job-based)
```
1. User submits task → get task_id
2. Agent runs in background (Celery, Cloud Run Jobs, etc.)
3. User polls or receives webhook on completion
```
- Necessary for: > 30s tasks, multi-step workflows, batch processing
- **Most production agents should be async**

### Event-Driven Agent
- Agent subscribes to a queue (Kafka, SQS, Pub/Sub)
- Triggered by events, not user requests
- Best for: monitoring agents, automation agents, data pipeline agents

### Agent-as-a-Microservice
- Agent is a standalone service with a REST/gRPC API
- Scales independently; integrates with existing infrastructure
- Statelessness: all state lives in external storage (Redis, DB)

---

# 7. Model Context Protocol (MCP)

> MCP is to AI agents what REST was to web services — a standard that makes integration composable.

## 7.1 What MCP Solves

**Before MCP**: every AI application writes custom integration code for every tool (search, database, file system, APIs). N tools × M applications = N×M integrations.

**After MCP**: tools expose a standard MCP interface. Any MCP-compatible client can use any MCP server. N tools + M applications = N+M implementations.

## 7.2 MCP Architecture

```
┌──────────────────────────────────┐
│         MCP Client (Host)         │
│  (Claude Desktop, IDE, Agent)    │
│  - Manages connections           │
│  - Sends requests, gets results  │
└────────────┬─────────────────────┘
             │ MCP Protocol (JSON-RPC 2.0 over stdio / HTTP+SSE)
             ↓
┌──────────────────────────────────┐
│         MCP Server               │
│  - Exposes Tools, Resources,    │
│    and Prompts                   │
│  - Stateless (usually)          │
└──────────────────────────────────┘
```

**Transport options**:
- **stdio**: server is a subprocess; client communicates via stdin/stdout. Local only.
- **HTTP + SSE**: server is an HTTP service; supports remote, multi-client. Production default.

## 7.3 Core MCP Primitives

### Tools
- Functions the LLM can call (side effects, computation)
- Defined with name, description, JSON schema for parameters
- **Critical**: the description IS the prompt. Write it like documentation for the LLM, not for humans.
- Example: `{"name": "search_documents", "description": "Searches the knowledge base for relevant documents. Use this when you need factual information about...", "inputSchema": {...}}`

### Resources
- Data the LLM can read (no side effects)
- Files, database records, API responses
- Identified by URI: `file:///path/to/file`, `db://table/row_id`
- LLM can list and read resources; server controls access

### Prompts
- Reusable prompt templates the server exposes
- Allow operators to define "skills" that users and LLMs can invoke
- Example: `summarize_document`, `code_review`, `extract_entities`

## 7.4 Tool Overload Problem

Too many tools → LLM can't choose correctly (attention dilution, routing errors).

**Symptoms**: LLM picks wrong tool, combines tools incorrectly, or fails to use tools at all.

**Solutions**:
- **Server Manager / Tool Router**: a meta-agent that selects which tool server to activate based on task type
- **Dynamic tool loading**: only provide tools relevant to current task
- **Tool grouping**: namespace tools by domain ("db.*", "search.*")
- **Rule of thumb**: < 20 tools in context at once; ideally < 10 for reliable selection

## 7.5 MCP vs. Function Calling

| Aspect | Function Calling | MCP |
|---|---|---|
| Defined by | LLM provider (OpenAI, Anthropic) | Open standard |
| Portability | Provider-specific | Universal |
| Discovery | Static (hardcoded) | Dynamic (server exposes tool list) |
| Transport | In-band (same API call) | Separate protocol |
| State | Stateless | Can be stateful (resources) |
| Ecosystem | Large (OpenAI tools ecosystem) | Growing (Anthropic-led) |

**MCP subsumes function calling**: use MCP for new systems; use function calling if you're already in an OpenAI-ecosystem.

## 7.6 Creating an MCP Server (Key Patterns)

```python
from mcp.server import Server
from mcp.server.models import InitializationOptions
import mcp.types as types

app = Server("my-server")

@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search",
            description="Search for documents matching a query",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"}
                },
                "required": ["query"]
            }
        )
    ]

@app.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "search":
        results = await do_search(arguments["query"])
        return [types.TextContent(type="text", text=format_results(results))]
    raise ValueError(f"Unknown tool: {name}")
```

**Production considerations**:
- Tool handlers should be async and non-blocking
- Add timeout handling; LLMs expect fast tool responses (< 5s)
- Log all tool calls for observability
- Implement tool-level rate limiting

---

# 8. LLM Optimization

> Optimization is how you go from "this works" to "this is viable at scale."

## 8.1 The Cost Structure of LLM Inference

```
Cost = (prompt_tokens + completion_tokens) × price_per_token
Latency ∝ completion_tokens (generation is sequential)
Throughput ∝ batch_size (prompt processing is parallelizable)
```

**The key insight**: prompts (prefill) are fast and parallelizable. Generation (decode) is slow and sequential. Optimization targets differ:
- **Latency optimization**: reduce generation time → speculative decoding, streaming, early stopping
- **Throughput optimization**: increase concurrent requests → batching, KV cache sharing
- **Cost optimization**: reduce token count → prompt compression, caching, smaller models

## 8.2 Model Compression Techniques

### Quantization
```
FP32 → FP16/BF16: 2× memory, minimal quality loss (standard)
FP16 → INT8:      2× additional, 0.5–1% quality loss
INT8 → INT4:      2× additional, 2–5% quality loss (task-dependent)
```

**AWQ (Activation-aware Weight Quantization)**:
- Identifies "salient" weights (high activation magnitude) and preserves their precision
- Outperforms naive INT4 significantly
- Recommended for production INT4 deployment

**GPTQ (Post-Training Quantization)**:
- Layer-by-layer quantization with second-order optimization
- Good quality, but slower to quantize than AWQ
- More suitable for: offline batch inference

### Pruning
- Remove weights below a threshold (unstructured) or entire neurons/heads (structured)
- Unstructured: high compression, hard to speed up on hardware (sparse matrices are slow)
- Structured: less compression, directly speeds up inference
- **Not widely used in production** — quantization is simpler and more reliable

### Distillation
- Train a small model to mimic a large model's outputs
- Best for specific, well-defined tasks
- E.g., distill GPT-4 reasoning traces → fine-tune a 7B model for 90% of GPT-4's performance on your specific task at 10% of the cost

## 8.3 Traditional ML Inference vs. LLM Inference

| Aspect | Traditional ML | LLM |
|---|---|---|
| Input size | Fixed (e.g., 224×224 image) | Variable (1–1M tokens) |
| Output size | Fixed (class probabilities) | Variable (1–4096 tokens) |
| Compute | One forward pass | N forward passes (one per token) |
| Memory pattern | Batch efficiently | KV cache grows with sequence length |
| Hardware | GPU or CPU | GPU (VRAM-intensive) |
| Batching | Trivial (same size inputs) | Complex (continuous batching) |

**Continuous batching** (used by vLLM): instead of waiting for all requests to finish before starting a new batch, new requests are inserted into the batch as soon as a slot frees up. Dramatically improves GPU utilization.

## 8.4 KV Caching — Deep Dive

Every transformer attention layer computes Key and Value matrices from input tokens. These are reused in every subsequent generation step.

```
Without caching: recompute K,V for ALL previous tokens at every step
                 Cost: O(n²) per token generated — brutal for long contexts

With KV caching: compute K,V once; cache in VRAM; reuse at every step
                 Cost: O(n) per token — much better
```

### KV Cache Memory Formula
```
KV cache size = 2 × num_layers × num_heads × head_dim × seq_len × batch_size × bytes_per_element
Example (Llama-3 70B, 4096 seq, batch=1, fp16):
= 2 × 80 × 8 × 128 × 4096 × 1 × 2 bytes ≈ 1.3 GB per request
```

**This is why LLMs OOM under load**: each concurrent request needs its own KV cache.

### Strategies to Manage KV Cache

| Strategy | How | Trade-off |
|---|---|---|
| Paged attention (vLLM) | Store KV cache in non-contiguous pages, like OS virtual memory | Enables more concurrent requests; slight overhead |
| Prefix caching | Cache KV for shared prefixes (system prompts) | Huge win when system prompt is long and shared |
| KV cache quantization | Store cache in INT8 instead of FP16 | 2× capacity, small quality hit |
| Sliding window (Mistral) | Only cache last N tokens, not all | Fixes memory but loses long-range context |
| Multi-Query Attention (MQA) | All heads share one K and V | Much smaller cache, slight quality drop |
| Grouped Query Attention (GQA) | Groups of heads share K and V | Balance of MQA and MHA; used in Llama-3 |

### Prefix Caching in Production
- Store KV cache for system prompt; reuse across requests
- **Up to 90% cost reduction** when system prompt is large
- Supported: Anthropic, Google (implicit caching), OpenAI (prompt caching)
- Implementation: pass long system prompts in consistent position (don't randomize)

## 8.5 Throughput vs. Latency Optimization

```
High Throughput mode (batch processing):
- Larger batch sizes
- Longer max sequence lengths
- Sacrifice P99 latency for higher total token/sec
- Use: background jobs, data preprocessing, evaluation

Low Latency mode (interactive):
- Small batches (often batch=1)
- Streaming responses (user sees tokens as generated)
- Shorter max tokens
- Use: chat interfaces, real-time applications
```

You cannot optimize for both simultaneously on the same deployment. Run **separate inference endpoints** for latency-sensitive (interactive) and throughput-sensitive (batch) workloads.

---

# 9. LLM Evaluation

> If you can't measure it, you can't improve it. Most "evals" teams do are inadequate.

## 9.1 The Evaluation Hierarchy

```
Level 1: Unit Tests          → Does output match expected for a given input?
Level 2: Reference-based     → How similar is output to a gold reference? (BLEU, ROUGE, BERTScore)
Level 3: Model-based         → Use another LLM to score quality (G-Eval, LLM-as-Judge)
Level 4: Human evaluation    → Ground truth; expensive, slow, gold standard
Level 5: Online / live eval  → A/B testing in production; measures real user outcomes
```

**Most teams stop at Level 3. Level 5 is what actually matters.**

## 9.2 G-Eval Framework

G-Eval uses chain-of-thought + form-filling to score LLM outputs:
```
1. Define evaluation criteria (coherence, relevance, fluency, etc.)
2. For each criterion, generate a CoT reasoning prompt
3. LLM scores each criterion (1–5)
4. Weighted aggregate = final score
```

**Key insight**: G-Eval scores correlate with human judgments better than ROUGE/BLEU for generative tasks.

**Implementation gotchas**:
- Use token-level probabilities (not just generated score) for more granular scoring
- Use a strong model as judge (GPT-4, Claude 3.5 Sonnet); weak judge = noisy scores
- Criteria must be explicit and non-overlapping

## 9.3 LLM-as-a-Judge

Use a strong LLM to evaluate the output of another LLM.

### Single-answer grading
```python
JUDGE_PROMPT = """
You are an expert judge evaluating AI responses.
Evaluate the following response on a scale of 1-10 for:
- Accuracy: Does it answer the question correctly?
- Completeness: Does it cover all aspects?
- Clarity: Is it clear and well-structured?

Question: {question}
Response: {response}
Reference Answer: {reference}

Provide scores and brief justification for each criterion.
Output as JSON: {"accuracy": N, "completeness": N, "clarity": N, "reasoning": "..."}
"""
```

### Pairwise comparison (Arena style)
- Show judge two responses (A and B), ask which is better
- More reliable than absolute scoring (eliminates scale ambiguity)
- Used by Chatbot Arena (LMSYS) for leaderboard rankings
- **Implement in production**: route 5% of traffic to response variant B; judge A vs B

### Bias mitigations
- **Position bias**: LLMs favor the first response shown. Randomize position; average both orderings.
- **Verbosity bias**: LLMs prefer longer responses. Explicitly penalize verbosity in judge prompt.
- **Self-preference**: Claude favors Claude-style responses. Use different family models as judges.

## 9.4 Multi-Turn Evaluations

Single-turn evals miss: context carryover, memory utilization, coherence over time.

**Multi-turn evaluation setup**:
```
Turn 1: Ask a question
Turn 2: Ask a follow-up that requires memory of Turn 1
Turn 3: Ask a clarifying question that changes the answer context
Turn N: Evaluate: did the agent maintain coherent state?
```

**Key metrics**:
- Context recall: does the agent remember prior turns correctly?
- Instruction persistence: if user sets a constraint in turn 1, does it hold in turn 10?
- Contradiction rate: does the agent contradict itself across turns?

## 9.5 Component-Level Evaluations (for RAG + Agents)

### RAG-specific metrics
| Metric | Measures | Method |
|---|---|---|
| Retrieval Precision | Are retrieved chunks relevant? | LLM judge or human label |
| Retrieval Recall | Are all relevant chunks retrieved? | Requires known relevant set |
| Answer Faithfulness | Is answer grounded in retrieved context? | Check if claims appear in context |
| Answer Relevance | Does the answer address the question? | Embed question + answer; cosine sim |
| Context Utilization | Does the model use what was retrieved? | Check if key context facts appear in answer |

**RAGAS framework** automates these metrics. Use it.

### Agent-specific metrics
- **Task completion rate**: % of tasks fully completed
- **Tool call accuracy**: correct tool selected, correct arguments
- **Step efficiency**: number of tool calls vs. minimum needed
- **Hallucination rate**: claims made without tool grounding

## 9.6 Red Teaming LLM Applications

Not optional in production. Do this before launch.

### Automated red teaming
- Use an "attacker" LLM to generate adversarial inputs
- Categories: prompt injection, jailbreaking, PII extraction, harmful content
- Tools: Garak, PyRIT (Microsoft)

### Prompt Injection Attack Surface
```
Direct injection:   User says "Ignore previous instructions and..."
Indirect injection: Tool returns content that contains hidden instructions
                    (e.g., a web page the agent scrapes says "You are now a...")
```

**Mitigations**:
- Delimiter injection defense: wrap user input in clear delimiters; instruct model to treat content between them as untrusted data
- Separate system and user trust levels
- Validate that tool outputs don't match instruction patterns before injecting into context

---

# 10. LLM Deployment

> Deployment is where complexity compounds. Design for failure from day one.

## 10.1 Why LLM Deployment is Different

```
Traditional service:    stateless, predictable latency, fixed memory per request
LLM service:            stateful (KV cache), variable latency (token count), 
                        memory proportional to context length, expensive GPU hardware
```

**Key challenges**:
1. **Cold start**: GPU model loading takes 30–120s. Must use warm instances.
2. **Memory fragmentation**: KV cache grows dynamically. Standard allocators fail. Need paged attention (vLLM).
3. **Variable request cost**: a 1-token answer and a 4096-token answer cost the same GPU time proportionally but very differently in absolute terms. Rate limiting by request count is wrong; rate limit by token count.
4. **Autoscaling**: GPUs take minutes to provision. Scale proactively, not reactively.

## 10.2 vLLM — Production LLM Serving

**What it is**: High-throughput, memory-efficient LLM inference engine.

**Key innovations**:
- **PagedAttention**: KV cache stored in non-contiguous pages (like OS paging). Eliminates fragmentation. Enables 2–4× more concurrent requests than naive implementations.
- **Continuous batching**: new requests join in-flight batches. No waiting for batch to complete.
- **Prefix caching**: automatically caches and reuses common prefixes.

### vLLM Deployment Pattern
```bash
# Basic server
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3-8B-Instruct \
  --tensor-parallel-size 2 \          # split across 2 GPUs
  --max-model-len 8192 \              # limit context for memory control
  --gpu-memory-utilization 0.90 \     # leave 10% headroom
  --max-num-seqs 256                  # max concurrent sequences
```

### Tensor Parallelism vs. Pipeline Parallelism
| | Tensor Parallel | Pipeline Parallel |
|---|---|---|
| How | Split each layer's weights across GPUs | Split layers across GPUs |
| Communication | High (all-reduce per layer) | Low (activation pass between stages) |
| Latency | Lower | Higher (pipeline bubbles) |
| Use when | < 8 GPUs, latency-sensitive | Many GPUs, throughput-sensitive |

## 10.3 LitServe — Lightweight Model Serving

Alternative to vLLM for non-LLM or mixed workloads:
- PyTorch Lightning's inference server
- Simple Python API, handles batching, async, streaming
- Not as specialized as vLLM for LLMs but more flexible for custom models

```python
import litserve as ls
from transformers import pipeline

class TextClassifierAPI(ls.LitAPI):
    def setup(self, device):
        self.model = pipeline("text-classification", device=device)
    
    def decode_request(self, request):
        return request["text"]
    
    def predict(self, x):
        return self.model(x)
    
    def encode_response(self, output):
        return {"label": output[0]["label"], "score": output[0]["score"]}

server = ls.LitServer(TextClassifierAPI(), accelerator="gpu", max_batch_size=64)
server.run(port=8000)
```

## 10.4 Production Deployment Architecture

```
                    ┌─────────────────────────────────┐
                    │         Load Balancer            │
                    │   (health check, rate limiting)  │
                    └──────────────┬──────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ↓                    ↓                    ↓
    ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
    │  vLLM Instance  │  │  vLLM Instance  │  │  vLLM Instance  │
    │  (GPU Node 1)   │  │  (GPU Node 2)   │  │  (GPU Node 3)   │
    └─────────────────┘  └─────────────────┘  └─────────────────┘
              │                    │                    │
              └────────────────────┼────────────────────┘
                                   ↓
                    ┌─────────────────────────────────┐
                    │     Shared KV Cache Store        │
                    │     (Redis / Distributed)        │
                    └─────────────────────────────────┘
```

**Routing strategies**:
- **Round-robin**: simple, doesn't account for KV cache affinity
- **Prefix-aware routing**: route requests with same prefix to same instance (maximizes cache hit)
- **Least-loaded**: route to instance with fewest active sequences

## 10.5 API Design for LLM Services

```
POST /v1/chat/completions        - OpenAI-compatible; use this for portability
GET  /v1/models                  - Model capability metadata
POST /v1/embeddings              - Embedding endpoint
GET  /health                     - Health check (liveness)
GET  /metrics                    - Prometheus metrics (latency, tokens/sec, queue depth)
```

**Always implement**:
- **Streaming** (`stream=true`): return tokens as SSE events; dramatically improves perceived latency
- **Request ID**: every request gets a UUID; log it; return in response header
- **Timeout handling**: set server-side max generation time; fail fast rather than timeout at client
- **Graceful degradation**: if GPU OOMs, return 503 with `Retry-After` header; don't crash

---

# 11. LLM Observability

> You can't debug what you can't see. LLM systems fail silently in ways traditional services don't.

## 11.1 Evaluation vs. Observability

| | Evaluation | Observability |
|---|---|---|
| When | Offline, before deployment | Online, during production |
| Data | Curated test sets | Live traffic samples |
| Purpose | Validate model quality | Detect degradation, debug issues |
| Feedback loop | Batch (daily/weekly) | Real-time or near-real-time |
| Key question | "Is the model good?" | "Is the system working as intended?" |

**They're complementary, not alternatives.** Evaluation tells you if you should deploy. Observability tells you what happened after you did.

## 11.2 What to Log (The Minimum Viable Observability Stack)

```json
{
  "request_id": "uuid",
  "timestamp": "ISO-8601",
  "model": "llama-3-8b-instruct",
  "prompt_tokens": 512,
  "completion_tokens": 128,
  "total_tokens": 640,
  "latency_ms": 2340,
  "ttfb_ms": 340,         // time to first byte (streaming)
  "prompt_hash": "sha256", // for dedup and caching analytics
  "user_id": "u_xxx",      // for per-user analytics
  "session_id": "s_xxx",
  "tool_calls": [...],
  "cost_usd": 0.00128,
  "error": null,
  "response_id": "uuid",
  "tags": ["production", "rag", "customer_support"]
}
```

**Also log**:
- Full prompt + response (with PII masking)
- Retrieved chunks (for RAG) with their scores
- Tool call inputs and outputs (for agents)
- User feedback signals (thumbs up/down, corrections, session abandon)

## 11.3 Key Metrics and Dashboards

### Infrastructure metrics
- **Tokens per second** (TPS): throughput health
- **GPU utilization %**: capacity planning
- **KV cache hit rate**: caching effectiveness
- **Queue depth**: request backpressure indicator
- **P50/P95/P99 latency**: SLA monitoring
- **Error rate %**: reliability

### Quality metrics (sampled)
- **LLM-as-judge scores**: sampled at 1–5% of traffic
- **Hallucination rate**: for RAG systems, check grounding
- **Tool call success rate**: for agent systems
- **User satisfaction proxy**: session length, follow-up questions, explicit feedback

## 11.4 Tracing for LLM Systems

Traditional distributed tracing (OpenTelemetry) + LLM-specific spans:

```
Request Span
├── Context Building Span (which slots, how many tokens)
├── RAG Retrieval Span (query, k, results, scores)
│   ├── Embedding Span (model, latency)
│   └── Vector Search Span (index, latency, results)
├── Reranking Span (input count, output count, latency)
├── LLM Inference Span (model, tokens, latency)
│   ├── Tool Call Span: search (args, result)
│   └── Tool Call Span: code_exec (code, output)
└── Response Post-processing Span
```

**Tools**: LangSmith, Weights & Biases Prompts, Helicone, Opik (Comet), Langfuse (open source).

**Opik specifically** (mentioned in your book list):
- Open-source LLM observability (Comet ML)
- Experiment tracking + prompt management + tracing
- Good for: teams that want self-hosted, integrated eval + observability

## 11.5 Anomaly Detection for LLM Systems

Unlike traditional services, LLM failures are *semantic*, not just HTTP errors:

| Failure Type | Detection Method |
|---|---|
| Model returning empty/short responses | Response length distribution monitoring |
| Hallucination spike | Automated faithfulness scoring on sampled traffic |
| Prompt injection attack | Pattern matching + anomaly on tool call count |
| Latency degradation | Rolling P95 vs. baseline alert |
| Cost spike | Token count anomaly detection |
| Repetition loop | Detect high n-gram repetition in output |

## 11.6 Feedback Loops: Closing the Loop

```
Production Traffic
       ↓
   Sampling Layer (1–5% of requests)
       ↓
   Automated Evaluation (LLM-as-Judge)
       ↓
   Human Review Queue (lowest scoring samples)
       ↓
   Labeled Dataset (add failures to eval set)
       ↓
   Model/Prompt Improvement
       ↓
   Deploy → (back to production)
```

This is the **continuous improvement flywheel**. Without it, your system degrades silently as the world changes and user patterns evolve.

---

# Appendix: Production Checklist

## Before Deploying an LLM System

### Model Selection
- [ ] Benchmarked on your specific task, not just MMLU/general
- [ ] Latency tested at P95 under expected load
- [ ] Tool-calling reliability validated with your tool schemas
- [ ] Cost estimate per 1M requests calculated

### RAG (if applicable)
- [ ] Chunking strategy chosen based on document type
- [ ] Hybrid retrieval (dense + sparse) implemented
- [ ] Reranker added to pipeline
- [ ] Evaluated with RAGAS metrics

### Agent System (if applicable)
- [ ] Max iteration limit set
- [ ] Timeout per tool call set
- [ ] Tool count < 20 in context
- [ ] All tool outputs sanitized before context injection
- [ ] Asynchronous execution for tasks > 30s

### Deployment
- [ ] GPU memory utilization validated under peak load
- [ ] KV cache size estimated and memory headroom confirmed
- [ ] Prefix caching configured for shared system prompts
- [ ] Autoscaling configured with time buffer for GPU provisioning
- [ ] Streaming enabled for interactive use cases

### Observability
- [ ] Full request/response logging with PII masking
- [ ] Distributed tracing across all components
- [ ] LLM-as-Judge sampling configured (1–5%)
- [ ] Cost tracking per request/user/feature
- [ ] Alert thresholds set for latency, error rate, cost

### Evaluation
- [ ] Eval set reflects production distribution
- [ ] Regression test suite runs on every deployment
- [ ] Human review process defined for flagged samples
- [ ] Red teaming conducted (prompt injection, jailbreak)

---

*Guide version: 1.0 | Focus: Production AI Engineering | Last updated: June 2026*

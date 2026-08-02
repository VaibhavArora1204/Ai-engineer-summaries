# AI Systems Engineering — Unified Knowledge Base
### Production LLM Systems: From Behavior to Architecture

> Consolidated from four evolving perspectives into a single interconnected reference.
> Goal: Understand LLM behavior deeply, then apply that understanding to wrap LLMs in production-grade AI systems.

---

## How to Use This Document

This is not a tutorial. It is structured as a **systems engineering reference** — every concept is introduced through the problem it solves, what it depends on, and what depends on it. Read linearly for the full picture, or jump to any section and follow the dependency links.

---

# Part 0 — Foundations: Mental Models of LLM Behavior

Before engineering systems around LLMs, you must internalize how they actually work — not mathematically, but mechanically. Every production decision traces back to these models.

### The Seven Mental Models

| Mental Model | What It Means | Engineering Consequence |
|---|---|---|
| **LLM as probabilistic inference engine** | Given input tokens, the model computes a probability distribution over next tokens. It does not "know" things — it assigns likelihoods. | You cannot guarantee correctness. You must design for uncertainty: evaluation loops, fallbacks, guardrails. |
| **Prompt as temporary program** | The prompt is the only "code" the model executes. It has no persistent state, no memory, no learned behavior between calls. | Prompt changes ARE code changes. They need versioning, testing, CI/CD, rollback — exactly like software deployments. |
| **Context as working memory** | The context window is the model's entire universe for that request. Anything not in the context does not exist for the model. | Context engineering is not optional. What you put in, how you order it, and how much you include directly determines output quality. |
| **KV cache as execution state** | During generation, the model builds a key-value cache representing its "understanding" of the context so far. This is the computational bottleneck. | KV cache size drives GPU memory consumption, limits batch sizes, and determines serving throughput. Every optimization in serving touches KV cache. |
| **Tokens as compute currency** | Every token consumed or generated costs compute, memory, latency, and money. Input tokens cost during prefill; output tokens cost during decode. | Token budgeting is not premature optimization — it is fundamental capacity planning. |
| **Attention as information routing** | The attention mechanism decides which parts of the context influence each generated token. It is not uniform — information in the middle of long contexts gets less attention ("lost in the middle"). | Context ordering matters. Critical information should be placed at the beginning or end. Retrieval ordering strategies exist specifically because of this behavior. |
| **Sampling as probabilistic search** | Temperature, top-p, top-k, and repetition penalties shape the search through probability space. They don't make the model "more creative" or "more precise" — they reshape the distribution. | Sampling parameters are production configuration, not arbitrary knobs. Different tasks need different sampling strategies, and they interact with prompt design. |

### Why These Models Matter for Systems Engineering

Every system you build wraps an LLM. The LLM's behavior under different conditions — long contexts, ambiguous prompts, adversarial inputs, high concurrency — is determined by these properties. If your system design contradicts how the LLM actually works, no amount of infrastructure will save you.

---

# Part 1 — Concept Dependency Graph

This is the map. Every major concept in this document connects to others. Before learning any topic, understand where it sits.

```
                    ┌─────────────────────────────────────────────┐
                    │          BUSINESS CONSTRAINTS                │
                    │  (SLAs, cost targets, compliance, latency)   │
                    └──────────┬──────────────────┬───────────────┘
                               │                  │
                    ┌──────────▼──────┐  ┌────────▼────────┐
                    │  COST ENGINEERING │  │  PLATFORM OPS   │
                    │  token economics  │  │  SLIs/SLOs      │
                    │  GPU economics    │  │  incident mgmt  │
                    │  build vs buy     │  │  capacity plan   │
                    └──────┬───────────┘  └────────┬────────┘
                           │                       │
              ┌────────────▼───────────────────────▼──────────┐
              │              AI PLATFORM ARCHITECTURE           │
              │  serving │ routing │ retrieval │ evaluation     │
              │  prompt registry │ observability │ deployment   │
              └──┬────────┬──────────┬──────────┬─────────────┘
                 │        │          │          │
      ┌──────────▼──┐ ┌──▼────────┐ │  ┌───────▼──────────┐
      │MODEL SERVING │ │  ROUTING  │ │  │  EVALUATION &     │
      │ vLLM, TGI,   │ │ quality   │ │  │  OBSERVABILITY    │
      │ TRT-LLM,     │ │ cost      │ │  │  metrics, traces  │
      │ SGLang       │ │ latency   │ │  │  eval flywheel    │
      │              │ │ cascade   │ │  │                   │
      │ KV cache ◄───┤ │           │ │  │                   │
      │ batching     │ └───────────┘ │  └───────────────────┘
      │ parallelism  │               │
      │ scheduling   │    ┌──────────▼──────────┐
      └──────────────┘    │  CONTEXT ENGINEERING │
                          │  retrieval, ranking  │
                          │  memory, compression │
                          │  chunk engineering   │
                          │  grounding           │
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼───────────┐
                          │  PROMPT MANAGEMENT    │
                          │  versioning, CI/CD    │
                          │  governance, rollback │
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼───────────┐
                          │  LLM BEHAVIOR         │
                          │  (mental models above) │
                          └────────────────────────┘
```

**Reading the graph bottom-up:** LLM behavior constrains prompt design. Prompt design shapes context engineering. Context engineering feeds into retrieval/ranking quality. The serving layer determines how fast and at what cost you can execute all of this. Routing decides which model or path handles each request. Evaluation tells you if any of it is working. Platform ops keeps it all alive. Cost and business constraints bound every decision.

**Key insight:** Optimizing any single layer without understanding its dependencies creates problems elsewhere. Faster serving means nothing if your context is garbage. Perfect retrieval is wasted on a bad prompt. Beautiful architecture fails without evaluation.

---

# Part 2 — Model Serving

> **Depends on:** LLM behavior (KV cache, tokens as compute, attention)
> **Depended on by:** Routing, cost engineering, platform ops, capacity planning
> **Problem it optimizes:** Turn a model artifact into a service that can handle concurrent requests at target latency and cost
> **Constraints it introduces:** GPU memory limits, cold start latency, batching tradeoffs

### Why Serving Is Hard

A naive LLM deployment handles one request at a time, wastes GPU cycles during token generation (which is memory-bound, not compute-bound during decode), and allocates memory inefficiently. Production serving engines exist because the gap between "model works on my laptop" and "model serves 1000 concurrent users at P99 < 2s" is enormous.

### Core Serving Concepts

#### KV Cache Management
- **What:** During generation, each transformer layer stores key-value pairs for all tokens processed so far. This is the model's "memory" of the context.
- **Problem:** KV cache grows linearly with sequence length × batch size × layers × heads. A 70B model with 4K context can consume 10+ GB of KV cache per request.
- **Why it matters:** KV cache is the primary constraint on how many requests you can batch together. It directly determines your throughput ceiling.

#### PagedAttention (pioneered by vLLM)
- **Problem it solves:** Traditional KV cache allocation is contiguous — you must pre-allocate the maximum possible sequence length for every request, wasting memory on shorter sequences.
- **How it works:** Borrows the OS virtual memory concept. KV cache is stored in non-contiguous "pages" mapped by a page table. Memory is allocated on-demand as the sequence grows.
- **What it enables:** ~2-4x improvement in memory utilization, which directly translates to higher batch sizes and throughput.
- **What breaks:** Page table overhead, memory fragmentation over time, complexity in distributed settings.

#### Continuous Batching
- **Problem:** Static batching waits for all requests in a batch to finish before starting new ones. Short requests wait for long ones → wasted GPU cycles.
- **How:** Requests are inserted/removed from the batch at every iteration step. The GPU is never idle waiting for a long generation to complete.
- **Tradeoff:** Increased scheduler complexity, slightly higher per-token overhead, but dramatically better throughput and latency for mixed workloads.

#### Chunked Prefill
- **Problem:** Long prefill (processing the input prompt) blocks the GPU for hundreds of milliseconds, stalling decode for other in-flight requests.
- **How:** The prefill is broken into chunks interleaved with decode steps for other requests.
- **Tradeoff:** Slightly longer total prefill time for the individual request, but much better P99 latency across the batch.

#### Speculative Decoding
- **Problem:** Decode is memory-bandwidth-bound — the GPU is underutilized because it's generating one token at a time.
- **How:** A small "draft" model generates several candidate tokens quickly. The large model verifies them in parallel (which IS compute-efficient because it's essentially a prefill step). Accepted tokens skip expensive decode steps.
- **Tradeoff:** Requires maintaining a draft model, acceptance rate varies by task, adds complexity. Best for scenarios where the draft model can predict well (code completion, formulaic text).

#### Prefix Caching
- **Problem:** Many requests share common prefixes (system prompts, few-shot examples). Recomputing their KV cache each time wastes compute.
- **How:** Cache the KV state for common prefixes. New requests that match a cached prefix skip prefill for that portion.
- **When it matters:** High-volume applications with stable system prompts. Can reduce TTFT (time to first token) dramatically.

#### Parallelism Strategies
| Strategy | What It Splits | When to Use |
|---|---|---|
| **Tensor parallelism** | Individual layers across GPUs | Model doesn't fit on one GPU. Low latency requirement. |
| **Pipeline parallelism** | Groups of layers across GPUs | Optimizing throughput over latency. Allows micro-batching between stages. |
| **Expert parallelism** | MoE experts across GPUs | Mixture-of-Experts models (Mixtral, etc.). |

### Serving Engine Decision Map

| Engine | Best For | Avoid When |
|---|---|---|
| **vLLM** | General-purpose high-throughput serving. Strong community. PagedAttention pioneer. | You need maximum low-latency optimization for NVIDIA-specific deployments. |
| **SGLang** | Complex LLM programs with structured generation, constrained decoding, multi-turn. | Simple single-turn inference at scale. |
| **TensorRT-LLM** | Maximum NVIDIA GPU performance. Production deployments where every ms matters. | Non-NVIDIA hardware. Rapid iteration (compilation overhead). |
| **TGI** | Hugging Face ecosystem. Quick deployment. Good defaults. | Need to squeeze last 20% of performance. |
| **llama.cpp** | CPU/edge inference. Apple Silicon. Quantized models. Developer experimentation. | High-throughput GPU serving. |
| **Triton Inference Server** | Multi-model, multi-framework serving. Ensemble pipelines. | Single-model simple deployments (overkill). |
| **Ollama** | Developer experimentation. Quick local model testing. | Anything production. |

### What a Staff Engineer Would Notice

- Most serving performance problems are **memory problems**, not compute problems. Check KV cache utilization before adding GPUs.
- TTFT and decode latency have **different bottlenecks** — TTFT is compute-bound (prefill), decode is memory-bandwidth-bound. Optimizing one doesn't help the other.
- Cold starts kill autoscaling. Model loading can take 30-120 seconds. Pre-warm replicas.
- GPU utilization metrics lie. 90% GPU utilization can mean the GPU is busy doing memory transfers, not useful compute. Profile with `nsys` or `py-spy`, not just `nvidia-smi`.

---

# Part 3 — Routing

> **Depends on:** Model serving (you need multiple models/endpoints to route between), evaluation (routing decisions need quality signals)
> **Depended on by:** Cost engineering, platform ops, system design
> **Problem it optimizes:** Not every request needs the same model, latency, or cost profile. Route each request to the optimal handler.
> **Constraints it introduces:** Router latency, router accuracy, added failure modes

### Routing as an Engineering Discipline

Routing exists because production systems serve diverse queries. A simple factual lookup does not need GPT-4-class reasoning. A complex multi-step analysis does not belong on a cheap, fast model. Without routing, you either overpay (send everything to the best model) or underdeliver (send everything to the cheapest).

### Routing Strategies

| Strategy | Route By | Trade Off |
|---|---|---|
| **Quality routing** | Estimated task difficulty → stronger model for harder tasks | Requires a quality classifier (itself an ML problem). Wrong classification = wrong model. |
| **Cost routing** | Budget constraints → cheapest model that meets quality threshold | Needs quality feedback loops. Cheapest model today may degrade tomorrow. |
| **Latency routing** | Response time requirements → fastest available model | Fast ≠ good. Must pair with quality thresholds. |
| **Intent routing** | Classified intent → specialized model/prompt per intent | Intent classifier accuracy is the ceiling. Misclassified intent = completely wrong behavior. |
| **Confidence routing** | Model's self-assessed confidence → escalate low-confidence to stronger model | Confidence ≠ correctness (models are confidently wrong). Calibration is essential. |
| **Cascade routing** | Try cheap first → escalate on failure/low quality | Adds latency on escalation. Need fast failure detection. |

### Router Implementation Patterns

**Embedding routers:** Encode the query, compare against cluster centroids or trained embeddings. Fast (~5ms), but coarse.

**LLM routers:** Use a small LLM to classify/route. More accurate, but adds 50-200ms of latency and its own cost.

**Rule-based routers:** Pattern matching, token count thresholds, user tier. Zero ML overhead, but brittle.

### Traffic Management

- **Shadow routing:** Send traffic to new model in parallel, compare results, don't serve the shadow response. Essential for safe model migrations.
- **Canary routing:** Route 1-5% of traffic to new model/config, monitor metrics, gradually increase.
- **A/B routing:** Split traffic for experimentation. Requires statistical rigor — LLM output variance is high.

### What Breaks

- **Router becomes the bottleneck.** A 200ms router call on every request adds 200ms to your P50. Router must be fast.
- **Cascades stack latency.** If your cascade is small → medium → large, a hard query hits all three sequentially.
- **Router training data goes stale.** Query distributions shift. Retrain or recalibrate continuously.
- **Fallback storms.** If the primary route fails and all traffic hits the fallback simultaneously, the fallback overloads.

---

# Part 4 — Context Engineering

> **Depends on:** LLM behavior (attention mechanics, context as working memory, lost-in-the-middle), prompt management
> **Depended on by:** Output quality, hallucination rate, cost, latency
> **Problem it optimizes:** Given a limited context window, maximize the information density and relevance of what the model sees
> **Constraints it introduces:** Retrieval latency, token cost, ordering sensitivity

### Why Context Engineering Is Not "Just RAG"

RAG (Retrieval-Augmented Generation) is one tool within context engineering. Context engineering is the discipline of constructing the optimal input for an LLM given the task, constraints, and available information. It encompasses:

1. **What to retrieve** (retrieval strategy)
2. **How much to retrieve** (token budgeting)
3. **How to order it** (attention-aware placement)
4. **How to compress it** (summarization, extraction)
5. **What to remember** (memory architecture)
6. **How to validate it** (grounding, citation)

### Retrieval Stack

```
User Query
    │
    ▼
┌──────────────┐     ┌──────────────────┐
│ Query         │     │ Multi-query       │
│ Understanding │────▶│ Expansion         │
└──────┬───────┘     │ (HyDE, sub-queries)│
       │              └────────┬──────────┘
       ▼                       ▼
┌──────────────────────────────────┐
│        Vector Search              │
│  (embedding similarity)          │
│  + Keyword Search (BM25/hybrid)  │
└──────────────┬───────────────────┘
               │  top-K candidates
               ▼
┌──────────────────────┐
│     Reranking         │
│  (cross-encoder or    │
│   LLM-based reranker) │
└──────────┬───────────┘
           │  top-N reranked
           ▼
┌──────────────────────┐
│  Context Construction │
│  ordering, budgeting  │
│  dedup, compression   │
└──────────┬───────────┘
           │
           ▼
      [Final Prompt]
```

### Retrieval Strategies & When They Matter

| Strategy | What It Does | When to Use |
|---|---|---|
| **HyDE** (Hypothetical Document Embeddings) | Generate a hypothetical answer, embed that, search with it | Query-document vocabulary mismatch is high |
| **Multi-query retrieval** | Rephrase query from multiple angles, retrieve for each, merge | Ambiguous or complex queries |
| **Parent-child retrieval** | Index small chunks, retrieve them, but return the parent document | Need precise matching but full context |
| **GraphRAG** | Build a knowledge graph from documents, traverse it during retrieval | Complex multi-hop reasoning over interconnected facts |
| **Reciprocal rank fusion** | Merge results from multiple retrieval methods by combining rank positions | Hybrid search (vector + keyword + metadata) |
| **Self-RAG / CRAG** | Model decides when retrieval is needed and evaluates retrieval quality | Reduce unnecessary retrieval; improve retrieval quality |

### Context Construction Principles

1. **Lost-in-the-middle:** Place the most critical information at the START and END of the context. Information in the middle receives less attention. This is not a theory — it is measured behavior in every production LLM.

2. **Token budgeting:** Decide upfront: of your context window (say 128K), how much goes to system prompt? Retrieved documents? Conversation history? Generation headroom? This is not flexible at runtime — it's an architectural decision.

3. **Compression strategies:**
   - **Extractive summarization:** Pull key sentences. Fast, preserves original phrasing, but may miss synthesis.
   - **Abstractive summarization:** Generate a summary. Better compression ratio, but risks introducing errors.
   - **Recursive summarization:** Summarize chunks, then summarize summaries. For very large document sets.

4. **Chunk engineering:** How you split documents determines retrieval quality. Too small → loss of context. Too large → diluted relevance and wasted tokens. Chunk size, overlap, and boundary strategy (sentence, paragraph, semantic) are engineering decisions with measurable impact.

### Memory Architecture

| Memory Type | Scope | Implementation |
|---|---|---|
| **Working memory** | Single request | The context window itself |
| **Short-term memory** | Conversation/session | Stored conversation history, sliding window or summarized |
| **Long-term memory** | Cross-session, per-user | Vector DB or structured store of past interactions, preferences, facts |

### What a Staff Engineer Would Notice

- Retrieval quality is the **highest-leverage optimization** in most RAG systems. Improving retrieval precision from 60% to 80% often matters more than switching models.
- Rerankers add 50-200ms latency but typically improve downstream quality more than any other single component. Always benchmark with and without.
- Metadata filtering before vector search (date ranges, document types, access control) is cheaper than retrieving broadly and filtering later.
- If your retrieval returns 10 chunks and 7 are irrelevant, you're paying token cost for noise that actively degrades output quality.

---

# Part 5 — Prompt Management

> **Depends on:** LLM behavior (prompt as temporary program), context engineering
> **Depended on by:** Output quality, system reliability, evaluation
> **Problem it optimizes:** Treat prompts as production code — versionable, testable, auditable, rollbackable
> **Constraints it introduces:** Governance overhead, testing complexity, regression risk

### Prompt Lifecycle

```
Author → Review → Test → Stage → Deploy → Monitor → Iterate
   │                                           │
   └────────────────── Rollback ◄──────────────┘
```

### Core Practices

| Practice | What It Is | Why It Matters |
|---|---|---|
| **Prompt repository** | Centralized store for all prompts with metadata | Without this, prompts live in code, spreadsheets, Slack messages. Impossible to audit. |
| **Versioning** | Every prompt change creates a new version with diff | A single word change can cause regressions. You need to know what changed and when. |
| **Templates + variables** | Separate static prompt structure from dynamic content | Enables testing the template independently from the data pipeline. |
| **Golden test sets** | Curated input/output pairs that define expected behavior | Regression detection. If a prompt change breaks goldens, it doesn't ship. |
| **Prompt CI/CD** | Automated evaluation on every prompt change | Same principle as code CI. Prompt changes are code changes. |
| **Prompt diffing** | Show what changed between prompt versions | Essential for debugging regressions. "The model got worse" → which prompt version changed? |
| **Rollback** | Revert to previous prompt version instantly | Production incidents caused by bad prompts need immediate mitigation, not debugging. |
| **Prompt observability** | Track which prompt version produced which output | Without this, you cannot correlate quality changes with prompt changes. |

### Prompt Optimization Tools

- **DSPy:** Treats prompts as differentiable programs. Automatically optimizes prompt structure, few-shot examples, and instructions against an evaluation metric. Useful when manual prompt engineering plateaus.
- **Automatic optimization:** Use LLMs to generate prompt variations, evaluate against golden sets, select winners. Essentially automated A/B testing for prompts.

### What Breaks

- **Prompt-model coupling:** A prompt optimized for GPT-4 may fail on Claude or Llama. Prompts are coupled to model behavior. Model upgrades require prompt re-evaluation.
- **Regression without CI:** A prompt "improvement" for one use case degrades another. Without golden test coverage, you discover this in production.
- **Template injection:** User input that manipulates the template structure. Sanitization and input validation are security requirements.

---

# Part 6 — Cost Engineering

> **Depends on:** Model serving (GPU costs), routing (model selection costs), context engineering (token costs)
> **Depended on by:** Business viability, architecture decisions, build vs buy
> **Problem it optimizes:** Deliver acceptable quality at sustainable cost
> **Constraints it introduces:** Quality ceilings, latency floors, operational complexity

### The Cost Stack

```
Total Cost Per Request =
    Token cost (input + output)
  + GPU compute cost (amortized)
  + Retrieval cost (embedding + search + reranker)
  + Infrastructure cost (networking, storage, orchestration)
  + Operational cost (monitoring, on-call, maintenance)
```

### Key Levers

| Lever | What It Does | Tradeoff |
|---|---|---|
| **Routing to cheaper models** | Send easy queries to small/cheap models | Quality risk on misrouted queries |
| **Caching** | Serve identical/similar requests from cache | Staleness, cache invalidation complexity |
| **Prompt optimization** | Reduce token count without losing quality | Engineering effort, fragility |
| **Quantization** | Reduce model precision (FP16 → INT8 → INT4) | Quality degradation, especially on reasoning tasks |
| **Batching** | Amortize GPU overhead across requests | Latency increase for individual requests |
| **Context pruning** | Send fewer, more relevant tokens | Risk of losing important context |
| **Self-host vs API** | Fixed GPU cost vs per-token API cost | Engineering effort, maintenance burden, flexibility |

### Cache Hierarchy

```
L1: Exact match cache (same prompt → same response)
L2: Semantic cache (similar prompt → cached response)
L3: Prefix cache (shared system prompt KV cache)
L4: Retrieval cache (cached search results)
```

Each level has different hit rates, invalidation strategies, and staleness risks.

### Build vs Buy Decision Framework

| Factor | Self-Host | API Provider | Managed Cloud |
|---|---|---|---|
| **Upfront cost** | High (GPUs, infra) | None | Medium |
| **Per-request cost** | Low at scale | Linear with usage | Medium |
| **Engineering effort** | High | Low | Medium |
| **Customization** | Full | Limited | Moderate |
| **Compliance** | Full control | Depends on provider | Shared responsibility |
| **Vendor lock-in** | None | High | Medium |
| **Break-even point** | ~$10K-50K/month in API spend | Below that threshold | Varies |

### What a Staff Engineer Would Notice

- The most expensive part of most LLM systems is not the LLM call — it's the **retrieval pipeline** (embedding generation, vector search, reranking) when measured per-request at scale.
- Token cost drops ~50% per year across API providers. Architectures optimized purely for token savings today may be over-engineered tomorrow.
- GPU spot instances can save 60-70% but introduce preemption risk. Only use for batch/offline workloads or with robust checkpointing.

---

# Part 7 — Evaluation & Observability

> **Depends on:** Every other layer (you evaluate the entire system, not just components)
> **Depended on by:** Routing (quality signals), prompt management (regression detection), platform ops (alerting)
> **Problem it optimizes:** Know whether your system is working, and detect when it stops
> **Constraints it introduces:** Evaluation latency, cost of LLM-as-judge, definition of "quality"

### Production Metrics Taxonomy

#### Serving Metrics (Infrastructure Health)
| Metric | What It Measures | Alert When |
|---|---|---|
| **TTFT** (Time to First Token) | Prefill latency | P95 > your target (typically 500ms-2s) |
| **Tokens/sec** (decode throughput) | Generation speed | Below model's theoretical throughput by >30% |
| **P50/P95/P99 latency** | End-to-end response time distribution | P99 exceeds SLO |
| **GPU utilization** | Effective GPU use | Sustained >90% (approaching limits) or <40% (wasting money) |
| **Queue depth** | Request backlog | Growing faster than draining |
| **Cache hit ratio** | Cache effectiveness | Below expected baseline (varies by workload) |

#### Quality Metrics (Output Correctness)
| Metric | What It Measures | How It's Measured |
|---|---|---|
| **Groundedness** | Are claims supported by provided context? | LLM-as-judge or NLI models |
| **Faithfulness** | Does the output contradict the context? | Claim decomposition + entailment checking |
| **Hallucination rate** | Fraction of outputs containing unsupported claims | Automated detection + human sampling |
| **Citation accuracy** | Do cited sources actually support the claims? | Automated source verification |
| **Tool success rate** | Did tool calls execute correctly? | Execution logs + result validation |
| **Agent completion rate** | Did the agent achieve its goal? | Task-specific success criteria |

#### Retrieval Metrics (Context Quality)
| Metric | What It Measures |
|---|---|
| **Precision@K** | Of K retrieved docs, how many are relevant? |
| **Recall** | Of all relevant docs, how many were retrieved? |
| **MRR** (Mean Reciprocal Rank) | How high is the first relevant result? |
| **nDCG** | Quality of the full ranking (position-weighted) |
| **Reranker gain** | How much did reranking improve retrieval quality? |

### The Evaluation Flywheel

This is how mature AI teams continuously improve:

```
Production traffic
       │
       ▼
Failure clustering ──── "What categories of failures are we seeing?"
       │
       ▼
Golden dataset expansion ── Add representative failures as test cases
       │
       ▼
Regression suite ──── Run all prompt/model changes against goldens
       │
       ▼
Offline evaluation ──── LLM-as-judge, human review, automated metrics
       │
       ▼
Shadow deployment ──── Run new version in parallel, compare outputs
       │
       ▼
Canary rollout ──── 1-5% traffic, monitor quality metrics
       │
       ▼
Full production ──── Monitor, collect new failures
       │
       └────── repeat ──▶
```

### Observability Stack

Every request should produce a trace containing:
- Request ID, timestamp, user/session ID
- Prompt version used
- Model + model version
- Retrieval results (query, chunks retrieved, reranker scores)
- Full context assembled (or hash + token count)
- Model response
- Latency breakdown (retrieval, context construction, prefill, decode)
- Token counts (input, output)
- Quality scores (if evaluated)
- Cost

Tools: Langfuse, Phoenix (Arize), OpenTelemetry, custom pipelines into your data warehouse.

---

# Part 8 — Platform Operations

> **Depends on:** All infrastructure layers
> **Depended on by:** Business reliability commitments
> **Problem it optimizes:** Keep the system running, recoverable, and evolvable
> **Constraints it introduces:** Operational overhead, on-call burden, process friction

### SLIs, SLOs, SLAs

| Concept | Definition | Example |
|---|---|---|
| **SLI** (Service Level Indicator) | The metric you measure | P95 latency, error rate, quality score |
| **SLO** (Service Level Objective) | Your internal target | P95 latency < 3s for 99.5% of requests |
| **SLA** (Service Level Agreement) | Your contractual commitment to customers | 99.9% availability with financial penalties |

**Error budgets:** If your SLO is 99.5% success rate, you have a 0.5% error budget. When the budget is exhausted, freeze deployments and fix reliability. This creates natural tension between feature velocity and reliability.

### Deployment Strategies

| Strategy | How It Works | Risk Level | Use When |
|---|---|---|---|
| **Blue-green** | Two identical environments, switch traffic atomically | Low | Critical services, need instant rollback |
| **Canary** | Route small % to new version, monitor, gradually increase | Low | Model/prompt changes, need quality validation |
| **Shadow** | New version processes traffic in parallel, results discarded | Lowest | Pre-deployment validation, no user impact |
| **Rolling** | Gradually replace instances | Medium | Infrastructure changes |

### Capacity Planning

Questions you must answer:
- **How many GPUs?** = (target throughput × avg tokens per request) ÷ (tokens/sec per GPU × batch efficiency)
- **When to autoscale?** = Queue depth exceeds threshold OR GPU utilization sustained above target
- **How much cache?** = Working set size × (1 / target hit ratio) × safety margin
- **How many concurrent users?** = (available GPU memory ÷ KV cache per request) × num GPUs × parallelism factor

### Failure Taxonomy

| Failure Category | Symptoms | First Check |
|---|---|---|
| **Retrieval failure** | Irrelevant outputs, hallucinations increase | Retrieval precision metrics, embedding model health |
| **Prompt regression** | Quality drop correlated with deployment | Prompt version diff, golden test results |
| **Serving failure** | Latency spike, timeouts, OOM | GPU memory, KV cache utilization, queue depth |
| **Cache failure** | Latency increase, cost spike | Cache hit ratio, cache service health |
| **Routing failure** | Wrong model for query type | Router accuracy metrics, traffic distribution |
| **Tool failure** | Agent tasks incomplete | Tool execution logs, API health checks |
| **Hallucination spike** | Factually incorrect outputs increase | Retrieval quality, context construction, model behavior |

### Incident Response Pattern

```
1. DETECT   ─── Alert fires (automated metric threshold breach)
2. TRIAGE   ─── Which component? Check: serving → routing → retrieval → prompt
3. MITIGATE ─── Rollback prompt? Redirect traffic? Scale up? Disable feature?
4. DIAGNOSE ─── Root cause analysis using traces, logs, metric correlations
5. RESOLVE  ─── Fix + add to regression suite + update runbook
6. REVIEW   ─── Postmortem: timeline, root cause, impact, prevention
```

---

# Part 9 — AI System Design Patterns

> **Depends on:** All previous layers
> **Problem it optimizes:** Compose the layers into complete, production-ready systems

### Reference Architecture: Enterprise RAG

```
┌──────────────────────────────────────────────────┐
│                    API Gateway                     │
│          (auth, rate limit, request logging)        │
└──────────────┬──────────────────┬─────────────────┘
               │                  │
    ┌──────────▼──────┐  ┌───────▼────────┐
    │  Intent Router   │  │  Cache Layer    │
    │  (classify task) │  │  (exact+semantic)│
    └──────┬──────────┘  └───────┬────────┘
           │ cache miss          │ cache hit
           ▼                     │
    ┌─────────────────┐          │
    │ Query Processing │          │
    │ - expansion      │          │
    │ - rewriting      │          │
    │ - decomposition  │          │
    └──────┬──────────┘          │
           ▼                     │
    ┌─────────────────┐          │
    │ Retrieval        │          │
    │ - vector search  │          │
    │ - keyword search │          │
    │ - metadata filter│          │
    └──────┬──────────┘          │
           ▼                     │
    ┌─────────────────┐          │
    │ Reranking        │          │
    └──────┬──────────┘          │
           ▼                     │
    ┌─────────────────┐          │
    │ Context Assembly │          │
    │ - budget, order  │          │
    │ - compress       │          │
    └──────┬──────────┘          │
           ▼                     │
    ┌─────────────────┐          │
    │ Prompt Assembly  │          │
    │ (template+context│          │
    │  +history)       │          │
    └──────┬──────────┘          │
           ▼                     │
    ┌─────────────────┐          │
    │ LLM Serving      │◄─────── │
    │ (model inference) │         │
    └──────┬──────────┘          │
           ▼                     ▼
    ┌──────────────────────────────┐
    │ Response Processing           │
    │ - guardrails, citation check  │
    │ - formatting, streaming       │
    └──────────────┬───────────────┘
                   ▼
    ┌──────────────────────────────┐
    │ Observability Pipeline        │
    │ traces, metrics, eval scores  │
    └──────────────────────────────┘
```

### Design Review Checklist (Apply to Any System)

- [ ] **Scalability:** What's the bottleneck at 10x traffic? 100x?
- [ ] **Reliability:** What happens when each component fails? Is there a fallback?
- [ ] **Observability:** Can you diagnose a quality drop to a specific component within 15 minutes?
- [ ] **Maintainability:** Can a new team member understand the architecture in a day?
- [ ] **Security:** Where does user data flow? What's the blast radius of a compromise?
- [ ] **Cost:** What's the cost per request? How does it scale with traffic?
- [ ] **Extensibility:** Can you add a new model, retrieval source, or feature without rewriting?

### Decision Playbooks

#### Fine-tuning vs Prompt Engineering vs RAG

```
Is the knowledge static and small?
  ├─ YES → Prompt engineering (few-shot examples in prompt)
  └─ NO
      Is the knowledge large or frequently updated?
        ├─ YES → RAG
        └─ NO
            Does the model need to learn a new behavior/style/format?
              ├─ YES → Fine-tuning (+ RAG if knowledge is also needed)
              └─ NO → Prompt engineering with better instructions
```

#### API vs Self-Host

```
Monthly API spend > $10-50K?
  ├─ NO → Use API (engineering cost of self-hosting exceeds savings)
  └─ YES
      Do you need custom models or full data control?
        ├─ YES → Self-host
        └─ NO
            Is latency critical and are you in a single region?
              ├─ YES → Self-host (eliminate network hop to API provider)
              └─ NO → API (let provider handle ops)
```

#### Single Agent vs Workflow vs Multi-Agent

```
Is the task a single-turn transformation?
  ├─ YES → Single LLM call (no agent needed)
  └─ NO
      Is the task a fixed sequence of steps?
        ├─ YES → Workflow engine (deterministic orchestration)
        └─ NO
            Does the task require dynamic planning and tool use?
              ├─ YES → Single agent with tools
              └─ Still stuck?
                  Does it require multiple specialized capabilities?
                    ├─ YES → Multi-agent (but accept the complexity cost)
                    └─ NO → Simplify the problem decomposition
```

---

# Part 10 — Change Management & Evolution

> **Depends on:** Platform ops, evaluation, prompt management
> **Problem it optimizes:** Evolve the system safely without breaking production
> **Constraints it introduces:** Migration overhead, backwards compatibility requirements

### Migration Strategies

| Migration | Risk | Strategy |
|---|---|---|
| **Model upgrade** | Prompt-model coupling, quality regression | Shadow deploy → eval against goldens → canary → full rollout |
| **Embedding model change** | All vectors must be re-embedded | Dual-write period: query both old and new indices, compare, cutover |
| **Vector DB migration** | Data integrity, query compatibility | Build new index in parallel, shadow query, validate recall parity |
| **Prompt migration** | Quality regression | Version, A/B test, monitor golden set metrics |

### Data Lifecycle

Everything in a production AI system has a lifecycle:

| Data | Creation | Active Use | Archival/Deletion |
|---|---|---|---|
| **Prompts** | Authored by engineers | Served to models | Archived on version rollover |
| **Embeddings** | Generated from source docs | Stored in vector DB, queried | Invalidated on source update or model change |
| **KV cache** | Created per-request during prefill | Used during decode | Evicted when request completes (or cached for prefix) |
| **Evaluation data** | Collected from production + human annotation | Used in CI/CD eval | Versioned, never deleted |
| **Feedback** | User thumbs-up/down, corrections | Powers eval flywheel | Feeds fine-tuning datasets |

---

# Part 11 — AI Platform Maturity Model

| Level | Description | Architecture | Monitoring | Team |
|---|---|---|---|---|
| **1 — Prototype** | Single notebook/script, one model, one use case | Monolith, direct API calls | Print statements | 1 engineer |
| **2 — Internal Tool** | Deployed service, specific users, limited scale | Basic API server, simple retrieval | Basic logging, latency tracking | 2-3 engineers |
| **3 — Production Service** | Customer-facing, SLOs, reliability requirements | Serving layer + retrieval + prompt versioning | Dashboards, alerts, traces | 5-8 engineers (AI + infra) |
| **4 — Multi-Tenant Platform** | Multiple use cases, shared infrastructure, internal customers | Platform architecture with routing, shared serving, eval framework | Per-tenant metrics, cost attribution | 10-15 engineers across teams |
| **5 — Enterprise Platform** | Organization-wide, compliance, governance, self-service | Full platform with governance, experimentation, multi-region | Comprehensive observability, automated quality monitoring | 20+ engineers, dedicated platform team |

### What Changes at Each Level

- **1→2:** You need deployment, basic monitoring, and error handling.
- **2→3:** You need evaluation, prompt management, SLOs, on-call, and capacity planning.
- **3→4:** You need routing, cost attribution, multi-tenancy, and a platform team.
- **4→5:** You need governance, compliance, self-service tooling, and enterprise-grade reliability.

**Key insight:** Most production incidents happen during transitions between levels, when the system has outgrown its architecture but the team hasn't rebuilt yet.

---

# Part 12 — Team Responsibilities

| Role | Owns | Interfaces With |
|---|---|---|
| **AI Engineer** | Prompt design, retrieval strategy, evaluation, model selection | Platform eng, product, data eng |
| **Platform Engineer** | Serving infrastructure, routing, scaling, deployment pipelines | AI eng, SRE, infrastructure |
| **MLOps** | Model lifecycle, training pipelines, experiment tracking | AI eng, platform eng, data eng |
| **Infrastructure** | GPU clusters, networking, storage, Kubernetes | Platform eng, SRE |
| **Data Engineering** | Document ingestion, embedding pipelines, data quality | AI eng, platform eng |
| **SRE** | Reliability, incident response, SLOs, runbooks | All engineering teams |
| **Product** | Requirements, success criteria, user feedback | AI eng, design |
| **Security** | Data access controls, prompt injection prevention, compliance | All teams |

---

# Part 13 — Engineering Principles

These principles should inform every decision:

1. **Measure before optimizing.** Intuition about LLM systems is usually wrong. Profile, benchmark, then optimize.
2. **Evaluation beats intuition.** "This prompt feels better" is not evidence. Run it against your golden set.
3. **Every token has a cost.** Compute, latency, money. Be intentional about what enters the context.
4. **Every retrieval stage adds latency.** More stages = better quality, but at what cost? Measure the marginal gain.
5. **Logs beat guesses.** When quality degrades, traces and logs tell you what changed. Without observability, you're guessing.
6. **Prefer simple systems until complexity is justified.** A single well-prompted model beats a poorly-orchestrated multi-agent system.
7. **Optimize bottlenecks, not assumptions.** Profile to find the actual bottleneck. It's rarely where you think.
8. **Reliability is a feature.** Users forgive occasional low quality. They don't forgive downtime.
9. **Prompt changes are code changes.** Version, test, review, rollback.
10. **Design for failure.** Every component will fail. The question is: what happens when it does?

---

# Source Priority

When researching or validating any concept in this document:

### Tier 1 — Official Documentation
vLLM · SGLang · TensorRT-LLM · TGI · llama.cpp · Hugging Face · LangChain · LlamaIndex · LangGraph · Qdrant · Milvus · FAISS · Redis · Langfuse · Phoenix · OpenTelemetry · MLflow · Weights & Biases · Kubernetes · NVIDIA CUDA

### Tier 2 — Engineering Blogs
OpenAI · Anthropic · Google DeepMind · NVIDIA · Meta AI · Microsoft · Hugging Face · Cloudflare · Uber · Netflix · Shopify · Databricks · Modal · Baseten · Anyscale

### Tier 3 — Seminal Papers (Production-Relevant)
Attention Is All You Need · FlashAttention · PagedAttention · Llama 2/3 · Mixtral · ReAct · Toolformer · Gorilla · RAG · Self-RAG · CRAG · RAPTOR · GraphRAG · InstructGPT · DPO · ORPO · GRPO · KTO

---

> *This document consolidates four iterative perspectives on production LLM systems engineering. It is not a tutorial — it is a map of the territory. Use the dependency graph to navigate. Use the mental models to reason. Use the checklists and playbooks to decide. Use the metrics to measure. Build systems that work.*

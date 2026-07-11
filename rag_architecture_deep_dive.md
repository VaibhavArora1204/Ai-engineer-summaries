# RAG Architecture Deep Dive
### Pairing Session — Technical Manual Corpus, CPU Laptop, 65 Chunks

---

## PART 1 — RERANKING

---

### 1.1 Cross-Encoder Internals

**What it computes:**
The model receives `[CLS] query [SEP] chunk [SEP]` as a single token sequence. Both sides attend to each other across every layer (bidirectional, full attention). The final `[CLS]` hidden state is projected by a linear head to a single scalar — a **logit**. This is fundamentally different from bi-encoder (Qdrant vector search), where query and document are encoded independently and compared with cosine similarity.

**Logit vs probability:**
The raw logit is unbounded — you'll see `-3.2`, `1.7`, `0.05`. Passing through sigmoid gives a probability, but **you don't need to**. For ranking, raw logits are monotone with sigmoid, so sort order is identical. Sigmoid only matters if you want to interpret the score as a calibrated confidence (e.g. "70% relevant") — which out-of-the-box reranker models are NOT calibrated to give you. `bge-reranker-base` was fine-tuned on MS MARCO passage pairs; the absolute scores have no inherent meaning on your domain. What's meaningful: **relative rank** and **score gap between rank 1 and rank 2**, not the absolute value.

**When the sort lies:**
Cross-encoder scores can be misleading when:
- Chunk contains the query terms verbatim but in unrelated context (lexical trap). Dense retrieval already degrades on this; cross-encoder sometimes doubles down.
- Chunk is very short (a heading, a note) — it may score high purely due to high token overlap density, not actual informativeness.
- Query is very long and procedural. The model may focus on early tokens and underweight later specifics.

**What to check first when top-1 result is obviously wrong:** Log the raw logit of rank 1 AND rank 2. If gap < 0.3, the model is essentially guessing between them. That's a retrieval problem (both are marginally relevant) not a reranker problem.

---

### 1.2 Alternate Reranking Architectures

---

#### ColBERT — Late Interaction (Multi-Vector)

**What it does internally:**
Instead of one vector per document, ColBERT stores one vector **per token** in the document at index time. At query time, each query token computes max similarity against all document token vectors (MaxSim), and scores are summed:

```
score(q, d) = Σ_{i∈query_tokens} max_{j∈doc_tokens} (qi · dj)
```

This preserves token-level matching granularity while keeping retrieval fast (MIPS per token, not full cross-attention).

**Failure it fixes vs cross-encoder alone:**
Latency at scale. Cross-encoder is O(n) inferences at rerank time; ColBERT compresses to a single ANN pass. Irrelevant at 65 chunks.

**New failure/cost introduced:**
Storage explodes. A 300-char chunk (~60 tokens) × 128-dim vectors = 60 vectors per chunk instead of 1. Qdrant would need a named vector per token, or you'd use a dedicated ColBERT store (Vespa, Weaviate). Also: ColBERT models aren't drop-in replacements — need fine-tuned ColBERT checkpoint, different indexing pipeline entirely.

**When this breaks, check first:** Token vector count explosion from long documents. Per-token storage is a fixed multiplier — if your chunks grow, your index grows proportionally.

**Verdict for your corpus:** Premature. Solves a latency problem you don't have.

---

#### LLM-as-Reranker (Listwise)

**What it does:**
Pass the query + all N candidates to an LLM and ask it to return a ranked list. Listwise approaches (RankGPT, RankLLaMA) give the LLM all candidates in one prompt and ask for a permutation.

**Failure it fixes:**
Captures global coherence — e.g., if chunk 3 is only useful *given* chunk 1 was already retrieved, an LLM can reason about that. Cross-encoder is pairwise, blind to other candidates.

**New failure/cost introduced:**
- Non-determinism: same query, different run, different rank. Catastrophic for regression testing.
- Prompt sensitivity: list order in the prompt biases the output (primacy/recency effects within the LLM's context window — the same lost-in-the-middle you're trying to avoid downstream).
- Cost/latency: API call per request at generation-class token length.
- Output parsing fragility: LLM may refuse to rank, hallucinate a rank, or return partial list.

**When this breaks, check first:** Non-determinism is the first symptom. If answer quality suddenly drops without model/data change, it's the LLM reranker drifting. Requires golden-set regression on every deployment.

**Verdict for your corpus:** Don't touch it. Introduces non-determinism for marginal quality gain on 65 chunks.

---

#### Score Fusion — RRF (Reciprocal Rank Fusion)

**What it does:**
Combines rankings from two independent retrievers (e.g. dense Qdrant + keyword BM25) without needing to normalize scores across systems:

```
RRF_score(chunk) = Σ_r  1 / (k + rank_r(chunk))
```
`k=60` is standard (smoothing constant). Each retriever votes via rank, not raw score. A chunk that ranks #3 in dense AND #5 in BM25 beats one that ranks #1 in dense only.

**Failure it fixes:**
Exact-string queries that dense retrieval weakens on — error codes, part numbers, model identifiers. `E-04` fails embedding similarity if it never appears in training data; BM25 finds it by exact token match.

**New failure/cost introduced:**
- Second retrieval system to run and maintain (Elasticsearch, Typesense, or a local BM25 library like `wink-nlp` or `minisearch`).
- RRF doesn't care about score magnitude — a barely-relevant BM25 result at rank 2 carries same weight as a highly-relevant one. Can introduce noise when one retriever is junk on a query type.
- Non-obvious failure mode: a chunk that dense retrieval ranks #31 (below your TOP_K cutoff) and BM25 ranks #1 gets missed entirely if you apply TOP_K before fusion.

**When this breaks, check first:** Recall@30 on exact-code queries specifically. If BM25 alone retrieves the right chunk but fused result misses it, your TOP_K cutoff is cutting before fusion.

---

### 1.3 Hybrid Dense + BM25 vs Upgrading Reranker — Concrete Argument

**The question:** For a technical manual with error codes and part numbers, is adding BM25 before reranking higher leverage than swapping `bge-reranker-base` for `bge-reranker-large`?

**Yes, and here's why:**

The reranker can only rerank what retrieval gave it. If the dense vector search at TOP_K=30 never retrieves the chunk containing `Error E-04 / Replace Part #BRK-2210`, no reranker — base or large — sees it. The reranker operates on a fixed candidate set. It cannot hallucinate candidates.

Dense embeddings generalize well on semantic queries ("how do I stop the machine"). They are structurally weak on:
- Alphanumeric codes with no semantic neighborhood in the embedding space (`E-04` has no neighbors unless explicitly trained on domain vocab)
- Part numbers that look like noise to a general-purpose embedding model
- Version-specific identifiers (`firmware v2.3.1`)

BM25 has the opposite profile: exact token match, no semantic understanding. The two failure modes are orthogonal — which is exactly when fusion helps.

`bge-reranker-large` vs `bge-reranker-base`: both fail equally on candidates they never receive. The improvement is in cross-encoder quality on semantically ambiguous pairs, which is a second-order problem if your first-order problem is recall failure on exact codes.

**Concrete symptom:** User queries `"E-04 error reset"`. Qdrant returns 30 chunks, none contain `E-04` because the embedding for `E-04` is noisy. Reranker runs on junk inputs and returns junk. Switching to `bge-reranker-large` scores junk chunks slightly differently — still junk. Adding BM25 in parallel retrieves the exact chunk, fusion puts it in the candidate set, cross-encoder reranks it to #1.

**When BM25 is NOT the answer:** If your queries are all paraphrases ("the part that makes noise when turning" → procedure involving a specific component) and none are exact-code lookups, dense retrieval is fine and BM25 adds noise.

**Verdict:** If you have any exact-code or part-number queries in your actual usage — BM25 hybrid is higher leverage than reranker upgrade. Validate by checking which query types are failing before committing.

---

### 1.4 Eval Methodology

**Two separate harnesses — never conflate them:**

| Harness | What it measures | Input | Metric |
|---|---|---|---|
| Retrieval eval | Does the right chunk appear in top-K? | query → chunk IDs | Recall@K, MRR |
| Answer eval | Does the final answer correctly respond? | query → LLM answer | Human / LLM-judge pass/fail |

A retrieval eval passing with answer eval failing means: correct chunks retrieved, generation is broken (prompt, context order, gating threshold).  
A retrieval eval failing means: fix retrieval first, answer eval is meaningless.

**Building the golden set:**
1. Take 20-30 queries representative of real usage — mix semantic paraphrases AND exact-code queries.
2. Manually identify the chunk ID(s) that correctly answer each query.
3. For each query: run retrieval, check if golden chunk IDs appear in top-K, compute MRR (reciprocal rank of first golden hit).

**Recall@K** — fraction of queries where at least one golden chunk is in top-K. Tells you whether retrieval is finding anything useful.

**MRR (Mean Reciprocal Rank)** — average of `1/rank` of first correct hit. Tells you how far down you're burying the right answer. MRR = 1.0 means always rank 1. MRR = 0.33 means the right chunk is on average at rank 3.

**Regression detection:** Run the golden set eval before and after any change to embedding model, chunk size, TOP_K, or reranker. A 5% MRR drop is a signal. This is your canary.

**Threshold for "good enough":** At 65 chunks and TOP_K=30, you're retrieving nearly half the corpus every query. Recall@30 should be near 1.0 on semantically-clear queries. If it isn't, the chunks themselves may be too coarse or the embedding model is wrong for domain.

---

## PART 2 — RESPONSE GENERATION

---

### 2.1 Context Assembly After Rerank

**Lost-in-the-middle effect:**
LLMs (and even humans reading long context) underweight information in the middle of a long prompt. If you pass top-5 reranked chunks in score order (rank 1 first, rank 5 last), chunks 2-4 are in the middle — empirically the most ignored region. Studies on GPT-4 show answer quality measurably degrades when the correct chunk is in positions 3-4 of a 5-chunk context.

**For a procedural/sequential corpus this compounds:**
Your chunks have overlap by design. After reranking, top-5 may be steps 4, 7, 2, 9, 1 from the same procedure — passed in score order, they're incoherent. The LLM may reconstruct the procedure incorrectly or miss the logical dependency ("Step 7 requires you to have done Step 2 first").

**Fix — document-order restoration:**
After rerank cut, sort the surviving chunks by their original document position (chunk ID or filename + position index) before building the context window. You preserve procedural coherence without discarding rerank's relevance filtering.

```
top5_by_score = reranked[:5]
top5_in_doc_order = sort(top5_by_score, key=chunk.position)
```

**When to NOT restore document order:** When top-5 chunks come from multiple documents (multi-document retrieval). Then document-order restoration within each document group, placed by relevance group order, is the right structure.

**What breaks if you skip this:** User asks "how to do X" and the model returns steps in the wrong order, or skips a prerequisite step that was in a deprioritized middle chunk.

---

### 2.2 Relevance Gating

**What it is:**
Before calling the LLM, inspect the top rerank score. If it's below a threshold, return a "no relevant content found" response without calling the LLM at all.

**Why it must happen before streaming opens:**
Once you initiate a streaming response (SSE or chunked HTTP), you've committed to a response contract with the client. You cannot return a 404 or a structured error mid-stream without breaking the client's stream parser. If the gating check happens after the stream opens, you're stuck either silently truncating or sending malformed JSON as a terminal event.

**Threshold design:**
The threshold is domain-specific and not derivable from first principles — it comes from your golden-set eval. Run your golden set, record the rerank score of the correct answer for every query. The floor of that distribution is your minimum threshold. Anything below it is "probably not relevant."

**Borderline scores (the interesting case):**
A binary gate (above → answer, below → refuse) wastes information. If top score is 0.31 (above gate of 0.25) but rank 2 is 0.29 — both borderline — your answer confidence is lower than if top score is 0.85 and rank 2 is 0.45. You can surface this to the prompt:

```
[Context confidence: borderline — answer with appropriate hedging]
```

Or surface it to the client as a confidence field in the response metadata. Either way, throwing the score away after the top-N cut is a design smell.

---

### 2.3 Streaming / SSE Production Patterns

**The fundamental contract SSE requires:**
Every event is a line `data: <payload>\n\n`. A terminal event must be explicit — either `data: [DONE]\n\n` (OpenAI convention) or a typed event `event: end\n\n`. The client MUST know the stream ended cleanly versus the connection dropped.

**Partial failure mid-stream:**
If generation fails at token 200 of a 400-token response, the client has half an answer and no indication it's incomplete. Correct pattern:

```
data: {"token": "...partial answer..."}\n\n
...
data: {"error": "generation_failed", "partial": true}\n\n   ← terminal error event
```

The client must be coded to check for the error terminal event, not just assume `[DONE]` means success.

**Source citation sequencing:**
Two valid strategies:
1. **Citations first, then answer tokens** — LLM receives context, you emit source metadata as a preamble event before streaming answer tokens. Clean but means the client shows sources before seeing the answer.
2. **Citations last, answer tokens first** — Stream the answer, then emit a citations event as a terminal metadata block. User sees the answer form, sources appear at end. Requires the client to handle a mixed-type event stream.

Never interleave citation events between answer tokens — client reconstruction becomes stateful and fragile.

**What breaks when SSE is bolted onto a non-streaming design:**

| Assumed non-streaming | Breaks with SSE |
|---|---|
| Gating in same try/catch as generation | Error after stream open has no clean emit path |
| Error returns `res.status(500).json(...)` | Headers already sent — throws unhandled exception |
| Sources attached to final response object | Final object doesn't exist mid-stream |
| Single top-level try/catch swallows stage | Client sees truncated stream with no terminal error |

The correct architecture: gating and source assembly happen **before** `res.writeHead(200, {'Content-Type': 'text/event-stream'})`. Generation is the only thing inside the stream. Any pre-generation failure returns a normal JSON error response.

---

## DECISION FRAMEWORK — Your Corpus, Right Now

| Technique | Implement now? | Reason |
|---|---|---|
| **BM25 hybrid retrieval** | **Yes, if exact codes/part numbers exist in your queries** | Orthogonal failure mode to dense. Minisearch or wink-nlp adds < 100 lines. High leverage, low cost. |
| **Document-order restoration post-rerank** | **Yes, immediate** | One sort line. Free. Measurably helps procedural answer coherence. |
| **Relevance gate pre-generation** | **Yes, when you add generation** | Prevents LLM hallucinating on irrelevant context. Threshold from golden-set eval. |
| **Rerank score in prompt / client confidence** | **Yes, trivial** | Pass borderline score as a hedging hint. Free signal you're already computing. |
| **Golden-set eval harness** | **Yes, now** | 20 queries, manual golden chunk IDs, script that runs retrieval and computes Recall@30 + MRR. Should exist before any model change. |
| **SSE streaming** | **When you need streaming UX** | Design the gate-before-stream boundary correctly from day 1 — it's architectural, hard to retrofit. |
| **bge-reranker-large upgrade** | **No** | Marginal on 65 chunks. Fixes second-order problem. Do BM25 first, eval regression, then reconsider. |
| **ColBERT** | **No** | Storage architecture change, no latency problem to solve at 65 chunks. |
| **LLM-as-reranker** | **No** | Non-determinism is disqualifying for a system you need to debug and regress. |
| **RRF without BM25** | **No** | RRF is a fusion formula. Useless without a second retriever. |

**The one thing to do today that has the most leverage:**
Build the golden-set eval harness. Every other decision — whether to add BM25, whether to change reranker, whether to adjust TOP_K — is guessing without it. You currently have no quantitative baseline to argue from.

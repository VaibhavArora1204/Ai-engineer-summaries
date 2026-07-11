# Golden-Set Eval + Generation Layer
### Learning Deep Dive — Flow Understanding, Not Production Code

---

## PART 1 — GOLDEN-SET EVALUATION

---

### What You're Actually Measuring

You have a retrieval pipeline. The question is: **does it find the right chunk?** Not "does the LLM answer well" — that's a separate question downstream.

Two metrics, each tells you something different:

---

### Recall@K

**Plain English:** "Out of all my test queries, what percentage had the correct chunk somewhere in the top-K results?"

```
Recall@K = (queries where golden chunk appears in top-K) / (total queries)
```

If you have 20 test queries and 18 of them have the right chunk in top-5:
```
Recall@5 = 18/20 = 0.90
```

**What it tells you:**
- Recall@5 = 1.0 → retrieval + reranking always surfaces the right chunk in top 5. Generation has a fair shot.
- Recall@5 = 0.70 → 30% of queries, the right chunk isn't even in the context window you send to the LLM. No prompt engineering fixes this. Retrieval is the bottleneck.
- Recall@30 = 0.95, Recall@5 = 0.60 → retrieval finds it, reranking buries it. Reranker is the bottleneck.

**The gap between Recall@30 and Recall@5 is diagnostic.** Large gap = reranker problem. Both low = retrieval problem. Both high = move on to generation quality.

---

### MRR (Mean Reciprocal Rank)

**Plain English:** "On average, how high up does the right chunk appear?"

```
MRR = average of (1 / rank_of_first_correct_chunk) across all queries
```

Examples:
| Query | Rank of correct chunk | Reciprocal Rank |
|---|---|---|
| "how to cancel ticket" | 1 | 1/1 = 1.0 |
| "error E-04" | 3 | 1/3 = 0.33 |
| "part number BRK-2210" | not found | 0 |

MRR = (1.0 + 0.33 + 0) / 3 = **0.44**

**What it tells you vs Recall:**
Recall tells you hit/miss. MRR tells you *where* the hit is. You can have Recall@5 = 1.0 (always found) but MRR = 0.25 (always at rank 4-5). That means the LLM sees the right chunk in the context window, but it's deep — lost-in-the-middle risk.

**Target values for a 65-chunk corpus:**
- Recall@30 should be > 0.95 (you're retrieving half the collection)
- Recall@5 should be > 0.85 after reranking
- MRR should be > 0.70 (correct chunk usually in top 2)

If you're below these on a 65-chunk corpus, something is structurally wrong — likely embedding model mismatch with your domain or chunking too coarse.

---

### Your Excel → Eval Harness

Your sheet: `Query | Observation | Doc Reference | Expected Doc | Issue Type`

**What to add:**

| New column | Purpose |
|---|---|
| `Expected Chunk ID` | The specific chunk ID (from indexedChunk.js) that correctly answers this query. Not just filename — a file can have 10 chunks. |
| `Retrieved Rank` | After running eval: what rank was the golden chunk at? `MISS` if not found. |

**How the eval script works conceptually:**

```
for each row in your golden set:
    1. Call retrieve(query) — your existing function
    2. Look through the returned results for Expected Chunk ID
    3. If found: record its rank position (1, 2, 3...)
    4. If not found: record MISS
    5. Compute Recall@5 and MRR across all rows
```

That's it. The script is ~30 lines. It imports your `retrieve()` function and loops through your test data.

---

### Failure Taxonomy — What Each Result Pattern Means

| Recall@30 | Recall@5 | MRR | Diagnosis |
|---|---|---|---|
| High | High | High | Pipeline is working. Move to generation eval. |
| High | Low | Low | Qdrant finds it, reranker buries it. Cross-encoder is scoring it wrong — inspect the specific queries, look for short chunks or lexical traps. |
| Low | Low | Low | Qdrant never finds it. Embedding model issue or chunking too coarse. Check if the golden chunk's topic is semantically distant from the query wording. |
| High | High | Medium | Right chunk found but at rank 3-4 consistently. Reranker is borderline — consider whether the chunk itself is genuinely the best answer or if your golden label needs updating. |

**Your Issue Type column matters here.** If you've already categorized failures as "wrong doc" vs "right doc wrong chunk" vs "query too vague" — that maps directly:
- "wrong doc" → Recall@30 failure → retrieval problem
- "right doc wrong chunk" → Recall@30 pass, Recall@5 fail → reranker or chunking problem
- "query too vague" → not a pipeline problem, it's a query quality problem — no fix in retrieval

---

### When to Run Eval

Run the golden set **before and after** any of these changes:
- Embedding model swap
- Chunk size or overlap change
- TOP_K or TOP_N change
- Reranker model swap
- Adding BM25 hybrid

If MRR drops > 5%, the change regressed something. Investigate before shipping.

---

### Minimal Flow Sketch

```javascript
// evalHarness.js — conceptual, not production
const { retrieve } = require('./retrievalService');

const goldenSet = [
  { query: "how to cancel ticket", expectedChunkId: 12 },
  { query: "error E-04 reset", expectedChunkId: 45 },
  // ... from your Excel
];

async function runEval() {
  let totalRR = 0;  // sum of reciprocal ranks
  let hits5 = 0;    // count of queries where golden chunk in top 5

  for (const test of goldenSet) {
    const results = await retrieve(test.query);
    const rank = results.findIndex(r => r.id === test.expectedChunkId) + 1;
    // findIndex returns -1 if not found, +1 makes it 0 (miss)

    if (rank > 0 && rank <= 5) hits5++;
    totalRR += rank > 0 ? 1 / rank : 0;

    console.log(`Query: "${test.query}" → Rank: ${rank || 'MISS'}`);
  }

  console.log(`Recall@5: ${(hits5 / goldenSet.length).toFixed(2)}`);
  console.log(`MRR: ${(totalRR / goldenSet.length).toFixed(2)}`);
}
```

> [!IMPORTANT]
> This requires your `retrieve()` to return `id` in the output objects. Currently your scored output drops `id` — you'd need to carry it through or look it up. Minor fix.

---

## PART 2 — GENERATION LAYER

---

### The Flow After Retrieval

Your pipeline currently ends here:
```
query → embed → qdrant → join → rerank → top 5 results returned
```

Generation extends it:
```
query → embed → qdrant → join → rerank → top 5
  → score gate check
  → document-order restoration
  → context assembly (prompt construction)
  → LLM call (Gemini)
  → response to client
```

Each step is a design decision. Let's go through them.

---

### Step 1: Score Gate

**What it is:**
Look at the top reranked score. If it's below a threshold, don't call the LLM. Return "I don't have enough relevant information to answer this."

**Why it exists:**
Without it, the LLM receives irrelevant chunks and hallucinates a confident-sounding wrong answer. The user can't distinguish a confident correct answer from a confident hallucinated one. The gate prevents this by refusing to answer when confidence is low.

**How to set the threshold:**
You cannot guess it. It comes from your golden set eval:
1. Run eval, record the rerank score of the correct chunk for every query
2. The floor of that distribution is your threshold
3. Example: correct chunks always score > 0.3, irrelevant queries' top chunk scores < 0.15 → threshold at 0.2

**The grey zone:**
If correct chunks score 0.3–0.8 and irrelevant tops score 0.1–0.35, there's overlap at 0.3–0.35. This is your grey zone — any threshold you pick will either:
- Let some hallucinations through (threshold too low)
- Refuse some valid queries (threshold too high)

There's no magic threshold. You pick the side of the tradeoff you prefer for your use case and document it.

**Where it sits in the flow — critical:**
```
retrieve() returns top 5
↓
gate check: top score < threshold?
  YES → return JSON: { answer: null, reason: "low_confidence" }
  NO  → proceed to LLM
```

This must happen **before** you open a stream, before you build a prompt, before you touch the LLM. It's a circuit breaker.

---

### Step 2: Document-Order Restoration

**What it is:**
After reranking gives you top 5 by relevance score, re-sort them by their original position in the source document before passing to the LLM.

**Why:**
Your chunks are from an instruction manual with overlap. After reranking, top 5 might be:

```
Rank 1: chunk 47 (Step 7 - Confirm cancellation)    score: 0.82
Rank 2: chunk 44 (Step 4 - Select booking)           score: 0.78
Rank 3: chunk 42 (Step 2 - Navigate to My Trips)     score: 0.75
Rank 4: chunk 49 (Step 9 - Print confirmation)        score: 0.71
Rank 5: chunk 41 (Step 1 - Log in to account)         score: 0.68
```

If you pass these in score order, the LLM sees Step 7 first, then Step 4, then Step 2, then Step 9, then Step 1. It will either:
- Reproduce the wrong order in its answer
- Attempt to fix the order but miss dependencies ("Step 7 requires Step 4")
- Ignore middle chunks entirely (lost-in-the-middle)

After document-order restoration:
```
chunk 41 (Step 1) → chunk 42 (Step 2) → chunk 44 (Step 4) → chunk 47 (Step 7) → chunk 49 (Step 9)
```

Now the LLM reads a coherent procedure with correct flow. Steps 3, 5, 6, 8 are missing (not retrieved) but the order of what IS there is correct.

**Implementation — one line:**
```javascript
const orderedResults = topNResults.sort((a, b) => a.id - b.id);
```

That's it. Chunk IDs in your system are sequential by document position. Sort by ID = document order.

**When NOT to do this:**
When your top 5 come from different documents. Then you'd group by filename first, sort within each group by ID, and order groups by the highest score in each group:

```
Group 1 (cancellation_guide.md): chunk 41, 42, 44  ← best score 0.82
Group 2 (refund_policy.md): chunk 12, 15            ← best score 0.71
```

---

### Step 3: Context Assembly (Prompt Construction)

**What you're building:**
A single string that goes to the LLM containing: system instruction + retrieved context + user query.

**The structure that works for instruction manuals:**

```
SYSTEM: You are a customer support assistant. Answer ONLY using the provided 
context. If the context doesn't contain enough information to answer, say so.
Do not make up information.

CONTEXT:
[Source: cancellation_guide.md]
Step 1 - Log in to account...
Step 2 - Navigate to My Trips...
Step 4 - Select booking...
Step 7 - Confirm cancellation...
Step 9 - Print confirmation...

USER QUERY: How do I cancel my booked airline ticket?
```

**Key decisions in this structure:**

1. **"Answer ONLY using the provided context"** — this is your primary hallucination defense. Without it, the LLM falls back to parametric knowledge, which may be wrong or outdated for your domain.

2. **Source attribution in context** — including `[Source: filename]` lets the LLM reference which document it used. You can then verify its answer against the actual source. Without it, the LLM gives an answer with no traceability.

3. **No chunk boundaries visible to the LLM** — don't pass chunks as separate numbered items (`Chunk 1:`, `Chunk 2:`). The LLM may then reference "as mentioned in Chunk 3" which is meaningless to the user. Concatenate the text as continuous prose (your overlap already handles transitions).

4. **Query goes LAST** — recency bias in LLMs means the last thing in the prompt gets the most attention. Query at the end = LLM focuses on answering it. Query at the beginning = LLM may drift into summarizing the context.

---

### Step 4: LLM Call (Gemini)

**Non-streaming (what you build first):**
```javascript
const model = genAI.getGenerativeModel({ model: 'gemini-pro' });
const result = await model.generateContent(prompt);
const answer = result.response.text();
```

Full response returns as one string. You return it as JSON. Simple.

**Streaming (when you need it later):**
```javascript
const result = await model.generateContentStream(prompt);
for await (const chunk of result.stream) {
  const token = chunk.text();
  res.write(`data: ${JSON.stringify({ token })}\n\n`);
}
res.write('data: [DONE]\n\n');
res.end();
```

Same model, same prompt, different method name. The stream yields text chunks as generated.

**The boundary between these two is the gate.** Streaming means you can't take back what you've already sent. Non-streaming means you can inspect the full answer before sending (e.g., check for hallucination markers, check answer length, log it). Start non-streaming.

---

### Step 5: What the Response Should Contain

Not just the answer text. Include:

```json
{
  "answer": "To cancel your ticket, follow these steps: 1. Log in...",
  "sources": [
    { "filename": "cancellation_guide.md", "chunk_id": 41 },
    { "filename": "cancellation_guide.md", "chunk_id": 42 }
  ],
  "confidence": {
    "top_rerank_score": 0.82,
    "score_gap": 0.04,
    "gate_status": "pass"
  }
}
```

**Why include confidence:**
- `top_rerank_score` — raw reranker output. Your frontend or QA team can flag borderline answers.
- `score_gap` — difference between rank 1 and rank 2. Small gap = model is unsure between two candidates. Large gap = clear winner.
- `gate_status` — did it pass the gate cleanly or was it borderline?

This is signal you've already computed. Throwing it away after the top-N cut is waste. Surface it.

---

### The Complete Flow — One Read

```
1. Client POST { query: "how to cancel ticket" }

2. GATE: is query valid?
   NO  → 400 { error: "missing query" }
   YES → continue

3. EMBED: queryEmbed(query) → vector [0.12, -0.34, ...]
   FAIL → 500 { error: "embedding failed", stage: "embed" }

4. QDRANT: search(vector, limit=30) → 30 hits with scores
   FAIL → 500 { error: "qdrant failed", stage: "qdrant" }

5. JOIN: map hit IDs → chunk text from indexedChunk.js
   Misses logged, dropped. Continue with remaining.

6. RERANK: cross-encoder scores all (query, chunk) pairs
   Sort descending. Take top 5.
   FAIL → 500 { error: "reranker failed", stage: "rerank" }

7. SCORE GATE: top score < threshold?
   YES → 200 { answer: null, reason: "low_confidence" }
   NO  → continue

8. DOCUMENT ORDER: sort top 5 by chunk ID (original doc position)

9. CONTEXT: concatenate chunks with source labels + system prompt + query

10. GENERATE: Gemini generates answer from context
    FAIL → 500 { error: "generation failed", stage: "generate" }

11. RESPOND: { answer, sources, confidence }
```

Steps 1–6 = what you have now.
Steps 7–11 = what generation adds.

Each step has its own try/catch and failure path. No step depends on a step that hasn't explicitly succeeded.

---

## Where Rerank Scores Flow Beyond the Gate

The score is useful in three places beyond "pass/fail":

| Where | How | Why |
|---|---|---|
| **Prompt injection** | Add `[Confidence: moderate]` to system prompt when top score is borderline | LLM hedges appropriately: "Based on available information..." vs confidently asserting |
| **Client response** | Include score in API response | Frontend can show confidence indicator, QA can filter borderline answers |
| **Eval logging** | Log score alongside answer for every query | Post-hoc analysis: "all wrong answers had top_score < 0.35" → threshold discovery |

The score is a calibration signal. It's imperfect (uncalibrated raw logit), but it's the ONLY relevance signal between retrieval and generation. Use it everywhere you can, don't just threshold and discard.

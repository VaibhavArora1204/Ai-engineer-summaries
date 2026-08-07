# Travel Policy RAG — Eval Harness: Final Architecture & Implementation

## 0. Confirmed constraints (changes design vs. previous draft)

| Constraint | Answer | Design impact |
|---|---|---|
| Citation granularity | Doc URL only, not chunk ID | Citation Evaluator becomes doc-level, deterministic. It **cannot** catch same-document-wrong-branch. That job moves entirely to Policy Resolution + Completeness evaluators (judge-based, operate on answer text, not the citation field). This is the single most important design decision in this doc — see §5.3–5.5. |
| Judge model | Gemini Flash 2.5 (same as generator) | Self-preference bias risk: a model rating its own family's output tends to score it more favorably than an equivalent output from elsewhere. Not fixable by prompt engineering alone. Mitigation in §6. |
| Human review | Informal spreadsheet | Self-evolving golden-set loop cannot be fully automated yet. Phase 1 uses a manual CSV bridge with a fixed schema. Full automation is blocked on a process change (ops adopting the template), not a code change — flagged in §10. |
| Repo placement | Flexible | Assume `eval/` inside the existing retrieval-to-generation repo, so it shares Qdrant client + API auth. Nothing below depends on this — move it out later with zero redesign. |

---

## 1. Non-negotiable design principles (carried from prior review)

1. **No score aggregator.** A blended number lets 9 passes hide 1 critical failure. Output is a **gate**: PASS / WARN / BLOCK.
2. **Two separate granularities, two separate data sources:**
   - **Retrieval-internal (chunk-level):** sourced from Qdrant logs. Used only by the Retrieval Evaluator. Never exposed to the user, so re-chunking can break it silently — see §10.
   - **Citation-external (doc-level):** sourced from the API's actual citation output. Used only by the Citation Evaluator.
3. **Deterministic over judge, wherever math suffices.** Judge calls are reserved for entailment/reasoning tasks that can't be expressed as set arithmetic.
4. **Every production failure becomes a permanent regression case.** Architecture stays fixed; the golden set grows.

---

## 2. Architecture

```
                    ┌─────────────────────┐
                    │   Golden Dataset     │◄──────────────┐
                    └──────────┬───────────┘                │
                               │                             │
                    ┌──────────▼───────────┐                │
                    │   Evaluation Runner   │                │
                    └──────────┬───────────┘                │
        ┌──────────┬───────────┼───────────┬──────────┐     │
        ▼          ▼           ▼           ▼          ▼     │
   Retrieval   Citation   Policy Res.  Completeness  Ground-  │
   Evaluator   Evaluator  Evaluator    Evaluator     edness   │
   (chunk,     (doc URL,  (judge,      (judge,       Evaluator│
   Qdrant log, det.)      branch       condition     (judge,  │
   det.)                  text)        text)         faith+   │
        │          │           │           │         halluc)  │
        └──────────┴───────────┴───────────┴──────────┘       │
                               │                                │
                      Abstention Evaluator (det.)               │
                               │                                │
                      Business Risk GATE (not aggregator)       │
                               │                                │
                    ┌──────────┴───────────┐                    │
                    │  Report + Trace Log   │                    │
                    └──────────┬───────────┘                    │
                               │                                │
          ┌────────────────────┼─────────────────────┐          │
          ▼                    ▼                     ▼          │
   Drift Monitor        Coverage Monitor      Reviewer Diff Loop─┘
   (query/index/judge)  (doc × branch matrix)  (spreadsheet → candidate
                                                 golden entries, Phase 1)
```

Retrieval, Citation, Abstention → **deterministic, run on every PR.**
Policy Resolution, Completeness, Groundedness → **judge-based, run nightly / pre-release / sampled** (cost reason, see §10).

---

## 3. Golden dataset schema (reconciled — one schema, not two)

```json
{
  "id": "Q001",
  "question": "Can I get a refund after cancelling within 5 days?",
  "intent": "refund",
  "difficulty": "medium",
  "expected_result": "answer",

  "expected_documents": ["Cancellation Policy", "Refund Policy"],
  "forbidden_documents": ["Meal Policy"],

  "expected_chunk_ids": ["chunk_18", "chunk_41"],
  "index_snapshot_id": "qdrant_snap_2026_08_01",

  "expected_branches": ["domestic_cancellation", "cancellation_7day"],
  "forbidden_branches": ["international_cancellation"],

  "required_policy_conditions": [
    "Cancellation within 7 days",
    "Ticket unused",
    "Refund fee applies"
  ],

  "business_risk": "critical",
  "source": "production_reviewed",
  "created_from": "complaint_ticket_4821"
}
```

Notes:
- `expected_chunk_ids` + `index_snapshot_id` are **retrieval-internal only** — never compared against citation output.
- `expected_documents` / `forbidden_documents` are **citation-external** — compared against the API's actual citation field.
- `expected_branches` / `forbidden_branches` feed Policy Resolution — this is the real defense against your core business risk, not the citation evaluator. Label these exhaustively; sloppy labels here are a silent hole in your only real defense.
- `source` distinguishes `production_reviewed` (trusted) from `synthetic` (lower-weight, Phase 3 coverage-gap filler, §7).

---

## 4. Logging schema (unchanged necessity regardless of citation granularity)

Every eval run and every sampled production call must log:

```json
{
  "query": "...", "query_variants": ["...", "...", "..."],
  "retrieved_chunks": [
    {"chunk_id": "chunk_18", "doc_url": "...", "vector_score": 0.61,
     "rrf_score": 0.032, "rank": 1}
  ],
  "chunks_sent_to_llm": ["chunk_18", "chunk_41"],
  "raw_llm_output": "...",
  "final_answer": "...",
  "citations_returned": ["https://.../cancellation-policy"],
  "latency_ms": 842, "token_usage": {"input": 2100, "output": 340},
  "index_snapshot_id": "qdrant_snap_2026_08_01"
}
```

`chunks_sent_to_llm` is the field that lets you attribute a bad answer to retrieval vs. generation without re-running anything. Do not skip logging it — it's the only thing that separates "reranker demoted the right chunk" from "LLM ignored the right chunk it was given."

---

## 5. Evaluators

### 5.1 Retrieval Evaluator — chunk-level, deterministic, Qdrant-sourced

```python
def retrieval_eval(golden, retrieved_chunks):
    expected = set(golden["expected_chunk_ids"])
    retrieved = set(c["chunk_id"] for c in retrieved_chunks)
    recall = len(expected & retrieved) / max(len(expected), 1)
    missing = expected - retrieved
    return {"recall_at_k": recall, "missing_chunks": list(missing),
            "mrr": _mrr(golden["expected_chunk_ids"], retrieved_chunks)}
```
Run at **each pipeline stage separately** (post-dense-search per query variant, post-RRF, and post-reranker once BGE ships). Recall ceiling is set at the earliest stage — a rerank fix cannot recover a chunk that never entered the candidate set.

### 5.2 Context / Retrieval-Quality — merged into 5.1's output, not a separate module
`duplicate_chunk_rate`, `avg_vector_score`, `avg_rrf_score`, `context_pollution = irrelevant_chunks / total_chunks` computed from the same `retrieved_chunks` array. No separate evaluator class needed — it's a different metric on the same input.

### 5.3 Citation Evaluator — doc-level, deterministic

```python
def citation_eval(golden, citations_returned):
    expected = set(golden["expected_documents"])
    forbidden = set(golden["forbidden_documents"])
    actual = set(_doc_title_from_url(u) for u in citations_returned)

    precision = len(actual & expected) / max(len(actual), 1)
    recall = len(actual & expected) / max(len(expected), 1)
    pollution = len(actual & forbidden) / max(len(actual), 1)
    return {"precision": precision, "recall": recall,
            "pollution": pollution, "forbidden_cited": list(actual & forbidden)}
```
**What this catches:** citing an entirely wrong document (Meal Policy on a refund query).
**What this does NOT catch:** citing the *correct* document but the model reasoning from the wrong branch inside it. Doc-level citation matching cannot distinguish "Cancellation Policy, 24-hour branch" from "Cancellation Policy, 7-day branch" — both are the same URL. This is not a bug to fix here; it's a structural limit of doc-level citations. The defense lives in 5.4 and 5.5.

### 5.4 Policy Resolution Evaluator — judge, text-based, **your primary risk defense**

```python
JUDGE_PROMPT = """
Golden branches this answer SHOULD reflect: {expected_branches}
Branches this answer must NOT reflect: {forbidden_branches}
Answer text: {answer}

For each branch in both lists, return entailed / not_entailed based ONLY on
whether the answer's stated conditions match that branch's defining rule.
Return strict JSON: {{"branch": "...", "verdict": "..."}}
"""

def policy_resolution_eval(golden, answer_text, judge_fn):
    results = judge_fn(JUDGE_PROMPT.format(
        expected_branches=golden["expected_branches"],
        forbidden_branches=golden["forbidden_branches"],
        answer=answer_text))
    correct_present = sum(1 for r in results
                           if r["branch"] in golden["expected_branches"] and r["verdict"] == "entailed")
    wrong_present = sum(1 for r in results
                         if r["branch"] in golden["forbidden_branches"] and r["verdict"] == "entailed")
    precision = correct_present / max(correct_present + wrong_present, 1)
    recall = correct_present / max(len(golden["expected_branches"]), 1)
    return {"precision": precision, "recall": recall, "wrong_branches_present": wrong_present}
```
This is judge-based specifically because "does this answer reflect the international branch" requires reading comprehension, not string matching. Gate: **BLOCK on any `wrong_branches_present > 0`** — this is the check standing in for the citation-granularity gap.

### 5.5 Policy Completeness Evaluator — judge, per-condition entailment, not substring match

```python
def completeness_eval(golden, answer_text, judge_fn):
    results = []
    for cond in golden["required_policy_conditions"]:
        verdict = judge_fn(condition=cond, answer=answer_text,
            instruction="entailed / contradicted / absent — any wording counts")
        results.append({"condition": cond, "verdict": verdict})
    present = sum(1 for r in results if r["verdict"] == "entailed")
    contradicted = [r["condition"] for r in results if r["verdict"] == "contradicted"]
    missing = [r["condition"] for r in results if r["verdict"] == "absent"]
    return {"score": present / len(results), "missing": missing, "contradicted": contradicted}
```
`contradicted` (stating a wrong fee/date) is worse than `missing` (silence) — a fabricated business rule is a Critical-tier failure distinct from an omission. Keep these as separate buckets in the report, don't collapse them.

### 5.6 Groundedness Evaluator — judge, faithfulness + hallucination merged (same underlying check)

```python
def groundedness_eval(chunks_sent_to_llm, answer_text, judge_fn):
    claims = judge_fn(instruction="extract atomic factual claims", answer=answer_text)
    results = [judge_fn(instruction="is this claim entailed by the evidence?",
                         claim=c, evidence=chunks_sent_to_llm) for c in claims]
    supported = sum(1 for r in results if r == "entailed")
    return {"score": supported / max(len(claims), 1),
            "unsupported_claims": [c for c, r in zip(claims, results) if r != "entailed"]}
```
Checks against `chunks_sent_to_llm` (the log field from §4), not against the cited documents — a claim can be grounded in evidence the model saw but forgot to cite, or cited but not actually used. These are different failures; this evaluator only measures the first.

### 5.7 Abstention (Not Found) Evaluator — deterministic, correct score space

```python
def abstention_eval(golden, answer_text, post_rrf_max_score):
    should_abstain = golden["expected_result"] == "not_found"
    did_abstain = answer_text.strip().lower() == "not found"
    if should_abstain and not did_abstain:
        return {"verdict": "FALSE_CONFIDENCE", "risk": "critical"}
    if not should_abstain and did_abstain:
        return {"verdict": "FALSE_ABSTENTION", "risk": "high"}
    return {"verdict": "PASS"}
```
Threshold check must use the **post-RRF fused score**, not the raw 0.50 vector cutoff — RRF operates on rank position, not cosine similarity, so a raw-score threshold checks a decision boundary the production system doesn't actually use.

### 5.8 Business Risk Gate — replaces the score aggregator entirely

```python
def gate(results):
    critical = (results["citations"]["forbidden_cited"] or
                results["policy_resolution"]["wrong_branches_present"] > 0 or
                results["completeness"]["contradicted"] or
                results["completeness"]["missing"] or
                results["abstention"]["verdict"] == "FALSE_CONFIDENCE" or
                results["groundedness"]["unsupported_claims"])
    if critical:
        return "BLOCK"
    warn = (results["retrieval"]["missing_chunks"] or
            results["abstention"]["verdict"] == "FALSE_ABSTENTION")
    return "WARN" if warn else "PASS"
```
No blended score is ever computed. A single BLOCK on one sample fails the whole regression run.

### 5.9 / 5.10 Drift & Coverage — cross-run monitors, not per-sample evaluators
- **Drift**, three independent sub-checks, don't merge: (a) query distribution drift — production query embeddings diverging from golden-set distribution; (b) index drift — `expected_chunk_ids` no longer resolving after a reindex; (c) judge drift — judge-vs-human agreement dropping after a provider-side model update.
- **Coverage**: `doc × branch` matrix, percentage of cells with ≥1 golden query. Zero-coverage cells are the input to Phase 3 synthetic generation (§7).

---

## 6. Judge design: Flash 2.5 judging Flash 2.5

You're accepting a known bias, not avoiding one. Mitigations, in priority order:

1. **Minimize judge surface area.** Retrieval, Citation, and Abstention are already deterministic (5.1, 5.3, 5.7) — zero judge exposure. Only 5.4/5.5/5.6 touch the judge.
2. **Atomic, closed-form prompts only.** Never "rate this answer 1–5." Always single-claim entailed/contradicted/absent verdicts. Open-ended scoring is where self-preference leniency shows up most.
3. **Monthly calibration against ~50 human-labeled examples**, tracked as its own trend line (part of Drift §5.9c). If judge-human agreement drops, freeze the judge version and alert — don't let it silently decay.
4. **Budget for a second-model spot-check** on BLOCK verdicts specifically — even a small monthly sample of BLOCKs re-judged by a different model (Claude/GPT-4o, since you have provider access) tells you whether Flash 2.5 is under- or over-flagging its own failures. This is the single highest-leverage mitigation available and costs the least (you only re-check the samples that already flagged as failing).

---

## 7. Self-evolving loop — Phase 1 (spreadsheet bridge) → Phase 2 (automated)

**Phase 1 — works today, no process change required beyond a fixed template:**

Minimum spreadsheet columns ops needs to maintain (this is the actual blocker — see §10):
```
query | model_answer | model_citations | reviewer_corrected_answer |
reviewer_corrected_citations | reviewer_notes | date
```

Weekly ingestion script:
```python
def ingest_reviewer_diffs(csv_path, judge_fn):
    candidates = []
    for row in read_csv(csv_path):
        if row["model_answer"].strip() == row["reviewer_corrected_answer"].strip():
            continue  # no diff, skip
        diff_type = judge_fn(instruction="classify this diff",
            model=row["model_answer"], corrected=row["reviewer_corrected_answer"])
        candidates.append({
            "question": row["query"],
            "diff_type": diff_type,  # citation_added / condition_removed / branch_changed / etc
            "source": "production_reviewed",
            "needs_confirm": True
        })
    return candidates  # → confirm queue, engineer clicks yes/no, confirmed → golden set
```

**Phase 2 (blocked on process, not code):** once review moves into any structured tool (even a fixed Google Form beats free-text spreadsheet), the diff-classification step gets more reliable and this can run daily instead of weekly, with less manual confirm overhead.

**Pattern detection on top (do this once Phase 1 has ~2 weeks of data):** cluster confirmed candidates by `(diff_type, branch_touched)`. A cluster of 5+ `branch_changed` diffs on the same branch pair in a week is a systemic router bug, not five isolated golden entries — file it as a standing regression sub-suite, not five rows.

---

## 8. Repo layout

```
eval/
 ├── datasets/golden_v1.json
 ├── configs/eval.yaml
 ├── evaluators/
 │    ├── retrieval.py        # 5.1, deterministic
 │    ├── citations.py        # 5.3, deterministic
 │    ├── abstention.py       # 5.7, deterministic
 │    ├── policy_resolution.py# 5.4, judge
 │    ├── completeness.py     # 5.5, judge
 │    └── groundedness.py     # 5.6, judge
 ├── judges/llm_judge.py       # atomic entailment calls only
 ├── gate.py                   # 5.8, no aggregator
 ├── monitors/drift.py          coverage.py
 ├── ingestion/reviewer_diff.py # §7 Phase 1
 └── runner.py
```

---

## 9. Rollout order

| Phase | What ships | Depends on |
|---|---|---|
| 0 | Logging schema (§4) live in prod, `chunks_sent_to_llm` captured | API/pipeline change, do this first — nothing else works without it |
| 1 | Retrieval, Citation, Abstention evaluators + gate | Phase 0 |
| 2 | Policy Resolution, Completeness, Groundedness (judge) | Phase 1, judge calibration set (50 human-labeled) |
| 3 | Reviewer diff ingestion, coverage-gap synthetic generation | Phase 2, spreadsheet template adopted by ops |

Deterministic checks (Phase 1) run on every PR — cheap, fast. Judge checks (Phase 2) run nightly or pre-release, sampled, not on every commit — see §10 for why.

---

## 10. Challenges — what's actually hard here, not cosmetic

**Your primary risk defense now rests entirely on golden-label quality, not on the citation field.** Since citations are doc-level, the only thing standing between you and "correct citation, wrong branch" shipping silently is how exhaustively you label `expected_branches` / `forbidden_branches` per golden query. If that labeling is sloppy or incomplete, the harness has a blind spot in exactly the place your original brief said was the biggest business risk. This is worth spending disproportionate review time on — more than on evaluator code.

**Judge-judges-same-model bias compounds when the diff classifier is also a judge.** Phase 1's `ingest_reviewer_diffs` uses Flash 2.5 to classify diffs between Flash 2.5's own output and a human correction. That's two layers of the same bias risk stacked. Periodically hand-audit a sample of the diff classifier's own output, not just the eval judge's output.

**Chunk ID churn on reindex breaks Retrieval Evaluator silently, even though citations don't depend on chunk IDs.** `expected_chunk_ids` in the golden set can point at a chunk that a re-chunk pass merged or deleted. This won't throw an error — it'll just silently report artificially low recall or, worse, an artificially resolved chunk pointing at unrelated content. Add a periodic revalidation job: on every reindex, check every golden `expected_chunk_id` still resolves to content matching a stored content hash, not just that the ID exists.

**RRF fused scores and raw vector similarity are not interchangeable**, and it's tempting to reuse the 0.50 raw-vector abstention threshold because it's already documented. It measures a decision boundary the production system doesn't use post-fusion. Confirm the abstention check reads whatever score the intent router prompt actually sees.

**Cost and latency add up faster than expected once judge evaluators are real.** Three judge calls per sample (resolution, completeness, groundedness — and groundedness itself does one call per extracted claim) on a 500-query golden set is not a 500-call run, it's closer to 2,000+. Running that on every PR is slow and expensive. This is why Phase 1/2 are split: deterministic gates block merges immediately; judge-based gates run as a nightly or pre-release job, with PR-time coverage limited to a stratified sample (all Critical-risk golden entries + a random subset of the rest).

**The self-evolving loop's actual bottleneck is a spreadsheet template, not code.** Everything in §7 Phase 1 is buildable this week. It produces nothing useful if ops doesn't consistently fill in `reviewer_corrected_answer` as a full corrected answer rather than a one-line note like "fixed citation." Get the column discipline agreed before writing the ingestion script — building the automation first and discovering the input data is unusable is the more expensive order to do this in.

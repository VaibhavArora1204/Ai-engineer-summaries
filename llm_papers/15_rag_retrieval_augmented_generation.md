# Paper 15: RAG — Retrieval-Augmented Generation (Lewis et al., 2020)

## What Existed Before and What Broke

LLMs store knowledge in their weights during training. This creates three fundamental problems that cannot be solved by making the model bigger or training it longer:

**1. Knowledge is frozen at training cutoff.** A model trained in January 2024 doesn't know about events from February 2024. For any domain where information changes — stock prices, medical guidelines, legal precedents, product documentation, company policies — the model's knowledge is stale from the moment training ends. Retraining is the only way to update it, and retraining costs millions of dollars and takes months.

**2. No verifiable attribution.** When a model generates "The treatment protocol for condition X is Y," there's no way to verify where that information came from. Did it come from a reliable medical textbook in the training data? From a Reddit post? From a hallucinated synthesis of loosely related training examples? The model doesn't know, and you can't check. For any application requiring verifiable claims — legal, medical, financial, compliance — this is disqualifying.

**3. Knowledge is compressed and lossy.** The model doesn't memorize training data — it learns compressed statistical patterns. Specific facts, especially rare ones, are unreliably stored. The model might know that "aspirin is an anti-inflammatory" (common fact, well-represented in training data) but not "the specific dosing protocol for aspirin in pediatric Kawasaki disease" (rare, specialized fact). The compression is lossy, and you can't predict which facts survived compression and which didn't.

RAG addresses all three by externalizing knowledge: instead of relying on what the model "remembers" from training, retrieve relevant documents at query time and inject them into the prompt.

---

## The Core Mechanism

### The Original RAG Paper (2020) — What It Actually Proposed

The original RAG paper is not what "RAG" means in production today. Understanding the gap is important:

```
Original RAG (Lewis et al., 2020):
  Retriever: Dense Passage Retriever (DPR)
    - Bi-encoder: query encoder + passage encoder (both BERT-based)
    - Encode query → vector. Encode passages → vectors. 
    - Retrieve top-k passages by maximum inner product search (MIPS)
  
  Generator: BART (encoder-decoder model)
    - Conditions on query + retrieved passages
    - Generates answer
  
  Key property: Jointly trained end-to-end
    - Retriever and generator are trained together
    - Gradients from the generator update the retriever
    - The retriever LEARNS what to retrieve based on what helps generation
  
  Two variants:
    RAG-Sequence: retrieve once, generate full answer
    RAG-Token: retrieve separately for each output token (expensive)
```

**What survived from the original paper:** The retrieve → augment → generate pattern. That's it.

**What changed in production RAG:**

```
Original (2020)                     Production (2024-2025)
─────────────────────────────────── ──────────────────────────────────
BART generator                      Frozen decoder-only LLM (GPT-4, Claude, Llama)
Jointly trained retriever+generator  Completely separate retriever and generator
Dense-only retrieval (DPR)          Hybrid: dense (vector) + sparse (BM25)
Document-level retrieval            Chunk-level retrieval with overlap
No reranking                        Cross-encoder reranking stage
End-to-end trained on NQ/TriviaQA   No joint training; prompt engineering
Small encoder model                 Large embedding models (text-embedding-3, E5)
```

### What Modern Production RAG Actually Looks Like

```
Ingestion pipeline (offline):
  1. Document loading: PDFs, HTML, Markdown, databases → raw text
  2. Chunking: split documents into chunks (500-1000 tokens each)
     - Fixed-size: simple, consistent, but may split mid-sentence
     - Semantic: split at natural boundaries (paragraphs, sections)
     - Hierarchical: parent chunks contain children (multi-resolution)
  3. Embedding: encode each chunk → dense vector (768-3072 dimensions)
     - Models: text-embedding-3-small/large, E5, BGE
  4. Indexing: store vectors + metadata in vector store
     - Stores: Pinecone, Weaviate, Qdrant, Chroma, pgvector
  5. Keyword indexing: store text in BM25/full-text search index
     - For hybrid retrieval (dense + sparse)

Query pipeline (online):
  1. Query embedding: encode user query → dense vector
  2. Dense retrieval: vector similarity search → top-k chunks
  3. Sparse retrieval: BM25 keyword search → top-k chunks
  4. Fusion: combine dense + sparse results (Reciprocal Rank Fusion)
  5. Reranking: cross-encoder reranks fused results by relevance
  6. Context assembly: format top-N chunks into prompt
  7. Generation: LLM generates answer grounded in retrieved chunks
  8. Citation extraction: map answer claims to source chunks
```

---

## What This Creates for Your System

### Retrieval Quality Is the Ceiling

This is the single most important principle in RAG system design: **the quality of your generation is bounded by the quality of your retrieval.** The best LLM in the world cannot generate a correct answer from irrelevant retrieved chunks.

```
Retrieval quality hierarchy:

  Perfect retrieval + mediocre LLM = good answers
  (LLM has the right information, just needs to synthesize)
  
  Perfect retrieval + great LLM = great answers
  (Right information + great synthesis)
  
  Bad retrieval + great LLM = confidently wrong answers
  (LLM generates authoritative-sounding response from wrong context)
  
  Bad retrieval + mediocre LLM = obviously wrong answers
  (At least the user knows something is wrong)

The dangerous case: bad retrieval + great LLM.
The LLM produces a coherent, well-structured, confident response
grounded in the wrong documents. The user trusts it because it
SOUNDS authoritative. This is worse than no RAG at all, because
without RAG the LLM might at least hedge or say "I don't know."
```

**Where most teams invest vs where they should:**

```
Typical team investment:
  LLM selection and prompt engineering:  60% of effort
  Retrieval pipeline:                    30% of effort
  Evaluation and monitoring:            10% of effort

Where the quality leverage actually is:
  Retrieval pipeline (chunking, embedding, reranking): 50% of quality
  Data quality (document preprocessing, metadata):    25% of quality
  Prompt engineering:                                  15% of quality
  LLM selection:                                       10% of quality

Most teams over-invest in LLM prompt tuning and under-invest in 
retrieval. Switching from GPT-3.5 to GPT-4 gives ~10% improvement.
Adding a reranker gives ~15% improvement. Better chunking gives ~20%.
The leverage is in retrieval, not generation.
```

### Chunking Strategy — The Highest-Leverage Decision

How you split documents into chunks determines what the retriever can find:

```
Fixed-size chunking (500 tokens, 100 token overlap):
  Simple to implement.
  Chunks may split mid-sentence, mid-paragraph, mid-thought.
  A crucial fact might span two chunks. Neither chunk alone is sufficient.
  Overlap helps but doesn't solve: if the key passage is exactly at 
  the split boundary, both overlapping chunks have only partial context.

Semantic chunking:
  Split at natural boundaries: paragraphs, sections, markdown headers.
  Each chunk is a self-contained unit of information.
  Harder to implement (need to parse document structure).
  Quality improvement: 15-25% better retrieval precision in practice.

Hierarchical chunking:
  Parent chunks (1000-2000 tokens): full sections for broad context
  Child chunks (200-400 tokens): specific passages for precise retrieval
  Retrieve on child chunks (precise matching) → return parent chunks 
  (full context) to the LLM.
  Best quality. Most complex. Worth it for production systems.

Practical recommendation:
  Start with semantic chunking at paragraph/section boundaries.
  Add chunk overlap (10-20% of chunk size).
  Move to hierarchical chunking if retrieval precision is insufficient.
  Fixed-size chunking is acceptable for prototypes, not for production.
```

### Hybrid Search — Dense + Sparse

Dense (vector) search and sparse (keyword/BM25) search have complementary strengths:

```
Dense search (vector similarity):
  ✓ Semantic matching: "car" matches "automobile"
  ✓ Paraphrase handling: different wording, same meaning
  ✗ Exact keyword matching: medical code "ICD-10 J06.9" fails
  ✗ Rare terms: product SKUs, case numbers, specific technical terms
  
Sparse search (BM25):
  ✓ Exact keyword matching: "ICD-10 J06.9" matches perfectly
  ✓ Rare terms: unique identifiers, codes, names
  ✗ Semantic similarity: "car" does NOT match "automobile"
  ✗ Paraphrase: different wording = no match

Hybrid search:
  Run both. Merge results with Reciprocal Rank Fusion (RRF):
    RRF_score(doc) = Σ 1/(k + rank_i) for each retrieval method
    k = 60 (standard constant)
  
  Hybrid catches both semantic matches AND exact keyword matches.
  Quality improvement: 10-20% better recall vs dense-only.
  Implementation cost: moderate (two indices, one fusion step).
  
  For any production RAG system, hybrid is the minimum bar.
  Pure vector search misses exact-match queries that matter.
```

### Reranking — The Free Precision Boost

Retrieval returns top-k candidates (typically k=20-50). A cross-encoder reranker rescores these candidates for precision:

```
Retrieval pipeline:
  Dense search → top 50 chunks (fast, imprecise)
  BM25 search → top 50 chunks (fast, imprecise)
  RRF fusion → top 50 merged chunks
  
  Cross-encoder reranking:
  Score each of the top 50 chunks against the query
  Cross-encoder sees (query, chunk) pair and scores relevance
  Much more accurate than bi-encoder retrieval (sees full interaction)
  But much slower (can't pre-compute, must score each pair at query time)
  
  Rerank top 50 → select top 5 for LLM context
  
  Latency cost: ~20-50ms for 50 chunks
  Quality improvement: 10-20% precision improvement
  
  Models: ms-marco-MiniLM-L-12-v2 (free, open-source, 33M params)
          Cohere rerank API, Jina rerank
  
  This is the highest ROI addition to any RAG pipeline.
  20ms latency for 15% better precision. Most teams skip it.
```

### The Evaluation Framework

RAG quality must be measured at each stage independently:

```
Stage 1: Retrieval evaluation
  Metrics: Recall@k, Precision@k, MRR (Mean Reciprocal Rank)
  Question: "Did we retrieve the right chunks?"
  Ground truth: labeled (query, relevant_chunks) pairs
  
  If retrieval fails → fix chunking, embedding model, or hybrid search
  No amount of prompt engineering will fix bad retrieval.

Stage 2: Generation evaluation  
  Metrics: Faithfulness, Relevance, Completeness
  Question: "Did the LLM correctly use the retrieved chunks?"
  
  Faithfulness: Is the answer supported by the retrieved chunks?
    (detects hallucination — model inventing facts not in context)
  Relevance: Does the answer address the user's question?
  Completeness: Did the answer cover all relevant information?
  
  If generation fails with good retrieval → fix prompt or model

Automated evaluation frameworks:
  RAGAS: automated RAG evaluation using LLM-as-judge
  TruLens: faithfulness and relevance scoring
  Custom: LLM judges with specific rubrics for your domain
```

---

## What Production Systems Changed After This

**The RAG ecosystem.** RAG created entire product categories:
- **Vector databases:** Pinecone, Weaviate, Qdrant, Chroma, Milvus — purpose-built for dense retrieval
- **Embedding models:** text-embedding-3-small/large, E5, BGE, Cohere embed — optimized for RAG retrieval
- **RAG frameworks:** LangChain, LlamaIndex, Haystack — orchestration layers for RAG pipelines
- **Evaluation tools:** RAGAS, TruLens, DeepEval — automated RAG quality measurement

**"Chat with your documents" as a product category.** Every enterprise AI product that lets you ask questions about your own documents (Notion AI, Confluence AI, custom enterprise chatbots) is a RAG system. The pattern is universal.

**Knowledge management shifted.** Before RAG, enterprise knowledge was locked in documents that humans searched manually. After RAG, the same documents are chunked, embedded, indexed, and queried by AI. The quality of the AI depends on the quality of the documents — which created new incentives for better documentation.

---

## How This Connects to the Other 17 Papers

**Built on Paper 4's (GPT-3) in-context learning:** RAG works because LLMs can use information injected into the prompt at inference time. This is in-context learning (Paper 4) applied to retrieved documents. Without in-context learning, stuffing documents into the prompt wouldn't help.

**Bounded by Paper 1's (Attention) context window:** The O(n²) attention cost limits how many chunks you can stuff into context. More chunks = better recall but higher cost and latency. FlashAttention (Paper 8) and longer context windows (Paper 11, RoPE) expand this budget but don't eliminate the tradeoff.

**Improved by Paper 14's (PagedAttention) prefix caching:** RAG prompts typically have a stable prefix (system prompt + few-shot examples). PagedAttention's prefix caching reduces the cost of this stable portion by 90%.

**Quality depends on Paper 9 (CoT) decisions:** For complex RAG queries requiring synthesis across multiple chunks, Chain-of-Thought reasoning improves answer quality. For simple factual lookup from a single chunk, CoT adds cost without benefit. The routing decision (Paper 9) applies within RAG systems.

**Interacts with Paper 7 (LoRA):** When RAG retrieval quality plateaus, LoRA fine-tuning the LLM on (chunks, correct_answer) pairs can improve the model's ability to synthesize retrieved information — training the model to be a better reader of your specific document format.

---

## The Honest Take

**1. What most engineers miss when they skip this paper and just use the API:**

The original RAG paper is mostly historical — its specific architecture (DPR + BART, jointly trained) is not what production RAG looks like. But the principle — retrieval quality is the ceiling for generation quality — is the most important insight for any engineer building a RAG system. Most teams spend months tuning LLM prompts when the actual problem is that their chunking is bad, they're missing a reranker, or they're using dense-only search when hybrid is needed.

The diagnostic priority: when your RAG system gives bad answers, check retrieval FIRST. Pull the retrieved chunks and read them. If they're irrelevant, no prompt change will fix the answer. If they're relevant but the answer is still bad, THEN look at the prompt.

**2. The one non-obvious systems implication that blog posts never explain:**

The embedding model and the LLM are independently chosen, independently versioned, and can silently drift out of alignment. If you update your embedding model (from text-embedding-ada-002 to text-embedding-3-small), ALL your stored embeddings are now computed with a different model than your query embeddings. Retrieval quality can silently degrade because the vector spaces don't match. Re-embedding your entire corpus after an embedding model change is mandatory — and most teams don't do it because it's expensive and they don't realize the mismatch.

Similarly, if you change the LLM (GPT-3.5 → GPT-4), the few-shot examples you optimized for GPT-3.5 may not be optimal for GPT-4. The prompt and the model are coupled, and changing one without re-evaluating the other is a silent quality regression.

**3. Essential, useful context, or interesting history?**

**Essential. This is the most important applied paper in the curriculum.** Not because of its specific mechanism (which is outdated), but because RAG is the pattern behind the majority of production LLM applications. Understanding the retrieval pipeline (chunking, embedding, hybrid search, reranking), the evaluation framework (retrieval metrics vs generation metrics), and the core principle (retrieval quality is the ceiling) is directly actionable for any engineer building LLM-powered products.

Read the original paper for the concept. Build modern RAG using the production pipeline described above. The gap between the paper and production is large — but the paper established the principle that makes the entire pattern work: externalize knowledge to retrieval, inject at inference time, generate grounded in retrieved context.

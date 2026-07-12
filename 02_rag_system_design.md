# RAG System Design — The Deep Engineering Guide

> You've built a RAG pipeline. Here's what breaks at scale and how to fix it.  
> Source: Chip Huyen *AI Engineering* Ch. 6, Albada *Building Applications with AI Agents* Ch. 6, production systems.

---

## 1. The RAG Architecture You Actually Need

Most "RAG tutorials" show the naive pipeline. Production RAG has **7 stages**, each with critical decisions:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     PRODUCTION RAG PIPELINE                             │
│                                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │ QUERY    │→ │RETRIEVAL │→ │RERANKING │→ │ CONTEXT  │→ │GENERATION│ │
│  │PROCESSING│  │          │  │          │  │ ASSEMBLY │  │          │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │
│   - Expansion   - Dense       - Cross-enc   - Dedup       - LLM call  │
│   - HyDE         - Sparse      - LLM rerank  - Token mgmt  - Stream   │
│   - Routing      - Hybrid      - MMR         - Compression  - Cite     │
│   - Classify     - Filter      - Diversity   - Ordering                │
│                                                                         │
│  OFFLINE: [Ingestion] → [Chunking] → [Embedding] → [Indexing]         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Most RAG failures are retrieval failures, not generation failures.** If the right context isn't in the prompt, the LLM cannot produce a correct answer — no amount of prompt engineering fixes bad retrieval.

---

## 2. Retrieval: The Three Paradigms

### 2.1 Term-Based Retrieval (BM25)

BM25 is the most underrated component in RAG. It's fast, requires no GPU, no embedding model, and handles exact matches perfectly.

**The BM25 Scoring Formula:**

```
score(D, Q) = Σ  IDF(qi) × [ f(qi, D) × (k1 + 1) ]
              i              ─────────────────────────────
                             f(qi, D) + k1 × (1 - b + b × |D|/avgdl)

Where:
  qi      = query term i
  f(qi,D) = frequency of qi in document D
  |D|     = document length (in tokens)
  avgdl   = average document length in corpus
  k1      = term frequency saturation (default: 1.2)
  b       = length normalization (default: 0.75)
  IDF(qi) = log((N - n(qi) + 0.5) / (n(qi) + 0.5))
  N       = total documents
  n(qi)   = documents containing qi
```

**Why BM25 matters in production:**
- Zero cold start (no model to load)
- Handles exact terms: product codes, error IDs, entity names, acronyms
- Near-instant: microseconds per query on inverted index
- Perplexity CEO Aravind Srinivas: *"Making a genuine improvement over BM25 or full-text search is hard"*

```python
# BM25 with rank_bm25 — simple but effective
from rank_bm25 import BM25Okapi

# Indexing
corpus = [doc.split() for doc in documents]  # tokenized docs
bm25 = BM25Okapi(corpus, k1=1.2, b=0.75)

# Querying
query_tokens = query.split()
scores = bm25.get_scores(query_tokens)
top_k_indices = scores.argsort()[-10:][::-1]

# Production: use Elasticsearch or OpenSearch for scale
# They implement BM25 natively with inverted indices
```

**When BM25 fails:** Paraphrases ("car" vs "automobile"), synonyms, semantic similarity without shared vocabulary.

### 2.2 Dense Retrieval (Embedding-Based)

Encode query and documents into the same vector space. Retrieval = nearest neighbor search.

```python
from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer("BAAI/bge-large-en-v1.5")

# Offline: embed all documents
doc_embeddings = model.encode(documents, normalize_embeddings=True)

# Online: embed query + cosine similarity
query_embedding = model.encode([query], normalize_embeddings=True)
scores = query_embedding @ doc_embeddings.T  # cosine sim (normalized)
top_k = np.argsort(scores[0])[-10:][::-1]
```

**Bi-encoder vs Cross-encoder:**

```
Bi-Encoder (for retrieval — fast):
  ┌─────────┐     ┌─────────┐
  │ Encoder  │     │ Encoder  │
  │  (query) │     │  (doc)   │
  └────┬─────┘     └────┬─────┘
       │                │
       ↓                ↓
    query_vec        doc_vec     → cosine_sim(q, d) = score
  
  Time: O(1) per document (precompute doc vecs)
  Quality: Good for recall, weaker on nuance

Cross-Encoder (for reranking — accurate):
  ┌─────────────────────┐
  │      Encoder         │
  │  (query + doc)       │
  │  jointly             │
  └──────────┬──────────┘
             │
             ↓
         relevance_score
  
  Time: O(n) — must run model for EACH (query, doc) pair
  Quality: Much better — sees token-level interactions
  Use: Top-100 from bi-encoder → cross-encoder reranks to top-5
```

### 2.3 Hybrid Search (The Production Default)

**Almost always outperforms either dense or sparse alone.** Combine with Reciprocal Rank Fusion:

```python
def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """
    Combine multiple rankings into a single ranking.
    
    RRF score for document d = Σ 1/(k + rank_i(d))
    
    k=60 is the standard default from the original paper.
    Higher k → less weight on top results → more uniform blending.
    """
    scores = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            if doc_id not in scores:
                scores[doc_id] = 0.0
            scores[doc_id] += 1.0 / (k + rank)
    
    # Sort by RRF score descending
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)

# Usage: combine BM25 top-100 and dense retrieval top-100
dense_results = dense_search(query, k=100)   # returns list of doc_ids
sparse_results = bm25_search(query, k=100)   # returns list of doc_ids

# Fuse rankings
combined = reciprocal_rank_fusion([dense_results, sparse_results])
top_20 = [doc_id for doc_id, score in combined[:20]]
```

**Why RRF works better than score normalization:**
- Dense and sparse scores are on different scales (cosine sim vs BM25 score)
- Score distributions differ wildly between queries
- RRF uses only **ranks**, which are naturally normalized
- Robust: if one retriever fails completely, the other still contributes

**Native hybrid search support:** Weaviate, Qdrant, Elasticsearch (8.x+), OpenSearch, Pinecone

---

## 3. ANN Index Algorithms: Choosing Your Index

When you have 10M+ vectors, brute-force cosine similarity is too slow. ANN (Approximate Nearest Neighbor) indices trade recall for speed.

### HNSW (Hierarchical Navigable Small World)

```
Structure: Multi-layer graph
  Layer 3: [a] ──── [b]                    (sparse, long-range)
  Layer 2: [a] ── [c] ── [b] ── [d]       (medium connections)
  Layer 1: [a]-[e]-[c]-[f]-[b]-[g]-[d]    (dense, short-range)
  Layer 0: all nodes, fine-grained connections

Search: Start at top layer, greedily navigate to nearest neighbor,
        then descend to next layer and repeat with finer resolution.

Parameters:
  M = max connections per node (default: 16, higher = more accurate, more memory)
  efConstruction = search breadth during build (default: 200)
  efSearch = search breadth during query (default: 100, tune for recall)
```

| Pros | Cons |
|------|------|
| Best recall at high QPS | High memory (graph stored in RAM) |
| Supports incremental inserts | Slow build time for >100M vectors |
| No rebuild needed for updates | Memory = vectors + graph edges |
| Industry standard | |

### IVF-PQ (Inverted File + Product Quantization)

```
Step 1: Cluster vectors into C centroids (IVF)
Step 2: For each vector, store only its cluster + compressed residual (PQ)

Search: 
  1. Find closest clusters to query
  2. Search only vectors in those clusters (nprobe parameter)
  3. Approximate distance using PQ-compressed vectors

Parameters:
  nlist = number of clusters (√N is a good default)
  nprobe = clusters to search (trade recall for speed)
  m = PQ subspaces (higher = better accuracy, more memory)
```

| Pros | Cons |
|------|------|
| Much lower memory (10-50× compression) | Lower recall than HNSW |
| Fast for very large datasets | Requires full rebuild for major updates |
| Tunable accuracy/speed | Training step needed (cluster + PQ codebook) |

### DiskANN

```
For datasets that don't fit in RAM:
  - Graph index stored on SSD
  - In-memory cache for frequently accessed nodes
  - 95%+ recall at 5-10× more QPS than naive SSD search
  
Best for: 100M+ vectors with RAM constraints
Not for: latency-sensitive (<5ms) applications
```

### Choosing Your Index

```
< 1M vectors      → HNSW (brute force is also fine)
1M - 50M vectors  → HNSW if you have RAM, IVF-PQ if not
50M - 500M vectors → HNSW with quantized vectors, or IVF-PQ
500M+ vectors      → DiskANN or IVF-PQ with sharding
```

---

## 4. Chunking: Where Most RAG Systems Silently Fail

### The Core Tension

```
Large chunks (1000+ tokens):
  ✓ More context per chunk → less "missing info"  
  ✗ More noise → dilutes relevance signal
  ✗ Fewer chunks fit in context window
  ✗ Embedding captures a "blurry average" of topics

Small chunks (100-200 tokens):
  ✓ Higher precision → each chunk is about one thing
  ✓ More chunks in context → more diverse information
  ✗ Loses surrounding context → "orphan" chunks
  ✗ Cross-chunk references break ("as mentioned above...")
```

### Chunking Strategies Compared

#### Fixed-Size (Naive)
```python
def fixed_size_chunk(text: str, chunk_size: int = 512, overlap: int = 50):
    """Brute force. Breaks mid-sentence, mid-thought, mid-table."""
    chunks = []
    for i in range(0, len(text), chunk_size - overlap):
        chunks.append(text[i:i + chunk_size])
    return chunks
```
**Only use for:** Truly homogeneous text (logs, CSV rows, already-structured data).

#### Semantic Chunking
```python
from sentence_transformers import SentenceTransformer
import numpy as np

def semantic_chunk(text: str, model, threshold: float = 0.75, 
                   max_chunk_size: int = 1000):
    """
    Split on sentence boundaries; merge until semantic similarity drops.
    Preserves semantic cohesion within each chunk.
    """
    sentences = split_into_sentences(text)  # use spaCy or nltk
    embeddings = model.encode(sentences)
    
    chunks = []
    current_chunk = [sentences[0]]
    current_embedding = embeddings[0]
    
    for i in range(1, len(sentences)):
        # Cosine similarity between current chunk and next sentence
        sim = np.dot(current_embedding, embeddings[i]) / (
            np.linalg.norm(current_embedding) * np.linalg.norm(embeddings[i])
        )
        
        chunk_text = " ".join(current_chunk + [sentences[i]])
        
        if sim >= threshold and len(chunk_text) <= max_chunk_size:
            current_chunk.append(sentences[i])
            # Update rolling embedding (average)
            current_embedding = np.mean(
                [current_embedding, embeddings[i]], axis=0
            )
        else:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentences[i]]
            current_embedding = embeddings[i]
    
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    
    return chunks
```
**Cost:** 2-5× more expensive at ingestion (must embed every sentence). Worth it.

#### Hierarchical Parent-Child (Best Default for Production)

```python
def hierarchical_chunk(text: str, child_size: int = 200, parent_size: int = 1000):
    """
    Small chunks for RETRIEVAL (high precision).
    Return PARENT chunk for CONTEXT (high recall).
    
    Store both in your vector DB with a parent_id relationship.
    """
    # Create parent chunks
    parents = fixed_size_chunk(text, chunk_size=parent_size, overlap=0)
    
    all_chunks = []
    for parent_idx, parent_text in enumerate(parents):
        # Create child chunks within each parent
        children = fixed_size_chunk(parent_text, chunk_size=child_size, overlap=50)
        for child_text in children:
            all_chunks.append({
                "text": child_text,        # embed THIS for retrieval
                "parent_text": parent_text, # return THIS for context
                "parent_id": parent_idx,
                "metadata": {...}
            })
    
    return all_chunks

# At query time:
# 1. Dense search matches child chunks (precise)
# 2. Look up parent_id for each matched child
# 3. Return parent chunks (more context) for LLM prompt
# 4. Deduplicate parents (multiple children from same parent)
```

**Why this works:** You get the precision of small chunks for retrieval, but the context richness of large chunks for generation. The LLM sees the full paragraph, not a ripped-out sentence.

#### Late Chunking (Contextual Embeddings)

```
Standard chunking:
  Document → split into chunks → embed each chunk INDEPENDENTLY
  Problem: chunk loses document context → embedding is context-free

Late chunking:
  Document → embed ENTIRE document (full context) → pool at chunk boundaries
  Each chunk embedding has full document context → much better for long docs

Models supporting this: jina-embeddings-v3, ColBERT
```

### Chunking Decision by Document Type

| Document Type | Strategy | Why |
|---|---|---|
| Technical docs (markdown) | Split on headers (`#`, `##`), keep code blocks intact | Natural semantic boundaries |
| PDFs with tables | Extract tables as structured data separately; chunk prose only | Tables break with character splitting |
| Code | Split on function/class boundaries (AST parsing) | Functions are semantic units |
| Legal contracts | Clause-level splitting (section numbers) | Legal clauses are self-contained |
| Chat transcripts | Sliding window with overlap; summarize older turns | Temporal context matters |
| Product catalogs | One chunk per product (structured) | Each product is an entity |

---

## 5. Reranking: The 10× Quality Multiplier

First-stage retrieval (dense + sparse) gives you **recall**: the right document is *somewhere* in top-100. Reranking gives you **precision**: the right document is in top-5.

### Cross-Encoder Reranking

```python
from sentence_transformers import CrossEncoder

# Load reranker model
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

def rerank(query: str, documents: list[str], top_k: int = 5) -> list[tuple[str, float]]:
    """
    Cross-encoder scores each (query, doc) pair independently.
    Much more accurate than bi-encoder similarity.
    """
    # Create (query, document) pairs
    pairs = [(query, doc) for doc in documents]
    
    # Score all pairs
    scores = reranker.predict(pairs)
    
    # Sort by score
    scored_docs = sorted(
        zip(documents, scores), key=lambda x: x[1], reverse=True
    )
    return scored_docs[:top_k]

# Pipeline: retrieve 100 candidates, rerank to top 5
candidates = hybrid_search(query, k=100)  # fast, high recall
final = rerank(query, candidates, top_k=5)  # slow, high precision
```

**Latency budget:** Cross-encoder reranking adds 50-200ms for top-100 candidates. Almost always worth it.

### Cohere Rerank API (Production Shortcut)

```python
import cohere

co = cohere.Client("your-api-key")

results = co.rerank(
    model="rerank-english-v3.0",
    query="How does LoRA work?",
    documents=candidate_texts,
    top_n=5,
    return_documents=True
)
# Results include relevance_score for each document
```

### Maximal Marginal Relevance (MMR) — Diversity in Retrieval

```python
def mmr_rerank(query_embedding, doc_embeddings, documents, 
               k: int = 5, lambda_param: float = 0.7):
    """
    MMR balances RELEVANCE and DIVERSITY.
    
    MMR(d) = λ × sim(query, d) - (1-λ) × max(sim(d, d_selected))
    
    λ = 1.0: pure relevance (may return near-duplicates)
    λ = 0.0: pure diversity (may return irrelevant docs)
    λ = 0.5-0.7: typical production range
    """
    selected = []
    remaining = list(range(len(documents)))
    
    for _ in range(k):
        best_score = -float('inf')
        best_idx = -1
        
        for idx in remaining:
            # Relevance to query
            relevance = cosine_sim(query_embedding, doc_embeddings[idx])
            
            # Max similarity to already-selected documents
            if selected:
                redundancy = max(
                    cosine_sim(doc_embeddings[idx], doc_embeddings[s])
                    for s in selected
                )
            else:
                redundancy = 0
            
            mmr_score = lambda_param * relevance - (1 - lambda_param) * redundancy
            
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx
        
        selected.append(best_idx)
        remaining.remove(best_idx)
    
    return [documents[i] for i in selected]
```

**When MMR is critical:** Knowledge bases with overlapping/duplicate content. Without MMR, top-5 might be 5 near-identical chunks — wasting your context window.

---

## 6. Contextual Retrieval (Anthropic's Approach)

**The problem with standard chunking:** When you rip a chunk out of a document, it loses context. A chunk saying *"The company reported a 15% increase"* is useless without knowing WHICH company, WHICH metric, WHICH time period.

**Anthropic's solution:** Before embedding, prepend a **context summary** generated by an LLM:

```python
CONTEXT_PROMPT = """
<document>
{full_document}
</document>

Here is a chunk from that document:
<chunk>
{chunk}
</chunk>

Give a short, succinct context to situate this chunk within the overall 
document. Answer only with the context, nothing else.
"""

def contextual_chunk(document: str, chunks: list[str], llm) -> list[str]:
    """
    For each chunk, generate a contextual prefix that situates it
    within the full document.
    """
    contextualized = []
    for chunk in chunks:
        context = llm.generate(
            CONTEXT_PROMPT.format(full_document=document, chunk=chunk)
        )
        # Prepend context to chunk before embedding
        contextualized.append(f"{context}\n\n{chunk}")
    return contextualized

# Example output:
# Original chunk: "Revenue increased by 15% year-over-year."
# Contextualized:  "This chunk is from Acme Corp's Q3 2024 earnings report, 
#                   discussing financial performance in the cloud services 
#                   division. Revenue increased by 15% year-over-year."
```

**Anthropic's reported results:**
- Contextual embeddings alone: 35% reduction in retrieval failure
- Contextual embeddings + BM25 (hybrid): 49% reduction in retrieval failure

**Cost trade-off:** You pay for an LLM call per chunk at ingestion time. For a corpus that doesn't change frequently, this is a one-time cost that dramatically improves retrieval quality.

---

## 7. Query Processing: Before You Even Search

### Query Expansion

```python
def expand_query(query: str, llm) -> list[str]:
    """
    Generate multiple search queries from a single user question.
    Different phrasings retrieve different relevant documents.
    """
    prompt = f"""Given this search query, generate 3 alternative 
    phrasings that would help find relevant information. 
    Return each on a new line.
    
    Query: {query}"""
    
    expansions = llm.generate(prompt).strip().split("\n")
    return [query] + expansions  # original + expansions

# Example:
# Input: "How to handle errors in async Python?"
# Output: ["How to handle errors in async Python?",
#          "Python asyncio exception handling best practices",
#          "try except in coroutines and async functions",
#          "error handling patterns for aiohttp and asyncio"]
```

### HyDE (Hypothetical Document Embeddings)

```python
def hyde_search(query: str, llm, embedder, index, k: int = 10):
    """
    Instead of embedding the QUERY, embed a HYPOTHETICAL ANSWER.
    The hypothetical answer is in the same distribution as real documents,
    making it a better embedding signal for retrieval.
    """
    # Step 1: LLM generates a hypothetical answer (even if wrong)
    hypothetical = llm.generate(
        f"Answer this question in a detailed paragraph: {query}"
    )
    
    # Step 2: Embed the hypothetical (not the query)
    hyde_embedding = embedder.encode(hypothetical)
    
    # Step 3: Search with the hypothetical embedding
    results = index.search(hyde_embedding, k=k)
    return results

# Why it works: 
# Query: "What is LoRA?" → short, question-style embedding
# HyDE:  "LoRA (Low-Rank Adaptation) is a parameter-efficient 
#         fine-tuning technique that..." → document-style embedding
# The HyDE embedding is in the same "space" as actual documents.
```

**When HyDE fails:** If the LLM hallucinates badly, the hypothetical answer points to wrong documents. Use a fast/cheap model for hypothesis generation.

### Query Routing

```python
def route_query(query: str, llm) -> str:
    """
    Route queries to specialized retrieval pipelines.
    Different query types need different retrieval strategies.
    """
    prompt = f"""Classify this query into one of these categories:
    - FACTUAL: Looking for specific facts, definitions, or data
    - ANALYTICAL: Requires synthesis across multiple sources
    - CODE: Looking for code examples or technical implementation
    - CONVERSATIONAL: Follow-up question in ongoing dialogue
    
    Query: {query}
    Category:"""
    
    category = llm.generate(prompt).strip()
    
    routing = {
        "FACTUAL": {"retriever": "hybrid", "k": 5, "rerank": True},
        "ANALYTICAL": {"retriever": "dense", "k": 20, "rerank": True},
        "CODE": {"retriever": "bm25", "k": 10, "rerank": False},  # exact match matters
        "CONVERSATIONAL": {"retriever": "hybrid", "k": 3, "rerank": False},
    }
    return routing.get(category, routing["FACTUAL"])
```

---

## 8. Context Assembly: The Token Budget Problem

After retrieval and reranking, you have N relevant chunks. Now you must fit them into the LLM's context window alongside the system prompt, conversation history, and user query.

```python
class RAGContextAssembler:
    def __init__(self, max_context_tokens: int = 8000):
        self.budget = max_context_tokens
        
    def assemble(self, query: str, chunks: list[dict], 
                 system_prompt: str, conversation: list[str]) -> str:
        """
        Pack retrieved chunks into context window respecting token budget.
        Priority: system prompt > query > top chunks > conversation > lower chunks
        """
        # Fixed allocations
        system_tokens = count_tokens(system_prompt)
        query_tokens = count_tokens(query)
        conv_tokens = count_tokens("\n".join(conversation[-3:]))  # last 3 turns
        
        remaining = self.budget - system_tokens - query_tokens - conv_tokens - 200  # buffer
        
        # Pack chunks by relevance score (already sorted by reranker)
        selected_chunks = []
        used_tokens = 0
        seen_parents = set()  # deduplicate parent chunks
        
        for chunk in chunks:
            # Deduplicate: skip if parent already included
            parent_id = chunk.get("parent_id")
            if parent_id and parent_id in seen_parents:
                continue
                
            chunk_tokens = count_tokens(chunk["text"])
            if used_tokens + chunk_tokens <= remaining:
                selected_chunks.append(chunk["text"])
                used_tokens += chunk_tokens
                if parent_id:
                    seen_parents.add(parent_id)
            else:
                break  # budget exhausted
        
        # Assemble final prompt
        # KEY: put most relevant chunks FIRST and LAST (lost-in-middle mitigation)
        if len(selected_chunks) > 2:
            # Interleave: best at start, second-best at end
            reordered = [selected_chunks[0]]  # best chunk first
            reordered += selected_chunks[2:]   # middle chunks
            reordered += [selected_chunks[1]]  # second-best chunk last
            selected_chunks = reordered
        
        context_block = "\n\n---\n\n".join(selected_chunks)
        
        return f"""{system_prompt}

## Retrieved Context:
{context_block}

## Conversation:
{chr(10).join(conversation[-3:])}

## Current Question:
{query}

Answer based on the retrieved context above. If the context doesn't contain 
the answer, say so explicitly."""
```

### The "Lost in the Middle" Problem

Research shows LLMs best utilize information at the **beginning** and **end** of their context window. Content in the middle is ~40% less likely to influence the output.

**Mitigations:**
1. Put the most important chunk **first**, second most important **last**
2. Use compression for middle chunks (summarize before inserting)
3. Repeat critical facts at the end of the context block
4. Keep total context short — less middle means less loss

---

## 9. GraphRAG: When Flat Retrieval Isn't Enough

### When Standard RAG Fails

```
Query: "How are the themes in chapter 3 related to the conclusions in chapter 8?"

Standard RAG problem:
  - Retrieves chunks from chapter 3 OR chapter 8 (not both)
  - Can't connect cross-document relationships
  - Can't reason about entity relationships across chunks

GraphRAG solution:
  - Build a knowledge graph from your corpus
  - Entities = nodes, relationships = edges
  - Query traverses the graph to find connected information
```

### Building a Knowledge Graph for RAG

```python
# Extract entities and relationships from text using LLM
EXTRACTION_PROMPT = """Extract entities and relationships from this text.

Text: {chunk}

Output as JSON:
{{
  "entities": [
    {{"name": "...", "type": "person|org|concept|location", "description": "..."}}
  ],
  "relationships": [
    {{"source": "...", "target": "...", "relation": "...", "description": "..."}}
  ]
}}"""

def build_knowledge_graph(chunks: list[str], llm):
    """
    For each chunk, extract entities and relationships.
    Merge into a unified graph.
    """
    import networkx as nx
    G = nx.DiGraph()
    
    for chunk in chunks:
        extraction = llm.generate(
            EXTRACTION_PROMPT.format(chunk=chunk),
            response_format="json"
        )
        
        for entity in extraction["entities"]:
            G.add_node(entity["name"], 
                      type=entity["type"], 
                      description=entity["description"])
        
        for rel in extraction["relationships"]:
            G.add_edge(rel["source"], rel["target"], 
                      relation=rel["relation"],
                      description=rel["description"])
    
    return G

# Query-time: find relevant subgraph
def graph_retrieve(query: str, graph, embedder, k: int = 3):
    """
    1. Extract entities from query
    2. Find matching nodes in graph
    3. Retrieve connected subgraph (1-2 hops)
    4. Return subgraph context as text
    """
    # Entity linking: find query entities in graph
    query_entities = extract_entities(query)
    
    relevant_nodes = set()
    for entity in query_entities:
        # Find best matching node (fuzzy/embedding match)
        match = find_closest_node(entity, graph, embedder)
        if match:
            relevant_nodes.add(match)
            # Add 1-hop neighbors
            relevant_nodes.update(graph.neighbors(match))
            relevant_nodes.update(graph.predecessors(match))
    
    # Extract subgraph as context
    subgraph = graph.subgraph(relevant_nodes)
    context = format_subgraph_as_text(subgraph)
    return context
```

**GraphRAG trade-offs:**
| Pros | Cons |
|------|------|
| Handles multi-hop reasoning | Expensive to build (LLM call per chunk) |
| Cross-document relationships | Entity resolution is hard (same entity, different names) |
| Structured knowledge representation | Graph updates are complex |
| Explainable retrieval paths | Overkill for simple Q&A |

**When to use GraphRAG:** Legal research (statute → case → precedent chains), medical (symptom → diagnosis → treatment pathways), organizational knowledge (people → teams → projects → outcomes).

---

## 10. Production RAG Failure Modes (Debug Guide)

### Failure Mode: Wrong documents retrieved

```
Symptom:  LLM gives wrong answer, but confidently
Root cause: Retriever returns irrelevant documents
Debug:
  1. Log retrieved chunks + their scores for every query
  2. Sample 50 queries, manually check if correct doc is in top-20
  3. If correct doc exists but isn't retrieved:
     → Embedding model is wrong for your domain (try domain-specific model)
     → Chunking broke the relevant passage (try larger chunks)
     → Add BM25 to hybrid search (exact term matching)
  4. If correct doc doesn't exist in your corpus:
     → Knowledge gap, not retrieval problem
```

### Failure Mode: Right documents, wrong answer

```
Symptom:  Retrieved chunks contain the answer, but LLM ignores them
Root cause: "Lost in the middle" or instruction following failure
Debug:
  1. Check if answer-containing chunk is in middle of context
     → Move to first or last position
  2. Check if context is too long (LLM overwhelmed)
     → Reduce k, add reranker to select fewer better chunks
  3. Check if prompt formatting is wrong
     → Test with just the relevant chunk + question (does it work?)
  4. Check if LLM's parametric knowledge contradicts context
     → Add explicit instruction: "Answer ONLY based on provided context"
```

### Failure Mode: Hallucinated citations

```
Symptom:  LLM cites chunk [3] but the information isn't in chunk [3]
Root cause: LLM generates plausible-looking citations without grounding
Debug:
  1. Post-process: verify each citation by checking if claim appears in cited chunk
  2. Use structured output: force LLM to output (claim, source_chunk_id, quote)
  3. Cross-check: embed the claim and the cited chunk; if cosine_sim < threshold, flag
```

### Failure Mode: Latency spike

```
Symptom:  RAG response takes 5-10 seconds instead of 1-2
Root cause: Vector search or reranking too slow
Debug:
  1. Profile each stage independently:
     Query processing:    < 100ms (LLM call for expansion)
     Vector search:       < 50ms  (HNSW at < 10M vectors)
     BM25 search:         < 10ms
     Reranking (100 docs): < 200ms (cross-encoder)
     LLM generation:       500ms - 3s (depends on output length)
  2. If vector search slow: wrong index type, or index not in memory
  3. If reranking slow: reduce candidates from 100 to 50, or use lighter reranker
  4. If LLM slow: reduce context size, use faster model, enable streaming
```

---

## 11. Evaluation: Measuring RAG Quality

### RAGAS Framework

```python
# RAGAS provides 4 core metrics for RAG evaluation
# Install: pip install ragas

from ragas.metrics import (
    faithfulness,       # Is the answer grounded in the context?
    answer_relevancy,   # Does the answer address the question?
    context_precision,  # Are the retrieved contexts relevant?
    context_recall      # Are all relevant contexts retrieved?
)

# Faithfulness: checks each claim in the answer against the context
# Score 1.0 = every claim is supported by context
# Score 0.0 = all claims are hallucinated

# Answer Relevancy: embeds the answer and checks if it addresses the question
# Penalizes incomplete or off-topic answers

# Context Precision: checks if top-ranked contexts are relevant
# Penalizes retrieving irrelevant docs in high positions

# Context Recall: checks if all ground-truth relevant docs were retrieved
# Requires a labeled dataset with known relevant documents
```

### Building a RAG Evaluation Set

```python
def create_eval_set(documents: list[str], llm, n_questions: int = 100):
    """
    Generate question-answer-context triples for evaluation.
    
    For each document, generate questions that can be answered
    from that document, plus the expected answer.
    """
    eval_set = []
    
    for doc in random.sample(documents, min(n_questions, len(documents))):
        qa = llm.generate(f"""Based on this document, generate:
        1. A question that can be answered from this text
        2. The correct answer (directly from the text)
        3. A relevant quote from the text that supports the answer
        
        Document: {doc}
        
        Output as JSON: {{"question": "...", "answer": "...", "quote": "..."}}
        """)
        
        eval_set.append({
            "question": qa["question"],
            "ground_truth_answer": qa["answer"],
            "ground_truth_context": doc,
            "supporting_quote": qa["quote"]
        })
    
    return eval_set
```

### Key Metrics for Production RAG

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Retrieval Recall@10 | > 90% | Is the correct doc in top-10? |
| Retrieval Precision@5 | > 60% | Are top-5 docs all relevant? |
| Faithfulness | > 0.9 | Is every claim grounded? (RAGAS) |
| Answer Relevancy | > 0.85 | Does the answer address the question? |
| Latency (P95) | < 3s | End-to-end response time |
| Hallucination rate | < 5% | Claims not supported by context |

---

*Guide synthesized from: Chip Huyen "AI Engineering" Ch. 6, Albada "Building Applications with AI Agents" Ch. 6, Anthropic's contextual retrieval research, vLLM, RAGAS. Last updated: June 2026.*

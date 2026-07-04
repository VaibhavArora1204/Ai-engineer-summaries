# 30 — Case Study: Production RAG Pipeline at Scale

## Requirements Clarification

**This is your domain. This case study goes deepest.**

**Functional:**
- Multi-tenant RAG platform: 500 business customers, each with their own document corpus.
- Users upload documents (PDF, Markdown, HTML). Documents are chunked, embedded, and indexed.
- Users query the system: "What is our refund policy?" → The system retrieves relevant chunks and generates an answer using an LLM.
- Support for conversational follow-ups (multi-turn).

**Non-Functional:**
- Query latency: under 5 seconds p95 (including LLM generation).
- Ingestion: a new document should be searchable within 5 minutes of upload.
- Multi-tenancy: Tenant A's data must NEVER leak into Tenant B's responses.
- Cost efficiency: LLM API costs must be tracked per-tenant for billing.

---

## Back-of-Envelope Estimation

```
Tenants: 500 businesses.
Users: avg 50 users per tenant = 25,000 total users.
Queries: avg 30 queries per user per day = 750,000 queries/day.
QPS: 750K / 86,400 ≈ 9 queries/second average.
Peak (business hours, 8-hour window): 750K / 28,800 ≈ 26 QPS.
Peak burst (3x): ~80 QPS.

Document corpus:
  Per tenant: avg 5,000 documents, avg 10 pages each, avg 2,000 chars/page.
  Per tenant raw text: 5K × 10 × 2KB = 100 MB.
  Per tenant embeddings: 5K docs × 20 chunks/doc × 1536 dim × 4 bytes = 600 MB.
  500 tenants: 50 GB raw text + 300 GB embeddings = 350 GB total.
  
  Fits on a single large Postgres+pgvector instance (512 GB RAM).

LLM cost per query:
  Input: ~1,500 tokens (system prompt + retrieved chunks + user query) × $2.50/M = $0.00375
  Output: ~500 tokens × $10/M = $0.005
  Total: ~$0.009 per query
  
  750K queries/day × $0.009 = $6,750/day = ~$200K/month on LLM alone.
  
  A 25% semantic cache hit rate saves $50K/month.
  Caching is not optional — it's the #1 cost optimization.

Connection pool:
  80 QPS × 4 seconds avg hold time (LLM generation) = 320 concurrent connections needed.
  Default Postgres max_connections: 100. PROBLEM.
```

---

## High-Level Design

### The Request Path (Single Query)

```
1. User sends query: "What is our refund policy?"
   ↓
2. API Gateway: Auth, rate limit, tenant identification.
   ↓
3. Semantic Cache Check (Redis):
   - Embed the query.
   - Check if a similar query (cosine similarity > 0.95) was recently answered.
   - Cache HIT → return cached response. DONE.
   ↓
4. Retrieval:
   a. Embed the query using embedding model (local or API).
   b. Vector search in pgvector: top-10 most similar chunks WHERE tenant_id = X.
   c. (Optional) BM25 keyword search on the same chunks. Merge results (hybrid search — Module 27).
   d. Rerank top-10 to top-5 using a cross-encoder or LLM reranker.
   ↓
5. Prompt Construction:
   - System prompt + tenant-specific instructions + retrieved chunks + user query.
   - Estimate token count. If over context window, truncate least-relevant chunks.
   ↓
6. LLM Generation:
   - Call LLM API (OpenAI, Anthropic, or self-hosted).
   - Stream response back to user via SSE (Module 26).
   ↓
7. Post-Processing:
   - Cache the query+response in the semantic cache (Redis).
   - Log the full trace (Module 25): latency per step, tokens used, cost, chunks retrieved.
   - Write conversation history to the database for multi-turn support.
```

### The Ingestion Path (Document Upload)

```
1. User uploads document (PDF/Markdown/HTML).
   ↓
2. API stores the raw file in S3 (Module 34) and creates a metadata record in Postgres.
   Returns "Processing" immediately. (Async — Module 14.)
   ↓
3. Message published to ingestion queue (SQS/RabbitMQ):
   {"tenant_id": "abc", "document_id": "doc-123", "s3_path": "..."}
   ↓
4. Ingestion worker picks up the message:
   a. Download file from S3.
   b. Parse: extract text from PDF (PyMuPDF), Markdown, HTML.
   c. Chunk: split text into ~500-token chunks with 50-token overlap.
   d. Embed: generate embeddings for each chunk (batch API call to embedding model).
   e. Store: INSERT chunks + embeddings INTO pgvector with tenant_id.
   f. Update document metadata: status = "indexed."
   ↓
5. ACK the queue message. Document is now searchable.
```

---

## Deep Dive: The Genuinely Hard Parts

### 1. Connection Pool Exhaustion — The #1 Production Incident

This is the failure mode that brings down more RAG systems than any other.

**The incident:**
```
Time: 2:15 PM. Traffic: normal (30 QPS).
Step 4 (Retrieval) grabs a Postgres connection from the pool.
Step 6 (LLM Generation) takes 5 seconds.
The code holds the Postgres connection for the ENTIRE request (steps 4-7).

30 QPS × 5 seconds hold time = 150 concurrent connections needed.
Postgres max_connections = 100.
Connection pool = 20 per API server × 5 servers = 100.

Result: Connection pool exhausted. New requests queue.
Queue grows. Latency spikes from 5s to 30s. Users see timeouts.
Monitoring fires: "Connection pool wait time > 10s."
```

**The fix:**
```python
# BAD: Hold connection for entire request
async def handle_query(query, tenant_id):
    conn = await pool.acquire()  # Grab connection
    chunks = await search_vectors(conn, query, tenant_id)  # Uses connection
    prompt = build_prompt(chunks, query)
    response = await call_llm(prompt)  # 5 seconds — connection is HELD
    await save_response(conn, response)  # Uses connection
    await pool.release(conn)  # Release after 5+ seconds

# GOOD: Release connection between steps
async def handle_query(query, tenant_id):
    async with pool.acquire() as conn:  # ~20ms
        chunks = await search_vectors(conn, query, tenant_id)
    # Connection released. LLM call doesn't hold it.
    
    prompt = build_prompt(chunks, query)
    response = await call_llm(prompt)  # 5 seconds — NO connection held
    
    async with pool.acquire() as conn:  # ~1ms
        await save_response(conn, response)
    # Connection released.
```

The connection is now held for ~21ms total (retrieval + save) instead of 5,000ms (the entire request). At 30 QPS, you need 30 × 0.021 = 0.63 concurrent connections instead of 150. Your 20-connection pool handles it effortlessly.

### 2. Tenant Data Isolation

**The correctness nightmare:** Tenant A asks "What is our refund policy?" and receives chunks from Tenant B's documents. This is a data breach.

**Defense in depth:**

1. **Query-level isolation:** Every vector search query MUST include a tenant_id filter.
   ```sql
   SELECT content, embedding <=> $query_embedding AS distance
   FROM chunks
   WHERE tenant_id = $tenant_id  -- MANDATORY
   ORDER BY distance
   LIMIT 10;
   ```

2. **Schema-level isolation (optional but stronger):** Use Postgres Row-Level Security (RLS):
   ```sql
   ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
   CREATE POLICY tenant_isolation ON chunks
     USING (tenant_id = current_setting('app.current_tenant'));
   ```
   Even a buggy query without the WHERE clause returns only the current tenant's data.

3. **Cache isolation:** Semantic cache keys MUST include tenant_id. Without it, Tenant A's cached answer for "refund policy" might be served to Tenant B.
   ```
   Cache key: hash(tenant_id + query_embedding)
   ```

4. **LLM prompt isolation:** The system prompt should specify: "You are answering for {tenant_name}. Only use the provided context. Do not reference information from other sources."

### 3. Semantic Caching — The $50K/Month Savings

**How semantic caching works:**

Traditional caching uses exact key matching. Semantic caching uses embedding similarity.

```python
query = "What is the refund policy?"
query_embedding = embed(query)

# Search cache for similar queries (cosine similarity > 0.95)
cached = redis.search_vector("cache:{tenant_id}", query_embedding, threshold=0.95)

if cached:
    return cached.response  # Cache HIT — no LLM call
else:
    response = call_llm(...)
    redis.store_vector("cache:{tenant_id}", query_embedding, response, ttl=3600)
    return response
```

"What is the refund policy?" and "Can you tell me about your refund policy?" have embeddings with >0.95 cosine similarity. Both are served from the same cached response.

**The tradeoff:** The similarity threshold is the critical parameter.
- 0.99: Very conservative. Only near-exact paraphrases match. Low cache hit rate but high accuracy.
- 0.90: Aggressive. Looser matches. Higher cache hit rate but risk of serving wrong answers.
- 0.95: The typical production sweet spot.

### 4. Hybrid Search (Callback to Module 27)

Pure vector search misses exact keyword matches. Pure keyword search misses semantic matches.

**Production pattern: Reciprocal Rank Fusion (RRF)**

1. Run vector search → top 20 results with similarity scores.
2. Run BM25 keyword search → top 20 results with relevance scores.
3. Merge using RRF: for each document appearing in either list, compute:
   ```
   RRF_score = sum(1 / (k + rank_in_list)) for each list it appears in
   ```
   where k is a constant (typically 60).
4. Sort by RRF_score. Take top 5.

Documents that appear in BOTH lists get a boost (they're relevant both semantically and by keyword). Documents that appear in only one list are still included but ranked lower.

---

## Bottlenecks and Fixes

| Bottleneck | Trigger | Module Callback | Fix |
|-----------|---------|----------------|-----|
| Connection pool exhaustion | LLM latency holding DB connections | Module 09, 18 | Release connection before LLM call |
| LLM cost | Volume × price per token | Module 04, 07 | Semantic caching (25% hit rate = $50K/month saved) |
| Stale knowledge | Document updated, vector index not yet | Module 12, 13, 15 | Async ingestion pipeline with <5 min SLA |
| Tenant data leakage | Missing WHERE clause | Module 09 | Row-Level Security + mandatory tenant_id in all queries |
| Embedding API bottleneck | Bulk upload (10K docs) | Module 14 | Queue-based async ingestion with batch embedding calls |
| Context window overflow | Too many chunks retrieved | Module 16 | Token counting + truncation + reranking to select best chunks |

---

## What Real Systems Do Differently

- **Pinecone** customers often use a separate namespace per tenant for hard isolation (no shared index).
- **LangChain** users frequently over-architect the ingestion pipeline with complex splitters when a simple `RecursiveCharacterTextSplitter` with 500-token chunks and 50-token overlap works for 90% of use cases.
- Production systems use a **reranker** (Cohere Rerank, a small cross-encoder model) after retrieval to improve precision before sending chunks to the LLM — this is the single biggest quality improvement most teams discover.
- Most production systems use **PgBouncer** (a Postgres connection pooler) to multiplex application connections to a smaller pool of actual database connections, mitigating the pool exhaustion problem at the infrastructure level.

---

## Mentor's Take — What Actually Matters Here

**What matters:** This case study is a synthesis of almost every module in the curriculum. The connection pool incident (Module 09) is the most important lesson — it's real, it's common, and it's how the LLM's fundamentally different latency profile (seconds, not milliseconds) breaks assumptions that have held true for 20 years of web development. If you take one thing from this file, take the code fix: release the database connection before the LLM call.

**The AI-era connection:** This IS the AI-era system. Everything about this case study is what every AI startup building on RAG will face. The specific trap: teams optimize the model (better embeddings, better prompts, better chunking) while ignoring the infrastructure (connection pools, caching, cost tracking). The model improvements add 5% quality. The infrastructure improvements prevent the system from falling over entirely. Both matter, but the infrastructure is the one you can't demo to investors, so it gets neglected.

**Brutally honest advice:** Start with the boring architecture: Postgres + pgvector + Redis + FastAPI + one queue for ingestion. No microservices. No Kubernetes. No dedicated vector database. This handles 500 tenants and 80 QPS comfortably. When you outgrow it, you'll know exactly where the bottleneck is because you have one system to observe, not five. The teams that split RAG into 4 microservices on day one spend more time debugging inter-service communication than improving the product. Build the monolith, add observability, and split only when you have data showing where the bottleneck is.

---

## Check Your Understanding

1. Your RAG system processes 80 QPS with an average LLM response time of 4 seconds. Your Postgres connection pool has 20 connections. You're holding the connection for the entire request lifecycle. How many concurrent connections are needed? Does the pool survive, and what happens if it doesn't?

2. Tenant A uploads a new document containing an updated refund policy. The old version is still in the vector index. A user asks "What is the refund policy?" 2 minutes after the upload. What does the system return, and how do you detect this is a consistency problem rather than a model quality problem?

3. Your semantic cache has a similarity threshold of 0.92. A user asks "How do I cancel my subscription?" The cache finds a similar entry for "How do I delete my account?" (similarity 0.93). These are semantically similar but functionally different questions. What happens, and how do you fix it?

4. Explain why PgBouncer helps with connection pool exhaustion even though it doesn't reduce the actual number of queries hitting Postgres.

5. You're choosing between pgvector (in-Postgres) and Pinecone (managed vector DB) for 500 tenants with 350 GB of embeddings. What is the single strongest argument for each, and what does the choice depend on?

---

### Answers

1. **Answer:** 80 QPS × 4 seconds = 320 concurrent connections needed. The pool has 20 connections. It instantly exhausts. The 21st concurrent request waits for a free connection. With 320 requests needing connections simultaneously, the queue grows, and requests start timing out. Users experience 30+ second latencies or connection errors. Fix: release the connection before the LLM call, reducing hold time from 4 seconds to ~20ms. New requirement: 80 × 0.02 = 1.6 concurrent connections. The 20-connection pool handles it with 18 connections to spare.

2. **Answer:** The system returns the OLD refund policy because the new document hasn't been ingested into the vector index yet (it takes up to 5 minutes). This looks like a hallucination or a "the AI is wrong" complaint, but it's actually a replication lag / eventual consistency problem (Module 12). Detection: compare the document's `updated_at` timestamp in Postgres with the `indexed_at` timestamp. If `updated_at > indexed_at`, the vector index is stale. You can surface this to the user: "Note: some documents are still being indexed and may not be reflected in this answer."

3. **Answer:** The cache returns the answer for "How do I delete my account?" to the user who asked about canceling their subscription. This is incorrect — canceling a subscription is different from deleting an account. The user gets a wrong answer served confidently from cache. Fix: increase the similarity threshold to 0.95-0.97 (more conservative matching). Accept a lower cache hit rate in exchange for higher answer accuracy. Alternatively, add a "verification step" where the cached answer is compared against the current query's intent using a lightweight LLM classifier before being served.

4. **Answer:** PgBouncer sits between your application and Postgres. Your 5 API servers each open 20 connections to PgBouncer (100 total application connections), but PgBouncer maintains only 30 actual connections to Postgres. When an application connection releases a query, PgBouncer immediately reuses the underlying Postgres connection for another application connection. This works because most application connections are idle most of the time (waiting for the LLM, waiting for the next request). PgBouncer multiplexes the "bursty" application usage pattern onto a smaller, steadier pool of database connections.

5. **Answer:** Strongest argument for pgvector: operational simplicity. One database for relational data AND vector search. No sync pipeline to maintain, no second system to monitor, ACID transactions across vector and relational data. Strongest argument for Pinecone: purpose-built performance at scale. HNSW indexing optimized for vector search, built-in sharding, managed infrastructure. The choice depends on scale and team size. Under 500M vectors with a team under 10 engineers: pgvector. Over 1B vectors or needing sub-10ms query latency with complex filtering: dedicated vector DB. For 500 tenants with 350 GB, pgvector on a single large instance is sufficient and dramatically simpler.

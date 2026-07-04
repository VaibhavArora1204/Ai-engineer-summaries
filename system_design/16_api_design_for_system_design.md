# 16 — API Design for System Design

## The Problem

Your system has services that need to talk to each other. Your frontend needs to talk to your backend. Third-party customers need to integrate with your platform. Every interaction requires an API — a contract that defines: what can I ask for, what format does the request take, what format does the response take, and what happens when things go wrong.

Bad API design is permanent. Once external customers depend on your `POST /api/v1/embeddings` endpoint, changing its request format or removing a field breaks their integration. You can fix a bad database schema with a migration. You can fix bad internal code with a refactor. A bad public API contract is a liability you carry for years, because someone, somewhere, has hardcoded their system against your current response format. API design is one of the few areas where getting it right the first time genuinely matters.

---

## The Naive Approach and Why It Fails

**Naive approach: "Just expose my database models as JSON endpoints."**

```python
# "API" that mirrors the database schema directly
@app.get("/users/{id}")
def get_user(id):
    return db.query("SELECT * FROM users WHERE id = ?", id)
    # Returns: {"id": 1, "name": "Alice", "password_hash": "bcrypt$...",
    #           "internal_org_id": 42, "stripe_customer_id": "cus_abc"}
```

This leaks internal implementation details (password hashes, internal IDs, third-party identifiers), couples your API contract to your database schema (a schema migration breaks the API), and exposes more data than the client needs (violating the principle of least privilege). The API should be a carefully designed contract, not a transparent window into your database.

---

## The Real Mechanism

### REST — The Standard for External APIs

REST (Representational State Transfer) models your API as resources (nouns) with standard HTTP methods (verbs):

```
Resource: /users
  GET    /users          → List users         (200 OK)
  POST   /users          → Create a user      (201 Created)
  GET    /users/{id}     → Get one user        (200 OK)
  PUT    /users/{id}     → Replace user fully  (200 OK)
  PATCH  /users/{id}     → Update user fields  (200 OK)
  DELETE /users/{id}     → Delete a user       (204 No Content)

Resource: /documents/{id}/chunks
  GET    /documents/42/chunks    → Get chunks for document 42
  POST   /documents/42/chunks    → Add a chunk to document 42
```

**REST Design Principles That Matter:**
- **Resources are nouns, methods are verbs.** Not `POST /createUser` — use `POST /users`.
- **Use HTTP status codes correctly.** `200` for success, `201` for created, `400` for bad request, `401` for unauthorized, `404` for not found, `429` for rate limited, `500` for server error. Don't return `200` with `{"error": "not found"}` — that forces clients to parse the body to detect errors.
- **Use plural nouns.** `/users`, not `/user`. `/documents`, not `/document`.
- **Nest resources for relationships.** `/users/42/documents` = "documents belonging to user 42."
- **Pagination for lists.** Never return unbounded lists. Always paginate: `GET /documents?page=2&per_page=20` or cursor-based: `GET /documents?cursor=eyJ...&limit=20`.

### RPC — The Standard for Internal Service Communication

RPC (Remote Procedure Call) models your API as function calls, not resources:

```
gRPC example (protocol buffers):
  service EmbeddingService {
    rpc GenerateEmbedding(EmbeddingRequest) returns (EmbeddingResponse);
    rpc BatchEmbed(BatchEmbedRequest) returns (BatchEmbedResponse);
  }
  
  message EmbeddingRequest {
    string text = 1;
    string model = 2;  // "text-embedding-3-small"
  }
  
  message EmbeddingResponse {
    repeated float vector = 1;  // [0.12, 0.45, ..., 0.89]
    int32 token_count = 2;
  }
```

**Why gRPC for internal, REST for external:**
- gRPC uses binary serialization (protobuf): 10x smaller payloads, 5-10x faster parsing than JSON.
- gRPC generates client and server code from the `.proto` definition — type-safe, auto-documented.
- gRPC supports streaming (server-stream, client-stream, bidirectional) — critical for LLM token streaming.
- But: gRPC doesn't work in browsers without a proxy (gRPC-Web), requires code generation tooling, and is harder to debug (binary protocol, not human-readable). REST is simpler for external consumers who just want to `curl` your API.

### GraphQL — When Clients Need Flexible Queries

```graphql
# Client specifies exactly what fields it needs
query {
  document(id: 42) {
    title
    chunks(limit: 5) {
      content
      similarity_score
    }
    uploaded_by {
      name
    }
  }
}

# Server returns exactly that shape — no over-fetching, no under-fetching
{
  "data": {
    "document": {
      "title": "NDA Contract",
      "chunks": [...],
      "uploaded_by": { "name": "Alice" }
    }
  }
}
```

**The honest take:** GraphQL solves over-fetching (REST returns 30 fields when the client needs 3) and under-fetching (REST requires 3 requests for data that could be one query). It's excellent for frontend-heavy applications with complex, nested data. It's overkill for most backend-to-backend communication and most simple APIs. The operational cost (query complexity limits, N+1 query problems, caching difficulties) is often underestimated.

### API Versioning — Managing Change Without Breaking Clients

```
URL versioning (most common):
  /api/v1/embeddings    → original format
  /api/v2/embeddings    → new format (different request/response schema)
  
  Run both simultaneously. Deprecate v1 after 6 months.
  
Header versioning:
  GET /api/embeddings
  Accept-Version: 2
  
  Cleaner URLs, harder for clients to discover versions.

The practical approach:
  1. Use URL versioning (/api/v1/) — it's the most explicit and debuggable.
  2. Never break a version. Adding fields is safe. Removing fields breaks clients.
  3. When you must break: create a new version, run both, deprecate the old one.
  4. Never maintain more than 2 versions simultaneously. The operational cost is too high.
```

### Rate Limiting — Protecting Your System From Abuse and Overload

Rate limiting controls how many requests a client can make in a time window. For AI APIs, this is two-dimensional: you're limiting both request count AND token consumption.

**Token Bucket (The Most Common Algorithm):**

```
Mechanism:
  Bucket has capacity C (e.g., 100 tokens).
  Tokens are added at rate R (e.g., 10 tokens/second).
  Each request consumes 1 token.
  If bucket is empty → reject request (429 Too Many Requests).

Properties:
  - Allows bursts up to C requests.
  - Sustained rate limited to R requests/second.
  - Smooths traffic naturally.

Example:
  C=100, R=10/sec
  T=0:   Bucket has 100 tokens. Client sends 50 requests → all pass. Bucket: 50.
  T=1:   Bucket refilled to 60. Client sends 20 → all pass. Bucket: 40.
  T=2:   Bucket refilled to 50. Client sends 80 → 50 pass, 30 rejected (429).
```

**Leaky Bucket:**
```
Mechanism:
  Requests go into a fixed-size queue (the bucket).
  Requests drain from the queue at a fixed rate.
  If the queue is full → reject (429).
  
Properties:
  - Enforces a perfectly smooth output rate.
  - No bursts — every request waits in the queue.
  - Good for: APIs with strict rate limits from upstream providers.
```

**Fixed Window:**
```
Mechanism:
  Count requests per fixed time window (e.g., per minute).
  If count > limit → reject.
  
Properties:
  - Simple to implement (Redis INCR + EXPIRE).
  - Problem: Burst at window boundary. If limit is 100/minute:
    Client sends 100 at 0:59 → all pass (window 1).
    Client sends 100 at 1:01 → all pass (window 2).
    200 requests in 2 seconds. Effective rate: 100x the limit.
```

**Sliding Window (Fixes the boundary problem):**
```
Mechanism:
  Weighted average of current window and previous window.
  Example: 70% through current minute, previous minute had 80 requests,
  current minute has 30 requests.
  Effective count = 80 × 0.30 + 30 = 54 (compare to limit).
  
Properties:
  - Smooths the boundary burst problem.
  - Slightly more complex to implement.
```

**The AI-Era Rate Limiting Problem — Two Dimensions:**

```
Traditional rate limiting: 100 requests/minute.
  Each request costs roughly the same (10ms of compute).

AI API rate limiting: 100 requests/minute AND 100,000 tokens/minute.
  A request sending 10 tokens costs $0.00003.
  A request sending 50,000 tokens costs $1.50.
  Rate limiting by request count alone lets one 50K-token request 
  consume half your token budget.

Solution: Two rate limiters composted:
  1. Request rate limiter: 100 RPM (token bucket)
  2. Token rate limiter: 100,000 TPM (token bucket, where each request 
     consumes token_count tokens instead of 1)
  
  A request passes only if BOTH rate limiters allow it.
  
  The naive Redis INCR counter doesn't handle this.
  You need a token bucket that decrements by a variable amount per request.
```

### Idempotency Keys — Safe Retries

When a client's request times out, they don't know if the server processed it. If they retry, the server might process it twice — charging a credit card twice, creating two documents, sending two emails.

```
Solution: Idempotency keys (Module 24).

Client sends:
  POST /api/v1/embeddings
  Idempotency-Key: 7f8a9b2c-...
  {"text": "Hello world"}

Server behavior:
  1. Check if this idempotency key has been seen before.
  2. If yes → return the cached response (no re-processing).
  3. If no → process the request, store the result keyed by idempotency key.
  
Now retries are safe: the same request with the same key always 
returns the same result, no matter how many times it's sent.
```

---

## Concrete Example From a Real System

**Illustrative: API Design for a RAG-as-a-Service Platform**

```
Public REST API (for customers):
  POST   /api/v1/documents                    → Upload document
  GET    /api/v1/documents/{id}               → Get document metadata
  GET    /api/v1/documents/{id}/status         → Get processing status
  DELETE /api/v1/documents/{id}               → Delete document + chunks
  
  POST   /api/v1/query                         → Ask a question (RAG query)
    Request:  {"query": "What is the termination clause?", "top_k": 5}
    Response: {"answer": "...", "sources": [...], "tokens_used": 1234}
  
  Rate limits (per API key):
    100 RPM (request rate)
    500,000 TPM (token rate)
    Headers: X-RateLimit-Remaining: 87, X-RateLimit-Reset: 1720000060

Internal gRPC (between services):
  EmbeddingService.BatchEmbed()          → chunking → embedding (protobuf)
  VectorSearchService.SimilaritySearch() → pgvector query (protobuf)
  LLMService.Generate()                 → model inference (streaming protobuf)
```

---

## The Tradeoffs

| Style | Best For | Gives Up |
|-------|----------|----------|
| REST | External APIs, simplicity, broad tooling support | Verbose (over-fetching), multiple requests for complex data |
| gRPC | Internal services, high throughput, streaming | Browser support, human readability, debugging ease |
| GraphQL | Complex frontends, flexible client queries | Caching difficulty, query complexity attacks, N+1 problems |

| Rate Limiter | Best For | Weakness |
|-------------|----------|----------|
| Token bucket | General purpose, allows bursts | Requires tracking token count per bucket |
| Leaky bucket | Strict smooth rate | No burst tolerance |
| Fixed window | Simplest implementation | Boundary burst problem (2x limit in 2 seconds) |
| Sliding window | Smooth rate without boundary bursts | More complex to implement |

---

## How This Connects to Other Modules

- **Module 06** (Load Balancing): L7 load balancers can enforce rate limits, route by URL path, and terminate TLS — they're API gateways.
- **Module 14** (Message Queues): Async APIs (202 Accepted) are built on queues. The queue decouples the API response from the processing.
- **Module 18** (Service Communication): gRPC is the internal communication pattern. Circuit breakers and retries apply here.
- **Module 24** (Idempotency): Idempotency keys make API retries safe. Critical for any API that has side effects.
- **Module 26** (Real-time): Streaming API responses (LLM token streaming) use SSE or WebSockets, not REST.
- **Module 29** (Case Study: Rate Limiter): Full implementation of a distributed rate limiter.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** Know REST resource design (nouns, HTTP methods, status codes) — it comes up in every interview. Know the rate limiting algorithms (token bucket, sliding window) — you'll be asked to design a rate limiter. Know why gRPC is better for internal calls and REST for external. Know API versioning (URL-based, never break a version). Know idempotency keys. Everything else (HATEOAS, Richardson Maturity Model, content negotiation) is trivia.

**The AI-era connection:** Rate limiting against a token budget and a provider's RPM/TPM simultaneously is a two-dimensional rate limiting problem that most rate limiter implementations were never designed for. A naive Redis INCR counter tracks request count but not token count. You need two rate limiters composed: one for RPM (standard), one for TPM (where each request decrements the counter by its token count, not by 1). Most teams implement the RPM limiter and forget the TPM limiter — then get surprised when one customer's 50K-token request consumes half the token budget in a single call. The composability of rate limiters (both must pass for the request to proceed) is the conceptual leap.

**Brutally honest advice:** The biggest API design mistake I see from AI engineers is not having a versioning strategy until it's too late. Your first API response includes a field called `score`. Six months later, you realize it should be `relevance_score` because you've added `confidence_score` and `cosine_score`. If you don't have versioning, you can't change it — some customer has `response.score` hardcoded in their production system. The fix is trivial: always start with `/api/v1/`. It costs nothing. Not having it costs you a breaking change. Second mistake: not paginating list endpoints. `GET /documents` returns all 50,000 documents in one response. The client OOMs, your server OOMs, everyone is unhappy. Always paginate. Default page size: 20. Max page size: 100.

---

## Check Your Understanding

1. You have an endpoint `POST /api/v1/generate` that calls an LLM. The request takes 10 seconds. The client's connection drops at 9 seconds. They retry. Without an idempotency key, what happens? With one?

2. Your rate limiter uses a fixed window of 100 requests/minute. A client sends 99 requests at 0:59 and 100 requests at 1:01. How many requests pass? Why is this a problem, and which algorithm fixes it?

3. You need to rate limit both by request count (100 RPM) AND by token count (500K TPM). A request consuming 200K tokens arrives when the client has 80 RPM remaining and 300K TPM remaining. Does it pass? What if the next request consumes 200K tokens?

4. Why is gRPC better than REST for an internal embedding service that processes 10,000 requests/second? Cite two specific technical advantages.

5. A customer integrates with your `GET /api/v1/documents` endpoint. You realize you need to add pagination. Can you add `?page=1&per_page=20` as an optional parameter without breaking existing clients who don't send it? What default behavior makes this backward-compatible?

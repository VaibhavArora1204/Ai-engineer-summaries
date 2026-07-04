# 29 — Case Study: Distributed Rate Limiter

## Requirements Clarification

**Functional:**
- Enforce rate limits on API requests: e.g., "User X can make 100 requests per minute."
- Support multiple limit dimensions: per-user, per-API-key, per-IP, per-endpoint.
- Return `429 Too Many Requests` when a limit is exceeded, with a `Retry-After` header.

**Non-Functional:**
- Sub-millisecond decision time. The rate limiter sits in the critical request path — every microsecond of overhead affects every request.
- Must work across multiple API server instances. If the rate limit is 100 req/min and you have 10 servers, a user shouldn't get 100 requests per server (1,000 total). The limit must be global.
- Must handle edge cases: clock synchronization, burst allowance, and the two-dimensional AI problem (request count + token count).

---

## Back-of-Envelope Estimation

```
Traffic:
  10,000 requests/second across all users.
  Each request triggers 1 rate limit check.
  = 10,000 Redis operations/second.
  
  Redis handles ~100,000+ operations/second on a single instance.
  A single Redis instance is sufficient for the rate limiter data.

Storage:
  Each rate limit counter: ~100 bytes (key + counter + TTL metadata).
  100,000 active users with per-user limits: ~10 MB.
  Trivial — fits entirely in Redis memory.

Verdict:
  Rate limiting is a metadata problem, not a storage problem.
  A single Redis instance handles this comfortably.
  The challenge is algorithm correctness, not scale.
```

---

## High-Level Design

```
Client → Load Balancer → Rate Limiter Middleware → API Server → Backend

Rate Limiter checks Redis:
  - Key: "ratelimit:{user_id}:{endpoint}:{time_window}"
  - If count < limit: increment counter, allow request.
  - If count >= limit: reject with 429.
```

The rate limiter is typically implemented as middleware in the API gateway or as a shared library in each API server instance. All instances share the same Redis backend, making the rate limit global.

---

## Deep Dive: Rate Limiting Algorithms

### Algorithm 1: Fixed Window Counter

**Mechanism:**
- Divide time into fixed windows (e.g., 1-minute windows starting at :00, :01, :02...).
- For each user, maintain a counter for the current window.
- Key: `ratelimit:user123:2024-01-15T10:05` → Counter: 47

```python
key = f"ratelimit:{user_id}:{current_minute}"
count = redis.incr(key)
if count == 1:
    redis.expire(key, 60)  # Auto-delete after the window
if count > 100:
    return 429  # Too Many Requests
```

**Problem — Boundary Burst:**
Limit is 100/minute. User sends 100 requests at 10:00:59 (end of window). Counter resets at 10:01:00. User sends 100 more requests at 10:01:01. In a 2-second span, 200 requests went through despite a 100/minute limit.

### Algorithm 2: Sliding Window Log

**Mechanism:**
- Store the timestamp of every request in a sorted set.
- On each new request, remove all timestamps older than 1 minute.
- Count remaining entries. If count >= limit, reject.

```python
now = time.time()
key = f"ratelimit:{user_id}"
redis.zremrangebyscore(key, 0, now - 60)  # Remove old entries
count = redis.zcard(key)
if count >= 100:
    return 429
redis.zadd(key, {str(now): now})
redis.expire(key, 60)
```

**Pros:** Perfectly accurate. No boundary burst problem.
**Cons:** Memory-hungry. Stores one entry per request. At 100 requests/minute × 100K users = 10M entries in Redis. Also, multiple Redis operations per check (non-atomic without Lua scripting).

### Algorithm 3: Sliding Window Counter (The Practical Choice)

**Mechanism:**
A weighted average between the current fixed window and the previous fixed window.

```
previous_window_count = 85 (requests in the previous minute)
current_window_count = 30 (requests in the current minute so far)
elapsed_fraction = 0.4 (we're 24 seconds into the current 60-second window)

weighted_count = previous_window × (1 - elapsed_fraction) + current_window × 1
               = 85 × 0.6 + 30 × 1
               = 51 + 30 = 81

Limit = 100. 81 < 100, so allow the request.
```

**Pros:** Minimal memory (2 counters per user per endpoint). Eliminates the boundary burst problem with ~99.8% accuracy. Fast (2 Redis operations).
**Cons:** Approximate — not perfectly accurate, but the error is negligible in practice.

This is the algorithm most production rate limiters use.

### Algorithm 4: Token Bucket

**Mechanism:**
- Each user has a "bucket" with a maximum capacity (e.g., 100 tokens).
- Tokens are added to the bucket at a fixed rate (e.g., 100 tokens per minute, or ~1.67 tokens per second).
- Each request consumes 1 token. If the bucket is empty, the request is rejected.
- The bucket can accumulate tokens up to the maximum, allowing controlled bursts.

```python
# Token bucket state: {tokens: float, last_refill: timestamp}
now = time.time()
elapsed = now - state.last_refill
state.tokens = min(max_tokens, state.tokens + elapsed * refill_rate)
state.last_refill = now

if state.tokens >= 1:
    state.tokens -= 1
    allow_request()
else:
    reject_request()
```

**Pros:** Allows controlled bursts (up to bucket capacity). Smooth rate limiting. Used by AWS API Gateway.
**Cons:** Slightly more complex state management (float instead of integer counter).

### Algorithm 5: Leaky Bucket

**Mechanism:**
- Requests enter a queue (the bucket). The queue has a maximum size.
- Requests are processed from the queue at a fixed rate.
- If the queue is full, new requests are dropped.

**Pros:** Smooth, constant output rate. No bursts.
**Cons:** Recent requests are delayed behind queued requests. Not suitable for real-time APIs where latency matters.

---

## Deep Dive: The Two-Dimensional AI Rate Limiting Problem

Classic rate limiters track one dimension: requests per time window.

LLM APIs introduce a second dimension: **tokens per time window.**

OpenAI's rate limits are:
- 500 requests per minute (RPM)
- 200,000 tokens per minute (TPM)

A user might send 1 request with a 150,000-token document. This passes the RPM check (1 < 500) but should be throttled by the TPM check (150,000 is 75% of the budget in a single request).

**Solution — Composed Rate Limiters:**

```python
rpm_allowed = check_rate_limit(user_id, dimension="requests", limit=500, window=60)
tpm_allowed = check_rate_limit(user_id, dimension="tokens", limit=200000, window=60, 
                                cost=count_tokens(request.body))

if rpm_allowed and tpm_allowed:
    forward_request()
else:
    return 429  # Specify which limit was hit in the response body
```

The token count must be estimated BEFORE forwarding the request to the LLM (count input tokens using a tokenizer like `tiktoken`). Output tokens are harder — you don't know how many the model will generate until it's done. The common approach: estimate a reasonable maximum output (e.g., 4,000 tokens for a `max_tokens=4096` request) and debit that from the budget, then credit back unused tokens after the response.

**Redis implementation for token-based limiting:**

```python
# Token budget as a sliding window counter
key = f"tpm:{user_id}:{current_minute}"
current_tokens = redis.incrby(key, estimated_token_count)
if current_tokens > 200000:
    redis.decrby(key, estimated_token_count)  # Rollback
    return 429
redis.expire(key, 120)  # Keep for 2 minutes for sliding window
```

---

## Distributed Rate Limiting: The Multi-Instance Problem

With 10 API servers, each server has its own rate limiter middleware. All must agree on the global count. Two approaches:

**Approach 1: Shared Redis (Standard)**
All instances read/write counters in a shared Redis instance. This is the standard approach. Redis operations are atomic (`INCR` is atomic), so concurrent increments from different servers are safe.

**Approach 2: Local + Sync (Approximate)**
Each server maintains a local counter and periodically syncs to Redis. This reduces Redis traffic but introduces inaccuracy — a user might exceed the global limit because the local counters haven't synced yet.

**Practical choice:** Use shared Redis. At 10K-100K requests/second, a single Redis instance handles the rate limit checks with sub-millisecond latency. The complexity of local-then-sync is rarely justified.

---

## The Tradeoffs

| Algorithm | Accuracy | Memory | Burst Handling | Complexity |
|-----------|----------|--------|---------------|------------|
| Fixed Window | Low (boundary burst) | Very Low | Poor | Very Low |
| Sliding Window Log | Perfect | High | Perfect | Medium |
| Sliding Window Counter | ~99.8% | Very Low | Good | Low |
| Token Bucket | Good | Low | Controlled bursts | Medium |
| Leaky Bucket | Good | Medium (queue) | None (constant rate) | Medium |

---

## Mentor's Take — What Actually Matters Here

**What matters:** The sliding window counter is the algorithm you'll use 90% of the time. Understand it deeply. Token bucket matters when you need burst allowance (letting a user send 10 requests in 1 second if they haven't used their quota in the last minute). The two-dimensional rate limiting problem (RPM + TPM) is the most practically relevant challenge for AI engineers right now — and most naive Redis-counter rate limiters don't handle it.

**The AI-era connection:** The two-dimensional rate limiting problem IS the rate limiting problem for anyone building on LLM APIs. If you only track requests and ignore tokens, a single user can send one massive request and consume your entire provider quota. If you only track tokens, you might allow a user to send 10,000 tiny requests that overwhelm your connection pool despite consuming few tokens.

The deeper problem: **cost-based rate limiting.** Different models cost different amounts. GPT-4o costs 10x more per token than GPT-4o-mini. A cost-aware rate limiter doesn't just track requests or tokens — it tracks estimated dollar cost per user per billing period. This is a third dimension: RPM × TPM × $/minute.

**Brutally honest advice:** Don't build your own rate limiter from scratch unless you're doing it as a learning exercise. In production, use your API gateway's built-in rate limiting (AWS API Gateway, Kong, Nginx's `limit_req`). These are battle-tested and handle edge cases (clock drift, Redis failover, distributed coordination) that your first implementation will miss. Build a custom rate limiter only when you need the two-dimensional RPM+TPM logic that generic solutions don't support.

---

## Check Your Understanding

1. A user sends 95 requests at 10:00:58 and 95 requests at 10:01:02. The limit is 100 requests per minute. Using a Fixed Window Counter, does this pass? Using a Sliding Window Counter, does this pass? Show the math.

2. Your rate limiter uses a shared Redis instance. Redis is down for 30 seconds. What happens to all incoming API requests? Describe two different failure modes (fail-open vs fail-closed) and when each is appropriate.

3. A user sends a single API request containing a 180,000-token document to your LLM proxy. Your TPM limit is 200,000. How does the two-dimensional rate limiter handle this? What happens 30 seconds later when the same user sends another 50,000-token request?

4. You have 5 API servers behind a load balancer. Each has a local rate limiter counting requests in-memory (no shared Redis). The global limit is 100 requests per minute per user. What is the effective limit the user experiences, and why?

5. Explain why Leaky Bucket is a poor choice for rate limiting an LLM streaming API where individual requests take 5-30 seconds.

---

### Answers

1. **Answer:** Fixed Window: The minute boundary is at 10:01:00. In the 10:00 window, 95 requests — passes (< 100). In the 10:01 window, 95 requests — passes (< 100). Total: 190 requests in 4 seconds, all allowed. Sliding Window Counter: At 10:01:02, we're 2 seconds into the new minute (elapsed_fraction = 2/60 ≈ 0.033). weighted_count = 95 × (1 - 0.033) + 95 × 1 = 91.8 + 95 = 186.8. This exceeds 100, so the requests at 10:01:02 are rejected. The sliding window catches the boundary burst.

2. **Answer:** Fail-open: When Redis is down, allow all requests through (no rate limiting). This prevents a Redis outage from taking down your entire API. Appropriate for non-critical rate limiting (general abuse prevention). Fail-closed: When Redis is down, reject all requests (return 503). Appropriate when the rate limiter protects a critical resource (like an expensive LLM API with a hard quota — if you can't verify the limit, you can't risk exceeding it and getting banned by the provider).

3. **Answer:** The rate limiter checks: RPM = 1 (allowed, < 500), TPM = 180,000 (allowed, < 200,000). Request proceeds. 30 seconds later: RPM = 2 (allowed). TPM sliding window: 180,000 tokens were used 30 seconds ago. With ~30 seconds remaining in the window, the weighted token count is approximately 180,000 × 0.5 + 50,000 = 140,000. This is under 200,000, so it's allowed. But if the user sends a 100,000-token request instead, weighted count = 90,000 + 100,000 = 190,000. Still allowed. A 50,000-token request after THAT would push over the limit.

4. **Answer:** Each server independently allows up to 100 requests per minute. A user's requests are distributed across the 5 servers by the load balancer (roughly equally). Each server sees ~20 requests from this user per minute, well under the 100 limit. The user can effectively send up to 500 requests per minute (100 per server × 5 servers) before any server rejects. The local rate limiter is 5x too lenient. This is why shared Redis is necessary for accurate global rate limiting.

5. **Answer:** Leaky Bucket processes requests at a fixed rate (e.g., 2 requests/second). Each LLM request takes 5-30 seconds. If the bucket dequeues a request, the server starts processing it, but the slot isn't freed until 5-30 seconds later. The bucket becomes a bottleneck — it can only release 2 requests/second, but each takes 5-30 seconds of server resources. Meanwhile, new requests queue up in the bucket, experiencing massive wait times. The fundamental mismatch: Leaky Bucket assumes uniform, fast processing. LLM requests are slow and variable. Token Bucket or Sliding Window Counter, which track the number of concurrent/recent requests rather than processing at a fixed rate, are better fits.

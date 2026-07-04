# 24 — Idempotency and Exactly-Once Semantics in Practice

## The Problem

Your API server sends a request to Stripe: "Charge customer #123 exactly $99.00." The request succeeds — Stripe charges the card. But the HTTP response is lost on the network. Your server gets a timeout. It doesn't know if the charge went through.

Your retry logic kicks in and sends the exact same request: "Charge customer #123 exactly $99.00." Stripe sees a new request. It charges $99.00 again. The customer has been charged $198.00.

This isn't a Stripe bug. Stripe did exactly what you asked — twice. The bug is in your system: you sent a mutating request twice without telling the downstream system "these two requests are the same request."

This is the idempotency problem. It appears in every distributed system where messages can be lost, duplicated, or retried — which is every distributed system, period.

---

## The Naive Approach and Why It Fails

**"Just don't retry."**
If you don't retry, you accept that some operations silently fail. The customer's card was charged but your system doesn't know, so no order is created. This is worse than double-charging — it's a silent failure that's much harder to detect and fix.

**"Retry only on specific errors."**
You retry on `500 Internal Server Error` and `408 Timeout`, but not on `200 OK`. The problem: a timeout doesn't tell you whether the operation succeeded. The server might have processed the request and crashed before sending the response. Or the network might have dropped the response. You can't distinguish between "the operation failed" and "the operation succeeded but I don't know."

**"Just check if it exists before doing it."**
```python
if not db.payment_exists(payment_id):
    charge_card()
    db.create_payment(payment_id)
```
Race condition: Two workers check simultaneously. Neither finds the payment. Both charge the card. This is a classic TOCTOU (Time Of Check To Time Of Use) bug.

The only real solution is **application-level idempotency.**

---

## The Real Mechanism

### What "Idempotent" Means Precisely

An operation is **idempotent** if performing it multiple times has the same effect as performing it once.

| Operation | Idempotent? | Why |
|-----------|-------------|-----|
| `SET balance = 500` | Yes | Running it 10 times still results in balance = 500 |
| `INCREMENT balance BY 50` | No | Running it 10 times adds $500 |
| `DELETE FROM orders WHERE id = 123` | Yes | First call deletes; subsequent calls find nothing, no-op |
| `INSERT INTO orders VALUES (...)` | No (without unique constraint) | Creates duplicates |
| `PUT /users/123 {"name": "Alice"}` | Yes (in theory) | Replaces the entire resource with the same state |
| `POST /charges {"amount": 99}` | No | Creates a new charge every time |

HTTP methods have *intended* idempotency semantics: GET, PUT, DELETE are supposed to be idempotent; POST is not. But this is a convention, not an enforcement — your server code determines actual behavior.

### The Idempotency Key Pattern

The standard pattern for making non-idempotent operations safe:

**Step 1: Client generates a unique key.**
Before sending the request, the client generates a UUID: `Idempotency-Key: abc-123-def-456`. This key uniquely identifies this specific intent to perform this specific operation.

**Step 2: Server receives the request.**
The server checks a **deduplication store** (typically Redis or a database table) for the key:

**Case A — Key not found (first attempt):**
1. Server atomically writes the key to the deduplication store with status "processing."
2. Server processes the request (e.g., charges the card).
3. Server updates the deduplication entry with the result: status "completed", response payload, HTTP status code.
4. Server returns the response to the client.

**Case B — Key found with status "completed" (retry):**
1. Server does NOT re-process the request.
2. Server retrieves the cached response payload from the deduplication entry.
3. Server returns the cached response. Identical to the original response.

**Case C — Key found with status "processing" (concurrent duplicate):**
1. Server returns `409 Conflict` or waits briefly and re-checks.
2. This handles the case where the same request is sent twice simultaneously.

```python
# Simplified pseudocode
def charge_endpoint(request):
    key = request.headers['Idempotency-Key']
    
    # Atomic check-and-set
    existing = redis.get(f"idempotency:{key}")
    
    if existing and existing['status'] == 'completed':
        return existing['response']  # Return cached response
    
    if existing and existing['status'] == 'processing':
        return Response(status=409)  # Concurrent duplicate
    
    # First time — mark as processing
    redis.set(f"idempotency:{key}", {"status": "processing"}, ex=86400)
    
    try:
        result = stripe.charge(amount=request.amount)
        response = {"charge_id": result.id, "status": "success"}
        redis.set(f"idempotency:{key}", {
            "status": "completed", 
            "response": response
        }, ex=86400)
        return response
    except Exception as e:
        redis.delete(f"idempotency:{key}")  # Allow retry
        raise
```

### The Deduplication Table Pattern

For persistent idempotency (survives Redis restarts), use a database table:

```sql
CREATE TABLE idempotency_keys (
    key         VARCHAR(255) PRIMARY KEY,
    status      VARCHAR(20) NOT NULL,  -- 'processing', 'completed', 'failed'
    response    JSONB,
    created_at  TIMESTAMP DEFAULT NOW(),
    expires_at  TIMESTAMP
);
```

The critical detail: the INSERT into `idempotency_keys` and the actual business operation (e.g., creating a payment record) should be in the SAME database transaction:

```sql
BEGIN;
  INSERT INTO idempotency_keys (key, status) VALUES ('abc-123', 'processing')
    ON CONFLICT (key) DO NOTHING;
  -- If affected rows = 0, this is a duplicate. Return cached response.
  
  INSERT INTO payments (user_id, amount, idempotency_key) VALUES (123, 99.00, 'abc-123');
  
  UPDATE idempotency_keys SET status = 'completed', response = '{"payment_id": 456}'
    WHERE key = 'abc-123';
COMMIT;
```

Because both the idempotency record and the payment record are in the same transaction, they either both exist or neither exists. No partial state.

### Upsert Pattern

For simpler cases, an upsert (INSERT ... ON CONFLICT UPDATE) provides idempotency without a separate deduplication table:

```sql
INSERT INTO user_profiles (user_id, name, email)
VALUES (123, 'Alice', 'alice@example.com')
ON CONFLICT (user_id) DO UPDATE SET name = 'Alice', email = 'alice@example.com';
```

Running this 10 times produces the same result. The `ON CONFLICT` clause makes the INSERT idempotent.

### Exactly-Once Semantics: The Lie and The Workaround

True exactly-once delivery across a network is impossible in the general case (proven by the Two Generals' Problem). What we actually build is **effectively-exactly-once**: at-least-once delivery (retry until acknowledged) + application-layer idempotency (make duplicates harmless).

```
At-Least-Once Delivery + Idempotent Processing = Effectively Exactly-Once
```

This is how:
- Stripe ensures charges aren't duplicated (Idempotency-Key header)
- Kafka consumers achieve exactly-once semantics (consumer offset + transactional producer)
- SQS FIFO queues deduplicate messages (MessageDeduplicationId)

---

## Concrete Example From a Real System

**Stripe's Idempotency Implementation:**

Stripe's API accepts an `Idempotency-Key` header on every POST request. Their server-side implementation:

1. When you send `POST /v1/charges` with `Idempotency-Key: xyz`, Stripe stores the key.
2. If the charge succeeds, Stripe stores the full response associated with key `xyz`.
3. If you retry with the same key (because you got a timeout), Stripe returns the stored response without charging again.
4. Keys expire after 24 hours. After that, the same key can create a new charge.
5. If you send the same key but with different parameters (different amount), Stripe returns a `400` error — preventing you from accidentally reusing a key for a different intent.

**Why the 24-hour expiry matters:** Without an expiry, the deduplication store grows forever. With billions of API calls, Stripe would need petabytes of storage just for idempotency keys. The 24-hour window balances safety (retries happen within minutes, not days) with storage efficiency.

---

## The Tradeoffs

| Approach | Guarantee | Complexity | Storage Cost |
|----------|-----------|------------|--------------|
| No idempotency | None | None | None |
| Client-generated UUID + Redis dedup | Good (survives retries) | Low | Redis memory |
| Idempotency key in same DB transaction | Strong (atomic) | Medium | Table storage |
| Upsert (ON CONFLICT) | Strong for simple cases | Low | None (built-in) |
| Message dedup ID (SQS FIFO) | Good (5-min window) | Low | Managed |

**When idempotency is non-negotiable:**
- Payment processing (double-charge = financial loss + customer trust destruction)
- Inventory decrement (double-decrement = selling items you don't have)
- Account creation (duplicate accounts = data integrity nightmare)
- External API calls with financial cost (LLM calls at $0.50 each)

**When idempotency is nice-to-have:**
- Analytics event logging (a duplicate pageview event is noise, not a crisis)
- Cache warming (re-warming is just wasted compute)
- Notification sending (a duplicate email is annoying, not catastrophic — though still bad UX)

---

## How This Connects to Other Modules

- **Module 14** (Message Queues): At-least-once delivery is the default for most queues. Consumers MUST be idempotent, or duplicate messages will cause duplicate side effects.
- **Module 18** (Service Communication): Retries (with exponential backoff) are essential for reliability. But retries without idempotency double-charge customers. These two modules are inseparable.
- **Module 21** (Distributed Locks): A lock prevents concurrent execution. Idempotency makes re-execution harmless. They're complementary strategies — locks are preventive, idempotency is tolerant.
- **Module 23** (Distributed Transactions): Every saga step and every compensating transaction must be idempotent. If "refund $99" is retried, it must not refund twice.
- **Module 32** (Payment Case Study): This module is the theoretical foundation; Module 32 is the full application.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** This is the single highest-value module in this entire curriculum for your stated future in payments. If you internalize one thing, internalize this: **every mutating operation that crosses a network boundary must be idempotent.** Every API endpoint that creates, updates, or deletes must accept an idempotency key. Every message consumer must check for duplicates before processing. Every saga step must be safe to retry.

The idempotency key pattern is simple to understand and simple to implement. The hard part is discipline — actually adding it to every endpoint, not just the ones you've already been bitten by.

**The AI-era connection:** LLM API calls are expensive mutating operations. A `POST /v1/chat/completions` to OpenAI costs $0.01-$0.50 per call. If your retry logic fires unnecessarily, you're burning money. This makes idempotency not just a correctness concern but a financial one.

The specific trap: your application calls OpenAI, the generation succeeds, but your database write fails (storing the response). Your retry logic calls OpenAI again — paying for the generation twice — even though you already have a perfectly good response from the first call.

The fix: **cache the LLM response before doing anything else with it.** Store the raw response with the idempotency key immediately. If the downstream operation (database write, email send) fails, retry THAT step with the cached LLM response. Never re-call the LLM just because a subsequent step failed.

```python
# BAD: Re-calls LLM on any failure
def generate_report(idempotency_key):
    response = openai.chat(...)  # $0.50
    db.save_report(response)     # If this fails, retry calls openai again

# GOOD: Caches LLM response, only retries cheap steps  
def generate_report(idempotency_key):
    cached = redis.get(f"llm_response:{idempotency_key}")
    if not cached:
        cached = openai.chat(...)  # $0.50 — only called once
        redis.set(f"llm_response:{idempotency_key}", cached, ex=3600)
    db.save_report(cached)  # Safe to retry — uses cached response
```

**Brutally honest advice:** The most common thing junior-to-mid engineers get wrong in their first payments-adjacent system is testing only the happy path. They test: send request → get response → ✅. They never test: send request → response lost → retry → ???. They never test: send request → server crashes after processing but before responding → client retries → ???.

Simulate failures. Kill your server mid-request. Drop HTTP responses at the network layer. Run two instances of the same consumer. If your system charges a customer twice under any of these scenarios, you have a production-quality bug that will 100% happen at scale, and it will happen on the worst possible day — Black Friday, launch day, the day an investor is watching.

---

## Check Your Understanding

1. Your API receives a `POST /v1/orders` request with `Idempotency-Key: abc-123`. The order is created successfully. 30 seconds later, the same request arrives with the same key but a different `quantity` field. What should your server do, and why?

2. A message queue consumer processes payment messages. The queue has at-least-once delivery. The consumer processes a message, charges the customer, but crashes before acknowledging the message. The queue re-delivers the message to another consumer. Without idempotency, what happens? Design the idempotent version.

3. Your LLM-powered API generates a custom poem for $0.25 per call. A client sends the request, the poem is generated successfully, but the database write to store the poem fails. Your retry logic re-sends the request. What's the financial impact? How do you restructure the code to avoid this cost?

4. Why is `INSERT INTO payments (amount, user_id) VALUES (99, 123)` NOT idempotent, but `INSERT INTO payments (idempotency_key, amount, user_id) VALUES ('abc', 99, 123) ON CONFLICT (idempotency_key) DO NOTHING` IS idempotent?

5. Stripe's idempotency keys expire after 24 hours. What would happen if they never expired? What would happen if they expired after 1 minute? Explain the tradeoff.

---

### Answers

1. **Answer:** The server should return a `400 Bad Request` error (or `422 Unprocessable Entity`). An idempotency key is bound to a specific intent — the original request parameters. If the key is the same but the parameters are different, it means the client is either reusing a key incorrectly or a different operation is being disguised as a retry. Stripe does exactly this: it stores the original request body hash alongside the key and rejects mismatches.

2. **Answer:** Without idempotency: the customer is charged twice (the new consumer processes the message again and calls the payment API a second time). Idempotent version: each payment message includes a unique `payment_intent_id`. The consumer first checks the database: `SELECT 1 FROM payments WHERE intent_id = 'xyz'`. If found, the message is a duplicate — acknowledge it and skip processing. If not found, process the payment and insert the record. The check and insert should ideally be atomic (same transaction) to prevent TOCTOU races.

3. **Answer:** Financial impact: you pay $0.50 instead of $0.25 — the LLM generates the poem twice, but you only needed one. Fix: after the LLM call succeeds, immediately cache the response in Redis with the idempotency key. When the retry fires, the code checks Redis first, finds the cached poem, and skips the LLM call. It then retries only the database write (which is essentially free). Total cost: $0.25, not $0.50.

4. **Answer:** The first INSERT creates a new row every time it's executed (auto-incrementing primary key, no uniqueness constraint on amount+user_id). Run it 5 times, get 5 payment rows. The second INSERT uses `idempotency_key` as a unique constraint. The first execution inserts the row. Subsequent executions hit the `ON CONFLICT` clause and `DO NOTHING` — the row already exists, no duplicate is created. Run it 5 times, get 1 payment row.

5. **Answer:** If keys never expired: Stripe's deduplication store would grow without bound. With billions of API calls, this requires massive storage (petabytes over years) and increasingly slow lookups. If keys expired after 1 minute: a client that retries after 2 minutes (due to a slow network or a retry backoff) would find no stored key and accidentally create a duplicate charge. The 24-hour window is a sweet spot — retries in production almost always happen within seconds or minutes (retry policies with exponential backoff cap around 5-10 minutes), so 24 hours is conservative enough to catch all realistic retries while keeping storage manageable.

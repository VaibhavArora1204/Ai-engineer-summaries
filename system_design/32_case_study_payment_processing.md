# 32 — Case Study: Payment Processing System

## Requirements Clarification

**Functional:**
- Process credit card charges, refunds, and payouts.
- Support a multi-step checkout: payment → inventory reservation → order confirmation.
- Handle webhook notifications from Stripe/payment provider.
- Reconciliation: detect and fix inconsistencies (double charges, missed charges).

**Non-Functional:**
- Every charge must be idempotent. A retry must NEVER double-charge.
- The system must handle partial failures gracefully (payment succeeds but inventory fails).
- All payment events must be auditable (immutable audit log).
- 99.99% availability for the charge endpoint (financial SLA).

---

## Back-of-Envelope Estimation

```
Transactions: 500,000 orders per day.
QPS: 500K / 86,400 ≈ 6 transactions/second average.
Peak (flash sale): 10x → 60 transactions/second.

Each transaction involves:
  1 Stripe API call (~500ms)
  1-2 database writes (~5ms each)
  1 queue publish (~2ms)
  
Total: ~510ms per transaction.

Storage:
  Each transaction record: ~500 bytes.
  500K/day × 500 bytes = 250 MB/day.
  1 year: ~90 GB. Trivial.
  
  Audit log: every event (charge, refund, webhook, state change).
  ~5 events per transaction × 200 bytes = 500 MB/day.
  1 year: ~180 GB.

Verdict: Single Postgres instance handles this easily.
The hard part is not scale — it's correctness.
```

---

## High-Level Design

```
Client → API → Checkout Orchestrator
                     ↓
              ┌──────┼──────┐
              ↓      ↓      ↓
          Payment  Inventory  Order
          Service   Service   Service
              ↓
          Stripe API
              ↓
          Webhook Handler ← Stripe Webhooks
              ↓
          Reconciliation Job (hourly)
```

---

## Deep Dive: The Genuinely Hard Parts

### 1. Idempotent Charge Processing (Direct Application of Module 24)

**The scenario:** User clicks "Pay" → browser sends POST `/checkout` → Stripe charges $99 → but the HTTP response from your server to the browser is dropped (network hiccup) → the browser's retry logic sends the same POST again.

**The implementation:**

```python
@app.post("/checkout")
async def checkout(request: CheckoutRequest):
    idempotency_key = request.idempotency_key  # Client-generated UUID
    
    # Step 1: Check deduplication table
    existing = await db.fetchone(
        "SELECT response FROM idempotency_keys WHERE key = $1", 
        idempotency_key
    )
    if existing:
        return existing['response']  # Return cached response — no re-charge
    
    # Step 2: Atomically insert idempotency key + create payment intent
    async with db.transaction():
        await db.execute(
            "INSERT INTO idempotency_keys (key, status) VALUES ($1, 'processing')",
            idempotency_key
        )
        payment = await db.execute(
            "INSERT INTO payments (idempotency_key, user_id, amount, status) "
            "VALUES ($1, $2, $3, 'pending')",
            idempotency_key, request.user_id, request.amount
        )
    
    # Step 3: Call Stripe with THEIR idempotency key
    stripe_response = await stripe.charges.create(
        amount=request.amount * 100,  # Stripe uses cents
        currency="usd",
        customer=request.stripe_customer_id,
        idempotency_key=idempotency_key  # Stripe's own dedup
    )
    
    # Step 4: Update payment status
    await db.execute(
        "UPDATE payments SET status = 'charged', stripe_charge_id = $1 "
        "WHERE idempotency_key = $2",
        stripe_response.id, idempotency_key
    )
    
    # Step 5: Cache the response for future retries
    response = {"payment_id": payment.id, "status": "charged"}
    await db.execute(
        "UPDATE idempotency_keys SET status = 'completed', response = $1 "
        "WHERE key = $2",
        json.dumps(response), idempotency_key
    )
    
    return response
```

**Critical detail:** The idempotency key is passed to BOTH your system AND Stripe. Even if your server crashes after Stripe charges but before updating your database, a retry will hit Stripe with the same key, and Stripe returns the original charge without charging again.

### 2. The Checkout Saga (Direct Application of Module 23)

**Happy path:**
```
1. Payment Service → Stripe: Charge $99. → Success (charge_id: ch_123)
2. Inventory Service → DB: Reserve Widget X, stock 5→4. → Success
3. Order Service → DB: Create order, status="confirmed." → Success
4. Notification Service → Email: Send confirmation. → Success
```

**Failure at step 2 (out of stock):**
```
1. Payment Service → Stripe: Charge $99. → Success
2. Inventory Service → DB: Reserve Widget X. → FAIL (stock = 0)
3. COMPENSATE Step 1: Payment Service → Stripe: Refund charge ch_123.
4. Return to user: "Item out of stock. Your payment has been refunded."
```

**Step ordering matters:**
Do NOT charge the card first. Check inventory first. Then charge.

```
BETTER ORDER:
1. Inventory Service: Reserve Widget X (stock 5→4, status="reserved"). → Success
2. Payment Service: Charge $99. → Success
3. Order Service: Create order. → Success
4. Inventory Service: Confirm reservation (status="sold"). → Success

If Step 2 fails (card declined):
  COMPENSATE Step 1: Release reservation (stock 4→5, status="available").
  No refund needed — card was never charged.
```

This ordering minimizes unnecessary refunds. Inventory reservation is free and instant. Card charges involve Stripe's processing fee (which you might not get back on refund).

### 3. Webhook Reliability

Stripe sends webhooks for events: `charge.succeeded`, `charge.failed`, `refund.created`, etc. Your system must handle them correctly.

**Problems with webhooks:**
1. **At-least-once delivery:** Stripe may send the same webhook multiple times (retry on timeout).
2. **Out-of-order delivery:** `charge.succeeded` might arrive BEFORE your server finishes processing the original charge response.
3. **Verification:** Anyone can send a POST to your webhook endpoint. You must verify it's from Stripe.

**Handling:**

```python
@app.post("/webhooks/stripe")
async def handle_stripe_webhook(request: Request):
    # Step 1: Verify signature
    payload = await request.body()
    sig = request.headers['Stripe-Signature']
    try:
        event = stripe.Webhook.construct_event(payload, sig, webhook_secret)
    except ValueError:
        return Response(status_code=400)  # Invalid payload
    except stripe.SignatureVerificationError:
        return Response(status_code=401)  # Invalid signature
    
    # Step 2: Idempotent processing
    event_id = event['id']
    existing = await db.fetchone(
        "SELECT 1 FROM processed_webhooks WHERE event_id = $1", event_id
    )
    if existing:
        return Response(status_code=200)  # Already processed — skip
    
    # Step 3: Process the event
    if event['type'] == 'charge.succeeded':
        await handle_charge_succeeded(event['data']['object'])
    elif event['type'] == 'charge.failed':
        await handle_charge_failed(event['data']['object'])
    
    # Step 4: Mark as processed
    await db.execute(
        "INSERT INTO processed_webhooks (event_id, processed_at) VALUES ($1, NOW())",
        event_id
    )
    
    return Response(status_code=200)
```

### 4. Reconciliation — The Safety Net

No matter how well you implement idempotency and sagas, edge cases will cause inconsistencies. A reconciliation job detects and fixes them.

**Reconciliation pattern:**

```python
# Run every hour
async def reconcile():
    # Get all Stripe charges in the last 2 hours
    stripe_charges = stripe.Charge.list(created={'gte': two_hours_ago})
    
    for charge in stripe_charges:
        local_payment = await db.fetchone(
            "SELECT * FROM payments WHERE stripe_charge_id = $1", charge.id
        )
        
        if local_payment is None:
            # Stripe has a charge we don't know about — orphaned charge
            log.error(f"Orphaned Stripe charge: {charge.id}. Auto-refunding.")
            stripe.Refund.create(charge=charge.id)
            alert_ops_team(charge)
        
        elif local_payment['status'] == 'pending' and charge.status == 'succeeded':
            # Our DB says "pending" but Stripe says "succeeded"
            # This happens if our server crashed after Stripe charged but before updating DB
            log.warn(f"Fixing stale payment {local_payment['id']}")
            await db.execute(
                "UPDATE payments SET status = 'charged' WHERE id = $1",
                local_payment['id']
            )
    
    # Check for payments in "charged" status with no Stripe charge
    orphaned_local = await db.fetch(
        "SELECT * FROM payments WHERE status = 'charged' "
        "AND stripe_charge_id IS NULL AND created_at < $1",
        one_hour_ago
    )
    for payment in orphaned_local:
        log.error(f"Local payment {payment['id']} has no Stripe charge. Marking failed.")
        await db.execute(
            "UPDATE payments SET status = 'failed' WHERE id = $1",
            payment['id']
        )
```

Reconciliation is not glamorous. It's the most important safety mechanism in a payment system. Every serious payments company (Stripe, PayPal, Square) runs reconciliation continuously.

---

## The Immutable Audit Log

Every state change must be recorded in an append-only audit log. This log is never updated or deleted — only appended.

```sql
CREATE TABLE payment_audit_log (
    id BIGSERIAL PRIMARY KEY,
    payment_id UUID NOT NULL,
    event_type VARCHAR(50) NOT NULL,  -- 'charge_initiated', 'charge_succeeded', 'refund_issued'
    old_status VARCHAR(20),
    new_status VARCHAR(20),
    details JSONB,  -- Stripe response, error message, etc.
    created_at TIMESTAMP DEFAULT NOW(),
    actor VARCHAR(100)  -- 'system', 'user:123', 'reconciliation_job'
);
```

This log is your forensic tool. When a customer disputes a charge 60 days later, you can reconstruct the exact sequence of events.

---

## Mentor's Take — What Actually Matters Here

**What matters:** This case study is about one thing: **defense in depth.** No single layer of protection is sufficient. You need: idempotency keys (prevent double-charges at the API layer), saga-pattern compensation (handle partial failures), webhook deduplication (handle at-least-once delivery), and reconciliation (catch everything the other layers missed). Any team that relies on just one of these will eventually have a payment incident.

**The AI-era connection:** If you're building an AI product with a usage-based billing model (charge per token, per generation, per agent task), you're building a micro-payments system. Every LLM API call has a cost. If your system double-charges a user for a generation (because a retry wasn't idempotent), the amounts are small but the trust impact is large. The same patterns apply: idempotency on the billing event, reconciliation of your usage tracking against the LLM provider's invoice, and an audit trail showing exactly which user incurred which cost.

**Brutally honest advice:** The most important thing I can tell you about payment systems: **test the failure modes, not the happy path.** Every junior engineer writes tests for "user pays, order is created, everyone is happy." Senior payment engineers write tests for:
- "Stripe charges the card, our server crashes, client retries" → verify no double charge.
- "Inventory reservation succeeds, card is declined" → verify reservation is released.
- "Webhook arrives before the synchronous charge response" → verify no race condition.
- "Reconciliation finds an orphaned Stripe charge" → verify auto-refund works.

If you only test the happy path, you'll have your first payment incident within a month of launch. It will happen on a weekend. It will involve a furious customer and a panicked founder.

---

## Check Your Understanding

1. Your server calls Stripe to charge $99. Stripe processes the charge successfully, but your server crashes before receiving the response and before updating the database. When the server restarts, the payment record still shows status="pending." How does reconciliation fix this? How does the idempotency key prevent a double-charge if the user retries?

2. In the checkout saga, you charge the card in Step 1 and reserve inventory in Step 2. Step 2 fails (out of stock). You issue a refund. But Stripe's refund takes 5-10 business days to appear in the customer's bank account. From the customer's perspective, what just happened? How should the UI handle this?

3. Stripe sends a `charge.succeeded` webhook for charge `ch_xyz`. Your server is processing the synchronous charge response for the same charge at the exact same moment. Both code paths try to update the payment status to "charged." Describe the race condition and how to prevent data corruption.

4. Your audit log shows that payment #456 was charged at 10:00:00 and refunded at 10:00:05 — but the customer never requested a refund. Using the audit log, how do you trace what happened?

5. You build an AI product that charges users $0.02 per LLM generation. A user generates 500 responses in a day ($10 total). Your billing system shows $10, but the LLM provider's invoice shows you were charged $12 for that user's generations. What is the $2 discrepancy likely caused by, and how does reconciliation detect it?

---

### Answers

1. **Answer:** Reconciliation: The hourly job queries Stripe for recent charges, finds charge `ch_xyz`, looks it up locally, finds status="pending" for the matching idempotency key. It updates the status to "charged." The payment is now correctly reflected. Idempotency: If the user retries before reconciliation runs, the retry hits your server. Your server either finds the idempotency key in "processing" status (returns a "please wait" response) or passes the same key to Stripe. Stripe finds the key in their deduplication store and returns the original successful charge without charging again.

2. **Answer:** From the customer's perspective: "I tried to buy something, my card was charged $99, then I was told it's out of stock." Even though the refund is issued instantly on Stripe's side, the money takes 5-10 days to appear back in their account. The UI should: (1) clearly explain "Your payment of $99 has been refunded. It may take 5-10 business days to appear in your statement." (2) Show the refund status in the order history. (3) Optionally, offer store credit for immediate use while the refund processes.

3. **Answer:** Both code paths execute `UPDATE payments SET status = 'charged' WHERE stripe_charge_id = 'ch_xyz'`. If they run concurrently, the second UPDATE is harmless (idempotent — setting "charged" to "charged"). However, if both paths also try to INSERT into the audit log and trigger downstream events (send confirmation email, reserve inventory), you might get duplicate emails or double inventory decrements. Prevention: use the processed_webhooks deduplication table. The webhook handler checks if the event was already processed. If the synchronous response already handled it, the webhook is a no-op. Using `ON CONFLICT DO NOTHING` on the audit log's event_id ensures no duplicate audit entries.

4. **Answer:** Query the audit log: `SELECT * FROM payment_audit_log WHERE payment_id = 456 ORDER BY created_at`. The log shows: (1) 10:00:00 — event: "charge_initiated", actor: "user:789". (2) 10:00:01 — event: "charge_succeeded", actor: "system". (3) 10:00:05 — event: "refund_issued", actor: "reconciliation_job". The `actor` field reveals that the refund was issued by the reconciliation job, not by a user. This means the reconciliation detected an inconsistency (perhaps the charge succeeded on Stripe but the order creation failed, making it an orphaned charge). The reconciliation job auto-refunded it. Without the audit log, you'd have no idea why the refund happened.

5. **Answer:** The $2 discrepancy is likely caused by failed/retried LLM calls. Your billing system only counts successful generations delivered to the user (500 × $0.02 = $10). But some LLM calls might have timed out or errored after the tokens were consumed (the model generated the response, but your server crashed before delivering it). The provider charges for all token consumption, including failed attempts. Reconciliation detects this by comparing your generation logs (with timestamps and token counts) against the provider's detailed usage API. The unmatched entries reveal the retried/failed calls. Fix: implement the Module 24 pattern — cache LLM responses before any downstream processing, so retries use the cached response instead of re-calling the LLM.

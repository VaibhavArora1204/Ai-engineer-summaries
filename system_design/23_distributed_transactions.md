# 23 — Distributed Transactions

## The Problem

A user buys a product on your e-commerce platform. Three things must happen:

1. **Payment Service:** Charge the customer's credit card $99.
2. **Inventory Service:** Decrease stock of "Widget X" from 5 to 4.
3. **Order Service:** Create an order record with status "confirmed."

In a monolith, you wrap all three operations in a single database transaction:
```sql
BEGIN;
  INSERT INTO payments (user_id, amount) VALUES (123, 99.00);
  UPDATE inventory SET stock = stock - 1 WHERE product_id = 'widget-x';
  INSERT INTO orders (user_id, product_id, status) VALUES (123, 'widget-x', 'confirmed');
COMMIT;
```

If any step fails, the entire transaction rolls back. ACID guarantees (Module 09) protect you.

But you split into microservices (Module 17). Payment, Inventory, and Order are separate services with separate databases. There is no single `BEGIN/COMMIT` that spans three databases on three servers. The moment you split, you lose ACID across the boundary.

Now what? The payment goes through, but the inventory update fails because the last widget was just sold to someone else. You've charged the customer but can't fulfill the order. This is a **distributed transaction** problem.

---

## The Naive Approach and Why It Fails

**"Just use a distributed transaction manager."**

This exists. It's called **Two-Phase Commit (2PC).**

### 2PC Mechanism

A **Coordinator** orchestrates the transaction across all participants:

**Phase 1 — Prepare (Voting):**
1. Coordinator sends "Prepare to commit" to Payment, Inventory, and Order services.
2. Each service executes its local operation, writes to a write-ahead log, locks the affected rows, and responds: "Yes, I'm prepared" or "No, I can't."
3. Each service holds its locks open while waiting for the final decision.

**Phase 2 — Commit/Abort:**
1. If ALL participants voted "Yes": Coordinator sends "Commit" to all. Each service commits its local transaction and releases locks.
2. If ANY participant voted "No": Coordinator sends "Abort" to all. Each service rolls back and releases locks.

### Why 2PC Is Rarely Used

1. **Blocking:** While waiting for the Phase 2 decision, every participant holds database locks. If the Coordinator crashes between Phase 1 and Phase 2, all participants are stuck holding locks indefinitely. No participant can unilaterally decide to commit or abort — they must wait for the Coordinator. This can freeze your database for minutes or hours.

2. **Coordinator is a SPOF:** The entire transaction depends on a single Coordinator process being alive. If it dies at the worst moment (after sending "Prepare" but before sending "Commit"), the participants are in an uncertain state. They can't roll back (some might have already committed), and they can't commit (they don't know if everyone else voted "Yes").

3. **Latency:** Every participant must do a network round-trip to the Coordinator, wait for all other participants, then do another round-trip for the final decision. In a system with 50ms network latency, a 3-participant 2PC takes ~200ms minimum, during which database rows are locked.

4. **Doesn't work across company boundaries:** You can't send a "Prepare" message to Stripe's API and ask it to hold a charge in limbo while you check your inventory. External APIs don't participate in your 2PC protocol.

2PC is used internally by some distributed databases (e.g., Google Spanner, CockroachDB) where the coordinator is built into the database engine. You will almost never implement 2PC in application-level microservice architectures.

---

## The Real Mechanism: The Saga Pattern

A **Saga** is a sequence of local transactions, each in its own service, where each step has a corresponding **compensating transaction** that undoes it if a later step fails.

Instead of one atomic operation across services, you have a chain of individually atomic operations with cleanup logic.

### Worked Example: E-Commerce Order

**Happy path (all steps succeed):**
1. **Payment Service:** Charge $99. → Success.
2. **Inventory Service:** Reserve 1 Widget X. → Success.
3. **Order Service:** Create order, status = "confirmed." → Success.
4. Done.

**Failure at Step 3:**
1. **Payment Service:** Charge $99. → Success.
2. **Inventory Service:** Reserve 1 Widget X. → Success.
3. **Order Service:** Create order. → **Fails** (database down).
4. **Compensate Step 2:** Inventory Service: Release the reservation. Stock goes back to 5.
5. **Compensate Step 1:** Payment Service: Issue a refund of $99.
6. Tell the user: "Order failed. Your payment has been refunded."

**Failure at Step 2:**
1. **Payment Service:** Charge $99. → Success.
2. **Inventory Service:** Reserve Widget X. → **Fails** (out of stock).
3. **Compensate Step 1:** Payment Service: Refund $99.
4. Tell the user: "Item out of stock. Your payment has been refunded."

### Compensating Transactions

A compensating transaction is NOT a rollback. A rollback undoes a transaction as if it never happened (database magic). A compensating transaction is a new, forward action that semantically reverses the effect:

| Original Action | Compensating Action |
|----------------|-------------------|
| Charge $99 | Refund $99 |
| Reserve inventory | Release reservation |
| Create order record | Update order to "cancelled" |
| Send confirmation email | Send cancellation email |
| Call embedding API | (No compensation needed — idempotent, just cost wasted) |

**Critical insight:** Some actions have no natural compensation. If you've already shipped the physical product, you can't un-ship it. If you've already sent a push notification, you can't un-send it. The order of your saga steps matters — put irreversible actions LAST.

### Orchestration vs Choreography

There are two ways to coordinate a saga:

**Orchestration (Central Coordinator):**
A single "Saga Orchestrator" service drives the workflow step by step.

```
Orchestrator → Payment Service: "Charge $99"
Payment Service → Orchestrator: "Charged. Here's transaction ID."
Orchestrator → Inventory Service: "Reserve Widget X"
Inventory Service → Orchestrator: "Reserved."
Orchestrator → Order Service: "Create order"
Order Service → Orchestrator: "Created."
Orchestrator: "Saga complete."
```

If Step 2 fails:
```
Orchestrator → Payment Service: "Refund transaction ID XYZ"
Orchestrator: "Saga compensated."
```

*Pros:* Clear, debuggable, the orchestrator holds the entire state.
*Cons:* The orchestrator is a potential SPOF. Tight coupling to the orchestrator.

**Choreography (Event-Driven):**
No central coordinator. Each service publishes an event when it completes its step, and the next service listens for that event.

```
Payment Service charges $99 → publishes "PaymentCompleted" event
Inventory Service hears "PaymentCompleted" → reserves inventory → publishes "InventoryReserved"
Order Service hears "InventoryReserved" → creates order → publishes "OrderCreated"
```

If Inventory fails:
```
Inventory Service publishes "InventoryReservationFailed"
Payment Service hears "InventoryReservationFailed" → refunds → publishes "PaymentRefunded"
```

*Pros:* No central SPOF. Services are loosely coupled. Scales naturally.
*Cons:* Hard to understand the full workflow. Hard to debug — you need to trace events across services. Race conditions are possible if events arrive out of order.

**When to use which:**
- Use **Orchestration** for business-critical workflows (payments, order processing) where visibility and debuggability matter more than loose coupling.
- Use **Choreography** for low-stakes, highly parallelizable workflows (user signup triggers a welcome email, creates a default workspace, initializes user analytics — these don't depend on each other and failure in one doesn't require compensating the others).

---

## Concrete Example From a Real System

**Stripe Payment + Internal Order System:**

You can't 2PC with Stripe. Stripe is an external API. Your saga looks like:

1. **Create a Payment Intent** with Stripe (tells Stripe "I intend to charge $99, but don't charge yet").
2. **Reserve inventory** in your database.
3. **Confirm the Payment Intent** with Stripe (now Stripe actually charges the card).
4. **Create the order record.**

If Step 2 fails (out of stock): Cancel the Payment Intent with Stripe. No charge.
If Step 3 fails (card declined): Release the inventory reservation.
If Step 4 fails (your DB down): The payment went through but you have no order record. You use a **reconciliation job** that periodically compares Stripe's records with your database and creates missing orders or issues refunds for orphaned payments.

The reconciliation job is the safety net. You accept that your saga will occasionally leave the system in an inconsistent state (payment exists, order doesn't). Instead of preventing this 100% (impossible with external services), you detect and repair it.

---

## The Tradeoffs

| Approach | Consistency | Latency | Complexity | External Service Support |
|----------|-------------|---------|------------|------------------------|
| Single DB Transaction | Strong (ACID) | Low | Low | No (single DB only) |
| 2PC | Strong | High (lock holding) | High | No (all parties must participate) |
| Saga (Orchestration) | Eventual | Medium | Medium | Yes |
| Saga (Choreography) | Eventual | Medium-Low | High (debugging) | Yes |

**The fundamental tradeoff:** Sagas give you cross-service consistency, but only **eventual** consistency. Between Step 1 succeeding and Step 3 completing, your system is in a partially-committed state. A user who refreshes at that exact moment might see "payment charged" but "order pending." You must design your UI to handle these intermediate states gracefully.

---

## How This Connects to Other Modules

- **Module 09** (Databases): Local transactions (ACID) are the building blocks of each saga step. A saga is a chain of local ACID transactions.
- **Module 12** (CAP): Sagas embrace eventual consistency. You're choosing AP (availability and partition tolerance) over strong consistency across services.
- **Module 14** (Message Queues): Orchestrated sagas often use a durable queue between the orchestrator and the services to guarantee delivery of saga commands. Choreography uses event streams.
- **Module 15** (Event-Driven): Choreography sagas ARE event-driven architecture applied to a transactional workflow.
- **Module 18** (Service Communication): Each saga step is a service-to-service call. Circuit breakers, retries, and timeouts (Module 18) apply to every step.
- **Module 24** (Idempotency): Every saga step and every compensating transaction MUST be idempotent. If the "charge $99" step is retried (network timeout), it must not double-charge. This is non-negotiable.
- **Module 32** (Payment Case Study): Module 32 is a full case study of exactly this saga pattern applied to a real payment system.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** Understand 2PC well enough to explain why it's impractical for microservices (blocking, coordinator SPOF, can't work with external APIs). Understand sagas deeply — both orchestration and choreography — because this is how every production payment/order system actually works. The concept of a compensating transaction is the core mental model.

The skill that separates senior from junior here: designing saga steps in the right ORDER. Irreversible or expensive actions go last. Cheap, easily-compensated actions go first. If you charge the credit card in Step 1 and check inventory in Step 3, you're issuing unnecessary refunds every time you're out of stock. If you check inventory first and charge last, out-of-stock failures cost nothing.

**The AI-era connection:** LLM API calls inside a saga are a unique headache.

Consider this saga: (1) Call OpenAI to generate a report → (2) Store the report in the database → (3) Send it to the user via email.

If Step 2 fails, the compensating transaction for Step 1 is... what? You can't "un-generate" the report. The tokens are already consumed, the money is already spent. The compensating transaction is simply "accept the cost and move on," or "retry step 2" (which is usually the better choice — retry the cheap step, not the expensive one).

This means for AI pipelines, the saga design should put the expensive LLM call as LATE as possible in the chain. Validate all inputs, check all preconditions, reserve all resources BEFORE you call the LLM. The LLM call should be the last step before writing the final result, so that if it fails, you've wasted the least amount of prior work, and if it succeeds, the remaining steps (write to DB, send to user) are cheap and retriable.

**Brutally honest advice:** The instinct every backend engineer has — "just wrap it in a database transaction" — is the instinct that gets you fired on a payments team. It doesn't work across services. It doesn't work with Stripe. It doesn't work with any external API. If you're building anything that touches money, you must think in sagas from day one. And you must accept that your system will occasionally be in an inconsistent state and build reconciliation — the automated process that compares "what should have happened" with "what actually happened" and fixes the differences. Reconciliation is not a nice-to-have. In payments, it's as important as the transaction logic itself. Every serious payments company (Stripe, PayPal, Square) runs reconciliation jobs continuously.

---

## Check Your Understanding

1. In a 2PC protocol, the Coordinator sends "Prepare" to Services A, B, and C. Services A and B respond "Yes." Service C never responds (network partition). What happens? Can the Coordinator commit? What state are Services A and B stuck in?

2. Design a 3-step saga for: (1) Reserve a ride with a driver, (2) Charge the rider's credit card, (3) Send a push notification confirming the ride. What is the compensating transaction for each step? Which step should go last and why?

3. Your saga orchestrator calls Payment Service to charge $99. The charge succeeds on Stripe, but the HTTP response is lost due to a network timeout. The orchestrator retries. Without idempotency, what happens? How does an idempotency key (Module 24) prevent it?

4. You're building an AI report generation pipeline as a saga: (1) Validate user permissions, (2) Retrieve context documents, (3) Call LLM to generate report ($0.50 per call), (4) Store report in database, (5) Send email to user. Step 4 fails. What do you do? Should you compensate Step 3?

5. Explain why choreography-based sagas are harder to debug than orchestration-based sagas. What specific observability tool (Module 25) becomes essential?

---

### Answers

1. **Answer:** The Coordinator cannot commit because it hasn't received unanimity. It cannot abort either (Services A and B are prepared and holding locks, waiting for the final decision). The Coordinator must wait — potentially forever — for Service C to respond. Services A and B are stuck in the "prepared" state with database locks held open, unable to commit or roll back on their own. This is the fundamental blocking problem of 2PC: a single non-responsive participant freezes the entire system.

2. **Answer:** Compensations: (1) Reserve ride → Cancel the reservation, release the driver. (2) Charge card → Refund the charge. (3) Send push notification → Send a "ride cancelled" notification. The push notification should go LAST because it's the most irreversible — you can't un-send a notification that's already appeared on someone's phone. Better ordering: (1) Reserve ride (cheap, easily cancelled), (2) Charge card (compensatable via refund), (3) Send notification (irreversible). If charging fails, you cancel the reservation but the user never got a notification, so no confusion.

3. **Answer:** Without idempotency, Stripe charges the customer $99 again, resulting in a $198 total charge. The orchestrator doesn't know the first attempt succeeded. With an idempotency key: the orchestrator sends the same key on the retry. Stripe receives the key, looks it up in its internal deduplication store, finds the previous successful charge, and returns the original success response without charging again. The customer is charged exactly $99.

4. **Answer:** Do NOT compensate Step 3 (the LLM call). You can't un-generate the report, and the $0.50 is already spent. Instead, RETRY Step 4 (store report in database). Database writes are cheap, fast, and retriable. If the database is temporarily down, put the report on a queue and retry later. The $0.50 LLM cost is the sunk cost you accept. This is why the expensive LLM call should be positioned so that subsequent steps are cheap and reliable.

5. **Answer:** In orchestration, the Saga Orchestrator holds the complete state of the workflow — you can query it to see "Step 2 succeeded, Step 3 failed, compensation in progress." In choreography, there's no single place that knows the full picture. Each service only knows about its own step. To reconstruct the full saga flow, you must trace events across multiple services and correlate them by a shared saga/correlation ID. Distributed Tracing (Module 25) with trace ID propagation across all events becomes essential — without it, debugging a failed choreography saga across 5 services is like reading a novel with the pages shuffled.

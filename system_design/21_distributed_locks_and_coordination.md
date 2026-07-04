# 21 — Distributed Locks and Coordination

## The Problem

You have 5 worker instances processing tasks from a shared queue. A task appears: "Generate embedding for document #4521." Worker A picks it up. Worker B also picks it up at the same millisecond. Both workers call the OpenAI embedding API, both write the result to the vector database. You've just paid for the embedding twice and introduced a potential race condition where Worker B's slightly-later write overwrites Worker A's.

This is the **mutual exclusion** problem in distributed systems: ensuring that only one process performs a specific action at a time, even when multiple processes are running on different machines that can't share memory.

In a single-process application, you'd use a mutex or a lock from your language's standard library. In a distributed system, there's no shared memory. The processes are on different servers. You need a lock that works across the network.

---

## The Naive Approach and Why It Fails

**Attempt 1: "I'll use a database column."**
```sql
UPDATE tasks SET locked_by = 'worker-A', locked_at = NOW() 
WHERE id = 4521 AND locked_by IS NULL;
```
If the affected rows count is 1, you "got the lock." This works... until Worker A crashes mid-task. The `locked_by` column stays set forever. The task is permanently stuck. You add a timeout: "If `locked_at` is older than 5 minutes, consider it unlocked." Now Worker B starts working on the task at minute 5:01, and Worker A (which was just slow, not dead) finishes at minute 5:02 and writes its result. You have a race condition.

**Attempt 2: "I'll use Redis SET NX."**
```
SET task:4521:lock worker-A NX EX 30
```
`NX` means "only set if not exists." `EX 30` means "expire in 30 seconds." This is better — it has a built-in TTL. But it has two critical failure modes:

1. **Worker A takes longer than 30 seconds.** The lock expires. Worker B acquires it. Both are now working concurrently. Worker A finishes and deletes the lock — but it's deleting Worker B's lock. Worker C can now acquire it. You have three workers running simultaneously.
2. **Redis master fails over.** The lock was written to the master but not replicated to the replica (Redis replication is async — Module 20). The replica becomes master. The lock doesn't exist. Worker B acquires it. Double processing.

These aren't theoretical. These are production incidents I've seen reported at scale.

---

## The Real Mechanism

### Lease-Based Locks with Fencing Tokens

The fundamental insight: a distributed lock isn't a binary "locked/unlocked." It's a **lease** — a time-limited grant of exclusive access, paired with a **fencing token** that the downstream system uses to reject stale operations.

**Step 1: Acquire a lease.**
The lock service (ZooKeeper, etcd) grants Worker A a lease with a unique, monotonically increasing token (e.g., token #42) and a TTL of 30 seconds.

**Step 2: Do the work.**
Worker A does its task. It includes token #42 in every write it makes to downstream systems.

**Step 3: Downstream systems validate the token.**
The database or API receiving Worker A's writes checks: "Is token #42 >= the highest token I've ever seen for this resource?" If yes, accept. If no, reject.

**Step 4: Lease expires or is released.**
Worker A either explicitly releases the lock when done, or the TTL expires.

**Why fencing tokens fix the timeout problem:**
Worker A has token #42 with a 30-second TTL. Worker A is slow. At second 31, the lock expires. Worker B acquires the lock and gets token #43. Worker A finishes at second 35 and tries to write its result with token #42. The database sees that token #43 has already been used (or is currently active) and rejects token #42's write. Worker B's result wins. No data corruption.

### ZooKeeper-Style Locking (Ephemeral Nodes)

ZooKeeper provides a particularly elegant lock mechanism using **ephemeral sequential nodes:**

1. Worker A creates an ephemeral sequential node: `/locks/task-4521/lock-0001`
2. Worker B creates: `/locks/task-4521/lock-0002`
3. Each worker checks: "Is my node the lowest-numbered child of `/locks/task-4521`?"
4. Worker A's `0001` < Worker B's `0002`, so Worker A holds the lock.
5. Worker B sets a **watch** on Worker A's node and waits.
6. When Worker A finishes (or crashes), its ephemeral node is automatically deleted (ZooKeeper detects the dead session).
7. Worker B's watch fires. It checks again, sees it now has the lowest number, and acquires the lock.

**Why ephemeral nodes solve the crash problem:**
If Worker A crashes, its TCP session with ZooKeeper dies. ZooKeeper automatically deletes all ephemeral nodes associated with that session. The lock is released without any timeout guessing.

**Why sequential nodes solve the thundering herd problem:**
Without sequential ordering, if 100 workers are waiting for the lock, they'd all get notified when it's released and all try to acquire it simultaneously (a thundering herd). With sequential nodes, only the next-in-line worker (the one watching the deleted node) wakes up.

### The Redlock Controversy — A Humility Lesson

Redis's creator (Antirez) proposed **Redlock**: acquire locks on 5 independent Redis masters, and consider the lock acquired if you get it on a majority (3+). This was supposed to fix the single-Redis-master failover problem.

Martin Kleppmann (author of Designing Data-Intensive Applications) published a devastating critique showing that Redlock can fail if:
- Clocks on the Redis nodes drift (the TTL expires at different times)
- A process pauses (GC pause, page fault) after acquiring the lock but before using it
- Network delays cause the lock to expire before the client realizes it

Antirez responded. The debate was never fully resolved.

**The lesson is not "which one is right."** The lesson is: **distributed locking is fundamentally harder than it looks, and smart people who build distributed systems for a living disagree about whether a specific implementation is correct.** If you're building a quick "don't duplicate work" mechanism and occasional double-processing is merely wasteful (not catastrophic), use a simple Redis SET NX with a TTL and accept the edge cases. If double-processing is catastrophic (double-charging a customer, corrupting financial data), use a proper consensus-based lock (ZooKeeper, etcd) with fencing tokens.

### Leader Election

Leader election is distributed locking applied to a specific use case: "Which instance is the primary?"

**Pattern:**
1. All instances try to create the same ephemeral node in ZooKeeper (e.g., `/election/leader`).
2. Only one succeeds (the first one). That instance is the Leader.
3. All others watch the node.
4. If the Leader crashes, the ephemeral node disappears. The watchers race to create it again. One wins. New Leader.

This is how Kafka brokers elect partition leaders, how HDFS NameNodes do active-passive failover, and how many database clusters implement automatic primary promotion.

---

## Concrete Example From a Real System

**Preventing Duplicate Cron Jobs in a Scaled Application:**

You have a FastAPI application running on 8 Kubernetes pods. You need a cron job that runs every hour: "Sync all updated documents to the vector database." If all 8 pods have the cron scheduler running, the job fires 8 times simultaneously.

**Solution with Redis (acceptable for this use case):**
```python
import redis
import uuid

r = redis.Redis()
my_id = str(uuid.uuid4())

# Try to acquire the lock for 55 minutes (just under the 1-hour cron interval)
acquired = r.set("cron:sync-vectors", my_id, nx=True, ex=3300)

if acquired:
    try:
        run_vector_sync()
    finally:
        # Only delete if we still own the lock
        if r.get("cron:sync-vectors") == my_id.encode():
            r.delete("cron:sync-vectors")
```

This has the Redis single-point-of-failure risk, but for a vector sync job where occasional double-execution is merely wasteful (you re-embed some documents), it's perfectly acceptable.

**Solution with etcd (necessary for financial operations):**
```python
import etcd3

client = etcd3.client()
lock = client.lock('payment-reconciliation', ttl=3600)

if lock.acquire(timeout=5):
    try:
        run_reconciliation()
    finally:
        lock.release()
```

etcd's lock is backed by Raft consensus. Even during a leader failover, the lock is either consistently held or consistently released. No split-brain.

---

## The Tradeoffs

| Mechanism | Correctness | Performance | Complexity |
|-----------|-------------|-------------|------------|
| Database row lock | Weak (crash = stuck) | Slow (full DB round-trip) | Low |
| Redis SET NX + TTL | Good enough for most cases | Fast (~1ms) | Low |
| Redlock (multi-Redis) | Debated/controversial | Fast | Medium |
| ZooKeeper ephemeral nodes | Strong (consensus-backed) | Slower (~10-50ms) | High (ZK cluster needed) |
| etcd lease-based lock | Strong (Raft-backed) | Slower (~10-50ms) | Medium (etcd simpler than ZK) |

**When to use simple Redis lock:** Deduplication where occasional duplicates are tolerable (cron jobs, background syncs, cache warming).

**When to use consensus-based lock:** Financial operations, payment processing, any scenario where double-processing has irreversible consequences.

---

## How This Connects to Other Modules

- **Module 14** (Message Queues): Queue-based task distribution can replace locks entirely — SQS's "visibility timeout" is essentially a lease. When a worker pulls a message, no other worker can see it until the timeout expires. This is often simpler than explicit locking.
- **Module 20** (Consensus): ZooKeeper and etcd's locks work BECAUSE they're built on consensus. The lock's correctness inherits from the Raft/ZAB protocol's guarantees.
- **Module 23** (Distributed Transactions): Sagas don't use locks — they use compensating transactions. But 2PC does use a form of locking (each participant locks its resources until the coordinator says commit/abort).
- **Module 24** (Idempotency): Idempotency is often the better alternative to locking. Instead of "prevent duplicates," you design the system so duplicates are harmless.
- **Module 31** (Multi-Agent Orchestration): Agent task assignment is a distributed lock problem. "Only one agent should work on this sub-task" requires a coordination mechanism.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** The Redlock algorithm details? Textbook noise. You will never implement Redlock. What matters is the *decision framework*: "Is double-processing of this task merely wasteful, or is it catastrophic?" That single question determines whether you use a simple Redis lock (fast, easy, occasionally wrong) or a consensus-backed lock (slow, complex, correct).

The other thing that matters is knowing that **a queue often replaces a lock entirely.** Instead of "acquire lock → process task → release lock," you use "pull message from SQS → process → acknowledge." The queue's visibility timeout acts as a lease. The message automatically reappears if the worker crashes. You get at-least-once delivery without writing any locking code.

**The AI-era connection:** Multi-agent orchestration systems are the poster child for this module. When you have a dispatcher assigning tasks to 20 dynamically-scaling agent workers:
- **Task assignment** is a lock problem. Two workers must not pick up the same task. A message queue (SQS, RabbitMQ) is usually the cleanest solution — each message is a task, visibility timeout is the lease.
- **Shared state mutation** is a lock problem. If two agents are both updating a shared document or a shared "research notes" artifact, you need coordination. Append-only designs (each agent writes to its own section) often eliminate the need for locking entirely.
- **Long-running tasks** break lock TTLs. An agent task might run for 10 minutes. A lock with a 30-second TTL will expire. You need a heartbeat mechanism that extends the lease periodically — exactly like SQS's `ChangeMessageVisibility` extending the visibility timeout for a message being actively processed.

**Brutally honest advice:** Your first instinct when you discover distributed locks will be to lock everything. Don't. Locks reduce throughput (serialization), increase latency (acquisition time), and create deadlock risks. The most experienced distributed systems engineers I know reach for locks as a last resort. Their first question is: "Can I make this operation idempotent so duplicates don't matter?" (Module 24). Their second question is: "Can I use a queue so only one consumer sees the message?" (Module 14). Only if both answers are "no" do they reach for a distributed lock. If you start your design with locks, you're almost certainly over-constraining the system.

---

## Check Your Understanding

1. Worker A acquires a Redis `SET NX` lock with a 30-second TTL. Worker A experiences a 45-second garbage collection pause. What happens, step by step, and what is the state of the system when Worker A resumes?

2. You're using ZooKeeper ephemeral sequential nodes for locking. 50 workers are waiting for the lock. Worker 1 (the current lock holder) finishes and deletes its node. How many of the 49 remaining workers wake up? Contrast this with a design where all workers watch the lock node directly.

3. Your system processes payment refunds. Occasionally processing a refund twice would result in giving the customer double their money back. Should you use a Redis SET NX lock or a ZooKeeper/etcd lock? Why? And is locking alone sufficient, or do you also need something else?

4. An agent orchestration system has 10 worker agents pulling tasks from a shared Postgres table. Describe how you would replace the explicit distributed lock pattern with a message queue (SQS) pattern. What acts as the "lease"?

5. Explain why "making the operation idempotent" is often a better solution than "using a distributed lock." Give a concrete example where idempotency eliminates the need for a lock entirely.

---

### Answers

1. **Answer:** Worker A acquires the lock (token). At second 31, the TTL expires and Redis deletes the key. Worker B calls `SET NX`, succeeds, and starts processing the same task. At second 45, Worker A's GC pause ends. Worker A is unaware the lock expired. It continues processing and attempts to write its result. Now both A and B are working concurrently, and A might overwrite B's work. Without a fencing token, the downstream system has no way to reject A's stale write. This is exactly why fencing tokens are necessary for correctness.

2. **Answer:** With sequential nodes, only 1 worker wakes up — specifically, Worker 2, which was watching Worker 1's node. Worker 2 checks that its node is now the lowest, acquires the lock, and proceeds. The other 48 workers remain sleeping. If all 50 workers were watching the lock node directly, all 49 would wake up simultaneously (thundering herd), all query ZooKeeper to check if they're the new holder, 48 would fail, and the burst of 49 simultaneous requests would spike ZooKeeper's load.

3. **Answer:** You must use a ZooKeeper/etcd lock because double-processing is catastrophic (double refund = financial loss). However, locking alone is NOT sufficient. You also need idempotency (Module 24). Even with a consensus-backed lock, edge cases exist (lock lease expires during a slow network call to the payment provider). The refund endpoint must use an idempotency key so that even if a refund request is sent twice, the payment provider only processes it once. Defense in depth: lock to prevent concurrent processing + idempotency to make duplicates harmless.

4. **Answer:** Instead of workers polling the Postgres table and using `SELECT ... FOR UPDATE` (a lock), you push tasks onto an SQS queue. Each worker calls `ReceiveMessage`, which returns a task and makes it invisible to other workers for a configurable period (the Visibility Timeout — this IS the lease). The worker processes the task and calls `DeleteMessage` when done. If the worker crashes, the visibility timeout expires, and the message reappears for another worker. No explicit lock code needed.

5. **Answer:** If an operation is idempotent, running it twice produces the same result as running it once. Example: "SET user.email = 'new@email.com'" is idempotent — running it 5 times results in the same state. If two workers both execute this simultaneously, the final state is correct regardless of ordering. No lock needed. Contrast with "INCREMENT balance BY 50" — this is NOT idempotent (running it twice adds 100). Here you'd need either a lock, or you'd redesign it as an idempotent operation using a deduplication key: "Apply credit #ABC123 of $50" — the system checks if credit #ABC123 was already applied, and skips if so.

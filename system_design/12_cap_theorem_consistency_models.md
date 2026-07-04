# 12 — CAP Theorem and Consistency Models

## The Problem

You have a database. You replicate it across two data centers for availability — if one data center burns down, the other keeps serving traffic. But the network link between the two data centers fails for 30 seconds (a network partition). During those 30 seconds, you face an impossible choice:

**Option A (Consistency):** Reject all writes. Both data centers refuse to accept new data because they can't confirm the other side has it too. Your system is correct but unavailable. Users see errors.

**Option B (Availability):** Accept writes on both sides independently. Both data centers keep serving traffic. But now User A updates their profile on DC-East while User B reads the old profile on DC-West. When the network heals, you have two conflicting versions of the profile. Your system is available but inconsistent.

You cannot have both. This isn't a software limitation — it's a mathematical impossibility, proven by Gilbert and Lynch in 2002. This is the CAP theorem.

---

## The Naive Approach and Why It Fails

**Naive approach: "Just use a good database and you won't have this problem."**

This fails because CAP is not about database quality. It's about physics. When a network partition occurs (and it will — cables get cut, routers crash, cloud availability zones lose connectivity), every distributed database must choose between consistency and availability. There is no "both" option during a partition. Even the most expensive, well-engineered databases in the world (Google Spanner, CockroachDB, YugabyteDB) make this tradeoff — they just make it more gracefully.

**The second naive approach: "Partitions are rare, so I can ignore CAP."**

Partitions in a cloud environment are not rare. They're just usually short (milliseconds to minutes). AWS documents AZ connectivity issues multiple times per year. What matters is not whether partitions happen, but how your system behaves during one. If you haven't decided in advance, your system will choose for you — usually by doing something confusing and wrong.

---

## The Real Mechanism

### CAP — What C, A, and P Actually Mean

**Consistency (C):** Every read receives the most recent write or an error. All nodes see the same data at the same time. If you write `name = "Alice"` and immediately read, you get "Alice" — never the old value.

**Availability (A):** Every request receives a non-error response, without the guarantee that it reflects the most recent write. The system always answers, even if the answer might be stale.

**Partition Tolerance (P):** The system continues to operate despite network partitions — messages between nodes being dropped or delayed indefinitely.

### Why Partition Tolerance Is Not Optional

A network partition is not a theoretical concern. It's a guaranteed reality in any distributed system:

```
Scenario: Two database replicas in different availability zones.
The network link between them fails.

If you don't tolerate partitions (no P):
  Your system requires ALL nodes to communicate for EVERY operation.
  A single network failure takes down the entire system.
  You've built a single-point-of-failure distributed system.
  This is worse than a single-node database.

Therefore: In any real distributed system, P is mandatory.
The real choice is: CP or AP during a partition.
```

### CP Systems (Consistency + Partition Tolerance)

During a partition, CP systems refuse to serve stale data. They sacrifice availability to maintain consistency.

```
CP behavior during a network partition:
  
  DC-East (has latest data) ←——— PARTITION ———→ DC-West (might be stale)
  
  Client reads from DC-West:
    CP system: "I can't confirm this data is current. Returning ERROR."
    
  Client writes to DC-West:
    CP system: "I can't replicate to DC-East. Rejecting write."
```

*Examples:* PostgreSQL (single-leader replication — writes go to leader only), MongoDB (default config), ZooKeeper, etcd, HBase.

*Use when:* Correctness is more important than availability. Financial transactions, inventory systems, distributed locks. Getting the wrong answer is worse than getting no answer.

### AP Systems (Availability + Partition Tolerance)

During a partition, AP systems keep serving requests on both sides. They sacrifice consistency — you might get stale data.

```
AP behavior during a network partition:
  
  DC-East ←——— PARTITION ———→ DC-West
  
  Client writes to DC-East: name = "Alice"  → Accepted!
  Client writes to DC-West: name = "Bob"    → Accepted!
  
  Partition heals. DC-East has "Alice". DC-West has "Bob".
  Conflict! The database must resolve this somehow:
    - Last-write-wins (LWW): whichever write has the later timestamp "wins"
    - Application-level resolution: your code decides (e.g., merge both)
```

*Examples:* Cassandra, DynamoDB, CouchDB, Riak, DNS.

*Use when:* Availability is more important than immediate consistency. Shopping carts, social media feeds, user activity logs, sensor data. Getting a slightly stale answer is better than getting no answer.

### PACELC — The More Honest Version

CAP only describes behavior during partitions. But partitions are rare. What about normal operation (when there IS no partition)?

PACELC extends CAP: "In case of Partition, choose Availability or Consistency. Else (normal operation), choose Latency or Consistency."

```
PACELC examples:
  
  Cassandra:  PA/EL  (Partition → Available, Else → Low Latency)
    Normal operation: reads can return stale data for lower latency
    During partition: keeps serving both sides
    
  PostgreSQL: PC/EC  (Partition → Consistent, Else → Consistent)
    Normal operation: reads always return latest data
    During partition: rejects operations that can't be confirmed
    
  DynamoDB:   PA/EL  or PA/EC  (configurable per table)
    You choose: eventual consistency (fast) or strong consistency (slower)
```

### Consistency Models — What "Consistent" Actually Means in Practice

"Consistency" is not binary. There's a spectrum:

**Strong Consistency (Linearizability):**
Every read returns the most recent write. All operations appear to happen in a single, global order. This is what ACID "C" means.

```
Write: x = 5  (at time T=1)
Read:  x → 5  (at time T=2, guaranteed to see the write)

Cost: Every read must check the leader (or a quorum). Higher latency.
```

**Eventual Consistency:**
If no new writes occur, all replicas will *eventually* converge to the same value. But between the write and convergence, different replicas may return different values.

```
Write to Leader: x = 5  (at T=1)
Read from Replica A: x → 3  (at T=1.5, hasn't received update yet — STALE)
Read from Replica A: x → 5  (at T=3, update has propagated)

"Eventually" could be 10ms or 10 minutes, depending on replication lag.
```

**Causal Consistency:**
Operations that are causally related are seen in the correct order by all nodes. Operations that are not causally related may be seen in different orders.

```
Alice posts: "I'm getting a dog!"         (at T=1)
Bob replies: "What breed?"                (at T=2, caused by Alice's post)

Causal consistency guarantees: No reader sees Bob's reply without Alice's post.
But two unrelated posts by Alice and Charlie may be seen in different orders
by different readers.
```

**Read-Your-Writes Consistency:**
A user always sees their own writes. Other users may see stale data.

```
Alice updates profile to "Alice Smith" → writes to Leader
Alice reads profile → guaranteed to see "Alice Smith"
Bob reads Alice's profile → might still see "Alice Jones" (stale replica)
```

This is the minimum consistency level most applications need for a good user experience. It's the fix for the replication lag bug described in Module 10.

---

## Concrete Example From a Real System

**Illustrative: Where Eventual Consistency Quietly Bites RAG Systems**

A RAG system stores documents in PostgreSQL (source of truth) and embeddings in a vector database (Pinecone). The sync pipeline uses an async event (Module 15):

```
1. User uploads updated document → Postgres row updated
2. CDC event fires → goes to message queue
3. Worker reads event → re-chunks document → re-embeds → writes to Pinecone
4. Time from step 1 to step 3 completing: 30-120 seconds (async processing)

During those 30-120 seconds:
  User asks: "What does the updated clause say?"
  RAG retrieves chunks from Pinecone → gets OLD embedding → returns OLD text
  User sees the old answer
  User says: "I just updated this document, why is the AI still showing the old version?"
```

This is a consistency bug wearing a hallucination costume. The model is not hallucinating — it's correctly answering based on the data it was given. The data is stale because the system is eventually consistent. Most teams misdiagnose this as a model problem ("the AI is dumb") instead of a system design problem (the vector DB hasn't caught up to the source of truth yet).

**Fix options:**
- **Read-your-writes for the updating user:** After a document update, bypass vector search and serve the updated document directly from Postgres for that specific user until the sync confirms completion.
- **Sync confirmation UI:** Show the user "indexing in progress" after an update, and don't allow questions about that document until sync is confirmed.
- **Reduce the consistency window:** Move from async to near-sync embedding (chunk + embed inline, write to both Postgres and vector DB in the same request path). Trades latency for freshness.

---

## The Tradeoffs

| Model | Guarantee | Cost | Use When |
|-------|-----------|------|----------|
| Strong consistency | Latest data, always | Higher latency, lower throughput | Financial data, inventory, locks |
| Eventual consistency | Data converges "eventually" | Staleness window, possible stale reads | Social feeds, analytics, caches |
| Causal consistency | Cause-before-effect ordering | Moderate overhead (vector clocks) | Chat, comments, collaborative editing |
| Read-your-writes | User sees own writes | Routing complexity (send reads to leader after write) | Any user-facing application |

---

## How This Connects to Other Modules

- **Module 07** (Caching): Every cache is an eventually consistent system. The data in Redis may be stale relative to the database. TTL is your consistency window.
- **Module 10** (Scaling Relational): Async read replicas create an AP system during normal operation. Replication lag is the consistency window.
- **Module 11** (NoSQL): Cassandra is AP. MongoDB is CP. DynamoDB is configurable. CAP determines their fundamental behavior.
- **Module 13** (Replication): The replication topology (leader-follower vs leaderless) determines where on the CAP spectrum your system falls.
- **Module 20** (Consensus): CP systems use consensus algorithms (Raft, Paxos) to agree on the "correct" value during a partition. This is the mechanism behind CP guarantees.
- **Module 23** (Distributed Transactions): Cross-service consistency is a CAP problem. Sagas are an eventually consistent alternative to distributed transactions.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** CAP is one of the most tested concepts in system design interviews. What matters is NOT reciting the theorem — it's demonstrating that you understand: (1) partition tolerance is not optional, so the real choice is CP vs AP, (2) the choice depends on your use case (bank accounts = CP, social feeds = AP), (3) eventual consistency is not "no consistency" — it's consistency with a delay, and your job is to define how long that delay is acceptable, (4) most real systems are not purely CP or AP — they make different choices for different operations (a banking app might be CP for transfers but AP for showing transaction history). Know PACELC — it's a more complete and honest model than basic CAP.

**The AI-era connection:** The most common and most misdiagnosed consistency bug in AI systems is the RAG staleness problem: the embedding index hasn't caught up to the document source of truth. When a user sees an outdated answer after updating a document, they blame the AI. It's not the AI's fault — it's a consistency gap between your document store and your vector store. This is the exact same problem that has existed in database replication for 30 years, wearing an AI costume. The fix is the same: define your consistency window, implement read-your-writes for the updating user, and build observability to track how stale your embedding index is at any given moment. If you can't answer "how far behind is my vector store right now?" you can't manage this consistency tradeoff.

**Brutally honest advice:** Most engineers who say "I chose eventual consistency for performance" have not actually measured the performance difference. On a well-tuned Postgres instance with a single leader and read replicas, the latency difference between a consistent read (from leader) and an eventually consistent read (from replica) is typically 1-3ms. For most applications, that difference is invisible to users. Don't choose eventual consistency because you assume it's faster — choose it because you've measured that strong consistency creates a bottleneck (like write throughput exceeding what a single leader can handle). The cost of debugging consistency bugs (stale data, conflicting writes, mysterious "hallucinations" that are actually stale retrievals) is vastly higher than the cost of the extra millisecond.

---

## Check Your Understanding

1. During a network partition between two data centers, your database can either reject writes (maintaining consistency) or accept writes on both sides (maintaining availability). Explain why it's mathematically impossible to do both.

2. Your Cassandra cluster is AP. Two users simultaneously update the same profile from different data centers during a partition. When the partition heals, how does Cassandra resolve the conflict? What data is lost?

3. A RAG system updates a document in Postgres. The embedding re-generation pipeline takes 60 seconds. During that 60 seconds, what consistency model describes the relationship between Postgres and the vector DB? Is this a "hallucination" or a consistency bug?

4. Your banking application processes transfers. Should it be CP or AP? What does a user experience during a network partition under each choice? Which is more acceptable for a financial product?

5. Explain the PACELC classification of DynamoDB with `ConsistentRead=false` vs `ConsistentRead=true`. What changes, and what is the latency implication?

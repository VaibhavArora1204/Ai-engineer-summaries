# 20 — Consensus Algorithms

## The Problem

You have three servers forming a database cluster. A client writes `balance = $500`. Server 1 receives it. Now Server 1 needs Servers 2 and 3 to also store `balance = $500`. If Server 2 applies it but Server 3 doesn't (because a network packet was dropped), your cluster is in an inconsistent state. One node says $500, another says whatever it had before.

This isn't hypothetical. This is the real, daily failure mode of any system that stores data on more than one machine. Networks drop packets. Machines crash mid-operation. Clocks disagree. And yet your system needs all participants to agree on the same value — or at least know they haven't agreed and refuse to proceed.

This is the **consensus problem**: getting a group of unreliable machines to reliably agree on a single value. It is the hardest fundamental problem in distributed computing.

---

## The Naive Approach and Why It Fails

The naive approach: "Server 1 is the leader. It sends the value to Servers 2 and 3. If they both acknowledge, the write is committed."

This is called a simple two-phase broadcast. It fails in exactly two catastrophic ways:

1. **The leader crashes after sending the write to Server 2 but before sending it to Server 3.** Now Server 2 has the new value and Server 3 doesn't. If Server 3 is elected as the new leader, it has stale data. Writes are lost.
2. **Network partition:** Server 3 can't hear Server 1. Server 1 waits forever for the acknowledgment. If it times out and commits anyway (with only Server 2's ACK), Server 3's data diverges. If it blocks and waits, the entire cluster is unavailable.

The naive approach has no protocol for: Who is the leader? How do you pick a new one? What happens if two nodes both think they're the leader? How do you guarantee a value is *never* rolled back once a client was told it succeeded?

These aren't edge cases. They're the core problem.

---

## The Real Mechanism

### Why Consensus Is Provably Hard

The FLP impossibility result (Fischer, Lynch, Paterson, 1985) proved that in an asynchronous system where even one node can crash, no deterministic algorithm can guarantee consensus in bounded time. This is a mathematical fact, not a limitation of current technology.

Practical consensus algorithms (Paxos, Raft) work around this by using timeouts and randomization — they sacrifice guaranteed termination in theory but work reliably in practice. You should understand FLP the same way you understand the halting problem: you can't solve the general case perfectly, but you can build practical systems that work in all reasonable scenarios.

### Raft — The Practical Algorithm

Raft was designed explicitly to be understandable (unlike Paxos, which is notoriously difficult to implement correctly). Most production consensus systems today either use Raft directly or something heavily inspired by it. etcd (the brain of Kubernetes), CockroachDB, and TiKV all use Raft.

**The Core Idea:** A cluster of nodes elects a single Leader. All writes go through the Leader. The Leader replicates writes to a majority of nodes before acknowledging success. If the Leader dies, a new election happens.

**Three Roles:**
- **Leader:** Handles all client requests. Replicates log entries to followers.
- **Follower:** Passive. Receives replicated entries from the leader.
- **Candidate:** A follower that hasn't heard from the leader in a while and starts an election.

**The Term System:**
Time is divided into "terms" (like political terms). Each term has at most one leader. Terms are monotonically increasing integers. If a node receives a message from a higher term, it immediately steps down and updates its term. This prevents stale leaders from causing damage.

#### Phase 1: Leader Election

1. All nodes start as Followers.
2. Each Follower has a randomized election timeout (e.g., 150-300ms). If it doesn't hear from a Leader before the timer expires, it transitions to Candidate.
3. The Candidate increments its term number and votes for itself.
4. It sends `RequestVote` RPCs to all other nodes.
5. Each node grants its vote to the first Candidate it hears from in that term (one vote per term).
6. If the Candidate receives votes from a majority (e.g., 3 out of 5), it becomes the Leader for that term.
7. The Leader immediately sends heartbeat messages to all followers to prevent new elections.

**Why randomized timeouts?** If all followers had the same timeout, they'd all become candidates simultaneously, split the votes, and nobody would win. Randomization breaks the symmetry — one candidate almost always starts slightly before the others and wins the election.

#### Phase 2: Log Replication

1. A client sends a write to the Leader: `SET balance = $500`.
2. The Leader appends this command to its local log (uncommitted).
3. The Leader sends `AppendEntries` RPCs to all Followers, containing the new log entry.
4. Each Follower appends the entry to its own log and acknowledges.
5. Once the Leader receives acknowledgments from a **majority** (including itself), it considers the entry *committed*.
6. The Leader applies the committed entry to its state machine (the actual database) and responds to the client: "Success."
7. On the next heartbeat, the Leader tells Followers the entry is committed. They apply it to their state machines too.

**The critical invariant:** An entry is committed if and only if it's stored on a majority of nodes. Because any two majorities overlap by at least one node, a new Leader elected after a crash is guaranteed to include at least one node that has every committed entry. No committed data is ever lost.

#### Phase 3: Leader Failure and Recovery

1. Followers stop receiving heartbeats from the Leader.
2. Their election timeouts expire. A new election begins.
3. The new Leader's log must contain all committed entries (the voting protocol ensures this — a Candidate can only win if its log is at least as up-to-date as a majority).
4. The new Leader then replicates any missing entries to followers that fell behind.
5. Client operations resume.

### Paxos — The Academic Foundation

Paxos solves the same problem but is much harder to understand and implement correctly. The key idea: a Proposer suggests a value, Acceptors vote on it, and a value is chosen when accepted by a majority. Multi-Paxos extends single-decree Paxos to a continuous stream of values (like a replicated log).

In practice, you don't need to understand Paxos implementation details. You need to understand that Paxos is the theoretical foundation, Raft is the practical implementation, and both guarantee the same safety properties: once a value is agreed upon, it cannot be un-agreed upon.

### Where Consensus Shows Up in Practice

| System | Consensus For | Implementation |
|--------|-------------|----------------|
| etcd (Kubernetes brain) | Cluster state, service discovery | Raft |
| ZooKeeper | Distributed coordination, config | ZAB (Paxos-like) |
| CockroachDB | Distributed SQL transactions | Raft |
| Kafka (KRaft mode) | Partition leadership, metadata | Raft |
| Consul | Service catalog, KV store | Raft |

---

## Concrete Example From a Real System

**Kubernetes Cluster State:**

When you run `kubectl apply -f deployment.yaml`, here's what happens at the consensus level:

1. The `kubectl` client sends the request to the Kubernetes API server.
2. The API server writes the desired state to **etcd** (e.g., "I want 3 replicas of Pod X").
3. etcd's Raft leader receives this write.
4. The Raft leader replicates the write to a majority of the etcd cluster (typically 3 or 5 nodes).
5. Once a majority acknowledges, etcd tells the API server the write succeeded.
6. The Kubernetes scheduler reads the desired state from etcd and schedules the pods onto physical machines.

If one etcd node dies, the cluster continues operating because the majority is still alive. If the leader dies, a new leader is elected within ~300ms (the election timeout). During the election, writes are temporarily blocked but no data is lost.

**Why 3 or 5 nodes, not 2 or 4?**
You need a majority for consensus. With 2 nodes, a majority is 2 — if one dies, you can't reach consensus (no fault tolerance at all). With 3 nodes, a majority is 2 — you tolerate 1 failure. With 5, a majority is 3 — you tolerate 2 failures. Even numbers don't help: 4 nodes require a majority of 3, tolerating only 1 failure (same as 3 nodes but with more overhead). So you always deploy odd numbers.

---

## The Tradeoffs

| Choice | Benefit | Cost |
|--------|---------|------|
| Raft consensus for all writes | Strong consistency, no data loss after commit | Write latency includes network round-trip to majority |
| Larger cluster (5 vs 3) | Tolerate 2 failures instead of 1 | Every write requires 3 ACKs instead of 2 (higher latency) |
| Single leader for writes | Simple ordering, no write conflicts | Leader is a bottleneck, write throughput capped by one machine |
| Leaderless (like Dynamo) | No single bottleneck for writes | Conflict resolution needed, weaker consistency guarantees |

**When to use consensus:** Whenever correctness matters more than raw performance — config state, leader election, distributed locks, financial ledgers.

**When NOT to use consensus:** For high-throughput data where approximate agreement is fine — analytics counters, caching, eventually-consistent read replicas.

---

## How This Connects to Other Modules

- **Module 12** (CAP): Consensus is the mechanism that delivers the "C" in CP systems. When a partition hits, a Raft cluster refuses writes (sacrificing Availability) rather than risking inconsistency.
- **Module 13** (Replication): Raft's log replication IS the replication mechanism for CP databases. Leader-Follower replication with synchronous ACK from a majority.
- **Module 19** (Service Discovery): etcd, Consul, and ZooKeeper — the Service Registries — all use consensus internally. They can only give you correct, consistent service locations *because* they're built on Raft/ZAB.
- **Module 21** (Distributed Locks): Locks that work across machines need consensus. A Redis `SET NX` is *not* consensus; ZooKeeper's ephemeral nodes *are*.
- **Module 23** (Distributed Transactions): 2PC is a form of consensus, and it inherits all the problems (coordinator failure = cluster stalls).

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** You will almost certainly never implement Raft from scratch. I have never implemented it from scratch in production. What matters is being able to recognize when a problem you're facing IS a consensus problem — because then you know to reach for etcd, ZooKeeper, or a managed service, instead of building a "good enough" homegrown version with Redis flags that works 99.5% of the time and catastrophically fails the other 0.5%.

The telltale signs of a hidden consensus problem:
- "Only one instance should process this task" → distributed lock → consensus
- "All nodes must agree on who the leader is" → leader election → consensus
- "This config change must be seen by all nodes in the same order" → ordered broadcast → consensus

**The AI-era connection:** You probably won't touch consensus directly in a RAG pipeline. But the moment you build a **multi-agent orchestration system** (Module 31), you're swimming in consensus problems:
- Which agent gets assigned this task? (Leader election / lock)
- What is the current state of the shared task queue? (Replicated state machine)
- Did the sub-agent's result get recorded before the coordinator crashed? (Log replication)

If you deploy your agent orchestrator on Kubernetes, you're already relying on etcd's Raft consensus for every pod scheduling and service discovery decision. Understanding that etcd is a 3-node Raft cluster — and that its write throughput is capped by network round-trip time — explains why K8s control plane operations sometimes feel slow and why you should never store high-frequency telemetry data in etcd.

**Brutally honest advice:** The most dangerous mistake an AI engineer makes here is thinking "I don't need consensus, I'll just use Redis." Redis is a single-node data store. Even Redis Cluster uses gossip protocol and hash slots, not consensus — which means during a failover, Redis can and does lose acknowledged writes. If you're using Redis `SET NX` as a distributed lock for "only one agent should process this task," you have a lock that can fail under exactly the conditions where you need it most (network partition, Redis master failover). This is fine for rate limiting. It is not fine for payment deduplication or agent task assignment where double-processing has real consequences. Know the difference, and reach for ZooKeeper/etcd when the lock must be correct, not just fast.

---

## Check Your Understanding

1. A 5-node Raft cluster is operating normally. Two nodes crash simultaneously. Can the cluster still accept writes? What if three nodes crash?

2. During a Raft leader election, two candidates each receive exactly 2 votes out of 5 nodes (the 5th node hasn't voted yet). What happens? How does Raft prevent this from deadlocking forever?

3. A client sends a write to the Raft leader. The leader replicates it to 1 out of 2 followers, then crashes before the second follower receives it. The write was NOT committed (majority not reached). But the one follower that received it now has the entry in its log. What happens to this entry when a new leader is elected?

4. Explain why an even-numbered cluster (e.g., 4 nodes) provides worse availability than a 3-node cluster despite having more hardware. Use the concept of "majority quorum" in your answer.

5. Your AI agent orchestration system uses a Redis `SET NX` lock to ensure only one worker picks up each task. During a Redis master failover (the master dies and a replica is promoted), the replica hasn't received the lock key yet. What specific failure occurs, and how would using etcd with Raft consensus prevent it?

---

### Answers

1. **Answer:** With 2 nodes crashed, 3 out of 5 are alive. A majority of 5 is 3. So yes, the cluster can still elect a leader and accept writes. If 3 nodes crash, only 2 remain — below the majority threshold of 3. The cluster becomes read-only (or completely unavailable for writes) until at least one more node recovers. No data is lost, but new writes are blocked.

2. **Answer:** Neither candidate has a majority (3 out of 5 needed). The election for this term fails. Both candidates' election timers reset with new randomized timeouts. Because the timeouts are randomized, one candidate will almost certainly time out before the other, start a new election in a higher term, and win the 5th node's vote first. This randomization prevents infinite deadlocking.

3. **Answer:** It depends on the new leader's log. If the new leader is the follower that HAS the entry, the entry will be replicated to the other follower and eventually committed. If the new leader is the follower that does NOT have the entry, the entry on the other follower will be overwritten/truncated to match the new leader's log. Because the entry was never committed (majority never reached), this is safe — the client never received a success response.

4. **Answer:** A 4-node cluster requires a majority of 3 to operate. It can tolerate only 1 failure (if 2 die, only 2 remain < 3 majority). A 3-node cluster requires a majority of 2, tolerating 1 failure. Both tolerate exactly 1 failure, but the 4-node cluster pays for an extra machine, uses more network bandwidth for replication, and has higher write latency (3 ACKs vs 2). The 4th node adds cost without adding fault tolerance.

5. **Answer:** During the failover, the Redis replica is promoted to master. Because Redis replication is asynchronous, the `SET NX` lock key may not have been replicated yet. The new master doesn't know the lock exists. A second worker calls `SET NX` on the same key and succeeds — both workers now believe they hold the lock, causing duplicate task processing. etcd prevents this because Raft requires a majority ACK before the lock write is considered committed. If the leader dies before reaching majority, the lock was never committed, and the client is never told it succeeded. If it WAS committed, the new leader is guaranteed to have the lock entry in its log.

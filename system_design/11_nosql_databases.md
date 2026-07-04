# 11 — NoSQL Databases

## The Problem

Relational databases are general-purpose, and ACID guarantees make them safe. But "general-purpose" also means "not specifically optimized for your access pattern." If every query your application runs is "get this one user's profile by their ID," a relational database works — but you're paying for capabilities you don't use (JOINs, complex transactions, schema enforcement) and those capabilities have costs: overhead per write, rigid schemas that require migrations, and scaling limitations because ACID guarantees are expensive to distribute.

NoSQL databases exist because specific access patterns can be served dramatically more efficiently by databases designed exclusively for those patterns. The trade: you give up generality (no ad-hoc JOINs, no multi-table transactions, sometimes no schema enforcement) and get performance, scalability, or flexibility that a relational database can't match for that specific use case.

---

## The Naive Approach and Why It Fails

**Naive approach: "NoSQL is better because it scales."**

This is the most dangerous half-truth in database engineering. NoSQL databases scale horizontally more easily for specific access patterns. But they don't eliminate the hard problems — they move them from the database layer to the application layer. Cross-entity consistency that a relational database handles with a JOIN and a transaction, you must now handle in your application code — manually, with bugs.

The naive approach is choosing a database based on buzzwords ("Mongo is web-scale!") instead of on your actual access patterns. A startup that picks MongoDB because it's "schemaless" and then spends six months debugging data inconsistencies caused by the lack of schema enforcement has not saved time. They've shifted the work from schema design (upfront, measured) to data cleanup (ongoing, chaotic).

**The correct approach:** Choose a database based on one question: **"What does my most common query look like?"** If it's relational (joins, aggregations, ad-hoc queries), use Postgres. If it fits a NoSQL access pattern (key lookup, document retrieval, time-series append, graph traversal), use the NoSQL database optimized for that pattern.

---

## The Real Mechanism

### The Four NoSQL Categories

Each category is optimized for a specific access pattern. They are not interchangeable.

**1. Key-Value Stores (Redis, DynamoDB, Memcached)**

```
Data model: A giant hash map. Key → Value. That's it.
Access pattern: GET key, SET key value, DELETE key
Typical operations per second: 100,000-1,000,000+
Typical latency: <1ms

Example:
  SET "session:abc123" '{"user_id": 42, "role": "admin", "expires": 1720000}'
  GET "session:abc123"
  → '{"user_id": 42, "role": "admin", "expires": 1720000}'
```

*Best for:* Session storage, caching (Module 07), rate limiting counters, feature flags, real-time leaderboards — anything where the query is always "get this one thing by its exact key."

*Not for:* Any query that requires searching by value, filtering, sorting, or joining across multiple keys. "Find all sessions for user 42" requires scanning every key — there is no index on values.

*The important distinction:* Redis is in-memory (fast but limited by RAM). DynamoDB is disk-backed (slower but unlimited capacity). Redis is a cache with persistence options. DynamoDB is a database.

**2. Document Stores (MongoDB, CouchDB, Firestore)**

```
Data model: JSON-like documents, each stored with a unique ID.
Documents can be nested and have varying structures.
Access pattern: GET by ID, query by field values, full-text search

Example document:
{
  "_id": "doc_42",
  "title": "Contract NDA",
  "parties": ["Alice Corp", "Bob Ltd"],
  "clauses": [
    {"type": "termination", "text": "Either party may terminate..."},
    {"type": "confidentiality", "text": "All disclosed information..."}
  ],
  "metadata": {
    "uploaded_by": "user_7",
    "uploaded_at": "2026-01-15T10:30:00Z",
    "page_count": 12
  }
}
```

*Best for:* Content management, catalogs, user profiles, configuration — data that is naturally document-shaped (nested, variable structure) and is mostly queried by its fields.

*Not for:* Data with deep relationships between entities (e.g., "find all users who liked a post by someone who follows me" — this is a graph problem, not a document problem). Also bad for: data that requires strong consistency across multiple documents — MongoDB's multi-document transactions work but are significantly slower and more limited than Postgres transactions.

*The "schemaless" trap:* Document stores don't enforce a schema at the database level. This means every document in a collection can have a different structure. This sounds flexible until you realize that your application code IS the schema — you must validate every document on read because you can't trust the structure. In practice, most mature MongoDB deployments use schema validation (introduced in MongoDB 3.6) to get back the guarantees they initially gave up.

**3. Column-Family Stores (Cassandra, HBase, ScyllaDB)**

```
Data model: Rows organized by partition key, with data stored
in column families. Optimized for write-heavy, time-series data.
Access pattern: Write-append, read by partition key + time range

Example (IoT sensor data):
  Partition key: sensor_id
  Clustering key: timestamp (sorted within partition)
  
  sensor_42 | 2026-07-01T00:00:00 | temp=22.5, humidity=45
  sensor_42 | 2026-07-01T00:01:00 | temp=22.6, humidity=44
  sensor_42 | 2026-07-01T00:02:00 | temp=22.4, humidity=46
  
  Query: "Get all readings for sensor_42 between 00:00 and 00:05"
  → Extremely fast: partition key locates the node, clustering key 
    gives sorted range scan within the partition.
```

*Best for:* Time-series data (metrics, logs, IoT), high-write-throughput systems, data that is naturally partitioned (by device, by tenant, by date).

*Not for:* Ad-hoc queries, JOINs, aggregations across partitions, or any query pattern that doesn't include the partition key. "Find the average temperature across all sensors" requires scanning every partition — a full cluster scan.

*Why it writes so fast:* Cassandra uses an append-only storage engine (LSM tree). Writes go to an in-memory memtable and are flushed to disk as sorted SSTables. No random disk I/O on writes. Compare this to B-tree (Postgres), which must find and update the correct page on disk for every write. For write-heavy workloads, LSM trees are 5-10x faster.

**4. Graph Databases (Neo4j, Amazon Neptune, DGraph)**

```
Data model: Nodes (entities) + Edges (relationships) + Properties
Access pattern: Traverse relationships. "Find connected entities."

Example:
  (:User {name: "Alice"})-[:FOLLOWS]->(:User {name: "Bob"})
  (:User {name: "Bob"})-[:FOLLOWS]->(:User {name: "Charlie"})
  
  Query: "Find all users within 3 hops of Alice"
  Alice → Bob → Charlie (2 hops: found)
  
  In SQL this requires recursive self-JOINs:
    SELECT ... FROM follows f1
    JOIN follows f2 ON f1.target = f2.source
    JOIN follows f3 ON f2.target = f3.source
    WHERE f1.source = 'Alice'
  
  In Cypher (Neo4j):
    MATCH (a:User {name: "Alice"})-[:FOLLOWS*1..3]->(b:User)
    RETURN b.name
```

*Best for:* Social networks, fraud detection (finding suspicious transaction rings), recommendation engines ("users who bought X also bought Y"), knowledge graphs (entity relationships).

*Not for:* Tabular data, time-series, or any access pattern where the primary query is "get one record by ID" or "scan a range of records." Graph databases are optimized for traversals, not scans.

### Vector Databases — The New Category That Doesn't Fit the Classic Taxonomy

Vector databases (Pinecone, Qdrant, Weaviate, Milvus, pgvector) are purpose-built for **approximate nearest neighbor (ANN) search** over high-dimensional embedding vectors. This is the access pattern that drives RAG systems.

```
Access pattern:
  Store: INSERT vector=[0.12, 0.45, ..., 0.89] with metadata
  Query: "Find the 10 vectors most similar to this query vector"
         using cosine similarity or L2 distance

This is NOT a key-value lookup (the "key" is a floating-point vector).
This is NOT a document query (you're searching by geometric proximity, 
not by field values).
This is NOT a range scan (there's no ordering in 1536 dimensions).

It's a fundamentally different access pattern: geometric nearest-neighbor
search in high-dimensional space.
```

**The honest tradeoff: pgvector vs dedicated vector DBs:**

```
pgvector (embedding column in Postgres):
  Pro: One database for everything. No sync issues between Postgres and 
       a separate vector DB. Simpler ops. Transactional consistency with 
       your relational data.
  Con: ANN indexing (IVFFlat, HNSW) is less mature than dedicated vector DBs.
       Performance degrades at very high vector counts (>100M).
       
Dedicated vector DB (Pinecone, Qdrant):
  Pro: Purpose-built ANN indexes (HNSW, product quantization, hybrid search).
       Handles billions of vectors efficiently. Features like metadata filtering
       during vector search.
  Con: Now you have two databases. Document updates in Postgres must be synced 
       to the vector DB. If sync fails, your RAG system answers from stale data.
       This is a consistency bug wearing a hallucination costume (Module 12).
```

---

## Concrete Example From a Real System

**The Access Pattern Decision for a Legal-AI Platform:**

```
Data they store:                          Best database:
─────────────────────────────────────────────────────────
User accounts, orgs, billing              → Postgres (relational, ACID)
Document metadata, permissions            → Postgres (foreign keys, tenant isolation)
Document chunks + embeddings              → Postgres + pgvector (co-located with metadata)
User sessions, rate limit counters        → Redis (key-value, sub-ms latency)
Audit logs (who accessed what, when)      → Cassandra (write-heavy, time-series, never updated)
Entity relationships (contracts between   → Neo4j (graph traversals:
  companies, referenced in other contracts)  "find all contracts connected to Company X")

Total databases in production: 4
Each chosen for a specific access pattern.
```

**Why not "just use Postgres for everything"?** They could — and for a startup, that's the right call. One database is simpler to operate than four. But at scale:
- Audit logs generate 50x the write volume of everything else. Dumping them into Postgres would dominate its I/O budget.
- Entity relationship queries (3+ hop traversals) would require recursive CTEs in Postgres that take seconds, vs milliseconds in Neo4j.
- Session lookups need <1ms latency, which Redis delivers but Postgres can't (network hop + query parse overhead).

---

## The Tradeoffs

| Database Type | Optimized For | Gives Up |
|---------------|--------------|----------|
| Relational (Postgres) | Flexibility, ACID, JOINs, ad-hoc queries | Horizontal write scaling, schema flexibility |
| Key-Value (Redis) | Sub-ms reads by exact key | Querying by value, relationships, durability (unless configured) |
| Document (MongoDB) | Nested/variable data, developer velocity | Cross-document consistency, complex JOINs |
| Column-Family (Cassandra) | Write throughput, time-series, partition scans | Ad-hoc queries, cross-partition aggregation |
| Graph (Neo4j) | Relationship traversals, connected data | Tabular scans, write throughput, horizontal scaling |
| Vector (Pinecone/pgvector) | ANN similarity search over embeddings | Exact lookups, range scans, relational queries |

---

## How This Connects to Other Modules

- **Module 09** (Relational Fundamentals): Everything NoSQL gives up. You must understand what you're losing before you decide to lose it.
- **Module 07** (Caching): Redis is both a NoSQL database AND a cache. The same system serves both purposes.
- **Module 12** (CAP Theorem): Cassandra is AP (available, partition-tolerant, eventually consistent). MongoDB is CP by default. This determines how they behave during network partitions.
- **Module 13** (Replication): Cassandra's leaderless replication (quorum reads/writes) vs MongoDB's leader-follower model — fundamentally different approaches to consistency.
- **Module 15** (Event-Driven Architecture): Keeping multiple databases in sync (Postgres + vector DB) is an event-driven problem — change data capture (CDC) from Postgres feeds updates to the vector DB.
- **Module 22** (Sharding): DynamoDB and Cassandra are natively sharded. Understanding hash-based partitioning from Module 22 explains how they distribute data.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** In interviews, you need to know four things: (1) the four classic NoSQL categories and what access pattern each serves, (2) why you'd pick each one (give a concrete example), (3) what you give up vs a relational database, and (4) that the choice is driven by access patterns, not by hype. If an interviewer asks "why MongoDB?" and you say "because it's web-scale" you've failed. If you say "because our data is naturally document-shaped and we rarely query across documents" you've passed. The actual technology names matter less than demonstrating you understand the tradeoff.

**The AI-era connection:** Vector databases are a genuine new category that emerged from the RAG ecosystem. The access pattern (ANN similarity search in high-dimensional space) didn't exist in production systems at scale before 2022. The honest tradeoff for most teams: start with pgvector inside your existing Postgres instance. You avoid the consistency problem of keeping two databases in sync (a document gets updated in Postgres, but the vector DB still has the old embedding — your RAG system answers from stale data, users think the AI is wrong, but it's actually a database sync bug). Only move to a dedicated vector DB (Pinecone, Qdrant) when you've measured that pgvector's ANN performance genuinely can't keep up with your scale — typically >100M vectors or >1000 QPS of vector search.

**Brutally honest advice:** The most expensive mistake I see AI engineers make with NoSQL is choosing MongoDB "because it's schemaless and easier" and then spending months dealing with data quality issues that Postgres would have caught with a `NOT NULL` constraint. Schemaless doesn't mean "no schema" — it means "the schema is in your application code, undocumented, and unenforced." If you don't have the discipline to validate every document on write and handle every possible structure variation on read, use a database that enforces the schema for you. The 30 minutes you spend writing a `CREATE TABLE` statement saves you 30 hours debugging why some documents have `userId` and others have `user_id` and others have `uid`.

---

## Check Your Understanding

1. Your RAG system stores document metadata in Postgres and embeddings in Pinecone. A user updates a document's content. The Postgres row is updated, but the Pinecone embedding hasn't been re-generated yet. A user asks a question about the document. What happens? Is this a "hallucination" or a database consistency bug?

2. You're building a rate limiter that needs to track API calls per user per minute with sub-millisecond latency. Which NoSQL category is the right fit, and why would Postgres be a poor choice?

3. Your IoT platform ingests 100,000 sensor readings per second. Each reading is timestamped and never updated after insertion. You need to query "all readings from sensor X in the last hour." Which NoSQL category, and why?

4. A social network needs to answer "find friends of friends of Alice who also like jazz." This requires traversing relationships 2 hops deep. Why is this query dramatically faster in a graph database than in a relational database?

5. Your team chose MongoDB for a multi-tenant SaaS application. Six months later, you discover that some tenant documents have `organization_id` as a string, others as an integer, and some don't have the field at all. What went wrong, and how would you prevent this?

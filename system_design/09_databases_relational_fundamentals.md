# 09 — Databases Part 1 — Relational Fundamentals

## The Problem

Every system needs to remember things. Your application server processes a request, computes a result, and then... the process restarts, the server reboots, or the container is recycled. Everything in memory is gone. If you want data to survive a restart, you need to write it to a place that persists independently of your application process. That place is a database.

The question isn't whether to use a database — it's which type, how to structure your data inside it, and how to query it without accidentally creating a system that works beautifully at 100 rows and grinds to a halt at 10 million.

---

## The Naive Approach and Why It Fails

The naive approach is storing data in flat files — JSON, CSV, or SQLite on the local filesystem.

```python
# "Database" v1: a JSON file
import json

def save_user(user):
    with open("users.json", "r+") as f:
        users = json.load(f)
        users.append(user)
        f.seek(0)
        json.dump(users, f)
```

This works for a prototype and fails in production for four reasons:

1. **No concurrent access:** Two requests writing simultaneously corrupt the file. There's no locking, no transaction isolation, no rollback.
2. **No indexing:** To find a user by email, you read the entire file and scan every record. At 1 million users, this takes seconds. A database with a B-tree index does it in microseconds.
3. **No schema enforcement:** Nothing prevents you from saving `{"name": "Alice"}` in one record and `{"username": "Bob", "age": "twenty"}` in another. Your application code is the only thing standing between you and data chaos.
4. **No replication or backup:** If the disk dies, your data is gone. No replicas, no point-in-time recovery, no WAL (Write-Ahead Log).

Relational databases (PostgreSQL, MySQL) solve all four of these problems with decades of battle-tested engineering.

---

## The Real Mechanism

### Tables, Rows, Columns — The Relational Model

A relational database stores data in tables. Each table has a fixed schema (columns with defined types). Each row is a record.

```sql
CREATE TABLE users (
    id         SERIAL PRIMARY KEY,
    email      VARCHAR(255) UNIQUE NOT NULL,
    name       VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE documents (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id),   -- Foreign key
    title      VARCHAR(500) NOT NULL,
    content    TEXT,
    embedding  VECTOR(1536),                   -- pgvector extension
    created_at TIMESTAMP DEFAULT NOW()
);
```

The `REFERENCES users(id)` is a foreign key constraint — the database physically prevents you from inserting a document with a `user_id` that doesn't exist in the `users` table. This is referential integrity, and it's one of the primary reasons relational databases exist: the database enforces data correctness, not your application code.

### Indexes — Why Queries Are Fast (Or Catastrophically Slow)

Without an index, finding a user by email requires a **full table scan** — reading every single row in the table and checking each one. At 10 million rows, this is unacceptably slow.

```sql
-- Without an index on email:
SELECT * FROM users WHERE email = 'alice@example.com';
-- Database reads ALL 10 million rows. Time: ~2 seconds.

-- With an index on email:
CREATE INDEX idx_users_email ON users(email);
SELECT * FROM users WHERE email = 'alice@example.com';
-- Database looks up the B-tree. Time: ~0.5ms.
```

**How a B-Tree Index Works (The Mental Model):**

Think of a phone book. You don't read every page to find "Smith." You open to the middle, see "M," know Smith is in the second half, open to 3/4, see "R," keep going. This is binary search, and it's O(log n).

A B-tree index is a self-balancing tree structure stored on disk:

```
                    [M]
                   /   \
              [D, H]    [R, V]
             / |  \    /  |  \
          [A-C][E-G][I-L][N-Q][S-U][W-Z]
          
Leaf nodes contain pointers to the actual rows on disk.
To find "Smith": traverse 3 nodes (root → R,V → S-U → pointer to row)
At 10 million rows: ~4 node reads (log₂₅₆(10M) ≈ 3-4)
Each node read = 1 disk I/O (or cache hit)
Total time: <1ms
```

**Index Costs — Nothing Is Free:**
- Every index takes disk space (a table with 5 indexes stores the data 6 times in different sort orders).
- Every `INSERT` must update all indexes (a table with 5 indexes does 6 writes per insert, not 1).
- Choosing which columns to index is a critical design decision. Index columns that appear in `WHERE` clauses and `JOIN` conditions. Don't index columns that are rarely queried.

**Composite Indexes:**
```sql
-- If you frequently query: WHERE user_id = ? AND created_at > ?
CREATE INDEX idx_docs_user_date ON documents(user_id, created_at);

-- Column order matters! This index is useful for:
--   WHERE user_id = 5                        ✓ (leftmost prefix)
--   WHERE user_id = 5 AND created_at > '...' ✓ (both columns)
--   WHERE created_at > '...'                 ✗ (can't skip user_id)
```

### Normalization vs Denormalization

**Normalization:** Eliminate data duplication by splitting data across multiple tables linked by foreign keys.

```sql
-- Normalized: user info stored once
users:      {id: 1, name: "Alice", email: "alice@ex.com"}
documents:  {id: 10, user_id: 1, title: "Contract NDA"}
documents:  {id: 11, user_id: 1, title: "Patent Filing"}

-- To get documents with user names: JOIN
SELECT d.title, u.name FROM documents d JOIN users u ON d.user_id = u.id;
```

*Pros:* No data duplication. Update Alice's name in one place, it's correct everywhere. Storage-efficient. Data integrity guaranteed.
*Cons:* JOINs are required for most queries. JOINs are expensive at scale (they multiply the work the database does).

**Denormalization:** Intentionally duplicate data to avoid JOINs.

```sql
-- Denormalized: user name duplicated into every document row
documents:  {id: 10, user_id: 1, user_name: "Alice", title: "Contract NDA"}
documents:  {id: 11, user_id: 1, user_name: "Alice", title: "Patent Filing"}

-- No JOIN needed:
SELECT title, user_name FROM documents WHERE user_id = 1;
```

*Pros:* Queries are faster (no JOINs). Single table scans.
*Cons:* Data duplication. If Alice changes her name, you must update every row in the documents table that contains her name. If you miss one, you have inconsistent data. This is a maintenance nightmare.

**The Real-World Decision:** Start normalized. Denormalize specific queries when you have measured evidence that the JOIN is a bottleneck. Don't denormalize preemptively — you're trading data integrity for speed, and that trade isn't free.

### ACID — The Four Guarantees (With Concrete Failure Examples)

ACID is why you use a relational database instead of a JSON file. Each property prevents a specific class of data corruption:

**Atomicity — All or Nothing**
A transaction either completes entirely or has no effect. If the system crashes mid-transaction, the partially-completed work is rolled back.

```sql
-- Transfer $100 from Alice to Bob
BEGIN;
  UPDATE accounts SET balance = balance - 100 WHERE user_id = 'alice';
  -- ** CRASH HERE **
  UPDATE accounts SET balance = balance + 100 WHERE user_id = 'bob';
COMMIT;

-- Without Atomicity: Alice loses $100, Bob gets nothing. $100 vanishes.
-- With Atomicity: The database rolls back Alice's deduction. No money moves.
```

**Consistency — Rules Are Always Enforced**
The database enforces all constraints (foreign keys, unique constraints, check constraints) at all times. A transaction that would violate a constraint is rejected.

```sql
-- Constraint: balance >= 0
ALTER TABLE accounts ADD CONSTRAINT positive_balance CHECK (balance >= 0);

-- Alice has $50. Tries to transfer $100.
UPDATE accounts SET balance = balance - 100 WHERE user_id = 'alice';
-- ERROR: check constraint "positive_balance" violated. Transaction rejected.
```

**Isolation — Concurrent Transactions Don't Interfere**
Two transactions running simultaneously behave as if they ran sequentially. Without isolation, you get race conditions:

```
Without Isolation (the "lost update" bug):
  Alice's balance: $100
  Transaction A: reads balance ($100), deducts $30  → writes $70
  Transaction B: reads balance ($100), deducts $50  → writes $50
  Final balance: $50 (Transaction A's deduction was silently lost!)
  
With Isolation (SERIALIZABLE):
  Transaction A: reads $100, writes $70
  Transaction B: waits for A to finish, reads $70, writes $20
  Final balance: $20 (correct)
```

Isolation levels (from weakest to strongest): READ UNCOMMITTED → READ COMMITTED → REPEATABLE READ → SERIALIZABLE. Stronger isolation = fewer bugs, but more locking = lower throughput. PostgreSQL defaults to READ COMMITTED, which is sufficient for most applications.

**Durability — Committed Data Survives Crashes**
Once a transaction is committed, it's written to disk (via the Write-Ahead Log). Even if the server loses power immediately after `COMMIT`, the data is recoverable. The WAL is flushed to disk before the commit is acknowledged.

### Connection Pooling — The Hidden Bottleneck

Opening a database connection is expensive. The TCP handshake, TLS negotiation, authentication, and session setup can take 20-50ms. If every HTTP request opens and closes a database connection, you're wasting 20-50ms per request on connection overhead alone.

A connection pool (PgBouncer for Postgres, or built-in pools in ORMs like SQLAlchemy) maintains a set of pre-opened, reusable connections:

```
Without pooling:
  Request 1 → Open connection (30ms) → Query (2ms) → Close connection
  Request 2 → Open connection (30ms) → Query (2ms) → Close connection
  1000 requests/sec = 1000 connections opened/closed per second

With pooling (pool size = 20):
  Request 1 → Borrow connection from pool (0.1ms) → Query (2ms) → Return to pool
  Request 2 → Borrow connection from pool (0.1ms) → Query (2ms) → Return to pool
  1000 requests/sec = 20 connections reused, 0 connections opened/closed
```

**Pool exhaustion** — the single most common production incident with connection pools:

```
Pool size: 20 connections
Normal requests: 5ms each → 20 connections can handle 4,000 req/sec

RAG pipeline request: holds a connection for 5 SECONDS (retrieval + generation)
  → 20 connections × 5 seconds = 4 concurrent RAG requests saturate the pool
  → Request #5 waits for a connection → timeout → 503 error
  → Your entire application is down because 4 RAG requests ate the pool
```

---

## Concrete Example From a Real System

**Illustrative: Schema Design for a RAG Application**

A legal-AI startup builds a document Q&A system. Their schema:

```sql
-- Users and organizations
CREATE TABLE organizations (
    id    SERIAL PRIMARY KEY,
    name  VARCHAR(255) NOT NULL
);

CREATE TABLE users (
    id      SERIAL PRIMARY KEY,
    org_id  INTEGER REFERENCES organizations(id) NOT NULL,
    email   VARCHAR(255) UNIQUE NOT NULL
);

-- Documents and chunks (the RAG data model)
CREATE TABLE documents (
    id          SERIAL PRIMARY KEY,
    org_id      INTEGER REFERENCES organizations(id) NOT NULL,
    title       VARCHAR(500),
    source_url  TEXT,
    uploaded_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE chunks (
    id           SERIAL PRIMARY KEY,
    document_id  INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    content      TEXT NOT NULL,
    embedding    VECTOR(1536),  -- pgvector: OpenAI text-embedding-3-small
    token_count  INTEGER NOT NULL,
    UNIQUE(document_id, chunk_index)
);

-- Indexes for the queries that actually run in production
CREATE INDEX idx_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_chunks_document  ON chunks(document_id);
CREATE INDEX idx_documents_org    ON documents(org_id);

-- The retrieval query (what runs on every user question):
SELECT c.content, c.chunk_index, d.title
FROM chunks c
JOIN documents d ON c.document_id = d.id
WHERE d.org_id = $1                              -- tenant isolation
ORDER BY c.embedding <=> $2::vector              -- cosine distance to query embedding
LIMIT 10;
```

Key design decisions: (1) `org_id` on documents ensures tenant isolation — Organization A can never retrieve Organization B's chunks. (2) `ON DELETE CASCADE` ensures deleting a document automatically deletes its chunks — no orphaned data. (3) The `ivfflat` index enables approximate nearest neighbor search on embeddings — without it, the vector similarity query does a full table scan on every chunk.

---

## The Tradeoffs

| Decision | Benefit | Cost |
|----------|---------|------|
| Normalization | No data duplication, integrity guaranteed | JOINs required, slower reads |
| Denormalization | Fast reads, no JOINs | Data duplication, update anomalies, inconsistency risk |
| More indexes | Faster reads (WHERE, JOIN, ORDER BY) | Slower writes, more disk space |
| Fewer indexes | Faster writes, less disk | Slower reads, full table scans |
| Larger connection pool | Handles more concurrent queries | More memory on DB server, risk of overloading DB |
| Smaller connection pool | Less DB load, more predictable | Requests queue up, higher tail latency |
| Strong isolation (SERIALIZABLE) | No concurrency bugs, simplest mental model | Lowest throughput, most lock contention |
| Weak isolation (READ COMMITTED) | Good throughput, less locking | Possible phantom reads, non-repeatable reads |

---

## How This Connects to Other Modules

- **Module 07** (Caching): You cache to avoid hitting the database. Understanding what queries are expensive helps you know what to cache.
- **Module 10** (Scaling Relational): When a single Postgres instance can't handle the load, you use read replicas and sharding — but only after you've exhausted indexing and caching.
- **Module 11** (NoSQL): NoSQL databases sacrifice the relational model (JOINs, schema enforcement, ACID) for specific performance advantages. Understanding what you're giving up requires understanding what relational databases provide.
- **Module 12** (CAP Theorem): ACID's "Consistency" and CAP's "Consistency" mean different things — a common source of confusion.
- **Module 14** (Message Queues): Decoupling long-running operations (like embedding generation) from the request-response cycle prevents connection pool exhaustion.
- **Module 22** (Sharding): When you need to partition your database across multiple machines, you shard it — but the sharding strategy depends entirely on your schema and query patterns.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** You need to know B-tree indexes cold — not the implementation details, but how to reason about which queries will use an index and which won't. The leftmost prefix rule for composite indexes catches people constantly in interviews and in production. Know ACID — not the academic definitions, but what each property prevents (Atomicity prevents partial failures, Isolation prevents race conditions, Durability prevents data loss on crash). Know the difference between normalization and denormalization and when each is appropriate — this is a design judgment question that comes up in every single system design interview. Everything else (normal forms beyond 3NF, the details of MVCC, the internals of WAL) is reference material.

**The AI-era connection:** Connection pool exhaustion under RAG workloads is one of the single most common production incidents in AI systems built on Postgres, and almost nobody warns you about it. A classic CRUD request holds a database connection for 5-10ms. A RAG pipeline request that does retrieval and then waits for LLM generation can hold a connection for 5-10 *seconds*. That's a 1000x difference in connection hold time. If your connection pool is sized for CRUD workloads (20 connections) and you start running RAG queries through it, 4 concurrent RAG requests will exhaust your entire pool and every other query in your application — user login, health checks, admin dashboard — blocks waiting for a connection. The fix is straightforward: release the database connection immediately after retrieval, before calling the LLM. Don't hold the connection open while waiting for a 5-second model response. This is a queueing theory problem (Module 14) wearing a database costume.

**Brutally honest advice:** AI engineers love ORMs because they abstract away SQL. This is fine until your query is slow and you need to understand why. If you can't read an `EXPLAIN ANALYZE` output and identify whether a query is doing a sequential scan (bad), an index scan (good), or a nested loop join on a large table (catastrophic), you will be unable to diagnose the most common class of production performance issues. You don't need to be a SQL expert, but you need to be able to read a query plan. Spend one hour learning `EXPLAIN ANALYZE` in Postgres. It will save you dozens of hours debugging mysterious slowness later. The ORM is not the bottleneck — your missing index is.

---

## Check Your Understanding

1. You have a `chunks` table with 50 million rows and no index on `document_id`. You run `SELECT * FROM chunks WHERE document_id = 42`. How many rows does the database read? How long does it take? Now you add `CREATE INDEX idx_chunks_doc ON chunks(document_id)`. How many rows does the database read now?

2. You have a composite index on `(user_id, created_at)`. Which of these queries can use the index? (a) `WHERE user_id = 5`, (b) `WHERE created_at > '2024-01-01'`, (c) `WHERE user_id = 5 AND created_at > '2024-01-01'`, (d) `WHERE user_id = 5 ORDER BY created_at DESC`.

3. Your RAG application has a connection pool of 20. Each RAG request holds a connection for 6 seconds (retrieval + LLM generation). What is the maximum number of concurrent RAG requests your system can handle before the pool is exhausted? What happens to request #21?

4. Explain the "lost update" problem that occurs without proper transaction isolation, using a concrete example of two users simultaneously updating a document's `view_count`.

5. You're designing a multi-tenant RAG system. Explain why putting `org_id` in the `WHERE` clause of your retrieval query is a security requirement, not just a performance optimization. What happens if you forget it?

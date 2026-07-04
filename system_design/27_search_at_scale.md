# 27 — Search at Scale

## The Problem

Your application has 50 million product listings. A user types "red running shoes size 10" into the search bar. You need to return relevant results in under 200 milliseconds.

The naive approach — `SELECT * FROM products WHERE description LIKE '%red running shoes%'` — performs a full table scan. The database reads every single row, checks if the string contains "red running shoes," and returns matches. At 50 million rows, this takes 30-60 seconds. Unusable.

Search is one of the most deceptively complex features in a system. It looks like a simple text input, but behind it is an entirely separate data system with its own indexing, ranking, and scaling challenges — distinct from your primary database.

---

## The Naive Approach and Why It Fails

**`LIKE '%keyword%'` on a SQL database:**
- Cannot use indexes (the leading `%` prevents B-Tree lookups).
- Full table scan: O(n) where n = total rows. At 50M rows, unacceptable.
- No ranking: returns results in insertion order, not relevance.
- No fuzzy matching: "runnin shoes" returns zero results.
- No synonym handling: searching "sneakers" won't find products labeled "running shoes."

**Full-text search extensions (Postgres `tsvector`):**
Postgres has built-in full-text search using `tsvector` and `tsquery`. It builds an inverted index on text columns. This works surprisingly well for small-to-medium datasets (under 10 million rows) and avoids adding another system. But it has limits:
- No built-in relevance ranking beyond basic TF-IDF.
- Limited language processing (stemming is basic).
- Scaling beyond one Postgres instance requires sharding the search index, which Postgres doesn't natively support.
- Query syntax is limited compared to dedicated search engines.

For many AI startups, Postgres full-text search is the right starting point. You avoid adding Elasticsearch to your stack, and it handles 80% of use cases.

---

## The Real Mechanism

### The Inverted Index

The core data structure behind all full-text search engines.

**How it works:**

A normal database index maps: row ID → content.
```
Doc 1: "The quick brown fox"
Doc 2: "The lazy brown dog"  
Doc 3: "Quick fox jumps high"
```

An **inverted index** maps: word → list of document IDs containing that word.
```
"the"   → [Doc 1, Doc 2]
"quick" → [Doc 1, Doc 3]
"brown" → [Doc 1, Doc 2]
"fox"   → [Doc 1, Doc 3]
"lazy"  → [Doc 2]
"dog"   → [Doc 2]
"jumps" → [Doc 3]
"high"  → [Doc 3]
```

When a user searches "quick fox":
1. Look up "quick" → [Doc 1, Doc 3]
2. Look up "fox" → [Doc 1, Doc 3]
3. Intersect: [Doc 1, Doc 3]
4. Rank by relevance (TF-IDF, BM25).
5. Return results in order.

Each lookup is O(1) in a hash map. The intersection is O(n) on sorted posting lists. This is how a search across 50 million documents returns in milliseconds.

### Text Processing Pipeline

Before building the inverted index, the text goes through a processing pipeline:

1. **Tokenization:** Split "The quick brown fox" into ["The", "quick", "brown", "fox"].
2. **Lowercasing:** ["the", "quick", "brown", "fox"].
3. **Stop word removal:** Remove common words that don't carry meaning: ["quick", "brown", "fox"].
4. **Stemming/Lemmatization:** Reduce words to their root form. "running" → "run", "shoes" → "shoe". Now a search for "runs" matches documents containing "running."
5. **Synonym expansion (optional):** "sneakers" also indexes under "shoes."

### Relevance Ranking: BM25

Not all matches are equally relevant. BM25 (Best Matching 25) is the standard ranking algorithm:

- **Term Frequency (TF):** A document that mentions "fox" 10 times is probably more about foxes than one that mentions it once.
- **Inverse Document Frequency (IDF):** A term that appears in 90% of documents ("the") is less useful for distinguishing relevance than a term that appears in 0.1% of documents ("aardvark").
- **Document length normalization:** A 10-word document mentioning "fox" once is more focused than a 10,000-word document mentioning "fox" once.

BM25 combines these into a single relevance score. Elasticsearch and most search engines use BM25 by default.

### Elasticsearch Architecture

Elasticsearch is the most widely-used dedicated search engine. Key architectural concepts:

- **Index:** Equivalent to a database table. Contains documents of a similar type.
- **Document:** A JSON object stored in the index.
- **Shard:** An index is split into shards (like database sharding — Module 22). Each shard is a self-contained Lucene index.
- **Replica:** Each shard has replica copies for fault tolerance and read scaling.

**Write path:**
1. Document is sent to the coordinating node.
2. The coordinating node routes it to the correct shard (based on document ID hash).
3. The primary shard indexes the document (builds/updates the inverted index) and replicates to replica shards.
4. By default, the document is NOT immediately searchable — it becomes searchable after a "refresh" (every 1 second by default). This is called **near-real-time search.**

**Read path:**
1. Query is sent to the coordinating node.
2. The coordinating node broadcasts the query to all relevant shards (or specific shards if a routing key is provided).
3. Each shard searches its local inverted index and returns top-N results with scores.
4. The coordinating node merges and re-ranks the results from all shards.
5. Returns the final top-N to the client.

### Keeping Search in Sync With Your Primary Database

Elasticsearch is NOT your primary database. Your source of truth is Postgres (or whatever your primary store is). Elasticsearch is a secondary index that must be kept in sync.

**Sync patterns:**

1. **Application-level dual write:** When you write to Postgres, also write to Elasticsearch. Simple but dangerous — if one write fails and the other succeeds, they're out of sync. No transactional guarantee.

2. **Change Data Capture (CDC):** Use a tool like Debezium to read the Postgres WAL (Write-Ahead Log) and stream changes to Elasticsearch in near-real-time. This is the gold standard — it captures ALL changes (including direct SQL modifications) and guarantees eventual consistency.

3. **Event-driven (Module 15):** When your application writes to Postgres, it also publishes an event to Kafka. A consumer reads the event and updates Elasticsearch. More reliable than dual-write but can miss changes made outside the application (direct SQL, migrations).

### Autocomplete: A Different Problem

Autocomplete ("search suggestions as you type") is NOT full-text search. It has different requirements:
- Must respond in under 50ms (users expect instant feedback).
- Matches prefixes, not full terms ("run" should suggest "running shoes").
- Often backed by a prefix tree (Trie) or an edge-ngram index in Elasticsearch.
- Can use a simple Redis sorted set for the top 1000 most popular queries.

Don't over-engineer autocomplete. For most applications, a Redis sorted set with the top few thousand queries, updated hourly, provides a great user experience with minimal complexity.

---

## Concrete Example From a Real System

**E-Commerce Product Search:**

A marketplace with 20 million products uses:
1. **Primary DB:** Postgres stores product data (name, description, price, seller, stock count).
2. **Search Engine:** Elasticsearch indexes product name, description, and category for full-text search.
3. **Sync:** Debezium reads Postgres WAL and updates Elasticsearch within 2 seconds of any product change.
4. **Autocomplete:** Redis sorted set with the top 5,000 search queries, ranked by frequency. Updated every hour from Elasticsearch analytics.
5. **Filters:** Elasticsearch aggregations for faceted navigation (filter by price range, brand, rating).

When stock hits zero, the product remains in Elasticsearch (for informational display: "Out of stock") but is excluded from the default search results via a filter query: `stock > 0`.

---

## The Tradeoffs

| Approach | Latency | Complexity | Consistency | Scale Ceiling |
|----------|---------|------------|-------------|--------------|
| Postgres LIKE | 30-60 seconds at scale | Zero | Strong (same DB) | ~1M rows |
| Postgres Full-Text (tsvector) | 10-100ms | Low | Strong (same DB) | ~10M rows |
| Elasticsearch | 5-50ms | High (separate system) | Eventual (sync lag) | Billions of docs |
| Algolia (managed) | 5-20ms | Very Low | Eventual | Billions (managed) |

---

## How This Connects to Other Modules

- **Module 07** (Caching): Cache frequent search queries in Redis. If 30% of searches are for the same 100 terms, caching eliminates the Elasticsearch query entirely.
- **Module 11** (NoSQL): Elasticsearch IS a NoSQL document store under the hood. Its inverted index is a specialized data structure for text-search access patterns.
- **Module 15** (Event-Driven): CDC/Debezium streaming Postgres changes to Elasticsearch is an event-driven sync pipeline.
- **Module 22** (Sharding): Elasticsearch's sharding model is consistent hashing applied to a search index.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** Understanding the inverted index is the key conceptual takeaway. Everything else — BM25 scoring, analyzers, shard routing — is implementation detail you'll learn on the job. What matters for system design is knowing: (1) search is a separate system from your primary database, (2) you must keep it in sync (CDC is the right answer), and (3) the search index is eventually consistent with your primary data.

**The AI-era connection:** This is where vector/semantic search and keyword search collide. They solve different problems:

- **Keyword search (BM25/inverted index):** "Find documents containing the exact words 'connection pool timeout.'" Perfect for specific, technical, known-item searches.
- **Semantic search (vector DB/embedding similarity):** "Find documents about database performance issues caused by too many open connections." Understands meaning, not just words.

The most robust production RAG systems use **hybrid search**: run BOTH a keyword search and a vector similarity search, then merge and re-rank the results. Why?

- Semantic search sometimes misses results where the exact keyword would have nailed it (e.g., searching for a specific error code "ECONNREFUSED" — the embedding might not capture this as a connection error).
- Keyword search misses results where the concept is expressed in different words (e.g., "database choking" doesn't match "connection pool exhaustion" by keyword).

Hybrid search gives you both precision (keyword) and recall (semantic).

**Implementation:** pgvector for vector search + Postgres tsvector for keyword search gives you hybrid search in a single database. No Elasticsearch required for many use cases. This is the "boring but correct" architecture that most AI startups should start with.

**Brutally honest advice:** "Just use vector search for everything" is a common beginner mistake in RAG. I've seen teams that ripped out their keyword search and replaced it entirely with semantic search, then wondered why their system couldn't find documents when users searched for specific error codes, ticket numbers, or exact product names. Embeddings compress semantic meaning — they're great at "what is this about?" but lossy on exact strings. Keep keyword search for exact matches. Use semantic search for conceptual similarity. Use both for the best user experience.

---

## Check Your Understanding

1. Explain why `SELECT * FROM products WHERE description LIKE '%running shoes%'` cannot use a B-Tree index, but a full-text search engine can answer the same query in milliseconds.

2. Your Elasticsearch index is synced from Postgres via dual-write (application writes to both). A network hiccup causes the Elasticsearch write to fail while the Postgres write succeeds. What is the user-visible consequence, and how does CDC (Debezium) prevent this?

3. A user searches for "laptop charger" in your product search. Your inverted index has entries for "laptop" and "charger" separately. Document A mentions "laptop" 5 times and "charger" once. Document B mentions "laptop" once and "charger" 8 times. Document C mentions "laptop charger" 3 times. Using the intuition behind BM25 (TF and IDF), which document should rank highest and why?

4. You have a RAG system where users search for technical documentation. A user searches for "ECONNREFUSED error in Node.js." Explain why a pure semantic search (vector similarity) might miss the best result, and how adding keyword search (BM25) would catch it.

5. Your search index has 100 million documents across 10 shards. A user's search query must be broadcast to all 10 shards, each returns its top 50 results, and the coordinating node merges them. What is the latency bottleneck in this architecture? (Hint: think about the slowest shard.)

---

### Answers

1. **Answer:** The leading `%` in `LIKE '%running shoes%'` means the database cannot binary-search the B-Tree index — the match could start at any position in the string, so every row must be checked (full table scan). A full-text search engine builds an inverted index: a pre-computed mapping of every word to the documents containing it. Looking up "running" and "shoes" is a direct hash map/tree lookup (O(1) or O(log n)), then intersecting the two posting lists gives the result. The inverted index is the pre-computed answer to "which documents contain this word?"

2. **Answer:** The product exists in Postgres but is missing from the search index. Users searching for that product won't find it — it's invisible to search despite existing in the database. This silent data loss persists until someone notices or a manual re-index is triggered. CDC (Debezium) prevents this by reading directly from the Postgres WAL (which is written atomically with the Postgres transaction). If the row was committed to Postgres, it will appear in the WAL, and Debezium will deliver it to Elasticsearch. The application never writes to Elasticsearch directly — it can't "forget" to.

3. **Answer:** Document C should rank highest. BM25 considers term frequency (TF) and co-occurrence. Document C has the phrase "laptop charger" mentioned together 3 times, indicating the document is specifically about laptop chargers. Document A is heavily about laptops with a passing mention of chargers. Document B is heavily about chargers with a passing mention of laptops. Document C's balanced, co-occurring mentions signal the highest topical relevance. (In practice, Elasticsearch also supports phrase queries that boost documents where terms appear adjacent, further favoring Document C.)

4. **Answer:** A semantic search encodes "ECONNREFUSED error in Node.js" into a vector. The embedding captures the general concept of "Node.js connection errors." But "ECONNREFUSED" is a specific, exact error code string. The embedding model likely treats it as an unknown token or compresses it into a generic "error" representation, losing the specificity. A document titled "Troubleshooting ECONNREFUSED in Node.js" would be the perfect result, but its vector might not be the closest neighbor to the query vector because the embedding space doesn't precisely represent unique error code strings. A BM25 keyword search trivially matches "ECONNREFUSED" as an exact string, ranking that document #1.

5. **Answer:** The latency is determined by the slowest shard (tail latency). Even if 9 shards respond in 10ms, if shard 7 is overloaded (hot partition, GC pause, disk I/O contention) and takes 500ms, the entire query takes 500ms because the coordinating node must wait for ALL shards before merging. This is the "scatter-gather latency amplification" problem — as you add more shards, the probability that at least one shard is slow on any given query increases, pushing up tail latency even as average per-shard latency stays constant.

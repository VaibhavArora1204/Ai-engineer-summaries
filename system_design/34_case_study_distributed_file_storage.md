# 34 — Case Study: Distributed File Storage (S3 Core Concepts)

## Requirements Clarification

**Functional:**
- Store and retrieve files of any size (1 KB text files to 50 GB video files).
- Support billions of objects across millions of users.
- Each object is identified by a unique key (e.g., `tenant-123/documents/report.pdf`).
- Support metadata (content type, upload date, custom tags).

**Non-Functional:**
- 99.999999999% durability (11 nines — virtually zero chance of data loss).
- 99.99% availability for reads.
- Read latency: under 100ms for small objects, streaming for large objects.
- Cost-efficient: hot data (frequently accessed) and cold data (archives) should have different cost tiers.

---

## Back-of-Envelope Estimation

```
Objects: 1 billion files stored.
Average file size: 2 MB.
Total storage: 1B × 2 MB = 2 PB (petabytes).
New uploads: 10M files/day = 115 files/second.
Downloads: 50M files/day = 578 files/second.
Upload bandwidth: 115 × 2 MB = 230 MB/second inbound.
Download bandwidth: 578 × 2 MB = 1.16 GB/second outbound.

This is the scale that justifies a custom distributed storage system.
Below ~1 TB, just use managed S3 or GCS.
```

---

## High-Level Design

The key architectural insight: **separate metadata from data.**

```
Client → API Gateway → Metadata Service → Metadata DB (Postgres/DynamoDB)
                     → Data Service → Distributed Data Nodes (storage clusters)
```

**Why separate them?**
- Metadata operations are small and fast: "Does this file exist? What's its size? When was it uploaded?"
- Data operations are large and slow: "Give me the 50 GB file."
- Different scaling characteristics: metadata needs low-latency lookups (database), data needs high-throughput streaming (disk arrays).
- You can scale metadata horizontally (shard by object key) independently of data capacity (add more storage nodes).

---

## Deep Dive: The Genuinely Hard Parts

### 1. Chunking Large Files

A 10 GB file isn't stored as a single blob. It's split into fixed-size **chunks** (e.g., 64 MB each).

```
report.pdf (10 GB) → [Chunk 0: 64 MB] [Chunk 1: 64 MB] ... [Chunk 159: 64 MB]
```

**Why chunk?**
1. **Parallel uploads/downloads:** Upload 5 chunks simultaneously instead of streaming 10 GB sequentially. Resumable uploads — if chunk 78 fails, retry only that chunk.
2. **Distributed storage:** Chunks are spread across multiple storage nodes. No single node holds the entire file.
3. **Replication:** Each chunk is replicated independently. Losing a node loses some chunk replicas, not entire files.

**Metadata record for a file:**
```json
{
  "key": "tenant-123/documents/report.pdf",
  "size": 10737418240,
  "content_type": "application/pdf",
  "created_at": "2024-01-15T10:00:00Z",
  "chunks": [
    {"id": "chunk-0", "nodes": ["node-A", "node-D", "node-G"]},
    {"id": "chunk-1", "nodes": ["node-B", "node-E", "node-H"]},
    ...
  ]
}
```

### 2. Replication for Durability

Each chunk is replicated to N nodes (typically 3). If one node's disk fails, the data survives on the other two replicas.

**Replication factor 3:**
- 3 copies of each chunk on 3 different physical machines (ideally in different racks or availability zones).
- Storage overhead: 3x the raw data size (2 PB raw → 6 PB actual storage).
- To lose data, all 3 copies must be destroyed simultaneously. At 11 nines durability, this means losing a file is statistically expected to happen once every few billion years.

**Erasure coding (advanced alternative):**
Instead of 3 full copies (3x overhead), split each chunk into k data fragments and m parity fragments. You can reconstruct the original data from any k of the k+m fragments.

Example: Reed-Solomon (10, 4) — split into 10 data + 4 parity = 14 fragments. Can lose any 4 fragments and still recover. Storage overhead: 1.4x instead of 3x. AWS S3 uses erasure coding for its durability guarantee.

**Tradeoff:** Erasure coding saves 50% storage cost but requires CPU for encoding/decoding and is more complex to implement. Replication is simpler and faster for reads (any replica can serve the full chunk without decoding).

### 3. Consistency Model

**S3's consistency evolution:**
- Pre-2020: S3 was eventually consistent for overwrites and deletes. You could upload a new version, immediately read, and get the old version. This caused real bugs in data pipelines.
- Post-2020: S3 provides strong read-after-write consistency. If a PUT succeeds, a subsequent GET returns the new version. This was a massive engineering effort by AWS.

**How strong consistency works for object storage:**
1. The metadata service is the source of truth for "which version is current."
2. A PUT writes the new object data to storage nodes and atomically updates the metadata.
3. A GET queries the metadata service for the current version, then fetches the data from storage nodes.
4. Because the metadata update is atomic (within a transactional database), reads always see the latest committed version.

### 4. Storage Tiers (Cost Optimization)

| Tier | Use Case | Access Latency | Cost (relative) |
|------|----------|---------------|-----------------|
| Standard (Hot) | Frequently accessed files | Milliseconds | $$$ |
| Infrequent Access | Backup files, accessed monthly | Milliseconds | $$ |
| Archive (Cold) | Compliance archives, accessed yearly | Minutes to hours | $ |
| Deep Archive | Legal holds, rarely if ever accessed | 12+ hours | ¢ |

**Lifecycle policies:** Automatically move objects between tiers:
```
Rule: If an object in Standard tier hasn't been accessed in 90 days, 
      move to Infrequent Access.
Rule: If an object in Infrequent Access hasn't been accessed in 365 days, 
      move to Archive.
```

This is critical for AI pipelines that generate large intermediate artifacts (chunked documents, embedding batches, training datasets) that are needed once and rarely again.

---

## Concrete Example From a Real System

**How S3 Fits Into an AI Pipeline:**

A RAG system's document ingestion pipeline:
1. User uploads a PDF via the web app.
2. The API saves the raw PDF to **S3** (`s3://documents/tenant-123/raw/report.pdf`).
3. A background worker downloads the PDF from S3, extracts text, chunks it.
4. Chunks are stored in Postgres (text) and pgvector (embeddings).
5. Generated audio/image artifacts from the AI pipeline are stored in S3 and served via CDN.

**Why S3 and not the database?**
The PDF is 20 MB. Storing it in Postgres:
- Bloats the database size (slowing backups from 10 minutes to 2 hours).
- Fills the buffer pool with binary data (evicting useful indexes from cache).
- Makes database migrations and schema changes slower.

S3 stores the raw bytes cheaply ($0.023/GB/month). Postgres stores a 100-byte URL pointing to the S3 object. The database stays lean and fast.

---

## The Tradeoffs

| Design Choice | Benefit | Cost |
|--------------|---------|------|
| Separate metadata/data | Independent scaling, optimal storage per type | Two systems to manage, consistency between them |
| Chunking (64 MB) | Parallel I/O, resumable uploads, distributed storage | Overhead for small files, chunk management complexity |
| Replication (3x) | Simple, fast reads from any replica | 3x storage cost |
| Erasure coding | 1.4x storage cost (saves ~50% vs replication) | CPU for encode/decode, slower reads (must reconstruct) |
| Storage tiers | 10-100x cost savings for cold data | Access latency for archived data (minutes to hours) |

---

## How This Connects to Other Modules

- **Module 08** (CDN): S3 is the origin; the CDN is the delivery network. Static assets (images, documents, generated audio) are stored in S3 and served to users through the CDN.
- **Module 13** (Replication): S3's durability comes from the same replication principles — data is copied to multiple nodes across multiple physical locations.
- **Module 14** (Message Queues): S3 event notifications trigger ingestion pipelines. "A new PDF was uploaded to S3" → message to SQS → ingestion worker processes it.
- **Module 22** (Sharding): Object storage systems shard by object key hash. The key prefix determines which storage partition holds the data.

---

## Mentor's Take — What Actually Matters Here

**What matters:** The architectural insight that metadata and data are separate systems with different scaling requirements. This applies everywhere, not just file storage. In your RAG system, the document metadata (title, author, upload date, tenant_id) lives in Postgres. The raw document bytes live in S3. The embeddings live in pgvector. Three different storage systems for three different access patterns. Understanding this separation instinct is the real takeaway.

**The AI-era connection:** AI pipelines generate massive intermediate artifacts:
- Raw uploaded documents (PDFs, images, videos): 10s of MB each.
- Chunked text files: MBs per document.
- Embedding vectors: 100s of MB per tenant.
- Generated outputs (images, audio, reports): MBs each.
- Training datasets and fine-tuning artifacts: GBs.

All of these should live in object storage (S3), not in your database. Your database should store only metadata and references (S3 URLs). This keeps your database fast, your backups small, and your storage costs 10x lower.

**Lifecycle policies** are particularly important for AI: model checkpoints, training data, and intermediate pipeline artifacts are created once and rarely accessed again. Moving them from Standard to Infrequent Access after 30 days and to Archive after 180 days can cut storage costs by 70%.

**Brutally honest advice:** I've seen AI teams store base64-encoded PDFs in Postgres JSON columns. At 100 documents, this works. At 10,000 documents, the database is 200 GB, backups take 4 hours, and every migration is an ordeal. Use S3. Store the URL in Postgres. This is a 10-minute architectural decision that saves weeks of pain later. There is never a reason to store binary files in a relational database.

---

## Check Your Understanding

1. A 1 GB file is uploaded and chunked into 16 × 64 MB chunks. Each chunk is replicated to 3 nodes. How much total storage does this file consume? If Node A (holding replicas of chunks 0, 5, and 12) fails, is any data lost?

2. You use S3 to store uploaded documents for your RAG pipeline. A user uploads a document, and the API returns "Upload successful." 10 seconds later, the ingestion worker tries to read the document from S3 and gets a "NoSuchKey" error. Under S3's pre-2020 eventually consistent model, explain why this could happen. Under the current strongly consistent model, can this still happen?

3. Your AI pipeline generates 500,000 intermediate embedding files (one per document chunk, 6 KB each) in S3 during bulk ingestion. These files are read once during index building and never again. What lifecycle policy would you apply, and how much would it save versus keeping them in Standard tier for 1 year?

4. Explain why erasure coding with a (10, 4) configuration can tolerate more node failures than 3x replication despite using less total storage.

5. Your database stores a `file_url` column pointing to S3 objects. You delete the database record but forget to delete the S3 object. What happens over time, and how do you prevent this?

---

### Answers

1. **Answer:** Raw file: 1 GB. Chunked into 16 chunks. Each chunk replicated 3x. Total: 16 × 64 MB × 3 = 3 GB (3x the original). When Node A fails, chunks 0, 5, and 12 each lose 1 of their 3 replicas. The remaining 2 replicas (on other nodes) are still intact. No data is lost. The system detects the under-replicated chunks and automatically copies them to a new node to restore the replication factor to 3.

2. **Answer:** Pre-2020 eventually consistent S3: The PUT was acknowledged by the primary storage node, but the metadata had not yet propagated to the node serving the GET request. The worker reads from a node that doesn't know the object exists yet. This was a real, documented bug in data pipelines. Current strongly consistent S3: This cannot happen. A successful PUT guarantees that any subsequent GET returns the new object. If the worker gets "NoSuchKey," the upload genuinely failed (check for errors in the upload response).

3. **Answer:** 500K files × 6 KB = 3 GB total. Standard tier for 1 year: 3 GB × $0.023/GB/month × 12 = $0.83/year (trivially cheap at this scale). But the pattern matters at scale — if this grows to 500M files (3 TB), Standard for 1 year = $828/year. Lifecycle policy: move to Infrequent Access after 7 days ($0.0125/GB/month) → $0.0125 × 3000 × 11.75 = $441. Move to Glacier after 30 days ($0.004/GB/month) → even cheaper. Savings: ~50-80% depending on tier. The principle matters more than the specific dollar amount — at petabyte scale, lifecycle policies save millions.

4. **Answer:** 3x replication: 3 copies of each chunk. Can lose any 2 replicas of any chunk and survive. But can tolerate at most 2 node failures (if a chunk has all 3 replicas on the 2 failed nodes + 1 other, it survives; if all 3 replicas are on the 2 failed nodes, it's lost — unlikely but possible with poor placement). Erasure coding (10, 4): data is spread across 14 fragments. Can lose any 4 of the 14 fragments. This means you can lose 4 nodes (each holding 1 fragment) and still reconstruct all data. Storage: 14/10 = 1.4x overhead vs 3x. More fault-tolerant AND cheaper, at the cost of CPU for reconstruction.

5. **Answer:** The S3 object becomes an "orphan" — it exists in S3, consuming storage and costing money, but nothing references it. Over time, orphaned objects accumulate, increasing storage costs with no value. Prevention: (1) Use a cleanup job that lists S3 objects and checks if a corresponding database record exists. Delete orphans. (2) Use S3 lifecycle policies to auto-delete objects older than N days in a specific prefix (e.g., `/tmp/` for intermediate files). (3) Better: delete the S3 object in the same transaction-like flow as the database delete — publish a "file deleted" event to a queue, and a worker handles both the DB delete and the S3 delete. If one fails, the event is retried.

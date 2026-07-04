# 28 — Case Study: URL Shortener

## Requirements Clarification

**Functional:**
- Given a long URL, generate a unique short URL (e.g., `https://short.ly/abc123`).
- Given a short URL, redirect the user to the original long URL.
- Optional: custom short URLs, analytics (click count, referrer), URL expiration.

**Non-Functional:**
- The system is massively read-heavy (100:1 read-to-write ratio — many people click short links, few create them).
- Redirects must be fast: under 50ms for a cache hit, under 200ms for a cache miss.
- Short URLs must be unique and never collide.
- The system must handle billions of URLs over its lifetime.

---

## Back-of-Envelope Estimation

```
Writes (URL creation):
  100M new URLs per month
  = 100M / (2.5M seconds) ≈ 40 writes/second average
  Peak (3x): ~120 writes/second

Reads (redirects):
  100:1 read-write ratio → 4,000 reads/second average
  Peak: ~12,000 reads/second

Storage:
  Each record: short_code (7 bytes) + long_url (avg 200 bytes) + metadata (50 bytes) ≈ 250 bytes
  100M records/month × 250 bytes = 25 GB/month
  5 years: 1.5 TB total

Bandwidth:
  12,000 reads/sec × 250 bytes = 3 MB/sec outbound (trivial)

Verdict:
  40 writes/sec and 12,000 reads/sec with 1.5TB over 5 years.
  A single Postgres instance can handle this easily.
  Add Redis caching for hot URLs, and the DB never sees most read traffic.
  No sharding needed. No microservices needed. This is a one-server problem
  (with a replica for fault tolerance).
```

---

## High-Level Design

```
Client → API Gateway → URL Shortening Service → Database (Postgres)
                                               → Cache (Redis)

Write path: Client sends long URL → Service generates short code → writes to Postgres → returns short URL
Read path:  Client requests short URL → Service checks Redis cache
            → Cache HIT: redirect immediately
            → Cache MISS: query Postgres → cache the result → redirect
```

---

## Deep Dive: The Hard Parts

### 1. Short Code Generation — Uniqueness Without Collisions

**Option A: Hash and truncate.**
```
short_code = base62(md5(long_url))[:7]
```
MD5 the long URL, take the first 7 characters of the base62 encoding. Problem: collisions. Two different long URLs can produce the same 7 characters. You detect the collision (try to INSERT, get a unique constraint violation) and retry with a modification (append a counter). This works but adds complexity and occasional write retries.

**Option B: Pre-generated unique IDs.**
Use a counter or a distributed ID generator (like Twitter's Snowflake) to produce a unique 64-bit integer. Convert it to base62:
```
id = 1000000007 → base62 = "15FTGf"
```
Base62 uses `[a-zA-Z0-9]` — 62 characters. A 7-character base62 string can represent 62^7 = ~3.5 trillion unique codes. At 100M URLs/month, this lasts 2,900 years. No collisions possible because each ID is unique.

**The tradeoff:** Option A gives deterministic mapping (same long URL always gets the same short code, enabling deduplication). Option B gives guaranteed uniqueness but different short codes for the same long URL unless you add a deduplication lookup.

**Practical choice:** Option B with a counter. Use Postgres's auto-incrementing `BIGSERIAL` primary key. Convert the ID to base62 for the short code. Simple, collision-free, fast.

### 2. The 301 vs 302 Redirect Decision

When the user clicks `https://short.ly/abc123`, the server returns an HTTP redirect:
- **301 Moved Permanently:** The browser caches this redirect. Future clicks skip your server entirely — the browser goes directly to the long URL. Good for performance, bad for analytics (you can't count clicks if the browser never calls you).
- **302 Found (Temporary):** The browser does NOT cache the redirect. Every click hits your server. Good for analytics, slightly higher server load.

**Decision:** Use 302 if analytics matter (most commercial URL shorteners). Use 301 if you're building an internal tool and want minimal server load.

### 3. Handling Hot URLs (Callback to Module 22)

A viral tweet links to `short.ly/abc123`. This URL gets 500,000 clicks in 10 minutes. Without caching, all 500K requests hit Postgres. With caching (Redis), the first request populates the cache, and the next 499,999 are served from Redis in <1ms.

**Cache strategy:** Cache-aside (Module 07). On read, check Redis first. On miss, query Postgres, cache the result with a 24-hour TTL. URL mappings are immutable (once created, they don't change), so cache invalidation is trivial — you don't need to invalidate.

### 4. Analytics Pipeline (Callback to Module 14/15)

For each redirect, log the event asynchronously:
1. User clicks short URL.
2. Server looks up long URL and issues a 302 redirect.
3. **Asynchronously**, the server publishes a click event to a message queue (Kafka/SQS):
   ```json
   {"short_code": "abc123", "timestamp": "2024-...", "ip": "...", "user_agent": "...", "referrer": "..."}
   ```
4. A background worker consumes click events and updates an analytics table (or sends to a data warehouse).

This is critical — the analytics write must NOT block the redirect response. The user should be redirected in <50ms; the analytics can be processed seconds later.

---

## Bottlenecks and Fixes

| Bottleneck | Trigger | Fix |
|-----------|---------|-----|
| Database read overload | Viral URL → 100K reads/sec | Redis cache (immutable data, easy caching) |
| Write throughput | Bulk URL creation API | Batch inserts, or pre-generate ID ranges |
| Short code collision | Hash-based generation | Switch to counter-based (BIGSERIAL + base62) |
| Analytics blocking redirects | Inline analytics write | Async: publish to queue, process in background |

---

## What Real Systems Do Differently

- **Bit.ly** uses a counter-based ID system with base62 encoding, stored in a distributed database.
- **TinyURL** allows custom aliases, which introduces additional uniqueness checking against user-provided strings.
- **Most systems** separate the redirect path (optimized for speed: Redis cache → single-row DB lookup) from the analytics path (asynchronous, eventually consistent).
- Enterprise URL shorteners often use Redis Cluster or a CDN for redirect resolution, eliminating the database entirely from the hot path.

---

## Mentor's Take — What Actually Matters Here

**What matters:** This is the "Hello World" of system design. Its real value is teaching you to think in terms of: estimation → access patterns → caching strategy → async analytics. The URL shortener itself is trivially simple. The design thinking it teaches — especially the read-heavy optimization pattern (cache immutable data aggressively) and the async analytics pattern (don't block the critical path with logging) — appears in every system you'll ever build.

**The AI-era connection:** This same architecture applies to any AI system with a "hot result" pattern. If your RAG system generates a popular report that gets shared, you're looking at the same hot-key problem. Cache the generated result (Module 07). Serve it from Redis. Log access events asynchronously. The URL shortener is a 100-line system that teaches patterns you'll use at 100x the complexity.

**Brutally honest advice:** If you're asked to design a URL shortener in an interview and you immediately jump to sharding, microservices, or Kafka — stop. You'll look like you don't understand scale. Show the math: 40 writes/sec, 12K reads/sec, 1.5TB over 5 years. This is a single Postgres + Redis problem. Showing that you know when NOT to add complexity is more impressive than showing you know every distributed system tool.

---

## Check Your Understanding

1. You're using hash-based short code generation. Two different long URLs produce the same short code. Your system detects the collision on INSERT (unique constraint violation). Describe the retry mechanism, and explain a potential issue if the retry also collides.

2. Why is it safe to cache URL mappings in Redis with a very long TTL (24 hours or more), but NOT safe to cache user profile data with the same long TTL?

3. You switch from 302 redirects to 301 redirects. What happens to your analytics dashboard, and why?

4. Your URL shortener goes viral. 200,000 redirects per second for a single short URL. Redis is handling it fine, but your analytics Kafka queue is backing up. What's the consequence, and is it acceptable?

5. A user creates a short URL that points to a phishing site. How would you design an abuse detection system without adding latency to the redirect path?

---

### Answers

1. **Answer:** On collision, you modify the input (e.g., append a counter: `hash(long_url + "1")`) and regenerate the short code. If this also collides, increment the counter and retry. The issue: in the worst case (many collisions), you retry multiple times, each requiring a database INSERT attempt. This adds latency to URL creation and can cause database contention under high write load. Counter-based generation avoids this entirely.

2. **Answer:** URL mappings are immutable — once `abc123 → https://example.com/long-url` is created, it never changes. There's no cache invalidation problem. User profile data changes (name, email, settings). A 24-hour TTL means users might see stale data for up to 24 hours after an update, which is a bad user experience.

3. **Answer:** Your analytics dashboard shows dramatically fewer clicks. With 301 redirects, browsers cache the mapping and stop calling your server on subsequent clicks. You never see those redirects, so you can't count them. Your analytics will show only first-time clicks from each browser, massively undercounting actual traffic.

4. **Answer:** The analytics queue backing up means click events are being buffered in Kafka. Analytics data (click counts, geographic distribution) will be delayed — the dashboard might be minutes or hours behind real-time. However, the redirect itself is unaffected (it doesn't depend on analytics). This is acceptable because analytics are eventually consistent by design — a few minutes of delay in click counts is fine. The redirects keep working at full speed.

5. **Answer:** Check URLs asynchronously, not at redirect time. When a new short URL is created, enqueue a background job to scan the long URL against phishing blacklists (Google Safe Browsing API). If flagged, mark the short URL as malicious in the database. At redirect time, check a `flagged` boolean column (which is cached in Redis). If flagged, show a warning page instead of redirecting. The phishing check happens after creation (minutes later), not at redirect time (which would add seconds of latency).

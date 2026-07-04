# 08 — Content Delivery Networks

## The Problem

Your application servers are in AWS `us-east-1` (Virginia). A user in Sydney, Australia opens your web app. The physics of light through fiber optic cables dictates a hard, non-negotiable minimum latency: a round trip from Sydney to Virginia takes about 200ms. This is not a software problem. This is the speed of light through 15,000 kilometers of glass. No amount of code optimization, database tuning, or algorithm improvement can fix this.

If your webpage requires 5 sequential assets to load (HTML → CSS → JS → Logo → Font), that's 5 round trips. 5 × 200ms = 1 full second of delay purely from physics, before your server even starts processing. Your server's 10ms response time is drowned out by the speed of light. The user in Sydney experiences a slow, janky page that a user in New York never encounters. Your problem isn't compute. Your problem is geography.

You cannot make the speed of light faster. You must move the data closer to the user.

---

## The Naive Approach and Why It Fails

**Naive approach: "I'll deploy my entire stack to multiple regions!"**

You spin up application servers, databases, Redis instances, and vector databases in Virginia, Sydney, London, and Tokyo. Every region runs a complete copy of your system.

This fails catastrophically for three reasons:

1. **Database replication across continents is one of the hardest problems in distributed systems.** Multi-master replication with conflict resolution across 200ms links introduces consistency nightmares (Module 12, Module 13). User A updates a document in Virginia. User B updates the same document in Sydney. Which write wins? How do you detect and resolve the conflict? This is the exact problem that Google Spanner exists to solve — and Google built custom atomic clocks into their data centers to make it work.

2. **You're over-engineering for a static file problem.** 80-90% of the bytes a browser downloads from your web app are static assets: HTML, CSS, JavaScript bundles, images, fonts. These don't change per user. They don't need multi-region databases. They need to be physically closer to the user.

3. **Operational complexity explodes.** Every region needs monitoring, alerting, deployment pipelines, database backups, and on-call rotation. You've 4x'd your operational surface area to solve a problem that has a simpler, cheaper, battle-tested solution.

The solution is a Content Delivery Network: a third-party infrastructure that caches your static (and increasingly dynamic) content on servers distributed globally, without you deploying a single additional server.

---

## The Real Mechanism

### What a CDN Actually Is

A CDN (Cloudflare, Fastly, Akamai, AWS CloudFront) is a globally distributed network of proxy servers called Points of Presence (PoPs). These companies deploy racks of servers in hundreds of cities worldwide — in IXPs (Internet Exchange Points), co-location facilities, and ISP data centers.

When you configure a CDN, you change your DNS records so that user requests hit the CDN's nearest PoP first, not your origin server.

```
Without CDN:
  User (Sydney) → DNS resolves to Origin (Virginia, 15,000 km away)
  Request:   200ms (speed of light through fiber)
  Response:  200ms (speed of light back)
  Total:     400ms minimum round-trip, PLUS server processing time
  
  For a webpage with 10 assets, each requiring a round trip:
  10 × 400ms = 4 seconds of network latency alone

With CDN:
  User (Sydney) → DNS resolves to CDN Edge Node (Sydney, 10 km away)
  Request:   2ms
  Response:  2ms
  Total:     4ms round-trip for each cached asset
  
  Cache HIT:  Edge node has the file → returns it in 4ms. Origin does zero work.
  Cache MISS: Edge node fetches from Origin (400ms), returns to user,
              AND caches the file. Every subsequent Sydney user gets 4ms.
```

### The Mechanics of a CDN Request

When a request arrives at a CDN edge node, here's what happens step by step:

```
1. DNS Resolution:
   User's browser resolves cdn.yourapp.com
   → CDN's authoritative DNS uses anycast routing (or geolocation DNS)
   → Returns the IP of the nearest PoP (e.g., Sydney node)

2. TLS Termination:
   User does TLS handshake with the Sydney edge node (4ms round trip)
   NOT with Virginia (400ms round trip)
   This alone saves ~400ms on the first request.

3. Cache Lookup:
   Edge node looks up the requested URL in its local cache
   Key: URL + Vary headers (e.g., Accept-Encoding)
   
4a. Cache HIT:
   Return cached response immediately.
   Add headers: X-Cache: HIT, Age: 3600 (seconds since cached)
   Total latency: ~4ms
   
4b. Cache MISS:
   Edge node fetches from your origin server.
   CDN maintains warm, persistent TCP/TLS connections to your origin
   (pre-negotiated, keep-alive). This avoids the 400ms TLS handshake
   on every miss — the connection is already established.
   
   Edge node receives the response, caches it locally, returns to user.
   Total latency: ~450ms (still faster because TLS was local)
   
5. Cache Storage:
   Response stored locally with TTL from Cache-Control header.
   max-age=86400 → cached for 24 hours.
   s-maxage=3600 → CDN caches for 1 hour (overrides max-age for shared caches).
```

### Static vs Dynamic Content Delivery

**Static Content (What CDNs Were Built For):**
Images, CSS, JavaScript bundles, fonts, videos, PDFs. These don't change per user. The CDN caches them based on the URL. By putting static assets behind a CDN, you remove 80-90% of bandwidth from your origin servers.

```
A single page load for a modern web app:
  index.html           →  5 KB
  app.bundle.js        → 300 KB
  styles.css           → 50 KB
  logo.svg             → 15 KB
  inter-font.woff2     → 90 KB
  hero-image.webp      → 200 KB
  ────────────────────────────────
  Total:                 660 KB
  
  Without CDN: Your API server sends 660 KB × every user
  With CDN:    Your API server sends 0 bytes for static assets
               (CDN serves them all from edge)
```

**Dynamic Content (The Modern Evolution):**
API responses, user-specific data, personalized content. These change per user and generally cannot be cached globally. However, CDNs still help:

- **Connection pooling & keep-alive:** The CDN maintains warm, persistent TCP/TLS connections to your origin. A user in Sydney does a fast TLS handshake with the local CDN node (4ms). The CDN forwards the API request over its pre-warmed connection to Virginia. This eliminates the 400ms cross-globe TLS handshake the user would otherwise pay on every request.

- **Edge Compute (Cloudflare Workers, Lambda@Edge, Fastly Compute):** Run lightweight functions directly on the CDN edge node. Authentication checks, A/B test routing, geolocation-based personalization, header manipulation, or even semantic cache lookups — all executing 10km from the user instead of 15,000km away. This is where CDNs stop being "just a cache" and become an application execution layer.

- **Stale-While-Revalidate:** Return the cached (potentially stale) response immediately while asynchronously fetching a fresh copy from the origin. The user gets a fast response, and the cache gets updated for the next request. This is controlled by the `stale-while-revalidate` directive in the `Cache-Control` header.

### Cache Invalidation at the Edge — The Versioned URL Pattern

Your build system generates a new `app.js`. But the CDN has the old version cached across 200 global edge nodes with a 24-hour TTL. If you wait for TTL expiry, users see a broken site for up to 24 hours (new HTML referencing CSS classes that don't exist in the old cached CSS).

**The dangerous approach: Purge/Invalidate APIs.** CDNs offer API endpoints to purge cached content. You call the API, and the CDN invalidates the file across all 200 nodes. Problems: (1) propagation takes seconds to minutes, (2) there's a brief window where some users get old content and some get new, (3) if you purge wrong, you cause a cache stampede against your origin.

**The correct approach: Cache Busting via Versioned URLs.**

```
Instead of:   /static/app.js        (mutable — same URL, content changes)
Use:          /static/app.a3f2b1.js (immutable — new content = new URL)

How it works:
  1. Your build tool (Webpack, Vite, esbuild) generates a content hash
     of the file and includes it in the filename.
  2. Your HTML references the hashed filename.
  3. When the code changes, the hash changes, the URL changes.
  4. A new URL is always a cache MISS → CDN fetches the new file.
  5. The old URL is still cached, but nothing references it anymore.
  6. You set TTL to 1 year (effectively "forever") for hashed assets.
  7. You NEVER need to manually invalidate.

The only file that changes URL is index.html (which references the hashed
assets). Set index.html to a short TTL (5 minutes) or no-cache.
```

This pattern is so standard that every modern frontend build tool supports it out of the box. If you're not using it, you will inevitably cause a production incident where users see a cached CSS file applied to a new HTML structure, and the site looks like a broken Picasso painting.

### CDN Security — DDoS Protection as a Side Effect

Because all traffic flows through the CDN before reaching your origin, CDNs naturally act as a DDoS shield. Your origin server's IP is hidden behind the CDN's anycast network. The CDN absorbs volumetric attacks across its massive global infrastructure. Cloudflare, for example, regularly absorbs attacks exceeding 1 Tbps without any impact on the origin. This is not CDN's primary purpose, but it's one of the most valuable side effects.

---

## Concrete Example From a Real System

**Illustrative: AI Image Generation Platform**

A team builds a text-to-image application (like Midjourney). Users in London generate images. The GPU inference servers are in Virginia.

```
Without CDN:
  1. User (London) → POST /generate (prompt: "cyberpunk city") → Virginia
  2. GPU generates 4 images (5 seconds)
  3. Virginia server streams 4 images (5MB each, 20MB total) to London
  4. 20MB traverses the Atlantic: ~3 seconds download time
  5. Total: 8 seconds
  6. When user shares the link on Twitter:
     Next 10,000 European viewers each download 20MB from Virginia
     = 200 GB of transatlantic bandwidth from your Python server
     
With CDN + Object Storage:
  1. User (London) → POST /generate → Virginia
  2. GPU generates 4 images (5 seconds)
  3. Virginia server uploads images to S3 bucket (fast, same region)
  4. Returns 4 CDN URLs to the client: cdn.yourapp.com/images/abc123_1.webp
  5. Client requests images from CDN
  6. London CDN node fetches from S3 (once), caches, serves to user
  7. Total: 5.5 seconds (generation + fast CDN delivery)
  8. When user shares on Twitter:
     10,000 European viewers download from London/Paris/Frankfurt CDN nodes
     = 0 bytes from your Virginia server
     = 0 GPU server bandwidth consumed
```

The CDN converts a scaling problem (every viewer hits your origin) into a caching problem (origin hit once per asset per edge node). Your GPU servers focus on generation, not serving cached images.

---

## The Tradeoffs

| Mechanism | Benefit | Cost |
|-----------|---------|------|
| Using a CDN at all | Massively lower global latency, reduced origin bandwidth, DDoS absorption | Added layer (DNS config, cache headers), potential caching bugs, cost per GB served |
| Long TTLs on edge | Near 100% hit rate, extremely fast, minimal origin load | Data is stale longer — must use versioned URLs for assets |
| Caching API responses at edge | Huge origin offload for public, non-personalized APIs | Risk of serving User A's private data to User B if `Cache-Control` and `Vary` headers are misconfigured — a privacy/security incident |
| Edge Compute (Workers) | Run logic close to user (auth, routing, A/B tests) | Harder to debug (no local reproduction), limited execution time and memory, vendor lock-in |
| Stale-While-Revalidate | Users always get fast responses, cache freshness eventually catches up | Brief window of stale data; origin must handle async revalidation requests |

---

## How This Connects to Other Modules

- **Module 02** (Networking): CDNs mitigate the speed of light and TLS handshake costs globally. TLS termination at the edge saves the most expensive part of HTTPS (the handshake round trips).
- **Module 03** (Scalability): CDNs are the ultimate horizontal scaling for static reads — distributing load across thousands of third-party servers you don't manage.
- **Module 07** (Caching): A CDN is a distributed HTTP cache (Cache-Aside pattern) operating at the network edge. The same concepts apply: TTL, eviction, invalidation, cache busting.
- **Module 16** (API Design): HTTP `Cache-Control` headers determine CDN behavior. Understanding these headers is essential for correct CDN configuration.
- **Module 34** (Distributed File Storage): CDNs almost always sit in front of object storage (S3, GCS) to serve user-uploaded or generated media.
- **Module 35** (Notification System): Push notification payloads often reference CDN URLs for images and media.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** You will never build a CDN. You will configure Cloudflare, AWS CloudFront, or Fastly. What actually matters is understanding three things: (1) the `Cache-Control` header and its directives (`max-age`, `s-maxage`, `no-cache`, `no-store`, `stale-while-revalidate` — know what each does), (2) the critical difference between caching static files (safe, do it aggressively) and caching dynamic API responses (dangerous, requires careful `Vary` header configuration to avoid serving private data cross-user), and (3) the absolute necessity of URL versioning/cache busting for deployed assets. Interview questions about CDNs are straightforward once you can explain the request flow (DNS → edge → cache check → origin on miss → cache populate) and articulate why a CDN improves performance even for cache misses (TLS termination at the edge).

**The AI-era connection:** Here is the brief, honest truth: if you are building an agent orchestration system, an internal RAG tool, or a B2B AI copilot, a CDN is not your performance bottleneck right now. Your bottleneck is the 5-second LLM generation time, not the 100ms network transit time. If an API call takes 5,000ms, shaving 100ms off via edge routing is a 2% improvement. Nobody will notice.

However, the moment your AI application generates media (images via Stable Diffusion, audio via TTS, video via Sora) or serves large document chunks to the frontend for highlighting and annotation, the CDN becomes critical again. You do not want your expensive GPU API servers spending their bandwidth streaming 10MB PDF chunks or generated images to end users. Upload the output to S3, return a CDN URL, and let the edge network handle the heavy lifting of bytes. Your GPU servers should be doing inference, not acting as file servers.

**Brutally honest advice:** Don't waste time over-engineering a multi-region API deployment to reduce latency until you've measured where the latency actually is. Engineers from traditional web backgrounds obsess over edge routing and CDN configuration because in classic web apps, network latency was the largest slice of the latency pie. In AI apps, model inference *is* the pie — it's 95% of your latency. Shaving 200ms off network transit when the LLM takes 5,000ms is polishing the deck chairs. Use a CDN for your React/Next.js frontend and for serving generated media assets. Don't expect it to make your AI product feel faster. Focus on inference optimization (Module 07 of the LLM Papers curriculum) first. The CDN will be essential when you scale to a global user base, but it's not the lever that moves the needle on perceived performance for AI-powered features.

---

## Check Your Understanding

1. A user in Tokyo requests `style.css` from your CDN. The CDN node in Tokyo has never seen this file before. Describe the exact sequence of events (DNS, TLS, cache lookup, origin fetch, cache populate, response) that occurs to fulfill this request.

2. Why is relying on manual cache purge/invalidation via a CDN provider's API considered a fragile operational practice compared to URL versioning (cache busting)? What specific failure modes does manual purging introduce?

3. You have an endpoint `GET /api/v1/user/settings` that returns personalized user configuration. A junior engineer suggests caching this on the CDN to reduce database load. Explain why this is potentially a privacy-violating catastrophe, and describe the specific HTTP headers (`Cache-Control`, `Vary`) that must be configured to prevent it.

4. Your application generates a 15-second audio clip using a Text-to-Speech model and serves it to the user. Draw the architecture showing how a CDN, Object Storage (S3), and your API server should interact. What are the exact steps, and why does this architecture prevent your API server from becoming a bandwidth bottleneck?

5. In a RAG application where the average LLM response generation takes 4 seconds, calculate the percentage improvement in total response time from: (a) edge-caching the JavaScript bundle (saving 150ms of load time), (b) edge-routing the API call via CDN connection pooling (saving 50ms of TLS setup), and (c) implementing response caching that avoids the LLM call entirely (saving 4000ms). Which investment has the highest ROI?

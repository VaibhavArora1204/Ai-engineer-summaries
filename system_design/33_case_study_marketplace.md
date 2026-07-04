# 33 — Case Study: High-Scale Consumer Marketplace (Swiggy/Zomato-Class)

## Requirements Clarification

**Functional:**
- Users browse restaurants, view menus, place food orders.
- System matches orders with delivery partners in real-time.
- Real-time order tracking (user sees delivery partner's location on a map).
- Restaurant manages availability (mark items as out of stock in real time).

**Non-Functional:**
- Handle 100,000+ concurrent orders during peak (dinner time).
- Order placement to restaurant notification: under 3 seconds.
- Real-time location updates: every 5 seconds from delivery partner.
- High write contention: 50 people might order the last biryani at the same restaurant simultaneously.
- Geospatial queries: "Show me restaurants within 5 km" in under 200ms.

---

## Back-of-Envelope Estimation

```
Users: 50M monthly active users, 5M daily active users.
Orders: 2M orders/day.
QPS: 2M / 86,400 ≈ 23 orders/second average.
Peak dinner (7-10 PM, 3 hours): 2M × 0.6 / 10,800 ≈ 111 orders/second.
Peak burst (3x): ~330 orders/second.

Restaurant searches: 10x orders = 20M searches/day.
Peak search QPS: ~3,300 searches/second.

Delivery partner location updates:
  100K active delivery partners during peak.
  Update every 5 seconds: 100K / 5 = 20,000 location writes/second.

Real-time tracking reads:
  Each active order triggers location reads every 3 seconds from the user's app.
  100K active orders: 100K / 3 = 33,000 location reads/second.

Storage:
  Order records: 2M/day × 2 KB = 4 GB/day. 1 year: 1.5 TB.
  Location history: 20K writes/sec × 50 bytes = 1 MB/sec = 86 GB/day.
  If stored for 30 days: 2.6 TB. (Most location history is ephemeral.)
```

---

## High-Level Design

```
User App → API Gateway → Load Balancer
                              ↓
    ┌──────────────┬──────────┼──────────┬──────────────┐
    ↓              ↓          ↓          ↓              ↓
Restaurant     Search      Order      Delivery      Tracking
Service        Service     Service    Matching      Service
    ↓              ↓          ↓          ↓              ↓
Restaurant    Elasticsearch  Postgres   Matching      Redis
DB (Postgres)  + Geospatial   (Orders)   Algorithm    (Location Cache)
                Index                                     ↓
                                                    WebSocket/SSE
                                                    to User App
```

---

## Deep Dive: The Genuinely Hard Parts

### 1. Geospatial Queries — "Restaurants Within 5 km"

**The mechanism: Geohashing**

Geohashing converts a 2D coordinate (latitude, longitude) into a 1D string. The key insight: nearby locations share a common prefix.

```
Location: 12.9716°N, 77.5946°E (Bangalore)
Geohash:  "tdr1wc" (precision 6 = ~1.2 km × 0.6 km cell)

Location: 12.9720°N, 77.5950°E (200 meters away)
Geohash:  "tdr1wc" (same prefix!)

Location: 28.6139°N, 77.2090°E (New Delhi — far away)
Geohash:  "ttnfv1" (completely different prefix)
```

**How "find restaurants within 5 km" works:**
1. Compute the user's geohash at a precision that covers ~5 km (precision 4-5).
2. Query: `WHERE geohash LIKE 'tdr1%'` — this returns all restaurants in the same geospatial cell.
3. Include the 8 neighboring cells (geohash edge case: a location near a cell boundary would miss nearby restaurants in the adjacent cell).
4. Filter by exact distance using the Haversine formula on the remaining candidates.

**PostGIS extension** for Postgres provides native geospatial indexing using R-Trees, which is more precise than geohashing and handles edge cases automatically:
```sql
SELECT name, ST_Distance(location, ST_MakePoint(77.5946, 12.9716)::geography) AS distance
FROM restaurants
WHERE ST_DWithin(location, ST_MakePoint(77.5946, 12.9716)::geography, 5000)  -- 5000 meters
ORDER BY distance
LIMIT 20;
```

At 3,300 QPS, this needs either aggressive caching (restaurants don't move; cache the results by geohash cell with a 5-minute TTL) or a read replica dedicated to search queries.

### 2. Real-Time Order Tracking — 20K Location Writes/Second

**Write path (delivery partner → server):**
The delivery partner's app sends GPS coordinates every 5 seconds. This data is ephemeral — you only care about the current location, not history.

```python
# Write to Redis (fast, ephemeral)
redis.geoadd("delivery_locations", longitude, latitude, f"partner:{partner_id}")
redis.set(f"partner:{partner_id}:location", json.dumps({
    "lat": latitude, "lng": longitude, "updated_at": now
}), ex=30)  # Expire after 30 seconds (stale = partner went offline)
```

**Read path (user tracking order):**
```python
# User's app polls every 3 seconds (or uses SSE)
location = redis.get(f"partner:{partner_id}:location")
return location
```

**Why Redis and not Postgres?**
20,000 writes/second of ephemeral data would thrash Postgres's WAL (write-ahead log) and disk I/O for data that's irrelevant after 30 seconds. Redis handles 100K+ writes/second in memory with zero disk overhead for this use case. The data has a natural TTL and doesn't need ACID guarantees.

**Scaling the read path:**
33,000 location reads/second per Redis instance is well within Redis's capacity (~100K ops/sec). For higher scale, use Redis Cluster or a pub/sub pattern where each user's tracking session subscribes to their delivery partner's location channel.

### 3. Inventory Contention — The Last Biryani Problem

**The scenario:** A restaurant's "Hyderabadi Biryani" has 3 remaining servings. In a 2-second window, 50 orders come in for this item. Only 3 should succeed.

**The naive approach fails:**
```python
stock = db.query("SELECT stock FROM menu_items WHERE id = 'biryani-123'")
if stock > 0:
    db.execute("UPDATE menu_items SET stock = stock - 1 WHERE id = 'biryani-123'")
    create_order()
```
This has a TOCTOU race condition. 50 processes read `stock = 3` simultaneously. All 50 pass the `if` check. All 50 decrement. Stock goes to -47. 50 orders are created for 3 servings.

**The fix: Atomic conditional update.**
```sql
UPDATE menu_items 
SET stock = stock - 1 
WHERE id = 'biryani-123' AND stock > 0
RETURNING stock;
```
This is atomic. Postgres executes it as a single operation. The `WHERE stock > 0` clause ensures the decrement only happens if stock is positive. If 50 concurrent queries hit this, exactly 3 succeed (returning stock 2, 1, 0) and the remaining 47 return 0 affected rows (the item is out of stock).

This is a **write contention** pattern — fundamentally different from the read-heavy patterns in RAG/search systems. Module 30's RAG pipeline is 95% reads. A marketplace's inventory system is the hot path for writes. The design instincts are different.

### 4. Order-Delivery Matching

When an order is confirmed, the system must find the best delivery partner. This is a real-time optimization problem:

**Simple algorithm (good enough for most):**
1. Query Redis for all available delivery partners within 3 km of the restaurant (using Redis's `GEORADIUS` command).
2. Rank by: (a) distance to restaurant, (b) current number of active deliveries, (c) historical acceptance rate.
3. Send the order offer to the top-ranked partner.
4. If they don't accept within 30 seconds, offer to the next.

**Why this is a queue problem:**
The order sits in a "matching queue" until a partner accepts. The matching service is the consumer. If order volume spikes (dinner rush) and available partners are scarce, the queue grows. The system must handle backpressure: show the user "Searching for delivery partner..." with an estimated wait time, and after 5 minutes, offer the option to pick up the order themselves.

### 5. Surge/Dynamic Pricing (Callback to Module 12 — Consistency)

When demand exceeds supply (rain, holidays), prices increase to incentivize more delivery partners to go online.

**The distributed state problem:** Pricing must be calculated based on real-time supply/demand data from multiple sources (order volume per zone, active partner count per zone, current weather). This data is eventually consistent — a partner going online in Zone A might not be reflected in the pricing service for 10-30 seconds.

**The design decision:** Accept eventual consistency for pricing. A 30-second stale price is acceptable (the user sees the price, agrees, and the price is locked at order time). This is different from inventory (where you need strong consistency to prevent overselling).

---

## The Access Pattern Contrast: Marketplace vs RAG

| Characteristic | RAG Pipeline (Module 30) | Marketplace |
|---------------|--------------------------|-------------|
| Read/Write ratio | 95% reads / 5% writes | 60% reads / 40% writes |
| Write contention | Rare (each user writes to their own tenant) | Intense (50 users competing for same item) |
| Latency budget | 3-5 seconds (LLM generation dominates) | <3 seconds (time-critical ordering) |
| Data freshness | Minutes acceptable (document indexing lag) | Seconds critical (stock, partner location) |
| Consistency model | Eventual (stale knowledge tolerable) | Strong for inventory, eventual for pricing/tracking |
| Cost bottleneck | LLM API costs ($0.01/query) | Logistics costs (delivery partner pay) |

This contrast matters because the design instincts you build in a RAG context (aggressive caching, eventual consistency is fine, connection pool is the bottleneck) don't directly transfer to marketplace design (write contention, strong consistency for inventory, real-time data freshness is the bottleneck).

---

## Mentor's Take — What Actually Matters Here

**What matters:** The Last Biryani Problem (write contention with atomic conditional updates), geospatial queries (geohashing/PostGIS), and the read/write pattern contrast with RAG systems. This case study teaches you a fundamentally different design mode than the read-heavy, AI-cost-dominated systems you've studied so far.

**The AI-era connection:** Food delivery marketplaces are actively adopting AI for: (1) demand prediction (pre-position delivery partners near expected order clusters), (2) route optimization (multi-drop deliveries where a partner picks up from 2 restaurants on one route), and (3) customer service bots (AI handling "where is my order?" queries). These AI features run alongside the core marketplace — they consume data from the real-time systems described above and must respect the same latency and consistency constraints.

**Brutally honest advice:** The biggest mistake engineers from an AI background make when working on marketplace systems is treating the inventory system like a read-heavy database. "I'll just cache the stock count" — NO. Cached stock counts cause overselling. The inventory decrement must hit the source-of-truth database with an atomic conditional update every single time. Caching is for search results, restaurant menus, and delivery partner profiles. Never cache mutable, contended state like stock levels.

---

## Check Your Understanding

1. A user at the border of two geohash cells searches for "restaurants within 5 km." A restaurant 500 meters away is in the adjacent geohash cell. If you only search the user's geohash cell, what happens? How do you fix this?

2. 100 users simultaneously try to order the last serving of a menu item. Using the atomic conditional update (`UPDATE ... WHERE stock > 0`), exactly how many orders succeed? What happens to the other 99 requests?

3. Your delivery tracking uses Redis with a 30-second TTL on location data. A delivery partner's phone loses signal for 2 minutes. What does the user see on the tracking map, and how should the UI handle this?

4. Explain why caching a restaurant's menu (including stock levels) in Redis with a 5-minute TTL is acceptable for menu display but dangerous for order placement.

5. Contrast the consistency requirements for these three marketplace subsystems: (a) restaurant menu search results, (b) item stock level during order placement, (c) delivery partner location during tracking. For each, state whether eventual or strong consistency is required and why.

---

### Answers

1. **Answer:** The restaurant is missed entirely — it's 500 meters away but in a different geohash cell, so the query doesn't find it. Fix: always search the user's geohash cell AND all 8 neighboring cells. This guarantees coverage of the area around cell boundaries. PostGIS's `ST_DWithin` handles this automatically by using proper geometric distance calculations instead of discrete cell boundaries.

2. **Answer:** Exactly 1 order succeeds (for the last serving). The `UPDATE ... SET stock = stock - 1 WHERE stock > 0` is serialized by Postgres's row-level locking. The first transaction to acquire the row lock decrements stock from 1 to 0 and commits. The remaining 99 transactions acquire the lock but find `stock = 0`, so the `WHERE stock > 0` clause matches zero rows. They return `0 affected rows`, and the application knows the item is out of stock. No overselling.

3. **Answer:** The location data in Redis expires after 30 seconds (TTL). The user's app polls for location and gets `null` (key expired). The delivery partner's dot on the map disappears or freezes at the last known position. The UI should handle this gracefully: show the last known location with a message "Updating delivery partner's location..." or "Partner's location temporarily unavailable." After 2 minutes, when the signal returns, the partner's app sends a new GPS update, Redis is updated, and the map resumes.

4. **Answer:** For menu display, showing a stock count that's 5 minutes stale is fine — the user sees "3 biryanis available" and might see "out of stock" when they try to order, which is a minor UX annoyance. For order placement, using the cached stock count (which might be stale) to determine if an order can proceed would cause overselling. The cache might say "3 available" when the real stock is 0. Order placement MUST hit the source-of-truth database with an atomic conditional update, bypassing the cache entirely.

5. **Answer:** (a) Restaurant search results: Eventual consistency is fine. If a new restaurant was added 5 minutes ago and doesn't appear in search yet, the user will see it on the next refresh. No harm done. (b) Stock level during order placement: Strong consistency required. Reading stale stock causes overselling — you accept orders for items that don't exist. Must use atomic conditional updates on the primary database. (c) Delivery partner location: Eventual consistency is acceptable. A location that's 5-10 seconds stale on the tracking map is imperceptible to the user — the dot moves smoothly enough. The delivery still arrives regardless of tracking precision.

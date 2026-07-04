
answers = {
    '01_why_system_design_exists.md': """
### Answers

1. **Answer:** The application will experience a connection pool/thread exhaustion and crash (or queue requests until timeouts occur). If max throughput is 20 requests / 10 seconds = 2 requests/sec, sending 20 req/sec means 18 requests pile up every second. The system is physically incapable of processing them, leading to an immediate bottleneck despite the hardware not being fully maxed out (if the 10s wait is I/O).
2. **Answer:** You must always try to "do less work" first. Caching the complex calculation is O(1) effort and eliminates the compute cost entirely. "Doing work in more places" (horizontal scaling) increases infrastructure cost, introduces distributed system complexity, and doesn't solve the fundamental inefficiency.
3. **Answer:** Premature optimization. At 1,000 users, an in-memory numpy array or a single Postgres table with pgvector on a tiny VPS can easily handle the load. Sharding a vector DB introduces massive operational overhead and latency for no practical benefit at that scale.
4. **Answer:** The p99 latency dictates the worst-case user experience. In an agent pipeline with 5 sequential tool calls, the probability of hitting a p99 latency spike compounds. The agent's overall latency will frequently hit that 12-second floor, making the UX feel consistently slow even if the "average" tool call is fast.
5. **Answer:** The system goes completely offline. The load balancer is a single point of failure (SPOF). To fix it, you need at least two load balancers (Active-Passive or Active-Active) with a virtual IP failover mechanism, or use a managed cloud load balancer.
""",

    '02_client_server_networking_fundamentals.md': """
### Answers

1. **Answer:** A DNS lookup involves UDP packets traversing multiple servers (Root, TLD, Authoritative). If the DNS resolver is slow or the connection drops, the DNS resolution fails or times out, preventing the TCP handshake from even beginning. This looks like an API failure but is entirely a DNS layer issue.
2. **Answer:** Use connection pooling or Keep-Alive. Instead of tearing down the TCP connection and TLS session after every 50ms request, the connection is kept open so subsequent requests only incur the 50ms payload transit time, eliminating the 150ms handshake overhead.
3. **Answer:** 30 requests/sec * 5 seconds = 150 concurrent connections. A standard web server might default to 100 worker threads. The 101st request will queue up and eventually time out because all 100 threads are blocked waiting for the LLM. The fix is to increase the thread pool/connection pool size or use asynchronous non-blocking I/O (like Python's asyncio).
4. **Answer:** The load balancer must terminate the TLS connection to read the HTTP headers and path. This is L7 load balancing. The LB does the decryption, reads the routing rules, and forwards the request over a new or pooled connection to the backend.
5. **Answer:** In a streaming response, the TCP connection must be held open for the entire duration of the token generation (e.g., 10 seconds). This drastically increases the number of concurrent open connections on the server compared to returning a single JSON payload in 200ms.
""",

    '03_scalability_vertical_vs_horizontal.md': """
### Answers

1. **Answer:** You will hit the physical limits of a single machine. While you can add more RAM or CPU up to a point, eventually there is no larger server available to buy, or the cost becomes exponentially unjustifiable compared to two smaller servers.
2. **Answer:** The user's session data is stored only in Server A's memory. If the load balancer routes their next request to Server B, Server B does not know they are logged in and treats them as a new/unauthenticated user.
3. **Answer:** Store the session state in a centralized, external datastore like Redis. All servers read from and write to Redis, making the application servers completely stateless.
4. **Answer:** Model weights are massive (e.g., 40GB for a 70B model). You cannot easily move them across the network for every request. Loading them into VRAM takes time. Therefore, the server becomes inherently stateful because it holds the heavy model in memory, making autoscaling slow and complex.
5. **Answer:** A local vector cache means Server A and Server B have different cached data. If User queries A, they get a cache hit. If they query B, they get a cache miss and trigger a slow embedding process. The solution is an external, shared vector database or Redis cache.
""",

    '04_back_of_envelope_estimation.md': """
### Answers

1. **Answer:** 1 million DAU * 10 messages = 10 million messages/day. 10M / 100,000 seconds/day = 100 requests per second (QPS) average. Peak QPS is typically 2x average, so ~200 Peak QPS.
2. **Answer:** 50 million images * 2MB = 100 million MB = 100 TB. You would need to store this in an object storage service like Amazon S3, not a relational database.
3. **Answer:** 2 million tokens / 1000 * $0.01 = $20 per day. Monthly = $20 * 30 = $600/month.
4. **Answer:** Throughput is 5 requests per second. With 50 concurrent requests, the wait time is 50 / 5 = 10 seconds before a request even begins processing. The user experiences a 12-second total latency (10s wait + 2s processing).
5. **Answer:** Estimations are crucial for identifying physical impossibilities (e.g., "we can't do this synchronously"), hardware requirements, and most importantly for AI, unit economics. If the LLM cost per user is higher than the subscription fee, the business model fails.
""",

    '05_reliability_vocabulary.md': """
### Answers

1. **Answer:** 99.9% availability allows for ~43 minutes of downtime per month. 99.99% allows for ~4.3 minutes. The engineering effort required to go from 43 minutes to 4 minutes is exponential, often requiring automated failovers, multi-region deployments, and zero-downtime migrations.
2. **Answer:** Service A (99%) * Service B (99%) * Service C (99%) = 0.99 * 0.99 * 0.99 = 0.97029. The overall availability is ~97%.
3. **Answer:** A standard p99 metric only measures latency (speed). An LLM can return a hallucination in 2 seconds. A Quality SLI measures the correctness or usefulness of the response (e.g., user thumb up/down, or an automated eval score) to ensure the system is actually working, not just responding quickly.
4. **Answer:** The error budget is 1%. It represents the allowable unreliability. Teams use it to balance feature velocity and stability. If the budget is exhausted, feature deployments are halted to focus on reliability fixes until the rolling window recovers.
5. **Answer:** Fallbacks (Graceful Degradation). If the primary OpenAI model is down, the system should automatically fall back to a cached response, a smaller local model, or Anthropic. The system remains partially available rather than crashing completely.
""",

    '06_load_balancing.md': """
### Answers

1. **Answer:** The problem is uneven distribution. Round robin sends the next request to the server that handled the 5-second `/chat` request, even though it's busy, because round robin doesn't track server state. The Least Connections algorithm fixes this by sending new requests to the servers handling the fast `/health` checks, naturally routing around the busy server.
2. **Answer:** Terminating TLS at the load balancer and sending unencrypted HTTP to backends is acceptable *only* if the network between the LB and backends is a trusted, private VPC (Virtual Private Cloud) that cannot be snooped. If the traffic traverses the public internet or an untrusted network, it is a severe security vulnerability.
3. **Answer:** (a) Without health checks, 60% of all user requests fail or hang indefinitely because the load balancer keeps routing them to the dead OpenAI pool. (b) With active health checks, the load balancer detects the failure within 30 seconds. It removes OpenAI from the routing pool and redistributes that 60% of traffic across Anthropic and the self-hosted model based on their relative weights.
4. **Answer:** Because RAG latencies are highly variable. A cache hit finishes in 200ms, freeing the connection. A full generation takes 8 seconds, holding the connection. Least-connections naturally sends traffic to servers that just had cache hits (because their connection count dropped), preventing servers doing heavy LLM generation from being overwhelmed.
5. **Answer:** The maximum availability is the availability of the load balancer itself. If the LB has 99.9% uptime, your system cannot exceed 99.9% uptime, even if you have 1,000 backend servers with 100% uptime. The fix is redundant load balancers (Active-Passive or Active-Active) sharing a Virtual IP.
""",

    '07_caching_deep_dive.md': """
### Answers

1. **Answer:** With cache-aside, the impact is serving stale data to all subsequent reads until the cache key's TTL expires. If it were a write-through cache, the application would have synchronously updated the cache at the exact same time it updated the database, ensuring the next read gets the fresh profile immediately.
2. **Answer:** An LRU cache only stores data that actually exists. The 10,000 random UUIDs are cache misses, so the app queries the DB, finds nothing, and caches nothing. The LRU logic is never invoked. The fix is to cache the "not found" state (e.g., store the UUID with a value of `null` and a short TTL) so the next request for that UUID hits the cache instead of the DB.
3. **Answer:** Because the "regeneration" cost is massive. A web app regenerating a 10ms JSON payload might cause a tiny CPU spike on the DB. A RAG system where 5,000 requests all try to regenerate a 30-second LLM report simultaneously will instantly exhaust API rate limits, database connection pools, and worker threads, causing a total system outage.
4. **Answer:** (a) Correctness increases significantly (fewer false positives). (b) Cache hit rate drops because the exact phrasing must match much more closely. (c) LLM API costs increase because fewer requests are served from the cache, requiring more full generations.
5. **Answer:** Immediate consequence: A Cache Stampede. 100% of read traffic immediately hits the database, likely overwhelming it. To prevent a total outage, you could use cache pre-warming (running scripts to populate hot keys before directing traffic back to the app) or implement probabilistic early expiration/jitter so not all keys miss at the same time upon restart.
""",

    '08_content_delivery_networks.md': """
### Answers

1. **Answer:** The user requests the file. DNS routes them to the Tokyo CDN edge node. The node checks its cache and gets a "Miss". The Tokyo node opens a connection to your Origin server (e.g., in Virginia), downloads `style.css`, serves it to the user in Tokyo, and simultaneously saves a copy to its local disk/memory with the specified TTL.
2. **Answer:** Manual invalidation takes time to propagate globally (leaving windows where users see stale data), is prone to human error (forgetting to click "invalidate"), and is hard to automate safely in CI/CD. URL versioning (e.g., `style_v2.css`) instantly guarantees a cache miss on the new file without touching CDN configuration.
3. **Answer:** `/api/v1/user/settings` is dynamic, private user data. If the CDN caches it, User B might receive the cached response generated for User A, causing a massive security/privacy breach. The `Cache-Control: private` or `Cache-Control: no-store` HTTP headers prevent the CDN from caching it.
4. **Answer:** The API server generates the audio clip and uploads the binary file to an S3 bucket. The API server then returns a JSON response containing a CDN URL pointing to that S3 object. The client's browser requests the CDN URL. The CDN fetches the audio from S3 once and serves it, completely bypassing the API server for the heavy byte transfer.
5. **Answer:** Edge-caching the JS bundle saves 150ms on a 300ms total load time (a 50% perceived speedup for the UI rendering). Edge-routing the API call saves 50ms of network transit on a 4,000ms LLM generation time (a 1.25% perceived speedup). The user literally cannot perceive a 50ms difference when waiting 4 seconds for an answer.
""",

    '09_databases_relational_fundamentals.md': """
### Answers

1. **Answer:** The query is performing a sequential table scan because there is no index on `last_login`. You fix this by adding a B-Tree index: `CREATE INDEX idx_last_login ON users(last_login)`. The tradeoff is that every future `INSERT` or `UPDATE` to the `users` table will be slightly slower because the database must also update the B-Tree data structure on disk.
2. **Answer:** The naive ORM approach executes 51 queries: 1 query to fetch the 50 users (`SELECT * FROM users LIMIT 50`), and then 50 separate queries (`SELECT * FROM messages WHERE user_id = ?`) as the code loops through each user.
3. **Answer:** Yes. If the database isolation level is low (e.g., Read Committed) or the connection is reading from an asynchronously updated Read Replica, the user's refresh might hit the database before the transaction containing their new message has fully committed or replicated. Eventual consistency causes the "missing" message anomaly.
4. **Answer:** 4 workers * 5 servers * 20 connections = 400 total connections. If Postgres is configured with `max_connections=100`, the database will reject the 101st connection attempt. The application will crash with "FATAL: sorry, too many clients already" errors during spikes.
5. **Answer:** Storing the raw BLOB in Postgres bloats the table size, rapidly fills up the RAM buffer pool (evicting useful indexes/data), and makes database backups massive and slow. Storing in S3 and saving the URL in Postgres keeps the database lean, fast, and optimized for structured querying, while offloading the heavy byte storage to cheap object storage.
""",

    '10_databases_scaling_relational.md': """
### Answers

1. **Answer:** The bug is caused by Replication Lag. The write went to the Leader, but the read was routed to a Follower that hadn't received the WAL update yet. Fix: Implement "read-after-write consistency" in the application layer—if a user makes a write, set a flag/cookie that forces all their reads to hit the Leader database for the next 5-10 seconds.
2. **Answer:** Because the data is sharded by `order_id`, the database does not know which shard holds orders for `User 123`. The application must send the query `SELECT * FROM orders WHERE user_id = 123` to *every single shard* (a Scatter-Gather query), wait for all of them to respond, and merge the results in memory. This is extremely slow and resource-intensive.
3. **Answer:** Range-based sharding by timestamp creates a massive "hotspot". All current writes (e.g., today's logs) will go to the exact same shard (the "current" shard). The other 99 shards holding historical data will sit completely idle for writes. You gain zero write scalability.
4. **Answer:** No. Read Replicas only scale read throughput. Because every Read Replica must process and replay every single write from the Leader's WAL, adding more replicas does not reduce the write load on the Leader; it actually slightly increases the network/CPU overhead on the Leader to stream the WAL to more followers.
5. **Answer:** The most logical Shard Key is `tenant_id` (or `customer_id`). Because all data (users, documents, settings) for a specific corporate customer will live on the same physical shard, you can perform fast, local relational JOINs and ACID transactions entirely within the scope of that customer without ever needing cross-shard network calls.
""",

    '11_nosql_databases.md': """
### Answers

1. **Answer:** You should use a Column-Family store (like Cassandra). A Document store is a poor choice because parsing, updating, and indexing massive JSON documents at 100,000 writes/sec will cause heavy CPU and memory overhead. Cassandra is optimized for ultra-fast, append-only writes to specific partition keys without the overhead of document parsing.
2. **Answer:** The database is forced to perform a Collection Scan. It must load every single JSON document from the disk into memory, parse the JSON, and check if the nested property exists. This is incredibly slow and CPU-intensive, destroying the performance of the database at scale.
3. **Answer:** A Key-Value store uses a Hash Map (O(1) exact match lookup). A Vector DB uses algorithms like HNSW (Hierarchical Navigable Small World graphs) to calculate the mathematical distance (cosine similarity) between high-dimensional arrays. A Hash Map can only say "Are these exactly the same string?"; it cannot say "Are these strings conceptually similar?"
4. **Answer:** The application will suffer from "Orphaned Data" (Data Inconsistency). Postgres knows about the document metadata, but Pinecone has no vector representation. When a user searches semantically, they will never find the document. The UX impact is silent failure—the user uploaded the file, but the AI behaves as if the file does not exist.
5. **Answer:** "Schema-less" just means the database engine doesn't enforce the schema. The schema enforcement moves into the application code. The Python/Node code must check if a field exists, handle type casting, and provide defaults if older documents are missing new fields.
""",

    '12_cap_theorem_consistency_models.md': """
### Answers

1. **Answer:** You must choose CP (Consistency and Partition Tolerance). If you choose AP, the East DB and West DB will both accept a booking for the single seat (Availability), resulting in a double-booking. For ticketing/financial transactions, it is better to fail the request (rejecting availability) than to violate consistency.
2. **Answer:** Eventual Consistency means a user might edit their profile and see the old profile on refresh. Read-Your-Own-Writes ensures the specific user sees their update instantly. You implement this by updating the user's local session cache or routing their specific reads to the primary database for a few seconds, while allowing the rest of the world to read from the eventually consistent replicas.
3. **Answer:** Under normal, healthy network conditions (the "E" in PACELC), a standard Postgres Read Replica setup trades Consistency for Latency (EL). It returns read queries instantly from the local replica (low Latency) but sacrifices Strong Consistency, as the replica might be slightly behind the primary.
4. **Answer:** Instead of querying the Vector DB immediately, the agent's context pipeline should query the primary Postgres DB for document metadata. If Postgres indicates the document was uploaded but the Vector DB has no chunks, the agent can explicitly tell the user: "I see you uploaded the document, but I am still processing it. Please give me a moment." This turns a hallucination into a graceful UI state.
5. **Answer:** "CA" implies the system is Consistent and Available, but lacks Partition Tolerance. In the real world, network partitions (P) are physical inevitabilities (routers fail, cables break). Because you cannot prevent partitions, you are always forced to choose between C and A when a partition occurs.
""",

    '13_replication_and_consistency.md': """
### Answers

1. **Answer:** If W=1 and N=5, your Read Quorum (R) must be 5 to satisfy W + R > N (1 + 5 > 5). Because you must read from all 5 nodes and wait for the slowest one to respond before returning the data, your read latency will increase significantly.
2. **Answer:** Those writes are permanently lost. Because the replication was Asynchronous, the Leader told the user "Success" before streaming the WAL to the Follower. When the Leader died, the Follower took over without those last 500ms of data. This is the definition of data loss in an eventually consistent setup.
3. **Answer:** If Server A's clock is 5 seconds fast, and Server B's clock is perfectly accurate, a user could update their profile on B, and 2 seconds later update it on A. Because A's clock is artificially in the "future", LWW might incorrectly decide A's write was the "last" one, overwriting B's legitimate, later update.
4. **Answer:** In a highly interactive app (like chat), users are writing constantly. If every write forces their reads to the Leader for 10 seconds, almost 100% of the read traffic will end up routed to the Leader. The Read Replicas will sit idle, and the Leader will be overwhelmed, completely defeating the purpose of having Read Replicas.
5. **Answer:** Postgres is the Leader. The message queue (Kafka/RabbitMQ) acts as the WAL stream mechanism. The worker processes (chunking/embedding scripts) act as the Follower replay mechanism, reading the stream and applying the changes to the Vector DB (the Follower database).
""",

    '14_message_queues_async_processing.md': """
### Answers

1. **Answer:** Synchronous: The user's browser hangs for 3 minutes. The API server holds an HTTP thread open the entire time. If 50 users upload files, the server runs out of threads and crashes. Asynchronous: The API saves the file to S3, drops a message on the Queue, and returns "Processing" in 50ms. The user's UI shows a progress bar. Worker servers process the CSV safely in the background without blocking the API.
2. **Answer:** The worker dies before ACKing the message. The Queue's timeout expires, making the message visible again. Another worker picks it up and calls the Stripe API *again*. If the Stripe API call wasn't built with an Idempotency Key, the user is charged $50 a second time. The business impact is furious customers and chargeback fees.
3. **Answer:** A DLQ catches messages that crash workers repeatedly (e.g., malformed JSON). Without a DLQ, the "Poison Pill" message goes back on the queue, is picked up by a worker, crashes the worker, goes back on the queue, and repeats infinitely. This loop will systematically crash your entire fleet of workers, halting all background processing.
4. **Answer:** The frontend must use a mechanism to ask the server for updates. Common patterns include Long Polling (frontend repeatedly asks `/status?job=123`), Server-Sent Events (SSE), or WebSockets (a persistent connection where the server pushes the "Done" message to the client).
5. **Answer:** When an agent runs synchronously for 45 seconds, the application code typically holds a database connection open for that entire duration. If your connection pool has 20 connections, 20 concurrent agent runs will exhaust the pool. Subsequent requests will timeout. A Queue solves this by freeing the API thread and DB connection instantly; the background worker only grabs a DB connection for the milliseconds it takes to save the final result.
""",

    '15_event_driven_architecture_streaming.md': """
### Answers

1. **Answer:** In a Message Queue (RabbitMQ), once a message is successfully processed and ACKed by the consumer, it is deleted from the queue forever. In an Event Stream (Kafka), the message is appended to a durable log on disk and remains there. The consumer just advances its "offset" (bookmark), allowing other consumers to read the exact same message later.
2. **Answer:** Because Kafka stores events durably on disk. When the Analytics Service reboots 2 days later, it simply looks at its last saved offset and starts reading the stream from exactly where it crashed. It processes the 2 days of backlog from the stream without the User Service ever knowing or participating.
3. **Answer:** CQRS separates the write path (Commands) from the read path (Queries). The write updates the Event Stream, and a background process updates the Read Database. Because this update happens asynchronously over the network, there is an unavoidable time delay (lag) between the write succeeding and the read database reflecting it.
4. **Answer:** Direct REST: Agent A must know the IP/URL of Agent B, must handle network timeouts if B is slow, and must retry if B fails. Tight coupling. Event: Agent A publishes `TaskCompleted` to Kafka and forgets about it. Agent B listens to Kafka at its own pace. Loose coupling. If Agent C is later added to also review tasks, Agent A's code doesn't change at all.
5. **Answer:** `TriggerEmbeddingGeneration` is a Command. It implies the upstream service is directing the downstream service, creating tight coupling. `DocumentChunked` is an Event (a fact about the past). Emitting facts allows downstream services to decide *for themselves* what to do with that fact, preserving true architectural decoupling.
""",

    '16_api_design_for_system_design.md': """
### Answers

1. **Answer:** Because the API is a public contract. If an existing mobile app expects `first_name` and you suddenly return `given_name`, the app's JSON parser will fail, and the app will crash for millions of users who haven't updated their app yet. Bumping to `/v2/` allows old apps to continue functioning on `/v1/` while new apps adopt the new schema.
2. **Answer:** The server intercepts the request, hashes the `Idempotency-Key`, and looks it up in a fast Key-Value store (Redis). It finds a match indicating that this key was already successfully processed. Instead of hitting the payment gateway again, the server simply retrieves the cached HTTP 200 response payload associated with that key and returns it to the client. The user is charged once.
3. **Answer:** A REST `GET /users/123` is cacheable because the URL acts as a unique, deterministic cache key. A CDN can intercept it and return the cached JSON. A GraphQL request is sent as a `POST` to a generic `/graphql` endpoint with the query embedded in the request body. CDNs generally do not cache POST requests because POST traditionally implies state mutation, and CDNs do not parse JSON bodies to determine cache keys.
4. **Answer:** LLM rate limiting is Two-Dimensional. A user might only make 1 API request per minute (passing the Request RPM limit), but that single request might contain a 100,000-token PDF (exhausting the Token TPM limit). If you only track requests, you will blow past your provider's token budget and cause outages. You must intercept the request, count the tokens, and decrement a Token Bucket before forwarding.
5. **Answer:** I would use gRPC/Protobuf. At 10,000 requests per second internally, the CPU overhead of serializing and deserializing JSON string keys (`"user_id": ...`) becomes a massive bottleneck. Protobuf uses a compact binary format that drastically reduces network payload size and requires virtually zero CPU parsing overhead compared to JSON.
""",

    '17_microservices_vs_monoliths.md': """
### Answers

1. **Answer:** It violates the principle of "Private Databases". Microservices must own their data exclusively. If the User team renames a column or changes the schema, the Order Service will instantly crash because its direct SQL queries will fail. The User team is no longer free to safely update their own database.
2. **Answer:** Availability compounds multiplicatively. 0.99 * 0.99 * 0.99 * 0.99 = ~0.96. The overall availability of the request path is 96%. This means the system as a whole is significantly less reliable than any individual microservice.
3. **Answer:** Conway's Law states that software architecture mimics communication structures. A small, tightly-knit team of 6 people working in the same room communicates constantly and naturally acts as a single cohesive unit. Therefore, they will (and should) produce a single, cohesive Monolithic architecture. Splitting into microservices would artificially hinder their workflow.
4. **Answer:** The split is justified by differing, conflicting physical resource needs. Crawling requires thousands of lightweight async threads but very little CPU. Embedding requires expensive GPU instances. Report generation requires heavy CPU but no GPUs. Keeping them in a monolith forces you to run the crawler on expensive GPU instances. Splitting them allows you to independently scale CPU servers, GPU servers, and cheap I/O instances.
5. **Answer:** In a Monolith, a crash produces a single, readable stack trace in one log file that tells you exactly which function failed. In Microservices, a crash in Service D might manifest as a generic "Timeout" error in Service A. You cannot piece the story together without Distributed Tracing (Trace IDs), which attaches a unique ID to the original request that is passed down through all network hops, allowing you to stitch the logs back together.
""",

    '18_service_communication_patterns.md': """
### Answers

1. **Answer:** Python's `requests` library will block indefinitely (hang forever) waiting for a response. At 50 requests per second, within a few minutes, thousands of threads/connections will be stuck open. Your server will run out of memory or connection pool capacity and crash. You must always specify a timeout (e.g., `timeout=5.0`).
2. **Answer:** A Retry Storm occurs when thousands of failing clients immediately retry at the exact same millisecond, essentially DDoSing the server. Exponential backoff spaces out the retries (1s, 2s, 4s), but without Jitter, all clients that failed at the exact same time will still retry at the exact same time (e.g., all hit the server 1s later, then 2s later). Jitter adds randomness so the retries are smeared across a time window, flattening the load spike.
3. **Answer:** The Circuit Breaker immediately intercepts the request and returns an error (or a Fallback response) to the client. It does *not* send the request to the downstream service. This protects the failing downstream service from being hammered with traffic while it is trying to recover.
4. **Answer:** A Bulkhead limits the specific resources (e.g., connection pool size or thread count) allocated to the Summarization dependency. If Summarization is slow, it will quickly exhaust its allocated compartment (e.g., 20 threads), causing subsequent Summarization requests to fail instantly. However, the remaining 80 threads in the web server remain perfectly healthy and available to serve Authentication requests.
5. **Answer:** If the endpoint is not Idempotent, a successful retry will execute the generation again. If the first call actually succeeded on the server but the response was dropped by the network (a timeout on the client side), the LLM generation happens twice. In an AI app, this means the user is billed twice for an expensive token generation, and the database might end up with duplicate stories.
""",

    '19_service_discovery_and_configuration.md': """
### Answers

1. **Answer:** No, they do not immediately stop. Client-Side discovery libraries typically cache the list of active IPs locally. If the Registry crashes, the clients will continue using the last known good IPs. They will only fail if those cached IPs also die or change before the Registry recovers.
2. **Answer:** An internal Load Balancer sits between the services; Service A makes a network hop to the LB, and the LB makes a network hop to Service B. A Service Mesh proxy (Sidecar) runs on the exact same machine/container as Service A. The call to the proxy happens over `localhost` (no network hop), and the proxy routes directly to Service B.
3. **Answer:** Standard DNS caches IP addresses for a set TTL (Time To Live). If containers are spinning up and dying every few minutes, a cached DNS record will quickly point to a dead IP. A Service Registry bypasses DNS caching issues by continuously maintaining and instantly returning the exact, real-time IPs of healthy containers via an API or a Sidecar proxy.
4. **Answer:** It lives in the proxy infrastructure layer (the Sidecar, like Envoy), not the application code. Service A's Python code makes a naive HTTP call without any try/catch retry logic. The Envoy proxy intercepts the call, executes the retries, monitors the failure rate, and trips the circuit breaker if necessary, returning a 503 to the Python app.
5. **Answer:** If the Registry uses Eventual Consistency (AP), one node in the registry might know that `User Service IP 10.0.0.5` just crashed, while another node hasn't received the update yet. If a client queries the outdated node, it will be given the IP of a dead service and its requests will fail. A Service Registry must be strictly consistent (CP) to ensure it only routes traffic to genuinely alive services.
"""
}



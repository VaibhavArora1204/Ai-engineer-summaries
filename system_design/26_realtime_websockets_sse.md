# 26 — Real-Time Systems: WebSockets, Long Polling, Server-Sent Events

## The Problem

Your AI chatbot generates a response word by word. The LLM produces tokens over 5-10 seconds. If you wait for the entire response before sending it to the user, they stare at a blank screen for 10 seconds. If you stream the tokens as they're generated, the user sees words appearing in real-time — the same UX as ChatGPT. The second experience is dramatically better.

But HTTP was designed for request-response. The client asks, the server answers, the connection closes. There's no mechanism in basic HTTP for the server to proactively push data to the client without the client asking.

This is the **push problem**: how does the server send data to the client at the server's initiative, continuously and in real-time?

---

## The Naive Approach and Why It Fails

**Short Polling: "The client asks every 100ms."**

```javascript
setInterval(async () => {
    const response = await fetch('/api/chat/status');
    if (response.data.new_tokens) {
        appendToUI(response.data.new_tokens);
    }
}, 100);
```

The client fires an HTTP request every 100 milliseconds. Most of these requests return nothing (no new tokens yet). At 10 requests/second per user, with 10,000 concurrent users, your server is handling 100,000 requests per second — and 90% of them are returning empty responses.

This is incredibly wasteful. It hammers your server, wastes bandwidth, and still has 100ms of potential delay between when a token is generated and when the client receives it.

---

## The Real Mechanism

### Long Polling

An improvement over short polling. The server holds the HTTP connection open until it actually has data to send.

**Mechanism:**
1. Client sends an HTTP request: `GET /api/chat/stream?last_token_id=42`
2. Server receives it. If there are new tokens after #42, it immediately responds with them.
3. If there are no new tokens yet, the server **holds the connection open** and waits.
4. When new tokens arrive, the server responds.
5. The client immediately sends another long-poll request.

**Pros:**
- No wasted requests — every response carries real data.
- Works with standard HTTP infrastructure (load balancers, proxies, CDNs).
- Simple to implement.

**Cons:**
- Each connection is still a full HTTP request/response cycle. Headers, TLS, etc. are repeated every time.
- The server holds open TCP connections for idle clients — this consumes server resources (threads/connections).
- If tokens arrive rapidly, the client is constantly cycling: receive → close → reconnect → receive. This churn adds overhead.

Long polling is a reasonable choice for infrequent updates (chat messages arriving every few seconds). It's a poor choice for high-frequency streaming (LLM tokens arriving every 50ms).

### Server-Sent Events (SSE)

A standard, built-in browser API for one-directional server-to-client streaming over a single, persistent HTTP connection.

**Mechanism:**
1. Client opens a connection: `const source = new EventSource('/api/chat/stream')`
2. Server responds with `Content-Type: text/event-stream` and keeps the connection open.
3. Server sends events as plain text in a specific format:
   ```
   data: {"token": "Hello"}
   
   data: {"token": " world"}
   
   data: {"token": "!"}
   
   data: [DONE]
   ```
4. Each `data:` line is an event. The browser's `EventSource` API automatically parses these and fires JavaScript events.
5. If the connection drops, `EventSource` automatically reconnects and can resume from a `Last-Event-ID`.

**Server-side (Python/FastAPI):**
```python
from fastapi.responses import StreamingResponse

@app.get("/api/chat/stream")
async def stream_chat(query: str):
    async def generate():
        async for token in llm.stream(query):
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")
```

**Client-side (JavaScript):**
```javascript
const source = new EventSource('/api/chat/stream?query=hello');
source.onmessage = (event) => {
    if (event.data === '[DONE]') {
        source.close();
    } else {
        const { token } = JSON.parse(event.data);
        appendToUI(token);
    }
};
```

**Pros:**
- Built-in browser API. No library needed.
- Automatic reconnection with resumption.
- Uses standard HTTP — works through all proxies, load balancers, CDNs.
- Lightweight — minimal overhead compared to WebSockets.
- Perfect for unidirectional streaming (server → client).

**Cons:**
- One-directional only. Client cannot send data back on the same connection.
- Text-based only (no binary data).
- Limited to ~6 concurrent connections per domain in HTTP/1.1 (not an issue with HTTP/2).

### WebSockets

A full-duplex, bidirectional, persistent connection between client and server.

**Mechanism:**
1. Client initiates an HTTP request with an `Upgrade: websocket` header.
2. Server responds with `101 Switching Protocols`.
3. The HTTP connection is "upgraded" to a WebSocket connection — a persistent, bidirectional TCP connection.
4. Both client and server can send messages at any time, in either direction.
5. Messages are framed (small header + payload) — much lower overhead than full HTTP requests.

```javascript
const ws = new WebSocket('wss://api.example.com/chat');

ws.onopen = () => {
    ws.send(JSON.stringify({ query: "Explain consensus" }));
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    appendToUI(data.token);
};
```

**Pros:**
- Bidirectional — client and server can send messages at any time.
- Low overhead per message (2-14 byte frame header vs 200+ byte HTTP headers).
- Supports binary data.
- Ideal for interactive apps (collaborative editing, multiplayer games, live trading).

**Cons:**
- **Connection-holding at scale:** Each WebSocket connection holds a TCP connection open for the entire session. 100,000 concurrent users = 100,000 open TCP connections on your server. This is fundamentally different scaling math than HTTP's "connect → respond → disconnect."
- **Stateful:** The connection has state (which user, which session). Load balancing must be sticky — if the user's WebSocket is on Server A, all messages must go to Server A. This complicates horizontal scaling.
- **Infrastructure complexity:** Many HTTP proxies, CDNs, and load balancers need special configuration for WebSocket support. Some older infrastructure doesn't support it at all.
- **No automatic reconnection:** Unlike SSE's `EventSource`, the WebSocket API has no built-in reconnection. You must implement it yourself.

### When to Use What

| Use Case | Best Choice | Why |
|----------|-------------|-----|
| LLM token streaming | **SSE** | Unidirectional (server → client), simple, standard HTTP |
| Chat messages (send + receive) | **WebSocket** | Bidirectional needed (user sends messages AND receives them) |
| Notification feed (read-only) | **SSE** | Server pushes updates, client just listens |
| Collaborative document editing | **WebSocket** | Both parties sending edits simultaneously |
| Live stock prices | **SSE** or WebSocket | SSE if read-only; WebSocket if user places trades |
| Infrequent status updates | **Long Polling** | Simplest to implement, works everywhere |

---

## Concrete Example From a Real System

**How ChatGPT Streams Tokens:**

OpenAI's `/v1/chat/completions` API with `stream: true` uses **SSE**.

The client sends a POST request. The server responds with `Content-Type: text/event-stream` and streams chunks:

```
data: {"choices": [{"delta": {"content": "Hello"}}]}

data: {"choices": [{"delta": {"content": " there"}}]}

data: {"choices": [{"delta": {"content": "!"}}]}

data: [DONE]
```

The ChatGPT frontend uses `EventSource` (or a fetch-based streaming reader) to consume these chunks and render them as they arrive.

**Why SSE and not WebSocket?** Because the communication is fundamentally one-directional for each request. The user sends a message (one HTTP POST), and the server streams back the response. There's no simultaneous bidirectional communication during the generation. SSE is simpler, cheaper to operate, and works through standard HTTP infrastructure without special proxy configuration.

**The operational math difference:**
- With SSE: each streaming response holds a connection for ~5-10 seconds (the generation duration), then closes. At 1,000 concurrent generations, you have 1,000 open connections.
- With WebSocket: each user session holds a connection open for the entire browsing session (~30 minutes average). At 100,000 active users, you have 100,000 open connections, even if only 1,000 are actively generating.

SSE scales to the number of concurrent *generations*. WebSocket scales to the number of concurrent *users*. The difference is 100x.

---

## The Tradeoffs

| Mechanism | Direction | Connection Lifecycle | Complexity | Scaling Challenge |
|-----------|-----------|---------------------|------------|-------------------|
| Short Polling | Client → Server | New connection per poll | Very Low | Wasted requests at scale |
| Long Polling | Client → Server (held) | Held until data available | Low | Connection churn, timeout tuning |
| SSE | Server → Client | Persistent until stream ends | Low-Medium | Connection count during streams |
| WebSocket | Bidirectional | Persistent for entire session | High | Connection count = active users |

---

## How This Connects to Other Modules

- **Module 06** (Load Balancing): WebSocket connections require sticky sessions or session-aware load balancing. SSE works with standard round-robin because each stream is a self-contained HTTP response.
- **Module 07** (Caching): Streaming responses are not cacheable by CDNs. The CDN can cache the initial page load but not the live stream.
- **Module 14** (Message Queues): In a multi-server setup, when the LLM finishes generating on Server B but the user's WebSocket is connected to Server A, you need a message bus (Redis Pub/Sub, Kafka) to route the tokens from Server B to Server A. This is the "fan-out to the correct connection" problem.
- **Module 18** (Service Communication): What happens when the SSE connection drops mid-stream? The client needs retry logic. SSE has built-in `Last-Event-ID` for resumption; WebSocket doesn't.

---

## Mentor's Take — What Actually Matters Here

**What matters vs textbook noise:** For your immediate work (AI applications), SSE is the tool you'll use most. It's simpler than WebSockets, it works through standard HTTP infrastructure, and it matches the actual communication pattern of LLM streaming perfectly: the server sends, the client receives.

WebSockets matter when you build genuinely interactive features — collaborative editing, real-time multiplayer, bidirectional data sync. For a chatbot? SSE.

**The AI-era connection:** Streaming LLM responses via SSE is the most visible application of real-time systems in AI. But there's a subtler scaling issue: **connection holding.**

A traditional web API completes a request in 50-200ms. Connection pools, load balancers, and reverse proxies are tuned for this assumption. An LLM streaming response holds a connection open for 5-30 seconds. This means:
- Nginx's `keepalive_timeout` (default 60s) needs adjustment.
- Your load balancer's connection timeout must exceed the longest possible generation.
- Your cloud provider's request timeout (e.g., AWS ALB's 60-second default) might kill long generations mid-stream.
- Connection pool sizes need to account for 100x longer hold times.

When teams first deploy streaming LLM responses behind a standard Nginx + load balancer stack, the #1 bug report is "the response gets cut off after 60 seconds." That's Nginx's `proxy_read_timeout` killing the connection. It's a 10-second config fix, but it bites everyone exactly once.

**Brutally honest advice:** A lot of AI products reach for WebSockets when SSE would be simpler and cheaper. I've seen teams spend 2 weeks building WebSocket infrastructure with session management, heartbeats, reconnection logic, and sticky load balancing — for a chatbot that needs exactly one feature: stream tokens from server to client. SSE does that in 10 lines of code with automatic reconnection built in. Don't reach for the complex tool when the simple one fits perfectly. The time you save on infrastructure complexity, spend on making the product better.

---

## Check Your Understanding

1. Your LLM streaming endpoint uses SSE. A user's internet briefly drops for 2 seconds mid-generation (tokens 15-30 of 100 are lost). The SSE connection automatically reconnects. How does the `Last-Event-ID` mechanism allow the client to resume from where it left off? What must the server implement to support this?

2. You have 50,000 concurrent users connected via WebSockets. Each connection holds a TCP socket open. Your server has a default file descriptor limit of 65,535. What happens when the 65,536th user tries to connect? How do you fix this?

3. Explain the operational difference between "1,000 concurrent SSE streams" and "50,000 persistent WebSocket connections" in terms of server resource consumption, even though both are "open connections."

4. Your architecture has 4 API servers behind a load balancer. User Alice's WebSocket is connected to Server 2. The LLM generates her response on Server 3 (where the GPU is). How do the generated tokens get from Server 3 to Server 2 to reach Alice? What infrastructure component is needed?

5. Why is a standard CDN (Module 08) unable to cache or accelerate an SSE stream, even though SSE uses standard HTTP?

---

### Answers

1. **Answer:** Each SSE event can include an `id:` field (e.g., `id: 42`). When the connection drops, the browser stores the last received ID. Upon automatic reconnection, `EventSource` sends a `Last-Event-ID: 42` header. The server reads this header and resumes sending events from ID 43 onward. The server must maintain a buffer of recent events (or be able to replay from a given ID) to support this. Without server-side event buffering, resumption is impossible and the client misses the tokens.

2. **Answer:** The operating system refuses the new TCP connection with a "Too many open files" error. The user gets a connection failure. Fix: increase the file descriptor limit (`ulimit -n 100000` on Linux), tune kernel parameters (`net.core.somaxconn`, `net.ipv4.tcp_max_syn_backlog`), and horizontally scale by adding more servers with sticky session routing so connections are distributed across machines.

3. **Answer:** 1,000 SSE streams are short-lived (5-30 seconds each, closing when the LLM generation finishes). Server resources (TCP sockets, memory) are held briefly and released. Over a minute, the 1,000 slots are recycled across many users. 50,000 WebSocket connections are persistent for the entire user session (potentially 30+ minutes). All 50,000 TCP sockets, their kernel buffers, and the associated application-level session state are held simultaneously. The steady-state resource consumption is vastly higher, even if most connections are idle.

4. **Answer:** A message broker (Redis Pub/Sub, Kafka, or an internal message bus) is needed. Server 3 publishes generated tokens to a channel identified by Alice's session/request ID. Server 2 subscribes to that channel. When tokens arrive on Server 2 via the message broker, Server 2 pushes them down Alice's WebSocket connection. Without this pub/sub infrastructure, Server 2 has no way to know that Server 3 generated tokens for its connected user.

5. **Answer:** A CDN caches complete HTTP responses. An SSE stream is an open-ended, chunked response that doesn't terminate until the server closes it (or the client disconnects). The CDN can't cache it because: (1) the response has no defined end — it might stream for 5 seconds or 5 minutes; (2) the content is dynamic and unique per request; (3) CDNs need to return the full response from cache, but the response is still being generated. CDNs can accelerate the initial TCP/TLS handshake by edge-terminating the connection, but the actual SSE data must flow from the origin server to the user in real time.

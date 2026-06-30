# Streaming Generation — How It Works and Why It Matters

## The Problem It Solves

**Bottleneck: User-perceived latency, not actual compute time.**

Without streaming, the user submits a query and stares at a blank screen until the entire response is generated. For a 500-token response at 50 tokens/sec, that's 10 seconds of nothing, then a wall of text. With streaming, the first token appears in ~200ms and text flows word-by-word. The total generation time is identical, but perceived latency drops from 10 seconds to 200ms.

---

## How It Works

### The Mechanism

LLMs generate tokens one at a time. Streaming sends each token to the client as soon as it's generated, rather than buffering the entire response.

```
Without streaming:
  Client → Server: "Explain quantum computing"
  Server: generates 500 tokens (10 seconds)
  Server → Client: [full 500-token response]
  User experience: 10 seconds of loading → wall of text

With streaming:
  Client → Server: "Explain quantum computing"  (stream=true)
  Server → Client: "Quantum"          (t=200ms, time-to-first-token)
  Server → Client: " computing"       (t=240ms)
  Server → Client: " is"              (t=280ms)
  ...
  Server → Client: " [DONE]"          (t=10s)
  User experience: text appears immediately, flows naturally
```

### Server-Sent Events (SSE)

The standard transport for LLM streaming. Unidirectional server→client over HTTP:

```
HTTP Response:
  Content-Type: text/event-stream
  Transfer-Encoding: chunked

  data: {"choices": [{"delta": {"content": "Quantum"}}]}
  
  data: {"choices": [{"delta": {"content": " computing"}}]}
  
  data: {"choices": [{"delta": {"content": " is"}}]}
  
  data: [DONE]
```

**Why SSE over WebSockets:** SSE is simpler (one-way, HTTP-native, auto-reconnect). WebSockets are bidirectional but overkill for streaming generation. SSE works through proxies, load balancers, and CDNs without modification.

### Key Metrics

```
TTFT (Time-to-First-Token):
  Time from request submission to first token received by client.
  = prefill time + first decode step + network latency
  Target: <500ms for interactive, <2s for batch

ITL (Inter-Token Latency):
  Time between consecutive tokens.
  = single decode step time
  Target: <50ms (feels like real-time typing)

Total Generation Time:
  = TTFT + (num_tokens - 1) × ITL
  User doesn't directly perceive this — they see TTFT + flowing text
```

### Chunked Prefill

A related optimization that interacts with streaming and continuous batching:

```
Problem: Long prompts (10K+ tokens) create a TTFT spike.
  Prefill for 10K tokens takes 2-5 seconds.
  During this time, the GPU is doing prefill and NOT generating
  tokens for any other request. Other requests stall.

Chunked prefill:
  Break the 10K prompt into chunks (e.g., 512 tokens each)
  After processing each chunk, yield the GPU for one decode iteration
  Other requests can generate tokens between chunks

Result:
  - Long-prompt TTFT is slightly longer (chunking overhead)
  - Other requests' ITL is not disrupted
  - System-wide P99 latency improves dramatically
```

---

## The Numbers

| Metric | Without Streaming | With Streaming | Impact |
|--------|-------------------|----------------|--------|
| Perceived latency (500 tokens) | 10s | 200ms (TTFT) | 50× perceived improvement |
| User engagement | Lower (users abandon after 3-5s) | Higher | Critical for UX |
| Total computation | Same | Same | Zero cost |
| Network overhead | Single response | SSE overhead (~5-10% more bytes) | Negligible |

**Chunked prefill impact (vLLM benchmarks):**
```
Without chunked prefill:
  System with 1 long request (50K tokens) + 100 short requests
  Short request P99 ITL: 800ms (blocked by long prefill)

With chunked prefill:
  Same workload
  Short request P99 ITL: 45ms (chunked prefill yields between chunks)
```

---

## Where It Lives in the Stack

**Layer: API server + client integration.**

Streaming modifies two things:
1. **Server:** The API returns a streaming HTTP response (SSE) instead of a buffered JSON response.
2. **Client:** The frontend reads the SSE stream and renders tokens incrementally.

```
Server-side (vLLM, TGI, TensorRT-LLM):
  Model generates token → Scheduler returns token → 
  API server sends SSE event → Client receives and renders

Client-side:
  const response = await fetch('/v1/chat/completions', {
    method: 'POST',
    body: JSON.stringify({...request, stream: true}),
  });
  
  const reader = response.body.getReader();
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    const text = new TextDecoder().decode(value);
    // Parse SSE data lines, extract token, append to UI
  }
```

---

## Tradeoffs

| You gain | You give up |
|----------|-------------|
| Dramatically lower perceived latency | Slightly more complex client code |
| Better user engagement | Cannot validate/filter full response before showing |
| Progressive rendering | SSE connection must stay open (proxy timeout risk) |
| | Structured output (JSON) is harder to stream (partial JSON is invalid) |

**The structured output tension:** If your API returns JSON, streaming sends partial JSON that's invalid until complete. Solutions:
- Stream JSON field by field (e.g., stream the `content` field while structure is fixed)
- Buffer structured output, stream only text content
- Use libraries like `partial-json-parser` on the client

**Proxy and load balancer considerations:**
- Many reverse proxies (nginx, AWS ALB) have default timeouts (60s). Long generations may be cut off.
- Configure: `proxy_read_timeout 300s;` in nginx
- HTTP/2 multiplexing: multiple SSE streams over one connection (reduces connection overhead)

---

## What It Combines With

**Stacks well with:**
- **KV Caching (01):** Each streamed token uses the cached K/V. No interaction.
- **Continuous Batching (17):** Streaming is natural with continuous batching — each completed token is immediately streamable.
- **Speculative Decoding (02):** Multiple tokens may be accepted at once. Stream the batch of accepted tokens together.
- **FlashAttention (03):** No interaction — FA operates at the compute level, streaming at the API level.
- **Chunked Prefill:** Directly enables better streaming UX by preventing TTFT spikes from long prompts.

**Conflicts with:**
- Nothing significant. Streaming is a presentation-layer optimization. It's compatible with everything.

---

## Implementation Today

| Framework | Streaming | Chunked Prefill |
|-----------|-----------|-----------------|
| **vLLM** | ✅ (SSE, OpenAI-compatible) | ✅ (`--enable-chunked-prefill`) |
| **TGI** | ✅ (SSE) | ✅ |
| **TensorRT-LLM** | ✅ (SSE) | ✅ |
| **SGLang** | ✅ (SSE) | ✅ |
| **llama.cpp** | ✅ (SSE via `llama-server`) | ❌ |
| **OpenAI API** | ✅ (`stream: true`) | N/A (managed) |
| **Anthropic API** | ✅ (`stream: true`) | N/A (managed) |

**OpenAI-compatible streaming (vLLM):**
```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="na")

stream = client.chat.completions.create(
    model="meta-llama/Llama-3-70B-Instruct",
    messages=[{"role": "user", "content": "Explain KV caching"}],
    stream=True
)

for chunk in stream:
    token = chunk.choices[0].delta.content
    if token:
        print(token, end="", flush=True)
```

---

## Primary Sources

- **SSE specification:** https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events
- **vLLM streaming docs:** https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html
- **vLLM chunked prefill:** https://docs.vllm.ai/en/latest/models/performance.html
- **OpenAI streaming guide:** https://platform.openai.com/docs/api-reference/streaming

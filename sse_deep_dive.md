# SSE — Complete Ground-Up Explanation
### + Your Excel Sheet as a Golden Eval Harness

---

## What Problem SSE Solves

Right now your pipeline works like this:

```
Client sends request
→ Server: embed → qdrant → rerank → LLM generates 300 tokens → done
→ Server sends entire response at once
→ Client renders it
```

The user stares at a blank screen for 4–8 seconds (embed + qdrant + rerank + generation time), then the whole answer appears instantly.

SSE changes this to:

```
Client sends request
→ Server: embed → qdrant → rerank → starts LLM generation
→ Server sends each token to client AS IT IS GENERATED
→ Client renders tokens one by one — answer appears to "type itself"
```

Same total time. Better perceived experience. The user sees progress immediately.

---

## What SSE Is at the HTTP Level

Normal HTTP response:
```
HTTP/1.1 200 OK
Content-Type: application/json
Content-Length: 342

{"results": [...]}     ← entire body sent once, connection closes
```

SSE response:
```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

data: {"token": "The"}\n\n
data: {"token": " error"}\n\n
data: {"token": " code"}\n\n
data: {"token": " E-04"}\n\n
data: [DONE]\n\n        ← explicit terminal event, then connection closes
```

The connection stays open. The server writes chunks to it over time. The client's browser (or fetch reader) receives each chunk as it arrives without waiting for the connection to close.

**The `\n\n` is mandatory.** SSE spec says each event ends with a blank line. One `\n` = continuation of current event. Two `\n\n` = event complete, deliver it to the listener. If you forget the double newline, the client buffers forever and delivers nothing.

---

## Three HTTP Models — Know the Difference

| Model | How it works | Use case |
|---|---|---|
| Normal JSON | Full body sent once, connection closes | Your current retrieval endpoint |
| SSE (Server-Sent Events) | Server pushes events over open connection, one direction | Streaming LLM tokens |
| WebSocket | Bidirectional persistent connection | Real-time chat, collaborative editing |

SSE is one-directional: server → client only. The client cannot send messages after the initial request. That's fine for LLM streaming — the client sends one query, server streams one answer.

---

## Exact Wire Format — No Ambiguity

Each SSE event looks like:
```
data: <your payload here>\n\n
```

Optional fields:
```
event: token\n          ← named event type (optional)
data: {"token": "hello"}\n\n
```

If you use named events, the client listens for them specifically:
```javascript
evtSource.addEventListener('token', (e) => { ... });
evtSource.addEventListener('done', (e) => { ... });
evtSource.addEventListener('error', (e) => { ... });
```

If you don't use named events, everything comes through `evtSource.onmessage`.

**What OpenAI does (and what most LLM APIs copy):**
- Every token: `data: {"choices":[{"delta":{"content":"hello"}}]}\n\n`
- End of stream: `data: [DONE]\n\n`
- The literal string `[DONE]` is not JSON — the client checks for it explicitly before trying to parse.

---

## Express SSE — What You Actually Write

```javascript
router.post('/generate', async (req, res) => {
  const { query } = req.body;

  // ── ALL pre-generation work happens BEFORE opening the stream ──

  // 1. Retrieve + rerank (your existing pipeline)
  let results;
  try {
    results = await retrieve(query);
  } catch (err) {
    // Normal JSON error — headers NOT sent yet, this is fine
    return res.status(500).json({ error: `Retrieval failed: ${err.message}` });
  }

  // 2. Relevance gate — BEFORE headers are sent
  if (results[0].score < SCORE_THRESHOLD) {
    return res.status(200).json({ error: 'No relevant content found' });
  }

  // ── Stream opens HERE — from this point, no more res.status() or res.json() ──
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders(); // sends the headers immediately, opens the pipe

  // 3. Stream generation tokens
  try {
    const stream = await llmClient.streamGenerateContent(prompt);
    for await (const chunk of stream) {
      const token = chunk.text();
      res.write(`data: ${JSON.stringify({ token })}\n\n`);
    }
    // Terminal event — clean end
    res.write('data: [DONE]\n\n');
    res.end();
  } catch (err) {
    // Stream is already open — can't send HTTP 500
    // Must send error as an SSE event, then close
    res.write(`data: ${JSON.stringify({ error: err.message, partial: true })}\n\n`);
    res.end();
  }
});
```

---

## The Critical Architectural Rule

**Once `res.setHeader` + `res.flushHeaders()` runs, you are committed.**

After that point:
- `res.status(500)` — throws "Cannot set headers after they are sent"
- `res.json({...})` — same, crashes
- A try/catch that tries to return a JSON error — too late

This is why the gate (score threshold check) and ALL validation must happen before the stream opens. The stream is a one-way door.

**The failure mode if you get this wrong:**
- LLM call fails mid-stream
- Server crashes with "Cannot set headers after they are sent"
- Client receives a truncated stream with no terminal event
- Client's stream reader hangs waiting for `[DONE]` that never comes
- From the user's perspective: answer cuts off mid-sentence, spinner never stops

---

## Client Side — How to Read SSE

**Native browser (EventSource API):**
```javascript
// EventSource only supports GET — not useful for POST with a query body
const es = new EventSource('/api/generate?query=...');
es.onmessage = (e) => {
  if (e.data === '[DONE]') { es.close(); return; }
  const { token } = JSON.parse(e.data);
  appendToUI(token);
};
es.onerror = (e) => { es.close(); };
```

**Limitation:** Native EventSource is GET-only. For POST (which you need to send query in body), you need `fetch` with a readable stream:

```javascript
const response = await fetch('/api/generate', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ query }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  const text = decoder.decode(value);
  // text may contain multiple events — split on \n\n
  const events = text.split('\n\n').filter(Boolean);
  for (const event of events) {
    const data = event.replace(/^data: /, '');
    if (data === '[DONE]') break;
    const { token } = JSON.parse(data);
    appendToUI(token);
  }
}
```

---

## Your Current Setup vs SSE

| What you have now | What SSE changes |
|---|---|
| Retrieval route returns full result | Generation route returns a stream |
| Client gets one JSON response | Client reads events one at a time |
| Error = `res.status(500)` anywhere | Error before stream = JSON error; error during stream = SSE error event |
| Response time = full pipeline time | User sees first token after embed+qdrant+rerank (seconds faster perceived) |

**Your token-by-token test file** is essentially simulating what SSE delivers to a client — each token arriving independently. SSE just exposes that to the browser instead of your local console.

---

## Your Excel Sheet → Golden Eval Harness

Your sheet has: **Query | Observation | Doc Reference | Expected Doc | Issue Type**

That is 80% of a proper golden-set eval. Here's what maps to what:

| Your column | Eval concept | What to add |
|---|---|---|
| Query | Test input | ✅ already have it |
| Expected Doc | Golden chunk source | ✅ Add golden chunk ID (not just filename) |
| Observation | Manual pass/fail | Semi-automate: did top-K include golden chunk? |
| Doc Reference | Retrieved doc | Compare to Expected Doc → Recall@K |
| Issue Type | Failure taxonomy | Keep — this tells you WHERE the pipeline broke |

**What to add to make it computable:**
1. Add a column: `Expected Chunk ID` (the specific chunk ID, not just filename — multiple chunks per file)
2. Write a script that: for each query → runs retrieval → checks if Expected Chunk ID appears in top-K → logs rank if found, `MISS` if not
3. Output: Recall@30 (did you find it at all?), rank position (how deep did you have to go?), MRR

The Issue Type column is gold — if you've already categorized failures as e.g. "wrong doc returned" vs "right doc but wrong chunk" vs "query too vague" — you already know where the pipeline is breaking. That categorization tells you whether the fix is retrieval (add BM25), chunking (different overlap), or generation.

---

## Decision: Do You Need SSE Right Now?

**No — not until you have generation.**

Your current endpoint returns retrieval results (no LLM). There's nothing to stream. SSE becomes relevant the moment you add a generation call.

**When you do add generation:**
Design the route with the gate-before-stream rule from day 1. The order:
1. Retrieve → rerank (your existing code, returns synchronously)
2. Score gate check → return JSON error if below threshold
3. Open SSE stream
4. Stream LLM tokens
5. Emit `[DONE]`

If you build generation without SSE first (full JSON response), retrofitting SSE later requires restructuring error handling — it's not a one-line change. So design the error-handling boundary correctly even if you implement non-streaming first.

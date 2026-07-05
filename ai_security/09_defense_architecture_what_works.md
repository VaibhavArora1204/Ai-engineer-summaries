# 09 — Defense Architecture: What Actually Works

Purely practical. No threat descriptions. What to build, in what order, at what cost, with what gaps.

---

## Layer 0: Design Decisions Before Writing Code

Cost: $0. Time: 1 day of design review. ROI: highest of any layer.

These decisions cannot be retrofitted cheaply. Get them right upfront.

### Least-Privilege Context
Put only what the task requires in the LLM's context. Every piece of data in context is exfiltrable. API keys, database credentials, internal URLs — if they're in the prompt, they can be extracted.

```
Audit your system prompts RIGHT NOW:
  - Are there API keys in the prompt? Remove them. Use env vars.
  - Are there internal URLs? Remove them. Use tool abstractions.
  - Does the model see all user data or only what's needed for this query?
  - Does RAG retrieve from all documents or scoped by user permissions?
  
  The less data in context, the less there is to exfiltrate.
  This is free and prevents the most common exfiltration scenarios.
```

### Least-Privilege Tools
Every tool permission is a capability you hand to attackers. Read-only where write isn't needed. Scoped parameters, not free strings. No shell access unless that IS the product.

### Assume-Breach Design
If injection succeeds (and it will), what's the maximum damage? Design to minimize that ceiling.

```
Ask for each tool:
  "If an attacker controls what this tool does, what's the worst outcome?"
  
  send_email: attacker exfiltrates data to arbitrary recipients.
  delete_file: attacker destroys production data.
  http_request: attacker makes arbitrary outbound requests (SSRF + exfil).
  read_file (scoped): attacker reads files in the allowed directory.
  
  The last one is acceptable. The first three need confirmation gates.
```

### Human-in-the-Loop for Irreversible Actions
Non-negotiable from day one. The confirmation happens in your application UI, not in the LLM conversation. The LLM can be injected into approving its own actions.

### Separate Trust Levels in Prompt Structure
System instructions vs retrieved content vs user input — always explicit, always marked with trust level tags. Not a hard boundary, but measurably reduces injection success rate.

---

## Layer 1: Input Pipeline

Cost: 2-3 days integration. Ongoing: classifier subscription.

```
Components:

1. Input classifier (Lakera Guard or Prompt Shields)
   - Catches known injection patterns
   - <20-50ms latency
   - Integration: single API call before your main LLM call
   
   What it catches: ~80-90% of known injection patterns
   What it misses: novel payloads, indirect injection (those come 
   via retrieval, not user input)

2. Content trust scoring
   - Documents from internal authored sources: HIGH trust
   - User uploads: MEDIUM trust
   - Web-crawled content: LOW trust
   - Each trust level gets different framing in the prompt

3. PII detection on user input
   - Scan for SSN, credit cards, medical IDs before they enter context
   - If detected: warn user, redact, or block depending on policy
   - Tools: Microsoft Presidio (open source), AWS Comprehend

4. Rate limiting
   - Requests per user per minute: hard cap
   - Injection attempt pattern detection: if input classifier flags 
     5+ attempts in 10 minutes → automatic rate limit to 1/min
   - Alert security team on repeated flagged attempts
```

---

## Layer 2: Prompt Construction Standards

Cost: 1 day to define. 1-2 sprints to retrofit.

```xml
<!-- Every prompt in your system follows this structure -->
<system_instructions trust="SYSTEM">
  [Your instructions. Never modified by external content.
   No tenant-specific data. No credentials. No internal URLs.]
</system_instructions>

<retrieved_context trust="UNTRUSTED">
  [Retrieved documents. Explicitly marked as DATA, not instructions.
   Source and trust level annotated per chunk.]
  <chunk source="internal_kb" trust="HIGH">...</chunk>
  <chunk source="user_upload" trust="LOW">...</chunk>
</retrieved_context>

<user_query trust="USER">
  [User's actual message. Last in the prompt, never before system instructions.]
</user_query>
```

**Team standard:** every prompt template is reviewed for this structure before deployment. No exceptions. This is a code review checklist item.

**Prompt caching consideration:** the cached prefix (system_instructions) must contain ZERO tenant-specific data, ZERO dynamic content, ZERO timestamps. Dynamic content goes in the non-cached section after the cached prefix.

---

## Layer 3: Model Call Controls

Cost: 1 day.

```python
# Every LLM call, without exception:
response = llm.call(
    messages=messages,
    max_tokens=2000,        # Hard cap, not suggestion
    timeout_seconds=30,     # Kill runaway calls
    temperature=0.3,        # Lower = more predictable = fewer surprises
)

# For agent loops:
MAX_AGENT_STEPS = 15       # Hard cap on loop iterations
MAX_COST_PER_QUERY = 0.50  # Dollar limit per user query
step_count = 0

while not done and step_count < MAX_AGENT_STEPS:
    if total_cost > MAX_COST_PER_QUERY:
        return "Query budget exceeded. Please simplify your request."
    step_count += 1
    # ... agent step ...
```

Model selection by risk level: higher-stakes tasks use models with stronger documented alignment. Don't use the cheapest model for financial or medical queries.

---

## Layer 4: Output Pipeline

Cost: 2-4 days.

```python
def validate_output(response, system_prompt, user_query):
    alerts = []
    
    # 1. System prompt leakage (fuzzy match)
    if fuzzy_similarity(response, system_prompt) > 0.7:
        alerts.append("SYSTEM_PROMPT_LEAK")
    
    # 2. Off-task detection
    if semantic_similarity(response, user_query) < 0.3:
        alerts.append("OFF_TASK_RESPONSE")
    
    # 3. PII in output
    pii = presidio.analyze(response)
    if pii:
        alerts.append(f"PII_IN_OUTPUT: {[e.entity_type for e in pii]}")
    
    # 4. Suspicious URLs
    for url in extract_urls(response):
        if url.domain not in ALLOWED_DOMAINS:
            alerts.append(f"EXTERNAL_URL: {url}")
        if len(url.query_string) > 100:
            alerts.append(f"ENCODED_DATA_URL: {url}")
    
    # 5. Markdown image exfiltration (EchoLeak pattern)
    if re.search(r'!\[.*?\]\(https?://(?!your-domain\.com)', response):
        alerts.append("MARKDOWN_IMAGE_EXFIL")
    
    if alerts:
        log_security_event(alerts, response, user_query)
        return generate_safe_fallback(user_query)
    return response
```

---

## Layer 5: Agent-Specific Controls

Cost: 3-5 days.

```
1. Tool allowlist enforced at the HARNESS level
   The agent harness only exposes tools from a hardcoded allowlist.
   The model cannot "discover" or "create" new tools.
   Enforced in code, not in the prompt.

2. Outbound network allowlist enforced at INFRASTRUCTURE level
   Container/firewall rules: DENY ALL outbound except:
     - Your LLM API endpoint
     - Your vector database
     - Your internal APIs
   Cannot be bypassed by injection. Network layer doesn't read prompts.

3. Irreversible action confirmation
   Human approval gate OUTSIDE the agent loop.
   Agent creates a draft/proposal → human reviews in application UI → 
   human clicks approve → action executes.
   The LLM never has direct execution authority for irreversible actions.

4. Tool call audit logging
   Every call: timestamp, tool name, full parameters, response, user ID.
   Stored for 90+ days.
   Queryable for incident investigation.
   Alerting on anomalous patterns (see Layer 6).
```

---

## Layer 6: Monitoring and Response

Cost: 1 week initial, ongoing maintenance.

```
Metrics to track:
  - Input classifier block rate (trending up = attack campaign)
  - Output validator alert rate (trending up = bypasses succeeding)
  - Agent tool call frequency per user (anomalies = injection)
  - Response length distribution (shift = behavioral change)
  - Refusal rate (sudden drop = jailbreak; sudden spike = false positives)

Incident response playbook:
  Severity 1 (data exfiltration confirmed):
    → Kill switch: disable agent tools immediately
    → Page security lead and engineering lead
    → Audit last 24 hours of tool call logs
    → Notify affected users per your data breach policy
  
  Severity 2 (injection detected, no confirmed exfiltration):
    → Rate limit the source user/IP
    → Review the injection payload
    → Update input classifier if new pattern
    → Audit output for the session
  
  Severity 3 (jailbreak detected, no agent tools involved):
    → Log the jailbreak payload
    → Rate limit if repeated
    → No immediate page unless content policy violation was severe
```

---

## Priority Order: 2 Engineers, 4 Weeks

```
Week 1:
  Day 1-2: Layer 0 design review. Audit all system prompts for 
           credentials, internal URLs, excess context. Remove them.
  Day 3-4: Layer 2 prompt structure standards. Define the template. 
           Retrofit existing prompts.
  Day 5:   Layer 3 timeouts and token limits on every LLM call.

Week 2:
  Full week: Layer 1 input classifier integration (Lakera Guard or 
  Prompt Shields). Rate limiting on injection patterns.

Week 3:
  Full week: Layer 4 output validation. PII detection, system prompt 
  leakage detection, URL scanning, markdown image blocking.

Week 4:
  Full week: Layer 5 agent controls. Tool allowlist at harness level.
  Network allowlist at infrastructure level. Human confirmation for 
  irreversible actions. Basic tool call audit logging.

Ongoing from Week 1: Layer 6 monitoring. Start with basic metrics.
  Full alerting and incident response playbook by Week 6.
```

This order is not arbitrary. It's ranked by risk reduction per engineering hour. Layer 0 (design review) has the highest ROI because it costs nothing and prevents the most common vulnerabilities. Layer 1 (input classifier) catches the highest volume of attacks. Layers 4-5 (output validation and agent controls) handle the highest-impact scenarios.

# 10 — Threat Model Synthesis

## The Fundamental Difference From Traditional Application Security

```
SQL injection:
  Problem: mixing code and data in database queries.
  Fix: parameterized queries. Structural. Complete. Solved.
  
  PreparedStatement: "SELECT * FROM users WHERE id = ?"
  The database engine enforces the boundary. The fix is architectural.

Prompt injection:
  Problem: mixing instructions and data in LLM context.
  Fix: ??? 
  
  There is no parameterization for natural language.
  There is no architectural separation between system prompt 
  and user input. Both are tokens processed identically.
  
  The UK NCSC explicitly warns: treating prompt injection like 
  SQL injection is dangerous. The attack class looks familiar.
  The solution space is fundamentally different.
  
  SQL injection is solved. Prompt injection is mitigated.
  This distinction governs every architectural decision in this file.
```

---

## Complete Attack Surface Map

For a production RAG + Agent system, every entry point maps to a specific threat and defense:

```
Entry Point              Threat (File)                    Primary Defense
─────────────────────────────────────────────────────────────────────────────
User text input          Direct injection (01)            Input classifier (Layer 1)
Uploaded documents       Indirect injection via RAG (02)  Ingestion sanitization + trust scoring
Web pages (agent)        Indirect injection via agent (02) Outbound network allowlist (Layer 5)
Retrieved chunks         RAG poisoning (02, 05)           Per-tenant namespace isolation
Model/adapter download   Supply chain poisoning (06)      Source verification + hash check
Shared KV cache          Multi-tenant leakage (05)        Tenant isolation at serving layer
Agent tool parameters    Insecure tool design (07)        Typed params + scoped permissions
Guardrail model          Guardrail bypass (08)            Layered defense, not single guardrail
Training data            Data poisoning (06)              Dataset provenance + red-team testing
Agent output             Data exfiltration (03)           Output scanning + outbound control
Model response           Jailbreak content (04)           Output classifier + containment
Session state            Conversation bleed (05)          Per-tenant session isolation
Prompt cache             Cross-tenant cache (05)          Generic cached prefix, no tenant data
```

---

## Risk Matrix — Honest Likelihood and Impact

```
Threat                         Likelihood    Impact (no agents)   Impact (with agents)
───────────────────────────────────────────────────────────────────────────────────────
Direct prompt injection        HIGH          MEDIUM               HIGH
  73% of assessed deployments vulnerable (OWASP).
  Actively exploited at 90+ organizations (CrowdStrike 2026).

Indirect injection via RAG     HIGH          MEDIUM               VERY HIGH
  Any system that retrieves external content is vulnerable.
  EchoLeak proved production-scale exploitation (CVE-2025-32711).

Data exfiltration              MEDIUM        HIGH                 VERY HIGH
  Requires successful injection first. Impact is data breach.
  With agents: exfiltration without user interaction.

Jailbreaking                   VERY HIGH     LOW                  MEDIUM
  Users WILL attempt this. Unsolved problem.
  Low impact if contained (no tools). Medium if tools accessible.

Multi-tenant leakage           LOW           VERY HIGH            VERY HIGH
  Requires specific infrastructure bugs. Impact is catastrophic 
  when it occurs. "Low probability, high severity."

Supply chain poisoning         LOW           HIGH                 HIGH
  Low probability from major providers (Meta, Mistral).
  Higher from community models/adapters on HuggingFace.
  Impact is persistent backdoor in production.

Guardrail bypass               MEDIUM        LOW                  MEDIUM
  Base rate of novel attacks passing classifiers is non-zero.
  Impact depends entirely on what the model can DO when bypassed.
```

---

## Your Stack Risk Assessment: RAG + Postgres + Redis + Agents

### Postgres as Document Store
```
Primary risk: RAG retrieval of poisoned documents.
  Documents stored in Postgres → chunked → embedded → retrieved.
  Poisoned document in Postgres → poisoned chunk in context → injection.

Mitigation:
  Row-level security enforcing per-tenant document isolation.
  Ingestion pipeline with content sanitization (strip invisible text,
  normalize Unicode, quarantine metadata).
  Never share document tables across tenants.
```

### Redis as Session Store
```
Primary risk: session isolation failure → conversation bleed.
  If Redis keys aren't properly namespaced by tenant:
  tenant:A:session:123 could serve tenant:B's request if session 
  lookup has a bug.

Mitigation:
  Key format: "tenant:{tenant_id}:session:{session_id}"
  Validate tenant_id on EVERY request against the authenticated user.
  TTL on all session keys (explicit cleanup, don't rely on TTL alone).
  Automated cross-tenant isolation test in CI/CD.
```

### Redis as Rate Limiter
```
Primary risk: rate limiter bypass → unlimited injection attempts.
  If the rate limiter fails or is bypassed, the attacker can send 
  thousands of injection probes to find one that works.

Mitigation:
  Rate limiter must be in the critical path (not optional middleware).
  Failure mode: if Redis is down, DEFAULT TO DENY, not allow.
  Monitor rate limiter health as a security-critical service.
```

### Agent Tools Touching Postgres
```
Primary risk: injection controls which rows get queried or modified.
  Agent tool: query_database(sql: str) → injection writes the SQL.
  Agent tool: update_record(id: int, data: dict) → injection 
  controls which record is modified and with what data.

Mitigation:
  Agent database user has MINIMAL permissions:
    SELECT only on specific views (not tables).
    No INSERT/UPDATE/DELETE unless explicitly required for the task.
    Row-level security: agent can only access rows belonging to 
    the current tenant.
  Parameterized queries in tool implementation (even though the 
  agent provides parameters, they go through parameterized SQL).
  Audit log of every query the agent executes.
```

---

## Prioritized Roadmap by Risk Reduction Per Engineering Hour

```
Priority 1: IMMEDIATE (Day 1-2)
  Action: Audit all system prompts. Remove credentials, API keys, 
          internal URLs, excess context.
  Risk reduced: eliminates most common exfiltration targets.
  Cost: 0. Just review and delete lines.
  Mitigates: File 03 (exfiltration)

Priority 2: WEEK 1
  Action: Add timeouts and token limits to every LLM call.
          Define prompt structure standard (trust-level XML tags).
  Risk reduced: prevents runaway agents, reduces injection success rate.
  Cost: 1-2 days.
  Mitigates: File 07 (agent tools), File 01 (injection)

Priority 3: WEEK 2
  Action: Integrate input classifier (Lakera Guard or Prompt Shields).
          Add rate limiting on injection patterns.
  Risk reduced: blocks ~80-90% of known injection attempts.
  Cost: 2-3 days.
  Mitigates: File 01 (injection), File 04 (jailbreaking)

Priority 4: WEEK 3
  Action: Output validation pipeline (PII detection, system prompt 
          leakage, URL scanning, markdown image blocking).
  Risk reduced: catches successful injections at the output stage.
  Cost: 3-4 days.
  Mitigates: File 03 (exfiltration), File 08 (guardrail bypass)

Priority 5: WEEK 4
  Action: Agent-specific controls. Tool allowlist at harness level.
          Network allowlist at infrastructure level.
          Human confirmation for irreversible actions.
  Risk reduced: contains blast radius when injection succeeds.
  Cost: 3-5 days.
  Mitigates: File 07 (agent tools), File 03 (exfiltration)

Priority 6: ONGOING
  Action: Monitoring, alerting, incident response playbook.
          Cross-tenant isolation tests in CI/CD.
          Model/adapter provenance tracking (AI SBOM).
  Risk reduced: detection and response capability.
  Cost: ongoing.
  Mitigates: File 05 (multi-tenant), File 06 (supply chain)
```

---

## The Honest State of AI Security (2025-2026)

```
What is true:
  - Prompt injection is OWASP #1 for the second consecutive year.
  - Actively exploited at 90+ organizations (CrowdStrike 2026).
  - No complete defense exists for indirect injection.
  - The field is 2-3 years behind traditional appsec in tooling maturity.
  - Managed API providers patch faster than you discover, but new 
    vectors appear as fast as old ones close.

What this means for how you build:
  1. Defense in depth — no single layer is sufficient.
  2. Assume breach — design for what happens when injection succeeds.
  3. Minimize blast radius — least-privilege context, least-privilege tools.
  4. Maintain incident response — this is ongoing ops, not one-time deploy.
  5. Containment > prevention — you can't prevent all injection, but 
     you can limit what an injected model can do.

What this does NOT mean:
  "Don't build AI systems." The threats are real and manageable.
  Every security discipline started with unsolved problems. 
  We shipped web apps before XSS had mature tooling.
  We shipped APIs before rate limiting was standard.
  We ship AI systems with defense in depth and honest risk acceptance.
  
  The key: know what you're accepting. Document the residual risk.
  Build the monitoring to detect when it materializes.
  Have the playbook to respond when it does.

This is not a problem you solve once. It is an engineering discipline.
Budget for it. Staff for it. Or accept the residual risk explicitly 
and document that decision for when your CISO asks.
```

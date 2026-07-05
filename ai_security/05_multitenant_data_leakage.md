# 05 — Multi-Tenant Data Leakage

## The KV-Cache Sharing Attack

PagedAttention (Paper 14) shares physical KV cache blocks across requests with identical prefixes. This is a performance optimization — prefix caching. It's also a security boundary violation if tenant isolation isn't enforced at the physical block level.

```
How prefix sharing creates cross-tenant leakage:

  Tenant A request: [system_prompt] + [Tenant A context] + [query]
  Tenant B request: [system_prompt] + [Tenant B context] + [query]
  
  If both share the same system prompt, PagedAttention stores ONE 
  copy of the system prompt's KV blocks in physical memory.
  Both requests' page tables point to the same physical blocks.
  
  The vulnerability:
  If the serving layer doesn't enforce isolation at the physical 
  block boundary, residual information from Tenant A's context 
  processing can influence Tenant B's response through:
  1. Attention pattern leakage across shared blocks
  2. KV cache entries from one tenant persisting for the next
  3. Timing side-channels revealing prefix match patterns
  
  "I Know What You Asked" (2024): cross-tenant data exfiltration 
  had the HIGHEST amplification factor of all 18 vulnerabilities 
  studied. 12 of 18 vulnerabilities were amplified by multi-tenancy.
```

This is not a theoretical concern. It's a measured, quantified vulnerability class specific to how production LLM serving infrastructure works.

## Conversation History Bleed

The more common (and less dramatic) multi-tenant failure: session isolation bugs.

```
How it happens:
  Request 1 from User A processes. KV cache populated. Session ends.
  Request 2 from User B arrives at the same GPU worker.
  If session state isn't properly cleared: User A's conversation 
  history remains in context for User B's request.
  
  User B asks: "What did we discuss earlier?"
  System responds with User A's conversation content.
  
  This is not a sophisticated attack. It's a bug.
  It's more common than teams admit because:
  1. Session cleanup is easy to get wrong under load
  2. Connection pooling can reuse sessions across tenants
  3. Redis session stores without proper key isolation 
     can serve wrong tenant's state
  
  Testing for it: send requests with distinct identifiable content,
  then query "what was my previous message?" from a different session.
  If any cross-contamination appears, your session isolation is broken.
```

## Knowledge Base Poisoning Across Tenants

```
Scenario: Multi-tenant RAG system with shared vector store.

Attack:
  Tenant A uploads a document designed to rank highly for common queries.
  The document contains injection payloads (File 02).
  
  If the vector store has NO per-tenant namespace isolation:
    Tenant B's query → retriever finds Tenant A's poisoned document 
    → poisoned chunk in Tenant B's context → injection executes.
  
  Tenant A has poisoned Tenant B's responses without ever 
  touching Tenant B's interface.

The fix is architectural, not algorithmic:
  Every tenant's documents MUST live in a separate namespace/collection.
  Cross-tenant retrieval must be impossible BY CONSTRUCTION at the 
  database level. Not prevented by application logic. Not filtered 
  by a query parameter. Enforced by the storage engine.
  
  Application logic can have bugs. Database-level isolation cannot 
  be bypassed by application-layer errors.
```

## Prompt Caching Risk on Managed APIs

```
When you use prompt caching (Anthropic, OpenAI):
  The provider routes requests with similar prefixes to the same 
  server to maximize cache hits.
  
  If your system prompt contains tenant-specific data:
    Tenant A: "You are an assistant for Acme Corp. Internal API: https://acme..."
    Tenant B: "You are an assistant for Beta Inc. Internal API: https://beta..."
    
    These are DIFFERENT prefixes → no cache sharing. Safe but no savings.
  
  If you try to cache by making prefixes identical but including 
  tenant data in the cached portion:
    Shared: "You are an assistant. Tenant config: {TENANT_DATA_HERE}"
    
    Risk: if caching implementation has bugs, Tenant A's config 
    could be served to Tenant B.

  Correct pattern:
    Cached prefix: "You are a customer support assistant." (generic, no tenant data)
    Non-cached suffix: "Tenant: Acme Corp. Policies: [tenant-specific]"
    
    System prompt contains ZERO tenant-specific data.
    Tenant context goes in the dynamic (non-cached) section.
```

## Defense Architecture

```
1. Per-tenant vector store namespace (database-level enforcement)
   Every tenant gets a separate collection/namespace.
   Query routing includes tenant_id as a mandatory filter 
   enforced at the DB driver level, not application query construction.

2. Per-tenant session state with explicit validation
   Session ID checked against tenant ID on EVERY request.
   Redis keys namespaced: "tenant:{id}:session:{sid}"
   Session cleanup on completion — explicit, not relying on TTL alone.

3. System prompt contains zero tenant-specific data
   Generic system prompt cached. Tenant context in dynamic section.

4. Audit logging of every retrieval
   Log: tenant_id, query, chunks returned, chunk source tenant.
   Alert if chunk_source_tenant ≠ requesting_tenant. 
   This should never happen. If it does, you have a breach.

5. Cross-tenant isolation testing in CI/CD
   Automated test: create data as Tenant A, query as Tenant B.
   Assert zero results. Run this on every deployment.
   Not optional. Not "we'll add it later." In the pipeline from day one.
```

# Glean — Engineering Deep Dive

## 1. The One-Line Architectural Bet

**Build a permission-aware enterprise knowledge graph across 100+ SaaS integrations first, then add LLM-powered answer synthesis on top — treating permissions as a first-class indexed data model, not a filter applied after retrieval.**

The most important event in Glean's history was not their founding in 2019 or any funding round — it was what happened in the hours after ChatGPT launched on November 30, 2022. Glean's leadership played with ChatGPT and immediately saw the shift. "It showed us the art of the possible," said CEO Arvind Jain. Before ChatGPT: Glean provided links to documents (enterprise search). After ChatGPT: Glean could provide direct answers synthesized from company knowledge (enterprise AI assistant).

Within days, they established virtual war rooms in Palo Alto and Bengaluru. Six weeks later, they shipped a test version of Glean Assistant. "It massively changed the trajectory of our company," said Tony Gentilcore (co-founder).

The 6-week pivot was possible because of the architectural bet they'd made 3 years earlier: build the data infrastructure first. By the time ChatGPT arrived, Glean already had:
- 100+ connectors to SaaS tools (Slack, Notion, Drive, Salesforce, Jira, Confluence, email, GitHub, etc.)
- A permission model that maps which users/groups can access which documents
- An indexed corpus of enterprise knowledge
- A search infrastructure (keyword + semantic)

The LLM was the missing layer — and adding it on top of a well-indexed, permission-aware corpus was a 6-week engineering project, not a 2-year infrastructure build. The companies that didn't have the data infrastructure in 2022 spent the next 2+ years building it. Glean just plugged in the model.

This is the deepest lesson in the entire analysis: **the companies that win the AI moment are the ones that built the data pipeline before the AI was ready.** Glean built connectors and permissions when LLMs were academic research. When LLMs became commercial products, Glean was ready.

## 2. Data Model

### Core Entities and Relationships

**Document** — A piece of content from any connected SaaS tool. A document is not just a file — it's any information unit: a Slack message, a Notion page, a Google Drive file, a Jira ticket, a Confluence page, a Salesforce record, a GitHub PR, an email, a Zendesk ticket. The document entity must accommodate radically different data structures across systems: a Slack message has a timestamp, author, channel, and thread; a Jira ticket has a status, assignee, priority, labels, and comments; a Google Doc has content, sharing settings, and edit history. Glean's document model must normalize these into a searchable representation while preserving system-specific metadata.

**Chunk** — A semantic fragment of a document, embedded for retrieval. Chunking strategy matters enormously for RAG quality. A Notion page might be chunked by headings. A Slack thread might be chunked by conversation turns. A PDF might be chunked by pages or sections. A Jira ticket might be a single chunk (short) or multiple chunks (if it has a long description + many comments). The chunking must be semantic (not arbitrary character splits) and must preserve enough context for the chunk to be useful in isolation (when retrieved without the full document).

**User** — An identity with group memberships, role assignments, and access patterns across all connected systems. The critical challenge: a single human has different identities in different systems. "ajain@company.com" in Google is the same person as "@arvind" in Slack and "Arvind Jain" in Confluence. Identity resolution across 100+ systems is a prerequisite for permission-aware search. If the identity mapping is wrong, the permission filter is wrong, and the user either sees too much (data leak) or too little (poor search quality).

**Permission** — A mapping from user/group to document/chunk, synced per-source-system. This is the most complex entity in Glean's data model. Permissions differ fundamentally across systems:
- **Google Drive:** Owner, Editor, Viewer, shared with specific users or groups, link sharing options
- **Slack:** Public channels (everyone), private channels (members), DMs (participants only)
- **Confluence:** Space permissions, page restrictions, group access
- **Salesforce:** Record-level security, role hierarchy, sharing rules, field-level security
- **GitHub:** Repository access, organization membership, team membership, collaborator access
- **Jira:** Project permissions, issue security levels, reporter/assignee visibility

Glean must map each system's permission model into a unified permission graph and keep it synchronized. When someone is removed from a Slack channel, their access to messages in that channel must be revoked in Glean's index within minutes — not hours or days.

**Connector** — An integration with a SaaS tool. Each connector handles:
- **Authentication:** OAuth, API keys, service accounts — different per system
- **Data extraction:** Full crawl (initial indexing) + incremental sync (ongoing updates via webhooks or polling)
- **Permission synchronization:** Fetching the current permission state from the source system and propagating it to the index
- **Rate limiting:** Respecting each system's API limits (e.g., Slack API has a rate limit of ~1 request per second; Google Drive API has a per-user quota)
- **Schema mapping:** Translating the source system's data model into Glean's document model
- **Error handling:** Retrying failed fetches, handling API changes, alerting on connector failures

100+ connectors is a significant engineering surface area. Each connector is essentially a mini-integration product. When Notion changes their API, the Notion connector breaks. When Salesforce adds a new object type, the Salesforce connector may need updating.

**Agent** — An agentic workflow that can search, reason, and take actions across connected systems. Agents go beyond search — they can create Jira tickets, update Confluence pages, send Slack messages, and modify records in connected systems. This requires write access to source systems, which adds another layer of permission complexity.

### State Transitions

```
Source System Data Change (new Slack message, updated Notion page, closed Jira ticket)
→ Connector Detects Change (webhook notification or polling interval)
→ Document Fetched from Source System
→ Permission State Fetched for This Document
→ Document Chunked at Semantic Boundaries
→ Chunks Embedded (vector representations generated)
→ Permission Mapping Applied to Each Chunk
→ Index Updated (old chunks replaced, new chunks + permissions + embeddings stored)
→ Search Index Reflects Current State
```

### What's Stored Where

- **Source documents:** Remain in their original SaaS tools. Glean indexes content but does not become the system of record. This is important: Glean is a read-through cache of enterprise knowledge, not a data store. If a Notion page is updated, Glean re-indexes it — but the source of truth is always Notion.
- **Chunks + embeddings:** Glean's search infrastructure. Likely a combination of inverted index (for keyword search) + vector database (for semantic search), possibly built on Elasticsearch/OpenSearch + a custom vector index, or entirely custom-built.
- **Permission graph:** Glean's servers, continuously synced from 100+ source systems. This is a large, dynamic graph: users × groups × documents × permissions, with frequent updates as people join/leave teams, documents are created/shared, and access is granted/revoked.
- **Query history:** Glean's servers, per-user. Used for ranking improvement (personalized search results) and analytics (what are people searching for? what aren't they finding?).
- **LLM-generated answers:** Ephemeral. An answer synthesized for one user cannot be cached and served to another user because they may have different permissions — the answer might include information from a chunk that the second user can't access. This makes caching fundamentally harder than in consumer search.
- **Connector state:** Persistent — last sync timestamp, cursor/offset for incremental sync, error state, credential status.

### Ephemeral vs Persistent

LLM-generated answers are ephemeral (permission-sensitive, non-cacheable across users). The index (chunks + embeddings + permissions) is persistent and continuously updated. Connector sync state is persistent. Query history is persistent (for personalization). Source documents are always fetched fresh when needed (Glean may cache document content in the index, but the source system is authoritative).

## 3. Write Path / Read Path

### Write Path: Source Data Changes, Index Must Update

1. **Change detection** — A SaaS tool changes: new Slack message posted, Notion page edited, Jira ticket closed, Google Doc shared with a new user. Detection happens via:
   - **Webhooks** (preferred): source system pushes a notification to Glean when something changes. Real-time, low latency, efficient.
   - **Polling** (fallback): Glean periodically queries the source system's API for changes. Higher latency (depends on polling interval), higher API usage, necessary for systems without webhook support.
   
   Different systems support different change detection mechanisms, and the reliability varies. Webhooks can be dropped during system outages. Polling can miss changes if the API's change-detection is imperfect.

2. **Document fetching** — Glean's connector fetches the changed document via the source system's API. This must be incremental (only fetch what changed, not re-crawl everything) to stay within API rate limits and minimize latency.

3. **Permission fetching** — Simultaneously, the connector fetches the current permission state for this document:
   - Who has access? (Specific users and groups)
   - What level of access? (Read, write, admin — Glean primarily cares about read access)
   - Are there inheritance rules? (A child page inherits parent page permissions in Confluence)
   - Are there exceptions? (A document in a public Drive folder with a specific "restricted" sharing setting)
   
   Permission resolution can be complex. In Salesforce, determining whether a user can see a specific record requires evaluating: organization-wide defaults, role hierarchy, sharing rules, manual shares, team membership, and record ownership. This is a non-trivial computation that must be performed for every document.

4. **Chunking** — The document is split into semantic chunks. Chunking strategy varies by document type:
   - **Slack messages:** Each message or short thread might be a chunk
   - **Confluence pages:** Chunked by heading sections
   - **Google Docs:** Chunked by paragraphs or sections
   - **Jira tickets:** Description + each comment might be separate chunks
   - **Code (GitHub):** Chunked by function/class/file
   
   Chunk size must balance: too small → loss of context (a retrieved chunk makes no sense without its surroundings); too large → irrelevant content dilutes the signal.

5. **Embedding** — Each chunk is passed through an embedding model to generate a vector representation. The embedding model must handle multi-format, multi-domain content: code, natural language, structured data, tables, lists. Glean likely uses a general-purpose text embedding model, possibly fine-tuned on enterprise content patterns.

6. **Permission association** — The resolved permissions are associated with each chunk in the index. This is the critical step that makes Glean's architecture unique. Permissions are not a metadata tag on the document — they are part of the indexed data structure. At query time, the search engine can filter by permission as part of the retrieval process, not as a post-processing step.

7. **Index update** — The old version of the document's chunks is replaced with the new version. The index must handle concurrent updates (many documents changing simultaneously) without corruption or inconsistency.

8. **Latency target:** Minutes, not hours. Enterprise search with stale data is worse than no search — if a user searches for the latest sales numbers and gets yesterday's numbers because the index hasn't synced, trust erodes quickly. For critical systems (Slack, email), near-real-time sync (under 5 minutes) is likely targeted.

### Read Path: User Queries for Information

1. **Query submission** — User types a natural language query ("What's our Q3 revenue forecast?") or a keyword search ("Q3 revenue forecast deck"). The query interface is likely in a browser extension, standalone web app, or Slack bot.

2. **Query parsing** — Intent extraction (is this a factual question, a document search, or a complex analytical question?), entity recognition (company names, product names, people, dates), and query expansion (adding synonyms or related terms).

3. **User permission set retrieval** — Before searching, the system must know what this user can see. The user's permission set is the union of all their access rights across all connected systems. This is potentially a large data structure: a user might have access to thousands of documents across 20+ systems. Glean likely caches the permission set per user and invalidates the cache when permissions change.

4. **Hybrid search with permission filtering** — This is the core engineering achievement:
   - **Keyword search:** Traditional inverted index search for exact term matches. Fast, precise, good for specific queries ("Q3 revenue deck").
   - **Semantic search:** Embedding similarity search for meaning-based matches. Good for broad queries ("how do we handle enterprise customer renewals?").
   - **Permission filter:** Applied DURING retrieval, not after. The search engine only considers chunks that the requesting user can access. This filter is baked into the index structure — permission-disallowed chunks are not retrieved, not scored, and not returned.
   
   Why permission filtering must happen during retrieval, not after:
   - **Performance:** Retrieving 1,000 chunks and then filtering to 100 is 10x more expensive than retrieving 100 directly
   - **Quality:** If you retrieve 100 chunks and filter to 10, your result set is much smaller than intended — you may miss relevant, permitted content that was ranked 101–200
   - **Security:** Post-retrieval filtering means unpermitted data was loaded into memory, scored, and processed. Even if it's not shown to the user, it was handled by the system — this is an audit risk
   - **Correctness:** If the LLM sees unpermitted chunks (even if they're filtered from the final answer), it might incorporate information from those chunks into its reasoning — a subtle but serious permission leakage

5. **Top-K chunk retrieval** — The K most relevant, permission-filtered chunks are retrieved. K is likely dynamically sized based on query complexity and the number of relevant chunks found. Each chunk includes metadata: source system, document title, author, date, and a link back to the source.

6. **LLM synthesis (Glean Assistant)** — For answer-mode queries, the retrieved chunks are passed to a frontier LLM (GPT-4, Claude, or Gemini — Glean doesn't build its own model) with the user's query. The LLM synthesizes a coherent answer from the chunks, with citations back to source documents. The synthesis must:
   - Answer the question directly (not just list relevant documents)
   - Include citations (so the user can verify and drill deeper)
   - Not include information from unchunked sources (don't hallucinate)
   - Not synthesize information that combines permitted chunks to infer unpermitted knowledge (the information-theoretic leakage problem)

7. **Response rendering** — The answer is presented with cited sources, each linking back to the original document in the source system (clicking a citation opens the Notion page, Slack message, or Drive file directly). For search-mode queries, a ranked list of documents/chunks is returned with snippets.

8. **For agentic queries** — If the user asks the agent to take an action ("create a Jira ticket for this bug" or "summarize this and post it in #engineering channel"), the agent uses write-back connectors to execute the action across connected systems. This requires separate permission verification: does this user have write access to the target system?

### Where Latency Lives

| Component | Estimated Latency | Notes |
|-----------|------------------|-------|
| Query parsing | 50–100ms | Intent extraction + entity recognition |
| Permission set retrieval | 50–200ms | Cached per user, invalidated on permission changes |
| Keyword search | 100–300ms | Inverted index, well-optimized |
| Semantic search | 200–500ms | Vector similarity search across large embedding space |
| Permission filtering (during retrieval) | 100–500ms | Depends on permission graph complexity |
| Hybrid result merging | 50–100ms | Combine keyword + semantic results |
| LLM synthesis (Glean Assistant) | 2–5 seconds | Frontier model inference, streaming |
| **Total (search results)** | **500ms–1.5 seconds** | |
| **Total (synthesized answer)** | **3–7 seconds** | Dominated by LLM inference |

## 4. AI/ML Layer

### Models Used and Why

**Glean does not build its own base models.** They use frontier models (likely GPT-4, Claude, and/or Gemini) for the Assistant's answer synthesis layer. This is a deliberate strategic choice:
- **Pro:** Zero R&D cost on model training. Free quality upgrades when frontier models improve. Can switch model providers based on cost/quality/latency.
- **Con:** No unique model capability. Any competitor with the same frontier model access has equivalent reasoning quality. Dependent on model providers' pricing, availability, and terms.

The strategic logic: Glean's competitive advantage is the data layer (connectors, permissions, index), not the reasoning layer (LLM). They correctly identified that building a model would distract from their actual moat. Let OpenAI, Anthropic, and Google compete on model quality — Glean will use whichever is best at any given time.

**Embedding model:** Likely a general-purpose text embedding model (could be OpenAI's embedding model, a fine-tuned Sentence-BERT, or a custom model trained on enterprise content). The embedding model quality directly affects semantic search relevance. Glean may fine-tune the embedding model on enterprise content patterns (technical documentation, business communication, project management) to improve domain-specific retrieval.

### Context Strategy: Permission-Aware RAG

Standard RAG: retrieve the K most semantically similar chunks to the query, inject them into the LLM context, generate an answer.

Glean's RAG: retrieve the K most semantically similar chunks *that this specific user is allowed to see*, inject them into the LLM context, generate an answer.

The permission filter degrades retrieval quality by design. The most relevant chunk might be in a document the user can't access. Example:
- User (Marketing team) asks: "What's our next product launch timeline?"
- The most relevant chunk is in a restricted Engineering document that Marketing can't see
- The second-most relevant chunk is in a public Slack announcement, which is less detailed

The system correctly returns the less-detailed-but-permitted chunk. The user gets a worse answer than they would with unrestricted access — but this is correct behavior. The alternative (showing them the Engineering document) is a data breach.

This creates a unique engineering challenge: **the system must be good enough that permission-filtered results are still useful.** If the best information is always in restricted documents, the search quality will feel poor to most users. Glean must optimize for "best answer given your access rights" — which means the retrieval must be excellent at finding the second-best, third-best chunks, not just the single best.

### Fine-tuning vs Prompting vs Retrieval

- **Retrieval dominates.** The value is in *what* gets retrieved (and who gets to see it), not in how the model reasons about it.
- **Prompting:** System prompt for the synthesis layer includes: user's query, retrieved chunks with source metadata, instructions for citation format, and constraints (don't make up information, cite sources).
- **Fine-tuning:** Minimal for the base model. Glean may fine-tune the embedding model on enterprise content, and may fine-tune a ranking model for search result ordering. But the LLM synthesis layer is likely used off-the-shelf.
- **Personalization:** Glean likely uses query history and click patterns to personalize search rankings — but this is search ranking personalization, not LLM fine-tuning.

### Failure Modes

1. **Permission leakage** — The catastrophic failure. If a user sees a chunk they shouldn't have access to, Glean has committed the enterprise equivalent of a data breach. This can happen through:
   - Stale permissions (user's access was revoked in the source system but Glean hasn't synced yet)
   - Permission resolution errors (the connector misinterprets the source system's permission model)
   - Identity mapping errors (the user's Glean identity is incorrectly linked to a different person's source system identity)
   - LLM inference leakage (the model combines information from multiple permitted chunks to infer information that no single chunk reveals)

2. **Stale data** — Documents change, tickets close, Slack threads get archived. If Glean's index is stale, search results are wrong. A user who searches for "current sales quota" and gets last quarter's numbers will stop trusting the system. The sync latency (how quickly index reflects source changes) directly determines data freshness.

3. **Connector failures** — Each connector can fail independently. A broken Slack connector means Slack messages stop indexing. The user might not notice until they can't find something they know is in Slack. Connector health monitoring and alerting is critical.

4. **Answer hallucination** — The LLM synthesizes an answer from retrieved chunks but adds information not present in any chunk. Mitigated by requiring citations (every claim in the answer must link to a source chunk), but not fully eliminated — LLMs can generate plausible-sounding text that subtly extends beyond the source material.

5. **Cross-system information combination** — The LLM sees chunks from Slack, Drive, and Jira simultaneously. It might combine information across systems to create a synthesis that no single system contains. This is usually the desired behavior (synthesizing company knowledge), but can be dangerous when the combination reveals something that the user shouldn't know (e.g., combining permitted revenue numbers from Salesforce with permitted project delays from Jira to infer upcoming layoffs — information that no single system reveals but the combination implies).

## 5. Critical Engineering Decisions & Tradeoffs

### What They Gave Up

**Model differentiation.** By not building their own model, Glean has no unique AI capability. Their LLM synthesis is only as good as the frontier model they're using — and that model is available to every competitor. A competitor with good data infrastructure + the same frontier model + permission awareness could theoretically match Glean's output quality.

The mitigation: the data infrastructure IS the differentiation. Building 100+ connectors with robust incremental sync, permission mapping, and error handling takes 2–3 years. Even if a competitor has the same model, they don't have the same data access.

### Technical Debt Accumulating

**100+ connector maintenance.** Each connector is a point of integration with an external system. External systems change:
- API versions get deprecated (Slack moved from Web API to Events API)
- Authentication flows change (OAuth 2.0 refresh token behavior varies by vendor)
- Data models evolve (Notion adds new block types, Jira adds new field types)
- Rate limits change (source systems may tighten limits as Glean's usage grows)
- New systems emerge (customers adopt new tools that Glean doesn't yet support)

Each connector requires ongoing maintenance, testing, and monitoring. At 100+ connectors, this is a full-time job for a dedicated team of 10–20 engineers. The maintenance burden grows linearly with connector count and non-linearly with total customers (more customers = more diverse system configurations = more edge cases per connector).

The connector catalog is both the moat and the debt. Adding a connector increases competitive advantage; maintaining it has ongoing cost. The decision to build connector N+1 must weigh: market demand (do customers need it?) vs maintenance cost (can the team sustain it?).

### The Decision Hardest to Undo

**Permissions baked into the index at the chunk level.** This was architecturally correct (the alternatives are worse), but it means:
- The entire index schema includes permission data for every chunk
- Index operations (write, update, query) are all permission-aware
- Index performance is coupled to permission graph complexity
- Changing the permission model (e.g., from chunk-level to document-level for performance, or adding new permission types) requires re-indexing everything

This decision permeates every layer of the system. It's not a module that can be swapped — it's a fundamental property of the data structure. Undoing it means rebuilding the index from scratch, which means rebuilding the core product.

## 6. Privacy & Security Architecture

### Data Flow

```
SaaS tools (Slack, Drive, Notion, Salesforce, etc.)
→ [OAuth/API keys] → Glean connectors (authentication, data extraction, permission sync)
→ Glean processing (chunking, embedding, permission mapping)
→ Glean index (chunks + embeddings + permission associations)
→ User query → Permission-filtered retrieval → LLM synthesis → Response to user
```

### Threat Model at Each Hop

**Connector credentials:**
- OAuth tokens, API keys, and service account credentials are high-value targets. Each credential grants access to a customer's SaaS data. A breach of Glean's credential store could expose multiple customers' data across multiple systems.
- Credentials must be encrypted at rest, rotated periodically, and scoped to minimum necessary permissions (read-only where possible).

**Permission leakage:**
- The existential risk. If an intern sees the board deck, Glean has failed. Permission leakage can occur at any point: indexing (wrong permissions stored), querying (permission filter bypassed), or synthesis (LLM combines permitted information to infer restricted information).
- Testing for permission leakage requires adversarial test cases: create a document visible to group A but not group B, and verify that group B members cannot retrieve it through any query.

**LLM synthesis risk (information-theoretic leakage):**
- The model could combine information from multiple permitted chunks to infer information that no single chunk reveals but that the user shouldn't know. Example: User has access to "Q3 revenue was below target" (from a public announcement) and "Executive team is restructuring sales org" (from a public Slack channel). The LLM combines these to answer "Is there going to be a sales layoff?" with "Based on the below-target revenue and sales restructuring, layoffs appear likely." Neither individual chunk reveals this, but the combination does.
- This is fundamentally hard to prevent. Solutions: restrict the LLM's ability to combine cross-system information, limit the number of chunks from different access levels, or add a review step for sensitive queries. None of these fully solve the problem.

**Multi-tenant isolation:**
- Enterprise customers must be guaranteed that their data is never visible to other tenants. This is table-stakes for enterprise SaaS but especially critical when Glean holds data from 100+ systems per customer. A multi-tenant breach would expose a company's Slack messages, Drive files, Salesforce records, and email simultaneously.

### Compliance Choices Shaping Architecture

**SOC 2 Type II** minimum for enterprise sales. Data residency requirements (EU customers may require EU-based processing and storage — this means Glean's index infrastructure must be multi-region). GDPR right-to-erasure must be implemented (if a user requests deletion, all chunks and embeddings associated with their content must be identifiable and deletable across the index).

The permission-at-index-time decision was partly compliance-driven. Post-retrieval filtering is an audit nightmare: "we retrieved 1,000 chunks, including 200 that this user shouldn't see, and then filtered them out." An auditor asks: "but your system loaded those 200 restricted chunks into memory and scored them — how do you know no information leaked?" Index-level filtering means the data is never retrieved in the first place — a much cleaner compliance story.

## 7. Latency Engineering

### Where the Latency Budget Is Spent

The permission filter is the latency variable that makes Glean unique. Standard search: query → retrieve → rank → return. Glean search: query → retrieve-with-permission-filter → rank → return. The permission filter adds computation to every retrieval operation.

A user with simple permissions (member of 3 groups, access to 1,000 documents) has a fast filter. A user with complex permissions (member of 20 groups across 10 systems, with individual exceptions and inherited access rules) has a slow filter. The permission graph must be traversed to determine access for each candidate chunk.

Optimization strategies:
- **Permission set caching:** Pre-compute each user's accessible document set and cache it. Invalidate on permission changes.
- **Bloom filters:** Use probabilistic data structures for fast "definitely not accessible" checks, with exact checks only for probable matches.
- **Permission-aware index partitioning:** Physically separate chunks by permission level (public, team-level, restricted) and query only the relevant partitions.

### P50/P90/P99 Targets

Source material doesn't provide specific numbers. Reasoning from first principles:

| Query Type | P50 Target | P90 Target | P99 Target |
|-----------|------------|------------|------------|
| Keyword search | 300ms | 600ms | 1.5 seconds |
| Semantic search | 700ms | 1.2 seconds | 2.5 seconds |
| Synthesized answer | 4 seconds | 6 seconds | 10 seconds |
| Agentic action | 8 seconds | 15 seconds | 30 seconds |

### What Breaks at 10x Scale

**Permission graph size.** If you have 10x more users, each with access patterns across 100+ systems, the permission graph becomes enormous. The graph has O(users × documents) edges in the worst case, and with 100+ systems contributing documents, the total document count can reach billions.

**Permission sync frequency.** More users = more permission changes per minute (people join teams, leave teams, documents are shared, access is revoked). Each permission change must be propagated to the index. At 10x scale, the permission sync pipeline must handle 10x more events per minute.

**Index size.** More customers = more documents = larger index. If each customer has 10M documents and each document has 5 chunks, at 1,000 customers that's 50 billion chunks. The vector search infrastructure must handle similarity queries across 50 billion vectors with permission filtering. This is at the frontier of vector search capability.

## 8. The Product-Engineering Intersection

### Product Decision Forcing Hard Engineering Constraint

**"Respect who can see what."** This is not a feature — it's the entire architecture. Enterprise customers won't deploy a search tool that might expose restricted documents. The product requirement (permission awareness) forced the most expensive and complex architectural decision (permission-at-index-time). Estimated engineering cost: 30–40% of total engineering effort is spent on the permission infrastructure — indexing, syncing, querying, testing, monitoring.

A consumer search product could skip this entirely. A startup building enterprise search without permissions would ship faster, but would fail the first enterprise security review.

### Engineering Constraint Creating Product Feature

**The connector infrastructure** (100+ SaaS integrations) became the product pitch. Glean's value proposition is: "search across all your tools." But the engineering that makes this possible (connectors, auth, incremental sync, permission mapping) IS the product. Search quality is a commodity (Elasticsearch, OpenSearch, custom models — all can provide decent search). Connector breadth is the differentiator.

No competitor can casually add 100 connectors. Each one requires: understanding the source system's API, authentication flow, data model, permission model, and change detection mechanism. Testing with real customer data. Handling edge cases specific to that system. Maintaining the connector as the source system evolves. This is 2–3 years of engineering to replicate.

### The "Looks Like Product but Is Actually Systems Design" Moment

**The 6-week ChatGPT pivot.** This looks like a product pivot (from search to AI assistant), but it's actually a demonstration that the engineering infrastructure was correctly architected. Adding an LLM synthesis layer on top of a well-indexed, permission-aware corpus is a modest engineering project — the hard work (connectors, permissions, index) was already done.

If Glean had not built the data infrastructure in 2019–2022, the "pivot" would have been a 2-year rebuild. The 6-week timeline proves that the infrastructure was designed for extensibility — adding a new retrieval consumer (LLM synthesis layer) didn't require modifying the existing infrastructure (connectors, permissions, index).

The lesson: build infrastructure that is consumer-agnostic. Glean's index serves keyword search, semantic search, and LLM synthesis from the same data store. If a new AI paradigm emerges next year, Glean can add it as another consumer of the same index. The infrastructure investment compounds.

## 9. What a Well-Resourced Competitor Needs to Win

### The Actual Moat

The moat is **the connector catalog + the permission graph + the customer base**, layered:

1. **Connector catalog (100+ integrations):** 2–3 years to replicate at comparable quality. Each connector requires system-specific expertise and ongoing maintenance. The catalog breadth is what makes Glean the "Switzerland option" — it works across all vendors, unlike Microsoft Copilot (Microsoft ecosystem only) or Google Vertex AI Search (Google ecosystem only).

2. **Permission graph infrastructure:** The permission-at-index-time architecture is a fundamental design decision that permeates every layer. A competitor that starts with post-retrieval filtering and later decides to move to index-time filtering is rebuilding from scratch.

3. **Accumulated index quality:** Years of connector tuning, chunking optimization, and ranking model improvement. The search quality for "engineering document from Q2 last year about API rate limiting" depends on thousands of small decisions about how to chunk, embed, and rank enterprise content.

### Build vs Buy

| Component | Build or Buy? | Time to Parity |
|-----------|--------------|----------------|
| LLM synthesis | Rent (frontier model API) | Immediate |
| Search infrastructure | Build (Elasticsearch + vector DB) | 3–6 months |
| Single connector | Build | 2–4 weeks per connector |
| 100+ connectors | Build | 2–3 years |
| Permission-at-index infrastructure | Build (fundamental architecture) | 6–12 months |
| Permission graph maintenance at scale | Build + operate | Ongoing |
| Customer trust + deployment data | Build (requires customer base) | 2–3 years |

The dangerous competitor is Microsoft (Copilot for Microsoft 365) — they have distribution, deep integration with Office 365 + Teams + SharePoint, and the Azure AI infrastructure. But Microsoft is limited to the Microsoft ecosystem; Glean works across all vendors. If a company uses Notion + Slack + Salesforce + GitHub (not Microsoft's tools), Microsoft Copilot can't help them. Glean can.

## 10. Steal This

### What You'd Take

**"Build the infrastructure first, add intelligence later."** Glean built connectors and permissions in 2019–2022, before LLMs were commercially available. When the LLM moment arrived, they were ready. The lesson is universal:

If you know a domain will eventually need AI (and every domain will), build the data pipeline now. The data pipeline — connectors, data normalization, permission models, indexing — is the hard, slow work. The model is the easy, fast work (call an API, pass the data, get an answer). The company that has the data pipeline when the model arrives wins. The company that has the model but no data pipeline builds a demo.

### Mistake They Avoided

**Building their own model.** Glean correctly identified that their competitive advantage is the data layer, not the reasoning layer. Building a model would have consumed years of engineering effort and tens of millions in compute — and the result would have been worse than GPT-4 or Claude. Instead, they invested that effort in connectors and permissions, which no model vendor provides.

The temptation to build a model is strong (it's technically interesting, it's differentiating on paper, investors like it). Glean resisted the temptation and focused on the unglamorous infrastructure that actually drives enterprise value. This is a discipline that most AI companies lack.

### What I'd Do Differently

**I'd invest more aggressively in write-back capabilities (agentic actions).** Glean currently excels at search (read). The agentic layer (create tickets, update docs, send messages) is newer. The moat gets dramatically stronger when Glean can not only find information but take actions:
- "Find all open bugs related to the payments service and create a summary Jira ticket" — this requires search + write-back to Jira
- "Update the onboarding doc with the latest security policy changes" — this requires search + write-back to Confluence

Write-back across 100+ systems with the same permission awareness is an order of magnitude harder than read (you need write permissions, which are more complex than read permissions; you need to handle conflicts, versioning, and undo). But it transforms Glean from a search tool into an enterprise operating system.

## 11. Raw Engineering Signals

- "It showed us the art of the possible" — Arvind Jain, on playing with ChatGPT hours after its launch
- "It massively changed the trajectory of our company" — Tony Gentilcore
- 6-week sprint from ChatGPT launch to test version of Glean Assistant
- Virtual war rooms in Palo Alto and Bengaluru for the pivot
- 100+ SaaS connectors (Slack, Notion, Drive, Salesforce, Jira, Confluence, email, GitHub — and dozens more)
- Founded by ex-Google engineers: Arvind Jain, T.R. Vishwanath, Tony Gentilcore (search is in the DNA)
- $7.2B valuation (Series F, $150M, February 2026)
- ~$200M ARR
- Permission model operates at chunk level, not document level — this is the fundamental architectural decision
- Hybrid search: keyword + semantic, combined for better retrieval
- Pre-ChatGPT: Glean provided links to documents. Post-ChatGPT: provides answers with citations.
- "It showed us the art of the possible" — this quote captures the pivot moment perfectly
- Agentic layer: Glean agents that can take actions across connected systems (not just search)
- Originally: "Google search for the workplace" — LLMs trained on enterprise data before LLMs were mainstream

---

**The single most important thing I'd tell a team building in enterprise AI:** Permissions are not a feature — they are the architecture. If you treat access control as a post-processing filter, you've built a system that will either leak data or be too slow to use. Bake permissions into your index from day one, even if it costs 3x the engineering effort. Enterprise customers will never deploy a system where the answer to "who can see this?" is "we check after retrieval." And build your data pipeline before you need your AI — the company that has the connectors when the next model breakthrough arrives will pivot in 6 weeks. The company that doesn't will spend 2 years catching up.

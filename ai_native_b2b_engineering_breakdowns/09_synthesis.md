# Cross-Cutting Engineering Synthesis

## The Pattern Nobody's Naming

**The integration layer is the actual product; the AI is the feature.**

After dissecting all 8 companies to atoms, the pattern that emerges most clearly is one that none of them market: the engineering that enables distribution is more valuable than the AI itself.

- Harvey's moat is not the custom case law model — it's the trust architecture that got BigLaw firms to let AI touch attorney-client privileged documents, the compliance infrastructure that passed government security reviews (Singapore judiciary), and the 25,000 agent configurations that encode how specific legal workflows operate at specific firms.
- Tennr's moat is not RaeLM — it's the integration layer that connects fax servers, on-prem file storage systems from the 1990s, and dozens of EHR systems. It's the payer criteria knowledge base containing thousands of insurance-specific rule sets by state, service type, and payer. It's the 8,000 page classification taxonomy built from processing 4 million medical documents.
- Abridge's moat is not the Contextual Reasoning Engine — it's being the first ambient AI tool inside Epic's Pal program. Epic holds 350M+ patient records. Being inside Epic means Abridge is inside the workflow where the note gets signed. Any competitor must either replicate the Epic integration (which Epic controls) or compete outside the dominant workflow.
- Glean's moat is not frontier LLM quality — it's 100+ SaaS connectors with permission-aware indexing at the chunk level. When ChatGPT launched, Glean pivoted in 6 weeks because the connector infrastructure was already built. The LLM was just the last layer plugged in.
- Cursor's moat is not the VS Code fork or tree-sitter integration — it's the billions of accepted Tab completions that train the fine-tuned completion model, creating a feedback flywheel that a new competitor can't replicate without the same user volume.
- Writer's moat is not any AI capability at all — it's the customer-specific configurations (style guides, knowledge graphs, workflows) that represent months of organizational effort to build and would take months to rebuild in a competing product.

**The pattern: the companies that win in AI-native B2B are building integration infrastructure that happens to use AI as the core capability — not AI that happens to need integration.** The model is commodity. The connector, the permission graph, the compliance pipeline, the audit trail, the EHR integration, the payer criteria database, the citation verification layer — these are the engineering investments that compound over time and create defensible positions.

Nobody names this pattern because it's unglamorous. "We built 100 SaaS connectors" doesn't make a TechCrunch headline. "We can read 8,000 types of medical forms" doesn't go viral on Twitter. "Our audit trail logs every generation with full provenance" doesn't impress AI researchers. But these are the engineering decisions that, 4 years into a company's life, separate the $11B company from the demo that never found product-market fit.

## The Shared Infrastructure Layer

**Every company in this analysis sits on top of 3 invisible infrastructure layers that nobody talks about in product demos or investor presentations:**

### 1. Vector Databases / Embedding Infrastructure

The embedding pipeline (chunk → embed → store → retrieve) is now as fundamental to AI-native software as SQL databases are to traditional software. Every company uses it:
- Cursor: tree-sitter AST chunking → custom embedding model → Turbopuffer (serverless vector index)
- Glean: multi-source document chunking → embedding model → custom index with permission-aware filtering
- Harvey: case law chunking → embedding for retrieval alongside the custom model
- Tennr: medical document representation for classification and extraction (visual embeddings via RaeLM)

Nobody differentiates on their embedding pipeline — it's infrastructure. But everyone builds one. The tools vary (Pinecone, Weaviate, Qdrant, ChromaDB, Turbopuffer, custom-built), and the chunking strategies are domain-specific (tree-sitter for code, heading-based for documents, speaker-turn-based for conversations). But the pattern is universal.

### 2. Model Routing / Orchestration

No company uses a single model for all tasks. Model routing — selecting the right model for each inference call based on latency, quality, and cost constraints — is becoming a standard infrastructure component:

- **Cursor:** Two completely separate inference paths. Tab completion uses a small, fast, fine-tuned model (~50ms budget). Chat/Agent uses frontier models (Claude, GPT-4, Gemini) with seconds of latency budget. Plus Explore subagent with a faster model for parallel searches.
- **Harvey:** Multi-call agent orchestration — multiple model invocations per user query, each focused on a different sub-task (parse, retrieve, reason, synthesize).
- **Tennr:** "Enterprise orchestration engine + series of specialized language models" — classification model, extraction model(s), orchestration layer routing between them.
- **Abridge:** Separate ASR model + Contextual Reasoning Engine (itself multi-component: clinical significance classifier, SOAP mapper, billing code assigner).
- **Writer:** Routes to different frontier models (GPT-4, Claude) based on availability, cost, and task type, with the governance layer as the constant.

The pattern: **every product has at least two modes — fast/cheap and slow/expensive — and routes between them based on the task.** This is not a feature; it's an architectural principle. Teams that try to serve both modes from a single model end up with a system that's too slow for real-time use and too expensive for interactive use.

### 3. Compliance and Audit Infrastructure

Every company spends 20–40% of its engineering budget on compliance infrastructure that never shows up in a product demo:

- **Writer:** Audit trails are literally the product. Every generation logged with full provenance.
- **Harvey:** Attorney-client privilege protections, firm-level data isolation, government security reviews.
- **Tennr:** HIPAA compliance, BAAs with every integration partner, PHI handling throughout the pipeline.
- **Abridge:** HIPAA, patient consent management, BAAs, PHI data flow controls, Epic-grade security.
- **Glean:** Per-user permission enforcement at the chunk level, SOC 2 Type II, data residency.
- **Cursor:** "Source code never stored" guarantee, file path encryption, 6-week expiry on indexed data.
- **ElevenLabs:** Voice clone consent verification, deepfake moderation, content watermarking.
- **Devin:** Sandbox isolation (VM-level), execution trace handling, code retention policies.

This infrastructure is invisible to users but essential for enterprise adoption. A startup that builds a beautiful AI product and then tries to add compliance as an afterthought will spend 6–12 months redesigning their architecture. The companies in this analysis that designed for compliance from day one (Writer, Glean, Abridge) have a structural advantage: their architecture naturally supports enterprise requirements without retrofitting.

## The Common Constraint

**Context management is the single constraint all 8 products are fighting against.**

Every company has a different answer, but they're all solving the same problem: the model can reason about X tokens, but the task requires 10X tokens of context. The context window is the new memory limit, and every architecture is a workaround for it.

| Company | Context Challenge | Workaround |
|---------|------------------|------------|
| Harvey | Legal reasoning requires considering many cases simultaneously | Multi-call agent orchestration (break reasoning into focused sub-tasks, each with a clean context) |
| Tennr | Multi-page medical documents with complex form structures | Vision-language model processes documents as images, avoiding text extraction information loss |
| Abridge | 15–60 minute clinical conversations with patient history | Streaming processing + EHR data injection + clinician profile conditioning |
| Glean | Enterprise knowledge spread across 100+ systems | Permission-aware RAG (retrieve only what the user can see, fit into context) |
| ElevenLabs | Conversational context across voice agent turns | Conversation state managed by the LLM layer, TTS is stateless per turn |
| Cursor | Repository-level understanding (100K+ files) | Codebase vector index with semantic + grep retrieval; 272K token limit is a hard constraint |
| Devin | Long-horizon tasks accumulating 100+ action observations | State summarization, hierarchical planning, sliding window with retrieval |
| Writer | Company knowledge + style rules + compliance rules + user prompt | Knowledge graph injection + style guide prompting + rule-based post-validation |

The next architectural shift will be **persistent context** — models that maintain state across sessions, accumulating knowledge rather than receiving it fresh each time. The companies building feedback loops are proto-persistent-context systems:
- Abridge's clinician profiles learn from edit patterns across sessions
- Cursor's Tab model improves from accepted completions across all users
- Devin's planning model improves from execution traces across all tasks
- Writer's knowledge graph accumulates organizational knowledge over time

These are persistence mechanisms that sit outside the model's context window but provide the effect of long-term memory. The model itself is stateless (each inference is independent), but the system around it (profiles, training data, knowledge graphs) is stateful.

## Domain Specificity vs Horizontal — The Real Decision

### When Vertical Beats General

| Company | Position | Why That Position |
|---------|----------|-------------------|
| Harvey | Deep vertical (legal) | RAG alone failed — legal reasoning requires model-level knowledge of case law, precedent, and argumentation |
| Tennr | Deep vertical (healthcare referrals) | 8,000 page types + payer-specific criteria + HIPAA = irreducible domain complexity that generic tools can't handle |
| Abridge | Deep vertical (clinical documentation) | Billing codes + doctor preferences + hospital rules + SOAP format = domain knowledge that can't be prompted into a generic model |
| Glean | Horizontal (enterprise search) | Value is in breadth (100+ integrations), not domain depth. Enterprise search is domain-agnostic. |
| ElevenLabs | Horizontal (voice API) | Voice synthesis is domain-agnostic — the same model serves audiobooks, customer support, gaming, and education |
| Cursor | Horizontal (developer tooling) | Code is a universal domain. Developer workflows are similar across industries. |
| Devin | Horizontal (developer tooling) | Same reasoning as Cursor, but autonomous rather than assistive |
| Writer | Horizontal with vertical deployment | Governance layer is domain-agnostic; customer-specific configuration makes it feel vertical |

### The Cost of Going Vertical

Going vertical requires:
1. **Proprietary training data** (Harvey's 10B case law tokens, Tennr's 4M medical documents, Abridge's clinical conversations). This data takes years and millions of interactions to accumulate. It can't be purchased — it must be collected through product usage.
2. **Domain-expert employees** (Harvey's BigLaw sales team, Abridge's physician CEO, Tennr's Stanford engineers doing healthcare LLM research). These people are rare and expensive.
3. **Regulatory compliance** (HIPAA for healthcare, attorney-client privilege for legal, financial regulations for fintech). Compliance infrastructure is domain-specific and expensive.
4. **TAM limitation.** Harvey can't sell to hospitals. Tennr can't sell to law firms. The addressable market is smaller, but the competitive intensity within it is lower.

### The Signal for When to Go Vertical

**Go vertical when domain error cost exceeds domain acquisition cost.**

In legal: a hallucinated citation is malpractice. The cost of a wrong answer ($millions in liability) exceeds the cost of building domain-specific AI ($tens of millions in R&D). So you go vertical.

In healthcare: a missed diagnosis mention or wrong billing code affects patient care and hospital revenue. The cost of errors exceeds the cost of specialization. So you go vertical.

In coding: a bad autocomplete is annoying. The developer catches it and fixes it. The cost of errors is low (developer time to fix). So you go horizontal — the breadth of the market justifies the lower accuracy per domain.

In enterprise search: a wrong search result is inconvenient. The user clicks the next result. The cost of errors is low. So you go horizontal.

The deeper principle: **vertical AI wins when the end user can't tolerate errors, and error reduction requires domain-specific knowledge that can't be achieved through prompting alone.** If domain accuracy can be achieved through better prompting or retrieval (without model-level changes), horizontal wins because it amortizes engineering cost across a larger market.

## The AI Integration Spectrum

Mapping all 8 companies on the spectrum from "AI as a feature" to "AI as the OS layer":

```
AI as Feature ←————————————————————————————————————————→ AI as OS Layer

Writer         Glean         Abridge        Harvey         Cursor         ElevenLabs      Devin
(governance    (search +     (clinical      (legal         (IDE where     (voice IS       (agent IS
 wraps AI;     AI answers;   workflow;      reasoning;     AI drives      the infra;      the dev;
 model is      model is      AI generates   custom model   every          developers      human
 swappable)    rented)       billable       + RAG;         interaction;   build ON        reviews
                             notes)         AI IS the      two inference  the voice)      at end)
                                            capability)    paths)
```

### Architectural Implications by Position

**AI as Feature (Writer):**
- The product is the governance layer; the AI is interchangeable
- Architecture: thin AI integration (API call to frontier model), thick control plane (style guide engine, knowledge graph, audit trail, workflow orchestration)
- Low model risk (can switch providers), high feature-competition risk (governance features can be replicated)
- Moat: customer configuration and organizational adoption, not technology

**AI as Product (Harvey, Tennr, Abridge):**
- The AI capability IS the value proposition. The product is "better legal research" or "better referral processing" or "better clinical notes" — and the AI is what makes it better.
- Architecture: deep model integration, domain-specific training, tight feedback loops between user behavior and model improvement
- High model risk (model quality = product quality), high switching cost (domain-specific data and integrations can't be easily replicated)
- Moat: domain-specific training data + integration with domain workflows

**AI as OS Layer (Cursor, ElevenLabs, Devin):**
- The AI is the platform that other experiences are built on. Cursor is not "VS Code with AI" — AI is the operating system of the editor. ElevenLabs is not "a TTS tool" — voice is the infrastructure layer.
- Architecture: multi-model routing, API-first design, platform extensibility, highest scale requirements
- Winner-take-most dynamics (developers choose one IDE, one voice API, one coding agent — switching costs compound with integration depth)
- Moat: user adoption + feedback flywheel + platform ecosystem

## Context Window as the New Database

### How These Companies Use Context Differently

**Harvey — Context as Deliberation Space:**
Multiple model calls combined into a single output. The context window is not a database lookup — it's a workspace where the model reasons about retrieved case law. Each call in the multi-call orchestration uses its own context for focused reasoning. The total "context" is distributed across calls, not crammed into one.

**Cursor — Tiered Context:**
Two completely different context regimes: Tab (narrow, fast, current file — 50ms budget) and Agent (broad, slow, codebase-wide retrieval — seconds budget). The 272K token limit is a hard constraint that shapes what the product can do. Explore subagents run in their own context windows to prevent main conversation bloating. Context is managed as a scarce resource, not an unlimited buffer.

**Devin — Context as Memory:**
Every action adds to context. The context window is the agent's working memory — it holds what the agent has done, what it's learned, what went wrong, and what to do next. On complex tasks (100+ actions), the context fills up, and the agent must summarize or drop older observations. Context management (what to remember, what to forget) directly determines the maximum complexity of tasks the agent can handle.

**Glean — Context as Security Boundary:**
The context window is filled only with permission-filtered chunks. The best answer might be in a chunk the user can't access — but it won't be in context. The context window is not just a capacity constraint; it's a security enforcement mechanism. Every token in the context is authorized for this specific user.

**Abridge — Context as Clinical Record:**
The context includes: the conversation transcript (what was said), patient history from the EHR (what's already known), clinician preferences (how the doctor documents), and hospital rules (what's required). Context is assembled from multiple structured sources and merged into a generation pipeline. It's more like a data warehouse join than a document retrieval.

**Writer — Context as Constraint Set:**
The context includes: knowledge graph facts (what's true about this company), style guide rules (what's allowed), compliance constraints (what's required), and the user prompt (what's requested). The context is not just information — it's constraints that bound the model's output. More constraints = more context consumed = less room for the actual generation.

### Where Inference Architecture Is Going

The context window is currently the primary bottleneck. Every company is building workarounds:
- Multi-call orchestration (Harvey) — distribute context across calls
- Tiered context (Cursor) — different sizes for different tasks
- Hierarchical planning (Devin) — summarize older context, keep recent context detailed
- Permission-aware filtering (Glean) — reduce available context to authorized subsets
- Knowledge graph injection (Writer) — inject precise structured facts, not verbose documents

The next architectural shift: **persistent context — models that maintain state across sessions.** Currently, every inference starts from scratch. The model has no memory of previous interactions. Companies build persistence outside the model (clinician profiles, training data, knowledge graphs), but the model itself is amnesiac.

When models gain native persistence (memory across conversations, accumulating knowledge from interactions), the architectures that currently manage "pseudo-persistence" (external feedback loops, profile systems, knowledge graphs) will need to be redesigned. The companies that have built clean abstractions between the model and the persistence layer will adapt faster. The companies that have tightly coupled their product to specific context management workarounds will struggle.

## The 6-Month Build

**If I had 4 senior engineers and 6 months, I'd build: a vertical AI agent for insurance claims processing.**

### Why This Vertical

The problem is structurally identical to what Tennr and Abridge solved:

- **Equivalent to "fax machine automation" (Tennr):** Insurance claims arrive as PDFs, scanned documents, emails, and portal submissions. They're processed manually by claims adjusters who extract structured data, apply policy rules, and make coverage determinations. The input is unstructured. The processing is rule-intensive. The output must go into a system of record.

- **Equivalent to "clinical note documentation" (Abridge):** The output must be accurate (wrong determination = lawsuit), compliant (regulatory requirements for claim handling), and formatted for the system of record (claims management system). Speed matters (faster claim processing = better customer experience + lower operational cost).

- **TAM:** Insurance claims processing is a multi-billion-dollar operational cost. The industry processes billions of claims annually. Labor costs for claims adjusters are the largest operational expense for most insurers.

- **The "fax equivalent":** Insurance forms, EOBs (Explanations of Benefits), medical records supporting claims, repair estimates, and incident reports — all heterogeneous document types requiring extraction and rule application.

### Day 1 Architecture

**Week 1–4: Document Processing Pipeline**
1. **Document ingestion layer:** Accept PDFs, scanned images, emails, and portal submissions. Use open-source OCR (Tesseract, PaddleOCR) for initial text extraction. Fine-tune an open-source VLM (Florence-2, Qwen-VL, or PaliGemma) on insurance document images for extraction where OCR fails.

2. **Document classification:** Start with 50 common claim document types (auto insurance claim form, homeowner's damage report, medical records, repair estimate, police report, etc.). Use the VLM for classification. Expand the taxonomy as new document types are encountered.

3. **Field extraction:** Extract structured fields: claimant name, policy number, date of loss, description of incident, claimed amount, supporting documentation type.

**Week 5–8: Policy Engine**
4. **Claims knowledge base:** Encode insurance policy rules as structured data. Start with 2–3 major personal lines products (auto, homeowner's, renter's). Rules include: coverage limits, deductible amounts, exclusions, required documentation, and state-specific regulations.

5. **Extraction + validation pipeline:** Match extracted claim data against policy rules. Identify: covered vs excluded items, documentation gaps, policy limit exceedances, and potential fraud indicators.

**Week 9–16: Integration and Workflow**
6. **Integration layer:** Connect to 2–3 major claims management systems (Guidewire, Duck Creek, or similar). This is the Abridge-equivalent EHR integration — the output must go into the system of record, not a standalone dashboard.

7. **Audit trail:** Every extraction, validation, and routing decision logged with full provenance. Claims decisions are subject to regulatory review — audit is mandatory, not optional.

8. **Adjuster workflow:** Present extracted data, policy evaluation, and recommendation to the claims adjuster. The adjuster reviews, adjusts, and approves — similar to Abridge's doctor review of the generated note.

**Week 17–24: Polish and Expansion**
9. **Feedback loops:** Adjuster corrections feed back into the extraction model and policy engine. Every approved claim is a training example.

10. **Analytics:** Claim processing time, accuracy metrics, coverage determination accuracy, common documentation gaps.

### What I'd Cut

- **Consumer-facing UI** (only claims adjusters use the system, not policyholders) — build for internal operations
- **Voice capabilities** (text-first; add voice for phone claim intake later)
- **Multi-language support** (English-only for 6 months)
- **Custom model training** (use fine-tuned open-source for MVP; invest in proprietary model after product-market fit)
- **All lines of business simultaneously** (start with personal auto insurance — highest volume, most standardized forms, clearest rules)

### The "Fax Machine Automation" Equivalent in Insurance

**EOB (Explanation of Benefits) processing for health insurance claims.** Every health insurance claim generates an EOB — a document that explains what was covered, what wasn't, and why. Processing EOBs is:
- Manual (adjusters read each EOB and enter data into the claims system)
- Error-prone (misreading an EOB can lead to wrong patient billing)
- High-volume (millions of EOBs per month at a large insurer)
- Rule-intensive (each EOB must be validated against the policy terms, network status, and regulatory requirements)

An AI that reads EOBs, extracts coverage determinations, validates against policy rules, and routes appeals automatically is the Tennr of insurance.

## The 10 Engineering Lessons That Cut Across All Companies

**1. Build the data pipeline before you need the AI.**
Glean had 100+ connectors before ChatGPT launched. When the LLM moment arrived, they pivoted in 6 weeks because the data infrastructure existed. If you're building in a domain that will eventually need AI (all domains), build the connectors, the data normalization, the permission models, and the indexes now. The data pipeline is a 2-year investment. The model is a 6-week integration. Build the 2-year thing first.

**2. Own the layer where your domain expertise matters most.**
Harvey owns the legal reasoning layer. Tennr owns the document understanding layer. Cursor owns the context assembly layer. Writer owns the governance layer. Glean owns the permission-aware retrieval layer. You don't need to build the base model. You need to own the layer above it where your unique value lives. Identify that layer — it's where your domain knowledge, your data, and your customer relationships intersect — and invest 80% of your engineering effort there.

**3. Treat permissions and compliance as architecture, not features.**
Glean bakes permissions into the index at the chunk level — not as a filter applied after retrieval. Writer makes audit trails the entire product. Abridge designed around HIPAA from day one. Cursor designed "never store source code" into the indexing pipeline architecture. Companies that add compliance as an afterthought spend 6–12 months redesigning when their first enterprise customer fails a security review. Companies that design for compliance from day one have a structural advantage that looks invisible but saves months of re-architecture.

**4. Don't ask users to change their behavior.**
Tennr reads the fax (doesn't replace it). Abridge works inside Epic (doesn't compete with it). Harvey integrates with Word and email (doesn't force a new interface). Glean searches existing tools (doesn't replace them). Cursor forks VS Code (doesn't ask developers to learn a new editor). Every successful company in this analysis meets users where they already work. The unsuccessful alternative — building a beautiful new interface and expecting behavior change — is the default failure mode of enterprise software and the graveyard of a thousand startups.

**5. Two inference paths, not one.**
Cursor's architecture is the template: fast/cheap/narrow (Tab completion, ~50ms, fine-tuned model, current file only) vs slow/expensive/broad (Chat/Agent, seconds, frontier model, codebase-wide retrieval). This decomposition applies universally. Every AI product has real-time and deliberative modes. Serving both from the same model/infrastructure is a latency and cost mistake. Design separate paths from day one — different models, different context strategies, different latency budgets.

**6. The feedback loop IS the moat.**
Harvey's 25,000 agents improve from lawyer feedback (edits to generated results). Cursor's Tab model improves from billions of accepted completions. Devin's planning model improves from successful execution traces. Abridge's clinician profiles improve from note edit patterns. Writer's knowledge graph accumulates organizational knowledge over time. In every case: usage data makes the product better, which drives more usage, which generates more data. If your product doesn't get better with use, you don't have a flywheel — you have a tool. Tools get replaced. Flywheels compound.

**7. Domain-specific training data is the real asset — start collecting it before you need it.**
Harvey's 10B case law tokens can't be purchased. Tennr's 4M medical documents and 2B checkbox labels can't be downloaded. Abridge's clinical conversations can't be scraped from the web. Devin's execution traces can't be synthesized. These datasets took years to accumulate, cost millions in processing, and represent the core competitive advantage of each company. If your competitive advantage will eventually require domain-specific data, start the collection pipeline on day one — even if your current model doesn't use it yet. By the time you need the data, it's too late to start collecting.

**8. The planning model is harder than the generation model.**
Devin's hardest problem is not writing code — it's deciding what to do next when the tests fail. Harvey's multi-call agent orchestration is harder to build than single-query inference. Abridge's Contextual Reasoning Engine (which figures out what's clinically significant, which billing codes apply, and how the doctor likes to document) is harder than transcription. Tennr's orchestration of classification → extraction → criteria application is harder than any single model call. In every case, the *reasoning about what to generate* is the harder engineering problem than the *generation itself*. Invest proportionally — planning, orchestration, and reasoning deserve more engineering attention than raw generation quality.

**9. Research translates to product only when the research team ships.**
ElevenLabs' Fourier-based vocoder became a cost advantage (lower inference cost → lower API price → more developer adoption). Their two-stage architecture became a quality advantage (ranked highest on TTS Arena V2). But these advantages exist because the research translated to production code, not just papers. Research that stays in papers is useless. Research that ships as lower inference cost, higher output quality, or new capabilities is a compounding advantage. The key organizational design: researchers who understand product constraints and ship code, not researchers who optimize for conference acceptances.

**10. The fastest companies share 4 traits: specific problem, existing model infrastructure, integration-first distribution, and founder domain expertise.**
- Harvey: securities litigator + DeepMind research scientist = litigator knows the problem, researcher knows the infrastructure
- Tennr: Stanford engineers doing LLM research in healthcare = domain knowledge + technical capability from the same founding team
- Abridge: physician + CMU speech researcher + CTO = clinical knowledge + AI research + engineering execution
- ElevenLabs: Polish founders who understood dubbed media = personal frustration with a specific problem + technical capability to solve it
- Cursor: researchers who were frustrated developers = users of the product they're building
- The pattern is **founder-domain-fit**, not founder-market-fit. You need founders who understand the problem domain at the atomic level, combined with engineers who understand the AI infrastructure deeply enough to build on it without building from scratch. The domain expert validates that the solution is actually useful (not just technically impressive). The AI expert validates that the architecture is sound (not just a demo). Both are required.

---

**The single sentence that captures everything in this analysis:**

The winning AI-native B2B companies are not model companies — they are integration companies that happen to use AI as the core capability, and their moats are built from three things no demo can replicate: domain-specific data accumulated over years, compliance architecture designed from day one, and the engineering that meets users exactly where they already work.

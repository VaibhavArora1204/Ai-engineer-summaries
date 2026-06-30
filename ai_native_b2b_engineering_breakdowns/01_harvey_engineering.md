# Harvey — Engineering Deep Dive

## 1. The One-Line Architectural Bet

**Custom-train a foundation model on 10 billion tokens of US case law in partnership with OpenAI, rather than bolting RAG onto a general-purpose LLM.**

Every architectural decision Harvey makes flows from this single bet. They looked at the standard industry approach — take a foundation model, build a retrieval layer over legal documents, and prompt-engineer your way to useful outputs — and said "this is insufficient for what lawyers actually need." The key insight came from the founding moment: Winston Weinberg, a securities litigator at O'Melveny & Myers, ran GPT-3 on 100 tenant law questions and had 3 attorneys evaluate the outputs. 86 out of 100 were approved. That's impressive for a general model, but 86% accuracy in legal work is dangerous — the 14% that fail can be the 14% that get you sanctioned by a judge or sued for malpractice.

The deeper insight, articulated directly by Weinberg: "If you just do retrieval, you can answer very simple questions about areas of law that you aren't really an expert in, but that's actually not that useful for most attorneys. With case law research, you're finding ammo for your argument, and that's much more difficult to do." This tells you the failure mode of plain RAG in legal: retrieval finds *relevant* cases, but lawyers need cases that *support a specific argumentative position*. That requires reasoning about holdings, distinguishing cases by facts, understanding procedural posture, and evaluating persuasive authority — none of which a retrieval layer provides. You need the model itself to understand law at a deep structural level.

So Harvey partnered with OpenAI (calling Sam Altman directly in 2022, when that was still possible) and built a custom-trained model starting with Delaware case law and expanding to all US case law — 10 billion tokens. The validation: side-by-side tests with 10 of the largest law firms showed 97% of lawyers preferred Harvey's custom model output vs GPT-4 for the same question. That 86% → 97% jump is the difference between "interesting demo" and "production-grade legal tool."

The trade they made: total vendor dependency on OpenAI's infrastructure in exchange for a model capability that no competitor can replicate without the same data + training partnership + 18 months of iteration.

## 2. Data Model

### Core Entities and Relationships

**Case** — The atomic unit of legal knowledge. A case contains: citation (the unique identifier in the legal system), jurisdiction (which court), date decided, holding (what the court decided), reasoning (why), procedural history (how it got to this court), parties, judges, and a rich network of citations to other cases. Cases cite each other, creating a directed graph of legal authority. This graph is the structure that makes legal reasoning different from general knowledge retrieval — a case's value depends on its position in the citation graph, not just its textual content.

**Agent** — Harvey's unit of AI workflow. There are 25,000+ custom agents deployed across clients. An agent is not a generic chatbot — it's a configured pipeline tuned for a specific legal task: contract review, due diligence, regulatory research, case law analysis for a specific practice area. Each agent likely encapsulates: a system prompt with task-specific instructions, retrieval parameters (which parts of the corpus to search), output format requirements (memo vs bullet points vs annotated citations), and quality thresholds. The agent abstraction is critical because it decouples model improvements from user experience — you can upgrade the underlying model without changing 25,000 agent configurations (in theory; in practice, model changes can subtly alter agent behavior).

**Firm/Client** — The organizational boundary. In BigLaw, data isolation is non-negotiable. Allen & Overy's work product cannot be visible to competitors. This means Harvey must implement strict multi-tenant isolation at the data level — firm-specific query history, firm-specific agent configurations, firm-specific feedback loops. The relationship between firm and agent is many-to-many: a firm has multiple agents for different practice areas, and some agent templates may be shared across firms (with firm-specific customization).

**Query** — A user's research request, enriched with context: practice area, jurisdiction, matter type, adversarial position (are we plaintiff or defendant?), key facts. The query is not just the text the lawyer types — it includes the metadata that shapes how the model should reason about the answer. A query about Delaware corporate law requires different reasoning than the same textual question applied to California employment law.

**Result** — The model's output, consisting of: synthesized legal analysis, cited cases (with specific holdings and relevance to the query), counter-arguments identified, confidence indicators, and links to full case text. The result is not just text — it's a structured document with traceable citations that a lawyer can verify and cite in their own work product.

### State Transitions

```
User Input → Query Enrichment (practice area, jurisdiction, context)
→ Agent Selection/Routing (which of the 25,000 agents handles this?)
→ Multi-Call Model Inference (multiple model invocations orchestrated by the agent)
→ Citation Verification (do all cited cases exist? are holdings accurately characterized?)
→ Result Assembly (synthesize multiple model outputs into coherent analysis)
→ Result Presentation (formatted for the specific output type: memo, brief section, research summary)
→ User Review (accept, edit, reject)
→ Feedback Capture (edits and acceptance become training signal)
```

### What's Stored Where

- **Case law corpus (10B tokens):** Server-side, pre-processed and tokenized for model training. Also indexed for retrieval (the custom model can reason about law generally, but specific case retrieval still requires an index for precision). This is Harvey's crown jewel data asset.
- **Agent configurations:** Server-side, per-firm and per-practice-area. Versioned (you need to know which agent configuration produced a given result for compliance and debugging).
- **Query-result pairs with user feedback:** Server-side, per-firm. This is the feedback flywheel — every time a lawyer edits a result, that edit is a training signal about what the model got wrong or what the lawyer prefers. Over 100,000 lawyers × thousands of queries each = massive feedback dataset.
- **Fine-tuning data and model weights:** Co-located with OpenAI infrastructure (Harvey's custom model is trained on OpenAI's platform).
- **User identity and access controls:** Server-side, integrated with firm's identity provider (likely SAML/SSO for BigLaw, which uniformly uses enterprise SSO).

### Ephemeral vs Persistent

Model inference state (the intermediate reasoning during a multi-call agent execution) is ephemeral. Query-result pairs with feedback are persistent and are the raw material for model improvement. Agent configurations are persistent and versioned. The case law corpus is persistent and growing (new cases are decided daily; Harvey must continuously ingest new case law to stay current). Audit logs of who queried what are persistent (BigLaw compliance requires knowing which associates worked on which matters).

## 3. Write Path / Read Path

### Write Path: User Creates a Legal Research Query

1. **Lawyer opens Harvey** — likely via browser (SaaS) or integrated within their existing tools (Harvey integrates into legal workflows; the source mentions this is important for adoption).

2. **Query formulation** — The lawyer types a question or selects a structured research task. The query is enriched with context: practice area (M&A, litigation, regulatory), jurisdiction (Delaware, SDNY, 9th Circuit), client matter context, and adversarial position. This enrichment is critical — the same legal question has different answers in different jurisdictions, and "finding ammo for your argument" requires knowing which side you're on.

3. **Agent routing** — The system selects the appropriate agent from the 25,000+ deployed. Routing logic: practice area + task type + firm-specific customization. A due diligence agent for an M&A team at Wachtell operates differently from a brief-drafting agent for a litigation team at Quinn Emanuel. The agent encapsulates the system prompt, retrieval parameters, and output format.

4. **Multi-call model inference** — This is where Harvey's architecture diverges from simple "send query to model, get response" systems. The agent orchestrates multiple model calls:
   - Call 1: Parse the legal question, identify the legal issues, determine which areas of law are relevant
   - Call 2: For each legal issue, retrieve relevant cases from the corpus and reason about their applicability
   - Call 3: Evaluate the strength of each case — does it support or undermine the client's position? Is it good law (not overruled)? Is it from a persuasive authority?
   - Call 4: Synthesize findings into a coherent analysis with structured citations
   
   This multi-call approach reduces prompt engineering burden on users (they ask a question, the agent breaks it down) and allows each call to focus on a specific reasoning task. The tradeoff: latency multiplies with each call, and errors in early calls propagate through later ones.

5. **Citation verification** — After the model generates its analysis, a verification layer checks every cited case:
   - Does this case exist in the corpus? (Hallucinated citations are the existential risk in legal AI)
   - Is the holding accurately characterized? (The model might cite a real case but misstate what it decided)
   - Is the case still good law? (Has it been overruled, distinguished, or limited by subsequent decisions?)
   - Is the citation format correct? (Bluebook citation format is standardized and lawyers notice errors)
   
   This verification layer is likely a combination of database lookups (does this citation match a real case?) and model-based checks (is this characterization of the holding consistent with the case text?).

6. **Result assembly and persistence** — The verified analysis is assembled into the requested output format and presented to the user. The result is persisted with full metadata: agent used, model version, all intermediate model calls, citations checked, timestamp, user identity.

7. **User review and feedback** — The lawyer reads the result, verifies key citations, edits as needed, and either uses it in their work product or discards it. Every edit is captured as a feedback signal: "the model said X, the lawyer changed it to Y" → this delta is training data for future model improvement.

### Read Path: Lawyer Retrieves Prior Research or Explores Case Law

1. **User enters a research query** — This hits Harvey Knowledge, the product targeting the eDiscovery market (43% of legal tech).

2. **Query analysis** — The system parses the query for legal entities (case names, statutes, regulatory bodies), concepts (fiduciary duty, proximate cause, material adverse change), and jurisdictional scope.

3. **Retrieval** — Against the 10B-token case law index, using hybrid search: keyword matching for specific case names/citations + semantic search for conceptual queries. The custom model's understanding of legal concepts means semantic search is more accurate than with a general-purpose embedding model.

4. **Argument-quality analysis** — This is Harvey's differentiator. The custom model evaluates each retrieved case not just for relevance but for argumentative value: How strong is this case for the user's position? What are the distinguishing facts? What counter-arguments does it expose? This is the "finding ammo for your argument" capability that RAG alone cannot provide.

5. **Result ranking and presentation** — Cases ranked by argumentative value, not just semantic similarity. Each case presented with: citation, holding, why it's relevant to the query, strength assessment, and potential counter-arguments. Opposing authority is flagged — good legal research acknowledges the best arguments against your position.

### Where Latency Lives

- **Multi-call model inference:** Each model call is 2–5 seconds. With 3–4 calls per agent execution, total inference time is 8–20 seconds. This is the dominant source of latency.
- **Citation verification:** Database lookups are fast (sub-second for existence checks), but semantic verification of holding accuracy adds 2–5 seconds per citation, and a typical result might cite 5–15 cases.
- **Agent orchestration overhead:** Routing, context assembly between calls, and result synthesis add 1–3 seconds.
- **Total estimated latency:** 15–40 seconds for a research query. Acceptable because the alternative is 30–60 minutes of manual research.

The latency tradeoff is explicit: Harvey chose multi-call orchestration (slower but more accurate and more thorough) over single-call inference (faster but less reliable). This is the right trade in legal — lawyers wait for quality, and they're already spending hours on research.

## 4. AI/ML Layer

### Models Used and Why

**Custom-trained model** built on OpenAI infrastructure, starting with Delaware case law corpus and expanding to all US case law (10 billion tokens). This is not just fine-tuning — the source material says "custom-trained model," which implies deeper modification than LoRA or standard fine-tuning. The partnership with OpenAI was the enabler: Harvey got early access to GPT-4 before public launch and a training partnership that let them modify model weights with their domain-specific corpus.

Why custom training vs fine-tuning vs prompting:
- **Prompting alone (prompt engineering over base GPT-4):** Insufficient for deep legal reasoning. The model can generate lawyer-sounding text but makes subtle errors in legal reasoning that a domain expert catches. The 86% accuracy in the original GPT-3 test would improve with GPT-4 + careful prompting, but not to the 97% threshold BigLaw demands.
- **Fine-tuning (LoRA/QLoRA over GPT-4):** Better, but fine-tuning primarily adjusts the model's output style and surface-level knowledge. Deep legal reasoning — understanding how precedent chains work, how courts distinguish cases, how statutory interpretation differs from common law reasoning — requires the knowledge to be in the model's weights, not just in the prompt or adapter layers.
- **Custom training (modifying base model weights with 10B tokens):** This embeds legal knowledge at the weight level, making legal reasoning a native capability rather than an emergent one from prompting. The 97% lawyer preference rate validates this approach.

Why OpenAI and not self-hosted:
- In 2022, training a custom model from scratch was prohibitively expensive without frontier lab infrastructure. OpenAI offered the training partnership through the Startup Fund ($5M seed).
- Early GPT-4 access gave Harvey a model quality advantage before competitors could even try the same approach.
- The trade: vendor lock-in to OpenAI. Harvey's custom model lives on OpenAI's infrastructure. If OpenAI raises prices, deprecates capabilities, or becomes a competitor (OpenAI for Legal), Harvey has limited options.

### Context Strategy

Hybrid: domain knowledge in model weights + RAG for specific case retrieval + multi-call orchestration for complex reasoning.

The model has legal knowledge baked in (from the 10B-token training), so it can reason about legal concepts without needing to retrieve background information. But for specific case retrieval — "find all 9th Circuit cases from the last 5 years on qualified immunity" — you still need a retrieval layer because the model can't memorize every case with perfect citation accuracy.

The multi-call agent architecture adds another context dimension: each model call can be focused on a specific sub-task, keeping the context window focused and reducing the risk of the model losing track of the original question during a long reasoning chain. This is a practical solution to the context window constraint: instead of stuffing everything into one giant prompt, decompose the task and give each sub-task a clean context.

### Latency / Quality / Cost Tradeoff

Quality is king. The explicit tradeoff:
- **Quality:** 97% lawyer preference rate, citation accuracy, argument-quality analysis. Non-negotiable in legal — an error is malpractice.
- **Latency:** 15–40 seconds per query. Acceptable because the alternative is manual research taking 30–60 minutes.
- **Cost:** Multi-call inference means 3–5x the inference cost of a single call. Plus citation verification. Plus the ongoing cost of the OpenAI training partnership. Harvey's ARR is $190M, so they can afford premium inference costs. At ~$200/user/month (estimated), the per-query cost is a small fraction of the value delivered (a single hour of BigLaw attorney time bills at $500–$1,500).

### Failure Modes

1. **Hallucinated citations** — The existential risk. A model-generated citation that doesn't correspond to a real case is career-ending for the lawyer who includes it in a filing. The citation verification layer is the safety net, but it has its own failure modes: it can catch citations that don't exist, but it's harder to catch citations that exist but are mischaracterized (the model cites the right case but misstates its holding).

2. **Jurisdiction confusion** — Delaware corporate law ≠ California corporate law ≠ English corporate law. The model must keep jurisdictional boundaries sharp. A case from a non-controlling jurisdiction cited as binding authority is a serious error. Harvey operates in 60 countries, which means the model must understand multiple legal systems — a much harder problem than just US case law.

3. **Temporal errors** — Law changes. A case that was good law in 2020 may have been overruled in 2023. The model's training data has a cutoff, and new case law must be continuously ingested. If the verification layer doesn't check whether cited cases are still good law, the model might confidently cite overruled authority.

4. **Argumentative bias** — "Finding ammo for your argument" means the model should favor cases supporting the client's position. But it must also identify strong counter-arguments (a good brief addresses opposing authority). If the model is too aggressive in cherry-picking favorable cases and ignoring negative authority, the lawyer's work product is weaker, not stronger.

5. **Agent configuration drift** — With 25,000 agents and a continuously evolving underlying model, agent behavior can shift in subtle ways after model updates. An agent that worked perfectly for Delaware chancery court research might produce slightly different outputs after a model version change. Testing 25,000 agents against model updates is a combinatorial explosion.

## 5. Critical Engineering Decisions & Tradeoffs

### What They Gave Up

**Vendor independence.** Harvey is deeply coupled to OpenAI's infrastructure for their custom model. This is not just API dependency — the model weights live on OpenAI's servers, the training pipeline uses OpenAI's tooling, and the ongoing model improvement depends on OpenAI's cooperation. If OpenAI:
- Raises inference pricing → Harvey's margins shrink
- Deprecates the model version Harvey trained on → Harvey must retrain
- Launches "OpenAI for Legal" as a competitor → Harvey faces existential competition from its own infrastructure provider
- Gets acquired or changes strategic direction → Harvey's roadmap is subject to another company's strategic decisions

The mitigation: Harvey's $190M ARR and $11B valuation give it leverage in the relationship. OpenAI benefits from Harvey as a showcase customer and revenue source. But the structural dependency remains.

### Technical Debt Accumulating

**Agent maintenance at scale.** 25,000 custom agents is not a product feature — it's a maintenance challenge. Each agent has firm-specific configurations, practice-area-specific prompts, and task-specific output formats. As the underlying model evolves:
- Agent behavior shifts (model v2 interprets the same system prompt differently than model v1)
- Agent quality must be re-validated (did the update make this agent better or worse?)
- Agent interactions compound (an agent that calls another agent amplifies version sensitivity)

The testing infrastructure required is significant: an evaluation harness that can run each agent against a set of benchmark queries, compare outputs across model versions, and flag regressions. This is equivalent to the test suite for a large software system — but instead of deterministic tests (function returns expected value), you're dealing with probabilistic evaluations (model output quality assessed by legal experts or automated quality scores).

Likely payoff timeline: 18–24 months before agent maintenance becomes a blocking engineering problem. The solution: invest in automated evaluation infrastructure, reduce per-agent customization where possible (shift from 25,000 unique agents to a smaller number of agent templates with firm-specific parameters), and build regression testing into the model update pipeline.

### The Decision Hardest to Undo

**The OpenAI training partnership.** The custom model weights live on OpenAI infrastructure. The training data was processed through OpenAI's pipeline. The ongoing model improvement depends on OpenAI's collaboration. Moving to a different model provider — Anthropic, Google, Mistral, or self-hosted open-source — means:
- Retraining the custom model from scratch (the 10B-token corpus must be re-processed through a different training pipeline)
- Re-validating all 25,000 agents against the new model (months of evaluation work)
- Potentially renegotiating data rights (who owns the model weights trained on Harvey's data?)
- 18+ months of migration before parity with the current system

This is the classic platform risk decision: the OpenAI partnership gave Harvey a massive head start (early GPT-4 access, custom training capability, credibility from OpenAI's endorsement), but the switching cost is measured in years, not months.

## 6. Privacy & Security Architecture

### Data Flow

```
Lawyer's query → Harvey client (browser/app)
→ [TLS] → Harvey's API servers
→ Query enrichment (add practice area, jurisdiction, context)
→ Agent routing
→ [Internal] → OpenAI custom model endpoint
→ Model inference (multiple calls per agent execution)
→ [Internal] → Citation verification against case law corpus
→ Result assembly
→ [TLS] → Harvey client
→ Rendered to lawyer
```

### Threat Model at Each Hop

**Client to Harvey servers:**
- Threat: Man-in-the-middle interception of legal queries. Legal queries contain privileged information — the nature of a client's legal problem, their litigation strategy, their vulnerabilities.
- Mitigation: TLS 1.3, certificate pinning, SOC 2 Type II compliance.
- Residual risk: Endpoint compromise on the lawyer's machine. Harvey can't control the client's security posture.

**Harvey servers to OpenAI:**
- Threat: Legal query content flows to OpenAI's infrastructure. OpenAI's employees could theoretically access query content. OpenAI's security breach would expose Harvey's customers' queries.
- Mitigation: Data processing agreement with OpenAI (no training on customer data, data retention limits, access controls). Harvey's custom model likely runs in a dedicated tenant or isolated compute environment.
- Residual risk: Trust dependency on OpenAI's security. Harvey cannot independently audit OpenAI's production infrastructure.

**Harvey's storage layer:**
- Threat: Breach of query-result database exposes privileged legal work product across multiple firms.
- Mitigation: Firm-level data isolation (separate databases or strict row-level security), encryption at rest, access audit logging.
- Residual risk: A breach of Harvey's infrastructure could expose multiple firms' data simultaneously — a systemic risk that BigLaw firms weigh heavily in vendor evaluation.

### Compliance Choices That Shaped Architecture

**Firm-level data isolation** is mandatory. BigLaw firms will not tolerate any risk of their data being visible to competitors. This drives multi-tenant architecture with strict isolation — either separate databases per firm or rigorous row-level security with audit logging. The Singapore judiciary deployment signals government-grade security, which likely means Harvey has passed compliance reviews equivalent to FedRAMP or similar frameworks.

**Attorney-client privilege** adds a unique dimension: unlike most SaaS data, legal work product is protected by privilege. A data breach doesn't just expose business information — it can waive privilege, which has legal consequences for Harvey's clients. This means Harvey's security posture must be demonstrably stronger than a typical SaaS vendor's, and their incident response must include legal analysis of privilege implications.

**SOC 2 Type II** is table stakes for BigLaw. More advanced firms may require SOC 2 Type II + additional controls specific to legal data handling. Harvey likely also maintains data processing agreements with specific provisions for legal privilege, data residency (EU firms may require EU-based processing), and data deletion (when an engagement ends, the firm may require that all related queries and results be deleted).

## 7. Latency Engineering

### Where the Latency Budget Is Spent

| Component | Estimated Latency | % of Total |
|-----------|------------------|------------|
| Query enrichment + agent routing | 200–500ms | 2–3% |
| Model inference (per call) | 2–5 seconds | — |
| Multi-call orchestration (3–5 calls) | 8–20 seconds | 50–65% |
| Citation verification (5–15 citations) | 3–10 seconds | 20–30% |
| Result assembly + formatting | 500ms–1 second | 3–5% |
| Network overhead | 200–500ms | 2–3% |
| **Total** | **15–40 seconds** | **100%** |

### P50/P90/P99 Targets

Source material doesn't provide specific latency targets. Reasoning from first principles:
- **P50:** 20 seconds (typical research query, 3–4 model calls, 5–8 citations to verify)
- **P90:** 35 seconds (complex queries requiring more model calls or more citation verification)
- **P99:** 60 seconds (edge cases: large context, many citations, model retries due to quality checks)
- **Acceptable ceiling:** 90 seconds. Beyond this, lawyers will lose patience even considering the alternative (30–60 minutes of manual research).

### What Breaks at 10x Scale

**Concurrent inference demand.** 100,000 lawyers × average 10 queries/day = 1M queries/day. At 10x: 10M queries/day, with thundering herd patterns during business hours (9am–6pm across time zones, with overlap creating peak periods). Each query requires 3–5 model inference calls, so the model endpoint must handle 30–50M inference calls per day.

OpenAI's inference capacity becomes the bottleneck. Harvey needs either:
- Reserved capacity guarantees (expensive, but ensures availability during peak)
- Multi-provider model routing (route some queries to a secondary model when OpenAI is at capacity — but this requires a second model with comparable quality, which undermines the custom model advantage)
- Query prioritization (urgent research for a filing deadline gets priority over background research)

**Citation verification throughput.** At 10M queries/day with average 10 citations each = 100M citation verifications/day. If verification involves both database lookups and semantic checks, this is a significant database and compute load. Solution: cache verification results (if a citation was verified yesterday and the case hasn't been overruled, skip re-verification) and batch verification requests.

## 8. The Product-Engineering Intersection

### Product Decision Forcing Hard Engineering Constraint

**"Finding ammo for your argument."** This product requirement is the reason plain RAG failed and custom model training was necessary. The distinction is subtle but architecturally profound:
- RAG retrieval finds cases that are *semantically relevant* to a query
- Argument-quality analysis evaluates which cases *support a specific legal position*

These are different tasks. Semantic relevance is a vector similarity problem. Argumentative support is a reasoning problem that requires understanding:
- The facts of the retrieved case vs the facts of the user's situation
- Whether the holding is broad or narrow
- Whether the court's reasoning applies to the user's jurisdiction
- Whether the case has been subsequently limited or distinguished

This reasoning cannot be achieved through retrieval alone — it requires the model to have internalized legal reasoning patterns through training. The product requirement ("find ammo") forced the engineering decision (custom model training), which forced the vendor partnership (OpenAI), which created the vendor dependency. One product insight cascaded into the defining architectural decision.

### Engineering Constraint Creating Product Feature

**Multi-call agent orchestration** was an engineering decision to improve accuracy (decompose complex queries into sub-tasks). But it became a product feature: "Harvey doesn't just answer your question — it researches it." The multi-call approach produces more thorough, more structured output than a single model call. What started as an accuracy improvement became the product experience of "AI that works like a junior associate doing proper research" rather than "AI that gives you a quick answer."

This also reduced prompt engineering burden on users: instead of requiring lawyers to craft perfect prompts (an unreasonable expectation for non-technical users), the agent decomposes a natural language question into structured research steps. The engineering architecture (multi-call) enabled the product simplicity (ask a question, get research).

### The "Looks Like Product but Is Actually Systems Design" Moment

**Hiring former BigLaw attorneys as salespeople.** This looks like a go-to-market decision: hire people who speak the buyer's language. But it's actually a data architecture decision. Domain-expert salespeople generate qualitatively different product feedback than generic enterprise sales reps:
- A BigLaw attorney seller notices when the model misstates a holding in a way a generic seller would miss
- They can articulate why a specific output format doesn't match how lawyers actually write memos
- They can identify practice areas where the model underperforms based on their own experience
- They can spec agent configurations that match real workflows

This feedback flows into agent design, model evaluation, and product prioritization. The sales team is part of the feedback loop, not just the distribution channel. The "hiring decision" is actually a decision about feedback quality — which directly impacts model and agent quality.

## 9. What a Well-Resourced Competitor Needs to Win

### The Actual Moat (Not the Marketing Version)

The moat is **layered**, not singular:

1. **The 10B-token case law training dataset and custom model weights.** A competitor can license case law data from Westlaw or LexisNexis, but replicating the training process (data cleaning, tokenization, training runs, evaluation, iteration) takes 12–18 months and requires a frontier lab partnership.

2. **The 25,000 agent configurations.** Each agent represents accumulated knowledge about how a specific legal task should be performed for a specific firm. A competitor starting today has zero agents — they must build each one through customer engagement and iteration.

3. **The feedback flywheel.** 100,000+ lawyers generating queries and editing results every day creates a continuous training signal. A competitor with fewer users generates less feedback, which means their model improves slower, which means they remain less accurate, which means they attract fewer users. This is the classic AI flywheel — and Harvey is 3+ years into spinning it.

4. **The trust relationships.** Getting BigLaw firms to trust AI with privileged work product took Harvey years of security reviews, pilot programs, and relationship building. Trust in legal is not transferable — a competitor must earn it independently with each firm.

### What Must Be Rebuilt vs What Can Be Bought

| Component | Build or Buy? | Time to Parity |
|-----------|--------------|----------------|
| Case law corpus | Buy (license from Westlaw/LexisNexis) | Weeks |
| Custom model training | Build (requires frontier lab partnership) | 12–18 months |
| Agent configurations | Build (requires customer feedback loops) | 18–24 months |
| BigLaw trust relationships | Build (no shortcut) | 2–3 years |
| Feedback flywheel data | Build (requires user base) | 3+ years |
| Citation verification system | Build (tractable engineering problem) | 3–6 months |

**The critical insight:** The technology components (model, agents, verification) are replicable given time and resources. The data assets (training corpus, feedback data) and relationship assets (BigLaw trust) are the true moats because they compound with time and cannot be purchased.

## 10. Steal This

### What You'd Take

**The agent abstraction.** Instead of exposing a model to users (here's a prompt box, figure it out), expose configured agents — each one tuned for a specific workflow with specific output formats and quality thresholds. This has several engineering benefits:
- **Decoupling:** Model improvements don't require UX changes. You can swap the model without touching the agent layer.
- **Customization:** Each customer's agents can be configured differently without forking the product.
- **Evaluation:** You can evaluate agent quality independently of model quality — the same model might perform differently under different agent configurations.
- **Scaling:** 25,000 agents is a product ecosystem, not just a feature. Each agent represents a solved workflow.

If building in any domain (not just legal), the agent pattern applies: instead of "use our AI," offer "use our AI for [specific task]" with pre-configured workflows.

### Mistake They Avoided

**Building a "legal chatbot."** The early legal AI companies (2016–2020) positioned as "AI that replaces legal research" — which triggered the "AI will replace lawyers" defensive reaction from the profession. Harvey positioned as "AI that augments legal work" — producing work-product-quality output that lawyers review and sign. This framing difference is not just marketing — it shaped the product architecture:
- "Replace lawyers" → build an end-to-end system that produces final outputs
- "Augment lawyers" → build a tool that produces drafts for lawyer review

The "augment" approach is architecturally easier (the lawyer catches errors), commercially easier (lawyers are not threatened), and practically more accurate (lawyer review is a quality gate).

### What I'd Do Differently

**Invest earlier in multi-model capability.** Being coupled to a single provider is a strategic risk that grows over time. I'd build an abstraction layer between the agent orchestration system and the model inference layer — so that any agent can be configured to use Harvey's custom model, GPT-4, Claude, Gemini, or a self-hosted model. This:
- Reduces vendor dependency risk
- Enables cost optimization (use cheaper models for simpler tasks)
- Enables quality optimization (use the best model for each task, regardless of provider)
- Future-proofs against the scenario where Anthropic or Google offers comparable legal fine-tuning

The reason Harvey likely hasn't done this: the custom model's quality advantage is so significant (97% preference) that no other model is a viable substitute for the core use case. But as frontier models improve and the quality gap narrows, multi-model routing becomes more important.

## 11. Raw Engineering Signals

- "If you just do retrieval, you can answer very simple questions about areas of law that you aren't really an expert in, but that's actually not that useful for most attorneys. With case law research, you're finding ammo for your argument, and that's much more difficult to do." — Winston Weinberg
- 86/100 GPT-3 answers approved by 3 attorneys in the initial test (2022)
- 97% of lawyers preferred custom model output vs GPT-4 in side-by-side tests with 10 of the largest law firms
- 10 billion tokens of US case law in the training corpus, starting with Delaware
- 25,000+ custom AI agents deployed across clients
- $190M ARR as of January 2026
- 100,000+ lawyers, 1,300+ customers, 60 countries
- Allen & Overy trial: 3,500 lawyers, 40,000 queries — the first BigLaw deployment at scale (November 2022)
- Singapore judiciary deployment (Small Claims Tribunals) — public sector signals compliance maturity
- 43% of legal tech market is eDiscovery — Harvey Knowledge product targets this directly
- Seed: $5M, OpenAI Startup Fund (November 2022)
- $11B valuation in under 4 years (March 2026)
- Sequoia led 3 of Harvey's funding rounds — "the ultimate sign of conviction" from the most brand-conscious VC firm
- Founded by a securities litigator (Weinberg) + a Google DeepMind/Meta research scientist (Pereyra) — the domain expert + AI expert combination that appears across multiple companies in this analysis

---

**The single most important thing I'd tell a team building in legal AI:** RAG is not enough for domains where the user needs the system to *reason* about retrieved information, not just *retrieve* it. Legal research is not search — it's argumentation. If your system finds relevant cases but can't evaluate their argumentative value, you've built a faster version of what lawyers already have (Westlaw, LexisNexis), not a better one. The 97% preference rate came from a model that can reason about law, not just retrieve it. That's the accuracy gap that matters, and it requires domain-specific model training — not just a better prompt.

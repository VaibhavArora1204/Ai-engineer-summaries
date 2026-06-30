# Tennr — Engineering Deep Dive

## 1. The One-Line Architectural Bet

**Build a proprietary vision-language model (RaeLM) that reads unstructured medical documents — faxes, scanned PDFs, handwritten forms — and extracts structured data against payer-specific criteria, rather than trying to eliminate the fax.**

This bet is a refusal to fight the industry's entrenched behavior. Healthcare sends 9 billion faxes a year. The HITECH Act in 2009 put $27 billion toward EHR adoption. Fifteen years later: everyone has EHRs, and everyone still defaults to fax for referrals. Every previous startup that tried to replace the fax failed — not because their technology was wrong, but because they asked healthcare providers to change how they work. As IVP partner Zeya Yang put it: "Forcing healthcare providers to change the way they refer their patients doesn't work. Many have tried."

Tennr's founders (Trey Holterman, Diego Baugh, Tyler Johnson — Stanford engineering students doing LLM research) understood that the fax is not a technology problem. It's a behavior problem with regulatory and workflow roots. The fax persists because:
1. Providers have workflows built around fax for decades
2. Fax meets HIPAA requirements for point-to-point transmission (simpler compliance than email)
3. Fax works between any two healthcare entities regardless of their EHR system
4. Retraining staff on new referral methods has a real cost that exceeds the cost of continuing to fax

So Tennr made the architectural bet: don't fight the input. Accept faxes, scanned PDFs, emails, and portal submissions as they arrive. Apply AI *after* the document lands. Convert unstructured input to structured, actionable data. Integrate the structured output into existing EHR systems. The provider's behavior doesn't change. The operations team's workload drops dramatically. The referral conversion rate goes from 80% to 85% in the first month.

## 2. Data Model

### Core Entities and Relationships

**Document** — An inbound medical document in any format: fax, email attachment, e-portal submission, or on-prem file system pickup. Each document is classified into one of 8,000+ page types. The page type taxonomy is the critical data asset — it represents Tennr's accumulated understanding of the full diversity of medical document formats across payers, states, and provider types. A "Blue Cross Blue Shield of Texas Prior Authorization Request for Cardiovascular Surgery" is a different page type from "Aetna Referral Form for Physical Therapy in California." The granularity of the taxonomy determines extraction accuracy.

**Patient** — Extracted from the document and linked to existing records in the receiving provider's EHR. Patient identity resolution is a non-trivial sub-problem: the same patient might appear as "John Smith, DOB 01/15/1980" on the fax and "Jonathan A. Smith, DOB 1/15/80" in the EHR. Name matching, DOB matching, and insurance ID matching are all required for confident linkage.

**Referral** — The atomic unit of Tennr's business. A referral is a request from a referring provider (primary care doctor, ER, another specialist) to a receiving provider (specialist, treatment center, diagnostic facility) for patient care. A referral has a lifecycle: received → classified → data extracted → eligibility checked → payer criteria applied → denial risk assessed → routed → prior authorization initiated (if required) → resolved (approved/denied). Each stage has failure modes, and Tennr's value is in automating each stage with higher accuracy than human data entry.

**Payer Criteria** — Insurance-specific rules that determine whether a referral will be approved. This is the knowledge base that makes Tennr's problem AI-hard. Payer criteria vary along at least 4 dimensions:
1. **Insurance company:** United Healthcare has different criteria than Blue Cross than Aetna
2. **State:** The same insurer has different criteria in Texas vs New York
3. **Service type:** Criteria for cardiology differ from criteria for physical therapy
4. **Plan type:** A PPO plan has different requirements than an HMO
The cross-product of these dimensions creates thousands of distinct rule sets that must be maintained, updated, and applied accurately.

**Authorization** — The outcome of the payer criteria evaluation: approved, denied, or pending with a reason. If denied, the denial reason must be specific enough for the receiving provider to appeal or request additional documentation. The authorization entity tracks the full chain: which criteria were applied, what evidence was found in the document, what was missing, and what the recommended next action is.

**Provider** — Both referring and receiving, with separate data models. The referring provider needs visibility into what happened after they sent the referral (solving the "black hole" problem where referrals disappear). The receiving provider needs the extracted data routed into their workflow. These are different integration challenges — the receiving provider's EHR must be written to; the referring provider's system must be read-updated.

### State Transitions

```
Document Received (fax/email/portal)
→ Image Preprocessing (de-skew, normalize, enhance)
→ Document Classification (which of 8,000+ page types?)
→ Field Extraction (patient info, clinical context, ordering provider, diagnosis codes)
→ Patient Identity Resolution (link to existing EHR records)
→ Eligibility Check (is this patient covered? what are their benefits?)
→ Payer Criteria Application (does the clinical context meet the payer's requirements?)
→ Denial Risk Scoring (probability of denial, with specific missing criteria flagged)
→ Routing (to appropriate workflow queue: standard, urgent, needs-more-info, likely-denial)
→ Prior Authorization Initiation (if required by payer)
→ Status Sync (update referring provider, receiving provider, and patient)
→ Resolution (authorized / denied / pending)
→ Feedback Loop (outcome feeds back into model training and criteria validation)
```

### What's Stored Where

- **Raw documents:** Server-side object storage (S3 or equivalent), encrypted at rest. Raw documents must be retained for compliance — if a denial is appealed, the original document is evidence.
- **Extracted structured data:** Server-side database, linked to patient and referral records. This is the primary operational data store.
- **RaeLM model weights:** Server-side, proprietary, versioned. Not exposed to customers.
- **Payer criteria knowledge base:** Server-side, maintained per payer per state per service type. This is a living dataset that must be updated as insurance companies change their rules — which they do frequently and without standardized notification.
- **EHR integration state:** Maintained via connectors to customer EHR systems (both modern APIs and legacy interfaces — HL7v2, FHIR, custom APIs, even file-based integrations for the oldest systems).
- **Document classification taxonomy (8,000+ types):** Server-side, continuously expanded as new document types are encountered.

### Ephemeral vs Persistent

- **OCR/extraction intermediate outputs** (e.g., bounding boxes, confidence scores per field): ephemeral during processing, though may be logged for debugging and model improvement.
- **Extracted structured data:** Persistent — this is the operational output that flows into provider workflows.
- **Authorization outcomes:** Persistent — required for billing, appeals, and audit.
- **Model inference state:** Ephemeral.
- **The 230 million extracted data fields and 2 billion checkboxes:** Persistent training data — the accumulated result of processing millions of documents. This is Tennr's primary data asset.

## 3. Write Path / Read Path

### Write Path: Fax Arrives, Gets Processed

1. **Document ingestion** — Fax/email/e-portal submission hits Tennr's ingestion layer. Tennr integrates with: fax providers (cloud fax services), on-prem file storage systems, and EHR submission portals. The integration must handle the full diversity of input channels because healthcare organizations use all of them simultaneously. A single specialty practice might receive referrals via RightFax (on-prem), email, and a web portal — Tennr must watch all three.

2. **Image preprocessing** — Fax quality is genuinely terrible. Documents may be rotated, skewed, low-resolution (200 DPI is common for fax), partially illegible, or multi-page with mixed page types in a single transmission. Preprocessing includes: rotation correction, de-skewing, resolution enhancement (super-resolution models or interpolation), contrast normalization, and page splitting (a 15-page fax might contain 3 different documents). This step is critical because downstream model accuracy depends heavily on image quality.

3. **Document classification** — RaeLM classifies each page into one of 8,000+ page types. This is a multi-class classification problem with an extremely long tail — common form types (standard referral forms from major insurers) might represent 20% of volume but only 5% of the taxonomy. The remaining 95% of page types are rare, specialized forms that the model must still handle. Classification accuracy directly determines extraction accuracy — if the model thinks it's looking at a Blue Cross referral form but it's actually a Cigna prior authorization form, it will look for the wrong fields in the wrong locations.

4. **Field extraction** — RaeLM extracts structured fields from the classified document: patient demographics (name, DOB, insurance ID, contact info), clinical context (diagnosis, symptoms, treatment history, current medications), ordering/referring provider (name, NPI number, practice info), and procedure-specific information (requested service, CPT codes, clinical justification). The extraction must handle:
   - **Printed text:** Standard OCR → field mapping
   - **Handwritten text:** Significantly harder — handwriting recognition in medical documents is a known AI challenge (doctor handwriting is legendarily illegible)
   - **Checkboxes:** 2 billion checkboxes in the training data tells you how prevalent checkbox-heavy forms are in insurance documentation. A checked box vs an unchecked box vs an X vs a circle can be ambiguous.
   - **Mixed formats:** A single page might have printed headers, handwritten notes, checkboxes, stamps, and signatures — all of which the model must parse.

5. **Patient identity resolution** — Extracted patient data is matched against the receiving provider's existing patient records. This is a fuzzy matching problem: the fax says "Robert Johnson" and the EHR has "Bob Johnson" — are they the same person? Resolution uses: name similarity, date of birth, insurance ID, address, and phone number. False positives (merging two different patients) are dangerous; false negatives (creating a duplicate record) are inconvenient but less harmful.

6. **Eligibility and benefits check** — Extracted patient insurance information is sent to the payer's eligibility API (via EDI 270/271 or proprietary payer APIs). This returns: is the patient currently covered? What benefits do they have for this service type? What is their copay/coinsurance/deductible status? Eligibility checks are real-time but depend on external payer APIs — latency is outside Tennr's control (typically 2–10 seconds, but some payers are slower).

7. **Payer criteria application** — This is where Tennr's domain expertise becomes essential. The engine takes the extracted clinical context and applies the specific payer's criteria for this service type in this state. For example: "Does this patient's clinical history meet Blue Cross of Texas's criteria for authorization of cardiac catheterization?" The criteria might require: specific diagnosis codes, documented failed conservative treatment, recent lab results within specific ranges, and referring physician attestation. The engine checks each criterion against the extracted data and flags what's met, what's missing, and what's ambiguous.

8. **Denial risk scoring** — Based on the criteria evaluation, the system produces a denial risk score. High-risk referrals (likely to be denied due to missing clinical documentation) are flagged for the operations team to address proactively — requesting additional information from the referring provider before submitting the authorization, rather than waiting for a denial and then appealing. This proactive approach is a significant value driver: denied authorizations cost providers revenue and cost patients treatment delays.

9. **Routing** — The processed referral is routed to the appropriate workflow queue in the receiving provider's system:
   - **Clean referrals** (all criteria met, low denial risk): auto-processed, provider notified
   - **Needs attention** (some criteria met, some missing): routed to operations for review and follow-up
   - **High denial risk** (criteria not met, missing documentation): escalated with specific action items
   - **Urgent/stat referrals** (clinical urgency indicated): priority routing

10. **Prior authorization initiation** — If the payer requires prior authorization for this service, Tennr initiates the authorization process: submitting the clinical documentation to the payer via their required channel (fax, portal, EDI 278), with all required fields populated from the extracted data. This is often a fax *back* to the insurance company — the irony of the healthcare system.

11. **Status synchronization** — Throughout the process, status updates are pushed to:
    - The receiving provider (via EHR integration)
    - The referring provider (solving the "black hole" problem)
    - The patient (if the provider has patient communication enabled)
    This bi-directional communication is the product feature that closes the referral loop — the referring doctor knows their patient was received, the patient knows their appointment is being scheduled.

### Read Path: Provider Checks Referral Status

1. Provider queries referral status via Tennr dashboard or EHR integration
2. System returns current state: where in the pipeline the referral is, what's complete, what's pending
3. If denied: specific denial reason, missing documentation, recommended next action (appeal template, additional documentation request)
4. Historical analytics: referral conversion rates, average time-to-authorization, denial rates by payer, common reasons for denial — this operational data helps providers optimize their referral processes

### Where Latency Lives

- **Image preprocessing:** 1–5 seconds per page (depends on image quality and number of corrections needed)
- **Document classification:** 500ms–2 seconds (RaeLM inference on the document image)
- **Field extraction:** 2–10 seconds per page (depends on document complexity — a simple referral form vs a 10-page clinical summary)
- **Eligibility check:** 2–10 seconds (external payer API, outside Tennr's control)
- **Payer criteria application:** 500ms–2 seconds (rule engine, not model inference — fast)
- **Total per document:** 10–30 seconds for a typical single-page referral. Multi-page documents scale linearly.
- **Context:** The alternative is 15–30 minutes of human data entry per referral. Even at 30 seconds, Tennr is 30–60x faster.

## 4. AI/ML Layer

### Models Used and Why

**RaeLM** (formerly RaeLLM 7B): proprietary vision-language model. The name tells you about its heritage — "LLM" in the original name indicates it started as a language model architecture that was extended with vision capabilities. The 7B parameter count is a deliberate engineering choice:

- **Why not larger (70B, 175B)?** At 10 million documents per month, inference cost scales linearly with model size. A 70B model is 10x the cost per document. For a problem where the model processes millions of documents (not one-off queries from human users), compute efficiency matters enormously. A 7B model trained on domain-specific data can outperform a 70B general model on the specific task.

- **Why not smaller (1B, 3B)?** Document understanding requires handling the full diversity of medical documents — 8,000+ page types, handwritten text, degraded fax quality, complex form layouts. A 1B model likely lacks the capacity to maintain accuracy across this diversity. 7B is the sweet spot: large enough for the task diversity, small enough for cost-efficient serving at millions of documents per month.

- **Why proprietary vs open-source VLM?** Generic VLMs (GPT-4V, Claude's vision, LLaVA, Florence) can read documents but cannot reliably apply payer-specific criteria to unstructured medical forms. The training data is the differentiator: 4 million medical documents, 230 million data fields, 8,000 page classifications, 2 billion checkboxes. No open-source model has been trained on this domain-specific data at this scale. Additionally, sending PHI to a third-party model API adds a HIPAA compliance hop that healthcare organizations resist.

### Architecture: Orchestration Engine + Specialized Models

The source material describes an "enterprise orchestration engine + series of specialized language models." This is not a single monolithic model — it's an ensemble architecture:

- **Classification model:** Identifies document type from 8,000+ classes. Likely a vision classifier (could be a fine-tuned ViT or similar) that outputs a document type label.
- **Extraction model(s):** Given a classified document type, extracts structured fields. May be specialized by document category (insurance forms, clinical notes, lab reports) or by extraction type (text fields, checkboxes, tables, handwritten notes).
- **Orchestration engine:** Routes documents through the appropriate model pipeline based on classification results, manages the flow from ingestion to EHR integration, handles retries and error cases.

This ensemble approach has advantages over a single model:
- Each specialized model can be trained, evaluated, and updated independently
- Failure in one model (misclassification) is isolated from other models (extraction accuracy on correctly classified documents is unaffected)
- Different models can have different latency and accuracy characteristics (classification can be fast and high-recall; extraction can be slower and high-precision)

### Training Data

The scale of the training data is the primary technical moat:
- **4 million medical documents:** Spanning the diversity of referral types, payer forms, clinical summaries, lab reports, and imaging orders across US healthcare
- **230 million extracted data fields:** Supervised labels for the extraction model. Each field is a training example: (document image region, field type, extracted value). At 230M examples, the extraction model has seen enormous diversity.
- **8,000 page classifications:** Supervised labels for the classification model. Each new page type added to the taxonomy is a model improvement that makes Tennr more capable.
- **2 billion checkboxes:** This number is remarkable. It tells you that Tennr's training data is heavily weighted toward insurance forms (which are checkbox-intensive). Checkbox detection and state classification (checked, unchecked, X'd, circled, ambiguous) is a specific sub-task that benefits from massive training data.

### Fine-tuning vs Prompting vs Retrieval

**Fine-tuning dominates.** This is not a system where you can prompt a general-purpose VLM to extract data reliably. The reasons:

1. **Positional understanding:** Medical forms have specific field layouts that vary by form type. The model must learn that "Patient Name" on form type A is in the top-left corner, but on form type B it's in the middle of the page. This is learned through supervised training, not prompting.

2. **Handwriting recognition:** Prompting a VLM to read doctor handwriting is unreliable. Fine-tuning on millions of handwritten medical notes produces a model that handles the specific characteristics of medical handwriting (abbreviations, symbols, illegible passages).

3. **Checkbox semantics:** A checkbox that's checked vs one that has an X through it vs one that's circled vs one that's blank — these distinctions matter for insurance criteria. The 2 billion checkbox training examples teach the model these distinctions.

4. **Payer-specific patterns:** The model must learn that the same clinical information is presented differently on different payer forms, and that different payers require different information. This is not knowledge that can be injected via prompting — it requires training on thousands of examples from each payer.

### Failure Modes

1. **Document misclassification** — If the model classifies a Cigna prior authorization form as a Blue Cross referral form, every subsequent extraction will look for the wrong fields. The failure cascades: wrong fields extracted → wrong eligibility check → wrong criteria applied → wrong denial risk assessment. Misclassification is most likely for rare form types (low training examples) and for forms that share similar layouts across payers.

2. **Extraction errors on degraded scans** — Fax quality is the single biggest source of extraction errors. A fax that's been through multiple generations (faxed from one machine, printed, faxed again) can be nearly illegible. The preprocessing step helps, but some documents are simply too degraded for reliable extraction. The system must have a confidence threshold below which it routes the document for human review rather than trusting the extraction.

3. **Payer criteria drift** — Insurance companies change their authorization criteria. Sometimes they publish updates; sometimes they change quietly. The payer criteria knowledge base must be continuously maintained. If criteria are outdated, the system may approve a referral that the payer will deny (false negative on denial risk) or flag a referral as high-risk when it would actually be approved (false positive, creating unnecessary work for the operations team).

4. **Patient identity resolution errors** — Merging two different patients (false positive match) can lead to wrong clinical context being applied, potentially causing a denial or, worse, patient safety issues. Creating a duplicate patient record (false negative) creates administrative burden but is safer.

5. **The most dangerous failure:** A false negative on denial risk — the system says "this referral is fine" but the payer denies it. The provider proceeds with the referral, schedules the patient, potentially performs a procedure, and then discovers the authorization was denied. This can cost thousands of dollars and delay patient care. The denial risk scoring must be calibrated to err on the side of flagging (higher sensitivity at the cost of more false positives).

## 5. Critical Engineering Decisions & Tradeoffs

### What They Gave Up

**User interface polish and end-user visibility.** Tennr's product is fundamentally invisible to the end users of healthcare — patients never see it, and most providers interact with it only through their existing EHR. They traded consumer-grade UX for deep integration with legacy systems (fax servers, on-prem file storage, 1990s EHRs). This is architecturally correct: their users are operations staff who care about throughput, accuracy, and FTE reduction — not design aesthetics.

But the deeper trade is: **Tennr does not own the user relationship at the point of care.** They are middleware. Their value is entirely dependent on being integrated into the provider's existing workflow. If the provider changes their EHR or their workflow, Tennr must re-integrate. This middleware position is both a strength (easy adoption, no behavior change) and a vulnerability (if the EHR vendor builds native document processing, Tennr can be disintermediated).

### Technical Debt Accumulating

**The 8,000 page classification taxonomy is growing without bound.** Every new payer, state, service type, or form revision adds edge cases. The taxonomy is a long-tail problem:
- The top 100 page types might represent 60% of document volume
- The next 900 page types represent 30%
- The remaining 7,000 page types represent 10% of volume but require 70% of the taxonomy maintenance effort

Each new page type requires: labeling training data, adding to the classification model, building extraction templates, and validating accuracy. This never stops — as long as healthcare payers create new forms (which they do annually), the taxonomy grows.

This is the kind of technical debt that is also the moat: a competitor starting today must build a taxonomy of 8,000+ page types and label training data for each. Tennr has been doing this for 4+ years with 10 million documents per month flowing through the system. The debt is real (maintenance cost grows with taxonomy size), but the cost of the debt is the cost of the moat.

### The Decision Hardest to Undo

**Building a proprietary VLM instead of using or fine-tuning an existing model.** Full ownership of RaeLM means:
- Full control of model architecture, training, and deployment
- No vendor dependency for the core AI capability
- Full ownership of the training data pipeline
- No HIPAA compliance hop to a third-party model API

But it also means:
- Full responsibility for model infrastructure (GPU clusters, training pipelines, serving infrastructure)
- Full responsibility for model improvement (no free upgrades from a frontier lab)
- Full R&D cost (researchers, compute, evaluation infrastructure)
- Harder to benefit from general VLM improvements (when GPT-5V or Claude's next vision model is released, Tennr doesn't automatically benefit)

This decision is hardest to undo because the entire system — training pipelines, evaluation harnesses, serving infrastructure, deployment processes — is built around the proprietary model. Switching to a fine-tuned open-source model or a third-party API would require rebuilding the inference layer and revalidating accuracy across 8,000 page types. The migration risk is high and the timeline is 6–12 months.

## 6. Privacy & Security Architecture

### Data Flow

```
Fax server / email server / e-portal
→ [Various protocols: T.38, SMTP, HTTPS] → Tennr ingestion layer
→ Image preprocessing (server-side)
→ RaeLM processing (server-side, proprietary model — no third-party API call)
→ Structured data output
→ Eligibility check (outbound to payer API via EDI 270/271)
→ EHR integration (HL7v2, FHIR, or proprietary API depending on EHR system)
→ Status sync (to referring provider and patient)
```

### Threat Model at Each Hop

**Fax ingestion:**
- Fax protocols (T.30, T.38) have no encryption by default. A fax in transit is unencrypted. This is a known HIPAA risk that the entire healthcare industry accepts because the alternative (replacing fax) hasn't worked.
- Tennr must secure PHI from the moment it hits their systems. The transition from unencrypted fax to encrypted storage is a critical security boundary.
- For email and portal ingestion: TLS in transit, encryption at rest.

**Tennr processing:**
- PHI flows through every stage of the pipeline: document images contain patient names, DOBs, diagnoses, insurance IDs.
- The proprietary model (RaeLM) processes PHI on Tennr's own infrastructure — no PHI leaves Tennr's security boundary for model inference. This is a significant compliance advantage over systems that send PHI to a third-party API.
- All processing must be auditable: which documents were processed, what data was extracted, what decisions were made.

**Payer API communication:**
- Eligibility checks require sending patient insurance information to payer APIs. These are standard healthcare data exchanges (EDI 270/271) with established security protocols.
- Tennr must maintain secure connections to each payer's eligibility service — which may number in the hundreds (each major insurer has its own API, and some states have clearinghouse intermediaries).

**EHR integration:**
- On-prem connectors mean Tennr's code runs inside customer networks. This requires passing healthcare organization security reviews (which are extensive) and may require on-prem deployment of connector components.
- Cloud-based EHR integrations (Epic on Azure, Cerner on AWS) use API-based connections with OAuth or SMART on FHIR authentication.

### Compliance Choices Shaping Architecture

**HIPAA drives every architectural decision.** Business Associate Agreements (BAAs) with every entity in the data flow chain. Encryption at rest and in transit. Access logging. Minimum necessary data exposure (extract and transmit only the data fields needed, not the entire document). Data retention policies per healthcare organization. Breach notification procedures.

The decision to build a proprietary VLM (rather than using a third-party model API) was partly compliance-driven. Sending PHI to OpenAI or Google requires a BAA with that vendor, adds a compliance hop, and creates a data residency concern. By keeping all PHI processing within Tennr's security boundary, they simplified the compliance picture for their customers: "your data never leaves our infrastructure for model processing."

## 7. Latency Engineering

### Where the Latency Budget Is Spent

| Component | Estimated Latency | Notes |
|-----------|------------------|-------|
| Document ingestion | 1–5 seconds | Depends on input channel (fax is slower than email) |
| Image preprocessing | 1–5 seconds/page | De-skewing, enhancement, page splitting |
| Document classification | 500ms–2 seconds | RaeLM classification inference |
| Field extraction | 2–10 seconds/page | Depends on document complexity |
| Patient identity resolution | 500ms–2 seconds | Database matching |
| Eligibility check | 2–10 seconds | External payer API (outside Tennr's control) |
| Payer criteria application | 500ms–2 seconds | Rule engine, not model inference |
| Routing + status update | 500ms–1 second | Internal routing and EHR write |
| **Total (single page)** | **10–30 seconds** | |
| **Total (complex multi-page)** | **30–120 seconds** | Linear scaling with page count |

### P50/P90/P99

Source material doesn't provide specific targets. Reasoning from first principles:
- **P50:** 15 seconds for a single-page standard referral form
- **P90:** 45 seconds for a multi-page referral with complex clinical documentation
- **P99:** 2–3 minutes for edge cases: degraded fax quality requiring multiple preprocessing attempts, rare page types requiring fallback to human review, payer API timeouts
- **Acceptable ceiling:** 5 minutes per document. The alternative is 15–30 minutes of human data entry.

### What Breaks at 10x Scale

**10M documents/month → 100M documents/month** requires:

1. **10x GPU capacity for RaeLM inference.** At 7B parameters, serving 100M documents/month (3.3M/day, 140K/hour, 2,300/minute) requires a fleet of GPU instances. The model can likely be served on A100 or H100 GPUs with batched inference — 7B parameters is small enough for efficient serving, but the volume is the challenge.

2. **Payer API rate limits.** Eligibility check APIs from major payers have rate limits. At 10x volume, Tennr hits these limits and must negotiate higher quotas or implement intelligent rate-limiting with backpressure (slow down ingestion when payer APIs are throttled).

3. **EHR write throughput.** Pushing extracted data into customer EHR systems at 10x volume may hit API rate limits or database write limits on the EHR side. Particularly for on-prem EHR deployments with limited infrastructure.

4. **Payer criteria knowledge base maintenance.** More volume means more exposure to rare payer + state + service type combinations, which means more criteria gaps discovered. The knowledge base maintenance team must scale proportionally — or the criteria engine must learn to infer criteria from patterns rather than requiring explicit rules.

5. **Document classification at the long tail.** At 10x volume, the long tail becomes longer. More rare document types are encountered. The classification model needs continuous retraining to handle new page types. The 8,000+ taxonomy may need to grow to 20,000+ to maintain accuracy.

## 8. The Product-Engineering Intersection

### Product Decision Forcing Hard Engineering Constraint

**"Work with the fax, not against it."** This product philosophy forced the construction of a vision-language model rather than a text-based system. If Tennr had required providers to submit referrals through a digital form (like every previous failed startup), they could have used a text-only LLM for processing. But because they accept faxes, they must process images. And because fax quality is terrible, they must handle:
- Low-resolution images (200 DPI)
- Skewed and rotated pages
- Handwritten annotations
- Smudged or partially illegible text
- Multi-generation fax artifacts (moiré patterns, contrast loss)

This forced the VLM approach: a model that processes the document as a visual input rather than relying on OCR → text → LLM (which loses layout information, struggles with handwriting, and fails on degraded images). The product decision (accept the fax) cascaded into the core AI architecture (build a VLM), which cascaded into the model strategy (proprietary training on domain data), which defined the company's engineering identity.

### Engineering Constraint Creating Product Feature

**The 8,000 page classification taxonomy** became a product feature: Tennr can tell a provider exactly what type of document they received and what's missing. "You received a referral for cardiology from Dr. Smith via Blue Cross of Texas, but it's missing the required clinical documentation for cardiac catheterization — specifically, the stress test results and recent lab panel required by Blue Cross's criteria."

This level of specificity is only possible because the model was trained to distinguish thousands of form types and because the payer criteria knowledge base maps each form type to its required fields. What started as an engineering requirement (the model needs to know what form it's looking at) became a product feature (we can tell you exactly what's wrong and how to fix it).

### The "Looks Like Product but Is Actually Systems Design" Moment

**Voice AI for phone calls (2026).** Adding automated phone calling looks like a product expansion — "now Tennr can make calls too!" But it's actually the integration layer extending from document processing to another channel of unstructured information.

The underlying system design insight: healthcare operations involve two primary channels of unstructured information exchange — documents (faxes, forms) and phone calls (payer verification, patient scheduling, documentation follow-up). Both channels produce unstructured input that must be converted to structured data and routed into the same orchestration engine. Voice AI is not a separate product — it's another ingestion adapter in the same pipeline.

The CEO's framing is telling: "Voice AI is a feature that will become commoditized. The key is embedding it inside existing patient workflows." The voice capability is a feature; the workflow integration is the architecture. The engineering challenge is not voice (ElevenLabs and others solve that) — it's connecting voice interaction outcomes to the existing referral pipeline with the same accuracy and auditability as document processing.

## 9. What a Well-Resourced Competitor Needs to Win

### The Actual Moat

The moat has four layers, each harder to replicate than the last:

1. **The training dataset (medium difficulty to replicate).** 4 million medical documents, 230 million data fields, 2 billion checkboxes. A competitor can start processing medical documents and accumulating training data, but reaching Tennr's scale requires processing millions of documents — which requires having customers — which requires having a working product. Chicken-and-egg problem.

2. **The page classification taxonomy (hard to replicate).** 8,000+ page types, each with labeled training data and extraction templates. This is years of accumulated domain knowledge. A competitor starting today would encounter each page type for the first time and need to label, classify, and build extraction logic for it.

3. **The payer criteria knowledge base (very hard to replicate).** Thousands of distinct rule sets (payer × state × service type), continuously maintained. This is not publicly available data — it's assembled from payer manuals, appeals data, and operational experience. A competitor would need to build this knowledge base from primary sources, which is a multi-year effort.

4. **The integration infrastructure (hardest to replicate).** Connectors to fax providers, on-prem file systems, dozens of EHR systems, payer eligibility APIs, and provider communication channels. Each integration is custom, each customer deployment requires configuration, and each legacy system has its own quirks. This is the "boring" engineering that takes years and can't be shortcut.

### Build vs Buy

| Component | Build or Buy? | Time to Parity |
|-----------|--------------|----------------|
| VLM for document processing | Build (fine-tune open-source VLM as starting point) | 6–12 months |
| Page classification taxonomy | Build (must process documents to discover page types) | 18–24 months |
| Training data at scale | Build (requires customer volume) | 2–3 years |
| Payer criteria knowledge base | Build (must assemble from primary sources) | 2–3 years |
| EHR integrations | Build (customer by customer) | 12–18 months for top 5 EHRs |
| Fax/document ingestion | Build (relatively straightforward) | 3–6 months |

## 10. Steal This

### What You'd Take

**The "don't change the input, change the processing" strategy.** This is the most transferable insight from Tennr. In any domain where legacy infrastructure is entrenched:
- **Finance:** Accept spreadsheets and PDFs as inputs, extract structured data, apply compliance rules. Don't ask traders to use a new system.
- **Legal:** Accept Word documents and emails, extract contractual terms, flag risks. Don't ask lawyers to use a contract management tool.
- **Government:** Accept paper forms and scanned documents, extract structured data, populate systems of record. Don't ask citizens to use a new portal.

The pattern: the input is a behavior that won't change. The processing is where AI adds value. The output goes into the existing system of record. The user's workflow is unchanged.

### Mistake They Avoided

**Trying to build an EHR replacement.** Every startup that tried to replace Epic, Cerner, or Athenahealth either failed, pivoted, or got acquired for parts. EHR replacement is a multi-year, multi-hundred-million-dollar undertaking with massive switching costs for customers. Tennr integrates with existing EHRs — they are additive, not competitive. This eliminated:
- The "rip and replace" sales objection
- The multi-year implementation timeline that kills healthcare IT deals
- The risk of competing with companies that have 10–20x their resources

### What I'd Do Differently

**I'd build the payer criteria engine as a separate, licenseable product.** The knowledge base of insurance-specific rules by state, service type, and payer is valuable beyond referral processing. It applies to:
- Prior authorization platforms (other companies processing authorizations)
- Revenue cycle management (companies managing billing and collections)
- Clinical decision support (alerting physicians to insurance requirements during encounters)
- Health plan administration (insurance companies validating their own criteria application)

Tennr has this data but bundles it into the product. Unbundling it as an API ("is this clinical scenario covered by this payer in this state?") would create a second revenue stream, make Tennr a platform rather than a product, and create API lock-in with other healthcare software companies.

## 11. Raw Engineering Signals

- 9 billion faxes per year in US healthcare — this number is the reason Tennr exists
- HITECH Act (2009): $27B invested in EHR adoption → universal EHR deployment, continued fax dominance
- One-third of Americans referred for specialty care annually — the TAM is enormous
- RaeLM: 7B parameter proprietary VLM
- Training data: 4 million medical documents, 230 million data fields, 8,000 page classifications, 2 billion checkboxes
- Scale: 10 million documents processed per month (and growing)
- ROI example: specialty group went from 80% → 85% referral conversion in first month after turning on Intake — that's a meaningful revenue increase for a specialty practice
- "Forcing healthcare providers to change the way they refer their patients doesn't work. Many have tried." — IVP partner Zeya Yang
- Founded 2021, YC W23, Series C $101M (June 2025) — under 4 years from founding to $101M raise
- Revenue anchors: "conversions, denials, FTE efficiency" — tracked monthly, must all trend in the right direction
- Voice AI (2026): extension from document processing to phone call automation — same orchestration engine, new input channel
- Customers: high-volume treatment providers across drugs, devices, diagnostics, therapies — entities that live on inbound referrals and can measure ROI in referral conversion rates
- Architecture: "enterprise orchestration engine + series of specialized language models" — not one monolithic model

---

**The single most important thing I'd tell a team building in healthcare AI:** Don't fight the workflow. Healthcare has entrenched behaviors backed by regulation, decades of habit, and the sunk cost of existing infrastructure. The winning move is to sit between the existing input channel (fax, phone, portal) and the existing system of record (EHR), and add intelligence to the connection — not replace either end. Every company that tried to change healthcare's input medium failed. Every company that accepted the input medium and improved the processing succeeded.

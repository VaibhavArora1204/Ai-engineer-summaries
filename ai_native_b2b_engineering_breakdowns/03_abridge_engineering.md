# Abridge — Engineering Deep Dive

## 1. The One-Line Architectural Bet

**Build a Contextual Reasoning Engine that converts ambient doctor-patient conversations into billable, codeable clinical notes inside Epic EHR, rather than building a standalone transcription product.**

The bet is layered. Layer 1: ambient capture (microphone on during conversation) is the input mechanism. Layer 2: transcription is the intermediate step. Layer 3: the Contextual Reasoning Engine — which understands clinical significance, billing codes, doctor preferences, and hospital-specific documentation requirements — is the actual product. Layer 4: embedding the output directly inside Epic (the EHR that holds 350M+ patient records) is the distribution moat.

Most ambient AI companies stop at layer 2 (transcription) or layer 3 (note generation). Abridge's bet is that layers 3 AND 4 together are required — a note that isn't billable is useless to the hospital's revenue, and a note that isn't inside Epic doesn't get signed. The product is not the transcript. The product is the *signed, billable, compliant note in the EHR.*

The problem they're solving is quantified and severe:
- Doctors spend 15.5 hours/week on administrative tasks during scheduled work hours
- Specialties like internal medicine, oncology, nephrology: 18–19 hours/week on admin
- 93% of physicians felt regular burnout as of February 2024; 62% attributed it directly to excessive administrative burden
- Every patient visit must produce a SOAP note (Subjective/Objective/Assessment/Plan) for billing and continuity of care — this takes 15–30 minutes per visit to write manually
- Abridge saves an average of 2 hours/day per clinician

Founded in 2018 out of the Pittsburgh Health Data Alliance (CMU + UPMC + Pitt), Abridge was building before the ambient AI wave. The company was founded by Shivdev Rao (CEO/physician), Florian Metze (CSO — speech recognition researcher), and Sandeep Konam (CTO). The founder combination is clinically informed (Rao practices medicine), research-grounded (Metze comes from speech recognition at CMU), and engineering-led (Konam is the technical architect). This combination explains why the product goes deeper than transcription — the physician co-founder knows what a useful clinical note actually requires.

## 2. Data Model

### Core Entities and Relationships

**Encounter** — A single doctor-patient conversation session. The encounter is the fundamental unit of clinical documentation. Metadata includes: consent status (patient must consent before recording), start/end timestamps, participating clinicians, patient identifier, visit type (follow-up, new patient, urgent, telehealth), and clinical setting (outpatient clinic, hospital inpatient, emergency department). The encounter type determines which documentation template and billing rules apply — an outpatient follow-up visit generates a different note type than an inpatient admission.

**Transcript** — The raw speech-to-text output of the encounter, with speaker diarization (who said what). The transcript is not a simple text string — it's a time-aligned, speaker-labeled sequence of utterances. Quality of diarization directly impacts note accuracy: if the system attributes a patient's complaint to the doctor, the SOAP note will be wrong. Medical speech transcription is harder than general speech because of:
- Medical terminology (drug names, diagnoses, procedures — a vocabulary of hundreds of thousands of terms)
- Accented speech (healthcare workforce is globally diverse)
- Overlapping speakers (in inpatient settings, multiple clinicians may be present)
- Background noise (hospital environments are loud)
- Rapid speech under time pressure (doctors in busy clinics speak quickly)

**Clinical Note** — The generated SOAP document. This is not free-form text — it's a structured document with four mandatory sections:
- **Subjective:** What the patient reports — symptoms, concerns, history as told by the patient
- **Objective:** What the clinician observes — vital signs, physical exam findings, lab results
- **Assessment:** The clinician's diagnosis or differential diagnosis
- **Plan:** What happens next — medications, referrals, follow-up, patient education

Each section must be clinically accurate (faithful to the conversation), complete (including all relevant clinical details), and billable (supporting the level of medical decision-making claimed by the billing codes). A note that's accurate but doesn't support billing is a revenue loss. A note that supports billing but isn't accurate is fraud.

**Clinician Profile** — The personalization layer. This is critical and often overlooked by transcription-focused competitors. Different doctors at the same hospital document differently:
- Dr. A writes detailed assessment sections with differential diagnoses listed in order of probability
- Dr. B writes terse assessments with a single working diagnosis
- Dr. C always includes patient education notes in the plan
- Dr. D uses specific abbreviations and formatting conventions

The Contextual Reasoning Engine must learn each clinician's style and generate notes that match their preferences. "The same conversation produces different notes for different doctors at different hospitals" — this personalization is the hard engineering problem. The clinician profile likely stores: preferred note length, section formatting, common phrases, abbreviation patterns, and documentation style (narrative vs bulleted).

**Hospital Configuration** — Facility-specific requirements that affect note generation:
- Billing code sets (which ICD-10 and CPT codes are used for which visit types)
- Documentation templates (some hospitals have custom SOAP templates)
- Compliance rules (e.g., specific documentation requirements for certain diagnoses)
- EHR-specific settings (Epic configuration varies significantly between health systems)
- Specialty-specific requirements (cardiology notes have different requirements than dermatology notes)

**Billing Codes** — ICD-10 (diagnosis codes), CPT (procedure codes), and HCPCS (supply/service codes) embedded in the note for reimbursement. Correct coding is the financial backbone of healthcare: a visit coded as level 3 reimburses differently than a visit coded as level 4. The coding must be supported by the documentation — if the note doesn't demonstrate sufficient medical decision-making for a level 4 code, the claim can be denied or the hospital can be audited. Abridge's revenue cycle intelligence feature embeds billing code validation in real time, catching coding errors before the note is signed.

### State Transitions

```
Patient Consent Given
→ Recording Active (ambient microphone capturing conversation)
→ Streaming ASR (real-time speech-to-text with speaker diarization)
→ Transcript Accumulation (growing transcript during conversation)
→ Conversation Ends (recording stops)
→ Contextual Reasoning Engine Processing:
    → Clinical Significance Extraction (what's clinically relevant vs small talk)
    → Patient History Integration (pull relevant history from EHR)
    → Clinician Profile Application (match this doctor's documentation style)
    → Hospital Rules Application (apply facility-specific requirements)
    → Billing Code Assignment (ICD-10, CPT based on medical decision-making level)
    → Billing Code Validation (does the documentation support the codes?)
→ Draft SOAP Note Generated
→ Draft Appears in Epic (via Pal integration)
→ Clinician Review (doctor reads, edits, adjusts billing codes if needed)
→ Clinician Signs Note in Epic
→ Signed Note Persists in Epic as System of Record
→ Edit Patterns Captured (feeds back to clinician profile for future improvement)
→ Billing Submission (note + codes submitted for reimbursement)
```

### What's Stored Where

- **Audio:** Ephemeral during processing, likely NOT persisted post-note-generation. HIPAA's minimum necessary principle favors discarding audio after the note is generated — there's no clinical or legal reason to retain the raw audio if the transcript and note are preserved. However, some health systems may require audio retention for quality assurance or litigation; this is configurable per hospital.
- **Transcript:** Server-side, encrypted, retained per hospital policy. The transcript is the evidence that the note is faithful to the conversation. Retention period varies by hospital (typically 7–10 years for medical records, but the transcript may have a shorter retention period if it's considered a processing artifact rather than part of the medical record).
- **Clinical note:** Persisted in Epic as the system of record. Once signed, the note is part of the patient's permanent medical record. Abridge does not own this data — Epic does.
- **Clinician profiles:** Server-side, per-organization, continuously updated from edit patterns.
- **Hospital configurations:** Server-side, set during deployment, updated as hospital policies change.
- **Model inference artifacts:** Ephemeral (intermediate reasoning during note generation is not retained).

### Ephemeral vs Persistent

Audio is the most clearly ephemeral — processed and discarded. Model inference state is ephemeral. Transcripts are quasi-persistent (retained for a configurable period for quality assurance, then deleted). The clinical note is the only truly permanent artifact — and it lives in Epic, not in Abridge's systems. This is architecturally clean: Abridge generates the note, but Epic is the system of record. If Abridge goes down, the historical notes are unaffected.

## 3. Write Path / Read Path

### Write Path: Conversation → Clinical Note

1. **Patient consent** — Before any recording begins, the patient must be informed and consent to the recording. This is a regulatory requirement (state recording laws vary) and an ethical requirement (patients have a right to know their conversation is being captured by AI). The consent mechanism is built into the product workflow — likely a prompt in the Epic interface or a physical signage requirement in the exam room.

2. **Ambient audio capture** — Microphone activated. The capture mechanism could be:
   - A dedicated device in the exam room (purpose-built microphone with noise cancellation)
   - The clinician's smartphone running an Abridge app
   - A computer microphone on the workstation running Epic
   - For telehealth: capture from the video call audio stream
   
   The choice of capture mechanism affects audio quality, which directly affects transcription accuracy. Purpose-built devices with directional microphones and noise cancellation produce better audio than a smartphone in a pocket.

3. **Streaming ASR (Automatic Speech Recognition)** — Audio is processed in real-time (or near-real-time) by the ASR model. Streaming is important because:
   - The clinician wants to see the note draft as soon as possible after the conversation ends (no 5-minute processing delay)
   - Streaming allows incremental processing — the system can start building context before the conversation is complete
   - For inpatient settings with long encounters (30–60 minutes), waiting for the full audio before starting processing would add unacceptable latency
   
   The ASR model is likely proprietary or heavily fine-tuned on medical speech. Medical terminology recognition is a known challenge for general ASR models — drug names like "metoprolol" or "hydroxychloroquine" must be transcribed correctly because errors in medication names can affect patient safety. Speaker diarization (who said what) runs alongside ASR — this is typically a separate model or pipeline component.

4. **Transcript enrichment** — The raw transcript is enriched with:
   - Speaker labels (doctor, patient, nurse, family member — based on diarization)
   - Time alignment (each utterance has a timestamp)
   - Medical entity recognition (drug names, diagnoses, procedures highlighted)
   - Utterance classification (clinically significant statement vs small talk vs administrative discussion)

5. **Contextual Reasoning Engine processing** — This is the core of Abridge's technology. The engine takes the enriched transcript and produces a clinical note. This is NOT simple summarization. The engine must:
   
   **a. Determine clinical significance:** "The weather's been nice lately" → not clinically relevant, exclude. "My knee has been hurting for two weeks, worse when I go up stairs" → clinically relevant, include in Subjective section. "I stopped taking the metoprolol because it made me dizzy" → clinically significant AND affects the plan, include in Subjective and reference in Plan. This is a classification problem that requires medical knowledge — not all statements that mention body parts or symptoms are clinically significant, and some apparently casual statements have clinical importance.
   
   **b. Integrate patient history:** Pull relevant history from the EHR. If the patient has a known history of hypertension and the conversation discusses blood pressure, the Assessment section should reference the existing diagnosis. If the patient was started on a new medication at the last visit, and the current conversation discusses side effects, the note should connect these. This requires reading EHR data (problem list, medication list, recent lab results) and incorporating it into the note context.
   
   **c. Apply clinician documentation preferences:** Generate the note in the specific doctor's style. Dr. A gets a detailed narrative Assessment. Dr. B gets a bulleted, terse Assessment. Dr. C gets patient education notes in the Plan. The engine must learn these preferences from historical edits (the feedback loop: clinician edits a generated note → edit patterns update the clinician profile → future notes match the clinician's style more closely).
   
   **d. Apply hospital-specific requirements:** Use the correct documentation templates, billing code sets, and compliance rules for this hospital. A note generated for UPMC may have different formatting than a note generated for Mayo Clinic, even for the same conversation.
   
   **e. Assign billing codes:** Based on the medical decision-making documented in the Assessment and Plan sections, assign ICD-10 diagnosis codes and CPT visit-level codes. Correct coding requires understanding:
   - How many problems were addressed (more problems = higher visit level)
   - The complexity of data reviewed (lab results, imaging, specialist reports)
   - The risk of management decisions (prescribing controlled substances = higher risk)
   
   This is the revenue cycle intelligence feature: billing code validation happens during note generation, not after. If the conversation documented enough medical decision-making for a level 4 visit but the system would under-code it as level 3, the system should flag this — the hospital loses revenue on every under-coded visit.

6. **Draft note appears in Epic** — Via the Pal integration, the draft SOAP note appears inside Epic's note editor. The clinician sees the draft in their normal workflow — no context switching to a separate application. This is critical: if the clinician had to leave Epic, open Abridge, copy the note, and paste it back into Epic, adoption would drop dramatically.

7. **Clinician review and editing** — The doctor reads the draft, makes corrections:
   - Factual corrections (the model got a medication name wrong)
   - Style adjustments (the doctor prefers different phrasing)
   - Clinical additions (the model missed something the doctor considers important)
   - Billing code adjustments (the doctor disagrees with the coding level)
   
   Average edit time: reportedly a few minutes vs 15–30 minutes for writing from scratch. Over time, as the clinician profile improves, edit time decreases.

8. **Sign and submit** — The doctor signs the note in Epic, finalizing it as part of the patient's medical record. The signed note is submitted for billing with the assigned codes.

9. **Feedback capture** — Every edit the clinician makes is a training signal:
   - Systematic edits (this doctor always adds "patient was counseled on risks") update the clinician profile
   - Error corrections (the model consistently misidentifies a specific drug name) feed back to the ASR and reasoning models
   - Code adjustments (the doctor consistently changes level 3 to level 4) may indicate the model is under-coding

### Read Path: Clinician Reviews Previous Notes

1. Clinician opens Epic, navigates to a patient's chart
2. Previous Abridge-generated notes are indistinguishable from manually written notes — they're stored in Epic's standard note format
3. For quality assurance: Abridge dashboard shows generation metadata — edit rates, time-to-sign, confidence scores, coding accuracy
4. For compliance auditing: audit trail showing which notes were AI-generated, what edits were made, and who signed

### Where Latency Lives

- **Streaming ASR:** Continuous during conversation, ~200–500ms behind real-time. Not a bottleneck because processing is concurrent with the conversation.
- **Contextual Reasoning Engine:** This is the critical path. Processing begins when the conversation ends (or slightly before, if the engine can start generating sections for already-completed portions of the conversation). Estimated: 15–45 seconds for a typical 15-minute encounter. Longer encounters (30–60 minutes for complex cases) take proportionally longer.
- **EHR data retrieval:** Pulling patient history from Epic: 1–5 seconds depending on Epic's API performance.
- **Epic API push (draft note):** Writing the draft note into Epic: 2–5 seconds.
- **Total time from conversation end to draft note visible:** 20–60 seconds is the target. Every additional second is a second the doctor is waiting or has moved to the next patient. If the doctor moves on and forgets to review the note until hours later, the quality of their review decreases (they remember the conversation less well), and the value of Abridge decreases.

## 4. AI/ML Layer

### Models Used and Why

**ASR model:** Likely proprietary or heavily fine-tuned on medical speech. Medical ASR has specific requirements that general models (Whisper, Deepgram) don't fully address:
- Medical vocabulary: hundreds of thousands of drug names, diagnoses, procedures, body parts, lab values
- Accented speech: healthcare workforce speaks many languages with many accents
- Noisy environments: exam rooms, hospital floors, emergency departments
- Speaker overlap: in inpatient settings, multiple people may speak simultaneously
- Abbreviations and jargon: "BP 120/80," "BID," "PRN," "EMG," "CBC"

A fine-tuned Whisper or a proprietary ASR model trained on medical conversation data is the most likely approach. The Pittsburgh Health Data Alliance (CMU + UPMC) provided access to medical speech data for research, which likely seeded the ASR training.

**Contextual Reasoning Engine:** Proprietary, multi-component. This is not a single LLM — it's a pipeline:
- **Clinical significance classifier:** Determines which utterances are clinically relevant
- **SOAP section mapper:** Maps relevant utterances to the appropriate SOAP section
- **Medical entity recognizer:** Identifies drugs, diagnoses, procedures, lab values in the transcript
- **Billing code assigner:** Maps the medical decision-making level to ICD-10 and CPT codes
- **Style adapter:** Adjusts output formatting and phrasing to match the clinician profile
- **Consistency checker:** Ensures the note is internally consistent (the Assessment references conditions discussed in the Subjective; the Plan addresses the Assessment)

Source material does not specify whether the base LLM is proprietary or a fine-tuned frontier model. Reasoning from first principles: Abridge likely uses a combination:
- A proprietary or fine-tuned LLM for the core note generation (generating natural-language clinical text)
- Rule-based or classifier-based components for billing code assignment (billing rules are deterministic)
- A personalization model or system for style adaptation (learned from clinician edit patterns)

### Context Strategy

Full-context processing of the encounter transcript, enriched with three additional context sources:
1. **Patient history from EHR:** Problem list, medication list, recent lab results, previous visit notes. This is structured data injected into the reasoning pipeline — not RAG in the traditional sense.
2. **Clinician documentation preferences:** The clinician profile provides style parameters. This is also structured data, not retrieved documents.
3. **Hospital configuration:** Billing rules, documentation templates, compliance requirements. Structured, deterministic data.

The context strategy is hybrid: the transcript is unstructured text processed by the language model, while the enriching context (patient history, clinician profile, hospital config) is structured data that constrains and guides the model's output. This is closer to "constrained generation" than "retrieval-augmented generation" — the model generates within the constraints of the patient's history, the doctor's style, and the hospital's rules.

### Fine-tuning vs Prompting vs Retrieval

- **Fine-tuning:** The ASR model is fine-tuned on medical speech (vocabulary, accents, noise patterns). The clinical reasoning components are likely fine-tuned on medical documentation tasks (SOAP note generation, billing code assignment).
- **Prompting:** The style adaptation layer likely uses prompt-based customization (injecting clinician preferences into the generation prompt). Hospital-specific rules may also be injected via system prompts.
- **Retrieval:** Patient history is retrieved from the EHR, but this is structured data retrieval (API call to Epic), not semantic search over a document corpus.
- **Rule-based:** Billing code assignment is partially rule-based (the relationship between documentation level and billing codes is defined by CMS guidelines, not learned from data). The Contextual Reasoning Engine likely combines model-based reasoning (is this conversation complex enough for a level 4 visit?) with rule-based code assignment (level 4 maps to CPT code 99214/99215).

### Latency / Quality / Cost Tradeoff

**Quality is non-negotiable.** Clinical notes affect patient care (the next doctor who sees this patient reads this note) and billing (the hospital's revenue depends on correct coding). A note that contains errors in diagnosis, medication names, or allergies is a patient safety risk. A note that under-codes loses revenue. A note that over-codes is fraud.

**Latency matters more here than in most AI products.** Doctors have 15-minute appointment slots. If the AI note takes 5 minutes to generate, the doctor spends those 5 minutes doing nothing (or seeing the next patient without having reviewed the note). The target: note available within 30–60 seconds of conversation end.

**Cost is absorbed into the enormous value proposition.** 2 hours/day saved per clinician × $200+/hour effective clinician cost = $400+/day in recovered productivity per clinician. At 250+ health systems with thousands of clinicians each, the per-clinician inference cost is a tiny fraction of the value. Abridge can charge premium pricing and still deliver massive ROI.

### Failure Modes

1. **Misattributed speech** — If the system attributes a patient's symptom report to the doctor (or vice versa), the SOAP note will be wrong in a clinically dangerous way. "I've been having chest pain" attributed to the doctor instead of the patient means the note omits a potentially critical symptom.

2. **Missed clinical significance** — The doctor casually mentions "your potassium is a little low" and the system doesn't include it in the note because it was said informally. But low potassium with certain medications can indicate a serious drug interaction. The clinical significance classifier must have high sensitivity for these cases.

3. **Wrong billing codes** — Over-coding (assigning a higher visit level than the documentation supports) is healthcare fraud. Under-coding (assigning a lower level than supported) costs the hospital revenue. The billing code assignment must be calibrated to match the actual documentation level — this requires understanding CMS's documentation guidelines, which are complex and change periodically.

4. **Hallucinated content** — The model adds clinical information that was NOT discussed in the conversation. "Patient denies chest pain" when chest pain was never mentioned. This is the most dangerous failure because the clinician may not catch it during review — it looks like something they'd normally document, and they might sign it without noticing it wasn't actually discussed.

5. **Automation trust decay** — Over time, as clinicians become comfortable with AI-generated notes, they review less carefully. The first month, they read every word. By month 6, they skim. By month 12, they might sign without reading. This is a systemic risk: the quality of the AI note is partially maintained by the human review step, and as review quality degrades, errors slip through. Abridge must invest in mechanisms that maintain clinician engagement with the review step.

## 5. Critical Engineering Decisions & Tradeoffs

### What They Gave Up

**Platform independence.** By building deeply into Epic, Abridge is coupled to Epic's roadmap, API changes, partnership terms, and competitive decisions. Specifically:
- Epic controls the Pal integration program and can add or remove partners
- Epic's API surface can change, requiring Abridge to update their integration
- Epic could build (or is building) native ambient AI capability, competing directly
- Abridge's go-to-market is dependent on Epic's sales motion (health systems that use Epic are the primary market)

The mitigation: Epic has 350M+ patient records and dominates US health systems. Being inside Epic is being inside the workflow where 85%+ of US hospital documentation happens. The concentration risk is real, but the distribution advantage is overwhelming.

**Multi-EHR coverage speed.** Building Epic-first means Cerner/Oracle Health, athenahealth, and smaller EHR systems were deprioritized. Health systems using non-Epic EHRs must either wait for Abridge to build integration or use a competitor. This is a market segment left unserved by choice — the Epic segment is so large that serving it exclusively is a viable strategy.

### Technical Debt Accumulating

**Clinician profile personalization at scale.** With 250+ health systems and thousands of clinicians per system, the profile database is large and complex:
- Each profile must learn from edits (which requires tracking edit patterns per clinician)
- Profiles must be robust to noisy signals (a clinician edits for reasons unrelated to preference — correcting a patient name, fixing a date)
- Profiles must adapt to changing preferences (a clinician changes their style after attending a documentation training)
- Profile quality must be validated (is this profile making notes better or worse?)

The feedback loop is the value, but managing it at scale is the debt. A clinician profile that's learned incorrect preferences (because it misinterpreted edit patterns) will generate progressively worse notes for that clinician, creating a negative spiral until someone notices and resets the profile.

### The Decision Hardest to Undo

**The Epic-first integration strategy.** Everything about Abridge's product is designed around Epic's APIs, data models, and user workflows:
- The draft note appears in Epic's note editor (using Epic's API for note creation)
- Patient history is pulled from Epic's data model (problem list, medication list, lab results)
- Billing codes are mapped to Epic's coding interface
- The clinical workflow (record → generate → review → sign) follows Epic's documentation workflow

Porting to another EHR requires re-engineering the entire integration layer. The clinical reasoning should be EHR-agnostic (the SOAP note format is standard), but the integration — data retrieval, note creation, coding interface, workflow embedding — is deeply Epic-specific. A Cerner integration would take 6–12 months of dedicated engineering.

## 6. Privacy & Security Architecture

### Data Flow

```
Ambient audio (clinic exam room)
→ [Device/network] → Abridge processing servers
→ Streaming ASR → Transcript
→ EHR data retrieval → Epic API (patient history, problem list, medications)
→ Contextual Reasoning Engine → Draft SOAP note + billing codes
→ Draft note → Epic API (write draft into Epic's note editor)
→ Clinician review in Epic
→ Signed note persists in Epic
```

### Threat Model at Each Hop

**Audio capture to Abridge servers:**
- The audio of a doctor-patient conversation is the highest-sensitivity data in healthcare. It contains PHI + medical confidentiality (analogous to attorney-client privilege).
- The audio must be encrypted in transit (TLS). If the audio is transmitted over a hospital WiFi network, the hospital's network security becomes part of Abridge's threat model.
- Edge case: if the device stores audio locally before uploading (e.g., during a network outage), the local storage must be encrypted and the audio must be deleted after successful upload.

**Abridge processing servers:**
- PHI flows through every stage of the pipeline. Abridge's servers must be SOC 2 Type II compliant, HIPAA compliant, and secured against unauthorized access.
- Multi-tenant isolation is critical: audio and transcripts from Hospital A must never be accessible to Hospital B. This is both a HIPAA requirement and a business requirement (health systems are competitors).
- If any component of the pipeline uses a third-party model API (sending transcript text to OpenAI or Anthropic for processing), PHI flows to that vendor — requiring a BAA, data residency compliance, and assurance that the third-party won't train on the data. If Abridge uses proprietary models exclusively, this risk is eliminated.

**Epic API communication:**
- Retrieving patient history: Abridge reads PHI from Epic. This read access must be scoped to the minimum necessary (only the patient being seen, only the data fields needed for note generation).
- Writing the draft note: Abridge writes to Epic's database. This write access is sensitive — a bug or exploit that writes incorrect medical information to a patient's chart could cause patient harm.

### Compliance Choices Shaping Architecture

**HIPAA drives the ephemeral audio decision.** The minimum necessary rule says: don't retain data you don't need. Once the transcript and note are generated, the raw audio is no longer necessary for the clinical purpose. Deleting the audio after processing reduces the data retention surface area and the risk of a breach exposing recorded conversations.

**Patient consent requirement** before recording is both a regulatory mandate (state wiretapping laws vary; some states require all-party consent) and a product constraint. There's no "always-on" recording — the system must verify consent before capturing any audio. This means the product can't work without explicit patient participation, which limits adoption in settings where consent is hard to obtain (emergency departments, patients who decline).

**BAAs with every vendor** in the processing chain. If Abridge uses cloud infrastructure (AWS, Azure, GCP), the cloud provider needs a BAA. If they use any third-party model API, that provider needs a BAA. If they use any analytics service that touches PHI, that service needs a BAA. The BAA requirement cascades through the entire technology stack and constrains vendor choices.

## 7. Latency Engineering

### Where the Latency Budget Is Spent

| Component | Estimated Latency | Notes |
|-----------|------------------|-------|
| Audio capture | Real-time (continuous) | Not a latency component — concurrent with conversation |
| Streaming ASR | 200–500ms behind real-time | Continuous during conversation |
| ASR finalization | 2–5 seconds after last speech | Final transcript processing |
| EHR data retrieval (Epic API) | 1–5 seconds | Patient history, medications, labs |
| Contextual Reasoning Engine | 15–40 seconds | The dominant latency component |
| Billing code assignment + validation | 1–3 seconds | Partially rule-based |
| Epic API push (draft note) | 2–5 seconds | Writing the note into Epic |
| **Total (conversation end → draft note visible)** | **20–60 seconds** | |

### P50/P90/P99 Targets

Source material doesn't provide specific targets. Reasoning from first principles:

- **P50:** 25 seconds for a standard 15-minute outpatient visit (common encounter type, straightforward medical decision-making)
- **P90:** 50 seconds for a longer or more complex visit (multiple problems addressed, extensive medication changes, specialist consultation)
- **P99:** 90–120 seconds for complex encounters (oncology treatment discussions, multi-problem geriatric visits with extensive plan changes). These encounters have longer transcripts and more complex clinical reasoning requirements.
- **Acceptable ceiling:** 3 minutes. Beyond this, the clinician has moved to the next patient and will review the note later (or not at all), reducing review quality.

### What Breaks at 10x Scale

**Concurrent ASR processing during peak clinic hours.** Healthcare operations follow a predictable schedule:
- 8:00–12:00: Morning clinic hours (maximum encounter volume)
- 12:00–13:00: Lower volume (lunch, administrative time)
- 13:00–17:00: Afternoon clinic hours (high volume)
- After 17:00: Dramatically lower volume

This creates a thundering herd pattern: all clinicians at a health system start appointments at similar times, and conversations end at similar times. If a health system has 500 clinicians and appointments end on the hour and half-hour, the system may need to process 200+ encounters simultaneously during peak 5-minute windows.

At 10x scale (2,500+ health systems, not 250+):
- Peak concurrent ASR streams: thousands simultaneously
- Peak concurrent Contextual Reasoning Engine jobs: thousands simultaneously
- Peak concurrent Epic API operations: thousands simultaneously

Solutions:
- **Edge preprocessing:** Move initial ASR processing to edge devices (clinic hardware) to reduce server load. Send transcripts to the cloud instead of audio — less bandwidth, less server processing.
- **Auto-scaling inference clusters:** Scale GPU capacity with clinic schedules (predictable — you know when morning clinic starts).
- **Staggered processing:** Not all conversations end simultaneously. Process as conversations end rather than batching.
- **Streaming reasoning:** Start generating the SOAP note during the conversation (generate Subjective section while the conversation is still happening) rather than waiting for the full transcript.

## 8. The Product-Engineering Intersection

### Product Decision Forcing Hard Engineering Constraint

**"Be inside Epic."** This product decision — that the draft note must appear inside Epic's note editor, not in a separate Abridge application — forced Abridge to build within Epic's API constraints:
- Data formats: Epic dictates the note format, coding interface, and metadata structure
- Authentication: Epic's OAuth/SAML flows must be used
- UI embedding: Abridge's functionality must be accessible within Epic's interface (via the Pal program)
- Update cadence: changes to the integration must be compatible with Epic's release schedule
- Testing: Abridge must test against multiple Epic versions (health systems upgrade on different schedules)

A standalone product could iterate weekly, ship features independently, and control the full UX. An Epic-embedded product iterates on Epic's timeline and within Epic's constraints. The tradeoff: slower iteration in exchange for being inside the workflow where 85%+ of US clinical documentation happens.

### Engineering Constraint Creating Product Feature

**The Contextual Reasoning Engine's billing code capability** started as a technical requirement (the generated note must include codes for billing submission) and became a standalone product feature: revenue cycle intelligence. What started as "generate the right ICD-10 code" evolved into:
- "Validate that the documentation level supports the billing code" (catch under-coding before the note is signed)
- "Identify documentation opportunities" (the conversation contained enough medical decision-making for a higher billing code, but the draft note didn't capture it — suggest adding specific documentation)
- "Revenue analytics" (aggregate data on coding patterns across clinicians, identifying systematic under-coding)

This is an engineering capability (billing code assignment) becoming a revenue feature (revenue cycle intelligence). The health system buys Abridge for productivity (save clinicians 2 hours/day) but gets additional revenue from better coding accuracy.

### The "Looks Like Product but Is Actually Systems Design" Moment

**Expanding from outpatient to inpatient (Abridge Inside for Inpatient, 2025).** This looks like a product expansion — "now it works in the hospital too!" But inpatient documentation is fundamentally different from outpatient:

- **Multiple providers per encounter:** An inpatient patient is seen by attending physicians, residents, specialists, nurses, and care coordinators. The note must capture contributions from multiple speakers across multiple conversations.
- **Longer encounters:** An inpatient encounter may span hours or days, with multiple short conversations rather than a single continuous appointment.
- **Different note types:** Inpatient generates H&P (history and physical), progress notes, procedure notes, and discharge summaries — not SOAP notes.
- **Different billing rules:** Inpatient billing uses DRGs (Diagnosis Related Groups), not CPT visit-level codes. The billing model is completely different.
- **Different clinical context:** Inpatient patients are sicker, with more active problems, more medications, and more complex care coordination.

The Contextual Reasoning Engine must handle a completely different document model, billing model, and conversation model for inpatient. This is not "the same product in a different setting" — it's a new product that shares infrastructure with the outpatient product but has different models, different templates, different billing logic, and different clinical reasoning requirements.

## 9. What a Well-Resourced Competitor Needs to Win

### The Actual Moat

**The Epic integration.** Being the first ambient AI tool in Epic's "Pal" program means:
- Abridge is the default recommendation when a health system says "we want ambient AI in Epic"
- Abridge has been tested, certified, and deployed within Epic's ecosystem
- Abridge has established data flows, authentication integrations, and workflow embeddings that a competitor must replicate from scratch
- Epic's partnership is not infinitely replicable — having 5 ambient AI partners dilutes each partner's value

A competitor must either:
1. **Get Epic partnership status** — Epic controls this, and adding a competitor undermines the value of the existing partnership. It's possible but not guaranteed.
2. **Compete outside Epic** — Serve health systems using Cerner/Oracle Health, athenahealth, or other EHRs. This is a viable but smaller market.
3. **Wait for Epic to build it natively** — Epic has announced ambient AI capabilities (potentially using Microsoft/Nuance DAX technology). If Epic builds it in, all third-party partners (including Abridge) face disintermediation risk.

### Build vs Buy

| Component | Build or Buy? | Time to Parity |
|-----------|--------------|----------------|
| Medical ASR | Build (fine-tune Whisper or equivalent) | 6–12 months |
| Clinical reasoning / note generation | Build (requires medical NLP expertise) | 12–18 months |
| Clinician profile personalization | Build (requires deployment + feedback loops) | 18–24 months |
| Billing code assignment | Build (rules are published by CMS) | 3–6 months |
| Epic integration | Build (requires Epic partnership) | 12–18 months + Epic approval |
| Clinician trust + adoption data | Build (requires deployments) | 2–3 years |

**The critical insight:** The technology is replicable. The Epic integration is hard to replicate. The clinician profiles (accumulated personalization data from thousands of doctors) are impossible to replicate without deploying to those doctors and running for months. A competitor ships a generic product and iterates toward personalization; Abridge already has personalized profiles for thousands of clinicians.

## 10. Steal This

### What You'd Take

**The "billing code as a real-time feature" insight.** In any domain where the output document has financial implications:
- **Insurance claims:** Embed coverage validation during claim generation (is this claim going to be approved? what's missing?)
- **Legal filings:** Embed fee-petition validation during brief generation (does this documentation support the requested fees?)
- **Financial reporting:** Embed compliance validation during report generation (does this report meet regulatory requirements?)
- **Government applications:** Embed eligibility validation during application processing (does this applicant meet the criteria?)

The pattern: don't generate the document and then validate it. Validate during generation. Catch errors before the user sees the draft, not after they've signed and submitted.

### Mistake They Avoided

**Building a transcription-only product.** Transcription is a race to zero margin. Otter.ai, Rev, Deepgram, AssemblyAI, and OpenAI's Whisper all offer medical-grade transcription. If Abridge had stopped at "we transcribe doctor-patient conversations," they'd be competing on price against these commoditized services.

By going straight to clinical note generation — the document that gets signed, billed, and becomes part of the permanent medical record — Abridge captured the high-value part of the workflow. Transcription became an implementation detail. No clinician says "I wish I had a better transcript." Every clinician says "I wish I didn't have to write this note."

### What I'd Do Differently

**I'd build EHR-agnostic from day one with Epic as the first integration, not the only architecture.** The Epic bet is paying off massively ($5.3B valuation), but it creates concentration risk. An abstraction layer that handles Epic, Cerner/Oracle Health, and athenahealth with a unified interface would:
- Reduce the risk of Epic building native capabilities
- Open the non-Epic market segment (30–40% of US health systems)
- Make the technology portable to international markets (where Epic is less dominant)
- Create a defensible platform, not just a product tied to one EHR vendor

The counter-argument: building EHR-agnostic from day one would have slowed down Epic integration depth, potentially costing them the Pal program partnership. Speed-to-Epic was the right tactical choice. But the strategic debt of Epic-only architecture is growing as Abridge scales.

## 11. Raw Engineering Signals

- 15.5 hours/week on administrative tasks during scheduled work hours (all physicians)
- Internal medicine, oncology, nephrology: 18–19 hours/week on administration
- 93% of physicians felt regular burnout as of February 2024; 62% attributed it to excessive administrative burden
- SOAP note: 15–30 minutes per visit to write manually
- Average 2 hours/day saved per clinician using Abridge
- Epic: 350M+ patient records, dominant US EHR
- Abridge: first ambient AI tool officially integrated into Epic EHR via "Pal" program
- 250+ health systems as customers
- $5.3B valuation, ~$860M total funding (Series E $315M, February 2026)
- Founded 2018 by physician CEO (Rao) + CMU speech researcher (Metze) + CTO (Konam) — originated from Pittsburgh Health Data Alliance (CMU + UPMC + Pitt)
- Became enterprise-scale 2022–2024 with rise of ambient AI
- 2025 expansions: Abridge Inside for Inpatient, Outpatient Orders inside Epic, Revenue Cycle Intelligence
- "The same conversation produces different notes for different doctors at different hospitals" — the personalization challenge
- Contextual Reasoning Engine: "not just a transcription → summarization pipeline"
- HIPAA compliant, patient consent required before recording
- Competitor comparison: Reclaim.ai explicitly is NOT HIPAA compliant — Abridge is

---

**The single most important thing I'd tell a team building in clinical AI:** The note is not the product. The *signed, billable, compliant note inside the EHR* is the product. Three conditions must all be true: (1) the note must be clinically accurate (faithful to the conversation, correct medical facts), (2) the note must be billable (correct ICD-10 and CPT codes, documentation supporting the coding level), and (3) the note must be inside the EHR where the doctor signs it (no separate app, no copy-paste). If any of these three is missing, you've built a demo, not a business. The technology that generates the note is interesting. The integration that puts it in front of the doctor in their existing workflow is what gets it signed.

# Data Engineering for AI — The Deep Engineering Guide

> AI systems are only as good as the data flowing through them. This guide covers the infrastructure to build, clean, and scale that data.
> Source: Chip Huyen *AI Engineering* Ch. 3 & 4, production systems.

---

## 1. The Data Flywheel Architecture

In production AI, data is not a static dataset—it is a continuous pipeline.

```
┌───────────────────────────────────────────────────────────────┐
│                    THE AI DATA FLYWHEEL                        │
│                                                               │
│   ┌───────────────┐           ┌───────────────────────────┐   │
│   │ 1. Generation │           │ 4. Deployment & Logging   │   │
│   │    (Users)    │──────────→│    (System in Prod)       │   │
│   └───────────────┘           └─────────────┬─────────────┘   │
│           ↑                                 │                 │
│           │                                 ↓                 │
│   ┌───────┴───────┐           ┌─────────────┴─────────────┐   │
│   │ 3. Model      │           │ 2. Data Engine            │   │
│   │    Training/  │←──────────│    (Labeling, Filtering,  │   │
│   │    Evaluation │           │     Curation)             │   │
│   └───────────────┘           └───────────────────────────┘   │
└───────────────────────────────────────────────────────────────┘
```

**Why it matters:** The model architecture you choose today will be obsolete in 6 months. The data engine you build today is your long-term competitive moat.

---

## 2. Handling Unstructured Data at Scale

> 80% of enterprise data is unstructured (PDFs, images, raw text, emails).

### 2.1 The Ingestion Pipeline

```
Raw Files (S3/GCS) → Parsing (Extract Text/Layout) → Cleaning (Filter/Normalize) → Chunking → Embedding → Vector DB
```

### 2.2 PDF Parsing: The Hardest Problem in RAG

PDFs are visual documents, not semantic documents. They do not contain "paragraphs" or "tables"—they contain characters at (X, Y) coordinates.

**Parsing Strategies:**
1. **Heuristic Parsing (PyPDF, pdfplumber):**
   - Fast, cheap.
   - Fails completely on multi-column layouts, tables, and charts.
   - *Use for:* Text-heavy, simple single-column documents.

2. **OCR + Layout Detection (Tesseract, layoutparser):**
   - Renders PDF to image, runs OCR and object detection (identifies "Header", "Table", "Text").
   - *Use for:* Scanned documents, complex layouts.

3. **Vision-Language Models (Marker, Nougat, GPT-4V):**
   - State-of-the-art approach. Passes the image of the page to a VLM trained to output structured Markdown (or LaTeX for math).
   - *Cost:* High compute requirement at ingestion.
   - *Use for:* Documents with dense tables, mathematical equations, and complex formatting.

**Production Table Handling Pattern:**
```python
# When a layout model detects a table:
def process_table(table_image, vlm_model):
    """
    Extract table as Markdown or HTML. 
    Do NOT flatten tables into raw text; LLMs need structural tokens (|) to reason.
    """
    markdown_table = vlm_model.generate(
        image=table_image,
        prompt="Extract this table perfectly as Markdown. Preserve all headers."
    )
    return markdown_table

# During chunking: DO NOT split tables mid-row. Keep tables intact in a single chunk.
```

---

## 3. Data Quality Filtering (The Curation Phase)

Before data hits an embedding model or a fine-tuning job, it must be aggressively filtered. Training on garbage (or retrieving garbage) destroys performance.

### 3.1 The Filtering Heuristics Pipeline

```python
def quality_filter(document_text: str) -> bool:
    """Production data filtering pipeline."""
    
    # 1. Length/Entropy Filter
    if len(document_text) < 50 or is_repetitive(document_text):
        return False  # Drop garbage/navigational text
        
    # 2. Language ID
    if fasttext_lang_id(document_text) != "en":
        return False  # Ensure language consistency
        
    # 3. PII Redaction
    if contains_high_risk_pii(document_text):
        return False  # Or redact: replace SSN with [REDACTED]
        
    # 4. Toxicity/Safety
    if toxicity_score(document_text) > 0.8:
        return False
        
    return True
```

### 3.2 Deduplication (Crucial for Fine-Tuning)

Training on duplicated data causes the model to overfit/memorize those specific sequences.

- **Exact Match Deduplication:** Hash the document (SHA-256). Fast, but misses minor edits.
- **Fuzzy Deduplication (MinHash / Locality Sensitive Hashing):**
  - Creates a "signature" of the document based on N-grams.
  - Documents with similar signatures are clustered and deduplicated.
  - *Standard practice:* Remove documents with > 80% Jaccard similarity.

---

## 4. Automated Labeling & Synthetic Data

> Human labeling is too slow and expensive for modern AI scale. We must use models to label data for other models.

### 4.1 LLM-as-a-Judge (For Evaluation Data)

You need ground truth data to evaluate your RAG or Agent system. 

```python
# Instead of paying humans to write 1,000 Q&A pairs for your docs:
def generate_synthetic_qa(document_chunk, strong_llm="gpt-4o"):
    prompt = f"""
    Read the following technical document chunk.
    Write 3 difficult, multi-hop questions that can ONLY be answered using this text.
    Then, provide the correct answer and extract the exact quote that proves it.
    
    Document: {document_chunk}
    
    Output JSON: [{{question, answer, supporting_quote}}]
    """
    return strong_llm.generate(prompt)
```

### 4.2 Weak Supervision & Programmatic Labeling

Using tools like **Snorkel**:
Instead of labeling 10,000 customer support tickets by hand as "Refund" or "Technical", you write *Labeling Functions (LFs)*:

```python
@labeling_function()
def lf_contains_refund_keywords(x):
    return "Refund" if "money back" in x.text.lower() else ABSTAIN

@labeling_function()
def lf_llm_zero_shot(x):
    # Ask a cheap, fast LLM to guess
    return cheap_llm.classify(x.text)

# Snorkel's LabelModel mathematically combines these noisy heuristics 
# to create probabilistically accurate labels at massive scale.
```

---

## 5. Building Datasets for Fine-Tuning

### 5.1 SFT (Supervised Fine-Tuning) Data Formats

For an LLM to learn a task (like tool calling or specific formatting), it needs **demonstrations**.

**Format Matters:** You must format your training data using the EXACT chat template (e.g., ChatML, Llama-3 format) that you will use in production.

```json
// Example of a clean SFT row
{
  "messages": [
    {"role": "system", "content": "You are a helpful coding assistant."},
    {"role": "user", "content": "Write a Python function to reverse a string."},
    {"role": "assistant", "content": "```python\ndef reverse_string(s):\n    return s[::-1]\n```"}
  ]
}
```
*Rule of thumb: 1,000 high-quality, perfectly formatted examples > 100,000 scraped, noisy examples.*

### 5.2 Preference Data for DPO/RLHF

To teach a model *judgment* (e.g., "Don't be rude", "Admit when you don't know"), you need preference data.

```json
// Example of a DPO row (Direct Preference Optimization)
{
  "prompt": "User: What is the company's Q4 revenue?",
  "chosen": "I don't have access to the Q4 revenue figures in my current context. I can search the financial database if you'd like.",
  "rejected": "The Q4 revenue was $45.2 million." // Hallucination
}
```

**How to generate preference data synthetically (Constitutional AI):**
1. Generate an answer using your base model.
2. Ask a strong judge model (GPT-4) to critique the answer based on a "Constitution" (e.g., "Is this answer hallucinated?").
3. Ask the judge to rewrite the answer to fix the critique.
4. `chosen` = rewritten answer, `rejected` = original answer.

---

## 6. Continuous Data Operations (DataOps)

### The Offline/Online Skew

The biggest risk in data engineering for AI is training/evaluating on data that doesn't match what the model sees in production.

- **Offline Data:** Perfectly cleaned, spell-checked, beautifully formatted markdown.
- **Online Data:** User typing on a phone with typos, missing context, and broken formatting.

**The Fix:** 
1. Inject synthetic noise into your training/eval data (add typos, remove casing).
2. Log production requests and sample them back into your evaluation dataset continuously.

---
*Guide synthesized from: Chip Huyen "AI Engineering" Chapters 3 & 4. Last updated: June 2026.*

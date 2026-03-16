#  Advanced Legal Contract Analyzer & Risk Assessor

> **An enterprise-grade, single-agent AI pipeline for automated legal contract compliance review.**
> Built with LangChain ReAct architecture, Google Gemini LLM, Hybrid RAG (BM25 + Vector Search), and enforced guardrails using Pydantic schema validation.



##  Project Task & Objectives

> This project was assigned as part of an AI Engineering internship program to build hands-on experience with modern AI workflows using Python (LangChain and Pydantic).

### Project Title
**Advanced Legal Contract Analyzer & Risk Assessor (Single-Agent Pipeline)**

This agent acts as a legal analyst driven by a **ReAct (Reasoning and Acting) loop** and sequential tool calling to create a risk-management pipeline.

---

###  Core Requirements

#### RAG Implementation
The agent accesses a local folder (e.g., `D:/MyFiles/Contracts`) containing both client agreements (MSAs, SOWs) and the **"Company Standard Playbook"**. It uses this local knowledge base to retrieve the company's acceptable standards for comparison against client contracts.

#### Single-Agent Tool Calling — Sequential Pipeline
The agent is configured with **three distinct tools** it must call in a specific, enforced sequence:

| Tool | Function Name | Responsibility |
|------|--------------|----------------|
| Tool 1 | `extract_contract_terms` | Searches the target contract and extracts specific clauses into a strict Pydantic schema |
| Tool 2 | `query_playbook` | Queries the RAG system for the company's acceptable standards regarding the extracted clause topics |
| Tool 3 | `generate_risk_report` | Compares the output of Tool 1 and Tool 2 to generate a structured risk assessment |

#### Strict Guardrails — Mandatory Enforcement

**Guardrail 1 — Mandatory Verbatim Quotation:**
> Any risk flagged by the agent must explicitly include the **exact text string** from the document. The system prompt must enforce that **no summarization** occurs during the extraction or risk-flagging step.

**Guardrail 2 — Zero-Inference Rule:**
> The agent is **forbidden from inferring legal intent**. It must strictly evaluate whether the text in Clause X literally contradicts the text in Standard Y — **without offering legal advice**.

---

###  Suggested Additions (Both Implemented)

#### Semantic Chunking
> Chunk legal documents by heading, section, or legal clause rather than arbitrary token counts — ensuring the RAG retrieves **complete, contextual legal thoughts** rather than mid-sentence fragments.

**Implementation:** `RecursiveCharacterTextSplitter` with paragraph-first separator hierarchy (`\n\n → \n → . → space`), preserving complete clause structures.

#### Human-in-the-Loop (HITL) Approval
> The script must **pause after Tool 1** and display the extracted clauses to the user, asking them to **Approve** or **Reject** before the agent is allowed to proceed to the risk assessment step.

**Implementation:** Streamlit session state gate — Tools 2 and 3 are structurally unreachable until `session_state.hitl_approved == True`.

---

###  Task Completion Checklist

- [x] RAG pipeline accessing local `MyFiles/Contracts/` directory
- [x] Tool 1 — `extract_contract_terms` with Pydantic schema (`ContractData`)
- [x] Tool 2 — `query_playbook` with hybrid BM25 + vector RAG search
- [x] Tool 3 — `generate_risk_report` with structured `FinalRiskReport` output
- [x] Mandatory Verbatim Quotation enforced in prompt AND Pydantic `field_validator`
- [x] Zero-Inference Rule enforced in prompt AND `field_validator` rejects inference language
- [x] Semantic Chunking via `RecursiveCharacterTextSplitter` (paragraph-first hierarchy)
- [x] HITL Approval Gate — pipeline structurally pauses between Tool 1 and Tool 2
- [x] ReAct Thought → Action → Observation trace log
- [x] Enterprise-grade Streamlit UI with sticky pipeline status bar
- [x] Modular codebase — UI rendering separated into `ui_components.py`

---

##  Table of Contents

- [Project Overview](#-project-overview)
- [System Architecture](#-system-architecture)
- [Key Features](#-key-features)
- [Guardrails & Safety Mechanisms](#-guardrails--safety-mechanisms)
- [Technology Stack](#-technology-stack)
- [Prerequisites](#-prerequisites)
- [Installation & Setup](#-installation--setup)
- [Project Structure](#-project-structure)
- [Module Reference](#-module-reference)
- [Configuration](#-configuration)
- [Usage Guide](#-usage-guide)
- [Agent Pipeline Deep Dive](#-agent-pipeline-deep-dive)
- [RAG Pipeline Architecture](#-rag-pipeline-architecture)
- [Pydantic Schema Reference](#-pydantic-schema-reference)
- [Testing the System](#-testing-the-system)
- [Troubleshooting](#-troubleshooting)
- [Dependency Matrix](#-dependency-matrix)
- [Contributing](#-contributing)

---

##  Project Overview

The **Advanced Legal Contract Analyzer** is a production-ready AI agent designed to automate the compliance review of client contracts against a company's internal legal standards (the "Playbook"). It eliminates manual clause-by-clause review by deploying a structured, auditable AI pipeline that:

1. **Discovers** all legal section headings in a client contract
2. **Extracts** exact, verbatim clause text (no summarization permitted)
3. **Pauses for human approval** before proceeding (Human-in-the-Loop)
4. **Retrieves** the relevant company standard rules via hybrid semantic search
5. **Generates** a structured risk report identifying literal textual contradictions

### 🎓 Learning Objectives

| Concept | Implementation |
|---------|---------------|
| **ReAct Agent Architecture** | LangChain `@tool` decorated functions with Thought → Action → Observation loop |
| **RAG (Retrieval-Augmented Generation)** | ChromaDB vector store + BM25 keyword search ensemble |
| **Semantic Chunking** | `RecursiveCharacterTextSplitter` with paragraph-first hierarchy |
| **Pydantic Schema Validation** | Strict data contracts with `field_validator` guardrails |
| **Human-in-the-Loop (HITL)** | Streamlit session state approval gate blocking agent progression |
| **Hybrid Search** | 50% BM25 keyword + 50% vector semantic search via `EnsembleRetriever` |
| **Structured LLM Output** | `llm.with_structured_output()` enforcing typed Pydantic responses |
| **Modular Architecture** | Business logic in `app.py`, UI rendering in `ui_components.py` |

---

##  System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│              STREAMLIT FRONTEND (app.py + ui_components.py)          │
│                                                                       │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────────────────┐   │
│  │  Sidebar    │    │  Pipeline    │    │   ReAct Trace Log     │   │
│  │  - Playbook │    │  Status Bar  │    │  Thought→Action→Obs   │   │
│  │  - Contract │    │  (Sticky)    │    │   (Live Stream)       │   │
│  │  - Guards   │    └──────────────┘    └───────────────────────┘   │
│  └─────────────┘                                                      │
│  ┌──────────┐   ┌──────────────┐   ┌──────────┐   ┌─────────────┐  │
│  │  STEP 1  │   │   STEP 2     │   │   HITL   │   │   STEP 3    │  │
│  │Discovery │──▶│  Tool 1      │──▶│  GATE    │──▶│ Tool 2 + 3  │  │
│  │   Scan   │   │  Extraction  │   │ Approve/ │   │  Risk Report│  │
│  └──────────┘   └──────────────┘   │  Reject  │   └─────────────┘  │
│                                     └──────────┘                     │
└─────────────────────────────────────────────────────────────────────┘
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
   │   TOOL 1     │  │   TOOL 2     │  │   TOOL 3     │
   │  Verbatim    │  │   Hybrid     │  │    Risk      │
   │  Extractor   │  │  Playbook    │  │   Report     │
   │ Gemini LLM   │  │ BM25+Vector  │  │  Gemini LLM  │
   │ + Pydantic   │  │  ChromaDB    │  │  + Pydantic  │
   └──────────────┘  └──────────────┘  └──────────────┘
                              │
                     ┌────────────────┐
                     │   ChromaDB     │
                     │  41 chunks     │
                     │  (Persisted)   │
                     └────────────────┘
```

---

##  Key Features

###  ReAct Agent Pipeline
Three `@tool` decorated LangChain functions called in strict sequential order with a full **Thought → Action → Observation** trace log rendered live in the UI. The factory pattern (`make_tools()`) bakes context into each tool via closure — no global state.

###  Two-Pass Document Analysis
**Pass 1 (Discovery)** is a lightweight LLM call returning only section headings — no content extracted. **Pass 2 (Tool 1)** performs full verbatim extraction of user-selected clauses only.

###  Hybrid RAG Search
BM25 catches exact legal terminology (`Net 30`, `Delaware`, `48 hours`) while vector search catches semantically related text with different wording. The 50/50 ensemble provides maximum recall for legal documents.

###  Human-in-the-Loop (HITL) Gate
Pipeline **structurally halts** after Tool 1. Extracted clause text shown in `st.code()` blocks for review. Every human decision is logged to the ReAct trace. Tools 2 and 3 cannot execute until `hitl_approved == True`.

###  Enterprise Risk Report
Side-by-side verbatim comparison (client LEFT, standard RIGHT), three-level risk classification, risk legend explaining each level, and a guardrail confirmation badge on every card. All verbatim text uses `st.code()` for consistent rendering regardless of source document formatting.

###  Modular Codebase
`app.py` contains only business logic. `ui_components.py` contains only UI rendering. Each can be updated independently.

###  Auto-Reset on Document Change
Selecting a different client contract automatically clears all pipeline state, preventing stale data from contaminating a new analysis.

---

##  Guardrails & Safety Mechanisms

Dual-layer architecture — guardrails in both the LLM prompt AND the Pydantic data validation layer. If the LLM violates a rule, Pydantic raises a `ValueError` before bad data reaches the UI.

### Guardrail 1 — Verbatim Extraction Enforcer
```python
@field_validator("verbatim_text")
def guardrail_no_summary(cls, v: str) -> str:
    # Rejects short text containing summary phrases
    # Triggers on: "this section outlines", "sets forth the terms", etc.
```

### Guardrail 2 — Risk Level Enforcer
```python
@field_validator("risk_level")
def guardrail_risk_level(cls, v: str) -> str:
    # Rejects any value not in {high, medium, low}
```

### Guardrail 3 — Zero Inference Enforcer
```python
@field_validator("factual_conflict")
def guardrail_zero_inference(cls, v: str) -> str:
    # Rejects: "may imply", "could suggest", "appears to",
    # "likely means", "probably", "might indicate"
```

### Guardrail 4 — HITL Structural Gate
```python
if st.session_state.hitl_approved:
    # Tools 2 and 3 only reachable after human approval
```

---

## 🔧 Technology Stack

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| **LLM** | Google Gemini 2.5 Flash | via API | Clause extraction, risk analysis |
| **Embeddings** | Google Gemini Embedding | `gemini-embedding-001` | Semantic vector generation |
| **Agent Framework** | LangChain | 0.3.25 | ReAct agent, tool calling |
| **Vector Database** | ChromaDB | 0.6.3 | Persistent playbook embeddings |
| **Keyword Search** | BM25 (rank_bm25) | 0.2.2 | Exact legal term retrieval |
| **Hybrid Retrieval** | LangChain EnsembleRetriever | 0.3.25 | 50/50 BM25 + vector fusion |
| **Data Validation** | Pydantic | 2.11.4 | Schema enforcement + guardrails |
| **UI Framework** | Streamlit | 1.45.0 | Interactive web application |
| **Document Loading** | PyPDF + docx2txt | 4.3.1 / 0.8 | PDF and Word file parsing |
| **Text Splitting** | LangChain RecursiveCharacterTextSplitter | 0.3.8 | Semantic chunking |
| **Environment** | python-dotenv | 1.1.0 | Secure API key management |

---

##  Prerequisites

- **Python 3.13+** — [Download](https://www.python.org/downloads/)
- **Microsoft Visual C++ Build Tools** — required for `chroma-hnswlib` on Windows
  - Download: https://visualstudio.microsoft.com/visual-cpp-build-tools/
  - Select: **Desktop development with C++**
- **Google Gemini API Key** — [Get one free](https://aistudio.google.com/app/apikey)
- **Git** — [Download](https://git-scm.com/)

```bash
python --version   # Expected: Python 3.13.x
```

---

##  Installation & Setup

### Step 1 — Clone the Repository
```bash
git clone https://github.com/your-username/ai-legal-contract-analyzer.git
cd ai-legal-contract-analyzer
```

### Step 2 — Create Virtual Environment
```bash
python -m venv venv
venv\Scripts\activate
# (venv) should appear at start of terminal prompt
```

### Step 3 — Install Dependencies
```bash
pip install -r requirements.txt
```

>  If you see `error: Microsoft Visual C++ 14.0 or greater is required`, install C++ Build Tools first, then re-run.

### Step 4 — Configure Environment Variables
```bash
copy .env.example .env
```
Open `.env` and fill in:
```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
ANONYMIZED_TELEMETRY=False
```

### Step 5 — Create Directory Structure
```bash
mkdir MyFiles\Contracts\company_standard
mkdir MyFiles\Contracts\clients
```

### Step 6 — Add Your Documents
```
MyFiles/
└── Contracts/
    ├── company_standard/
    │   └── Globex_Corp_Standard_Vendor_Playbook_v4.2.docx
    └── clients/
        ├── ACME_Corp_MSA_LOW_RISK_2025.docx
        └── Initech_Inc_MSA_HIGH_RISK_2025.docx
```

### Step 7 — Build the Vector Database
```bash
python main.py
```

Expected output:
```
[SYSTEM BOOT] Initializing Legal Agent Backend...
  [Contracts root]:        EXISTS
  [Company Playbook dir]:  EXISTS
  [Client Contracts dir]:  EXISTS

[DB SETUP] Found playbook: Globex_Corp_Standard_Vendor_Playbook_v4.2.docx
[DB SETUP] No existing DB found. Creating new vector store...
  -> Reading document: Globex_Corp_Standard_Vendor_Playbook_v4.2.docx...
  -> Success: Document split into 41 logical chunks.
[DB SETUP] Vector database created and persisted! (41 chunks stored)

[SYSTEM BOOT] SUCCESS -- RAG Memory is online and ready.
```

>  Run this step only once, or whenever the company playbook changes.

### Step 8 — Launch the Application
```bash
streamlit run app.py
```
Opens at: **http://localhost:8501**

---

##  Project Structure

```
ai-legal-contract-analyzer/
│
├──  app.py                    # Main entry point — business logic only
│   ├── Section 1:  Environment & path setup
│   ├── Section 2:  Page config + CSS injection call
│   ├── Section 3:  Session state initialisation
│   ├── Section 4:  Pydantic schemas + guardrail validators
│   ├── Section 5:  Utility functions
│   ├── Section 6:  Agent tools factory (make_tools)
│   │   ├── Tool 1: extract_contract_terms()
│   │   ├── Tool 2: query_playbook()
│   │   └── Tool 3: generate_risk_report()
│   ├── Section 7:  Sidebar
│   ├── Section 8:  Page header
│   ├── Section 9:  Pipeline bar      → render_pipeline_bar()
│   ├── Section 10: ReAct trace       → render_trace_panel()
│   ├── Section 11: Step 1 Discovery
│   ├── Section 12: Step 2 Tool 1
│   ├── Section 13: HITL gate         → render_hitl_gate()
│   ├── Section 14: Step 3 Tool 2 + 3
│   └── Section 15: Final report      → render_full_report()
│
├──  ui_components.py          # Pure UI rendering — zero business logic
│   ├── Section 1:  inject_css()
│   ├── Section 2:  render_pipeline_bar()
│   ├── Section 3:  render_trace_panel()
│   ├── Section 4:  render_hitl_gate()
│   └── Section 5:  render_risk_legend()
│                   render_risk_card()
│                   render_full_report()
│
├──  main.py                   # ChromaDB builder — run once
│   ├── Section 1:  Environment initialisation
│   ├── Section 2:  Directory routing
│   ├── Section 3:  load_and_chunk_document()
│   ├── Section 4:  initialize_playbook_db()
│   └── Section 5:  System test execution
│
├──  requirements.txt
├──  .env                      # API keys (NOT committed to Git)
├──  .env.example              # Template for .env setup
├──  .gitignore
├──  README.md
│
├── 📁 MyFiles/Contracts/
│   ├── company_standard/        # Company Playbook (.docx/.pdf)
│   └── clients/                 # Client MSAs/SOWs (.docx/.pdf)
│
├── 📁 chroma_db/                # Auto-generated by main.py (DO NOT commit)
└── 📁 venv/                     # Virtual environment (DO NOT commit)
```

---

##  Module Reference

### `app.py` — Business Logic

| Item | Type | Description |
|------|------|-------------|
| `ClauseList` | Pydantic schema | Pass 1 output — heading names only |
| `ExtractedClause` | Pydantic schema | Single clause with verbatim guardrail validator |
| `ContractData` | Pydantic schema | Full Tool 1 output — list of `ExtractedClause` |
| `RiskAnalysis` | Pydantic schema | Single clause risk card with 2 guardrail validators |
| `FinalRiskReport` | Pydantic schema | Full Tool 3 output — list of `RiskAnalysis` |
| `get_files_from_dir()` | Utility | Scans folder for `.pdf` and `.docx` files |
| `load_doc_text()` | Utility | Loads document, returns full text string |
| `log_step()` | Utility | Appends step to ReAct trace log |
| `reset_pipeline_for_new_client()` | Utility | Clears all session state on client change |
| `run_discovery_scan()` | Utility | Pass 1 — lightweight LLM heading extraction |
| `make_tools()` | Factory | Creates all 3 tools with context baked in via closure |

### `ui_components.py` — UI Rendering

| Function | Description |
|----------|-------------|
| `inject_css()` | Full CSS stylesheet — light enterprise theme, all class names |
| `render_pipeline_bar()` | Sticky 5-stage tracker: ✅ done / 🔄 active / ⏳ waiting / ⭕ idle |
| `render_trace_panel()` | Colour-coded Thought/Action/Observation log expander |
| `render_hitl_gate()` | Pause banner + clause `st.code()` blocks + Approve/Reject buttons |
| `render_risk_legend()` | Three-column HIGH/MEDIUM/LOW classification explanation |
| `render_risk_card(analysis)` | Single clause card — verbatim columns, conflict box, guardrail badge |
| `render_full_report()` | Orchestrates: header → metrics → legend → all cards |

### `main.py` — Vector Store Builder

| Function | Description |
|----------|-------------|
| `load_and_chunk_document(file_path)` | Loads `.pdf` or `.docx`, applies semantic chunking |
| `initialize_playbook_db()` | Builds or loads ChromaDB from the company playbook |
| `validate_directory_structure()` | Checks required folders exist, prints status |

---

## ⚙️ Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | ✅ Yes | Google Gemini API key from Google AI Studio |
| `ANONYMIZED_TELEMETRY` | Optional | Set `False` to silence ChromaDB telemetry messages |

### Chunking Configuration (`main.py`)
```python
RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=150,
    separators=["\n\n", "\n", ".", " ", ""],
)
```

### Retrieval Configuration (`app.py`)
```python
EnsembleRetriever(
    retrievers=[bm25_retriever, vector_retriever],
    weights=[0.5, 0.5],   # Equal weight — tune as needed
)
```

**Tuning:** Increase `k` to `5` for broader recall. Weights `[0.7, 0.3]` favour exact keyword matching; `[0.3, 0.7]` favour semantic matching.

---

##  Usage Guide

**Step 1 — Select Documents** in the sidebar: Company Playbook and Client Contract.

**Step 2 — Run Discovery Scan** — returns section headings only. No clause content extracted yet.

**Step 3 — Select Clauses** — choose 3–5 clauses from the multiselect dropdown.

**Step 4 — Execute Tool 1** — verbatim extraction. Pipeline pauses after this step.

**Step 5 — HITL Review** — inspect each clause in the code block. Click **✅ APPROVE** or **❌ REJECT**.

**Step 6 — Generate Risk Report** — Tool 2 queries the playbook; Tool 3 generates the comparison.

**Step 7 — Read the Report** — each card shows: risk badge, client vs standard verbatim text, factual conflict, guardrail confirmation.

**Step 8 — View ReAct Trace** — expand the 🧠 panel to see the full Thought → Action → Observation chain.

---

##  Agent Pipeline Deep Dive

### Tool 1 — `extract_contract_terms`
1. Loads full contract text via `load_doc_text()`
2. Sends to Gemini with verbatim-only prompt
3. Receives `ContractData` Pydantic object
4. `guardrail_no_summary` validator rejects any condensed text
5. Stores in `session_state.extracted_data`
6. Returns JSON preview to trace log

### Tool 2 — `query_playbook`
1. Loads persisted ChromaDB vector store
2. Creates BM25 retriever from all stored documents
3. Combines into `EnsembleRetriever` (50% BM25 + 50% vector)
4. Queries once per clause topic
5. Returns concatenated playbook standard text

### Tool 3 — `generate_risk_report`
1. Retrieves full verbatim text from `session_state.extracted_data`
2. Builds context block pairing each clause with playbook standard
3. Sends to Gemini with zero-inference guardrail prompt
4. Receives `FinalRiskReport` Pydantic object
5. `guardrail_zero_inference` validator rejects inference language
6. Stores in `session_state.final_report`

---

##  RAG Pipeline Architecture

```
Company Playbook (.docx)
         │
         ▼
[Docx2txtLoader]  →  raw text
         │
         ▼
[RecursiveCharacterTextSplitter]
  chunk_size=1000, overlap=150
  Splits: paragraph → newline → sentence
         │
         ▼
[41 Semantic Chunks]
  Each = one complete legal thought
         │
         ▼
[GoogleGenerativeAIEmbeddings]
  gemini-embedding-001
  768-dimensional vectors
         │
         ▼
[ChromaDB] persisted to ./chroma_db/
```

### Query Process (Tool 2)
```
Clause Topic
     ├────────────────────────┐
     ▼                        ▼
[BM25Retriever]        [VectorRetriever]
  Top 3 keyword            Top 3 semantic
     │                        │
     └──────────┬─────────────┘
                ▼
      [EnsembleRetriever]
       50% BM25 + 50% Vector
                ▼
      Top 6 Deduplicated Chunks
```

---

##  Pydantic Schema Reference

```python
class ExtractedClause(BaseModel):
    clause_name:   str   # Exact heading from document
    verbatim_text: str   # CHARACTER-BY-CHARACTER copy (validated)

class RiskAnalysis(BaseModel):
    clause_name:       str    # Name of analyzed clause
    risk_level:        str    # "High" | "Medium" | "Low" (validated)
    conflict_found:    bool   # True = direct contradiction
    client_verbatim:   str    # Exact quote from client contract
    standard_verbatim: str    # Exact quote from company standard
    factual_conflict:  str    # One literal sentence (inference rejected)
    guardrail_note:    str    # Zero-Inference Rule confirmation
```

| Level | `conflict_found` | Meaning |
|-------|-----------------|---------|
| `High` | `True` | Client text DIRECTLY contradicts standard |
| `Medium` | `False` | Client text SILENT on a required standard |
| `Low` | `False` | Client text FULLY ALIGNED — no deviation |

---

##  Testing the System

### Test Case 1 — Happy Path (ACME Low Risk)
Select `ACME_Corp_MSA_LOW_RISK_2025.docx`. Sections 5, 9, 15 should return LOW. Trace should show all 3 tools executing.

### Test Case 2 — Conflict Detection (Initech High Risk)
Select `Initech_Inc_MSA_HIGH_RISK_2025.docx`. Expect: Payment Terms HIGH (Net 90 vs Net 30), Governing Law HIGH (New York vs Delaware), Liability HIGH (uncapped vs 100% cap), Breach Notification HIGH (7 days vs 48 hours).

### Test Case 3 — HITL Rejection Path
Run Tool 1 → click REJECT → verify `extracted_data` is cleared, `rejected_flag` is True, pipeline returns to Step 2, retry works.

### Test Case 4 — Auto-Reset on Client Change
Complete ACME analysis → switch dropdown to Initech → verify all state is cleared and no ACME data appears.

### Verify ChromaDB
```bash
python -c "
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from dotenv import load_dotenv; import os; load_dotenv()
db = Chroma(persist_directory='./chroma_db',
    embedding_function=GoogleGenerativeAIEmbeddings(
        model='models/gemini-embedding-001',
        google_api_key=os.getenv('GEMINI_API_KEY')))
print(f'ChromaDB chunks: {db._collection.count()}')
# Expected: 41
"
```

---

##  Troubleshooting

### `DefaultCredentialsError`
`.env` missing or API key wrong.
```bash
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('GEMINI_API_KEY')[:10])"
```

### `ModuleNotFoundError: No module named 'langchain.retrievers'`
Wrong LangChain version.
```bash
pip uninstall langchain -y && pip install langchain==0.3.25
```

### `chroma-hnswlib` build failure
Install C++ Build Tools (Desktop development with C++) then re-run `pip install -r requirements.txt`.

### `ImportError: ModelProfile`
```bash
pip uninstall langchain-google-genai -y && pip install langchain-google-genai==2.1.4
```

### ChromaDB telemetry errors in terminal
Harmless. Add `ANONYMIZED_TELEMETRY=False` to `.env`.

### "No files found" in dropdowns
```bash
dir MyFiles\Contracts\company_standard
dir MyFiles\Contracts\clients
```

### ChromaDB empty after `main.py`
```bash
rmdir /s /q chroma_db && python main.py
```

---

##  Dependency Matrix

```
# requirements.txt
# ==========================================
# LEGAL CONTRACT ANALYZER — REQUIREMENTS
# Fixed for Python 3.13 — resolves numpy conflict
# between langchain-community and langchain-chroma
# ==========================================

# Core LangChain Framework
langchain==0.3.25
langchain-community==0.3.24
langchain-core==0.3.63
langchain-text-splitters==0.3.8

# Google Gemini Integration — pinned to match langchain-core 0.3.63
langchain-google-genai==2.1.4

# Vector Database
# langchain-chroma 0.2.x supports numpy>=2.0 — fixes Python 3.13 conflict
langchain-chroma==0.2.3
chromadb==0.6.3

# Hybrid Search (BM25)
rank_bm25==0.2.2

# UI
streamlit==1.45.0

# Data Validation
pydantic==2.11.4

# Environment & Config
python-dotenv==1.1.0

# Document Processing
pypdf==4.3.1
docx2txt==0.8
```

**Why versions are pinned:** The LangChain ecosystem has frequent breaking changes between minor versions. This combination resolves three known conflicts on Python 3.13 Windows: the numpy `>=2.1.0` vs `<2.0.0` clash between `langchain-community` and older `langchain-chroma`; the `langchain-google-genai 4.x` incompatibility with `langchain-core 0.3.x`; and the `EnsembleRetriever` import path change across versions.

---

##  Security Notes

- **Never commit `.env`** — excluded by `.gitignore` by default.
- **API keys passed explicitly** via `google_api_key=GEMINI_API_KEY` — no Google Cloud ADC dependency.
- **ChromaDB is local only** — no contract text sent to third-party database services.
- **Document text sent to Google Gemini API** — ensure contracts comply with your organisation's data handling policies.

---

##  Contributing

1. Fork the repository
2. Create a branch: `git checkout -b feature/your-feature-name`
3. Make changes with docstrings and inline comments
4. Test all four test cases
5. Commit: `git commit -m "feat: describe your change"`
6. Push and open a Pull Request

### Commit Convention
```
feat:     New feature
fix:      Bug fix
docs:     Documentation change
refactor: Code restructure without behavior change
test:     Tests
chore:    Dependencies, config
```

---

##  License

MIT License — see [LICENSE](LICENSE) for details.

---

##  Acknowledgements

[LangChain](https://langchain.com/) · [Google Gemini](https://ai.google.dev/) · [ChromaDB](https://www.trychroma.com/) · [Streamlit](https://streamlit.io/) · [Pydantic](https://docs.pydantic.dev/)

---

<div align="center">

**Built as part of an AI Engineering internship project**
**Demonstrating production-level RAG, ReAct agents, and enterprise guardrails**

</div>
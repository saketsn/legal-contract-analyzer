# Legal Contract Analyzer

> **AI-powered legal contract risk analysis platform** built on a ReAct Agent pipeline with enforced zero-inference guardrails, Human-in-the-Loop (HITL) review, hybrid RAG retrieval, and verbatim-only conflict detection.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Feature List](#feature-list)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Using the Application](#using-the-application)
- [Guardrails System](#guardrails-system)
- [ReAct Agent Pipeline](#react-agent-pipeline)
- [Vector Database (ChromaDB)](#vector-database-chromadb)
- [PDF Export](#pdf-export)
- [Sidebar Legal Assistant (RAG Chatbot)](#sidebar-legal-assistant-rag-chatbot)
- [Troubleshooting](#troubleshooting)
- [Development Notes](#development-notes)

---

## Overview

The **Legal Contract Analyzer** is a Streamlit-based web application that automates the comparison of client contracts against a company's internal legal playbook. It uses a multi-step **ReAct (Reasoning + Acting) agent pipeline** powered by Google Gemini 2.5 Flash to extract, retrieve, and analyze legal clauses — producing a structured **HIGH / MEDIUM / LOW risk report** with verbatim text evidence for every finding.

The system is engineered around a strict **Zero-Inference Rule**: all outputs are grounded exclusively in literal text from source documents. No legal advice, no inferred intent, no hallucinated content.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        STREAMLIT UI (app.py)                    │
│                                                                 │
│  Sidebar                     │  Main Panel                      │
│  ─────────────────────────── │  ─────────────────────────────── │
│  💬 RAG Chatbot              │  Pipeline Status Bar (sticky)    │
│  📂 Document Selection       │  ReAct Trace Log (live)          │
│  📤 File Uploads             │  Step 1: Discovery Scan          │
│  🔧 System Status            │  Step 2: Clause Selection        │
│  🗄️ Playbook DB Builder      │  ⏸️ HITL Gate (Approve/Reject)  │
│                              │  📊 Final Risk Report            │
│                              │  ⬇️ PDF Export                  │
└─────────────────────────────────────────────────────────────────┘

ReAct Agent Tool Chain
──────────────────────
Tool 1: extract_contract_terms   → Verbatim clause extractor (Gemini + Pydantic)
           ↓  [HITL GATE — human reviews, approves or rejects]
Tool 2: query_playbook           → Hybrid BM25 (50%) + Vector (50%) retrieval
           ↓
Tool 3: generate_risk_report     → Factual comparison → HIGH / MEDIUM / LOW

Vector Store
────────────
ChromaDB (persistent, per-playbook subfolder)
  + BM25 keyword retrieval (rank_bm25)
  + Gemini Embeddings (gemini-embedding-001)
  = EnsembleRetriever (hybrid, equal weight)
```

---

## Feature List

### Core Pipeline
- **Discovery Scan** — Lightweight LLM scan that returns only section headings from a client contract (no clause content is extracted at this stage, minimizing token cost)
- **Verbatim Clause Extraction (Tool 1)** — Extracts exact, word-for-word text for each selected section using Gemini 2.5 Flash with structured output (Pydantic `ContractData` schema)
- **Human-in-the-Loop (HITL) Gate** — Pipeline pauses after Tool 1; human reviews all extracted clauses and must explicitly APPROVE or REJECT before analysis continues
- **Hybrid Playbook Retrieval (Tool 2)** — Queries ChromaDB using a 50% BM25 keyword + 50% semantic vector `EnsembleRetriever` for maximum recall
- **Risk Report Generation (Tool 3)** — Compares verbatim client text against playbook standards, classifies each clause as HIGH / MEDIUM / LOW, and produces one factual conflict sentence per clause

### Guardrails (Pydantic-Enforced)
- **Guardrail 1 — No Summary** — Rejects `verbatim_text` fields that look like a summary at the data layer (validator checks for trigger phrases and minimum length)
- **Guardrail 2 — Risk Level Enforcer** — `risk_level` must be exactly `High`, `Medium`, or `Low`; all other values raise a `ValueError`
- **Guardrail 3 — Zero-Inference Rule** — `factual_conflict` is rejected if it contains inference language (`may imply`, `could suggest`, `appears to`, `probably`, etc.)
- **Guardrail 4 — Guardrail Note Confirmation** — Each analysis block must include a verbatim guardrail confirmation statement

### Document Management
- **Multi-format support** — Accepts `.pdf` and `.docx` for both playbooks and client contracts
- **In-app file upload** — Upload playbooks and client contracts directly from the sidebar; files are saved to the correct directory automatically
- **Duplicate upload prevention** — `processed_uploads` session state set prevents duplicate upload warnings on re-render
- **Auto-reset on client change** — Switching to a different client contract automatically clears all pipeline state to prevent stale data contamination

### Vector Database
- **Per-playbook ChromaDB isolation** — Each playbook gets its own `chroma_db/<playbook_stem>/` subfolder; switching playbooks is instant if previously embedded
- **MD5 hash change detection** — On every load, the current file hash is compared against the stored hash; the database is automatically rebuilt if the file has changed
- **Force rebuild button** — UI "Rebuild Playbook DB" button in the sidebar triggers a fresh build for the selected playbook only
- **Hash metadata storage** — Build timestamp, playbook filename, and MD5 hash are stored as JSON in `.playbook_hash` inside each playbook's ChromaDB folder

### UI & UX
- **Sticky pipeline status bar** — 5-stage visual tracker (Discovery → Tool 1 → HITL → Tool 2 → Tool 3) updates in real time with Done ✅ / Active 🔄 / Waiting ⏳ states
- **Live ReAct trace panel** — Collapsible expander shows every Thought / Action / Observation / Human Decision / Final Answer log entry in color-coded blocks
- **Risk cards with side-by-side verbatim comparison** — Each clause card shows client text and company standard text in full monospace boxes (no truncation, no max-height scroll cutoff)
- **Risk level legend** — Persistent HIGH / MEDIUM / LOW explanation cards above the report
- **Summary metrics** — Total / High / Medium / Low clause counts displayed as Streamlit `st.metric` widgets
- **System status panel** — Sidebar shows ChromaDB health, playbook file status, and client contract status at a glance

### PDF Export
- **One-click PDF download** — Generates a structured PDF report using `reportlab` in memory (no temp files)
- **Color-coded risk levels** — RED for HIGH, ORANGE for MEDIUM, GREEN for LOW in the PDF
- **Full verbatim text** — Both client verbatim and company standard verbatim sections are included in monospace font
- **Named file download** — Download filename is derived from the client contract name

### Sidebar Legal Assistant (RAG Chatbot)
- **Always-visible chat panel** — Embedded in the sidebar, available at all times without leaving the main workflow
- **RAG-augmented responses** — Silently queries the active ChromaDB on every message; top-3 most relevant chunks are injected into the system prompt
- **Dynamic system prompt** — Includes current playbook names, selected playbook, and retrieved context per message
- **Quick-start chips** — 6 pre-built question buttons for new users (How to use, list playbooks, liability cap, notice period, guardrails, RAG explanation)
- **Conversation history** — Maintains up to 8 turns of history per session; clear button resets history
- **Graceful RAG fallback** — If ChromaDB is not built yet, chatbot continues to function without RAG context

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI Framework | Streamlit 1.45.0 |
| LLM | Google Gemini 2.5 Flash (`gemini-2.5-flash`) |
| Embeddings | Google Gemini Embedding (`gemini-embedding-001`) |
| Agent Framework | LangChain 0.3.25 + LangChain Tools |
| Vector Store | ChromaDB 0.6.3 via `langchain-chroma` 0.2.3 |
| Keyword Retrieval | BM25 via `rank_bm25` 0.2.2 |
| Data Validation | Pydantic 2.11.4 |
| Document Loaders | `PyPDFLoader`, `Docx2txtLoader` (langchain-community) |
| PDF Generation | ReportLab 4.2.5 |
| Environment | `python-dotenv` 1.1.0 |

---

## Project Structure

```
AI-AGENT-PROJECT/
│
├── app.py                        # Main application entry point
├── chatbot_component.py          # Sidebar RAG chatbot
├── main.py                       # ChromaDB vector store builder
├── ui_components.py              # All Streamlit UI rendering functions
│
├── requirements.txt              # Python dependencies
├── .env                          # Environment variables (not committed)
├── .gitignore
│
├── MyFiles/
│   └── Contracts/
│       ├── company_standard/     # Playbook files (.pdf or .docx)
│       └── clients/              # Client contract files (.pdf or .docx)
│
├── chroma_db/                    # Persisted ChromaDB vector stores
│   └── <playbook_stem>/          # One subfolder per playbook
│       └── .playbook_hash        # MD5 hash + build metadata (JSON)
│
└── venv/                         # Python virtual environment
```

---

## Prerequisites

- **Python 3.11 or 3.12** — Recommended. Python 3.13 is supported but see the note in `requirements.txt` about numpy compatibility.
- **Google Gemini API Key** — Required. Get one at [Google AI Studio](https://aistudio.google.com/).
- A **company standard playbook** document (`.pdf` or `.docx`) to use as the legal baseline.
- One or more **client contract** documents (`.pdf` or `.docx`) to analyze.

---

## Installation

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd AI-AGENT-PROJECT
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
```

Activate it:

```bash
# macOS / Linux
source venv/bin/activate

# Windows (Command Prompt)
venv\Scripts\activate

# Windows (PowerShell)
venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

> **Note for Python 3.13 users:** The `requirements.txt` pins `langchain-chroma==0.2.3` which supports `numpy>=2.0`, resolving the numpy conflict introduced in Python 3.13. No additional steps are needed.

### 4. Create the Required Directory Structure

```bash
mkdir -p MyFiles/Contracts/company_standard
mkdir -p MyFiles/Contracts/clients
```

### 5. Add Your Documents

- Place your **company playbook** (`.pdf` or `.docx`) in `MyFiles/Contracts/company_standard/`
- Place your **client contracts** (`.pdf` or `.docx`) in `MyFiles/Contracts/clients/`

You can also upload files directly from the sidebar after launching the app.

---

## Configuration

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_google_gemini_api_key_here
```

The application will not start without this key. If it is missing, an error banner is shown and execution halts.

---

## Running the Application

### Step 1 — Build the Vector Database

Before the first launch, run the database builder to embed your playbook:

```bash
python main.py
```

Expected output:

```
[SYSTEM BOOT] Initializing Legal Agent Backend...
  [Contracts root]: EXISTS
  [Company Playbook dir]: EXISTS
  [Client Contracts dir]: EXISTS

[DB SETUP] Initializing Company Playbook Database...
[DB SETUP] Found playbook: your_playbook.pdf
[HASH CHECK] Computing file hash...
[HASH CHECK] No existing database. Building for first time...
[DB SETUP] Building new vector store (30-60 seconds)...
  -> Reading: your_playbook.pdf...
  -> Success: 87 chunks created.
[DB SETUP] Database built! (87 chunks stored)
[HASH CHECK] Hash saved.

[SYSTEM BOOT] SUCCESS -- RAG Memory is online and ready.
```

> **Tip:** You only need to run `main.py` once. After that, the app auto-detects changes using MD5 hashing and rebuilds automatically — or you can click "Rebuild Playbook DB" in the sidebar.

### Step 2 — Launch the App

```bash
streamlit run app.py
```

The application opens at `http://localhost:8501` in your browser.

---

## Using the Application

### End-to-End Workflow

**1. Select Documents (Sidebar)**
- Choose your company playbook from the "Company Playbook" dropdown.
- Choose the client contract from the "Client Contract" dropdown.
- Verify the System Status panel shows "ChromaDB Online — Up to date".

**2. Run Discovery Scan (Main Panel — Step 1)**
- Click **Run Discovery Scan**.
- The app performs a lightweight LLM scan and returns all section headings found in the client contract.
- No clause content is extracted at this stage.

**3. Select Sections to Analyze (Step 2)**
- Use the multiselect widget to choose which sections you want to analyze.
- The first 3 sections are pre-selected by default.

**4. Analyze Selected Sections**
- Click **Analyze Selected Sections**.
- Tool 1 runs and extracts verbatim text for each selected section.
- The pipeline **pauses automatically** and the HITL gate appears.

**5. Human Review (HITL Gate)**
- Review each extracted clause in the expandable panels.
- Click **Proceed** to approve and automatically run Tool 2 + Tool 3.
- Click **Go back, discard clauses, and reselect** to reject the extraction and start over.

**6. Automatic Analysis (Tools 2 + 3)**
- Upon approval, Tool 2 queries the playbook via hybrid search.
- Tool 3 generates the full risk report.
- The pipeline status bar advances to stage 5.

**7. Review the Report**
- The final risk report is displayed with summary metrics and individual clause cards.
- Each card shows: risk level, client verbatim text, company standard verbatim text, factual conflict statement, and guardrail confirmation.

**8. Export to PDF**
- Click **⬇ Download PDF Report** (top-right of the report section).
- A structured PDF is downloaded instantly.

### Uploading New Documents

You can upload files directly from the sidebar without touching the filesystem:

- **Upload Playbook** — Saved to `MyFiles/Contracts/company_standard/`. After uploading, select the file from the dropdown and click "Rebuild Playbook DB".
- **Upload Client Contract** — Saved to `MyFiles/Contracts/clients/`. Select from the dropdown to analyze.

Uploading the same file twice is safe — the app detects duplicates and skips re-saving.

---

## Guardrails System

The system enforces four Pydantic-level guardrails that operate at the data layer, independent of the LLM prompt:

### Guardrail 1 — No Summary (Tool 1 Output)

Validates the `verbatim_text` field of each `ExtractedClause`. If the text is shorter than 120 characters **and** contains any of the following trigger phrases, a `ValueError` is raised and the extraction is rejected:

```
"this section outlines", "this clause states", "the parties agree that",
"as described above", "sets forth the terms", "this agreement provides"
```

### Guardrail 2 — Risk Level Enforcer (Tool 3 Output)

The `risk_level` field is validated to be exactly one of: `High`, `Medium`, `Low`. Any other value (e.g., `"Moderate"`, `"Critical"`, `"N/A"`) raises a `ValueError`.

### Guardrail 3 — Zero-Inference Rule (Tool 3 Output)

The `factual_conflict` field is scanned for banned inference phrases:

```
"may imply", "could suggest", "appears to", "seems to",
"likely means", "probably", "it is possible", "might indicate"
```

If any are found, the field is rejected. Only literal, explicit textual differences are permitted.

### Guardrail 4 — Guardrail Note Confirmation

The `guardrail_note` field must contain the exact statement confirming that the analysis is based solely on literal text comparison and that no legal advice or intent inference was provided.

---

## ReAct Agent Pipeline

The pipeline follows the **Reasoning + Acting (ReAct)** pattern. Each tool is created via a factory function (`make_tools`) that bakes in the current session context (selected client, selected clauses, selected playbook) via closures.

```
User selects clauses
        │
        ▼
  [THOUGHT] "Must call Tool 1 to extract verbatim text"
  [ACTION]  extract_contract_terms(clause_list)
  [OBS]     JSON preview of extracted clauses (250 char preview per clause)
        │
        ▼
  ══════════════════════════════
  ⏸️  HITL GATE — Human reviews
      APPROVE → continue
      REJECT  → discard + return to selection
  ══════════════════════════════
        │
        ▼
  [THOUGHT] "Tool 1 approved. Querying playbook RAG with Tool 2."
  [ACTION]  query_playbook(clause_topics)
  [OBS]     Retrieved playbook standard text (500 char preview)
        │
        ▼
  [THOUGHT] "Playbook retrieved. Generating risk report with Tool 3."
  [ACTION]  generate_risk_report(comparison_context)
  [OBS]     JSON summary of all clause risk levels
  [FINAL]   "Report complete. N sections analyzed."
```

All steps are logged to `st.session_state.agent_log` and rendered in the live ReAct trace panel.

---

## Vector Database (ChromaDB)

### How It Works

1. The playbook document is loaded and split into 1000-character chunks with 150-character overlap using `RecursiveCharacterTextSplitter`.
2. Each chunk is embedded using `GoogleGenerativeAIEmbeddings` (`gemini-embedding-001`).
3. Embeddings are persisted to `chroma_db/<playbook_stem>/`.
4. A `.playbook_hash` file (JSON) is written alongside the DB containing the MD5 hash, filename, and build timestamp.

### Hybrid Retrieval (Tool 2)

Tool 2 uses an `EnsembleRetriever` combining:
- **BM25Retriever** (50% weight) — keyword-based sparse retrieval over the full document set
- **Chroma vector retriever** (50% weight) — semantic dense retrieval, top-3 results

This hybrid approach ensures that both exact legal terminology (BM25 strength) and semantic similarity (vector strength) contribute to each query.

### Per-Playbook Isolation

Each playbook file gets its own ChromaDB subfolder named after the playbook stem (with special characters replaced by underscores). This means:
- Switching playbooks does not require a rebuild if that playbook was previously embedded
- Rebuilding one playbook does not affect other playbooks
- The UI "System Status" panel checks the correct subfolder for the currently selected playbook

---

## PDF Export

The PDF report is generated entirely in-memory using `reportlab` and served via Streamlit's `st.download_button`. No temporary files are written to disk.

Report contents:
- Header with analyzed document name
- Per-clause sections with: risk level (color-coded), factual conflict statement, client verbatim text (monospace), company standard verbatim text (monospace)
- Horizontal rule separators between clauses

---

## Sidebar Legal Assistant (RAG Chatbot)

The chatbot (`chatbot_component.py`) runs as an embedded sidebar panel using Gemini 2.5 Flash. On every message:

1. If a playbook is selected and its ChromaDB exists, the user's message is used to query ChromaDB for top-3 relevant chunks.
2. Retrieved chunks are injected into a dynamic system prompt alongside current application state (playbook names, selected playbook).
3. The LLM responds with context from the actual playbook document.
4. If ChromaDB is not built, the chatbot falls back to general knowledge about the application.

This means users can ask questions like "What is the liability cap in our playbook?" and receive answers grounded in the actual document text.

---

## Troubleshooting

### "ChromaDB Online — No hash record" in System Status
The database exists but was built without hash metadata (older build). Click **Rebuild Playbook DB** to regenerate with a hash file.

### "No DB for this playbook — click Rebuild Playbook DB"
No ChromaDB exists for the currently selected playbook. Either run `python main.py` from the terminal or click **Rebuild Playbook DB** in the sidebar.

### Extraction feels too short / summarized
Tool 1 extracted a summary instead of verbatim text. This can happen with very large contracts. The Pydantic validator will catch obvious summaries. If it passes but still looks like a summary, try selecting fewer clauses per run, or split the analysis into multiple runs.

### "GUARDRAIL: verbatim_text is a summary"
Pydantic rejected the LLM output for that clause because it detected summary language. Click **Reject** in the HITL gate, re-select the clause, and re-analyze. On retry, the LLM usually produces a more faithful extraction.

### Chatbot gives generic answers instead of playbook-specific answers
The ChromaDB for the selected playbook has not been built yet. Click **Rebuild Playbook DB** and wait for the build to complete before asking playbook-specific questions.

### Upload shows "already exists" warning on every page refresh
This is expected behavior. The `processed_uploads` set is per-session. Refreshing the page resets the session. The file is not re-written if it already exists on disk — only the warning reappears.

### `ValueError: CRITICAL: GEMINI_API_KEY is not set`
The `.env` file is missing or the key is not named `GEMINI_API_KEY`. Check that `.env` exists in the project root and contains a valid key.

---

## Development Notes

### Module Responsibilities

| File | Responsibility |
|---|---|
| `app.py` | Application entry point, session state, sidebar, pipeline orchestration, all Streamlit callbacks |
| `ui_components.py` | Pure presentation layer — zero business logic, zero LLM calls (except HITL state writes) |
| `chatbot_component.py` | Sidebar chatbot with RAG — self-contained, imported once by `app.py` |
| `main.py` | ChromaDB builder — can be run standalone (`python main.py`) or called by `app.py` via `initialize_playbook_db()` |

### Session State Keys

| Key | Type | Purpose |
|---|---|---|
| `discovered_clauses` | `list[str]` | Section headings from discovery scan |
| `extracted_data` | `ContractData` | Tool 1 output (Pydantic model) |
| `hitl_approved` | `bool` | Whether human has approved Tool 1 output |
| `rejected_flag` | `bool` | Whether human rejected the extraction |
| `final_report` | `FinalRiskReport` | Tool 3 output (Pydantic model) |
| `agent_log` | `list[dict]` | ReAct trace entries |
| `selected_client` | `str` | Currently selected client contract filename |
| `selected_clauses` | `list[str]` | Clauses selected for analysis |
| `tool2_result` | `str` | Raw playbook retrieval text from Tool 2 |
| `pipeline_stage` | `int` | Current pipeline stage (0–4) |
| `last_client` | `str` | Previous client (for auto-reset detection) |
| `processed_uploads` | `set` | Filenames already processed this session |
| `chatbot_history` | `list[dict]` | Sidebar chatbot conversation history |

### Adding a New Guardrail

1. Add a `@field_validator` to the relevant Pydantic model in `app.py` Section 4.
2. Add the guardrail description to the LLM prompt in the relevant tool in Section 7.
3. Verify the guardrail activates by testing with a prompt that should fail.

### Adding a New Tool

1. Define the tool function inside `make_tools()` using the `@tool` decorator.
2. Add `log_step()` calls for Thought, Action, and Observation.
3. Append the new tool to the returned list.
4. Add the corresponding pipeline stage and status bar entry in `ui_components.py`.

---


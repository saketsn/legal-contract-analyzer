# Legal Contract Analyzer

> **AI-powered legal contract risk analysis platform** built on a ReAct Agent pipeline with enforced zero-inference guardrails, Human-in-the-Loop (HITL) review, hybrid RAG retrieval, verbatim-only conflict detection, and a full admin panel with department-wise document management and LLM token analytics.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Setup & Installation](#setup--installation)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Using the Main App](#using-the-main-app)
- [Using the Admin Panel](#using-the-admin-panel)
- [Guardrails & Safety Rules](#guardrails--safety-rules)
- [RAG Implementation](#rag-implementation)
- [Database Design](#database-design)
- [API & Token Cost Reference](#api--token-cost-reference)
- [Git Tags & Versioning](#git-tags--versioning)
- [Known Limitations](#known-limitations)
- [Future Improvements](#future-improvements)

---

## Overview

The Legal Contract Analyzer is a single-agent AI application that acts as an automated legal analyst. It compares client contracts (MSAs, SOWs) against a company's internal standard playbook and produces a structured, clause-level risk report — with zero tolerance for inference, summarization, or legal advice.

The system is built around a strict **ReAct (Reasoning and Acting)** loop that enforces a sequential, auditable tool-calling pipeline. Every risk flag must include the exact verbatim text from the source document. The agent is forbidden from inferring legal intent.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Streamlit UI (app.py)                    │
│                                                                 │
│  Sidebar: Dept Filter → Playbook Select → Client Contract       │
│           Legal Assistant Chatbot (RAG-powered)                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  Discovery Scan  │  (lightweight heading extractor)
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │    Tool 1        │  extract_contract_terms()
                    │  Verbatim        │  → Pydantic: ContractData
                    │  Extraction      │  → GUARDRAIL: no summaries
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   HITL Gate      │  Human must APPROVE or REJECT
                    │  (pipeline       │  before proceeding
                    │   paused)        │
                    └────────┬────────┘
                             │  APPROVED
                    ┌────────▼────────┐
                    │    Tool 2        │  query_playbook()
                    │  Hybrid RAG      │  → BM25 + ChromaDB vector search
                    │  Retrieval       │  → Returns playbook standards
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │    Tool 3        │  generate_risk_report()
                    │  Risk Report     │  → Pydantic: FinalRiskReport
                    │  Generator       │  → HIGH / MEDIUM / LOW per clause
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Final Report    │  Rendered in UI + PDF export
                    │  + Logging       │  → token_log.json + history_log.json
                    └─────────────────┘
```

**Admin Panel** (`pages/admin.py`) runs as a separate Streamlit page with a password gate. It reads from the same log files and SQLite database but never touches the main pipeline.

---

## Features

### Main Application

- **5-Stage ReAct Pipeline** — Discovery Scan → Tool 1 → HITL Gate → Tool 2 → Tool 3
- **Verbatim-Only Extraction** — Pydantic validators enforce character-for-character copying, rejecting any summarization attempt at the schema layer
- **Zero-Inference Rule** — The agent is forbidden from inferring intent; it only reports literal textual contradictions
- **Human-in-the-Loop (HITL) Gate** — Pipeline pauses after Tool 1; user reviews extracted clauses and must explicitly Approve or Reject before analysis proceeds
- **Hybrid RAG Retrieval** — Tool 2 combines BM25 keyword search and ChromaDB vector search (50/50 ensemble) for more accurate playbook standard retrieval
- **Semantic Chunking** — Playbook documents are chunked using paragraph-first separators to preserve complete legal clauses within a single chunk
- **Department-wise Contract Management** — Client contracts organised into department subfolders; sidebar filters by department
- **Legal Assistant Chatbot** — RAG-powered sidebar chatbot that answers questions about the active playbook using ChromaDB similarity search
- **PDF Risk Report Export** — One-click download of the full risk assessment report as a formatted PDF
- **Auto-rebuild Detection** — ChromaDB uses MD5 hashing to detect playbook file changes and auto-rebuilds only when necessary

### Admin Panel

- **Password-protected access** — 5-attempt lockout with 60-second cooldown
- **Department Management** — Create, rename, edit departments with head name / email / phone (all required, production-level validated)
- **Contract File Management** — Browse, filter, move, and delete contracts by department; global filename uniqueness enforced across all departments
- **Playbook Management** — Upload, delete, or wipe ChromaDB for any playbook
- **Token Usage Analytics** — Per-tool token breakdown, cost estimates, daily usage charts (Bar/Line toggle, expandable), date range picker
- **Analysis History Log** — Full pipeline run history with clause-level risk detail, searchable and filterable
- **Downloadable Reports** — PDF and Excel exports with overview metrics, token breakdown, department file listing, history, and raw token log
- **SQLite Department Store** — Department metadata stored in `dept.db` with WAL mode for safe concurrent access

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI Framework | Streamlit |
| LLM | Google Gemini 2.5 Flash (`gemini-2.5-flash`) |
| Embeddings | Google Gemini Embedding (`models/gemini-embedding-001`) |
| Agent Framework | LangChain |
| Vector Store | ChromaDB (persistent, local) |
| Keyword Search | BM25 (via `langchain-community`) |
| Schema Validation | Pydantic v2 |
| Document Loading | PyPDFLoader, Docx2txtLoader |
| Department DB | SQLite (via Python `sqlite3`, WAL mode) |
| PDF Generation | ReportLab |
| Excel Generation | openpyxl |
| Environment Config | python-dotenv |

---

## Project Structure

```
AI-AGENT-PROJECT/
│
├── app.py                    # Main application entry point
├── main.py                   # ChromaDB vector store builder
├── logger.py                 # Append-only JSON event logger
├── dept_db.py                # SQLite department metadata layer
├── chatbot_component.py      # Sidebar Legal Assistant chatbot
├── ui_components.py          # All Streamlit UI rendering functions
│
├── pages/
│   └── admin.py              # Admin panel (password-protected)
│
├── MyFiles/
│   └── Contracts/
│       ├── company_standard/ # Playbook files (.docx / .pdf)
│       └── clients/          # Client contracts, organised by dept
│           ├── Engineering/
│           ├── Finance/
│           ├── HR/
│           └── ...
│
├── chroma_db/                # Persisted ChromaDB vector stores
│   └── <playbook_stem>/      # One subfolder per playbook
│       ├── .playbook_hash    # MD5 hash + build timestamp
│       └── chroma.sqlite3
│
├── dept.db                   # SQLite department metadata (gitignored)
├── token_log.json            # LLM token usage log (gitignored)
├── history_log.json          # Pipeline run history (gitignored)
│
├── .env                      # API keys and admin password (gitignored)
├── .gitignore
└── requirements.txt
```

---

## Setup & Installation

### Prerequisites

- Python 3.10 or higher
- A Google Gemini API key ([get one here](https://aistudio.google.com/app/apikey))

### 1. Clone the repository

```bash
git clone https://github.com/saketsn/legal-contract-analyzer.git
cd legal-contract-analyzer
```

### 2. Create and activate a virtual environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create the required folder structure

```bash
mkdir -p "MyFiles/Contracts/company_standard"
mkdir -p "MyFiles/Contracts/clients"
```

### 5. Add your documents

- Place your **company standard playbook** (`.docx` or `.pdf`) inside `MyFiles/Contracts/company_standard/`
- Place your **client contracts** (`.docx` or `.pdf`) inside `MyFiles/Contracts/clients/` or in a department subfolder

### 6. Configure environment variables

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key_here
ADMIN_PASSWORD=your_admin_password_here
```

### 7. Build the ChromaDB vector store

```bash
python main.py
```

You should see:
```
[SYSTEM BOOT] SUCCESS -- RAG Memory is online and ready.
```

---

## Configuration

| Variable | File | Description |
|---|---|---|
| `GEMINI_API_KEY` | `.env` | Google Gemini API key (required) |
| `ADMIN_PASSWORD` | `.env` | Admin panel login password (default: `admin123`) |
| `CONTRACTS_DIR` | `app.py` / `main.py` | Root path for all contract documents |
| `CHROMA_PERSIST_DIR` | `app.py` / `main.py` | Path for ChromaDB persistence |
| `PRICE_INPUT_PER_1M` | `logger.py` | Gemini input token price (USD per 1M tokens) |
| `PRICE_OUTPUT_PER_1M` | `logger.py` | Gemini output token price (USD per 1M tokens) |

---

## Running the Application

```bash
streamlit run app.py
```

The app opens at `http://localhost:8501` by default.

To access the **Admin Panel**, click the **⚙ Admin Panel** button at the top of the sidebar and enter the password set in `.env`.

---

## Using the Main App

### Step 1 — Select Documents

In the sidebar:
1. Select a **Department** (or leave as "All departments")
2. Select the **Company Playbook** to use as the standard
3. Select the **Client Contract** to analyse
4. Optionally upload new files using the file upload widgets

### Step 2 — Run Discovery Scan

Click **Run Discovery Scan**. The agent makes a lightweight LLM call to extract all section headings from the client contract. No clause content is extracted at this stage.

### Step 3 — Select Clauses

From the discovered headings, select the specific clauses you want to analyse using the multiselect dropdown.

### Step 4 — Analyse

Click **Analyse Selected Sections**. Tool 1 runs and extracts verbatim text for each selected clause. The pipeline then **pauses** at the HITL Gate.

### Step 5 — HITL Review

Review the verbatim-extracted clauses displayed on screen. Click:
- **Proceed** — approves the extraction; Tools 2 and 3 run automatically
- **Go back, discard and reselect** — discards the extraction; re-select clauses and try again

### Step 6 — View Report

The final risk report appears with HIGH / MEDIUM / LOW classification per clause, verbatim quotes from both the client contract and company standard, and a one-sentence factual conflict statement. Download as PDF using the **Download PDF Report** button.

---

## Using the Admin Panel

### Access

Click **⚙ Admin Panel** in the sidebar → enter password → you are in.

### Tab 1 — Documents

- **Summary metrics** — department count, total contracts, unanalyzed count
- **Client Contracts table** — filter by department, search by filename, filter by analyzed/unanalyzed status; move files between departments or delete
- **Upload Contract** — upload a new client contract to a specific department (global filename uniqueness enforced)
- **Manage Departments** — create new departments (head name, email, phone all required); edit existing department head details including renaming
- **Company Playbooks** — view playbook files, wipe ChromaDB (keeps file), or delete completely (removes file and DB)

### Tab 2 — Token Usage

- Summary metrics: total tokens, estimated cost, API calls, average duration
- Token usage by tool — bar or line chart (expandable), per-tool breakdown table
- Daily token usage chart
- Raw token log with tool filter
- Calendar date range picker to filter any period

### Tab 3 — History

- Summary: total runs, high-risk runs, average clauses per run, top department
- Filter by filename or department
- Expandable run cards showing clause-level risk detail
- Delete individual runs

### Tab 4 — Export

- Select any date range using the calendar picker
- Generate a full **PDF report** (5 sections: overview, token breakdown, dept files, history, raw log)
- Generate a full **Excel report** (5 sheets with the same data, color-coded risk cells)

---

## Guardrails & Safety Rules

The system enforces four hard guardrails at the Pydantic schema layer — not just in the prompt:

### Guardrail 1 — Mandatory Verbatim Quotation

`verbatim_text` in `ExtractedClause` is validated by a `@field_validator` that rejects responses matching known summarization patterns (e.g. "this section outlines", "the parties agree that"). If the LLM summarizes instead of copying, the Pydantic validation fails and the pipeline raises an error.

### Guardrail 2 — Zero-Inference Rule

`factual_conflict` in `RiskAnalysis` is validated against a list of banned inference phrases: "may imply", "could suggest", "appears to", "seems to", "likely means", "probably", "it is possible", "might indicate". Any response containing these phrases fails validation.

### Guardrail 3 — Risk Level Enforcement

`risk_level` must be exactly `High`, `Medium`, or `Low` (case-insensitive, then capitalized). Any other value fails validation immediately.

### Guardrail 4 — Guardrail Confirmation

`guardrail_note` must explicitly state:
> *"Analysis based solely on literal text comparison. No legal advice provided. No intent inferred."*

This is enforced in the system prompt and verified in the output structure.

---

## RAG Implementation

### Playbook Chunking (`main.py`)

Documents are split using `RecursiveCharacterTextSplitter` with a paragraph-first separator hierarchy:

```python
separators=["\n\n", "\n", ".", " ", ""]
chunk_size=1000
chunk_overlap=150
```

This ensures complete legal clauses are preserved within a single chunk rather than being split at arbitrary token counts.

### Hybrid Retrieval (`app.py` — Tool 2)

Tool 2 uses an `EnsembleRetriever` combining:
- **BM25** (keyword matching, weight 0.5) — good for exact legal terminology
- **ChromaDB vector search** (semantic matching, weight 0.5) — good for conceptually similar clauses

Each clause topic is queried independently against the ensemble retriever with `k=3` results per retriever, giving up to 6 unique playbook passages per clause.

### Change Detection (`main.py`)

Each playbook gets its own ChromaDB subfolder named after the playbook stem (sanitised). An MD5 hash of the playbook file is stored in `.playbook_hash`. On startup, the hash is recomputed. If it matches — load from disk. If it differs — delete old DB and rebuild automatically. This means replacing a playbook file and clicking "Rebuild" is all that's needed.

---

## Database Design

### SQLite — `dept.db`

Used for department metadata. WAL (Write-Ahead Logging) mode enabled for safe concurrent reads.

```sql
CREATE TABLE departments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    UNIQUE NOT NULL,
    head_name   TEXT    NOT NULL DEFAULT '',
    head_email  TEXT    NOT NULL DEFAULT '',
    head_phone  TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
```

### JSON Logs

| File | Purpose | Written by | Read by |
|---|---|---|---|
| `token_log.json` | One entry per LLM API call | `logger.log_token_event()` | Admin Tab 2, Tab 4 |
| `history_log.json` | One entry per completed pipeline run | `logger.log_run()` | Admin Tab 3, Tab 4 |

Both files are append-only. All write operations are wrapped in `try/except` so a logging failure can never crash the main pipeline.

---

## API & Token Cost Reference

Token costs are estimated using character-count approximation (`len(text) // 4 ≈ tokens`) and Gemini 2.5 Flash pricing:

| Token Type | Price |
|---|---|
| Input tokens | $0.075 per 1M tokens |
| Output tokens | $0.30 per 1M tokens |

To update pricing, edit the constants in `logger.py`:

```python
PRICE_INPUT_PER_1M  = 0.075
PRICE_OUTPUT_PER_1M = 0.30
```

---

## Git Tags & Versioning

| Tag | Description |
|---|---|
| `v1.0-working-baseline` | Original working pipeline — before admin panel addition |
| `v2.0-admin-panel-complete` | Full admin panel with all 4 tabs, department management, SQLite, exports |

To revert to a previous tag:

```bash
# Go back to v1 (original pipeline only)
git checkout v1.0-working-baseline

# Go back to v2 (with admin panel)
git checkout v2.0-admin-panel-complete

# Return to latest
git checkout main
```

---

## Known Limitations

- **Token count approximation** — Token counts are estimated using character length divided by 4. Actual counts may vary by ±10–15%. The Gemini LangChain wrapper does expose `usage_metadata` for exact counts — this can be integrated in a future update.
- **Concurrent write safety** — `token_log.json` and `history_log.json` use simple file-level read/write. Under high concurrent load (multiple users finishing a pipeline simultaneously), a last-write-wins race condition is possible. Migrating logs to SQLite would resolve this.
- **ChromaDB rebuild lock** — If two users trigger a playbook rebuild simultaneously, both will attempt to delete and recreate the same ChromaDB subfolder. A file lock around the rebuild process would prevent this.
- **Single server deployment** — The application is designed for single-server use. It is not horizontally scalable in its current form.

---

## Future Improvements

- Exact token counts from Gemini `usage_metadata` API response field
- Migrate `token_log.json` and `history_log.json` to SQLite for concurrent-safe logging
- ChromaDB rebuild mutex lock for multi-user safety
- Role-based access control (analyst vs admin vs read-only)
- Email notification when a HIGH risk clause is detected
- Batch contract analysis (process multiple contracts against the same playbook)
- Contract comparison mode (compare two versions of the same contract)
- Audit trail — track which human approved which HITL gate and when
- Docker containerisation for one-command deployment

---

## License

This project was built as part of an AI engineering internship. All rights reserved.

---

*Built with LangChain · Google Gemini · ChromaDB · Streamlit · ReportLab · SQLite*
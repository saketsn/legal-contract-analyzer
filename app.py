"""
================================================================================
app.py -- Main Application Entry Point
================================================================================
Architecture : ReAct Agent Pipeline (Tool 1 -> HITL Gate -> Tool 2 -> Tool 3)
Guardrails   : Zero-Inference Rule + Mandatory Verbatim Quotation (Pydantic)
UI           : Imported from ui_components.py (purely presentational)

Flow:
    1. Run Discovery Scan
    2. Select clauses -> click "Analyze Selected Sections"
       -> Tool 1 runs -> HITL gate appears
    3. APPROVE -> Tool 2 + Tool 3 run automatically -> Report shown
       REJECT  -> Error message, user re-selects and re-analyzes

Run:
    streamlit run app.py
================================================================================
"""

import json
import os
import glob
import html
import time
from io import BytesIO

import streamlit as st
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from typing import List

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
from langchain.tools import tool

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors

from main import initialize_playbook_db
from chatbot_component import render_chatbot
from ui_components import (
    inject_css,
    render_pipeline_bar,
    render_trace_panel,
    render_hitl_gate,
    render_full_report,
)
import logger

# ==========================================
# SECTION 1: ENVIRONMENT & PATHS
# ==========================================
load_dotenv()

GEMINI_API_KEY       = os.getenv("GEMINI_API_KEY")
BASE_DIR             = os.path.dirname(os.path.abspath(__file__))
CONTRACTS_DIR        = os.path.join(BASE_DIR, "MyFiles", "Contracts")
COMPANY_PLAYBOOK_DIR = os.path.join(CONTRACTS_DIR, "company_standard")
CLIENT_CONTRACTS_DIR = os.path.join(CONTRACTS_DIR, "clients")
CHROMA_PERSIST_DIR   = os.path.join(BASE_DIR, "chroma_db")

# ==========================================
# SECTION 2: PAGE CONFIG
# ==========================================
st.set_page_config(
    page_title="Legal Contract Analyzer",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={}
)

inject_css()

st.markdown("""
    <style>
    [data-testid="stSidebarNav"] { display: none !important; }
    </style>
""", unsafe_allow_html=True)

if not GEMINI_API_KEY:
    st.error(" CRITICAL: GEMINI_API_KEY not found in .env file. Add it and restart.")
    st.stop()

# ==========================================
# SECTION 3: SESSION STATE
# ==========================================
SESSION_DEFAULTS = {
    "discovered_clauses":  [],
    "extracted_data":      None,
    "hitl_approved":       False,
    "rejected_flag":       False,
    "final_report":        None,
    "agent_log":           [],
    "selected_client":     None,
    "selected_clauses":    [],
    "tool2_result":        None,
    "pipeline_stage":      0,
    "last_client":         None,
    "last_department":     None,
    "processed_uploads":   set(),
    "selected_department": "",
    "run_token_total":     0,
}
for key, value in SESSION_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

# ==========================================
# SECTION 4: PYDANTIC SCHEMAS
# ==========================================

class ClauseList(BaseModel):
    clauses: List[str] = Field(
        description="All main legal section headings in the document."
    )


class ExtractedClause(BaseModel):
    clause_name:   str = Field(description="Exact heading name from the document.")
    verbatim_text: str = Field(description="EXACT word-for-word text. No summarization.")

    @field_validator("verbatim_text")
    @classmethod
    def guardrail_no_summary(cls, v: str) -> str:
        if v.strip() == "Clause Not Present":
            return v
        triggers = [
            "this section outlines", "this clause states",
            "the parties agree that", "as described above",
            "sets forth the terms", "this agreement provides",
        ]
        if len(v) < 120 and any(t in v.lower() for t in triggers):
            raise ValueError(f"GUARDRAIL: verbatim_text is a summary. Got: '{v}'")
        return v


class ContractData(BaseModel):
    extracted_clauses: List[ExtractedClause]


class RiskAnalysis(BaseModel):
    clause_name:       str  = Field(description="Name of the analyzed clause.")
    risk_level:        str  = Field(description="Exactly: High, Medium, or Low")
    conflict_found:    bool = Field(description="True=direct contradiction. False=gap or aligned.")
    client_verbatim:   str  = Field(description="EXACT quoted text from client contract.")
    standard_verbatim: str  = Field(description="EXACT quoted text from company standard.")
    factual_conflict:  str  = Field(description="One literal sentence. No inference.")
    guardrail_note:    str  = Field(description="Confirms Zero-Inference Rule was applied.")

    @field_validator("risk_level")
    @classmethod
    def guardrail_risk_level(cls, v: str) -> str:
        if v.strip().lower() not in {"high", "medium", "low"}:
            raise ValueError(f"GUARDRAIL: risk_level must be High/Medium/Low. Got: '{v}'")
        return v.strip().capitalize()

    @field_validator("factual_conflict")
    @classmethod
    def guardrail_zero_inference(cls, v: str) -> str:
        banned = ["may imply", "could suggest", "appears to", "seems to",
                  "likely means", "probably", "it is possible", "might indicate"]
        found = [p for p in banned if p in v.lower()]
        if found:
            raise ValueError(f"GUARDRAIL: Zero-Inference violated: {found}")
        return v


class FinalRiskReport(BaseModel):
    analyses: List[RiskAnalysis]


# ==========================================
# SECTION 5: UTILITY FUNCTIONS
# ==========================================

def get_departments() -> list:
    """Returns sorted list of department subfolder names inside clients/."""
    if not os.path.exists(CLIENT_CONTRACTS_DIR):
        return []
    return sorted([
        d for d in os.listdir(CLIENT_CONTRACTS_DIR)
        if os.path.isdir(os.path.join(CLIENT_CONTRACTS_DIR, d))
    ])


def get_all_client_filenames() -> set:
    """
    Returns set of ALL client contract filenames across ALL departments
    and the flat clients/ root. Used for global uniqueness enforcement.
    """
    names = set()
    for ext in ["*.pdf", "*.docx"]:
        for f in glob.glob(os.path.join(CLIENT_CONTRACTS_DIR, ext)):
            names.add(os.path.basename(f))
    for dept in get_departments():
        dept_dir = os.path.join(CLIENT_CONTRACTS_DIR, dept)
        for ext in ["*.pdf", "*.docx"]:
            for f in glob.glob(os.path.join(dept_dir, ext)):
                names.add(os.path.basename(f))
    return names


def find_file_department(filename: str) -> str:
    """
    Returns the department name where a filename lives,
    'clients/ (root)' if flat, or '' if not found.
    """
    if os.path.exists(os.path.join(CLIENT_CONTRACTS_DIR, filename)):
        return "clients/ (root)"
    for dept in get_departments():
        if os.path.exists(os.path.join(CLIENT_CONTRACTS_DIR, dept, filename)):
            return dept
    return ""


def get_files_from_dir(directory: str) -> list:
    """Returns sorted basenames of all .pdf and .docx files in a directory."""
    if not os.path.exists(directory):
        return []
    return sorted([
        os.path.basename(f)
        for f in glob.glob(os.path.join(directory, "*.pdf"))
        + glob.glob(os.path.join(directory, "*.docx"))
    ])


def get_client_files_for_department(selected_dept: str) -> list:
    """
    Returns sorted list of client contract filenames based on department filter.
    - "" or "All departments" -> ALL files from ALL subfolders + flat root
    - specific dept name      -> only files in that dept subfolder
    """
    if not selected_dept or selected_dept == "All departments":
        all_files = set()
        for ext in ["*.pdf", "*.docx"]:
            for f in glob.glob(os.path.join(CLIENT_CONTRACTS_DIR, ext)):
                all_files.add(os.path.basename(f))
        for dept in get_departments():
            dept_dir = os.path.join(CLIENT_CONTRACTS_DIR, dept)
            for ext in ["*.pdf", "*.docx"]:
                for f in glob.glob(os.path.join(dept_dir, ext)):
                    all_files.add(os.path.basename(f))
        return sorted(list(all_files))
    else:
        dept_dir = os.path.join(CLIENT_CONTRACTS_DIR, selected_dept)
        return get_files_from_dir(dept_dir)


def find_client_file_path(filename: str) -> str:
    """
    Finds the full path of a client contract by searching
    flat root and all department subfolders.
    """
    flat_path = os.path.join(CLIENT_CONTRACTS_DIR, filename)
    if os.path.exists(flat_path):
        return flat_path
    for dept in get_departments():
        dept_path = os.path.join(CLIENT_CONTRACTS_DIR, dept, filename)
        if os.path.exists(dept_path):
            return dept_path
    return flat_path


def load_doc_text(file_path: str) -> str:
    """Loads a PDF or .docx document and returns its full text."""
    loader = (
        PyPDFLoader(file_path)
        if file_path.lower().endswith(".pdf")
        else Docx2txtLoader(file_path)
    )
    return "\n".join([p.page_content for p in loader.load()])


def log_step(role: str, content: str, status: str = "thought") -> None:
    """Appends one step to the ReAct trace log."""
    st.session_state.agent_log.append({
        "role": role, "content": content, "status": status,
    })


def reset_pipeline_for_new_client() -> None:
    """Clears all pipeline state when user selects a different client or department."""
    st.session_state.discovered_clauses = []
    st.session_state.extracted_data     = None
    st.session_state.hitl_approved      = False
    st.session_state.rejected_flag      = False
    st.session_state.final_report       = None
    st.session_state.agent_log          = []
    st.session_state.selected_clauses   = []
    st.session_state.tool2_result       = None
    st.session_state.pipeline_stage     = 0
    st.session_state.run_token_total    = 0


def run_discovery_scan(file_name: str, file_path: str) -> list:
    """
    Pass 1: Lightweight LLM scan returning section headings only.
    Accepts full file_path to support department subfolders.
    """
    full_text = load_doc_text(file_path)
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash", temperature=0, google_api_key=GEMINI_API_KEY
    )

    _t0     = time.time()
    result  = llm.with_structured_output(ClauseList).invoke(
        "You are a legal document parser. "
        "Extract ALL main section headings from this contract. "
        "Return ONLY heading names — no clause content.\n\n" + full_text
    )
    _dur_ms = int((time.time() - _t0) * 1000)

    _approx_in  = len(full_text) // 4
    _approx_out = len(str(result.clauses)) // 4
    logger.log_token_event(
        tool_name="Discovery Scan",
        input_tokens=_approx_in,
        output_tokens=_approx_out,
        duration_ms=_dur_ms,
        client_file=file_name,
        playbook_file=st.session_state.get("playbook_select", ""),
        department=st.session_state.get("selected_department", ""),
    )
    st.session_state.run_token_total += _approx_in + _approx_out

    return result.clauses


def save_uploaded_file(uploaded_file, target_dir: str,
                       is_client_file: bool = False) -> tuple[bool, str]:
    """
    Saves an uploaded file with smart duplicate detection.

    For CLIENT files (is_client_file=True):
        Enforces GLOBAL uniqueness — same filename cannot exist in ANY department.

    For PLAYBOOK files (is_client_file=False):
        Only checks within company_standard/ folder.
    """
    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)

    if is_client_file:
        # Global uniqueness check across ALL departments + flat root
        all_existing = get_all_client_filenames()
        if uploaded_file.name in all_existing:
            existing_dept = find_file_department(uploaded_file.name)
            return (
                False,
                f"⚠️ **'{uploaded_file.name}'** already exists in **{existing_dept}**.\n\n"
                f"Filenames must be unique across all departments. "
                f"Please rename the file before uploading.",
            )
    else:
        # Standard check — only within target directory
        file_path = os.path.join(target_dir, uploaded_file.name)
        if os.path.exists(file_path):
            return (False, f"⚠️ File '{uploaded_file.name}' already exists. Skipping upload.")

    file_path = os.path.join(target_dir, uploaded_file.name)
    try:
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        return (True, f"✅ Uploaded '{uploaded_file.name}' successfully!")
    except Exception as e:
        return (False, f"❌ Upload failed: {str(e)}")


# ==========================================
# SECTION 6: PDF GENERATOR FUNCTION
# ==========================================
def generate_pdf_report(report_data: FinalRiskReport, client_name: str) -> BytesIO:
    """Generates a structured PDF from the FinalRiskReport object using reportlab."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER,
                            rightMargin=40, leftMargin=40,
                            topMargin=40,  bottomMargin=40)
    styles = getSampleStyleSheet()

    title_style    = styles['Title']
    heading_style  = styles['Heading2']
    normal_style   = styles['Normal']
    risk_style     = ParagraphStyle('RiskStyle', parent=normal_style,
                                    fontName='Helvetica-Bold', fontSize=11)
    verbatim_style = ParagraphStyle('VerbatimStyle', parent=normal_style,
                                    fontName='Courier', fontSize=9, leading=12,
                                    leftIndent=10, rightIndent=10)

    elements = []
    elements.append(Paragraph("Legal Risk Assessment Report", title_style))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(
        f"<b>Analyzed Document:</b> {html.escape(client_name)}", normal_style
    ))
    elements.append(Spacer(1, 20))
    elements.append(HRFlowable(width="100%", thickness=2, color=colors.darkblue))
    elements.append(Spacer(1, 20))

    for analysis in report_data.analyses:
        elements.append(Paragraph(
            f"Section: {html.escape(analysis.clause_name)}", heading_style
        ))
        risk_color = ("red"    if analysis.risk_level.lower() == "high"   else
                      "orange" if analysis.risk_level.lower() == "medium" else "green")
        elements.append(Paragraph(
            f"<font color='{risk_color}'>RISK LEVEL: {analysis.risk_level.upper()}</font>",
            risk_style,
        ))
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("<b>Factual Conflict:</b>", normal_style))
        elements.append(Paragraph(html.escape(analysis.factual_conflict), normal_style))
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("<b>Client Verbatim:</b>", normal_style))
        elements.append(Paragraph(
            html.escape(analysis.client_verbatim).replace('\n', '<br/>'), verbatim_style
        ))
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("<b>Company Standard Verbatim:</b>", normal_style))
        elements.append(Paragraph(
            html.escape(analysis.standard_verbatim).replace('\n', '<br/>'), verbatim_style
        ))
        elements.append(Spacer(1, 20))
        elements.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey))
        elements.append(Spacer(1, 20))

    doc.build(elements)
    buffer.seek(0)
    return buffer


# ==========================================
# SECTION 7: AGENT TOOLS (FACTORY PATTERN)
# ==========================================

def make_tools(selected_client: str, selected_clauses: list,
               selected_playbook: str = None,
               client_file_path: str = None) -> list:
    """
    Factory: Creates all 3 agent tools with current context baked in via closure.
    client_file_path: full path supporting department subfolders.
    """
    _client_path = client_file_path or find_client_file_path(selected_client)

    @tool
    def extract_contract_terms(clause_list: str) -> str:
        """TOOL 1 — VERBATIM CLAUSE EXTRACTOR."""
        log_step(" Thought", "Must call Tool 1 first to extract verbatim section text.", "thought")
        log_step(" Action",  f"extract_contract_terms({clause_list})", "action")

        full_text = load_doc_text(_client_path)
        llm       = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash", temperature=0, google_api_key=GEMINI_API_KEY
        )

        _t0    = time.time()
        result = llm.with_structured_output(ContractData).invoke(
            "MANDATORY EXTRACTION GUARDRAILS\n"
            "--------------------------------\n"
            "RULE 1 -- VERBATIM ONLY: Copy CHARACTER BY CHARACTER. No summarizing.\n"
            "RULE 2 -- COMPLETE: Include ALL numbered sub-sections.\n"
            "RULE 3 -- ABSENT: If section absent, set verbatim_text to: Section Not Present\n"
            "--------------------------------\n\n"
            f"Extract VERBATIM text for: {clause_list}\n\nDOCUMENT TEXT:\n{full_text}"
        )
        _dur_ms     = int((time.time() - _t0) * 1000)
        _approx_in  = (len(full_text) + len(clause_list)) // 4
        _approx_out = sum(len(c.verbatim_text) for c in result.extracted_clauses) // 4
        logger.log_token_event(
            tool_name="Tool 1 — Extract",
            input_tokens=_approx_in,
            output_tokens=_approx_out,
            duration_ms=_dur_ms,
            client_file=selected_client,
            playbook_file=selected_playbook or "",
            department=st.session_state.get("selected_department", ""),
        )
        st.session_state.run_token_total += _approx_in + _approx_out

        st.session_state.extracted_data = result
        st.session_state.pipeline_stage = 2

        preview = json.dumps([
            {"section": c.clause_name,
             "preview": (c.verbatim_text[:250] + "...") if len(c.verbatim_text) > 250
                        else c.verbatim_text}
            for c in result.extracted_clauses
        ], indent=2)
        log_step(" Observation", preview, "observation")
        return preview

    @tool
    def query_playbook(clause_topics: str) -> str:
        """TOOL 2 — HYBRID PLAYBOOK RETRIEVER."""
        log_step(" Thought", "Tool 1 approved. Querying playbook RAG with Tool 2.", "thought")
        log_step(" Action",  f"query_playbook({clause_topics})", "action")

        embeddings = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001", google_api_key=GEMINI_API_KEY
        )
        _playbook_stem = os.path.splitext(selected_playbook)[0] if selected_playbook else "default"
        _safe_stem     = "".join(c if c.isalnum() or c in "-_" else "_" for c in _playbook_stem)
        _playbook_dir  = os.path.join(CHROMA_PERSIST_DIR, _safe_stem)

        vector_store = Chroma(persist_directory=_playbook_dir, embedding_function=embeddings)

        if vector_store._collection.count() == 0:
            return "ERROR: ChromaDB empty. Run: python main.py"

        vector_retriever = vector_store.as_retriever(search_kwargs={"k": 3})
        all_docs         = vector_store.get()
        bm25_retriever   = BM25Retriever.from_texts(all_docs["documents"])
        bm25_retriever.k = 3
        hybrid           = EnsembleRetriever(
            retrievers=[bm25_retriever, vector_retriever], weights=[0.5, 0.5]
        )

        results = []
        for topic in clause_topics.split(","):
            topic = topic.strip()
            docs  = hybrid.invoke(f"Company standard rules for: {topic}")
            results.append(
                f"[STANDARD FOR: {topic}]\n"
                + "\n---\n".join([d.page_content for d in docs])
            )

        output = "\n\n".join(results)

        _approx_in  = len(clause_topics) // 4
        _approx_out = len(output) // 4
        logger.log_token_event(
            tool_name="Tool 2 — Playbook",
            input_tokens=_approx_in,
            output_tokens=_approx_out,
            duration_ms=0,
            client_file=selected_client,
            playbook_file=selected_playbook or "",
            department=st.session_state.get("selected_department", ""),
        )
        st.session_state.run_token_total += _approx_in + _approx_out

        st.session_state.tool2_result = output
        log_step(" Observation", output[:500] + "..." if len(output) > 500 else output, "observation")
        return output

    @tool
    def generate_risk_report(comparison_context: str) -> str:
        """TOOL 3 — RISK REPORT GENERATOR."""
        log_step(" Thought", "Playbook retrieved. Generating risk report with Tool 3.", "thought")
        log_step(" Action",  "generate_risk_report(...)", "action")

        if not st.session_state.extracted_data:
            return "ERROR: No extracted data. Run Tool 1 first."

        context = ""
        for clause in st.session_state.extracted_data.extracted_clauses:
            context += (
                f"\nSECTION NAME: {clause.clause_name}\n"
                f"CLIENT VERBATIM TEXT:\n{clause.verbatim_text}\n"
                f"COMPANY STANDARD:\n{comparison_context}\n"
                f"{'=' * 60}\n"
            )

        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash", temperature=0, google_api_key=GEMINI_API_KEY
        )

        _t0    = time.time()
        result = llm.with_structured_output(FinalRiskReport).invoke(f"""
You are a Senior Legal Risk Analyst. Your ONLY function is FACTUAL TEXT COMPARISON.

ABSOLUTE GUARDRAILS -- MANDATORY
==================================
GUARDRAIL 1 -- ZERO INFERENCE RULE
  FORBIDDEN: inferring intent, legal advice, phrases like may imply / could suggest.
  ONLY report LITERALLY AND EXPLICITLY written text.

GUARDRAIL 2 -- MANDATORY VERBATIM QUOTATION
  client_verbatim   : EXACT client section text, word for word.
  standard_verbatim : EXACT playbook standard text, word for word.
  factual_conflict  : ONE sentence, literal difference only.
    Example: Client states 90 days; company standard requires 30 days.

GUARDRAIL 3 -- RISK CLASSIFICATION
  HIGH   = Client DIRECTLY contradicts standard.
  MEDIUM = Client SILENT or AMBIGUOUS on a required standard.
  LOW    = Client FULLY ALIGNED. No deviation found.

GUARDRAIL 4 -- CONFIRMATION
  guardrail_note must say exactly:
    Analysis based solely on literal text comparison. No legal advice provided. No intent inferred.

DATA:
{context}
""")
        _dur_ms     = int((time.time() - _t0) * 1000)
        _approx_in  = len(context) // 4
        _approx_out = len(json.dumps([a.dict() for a in result.analyses])) // 4
        logger.log_token_event(
            tool_name="Tool 3 — Report",
            input_tokens=_approx_in,
            output_tokens=_approx_out,
            duration_ms=_dur_ms,
            client_file=selected_client,
            playbook_file=selected_playbook or "",
            department=st.session_state.get("selected_department", ""),
        )
        _final_total = st.session_state.run_token_total + _approx_in + _approx_out
        st.session_state.run_token_total = _final_total

        logger.log_run(
            client_file=selected_client,
            playbook_file=selected_playbook or "",
            department=st.session_state.get("selected_department", ""),
            clauses=selected_clauses,
            risk_report=result,
            total_tokens=_final_total,
        )

        st.session_state.final_report   = result
        st.session_state.pipeline_stage = 4

        summary = json.dumps([
            {"section": a.clause_name, "risk": a.risk_level, "conflict": a.conflict_found}
            for a in result.analyses
        ], indent=2)
        log_step(" Observation", summary, "observation")
        log_step(" Final Answer", f"Report complete. {len(result.analyses)} sections analyzed.", "final")
        return f"Report generated.\n{summary}"

    return [extract_contract_terms, query_playbook, generate_risk_report]


# ==========================================
# SECTION 8: SIDEBAR
# ==========================================
with st.sidebar:
    st.markdown(
        '<div style="font-size:19px;font-weight:800;color:#1E2D5E;padding:4px 0;">'
        "Legal Contract Analyzer</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # ── ADMIN BUTTON — TOP OF SIDEBAR ─────────────────────────────────────────
    if st.button("⚙ Admin Panel", use_container_width=True):
        st.switch_page("pages/admin.py")

    st.markdown("---")

    # ── PRE-FETCH DATA FOR CHATBOT RAG ────────────────────────────────────────
    _sidebar_playbooks = get_files_from_dir(COMPANY_PLAYBOOK_DIR)
    _sidebar_active_pb = st.session_state.get("playbook_select")
    if not _sidebar_active_pb and _sidebar_playbooks:
        _sidebar_active_pb = _sidebar_playbooks[0]
    elif not _sidebar_playbooks:
        _sidebar_active_pb = "No files found"

    # ── 1. 💬 LEGAL ASSISTANT ─────────────────────────────────────────────────
    render_chatbot(GEMINI_API_KEY, _sidebar_active_pb, _sidebar_playbooks)

    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown("---")

    # ── 2. DOCUMENT SELECTION & UPLOADS ───────────────────────────────────────
    st.markdown(
        '<p style="font-size:12px;font-weight:700;color:#374151;'
        'text-transform:uppercase;letter-spacing:0.8px;margin:4px 0 8px 0;">'
        "Document Selection</p>",
        unsafe_allow_html=True,
    )

    # Playbook Upload
    uploaded_playbook = st.file_uploader(
        "Upload Playbook",
        type=["pdf", "docx"],
        key="upload_playbook",
        label_visibility="collapsed",
    )

    if uploaded_playbook and uploaded_playbook.name not in st.session_state.processed_uploads:
        success, msg = save_uploaded_file(
            uploaded_playbook, COMPANY_PLAYBOOK_DIR, is_client_file=False
        )
        if success:
            st.success(msg)
            st.caption("📌 Select the file from the dropdown below and click **Rebuild Playbook DB**.")
        else:
            st.warning(msg)
        st.session_state.processed_uploads.add(uploaded_playbook.name)

    playbook_files = get_files_from_dir(COMPANY_PLAYBOOK_DIR)
    selected_playbook = st.selectbox(
        "Company Playbook:",
        options=playbook_files if playbook_files else ["No files found"],
        help="Standards document in company_standard/",
        index=0,
        key="playbook_select",
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── DEPARTMENT FILTER ─────────────────────────────────────────────────────
    departments  = get_departments()
    dept_options = ["All departments"] + departments

    selected_dept_display = st.selectbox(
        "Department:",
        options=dept_options,
        help="Filter contracts by department. 'All departments' shows every contract.",
        key="dept_select",
    )

    # Map display value to session state value
    selected_dept = "" if selected_dept_display == "All departments" else selected_dept_display

    # Auto-reset pipeline when department changes
    if selected_dept != st.session_state.get("last_department"):
        if st.session_state.get("last_department") is not None:
            reset_pipeline_for_new_client()
            st.session_state.last_client = None
        st.session_state.last_department     = selected_dept
        st.session_state.selected_department = selected_dept

    st.session_state.selected_department = selected_dept

    # ── Client Upload ─────────────────────────────────────────────────────────
    uploaded_client = st.file_uploader(
        "Upload Client Contract",
        type=["pdf", "docx"],
        key="upload_client",
        label_visibility="collapsed",
    )

    if uploaded_client and uploaded_client.name not in st.session_state.processed_uploads:
        # Upload to selected dept subfolder, or flat root if "All departments"
        target_dir = (
            os.path.join(CLIENT_CONTRACTS_DIR, selected_dept)
            if selected_dept else CLIENT_CONTRACTS_DIR
        )
        success, msg = save_uploaded_file(
            uploaded_client, target_dir, is_client_file=True
        )
        if success:
            dept_label = f"'{selected_dept}'" if selected_dept else "clients/ folder"
            st.success(f"✅ Uploaded '{uploaded_client.name}' to {dept_label}.")
            st.caption("📌 File uploaded. Select it from the dropdown below to analyze.")
        else:
            st.warning(msg)
        st.session_state.processed_uploads.add(uploaded_client.name)

    # ── Client Contract dropdown — filtered by department ─────────────────────
    client_files = get_client_files_for_department(selected_dept)

    if not client_files:
        dept_msg = (f"No files in '{selected_dept}'"
                    if selected_dept else "No client contracts found")
        client_files_display = [dept_msg]
    else:
        client_files_display = client_files

    selected_client = st.selectbox(
        "Client Contract:",
        options=client_files_display,
        help="Client MSA or SOW — filtered by department above.",
        index=0,
        key="client_select",
    )

    # Caption showing file count context
    if selected_dept and client_files:
        st.caption(f"Showing {len(client_files)} file(s) from '{selected_dept}'")
    elif not selected_dept and client_files:
        st.caption(f"Showing all {len(client_files)} contract(s) across all departments")

    # Auto-reset when client changes
    if selected_client != st.session_state.last_client:
        if st.session_state.last_client is not None:
            reset_pipeline_for_new_client()
        st.session_state.last_client     = selected_client
        st.session_state.selected_client = selected_client
    st.session_state.selected_client = selected_client

    # ── 3. SYSTEM STATUS ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        '<p style="font-size:12px;font-weight:700;color:#374151;'
        'text-transform:uppercase;letter-spacing:0.8px;margin:4px 0 8px 0;">'
        "System Status</p>",
        unsafe_allow_html=True,
    )

    _sel_stem      = os.path.splitext(selected_playbook)[0] if selected_playbook and selected_playbook != "No files found" else ""
    _safe_sel_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in _sel_stem)
    _sel_chroma    = os.path.join(CHROMA_PERSIST_DIR, _safe_sel_stem)
    _sel_hash_file = os.path.join(_sel_chroma, ".playbook_hash")

    db_ok = os.path.exists(_sel_chroma) and bool(os.listdir(_sel_chroma))
    if db_ok:
        if os.path.exists(_sel_hash_file):
            st.success(" ChromaDB Online — Up to date")
            try:
                import json as _j
                data = _j.load(open(_sel_hash_file))
                st.caption(
                    f" `{data.get('playbook_filename','?')}`\n\n"
                    f" Built: {data.get('built_at','?')}"
                )
            except Exception:
                pass
        else:
            st.warning(" ChromaDB Online — No hash record")
    else:
        st.error("❌ No DB for this playbook — click Rebuild Playbook DB")

    st.markdown(f"{'✅' if playbook_files else '❌'} Playbook: {'Found' if playbook_files else 'Missing'}")
    st.markdown(f"{'✅' if client_files  else '❌'} Client Contracts: {'Found' if client_files else 'Missing'}")

    # ── 4. PLAYBOOK DATABASE ──────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        '<p style="font-size:12px;font-weight:700;color:#374151;'
        'text-transform:uppercase;letter-spacing:0.8px;margin:4px 0 8px 0;">'
        "Playbook Database</p>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Replace the playbook in `company_standard/` then click Rebuild. "
        "Auto-detects changes — no manual deletion needed."
    )
    if st.button(" Rebuild Playbook DB", use_container_width=True):
        if not playbook_files or selected_playbook == "No files found":
            st.error("No playbook file found in company_standard/")
        else:
            with st.spinner(f"Rebuilding ChromaDB for {selected_playbook}..."):
                try:
                    db = initialize_playbook_db(
                        force_rebuild=True,
                        selected_playbook=selected_playbook,
                    )
                    if db:
                        st.success(
                            f" Rebuilt `{selected_playbook}` — "
                            f"{db._collection.count()} chunks stored"
                        )
                        reset_pipeline_for_new_client()
                    else:
                        st.error("❌ Rebuild failed. Check that the file is a valid .docx or .pdf.")
                except Exception as e:
                    st.error(f"❌ Rebuild error: {e}")
            st.rerun()

# Guard: stop if no valid documents
if not client_files or not playbook_files:
    st.warning(" No documents found. Check MyFiles/Contracts folders.")
    st.stop()

# Guard: stop if selected_client is a placeholder message
_no_file_msgs = {"No files found", "No client contracts found"}
if selected_client in _no_file_msgs or selected_client.startswith("No files in '"):
    st.warning("No client contracts available. Upload a contract or select a different department.")
    st.stop()


# ==========================================
# SECTION 9: PAGE HEADER
# ==========================================
st.markdown(
    '<h1 style="font-size:32px;font-weight:800;color:#1E2D5E;margin-bottom:4px;">'
    "Legal Contract Analyzer</h1>",
    unsafe_allow_html=True,
)
_dept_ctx = f" · Department: **{selected_dept}**" if selected_dept else ""
st.markdown(
    "**ReAct Agent Pipeline** — Sequential tool calling with enforced guardrails, "
    f"HITL approval gate, and verbatim-only conflict detection.{_dept_ctx}"
)

# ==========================================
# SECTION 10: PIPELINE BAR
# ==========================================
render_pipeline_bar()

# ==========================================
# SECTION 11: REACT TRACE PANEL
# ==========================================
render_trace_panel()

# ==========================================
# SECTION 12: STEP 1 — DOCUMENT DISCOVERY
# ==========================================
st.markdown("---")
st.markdown("## Step 1 — Document Discovery")
st.markdown(
    "Scan the client contract to discover its legal section headings. "
    "This is a lightweight call — it does **not** extract section content."
)

col_btn, col_info = st.columns([2, 3])
with col_btn:
    if st.button(" Run Discovery Scan", type="primary", use_container_width=True):
        with st.spinner("Scanning for section headings..."):
            reset_pipeline_for_new_client()
            _client_full_path = find_client_file_path(selected_client)
            st.session_state.discovered_clauses = run_discovery_scan(
                selected_client, _client_full_path
            )
            st.session_state.pipeline_stage = 1
        st.rerun()

with col_info:
    if st.session_state.discovered_clauses:
        st.success(
            f" Discovered **{len(st.session_state.discovered_clauses)}** "
            f"sections in `{selected_client}`"
        )
    else:
        st.info("Click **Run Discovery Scan** to begin.")

# ==========================================
# SECTION 13: STEP 2 — CLAUSE SELECTION
# ==========================================
if st.session_state.discovered_clauses:
    selected_clauses = st.multiselect(
        "Select sections to analyze:",
        options=st.session_state.discovered_clauses,
        default=st.session_state.discovered_clauses[:3],
        help="Choose sections to extract and compare against the playbook.",
    )
    st.session_state.selected_clauses = selected_clauses

    st.markdown("---")
    st.markdown("## Step 2 — Analyze Sections")
    st.markdown(
        "Select sections above then click **Analyze Selected Sections**. "
        "The agent extracts verbatim text (Tool 1), pauses for your review, "
        "then automatically runs the playbook query (Tool 2) and generates "
        "the full risk report (Tool 3) the moment you approve."
    )

    if st.session_state.rejected_flag:
        st.error("❌ Extraction was rejected. Adjust section selection and click Analyze again.")

    if st.button(
        " Analyze Selected Sections",
        type="primary",
        disabled=not selected_clauses,
        use_container_width=False,
    ):
        with st.spinner("Tool 1: Extracting verbatim section text..."):
            _client_full_path = find_client_file_path(selected_client)
            tools      = make_tools(selected_client, selected_clauses,
                                    selected_playbook, _client_full_path)
            clause_str = ", ".join(selected_clauses)
            tools[0].invoke({"clause_list": clause_str})
            st.session_state.hitl_approved = False
            st.session_state.rejected_flag = False
        st.rerun()

# ==========================================
# SECTION 14: HITL GATE
# ==========================================
render_hitl_gate()

# ==========================================
# SECTION 15: AUTO-RUN TOOL 2 + TOOL 3
# ==========================================
if st.session_state.hitl_approved and st.session_state.final_report is None:
    clause_str        = ", ".join(st.session_state.selected_clauses)
    _client_full_path = find_client_file_path(selected_client)
    tools             = make_tools(selected_client, st.session_state.selected_clauses,
                                   selected_playbook, _client_full_path)

    with st.spinner("Tool 2: Querying company playbook via hybrid search..."):
        tool2_result = tools[1].invoke({"clause_topics": clause_str})

    with st.spinner("Tool 3: Generating risk report (zero-inference analysis)..."):
        tools[2].invoke({"comparison_context": tool2_result})

    st.rerun()

# ==========================================
# SECTION 16: FINAL REPORT & PDF EXPORT
# ==========================================
if st.session_state.final_report:
    st.markdown("---")

    col_header, col_btn = st.columns([3, 1])

    with col_header:
        st.markdown("## 📊 Final Risk Assessment Report")

    with col_btn:
        pdf_buffer = generate_pdf_report(st.session_state.final_report, selected_client)
        st.markdown("<div style='margin-top: 5px;'></div>", unsafe_allow_html=True)
        st.download_button(
            label="⬇ Download PDF Report",
            data=pdf_buffer,
            file_name=f"Risk_Report_{selected_client.replace('.docx', '').replace('.pdf', '')}.pdf",
            mime="application/pdf",
            use_container_width=True,
            type="primary",
        )

render_full_report()
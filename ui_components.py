"""
================================================================================
ui_components.py -- UI Rendering Module
================================================================================
Purpose : Contains ALL Streamlit UI rendering functions for the Legal Contract
          Analyzer. This module is purely presentational -- zero business logic,
          zero LLM calls. Session state is only written in render_hitl_gate()
          which must update state when the human clicks Approve or Reject.

Functions:
    inject_css()              -- Full CSS stylesheet
    render_pipeline_bar()     -- Sticky 5-stage pipeline status tracker
    render_trace_panel()      -- ReAct Thought/Action/Observation log
    render_hitl_gate()        -- HITL pause banner + Approve/Reject buttons
    render_risk_legend()      -- HIGH/MEDIUM/LOW explanation cards
    render_risk_card(analysis)-- Single clause risk analysis card
    render_full_report()      -- Full report: metrics + legend + all cards

Usage:
    from ui_components import (
        inject_css, render_pipeline_bar, render_trace_panel,
        render_hitl_gate, render_full_report,
    )
================================================================================
"""

import html
import streamlit as st


# ==========================================
# SECTION 1: CSS STYLES
# ==========================================

def inject_css() -> None:
    """
    Injects the complete CSS stylesheet into the Streamlit application.
    Called once at the top of app.py before any UI is rendered.

    Returns:
        None
    """
    st.markdown("""
<style>
/* ── Global ──────────────────────────────────────────────── */
[data-testid="stAppViewContainer"] { background: #f8fafc; }
[data-testid="stSidebar"]          { background: #ffffff;
                                     border-right: 1px solid #e2e8f0; }

/* ── Sticky pipeline bar ─────────────────────────────────── */
.pipeline-wrapper {
    position: sticky;
    top: 0;
    z-index: 999;
    background: #f8fafc;
    padding: 10px 0 6px 0;
    border-bottom: 2px solid #e2e8f0;
    margin-bottom: 20px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.05);
}

/* ── Pipeline step cells ─────────────────────────────────── */
.pipeline-bar {
    display: flex; gap: 0;
    border-radius: 8px; overflow: hidden;
    border: 1px solid #e2e8f0; margin: 0;
}
.pipeline-step {
    flex: 1; padding: 10px 6px; text-align: center;
    font-size: 12px; font-weight: 600; letter-spacing: 0.3px;
    background: #f1f5f9; color: #94a3b8;
    border-right: 1px solid #e2e8f0; transition: all 0.3s;
}
.pipeline-step:last-child { border-right: none; }
.pipeline-step.active  { background: #dbeafe; color: #1d4ed8; }
.pipeline-step.done    { background: #dcfce7; color: #15803d; }
.pipeline-step.waiting { background: #fef9c3; color: #a16207; }

/* ── ReAct trace log entries ─────────────────────────────── */
.trace-thought {
    background: #eef2ff; border-left: 3px solid #6366f1;
    padding: 10px 14px; border-radius: 6px; margin: 6px 0;
    font-size: 13px; color: #3730a3;
}
.trace-action {
    background: #f0fdf4; border-left: 3px solid #16a34a;
    padding: 10px 14px; border-radius: 6px; margin: 6px 0;
    font-size: 13px; color: #15803d; font-family: monospace;
}
.trace-observation {
    background: #f0f9ff; border-left: 3px solid #0284c7;
    padding: 10px 14px; border-radius: 6px; margin: 6px 0;
    font-size: 12px; color: #0369a1; font-family: monospace;
}
.trace-human {
    background: #f0fdf4; border-left: 3px solid #22c55e;
    padding: 10px 14px; border-radius: 6px; margin: 6px 0;
    font-size: 13px; color: #166534; font-weight: 600;
}
.trace-final {
    background: #fffbeb; border-left: 3px solid #d97706;
    padding: 10px 14px; border-radius: 6px; margin: 6px 0;
    font-size: 13px; color: #92400e; font-weight: 600;
}

/* ── Risk badges ─────────────────────────────────────────── */
.risk-badge-high   { background:#ef4444; color:white; padding:3px 10px;
                     border-radius:12px; font-size:11px; font-weight:700; }
.risk-badge-medium { background:#f59e0b; color:white; padding:3px 10px;
                     border-radius:12px; font-size:11px; font-weight:700; }
.risk-badge-low    { background:#22c55e; color:white; padding:3px 10px;
                     border-radius:12px; font-size:11px; font-weight:700; }

/* ── Verbatim text box ───────────────────────────────────── */
/* white-space:pre-wrap wraps long lines — no horizontal scroll.
   The * rule resets ALL child elements so Word heading styles
   (h1/h2/h3) cannot make text render at browser heading sizes. */
.verbatim-box {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 12px 14px;
    margin: 6px 0 12px 0;
    font-size: 12px !important;
    line-height: 1.7;
    color: #374151;
    font-family: "Courier New", Courier, monospace;
    white-space: pre-wrap;       /* wrap long lines — no horizontal truncation */
    word-wrap: break-word;
    overflow-wrap: break-word;
    /* NO max-height — show ALL text, no scroll cutoff */
}
/* Kill Word heading styles — prevents h1/h2/h3 from rendering large */
.verbatim-box * {
    font-size: 12px !important;
    font-weight: normal !important;
    font-family: "Courier New", Courier, monospace !important;
    line-height: 1.7 !important;
    margin: 0 !important;
    padding: 0 !important;
    color: #374151 !important;
}

/* ── Factual conflict box ────────────────────────────────── */
.conflict-box {
    background: #fff5f5; border: 1px solid #fecaca;
    border-radius: 6px; padding: 10px 14px;
    margin: 6px 0; font-size: 13px; color: #b91c1c;
}

/* ── Section label ───────────────────────────────────────── */
.section-label {
    font-size: 11px; font-weight: 700; letter-spacing: 1px;
    text-transform: uppercase; color: #64748b; margin: 10px 0 4px 0;
}

/* ── HITL banner ─────────────────────────────────────────── */
.hitl-banner {
    background: #f0fdf4; border: 2px solid #16a34a;
    border-radius: 10px; padding: 16px 20px; margin: 16px 0;
    color: #166534; font-size: 14px; font-weight: 600;
}

/* ── Guardrail chips ─────────────────────────────────────── */
.guardrail-chip {
    display: inline-block; background: #f0fdf4;
    border: 1px solid #bbf7d0; color: #15803d;
    border-radius: 20px; padding: 4px 12px; margin: 3px;
    font-size: 11px; font-weight: 600;
}

/* ── Selectbox — disable free-text typing ────────────────── */
/* Streamlit renders selectboxes as searchable <input> fields */
/* by default — users can type into them.                     */
/* These rules disable the cursor and pointer events on the   */
/* input element so only clicking the dropdown arrow works.   */

/* Target the text input inside every sidebar selectbox       */
[data-testid="stSidebar"] [data-baseweb="select"] input {
    caret-color: transparent !important;  /* hide text cursor */
    pointer-events: none !important;      /* block mouse clicks on input */
    cursor: default !important;
}
/* Target the inner input container                           */
[data-testid="stSidebar"] [data-baseweb="select"] [data-baseweb="input"] {
    pointer-events: none !important;
}
/* Keep the outer container clickable to open the dropdown    */
[data-testid="stSidebar"] [data-baseweb="select"] [data-baseweb="select"] {
    cursor: pointer !important;
    pointer-events: all !important;
}
/* Hide the clear/search icon that appears on hover           */
[data-testid="stSidebar"] [data-baseweb="select"] [data-baseweb="icon"] {
    pointer-events: none !important;
}
</style>
""", unsafe_allow_html=True)


# ==========================================
# SECTION 2: PIPELINE STATUS BAR
# ==========================================

_PIPELINE_STEPS = [
    ("1", "Discovery",        0),
    ("2", "Tool 1: Extract",  1),
    ("3", "HITL Review",      2),
    ("4", "Tool 2: Playbook", 3),
    ("5", "Tool 3: Report",   4),
]
_STAGE_ICONS = {"done": "✅", "active": "🔄", "waiting": "⏳", "": "⭕"}


def _get_step_css(idx: int) -> str:
    """Returns the CSS class for a pipeline step based on current stage."""
    stage = st.session_state.pipeline_stage
    data  = st.session_state.extracted_data
    appr  = st.session_state.hitl_approved

    if idx == 2:
        if data and not appr:
            return "waiting"
        if appr:
            return "done"

    if idx < stage:
        return "done"
    if idx == stage:
        return "done" if stage == 4 else "active"
    return ""


def render_pipeline_bar() -> None:
    """
    Renders the sticky 5-stage pipeline status bar.

    Returns:
        None
    """
    bar = (
        '<div class="pipeline-wrapper">'
        '<div class="pipeline-bar" style="border:none;border-radius:0;margin:0;">'
    )
    for _n, label, idx in _PIPELINE_STEPS:
        css  = _get_step_css(idx)
        icon = _STAGE_ICONS.get(css, "⭕")
        bar += (
            f'<div class="pipeline-step {css}">'
            f'<div style="font-size:18px">{icon}</div>'
            f'<div>{label}</div>'
            f'</div>'
        )
    bar += "</div></div>"
    st.markdown(bar, unsafe_allow_html=True)


# ==========================================
# SECTION 3: REACT AGENT TRACE PANEL
# ==========================================

_TRACE_LIMIT = 800
_TRACE_CSS = {
    "thought":     "trace-thought",
    "action":      "trace-action",
    "observation": "trace-observation",
    "human":       "trace-human",
    "final":       "trace-final",
}


def render_trace_panel() -> None:
    """
    Renders the ReAct agent trace log as a collapsible expander.
    Only visible when agent_log is non-empty.

    Returns:
        None
    """
    if not st.session_state.agent_log:
        return

    count = len(st.session_state.agent_log)
    with st.expander(f" ReAct Agent Trace — Live Log ({count} steps)", expanded=True):
        for step in st.session_state.agent_log:
            role    = step.get("role",    "")
            content = step.get("content", "")
            status  = step.get("status",  "thought")
            css     = _TRACE_CSS.get(status, "trace-thought")
            display = (
                content[:_TRACE_LIMIT] + "\n... [truncated]"
                if len(content) > _TRACE_LIMIT else content
            )
            st.markdown(
                f'<div class="{css}"><strong>{role}</strong><br>'
                f'<pre style="margin:6px 0 0 0;white-space:pre-wrap;font-size:12px">'
                f'{display}</pre></div>',
                unsafe_allow_html=True,
            )
    st.markdown("")


# ==========================================
# SECTION 4: HITL APPROVAL GATE
# ==========================================

def render_hitl_gate() -> None:
    """
    Renders the Human-in-the-Loop approval gate.

    Shows extracted clauses for review with APPROVE / REJECT buttons.
    - APPROVE: sets hitl_approved=True, Tools 2+3 run automatically in app.py
    - REJECT:  clears extracted data, user re-selects clauses and re-analyzes

    Only visible when extracted_data exists AND hitl_approved is False.

    Returns:
        None
    """
    if not st.session_state.extracted_data or st.session_state.hitl_approved:
        return

    st.markdown(
        '<div class="hitl-banner">'
        "⏸️ &nbsp;<strong>AGENT PAUSED — HUMAN REVIEW REQUIRED</strong><br>"
        '<span style="font-weight:400; font-size:13px">'
        "Review the verbatim-extracted clauses below. "
        "<strong>Approve</strong> to automatically run the full risk analysis. "
        "<strong>Reject</strong> to discard and re-select clauses."
        "</span></div>",
        unsafe_allow_html=True,
    )

    for clause in st.session_state.extracted_data.extracted_clauses:
        with st.expander(f"📄 {clause.clause_name}", expanded=True):
            st.markdown(
                '<div class="section-label">Verbatim Extracted Text</div>',
                unsafe_allow_html=True,
            )
            st.code(clause.verbatim_text, language=None)

    st.markdown("")
    col_approve, col_reject = st.columns(2)

    with col_approve:
        if st.button(
            "✅ APPROVE — Run Full Analysis Automatically",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.hitl_approved  = True
            st.session_state.pipeline_stage = 3
            st.session_state.agent_log.append({
                "role":    "👤 Human Decision",
                "content": "APPROVED — Running Tool 2 and Tool 3 automatically.",
                "status":  "human",
            })
            st.rerun()

    with col_reject:
        if st.button("❌ REJECT — Discard and Re-select Clauses", use_container_width=True):
            st.session_state.extracted_data = None
            st.session_state.rejected_flag  = True
            st.session_state.pipeline_stage = 1
            st.session_state.agent_log.append({
                "role":    "👤 Human Decision",
                "content": "REJECTED — Extraction discarded. Re-select clauses and analyze again.",
                "status":  "human",
            })
            st.rerun()


# ==========================================
# SECTION 5: RISK REPORT RENDERING
# ==========================================

def render_risk_legend() -> None:
    """
    Renders the HIGH / MEDIUM / LOW classification legend.

    Returns:
        None
    """
    st.markdown("""
<div style="display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap;">

  <div style="flex:1;min-width:200px;background:#fff5f5;
              border:1px solid #fecaca;border-left:4px solid #ef4444;
              border-radius:8px;padding:12px 16px;">
    <div style="font-size:13px;font-weight:700;color:#b91c1c;margin-bottom:4px;">
      🔴 HIGH — Direct Contradiction</div>
    <div style="font-size:12px;color:#7f1d1d;">
      Client text DIRECTLY contradicts the standard.
      Example: Client says "Net 90 days" — standard requires "Net 30 days."</div>
  </div>

  <div style="flex:1;min-width:200px;background:#fffbeb;
              border:1px solid #fde68a;border-left:4px solid #f59e0b;
              border-radius:8px;padding:12px 16px;">
    <div style="font-size:13px;font-weight:700;color:#92400e;margin-bottom:4px;">
      🟠 MEDIUM — Gap / Client Silent</div>
    <div style="font-size:12px;color:#78350f;">
      Client does NOT address something the standard requires.
      No direct contradiction — the rule is simply absent.</div>
  </div>

  <div style="flex:1;min-width:200px;background:#f0fdf4;
              border:1px solid #bbf7d0;border-left:4px solid #22c55e;
              border-radius:8px;padding:12px 16px;">
    <div style="font-size:13px;font-weight:700;color:#15803d;margin-bottom:4px;">
      🟢 LOW — Fully Aligned</div>
    <div style="font-size:12px;color:#14532d;">
      Client text is fully consistent with the standard.
      No deviation, contradiction, or gap found.</div>
  </div>

</div>
""", unsafe_allow_html=True)


def render_risk_card(analysis) -> None:
    """
    Renders a single clause risk analysis card.

    Layout:
        Row 1: Clause name + Risk badge + Status label
        Row 2: Client verbatim text (full width, wrapped monospace)
        Row 3: Company standard verbatim text (full width, wrapped monospace)
        Row 4: Factual conflict statement (red box)
        Row 5: Guardrail confirmation (green box)

    Args:
        analysis: RiskAnalysis Pydantic object from FinalRiskReport.analyses.

    Returns:
        None
    """
    level = analysis.risk_level.lower()

    bg_color     = {"high": "#fff5f5", "medium": "#fffbeb", "low": "#f0fdf4"}.get(level, "#ffffff")
    border_color = {"high": "#ef4444", "medium": "#f59e0b", "low": "#22c55e"}.get(level, "#e2e8f0")
    badge_css    = f"risk-badge-{level}"
    icon         = {"high": "🔴", "medium": "🟠", "low": "🟢"}.get(level, "⚪")
    status_label = {
        "high":   "⚠️ Direct Contradiction",
        "medium": "ℹ️ Gap — Client Silent",
        "low":    "✅ Fully Aligned",
    }.get(level, "")
    status_color = {
        "high": "#b91c1c", "medium": "#92400e", "low": "#15803d"
    }.get(level, "#64748b")

    # ── Card wrapper ──────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:{bg_color};border-left:4px solid {border_color};'
        f'border-radius:10px;padding:16px 20px;margin:14px 0;border:1px solid #e2e8f0;">',
        unsafe_allow_html=True,
    )

    # ── Row 1: Header ─────────────────────────────────────────────────────────
    col_name, col_meta = st.columns([5, 2])
    with col_name:
        st.markdown(
            f'<p style="font-size:16px;font-weight:700;margin:0;color:#1e293b;">'
            f'{icon} {html.escape(analysis.clause_name)}</p>',
            unsafe_allow_html=True,
        )
    with col_meta:
        st.markdown(
            f'<div style="padding-top:2px;">'
            f'<span class="{badge_css}">{analysis.risk_level.upper()}</span>'
            f'&nbsp;&nbsp;<span style="font-size:11px;color:{status_color};font-weight:600;">'
            f'{status_label}</span></div>',
            unsafe_allow_html=True,
        )

    st.markdown("")

    # ── Rows 2+3: Side-by-side verbatim comparison ────────────────────────────
    # Using styled <div> with white-space:pre-wrap so ALL text is visible.
    # The * CSS rule inside verbatim-box kills Word heading styles.
    # No max-height cap — content expands to show everything.
    col_client, col_standard = st.columns(2)

    with col_client:
        st.markdown(
            '<div class="section-label">📄 Client Contract — Verbatim Text</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="verbatim-box">{html.escape(analysis.client_verbatim)}</div>',
            unsafe_allow_html=True,
        )

    with col_standard:
        st.markdown(
            '<div class="section-label">📘 Company Standard — Verbatim Text</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="verbatim-box">{html.escape(analysis.standard_verbatim)}</div>',
            unsafe_allow_html=True,
        )

    # ── Row 4: Factual conflict ───────────────────────────────────────────────
    st.markdown(
        '<div class="section-label">⚡ Factual Conflict (Zero-Inference)</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="conflict-box">{html.escape(analysis.factual_conflict)}</div>',
        unsafe_allow_html=True,
    )

    # ── Row 5: Guardrail confirmation ─────────────────────────────────────────
    st.markdown(
        '<div style="margin-top:10px;padding:8px 12px;background:#f0fdf4;'
        'border:1px solid #bbf7d0;border-radius:6px;font-size:12px;color:#15803d;">'
        "🛡️ <strong>Guardrail Confirmed:</strong> "
        f"{html.escape(analysis.guardrail_note)}"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Close card ────────────────────────────────────────────────────────────
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("")


def render_full_report() -> None:
    """
    Orchestrates the complete Final Risk Assessment Report.

    Renders:
        1. Section header + Zero-Inference notice
        2. Summary metrics (Total / High / Medium / Low)
        3. Risk level legend
        4. Individual clause cards

    Only renders when st.session_state.final_report is not None.

    Returns:
        None
    """
    if not st.session_state.final_report:
        return

    st.markdown("---")
    st.markdown("## 📊 Final Risk Assessment Report")

    st.markdown(
        '<div style="color:#475569;font-size:13px;margin-bottom:20px;'
        'background:#f1f5f9;border-radius:6px;padding:10px 14px;">'
        "⚠️ <strong>Zero-Inference Rule enforced</strong> — "
        "All conflicts are literal textual contradictions only. "
        "No legal advice. No inferences. Verbatim quotes only."
        "</div>",
        unsafe_allow_html=True,
    )

    analyses = st.session_state.final_report.analyses
    total    = len(analyses)
    high     = sum(1 for a in analyses if a.risk_level.lower() == "high")
    medium   = sum(1 for a in analyses if a.risk_level.lower() == "medium")
    low      = sum(1 for a in analyses if a.risk_level.lower() == "low")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📋 Total Clauses", total)
    m2.metric("🔴 High Risk",     high)
    m3.metric("🟠 Medium Risk",   medium)
    m4.metric("🟢 Low Risk",      low)

    st.markdown("---")
    render_risk_legend()

    for analysis in analyses:
        render_risk_card(analysis)
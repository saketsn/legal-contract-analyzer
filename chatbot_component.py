"""
================================================================================
chatbot_component.py — Sidebar Chat Assistant
================================================================================
Purpose : Renders a fixed, always-visible Legal Assistant chat panel inside 
          the Streamlit sidebar. 

          All state lives in st.session_state with "chatbot_" prefix to avoid
          any collision with the main pipeline session state keys.

          Gemini 2.5 Flash is called server-side via LangChain — the API key
          never reaches the browser.

Usage:
    from chatbot_component import render_chatbot
    # Call this INSIDE the `with st.sidebar:` block in app.py
    render_chatbot(GEMINI_API_KEY)
================================================================================
"""

import streamlit as st
from langchain_google_genai import ChatGoogleGenerativeAI


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """You are the Legal Contract Analyzer Assistant — a helpful, friendly AI assistant embedded in the Advanced Legal Contract Analyzer web application.

YOUR ROLE:
Help users understand and use the Legal Contract Analyzer. Keep answers concise and friendly — 3 to 5 sentences max unless the user asks for more detail.

THE 5-STEP PIPELINE:
1. DISCOVERY SCAN — lightweight scan returning section headings only
2. TOOL 1 — extracts exact verbatim word-for-word text for selected clauses
3. HITL GATE — pipeline PAUSES, human must click APPROVE or REJECT
4. TOOL 2 — hybrid BM25 keyword (50%) + vector semantic (50%) search retrieves playbook standards
5. TOOL 3 — compares client text vs playbook, produces HIGH/MEDIUM/LOW risk report

THREE TOOLS:
- Tool 1 (extract_contract_terms): copies exact clause text from the client contract
- Tool 2 (query_playbook): searches ChromaDB with EnsembleRetriever (BM25 + vector)
- Tool 3 (generate_risk_report): produces the final risk analysis cards

FOUR GUARDRAILS:
- Verbatim Enforcer: Pydantic rejects text under 120 chars with summary phrases
- Risk Level Enforcer: only High, Medium, Low accepted
- Zero-Inference Rule: rejects inference language in factual_conflict
- HITL Structural Gate: Tools 2 and 3 are unreachable until hitl_approved == True

RISK LEVELS:
- HIGH: direct contradiction — client says Net 90, standard requires Net 30
- MEDIUM: client is silent on something the standard requires (gap)
- LOW: fully aligned, no deviation found

HOW TO USE STEP BY STEP:
1. Select Company Playbook from sidebar dropdown
2. Select Client Contract from sidebar dropdown
3. Click Run Discovery Scan
4. Select 2-4 clauses from the multiselect dropdown
5. Click Analyze Selected Clauses — Tool 1 extracts text
6. Review the HITL gate — check extracted clauses look correct
7. Click APPROVE — Tools 2 and 3 run automatically
8. Read the Final Risk Assessment Report

HOW TO ADD DOCUMENTS:
- Playbooks: drop .docx or .pdf into MyFiles/Contracts/company_standard/ or upload via UI, then click Rebuild Playbook DB
- Client contracts: drop .docx or .pdf into MyFiles/Contracts/clients/ or upload via UI — appears in dropdown automatically

TROUBLESHOOTING:
- No DB for this playbook → select it and click Rebuild Playbook DB in sidebar
- ChromaDB missing → run: python main.py with venv activated
- Slow response → Gemini API call in progress, wait 10-30 seconds
- Venv error → run env\\Scripts\\activate first

TWO PLAYBOOKS — GLOBEX vs NEXORA:
- Globex: Net 30 days, Delaware law, 30-day notice, 48-hour breach notification, 100% liability cap
- Nexora: Net 60 days, New South Wales law, 45-day notice, 72-hour breach notification, 150% liability cap
- Same client contract produces different risk results against different playbooks

OUT-OF-SCOPE: If asked anything not about this Legal Contract Analyzer, respond:
"I'm the Legal Contract Analyzer assistant. I can only help with questions about this tool. What would you like to know?"

TONE: Friendly, concise, plain language. Use bullet points when listing steps."""


# ─────────────────────────────────────────────────────────────────────────────
# GEMINI CALL
# ─────────────────────────────────────────────────────────────────────────────
def _get_bot_response(user_message: str, history: list, gemini_api_key: str) -> str:
    """
    Calls Gemini 2.5 Flash server-side via LangChain.
    API key stays in Python — never reaches the browser.

    Args:
        user_message   (str):  Latest user message.
        history        (list): Previous {"role", "content"} dicts (last 8 only).
        gemini_api_key (str):  From .env

    Returns:
        str: Bot response text.
    """
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.4,
        google_api_key=gemini_api_key,
    )
    messages = [("system", _SYSTEM_PROMPT)]
    for msg in history[-8:]:
        messages.append((msg["role"], msg["content"]))
    messages.append(("user", user_message))

    try:
        return llm.invoke(messages).content
    except Exception as e:
        return f"Sorry, something went wrong. Please try again. ({str(e)[:80]})"


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
def render_chatbot(gemini_api_key: str) -> None:
    """
    Renders the Legal Assistant chat panel inside the Streamlit sidebar.
    Always visible, fixed 400px height with internal scrolling.

    Args:
        gemini_api_key (str): GEMINI_API_KEY loaded from .env in app.py

    Returns:
        None
    """

    # ── Session state init ────────────────────────────────────────────────────
    if "chatbot_history" not in st.session_state:
        st.session_state.chatbot_history = []

    # Removed the duplicate st.markdown("---") from here to fix the double-spacing issue!

    st.markdown(
        '<p style="font-size:12px;font-weight:700;color:#374151;'
        'text-transform:uppercase;letter-spacing:0.8px;margin:4px 0 8px 0;">'
        "💬 Legal Assistant</p>",
        unsafe_allow_html=True,
    )

    # ── Header banner ─────────────────────────────────────────────────────
    st.markdown(
        """
<div style="background:linear-gradient(135deg,#1E2D5E 0%,#0D9488 100%);
            padding:10px 14px;border-radius:8px;margin-bottom:10px;
            display:flex;align-items:center;gap:10px;">
  <span style="font-size:20px;">🤖</span>
  <div>
    <div style="color:white;font-weight:700;font-size:13px;">Legal Assistant</div>
    <div style="color:rgba(255,255,255,0.75);font-size:10px;">
      Gemini 2.5 Flash &nbsp;·&nbsp; Legal Analyzer questions only
    </div>
  </div>
  <div style="margin-left:auto;width:8px;height:8px;background:#22c55e;
              border-radius:50%;border:2px solid white;"></div>
</div>
""",
        unsafe_allow_html=True,
    )

    # ── Fixed 400px scrollable chat container ─────────────────────────────
    chat_container = st.container(height=400)

    with chat_container:
        # ── Quick chips (only when no history yet) ────────────────────────
        if not st.session_state.chatbot_history:
            st.markdown(
                '<p style="font-size:11px;color:#64748b;margin:0 0 6px 0;">'
                "💡 Quick questions:</p>",
                unsafe_allow_html=True,
            )
            chips = [
                ("📋 How to use?",    "How do I use this tool step by step?"),
                ("🎯 HIGH risk?",     "What does HIGH risk mean in the report?"),
                ("👤 HITL gate?",     "What is the HITL gate and why does it exist?"),
                ("🛡️ Guardrails?",   "What are the four guardrails and how do they work?"),
                ("📁 Add contract?",  "How do I add a new client contract or playbook?"),
                ("🔍 What is RAG?",   "What is RAG and how does ChromaDB work?"),
            ]
            col1, col2 = st.columns(2)
            for i, (label, question) in enumerate(chips):
                col = col1 if i % 2 == 0 else col2
                with col:
                    if st.button(label, key=f"chip_{i}", use_container_width=True):
                        st.session_state.chatbot_history.append(
                            {"role": "user", "content": question}
                        )
                        with st.spinner("Thinking..."):
                            reply = _get_bot_response(
                                question,
                                st.session_state.chatbot_history[:-1],
                                gemini_api_key,
                            )
                        st.session_state.chatbot_history.append(
                            {"role": "assistant", "content": reply}
                        )
                        st.rerun()

            st.markdown("---")

        # ── Chat history ──────────────────────────────────────────────────
        for msg in st.session_state.chatbot_history:
            avatar = "🤖" if msg["role"] == "assistant" else "👤"
            with st.chat_message(msg["role"], avatar=avatar):
                st.markdown(msg["content"])

    # ── Chat input (Outside the fixed container) ──────────────────────────
    user_input = st.chat_input(
        "Ask about the Legal Contract Analyzer...",
        key="chatbot_sidebar_input",
    )

    if user_input:
        # Display user message instantly inside the container
        with chat_container:
            with st.chat_message("user", avatar="👤"):
                st.markdown(user_input)
                
        st.session_state.chatbot_history.append(
            {"role": "user", "content": user_input}
        )
        
        # Process and display assistant response inside the container
        with chat_container:
            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("Thinking..."):
                    reply = _get_bot_response(
                        user_input,
                        st.session_state.chatbot_history[:-1],
                        gemini_api_key,
                    )
                st.markdown(reply)
                
        st.session_state.chatbot_history.append(
            {"role": "assistant", "content": reply}
        )
        st.rerun()

    # ── Clear button (Outside the fixed container) ────────────────────────
    if st.session_state.chatbot_history:
        st.markdown("")
        if st.button(
            "🗑️ Clear chat",
            key="chatbot_clear",
            use_container_width=True,
        ):
            st.session_state.chatbot_history = []
            st.rerun()
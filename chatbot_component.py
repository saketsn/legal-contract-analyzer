"""
================================================================================
chatbot_component.py — Sidebar Chat Assistant (Now with RAG!)
================================================================================
Purpose : Renders a fixed, always-visible Legal Assistant chat panel.
          Now includes Dynamic Context and Vector DB querying!
================================================================================
"""

import os
import streamlit as st
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma

# ─────────────────────────────────────────────────────────────────────────────
# CHAT INPUT CSS — visible border at idle, branded on focus, no red bleed
# ─────────────────────────────────────────────────────────────────────────────
_CHAT_INPUT_CSS = """
<style>
/* ── GLOBAL nuclear reset — kill every possible red/pink border source ───── */
/* Streamlit wraps chat_input in multiple divs; target them all globally      */

div[data-testid="stChatInput"],
div[data-testid="stChatInput"] *,
div[data-testid="stChatInput"] textarea,
div[data-testid="stChatInput"] textarea:focus,
div[data-testid="stChatInput"] textarea:active,
div[data-testid="stChatInput"] textarea:invalid,
div[data-testid="stChatInput"] textarea:focus:invalid,
div[data-testid="stChatInput"] textarea:required,
div[data-testid="stChatInput"] textarea:placeholder-shown,
div[data-testid="stChatInput"] [data-baseweb="base-input"],
div[data-testid="stChatInput"] [data-baseweb="base-input"]:focus,
div[data-testid="stChatInput"] [data-baseweb="base-input"]:focus-within,
div[data-testid="stChatInput"] [data-baseweb="textarea"],
div[data-testid="stChatInput"] [class*="stChatInput"],
div[data-testid="stChatInputTextArea"],
div[data-testid="stChatInputTextArea"]:focus,
div[data-testid="stChatInputTextArea"]:invalid {
    border-color: transparent !important;
    outline: none !important;
    outline-color: transparent !important;
    box-shadow: none !important;
    -webkit-box-shadow: none !important;
    -moz-box-shadow: none !important;
}

/* ── Chat input outer container — idle state ────────────────────────────── */
[data-testid="stSidebar"] div[data-testid="stChatInput"] {
    border: 1.5px solid #94a3b8 !important;
    border-radius: 12px !important;
    background: #f8fafc !important;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06) !important;
    transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
    overflow: hidden !important;
}

/* ── Chat input outer container — focus state ───────────────────────────── */
[data-testid="stSidebar"] div[data-testid="stChatInput"]:focus-within {
    border: 1.5px solid #0D9488 !important;
    box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.15) !important;
    background: #ffffff !important;
}

/* ── Teal caret while typing ────────────────────────────────────────────── */
[data-testid="stSidebar"] div[data-testid="stChatInput"] textarea {
    caret-color: #0D9488 !important;
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
    background: transparent !important;
}

/* ── Send button styling ────────────────────────────────────────────────── */
[data-testid="stSidebar"] div[data-testid="stChatInput"] button {
    border: none !important;
    background: transparent !important;
    color: #0D9488 !important;
    box-shadow: none !important;
}
[data-testid="stSidebar"] div[data-testid="stChatInput"] button:hover {
    color: #0f766e !important;
}
</style>
"""


# ─────────────────────────────────────────────────────────────────────────────
# DYNAMIC SYSTEM PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def _build_system_prompt(playbook_files: list, selected_playbook: str, retrieved_context: str) -> str:
    """Builds a dynamic system prompt injecting current file states and DB context."""

    files_str = ", ".join(playbook_files) if playbook_files else "None currently uploaded."

    prompt = f"""You are the Legal Contract Analyzer Assistant — a helpful, friendly AI assistant embedded in the Advanced Legal Contract Analyzer web application.

YOUR ROLE:
Help users understand the tool AND answer questions about their legal playbooks. Keep answers concise and friendly — 3 to 5 sentences max.

CURRENT SYSTEM STATE:
- Total Playbooks Uploaded: {len(playbook_files)}
- Names of Uploaded Playbooks: {files_str}
- Currently Selected Playbook: {selected_playbook if selected_playbook else 'None'}

THE 5-STEP PIPELINE:
1. DISCOVERY SCAN — lightweight scan returning section headings only
2. TOOL 1 — extracts exact verbatim text
3. HITL GATE — pipeline PAUSES, human must click APPROVE or REJECT
4. TOOL 2 — hybrid BM25 + vector search retrieves playbook standards
5. TOOL 3 — compares client text vs playbook, produces HIGH/MEDIUM/LOW risk report

"""
    # If we retrieved context from ChromaDB, inject it here!
    if retrieved_context:
        prompt += f"""
=========================================
RETRIEVED KNOWLEDGE FROM CURRENT PLAYBOOK
=========================================
The user is asking a question that requires knowledge from "{selected_playbook}".
Use the following exact text from the playbook to answer their question:

{retrieved_context}
=========================================
"""
    else:
        prompt += "OUT-OF-SCOPE: If asked about playbook details, tell the user to select a playbook first, or state that the info isn't in the current playbook.\n"

    prompt += "TONE: Friendly, concise, plain language. Use bullet points when listing steps."
    return prompt


# ─────────────────────────────────────────────────────────────────────────────
# GEMINI CALL WITH RAG
# ─────────────────────────────────────────────────────────────────────────────
def _get_bot_response(user_message: str, history: list, gemini_api_key: str, selected_playbook: str, playbook_files: list) -> str:
    """
    Calls Gemini 2.5 Flash. First queries ChromaDB for context if a playbook is selected.
    """
    retrieved_context = ""

    # 1. Silently query ChromaDB if a playbook is active
    if selected_playbook and selected_playbook != "No files found":
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            chroma_persist_dir = os.path.join(base_dir, "chroma_db")

            _playbook_stem = os.path.splitext(selected_playbook)[0]
            _safe_stem     = "".join(c if c.isalnum() or c in "-_" else "_" for c in _playbook_stem)
            _playbook_dir  = os.path.join(chroma_persist_dir, _safe_stem)

            if os.path.exists(_playbook_dir):
                embeddings = GoogleGenerativeAIEmbeddings(
                    model="models/gemini-embedding-001",
                    google_api_key=gemini_api_key
                )
                vector_store = Chroma(persist_directory=_playbook_dir, embedding_function=embeddings)

                # Retrieve top 3 most relevant chunks
                docs = vector_store.similarity_search(user_message, k=3)
                retrieved_context = "\n---\n".join([d.page_content for d in docs])
        except Exception as e:
            print(f"Chatbot RAG Error: {e}")  # Fails gracefully if DB isn't built yet

    # 2. Build the LLM prompt with the new context
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.4,
        google_api_key=gemini_api_key,
    )

    dynamic_prompt = _build_system_prompt(playbook_files, selected_playbook, retrieved_context)
    messages = [("system", dynamic_prompt)]

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
def render_chatbot(gemini_api_key: str, selected_playbook: str, playbook_files: list) -> None:
    """
    Renders the Legal Assistant chat panel inside the Streamlit sidebar.
    Requires playbook context parameters.
    """

    if "chatbot_history" not in st.session_state:
        st.session_state.chatbot_history = []

    # Inject chat input CSS — visible border at idle, teal on focus, no red bleed
    st.markdown(_CHAT_INPUT_CSS, unsafe_allow_html=True)

    st.markdown(
        '<p style="font-size:12px;font-weight:700;color:#374151;'
        'text-transform:uppercase;letter-spacing:0.8px;margin:4px 0 8px 0;">'
        "💬 Legal Assistant</p>",
        unsafe_allow_html=True,
    )

    st.markdown(
        """
<div style="background:linear-gradient(135deg,#1E2D5E 0%,#0D9488 100%);
            padding:10px 14px;border-radius:8px;margin-bottom:10px;
            display:flex;align-items:center;gap:10px;">
  <span style="font-size:20px;">🤖</span>
  <div>
    <div style="color:white;font-weight:700;font-size:13px;">Legal Assistant</div>
    <div style="color:rgba(255,255,255,0.75);font-size:10px;">
      Gemini 2.5 Flash &nbsp;·&nbsp; Ask about the app or playbook!
    </div>
  </div>
  <div style="margin-left:auto;width:8px;height:8px;background:#22c55e;
              border-radius:50%;border:2px solid white;"></div>
</div>
""",
        unsafe_allow_html=True,
    )

    chat_container = st.container(height=400)

    with chat_container:
        if not st.session_state.chatbot_history:
            st.markdown(
                '<p style="font-size:11px;color:#64748b;margin:0 0 6px 0;">'
                "💡 Quick questions:</p>",
                unsafe_allow_html=True,
            )
            chips = [
                ("📋 How to use?",        "How do I use this tool step by step?"),
                ("📚 Listed playbooks?",  "What are the names of the playbooks currently stored?"),
                ("⚖️ Liability Cap?",     "What is the liability cap in the currently selected playbook?"),
                ("⏳ Notice Period?",     "What is the required notice period for termination in the selected playbook?"),
                ("🛡️ Guardrails?",       "What are the four guardrails and how do they work?"),
                ("🔍 What is RAG?",       "What is RAG and how does ChromaDB work?"),
            ]
            col1, col2 = st.columns(2)
            for i, (label, question) in enumerate(chips):
                col = col1 if i % 2 == 0 else col2
                with col:
                    if st.button(label, key=f"chip_{i}", use_container_width=True):
                        st.session_state.chatbot_history.append({"role": "user", "content": question})
                        with st.spinner("Searching DB & Thinking..."):
                            reply = _get_bot_response(
                                question, st.session_state.chatbot_history[:-1], gemini_api_key, selected_playbook, playbook_files
                            )
                        st.session_state.chatbot_history.append({"role": "assistant", "content": reply})
                        st.rerun()
            st.markdown("---")

        for msg in st.session_state.chatbot_history:
            avatar = "🤖" if msg["role"] == "assistant" else "👤"
            with st.chat_message(msg["role"], avatar=avatar):
                st.markdown(msg["content"])

    user_input = st.chat_input("Ask about the Analyzer or the current Playbook...", key="chatbot_sidebar_input")

    if user_input:
        with chat_container:
            with st.chat_message("user", avatar="👤"):
                st.markdown(user_input)

        st.session_state.chatbot_history.append({"role": "user", "content": user_input})

        with chat_container:
            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("Searching Playbook DB..."):
                    reply = _get_bot_response(
                        user_input, st.session_state.chatbot_history[:-1], gemini_api_key, selected_playbook, playbook_files
                    )
                st.markdown(reply)

        st.session_state.chatbot_history.append({"role": "assistant", "content": reply})
        st.rerun()

    if st.session_state.chatbot_history:
        st.markdown("")
        if st.button("🗑️ Clear chat", key="chatbot_clear", use_container_width=True):
            st.session_state.chatbot_history = []
            st.rerun()
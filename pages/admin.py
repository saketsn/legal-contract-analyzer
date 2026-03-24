"""
================================================================================
pages/admin.py -- Admin Panel
================================================================================
Access  : Via "Admin Panel" button in app.py sidebar → password gate
Password: Set ADMIN_PASSWORD in .env file

Tabs:
    1. Documents   -- Department-wise contract management + playbook management
    2. Token Usage -- LLM API call analytics + cost breakdown
    3. History     -- Pipeline run history log
    4. Export      -- PDF + Excel report download

Navigation:
    "← Back to Main App" button in sidebar → st.switch_page("app.py")
================================================================================
"""

import os
import glob
import shutil
import json
from datetime import datetime, timedelta
from io import BytesIO

import streamlit as st
from dotenv import load_dotenv

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors as rl_colors
from reportlab.lib.units import inch

import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

import logger
import dept_db   # SQLite department metadata layer

# ==========================================
# SECTION 1: CONFIG & PATHS
# ==========================================
load_dotenv()

ADMIN_PASSWORD       = os.getenv("ADMIN_PASSWORD", "admin123")
BASE_DIR             = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS_DIR        = os.path.join(BASE_DIR, "MyFiles", "Contracts")
COMPANY_PLAYBOOK_DIR = os.path.join(CONTRACTS_DIR, "company_standard")
CLIENT_CONTRACTS_DIR = os.path.join(CONTRACTS_DIR, "clients")
CHROMA_PERSIST_DIR   = os.path.join(BASE_DIR, "chroma_db")

# Initialise SQLite dept DB on startup (auto-migrates from dept_meta.json)
dept_db.init_db()

st.set_page_config(
    page_title="Admin Panel — Legal Contract Analyzer",
    page_icon="⚙",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
    [data-testid="stSidebarNav"] { display: none !important; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# SECTION 2: SESSION STATE
# ==========================================
for key, val in {
    "admin_auth":          False,
    "admin_fail_count":    0,
    "admin_lockout_until": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ==========================================
# SECTION 3: SIDEBAR
# ==========================================
with st.sidebar:
    if st.button("← Back to Main App", use_container_width=True):
        st.switch_page("app.py")

    if st.session_state.admin_auth:
        st.markdown("---")
        st.markdown(
            '<p style="font-size:11px;color:#6b7280;text-align:center;">'
            'Logged in as Admin</p>',
            unsafe_allow_html=True,
        )
        if st.button("Logout", use_container_width=True):
            st.session_state.admin_auth       = False
            st.session_state.admin_fail_count = 0
            st.rerun()

# ==========================================
# SECTION 4: PASSWORD GATE
# ==========================================
if not st.session_state.admin_auth:

    locked = False
    if st.session_state.admin_lockout_until:
        remaining = (st.session_state.admin_lockout_until - datetime.now()).total_seconds()
        if remaining > 0:
            locked = True
        else:
            st.session_state.admin_lockout_until = None
            st.session_state.admin_fail_count    = 0

    col_l, col_c, col_r = st.columns([1, 1.2, 1])
    with col_c:
        st.markdown("<div style='height:60px'></div>", unsafe_allow_html=True)
        st.markdown(
            '<div style="text-align:center;margin-bottom:24px;">'
            '<div style="font-size:40px;">⚙</div>'
            '<h2 style="margin:8px 0 4px;">Admin panel</h2>'
            '<p style="color:#6b7280;font-size:14px;margin:0;">'
            'Restricted access. Enter your password to continue.</p>'
            '</div>',
            unsafe_allow_html=True,
        )

        if locked:
            remaining = int((st.session_state.admin_lockout_until - datetime.now()).total_seconds())
            st.warning(f"🔒 Too many failed attempts. Try again in {remaining} seconds.")
            st.markdown(
                '<div style="display:flex;gap:6px;justify-content:center;margin:12px 0;">'
                + ''.join([
                    '<div style="width:10px;height:10px;border-radius:50%;background:#ef4444;"></div>'
                    for _ in range(5)
                ])
                + '</div>',
                unsafe_allow_html=True,
            )
        else:
            if st.session_state.admin_fail_count > 0:
                dots_html = '<div style="display:flex;gap:6px;justify-content:center;margin-bottom:12px;">'
                for i in range(5):
                    color = "#ef4444" if i < st.session_state.admin_fail_count else "#e5e7eb"
                    dots_html += f'<div style="width:10px;height:10px;border-radius:50%;background:{color};"></div>'
                dots_html += "</div>"
                st.markdown(dots_html, unsafe_allow_html=True)

            pwd = st.text_input(
                "Password", type="password",
                label_visibility="collapsed",
                placeholder="Enter admin password...",
            )

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("Login to admin", type="primary", use_container_width=True):
                    if pwd == ADMIN_PASSWORD:
                        st.session_state.admin_auth       = True
                        st.session_state.admin_fail_count = 0
                        st.rerun()
                    else:
                        st.session_state.admin_fail_count += 1
                        if st.session_state.admin_fail_count >= 5:
                            st.session_state.admin_lockout_until = (
                                datetime.now() + timedelta(seconds=60)
                            )
                            st.rerun()
                        else:
                            rem = 5 - st.session_state.admin_fail_count
                            st.error(f"Incorrect password. {rem} attempt(s) remaining.")
            with col_b:
                if st.button("Cancel", use_container_width=True):
                    st.switch_page("app.py")

    st.stop()


# ==========================================
# SECTION 5: HELPER FUNCTIONS
# ==========================================

def get_departments() -> list:
    """Returns sorted list of department subfolder names inside clients/."""
    if not os.path.exists(CLIENT_CONTRACTS_DIR):
        return []
    return sorted([
        d for d in os.listdir(CLIENT_CONTRACTS_DIR)
        if os.path.isdir(os.path.join(CLIENT_CONTRACTS_DIR, d))
    ])


def get_dept_files(dept: str) -> list:
    """Returns list of dicts with file info for a specific department."""
    dept_dir = os.path.join(CLIENT_CONTRACTS_DIR, dept)
    files = []
    for ext in ["*.pdf", "*.docx"]:
        for f in glob.glob(os.path.join(dept_dir, ext)):
            stat = os.stat(f)
            files.append({
                "name":       os.path.basename(f),
                "path":       f,
                "size_kb":    round(stat.st_size / 1024, 1),
                "modified":   datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
                "department": dept,
            })
    return sorted(files, key=lambda x: x["name"])


def get_flat_client_files() -> list:
    """Returns files directly in clients/ root (legacy flat layout)."""
    files = []
    for ext in ["*.pdf", "*.docx"]:
        for f in glob.glob(os.path.join(CLIENT_CONTRACTS_DIR, ext)):
            stat = os.stat(f)
            files.append({
                "name":       os.path.basename(f),
                "path":       f,
                "size_kb":    round(stat.st_size / 1024, 1),
                "modified":   datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
                "department": "(unorganized)",
            })
    return sorted(files, key=lambda x: x["name"])


def get_all_client_files() -> list:
    """Returns all client files from all departments + flat root."""
    all_files = []
    all_files.extend(get_flat_client_files())
    for dept in get_departments():
        all_files.extend(get_dept_files(dept))
    return sorted(all_files, key=lambda x: (x["department"], x["name"]))


def get_all_client_filenames() -> set:
    """Returns set of ALL filenames across ALL departments + flat root."""
    return {f["name"] for f in get_all_client_files()}


def find_file_department(filename: str) -> str:
    """Returns the department (or 'clients/ root') where a filename lives."""
    if os.path.exists(os.path.join(CLIENT_CONTRACTS_DIR, filename)):
        return "clients/ (root)"
    for dept in get_departments():
        if os.path.exists(os.path.join(CLIENT_CONTRACTS_DIR, dept, filename)):
            return dept
    return "unknown"


def get_playbook_files() -> list:
    """Returns list of dicts with playbook file info."""
    files = []
    for ext in ["*.pdf", "*.docx"]:
        for f in glob.glob(os.path.join(COMPANY_PLAYBOOK_DIR, ext)):
            stat      = os.stat(f)
            stem      = os.path.splitext(os.path.basename(f))[0]
            safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)
            chroma    = os.path.join(CHROMA_PERSIST_DIR, safe_stem)
            hash_file = os.path.join(chroma, ".playbook_hash")
            built_at  = "—"
            if os.path.exists(hash_file):
                try:
                    data     = json.load(open(hash_file))
                    built_at = data.get("built_at", "—")
                except Exception:
                    pass
            files.append({
                "name":       os.path.basename(f),
                "path":       f,
                "size_kb":    round(stat.st_size / 1024, 1),
                "modified":   datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
                "db_exists":  os.path.exists(chroma) and bool(os.listdir(chroma)),
                "built_at":   built_at,
                "chroma_dir": chroma,
            })
    return sorted(files, key=lambda x: x["name"])


def get_file_risk_status(filename: str) -> str:
    """Looks up last known risk status from history_log for a given filename."""
    history = logger.get_history_log()
    for entry in reversed(history):
        if entry.get("client_file") == filename:
            h = entry.get("high_count",   0)
            m = entry.get("medium_count", 0)
            l = entry.get("low_count",    0)
            if h > 0: return "High risk"
            if m > 0: return "Medium risk"
            if l > 0: return "Low risk"
            return "Analyzed"
    return "Not analyzed"


def risk_badge_html(status: str) -> str:
    colors_map = {
        "High risk":    ("var(--color-background-danger)",   "var(--color-text-danger)"),
        "Medium risk":  ("var(--color-background-warning)",  "var(--color-text-warning)"),
        "Low risk":     ("var(--color-background-success)",  "var(--color-text-success)"),
        "Analyzed":     ("var(--color-background-success)",  "var(--color-text-success)"),
        "Not analyzed": ("var(--color-background-secondary)","var(--color-text-secondary)"),
    }
    bg, fg = colors_map.get(status, colors_map["Not analyzed"])
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 10px;'
        f'border-radius:12px;font-size:11px;font-weight:500;">{status}</span>'
    )


def filter_entries_by_date(entries: list, date_filter: str) -> list:
    """Filters log entries by date range string."""
    if date_filter == "All time":
        return entries
    now    = datetime.now()
    cutoff = now - timedelta(days=7 if date_filter == "Last 7 days" else 30)
    result = []
    for e in entries:
        try:
            if datetime.fromisoformat(e.get("timestamp", "")) >= cutoff:
                result.append(e)
        except Exception:
            pass
    return result


def save_client_file_with_uniqueness_check(
    uploaded_file, target_dir: str
) -> tuple[bool, str]:
    """Saves a client contract with GLOBAL uniqueness enforcement."""
    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)

    all_existing = get_all_client_filenames()
    if uploaded_file.name in all_existing:
        existing_dept = find_file_department(uploaded_file.name)
        return (
            False,
            f"**'{uploaded_file.name}'** already exists in **{existing_dept}**. "
            f"Filenames must be unique across all departments. "
            f"Please rename the file before uploading.",
        )

    dest = os.path.join(target_dir, uploaded_file.name)
    try:
        with open(dest, "wb") as fh:
            fh.write(uploaded_file.getbuffer())
        return (True, f"✅ '{uploaded_file.name}' uploaded successfully.")
    except Exception as e:
        return (False, f"❌ Upload failed: {str(e)}")


# ── Department metadata now handled by dept_db (SQLite) ──────────────────────
# All load_dept_meta / save_dept_meta / get_dept_head / set_dept_head calls
# replaced with dept_db functions throughout this file.


# ==========================================
# SECTION 6: MAIN ADMIN PAGE
# ==========================================

st.markdown(
    '<h1 style="font-size:28px;font-weight:700;color:#1E2D5E;margin-bottom:4px;">'
    '⚙ Admin Panel</h1>',
    unsafe_allow_html=True,
)
st.markdown("Legal Contract Analyzer — administration and analytics dashboard.")
st.markdown("---")

tab1, tab2, tab3, tab4 = st.tabs([
    "📂 Documents",
    "📊 Token Usage",
    "🕓 History",
    "⬇ Export",
])


# ==========================================
# TAB 1: DOCUMENT MANAGEMENT
# ==========================================
with tab1:

    depts      = get_departments()
    flat_files = get_flat_client_files()
    pb_files   = get_playbook_files()

    all_dept_files = []
    for d in depts:
        all_dept_files.extend(get_dept_files(d))

    total_contracts = len(all_dept_files) + len(flat_files)
    history         = logger.get_history_log()
    analyzed_names  = {e.get("client_file") for e in history}
    unanalyzed      = sum(
        1 for f in (all_dept_files + flat_files)
        if f["name"] not in analyzed_names
    )

    # ── Summary metrics ───────────────────────────────────────────────────────
    m1, m2, m3 = st.columns(3)
    m1.metric("Departments",     len(depts))
    m2.metric("Total contracts", total_contracts)
    m3.metric("Unanalyzed",      unanalyzed)

    st.markdown("---")
    st.markdown("#### Client contracts")

    # ── Toolbar ───────────────────────────────────────────────────────────────
    tool_col1, tool_col2, tool_col3, tool_col4, tool_col5 = st.columns([2, 2, 2, 1.5, 1.5])

    with tool_col1:
        dept_filter_options  = ["All departments"] + depts
        selected_filter_dept = st.selectbox(
            "Department", options=dept_filter_options,
            key="doc_dept_filter", label_visibility="collapsed",
        )

    with tool_col2:
        search_term = st.text_input(
            "Search", placeholder="Search by filename...",
            key="doc_search", label_visibility="collapsed",
        )

    with tool_col3:
        status_filter = st.selectbox(
            "Status", ["All statuses", "Analyzed", "Unanalyzed"],
            key="doc_status_filter", label_visibility="collapsed",
        )

    # Fix 2: tool_col4 and tool_col5 replaced by radio — only one panel open at a time
    with tool_col4:
        pass
    with tool_col5:
        pass

    panel_mode = st.radio(
        "Panel",
        options=["None", "Upload contract", "Manage departments"],
        index=0,
        horizontal=True,
        key="panel_mode_radio",
        label_visibility="collapsed",
    )

    # ── Upload panel ──────────────────────────────────────────────────────────
    if panel_mode == "Upload contract":
        with st.container():
            st.markdown(
                '<div style="background:var(--color-background-secondary);'
                'border-radius:8px;padding:14px 16px;margin:8px 0;">',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div style="font-size:13px;font-weight:500;margin-bottom:10px;">'
                'Upload contract</div>',
                unsafe_allow_html=True,
            )
            up_col1, _ = st.columns([3, 1])
            with up_col1:
                upload_dest_dept = st.selectbox(
                    "Upload to department",
                    options=["(flat root — no department)"] + depts,
                    key="upload_dest_dept",
                )
            new_file = st.file_uploader(
                "Choose file", type=["pdf", "docx"],
                key="tab1_upload", label_visibility="collapsed",
            )
            if new_file:
                target = (
                    CLIENT_CONTRACTS_DIR
                    if upload_dest_dept == "(flat root — no department)"
                    else os.path.join(CLIENT_CONTRACTS_DIR, upload_dest_dept)
                )
                ok, msg = save_client_file_with_uniqueness_check(new_file, target)
                if ok:
                    # A1: use toast so message never overflows
                    st.toast(msg, icon="✅")
                    st.rerun()
                else:
                    st.warning(msg)
            st.markdown("</div>", unsafe_allow_html=True)

    # ── Manage departments panel — SQLite backed ─────────────────────────────
    if panel_mode == "Manage departments":
        with st.container():
            st.markdown(
                '<div style="background:var(--color-background-secondary);'
                'border-radius:8px;padding:14px 16px;margin:8px 0;">',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div style="font-size:13px;font-weight:500;margin-bottom:12px;">'
                'Manage departments</div>',
                unsafe_allow_html=True,
            )

            # ── Create new department ─────────────────────────────────────────
            st.markdown(
                '<div style="font-size:12px;color:var(--color-text-secondary);'
                'margin-bottom:6px;">Create new department</div>',
                unsafe_allow_html=True,
            )
            cr1, cr2, cr3, cr4, cr5 = st.columns([2, 2, 2, 2, 1])
            with cr1:
                new_dept_name = st.text_input(
                    "Dept name", placeholder="Department name",
                    key="new_dept_name_input", label_visibility="collapsed",
                )
            with cr2:
                new_dept_head = st.text_input(
                    "Head name", placeholder="Head name (optional)",
                    key="new_dept_head_input", label_visibility="collapsed",
                )
            with cr3:
                new_dept_email = st.text_input(
                    "Head email", placeholder="Email (optional)",
                    key="new_dept_email_input", label_visibility="collapsed",
                )
            with cr4:
                new_dept_phone = st.text_input(
                    "Head phone", placeholder="Phone (optional)",
                    key="new_dept_phone_input", label_visibility="collapsed",
                )
            with cr5:
                if st.button("Create", key="create_dept_btn", use_container_width=True):
                    if not new_dept_name.strip():
                        st.session_state["create_dept_err"] = "Please enter a department name."
                    else:
                        new_path = os.path.join(CLIENT_CONTRACTS_DIR, new_dept_name.strip())
                        if os.path.exists(new_path):
                            st.warning(f"'{new_dept_name}' already exists.")
                        else:
                            # Validate all 4 fields before creating
                            dname_ok, dname_err = dept_db.validate_dept_name(new_dept_name.strip())
                            hname_ok, hname_err = dept_db.validate_head_name(new_dept_head.strip())
                            email_ok, email_err = dept_db.validate_email(new_dept_email.strip())
                            phone_ok, phone_err = dept_db.validate_phone(new_dept_phone.strip())
                            # Store error for full-width display outside the button column
                            if not dname_ok:
                                st.session_state["create_dept_err"] = dname_err
                            elif not hname_ok:
                                st.session_state["create_dept_err"] = hname_err
                            elif not email_ok:
                                st.session_state["create_dept_err"] = email_err
                            elif not phone_ok:
                                st.session_state["create_dept_err"] = phone_err
                            else:
                                st.session_state.pop("create_dept_err", None)
                                os.makedirs(new_path, exist_ok=True)
                                dept_db.upsert_dept(
                                    new_dept_name.strip(),
                                    new_dept_head.strip(),
                                    new_dept_email.strip(),
                                    new_dept_phone.strip(),
                                )
                                st.toast(f"Department '{new_dept_name}' created.", icon="✅")
                                st.rerun()

            # Full-width error display for create form — outside the button column
            if st.session_state.get("create_dept_err"):
                st.error(st.session_state["create_dept_err"])
                if st.button("Dismiss", key="dismiss_create_err", type="secondary"):
                    st.session_state.pop("create_dept_err", None)
                    st.rerun()

            # ── Department heads table with 5 cols + inline edit ──────────────
            if depts:
                st.markdown(
                    '<div style="border-top:0.5px solid var(--color-border-tertiary);'
                    'margin:14px 0 10px;"></div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    '<div style="font-size:12px;color:var(--color-text-secondary);'
                    'margin-bottom:6px;">Department heads</div>',
                    unsafe_allow_html=True,
                )

                if "editing_dept_head" not in st.session_state:
                    st.session_state["editing_dept_head"] = None

                # Table column headers — bold
                th1, th2, th3, th4, th5, th6 = st.columns([1.5, 1.8, 2, 1.8, 1.8, 1])
                for col, label in zip(
                    [th1, th2, th3, th4, th5, th6],
                    ["Department", "Head name", "Email", "Phone", "Updated", "Action"],
                ):
                    col.markdown(
                        f'<div style="font-size:11px;font-weight:700;'
                        f'color:var(--color-text-primary);text-transform:uppercase;'
                        f'letter-spacing:0.5px;padding:4px 0;">{label}</div>',
                        unsafe_allow_html=True,
                    )
                st.markdown(
                    '<div style="border-top:0.5px solid var(--color-border-tertiary);'
                    'margin-bottom:4px;"></div>',
                    unsafe_allow_html=True,
                )

                # Load all dept rows from SQLite once
                all_db_depts = {d["name"]: d for d in dept_db.get_all_depts()}

                for dept in depts:
                    db_row     = all_db_depts.get(dept, {})
                    is_editing = st.session_state["editing_dept_head"] == dept

                    tr1, tr2, tr3, tr4, tr5, tr6 = st.columns([1.5, 1.8, 2, 1.8, 1.8, 1])

                    if is_editing:
                        # ── Edit mode — all fields inline ─────────────────────
                        with tr1:
                            edited_dept_name = st.text_input(
                                "Dept", value=dept,
                                key=f"edit_dname_{dept}",
                                label_visibility="collapsed",
                            )
                        with tr2:
                            edited_head = st.text_input(
                                "Head", value=db_row.get("head_name", ""),
                                key=f"edit_head_input_{dept}",
                                label_visibility="collapsed",
                            )
                        with tr3:
                            edited_email = st.text_input(
                                "Email", value=db_row.get("head_email", ""),
                                key=f"edit_email_{dept}",
                                label_visibility="collapsed",
                            )
                        with tr4:
                            edited_phone = st.text_input(
                                "Phone", value=db_row.get("head_phone", ""),
                                key=f"edit_phone_{dept}",
                                label_visibility="collapsed",
                            )
                        with tr5:
                            st.markdown(
                                '<div style="font-size:11px;color:var(--color-text-secondary);'
                                'padding:10px 0;">editing...</div>',
                                unsafe_allow_html=True,
                            )
                        with tr6:
                            if st.button("Save", key=f"save_head_{dept}",
                                         use_container_width=True, type="primary"):
                                # Validate all 4 fields
                                dname_ok, dname_err = dept_db.validate_dept_name(edited_dept_name.strip())
                                hname_ok, hname_err = dept_db.validate_head_name(edited_head.strip())
                                email_ok, email_err = dept_db.validate_email(edited_email.strip())
                                phone_ok, phone_err = dept_db.validate_phone(edited_phone.strip())

                                # Store error in session state so it renders
                                # FULL WIDTH below the row — never inside a narrow column
                                if not dname_ok:
                                    st.session_state[f"dept_err_{dept}"] = dname_err
                                elif not hname_ok:
                                    st.session_state[f"dept_err_{dept}"] = hname_err
                                elif not email_ok:
                                    st.session_state[f"dept_err_{dept}"] = email_err
                                elif not phone_ok:
                                    st.session_state[f"dept_err_{dept}"] = phone_err
                                else:
                                    st.session_state.pop(f"dept_err_{dept}", None)
                                    new_dname = edited_dept_name.strip()
                                    if new_dname != dept:
                                        old_path = os.path.join(CLIENT_CONTRACTS_DIR, dept)
                                        new_path = os.path.join(CLIENT_CONTRACTS_DIR, new_dname)
                                        if os.path.exists(new_path):
                                            st.session_state[f"dept_err_{dept}"] = f"A department named '{new_dname}' already exists."
                                        else:
                                            try:
                                                os.rename(old_path, new_path)
                                                ok, err = dept_db.rename_dept(dept, new_dname)
                                                if not ok:
                                                    os.rename(new_path, old_path)
                                                    st.session_state[f"dept_err_{dept}"] = err
                                                else:
                                                    dept_db.upsert_dept(new_dname, edited_head,
                                                                        edited_email, edited_phone)
                                                    st.session_state["editing_dept_head"] = None
                                                    st.toast(f"Renamed to '{new_dname}' and saved.", icon="✅")
                                                    st.rerun()
                                            except Exception as e:
                                                st.session_state[f"dept_err_{dept}"] = f"Rename failed: {e}"
                                    else:
                                        dept_db.upsert_dept(dept, edited_head,
                                                            edited_email, edited_phone)
                                        st.session_state["editing_dept_head"] = None
                                        st.toast(f"'{dept}' updated.", icon="✅")
                                        st.rerun()

                        # Error shown FULL WIDTH below the row — never inside a narrow column
                        err_key = f"dept_err_{dept}"
                        if st.session_state.get(err_key):
                            st.error(st.session_state[err_key])
                            if st.button("Dismiss", key=f"dismiss_err_{dept}", type="secondary"):
                                st.session_state.pop(err_key, None)
                                st.rerun()
                    else:
                        # ── Read mode — display values ────────────────────────
                        def _cell(val, col):
                            col.markdown(
                                f'<div style="font-size:12px;padding:9px 0;'
                                f'color:var(--color-text-primary);word-break:break-word;">'
                                f'{val if val else "—"}</div>',
                                unsafe_allow_html=True,
                            )

                        _cell(dept,                          tr1)
                        _cell(db_row.get("head_name",  ""), tr2)
                        _cell(db_row.get("head_email", ""), tr3)
                        _cell(db_row.get("head_phone", ""), tr4)

                        updated = db_row.get("updated_at", "")
                        tr5.markdown(
                            f'<div style="font-size:11px;color:var(--color-text-secondary);'
                            f'padding:10px 0;">{updated[:10] if updated else "—"}</div>',
                            unsafe_allow_html=True,
                        )
                        if tr6.button("Edit", key=f"edit_head_{dept}",
                                      use_container_width=True):
                            st.session_state["editing_dept_head"] = dept
                            st.rerun()

                    st.markdown(
                        '<div style="border-top:0.5px solid var(--color-border-tertiary);'
                        'margin:2px 0;"></div>',
                        unsafe_allow_html=True,
                    )

            st.markdown("</div>", unsafe_allow_html=True)

    # ── Build file list based on filters ──────────────────────────────────────
    if selected_filter_dept == "All departments":
        display_files = all_dept_files + flat_files
    else:
        display_files = get_dept_files(selected_filter_dept)

    if search_term:
        display_files = [
            f for f in display_files
            if search_term.lower() in f["name"].lower()
        ]

    if status_filter == "Analyzed":
        display_files = [f for f in display_files if f["name"] in analyzed_names]
    elif status_filter == "Unanalyzed":
        display_files = [f for f in display_files if f["name"] not in analyzed_names]

    st.markdown(
        f'<div style="font-size:12px;color:var(--color-text-secondary);margin:8px 0 6px;">'
        f'Showing <strong>{len(display_files)}</strong> file(s)'
        + (f' in <strong>{selected_filter_dept}</strong>'
           if selected_filter_dept != "All departments"
           else ' across all departments')
        + '</div>',
        unsafe_allow_html=True,
    )

    # ── File table helpers ────────────────────────────────────────────────────
    def _render_file_table_header():
        h1, h2, h3, h4, h5 = st.columns([4, 1, 1.2, 1.5, 2.8])
        for col, label in zip(
            [h1, h2, h3, h4, h5],
            ["File name", "Size", "Uploaded", "Risk status", "Actions"],
        ):
            col.markdown(
                f'<div style="font-size:11px;font-weight:500;'
                f'color:var(--color-text-secondary);text-transform:uppercase;'
                f'letter-spacing:0.5px;padding:5px 0 4px;">{label}</div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            '<div style="border-top:0.5px solid var(--color-border-tertiary);'
            'margin-bottom:2px;"></div>',
            unsafe_allow_html=True,
        )

    def _render_file_row(f: dict, dept_name: str):
        """Renders a file row. A1: uses st.toast() for delete/move messages."""
        risk        = get_file_risk_status(f["name"])
        other_depts = [d for d in depts if d != dept_name]
        if dept_name == "(unorganized)":
            other_depts = depts

        c1, c2, c3, c4, c5 = st.columns([4, 1, 1.2, 1.5, 2.8])

        with c1:
            st.markdown(
                f'<div style="font-size:13px;padding:9px 0 2px;'
                f'word-break:break-word;">{f["name"]}</div>',
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f'<div style="font-size:12px;color:var(--color-text-secondary);'
                f'padding:10px 0;">{f["size_kb"]} KB</div>',
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown(
                f'<div style="font-size:12px;color:var(--color-text-secondary);'
                f'padding:10px 0;">{f["modified"]}</div>',
                unsafe_allow_html=True,
            )
        with c4:
            st.markdown(
                f'<div style="padding:8px 0;">{risk_badge_html(risk)}</div>',
                unsafe_allow_html=True,
            )
        with c5:
            act_move, act_del = st.columns([2, 1])
            with act_move:
                if other_depts:
                    move_to = st.selectbox(
                        "Move",
                        options=["Move to..."] + other_depts,
                        key=f"move_{dept_name}_{f['name']}",
                        label_visibility="collapsed",
                    )
                    if move_to != "Move to...":
                        dest_path = os.path.join(
                            CLIENT_CONTRACTS_DIR, move_to, f["name"]
                        )
                        shutil.move(f["path"], dest_path)
                        # A1: toast — never overflows column
                        st.toast(f"Moved '{f['name']}' to {move_to}.", icon="✅")
                        st.rerun()
                else:
                    st.markdown(
                        '<div style="font-size:11px;color:var(--color-text-secondary);'
                        'padding:9px 0;">—</div>',
                        unsafe_allow_html=True,
                    )
            with act_del:
                if st.button(
                    "Delete",
                    key=f"del_{dept_name}_{f['name']}",
                    type="secondary",
                    use_container_width=True,
                ):
                    fname = f["name"]
                    os.remove(f["path"])
                    # A1: toast — never overflows narrow column
                    st.toast(f"Deleted '{fname}'.", icon="🗑")
                    st.rerun()

        st.markdown(
            '<div style="border-top:0.5px solid var(--color-border-tertiary);'
            'margin:2px 0;"></div>',
            unsafe_allow_html=True,
        )

    # ── Render file table ─────────────────────────────────────────────────────
    if not display_files:
        st.info("No files match the current filters.")
    elif selected_filter_dept != "All departments":
        _render_file_table_header()
        for f in display_files:
            _render_file_row(f, selected_filter_dept)
    else:
        # Group by department — data from SQLite
        all_db_depts_map = {d["name"]: d for d in dept_db.get_all_depts()}
        groups: dict = {}
        for dept in depts:
            groups[dept] = []
        groups["(unorganized)"] = []

        for f in display_files:
            dept_name = f.get("department", "(unorganized)")
            if dept_name not in groups:
                groups[dept_name] = []
            groups[dept_name].append(f)

        for group_dept, group_files in groups.items():
            if not group_files:
                continue

            analyzed_in_group = sum(
                1 for f in group_files if f["name"] in analyzed_names
            )
            label = group_dept if group_dept != "(unorganized)" else "Unorganized files"

            # Build head info line from SQLite — shows name, email, phone
            db_row     = all_db_depts_map.get(group_dept, {})
            head_name  = db_row.get("head_name",  "")
            head_email = db_row.get("head_email", "")
            head_phone = db_row.get("head_phone", "")

            if head_name or head_email or head_phone:
                parts = []
                if head_name:  parts.append(f"<strong>{head_name}</strong>")
                if head_email: parts.append(f'<a href="mailto:{head_email}" style="color:var(--color-text-info);">{head_email}</a>')
                if head_phone: parts.append(head_phone)
                head_info = " &nbsp;·&nbsp; ".join(parts)
                head_line = (
                    f'<div style="font-size:11px;color:var(--color-text-secondary);'
                    f'margin-top:4px;">Head: {head_info}</div>'
                )
            else:
                head_line = (
                    f'<div style="font-size:11px;color:var(--color-text-secondary);'
                    f'font-style:italic;margin-top:4px;">No head assigned</div>'
                )

            st.markdown(
                f'<div style="background:var(--color-background-secondary);'
                f'border-radius:6px;padding:8px 12px;margin:12px 0 6px;">'
                f'<div style="display:flex;align-items:center;gap:10px;">'
                f'<span style="font-size:13px;font-weight:500;">{label}</span>'
                f'<span style="font-size:11px;color:var(--color-text-secondary);">'
                f'{len(group_files)} file(s) · {analyzed_in_group} analyzed</span>'
                f'</div>'
                f'{head_line}'
                f'</div>',
                unsafe_allow_html=True,
            )
            _render_file_table_header()
            for f in group_files:
                _render_file_row(f, group_dept)

    # ── A3: Playbook management — single row per playbook, buttons on right ───
    st.markdown("---")
    st.markdown("#### Company playbooks")

    st.markdown(
        '<div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:12px;">'
        '<strong>Wipe DB</strong> — deletes only the ChromaDB vector database (file stays on disk). '
        'Use when you want to force a fresh rebuild via main app → Rebuild Playbook DB. &nbsp;|&nbsp; '
        '<strong>Delete</strong> — permanently removes the playbook file AND its ChromaDB.'
        '</div>',
        unsafe_allow_html=True,
    )

    if not pb_files:
        st.info("No playbooks found in company_standard/")
    else:
        # Fix 4: Table-style header — Wipe DB and Delete centered above buttons
        pbh1, pbh2, pbh3, pbh4 = st.columns([5, 1.4, 1.4, 0.1])
        for col, label, align in zip(
            [pbh1, pbh2, pbh3],
            ["File name · info", "Wipe DB", "Delete"],
            ["left", "center", "center"],
        ):
            col.markdown(
                f'<div style="font-size:11px;font-weight:500;color:var(--color-text-secondary);'
                f'text-transform:uppercase;letter-spacing:0.5px;padding:5px 0 4px;'
                f'text-align:{align};">'
                f'{label}</div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            '<div style="border-top:0.5px solid var(--color-border-tertiary);'
            'margin-bottom:6px;"></div>',
            unsafe_allow_html=True,
        )

        for pb in pb_files:
            db_status = (
                "✅ ChromaDB built" if pb["db_exists"] else "❌ No ChromaDB"
            )
            built_label = pb["built_at"][:10] if pb["built_at"] != "—" else "—"
            db_color    = (
                "var(--color-text-success)" if pb["db_exists"]
                else "var(--color-text-danger)"
            )

            # A3: info col + 2 button cols on SAME row
            pb1, pb2, pb3, _ = st.columns([5, 1.4, 1.4, 0.1])

            with pb1:
                st.markdown(
                    f'<div style="padding:8px 0;">'
                    f'<div style="font-size:13px;font-weight:500;margin-bottom:3px;">'
                    f'{pb["name"]}</div>'
                    f'<div style="font-size:11px;color:var(--color-text-secondary);">'
                    f'{pb["size_kb"]} KB &nbsp;·&nbsp; '
                    f'<span style="color:{db_color};">{db_status}</span>'
                    f' &nbsp;·&nbsp; built {built_label}'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

            with pb2:
                if pb["db_exists"]:
                    if st.button(
                        "Wipe DB",
                        key=f"wipe_{pb['name']}",
                        use_container_width=True,
                    ):
                        shutil.rmtree(pb["chroma_dir"])
                        st.toast(
                            f"ChromaDB wiped for '{pb['name']}'. "
                            "Rebuild from main app when ready.",
                            icon="🗑",
                        )
                        st.rerun()
                else:
                    st.markdown(
                        '<div style="font-size:11px;color:var(--color-text-secondary);'
                        'padding:10px 0;">No DB</div>',
                        unsafe_allow_html=True,
                    )

            with pb3:
                if st.button(
                    "Delete",
                    key=f"del_pb_{pb['name']}",
                    type="secondary",
                    use_container_width=True,
                ):
                    pbname = pb["name"]
                    os.remove(pb["path"])
                    if pb["db_exists"]:
                        shutil.rmtree(pb["chroma_dir"])
                    st.toast(f"Deleted playbook '{pbname}' and its ChromaDB.", icon="🗑")
                    st.rerun()

            st.markdown(
                '<div style="border-top:0.5px solid var(--color-border-tertiary);'
                'margin:4px 0 8px;"></div>',
                unsafe_allow_html=True,
            )

    # Upload new playbook
    st.markdown("")
    st.caption("Upload a new playbook to company_standard/")
    new_pb = st.file_uploader(
        "Upload new playbook", type=["pdf", "docx"],
        key="upload_new_pb", label_visibility="collapsed",
    )
    if new_pb:
        dest = os.path.join(COMPANY_PLAYBOOK_DIR, new_pb.name)
        if os.path.exists(dest):
            st.warning(f"'{new_pb.name}' already exists.")
        else:
            os.makedirs(COMPANY_PLAYBOOK_DIR, exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(new_pb.getbuffer())
            st.toast(
                f"Uploaded '{new_pb.name}'. Go to main app to rebuild ChromaDB.",
                icon="✅",
            )
            st.rerun()


# ==========================================
# TAB 2: TOKEN USAGE ANALYTICS
# ==========================================
with tab2:

    date_filter = st.selectbox(
        "Date range",
        ["Last 7 days", "Last 30 days", "All time"],
        index=1,
        key="token_date_filter",
    )

    all_token_entries = logger.get_token_log()
    token_entries     = filter_entries_by_date(all_token_entries, date_filter)

    if not token_entries:
        st.info("No token usage data yet. Run the pipeline to start logging.")
    else:
        total_filtered_tokens = sum(e.get("total_tokens", 0) for e in token_entries)
        total_filtered_cost   = sum(e.get("cost_usd",     0) for e in token_entries)
        total_filtered_calls  = len(token_entries)
        avg_duration          = (
            sum(e.get("duration_ms", 0) for e in token_entries)
            // max(len(token_entries), 1)
        )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total tokens",   f"{total_filtered_tokens:,}")
        m2.metric("Estimated cost", f"${total_filtered_cost:.4f}")
        m3.metric("API calls",      total_filtered_calls)
        m4.metric("Avg duration",   f"{avg_duration:,} ms")

        st.markdown("---")
        st.markdown("#### Token usage by tool")

        tool_data: dict = {}
        for e in token_entries:
            tool = e.get("tool_name", "Unknown")
            if tool not in tool_data:
                tool_data[tool] = {"calls": 0, "total_tokens": 0, "cost_usd": 0.0}
            tool_data[tool]["calls"]        += 1
            tool_data[tool]["total_tokens"] += e.get("total_tokens", 0)
            tool_data[tool]["cost_usd"]     += e.get("cost_usd", 0.0)

        if tool_data:
            import pandas as pd
            df_chart = pd.DataFrame(
                {"Tool": list(tool_data.keys()),
                 "Tokens": [v["total_tokens"] for v in tool_data.values()]}
            ).set_index("Tool")
            st.bar_chart(df_chart)

        col_headers = ["Tool", "Calls", "Total tokens", "Input tokens",
                        "Output tokens", "Cost (USD)"]
        tool_rows = []
        for tool, vals in tool_data.items():
            tin  = sum(e.get("input_tokens",  0)
                       for e in token_entries if e.get("tool_name") == tool)
            tout = sum(e.get("output_tokens", 0)
                       for e in token_entries if e.get("tool_name") == tool)
            tool_rows.append([
                tool, vals["calls"],
                f"{vals['total_tokens']:,}", f"{tin:,}", f"{tout:,}",
                f"${vals['cost_usd']:.6f}",
            ])
        if tool_rows:
            st.dataframe(
                pd.DataFrame(tool_rows, columns=col_headers),
                use_container_width=True, hide_index=True,
            )

        st.markdown("---")
        st.markdown("#### Daily token usage")
        daily: dict = {}
        for e in token_entries:
            try:
                day = e["timestamp"][:10]
                daily[day] = daily.get(day, 0) + e.get("total_tokens", 0)
            except Exception:
                pass
        if daily:
            df_daily = pd.DataFrame(
                sorted(daily.items()), columns=["Date", "Tokens"]
            ).set_index("Date")
            st.bar_chart(df_daily)

        st.markdown("---")
        st.markdown("#### Raw token log")
        tool_filter = st.selectbox(
            "Filter by tool",
            ["All tools"] + sorted(set(e.get("tool_name", "") for e in token_entries)),
            key="token_tool_filter",
        )
        display_entries = [
            e for e in reversed(token_entries)
            if tool_filter == "All tools" or e.get("tool_name") == tool_filter
        ]
        rows = []
        for e in display_entries[:100]:
            rows.append({
                "Timestamp":     e.get("timestamp", ""),
                "Tool":          e.get("tool_name", ""),
                "Input tokens":  e.get("input_tokens",  0),
                "Output tokens": e.get("output_tokens", 0),
                "Total tokens":  e.get("total_tokens",  0),
                "Cost (USD)":    f"${e.get('cost_usd', 0):.6f}",
                "Duration (ms)": e.get("duration_ms",  0),
                "Client file":   e.get("client_file",  ""),
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.markdown("")
        if st.button("🗑 Clear token log", type="secondary"):
            logger.clear_token_log()
            st.toast("Token log cleared.", icon="🗑")
            st.rerun()


# ==========================================
# TAB 3: HISTORY LOG
# ==========================================
with tab3:

    history_entries = logger.get_history_log()

    if not history_entries:
        st.info("No analysis history yet. Run the full pipeline to start logging runs.")
    else:
        hist_summary = logger.get_history_summary()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total runs",        hist_summary["total_runs"])
        m2.metric("High risk runs",    hist_summary["high_risk_runs"])
        m3.metric("Avg clauses / run", hist_summary["avg_clauses"])
        m4.metric("Top department",    hist_summary["top_department"])

        st.markdown("---")

        col_s, col_d, col_r = st.columns(3)
        with col_s:
            search_hist = st.text_input(
                "Search", placeholder="Filter by filename...",
                label_visibility="collapsed", key="hist_search",
            )
        with col_d:
            dept_options = ["All departments"] + sorted(set(
                e.get("department", "") or "Unknown" for e in history_entries
            ))
            dept_filter = st.selectbox(
                "Department", dept_options,
                key="hist_dept_filter", label_visibility="collapsed",
            )
        with col_r:
            risk_filter = st.selectbox(
                "Risk level",
                ["All risk levels", "High risk", "Medium risk", "Low risk", "No risk"],
                key="hist_risk_filter", label_visibility="collapsed",
            )

        filtered_hist = list(reversed(history_entries))
        if search_hist:
            filtered_hist = [e for e in filtered_hist
                             if search_hist.lower() in e.get("client_file", "").lower()]
        if dept_filter != "All departments":
            filtered_hist = [e for e in filtered_hist
                             if (e.get("department") or "Unknown") == dept_filter]
        if risk_filter != "All risk levels":
            if risk_filter == "High risk":
                filtered_hist = [e for e in filtered_hist if e.get("high_count", 0) > 0]
            elif risk_filter == "Medium risk":
                filtered_hist = [e for e in filtered_hist
                                 if e.get("medium_count", 0) > 0
                                 and e.get("high_count", 0) == 0]
            elif risk_filter == "Low risk":
                filtered_hist = [e for e in filtered_hist
                                 if e.get("low_count", 0) > 0
                                 and e.get("high_count", 0) == 0
                                 and e.get("medium_count", 0) == 0]
            elif risk_filter == "No risk":
                filtered_hist = [e for e in filtered_hist
                                 if e.get("high_count", 0) == 0
                                 and e.get("medium_count", 0) == 0]

        st.markdown(f"Showing **{len(filtered_hist)}** run(s)")

        for entry in filtered_hist:
            h = entry.get("high_count",   0)
            m = entry.get("medium_count", 0)
            l = entry.get("low_count",    0)

            risk_pills = ""
            if h:
                risk_pills += (
                    f'<span style="background:var(--color-background-danger);'
                    f'color:var(--color-text-danger);padding:2px 8px;'
                    f'border-radius:10px;font-size:11px;margin-right:4px;">{h} High</span>'
                )
            if m:
                risk_pills += (
                    f'<span style="background:var(--color-background-warning);'
                    f'color:var(--color-text-warning);padding:2px 8px;'
                    f'border-radius:10px;font-size:11px;margin-right:4px;">{m} Medium</span>'
                )
            if l:
                risk_pills += (
                    f'<span style="background:var(--color-background-success);'
                    f'color:var(--color-text-success);padding:2px 8px;'
                    f'border-radius:10px;font-size:11px;margin-right:4px;">{l} Low</span>'
                )
            if not (h or m or l):
                risk_pills = (
                    '<span style="background:var(--color-background-secondary);'
                    'color:var(--color-text-secondary);padding:2px 8px;'
                    'border-radius:10px;font-size:11px;">No risk data</span>'
                )

            dept_label = entry.get("department") or "No department"

            with st.expander(
                f"{entry.get('client_file', 'Unknown')}  ·  "
                f"{entry.get('timestamp', '')[:16]}",
                expanded=False,
            ):
                st.markdown(
                    f'<div style="margin-bottom:10px;">{risk_pills}</div>',
                    unsafe_allow_html=True,
                )
                col_a, col_b, col_c = st.columns(3)
                col_a.markdown(f"**Department:** {dept_label}")
                col_b.markdown(f"**Playbook:** {entry.get('playbook_file', '—')}")
                col_c.markdown(f"**Total tokens:** {entry.get('total_tokens', 0):,}")

                clauses = entry.get("clauses_selected", [])
                if clauses:
                    st.markdown(f"**Clauses analyzed:** {', '.join(clauses)}")

                clause_detail = entry.get("clause_detail", [])
                if clause_detail:
                    st.markdown("**Clause-level results:**")
                    for cd in clause_detail:
                        level = cd.get("risk_level", "—")
                        name  = cd.get("clause_name", "—")
                        conf  = cd.get("factual_conflict", "—")
                        color = {
                            "High":   "var(--color-text-danger)",
                            "Medium": "var(--color-text-warning)",
                            "Low":    "var(--color-text-success)",
                        }.get(level, "var(--color-text-secondary)")
                        st.markdown(
                            f'<div style="border-left:3px solid {color};'
                            f'padding:6px 10px;margin:4px 0;'
                            f'background:var(--color-background-secondary);'
                            f'border-radius:0 6px 6px 0;">'
                            f'<strong>{name}</strong> — '
                            f'<span style="color:{color};">{level}</span><br>'
                            f'<span style="font-size:12px;'
                            f'color:var(--color-text-secondary);">{conf}</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                if st.button(
                    "Delete this run",
                    key=f"del_run_{entry.get('run_id', '')}",
                    type="secondary",
                ):
                    logger.delete_history_entry(entry.get("run_id", ""))
                    st.toast("Run deleted.", icon="🗑")
                    st.rerun()

        st.markdown("---")
        st.markdown("**Danger zone**")
        confirm_clear = st.text_input(
            "Type CONFIRM to clear all history",
            placeholder="Type CONFIRM...",
            key="clear_hist_confirm",
            label_visibility="collapsed",
        )
        if st.button("🗑 Clear all history", type="secondary"):
            if confirm_clear == "CONFIRM":
                logger.clear_history_log()
                st.toast("All history cleared.", icon="🗑")
                st.rerun()
            else:
                st.error("Type CONFIRM exactly to clear history.")


# ==========================================
# TAB 4: EXPORT
# ==========================================
with tab4:

    st.markdown("#### Generate admin report")
    st.markdown(
        "Download a PDF or Excel report with full token usage breakdown, "
        "per-file department listing, clause-level risk details, and raw token log."
    )

    export_date = st.selectbox(
        "Date range for report",
        ["Last 7 days", "Last 30 days", "All time"],
        index=2,
        key="export_date",
    )

    col_pdf, col_xlsx = st.columns(2)

    # ── B: PDF color constants ────────────────────────────────────────────────
    DARK_BLUE  = rl_colors.HexColor("#1E2D5E")
    LIGHT_BLUE = rl_colors.HexColor("#E6F1FB")
    ROW_ALT    = rl_colors.HexColor("#f8fafc")
    RED_BG     = rl_colors.HexColor("#fee2e2")
    ORANGE_BG  = rl_colors.HexColor("#fef3c7")
    GREEN_BG   = rl_colors.HexColor("#dcfce7")

    # B1: base table style with WORDWRAP and VALIGN=TOP
    def _tbl_style(extra=None):
        base = [
            ("BACKGROUND",    (0, 0), (-1, 0),  DARK_BLUE),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  rl_colors.white),
            ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0),  9),
            ("FONTSIZE",      (0, 1), (-1, -1), 8),
            # B1: word wrap + top align so cells expand with content
            ("WORDWRAP",      (0, 0), (-1, -1), True),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [rl_colors.white, ROW_ALT]),
            ("GRID",          (0, 0), (-1, -1), 0.4, rl_colors.lightgrey),
            # B3: padding so wrapped text has breathing room
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ]
        if extra:
            base.extend(extra)
        return TableStyle(base)

    # ── PDF EXPORT ────────────────────────────────────────────────────────────
    with col_pdf:
        st.markdown("**PDF report**")
        st.caption(
            "Full report: overview metrics, per-tool token breakdown, "
            "department file listing, clause-level history, and raw token log. "
            "All tables use word-wrap — no text is cut off."
        )

        if st.button("Generate PDF", use_container_width=True):
            with st.spinner("Building PDF..."):
                try:
                    token_data   = filter_entries_by_date(logger.get_token_log(),   export_date)
                    history_data = filter_entries_by_date(logger.get_history_log(), export_date)

                    buffer = BytesIO()
                    # B2: full usable width = 540pt for LETTER with 36pt margins each side
                    doc = SimpleDocTemplate(
                        buffer, pagesize=LETTER,
                        rightMargin=36, leftMargin=36,
                        topMargin=44, bottomMargin=36,
                    )
                    PAGE_W = 540  # usable width in points

                    styles   = getSampleStyleSheet()
                    h1_style = styles["Title"]
                    h2_style = styles["Heading2"]
                    h3_style = styles["Heading3"]
                    n_style  = styles["Normal"]
                    sm_style = ParagraphStyle("sm", parent=n_style, fontSize=8, leading=11)
                    # B1: wrap style for cell content that may be long
                    cell_style = ParagraphStyle(
                        "cell", parent=n_style, fontSize=8, leading=11,
                        wordWrap="LTR",
                    )
                    elements = []

                    # ── Cover ─────────────────────────────────────────────────
                    elements.append(Paragraph("Admin Report — Legal Contract Analyzer", h1_style))
                    elements.append(Paragraph(
                        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ·  "
                        f"Period: {export_date}  ·  "
                        f"Departments: {len(get_departments())}",
                        sm_style,
                    ))
                    elements.append(Spacer(1, 12))
                    elements.append(HRFlowable(width="100%", thickness=2, color=DARK_BLUE))
                    elements.append(Spacer(1, 16))

                    # ── Section 1: Overview metrics ───────────────────────────
                    elements.append(Paragraph("1. Overview Metrics", h2_style))
                    elements.append(Spacer(1, 6))
                    all_files_pdf = get_all_client_files()
                    total_t    = sum(e.get("total_tokens", 0) for e in token_data)
                    total_cost = sum(e.get("cost_usd",     0) for e in token_data)
                    total_runs = len(history_data)
                    high_runs  = sum(1 for e in history_data if e.get("high_count", 0) > 0)

                    # B2: col widths sum to PAGE_W
                    ov_data = [
                        ["Metric", "Value"],
                        ["Total API calls",        str(len(token_data))],
                        ["Total tokens used",       f"{total_t:,}"],
                        ["Estimated cost (USD)",    f"${total_cost:.6f}"],
                        ["Pipeline runs completed", str(total_runs)],
                        ["Runs with HIGH risk",     str(high_runs)],
                        ["Departments",             str(len(get_departments()))],
                        ["Total client contracts",  str(len(all_files_pdf))],
                    ]
                    ov_tbl = Table(ov_data, colWidths=[300, 240])
                    ov_tbl.setStyle(_tbl_style())
                    elements.append(ov_tbl)
                    elements.append(Spacer(1, 18))
                    elements.append(HRFlowable(width="100%", thickness=0.5, color=rl_colors.lightgrey))
                    elements.append(Spacer(1, 14))

                    # ── Section 2: Token usage by tool ────────────────────────
                    elements.append(Paragraph("2. Token Usage by Tool", h2_style))
                    elements.append(Spacer(1, 6))
                    tool_sum: dict = {}
                    for e in token_data:
                        t = e.get("tool_name", "Unknown")
                        if t not in tool_sum:
                            tool_sum[t] = {"calls": 0, "input": 0, "output": 0,
                                           "total": 0, "cost": 0.0, "dur": 0}
                        tool_sum[t]["calls"]  += 1
                        tool_sum[t]["input"]  += e.get("input_tokens",  0)
                        tool_sum[t]["output"] += e.get("output_tokens", 0)
                        tool_sum[t]["total"]  += e.get("total_tokens",  0)
                        tool_sum[t]["cost"]   += e.get("cost_usd",      0.0)
                        tool_sum[t]["dur"]    += e.get("duration_ms",   0)

                    if tool_sum:
                        # B2: 7 cols, widths sum to 540
                        td = [["Tool", "Calls", "Input", "Output", "Total", "Cost (USD)", "Avg ms"]]
                        for tool, v in tool_sum.items():
                            avg_dur = v["dur"] // max(v["calls"], 1)
                            td.append([tool, str(v["calls"]),
                                       f"{v['input']:,}", f"{v['output']:,}",
                                       f"{v['total']:,}", f"${v['cost']:.6f}", f"{avg_dur:,}"])
                        td.append([
                            "TOTAL", str(len(token_data)),
                            f"{sum(v['input']  for v in tool_sum.values()):,}",
                            f"{sum(v['output'] for v in tool_sum.values()):,}",
                            f"{total_t:,}", f"${total_cost:.6f}", "—",
                        ])
                        tool_tbl = Table(td, colWidths=[130, 38, 72, 72, 72, 86, 70])
                        tool_tbl.setStyle(_tbl_style([
                            ("FONTNAME",   (0, -1), (-1, -1), "Helvetica-Bold"),
                            ("BACKGROUND", (0, -1), (-1, -1), LIGHT_BLUE),
                        ]))
                        elements.append(tool_tbl)
                    else:
                        elements.append(Paragraph("No token data in selected period.", n_style))

                    elements.append(Spacer(1, 18))
                    elements.append(HRFlowable(width="100%", thickness=0.5, color=rl_colors.lightgrey))
                    elements.append(Spacer(1, 14))

                    # ── Section 3: Department & file listing ──────────────────
                    elements.append(Paragraph("3. Department & File Listing", h2_style))
                    elements.append(Spacer(1, 6))
                    all_analyzed_pdf = {e.get("client_file") for e in logger.get_history_log()}

                    for dept in get_departments():
                        head = (dept_db.get_dept(dept) or {}).get('head_name', '')
                        head_info = f" · Head: {head}" if head else ""
                        elements.append(Paragraph(f"Department: {dept}{head_info}", h3_style))
                        dfiles = get_dept_files(dept)
                        if not dfiles:
                            elements.append(Paragraph("  No files.", sm_style))
                        else:
                            # B2: 4 cols summing to 540
                            df_data = [["File Name", "Size (KB)", "Modified", "Risk Status"]]
                            for f in dfiles:
                                risk = get_file_risk_status(f["name"])
                                # B1: Use Paragraph for long cell content so it wraps
                                df_data.append([
                                    Paragraph(f["name"], cell_style),
                                    str(f["size_kb"]),
                                    f["modified"],
                                    risk,
                                ])
                            df_tbl = Table(df_data, colWidths=[250, 60, 90, 140])
                            extra_styles = []
                            for ri, row in enumerate(df_data[1:], start=1):
                                r_status = row[3]
                                if r_status == "High risk":
                                    extra_styles.append(("BACKGROUND", (3, ri), (3, ri), RED_BG))
                                elif r_status == "Medium risk":
                                    extra_styles.append(("BACKGROUND", (3, ri), (3, ri), ORANGE_BG))
                                elif r_status in ("Low risk", "Analyzed"):
                                    extra_styles.append(("BACKGROUND", (3, ri), (3, ri), GREEN_BG))
                            df_tbl.setStyle(_tbl_style(extra_styles))
                            elements.append(df_tbl)
                        elements.append(Spacer(1, 10))

                    flat = get_flat_client_files()
                    if flat:
                        elements.append(Paragraph("Unorganized files", h3_style))
                        fl_data = [["File Name", "Size (KB)", "Modified", "Risk Status"]]
                        for f in flat:
                            fl_data.append([
                                Paragraph(f["name"], cell_style),
                                str(f["size_kb"]),
                                f["modified"],
                                get_file_risk_status(f["name"]),
                            ])
                        fl_tbl = Table(fl_data, colWidths=[250, 60, 90, 140])
                        fl_tbl.setStyle(_tbl_style())
                        elements.append(fl_tbl)

                    elements.append(Spacer(1, 18))
                    elements.append(HRFlowable(width="100%", thickness=0.5, color=rl_colors.lightgrey))
                    elements.append(Spacer(1, 14))

                    # ── Section 4: Analysis history ───────────────────────────
                    elements.append(Paragraph("4. Analysis History", h2_style))
                    elements.append(Spacer(1, 6))
                    if not history_data:
                        elements.append(Paragraph("No history in selected period.", n_style))
                    else:
                        for entry in reversed(history_data):
                            h_c = entry.get("high_count",   0)
                            m_c = entry.get("medium_count", 0)
                            l_c = entry.get("low_count",    0)
                            dept_h = (dept_db.get_dept(entry.get("department") or "") or {}).get("head_name", "")
                            dept_display = entry.get("department") or "—"
                            if dept_h:
                                dept_display += f" (Head: {dept_h})"
                            elements.append(Paragraph(
                                f"<b>{entry.get('client_file', '—')}</b>  "
                                f"<font color='grey'>{entry.get('timestamp', '')[:16]}</font>  "
                                f"| Dept: {dept_display}  "
                                f"| Tokens: {entry.get('total_tokens', 0):,}",
                                ParagraphStyle("run_hdr", parent=n_style,
                                               fontSize=8, fontName="Helvetica-Bold"),
                            ))
                            elements.append(Spacer(1, 4))

                            # Risk summary
                            rs_data = [["Clauses", "High", "Medium", "Low"]]
                            rs_data.append([str(entry.get("clause_count", 0)),
                                            str(h_c), str(m_c), str(l_c)])
                            rs_extra = []
                            if h_c > 0: rs_extra.append(("BACKGROUND", (1, 1), (1, 1), RED_BG))
                            if m_c > 0: rs_extra.append(("BACKGROUND", (2, 1), (2, 1), ORANGE_BG))
                            if l_c > 0: rs_extra.append(("BACKGROUND", (3, 1), (3, 1), GREEN_BG))
                            # B2: 4 cols summing to 540
                            rs_tbl = Table(rs_data, colWidths=[135, 135, 135, 135])
                            rs_tbl.setStyle(_tbl_style(rs_extra))
                            elements.append(rs_tbl)
                            elements.append(Spacer(1, 4))

                            # B1+B2: Clause detail — Factual Conflict gets most width
                            clause_detail = entry.get("clause_detail", [])
                            if clause_detail:
                                # colWidths: ClauseName=160, Risk=60, FactualConflict=320
                                cd_data = [["Clause Name", "Risk", "Factual Conflict"]]
                                for cd in clause_detail:
                                    level = cd.get("risk_level", "—")
                                    cd_data.append([
                                        # B1: Paragraph wraps long clause names
                                        Paragraph(cd.get("clause_name", "—"), cell_style),
                                        level,
                                        # B1: Paragraph wraps long conflict text — no more cut-off
                                        Paragraph(cd.get("factual_conflict", "—"), cell_style),
                                    ])
                                cd_extra = []
                                for ri, row in enumerate(cd_data[1:], start=1):
                                    lvl = row[1]
                                    if lvl == "High":
                                        cd_extra.append(("BACKGROUND", (1, ri), (1, ri), RED_BG))
                                    elif lvl == "Medium":
                                        cd_extra.append(("BACKGROUND", (1, ri), (1, ri), ORANGE_BG))
                                    elif lvl == "Low":
                                        cd_extra.append(("BACKGROUND", (1, ri), (1, ri), GREEN_BG))
                                # B2: 160 + 60 + 320 = 540
                                cd_tbl = Table(cd_data, colWidths=[160, 60, 320])
                                cd_tbl.setStyle(_tbl_style(cd_extra))
                                elements.append(cd_tbl)

                            elements.append(Spacer(1, 12))

                    elements.append(HRFlowable(width="100%", thickness=0.5, color=rl_colors.lightgrey))
                    elements.append(Spacer(1, 14))

                    # ── Section 5: Raw token log ───────────────────────────────
                    elements.append(Paragraph("5. Raw Token Log", h2_style))
                    elements.append(Spacer(1, 6))
                    if not token_data:
                        elements.append(Paragraph("No token log data.", n_style))
                    else:
                        # B4: truncate client file to 28 chars to prevent overflow
                        # B2: 6 cols summing to 540
                        rl_data = [["Timestamp", "Tool", "In", "Out", "Total", "Cost", "ms", "Client file"]]
                        for e in reversed(token_data):
                            cf = e.get("client_file", "")
                            cf_short = (cf[:28] + "…") if len(cf) > 28 else cf
                            rl_data.append([
                                e.get("timestamp", "")[:16],
                                e.get("tool_name", "")[:20],
                                str(e.get("input_tokens",  0)),
                                str(e.get("output_tokens", 0)),
                                str(e.get("total_tokens",  0)),
                                f"${e.get('cost_usd', 0):.6f}",
                                str(e.get("duration_ms",   0)),
                                cf_short,
                            ])
                        # B2: 8 cols — 100+105+35+40+45+72+40+103 = 540
                        rl_tbl = Table(rl_data, colWidths=[100, 105, 35, 40, 45, 72, 40, 103])
                        rl_tbl.setStyle(_tbl_style())
                        elements.append(rl_tbl)

                    doc.build(elements)
                    buffer.seek(0)

                    st.download_button(
                        label="⬇ Download PDF",
                        data=buffer,
                        file_name=f"Admin_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        type="primary",
                    )
                except Exception as ex:
                    st.error(f"PDF generation failed: {ex}")

    # ── EXCEL EXPORT ──────────────────────────────────────────────────────────
    with col_xlsx:
        st.markdown("**Excel report**")
        st.caption(
            "5 sheets: overview metrics, token breakdown by tool, "
            "department file listing, full analysis history with clause details, "
            "and raw token log."
        )

        if st.button("Generate Excel", use_container_width=True):
            with st.spinner("Building Excel..."):
                try:
                    token_data   = filter_entries_by_date(logger.get_token_log(),   export_date)
                    history_data = filter_entries_by_date(logger.get_history_log(), export_date)

                    wb = openpyxl.Workbook()

                    hdr_font    = Font(bold=True, color="FFFFFF")
                    hdr_fill    = PatternFill("solid", fgColor="1E2D5E")
                    total_fill  = PatternFill("solid", fgColor="DBEAFE")
                    red_fill    = PatternFill("solid", fgColor="FEE2E2")
                    orange_fill = PatternFill("solid", fgColor="FEF3C7")
                    green_fill  = PatternFill("solid", fgColor="DCFCE7")
                    grey_fill   = PatternFill("solid", fgColor="F1F5F9")
                    center_al   = Alignment(horizontal="center", vertical="center")
                    wrap_al     = Alignment(horizontal="left", vertical="top", wrap_text=True)
                    thin_bd     = Border(
                        left=Side(style="thin"),  right=Side(style="thin"),
                        top=Side(style="thin"),   bottom=Side(style="thin"),
                    )

                    def style_hdr(ws, row=1):
                        for cell in ws[row]:
                            cell.font      = hdr_font
                            cell.fill      = hdr_fill
                            cell.alignment = center_al
                            cell.border    = thin_bd
                        ws.row_dimensions[row].height = 20

                    def auto_w(ws, max_w=55):
                        for col in ws.columns:
                            mx = max((len(str(c.value or "")) for c in col), default=8)
                            ws.column_dimensions[
                                get_column_letter(col[0].column)
                            ].width = min(mx + 3, max_w)

                    def add_border(ws):
                        for row in ws.iter_rows():
                            for cell in row:
                                if cell.value is not None:
                                    cell.border = thin_bd

                    all_analyzed_xl = {e.get("client_file") for e in logger.get_history_log()}
                    all_files_xl    = get_all_client_files()
                    dept_meta_xl    = {d["name"]: d for d in dept_db.get_all_depts()}

                    # Sheet 1: Overview
                    ws1       = wb.active
                    ws1.title = "Overview"
                    total_t_xl    = sum(e.get("total_tokens", 0) for e in token_data)
                    total_cost_xl = sum(e.get("cost_usd",     0) for e in token_data)
                    ws1.append(["Metric", "Value"])
                    style_hdr(ws1)
                    for label, val in [
                        ("Report period",            export_date),
                        ("Generated at",             datetime.now().strftime("%Y-%m-%d %H:%M")),
                        ("Total API calls",           len(token_data)),
                        ("Total tokens used",         total_t_xl),
                        ("Estimated cost (USD)",      f"${total_cost_xl:.6f}"),
                        ("Pipeline runs completed",   len(history_data)),
                        ("Runs with HIGH risk",       sum(1 for e in history_data
                                                         if e.get("high_count", 0) > 0)),
                        ("Total departments",         len(get_departments())),
                        ("Total client contracts",    len(all_files_xl)),
                        ("Total playbooks",           len(get_playbook_files())),
                    ]:
                        ws1.append([label, val])
                    auto_w(ws1)
                    add_border(ws1)

                    # Sheet 2: Token breakdown
                    ws2       = wb.create_sheet("Token Breakdown")
                    ws2.append(["Tool", "Calls", "Input", "Output", "Total",
                                 "Cost (USD)", "Avg Duration (ms)"])
                    style_hdr(ws2)
                    tool_xl: dict = {}
                    for e in token_data:
                        t = e.get("tool_name", "Unknown")
                        if t not in tool_xl:
                            tool_xl[t] = {"calls": 0, "inp": 0, "out": 0,
                                          "tot": 0, "cost": 0.0, "dur": 0}
                        tool_xl[t]["calls"] += 1
                        tool_xl[t]["inp"]   += e.get("input_tokens",  0)
                        tool_xl[t]["out"]   += e.get("output_tokens", 0)
                        tool_xl[t]["tot"]   += e.get("total_tokens",  0)
                        tool_xl[t]["cost"]  += e.get("cost_usd",      0.0)
                        tool_xl[t]["dur"]   += e.get("duration_ms",   0)
                    for tool, v in tool_xl.items():
                        avg_d = v["dur"] // max(v["calls"], 1)
                        ws2.append([tool, v["calls"], v["inp"], v["out"],
                                    v["tot"], round(v["cost"], 6), avg_d])
                    ws2.append([
                        "TOTAL",
                        sum(v["calls"] for v in tool_xl.values()),
                        sum(v["inp"]   for v in tool_xl.values()),
                        sum(v["out"]   for v in tool_xl.values()),
                        total_t_xl, round(total_cost_xl, 6), "—",
                    ])
                    for cell in ws2[ws2.max_row]:
                        cell.fill = total_fill
                        cell.font = Font(bold=True)
                    auto_w(ws2)
                    add_border(ws2)

                    # Sheet 3: Department files — includes head name
                    ws3       = wb.create_sheet("Department Files")
                    ws3.append(["Department", "Head", "File Name", "Size (KB)",
                                 "Last Modified", "Risk Status", "Analyzed"])
                    style_hdr(ws3)
                    for dept in get_departments():
                        head  = dept_meta_xl.get(dept, {}).get("head", "")
                        dfiles = get_dept_files(dept)
                        if not dfiles:
                            ws3.append([dept, head, "(no files)", "", "", "", ""])
                            ws3.cell(ws3.max_row, 1).fill = grey_fill
                        else:
                            for f in dfiles:
                                risk     = get_file_risk_status(f["name"])
                                analyzed = "Yes" if f["name"] in all_analyzed_xl else "No"
                                ws3.append([dept, head, f["name"], f["size_kb"],
                                             f["modified"], risk, analyzed])
                                lr = ws3.max_row
                                if risk == "High risk":
                                    ws3.cell(lr, 6).fill = red_fill
                                elif risk == "Medium risk":
                                    ws3.cell(lr, 6).fill = orange_fill
                                elif risk in ("Low risk", "Analyzed"):
                                    ws3.cell(lr, 6).fill = green_fill
                    for f in get_flat_client_files():
                        risk     = get_file_risk_status(f["name"])
                        analyzed = "Yes" if f["name"] in all_analyzed_xl else "No"
                        ws3.append(["(unorganized)", "", f["name"], f["size_kb"],
                                     f["modified"], risk, analyzed])
                    auto_w(ws3)
                    add_border(ws3)

                    # Sheet 4: Analysis history
                    ws4       = wb.create_sheet("Analysis History")
                    ws4.append(["Timestamp", "Client File", "Department", "Dept Head",
                                 "Playbook", "Clause Count", "High", "Medium", "Low",
                                 "Total Tokens", "Clause Name", "Risk Level",
                                 "Factual Conflict"])
                    style_hdr(ws4)
                    for e in reversed(history_data):
                        h_v  = e.get("high_count",   0)
                        m_v  = e.get("medium_count", 0)
                        l_v  = e.get("low_count",    0)
                        dept = e.get("department", "") or "—"
                        head = dept_meta_xl.get(dept, {}).get("head", "") if dept != "—" else ""
                        clause_detail = e.get("clause_detail", [])
                        if clause_detail:
                            for cd in clause_detail:
                                ws4.append([
                                    e.get("timestamp",    ""),
                                    e.get("client_file",  ""),
                                    dept, head,
                                    e.get("playbook_file",""),
                                    e.get("clause_count", 0),
                                    h_v, m_v, l_v,
                                    e.get("total_tokens", 0),
                                    cd.get("clause_name",      ""),
                                    cd.get("risk_level",       ""),
                                    cd.get("factual_conflict", ""),
                                ])
                                lr  = ws4.max_row
                                lvl = cd.get("risk_level", "")
                                row_fill = (
                                    red_fill    if h_v > 0 and lvl == "High"   else
                                    orange_fill if m_v > 0 and lvl == "Medium" else
                                    green_fill  if lvl == "Low" else None
                                )
                                if row_fill:
                                    for col in range(11, 14):
                                        ws4.cell(lr, col).fill = row_fill
                                if h_v > 0: ws4.cell(lr, 7).fill = red_fill
                                if m_v > 0: ws4.cell(lr, 8).fill = orange_fill
                                if l_v > 0: ws4.cell(lr, 9).fill = green_fill
                                # enable wrap for Factual Conflict column
                                ws4.cell(lr, 13).alignment = wrap_al
                        else:
                            ws4.append([
                                e.get("timestamp",    ""),
                                e.get("client_file",  ""),
                                dept, head,
                                e.get("playbook_file",""),
                                e.get("clause_count", 0),
                                h_v, m_v, l_v,
                                e.get("total_tokens", 0),
                                "—", "—", "—",
                            ])
                    auto_w(ws4)
                    add_border(ws4)

                    # Sheet 5: Raw token log
                    ws5       = wb.create_sheet("Token Log")
                    ws5.append(["Timestamp", "Tool", "Input Tokens", "Output Tokens",
                                 "Total Tokens", "Cost (USD)", "Duration (ms)",
                                 "Client File", "Playbook", "Department"])
                    style_hdr(ws5)
                    for e in reversed(token_data):
                        ws5.append([
                            e.get("timestamp",     ""),
                            e.get("tool_name",     ""),
                            e.get("input_tokens",  0),
                            e.get("output_tokens", 0),
                            e.get("total_tokens",  0),
                            round(e.get("cost_usd", 0.0), 6),
                            e.get("duration_ms",   0),
                            e.get("client_file",   ""),
                            e.get("playbook_file", ""),
                            e.get("department",    ""),
                        ])
                    auto_w(ws5)
                    add_border(ws5)

                    xlsx_buf = BytesIO()
                    wb.save(xlsx_buf)
                    xlsx_buf.seek(0)

                    st.download_button(
                        label="⬇ Download Excel",
                        data=xlsx_buf,
                        file_name=f"Admin_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        type="primary",
                    )
                except Exception as ex:
                    st.error(f"Excel generation failed: {ex}")
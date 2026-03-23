"""
================================================================================
logger.py -- Append-Only Event Logger
================================================================================
Purpose : Logs two types of events to JSON files:
          1. token_log.json   -- every LLM API call (tokens, cost, duration)
          2. history_log.json -- every completed pipeline run (risk summary)

Design  : Pure append-only writes. Never reads during normal app operation.
          All functions are wrapped in try/except so a logging failure
          CANNOT crash or interrupt the main pipeline in app.py.

Usage in app.py:
    import logger
    logger.log_token_event(tool_name="Tool 1", ...)
    logger.log_run(client_file="ACME.docx", ...)

Files created automatically on first write (no manual setup needed):
    token_log.json
    history_log.json
================================================================================
"""

import json
import os
from datetime import datetime

# ==========================================
# SECTION 1: PATHS
# ==========================================

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
TOKEN_LOG_PATH   = os.path.join(BASE_DIR, "token_log.json")
HISTORY_LOG_PATH = os.path.join(BASE_DIR, "history_log.json")


# ==========================================
# SECTION 2: GEMINI PRICING CONSTANTS
# Gemini 2.5 Flash pricing (USD per 1M tokens)
# Update these if Google changes pricing.
# ==========================================

PRICE_INPUT_PER_1M  = 0.075   # $0.075 per 1M input tokens
PRICE_OUTPUT_PER_1M = 0.30    # $0.30  per 1M output tokens


# ==========================================
# SECTION 3: INTERNAL HELPERS
# ==========================================

def _load_log(path: str) -> list:
    """
    Loads a JSON log file and returns its contents as a list.
    Returns an empty list if the file does not exist or is corrupt.
    Never raises an exception.
    """
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def _save_log(path: str, entries: list) -> None:
    """
    Writes the full list back to the JSON log file.
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """
    Estimates USD cost for a single API call using Gemini 2.5 Flash pricing.

    Returns:
        float: Estimated cost in USD, rounded to 6 decimal places.
    """
    cost = (
        (input_tokens  / 1_000_000) * PRICE_INPUT_PER_1M +
        (output_tokens / 1_000_000) * PRICE_OUTPUT_PER_1M
    )
    return round(cost, 6)


# ==========================================
# SECTION 4: TOKEN EVENT LOGGER
# ==========================================

def log_token_event(
    tool_name:     str,
    input_tokens:  int,
    output_tokens: int,
    duration_ms:   int = 0,
    client_file:   str = "",
    playbook_file: str = "",
    model:         str = "gemini-2.5-flash",
    department:    str = "",
) -> None:
    """
    Logs a single LLM API call to token_log.json.

    Called once per tool invocation inside app.py:
        - Discovery Scan
        - Tool 1: extract_contract_terms
        - Tool 2: query_playbook
        - Tool 3: generate_risk_report
        - Chatbot: _get_bot_response

    Args:
        tool_name     (str): Human-readable name e.g. "Tool 1", "Discovery Scan".
        input_tokens  (int): Input token count from the LLM response metadata.
        output_tokens (int): Output token count from the LLM response metadata.
        duration_ms   (int): Wall-clock duration of the API call in milliseconds.
        client_file   (str): Basename of the client contract being analyzed.
        playbook_file (str): Basename of the active company playbook.
        model         (str): Model string used for this call.
        department    (str): Department the client file belongs to (if any).

    Returns:
        None. Silently swallows all exceptions to protect the main pipeline.
    """
    try:
        entry = {
            "timestamp":     datetime.now().isoformat(timespec="seconds"),
            "tool_name":     tool_name,
            "model":         model,
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "total_tokens":  input_tokens + output_tokens,
            "cost_usd":      _estimate_cost(input_tokens, output_tokens),
            "duration_ms":   duration_ms,
            "client_file":   client_file,
            "playbook_file": playbook_file,
            "department":    department,
        }
        entries = _load_log(TOKEN_LOG_PATH)
        entries.append(entry)
        _save_log(TOKEN_LOG_PATH, entries)
    except Exception:
        pass  # Never crash the main pipeline over a logging failure


# ==========================================
# SECTION 5: PIPELINE RUN LOGGER
# ==========================================

def log_run(
    client_file:   str,
    playbook_file: str,
    department:    str,
    clauses:       list,
    risk_report,
    total_tokens:  int = 0,
) -> None:
    """
    Logs a completed full pipeline run to history_log.json.

    Called once in app.py Section 15 after Tool 3 completes and
    st.session_state.final_report is set.

    Args:
        client_file   (str):             Basename of the analyzed client contract.
        playbook_file (str):             Basename of the playbook used.
        department    (str):             Department the client file belongs to.
        clauses       (list[str]):       List of clause names that were analyzed.
        risk_report   (FinalRiskReport): Pydantic model from Tool 3 output.
        total_tokens  (int):             Total tokens used across the full run.

    Returns:
        None. Silently swallows all exceptions to protect the main pipeline.
    """
    try:
        analyses = risk_report.analyses if risk_report else []

        high_count   = sum(1 for a in analyses if a.risk_level.lower() == "high")
        medium_count = sum(1 for a in analyses if a.risk_level.lower() == "medium")
        low_count    = sum(1 for a in analyses if a.risk_level.lower() == "low")

        # Per-clause snapshot stored for expandable history view in admin
        clause_snapshots = [
            {
                "clause_name":      a.clause_name,
                "risk_level":       a.risk_level,
                "conflict_found":   a.conflict_found,
                "factual_conflict": a.factual_conflict,
            }
            for a in analyses
        ]

        entry = {
            "run_id":           datetime.now().strftime("%Y%m%d%H%M%S"),
            "timestamp":        datetime.now().isoformat(timespec="seconds"),
            "client_file":      client_file,
            "playbook_file":    playbook_file,
            "department":       department,
            "clauses_selected": clauses,
            "clause_count":     len(clauses),
            "high_count":       high_count,
            "medium_count":     medium_count,
            "low_count":        low_count,
            "total_tokens":     total_tokens,
            "clause_detail":    clause_snapshots,
        }

        entries = _load_log(HISTORY_LOG_PATH)
        entries.append(entry)
        _save_log(HISTORY_LOG_PATH, entries)
    except Exception:
        pass  # Never crash the main pipeline over a logging failure


# ==========================================
# SECTION 6: ADMIN UTILITY FUNCTIONS
# Called only by pages/admin.py, never by app.py
# ==========================================

def get_token_log() -> list:
    """Returns all token log entries as a list of dicts."""
    return _load_log(TOKEN_LOG_PATH)


def get_history_log() -> list:
    """Returns all history log entries as a list of dicts."""
    return _load_log(HISTORY_LOG_PATH)


def clear_token_log() -> None:
    """Wipes token_log.json. Called only from admin page."""
    try:
        _save_log(TOKEN_LOG_PATH, [])
    except Exception:
        pass


def clear_history_log() -> None:
    """Wipes history_log.json. Called only from admin page."""
    try:
        _save_log(HISTORY_LOG_PATH, [])
    except Exception:
        pass


def delete_history_entry(run_id: str) -> None:
    """
    Deletes a single history entry by its run_id.
    Called from the admin history tab when user deletes one run.

    Args:
        run_id (str): The run_id string (format: YYYYMMDDHHMMSS).
    """
    try:
        entries = _load_log(HISTORY_LOG_PATH)
        entries = [e for e in entries if e.get("run_id") != run_id]
        _save_log(HISTORY_LOG_PATH, entries)
    except Exception:
        pass


def get_token_summary() -> dict:
    """
    Returns aggregated token stats for the admin dashboard metrics row.

    Returns:
        dict with keys:
            total_calls      (int)
            total_tokens     (int)
            total_input      (int)
            total_output     (int)
            total_cost_usd   (float)
            by_tool          (dict[str, dict]) -- per-tool breakdown
    """
    entries = _load_log(TOKEN_LOG_PATH)
    if not entries:
        return {
            "total_calls":    0,
            "total_tokens":   0,
            "total_input":    0,
            "total_output":   0,
            "total_cost_usd": 0.0,
            "by_tool":        {},
        }

    total_input  = sum(e.get("input_tokens",  0) for e in entries)
    total_output = sum(e.get("output_tokens", 0) for e in entries)
    total_cost   = sum(e.get("cost_usd",      0) for e in entries)

    by_tool: dict = {}
    for e in entries:
        tool = e.get("tool_name", "Unknown")
        if tool not in by_tool:
            by_tool[tool] = {
                "calls":         0,
                "input_tokens":  0,
                "output_tokens": 0,
                "total_tokens":  0,
                "cost_usd":      0.0,
            }
        by_tool[tool]["calls"]         += 1
        by_tool[tool]["input_tokens"]  += e.get("input_tokens",  0)
        by_tool[tool]["output_tokens"] += e.get("output_tokens", 0)
        by_tool[tool]["total_tokens"]  += e.get("total_tokens",  0)
        by_tool[tool]["cost_usd"]      += e.get("cost_usd",      0.0)

    return {
        "total_calls":    len(entries),
        "total_tokens":   total_input + total_output,
        "total_input":    total_input,
        "total_output":   total_output,
        "total_cost_usd": round(total_cost, 6),
        "by_tool":        by_tool,
    }


def get_history_summary() -> dict:
    """
    Returns aggregated run stats for the admin history metrics row.

    Returns:
        dict with keys:
            total_runs         (int)
            high_risk_runs     (int)
            avg_clauses        (float)
            top_department     (str)
    """
    entries = _load_log(HISTORY_LOG_PATH)
    if not entries:
        return {
            "total_runs":     0,
            "high_risk_runs": 0,
            "avg_clauses":    0.0,
            "top_department": "—",
        }

    high_risk_runs = sum(1 for e in entries if e.get("high_count", 0) > 0)
    avg_clauses    = sum(e.get("clause_count", 0) for e in entries) / len(entries)

    dept_counts: dict = {}
    for e in entries:
        dept = e.get("department", "Unknown") or "Unknown"
        dept_counts[dept] = dept_counts.get(dept, 0) + 1
    top_dept = max(dept_counts, key=dept_counts.get) if dept_counts else "—"

    return {
        "total_runs":     len(entries),
        "high_risk_runs": high_risk_runs,
        "avg_clauses":    round(avg_clauses, 1),
        "top_department": top_dept,
    }


# ==========================================
# SECTION 7: QUICK SELF-TEST
# Run:  python logger.py   to verify it works
# ==========================================

if __name__ == "__main__":
    print("[TEST] Writing a test token event...")
    log_token_event(
        tool_name="Test Tool",
        input_tokens=1500,
        output_tokens=300,
        duration_ms=1200,
        client_file="test_contract.docx",
        playbook_file="test_playbook.docx",
        department="Engineering",
    )
    print(f"[TEST] token_log.json written at: {TOKEN_LOG_PATH}")

    print("[TEST] Writing a test run entry...")

    class _FakeAnalysis:
        clause_name      = "Payment Terms"
        risk_level       = "High"
        conflict_found   = True
        factual_conflict = "Client states Net 90; standard requires Net 30."

    class _FakeReport:
        analyses = [_FakeAnalysis()]

    log_run(
        client_file="test_contract.docx",
        playbook_file="test_playbook.docx",
        department="Engineering",
        clauses=["Payment Terms"],
        risk_report=_FakeReport(),
        total_tokens=1800,
    )
    print(f"[TEST] history_log.json written at: {HISTORY_LOG_PATH}")

    summary = get_token_summary()
    print(f"[TEST] Token summary: {summary}")

    hist = get_history_summary()
    print(f"[TEST] History summary: {hist}")

    print("\n[TEST] All tests passed. logger.py is working correctly.")
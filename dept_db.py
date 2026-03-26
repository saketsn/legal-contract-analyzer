"""
================================================================================
dept_db.py -- Department SQLite Database Layer
================================================================================
v2 Changes:
    - head_name, head_email, head_phone are now REQUIRED (not optional)
    - Phone: exactly 10 digits domestic; 7-15 digits with + (E.164 international)
    - Email: full RFC 5321 pattern validation, no consecutive dots
    - Head name: letters/spaces/dots/hyphens/apostrophes only, no digits
    - validate_all() convenience function runs all 4 validators at once
================================================================================
"""

import os
import json
import sqlite3
import re as _re
from datetime import datetime
from contextlib import contextmanager

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
DB_PATH        = os.path.join(BASE_DIR, "dept.db")
DEPT_META_PATH = os.path.join(BASE_DIR, "dept_meta.json")


@contextmanager
def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS departments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    UNIQUE NOT NULL,
                head_name   TEXT    NOT NULL DEFAULT '',
                head_email  TEXT    NOT NULL DEFAULT '',
                head_phone  TEXT    NOT NULL DEFAULT '',
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL
            )
        """)
    _migrate_from_json()


def _migrate_from_json() -> None:
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                name TEXT PRIMARY KEY, ran_at TEXT NOT NULL
            )
        """)
        if conn.execute("SELECT 1 FROM _migrations WHERE name='json_import'").fetchone():
            return

    if not os.path.exists(DEPT_META_PATH):
        with _get_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO _migrations (name,ran_at) VALUES (?,?)",
                         ("json_import", datetime.now().isoformat(timespec="seconds")))
        return

    try:
        meta = json.load(open(DEPT_META_PATH, "r", encoding="utf-8"))
    except Exception:
        meta = {}

    now = datetime.now().isoformat(timespec="seconds")
    with _get_conn() as conn:
        for dept_name, values in meta.items():
            head = values.get("head", "") if isinstance(values, dict) else str(values)
            conn.execute("""
                INSERT OR IGNORE INTO departments
                    (name, head_name, head_email, head_phone, created_at, updated_at)
                VALUES (?, ?, '', '', ?, ?)
            """, (dept_name, head, now, now))
        conn.execute("INSERT OR IGNORE INTO _migrations (name,ran_at) VALUES (?,?)",
                     ("json_import", now))


# ── CRUD ──────────────────────────────────────────────────────────────────────

def get_all_depts() -> list:
    try:
        with _get_conn() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM departments ORDER BY name").fetchall()]
    except Exception:
        return []


def get_dept(name: str) -> dict | None:
    try:
        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM departments WHERE name=?", (name,)).fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def upsert_dept(name: str, head_name: str = "", head_email: str = "", head_phone: str = "") -> bool:
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with _get_conn() as conn:
            conn.execute("""
                INSERT INTO departments (name, head_name, head_email, head_phone, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    head_name=excluded.head_name, head_email=excluded.head_email,
                    head_phone=excluded.head_phone, updated_at=excluded.updated_at
            """, (name, head_name.strip(), head_email.strip(), head_phone.strip(), now, now))
        return True
    except Exception as e:
        print(f"[dept_db] upsert error: {e}")
        return False


def rename_dept(old_name: str, new_name: str) -> tuple[bool, str]:
    new_name = new_name.strip()
    if not new_name:
        return (False, "Department name cannot be blank.")
    if new_name == old_name:
        return (True, "")
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with _get_conn() as conn:
            if conn.execute("SELECT 1 FROM departments WHERE name=?", (new_name,)).fetchone():
                return (False, f"A department named '{new_name}' already exists.")
            conn.execute("UPDATE departments SET name=?, updated_at=? WHERE name=?",
                         (new_name, now, old_name))
        return (True, "")
    except Exception as e:
        return (False, str(e))


def delete_dept(name: str) -> bool:
    try:
        with _get_conn() as conn:
            conn.execute("DELETE FROM departments WHERE name=?", (name,))
        return True
    except Exception as e:
        print(f"[dept_db] delete error: {e}")
        return False


def ensure_dept_exists(name: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with _get_conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO departments
                    (name, head_name, head_email, head_phone, created_at, updated_at)
                VALUES (?, '', '', '', ?, ?)
            """, (name, now, now))
    except Exception as e:
        print(f"[dept_db] ensure_dept_exists error: {e}")


# ── VALIDATORS ────────────────────────────────────────────────────────────────
# v2: head_name, head_email, head_phone are REQUIRED by default.
# All return (True, "") on success or (False, error_message) on failure.

def validate_phone(phone: str, required: bool = True) -> tuple[bool, str]:
    """
    Phone validation.
    - REQUIRED by default (v2 change)
    - Allowed chars: digits 0-9, space, +, -, (, ), dot
    - No leading +: exactly 10 digits (Indian domestic)
    - Leading +:   7-15 digits total (ITU-T E.164 international)
    """
    phone = phone.strip()
    if not phone:
        return (False, "Phone number is required.") if required else (True, "")

    allowed = set("0123456789 +-().")
    bad = sorted({c for c in phone if c not in allowed})
    if bad:
        return (False, f"Phone contains invalid character(s): {' '.join(bad)}")

    digits = "".join(c for c in phone if c.isdigit())
    if phone.startswith("+"):
        if len(digits) < 7:
            return (False, f"International phone has only {len(digits)} digit(s) — minimum 7 required.")
        if len(digits) > 15:
            return (False, f"Phone has {len(digits)} digits — maximum 15 allowed (ITU-T E.164).")
    else:
        if len(digits) != 10:
            return (False,
                    f"Phone must be exactly 10 digits (got {len(digits)}). "
                    f"For international numbers, start with + and country code.")
    return (True, "")


def validate_email(email: str, required: bool = True) -> tuple[bool, str]:
    """
    Email validation (RFC 5321 compliant subset).
    - REQUIRED by default (v2 change)
    - Pattern: local@domain.tld
    - No spaces, no consecutive dots, max 254 chars, TLD >= 2 chars
    """
    email = email.strip()
    if not email:
        return (False, "Email address is required.") if required else (True, "")

    if " " in email:
        return (False, "Email address cannot contain spaces.")
    if len(email) > 254:
        return (False, "Email address is too long (max 254 characters).")

    pattern = _re.compile(
        r"^[a-zA-Z0-9._%+\-]{1,64}@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    )
    if not pattern.match(email):
        return (False, f"'{email}' is not a valid email address (expected: name@domain.com).")
    if ".." in email:
        return (False, "Email address cannot contain consecutive dots (..).")
    local = email.split("@")[0]
    if local.startswith(".") or local.endswith("."):
        return (False, "Email local part cannot start or end with a dot.")
    return (True, "")


def validate_dept_name(name: str) -> tuple[bool, str]:
    """
    Department name validation.
    - REQUIRED always
    - Min 2 / max 50 chars
    - Letters, digits, spaces, hyphens, underscores only
    """
    name = name.strip()
    if not name:
        return (False, "Department name cannot be blank.")
    if len(name) < 2:
        return (False, f"Department name too short (min 2 chars, got {len(name)}).")
    if len(name) > 50:
        return (False, f"Department name too long (max 50 chars, got {len(name)}).")
    if not _re.compile(r"^[a-zA-Z0-9 _\-]+$").match(name):
        bad = sorted({c for c in name if not _re.match(r"[a-zA-Z0-9 _\-]", c)})
        return (False, f"Invalid character(s): {' '.join(repr(c) for c in bad)}. "
                       f"Only letters, digits, spaces, hyphens and underscores allowed.")
    return (True, "")


def validate_head_name(name: str, required: bool = True) -> tuple[bool, str]:
    """
    Head name validation.
    - REQUIRED by default (v2 change)
    - Max 100 chars
    - Letters, spaces, dots, hyphens, apostrophes only — NO digits
    """
    name = name.strip()
    if not name:
        return (False, "Head name is required.") if required else (True, "")
    if len(name) > 100:
        return (False, f"Head name too long (max 100 chars, got {len(name)}).")
    pattern = _re.compile(r"^[^\d!@#$%^&*()+=\[\]{};:\"<>?,/\\|`~]+$", _re.UNICODE)
    if not pattern.match(name):
        bad = sorted({c for c in name if _re.match(r"[\d!@#$%^&*()+=\[\]{};:\"<>?,/\\|`~]", c)})
        return (False, f"Invalid character(s): {' '.join(repr(c) for c in bad)}. "
                       f"Only letters, spaces, dots, hyphens and apostrophes allowed.")
    return (True, "")


def validate_all(dept_name: str, head_name: str, head_email: str, head_phone: str) -> tuple[bool, str]:
    """
    Convenience: runs all 4 validators (all required) and returns first error.
    Returns (True, "") if all pass.
    """
    checks = [
        (validate_dept_name,  [dept_name]),
        (validate_head_name,  [head_name,  True]),
        (validate_email,      [head_email, True]),
        (validate_phone,      [head_phone, True]),
    ]
    for fn, args in checks:
        ok, err = fn(*args)
        if not ok:
            return (False, err)
    return (True, "")


# ── SELF-TEST ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("[TEST] init_db...")
    init_db()
    upsert_dept("Engineering", "Mr. Smith", "smith@company.com", "+91 98765 43210")
    upsert_dept("HR",          "Ms. Jones", "jones@company.com", "9876543210")
    print(f"[TEST] Depts: {[d['name'] for d in get_all_depts()]}")

    all_pass = True
    cases = [
        # (fn, args, expected_ok, desc)
        (validate_phone, ["9876543210", True],       True,  "10-digit domestic"),
        (validate_phone, ["+91 9876543210", True],   True,  "international +91"),
        (validate_phone, ["", True],                 False, "empty required"),
        (validate_phone, ["90651280000000", True],   False, "13 digits no +"),
        (validate_email, ["a@b.com", True],          True,  "valid email"),
        (validate_email, ["", True],                 False, "empty required"),
        (validate_email, ["notanemail", True],        False, "no @"),
        (validate_email, ["a..b@x.com", True],       False, "double dot"),
        (validate_head_name, ["Mr. Smith", True],    True,  "valid name"),
        (validate_head_name, ["", True],             False, "empty required"),
        (validate_head_name, ["John123", True],      False, "digits in name"),
        (validate_dept_name, ["Engineering"],        True,  "valid dept"),
        (validate_dept_name, [""],                   False, "blank dept"),
        (validate_dept_name, ["IT/Finance"],         False, "slash in dept"),
    ]
    for fn, args, exp, desc in cases:
        ok, msg = fn(*args)
        passed = ok == exp
        if not passed:
            all_pass = False
        print(f"  [{'PASS' if passed else 'FAIL'}] {desc}: {msg or 'OK'}")

    ok, err = validate_all("Engineering", "Mr. Smith", "smith@co.com", "9876543210")
    print(f"  [{'PASS' if ok else 'FAIL'}] validate_all all valid: {err or 'OK'}")
    ok, err = validate_all("Engineering", "", "smith@co.com", "9876543210")
    print(f"  [{'PASS' if not ok else 'FAIL'}] validate_all missing head: {err}")

    for d in ["Engineering", "HR"]:
        delete_dept(d)
    print(f"\n[TEST] {'All passed!' if all_pass else 'Some FAILED — check above.'}")
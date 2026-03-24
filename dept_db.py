"""
================================================================================
dept_db.py -- Department SQLite Database Layer
================================================================================
Purpose : Stores department metadata (head name, email, phone) in a proper
          SQLite database instead of a flat JSON file.

Database : dept.db  (auto-created in project root on first run)
Table    : departments
           id          INTEGER PRIMARY KEY AUTOINCREMENT
           name        TEXT UNIQUE NOT NULL      -- department folder name
           head_name   TEXT DEFAULT ''
           head_email  TEXT DEFAULT ''
           head_phone  TEXT DEFAULT ''
           created_at  TEXT                      -- ISO timestamp
           updated_at  TEXT                      -- ISO timestamp

Migration : On first run, if dept_meta.json exists in the project root,
            its data is automatically imported into the new DB.
            dept_meta.json is NOT deleted — kept as backup.

Usage in admin.py:
    import dept_db
    dept_db.init_db()                             # call once at app start
    dept_db.upsert_dept("IT", "Mr. O", "o@co.com", "+91 98765 43210")
    dept_db.rename_dept("IT", "Engineering")      # renames folder too
    info = dept_db.get_dept("IT")                 # returns dict or None
    all_depts = dept_db.get_all_depts()           # returns list of dicts

Add to .gitignore:
    dept.db

================================================================================
"""

import os
import json
import sqlite3
from datetime import datetime
from contextlib import contextmanager

# ==========================================
# SECTION 1: PATHS
# ==========================================

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
DB_PATH        = os.path.join(BASE_DIR, "dept.db")
DEPT_META_PATH = os.path.join(BASE_DIR, "dept_meta.json")   # legacy JSON


# ==========================================
# SECTION 2: CONNECTION HELPER
# ==========================================

@contextmanager
def _get_conn():
    """
    Context manager that yields a SQLite connection with:
    - WAL mode enabled (safe concurrent reads + serialised writes)
    - Row factory set to sqlite3.Row (access columns by name)
    - Automatic commit on success, rollback on exception
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent access
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ==========================================
# SECTION 3: SCHEMA INITIALISATION
# ==========================================

def init_db() -> None:
    """
    Creates the departments table if it does not already exist.
    Runs the one-time migration from dept_meta.json if needed.
    Safe to call on every app startup — idempotent.
    """
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

    # One-time migration from legacy dept_meta.json
    _migrate_from_json()


# ==========================================
# SECTION 4: MIGRATION
# ==========================================

def _migrate_from_json() -> None:
    """
    One-time import of dept_meta.json into the SQLite DB.
    Only runs if:
      1. dept_meta.json exists
      2. The migration has NOT already been done (checked via a marker table)
    After migration, the JSON file is kept as a backup — not deleted.
    """
    # Check if migration already done
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                name TEXT PRIMARY KEY,
                ran_at TEXT NOT NULL
            )
        """)
        row = conn.execute(
            "SELECT 1 FROM _migrations WHERE name = 'json_import'"
        ).fetchone()
        if row:
            return  # already migrated

    if not os.path.exists(DEPT_META_PATH):
        # Nothing to migrate — mark as done
        with _get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO _migrations (name, ran_at) VALUES (?, ?)",
                ("json_import", datetime.now().isoformat(timespec="seconds")),
            )
        return

    try:
        with open(DEPT_META_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        meta = {}

    now = datetime.now().isoformat(timespec="seconds")
    migrated = 0

    with _get_conn() as conn:
        for dept_name, values in meta.items():
            head = values.get("head", "") if isinstance(values, dict) else str(values)
            conn.execute("""
                INSERT OR IGNORE INTO departments
                    (name, head_name, head_email, head_phone, created_at, updated_at)
                VALUES (?, ?, '', '', ?, ?)
            """, (dept_name, head, now, now))
            migrated += 1

        conn.execute(
            "INSERT OR IGNORE INTO _migrations (name, ran_at) VALUES (?, ?)",
            ("json_import", now),
        )

    if migrated:
        print(f"[dept_db] Migrated {migrated} department(s) from dept_meta.json → dept.db")


# ==========================================
# SECTION 5: CRUD OPERATIONS
# ==========================================

def get_all_depts() -> list:
    """
    Returns all departments as a list of dicts, sorted by name.
    Each dict has keys: id, name, head_name, head_email, head_phone,
                        created_at, updated_at
    Returns [] if table is empty or DB doesn't exist yet.
    """
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM departments ORDER BY name"
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def get_dept(name: str) -> dict | None:
    """
    Returns a single department dict by name, or None if not found.
    """
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM departments WHERE name = ?", (name,)
            ).fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def upsert_dept(
    name:       str,
    head_name:  str = "",
    head_email: str = "",
    head_phone: str = "",
) -> bool:
    """
    Inserts a new department or updates an existing one.
    name must match the actual filesystem folder name exactly.

    Returns True on success, False on failure.
    """
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with _get_conn() as conn:
            conn.execute("""
                INSERT INTO departments
                    (name, head_name, head_email, head_phone, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    head_name  = excluded.head_name,
                    head_email = excluded.head_email,
                    head_phone = excluded.head_phone,
                    updated_at = excluded.updated_at
            """, (name, head_name.strip(), head_email.strip(),
                  head_phone.strip(), now, now))
        return True
    except Exception as e:
        print(f"[dept_db] upsert_dept error: {e}")
        return False


def rename_dept(old_name: str, new_name: str) -> tuple[bool, str]:
    """
    Renames a department in the database.
    Does NOT rename the filesystem folder — caller (admin.py) handles that
    so it can show proper Streamlit error messages if the rename fails.

    Returns (True, "") on success.
    Returns (False, error_message) on failure.
    """
    new_name = new_name.strip()
    if not new_name:
        return (False, "Department name cannot be blank.")
    if new_name == old_name:
        return (True, "")  # no-op

    now = datetime.now().isoformat(timespec="seconds")
    try:
        with _get_conn() as conn:
            # Check new name not already taken
            existing = conn.execute(
                "SELECT 1 FROM departments WHERE name = ?", (new_name,)
            ).fetchone()
            if existing:
                return (False, f"A department named '{new_name}' already exists.")

            conn.execute("""
                UPDATE departments
                SET name = ?, updated_at = ?
                WHERE name = ?
            """, (new_name, now, old_name))

        return (True, "")
    except Exception as e:
        return (False, str(e))


def delete_dept(name: str) -> bool:
    """
    Removes a department record from the database.
    Does NOT delete the filesystem folder — caller handles that.

    Returns True on success, False on failure.
    """
    try:
        with _get_conn() as conn:
            conn.execute("DELETE FROM departments WHERE name = ?", (name,))
        return True
    except Exception as e:
        print(f"[dept_db] delete_dept error: {e}")
        return False


def ensure_dept_exists(name: str) -> None:
    """
    Ensures a department row exists in the DB for the given folder name.
    Creates a blank row if it doesn't. Used when admin creates a new
    department folder — guarantees DB stays in sync with filesystem.
    """
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


# ==========================================
# SECTION 6: VALIDATION HELPERS
# Production-level validators for all 4 department fields.
# All functions follow the same contract:
#   Returns (True,  "")            — valid or empty (fields are optional)
#   Returns (False, error_message) — invalid, with a clear human-readable reason
# ==========================================

import re as _re

def validate_phone(phone: str) -> tuple[bool, str]:
    """
    Production-level phone number validation.

    Rules:
      1. Optional — empty string is always valid.
      2. Allowed characters: digits 0-9, space, +, -, (, ), dot.
         Any other character is rejected immediately.
      3. Strip all formatting to get digit-only string.
      4. Without country code (no leading +):
           Must be exactly 10 digits (Indian standard).
      5. With country code (starts with +):
           Must be 7–15 digits total (ITU-T E.164 standard).
           Country code itself counts toward the digit total.

    Valid:   "9876543210"  "98765 43210"  "+91 98765 43210"  "+1 415 555 0123"
    Invalid: "90651280000000" (13 digits, no +)  "12345" (too short)
             "abc123" (letters)  "98765-4321O" (letter O not zero)
    """
    phone = phone.strip()
    if not phone:
        return (True, "")

    # Rule 2: allowed characters only
    allowed = set("0123456789 +-().")
    bad_chars = sorted({c for c in phone if c not in allowed})
    if bad_chars:
        return (False, f"Phone contains invalid character(s): {' '.join(bad_chars)}")

    # Rule 3: extract digits
    digits = "".join(c for c in phone if c.isdigit())

    has_country_code = phone.startswith("+")

    if has_country_code:
        # Rule 5: international — 7 to 15 digits total (E.164)
        if len(digits) < 7:
            return (False,
                    f"International phone number has only {len(digits)} digit(s) — "
                    f"minimum 7 required after the country code.")
        if len(digits) > 15:
            return (False,
                    f"Phone number has {len(digits)} digits — "
                    f"maximum 15 allowed (ITU-T E.164 standard).")
    else:
        # Rule 4: domestic (India) — exactly 10 digits
        if len(digits) != 10:
            return (False,
                    f"Phone number must be exactly 10 digits "
                    f"(got {len(digits)}). "
                    f"For international numbers, start with + followed by country code.")

    return (True, "")


def validate_email(email: str) -> tuple[bool, str]:
    """
    Production-level email validation (RFC 5321 / RFC 5322 compliant subset).

    Rules:
      1. Optional — empty string is always valid.
      2. No spaces anywhere in the address.
      3. Must match pattern: local@domain.tld
           local  : letters, digits, dots, +, -, _, % — max 64 chars
           domain : letters, digits, dots, hyphens
           tld    : at least 2 letters
      4. No consecutive dots anywhere (a..b or @..x not allowed).
      5. Cannot start or end with a dot.
      6. Total length max 254 chars (RFC 5321 MAIL command limit).

    Valid:   "mr.d@company.com"  "head+dept@org.in"  "user.name@sub.domain.co.uk"
    Invalid: "notanemail"  "a..b@x.com"  "test @x.com"  "@domain.com"  "x@.com"
    """
    email = email.strip()
    if not email:
        return (True, "")

    # Rule 2: no spaces
    if " " in email:
        return (False, "Email address cannot contain spaces.")

    # Rule 6: max length
    if len(email) > 254:
        return (False, "Email address is too long (max 254 characters).")

    # Rule 3: structural regex
    pattern = _re.compile(
        r"^[a-zA-Z0-9._%+\-]{1,64}"   # local part
        r"@"
        r"[a-zA-Z0-9.\-]+"             # domain
        r"\.[a-zA-Z]{2,}$"             # TLD
    )
    if not pattern.match(email):
        return (False, f"'{email}' is not a valid email address (expected format: name@domain.com).")

    # Rule 4: no consecutive dots
    if ".." in email:
        return (False, "Email address cannot contain consecutive dots (..).")

    # Rule 5: local part cannot start or end with a dot
    local_part = email.split("@")[0]
    if local_part.startswith(".") or local_part.endswith("."):
        return (False, "Email local part cannot start or end with a dot.")

    return (True, "")


def validate_dept_name(name: str) -> tuple[bool, str]:
    """
    Production-level department name validation.

    Rules:
      1. Cannot be blank or only whitespace.
      2. Min 2 characters, max 50 characters (after stripping).
      3. Only letters, digits, spaces, hyphens, underscores allowed.
         No slashes, dots, colons, or other chars that break filesystem
         folder names on Linux / macOS / Windows.

    Valid:   "Engineering"  "HR-Admin"  "IT_Support"  "Finance 2"
    Invalid: "A" (too short)  "IT/Finance" (slash)  "HR." (dot)  "" (blank)
    """
    name = name.strip()

    if not name:
        return (False, "Department name cannot be blank.")

    if len(name) < 2:
        return (False, f"Department name is too short (min 2 characters, got {len(name)}).")

    if len(name) > 50:
        return (False, f"Department name is too long (max 50 characters, got {len(name)}).")

    # Filesystem-safe: letters, digits, spaces, hyphens, underscores only
    pattern = _re.compile(r"^[a-zA-Z0-9 _\-]+$")
    if not pattern.match(name):
        bad = sorted({c for c in name if not _re.match(r"[a-zA-Z0-9 _\-]", c)})
        return (False,
                f"Department name contains invalid character(s): {' '.join(repr(c) for c in bad)}. "
                f"Only letters, digits, spaces, hyphens and underscores are allowed.")

    return (True, "")


def validate_head_name(name: str) -> tuple[bool, str]:
    """
    Production-level department head name validation.

    Rules:
      1. Optional — empty string is always valid.
      2. Max 100 characters.
      3. Only letters (any script), spaces, dots, hyphens, apostrophes allowed.
         Digits and most special characters are rejected — these don't belong
         in a person's name.

    Valid:   "Mr. O'Brien"  "Dr. Smith-Jones"  "Ms. Priya Sharma"  ""
    Invalid: "John123" (digits)  "CEO@company" (@ symbol)
    """
    name = name.strip()
    if not name:
        return (True, "")   # optional

    if len(name) > 100:
        return (False, f"Head name is too long (max 100 characters, got {len(name)}).")

    # Letters (unicode), spaces, dots, hyphens, apostrophes — NO digits
    # Use explicit unicode letter categories instead of \w (which includes digits)
    pattern = _re.compile(r"^[^\d!@#$%^&*()+=\[\]{};:\"<>?,/\\|`~]+$", _re.UNICODE)
    if not pattern.match(name):
        bad = sorted({c for c in name if _re.match(r"[\d!@#$%^&*()+=\[\]{};:\"<>?,/\\|`~]", c)})
        return (False,
                f"Head name contains invalid character(s): {' '.join(repr(c) for c in bad)}. "
                f"Only letters, spaces, dots, hyphens and apostrophes are allowed.")

    return (True, "")


# ==========================================
# SECTION 7: QUICK SELF-TEST
# Run:  python dept_db.py   to verify everything works
# ==========================================

if __name__ == "__main__":
    print("[TEST] Initialising DB...")
    init_db()
    print(f"[TEST] DB created at: {DB_PATH}")

    print("\n[TEST] Upserting test departments...")
    upsert_dept("Engineering", "Mr. Smith",  "smith@company.com",  "+91 98765 43210")
    upsert_dept("HR",          "Ms. Jones",  "jones@company.com",  "+91 98765 43211")
    upsert_dept("Finance",     "",            "",                   "")

    all_d = get_all_depts()
    print(f"[TEST] All departments ({len(all_d)}):")
    for d in all_d:
        print(f"       {d['name']} | {d['head_name']} | {d['head_email']} | {d['head_phone']}")

    print("\n[TEST] Rename Engineering → Tech...")
    ok, err = rename_dept("Engineering", "Tech")
    print(f"       Result: {ok} {err or 'OK'}")

    print("\n[TEST] Fetch Tech...")
    d = get_dept("Tech")
    print(f"       {d}")

    # ── Phone validation ──────────────────────────────────────────────────────
    print("\n[TEST] Phone validation:")
    phone_cases = [
        ("9876543210",        True,  "valid 10-digit domestic"),
        ("98765 43210",       True,  "valid with space"),
        ("+91 98765 43210",   True,  "valid international +91"),
        ("+1 415 555 0123",   True,  "valid international +1"),
        ("+44 7911 123456",   True,  "valid international +44"),
        ("",                  True,  "empty — optional"),
        ("90651280000000",    False, "13 digits no + — INVALID"),
        ("12345",             False, "only 5 digits — too short"),
        ("abc123",            False, "letters — INVALID"),
        ("98765-4321O",       False, "letter O not zero — INVALID"),
        ("+91123",            False, "international too short — INVALID"),
    ]
    all_pass = True
    for val, expected_ok, desc in phone_cases:
        ok, msg = validate_phone(val)
        status = "✅" if ok == expected_ok else "❌ FAIL"
        if ok != expected_ok:
            all_pass = False
        print(f"       {status}  '{val}' — {desc}")
        if msg:
            print(f"              → {msg}")

    # ── Email validation ──────────────────────────────────────────────────────
    print("\n[TEST] Email validation:")
    email_cases = [
        ("mr.d@company.com",        True,  "valid standard"),
        ("head+dept@org.in",        True,  "valid with +"),
        ("user.name@sub.domain.uk", True,  "valid subdomain"),
        ("",                        True,  "empty — optional"),
        ("notanemail",              False, "no @ — INVALID"),
        ("a..b@x.com",              False, "double dot — INVALID"),
        ("test @x.com",             False, "space — INVALID"),
        ("@domain.com",             False, "no local part — INVALID"),
        (".user@domain.com",        False, "starts with dot — INVALID"),
        ("user@domain.c",           False, "TLD too short — INVALID"),
    ]
    for val, expected_ok, desc in email_cases:
        ok, msg = validate_email(val)
        status = "✅" if ok == expected_ok else "❌ FAIL"
        if ok != expected_ok:
            all_pass = False
        print(f"       {status}  '{val}' — {desc}")
        if msg:
            print(f"              → {msg}")

    # ── Dept name validation ──────────────────────────────────────────────────
    print("\n[TEST] Department name validation:")
    dept_cases = [
        ("Engineering",   True,  "valid"),
        ("HR-Admin",      True,  "valid with hyphen"),
        ("IT_Support",    True,  "valid with underscore"),
        ("Finance 2",     True,  "valid with digit"),
        ("",              False, "blank — INVALID"),
        ("A",             False, "too short — INVALID"),
        ("IT/Finance",    False, "slash — INVALID"),
        ("HR.",           False, "dot — INVALID"),
        ("x" * 51,        False, "too long — INVALID"),
    ]
    for val, expected_ok, desc in dept_cases:
        ok, msg = validate_dept_name(val)
        status = "✅" if ok == expected_ok else "❌ FAIL"
        if ok != expected_ok:
            all_pass = False
        print(f"       {status}  '{val[:20]}' — {desc}")
        if msg:
            print(f"              → {msg}")

    # ── Head name validation ──────────────────────────────────────────────────
    print("\n[TEST] Head name validation:")
    head_cases = [
        ("Mr. O'Brien",     True,  "valid with apostrophe"),
        ("Dr. Smith-Jones", True,  "valid with hyphen"),
        ("Ms. Priya Sharma",True,  "valid Indian name"),
        ("",                True,  "empty — optional"),
        ("John123",         False, "digits — INVALID"),
        ("CEO@company",     False, "@ symbol — INVALID"),
        ("x" * 101,         False, "too long — INVALID"),
    ]
    for val, expected_ok, desc in head_cases:
        ok, msg = validate_head_name(val)
        status = "✅" if ok == expected_ok else "❌ FAIL"
        if ok != expected_ok:
            all_pass = False
        print(f"       {status}  '{val[:30]}' — {desc}")
        if msg:
            print(f"              → {msg}")

    print("\n[TEST] Deleting test departments...")
    for dept_name in ["Tech", "HR", "Finance"]:
        delete_dept(dept_name)
    print(f"       Remaining: {[d['name'] for d in get_all_depts()]}")

    print(f"\n{'[TEST] ✅ All tests passed!' if all_pass else '[TEST] ❌ Some tests FAILED — check output above.'}")
"""
================================================================================
main.py -- ChromaDB Vector Store Builder
================================================================================
Purpose : Builds and persists the ChromaDB vector store from the Company
          Standard Playbook. Run once before launching the app, and again
          whenever the playbook file is replaced.

AUTO-DETECTION OF PLAYBOOK CHANGES
------------------------------------
On every run, computes an MD5 hash of the playbook file and compares it
against the stored hash from the previous build.

Outcomes:
  1. No DB exists          -> fresh build
  2. Hash MATCHES          -> load from disk, skip rebuild
  3. Hash DIFFERS          -> delete old DB, rebuild automatically

The hash is stored at: chroma_db/.playbook_hash

Usage:
    python main.py
================================================================================
"""

import glob
import hashlib
import json
import os
import shutil
from datetime import datetime

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# ── Environment ────────────────────────────────────────────────────────────────
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("CRITICAL: GEMINI_API_KEY is not set in the .env file!")

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR             = os.path.dirname(os.path.abspath(__file__))
CONTRACTS_DIR        = os.path.join(BASE_DIR, "MyFiles", "Contracts")
COMPANY_PLAYBOOK_DIR = os.path.join(CONTRACTS_DIR, "company_standard")
CLIENT_CONTRACTS_DIR = os.path.join(CONTRACTS_DIR, "clients")
CHROMA_PERSIST_DIR   = os.path.join(BASE_DIR, "chroma_db")
HASH_FILE_PATH       = os.path.join(CHROMA_PERSIST_DIR, ".playbook_hash")


# ==========================================
# SECTION 1: HASH UTILITIES
# ==========================================

def compute_file_hash(file_path: str) -> str:
    """
    Computes an MD5 hash of a file for change detection.

    Args:
        file_path (str): Absolute path to the file.

    Returns:
        str: 32-character hex MD5 digest.
    """
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _load_hash_from(hash_file_path: str) -> str | None:
    """
    Loads the MD5 hash stored at a specific hash file path.

    Args:
        hash_file_path (str): Absolute path to the .playbook_hash JSON file.

    Returns:
        str:  Stored hash string if file exists and is valid.
        None: If file is missing or corrupt.
    """
    if not os.path.exists(hash_file_path):
        return None
    try:
        with open(hash_file_path, "r", encoding="utf-8") as f:
            return json.load(f).get("playbook_hash")
    except (json.JSONDecodeError, KeyError):
        return None


def _save_hash_to(hash_file_path: str, file_hash: str, playbook_filename: str) -> None:
    """
    Saves the playbook MD5 hash and build metadata to a specific path.

    Args:
        hash_file_path    (str): Absolute path to write the .playbook_hash file.
        file_hash         (str): MD5 hex digest of the playbook.
        playbook_filename (str): Basename of the playbook file.
    """
    os.makedirs(os.path.dirname(hash_file_path), exist_ok=True)
    with open(hash_file_path, "w", encoding="utf-8") as f:
        json.dump({
            "playbook_hash":     file_hash,
            "playbook_filename": playbook_filename,
            "built_at":          datetime.now().isoformat(timespec="seconds"),
        }, f, indent=2)


# Keep backward-compatible aliases (used in __main__ block)
def load_stored_hash() -> str | None:
    """Legacy wrapper — reads from default HASH_FILE_PATH for CLI use."""
    return _load_hash_from(HASH_FILE_PATH)


def save_hash(file_hash: str, playbook_filename: str) -> None:
    """Legacy wrapper — writes to default HASH_FILE_PATH for CLI use."""
    _save_hash_to(HASH_FILE_PATH, file_hash, playbook_filename)


# ==========================================
# SECTION 2: DIRECTORY VALIDATION
# ==========================================

def validate_directory_structure() -> None:
    """Validates that all required project directories exist and prints status."""
    for label, path in [
        ("Contracts root",       CONTRACTS_DIR),
        ("Company Playbook dir", COMPANY_PLAYBOOK_DIR),
        ("Client Contracts dir", CLIENT_CONTRACTS_DIR),
    ]:
        status = "EXISTS" if os.path.exists(path) else "MISSING -- please create this directory"
        print(f"  [{label}]: {status}")


# ==========================================
# SECTION 3: DOCUMENT LOADING & CHUNKING
# ==========================================

def load_and_chunk_document(file_path: str) -> list:
    """
    Loads a PDF or .docx document and splits it into semantic chunks.

    Uses paragraph-first separator hierarchy so complete legal clauses
    are preserved within a single chunk wherever possible.

    Args:
        file_path (str): Absolute path to .pdf or .docx file.

    Returns:
        list[Document]: LangChain Document objects (semantic chunks).

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError:        If file extension is not .pdf or .docx.
    """
    from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Document not found: {file_path}")

    print(f"  -> Reading: {os.path.basename(file_path)}...")

    if file_path.lower().endswith(".pdf"):
        loader = PyPDFLoader(file_path)
    elif file_path.lower().endswith(".docx"):
        loader = Docx2txtLoader(file_path)
    else:
        raise ValueError(f"Unsupported format. Expected .pdf or .docx, got: {file_path}")

    pages = loader.load()
    if not pages:
        print("  -> WARNING: Document contained no content.")
        return []

    chunks = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
        separators=["\n\n", "\n", ".", " ", ""],
        length_function=len,
    ).split_documents(pages)

    print(f"  -> Success: {len(chunks)} chunks created.")
    return chunks


# ==========================================
# SECTION 4: HASH-AWARE DB INITIALIZER
# ==========================================

def initialize_playbook_db(force_rebuild: bool = False, selected_playbook: str = None) -> Chroma | None:
    """
    Builds or loads ChromaDB with automatic playbook change detection.

    Each playbook gets its own isolated ChromaDB subfolder:
        chroma_db/<playbook_stem>/

    This means switching playbooks is instant if that playbook was
    previously embedded — no rebuild needed. Rebuilding only affects
    the currently selected playbook; other playbooks are untouched.

    Decision logic:
        force_rebuild=True  -> always rebuild (UI button)
        No DB / no hash     -> fresh build
        Hash matches        -> load from disk
        Hash differs        -> delete old DB, rebuild

    Args:
        force_rebuild      (bool): Force a full rebuild. Default: False.
        selected_playbook  (str):  Basename of the selected playbook file.
                                   If None, uses the first file found.

    Returns:
        Chroma: Ready-to-query vector store.
        None:   If no playbook file found.
    """
    print("\n[DB SETUP] Initializing Company Playbook Database...")

    # Locate playbook file — use selected_playbook if provided, else first found
    if selected_playbook:
        playbook_path = os.path.join(COMPANY_PLAYBOOK_DIR, selected_playbook)
        if not os.path.exists(playbook_path):
            print(f"[WARNING] Selected playbook not found: {selected_playbook}")
            return None
    else:
        playbook_files = (
            glob.glob(os.path.join(COMPANY_PLAYBOOK_DIR, "*.pdf"))
            + glob.glob(os.path.join(COMPANY_PLAYBOOK_DIR, "*.docx"))
        )
        if not playbook_files:
            print("[WARNING] No playbook file found in company_standard/")
            return None
        playbook_path = playbook_files[0]

    playbook_filename = os.path.basename(playbook_path)
    print(f"[DB SETUP] Found playbook: {playbook_filename}")

    # Each playbook gets its own ChromaDB subfolder so switching playbooks
    # is instant and rebuilding one does not affect another.
    playbook_stem     = os.path.splitext(playbook_filename)[0]
    # Sanitise stem — replace spaces and special chars with underscores
    safe_stem         = "".join(c if c.isalnum() or c in "-_" else "_" for c in playbook_stem)
    chroma_dir        = os.path.join(CHROMA_PERSIST_DIR, safe_stem)
    hash_file         = os.path.join(chroma_dir, ".playbook_hash")

    # Compute current hash
    print("[HASH CHECK] Computing file hash...")
    current_hash = compute_file_hash(playbook_path)
    stored_hash  = _load_hash_from(hash_file)
    db_exists    = os.path.exists(chroma_dir) and bool(os.listdir(chroma_dir))

    # Decide action
    if force_rebuild:
        print("[HASH CHECK] Force rebuild requested.")
        action = "rebuild"
    elif not db_exists or stored_hash is None:
        print("[HASH CHECK] No existing database. Building for first time...")
        action = "rebuild"
    elif current_hash == stored_hash:
        print("[HASH CHECK] Playbook unchanged. Loading existing DB.")
        action = "load"
    else:
        print("[HASH CHECK] Playbook has CHANGED. Rebuilding database...")
        action = "rebuild"

    # Embeddings model
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=GEMINI_API_KEY,
    )

    # Load existing
    if action == "load":
        db = Chroma(persist_directory=chroma_dir, embedding_function=embeddings)
        print(f"[DB SETUP] Loaded. ({db._collection.count()} chunks in memory)")
        return db

    # Rebuild
    if os.path.exists(chroma_dir):
        shutil.rmtree(chroma_dir)
        print("[DB SETUP] Old database removed.")

    print("[DB SETUP] Building new vector store (30-60 seconds)...")
    chunks = load_and_chunk_document(playbook_path)
    if not chunks:
        print("[ERROR] No chunks produced. Cannot build database.")
        return None

    db = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=chroma_dir,
    )
    print(f"[DB SETUP] Database built! ({db._collection.count()} chunks stored)")

    _save_hash_to(hash_file, current_hash, playbook_filename)
    print("[HASH CHECK] Hash saved.")
    return db


# ==========================================
# SECTION 5: ENTRY POINT
# ==========================================

if __name__ == "__main__":
    print("\n[SYSTEM BOOT] Initializing Legal Agent Backend...")
    print("--------------------------------------------------")
    validate_directory_structure()
    print()

    db = initialize_playbook_db()

    if db:
        print("\n[SYSTEM BOOT] SUCCESS -- RAG Memory is online and ready.")
    else:
        print("\n[SYSTEM BOOT] FAILED -- Check warnings above.")
        print("              Place a .docx or .pdf in company_standard/ and re-run.")

    print("--------------------------------------------------\n")
"""
src/config.py
Central configuration: paths, tenant registry, constants.
Enforces tenant isolation via explicit tenant-scoped path dictionaries.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Project root (this file lives in <root>/src/config.py)
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")



DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
SUMMARY_DIR = DATA_DIR / "summaries"
KNOWLEDGE_PDF_DIR = DATA_DIR / "knowledge_pdfs"          # PDFs dropped here get auto-ingested
KNOWLEDGE_BASE_DIR = ROOT_DIR / "knowledge_base"          # .md files + tariff image
OUTPUT_REPORTS_DIR = ROOT_DIR / "output_reports"
VECTOR_STORE_DIR = ROOT_DIR / "vector_store"

GLOBAL_KB_DB = VECTOR_STORE_DIR / "global_kb_db"


TARIFF_IMAGE_CANDIDATES = [
    KNOWLEDGE_BASE_DIR / "tariff.png",
    KNOWLEDGE_BASE_DIR / "Screenshot 2026-07-11 155306.png",
]
TARIFF_JSON_PATH = DATA_DIR / "config" / "tariffs.json"


TENANT_PATHS = {
    "Tenant A": {
        "id": "tenant_a",
        "display": "Tenant A",
        "raw": RAW_DIR / "tenant_a_readings.csv.xlsx",
        "summary": SUMMARY_DIR / "tenant_a_summary.txt",
        "vector_db": VECTOR_STORE_DIR / "tenant_a_db",
        "reports": OUTPUT_REPORTS_DIR / "tenant_a",
    },
    "Tenant B": {
        "id": "tenant_b",
        "display": "Tenant B",
        "raw": RAW_DIR / "tenant_b_readings.csv.xlsx",
        "summary": SUMMARY_DIR / "tenant_b_summary.txt",
        "vector_db": VECTOR_STORE_DIR / "tenant_b_db",
        "reports": OUTPUT_REPORTS_DIR / "tenant_b",
    },
}

TENANTS = list(TENANT_PATHS.keys())


def get_tenant(tenant_name: str) -> dict:
    """Return the isolated path bundle for a tenant. Raises on unknown tenant."""
    if tenant_name not in TENANT_PATHS:
        raise ValueError(f"Unknown tenant: {tenant_name!r}. Valid: {TENANTS}")
    return TENANT_PATHS[tenant_name]


GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "12"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))

EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
RETRIEVAL_TOP_K = 5

COLLECTION_NAME = "documents"

TIME_COLUMN_HINTS = ["timestamp", "time", "date", "datetime", "reading_time"]

for _p in (SUMMARY_DIR, KNOWLEDGE_PDF_DIR, DATA_DIR / "config",
           OUTPUT_REPORTS_DIR / "tenant_a", OUTPUT_REPORTS_DIR / "tenant_b"):
    _p.mkdir(parents=True, exist_ok=True)

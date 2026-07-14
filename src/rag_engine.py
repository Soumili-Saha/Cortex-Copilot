"""
src/rag_engine.py
Embedding + vector-store helpers on ChromaDB (persistent) using a local
sentence-transformers model (no embedding API key needed).

Provides:
  * chunk_text()                 - heading-aware / fixed-size chunking with overlap
  * embed_texts()                - encode a list of strings
  * get_collection(db_path)      - open/create a persistent Chroma collection
  * add_documents(...)           - idempotent upsert (skip already-embedded ids)
  * query(db_path, text, k)      - similarity search -> list[str] chunks
  * ensure_tenant_summary(...)   - auto-generate a tenant summary if missing
  * embed_tenant_summary(...)    - embed a tenant summary into its own db
  * retrieve_tenant(...)         - tenant-scoped retrieval
  * retrieve_global(...)         - shared global_kb_db retrieval
"""
from __future__ import annotations
import hashlib
import logging
from pathlib import Path
from typing import Iterable

from src import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag_engine")

_model = None
_clients: dict[str, object] = {}


# Embedding model (lazy singleton)

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model: %s", config.EMBEDDING_MODEL_NAME)
        _model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = _get_model()
    return model.encode(texts, normalize_embeddings=True).tolist()


# Chunking
def chunk_text(text: str, size: int = None, overlap: int = None) -> list[str]:
    size = size or config.CHUNK_SIZE
    overlap = overlap or config.CHUNK_OVERLAP
    text = (text or "").strip()
    if not text:
        return []

    blocks, current = [], []
    for line in text.splitlines():
        if line.startswith("#") and current:
            blocks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))

    chunks: list[str] = []
    for block in blocks:
        block = block.strip()
        if len(block) <= size:
            if block:
                chunks.append(block)
            continue
        start = 0
        while start < len(block):
            chunks.append(block[start:start + size])
            start += size - overlap
    return [c for c in chunks if c.strip()]


# Chroma persistent collection

def get_collection(db_path: Path):
    import chromadb
    key = str(db_path)
    if key not in _clients:
        db_path.mkdir(parents=True, exist_ok=True)
        _clients[key] = chromadb.PersistentClient(path=str(db_path))
    client = _clients[key]
    return client.get_or_create_collection(
        name=config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )


def _doc_id(source: str, chunk: str) -> str:
    h = hashlib.sha1(f"{source}::{chunk}".encode("utf-8")).hexdigest()
    return h


def add_documents(db_path: Path, chunks: list[str], source: str,
                  extra_meta: dict | None = None) -> int:
    """Idempotent add: skips ids already present (safe to re-run)."""
    if not chunks:
        return 0
    col = get_collection(db_path)
    ids = [_doc_id(source, c) for c in chunks]

    existing = set()
    try:
        got = col.get(ids=ids)
        existing = set(got.get("ids", []))
    except Exception:  # noqa: BLE001
        pass

    new_pairs = [(i, c) for i, c in zip(ids, chunks) if i not in existing]
    if not new_pairs:
        logger.info("No new chunks for source=%s (already embedded).", source)
        return 0

    new_ids = [i for i, _ in new_pairs]
    new_chunks = [c for _, c in new_pairs]
    metas = [{"source": source, **(extra_meta or {})} for _ in new_chunks]
    col.add(ids=new_ids, documents=new_chunks,
            embeddings=embed_texts(new_chunks), metadatas=metas)
    logger.info("Embedded %d new chunks from %s into %s",
                len(new_chunks), source, db_path.name)
    return len(new_chunks)


def query(db_path: Path, text: str, k: int = None) -> list[str]:
    k = k or config.RETRIEVAL_TOP_K
    col = get_collection(db_path)
    try:
        if col.count() == 0:
            return []
    except Exception:  # noqa: BLE001
        return []
    res = col.query(query_embeddings=embed_texts([text]), n_results=k)
    docs = res.get("documents", [[]])
    return docs[0] if docs else []


# Tenant summary generation + embedding
def _build_summary_from_raw(raw_path: Path, tenant_display: str) -> str:
    import pandas as pd
    df = pd.read_excel(raw_path)
    lines = [f"Energy data summary for {tenant_display}.",
             f"Total rows/readings: {len(df)}.",
             f"Columns: {', '.join(map(str, df.columns))}."]

    from src.analytics import detect_time_column  
    tcol = detect_time_column(df)
    if tcol:
        ts = pd.to_datetime(df[tcol], errors="coerce")
        lines.append(f"Time span: {ts.min()} to {ts.max()}.")

    num = df.select_dtypes("number")
    for col in num.columns:
        s = num[col].dropna()
        if s.empty:
            continue
        lines.append(
            f"{col}: min={s.min():.3f}, max={s.max():.3f}, mean={s.mean():.3f}, "
            f"sum={s.sum():.3f}, std={s.std():.3f}."
        )
    return "\n".join(lines)


def ensure_tenant_summary(tenant_display: str) -> Path:
    """Return the tenant summary path, auto-generating it from raw if missing."""
    t = config.get_tenant(tenant_display)
    summary_path: Path = t["summary"]
    if summary_path.exists() and summary_path.stat().st_size > 0:
        return summary_path

    raw_path: Path = t["raw"]
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw data missing for {tenant_display}: {raw_path}")
    logger.info("Summary missing for %s -> generating from raw.", tenant_display)
    text = _build_summary_from_raw(raw_path, tenant_display)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(text, encoding="utf-8")
    return summary_path


def embed_tenant_summary(tenant_display: str) -> int:
    """Ensure summary exists, then embed it into the tenant's OWN vector db."""
    t = config.get_tenant(tenant_display)
    summary_path = ensure_tenant_summary(tenant_display)
    text = summary_path.read_text(encoding="utf-8")
    chunks = chunk_text(text)
    return add_documents(t["vector_db"], chunks,
                         source=f"{t['id']}_summary", extra_meta={"tenant": t["id"]})


def retrieve_tenant(tenant_display: str, question: str, k: int = None) -> list[str]:
    t = config.get_tenant(tenant_display)
    # make sure the tenant summary is embedded before querying
    try:
        if get_collection(t["vector_db"]).count() == 0:
            embed_tenant_summary(tenant_display)
    except Exception as e:  # noqa: BLE001
        logger.warning("Tenant embed check failed: %s", e)
    return query(t["vector_db"], question, k)


def retrieve_global(question: str, k: int = None) -> list[str]:
    return query(config.GLOBAL_KB_DB, question, k)

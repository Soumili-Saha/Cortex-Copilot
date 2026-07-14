"""
scripts/ingest_knowledge_base.py   (NEW)
Scan knowledge_base/ for .md files, chunk them, embed via src/rag_engine,
and store in the SHARED vector_store/global_kb_db.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import logging

from src import config, rag_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_kb")


def run() -> int:
    md_files = sorted(config.KNOWLEDGE_BASE_DIR.glob("*.md"))
    if not md_files:
        logger.warning(
            "No .md files found in %s. GLOBAL_KNOWLEDGE answers will fall back to "
            "the LLM's general electrical knowledge (tagged 'not grounded in local KB').",
            config.KNOWLEDGE_BASE_DIR,
        )
        return 0

    total = 0
    for md in md_files:
        text = md.read_text(encoding="utf-8", errors="ignore")
        chunks = rag_engine.chunk_text(text)
        added = rag_engine.add_documents(
            config.GLOBAL_KB_DB, chunks, source=md.name, extra_meta={"kind": "markdown"}
        )
        logger.info("%s -> %d new chunks", md.name, added)
        total += added
    logger.info("Knowledge-base ingestion complete. %d new chunks embedded.", total)
    return total


if __name__ == "__main__":
    run()

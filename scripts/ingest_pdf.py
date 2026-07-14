"""
scripts/ingest_pdf.py
Parse & embed a general electrical-knowledge PDF into the SHARED
vector_store/global_kb_db -- IF one is present.

On every run this script checks the configured
path; if no PDF exists it logs a clear message and exits cleanly. The moment a PDF is dropped into data/knowledge_pdfs/ it
auto-activates.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import logging

from src import config, rag_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_pdf")


def _read_pdf(path) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to read PDF %s: %s", path, e)
        return ""


def run() -> int:
    config.KNOWLEDGE_PDF_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(config.KNOWLEDGE_PDF_DIR.glob("*.pdf"))
    if not pdfs:
        logger.info("No PDF found at %s -- skipping PDF ingestion.",
                    config.KNOWLEDGE_PDF_DIR)
        return 0

    total = 0
    for pdf in pdfs:
        text = _read_pdf(pdf)
        if not text.strip():
            logger.warning("PDF %s yielded no extractable text -- skipping.", pdf.name)
            continue
        chunks = rag_engine.chunk_text(text)
        added = rag_engine.add_documents(
            config.GLOBAL_KB_DB, chunks, source=pdf.name, extra_meta={"kind": "pdf"}
        )
        logger.info("%s -> %d new chunks", pdf.name, added)
        total += added
    logger.info("PDF ingestion complete. %d new chunks embedded.", total)
    return total


if __name__ == "__main__":
    run()

"""
scripts/pre_compute_summaries.py
Batch / offline generation of data/summaries/tenant_x_summary.txt from raw
tenant data, and embedding each into its OWN tenant vector db.

Run offline. The live chat flow does NOT depend on this script when a valid
summary already exists on disk (src/rag_engine.ensure_tenant_summary handles it).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import logging

from src import config, rag_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pre_compute_summaries")


def run():
    for tenant_display in config.TENANTS:
        try:
            path = rag_engine.ensure_tenant_summary(tenant_display)
            n = rag_engine.embed_tenant_summary(tenant_display)
            logger.info("%s: summary=%s, embedded %d chunks", tenant_display, path.name, n)
        except FileNotFoundError as e:
            logger.warning("%s: %s", tenant_display, e)


if __name__ == "__main__":
    run()

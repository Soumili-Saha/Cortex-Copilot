"""
src/router.py   (NEW)
Intent classification (spec Section 3.4).

A lightweight LLM call decides, by MEANING, whether a question is
TENANT_CONTEXT, GLOBAL_KNOWLEDGE, or OUT_OF_DOMAIN. No keyword lists,
no regex, no hardcoded question table.
"""
from __future__ import annotations
import logging

from src import llm, prompts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("router")

VALID = {"TENANT_CONTEXT", "GLOBAL_KNOWLEDGE", "OUT_OF_DOMAIN"}


def classify_intent(question: str) -> str:
    """Return one of TENANT_CONTEXT / GLOBAL_KNOWLEDGE / OUT_OF_DOMAIN."""
    prompt = prompts.INTENT_CLASSIFIER_TEMPLATE.format(question=question.strip())
    raw = llm.generate_response(
        prompt,
        system=prompts.INTENT_CLASSIFIER_SYSTEM,
        temperature=0.0,
        max_tokens=10,
    )
    label = (raw or "").strip().upper()

    for token in VALID:
        if token in label:
            return token

    logger.warning("Unrecognised classifier output %r -> GLOBAL_KNOWLEDGE", raw)
    return "GLOBAL_KNOWLEDGE"

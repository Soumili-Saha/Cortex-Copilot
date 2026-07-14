"""
src/llm.py
Unified LLM interface: Groq (primary) with automatic Gemini fallback.

Callers use generate_response(prompt, ...) and never need to know which
provider actually answered.
"""
from __future__ import annotations
import logging

from src import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("llm")


_groq_client = None
_gemini_ready = False


def _get_groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set")
        _groq_client = Groq(api_key=config.GROQ_API_KEY)
    return _groq_client


def _init_gemini():
    global _gemini_ready
    if not _gemini_ready:
        import google.generativeai as genai
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set")
        genai.configure(api_key=config.GEMINI_API_KEY)
        _gemini_ready = True


def _groq_chat(prompt: str, system: str | None, temperature: float,
               max_tokens: int, model: str | None = None) -> str:
    client = _get_groq()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model=model or config.GROQ_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=config.LLM_TIMEOUT,
    )
    return resp.choices[0].message.content.strip()


def _gemini_chat(prompt: str, system: str | None, temperature: float,
                 max_tokens: int) -> str:
    import google.generativeai as genai
    _init_gemini()
    model = genai.GenerativeModel(
        config.GEMINI_MODEL,
        system_instruction=system or None,
    )
    resp = model.generate_content(
        prompt,
        generation_config={
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        },
        request_options={"timeout": config.LLM_TIMEOUT},
    )
    return (resp.text or "").strip()


def generate_response(
    prompt: str,
    system: str | None = None,
    temperature: float | None = None,
    max_tokens: int = 1024,
    model_override: str | None = None,
) -> str:
    """
    Generate a completion. Tries Groq first; on ANY Groq failure
    (timeout, rate limit, error) automatically falls back to Gemini.

    model_override lets a caller request a specific Groq model (e.g. the
    fast model for guarded bill/schema answers whose numbers get overwritten
    anyway) instead of the default config.GROQ_MODEL. Only affects the Groq
    leg -- Gemini fallback always uses config.GEMINI_MODEL regardless.
    """
    temperature = config.LLM_TEMPERATURE if temperature is None else temperature

    try:
        return _groq_chat(prompt, system, temperature, max_tokens, model=model_override)
    except Exception as groq_err:  # noqa: BLE001
        logger.warning("Groq failed (%s). Falling back to Gemini.", groq_err)
        try:
            return _gemini_chat(prompt, system, temperature, max_tokens)
        except Exception as gem_err:  # noqa: BLE001
            logger.error("Gemini fallback also failed (%s).", gem_err)
            return (
                "The language service is currently unavailable. "
                "Please verify GROQ_API_KEY / GEMINI_API_KEY in your .env and retry."
            )
def describe_image(image_path: str, prompt: str,
                   temperature: float = 0.0, max_tokens: int = 1024) -> str:
    """Read an image with Gemini vision. Raises if Gemini isn't configured."""
    import google.generativeai as genai
    _init_gemini()
    with open(image_path, "rb") as f:
        img_bytes = f.read()
    model = genai.GenerativeModel(config.GEMINI_MODEL)
    resp = model.generate_content(
        [prompt, {"mime_type": "image/png", "data": img_bytes}],
        generation_config={"temperature": temperature,
                           "max_output_tokens": max_tokens},
    )
    return (resp.text or "").strip()

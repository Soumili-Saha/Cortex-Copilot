"""
api.py  --  FastAPI backend for Cortex Copilot.

Routing

Tenant-context flow:
  1. /api/chat/check  -> if the question is about the tenant's data, tell the UI
     to ask for a start/end time range (and pre-match the relevant variables).
  2. /api/chat/stream -> runs src.insights.analyze_variables over the chosen
     variables + range, phrases the computed facts as human-readable bullet
     insights , grounded strictly in the numbers.

Run:  uvicorn api:app --port 8000   (no --reload for streaming)
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src import (analytics, chart_utils, config, domain_analysis, insights, llm,
                 prompts, query_classifier, rag_engine, report_generator, router)

app = FastAPI(title="Cortex Copilot API")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Source"])
app.mount("/reports", StaticFiles(directory=str(config.OUTPUT_REPORTS_DIR)),
          name="reports")

FAST_MODEL = os.getenv("GROQ_FAST_MODEL", "llama-3.1-8b-instant")
ANSWER_MAX_TOKENS = int(os.getenv("ANSWER_MAX_TOKENS", "500"))  # medium default

SHORT_LEN_HINTS = ("briefly", "brief", "short answer", "in short", "quickly",
                   "one line", "one sentence", "concise", "keep it short",
                   "tl;dr", "just the")
LONG_LEN_HINTS = ("in detail", "detailed", "elaborate", "thorough",
                  "comprehensive", "explain fully", "long answer",
                  "full explanation", "in depth", "go deep", "all the")

SCHEMA_TOKENS_PER_COLUMN = 45   
SCHEMA_TOKENS_BASE = 250        
SCHEMA_TOKENS_MAX = 3000        


def compute_max_tokens(question: str, facts: str | None, is_schema: bool) -> int:
    if is_schema and facts:
        
        n_cols = facts.count("\n- ")
        return min(SCHEMA_TOKENS_MAX,
                  max(SCHEMA_TOKENS_BASE + 300,
                      SCHEMA_TOKENS_BASE + n_cols * SCHEMA_TOKENS_PER_COLUMN))

    ql = question.lower()
    if any(h in ql for h in SHORT_LEN_HINTS):
        return 180
    if any(h in ql for h in LONG_LEN_HINTS):
        return 1200
    return ANSWER_MAX_TOKENS



class ChatIn(BaseModel):
    tenant: str
    message: str
    start: str | None = None
    end: str | None = None
    variables: list[str] = []
    intent: str | None = None   
    subtype: str | None = None  


class AnomalyIn(BaseModel):
    tenant: str
    start: str
    end: str


class RetrieveIn(BaseModel):
    tenant: str
    start: str
    end: str
    variables: list[str] = []


class AnalyzeIn(BaseModel):
    tenant: str
    start: str
    end: str



SYNONYMS = {
    "load": ["load", "demand"], "demand": ["demand", "load"],
    "power": ["watts", "watt", "active"], "watt": ["watts", "watt"],
    "energy": ["wh_received", "vah", "energy"],
    "consumption": ["wh_received", "vah", "energy"],
    "usage": ["wh_received", "watts_total", "energy"],
    "voltage": ["vll", "vln", "v_r", "v_y", "v_b", "volt"],
    "current": ["i_total", "i_r", "i_y", "i_b", "amps", "amp"],
    "reactive": ["var"], "apparent": ["va_"],
    "power factor": ["pf", "factor"], "pf": ["pf"],
    "frequency": ["frequency", "hz"], "thd": ["thd"],
    "harmonic": ["harmonic", "thd", "k_factor"],
    "unbalance": ["unbal"], "interruption": ["interrupt"],
}
DEFAULT_HINTS = ["watts_total", "wh_received", "va_total", "load", "max_demand"]


def _numeric_cols(df: pd.DataFrame) -> list[str]:
    tcol = insights._pick_time_col(df)
    return [c for c in df.columns
            if c != tcol and pd.api.types.is_numeric_dtype(
                pd.to_numeric(df[c], errors="coerce"))]


BILL_HINTS = ["vah_received","va_total"]
BILL_COMPARISON_HINTS = ("why", "compare", "comparison", "compared", "higher", "lower",
                         "increase", "decrease", "change", "vs", "versus", "difference",
                         "went up", "went down", "more than", "less than", "previous",
                         "last month", "last period")
BILL_WHY_HINTS = ("why", "reason", "cause", "caused", "driver", "drivers",
                  "what made", "what's causing", "whats causing")
# temporal uses of the word "current" that must NOT be read as electrical current
_TEMPORAL_CURRENT = ["current bill", "current month", "current week",
                     "current period", "current day", "current reading",
                     "current usage", "currently"]



_LABEL_LINE_RE = re.compile(
    r'^-?\s*([A-Za-z][A-Za-z /()]+?)\s*[:\-]\s*\u20b9\s*(-?[\d,]+\.?\d*)',
)


def _extract_labeled_amounts(facts: str) -> dict:
    """Pull {label: amount} pairs straight out of the deterministic facts
    text produced by domain_analysis.bill_text / bill_delta_text -- this is
    the single source of truth for what the correct numbers actually are."""
    out = {}
    for line in facts.splitlines():
        m = _LABEL_LINE_RE.match(line.strip())
        if m:
            label = m.group(1).strip().lower()
            try:
                out[label] = float(m.group(2).replace(",", ""))
            except ValueError:
                pass
    m2 = re.search(
        r'(?:ESTIMATED TOTAL|period total)[^\u20b9]*\u20b9\s*(-?[\d,]+\.?\d*)',
        facts, re.IGNORECASE)
    if m2:
        try:
            out['total'] = float(m2.group(1).replace(",", ""))
        except ValueError:
            pass
    return out


def enforce_exact_bill_numbers(llm_text: str, facts: str) -> str:
    """Force every rupee figure the LLM wrote next to a KNOWN label to match
    the deterministic value exactly. If the total never shows up at all in
    the LLM's text (it paraphrased around it), append it so the correct
    figure is always visible to the user."""
    truth = _extract_labeled_amounts(facts)
    if not truth:
        return llm_text  

    fixed = llm_text
    for label, value in truth.items():
        pattern = re.compile(
            rf'({re.escape(label)}[^\u20b9\n]{{0,60}}\u20b9)\s?-?[\d,]+\.?\d*',
            re.IGNORECASE)
        fixed = pattern.sub(lambda m: m.group(1) + f"{value:,.2f}", fixed)

    total = truth.get('total')
    if total is not None and f"{total:,.2f}" not in fixed:
        fixed = fixed.rstrip() + f"\n\n**Estimated bill total: \u20b9{total:,.2f}**"
    return fixed


def match_columns(question: str, cols: list[str]) -> list[str]:
    q = question.lower()
    for phrase in _TEMPORAL_CURRENT:
        q = q.replace(phrase, phrase.replace("current", "this"))

    matched: list[str] = []

    if any(w in q for w in ("bill", "cost", "charge", "tariff", "expensive",
                            "invoice", "amount")):
        for c in cols:
            if any(h in c.lower() for h in BILL_HINTS) and c not in matched:
                matched.append(c)

    for key, syns in sorted(SYNONYMS.items(), key=lambda kv: -len(kv[0])):
        if key in q:
            for c in cols:
                if any(s in c.lower() for s in syns) and c not in matched:
                    matched.append(c)
    for c in cols:
        words = [w for w in c.lower().replace("_", " ").split() if len(w) > 2]
        if any(w in q for w in words) and c not in matched:
            matched.append(c)
    if matched:
        return matched[:6]
    defaults = [c for c in cols if any(h in c.lower() for h in DEFAULT_HINTS)]
    return (defaults or cols)[:4]


def classify_fast(question: str) -> str:
    try:
        from groq import Groq
        client = Groq(api_key=config.GROQ_API_KEY)
        prompt = prompts.INTENT_CLASSIFIER_TEMPLATE.format(question=question.strip())
        resp = client.chat.completions.create(
            model=FAST_MODEL,
            messages=[{"role": "system", "content": prompts.INTENT_CLASSIFIER_SYSTEM},
                      {"role": "user", "content": prompt}],
            temperature=0.0, max_tokens=6)
        label = (resp.choices[0].message.content or "").upper()
        for tok in ("TENANT_CONTEXT", "GLOBAL_KNOWLEDGE", "OUT_OF_DOMAIN"):
            if tok in label:
                return tok
    except Exception:
        pass
    return router.classify_intent(question)


# Words that mark a DEFINITION / concept question -> knowledge base, NO range card.
DEFINITION_HINTS = ("what is", "what are", "what do you mean", "define", "definition",
                    "explain", "meaning of", "how does", "how do", "difference between",
                    "why is power factor", "what causes")

# Words that mark a DATA question about the tenant's own readings -> range card.
DATA_TRIGGERS = ("my ", " my", "our ", "mine", "this month", "this week", "today",
                 "yesterday", "last month", "last week", "when was", "when did",
                 "which week", "which day", "which month", "why is my", "why my",
                 "why is the bill", "my bill", "highest", "lowest", "peaked",
                 "trend", "anomal", "over time", "each day", "per day")


# Strong data signals: if ANY of these appear, it's about the tenant's own data,
# even if the sentence happens to start with "what is ...".
STRONG_DATA_SIGNALS = ("my ", " my", "mine", "our ", "this month", "this week",
                       "today", "yesterday", "last month", "last week", "bill",
                       "consumption", "usage", "anomal")


def looks_like_tenant_question(q: str) -> bool:
    ql = " " + q.lower().strip() + " "
    
    if any(s in ql for s in STRONG_DATA_SIGNALS):
        return True
    
    if any(ql.strip().startswith(d) or (" " + d) in ql for d in DEFINITION_HINTS):
        return False
    return any(t in ql for t in DATA_TRIGGERS)


@app.post("/api/chat/check")
def chat_check(body: ChatIn):
    
    intent, sub = query_classifier.classify(body.message.strip())
    need = query_classifier.needs_range(intent, sub) and (
        body.start is None or body.end is None)
    window, matched = None, []
    if need:
        try:
            df = analytics.load_tenant_df(body.tenant)
            matched = match_columns(body.message, _numeric_cols(df))
            _, tmin, tmax = analytics.tenant_time_bounds(body.tenant)
            if tmin is not None:
                window = {"min": pd.to_datetime(tmin).isoformat(),
                          "max": pd.to_datetime(tmax).isoformat()}
        except Exception:
            pass
    return {"intent": intent, "subtype": sub, "needs_range": need,
            "window": window, "variables": matched}


TENANT_BULLET_INSTRUCTION = (
    "Using ONLY the computed analysis facts below, answer the question as a short "
    "set of clear bullet points (start each line with '- '). Be specific: cite the "
    "actual values, timestamps, peak day, busiest/lightest week, weekday-vs-weekend "
    "and peak-hour where relevant. Keep it CONCISE -- include only the bullets that "
    "actually answer the question (around 5, no more than 6). Refer to quantities in "
    "plain human terms (e.g. 'energy consumption', 'peak demand'); NEVER print "
    "internal field codes or table names such as 'I_Y', 'Wh_Received', and NEVER "
    "write phrases like '(as per [X] table)' or 'as per the table'. Never invent "
    "numbers not in the facts. If the range has no data, say so plainly."
)


def build_tenant_prompt(tenant, question, start, end, variables, sub):
    sub = (sub or 'GENERAL').lower()

    if sub == "thd":
        facts = domain_analysis.thd_text(domain_analysis.analyze_thd(tenant, start, end))
        instr = ("Explain in plain language what THD (total harmonic distortion) means, "
                 "state the tenant's ACTUAL values from the facts, and say clearly whether "
                 "they are within the IEEE-519 limits (5% voltage, 8% current) or exceed them. "
                 "Answer in at most 5 short bullets. Never invent numbers; no field codes.")
    elif sub == "pf":
        facts = domain_analysis.pf_text(domain_analysis.analyze_pf(tenant, start, end))
        instr = ("Explain the tenant's power-factor situation using ONLY the facts: the average, "
                 "how often it was below 0.90, when it was lowest, and if many readings are "
                 "negative note the likely reverse-CT/reverse-flow cause. Give a brief likely "
                 "reason for low PF (inductive load / capacitor issue). At most 5 bullets, "
                 "no invented numbers, no field codes.")
    elif sub == "advice":
        adv = domain_analysis.advice_text(domain_analysis.consumption_advice(tenant, start, end))
        pff = domain_analysis.pf_text(domain_analysis.analyze_pf(tenant, start, end))
        pqf = domain_analysis.power_quality_text(domain_analysis.power_quality(tenant, start, end))
        facts = adv + "\n\nPower factor:\n" + pff + "\n\nPower quality:\n" + pqf
        instr = ("Answer 'how to reduce bill/consumption' using the spec's 4-step diagnostic, "
                 "as bullets tied to THIS tenant's numbers:\n"
                 "1) Peak Demand Shaving: if max demand approaches/exceeds contract (1501 kVA), "
                 "advise staggering heavy machinery start-ups.\n"
                 "2) Time-of-Day shifting: note peak vs off-peak usage and advise moving batch "
                 "processes to off-peak (peak 8.65 vs off-peak 6.65/kVAh).\n"
                 "3) Power-factor correction: if weighted/average PF < 0.95, advise inspecting "
                 "capacitor banks / AHF to shrink billed kVAh.\n"
                 "4) Phase balancing: if current unbalance > 10% or neutral current > 15 A, advise "
                 "redistributing single-phase loads across R/Y/B.\n"
                 "Max 6 bullets, each tied to a real number. No invented numbers, no field codes.")
    elif sub == "bill":
        ql = question.lower()
        if any(h in ql for h in BILL_WHY_HINTS):
            reason_res = domain_analysis.bill_reason_facts(tenant, start, end)
            facts = domain_analysis.bill_reason_text(reason_res)
            instr = ("Using ONLY the grounded facts above, explain in 2-4 sentences of natural "
                     "prose -- NOT a bullet list of every tariff component -- why the bill "
                     "changed. Mention only the drivers that actually moved: the consumption "
                     "change (%), whether maximum demand crossed the contract demand (and how "
                     "that changed vs the previous period), and any meaningful power-factor "
                     "swing. Cite the real numbers and the real period dates from the facts. "
                     "If the facts state no comparison could be made, say so plainly instead of "
                     "explaining drivers. End with a short 'Sources: ...' clause naming this "
                     "period's date range and, if compared, the previous period's date range. "
                     "Never invent numbers; no field codes.")
        else:
            cur_bill = domain_analysis.compute_bill(tenant, start, end)
            facts = domain_analysis.bill_text(cur_bill)
            if any(h in ql for h in BILL_COMPARISON_HINTS):
                delta_res = domain_analysis.bill_delta(tenant, start, end)
                facts += "\n\n" + domain_analysis.bill_delta_text(delta_res)
            instr = ("Answer with a clear bill breakdown, one bullet per component, using ONLY "
                     "the figures in the facts above -- e.g. 'Energy charge: ₹X', 'Demand "
                     "charge: ₹X', 'Demand penalty: ₹X', 'Electricity duty: ₹X', 'Customer "
                     "charge: ₹X', ending with 'Estimated total: ₹X'. Include every component "
                     "present in the facts (max 8 bullets). If a previous-period comparison is "
                     "present in the facts, add 1-2 extra bullets explaining which components "
                     "drove the change, in plain rupee terms. If the facts state no comparison "
                     "could be made, say so plainly in one line and do NOT invent a previous "
                     "total or change figures. If power factor is poor, mention it as an "
                     "efficiency issue but do NOT invent a PF penalty (this tariff has none). "
                     "Never invent numbers; no field codes.")
        tariff_ctx = ""
        try:
            ch = rag_engine.retrieve_global("tariff demand charge power factor peak off-peak", k=3)
            if ch:
                tariff_ctx = "\n\nTariff reference:\n" + "\n".join(ch)
        except Exception:
            pass
        facts = facts + tariff_ctx
    elif sub == "anomaly":
        # deterministic anomaly detection over the window
        try:
            df = analytics.load_tenant_df(tenant)
            sub_df = analytics.filter_by_range(
                df, pd.to_datetime(start) if start else None,
                pd.to_datetime(end) if end else None, None)
            labels, feat_cols = analytics.isolation_forest_anomalies(sub_df)
            import numpy as _np
            n = int((_np.asarray(labels) == -1).sum())
            stats = analytics.univariate_stats(sub_df)
            top = analytics.top_univariate_columns(stats, k=5)
            lines = [f"Multivariate anomalies flagged: {n} of {len(labels)} readings."]
            for c in top:
                s = stats.get(c, {})
                lines.append(f"{c}: {s.get('n_anomalies',0)} univariate anomalies "
                             f"(mean {s.get('mean',0):.2f}, max {s.get('max',0):.2f}).")
            pq = domain_analysis.power_quality_text(
                domain_analysis.power_quality(tenant, start, end))
            facts = "\n".join(lines) + "\n\nPower quality checks:\n" + pq
        except Exception as e:
            facts = f"Anomaly analysis unavailable: {e}"
        instr = ("Summarise the abnormalities found using ONLY these facts, in at most "
                 "5 bullets, in plain language. Never invent numbers; no field codes.")
    elif sub == "schema":
        facts = domain_analysis.schema_text(domain_analysis.dataset_schema(tenant))
        instr = ("Using ONLY the facts above (the real column names, their real meanings, "
                 "the real row count, and the real date range -- all read live from the "
                 "actual dataset), answer the user's question about their data's structure. "
                 "Match the level of detail they actually asked for: if they asked for ONLY "
                 "column names, list ONLY the names (no meanings, no row count, no date "
                 "range); if they asked how many rows/columns, answer just that; if they "
                 "asked the date range, answer just that; if they asked for the schema/full "
                 "picture, give the names with their meanings. Use the EXACT column names "
                 "and EXACT meanings as given -- never rename, merge, abbreviate, invent, or "
                 "omit a column silently.")
    else:
        df = analytics.load_tenant_df(tenant)
        if not variables:
            variables = match_columns(question, _numeric_cols(df))
        facts = insights.facts_to_text(
            insights.analyze_variables(tenant, variables, start, end))
        instr = TENANT_BULLET_INSTRUCTION

    user = (f"User question: {question}\n\n"
            f"Computed facts (the ONLY source of truth -- use no number or date not "
            f"listed here):\n{facts}\n\n{instr}")
    return prompts.TENANT_ANSWER_SYSTEM, user, facts


UNAVAILABLE_MESSAGE = (
    "I can only answer from your available meter data (the period covered by your "
    "readings) and general electrical knowledge. I don't have data for that request "
    "(e.g. a different year, the future, or other facilities), so I can't answer it.")

INJECTION_MESSAGE = (
    "I can only work with the data for the tenant you have selected. I can't access "
    "another tenant's data or override that restriction.")


def build_answer_request(body: ChatIn):
    question = body.message.strip()
    
    if (body.intent in query_classifier.INTENTS
            and body.subtype in query_classifier.SUBTYPES):
        intent, sub = body.intent, body.subtype
    else:
        intent, sub = query_classifier.classify(question)

    if intent == "INJECTION":
        return None, None, None, INJECTION_MESSAGE, None
    if intent == "UNAVAILABLE":
        return None, None, None, UNAVAILABLE_MESSAGE, None
    if intent == "OUT_OF_DOMAIN":
        return None, None, None, prompts.OUT_OF_DOMAIN_MESSAGE, None

    if intent == "TENANT_CONTEXT":
        system, user, facts = build_tenant_prompt(
            body.tenant, question, body.start, body.end, body.variables, sub)
        return system, user, "your data", None, facts

    chunks = rag_engine.retrieve_global(question)
    context = "\n\n".join(chunks) if chunks else ""
    user = (f"Question: {question}\n\n"
            f"Reference context (use silently, do NOT mention it):\n{context}\n\n"
            "Answer the question directly and clearly for the user. Do NOT describe "
            "the context, do NOT say things like 'based on the retrieved context' or "
            "'the context does/doesn't say'. Just give the answer itself. Stay within "
            "the electrical domain.")
    source = "knowledge base" if chunks else "general knowledge"
    return prompts.KNOWLEDGE_ANSWER_SYSTEM, user, source, None, None


@app.post("/api/chat/stream")
def chat_stream(body: ChatIn):
    if not body.message.strip():
        raise HTTPException(400, "Empty message")
    system, user, source, canned, facts = build_answer_request(body)

    if canned is not None:
        def one():
            yield canned
        return StreamingResponse(one(), media_type="text/plain",
                                 headers={"X-Source": ""})

    needs_number_guard = bool(facts) and "\u20b9" in facts
    needs_schema_guard = bool(facts) and "Total columns:" in facts
    max_tokens = compute_max_tokens(body.message, facts, needs_schema_guard)

    # Guarded answers (bill / schema) have every number or column name forced
    # to match the deterministic facts afterwards regardless of what the LLM
    # writes -- so the LLM's job there is just plausible connective prose, not
    # correctness. The small/fast model does that job just as well and much
    # quicker, so we only pay for the larger default model when nothing is
    # going to overwrite its numbers anyway.
    gen_model = FAST_MODEL if (needs_number_guard or needs_schema_guard) else config.GROQ_MODEL

    def _apply_guards(text: str) -> str:
        if needs_number_guard:
            text = enforce_exact_bill_numbers(text, facts)
        if needs_schema_guard:
            text = domain_analysis.verify_schema_columns(text, facts)
        return text

    def gen():
        try:
            from groq import Groq
            client = Groq(api_key=config.GROQ_API_KEY)
            stream = client.chat.completions.create(
                model=gen_model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                temperature=config.LLM_TEMPERATURE,
                max_tokens=max_tokens, stream=True)
            if needs_number_guard or needs_schema_guard:
            
                buf = []
                for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        buf.append(delta)
                yield _apply_guards("".join(buf))
            else:
                for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
        except Exception:
            full_text = llm.generate_response(user, system=system,
                                              max_tokens=max_tokens,
                                              model_override=gen_model)
            yield _apply_guards(full_text)

    return StreamingResponse(gen(), media_type="text/plain",
                             headers={"X-Source": source or ""})


@app.get("/api/tenants")
def tenants():
    return {"tenants": config.TENANTS}


@app.get("/api/bounds")
def bounds(tenant: str):
    try:
        tcol, tmin, tmax = analytics.tenant_time_bounds(tenant)
    except Exception as e:
        raise HTTPException(400, str(e))
    if tmin is None:
        return {"has_time": False, "min": None, "max": None}
    return {"has_time": True,
            "min": pd.to_datetime(tmin).isoformat(),
            "max": pd.to_datetime(tmax).isoformat()}


@app.get("/api/variables")
def variables(tenant: str):
    try:
        df = analytics.load_tenant_df(tenant)
        return {"variables": analytics.numeric_variables(df)}
    except Exception as e:
        raise HTTPException(400, str(e))


def _report_url(path: Path) -> str:
    rel = path.relative_to(config.OUTPUT_REPORTS_DIR)
    return f"/reports/{rel.as_posix()}"


@app.post("/api/anomaly-report")
def anomaly_report(body: AnomalyIn):
    try:
        start, end, tmin, tmax = analytics.resolve_window(body.tenant, body.start, body.end)
    except ValueError as e:
        raise HTTPException(400, str(e))
    path = report_generator.generate_anomaly_report(body.tenant, start, end)
    return {"message": f"Anomaly report from {start} to {end}",
            "download_url": _report_url(path), "filename": path.name}


def _phase_cols(df: pd.DataFrame, base: str) -> dict[str, str]:
    """Find {'R': col, 'Y': col, 'B': col} for an exact-name family like
    va_r/va_y/va_b or i_r/i_y/i_b -- same exact-match convention used
    throughout domain_analysis.py."""
    out = {}
    for phase in ("r", "y", "b"):
        col = next((c for c in df.columns if c.lower() == f"{base}_{phase}"), None)
        if col:
            out[phase.upper()] = col
    return out


@app.post("/api/analyze-charts")
def analyze_charts(body: AnalyzeIn):
    """Powers the 'Analyze' side panel: a handful of important, runtime-scaled
    charts (not every variable) for whatever window the user picks."""
    try:
        start, end, tmin, tmax = analytics.resolve_window(body.tenant, body.start, body.end)
    except ValueError as e:
        raise HTTPException(400, str(e))

    df = analytics.load_tenant_df(body.tenant)
    window = analytics.filter_by_range(df, start, end)
    if window.empty:
        raise HTTPException(400, "No readings in this range.")
    tcol, x = analytics.get_full_timestamp(window)
    if x is None:
        x = window.index

    charts = []

    va_cols = _phase_cols(window, "va")
    if va_cols:
        series = {f"VA_{p}": pd.to_numeric(window[c], errors="coerce")
                 for p, c in va_cols.items()}
        charts.append({"title": "Apparent Power by Phase (VA_R / VA_Y / VA_B)",
                       "image": chart_utils.phase_group_chart(
                           x, series, "Apparent Power by Phase", "VA")})

    i_cols = _phase_cols(window, "i")
    if i_cols:
        series = {f"I_{p}": pd.to_numeric(window[c], errors="coerce")
                 for p, c in i_cols.items()}
        charts.append({"title": "Current by Phase (I_R / I_Y / I_B)",
                       "image": chart_utils.phase_group_chart(
                           x, series, "Current by Phase", "Amps")})

    try:
        bill = domain_analysis.compute_bill(body.tenant, start, end)
        k = bill.get("kvah")
        if k:
            charts.append({"title": "Energy Consumption: Peak vs Normal vs Off-peak",
                           "image": chart_utils.tod_bar_chart(
                               k["peak"], k["normal"], k["offpeak"],
                               "Energy Consumption by Tariff Period (kVAh)")})
    except Exception:  # noqa: BLE001
        pass  

    if not charts:
        
        try:
            stats = analytics.univariate_stats(window)
            top = analytics.top_univariate_columns(stats, n=4)
        except Exception:  # noqa: BLE001
            top = []
        if not top:
            top = analytics.numeric_variables(window)[:4]
        for col in top:
            if col not in window.columns:
                continue
            s = pd.to_numeric(window[col], errors="coerce")
            if s.dropna().empty:
                continue
            charts.append({"title": f"{col} over time",
                           "image": chart_utils.phase_group_chart(
                               x, {col: s}, col, col)})

    if not charts:
        raise HTTPException(400, "No relevant columns found for these charts in this dataset.")
    return {"charts": charts, "rows": int(len(window))}


@app.post("/api/retrieve")
def retrieve(body: RetrieveIn):
   
    try:
        df = analytics.load_tenant_df(body.tenant)
    except Exception as e:
        raise HTTPException(400, str(e))
    start = pd.to_datetime(body.start)
    end = pd.to_datetime(body.end) + pd.Timedelta(days=1)
    subset = analytics.filter_by_range(df, start, end, body.variables or None)
    path = report_generator.generate_data_report(
        body.tenant, subset, start, end, body.variables)
    disp = subset.head(200).astype(str)
    return {"columns": list(disp.columns), "rows": disp.values.tolist(),
            "total_rows": int(len(subset)),
            "download_url": _report_url(path), "filename": path.name}


@app.on_event("startup")
def _warmup():
    try:
        rag_engine.embed_texts(["warmup"])
        for t in config.TENANTS:
            rag_engine.embed_tenant_summary(t)  # pre-embed so first real question isn't the first embed
    except Exception as e:
        print("warmup embed failed:", e)
    try:
        rag_engine.retrieve_global("power factor")  # opens/warms the shared global_kb_db too
    except Exception as e:
        print("warmup global kb failed:", e)
    try:
        llm.generate_response("Say OK.", max_tokens=5)  # real round-trip, not just client construction
    except Exception as e:
        print("warmup llm failed:", e)
    print("Warmup complete -- ready for fast responses.")


FRONTEND_DIR = ROOT / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True),
              name="frontend")

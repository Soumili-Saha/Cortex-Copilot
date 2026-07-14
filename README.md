# Cortex Copilot

Cortex Copilot is a tenant-aware electrical meter data assistant. It combines deterministic, code-computed analytics with an LLM narration layer to answer questions about a tenant's electricity bill, power factor, harmonic distortion, consumption patterns, and anomalies -- grounded strictly in that tenant's own meter readings and tariff configuration.

The system is built as a multi-tenant RAG chatbot: every numeric answer originates from code, not from the language model. The LLM's role is limited to phrasing those computed facts as clear, natural-language responses, and a validation layer checks its output against the original facts before anything reaches the user.

## What it does

- **Bill breakdown**: computes a tenant's estimated bill from their raw readings and tariff configuration -- energy charge, demand charge, demand penalty, electricity duty, customer charge -- and explains it in plain language.
- **"Why is my bill higher" reasoning**: when a genuine equal-length prior period exists in the data, explains the actual drivers behind a bill change -- consumption swing, demand crossing the contract limit, power-factor movement -- instead of just listing components.
- **Power factor analysis**: explains a tenant's power-factor situation, including instantaneous and weighted period PF, and flags likely causes for low PF.
- **THD (harmonic distortion) analysis**: reports a tenant's actual THD values against IEEE-519 style limits.
- **Anomaly detection**: runs deterministic multivariate and univariate anomaly detection over a selected time range and summarizes the findings.
- **Consumption advice**: ties efficiency recommendations to the tenant's own load profile, demand, and power-factor numbers rather than generic tips.
- **Dataset schema questions**: answers questions about the tenant's own data structure -- column names, meanings, row counts, date range -- read live from the actual file.
- **General knowledge questions**: answers electrical-concept questions using a dedicated knowledge base, separate from any tenant's data.
- **Analyze sidebar**: lets a user pick any time range and instantly see charts of key electrical attributes (phase-wise power, current, energy by tariff period), auto-selected based on available columns and auto-scaled for readability across any window size, from a few hours to several months.
- **Data retrieval and anomaly reports**: generates downloadable reports for a selected tenant and time range.

## Tenant isolation

Tenant isolation is enforced server-side, not just through prompting. Each tenant has its own raw data path and its own vector database; retrieval for one tenant never has access to another tenant's index. Prompt-injection attempts to access another tenant's data are explicitly classified and refused before reaching the language model.

## Architecture

- **Frontend**: a lightweight chat UI served as static HTML/JS.
- **API layer** (`api.py`): a FastAPI backend that classifies each question's intent and subtype, decides whether a time range is required, builds the appropriate deterministic-facts prompt, and streams the LLM's response back to the user.
- **Deterministic analytics** (`src/analytics.py`, `src/domain_analysis.py`, `src/insights.py`): all numeric computation -- billing, power factor, THD, anomalies, statistics -- happens here in plain code, never in the language model.
- **Knowledge base and RAG** (`src/rag_engine.py`, `knowledge_base/`): a glossary of electrical parameters and the tenant's tariff reference are chunked, embedded, and stored in a persistent vector database (Chroma), with per-tenant isolation and a separate shared store for general domain knowledge.
- **LLM layer** (`src/llm.py`): a unified interface that calls Groq as the primary provider, with automatic fallback to Gemini if Groq fails.
- **Output guards** (`api.py`): every rupee figure and every column name the LLM writes is checked against the deterministic facts and corrected if it drifts, so the final answer can never contradict the underlying computation.

## Project structure

```
.
|-- api.py                      FastAPI backend and routing
|-- requirements.txt
|-- Dockerfile
|-- data/
|   |-- raw/                    tenant meter reading files
|   |-- summaries/              auto-generated tenant summaries
|   `-- config/                 tariff configuration
|-- knowledge_base/
|   |-- power_meter_parameter_glossary.md
|   `-- tariff.md
|-- frontend/
|   `-- index.html
|-- scripts/
|   |-- ingest_knowledge_base.py
|   |-- ingest_pdf.py
|   `-- pre_compute_summaries.py
`-- src/
    |-- analytics.py
    |-- domain_analysis.py
    |-- insights.py
    |-- rag_engine.py
    |-- llm.py
    |-- query_classifier.py
    |-- router.py
    |-- prompts.py
    |-- chart_utils.py
    |-- report_generator.py
    `-- config.py
```

## Setup and installation

### Prerequisites

- Python 3.12
- A Groq API key
- A Gemini API key

### Steps

1. Clone the repository:
   ```
   git clone https://github.com/Soumili-Saha/Cortex-Copilot.git
   cd Cortex-Copilot
   ```

2. Create and activate a virtual environment:
   ```
   python -m venv .venv
   .venv\Scripts\activate      (Windows)
   source .venv/bin/activate   (macOS/Linux)
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Create a `.env` file in the project root with:
   ```
   GROQ_API_KEY=your_groq_key_here
   GEMINI_API_KEY=your_gemini_key_here
   ```

5. Run the server:
   ```
   uvicorn api:app --port 8000
   ```
   Do not use `--reload`, since the chat endpoint streams its response.

6. Open `http://127.0.0.1:8000` in a browser.



## Deployment note

A public deployable link is not included with this submission. The model and its dependencies (including local embedding and inference libraries) exceed what is deployable on the free hosting tiers available at the time of submission: Render's free tier has a memory limit lower than what this application requires under real load, and Hugging Face Spaces no longer supports free hosting for Docker-based backends of this kind. Because of this, only the GitHub repository is provided, along with a recorded demonstration video of the working application, linked in the accompanying submission materials.


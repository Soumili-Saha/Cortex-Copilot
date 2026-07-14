FROM python:3.11-slim

WORKDIR /app

# System deps: build tools for compiled Python packages, libgomp for
# scikit-learn/chromadb, tesseract-ocr for pytesseract (scanned-PDF ingestion)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libgomp1 tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model at BUILD time, not on first request --
# avoids a slow/timed-out cold start on the first real question
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .

EXPOSE 10000
CMD uvicorn api:app --host 0.0.0.0 --port ${PORT:-10000}

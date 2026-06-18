# Agentic RAG Platform v2

A production-ready multi-brand RAG backend built on **FastAPI + SQLite + ChromaDB + Ollama**.

## What's new vs the original starter

| Feature | Original | v2 |
|---|---|---|
| Chat endpoint | ✅ (bare) | ✅ with memory + sources |
| Conversation memory | ❌ | ✅ SQLite-backed, 6-turn window |
| PDF ingestion | ❌ | ✅ PyMuPDF, page-chunked |
| Website crawler | ❌ | ✅ BFS, same-domain, configurable depth |
| FAQ import | ❌ | ✅ JSON + CSV |
| Lead capture | ❌ | ✅ with analytics event |
| Analytics | ❌ | ✅ event log + summary |
| Admin dashboard | ❌ | ✅ session-auth, dark UI |
| Widget frontend | ❌ | ✅ embeddable via `<script>` |
| Settings via .env | ❌ | ✅ pydantic-settings |
| Seed script | ❌ | ✅ auto-ingests `knowledge/` |
| Chunk deduplication | ❌ | ✅ SHA-1 Chroma IDs (upsert) |
| Source tracking | ❌ | ✅ every chunk linked to source |

---

## Local setup (5 steps)

### 1 — Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) installed and running

Pull the required models:
```bash
ollama pull llama3.1
ollama pull nomic-embed-text
```

### 2 — Clone / unzip and install

```bash
cd agentic-rag
pip install -r requirements.txt
```

### 3 — Configure

```bash
cp .env.example .env
# Edit .env — at minimum change ADMIN_PASSWORD and SESSION_SECRET
```

### 4 — Seed knowledge (optional)

Drop `.txt`, `.pdf`, `faq.json`, or `.csv` files into `knowledge/<brand>/`:

```
knowledge/
  kalp/
    product-catalogue.pdf
    faq.json
  biopharma/
    overview.txt
```

Then run:
```bash
python seed.py
```

### 5 — Start

```bash
uvicorn app.main:app --reload
```

Open:
- **API docs**: http://localhost:8000/docs
- **Admin dashboard**: http://localhost:8000/admin
- **Chat widget (default brand)**: http://localhost:8000/widget/default

---

## Embedding a widget on any website

Add this one-liner before `</body>`:

```html
<script src="http://localhost:8000/widget.js" data-brand="kalp"></script>
```

---

## Key API routes

### Chat
```
POST /api/{brand}/chat
{ "message": "...", "session_id": "visitor-abc", "top_k": 5 }
```

### Ingest PDF
```
POST /api/{brand}/ingest/pdf
multipart: source_name=..., file=<binary>
```

### Ingest FAQ (JSON)
```
POST /api/{brand}/ingest/faq
multipart: source_name=..., payload='[{"question":"...","answer":"..."}]'
```

### Crawl a website
```
POST /api/{brand}/crawl
{ "url": "https://example.com", "max_pages": 10, "max_depth": 1 }
```

### Create a new brand
```
POST /api/brands
{ "slug": "my-brand", "name": "My Brand", "description": "..." }
```

### Analytics
```
GET /api/{brand}/analytics
```

### Order tracking
```
POST /api/{brand}/tracking/lookup
{
  "lookup_type": "auto",
  "lookup_value": "BIO-1001",
  "session_id": "visitor-abc",
  "source": "tracking_page"
}
```

The chatbot also handles tracking intent through the normal chat route:
```
POST /api/{brand}/chat
{ "message": "Where is my order?", "session_id": "visitor-abc" }
```

Local startup creates a demo logistics provider, hubs, and these sample orders:

| Brand | Order ID | Tracking Number |
|---|---|---|---|
| `default` | `BIO-1001` | `TRK-BIO-1001` |
| `biopharma` | `BIO-1001` | `TRK-BIO-1001` |
| `biopharma` | `BIO-1001` | `TRK-BIO-1001` |
| `building` | `BLD-1001` | `TRK-BLD-1001` |
| `kalp` | `KALP-1001` | `TRK-KALP-1001` |

Admin tracking UI:
```
GET /admin/tracking
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./app.db` | SQLAlchemy DB URL |
| `CHROMA_PATH` | `./vector_db` | ChromaDB persistence path |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_CHAT_MODEL` | `llama3.1` | Chat model |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model |
| `USE_OLLAMA_EMBEDDINGS` | `true` | Use Ollama embeddings |
| `ADMIN_USERNAME` | `admin` | Dashboard login |
| `ADMIN_PASSWORD` | `change-me-now` | **Change this** |
| `SESSION_SECRET` | *(placeholder)* | **Change this** |
| `CHUNK_SIZE` | `512` | Words per chunk |
| `CHUNK_OVERLAP` | `64` | Overlap between chunks |
| `DEFAULT_TOP_K` | `5` | Default retrieval count |
| `CRAWLER_MAX_PAGES` | `50` | Max pages per crawl |
| `CRAWLER_TIMEOUT` | `10` | HTTP timeout (seconds) |

---

## Production hardening checklist

- [ ] Replace `hash_password` with `bcrypt` or `argon2`
- [ ] Add `slowapi` rate limiting on `/chat` and `/ingest/*`
- [ ] Enable CSRF protection for admin forms
- [ ] Add background task queue (Celery/ARQ) for large crawls and batch PDFs
- [ ] Switch to PostgreSQL for high-concurrency deployments
- [ ] Add JWT / API-key auth for external API clients
- [ ] Set up structured logging (structlog / loguru)
- [ ] Add health-check endpoint for load balancers
- [ ] Set CORS `allow_origins` to your actual frontend domain(s)

---

## Project structure

```
app/
  __init__.py
  config.py       — pydantic-settings env config
  db.py           — SQLAlchemy engine + session
  models.py       — ORM tables
  schemas.py      — Pydantic request/response models
  utils.py        — chunking, slugify, hashing
  chroma_client.py — ChromaDB singleton
  services.py     — all business logic
  main.py         — FastAPI routes, admin UI, widget
knowledge/
  <brand>/        — drop files here for seed.py
seed.py           — auto-ingest knowledge/ on first run
requirements.txt
.env.example
README.md
```

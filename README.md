# Agentic RAG Platform

A production-ready multi-brand RAG backend built on **FastAPI + SQLite + ChromaDB + Ollama/Groq**.

## Features

| Category | Capabilities |
|---|---|
| **Multi-language** | 8 languages (en, es, ar, hi, mr, ta, gu, pa), RTL support for Arabic |
| **Conversational RAG** | Hybrid search (BM25 + dense embeddings), 6-turn memory, source citations |
| **Order tracking** | State-machine-driven tracking intent, carrier lookup, verification, ETA |
| **Admin dashboard** | Session-auth, brand CRUD, analytics, tracking override, source rollback |
| **Widget** | Embeddable `<script>` tag, configurable colors/labels, 8-language UI |
| **Ingestion** | PDF, TXT, FAQ JSON/CSV, website crawler with SSRF protection |
| **Security** | CSP, CSRF (itsdangerous), API-key auth, rate limiting, input sanitization |
| **LLM backends** | Ollama (local) or Groq (cloud), configurable per model |

---

## Quick start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) (optional — can use Groq cloud instead)

Pull models if using Ollama:
```bash
ollama pull qwen3:1.7b
ollama pull nomic-embed-text
```

### Install & run

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set ADMIN_PASSWORD, SESSION_SECRET, CSRF_SECRET
python seed.py                    # optional: ingest knowledge/
uvicorn app.main:app --reload --port 8000
```

### Open

| URL | What |
|---|---|
| `http://localhost:8000/docs` | API docs (OpenAPI) |
| `http://localhost:8000/admin` | Admin dashboard |
| `http://localhost:8000/widget/kalp` | Chat widget |

### Embed widget on any site

```html
<script src="http://localhost:8000/widget.js" data-brand="kalp"></script>
```

---

## Multi-language

All chat, tracking, widget, and admin responses respect the `language` parameter.
Set it per brand in the admin panel or pass it per-request:

```json
POST /api/kalp/chat
{ "message": "Where is my order?", "session_id": "abc", "language": "hi" }
```

Supported languages: `en` (default), `es`, `ar`, `hi`, `mr`, `ta`, `gu`, `pa`.

---

## API overview

All `/api/*` endpoints require the `X-API-Key` header. Create an API key via the admin dashboard.

```json
POST /api/{brand}/chat
{ "message": "...", "session_id": "visitor-abc", "language": "en", "top_k": 5 }
```

```json
POST /api/{brand}/tracking/lookup
{ "lookup_type": "auto", "lookup_value": "KALP-1001", "session_id": "abc", "source": "web" }
```

```json
GET/PUT /api/{brand}/widget-config
// Update widget title, colors, welcome message, placeholder
```

```json
POST /api/{brand}/ingest/text
{ "source_name": "docs", "content": "...", "metadata": {} }
```

```json
POST /api/{brand}/crawl
{ "url": "https://example.com", "max_pages": 10, "max_depth": 1 }
```

Tracking is also handled through the chat endpoint (state machine auto-detects intent):

```json
POST /api/{brand}/chat
{ "message": "Where is my order?", "session_id": "abc" }
```

### Admin routes

| Route | Description |
|---|---|
| `GET /admin` | Dashboard with stats |
| `GET /admin/brands` | Brand CRUD |
| `GET /admin/tracking` | Tracking search |
| `GET /admin/tracking/{brand_slug}/{id}` | Shipment detail + override |
| `GET /admin/analytics` | Usage analytics |

---

## Sample tracking data

Local startup seeds demo data:

| Brand | Order ID | Tracking Number |
|---|---|---|
| `kalp` | `KALP-1001` | `TRK-KALP-1001` |
| `biopharma` | `BIO-1001` | `TRK-BIO-1001` |
| `building` | `BLD-1001` | `TRK-BLD-1001` |

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./app.db` | SQLAlchemy DB URL |
| `CHROMA_PATH` | `./vector_db` | ChromaDB persistence path |
| `ADMIN_USERNAME` | `admin` | Dashboard login |
| `ADMIN_PASSWORD` | `change-me-now` | **Change before deploying** |
| `SESSION_SECRET` | *(placeholder)* | Session signing key — **change this** |
| `CSRF_SECRET` | *(placeholder)* | CSRF signing key — **set this** |
| `CORS_ORIGINS` | `["http://localhost:8000"]` | Allowed CORS origins |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_CHAT_MODEL` | `qwen3:1.7b` | Chat model |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model |
| `OLLAMA_NUM_CTX` | `1024` | Context window size |
| `USE_OLLAMA_EMBEDDINGS` | `true` | Use Ollama for embeddings |
| `GROQ_API_KEY` | — | Cloud LLM (Groq) API key |
| `GROQ_MODEL` | `llama-3.1-8b-instant` | Groq model name |
| `HF_API_TOKEN` | — | HuggingFace API token |
| `HF_EMBED_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | HF embedding model |
| `CHUNK_SIZE` | `512` | Words per chunk |
| `CHUNK_OVERLAP` | `64` | Overlap between chunks |
| `DEFAULT_TOP_K` | `5` | Default retrieval count |
| `CRAWLER_MAX_PAGES` | `50` | Max pages per crawl |
| `CRAWLER_TIMEOUT` | `10` | HTTP timeout (seconds) |

---

## Production hardening

- [x] CSP header (`default-src 'self'`, restricted script/style/font/base-uri)
- [x] CORS locked to configured origins
- [x] CSRF tokens on all admin POST forms (itsdangerous-signed)
- [x] API-key authentication on all `/api/*` endpoints
- [x] Rate limiting (chat, brand creation, FAQ ingestion)
- [x] SSRF protection (DNS rebinding–resistant transport)
- [x] Input sanitization (HTML tag stripping, CSS validation)
- [x] Session cookie hardened (`HttpOnly`, `Secure`, `SameSite`)
- [x] Startup assertions enforce non-default `ADMIN_PASSWORD`/`SESSION_SECRET`/`CSRF_SECRET`
- [ ] Replace `hash_password` with bcrypt or argon2
- [ ] Add background task queue (Celery/ARQ) for large crawls and batch PDFs
- [ ] Switch to PostgreSQL for high-concurrency deployments
- [ ] Add health-check endpoint for load balancers

---

## Project structure

```
app/
  __init__.py
  config.py                     — pydantic-settings env config
  db.py                         — SQLAlchemy engine + session
  models.py                     — ORM tables
  schemas.py                    — Pydantic request/response models
  utils.py                      — chunking, slugify, hashing
  chroma_client.py              — ChromaDB singleton
  main.py                       — FastAPI routes, admin UI, widget
  services.py                   — RAG, chat, FAQ, lead logic
  brand_service.py              — Brand CRUD + widget config validation
  tracking_service.py           — Tracking lookup, status labels, validation
  crawler_service.py            — SSRF-protected web crawler
  conversation_state_machine.py — Tracking intent FSM
  api_auth.py                   — API key generation + validation
  prompts.py                    — 8-language prompts + widget labels
  translations.py               — 8-language key/value dictionary
  templates/                    — Jinja2 templates (admin + widget)
knowledge/
  <brand>/                      — Drop files here for seed.py
pytest.ini
requirements.txt
.env.example
README.md
```

---

## Running tests

```bash
pytest tests/ -v --ignore=tests/perf -k "not (test_stream_chat or test_genuine_faq_still_uses_rag)"
```

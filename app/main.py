"""
main.py — FastAPI application entry point.

Routes:
  /health                           global health
  /api/{brand}/health               brand health
  /api/{brand}/chat                 chat (RAG)
  /api/{brand}/lead                 lead capture
  /api/{brand}/event                analytics event
  /api/{brand}/ingest/text          raw text ingestion
  /api/{brand}/ingest/pdf           PDF ingestion
  /api/{brand}/ingest/faq           FAQ ingestion (JSON or CSV)
  /api/{brand}/crawl                website crawler
  /api/{brand}/conversations/{sid}  conversation history
  /api/{brand}/sources              list knowledge sources
  /api/{brand}/leads                list leads
  /api/{brand}/analytics            analytics summary
  /api/brands                       list all brands
  /widget/{brand}                   embeddable chat widget
  /widget.js                        embeddable JS snippet
  /admin                            admin dashboard (session auth)
  /admin/login                      POST login
  /admin/logout                     POST logout
"""

from __future__ import annotations
import asyncio
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from fastapi import (
    FastAPI, Depends, HTTPException, Request, UploadFile, File, Form,
    status, Query, BackgroundTasks,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app import models
from app.config import get_settings
from app.db import get_db, init_db, SessionLocal
from app.schemas import (
    ChatRequest, ChatResponse,
    FeedbackCreate, WidgetConfig,
    LeadCreate, LeadOut,
    EventCreate,
    TextIngestRequest, CrawlRequest, FAQIngestRequest, IngestResponse,
    ConversationOut, MessageOut,
    BrandCreate, BrandOut,
    SourceOut, AnalyticsSummary, AnalyticsDetailed,
    TrackingLookupRequest, TrackingLookupResponse,
    TrackingAdminShipmentOut, TrackingSearchResponse,
    TrackingOverrideRequest, TrackingEtaResponse,
)
from app.services import (
    rag_service, ingestion_service, crawler_service,
    auth_service, analytics_service, brand_service,
    AnalyticsService, tracking_service, seed_knowledge,
)
from app.observability import init_logging
try:
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
except Exception:
    # prometheus_client may not be installed in some environments (tests).
    def generate_latest():
        return b""

    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

settings = get_settings()
logger = logging.getLogger(__name__)

# Initialize structured logging
init_logging()

# Start: uvicorn app.main:app --workers 4 --loop uvloop

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

tags_metadata = [
    {"name": "System", "description": "Health checks and monitoring endpoints."},
    {"name": "Chat", "description": "RAG-powered chat — both synchronous and SSE streaming."},
    {"name": "Tracking", "description": "Order and shipment tracking lookups and management."},
    {"name": "Knowledge Base", "description": "Ingest text, PDF, FAQ documents and manage knowledge sources."},
    {"name": "Leads", "description": "Capture and list customer leads."},
    {"name": "Analytics", "description": "Event collection and analytics summaries."},
    {"name": "Widget", "description": "Embeddable chat widget configuration and assets."},
    {"name": "Admin", "description": "Admin dashboard — session-auth protected pages and API actions."},
    {"name": "Brands", "description": "Brand CRUD operations."},
    {"name": "Feedback", "description": "Message feedback (thumbs up/down)."},
]

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

app = FastAPI(
    title="Agentic RAG Platform",
    description=(
        "Multi-brand RAG chatbot with order-tracking integration, SSE streaming, "
        "hybrid search, conversation summarization, knowledge-base versioning, "
        "and an embeddable chat widget."
    ),
    summary="Agentic RAG chatbot platform for multi-brand customer support.",
    version="2.0.0",
    contact={"name": "Support", "url": "https://example.com/support"},
    license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
    openapi_tags=tags_metadata,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=3600,
    https_only=True,
    same_site="lax",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Startup ─────────────────────────────────────────────────────────────────

_started = False
_startup_error: str | None = None


@app.on_event("startup")
async def startup_event():
    """Initialize DB, seed defaults and mark readiness.

    This runs at application startup (TestClient triggers it), and records
    any startup error in `_startup_error` so readiness checks can report it.
    """
    global _started, _startup_error
    if _started:
        return
    try:
        init_db()
        db = next(get_db())
        try:
            auth_service.ensure_admin_user(db)
            brand_service.get_or_create(db, "default")
            tracking_service.ensure_defaults(db)
            seed_knowledge(db)
        finally:
            db.close()
        _started = True
        if settings.admin_password == "change-me-now":
            logger.warning("Using default admin_password — set ADMIN_PASSWORD in .env")
        if settings.session_secret == "replace-with-a-long-random-string":
            logger.warning("Using default session_secret — set SESSION_SECRET in .env")
        logger.info("Agentic RAG Platform initialized.")
        try:
            from app.rag_service import _get_reranker
            _get_reranker()
        except Exception:
            logger.exception("Failed to preload CrossEncoder reranker", exc_info=True)
        try:
            from app.ollama_client import ollama

            # Verify Groq API key is valid (~0.5s).
            await ollama.warmup()
        except Exception:
            logger.exception("Failed to verify LLM API key", exc_info=True)
        try:
            from app.chroma_client import _build_embedding_function

            t0 = time.monotonic()
            ef_ = _build_embedding_function()
            if ef_ is not None:
                ef_(["warmup"])
                logger.info("Embedding warmed in %.2fs", time.monotonic() - t0)
        except Exception:
            logger.exception("Failed to warm embedding model", exc_info=True)
    except Exception as e:
        _startup_error = str(e)
        logger.exception("Startup failed: %s", e)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_brand(slug: str, db: Session) -> models.Brand:
    brand = db.query(models.Brand).filter_by(slug=slug).first()
    if not brand:
        raise HTTPException(status_code=404, detail=f"Brand '{slug}' not found")
    return brand


def _require_admin(request: Request):
    if not request.session.get("admin_logged_in"):
        raise HTTPException(status_code=401, detail="Not authenticated")


TEMPLATES_DIR = Path(__file__).parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True,
)


def _load_template(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


# Background ingestion helpers
def _run_ingest_text_background(brand_slug: str, source_name: str, content: str, metadata: dict | None = None):
    db = SessionLocal()
    try:
        from app.brand_service import brand_service
        from app.ingestion_service import ingestion_service
        brand = brand_service.get_or_create(db, brand_slug)
        ingestion_service.ingest_text(db, brand, source_name, content, metadata)
    finally:
        db.close()


def _run_ingest_pdf_background(brand_slug: str, source_name: str, file_bytes: bytes):
    db = SessionLocal()
    try:
        from app.brand_service import brand_service
        from app.ingestion_service import ingestion_service
        brand = brand_service.get_or_create(db, brand_slug)
        ingestion_service.ingest_pdf(db, brand, source_name, file_bytes)
    finally:
        db.close()


def _run_ingest_faq_background(brand_slug: str, source_name: str, file_bytes: bytes | None, payload: str | None):
    db = SessionLocal()
    try:
        from app.brand_service import brand_service
        from app.ingestion_service import ingestion_service
        brand = brand_service.get_or_create(db, brand_slug)
        if file_bytes:
            ingestion_service.ingest_faq_json(db, brand, source_name, file_bytes)
        elif payload:
            items = json.loads(payload)
            if isinstance(items, dict):
                items = [items]
            ingestion_service.ingest_faq_items(db, brand, source_name, items)
    finally:
        db.close()


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"], summary="Global health check")
def global_health(db: Session = Depends(get_db)):
    db_ok = False
    brand_count = 0
    try:
        brand_count = db.query(models.Brand).count()
        db_ok = True
    except Exception:
        pass
    return {
        "status": "ok",
        "database": "connected" if db_ok else "error",
        "brand_count": brand_count,
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/metrics", tags=["System"], summary="Prometheus metrics scrape endpoint", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/ready", tags=["System"], summary="Readiness probe (returns 503 during startup)")
def readiness():
    if _started:
        return {"ready": True}
    return JSONResponse(status_code=503, content={"ready": False, "error": _startup_error or "starting"})


@app.get("/api/{brand_slug}/health", tags=["System"], summary="Per-brand health with chunk count")
def brand_health(brand_slug: str, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    from app.chroma_client import collection_count
    return {
        "status": "ok",
        "brand": brand.slug,
        "chunk_count": collection_count(brand.slug),
    }


# ─── Chat ─────────────────────────────────────────────────────────────────────

@app.post("/api/{brand_slug}/chat", response_model=ChatResponse, tags=["Chat"], summary="Synchronous RAG chat")
@limiter.limit("30/minute")
async def chat(brand_slug: str, req: ChatRequest, request: Request, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    allow_unverified_tracking = (
        req.allow_unverified_tracking
        if getattr(req, "allow_unverified_tracking", None) is not None
        else settings.allow_unverified_tracking
    )
    result = await rag_service.ask(
        db=db,
        brand=brand,
        session_id=req.session_id,
        user_message=req.message,
        top_k=req.top_k,
        allow_unverified_tracking=allow_unverified_tracking,
    )
    if result.get("message_id"):
        from app.rag_service import _generate_suggestions_async
        asyncio.create_task(
            _generate_suggestions_async(
                message_id=result["message_id"],
                brand_name=brand.name,
                answer=result.get("answer", ""),
                history=[],
                user_message=req.message,
                language=getattr(brand, "language", "en"),
            )
        )
        # Trigger background summarization for long conversations
        conv = db.query(models.Conversation).filter_by(
            brand_id=brand.id, session_id=req.session_id,
        ).first()
        if conv:
            recent = db.query(models.Message).filter_by(conversation_id=conv.id).count()
            if recent >= 12:
                from app.db import SessionLocal
                bg_db = SessionLocal()
                from app.rag_service import _summarize_conversation_async
                asyncio.create_task(
                    _summarize_conversation_async(bg_db, brand.name, conv, getattr(brand, "language", "en"))
                )
    return ChatResponse(**result)


@app.post("/api/{brand_slug}/chat/stream", tags=["Chat"], summary="SSE streaming chat")
@limiter.limit("30/minute")
async def chat_stream(brand_slug: str, req: ChatRequest, request: Request, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    allow_unverified_tracking = (
        req.allow_unverified_tracking
        if getattr(req, "allow_unverified_tracking", None) is not None
        else settings.allow_unverified_tracking
    )
    return StreamingResponse(
        rag_service.ask_stream(
            db=db,
            brand=brand,
            session_id=req.session_id,
            user_message=req.message,
            top_k=req.top_k,
            allow_unverified_tracking=allow_unverified_tracking,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Lead capture ─────────────────────────────────────────────────────────────

@app.post("/api/{brand_slug}/lead", response_model=LeadOut, tags=["Leads"], summary="Capture a new lead")
@limiter.limit("5/minute")
def capture_lead(brand_slug: str, request: Request, lead: LeadCreate, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    db_lead = models.Lead(
        brand_id=brand.id,
        session_id=lead.session_id,
        name=lead.name,
        email=lead.email,
        phone=lead.phone,
        company=lead.company,
        notes=lead.notes,
        source=lead.source,
    )
    db.add(db_lead)
    db.commit()
    db.refresh(db_lead)
    AnalyticsService.log_event(db, brand.id, "lead", lead.session_id, {"email": lead.email})
    return db_lead


# ─── Analytics event ──────────────────────────────────────────────────────────

@app.post("/api/{brand_slug}/event", tags=["Analytics"], summary="Log a custom analytics event")
def track_event(brand_slug: str, event: EventCreate, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    AnalyticsService.log_event(db, brand.id, event.event_type, event.session_id, event.payload)
    return {"ok": True}


# Tracking

@app.post("/api/{brand_slug}/tracking/lookup", response_model=TrackingLookupResponse, tags=["Tracking"], summary="Look up shipment by order or tracking number")
def tracking_lookup(
    brand_slug: str,
    req: TrackingLookupRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    brand = _get_brand(brand_slug, db)
    client_host = request.client.host if request.client else ""
    allow_unverified = (
        req.allow_unverified
        if getattr(req, "allow_unverified", None) is not None
        else settings.allow_unverified_tracking
    )
    return tracking_service.lookup(
        db=db,
        brand=brand,
        lookup_type=req.lookup_type,
        lookup_value=req.lookup_value,
        customer_verification=req.customer_verification,
        session_id=req.session_id,
        source=req.source,
        force_refresh=req.force_refresh,
        ip_address=client_host,
        allow_unverified=allow_unverified,
    )


@app.get("/api/{brand_slug}/tracking/shipments", response_model=TrackingSearchResponse, tags=["Tracking"], summary="Search shipments (admin)")
def tracking_search(
    brand_slug: str,
    request: Request,
    q: str = Query("", max_length=96),
    db: Session = Depends(get_db),
):
    _require_admin(request)
    brand = _get_brand(brand_slug, db)
    shipments = tracking_service.search_shipments(db, brand=brand, query=q)
    items = [tracking_service.shipment_to_admin_dict(db, shipment) for shipment in shipments]
    return {"items": items, "count": len(items)}


@app.get("/api/{brand_slug}/tracking/shipments/{shipment_id}", response_model=TrackingAdminShipmentOut, tags=["Tracking"], summary="Get shipment detail (admin)")
def tracking_shipment_detail(
    brand_slug: str,
    shipment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _require_admin(request)
    brand = _get_brand(brand_slug, db)
    shipment = db.query(models.Shipment).filter_by(id=shipment_id, brand_id=brand.id).first()
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    return tracking_service.shipment_to_admin_dict(db, shipment)


@app.post("/api/{brand_slug}/tracking/shipments/{shipment_id}/refresh", response_model=TrackingAdminShipmentOut, tags=["Tracking"], summary="Force-refresh shipment from carrier")
def tracking_refresh(
    brand_slug: str,
    shipment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _require_admin(request)
    brand = _get_brand(brand_slug, db)
    shipment = db.query(models.Shipment).filter_by(id=shipment_id, brand_id=brand.id).first()
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    tracking_service.refresh_shipment(db, shipment.id)
    db.refresh(shipment)
    return tracking_service.shipment_to_admin_dict(db, shipment)


@app.post("/api/{brand_slug}/tracking/shipments/{shipment_id}/recalculate-eta", response_model=TrackingEtaResponse, tags=["Tracking"], summary="Recalculate shipment ETA")
def tracking_recalculate_eta(
    brand_slug: str,
    shipment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _require_admin(request)
    brand = _get_brand(brand_slug, db)
    shipment = db.query(models.Shipment).filter_by(id=shipment_id, brand_id=brand.id).first()
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    return tracking_service.recalculate_eta(db, shipment, force=True)


@app.post("/api/{brand_slug}/tracking/shipments/{shipment_id}/override", response_model=TrackingAdminShipmentOut, tags=["Tracking"], summary="Manually override shipment data")
def tracking_override(
    brand_slug: str,
    shipment_id: int,
    req: TrackingOverrideRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _require_admin(request)
    brand = _get_brand(brand_slug, db)
    shipment = db.query(models.Shipment).filter_by(id=shipment_id, brand_id=brand.id).first()
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    try:
        updated = tracking_service.manual_override(
            db=db,
            shipment_id=shipment.id,
            status=req.status,
            eta=req.eta,
            notes=req.notes,
            admin_username=request.session.get("admin_username", ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return tracking_service.shipment_to_admin_dict(db, updated)


# ─── Text ingestion ───────────────────────────────────────────────────────────

@app.post("/api/{brand_slug}/ingest/text", response_model=IngestResponse, tags=["Knowledge Base"], summary="Ingest raw text content")
@limiter.limit("10/minute")
def ingest_text(
    brand_slug: str,
    req: TextIngestRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    background: bool = False,
):
    brand = _get_brand(brand_slug, db)
    if background:
        if background_tasks is None:
            raise HTTPException(500, "BackgroundTasks not available")
        background_tasks.add_task(_run_ingest_text_background, brand_slug, req.source_name, req.content, req.metadata)
        return IngestResponse(source_id=0, source_name=req.source_name, chunk_count=0, message="Ingestion scheduled in background")
    source = ingestion_service.ingest_text(db, brand, req.source_name, req.content, req.metadata)
    return IngestResponse(
        source_id=source.id,
        source_name=source.name,
        chunk_count=source.chunk_count,
        message=f"Ingested {source.chunk_count} chunks from text.",
    )


# ─── PDF ingestion ────────────────────────────────────────────────────────────

@app.post("/api/{brand_slug}/ingest/pdf", response_model=IngestResponse, tags=["Knowledge Base"], summary="Upload and ingest a PDF file")
@limiter.limit("10/minute")
async def ingest_pdf(
    brand_slug: str,
    request: Request,
    background_tasks: BackgroundTasks,
    source_name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    background: bool = False,
):
    brand = _get_brand(brand_slug, db)
    file_bytes = await file.read()
    if background:
        if background_tasks is None:
            raise HTTPException(500, "BackgroundTasks not available")
        background_tasks.add_task(_run_ingest_pdf_background, brand_slug, source_name, file_bytes)
        return IngestResponse(source_id=0, source_name=source_name, chunk_count=0, message="Ingestion scheduled in background")
    source = ingestion_service.ingest_pdf(db, brand, source_name, file_bytes)
    return IngestResponse(
        source_id=source.id,
        source_name=source.name,
        chunk_count=source.chunk_count,
        message=f"Ingested PDF with {source.chunk_count} chunks.",
    )


# ─── FAQ ingestion ────────────────────────────────────────────────────────────

@app.post("/api/{brand_slug}/ingest/faq", response_model=IngestResponse, tags=["Knowledge Base"], summary="Ingest FAQ items (JSON or CSV)")
async def ingest_faq(
    brand_slug: str,
    background_tasks: BackgroundTasks,
    source_name: str = Form("FAQ Import"),
    file: UploadFile | None = File(None),
    payload: str | None = Form(None),
    db: Session = Depends(get_db),
    background: bool = False,
):
    brand = _get_brand(brand_slug, db)
    source = None

    if file:
        file_bytes = await file.read()
        if background:
            if background_tasks is None:
                raise HTTPException(500, "BackgroundTasks not available")
            background_tasks.add_task(_run_ingest_faq_background, brand_slug, source_name, file_bytes, None)
            return IngestResponse(source_id=0, source_name=source_name, chunk_count=0, message="Ingestion scheduled in background")
        fname = (file.filename or "").lower()
        if fname.endswith(".csv"):
            source = ingestion_service.ingest_faq_csv(db, brand, source_name, file_bytes)
        else:
            source = ingestion_service.ingest_faq_json(db, brand, source_name, file_bytes)
    elif payload:
        if background:
            if background_tasks is None:
                raise HTTPException(500, "BackgroundTasks not available")
            background_tasks.add_task(_run_ingest_faq_background, brand_slug, source_name, None, payload)
            return IngestResponse(source_id=0, source_name=source_name, chunk_count=0, message="Ingestion scheduled in background")
        items = json.loads(payload)
        if isinstance(items, dict):
            items = [items]
        source = ingestion_service.ingest_faq_items(db, brand, source_name, items)
    else:
        raise HTTPException(400, "Provide a file or payload")

    return IngestResponse(
        source_id=source.id,
        source_name=source.name,
        chunk_count=source.chunk_count,
        message=f"Imported {source.chunk_count} FAQ chunks.",
    )


# ─── Website crawler ──────────────────────────────────────────────────────────

@app.post("/api/{brand_slug}/crawl", response_model=IngestResponse, tags=["Knowledge Base"], summary="Crawl a website and ingest its content")
def crawl_website(brand_slug: str, req: CrawlRequest, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    source = crawler_service.crawl(
        db, brand, req.url, req.max_pages, req.max_depth, req.same_domain_only
    )
    return IngestResponse(
        source_id=source.id,
        source_name=source.name,
        chunk_count=source.chunk_count,
        message=f"Crawled and indexed {source.chunk_count} chunks.",
    )


# ─── Conversation history ─────────────────────────────────────────────────────

@app.get("/api/{brand_slug}/conversations/{session_id}", response_model=ConversationOut, tags=["Chat"], summary="Get conversation history")
def get_conversation(brand_slug: str, session_id: str, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    conv = db.query(models.Conversation).filter_by(brand_id=brand.id, session_id=session_id).first()
    if not conv:
        return ConversationOut(session_id=session_id, messages=[])
    msgs = [MessageOut.model_validate(m) for m in conv.messages]
    return ConversationOut(session_id=session_id, messages=msgs)


@app.get("/api/{brand_slug}/suggestions/{message_id}", tags=["Chat"], summary="Get suggested follow-up questions for a message")
def get_suggestions(brand_slug: str, message_id: int, db: Session = Depends(get_db)):
    msg = db.query(models.Message).filter_by(id=message_id).first()
    if not msg:
        return {"suggestions": []}
    try:
        suggestions = json.loads(msg.suggested_questions_json)
        if not isinstance(suggestions, list):
            suggestions = []
    except (json.JSONDecodeError, TypeError):
        suggestions = []
    return {"suggestions": suggestions}


# ─── Brand listing / creation ─────────────────────────────────────────────────

@app.get("/api/brands", response_model=list[BrandOut], tags=["Brands"], summary="List all brands")
@app.get("/api/{brand_slug}/brands", response_model=list[BrandOut], tags=["Brands"], summary="List brands (by slug)")
def list_brands(db: Session = Depends(get_db), brand_slug: str = "default"):
    return brand_service.list_all(db)


@app.post("/api/brands", response_model=BrandOut, tags=["Brands"], summary="Create a new brand")
def create_brand(req: BrandCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Brand).filter_by(slug=req.slug).first()
    if existing:
        raise HTTPException(409, f"Brand '{req.slug}' already exists")
    return brand_service.create(db, req.slug, req.name, req.description)


# ─── Sources & leads ──────────────────────────────────────────────────────────

@app.get("/api/{brand_slug}/sources", response_model=list[SourceOut], tags=["Knowledge Base"], summary="List all knowledge sources for a brand")
def list_sources(brand_slug: str, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    return db.query(models.KnowledgeSource).filter_by(brand_id=brand.id).order_by(models.KnowledgeSource.created_at.desc()).all()


@app.post("/api/{brand_slug}/knowledge/{source_id}/rollback", tags=["Knowledge Base"], summary="Roll back a knowledge source to its previous version")
def rollback_source(brand_slug: str, source_id: int, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    source = db.query(models.KnowledgeSource).filter_by(id=source_id, brand_id=brand.id).first()
    if not source:
        raise HTTPException(404, "Source not found")
    if not source.previous_source_id:
        raise HTTPException(400, "No previous version to roll back to")
    prev = db.query(models.KnowledgeSource).filter_by(id=source.previous_source_id).first()
    if not prev:
        raise HTTPException(404, "Previous source version not found")
    source.is_active = False
    prev.is_active = True
    db.commit()
    from app.hybrid_retriever import invalidate_retriever
    invalidate_retriever(brand.slug)
    return {"ok": True, "rolled_back_to": prev.id, "version": prev.version}


@app.get("/api/{brand_slug}/leads", response_model=list[LeadOut], tags=["Leads"], summary="List captured leads")
def list_leads(brand_slug: str, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    return db.query(models.Lead).filter_by(brand_id=brand.id).order_by(models.Lead.created_at.desc()).all()


# ─── Analytics summary ────────────────────────────────────────────────────────

@app.get("/api/{brand_slug}/analytics", response_model=AnalyticsSummary, tags=["Analytics"], summary="Get analytics summary for a brand")
def get_analytics(brand_slug: str, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    return analytics_service.get_summary(db, brand)


@app.get("/api/{brand_slug}/analytics/detailed", response_model=AnalyticsDetailed, tags=["Analytics"], summary="Get detailed analytics with time-series")
def get_analytics_detailed(brand_slug: str, days: int = 30, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    return analytics_service.get_detailed(db, brand, days)


@app.get("/admin/analytics", response_class=HTMLResponse, tags=["Admin"], summary="Admin analytics dashboard page")
def admin_analytics(request: Request, days: int = 30, db: Session = Depends(get_db)):
    _require_admin(request)
    brands = brand_service.list_all(db)
    all_data = {}
    for b in brands:
        all_data[b.slug] = analytics_service.get_detailed(db, b, days)
    totals = {
        "total_chats": sum(d["total_chats"] for d in all_data.values()),
        "total_leads": sum(d["total_leads"] for d in all_data.values()),
        "avg_latency": round(sum(d["avg_latency_ms"] for d in all_data.values()) / max(len(all_data), 1), 1),
    }
    html = _load_template("admin_analytics.html").format(
        total_chats=totals["total_chats"],
        total_leads=totals["total_leads"],
        avg_latency=totals["avg_latency"],
        days=days,
        days_links="".join(
            f'<span class="active">{d}d</span>' if d == days else f'<a href="/admin/analytics?days={d}">{d}d</a>'
            for d in (7, 30, 90)
        ),
        brands_json=json.dumps(list(all_data.keys())),
        detailed_json=json.dumps(all_data),
        year=datetime.utcnow().year,
    )
    return HTMLResponse(html)


# ─── Feedback ──────────────────────────────────────────────────────────────────

@app.post("/api/{brand_slug}/feedback", tags=["Feedback"], summary="Submit message feedback (thumbs up/down)")
def submit_feedback(
    brand_slug: str,
    req: FeedbackCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    brand = _get_brand(brand_slug, db)
    if req.rating not in (1, -1):
        raise HTTPException(400, "rating must be 1 (thumbs up) or -1 (thumbs down)")
    msg = db.query(models.Message).filter_by(id=req.message_id).first()
    if not msg:
        raise HTTPException(404, "Message not found")
    feedback = models.MessageFeedback(
        message_id=req.message_id,
        brand_id=brand.id,
        session_id=req.session_id,
        rating=req.rating,
        feedback_text=req.feedback_text,
    )
    db.add(feedback)
    db.commit()
    AnalyticsService.log_event(db, brand.id, "feedback", feedback.session_id, {
        "message_id": req.message_id,
        "rating": req.rating,
    })
    return {"ok": True}


# ─── Widget config ─────────────────────────────────────────────────────────────

@app.get("/api/{brand_slug}/widget-config", response_model=WidgetConfig, tags=["Widget"], summary="Get widget configuration")
def get_widget_config(brand_slug: str, db: Session = Depends(get_db)):
    _get_brand(brand_slug, db)
    return brand_service.get_widget_config(db, brand_slug)


@app.put("/api/{brand_slug}/widget-config", response_model=WidgetConfig, tags=["Widget"], summary="Update widget configuration")
def update_widget_config(brand_slug: str, cfg: WidgetConfig, request: Request, db: Session = Depends(get_db)):
    _get_brand(brand_slug, db)
    _require_admin(request)
    return brand_service.update_widget_config(db, brand_slug, cfg.model_dump())


# ─────────────────────────────────────────────────────────────────────────────
# Widget frontend
# ─────────────────────────────────────────────────────────────────────────────




@app.get("/widget/{brand_slug}", response_class=HTMLResponse, tags=["Widget"], summary="Get the embeddable chat widget HTML")
def widget(brand_slug: str, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    cfg = brand_service.get_widget_config(db, brand_slug)
    logo_html = f'<img src="{cfg.logo_url}" alt="Logo" style="height:24px;border-radius:4px;">' if cfg.logo_url else ""
    title_text = cfg.title or brand_slug
    welcome = cfg.welcome_message or f"Hello! I'm the {brand_slug} assistant. Ask me anything."
    from app.prompts import get_widget_labels
    labels = get_widget_labels(getattr(brand, "language", "en"))
    return HTMLResponse(_load_template("widget.html").format(
        brand=brand_slug,
        accent_color=cfg.accent_color,
        bg_color=cfg.bg_color,
        surface_color=cfg.surface_color,
        border_color=cfg.border_color,
        text_color=cfg.text_color,
        text_dim_color=cfg.text_dim_color,
        user_bg_color=cfg.user_bg_color,
        bot_bg_color=cfg.bot_bg_color,
        width=cfg.width,
        height=cfg.height,
        logo_html=logo_html,
        title=title_text,
        welcome_message=welcome,
        **labels,
    ))


@app.get("/widget.js", tags=["Widget"], summary="Get the widget JavaScript snippet")
def widget_js():
    js = """
(function() {
  var s = document.currentScript;
  var brand = s.dataset.brand || "default";
  var pos = s.dataset.position || "bottom-right";
  var w = s.dataset.width || "420px";
  var h = s.dataset.height || "600px";
  var parts = pos.split("-");
  var v = parts[0] || "bottom";
  var hz = parts[1] || "right";
  var iframe = document.createElement("iframe");
  iframe.src = "/widget/" + brand;
  var css = "position:fixed;border:none;border-radius:12px;box-shadow:0 8px 40px rgba(0,0,0,.4);z-index:9999;width:" + w + ";height:" + h + ";";
  if (v === "bottom") css += "bottom:20px;";
  else css += "top:20px;";
  if (hz === "right") css += "right:20px;";
  else css += "left:20px;";
  iframe.style.cssText = css;
  document.body.appendChild(iframe);
})();
"""
    return Response(content=js, media_type="application/javascript")


# ─────────────────────────────────────────────────────────────────────────────
# Admin dashboard
# ─────────────────────────────────────────────────────────────────────────────

def _admin_dashboard_html(db: Session, error: str = "") -> str:
    from app.chroma_client import collection_count

    brands = brand_service.list_all(db)
    total_chunks = db.query(models.Chunk).count()
    total_convs = db.query(models.Conversation).count()
    total_msgs = db.query(models.Message).count()
    total_leads = db.query(models.Lead).count()
    total_events = db.query(models.AnalyticsEvent).count()
    tracking_stats = tracking_service.get_tracking_analytics(db)

    brand_list = []
    for b in brands:
        brand_list.append({
            "slug": b.slug,
            "name": b.name,
            "chunk_count": db.query(models.Chunk).filter_by(brand_id=b.id).count(),
            "conversation_count": db.query(models.Conversation).filter_by(brand_id=b.id).count(),
            "lead_count": db.query(models.Lead).filter_by(brand_id=b.id).count(),
        })

    recent = (
        db.query(models.Message)
        .order_by(models.Message.created_at.desc())
        .limit(10)
        .all()
    )
    recent_messages = []
    for m in recent:
        conv = db.query(models.Conversation).get(m.conversation_id)
        brand_slug = db.query(models.Brand).get(conv.brand_id).slug if conv else "-"
        recent_messages.append({
            "brand_slug": brand_slug,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.strftime("%H:%M %d %b"),
        })

    recent_shipments = tracking_service.search_shipments(db, query="", limit=10)
    shipment_list = []
    for shipment in recent_shipments:
        current_hub = shipment.current_hub.hub_name if shipment.current_hub else "-"
        shipment_list.append({
            "brand_slug": shipment.brand.slug,
            "order_id": shipment.order.order_id,
            "tracking_number": shipment.tracking_number,
            "status_label": tracking_service.status_label(shipment.current_status),
            "current_hub": current_hub,
            "eta_date": shipment.eta_date or "-",
            "id": shipment.id,
        })

    return _jinja_env.get_template("admin_dashboard.html").render(
        error=error,
        len_brands=len(brands),
        total_chunks=total_chunks,
        total_convs=total_convs,
        total_msgs=total_msgs,
        total_leads=total_leads,
        total_events=total_events,
        total_shipments=tracking_stats['total_shipments'],
        delayed_shipments=tracking_stats['delayed_shipments'],
        brands=brand_list,
        shipments=shipment_list,
        recent_messages=recent_messages,
    )


def _admin_tracking_html(db: Session, query: str = "", brand_slug: str = "") -> str:
    brands = brand_service.list_all(db)
    selected_brand = None
    if brand_slug:
        selected_brand = db.query(models.Brand).filter_by(slug=brand_slug).first()

    shipments = tracking_service.search_shipments(db, brand=selected_brand, query=query, limit=100)
    stats = tracking_service.get_tracking_analytics(db, selected_brand)

    shipment_list = []
    for shipment in shipments:
        current_hub = shipment.current_hub.hub_name if shipment.current_hub else "-"
        shipment_list.append({
            "brand_slug": shipment.brand.slug,
            "order_id": shipment.order.order_id,
            "tracking_number": shipment.tracking_number,
            "status_label": tracking_service.status_label(shipment.current_status),
            "current_hub": current_hub,
            "location_text": shipment.current_location_text or "-",
            "eta_date": shipment.eta_date or "-",
            "id": shipment.id,
        })

    hub_list = [{"name": hub_name, "count": count} for hub_name, count in stats["common_hubs"]]

    return _jinja_env.get_template("admin_tracking.html").render(
        search_query=query,
        brands=brands,
        brand_slug=brand_slug,
        total_shipments=stats['total_shipments'],
        active_shipments=stats['active_shipments'],
        delivered_shipments=stats['delivered_shipments'],
        delayed_shipments=stats['delayed_shipments'],
        delay_percentage=stats['delay_percentage'],
        tracking_requests=stats['tracking_requests'],
        shipments=shipment_list,
        hubs=hub_list,
    )


def _admin_tracking_detail_html(db: Session, shipment: models.Shipment) -> str:
    detail = tracking_service.shipment_to_admin_dict(db, shipment)

    statuses = (
        "order_created", "picked_up", "at_origin_hub", "in_transit",
        "at_intermediate_hub", "at_destination_hub", "out_for_delivery",
        "delivered", "delayed", "failed_delivery", "returned", "cancelled",
    )
    status_list = []
    for status_value in statuses:
        status_list.append({
            "value": status_value,
            "label": tracking_service.status_label(status_value),
            "selected": status_value == shipment.current_status,
        })

    events = []
    for event in detail["events"]:
        hub_name = event["hub"]["hub_name"] if event.get("hub") else "-"
        events.append({
            "event_timestamp": event["event_timestamp"],
            "status_label": tracking_service.status_label(event["normalized_status"]),
            "hub_name": hub_name,
            "location_text": event["location_text"],
            "notes": event["notes"],
        })

    eta_value = shipment.eta_date.isoformat() if shipment.eta_date else ""
    current_hub = shipment.current_hub.hub_name if shipment.current_hub else "-"
    previous_hub = shipment.previous_hub.hub_name if shipment.previous_hub else "-"
    next_hub = shipment.next_hub.hub_name if shipment.next_hub else "-"

    return _jinja_env.get_template("admin_tracking_detail.html").render(
        shipment_id=shipment.id,
        brand_slug=shipment.brand.slug,
        order_id=shipment.order.order_id,
        tracking_number=shipment.tracking_number,
        status_label=tracking_service.status_label(shipment.current_status),
        current_hub=current_hub,
        previous_hub=previous_hub,
        next_hub=next_hub,
        eta=shipment.eta_date or "-",
        statuses=status_list,
        eta_value_input=eta_value,
        events=events,
    )





@app.get("/admin", response_class=HTMLResponse, tags=["Admin"], summary="Admin dashboard (or login page)")
def admin_get(request: Request, db: Session = Depends(get_db)):
    if not request.session.get("admin_logged_in"):
        return HTMLResponse(_jinja_env.get_template("admin_login.html").render(error=""))
    return HTMLResponse(_admin_dashboard_html(db))


@app.get("/admin/tracking", response_class=HTMLResponse, tags=["Admin"], summary="Admin tracking search page")
def admin_tracking_get(
    request: Request,
    q: str = "",
    brand: str = "",
    db: Session = Depends(get_db),
):
    if not request.session.get("admin_logged_in"):
        return HTMLResponse(_jinja_env.get_template("admin_login.html").render(error=""))
    return HTMLResponse(_admin_tracking_html(db, query=q, brand_slug=brand))


@app.get("/admin/tracking/{shipment_id}", response_class=HTMLResponse, tags=["Admin"], summary="Admin shipment detail page")
def admin_tracking_detail_get(
    shipment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    if not request.session.get("admin_logged_in"):
        return HTMLResponse(_jinja_env.get_template("admin_login.html").render(error=""))
    shipment = db.query(models.Shipment).filter_by(id=shipment_id).first()
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    return HTMLResponse(_admin_tracking_detail_html(db, shipment))


@app.post("/admin/tracking/{shipment_id}/refresh", tags=["Admin"], summary="Admin: refresh shipment")
def admin_tracking_refresh(
    shipment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _require_admin(request)
    shipment = tracking_service.refresh_shipment(db, shipment_id)
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/admin/tracking/{shipment_id}", status_code=302)


@app.post("/admin/tracking/{shipment_id}/recalculate-eta", tags=["Admin"], summary="Admin: recalculate ETA")
def admin_tracking_recalculate_eta(
    shipment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _require_admin(request)
    shipment = db.query(models.Shipment).filter_by(id=shipment_id).first()
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    tracking_service.recalculate_eta(db, shipment, force=True)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/admin/tracking/{shipment_id}", status_code=302)


@app.post("/admin/tracking/{shipment_id}/override", tags=["Admin"], summary="Admin: override shipment")
async def admin_tracking_override(
    shipment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _require_admin(request)
    form = await request.form()
    eta_text = str(form.get("eta") or "").strip()
    eta_value = datetime.strptime(eta_text, "%Y-%m-%d").date() if eta_text else None
    try:
        updated = tracking_service.manual_override(
            db=db,
            shipment_id=shipment_id,
            status=str(form.get("status") or ""),
            eta=eta_value,
            notes=str(form.get("notes") or ""),
            admin_username=request.session.get("admin_username", ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not updated:
        raise HTTPException(404, "Shipment not found")
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/admin/tracking/{shipment_id}", status_code=302)


# ─── Admin Brands ─────────────────────────────────────────────────────────────

@app.get("/admin/brands", response_class=HTMLResponse, tags=["Admin"], summary="Admin brands management")
def admin_brands(request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    brands = brand_service.list_all(db)
    brand_rows = []
    for b in brands:
        brand_rows.append({
            "slug": b.slug, "name": b.name, "language": b.language,
            "description": b.description,
            "chunks": db.query(models.Chunk).filter_by(brand_id=b.id).count(),
            "convs": db.query(models.Conversation).filter_by(brand_id=b.id).count(),
            "leads": db.query(models.Lead).filter_by(brand_id=b.id).count(),
            "created_at": b.created_at.strftime("%Y-%m-%d"),
        })
    success = request.session.pop("success", "")
    error = request.session.pop("error", "")
    return HTMLResponse(_jinja_env.get_template("admin_brands.html").render(
        brands=brand_rows, success=success, error=error,
    ))


@app.post("/admin/brands/create", tags=["Admin"], summary="Admin brand create")
async def admin_brand_create(request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    form = await request.form()
    slug = str(form.get("slug", "")).strip()
    name = str(form.get("name", "")).strip()
    language = str(form.get("language", "en")).strip()
    description = str(form.get("description", "")).strip()
    if not slug or not name:
        request.session["error"] = "Slug and name are required"
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/admin/brands", status_code=302)
    existing = db.query(models.Brand).filter_by(slug=slug).first()
    if existing:
        request.session["error"] = f"Brand '{slug}' already exists"
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/admin/brands", status_code=302)
    brand_service.create(db, slug, name, description, language)
    request.session["success"] = f"Brand '{slug}' created"
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/admin/brands", status_code=302)


@app.post("/admin/brands/{slug}/edit", tags=["Admin"], summary="Admin brand update")
async def admin_brand_edit(slug: str, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    brand = _get_brand(slug, db)
    form = await request.form()
    name = str(form.get("name", "")).strip()
    language = str(form.get("language", "en")).strip()
    description = str(form.get("description", "")).strip()
    if name:
        brand_service.update(db, brand, name=name, description=description, language=language)
        request.session["success"] = f"Brand '{slug}' updated"
    else:
        request.session["error"] = "Name is required"
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/admin/brands", status_code=302)


@app.get("/admin/brands/{slug}/sources", response_class=HTMLResponse, tags=["Admin"], summary="Admin brand sources")
def admin_brand_sources(slug: str, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    brand = _get_brand(slug, db)
    sources = db.query(models.KnowledgeSource).filter_by(brand_id=brand.id).order_by(models.KnowledgeSource.created_at.desc()).all()
    source_rows = []
    for s in sources:
        source_rows.append({
            "id": s.id,
            "name": s.name,
            "source_type": s.source_type,
            "version": s.version,
            "is_active": s.is_active,
            "chunk_count": s.chunk_count,
            "created_at": s.created_at.strftime("%Y-%m-%d %H:%M"),
            "can_rollback": bool(s.is_active and s.previous_source_id),
        })
    success = request.session.pop("success", "")
    error = request.session.pop("error", "")
    return HTMLResponse(_jinja_env.get_template("admin_sources.html").render(
        brand_slug=slug, sources=source_rows, success=success, error=error,
    ))


@app.post("/admin/brands/{slug}/sources/{source_id}/rollback", tags=["Admin"], summary="Admin source rollback")
def admin_source_rollback(slug: str, source_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    brand = _get_brand(slug, db)
    source = db.query(models.KnowledgeSource).filter_by(id=source_id, brand_id=brand.id).first()
    if not source:
        raise HTTPException(404, "Source not found")
    if not source.previous_source_id:
        request.session["error"] = "No previous version to roll back to"
        from fastapi.responses import RedirectResponse
        return RedirectResponse(f"/admin/brands/{slug}/sources", status_code=302)
    prev = db.query(models.KnowledgeSource).filter_by(id=source.previous_source_id).first()
    if not prev:
        request.session["error"] = "Previous source version not found"
        from fastapi.responses import RedirectResponse
        return RedirectResponse(f"/admin/brands/{slug}/sources", status_code=302)
    source.is_active = False
    prev.is_active = True
    db.commit()
    from app.hybrid_retriever import invalidate_retriever
    invalidate_retriever(slug)
    request.session["success"] = f"Rolled back to version {prev.version}"
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/admin/brands/{slug}/sources", status_code=302)


@app.get("/admin/brands/{slug}/leads", response_class=HTMLResponse, tags=["Admin"], summary="Admin brand leads")
def admin_brand_leads(slug: str, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    _get_brand(slug, db)
    leads = db.query(models.Lead).filter_by(brand_id=db.query(models.Brand).filter_by(slug=slug).first().id).order_by(models.Lead.created_at.desc()).all()
    return HTMLResponse(_jinja_env.get_template("admin_leads.html").render(
        brand_slug=slug, leads=leads,
    ))


@app.get("/admin/brands/{slug}/conversations", response_class=HTMLResponse, tags=["Admin"], summary="Admin brand conversations")
def admin_brand_conversations(slug: str, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    brand = _get_brand(slug, db)
    convs = db.query(models.Conversation).filter_by(brand_id=brand.id).order_by(models.Conversation.created_at.desc()).all()
    conv_rows = []
    for c in convs:
        summary = ""
        try:
            summary_data = json.loads(c.summary_json) if c.summary_json else {}
            summary = summary_data.get("summary", "")
        except (json.JSONDecodeError, TypeError):
            summary = ""
        msgs = [{"role": m.role, "content": m.content[:200]} for m in c.messages]
        conv_rows.append({
            "session_id": c.session_id,
            "msg_count": len(c.messages),
            "summary": summary,
            "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
            "messages": msgs,
        })
    return HTMLResponse(_jinja_env.get_template("admin_conversations.html").render(
        brand_slug=slug, conversations=conv_rows,
    ))


@app.post("/admin/login", tags=["Admin"], summary="Admin login")
@limiter.limit("5/minute")
async def admin_login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")
    if auth_service.authenticate(db, username, password):
        request.session["admin_logged_in"] = True
        request.session["admin_username"] = username
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/admin", status_code=302)
    return HTMLResponse(_jinja_env.get_template("admin_login.html").render(error="Invalid credentials"), status_code=401)


@app.post("/admin/logout", tags=["Admin"], summary="Admin logout")
def admin_logout(request: Request):
    request.session.clear()
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/admin", status_code=302)

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

from fastapi import (
    FastAPI, Depends, HTTPException, Request, UploadFile, File, Form,
    status, Query, BackgroundTasks,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app import models
from app.config import get_settings
from app.db import get_db, init_db, SessionLocal
from app.schemas import (
    ChatRequest, ChatResponse,
    LeadCreate, LeadOut,
    EventCreate,
    TextIngestRequest, CrawlRequest, FAQIngestRequest, IngestResponse,
    ConversationOut, MessageOut,
    BrandCreate, BrandOut,
    SourceOut, AnalyticsSummary,
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

app = FastAPI(title="Agentic RAG Platform", version="2.0.0")

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

@app.get("/health")
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


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/ready")
def readiness():
    if _started:
        return {"ready": True}
    return JSONResponse(status_code=503, content={"ready": False, "error": _startup_error or "starting"})


@app.get("/api/{brand_slug}/health")
def brand_health(brand_slug: str, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    from app.chroma_client import collection_count
    return {
        "status": "ok",
        "brand": brand.slug,
        "chunk_count": collection_count(brand.slug),
    }


# ─── Chat ─────────────────────────────────────────────────────────────────────

@app.post("/api/{brand_slug}/chat", response_model=ChatResponse)
async def chat(brand_slug: str, req: ChatRequest, db: Session = Depends(get_db)):
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
    return ChatResponse(**result)


# ─── Lead capture ─────────────────────────────────────────────────────────────

@app.post("/api/{brand_slug}/lead", response_model=LeadOut)
def capture_lead(brand_slug: str, lead: LeadCreate, db: Session = Depends(get_db)):
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

@app.post("/api/{brand_slug}/event")
def track_event(brand_slug: str, event: EventCreate, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    AnalyticsService.log_event(db, brand.id, event.event_type, event.session_id, event.payload)
    return {"ok": True}


# Tracking

@app.post("/api/{brand_slug}/tracking/lookup", response_model=TrackingLookupResponse)
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


@app.get("/api/{brand_slug}/tracking/shipments", response_model=TrackingSearchResponse)
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


@app.get("/api/{brand_slug}/tracking/shipments/{shipment_id}", response_model=TrackingAdminShipmentOut)
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


@app.post("/api/{brand_slug}/tracking/shipments/{shipment_id}/refresh", response_model=TrackingAdminShipmentOut)
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


@app.post("/api/{brand_slug}/tracking/shipments/{shipment_id}/recalculate-eta", response_model=TrackingEtaResponse)
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


@app.post("/api/{brand_slug}/tracking/shipments/{shipment_id}/override", response_model=TrackingAdminShipmentOut)
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

@app.post("/api/{brand_slug}/ingest/text", response_model=IngestResponse)
def ingest_text(
    brand_slug: str,
    req: TextIngestRequest,
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

@app.post("/api/{brand_slug}/ingest/pdf", response_model=IngestResponse)
async def ingest_pdf(
    brand_slug: str,
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

@app.post("/api/{brand_slug}/ingest/faq", response_model=IngestResponse)
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

@app.post("/api/{brand_slug}/crawl", response_model=IngestResponse)
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

@app.get("/api/{brand_slug}/conversations/{session_id}", response_model=ConversationOut)
def get_conversation(brand_slug: str, session_id: str, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    conv = db.query(models.Conversation).filter_by(brand_id=brand.id, session_id=session_id).first()
    if not conv:
        return ConversationOut(session_id=session_id, messages=[])
    msgs = [MessageOut.model_validate(m) for m in conv.messages]
    return ConversationOut(session_id=session_id, messages=msgs)


# ─── Brand listing / creation ─────────────────────────────────────────────────

@app.get("/api/brands", response_model=list[BrandOut])
@app.get("/api/{brand_slug}/brands", response_model=list[BrandOut])
def list_brands(db: Session = Depends(get_db), brand_slug: str = "default"):
    return brand_service.list_all(db)


@app.post("/api/brands", response_model=BrandOut)
def create_brand(req: BrandCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Brand).filter_by(slug=req.slug).first()
    if existing:
        raise HTTPException(409, f"Brand '{req.slug}' already exists")
    return brand_service.create(db, req.slug, req.name, req.description)


# ─── Sources & leads ──────────────────────────────────────────────────────────

@app.get("/api/{brand_slug}/sources", response_model=list[SourceOut])
def list_sources(brand_slug: str, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    return db.query(models.KnowledgeSource).filter_by(brand_id=brand.id).all()


@app.get("/api/{brand_slug}/leads", response_model=list[LeadOut])
def list_leads(brand_slug: str, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    return db.query(models.Lead).filter_by(brand_id=brand.id).order_by(models.Lead.created_at.desc()).all()


# ─── Analytics summary ────────────────────────────────────────────────────────

@app.get("/api/{brand_slug}/analytics", response_model=AnalyticsSummary)
def get_analytics(brand_slug: str, db: Session = Depends(get_db)):
    brand = _get_brand(brand_slug, db)
    return analytics_service.get_summary(db, brand)


# ─────────────────────────────────────────────────────────────────────────────
# Widget frontend
# ─────────────────────────────────────────────────────────────────────────────




@app.get("/widget/{brand_slug}", response_class=HTMLResponse)
def widget(brand_slug: str, db: Session = Depends(get_db)):
    _get_brand(brand_slug, db)  # 404 if not found
    return HTMLResponse(_load_template("widget.html").format(brand=brand_slug))


@app.get("/widget.js")
def widget_js():
    js = """
(function() {
  const brand = document.currentScript.dataset.brand || "default";
  const iframe = document.createElement("iframe");
  iframe.src = `/widget/${brand}`;
  iframe.style.cssText = "position:fixed;bottom:20px;right:20px;width:420px;height:600px;border:none;border-radius:12px;box-shadow:0 8px 40px rgba(0,0,0,.4);z-index:9999";
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

    brand_rows = ""
    for b in brands:
        chunk_c = db.query(models.Chunk).filter_by(brand_id=b.id).count()
        conv_c = db.query(models.Conversation).filter_by(brand_id=b.id).count()
        lead_c = db.query(models.Lead).filter_by(brand_id=b.id).count()
        brand_rows += f"""
        <tr>
          <td><code>{b.slug}</code></td>
          <td>{b.name}</td>
          <td>{chunk_c}</td>
          <td>{conv_c}</td>
          <td>{lead_c}</td>
          <td><a href="/widget/{b.slug}" target="_blank">Open widget ↗</a></td>
        </tr>"""

    # Recent messages
    recent = (
        db.query(models.Message)
        .order_by(models.Message.created_at.desc())
        .limit(10)
        .all()
    )
    recent_rows = ""
    for m in recent:
        conv = db.query(models.Conversation).get(m.conversation_id)
        brand_slug = db.query(models.Brand).get(conv.brand_id).slug if conv else "-"
        snippet = m.content[:80].replace("<", "&lt;").replace(">", "&gt;")
        recent_rows += f"""
        <tr>
          <td><code>{brand_slug}</code></td>
          <td><span class="role {m.role}">{m.role}</span></td>
          <td>{snippet}{"…" if len(m.content)>80 else ""}</td>
          <td>{m.created_at.strftime("%H:%M %d %b")}</td>
        </tr>"""

    recent_shipments = tracking_service.search_shipments(db, query="", limit=10)
    shipment_rows = ""
    for shipment in recent_shipments:
        current_hub = shipment.current_hub.hub_name if shipment.current_hub else "-"
        shipment_rows += f"""
        <tr>
          <td><code>{shipment.brand.slug}</code></td>
          <td>{shipment.order.order_id}</td>
          <td><code>{shipment.tracking_number}</code></td>
          <td>{tracking_service.status_label(shipment.current_status)}</td>
          <td>{current_hub}</td>
          <td>{shipment.eta_date or "-"}</td>
          <td><a href="/admin/tracking/{shipment.id}">View</a></td>
        </tr>"""

    error_html = '<div class="error">' + error + "</div>" if error else ""
    if not shipment_rows:
        shipment_rows = '<tr><td colspan="7" style="color:var(--dim);text-align:center;padding:24px">No shipments yet</td></tr>'
    if not recent_rows:
        recent_rows = '<tr><td colspan="4" style="color:var(--dim);text-align:center;padding:24px">No messages yet</td></tr>'
    return _load_template("admin_dashboard.html").format(
        error_html=error_html,
        len_brands=len(brands),
        total_chunks=total_chunks,
        total_convs=total_convs,
        total_msgs=total_msgs,
        total_leads=total_leads,
        total_events=total_events,
        total_shipments=tracking_stats['total_shipments'],
        delayed_shipments=tracking_stats['delayed_shipments'],
        brand_rows=brand_rows,
        shipment_rows=shipment_rows,
        recent_rows=recent_rows,
    )


def _html_escape(value: object) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _admin_tracking_html(db: Session, query: str = "", brand_slug: str = "") -> str:
    brands = brand_service.list_all(db)
    selected_brand = None
    if brand_slug:
        selected_brand = db.query(models.Brand).filter_by(slug=brand_slug).first()

    shipments = tracking_service.search_shipments(db, brand=selected_brand, query=query, limit=100)
    stats = tracking_service.get_tracking_analytics(db, selected_brand)

    brand_options = '<option value="">All brands</option>'
    for brand in brands:
        selected = "selected" if brand.slug == brand_slug else ""
        brand_options += f'<option value="{_html_escape(brand.slug)}" {selected}>{_html_escape(brand.slug)}</option>'

    rows = ""
    for shipment in shipments:
        current_hub = shipment.current_hub.hub_name if shipment.current_hub else "-"
        rows += f"""
        <tr>
          <td><code>{_html_escape(shipment.brand.slug)}</code></td>
          <td>{_html_escape(shipment.order.order_id)}</td>
          <td><code>{_html_escape(shipment.tracking_number)}</code></td>
          <td>{_html_escape(tracking_service.status_label(shipment.current_status))}</td>
          <td>{_html_escape(current_hub)}</td>
          <td>{_html_escape(shipment.current_location_text or "-")}</td>
          <td>{_html_escape(shipment.eta_date or "-")}</td>
          <td><a href="/admin/tracking/{shipment.id}">View</a></td>
        </tr>"""

    hub_rows = ""
    for hub_name, count in stats["common_hubs"]:
        hub_rows += f"<tr><td>{_html_escape(hub_name)}</td><td>{count}</td></tr>"

    if not rows:
        rows = '<tr><td colspan="8" style="color:#777;text-align:center;padding:24px">No shipments found</td></tr>'
    if not hub_rows:
        hub_rows = '<tr><td colspan="2" style="color:#777;text-align:center;padding:24px">No hub data yet</td></tr>'
    return _load_template("admin_tracking.html").format(
        search_query=_html_escape(query),
        brand_options=brand_options,
        total_shipments=stats['total_shipments'],
        active_shipments=stats['active_shipments'],
        delivered_shipments=stats['delivered_shipments'],
        delayed_shipments=stats['delayed_shipments'],
        delay_percentage=stats['delay_percentage'],
        tracking_requests=stats['tracking_requests'],
        rows=rows,
        hub_rows=hub_rows,
    )


def _admin_tracking_detail_html(db: Session, shipment: models.Shipment) -> str:
    detail = tracking_service.shipment_to_admin_dict(db, shipment)
    event_rows = ""
    for event in detail["events"]:
        hub = event["hub"]["hub_name"] if event.get("hub") else "-"
        event_rows += f"""
        <tr>
          <td>{_html_escape(event['event_timestamp'])}</td>
          <td>{_html_escape(tracking_service.status_label(event['normalized_status']))}</td>
          <td>{_html_escape(hub)}</td>
          <td>{_html_escape(event['location_text'])}</td>
          <td>{_html_escape(event['notes'])}</td>
        </tr>"""

    statuses = (
        "order_created", "picked_up", "at_origin_hub", "in_transit",
        "at_intermediate_hub", "at_destination_hub", "out_for_delivery",
        "delivered", "delayed", "failed_delivery", "returned", "cancelled",
    )
    status_options = ""
    for status_value in statuses:
        selected = "selected" if status_value == shipment.current_status else ""
        status_options += f'<option value="{status_value}" {selected}>{tracking_service.status_label(status_value)}</option>'

    eta_value = shipment.eta_date.isoformat() if shipment.eta_date else ""
    current_hub = shipment.current_hub.hub_name if shipment.current_hub else "-"
    previous_hub = shipment.previous_hub.hub_name if shipment.previous_hub else "-"
    next_hub = shipment.next_hub.hub_name if shipment.next_hub else "-"

    if not event_rows:
        event_rows = '<tr><td colspan="5" style="color:#777;text-align:center;padding:24px">No events yet</td></tr>'
    return _load_template("admin_tracking_detail.html").format(
        shipment_id=shipment.id,
        brand_slug=_html_escape(shipment.brand.slug),
        order_id=_html_escape(shipment.order.order_id),
        tracking_number=_html_escape(shipment.tracking_number),
        status_label=_html_escape(tracking_service.status_label(shipment.current_status)),
        current_hub=_html_escape(current_hub),
        previous_hub=_html_escape(previous_hub),
        next_hub=_html_escape(next_hub),
        eta=_html_escape(shipment.eta_date or "-"),
        status_options=status_options,
        eta_value_input=_html_escape(eta_value),
        event_rows=event_rows,
    )





@app.get("/admin", response_class=HTMLResponse)
def admin_get(request: Request, db: Session = Depends(get_db)):
    if not request.session.get("admin_logged_in"):
        return HTMLResponse(_load_template("login.html").format(error=""))
    return HTMLResponse(_admin_dashboard_html(db))


@app.get("/admin/tracking", response_class=HTMLResponse)
def admin_tracking_get(
    request: Request,
    q: str = "",
    brand: str = "",
    db: Session = Depends(get_db),
):
    if not request.session.get("admin_logged_in"):
        return HTMLResponse(_load_template("login.html").format(error=""))
    return HTMLResponse(_admin_tracking_html(db, query=q, brand_slug=brand))


@app.get("/admin/tracking/{shipment_id}", response_class=HTMLResponse)
def admin_tracking_detail_get(
    shipment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    if not request.session.get("admin_logged_in"):
        return HTMLResponse(_load_template("login.html").format(error=""))
    shipment = db.query(models.Shipment).filter_by(id=shipment_id).first()
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    return HTMLResponse(_admin_tracking_detail_html(db, shipment))


@app.post("/admin/tracking/{shipment_id}/refresh")
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


@app.post("/admin/tracking/{shipment_id}/recalculate-eta")
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


@app.post("/admin/tracking/{shipment_id}/override")
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


@app.post("/admin/login")
async def admin_login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")
    if auth_service.authenticate(db, username, password):
        request.session["admin_logged_in"] = True
        request.session["admin_username"] = username
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/admin", status_code=302)
    return HTMLResponse(_load_template("login.html").format(error='<div class="err">Invalid credentials</div>'), status_code=401)


@app.post("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/admin", status_code=302)

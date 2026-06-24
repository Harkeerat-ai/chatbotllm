from __future__ import annotations
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Chat ────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(description="User message text")
    session_id: str = Field("default", description="Client-provided session identifier for conversation continuity")
    top_k: int = Field(10, description="Number of documents to retrieve from the knowledge base", ge=1, le=50)
    stream: bool = Field(False, description="If true, use SSE streaming response")
    allow_unverified_tracking: Optional[bool] = Field(None, description="Override the per-brand tracking verification setting")

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be empty")
        return v.strip()


class SourceCitation(BaseModel):
    source_name: str
    snippet: str = ""


class FeedbackCreate(BaseModel):
    message_id: int = Field(description="ID of the assistant message to rate")
    rating: int = Field(description="1 for thumbs up, -1 for thumbs down")
    feedback_text: str = Field("", description="Optional free-text feedback")
    session_id: str = Field("", description="Session identifier for analytics attribution")


class ChatResponse(BaseModel):
    brand: str = Field(description="Brand slug")
    session_id: str = Field(description="Conversation session identifier")
    answer: str = Field(description="Generated response text")
    message_id: int = Field(0, description="ID of the assistant message, used for feedback and suggestions")
    sources: list[str] = Field([], description="Source names used to generate the answer")
    citations: list[SourceCitation] = Field([], description="Top source snippets cited in the response")
    urls: list[dict] = Field([], description="Relevant product page URLs discovered during the request")
    latency_ms: int = Field(0, description="Total request latency in milliseconds")


# ── Lead capture ─────────────────────────────────────────────────────────────

class LeadCreate(BaseModel):
    name: str = Field("", description="Customer name")
    email: str = Field("", description="Customer email address")
    phone: str = Field("", description="Customer phone number")
    company: str = Field("", description="Customer company name")
    notes: str = Field("", description="Additional notes about the lead")
    source: str = Field("widget", description="Lead source (widget, api, manual)")
    session_id: str = Field("", description="Session identifier from the chat widget")


class LeadOut(BaseModel):
    id: int
    name: str
    email: str
    phone: str
    company: str
    notes: str
    source: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Analytics ─────────────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    event_type: str
    session_id: str = ""
    payload: dict[str, Any] = {}


class AnalyticsSummary(BaseModel):
    brand: str
    total_chats: int
    total_leads: int
    total_custom_events: int
    event_breakdown: dict[str, int]


class AnalyticsTimeSeries(BaseModel):
    date: str
    count: int


class AnalyticsBreakdown(BaseModel):
    event_type: str
    count: int


class AnalyticsDetailed(BaseModel):
    brand: str
    total_chats: int
    total_leads: int
    total_events: int
    avg_latency_ms: float
    chats_over_time: list[AnalyticsTimeSeries]
    event_breakdown: list[AnalyticsBreakdown]
    latency_trend: list[AnalyticsTimeSeries]


# Tracking

class HubOut(BaseModel):
    id: int
    hub_code: str
    hub_name: str
    city: str = ""
    state: str = ""
    country: str = "India"

    model_config = {"from_attributes": True}


class TrackingEventOut(BaseModel):
    id: int
    status: str
    normalized_status: str
    raw_provider_status: str = ""
    location_text: str = ""
    event_timestamp: datetime
    notes: str = ""
    hub: Optional[HubOut] = None

    model_config = {"from_attributes": True}


class TrackingLookupRequest(BaseModel):
    lookup_type: str = "auto"
    lookup_value: str
    customer_verification: str = ""
    session_id: str = ""
    source: str = "tracking_page"
    force_refresh: bool = False
    allow_unverified: Optional[bool] = None

    @field_validator("lookup_type")
    @classmethod
    def valid_lookup_type(cls, v: str) -> str:
        value = v.strip().lower()
        if value not in {"auto", "order_id", "tracking_number"}:
            raise ValueError("lookup_type must be auto, order_id, or tracking_number")
        return value

    @field_validator("lookup_value")
    @classmethod
    def lookup_value_not_empty(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("lookup_value must not be empty")
        return value


class TrackingLookupResponse(BaseModel):
    success: bool
    brand: str
    order_id: str = ""
    shipment_id: str = ""
    tracking_number: str = ""
    shipment_status: str = ""
    status_label: str = ""
    current_hub: Optional[HubOut] = None
    previous_hub: Optional[HubOut] = None
    next_hub: Optional[HubOut] = None
    current_location: str = ""
    last_updated: Optional[datetime] = None
    eta: Optional[date] = None
    delivered_on: Optional[date] = None
    delay_reason: str = ""
    confidence: str = ""
    message_template_key: str = ""
    safe_response_text: str
    timeline: list[TrackingEventOut] = []
    error_code: str = ""
    retry_allowed: bool = False
    requires_customer_verification: bool = False


class TrackingAdminShipmentOut(BaseModel):
    id: int
    brand: str
    order_id: str
    shipment_id: str
    tracking_number: str
    current_status: str
    status_label: str
    current_location: str = ""
    current_hub: Optional[HubOut] = None
    previous_hub: Optional[HubOut] = None
    next_hub: Optional[HubOut] = None
    eta: Optional[date] = None
    delivered_at: Optional[datetime] = None
    delay_reason: str = ""
    last_provider_sync_at: Optional[datetime] = None
    events: list[TrackingEventOut] = []


class TrackingSearchResponse(BaseModel):
    items: list[TrackingAdminShipmentOut]
    count: int


class TrackingOverrideRequest(BaseModel):
    status: str
    eta: Optional[date] = None
    notes: str = ""


class TrackingEtaResponse(BaseModel):
    shipment_id: int
    eta: Optional[date] = None
    confidence: str = ""
    source: str = ""
    reason: str = ""


# ── Ingestion ─────────────────────────────────────────────────────────────────

class TextIngestRequest(BaseModel):
    source_name: str
    content: str
    metadata: dict[str, Any] = {}


class FAQItem(BaseModel):
    question: str
    answer: str
    category: str = ""


class FAQIngestRequest(BaseModel):
    source_name: str
    items: list[FAQItem]


class CrawlRequest(BaseModel):
    url: str
    max_pages: int = 10
    max_depth: int = 1
    same_domain_only: bool = True

    @field_validator("url")
    @classmethod
    def validate_url_scheme_and_host(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("Only http and https URLs are allowed")
        if not parsed.netloc:
            raise ValueError("URL must have a valid host")
        return v


class IngestResponse(BaseModel):
    source_id: int
    source_name: str
    chunk_count: int
    message: str


# ── Conversation ──────────────────────────────────────────────────────────────

class MessageOut(BaseModel):
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    session_id: str
    messages: list[MessageOut]

    model_config = {"from_attributes": True}


# ── Brand ─────────────────────────────────────────────────────────────────────

class WidgetConfig(BaseModel):
    accent_color: str = Field("#f0a500", description="Accent color for buttons and highlights (CSS hex)")
    bg_color: str = Field("#0d0d0d", description="Main background color (CSS hex)")
    surface_color: str = Field("#161616", description="Card/surface background color (CSS hex)")
    border_color: str = Field("#2a2a2a", description="Border color for UI elements (CSS hex)")
    text_color: str = Field("#e8e8e8", description="Primary text color (CSS hex)")
    text_dim_color: str = Field("#888", description="Muted / secondary text color (CSS hex)")
    user_bg_color: str = Field("#1e1e1e", description="User message bubble background (CSS hex)")
    bot_bg_color: str = Field("#111", description="Bot message bubble background (CSS hex)")
    logo_url: str = Field("", description="URL to brand logo image shown in widget header")
    title: str = Field("", description="Widget header title (falls back to brand name)")
    welcome_message: str = Field("", description="Initial greeting message shown in widget")
    position: str = Field("bottom-right", description="Widget position on screen (bottom-right, bottom-left)")
    width: str = Field("420px", description="Widget container width (CSS value)")
    height: str = Field("600px", description="Widget container height (CSS value)")


class BrandCreate(BaseModel):
    slug: str
    name: str
    description: str = ""
    language: str = "en"


class BrandOut(BaseModel):
    id: int
    slug: str
    name: str
    description: str
    language: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Source ────────────────────────────────────────────────────────────────────

class SourceOut(BaseModel):
    id: int = Field(description="Knowledge source ID")
    name: str = Field(description="Source name")
    source_type: str = Field(description="Source type: text, pdf, faq, legal, kb, page")
    uri: str = Field(description="Source file path or URL")
    chunk_count: int = Field(description="Number of chunks indexed from this source")
    version: int = Field(1, description="Source version number (increments on re-ingestion)")
    is_active: bool = Field(True, description="Whether this source version is currently active")
    previous_source_id: int | None = Field(None, description="ID of the previous version, if any")
    created_at: datetime = Field(description="Source creation timestamp")

    model_config = {"from_attributes": True}

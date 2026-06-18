from __future__ import annotations
from datetime import date, datetime
from typing import Any, Optional
from pydantic import BaseModel, EmailStr, field_validator


# ── Chat ────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    top_k: int = 10
    stream: bool = False
    allow_unverified_tracking: Optional[bool] = None

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be empty")
        return v.strip()


class ChatResponse(BaseModel):
    brand: str
    session_id: str
    answer: str
    sources: list[str] = []
    urls: list[dict] = []
    latency_ms: int = 0


# ── Lead capture ─────────────────────────────────────────────────────────────

class LeadCreate(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    company: str = ""
    notes: str = ""
    source: str = "widget"
    session_id: str = ""


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

class BrandCreate(BaseModel):
    slug: str
    name: str
    description: str = ""


class BrandOut(BaseModel):
    id: int
    slug: str
    name: str
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Source ────────────────────────────────────────────────────────────────────

class SourceOut(BaseModel):
    id: int
    name: str
    source_type: str
    uri: str
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}

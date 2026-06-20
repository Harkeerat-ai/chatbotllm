from datetime import datetime, timedelta
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date,
    ForeignKey, Boolean, Float, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.db import Base


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    widget_config_json = Column(Text, default="{}")
    language = Column(String(10), default="en")
    created_at = Column(DateTime, default=datetime.utcnow)

    sources = relationship("KnowledgeSource", back_populates="brand", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="brand", cascade="all, delete-orphan")
    leads = relationship("Lead", back_populates="brand", cascade="all, delete-orphan")
    analytics = relationship("AnalyticsEvent", back_populates="brand", cascade="all, delete-orphan")
    chunks = relationship("Chunk", back_populates="brand", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="brand", cascade="all, delete-orphan")
    shipments = relationship("Shipment", back_populates="brand", cascade="all, delete-orphan")
    tracking_requests = relationship("TrackingRequest", back_populates="brand", cascade="all, delete-orphan")
    product_pages = relationship("ProductPage", back_populates="brand", cascade="all, delete-orphan")


class ProductPage(Base):
    __tablename__ = "product_pages"

    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    slug = Column(String(128), index=True, nullable=False)
    url = Column(Text, nullable=False)
    title = Column(String(256), default="")
    keywords = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    brand = relationship("Brand", back_populates="product_pages")


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    name = Column(String(256), nullable=False)
    source_type = Column(String(32), nullable=False)  # pdf | text | faq | crawl
    uri = Column(Text, default="")                     # file path or URL
    chunk_count = Column(Integer, default=0)
    version = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    previous_source_id = Column(Integer, ForeignKey("knowledge_sources.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    brand = relationship("Brand", back_populates="sources")
    chunks = relationship("Chunk", back_populates="source", cascade="all, delete-orphan")
    previous_source = relationship("KnowledgeSource", remote_side=[id], backref="next_versions")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("knowledge_sources.id"), nullable=True)
    chroma_id = Column(String(128), unique=True, index=True)
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

    brand = relationship("Brand", back_populates="chunks")
    source = relationship("KnowledgeSource", back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    session_id = Column(String(128), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    summary_json = Column(Text, default="{}")

    brand = relationship("Brand", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")
    context = relationship("ConversationContext", back_populates="conversation", uselist=False, cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(16), nullable=False)   # user | assistant
    content = Column(Text, nullable=False)
    token_count = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    suggested_questions_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    session_id = Column(String(128), index=True, default="")
    name = Column(String(128), default="")
    email = Column(String(256), index=True, default="")
    phone = Column(String(64), default="")
    company = Column(String(128), default="")
    notes = Column(Text, default="")
    source = Column(String(64), default="widget")
    created_at = Column(DateTime, default=datetime.utcnow)

    brand = relationship("Brand", back_populates="leads")


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    event_type = Column(String(64), index=True, nullable=False)  # chat | lead | custom
    session_id = Column(String(128), default="")
    payload_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

    brand = relationship("Brand", back_populates="analytics")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    hashed_password = Column(String(256), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String(256), unique=True, index=True, nullable=False)
    label = Column(String(128), default="")
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LogisticsProvider(Base):
    __tablename__ = "logistics_providers"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    provider_type = Column(String(32), default="mock")  # mock | http
    base_url = Column(Text, default="")
    api_key_env = Column(String(128), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    hubs = relationship("HubMaster", back_populates="provider", cascade="all, delete-orphan")
    shipments = relationship("Shipment", back_populates="provider")


class HubMaster(Base):
    __tablename__ = "hub_master"
    __table_args__ = (
        UniqueConstraint("provider_id", "hub_code", name="uq_provider_hub_code"),
    )

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("logistics_providers.id"), nullable=False)
    hub_code = Column(String(64), index=True, nullable=False)
    hub_name = Column(String(128), nullable=False)
    city = Column(String(96), index=True, default="")
    state = Column(String(96), default="")
    country = Column(String(96), default="India")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    provider = relationship("LogisticsProvider", back_populates="hubs")


class HubRoute(Base):
    __tablename__ = "hub_routes"
    __table_args__ = (
        UniqueConstraint("provider_id", "origin_hub_id", "destination_hub_id", name="uq_provider_hub_route"),
    )

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("logistics_providers.id"), nullable=False)
    origin_hub_id = Column(Integer, ForeignKey("hub_master.id"), nullable=False)
    destination_hub_id = Column(Integer, ForeignKey("hub_master.id"), nullable=False)
    avg_transit_hours = Column(Integer, default=24)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    provider = relationship("LogisticsProvider")
    origin_hub = relationship("HubMaster", foreign_keys=[origin_hub_id])
    destination_hub = relationship("HubMaster", foreign_keys=[destination_hub_id])


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("brand_id", "order_id", name="uq_brand_order_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    order_id = Column(String(96), index=True, nullable=False)
    customer_email_hash = Column(String(128), index=True, default="")
    customer_phone_hash = Column(String(128), index=True, default="")
    order_status = Column(String(64), default="order_created")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    brand = relationship("Brand", back_populates="orders")
    shipments = relationship("Shipment", back_populates="order", cascade="all, delete-orphan")


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("brand_id", "tracking_number", name="uq_brand_tracking_number"),
        UniqueConstraint("provider_id", "shipment_id", name="uq_provider_shipment_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    provider_id = Column(Integer, ForeignKey("logistics_providers.id"), nullable=False)
    shipment_id = Column(String(96), index=True, nullable=False)
    tracking_number = Column(String(96), index=True, nullable=False)
    current_status = Column(String(64), index=True, default="order_created")
    current_hub_id = Column(Integer, ForeignKey("hub_master.id"), nullable=True)
    previous_hub_id = Column(Integer, ForeignKey("hub_master.id"), nullable=True)
    next_hub_id = Column(Integer, ForeignKey("hub_master.id"), nullable=True)
    current_location_text = Column(Text, default="")
    eta_date = Column(Date, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    delay_reason = Column(Text, default="")
    verification_required = Column(Boolean, default=False)
    last_provider_sync_at = Column(DateTime, nullable=True)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    brand = relationship("Brand", back_populates="shipments")
    order = relationship("Order", back_populates="shipments")
    provider = relationship("LogisticsProvider", back_populates="shipments")
    current_hub = relationship("HubMaster", foreign_keys=[current_hub_id])
    previous_hub = relationship("HubMaster", foreign_keys=[previous_hub_id])
    next_hub = relationship("HubMaster", foreign_keys=[next_hub_id])
    events = relationship("TrackingEvent", back_populates="shipment", cascade="all, delete-orphan", order_by="TrackingEvent.event_timestamp")
    etas = relationship("ShipmentEta", back_populates="shipment", cascade="all, delete-orphan")
    overrides = relationship("TrackingOverride", back_populates="shipment", cascade="all, delete-orphan")


class TrackingEvent(Base):
    __tablename__ = "tracking_events"
    __table_args__ = (
        UniqueConstraint("shipment_id", "provider_event_id", name="uq_shipment_provider_event"),
    )

    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"), nullable=False)
    status = Column(String(64), index=True, nullable=False)
    normalized_status = Column(String(64), index=True, nullable=False)
    raw_provider_status = Column(String(128), default="")
    hub_id = Column(Integer, ForeignKey("hub_master.id"), nullable=True)
    location_text = Column(Text, default="")
    event_timestamp = Column(DateTime, index=True, default=datetime.utcnow)
    provider_event_id = Column(String(128), default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    shipment = relationship("Shipment", back_populates="events")
    hub = relationship("HubMaster")


class TrackingCache(Base):
    __tablename__ = "tracking_cache"

    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    lookup_type = Column(String(32), index=True, nullable=False)
    lookup_value_hash = Column(String(128), index=True, nullable=False)
    shipment_id = Column(Integer, ForeignKey("shipments.id"), nullable=True)
    response_snapshot_json = Column(Text, default="{}")
    expires_at = Column(DateTime, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    brand = relationship("Brand")
    shipment = relationship("Shipment")


class ShipmentEta(Base):
    __tablename__ = "shipment_eta"

    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"), nullable=False)
    eta_date = Column(Date, nullable=False)
    source = Column(String(64), default="fallback")  # provider | override | route_history | fallback
    confidence = Column(String(16), default="low")   # high | medium | low
    reason = Column(Text, default="")
    calculated_at = Column(DateTime, default=datetime.utcnow)

    shipment = relationship("Shipment", back_populates="etas")


class TrackingRequest(Base):
    __tablename__ = "tracking_requests"

    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    session_id = Column(String(128), index=True, default="")
    source = Column(String(64), default="chatbot")
    lookup_type = Column(String(32), default="")
    lookup_value_hash = Column(String(128), index=True, default="")
    result_code = Column(String(64), index=True, default="")
    ip_hash = Column(String(128), index=True, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    brand = relationship("Brand", back_populates="tracking_requests")


class TrackingOverride(Base):
    __tablename__ = "tracking_overrides"

    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"), nullable=False)
    admin_username = Column(String(64), default="")
    previous_status = Column(String(64), default="")
    new_status = Column(String(64), default="")
    previous_eta = Column(Date, nullable=True)
    new_eta = Column(Date, nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    shipment = relationship("Shipment", back_populates="overrides")


class MessageFeedback(Base):
    __tablename__ = "message_feedback"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    session_id = Column(String(128), default="")
    rating = Column(Integer, nullable=False)
    feedback_text = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class ConversationContext(Base):
    __tablename__ = "conversation_contexts"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), unique=True, nullable=False)
    state = Column(String(32), default="idle")
    slots_json = Column(Text, default="{}")
    error_info_json = Column(Text, default="{}")
    retry_count = Column(Integer, default=0)
    expired_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="context")

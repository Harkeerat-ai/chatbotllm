"""
tracking_service.py — tracking business logic extracted from services.py.
"""

from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import difflib
import httpx
import requests
from cachetools import TTLCache
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.conversation import state_machine, MAX_TRACKING_RETRIES
from app.ollama_client import ollama
from app.analytics_service import AnalyticsService
from app.brand_service import brand_service
from app.utils import chunk_text, make_chroma_id, slugify

logger = logging.getLogger(__name__)

_LOOKUP_CACHE: TTLCache = TTLCache(maxsize=256, ttl=300)


TRACKING_STATUS_LABELS = {
    "order_created": "Order Created",
    "picked_up": "Picked Up",
    "at_origin_hub": "At Origin Hub",
    "in_transit": "In Transit",
    "at_intermediate_hub": "At Intermediate Hub",
    "at_destination_hub": "At Destination Hub",
    "out_for_delivery": "Out For Delivery",
    "delivered": "Delivered",
    "delayed": "Delayed",
    "failed_delivery": "Failed Delivery",
    "returned": "Returned",
    "cancelled": "Cancelled",
}

TRACKING_TERMINAL_STATES = {"delivered", "returned", "cancelled"}

TRACKING_TRANSITIONS = {
    "order_created": {"picked_up", "cancelled", "delayed"},
    "picked_up": {"at_origin_hub", "in_transit", "delayed", "cancelled"},
    "at_origin_hub": {"in_transit", "delayed", "cancelled"},
    "in_transit": {"at_intermediate_hub", "at_destination_hub", "delayed", "cancelled"},
    "at_intermediate_hub": {"in_transit", "delayed", "cancelled"},
    "at_destination_hub": {"out_for_delivery", "delivered", "delayed", "cancelled"},
    "out_for_delivery": {"delivered", "failed_delivery", "delayed"},
    "failed_delivery": {"out_for_delivery", "returned", "delayed"},
    "delayed": {
        "picked_up",
        "at_origin_hub",
        "in_transit",
        "at_intermediate_hub",
        "at_destination_hub",
        "out_for_delivery",
        "delivered",
        "failed_delivery",
        "returned",
        "cancelled",
    },
    "delivered": set(),
    "returned": set(),
    "cancelled": set(),
}

HUB_STATUSES = {"at_origin_hub", "at_intermediate_hub", "at_destination_hub"}


class TrackingService:
    lookup_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,95}$")
    lookup_token_pattern = re.compile(
        r"\b(?:TRK[-_]?[A-Z0-9-]{3,}|[A-Z]{2,8}[-_][A-Z0-9-]{3,}|\d{6,})\b",
        re.IGNORECASE,
    )
    tracking_intent_patterns = (
        "where is my order",
        "track order",
        "track my order",
        "tracking number",
        "shipment status",
        "shipment update",
        "order update",
        "delivery status",
        "courier status",
        "where is my shipment",
        "has my order shipped",
        "where is my package",
        "parcel status",
        "delivery update",
        "shipment details",
        "courier update",
        "order progress",
        "has it shipped",
        "when will it arrive",
        "delivery date",
        "when is it coming",
        "order tracking",
        "package tracking",
        "shipment tracking",
        "track my package",
        "where my package",
    )
    pending_lookup_phrase = "Please share your order ID or tracking number"

    def ensure_defaults(self, db: Session) -> None:
        """Create local brands, provider, hubs, routes, and demo shipments."""
        for slug in ("biopharma", "building", "kalp", "default"):
            brand_service.get_or_create(db, slug)

        provider = db.query(models.LogisticsProvider).filter_by(slug="local-demo-logistics").first()
        if not provider:
            provider = models.LogisticsProvider(
                slug="local-demo-logistics",
                name="Local Demo Logistics",
                provider_type="mock",
            )
            db.add(provider)
            db.commit()
            db.refresh(provider)

        hubs = self._ensure_default_hubs(db, provider)
        self._ensure_default_routes(db, provider, hubs)
        self._ensure_demo_shipments(db, provider, hubs)

    def should_handle_chat(self, user_message: str, history: list[dict]) -> bool:
        text = user_message.strip().lower()
        if any(pattern in text for pattern in self.tracking_intent_patterns):
            return True
        if "track" in text and ("order" in text or "shipment" in text or "delivery" in text):
            return True
        if self._awaiting_tracking_lookup(history) and self.extract_lookup_value_with_type(user_message)[0]:
            return True
        fuzzy_patterns = ["trackin", "delivery staus", "packge", "shipmnt", "ordr status"]
        for pat in fuzzy_patterns:
            matches = difflib.get_close_matches(pat, text.split(), cutoff=0.8)
            if matches:
                return True
        value, lt, conf = self.extract_lookup_value_with_type(user_message)
        if value and conf >= 60 and len(text.split()) <= 8:
            return True
        return False

    def lookup(
        self,
        db: Session,
        brand: models.Brand,
        lookup_type: str,
        lookup_value: str,
        customer_verification: str = "",
        session_id: str = "",
        source: str = "tracking_page",
        force_refresh: bool = False,
        ip_address: str = "",
        allow_unverified: bool = False,
    ) -> dict[str, Any]:
        lookup_type = (lookup_type or "auto").strip().lower()
        normalized_lookup = self._normalize_lookup_value(lookup_value)
        lookup_hash = self._hash_lookup(brand.slug, lookup_type, normalized_lookup)
        cache_key = f"{brand.slug}:{lookup_type}:{lookup_hash}"
        ip_hash = self._hash_lookup("ip", "ip", ip_address) if ip_address else ""

        if lookup_type not in {"auto", "order_id", "tracking_number"}:
            return self._record_and_error(
                db, brand, session_id, source, lookup_type, lookup_hash, ip_hash,
                "invalid_lookup_type",
                "Please use either an order ID or a tracking number.",
            )

        if not self.lookup_pattern.match(normalized_lookup):
            return self._record_and_error(
                db, brand, session_id, source, lookup_type, lookup_hash, ip_hash,
                "invalid_lookup_value",
                "That does not look like a valid order ID or tracking number. Please check it and try again.",
            )

        if self._is_rate_limited(db, brand, session_id, lookup_hash):
            return self._record_and_error(
                db, brand, session_id, source, lookup_type, lookup_hash, ip_hash,
                "rate_limited",
                "Too many tracking attempts were made recently. Please wait a moment and try again.",
                retry_allowed=True,
            )

        if not force_refresh:
            cached = _LOOKUP_CACHE.get(cache_key)
            if cached is not None:
                response, shipment_id = cached
                self._record_tracking_request(db, brand.id, session_id, source, lookup_type, lookup_hash, "mem_cache_hit", ip_hash)
                try:
                    asyncio.get_running_loop().create_task(
                        self._background_refresh_cache(cache_key, brand, lookup_type, lookup_hash)
                    )
                except RuntimeError:
                    pass
                return response

            cached = self._get_cached_response(db, brand.id, lookup_type, lookup_hash)
            if cached:
                self._record_tracking_request(db, brand.id, session_id, source, lookup_type, lookup_hash, "cache_hit", ip_hash)
                _LOOKUP_CACHE[cache_key] = (cached, cached.get("_shipment_id", 0))
                return cached

        shipment, find_error = self._find_shipment(db, brand, lookup_type, normalized_lookup)
        if find_error:
            return self._record_and_error(
                db, brand, session_id, source, lookup_type, lookup_hash, ip_hash,
                find_error["code"],
                find_error["message"],
                retry_allowed=find_error.get("retry_allowed", False),
            )

        if not shipment:
            return self._record_and_error(
                db, brand, session_id, source, lookup_type, lookup_hash, ip_hash,
                "not_found",
                "I could not find a shipment for that order ID or tracking number.",
            )

        if shipment.verification_required:
            if allow_unverified:
                AnalyticsService.log_event(
                    db,
                    brand.id,
                    "unverified_tracking_disclosed",
                    session_id,
                    {
                        "shipment_id": shipment.id,
                        "lookup_type": lookup_type,
                        "source": source,
                        "ip_hash": ip_hash,
                        "has_email_hash": bool(getattr(shipment.order, "customer_email_hash", "")),
                        "has_phone_hash": bool(getattr(shipment.order, "customer_phone_hash", "")),
                    },
                )
            else:
                if not self._verify_customer(shipment, customer_verification):
                    return self._record_and_error(
                        db, brand, session_id, source, lookup_type, lookup_hash, ip_hash,
                        "verification_required",
                        "For privacy, please also provide the phone number or email used for the order.",
                        requires_customer_verification=True,
                    )

        self.refresh_shipment(db, shipment.id)
        self.recalculate_eta(db, shipment, force=False)

        response = self._build_lookup_response(db, brand, shipment)
        _LOOKUP_CACHE[cache_key] = (response, shipment.id)
        self._cache_response(db, brand.id, lookup_type, lookup_hash, shipment.id, response)
        self._record_tracking_request(db, brand.id, session_id, source, lookup_type, lookup_hash, "success", ip_hash)
        AnalyticsService.log_event(
            db,
            brand.id,
            "tracking_request",
            session_id,
            {
                "source": source,
                "lookup_type": lookup_type,
                "status": shipment.current_status,
                "shipment_id": shipment.id,
                "cache": False,
            },
        )
        return response

    def refresh_shipment(self, db: Session, shipment_id: int, brand_id: int | None = None) -> models.Shipment | None:
        q = db.query(models.Shipment).filter_by(id=shipment_id)
        if brand_id is not None:
            q = q.filter(models.Shipment.brand_id == brand_id)
        shipment = q.first()
        if not shipment:
            return None

        if shipment.provider.provider_type == "http" and shipment.provider.base_url:
            self._sync_http_provider(db, shipment)

        latest_event = (
            db.query(models.TrackingEvent)
            .filter_by(shipment_id=shipment.id)
            .order_by(models.TrackingEvent.event_timestamp.desc())
            .first()
        )
        if latest_event:
            self._apply_event_snapshot(db, shipment, latest_event)

        shipment.last_provider_sync_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        return shipment

    def recalculate_eta(
        self,
        db: Session,
        shipment: models.Shipment,
        force: bool = False,
    ) -> dict[str, Any]:
        today = datetime.now(timezone.utc).replace(tzinfo=None).date()
        latest_eta = (
            db.query(models.ShipmentEta)
            .filter_by(shipment_id=shipment.id)
            .order_by(models.ShipmentEta.calculated_at.desc())
            .first()
        )

        if (
            not force
            and shipment.eta_date
            and shipment.eta_date >= today
            and latest_eta
            and latest_eta.source in {"provider", "override"}
        ):
            return {
                "shipment_id": shipment.id,
                "eta": shipment.eta_date,
                "confidence": latest_eta.confidence,
                "source": latest_eta.source,
                "reason": latest_eta.reason,
            }

        if shipment.current_status in TRACKING_TERMINAL_STATES:
            return {
                "shipment_id": shipment.id,
                "eta": shipment.eta_date,
                "confidence": latest_eta.confidence if latest_eta else "",
                "source": latest_eta.source if latest_eta else "",
                "reason": "Terminal shipment state",
            }

        route_eta = self._route_based_eta(db, shipment)
        if route_eta:
            eta_date, reason = route_eta
            confidence = "medium"
            source = "route_history"
        else:
            fallback_days = {
                "order_created": 5,
                "picked_up": 4,
                "at_origin_hub": 4,
                "in_transit": 3,
                "at_intermediate_hub": 3,
                "at_destination_hub": 2,
                "out_for_delivery": 0,
                "failed_delivery": 2,
                "delayed": 2,
            }.get(shipment.current_status, 4)
            eta_date = today + timedelta(days=fallback_days)
            confidence = "low"
            source = "fallback"
            reason = "Fallback ETA based on current shipment status"

        shipment.eta_date = eta_date
        eta_row = models.ShipmentEta(
            shipment_id=shipment.id,
            eta_date=eta_date,
            source=source,
            confidence=confidence,
            reason=reason,
        )
        db.add(eta_row)
        db.commit()
        return {
            "shipment_id": shipment.id,
            "eta": eta_date,
            "confidence": confidence,
            "source": source,
            "reason": reason,
        }

    def manual_override(
        self,
        db: Session,
        shipment_id: int,
        status: str,
        eta: date | None,
        notes: str,
        admin_username: str = "",
        brand_id: int | None = None,
    ) -> models.Shipment | None:
        q = db.query(models.Shipment).filter_by(id=shipment_id)
        if brand_id is not None:
            q = q.filter(models.Shipment.brand_id == brand_id)
        shipment = q.first()
        if not shipment:
            return None

        normalized_status = self.normalize_status(status)
        if normalized_status not in TRACKING_STATUS_LABELS:
            raise ValueError("Unsupported tracking status")

        previous_status = shipment.current_status
        previous_eta = shipment.eta_date
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        override = models.TrackingOverride(
            shipment_id=shipment.id,
            admin_username=admin_username,
            previous_status=previous_status,
            new_status=normalized_status,
            previous_eta=previous_eta,
            new_eta=eta,
            notes=notes,
        )
        db.add(override)

        event = models.TrackingEvent(
            shipment_id=shipment.id,
            status=normalized_status,
            normalized_status=normalized_status,
            raw_provider_status=f"manual_override:{normalized_status}",
            hub_id=shipment.current_hub_id,
            location_text=shipment.current_location_text,
            event_timestamp=now,
            provider_event_id=f"override-{shipment.id}-{now.strftime('%Y%m%d%H%M%S%f')}",
            notes=notes,
        )
        db.add(event)

        shipment.current_status = normalized_status
        if eta:
            shipment.eta_date = eta
            db.add(models.ShipmentEta(
                shipment_id=shipment.id,
                eta_date=eta,
                source="override",
                confidence="high",
                reason=notes or "Manual admin override",
            ))
        if normalized_status == "delivered" and not shipment.delivered_at:
            shipment.delivered_at = now
        db.commit()
        return shipment

    def search_shipments(
        self,
        db: Session,
        brand: models.Brand | None = None,
        query: str = "",
        limit: int = 50,
    ) -> list[models.Shipment]:
        q = db.query(models.Shipment).join(models.Order)
        if brand:
            q = q.filter(models.Shipment.brand_id == brand.id)
        query = query.strip()
        if query:
            pattern = f"%{query}%"
            q = q.filter(or_(
                models.Order.order_id.ilike(pattern),
                models.Shipment.tracking_number.ilike(pattern),
                models.Shipment.shipment_id.ilike(pattern),
                models.Shipment.current_status.ilike(pattern),
                models.Shipment.current_location_text.ilike(pattern),
            ))
        return q.order_by(models.Shipment.updated_at.desc()).limit(limit).all()

    def shipment_to_admin_dict(self, db: Session, shipment: models.Shipment) -> dict[str, Any]:
        events = (
            db.query(models.TrackingEvent)
            .filter_by(shipment_id=shipment.id)
            .order_by(models.TrackingEvent.event_timestamp)
            .all()
        )
        return {
            "id": shipment.id,
            "brand": shipment.brand.slug,
            "order_id": shipment.order.order_id,
            "shipment_id": shipment.shipment_id,
            "tracking_number": shipment.tracking_number,
            "current_status": shipment.current_status,
            "status_label": self.status_label(shipment.current_status),
            "current_location": shipment.current_location_text,
            "current_hub": self._hub_to_dict(shipment.current_hub),
            "previous_hub": self._hub_to_dict(shipment.previous_hub),
            "next_hub": self._hub_to_dict(shipment.next_hub),
            "eta": shipment.eta_date,
            "delivered_at": shipment.delivered_at,
            "delay_reason": shipment.delay_reason,
            "last_provider_sync_at": shipment.last_provider_sync_at,
            "events": [self._event_to_dict(event) for event in events],
        }

    def get_tracking_analytics(self, db: Session, brand: models.Brand | None = None) -> dict[str, Any]:
        q = db.query(models.Shipment)
        request_q = db.query(models.TrackingRequest)
        if brand:
            q = q.filter_by(brand_id=brand.id)
            request_q = request_q.filter_by(brand_id=brand.id)

        shipments = q.all()
        total = len(shipments)
        delivered = len([s for s in shipments if s.current_status == "delivered"])
        delayed = len([s for s in shipments if s.current_status == "delayed"])
        failed = len([s for s in shipments if s.current_status == "failed_delivery"])
        active = len([s for s in shipments if s.current_status not in TRACKING_TERMINAL_STATES])

        durations = []
        for shipment in shipments:
            first_event = shipment.events[0] if shipment.events else None
            if first_event and shipment.delivered_at:
                durations.append((shipment.delivered_at - first_event.event_timestamp).total_seconds() / 86400)

        hub_counts: dict[str, int] = {}
        for shipment in shipments:
            if shipment.current_hub:
                key = shipment.current_hub.hub_name
                hub_counts[key] = hub_counts.get(key, 0) + 1

        return {
            "total_shipments": total,
            "active_shipments": active,
            "delivered_shipments": delivered,
            "delayed_shipments": delayed,
            "failed_deliveries": failed,
            "delay_percentage": round((delayed / total) * 100, 2) if total else 0,
            "average_delivery_days": round(sum(durations) / len(durations), 2) if durations else 0,
            "tracking_requests": request_q.count(),
            "common_hubs": sorted(hub_counts.items(), key=lambda item: item[1], reverse=True)[:5],
        }

    def normalize_status(self, raw_status: str) -> str:
        raw = (raw_status or "").strip().lower().replace("-", " ").replace("_", " ")
        raw = re.sub(r"\s+", " ", raw)
        mapping = (
            ("cancel", "cancelled"),
            ("return", "returned"),
            ("failed", "failed_delivery"),
            ("delivery failed", "failed_delivery"),
            ("delivered", "delivered"),
            ("out for delivery", "out_for_delivery"),
            ("destination", "at_destination_hub"),
            ("intermediate", "at_intermediate_hub"),
            ("origin hub", "at_origin_hub"),
            ("at hub", "at_intermediate_hub"),
            ("in transit", "in_transit"),
            ("transit", "in_transit"),
            ("picked", "picked_up"),
            ("created", "order_created"),
            ("delay", "delayed"),
        )
        for needle, status in mapping:
            if needle in raw:
                return status
        compact = raw.replace(" ", "_")
        return compact if compact in TRACKING_STATUS_LABELS else raw

    def status_label(self, status: str) -> str:
        return TRACKING_STATUS_LABELS.get(status, status.replace("_", " ").title())

    def validate_order_id(self, value: str) -> tuple[bool, str]:
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,95}$", value):
            return False, "The order ID contains invalid characters."
        if not re.search(r"\d", value):
            return False, "The order ID should contain at least one digit."
        return True, ""

    def validate_tracking_number(self, value: str) -> tuple[bool, str]:
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,95}$", value):
            return False, "The tracking number contains invalid characters."
        if not re.search(r"\d", value):
            return False, "The tracking number should contain at least one digit."
        return True, ""

    def validate_verification(self, value: str) -> tuple[bool, str]:
        stripped = value.strip().lower()
        if not stripped:
            return False, "Please provide an email address or phone number."
        has_at = "@" in stripped and "." in stripped
        has_digits = re.search(r"\d", stripped)
        if has_at or (has_digits and len(stripped) >= 7):
            return True, ""
        return False, "That doesn't look like a valid email or phone number."

    def infer_lookup_type(self, value: str) -> str:
        upper = value.upper()
        if upper.startswith("TRK") or upper.startswith("SHIP"):
            return "tracking_number"
        brand_prefixes = ("BIO-", "BLD-", "VIT-", "KALP-", "ORD-")
        if any(upper.startswith(p) for p in brand_prefixes):
            return "order_id"
        if re.match(r"^[A-Z]{2,8}[-_]", upper):
            return "order_id"
        return "auto"

    def extract_lookup_value_with_type(self, message: str) -> tuple[str, str, int]:
        explicit = re.search(
            r"(?:order\s*id|tracking\s*(?:number|no)|shipment\s*(?:id|number))\s*(?:is|:|#)?\s*([A-Za-z0-9._-]{3,96})",
            message,
            re.IGNORECASE,
        )
        if explicit:
            value = self._normalize_lookup_value(explicit.group(1))
            lt = self.infer_lookup_type(value)
            return value, lt, 90
        token = self.lookup_token_pattern.search(message)
        if token:
            value = self._normalize_lookup_value(token.group(0))
            lt = self.infer_lookup_type(value)
            return value, lt, 80
        stripped = message.strip().upper()
        if self.lookup_pattern.match(stripped) and any(ch.isdigit() for ch in stripped):
            lt = self.infer_lookup_type(stripped)
            return stripped, lt, 60
        words = message.strip().split()
        for word in words:
            clean = re.sub(r"[^A-Za-z0-9._-]", "", word).upper()
            if self.lookup_pattern.match(clean) and any(ch.isdigit() for ch in clean):
                lt = self.infer_lookup_type(clean)
                return clean, lt, 40
        return "", "", 0

    def build_tracking_data_dict(self, response: dict[str, Any]) -> dict[str, Any]:
        hub = response.get("current_hub") or {}
        return {
            "order_id": response.get("order_id", ""),
            "tracking_number": response.get("tracking_number", ""),
            "shipment_id": response.get("shipment_id", ""),
            "status": response.get("shipment_status", ""),
            "status_label": response.get("status_label", ""),
            "hub_name": hub.get("hub_name", ""),
            "hub_city": hub.get("city", ""),
            "current_location": response.get("current_location", ""),
            "eta": self._format_date(response["eta"]) if response.get("eta") else "",
            "last_updated": self._format_datetime(response["last_updated"]) if response.get("last_updated") else "",
            "delay_reason": response.get("delay_reason", ""),
            "timeline": [
                f"{self._format_datetime(e['event_timestamp'])}: {e['status_label'] if 'status_label' in e else e['normalized_status']} - {e.get('location_text', '') or e.get('hub', {}).get('hub_name', '')}"
                for e in response.get("timeline", [])
            ],
        }

    def allowed_transition(self, current_status: str, new_status: str) -> bool:
        current = current_status or "order_created"
        new = new_status or current
        if current == new:
            return True
        if current in TRACKING_TERMINAL_STATES:
            return False
        return new in TRACKING_TRANSITIONS.get(current, set())

    def _ensure_default_hubs(self, db: Session, provider: models.LogisticsProvider) -> dict[str, models.HubMaster]:
        hub_specs = {
            "DEL": ("Delhi Hub", "Delhi", "Delhi"),
            "MUM": ("Mumbai Distribution Hub", "Mumbai", "Maharashtra"),
            "PUN": ("Pune Hub", "Pune", "Maharashtra"),
            "BLR": ("Bangalore Hub", "Bangalore", "Karnataka"),
        }
        hubs: dict[str, models.HubMaster] = {}
        for code, (name, city, state) in hub_specs.items():
            hub = (
                db.query(models.HubMaster)
                .filter_by(provider_id=provider.id, hub_code=code)
                .first()
            )
            if not hub:
                hub = models.HubMaster(
                    provider_id=provider.id,
                    hub_code=code,
                    hub_name=name,
                    city=city,
                    state=state,
                )
                db.add(hub)
                db.commit()
                db.refresh(hub)
            hubs[code] = hub
        return hubs

    def _ensure_default_routes(
        self,
        db: Session,
        provider: models.LogisticsProvider,
        hubs: dict[str, models.HubMaster],
    ) -> None:
        route_specs = (
            ("DEL", "MUM", 36),
            ("MUM", "PUN", 10),
            ("DEL", "BLR", 48),
            ("BLR", "MUM", 30),
            ("MUM", "BLR", 30),
        )
        for origin_code, dest_code, hours in route_specs:
            origin = hubs[origin_code]
            dest = hubs[dest_code]
            exists = (
                db.query(models.HubRoute)
                .filter_by(provider_id=provider.id, origin_hub_id=origin.id, destination_hub_id=dest.id)
                .first()
            )
            if not exists:
                db.add(models.HubRoute(
                    provider_id=provider.id,
                    origin_hub_id=origin.id,
                    destination_hub_id=dest.id,
                    avg_transit_hours=hours,
                ))
        db.commit()

    def _ensure_demo_shipments(
        self,
        db: Session,
        provider: models.LogisticsProvider,
        hubs: dict[str, models.HubMaster],
    ) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)
        samples = {
            "biopharma": {
                "order_id": "BIO-1001",
                "tracking_number": "TRK-BIO-1001",
                "shipment_id": "SHIP-BIO-1001",
                "eta": now.date() + timedelta(days=2),
                "events": [
                    ("order_created", None, "Order created", now - timedelta(days=3, hours=8)),
                    ("picked_up", hubs["DEL"], "Picked up from seller", now - timedelta(days=3, hours=2)),
                    ("at_origin_hub", hubs["DEL"], "Delhi Hub", now - timedelta(days=2, hours=18)),
                    ("in_transit", hubs["DEL"], "In transit from Delhi Hub to Mumbai Distribution Hub", now - timedelta(days=2, hours=4)),
                    ("at_destination_hub", hubs["MUM"], "Mumbai Distribution Hub", now - timedelta(hours=7)),
                ],
                "next_hub": None,
            },
            "building": {
                "order_id": "BLD-1001",
                "tracking_number": "TRK-BLD-1001",
                "shipment_id": "SHIP-BLD-1001",
                "eta": now.date() + timedelta(days=3),
                "events": [
                    ("order_created", None, "Order created", now - timedelta(days=2, hours=5)),
                    ("picked_up", hubs["DEL"], "Picked up from seller", now - timedelta(days=2)),
                    ("at_origin_hub", hubs["DEL"], "Delhi Hub", now - timedelta(days=1, hours=18)),
                    ("in_transit", hubs["DEL"], "In transit from Delhi Hub to Mumbai Distribution Hub", now - timedelta(hours=5)),
                ],
                "next_hub": hubs["MUM"],
            },
            "kalp": {
                "order_id": "KALP-1001",
                "tracking_number": "TRK-KALP-1001",
                "shipment_id": "SHIP-KALP-1001",
                "eta": now.date() - timedelta(days=1),
                "events": [
                    ("order_created", None, "Order created", now - timedelta(days=4)),
                    ("picked_up", hubs["MUM"], "Picked up from seller", now - timedelta(days=3, hours=18)),
                    ("at_origin_hub", hubs["MUM"], "Mumbai Distribution Hub", now - timedelta(days=3, hours=14)),
                    ("in_transit", hubs["MUM"], "In transit from Mumbai Distribution Hub to Pune Hub", now - timedelta(days=3)),
                    ("at_destination_hub", hubs["PUN"], "Pune Hub", now - timedelta(days=2, hours=8)),
                    ("out_for_delivery", hubs["PUN"], "Out for delivery in Pune", now - timedelta(days=1, hours=9)),
                    ("delivered", hubs["PUN"], "Delivered successfully", now - timedelta(days=1, hours=5)),
                ],
                "next_hub": None,
            },
            "default": {
                "order_id": "BIO-1001",
                "tracking_number": "TRK-BIO-1001",
                "shipment_id": "SHIP-DEF-1001",
                "eta": now.date() + timedelta(days=2),
                "events": [
                    ("order_created", None, "Order created", now - timedelta(days=3, hours=8)),
                    ("picked_up", hubs["DEL"], "Picked up from seller", now - timedelta(days=3, hours=2)),
                    ("at_origin_hub", hubs["DEL"], "Delhi Hub", now - timedelta(days=2, hours=18)),
                    ("in_transit", hubs["DEL"], "In transit from Delhi Hub to Mumbai Distribution Hub", now - timedelta(days=2, hours=4)),
                    ("at_destination_hub", hubs["MUM"], "Mumbai Distribution Hub", now - timedelta(hours=7)),
                ],
                "next_hub": None,
            },
        }

        for brand_slug, sample in samples.items():
            brand = brand_service.get_or_create(db, brand_slug)
            existing = (
                db.query(models.Order)
                .filter_by(brand_id=brand.id, order_id=sample["order_id"])
                .first()
            )
            if existing:
                continue

            order = models.Order(
                brand_id=brand.id,
                order_id=sample["order_id"],
                order_status="shipped",
            )
            db.add(order)
            db.flush()

            shipment = models.Shipment(
                brand_id=brand.id,
                order_id=order.id,
                provider_id=provider.id,
                shipment_id=sample["shipment_id"],
                tracking_number=sample["tracking_number"],
                current_status="order_created",
                eta_date=sample["eta"],
                verification_required=False,
            )
            db.add(shipment)
            db.flush()

            for idx, (status, hub, location, timestamp) in enumerate(sample["events"], start=1):
                db.add(models.TrackingEvent(
                    shipment_id=shipment.id,
                    status=status,
                    normalized_status=status,
                    raw_provider_status=status,
                    hub_id=hub.id if hub else None,
                    location_text=location,
                    event_timestamp=timestamp,
                    provider_event_id=f"{sample['shipment_id']}-event-{idx}",
                ))
            db.add(models.ShipmentEta(
                shipment_id=shipment.id,
                eta_date=sample["eta"],
                source="provider",
                confidence="high",
                reason="Demo logistics provider ETA",
            ))

            db.flush()
            latest_event = (
                db.query(models.TrackingEvent)
                .filter_by(shipment_id=shipment.id)
                .order_by(models.TrackingEvent.event_timestamp.desc())
                .first()
            )
            if latest_event:
                self._apply_event_snapshot(db, shipment, latest_event)
            if sample["next_hub"]:
                shipment.next_hub_id = sample["next_hub"].id
            db.commit()

    def _find_shipment(
        self,
        db: Session,
        brand: models.Brand,
        lookup_type: str,
        normalized_lookup: str,
    ) -> tuple[models.Shipment | None, dict[str, Any] | None]:
        if lookup_type in {"auto", "tracking_number"}:
            shipment = (
                db.query(models.Shipment)
                .filter_by(brand_id=brand.id, tracking_number=normalized_lookup)
                .first()
            )
            if shipment:
                return shipment, None
            if lookup_type == "tracking_number":
                return None, None

        order = (
            db.query(models.Order)
            .filter_by(brand_id=brand.id, order_id=normalized_lookup)
            .first()
        )
        if not order:
            return None, None

        shipments = (
            db.query(models.Shipment)
            .filter_by(brand_id=brand.id, order_id=order.id)
            .order_by(models.Shipment.created_at.desc())
            .all()
        )
        if not shipments:
            return None, {
                "code": "shipment_not_created",
                "message": "The order exists, but shipment tracking is not available yet.",
                "retry_allowed": True,
            }
        if len(shipments) > 1:
            return None, {
                "code": "multiple_shipments",
                "message": "This order has multiple shipments. Please use the shipment tracking number.",
                "retry_allowed": True,
            }
        return shipments[0], None

    async def _background_refresh_cache(
        self,
        cache_key: str,
        brand: models.Brand,
        lookup_type: str,
        lookup_hash: str,
    ) -> None:
        """Re-fetch provider data in the background and update the TTL cache.

        Never raises — all errors are logged and swallowed.
        """
        try:
            from app.db import SessionLocal

            db = SessionLocal()
            try:
                cached_row = (
                    db.query(models.TrackingCache)
                    .filter_by(
                        brand_id=brand.id,
                        lookup_type=lookup_type,
                        lookup_hash=lookup_hash,
                    )
                    .order_by(models.TrackingCache.created_at.desc())
                    .first()
                )
                if cached_row and cached_row.shipment_id:
                    shipment = db.query(models.Shipment).get(cached_row.shipment_id)
                    if shipment:
                        self.refresh_shipment(db, shipment.id)
                        fresh = self._build_lookup_response(db, brand, shipment)
                        _LOOKUP_CACHE[cache_key] = (fresh, shipment.id)
            finally:
                db.close()
        except Exception:
            logger.exception("Background cache refresh failed for key=%s", cache_key)

    def _sync_http_provider(self, db: Session, shipment: models.Shipment) -> None:
        provider = shipment.provider
        api_key = os.getenv(provider.api_key_env, "") if provider.api_key_env else ""
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        url = f"{provider.base_url.rstrip('/')}/shipments/{shipment.tracking_number}"
        try:
            with httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
                response = client.get(url, headers=headers)
            if response.status_code != 200:
                return
            payload = response.json()
        except Exception as exc:
            logger.warning("Provider sync failed for shipment %s: %s", shipment.id, exc)
            return

        status = self.normalize_status(payload.get("shipment_status") or payload.get("status") or "")
        if not status or status not in TRACKING_STATUS_LABELS:
            return
        if not self.allowed_transition(shipment.current_status, status):
            return

        hub = self._get_or_create_provider_hub(db, provider, payload)
        event_timestamp = self._parse_datetime(payload.get("timestamp")) or datetime.now(timezone.utc).replace(tzinfo=None)
        provider_event_id = (
            str(payload.get("event_id") or "")
            or self._hash_lookup("event", shipment.tracking_number, f"{status}:{event_timestamp.isoformat()}")
        )

        exists = (
            db.query(models.TrackingEvent)
            .filter_by(shipment_id=shipment.id, provider_event_id=provider_event_id)
            .first()
        )
        if exists:
            return

        event = models.TrackingEvent(
            shipment_id=shipment.id,
            status=status,
            normalized_status=status,
            raw_provider_status=str(payload.get("shipment_status") or payload.get("status") or ""),
            hub_id=hub.id if hub else None,
            location_text=str(payload.get("current_location") or payload.get("hub_name") or ""),
            event_timestamp=event_timestamp,
            provider_event_id=provider_event_id,
            notes=str(payload.get("notes") or ""),
        )
        db.add(event)

        eta = self._parse_date(payload.get("eta") or payload.get("ETA"))
        if eta:
            shipment.eta_date = eta
            db.add(models.ShipmentEta(
                shipment_id=shipment.id,
                eta_date=eta,
                source="provider",
                confidence="high",
                reason="Provider supplied ETA",
            ))
        db.commit()
        self._apply_event_snapshot(db, shipment, event)

    def _get_or_create_provider_hub(
        self,
        db: Session,
        provider: models.LogisticsProvider,
        payload: dict[str, Any],
    ) -> models.HubMaster | None:
        hub_code = str(payload.get("hub_id") or payload.get("hub_code") or "").strip()
        hub_name = str(payload.get("hub_name") or "").strip()
        hub_city = str(payload.get("hub_city") or "").strip()
        if not hub_code and not hub_name:
            return None
        hub_code = hub_code or slugify(hub_name).upper()[:32]
        hub = (
            db.query(models.HubMaster)
            .filter_by(provider_id=provider.id, hub_code=hub_code)
            .first()
        )
        if hub:
            return hub
        hub = models.HubMaster(
            provider_id=provider.id,
            hub_code=hub_code,
            hub_name=hub_name or hub_code,
            city=hub_city,
            state=str(payload.get("hub_state") or ""),
            country=str(payload.get("country") or "India"),
        )
        db.add(hub)
        db.commit()
        db.refresh(hub)
        return hub

    def _apply_event_snapshot(
        self,
        db: Session,
        shipment: models.Shipment,
        latest_event: models.TrackingEvent,
    ) -> None:
        status = latest_event.normalized_status
        if latest_event.event_timestamp:
            newest_known = (
                db.query(models.TrackingEvent)
                .filter_by(shipment_id=shipment.id)
                .order_by(models.TrackingEvent.event_timestamp.desc())
                .first()
            )
            if newest_known and newest_known.id != latest_event.id:
                latest_event = newest_known
                status = latest_event.normalized_status

        previous_current_hub_id = shipment.current_hub_id
        shipment.current_status = status
        shipment.current_location_text = latest_event.location_text or shipment.current_location_text

        if status in HUB_STATUSES and latest_event.hub_id:
            if previous_current_hub_id and previous_current_hub_id != latest_event.hub_id:
                shipment.previous_hub_id = previous_current_hub_id
            shipment.current_hub_id = latest_event.hub_id
            shipment.next_hub_id = self._infer_next_hub_id(db, shipment)
        elif status == "in_transit":
            if latest_event.hub_id:
                shipment.previous_hub_id = latest_event.hub_id
            elif previous_current_hub_id:
                shipment.previous_hub_id = previous_current_hub_id
            shipment.current_hub_id = None
            shipment.next_hub_id = self._infer_next_hub_id(db, shipment)
        elif status == "out_for_delivery" and latest_event.hub_id:
            shipment.current_hub_id = latest_event.hub_id
            shipment.next_hub_id = None
        elif status == "delivered":
            shipment.delivered_at = latest_event.event_timestamp
            shipment.next_hub_id = None

        db.commit()

    def _infer_next_hub_id(self, db: Session, shipment: models.Shipment) -> int | None:
        origin_id = shipment.current_hub_id or shipment.previous_hub_id
        if not origin_id:
            return None
        route = (
            db.query(models.HubRoute)
            .filter_by(provider_id=shipment.provider_id, origin_hub_id=origin_id, is_active=True)
            .order_by(models.HubRoute.avg_transit_hours)
            .first()
        )
        return route.destination_hub_id if route else None

    def _route_based_eta(self, db: Session, shipment: models.Shipment) -> tuple[date, str] | None:
        origin_id = shipment.current_hub_id or shipment.previous_hub_id
        dest_id = shipment.next_hub_id
        if not origin_id or not dest_id:
            return None
        route = (
            db.query(models.HubRoute)
            .filter_by(provider_id=shipment.provider_id, origin_hub_id=origin_id, destination_hub_id=dest_id, is_active=True)
            .first()
        )
        if not route:
            return None
        days = max(1, int((route.avg_transit_hours + 23) / 24) + 1)
        return datetime.now(timezone.utc).replace(tzinfo=None).date() + timedelta(days=days), (
            f"Calculated from {route.origin_hub.hub_name} to {route.destination_hub.hub_name}"
        )

    def _build_lookup_response(
        self,
        db: Session,
        brand: models.Brand,
        shipment: models.Shipment,
    ) -> dict[str, Any]:
        events = (
            db.query(models.TrackingEvent)
            .filter_by(shipment_id=shipment.id)
            .order_by(models.TrackingEvent.event_timestamp)
            .all()
        )
        latest_event = events[-1] if events else None
        latest_eta = (
            db.query(models.ShipmentEta)
            .filter_by(shipment_id=shipment.id)
            .order_by(models.ShipmentEta.calculated_at.desc())
            .first()
        )
        response = {
            "success": True,
            "brand": brand.slug,
            "order_id": shipment.order.order_id,
            "shipment_id": shipment.shipment_id,
            "tracking_number": shipment.tracking_number,
            "shipment_status": shipment.current_status,
            "status_label": self.status_label(shipment.current_status),
            "current_hub": self._hub_to_dict(shipment.current_hub),
            "previous_hub": self._hub_to_dict(shipment.previous_hub),
            "next_hub": self._hub_to_dict(shipment.next_hub),
            "current_location": shipment.current_location_text,
            "last_updated": latest_event.event_timestamp if latest_event else shipment.updated_at,
            "eta": shipment.eta_date,
            "delivered_on": shipment.delivered_at.date() if shipment.delivered_at else None,
            "delay_reason": shipment.delay_reason,
            "confidence": latest_eta.confidence if latest_eta else "",
            "message_template_key": shipment.current_status,
            "timeline": [self._event_to_dict(event) for event in events[-8:]],
            "error_code": "",
            "retry_allowed": False,
            "requires_customer_verification": False,
        }
        response["safe_response_text"] = self._build_safe_response_text(response)
        return response

    def _build_safe_response_text(self, response: dict[str, Any]) -> str:
        status = response["shipment_status"]
        status_label = response["status_label"]
        current_hub = response.get("current_hub")
        previous_hub = response.get("previous_hub")
        next_hub = response.get("next_hub")

        if status == "delivered":
            headline = "Your shipment has been delivered successfully."
            lines = [headline]
            if response.get("delivered_on"):
                lines.extend(["", "Delivered On:", self._format_date(response["delivered_on"])])
            return "\n".join(lines)

        if status == "in_transit" and previous_hub and next_hub:
            headline = (
                f"Your shipment has departed from the {previous_hub['hub_name']} "
                f"and is currently in transit to the {next_hub['hub_name']}."
            )
        elif status in HUB_STATUSES and current_hub:
            headline = f"Your order has reached the {current_hub['hub_name']}."
        elif status == "out_for_delivery":
            headline = "Your shipment is out for delivery."
        elif status == "delayed":
            headline = "Your shipment is taking longer than expected."
        elif status == "failed_delivery":
            headline = "Delivery was attempted, but it could not be completed."
        elif status == "returned":
            headline = "Your shipment is being returned."
        elif status == "cancelled":
            headline = "This shipment has been cancelled."
        elif status == "picked_up":
            headline = "Your shipment has been picked up."
        else:
            headline = "Your shipment update is available."

        lines = [headline, "", "Current Status:", status_label]
        if response.get("last_updated"):
            lines.extend(["", "Last Updated:", self._format_datetime(response["last_updated"])])
        if response.get("eta"):
            lines.extend(["", "Estimated Delivery:", self._format_date(response["eta"])])
        if response.get("delay_reason"):
            lines.extend(["", "Delay Reason:", response["delay_reason"]])
        return "\n".join(lines)

    def _event_to_dict(self, event: models.TrackingEvent) -> dict[str, Any]:
        return {
            "id": event.id,
            "status": event.status,
            "normalized_status": event.normalized_status,
            "raw_provider_status": event.raw_provider_status,
            "location_text": event.location_text,
            "event_timestamp": event.event_timestamp,
            "notes": event.notes,
            "hub": self._hub_to_dict(event.hub),
        }

    def _hub_to_dict(self, hub: models.HubMaster | None) -> dict[str, Any] | None:
        if not hub:
            return None
        return {
            "id": hub.id,
            "hub_code": hub.hub_code,
            "hub_name": hub.hub_name,
            "city": hub.city,
            "state": hub.state,
            "country": hub.country,
        }

    def _record_and_error(
        self,
        db: Session,
        brand: models.Brand,
        session_id: str,
        source: str,
        lookup_type: str,
        lookup_hash: str,
        ip_hash: str,
        code: str,
        message: str,
        retry_allowed: bool = False,
        requires_customer_verification: bool = False,
    ) -> dict[str, Any]:
        self._record_tracking_request(db, brand.id, session_id, source, lookup_type, lookup_hash, code, ip_hash)
        return self._error_response(
            brand=brand,
            code=code,
            message=message,
            retry_allowed=retry_allowed,
            requires_customer_verification=requires_customer_verification,
        )

    def _error_response(
        self,
        brand: models.Brand,
        code: str,
        message: str,
        retry_allowed: bool = False,
        requires_customer_verification: bool = False,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "brand": brand.slug,
            "order_id": "",
            "shipment_id": "",
            "tracking_number": "",
            "shipment_status": "",
            "status_label": "",
            "current_hub": None,
            "previous_hub": None,
            "next_hub": None,
            "current_location": "",
            "last_updated": None,
            "eta": None,
            "delivered_on": None,
            "delay_reason": "",
            "confidence": "",
            "message_template_key": "error",
            "safe_response_text": message,
            "timeline": [],
            "error_code": code,
            "retry_allowed": retry_allowed,
            "requires_customer_verification": requires_customer_verification,
        }

    def _record_tracking_request(
        self,
        db: Session,
        brand_id: int,
        session_id: str,
        source: str,
        lookup_type: str,
        lookup_hash: str,
        result_code: str,
        ip_hash: str = "",
    ) -> None:
        db.add(models.TrackingRequest(
            brand_id=brand_id,
            session_id=session_id,
            source=source,
            lookup_type=lookup_type,
            lookup_value_hash=lookup_hash,
            result_code=result_code,
            ip_hash=ip_hash,
        ))
        db.commit()

    def _is_rate_limited(
        self,
        db: Session,
        brand: models.Brand,
        session_id: str,
        lookup_hash: str,
    ) -> bool:
        window_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        if session_id:
            session_count = (
                db.query(models.TrackingRequest)
                .filter(
                    models.TrackingRequest.brand_id == brand.id,
                    models.TrackingRequest.session_id == session_id,
                    models.TrackingRequest.created_at >= window_start,
                )
                .count()
            )
            if session_count >= 20:
                return True
        lookup_count = (
            db.query(models.TrackingRequest)
            .filter(
                models.TrackingRequest.brand_id == brand.id,
                models.TrackingRequest.lookup_value_hash == lookup_hash,
                models.TrackingRequest.created_at >= window_start,
            )
            .count()
        )
        return lookup_count >= 10

    def _get_cached_response(
        self,
        db: Session,
        brand_id: int,
        lookup_type: str,
        lookup_hash: str,
    ) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cache = (
            db.query(models.TrackingCache)
            .filter(
                models.TrackingCache.brand_id == brand_id,
                models.TrackingCache.lookup_type == lookup_type,
                models.TrackingCache.lookup_value_hash == lookup_hash,
                models.TrackingCache.expires_at > now,
            )
            .order_by(models.TrackingCache.created_at.desc())
            .first()
        )
        if not cache:
            return None
        try:
            return json.loads(cache.response_snapshot_json)
        except json.JSONDecodeError:
            return None

    def _cache_response(
        self,
        db: Session,
        brand_id: int,
        lookup_type: str,
        lookup_hash: str,
        shipment_id: int,
        response: dict[str, Any],
    ) -> None:
        status = response.get("shipment_status", "")
        ttl = timedelta(hours=24) if status in TRACKING_TERMINAL_STATES else timedelta(minutes=5)
        db.add(models.TrackingCache(
            brand_id=brand_id,
            lookup_type=lookup_type,
            lookup_value_hash=lookup_hash,
            shipment_id=shipment_id,
            response_snapshot_json=json.dumps(response, default=str),
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + ttl,
        ))
        db.commit()

    def _verify_customer(self, shipment: models.Shipment, customer_verification: str) -> bool:
        if not shipment.verification_required:
            return True
        value = customer_verification.strip().lower()
        if not value:
            return False
        hashed = hashlib.sha256(value.encode()).hexdigest()
        return hashed in {shipment.order.customer_email_hash, shipment.order.customer_phone_hash}

    def _awaiting_tracking_lookup(self, history: list[dict]) -> bool:
        if not history:
            return False
        recent_assistant = [m for m in history[-4:] if m.get("role") == "assistant"]
        return any(self.pending_lookup_phrase.lower() in m.get("content", "").lower() for m in recent_assistant)

    def _normalize_lookup_value(self, value: str) -> str:
        return value.strip().upper()

    def _hash_lookup(self, brand_slug: str, lookup_type: str, value: str) -> str:
        raw = f"{brand_slug}:{lookup_type}:{value.strip().lower()}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _format_datetime(self, value: datetime | str) -> str:
        if isinstance(value, str):
            parsed = self._parse_datetime(value)
            value = parsed or datetime.now(timezone.utc).replace(tzinfo=None)
        return value.strftime("%d %B %Y, %I:%M %p")

    def _format_date(self, value: date | datetime | str) -> str:
        if isinstance(value, str):
            parsed_date = self._parse_date(value)
            value = parsed_date or datetime.now(timezone.utc).replace(tzinfo=None).date()
        if isinstance(value, datetime):
            value = value.date()
        return value.strftime("%d %B %Y")

    def _parse_datetime(self, value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo:
                parsed = parsed.replace(tzinfo=None)
            return parsed
        except ValueError:
            return None

    def _parse_date(self, value: Any) -> date | None:
        if not value:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        parsed_dt = self._parse_datetime(text)
        return parsed_dt.date() if parsed_dt else None


tracking_service = TrackingService()

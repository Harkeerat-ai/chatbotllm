"""
Analytics service — event logging and summary queries.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)


class AnalyticsService:
    @staticmethod
    def log_event(
        db: Session,
        brand_id: int,
        event_type: str,
        session_id: str = "",
        payload: dict | None = None,
    ) -> None:
        event = models.AnalyticsEvent(
            brand_id=brand_id,
            event_type=event_type,
            session_id=session_id,
            payload_json=json.dumps(payload or {}),
        )
        db.add(event)
        db.commit()

    @staticmethod
    def get_summary(db: Session, brand: models.Brand) -> dict[str, Any]:
        events = (
            db.query(models.AnalyticsEvent)
            .filter_by(brand_id=brand.id)
            .all()
        )
        breakdown: dict[str, int] = {}
        for e in events:
            breakdown[e.event_type] = breakdown.get(e.event_type, 0) + 1

        return {
            "brand": brand.slug,
            "total_chats": breakdown.get("chat", 0),
            "total_leads": breakdown.get("lead", 0),
            "total_custom_events": sum(v for k, v in breakdown.items() if k not in ("chat", "lead")),
            "event_breakdown": breakdown,
        }


analytics_service = AnalyticsService()

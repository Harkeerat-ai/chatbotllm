"""
Analytics service — event logging and summary queries.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta, timezone
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

    @staticmethod
    def get_detailed(db: Session, brand: models.Brand, days: int = 30) -> dict[str, Any]:
        from sqlalchemy import func, cast, Date

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

        events = (
            db.query(models.AnalyticsEvent)
            .filter(models.AnalyticsEvent.brand_id == brand.id, models.AnalyticsEvent.created_at >= cutoff)
            .all()
        )

        total_events = len(events)
        chat_events = [e for e in events if e.event_type == "chat"]
        total_chats = len(chat_events)
        leads = len([e for e in events if e.event_type == "lead"])

        latencies = []
        for e in chat_events:
            try:
                p = json.loads(e.payload_json) if isinstance(e.payload_json, str) else e.payload_json
                if p and "latency_ms" in p:
                    latencies.append(p["latency_ms"])
            except (json.JSONDecodeError, TypeError):
                pass
        avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0.0

        date_groups: dict[str, int] = {}
        breakdown: dict[str, int] = {}
        latency_groups: dict[str, list[int]] = {}
        for e in events:
            day = e.created_at.strftime("%Y-%m-%d")
            date_groups[day] = date_groups.get(day, 0) + 1
            breakdown[e.event_type] = breakdown.get(e.event_type, 0) + 1
            if e.event_type == "chat":
                try:
                    p = json.loads(e.payload_json) if isinstance(e.payload_json, str) else e.payload_json
                    if p and "latency_ms" in p:
                        latency_groups.setdefault(day, []).append(p["latency_ms"])
                except (json.JSONDecodeError, TypeError):
                    pass

        chats_over_time: list[dict[str, Any]] = []
        for day_str in sorted(date_groups):
            chats_over_time.append({"date": day_str, "count": date_groups[day_str]})

        latency_trend: list[dict[str, Any]] = []
        for day_str in sorted(latency_groups):
            vals = latency_groups[day_str]
            latency_trend.append({"date": day_str, "count": round(sum(vals) / len(vals), 1)})

        return {
            "brand": brand.slug,
            "total_chats": total_chats,
            "total_leads": leads,
            "total_events": total_events,
            "avg_latency_ms": avg_latency,
            "chats_over_time": chats_over_time,
            "event_breakdown": [{"event_type": k, "count": v} for k, v in sorted(breakdown.items(), key=lambda x: -x[1])],
            "latency_trend": latency_trend,
        }


analytics_service = AnalyticsService()

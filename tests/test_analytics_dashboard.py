import json
from datetime import datetime, timedelta


def test_analytics_time_series_schema():
    from app.schemas import AnalyticsTimeSeries
    ts = AnalyticsTimeSeries(date="2024-01-01", count=5)
    assert ts.date == "2024-01-01"
    assert ts.count == 5


def test_analytics_breakdown_schema():
    from app.schemas import AnalyticsBreakdown
    b = AnalyticsBreakdown(event_type="chat", count=10)
    assert b.event_type == "chat"
    assert b.count == 10


def test_analytics_detailed_schema():
    from app.schemas import AnalyticsDetailed, AnalyticsTimeSeries, AnalyticsBreakdown
    d = AnalyticsDetailed(
        brand="test",
        total_chats=10,
        total_leads=2,
        total_events=15,
        avg_latency_ms=250.5,
        chats_over_time=[AnalyticsTimeSeries(date="2024-01-01", count=5)],
        event_breakdown=[AnalyticsBreakdown(event_type="chat", count=10)],
        latency_trend=[AnalyticsTimeSeries(date="2024-01-01", count=200)],
    )
    assert d.brand == "test"
    assert d.total_chats == 10
    assert d.avg_latency_ms == 250.5


def test_get_detailed_empty_brand(db_session):
    from app import models
    from app.analytics_service import analytics_service

    brand = models.Brand(slug="emptybrand", name="Empty Brand")
    db_session.add(brand)
    db_session.commit()

    result = analytics_service.get_detailed(db_session, brand, days=30)
    assert result["brand"] == "emptybrand"
    assert result["total_chats"] == 0
    assert result["total_events"] == 0
    assert result["avg_latency_ms"] == 0.0
    assert result["chats_over_time"] == []
    assert result["latency_trend"] == []


def test_get_detailed_with_events(db_session):
    from app import models
    from app.analytics_service import analytics_service

    brand = models.Brand(slug="testbrand2", name="Test Brand 2")
    db_session.add(brand)
    db_session.commit()

    for i in range(5):
        event = models.AnalyticsEvent(
            brand_id=brand.id,
            event_type="chat",
            session_id=f"sess_{i}",
            payload_json=json.dumps({"latency_ms": 200 + i * 10, "query_len": 20}),
            created_at=datetime.utcnow() - timedelta(hours=i),
        )
        db_session.add(event)

    lead = models.AnalyticsEvent(
        brand_id=brand.id,
        event_type="lead",
        session_id="lead_sess",
        payload_json="{}",
        created_at=datetime.utcnow(),
    )
    db_session.add(lead)
    db_session.commit()

    result = analytics_service.get_detailed(db_session, brand, days=30)
    assert result["total_chats"] == 5
    assert result["total_leads"] == 1
    assert result["total_events"] == 6
    assert result["avg_latency_ms"] > 0
    assert len(result["chats_over_time"]) >= 1
    assert len(result["event_breakdown"]) == 2


def test_get_detailed_respects_days_window(db_session):
    from app import models
    from app.analytics_service import analytics_service

    brand = models.Brand(slug="oldbrand", name="Old Brand")
    db_session.add(brand)
    db_session.commit()

    old = models.AnalyticsEvent(
        brand_id=brand.id, event_type="chat",
        session_id="old", payload_json="{}",
        created_at=datetime.utcnow() - timedelta(days=60),
    )
    db_session.add(old)
    db_session.commit()

    result = analytics_service.get_detailed(db_session, brand, days=7)
    assert result["total_chats"] == 0
    assert result["total_events"] == 0

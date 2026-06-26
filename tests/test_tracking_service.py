from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app import models
from app.services import tracking_service, brand_service


def _setup_brand_and_shipment(db: Session):
    brand = brand_service.get_or_create(db, "test-brand")
    provider = models.LogisticsProvider(
        slug="test-provider",
        name="Test Provider",
        provider_type="mock",
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)

    hub = models.HubMaster(
        provider_id=provider.id,
        hub_code="TST",
        hub_name="Test Hub",
        city="Test City",
    )
    db.add(hub)
    db.commit()
    db.refresh(hub)

    order = models.Order(
        brand_id=brand.id,
        order_id="TST-1001",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    shipment = models.Shipment(
        brand_id=brand.id,
        order_id=order.id,
        provider_id=provider.id,
        shipment_id="SHIP-TST-1001",
        tracking_number="TRK-TST-1001",
        current_status="in_transit",
        eta_date=datetime.now(timezone.utc).replace(tzinfo=None).date() + timedelta(days=2),
    )
    db.add(shipment)
    db.commit()
    db.refresh(shipment)

    event = models.TrackingEvent(
        shipment_id=shipment.id,
        status="in_transit",
        normalized_status="in_transit",
        hub_id=hub.id,
        location_text="In transit from Test Hub",
        event_timestamp=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=4),
        provider_event_id="evt-tst-001",
    )
    db.add(event)
    db.commit()

    return brand, shipment


class TestTrackingLookup:

    def test_lookup_success_by_order_id(self, db_session):
        brand, shipment = _setup_brand_and_shipment(db_session)
        result = tracking_service.lookup(
            db=db_session,
            brand=brand,
            lookup_type="auto",
            lookup_value="TST-1001",
            session_id="test-session",
            source="test",
        )
        assert result["success"] is True
        assert result["order_id"] == "TST-1001"
        assert result["tracking_number"] == "TRK-TST-1001"
        assert result["shipment_status"] == "in_transit"

    def test_lookup_success_by_tracking_number(self, db_session):
        brand, shipment = _setup_brand_and_shipment(db_session)
        result = tracking_service.lookup(
            db=db_session,
            brand=brand,
            lookup_type="tracking_number",
            lookup_value="TRK-TST-1001",
            session_id="test-session",
            source="test",
        )
        assert result["success"] is True
        assert result["tracking_number"] == "TRK-TST-1001"
        assert result["shipment_status"] == "in_transit"

    def test_lookup_not_found(self, db_session):
        brand, _ = _setup_brand_and_shipment(db_session)
        result = tracking_service.lookup(
            db=db_session,
            brand=brand,
            lookup_type="auto",
            lookup_value="NONEXISTENT-999",
            session_id="test-session",
            source="test",
        )
        assert result["success"] is False
        assert result["error_code"] == "not_found"

    def test_lookup_invalid_value(self, db_session):
        brand, _ = _setup_brand_and_shipment(db_session)
        result = tracking_service.lookup(
            db=db_session,
            brand=brand,
            lookup_type="auto",
            lookup_value="ab",
            session_id="test-session",
            source="test",
        )
        assert result["success"] is False
        assert result["error_code"] == "invalid_lookup_value"

    def test_lookup_rate_limited(self, db_session):
        brand, _ = _setup_brand_and_shipment(db_session)
        window_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        for i in range(25):
            db_session.add(models.TrackingRequest(
                brand_id=brand.id,
                session_id="test-session",
                lookup_value_hash="test",
                result_code="test",
                created_at=window_start + timedelta(seconds=i),
            ))
        db_session.commit()
        result = tracking_service.lookup(
            db=db_session,
            brand=brand,
            lookup_type="auto",
            lookup_value="TST-1001",
            session_id="test-session",
            source="test",
        )
        assert result["success"] is False
        assert result["error_code"] == "rate_limited"


class TestTrackingServiceValidation:

    def test_normalize_status_variants(self):
        assert tracking_service.normalize_status("in transit") == "in_transit"
        assert tracking_service.normalize_status("DELIVERED") == "delivered"
        assert tracking_service.normalize_status("Out For Delivery") == "out_for_delivery"
        assert tracking_service.normalize_status("at origin hub") == "at_origin_hub"
        assert tracking_service.normalize_status("CANCELLED") == "cancelled"

    def test_status_label(self):
        assert tracking_service.status_label("in_transit") == "In Transit"
        assert tracking_service.status_label("delivered") == "Delivered"
        assert tracking_service.status_label("at_destination_hub") == "At Destination Hub"
        assert tracking_service.status_label("unknown_status") == "Unknown Status"

    def test_allowed_transition_valid(self):
        assert tracking_service.allowed_transition("in_transit", "at_intermediate_hub")

    def test_allowed_transition_invalid(self):
        assert not tracking_service.allowed_transition("delivered", "in_transit")

    def test_allowed_transition_same(self):
        assert tracking_service.allowed_transition("in_transit", "in_transit")

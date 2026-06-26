from __future__ import annotations

import pytest
import sqlalchemy as sa


@pytest.fixture
def clean_engine():
    from sqlalchemy import create_engine
    from app.db import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    yield engine
    engine.dispose()


@pytest.fixture
def tables_created(clean_engine):
    from app.db import Base
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=clean_engine)
    return clean_engine


def test_init_db_creates_expected_tables(clean_engine):
    import app.db as db_module
    original_engine = db_module.engine
    try:
        db_module.engine = clean_engine
        db_module.init_db()
        inspector = sa.inspect(clean_engine)
        tables = set(inspector.get_table_names())

        expected = {
            "brands", "product_pages", "knowledge_sources", "chunks",
            "conversations", "messages", "leads", "analytics_events",
            "users", "api_tokens", "logistics_providers", "hub_master",
            "hub_routes", "orders", "shipments", "tracking_events",
            "tracking_cache", "shipment_eta", "tracking_requests",
            "tracking_overrides", "message_feedback", "conversation_contexts",
        }
        for t in expected:
            assert t in tables, f"Missing table: {t}"
    finally:
        db_module.engine = original_engine


def test_migrate_schema_idempotent(tables_created):
    from app.db import _migrate_schema
    _migrate_schema(tables_created)
    _migrate_schema(tables_created)


def test_get_db_yields_and_closes():
    import app.db as db_module
    original_engine = db_module.engine
    fresh = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    from app.db import Base
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=fresh)
    db_module.engine = fresh

    try:
        gen = db_module.get_db()
        session = next(gen)
        result = session.execute(sa.text("SELECT 1")).scalar()
        assert result == 1
        gen.close()
    finally:
        db_module.engine = original_engine

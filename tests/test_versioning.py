from __future__ import annotations
import os

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    os.environ["CHROMA_PATH"] = str(tmp_path / "chroma")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'db.sqlite'}"
    os.environ["USE_OLLAMA_EMBEDDINGS"] = "false"
    import chromadb
    import app.chroma_client as chroma_client
    monkeypatch.setattr(chroma_client, "get_client", lambda: chromadb.Client())
    monkeypatch.setattr(chroma_client, "_build_embedding_function", lambda: None)


def test_version_columns_exist(env):
    from sqlalchemy import inspect
    from app.db import engine
    inspector = inspect(engine)
    ks_columns = {c["name"] for c in inspector.get_columns("knowledge_sources")}
    assert "version" in ks_columns
    assert "is_active" in ks_columns
    assert "previous_source_id" in ks_columns


def _make_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import Base
    import app.models  # noqa: F401 - register tables on Base.metadata
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal(), engine


def test_get_or_version_source_creates_new(env):
    db, _ = _make_db()
    try:
        from app.brand_service import brand_service
        brand = brand_service.get_or_create(db, "testbrand")
        from app.ingestion_service import ingestion_service

        source = ingestion_service._get_or_version_source(db, brand, "test-source", "text")
        assert source.version == 1
        assert source.is_active is True
        assert source.previous_source_id is None
    finally:
        db.close()


def test_get_or_version_source_increments_on_reingest(env):
    db, _ = _make_db()
    try:
        from app.brand_service import brand_service
        brand = brand_service.get_or_create(db, "testbrand")
        from app.ingestion_service import ingestion_service

        v1 = ingestion_service._get_or_version_source(db, brand, "test-source", "text")
        assert v1.version == 1

        v2 = ingestion_service._get_or_version_source(db, brand, "test-source", "text")
        assert v2.version == 2
        assert v2.previous_source_id == v1.id

        db.refresh(v1)
        assert v1.is_active is False
    finally:
        db.close()


def test_active_sources_filter(env):
    db, _ = _make_db()
    try:
        from app.brand_service import brand_service
        brand = brand_service.get_or_create(db, "testbrand")
        from app.ingestion_service import ingestion_service

        v1 = ingestion_service._get_or_version_source(db, brand, "test-filter", "text")
        v2 = ingestion_service._get_or_version_source(db, brand, "test-filter", "text")

        active = db.query(type(v1)).filter_by(brand_id=brand.id, is_active=True).all()
        assert len(active) == 1
        assert active[0].id == v2.id
    finally:
        db.close()


def test_version_sources_are_independent(env):
    db, _ = _make_db()
    try:
        from app.brand_service import brand_service
        brand = brand_service.get_or_create(db, "testbrand")
        from app.ingestion_service import ingestion_service

        s1 = ingestion_service._get_or_version_source(db, brand, "source-a", "text")
        s2 = ingestion_service._get_or_version_source(db, brand, "source-b", "text")

        assert s1.version == 1
        assert s2.version == 1

        s1_v2 = ingestion_service._get_or_version_source(db, brand, "source-a", "text")
        assert s1_v2.version == 2
        assert s2.version == 1
    finally:
        db.close()

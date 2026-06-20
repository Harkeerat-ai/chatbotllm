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


def _make_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import Base
    import app.models  # noqa: F401 - register tables on Base.metadata
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def test_widget_config_defaults(env):
    db = _make_db()
    try:
        from app.brand_service import brand_service
        brand = brand_service.get_or_create(db, "testbrand")

        config = brand_service.get_widget_config(db, brand.slug)
        assert config.accent_color == "#f0a500"
        assert config.position == "bottom-right"
        assert config.width == "420px"
    finally:
        db.close()


def test_widget_config_update(env):
    db = _make_db()
    try:
        from app.brand_service import brand_service
        brand = brand_service.get_or_create(db, "testbrand")

        updated = brand_service.update_widget_config(db, brand.slug, {"accent_color": "#ff0000", "title": "My Bot"})
        assert updated.accent_color == "#ff0000"
        assert updated.title == "My Bot"

        config = brand_service.get_widget_config(db, brand.slug)
        assert config.accent_color == "#ff0000"
    finally:
        db.close()


def test_widget_config_partial_update(env):
    db = _make_db()
    try:
        from app.brand_service import brand_service
        brand = brand_service.get_or_create(db, "testbrand")

        config = brand_service.update_widget_config(db, brand.slug, {"logo_url": "https://example.com/logo.png"})
        assert config.logo_url == "https://example.com/logo.png"
        assert config.accent_color == "#f0a500"
    finally:
        db.close()


def test_widget_config_column_exists(env):
    from sqlalchemy import inspect
    from app.db import engine
    inspector = inspect(engine)
    br_columns = {c["name"] for c in inspector.get_columns("brands")}
    assert "widget_config_json" in br_columns

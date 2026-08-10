from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base

# Set production-safe defaults for tests to avoid startup assertions in lifespan
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pass-123")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-456")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-789")


@pytest.fixture
def db_session():
    import app.models  # ensure models are registered with Base.metadata
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

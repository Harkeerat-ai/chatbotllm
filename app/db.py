from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # SQLite-specific
)

SessionLocal = sessionmaker(autoflush=False, bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Call once on startup."""
    from app import models  # noqa: F401 — side-effect import
    Base.metadata.create_all(bind=engine)
    _migrate_schema(engine)


def _migrate_schema(engine):
    """Apply schema migrations for columns added after initial release."""
    import sqlalchemy as sa
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "messages" in existing_tables:
        msg_columns = {c["name"] for c in inspector.get_columns("messages")}
        if "suggested_questions_json" not in msg_columns:
            with engine.begin() as conn:
                conn.execute(
                    sa.text("ALTER TABLE messages ADD COLUMN suggested_questions_json TEXT DEFAULT '[]'")
                )
    if "brands" in existing_tables:
        br_columns = {c["name"] for c in inspector.get_columns("brands")}
        if "widget_config_json" not in br_columns:
            with engine.begin() as conn:
                conn.execute(
                    sa.text("ALTER TABLE brands ADD COLUMN widget_config_json TEXT DEFAULT '{}'")
                )
        if "language" not in br_columns:
            with engine.begin() as conn:
                conn.execute(
                    sa.text("ALTER TABLE brands ADD COLUMN language VARCHAR(10) DEFAULT 'en'")
                )
    if "conversations" in existing_tables:
        conv_columns = {c["name"] for c in inspector.get_columns("conversations")}
        if "summary_json" not in conv_columns:
            with engine.begin() as conn:
                conn.execute(
                    sa.text("ALTER TABLE conversations ADD COLUMN summary_json TEXT DEFAULT '{}'")
                )
    if "knowledge_sources" in existing_tables:
        ks_columns = {c["name"] for c in inspector.get_columns("knowledge_sources")}
        if "version" not in ks_columns:
            with engine.begin() as conn:
                conn.execute(sa.text("ALTER TABLE knowledge_sources ADD COLUMN version INTEGER DEFAULT 1"))
                conn.execute(sa.text("ALTER TABLE knowledge_sources ADD COLUMN is_active BOOLEAN DEFAULT 1"))
                conn.execute(sa.text("ALTER TABLE knowledge_sources ADD COLUMN previous_source_id INTEGER REFERENCES knowledge_sources(id)"))
                conn.execute(sa.text("UPDATE knowledge_sources SET version = 1, is_active = 1"))

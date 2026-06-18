"""
seed_service.py — bootstrap knowledge for every brand in knowledge/.

Scans knowledge/<brand_slug>/ and ingests .txt, .pdf, .json (faq), .csv (faq),
and .md files into ChromaDB + SQLite. Idempotent — skips brands that already
have knowledge sources.
"""

from __future__ import annotations
import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app import models
from app.brand_service import brand_service
from app.ingestion_service import ingestion_service

logger = logging.getLogger(__name__)

KNOWLEDGE_ROOT = Path(__file__).resolve().parent.parent / "knowledge"


def seed_knowledge(db: Session) -> None:
    if not KNOWLEDGE_ROOT.exists():
        logger.info("No knowledge/ directory found. Nothing to seed.")
        return

    for brand_dir in sorted(KNOWLEDGE_ROOT.iterdir()):
        if not brand_dir.is_dir():
            continue

        slug = brand_dir.name
        brand = brand_service.get_or_create(db, slug)

        existing = (
            db.query(models.KnowledgeSource)
            .filter_by(brand_id=brand.id)
            .first()
        )

        for fpath in sorted(brand_dir.iterdir()):
            suffix = fpath.suffix.lower()
            name = fpath.stem

            try:
                # Product pages are always seeded (idempotent via slug)
                if suffix == ".json" and "page" in name.lower():
                    items = json.loads(fpath.read_text())
                    if isinstance(items, dict):
                        items = [items]
                    src = ingestion_service.ingest_product_pages(db, brand, name, items)
                    logger.info("  [page] %s → %d pages", fpath.name, src.chunk_count)
                    continue

                # Legal policies are always seeded (idempotent via stable IDs)
                if suffix == ".json" and "legal" in name.lower():
                    policies = json.loads(fpath.read_text())
                    if isinstance(policies, dict):
                        policies = [policies]
                    src = ingestion_service.ingest_legal_policies(db, brand, name, policies)
                    logger.info("  [legal] %s → %d chunks", fpath.name, src.chunk_count)
                    continue

                # Skip non-page files if brand already seeded
                if existing:
                    continue

                if suffix == ".txt":
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    src = ingestion_service.ingest_text(db, brand, name, content)
                    logger.info("  [txt]  %s → %d chunks", fpath.name, src.chunk_count)

                elif suffix == ".pdf":
                    src = ingestion_service.ingest_pdf(db, brand, name, fpath.read_bytes())
                    logger.info("  [pdf]  %s → %d chunks", fpath.name, src.chunk_count)

                elif suffix == ".json" and "faq" in name.lower():
                    items = json.loads(fpath.read_text())
                    if isinstance(items, dict):
                        items = [items]
                    src = ingestion_service.ingest_faq_items(db, brand, name, items)
                    logger.info("  [faq]  %s → %d chunks", fpath.name, src.chunk_count)

                elif suffix == ".csv":
                    src = ingestion_service.ingest_faq_csv(db, brand, name, fpath.read_bytes())
                    logger.info("  [csv]  %s → %d chunks", fpath.name, src.chunk_count)

                elif suffix == ".md":
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    if content.strip() and not content.strip().startswith("Place"):
                        src = ingestion_service.ingest_text(db, brand, name, content)
                        logger.info("  [md]   %s → %d chunks", fpath.name, src.chunk_count)
            except Exception:
                logger.exception("Failed to ingest %s for brand '%s'", fpath.name, slug)

    logger.info("Seed complete.")

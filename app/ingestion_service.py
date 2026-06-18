"""
Ingestion service — PDF / text / FAQ → chunks → Chroma + SQLite.
"""

from __future__ import annotations
import io
import json
import logging
import csv
import time
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app import models
from app.chroma_client import get_collection, delete_collection
from app.config import get_settings
from app.ollama_client import ollama
from app.utils import chunk_text, make_chroma_id
from app.observability import INGEST_LATENCY, INGEST_BATCHES

logger = logging.getLogger(__name__)
settings = get_settings()


class IngestionService:
    def _upsert_chunks(
        self,
        db: Session,
        brand: models.Brand,
        source: models.KnowledgeSource,
        chunks: list[str],
        extra_metadata: dict | None = None,
        custom_ids: list[str] | None = None,
    ) -> int:
        """Embed and upsert chunks into ChromaDB + SQLite.

        When *custom_ids* is provided, those are used as ChromaDB document IDs
        instead of the default ``make_chroma_id(brand, source.id, i)``.
        """
        collection = get_collection(brand.slug)
        extra_metadata = extra_metadata or {}

        ids, documents, metadatas = [], [], []

        existing_chroma_ids: set[str] = set()
        if custom_ids is not None:
            existing_rows = (
                db.query(models.Chunk)
                .filter(models.Chunk.chroma_id.in_(custom_ids))
                .all()
            )
            existing_chroma_ids = {r.chroma_id for r in existing_rows}
            lookup = {r.chroma_id: r for r in existing_rows}

        for i, chunk in enumerate(chunks):
            if not chunk.strip():
                continue

            if custom_ids is not None:
                cid = custom_ids[i]
            else:
                cid = make_chroma_id(brand.slug, source.id, i)
            meta = {
                "brand": brand.slug,
                "source_id": source.id,
                "source_name": source.name,
                "source_type": source.source_type,
                **extra_metadata,
            }

            ids.append(cid)
            documents.append(chunk)
            metadatas.append(meta)

            if cid in existing_chroma_ids:
                row = lookup[cid]
                row.content = chunk
                row.metadata_json = json.dumps(meta)
            else:
                db_chunk = models.Chunk(
                    brand_id=brand.id,
                    source_id=source.id,
                    chroma_id=cid,
                    content=chunk,
                    metadata_json=json.dumps(meta),
                )
                db.add(db_chunk)

        if ids:
            # Upsert in batches of 100 and record metrics
            start_time = time.monotonic()
            batch_count = 0
            for start in range(0, len(ids), 100):
                collection.upsert(
                    ids=ids[start : start + 100],
                    documents=documents[start : start + 100],
                    metadatas=metadatas[start : start + 100],
                )
                batch_count += 1
            try:
                INGEST_BATCHES.labels(brand=brand.slug).inc(batch_count)
                INGEST_LATENCY.labels(brand=brand.slug).observe(time.monotonic() - start_time)
            except Exception:
                logger.debug("Failed to record ingest metrics")

        db.commit()
        return len(ids)

    # ── Text ─────────────────────────────────────────────────────────────────

    def ingest_text(
        self,
        db: Session,
        brand: models.Brand,
        source_name: str,
        content: str,
        metadata: dict | None = None,
    ) -> models.KnowledgeSource:
        source = models.KnowledgeSource(
            brand_id=brand.id,
            name=source_name,
            source_type="text",
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        chunks = list(chunk_text(content, settings.chunk_size, settings.chunk_overlap))
        count = self._upsert_chunks(db, brand, source, chunks, metadata)
        source.chunk_count = count
        db.commit()
        return source

    # ── PDF ──────────────────────────────────────────────────────────────────

    def ingest_pdf(
        self,
        db: Session,
        brand: models.Brand,
        source_name: str,
        file_bytes: bytes,
    ) -> models.KnowledgeSource:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise RuntimeError("PyMuPDF is not installed. Run: pip install pymupdf")

        source = models.KnowledgeSource(
            brand_id=brand.id,
            name=source_name,
            source_type="pdf",
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        all_chunks: list[str] = []
        for page_num, page in enumerate(doc, start=1):
            page_text = page.get_text("text")
            page_chunks = list(chunk_text(page_text, settings.chunk_size, settings.chunk_overlap))
            for c in page_chunks:
                all_chunks.append(c)

        count = self._upsert_chunks(
            db, brand, source, all_chunks,
            {"page_count": len(doc)},
        )
        source.chunk_count = count
        db.commit()
        return source

    # ── FAQ ──────────────────────────────────────────────────────────────────

    def ingest_faq_items(
        self,
        db: Session,
        brand: models.Brand,
        source_name: str,
        items: list[dict],
    ) -> models.KnowledgeSource:
        source = models.KnowledgeSource(
            brand_id=brand.id,
            name=source_name,
            source_type="faq",
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        chunks = [
            f"Q: {item.get('question', '')}\nA: {item.get('answer', '')}"
            for item in items
            if item.get("question") and item.get("answer")
        ]

        count = self._upsert_chunks(db, brand, source, chunks)
        source.chunk_count = count
        db.commit()
        return source

    def ingest_faq_csv(
        self,
        db: Session,
        brand: models.Brand,
        source_name: str,
        csv_bytes: bytes,
    ) -> models.KnowledgeSource:
        text = csv_bytes.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        items = []
        for row in reader:
            q = row.get("question") or row.get("Question") or ""
            a = row.get("answer") or row.get("Answer") or ""
            if q and a:
                items.append({"question": q, "answer": a})
        return self.ingest_faq_items(db, brand, source_name, items)

    def ingest_faq_json(
        self,
        db: Session,
        brand: models.Brand,
        source_name: str,
        json_bytes: bytes,
    ) -> models.KnowledgeSource:
        items = json.loads(json_bytes.decode("utf-8", errors="replace"))
        if isinstance(items, dict):
            items = [items]
        return self.ingest_faq_items(db, brand, source_name, items)


    def ingest_structured_kb(
        self,
        db: Session,
        brand: models.Brand,
        source_name: str,
        documents: list[dict],
    ) -> models.KnowledgeSource:
        """Ingest a pre-structured knowledge base where each dict has
        ``id``, ``category``, ``title``, ``source_url``, and ``content``.

        The document ``id`` is used as the stable ChromaDB upsert key,
        making the pipeline fully idempotent.
        """
        source = models.KnowledgeSource(
            brand_id=brand.id,
            name=source_name,
            source_type="kb",
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        chunks: list[str] = []
        custom_ids: list[str] = []
        extra_meta: list[dict] = []

        for doc in documents:
            cid = doc.get("id", "").strip()
            content = doc.get("content", "").strip()
            if not cid or not content:
                continue

            chunks.append(content)
            custom_ids.append(cid)
            extra_meta.append({
                "doc_id": cid,
                "category": doc.get("category", ""),
                "title": doc.get("title", ""),
                "source_url": doc.get("source_url", ""),
            })

        count = self._upsert_chunks(
            db, brand, source, chunks,
            extra_metadata={"source_type": "kb"},
            custom_ids=custom_ids,
        )

        # Patch per-chunk metadata into the SQLite mirror
        chunk_rows = (
            db.query(models.Chunk)
            .filter_by(source_id=source.id)
            .order_by(models.Chunk.id)
            .all()
        )
        for row, meta in zip(chunk_rows, extra_meta):
            existing = json.loads(row.metadata_json)
            existing.update(meta)
            row.metadata_json = json.dumps(existing)
        db.commit()

        source.chunk_count = count
        db.commit()
        return source

    def ingest_product_pages(
        self,
        db: Session,
        brand: models.Brand,
        source_name: str,
        items: list[dict],
    ) -> models.KnowledgeSource:
        source = models.KnowledgeSource(
            brand_id=brand.id,
            name=source_name,
            source_type="page",
        )
        db.add(source)
        db.flush()

        count = 0
        for item in items:
            slug = item.get("slug", "").strip()
            if not slug:
                continue
            existing = (
                db.query(models.ProductPage)
                .filter_by(brand_id=brand.id, slug=slug)
                .first()
            )
            if existing:
                existing.url = item.get("url", existing.url)
                existing.title = item.get("title", existing.title)
                existing.keywords = item.get("keywords", existing.keywords)
            else:
                db.add(models.ProductPage(
                    brand_id=brand.id,
                    slug=slug,
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    keywords=item.get("keywords", ""),
                ))
            count += 1

        source.chunk_count = count
        db.commit()
        logger.info("Ingested %d product pages for brand '%s'", count, brand.slug)
        return source


ingestion_service = IngestionService()

#!/usr/bin/env python3
"""Reproduce RAG vs tracking flow for a tracking query."""
import logging
import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logging.basicConfig(level=logging.DEBUG)

from app.db import init_db, SessionLocal
from app import models
from app.services import rag_service, tracking_service
from app.brand_service import brand_service


def main():
    init_db()
    db = SessionLocal()
    try:
        # Ensure demo brands + shipments exist
        tracking_service.ensure_defaults(db)

        brand = db.query(models.Brand).filter_by(slug="kalp").first()
        if not brand:
            brand = brand_service.get_or_create(db, "kalp")

        # Test messages
        messages = [
            "Where is my order TRK-KALP-1001?",
            "Can you track my order KALP-1001?",
            "I want to know the delivery status of my order.",
            "What is KALP?",
        ]

        import asyncio

        for idx, msg in enumerate(messages, start=1):
            print("\n--- Test", idx, "message:", msg)
            should = tracking_service.should_handle_chat(msg, [])
            print("should_handle_chat:", should)
            res = asyncio.run(rag_service.ask(db=db, brand=brand, session_id=f"test-{idx}", user_message=msg))
            print("Answer:")
            print(res["answer"])
            print("Sources:", res.get("sources"))
    finally:
        db.close()


if __name__ == '__main__':
    main()

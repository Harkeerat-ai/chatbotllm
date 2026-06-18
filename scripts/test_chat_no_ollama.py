#!/usr/bin/env python3
"""Run a chat-like call to rag_service.ask while forcing Ollama to be unavailable.
This ensures the tracking NLP fallback path is used deterministically.
"""
import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Force Ollama to be unreachable for this run
os.environ['OLLAMA_BASE_URL'] = 'http://127.0.0.1:9999'

from app.db import init_db, SessionLocal
from app.services import rag_service, tracking_service
from app import models


def main():
    init_db()
    db = SessionLocal()
    try:
        # Ensure demo shipments exist
        tracking_service.ensure_defaults(db)
        brand = db.query(models.Brand).filter_by(slug="kalp").first()
        if not brand:
            print("Brand 'kalp' not found")
            return

        msg = "Where is my order TRK-KALP-1001?"
        print("Message:", msg)
        import asyncio
        res = asyncio.run(rag_service.ask(db=db, brand=brand, session_id="smoke-no-ollama", user_message=msg))
        print("Response:")
        print(res)
    finally:
        db.close()


if __name__ == '__main__':
    main()

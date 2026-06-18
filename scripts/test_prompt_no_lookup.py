#!/usr/bin/env python3
"""Test that a tracking-intent message without a lookup ID prompts for the ID."""
import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Force Ollama offline to avoid network calls
os.environ['OLLAMA_BASE_URL'] = 'http://127.0.0.1:9999'

from app.db import init_db, SessionLocal
from app.services import rag_service, tracking_service


def main():
    init_db()
    db = SessionLocal()
    try:
        tracking_service.ensure_defaults(db)
        brand = db.query.__self__.session.bind.pool._creator.__self__ if False else db.query
        # find brand kalp
        from app import models
        brand = db.query(models.Brand).filter_by(slug="kalp").first()
        if not brand:
            print("brand 'kalp' not found")
            return
        msg = "Where is my order?"
        print("Message:", msg)
        import asyncio
        res = asyncio.run(rag_service.ask(db=db, brand=brand, session_id="prompt-no-lookup", user_message=msg))
        print("Response:")
        print(res)
    finally:
        db.close()

if __name__ == '__main__':
    main()

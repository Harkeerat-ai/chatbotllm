#!/usr/bin/env python3
"""Test a single tracking chat request and print the result or exception."""
import logging
import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logging.basicConfig(level=logging.DEBUG)

from app.db import init_db, SessionLocal
from app.services import rag_service, tracking_service
from app import models


def main():
    init_db()
    db = SessionLocal()
    try:
        tracking_service.ensure_defaults(db)
        brand = db.query(models.Brand).filter_by(slug="kalp").first()
        if not brand:
            print("Brand 'kalp' not found")
            return
        msg = "Where is my order TRK-KALP-1001?"
        print("calling rag_service.ask with message:", msg)
        try:
            import asyncio
            res = asyncio.run(rag_service.ask(db=db, brand=brand, session_id="test-single", user_message=msg))
            print("Result:")
            print(res)
        except Exception as e:
            print("rag_service.ask raised:", type(e), e)
    finally:
        db.close()

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Inspect application SQLite DB for seeded KnowledgeSource records."""
import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.db import SessionLocal, init_db
from app import models


def main():
    init_db()
    db = SessionLocal()
    try:
        sources = db.query(models.KnowledgeSource).all()
        print(f"Knowledge sources: {len(sources)}")
        for s in sources:
            print(f"- id={s.id} brand_id={s.brand_id} name={s.name} chunks={s.chunk_count} type={s.source_type}")
        chunks = db.query(models.Chunk).count()
        print(f"Total chunks: {chunks}")
    finally:
        db.close()

if __name__ == '__main__':
    main()

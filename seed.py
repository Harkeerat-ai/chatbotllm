"""
seed.py — CLI entry point to seed knowledge from knowledge/ directory.

Usage:
    python seed.py

Delegates to app.seed_service.seed_knowledge for the actual logic.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.db import SessionLocal, init_db
from app.seed_service import seed_knowledge


def seed():
    init_db()
    db = SessionLocal()
    try:
        seed_knowledge(db)
    finally:
        db.close()


if __name__ == "__main__":
    seed()

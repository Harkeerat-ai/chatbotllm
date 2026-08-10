"""
reset_brand.py — delete a brand's vector + SQLite knowledge data so seed.py can re-seed it.

Usage:
    python reset_brand.py kalp        # reset one brand
    python reset_brand.py --all       # reset every brand

Run python seed.py afterwards to re-ingest with the correct embedding function.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.db import SessionLocal, init_db
from app import models
from app.chroma_client import delete_collection


def reset_brand(brand_slug: str, db) -> None:
    brand = db.query(models.Brand).filter_by(slug=brand_slug).first()
    if not brand:
        print(f"  [{brand_slug}] not found in app.db — skipping.")
        return

    # 1. Drop ChromaDB collection (removes all stored vectors)
    delete_collection(brand_slug)
    print(f"  [{brand_slug}] ChromaDB collection deleted")

    # 2. Remove SQLite chunks
    n_chunks = db.query(models.Chunk).filter_by(brand_id=brand.id).delete()
    print(f"  [{brand_slug}] {n_chunks} chunks removed from app.db")

    # 3. Remove knowledge sources (seed_service skips brands that have any)
    n_sources = db.query(models.KnowledgeSource).filter_by(brand_id=brand.id).delete()
    print(f"  [{brand_slug}] {n_sources} knowledge sources removed from app.db")

    db.commit()
    print(f"  [{brand_slug}] reset complete")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python reset_brand.py <slug> | --all")
        sys.exit(1)

    init_db()
    db = SessionLocal()
    try:
        if sys.argv[1] == "--all":
            for brand in db.query(models.Brand).all():
                reset_brand(brand.slug, db)
        else:
            reset_brand(sys.argv[1], db)
    finally:
        db.close()

    print("\nDone. Now run:  python seed.py")
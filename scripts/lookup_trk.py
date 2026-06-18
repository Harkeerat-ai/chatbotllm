import os
import json
import tempfile

# Use an isolated DB for this check
tmp_db = os.path.join(os.getcwd(), "tmp_tracking_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db}"
os.environ["CHROMA_PATH"] = os.path.join(os.getcwd(), "tmp_vector_db")
os.environ["USE_OLLAMA_EMBEDDINGS"] = "false"

from app.db import init_db, SessionLocal
from app.tracking_service import tracking_service
from app.brand_service import brand_service

init_db()
db = SessionLocal()
try:
    tracking_service.ensure_defaults(db)
    brand = brand_service.get_or_create(db, "kalp")
    res = tracking_service.lookup(db, brand, "tracking_number", "TRK-KALP-1001")
    print(json.dumps(res, default=str, indent=2))
finally:
    db.close()

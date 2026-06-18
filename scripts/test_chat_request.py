import sys
sys.path.insert(0, '.')
from app.main import app
from fastapi.testclient import TestClient
from app.db import init_db, SessionLocal
from app.brand_service import brand_service
import json

init_db()
_db = SessionLocal()
try:
    brand = brand_service.get_or_create(_db, 'kalp')
finally:
    _db.close()

client = TestClient(app)
resp = client.post(f"/api/{brand.slug}/chat", json={"message":"where is TRK-KALP-1001","session_id":"t1","allow_unverified_tracking":True})
print(resp.status_code)
print(json.dumps(resp.json(), indent=2, default=str))

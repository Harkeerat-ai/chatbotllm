import sys
sys.path.insert(0, '.')
from app.db import init_db, SessionLocal
from app.brand_service import brand_service
from app.rag_service import rag_service
from app import models
import json

init_db()
db = SessionLocal()
try:
    brand = brand_service.get_or_create(db, 'kalp')
finally:
    db.close()

# Call RAGService.ask and print response
import asyncio

res = asyncio.run(rag_service.ask(
    db=db,
    brand=brand,
    session_id='t-repro',
    user_message='where is my order trk-kalp-1001 this was my question',
    allow_unverified_tracking=True,
))
print('RAG response:')
print(json.dumps(res, default=str, indent=2))

# Inspect conversation messages in DB
DB = SessionLocal()
try:
    conv = DB.query(models.Conversation).filter_by(brand_id=brand.id, session_id='t-repro').first()
    if conv:
        msgs = DB.query(models.Message).filter_by(conversation_id=conv.id).order_by(models.Message.created_at).all()
        print('\nConversation messages:')
        for m in msgs:
            print(f"{m.role}: {m.content}")
    else:
        print('\nNo conversation found')
finally:
    DB.close()

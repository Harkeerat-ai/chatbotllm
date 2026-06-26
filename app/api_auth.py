import hashlib
import secrets
import logging
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

logger = logging.getLogger(__name__)

def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

def generate_api_key() -> tuple[str, str]:
    raw = "rag_" + secrets.token_hex(32)
    return raw, hash_api_key(raw)

def require_api_key(request: Request, db: Session = Depends(get_db)):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    key = auth[7:]
    key_hash = hash_api_key(key)
    token = db.query(models.ApiToken).filter_by(token_hash=key_hash, is_active=True).first()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    token.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return token

def create_initial_api_key(db: Session) -> str:
    existing = db.query(models.ApiToken).first()
    if existing:
        logger.info("API key already exists, skipping creation")
        return ""
    raw, key_hash = generate_api_key()
    token = models.ApiToken(
        token_hash=key_hash,
        label="initial-setup-key",
        is_active=True,
    )
    db.add(token)
    db.commit()
    logger.info("Created initial API key")
    return raw

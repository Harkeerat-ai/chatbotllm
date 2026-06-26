"""
Auth service — admin session authentication.
"""

from __future__ import annotations
import logging
from hmac import compare_digest

from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.utils import hash_password, verify_password

logger = logging.getLogger(__name__)
settings = get_settings()


class AuthService:
    def authenticate(self, db: Session, username: str, password: str) -> bool:
        user = db.query(models.User).filter_by(username=username, is_active=True).first()
        if user:
            return verify_password(password, user.hashed_password)
        # Fallback to env-configured admin credentials
        return (
            compare_digest(username, settings.admin_username)
            and compare_digest(password, settings.admin_password)
        )

    def ensure_admin_user(self, db: Session) -> None:
        existing = db.query(models.User).filter_by(username=settings.admin_username).first()
        hashed = hash_password(settings.admin_password)
        if existing:
            existing.hashed_password = hashed
        else:
            user = models.User(
                username=settings.admin_username,
                hashed_password=hashed,
            )
            db.add(user)
        db.commit()


auth_service = AuthService()

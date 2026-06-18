from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app import models


class ConversationRepository:
    """Centralises conversation + message persistence.

    Each public method issues *exactly one* ``commit()`` regardless of how
    many rows are written.  Non-critical writes (context mutations, analytics
    events) can be deferred via ``defer()`` and flushed together in a single
    later commit via ``flush_deferred()``.
    """

    def __init__(self) -> None:
        self._deferred: list[Any] = []

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------

    def save_conversation(
        self, db: Session, brand_id: int, session_id: str
    ) -> models.Conversation:
        """Return existing conversation or create + persist a new one.

        Issues exactly one ``commit()`` when creating a new row.
        """
        conv = (
            db.query(models.Conversation)
            .filter_by(brand_id=brand_id, session_id=session_id)
            .first()
        )
        if conv:
            return conv
        conv = models.Conversation(brand_id=brand_id, session_id=session_id)
        db.add(conv)
        db.commit()
        db.refresh(conv)
        return conv

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def save_messages(
        self, db: Session, messages: list[models.Message]
    ) -> None:
        """Persist *all* messages in a single ``commit()``."""
        if not messages:
            return
        db.add_all(messages)
        db.commit()

    # ------------------------------------------------------------------
    # Deferred writes (context updates, analytics, logging …)
    # ------------------------------------------------------------------

    def defer(self, obj: Any) -> None:
        """Queue a non-critical write for a later ``flush_deferred()``."""
        self._deferred.append(obj)

    def flush_deferred(self, db: Session) -> None:
        """Flush all queued deferred writes in a single ``commit()``."""
        if not self._deferred:
            return
        db.add_all(self._deferred)
        db.commit()
        self._deferred.clear()


# Module-level singleton for convenience.
conversation_repo = ConversationRepository()

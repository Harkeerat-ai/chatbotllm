from __future__ import annotations
import re
import uuid
import hashlib
from typing import Generator


def slugify(text: str) -> str:
    """Convert arbitrary text to a safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text


def make_chroma_id(brand: str, source_id: int, index: int) -> str:
    """Deterministic, collision-resistant ChromaDB document ID."""
    key = f"{brand}::{source_id}::{index}"
    return hashlib.sha1(key.encode()).hexdigest()


def generate_session_id() -> str:
    return str(uuid.uuid4())


def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 64,
) -> Generator[str, None, None]:
    """
    Yield overlapping word-boundary chunks from a block of text.
    Uses word-level splitting so we never cut mid-word.
    """
    words = text.split()
    if not words:
        return

    step = max(1, chunk_size - overlap)
    i = 0
    while i < len(words):
        chunk_words = words[i : i + chunk_size]
        yield " ".join(chunk_words)
        if i + chunk_size >= len(words):
            break
        i += step


def truncate(text: str, max_chars: int = 3000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + " …"


import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

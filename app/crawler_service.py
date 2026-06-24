"""
Crawler service — BFS website crawler for ingestion.
"""

from __future__ import annotations
import ipaddress
import logging
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app import models
from app.chroma_client import get_collection
from app.config import get_settings
from app.ollama_client import ollama
from app.services import ingestion_service
from app.utils import chunk_text, make_chroma_id

logger = logging.getLogger(__name__)
settings = get_settings()


def _validate_url_external(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise ValueError("Crawling localhost is not allowed")
    if host.startswith("169.254."):
        raise ValueError("Crawling link-local addresses is not allowed")
    allowed = getattr(settings, "allowed_crawl_domains", [])
    if allowed and host in allowed:
        return
    try:
        ip = socket.gethostbyname(host)
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_unspecified:
            raise ValueError("Crawling private or internal IPs is not allowed")
    except socket.gaierror:
        raise ValueError("Could not resolve host — crawling blocked")


class CrawlerService:
    def crawl(
        self,
        db: Session,
        brand: models.Brand,
        url: str,
        max_pages: int = 10,
        max_depth: int = 1,
        same_domain_only: bool = True,
    ) -> models.KnowledgeSource:
        _validate_url_external(url)
        parsed_root = urlparse(url)
        root_domain = parsed_root.netloc

        source = models.KnowledgeSource(
            brand_id=brand.id,
            name=f"Crawl: {url}",
            source_type="crawl",
            uri=url,
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(url, 0)]
        all_chunks: list[str] = []

        while queue and len(visited) < max_pages:
            current_url, depth = queue.pop(0)
            if current_url in visited:
                continue
            if same_domain_only and urlparse(current_url).netloc != root_domain:
                continue

            visited.add(current_url)

            try:
                resp = httpx.get(
                    current_url,
                    timeout=settings.crawler_timeout,
                    headers={"User-Agent": "AgenticRAG/1.0"},
                )
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")

                # Strip noise
                for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    tag.decompose()

                page_text = soup.get_text(separator=" ", strip=True)
                page_chunks = list(chunk_text(page_text, settings.chunk_size, settings.chunk_overlap))
                all_chunks.extend(page_chunks)

                # Enqueue links
                if depth < max_depth:
                    for a in soup.find_all("a", href=True):
                        href = urljoin(current_url, a["href"])
                        if href not in visited:
                            queue.append((href, depth + 1))

            except Exception as e:
                logger.warning("Crawl error at %s: %s", current_url, e)

        count = ingestion_service._upsert_chunks(
            db, brand, source, all_chunks,
            {"crawled_url": url, "pages_visited": len(visited)},
        )
        source.chunk_count = count
        db.commit()
        return source


crawler_service = CrawlerService()

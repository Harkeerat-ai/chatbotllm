from __future__ import annotations
import json
import logging
import time
import hashlib
import threading
from datetime import datetime, timedelta
from typing import Any

from cachetools import TTLCache
from sqlalchemy.orm import Session
import difflib

from app import models
from app.models import ProductPage
from app.chroma_client import get_collection
from app.cross_encoder_onnx import CrossEncoderONNX
from app.observability import (
    CHAT_REQUESTS,
    CHAT_LATENCY,
    CHROMA_QUERIES,
    CHROMA_ERRORS,
    TRACKING_LOOKUPS,
)
from app.config import get_settings
from app.conversation import state_machine, MAX_TRACKING_RETRIES
from app.conversation_repository import conversation_repo
from app.ollama_client import ollama
from app.tracking_service import tracking_service
from app.utils import chunk_text, make_chroma_id

logger = logging.getLogger(__name__)

_RERANKER: CrossEncoderONNX | None = None
_resp_cache: TTLCache = TTLCache(maxsize=256, ttl=3600)
_resp_lock = threading.Lock()

NAVIGATION_KEYWORDS = sorted({"take me to", "go to", "show me", "open", "navigate", "link", "take me"}, key=len, reverse=True)


def _get_reranker() -> CrossEncoderONNX:
    global _RERANKER
    if _RERANKER is None:
        _RERANKER = CrossEncoderONNX()
    return _RERANKER

SYSTEM_PROMPT = (
    "You are a friendly and knowledgeable assistant for {brand_name}. "
    "Answer the customer's question clearly using only the provided context. "
    "Keep your answer to 2\u20133 sentences. "
    "Write in plain text only \u2014 no bullet points, no markdown, no headers, no URLs. "
    "If the context does not contain the answer, say so politely in one sentence "
    "and suggest the customer reach out to {brand_name} support directly."
)

LOGISTICS_SYSTEM_PROMPT = (
    "You are a helpful logistics assistant for {brand_name}. "
    "Given the tracking data below, write a friendly, natural language update "
    "for the customer. Be concise (2-4 sentences) but include the key information: "
    "current status, current hub, ETA, and any delay reasons. "
    "Write in plain text only - no markdown, no formatting, no bullet points."
)


settings = get_settings()


class RAGService:
    async def ask(
        self,
        db: Session,
        brand: models.Brand,
        session_id: str,
        user_message: str,
        top_k: int | None = None,
        allow_unverified_tracking: bool = False,
    ) -> dict[str, Any]:
        if top_k is None:
            top_k = settings.default_top_k
        # start time for latency measurements when returning early
        t0 = time.monotonic()
        product_urls: list[dict] = []
        _key = hashlib.md5(f"{brand.slug}:{user_message}".lower().encode()).hexdigest()
        with _resp_lock:
            _cached = _resp_cache.get(_key)
        if _cached:
            return _cached
        # 1. Retrieve or create conversation
        conv = conversation_repo.save_conversation(db, brand.id, session_id)

        # 2. Load recent memory (last 6 turns)
        recent_msgs = (
            db.query(models.Message)
            .filter_by(conversation_id=conv.id)
            .order_by(models.Message.created_at.desc())
            .limit(12)
            .all()
        )
        history = [
            {"role": m.role, "content": m.content}
            for m in reversed(recent_msgs)
        ]

        collection = get_collection(brand.slug)
        t_setup = time.monotonic() - t0

        # 3. Accumulate messages — single commit at each return point
        user_msg = models.Message(
            conversation_id=conv.id,
            role="user",
            content=user_message,
        )
        pending_messages: list[models.Message] = [user_msg]

        # 4. State-machine-driven tracking flow
        ctx = state_machine.get_context(db, conv.id)

        try:
            if state_machine.is_tracking_active(ctx):
                result = await self._handle_active_tracking(
                    db, brand, session_id, conv, ctx, user_message, history,
                    allow_unverified_tracking=allow_unverified_tracking,
                    pending_messages=pending_messages,
                    product_urls=product_urls,
                )
                if result:
                    return result
                ctx = state_machine.get_context(db, conv.id)

            lookup_value, lookup_type, confidence = self._safe_extract_lookup(user_message)

            # Auto-trigger on explicit lookup token (e.g. TRK-..., KALP-1001)
            if lookup_value and confidence >= 60:
                logger.info(
                    "Auto-triggering tracking lookup for extracted value=%s (conf=%s)",
                    lookup_value, confidence,
                )
                result = await self._handle_new_tracking_intent(
                    db, brand, session_id, conv, ctx, user_message, history,
                    allow_unverified_tracking=allow_unverified_tracking,
                    pending_messages=pending_messages,
                    product_urls=product_urls,
                )
                if result:
                    return result

            if tracking_service.should_handle_chat(user_message, history):
                # Bypass tracking if user is asking for a page link (no tracking number)
                msg_lower = user_message.lower()
                if any(kw in msg_lower for kw in NAVIGATION_KEYWORDS) and not (lookup_value and confidence >= 60):
                    logger.info("Navigation intent detected — bypassing tracking flow")
                else:
                    result = await self._handle_new_tracking_intent(
                        db, brand, session_id, conv, ctx, user_message, history,
                        allow_unverified_tracking=allow_unverified_tracking,
                        pending_messages=pending_messages,
                        product_urls=product_urls,
                    )
                    if result:
                        return result
        except Exception as e:
            logger.exception(
                "Tracking flow failed — brand=%s session=%s message=%.80s err=%s",
                brand.slug, session_id, user_message, e,
            )
            state_machine.reset(db, ctx)

            answer = (
                "I'm having trouble accessing the tracking system right now. "
                "Please try again later or provide your order ID or tracking number and I'll retry."
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            asst_msg = models.Message(
                conversation_id=conv.id,
                role="assistant",
                content=answer,
                latency_ms=latency_ms,
            )
            conversation_repo.save_messages(db, pending_messages + [asst_msg])
            conversation_repo.defer(
                models.AnalyticsEvent(
                    brand_id=brand.id,
                    event_type="chat",
                    session_id=session_id,
                    payload_json=json.dumps({"query_len": len(user_message), "latency_ms": latency_ms, "error": "tracking_flow_failed"}),
                )
            )
            conversation_repo.flush_deferred(db)

            return {
                "brand": brand.slug,
                "session_id": session_id,
                "answer": answer,
                "sources": [],
                "urls": product_urls,
                "latency_ms": latency_ms,
            }


        blocked = self._block_rag_for_tracking(
            db, brand, session_id, conv, user_message, history, pending_messages, t0,
            product_urls=product_urls,
        )
        if blocked:
            return blocked

        # 5. Vector retrieval
        sources: list[str] = []
        context = ""

        TRACKING_KEYWORDS = {"order","track","delivery","shipment","dispatch","arrive","late","return","refund"}
        is_tracking = bool(TRACKING_KEYWORDS.intersection(user_message.lower().split()))
        effective_top_k = top_k if is_tracking else 1

        try:
            results = collection.query(query_texts=[user_message], n_results=effective_top_k)
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]

            if docs and len(docs) > 1:
                pairs = [(user_message, doc) for doc in docs]
                scores = _get_reranker().predict(pairs)
                scored = sorted(
                    zip(scores, docs, metas), key=lambda x: x[0], reverse=True
                )[:3]
                docs = [d for _, d, _ in scored]
                metas = [m for _, _, m in scored]

            context = "\n\n".join(doc[:1200] for doc in docs)
            sources = [m.get("source_name", "") for m in metas if m.get("source_name")]

            # Product page lookup — only on explicit navigation intent
            msg_lower = user_message.lower()
            if any(kw in msg_lower for kw in NAVIGATION_KEYWORDS):
                try:
                    search_term = msg_lower
                    for phrase in NAVIGATION_KEYWORDS:
                        if phrase in msg_lower:
                            search_term = msg_lower.split(phrase, 1)[1].strip().rstrip(".!?' ")
                            break
                    from sqlalchemy import or_
                    search_words = [
                        w for w in search_term.replace("'s", " ").split()
                        if len(w) > 2
                    ]
                    page = (
                        db.query(ProductPage)
                        .filter(
                            ProductPage.brand_id == brand.id,
                            or_(
                                ProductPage.keywords.ilike(f"%{search_term}%"),
                                ProductPage.title.ilike(f"%{search_term}%"),
                                *[ProductPage.keywords.ilike(f"%{w}%") for w in search_words],
                            ),
                        )
                        .first()
                    )
                    if page:
                        answer = f"You're now on the {page.title} product page."
                        elapsed_ms = int((time.monotonic() - t0) * 1000)
                        logger.info("Product page link: %s → %s (%.2fs)", page.title, page.url, elapsed_ms / 1000)
                        return {
                            "answer": answer,
                            "session_id": session_id,
                            "latency_ms": elapsed_ms,
                            "urls": [{"title": page.title, "url": page.url}],
                            "brand": brand.slug,
                            "sources": [],
                        }

                    all_pages = (
                        db.query(ProductPage)
                        .filter(ProductPage.brand_id == brand.id)
                        .all()
                    )
                    candidates = []
                    for p in all_pages:
                        candidates.append(p.title)
                        for kw in p.keywords.split(","):
                            candidates.append(kw.strip())
                    candidates = [c for c in candidates if c]

                    close = difflib.get_close_matches(search_term, candidates, n=1, cutoff=0.6)
                    if not close:
                        for w in search_words:
                            close = difflib.get_close_matches(w, candidates, n=1, cutoff=0.6)
                            if close:
                                break

                    if close:
                        match = close[0]
                        match_lower = match.lower()
                        matched_page = next(
                            (p for p in all_pages
                             if match_lower in p.title.lower()
                             or any(match_lower in kw.strip().lower() for kw in p.keywords.split(","))),
                            None,
                        )
                        if matched_page:
                            answer = (
                                f"I couldn't find '{search_term}'. "
                                f"Did you mean '{matched_page.title}'?"
                            )
                            elapsed_ms = int((time.monotonic() - t0) * 1000)
                            return {
                                "answer": answer,
                                "session_id": session_id,
                                "latency_ms": elapsed_ms,
                                "urls": [{"title": matched_page.title, "url": matched_page.url}],
                                "brand": brand.slug,
                                "sources": [],
                            }

                    titles = [p.title for p in all_pages if p.title]
                    answer = (
                        f"I couldn't find a page for '{search_term}'. "
                        f"Available pages: {', '.join(titles)}."
                    )
                    elapsed_ms = int((time.monotonic() - t0) * 1000)
                    return {
                        "answer": answer,
                        "session_id": session_id,
                        "latency_ms": elapsed_ms,
                        "urls": [{"title": p.title, "url": p.url} for p in all_pages if p.title],
                        "brand": brand.slug,
                        "sources": [],
                    }
                except Exception:
                    logger.debug("Product page lookup failed", exc_info=True)

            t_rag = time.monotonic() - t0
            logger.info("Timing: setup=%.2fs rag=%.2fs (docs=%d, top_k=%s)", t_setup, t_rag, len(docs), effective_top_k)
            logger.debug(
                "Chroma query returned %d documents for brand %s (top_k=%s)",
                len(docs), brand.slug, top_k,
            )
            try:
                CHROMA_QUERIES.labels(brand=brand.slug).inc()
            except Exception:
                logger.debug("Failed to increment CHROMA_QUERIES metric", exc_info=True)
        except Exception as e:
            logger.error("Chroma query FAILED for brand %s: %s", brand.slug, e, exc_info=True)
            try:
                CHROMA_ERRORS.labels(brand=brand.slug).inc()
            except Exception:
                logger.debug("Failed to increment CHROMA_ERRORS metric", exc_info=True)

        # If retrieval returned no context, return an explicit no-results response
        if not context or not context.strip():
            # Try to get a collection count for diagnostics (best-effort)
            col_count = None
            try:
                if hasattr(collection, "count"):
                    col_count = collection.count()
            except Exception:
                logger.debug("Failed to fetch collection.count() for brand %s", brand.slug, exc_info=True)

            logger.info(
                "No retrieval results for brand %s (collection_count=%s) — returning no-results fallback",
                brand.slug,
                col_count,
            )

            answer = (
                "I don't have relevant information in the knowledge base to answer that question. "
                "You can provide more details or try a different question."
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            asst_msg = models.Message(
                conversation_id=conv.id,
                role="assistant",
                content=answer,
                latency_ms=latency_ms,
            )
            conversation_repo.save_messages(db, pending_messages + [asst_msg])
            conversation_repo.defer(
                models.AnalyticsEvent(
                    brand_id=brand.id,
                    event_type="chat",
                    session_id=session_id,
                    payload_json=json.dumps({"query_len": len(user_message), "latency_ms": latency_ms, "rag": "no_results"}),
                )
            )
            conversation_repo.flush_deferred(db)

            try:
                CHAT_REQUESTS.labels(brand=brand.slug, outcome="no_results").inc()
                CHAT_LATENCY.labels(brand=brand.slug).observe(latency_ms / 1000)
            except Exception:
                logger.debug("Failed to record no-results metrics", exc_info=True)

            return {
                "brand": brand.slug,
                "session_id": session_id,
                "answer": answer,
                "sources": [],
                "urls": product_urls,
                "latency_ms": latency_ms,
            }

        # 6. Build LLM messages (history + current)
        llm_messages = history + [{"role": "user", "content": user_message}]

        # 7. Generate answer
        system_prompt = SYSTEM_PROMPT.format(brand_name=brand.name)
        t_llm_start = time.monotonic()
        answer, latency_ms = await ollama.chat(system_prompt, llm_messages, context)
        t_llm = time.monotonic() - t_llm_start
        logger.info("Timing: llm=%.2fs (ollama latency=%dms)", t_llm, latency_ms)

        # Record metrics for completed chat
        try:
            CHAT_REQUESTS.labels(brand=brand.slug, outcome="rag").inc()
            CHAT_LATENCY.labels(brand=brand.slug).observe(latency_ms / 1000)
        except Exception:
            logger.debug("Failed to record chat metrics", exc_info=True)

        # 8. Store assistant message + deferred analytics
        asst_msg = models.Message(
            conversation_id=conv.id,
            role="assistant",
            content=answer,
            latency_ms=latency_ms,
        )
        conversation_repo.save_messages(db, pending_messages + [asst_msg])
        conversation_repo.defer(
            models.AnalyticsEvent(
                brand_id=brand.id,
                event_type="chat",
                session_id=session_id,
                payload_json=json.dumps({"query_len": len(user_message), "latency_ms": latency_ms}),
            )
        )
        conversation_repo.flush_deferred(db)

        total_s = time.monotonic() - t0
        logger.info("Chat response completed in %.2fs", total_s)

        _result = {
            "brand": brand.slug,
            "session_id": session_id,
            "answer": answer,
            "sources": list(dict.fromkeys(sources)),  # deduplicated, order-preserved
            "urls": product_urls,
            "latency_ms": latency_ms,
        }
        with _resp_lock:
            _resp_cache[_key] = _result
        return _result

    def _safe_extract_lookup(self, message: str) -> tuple[str, str, int]:
        try:
            return tracking_service.extract_lookup_value_with_type(message)
        except Exception:
            logger.debug("Extracting lookup value failed", exc_info=True)
            return "", "", 0

    def _has_tracking_signal(self, user_message: str, history: list[dict]) -> bool:
        lookup_value, _, confidence = self._safe_extract_lookup(user_message)
        return tracking_service.should_handle_chat(user_message, history) or (
            lookup_value and confidence >= 60
        )

    def _block_rag_for_tracking(
        self,
        db: Session,
        brand: models.Brand,
        session_id: str,
        conv: models.Conversation,
        user_message: str,
        history: list[dict],
        pending_messages: list[models.Message],
        t0: float,
        product_urls: list[dict] | None = None,
    ) -> dict[str, Any] | None:
        """Prevent tracking queries from falling through to FAQ RAG."""
        try:
            if not self._has_tracking_signal(user_message, history):
                return None

            lookup_value, _, confidence = self._safe_extract_lookup(user_message)
            if not lookup_value:
                logger.info(
                    "Detected tracking intent without lookup value for brand %s — prompting user for ID",
                    brand.slug,
                )
                answer = (
                    f"{tracking_service.pending_lookup_phrase}. "
                    "Please provide your order ID or tracking number and I will look it up."
                )
                intent = "tracking_prompt"
            else:
                logger.warning(
                    "Tracking signal with value=%s (conf=%s) fell through for brand %s — blocking RAG fallback",
                    lookup_value, confidence, brand.slug,
                )
                answer = (
                    f"I see you're asking about {lookup_value}. "
                    "I'm having trouble accessing the tracking system right now. "
                    "Please try again shortly."
                )
                intent = "tracking_blocked_rag"

            latency_ms = int((time.monotonic() - t0) * 1000)
            asst_msg = models.Message(
                conversation_id=conv.id,
                role="assistant",
                content=answer,
                latency_ms=latency_ms,
            )
            conversation_repo.save_messages(db, pending_messages + [asst_msg])
            conversation_repo.defer(
                models.AnalyticsEvent(
                    brand_id=brand.id,
                    event_type="chat",
                    session_id=session_id,
                    payload_json=json.dumps({
                        "query_len": len(user_message),
                        "urls": product_urls or [],
                        "latency_ms": latency_ms,
                        "intent": intent,
                    }),
                )
            )
            conversation_repo.flush_deferred(db)
            return {
                "brand": brand.slug,
                "session_id": session_id,
                "answer": answer,
                "sources": [],
                "urls": product_urls or [],
                "latency_ms": latency_ms,
            }
        except Exception:
            logger.exception("Safeguard check for tracking intent failed")
            return None

    async def _handle_new_tracking_intent(
        self,
        db: Session,
        brand: models.Brand,
        session_id: str,
        conv: models.Conversation,
        ctx: models.ConversationContext,
        user_message: str,
        history: list[dict],
        allow_unverified_tracking: bool = False,
        pending_messages: list[models.Message] | None = None,
        product_urls: list[dict] | None = None,
    ) -> dict | None:
        logger.debug("_handle_new_tracking_intent called with message=%s", user_message)
        lookup_value, lookup_type, confidence = tracking_service.extract_lookup_value_with_type(user_message)
        logger.debug(
            "extracted lookup_value=%s lookup_type=%s confidence=%s",
            lookup_value, lookup_type, confidence,
        )
        t0 = time.monotonic()

        # Only treat an extracted value as an explicit lookup when we're
        # reasonably confident. Low-confidence extractions (eg. stray
        # numbers in a user message) should fall through to the "no value"
        # branch so the bot can prompt for an ID instead of returning a
        # confusing validation error or triggering a lookup.
        if lookup_value and confidence >= 60:
            state_machine.set_slot(ctx, "lookup_value", lookup_value)
            state_machine.set_slot(ctx, "lookup_type", lookup_type)
            state_machine.apply_transition(db, ctx, "intent_detected_with_value")

            validation_fn = (
                tracking_service.validate_tracking_number
                if lookup_type == "tracking_number"
                else tracking_service.validate_order_id
            )
            valid, msg = validation_fn(lookup_value)
            if not valid:
                state_machine.apply_transition(db, ctx, "validation_failed")
                answer = f"{msg} Please try again."
                asst_msg = models.Message(
                    conversation_id=conv.id,
                    role="assistant", content=answer,
                )
                conversation_repo.save_messages(db, (pending_messages or []) + [asst_msg])
                conversation_repo.flush_deferred(db)
                return {
                    "brand": brand.slug,
                    "session_id": session_id,
                    "answer": answer,
                    "sources": [],
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                }

            state_machine.apply_transition(db, ctx, "validation_passed")
            tracking_result = tracking_service.lookup(
                db=db, brand=brand,
                lookup_type=lookup_type,
                lookup_value=lookup_value,
                session_id=session_id, source="chatbot",
                allow_unverified=allow_unverified_tracking,
            )
            return await self._finalize_tracking(
                db, brand, session_id, conv, ctx,
                tracking_result, lookup_value, lookup_type, history, t0,
                pending_messages=pending_messages,
                product_urls=product_urls,
            )

        new_state, action = state_machine.apply_transition(db, ctx, "intent_detected_no_value")
        answer = (
            f"{tracking_service.pending_lookup_phrase}. "
            "You can send either one, and I will check the shipment status."
        )
        asst_msg = models.Message(
            conversation_id=conv.id,
            role="assistant", content=answer,
        )
        conversation_repo.save_messages(db, (pending_messages or []) + [asst_msg])
        conversation_repo.flush_deferred(db)
        return {
            "brand": brand.slug,
            "session_id": session_id,
            "answer": answer,
            "sources": [],
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }

    async def _handle_active_tracking(
        self,
        db: Session,
        brand: models.Brand,
        session_id: str,
        conv: models.Conversation,
        ctx: models.ConversationContext,
        user_message: str,
        history: list[dict],
        allow_unverified_tracking: bool = False,
        pending_messages: list[models.Message] | None = None,
        product_urls: list[dict] | None = None,
    ) -> dict | None:
        logger.debug("_handle_active_tracking state=%s message=%s", ctx.state, user_message)
        t0 = time.monotonic()
        state = ctx.state

        if state == "awaiting_lookup_value":
            lookup_value, lookup_type, confidence = tracking_service.extract_lookup_value_with_type(user_message)
            logger.debug(
                "active await lookup extraction -> value=%s type=%s confidence=%s",
                lookup_value, lookup_type, confidence,
            )
            if lookup_value:
                state_machine.set_slot(ctx, "lookup_value", lookup_value)
                state_machine.set_slot(ctx, "lookup_type", lookup_type)
                state_machine.apply_transition(db, ctx, "valid_value_provided")
                tracking_result = tracking_service.lookup(
                    db=db, brand=brand,
                    lookup_type=lookup_type,
                    lookup_value=lookup_value,
                    session_id=session_id, source="chatbot",
                    allow_unverified=allow_unverified_tracking,
                )
                return await self._finalize_tracking(
                    db, brand, session_id, conv, ctx,
                    tracking_result, lookup_value, lookup_type, history, t0,
                    pending_messages=pending_messages,
                    product_urls=product_urls,
                )

            retry_count = state_machine.increment_retry(ctx)
            if retry_count >= MAX_TRACKING_RETRIES:
                state_machine.apply_transition(db, ctx, "invalid_value_terminal")
                answer = (
                    "We've tried several times but couldn't find a valid order ID or tracking number. "
                    "Please contact customer support for assistance with your order."
                )
            else:
                state_machine.apply_transition(db, ctx, "invalid_value_retryable")
                answer = (
                    f"I couldn't find a valid order ID or tracking number in your message. "
                    f"Please share your order ID (e.g., BIO-1001) or tracking number (e.g., TRK-BIO-1001) "
                    f"so I can look up your shipment. (Attempt {retry_count}/{MAX_TRACKING_RETRIES})"
                )
            asst_msg = models.Message(
                conversation_id=conv.id,
                role="assistant", content=answer,
            )
            conversation_repo.save_messages(db, (pending_messages or []) + [asst_msg])
            conversation_repo.flush_deferred(db)
            return {
                "brand": brand.slug,
                "session_id": session_id,
                "answer": answer,
                "sources": [],
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }

        elif state == "awaiting_verification":
            verification = user_message.strip()
            valid, msg = tracking_service.validate_verification(verification)
            if valid:
                state_machine.set_slot(ctx, "verification", verification)
                state_machine.apply_transition(db, ctx, "verification_provided")
                lookup_value = state_machine.get_slot(ctx, "lookup_value")
                lookup_type = state_machine.get_slot(ctx, "lookup_type", "auto")
                tracking_result = tracking_service.lookup(
                    db=db, brand=brand,
                    lookup_type=lookup_type,
                    lookup_value=lookup_value,
                    customer_verification=verification,
                    session_id=session_id, source="chatbot",
                        allow_unverified=allow_unverified_tracking,
                )
                return await self._finalize_tracking(
                    db, brand, session_id, conv, ctx,
                    tracking_result, lookup_value, lookup_type, history, t0,
                    pending_messages=pending_messages,
                    product_urls=product_urls,
                )
            state_machine.apply_transition(db, ctx, "verification_invalid")
            answer = msg + " Please try again."
            asst_msg = models.Message(
                conversation_id=conv.id,
                role="assistant", content=answer,
            )
            conversation_repo.save_messages(db, (pending_messages or []) + [asst_msg])
            conversation_repo.flush_deferred(db)
            return {
                "brand": brand.slug,
                "session_id": session_id,
                "answer": answer,
                "sources": [],
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }

        elif state == "completed":
            text = user_message.strip().lower()
            is_follow_up = any(
                phrase in text
                for phrase in ("more detail", "tell me more", "explain", "timeline", "update")
            )
            if tracking_service.should_handle_chat(user_message, history):
                state_machine.reset(db, ctx)
                state_machine.apply_transition(db, ctx, "intent_detected_no_value")
                return await self._handle_new_tracking_intent(
                    db, brand, session_id, conv, ctx, user_message, history,
                    allow_unverified_tracking=allow_unverified_tracking,
                    pending_messages=pending_messages,
                )
            if is_follow_up:
                state_machine.apply_transition(db, ctx, "follow_up_same_shipment")
                tracking_data = state_machine.get_slot(ctx, "tracking_data", {})
                if tracking_data:
                    answer = await self._generate_nlp_tracking_response(brand, tracking_data, history)
                else:
                    answer = "I don't have the previous tracking details anymore. Feel free to ask for a new tracking update."
                state_machine.apply_transition(db, ctx, "response_ready")
                asst_msg = models.Message(
                    conversation_id=conv.id,
                    role="assistant", content=answer,
                )
                conversation_repo.save_messages(db, (pending_messages or []) + [asst_msg])
                conversation_repo.flush_deferred(db)
                return {
                    "brand": brand.slug,
                    "session_id": session_id,
                    "answer": answer,
                    "sources": ["tracking_system"],
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                }
            state_machine.reset(db, ctx)
            return None

        elif state in ("error_retryable", "error_terminal"):
            text = user_message.strip().lower()
            is_tracking = tracking_service.should_handle_chat(user_message, history) or "yes" in text
            if is_tracking and state == "error_retryable":
                retry_count = state_machine.increment_retry(ctx)
                if retry_count >= MAX_TRACKING_RETRIES:
                    state_machine.apply_transition(db, ctx, "retries_exhausted")
                    answer = (
                        "We've tried several times but couldn't complete the tracking lookup. "
                        "Please contact customer support for assistance."
                    )
                else:
                    state_machine.apply_transition(db, ctx, "user_retries")
                    answer = (
                        f"Let's try again. Please share your order ID or tracking number. "
                        f"(Attempt {retry_count}/{MAX_TRACKING_RETRIES})"
                    )
                asst_msg = models.Message(
                    conversation_id=conv.id,
                    role="assistant", content=answer,
                )
                conversation_repo.save_messages(db, (pending_messages or []) + [asst_msg])
                conversation_repo.flush_deferred(db)
                return {
                    "brand": brand.slug,
                    "session_id": session_id,
                    "answer": answer,
                    "sources": [],
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                }
            if self._has_tracking_signal(user_message, history):
                state_machine.reset(db, ctx)
                return await self._handle_new_tracking_intent(
                    db, brand, session_id, conv, ctx, user_message, history,
                    allow_unverified_tracking=allow_unverified_tracking,
                    pending_messages=pending_messages,
                )
            state_machine.reset(db, ctx)
            return None

        elif state in ("performing_lookup", "displaying_result"):
            if self._has_tracking_signal(user_message, history):
                state_machine.reset(db, ctx)
                return await self._handle_new_tracking_intent(
                    db, brand, session_id, conv, ctx, user_message, history,
                    allow_unverified_tracking=allow_unverified_tracking,
                    pending_messages=pending_messages,
                )
            state_machine.reset(db, ctx)
            return None

        return None

    async def _finalize_tracking(
        self,
        db: Session,
        brand: models.Brand,
        session_id: str,
        conv: models.Conversation,
        ctx: models.ConversationContext,
        tracking_result: dict,
        lookup_value: str,
        lookup_type: str,
        history: list[dict],
        t0: float,
        pending_messages: list[models.Message] | None = None,
        product_urls: list[dict] | None = None,
    ) -> dict:
        logger.debug("_finalize_tracking received tracking_result keys=%s", list(tracking_result.keys()))
        success = tracking_result.get("success", False)
        error_code = tracking_result.get("error_code", "")

        if not success:
            if error_code in ("rate_limited",):
                state_machine.apply_transition(db, ctx, "lookup_retryable_error")
                state_machine.set_slot(ctx, "lookup_value", lookup_value)
                state_machine.set_slot(ctx, "lookup_type", lookup_type)
                state_machine.set_error(ctx, error_code, tracking_result.get("safe_response_text", ""))
            elif error_code in ("verification_required",):
                state_machine.apply_transition(db, ctx, "verification_needed")
                state_machine.set_slot(ctx, "lookup_value", lookup_value)
                state_machine.set_slot(ctx, "lookup_type", lookup_type)
            else:
                state_machine.apply_transition(db, ctx, "lookup_terminal_error")
                state_machine.set_error(ctx, error_code, tracking_result.get("safe_response_text", ""))

            answer = tracking_result.get("safe_response_text", "")
            if error_code == "verification_required":
                answer = (
                    "For privacy, I need to verify your identity. "
                    "Please provide the email address or phone number used on this order."
                )

            asst_msg = models.Message(
                conversation_id=conv.id,
                role="assistant", content=answer,
            )
            conversation_repo.save_messages(db, (pending_messages or []) + [asst_msg])
            conversation_repo.flush_deferred(db)
            try:
                TRACKING_LOOKUPS.labels(brand=brand.slug, result=error_code or "error").inc()
            except Exception:
                logger.debug("Failed to record tracking lookup metric", exc_info=True)
            return {
                "brand": brand.slug,
                "session_id": session_id,
                "answer": answer,
                "sources": ["tracking_system"] if error_code == "verification_required" else [],
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }

        state_machine.apply_transition(db, ctx, "lookup_success")

        tracking_data = tracking_service.build_tracking_data_dict(tracking_result)
        state_machine.set_slot(ctx, "lookup_value", lookup_value)
        state_machine.set_slot(ctx, "lookup_type", lookup_type)
        state_machine.set_slot(ctx, "tracking_data", tracking_data)

        answer = await self._generate_nlp_tracking_response(brand, tracking_data, history)
        logger.debug("Generated tracking NLP answer (len=%d)", len(answer) if answer else 0)
        state_machine.apply_transition(db, ctx, "response_ready")

        latency_ms = int((time.monotonic() - t0) * 1000)
        asst_msg = models.Message(
            conversation_id=conv.id,
            role="assistant", content=answer,
            latency_ms=latency_ms,
        )
        conversation_repo.save_messages(db, (pending_messages or []) + [asst_msg])
        conversation_repo.defer(
            models.AnalyticsEvent(
                brand_id=brand.id,
                event_type="chat",
                session_id=session_id,
                payload_json=json.dumps({
                    "query_len": len(lookup_value),
                    "latency_ms": latency_ms,
                    "intent": "tracking",
                    "tracking_result": "success",
                }),
            )
        )
        conversation_repo.flush_deferred(db)
        try:
            TRACKING_LOOKUPS.labels(brand=brand.slug, result="success").inc()
        except Exception:
            logger.debug("Failed to record tracking success metric", exc_info=True)

        return {
            "brand": brand.slug,
            "session_id": session_id,
            "answer": answer,
            "sources": ["tracking_system"],
            "urls": product_urls or [],
            "latency_ms": latency_ms,
        }

    async def _generate_nlp_tracking_response(
        self,
        brand: models.Brand,
        tracking_data: dict[str, Any],
        history: list[dict],
    ) -> str:
        system_prompt = LOGISTICS_SYSTEM_PROMPT.format(brand_name=brand.name)
        context_str = json.dumps(tracking_data, indent=2)
        answer, _ = await ollama.chat(system_prompt, history[-4:], context_str, append_rag_instruction=False)

        if not answer or not answer.strip() or answer.startswith("[Ollama") or answer.startswith("I currently can't"):
            fallback = self._template_tracking_response(tracking_data)
            return fallback

        return answer

    def _template_tracking_response(
        self,
        tracking_data: dict[str, Any],
    ) -> str:
        status = tracking_data.get("status", "")
        status_label = tracking_data.get("status_label", "")
        hub_name = tracking_data.get("hub_name", "")
        hub_city = tracking_data.get("hub_city", "")
        location = tracking_data.get("current_location", "")
        eta = tracking_data.get("eta", "")
        last_updated = tracking_data.get("last_updated", "")
        delay_reason = tracking_data.get("delay_reason", "")
        timeline = tracking_data.get("timeline", [])

        if status == "delivered":
            lines = ["Your shipment has been delivered successfully."]
        elif status == "out_for_delivery":
            lines = ["Your shipment is out for delivery today."]
        elif status == "delayed":
            lines = ["Your shipment is taking longer than expected."]
            if delay_reason:
                lines.append(f"Reason: {delay_reason}")
        else:
            if hub_name:
                lines = [f"Your shipment is at {hub_name} in {hub_city}."]
            elif location:
                lines = [f"Your shipment is at {location}."]
            else:
                lines = [f"Status: {status_label}."]

        if eta:
            lines.append(f"Estimated delivery: {eta}.")
        if last_updated:
            lines.append(f"Last updated: {last_updated}.")
        if timeline:
            lines.append("\nRecent updates:")
            lines.extend(f"  - {event}" for event in timeline[-3:])

        return "\n".join(lines)


rag_service = RAGService()
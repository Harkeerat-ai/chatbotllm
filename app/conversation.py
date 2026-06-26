from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app import models

logger = logging.getLogger(__name__)

MAX_TRACKING_RETRIES = 3
CONTEXT_IDLE_TIMEOUT = timedelta(minutes=10)

STATES = frozenset({
    "idle",
    "awaiting_lookup_value",
    "awaiting_clarification",
    "validating_input",
    "awaiting_verification",
    "performing_lookup",
    "displaying_result",
    "error_retryable",
    "error_terminal",
    "completed",
})

EVENTS = frozenset({
    "user_message",
    "validation_done",
    "lookup_complete",
    "response_ready",
})

TRANSITION_TABLE: dict[tuple[str, str], tuple[str, str]] = {
    # (from_state, event) -> (to_state, action)

    # idle transitions
    ("idle", "intent_detected_with_value"): ("validating_input", "validate_lookup"),
    ("idle", "intent_detected_no_value"): ("awaiting_lookup_value", "ask_for_value"),
    ("idle", "no_intent"): ("idle", "normal_rag"),
    ("idle", "clarification_needed"): ("awaiting_clarification", "ask_clarification"),

    # awaiting_clarification transitions
    ("awaiting_clarification", "clarification_provided"): ("idle", "retry_rag"),
    ("awaiting_clarification", "clarification_skipped"): ("idle", "reset_context"),

    # awaiting_lookup_value transitions
    ("awaiting_lookup_value", "valid_value_provided"): ("validating_input", "validate_lookup"),
    ("awaiting_lookup_value", "invalid_value_retryable"): ("awaiting_lookup_value", "re_prompt_value"),
    ("awaiting_lookup_value", "invalid_value_terminal"): ("error_terminal", "max_retries_exceeded"),
    ("awaiting_lookup_value", "user_abandoned"): ("idle", "reset_context"),

    # validating_input transitions
    ("validating_input", "verification_needed"): ("awaiting_verification", "ask_verification"),
    ("validating_input", "validation_passed"): ("performing_lookup", "call_tracking"),
    ("validating_input", "validation_failed"): ("awaiting_lookup_value", "re_prompt_value"),

    # awaiting_verification transitions
    ("awaiting_verification", "verification_provided"): ("performing_lookup", "call_tracking"),
    ("awaiting_verification", "verification_invalid"): ("awaiting_verification", "re_prompt_verification"),
    ("awaiting_verification", "verification_declined"): ("error_terminal", "verification_failed"),

    # performing_lookup transitions
    ("performing_lookup", "lookup_success"): ("displaying_result", "generate_nlp_response"),
    ("performing_lookup", "lookup_retryable_error"): ("error_retryable", "offer_retry"),
    ("performing_lookup", "lookup_terminal_error"): ("error_terminal", "show_error"),
    ("performing_lookup", "lookup_system_error"): ("error_terminal", "show_system_error"),

    # displaying_result transitions
    ("displaying_result", "response_ready"): ("completed", "send_response"),

    # completed transitions
    ("completed", "new_tracking_intent"): ("awaiting_lookup_value", "start_fresh_tracking"),
    ("completed", "follow_up_same_shipment"): ("displaying_result", "regenerate_detail"),
    ("completed", "unrelated_question"): ("idle", "normal_rag"),

    # error_retryable transitions
    ("error_retryable", "user_retries"): ("awaiting_lookup_value", "retry_prompt"),
    ("error_retryable", "retries_exhausted"): ("error_terminal", "max_retries_exceeded"),
    ("error_retryable", "user_abandons"): ("idle", "reset_context"),

    # error_terminal transitions
    ("error_terminal", "user_starts_new"): ("idle", "reset_context"),
}


class ConversationStateMachine:

    @staticmethod
    def get_context(db: Session, conversation_id: int) -> models.ConversationContext:
        ctx = (
            db.query(models.ConversationContext)
            .filter_by(conversation_id=conversation_id)
            .first()
        )
        if not ctx:
            ctx = models.ConversationContext(
                conversation_id=conversation_id,
                state="idle",
                slots_json="{}",
                error_info_json="{}",
                retry_count=0,
            )
            db.add(ctx)
            db.commit()
            db.refresh(ctx)
        else:
            if ctx.expired_at and datetime.now(timezone.utc).replace(tzinfo=None) > ctx.expired_at:
                ConversationStateMachine.reset(db, ctx)
        return ctx

    @staticmethod
    def advance(
        ctx: models.ConversationContext,
        event: str,
    ) -> tuple[str, str]:
        transition = TRANSITION_TABLE.get((ctx.state, event))
        if transition:
            return transition
        logger.warning("No transition found for state=%s event=%s", ctx.state, event)
        return ctx.state, "noop"

    @staticmethod
    def apply_transition(
        db: Session,
        ctx: models.ConversationContext,
        event: str,
    ) -> tuple[str, str]:
        new_state, action = ConversationStateMachine.advance(ctx, event)
        ctx.state = new_state
        if action in ("reset_context", "normal_rag"):
            ConversationStateMachine.reset(db, ctx)
        if new_state == "completed":
            ctx.expired_at = datetime.now(timezone.utc) + CONTEXT_IDLE_TIMEOUT
        elif new_state in ("error_terminal", "error_retryable"):
            pass
        db.commit()
        return new_state, action

    @staticmethod
    def set_slot(ctx: models.ConversationContext, key: str, value: Any) -> None:
        slots = json.loads(ctx.slots_json)
        slots[key] = value
        ctx.slots_json = json.dumps(slots)

    @staticmethod
    def get_slot(ctx: models.ConversationContext, key: str, default: Any = "") -> Any:
        slots = json.loads(ctx.slots_json)
        return slots.get(key, default)

    @staticmethod
    def set_error(ctx: models.ConversationContext, code: str, message: str) -> None:
        ctx.error_info_json = json.dumps({"code": code, "message": message})

    @staticmethod
    def get_error(ctx: models.ConversationContext) -> dict[str, str]:
        try:
            data = json.loads(ctx.error_info_json)
            if isinstance(data, dict):
                return {
                    "code": data.get("code", ""),
                    "message": data.get("message", ""),
                }
            return {"code": "", "message": ""}
        except (json.JSONDecodeError, TypeError):
            return {"code": "", "message": ""}

    @staticmethod
    def increment_retry(ctx: models.ConversationContext) -> int:
        ctx.retry_count += 1
        return ctx.retry_count

    @staticmethod
    def reset(db: Session, ctx: models.ConversationContext) -> None:
        ctx.state = "idle"
        ctx.slots_json = "{}"
        ctx.error_info_json = "{}"
        ctx.retry_count = 0
        ctx.expired_at = None

    @staticmethod
    def is_tracking_active(ctx: models.ConversationContext) -> bool:
        return ctx.state != "idle"


state_machine = ConversationStateMachine()

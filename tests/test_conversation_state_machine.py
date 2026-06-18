from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from app.conversation import (
    ConversationStateMachine,
    MAX_TRACKING_RETRIES,
    CONTEXT_IDLE_TIMEOUT,
    STATES,
    EVENTS,
    TRANSITION_TABLE,
)
from datetime import datetime, timedelta


@pytest.fixture
def ctx():
    mock = MagicMock()
    mock.state = "idle"
    mock.slots_json = "{}"
    mock.error_info_json = "{}"
    mock.retry_count = 0
    mock.expired_at = None
    return mock


@pytest.fixture
def db_mock():
    return MagicMock()


class TestStateMachineTransitions:

    def test_all_states_are_defined(self):
        defined = set(STATES)
        for (from_state, _), (to_state, _) in TRANSITION_TABLE.items():
            assert from_state in defined, f"Undefined source state: {from_state}"
            assert to_state in defined, f"Undefined target state: {to_state}"
            assert to_state != "undefined"

    # ── idle ──────────────────────────────────────────────────────────────

    def test_idle_to_validating_with_value(self, ctx):
        new_state, action = ConversationStateMachine.advance(ctx, "intent_detected_with_value")
        assert new_state == "validating_input"
        assert action == "validate_lookup"

    def test_idle_to_awaiting_no_value(self, ctx):
        new_state, action = ConversationStateMachine.advance(ctx, "intent_detected_no_value")
        assert new_state == "awaiting_lookup_value"
        assert action == "ask_for_value"

    def test_idle_no_intent(self, ctx):
        new_state, action = ConversationStateMachine.advance(ctx, "no_intent")
        assert new_state == "idle"
        assert action == "normal_rag"

    # ── awaiting_lookup_value ─────────────────────────────────────────────

    def test_awaiting_to_validating(self, ctx):
        ctx.state = "awaiting_lookup_value"
        new_state, action = ConversationStateMachine.advance(ctx, "valid_value_provided")
        assert new_state == "validating_input"

    def test_awaiting_invalid_retryable(self, ctx):
        ctx.state = "awaiting_lookup_value"
        ctx.retry_count = 1
        new_state, action = ConversationStateMachine.advance(ctx, "invalid_value_retryable")
        assert new_state == "awaiting_lookup_value"

    def test_awaiting_invalid_terminal(self, ctx):
        ctx.state = "awaiting_lookup_value"
        ctx.retry_count = MAX_TRACKING_RETRIES
        new_state, action = ConversationStateMachine.advance(ctx, "invalid_value_terminal")
        assert new_state == "error_terminal"

    def test_awaiting_abandon(self, ctx):
        ctx.state = "awaiting_lookup_value"
        new_state, action = ConversationStateMachine.advance(ctx, "user_abandoned")
        assert new_state == "idle"

    # ── validating_input ──────────────────────────────────────────────────

    def test_validating_needs_verification(self, ctx):
        ctx.state = "validating_input"
        new_state, action = ConversationStateMachine.advance(ctx, "verification_needed")
        assert new_state == "awaiting_verification"

    def test_validating_passed(self, ctx):
        ctx.state = "validating_input"
        new_state, action = ConversationStateMachine.advance(ctx, "validation_passed")
        assert new_state == "performing_lookup"

    def test_validating_failed(self, ctx):
        ctx.state = "validating_input"
        new_state, action = ConversationStateMachine.advance(ctx, "validation_failed")
        assert new_state == "awaiting_lookup_value"

    # ── awaiting_verification ─────────────────────────────────────────────

    def test_verification_provided(self, ctx):
        ctx.state = "awaiting_verification"
        new_state, action = ConversationStateMachine.advance(ctx, "verification_provided")
        assert new_state == "performing_lookup"

    def test_verification_invalid(self, ctx):
        ctx.state = "awaiting_verification"
        new_state, action = ConversationStateMachine.advance(ctx, "verification_invalid")
        assert new_state == "awaiting_verification"

    def test_verification_declined(self, ctx):
        ctx.state = "awaiting_verification"
        new_state, action = ConversationStateMachine.advance(ctx, "verification_declined")
        assert new_state == "error_terminal"

    # ── performing_lookup ─────────────────────────────────────────────────

    def test_lookup_success(self, ctx):
        ctx.state = "performing_lookup"
        new_state, action = ConversationStateMachine.advance(ctx, "lookup_success")
        assert new_state == "displaying_result"

    def test_lookup_retryable_error(self, ctx):
        ctx.state = "performing_lookup"
        new_state, action = ConversationStateMachine.advance(ctx, "lookup_retryable_error")
        assert new_state == "error_retryable"

    def test_lookup_terminal_error(self, ctx):
        ctx.state = "performing_lookup"
        new_state, action = ConversationStateMachine.advance(ctx, "lookup_terminal_error")
        assert new_state == "error_terminal"

    # ── displaying_result ─────────────────────────────────────────────────

    def test_displaying_to_completed(self, ctx):
        ctx.state = "displaying_result"
        new_state, action = ConversationStateMachine.advance(ctx, "response_ready")
        assert new_state == "completed"

    # ── completed ─────────────────────────────────────────────────────────

    def test_completed_new_tracking(self, ctx):
        ctx.state = "completed"
        new_state, action = ConversationStateMachine.advance(ctx, "new_tracking_intent")
        assert new_state == "awaiting_lookup_value"

    def test_completed_follow_up(self, ctx):
        ctx.state = "completed"
        new_state, action = ConversationStateMachine.advance(ctx, "follow_up_same_shipment")
        assert new_state == "displaying_result"

    def test_completed_unrelated(self, ctx):
        ctx.state = "completed"
        new_state, action = ConversationStateMachine.advance(ctx, "unrelated_question")
        assert new_state == "idle"

    # ── error_retryable ───────────────────────────────────────────────────

    def test_error_retryable_retry(self, ctx):
        ctx.state = "error_retryable"
        new_state, action = ConversationStateMachine.advance(ctx, "user_retries")
        assert new_state == "awaiting_lookup_value"

    def test_error_retryable_exhausted(self, ctx):
        ctx.state = "error_retryable"
        new_state, action = ConversationStateMachine.advance(ctx, "retries_exhausted")
        assert new_state == "error_terminal"

    def test_error_retryable_abandon(self, ctx):
        ctx.state = "error_retryable"
        new_state, action = ConversationStateMachine.advance(ctx, "user_abandons")
        assert new_state == "idle"

    # ── error_terminal ────────────────────────────────────────────────────

    def test_error_terminal_new_start(self, ctx):
        ctx.state = "error_terminal"
        new_state, action = ConversationStateMachine.advance(ctx, "user_starts_new")
        assert new_state == "idle"

    # ── unknown transition ────────────────────────────────────────────────

    def test_unknown_transition_returns_current_state(self, ctx):
        new_state, action = ConversationStateMachine.advance(ctx, "nonexistent_event")
        assert new_state == "idle"
        assert action == "noop"


class TestStateMachineSlots:

    def test_set_and_get_slot(self, ctx):
        ConversationStateMachine.set_slot(ctx, "lookup_value", "BIO-1001")
        assert ConversationStateMachine.get_slot(ctx, "lookup_value") == "BIO-1001"

    def test_get_default_slot(self, ctx):
        assert ConversationStateMachine.get_slot(ctx, "missing", "default_val") == "default_val"

    def test_multiple_slots(self, ctx):
        ConversationStateMachine.set_slot(ctx, "a", 1)
        ConversationStateMachine.set_slot(ctx, "b", 2)
        slots = json.loads(ctx.slots_json)
        assert slots == {"a": 1, "b": 2}


class TestStateMachineErrors:

    def test_set_and_get_error(self, ctx):
        ConversationStateMachine.set_error(ctx, "not_found", "No shipment found")
        err = ConversationStateMachine.get_error(ctx)
        assert err["code"] == "not_found"
        assert err["message"] == "No shipment found"

    def test_get_error_default(self, ctx):
        err = ConversationStateMachine.get_error(ctx)
        assert err["code"] == ""


class TestStateMachineRetry:

    def test_increment_retry(self, ctx):
        assert ConversationStateMachine.increment_retry(ctx) == 1
        assert ConversationStateMachine.increment_retry(ctx) == 2
        assert ctx.retry_count == 2

    def test_reset_clears_retries(self, ctx, db_mock):
        ctx.retry_count = 5
        ConversationStateMachine.reset(db_mock, ctx)
        assert ctx.retry_count == 0
        assert ctx.state == "idle"
        assert ctx.slots_json == "{}"

    def test_is_tracking_active(self, ctx, db_mock):
        assert not ConversationStateMachine.is_tracking_active(ctx)
        ctx.state = "awaiting_lookup_value"
        assert ConversationStateMachine.is_tracking_active(ctx)
        ConversationStateMachine.reset(db_mock, ctx)
        assert not ConversationStateMachine.is_tracking_active(ctx)

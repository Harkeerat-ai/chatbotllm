from __future__ import annotations

import pytest
from app.services import tracking_service


class TestTrackingIntentDetection:

    @pytest.mark.parametrize("message", [
        "where is my order",
        "track my order",
        "tracking number",
        "shipment status",
        "delivery status",
        "where is my shipment",
        "has my order shipped",
        "where is my package",
        "parcel status",
        "delivery update",
        "courier update",
        "order progress",
        "has it shipped",
        "when will it arrive",
        "delivery date",
        "track order BIO-1001",
        "can you track my shipment",
        "i want to track my package",
        "what is the delivery status",
    ])
    def test_positive_intent(self, message):
        assert tracking_service.should_handle_chat(message, []), f"Failed to detect: {message}"

    @pytest.mark.parametrize("message", [
        "hello",
        "what products do you have",
        "tell me about your company",
        "open a support ticket",
        "i want a refund",
        "cancel my order",
        "what is your return policy",
        "good morning",
        "thanks",
    ])
    def test_negative_intent(self, message):
        assert not tracking_service.should_handle_chat(message, []), f"Wrongly detected: {message}"

    def test_fuzzy_misspelling_trackin(self):
        assert tracking_service.should_handle_chat("my trackin nmber is BIO-1001", [])

    def test_context_awaiting_lookup(self):
        history = [
            {"role": "assistant", "content": "Please share your order ID or tracking number. You can send either one, and I will check the shipment status."},
        ]
        assert tracking_service.should_handle_chat("BIO-1001", history)

    def test_context_awaiting_lookup_no_value(self):
        history = [
            {"role": "assistant", "content": "Please share your order ID or tracking number. You can send either one, and I will check the shipment status."},
        ]
        assert not tracking_service.should_handle_chat("thanks", history)

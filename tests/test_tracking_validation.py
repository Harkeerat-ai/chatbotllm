from __future__ import annotations

import pytest
from app.services import tracking_service


class TestOrderIdValidation:

    @pytest.mark.parametrize("value", [
        "BIO-1001",
        "BLD-1001",
        "VIT-1001",
        "KALP-1001",
        "ORD-9999",
        "TEST123",
        "MY-ORDER-42",
    ])
    def test_valid_order_ids(self, value):
        valid, msg = tracking_service.validate_order_id(value)
        assert valid, f"Should accept: {value} — {msg}"

    @pytest.mark.parametrize("value", [
        "",
        "AB",
        "no-digits-here",
        "@invalid!",
    ])
    def test_invalid_order_ids(self, value):
        valid, msg = tracking_service.validate_order_id(value)
        assert not valid, f"Should reject: {value}"


class TestTrackingNumberValidation:

    @pytest.mark.parametrize("value", [
        "TRK-BIO-1001",
        "TRK-BLD-1001",
        "TRK_VIT_1001",
        "1Z999AA10123456784",
    ])
    def test_valid_tracking_numbers(self, value):
        valid, msg = tracking_service.validate_tracking_number(value)
        assert valid, f"Should accept: {value} — {msg}"

    @pytest.mark.parametrize("value", [
        "",
        "NO-DIGITS",
        "!!invalid!!",
    ])
    def test_invalid_tracking_numbers(self, value):
        valid, msg = tracking_service.validate_tracking_number(value)
        assert not valid, f"Should reject: {value}"


class TestLookupTypeInference:

    @pytest.mark.parametrize("value,expected", [
        ("TRK-BIO-1001", "tracking_number"),
        ("SHIP-BIO-1001", "tracking_number"),
        ("BIO-1001", "order_id"),
        ("BLD-1001", "order_id"),
        ("VIT-1001", "order_id"),
        ("KALP-1001", "order_id"),
        ("ORD-12345", "order_id"),
        ("ABC123XYZ", "auto"),
        ("1234567890", "auto"),
    ])
    def test_infer_lookup_type(self, value, expected):
        assert tracking_service.infer_lookup_type(value) == expected


class TestExtractLookupValue:

    @pytest.mark.parametrize("message,expected_value", [
        ("my order id is BIO-1001", "BIO-1001"),
        ("tracking number: TRK-BIO-1001", "TRK-BIO-1001"),
        ("where is my order BIO-1001", "BIO-1001"),
        ("track TRK-BIO-1001 please", "TRK-BIO-1001"),
    ])
    def test_explicit_extraction(self, message, expected_value):
        value, lt, conf = tracking_service.extract_lookup_value_with_type(message)
        assert value == expected_value, f"Expected {expected_value} got {value}"

    def test_no_lookup_value(self):
        value, lt, conf = tracking_service.extract_lookup_value_with_type("hello how are you")
        assert value == ""
        assert conf == 0

    def test_token_pattern_extraction(self):
        value, lt, conf = tracking_service.extract_lookup_value_with_type("my tracking is TRK-BIO-1001")
        assert "TRK-BIO-1001" in value or value == "TRK-BIO-1001"


class TestVerificationValidation:

    @pytest.mark.parametrize("value", [
        "user@example.com",
        "9876543210",
        "+1-555-123-4567",
        "test.user@company.co.in",
    ])
    def test_valid_verification(self, value):
        valid, msg = tracking_service.validate_verification(value)
        assert valid, f"Should accept: {value} — {msg}"

    @pytest.mark.parametrize("value", [
        "",
        "abc",
        "12",
    ])
    def test_invalid_verification(self, value):
        valid, msg = tracking_service.validate_verification(value)
        assert not valid, f"Should reject: {value}"

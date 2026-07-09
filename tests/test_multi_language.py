from app.prompts import get_prompt, get_widget_labels
from app.translations import get_text, is_rtl, SUPPORTED_LANGUAGES


def test_get_text_returns_english_by_default():
    text = get_text("widget.send", "en")
    assert text == "Send"


def test_get_text_returns_spanish():
    text = get_text("widget.send", "es")
    assert text == "Enviar"


def test_get_text_falls_back_to_english_for_missing_language():
    text = get_text("widget.send", "de")
    assert text == "Send"


def test_get_text_returns_key_if_not_found():
    text = get_text("nonexistent.key", "en")
    assert text == "nonexistent.key"


def test_is_rtl_returns_true_for_arabic():
    assert is_rtl("ar") is True


def test_is_rtl_returns_false_for_english():
    assert is_rtl("en") is False
    assert is_rtl("es") is False
    assert is_rtl("hi") is False
    assert is_rtl("mr") is False
    assert is_rtl("ta") is False
    assert is_rtl("gu") is False
    assert is_rtl("pa") is False


def test_supported_languages_includes_8_languages():
    assert len(SUPPORTED_LANGUAGES) == 8
    assert "en" in SUPPORTED_LANGUAGES
    assert "es" in SUPPORTED_LANGUAGES
    assert "ar" in SUPPORTED_LANGUAGES
    assert "hi" in SUPPORTED_LANGUAGES
    assert "mr" in SUPPORTED_LANGUAGES
    assert "ta" in SUPPORTED_LANGUAGES
    assert "gu" in SUPPORTED_LANGUAGES
    assert "pa" in SUPPORTED_LANGUAGES


def test_get_prompt_returns_english_by_default():
    prompt = get_prompt("system", "en")
    assert "{brand_name}" in prompt
    assert "friendly and knowledgeable" in prompt


def test_get_prompt_returns_spanish():
    prompt = get_prompt("system", "es")
    assert "{brand_name}" in prompt
    assert "amable" in prompt


def test_get_prompt_returns_french():
    prompt = get_prompt("system", "fr")
    assert "{brand_name}" in prompt
    assert "amical" in prompt


def test_get_prompt_has_translations_for_new_languages():
    """Verify that new languages have prompt translations (not placeholders)."""
    for lang in ["ar", "hi", "mr", "ta", "gu", "pa"]:
        prompt = get_prompt("system", lang)
        assert prompt is not None
        assert "translation pending" not in prompt


def test_get_prompt_falls_back_to_english_for_unsupported_language():
    prompt = get_prompt("system", "de")
    assert "friendly and knowledgeable" in prompt


def test_get_prompt_logistics_spanish():
    prompt = get_prompt("logistics_system", "es")
    assert "{brand_name}" in prompt
    assert "log\u00edstica" in prompt


def test_get_prompt_clarification_system_spanish():
    prompt = get_prompt("clarification_system", "es")
    assert "aclaraci\u00f3n" in prompt


def test_get_prompt_clarification_prompt_english():
    prompt = get_prompt("clarification_prompt", "en")
    assert "{topic_list}" in prompt
    assert "{brand_name}" in prompt


def test_get_prompt_summarization_prompt_french():
    prompt = get_prompt("summarization_prompt", "fr")
    assert "{dialog}" in prompt
    assert "R\u00e9sumez" in prompt


def test_get_prompt_suggestion_prompt_spanish():
    prompt = get_prompt("suggestion_prompt", "es")
    assert "{brand_name}" in prompt
    assert "JSON array" in prompt or "array JSON" in prompt


def test_get_widget_labels_english():
    labels = get_widget_labels("en")
    assert labels["send"] == "Send"
    assert labels["placeholder"] == "Ask a question\u2026"


def test_get_widget_labels_spanish():
    labels = get_widget_labels("es")
    assert labels["send"] == "Enviar"
    assert labels["placeholder"] == "Haz una pregunta\u2026"


def test_get_widget_labels_french():
    labels = get_widget_labels("fr")
    assert labels["send"] == "Envoyer"
    assert labels["sources"] == "Sources:"


def test_get_widget_labels_has_all_8_languages():
    """Verify that all 8 languages have widget label entries."""
    for lang in SUPPORTED_LANGUAGES:
        labels = get_widget_labels(lang)
        assert labels is not None
        assert "send" in labels
        assert "placeholder" in labels


def test_get_widget_labels_falls_back_to_english():
    labels = get_widget_labels("de")
    assert labels["send"] == "Send"


def test_resolve_language_from_brand(monkeypatch):
    from app.rag_service import _resolve_language
    from app.config import get_settings

    class FakeBrand:
        language = "es"

    lang = _resolve_language(FakeBrand())
    assert lang == "es"


def test_resolve_language_falls_back_to_default(monkeypatch):
    from app.rag_service import _resolve_language
    from app.config import get_settings

    class FakeBrand:
        language = ""

    settings = get_settings()
    original_default = settings.default_language
    settings.default_language = "fr"
    lang = _resolve_language(FakeBrand())
    assert lang == "fr"
    settings.default_language = original_default


def test_tracking_validation_messages_are_translated():
    """Verify that tracking validation messages exist in translations."""
    validation_keys = [
        "tracking.validation.order_id.invalid_chars",
        "tracking.validation.order_id.no_digit",
        "tracking.validation.tracking_number.invalid_chars",
        "tracking.validation.tracking_number.no_digit",
        "tracking.validation.verification.required",
        "tracking.validation.verification.invalid",
    ]
    
    for key in validation_keys:
        en_text = get_text(key, "en")
        es_text = get_text(key, "es")
        assert en_text != key, f"Missing English text for {key}"
        assert es_text != key, f"Missing Spanish text for {key}"


def test_tracking_prompt_messages_are_translated():
    """Verify that tracking prompt messages exist in translations."""
    prompt_keys = [
        "tracking.prompt.pending_lookup",
        "tracking.prompt.provide_id",
        "tracking.prompt.no_value",
        "tracking.prompt.tracking_blocked",
        "tracking.prompt.verification_required",
        "tracking.prompt.verification_needed",
        "tracking.prompt.retry_attempt",
        "tracking.prompt.retry_exhausted",
        "tracking.prompt.invalid_value_retry",
        "tracking.prompt.invalid_value_terminal",
    ]
    
    for key in prompt_keys:
        en_text = get_text(key, "en")
        es_text = get_text(key, "es")
        assert en_text != key, f"Missing English text for {key}"
        assert es_text != key, f"Missing Spanish text for {key}"


def test_tracking_service_validation_with_language():
    """Verify that tracking validation methods accept language parameter."""
    from app.tracking_service import tracking_service
    
    # Test order ID validation
    valid, msg_en = tracking_service.validate_order_id("BIO-1001", "en")
    valid, msg_es = tracking_service.validate_order_id("BIO-1001", "es")
    assert valid is True
    assert msg_en == ""
    assert msg_es == ""
    
    # Test invalid order ID with no digits
    valid_en, msg_en = tracking_service.validate_order_id("ABCD", "en")
    valid_es, msg_es = tracking_service.validate_order_id("ABCD", "es")
    assert valid_en is False
    assert valid_es is False
    assert msg_en != msg_es  # Messages should be different languages
    assert "digit" in msg_en.lower()


def test_tracking_service_verification_with_language():
    """Verify that verification validation accepts language parameter."""
    from app.tracking_service import tracking_service
    
    valid_en, msg_en = tracking_service.validate_verification("user@example.com", "en")
    valid_es, msg_es = tracking_service.validate_verification("user@example.com", "es")
    assert valid_en is True
    assert valid_es is True
    
    valid_en, msg_en = tracking_service.validate_verification("invalid", "en")
    valid_es, msg_es = tracking_service.validate_verification("invalid", "es")
    assert valid_en is False
    assert valid_es is False
    assert msg_en != msg_es

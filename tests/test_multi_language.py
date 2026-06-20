from app.prompts import get_prompt, get_widget_labels


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
    settings.default_language = "fr"
    lang = _resolve_language(FakeBrand())
    assert lang == "fr"

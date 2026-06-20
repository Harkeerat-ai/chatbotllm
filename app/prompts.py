PROMPTS: dict[tuple[str, str], str] = {
    # ── System prompts ──────────────────────────────────────────────
    ("system", "en"): (
        "You are a friendly and knowledgeable assistant for {brand_name}. "
        "Answer the customer's question clearly using only the provided context. "
        "Keep your answer to 2\u20133 sentences. "
        "Write in plain text only \u2014 no bullet points, no markdown, no headers, no URLs. "
        "If the context does not contain the answer, say so politely in one sentence "
        "and suggest the customer reach out to {brand_name} support directly."
    ),
    ("system", "es"): (
        "Eres un asistente amable y conocedor de {brand_name}. "
        "Responde la pregunta del cliente claramente usando solo el contexto proporcionado. "
        "Mant\u00e9n tu respuesta en 2\u20133 oraciones. "
        "Escribe solo en texto plano, sin vi\u00f1etas, markdown, encabezados ni URL. "
        "Si el contexto no contiene la respuesta, dilo cort\u00e9smente en una oraci\u00f3n "
        "y sugiere al cliente que se comunique directamente con {brand_name}."
    ),
    ("system", "fr"): (
        "Vous \u00eates un assistant amical et comp\u00e9tent pour {brand_name}. "
        "R\u00e9pondez clairement \u00e0 la question du client en utilisant uniquement le contexte fourni. "
        "Limitez votre r\u00e9ponse \u00e0 2\u20133 phrases. "
        "\u00c9crivez uniquement en texte brut \u2014 pas de puces, markdown, en-t\u00eates ni URL. "
        "Si le contexte ne contient pas la r\u00e9ponse, dites-le poliment en une phrase "
        "et sugg\u00e9rez au client de contacter directement {brand_name}."
    ),

    # ── Logistics system prompts ────────────────────────────────────
    ("logistics_system", "en"): (
        "You are a helpful logistics assistant for {brand_name}. "
        "Given the tracking data below, write a friendly, natural language update "
        "for the customer. Be concise (2-4 sentences) but include the key information: "
        "current status, current hub, ETA, and any delay reasons. "
        "Write in plain text only - no markdown, no formatting, no bullet points."
    ),
    ("logistics_system", "es"): (
        "Eres un asistente de log\u00edstica \u00fatil para {brand_name}. "
        "Con los datos de seguimiento a continuaci\u00f3n, escribe una actualizaci\u00f3n amigable "
        "en lenguaje natural para el cliente. S\u00e9 conciso (2\u20134 oraciones) pero incluye "
        "la informaci\u00f3n clave: estado actual, centro actual, ETA y motivos de retraso. "
        "Escribe solo en texto plano, sin markdown, formato ni vi\u00f1etas."
    ),
    ("logistics_system", "fr"): (
        "Vous \u00eates un assistant logistique utile pour {brand_name}. "
        "Avec les donn\u00e9es de suivi ci-dessous, \u00e9crivez une mise \u00e0 jour amicale "
        "en langage naturel pour le client. Soyez concis (2\u20134 phrases) mais incluez "
        "les informations cl\u00e9s: statut actuel, hub actuel, ETA et raisons des retards. "
        "\u00c9crivez uniquement en texte brut, sans markdown, formatage ni puces."
    ),

    # ── Clarification prompts ───────────────────────────────────────
    ("clarification_system", "en"): "You are a helpful assistant. Generate a short clarification question.",
    ("clarification_system", "es"): "Eres un asistente \u00fatil. Genera una breve pregunta de aclaraci\u00f3n.",
    ("clarification_system", "fr"): "Vous \u00eates un assistant utile. G\u00e9n\u00e9rez une courte question de clarification.",

    ("clarification_prompt", "en"): (
        "I found information related to: {topic_list}. "
        "Ask the customer a brief clarification question to narrow down what they need about {brand_name}. "
        "Keep it to one sentence. Do not mention the brand name."
    ),
    ("clarification_prompt", "es"): (
        "Encontr\u00e9 informaci\u00f3n relacionada con: {topic_list}. "
        "Haz al cliente una breve pregunta de aclaraci\u00f3n para precisar qu\u00e9 necesita sobre {brand_name}. "
        "Mantenla en una oraci\u00f3n. No menciones el nombre de la marca."
    ),
    ("clarification_prompt", "fr"): (
        "J'ai trouv\u00e9 des informations li\u00e9es \u00e0: {topic_list}. "
        "Posez au client une br\u00e8ve question de clarification pour pr\u00e9ciser ce dont il a besoin concernant {brand_name}. "
        "Limitez-vous \u00e0 une phrase. Ne mentionnez pas le nom de la marque."
    ),

    ("clarification_fallback", "en"): "I found information about {topic_list}. Could you be more specific?",
    ("clarification_fallback", "es"): "Encontr\u00e9 informaci\u00f3n sobre {topic_list}. \u00bfPodr\u00edas ser m\u00e1s espec\u00edfico?",
    ("clarification_fallback", "fr"): "J'ai trouv\u00e9 des informations sur {topic_list}. Pourriez-vous \u00eatre plus sp\u00e9cifique?",

    ("clarification_none", "en"): "I'm not sure what you're asking. Could you provide more details?",
    ("clarification_none", "es"): "No estoy seguro de lo que preguntas. \u00bfPodr\u00edas proporcionar m\u00e1s detalles?",
    ("clarification_none", "fr"): "Je ne suis pas s\u00fbr de ce que vous demandez. Pourriez-vous fournir plus de d\u00e9tails?",

    # ── Summarization prompts ───────────────────────────────────────
    ("summarization_prompt", "en"): "Summarize this conversation in 2-3 sentences, capturing the main topics and open questions:\n{dialog}",
    ("summarization_prompt", "es"): "Resume esta conversaci\u00f3n en 2\u20133 oraciones, capturando los temas principales y preguntas abiertas:\n{dialog}",
    ("summarization_prompt", "fr"): "R\u00e9sumez cette conversation en 2\u20133 phrases, en capturant les sujets principaux et les questions ouvertes:\n{dialog}",

    ("summarization_system", "en"): "You are a helpful assistant for {brand_name}.",
    ("summarization_system", "es"): "Eres un asistente \u00fatil para {brand_name}.",
    ("summarization_system", "fr"): "Vous \u00eates un assistant utile pour {brand_name}.",

    # ── Suggestion prompts ──────────────────────────────────────────
    ("suggestion_prompt", "en"): (
        "Based on this customer service conversation for {brand_name}, "
        "suggest 2-3 very short follow-up questions the customer might ask next. "
        "Keep each question under 10 words. "
        "Return ONLY a JSON array of strings, nothing else."
    ),
    ("suggestion_prompt", "es"): (
        "Bas\u00e1ndote en esta conversaci\u00f3n de servicio al cliente para {brand_name}, "
        "sugiere 2\u20133 preguntas de seguimiento muy cortas que el cliente podr\u00eda hacer a continuaci\u00f3n. "
        "Mant\u00e9n cada pregunta en menos de 10 palabras. "
        "Devuelve SOLO un array JSON de cadenas, nada m\u00e1s."
    ),
    ("suggestion_prompt", "fr"): (
        "Sur la base de cette conversation de service client pour {brand_name}, "
        "sugg\u00e9rez 2\u20133 questions de suivi tr\u00e8s courtes que le client pourrait poser ensuite. "
        "Gardez chaque question sous 10 mots. "
        "Retournez UNIQUEMENT un tableau JSON de cha\u00eenes, rien d'autre."
    ),
}


def get_prompt(key: str, language: str) -> str:
    lang = language if (key, language) in PROMPTS else "en"
    return PROMPTS[(key, lang)]


WIDGET_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "assistant": "Assistant",
        "placeholder": "Ask a question\u2026",
        "send": "Send",
        "sources": "Sources:",
        "helpful": "Helpful",
        "not_helpful": "Not helpful",
        "feedback_thanks": "Thanks for the feedback!",
        "feedback_improve": "Noted, we'll improve.",
        "network_error": "Network error \u2014 please try again.",
        "powered_by": "powered by RAG",
    },
    "es": {
        "assistant": "Asistente",
        "placeholder": "Haz una pregunta\u2026",
        "send": "Enviar",
        "sources": "Fuentes:",
        "helpful": "\u00datil",
        "not_helpful": "No \u00fatil",
        "feedback_thanks": "\u00a1Gracias por tu comentario!",
        "feedback_improve": "Anotado, mejoraremos.",
        "network_error": "Error de red \u2014 int\u00e9ntalo de nuevo.",
        "powered_by": "impulsado por RAG",
    },
    "fr": {
        "assistant": "Assistant",
        "placeholder": "Posez une question\u2026",
        "send": "Envoyer",
        "sources": "Sources:",
        "helpful": "Utile",
        "not_helpful": "Pas utile",
        "feedback_thanks": "Merci pour votre avis !",
        "feedback_improve": "Not\u00e9, nous nous am\u00e9liorerons.",
        "network_error": "Erreur r\u00e9seau \u2014 veuillez r\u00e9essayer.",
        "powered_by": "propuls\u00e9 par RAG",
    },
}


def get_widget_labels(language: str) -> dict[str, str]:
    return WIDGET_LABELS.get(language, WIDGET_LABELS["en"])

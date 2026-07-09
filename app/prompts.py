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
    ("clarification_system", "es"): "Eres un asistente útil. Genera una pregunta de aclaración corta.",
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
    ("clarification_fallback", "es"): "Encontré información sobre {topic_list}. ¿Podrías ser más específico?",
    ("clarification_fallback", "fr"): "J'ai trouv\u00e9 des informations sur {topic_list}. Pourriez-vous \u00eatre plus sp\u00e9cifique?",

    ("clarification_none", "en"): "I'm not sure what you're asking. Could you provide more details?",
    ("clarification_none", "es"): "No estoy seguro de lo que me estás preguntando. ¿Podrías proporcionar más detalles?",
    ("clarification_none", "fr"): "Je ne suis pas s\u00fbr de ce que vous demandez. Pourriez-vous fournir plus de d\u00e9tails?",

    # ── Summarization prompts ───────────────────────────────────────
    ("summarization_prompt", "en"): "Summarize this conversation in 2-3 sentences, capturing the main topics and open questions:\n{dialog}",
    ("summarization_prompt", "es"): "Resuma esta conversación en 2-3 oraciones, capturando los temas principales y las preguntas abiertas.",
    ("summarization_prompt", "fr"): "R\u00e9sumez cette conversation en 2\u20133 phrases, en capturant les sujets principaux et les questions ouvertes:\n{dialog}",

    ("summarization_system", "en"): "You are a helpful assistant for {brand_name}.",
    ("summarization_system", "es"): "Usted es un asistente útil para {brand_name}.",
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

    # ── Language placeholders for ar, hi, mr, ta, gu, pa ─────────────
    # These will be populated by the translation script in Phase 5
    ("system", "ar"): "أنت مساعد ودية ومتخصصة ل{brand_name}. اجيب سؤال الزبون بوضوح باستخدام فقط السياق المُقدم. احتفظ بجوابك في 2-3 جمل. اكتب في نص عادي فقط — بدون نقط التأخير، بدون علامات التبويب، بدون رؤوس الصفحة، بدون روابط. إذا لم يحتوي السياق على الإجابة، قل ذلك بطريقة لطيفة في جملة واحدة واقترح على الزبون الاتصال بمساعدة {brand_name} مباشرة.",
    ("system", "hi"): "आप {brand_name} के लिए एक दोस्ताना और ज्ञानी सहायक हैं। ग्राहक के प्रश्न का उत्तर दें जो स्पष्ट रूप से प्रदान किए गए संदर्भ का उपयोग करता है। अपने उत्तर को 2-3 वाक्यों में रखें। केवल सामान्य पाठ में लिखें - बुलेट पॉइंट्स, मार्कडाउन, हेडर्स, यूआरएल के बिना। यदि संदर्भ में उत्तर नहीं है, तो एक वाक्य में दयालुतापूर्वक कहें और ग्राहक को {brand_name} के समर्थन से सीधे संपर्क करने का सुझाव दें।",
    ("system", "mr"): "तुम्ही {brand_name} चे एक मित्र आणि ज्ञानी सहाय्यक आहात. ग्राहकाच्या प्रश्नाचे उत्तर द्या जे स्पष्टपणे प्रदान केलेल्या संदर्भाचा वापर करते. तुमचे उत्तर २-३ वाक्यांत ठेवा. केवळ सामान्य पाठमध्ये लिहा. बुलेट पॉइंट्स, मार्कडाउन, हेडर्स, यूआरएलचा वापर करू नका. जर संदर्भात उत्तर नसेल तर दयालुतेपणे एक वाक्यात सांगा आणि ग्राहकाला {brand_name} च्या समर्थनाशी सीधे संपर्क साधण्याचा सुझाव द्या.",
    ("system", "ta"): "நீயே {brand_name} க்கான நல்லுறவுடைய மற்றும் அறிவுடைய உதவியாளர். கடையாளரின் கேள்விக்கு முழுமையான சான்றுடன் மட்டுமே த",
    ("system", "gu"): "You are a friendly and knowledgeable assistant for {brand_name}. Answer the customer's question clearly using only the provided context. Keep your answer to 2–3 sentences. Write in plain text only — no bullet points, no markdown, no headers, no URLs. If the context does not contain the answer, say so politely in one sentence and suggest the customer reach out to {brand_name} support directly.",
    ("system", "pa"): "You are a friendly and knowledgeable assistant for {brand_name}. Answer the customer's question clearly using only the provided context. Keep your answer to 2–3 sentences. Write in plain text only — no bullet points, no markdown, no headers, no URLs. If the context does not contain the answer, say so politely in one sentence and suggest the customer reach out to {brand_name} support directly.",

    ("logistics_system", "ar"): "أنت مساعد تتبع مفيد ل {brand_name}. مع البيانات التتبعية أدناه، كتابة تحديث صديق وطبيعي للعملاء. كن مختصرًا (2-4 جمل) ولكن احصل على المعلومات الرئيسية: الحالة الحالية، المركز الحالي، ووقت الوصول المتوقع، وسبب التأخير. اكتب فقط في نص بسيط - بدون علامات تنسيق، بدون ترقيم، بدون نقاط.",
    ("logistics_system", "hi"): "आप {brand_name} के लिए एक उपयोगी लॉजिस्टिक सहायक हैं। नीचे दिए गए ट्रैकिंग डेटा के साथ, ग्राहक के लिए एक दोस्ताना और प्राकृतिक भाषा में अपडेट लिखें। 2-4 वाक्यों में संक्षिप्त रहें, लेकिन मुख्य जानकारी शामिल करें: वर्तमान स्थिति, वर्तमान हब, ईटीए, और किसी भी देरी कारण। केवल प्लेन टेक्स्ट में लिखें - कोई मार्कडाउन, कोई फॉर्मेटिंग, कोई बुलेट पॉइंट्स नहीं।",
    ("logistics_system", "mr"): "तुम्ही {brand_name} साठी उपयुक्त लॉजिस्टिक सहाय्यक आहात. खालील ट्रॅकिंग डेटा पाहून, ग्राहकांच्या लिए एक मैत्रीपूर्ण आणि सामान्य भाषेत अपडेट लिहा. 2-4 वाक्यांत संक्षिप्त राहा, परंतु मुख्य माहिती समाविष्ट करा: वर्तमान स्थिती, वर्तमान हब, ईटीए, आणि कोणत्याही देरीचे कारण. केवळ साधा पाठ लिहा, - कोणत्याही मार्कडाउन, कोणत्याही फॉर्मेटिंग, कोणत्याही बुलेट पॉइंट्स नाही.",
    ("logistics_system", "ta"): "நீயே {brand_name} க்கான உதவியாளர் ஆவாய். கீழே கொடுக்கப்பட்ட ட்ராக்கிங் தரவுகளை பார்த்து, வாடிக்கைய",
    ("logistics_system", "gu"): "You are a helpful logistics assistant for {brand_name}. Given the tracking data below, write a friendly, natural language update for the customer. Be concise (2-4 sentences) but include the key information: current status, current hub, ETA, and any delay reasons. Write in plain text only - no markdown, no formatting, no bullet points.",
    ("logistics_system", "pa"): "ਤੁਸੀਂ {brand_name} ਦੇ ਮਦਦਗਾਰ ਲੋਜਿਸਟਿਕ ਸਹਾਇਕ ਹੋ ਰਹੇ ਹੋ। ਨੀਚੇ ਦਿੱਤੀ ਗਈ ਟ੍ਰੈਕਿੰਗ ਡੇਟਾ ਲਈ, ਗਰਮਜ਼ਾਰ ਭਾਸ਼ਾ ਵਿੱਚ ਇੱਕ ਮਿੱਠੀ, ਸਹਾਇਕ ਭਾਸ਼ਾ ਵਿੱਚ ਕਿਸਾਨ ਦੇ ਲਈ ਇੱਕ ਸੌਖਾ ਹੋਵੇਗਾ ਜਾਣਕਾਰੀ ਦਾ ਸੰਕੇਤ ਲਿਖੋ। ਸ਼ੁੱਧ ਸੰਕੇਤ",

    ("clarification_system", "ar"): "أنت مساعد مفيد. إجراء سؤال واضح قصير.",
    ("clarification_system", "hi"): "आप एक उपयोगी सहायक हैं। एक छोटी स्पष्टीकरण प्रश्न उत्पन्न करें।",
    ("clarification_system", "mr"): "तुम एक उपयुक्त सहाय्यक आहात. एक लहान स्पष्टीकरण प्रश्न निर्माण करा.",
    ("clarification_system", "ta"): "நீங்கள் ஒரு உதவியாளர். ஒரு சுருக்கமான விளக்க கேள்வி உருவாக்குங்கள்.",
    ("clarification_system", "gu"): "તમે એક મદદગાર છો. એક લઘુ સ્પષ્ટતા પ્રશ્ન ઉત્પન્ન કરો.",
    ("clarification_system", "pa"): "ਤੂੰ ਇਕ ਮਦਦਗਾਰ ਹੈਂ। ਇਕ ਛੋਟਾ ਸਪਸ਼ਟੀਕਰਨ ਪ੍ਰਸ਼ਨ ਪੈਦਾ ਕਰ।",

    ("clarification_prompt", "ar"): "وجدت معلومات متعلقة بـ: {topic_list}. اسأل العميل سؤالًا لتسليط الضوء على ما يحتاجونه عن {brand_name}. احتفظ به في جملة واحدة. لا تذكر اسم العلامة التجارية.",
    ("clarification_prompt", "hi"): "मैंने {topic_list} से संबंधित जानकारी पाई। ग्राहक से एक छोटी सी स्पष्टीकरण की प्रश्न पूछें ताकि वे क्या चाहते हैं वह स्पष्ट हो जाए। एक वाक्य में रखें। ब्रांड का नाम न दें.",
    ("clarification_prompt", "mr"): "मी {topic_list} संबंधित माहिती शोधली. ग्राहकांना एक लहान स्पष्टीकरण प्रश्न विचारा की ते काय हवे ते स्पष्ट होईल. एक वाक्यात राखा. ब्रँडचे नाव न द्या.",
    ("clarification_prompt", "ta"): "நான் {topic_list} தொடர்பான தகவல்களைக் கண்டேன். கடையாளரிடம் ஒரு சிறிய விளக்க கேள்வி கேட்டு, அவர்கள் என்ன வேண்டும் என்பதை விரித்துக் கூறுங்கள். ஒரு சொற்றொடராக இருங்கள். பிராண்டின் பெயரை குறிப்பிடாதீர்கள்.",
    ("clarification_prompt", "gu"): "મને {topic_list} સાથે સંબંધિત માહિતી મળી છે. ગ્રાહકને એક સરળ સમજૂતીની પ્રશ્ન પૂછો તેને શું જરૂરી છે તે સમજાવો. એક વાક્યમાં રાખો. બ્રાન્ડનું નામ ન કહો.",
    ("clarification_prompt", "pa"): "ਮੈਂ {topic_list} ਨਾਲ ਸੰਬ",

    ("clarification_fallback", "ar"): "وجدت معلومات عن {topic_list}. هل يمكنك أن تكون أكثر تحديدًا؟",
    ("clarification_fallback", "hi"): "मैंने {topic_list} के बारे में जानकारी प्राप्त की। क्या आप अधिक विशिष्ट हो सकते हैं?",
    ("clarification_fallback", "mr"): "मी {topic_list} बद्दल माहिती मिळवली. कृपया अधिक विशिष्ट हो.",
    ("clarification_fallback", "ta"): "{topic_list} பற்றி நான் தகவல் பெற்றேன். நீங்கள் அதிக தெளிவாக இருக்க முடியுமா?",
    ("clarification_fallback", "gu"): "મને {topic_list} વિશેની માહિતી મળી છે. તમે વધુ વિશેષ બની શકો છો?",
    ("clarification_fallback", "pa"): "ਮੈਂ {topic_list} ਬਾਰੇ ਜਾਣਕਾਰੀ ਲੱਭੀ। ਤੁਸੀਂ ਵੱਧ ਵਿਸ਼ੇਸ਼ ਹੋ ਸਕਦੇ ਹੋ?",

    ("clarification_none", "ar"): "أنا لا أستطيع أن أكون متأكدًا من ما تريد سؤالي. هل يمكنك أن توفر تفاصيل إضافية؟",
    ("clarification_none", "hi"): "मुझे नहीं पता कि आप क्या पूछ रहे हैं। कृपया अधिक विवरण प्रदान करें।",
    ("clarification_none", "mr"): "मी निश्चित नाही की तुम्ही काय विचारूं आहेस. कृपया अधिक माहिती द्या.",
    ("clarification_none", "ta"): "நான் தெரியாது நீ ஏன் கேட்டாய். நீ அதிக விவரங்களை தருமா?",
    ("clarification_none", "gu"): "મને તમારી પૂછપરછ વિશે સંભાવનાઓ નથી. કૃપા કરીને વધુ વિગતો આપો.",
    ("clarification_none", "pa"): "ਮੈਂ ਤਾਂ ਸਮਝ ਨਹੀਂ ਪਾ ਰਿਹਾ ਕਿ ਤੂੰ ਕੀ ਕਹਿ ਰਿਹਾ ਹੈਂ। ਕੁਝ ਵਧੇਰੇ ਜਾਣਕਾਰੀ ਦੇ ਕੇ ਦੱਸ।",

    ("summarization_prompt", "ar"): "استعرض هذه المحادثة في 2-3 جمل, يلقي الضوء على المواضيع الرئيسية والأسئلة المفتوحة.",
    ("summarization_prompt", "hi"): (
        "Summarize this conversation in 2-3 sentences, capturing the main topics and open questions:\n{dialog}"
    ),
    ("summarization_prompt", "mr"): (
        "Summarize this conversation in 2-3 sentences, capturing the main topics and open questions:\n{dialog}"
    ),
    ("summarization_prompt", "ta"): (
        "Summarize this conversation in 2-3 sentences, capturing the main topics and open questions:\n{dialog}"
    ),
    ("summarization_prompt", "gu"): (
        "Summarize this conversation in 2-3 sentences, capturing the main topics and open questions:\n{dialog}"
    ),
    ("summarization_prompt", "pa"): (
        "Summarize this conversation in 2-3 sentences, capturing the main topics and open questions:\n{dialog}"
    ),

    ("summarization_system", "ar"): "{brand_name} لديك مساعدتك.",
    ("summarization_system", "hi"): "{brand_name} के लिए आपका सहायक है।",
    ("summarization_system", "mr"): "{brand_name} चा मदतीचा सहाय्यक आहे.",
    ("summarization_system", "ta"): "{brand_name} க்கான உங்கள் உதவி நிபுணர் ஆவார்.",
    ("summarization_system", "gu"): "{brand_name} માટે તમારો સહાયક છે.",
    ("summarization_system", "pa"): "{brand_name} ਲਈ ਤੁਹਾਡਾ ਸਹਾਇਕ ਹੈ।",

    ("suggestion_prompt", "ar"): "بناءً على هذه المحادثة للخدمة العملاء ل {brand_name}، اقترح 2-3 أسئلة متابعة قصيرة جدًا التي قد يسألها العميل التالي. احتفظ بكل سؤال تحت 10 كلمات. أرجع فقط مصفوفة JSON من سلسلة، لا شيء آخر.",
    ("suggestion_prompt", "hi"): "{brand_name} के लिए ग्राहक सेवा संवाद पर आधारित, ग्राहक अगले के लिए 2-3 बहुत छोटे पालने के प्रश्न सुझाएं। प्रत्येक प्रश्न को 10 शब्दों के नीचे रखें। केवल एक JSON स्ट्रिंग्स का मассив वापस करें।",
    ("suggestion_prompt", "mr"): "{brand_name} ची ग्राहक सेवा संवादावर आधारित, ग्राहक पुढे करण्यासाठी २-३ खूप लहान पालने करण्यासाठी प्रश्न सुचवा. प्रत्येक प्रश्न १० शब्दांपेक्षा कमी असणे. केवळ JSON मधील stringचा array वापस करा.",
    ("suggestion_prompt", "ta"): "{brand_name} குறித்த பயனர் சேவை பேச்சு மூலம், அடுத்தவர் கேட்க முடியும் 2-3 சிறிய பின்வரும் கேள்விகளை பரிந்துரையுங்கள். ஒவ்வொரு கேள்வியும் 10 வார்த்தைகளுக்கு கீழே இருக்க வேண்டும். ஒரே JSON தொடர்களின் பட்டியலைத் திருப்பி அளியுங்கள்.",
    ("suggestion_prompt", "gu"): "{brand_name} ની ગ્રાહક સેવા ચર્ચા પર આધારિત, ગ્રાહક પછી કરવા માટે 2-3 ખૂબ લાંબા પગલાના પ્રશ",
    ("suggestion_prompt", "pa"): "Based on this customer service conversation for {brand_name}, suggest 2-3 very short follow-up questions the customer might ask next. Keep each question under 10 words. Return ONLY a JSON array of strings, nothing else.",
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
        "welcome": "Hello! How can I help you?",
    },
    "es": {
        "assistant": "Asistente",
        "feedback_improve": "Se ha notado, mejoraremos.",
        "feedback_thanks": "Gracias por el feedback!",
        "helpful": "Útil",
        "network_error": "Error de red — por favor inténtelo de nuevo.",
        "not_helpful": "No es útil",
        "placeholder": "Haz una pregunta\u2026",
        "powered_by": "impulsado por RAG",
        "send": "Enviar",
        "sources": "Fuentes:",
        "welcome": "Hola! Cómo puedo ayudarte?",
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
        "welcome": "Bonjour ! Comment puis-je vous aider ?",
    },
    "ar": {
        "assistant": "مساعد",
        "feedback_improve": "أُشير إلى ذلك، سنتحسين.",
        "feedback_thanks": "شكراً على الرأي!",
        "helpful": "مفيد",
        "network_error": "خطأ في الشبكة — يُرجى المحاولة مرة أخرى.",
        "not_helpful": "لا يساعد",
        "placeholder": "اسأل سؤالا…",
        "powered_by": "مسند على RAG",
        "send": "أرسل",
        "sources": "المصادر:",
        "welcome": "مرحباً! كيف يمكنني مساعدتك؟",
    },
    "hi": {
        "assistant": "सहायक",
        "feedback_improve": "पहचाना गया, हम सुधारेंगे।",
        "feedback_thanks": "धन्यवाद फीडबैक के लिए!",
        "helpful": "सहायक",
        "network_error": "नेटवर्क त्रुटि — कृपया फिर से प्रयास करें.",
        "not_helpful": "नहीं सहायक",
        "placeholder": "एक प्रश्न पूछें…",
        "powered_by": "RAG द्वारा संचालित",
        "send": "भेजें",
        "sources": "स्रोत:",
        "welcome": "नमस्ते! मैं आपकी कैसे मदद कर सकता हूँ?",
    },
    "mr": {
        "assistant": "सहायक",
        "feedback_improve": "पाहिल्यानंतर, आम्ही सुधारू.",
        "feedback_thanks": "धन्यवाद फीडबॅकसाठी!",
        "helpful": "सहाय्यक",
        "network_error": "नेटवर्क त्रुटी — कृपया फिर प्रयत्न करा.",
        "not_helpful": "नसलेले",
        "placeholder": "एक प्रश्न पूछा…",
        "powered_by": "RAG द्वारे चालविले जाते",
        "send": "पाठवा",
        "sources": "स्रोते:",
        "welcome": "नमस्कार! मी तुमची कशी मदत करू शकतो?",
    },
    "ta": {
        "assistant": "உதவியாளர்",
        "feedback_improve": "குறிப்பிடப்பட்டது, நாம் மேம்படுத்துவோம்.",
        "feedback_thanks": "நன்றி வாழ்த்துக்கள் பதிலுக்கு!",
        "helpful": "உதவுகிறது",
        "network_error": "நெட்வொர்க் தவறு — மீண்டும் முயற்சிக்க.",
        "not_helpful": "அல்ல",
        "placeholder": "ஒரு கேள்வி கேட்போம்…",
        "powered_by": "RAG அடிப்படையில்",
        "send": "அனுப்பு",
        "sources": "ஆதாரங்கள்:",
        "welcome": "வணக்கம்! உங்களுக்கு எப்படி உதவ முடியும்?",
    },
    "gu": {
        "assistant": "સહાયક",
        "feedback_improve": "નોંધાયું, અમે સુધારશું.",
        "feedback_thanks": "આભાર ફીડબેક માટે!",
        "helpful": "સહાયક",
        "network_error": "નેટવર્ક તકરાર — કૃપयાથી ફરીથી પ્રયત્ન કરો.",
        "not_helpful": "નહીં સહાયક",
        "placeholder": "એક પ્રશ્ન પૂછો…",
        "powered_by": "RAG દ્વારા શક્તિશાળી",
        "send": "મોકલો",
        "sources": "સ્રોત:",
        "welcome": "નમસ્તે! હું તમારી કેવી રીતે મદદ કરી શકું?",
    },
    "pa": {
        "assistant": "ਸਹਾਇਕ",
        "feedback_improve": "ਨੋਟ ਕੀਤਾ ਗਿਆ, ਅਸੀਂ ਸੁਧਾਰੀਏਂਗੇ।",
        "feedback_thanks": "ਧੰਨਵਾਦ ਫੀਡਬੈਕ ਲਈ!",
        "helpful": "ਸਹਾਇਕ",
        "network_error": "ਨੈੱਟਵਰਕ ਸਮੱਸਿਆ — ਕਿਰਪਾ ਕਰਕੇ ਫਿਰ ਸੁਪਨਾ ਕਰੋ.",
        "not_helpful": "ਨਹੀਂ ਸਹਾਇਕ",
        "placeholder": "ਇਕ ਪ੍ਰਸ਼ਨ ਪੁੱਛੋ…",
        "powered_by": "RAG ਦੁਆਰਾ ਸ਼ਕਤੀਸ਼ਾਲੀ",
        "send": "ਭੇਜੋ",
        "sources": "ਸਰੋਤ:",
        "welcome": "ਨਮਸਤੇ! ਮੈਂ ਤੁਹਾਡੀ ਕਿਵੇਂ ਮਦਦ ਕਰ ਸਕਦਾ ਹਾਂ?",
    },
}


def get_widget_labels(language: str) -> dict[str, str]:
    return WIDGET_LABELS.get(language, WIDGET_LABELS["en"])

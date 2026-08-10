"""
translate_strings.py — One-time script to populate translations for 6 new languages using Groq LLM.

Usage: python scripts/translate_strings.py

This script:
1. Extracts all English strings from translations.py and prompts.py
2. Translates them to ar, hi, mr, ta, gu, pa using Groq API
3. Outputs candidate translations for manual review and integration
"""

import asyncio
import json
import sys
from pathlib import Path
import os

import httpx

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import get_settings
from app.translations import TRANSLATIONS, SUPPORTED_LANGUAGES
from app.prompts import PROMPTS, WIDGET_LABELS

settings = get_settings()

TARGET_LANGUAGES = ["es", "ar", "hi", "mr", "ta", "gu", "pa"]

LANGUAGE_NAMES = {
    "es": "Spanish",
    "ar": "Arabic",
    "hi": "Hindi",
    "mr": "Marathi",
    "ta": "Tamil",
    "gu": "Gujarati",
    "pa": "Punjabi",
}


class TranslationHelper:
    def __init__(self):
        self.groq_api_key = settings.groq_api_key
        self.groq_base_url = settings.groq_base_url
        self.model = settings.groq_model
        
    async def translate_to_all(self, key: str, english_text: str) -> dict[str, str] | None:
        """Translate one English string to ALL target languages in a single API call."""
        if not self.groq_api_key:
            print("ERROR: GROQ_API_KEY not set. Cannot translate.")
            return None
        
        lang_list = "\n".join(f"  {i+1}. {lang}" for i, (code, lang) in enumerate(zip(TARGET_LANGUAGES, [LANGUAGE_NAMES[l] for l in TARGET_LANGUAGES])))
        prompt = f"""Translate the following English text to ALL of these languages:

{lang_list}

For each language, provide ONLY the translated text, nothing else.
Format your response as a JSON object with language codes as keys.

English: {english_text}

JSON:"""
        
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{self.groq_base_url}/chat/completions",
                        json={
                            "model": self.model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.3,
                            "max_tokens": 500,
                        },
                        headers={"Authorization": f"Bearer {self.groq_api_key}"},
                    )
                    if response.status_code == 429:
                        wait = 2 ** attempt
                        print(f"  rate limited, retrying in {wait}s...")
                        await asyncio.sleep(wait)
                        continue
                    if response.status_code == 200:
                        content = response.json()["choices"][0]["message"]["content"].strip()
                        # Extract JSON from response
                        import re
                        json_match = re.search(r'\{.*\}', content, re.DOTALL)
                        if json_match:
                            import json as json_mod
                            result = json_mod.loads(json_match.group())
                            # Validate we got all languages
                            valid = {}
                            for code in TARGET_LANGUAGES:
                                val = result.get(code, "")
                                if val and val != english_text and len(val) > 0:
                                    valid[code] = val
                            return valid
                    else:
                        print(f"WARNING: Translation failed for '{english_text[:40]}...': {response.status_code}")
                        return None
            except Exception as e:
                print(f"ERROR: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return None
        return None
    
    async def translate_batch(self, strings: list[tuple[str, str]], target_langs: list[str]) -> dict:
        """Translate all strings one by one, each to all target languages at once."""
        results: dict[str, dict[str, str]] = {lang: {} for lang in target_langs}
        success = 0
        failed = 0
        
        for i, (key, english_text) in enumerate(strings):
            print(f"[{i+1}/{len(strings)}] Translating '{key}': {english_text[:50]}...")
            translations = await self.translate_to_all(key, english_text)
            if translations:
                for lang, text in translations.items():
                    results[lang][key] = text
                success += 1
                print(f"  -> OK: {', '.join(translations.keys())}")
            else:
                failed += 1
                print(f"  -> FAILED")
        
        print(f"\nBatch complete: {success} ok, {failed} failed out of {len(strings)}")
        return results
    
    async def generate_translation_python(self, translations: dict) -> str:
        """Generate Python code for the new translations."""
        code_lines = ["# Translated strings — review and integrate into app/translations.py"]
        code_lines.append("# Generated by scripts/translate_strings.py")
        code_lines.append("")
        
        for lang, lang_translations in translations.items():
            code_lines.append(f"# {LANGUAGE_NAMES.get(lang, lang).upper()} ({lang})")
            for key, translated_text in lang_translations.items():
                escaped = translated_text.replace('"', '\\"')
                code_lines.append(f'    ("{key}", "{lang}"): "{escaped}",')
            code_lines.append("")
        
        return "\n".join(code_lines)


async def main():
    """Main entry point."""
    print("=" * 70)
    print("Multi-Language Translation Generator")
    print("=" * 70)
    print()
    
    helper = TranslationHelper()
    
    # Extract all English strings from translations
    english_strings = []
    for (key, lang), text in TRANSLATIONS.items():
        if lang == "en":
            english_strings.append((key, text))
    
    # Extract prompt strings
    for (key, lang), text in PROMPTS.items():
        if lang == "en":
            english_strings.append((f"prompt.{key}", text))
    
    # Extract widget labels
    for label_key, label_text in WIDGET_LABELS["en"].items():
        english_strings.append((f"widget.{label_key}", label_text))
    
    print(f"Found {len(english_strings)} English strings to translate")
    print(f"Target languages: {', '.join(TARGET_LANGUAGES)}")
    print()
    
    if not helper.groq_api_key:
        print("WARNING: GROQ_API_KEY not set. Skipping translations.")
        print("Set GROQ_API_KEY in .env and run this script again.")
        return
    
    print("Starting translations (this may take a few minutes)...")
    print()
    
    translations = await helper.translate_batch(english_strings, TARGET_LANGUAGES)
    
    # Generate Python code
    python_code = await helper.generate_translation_python(translations)
    
    # Save to a file
    output_path = Path(__file__).parent / "translated_strings.py"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(python_code)
    
    print()
    print("=" * 70)
    print(f"Translations saved to: {output_path}")
    print()
    print("Next steps:")
    print("1. Review the translated strings in translated_strings.py")
    print("2. Copy the translations for each language into app/translations.py")
    print("3. Copy the prompt translations into app/prompts.py")
    print("4. Copy the widget label translations into app/prompts.py (WIDGET_LABELS)")
    print("5. Run tests to verify: pytest tests/test_multi_language.py -v")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

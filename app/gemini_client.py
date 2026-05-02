import json
import logging
import os
from typing import Dict, List, Literal

from google import genai
from google.genai import types
from pydantic import BaseModel

from .config import get_gemini_api_key
from .faq_data import INFO

logger = logging.getLogger(__name__)

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
HISTORY_LIMIT = 10  # combined user+model turns kept per user

_client: genai.Client | None = None
_history: Dict[int, List[types.Content]] = {}

Lang = Literal["en", "uz", "ru"]

FALLBACK_MESSAGES: Dict[str, str] = {
    "en": "Sorry — I'm having trouble right now. Please try again in a moment.",
    "uz": "Kechirasiz — hozir muammo yuz berdi. Birozdan keyin qayta urinib ko'ring.",
    "ru": "Извините — сейчас возникла проблема. Пожалуйста, попробуйте чуть позже.",
}


class AnswerResponse(BaseModel):
    answer: str
    intent: Literal["info", "other"]
    language: Lang


class LanguageResponse(BaseModel):
    language: Lang


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=get_gemini_api_key())
    return _client


def _system_instruction() -> str:
    return (
        "You are the IDU Student Support Bot for International Degree University.\n"
        "Help students with questions about the university using the REFERENCE INFO below.\n\n"
        "LANGUAGE RULES (highest priority):\n"
        "- Detect the language of the user's latest message: English ('en'), Uzbek ('uz'), or Russian ('ru').\n"
        "- ALWAYS write your answer in that same language. If the user wrote in Uzbek, "
        "the entire answer MUST be in Uzbek; if Russian, the entire answer MUST be in Russian — "
        "even if the REFERENCE INFO below is in another language. Translate as needed.\n"
        "- Keep URLs, room numbers, system names, and proper nouns verbatim — do not translate or transliterate them.\n\n"
        "CONTENT RULES:\n"
        "- Stay grounded in the REFERENCE INFO for facts (URLs, navigation steps, contacts, policies).\n"
        "- Do not invent IDU-specific facts that are not present in the REFERENCE INFO.\n"
        "- If the question is unrelated to IDU student support or not covered by the info, "
        "politely say so and redirect (in the user's language).\n\n"
        f"REFERENCE INFO (translate as needed):\n{INFO}\n\n"
        "OUTPUT:\n"
        "- Set 'intent' to 'info' if your answer is grounded in the REFERENCE INFO, otherwise 'other'.\n"
        "- Set 'language' to 'en', 'uz', or 'ru' matching your answer."
    )


async def _detect_language_via_gemini(text: str) -> Lang:
    """Ask Gemini to classify text as 'en', 'uz', or 'ru'. Defaults to 'en' on failure."""
    try:
        response = await _get_client().aio.models.generate_content(
            model=MODEL,
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "Classify the language of the user's message as 'en' (English), "
                    "'uz' (Uzbek), or 'ru' (Russian). Reply with JSON only."
                ),
                response_mime_type="application/json",
                response_schema=LanguageResponse,
            ),
        )
        data = json.loads(response.text)
        lang = data.get("language", "en")
        return lang if lang in FALLBACK_MESSAGES else "en"
    except Exception:
        logger.exception("Gemini language detection failed")
        return "en"


async def ask_gemini(user_id: int, text: str) -> dict:
    """Send `text` to Gemini with per-user history; return {answer,intent,language}."""
    history = _history.setdefault(user_id, [])
    history.append(types.Content(role="user", parts=[types.Part(text=text)]))

    try:
        response = await _get_client().aio.models.generate_content(
            model=MODEL,
            contents=history,
            config=types.GenerateContentConfig(
                system_instruction=_system_instruction(),
                response_mime_type="application/json",
                response_schema=AnswerResponse,
            ),
        )
        data = json.loads(response.text)
        history.append(
            types.Content(role="model", parts=[types.Part(text=data["answer"])])
        )
        if len(history) > HISTORY_LIMIT:
            del history[: len(history) - HISTORY_LIMIT]
        return data
    except Exception:
        logger.exception("Gemini request failed")
        if history and history[-1].role == "user":
            history.pop()
        lang = await _detect_language_via_gemini(text)
        return {
            "answer": FALLBACK_MESSAGES[lang],
            "intent": "error",
            "language": lang,
        }

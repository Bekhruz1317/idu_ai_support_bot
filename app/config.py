import os
from dotenv import load_dotenv

load_dotenv()


def get_bot_token() -> str:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError(
            "Missing TELEGRAM_TOKEN environment variable. "
            "Set it in .env before running the bot."
        )
    return token


def get_gemini_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "Missing GEMINI_API_KEY environment variable. "
            "Set it in .env before running the bot."
        )
    return key


def get_admin_id() -> int:
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    if admin_id:
        try:
            return int(admin_id)
        except ValueError:
            return 0
    return 0

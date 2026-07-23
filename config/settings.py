import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()

OPENROUTER_API_KEY = (
    os.getenv("OPENROUTER_API_KEY") or ""
).strip()

LLM_MODEL = (
    os.getenv("LLM_MODEL") or "openrouter/free"
).strip()


if not BOT_TOKEN:
    raise RuntimeError(
        "Переменная BOT_TOKEN не найдена. Проверьте файл .env."
    )

if not OPENROUTER_API_KEY:
    raise RuntimeError(
        "Переменная OPENROUTER_API_KEY не найдена. "
        "Проверьте файл .env."
    )

if not OPENROUTER_API_KEY.isascii():
    raise RuntimeError(
        "OPENROUTER_API_KEY содержит недопустимые символы."
    )
try:
    MONITOR_INTERVAL_SECONDS = max(
        60,
        int(
            os.getenv(
                "MONITOR_INTERVAL_SECONDS",
                "3600",
            )
        ),
    )
except ValueError as error:
    raise RuntimeError(
        "MONITOR_INTERVAL_SECONDS должен быть целым числом."
    ) from error
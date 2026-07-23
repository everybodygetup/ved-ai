import logging

from openai import AsyncOpenAI

from config.settings import LLM_MODEL, OPENROUTER_API_KEY
from services.prompt_loader import build_system_prompt


logger = logging.getLogger(__name__)


client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    timeout=35.0,
    max_retries=0,
    default_headers={
        "X-OpenRouter-Title": "VED AI",
    },
)

SYSTEM_PROMPT = build_system_prompt()


async def ask_llm(user_input: str) -> str:
    """Отправляет запрос цифровому консультанту по ВЭД."""

    completion = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_input,
            },
        ],
        temperature=0.2,
        max_tokens=500,
    )

    logger.info(
        "Использована модель: %s",
        completion.model,
    )

    if not completion.choices:
        return (
            "Модель не вернула результат. "
            "Попробуйте повторить запрос позднее."
        )

    answer = completion.choices[0].message.content

    if not answer:
        return (
            "Не удалось сформировать ответ. "
            "Попробуйте подробнее описать ситуацию."
        )
    clean_answer = (
    answer
    .replace("<br>", "\n")
    .replace("<br/>", "\n")
    .replace("<br />", "\n")
    .replace("**", "")
)

    return clean_answer.strip()
    
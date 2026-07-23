import asyncio
import logging
from typing import Final

from openai import AsyncOpenAI

from config.settings import (
    LLM_MODEL,
    OPENROUTER_API_KEY,
)
from services.prompt_loader import build_system_prompt


logger = logging.getLogger(__name__)


client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    timeout=90.0,
    max_retries=0,
    default_headers={
        "X-OpenRouter-Title": "VED AI",
    },
)


CONSULTANT_SYSTEM_PROMPT = build_system_prompt()


DOCUMENT_ANALYST_SYSTEM_PROMPT: Final[str] = """
Ты — аналитик нормативных документов в области ВЭД,
таможенного регулирования и законодательства ЕАЭС.

Анализируй только сведения, которые переданы в запросе.

Запрещено придумывать:

- содержание документа;
- новые изменения законодательства;
- статус документа;
- дату вступления в силу;
- коды ТН ВЭД;
- ставки пошлин и налогов;
- категории товаров;
- штрафы и последствия.

ВАЖНО

Дата «Добавлен в базу Alta» означает только дату появления
документа в соответствующем разделе базы Alta.

Она не является автоматически:

- датой принятия;
- датой опубликования;
- датой вступления в силу;
- датой начала действия изменений.

Если документ является проектом решения, прямо укажи,
что это проект, а не окончательно принятое решение.

Если конкретное изменение нельзя установить из текста, напиши:

«Недостаточно данных для определения конкретных изменений».

Если статус не подтверждён, напиши:

«Статус не удалось подтвердить по извлечённому тексту».

Если дата вступления в силу не подтверждена, напиши:

«Дату вступления в силу не удалось подтвердить».

Составь короткий законченный ответ до 1800 символов.

Используй строго такую структуру:

🟢 Справочно / 🟡 Важно / 🔴 Критично

📄 Что это за документ
Краткое описание.

🔎 Что установлено
Только подтверждённые факты.

👥 Кого может касаться
Обоснованные категории участников либо сообщение,
что данных недостаточно.

📅 Статус и сроки
Статус и дата вступления в силу только при подтверждении.

✅ Что проверить специалисту по ВЭД
От двух до пяти конкретных действий.

Не используй таблицы, HTML и Markdown.
Не пиши приветствие.
Не повторяй ссылку.
Не обрывай ответ.
""".strip()


CONSULTANT_FALLBACK: Final[str] = (
    "Не удалось сформировать ответ. "
    "Попробуйте повторить запрос позднее."
)


BAD_RESPONSE_MARKERS: Final[tuple[str, ...]] = (
    "не удалось сформировать ответ",
    "попробуйте подробнее описать ситуацию",
    "модель не вернула результат",
    "попробуйте повторить запрос позднее",
    "user safety: safe",
)


async def ask_llm(
    user_input: str,
) -> str:
    """
    Основной консультант по ВЭД.

    Используется для вопросов пользователей,
    поставок, автозапчастей, Excel и PDF.
    """

    try:
        answer = await _request_completion(
            system_prompt=CONSULTANT_SYSTEM_PROMPT,
            user_input=user_input,
            max_completion_tokens=2500,
            temperature=0.2,
            reasoning_effort="low",
            request_name="консультант",
        )

    except Exception:
        logger.exception(
            "Ошибка запроса к LLM-консультанту"
        )
        return CONSULTANT_FALLBACK

    if not _is_valid_general_answer(answer):
        logger.warning(
            "LLM-консультант вернул некорректный ответ: %r",
            answer[:300],
        )
        return CONSULTANT_FALLBACK

    return answer


async def ask_document_llm(
    user_input: str,
) -> str:
    """
    Анализатор нормативных документов.

    Первая попытка:
    - 3000 выходных токенов;
    - низкий уровень рассуждения.

    Вторая попытка:
    - 4500 выходных токенов;
    - минимальный уровень рассуждения;
    - дополнительное требование дать краткий ответ.
    """

    clean_input = user_input.strip()

    if not clean_input:
        raise ValueError(
            "Передан пустой текст документа."
        )

    attempts = (
        {
            "max_completion_tokens": 3000,
            "reasoning_effort": "low",
        },
        {
            "max_completion_tokens": 4500,
            "reasoning_effort": "minimal",
        },
    )

    last_error: Exception | None = None

    for attempt_number, settings in enumerate(
        attempts,
        start=1,
    ):
        try:
            logger.info(
                "Запрос к анализатору документов: попытка=%s",
                attempt_number,
            )

            current_input = clean_input

            if attempt_number == 2:
                current_input = (
                    "Предыдущая генерация не завершилась.\n"
                    "Сделай максимально краткий, но полностью "
                    "законченный ответ. Не пропускай последний "
                    "блок с действиями специалиста.\n\n"
                    f"{clean_input}"
                )

            answer = await _request_completion(
                system_prompt=DOCUMENT_ANALYST_SYSTEM_PROMPT,
                user_input=current_input,
                max_completion_tokens=int(
                    settings["max_completion_tokens"]
                ),
                temperature=0.1,
                reasoning_effort=str(
                    settings["reasoning_effort"]
                ),
                request_name="анализатор документов",
            )

            if _is_valid_document_answer(answer):
                logger.info(
                    "Анализ документа успешно сформирован: "
                    "попытка=%s, символов=%s",
                    attempt_number,
                    len(answer),
                )
                return answer

            last_error = RuntimeError(
                "Модель вернула незавершённый "
                "или некорректный ответ."
            )

            logger.warning(
                "Ответ анализатора отклонён: "
                "попытка=%s, символов=%s, текст=%r",
                attempt_number,
                len(answer),
                answer[:400],
            )

        except Exception as error:
            last_error = error

            logger.warning(
                "Ошибка анализатора документов: "
                "попытка=%s, ошибка=%s: %s",
                attempt_number,
                type(error).__name__,
                error,
            )

        if attempt_number < len(attempts):
            await asyncio.sleep(2)

    raise RuntimeError(
        "Не удалось получить завершённый "
        "анализ нормативного документа."
    ) from last_error


async def _request_completion(
    system_prompt: str,
    user_input: str,
    max_completion_tokens: int,
    temperature: float,
    reasoning_effort: str,
    request_name: str,
) -> str:
    """Выполняет один запрос к OpenRouter."""

    clean_input = user_input.strip()

    if not clean_input:
        raise ValueError(
            "Нельзя отправить модели пустой запрос."
        )

    completion = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": clean_input,
            },
        ],
        temperature=temperature,
        max_completion_tokens=max_completion_tokens,
        extra_body={
            "reasoning": {
                "effort": reasoning_effort,
                "exclude": True,
            },
        },
    )

    logger.info(
        "Использована модель для режима «%s»: %s",
        request_name,
        completion.model,
    )

    if not completion.choices:
        raise RuntimeError(
            "Модель не вернула варианты ответа."
        )

    choice = completion.choices[0]

    finish_reason = getattr(
        choice,
        "finish_reason",
        None,
    )

    logger.info(
        "Причина завершения ответа модели "
        "для режима «%s»: %s",
        request_name,
        finish_reason,
    )

    _log_token_usage(
        completion=completion,
        request_name=request_name,
    )

    if finish_reason not in {
        None,
        "stop",
    }:
        raise RuntimeError(
            "Ответ модели завершён некорректно: "
            f"{finish_reason}"
        )

    answer = choice.message.content

    if not isinstance(answer, str):
        raise RuntimeError(
            "Модель вернула ответ неизвестного формата."
        )

    clean_answer = _clean_answer(
        answer
    )

    if not clean_answer:
        raise RuntimeError(
            "Модель вернула пустой ответ."
        )

    return clean_answer


def _log_token_usage(
    completion: object,
    request_name: str,
) -> None:
    """Записывает расход токенов без риска ошибки."""

    usage = getattr(
        completion,
        "usage",
        None,
    )

    if usage is None:
        return

    prompt_tokens = getattr(
        usage,
        "prompt_tokens",
        None,
    )

    completion_tokens = getattr(
        usage,
        "completion_tokens",
        None,
    )

    total_tokens = getattr(
        usage,
        "total_tokens",
        None,
    )

    reasoning_tokens = None

    completion_details = getattr(
        usage,
        "completion_tokens_details",
        None,
    )

    if completion_details is not None:
        reasoning_tokens = getattr(
            completion_details,
            "reasoning_tokens",
            None,
        )

    logger.info(
        "Токены режима «%s»: "
        "input=%s, output=%s, reasoning=%s, total=%s",
        request_name,
        prompt_tokens,
        completion_tokens,
        reasoning_tokens,
        total_tokens,
    )


def _is_valid_general_answer(
    answer: str,
) -> bool:
    """Проверяет обычный ответ консультанта."""

    normalized = answer.strip().lower()

    if len(normalized) < 40:
        return False

    return not any(
        marker in normalized
        for marker in BAD_RESPONSE_MARKERS
    )


def _is_valid_document_answer(
    answer: str,
) -> bool:
    """Проверяет полноту анализа документа."""

    normalized = answer.strip().lower()

    if len(normalized) < 250:
        return False

    if any(
        marker in normalized
        for marker in BAD_RESPONSE_MARKERS
    ):
        return False

    lines = [
        line.strip()
        for line in answer.splitlines()
        if line.strip()
    ]

    if len(lines) < 7:
        return False

    if len(lines[-1]) < 12:
        return False

    incomplete_last_lines = {
        "📄 что это за документ",
        "🔎 что установлено",
        "👥 кого может касаться",
        "📅 статус и сроки",
        "✅ что проверить специалисту по вэд",
    }

    if lines[-1].lower().strip(" :") in {
        line.strip(" :")
        for line in incomplete_last_lines
    }:
        return False

    required_groups = (
        (
            "что это за документ",
            "вид документа",
        ),
        (
            "что установлено",
            "подтверждённые факты",
            "подтвержденные факты",
        ),
        (
            "кого может касаться",
            "может касаться",
        ),
        (
            "статус и сроки",
            "дату вступления",
            "статус не удалось",
        ),
        (
            "что проверить",
            "проверить специалисту",
        ),
    )

    groups_found = sum(
        any(
            marker in normalized
            for marker in group
        )
        for group in required_groups
    )

    return groups_found >= 4


def _clean_answer(
    answer: str,
) -> str:
    """Очищает текст для отправки в Telegram."""

    clean_answer = (
        answer
        .replace("<br>", "\n")
        .replace("<br/>", "\n")
        .replace("<br />", "\n")
        .replace("**", "")
        .replace("###", "")
        .strip()
    )

    while "\n\n\n" in clean_answer:
        clean_answer = clean_answer.replace(
            "\n\n\n",
            "\n\n",
        )

    return clean_answer
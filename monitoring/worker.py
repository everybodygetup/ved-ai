import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import LinkPreviewOptions

from monitoring.document_reader import (
    AltaDocumentDetails,
    fetch_documents_details,
)

from config.settings import MONITOR_INTERVAL_SECONDS
from monitoring.alta import (
    AltaDocument,
    fetch_alta_documents,
)
from monitoring.storage import (
    count_documents,
    deactivate_subscriber,
    get_active_subscriber_chat_ids,
    initialize_monitor_database,
    save_new_documents,
)
from services.llm import ask_llm


logger = logging.getLogger(__name__)


_monitor_task: asyncio.Task[None] | None = None


async def start_monitor_worker(
    bot: Bot,
    **_: object,
) -> None:
    """Запускает фоновую проверку Alta."""

    global _monitor_task

    await asyncio.to_thread(
        initialize_monitor_database
    )

    if (
        _monitor_task is not None
        and not _monitor_task.done()
    ):
        return

    _monitor_task = asyncio.create_task(
        _monitor_loop(bot),
        name="alta-calendar-monitor",
    )

    logger.info(
        "Фоновый мониторинг Alta запущен. "
        "Интервал: %s секунд",
        MONITOR_INTERVAL_SECONDS,
    )


async def stop_monitor_worker(
    **_: object,
) -> None:
    """Корректно останавливает фоновую задачу."""

    global _monitor_task

    if _monitor_task is None:
        return

    _monitor_task.cancel()

    try:
        await _monitor_task
    except asyncio.CancelledError:
        pass

    _monitor_task = None

    logger.info(
        "Фоновый мониторинг Alta остановлен"
    )


async def _monitor_loop(
    bot: Bot,
) -> None:
    """Периодически проверяет Таможенный календарь."""

    while True:
        try:
            await _check_and_notify(bot)

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "Ошибка фонового мониторинга Alta"
            )

        await asyncio.sleep(
            MONITOR_INTERVAL_SECONDS
        )


async def _check_and_notify(
    bot: Bot,
) -> None:
    """Получает новые документы и рассылает уведомления."""

    await asyncio.to_thread(
        initialize_monitor_database
    )

    documents_before = await asyncio.to_thread(
        count_documents
    )

    documents = await fetch_alta_documents(
        limit=30
    )

    new_documents = await asyncio.to_thread(
        save_new_documents,
        documents,
    )

    # Совсем пустая база означает первое включение.
    # Текущие документы запоминаем, но не рассылаем.
    if documents_before == 0:
        logger.info(
            "Первичная инициализация мониторинга: "
            "сохранено документов=%s",
            len(documents),
        )
        return

    if not new_documents:
        logger.info(
            "Новых документов Alta не найдено"
        )
        return

    subscribers = await asyncio.to_thread(
        get_active_subscriber_chat_ids
    )

    if not subscribers:
        logger.info(
            "Найдено новых документов=%s, "
            "но активных подписчиков нет",
            len(new_documents),
        )
        return

    notification = await _build_notification(
        new_documents
    )

    message_parts = _split_message(
        notification
    )

    for chat_id in subscribers:
        try:
            for part in message_parts:
                await bot.send_message(
                    chat_id=chat_id,
                    text=part,
                    link_preview_options=LinkPreviewOptions(
                        is_disabled=True
                    ),
                )

            logger.info(
                "Уведомление отправлено: chat_id=%s, "
                "документов=%s",
                chat_id,
                len(new_documents),
            )

        except TelegramForbiddenError:
            logger.warning(
                "Бот заблокирован пользователем: chat_id=%s",
                chat_id,
            )

            await asyncio.to_thread(
                deactivate_subscriber,
                chat_id,
            )

        except Exception:
            logger.exception(
                "Не удалось отправить уведомление: "
                "chat_id=%s",
                chat_id,
            )

        await asyncio.sleep(0.1)


async def _build_notification(
    documents: list[AltaDocument],
) -> str:
    """
    Читает страницы документов,
    формирует доказательный LLM-дайджест.
    """

    documents_for_digest = documents[:10]

    details = await fetch_documents_details(
        documents_for_digest,
        max_documents=10,
    )

    prompt = _build_digest_prompt(
        details
    )

    try:
        digest = await ask_llm(prompt)

    except Exception:
        logger.exception(
            "Не удалось сформировать LLM-дайджест"
        )

        digest = (
            "Найдены новые документы в Таможенном "
            "календаре Alta.\n\n"
            "AI-анализ временно недоступен. "
            "Проверьте документы по ссылкам ниже."
        )

    if len(digest) > 2800:
        digest = (
            digest[:2797].rstrip()
            + "..."
        )

    lines = [
        "🆕 ДОКУМЕНТЫ, ДОБАВЛЕННЫЕ В БАЗУ ALTA",
        "",
        digest,
        "",
        "📚 Добавленные документы:",
    ]

    for number, detail in enumerate(
        details,
        start=1,
    ):
        lines.extend(
            [
                "",
                f"{number}. {detail.title}",
            ]
        )

        if detail.status != "Не указан":
            lines.append(
                f"Статус: {detail.status}"
            )

        if detail.effective_date != "Не указано":
            lines.append(
                "Вступление в силу: "
                f"{detail.effective_date}"
            )

        lines.append(detail.link)

    if len(documents) > len(details):
        lines.extend(
            [
                "",
                "Дополнительно найдено документов: "
                f"{len(documents) - len(details)}.",
            ]
        )

    calendar_link = (
        details[0].calendar_link
        if details
        else ""
    )

    if calendar_link:
        lines.extend(
            [
                "",
                "🗓 Таможенный календарь:",
                calendar_link,
            ]
        )

    lines.extend(
        [
            "",
            "Источник: Альта-Софт",
        ]
    )

    return "\n".join(lines)


def _build_digest_prompt(
    documents: list[AltaDocumentDetails],
) -> str:
    """Создаёт доказательный запрос для анализа документов."""

    lines = [        "",
        "Важно: документы являются новыми только для базы Alta.",
        "Это не означает, что они недавно приняты, изменены "
        "или вступили в силу.",
        "Не называй документ новым нормативным изменением, "
        "если это прямо не следует из его текста.",
        "Ты анализируешь новые документы по ВЭД.",
        "",
        "Используй только факты, приведённые ниже.",
        "Запрещено придумывать содержание документа, "
        "сроки, коды ТН ВЭД, ставки, последствия "
        "и категории товаров.",
        "",
        "Если конкретное изменение не видно из текста, "
        "напиши: «Недостаточно данных для вывода».",
        "",
        "Сформируй короткий дайджест для Telegram.",
        "",
        "По каждому документу укажи:",
        "1. Приоритет: 🔴 критично, 🟡 важно или 🟢 справочно.",
        "2. Что это за документ.",
        "3.Есть ли фактическое новое изменение законодательства. "
         "Если документ старый и лишь добавлен в базу Alta, "
         "прямо так и напиши."
        "4. Кого потенциально касается.",
        "5. Статус и вступление в силу.",
        "6. Что проверить специалисту по ВЭД.",
        "",
        "Красный приоритет используй только при наличии "
        "конкретного подтверждённого основания.",
        "",
        "Не используй таблицы, HTML и Markdown-заголовки.",
        "",
        "Документы:",
    ]

    for number, document in enumerate(
        documents,
        start=1,
    ):
        lines.extend(
            [
                "",
                f"ДОКУМЕНТ {number}",
                f"Название: {document.title}",
                f"Добавлен в базу: {document.published}",
                f"Статус: {document.status}",
                "Сведения о вступлении в силу: "
                f"{document.effective_date}",
                "Краткое описание из календаря: "
                f"{document.calendar_summary or 'не указано'}",
                "Фрагмент страницы документа:",
                (
                    document.text_excerpt
                    or "Текст извлечь не удалось."
                ),
            ]
        )

        if document.extraction_error:
            lines.append(
                "Ошибка извлечения: "
                f"{document.extraction_error}"
            )

    return "\n".join(lines)
def _split_message(
    text: str,
    chunk_size: int = 3900,
) -> list[str]:
    """Делит длинный текст на части для Telegram."""

    parts: list[str] = []
    remaining = text.strip()

    while len(remaining) > chunk_size:
        split_position = remaining.rfind(
            "\n",
            0,
            chunk_size,
        )

        if split_position <= 0:
            split_position = chunk_size

        part = remaining[:split_position].strip()
        remaining = remaining[split_position:].strip()

        if part:
            parts.append(part)

    if remaining:
        parts.append(remaining)

    return parts
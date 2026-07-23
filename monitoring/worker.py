import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import LinkPreviewOptions

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
    """Формирует LLM-дайджест и список документов."""

    documents_for_digest = documents[:10]

    prompt = _build_digest_prompt(
        documents_for_digest
    )

    try:
        digest = await ask_llm(prompt)

    except Exception:
        logger.exception(
            "Не удалось сформировать LLM-дайджест"
        )

        digest = (
            "Найдены новые документы в Таможенном "
            "календаре Alta. AI-анализ временно недоступен, "
            "поэтому проверьте названия и тексты документов "
            "по ссылкам ниже."
        )

    if len(digest) > 2500:
        digest = (
            digest[:2497].rstrip()
            + "..."
        )

    lines = [
        "🆕 ОБНОВЛЕНИЕ ПО ВЭД",
        "",
        digest,
        "",
        "📚 Новые документы:",
    ]

    for number, document in enumerate(
        documents_for_digest,
        start=1,
    ):
        lines.extend(
            [
                "",
                f"{number}. {document.title}",
                document.link,
            ]
        )

    if len(documents) > len(documents_for_digest):
        lines.extend(
            [
                "",
                "Дополнительно найдено документов: "
                f"{len(documents) - len(documents_for_digest)}.",
            ]
        )

    calendar_link = (
        documents_for_digest[0].calendar_link
        if documents_for_digest
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
    documents: list[AltaDocument],
) -> str:
    """Создаёт запрос для анализа новых документов."""

    lines = [
        "Сформируй краткий профессиональный дайджест "
        "новых документов по ВЭД.",
        "",
        "Используй только сведения ниже.",
        "Не придумывай содержание документов, даты "
        "вступления в силу, коды товаров и последствия.",
        "",
        "Для Telegram дай:",
        "1. Что опубликовано.",
        "2. Кому это потенциально важно.",
        "3. Что необходимо проверить вручную.",
        "4. Приоритет: важно или справочно.",
        "",
        "Если данных недостаточно, прямо так и напиши.",
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
                f"{number}. Название: {document.title}",
                f"Описание: {document.summary or 'не указано'}",
                f"Дата: {document.published}",
            ]
        )

    return "\n".join(lines)


def _split_message(
    text: str,
    chunk_size: int = 3900,
) -> list[str]:
    """Делит длинный текст на сообщения Telegram."""

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
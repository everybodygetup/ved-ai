import asyncio
import logging

from aiogram import F, Router
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from keyboards.main_menu import main_menu
from monitoring.alta import (
    AltaDocument,
    fetch_alta_documents,
)
from monitoring.storage import (
    count_documents,
    initialize_monitor_database,
    save_new_documents,
)


logger = logging.getLogger(__name__)

router = Router()

MAX_MESSAGES_PER_CHECK = 10


@router.message(F.text == "📰 Мониторинг ВЭД")
async def check_ved_updates(
    message: Message,
) -> None:
    """
    Проверяет раздел «Добавлен в базу»
    Таможенного календаря Alta.
    """

    await message.answer(
        "🗓 Проверяю Таможенный календарь Alta.\n"
        "Ищу документы, добавленные сегодня в базу..."
    )

    try:
        async with ChatActionSender.typing(
            bot=message.bot,
            chat_id=message.chat.id,
        ):
            # Создаём SQLite-базу при первом запуске.
            await asyncio.to_thread(
                initialize_monitor_database
            )

            saved_count = await asyncio.to_thread(
                count_documents
            )

            is_first_launch = saved_count == 0

            # Получаем документы из Таможенного календаря.
            documents = await fetch_alta_documents(
                limit=30
            )

            # Сохраняем и получаем только действительно новые.
            new_documents = await asyncio.to_thread(
                save_new_documents,
                documents,
            )

    except Exception:
        logger.exception(
            "Ошибка мониторинга Таможенного календаря Alta"
        )

        await message.answer(
            "⚠️ Не удалось получить данные "
            "Таможенного календаря Alta.\n\n"
            "Возможно, источник или интернет-соединение "
            "временно недоступны. Попробуйте позднее.",
            reply_markup=main_menu,
        )
        return

    # На выбранную дату раздел может быть пустым.
    if not documents:
        await message.answer(
            "✅ На сегодня в разделе «Добавлен в базу» "
            "документы не найдены.",
            reply_markup=main_menu,
        )
        return

    if is_first_launch:
        await message.answer(
            "✅ Мониторинг инициализирован.\n\n"
            "Текущие документы сохранены в локальной базе. "
            "При следующих проверках бот будет показывать "
            "только новые публикации."
        )

        # При первой проверке показываем несколько последних документов.
        documents_to_show = documents[:5]

        heading = (
            "📚 Документы, добавленные сегодня в базу:"
        )

    else:
        documents_to_show = new_documents[
            :MAX_MESSAGES_PER_CHECK
        ]

        heading = (
            "🆕 Новые документы, добавленные в базу:"
        )

    if not documents_to_show:
        await message.answer(
            "✅ Новых документов с момента "
            "предыдущей проверки нет.",
            reply_markup=main_menu,
        )
        return

    await message.answer(heading)

    for document in documents_to_show:
        await message.answer(
            _format_document(document)
        )

    if not is_first_launch:
        hidden_count = (
            len(new_documents)
            - len(documents_to_show)
        )

        if hidden_count > 0:
            await message.answer(
                f"Ещё новых документов: {hidden_count}."
            )

    await message.answer(
        "✅ Проверка Таможенного календаря завершена.",
        reply_markup=main_menu,
    )


def _format_document(
    document: AltaDocument,
) -> str:
    """Формирует карточку документа для Telegram."""

    summary = document.summary.strip()

    if len(summary) > 600:
        summary = (
            summary[:597].rstrip()
            + "..."
        )

    lines = [
        "📄 Добавлен в базу",
        "",
        document.title,
    ]

    if summary:
        lines.extend(
            [
                "",
                f"📝 {summary}",
            ]
        )

    if document.published:
        lines.extend(
            [
                "",
                f"📅 {document.published}",
            ]
        )

    lines.extend(
        [
            "",
            "🔗 Открыть документ:",
            document.link,
        ]
    )

    if document.calendar_link:
        lines.extend(
            [
                "",
                "🗓 Таможенный календарь за этот день:",
                document.calendar_link,
            ]
        )

    lines.extend(
        [
            "",
            "Источник: Альта-Софт",
        ]
    )

    return "\n".join(lines)
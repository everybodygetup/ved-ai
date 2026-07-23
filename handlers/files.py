import asyncio
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Message,
    ReplyKeyboardRemove,
)
from aiogram.utils.chat_action import ChatActionSender
from openai import APITimeoutError

from keyboards.file_actions import file_actions_keyboard
from keyboards.main_menu import main_menu
from services.file_parser import (
    FileParserError,
    build_file_llm_request,
    format_parse_result,
    parse_uploaded_file,
)
from services.llm import ask_llm
from states.file_state import FileState


logger = logging.getLogger(__name__)

router = Router()

ALLOWED_EXTENSIONS = {
    ".xlsx",
    ".pdf",
}

MAX_FILE_SIZE = 10 * 1024 * 1024


@router.message(F.text == "📄 Проверить файл")
async def start_file_check(
    message: Message,
    state: FSMContext,
) -> None:
    """Запускает сценарий проверки Excel или PDF."""

    await state.clear()
    await state.set_state(FileState.waiting_document)

    await message.answer(
        "📄 Отправьте файл в формате .xlsx или .pdf.\n\n"
        "Пока используйте тестовые или обезличенные данные.\n"
        "Файл сначала обрабатывается локально.\n\n"
        "Максимальный размер — 10 МБ.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(
    FileState.waiting_document,
    F.document,
)
async def process_uploaded_document(
    message: Message,
    state: FSMContext,
) -> None:
    """Скачивает файл, разбирает его и предлагает AI-анализ."""

    document = message.document

    if document is None:
        await message.answer(
            "Не удалось получить документ."
        )
        return

    filename = document.file_name or "uploaded_file"
    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        await message.answer(
            "Поддерживаются только файлы .xlsx и .pdf.\n"
            "Отправьте другой документ."
        )
        return

    if (
        document.file_size is not None
        and document.file_size > MAX_FILE_SIZE
    ):
        await message.answer(
            "Файл больше 10 МБ.\n"
            "Уменьшите его размер и отправьте повторно."
        )
        return

    await message.answer(
        "🔎 Получил файл. Читаю содержимое..."
    )

    try:
        async with ChatActionSender.typing(
            bot=message.bot,
            chat_id=message.chat.id,
        ):
            downloaded_file = await message.bot.download(
                document,
                timeout=60,
            )

            if downloaded_file is None:
                raise FileParserError(
                    "Telegram не вернул содержимое файла."
                )

            downloaded_file.seek(0)

            # Переменная result создаётся именно здесь.
            result = await asyncio.to_thread(
                parse_uploaded_file,
                filename,
                downloaded_file,
            )

            report = format_parse_result(result)

            # Используем result только после его создания.
            analysis_request = build_file_llm_request(
                result
            )

    except FileParserError as error:
        await message.answer(
            f"⚠️ {error}\n\n"
            "Исправьте файл или отправьте другой."
        )
        return

    except Exception:
        logger.exception(
            "Ошибка обработки файла %s",
            filename,
        )

        await message.answer(
            "⚠️ Не удалось обработать файл из-за "
            "внутренней ошибки.\n\n"
            "Попробуйте отправить другой документ."
        )
        return

    # Сохраняем подготовленный текст в памяти FSM.
    await state.update_data(
        file_analysis_request=analysis_request,
    )

    await state.set_state(
        FileState.waiting_confirmation
    )

    await _send_long_message(
        message=message,
        text=report,
    )

    await message.answer(
        "Файл обработан локально.\n\n"
        "Нажмите кнопку ниже, чтобы передать модели "
        "обезличенную текстовую сводку.",
        reply_markup=file_actions_keyboard,
    )


@router.message(FileState.waiting_document)
async def request_document_again(
    message: Message,
) -> None:
    """Обрабатывает текст или изображение вместо файла."""

    await message.answer(
        "Пришлите файл именно как документ "
        "в формате .xlsx или .pdf."
    )


@router.callback_query(
    FileState.waiting_confirmation,
    F.data == "file_analyze",
)
async def analyze_file(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Отправляет обезличенную сводку в LLM."""

    await callback.answer()

    message = callback.message

    if message is None:
        await state.clear()
        return

    data = await state.get_data()

    analysis_request = data.get(
        "file_analysis_request"
    )

    if not analysis_request:
        await state.clear()

        await message.answer(
            "Не удалось найти результаты обработки.\n"
            "Загрузите файл повторно.",
            reply_markup=main_menu,
        )
        return

    await message.edit_reply_markup(
        reply_markup=None
    )

    await message.answer(
        "🔎 Анализирую найденные позиции..."
    )

    try:
        async with ChatActionSender.typing(
            bot=callback.bot,
            chat_id=message.chat.id,
        ):
            analysis = await ask_llm(
                analysis_request
            )

    except APITimeoutError:
        analysis = (
            "⏳ Бесплатная модель отвечает слишком долго.\n\n"
            "Попробуйте повторить анализ позднее."
        )

    except Exception:
        logger.exception(
            "Ошибка AI-анализа загруженного файла"
        )

        analysis = (
            "⚠️ AI-анализ сейчас недоступен.\n\n"
            "Локальная проверка файла выполнена успешно."
        )

    await state.clear()

    await _send_long_message(
        message=message,
        text=analysis,
    )

    await message.answer(
        "✅ Анализ завершён.",
        reply_markup=main_menu,
    )


@router.callback_query(
    FileState.waiting_confirmation,
    F.data == "file_cancel",
)
async def cancel_file_analysis(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Отменяет передачу сводки в LLM."""

    await callback.answer(
        "Анализ отменён"
    )

    await state.clear()

    message = callback.message

    if message is None:
        return

    await message.edit_reply_markup(
        reply_markup=None
    )

    await message.answer(
        "AI-анализ отменён.\n"
        "Исходный файл модели не передавался.",
        reply_markup=main_menu,
    )


@router.message(FileState.waiting_confirmation)
async def waiting_for_file_action(
    message: Message,
) -> None:
    """Напоминает нажать кнопку после обработки файла."""

    await message.answer(
        "Выберите действие кнопкой под предыдущим сообщением:\n\n"
        "🤖 Провести AI-анализ\n"
        "или\n"
        "❌ Отменить"
    )


async def _send_long_message(
    message: Message,
    text: str,
    chunk_size: int = 3900,
) -> None:
    """Делит длинный текст на сообщения Telegram."""

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
            await message.answer(part)

    if remaining:
        await message.answer(remaining)
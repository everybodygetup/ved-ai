import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.utils.chat_action import ChatActionSender
from openai import APITimeoutError

from data.messages import (
    ASK_COMPANY,
    ASK_COUNTRY,
    ASK_PRODUCT,
)
from keyboards.company_type import company_keyboard
from keyboards.main_menu import main_menu
from services.llm import ask_llm
from services.summary import build_llm_request, build_summary
from states.import_state import ImportState


router = Router()


COMPANY_TYPES = {
    "🏢 ООО": "ООО",
    "👨‍💼 ИП": "ИП",
    "👤 Физическое лицо": "Физическое лицо",
}


@router.message(F.text == "🚗 Автозапчасти")
async def autoparts_handler(
    message: Message,
    state: FSMContext,
) -> None:
    """Запускает анкету по импорту автозапчастей."""

    # Удаляем данные предыдущей незавершённой анкеты.
    await state.clear()

    # Бот ожидает страну отправления.
    await state.set_state(ImportState.country)

    await message.answer(
        ASK_COUNTRY,
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(ImportState.country)
async def process_country(
    message: Message,
    state: FSMContext,
) -> None:
    """Сохраняет страну и запрашивает тип получателя."""

    country = (message.text or "").strip()

    if len(country) < 2:
        await message.answer(
            "Укажите страну текстом, например: Китай."
        )
        return

    await state.update_data(country=country)
    await state.set_state(ImportState.company_type)

    await message.answer(
        ASK_COMPANY,
        reply_markup=company_keyboard,
    )


@router.message(ImportState.company_type)
async def process_company(
    message: Message,
    state: FSMContext,
) -> None:
    """Сохраняет тип получателя и запрашивает товар."""

    company_type = COMPANY_TYPES.get(
        (message.text or "").strip()
    )

    if company_type is None:
        await message.answer(
            "Пожалуйста, выберите тип получателя кнопкой.",
            reply_markup=company_keyboard,
        )
        return

    await state.update_data(company_type=company_type)
    await state.set_state(ImportState.product)

    await message.answer(
        ASK_PRODUCT,
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(ImportState.product)
async def process_product(
    message: Message,
    state: FSMContext,
) -> None:
    """Сохраняет товар и запускает предварительный LLM-анализ."""

    product = (message.text or "").strip()

    if len(product) < 3:
        await message.answer(
            "Опишите товар подробнее: укажите название, "
            "назначение, бренд, модель или артикул."
        )
        return

    await state.update_data(product=product)
    data = await state.get_data()
    await state.clear()

    await message.answer(build_summary(data))
    await message.answer("🔎 Выполняю предварительный анализ...")

    try:
        async with ChatActionSender.typing(
            bot=message.bot,
            chat_id=message.chat.id,
        ):
            analysis = await ask_llm(
                build_llm_request(data)
            )

        logging.info(
            "Ответ LLM получен, длина: %s символов",
            len(analysis),
        )

    except APITimeoutError:
        analysis = (
            "⏳ Бесплатная модель сейчас отвечает слишком долго.\n\n"
            "Попробуйте повторить запрос через несколько минут."
        )

    except Exception:
        logging.exception("Ошибка при обращении к LLM")

        analysis = (
            "⚠️ Сейчас AI-анализ временно недоступен.\n\n"
            "Информация по поставке собрана. "
            "Попробуйте повторить запрос позже."
        )

    # Эта строка обязательно находится после всего блока try/except.
    await message.answer(
        analysis,
        reply_markup=main_menu,
    )
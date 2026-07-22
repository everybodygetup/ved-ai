from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from states.import_state import ImportState

from data.messages import (
    ASK_COUNTRY,
    ASK_COMPANY,
    ASK_PRODUCT,
    SUMMARY,
)

router = Router()


@router.message(F.text == "🚗 Автозапчасти")
async def autoparts_handler(message: Message, state: FSMContext):

    await state.set_state(ImportState.country)

    await message.answer(ASK_COUNTRY)

@router.message(ImportState.country)
async def process_country(message: Message, state: FSMContext):

    await state.update_data(country=message.text)

    await state.set_state(ImportState.company_type)

    await message.answer(ASK_COMPANY)

@router.message(ImportState.company_type)
async def process_company(message: Message, state: FSMContext):

    await state.update_data(company_type=message.text)

    await state.set_state(ImportState.product)

    await message.answer(ASK_PRODUCT)

@router.message(ImportState.product)
async def process_product(message: Message, state: FSMContext):

    await state.update_data(product=message.text)

    data = await state.get_data()

    await message.answer(
    f"""{SUMMARY}

🌍 Страна: {data["country"]}

🏢 Получатель: {data["company_type"]}

📦 Товар: {data["product"]}
"""
)


async def autoparts_handler(message: Message):
    await message.answer(
        "🚗 Импорт автозапчастей\n\n"
        "Давайте разберем вашу поставку.\n\n"
        "🌍 Из какой страны планируется импорт?"
    )
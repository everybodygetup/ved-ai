from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from keyboards.main_menu import main_menu

router = Router()


@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
    "👋 Добро пожаловать!\n\n"
    "Я AI-помощник по ВЭД.\n\n"
    "Выберите интересующий раздел.",
    reply_markup=main_menu,

    )
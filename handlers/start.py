from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()


@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "👋 Привет!\n\n"
        "Я AI-помощник по ВЭД.\n\n"
        "Пока я только учусь, но скоро смогу помогать с:\n"
        "• 🚗 Автозапчастями\n"
        "• 💻 Электроникой\n"
        "• 📦 Импортом и экспортом\n\n"
        "Добро пожаловать!"
    )
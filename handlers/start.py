from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from keyboards.main_menu import main_menu
from data.messages import WELCOME


router = Router()


@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
    WELCOME,
    reply_markup=main_menu,
)

  
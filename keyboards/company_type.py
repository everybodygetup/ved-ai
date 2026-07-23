from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

company_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🏢 ООО")],
        [KeyboardButton(text="👨‍💼 ИП")],
        [KeyboardButton(text="👤 Физическое лицо")],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)
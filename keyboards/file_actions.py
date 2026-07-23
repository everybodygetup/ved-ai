from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


file_actions_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🤖 Провести AI-анализ",
                callback_data="file_analyze",
            ),
        ],
        [
            InlineKeyboardButton(
                text="❌ Отменить",
                callback_data="file_cancel",
            ),
        ],
    ]
)
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup



main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🚗 Автозапчасти"),
            KeyboardButton(text="💻 Электроника"),
        ],
        [
            KeyboardButton(text="📦 Другие товары"),
            KeyboardButton(text="💰 Рассчитать платежи"),
            KeyboardButton(text="📄 Проверить документы")
        ],
        [
            KeyboardButton(text="📄 Проверить файл"),
        ],
        [
            KeyboardButton(text="📞 Консультация"),
        ],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие",
)

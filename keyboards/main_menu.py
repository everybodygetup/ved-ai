from aiogram.types import KeyboardButton, ReplyKeyboardMarkup



main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(
                text="🚗 Автозапчасти"
            ),
            KeyboardButton(
                text="💻 Электроника"
            ),
        ],
        [
            KeyboardButton(
                text="📄 Проверить файл"
            ),
        ],
        [
            KeyboardButton(
                text="📰 Мониторинг ВЭД"
            ),
        ],
        [
            KeyboardButton(
                text="📞 Консультация"
            ),
        ],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие",
)
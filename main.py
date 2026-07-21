import asyncio

from aiogram import Bot, Dispatcher

from config.settings import BOT_TOKEN
from handlers.start import router


async def main():
    bot = Bot(BOT_TOKEN)

    dp = Dispatcher()

    dp.include_router(router)

    print("Бот запущен")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
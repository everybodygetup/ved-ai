import asyncio

from aiogram import Bot, Dispatcher

from config.settings import BOT_TOKEN
from handlers.start import router
from handlers.autoparts import router as autoparts_router

async def main():
    bot = Bot(BOT_TOKEN)

    dp = Dispatcher()

    dp.include_router(router)

    dp.include_router(autoparts_router)
    
    print("Бот запущен")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
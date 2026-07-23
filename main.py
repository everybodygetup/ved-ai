import asyncio
import logging
from handlers.subscriptions import (
    router as subscriptions_router,
)
from monitoring.worker import (
    start_monitor_worker,
    stop_monitor_worker,
)
from aiogram import Bot, Dispatcher

from config.settings import BOT_TOKEN
from handlers.autoparts import router as autoparts_router
from handlers.start import router as start_router
from handlers.files import router as files_router
from handlers.monitor import router as monitor_router


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    bot = Bot(token=BOT_TOKEN)
    dispatcher = Dispatcher()

    dispatcher.include_routers(
    start_router,
    autoparts_router,
    files_router,
    monitor_router,
    subscriptions_router,
)
    dispatcher.startup.register(
    start_monitor_worker
)

    dispatcher.shutdown.register(
    stop_monitor_worker
)
    logging.info("Бот запущен")

    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
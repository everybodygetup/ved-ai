import asyncio

from aiogram import F, Router
from aiogram.types import Message

from keyboards.main_menu import main_menu
from monitoring.storage import (
    initialize_monitor_database,
    subscribe_chat,
    unsubscribe_chat,
)


router = Router()


@router.message(F.text == "🔔 Подписаться")
async def subscribe_to_monitoring(
    message: Message,
) -> None:
    """Подписывает чат на автоматические обновления."""

    user = message.from_user

    await asyncio.to_thread(
        initialize_monitor_database
    )

    activated = await asyncio.to_thread(
        subscribe_chat,
        message.chat.id,
        user.id if user else None,
        user.username if user and user.username else "",
        user.full_name if user else "",
    )

    if activated:
        text = (
            "🔔 Подписка включена.\n\n"
            "Теперь бот будет автоматически присылать "
            "новые документы из раздела «Добавлен в базу» "
            "Таможенного календаря Alta."
        )
    else:
        text = (
            "✅ Подписка уже была активна.\n\n"
            "Автоматические уведомления включены."
        )

    await message.answer(
        text,
        reply_markup=main_menu,
    )


@router.message(F.text == "🔕 Отписаться")
async def unsubscribe_from_monitoring(
    message: Message,
) -> None:
    """Отключает автоматические уведомления."""

    await asyncio.to_thread(
        initialize_monitor_database
    )

    deactivated = await asyncio.to_thread(
        unsubscribe_chat,
        message.chat.id,
    )

    if deactivated:
        text = (
            "🔕 Автоматические уведомления отключены.\n\n"
            "Ручная проверка через кнопку "
            "«Мониторинг ВЭД» продолжит работать."
        )
    else:
        text = (
            "Автоматическая подписка уже отключена."
        )

    await message.answer(
        text,
        reply_markup=main_menu,
    )
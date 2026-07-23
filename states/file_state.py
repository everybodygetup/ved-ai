from aiogram.fsm.state import State, StatesGroup


class FileState(StatesGroup):
    waiting_document = State()
    waiting_confirmation = State()
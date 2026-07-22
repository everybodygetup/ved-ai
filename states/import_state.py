from aiogram.fsm.state import State, StatesGroup


class ImportState(StatesGroup):
    country = State()
    company_type = State()
    product = State()
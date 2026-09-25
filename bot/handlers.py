"""Диалог Telegram-бота до формирования чек-листа."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from backend.messages import AFTER_CHECKLIST, DIMENSION_PROMPT, START
from backend.models import Session, SessionState
from bot import api_client
from bot.api_client import ApiClientError

router = Router()


class Dialog(StatesGroup):
    awaiting_dimensions = State()
    awaiting_file = State()
    processing = State()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(START)


@router.message(Command("new"))
async def new(message: Message, state: FSMContext) -> None:
    await state.clear()
    session = Session(user_id=message.from_user.id, state=SessionState.AWAITING_DIMENSIONS)
    await state.update_data(session=session.model_dump(mode="json"))
    await state.set_state(Dialog.awaiting_dimensions)
    await message.answer(DIMENSION_PROMPT)


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Команды: /start — приветствие, /new — новый диалог, "
        "/cancel — отмена, /help — справка.\n\n"
        "Формат: габарит_длина=100, габарит_ширина=50, "
        "отверстие_1_диаметр=10. Можно также указать высоту, "
        "отверстие_1_глубина и фаска_1. Значения — в мм, см или дюймах.\n"
        "На этом этапе бот формирует чек-лист; STL ещё не анализируется."
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    await state.clear()
    await message.answer(
        "Диалог отменён. Начать заново: /new."
        if current else "Активного диалога нет. Начать: /new."
    )


@router.message(Dialog.awaiting_dimensions, F.text)
async def receive_dimensions(message: Message, state: FSMContext) -> None:
    try:
        result = await api_client.parse_dimensions(message.from_user.id, message.text or "")
    except ApiClientError as error:
        await message.answer(f"{error.code}: {error.message}\nИсправь ввод или отправь /cancel.")
        return
    data = await state.get_data()
    session = Session.model_validate(data["session"])
    session.dimensions = result.dimensions
    session.state = SessionState.AWAITING_FILE
    await state.update_data(session=session.model_dump(mode="json"))
    await state.set_state(Dialog.awaiting_file)
    checklist = "\n".join(f"{number}. {item}" for number, item in enumerate(result.checklist, 1))
    await message.answer(f"Чек-лист для построения:\n{checklist}\n\n{AFTER_CHECKLIST}")


@router.message(Dialog.awaiting_dimensions, F.document)
async def file_before_dimensions(message: Message) -> None:
    await message.answer("Сначала введи размеры текстом. Загрузка STL появится на следующем этапе.")


@router.message(Dialog.awaiting_file, F.document)
async def file_placeholder(message: Message) -> None:
    await message.answer("Чек-лист готов, но анализ STL появится на следующем этапе. Файл не скачивается.")


@router.message(Dialog.awaiting_file, F.text)
async def after_checklist(message: Message) -> None:
    await message.answer("Чек-лист уже готов. Другие размеры: /new; отмена: /cancel.")


@router.message()
async def fallback(message: Message) -> None:
    await message.answer("Активного диалога нет. Начать: /new; помощь: /help.")

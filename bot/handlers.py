"""Диалог Telegram-бота: размеры, чек-лист и проверка STL."""

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from backend.config import get_settings
from backend.messages import AFTER_CHECKLIST, DIMENSION_PROMPT, PROCESSING, START
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
        "габарит_диаметр, отверстие_1_глубина и фаска_1.\n"
        "После чек-листа загрузи STL до 10 МБ. Бот сравнит габариты, "
        "простые осевые отверстия и фаски 45° с заданными размерами."
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
    await message.answer("Сначала введи размеры текстом. Начать заново: /new.")


@router.message(Dialog.awaiting_file, F.document)
async def receive_file(message: Message, state: FSMContext) -> None:
    document = message.document
    if not document.file_name or not document.file_name.lower().endswith(".stl"):
        await message.answer("INVALID_FILE: Загрузи файл с расширением .stl.")
        return
    if document.file_size is not None and document.file_size > get_settings().max_file_size_bytes:
        await message.answer("FILE_TOO_LARGE: STL больше 10 МБ. Загрузи файл меньшего размера.")
        return
    data = await state.get_data()
    session = Session.model_validate(data["session"])
    session.state = SessionState.PROCESSING
    await state.update_data(session=session.model_dump(mode="json"))
    await state.set_state(Dialog.processing)
    await message.answer(PROCESSING)
    try:
        downloaded = await message.bot.download(document)
        if downloaded is None:
            raise ApiClientError("INVALID_FILE", "Не удалось скачать файл из Telegram.")
        content = downloaded.getvalue()
        if len(content) > get_settings().max_file_size_bytes:
            raise ApiClientError("FILE_TOO_LARGE", "STL больше 10 МБ.")
        if await state.get_state() != Dialog.processing.state:
            return
        result = await api_client.validate_model(
            message.from_user.id, document.file_name, content, session.dimensions
        )
    except ApiClientError as error:
        if await state.get_state() == Dialog.processing.state:
            await message.answer(f"{error.code}: {error.message}\nИсправь файл и загрузи его снова.")
    except Exception:
        logging.exception("Telegram STL validation failed")
        if await state.get_state() == Dialog.processing.state:
            await message.answer("INTERNAL_ERROR: Не удалось проверить STL. Попробуй снова.")
    else:
        if await state.get_state() == Dialog.processing.state:
            await message.answer(result.report.summary)
    finally:
        if await state.get_state() == Dialog.processing.state:
            session.state = SessionState.AWAITING_FILE
            await state.update_data(session=session.model_dump(mode="json"))
            await state.set_state(Dialog.awaiting_file)


@router.message(Dialog.awaiting_file, F.text)
async def after_checklist(message: Message) -> None:
    await message.answer("Загрузи STL-файл для проверки. Другие размеры: /new; отмена: /cancel.")


@router.message(Dialog.processing)
async def while_processing(message: Message) -> None:
    await message.answer("Проверка файла ещё идёт. Подожди результат.")


@router.message()
async def fallback(message: Message) -> None:
    await message.answer("Активного диалога нет. Начать: /new; помощь: /help.")

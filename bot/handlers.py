"""Диалог Telegram-бота: размеры, чек-лист и проверка STL."""

import logging
from pathlib import Path
import tempfile

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from backend.config import ROOT, get_settings
from backend import messages
from backend.models import Session, SessionState
from bot import api_client
from bot.api_client import ApiClientError

router = Router()
BOT_TEMP_DIR = ROOT / ".runtime" / "bot-uploads"
BOT_TEMP_DIR.mkdir(parents=True, exist_ok=True)


class Dialog(StatesGroup):
    awaiting_dimensions = State()
    awaiting_file = State()
    processing = State()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(messages.START)


@router.message(Command("new"))
async def new(message: Message, state: FSMContext) -> None:
    await state.clear()
    session = Session(user_id=message.from_user.id, state=SessionState.AWAITING_DIMENSIONS)
    await state.update_data(session=session.model_dump(mode="json"))
    await state.set_state(Dialog.awaiting_dimensions)
    await message.answer(messages.DIMENSION_PROMPT)


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(messages.HELP)


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    await state.clear()
    await message.answer(
        messages.CANCELLED if current else messages.NOTHING_TO_CANCEL
    )


@router.message(Dialog.awaiting_dimensions, F.text)
async def receive_dimensions(message: Message, state: FSMContext) -> None:
    try:
        result = await api_client.parse_dimensions(message.from_user.id, message.text or "")
    except ApiClientError as error:
        await message.answer(messages.input_error(error.code, error.message))
        return
    data = await state.get_data()
    session = Session.model_validate(data["session"])
    session.dimensions = result.dimensions
    session.state = SessionState.AWAITING_FILE
    await state.update_data(session=session.model_dump(mode="json"))
    await state.set_state(Dialog.awaiting_file)
    await message.answer(messages.checklist_message(result.checklist))


@router.message(Dialog.awaiting_dimensions, F.document)
async def file_before_dimensions(message: Message) -> None:
    await message.answer(messages.FILE_BEFORE_DIMENSIONS)


@router.message(Dialog.awaiting_file, F.document)
async def receive_file(message: Message, state: FSMContext) -> None:
    document = message.document
    if not document.file_name or not document.file_name.lower().endswith(".stl"):
        await message.answer(messages.file_error("INVALID_FILE", "Ожидается файл с расширением .stl."))
        return
    if document.file_size is not None and document.file_size > get_settings().max_file_size_bytes:
        await message.answer(messages.file_error("FILE_TOO_LARGE", "STL больше 10 МБ."))
        return
    data = await state.get_data()
    session = Session.model_validate(data["session"])
    session.state = SessionState.PROCESSING
    await state.update_data(session=session.model_dump(mode="json"))
    await state.set_state(Dialog.processing)
    await message.answer(messages.PROCESSING)
    path: Path | None = None
    completed = False
    try:
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".stl", dir=BOT_TEMP_DIR, delete=False) as temporary:
            path = Path(temporary.name)
        await message.bot.download(document, destination=path)
        if path.stat().st_size == 0:
            raise ApiClientError("INVALID_FILE", "Не удалось скачать STL из Telegram.")
        if path.stat().st_size > get_settings().max_file_size_bytes:
            raise ApiClientError("FILE_TOO_LARGE", "STL больше 10 МБ.")
        if await state.get_state() != Dialog.processing.state:
            return
        result = await api_client.validate_model(
            message.from_user.id, document.file_name, path, session.dimensions
        )
        path.unlink(missing_ok=True)
        path = None
        if await state.get_state() == Dialog.processing.state:
            await message.answer(result.report.telegram_text or result.report.summary)
            completed = not result.report.mismatches
    except ApiClientError as error:
        if await state.get_state() == Dialog.processing.state:
            await message.answer(messages.file_error(error.code, error.message))
    except Exception:
        logging.exception("Telegram STL analysis failed")
        if await state.get_state() == Dialog.processing.state:
            await message.answer(messages.file_error("INTERNAL_ERROR", "Не удалось проверить STL."))
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
        if await state.get_state() == Dialog.processing.state:
            if completed:
                await state.clear()
            else:
                session.state = SessionState.AWAITING_FILE
                await state.update_data(session=session.model_dump(mode="json"))
                await state.set_state(Dialog.awaiting_file)


@router.message(Dialog.awaiting_file, F.text)
async def after_checklist(message: Message) -> None:
    await message.answer(messages.AWAITING_FILE)


@router.message(Dialog.awaiting_file)
async def unsupported_file_message(message: Message) -> None:
    await message.answer(messages.file_error("INVALID_FILE", "Загрузи STL как документ."))


@router.message(Dialog.awaiting_dimensions)
async def unsupported_dimensions_message(message: Message) -> None:
    await message.answer(messages.DIMENSION_PROMPT)


@router.message(Dialog.processing)
async def while_processing(message: Message) -> None:
    await message.answer(messages.ALREADY_PROCESSING)


@router.message()
async def fallback(message: Message) -> None:
    await message.answer(messages.NO_SESSION)

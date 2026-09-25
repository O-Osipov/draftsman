"""Команды, ввод размеров и состояния диалога."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot.dimensions import DimensionError, format_checklist, parse_dimensions


router = Router()

INPUT_EXAMPLE = (
    "габарит_длина=100, габарит_ширина=50, "
    "отверстие_1_диаметр=10"
)


class Dialog(StatesGroup):
    awaiting_dimensions = State()
    awaiting_file = State()
    processing = State()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Привет! Я «Чертёжник» — бот для самопроверки 3D-моделей.\n\n"
        "Сейчас я помогу составить чек-лист по контрольным размерам. "
        "Проверка STL появится на следующем этапе.\n\n"
        "Начать новый диалог: /new\nПомощь: /help"
    )


@router.message(Command("new"))
async def new(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Dialog.awaiting_dimensions)
    await message.answer(
        "Введи контрольные размеры с чертежа в формате название=значение.\n"
        f"Пример: {INPUT_EXAMPLE}\n\n"
        "Можно писать по одному размеру в строке или разделять их запятыми. "
        "По умолчанию единица — мм; также доступны см и дюйм. "
        "Для дробных чисел используй точку.\n"
        "Отменить ввод: /cancel"
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/start — приветствие и сброс диалога\n"
        "/new — начать ввод размеров заново\n"
        "/cancel — отменить текущий диалог\n"
        "/help — показать эту справку\n\n"
        "Названия размеров: габарит_длина, габарит_ширина, "
        "габарит_высота, отверстие_1_диаметр, "
        "отверстие_1_глубина, фаска_1. Номер отверстия или фаски "
        "может быть другим положительным целым числом.\n"
        f"Пример ввода: {INPUT_EXAMPLE}\n\n"
        "Бот пока составляет чек-лист; анализ STL ещё не готов."
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    await state.clear()
    if current_state is None:
        await message.answer("Активного диалога нет. Чтобы начать, отправь /new.")
    else:
        await message.answer("Диалог отменён. Чтобы начать заново, отправь /new.")


@router.message(Dialog.awaiting_dimensions, F.text)
async def receive_dimensions(message: Message, state: FSMContext) -> None:
    try:
        dimensions = parse_dimensions(message.text or "")
    except DimensionError as error:
        await message.answer(f"Не удалось сохранить размеры. {error}\nПопробуй ещё раз или отправь /cancel.")
        return

    await state.update_data(dimensions=[dimension.to_dict() for dimension in dimensions])
    await state.set_state(Dialog.awaiting_file)
    await message.answer(
        f"{format_checklist(dimensions)}\n\n"
        "Размеры сохранены в текущем диалоге. Проверка STL появится "
        "на следующем этапе. Чтобы изменить размеры, отправь /new."
    )


@router.message(Dialog.awaiting_dimensions, F.document)
async def file_before_dimensions(message: Message) -> None:
    await message.answer("Сначала введи размеры текстом. Загрузка STL появится на следующем этапе.")


@router.message(Dialog.awaiting_file, F.document)
async def file_placeholder(message: Message) -> None:
    await message.answer(
        "Чек-лист уже готов. Анализ STL появится на следующем этапе. "
        "Пока файл не скачивается и не проверяется."
    )


@router.message(Dialog.awaiting_file, F.text)
async def after_checklist(message: Message) -> None:
    await message.answer(
        "Чек-лист уже готов. Чтобы ввести другие размеры, отправь /new. "
        "Чтобы закончить диалог — /cancel."
    )


@router.message()
async def fallback(message: Message) -> None:
    await message.answer("Чтобы начать ввод размеров, отправь /new. Помощь: /help.")

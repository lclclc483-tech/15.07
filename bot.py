# -*- coding: utf-8 -*-

import asyncio
import os
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, FSInputFile, ReplyKeyboardRemove, \
    InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

import db
from config import BOT_TOKEN, ADMIN_ID
from categories import CATEGORIES

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler("bot_production.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("bot_logger")

router = Router()

# Английский контекст (English context):
# Path — путь (к файлу)
# Join — объединить / соединить части пути в одну строку
# Slice — срез (вырезаем часть списка от start до end)
# Page — страница

TYPE_LABEL = {"vacancy": "вакансия", "resume": "резюме"}
ACTION_LABEL = {"view": "Просмотр", "create": "Создание", "sub": "Подписка"}

# Главные текстовые кнопки
BTN_VIEW_VAC = "🔍 Смотреть вакансии"
BTN_CREATE_VAC = "➕ Создать вакансию"
BTN_VIEW_RES = "🔍 Смотреть резюме"
BTN_CREATE_RES = "➕ Создать резюме"
BTN_MY_VAC = "📋 Мои вакансии"
BTN_MY_RES = "📋 Мое резюме"
BTN_CITY = "🏙 Изменить город"
BTN_ALL_CITIES = "🌍 Все города"
BTN_ENTER_OTHER_CITY = "🏙 Ввести другой город"
BTN_BACK = "⬅️ Назад"
BTN_BACK_TO_SPECS = "⬅️ Назад к специальностям"
BTN_NOTIFICATIONS = "🔔 Уведомления"


class Form(StatesGroup):
    waiting_city = State()
    waiting_city_post = State()
    waiting_post_text = State()
    waiting_broadcast_content = State()
    waiting_broadcast_confirm = State()


# Middleware проверки блокировки
class BlockCheckMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user and db.is_blocked(user.id) and user.id != ADMIN_ID:
            if isinstance(event, CallbackQuery):
                await event.answer("🚫 Вы заблокированы.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("🚫 Вы заблокированы.")
            return
        return await handler(event, data)


# --- КЛАВИАТУРЫ ---

def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=BTN_VIEW_VAC), KeyboardButton(text=BTN_CREATE_VAC)],
        [KeyboardButton(text=BTN_VIEW_RES), KeyboardButton(text=BTN_CREATE_RES)],
        [KeyboardButton(text=BTN_MY_VAC), KeyboardButton(text=BTN_MY_RES)],
        [KeyboardButton(text=BTN_CITY), KeyboardButton(text=BTN_NOTIFICATIONS)]
    ], resize_keyboard=True)


def city_selection_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=BTN_ALL_CITIES)],
        [KeyboardButton(text=BTN_ENTER_OTHER_CITY)],
        [KeyboardButton(text=BTN_BACK)]
    ], resize_keyboard=True)


def post_city_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=BTN_ALL_CITIES)],
        [KeyboardButton(text=BTN_BACK)]
    ], resize_keyboard=True)


def text_input_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=BTN_BACK_TO_SPECS)]
    ], resize_keyboard=True)


def sub_type_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="💼 Вакансии", callback_data="substart|vacancy")
    kb.button(text="👤 Резюме", callback_data="substart|resume")
    kb.button(text="🏠 В меню", callback_data="menu")
    kb.adjust(2, 1)
    return kb.as_markup()


def categories_kb(action: str, ptype: str):
    kb = InlineKeyboardBuilder()
    for i, cat in enumerate(CATEGORIES):
        kb.button(text=f"{cat['emoji']} {cat['name']}", callback_data=f"cat|{action}|{ptype}|{i}")
    if action == "sub":
        kb.button(text="⬅️ Назад к типу подписок", callback_data="sub_menu_back")
    else:
        kb.button(text="⬅️ Назад в меню", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def specialties_sub_kb(ptype: str, cat_idx: int, current_subs: list, page: int = 0):
    kb = InlineKeyboardBuilder()
    cat = CATEGORIES[cat_idx]
    category_title = f"{cat['emoji']} {cat['name']}"
    specs = cat["specs"]

    per_page = 10
    start = page * per_page
    end = start + per_page
    current_specs = specs[start:end]

    for j, spec in enumerate(current_specs):
        actual_idx = start + j
        is_subbed = (category_title, spec) in current_subs
        status_emoji = "✅" if is_subbed else "❌"
        kb.button(
            text=f"{status_emoji} {spec}",
            callback_data=f"subtoggle|{ptype}|{cat_idx}|{actual_idx}|{page}"
        )
    kb.adjust(1)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"specpage|sub|{ptype}|{cat_idx}|{page - 1}"))
    if end < len(specs):
        nav_buttons.append(
            InlineKeyboardButton(text="➡️ След.", callback_data=f"specpage|sub|{ptype}|{cat_idx}|{page + 1}"))

    if nav_buttons:
        kb.row(*nav_buttons)

    kb.row(InlineKeyboardButton(text="✅ Сохранить", callback_data="menu"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data=f"actstart|sub|{ptype}"))
    return kb.as_markup()


def specialties_kb(action: str, ptype: str, cat_idx: int, page: int = 0):
    kb = InlineKeyboardBuilder()
    specs = CATEGORIES[cat_idx]["specs"]

    per_page = 10
    start = page * per_page
    end = start + per_page
    current_specs = specs[start:end]

    for j, spec in enumerate(current_specs):
        actual_idx = start + j
        kb.button(text=spec, callback_data=f"spec|{action}|{ptype}|{cat_idx}|{actual_idx}")
    kb.adjust(1)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"specpage|{action}|{ptype}|{cat_idx}|{page - 1}"))
    if end < len(specs):
        nav_buttons.append(
            InlineKeyboardButton(text="➡️ След.", callback_data=f"specpage|{action}|{ptype}|{cat_idx}|{page + 1}"))

    if nav_buttons:
        kb.row(*nav_buttons)

    kb.row(InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data=f"actstart|{action}|{ptype}"))
    return kb.as_markup()


def browse_kb(has_prev: bool, has_more: bool, action: str, ptype: str, cat_idx: int, spec_idx: int, post_id: int,
              author_id: int, username: str):
    kb = InlineKeyboardBuilder()
    if username:
        kb.button(text="✉️ Написать автору", url=f"t.me/{username}")
    else:
        kb.button(text="✉️ Написать автору", url=f"tg://user?id={author_id}")
    if has_prev: kb.button(text="⬅️ Предыдущее", callback_data="bprev")
    if has_more: kb.button(text="➡️ Следующее", callback_data="bnext")
    kb.button(text="🔔 Подписаться на новые", callback_data=f"sub|{cat_idx}|{spec_idx}")
    kb.button(text="🙈 Больше не показывать", callback_data=f"hide|{post_id}")
    kb.button(text="🚩 Пожаловаться", callback_data=f"report|{post_id}")
    kb.button(text="⬅️ К списку специальностей", callback_data=f"cat|{action}|{ptype}|{cat_idx}")
    kb.button(text="🏠 В меню", callback_data="menu")
    kb.adjust(1, 2, 1, 2, 1, 1)
    return kb.as_markup()


def my_list_kb(ptype: str, rows):
    kb = InlineKeyboardBuilder()
    for r in rows:
        kb.button(text=f"{r['specialty']} — {r['city']}", callback_data=f"myview|{ptype}|{r['id']}")
    kb.button(text="🏠 В меню", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def my_view_kb(ptype: str, post_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Удалить", callback_data=f"delconfirm|{ptype}|{post_id}")
    kb.button(text="⬅️ Назад", callback_data=f"mylist|{ptype}")
    kb.adjust(1)
    return kb.as_markup()


def del_confirm_kb(ptype: str, post_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, удалить", callback_data=f"delyes|{ptype}|{post_id}")
    kb.button(text="❌ Отмена", callback_data=f"myview|{ptype}|{post_id}")
    kb.adjust(1)
    return kb.as_markup()


# --- Вспомогательные сервисы ---

async def notify_subscribers(bot: Bot, ptype: str, city: str, category: str, specialty: str, post_text: str):
    user_ids = db.get_matching_subscriptions(city, category, specialty)
    if not user_ids: return
    label = "вакансия" if ptype == "vacancy" else "резюме"
    text = (
        f"🔔 <b>Новая {label} по вашей подписке!</b>\n\n"
        f"{post_text}"
    )
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            await asyncio.sleep(0.05)
        except Exception:
            pass


def format_post(row) -> str:
    author = f"@{row.get('username')}" if row.get('username') else "Скрыт (Используйте кнопку связи)"
    category = row.get('category', 'Без категории')
    specialty = row.get('specialty', 'Без специальности')
    city = row.get('city', 'Все города')
    ptype_str = TYPE_LABEL.get(row.get('ptype', 'vacancy'), 'объявление')
    text = row.get('text', '')
    return (
        f"<b>{category}</b>\n"
        f"Специальность: <b>{specialty}</b>\n"
        f"Город: {city}\n"
        f"Тип: {ptype_str}\n\n"
        f"{text}\n\n"
        f"Автор: {author}"
    )


# --- ХЕНДЛЕРЫ ЮЗЕРА ---

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    db.upsert_user(message.from_user.id, message.from_user.username)
    welcome_text = (
        "Привет! 👋\n\n"
        "Перед использованием бота ознакомься с правилами использования, "
        "политикой конфиденциальности и отказом от ответственности владельцем бота.\n\n"
        "Нажимая любую кнопку и продолжая работу бота, вы подтверждаете, "
        "что ознакомились и согласны с правилами использования, "
        "политикой конфиденциальности и отказом от ответственности владельцем бота."
    )
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        terms_path = os.path.join(base_dir, "terms.txt")

        terms_file = FSInputFile(path=terms_path)
        await message.answer_document(
            document=terms_file,
            caption=welcome_text,
            reply_markup=main_menu_kb()
        )
    except Exception as e:
        log.error(f"Не удалось отправить файл terms.txt: {e}")
        await message.answer(
            f"{welcome_text}\n\n⚠️ Не удалось загрузить файл с условиями (terms.txt).",
            reply_markup=main_menu_kb()
        )


@router.message(F.text == BTN_NOTIFICATIONS)
async def h_notifications(message: Message, state: FSMContext):
    await state.clear()
    city = db.get_city(message.from_user.id)
    if not city:
        await state.set_state(Form.waiting_city_post)
        await state.update_data(pending_action="sub", pending_ptype="vacancy")
        await message.answer("Укажите ваш город для настройки системы уведомлений:", reply_markup=post_city_kb())
        return
    await message.answer("⚙️ <b>Настройка уведомлений</b>\n\nВыберите, что вы хотите отслеживать:",
                         reply_markup=sub_type_kb())


@router.message(F.text == BTN_CITY)
async def h_city(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Выберите режим управления городом:", reply_markup=city_selection_kb())


@router.message(F.text == BTN_ALL_CITIES)
async def h_all_cities(message: Message, state: FSMContext):
    await state.clear()
    db.set_city(message.from_user.id, "Все города")
    await message.answer("Включен режим работы со всеми городами.", reply_markup=main_menu_kb())


@router.message(F.text == BTN_ENTER_OTHER_CITY)
async def h_enter_other_city(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Form.waiting_city)
    await message.answer("Введите новый город:", reply_markup=ReplyKeyboardRemove())


@router.message(F.text == BTN_BACK)
async def h_back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню:", reply_markup=main_menu_kb())


@router.message(Form.waiting_city)
async def process_city(message: Message, state: FSMContext):
    city = (message.text or "").strip()
    if city == BTN_BACK:
        await state.clear()
        await message.answer("Главное меню:", reply_markup=main_menu_kb())
        return
    if not city or len(city) > 100:
        await message.answer("Пожалуйста, укажите корректное название города:")
        return
    if city == BTN_ALL_CITIES:
        city_to_save = "Все города"
    else:
        city_to_save = city
    db.set_city(message.from_user.id, city_to_save)
    await state.clear()
    await message.answer(f"Город сохранён: {city_to_save}", reply_markup=main_menu_kb())


# --- ПОСТИНГ И ПРОСМОТР ---

async def start_action(message: Message, state: FSMContext, action: str, ptype: str):
    if action == "create":
        db.set_city(message.from_user.id, None)
    city = db.get_city(message.from_user.id)
    if not city:
        await state.set_state(Form.waiting_city_post)
        await state.update_data(pending_action=action, pending_ptype=ptype)
        await message.answer("Укажите ваш город для работы с системой или выберите «Все города»:",
                             reply_markup=post_city_kb())
        return
    await state.clear()
    await message.answer(f"{ACTION_LABEL[action]} · {TYPE_LABEL[ptype]}\nГород: {city}\n\nВыберите категорию:",
                         reply_markup=categories_kb(action, ptype))


@router.message(F.text == BTN_VIEW_VAC)
async def h_view_vac(message: Message, state: FSMContext): await start_action(message, state, "view", "vacancy")


@router.message(F.text == BTN_CREATE_VAC)
async def h_create_vac(message: Message, state: FSMContext): await start_action(message, state, "create", "vacancy")


@router.message(F.text == BTN_VIEW_RES)
async def h_view_res(message: Message, state: FSMContext): await start_action(message, state, "view", "resume")


@router.message(F.text == BTN_CREATE_RES)
async def h_create_res(message: Message, state: FSMContext): await start_action(message, state, "create", "resume")


@router.message(Form.waiting_city_post)
async def process_post_city(message: Message, state: FSMContext):
    raw_city = (message.text or "").strip()
    if raw_city == BTN_BACK:
        await state.clear()
        await message.answer("Главное меню:", reply_markup=main_menu_kb())
        return
    if not raw_city or len(raw_city) > 100:
        await message.answer("Укажите корректный город:")
        return
    if raw_city == BTN_ALL_CITIES:
        city_to_save = "Все города"
    else:
        city_to_save = raw_city
    db.set_city(message.from_user.id, city_to_save)
    state_data = await state.get_data()
    pending_action = state_data.get("pending_action")
    pending_ptype = state_data.get("pending_ptype")
    await state.clear()
    if pending_action == "sub":
        await message.answer("⚙️ <b>Настройка уведомлений</b>\n\nВыберите, что вы хотите отслеживать:",
                             reply_markup=sub_type_kb())
    elif pending_action == "create_post":
        await state.set_state(Form.waiting_post_text)
        await state.update_data(city=city_to_save, **{k: v for k, v in state_data.items() if k.startswith("post_")})
        await message.answer(
            f"Город: {city_to_save}\n\nВведите текст объявления:",
            reply_markup=text_input_kb()
        )
    elif pending_action and pending_ptype:
        await message.answer(
            f"{ACTION_LABEL[pending_action]} · {TYPE_LABEL[pending_ptype]}\nГород: {city_to_save}\n\nВыберите категорию:",
            reply_markup=categories_kb(pending_action, pending_ptype)
        )
    else:
        await message.answer("Главное меню:", reply_markup=main_menu_kb())


@router.message(Form.waiting_post_text)
async def process_post_text(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == BTN_BACK_TO_SPECS:
        state_data = await state.get_data()
        action = "create"
        ptype = state_data.get("post_ptype")
        cat_idx = state_data.get("post_cat_idx")
        await state.clear()
        if cat_idx is not None and ptype:
            await message.answer("Выберите специальность:", reply_markup=ReplyKeyboardRemove())
            await message.answer("Возвращаемся к выбору специальности:",
                                 reply_markup=specialties_kb(action, ptype, cat_idx, page=0))
        else:
            await message.answer("Главное меню:", reply_markup=main_menu_kb())
        return
    if not text:
        await message.answer("Пришлите описание текстовым сообщением:")
        return
    spam_err = db.check_spam_and_limits(message.from_user.id, text)
    if spam_err:
        await message.answer(spam_err, reply_markup=main_menu_kb())
        await state.clear()
        return
    state_data = await state.get_data()
    ptype, category, specialty = state_data["post_ptype"], state_data["post_category"], state_data["post_specialty"]
    city = db.get_city(message.from_user.id)
    db.add_post(message.from_user.id, message.from_user.username, ptype, category, specialty, city, text)
    formatted_content = format_post({
        "username": message.from_user.username,
        "ptype": ptype,
        "category": category,
        "specialty": specialty,
        "city": city,
        "text": text
    })
    await state.clear()
    await message.answer("✅ Публикация успешно размещена!", reply_markup=main_menu_kb())
    try:
        await notify_subscribers(message.bot, ptype, city, category, specialty, formatted_content)
    except Exception as e:
        log.error(f"Ошибка при рассылке уведомлений: {e}")


@router.message(F.text == BTN_MY_VAC)
async def h_my_vac(message: Message, state: FSMContext):
    await state.clear()
    rows = db.get_my_posts(message.from_user.id, "vacancy")
    if rows:
        await message.answer("Ваши вакансии:", reply_markup=my_list_kb("vacancy", rows))
    else:
        await message.answer("У вас пока нет активных вакансий.", reply_markup=main_menu_kb())


@router.message(F.text == BTN_MY_RES)
async def h_my_res(message: Message, state: FSMContext):
    await state.clear()
    rows = db.get_my_posts(message.from_user.id, "resume")
    if rows:
        await message.answer("Ваши резюме:", reply_markup=my_list_kb("resume", rows))
    else:
        await message.answer("У вас пока нет активных резюме.", reply_markup=main_menu_kb())


# --- ИНЛАЙН ХЕНДЛЕРЫ ---

@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "sub_menu_back")
async def cb_sub_menu_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("⚙️ <b>Настройка уведомлений</b>\n\nВыберите, что вы хотите отслеживать:",
                                     reply_markup=sub_type_kb())


@router.callback_query(F.data.startswith("substart|"))
async def cb_substart(callback: CallbackQuery):
    ptype = callback.data.split("|")[1]
    city = db.get_city(callback.from_user.id)
    await callback.message.edit_text(f"🔔 Подписка · {TYPE_LABEL[ptype]}\nГород: {city}\n\nВыберите категорию:",
                                     reply_markup=categories_kb("sub", ptype))


@router.callback_query(F.data.startswith("actstart|"))
async def cb_actstart(callback: CallbackQuery):
    _, action, ptype = callback.data.split("|")
    await callback.message.edit_text("Выберите категорию:", reply_markup=categories_kb(action, ptype))


@router.callback_query(F.data.startswith("cat|"))
async def cb_category(callback: CallbackQuery):
    _, action, ptype, cat_idx = callback.data.split("|")
    cat_idx = int(cat_idx)
    if action == "sub":
        city = db.get_city(callback.from_user.id)
        current_subs = db.get_user_subscriptions(callback.from_user.id, city, ptype)
        await callback.message.edit_text("Выберите специальности (нажмите для включения/выключения):",
                                         reply_markup=specialties_sub_kb(ptype, cat_idx, current_subs, page=0))
    else:
        await callback.message.edit_text("Выберите специальность:",
                                         reply_markup=specialties_kb(action, ptype, cat_idx, page=0))


@router.callback_query(F.data.startswith("specpage|"))
async def cb_specialty_page(callback: CallbackQuery):
    data_parts = callback.data.split("|")
    action = data_parts[1]
    ptype = data_parts[2]
    cat_idx = int(data_parts[3])
    page = int(data_parts[4])

    if action == "sub":
        city = db.get_city(callback.from_user.id)
        current_subs = db.get_user_subscriptions(callback.from_user.id, city, ptype)
        await callback.message.edit_text(
            "Выберите специальности (нажмите для включения/выключения):",
            reply_markup=specialties_sub_kb(ptype, cat_idx, current_subs, page=page)
        )
    else:
        await callback.message.edit_text(
            "Выберите специальность:",
            reply_markup=specialties_kb(action, ptype, cat_idx, page=page)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("subtoggle|"))
async def cb_subtoggle(callback: CallbackQuery):
    _, ptype, cat_idx, spec_idx, page = callback.data.split("|")
    cat_idx, spec_idx, page = int(cat_idx), int(spec_idx), int(page)
    cat = CATEGORIES[cat_idx]
    category_title = f"{cat['emoji']} {cat['name']}"
    specialty_title = cat["specs"][spec_idx]
    city = db.get_city(callback.from_user.id)
    current_subs = db.get_user_subscriptions(callback.from_user.id, city, ptype)
    if (category_title, specialty_title) in current_subs:
        db.remove_subscription(callback.from_user.id, city, category_title, specialty_title, ptype)
        await callback.answer("❌ Подписка удалена")
    else:
        db.add_subscription(callback.from_user.id, city, category_title, specialty_title, ptype)
        await callback.answer("✅ Подписка добавлена")
    updated_subs = db.get_user_subscriptions(callback.from_user.id, city, ptype)
    await callback.message.edit_reply_markup(reply_markup=specialties_sub_kb(ptype, cat_idx, updated_subs, page=page))


@router.callback_query(F.data.startswith("spec|"))
async def cb_specialty(callback: CallbackQuery, state: FSMContext):
    _, action, ptype, cat_idx, spec_idx = callback.data.split("|")
    cat_idx, spec_idx = int(cat_idx), int(spec_idx)
    cat = CATEGORIES[cat_idx]
    specialty = cat["specs"][spec_idx]
    category = f"{cat['emoji']} {cat['name']}"
    if action == "create":
        await state.set_state(Form.waiting_city_post)
        await state.update_data(
            pending_action="create_post",
            post_ptype=ptype,
            post_category=category,
            post_specialty=specialty,
            post_cat_idx=cat_idx
        )
        await callback.message.answer(
            "📍 Введите город вакансии/резюме:",
            reply_markup=post_city_kb()
        )
        return
    city = db.get_city(callback.from_user.id)
    rows = db.get_feed(ptype, city, category, specialty, callback.from_user.id)
    if not rows:
        await callback.message.edit_text("Объявлений пока нет.",
                                         reply_markup=specialties_kb(action, ptype, cat_idx, page=0))
        return
    await state.update_data(browse_ids=[r["id"] for r in rows], browse_pos=0, browse_action=action, browse_ptype=ptype,
                            browse_cat_idx=cat_idx, browse_spec_idx=spec_idx)
    post = rows[0]
    await callback.message.edit_text(format_post(post),
                                     reply_markup=browse_kb(False, len(rows) > 1, action, ptype, cat_idx, spec_idx,
                                                            post["id"], post["user_id"], post["username"]))


@router.callback_query(F.data.startswith("sub|"))
async def cb_subscribe(callback: CallbackQuery):
    _, cat_idx, spec_idx = callback.data.split("|")
    cat = CATEGORIES[int(cat_idx)]
    db.add_subscription(callback.from_user.id, db.get_city(callback.from_user.id), f"{cat['emoji']} {cat['name']}",
                        cat["specs"][int(spec_idx)], "vacancy")
    await callback.answer("🔔 Успешная подписка на вакансии!", show_alert=True)


@router.callback_query(F.data == "bnext")
async def cb_browse_next(callback: CallbackQuery, state: FSMContext): await _advance(callback, state, 1)


@router.callback_query(F.data == "bprev")
async def cb_browse_prev(callback: CallbackQuery, state: FSMContext): await _advance(callback, state, -1)


async def _advance(callback: CallbackQuery, state: FSMContext, step: int):
    state_data = await state.get_data()
    ids, pos = state_data.get("browse_ids", []), state_data.get("browse_pos", 0) + step
    if pos < 0 or pos >= len(ids):
        await callback.answer("Конец списка.")
        return
    post = db.get_post(ids[pos])
    if not post:
        await _advance(callback, state, step)
        return
    await state.update_data(browse_pos=pos)
    await callback.message.edit_text(format_post(post),
                                     reply_markup=browse_kb(pos > 0, pos + 1 < len(ids), state_data["browse_action"],
                                                            state_data["browse_ptype"], state_data["browse_cat_idx"],
                                                            state_data["browse_spec_idx"], post["id"], post["user_id"],
                                                            post["username"]))


@router.callback_query(F.data.startswith("hide|"))
async def cb_hide(callback: CallbackQuery, state: FSMContext):
    db.hide_post(callback.from_user.id, int(callback.data.split("|")[1]))
    await _advance(callback, state, 1)


@router.callback_query(F.data.startswith("report|"))
async def cb_report(callback: CallbackQuery):
    post = db.get_post(int(callback.data.split("|")[1]))
    if post and ADMIN_ID:
        kb = InlineKeyboardBuilder().button(text="🚫 Забанить автора",
                                            callback_data=f"adminblock|{post['user_id']}").as_markup()
        await callback.bot.send_message(ADMIN_ID, f"🚩 Жалоба на пост:\n\n{format_post(post)}", reply_markup=kb)
    await callback.answer("Жалоба отправлена.", show_alert=True)


@router.callback_query(F.data.startswith("myview|"))
async def cb_myview(callback: CallbackQuery):
    _, ptype, pid = callback.data.split("|")
    post = db.get_post(int(pid))
    if post: await callback.message.edit_text(format_post(post), reply_markup=my_view_kb(ptype, post["id"]))


@router.callback_query(F.data.startswith("delconfirm|"))
async def cb_delconfirm(callback: CallbackQuery):
    _, ptype, pid = callback.data.split("|")
    await callback.message.edit_text("Удалить публикацию?", reply_markup=del_confirm_kb(ptype, int(pid)))


@router.callback_query(F.data.startswith("delyes|"))
async def cb_delyes(callback: CallbackQuery):
    _, ptype, pid = callback.data.split("|")
    db.delete_post(int(pid), callback.from_user.id)
    rows = db.get_my_posts(callback.from_user.id, ptype)
    if rows:
        await callback.message.edit_text("Успешно удалено.", reply_markup=my_list_kb(ptype, rows))
    else:
        await callback.message.edit_text("Все публикации удалены.")
        await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await callback.answer()


# --- АДМИН-ПАНЕЛЬ ---

def is_admin(uid: int) -> bool: return bool(ADMIN_ID) and uid == ADMIN_ID


def admin_panel_kb():
    return InlineKeyboardBuilder().button(text="📊 Статистика", callback_data="adminstats").button(text="📢 Рассылка",
                                                                                                  callback_data="adminbroadcast").adjust(
        1).as_markup()


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if is_admin(message.from_user.id):
        await state.clear()
        await message.answer("🔧 <b>Админ-панель</b>", reply_markup=admin_panel_kb())


@router.callback_query(F.data == "adminpanel")
async def cb_admin_panel(callback: CallbackQuery, state: FSMContext):
    if is_admin(callback.from_user.id):
        await state.clear()
        await callback.message.edit_text("🔧 <b>Админ-панель</b>", reply_markup=admin_panel_kb())


@router.callback_query(F.data == "adminstats")
async def cb_admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    s = db.get_stats()
    kb = InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data="adminpanel").as_markup()
    await callback.message.edit_text(
        f"📊 <b>Статистика</b>\n\nЮзеров: {s['users']}\nВакансий: {s['vacancies']}\nРезюме: {s['resumes']}\nВ бане: {s['blocked']}",
        reply_markup=kb)


@router.callback_query(F.data == "adminbroadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(Form.waiting_broadcast_content)
    kb = InlineKeyboardBuilder().button(text="❌ Отмена", callback_data="adminpanel").as_markup()
    await callback.message.edit_text("Отправьте текст или любой файл (фото, документ) для рассылки:", reply_markup=kb)


@router.message(StateFilter(Form.waiting_broadcast_content))
async def process_broadcast_content(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.update_data(broadcast_message_id=message.message_id)
    await state.set_state(Form.waiting_broadcast_confirm)
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Разослать", callback_data="confirm_broadcast_send")
    kb.button(text="❌ Отмена", callback_data="adminpanel")
    kb.adjust(1)
    await message.answer("Вот предпросмотр вашего сообщения. Нажмите кнопку ниже для отправки:",
                         reply_markup=kb.as_markup())


@router.callback_query(F.data == "confirm_broadcast_send", StateFilter(Form.waiting_broadcast_confirm))
async def cb_confirm_broadcast_send(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    state_data = await state.get_data()
    msg_id = state_data.get("broadcast_message_id")
    await state.clear()
    uids = db.get_all_users()
    sent, errors, blocked = 0, 0, 0
    status = await callback.message.answer("📢 Рассылка запущена...")
    await callback.answer()
    for uid in uids:
        try:
            await callback.bot.copy_message(chat_id=uid, from_chat_id=ADMIN_ID, message_id=msg_id)
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await callback.bot.copy_message(chat_id=uid, from_chat_id=ADMIN_ID, message_id=msg_id)
                sent += 1
            except Exception:
                errors += 1
        except TelegramForbiddenError:
            blocked += 1
            db.block_user(uid)
        except Exception:
            errors += 1
    await status.delete()
    await callback.message.answer(
        f"📢 <b>Готово!</b>\n\nДоставлено: {sent}\nЗаблокировали бота: {blocked}\nОшибки: {errors}")


@router.callback_query(F.data.startswith("adminblock|"))
async def cb_adminblock(callback: CallbackQuery):
    if is_admin(callback.from_user.id):
        uid = int(callback.data.split("|")[1])
        db.block_user(uid)
        await callback.answer("Пользователь заблокирован.")


# --- ХЕНДЛЕР-ЗАГЛУШКА ДЛЯ ИГНОРИРОВАНИЯ ГОРОДОВ В ЧАТЕ ---
@router.message(StateFilter(None))
async def h_ignore_plain_text(message: Message):
    pass


# --- ЗАПУСК ---

async def main():
    db.init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(BlockCheckMiddleware())
    dp.callback_query.outer_middleware(BlockCheckMiddleware())
    dp.include_router(router)
    log.info("Бот успешно запущен в монолитном режиме.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
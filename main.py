# main.py — простой Telegram-бот для приёма заявок + панель владельца
# Запуск: python main.py
# Установка библиотеки (один раз): pip install pyTelegramBotAPI

import json
import os
import sys
import threading
import time
import telebot
from telebot import types
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
BOOKINGS_PATH = os.path.join(HERE, "bookings.json")
SLOTS_PATH = os.path.join(HERE, "slots.json")
WELCOME_VOICE_PATH = os.path.join(HERE, "welcome.ogg")  # необязательный голосовой attachment

# ===== Список услуг (для выбора при записи) =====
SERVICES = ("маникюр", "парикмахер", "ремонт", "услуги")

# ===== Дефолтная структура config.json =====
DEFAULT_CONFIG = {
    "business_name": "Название бизнеса",
    "welcome_text": "Здравствуйте! Чем могу помочь? Выберите кнопку:",
    "services_text": "Наши услуги:\n- Услуга 1\n- Услуга 2\n- Услуга 3",
    "prices_text": "Наши цены:\n- Услуга 1: 100 шек.\n- Услуга 2: 200 шек.",
    "address_text": "Наш адрес:\nАшдод, улица ...\nЧасы работы: 10:00-20:00",
    "admin_chat_id": 0,
}

# ===== Тексты-кнопки админ-панели (используются в нескольких местах) =====
ADMIN_PANEL_BTN = "⚙️ Панель владельца"
ADMIN_EDIT_SERVICES = "Изменить услуги"
ADMIN_EDIT_PRICES = "Изменить цены"
ADMIN_EDIT_ADDRESS = "Изменить адрес"
ADMIN_BACK = "⬅️ Назад"
# Кнопки админ-панели для быстрого доступа к командам
ADMIN_BTN_TODAY        = "📅 Сегодня"
ADMIN_BTN_ALL_BOOKINGS = "📋 Все записи"
ADMIN_BTN_SLOTS        = "🕒 Слоты"
ADMIN_BTN_ADD_SLOT     = "➕ Добавить слот"
ADMIN_BTN_BOOK_MANUAL  = "✍️ Записать вручную"
ADMIN_BTN_FREE_SLOT    = "🔓 Освободить слот"
ADMIN_BTN_DEL_SLOT     = "🗑 Удалить слот"
ADMIN_BTN_DEL_BOOKING  = "❌ Удалить запись"
ADMIN_BUTTONS = {
    ADMIN_PANEL_BTN, ADMIN_EDIT_SERVICES, ADMIN_EDIT_PRICES,
    ADMIN_EDIT_ADDRESS, ADMIN_BACK,
    ADMIN_BTN_TODAY, ADMIN_BTN_ALL_BOOKINGS, ADMIN_BTN_SLOTS,
    ADMIN_BTN_ADD_SLOT, ADMIN_BTN_BOOK_MANUAL, ADMIN_BTN_FREE_SLOT,
    ADMIN_BTN_DEL_SLOT, ADMIN_BTN_DEL_BOOKING,
}
USER_BUTTONS = {"Услуги", "Цены", "Адрес", "Записаться"}


# ===== Конфиг =====
def load_config():
    """Читает config.json. Если файла нет — создаёт шаблон и просит заполнить."""
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        print(f"⚠ config.json не найден — создан шаблон: {CONFIG_PATH}")
        print("Откройте файл, заполните admin_chat_id и тексты, потом запустите бота снова.")
        sys.exit(1)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"⚠ Ошибка чтения config.json: {e}")
        sys.exit(1)
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def save_config():
    """Атомарная запись CONFIG обратно в config.json (через временный файл)."""
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


# ===== Записи (календарь) =====
def load_bookings():
    """Читает bookings.json. Если файла нет или он битый — возвращает пустой список."""
    if not os.path.exists(BOOKINGS_PATH):
        return []
    try:
        with open(BOOKINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_bookings(items):
    """Атомарная запись списка записей в bookings.json."""
    tmp = BOOKINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, BOOKINGS_PATH)


def ensure_bookings_file():
    """Создаёт bookings.json с пустым списком, если файла нет."""
    if not os.path.exists(BOOKINGS_PATH):
        save_bookings([])


def today_str():
    """Сегодняшняя дата в формате DD.MM.YYYY."""
    return datetime.now().strftime("%d.%m.%Y")


def format_booking(b):
    """Одна запись → строка вида '11:30 — Тая — маникюр'."""
    return f"{b.get('time', '—')} — {b.get('client_name', '—')} — {b.get('service', '—')}"


# ===== Свободные слоты =====
def load_slots():
    """Читает slots.json. Если файла нет или он битый — возвращает пустой список."""
    if not os.path.exists(SLOTS_PATH):
        return []
    try:
        with open(SLOTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_slots(items):
    """Атомарная запись списка слотов в slots.json."""
    tmp = SLOTS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SLOTS_PATH)


def ensure_slots_file():
    """Создаёт slots.json с 3 примерами на сегодня, если файла нет."""
    if not os.path.exists(SLOTS_PATH):
        today = today_str()
        sample = [
            {"date": today, "time": "11:30", "service": "маникюр", "status": "free"},
            {"date": today, "time": "13:00", "service": "маникюр", "status": "free"},
            {"date": today, "time": "15:00", "service": "парикмахер", "status": "free"},
        ]
        save_slots(sample)


def _slot_sort_key(s):
    """Сортировка по дате (YYYYMMDD), затем по времени."""
    try:
        d = datetime.strptime(s.get("date", ""), "%d.%m.%Y").strftime("%Y%m%d")
    except Exception:
        d = "00000000"
    return (d, s.get("time", ""))


def get_free_slots_for_service(service):
    """Возвращает все свободные слоты для услуги, отсортированные по дате+времени."""
    slots = load_slots()
    free = [s for s in slots if s.get("service") == service and s.get("status") == "free"]
    free.sort(key=_slot_sort_key)
    return free


def mark_slot_booked(date, time, service):
    """Находит свободный слот по date+time+service и меняет status на 'booked'.
    Возвращает True, если слот был найден и обновлён."""
    slots = load_slots()
    updated = False
    for s in slots:
        if (s.get("date") == date and s.get("time") == time
                and s.get("service") == service and s.get("status") == "free"):
            s["status"] = "booked"
            updated = True
            break
    if updated:
        save_slots(slots)
    return updated


# ===== Bootstrap =====
# Переменные окружения (Railway / любой PaaS / shell export)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения")

TOKEN = BOT_TOKEN  # ниже telebot инициализируется переменной TOKEN

CONFIG = load_config()

# Если ADMIN_CHAT_ID задан через env — переопределяем значение из config.json
if ADMIN_CHAT_ID:
    try:
        CONFIG["admin_chat_id"] = int(ADMIN_CHAT_ID)
    except (TypeError, ValueError):
        print(f"⚠ ADMIN_CHAT_ID env не число: {ADMIN_CHAT_ID}")

ensure_bookings_file()
ensure_slots_file()

# ===== Создаём бота =====
bot = telebot.TeleBot(TOKEN)
user_data = {}


# ===== Helpers =====
def is_admin(chat_id):
    """True, если этот chat_id указан как admin_chat_id в config.json."""
    try:
        return int(chat_id) == int(CONFIG.get("admin_chat_id", 0))
    except (TypeError, ValueError):
        return False


def main_keyboard(chat_id=None):
    """Главная клавиатура. Для владельца — плюс кнопка панели."""
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("Услуги", "Цены")
    kb.row("Адрес", "Записаться")
    if is_admin(chat_id):
        kb.row(ADMIN_PANEL_BTN)
    return kb


def admin_keyboard():
    """Клавиатура внутри панели владельца."""
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(ADMIN_BTN_TODAY, ADMIN_BTN_ALL_BOOKINGS)
    kb.row(ADMIN_BTN_SLOTS, ADMIN_BTN_ADD_SLOT)
    kb.row(ADMIN_BTN_BOOK_MANUAL, ADMIN_BTN_FREE_SLOT)
    kb.row(ADMIN_BTN_DEL_SLOT, ADMIN_BTN_DEL_BOOKING)
    kb.row(ADMIN_EDIT_SERVICES, ADMIN_EDIT_PRICES)
    kb.row(ADMIN_EDIT_ADDRESS)
    kb.row(ADMIN_BACK)
    return kb


def services_keyboard():
    """Клавиатура выбора услуги при записи."""
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row(SERVICES[0], SERVICES[1])
    kb.row(SERVICES[2], SERVICES[3])
    return kb


def slots_keyboard(free_slots):
    """Клавиатура выбора свободного слота. По одной кнопке на слот."""
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for s in free_slots:
        kb.row(f"{s.get('date', '')} {s.get('time', '')}".strip())
    return kb


# ===== /start — приветствие =====
# Текст голосового файла welcome.ogg (если он есть в папке):
#   "Здравствуйте! Вы можете записаться через кнопки ниже."
# Если файла нет — отправляется только текстовое приветствие (fallback).
@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    user_data.pop(message.chat.id, None)

    # Голосовое приветствие (опционально)
    if os.path.exists(WELCOME_VOICE_PATH):
        try:
            with open(WELCOME_VOICE_PATH, "rb") as voice_file:
                bot.send_voice(message.chat.id, voice_file)
        except Exception as e:
            print(f"⚠ Не удалось отправить voice welcome.ogg: {e}")

    bot.send_message(
        message.chat.id,
        CONFIG["welcome_text"],
        reply_markup=main_keyboard(message.chat.id),
    )


# ===== Информационные кнопки (тексты из config.json) =====
@bot.message_handler(func=lambda m: m.text == "Услуги")
def show_services(message):
    bot.send_message(message.chat.id, CONFIG["services_text"], reply_markup=main_keyboard(message.chat.id))


@bot.message_handler(func=lambda m: m.text == "Цены")
def show_prices(message):
    bot.send_message(message.chat.id, CONFIG["prices_text"], reply_markup=main_keyboard(message.chat.id))


@bot.message_handler(func=lambda m: m.text == "Адрес")
def show_address(message):
    bot.send_message(message.chat.id, CONFIG["address_text"], reply_markup=main_keyboard(message.chat.id))


# ===== Кнопка "Записаться" — flow из 4 шагов =====
# 1) услуга → 2) свободный слот → 3) имя → 4) телефон → запись + уведомления
@bot.message_handler(func=lambda m: m.text == "Записаться")
def start_booking(message):
    user_data[message.chat.id] = {}
    bot.send_message(
        message.chat.id,
        "Выберите услугу:",
        reply_markup=services_keyboard(),
    )
    bot.register_next_step_handler(message, handle_service_choice)


def handle_service_choice(message):
    """Шаг 1: получили услугу, показываем свободные слоты."""
    chat_id = message.chat.id
    text = (message.text or "").strip()
    if text not in SERVICES:
        bot.send_message(chat_id, "Запись отменена.", reply_markup=main_keyboard(chat_id))
        user_data.pop(chat_id, None)
        return
    free = get_free_slots_for_service(text)
    if not free:
        bot.send_message(
            chat_id,
            "Пока нет свободного времени для этой услуги.",
            reply_markup=main_keyboard(chat_id),
        )
        user_data.pop(chat_id, None)
        return
    user_data.setdefault(chat_id, {})["service"] = text
    user_data[chat_id]["free_slots"] = free
    bot.send_message(
        chat_id,
        "Выберите свободное время:",
        reply_markup=slots_keyboard(free),
    )
    bot.register_next_step_handler(message, handle_slot_choice)


def handle_slot_choice(message):
    """Шаг 2: получили слот, спрашиваем имя."""
    chat_id = message.chat.id
    text = (message.text or "").strip()
    state = user_data.get(chat_id, {})
    free = state.get("free_slots", [])

    parts = text.split()
    if len(parts) != 2:
        bot.send_message(chat_id, "Запись отменена.", reply_markup=main_keyboard(chat_id))
        user_data.pop(chat_id, None)
        return
    chosen_date, chosen_time = parts[0], parts[1]
    matching = next(
        (s for s in free if s.get("date") == chosen_date and s.get("time") == chosen_time),
        None,
    )
    if not matching:
        bot.send_message(chat_id, "Запись отменена.", reply_markup=main_keyboard(chat_id))
        user_data.pop(chat_id, None)
        return
    state["slot"] = {"date": chosen_date, "time": chosen_time}
    bot.send_message(chat_id, "Как вас зовут?", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(message, handle_name)


def handle_name(message):
    """Шаг 3: получили имя, спрашиваем телефон."""
    chat_id = message.chat.id
    name = (message.text or "").strip()
    if not name or name.startswith("/"):
        bot.send_message(chat_id, "Имя пустое. Введите имя ещё раз:")
        bot.register_next_step_handler(message, handle_name)
        return
    user_data.setdefault(chat_id, {})["name"] = name
    bot.send_message(chat_id, "Введите ваш телефон:")
    bot.register_next_step_handler(message, handle_phone_finalize)


def handle_phone_finalize(message):
    """Шаг 4: получили телефон → сохраняем запись, бронируем слот, уведомляем."""
    chat_id = message.chat.id
    phone = (message.text or "").strip()
    if not phone or phone.startswith("/"):
        bot.send_message(chat_id, "Телефон пустой. Введите телефон ещё раз:")
        bot.register_next_step_handler(message, handle_phone_finalize)
        return

    state = user_data.get(chat_id, {})
    service = state.get("service", "—")
    slot = state.get("slot", {})
    date = slot.get("date", "—")
    time = slot.get("time", "—")
    name = state.get("name", "—")

    # 1) Сохраняем запись клиента в bookings.json
    bookings = load_bookings()
    new_booking = {
        "client_name": name,
        "service": service,
        "date": date,
        "time": time,
        "phone": phone,
        "client_chat_id": chat_id,        # для авто-напоминаний клиенту
        "client_reminder_sent": False,
    }
    bookings.append(new_booking)
    save_bookings(bookings)

    # 2) Помечаем слот как booked в slots.json
    mark_slot_booked(date, time, service)

    # 3) Подтверждаем клиенту
    bot.send_message(
        chat_id,
        f"✅ Вы записаны:\n{service}\n{date} в {time}",
        reply_markup=main_keyboard(chat_id),
    )

    # 4) Уведомляем админа
    user_username = message.from_user.username or "—"
    admin_msg = (
        f"📅 Новая запись:\n"
        f"Клиент: {name}\n"
        f"Телефон: {phone}\n"
        f"Услуга: {service}\n"
        f"Дата: {date}\n"
        f"Время: {time}\n"
        f"От: @{user_username} (chat_id={chat_id})"
    )
    print("=" * 50)
    print(admin_msg)
    print("=" * 50)
    try:
        bot.send_message(CONFIG["admin_chat_id"], admin_msg)
    except Exception as e:
        print(f"⚠ Не удалось отправить уведомление админу: {e}")

    user_data.pop(chat_id, None)


# ===== Админ-панель (видна только владельцу) =====
@bot.message_handler(func=lambda m: m.text == ADMIN_PANEL_BTN)
def show_admin_panel(message):
    if not is_admin(message.chat.id):
        return
    bot.send_message(
        message.chat.id,
        "Панель владельца. Что изменить?",
        reply_markup=admin_keyboard(),
    )


@bot.message_handler(func=lambda m: m.text == ADMIN_BACK)
def admin_back(message):
    if not is_admin(message.chat.id):
        return
    bot.send_message(
        message.chat.id,
        "Главное меню:",
        reply_markup=main_keyboard(message.chat.id),
    )


def _is_cancel_text(text):
    """Если вместо ввода нажата любая известная кнопка — считаем это отменой."""
    if not text:
        return True
    if text.startswith("/"):
        return True
    return text in ADMIN_BUTTONS or text in USER_BUTTONS


def _save_field(message, field_name, label):
    """Общий обработчик сохранения нового текста в CONFIG[field_name]."""
    if not is_admin(message.chat.id):
        return
    new_text = (message.text or "").strip()
    if _is_cancel_text(new_text):
        bot.send_message(message.chat.id, "Изменение отменено.", reply_markup=admin_keyboard())
        return
    # Поддержка \n как переноса строки
    new_text = new_text.replace("\\n", "\n")
    CONFIG[field_name] = new_text
    try:
        save_config()
        bot.send_message(message.chat.id, f"✅ {label} — обновлено.", reply_markup=admin_keyboard())
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠ Ошибка сохранения: {e}", reply_markup=admin_keyboard())


def _start_edit(message, prompt):
    bot.send_message(
        message.chat.id,
        prompt + "\n(\\n — это перенос строки)",
        reply_markup=types.ReplyKeyboardRemove(),
    )


@bot.message_handler(func=lambda m: m.text == ADMIN_EDIT_SERVICES)
def edit_services(message):
    if not is_admin(message.chat.id):
        return
    _start_edit(message, "Введите новый текст для 'Услуги':")
    bot.register_next_step_handler(message, lambda msg: _save_field(msg, "services_text", "Услуги"))


@bot.message_handler(func=lambda m: m.text == ADMIN_EDIT_PRICES)
def edit_prices(message):
    if not is_admin(message.chat.id):
        return
    _start_edit(message, "Введите новый текст для 'Цены':")
    bot.register_next_step_handler(message, lambda msg: _save_field(msg, "prices_text", "Цены"))


@bot.message_handler(func=lambda m: m.text == ADMIN_EDIT_ADDRESS)
def edit_address(message):
    if not is_admin(message.chat.id):
        return
    _start_edit(message, "Введите новый текст для 'Адрес':")
    bot.register_next_step_handler(message, lambda msg: _save_field(msg, "address_text", "Адрес"))


# ===== Команды календаря =====
@bot.message_handler(commands=["today"])
def today_cmd(message):
    """Показывает записи на сегодняшнюю дату."""
    bot.clear_step_handler_by_chat_id(message.chat.id)
    bookings = load_bookings()
    today = today_str()
    todays = [b for b in bookings if b.get("date") == today]
    if not todays:
        bot.send_message(message.chat.id, "Сегодня записей нет.")
        return
    todays.sort(key=lambda b: b.get("time", ""))
    lines = ["📅 Записи на сегодня:"]
    for b in todays:
        lines.append(format_booking(b))
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["bookings"])
def bookings_cmd(message):
    """Показывает все записи."""
    bot.clear_step_handler_by_chat_id(message.chat.id)
    bookings = load_bookings()
    if not bookings:
        bot.send_message(message.chat.id, "Записей пока нет.")
        return

    def _key(b):
        d = b.get("date", "")
        t = b.get("time", "")
        try:
            d = datetime.strptime(d, "%d.%m.%Y").strftime("%Y%m%d")
        except Exception:
            d = "00000000"
        return (d, t)

    bookings_sorted = sorted(bookings, key=_key)
    lines = ["📅 Все записи:"]
    for b in bookings_sorted:
        lines.append(f"{b.get('date', '—')} {format_booking(b)}")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["add"])
def add_cmd(message):
    """Добавляет тестовую запись на сегодня (MVP-команда)."""
    bot.clear_step_handler_by_chat_id(message.chat.id)
    bookings = load_bookings()
    new_booking = {
        "client_name": "Тая",
        "service": "маникюр",
        "date": today_str(),
        "time": "11:30",
        "phone": "",
    }
    bookings.append(new_booking)
    save_bookings(bookings)
    bot.send_message(
        message.chat.id,
        f"✅ Тестовая запись добавлена:\n{format_booking(new_booking)} ({new_booking['date']})",
    )


# ===== Клиентские команды управления своими записями =====
def _is_today_or_future(date_str):
    """True если дата DD.MM.YYYY сегодня или в будущем."""
    try:
        d = datetime.strptime(date_str, "%d.%m.%Y").date()
        return d >= datetime.now().date()
    except (ValueError, TypeError):
        return False


def _user_active_bookings(chat_id):
    """Возвращает [(original_index_in_bookings_list, booking), ...] для записей клиента,
    которые сегодня или в будущем. Сохраняем оригинальный индекс — его используем
    при удалении из bookings.json."""
    bookings = load_bookings()
    out = []
    for i, b in enumerate(bookings):
        if b.get("client_chat_id") != chat_id:
            continue
        if not _is_today_or_future(b.get("date", "")):
            continue
        out.append((i, b))
    # сортировка по дате+времени для красивого вывода
    out.sort(key=lambda pair: _slot_sort_key(pair[1]))
    return out


# --- /mybookings ---
@bot.message_handler(commands=["mybookings"])
def cmd_mybookings(message):
    """Клиент видит только свои активные записи."""
    bot.clear_step_handler_by_chat_id(message.chat.id)
    user_bookings = _user_active_bookings(message.chat.id)
    if not user_bookings:
        bot.send_message(message.chat.id, "У вас нет активных записей.")
        return
    lines = ["📅 Ваши записи:"]
    for i, (_orig_idx, b) in enumerate(user_bookings, 1):
        lines.append(f"{i}) {b.get('date', '—')} {b.get('time', '—')} — {b.get('service', '—')}")
    bot.send_message(message.chat.id, "\n".join(lines))


# --- /cancelbooking ---
@bot.message_handler(commands=["cancelbooking"])
def cmd_cancelbooking(message):
    """Клиент отменяет одну из своих записей по номеру."""
    bot.clear_step_handler_by_chat_id(message.chat.id)
    user_bookings = _user_active_bookings(message.chat.id)
    if not user_bookings:
        bot.send_message(message.chat.id, "У вас нет активных записей.")
        return
    lines = ["📅 Ваши записи:"]
    for i, (_orig_idx, b) in enumerate(user_bookings, 1):
        lines.append(f"{i}) {b.get('date', '—')} {b.get('time', '—')} — {b.get('service', '—')}")
    # cохраняем порядок original_index чтобы потом удалить именно ту запись
    user_data[message.chat.id] = {
        "cancel_indices": [orig_idx for orig_idx, _b in user_bookings],
    }
    bot.send_message(
        message.chat.id,
        "\n".join(lines) + "\n\nВведите номер записи для отмены:",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    bot.register_next_step_handler(message, _cancelbooking_number)


def _cancelbooking_number(message):
    """Шаг 2: клиент ввёл номер. Удаляем запись, освобождаем слот, уведомляем."""
    chat_id = message.chat.id
    state = user_data.get(chat_id, {})
    indices = state.get("cancel_indices", [])
    user_data.pop(chat_id, None)

    idx, err = _parse_index(message.text, len(indices))
    if err:
        bot.send_message(chat_id, err, reply_markup=main_keyboard(chat_id))
        return

    orig_idx = indices[idx]
    bookings = load_bookings()

    # Безопасность 1: индекс ещё валиден (вдруг bookings.json изменился между шагами)
    if orig_idx < 0 or orig_idx >= len(bookings):
        bot.send_message(chat_id, "Запись не найдена.", reply_markup=main_keyboard(chat_id))
        return

    target = bookings[orig_idx]
    # Безопасность 2: запись действительно принадлежит этому пользователю
    if target.get("client_chat_id") != chat_id:
        bot.send_message(chat_id, "Эта запись вам не принадлежит.", reply_markup=main_keyboard(chat_id))
        return

    # Удаляем запись
    deleted = bookings.pop(orig_idx)
    save_bookings(bookings)

    # Освобождаем соответствующий слот в slots.json
    slots = load_slots()
    freed = False
    for s in slots:
        if (s.get("date") == deleted.get("date")
                and s.get("time") == deleted.get("time")
                and s.get("service") == deleted.get("service")
                and s.get("status") == "booked"):
            s["status"] = "free"
            freed = True
            break
    if freed:
        save_slots(slots)
    else:
        print(
            f"⚠ slot not found for cancelled booking: "
            f"{deleted.get('date')} {deleted.get('time')} {deleted.get('service')}"
        )

    # Уведомляем клиента
    bot.send_message(
        chat_id,
        f"✅ Запись отменена:\n{deleted.get('date')} {deleted.get('time')} — {deleted.get('service')}",
        reply_markup=main_keyboard(chat_id),
    )

    # Уведомляем админа
    admin_id = CONFIG.get("admin_chat_id", 0)
    if admin_id:
        admin_msg = (
            "❌ Клиент отменил запись:\n"
            f"Клиент: {deleted.get('client_name', '—')}\n"
            f"Телефон: {deleted.get('phone', '—')}\n"
            f"Услуга: {deleted.get('service', '—')}\n"
            f"Дата: {deleted.get('date', '—')}\n"
            f"Время: {deleted.get('time', '—')}"
        )
        try:
            bot.send_message(admin_id, admin_msg)
        except Exception as e:
            print(f"⚠ Не удалось уведомить админа об отмене: {e}")


# ===== Admin: ручное управление слотами и записями =====
def _admin_guard(message):
    """True если admin. Иначе шлёт 'Доступ только владельцу.' и возвращает False."""
    if is_admin(message.chat.id):
        return True
    bot.send_message(message.chat.id, "Доступ только владельцу.")
    return False


def _format_slots_numbered(slots):
    if not slots:
        return "Слотов нет."
    lines = []
    for i, s in enumerate(slots, 1):
        lines.append(
            f"{i}) {s.get('date', '—')} {s.get('time', '—')} — "
            f"{s.get('service', '—')} — {s.get('status', '—')}"
        )
    return "\n".join(lines)


def _format_bookings_numbered(bookings):
    if not bookings:
        return "Записей нет."
    lines = []
    for i, b in enumerate(bookings, 1):
        lines.append(
            f"{i}) {b.get('date', '—')} {b.get('time', '—')} — "
            f"{b.get('client_name', '—')} — {b.get('service', '—')} — "
            f"{b.get('phone', '—')}"
        )
    return "\n".join(lines)


def _parse_index(text, length):
    """Парсит номер из текста. Возвращает (idx_0based, err_message_or_None)."""
    try:
        n = int((text or "").strip())
    except (TypeError, ValueError):
        return -1, "Это не число. Команда отменена."
    if n < 1 or n > length:
        return -1, f"Номер должен быть от 1 до {length}. Команда отменена."
    return n - 1, None


def _is_valid_date(text):
    try:
        datetime.strptime((text or "").strip(), "%d.%m.%Y")
        return True
    except (ValueError, TypeError):
        return False


def _is_valid_time(text):
    try:
        datetime.strptime((text or "").strip(), "%H:%M")
        return True
    except (ValueError, TypeError):
        return False


# --- /slots ---
@bot.message_handler(commands=["slots"])
def cmd_slots(message):
    if not _admin_guard(message):
        return
    bot.clear_step_handler_by_chat_id(message.chat.id)
    bot.send_message(message.chat.id, _format_slots_numbered(load_slots()))


# --- /addslot ---
@bot.message_handler(commands=["addslot"])
def cmd_addslot(message):
    if not _admin_guard(message):
        return
    bot.clear_step_handler_by_chat_id(message.chat.id)
    user_data[message.chat.id] = {}
    bot.send_message(
        message.chat.id,
        "Введите услугу (например: маникюр):",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    bot.register_next_step_handler(message, _addslot_service)


def _addslot_service(message):
    if not _admin_guard(message):
        return
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        bot.send_message(message.chat.id, "Команда отменена.")
        user_data.pop(message.chat.id, None)
        return
    user_data.setdefault(message.chat.id, {})["addslot_service"] = text
    bot.send_message(message.chat.id, "Введите дату в формате DD.MM.YYYY:")
    bot.register_next_step_handler(message, _addslot_date)


def _addslot_date(message):
    if not _admin_guard(message):
        return
    text = (message.text or "").strip()
    if not _is_valid_date(text):
        bot.send_message(message.chat.id, "Неверный формат даты. Команда отменена.")
        user_data.pop(message.chat.id, None)
        return
    user_data.setdefault(message.chat.id, {})["addslot_date"] = text
    bot.send_message(message.chat.id, "Введите время в формате HH:MM:")
    bot.register_next_step_handler(message, _addslot_time)


def _addslot_time(message):
    if not _admin_guard(message):
        return
    text = (message.text or "").strip()
    if not _is_valid_time(text):
        bot.send_message(message.chat.id, "Неверный формат времени. Команда отменена.")
        user_data.pop(message.chat.id, None)
        return
    state = user_data.get(message.chat.id, {})
    service = state.get("addslot_service", "—")
    date = state.get("addslot_date", "—")
    time = text
    slots = load_slots()
    slots.append({"date": date, "time": time, "service": service, "status": "free"})
    save_slots(slots)
    bot.send_message(
        message.chat.id,
        f"✅ Слот добавлен:\n{date} {time} — {service} — free",
    )
    user_data.pop(message.chat.id, None)


# --- /freeslot ---
@bot.message_handler(commands=["freeslot"])
def cmd_freeslot(message):
    if not _admin_guard(message):
        return
    bot.clear_step_handler_by_chat_id(message.chat.id)
    slots = load_slots()
    if not slots:
        bot.send_message(message.chat.id, "Слотов нет.")
        return
    bot.send_message(
        message.chat.id,
        _format_slots_numbered(slots) + "\n\nВведите номер слота для освобождения:",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    bot.register_next_step_handler(message, _freeslot_number)


def _freeslot_number(message):
    if not _admin_guard(message):
        return
    slots = load_slots()
    idx, err = _parse_index(message.text, len(slots))
    if err:
        bot.send_message(message.chat.id, err)
        return
    s = slots[idx]
    s["status"] = "free"
    save_slots(slots)
    bot.send_message(
        message.chat.id,
        f"✅ Слот #{idx + 1} → free:\n{s.get('date')} {s.get('time')} — {s.get('service')}",
    )


# --- /bookslot ---
@bot.message_handler(commands=["bookslot"])
def cmd_bookslot(message):
    if not _admin_guard(message):
        return
    bot.clear_step_handler_by_chat_id(message.chat.id)
    slots = load_slots()
    if not slots:
        bot.send_message(message.chat.id, "Слотов нет.")
        return
    bot.send_message(
        message.chat.id,
        _format_slots_numbered(slots) + "\n\nВведите номер слота для брони:",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    bot.register_next_step_handler(message, _bookslot_number)


def _bookslot_number(message):
    if not _admin_guard(message):
        return
    slots = load_slots()
    idx, err = _parse_index(message.text, len(slots))
    if err:
        bot.send_message(message.chat.id, err)
        return
    user_data[message.chat.id] = {"bookslot_idx": idx}
    bot.send_message(message.chat.id, "Имя клиента:")
    bot.register_next_step_handler(message, _bookslot_name)


def _bookslot_name(message):
    if not _admin_guard(message):
        return
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        bot.send_message(message.chat.id, "Имя пустое. Команда отменена.")
        user_data.pop(message.chat.id, None)
        return
    user_data.setdefault(message.chat.id, {})["bookslot_name"] = text
    bot.send_message(message.chat.id, "Телефон клиента:")
    bot.register_next_step_handler(message, _bookslot_phone)


def _bookslot_phone(message):
    if not _admin_guard(message):
        return
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        bot.send_message(message.chat.id, "Телефон пустой. Команда отменена.")
        user_data.pop(message.chat.id, None)
        return

    state = user_data.get(message.chat.id, {})
    idx = state.get("bookslot_idx")
    name = state.get("bookslot_name", "—")
    phone = text

    slots = load_slots()
    if idx is None or idx < 0 or idx >= len(slots):
        bot.send_message(message.chat.id, "Слот не найден. Команда отменена.")
        user_data.pop(message.chat.id, None)
        return
    s = slots[idx]
    s["status"] = "booked"
    save_slots(slots)

    bookings = load_bookings()
    bookings.append({
        "client_name": name,
        "service": s.get("service", "—"),
        "date": s.get("date", "—"),
        "time": s.get("time", "—"),
        "phone": phone,
        "client_chat_id": None,           # ручная запись — нет Telegram у клиента
        "client_reminder_sent": False,
    })
    save_bookings(bookings)

    bot.send_message(
        message.chat.id,
        f"✅ Слот забронирован:\n{name} — {s.get('service')} — {s.get('date')} {s.get('time')}",
    )
    user_data.pop(message.chat.id, None)


# --- /delslot ---
@bot.message_handler(commands=["delslot"])
def cmd_delslot(message):
    if not _admin_guard(message):
        return
    bot.clear_step_handler_by_chat_id(message.chat.id)
    slots = load_slots()
    if not slots:
        bot.send_message(message.chat.id, "Слотов нет.")
        return
    bot.send_message(
        message.chat.id,
        _format_slots_numbered(slots) + "\n\nВведите номер слота для удаления:",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    bot.register_next_step_handler(message, _delslot_number)


def _delslot_number(message):
    if not _admin_guard(message):
        return
    slots = load_slots()
    idx, err = _parse_index(message.text, len(slots))
    if err:
        bot.send_message(message.chat.id, err)
        return
    deleted = slots.pop(idx)
    save_slots(slots)
    bot.send_message(
        message.chat.id,
        f"✅ Слот #{idx + 1} удалён:\n{deleted.get('date')} {deleted.get('time')} — {deleted.get('service')}",
    )


# --- /delbooking ---
@bot.message_handler(commands=["delbooking"])
def cmd_delbooking(message):
    if not _admin_guard(message):
        return
    bot.clear_step_handler_by_chat_id(message.chat.id)
    bookings = load_bookings()
    if not bookings:
        bot.send_message(message.chat.id, "Записей нет.")
        return
    bot.send_message(
        message.chat.id,
        _format_bookings_numbered(bookings) + "\n\nВведите номер записи для удаления:",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    bot.register_next_step_handler(message, _delbooking_number)


def _delbooking_number(message):
    if not _admin_guard(message):
        return
    bookings = load_bookings()
    idx, err = _parse_index(message.text, len(bookings))
    if err:
        bot.send_message(message.chat.id, err)
        return
    deleted = bookings.pop(idx)
    save_bookings(bookings)

    # Если есть соответствующий 'booked' слот — освобождаем
    slots = load_slots()
    freed = False
    for s in slots:
        if (s.get("date") == deleted.get("date")
                and s.get("time") == deleted.get("time")
                and s.get("service") == deleted.get("service")
                and s.get("status") == "booked"):
            s["status"] = "free"
            freed = True
            break
    if freed:
        save_slots(slots)

    extra = " (соответствующий слот → free)" if freed else " (соответствующий слот не найден)"
    bot.send_message(
        message.chat.id,
        f"✅ Запись #{idx + 1} удалена{extra}:\n"
        f"{deleted.get('client_name')} — {deleted.get('service')} — "
        f"{deleted.get('date')} {deleted.get('time')}",
    )


# ===== Кнопки админ-панели — обёртки над существующими командами =====
def _admin_button_reject(message):
    """Не-админу шлёт отказ. True если можно продолжать."""
    if is_admin(message.chat.id):
        return True
    bot.send_message(message.chat.id, "Доступ только владельцу.")
    return False


@bot.message_handler(func=lambda m: m.text == ADMIN_BTN_TODAY)
def admin_btn_today(message):
    if _admin_button_reject(message):
        today_cmd(message)


@bot.message_handler(func=lambda m: m.text == ADMIN_BTN_ALL_BOOKINGS)
def admin_btn_all_bookings(message):
    if _admin_button_reject(message):
        bookings_cmd(message)


@bot.message_handler(func=lambda m: m.text == ADMIN_BTN_SLOTS)
def admin_btn_slots(message):
    if _admin_button_reject(message):
        cmd_slots(message)


@bot.message_handler(func=lambda m: m.text == ADMIN_BTN_ADD_SLOT)
def admin_btn_add_slot(message):
    if _admin_button_reject(message):
        cmd_addslot(message)


@bot.message_handler(func=lambda m: m.text == ADMIN_BTN_BOOK_MANUAL)
def admin_btn_book_manual(message):
    if _admin_button_reject(message):
        cmd_bookslot(message)


@bot.message_handler(func=lambda m: m.text == ADMIN_BTN_FREE_SLOT)
def admin_btn_free_slot(message):
    if _admin_button_reject(message):
        cmd_freeslot(message)


@bot.message_handler(func=lambda m: m.text == ADMIN_BTN_DEL_SLOT)
def admin_btn_del_slot(message):
    if _admin_button_reject(message):
        cmd_delslot(message)


@bot.message_handler(func=lambda m: m.text == ADMIN_BTN_DEL_BOOKING)
def admin_btn_del_booking(message):
    if _admin_button_reject(message):
        cmd_delbooking(message)


# ===== Любое непонятное сообщение — показать меню =====
@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.send_message(
        message.chat.id,
        "Выберите кнопку из меню:",
        reply_markup=main_keyboard(message.chat.id),
    )


# ===== Ежедневная напоминалка админу =====
# Время отправки. Чтобы изменить — поменять часы/минуты ниже.
DAILY_REMINDER_HOUR = 9
DAILY_REMINDER_MINUTE = 0

# Anti-spam: чтобы не слать одну и ту же напоминалку 60 раз внутри минуты.
_last_reminder_date = None


def send_today_bookings_to_admin():
    """Формирует список записей на сегодня и шлёт админу."""
    admin_id = CONFIG.get("admin_chat_id", 0)
    if not admin_id:
        print("⚠ admin_chat_id не задан — напоминалка не отправлена.")
        return
    bookings = load_bookings()
    today = today_str()
    todays = [b for b in bookings if b.get("date") == today]
    if not todays:
        text = "Сегодня записей нет."
    else:
        todays.sort(key=lambda b: b.get("time", ""))
        lines = ["📅 Записи на сегодня:"]
        for b in todays:
            lines.append(format_booking(b))
        text = "\n".join(lines)
    try:
        bot.send_message(admin_id, text)
        print(f"[reminder] sent to admin: {len(todays)} booking(s)")
    except Exception as e:
        print(f"⚠ Ошибка автоотправки админу: {e}")


def _daily_reminder_loop():
    """Каждые 60 сек смотрит время. В DAILY_REMINDER_HOUR:DAILY_REMINDER_MINUTE
    шлёт сегодняшний список (один раз в сутки)."""
    global _last_reminder_date
    while True:
        try:
            now = datetime.now()
            if (now.hour == DAILY_REMINDER_HOUR
                    and now.minute == DAILY_REMINDER_MINUTE
                    and _last_reminder_date != now.date()):
                send_today_bookings_to_admin()
                _last_reminder_date = now.date()
        except Exception as e:
            print(f"⚠ Ошибка в reminder loop: {e}")
        time.sleep(60)


# Окно отправки напоминания клиенту: за ≤2 часа до записи
TWO_HOURS = timedelta(hours=2)

# Эмодзи для известных услуг (для красивого формата напоминания)
SERVICE_EMOJI = {
    "маникюр": "💅",
    "парикмахер": "💇",
    "ремонт": "🔧",
    "услуги": "✨",
}


def _service_emoji(service):
    return SERVICE_EMOJI.get(service, "•")


def _format_delta(delta):
    """timedelta → строка вида '1 ч 30 мин' / '45 мин' / '2 часа' / '1 час'."""
    total_min = max(1, int(delta.total_seconds() // 60))
    hours = total_min // 60
    minutes = total_min % 60
    if hours == 0:
        return f"{minutes} мин"
    if minutes == 0:
        if hours == 1:
            return "1 час"
        if 2 <= hours <= 4:
            return f"{hours} часа"
        return f"{hours} часов"
    return f"{hours} ч {minutes} мин"


def send_client_reminders():
    """Шлёт клиенту напоминание за ≤2 часа до записи (один раз).
    Помечает client_reminder_sent=True, чтобы не отправлять повторно."""
    bookings = load_bookings()
    now = datetime.now()
    changed = False
    for b in bookings:
        chat_id = b.get("client_chat_id")
        if not chat_id:
            # ручная запись (client_chat_id is None) или старая без поля — пропускаем
            continue
        if b.get("client_reminder_sent"):
            continue
        # Парсим дату+время записи
        try:
            booking_dt = datetime.strptime(
                f"{b.get('date', '')} {b.get('time', '')}",
                "%d.%m.%Y %H:%M",
            )
        except (ValueError, TypeError):
            continue  # битая дата/время — пропускаем без падения цикла
        delta = booking_dt - now
        # Окно: запись в будущем и осталось не больше 2 часов
        if delta <= timedelta(0) or delta > TWO_HOURS:
            continue
        text = (
            "⏰ Напоминание:\n"
            f"У вас запись через {_format_delta(delta)}\n"
            "\n"
            f"🕐 {b.get('time', '—')}\n"
            f"{_service_emoji(b.get('service', ''))} {b.get('service', '—')}\n"
            "\n"
            "Ждём вас 🙂"
        )
        try:
            bot.send_message(chat_id, text)
            b["client_reminder_sent"] = True
            changed = True
            print(f"[client-reminder] sent to {chat_id}: {b.get('service')} {b.get('time')}")
        except Exception as e:
            print(f"⚠ Не удалось отправить напоминание клиенту {chat_id}: {e}")
    if changed:
        save_bookings(bookings)


def _client_reminder_loop():
    """Каждые 60 сек проверяет сегодняшние записи и шлёт клиентам напоминания (один раз)."""
    while True:
        try:
            send_client_reminders()
        except Exception as e:
            print(f"⚠ Ошибка в client reminder loop: {e}")
        time.sleep(60)


if __name__ == "__main__":
    print("=" * 50, flush=True)
    print("BOT STARTING", flush=True)
    print(f"Business: {CONFIG.get('business_name', '')}", flush=True)
    print("=" * 50, flush=True)

    # Если мы здесь — bootstrap прошёл, BOT_TOKEN валиден
    print(f"TOKEN EXISTS: {bool(BOT_TOKEN)}", flush=True)

    # Снять webhook, если он был установлен — иначе getUpdates ловит 409 Conflict.
    # Также drop_pending_updates=True гасит хвост сообщений от старого инстанса.
    try:
        bot.remove_webhook()
        print("WEBHOOK REMOVED", flush=True)
    except Exception as e:
        print(f"⚠ remove_webhook failed: {e}", flush=True)

    print(f"Напоминалка админу: ежедневно в {DAILY_REMINDER_HOUR:02d}:{DAILY_REMINDER_MINUTE:02d}", flush=True)

    # Фоновые потоки напоминаний
    threading.Thread(target=_daily_reminder_loop, daemon=True).start()
    threading.Thread(target=_client_reminder_loop, daemon=True).start()

    print("POLLING STARTED", flush=True)
    bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)

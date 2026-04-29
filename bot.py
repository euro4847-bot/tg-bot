import asyncio
import os
import re
import urllib.parse
from datetime import datetime, timedelta
import logging
from dotenv import load_dotenv

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================= CONFIG =================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
SHEET_ID = os.getenv("SHEET_ID")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.json")
TELEGRAM_PROXY_URL = os.getenv("TELEGRAM_PROXY_URL", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://vk-mini-booking.vercel.app/").strip()

CALENDAR_ID = "302126f7a32016f6a8b591ce17f6ac4af876b8695c9a0e5ce42c551d4374d21a@group.calendar.google.com"

WORK_START, WORK_END = 10, 22
MAX_DEVICES = 14

TARIFFS = {
    30: 490,
    60: 690,
    90: 990,
    120: 1390
}

logging.basicConfig(level=logging.INFO)

if TELEGRAM_PROXY_URL:
    logging.info("Telegram proxy is set: %s", TELEGRAM_PROXY_URL)
    bot = Bot(token=BOT_TOKEN, session=AiohttpSession(proxy=TELEGRAM_PROXY_URL))
else:
    logging.info("Telegram proxy is not set; direct connection will be used")
    bot = Bot(token=BOT_TOKEN)

dp = Dispatcher()

# ================= GOOGLE =================
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar"
]

creds = Credentials.from_service_account_file(
    CREDENTIALS_FILE,
    scopes=scope
)

gc = gspread.authorize(creds)
sheet = gc.open_by_key(SHEET_ID).sheet1
spreadsheet = gc.open_by_key(SHEET_ID)

try:
    sheet_birthday = spreadsheet.worksheet("birthday")
except:
    sheet_birthday = spreadsheet.add_worksheet(title="birthday", rows="1000", cols="20")

calendar_service = build("calendar", "v3", credentials=creds)

# ================= STATES =================
class Booking(StatesGroup):
    date = State()
    time = State()
    duration = State()
    players = State()
    name = State()
    phone = State()

class Birthday(StatesGroup):
    date = State()
    time = State()
    guests = State()
    age = State()
    name = State()
    phone = State()

class AdminBooking(StatesGroup):
    type = State()
    date = State()
    time = State()
    duration = State()
    devices = State()
    name = State()
    phone = State()
    comment = State()
    placement = State()

# ================= HELPERS =================
def valid_phone(phone):
    return bool(re.fullmatch(r"\d{11}", phone))

def generate_id():
    ids = sheet.col_values(1)[1:]  # без заголовка
    numbers = [
        int(i.replace("ZG", ""))
        for i in ids if i.startswith("ZG")
    ]
    next_id = max(numbers, default=0) + 1
    return f"ZG{next_id:05d}"

def compute_max_busy(date_str, start_dt, end_dt):
    rows = sheet.get_all_records()
    events = []

    for r in rows:
        if r.get("status") != "approved" or r.get("date") != date_str:
            continue

        r_start = datetime.strptime(
            f"{r['date']} {r['start_time']}",
            "%Y-%m-%d %H:%M"
        )
        r_end = datetime.strptime(
            f"{r['date']} {r['end_time']}",
            "%Y-%m-%d %H:%M"
        )

        if end_dt <= r_start or start_dt >= r_end:
            continue

        eff_start = max(start_dt, r_start)
        eff_end = min(end_dt, r_end)

        events.append((eff_start, int(r["devices"])))
        events.append((eff_end, -int(r["devices"])))

    sorted_events = sorted(events, key=lambda e: (e[0], 1 if e[1] < 0 else 0))

    current = 0
    max_busy = 0

    for time, delta in sorted_events:
        current += delta
        max_busy = max(max_busy, current)

    return max_busy

def is_time_available(date_str, start_dt, end_dt, devices_needed):
    max_busy = compute_max_busy(date_str, start_dt, end_dt)
    return max_busy + devices_needed <= MAX_DEVICES

def get_free_devices(date_str, start_dt, end_dt):
    max_busy = compute_max_busy(date_str, start_dt, end_dt)
    return MAX_DEVICES - max_busy

def create_calendar_event(date, start, end, devices, name, phone):
    event = {
        "summary": f"Игра {devices} устройств {name} {phone}",
        "start": {"dateTime": f"{date}T{start}:00", "timeZone": "Asia/Yekaterinburg"},
        "end": {"dateTime": f"{date}T{end}:00", "timeZone": "Asia/Yekaterinburg"},
    }

    event = calendar_service.events().insert(
        calendarId=CALENDAR_ID,
        body=event
    ).execute()

    return event["id"]

def delete_calendar_event(event_id):
    if not event_id:
        return
    try:
        calendar_service.events().delete(
            calendarId=CALENDAR_ID,
            eventId=event_id
        ).execute()
    except:
        pass

# ================= MENU =================
def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎮 Записаться через мини-аппу", web_app=WebAppInfo(url=WEBAPP_URL))
    kb.button(text="📝 Записаться в боте", callback_data="book")
    kb.button(text="🎉 День рождения", callback_data="birthday")
    kb.adjust(1)
    return kb.as_markup()

# ================= START =================
@dp.message(CommandStart())
async def start_cmd(m: Message):
    await m.answer("Добро пожаловать в VR-клуб 🎮", reply_markup=main_menu())

@dp.callback_query(F.data == "home")
async def home(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.answer("Главное меню:", reply_markup=main_menu())
    await c.answer()

# ================= BOOKING =================
@dp.callback_query(F.data == "book")
async def choose_date(c: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardBuilder()
    for i in range(7):
        d = datetime.now() + timedelta(days=i)
        kb.button(
            text=d.strftime("%d.%m"),
            callback_data=f"date_{d:%Y-%m-%d}"
        )
    kb.adjust(3)

    await c.message.answer("Выберите дату:", reply_markup=kb.as_markup())
    await state.set_state(Booking.date)
    await c.answer()

@dp.callback_query(F.data.startswith("date_"))
async def choose_time(c: CallbackQuery, state: FSMContext):
    date_str = c.data.split("_")[1]
    await state.update_data(date=date_str)

    now = datetime.now()
    kb = InlineKeyboardBuilder()

    for h in range(WORK_START, WORK_END):
        for m in [0, 30]:
            start_dt = datetime.strptime(
                f"{date_str} {h:02d}:{m:02d}",
                "%Y-%m-%d %H:%M"
            )

            if start_dt <= now:
                continue

            end_dt = start_dt + timedelta(minutes=30)

            if not is_time_available(date_str, start_dt, end_dt, 1):
                continue

            kb.button(
                text=f"{h:02d}:{m:02d}",
                callback_data=f"time_{h:02d}:{m:02d}"
            )

    kb.adjust(4)

    await c.message.answer("Выберите время:", reply_markup=kb.as_markup())
    await state.set_state(Booking.time)
    await c.answer()

@dp.callback_query(F.data.startswith("time_"))
async def choose_duration(c: CallbackQuery, state: FSMContext):
    await state.update_data(time=c.data.split("_")[1])

    kb = InlineKeyboardBuilder()
    for dur, price in TARIFFS.items():
        kb.button(
            text=f"{dur} мин — {price}₽",
            callback_data=f"dur_{dur}"
        )
    kb.adjust(2)

    await c.message.answer("Выберите тариф:", reply_markup=kb.as_markup())
    await state.set_state(Booking.duration)
    await c.answer()

@dp.callback_query(F.data.startswith("dur_"))
async def choose_players(c: CallbackQuery, state: FSMContext):
    await state.update_data(duration=int(c.data.split("_")[1]))
    await c.message.answer(f"Сколько устройств? (1–{MAX_DEVICES})")
    await state.set_state(Booking.players)
    await c.answer()

@dp.message(Booking.players)
async def get_players(m: Message, state: FSMContext):
    if not m.text.isdigit():
        await m.answer("Сколько устройств? (1–14)")
        return

    devices_requested = int(m.text)

    if devices_requested < 1 or devices_requested > MAX_DEVICES:
        await m.answer("Сколько устройств? (1–14)")
        return

    data = await state.get_data()

    start_dt = datetime.strptime(
        f"{data['date']} {data['time']}",
        "%Y-%m-%d %H:%M"
    )
    end_dt = start_dt + timedelta(minutes=data["duration"])

    free_devices = get_free_devices(
        data["date"],
        start_dt,
        end_dt
    )

    if devices_requested > free_devices:
        await m.answer(
            f"❗ Свободных устройств: {free_devices}\n\n"
            f"Сколько устройств? (1–14)"
        )
        return

    await state.update_data(devices=devices_requested)
    await m.answer("Ваше имя:")
    await state.set_state(Booking.name)

@dp.message(Booking.name)
async def get_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text)
    await m.answer("Телефон (11 цифр):")
    await state.set_state(Booking.phone)

@dp.message(Booking.phone)
async def create_request(m: Message, state: FSMContext):
    if not valid_phone(m.text):
        await m.answer("Телефон должен содержать 11 цифр")
        return

    data = await state.get_data()

    start_dt = datetime.strptime(
        f"{data['date']} {data['time']}",
        "%Y-%m-%d %H:%M"
    )
    end_dt = start_dt + timedelta(minutes=data["duration"])

    booking_id = generate_id()

    sheet.append_row([
        booking_id,
        "pending",
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        data["date"],
        data["time"],
        end_dt.strftime("%H:%M"),
        data["devices"],
        data["duration"],
        data["name"],
        m.text,
        m.from_user.id,
        "",
        "no"
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Подтвердить",
            callback_data=f"approve_{booking_id}"
        )],
        [InlineKeyboardButton(
            text="❌ Отменить",
            callback_data=f"cancel_request_{booking_id}"
        )]
    ])

    await bot.send_message(
        ADMIN_ID,
        f"🔥 Новая заявка {booking_id}\n\n"
        f"📅 {data['date']} {data['time']}\n"
        f"⏳ {data['duration']} минут\n"
        f"🎮 {data['devices']} устройств\n"
        f"👤 {data['name']}\n"
        f"📞 {m.text}",
        reply_markup=kb
    )

    await m.answer("Заявка отправлена администратору ⏳")
    await state.clear()

# ================= BIRTHDAY =================
@dp.callback_query(F.data == "birthday")
async def birthday_date(c: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardBuilder()
    for i in range(14):
        d = datetime.now() + timedelta(days=i)
        kb.button(
            text=d.strftime("%d.%m"),
            callback_data=f"bdate_{d:%Y-%m-%d}"
        )
    kb.adjust(3)

    await c.message.answer("Выберите дату праздника 🎉", reply_markup=kb.as_markup())
    await state.set_state(Birthday.date)
    await c.answer()

@dp.callback_query(F.data.startswith("bdate_"))
async def birthday_time(c: CallbackQuery, state: FSMContext):
    await state.update_data(date=c.data.split("_")[1])

    kb = InlineKeyboardBuilder()
    for h in range(WORK_START, WORK_END):
        for m in [0, 30]:
            kb.button(
                text=f"{h:02d}:{m:02d}",
                callback_data=f"btime_{h:02d}:{m:02d}"
            )
    kb.adjust(4)

    await c.message.answer("Выберите время начала:", reply_markup=kb.as_markup())
    await state.set_state(Birthday.time)
    await c.answer()

@dp.callback_query(F.data.startswith("btime_"))
async def birthday_guests(c: CallbackQuery, state: FSMContext):
    await state.update_data(time=c.data.split("_")[1])
    await c.message.answer("Сколько будет гостей?")
    await state.set_state(Birthday.guests)
    await c.answer()

@dp.message(Birthday.guests)
async def birthday_age(m: Message, state: FSMContext):
    await state.update_data(guests=m.text)
    await m.answer("Возраст именинника?")
    await state.set_state(Birthday.age)

@dp.message(Birthday.age)
async def birthday_name(m: Message, state: FSMContext):
    await state.update_data(age=m.text)
    await m.answer("Ваше имя:")
    await state.set_state(Birthday.name)

@dp.message(Birthday.name)
async def birthday_phone(m: Message, state: FSMContext):
    await state.update_data(name=m.text)
    await m.answer("Телефон (11 цифр):")
    await state.set_state(Birthday.phone)

@dp.message(Birthday.phone)
async def birthday_finish(m: Message, state: FSMContext):
    if not valid_phone(m.text):
        await m.answer("Телефон должен содержать 11 цифр")
        return

    data = await state.get_data()

    birthday_id = generate_id()

    sheet_birthday.append_row([
        birthday_id,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        data["date"],
        data["time"],
        data["guests"],
        data["age"],
        data["name"],
        m.text,
        m.from_user.id,
        "new"
    ])

    await bot.send_message(
        ADMIN_ID,
        f"🎉 Новый запрос День рождения {birthday_id}\n\n"
        f"Дата: {data['date']} {data['time']}\n"
        f"Гостей: {data['guests']}\n"
        f"Возраст: {data['age']}\n"
        f"{data['name']} {m.text}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Подробнее о тарифе",
            url="https://t.me/vr_birsk1/7"
        )],
        [InlineKeyboardButton(
            text="Список игр",
            url="https://t.me/vr_birsk1"
        )],
        [InlineKeyboardButton(
            text="🏠 На главную",
            callback_data="home"
        )]
    ])

    await m.answer(
        "Администратор свяжется с Вами в ближайшее время,\n"
        "или позвоните по номеру +7 937 477 78 37.\n\n"
        "Также вы можете ознакомиться:",
        reply_markup=kb
    )

    await state.clear()

# ================= APPROVE =================
@dp.callback_query(F.data.startswith("approve_"))
async def approve_booking(c: CallbackQuery):
    booking_id = c.data.split("_")[1]
    rows = sheet.get_all_records()

    for i, r in enumerate(rows, start=2):
        if r["ID"] != booking_id:
            continue

        start_dt = datetime.strptime(
            f"{r['date']} {r['start_time']}",
            "%Y-%m-%d %H:%M"
        )
        end_dt = datetime.strptime(
            f"{r['date']} {r['end_time']}",
            "%Y-%m-%d %H:%M"
        )

        devices_requested = int(r["devices"])

        free_devices = get_free_devices(
            r["date"],
            start_dt,
            end_dt
        )

        if devices_requested > free_devices:
            await c.answer(
                f"Свободных устройств: {free_devices}",
                show_alert=True
            )
            return

        sheet.update_cell(i, 2, "approved")

        event_id = create_calendar_event(
            r["date"],
            r["start_time"],
            r["end_time"],
            r["devices"],
            r["name"],
            r["phone"]
        )

        sheet.update_cell(i, 12, event_id)

        duration = int(r["duration"])
        devices = int(r["devices"])
        price = TARIFFS.get(duration, 0) * devices

        formatted_date = datetime.strptime(
            r["date"], "%Y-%m-%d"
        ).strftime("%d.%m.%Y")

        client_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🎮 Игры",
                url="https://t.me/vr_birsk1"
            )],
            [InlineKeyboardButton(
                text="❌ Отменить запись",
                callback_data=f"client_cancel_{booking_id}"
            )],
            [InlineKeyboardButton(
                text="🏠 На главную",
                callback_data="home"
            )]
        ])

    if r["tg_id"]:
        await bot.send_message(
            r["tg_id"],
            f"✅ Запись подтверждена!\n\n"
            f"💰 Сумма: {price}₽\n"
            f"🆔 Номер: {booking_id}\n"
            f"📅 {formatted_date} {r['start_time']}",
            reply_markup=client_kb
        )

        await c.message.edit_text(
            f"✅ Запись {booking_id} подтверждена"
        )

        await c.answer("Подтверждено")
        return

    await c.answer("Заявка не найдена", show_alert=True)

# ================= CLIENT CANCEL =================
@dp.callback_query(F.data.startswith("client_cancel_"))
async def client_cancel(c: CallbackQuery):
    booking_id = c.data.replace("client_cancel_", "")
    rows = sheet.get_all_values()

    for row in rows[1:]:
        if row[0] == booking_id:
            formatted_date = datetime.strptime(
                row[3], "%Y-%m-%d"
            ).strftime("%d.%m.%Y")

            text = (
                f"❗ Клиент хочет отменить запись {booking_id}\n\n"
                f"📅 {formatted_date} {row[4]}\n"
                f"⏳ {row[7]} минут\n"
                f"🎮 {row[6]} устройств\n"
                f"👤 {row[8]}\n"
                f"📞 {row[9]}"
            )

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="❌ Подтвердить отмену",
                    callback_data=f"cancel_{booking_id}"
                )],
                [InlineKeyboardButton(
                    text="↩ Оставить запись",
                    callback_data=f"cancel_back_{booking_id}"
                )]
            ])

            await bot.send_message(ADMIN_ID, text, reply_markup=kb)

            await c.message.edit_text(
                "⏳ Заявка на отмену отправлена администратору"
            )

            await c.answer()
            return

# ================= CANCEL REQUEST =================
@dp.callback_query(F.data.startswith("cancel_request_"))
async def show_cancel_confirm(c: CallbackQuery):
    booking_id = c.data.replace("cancel_request_", "")

    new_text = (
        c.message.text +
        "\n\n⚠️ Вы уверены, что хотите отменить запись?"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="❌ Подтвердить отмену",
            callback_data=f"cancel_{booking_id}"
        )],
        [InlineKeyboardButton(
            text="↩ Оставить запись",
            callback_data=f"cancel_back_{booking_id}"
        )]
    ])

    await c.message.edit_text(new_text, reply_markup=kb)
    await c.answer()

# ================= CANCEL BACK =================
@dp.callback_query(F.data.startswith("cancel_back_"))
async def cancel_back(c: CallbackQuery):
    booking_id = c.data.replace("cancel_back_", "")
    rows = sheet.get_all_records()

    for r in rows:
        if r["ID"] == booking_id:
            formatted_date = datetime.strptime(
                r["date"], "%Y-%m-%d"
            ).strftime("%d.%m.%Y")

            text = (
                f"🔥 Новая заявка {booking_id}\n\n"
                f"📅 {formatted_date} {r['start_time']}\n"
                f"⏳ {r['duration']} минут\n"
                f"🎮 {r['devices']} устройств\n"
                f"👤 {r['name']}\n"
                f"📞 {r['phone']}"
            )

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"approve_{booking_id}"
                )],
                [InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=f"cancel_request_{booking_id}"
                )]
            ])

            await c.message.edit_text(text, reply_markup=kb)
            await c.answer("Запись сохранена")
            return

# ================= FINAL CANCEL =================
@dp.callback_query(
    F.data.startswith("cancel_") &
    ~F.data.startswith("cancel_back_")
)
async def confirm_cancel(c: CallbackQuery):
    booking_id = c.data.replace("cancel_", "")
    rows = sheet.get_all_records()

    for i, r in enumerate(rows, start=2):
        if r["ID"] == booking_id:
            sheet.update_cell(i, 2, "cancelled")

            formatted_date = datetime.strptime(
                r["date"], "%Y-%m-%d"
            ).strftime("%d.%m.%Y")

            event_id = sheet.cell(i, 12).value
            delete_calendar_event(event_id)

            await c.message.edit_text(
                f"❌ Запись {booking_id} отменена\n\n"
                f"📅 {formatted_date} {r['start_time']}\n"
                f"👤 {r['name']}\n"
                f"📞 {r['phone']}"
            )

            support_text = f"Здравствуйте, хочу уточнить по записи №{booking_id}"
            encoded_text = urllib.parse.quote(support_text)

            client_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="✍️ Написать в поддержку",
                    url=f"https://t.me/vrbirsksupport?text={encoded_text}"
                )],
                [InlineKeyboardButton(
                    text="🏠 На главную",
                    callback_data="home"
                )]
            ])

            await bot.send_message(
                r["tg_id"],
                f"❌ Ваша запись {booking_id} на "
                f"{formatted_date} {r['start_time']} была отменена.\n\n"
                f"Если это ошибка — свяжитесь с администратором.",
                reply_markup=client_kb
            )

            await c.answer("Отменено")
            return

    await c.answer("Ошибка отмены", show_alert=True)

# ================= REMINDER LOOP =================
async def reminder_loop():
    while True:
        rows = sheet.get_all_records()
        now = datetime.now()

        for i, r in enumerate(rows, start=2):
            if r.get("status") != "approved" or r.get("reminded") == "yes":
                continue

            booking_time = datetime.strptime(
                f"{r['date']} {r['start_time']}",
                "%Y-%m-%d %H:%M"
            )

            diff = (booking_time - now).total_seconds()

            if 0 < diff <= 3600:
                await bot.send_message(
                    r["tg_id"],
                    f"Напоминаем! Ваша запись {r['ID']} через 1 час 🎮"
                )
                sheet.update_cell(i, 13, "yes")

        await asyncio.sleep(600)

# ================= RUN =================
async def main():
    await bot.delete_webhook(drop_pending_updates=True)

    asyncio.create_task(reminder_loop())

    await dp.start_polling(
        bot,
        skip_updates=True
    )

if __name__ == "__main__":
    asyncio.run(main())
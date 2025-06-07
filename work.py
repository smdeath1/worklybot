import sqlite3
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.filters import Command, CommandStart

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация бота
BOT_TOKEN = "7957098235:AAEI6XTZ_zZBMYViaJDymUZ-HFhXhyZtoew"
ADMIN_ID = 8143784621
ADMIN_USERNAME = "belovdanila"

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Состояния пользователей
user_states = {}  # {telegram_id: {"step": str, "city": str (опционально)}}
user_edit_states = {}  # Для редактирования вакансий
vacancy_states = {}  # Для навигации по вакансиям {telegram_id: {"current_index": int, "vacancy_list": list}}

# Инициализация базы данных
def init_db():
    try:
        with sqlite3.connect("jobs.db", check_same_thread=False) as conn:
            cur = conn.cursor()
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    employer_code TEXT UNIQUE,
                    subscription_active INTEGER DEFAULT 0,
                    subscription_start TEXT
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS vacancies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employer_code TEXT,
                    city TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (employer_code) REFERENCES users(employer_code)
                )
            ''')
            cur.execute("SELECT COUNT(*) FROM users WHERE telegram_id = ?", (ADMIN_ID,))
            if cur.fetchone()[0] == 0:
                cur.execute(
                    "INSERT INTO users (telegram_id, employer_code, subscription_active, subscription_start) "
                    "VALUES (?, ?, ?, ?)",
                    (ADMIN_ID, "EMP_ADMIN", 1, datetime.now().strftime("%Y-%m-%d"))
                )
                cur.execute(
                    "INSERT INTO vacancies (employer_code, city, description) VALUES (?, ?, ?)",
                    ("EMP_ADMIN", "Москва", "Требуется разработчик Python")
                )
            conn.commit()
            logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации базы: {e}")
        raise

# Получение активной клавиатуры для работодателя
def get_employer_keyboard():
    kb = ReplyKeyboardBuilder()
    kb.button(text="Разместить вакансию")
    kb.button(text="Мои вакансии")
    kb.button(text="Подписка")
    return kb.as_markup(resize_keyboard=True)

# Получение начальной клавиатуры
def get_start_keyboard():
    kb = ReplyKeyboardBuilder()
    kb.button(text="Я работодатель")
    kb.button(text="Ищу работу")
    return kb.as_markup(resize_keyboard=True)

# /start
@dp.message(CommandStart())
async def cmd_start(message: Message):
    uid = message.from_user.id
    logger.info(f"Пользователь {uid} запустил бота")
    await message.answer("👋 Привет! Выберите роль:", reply_markup=get_start_keyboard())

# Регистрация работодателя
@dp.message(lambda message: message.text == "Я работодатель")
async def employer_start(message: Message):
    try:
        uid = message.from_user.id
        with sqlite3.connect("jobs.db", check_same_thread=False) as conn:
            cur = conn.cursor()
            cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (uid,))
            row = cur.fetchone()
            if not row:
                employer_code = f"EMP{uid}"
                cur.execute(
                    "INSERT INTO users (telegram_id, employer_code, subscription_active) VALUES (?, ?, ?)",(uid, employer_code, 0)
                )
                conn.commit()
            else:
                employer_code = row[0]
        kb = ReplyKeyboardBuilder()
        kb.button(text="Оплатил")
        await message.answer(
            f"✅ Ваш код: <b>{employer_code}</b>\n📩 Свяжитесь с @{ADMIN_USERNAME} для оплаты.\n"
            f"Нажмите <b>Оплатил</b> после оплаты.",
            reply_markup=kb.as_markup(resize_keyboard=True)
        )
    except Exception as e:
        logger.error(f"Ошибка в employer_start: {e}")
        await message.answer("❌ Ошибка. Попробуйте позже.")

# Проверка оплаты
@dp.message(lambda message: message.text == "Оплатил")
async def check_payment(message: Message):
    try:
        uid = message.from_user.id
        with sqlite3.connect("jobs.db", check_same_thread=False) as conn:
            cur = conn.cursor()
            cur.execute("SELECT subscription_active, subscription_start FROM users WHERE telegram_id = ?", (uid,))
            row = cur.fetchone()
            if row and row[0] == 1 and row[1]:
                start_date = datetime.strptime(row[1], "%Y-%m-%d")
                if datetime.now() - start_date <= timedelta(days=30):
                    user_states[uid] = {"step": "employer_menu"}
                    await message.answer("✅ Подписка активна!", reply_markup=get_employer_keyboard())
                    return
            await message.answer("❌ Оплата не подтверждена. Свяжитесь с админом.")
    except Exception as e:
        logger.error(f"Ошибка в check_payment: {e}")
        await message.answer("❌ Ошибка. Попробуйте позже.")

# Размещение вакансии
@dp.message(lambda message: message.text == "Разместить вакансию")
async def add_vacancy(message: Message):
    try:
        uid = message.from_user.id
        with sqlite3.connect("jobs.db", check_same_thread=False) as conn:
            cur = conn.cursor()
            cur.execute("SELECT subscription_active, subscription_start FROM users WHERE telegram_id = ?", (uid,))
            user = cur.fetchone()
            if not user or user[0] != 1 or not user[1] or (datetime.now() - datetime.strptime(user[1], "%Y-%m-%d")).days > 30:
                await message.answer("❌ Подписка не активна.", reply_markup=get_employer_keyboard())
                return
        user_states[uid] = {"step": "city"}
        await message.answer("Введите город:")
    except Exception as e:
        logger.error(f"Ошибка в add_vacancy: {e}")
        await message.answer("❌ Ошибка. Попробуйте позже.")

# Просмотр вакансий
@dp.message(lambda message: message.text == "Мои вакансии")
async def my_vacancies(message: Message):
    try:
        uid = message.from_user.id
        with sqlite3.connect("jobs.db", check_same_thread=False) as conn:
            cur = conn.cursor()
            cur.execute("SELECT employer_code, subscription_active, subscription_start FROM users WHERE telegram_id = ?", (uid,))
            user = cur.fetchone()
            if not user:
                await message.answer("❌ Вы не работодатель.", reply_markup=get_start_keyboard())
                return
            if user[1] != 1 or not user[2] or (datetime.now() - datetime.strptime(user[2], "%Y-%m-%d")).days > 30:
                await message.answer("❌ Нет доступа. Активируйте подписку.", reply_markup=get_start_keyboard())
                return
            cur.execute("SELECT id, description FROM vacancies WHERE employer_code = ?", (user[0],))
            vacancies = cur.fetchall()
            if not vacancies:
                await message.answer("📭 У вас нет вакансий.", reply_markup=get_employer_keyboard())
                return
        vacancy_states[uid] = {"current_index": 0, "vacancy_list": vacancies}
        vid, desc = vacancies[0]
        kb = ReplyKeyboardBuilder()
        kb.button(text="⬅️ Назад")
        kb.button(text="Редактировать")
        kb.button(text="Удалить")
        kb.button(text="➡️ Вперед")
        await message.answer(f"<b>Вакансия #{vid}:</b>\n{desc}", reply_markup=kb.as_markup(resize_keyboard=True))
    except Exception as e:
        logger.error(f"Ошибка в my_vacancies: {e}")
        await message.answer("❌ Ошибка. Попробуйте позже.")

# Навигация и действия с вакансиями
@dp.message(lambda message: message.text in ["⬅️ Назад", "➡️ Вперед", "Редактировать", "Удалить"])
async def handle_vacancy_actions(message: Message):
    try:
        uid = message.from_user.id
        if uid not in vacancy_states:
            await message.answer("❌ Нет активных вакансий для просмотра.", reply_markup=get_employer_keyboard())
            return
        state = vacancy_states[uid]
        current_index = state["current_index"]
        vacancies = state["vacancy_list"]
        vid, desc = vacancies[current_index]
        text = message.text
        kb = ReplyKeyboardBuilder()
        kb.button(text="⬅️ Назад")
        kb.button(text="Редактировать")
        kb.button(text="Удалить")
        kb.button(text="➡️ Вперед")

        if text == "⬅️ Назад":
            if current_index > 0:
                state["current_index"] -= 1
                vid, desc = vacancies[state["current_index"]]
            else:
                await message.answer(f"<b>Вакансия #{vid}:</b>\n{desc}\nЭто первая.", reply_markup=kb.as_markup(resize_keyboard=True))
                return
        elif text == "➡️ Вперед":
            if current_index < len(vacancies) - 1:
                state["current_index"] += 1
                vid, desc = vacancies[state["current_index"]]
            else:
                await message.answer(f"<b>Вакансия #{vid}:</b>\n{desc}\nЭто последняя.", reply_markup=kb.as_markup(resize_keyboard=True))
                return
        elif text == "Редактировать":
            user_edit_states[uid] = vid
            vacancy_states.pop(uid, None)
            await message.answer(f"Введите новое описание для #{vid}:")
            return
        elif text == "Удалить":
            with sqlite3.connect("jobs.db", check_same_thread=False) as conn:
                cur = conn.cursor()
                cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (uid,))
                employer_code = cur.fetchone()[0]
                cur.execute("DELETE FROM vacancies WHERE id = ? AND employer_code = ?", (vid, employer_code))
                if cur.rowcount == 0:
                    await message.answer("❌ Вакансия не найдена.", reply_markup=get_employer_keyboard())
                    return
                conn.commit()
                vacancies.pop(current_index)
                if not vacancies:
                    vacancy_states.pop(uid, None)
                    await message.answer(f"✅ #{vid} удалена. Нет вакансий.", reply_markup=get_employer_keyboard())
                    return
                if current_index >= len(vacancies):
                    state["current_index"] = len(vacancies) - 1
                vid, desc = vacancies[state["current_index"]]
        await message.answer(f"<b>Вакансия #{vid}:</b>\n{desc}", reply_markup=kb.as_markup(resize_keyboard=True))
    except Exception as e:
        logger.error(f"Ошибка в handle_vacancy_actions: {e}")
        await message.answer("❌ Ошибка. Попробуйте позже.")

# Обработка ввода
@dp.message()
async def handle_input(message: Message):
    try:
        uid = message.from_user.id
        text = message.text.strip()
        logger.info(f"Обработка ввода для user {uid}: {text}")

        # Ищу работу
        if text == "Ищу работу":
            user_states[uid] = {"step": "worker_city"}
            logger.info(f"User {uid} начал поиск работы")
            await message.answer("Введите город для поиска:")
            return

        # Редактирование вакансии
        if uid in user_edit_states:
            vid = user_edit_states.pop(uid)
            new_desc = text
            with sqlite3.connect("jobs.db", check_same_thread=False) as conn:
                cur = conn.cursor()
                cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (uid,))
                employer_code = cur.fetchone()[0]
                cur.execute(
                "UPDATE vacancies SET description = ? WHERE id = ? AND employer_code = ?",
                    (new_desc, vid, employer_code)
                )
                if cur.rowcount == 0:
                    await message.answer("❌ Вакансия не найдена.", reply_markup=get_employer_keyboard())
                    return
                conn.commit()
            await message.answer(f"✅ #{vid} обновлена.", reply_markup=get_employer_keyboard())
            return

        # Добавление вакансии
        if uid in user_states and user_states[uid].get("step") == "city":
            if not text:
                await message.answer("❌ Город не может быть пустым. Введите город:")
                return
            user_states[uid]["city"] = text
            user_states[uid]["step"] = "desc"
            await message.answer("Введите описание:")
            return
        elif uid in user_states and user_states[uid].get("step") == "desc":
            if not text:
                await message.answer("❌ Описание не может быть пустым. Введите описание:")
                return
            city = user_states[uid]["city"]
            desc = text
            with sqlite3.connect("jobs.db", check_same_thread=False) as conn:
                cur = conn.cursor()
                cur.execute("SELECT employer_code FROM users WHERE telegram_id = ?", (uid,))
                employer_code = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO vacancies (employer_code, city, description) VALUES (?, ?, ?)",
                    (employer_code, city, desc)
                )
                conn.commit()
            user_states.pop(uid, None)
            await message.answer("✅ Вакансия добавлена.", reply_markup=get_employer_keyboard())
            return

        # Поиск работы
        if uid in user_states and user_states[uid].get("step") == "worker_city":
            city = text
            logger.info(f"Поиск вакансий для user {uid} в городе {city}")
            with sqlite3.connect("jobs.db", check_same_thread=False) as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, description FROM vacancies WHERE city LIKE ?", (f"%{city}%",))
                rows = cur.fetchall()
                if not rows:
                    await message.answer("📭 Нет вакансий в этом городе.", reply_markup=get_start_keyboard())
                else:
                    response = "<b>Вакансии:</b>\n"
                    for vid, desc in rows:
                        response += f"#{vid}: {desc[:50] + '...' if len(desc) > 50 else desc}\n"
                    await message.answer(response, reply_markup=get_start_keyboard())
            user_states.pop(uid, None)
            return

        # Статус подписки
        if text == "Подписка":
            logger.info(f"Проверка подписки для user {uid}")
            with sqlite3.connect("jobs.db", check_same_thread=False) as conn:
                cur = conn.cursor()
                cur.execute("SELECT subscription_active, subscription_start FROM users WHERE telegram_id = ?", (uid,))
                row = cur.fetchone()
                if not row or not row[0] or not row[1]:
                    await message.answer("📅 Подписка не активна.", reply_markup=get_employer_keyboard())
                else:
                    start = datetime.strptime(row[1], "%Y-%m-%d")
                    days_left = 30 - (datetime.now() - start).days
                    await message.answer(f"⏳ Осталось: {max(0, days_left)} дней.", reply_markup=get_employer_keyboard())
            return

        # Неизвестная команда
        logger.info(f"Неизвестная команда для user {uid}: {text}")
        if uid in user_states and user_states[uid].get("step") == "employer_menu":
            await message.answer("❌ Неверная команда.", reply_markup=get_employer_keyboard())
        else:
            await message.answer("❌ Неверная команда.", reply_markup=get_start_keyboard())

    except Exception as e:
        logger.error(f"Ошибка в handle_input: {e}")
        await message.answer("❌ Ошибка.Попробуйте позже.")

# Команда /pay для админа
@dp.message(Command("pay"))
async def admin_confirm_payment(message: Message):
    try:
        if message.from_user.id != ADMIN_ID:
            await message.answer("❌ У вас нет прав на эту команду.")
            return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("❌ Использование: /pay <employer_code>")
            return

        employer_code = args[1].strip()
        with sqlite3.connect("jobs.db", check_same_thread=False) as conn:
            cur = conn.cursor()
            cur.execute("SELECT telegram_id FROM users WHERE employer_code = ?", (employer_code,))
            row = cur.fetchone()
            if not row:
                await message.answer("❌ Работодатель не найден.")
                return
            cur.execute(
                "UPDATE users SET subscription_active = 1, subscription_start = ? WHERE employer_code = ?",
                (datetime.now().strftime("%Y-%m-%d"), employer_code)
            )
            conn.commit()
        await message.answer(f"✅ Подписка для {employer_code} активирована.")
    except Exception as e:
        logger.error(f"Ошибка в admin_confirm_payment: {e}")
        await message.answer("❌ Ошибка при подтверждении оплаты.")

# Запуск бота
if __name__ == "__main__":
    init_db()
    dp.run_polling(bot)

import psycopg2
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.filters import Command
import os

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация бота
BOT_TOKEN = os.getenv("BOT_TOKEN", "7957098235:AAEI6XTZ_zZBMYViaJDymUZ-HFhXhyZtoew")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8143784621"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "belovdanila")

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Состояния пользователей
user_states = {}  # {telegram_id: {"step": str, "city": str (опционально)}}
user_edit_states = {}  # Для редактирования вакансий
vacancy_states = {}  # Для навигации по вакансиям {telegram_id: {"current_index": int, "vacancy_list": list}}

# Инициализация базы данных (PostgreSQL)
def init_db():
    try:
        conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY,
                employer_code TEXT UNIQUE,
                subscription_active BOOLEAN DEFAULT FALSE,
                subscription_start DATE
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vacancies (
                id SERIAL PRIMARY KEY,
                employer_code TEXT,
                city TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (employer_code) REFERENCES users(employer_code)
            );
        """)
        cur.execute("SELECT COUNT(*) FROM users WHERE telegram_id = %s", (ADMIN_ID,))
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO users (telegram_id, employer_code, subscription_active, subscription_start) VALUES (%s, %s, %s, %s)",
                (ADMIN_ID, "EMP_ADMIN", True, datetime.now().strftime("%Y-%m-%d"))
            )
            cur.execute(
                "INSERT INTO vacancies (employer_code, city, description) VALUES (%s, %s, %s)",
                ("EMP_ADMIN", "Москва", "Требуется разработчик Python")
            )
        conn.commit()
        cur.close()
        conn.close()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации базы: {e}")
        raise

# /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    uid = message.from_user.id
    kb = ReplyKeyboardBuilder()
    kb.button(text="Я работодатель")
    kb.button(text="Ищу работу")
    await message.answer("👋 Привет! Выберите роль:", reply_markup=kb.as_markup(resize_keyboard=True))

# Регистрация работодателя
@dp.message(F.text == "Я работодатель")
async def employer_start(message: Message):
    try:
        uid = message.from_user.id
        conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
        cur = conn.cursor()
        cur.execute("SELECT employer_code FROM users WHERE telegram_id = %s", (uid,))
        row = cur.fetchone()
        if not row:
            employer_code = f"EMP{uid}"
            cur.execute(
                "INSERT INTO users (telegram_id, employer_code, subscription_active) VALUES (%s, %s, %s)",
                (uid, employer_code, False)
            )
            conn.commit()
        else:
            employer_code = row[0]
        cur.close()
        conn.close()
        kb = ReplyKeyboardBuilder()
        kb.button(text="Оплатил")
        await message.answer(
            f"✅ Ваш код: <b>{employer_code}</b>\n📩 Перейти для оплаты. Свяжитесь с @{ADMIN_USERNAME} после оплаты.\nНажмите <b>Оплатил</b> после оплаты.",
            reply_markup=kb.as_markup(resize_keyboard=True)
        )
    except Exception as e:
        logger.error(f"Ошибка в employer_start: {e}")
        await message.answer("❌ Ошибка. Попробуйте позже.")

# Проверка оплаты
@dp.message(F.text == "Оплатил")
async def check_payment(message: Message):
    try:
        uid = message.from_user.id
        conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
        cur = conn.cursor()
        cur.execute("SELECT subscription_active, subscription_start FROM users WHERE telegram_id = %s", (uid,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0] and row[1]:
            start_date = datetime.strptime(row[1], "%Y-%m-%d")
            if datetime.now() - start_date <= timedelta(days=30):
                kb = ReplyKeyboardBuilder()
                kb.button(text="Разместить вакансию")
                kb.button(text="Мои вакансии")
                kb.button(text="Подписка")
                await message.answer("✅ Подписка активна!", reply_markup=kb.as_markup(resize_keyboard=True))
                user_states[uid] = {"step": "employer_menu"}
                return
            await message.answer("❌ Оплата не подтверждена. Свяжитесь с админом.")
    except Exception as e:
        logger.error(f"Ошибка в check_payment: {e}")
        await message.answer("❌ Ошибка. Попробуйте позже.")

# Размещение вакансии
@dp.message(F.text == "Разместить вакансию")
async def add_vacancy(message: Message):
    try:
        uid = message.from_user.id
        conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
        cur = conn.cursor()
        cur.execute("SELECT subscription_active, subscription_start FROM users WHERE telegram_id = %s", (uid,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if not user or not user[0] or not user[1] or (datetime.now() - datetime.strptime(user[1], "%Y-%m-%d")).days > 30:
            await message.answer("❌ Подписка не активна.")
            return
        user_states[uid] = {"step": "city"}
        await message.answer("Введите город:")
    except Exception as e:
        logger.error(f"Ошибка в add_vacancy: {e}")
        await message.answer("❌ Ошибка. Попробуйте позже.")

# Просмотр вакансий
@dp.message(F.text == "Мои вакансии")
async def my_vacancies(message: Message):
    try:
        uid = message.from_user.id
        conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
        cur = conn.cursor()
        cur.execute("SELECT employer_code, subscription_active, subscription_start FROM users WHERE telegram_id = %s", (uid,))
        user = cur.fetchone()
        if not user:
            cur.close()
            conn.close()
            await message.answer("❌ Вы не работодатель.")
            return
        if not user[1] or not user[2] or (datetime.now() - datetime.strptime(user[2], "%Y-%m-%d")).days > 30:
            cur.close()
            conn.close()
            await message.answer("❌ Нет доступа. Активируйте подписку.")
            return
        cur.execute("SELECT id, description FROM vacancies WHERE employer_code = %s", (user[0],))
        vacancies = cur.fetchall()
        cur.close()
        conn.close()
        if not vacancies:
            await message.answer("📭 У вас нет вакансий.")
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
@dp.message(F.text.in_(["⬅️ Назад", "➡️ Вперед", "Редактировать", "Удалить"]))
async def handle_vacancy_actions(message: Message):
    try:
        uid = message.from_user.id
        if uid not in vacancy_states:
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
            conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
            cur = conn.cursor()
            cur.execute("SELECT employer_code FROM users WHERE telegram_id = %s", (uid,))
            employer_code = cur.fetchone()[0]
            cur.execute("DELETE FROM vacancies WHERE id = %s AND employer_code = %s", (vid, employer_code))
            if cur.rowcount == 0:
                cur.close()
                conn.close()
                await message.answer("❌ Вакансия не найдена.")
                return
            conn.commit()
            cur.close()
            conn.close()
            vacancies.pop(current_index)
            if not vacancies:
                vacancy_states.pop(uid, None)
                kb = ReplyKeyboardBuilder()
                kb.button(text="Разместить вакансию")
                kb.button(text="Мои вакансии")
                kb.button(text="Подписка")
                await message.answer(f"✅ #{vid} удалена. Нет вакансий.", reply_markup=kb.as_markup(resize_keyboard=True))
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

        # Редактирование
        if uid in user_edit_states:
            vid = user_edit_states.pop(uid)
            new_desc = text
            conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
            cur = conn.cursor()
            cur.execute("SELECT employer_code FROM users WHERE telegram_id = %s", (uid,))
            employer_code = cur.fetchone()[0]
            cur.execute("UPDATE vacancies SET description = %s WHERE id = %s AND employer_code = %s", (new_desc, vid, employer_code))
            if cur.rowcount == 0:
                cur.close()
                conn.close()
                await message.answer("❌ Вакансия не найдена.")
                return
            conn.commit()
            cur.close()
            conn.close()
            kb = ReplyKeyboardBuilder()
            kb.button(text="Мои вакансии")
            kb.button(text="Разместить вакансию")
            kb.button(text="Подписка")
            await message.answer(f"✅ #{vid} обновлена.", reply_markup=kb.as_markup(resize_keyboard=True))
            return
        # Добавление вакансии
        if uid in user_states and user_states[uid].get("step") == "city":
            user_states[uid]["city"] = text
            user_states[uid]["step"] = "desc"
            await message.answer("Введите описание:")
            return
        elif uid in user_states and user_states[uid].get("step") == "desc":
            city = user_states[uid]["city"]
            desc = text
            conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
            cur = conn.cursor()
            cur.execute("SELECT employer_code FROM users WHERE telegram_id = %s", (uid,))
            employer_code = cur.fetchone()[0]
            cur.execute("INSERT INTO vacancies (employer_code, city, description) VALUES (%s, %s, %s)", (employer_code, city, desc))
            conn.commit()
            cur.close()
            conn.close()
            user_states.pop(uid, None)
            kb = ReplyKeyboardBuilder()
            kb.button(text="Мои вакансии")
            kb.button(text="Разместить вакансию")
            kb.button(text="Подписка")
            await message.answer("✅ Вакансия добавлена.", reply_markup=kb.as_markup(resize_keyboard=True))
            return

        # Поиск работы
        if uid in user_states and user_states[uid].get("step") == "worker_city":
            city = text
            logger.info(f"Поиск вакансий для user {uid} в городе {city}")
            conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
            cur = conn.cursor()
            cur.execute("SELECT id, description FROM vacancies WHERE city ILIKE %s", (f"%{city}%",))
            rows = cur.fetchall()
            cur.close()
            conn.close()
            if not rows:
                await message.answer("📭 Нет вакансий в этом городе.")
            else:
                response = "<b>Вакансии:</b>\n"
                for vid, desc in rows:
                    response += f"#{vid}: {desc[:50] + '...' if len(desc) > 50 else desc}\n"
                await message.answer(response)
            user_states.pop(uid, None)
            kb = ReplyKeyboardBuilder()
            kb.button(text="Я работодатель")
            kb.button(text="Ищу работу")
            await message.answer("🔍 Поиск завершен. Выберите действие:", reply_markup=kb.as_markup(resize_keyboard=True))
            return

        # Статус подписки
        if text == "Подписка":
            logger.info(f"Проверка подписки для user {uid}")
            conn = psycopg2.connect(os.getenv("DATABASE_URL"), sslmode="require")
            cur = conn.cursor()
            cur.execute("SELECT subscription_active, subscription_start FROM users WHERE telegram_id = %s", (uid,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if not row or not row[0] or not row[1]:
                await message.answer("📅 Подписка не активна.")
            else:
                start = datetime.strptime(row[1], "%Y-%m-%d")
                days_left = 30 - (datetime.now() - start).days
                await message.answer(f"⏳ Осталось: {max(0, days_left)} дней.")
            kb = ReplyKeyboardBuilder()
            kb.button(text="Мои вакансии")
            kb.button(text="Разместить вакансию")
            kb.button(text="Подписка")
            await message.answer("Выберите действие:", reply_markup=kb.as_markup(resize_keyboard=True))
            return

        # Неизвестная команда
        logger.info(f"Неизвестная команда для user {uid}: {text}")
        kb = ReplyKeyboardBuilder()
        if uid in user_states and user_states[uid].get("step") == "employer_menu":
            kb.button(text="Мои вакансии")
            kb.button(text="Разместить вакансию")
            kb.button(text="Подписка")
        else:
            kb.button(text="Я работодатель")
            kb.button(text="Ищу работу")
        await message.answer("❌ Неверная команда.", reply_markup=kb.as_markup(resize_keyboard=True))

    except Exception as e:
        logger.error(f"Ошибка в handle_input: {e}")
        await message.answer("❌ Ошибка. Попробуйте позже.")

# Запуск бота
if __name__ == "__main__":
    init_db()
    dp.run_polling(bot)

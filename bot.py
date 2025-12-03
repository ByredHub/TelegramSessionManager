import asyncio
import logging
import warnings
import json
import time
import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
from telegram.error import TimedOut, NetworkError, RetryAfter, TelegramError
from telegram_automation import TelegramAutomation
import os
from dotenv import load_dotenv

# Подавляем предупреждение о per_message для CallbackQueryHandler
warnings.filterwarnings("ignore", message=".*per_message.*CallbackQueryHandler.*")
warnings.filterwarnings("ignore", category=UserWarning, module="telegram.ext._conversationhandler")
warnings.filterwarnings("ignore", category=UserWarning, module="telegram.ext")

# Загружаем переменные окружения (с обработкой ошибок)
try:
    load_dotenv()
except Exception as e:
    logging.warning(f"Не удалось загрузить .env файл: {e}. Продолжаем работу...")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
WAITING_PHONE, WAITING_CODE, WAITING_CLOUD_PASSWORD = range(3)

# Глобальный объект автоматизации
automation = TelegramAutomation()

# Путь к папке сессий
SESSIONS_DIR = "sessions"

# Защита от блокировки: Rate limiting (более строгие лимиты для безопасности)
user_requests = defaultdict(list)  # История запросов пользователей
user_blocked = {}  # Заблокированные пользователи
user_daily_logins = defaultdict(int)  # Количество входов в день
user_last_login_date = {}  # Дата последнего входа

# Строгие лимиты для защиты от блокировки Telegram
MAX_REQUESTS_PER_MINUTE = 5  # Максимум запросов в минуту (снижено для безопасности)
MAX_REQUESTS_PER_HOUR = 20  # Максимум запросов в час (снижено для безопасности)
MAX_LOGINS_PER_DAY = 3  # Максимум попыток входа в день на пользователя
BLOCK_DURATION = 3600  # Время блокировки в секундах (1 час)

# Задержки для имитации человеческого поведения
MIN_DELAY = 1.0  # Минимальная задержка между действиями (секунды)
MAX_DELAY = 3.0  # Максимальная задержка между действиями (секунды)


def save_session(user_id: int, data: dict):
    """Сохраняет сессию пользователя (отключено - сессии не сохраняются)"""
    # Сессии не сохраняются по запросу пользователя
    logger.debug(f"Сохранение сессии отключено для пользователя {user_id}")


def load_session(user_id: int) -> dict:
    """Загружает сессию пользователя (отключено - сессии не сохраняются)"""
    # Сессии не загружаются, так как не сохраняются
    return {}


def clear_session(user_id: int):
    """Удаляет сессию пользователя (отключено - сессии не сохраняются)"""
    # Сессии не удаляются, так как не сохраняются
    logger.debug(f"Удаление сессии отключено для пользователя {user_id}")


def get_human_delay() -> float:
    """Возвращает случайную задержку для имитации человеческого поведения"""
    return random.uniform(MIN_DELAY, MAX_DELAY)


async def human_delay():
    """Выполняет задержку для имитации человеческого поведения"""
    delay = get_human_delay()
    await asyncio.sleep(delay)


def check_rate_limit(user_id: int, is_login_attempt: bool = False) -> Tuple[bool, str]:
    """
    Проверяет rate limit для пользователя с защитой от блокировки аккаунта
    
    Args:
        user_id: ID пользователя
        is_login_attempt: True если это попытка входа (более строгие лимиты)
    
    Returns:
        (allowed, message) - разрешено ли действие и сообщение об ошибке
    """
    current_time = time.time()
    current_date = datetime.now().date()
    
    # Проверяем, не заблокирован ли пользователь
    if user_id in user_blocked:
        block_until = user_blocked[user_id]
        if current_time < block_until:
            remaining = int(block_until - current_time)
            return False, f"⏳ Вы временно заблокированы. Попробуйте через {remaining // 60} минут."
        else:
            # Блокировка истекла
            del user_blocked[user_id]
    
    # Проверяем лимит попыток входа в день
    if is_login_attempt:
        # Сбрасываем счетчик, если новый день
        if user_id in user_last_login_date and user_last_login_date[user_id] != current_date:
            user_daily_logins[user_id] = 0
        
        if user_daily_logins.get(user_id, 0) >= MAX_LOGINS_PER_DAY:
            return False, (
                f"⚠️ Превышен лимит попыток входа ({MAX_LOGINS_PER_DAY} в день).\n"
                "Это ограничение для защиты вашего аккаунта от блокировки Telegram.\n"
                "Попробуйте завтра."
            )
        
        # Обновляем дату и счетчик
        user_last_login_date[user_id] = current_date
        user_daily_logins[user_id] = user_daily_logins.get(user_id, 0) + 1
    
    # Очищаем старые запросы (старше часа)
    if user_id in user_requests:
        user_requests[user_id] = [
            req_time for req_time in user_requests[user_id]
            if current_time - req_time < 3600
        ]
    
    # Проверяем лимит в минуту (более строгий для попыток входа)
    minute_ago = current_time - 60
    recent_requests = [
        req_time for req_time in user_requests.get(user_id, [])
        if req_time > minute_ago
    ]
    
    max_per_minute = MAX_REQUESTS_PER_MINUTE // 2 if is_login_attempt else MAX_REQUESTS_PER_MINUTE
    
    if len(recent_requests) >= max_per_minute:
        # Блокируем пользователя
        user_blocked[user_id] = current_time + BLOCK_DURATION
        return False, (
            "⏳ Слишком много запросов.\n"
            "Это ограничение защищает ваш аккаунт от блокировки Telegram.\n"
            "Вы заблокированы на 1 час."
        )
    
    # Проверяем лимит в час
    hour_ago = current_time - 3600
    hourly_requests = [
        req_time for req_time in user_requests.get(user_id, [])
        if req_time > hour_ago
    ]
    
    max_per_hour = MAX_REQUESTS_PER_HOUR // 2 if is_login_attempt else MAX_REQUESTS_PER_HOUR
    
    if len(hourly_requests) >= max_per_hour:
        # Блокируем пользователя
        user_blocked[user_id] = current_time + BLOCK_DURATION
        return False, (
            "⏳ Превышен лимит запросов в час.\n"
            "Это ограничение защищает ваш аккаунт от блокировки Telegram.\n"
            "Вы заблокированы на 1 час."
        )
    
    # Добавляем текущий запрос
    user_requests[user_id].append(current_time)
    return True, ""


async def safe_reply_with_rate_limit(update: Update, text: str, max_retries: int = 3, reply_markup=None) -> bool:
    """Безопасная отправка сообщения с rate limiting и обработкой ошибок"""
    user_id = update.effective_user.id if update.effective_user else None
    
    # Проверяем rate limit
    if user_id:
        allowed, error_msg = check_rate_limit(user_id)
        if not allowed:
            try:
                if hasattr(update, 'message') and update.message:
                    await update.message.reply_text(error_msg)
                elif hasattr(update, 'callback_query') and update.callback_query:
                    await update.callback_query.answer(error_msg, show_alert=True)
            except:
                pass
            return False
    
    # Отправляем сообщение с обработкой ошибок
    return await safe_reply(update, text, max_retries, reply_markup)


async def safe_reply(update: Update, text: str, max_retries: int = 3, reply_markup=None) -> bool:
    """Безопасная отправка сообщения с повторными попытками"""
    for attempt in range(max_retries):
        try:
            if hasattr(update, 'message') and update.message:
                await update.message.reply_text(text, reply_markup=reply_markup)
            elif hasattr(update, 'callback_query') and update.callback_query:
                # Для callback_query используем edit_message_text
                await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
            return True
        except (TimedOut, NetworkError) as e:
            if attempt < max_retries - 1:
                logger.warning(f"Таймаут при отправке сообщения (попытка {attempt + 1}/{max_retries}), повтор...")
                await asyncio.sleep(1)
            else:
                logger.error(f"Не удалось отправить сообщение после {max_retries} попыток: {e}")
                return False
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения: {e}")
            return False
    return False


def create_code_keyboard(current_code: str = "") -> InlineKeyboardMarkup:
    """Создает клавиатуру для ввода кода"""
    # Кнопки с цифрами (3 ряда по 3 кнопки + 0 внизу)
    keyboard = []
    
    # Первый ряд: 1, 2, 3
    row1 = [
        InlineKeyboardButton("1", callback_data="code_1"),
        InlineKeyboardButton("2", callback_data="code_2"),
        InlineKeyboardButton("3", callback_data="code_3")
    ]
    keyboard.append(row1)
    
    # Второй ряд: 4, 5, 6
    row2 = [
        InlineKeyboardButton("4", callback_data="code_4"),
        InlineKeyboardButton("5", callback_data="code_5"),
        InlineKeyboardButton("6", callback_data="code_6")
    ]
    keyboard.append(row2)
    
    # Третий ряд: 7, 8, 9
    row3 = [
        InlineKeyboardButton("7", callback_data="code_7"),
        InlineKeyboardButton("8", callback_data="code_8"),
        InlineKeyboardButton("9", callback_data="code_9")
    ]
    keyboard.append(row3)
    
    # Четвертый ряд: 0, Удалить, Очистить
    row4 = [
        InlineKeyboardButton("0", callback_data="code_0"),
        InlineKeyboardButton("⌫ Удалить", callback_data="code_delete"),
        InlineKeyboardButton("🗑 Очистить", callback_data="code_clear")
    ]
    keyboard.append(row4)
    
    # Пятый ряд: Отправить (если код полный)
    if len(current_code) == 5:
        row5 = [InlineKeyboardButton("✅ Отправить", callback_data="code_send")]
        keyboard.append(row5)
    
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /start"""
    # Добавляем задержку для имитации человеческого поведения
    await human_delay()
    
    # Проверяем rate limit
    user_id = update.effective_user.id if update.effective_user else None
    if user_id:
        allowed, error_msg = check_rate_limit(user_id)
        if not allowed:
            await safe_reply(update, error_msg)
            return ConversationHandler.END
    
    # Проверяем, авторизован ли уже Telegram Desktop
    try:
        is_authorized = automation.check_if_authorized()
        if is_authorized:
            await safe_reply(
                update,
                "✅ Telegram Desktop уже авторизован!\n"
                "🎉 Используется существующая сессия.\n\n"
                "💡 Если нужно войти в другой аккаунт, сначала выйди из текущего в Telegram Desktop."
            )
            return ConversationHandler.END
    except Exception as e:
        logger.warning(f"Ошибка при проверке авторизации: {e}")
        # Продолжаем как обычно, если проверка не удалась
    
    await safe_reply(
        update,
        "👋 Привет! Я помогу тебе войти в Telegram Desktop/Portable.\n\n"
        "📱 Отправь мне номер телефона в формате: +79991234567\n\n"
        "⚠️ Внимание: Используйте бота осторожно. Telegram может заблокировать аккаунт "
        "при частых автоматизированных входах. Рекомендуется не более 2-3 попыток в день."
    )
    return WAITING_PHONE


async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик номера телефона"""
    # Добавляем задержку для имитации человеческого поведения
    await human_delay()
    
    phone = update.message.text.strip()
    
    # Простая валидация номера
    if not phone.startswith('+') or len(phone) < 10:
        await safe_reply(
            update,
            "❌ Неверный формат номера. Пожалуйста, отправь номер в формате: +79991234567"
        )
        return WAITING_PHONE
    
    # Проверяем, авторизован ли уже Telegram Desktop
    try:
        is_authorized = automation.check_if_authorized()
        if is_authorized:
            await safe_reply(
                update,
                "✅ Telegram Desktop уже авторизован!\n"
                "🎉 Используется существующая сессия.\n"
                "💡 Если нужно войти в другой аккаунт, сначала выйди из текущего."
            )
            # Очищаем данные
            context.user_data.clear()
            return ConversationHandler.END
    except Exception as e:
        logger.warning(f"Ошибка при проверке авторизации: {e}")
        # Продолжаем как обычно, если проверка не удалась
    
    # Проверяем rate limit для попытки входа (более строгие лимиты)
    user_id = update.effective_user.id if update.effective_user else None
    if user_id:
        allowed, error_msg = check_rate_limit(user_id, is_login_attempt=True)
        if not allowed:
            await safe_reply(update, error_msg)
            return WAITING_PHONE
    
    await safe_reply(
        update,
        f"📱 Получен номер: {phone}\n"
        "⏳ Ввожу номер в Telegram Desktop/Portable...\n"
        "💡 Убедись, что Telegram Desktop/Portable открыт и находится на экране входа.\n\n"
        "⚠️ Защита: Добавлена задержка для безопасности вашего аккаунта."
    )
    
    # Добавляем дополнительную задержку перед вводом номера
    await human_delay()
    
    # Сохраняем номер в контексте
    context.user_data['phone'] = phone
    
    # Сессии не сохраняются (отключено по запросу пользователя)
    
    try:
        # Вводим номер в Telegram
        success = automation.enter_phone_number(phone)
        
        if success:
            # Инициализируем код в контексте
            context.user_data['code'] = ""
            
            keyboard = create_code_keyboard("")
            await safe_reply(
                update,
                "✅ Номер введен!\n"
                "📨 Ожидаю подтверждение...\n"
                "🔢 Используй кнопки ниже:",
                reply_markup=keyboard
            )
            return WAITING_CODE
        else:
            await safe_reply(
                update,
                "❌ Не удалось ввести номер. Убедись, что:\n"
                "1. Telegram Desktop/Portable открыт\n"
                "2. Окно находится на экране входа\n"
                "3. Окно активно (в фокусе)\n\n"
                "Попробуй еще раз, отправив номер:"
            )
            return WAITING_PHONE
    except Exception as e:
        logger.error(f"Ошибка при вводе номера: {e}")
        await safe_reply(
            update,
            f"❌ Произошла ошибка: {str(e)}\n"
            "Попробуй еще раз, отправив номер:"
        )
        return WAITING_PHONE


async def handle_code_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик нажатий на кнопки ввода кода"""
    query = update.callback_query
    await query.answer()
    
    # Получаем текущий код из контекста
    current_code = context.user_data.get('code', '')
    
    # Обрабатываем нажатие
    if query.data == "code_send":
        # Отправляем код
        if len(current_code) == 5:
            await query.edit_message_text(
                f"🔢 {current_code}\n"
                "⏳ Обрабатываю..."
            )
            
            try:
                # Добавляем задержку перед вводом кода (имитация человеческого поведения)
                await human_delay()
                
                # Вводим код в Telegram
                success = automation.enter_code(current_code)
                
                if success:
                    # Проверяем, требуется ли облачный пароль
                    # Используем случайную задержку вместо фиксированной
                    delay = get_human_delay() + 1.0  # Дополнительная задержка
                    await asyncio.sleep(delay)
                    needs_password = automation.check_cloud_password_needed()
                    
                    if needs_password:
                        await query.edit_message_text(
                            "✅ Готово!\n"
                            "🔐 Требуется дополнительная проверка.\n"
                            "📝 Отправь данные:"
                        )
                        return WAITING_CLOUD_PASSWORD
                    else:
                        await query.edit_message_text(
                            "✅ Готово!\n"
                            "🎉 Проверь Telegram Desktop/Portable."
                        )
                        # Очищаем данные пользователя и сессию
                        user_id = update.effective_user.id if hasattr(update, 'effective_user') else None
                        if user_id:
                            clear_session(user_id)
                        context.user_data.clear()
                        return ConversationHandler.END
                else:
                    keyboard = create_code_keyboard(current_code)
                    await query.edit_message_text(
                        "❌ Не удалось выполнить. Убедись, что:\n"
                        "1. Telegram Desktop/Portable открыт\n"
                        "2. Окно активно\n\n"
                        f"🔢 {current_code or '(пусто)'}\n"
                        "Попробуй еще раз:",
                        reply_markup=keyboard
                    )
                    return WAITING_CODE
            except Exception as e:
                logger.error(f"Ошибка при вводе кода: {e}")
                keyboard = create_code_keyboard(current_code)
                await query.edit_message_text(
                    f"❌ Произошла ошибка: {str(e)}\n"
                    f"🔢 Текущий код: {current_code or '(пусто)'}\n"
                    "Попробуй еще раз:",
                    reply_markup=keyboard
                )
                return WAITING_CODE
        else:
            # Код не полный
            keyboard = create_code_keyboard(current_code)
            await query.edit_message_text(
                f"❌ Нужно 5 цифр.\n"
                f"🔢 {current_code or '(пусто)'}\n"
                "Введи еще:",
                reply_markup=keyboard
            )
            return WAITING_CODE
    
    elif query.data == "code_delete":
        # Удаляем последнюю цифру
        if current_code:
            current_code = current_code[:-1]
            context.user_data['code'] = current_code
    elif query.data == "code_clear":
        # Очищаем весь код
        current_code = ""
        context.user_data['code'] = current_code
    elif query.data.startswith("code_"):
        # Добавляем цифру
        digit = query.data.split("_")[1]
        if len(current_code) < 5:
            current_code += digit
            context.user_data['code'] = current_code
    
    # Если код полный, автоматически отправляем
    if len(current_code) == 5:
        await query.edit_message_text(
            f"🔢 {current_code}\n"
            "⏳ Обрабатываю..."
        )
        
        try:
            # Вводим код в Telegram
            success = automation.enter_code(current_code)
            
            if success:
                # Проверяем, требуется ли облачный пароль (ждем немного и проверяем окно)
                await asyncio.sleep(2)  # Даем время для появления запроса пароля
                needs_password = automation.check_cloud_password_needed()
                
                if needs_password:
                    await query.edit_message_text(
                        "✅ Готово!\n"
                        "🔐 Требуется дополнительная проверка.\n"
                        "📝 Отправь данные:"
                    )
                    return WAITING_CLOUD_PASSWORD
                else:
                    await query.edit_message_text(
                        "✅ Готово!\n"
                        "🎉 Проверь Telegram Desktop/Portable."
                    )
                    # Очищаем данные пользователя
                    context.user_data.clear()
                    return ConversationHandler.END
            else:
                keyboard = create_code_keyboard(current_code)
                await query.edit_message_text(
                    "❌ Не удалось выполнить. Убедись, что:\n"
                    "1. Telegram Desktop/Portable открыт\n"
                    "2. Окно активно\n\n"
                    f"🔢 {current_code}\n"
                    "Попробуй еще раз:",
                    reply_markup=keyboard
                )
                return WAITING_CODE
        except Exception as e:
            logger.error(f"Ошибка при вводе кода: {e}")
            keyboard = create_code_keyboard(current_code)
            await query.edit_message_text(
                f"❌ Произошла ошибка: {str(e)}\n"
                f"🔢 {current_code}\n"
                "Попробуй еще раз:",
                reply_markup=keyboard
            )
            return WAITING_CODE
    
    # Обновляем клавиатуру
    keyboard = create_code_keyboard(current_code)
    
    # Формируем текст сообщения
    code_display = current_code if current_code else "(пусто)"
    dots = "•" * (5 - len(current_code))
    full_display = current_code + dots if len(current_code) < 5 else current_code
    
    message_text = (
        "📨 Введи цифры:\n\n"
        f"🔢 `{full_display}`\n\n"
    )
    
    if len(current_code) == 5:
        message_text += "✅ Готово! Отправляю..."
    else:
        message_text += f"Осталось: {5 - len(current_code)}"
    
    await query.edit_message_text(
        message_text,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    
    return WAITING_CODE


async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик кода подтверждения (текстовый ввод для обратной совместимости)"""
    code = update.message.text.strip()
    
    # Валидация кода (обычно 5 цифр)
    if not code.isdigit() or len(code) != 5:
        keyboard = create_code_keyboard("")
        await safe_reply(
            update,
            "❌ Нужно 5 цифр.\n"
            "🔢 Используй кнопки ниже:",
            reply_markup=keyboard
        )
        return WAITING_CODE
    
    await safe_reply(
        update,
        f"🔢 {code}\n"
        "⏳ Обрабатываю..."
    )
    
    try:
        # Добавляем задержку перед вводом кода (имитация человеческого поведения)
        await human_delay()
        
        # Вводим код в Telegram
        success = automation.enter_code(code)
        
        if success:
            # Проверяем, требуется ли облачный пароль
            # Используем случайную задержку вместо фиксированной
            delay = get_human_delay() + 1.0  # Дополнительная задержка
            await asyncio.sleep(delay)
            needs_password = automation.check_cloud_password_needed()
            
            if needs_password:
                await safe_reply(
                    update,
                    "✅ Готово!\n"
                    "🔐 Требуется дополнительная проверка.\n"
                    "📝 Отправь данные:"
                )
                return WAITING_CLOUD_PASSWORD
            else:
                await safe_reply(
                    update,
                    "✅ Готово!\n"
                    "🎉 Проверь Telegram Desktop/Portable."
                )
                # Очищаем данные пользователя
                context.user_data.clear()
                return ConversationHandler.END
        else:
            keyboard = create_code_keyboard("")
            await safe_reply(
                update,
                "❌ Не удалось выполнить. Убедись, что:\n"
                "1. Telegram Desktop/Portable открыт\n"
                "2. Окно активно\n\n"
                "Попробуй еще раз:",
                reply_markup=keyboard
            )
            return WAITING_CODE
    except Exception as e:
        logger.error(f"Ошибка при вводе кода: {e}")
        keyboard = create_code_keyboard("")
        await safe_reply(
            update,
            f"❌ Произошла ошибка: {str(e)}\n"
            "Попробуй еще раз:",
            reply_markup=keyboard
        )
        return WAITING_CODE


async def handle_cloud_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик облачного пароля"""
    password = update.message.text.strip()
    
    if not password:
        await safe_reply(
            update,
            "❌ Не может быть пустым. Отправь данные:"
        )
        return WAITING_CLOUD_PASSWORD
    
    await safe_reply(
        update,
        f"🔐 Получено.\n"
        "⏳ Обрабатываю..."
    )
    
    try:
        # Вводим пароль в Telegram
        success = automation.enter_cloud_password(password)
        
        if success:
            await safe_reply(
                update,
                "✅ Готово!\n"
                "🎉 Проверь Telegram Desktop/Portable."
            )
            # Очищаем данные пользователя и сессию
            user_id = update.effective_user.id if hasattr(update, 'effective_user') else None
            if user_id:
                clear_session(user_id)
            context.user_data.clear()
            return ConversationHandler.END
        else:
            await safe_reply(
                update,
                "❌ Не удалось выполнить. Убедись, что:\n"
                "1. Telegram Desktop/Portable открыт\n"
                "2. Окно активно\n\n"
                "Попробуй еще раз:"
            )
            return WAITING_CLOUD_PASSWORD
    except Exception as e:
        logger.error(f"Ошибка при вводе пароля: {e}")
        await safe_reply(
            update,
            f"❌ Произошла ошибка: {str(e)}\n"
            "Попробуй отправить пароль еще раз:"
        )
        return WAITING_CLOUD_PASSWORD


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена операции"""
    await safe_reply(update, "❌ Операция отменена.")
    context.user_data.clear()
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок"""
    error = context.error
    
    # Игнорируем таймауты - они обрабатываются в safe_reply
    if isinstance(error, (TimedOut, NetworkError)):
        logger.warning(f"Таймаут или сетевая ошибка: {error}")
        return
    
    logger.error(f"Exception while handling an update: {error}", exc_info=error)
    
    # Если это конфликт (другой экземпляр бота запущен)
    if isinstance(error, Exception) and "Conflict" in str(error):
        logger.error("⚠️ Другой экземпляр бота уже запущен! Остановите все запущенные процессы бота.")
    
    # Пытаемся отправить сообщение об ошибке пользователю (если есть update)
    if update and hasattr(update, 'message') and update.message:
        try:
            await update.message.reply_text(
                "❌ Произошла ошибка при обработке запроса. Попробуй еще раз или отправь /start"
            )
        except:
            pass  # Игнорируем ошибки при отправке сообщения об ошибке


def main():
    """Запуск бота"""
    # Сессии не сохраняются (отключено по запросу пользователя)
    
    # Получаем токен из переменных окружения
    token = os.getenv('BOT_TOKEN')
    
    if not token:
        logger.error("BOT_TOKEN не найден в переменных окружения!")
        print("❌ Ошибка: Создай файл .env и добавь туда BOT_TOKEN=твой_токен_бота")
        return
    
    # Создаем приложение с увеличенными таймаутами и защитой от блокировки
    application = (
        Application.builder()
        .token(token)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )
    
    # Создаем ConversationHandler для управления диалогом
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)],
            WAITING_CODE: [
                CallbackQueryHandler(handle_code_button, pattern="^code_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code)
            ],
            WAITING_CLOUD_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cloud_password)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_chat=True,  # Отслеживание по чату
        per_user=True,  # Отслеживание по пользователю
    )
    
    # Добавляем обработчики
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    
    # Запускаем бота
    logger.info("Бот запущен...")
    print("✅ Бот запущен! Нажми Ctrl+C для остановки.")
    
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True  # Игнорируем старые обновления
        )
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
        print("\n👋 Бот остановлен.")
    except Exception as e:
        if "Conflict" in str(e):
            logger.error("⚠️ Конфликт: другой экземпляр бота уже запущен!")
            print("\n❌ Ошибка: Другой экземпляр бота уже запущен!")
            print("💡 Решение: Остановите все запущенные процессы Python или перезапустите компьютер.")
        else:
            logger.error(f"Критическая ошибка: {e}")
            print(f"\n❌ Критическая ошибка: {e}")


if __name__ == '__main__':
    main()


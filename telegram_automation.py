import pyautogui
import pywinauto
import time
import logging
import psutil
from pywinauto import Application

logger = logging.getLogger(__name__)

# Настройка pyautogui с защитой от блокировки
import random
pyautogui.PAUSE = random.uniform(0.2, 0.5)  # Случайная пауза для имитации человеческого поведения
pyautogui.FAILSAFE = True  # Безопасность: перемещение мыши в угол экрана прервет выполнение


class TelegramAutomation:
    """Класс для автоматизации ввода в Telegram Desktop/Portable"""
    
    def __init__(self):
        self.telegram_window = None
        self.is_authorized = None  # Кэш статуса авторизации
        # Не ищем окно при инициализации, будем искать когда нужно
    
    def find_telegram_window(self):
        """Поиск окна Telegram Desktop/Portable"""
        try:
            # Список возможных имен процессов Telegram
            telegram_processes = ["Telegram.exe", "Telegram", "telegram"]
            
            # Сначала ищем по процессу
            for proc_name in telegram_processes:
                try:
                    # Ищем процесс
                    for proc in psutil.process_iter(['pid', 'name']):
                        try:
                            if proc.info['name'] and proc_name.lower() in proc.info['name'].lower():
                                pid = proc.info['pid']
                                logger.info(f"Найден процесс Telegram: {proc.info['name']} (PID: {pid})")
                                
                                # Пробуем подключиться через uia
                                try:
                                    app = Application(backend="uia").connect(process=pid)
                                    self.telegram_window = app.top_window()
                                    logger.info("Окно Telegram найдено по PID (uia)")
                                    return True
                                except Exception as e:
                                    logger.debug(f"Не удалось подключиться через uia (PID {pid}): {e}")
                                
                                # Пробуем через win32
                                try:
                                    app = Application(backend="win32").connect(process=pid)
                                    self.telegram_window = app.top_window()
                                    logger.info("Окно Telegram найдено по PID (win32)")
                                    return True
                                except Exception as e:
                                    logger.debug(f"Не удалось подключиться через win32 (PID {pid}): {e}")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                except Exception as e:
                    logger.debug(f"Ошибка при поиске процесса {proc_name}: {e}")
            
            # Пробуем найти по заголовку окна (разные варианты)
            title_patterns = [".*Telegram.*", "Telegram", "Telegram Desktop"]
            
            for pattern in title_patterns:
                try:
                    app = Application(backend="uia").connect(title_re=pattern)
                    windows = app.windows()
                    if windows:
                        # Берем первое видимое окно
                        for win in windows:
                            try:
                                if win.is_visible():
                                    self.telegram_window = win
                                    logger.info(f"Окно Telegram найдено по заголовку '{pattern}' (uia)")
                                    return True
                            except:
                                continue
                except Exception as e:
                    logger.debug(f"Не удалось найти через uia с паттерном '{pattern}': {e}")
                
                try:
                    app = Application(backend="win32").connect(title_re=pattern)
                    windows = app.windows()
                    if windows:
                        for win in windows:
                            try:
                                if win.is_visible():
                                    self.telegram_window = win
                                    logger.info(f"Окно Telegram найдено по заголовку '{pattern}' (win32)")
                                    return True
                            except:
                                continue
                except Exception as e:
                    logger.debug(f"Не удалось найти через win32 с паттерном '{pattern}': {e}")
            
            logger.warning("Не удалось найти окно Telegram. Убедитесь, что Telegram Desktop/Portable запущен и видим.")
            return False
        except Exception as e:
            logger.warning(f"Ошибка при поиске окна Telegram: {e}")
            return False
    
    def activate_window(self):
        """Активация окна Telegram"""
        try:
            # Если окно не найдено, пробуем найти
            if not self.telegram_window:
                if not self.find_telegram_window():
                    # Если не удалось найти через pywinauto, пробуем активировать через Alt+Tab
                    logger.info("Пробуем активировать Telegram через Alt+Tab...")
                    try:
                        pyautogui.hotkey('alt', 'tab')
                        time.sleep(0.5)
                        # Пробуем найти окно еще раз после переключения
                        if self.find_telegram_window():
                            return True
                        # Если все равно не нашли, но переключились - продолжаем
                        logger.info("Переключение выполнено, продолжаем без pywinauto")
                        return True
                    except Exception as e:
                        logger.warning(f"Не удалось переключиться через Alt+Tab: {e}")
                    return False
            
            if self.telegram_window:
                try:
                    self.telegram_window.set_focus()
                    time.sleep(0.5)
                    return True
                except Exception as e:
                    logger.warning(f"Не удалось активировать окно, пробуем найти заново: {e}")
                    # Пробуем найти окно заново
                    if self.find_telegram_window():
                        try:
                            self.telegram_window.set_focus()
                            time.sleep(0.5)
                            return True
                        except:
                            # Если не удалось активировать, но окно найдено - продолжаем
                            logger.info("Окно найдено, но не удалось активировать через set_focus, продолжаем")
                            return True
            return False
        except Exception as e:
            logger.error(f"Ошибка при активации окна: {e}")
            return False
    
    def enter_phone_number(self, phone: str) -> bool:
        """
        Ввод номера телефона в Telegram Desktop/Portable
        
        Args:
            phone: Номер телефона в формате +79991234567
            
        Returns:
            True если успешно, False в противном случае
        """
        try:
            # Парсим номер: извлекаем код страны и сам номер
            # Формат: +79991234567 -> код: +7, номер: 9991234567
            if not phone.startswith('+'):
                logger.error("Номер должен начинаться с +")
                return False
            
            # Извлекаем код страны (обычно 1-3 цифры после +)
            country_code = ""
            phone_number = ""
            
            # Определяем длину кода страны (обычно 1-3 цифры)
            # Россия: +7, США: +1, Казахстан: +7, и т.д.
            if phone.startswith('+7'):
                # Россия или Казахстан
                country_code = "+7"
                phone_number = phone[2:]  # Все после +7
            elif phone.startswith('+1'):
                # США или Канада
                country_code = "+1"
                phone_number = phone[2:]
            else:
                # Для других стран пробуем определить код страны
                # Обычно код страны 1-3 цифры
                for i in range(1, min(4, len(phone))):
                    if phone[i].isdigit():
                        continue
                    else:
                        country_code = phone[:i]
                        phone_number = phone[i:]
                        break
                else:
                    # Если все цифры, пробуем стандартные коды
                    if len(phone) > 3:
                        country_code = phone[:2]  # По умолчанию 2 цифры
                        phone_number = phone[2:]
                    else:
                        logger.error("Не удалось определить код страны")
                        return False
            
            logger.info(f"Код страны: {country_code}, Номер: {phone_number}")
            
            # Пробуем активировать окно (но продолжаем даже если не удалось)
            self.activate_window()
            
            time.sleep(1)  # Даем время окну активироваться
            
            # Пробуем найти поля ввода через pywinauto
            try:
                if self.telegram_window:
                    # Ищем все поля ввода (Edit controls)
                    edit_controls = self.telegram_window.descendants(control_type="Edit")
                    
                    # Также ищем ComboBox для выбора страны
                    combobox_controls = self.telegram_window.descendants(control_type="ComboBox")
                    
                    if len(edit_controls) >= 2:
                        # Первое поле - код страны, второе - номер
                        country_field = edit_controls[0]
                        phone_field = edit_controls[1]
                        
                        # Сначала работаем с полем кода страны
                        country_field.set_focus()
                        time.sleep(0.5)
                        
                        # Очищаем поле кода страны
                        country_field.set_text("")
                        time.sleep(0.3)
                        
                        # Вводим код страны (только цифры, без +)
                        country_code_digits = country_code.replace('+', '')
                        country_field.type_keys(country_code_digits, with_spaces=False)
                        time.sleep(0.5)
                        
                        # Если есть ComboBox, пробуем выбрать страну
                        if combobox_controls:
                            try:
                                combobox = combobox_controls[0]
                                combobox.set_focus()
                                time.sleep(0.3)
                                # Пробуем ввести код страны для поиска
                                combobox.type_keys(country_code_digits, with_spaces=False)
                                time.sleep(0.5)
                                # Нажимаем Enter для выбора
                                pyautogui.press('enter')
                                time.sleep(0.3)
                            except Exception as e:
                                logger.debug(f"Не удалось использовать ComboBox: {e}")
                        
                        # Переходим в поле номера (Tab или клик)
                        phone_field.set_focus()
                        time.sleep(0.5)
                        
                        # Очищаем поле номера
                        phone_field.set_text("")
                        time.sleep(0.3)
                        
                        # Вводим номер
                        phone_field.type_keys(phone_number, with_spaces=False)
                        time.sleep(0.3)
                        
                        # Нажимаем Enter для подтверждения
                        pyautogui.press('enter')
                        time.sleep(0.5)
                        
                        logger.info(f"Номер {phone} введен через pywinauto (код: {country_code}, номер: {phone_number})")
                        return True
                    elif len(edit_controls) == 1:
                        # Только одно поле - пробуем ввести весь номер
                        phone_field = edit_controls[0]
                        phone_field.set_focus()
                        time.sleep(0.3)
                        phone_field.set_text("")
                        time.sleep(0.2)
                        phone_field.type_keys(phone, with_spaces=False)
                        logger.info(f"Номер {phone} введен через pywinauto (одно поле)")
                        return True
            except Exception as e:
                logger.warning(f"Не удалось ввести через pywinauto: {e}")
            
            # Альтернативный способ через pyautogui
            # В Telegram Desktop есть два поля: код страны и номер
            try:
                # Если окно найдено, используем его координаты
                if self.telegram_window:
                    try:
                        window_rect = self.telegram_window.rectangle()
                        # Поле кода страны обычно слева, выше (примерно 1/4 ширины, 1/3 высоты)
                        country_x = window_rect.left + (window_rect.width() // 4)
                        country_y = window_rect.top + (window_rect.height() // 3)
                        # Поле номера обычно справа, на той же высоте или чуть ниже
                        phone_x = window_rect.left + (window_rect.width() // 2)
                        phone_y = window_rect.top + (window_rect.height() // 3) + 30  # Чуть ниже
                    except:
                        # Если не удалось получить координаты, используем центр экрана
                        screen_width, screen_height = pyautogui.size()
                        country_x = screen_width // 3
                        country_y = screen_height // 3
                        phone_x = screen_width // 2
                        phone_y = screen_height // 3 + 30
                else:
                    # Если окно не найдено, используем центр экрана
                    screen_width, screen_height = pyautogui.size()
                    country_x = screen_width // 3
                    country_y = screen_height // 3
                    phone_x = screen_width // 2
                    phone_y = screen_height // 3 + 30
                
                # Шаг 1: Кликаем в поле кода страны (или выпадающий список)
                pyautogui.click(country_x, country_y, duration=0.1)  # Быстрый клик
                time.sleep(0.4)  # Уменьшенная задержка
                
                # Очищаем поле кода страны
                pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.1)
                pyautogui.press('delete')
                time.sleep(0.1)
                
                # Вводим код страны (только цифры, без +)
                country_code_digits = country_code.replace('+', '')
                pyautogui.write(country_code_digits, interval=0.05)  # Быстрее
                time.sleep(0.3)
                
                # Если открылся выпадающий список, нажимаем Enter для выбора
                pyautogui.press('enter')
                time.sleep(0.3)
                
                # Шаг 2: Переходим в поле номера (Tab или клик)
                # Сначала пробуем Tab (быстрее чем клик)
                pyautogui.press('tab')
                time.sleep(0.2)
                
                # Очищаем поле номера
                pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.1)
                pyautogui.press('delete')
                time.sleep(0.1)
                
                # Вводим номер (без кода страны)
                pyautogui.write(phone_number, interval=0.05)  # Быстрее
                time.sleep(0.3)
                
                # Нажимаем Enter для подтверждения и получения кода
                pyautogui.press('enter')
                time.sleep(0.5)
                
                logger.info(f"Номер {phone} введен через pyautogui (код: {country_code}, номер: {phone_number})")
                return True
                
            except Exception as e:
                logger.error(f"Ошибка при вводе через pyautogui: {e}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при вводе номера: {e}")
            return False
    
    def _click_continue_button(self):
        """Поиск и нажатие кнопки 'Продолжить' в Telegram Desktop"""
        try:
            time.sleep(0.5)  # Даем время для появления кнопки
            
            # Пробуем найти кнопку через pywinauto
            if self.telegram_window:
                try:
                    # Ищем кнопку по тексту
                    buttons = self.telegram_window.descendants(control_type="Button")
                    for button in buttons:
                        try:
                            button_text = button.window_text().lower()
                            # Ищем кнопку с текстом "продолжить", "continue", "next" и т.д.
                            if any(word in button_text for word in ["продолжить", "continue", "next", "далее"]):
                                button.click()
                                logger.info("Кнопка 'Продолжить' нажата через pywinauto")
                                time.sleep(1)
                                return True
                        except:
                            continue
                    
                    # Если не нашли по тексту, пробуем найти синюю кнопку (обычно это кнопка продолжения)
                    # Или просто первую активную кнопку
                    for button in buttons:
                        try:
                            if button.is_enabled():
                                button.click()
                                logger.info("Кнопка продолжения нажата (первая активная)")
                                time.sleep(1)
                                return True
                        except:
                            continue
                except Exception as e:
                    logger.debug(f"Не удалось найти кнопку через pywinauto: {e}")
            
            # Альтернативный способ через pyautogui - ищем кнопку внизу окна
            try:
                if self.telegram_window:
                    try:
                        window_rect = self.telegram_window.rectangle()
                        # Кнопка обычно внизу по центру окна
                        button_x = window_rect.left + (window_rect.width() // 2)
                        button_y = window_rect.top + (window_rect.height() - 100)  # Примерно 100px от низа
                    except:
                        screen_width, screen_height = pyautogui.size()
                        button_x = screen_width // 2
                        button_y = screen_height - 150  # Внизу экрана
                else:
                    screen_width, screen_height = pyautogui.size()
                    button_x = screen_width // 2
                    button_y = screen_height - 150
                
                # Кликаем в область кнопки
                pyautogui.click(button_x, button_y)
                logger.info("Кнопка 'Продолжить' нажата через pyautogui")
                time.sleep(1)
                return True
            except Exception as e:
                logger.warning(f"Не удалось нажать кнопку через pyautogui: {e}")
                # Пробуем просто нажать Enter (часто работает)
                try:
                    pyautogui.press('enter')
                    logger.info("Нажат Enter для продолжения")
                    time.sleep(1)
                    return True
                except:
                    pass
            
            return False
        except Exception as e:
            logger.warning(f"Ошибка при нажатии кнопки 'Продолжить': {e}")
            return False
    
    def enter_code(self, code: str) -> bool:
        """
        Ввод кода подтверждения в Telegram Desktop/Portable
        
        Args:
            code: Код подтверждения (5 цифр)
            
        Returns:
            True если успешно, False в противном случае
        """
        try:
            # Пробуем активировать окно (но продолжаем даже если не удалось)
            self.activate_window()
            
            time.sleep(1)  # Даем время окну активироваться
            
            # Пробуем найти поле ввода кода через pywinauto
            try:
                if self.telegram_window:
                    # Ищем поле ввода кода
                    edit_controls = self.telegram_window.descendants(control_type="Edit")
                    if edit_controls:
                        code_field = edit_controls[0]
                        code_field.set_focus()
                        time.sleep(0.3)
                        # Очищаем поле и вводим код
                        code_field.set_text("")
                        time.sleep(0.2)
                        code_field.type_keys(code, with_spaces=False)
                        time.sleep(0.3)
                        # Автоматически нажимаем Enter или кнопку подтверждения
                        pyautogui.press('enter')
                        logger.info(f"Код {code} введен через pywinauto")
                        return True
            except Exception as e:
                logger.warning(f"Не удалось ввести код через pywinauto: {e}")
            
            # Альтернативный способ через pyautogui
            try:
                # Если окно найдено, используем его координаты
                if self.telegram_window:
                    try:
                        window_rect = self.telegram_window.rectangle()
                        center_x = window_rect.left + (window_rect.width() // 2)
                        center_y = window_rect.top + (window_rect.height() // 2)
                    except:
                        # Если не удалось получить координаты, используем центр экрана
                        screen_width, screen_height = pyautogui.size()
                        center_x = screen_width // 2
                        center_y = screen_height // 2
                else:
                    # Если окно не найдено, используем центр экрана
                    screen_width, screen_height = pyautogui.size()
                    center_x = screen_width // 2
                    center_y = screen_height // 2
                
                # Кликаем в область поля ввода кода
                pyautogui.click(center_x, center_y)
                time.sleep(0.5)
                
                # Очищаем поле
                pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.3)
                pyautogui.press('delete')
                time.sleep(0.3)
                
                # Вводим код
                pyautogui.write(code, interval=0.05)  # Быстрее
                time.sleep(0.3)
                
                # Автоматически нажимаем Enter для подтверждения
                pyautogui.press('enter')
                logger.info(f"Код {code} введен через pyautogui")
                return True
                
            except Exception as e:
                logger.error(f"Ошибка при вводе кода через pyautogui: {e}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при вводе кода: {e}")
            return False
    
    def check_cloud_password_needed(self) -> bool:
        """
        Проверяет, требуется ли ввод облачного пароля
        
        Returns:
            True если требуется пароль, False в противном случае
        """
        try:
            # Пробуем активировать окно
            self.activate_window()
            time.sleep(0.5)
            
            # Ищем текст "облачный пароль", "cloud password" или поле ввода пароля
            if self.telegram_window:
                try:
                    # Ищем текст в окне
                    window_text = self.telegram_window.window_text().lower()
                    password_keywords = ["облачный пароль", "cloud password", "пароль", "password"]
                    
                    if any(keyword in window_text for keyword in password_keywords):
                        logger.info("Обнаружен запрос облачного пароля")
                        return True
                    
                    # Ищем поле ввода пароля (обычно это PasswordEdit или Edit с типом password)
                    edit_controls = self.telegram_window.descendants(control_type="Edit")
                    if edit_controls:
                        # Проверяем, есть ли поле пароля (обычно оно пустое и активно)
                        for edit in edit_controls:
                            try:
                                if edit.is_visible() and edit.is_enabled():
                                    # Если поле активно и видимо, возможно это запрос пароля
                                    logger.info("Обнаружено поле ввода (возможно пароль)")
                                    return True
                            except:
                                continue
                except Exception as e:
                    logger.debug(f"Ошибка при проверке пароля: {e}")
            
            return False
        except Exception as e:
            logger.warning(f"Ошибка при проверке необходимости пароля: {e}")
            return False
    
    def enter_cloud_password(self, password: str) -> bool:
        """
        Ввод облачного пароля в Telegram Desktop/Portable
        
        Args:
            password: Облачный пароль
            
        Returns:
            True если успешно, False в противном случае
        """
        try:
            # Пробуем активировать окно
            self.activate_window()
            
            time.sleep(1)  # Даем время окну активироваться
            
            # Пробуем найти поле ввода пароля через pywinauto
            try:
                if self.telegram_window:
                    # Ищем поле ввода пароля
                    edit_controls = self.telegram_window.descendants(control_type="Edit")
                    if edit_controls:
                        password_field = edit_controls[0]
                        password_field.set_focus()
                        time.sleep(0.3)
                        # Очищаем поле и вводим пароль
                        password_field.set_text("")
                        time.sleep(0.2)
                        password_field.type_keys(password, with_spaces=False)
                        time.sleep(0.3)
                        # Нажимаем Enter для подтверждения
                        pyautogui.press('enter')
                        logger.info("Облачный пароль введен через pywinauto")
                        return True
            except Exception as e:
                logger.warning(f"Не удалось ввести пароль через pywinauto: {e}")
            
            # Альтернативный способ через pyautogui
            try:
                # Если окно найдено, используем его координаты
                if self.telegram_window:
                    try:
                        window_rect = self.telegram_window.rectangle()
                        center_x = window_rect.left + (window_rect.width() // 2)
                        center_y = window_rect.top + (window_rect.height() // 2)
                    except:
                        screen_width, screen_height = pyautogui.size()
                        center_x = screen_width // 2
                        center_y = screen_height // 2
                else:
                    screen_width, screen_height = pyautogui.size()
                    center_x = screen_width // 2
                    center_y = screen_height // 2
                
                # Кликаем в область поля ввода пароля
                pyautogui.click(center_x, center_y)
                time.sleep(0.5)
                
                # Очищаем поле
                pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.3)
                pyautogui.press('delete')
                time.sleep(0.3)
                
                # Вводим пароль
                pyautogui.write(password, interval=0.05)
                time.sleep(0.3)
                
                # Нажимаем Enter для подтверждения
                pyautogui.press('enter')
                logger.info("Облачный пароль введен через pyautogui")
                return True
                
            except Exception as e:
                logger.error(f"Ошибка при вводе пароля через pyautogui: {e}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при вводе облачного пароля: {e}")
            return False


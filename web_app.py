from flask import Flask, render_template, jsonify, request
import os
import json
import psutil
import logging
from telegram_automation import TelegramAutomation
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

logger = logging.getLogger(__name__)

# Глобальный объект автоматизации
automation = TelegramAutomation()

# Временное хранилище активных сессий (в памяти, не сохраняется)
active_sessions = {}


def get_telegram_sessions():
    """Получает список всех сессий Telegram Desktop"""
    sessions = []
    
    try:
        # Ищем все процессы Telegram
        telegram_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'create_time']):
            try:
                proc_name = proc.info.get('name', '').lower() if proc.info.get('name') else ''
                if 'telegram' in proc_name:
                    telegram_processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'started': datetime.fromtimestamp(proc.info['create_time']).strftime('%Y-%m-%d %H:%M:%S')
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        # Если процессов нет, возвращаем пустой список
        if not telegram_processes:
            return sessions
        
        # Проверяем статус каждого процесса
        for proc_info in telegram_processes:
            try:
                # Сбрасываем окно для нового поиска
                automation.telegram_window = None
                
                # Пробуем найти окно для этого процесса
                try:
                    from pywinauto import Application
                    app = Application(backend="uia").connect(process=proc_info['pid'])
                    automation.telegram_window = app.top_window()
                except:
                    try:
                        app = Application(backend="win32").connect(process=proc_info['pid'])
                        automation.telegram_window = app.top_window()
                    except:
                        automation.telegram_window = None
                
                if automation.telegram_window:
                    is_authorized = automation.check_if_authorized()
                    
                    # Получаем информацию об окне
                    phone = "Неизвестно"
                    try:
                        window_text = automation.telegram_window.window_text()
                        # Пробуем найти номер в тексте окна
                        import re
                        phone_match = re.search(r'\+?\d{10,15}', window_text)
                        if phone_match:
                            phone = phone_match.group()
                    except:
                        pass
                    
                    sessions.append({
                        'pid': proc_info['pid'],
                        'name': proc_info['name'],
                        'started': proc_info['started'],
                        'authorized': is_authorized,
                        'phone': phone,
                        'status': 'Авторизован' if is_authorized else 'Требуется вход'
                    })
                else:
                    # Процесс есть, но окно не найдено
                    sessions.append({
                        'pid': proc_info['pid'],
                        'name': proc_info['name'],
                        'started': proc_info['started'],
                        'authorized': False,
                        'phone': 'Окно не найдено',
                        'status': 'Окно не найдено'
                    })
            except Exception as e:
                logger.error(f"Ошибка при проверке процесса {proc_info['pid']}: {e}")
                sessions.append({
                    'pid': proc_info['pid'],
                    'name': proc_info['name'],
                    'started': proc_info['started'],
                    'authorized': False,
                    'phone': 'Ошибка проверки',
                    'status': 'Ошибка проверки'
                })
    
    except Exception as e:
        logger.error(f"Ошибка при получении сессий: {e}")
    
    return sessions


@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')


@app.route('/api/sessions')
def get_sessions():
    """API для получения списка сессий"""
    sessions = get_telegram_sessions()
    return jsonify({'sessions': sessions, 'count': len(sessions)})


@app.route('/api/connect/<int:pid>', methods=['POST'])
def connect_session(pid):
    """Подключение к сессии по PID"""
    try:
        # Пробуем найти процесс
        try:
            proc = psutil.Process(pid)
            if 'telegram' not in proc.name().lower():
                return jsonify({'success': False, 'error': 'Процесс не является Telegram'}), 400
        except psutil.NoSuchProcess:
            return jsonify({'success': False, 'error': 'Процесс не найден'}), 404
        
        # Подключаемся к окну
        automation.telegram_window = None
        automation.find_telegram_window()
        
        if not automation.telegram_window:
            return jsonify({'success': False, 'error': 'Не удалось найти окно Telegram'}), 404
        
        # Активируем окно
        if automation.activate_window():
            # Проверяем статус авторизации
            is_authorized = automation.check_if_authorized()
            
            # Сохраняем в активные сессии (в памяти)
            active_sessions[pid] = {
                'pid': pid,
                'connected_at': datetime.now().isoformat(),
                'authorized': is_authorized
            }
            
            return jsonify({
                'success': True,
                'message': 'Подключено успешно',
                'authorized': is_authorized
            })
        else:
            return jsonify({'success': False, 'error': 'Не удалось активировать окно'}), 500
            
    except Exception as e:
        logger.error(f"Ошибка при подключении к сессии {pid}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/disconnect/<int:pid>', methods=['POST'])
def disconnect_session(pid):
    """Отключение от сессии"""
    try:
        if pid in active_sessions:
            del active_sessions[pid]
        return jsonify({'success': True, 'message': 'Отключено'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/status')
def get_status():
    """Получение статуса системы"""
    sessions = get_telegram_sessions()
    return jsonify({
        'active_sessions': len(active_sessions),
        'total_sessions': len(sessions),
        'authorized_sessions': len([s for s in sessions if s.get('authorized', False)])
    })


if __name__ == '__main__':
    print("🌐 Веб-приложение запущено на http://localhost:5000")
    print("📱 Откройте браузер и перейдите по адресу http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)


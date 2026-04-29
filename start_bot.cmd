@echo off
cd /d C:\vr_bot

echo =========================
echo   Запуск Telegram бота
echo =========================

if exist .venv (
    call .venv\Scripts\activate
) else (
    echo Виртуальное окружение не найдено, запускаем без него
)

python bot.py

echo.
echo Бот остановлен
pause
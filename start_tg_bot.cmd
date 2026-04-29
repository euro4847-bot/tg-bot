@echo off
cd /d C:\vr_bot

echo Starting Telegram bot...

IF NOT EXIST .venv (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate

echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo Running bot...
python bot.py

pause

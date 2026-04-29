import json
import os
import urllib.request

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://vk-mini-booking.vercel.app/")
ADMIN_URL = os.environ.get("ADMIN_URL", "")  # example: https://t.me/your_admin_username


def _json_response(status=200, body=None):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(body or {"ok": True}, ensure_ascii=False),
    }


def _telegram(method, payload):
    if not BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Telegram API error: {e}")
        return None


def _main_keyboard():
    buttons = [
        [
            {
                "text": "▶️ Начать запись",
                "web_app": {"url": WEBAPP_URL},
            }
        ]
    ]
    if ADMIN_URL:
        buttons.append([
            {
                "text": "✍️ Написать администратору",
                "url": ADMIN_URL,
            }
        ])
    return {"inline_keyboard": buttons}


def _send_start(chat_id):
    text = (
        "Привет! 🎮\n\n"
        "Нажмите кнопку «Начать запись», чтобы открыть форму бронирования."
    )
    _telegram("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": _main_keyboard(),
    })


def handler(request):
    if request.method != "POST":
        return _json_response(200, {"ok": True, "message": "Telegram webhook is ready"})

    try:
        update = json.loads(request.body or "{}")
    except Exception:
        return _json_response(400, {"ok": False, "error": "bad json"})

    message = update.get("message") or update.get("edited_message")
    if message:
        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip().lower()
        if chat_id and (text in ("/start", "start", "начать", "старт") or text.startswith("/start")):
            _send_start(chat_id)
        elif chat_id:
            _send_start(chat_id)

    return _json_response(200, {"ok": True})

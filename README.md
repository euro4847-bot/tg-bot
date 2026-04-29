# Telegram Bot for Vercel

Простой webhook-бот для Telegram:
- `/start` показывает кнопку `▶️ Начать запись`
- кнопка открывает мини-аппу
- опционально показывает кнопку `✍️ Написать администратору`

## Vercel Environment Variables

Обязательные:

```env
BOT_TOKEN=telegram_bot_token
WEBAPP_URL=https://vk-mini-booking.vercel.app/
```

Опционально:

```env
ADMIN_URL=https://t.me/your_admin_username
```

## Webhook

После деплоя откройте в браузере:

```text
https://api.telegram.org/bot<БОТ_ТОКЕН>/setWebhook?url=https://<ВАШ_ПРОЕКТ>.vercel.app/api/bot
```

Проверка:

```text
https://api.telegram.org/bot<БОТ_ТОКЕН>/getWebhookInfo
```

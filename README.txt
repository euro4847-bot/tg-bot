Патч Telegram WebApp кнопки

1) Замени файл bot.py в папке твоего Telegram-бота на этот bot.py.
2) В .env можно добавить строку:
WEBAPP_URL=https://vk-mini-booking.vercel.app/

Если WEBAPP_URL не указан, бот сам использует https://vk-mini-booking.vercel.app/

После замены перезапусти бота.
В меню появится кнопка "🎮 Записаться" как Telegram WebApp.
Именно через нее мини-аппа сможет получить tg_id.

---
title: Goofish Parser Bot
emoji: 🔥
colorFrom: blue
colorTo: red
sdk: docker
pinned: false
license: mit
---

# Goofish Parser Bot

Telegram bot для поиска выгодных товаров на Goofish (闲鱼).

## Переменные окружения (Secrets)

Установить в HF Space Settings → Secrets:

| Переменная | Описание |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен Telegram бота |
| `TELEGRAM_USER_ID` | ID пользователя Telegram |
| `API_BASE_URL` | URL Vercel-прокси (если Telegram заблокирован) |
| `CNY_TO_RUB` | Курс юаня к рублю (по умолчанию 12) |

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

Telegram bot for finding profitable deals on Goofish (闲鱼).

## Environment Variables

Set these in Hugging Face Space Settings → Secrets:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_USER_ID` | Telegram user ID |
| `CNY_TO_RUB` | CNY to RUB exchange rate (default: 12) |

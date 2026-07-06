---
title: FruitsFamily Parser Bot
emoji: 🔥
colorFrom: blue
colorTo: red
sdk: docker
pinned: false
license: mit
---

# FruitsFamily Parser Bot

Telegram бот для поиска выгодных товаров на корейском маркетплейсе [FruitsFamily](https://fruitsfamily.com).

## Команды

- `/search` — поиск товаров по бренду и категории
- `/rate` — курс KRW/RUB
- `/recent` — последние выгодные находки
- `/status` — статус API
- `/help` — справка

## Установка

```bash
pip install -r goofish_parser/requirements.txt
```

Создать `goofish_parser/.env`:

```
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_USER_ID=your_id
```

Запуск:

```bash
python goofish_parser/main.py
```

## Docker

```bash
docker-compose up --build
```

## Как это работает

1. Бот шлёт GraphQL-запросы на `web-server.production.fruitsfamily.com/graphql`
2. Никакой авторизации не требуется — API полностью открыт
3. Поиск через `searchProducts(filter: {query: "brand+тип", show_only: "selling"})`
4. Цены в корейских вонах (KRW), конвертируются в рубли по курсу ЦБ РФ
5. Товары сортируются по проценту скидки от рыночной цены

## Технологии

- Python + python-telegram-bot
- GraphQL (Apollo Client на фронтенде)
- ЦБ РФ для курса валют

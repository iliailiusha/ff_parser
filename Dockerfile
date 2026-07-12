FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright

WORKDIR /app

# System deps для Playwright
RUN apt-get update && apt-get install -y \
    libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 \
    libcups2t64 libdrm2 libdbus-1-3 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2t64 \
    && rm -rf /var/lib/apt/lists/*

COPY goofish_parser/requirements.txt /app/goofish_parser/
RUN pip install --no-cache-dir -r /app/goofish_parser/requirements.txt

# Устанавливаем Chromium для Playwright
RUN python -m playwright install chromium

COPY goofish_parser/ /app/goofish_parser/

RUN mkdir -p /app/goofish_parser/data

CMD ["python", "-m", "goofish_parser.main"]

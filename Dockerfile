FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright \
    DISPLAY=:99

WORKDIR /app

# System deps: Playwright browsers + Xvfb + chromium-browser
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 \
    libcups2t64 libdrm2 libdbus-1-3 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2t64 \
    xvfb x11-utils xauth \
    chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

COPY goofish_parser/requirements.txt /app/goofish_parser/
RUN pip install --no-cache-dir -r /app/goofish_parser/requirements.txt

# Install browsers for patchright and playwright
RUN python -m playwright install chromium 2>/dev/null || true
RUN python -m patchright install chromium 2>/dev/null || true

COPY goofish_parser/ /app/goofish_parser/

RUN mkdir -p /app/goofish_parser/data

# Entrypoint: start Xvfb, then the bot
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]

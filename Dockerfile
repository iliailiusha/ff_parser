FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates fonts-liberation \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 \
    libcups2 libdbus-1-3 libdrm2 libgbm1 \
    libglib2.0-0 libnspr4 libnss3 libu2f-udev \
    libvulkan1 libxcomposite1 libxdamage1 \
    libxfixes3 libxkbcommon0 libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY goofish_parser/requirements.txt /app/goofish_parser/
RUN pip install --no-cache-dir -r /app/goofish_parser/requirements.txt
RUN python -m playwright install chromium

COPY goofish_parser/ /app/goofish_parser/

RUN mkdir -p /app/goofish_parser/data

CMD ["python", "-m", "goofish_parser.main"]

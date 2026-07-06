FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/goofish_parser/
RUN pip install --no-cache-dir -r /app/goofish_parser/requirements.txt

COPY . /app/goofish_parser/

RUN mkdir -p /app/goofish_parser/data

CMD ["python", "-m", "goofish_parser.main"]

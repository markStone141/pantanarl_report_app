FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements ./requirements
RUN pip install --no-cache-dir -r requirements/prod.txt

COPY . .

RUN python manage.py collectstatic --noinput

CMD ["sh", "scripts/start.sh"]

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]>=3.2" "gunicorn>=21"

COPY . .

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && \
    gunicorn serialreg.wsgi:application --bind 0.0.0.0:8000"]

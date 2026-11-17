FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --system --uid 10001 logit && mkdir /data && chown logit /data && touch /data/.logit && chown logit /data/.logit
COPY . .
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput
USER logit
CMD ["sh", "-c", "python manage.py migrate --noinput --skip-checks && exec gunicorn --bind 0.0.0.0:8000 --workers 2 logit.wsgi"]

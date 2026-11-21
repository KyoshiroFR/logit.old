FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin logit
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src/ .
COPY deploy/entrypoint.sh /usr/local/bin/logit-entrypoint
# Le code appartient à root et reste en lecture seule pour le compte logit, quels que soient les droits sur l'hôte.
RUN chmod 0755 /usr/local/bin/logit-entrypoint \
    && chmod -R u=rwX,go=rX /app \
    && LOGIT_SECRET_KEY=build-only python manage.py collectstatic --noinput -v0 \
    && chmod -R go=rX /app/staticfiles
USER logit
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/sante/', timeout=3)"
ENTRYPOINT ["logit-entrypoint"]
CMD ["serve"]

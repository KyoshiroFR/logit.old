#!/bin/sh
# serve   : démarre l'application avec le compte PostgreSQL restreint
# migrate : applique les migrations et les droits avec le compte propriétaire (service à usage unique)
set -eu

wait_db() {
    python - <<'PY'
import os, sys, time
import psycopg
role = "OWNER" if os.environ.get("LOGIT_DB_AS_OWNER") == "1" else "APP"
for _ in range(60):
    try:
        psycopg.connect(host=os.environ.get("LOGIT_DB_HOST", "db"), dbname=os.environ.get("LOGIT_DB_NAME", "logit"),
                        user=os.environ[f"LOGIT_DB_{role}_USER"], password=os.environ[f"LOGIT_DB_{role}_PASSWORD"],
                        connect_timeout=3).close()
        sys.exit(0)
    except psycopg.OperationalError:
        time.sleep(2)
sys.exit("Base de données injoignable.")
PY
}

case "${1:-serve}" in
    migrate)
        export LOGIT_DB_AS_OWNER=1
        wait_db
        python manage.py migrate --noinput
        python manage.py secure_db
        ;;
    serve)
        wait_db
        exec gunicorn config.wsgi --bind 0.0.0.0:8000 --workers "${LOGIT_WORKERS:-3}" \
            --access-logfile - --forwarded-allow-ips "*" --timeout 60
        ;;
    *)
        exec python manage.py "$@"
        ;;
esac

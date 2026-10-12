FROM python:3.12.15-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FLASK_APP=app:create_app HOME=/home/app \
    STORAGE_DIR=/data/storage APP_INTERNAL_PORT=5010
WORKDIR /app
RUN useradd --system --uid 10001 --user-group --create-home --home-dir /home/app app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN chmod +x docker/entrypoint.sh && mkdir -p /data/storage && chown -R app:app /data/storage /home/app
# Port wewnętrzny aplikacji to APP_INTERNAL_PORT (albo PORT platformy); EXPOSE to tylko metadane.
EXPOSE 5010
# Sonda zdrowia w obrazie — każda platforma (compose, Swarm, Portainer) dziedziczy ją bez własnej kopii polecenia;
# start-period obejmuje czekanie na bazę i migracje.
HEALTHCHECK --interval=30s --timeout=6s --start-period=60s --retries=3 \
  CMD python -c "import os,sys,urllib.request; p=os.environ.get('PORT') or os.environ.get('APP_INTERNAL_PORT','5010'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/healthz', timeout=4).status == 200 else 1)"
# Entrypoint startuje jako root tylko po to, by naprawić właściciela wolumenu storage,
# po czym przez setpriv przechodzi na użytkownika app (uid 10001).
ENTRYPOINT ["docker/entrypoint.sh"]

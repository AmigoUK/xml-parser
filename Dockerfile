FROM python:3.12.15-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FLASK_APP=app:create_app HOME=/home/app \
    STORAGE_DIR=/data/storage
WORKDIR /app
RUN useradd --system --uid 10001 --user-group --create-home --home-dir /home/app app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN chmod +x docker/entrypoint.sh && mkdir -p /data/storage && chown -R app:app /data/storage /home/app
EXPOSE 5010
# Entrypoint startuje jako root tylko po to, by naprawić właściciela wolumenu storage,
# po czym przez setpriv przechodzi na użytkownika app (uid 10001).
ENTRYPOINT ["docker/entrypoint.sh"]

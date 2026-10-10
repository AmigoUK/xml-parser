#!/bin/sh
set -e
STORAGE="${STORAGE_DIR:-/data/storage}"
APP_UID=10001
APP_GID=10001

# Jako root: popraw właściciela wolumenu (starsze wolumeny mają pliki roota), potem zrzuć uprawnienia.
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$STORAGE"
  chown -R "$APP_UID:$APP_GID" "$STORAGE"
  exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups "$0" "$@"
fi

# Migracje z ponawianiem (baza może jeszcze wstawać); backoff 2s, 4s, ... do 30s.
if [ -d migrations ]; then
  attempt=1
  delay=2
  max="${DB_WAIT_ATTEMPTS:-10}"
  until flask db upgrade; do
    if [ "$attempt" -ge "$max" ]; then
      echo "Migracje nie powiodły się po $attempt próbach - przerywam." >&2
      exit 1
    fi
    echo "Baza niegotowa lub migracja nieudana (próba $attempt/$max), ponawiam za ${delay}s..." >&2
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
    [ "$delay" -gt 30 ] && delay=30
  done
fi
# Seed jest idempotentny (tworzy tylko brakujące jednostki/admina/klucz demo; nie resetuje danych).
if flask --help | grep -q " seed"; then flask seed; fi
# Wątkowe workery: bezczynne gniazda (np. preconnect przeglądarki) nie blokują workerów sync.
# Cykliczny restart workerów (max-requests) ogranicza wycieki pamięci.
# Nadpisanie: zmienna GUNICORN_CMD_ARGS (flagi CLI miałyby pierwszeństwo, więc są tylko tutaj).
export GUNICORN_CMD_ARGS="${GUNICORN_CMD_ARGS:--k gthread -w 2 --threads 8 --timeout 60 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 --worker-tmp-dir /dev/shm}"
exec gunicorn -b 0.0.0.0:5010 --access-logfile - "app:create_app()"

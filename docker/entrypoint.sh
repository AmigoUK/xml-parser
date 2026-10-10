#!/bin/sh
set -e
mkdir -p "${STORAGE_DIR:-/data/storage}"
if [ -d migrations ]; then flask db upgrade; fi
if flask --help | grep -q " seed"; then flask seed; fi
# Wątkowe workery: bezczynne gniazda (np. preconnect przeglądarki) nie blokują workerów sync.
# Nadpisanie: zmienna GUNICORN_CMD_ARGS (flagi CLI miałyby pierwszeństwo, więc są tylko tutaj).
export GUNICORN_CMD_ARGS="${GUNICORN_CMD_ARGS:--k gthread -w 2 --threads 8 --timeout 60}"
exec gunicorn -b 0.0.0.0:5010 --access-logfile - "app:create_app()"

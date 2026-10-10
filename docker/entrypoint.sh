#!/bin/sh
set -e
mkdir -p "${STORAGE_DIR:-/data/storage}"
if [ -d migrations ]; then flask db upgrade; fi
if flask --help | grep -q " seed"; then flask seed; fi
exec gunicorn -w 2 -b 0.0.0.0:5010 --access-logfile - "app:create_app()"

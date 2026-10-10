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

# FR-7: najpierw błędy konfiguracji (nie ponawiane), potem czekanie na bazę (ponawiane tylko
# przy błędzie połączenia), na końcu jedna próba migracji z czytelnym komunikatem.
probe="$STORAGE/.write-test.$$"
if ! { mkdir -p "$STORAGE" && : > "$probe" && rm -f "$probe"; } 2>/dev/null; then
  echo "Błąd konfiguracji: katalog STORAGE_DIR=$STORAGE nie jest zapisywalny dla uid $(id -u) - popraw STORAGE_DIR/wolumen, przerywam." >&2
  exit 1
fi

if [ -d migrations ]; then
  # Sonda połączenia: kod 3 = baza nieosiągalna/niegotowa (ponawiamy), inny = błąd konfiguracji (koniec).
  attempt=1
  delay=2
  max="${DB_WAIT_ATTEMPTS:-10}"
  while :; do
    rc=0
    python - <<'PY' || rc=$?
import os, sys
try:
    import sqlalchemy as sa
    from sqlalchemy.exc import OperationalError
    engine = sa.create_engine(os.environ.get("DATABASE_URL", "sqlite:///xmlparser-dev.db"))
except Exception as exc:  # zły URL, brak sterownika itp.
    print(f"Błąd konfiguracji bazy (DATABASE_URL): {type(exc).__name__}: {exc}", file=sys.stderr)
    sys.exit(1)
try:
    with engine.connect():
        pass
except OperationalError as exc:
    print(f"OperationalError: {exc.orig if exc.orig is not None else exc}", file=sys.stderr)
    sys.exit(3)
except Exception as exc:
    print(f"Błąd konfiguracji bazy: {type(exc).__name__}: {exc}", file=sys.stderr)
    sys.exit(1)
PY
    [ "$rc" -eq 0 ] && break
    if [ "$rc" -ne 3 ]; then
      echo "Błąd konfiguracji połączenia z bazą (szczegóły powyżej) - nie ponawiam, przerywam." >&2
      exit 1
    fi
    if [ "$attempt" -ge "$max" ]; then
      echo "Baza nieosiągalna po $attempt próbach - przerywam." >&2
      exit 1
    fi
    echo "Baza niegotowa (próba $attempt/$max), ponawiam za ${delay}s..." >&2
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
    [ "$delay" -gt 30 ] && delay=30
  done
  if ! flask db upgrade; then
    echo "Migracja bazy nie powiodła się (baza osiągalna, błąd migracji lub startu aplikacji - szczegóły powyżej). Nie ponawiam; sprawdź log, w razie potrzeby odtwórz kopię z tools/backup.sh." >&2
    exit 1
  fi
fi
# Seed jest idempotentny (tworzy tylko brakujące jednostki/admina/klucz demo; nie resetuje danych).
if flask --help | grep -q " seed"; then flask seed; fi
# Wątkowe workery: bezczynne gniazda (np. preconnect przeglądarki) nie blokują workerów sync.
# Cykliczny restart workerów (max-requests) ogranicza wycieki pamięci.
# Nadpisanie: zmienna GUNICORN_CMD_ARGS (flagi CLI miałyby pierwszeństwo, więc są tylko tutaj).
export GUNICORN_CMD_ARGS="${GUNICORN_CMD_ARGS:--k gthread -w 2 --threads 8 --timeout 60 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 --worker-tmp-dir /dev/shm}"
exec gunicorn -b 0.0.0.0:5010 --access-logfile - "app:create_app()"

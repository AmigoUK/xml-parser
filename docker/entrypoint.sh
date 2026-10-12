#!/bin/sh
set -e
STORAGE="${STORAGE_DIR:-/data/storage}"
APP_UID=10001
APP_GID=10001

# Jako root: popraw właściciela wolumenu (starsze wolumeny mają pliki roota), potem zrzuć uprawnienia.
# chown tylko, gdy katalog nie należy już do app (duże wolumeny / NFS: pełny chown -R trwa i bywa niemożliwy);
# niepowodzenie to ostrzeżenie — rozstrzyga sonda zapisu niżej.
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$STORAGE"
  if [ "$(stat -c %u "$STORAGE" 2>/dev/null)" != "$APP_UID" ]; then
    chown -R "$APP_UID:$APP_GID" "$STORAGE" || echo "OSTRZEŻENIE: chown $STORAGE nie powiódł się (wolumen sieciowy? ustaw właściciela uid $APP_UID po stronie platformy, np. fsGroup)." >&2
  fi
  exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups "$0" "$@"
fi

# FR-7: najpierw błędy konfiguracji (nie ponawiane), potem czekanie na bazę (ponawiane tylko
# przy błędzie połączenia), na końcu jedna próba migracji z czytelnym komunikatem.
probe="$STORAGE/.write-test.$$"
if ! { mkdir -p "$STORAGE" && : > "$probe" && rm -f "$probe"; } 2>/dev/null; then
  echo "Błąd konfiguracji: katalog STORAGE_DIR=$STORAGE nie jest zapisywalny dla uid $(id -u) - popraw STORAGE_DIR/wolumen, przerywam." >&2
  exit 1
fi

# W kontenerze baza musi być wskazana jawnie: bez DATABASE_URL aplikacja użyłaby pliku SQLite w /app (katalog roota,
# nietrwały) i padła dopiero na sondzie z mylącym „baza niegotowa”.
case "${DATABASE_URL:-}" in
  "")
    echo "Błąd konfiguracji: brak DATABASE_URL (adres MariaDB, np. mysql+pymysql://xmlparser:haslo@db:3306/xmlparser?charset=utf8mb4) - przerywam." >&2
    exit 1 ;;
  [Ss][Qq][Ll][Ii][Tt][Ee]:*)
    echo "Błąd konfiguracji: DATABASE_URL wskazuje SQLite - w kontenerze wymagana jest MariaDB (plik SQLite w obrazie nie jest trwały ani zapisywalny dla uid $(id -u)) - przerywam." >&2
    exit 1 ;;
esac

if [ -d migrations ]; then
  # Sonda połączenia (app/dbprobe.py): kod 3 = baza nieosiągalna/niegotowa (ponawiamy), inny = błąd konfiguracji (koniec).
  attempt=1
  delay=2
  max="${DB_WAIT_ATTEMPTS:-10}"
  while :; do
    rc=0
    python -m app.dbprobe || rc=$?
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
  if [ "${MIGRATE_ON_START:-1}" = "0" ]; then
    echo "MIGRATE_ON_START=0: pomijam migracje i seed - uruchom je osobnym zadaniem: flask db upgrade && flask seed." >&2
  else
    # Blokada po stronie bazy (app/dblock.py): przy wielu replikach migruje jedna, reszta czeka i powtarza no-op.
    if ! python -m app.dblock -- flask db upgrade; then
      echo "Migracja bazy nie powiodła się (baza osiągalna, błąd migracji lub startu aplikacji - szczegóły powyżej). Nie ponawiam; sprawdź log, w razie potrzeby odtwórz kopię z tools/backup.sh." >&2
      exit 1
    fi
    # Seed jest idempotentny (tworzy tylko brakujące jednostki/admina/klucz demo; nie resetuje danych).
    python -m app.dblock -- flask seed
  fi
fi
# Wątkowe workery: bezczynne gniazda (np. preconnect przeglądarki) nie blokują workerów sync.
# Cykliczny restart workerów (max-requests) ogranicza wycieki pamięci.
# Pojedyncze flagi: GUNICORN_WORKERS / GUNICORN_THREADS / GUNICORN_TIMEOUT; cały zestaw: GUNICORN_CMD_ARGS (zastępuje
# wszystko; flagi CLI miałyby pierwszeństwo, więc są tylko tutaj). --worker-tmp-dir tylko, gdy katalog istnieje —
# runtime bez /dev/shm (gVisor, --ipc=none) nie może wywrócić startu; wtedy heartbeat workerów idzie do domyślnego tmp.
if [ -z "${GUNICORN_CMD_ARGS:-}" ]; then
  GUNICORN_CMD_ARGS="-k gthread -w ${GUNICORN_WORKERS:-2} --threads ${GUNICORN_THREADS:-8} --timeout ${GUNICORN_TIMEOUT:-60} --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100"
  worker_tmp="${GUNICORN_WORKER_TMP_DIR:-/dev/shm}"
  if [ -d "$worker_tmp" ]; then
    GUNICORN_CMD_ARGS="$GUNICORN_CMD_ARGS --worker-tmp-dir $worker_tmp"
  else
    echo "UWAGA: katalog $worker_tmp nie istnieje - gunicorn użyje domyślnego katalogu tymczasowego na pliki heartbeat workerów." >&2
  fi
fi
export GUNICORN_CMD_ARGS
# Port wewnętrzny: PORT platformy (Cloud Run, Heroku…) ma pierwszeństwo przed APP_INTERNAL_PORT z obrazu/compose.
exec gunicorn -b "0.0.0.0:${PORT:-${APP_INTERNAL_PORT:-5010}}" --access-logfile - "app:create_app()"

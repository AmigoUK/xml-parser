#!/bin/bash
# Kopia zapasowa: zrzut MariaDB + archiwum wolumenu storage do backups/<data>/.
# Użycie (z katalogu projektu): tools/backup.sh [dni_retencji]   (domyślnie 14)
# Wymaga działającego stacku docker compose.
# FR-1: pipefail + kontrola zawartości; przy jakimkolwiek błędzie niekompletny katalog jest usuwany
# i skrypt kończy się kodem ≠ 0 (nigdy „Kopia zapasowa zapisana” dla pustego/przerwanego zrzutu).
set -euo pipefail
cd "$(dirname "$0")/.."
RETENTION_DAYS="${1:-${BACKUP_RETENTION_DAYS:-14}}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="backups/$STAMP"
umask 077
mkdir -p "$DEST"

DONE=0
cleanup() {
  if [ "$DONE" != 1 ]; then
    rm -rf "$DEST"
    echo "BŁĄD: kopia zapasowa NIE powstała (niekompletny katalog $DEST usunięty)." >&2
  fi
}
trap cleanup EXIT

fail() { echo "BŁĄD: $*" >&2; exit 1; }

# 1) Baza: zrzut spójny transakcyjnie (InnoDB). Hasło z env kontenera db, nie z linii poleceń hosta.
docker compose exec -T db sh -c \
  'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb-dump -uroot --single-transaction --routines --triggers --databases "$MARIADB_DATABASE"' \
  | gzip > "$DEST/db.sql.gz" || fail "zrzut bazy (mariadb-dump) nie powiódł się"

# 2) Pliki dokumentów: wolumen storage z działającego kontenera app.
docker compose exec -T app tar -C /data/storage -cf - . | gzip > "$DEST/storage.tar.gz" \
  || fail "archiwum storage (tar w kontenerze app) nie powiodło się"

# 3) Weryfikacja zawartości: archiwa czytelne, zrzut zawiera tabele i jest kompletny.
gzip -t "$DEST/db.sql.gz" "$DEST/storage.tar.gz" || fail "uszkodzone archiwum gzip"
# grep -c czyta całe wejście (grep -q przy pipefail dałby fałszywy SIGPIPE zcat dla dużych zrzutów).
zcat "$DEST/db.sql.gz" | grep -c 'CREATE TABLE' > /dev/null || fail "zrzut bazy nie zawiera żadnej tabeli (pusty?)"
zcat "$DEST/db.sql.gz" | tail -n 1 | grep -c 'Dump completed' > /dev/null || fail "zrzut bazy jest niekompletny (brak 'Dump completed')"
tar -tzf "$DEST/storage.tar.gz" > /dev/null || fail "archiwum storage jest nieczytelne"
DONE=1

# 4) Retencja (dopiero po udanej kopii).
find backups -mindepth 1 -maxdepth 1 -type d -mtime +"$RETENTION_DAYS" -exec rm -rf {} +
echo "Kopia zapasowa zapisana w $DEST (retencja: $RETENTION_DAYS dni)"

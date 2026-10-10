#!/bin/sh
# Kopia zapasowa: zrzut MariaDB + archiwum wolumenu storage do backups/<data>/.
# Użycie (z katalogu projektu): tools/backup.sh [dni_retencji]   (domyślnie 14)
# Wymaga działającego stacku docker compose.
set -eu
cd "$(dirname "$0")/.."
RETENTION_DAYS="${1:-${BACKUP_RETENTION_DAYS:-14}}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="backups/$STAMP"
umask 077
mkdir -p "$DEST"

# 1) Baza: zrzut spójny transakcyjnie (InnoDB). Hasło z env kontenera db, nie z linii poleceń hosta.
docker compose exec -T db sh -c \
  'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb-dump -uroot --single-transaction --routines --triggers --databases "$MARIADB_DATABASE"' \
  | gzip > "$DEST/db.sql.gz"

# 2) Pliki dokumentów: wolumen storage z działającego kontenera app.
docker compose exec -T app tar -C /data/storage -cf - . | gzip > "$DEST/storage.tar.gz"

# Weryfikacja minimalna: archiwa muszą być czytelne i niepuste.
gzip -t "$DEST/db.sql.gz" "$DEST/storage.tar.gz"
[ -s "$DEST/db.sql.gz" ] || { echo "Pusty zrzut bazy" >&2; exit 1; }

# 3) Retencja.
find backups -mindepth 1 -maxdepth 1 -type d -mtime +"$RETENTION_DAYS" -exec rm -rf {} +
echo "Kopia zapasowa zapisana w $DEST (retencja: $RETENTION_DAYS dni)"

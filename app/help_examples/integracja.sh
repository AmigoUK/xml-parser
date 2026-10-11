#!/usr/bin/env bash
# Wysyłka faktury i odbiór wyniku (curl 7.76+ i jq). Użycie: ./faktura.sh faktura.xml
set -euo pipefail
BASE="__API_BASE__/api/v1"
: "${XP_API_KEY:?Ustaw zmienną środowiskową XP_API_KEY}"
FILE="$1"
DELAY="${DELAY:-5}"          # pierwsza przerwa między odpytaniami (s)
MAX_WAIT="${MAX_WAIT:-3600}"  # ile najdłużej czekać na operatora (s)

resp=$(curl -sS --fail-with-body -H "X-API-Key: $XP_API_KEY" -F "file=@$FILE" "$BASE/documents") \
  || { echo "Błąd wysyłki: $resp" >&2; exit 1; }
id=$(jq -r '.id' <<<"$resp")
status=$(jq -r '.status' <<<"$resp")
echo "Dokument #$id: $status"

waited=0
while [[ "$status" == "needs_review" || "$status" == "received" ]] && (( waited + DELAY <= MAX_WAIT )); do
  sleep "$DELAY"
  waited=$(( waited + DELAY ))
  DELAY=$(( DELAY * 2 > 300 ? 300 : DELAY * 2 ))
  resp=$(curl -sS --fail-with-body -H "X-API-Key: $XP_API_KEY" "$BASE/documents/$id") \
    || { echo "Błąd odpytania: $resp" >&2; exit 1; }
  status=$(jq -r '.status' <<<"$resp")
done

case "$status" in
  approved)  jq '.invoice' <<<"$resp" > "faktura-$id.json"; echo "Zapisano faktura-$id.json" ;;
  duplicate) echo "Duplikat dokumentu #$(jq -r '.issues[] | select(.code == "duplicate") | .source_value' <<<"$resp")" ;;
  rejected)  jq -r '.issues[].message' <<<"$resp"; exit 1 ;;
  *)         echo "Nadal czeka na operatora — sprawdź później: GET $BASE/documents/$id" ;;
esac

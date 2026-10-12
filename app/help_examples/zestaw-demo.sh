#!/usr/bin/env bash
# Wczytanie zestawu demo „Miesiąc faktur” przez API (curl 7.76+ i jq 1.6+).
# Użycie: ./zestaw-demo.sh [pierwsze|pozostale|wszystko] [katalog]
#   pierwsze  — 6 pierwszych faktur (każdy dostawca raz; wszystkie czekają na operatora w panelu)
#   pozostale — 18 kolejnych (uruchom po nauczeniu szablonów w panelu)
#   wszystko  — obie fazy po kolei
# Katalog z plikami i manifest.json to domyślnie demo/dataset względem bieżącego katalogu.
set -euo pipefail
BASE="__API_BASE__/api/v1"
USAGE="Użycie: $0 [pierwsze|pozostale|wszystko] [katalog]"
for t in curl jq; do command -v "$t" > /dev/null || { echo "Brak programu $t — zainstaluj go (curl 7.76+, jq 1.6+)." >&2; exit 1; }; done
: "${XP_API_KEY:?Ustaw zmienną środowiskową XP_API_KEY}"

case "${1:-pierwsze}" in
  pierwsze)  PHASES='["first"]' ;;
  pozostale) PHASES='["rest"]' ;;
  wszystko)  PHASES='["first","rest"]' ;;
  *) echo "$USAGE" >&2; exit 1 ;;
esac
DIR="${2:-demo/dataset}"
[[ -f "$DIR/manifest.json" ]] || { echo "Brak pliku $DIR/manifest.json — podaj katalog zestawu. $USAGE" >&2; exit 1; }

declare -A COUNT=()
# pliki wybranych faz, w kolejności z manifestu
while IFS= read -r name; do
  resp=$(curl -sS --fail-with-body -H "X-API-Key: $XP_API_KEY" -F "file=@$DIR/$name" "$BASE/documents") \
    || { echo "Błąd wysyłki $name: $resp" >&2; exit 1; }
  id=$(jq -r '.id' <<<"$resp")
  status=$(jq -r '.status' <<<"$resp")
  echo "#$id $status $name"
  COUNT[$status]=$(( ${COUNT[$status]:-0} + 1 ))
done < <(jq -r --argjson p "$PHASES" '.files | sort_by(.order)[] | select(.phase as $f | $p | index($f)) | .filename' "$DIR/manifest.json")

summary=""
for s in "${!COUNT[@]}"; do summary+="${summary:+, }$s: ${COUNT[$s]}"; done
echo "Razem: ${summary:-brak plików do wczytania}"

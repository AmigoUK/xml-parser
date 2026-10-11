#!/usr/bin/env bash
# Wysyłka faktury, odbiór wyniku i synchronizacja zmian (curl 7.76+ i jq 1.6+).
# Użycie: ./faktura.sh faktura.xml        — wysyłka i odbiór wyniku (sposób A)
#         ./faktura.sh --sync [stan.json] — jeden przebieg synchronizacji (sposób B)
set -euo pipefail
BASE="__API_BASE__/api/v1"
: "${XP_API_KEY:?Ustaw zmienną środowiskową XP_API_KEY}"
for t in curl jq; do command -v "$t" > /dev/null || { echo "Brak programu $t — zainstaluj go (curl 7.76+, jq 1.6+)." >&2; exit 1; }; done
DELAY="${DELAY:-5}"          # pierwsza przerwa między odpytaniami (s)
MAX_WAIT="${MAX_WAIT:-3600}"  # ile najdłużej czekać na operatora (s)
SYNC_START="1970-01-01T00:00:00Z"  # pierwszy przebieg: pełna synchronizacja (albo data wdrożenia)
SYNC_MARGIN=300                    # zapas 5 min na zmiany zatwierdzone w innej kolejności niż ich updated_at

api() { curl -sS --fail-with-body -H "X-API-Key: $XP_API_KEY" "$@"; }

# Jeden przebieg synchronizacji: dokumenty zatwierdzone (także przez operatora w panelu) od ostatniego przebiegu.
# Stan w pliku: last_sync = największy odebrany updated_at, seen = przetworzone pary id → updated_at.
# Dostawa „co najmniej raz” — pary już przetworzone są pomijane, import ma być idempotentny (po id).
sync_approved() {
  local state="${1:-xp-sync.json}" since cursor="" page doc id status updated_at
  local -a args
  [[ -f "$state" ]] || echo '{"last_sync": null, "seen": {}}' > "$state"
  jq -e 'type == "object" and (.seen | type == "object")' "$state" > /dev/null \
    || { echo "Plik stanu $state ma zły format (oczekiwano obiektu z polem seen) — usuń go albo popraw." >&2; return 1; }
  # last_sync − margines (jq liczy w pełnych sekundach — przy 5-minutowym marginesie ułamek nie ma znaczenia)
  since=$(jq -r --argjson m "$SYNC_MARGIN" \
    '.last_sync // empty | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601 - $m | todateiso8601' "$state")
  since="${since:-$SYNC_START}"
  while :; do
    args=(-G --data-urlencode "updated_since=$since" -d status=approved -d limit=500)  # --data-urlencode: „+” → %2B
    [[ -z "$cursor" ]] || args+=(--data-urlencode "cursor=$cursor")  # kolejna strona: te same parametry + kursor
    page=$(api "${args[@]}" "$BASE/documents") || { echo "Błąd synchronizacji: $page" >&2; return 1; }
    # brak pola next_cursor (a nie null) to tryb zwykły listy, a nie ostatnia strona
    jq -e 'has("next_cursor")' <<<"$page" > /dev/null || {
      echo "Błąd protokołu: odpowiedź bez pola next_cursor (serwer sprzed v0.5.0?) — synchronizacja przerwana." >&2
      return 1
    }
    while read -r id updated_at; do  # tylko pary (id, updated_at), których jeszcze nie przetworzono
      doc=$(api "$BASE/documents/$id") || { echo "Błąd odpytania: $doc" >&2; return 1; }
      status=$(jq -r '.status' <<<"$doc")
      echo "#$id $status $updated_at $(jq -r '.invoice.number // ""' <<<"$doc")"
      # importuj tylko approved — pozycja listy mogła się zdezaktualizować (reprocess, odrzucenie, duplikat);
      # zapis do pliku po id — idempotentny
      [[ "$status" != approved ]] || jq '.invoice' <<<"$doc" > "faktura-$id.json"
    done < <(jq -r --slurpfile s "$state" \
      '.items[] | select($s[0].seen[.id | tostring] != .updated_at) | "\(.id) \(.updated_at)"' <<<"$page")
    # stan po każdej stronie: last_sync = max(updated_at) (czas zawsze w formacie API, więc max tekstów = max czasu),
    # nowe pary do seen niezależnie od statusu; pary sprzed okna marginesu już nie wrócą — plik stanu zostaje mały
    jq -s --argjson m "$SYNC_MARGIN" '
      def secs: sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601;
      .[0] as $s | .[1].items as $items
      | ([$s.last_sync] + ($items | map(.updated_at)) | map(select(. != null)) | max) as $last
      | {last_sync: $last, seen: ($s.seen + ($items | map({key: (.id | tostring), value: .updated_at}) | from_entries))}
      | if $last then .seen |= with_entries(select((.value | secs) >= ($last | secs) - $m)) else . end' \
      "$state" - <<<"$page" > "$state.tmp" && mv "$state.tmp" "$state"
    cursor=$(jq -r '.next_cursor // empty' <<<"$page")
    [[ -n "$cursor" ]] || break  # next_cursor = null: ostatnia strona
  done
}

if [[ "${1:-}" == "--sync" ]]; then
  sync_approved "${2:-}"
  exit
fi

FILE="$1"
resp=$(api -F "file=@$FILE" "$BASE/documents") || { echo "Błąd wysyłki: $resp" >&2; exit 1; }
id=$(jq -r '.id' <<<"$resp")
status=$(jq -r '.status' <<<"$resp")
echo "Dokument #$id: $status"

waited=0
while [[ "$status" == "needs_review" || "$status" == "received" ]] && (( waited + DELAY <= MAX_WAIT )); do
  sleep "$DELAY"
  waited=$(( waited + DELAY ))
  DELAY=$(( DELAY * 2 > 300 ? 300 : DELAY * 2 ))
  resp=$(api "$BASE/documents/$id") || { echo "Błąd odpytania: $resp" >&2; exit 1; }
  status=$(jq -r '.status' <<<"$resp")
done

case "$status" in
  approved)  jq '.invoice' <<<"$resp" > "faktura-$id.json"; echo "Zapisano faktura-$id.json" ;;
  duplicate) echo "Duplikat dokumentu #$(jq -r '.issues[] | select(.code == "duplicate") | .source_value' <<<"$resp")" ;;
  rejected)  jq -r '.issues[].message' <<<"$resp"; exit 1 ;;
  *)         echo "Nadal czeka na operatora — sprawdź później: GET $BASE/documents/$id" ;;
esac

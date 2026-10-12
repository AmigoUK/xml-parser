#!/usr/bin/env bash
# Odbiorca webhooka parsera faktur — powłoka + openssl: TYLKO weryfikacja podpisu (--check).
#
# Parser wysyła POST z JSON-em i nagłówkami:
#   X-XP-Timestamp  czas wysyłki (sekundy unixowe, tekst)
#   X-XP-Signature  sha256=<hex HMAC-SHA256(sekret, "<timestamp>.<surowe bajty ciała>")>
#   X-XP-Delivery   identyfikator dostawy (UUID) — taki sam przy ponowieniach
#
# Sekret bierz ze zmiennej XP_WEBHOOK_SECRET.
#
# Użycie:  ./webhook-odbiorca.sh --check <ts> <podpis> [--now <ts>] < ciało.json
# Wypisuje OK albo powód odrzucenia; kod wyjścia 0 / 1. Bez sieci.
#
# Uwaga: bash nie ma serwera HTTP — do odbioru żądań użyj odbiorcy w Pythonie, PHP lub Node.js.
# Uwaga: porównanie tekstów w bashu nie jest w stałym czasie; dla narzędzia do ręcznego sprawdzania
# podpisu jest to akceptowalne, w prawdziwym odbiorcy użyj hmac.compare_digest / hash_equals / timingSafeEqual.
set -euo pipefail

MAX_SKEW=300

if [[ "${1:-}" != "--check" || $# -lt 3 ]]; then
  echo "Użycie: $0 --check <ts> <podpis> [--now <ts>] < ciało.json" >&2
  echo "Ten skrypt tylko weryfikuje podpis; serwer HTTP wymaga innego środowiska (Python, PHP, Node.js)." >&2
  exit 2
fi
ts="$2"
signature="$3"
now="$(date +%s)"
if [[ "${4:-}" == "--now" ]]; then now="${5:-}"; fi

if [[ -z "${XP_WEBHOOK_SECRET:-}" ]]; then
  echo "Ustaw zmienną XP_WEBHOOK_SECRET (sekret webhooka z panelu)." >&2
  exit 2
fi
if [[ ! "$ts" =~ ^-?[0-9]+$ || ! "$now" =~ ^-?[0-9]+$ ]]; then
  echo "nieprawidłowy znacznik czasu"
  exit 1
fi
skew=$(( now - ts ))
if (( skew < 0 )); then skew=$(( -skew )); fi
if (( skew > MAX_SKEW )); then
  echo "znacznik czasu poza dopuszczalnym oknem ${MAX_SKEW} s"
  exit 1
fi

# Dopisek „x” chroni końcowe znaki nowej linii ciała przed obcięciem przez $(...) — podpis dotyczy surowych bajtów.
body="$(cat; printf x)"
body="${body%x}"
mac="$(printf '%s.%s' "$ts" "$body" | openssl dgst -sha256 -hmac "$XP_WEBHOOK_SECRET" | sed 's/^.*= //')"
if [[ "sha256=$mac" == "$signature" ]]; then
  echo "OK"
else
  echo "nieprawidłowy podpis"
  exit 1
fi

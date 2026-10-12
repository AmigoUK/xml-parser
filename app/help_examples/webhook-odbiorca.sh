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
#
# Ochrona przed powtórzeniem (replay): podpis obejmuje tylko „<timestamp>.<ciało>”, bez nagłówka X-XP-Delivery,
# więc w oknie ±300 s identyczne żądanie można przesłać ponownie. Deduplikuj po X-XP-Delivery WYŁĄCZNIE PO
# pozytywnej weryfikacji podpisu (inaczej ktoś bez sekretu mógłby „zająć” cudzy identyfikator), przechowuj
# widziane identyfikatory trwale (np. tabela webhook_deliveries_seen z unikalnym kluczem albo zbiór w Redis
# z TTL > 300 s) i powtórzony identyfikator traktuj jak sukces: odpowiedz 200 bez ponownego przetwarzania.
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
# Do 12 cyfr: dłuższa liczba przepełniłaby arytmetykę basha (64 bity) i zafałszowała różnicę czasu.
if [[ ! "$ts" =~ ^-?[0-9]{1,12}$ || ! "$now" =~ ^-?[0-9]{1,12}$ ]]; then
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
if command -v python3 >/dev/null 2>&1; then
  # Preferowane: sekret zostaje w środowisku procesu i nie trafia do argv (nie widać go w `ps`).
  mac="$(printf '%s.%s' "$ts" "$body" | python3 -I -c '
import hashlib, hmac, os, sys
print(hmac.new(os.environ["XP_WEBHOOK_SECRET"].encode(), sys.stdin.buffer.read(), hashlib.sha256).hexdigest())')"
else
  # UWAGA: w tej gałęzi sekret jest argumentem openssl, więc inni użytkownicy hosta zobaczą go w `ps`.
  # Skrypt służy do lokalnych sprawdzeń; na współdzielonym hoście zainstaluj python3 albo użyj innego odbiorcy.
  mac="$(printf '%s.%s' "$ts" "$body" | openssl dgst -sha256 -hmac "$XP_WEBHOOK_SECRET" | sed 's/^.*= //')"
fi
if [[ "sha256=$mac" == "$signature" ]]; then
  echo "OK"
else
  echo "nieprawidłowy podpis"
  exit 1
fi

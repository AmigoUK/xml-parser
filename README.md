# XML Parser faktur

Uczący się parser faktur strukturalnych (XML, JSON, CSV): REST API dla innych systemów
oraz panel po polsku do „negocjowania” odczytu przy pierwszej fakturze dostawcy.
Specyfikacja: `docs/superpowers/specs/2026-10-10-xml-invoice-parser-design.md`.

## Uruchomienie (Docker)

```bash
cp .env.example .env   # uzupełnij hasła
docker compose up -d --build
# panel: http://<host>:5010
```

## Rozwój lokalny

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
ln -sf ../../tools/pre-commit .git/hooks/pre-commit
pytest
```

## Dane prywatne

Realne faktury trzymaj **wyłącznie** w `private/` (ignorowane przez git).
Test `tests/test_no_private_data.py` (i hook pre-commit) szuka w śledzonych plikach
zakazanych tokenów (nazwy, NIP-y) wczytywanych z lokalnego pliku
`private/forbidden-tokens.txt` (jeden token na linię, małymi literami, `#` = komentarz).
Plik jest ignorowany przez git; bez niego skan jest pomijany — utwórz go na każdej maszynie deweloperskiej.

## Tryb demo

`DEMO_MODE=1` włącza publiczną stronę „O demo” **z danymi logowania admina** i kluczem API demo.
Nie używaj `DEMO_MODE=1` na instancji z prawdziwymi danymi. Wdrożenia demo muszą używać
jednorazowych (throwaway) danych logowania, bo strona pokazuje je publicznie.

## Sieć Docker (`XP_SUBNET`)

Domyślna sieć Compose ma jawną podsieć `${XP_SUBNET:-10.210.10.0/24}`. Gdy pule adresów Dockera
na hoście są wyczerpane lub podsieć koliduje z inną, ustaw w `.env` własną wartość `XP_SUBNET`.

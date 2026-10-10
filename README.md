# XML Parser faktur

Uczący się parser faktur strukturalnych (XML, JSON, CSV): REST API dla innych systemów
oraz panel po polsku do „negocjowania” odczytu przy pierwszej fakturze dostawcy.
Specyfikacja: `docs/superpowers/specs/2026-10-10-xml-invoice-parser-design.md`.

## Uruchomienie (Docker)

```bash
cp .env.example .env   # uzupełnij hasła
docker compose up -d --build
# panel (Tailscale MagicDNS): http://<nazwa-hosta>.<tailnet>.ts.net:${APP_PORT}   (domyślnie APP_PORT=18506; kontener nasłuchuje wewnętrznie na 5010)
```

Domyślnie port jest publikowany **tylko na 127.0.0.1** (`APP_BIND`). Docker omija ufw, więc `0.0.0.0`
wystawia aplikację na całą sieć. Aby udostępnić panel przez Tailscale, ustaw w `.env`
`APP_BIND=<IP interfejsu tailscale0>` (`tailscale ip -4`) i zrestartuj stack.

`MARIADB_PASSWORD` i `MARIADB_ROOT_PASSWORD` są wymagane (compose przerwie start bez nich).
Kontener aplikacji działa jako użytkownik nie-root (uid 10001); entrypoint przy starcie naprawia
właściciela wolumenu storage i czeka na bazę (migracje z ponawianiem). `/healthz` sprawdza połączenie
z bazą (503 przy awarii), a compose ma healthcheck usługi `app`. Limity zasobów: `APP_MEM_LIMIT`,
`APP_CPUS`, `DB_MEM_LIMIT`, `DB_CPUS`. Logi dockera są rotowane (10 MB x 3). Zależności runtime
są przypięte w `requirements.lock` (używany w obrazie), obrazy bazowe w konkretnych wersjach.

## Kopie zapasowe i odtwarzanie

```bash
tools/backup.sh          # dump MariaDB + archiwum storage do backups/<data>/ (retencja 14 dni; argument = liczba dni)
# cron (codziennie 03:15):  15 3 * * *  cd /ścieżka/do/xml-parser && tools/backup.sh >> backups/backup.log 2>&1
```

Odtwarzanie (na działającym stacku; **nadpisuje bieżące dane**):

```bash
B=backups/<data>
gunzip -c $B/db.sql.gz | docker compose exec -T db sh -c 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb -uroot'
gunzip -c $B/storage.tar.gz | docker compose exec -T app tar -C /data/storage -xf -
docker compose restart app
```

Okresowo sprawdź kopię, odtwarzając ją na osobnym środowisku.

Serwer: gunicorn z workerami wątkowymi (`-k gthread -w 2 --threads 8 --timeout 60`), dzięki czemu
bezczynne połączenia przeglądarki nie blokują aplikacji. Ustawienia można nadpisać zmienną
`GUNICORN_CMD_ARGS` (np. w `.env`: `GUNICORN_CMD_ARGS=-k gthread -w 4 --threads 16 --timeout 90`);
gdy zmienna jest ustawiona, zastępuje całe powyższe domyślne zestawienie flag.

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

Domyślnie `DEMO_MODE=0`. `DEMO_MODE=1` włącza publiczną stronę „O demo” (opis, próbki faktur,
e-mail konta demo) oraz kartotekę i klucz API demo. Strona **nigdy nie pokazuje hasła** —
hasło ustawiasz w `ADMIN_PASSWORD` w `.env`. Klucz API demo widzą tylko zalogowani, a reset danych
(„Wyczyść dane demo”) może wykonać tylko administrator. Nie używaj `DEMO_MODE=1` na instancji
z prawdziwymi danymi.

## Bezpieczeństwo panelu

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `SESSION_COOKIE_SECURE` | `0` | `1` = ciasteczka sesji tylko po HTTPS. Domyślnie wyłączone, bo demo działa po HTTP przez Tailscale (tunel szyfrowany). Włącz, gdy panel stoi za TLS (np. `tailscale serve` / reverse proxy z HTTPS) — inaczej logowanie przestanie działać. |
| `TRUSTED_PROXY_COUNT` | `0` | Liczba zaufanych reverse proxy przed aplikacją. `0` = nagłówki `X-Forwarded-*` ignorowane (bez proxy ktoś mógłby podszyć IP). Ustaw `1`, gdy aplikacja stoi za jednym proxy (adres klienta, schemat https). |
| `LOGIN_MAX_ATTEMPTS` | `5` | Liczba nieudanych logowań (na e-mail i osobno na adres IP), po której logowanie jest blokowane. `0` wyłącza limit. |
| `LOGIN_LOCKOUT_MINUTES` | `15` | Okno liczenia nieudanych prób i czas blokady. |

Pozostałe zabezpieczenia: nagłówki `Content-Security-Policy` (bez skryptów inline; `'unsafe-eval'`
jest wymagany przez standardowy build Alpine.js), `X-Frame-Options: DENY`, `X-Content-Type-Options`,
`Referrer-Policy`; ciasteczka `HttpOnly` + `SameSite=Lax`, sesja wygasa po 8 h; wylogowanie
(i zmiana hasła) unieważnia wszystkie wcześniej wydane ciasteczka sesji użytkownika.
Nieudane i zablokowane logowania trafiają do „Historii” (`login_failed`, `login_blocked`).
Klucz API widzi tylko swoje dokumenty i dostawców z tych dokumentów; podpowiedzi z kartoteki
(towary, inni dostawcy, szablony) nie są zwracane przez API.

## Sieć Docker (`XP_SUBNET`)

Domyślna sieć Compose ma jawną podsieć `${XP_SUBNET:-10.210.10.0/24}`. Gdy pule adresów Dockera
na hoście są wyczerpane lub podsieć koliduje z inną, ustaw w `.env` własną wartość `XP_SUBNET`.

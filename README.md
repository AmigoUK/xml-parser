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

`DEMO_MODE=1` włącza publiczną stronę „O demo” **z danymi logowania admina** i kluczem API demo.
Nie używaj `DEMO_MODE=1` na instancji z prawdziwymi danymi. Wdrożenia demo muszą używać
jednorazowych (throwaway) danych logowania, bo strona pokazuje je publicznie.

## Sieć Docker (`XP_SUBNET`)

Domyślna sieć Compose ma jawną podsieć `${XP_SUBNET:-10.210.10.0/24}`. Gdy pule adresów Dockera
na hoście są wyczerpane lub podsieć koliduje z inną, ustaw w `.env` własną wartość `XP_SUBNET`.

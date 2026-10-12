# Wdrożenie na nowej platformie

Lista kontrolna i procedury dla przeniesienia aplikacji poza obecny host (Docker Compose + `tailscale serve`).
Uzupełnia [README](../README.md) („Uruchomienie (Docker)”, „Bezpieczeństwo panelu”, „Kopie zapasowe”).

## 1. Zmienne środowiskowe — kontrakt

Kontener aplikacji dostaje **tylko** zmienne wymienione w `docker-compose.yml` (`services.app.environment`) — bez
`MARIADB_ROOT_PASSWORD` i innych sekretów usługi `db`. Platforma bez pliku `.env` (K8s, Portainer, Cloud Run) musi
przekazać je sama. Wartości przykładowe i opisy: [`.env.example`](../.env.example).

| Zmienna | Wymagana | Uwagi |
|---|---|---|
| `SECRET_KEY` | tak | min. 32 losowe znaki; z wartością przykładową aplikacja odmawia startu |
| `DATABASE_URL` | tak | `mysql+pymysql://użytkownik:hasło@host:3306/baza?charset=utf8mb4`; entrypoint odmawia startu bez niej i dla `sqlite:` |
| `STORAGE_DIR` | nie (`/data/storage`) | wolumen trwały, właściciel uid 10001 (K8s: `securityContext.fsGroup: 10001`, `runAsUser: 10001`) |
| `TRUSTED_PROXY_COUNT` | **za proxy: tak** | liczba reverse proxy przed aplikacją; `0` za proxy = wszystkie żądania z jednego IP → limit logowań per IP działa jak globalny (aplikacja ostrzega w logu, gdy zobaczy `X-Forwarded-For`) |
| `SESSION_COOKIE_SECURE` | za TLS: `1` | przy `TRUSTED_PROXY_COUNT>0` i `0` ostrzeżenie w logu przy starcie |
| `PREFERRED_URL_SCHEME` | za TLS: `https` | adresy zewnętrzne budowane poza żądaniem |
| `DEMO_MODE` | `0` | nigdy `1` na instancji z prawdziwymi danymi |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | pierwszy start | hasło min. 10 znaków, nie przykładowe — inaczej konto nie powstaje |
| `APP_INTERNAL_PORT` / `PORT` | nie (`5010`) | `PORT` platformy ma pierwszeństwo (Cloud Run, Heroku); ten sam port czyta sonda `HEALTHCHECK` |
| `MIGRATE_ON_START` | nie (`1`) | `0` = migracje i seed uruchamia osobne zadanie (init container / job) |
| `MIGRATE_LOCK_TIMEOUT` | nie (`600`) | ile sekund replika czeka na blokadę migracji |
| `DEMO_API_KEY` | tylko demo | min. 24 znaki; wartość z `.env.example` jest odrzucana (klucz nie powstaje) |
| `SESSION_HOURS` | nie (`8`) | czas życia sesji panelu w godzinach |
| `AUDIT_RETENTION_DAYS` | nie (`90`) | retencja wpisów logowań dla `flask prune-audit` (cron) |
| `GUNICORN_WORKERS`, `GUNICORN_THREADS`, `GUNICORN_TIMEOUT`, `GUNICORN_WORKER_TMP_DIR` | nie (`2`, `8`, `60`, `/dev/shm`) | pojedyncze flagi gunicorna; `GUNICORN_CMD_ARGS` zastępuje cały zestaw |
| `PUBLIC_BASE_URL` | **za proxy: tak** | publiczny adres panelu (`https://xp.example.com`) w polu `document_url` webhooków; bez niej w `document_url` jest host żądania, które zmieniło status; poza żądaniem (np. CLI) — `null` |
| `WEBHOOK_ALLOWED_HOSTS` | gdy odbiorca jest w sieci prywatnej / tailnecie | nazwy hostów i podsieci CIDR po przecinku (np. `erp.local,100.64.0.0/10`); domyślnie adresy prywatne, loopback, link-local i CGNAT są blokowane (SSRF) |
| `WEBHOOK_ALLOW_HTTP` | `0` | `1` dopuszcza `http://` — tylko testy i sieć wewnętrzna; produkcyjnie https |
| `WEBHOOK_RETENTION_DAYS` | nie (`30`) | retencja zakończonych dostaw dla `flask prune-webhooks` (cron) |
| `WEBHOOK_HEARTBEAT_FILE` | nie (puste) | plik heartbeat workera (healthcheck); compose ustawia go sam, na innej platformie wskaż plik na wolumenie workera |
| `WORKER_MEM_LIMIT`, `WORKER_CPUS` | nie (`512m`, `1.0`) | limity usługi `worker` w compose |
| `DB_WAIT_ATTEMPTS`, `MAX_*`, `LOGIN_*` | nie | jak w `.env.example` |

Aplikacja **wymaga własnej (sub)domeny**: wdrożenie pod podścieżką (`https://firma.pl/xml-parser/`) nie jest obsługiwane —
adresy w Pomocy, w przykładach integracji i w Swagger UI są liczone od korzenia hosta.

Nie kopiuj `.env` ze starego hosta 1:1: `APP_BIND` z adresem `tailscale0` nie istnieje na nowej maszynie
(`docker compose up` kończy się „cannot assign requested address”), a `XP_SUBNET` może kolidować z sieciami nowego hosta.

## 2. Reverse proxy (nginx, ingress, Traefik)

Aplikacja przyjmuje pliki do `MAX_DOCUMENT_BYTES` + 64 KB (domyślnie ~10,06 MB) i odpowiada własnym JSON-em 413
(`error.code = too_large`), na który liczą klienci integracji. Proxy musi przepuścić taki rozmiar i przekazać komplet
nagłówków `X-Forwarded-*`:

```nginx
# /etc/nginx/conf.d/xml-parser.conf — fragment server { listen 443 ssl; … }
client_max_body_size 11m;                 # ≥ MAX_DOCUMENT_BYTES + 64 KB, inaczej nginx odpowie własną stroną 413
proxy_read_timeout    75s;                # ≥ gunicorn --timeout 60
proxy_send_timeout    75s;
# aplikacja sama dodaje Strict-Transport-Security, gdy widzi HTTPS (X-Forwarded-Proto przez ProxyFix); wpis na proxy
# obejmuje też strony błędów samego proxy
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

limit_req_zone $binary_remote_addr zone=xp_login:1m rate=10r/m;
limit_req_zone $binary_remote_addr zone=xp_api:10m  rate=60r/m;

location /login { limit_req zone=xp_login burst=5 nodelay; proxy_pass http://127.0.0.1:18506; include /etc/nginx/xp-proxy.inc; }
location /api/  { limit_req zone=xp_api   burst=30;        proxy_pass http://127.0.0.1:18506; include /etc/nginx/xp-proxy.inc; }
location /      {                                          proxy_pass http://127.0.0.1:18506; include /etc/nginx/xp-proxy.inc; }
```

```nginx
# /etc/nginx/xp-proxy.inc
proxy_set_header Host              $host;          # host publiczny, bez portu wewnętrznego
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Host  $host;
proxy_http_version 1.1;
```

W `.env` aplikacji: `TRUSTED_PROXY_COUNT=1` (jedno proxy), `SESSION_COOKIE_SECURE=1`, `PREFERRED_URL_SCHEME=https`,
`APP_BIND=127.0.0.1`. Ingress-nginx: `nginx.ingress.kubernetes.io/proxy-body-size: 11m`,
`proxy-read-timeout: "75"`; Traefik: `buffering.maxRequestBodyBytes` ≥ 11 MB albo bez buforowania. Dwa proxy
(np. CDN + ingress) = `TRUSTED_PROXY_COUNT=2`.

## 3. Kontener i platforma

- **Obraz** buduj na docelowej architekturze (`docker buildx build --platform linux/amd64 …` albo build na hoście
  docelowym) — zależności z rozszerzeniami C (lxml, regex, RapidFuzz, cryptography) instalują się z kół dla danej
  platformy.
- **Sonda zdrowia** jest w obrazie (`HEALTHCHECK` → `/healthz`, `start-period` 60 s). K8s: `readinessProbe` i
  `livenessProbe` na `/healthz`, `initialDelaySeconds` ≥ czas migracji przy pierwszym starcie (przebudowa tabeli
  `documents` w `86ccf8021da9` na dużej bazie trwa minuty) — inaczej liveness zabije kontener w trakcie migracji.
- **Repliki i migracje.** Entrypoint uruchamia `flask db upgrade` i `flask seed` pod blokadą po stronie bazy
  (`GET_LOCK('xmlparser_migrate')`, `app/dblock.py`): przy kilku replikach migruje jedna, reszta czeka
  (`MIGRATE_LOCK_TIMEOUT`) i wykonuje no-op. Alternatywa dla platform z zadaniami: `MIGRATE_ON_START=0` w replikach i
  osobny job `flask db upgrade && flask seed` przed rolloutem.
- **Wolumen storage.** Entrypoint (jako root, przed `setpriv`) zmienia właściciela katalogu tylko, gdy nie należy do
  uid 10001; na wolumenie sieciowym (NFS/CIFS) chown może się nie udać — wtedy ustaw właściciela po stronie
  platformy (`fsGroup: 10001`, opcje montowania `uid=10001,gid=10001`). Brak prawa zapisu = kontener kończy się
  czytelnym błędem konfiguracji.
- **Baza zarządzana** (RDS, Cloud SQL, osobny serwer MariaDB ≥ 11.4): usuń usługę `db` i `depends_on` z compose
  (albo przenieś `db` do profilu), ustaw `DATABASE_URL` z `?charset=utf8mb4`, kolację bazy `utf8mb4_unicode_ci`.
  Wtyczki uwierzytelniania `caching_sha2_password` / `ed25519` działają — obraz ma pakiet `cryptography`; błąd
  użytkownika/hasła/bazy (1044, 1045, 1049, 1698) kończy start od razu, bez 10 ponowień.
- **Zasoby.** gunicorn: `GUNICORN_WORKERS` (2) × `GUNICORN_THREADS` (8), `GUNICORN_TIMEOUT` (60 s);
  `--worker-tmp-dir /dev/shm` jest dodawany tylko, gdy katalog istnieje (`GUNICORN_WORKER_TMP_DIR` zmienia ścieżkę),
  więc runtime bez `/dev/shm` startuje. `GUNICORN_CMD_ARGS` zastępuje cały zestaw flag. Pamięć ~1 GB na aplikację przy
  plikach 10 MB.
- **Worker webhooków.** Drugi kontener z tego samego obrazu (`command: flask webhooks-worker`), bez portów, z tymi
  samymi zmiennymi co `app` i wolumenem storage (heartbeat), ale z `MIGRATE_ON_START=0` — migracje i seed robi `app`
  (worker startuje po `service_healthy` aplikacji; na innej platformie uruchom go po migracjach). Healthcheck
  sprawdza wiek pliku `WEBHOOK_HEARTBEAT_FILE` (< 60 s) zamiast `/healthz`; `restart: unless-stopped`, SIGTERM kończy
  pętlę po bieżącej dostawie i wychodzi (przy twardym zabiciu dzierżawione dostawy wracają po wygaśnięciu dzierżawy). Może być wiele workerów (dostawy są blokowane dzierżawą), ale jeden wystarcza. Bez
  workera dostawy zostają `pending`; awaryjnie: `docker compose run --rm -T worker flask webhooks-worker --once` z crona (`-T`, bo cron nie ma TTY; wpis musi najpierw `cd` do katalogu projektu). Usuwanie starych dostaw:
  `docker compose exec -T app flask prune-webhooks` (cron, też z `cd` do katalogu projektu; `WEBHOOK_RETENTION_DAYS`). Zrzut bazy zawiera sekrety webhooków
  (`api_keys.webhook_secret`) — kopie traktuj jak sekret.
- **Hasło administratora i dziennik.** Po wdrożeniu (i po każdym wycieku `.env`) ustaw hasło poleceniem
  `flask set-admin-password` (albo „Zmień hasło” w panelu) — seed nie nadpisuje hasła istniejącego konta. Do crona:
  `flask prune-audit` (retencja wpisów logowań, `AUDIT_RETENTION_DAYS`).

## 4. Przeniesienie danych (stary host → nowy)

1. Na starym hoście: `tools/backup.sh` (albo `BACKUP_DIR=/mnt/kopie tools/backup.sh`) → `db.sql.gz` + `storage.tar.gz`.
   Zatrzymaj przyjmowanie dokumentów (wyłącz klucze API albo zatrzymaj `app`), żeby kopia była spójna.
2. Na nowym hoście: `.env` wg sekcji 1, `docker compose up -d db` i poczekaj na `healthy`.
3. Import bazy: `gunzip -c db.sql.gz | docker compose exec -T db sh -c 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb -uroot'`
   (zrzut zawiera `CREATE DATABASE`; przy bazie zarządzanej użyj klienta `mariadb` z `DATABASE_URL`).
4. `docker compose up -d app` — entrypoint czeka na bazę i dokłada brakujące migracje
   (`docker compose logs -f app`; `docker compose exec app flask db current` ma pokazać głowę `(head)`).
5. Pliki dokumentów: `gunzip -c storage.tar.gz | docker compose exec -T app tar -C /data/storage -xf -`
   (przy innym `STORAGE_DIR` — jego ścieżka). Archiwum nie zawiera plików tymczasowych `.tmp-*`.
6. Weryfikacja: `curl -fsS http://127.0.0.1:18506/healthz` → `{"status":"ok","db":"ok"}`;
   `docker compose exec app flask check-storage` → `brakujących plików: 0` (kod wyjścia 1 i lista id, gdy czegoś brakuje —
   te dokumenty trzeba wgrać ponownie); logowanie do panelu; `GET /api/v1/documents?limit=1` kluczem produkcyjnym.
7. Przełącz DNS / proxy, zostaw stary host w trybie tylko do odczytu przez kilka dni (kopia na wypadek powrotu).

Powrót (rollback): stary stack nadal ma komplet danych do momentu przełączenia; nowe dokumenty przyjęte po
przełączeniu trzeba przenieść wstecz tą samą procedurą.

## 5. Po wdrożeniu — sprawdź w logu aplikacji

- brak ostrzeżenia `X-Forwarded-For … TRUSTED_PROXY_COUNT=0` (inaczej proxy jest, a ProxyFix wyłączony),
- brak ostrzeżenia `SESSION_COOKIE_SECURE=0` przy `TRUSTED_PROXY_COUNT>0`,
- brak ostrzeżenia `DEMO_API_KEY jest wartością przykładową…` (klucz demo nie powstał) i `OSTRZEŻENIE: ADMIN_PASSWORD…`,
- `curl -I https://host/login` zwraca `Strict-Transport-Security`, `Permissions-Policy` i `Content-Security-Policy`
  z `script-src 'self'` (bez `'unsafe-eval'`),
- `Baza: mysql+pymysql://…` wskazuje właściwy host (hasło nie jest wypisywane),
- migracje: `docker compose exec app flask db current` → `99f2fe61d963 (head)` (tabela `webhook_deliveries`),
- `docker compose ps` pokazuje `worker` jako `healthy`, a `docker compose logs worker` zawiera `webhooks-worker: start`,
- w panelu „Klucze API” przycisk „Wyślij testowe zdarzenie” przy kluczu z adresem webhooka kończy się dostawą
  `sent` (odbiorca w sieci prywatnej: najpierw `WEBHOOK_ALLOWED_HOSTS`); `PUBLIC_BASE_URL` ustawiony, jeśli za proxy,
- adresy w Pomocy (`/pomoc/integracja`) mają schemat `https` i host publiczny,
- `tools/backup.sh` w cronie z `BACKUP_DIR` na osobnym dysku; raz na kwartał próbne odtworzenie.

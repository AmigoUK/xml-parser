"""Blokada migracji po stronie bazy (MariaDB/MySQL `GET_LOCK`) na start wielu replik naraz.

`python -m app.dblock -- <polecenie…>` wykonuje polecenie, trzymając nazwaną blokadę serwera bazy z `DATABASE_URL`.
Druga replika czeka na zwolnienie (do `MIGRATE_LOCK_TIMEOUT` s, domyślnie 600) i wykonuje to samo polecenie —
`flask db upgrade` i `flask seed` są idempotentne, więc powtórka jest bezpieczna; bez blokady dwie repliki
wykonywałyby ten sam `ALTER TABLE` równocześnie (MariaDB: DDL nietransakcyjny → „Duplicate key name”, kod 1).
Blokadę trzyma osobne połączenie i zwalnia ją po zakończeniu polecenia (także po jego błędzie); gdy proces zginie,
serwer zwalnia ją sam. Na innych dialektach (SQLite) polecenie wykonuje się bez blokady. Kod wyjścia = kod polecenia.
Moduł bez Flaska — importowalny także poza aplikacją."""
import os
import subprocess
import sys
from contextlib import contextmanager

import sqlalchemy as sa

LOCK_NAME = "xmlparser_migrate"
DEFAULT_TIMEOUT = 600


@contextmanager
def migration_lock(url: str, name: str = LOCK_NAME, timeout: int = DEFAULT_TIMEOUT):
    """Trzyma blokadę `GET_LOCK(name)` przez czas bloku (yield True); na innych dialektach nic nie robi (yield False).
    Gdy blokady nie da się uzyskać w `timeout` sekund — RuntimeError."""
    engine = sa.create_engine(url)
    try:
        if engine.dialect.name not in ("mysql", "mariadb"):
            yield False
            return
        with engine.connect() as conn:
            got = conn.execute(sa.text("SELECT GET_LOCK(:name, :timeout)"),
                               {"name": name, "timeout": int(timeout)}).scalar()
            if got != 1:
                raise RuntimeError(f"Nie udało się uzyskać blokady migracji „{name}” w {timeout} s — inna replika "
                                   "nadal migruje? Sprawdź jej log albo podnieś MIGRATE_LOCK_TIMEOUT.")
            try:
                yield True
            finally:
                conn.execute(sa.text("SELECT RELEASE_LOCK(:name)"), {"name": name})
    finally:
        engine.dispose()


def run_locked(url: str, command: list[str], timeout: int = DEFAULT_TIMEOUT) -> int:
    """Wykonuje polecenie pod blokadą migracji; zwraca jego kod wyjścia."""
    with migration_lock(url, timeout=timeout):
        return subprocess.call(command)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if not argv:
        print("Użycie: python -m app.dblock -- <polecenie> [argumenty…]", file=sys.stderr)
        return 2
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("Brak DATABASE_URL — blokada migracji wymaga adresu bazy.", file=sys.stderr)
        return 2
    try:
        return run_locked(url, argv, timeout=int(os.environ.get("MIGRATE_LOCK_TIMEOUT", DEFAULT_TIMEOUT)))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

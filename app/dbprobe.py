"""Sonda połączenia z bazą dla entrypointu kontenera (`python -m app.dbprobe`).

Kody wyjścia: 0 = połączenie działa; 3 = baza nieosiągalna albo jeszcze niegotowa (entrypoint ponawia z odstępem);
1 = błąd konfiguracji, którego ponawianie nic nie da: zły `DATABASE_URL`, brak sterownika lub pakietu
`cryptography` (nowsze wtyczki uwierzytelniania MariaDB), zły użytkownik/hasło/baza (1044, 1045, 1049, 1698),
nieotwieralny plik SQLite. Na stderr wypisuje cel połączenia bez hasła. Moduł bez Flaska."""
import os
import sys

# błędy MariaDB/MySQL, przy których czekanie nie pomoże (brak uprawnień, złe hasło, nieznana baza, zła wtyczka)
AUTH_ERRORS = {1044: "brak uprawnień do bazy", 1045: "zły użytkownik lub hasło", 1049: "nieznana baza danych",
               1698: "uwierzytelnianie odrzucone (wtyczka unix_socket / brak hasła)"}


def main(url: str | None = None) -> int:
    url = url if url is not None else os.environ.get("DATABASE_URL", "")
    try:
        import sqlalchemy as sa
        from sqlalchemy.exc import OperationalError
        parsed = sa.make_url(url)
        engine = sa.create_engine(parsed)
    except Exception as exc:  # noqa: BLE001 - zły URL, brak sterownika itp.
        print(f"Błąd konfiguracji bazy (DATABASE_URL): {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"Baza: {parsed.render_as_string(hide_password=True)}", file=sys.stderr)
    try:
        with engine.connect():
            pass
    except OperationalError as exc:
        code = exc.orig.args[0] if exc.orig is not None and exc.orig.args else None
        if code in AUTH_ERRORS:
            print(f"Błąd konfiguracji bazy ({AUTH_ERRORS[code]}): {exc.orig}", file=sys.stderr)
            return 1
        print(f"OperationalError: {exc.orig if exc.orig is not None else exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - np. RuntimeError o braku `cryptography`
        print(f"Błąd konfiguracji bazy: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Biblioteki wendorowane (`app/static/vendor/`)

Panel nie ładuje nic z CDN. Każdy plik ma tu wersję, adres pobrania i sumę SHA-256 — `tests/test_vendor_manifest.py`
sprawdza, że sumy zgadzają się z plikami i że nie ma plików bez wpisu. Alpine.js jest w buildzie CSP
(`@alpinejs/csp`): wyrażenia w atrybutach parsuje sam, więc `Content-Security-Policy` nie potrzebuje `'unsafe-eval'`.

| Plik | Biblioteka | Wersja | Źródło | SHA-256 |
|---|---|---|---|---|
| `bootstrap.min.css` | Bootstrap (CSS) | `5.3.3` | <https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.3/css/bootstrap.min.css> | `3c8f27e6009ccfd710a905e6dcf12d0ee3c6f2ac7da05b0572d3e0d12e736fc8` |
| `bootstrap.bundle.min.js` | Bootstrap (JS z Popperem) | `5.3.3` | <https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.3/js/bootstrap.bundle.min.js> | `0833b2e9c3a26c258476c46266e6877fc75218625162e0460be9a3a098a61c6c` |
| `alpine-csp.min.js` | Alpine.js — build CSP (@alpinejs/csp) | `3.17.4` | <https://cdn.jsdelivr.net/npm/@alpinejs/csp@3.17.4/dist/cdn.min.js> | `0d18d7f8d7910e2e0212f0f056b12f50bebc3abb7d88d2f7c7cb4c336fe4519a` |
| `swagger-ui.css` | Swagger UI (CSS) | `5.18.2` | <https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.18.2/swagger-ui.css> | `8f33d996025317049d4a9864f421eab2b2a247872f388026fa94c654913259e7` |
| `swagger-ui-bundle.js` | Swagger UI (JS) | `5.18.2` | <https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.18.2/swagger-ui-bundle.js> | `c50b94bbc4f02394326fb7aed1f4fb693b3677f4b3d3344e0d6131808cbf281f` |

## Aktualizacja

1. Sprawdź poradniki bezpieczeństwa dla nowej wersji (GitHub Advisories / CVE) i changelog biblioteki.
2. Pobierz plik z adresu w tabeli (z nowym numerem wersji) i podmień go w tym katalogu.
3. Wpisz nową wersję, adres i `sha256sum <plik>` do tabeli; uruchom `pytest tests/test_vendor_manifest.py`.
4. Przy zmianie Alpine.js sprawdź edytor mapowań i formularz wgrywania w przeglądarce (tylko build CSP
   `@alpinejs/csp` — standardowy wymagałby `'unsafe-eval'`).

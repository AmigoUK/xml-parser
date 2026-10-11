"""Treść sekcji „Pomoc”: spis tematów, rejestr kodów problemów, opisy statusów i transformacji.

Rejestr ``ISSUE_HELP`` musi obejmować dokładnie te kody problemów, które emituje kod źródłowy
(konstruktor ``Issue`` z kodem jako literałem w ``app/`` oraz funkcja ``_issue`` w migracjach) — pilnuje tego ``tests/test_web_help.py``.
"""
from __future__ import annotations

# slug → tytuł; kolejność = kolejność w menu i nawigacji „poprzedni / następny”
TOPICS: list[dict] = [
    {"slug": "jak-to-dziala", "title": "Jak to działa",
     "summary": "Droga faktury od pliku do zatwierdzonego dokumentu i na czym polega „uczenie”."},
    {"slug": "pierwsza-faktura", "title": "Pierwsza faktura dostawcy",
     "summary": "Negocjacja w widoku dokumentu: „tylko ta faktura” albo „zapamiętaj w szablonie”."},
    {"slug": "edytor-mapowan", "title": "Edytor mapowań",
     "summary": "Pełnoekranowy edytor reguł szablonu i wszystkie transformacje z białej listy."},
    {"slug": "szablony", "title": "Szablony i wersje",
     "summary": "Wersje szablonu, porównywanie, przywracanie i usuwanie."},
    {"slug": "jednostki", "title": "Jednostki, aliasy i przeliczniki",
     "summary": "Jak jednostka z faktury staje się naszą jednostką i jak działa przelicznik."},
    {"slug": "towary", "title": "Kartoteka i mapowania towarów",
     "summary": "Kartoteka towarów, import CSV i przypisywanie pozycji po kodzie, GTIN lub nazwie."},
    {"slug": "statusy-i-problemy", "title": "Statusy i problemy",
     "summary": "Wszystkie statusy dokumentu i kody problemów — co znaczą i jak je rozwiązać."},
    {"slug": "api", "title": "REST API",
     "summary": "Klucze API, przykłady curl dla każdego endpointu, kody odpowiedzi i limity."},
    {"slug": "faq", "title": "Najczęstsze pytania",
     "summary": "Krótkie odpowiedzi na pytania, które pojawiają się najczęściej."},
]
TOPICS_BY_SLUG = {t["slug"]: t for t in TOPICS}


# Statusy dokumentu (klucze = app.models.STATUS_LABELS).
STATUS_HELP: dict[str, str] = {
    "received": "Stan przejściowy: plik zapisano, dokument czeka na przetworzenie. Zwykle widoczny tylko "
                "przez ułamek sekundy — przetwarzanie rusza od razu po przyjęciu.",
    "approved": "Faktura odczytana bez problemów blokujących. Mogą wystąpić ostrzeżenia (np. niezgodność "
                "sumy w pozycji) — warto je przejrzeć, ale nie wstrzymują dokumentu.",
    "needs_review": "Jest co najmniej jeden problem blokujący. Dokument czeka w „Kolejce” na decyzję "
                    "operatora; po każdej decyzji poza „Odrzuć” jest przetwarzany ponownie.",
    "duplicate": "Ta sama faktura jest już w systemie (ten sam plik albo ten sam dostawca, rodzaj i numer "
                 "dokumentu) w tym samym zakresie — kluczu API albo panelu.",
    "rejected": "Dokument odrzucony. Automatycznie — gdy pliku nie da się odczytać albo ma zbyt wiele "
                "pozycji (można go przetworzyć ponownie) — albo ręcznie przez operatora (wtedy cofa to "
                "tylko „Przywróć” w panelu).",
}


# Kody problemów. blocking: "tak" | "nie" | "zależnie" (+ blocking_note).
ISSUE_HELP: dict[str, dict] = {
    "unknown_supplier": {
        "title": "Nie rozpoznano dostawcy",
        "blocking": "tak",
        "description": "Żaden dostawca w bazie nie ma NIP/VAT odczytanego z faktury (albo NIP-u nie udało "
                       "się odczytać).",
        "how_to_fix": "Utwórz nowego dostawcę z danych faktury albo wskaż istniejącego. Gdy struktura pliku "
                      "pasuje do szablonu innego dostawcy, panel proponuje skopiowanie jego reguł. Rozwiąż go "
                      "najpierw — bez dostawcy nie powstanie szablon, alias, przelicznik ani mapowanie towaru.",
    },
    "unmapped_field": {
        "title": "Brak wymaganego pola",
        "blocking": "zależnie",
        "blocking_note": "Blokuje; brak pozycji w korekcie lub fakturze zaliczkowej to tylko ostrzeżenie.",
        "description": "Szablon nie wskazuje, skąd wziąć wymagane pole (np. numer, datę, walutę, sumę brutto, "
                       "dane dostawcy), albo nie wskazano elementu z pozycjami faktury.",
        "how_to_fix": "Wybierz podpowiadaną ścieżkę w pliku, wskaż ją ręcznie albo ustaw stałą wartość "
                      "domyślną (np. PLN). Dla pól pozycji wybierz „zapamiętaj w szablonie”. Szersze zmiany "
                      "— w edytorze mapowań.",
    },
    "transform_error": {
        "title": "Błąd transformacji",
        "blocking": "zależnie",
        "blocking_note": "Blokuje dla pól wymaganych, dla pozostałych — ostrzeżenie.",
        "description": "Krok łańcucha transformacji nie dał się wykonać (np. data nie pasuje do formatu, "
                       "wartość nie pasuje do wyrażenia regularnego, kod GS1 nie zawiera wskazanego AI).",
        "how_to_fix": "Popraw łańcuch transformacji pola w edytorze mapowań albo wskaż inną ścieżkę.",
    },
    "invalid_value": {
        "title": "Niepoprawna wartość",
        "blocking": "zależnie",
        "blocking_note": "Blokuje dla pól wymaganych, dla pozostałych — ostrzeżenie.",
        "description": "Wartość nie pasuje do typu pola: nieznana waluta (oczekiwany kod ISO 4217), "
                       "nierozpoznana data, nieprawidłowa liczba albo GTIN z błędną cyfrą kontrolną.",
        "how_to_fix": "Sprawdź, czy pole wskazuje właściwy element pliku; w razie potrzeby dodaj "
                      "transformację (np. „date”, „map”, „decimal”) albo ustaw wartość domyślną.",
    },
    "ambiguous_number": {
        "title": "Niejednoznaczna liczba",
        "blocking": "tak",
        "description": "Liczba w postaci „1,234” lub „1.234” — separator może być dziesiętny albo "
                       "tysięcy, a reszta dokumentu nie rozstrzyga, który to przypadek. Błąd o trzy rzędy "
                       "wielkości nie może przejść po cichu.",
        "how_to_fix": "Wybierz w panelu jeden z gotowych wariantów (z podglądem wartości) albo dodaj do "
                      "pola transformację {\"decimal\": \",\"} lub {\"decimal\": \".\"} i przetwórz "
                      "dokument ponownie.",
    },
    "vat_rate_fraction": {
        "title": "Stawka VAT wygląda na ułamek",
        "blocking": "nie",
        "description": "Stawka VAT jest liczbą między 0 a 1 (np. 0,23 zamiast 23) — prawdopodobnie pole "
                       "wskazuje ułamek, a nie procent.",
        "how_to_fix": "Sprawdź mapowanie pola „Stawka VAT %”; w razie potrzeby wskaż inne pole pliku.",
    },
    "unknown_unit": {
        "title": "Nieznana jednostka miary",
        "blocking": "tak",
        "description": "Jednostka z faktury (np. „pcs”, „kart.”) nie jest naszym kodem jednostki ani "
                       "aliasem — ani tego dostawcy, ani globalnym.",
        "how_to_fix": "Wskaż odpowiadającą jej naszą jednostkę. Z „zapamiętaj” powstaje alias dostawcy; "
                      "bez — przypisanie tylko dla tej faktury.",
    },
    "unmapped_product": {
        "title": "Nie przypisano towaru",
        "blocking": "tak",
        "description": "Pozycji nie udało się dopasować do towaru z naszej kartoteki (po kodzie dostawcy, "
                       "GTIN ani nazwie) albo ręcznie przypisany towar usunięto z kartoteki.",
        "how_to_fix": "Przypisz towar z kartoteki albo dodaj nowy. Z „zapamiętaj” powstaje mapowanie "
                      "towaru dostawcy, więc kolejne faktury dopasują się same.",
    },
    "missing_conversion": {
        "title": "Brak przelicznika jednostki",
        "blocking": "tak",
        "description": "Jednostka pozycji nie jest jednostką bazową, a nie ma przelicznika na jednostkę "
                       "bazową (np. 1 karton = ? szt).",
        "how_to_fix": "Podaj przelicznik — dla wszystkich towarów dostawcy albo tylko dla tego towaru. "
                      "Kropka jest zawsze separatorem dziesiętnym (np. 1.125). Przelicznik zawsze zostaje "
                      "zapamiętany.",
    },
    "sum_mismatch_line": {
        "title": "Niezgodna suma w pozycji",
        "blocking": "nie",
        "description": "W pozycji ilość × cena różni się od wartości netto albo netto + VAT od brutto "
                       "o więcej niż 0,01.",
        "how_to_fix": "Sprawdź, czy pola ilości, ceny i wartości wskazują właściwe elementy (np. cena "
                      "brutto zamiast netto). Jeśli faktura naprawdę tak wygląda — ostrzeżenie można "
                      "zostawić.",
    },
    "sum_mismatch_total": {
        "title": "Niezgodna suma faktury",
        "blocking": "tak",
        "description": "Suma netto pozycji różni się od sumy netto faktury albo netto + VAT faktury od "
                       "brutto (tolerancja 0,01).",
        "how_to_fix": "Sprawdź mapowanie sum i wartości pozycji oraz element z pozycjami (czy nie pomija "
                      "części pozycji). Popraw reguły w edytorze mapowań i zapisz nową wersję.",
    },
    "duplicate": {
        "title": "Duplikat",
        "blocking": "tak",
        "description": "Ten sam plik albo faktura o tym samym dostawcy, rodzaju i numerze jest już w systemie "
                       "w tym samym zakresie (ten sam klucz API albo panel). Dokumenty różnych zakresów nie "
                       "są dla siebie duplikatami.",
        "how_to_fix": "Jeśli to rzeczywiście inna faktura — „To nie duplikat — przetwórz”. W przeciwnym "
                      "razie „Odrzuć”. Gdy oryginał zostanie odrzucony, jego duplikaty są przeliczane.",
    },
    "reprocess_required": {
        "title": "Wymaga ponownego przetworzenia",
        "blocking": "tak",
        "description": "Ustawiany przy aktualizacji do v0.2.0: dokument był oznaczony jako duplikat dokumentu "
                       "z innego zakresu (inny klucz API albo panel), a od v0.2.0 różne zakresy nie są dla "
                       "siebie duplikatami.",
        "how_to_fix": "„Przetwórz ponownie” w widoku dokumentu albo POST /api/v1/documents/{id}/reprocess.",
    },
    "unreadable": {
        "title": "Plik nieczytelny",
        "blocking": "tak",
        "description": "Pliku nie da się odczytać: pusty, binarny (np. PDF), w kodowaniu UTF-16/UTF-32, "
                       "niepoprawny XML/JSON/CSV, XML z DOCTYPE/ENTITY, zbyt głęboko zagnieżdżony albo "
                       "z liczbą węzłów ponad limit. Dokument dostaje status „Odrzucona”.",
        "how_to_fix": "Wgraj poprawny plik XML, JSON lub CSV w UTF-8. Ponowne przetworzenie jest możliwe "
                      "(to odrzucenie automatyczne), ale pomoże tylko, gdy zmieniono limit.",
    },
    "too_many_lines": {
        "title": "Zbyt wiele pozycji",
        "blocking": "tak",
        "description": "Liczba pozycji przekracza limit MAX_LINES. Dokument dostaje status „Odrzucona”.",
        "how_to_fix": "Podziel fakturę na mniejsze pliki albo poproś administratora o podniesienie limitu "
                      "MAX_LINES i przetwórz dokument ponownie.",
    },
    "file_missing": {
        "title": "Brak pliku źródłowego",
        "blocking": "tak",
        "description": "W magazynie plików nie ma pliku tego dokumentu (np. utracony wolumen storage).",
        "how_to_fix": "Wgraj fakturę ponownie albo odtwórz katalog storage z kopii zapasowej.",
    },
    "internal_error": {
        "title": "Wewnętrzny błąd przetwarzania",
        "blocking": "tak",
        "description": "Nieoczekiwany błąd podczas przetwarzania (np. uszkodzona reguła szablonu). Dokument "
                       "nie ginie — zostaje zapisany do wyjaśnienia.",
        "how_to_fix": "Sprawdź reguły szablonu w edytorze mapowań; jeśli problem się powtarza, zgłoś go "
                      "administratorowi (szczegóły są w logu aplikacji).",
    },
}


# Transformacje (klucze = app.engine.transforms.REGISTRY). Przykłady są wykonywane w testach.
# step — krok łańcucha w JSON; input / output — wartość przed i po kroku (None = brak wartości).
TRANSFORM_HELP: dict[str, dict] = {
    "trim": {"args": "brak", "step": '"trim"', "input": "  ABC  ", "output": "ABC",
             "note": "Usuwa białe znaki z początku i końca."},
    "upper": {"args": "brak", "step": '"upper"', "input": "abc", "output": "ABC", "note": ""},
    "lower": {"args": "brak", "step": '"lower"', "input": "ABC", "output": "abc", "note": ""},
    "decimal": {"args": "opcjonalny separator dziesiętny: \",\" albo \".\"", "step": '{"decimal": ","}',
                "input": "1 234,50", "output": "1234.5",
                "note": "Bez argumentu separator jest wnioskowany z dokumentu; forma niejednoznaczna "
                        "(„1,234”) daje problem „ambiguous_number”. Wynik zawsze z kropką."},
    "strip_percent": {"args": "brak", "step": '"strip_percent"', "input": "23%", "output": "23",
                      "note": "Typowo przed stawką VAT."},
    "date": {"args": "format daty w notacji strftime (wymagany)", "step": '{"date": "%d.%m.%Y"}',
             "input": "09.10.2026", "output": "2026-10-09",
             "note": "Wynik w formacie RRRR-MM-DD."},
    "regex_extract": {"args": "obiekt {\"pattern\": …, \"group\": …}; group domyślnie 0",
                      "step": '{"regex_extract": {"pattern": "(\\\\d+)$", "group": 1}}',
                      "input": "FV/2026/123", "output": "123",
                      "note": "Wzorzec maks. {max_pattern} znaków, dopasowywane pierwsze {max_input} znaków "
                              "wartości, limit czasu {regex_timeout} s (ochrona przed ReDoS)."},
    "map": {"args": "słownik wartość źródłowa → wartość docelowa", "step": '{"map": {"EA": "szt", "KGM": "kg"}}',
            "input": "EA", "output": "szt", "note": "Wartość spoza słownika przechodzi bez zmian."},
    "convert": {"args": "współczynnik > 0 (liczba albo tekst; kropka = separator dziesiętny)",
                "step": '{"convert": 12}', "input": "2", "output": "24",
                "note": "Mnoży wartość przez współczynnik — ta sama reguła co przy przelicznikach."},
    "constant": {"args": "stała wartość", "step": '{"constant": "PLN"}', "input": None, "output": "PLN",
                 "note": "Zastępuje wartość ze źródła stałą."},
    "concat": {"args": "obiekt {\"paths\": [ścieżki], \"sep\": separator}; sep domyślnie spacja",
               "step": '{"concat": {"paths": ["Faktura/Sprzedawca/Ulica", "Faktura/Sprzedawca/Miasto"], "sep": ", "}}',
               "input": None, "output": "Polna 1, Opole",
               "note": "Łączy wartości kilku elementów (puste są pomijane). W pozycjach ścieżki są "
                       "względne wobec pozycji."},
    "split": {"args": "obiekt {\"sep\": separator, \"index\": nr części}; domyślnie spacja i 0",
              "step": '{"split": {"sep": " ", "index": 1}}', "input": "Kowalski Jan", "output": "Jan",
              "note": "Numeracja części od 0."},
    "negate": {"args": "brak", "step": '"negate"', "input": "100.00", "output": "-100",
               "note": "Zmiana znaku — np. dla korekt."},
    "gs1": {"args": "numer AI, np. \"10\" (partia) albo \"17\" (data ważności)", "step": '{"gs1": "10"}',
            "input": "(01)05909999000013(10)ABC123(17)271231", "output": "ABC123",
            "note": "AI z datą (np. 17) zwraca datę RRRR-MM-DD."},
    "strip_ai_prefix": {"args": "brak", "step": '"strip_ai_prefix"', "input": "0105909999000013",
                        "output": "05909999000013",
                        "note": "Usuwa prefiks AI „01” z 16-cyfrowego zapisu EAN/GTIN; inne wartości bez zmian."},
}


FAQ: list[dict] = [
    {"q": "Dlaczego faktura trafiła do kolejki „Do wyjaśnienia”?",
     "a": "Bo ma co najmniej jeden problem blokujący — najczęściej przy pierwszej fakturze nowego dostawcy "
          "(nieznany dostawca, jednostka, towar). Otwórz dokument i rozwiązuj problemy od góry; po każdej "
          "decyzji dokument jest przetwarzany ponownie.", "link": "statusy-i-problemy"},
    {"q": "Jak cofnąć złą wersję szablonu?",
     "a": "Szablony → wybierz szablon → w tabeli wersji kliknij „Przywróć” przy dobrej wersji. Powstaje nowa "
          "wersja będąca kopią wybranej — historia zostaje. Dokumenty przetworzone wcześniej nie zmieniają się "
          "same; użyj „Przetwórz ponownie”.", "link": "szablony"},
    {"q": "Dlaczego dokument jest duplikatem?",
     "a": "W tym samym zakresie (ten sam klucz API albo panel) jest już ten sam plik albo faktura o tym samym "
          "dostawcy, rodzaju i numerze. Jeśli to inna faktura, wybierz „To nie duplikat — przetwórz”.",
     "link": "statusy-i-problemy"},
    {"q": "Jaki jest limit wielkości pliku i liczby pozycji?",
     "a": "Plik faktury: {max_document}. Pozycji: {max_lines}. Węzłów drzewa (elementy, atrybuty, komórki "
          "CSV): {max_tree_nodes}. Limity ustawia administrator w konfiguracji.", "link": "statusy-i-problemy"},
    {"q": "Jakie formaty są obsługiwane?",
     "a": "XML (dowolny, w tym KSeF i UBL), JSON i CSV, w kodowaniu UTF-8 (CSV także w Windows-1250). Format "
          "rozpoznawany jest po treści pliku, nie po rozszerzeniu. PDF i inne pliki binarne oraz UTF-16/UTF-32 są odrzucane.",
     "link": "jak-to-dziala"},
    {"q": "Czy wgranie XML jest bezpieczne?",
     "a": "Tak: pliki z deklaracją DOCTYPE/ENTITY są odrzucane, encje nie są rozwijane, parser nie sięga do "
          "sieci, a liczba węzłów i głębokość zagnieżdżenia są ograniczone.", "link": "jak-to-dziala"},
    {"q": "Dlaczego zostałem wylogowany?",
     "a": "Sesja wygasa po {session_hours} h bez aktywności. „Wyloguj” unieważnia wszystkie sesje tego konta — także na innych "
          "urządzeniach. Sesja nie jest powiązana z adresem IP ani przeglądarką, więc sama zmiana sieci (np. przejście "
          "z Wi-Fi na LTE) nie wylogowuje; adres IP liczy się natomiast w limicie nieudanych prób logowania.", "link": None},
    {"q": "Ile mam prób logowania?",
     "a": "Po {login_max} nieudanych próbach w ciągu {login_minutes} min dla pary (e-mail, adres IP) ta para "
          "jest blokowana na {login_minutes} min. Dodatkowo obowiązują limity {login_per_ip} prób z jednego IP "
          "(na dowolne konta) w {login_minutes} min i {login_per_email} prób na jedno konto z dowolnych IP "
          "w {login_email_minutes} min.", "link": None},
    {"q": "Czym różni się „tylko ta faktura” od „zapamiętaj w szablonie”?",
     "a": "„Tylko ta faktura” zapisuje decyzję w samym dokumencie. „Zapamiętaj” tworzy nową wersję szablonu "
          "albo wpis w słowniku dostawcy (alias jednostki, mapowanie towaru), więc kolejne faktury rozwiążą się "
          "same.", "link": "pierwsza-faktura"},
    {"q": "Jak przywrócić ręcznie odrzucony dokument?",
     "a": "Otwórz dokument i kliknij „Przywróć”. Ani „Przetwórz ponownie”, ani API (zwraca 409) nie cofają "
          "ręcznego odrzucenia.", "link": "statusy-i-problemy"},
    {"q": "Dlaczego liczba „1,234” blokuje fakturę?",
     "a": "Bo może oznaczać 1,234 albo 1234. Wskaż separator dziesiętny transformacją "
          "{\"decimal\": \",\"} lub {\"decimal\": \".\"} albo wybierz wariant podpowiedziany w panelu.",
     "link": "statusy-i-problemy"},
]

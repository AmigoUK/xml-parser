<!-- Wygenerowano przez tools/export_help.py z sekcji Pomoc w panelu — nie edytuj ręcznie. -->

# Szablony i wersje

**Szablon** to zestaw reguł odczytu faktur jednego dostawcy w jednej strukturze pliku: element z pozycjami, reguły pól nagłówka i pozycji (ścieżka + transformacje) oraz wartości domyślne. Szablon powstaje automatycznie, gdy rozpoznasz dostawcę pierwszej faktury, i nazywa się „&lt;dostawca> — &lt;FORMAT>”. Jeden dostawca może mieć kilka szablonów (np. XML i CSV) — wybierany jest ten, którego odcisk struktury najlepiej pasuje do pliku (podobieństwo zbiorów ścieżek — wspólne ÷ wszystkie — co najmniej 60%).

## Wersje

Reguły nigdy nie są nadpisywane — każda zmiana tworzy **nową wersję**, która od razu staje się aktywna. Nowa wersja powstaje, gdy:

- rozpoznajesz dostawcę pierwszej faktury (komentarz „Pierwsza wersja (z negocjacji)”);
- rozwiązujesz problem z polem z zaznaczonym „zapamiętaj” (komentarz „Mapowanie pola: …”);
- zapisujesz zmiany w [edytorze mapowań](edytor-mapowan.md) (Twój komentarz albo „Zmiana w edytorze mapowań”);
- przywracasz starszą wersję (komentarz „Przywrócono wersję N”).

Każdy dokument pamięta, którą wersją szablonu został odczytany (widać to w nagłówku dokumentu i w polu `template_version` w API).

## Historia i porównanie

*Szablony* → „Wersje” pokazuje tabelę wersji (autor, komentarz, data; aktywna jest oznaczona). U góry wybierz dwie wersje i kliknij „Pokaż różnice” — zobaczysz różnice reguł w formacie JSON (dodane linie na zielono, usunięte na czerwono). Wszystkie zmiany są też zapisywane w *Historii* (kto, kiedy, co).

## Przywrócenie

Przy każdej nieaktywnej wersji jest przycisk „Przywróć”. Przywrócenie **nie usuwa** nowszych wersji — tworzy nową wersję będącą kopią wybranej, więc zawsze można wrócić. Dokumenty odczytane wcześniej nie zmieniają się same — aby odczytać je przywróconymi regułami, użyj „Przetwórz ponownie” w dokumencie (albo `POST /api/v1/documents/{id}/reprocess`).

## Usuwanie

Szablon można usunąć z listy szablonów tylko wtedy, gdy nie jest użyty w żadnym dokumencie.

## Eksport i import

Panel nie ma obecnie funkcji eksportu ani importu szablonów. Reguły dowolnej wersji można podejrzeć w porównaniu wersji.

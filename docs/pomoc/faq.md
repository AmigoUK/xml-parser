<!-- Wygenerowano przez tools/export_help.py z sekcji Pomoc w panelu — nie edytuj ręcznie. -->

# Najczęstsze pytania

## Dlaczego faktura trafiła do kolejki „Do wyjaśnienia”?

Bo ma co najmniej jeden problem blokujący — najczęściej przy pierwszej fakturze nowego dostawcy (nieznany dostawca, jednostka, towar). Otwórz dokument i rozwiązuj problemy od góry; po każdej decyzji dokument jest przetwarzany ponownie. [Więcej →](statusy-i-problemy.md)

## Jak cofnąć złą wersję szablonu?

Szablony → wybierz szablon → w tabeli wersji kliknij „Przywróć” przy dobrej wersji. Powstaje nowa wersja będąca kopią wybranej — historia zostaje. Dokumenty przetworzone wcześniej nie zmieniają się same; użyj „Przetwórz ponownie”. [Więcej →](szablony.md)

## Dlaczego dokument jest duplikatem?

W tym samym zakresie (ten sam klucz API albo panel) jest już ten sam plik albo faktura o tym samym dostawcy, rodzaju i numerze. Jeśli to inna faktura, wybierz „To nie duplikat — przetwórz”. [Więcej →](statusy-i-problemy.md)

## Jaki jest limit wielkości pliku i liczby pozycji?

Plik faktury: 10 MB. Pozycji: 5 000. Węzłów drzewa (elementy, atrybuty, komórki CSV): 200 000. Limity ustawia administrator w konfiguracji. [Więcej →](statusy-i-problemy.md)

## Jakie formaty są obsługiwane?

XML (dowolny, w tym KSeF i UBL), JSON i CSV, w kodowaniu UTF-8 (CSV także w Windows-1250). Format rozpoznawany jest po treści pliku, nie po rozszerzeniu. PDF i inne pliki binarne oraz UTF-16/UTF-32 są odrzucane. [Więcej →](jak-to-dziala.md)

## Czy wgranie XML jest bezpieczne?

Tak: pliki z deklaracją DOCTYPE/ENTITY są odrzucane, encje nie są rozwijane, parser nie sięga do sieci, a liczba węzłów i głębokość zagnieżdżenia są ograniczone. [Więcej →](jak-to-dziala.md)

## Dlaczego zostałem wylogowany?

Sesja wygasa po 8 h bez aktywności. „Wyloguj” unieważnia wszystkie sesje tego konta — także na innych urządzeniach. Sesja nie jest powiązana z adresem IP ani przeglądarką, więc sama zmiana sieci (np. przejście z Wi-Fi na LTE) nie wylogowuje; adres IP liczy się natomiast w limicie nieudanych prób logowania.

## Ile mam prób logowania?

Po 5 nieudanych próbach w ciągu 15 min dla pary (e-mail, adres IP) ta para jest blokowana na 15 min. Dodatkowo obowiązują limity 20 prób z jednego IP (na dowolne konta) w 15 min i 50 prób na jedno konto z dowolnych IP w 5 min.

## Czym różni się „tylko ta faktura” od „zapamiętaj w szablonie”?

„Tylko ta faktura” zapisuje decyzję w samym dokumencie. „Zapamiętaj” tworzy nową wersję szablonu albo wpis w słowniku dostawcy (alias jednostki, mapowanie towaru), więc kolejne faktury rozwiążą się same. [Więcej →](pierwsza-faktura.md)

## Jak przywrócić ręcznie odrzucony dokument?

Otwórz dokument i kliknij „Przywróć”. Ani „Przetwórz ponownie”, ani API (zwraca 409) nie cofają ręcznego odrzucenia. [Więcej →](statusy-i-problemy.md)

## Dlaczego liczba „1,234” blokuje fakturę?

Bo może oznaczać 1,234 albo 1234. Wskaż separator dziesiętny transformacją {"decimal": ","} lub {"decimal": "."} albo wybierz wariant podpowiedziany w panelu. [Więcej →](statusy-i-problemy.md)

## Jak podłączyć swoją aplikację?

Utwórz klucz w „Klucze API”, wysyłaj faktury przez POST /api/v1/documents z nagłówkiem X-API-Key i zapisuj zwrócone id. Status approved oznacza gotowy dokument kanoniczny w polu invoice; needs_review — wynik przyjdzie później. Zmiany statusów odbieraj synchronizacją GET /api/v1/documents?updated_since=… z kursorem next_cursor albo odpytując GET /api/v1/documents/{id} (webhooków nie ma). Przewodnik z gotowym kodem w Pythonie, PHP, JavaScripcie i powłoce. [Więcej →](integracja.md)

## Jak dowiedzieć się, że operator zatwierdził fakturę wysłaną przez API?

Synchronizuj listę: GET /api/v1/documents?updated_since=…&status=approved zwraca dokumenty zatwierdzone od podanej chwili — także przyjęte wcześniej, a zatwierdzone przez operatora w panelu dopiero teraz. Kolejne strony pobierasz z cursor=&lt;next_cursor>, aż next_cursor będzie null; każdy przebieg zaczynaj od ostatniego odebranego updated_at minus 5 minut, a powtórzenia odrzucaj po id i updated_at. Parametr since tu nie pomoże — filtruje po czasie przyjęcia faktury. [Więcej →](integracja.md)

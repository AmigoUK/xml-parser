<!-- Wygenerowano przez tools/export_help.py z sekcji Pomoc w panelu — nie edytuj ręcznie. -->

# Najczęstsze pytania

## Dlaczego faktura trafiła do kolejki „Do wyjaśnienia”?

Bo ma co najmniej jeden problem blokujący — najczęściej przy pierwszej fakturze nowego dostawcy (nieznany dostawca, jednostka, towar). Otwórz dokument i rozwiązuj problemy od góry; po każdej decyzji dokument jest przetwarzany ponownie. [Więcej →](statusy-i-problemy.md)

## Jak cofnąć złą wersję szablonu?

Szablony → wybierz szablon → w tabeli wersji kliknij „Przywróć” przy dobrej wersji. Powstaje nowa wersja będąca kopią wybranej — historia zostaje. Dokumenty przetworzone wcześniej nie zmieniają się same; użyj „Przetwórz ponownie”. [Więcej →](szablony.md)

## Dlaczego dokument jest duplikatem?

W tym samym zakresie (ten sam klucz API albo panel) jest już ten sam plik albo faktura o tym samym dostawcy, rodzaju i numerze. Jeśli to inna faktura, wybierz „To nie duplikat — przetwórz”. [Więcej →](statusy-i-problemy.md)

## Jaki jest limit wielkości pliku i liczby pozycji?

Plik faktury: 10 MiB. Pozycji: 5 000. Węzłów drzewa (elementy, atrybuty, komórki CSV): 200 000. Limity ustawia administrator w konfiguracji. [Więcej →](statusy-i-problemy.md)

## Jakie formaty są obsługiwane?

XML (dowolny, w tym KSeF i UBL), JSON i CSV, w kodowaniu UTF-8 (CSV także w Windows-1250). Format rozpoznawany jest po treści pliku, nie po rozszerzeniu. PDF i inne pliki binarne oraz UTF-16/UTF-32 są odrzucane. [Więcej →](jak-to-dziala.md)

## Czy wgranie XML jest bezpieczne?

Tak: pliki z deklaracją DOCTYPE/ENTITY są odrzucane, encje nie są rozwijane, parser nie sięga do sieci, a liczba węzłów i głębokość zagnieżdżenia są ograniczone. [Więcej →](jak-to-dziala.md)

## Dlaczego zostałem wylogowany?

Sesja wygasa po 8 h bez aktywności. „Wyloguj” unieważnia wszystkie sesje tego konta — także na innych urządzeniach. Sesja nie jest powiązana z adresem IP ani przeglądarką, więc sama zmiana sieci (np. przejście z Wi-Fi na LTE) nie wylogowuje; adres IP liczy się natomiast w limicie nieudanych prób logowania.

## Jak zmienić hasło?

Po zalogowaniu wybierz „Zmień hasło” obok adresu e-mail w górnym pasku: podaj obecne hasło i dwa razy nowe (co najmniej 10 znaków, nie przykładowe). Pozostałe sesje tego konta zostaną wylogowane. Administrator instancji może też ustawić hasło poleceniem flask set-admin-password (np. po wycieku).

## Ile mam prób logowania?

Po 5 nieudanych próbach w ciągu 15 min dla pary (e-mail, adres IP) ta para jest blokowana na 15 min. Dodatkowo obowiązują limity 20 prób z jednego IP (na dowolne konta) w 15 min i 50 prób na jedno konto z dowolnych IP w 5 min.

## Czym różni się „tylko ta faktura” od „zapamiętaj w szablonie”?

„Tylko ta faktura” zapisuje decyzję w samym dokumencie. „Zapamiętaj” tworzy nową wersję szablonu albo wpis w słowniku dostawcy (alias jednostki, mapowanie towaru), więc kolejne faktury rozwiążą się same. [Więcej →](pierwsza-faktura.md)

## Jak przywrócić ręcznie odrzucony dokument?

Otwórz dokument i kliknij „Przywróć”. Ani „Przetwórz ponownie”, ani API (zwraca 409) nie cofają ręcznego odrzucenia. [Więcej →](statusy-i-problemy.md)

<a id="czas-w-panelu"></a>

## Jaki czas pokazuje panel?

Czas lokalny. Panel pokazuje daty i godziny w strefie z ustawienia DISPLAY_TZ (domyślnie Europe/Warsaw), więc wpis z 10:00 UTC zobaczysz latem jako 12:00. Najedź na godzinę, a w podpowiedzi zobaczysz pełną strefę. Baza i REST API zawsze używają UTC z przyrostkiem „Z” (np. 2026-10-12T10:00:00Z) — integracje nie muszą nic przeliczać.

<a id="dluzsze-listy"></a>

## Lista się urywa — gdzie reszta wpisów?

Długie listy (dokumenty, historia, słowniki) pokazują jedną stronę naraz. Dokumenty, kolejka, Historia i Szablony mają na dole przyciski „Starsze →” i „Następne →”; słowniki (Dane) mają numerowane strony, w stałej kolejności danego słownika. Żeby nie przewijać, użyj wyszukiwania: pole nad listą Dokumentów oraz pole „Szukaj” w słownikach (adres z ?q=…), a w Historii filtruj po akcji i użytkowniku. Strona z filtrem ma własny adres, więc możesz ją dodać do zakładek.

<a id="zestaw-demo-api"></a>

## Jak wczytać zestaw demo przez API?

Użyj skryptu zestaw-demo.sh (curl i jq) z tematu „Zestaw demo”: ustaw klucz w zmiennej XP_API_KEY i uruchom go z fazą „pierwsze”, „pozostale” albo „wszystko”. Po fazie „pierwsze” rozwiąż problemy w panelu, dopiero potem wczytaj „pozostałe”. Uwaga: dokumenty wczytane kluczem API leżą w zakresie duplikatów tego klucza, więc ten sam plik wczytany przez panel albo innym kluczem nie będzie duplikatem. [Więcej →](zestaw-demo.md)

<a id="worek-na-kg"></a>

## Dostawca sprzedaje w workach, a my liczymy w kilogramach. Jak to ustawić?

Wystarczy raz powiedzieć systemowi, ile waży worek. W negocjacji wskaż, że zapis „worek” z faktury to nasza jednostka worek, a potem wpisz przelicznik „1 worek = 25 kg”. Od tej chwili każda pozycja w workach tego dostawcy jest przeliczana na kilogramy: 20 worków staje się 500 kg, a cena za worek — ceną za kilogram. Poniżej krok po kroku, zrzut z panelu i lista pułapek. [Więcej →](jednostki.md)

### Krok po kroku

1. **Jednostka.** Faktura trafia do kolejki z problemem „Nieznana jednostka „worek”” (albo „wor.”, „BAG” — jak pisze dostawca). Wybierz naszą jednostkę `worek` i zostaw włączone „zapamiętaj” — powstaje alias dostawcy.
2. **Przelicznik.** Pojawia się „Brak przelicznika dla jednostki „worek””. W formularzu wpisz `25`, wybierz `kg` i zakres „dla wszystkich towarów dostawcy”. Jeśli nazwa towaru zawiera „25 kg”, liczba jest już podpowiedziana.
3. **Zapisz.** Dokument jest przetwarzany od nowa; przelicznik zostaje w słowniku, więc następna faktura tego dostawcy przejdzie bez pytań.

![Widok dokumentu w panelu z kartą problemu brak przelicznika: pole 1 worek = 25, lista jednostek z wybranym kg, lista zakresu i przycisk Zapisz przelicznik](../../app/static/screenshots/13-faq-worek.png)

*Negocjacja faktury demo: 20 worków cukru po 25 kg — karta „Brak przelicznika” z formularzem 1 worek = 25 kg (liczba podpowiedziana z nazwy towaru) i wyborem zakresu „dla wszystkich towarów dostawcy”.*

### Co dzieje się z liczbami

| Pole | Na fakturze | Po przeliczeniu |
| --- | --- | --- |
| Ilość | 20 worek | 500 kg (× 25) |
| Cena netto | 75,00 za worek | 3,00 za kg (÷ 25) |
| Wartość pozycji | 1 500,00 | 1 500,00 — bez zmian |
| W dokumencie i API | `unit_source` = worek | `unit` = kg, `conversion_factor` = 25 |

### Na co uważać

- **Nie wskazuj „worek” wprost jako kg.** `kg` jest jednostką bazową, więc nic nie zostanie przeliczone — zostanie 20 kg zamiast 500 kg. Jeśli tak się stało, usuń alias w Dane → Aliasy jednostek i kliknij „Przetwórz ponownie” w dokumencie.
- **Kropka, nie przecinek.** Przelicznik 12,5 wpisz jako `12.5`; zapis „1,125” jest odrzucany jako niejednoznaczny (1,125 czy 1125?). Przelicznik musi być większy od zera i mieć najwyżej 12 cyfr całkowitych.
- **Przelicznik jest zawsze zapamiętywany** — tu nie ma wyboru „tylko ta faktura”. Pomyłkę poprawisz w Dane → Przeliczniki.
- **Działa od teraz.** Dokumenty przetworzone wcześniej (także zatwierdzone) nie zmieniają się same — użyj w nich „Przetwórz ponownie”.
- **Tylko na jednostkę bazową.** Lista „na jednostkę” pokazuje wyłącznie jednostki bazowe (kg, szt, l…); worek → karton nie jest możliwy.
- **„Tylko dla tego towaru” wymaga przypisanego towaru.** Jeśli pozycja ma jeszcze problem „nie przypisano towaru”, rozwiąż go najpierw.
- **Inne worki u tego dostawcy** (np. 50 kg) — zobacz pytanie [„Ten sam dostawca ma worki 25 kg i 50 kg”](faq.md#worki-rozne-wagi).
- **Faktura już w kilogramach?** Nic nie rób — kg to jednostka bazowa, pozycja przechodzi bez przelicznika.

<a id="worki-rozne-wagi"></a>

## Ten sam dostawca ma worki 25 kg i 50 kg. Co wtedy?

Daj przelicznik na towar, nie na dostawcę: przy pozycji z workiem 50 kg wybierz zakres „tylko dla tego towaru” i wpisz 50. Przelicznik dla towaru wygrywa z przelicznikiem „dla wszystkich towarów dostawcy”, więc mąka dalej liczy się po 25 kg, a cukier po 50 kg. Warunek: towar musi być już przypisany do pozycji (rozwiąż najpierw problem „nie przypisano towaru”). Kolejność wyboru przelicznika: ten dostawca i ten towar → ten dostawca, wszystkie towary → wszyscy dostawcy, ten towar → wszyscy. [Więcej →](jednostki.md)

<a id="zly-przelicznik"></a>

## Wpisałem zły przelicznik. Jak go poprawić i co z fakturami już przeliczonymi?

Dane → Przeliczniki → „Edytuj” przy wpisie. Wpisanie w negocjacji nowego przelicznika dla tej samej jednostki, dostawcy i towaru także nadpisuje stary — nigdy nie powstaje drugi. Poprawka działa od następnego przetworzenia: dokumenty już przeliczone (także zatwierdzone) nie zmieniają się same. Otwórz każdy z nich i kliknij „Przetwórz ponownie”; system zewnętrzny zobaczy nową wersję przy synchronizacji (updated_since), bo ponowne przetworzenie odświeża updated_at. [Więcej →](jednostki.md)

<a id="cena-po-przeliczeniu"></a>

## Dlaczego po przeliczeniu cena jednostkowa jest inna niż na fakturze?

Bo to cena za naszą jednostkę, nie za opakowanie dostawcy: 75,00 zł za worek 25 kg to 3,00 zł za kilogram. Ilość jest mnożona przez przelicznik, cena dzielona — wartość pozycji się nie zmienia. Oryginalną jednostkę widać w kolumnie „JM źródłowa”, użyty współczynnik w kolumnie „Przelicznik” (w API: unit_source i conversion_factor). Gdy dzielenie nie wychodzi równo (np. 40,00 zł za karton 12 szt), cena jest zaokrąglana do 4 miejsc — grosz różnicy w przeliczeniu to nie błąd. [Więcej →](jednostki.md)

<a id="tylko-jednostka-bazowa"></a>

## Czy mogę przeliczyć worek na karton albo paletę?

Nie — przelicznik zawsze prowadzi do jednostki bazowej (kg, szt, l…), żeby każda pozycja kończyła w tej jednostce, w której liczy nasz magazyn; lista „na jednostkę” pokazuje tylko jednostki bazowe. Jeśli naprawdę liczysz w kartonach, oznacz karton jako jednostkę bazową w Dane → Jednostki — wtedy pozycje w kartonach nie są przeliczane. Jednostka jest bazowa dla wszystkich albo dla nikogo: nie może być bazowa dla jednego towaru, a przeliczana dla innego. [Więcej →](jednostki.md)

<a id="rozne-zapisy-jednostki"></a>

## Dostawca raz pisze „worek”, raz „wor.”, raz „BAG”. Muszę to ustawiać trzy razy?

Alias — tak, każdy nowy zapis trzeba raz wskazać (pojawi się „Nieznana jednostka” z podpowiedzią). Przelicznik — nie: wszystkie trzy zapisy wskazują naszą jednostkę worek, a przelicznik „1 worek = 25 kg” jest jeden. Wielkość liter, polskie znaki i podwójne spacje nie mają znaczenia („WOREK” = „worek”), a zapis równy kodowi naszej jednostki (np. „KG”) jest rozpoznawany bez aliasu. [Więcej →](jednostki.md)

## Dlaczego liczba „1,234” blokuje fakturę?

Bo może oznaczać 1,234 albo 1234. Wskaż separator dziesiętny transformacją {"decimal": ","} lub {"decimal": "."} albo wybierz wariant podpowiedziany w panelu. [Więcej →](statusy-i-problemy.md)

## Jak podłączyć swoją aplikację?

Utwórz klucz w „Klucze API”, wysyłaj faktury przez POST /api/v1/documents z nagłówkiem X-API-Key i zapisuj zwrócone id. Status approved oznacza gotowy dokument kanoniczny w polu invoice; needs_review — wynik przyjdzie później. Zmiany statusów odbieraj synchronizacją GET /api/v1/documents?updated_since=… z kursorem next_cursor, odpytując GET /api/v1/documents/{id} albo ustaw przy kluczu webhook — parser sam wyśle powiadomienie o zmianie statusu (temat „Webhooki”). Przewodnik z gotowym kodem w Pythonie, PHP, JavaScripcie i powłoce. [Więcej →](integracja.md)

## Jak dowiedzieć się, że operator zatwierdził fakturę wysłaną przez API?

Synchronizuj listę: GET /api/v1/documents?updated_since=…&status=approved zwraca dokumenty zatwierdzone od podanej chwili — także przyjęte wcześniej, a zatwierdzone przez operatora w panelu dopiero teraz. Kolejne strony pobierasz z cursor=&lt;next_cursor>, aż next_cursor będzie null; każdy przebieg zaczynaj od ostatniego odebranego updated_at minus 5 minut, a powtórzenia odrzucaj po id i updated_at. Parametr since tu nie pomoże — filtruje po czasie przyjęcia faktury. Zamiast odpytywać możesz też ustawić webhook przy kluczu: parser wyśle powiadomienie document.status_changed, gdy status się zmieni. [Więcej →](integracja.md)

<a id="webhook-podpis"></a>

## Jak sprawdzić, że webhook naprawdę przyszedł z parsera?

Sprawdź podpis. Każde powiadomienie ma nagłówki X-XP-Timestamp (czas wysyłki w sekundach unixowych) i X-XP-Signature (sha256= i HMAC-SHA256 w zapisie szesnastkowym). Policz HMAC-SHA256 sekretem webhooka z tekstu „X-XP-Timestamp, kropka, surowe bajty ciała”, porównaj z podpisem w stałym czasie i odrzuć żądanie, którego czas różni się od Twojego zegara o więcej niż 300 s. Sekretu nie zna nikt poza Tobą i parserem — panel pokazuje go tylko raz. [Więcej →](webhooki.md)

### Krok po kroku

1. **Czytaj surowe bajty ciała**, zanim cokolwiek z nimi zrobisz. Podpis obejmuje dokładnie te bajty — JSON sparsowany i zapisany od nowa (inna kolejność kluczy, spacje) da inny wynik.
2. **Sprawdź czas**: `X-XP-Timestamp` to liczba sekund; odrzuć żądanie, gdy różni się od Twojego zegara o więcej niż 300 s (w obie strony).
3. **Policz podpis**: HMAC-SHA256 sekretem webhooka z tekstu `<X-XP-Timestamp>.<ciało>`, zapis szesnastkowy małymi literami, z przedrostkiem `sha256=`. Porównaj z `X-XP-Signature` funkcją o stałym czasie (`hmac.compare_digest`, `hash_equals`, `timingSafeEqual`). Niezgodność → odpowiedz `401` i nic nie przetwarzaj.
4. **Dopiero po poprawnym podpisie** deduplikuj po `X-XP-Delivery` — ten sam identyfikator oznacza ponowienie tej samej dostawy; odpowiedz wtedy `200` bez ponownego przetwarzania.

Każdy z gotowych odbiorców w temacie [Webhooki](webhooki.md#podpis) ma tryb `--check <ts> <podpis>`: sprawdza podpis ciała podanego na wejściu, bez serwera i bez sieci (sekret ze zmiennej `XP_WEBHOOK_SECRET`), i wypisuje `OK` albo powód odrzucenia. Jeśli podpis się nie zgadza, a sekret jest na pewno aktualny, sprawdź, czy po „Rotuj sekret” odbiorca dostał nowy sekret — stary przestaje działać od razu.

<a id="webhook-brak-dostawy"></a>

## Ustawiłem webhook, ale nic nie przychodzi — dlaczego?

Najczęściej dokument nie przyszedł przez ten klucz albo powiadomienia czekają w kolejce, bo nie działa worker. Sprawdź po kolei punkty poniżej; każdą próbę dostawy (z kodem odpowiedzi i błędem) widzisz na liście dostaw klucza w panelu i w API. [Więcej →](webhooki.md)

### Sprawdź po kolei

1. **Dokument nie przyszedł przez ten klucz.** Powiadomienia dotyczą wyłącznie dokumentów wysłanych przez REST API kluczem, przy którym ustawiono webhook. Faktura wgrana w panelu albo przykład z trybu demo nie wysyła zdarzeń. Do próby użyj „Wyślij testowe zdarzenie” przy kluczu albo wyślij plik tym kluczem.
2. **Klucz jest nieaktywny albo nie ma adresu webhooka.** Wyłączony klucz nie wysyła zdarzeń, a dostawy czekające w kolejce kończą się stanem `failed`. Sprawdź w „Klucze API”, czy klucz jest aktywny, a adres zapisany.
3. **Nie działa worker.** Powiadomienia wysyła osobna usługa `worker`; bez niej dostawy zostają w stanie `pending`. Sprawdź `docker compose ps` — usługa `worker` powinna być uruchomiona i zdrowa (`healthy`); awaryjnie wyślij kolejkę poleceniem `flask webhooks-worker --once`.
4. **Adres jest zablokowany.** Parser nie wysyła na adresy prywatne, lokalne ani z sieci CGNAT (np. Tailscale) i wymaga `https`. Adres w sieci firmowej albo w tailnecie administrator instancji dopuszcza zmienną `WEBHOOK_ALLOWED_HOSTS` (nazwy hostów i podsieci CIDR).
5. **Odbiorca odpowiada błędem.** Za dostarczone uznawana jest tylko odpowiedź 2xx w ciągu 5 s; przekierowanie, inny kod albo przekroczenie czasu to porażka i ponowienie. Po 6 nieudanych próbach dostawa ma stan `failed` — popraw odbiorcę i kliknij „Ponów” przy dostawie.

Ostatni kod odpowiedzi i treść błędu każdej dostawy zobaczysz na liście dostaw przy kluczu w panelu albo w API: `GET /api/v1/webhook-deliveries?status=failed` (opis w temacie [Webhooki](webhooki.md#lista-dostaw)).

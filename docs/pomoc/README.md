<!-- Wygenerowano przez tools/export_help.py z sekcji Pomoc w panelu — nie edytuj ręcznie. -->

# Pomoc

Jak korzystać z parsera faktur: od pierwszej faktury nowego dostawcy po integrację przez REST API. Tematy są zilustrowane zrzutami ekranu panelu z fikcyjnymi danymi demo — kliknij zrzut, aby zobaczyć go w pełnym rozmiarze.

## Szybki start w 5 krokach

1. **Zaloguj się** — Panel wymaga konta; tryb demo pokazuje e-mail konta na stronie „O demo”.
2. **Wgraj fakturę** — „Wgraj fakturę” w menu (XML, JSON lub CSV) albo wyślij ją przez REST API.
3. **Rozwiąż problemy od góry** — Faktura nowego dostawcy trafia do „Kolejki” — wybieraj podpowiedzi, zaczynając od rozpoznania dostawcy.
4. **Zdecyduj, co zapamiętać** — „Zapamiętaj w szablonie” uczy system; „tylko ta faktura” dotyczy jednego dokumentu.
5. **Kolejne faktury przejdą same** — Następna faktura tego dostawcy zostanie zatwierdzona automatycznie, jeśli nie pojawi się nic nowego.

## Tematy

### [Jak to działa](jak-to-dziala.md)

Droga faktury od pliku do zatwierdzonego dokumentu i na czym polega „uczenie”.

### [Pierwsza faktura dostawcy](pierwsza-faktura.md)

Negocjacja w widoku dokumentu: „tylko ta faktura” albo „zapamiętaj w szablonie”.

### [Zestaw demo „Miesiąc faktur”](zestaw-demo.md)

24 fikcyjne faktury sześciu dostawców: przejdź krok po kroku całe uczenie, z tabelą oczekiwanych wyników i skryptem do wczytania przez API.

### [Edytor mapowań](edytor-mapowan.md)

Pełnoekranowy edytor reguł szablonu i wszystkie transformacje z białej listy.

### [Szablony i wersje](szablony.md)

Wersje szablonu, porównywanie, przywracanie i usuwanie.

### [Jednostki, aliasy i przeliczniki](jednostki.md)

Jak jednostka z faktury staje się naszą jednostką i jak działa przelicznik.

### [Kartoteka i mapowania towarów](towary.md)

Kartoteka towarów, import CSV i przypisywanie pozycji po kodzie, GTIN lub nazwie.

### [Statusy i problemy](statusy-i-problemy.md)

Wszystkie statusy dokumentu i kody problemów — co znaczą i jak je rozwiązać.

### [REST API](api.md)

Klucze API, przykłady curl dla każdego endpointu, kody odpowiedzi i limity.

### [Integracja z własną aplikacją](integracja.md)

Przewodnik krok po kroku: wysyłka, odbiór wyniku, synchronizacja zmian statusów albo webhook, ponowienia i gotowy kod w Pythonie, PHP, JavaScripcie i powłoce.

### [Webhooki](webhooki.md)

Parser sam powiadamia Twój system o zmianie statusu dokumentu: włączenie przy kluczu API, podpis HMAC, ponowienia i gotowy odbiorca w Pythonie, PHP, Node.js i powłoce.

### [Najczęstsze pytania](faq.md)

Krótkie odpowiedzi na pytania, które pojawiają się najczęściej.

**Najważniejsze limity tej instancji**

- Plik faktury: maks. 10 MiB.
- Pozycji na fakturze: maks. 5 000.
- Węzłów drzewa (elementy, atrybuty, komórki CSV): maks. 200 000.

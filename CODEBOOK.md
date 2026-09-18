# CODEBOOK

Instrukcja kodowania obserwacji. Wersja 1.0, zamrożona razem z [PROTOCOL.md](PROTOCOL.md).

Kodujemy **trajektorię** reklamy, a nie jej stan w jednym momencie. Klasyfikacja końcowa zapada dopiero po zamknięciu okna 30 dni.

---

## 1. Jednostka kodowania

Jedna **obserwacja** = jedna reklama zarejestrowana w nagraniu sesji, dla której odczytano identyfikator Biblioteki Reklam. Identyfikator `AD-XXXX` nadawany rosnąco i nigdy nie reużywany.

Obserwacja bez odczytanego identyfikatora **nie jest kodowana**. Trafia do rejestru nieudanych odczytów i jest raportowana osobno. Nigdy nie liczy się jako M4.

## 2. Wejście do kodowania

Dla każdej obserwacji koder ma:

- nagranie lub kadr z sesji, pokazujący reklamę tak, jak widział ją użytkownik,
- `observed_creative_hash`: SHA-256 kadru kreacji,
- serię snapshotów Biblioteki z zaplanowanych momentów t+1h, t+6h, t+24h, t+72h, t+7d, t+30d,
- dla każdego snapshotu: czy rekord istnieje, jakie kreacje udostępnia, ich hashe, flagę wielu wersji.

## 3. Kategorie

Kategorie są **rozłączne**. Jeżeli trajektoria spełnia kryteria kilku, obowiązuje kolejność pierwszeństwa z sekcji 4.

### M0. Zgodność

Rekord obecny, a obserwowana kreacja występuje wśród kreacji udostępnionych przez Bibliotekę, już w pierwszym pomiarze.

> Biblioteka zadziałała tak, jak wymaga tego art. 39 DSA. To jest kategoria odniesienia.

### M1. Opóźnienie

Rekord **nieobecny** w pierwszym pomiarze, ale obecny w którymś z późniejszych, z obserwowaną kreacją wśród udostępnionych.

> Problem po stronie Mety, ale jakościowo inny niż brak rekordu. To niezawodność i terminowość, nie ukrywanie. Zapisujemy czas pierwszego pojawienia się rekordu.

### M2. Maskowanie wariantem

Rekord obecny przez cały czas obserwacji, ale obserwowana kreacja **nigdy** nie występuje wśród kreacji udostępnionych, w żadnym pomiarze.

> To sytuacja, w której Biblioteka pokazuje inną reklamę niż ta, którą zobaczył użytkownik. Typowo reklama ma wiele wersji, a API udostępnia nie tę. Kodujemy tu również przypadek „w Bibliotece dżinsy, na ekranie oszustwo".

### M3. Podmiana po publikacji

Zbiór hashy kreacji w rekordzie **zmienia się** między dwoma kolejnymi pomiarami.

> Najmocniejszy możliwy dowód celowej ewazji, bo pokazuje ruch w czasie, a nie stan. Zapisujemy, między którymi pomiarami nastąpiła zmiana oraz czy kreacje zostały dodane, usunięte, czy podmienione.

### M4. Brak trwały

Rekord **nieobecny we wszystkich** pomiarach, łącznie z t+30d.

> Wprost naruszenie art. 39 DSA. Warunek konieczny: pomiar t+30d musi być wykonany skutecznie. Jeżeli go brakuje, kategoria nie może zostać przypisana.

### UNRESOLVED

Trajektoria niekompletna: brakuje więcej niż dwóch zaplanowanych pomiarów albo brakuje pomiaru t+30d przy nieobecnym rekordzie.

> Nie jest wynikiem, jest brakiem danych. Raportowana osobno i wykluczana z analizy głównej.

## 4. Kolejność pierwszeństwa

Sprawdzamy w tej kolejności i przypisujemy **pierwszą** pasującą kategorię:

```
1. UNRESOLVED   niekompletna trajektoria
2. M4           rekord nieobecny we wszystkich pomiarach
3. M3           zbiór hashy kreacji zmienił się w czasie
4. M2           obserwowana kreacja nigdy nieudostępniona
5. M1           rekord pojawił się z opóźnieniem, kreacja zgodna
6. M0           zgodność od pierwszego pomiaru
```

Uzasadnienie kolejności: M4 wyklucza wszystko inne, bo bez rekordu nie ma czego porównywać. M3 stoi przed M2, bo zaobserwowana zmiana w czasie jest mocniejszym dowodem niż statyczna rozbieżność i nie chcemy jej zgubić w kategorii zbiorczej. M1 stoi przed M0, bo opóźnienie jest odstępstwem od wymogu, nawet jeśli skończyło się zgodnością.

## 5. Zgodność kreacji

Kreację uznajemy za **udostępnioną**, jeżeli jej hash perceptualny mieści się w progu podobieństwa wobec `observed_creative_hash`. Porównanie bitowe nie wystarcza, bo Biblioteka przekodowuje materiały.

Próg zostanie ustalony empirycznie na zbiorze kalibracyjnym przed rozpoczęciem kodowania i zapisany jako dopisek do [PROTOCOL.md](PROTOCOL.md) sekcja 12. Do czasu ustalenia progu klasyfikacja automatyczna oznacza takie przypadki jako wymagające decyzji kodera.

Przypadki graniczne rozstrzyga koder, a decyzja jest zapisywana razem z uzasadnieniem w polu `coder_note`.

## 6. Czego koder nie robi

- **Nie ocenia, czy reklama jest oszustwem.** Ten codebook mierzy wyłącznie rozbieżność między tym, co widział użytkownik, a tym, co pokazuje Biblioteka. Ocena charakteru reklamy to osobna zmienna i osobna decyzja.
- **Nie domyśla się przyczyny.** „Reklamodawca podmienił" i „Meta nie zaktualizowała" wyglądają w danych tak samo. Kodujemy obserwowalne, nie intencję.
- **Nie zagląda do wcześniejszej klasyfikacji** przy kodowaniu kontrolnym 20% (rzetelność wewnątrzkoderska, PROTOCOL sekcja 8).

## 7. Rzetelność

Po co najmniej 14 dniach losowe 20% obserwacji jest kodowane ponownie, na ślepo. Raportujemy κ z porównania obu przejść. Przy κ < 0,7 codebook zostaje doprecyzowany, a cały korpus przekodowany, i fakt ten jest raportowany.

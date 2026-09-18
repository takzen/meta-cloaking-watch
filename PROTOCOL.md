# PROTOCOL.md

Protokół badawczy zarejestrowany **przed rozpoczęciem zbierania danych**.

| | |
|---|---|
| Wersja | 1.0 |
| Data zamrożenia | 2026-09-18 |
| Tag | `protocol-v1` |
| Zebranych danych w momencie zamrożenia | **zero** |

Po zamrożeniu ten plik jest edytowany wyłącznie przez **dopiski** w sekcji [Odchylenia i poprawki](#12-odchylenia-i-poprawki). Treść sekcji 1-11 nie jest zmieniana. Historia zmian jest w gicie i jest częścią dowodu.

---

## 1. Pytanie główne

> Jaki odsetek reklam zaobserwowanych realnie na platformach Mety nie posiada odwzorowania w Bibliotece Reklam po upływie 30 dni od obserwacji?

## 2. Pytania poboczne

1. Jak rozkłada się rozbieżność na pięć mechanizmów M1-M5 (sekcja 4)?
2. Jaki jest czas od obserwacji do pojawienia się rekordu w Bibliotece, dla tych reklam, które się pojawiają?
3. Jaki jest czas od obserwacji do usunięcia reklamy przez Metę (time to takedown)?
4. Jak często treść kreacji w Bibliotece zmienia się po publikacji (mechanizm M3)?
5. Jaki odsetek rekordów ma wypełnione pole `beneficiary_payers`, wymagane przez art. 39 ust. 2 lit. b DSA?

## 3. Hipotezy

- **H-A.** Odsetek reklam bez rekordu w Bibliotece po 30 dniach (M4) jest istotnie większy od zera.
- **H-B.** Odsetek reklam, dla których Biblioteka pokazuje kreację różną od zaobserwowanej, maleje wraz z upływem czasu od obserwacji. Innymi słowy: część rozbieżności raportowanych w dotychczasowych badaniach to opóźnienie (M1), a nie trwała rozbieżność.
- **H-C.** Wystąpią przypadki zmiany treści kreacji w Bibliotece między kolejnymi snapshotami tego samego `ad_id` (M3).

H-B jest hipotezą, która może **osłabić** dotychczasowe ustalenia w tej sprawie, w tym nasze własne oczekiwania. Rejestrujemy ją świadomie i zaraportujemy wynik niezależnie od kierunku.

## 4. Definicje

**Obserwacja.** Pojedyncza reklama zarejestrowana w nagraniu sesji na urządzeniu badawczym, dla której udało się odczytać identyfikator Biblioteki Reklam.

**Identyfikator Biblioteki.** Wartość odczytana w aplikacji ze ścieżki „Dlaczego widzę tę reklamę" / „Link do reklamy". Pochodzi od Mety. Nie rekonstruujemy go ani nie zgadujemy.

**Dopasowanie.** Odpytanie Biblioteki tym identyfikatorem. Wynik: rekord albo jego brak. Przypadki, w których identyfikatora nie dało się odczytać z aplikacji, są rejestrowane jako **nieudany odczyt** i wykluczane z analizy głównej (sekcja 10). Nigdy nie są liczone jako M4.

**Mechanizmy rozbieżności:**

| | Mechanizm | Kryterium operacyjne |
|---|---|---|
| **M0** | Zgodność | rekord obecny, kreacja zgodna z obserwowaną |
| **M1** | Opóźnienie | rekord nieobecny w chwili obserwacji, obecny i zgodny w którymś z późniejszych odpytań |
| **M2** | Maskowanie wariantem | rekord obecny, Biblioteka raportuje wiele wersji, obserwowana kreacja nie występuje wśród udostępnionych |
| **M3** | Podmiana po publikacji | hash kreacji w rekordzie zmienia się między dwoma snapshotami tego samego `ad_id` |
| **M4** | Brak trwały | rekord nieobecny we **wszystkich** odpytaniach, łącznie z t+30d |
| **M5** | Cloaking serwerowy | strona docelowa zwraca istotnie różną treść w zależności od User-Agent, adresu IP lub geolokalizacji |

M5 jest poza zakresem wersji 1.0 (sekcja 11).

Kategorie są rozłączne w momencie **końcowej** klasyfikacji, po zamknięciu okna 30 dni. Reklama może w trakcie obserwacji przechodzić między stanami; zapisujemy pełną trajektorię, a nie tylko stan końcowy.

## 5. Plan próby

- **Persony:** 1-2 konta obserwacyjne. Liczba zostanie ustalona po rekonesansie (sekcja 9) i odnotowana jako dopisek.
- **Konto obserwacyjne nigdy nie wchodzi w interakcję z reklamą.** Żadnych kliknięć, reakcji ani odwiedzin strony docelowej z tego konta. Sonda strony docelowej, jeśli powstanie, działa z osobnego środowiska.
- **Sesja:** ustalona liczba pozycji feedu (domyślnie 100), a nie ustalony czas. Czas trwania sesji jest zapisywany, ale nie definiuje sesji.
- **Harmonogram:** sesje rozłożone losowo w ciągu doby i w tygodniu, aby kontrolować porę dnia i dzień tygodnia.
- **Cel:** **N = 100-150 obserwacji** z odczytanym identyfikatorem, w oknie około 4 tygodni.
- **Uzasadnienie N:** przy oczekiwanym odsetku rzędu 0,4 przedział Wilsona dla N = 120 ma szerokość około ±9 punktów procentowych. To wystarcza, by odróżnić „zjawisko marginalne" od „zjawisko powszechne", i nie wystarcza do precyzyjnych porównań między podgrupami. Porównania między personami będą raportowane wyłącznie opisowo.

## 6. Procedura zbierania

1. Nagranie całej sesji. Rejestrujemy każdą reklamę, która pojawi się w feedzie, a nie te, które badacz uzna za interesujące. To eliminuje selekcję obserwatora.
2. Dla każdej reklamy: odczyt identyfikatora Biblioteki ze ścieżki w aplikacji.
3. Zapis artefaktów do `data/evidence/AD-XXXX/`.
4. Każdy artefakt otrzymuje SHA-256 i znacznik czasu UTC **w momencie zapisu**, dopisywane do `data/manifest.jsonl`. Katalog dowodów jest append-only.

## 7. Harmonogram odpytań Biblioteki

Dla każdego identyfikatora, automatycznie: **t+1h, t+6h, t+24h, t+72h, t+7d, t+30d**, licząc od momentu obserwacji.

Przy każdym odpytaniu zapisujemy: obecność rekordu, status aktywności, wszystkie udostępnione warianty kreacji, hash każdej kreacji, flagę wielu wersji, kompletność `beneficiary_payers` oraz surową odpowiedź API.

Nieudane odpytanie (błąd sieci, błąd API, limit) jest zapisywane jako **brak pomiaru**, nie jako brak rekordu, i ponawiane. Rozróżnienie tych dwóch przypadków jest krytyczne i podlega kontroli przy analizie.

## 8. Kodowanie i rzetelność

Klasyfikacja M0-M4 wg codebooka, opublikowanego razem z danymi.

Przy jednym badaczu stosujemy rzetelność **wewnątrzkoderską**: po upływie co najmniej 14 dni od pierwszego kodowania losowe 20% rekordów jest kodowane ponownie, na ślepo, bez wglądu w pierwszą klasyfikację. Raportujemy κ z porównania obu przejść, z jawnym zaznaczeniem, że jest to wariant słabszy niż dwóch niezależnych koderów.

Jeżeli κ < 0,7, codebook zostaje doprecyzowany, a **cały** korpus przekodowany. Fakt ten jest raportowany.

## 9. Warunek wstępny: rekonesans API

Przed zbieraniem uruchamiamy sondy `src/recon/probe.py` (H1-H5), które rozstrzygają faktyczne możliwości Ad Library API: zasięg per kraj, działanie `unmask_removed_content`, realne limity zapytań, ekspozycję wariantów kreacji, kompletność `beneficiary_payers`.

Wyniki rekonesansu mogą **zawęzić** zakres badania. Zostaną opublikowane w całości, razem z surowymi odpowiedziami API, niezależnie od tego, czy są dla projektu korzystne.

## 10. Kryteria wykluczenia

Z analizy głównej wykluczamy obserwacje, dla których:

1. nie udało się odczytać identyfikatora Biblioteki,
2. nagranie sesji jest niekompletne lub nieczytelne,
3. brakuje pomiaru w więcej niż dwóch punktach harmonogramu z sekcji 7,
4. reklama pochodzi z sesji, w której naruszono protokół (odnotowane w dzienniku odchyleń).

Liczba i przyczyny wykluczeń są raportowane. Odsetek wykluczeń powyżej 25% traktujemy jako sygnał, że protokół nie działa, i raportujemy to jako wynik negatywny.

## 11. Czego ten protokół nie obejmuje

- **Nie szacujemy przychodów Mety z reklam oszukańczych.** Świadoma decyzja. Przy publicznym API taki szacunek opiera się na łańcuchu mnożników liniowych i daje szeroki przedział, który w odbiorze medialnym przykrywa dowody.
- **Nie klasyfikujemy reklam jako oszukańczych na podstawie faktu ich usunięcia przez Metę.** Ten klasyfikator ma nieznaną precyzję i nieznaną czułość. Bez walidacji nie jest używany.
- **Nie badamy w wersji 1.0 cloakingu serwerowego stron docelowych (M5).** Wymaga osobnego środowiska i osobnej analizy ryzyka.
- **Nie ekstrapolujemy wyników na populację reklam w Polsce.** Próba jest celowa, nie losowa. Wyniki opisują to, co zaobserwowano, i nic ponadto.

## 12. Odchylenia i poprawki

Każde odstępstwo od sekcji 1-11 jest dopisywane tutaj, z datą, opisem i uzasadnieniem, **przed** albo niezwłocznie po jego zaistnieniu. Pusta sekcja oznacza brak odstępstw.

### P-01. Okna tolerancji dla punktów pomiaru

**Data:** 2026-09-18
**Charakter:** doprecyzowanie sekcji 7, przed rozpoczęciem zbierania danych
**Zebranych obserwacji w momencie wprowadzenia:** zero

Sekcja 7 wymienia momenty pomiaru, ale nie określa, jak duże spóźnienie jeszcze
oznacza pomiar w danym punkcie. Bez tego odpytanie wykonane dziesięć godzin po
obserwacji dałoby się zapisać jako pomiar t+1h, co jest niedopuszczalne.

Ustalamy okna ważności. Pomiar punktu jest ważny w przedziale od `obserwacja + odstęp`
do `obserwacja + odstęp + tolerancja`:

| Punkt | Odstęp | Tolerancja |
|---|---|---|
| t+1h | 1 h | 30 min |
| t+6h | 6 h | 1 h |
| t+24h | 24 h | 2 h |
| t+72h | 72 h | 6 h |
| t+7d | 7 dni | 12 h |
| t+30d | 30 dni | 24 h |

Tolerancja rośnie wraz z odstępem, ponieważ przy t+30d godzina nie zmienia
interpretacji wyniku, a przy t+1h zmienia ją zasadniczo.

Punkt, którego okno zamknęło się bez udanego odpytania, jest **trwale nieudany**.
Wchodzi do trajektorii jako brak pomiaru, nigdy jako brak rekordu, i może
doprowadzić obserwację do kategorii UNRESOLVED. Jest to skutek zamierzony:
utrata obserwacji jest mniejszym kosztem niż dopisanie pomiaru, którego nie było.

Nieudane odpytanie jest ponawiane najwyżej pięciokrotnie, z odstępem 10 minut,
wyłącznie w granicach otwartego okna. Każda próba, także nieudana, jest zapisywana
wraz z treścią błędu, ponieważ liczba prób i rodzaje błędów są danymi o
niezawodności interfejsu, wymaganej przez art. 39 DSA.

Implementacja: `src/schedule.py`. Reguły utrwalone testami w `tests/test_schedule.py`.

## 13. Etyka

Zasady w [README](README.md#etyka-i-granice). W skrócie: zero interakcji transakcyjnej z infrastrukturą oszustów, redakcja danych osób prywatnych przed publikacją, defangowanie adresów, jawny opis napięcia między badaniem a regulaminem platformy, responsible disclosure do Mety przed publikacją, równoległy wniosek o dostęp badawczy z art. 40 DSA.

## 14. Publikacja

Publikujemy niezależnie od wyniku, w tym wynik negatywny lub nieciekawy. Razem z raportem udostępniamy: zbiór danych, kod, codebook, ten protokół wraz z historią zmian oraz instrukcję replikacji.

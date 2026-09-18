# meta-cloaking-watch

**Otwarte, odtwarzalne badanie rozbieżności między reklamą, którą użytkownik widzi na Instagramie i Facebooku, a jej odwzorowaniem w oficjalnej Bibliotece Reklam Mety.**

Status: **pre-rejestracja, protokół przed zbieraniem danych. Wyników jeszcze nie ma.**
Data startu: 2026-09-18 · Pierwsze wyniki: ~połowa października 2026

---

## Jedno pytanie

> **Ile reklam zaobserwowanych realnie na platformie nie pojawia się w Bibliotece Reklam nigdy: nie po 24 godzinach, nie po 7 dniach, nie po 30?**

Nikt tego dotąd nie zmierzył. Dotychczasowe badania sprawdzały Bibliotekę minuty po zaobserwowaniu reklamy, więc nie potrafiły odróżnić **opóźnienia** publikacji od **trwałego braku** rekordu. To rozróżnienie jest całą różnicą między „Biblioteka działa wolno" a „Biblioteka nie zawiera tych reklam", a Meta ma wobec niej obowiązki z art. 39 DSA.

Rozstrzyga je jedna zmiana metodologiczna: **powtarzane odpytywanie tego samego `ad_id` w czasie.**

## Kontekst

Punktem wyjścia jest raport Fundacji Instrat *Skala problemu. Oszukańcze reklamy na platformach Mety* (Policy Paper 02/2026), który jako pierwszy udokumentował to zjawisko w Polsce na próbie 108 reklam. Jego część dowodowa jest mocna i to od niej zaczynamy.

Nie powtarzamy natomiast jego części szacunkowej, patrz [Czego NIE robimy](#czego-nie-robimy).

## Taksonomia: pięć różnych zjawisk, nie jedno

Publicystyka wrzuca to wszystko do worka „cloaking". To pięć osobnych mechanizmów, każdy z innym adresatem i innym środkiem zaradczym. Mierzymy je rozdzielnie:

| | Mechanizm | Co się dzieje | Po czyjej stronie |
|---|---|---|---|
| **M1** | Opóźnienie Biblioteki | ta sama kreacja pojawia się później | Meta, niezawodność (art. 39) |
| **M2** | Maskowanie wariantem | reklama ma N wersji, API pokazuje jedną | Meta, kompletność (art. 39 ust. 2) |
| **M3** | Podmiana po akceptacji | scam zamieniony na treść neutralną po kilku godzinach | reklamodawca + brak kontroli Mety |
| **M4** | Brak rekordu na zawsze | `ad_id` nie trafia do Biblioteki nigdy | Meta, wprost naruszenie art. 39 |
| **M5** | Cloaking serwerowy | strona docelowa serwuje inną treść wg User-Agent / IP / geo | reklamodawca |

Osobno raportujemy przypadki, w których **nie udało się dopasować** obserwacji do rekordu. Nigdy nie doklejamy ich do M4.

## Co robimy inaczej

1. **Pomiar longitudinalny.** Każdy `ad_id` odpytywany po 1 h, 6 h, 24 h, 72 h, 7 dniach i 30 dniach. To rozdziela M1 od M4 i wykrywa M3 przez porównanie hashy kreacji między snapshotami.
2. **Protokół zamrożony przed zbieraniem**, otagowany w gicie. Żadnego doboru danych po fakcie.
3. **Każda liczba z przedziałem ufności.** Odsetki: przedział Wilsona. Błędy odporne na klastrowanie, bo reklamy z jednego konta nie są niezależne.
4. **Pomiar rzetelności kodowania.** Przy jednym badaczu: ponowne zakodowanie losowych 20% na ślepo po dwóch tygodniach i raportowanie κ, z jawnym zaznaczeniem, że to słabszy wariant niż dwóch niezależnych koderów.
5. **Wszystko jawne.** Dane, kod, codebook, protokół. Badanie, którego tezą jest brak audytowalności platformy, samo musi być audytowalne.

Mierzymy też rzeczy, które nie wymagają żadnej ekstrapolacji i których nikt nie zbiera: **czas do usunięcia reklamy**, rotację kont nadawców, kompletność pola `beneficiary_payers` wymaganego przez DSA.

## Czego NIE robimy

**Nie szacujemy, ile Meta zarabia na oszukańczych reklamach.** Świadoma decyzja, nie przeoczenie.

Przy publicznym API Mety taki szacunek opiera się na łańcuchu założeń (częstotliwość wyświetleń, CPM, klasyfikacja reklam, przejście z zasięgu unijnego na krajowy), z których każde jest mnożnikiem liniowym. Wynik jest wtedy szerokim przedziałem, a nie liczbą, i w odbiorze medialnym natychmiast przykrywa dowody. Nie wchodzimy w to.

Jeżeli mimo wszystko powstanie oszacowanie, trafi wyłącznie do aneksu, jako mediana z 90% przedziałem i wykresem wrażliwości pokazującym, które założenie dominuje.

## Metoda w skrócie

Obserwacja w aplikacji na urządzeniu → odczyt identyfikatora Biblioteki ze ścieżki „Dlaczego widzę tę reklamę" → automatyczne odpytania Biblioteki w zaplanowanych odstępach → klasyfikacja M1-M5 wg codebooka → statystyka z przedziałami.

Nagrywamy całą sesję zamiast robić wybiórcze zrzuty, bo inaczej o składzie próby decyduje refleks badacza. Konto obserwacyjne nigdy nie klika w reklamy; do tego służy osobne konto, żeby nie zanieczyszczać pomiaru.

Każdy artefakt dowodowy dostaje SHA-256 i znacznik czasu UTC w momencie zapisu, dopisywane do `data/manifest.jsonl`. Dowody są append-only.

## Etyka i granice

- Zero interakcji transakcyjnej z infrastrukturą oszustów: żadnych formularzy, rejestracji, płatności ani pobierania plików. Strony docelowe wyłącznie GET, w izolowanym środowisku.
- Adresy scamowe publikujemy w formie defanged (`hxxps://przyklad[.]site`).
- Redakcja przed publikacją: twarze i nicki osób prywatnych rozmyte. Wizerunki osób publicznych użyte **w samej reklamie** zostają, bo one są dowodem.
- Napięcie między badaniem a regulaminem Mety jest realne i zostanie jawnie opisane w metodologii, a nie przemilczane. Równolegle składamy wniosek o dostęp badawczy z art. 40 DSA.
- Responsible disclosure do Mety przed publikacją, z udokumentowaną datą. Brak odpowiedzi też jest wynikiem i zostanie opublikowany.

## Struktura

```
PROTOCOL.md   pre-rejestrowany protokół (po zamrożeniu: tylko dopiski)
src/recon/    sondy rozstrzygające faktyczne możliwości Ad Library API
data/         dowody i snapshoty (poza gitem) + manifest z hashami
analysis/     skrypty produkujące liczby do publikacji
```

## Status

- [x] Analiza metodologiczna stanu wiedzy
- [x] Zasady projektu i plan prac
- [x] Sondy rekonesansowe Ad Library API: napisane
- [ ] Rekonesans uruchomiony (**bramka go/no-go**)
- [ ] `PROTOCOL.md` zamrożony i otagowany
- [ ] Zbieranie danych
- [ ] Wyniki

Ta lista jest aktualizowana na bieżąco i jest jedynym miejscem, w którym ogłaszamy postęp.

## Niezależność

Projekt prowadzony niezależnie, bez finansowania zewnętrznego i bez zleceniodawcy. Jeżeli to się zmieni, informacja pojawi się w tym miejscu przed publikacją jakichkolwiek wyników.

---

## English

**Open, reproducible measurement of the gap between ads actually served on Instagram and Facebook and their representation in Meta's official Ad Library.**

Status: **pre-registration. Protocol published before data collection. No results yet.** First results expected mid-October 2026.

The single question: **how many ads observed on-platform never appear in the Ad Library at all: not after 24 hours, not after 7 days, not after 30?** Prior work checked the Library minutes after observation and therefore could not separate *publication delay* from *permanent absence*, the difference between "the Library is slow" and "the Library does not contain these ads", which is what Article 39 DSA is about. One methodological change resolves it: repeated, scheduled re-querying of the same `ad_id` over time.

We measure five distinct mechanisms separately (M1 delay · M2 variant masking · M3 post-approval creative swap · M4 never recorded · M5 server-side landing-page cloaking), report every proportion with a Wilson interval and cluster-robust errors, freeze the protocol before collection, and publish data, code and codebook.

**We deliberately do not estimate Meta's revenue from scam advertising.** With the public API such an estimate rests on a chain of linear multipliers and collapses into a wide interval that, in media reception, immediately buries the evidence. If one is produced at all, it goes in an appendix as a median with a 90% interval and a sensitivity analysis.

Ethics: no transactional interaction with scam infrastructure, GET-only landing-page capture in an isolated environment, defanged URLs, private individuals redacted, SHA-256 + UTC timestamp on every piece of evidence, responsible disclosure to Meta before publication, and a parallel Article 40 DSA researcher-access request.

Independent, unfunded, uncommissioned.

# Soulad se zadáním: kontrolní seznam

**Stav k:** 9. 11. 2026 večer · **Pro:** vedoucího projektu a programátory všech ostrovů · **Zadání:** v1.40, obrázky ke kap. 5–21 · **Rozsah:** schéma (`sql/migrace`), kontrakty a pravidla ostrovů B–G, vzorek XLSM ([rozbor](migrace-xlsm.md))

Obrázky ze zadání se dodržují striktně. Kde si zadání protiřečí nebo dává nelogický scénář, rozhoduje vedoucí projektu. Rozhodnutí jsou v tabulce níže. Než ostrov změní chování popsané v zadání, zkontroluje tento seznam.

Čísla R-xx (rozpory), A-xx (nejasnosti) a Q-xx (otázky) jsou ze sdíleného dokumentu „Analýza zadání a osnova aplikace“.

**Výsledek k 9. 11. večer:**
- Schéma, kontrakty a pravidla odpovídají obrázkům kap. 5–21.
- Kontrola našla 7 rozdílů (Z-01 až Z-07), všechny jsou opravené a mají test.
- Vedoucí projektu rozhodl 35 sporných bodů (D-01 až D-35); 9. 11. jich přibylo 25 (D-11 až D-35), včetně výchozích oprávnění rolí (matice G4, D-23).
- Žádné rozhodnutí nezůstává s otevřeným detailem: D-15, D-27 a D-34 rozhodl vedoucí projektu večer 9. 11. a k D-26 schválil výklad.
- Dva body jsou náš výklad a dají se změnit (V-01, V-02).

## Opraveno

Všechna nová pole jsou přidaná, nic se nepřejmenovalo ani neubralo (P10).

| # | Kap. | Co nesedělo | Oprava | Test |
|---|---|---|---|---|
| Z-01 | 7.2 | Prázdný STAT box byl šedý s výstrahou (náš původní návrh Q-31). Zadání chce zelenou (7.2 i 17.1 krok 7, A-04) a minimum barvu měnit nesmí. | `prehledy.domena.barva_boxu`: blokovaný, úplně prázdný, DYN s obsahem, STAT s obsahem. Kód `SEDA_VYSTRAHA` zrušen. | `test_barvy` |
| Z-02 | 17.2 | Výstup pro SVG neměl seřazené Pozice P01… | `kodPoziceUrovne` u každého boxu | `test_rozlozeni` |
| Z-03 | 17.1 krok 7 | DYN box s obsahem byl bílý podle 7.2 | modrý, kód `MODRA` (D-05) | `test_barvy`, `test_rozlozeni` |
| Z-04 | 12.2 | Po skenu zdrojové pozice byl díl a stav jen v textu popisu | výsledek skenu pozice nese `obsah`: díl a počet kusů | `test_sken` |
| Z-05 | 13.1 | Chyběl filtr „pouze díly s aktivním STAT umístěním“ a klik na konkrétní umístění | filtr `jenSeStat`; řádek nese `mista[]`, každé místo se zvýrazněním | `test_zasoby_a_laser` |
| Z-06 | 15 | Karta neměla kód STAT boxu (BSTAT037) ani „Chybí do maxima“ | `stat.kodBoxu`, `stat.chybiDoMaximaKs` | `test_karta` |
| Z-07 | 17 | Popup pozice v SVG neměl odkaz do Vaultu | `pozice[].vaultUrl` | `test_rozlozeni` |

## Rozhodnutí vedoucího projektu

| # | Kdy | Sporný bod | Rozhodnutí | Dopad |
|---|---|---|---|---|
| D-01 | 2. 11. | 7.1: kód pozice C7 u DYN je „R“, nebo „R1…Rn“? (Q-01, R-02) | jen **R** (BPLE052-R); R1…Rn je značení rozměrových variant | beze změny |
| D-02 | 2. 11. | XLSM má kódy BPLE01 (2 číslice), kap. 11.2 chce 3 | převést na **BPLE001**, nové štítky | import (H) |
| D-03 | 2. 11. | boxy v XLSM mají pevný díl a minimum (chování STAT), ale kód BPLE | **typ určí sklad po boxech** (podle D-07 v aplikaci) | import (H), administrace |
| D-04 | 2. 11. | XLSM JINÉ INFORMACE a „(N kusů na stroj)“ nemají v zadání cíl | **poznámka k dílu** | `Dil.Poznamka` (Δ17 v 001), pole `poznamka` v kontraktu D |
| D-05 | 3. 11. | barva DYN boxu s obsahem: 7.2 bílá, 17.1 krok 7 modrá (Q-31, R-03) | **modrá** | Z-03 |
| D-06 | 3. 11. | převod starého STAV_BOXU (Q-21) | návrh přijat: BLOK → blokovaný box, MULTI → přihrádky, 0, OPER, MEOP a POL se nepřevádí | import (H) |
| D-07 | 3. 11. | doplňovací tabulku od skladu firma nemá | import vezme z XLSM, co tam je; zbytek se **doplní a mění v aplikaci** | [migrace-xlsm.md](migrace-xlsm.md), sekce 4 |
| D-08 | 3. 11. | kap. 21.1.1 jmenuje pole odpovědi TransakceID | API dál vrací `transakceId`, psané jako ostatní pole (`requestId`, `cilKod`); údaj je stejný | beze změny |
| D-09 | 3. 11. | obrázek U03 dělí BPLE002 na „A \| B“, tabulka 7.1 takové členění nemá (R-12) | chyba obrázku, platí **tabulka 7.1** | beze změny |
| D-10 | 3. 11. | kap. 20: správa firem v administraci | **zatím ne**, otevřené na později; jediná firma HOUFEK je v počátečních datech | žádný endpoint; tabulka `Firma` je připravená |
| D-11 | 9. 11. | Q-07: přesun DYN → DYN | jen celá dávka v rámci pracoviště, atomicky PRESUN-OUT + PRESUN-IN se stejným TransakceID; část dávky nebo jiné pracoviště = výdej + příjem | E, odpovídá kroku 1 |
| D-12 | 9. 11. | Q-08: uskladnění do STAT | zdroj volí obsluha: DYN pozice (celá dávka i část) nebo „z výroby“; poslední operaci obsluha výslovně potvrdí volbou operace, systém ji neodvozuje | E, odpovídá kroku 1 |
| D-13 | 9. 11. | Q-09: co blokace blokuje | příjem, výdej i přesun na blokovaném zdroji i cíli; inventuru ani její korekce nezastaví; důvod, uživatel a čas v `AuditZmen`; blokují SKL, MISTR a ADMIN | C, E (korekce blokaci nekontroluje) |
| D-14 | 9. 11. | Q-10: chybí volná pozice správné velikosti | nabídnou se označené ostatní regály pracoviště; varianta „větší pozice pro MISTRa“ se nedělá, DYN vyžaduje přesnou velikost | E, odpovídá kroku 1 |
| D-15 | 9. 11. | Q-11: maximum STAT | měkké: příjem nad maximum dokončit jde, ale až po zobrazení varování. **Rozhodnuto 9. 11. (varianta a):** obrazovka ukáže varování před odesláním, pokud je překročení známé už tehdy; server zaúčtuje příjem jedním požadavkem a ve výsledku vrátí skutečné varování podle stavu ověřeného při zápisu; žádné druhé odeslání, potvrzovací příznak ani nový povinný prvek API; maximum zůstává měkké a varování není odmítnutí; vznikne-li překročení až souběžnou změnou, obrazovka ukáže aspoň varování ze serverové odpovědi. | E |
| D-16 | 9. 11. | Q-13: upozornění zásoby | jedno otevřené na STAT místo; při zhoršení se aktualizuje; samo se uzavře až nad minimem; 0 ks = VYCERPANO i při minimu 0; ručně uzavírá MISTR nebo ADMIN, vždy s poznámkou; TECH jen čte | E, matice G4 |
| D-17 | 9. 11. | Q-14: blokovaný STAT cíl | POSITION_BLOCKED, nic se nezmění, dávka zůstane v DYN; kontrola znovu uvnitř transakce | E, odpovídá kroku 1 |
| D-18 | 9. 11. | Q-15: sken cíle | na terminálu (PDA) povinný sken; ruční potvrzení jen na PC s RUCNI_POTVRZENI, ověří server; u pohybu se uloží RUCNE, jinak SKEN | migrace 005, E |
| D-19 | 9. 11. | Q-26: díl bez velikosti pozice | do DYN ne; do STAT jen přes aktivní přiřazení téhož dílu | E, odpovídá kroku 1 |
| D-20 | 9. 11. | Q-27: rekonfigurace boxu | jen zcela prázdný box bez STAT přiřazení; staré pozice `Aktivni = 0` (nemažou se), nové ze šablony, záznam v `AuditZmen`, nové štítky | C, odpovídá kroku 2 |
| D-21 | 9. 11. | Q-28: změna velikosti dílu s obsahem | zakázaná, dokud má díl obsah v DYN; jinak s auditem | D, hotovo |
| D-22 | 9. 11. | TD-24: dvojklik na „Přidat box“ | odloženo do fáze obrazovek, ale povinné před pilotem: dvojklik nesmí založit dva boxy | C, před pilotem |
| D-23 | 9. 11. | G4: výchozí oprávnění rolí | matice 9.9 analýzy bez TECH u UPOZORNENI_UZAVRIT (tabulka níže) | migrace 005 |
| D-24 | 9. 11. | Q-32: víc rolí na uživatele | právě jedna role, žádná individuální oprávnění | B, odpovídá |
| D-25 | 9. 11. | Q-24: oprávnění podle pracoviště | ve V1 ne; pracoviště terminálu jen předvyplní filtry | beze změny |
| D-26 | 9. 11. | Q-16: inventura za provozu | bez celoskladového zámku; položka si při fyzické kontrole uloží poslední PohybID pozice; při dokončení se stav a pozdější pohyby ověří znovu v téže transakci; pozdější pohyb nepřepíše zjištěný díl ani počet; jednoznačné změny množství téhož dílu se dopočtou; změna dílu, uvolnění a nové obsazení pozice, rekonfigurace nebo jiná nejasná změna → položka znovu k fyzické kontrole; dočasná blokace boxu nebo pozice je volitelná. **Výklad schválený 9. 11.:** stav zapsané položky podle pohybů pozice po vodoznaku – žádný pohyb → ZAPSANO; SHODA nebo ROZDIL, všechny pohyby téhož dílu, žádné vyprázdnění pozice s dalším pohybem po něm a nezáporný dopočet (aktuální stav + RozdilKs) → ZAPSANO s dopočtem; jinak (jiný díl, vyprázdnění a nové obsazení, rekonfigurace, záporný dopočet, jakýkoli pohyb u JINY_DIL) → PREPOCITAT, tedy nová fyzická kontrola a nový zápis s novým vodoznakem, ne další automatický výpočet. Pozdější pohyb nikdy nemění SkutecnyDilID ani SkutecnyPocetKs. Při dokončení se po zámku pozic znovu načte aktuální stav i pohyby po vodoznaku, sestaví se aktuální plán korekcí a zaúčtuje se v téže SQL transakci; kontrola jen při zobrazení nestačí. | migrace 005, F |
| D-27 | 9. 11. | Q-17, S-22: jiný díl na pozici | ve STAT i v DYN: očekávaný díl se odúčtuje, nalezený se zaúčtuje na zvolený cíl, při dokončení znovu ověřený (volná neblokovaná DYN pozice přesné velikosti, nebo STAT místo přiřazené nalezenému dílu); současná pozice jen tehdy, když pro nalezený díl po korekci platí; bez cíle nejde inventuru dokončit; všechny korekce pohyby v jedné transakci, přímý přepis `DilID` zakázaný. **Rozhodnuto 9. 11.:** blokovaná pozice nesmí být cílem nalezeného dílu, ani když jde o současnou pozici; inventurník zvolí jiný platný cíl, nebo se blokace před dokončením odstraní, jinak položka zůstane nevyřešená. Pravidlo platí jen pro výběr cíle u JINY_DIL; Q-09 pro ostatní inventurní kontroly a korekce nemění. | F |
| D-28 | 9. 11. | Q-22: doporučení pro laser | základ = max(0, Maximum − STAT − DYN, je-li `odecitatDyn` zapnutý); doporučeno = 0 při nulovém základu, jinak základ zaokrouhlený nahoru na standardní dávku (smí přes maximum; díl bez standardní dávky se nezaokrouhluje); výchozí `odecitatDyn` = zapnuto | G |
| D-29 | 9. 11. | Q-20: počáteční stavy | z fyzické inventury po regálech při spuštění, řízenými pohyby POCAT-STAV; XLSM jen pro struktury a kmenová data; reálný vzorek XLSM je povinný vstup pro H | H |
| D-30 | 9. 11. | Q-18: terminál | prohlížeč na PDA, čtečka jako klávesnice, osobní číslo + PIN (jen hash); konkrétní Chainway ověřit před pilotem | B, před pilotem |
| D-31 | 9. 11. | Q-19: štítky | backend generuje PDF s Code 128, ZPL až podle tiskárny; samostatné štítky boxu i vnitřní pozice, i u C1 a C7 | C, před pilotem |
| D-32 | 9. 11. | Q-23: zmetky | ve V1 bez evidence; vrácené množství standardní operací, rozdíl do poznámky pohybu | beze změny |
| D-33 | 9. 11. | TD-07 (Q-33): zámek PINu | 5 chybných PINů po sobě → zámek účtu na 15 min; úspěšné přihlášení vynuluje počítadlo; odemknout může ADMIN; pokusy se auditují bez PINu. **Dopřesněno 9. 11.:** pátý chybný PIN po sobě se zapíše jako `CHYBNY_PIN`, nastaví `ZamcenoDo` = aktuální UTC + 15 minut a `ChybnePokusy` = 0; pokusy během zámku se zapisují jako `ZAMCENO`, nezvyšují počítadlo, neprodlužují `ZamcenoDo` a PIN se už neověřuje; po 15 minutách zámek sám přestane platit a uživatel má novou sérii 5 pokusů, zásah ADMINa není potřeba; úspěšné přihlášení vynuluje `ChybnePokusy` a odstraní případný vypršený `ZamcenoDo`; zamčený účet dostane stejnou obecnou odpověď jako chybný PIN, `ZAMCENO` je jen interní evidence v `PrihlaseniPokus`, ne veřejná chyba; odemčení ADMINem nastaví `ZamcenoDo` = NULL a `ChybnePokusy` = 0 a zapíše se do auditu; reset PINu účet neodemkne ani nezkrátí běžící zámek, k okamžitému obnovení přístupu musí ADMIN provést samostatné odemčení; žádný záznam nenese PIN. | B, migrace, před pilotem |
| D-34 | 9. 11. | TD-06 (Q-34): nečinnost | PDA: odhlášení po 15 min nečinnosti, posuvné, platí na serveru. TD‑06 hotové: PDA 15 minut posuvně na serveru; PC stávajících 12 hodin beze změny. | B, platforma, před pilotem |
| D-35 | 9. 11. | kód boxu z předtištěného štítku | ano, nepovinně: do zakládání boxu se přidá nepovinné `KodBoxu`, obsluha ho naskenuje nebo zadá; prázdná hodnota = automatické číslo řady; zadaný kód se normalizuje, ověří se formát a jedinečnost, kolize box nevytvoří; `KodBoxu` a `FullBoxKlic` jsou v databázi jedinečné; `FullBoxKlic` a kódy vnitřních pozic odvozuje systém, obsluha do nich nezasahuje. **Rozšířeno 9. 11. na výměnu boxu:** výměna přijímá nepovinný kód ze štítku nového fyzického boxu, prázdná hodnota = automatické číslo řady jako při zakládání; platí stejná normalizace a kontrola formátu a jedinečnosti vůči celé tabulce `Box`, tedy i vůči historickým kódům; při kolizi se celá výměna odmítne a starý box nesmí být mezitím deaktivován; starý box a jeho `KodBoxu` zůstávají v historii beze změny, nový box dostane vlastní `BoxID`; výměna je jedna transakce, která zachová `PoziceID` a nikdy nenechá pozici bez boxu ani se dvěma boxy; `FullBoxKlic` a vnitřní pozice nového boxu vytváří systém; do auditu patří vazba starý box → nový box, kód ze štítku, uživatel a čas. | C |

Schéma 001 ještě nikde v provozu neběželo, proto `Dil.Poznamka` přibyl přímo do něj. Po prvním spuštění už jen novou migrací (ADR-0003).

### Matice výchozích oprávnění rolí (G4, rozhodnutí D-23)

Seed v migraci `005_rozhodnuti_9_11.sql` je přesně tato matice; test je `tests/integrace/test_migrace_005.py`. Ostrovy berou tuto matici jako hotový fakt a nic k ní nedomýšlejí. Databáze – sdílená testovací i provozní – ale může obsahovat i řádky, které v matici nejsou: testy ostrova B si `RoleOpravneni` svých rolí přepisují samy, a proto test výchozí stav matice nezjišťuje nad sdílenými daty po cizích testech, ale smaže je a znovu založí ve své transakci.

| Oprávnění | OPER | SKL | MISTR | TECH | ADMIN |
|---|---|---|---|---|---|
| DIL_CIST | ✓ | ✓ | ✓ | ✓ | ✓ |
| SKLAD_PRIJEM, SKLAD_VYDEJ | ✓ | ✓ | ✓ | – | ✓ |
| SKLAD_PRESUN, INVENTURA | – | ✓ | ✓ | – | ✓ |
| KOREKCE | – | – | ✓ | – | ✓ |
| BOX_EDIT, UZIVATEL_EDIT | – | – | – | – | ✓ |
| BLOKACE | – | ✓ | ✓ | – | ✓ |
| RUCNI_POTVRZENI | – | – | ✓ | – | ✓ |
| UPOZORNENI_UZAVRIT | – | – | ✓ | – | ✓ |
| KMEN_EDIT, STAT_EDIT | – | – | – | ✓ | ✓ |
| AUDIT_CIST | – | – | ✓ | ✓ | ✓ |

## Náš výklad (změní se jedním rozhodnutím)

| # | Kap. | Co zadání neříká | Výklad projektu |
|---|---|---|---|
| V-01 | 13.1 | výchozí hodnotu filtru „pouze díly s aktivním STAT umístěním“ | Filtr je zapnutý: monitoring hlídá zásobu ve STAT a souhrn počítá díly se STAT místem. Vypnutím přibudou díly, které leží jen v DYN, bez stavu. |
| V-02 | 21 | co je „BoxID“ ve vyhledávání | kód boxu ze štítku (BPLE037). Vnitřní číselné ID uživatel nevidí. |

## Kontrola po kapitolách

| Kap. | Zadání (obrázek) | Projekt | Stav |
|---|---|---|---|
| 5 XLSM | mapování sloupců, žádné kopírování 1:1 | [migrace-xlsm.md](migrace-xlsm.md), import a doplnění v aplikaci (D-07) | ✔ |
| 6 Hierarchie | Firma → Pracoviště → Regál → Úroveň → Pozice → Box → Vnitřní pozice → Obsah | tabulky a sloupce shodné; `Box.PoziceID` NOT NULL a unikátní mezi aktivními boxy | ✔ s odchylkou Δ1 (G1, Q-04): vyměněný box zůstává v historii |
| 6.1 Pracoviště | 8 kódů a názvů v daném pořadí | seed 001 přesně v tomto pořadí | ✔ |
| 6.2 Pozice P01…Pn | jen pořadí boxu pro SVG, 1 Pozice = 1 Box | `Pozice.KodPozice` z `Poradi`; SVG řadí podle `Poradi` | ✔ |
| 7 DYN / STAT | DYN se při 0 ks uvolní, STAT zůstává dílu | řádek obsahu se při 0 ks maže; vyhrazení drží `StatickeUmisteniDilu` | ✔ |
| 7.1 Členění | C1–C7, V1–V6, písmena podle obrázku | šablona v 001 přihrádku po přihrádce; C7: DYN R, STAT 1 | ✔ (D-01, D-09) |
| 7.2 Barva boxu | priorita blokovaný, prázdný, DYN, STAT; minimum barvu nemění | Z-01, Z-03 | ✔ |
| 8 Kmenová data | IdentifikacniCislo, materiál, tloušťka, první operace, dávka, velikost, Vault, Aktivni | stejné sloupce; navíc název, rozměr pro V6 (Q-01), poznámka (D-04) | ✔ |
| 8.1 Velikost pozice | pevná v kmeni dílu, nabídka jen stejné velikosti, V6 podle rozměru C7 | `vejde_se`, kandidáti DYN, `PotrebnaDelkaMM/HloubkaMM` | ✔ |
| 8.2 Číselníky | materiály, tloušťky, první operace; filtry ze SQL | seed 001 podle tabulky; filtry z `/api/dily/ciselniky` a `/api/prehledy/ciselniky` | ✔ |
| 9 Stav a historie | ObsahPozice a SkladovyPohyb; záporný stav a ruční přepis zakázané | CHECK `StavPo = StavPred + Mnozstvi ≥ 0`; DENY UPDATE na historii | ✔ |
| 11 Barcode | kódy boxů, pozic, regálu, FullBoxKlic | všechny příklady ze zadání v testech parseru | ✔ |
| 12.1 Zaskladnění DYN | díl → regál → kandidáti → cíl skenem nebo potvrzením → ObsahPozice + pohyb v jedné transakci; kandidát jen v aktivním DYN boxu, neblokovaný, prázdný, stejné velikosti, u V6 rozměr R pojme dávku; řazení podle čísla boxu | `GET /api/sklad/kandidati-dyn` (řazení `int(kod_boxu[-3:])`), `POST /prijem-dyn`, `zpusobPotvrzeni` SKEN/RUCNE (Q-15), rozměr R řízeně `POST /api/struktura/vnitrni-pozice/{id}/rozmer-c7` | ✔ |
| 12.2 Vyskladnění DYN | sken zdroje, díl a stav, 0 < množství ≤ stav, při 0 ks smazat obsah, box zezelená | Z-04; `POST /api/sklad/vydej` (INSUFFICIENT_STOCK, `ocekavanyStavKs`); barva podle Z-01 | ✔ |
| 12.3 Přesun | PRESUN-OUT + PRESUN-IN se stejným TransakceID, cíl kompatibilní a prázdný, jen celá dávka | `POST /api/sklad/presun` bez množství (WHOLE_BATCH_ONLY); „oblast“ = pracoviště (Q-07, A-01) | ✔ |
| 13 STAT, min, max | OK / NA MINIMU / POD MINIMEM / VYČERPÁNO; jedno otevřené upozornění, uzavře se nad minimem; jedno aktivní přiřazení na pozici | `sklad.domena.stav_zasoby`, `vyhodnot_upozorneni`; filtrovaný UNIQUE index `UX_StatickeUmisteni_Pozice_Aktivni` | ✔ (stav 0 při minimu 0 = VYČERPÁNO, N-08) |
| 13.1 Monitoring | souhrn, jedním klikem jen problémové, filtry, STAT a DYN zvlášť, klik na díl i na umístění | `GET /api/prehledy/zasoby` (`jenProblemove`, `jenSeStat`, `mista[]`); Z-05, V-01 | ✔ |
| 14 Laser | první operace LASER, filtry materiál, tloušťka, operace, pod maximem; chybí = Maximum − STAT | `GET /api/prehledy/laser`; „doporučeno vyrobit“ s přepínačem `odecitatDyn` podle D-28 (základ Maximum − STAT − DYN, zaokrouhlení nahoru na standardní dávku) | ✔ (rozhodnuto D-28, provádí G) |
| 15 Karta dílu | kmenová data, Vault (jinak „Výkres ve Vaultu není přiřazen“), STAT s aktuálně/min/max a chybí do maxima, DYN umístění, historie | `GET /api/prehledy/dily/{id}/karta`; Z-06; text pro chybějící Vault řeší UI (komentář v kontraktu) | ✔ |
| 16 Vyhledávání | jedno vyhledávání pro díl, box, STAT a DYN pozici, regál; filtry pracoviště, operace, materiál, tloušťka, typ boxu, stav; vždy přepnout SVG a zvýraznit | `GET /api/prehledy/hledat`, `/sken/{kod}`; `zvyrazneni` regál → úroveň → box → přihrádka; více výsledků = seznam | ✔ |
| 17 SVG regálů | mm, viewBox z boxů a okrajů, řazení podle Poradi, svislé centrování, přihrádky podle konfigurace, zvýraznění, popup | `GET /api/prehledy/urovne/{id}/rozlozeni`; Z-07; vzhled zvýraznění a popupu je práce UI (fáze 3) | ✔ |
| 17.1 Princip SVG | kroky 1–8, vzorce X, šířky a výšky, barvy | `struktura.domena.rozmisteni_boxu` přesně podle vzorců; barvy Z-01, Z-03 | ✔ |
| 17.2 Výstup API | metadata úrovně, seřazené Pozice, Box, rozměry, typ, členění, vnitřní pozice, obsah a stav | Z-02 | ✔ |
| 18 Inventura | celý sklad i rozsah, slepá, korekce pohybem, JINÝ DÍL bez přepisu DilID | rozsahy FULL…POZICE, stavy ROZPRACOVANA/DOKONCENA/ZRUSENA, `zauctuj_korekci`; inventura za provozu bez celoskladového zámku a korekce jiného dílu podle D-26 a D-27, na to sloupec `InventuraPolozka.PosledniPohybID` (migrace 005) | ✔ (rozhodnuto D-26 a D-27, provádí F) |
| 19 Role a terminály | OPER, SKL, MISTR, TECH, ADMIN; N:M přes RoleOpravneni; PIN jen hash; Terminal s kódem, názvem, pracovištěm a Aktivni | seed rolí, `RoleOpravneni` – výchozí oprávnění podle matice G4 (migrace 005, D-23), `PinHash` (argon2), tabulka `Terminal` | ✔ (matice G4 zapsána a otestována) |
| 20 Administrace | díly, číselníky, firmy, pracoviště, regály, úrovně, boxy, STAT místa, min/max, uživatelé, role; žádné ruční přepsání počtu kusů; deaktivace místo DELETE; audit zásadních změn | endpointy C, D, E a B; počet kusů mění jen příjem, výdej, přesun, inventura a korekce; `004` bere DELETE; `AuditZmen` | ✔ kromě firem (D-10) |
| 21 Oblasti API | čtení úrovně, vyhledávání, kandidáti, příjem a výdej, přesun, inventura, administrace | všechny oblasti mají endpointy (73 + 4 Platformy) | ✔ (V-02) |
| 21.1 Datové kontrakty | ID od klienta nejsou důvěryhodná; před změnou znovu načíst stav ze SQL, ověřit oprávnění a podmínky | služby čtou stav uvnitř `@transakce` po zamčení pozic (ADR-0004, 0005); kontrola jen v JS se nepočítá | ✔ |
| 21.1.1 Formát odpovědi | success, code (OK, POSITION_OCCUPIED, WRONG_PART, NO_PERMISSION …), message česky bez SQL chyby, data, TransakceID | obálka `success`, `code`, `message`, `data`, `transakceId`, navíc `varovani`; chyby SQL převádí `sql_chyby` | ✔ (D-08) |

## Vzorové ukázky ze zadání: odkud se vezmou data

Každý vzor ze zadání musí jít složit z databáze. Tabulka říká z čeho.

| Vzor | Údaj | Databáze | API |
|---|---|---|---|
| 13.1 monitoring | STAT ks, DYN ks, Celkem, Minimum, Maximum, Stav | `v_ZasobaDilu` (StatKs, DynKs, CelkemKs, Min/Max, StavZasoby) | `GET /api/prehledy/zasoby` |
| 13.1 monitoring | Umístění „STAT + 2× DYN“ a klik na místo | `v_ObsahPozice` + `v_Misto` | `umisteni`, `mista[]` |
| 14 laser | materiál, tloušťka, STAT aktuálně, maximum, chybí do maxima | `v_Dil` + `v_ZasobaDilu` | `GET /api/prehledy/laser` |
| 15 karta | první operace, materiál, tloušťka, dávka, velikost, Vault | `v_Dil` | `GET /api/prehledy/dily/{id}/karta` |
| 15 karta | BSTAT037, aktuálně, min, max, chybí do maxima | `v_StatickeMisto` + `v_ZasobaDilu` | `stat.kodBoxu`, `stavKs`, `minimalniKs`, `maximalniKs`, `chybiDoMaximaKs` |
| 15 karta | BPLE003-D, 30 ks | `v_ObsahPozice` + `v_Misto` | `umisteni[]` |
| 15 karta | historie pohybů | `v_PohybDetail` | `posledniPohyby`, `GET /api/prehledy/pohyby?dilId=` |
| 16 Model F | regál R01 → úroveň U03 → box BPLE037 → přihrádka D | `v_Misto` | `zvyrazneni` |
| 17.1 příklad U03 | P01…P04, BPLE001, BPLE002, BSTAT037, BPLE010, šířky v mm | `Pozice`, `Box`, `CleneniBoxu`, `SablonaCleneni` | `GET /api/prehledy/urovne/{id}/rozlozeni` |
| 17 popup | BoxID, díl, počet, Vault, stav | `Box`, `v_ObsahPozice`, `v_Dil` | `kodBoxu`, `pozice[].identifikacniCislo`, `pocetKs`, `vaultUrl`, `stavBoxu` |

Čísla ve vzorech si navzájem neodpovídají (R-09). U AAR10044 má karta minimum 4, maximum 30 a 2 × 30 ks v DYN, monitoring minimum 10, maximum 40 a 18 ks v DYN. Na kód to vliv nemá a jako testovací data se vzory nepoužívají.

## Rozpory v zadání

Obrázky jsou podle kap. 17.2 ilustrační, závazná jsou pravidla v textu. Rozpor mezi dvěma pravidly rozhoduje vedoucí projektu.

| # | Co si protiřečí | Jak je to vyřešené |
|---|---|---|
| R-03 | barva DYN s obsahem: tabulka 7.2 bílá, tabulka 17.1 krok 7 modrá | D-05: modrá |
| R-04 | obrázek „Princip generování SVG“: „viewBox = rozměr úrovně“, „Y podle plochy úrovně“, „členění C1…C6“; text kap. 17 a 17.1: viewBox z vykreslených boxů a okrajů, C1…C7 | platí text, kap. 17 to říká výslovně |
| R-09 | čísla ve vzorových ukázkách (viz výše) | neovlivňuje kód |
| R-12 | stejný obrázek dělí BPLE002 na „A \| B“ | D-09: platí tabulka 7.1 |

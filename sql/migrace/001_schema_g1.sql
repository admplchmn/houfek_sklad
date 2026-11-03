/* =============================================================================
   HOUFEK a.s. – Skladový systém
   Databázové schéma po bráně G1 · Microsoft SQL Server 2016 a novější
   -----------------------------------------------------------------------------
   Zdroj:     Zadávací dokumentace v1.40 – kap. 6–13, 22–24 (datový slovník
              kap. 23 a 23.1) a příloha A (seed hodnoty).
   Změny:     rozhodnutí G1 z 25. 10. 2026 – Q-01 až Q-06, Q-12, Q-25, Q-29, Q-30.
   Spuštění:  nad PRÁZDNOU databází, např.
                sqlcmd -S <server> -d <databaze> -I -f 65001 -i houfek_sklad_schema_g1.sql
              -I        = QUOTED_IDENTIFIER ON (nutné pro filtrované indexy;
                          platí i pro další skripty, které do tabulek zapisují)
              -f 65001  = soubor je v UTF-8 (jinak se poškodí české názvy v seed datech)
   Kolace DB: doporučeno Czech_100_CI_AS (české řazení názvů, CH po H).
              Technické kódy jsou ASCII a CHECK omezení používají binární kolaci,
              na kolaci databáze tedy nezávisí.
   -----------------------------------------------------------------------------
   Odchylky od 1:1 zadání (u tabulek označeny [Δn]):
   Δ1  Q-04    Box(PoziceID) unikátní jen mezi aktivními boxy (filtrovaný index),
               vyměněný box zůstává v historii.
   Δ2  Q-04    Pozice.KodPozice je počítaný sloupec z Poradi (P01, P02 …);
               Poradi je unikátní na úrovni mezi aktivními pozicemi.
   Δ3  Q-05    VnitrniPoziceBoxu.VelikostPoziceID je NOT NULL i pro STAT.
   Δ4  Q-01    VnitrniPoziceBoxu.DelkaMM/HloubkaMM = aktuální rozměr C7;
               Dil.PotrebnaDelkaMM/PotrebnaHloubkaMM = požadavek dílu V6.
   Δ5  Q-06    Nová tabulka SablonaCleneni (19 řádků C1–C7) a vazba
               VnitrniPoziceBoxu.SablonaCleneniID: jeden zdroj kódů, velikostí
               a geometrie pro barcode i SVG.
   Δ6  Q-29    VelikostPozice.Poradi a PlochaMM2 (prozatím pořadí V1–V6, plocha NULL).
   Δ7  Q-12    StatickeUmisteniDilu(DilID) unikátní mezi aktivními přiřazeními.
   Δ8  Q-25    Technické hodnoty v CHECK jen ASCII velkými písmeny.
   Δ9  Q-03, Q-04, Q-30
               Pohled v_KontrolaIntegrity pro noční kontrolu pravidel, která
               nejde vynutit omezením.
   Δ10 A-14    VnitrniPoziceBoxu(BoxID, KodPozice) unikátní jen mezi aktivními
               pozicemi – jinak rekonfigurace boxu smaže historii.
   Δ11         Aktivni, Blokovany a kódy číselníků NOT NULL – NULL v Aktivni by
               obešel filtrované indexy WHERE Aktivni = 1.
   Δ12         Uzivatel.KodKarty unikátní jen u vyplněných hodnot
               (UNIQUE v SQL Serveru povoluje jediný NULL).
   Δ13         SkladovyPohyb: CHECK StavPo = StavPred + Mnozstvi, stavy nezáporné.
   Δ14         Inventura: CHECK konzistence rozsahu (kap. 23.1 „musí odmítnout“)
               a dokončení.
   Δ15         StatickeUmisteniDilu(VnitrniPoziceID) unikátní mezi aktivními
               přiřazeními – vyžaduje kap. 13, v návrhu chybělo.
   Δ16         Databázová role app_sklad: DENY UPDATE, DELETE na SkladovyPohyb
               a AuditZmen (historie je neměnná).
   Δ17         Dil.Poznamka: pokyny pro obsluhu ze sloupce JINÉ INFORMACE v XLSM
               (rozhodnutí vedoucího projektu 2. 11. 2026, před prvním spuštěním skriptu).
   Δ18 TD-11   Všechny DATETIME2 mají DEFAULT (SYSUTCDATETIME()), do DATETIME2 se ukládá UTC.
               Místní čas bez zóny by byl při přechodu na zimní čas dvojznačný a závisel by na
               časovém pásmu stroje – SQL Server běží na UTC, aplikace psala místní čas.
               Najevo se převádí na místní čas (app.platforma.kontrakty).
               (rozhodnutí vedoucího projektu 3. 11. 2026, před prvním spuštěním skriptu).
   Záměrně nezavedeno (brána G2/G3): hlavička transakce s requestId,
   ZpusobPotvrzeni / NaskenovanyKod, údaje o blokaci, rowversion, PosledniPohybID.
   ============================================================================= */

SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET ARITHABORT ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET NUMERIC_ROUNDABORT OFF;
GO

IF OBJECT_ID(N'dbo.Firma', N'U') IS NOT NULL
BEGIN
    RAISERROR (N'Schéma už v databázi existuje – skript je určen pro prázdnou databázi. Nic se neprovede.', 16, 1);
    SET NOEXEC ON;
END;
GO


/* =============================================================================
   1. FYZICKÁ HIERARCHIE (kap. 6, 23)
   ============================================================================= */

CREATE TABLE dbo.Firma (
    FirmaID         INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Firma PRIMARY KEY,
    KodFirmy        VARCHAR(20)   NOT NULL CONSTRAINT UQ_Firma_KodFirmy UNIQUE,
    NazevFirmy      NVARCHAR(150) NOT NULL,
    Aktivni         BIT NOT NULL CONSTRAINT DF_Firma_Aktivni DEFAULT (1),
    CONSTRAINT CK_Firma_KodFirmy CHECK (KodFirmy <> '' AND KodFirmy COLLATE Latin1_General_BIN NOT LIKE '%[^0-9A-Z]%')
);

CREATE TABLE dbo.Pracoviste (
    PracovisteID    INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Pracoviste PRIMARY KEY,
    FirmaID         INT NOT NULL CONSTRAINT FK_Pracoviste_Firma REFERENCES dbo.Firma (FirmaID),
    KodPracoviste   VARCHAR(20)   NOT NULL,               -- PLE, 1SV, … (kap. 6.1)
    NazevPracoviste NVARCHAR(100) NULL,
    Aktivni         BIT NOT NULL CONSTRAINT DF_Pracoviste_Aktivni DEFAULT (1),   -- [Δ11]
    CONSTRAINT UQ_Pracoviste_Firma_Kod UNIQUE (FirmaID, KodPracoviste),
    CONSTRAINT CK_Pracoviste_Kod CHECK (KodPracoviste <> '' AND KodPracoviste COLLATE Latin1_General_BIN NOT LIKE '%[^0-9A-Z]%')
);

CREATE TABLE dbo.Regal (
    RegalID         INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Regal PRIMARY KEY,
    PracovisteID    INT NOT NULL CONSTRAINT FK_Regal_Pracoviste REFERENCES dbo.Pracoviste (PracovisteID),
    KodRegalu       VARCHAR(20)   NOT NULL,               -- R01
    NazevRegalu     NVARCHAR(100) NULL,
    Aktivni         BIT NOT NULL CONSTRAINT DF_Regal_Aktivni DEFAULT (1),        -- [Δ11]
    CONSTRAINT UQ_Regal_Pracoviste_Kod UNIQUE (PracovisteID, KodRegalu),
    CONSTRAINT CK_Regal_Kod CHECK (KodRegalu <> '' AND KodRegalu COLLATE Latin1_General_BIN NOT LIKE '%[^0-9A-Z]%')
);

CREATE TABLE dbo.Uroven (
    UrovenID        INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Uroven PRIMARY KEY,
    RegalID         INT NOT NULL CONSTRAINT FK_Uroven_Regal REFERENCES dbo.Regal (RegalID),
    KodUrovne       VARCHAR(20)   NOT NULL,               -- U00, U03
    Poradi          INT NOT NULL,                         -- svislé pořadí
    DelkaPlochyMM   DECIMAL(10,2) NOT NULL CONSTRAINT CK_Uroven_Delka   CHECK (DelkaPlochyMM   > 0),  -- jen informační údaj, ne rozměr SVG
    HloubkaPlochyMM DECIMAL(10,2) NOT NULL CONSTRAINT CK_Uroven_Hloubka CHECK (HloubkaPlochyMM > 0),
    Aktivni         BIT NOT NULL CONSTRAINT DF_Uroven_Aktivni DEFAULT (1),       -- [Δ11]
    CONSTRAINT UQ_Uroven_Regal_Kod UNIQUE (RegalID, KodUrovne),
    CONSTRAINT CK_Uroven_Kod CHECK (KodUrovne <> '' AND KodUrovne COLLATE Latin1_General_BIN NOT LIKE '%[^0-9A-Z]%')
);

-- Pozice = trvalá identita pořadí boxu na úrovni (kap. 6.2). PoziceID se nemění,
-- KodPozice je jen zobrazovaný štítek odvozený z Poradi.
-- Přečíslování (vložení boxu doprostřed) dělá procedura ve dvou krocích:
-- Poradi + 10000 pro dotčené pozice, potom cílové hodnoty – kvůli unikátnímu indexu.
CREATE TABLE dbo.Pozice (
    PoziceID        INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Pozice PRIMARY KEY,
    UrovenID        INT NOT NULL CONSTRAINT FK_Pozice_Uroven REFERENCES dbo.Uroven (UrovenID),
    Poradi          INT NOT NULL CONSTRAINT CK_Pozice_Poradi CHECK (Poradi > 0),
    KodPozice       AS (CONVERT(VARCHAR(20), CASE WHEN Poradi < 10 THEN 'P0' ELSE 'P' END + CONVERT(VARCHAR(10), Poradi))) PERSISTED NOT NULL,  -- [Δ2]
    Aktivni         BIT NOT NULL CONSTRAINT DF_Pozice_Aktivni DEFAULT (1)        -- [Δ11]
);


/* =============================================================================
   2. BOXY, KONFIGURACE A ŠABLONA ČLENĚNÍ (kap. 7, 11, 23)
   ============================================================================= */

CREATE TABLE dbo.TypBoxu (
    TypBoxuID       INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_TypBoxu PRIMARY KEY,
    KodTypu         VARCHAR(10)  NOT NULL CONSTRAINT UQ_TypBoxu_KodTypu UNIQUE,    -- [Δ11]
    NazevTypu       NVARCHAR(50) NOT NULL,
    CONSTRAINT CK_TypBoxu_KodTypu CHECK (KodTypu COLLATE Latin1_General_BIN IN ('STAT', 'DYN'))
);

CREATE TABLE dbo.CleneniBoxu (
    CleneniBoxuID   INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CleneniBoxu PRIMARY KEY,
    KodCleneni      VARCHAR(10) NOT NULL CONSTRAINT UQ_CleneniBoxu_KodCleneni UNIQUE,  -- C1..C7 [Δ11]
    PocetPozic      INT NOT NULL CONSTRAINT CK_CleneniBoxu_PocetPozic CHECK (PocetPozic > 0)
);

CREATE TABLE dbo.VelikostPozice (
    VelikostPoziceID INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_VelikostPozice PRIMARY KEY,
    KodVelikosti     VARCHAR(10)  NOT NULL CONSTRAINT UQ_VelikostPozice_KodVelikosti UNIQUE,  -- V1..V6 [Δ11]
    Nazev            NVARCHAR(50) NOT NULL,
    Poradi           INT NOT NULL CONSTRAINT UQ_VelikostPozice_Poradi UNIQUE,  -- [Δ6] pořadí podle skutečné plochy (Q-29)
    PlochaMM2        DECIMAL(12,2) NULL CONSTRAINT CK_VelikostPozice_Plocha CHECK (PlochaMM2 > 0),  -- [Δ6] doplní se po dodání rozměrů (A-08)
    CONSTRAINT CK_VelikostPozice_Kod CHECK (KodVelikosti COLLATE Latin1_General_BIN LIKE 'V[1-9]')
);

-- [Δ5] Šablona vnitřních pozic pro každou konfiguraci (Q-06).
-- Rada 1 = zadní řada (nejdál od hlavního štítku boxu), Sloupec 1 = vlevo.
-- RelX/RelY/RelSirka/RelHloubka = poloha přihrádky jako podíl rozměru boxu (0–1) pro SVG.
-- Poradi = pořadí kandidátů v boxu podle české abecedy DYN kódu (CH po H).
-- DelkaMM/HloubkaMM = nominální rozměr přihrádky, doplní technologové (A-08).
CREATE TABLE dbo.SablonaCleneni (
    SablonaCleneniID INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_SablonaCleneni PRIMARY KEY,
    CleneniBoxuID    INT NOT NULL CONSTRAINT FK_SablonaCleneni_CleneniBoxu REFERENCES dbo.CleneniBoxu (CleneniBoxuID),
    DynKod           VARCHAR(2) NOT NULL,
    StatKod          VARCHAR(2) NOT NULL,
    Poradi           INT NOT NULL,
    Rada             TINYINT NOT NULL CONSTRAINT CK_SablonaCleneni_Rada    CHECK (Rada    > 0),
    Sloupec          TINYINT NOT NULL CONSTRAINT CK_SablonaCleneni_Sloupec CHECK (Sloupec > 0),
    VelikostPoziceID INT NOT NULL CONSTRAINT FK_SablonaCleneni_VelikostPozice REFERENCES dbo.VelikostPozice (VelikostPoziceID),
    RelX             DECIMAL(5,4) NOT NULL,
    RelY             DECIMAL(5,4) NOT NULL,
    RelSirka         DECIMAL(5,4) NOT NULL,
    RelHloubka       DECIMAL(5,4) NOT NULL,
    DelkaMM          DECIMAL(10,2) NULL,
    HloubkaMM        DECIMAL(10,2) NULL,
    CONSTRAINT UQ_SablonaCleneni_DynKod  UNIQUE (CleneniBoxuID, DynKod),
    CONSTRAINT UQ_SablonaCleneni_StatKod UNIQUE (CleneniBoxuID, StatKod),
    CONSTRAINT UQ_SablonaCleneni_Poradi  UNIQUE (CleneniBoxuID, Poradi),
    CONSTRAINT UQ_SablonaCleneni_Mrizka  UNIQUE (CleneniBoxuID, Rada, Sloupec),
    CONSTRAINT CK_SablonaCleneni_DynKod  CHECK (DynKod COLLATE Latin1_General_BIN IN
        ('A','B','C','D','E','F','G','H','CH','I','J','K','L','M','N','O','P','Q','R')),
    CONSTRAINT CK_SablonaCleneni_StatKod CHECK (StatKod COLLATE Latin1_General_BIN LIKE '[1-9]'),
    CONSTRAINT CK_SablonaCleneni_Geometrie CHECK (RelX >= 0 AND RelY >= 0 AND RelSirka > 0 AND RelHloubka > 0
                                                  AND RelX + RelSirka <= 1 AND RelY + RelHloubka <= 1),
    CONSTRAINT CK_SablonaCleneni_Rozmer CHECK ((DelkaMM IS NULL AND HloubkaMM IS NULL) OR (DelkaMM > 0 AND HloubkaMM > 0))
);

CREATE TABLE dbo.Box (
    BoxID           INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Box PRIMARY KEY,
    PoziceID        INT NOT NULL CONSTRAINT FK_Box_Pozice REFERENCES dbo.Pozice (PoziceID),  -- 1:1 jen mezi aktivními [Δ1], index v oddílu 8
    KodBoxu         VARCHAR(40)  NOT NULL CONSTRAINT UQ_Box_KodBoxu UNIQUE,      -- BPLE037 / BSTAT037, trvalá identita na štítku
    TypBoxuID       INT NOT NULL CONSTRAINT FK_Box_TypBoxu REFERENCES dbo.TypBoxu (TypBoxuID),
    CleneniBoxuID   INT NOT NULL CONSTRAINT FK_Box_CleneniBoxu REFERENCES dbo.CleneniBoxu (CleneniBoxuID),
    DelkaMM         DECIMAL(10,2) NOT NULL CONSTRAINT CK_Box_Delka   CHECK (DelkaMM   > 0),
    HloubkaMM       DECIMAL(10,2) NOT NULL CONSTRAINT CK_Box_Hloubka CHECK (HloubkaMM > 0),
    FullBoxKlic     VARCHAR(150) NOT NULL CONSTRAINT UQ_Box_FullBoxKlic UNIQUE,  -- Q-03: uložená adresa, přepočet v transakci přesunu boxu
    Blokovany       BIT NOT NULL CONSTRAINT DF_Box_Blokovany DEFAULT (0),        -- [Δ11]
    Aktivni         BIT NOT NULL CONSTRAINT DF_Box_Aktivni   DEFAULT (1),        -- [Δ11]
    CONSTRAINT CK_Box_KodBoxu CHECK (KodBoxu COLLATE Latin1_General_BIN LIKE 'B%[0-9][0-9][0-9]'
                                     AND KodBoxu COLLATE Latin1_General_BIN NOT LIKE '%[^0-9A-Z]%'),
    CONSTRAINT CK_Box_FullBoxKlic CHECK (FullBoxKlic COLLATE Latin1_General_BIN NOT LIKE '%[^0-9A-Z-]%')
);

CREATE TABLE dbo.VnitrniPoziceBoxu (
    VnitrniPoziceID  INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_VnitrniPoziceBoxu PRIMARY KEY,
    BoxID            INT NOT NULL CONSTRAINT FK_VnitrniPozice_Box REFERENCES dbo.Box (BoxID),
    SablonaCleneniID INT NOT NULL CONSTRAINT FK_VnitrniPozice_SablonaCleneni REFERENCES dbo.SablonaCleneni (SablonaCleneniID),  -- [Δ5]
    KodPozice        VARCHAR(20) NOT NULL,     -- DYN = SablonaCleneni.DynKod (A..R, CH), STAT = StatKod (1..n); barcode = KodBoxu + '-' + KodPozice
    VelikostPoziceID INT NOT NULL CONSTRAINT FK_VnitrniPozice_VelikostPozice REFERENCES dbo.VelikostPozice (VelikostPoziceID),  -- [Δ3]
    DelkaMM          DECIMAL(10,2) NULL,       -- [Δ4] aktuální rozměr variabilní C7 (povinný u V6, kontrola v_KontrolaIntegrity)
    HloubkaMM        DECIMAL(10,2) NULL,
    Blokovany        BIT NOT NULL CONSTRAINT DF_VnitrniPozice_Blokovany DEFAULT (0),  -- [Δ11]
    Aktivni          BIT NOT NULL CONSTRAINT DF_VnitrniPozice_Aktivni   DEFAULT (1),  -- [Δ11]
    CONSTRAINT CK_VnitrniPozice_KodPozice CHECK (
           KodPozice COLLATE Latin1_General_BIN IN ('A','B','C','D','E','F','G','H','CH','I','J','K','L','M','N','O','P','Q','R')
        OR KodPozice COLLATE Latin1_General_BIN LIKE '[1-9]'),
    CONSTRAINT CK_VnitrniPozice_Rozmer CHECK ((DelkaMM IS NULL AND HloubkaMM IS NULL) OR (DelkaMM > 0 AND HloubkaMM > 0))
);


/* =============================================================================
   3. DÍLY, ČÍSELNÍKY A STATICKÉ UMÍSTĚNÍ (kap. 8, 13, 23)
   ============================================================================= */

CREATE TABLE dbo.Material (
    MaterialID      INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Material PRIMARY KEY,
    KodMaterialu    VARCHAR(30) NOT NULL CONSTRAINT UQ_Material_KodMaterialu UNIQUE,   -- [Δ11]
    Aktivni         BIT NOT NULL CONSTRAINT DF_Material_Aktivni DEFAULT (1)
);

CREATE TABLE dbo.TloustkaMaterialu (
    TloustkaID      INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_TloustkaMaterialu PRIMARY KEY,
    TloustkaMM      DECIMAL(5,2) NOT NULL CONSTRAINT UQ_TloustkaMaterialu_TloustkaMM UNIQUE
                                          CONSTRAINT CK_TloustkaMaterialu_TloustkaMM CHECK (TloustkaMM > 0),
    Aktivni         BIT NOT NULL CONSTRAINT DF_TloustkaMaterialu_Aktivni DEFAULT (1)
);

CREATE TABLE dbo.PrvniVyrobniOperace (
    PrvniOperaceID  INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_PrvniVyrobniOperace PRIMARY KEY,
    KodOperace      VARCHAR(20)   NOT NULL CONSTRAINT UQ_PrvniVyrobniOperace_KodOperace UNIQUE,   -- [Δ11]
    NazevOperace    NVARCHAR(100) NOT NULL,
    Aktivni         BIT NOT NULL CONSTRAINT DF_PrvniVyrobniOperace_Aktivni DEFAULT (1),
    CONSTRAINT CK_PrvniVyrobniOperace_Kod CHECK (KodOperace COLLATE Latin1_General_BIN NOT LIKE '%[^0-9A-Z_]%')
);

CREATE TABLE dbo.Dil (
    DilID              INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Dil PRIMARY KEY,
    IdentifikacniCislo VARCHAR(80)    NOT NULL CONSTRAINT UQ_Dil_IdentifikacniCislo UNIQUE,  -- není barcode (kap. 11)
    NazevDilu          NVARCHAR(200)  NULL,
    MaterialID         INT NULL CONSTRAINT FK_Dil_Material     REFERENCES dbo.Material (MaterialID),
    TloustkaID         INT NULL CONSTRAINT FK_Dil_Tloustka     REFERENCES dbo.TloustkaMaterialu (TloustkaID),
    PrvniOperaceID     INT NULL CONSTRAINT FK_Dil_PrvniOperace REFERENCES dbo.PrvniVyrobniOperace (PrvniOperaceID),
    StandardniDavkaKs  INT NULL CONSTRAINT CK_Dil_StandardniDavka CHECK (StandardniDavkaKs > 0),
    VelikostPoziceID   INT NULL CONSTRAINT FK_Dil_VelikostPozice REFERENCES dbo.VelikostPozice (VelikostPoziceID),
    PotrebnaDelkaMM    DECIMAL(10,2)  NULL,    -- [Δ4] jen díl velikosti V6
    PotrebnaHloubkaMM  DECIMAL(10,2)  NULL,
    VaultVykresURL     NVARCHAR(1000) NULL,
    Poznamka           NVARCHAR(500)  NULL,    -- [Δ17] pokyn pro obsluhu (JINÉ INFORMACE z XLSM, 2. 11. 2026)
    Aktivni            BIT NOT NULL CONSTRAINT DF_Dil_Aktivni DEFAULT (1),       -- [Δ11]
    -- bez mezer na krajích a bez dvojitých mezer, aby „CE21RA 10 100194“ nevznikl dvakrát
    CONSTRAINT CK_Dil_IdentifikacniCislo CHECK (IdentifikacniCislo <> ''
        AND DATALENGTH(IdentifikacniCislo) = DATALENGTH(LTRIM(RTRIM(IdentifikacniCislo)))
        AND IdentifikacniCislo NOT LIKE '%  %'),
    CONSTRAINT CK_Dil_PotrebnyRozmer CHECK ((PotrebnaDelkaMM IS NULL AND PotrebnaHloubkaMM IS NULL)
                                            OR (PotrebnaDelkaMM > 0 AND PotrebnaHloubkaMM > 0))
);

CREATE TABLE dbo.StatickeUmisteniDilu (
    StatickeUmisteniID INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_StatickeUmisteniDilu PRIMARY KEY,
    DilID              INT NOT NULL CONSTRAINT FK_StatickeUmisteni_Dil REFERENCES dbo.Dil (DilID),
    VnitrniPoziceID    INT NOT NULL CONSTRAINT FK_StatickeUmisteni_VnitrniPozice REFERENCES dbo.VnitrniPoziceBoxu (VnitrniPoziceID),
    MinimalniPocetKs   INT NOT NULL CONSTRAINT CK_StatickeUmisteni_Min CHECK (MinimalniPocetKs >= 0),
    OptimalniPocetKs   INT NULL,
    MaximalniPocetKs   INT NULL,               -- XLSM maximum nemá, doplní se po migraci
    Aktivni            BIT NOT NULL CONSTRAINT DF_StatickeUmisteni_Aktivni DEFAULT (1),  -- [Δ11]
    CONSTRAINT CK_StatickeUmisteni_Max CHECK (MaximalniPocetKs IS NULL OR MaximalniPocetKs >= MinimalniPocetKs),
    CONSTRAINT CK_StatickeUmisteni_Opt CHECK (OptimalniPocetKs IS NULL
        OR (OptimalniPocetKs >= MinimalniPocetKs AND (MaximalniPocetKs IS NULL OR OptimalniPocetKs <= MaximalniPocetKs)))
);


/* =============================================================================
   4. UŽIVATELÉ, ROLE, OPRÁVNĚNÍ, TERMINÁLY (kap. 19, 23.1 – sloupce přesně podle slovníku)
   ============================================================================= */

CREATE TABLE dbo.Role (
    RoleID          INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Role PRIMARY KEY,
    KodRole         VARCHAR(20)   NOT NULL CONSTRAINT UQ_Role_KodRole UNIQUE,    -- OPER, SKL, MISTR, TECH, ADMIN
    NazevRole       NVARCHAR(100) NOT NULL,
    Popis           NVARCHAR(300) NULL,
    Aktivni         BIT NOT NULL CONSTRAINT DF_Role_Aktivni DEFAULT (1),
    CONSTRAINT CK_Role_KodRole CHECK (KodRole COLLATE Latin1_General_BIN NOT LIKE '%[^0-9A-Z_]%')
);

CREATE TABLE dbo.Opravneni (
    OpravneniID     INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Opravneni PRIMARY KEY,
    KodOpravneni    VARCHAR(50)   NOT NULL CONSTRAINT UQ_Opravneni_KodOpravneni UNIQUE,
    NazevOpravneni  NVARCHAR(120) NOT NULL,
    Popis           NVARCHAR(300) NULL,
    Aktivni         BIT NOT NULL CONSTRAINT DF_Opravneni_Aktivni DEFAULT (1),
    CONSTRAINT CK_Opravneni_KodOpravneni CHECK (KodOpravneni COLLATE Latin1_General_BIN NOT LIKE '%[^0-9A-Z_]%')
);

CREATE TABLE dbo.RoleOpravneni (
    RoleID          INT NOT NULL CONSTRAINT FK_RoleOpravneni_Role      REFERENCES dbo.Role (RoleID),
    OpravneniID     INT NOT NULL CONSTRAINT FK_RoleOpravneni_Opravneni REFERENCES dbo.Opravneni (OpravneniID),
    CONSTRAINT PK_RoleOpravneni PRIMARY KEY (RoleID, OpravneniID)
);

CREATE TABLE dbo.Uzivatel (
    UzivatelID      INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Uzivatel PRIMARY KEY,
    OsobniCislo     VARCHAR(30)   NOT NULL CONSTRAINT UQ_Uzivatel_OsobniCislo UNIQUE,
    Jmeno           NVARCHAR(100) NOT NULL,
    Prijmeni        NVARCHAR(100) NOT NULL,
    RoleID          INT NOT NULL CONSTRAINT FK_Uzivatel_Role REFERENCES dbo.Role (RoleID),
    PinHash         NVARCHAR(255) NULL,        -- jen bezpečný hash, nikdy otevřený PIN
    KodKarty        VARCHAR(100)  NULL,        -- unikátní jen vyplněné hodnoty [Δ12], index v oddílu 8
    Aktivni         BIT NOT NULL CONSTRAINT DF_Uzivatel_Aktivni DEFAULT (1)
);

CREATE TABLE dbo.Terminal (
    TerminalID      INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Terminal PRIMARY KEY,
    KodTerminalu    VARCHAR(50)   NOT NULL CONSTRAINT UQ_Terminal_KodTerminalu UNIQUE,
    NazevTerminalu  NVARCHAR(100) NULL,
    PracovisteID    INT NULL CONSTRAINT FK_Terminal_Pracoviste REFERENCES dbo.Pracoviste (PracovisteID),
    Aktivni         BIT NOT NULL CONSTRAINT DF_Terminal_Aktivni DEFAULT (1)
);


/* =============================================================================
   5. AKTUÁLNÍ STAV, HISTORIE POHYBŮ A UPOZORNĚNÍ (kap. 9, 10, 13, 23, 23.1)
   ============================================================================= */

CREATE TABLE dbo.ObsahPozice (
    ObsahPoziceID   BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ObsahPozice PRIMARY KEY,
    VnitrniPoziceID INT NOT NULL CONSTRAINT FK_ObsahPozice_VnitrniPozice REFERENCES dbo.VnitrniPoziceBoxu (VnitrniPoziceID),
    DilID           INT NOT NULL CONSTRAINT FK_ObsahPozice_Dil REFERENCES dbo.Dil (DilID),
    PocetKs         INT NOT NULL CONSTRAINT CK_ObsahPozice_PocetKs CHECK (PocetKs > 0),   -- při 0 ks se řádek maže (DYN i STAT)
    DatumZmeny      DATETIME2 NOT NULL CONSTRAINT DF_ObsahPozice_DatumZmeny DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT UQ_ObsahPozice_VnitrniPozice UNIQUE (VnitrniPoziceID)
);

CREATE TABLE dbo.TypPohybu (
    TypPohybuID     INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_TypPohybu PRIMARY KEY,
    KodPohybu       VARCHAR(30)   NOT NULL CONSTRAINT UQ_TypPohybu_KodPohybu UNIQUE,
    NazevPohybu     NVARCHAR(100) NOT NULL,
    Aktivni         BIT NOT NULL CONSTRAINT DF_TypPohybu_Aktivni DEFAULT (1),
    CONSTRAINT CK_TypPohybu_KodPohybu CHECK (KodPohybu COLLATE Latin1_General_BIN NOT LIKE '%[^0-9A-Z_-]%')
);

CREATE TABLE dbo.SkladovyPohyb (
    PohybID         BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_SkladovyPohyb PRIMARY KEY,
    DatumCas        DATETIME2 NOT NULL CONSTRAINT DF_SkladovyPohyb_DatumCas DEFAULT (SYSUTCDATETIME()),
    TypPohybuID     INT NOT NULL CONSTRAINT FK_SkladovyPohyb_TypPohybu     REFERENCES dbo.TypPohybu (TypPohybuID),
    DilID           INT NOT NULL CONSTRAINT FK_SkladovyPohyb_Dil           REFERENCES dbo.Dil (DilID),
    VnitrniPoziceID INT NOT NULL CONSTRAINT FK_SkladovyPohyb_VnitrniPozice REFERENCES dbo.VnitrniPoziceBoxu (VnitrniPoziceID),
    Mnozstvi        INT NOT NULL,              -- podepsaná změna (+ příjem, − výdej)
    StavPred        INT NOT NULL,
    StavPo          INT NOT NULL,
    UzivatelID      INT NOT NULL CONSTRAINT FK_SkladovyPohyb_Uzivatel REFERENCES dbo.Uzivatel (UzivatelID),
    TerminalID      INT NULL     CONSTRAINT FK_SkladovyPohyb_Terminal REFERENCES dbo.Terminal (TerminalID),
    TransakceID     UNIQUEIDENTIFIER NULL,     -- G2: NOT NULL FK na hlavičku transakce
    Poznamka        NVARCHAR(500) NULL,
    CONSTRAINT CK_SkladovyPohyb_Mnozstvi CHECK (Mnozstvi <> 0),                                          -- [Δ13]
    CONSTRAINT CK_SkladovyPohyb_Stavy    CHECK (StavPred >= 0 AND StavPo >= 0 AND StavPo = StavPred + Mnozstvi)  -- [Δ13]
);

CREATE TABLE dbo.UpozorneniZasoby (
    UpozorneniID       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_UpozorneniZasoby PRIMARY KEY,
    StatickeUmisteniID INT NOT NULL CONSTRAINT FK_UpozorneniZasoby_StatickeUmisteni REFERENCES dbo.StatickeUmisteniDilu (StatickeUmisteniID),
    DatumVzniku        DATETIME2 NOT NULL CONSTRAINT DF_UpozorneniZasoby_DatumVzniku DEFAULT (SYSUTCDATETIME()),
    AktualniPocetKs    INT NOT NULL CONSTRAINT CK_UpozorneniZasoby_Aktualni CHECK (AktualniPocetKs >= 0),
    MinimalniPocetKs   INT NOT NULL CONSTRAINT CK_UpozorneniZasoby_Minimum  CHECK (MinimalniPocetKs >= 0),   -- snapshot minima
    TypStavu           VARCHAR(20) NOT NULL CONSTRAINT CK_UpozorneniZasoby_TypStavu
                           CHECK (TypStavu COLLATE Latin1_General_BIN IN ('NA_MINIMU', 'POD_MINIMEM', 'VYCERPANO')),   -- [Δ8]
    StavUpozorneni     VARCHAR(20) NOT NULL CONSTRAINT DF_UpozorneniZasoby_Stav DEFAULT ('OTEVRENE')
                           CONSTRAINT CK_UpozorneniZasoby_Stav
                           CHECK (StavUpozorneni COLLATE Latin1_General_BIN IN ('OTEVRENE', 'UZAVRENE')),          -- [Δ8]
    DatumUzavreni      DATETIME2 NULL,
    UzavrelUzivatelID  INT NULL CONSTRAINT FK_UpozorneniZasoby_Uzivatel REFERENCES dbo.Uzivatel (UzivatelID),
    Poznamka           NVARCHAR(500) NULL,
    CONSTRAINT CK_UpozorneniZasoby_Uzavreni CHECK ((StavUpozorneni = 'OTEVRENE' AND DatumUzavreni IS NULL)
                                                OR (StavUpozorneni = 'UZAVRENE' AND DatumUzavreni IS NOT NULL))
);


/* =============================================================================
   6. INVENTURA (kap. 18, 23.1)
   ============================================================================= */

CREATE TABLE dbo.Inventura (
    InventuraID        BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Inventura PRIMARY KEY,
    TypRozsahu         VARCHAR(20) NOT NULL CONSTRAINT CK_Inventura_TypRozsahu
                           CHECK (TypRozsahu COLLATE Latin1_General_BIN IN ('FULL', 'PRAC', 'REGAL', 'UROVEN', 'BOX', 'POZICE')),
    PracovisteID       INT NULL CONSTRAINT FK_Inventura_Pracoviste    REFERENCES dbo.Pracoviste (PracovisteID),
    RegalID            INT NULL CONSTRAINT FK_Inventura_Regal         REFERENCES dbo.Regal (RegalID),
    UrovenID           INT NULL CONSTRAINT FK_Inventura_Uroven        REFERENCES dbo.Uroven (UrovenID),
    BoxID              INT NULL CONSTRAINT FK_Inventura_Box           REFERENCES dbo.Box (BoxID),
    VnitrniPoziceID    INT NULL CONSTRAINT FK_Inventura_VnitrniPozice REFERENCES dbo.VnitrniPoziceBoxu (VnitrniPoziceID),
    StavInventury      VARCHAR(20) NOT NULL CONSTRAINT CK_Inventura_StavInventury
                           CHECK (StavInventury COLLATE Latin1_General_BIN IN ('ROZPRACOVANA', 'DOKONCENA', 'ZRUSENA')),
    SlepaInventura     BIT NOT NULL CONSTRAINT DF_Inventura_SlepaInventura DEFAULT (1),
    DatumZahajeni      DATETIME2 NOT NULL CONSTRAINT DF_Inventura_DatumZahajeni DEFAULT (SYSUTCDATETIME()),
    DatumDokonceni     DATETIME2 NULL,
    ZalozilUzivatelID  INT NOT NULL CONSTRAINT FK_Inventura_Zalozil  REFERENCES dbo.Uzivatel (UzivatelID),
    DokoncilUzivatelID INT NULL     CONSTRAINT FK_Inventura_Dokoncil REFERENCES dbo.Uzivatel (UzivatelID),
    Poznamka           NVARCHAR(500) NULL,
    -- [Δ14] vyplněna je právě ta vazba, kterou určuje TypRozsahu
    CONSTRAINT CK_Inventura_Rozsah CHECK (
           (TypRozsahu = 'FULL'   AND PracovisteID IS NULL     AND RegalID IS NULL     AND UrovenID IS NULL     AND BoxID IS NULL     AND VnitrniPoziceID IS NULL)
        OR (TypRozsahu = 'PRAC'   AND PracovisteID IS NOT NULL AND RegalID IS NULL     AND UrovenID IS NULL     AND BoxID IS NULL     AND VnitrniPoziceID IS NULL)
        OR (TypRozsahu = 'REGAL'  AND PracovisteID IS NULL     AND RegalID IS NOT NULL AND UrovenID IS NULL     AND BoxID IS NULL     AND VnitrniPoziceID IS NULL)
        OR (TypRozsahu = 'UROVEN' AND PracovisteID IS NULL     AND RegalID IS NULL     AND UrovenID IS NOT NULL AND BoxID IS NULL     AND VnitrniPoziceID IS NULL)
        OR (TypRozsahu = 'BOX'    AND PracovisteID IS NULL     AND RegalID IS NULL     AND UrovenID IS NULL     AND BoxID IS NOT NULL AND VnitrniPoziceID IS NULL)
        OR (TypRozsahu = 'POZICE' AND PracovisteID IS NULL     AND RegalID IS NULL     AND UrovenID IS NULL     AND BoxID IS NULL     AND VnitrniPoziceID IS NOT NULL)),
    -- [Δ14] dokončená inventura má čas i autora dokončení
    CONSTRAINT CK_Inventura_Dokonceni CHECK (StavInventury <> 'DOKONCENA'
        OR (DatumDokonceni IS NOT NULL AND DokoncilUzivatelID IS NOT NULL))
);

CREATE TABLE dbo.InventuraPolozka (
    InventuraPolozkaID BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_InventuraPolozka PRIMARY KEY,
    InventuraID        BIGINT NOT NULL CONSTRAINT FK_InventuraPolozka_Inventura     REFERENCES dbo.Inventura (InventuraID),
    VnitrniPoziceID    INT NOT NULL    CONSTRAINT FK_InventuraPolozka_VnitrniPozice REFERENCES dbo.VnitrniPoziceBoxu (VnitrniPoziceID),
    OcekavanyDilID     INT NULL        CONSTRAINT FK_InventuraPolozka_OcekavanyDil  REFERENCES dbo.Dil (DilID),
    OcekavanyPocetKs   INT NOT NULL    CONSTRAINT CK_InventuraPolozka_Ocekavany CHECK (OcekavanyPocetKs >= 0),
    SkutecnyDilID      INT NULL        CONSTRAINT FK_InventuraPolozka_SkutecnyDil   REFERENCES dbo.Dil (DilID),
    SkutecnyPocetKs    INT NULL        CONSTRAINT CK_InventuraPolozka_Skutecny  CHECK (SkutecnyPocetKs >= 0),
    RozdilKs           INT NULL,               -- skutečný − očekávaný počet
    Vyhodnoceni        VARCHAR(30) NULL CONSTRAINT CK_InventuraPolozka_Vyhodnoceni
                           CHECK (Vyhodnoceni COLLATE Latin1_General_BIN IN ('SHODA', 'ROZDIL', 'JINY_DIL')),  -- [Δ8]
    DatumKontroly      DATETIME2 NULL,
    UzivatelID         INT NULL CONSTRAINT FK_InventuraPolozka_Uzivatel REFERENCES dbo.Uzivatel (UzivatelID),
    CONSTRAINT UQ_InventuraPolozka_Inventura_Pozice UNIQUE (InventuraID, VnitrniPoziceID)
);


/* =============================================================================
   7. AUDIT ZMĚN KMENOVÝCH DAT (kap. 25, 23.1 – sloupce přesně podle slovníku)
   ============================================================================= */

CREATE TABLE dbo.AuditZmen (
    AuditID         BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_AuditZmen PRIMARY KEY,
    DatumCas        DATETIME2 NOT NULL CONSTRAINT DF_AuditZmen_DatumCas DEFAULT (SYSUTCDATETIME()),
    UzivatelID      INT NOT NULL CONSTRAINT FK_AuditZmen_Uzivatel REFERENCES dbo.Uzivatel (UzivatelID),
    TypObjektu      VARCHAR(50)  NOT NULL,     -- DIL, BOX, STAT_UMISTENI, PRACOVISTE … (ASCII, Q-25)
    ObjektID        BIGINT       NOT NULL,     -- polymorfní odkaz podle TypObjektu
    Pole            VARCHAR(100) NOT NULL,     -- která vlastnost se změnila
    StaraHodnota    NVARCHAR(MAX) NULL,
    NovaHodnota     NVARCHAR(MAX) NULL,
    Poznamka        NVARCHAR(500) NULL,        -- důvod změny
    CONSTRAINT CK_AuditZmen_TypObjektu CHECK (TypObjektu <> '' AND TypObjektu COLLATE Latin1_General_BIN NOT LIKE '%[^0-9A-Z_]%')  -- [Δ8]
);
GO


/* =============================================================================
   8. INDEXY (kap. 24 + rozhodnutí G1)
   ============================================================================= */

-- Struktura skladu
CREATE UNIQUE INDEX UX_Pozice_Uroven_Poradi_Aktivni  ON dbo.Pozice (UrovenID, Poradi) WHERE Aktivni = 1;            -- [Δ2]
CREATE        INDEX IX_Pozice_UrovenID               ON dbo.Pozice (UrovenID);
CREATE UNIQUE INDEX UX_Box_Pozice_Aktivni            ON dbo.Box (PoziceID) WHERE Aktivni = 1;                       -- [Δ1]
CREATE        INDEX IX_Box_PoziceID                  ON dbo.Box (PoziceID);
CREATE        INDEX IX_Box_TypBoxuID                 ON dbo.Box (TypBoxuID);
CREATE        INDEX IX_Box_CleneniBoxuID             ON dbo.Box (CleneniBoxuID);
CREATE UNIQUE INDEX UX_VnitrniPozice_Box_Kod_Aktivni ON dbo.VnitrniPoziceBoxu (BoxID, KodPozice) WHERE Aktivni = 1;  -- [Δ10]
CREATE        INDEX IX_VnitrniPozice_BoxID           ON dbo.VnitrniPoziceBoxu (BoxID);
CREATE        INDEX IX_VnitrniPozice_SablonaCleneni  ON dbo.VnitrniPoziceBoxu (SablonaCleneniID);
CREATE        INDEX IX_VnitrniPozice_Velikost        ON dbo.VnitrniPoziceBoxu (VelikostPoziceID)
                                                     INCLUDE (BoxID, Blokovany) WHERE Aktivni = 1;                      -- hledání kandidátů

-- Díly a statické umístění
CREATE        INDEX IX_Dil_Filtr                     ON dbo.Dil (PrvniOperaceID, MaterialID, TloustkaID) INCLUDE (IdentifikacniCislo) WHERE Aktivni = 1;  -- přehled laseru
CREATE        INDEX IX_Dil_MaterialID                ON dbo.Dil (MaterialID);
CREATE        INDEX IX_Dil_TloustkaID                ON dbo.Dil (TloustkaID);
CREATE        INDEX IX_Dil_VelikostPoziceID          ON dbo.Dil (VelikostPoziceID);
CREATE UNIQUE INDEX UX_StatickeUmisteni_Pozice_Aktivni ON dbo.StatickeUmisteniDilu (VnitrniPoziceID) WHERE Aktivni = 1;  -- [Δ15] kap. 13
CREATE UNIQUE INDEX UX_StatickeUmisteni_Dil_Aktivni  ON dbo.StatickeUmisteniDilu (DilID) WHERE Aktivni = 1;          -- [Δ7] Q-12
CREATE        INDEX IX_StatickeUmisteni_DilID        ON dbo.StatickeUmisteniDilu (DilID);
CREATE        INDEX IX_StatickeUmisteni_VnitrniPozice ON dbo.StatickeUmisteniDilu (VnitrniPoziceID);

-- Identita
CREATE UNIQUE INDEX UX_Uzivatel_KodKarty             ON dbo.Uzivatel (KodKarty) WHERE KodKarty IS NOT NULL;            -- [Δ12]
CREATE        INDEX IX_Uzivatel_RoleID               ON dbo.Uzivatel (RoleID);
CREATE        INDEX IX_RoleOpravneni_OpravneniID     ON dbo.RoleOpravneni (OpravneniID);

-- Stav, historie, upozornění
CREATE        INDEX IX_ObsahPozice_DilID             ON dbo.ObsahPozice (DilID) INCLUDE (PocetKs);                   -- karta dílu
CREATE        INDEX IX_SkladovyPohyb_Pozice          ON dbo.SkladovyPohyb (VnitrniPoziceID, PohybID);
CREATE        INDEX IX_SkladovyPohyb_Dil_Datum       ON dbo.SkladovyPohyb (DilID, DatumCas);
CREATE        INDEX IX_SkladovyPohyb_DatumCas        ON dbo.SkladovyPohyb (DatumCas);
CREATE        INDEX IX_SkladovyPohyb_Uzivatel_Datum  ON dbo.SkladovyPohyb (UzivatelID, DatumCas);
CREATE        INDEX IX_SkladovyPohyb_TransakceID     ON dbo.SkladovyPohyb (TransakceID) WHERE TransakceID IS NOT NULL;
CREATE UNIQUE INDEX UX_UpozorneniZasoby_Otevrene     ON dbo.UpozorneniZasoby (StatickeUmisteniID) WHERE StavUpozorneni = 'OTEVRENE';  -- 1 otevřené na místo
CREATE        INDEX IX_UpozorneniZasoby_StatickeUmisteni ON dbo.UpozorneniZasoby (StatickeUmisteniID);

-- Inventura a audit
CREATE        INDEX IX_InventuraPolozka_VnitrniPozice ON dbo.InventuraPolozka (VnitrniPoziceID);
CREATE        INDEX IX_AuditZmen_Objekt              ON dbo.AuditZmen (TypObjektu, ObjektID, DatumCas);
GO


/* =============================================================================
   9. SEED – PŘÍLOHA A A ŠABLONA ČLENĚNÍ (technické kódy ASCII, Q-25)
   ============================================================================= */

INSERT INTO dbo.Firma (KodFirmy, NazevFirmy)
VALUES ('HOUFEK', N'HOUFEK a.s.');

INSERT INTO dbo.Pracoviste (FirmaID, KodPracoviste, NazevPracoviste)
SELECT f.FirmaID, v.Kod, v.Nazev
FROM dbo.Firma AS f
CROSS JOIN (VALUES
    (1, 'PLE', N'Plechotváření'),
    (2, '1SV', N'Horní svařovna'),
    (3, '2SV', N'Spodní svařovna'),
    (4, '1MO', N'Montáž konvenčních strojů'),
    (5, '2MO', N'Montáž CNC strojů'),
    (6, 'OBR', N'Obrobna'),
    (7, '1LA', N'Horní lakovna'),
    (8, '2LA', N'Spodní lakovna')
) AS v (Poradi, Kod, Nazev)
WHERE f.KodFirmy = 'HOUFEK'
ORDER BY v.Poradi;

INSERT INTO dbo.TypBoxu (KodTypu, NazevTypu)
VALUES ('STAT', N'Statický'),
       ('DYN',  N'Dynamický');

INSERT INTO dbo.CleneniBoxu (KodCleneni, PocetPozic)
VALUES ('C1', 1), ('C2', 2), ('C3', 3), ('C4', 4), ('C5', 2), ('C6', 6), ('C7', 1);

-- Poradi = prozatímní pořadí podle kódu; po dodání rozměrů se přepočte podle PlochaMM2 (Q-29).
INSERT INTO dbo.VelikostPozice (KodVelikosti, Nazev, Poradi)
VALUES ('V1', N'Velikost 1', 1),
       ('V2', N'Velikost 2', 2),
       ('V3', N'Velikost 3', 3),
       ('V4', N'Velikost 4', 4),
       ('V5', N'Velikost 5', 5),
       ('V6', N'Velikost 6 – variabilní prostor C7', 6);

-- Mapování DYN ↔ STAT podle rozhodnutí Q-06 (k ověření proti jednomu fyzickému boxu).
-- Geometrie = rovnoměrné dělení podle obrázků v kap. 7.1 (k ověření, A-08).
INSERT INTO dbo.SablonaCleneni
       (CleneniBoxuID, DynKod, StatKod, Poradi, Rada, Sloupec, VelikostPoziceID, RelX, RelY, RelSirka, RelHloubka)
SELECT c.CleneniBoxuID, s.DynKod, s.StatKod, s.Poradi, s.Rada, s.Sloupec, v.VelikostPoziceID,
       s.RelX, s.RelY, s.RelSirka, s.RelHloubka
FROM (VALUES
    -- konf. DYN   STAT  poř. řada sl.  vel.   RelX    RelY    šířka   hloubka
    ('C1', 'A',  '1', 1, 1, 1, 'V1', 0.0000, 0.0000, 1.0000, 1.0000),
    ('C2', 'B',  '2', 1, 2, 1, 'V2', 0.0000, 0.5000, 1.0000, 0.5000),
    ('C2', 'C',  '1', 2, 1, 1, 'V2', 0.0000, 0.0000, 1.0000, 0.5000),
    ('C3', 'D',  '3', 1, 2, 1, 'V2', 0.0000, 0.5000, 1.0000, 0.5000),
    ('C3', 'E',  '1', 2, 1, 1, 'V3', 0.0000, 0.0000, 0.5000, 0.5000),
    ('C3', 'F',  '2', 3, 1, 2, 'V3', 0.5000, 0.0000, 0.5000, 0.5000),
    ('C4', 'G',  '4', 1, 2, 2, 'V3', 0.5000, 0.5000, 0.5000, 0.5000),
    ('C4', 'H',  '3', 2, 2, 1, 'V3', 0.0000, 0.5000, 0.5000, 0.5000),
    ('C4', 'CH', '1', 3, 1, 1, 'V3', 0.0000, 0.0000, 0.5000, 0.5000),
    ('C4', 'I',  '2', 4, 1, 2, 'V3', 0.5000, 0.0000, 0.5000, 0.5000),
    ('C5', 'J',  '2', 1, 2, 1, 'V4', 0.0000, 0.5000, 1.0000, 0.5000),
    ('C5', 'K',  '1', 2, 1, 1, 'V4', 0.0000, 0.0000, 1.0000, 0.5000),
    ('C6', 'L',  '6', 1, 2, 3, 'V5', 0.6667, 0.5000, 0.3333, 0.5000),
    ('C6', 'M',  '5', 2, 2, 2, 'V5', 0.3333, 0.5000, 0.3334, 0.5000),
    ('C6', 'N',  '4', 3, 2, 1, 'V5', 0.0000, 0.5000, 0.3333, 0.5000),
    ('C6', 'O',  '1', 4, 1, 1, 'V5', 0.0000, 0.0000, 0.3333, 0.5000),
    ('C6', 'P',  '2', 5, 1, 2, 'V5', 0.3333, 0.0000, 0.3334, 0.5000),
    ('C6', 'Q',  '3', 6, 1, 3, 'V5', 0.6667, 0.0000, 0.3333, 0.5000),
    ('C7', 'R',  '1', 1, 1, 1, 'V6', 0.0000, 0.0000, 1.0000, 1.0000)
) AS s (KodCleneni, DynKod, StatKod, Poradi, Rada, Sloupec, KodVelikosti, RelX, RelY, RelSirka, RelHloubka)
JOIN dbo.CleneniBoxu    AS c ON c.KodCleneni   = s.KodCleneni
JOIN dbo.VelikostPozice AS v ON v.KodVelikosti = s.KodVelikosti;

INSERT INTO dbo.Material (KodMaterialu)
VALUES ('S235'), ('S355'), ('JRG2C'), ('POZINK'), ('1.4301'), ('ALMG3');   -- seznam bude ještě upraven (kap. 8.2)

INSERT INTO dbo.TloustkaMaterialu (TloustkaMM)
VALUES (1.00), (1.50), (2.00), (2.50), (3.00), (4.00), (5.00), (6.00), (8.00), (10.00),
       (12.00), (15.00), (20.00), (25.00), (30.00), (35.00), (40.00), (50.00), (60.00);

INSERT INTO dbo.PrvniVyrobniOperace (KodOperace, NazevOperace)
VALUES ('LASER',   N'Laser'),
       ('AUTOGEN', N'Autogen'),
       ('PILA',    N'Pila'),
       ('NAKUP',   N'Nákup');                                                -- seznam bude ještě upraven (kap. 8.2)

INSERT INTO dbo.TypPohybu (KodPohybu, NazevPohybu)
VALUES ('PRIJEM',     N'Příjem'),
       ('VYDEJ',      N'Výdej'),
       ('PRESUN-OUT', N'Přesun – odchozí'),
       ('PRESUN-IN',  N'Přesun – příchozí'),
       ('INVENTURA',  N'Inventura'),
       ('KOREKCE',    N'Korekce'),
       ('POCAT-STAV', N'Počáteční stav');

INSERT INTO dbo.Role (KodRole, NazevRole, Popis)
VALUES ('OPER',  N'Operátor',      N'Čtení, standardní příjem a výdej podle přidělených oprávnění.'),
       ('SKL',   N'Skladník',      N'Skladové operace a inventura.'),
       ('MISTR', N'Mistr',         N'Rozšířený dohled a provozní přehledy.'),
       ('TECH',  N'Technolog',     N'Kmenová data související s technologií, min/max dle kompetence.'),
       ('ADMIN', N'Administrátor', N'Struktura skladu, uživatelé, číselníky, systémová administrace.');

INSERT INTO dbo.Opravneni (KodOpravneni, NazevOpravneni)
VALUES ('DIL_CIST',      N'Čtení dílů a skladu'),
       ('SKLAD_PRIJEM',  N'Příjem'),
       ('SKLAD_VYDEJ',   N'Výdej'),
       ('SKLAD_PRESUN',  N'Přesun'),
       ('INVENTURA',     N'Inventura'),
       ('KOREKCE',       N'Korekce stavu přes řízenou operaci'),
       ('BOX_EDIT',      N'Správa struktury skladu a boxů'),
       ('UZIVATEL_EDIT', N'Správa uživatelů');

/* Přiřazení oprávnění rolím zatím NENÍ rozhodnuto (brána G4).
   Návrh ze sekce 9.9 analýzy – po schválení odkomentovat:

INSERT INTO dbo.RoleOpravneni (RoleID, OpravneniID)
SELECT r.RoleID, o.OpravneniID
FROM (VALUES
    ('OPER', 'DIL_CIST'), ('OPER', 'SKLAD_PRIJEM'), ('OPER', 'SKLAD_VYDEJ'),
    ('SKL', 'DIL_CIST'), ('SKL', 'SKLAD_PRIJEM'), ('SKL', 'SKLAD_VYDEJ'), ('SKL', 'SKLAD_PRESUN'), ('SKL', 'INVENTURA'),
    ('MISTR', 'DIL_CIST'), ('MISTR', 'SKLAD_PRIJEM'), ('MISTR', 'SKLAD_VYDEJ'), ('MISTR', 'SKLAD_PRESUN'),
    ('MISTR', 'INVENTURA'), ('MISTR', 'KOREKCE'),
    ('TECH', 'DIL_CIST'),
    ('ADMIN', 'DIL_CIST'), ('ADMIN', 'SKLAD_PRIJEM'), ('ADMIN', 'SKLAD_VYDEJ'), ('ADMIN', 'SKLAD_PRESUN'),
    ('ADMIN', 'INVENTURA'), ('ADMIN', 'KOREKCE'), ('ADMIN', 'BOX_EDIT'), ('ADMIN', 'UZIVATEL_EDIT')
) AS m (KodRole, KodOpravneni)
JOIN dbo.Role      AS r ON r.KodRole      = m.KodRole
JOIN dbo.Opravneni AS o ON o.KodOpravneni = m.KodOpravneni;
*/
GO


/* =============================================================================
   10. KONTROLA INTEGRITY [Δ9]
   Pravidla, která nejde vynutit omezením (vazba přes více tabulek).
   Spouštět nočně a z administrace: SELECT * FROM dbo.v_KontrolaIntegrity;
   Prázdný výsledek = v pořádku. Poslední kontrola čte celou historii pohybů.
   ============================================================================= */

CREATE VIEW dbo.v_KontrolaIntegrity
AS
/* N-02, Q-04: aktivní Pozice bez aktivního Boxu */
SELECT CAST('POZICE_BEZ_BOXU' AS VARCHAR(40))  AS Kontrola,
       CAST('CHYBA' AS VARCHAR(12))            AS Zavaznost,
       CAST(p.PoziceID AS BIGINT)              AS ObjektID,
       CAST(CONCAT(N'Pozice ', p.KodPozice, N' (UrovenID ', p.UrovenID, N') nemá aktivní box') AS NVARCHAR(400)) AS Popis
FROM dbo.Pozice AS p
WHERE p.Aktivni = 1
  AND NOT EXISTS (SELECT 1 FROM dbo.Box AS b WHERE b.PoziceID = p.PoziceID AND b.Aktivni = 1)

UNION ALL
/* aktivní box na neaktivní Pozici */
SELECT 'BOX_NA_NEAKTIVNI_POZICI', 'CHYBA', b.BoxID,
       CONCAT(N'Box ', b.KodBoxu, N' stojí na neaktivní pozici ', b.PoziceID)
FROM dbo.Box AS b
JOIN dbo.Pozice AS p ON p.PoziceID = b.PoziceID
WHERE b.Aktivni = 1 AND p.Aktivni = 0

UNION ALL
/* řada kódu neodpovídá typu boxu (BSTATnnn jen pro STAT) */
SELECT 'KOD_BOXU_NESEDI_S_TYPEM', 'CHYBA', b.BoxID,
       CONCAT(N'Box ', b.KodBoxu, N' má typ ', t.KodTypu)
FROM dbo.Box AS b
JOIN dbo.TypBoxu AS t ON t.TypBoxuID = b.TypBoxuID
WHERE b.Aktivni = 1
  AND (   (t.KodTypu = 'STAT' AND b.KodBoxu COLLATE Latin1_General_BIN NOT LIKE 'BSTAT[0-9][0-9][0-9]')
       OR (t.KodTypu = 'DYN'  AND b.KodBoxu COLLATE Latin1_General_BIN LIKE 'BSTAT%'))

UNION ALL
/* Q-30: DYN box stojí na regálu jiného pracoviště, než nese jeho kód */
SELECT 'DYN_BOX_MIMO_PRACOVISTE', 'CHYBA', b.BoxID,
       CONCAT(N'Box ', b.KodBoxu, N' stojí na pracovišti ', pr.KodPracoviste)
FROM dbo.Box AS b
JOIN dbo.TypBoxu    AS t  ON t.TypBoxuID     = b.TypBoxuID
JOIN dbo.Pozice     AS p  ON p.PoziceID      = b.PoziceID
JOIN dbo.Uroven     AS u  ON u.UrovenID      = p.UrovenID
JOIN dbo.Regal      AS r  ON r.RegalID       = u.RegalID
JOIN dbo.Pracoviste AS pr ON pr.PracovisteID = r.PracovisteID
WHERE b.Aktivni = 1 AND t.KodTypu = 'DYN'
  AND b.KodBoxu <> CONCAT('B', pr.KodPracoviste, RIGHT(b.KodBoxu, 3))

UNION ALL
/* Q-03: uložený FullBoxKlic neodpovídá aktuální adrese boxu */
SELECT 'FULLBOXKLIC_NESEDI', 'CHYBA', b.BoxID,
       CONCAT(N'Uloženo ', b.FullBoxKlic, N', adresa je ', a.Adresa)
FROM dbo.Box AS b
JOIN dbo.Pozice     AS p  ON p.PoziceID      = b.PoziceID
JOIN dbo.Uroven     AS u  ON u.UrovenID      = p.UrovenID
JOIN dbo.Regal      AS r  ON r.RegalID       = u.RegalID
JOIN dbo.Pracoviste AS pr ON pr.PracovisteID = r.PracovisteID
JOIN dbo.Firma      AS f  ON f.FirmaID       = pr.FirmaID
CROSS APPLY (SELECT CONCAT(f.KodFirmy, '-', pr.KodPracoviste, '-', r.KodRegalu, '-', u.KodUrovne, '-', b.KodBoxu) AS Adresa) AS a
WHERE b.Aktivni = 1 AND b.FullBoxKlic <> a.Adresa

UNION ALL
/* počet aktivních vnitřních pozic neodpovídá konfiguraci boxu */
SELECT 'POCET_POZIC_NESEDI', 'CHYBA', b.BoxID,
       CONCAT(N'Box ', b.KodBoxu, N' (', c.KodCleneni, N') má ', x.Pocet, N' aktivních pozic místo ', c.PocetPozic)
FROM dbo.Box AS b
JOIN dbo.CleneniBoxu AS c ON c.CleneniBoxuID = b.CleneniBoxuID
CROSS APPLY (SELECT COUNT(*) AS Pocet
             FROM dbo.VnitrniPoziceBoxu AS v
             WHERE v.BoxID = b.BoxID AND v.Aktivni = 1) AS x
WHERE b.Aktivni = 1 AND x.Pocet <> c.PocetPozic

UNION ALL
/* Q-05, Q-06: vnitřní pozice neodpovídá šabloně (konfigurace, kód nebo velikost) */
SELECT 'POZICE_NESEDI_SE_SABLONOU', 'CHYBA', v.VnitrniPoziceID,
       CONCAT(N'Pozice ', b.KodBoxu, '-', v.KodPozice, N' neodpovídá šabloně ', c.KodCleneni, '/', s.DynKod)
FROM dbo.VnitrniPoziceBoxu AS v
JOIN dbo.Box            AS b ON b.BoxID            = v.BoxID
JOIN dbo.TypBoxu        AS t ON t.TypBoxuID        = b.TypBoxuID
JOIN dbo.SablonaCleneni AS s ON s.SablonaCleneniID = v.SablonaCleneniID
JOIN dbo.CleneniBoxu    AS c ON c.CleneniBoxuID    = s.CleneniBoxuID
WHERE v.Aktivni = 1
  AND (   s.CleneniBoxuID    <> b.CleneniBoxuID
       OR s.VelikostPoziceID <> v.VelikostPoziceID
       OR v.KodPozice COLLATE Latin1_General_BIN <> CASE t.KodTypu WHEN 'DYN' THEN s.DynKod ELSE s.StatKod END)

UNION ALL
/* Q-01: aktuální rozměr C7 – povinný u V6, u ostatních velikostí nemá být */
SELECT 'ROZMER_C7', 'CHYBA', v.VnitrniPoziceID,
       CONCAT(N'Pozice ', b.KodBoxu, '-', v.KodPozice,
              CASE WHEN vp.KodVelikosti = 'V6' THEN N' (V6) nemá aktuální rozměr' ELSE N' není V6, ale má rozměr' END)
FROM dbo.VnitrniPoziceBoxu AS v
JOIN dbo.Box            AS b  ON b.BoxID             = v.BoxID
JOIN dbo.VelikostPozice AS vp ON vp.VelikostPoziceID = v.VelikostPoziceID
WHERE v.Aktivni = 1
  AND (   (vp.KodVelikosti =  'V6' AND v.DelkaMM IS NULL)
       OR (vp.KodVelikosti <> 'V6' AND v.DelkaMM IS NOT NULL))

UNION ALL
/* Q-01: díl V6 bez požadovaného rozměru, nebo rozměr u dílu jiné velikosti */
SELECT 'ROZMER_DILU_V6', 'CHYBA', d.DilID,
       CONCAT(N'Díl ', d.IdentifikacniCislo,
              CASE WHEN vp.KodVelikosti = 'V6' THEN N' (V6) nemá požadovaný rozměr' ELSE N' není V6, ale má požadovaný rozměr' END)
FROM dbo.Dil AS d
JOIN dbo.VelikostPozice AS vp ON vp.VelikostPoziceID = d.VelikostPoziceID
WHERE d.Aktivni = 1
  AND (   (vp.KodVelikosti =  'V6' AND d.PotrebnaDelkaMM IS NULL)
       OR (vp.KodVelikosti <> 'V6' AND d.PotrebnaDelkaMM IS NOT NULL))

UNION ALL
/* STAT přiřazení míří na pozici, která není ve STAT boxu */
SELECT 'STAT_PRIRAZENI_MIMO_STAT_BOX', 'CHYBA', s.StatickeUmisteniID,
       CONCAT(N'Přiřazení dílu ', d.IdentifikacniCislo, N' míří do boxu ', b.KodBoxu)
FROM dbo.StatickeUmisteniDilu AS s
JOIN dbo.Dil               AS d ON d.DilID           = s.DilID
JOIN dbo.VnitrniPoziceBoxu AS v ON v.VnitrniPoziceID = s.VnitrniPoziceID
JOIN dbo.Box               AS b ON b.BoxID           = v.BoxID
JOIN dbo.TypBoxu           AS t ON t.TypBoxuID       = b.TypBoxuID
WHERE s.Aktivni = 1 AND t.KodTypu <> 'STAT'

UNION ALL
/* Q-05: velikost dílu ≠ velikost STAT pozice – smí jen vědomé přepsání se záznamem v AuditZmen */
SELECT 'STAT_VELIKOST_PREPSANA', 'UPOZORNENI', s.StatickeUmisteniID,
       CONCAT(N'Díl ', d.IdentifikacniCislo, N' (', vd.KodVelikosti, N') je na STAT pozici ', b.KodBoxu, '-', v.KodPozice,
              N' (', vv.KodVelikosti, N') – ověřte důvod v auditu')
FROM dbo.StatickeUmisteniDilu AS s
JOIN dbo.Dil               AS d  ON d.DilID             = s.DilID
JOIN dbo.VnitrniPoziceBoxu AS v  ON v.VnitrniPoziceID   = s.VnitrniPoziceID
JOIN dbo.Box               AS b  ON b.BoxID             = v.BoxID
JOIN dbo.VelikostPozice    AS vd ON vd.VelikostPoziceID = d.VelikostPoziceID
JOIN dbo.VelikostPozice    AS vv ON vv.VelikostPoziceID = v.VelikostPoziceID
WHERE s.Aktivni = 1 AND d.VelikostPoziceID <> v.VelikostPoziceID

UNION ALL
/* obsah STAT pozice: jiný díl než přiřazený, nebo pozice bez přiřazení */
SELECT 'STAT_OBSAH_NESEDI', 'CHYBA', o.VnitrniPoziceID,
       CONCAT(N'Pozice ', b.KodBoxu, '-', v.KodPozice, N' obsahuje díl ', d.IdentifikacniCislo,
              CASE WHEN s.DilID IS NULL THEN N' bez aktivního přiřazení' ELSE N', přiřazen je jiný díl' END)
FROM dbo.ObsahPozice AS o
JOIN dbo.VnitrniPoziceBoxu AS v ON v.VnitrniPoziceID = o.VnitrniPoziceID
JOIN dbo.Box               AS b ON b.BoxID           = v.BoxID
JOIN dbo.TypBoxu           AS t ON t.TypBoxuID       = b.TypBoxuID
JOIN dbo.Dil               AS d ON d.DilID           = o.DilID
LEFT JOIN dbo.StatickeUmisteniDilu AS s ON s.VnitrniPoziceID = o.VnitrniPoziceID AND s.Aktivni = 1
WHERE t.KodTypu = 'STAT' AND (s.DilID IS NULL OR s.DilID <> o.DilID)

UNION ALL
/* obsah DYN pozice s dílem jiné velikosti (vzniká jen inventurou, N-05) */
SELECT 'DYN_VELIKOST_NESEDI', 'UPOZORNENI', o.VnitrniPoziceID,
       CONCAT(N'Pozice ', b.KodBoxu, '-', v.KodPozice, N' obsahuje díl ', d.IdentifikacniCislo, N' jiné velikosti – přeskladnit')
FROM dbo.ObsahPozice AS o
JOIN dbo.VnitrniPoziceBoxu AS v ON v.VnitrniPoziceID = o.VnitrniPoziceID
JOIN dbo.Box               AS b ON b.BoxID           = v.BoxID
JOIN dbo.TypBoxu           AS t ON t.TypBoxuID       = b.TypBoxuID
JOIN dbo.Dil               AS d ON d.DilID           = o.DilID
WHERE t.KodTypu = 'DYN' AND d.VelikostPoziceID IS NOT NULL AND d.VelikostPoziceID <> v.VelikostPoziceID

UNION ALL
/* obsah na neaktivní pozici nebo v neaktivním boxu */
SELECT 'OBSAH_NA_NEAKTIVNI_POZICI', 'CHYBA', o.VnitrniPoziceID,
       CONCAT(N'Pozice ', b.KodBoxu, '-', v.KodPozice, N' je neaktivní, ale má obsah ', o.PocetKs, N' ks')
FROM dbo.ObsahPozice AS o
JOIN dbo.VnitrniPoziceBoxu AS v ON v.VnitrniPoziceID = o.VnitrniPoziceID
JOIN dbo.Box               AS b ON b.BoxID           = v.BoxID
WHERE v.Aktivni = 0 OR b.Aktivni = 0

UNION ALL
/* kap. 10: aktuální obsah ≠ součet všech pohybů na pozici (pro každý díl) */
SELECT 'OBSAH_NESEDI_S_HISTORII', 'CHYBA', COALESCE(o.VnitrniPoziceID, h.VnitrniPoziceID),
       CONCAT(N'VnitrniPoziceID ', COALESCE(o.VnitrniPoziceID, h.VnitrniPoziceID),
              N', DilID ', COALESCE(o.DilID, h.DilID),
              N': obsah ', COALESCE(o.PocetKs, 0), N' ks, součet pohybů ', COALESCE(h.Soucet, 0), N' ks')
FROM (SELECT VnitrniPoziceID, DilID, SUM(CAST(Mnozstvi AS BIGINT)) AS Soucet
      FROM dbo.SkladovyPohyb
      GROUP BY VnitrniPoziceID, DilID) AS h
FULL OUTER JOIN dbo.ObsahPozice AS o
       ON o.VnitrniPoziceID = h.VnitrniPoziceID AND o.DilID = h.DilID
WHERE COALESCE(h.Soucet, 0) <> COALESCE(o.PocetKs, 0);
GO


/* =============================================================================
   11. PRÁVA APLIKACE [Δ16]
   Aplikace se připojuje účtem v roli app_sklad. Historie pohybů a audit jsou
   neměnné: DENY má přednost před GRANT na schématu.
   ============================================================================= */

CREATE ROLE app_sklad AUTHORIZATION dbo;
GO
GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON SCHEMA::dbo TO app_sklad;
DENY  UPDATE, DELETE ON OBJECT::dbo.SkladovyPohyb TO app_sklad;
DENY  UPDATE, DELETE ON OBJECT::dbo.AuditZmen     TO app_sklad;
-- Účet aplikace přidá správce databáze, např.:
-- ALTER ROLE app_sklad ADD MEMBER [houfek_app];
GO

SET NOEXEC OFF;
GO

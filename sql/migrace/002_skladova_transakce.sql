/* =============================================================================
   002 – Hlavička skladové transakce a ochrana proti dvojímu odeslání (requestId)
   Vlastník: Platforma (ostrov A). Doplněk D2 z analýzy, sekce 10.3.
   -----------------------------------------------------------------------------
   Každá skladová operace (příjem, výdej, přesun, blokace, dokončení inventury)
   založí jeden řádek. KlientRequestID je UUID z terminálu: druhý požadavek se
   stejným ID nic nezapíše a dostane uložený výsledek (sloupec Vysledek, JSON).
   SkladovyPohyb.TransakceID zůstává zatím NULL-able (import POCAT-STAV a korekce
   mimo HTTP); NOT NULL se zapne po migraci dat.
   ============================================================================= */

SET XACT_ABORT ON;
GO

CREATE TABLE dbo.SkladovaTransakce (
    TransakceID      UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_SkladovaTransakce PRIMARY KEY,
    KlientRequestID  UNIQUEIDENTIFIER NOT NULL CONSTRAINT UQ_SkladovaTransakce_KlientRequestID UNIQUE,
    TypOperace       VARCHAR(40)  NOT NULL,
    UzivatelID       INT NOT NULL CONSTRAINT FK_SkladovaTransakce_Uzivatel REFERENCES dbo.Uzivatel (UzivatelID),
    TerminalID       INT NULL     CONSTRAINT FK_SkladovaTransakce_Terminal REFERENCES dbo.Terminal (TerminalID),
    DatumCas         DATETIME2 NOT NULL CONSTRAINT DF_SkladovaTransakce_DatumCas DEFAULT (SYSUTCDATETIME()),
    Vysledek         NVARCHAR(MAX) NULL,
    CONSTRAINT CK_SkladovaTransakce_TypOperace CHECK (TypOperace <> ''
        AND TypOperace COLLATE Latin1_General_BIN NOT LIKE '%[^0-9A-Z_-]%')
);

CREATE INDEX IX_SkladovaTransakce_DatumCas ON dbo.SkladovaTransakce (DatumCas);

ALTER TABLE dbo.SkladovyPohyb
    ADD CONSTRAINT FK_SkladovyPohyb_SkladovaTransakce
    FOREIGN KEY (TransakceID) REFERENCES dbo.SkladovaTransakce (TransakceID);
GO

/* Nová oprávnění z analýzy (sekce 9.9) a dokumentu Ostrovy – bez nich nenastartuje
   kontrola oprávnění. Přiřazení rolím rozhodne brána G4. */
INSERT INTO dbo.Opravneni (KodOpravneni, NazevOpravneni)
SELECT v.Kod, v.Nazev
FROM (VALUES
    ('BLOKACE',            N'Blokace a odblokování boxu nebo pozice'),
    ('RUCNI_POTVRZENI',    N'Potvrzení cíle bez skenu (jen PC)'),
    ('UPOZORNENI_UZAVRIT', N'Ruční uzavření upozornění zásoby'),
    ('KMEN_EDIT',          N'Správa dílů a číselníků'),
    ('STAT_EDIT',          N'Statická umístění a min/max'),
    ('AUDIT_CIST',         N'Čtení auditu a kontroly integrity')
) AS v (Kod, Nazev)
WHERE NOT EXISTS (SELECT 1 FROM dbo.Opravneni AS o WHERE o.KodOpravneni = v.Kod);
GO

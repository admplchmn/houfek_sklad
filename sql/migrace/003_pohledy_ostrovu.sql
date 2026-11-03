/* =============================================================================
   003 – Publikované pohledy ostrovů (čtecí kontrakt mezi ostrovy, pravidlo P2)
   Vlastník: Platforma (ostrov A), obsah dodali vlastníci ostrovů (pohledy.sql).
   -----------------------------------------------------------------------------
   Pořadí podle závislostí: C (v_Misto, v_VelikostPozice) → D (v_Dil čte
   v_VelikostPozice) → B → E (v_ZasobaDilu čte v_Misto) → Platforma.
   Sloupce pohledů jsou kontrakt: po provedení se jen přidávají (P10), a to novou
   migrací s CREATE OR ALTER VIEW; pohledy.sql ostrova pak drží poslední tvar.
   Shodu tohoto souboru s pohledy.sql a sloupce proti tabulkám hlídá
   tests/test_migrace.py (SQL Server tu není, T-SQL se ověří při prvním upgrade).
   Práva: role app_sklad má SELECT na celé schéma dbo (migrace 001).
   ============================================================================= */

SET XACT_ABORT ON;
GO


/* -----------------------------------------------------------------------------
   Ostrov C – Struktura (app/ostrovy/struktura/pohledy.sql)
   ----------------------------------------------------------------------------- */

CREATE VIEW dbo.v_VelikostPozice
AS
SELECT VelikostPoziceID, KodVelikosti, Nazev, Poradi, PlochaMM2
FROM dbo.VelikostPozice;
GO

CREATE VIEW dbo.v_Misto
AS
SELECT v.VnitrniPoziceID,
       v.KodPozice,
       CONCAT(b.KodBoxu, '-', v.KodPozice)                     AS KodMista,       -- BPLE037-A
       b.BoxID,
       b.KodBoxu,
       t.KodTypu                                               AS TypBoxu,        -- DYN | STAT
       c.KodCleneni,
       vp.KodVelikosti                                         AS Velikost,       -- V1..V6
       vp.Poradi                                               AS PoradiVelikosti,
       v.DelkaMM                                               AS RozmerC7DelkaMM,
       v.HloubkaMM                                             AS RozmerC7HloubkaMM,
       CAST(CASE WHEN b.Blokovany = 1 OR v.Blokovany = 1 THEN 1 ELSE 0 END AS BIT) AS Blokovano,
       s.Poradi                                                AS PoradiVBoxu,
       p.PoziceID,
       p.Poradi                                                AS PoradiBoxu,
       u.UrovenID,
       u.KodUrovne,
       r.RegalID,
       r.KodRegalu,
       pr.PracovisteID,
       pr.KodPracoviste,
       CONCAT(b.FullBoxKlic, '-', v.KodPozice)                 AS Adresa          -- HOUFEK-PLE-R01-U03-BPLE037-A
FROM dbo.VnitrniPoziceBoxu AS v
JOIN dbo.Box            AS b  ON b.BoxID             = v.BoxID
JOIN dbo.TypBoxu        AS t  ON t.TypBoxuID         = b.TypBoxuID
JOIN dbo.CleneniBoxu    AS c  ON c.CleneniBoxuID     = b.CleneniBoxuID
JOIN dbo.VelikostPozice AS vp ON vp.VelikostPoziceID = v.VelikostPoziceID
JOIN dbo.SablonaCleneni AS s  ON s.SablonaCleneniID  = v.SablonaCleneniID
JOIN dbo.Pozice         AS p  ON p.PoziceID          = b.PoziceID
JOIN dbo.Uroven         AS u  ON u.UrovenID          = p.UrovenID
JOIN dbo.Regal          AS r  ON r.RegalID           = u.RegalID
JOIN dbo.Pracoviste     AS pr ON pr.PracovisteID     = r.PracovisteID
WHERE v.Aktivni = 1 AND b.Aktivni = 1;
GO


/* -----------------------------------------------------------------------------
   Ostrov D – Díly (app/ostrovy/dily/pohledy.sql)
   ----------------------------------------------------------------------------- */

CREATE VIEW dbo.v_Dil
AS
SELECT d.DilID,
       d.IdentifikacniCislo,
       d.NazevDilu,
       d.MaterialID,                         -- ID pro filtry ostrova Přehledy (filtry jsou ID, 4.2)
       m.KodMaterialu,
       d.TloustkaID,
       t.TloustkaMM,
       d.PrvniOperaceID,
       o.KodOperace        AS KodPrvniOperace,
       d.StandardniDavkaKs,
       d.VelikostPoziceID,
       vp.KodVelikosti     AS Velikost,
       d.PotrebnaDelkaMM,
       d.PotrebnaHloubkaMM,
       d.VaultVykresURL,
       d.Aktivni
FROM dbo.Dil AS d
LEFT JOIN dbo.Material            AS m  ON m.MaterialID        = d.MaterialID
LEFT JOIN dbo.TloustkaMaterialu   AS t  ON t.TloustkaID        = d.TloustkaID
LEFT JOIN dbo.PrvniVyrobniOperace AS o  ON o.PrvniOperaceID    = d.PrvniOperaceID
LEFT JOIN dbo.v_VelikostPozice    AS vp ON vp.VelikostPoziceID = d.VelikostPoziceID;
GO


/* -----------------------------------------------------------------------------
   Ostrov B – Identita (app/ostrovy/identita/pohledy.sql)
   ----------------------------------------------------------------------------- */

CREATE VIEW dbo.v_Uzivatel
AS
SELECT u.UzivatelID, u.OsobniCislo, CONCAT(u.Jmeno, N' ', u.Prijmeni) AS CeleJmeno, r.KodRole, u.Aktivni
FROM dbo.Uzivatel AS u
JOIN dbo.Role AS r ON r.RoleID = u.RoleID;
GO

CREATE VIEW dbo.v_Terminal
AS
SELECT TerminalID, KodTerminalu, NazevTerminalu, PracovisteID, Aktivni
FROM dbo.Terminal;
GO


/* -----------------------------------------------------------------------------
   Ostrov E – Sklad (app/ostrovy/sklad/pohledy.sql)
   ----------------------------------------------------------------------------- */

CREATE VIEW dbo.v_ObsahPozice
AS
SELECT VnitrniPoziceID, DilID, PocetKs, DatumZmeny
FROM dbo.ObsahPozice;
GO

/* Aktivní statická přiřazení – ostrov C před strukturální změnou boxu ověří, že žádné nemá (Q-27). */
CREATE VIEW dbo.v_StatickeMisto
AS
SELECT StatickeUmisteniID, DilID, VnitrniPoziceID, MinimalniPocetKs, OptimalniPocetKs, MaximalniPocetKs
FROM dbo.StatickeUmisteniDilu
WHERE Aktivni = 1;
GO

CREATE VIEW dbo.v_ZasobaDilu
AS
WITH stat AS (
    SELECT s.DilID, s.StatickeUmisteniID, s.VnitrniPoziceID,
           s.MinimalniPocetKs, s.OptimalniPocetKs, s.MaximalniPocetKs,
           COALESCE(o.PocetKs, 0) AS StatKs
    FROM dbo.StatickeUmisteniDilu AS s
    LEFT JOIN dbo.ObsahPozice AS o ON o.VnitrniPoziceID = s.VnitrniPoziceID AND o.DilID = s.DilID
    WHERE s.Aktivni = 1
), dyn AS (
    SELECT o.DilID, SUM(o.PocetKs) AS DynKs
    FROM dbo.ObsahPozice AS o
    JOIN dbo.v_Misto AS m ON m.VnitrniPoziceID = o.VnitrniPoziceID
    WHERE m.TypBoxu = 'DYN'
    GROUP BY o.DilID
)
SELECT stat.DilID,
       stat.StatickeUmisteniID,
       stat.VnitrniPoziceID,
       stat.StatKs,
       COALESCE(dyn.DynKs, 0)                 AS DynKs,
       stat.StatKs + COALESCE(dyn.DynKs, 0)   AS CelkemKs,
       stat.MinimalniPocetKs,
       stat.OptimalniPocetKs,
       stat.MaximalniPocetKs,
       CAST(CASE WHEN stat.StatKs <= 0                     THEN 'VYCERPANO'
                 WHEN stat.StatKs <  stat.MinimalniPocetKs THEN 'POD_MINIMEM'
                 WHEN stat.StatKs =  stat.MinimalniPocetKs THEN 'NA_MINIMU'
                 ELSE 'OK' END AS VARCHAR(20)) AS StavZasoby
FROM stat
LEFT JOIN dyn ON dyn.DilID = stat.DilID;
GO

CREATE VIEW dbo.v_PohybDetail
AS
SELECT p.PohybID, p.DatumCas, t.KodPohybu AS TypPohybu, p.DilID, p.VnitrniPoziceID,
       p.Mnozstvi, p.StavPred, p.StavPo, p.UzivatelID, p.TerminalID, p.TransakceID, p.Poznamka
FROM dbo.SkladovyPohyb AS p
JOIN dbo.TypPohybu AS t ON t.TypPohybuID = p.TypPohybuID;
GO


/* -----------------------------------------------------------------------------
   Platforma: hlavička skladové transakce pro historii (ostrov G, /transakce/{id})
   Bez KlientRequestID a Vysledek – ty patří jen ochraně proti dvojímu odeslání.
   ----------------------------------------------------------------------------- */

CREATE VIEW dbo.v_SkladovaTransakce
AS
SELECT TransakceID, TypOperace, UzivatelID, TerminalID, DatumCas
FROM dbo.SkladovaTransakce;
GO

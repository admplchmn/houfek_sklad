/* NÁVRH pohledů ostrova E – vlastník doladí ve fázi 0, Platforma zařadí do migrace 003 (P11).
   v_ZasobaDilu čte v_Misto ostrova C (P2), proto vzniká až po něm.
   StavZasoby musí odpovídat rozhrani.stav_zasoby(); shodu hlídá test ostrova E.
   v_PohybDetail obsahuje jen data ostrova E; kódy dílů, míst a jména uživatelů
   si ostrov Přehledy připojí z v_Dil, v_Misto a v_Uzivatel. */

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

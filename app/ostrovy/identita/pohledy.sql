/* NÁVRH pohledů ostrova B – vlastník doladí ve fázi 0, Platforma zařadí do migrace 003 (P11).
   PinHash ani KodKarty se nikdy nepublikují. v_Terminal vrací jen PracovisteID;
   kód pracoviště si spotřebitel připojí z pohledů ostrova C. Sloupce jsou kontrakt (P10). */

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

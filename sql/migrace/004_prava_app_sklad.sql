/* =============================================================================
   004 – Užší práva aplikace: DELETE jen tam, kde se řádek opravdu maže (TD-08, S-10)
   Vlastník: Platforma (ostrov A).
   -----------------------------------------------------------------------------
   Kmenová data a historie se nikdy nemažou, jen deaktivují (Aktivni = 0) – chyba
   v kódu ani útok přes aplikační účet je tedy nesmaže. DELETE potřebují jen:
     ObsahPozice    – pozice s 0 ks nemá řádek (výdej, přesun, korekce; ostrov E)
     RoleOpravneni  – nový seznam oprávnění role nahradí starý (ostrov B)
   SkladovaTransakce je ochrana proti dvojímu odeslání: smazaná hlavička by
   dovolila provést stejný požadavek znovu, proto DENY.
   Další tabulka s mazáním = nová migrace se zdůvodněním (code review).
   ============================================================================= */

SET XACT_ABORT ON;
GO

REVOKE DELETE ON SCHEMA::dbo FROM app_sklad;
GRANT  DELETE ON OBJECT::dbo.ObsahPozice   TO app_sklad;
GRANT  DELETE ON OBJECT::dbo.RoleOpravneni TO app_sklad;
DENY   DELETE ON OBJECT::dbo.SkladovaTransakce TO app_sklad;
GO

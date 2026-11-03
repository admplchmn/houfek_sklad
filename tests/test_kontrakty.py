"""Kontrakty se po zmrazení mění jen přidáním (P10). Snímek: python -m nastroje.kontrakty uloz"""
import copy
import json
import unittest

from nastroje import kontrakty


class TestKontrakty(unittest.TestCase):
    def test_aktualni_stav_je_kompatibilni_se_snimkem(self):
        ulozeny = {s: json.loads((kontrakty.SLOZKA / s).read_text(encoding="utf-8"))
                   for s in ("openapi.json", "rozhrani.json")}
        chyby = kontrakty.porovnej(ulozeny, kontrakty.aktualni())
        self.assertEqual(chyby, [], "\n".join(chyby))

    def test_kontrola_odhali_odebrani(self):
        novy = kontrakty.aktualni()
        upraveny = copy.deepcopy(novy)
        del upraveny["rozhrani.json"]["struktura"]["funkce"]["najdi_vnitrni_pozici"]
        upraveny["rozhrani.json"]["sklad"]["dto"]["PohybInfo"].remove("stav_po_ks")
        upraveny["openapi.json"]["paths"].pop("/api/system/zdravi")
        chyby = kontrakty.porovnej(novy, upraveny)
        self.assertEqual(len(chyby), 3, chyby)

    def test_kontrola_odhali_nove_povinne_vstupy(self):
        novy = kontrakty.aktualni()
        upraveny = copy.deepcopy(novy)
        audit = upraveny["openapi.json"]["paths"]["/api/system/audit"]["get"]
        audit["parameters"].append({"name": "sklad", "in": "query", "required": True, "schema": {"type": "string"}})
        vstup = upraveny["openapi.json"]["components"]["schemas"]["VyvojovePrihlaseniVstup"]
        vstup["required"] = [*vstup.get("required", []), "kodRole"]
        chyby = kontrakty.porovnej(novy, upraveny)
        self.assertEqual(sorted(chyby), sorted([
            "HTTP: GET /api/system/audit: nový povinný parametr sklad",
            "HTTP: vstup VyvojovePrihlaseniVstup má nové povinné pole kodRole",
        ]))

    def test_pridani_nepovinneho_je_v_poradku(self):
        novy = kontrakty.aktualni()
        upraveny = copy.deepcopy(novy)
        upraveny["openapi.json"]["components"]["schemas"]["ZdraviVystup"]["properties"]["uptime"] = {"type": "integer"}
        upraveny["openapi.json"]["components"]["schemas"]["ZdraviVystup"]["required"].append("uptime")
        upraveny["openapi.json"]["paths"]["/api/system/audit"]["get"]["parameters"].append(
            {"name": "uzivatelId", "in": "query", "required": False, "schema": {"type": "integer"}})
        self.assertEqual(kontrakty.porovnej(novy, upraveny), [])


if __name__ == "__main__":
    unittest.main()

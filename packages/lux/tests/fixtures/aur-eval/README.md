# Testovaci korpus kontroly komunity (AUR)

Inertni textove vzorky pro test staticke kontroly `lux_community.py` (precheck). **Nic se nikdy
nestavi ani nespousti** - jsou to jen soubory, ktere cte skener.

- `malicious/` - rucne psane skodlive varianty zalozene na skutecnych PKGBUILD. Payloady jsou
  cistě synteticke (domeny `evil-example.com`, adresy z bloku pro dokumentaci `198.51.100.0/24`,
  `203.0.113.0/24`), slouzi jen jako rozpoznavaci vzory. `manifest.json` drzi pravdu (kategorie).
  Kazdy vzorek musi precheck oznacit aspon jako `medium`.
- `benign/` - oriznute kopie (jen `PKGBUILD`) skutecnych oblibenych balicku z AUR, zachovan radek
  `# Maintainer:` pro uznani autorstvi. Zadny z nich nesmi dat nalez `high`.

Mereni uspesnosti detekce (realny LuxAI) je v docs/luxos/package-management.md.

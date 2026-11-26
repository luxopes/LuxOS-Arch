# Balíčky LuxOS (.lux)

Každá podsložka s `lux.json` se při `./build.sh packages` zabalí do `.lux`, podepíše
a přidá do repozitáře `https://luxos.lux-ai.cz/repo/lux/` (`scripts/publish-repo.sh`).
Formát popisuje [dokumentace](../packages/lux/lux-package-format.md), vzor je v `docs/examples/hello-lux`.

Aplikace s vlastním sestavením mohou mít `prepare.sh`. Skript dostává cestu k prázdnému
pracovnímu adresáři a připraví v něm `lux.json`, `app/` a případné `share/`.
Pro místní sestavení Lux Vely lze použít:

```bash
stage=$(mktemp -d)
bash lux-packages/luxos-vela/prepare.sh "$stage"
lux pack "$stage" out/
```

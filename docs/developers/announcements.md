# Novinky LuxOS (oznámení od vývojářů)

Aplikace **Novinky LuxOS** (`luxos-news`) ukazuje uživatelům zprávy od týmu LuxOS: nové vydání,
plánovanou údržbu serverů, důležité změny. Nové novinky se objeví jako oznámení (zůstanou pod
zvonkem v liště). Klik na oznámení otevře aplikaci. Uživatel může upozorňování v aplikaci vypnout.

## Jak to funguje

```
site/announcements.json  --scripts/publish-site.sh-->  https://luxos.lux-ai.cz/announcements.json
                                                                  |
luxos-hub (3 min po přihlášení, pak každých 6 h)  -->  luxos-news --check  -->  oznámení
```

- Kontrola stahuje jen tento jeden soubor přes HTTPS. Nic se neodesílá.
- Každá položka se kontroluje (formát id a data, délky textů, odkaz jen `https://`). Neplatné
  položky se přeskočí, soubor nad 256 kB nebo s jinou verzí se zahodí.
- Text se zobrazuje jako čistý text, bez formátování. Odkaz se otevře jen kliknutím.
- Při prvním spuštění se neohlašují novinky starší než 14 dní (jsou jen v aplikaci). Za jednu
  kontrolu nejvýš 3 oznámení.

## Přidání novinky

```bash
luxos-news new site/announcements.json \
  --title "LuxOS 1.2 is out" --title-cs "Vyšel LuxOS 1.2" \
  --body "New design of the menu bar and LuxOS News." \
  --body-cs "Nový vzhled lišty a Novinky LuxOS." \
  --url https://luxos.lux-ai.cz/changes/ \
  --level important --until 2026-12-31
luxos-news validate site/announcements.json
scripts/publish-site.sh
```

`new` novinku přidá na začátek, kontroluje celý soubor a zapíše ho s odsazením. Soubor jde upravovat
i ručně; před vydáním vždy spusťte `validate` (navratový kód 1 a seznam chyb, když je něco špatně).

## Formát

```json
{
  "version": 1,
  "announcements": [
    {
      "id": "2026-12-01-luxos-1-2",
      "date": "2026-12-01",
      "until": "2026-12-31",
      "level": "important",
      "title": {"en": "LuxOS 1.2 is out", "cs": "Vyšel LuxOS 1.2"},
      "body": {"en": "…", "cs": "…"},
      "url": "https://luxos.lux-ai.cz/changes/"
    }
  ]
}
```

| Pole | Povinné | Pravidla |
|---|---|---|
| `id` | ano | 1–64 znaků `a-z 0-9 -`, jedinečné. Podle id se pamatuje, co už uživatel viděl, takže ho neměňte. |
| `date` | ano | `YYYY-MM-DD`. Novinka s budoucím datem se ukáže až ten den (plánované oznámení). |
| `until` | ne | `YYYY-MM-DD`, poslední den, kdy se novinka ukazuje (údržba, akce). |
| `level` | ne | `info` (výchozí) nebo `important` (oranžový štítek, oznámení nezmizí samo). |
| `title` | ano | Text nebo `{jazyk: text}`, nejvýš 120 znaků. Jazyk uživatele, jinak `en`. |
| `body` | ne | Jako `title`, nejvýš 2000 znaků. |
| `url` | ne | Jen `https://`, nejvýš 300 znaků. |

Nejvýš 50 novinek. Staré novinky mažte; po odstranění z kanálu zmizí i z aplikace.

## Testování

`LUXOS_NEWS_URL=http://127.0.0.1:PORT/announcements.json luxos-news --check` stáhne kanál z místního
serveru (jiná adresa než `https://` nebo `127.0.0.1`/`localhost` se ignoruje).
`luxos-news --list` vypíše platné novinky z mezipaměti. Testy:
`packages/luxos-desktop/tests/test_luxos_news.py`.

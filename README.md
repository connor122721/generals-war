# Generals ranked by wins above replacement

An interactive ranking of every commander who appears in an English Wikipedia battle infobox, scored by **WAR (wins above replacement)**: how many more battles they won than an average general would have, given the same size of army.

It is a from-scratch, automated take on Ethan Arsht's [military rankings](https://ethanarsht.github.io/military_rankings/) ([write-up](https://towardsdatascience.com/napoleon-was-the-best-general-ever-and-the-math-proves-it-86efed303eeb)), with three differences:

- **No hand labelling.** Winners, troop strengths and dates are parsed from the infobox wikitext, so the whole thing can be re-run on a schedule.
- **Far more battles.** Instead of the "List of battles" pages, it reads every article that uses `{{Infobox military conflict}}`.
- **Historic and modern views.** The browser recomputes WAR for any period (ancient, medieval, early modern, 19th century, world wars, since 1945, or custom years) and engagement type.
- **Interactive scatterplots.** Plot any two of: battles fought, total WAR, WAR per battle, win rate, the average general's win chance, career midpoint, typical army size and force ratio. Hover for details, click a dot to open that commander, drag to zoom. Each commander's page also has an "odds faced" scatter of every battle they fought.

Live site here: https://connor122721.github.io/generals-war/

## Keeping the data up to date

- **Automatically:** the workflow re-scrapes every Monday. It only re-downloads articles whose Wikipedia revision changed since the last run, so weekly runs take a few minutes.
- **On demand:** Actions → Update rankings → Run workflow (this also works from the GitHub mobile app).
- **After changing the scraper:** pushing a change under `scraper/` triggers a fresh scrape.
- **Locally:** `python -m scraper.build` (see below).

The page header shows when the data was last refreshed.

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest -q                       # parser and pipeline tests (no network)
python -m scraper.build --limit 300       # quick sample
python -m scraper.build                   # everything
python -m http.server -d site 8000        # then open http://localhost:8000
```

`--offline` rebuilds from the local cache without touching Wikipedia, which is handy when tweaking the model.

## What you get

| Path | Contents |
|---|---|
| `site/` | Static browser (plain HTML/CSS/JS, no build step) |
| `site/data/*.json` | Compact data the browser loads |
| `data/battles.csv` | One row per battle: year, type, result, strengths, replacement win probability, commanders on each side |
| `data/generals.csv` | One row per commander: battles, W/L/D, WAR, WAR per battle, shared WAR, active years |

The CSVs are easy to pick up in R (`readr::read_csv`) or pandas if you want to fit a different model.

## How it works

```
Wikipedia API ──► every page embedding {{Infobox military conflict}}   scraper/wiki.py
              ──► section-0 wikitext → infobox                         (cached by revision id)
infobox ──► sides, commander links, strengths, date, result           scraper/infobox.py
        ──► "Decisive French victory" → which side won                scraper/textparse.py
commander links ──► resolve redirects; keep pages that are people      (short description,
                                                                        then birth/death categories)
battles ──► fit P(win | force ratio); WAR per commander per battle     scraper/model.py
        ──► site/data/*.json + CSVs                                    scraper/build.py
```

**The score.** For each battle, the chance an average ("replacement") general wins is

```
P(win) = 1 / (1 + (enemy / own)^b)
```

with `b` fitted by maximum likelihood on battles where both strengths are known (draws count as half a win). If a strength is missing, P = 0.5. A commander earns `result − P(win)` per battle (win = 1, draw = 0.5, loss = 0), summed over their career. The alternative "split" credit divides each side's score among its listed commanders, which stops subordinates from riding their commander-in-chief's coat-tails.

On the reference project's 2017 data this model reproduces its headline numbers closely: Napoleon about +16.5 WAR (original 16.7), Julius Caesar +7.2 (7.4), Hannibal +5.6 (5.5).

**Parsing rules worth knowing.**
- *Result*: the tactical outcome wins over the strategic one ("Tactical draw; strategic British victory" counts as a draw). The winner phrase is matched to a side using the combatant names, flag templates, links and a table of irregular demonyms (French → France, Union, Confederate, Carthaginian …). "Coalition/Allied victory" goes to the side listing several belligerents.
- *Strength*: personnel only. Ships, guns, tanks, aircraft and units like divisions are ignored; legions count as 5,000; ranges use the midpoint; "Total:" lines win; competing estimates use the median; breakdowns by arm or country are summed. On the reference project's hand-entered strengths it lands within 25% about 88% of the time.
- *Exclusions*: pages whose title marks them as a whole war, battles without exactly two sides, battles with no recognisable result, and commanders without a Wikipedia article.

## Customising

- **Eras** — edit `ERAS` and `SEGMENTS` at the top of `site/app.js`.
- **Schedule** — the `cron` line in `.github/workflows/update.yml`.
- **Model** — `scraper/model.py`. The per-battle table in `data/battles.csv` has everything needed to try alternatives (e.g. adding casualties, or a Bayesian shrinkage for generals with few battles).
- **Demonyms** — if a result keeps failing to match, add it to `DEMONYMS` in `scraper/textparse.py`.

## Caveats

Wikipedia coverage is uneven (Western and modern battles are over-represented), infobox numbers are often contested, and this measures battlefield results only, not strategy, logistics or politics. Treat this as a nerdy thought experiment please.

## Credits and licence

Idea and WAR framing from Ethan Arsht. Battle data © Wikipedia contributors, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Code: MIT.

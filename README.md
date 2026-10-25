# Swiss Pantry

Compare grocery products across Swiss supermarkets by **health quality** and
**price per unit**, so a shopping list can be split across stores on evidence
rather than guesswork.

Built for a Zurich household: vegetarian, additive-conscious, price-conscious.

## What it does

- Scrapes **Migros, Aldi, Denner and Lidl** for a configurable set of product
  categories (soy milk, tofu, mozzarella, müsli, oats, hummus, …).
- Normalises every price to **CHF per 100 g / 100 ml / roll**, so different
  pack sizes are directly comparable.
- Scores each product for health using [Open Food Facts](https://world.openfoodfacts.org),
  weighted toward what actually matters to the user (additives and saturated
  fat), not salt or calories.
- Presents everything in a Streamlit app with a comparison table, per-store
  shopping list, and a link back to the source data for every rating.

## Health score

Starts at 100 and subtracts:

| Factor | Penalty |
| --- | --- |
| NOVA processing level | 1 → -0, 2 → -5, 3 → -15, 4 (ultra-processed) → -30 |
| Additives, by risk tier | high -10 each, moderate -5, low/unflagged -1 (capped -30) |
| Saturated fat | -6 per g/100 g (capped -30) |

Grades: **A** ≥85 · **B** ≥70 · **C** ≥50 · **D** ≥30 · else **E**.

Additive risk tiers come from Open Food Facts' EFSA overexposure evaluations
and France's ANSES "additives of interest" list, cached locally in
`config/additives_risk.json` (regenerate with `scripts/build_additives_risk.py`).
So a product with a few innocuous additives (citric acid, lecithin) is not
punished like one containing nitrites or MSG.

### On not knowing

The scorer is deliberately conservative, because a confident wrong answer is
worse than an honest gap:

- **No NOVA classification → no grade.** Processing level is the heaviest single
  term, so without it a score would be a guess wearing a grade.
- A name-based match to Open Food Facts is only accepted if it is the same
  *kind* of product (checked against an OFF category allowlist per category),
  from a *brand* that appears in the store's product name, and the OFF record
  actually names the *variant* rather than being a bare brand stub.
- Anything unmatched shows as **Unrated** with a "Why" column explaining which
  data was missing, and nutrition columns show an explicit *No data*.

## Usage

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

Scrape everything (backs up the DB first):

```bash
.venv/bin/python -m swiss_pantry.pipeline
```

Scrape one store or category:

```bash
.venv/bin/python -m swiss_pantry.pipeline --store Migros
.venv/bin/python -m swiss_pantry.pipeline --category muesli --category oats
```

Replay a scoring-rule change over existing data, without re-scraping:

```bash
.venv/bin/python rescore.py
```

Run the app:

```bash
.venv/bin/streamlit run swiss_pantry/app.py
```

## Online version

The hosted app runs on [Streamlit Community Cloud](https://share.streamlit.io)
from `streamlit_app.py`. The scrapers can't run there (Migros needs a headed
browser), so it serves `snapshot/pantry.db`, a read-only copy of the working
DB that is committed to the repo. Hosted, "Hide from this category" is not
shown, so visitors can't change the data for everyone.

Refresh the online prices after a scrape:

```bash
.venv/bin/python -m swiss_pantry.pipeline
.venv/bin/python scripts/publish_snapshot.py
git add snapshot/pantry.db && git commit -m "Refresh prices" && git push
```

The app redeploys on push. The snapshot drops hidden products and the raw
store responses, which keeps it around 0.5 MB.

First-time setup: sign in to Streamlit Community Cloud with GitHub, choose
**Create app**, pick this repo, branch `main` and main file `streamlit_app.py`.

## Adding a product category

Add an entry to `config/categories.yaml`. `keywords_include` / `keywords_exclude`
filter the store's noisy search results (they will happily return gnocchi for
"mozzarella"), and `off_category_tags` constrains which Open Food Facts
categories count as a valid match.

## Layout

```
config/categories.yaml       product categories + matching rules
config/additives_risk.json   cached additive risk tiers (EFSA / ANSES)
swiss_pantry/scrapers/       one module per store, behind a common interface
swiss_pantry/health/         Open Food Facts client, additive risk, scoring
swiss_pantry/pricing/        pack-size parsing and per-unit price
swiss_pantry/app.py          Streamlit UI
swiss_pantry/ui.py           comparison table rendering (sticky columns)
streamlit_app.py             entry point for the hosted app
snapshot/pantry.db           published read-only copy of the data
scripts/publish_snapshot.py  refreshes snapshot/pantry.db
```

## Notes and limitations

- **Coop is not included.** Their site sits behind DataDome bot protection that
  blocks at the IP level; the scraper exists (`scrapers/coop.py`) and is wired
  up but excluded from the pipeline until access is granted. No attempt is made
  to work around the protection.
- **Spar** has no online product catalogue to scrape.
- Migros needs a headed browser; the others run headless.
- Scraping is low-volume and rate-limited, for personal use. Store markup
  changes will occasionally break a scraper — each one is isolated to its own
  module.
- Open Food Facts is crowd-sourced, so coverage of Swiss private-label products
  is patchy. That is the main reason many products are Unrated.

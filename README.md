# Swiss Pantry

Compare grocery products across Swiss supermarkets by **health quality** and
**price per unit**, so a shopping list can be split across stores on evidence
rather than guesswork.

Built for a Zurich household: vegetarian, additive-conscious, price-conscious.

## What it does

- Fetches prices from **Migros, Aldi, Denner, Lidl and Otto's** for a
  configurable set of product categories (soy milk, tofu, mozzarella, müsli, oats, hummus, …).
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

Skip any store that needs a browser (today only Migros), as the scheduled
cloud run does:

```bash
.venv/bin/python -m swiss_pantry.pipeline --no-browser
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

Run the tests:

```bash
.venv/bin/pip install pytest && .venv/bin/python -m pytest
```

Run the app:

```bash
.venv/bin/streamlit run swiss_pantry/app.py
```

## Online version

The hosted app runs on [Streamlit Community Cloud](https://share.streamlit.io)
from `streamlit_app.py`. The scrapers can't run there (Migros needs a headed
browser), so it serves `snapshot/pantry.db`, a read-only copy of the working
DB that is committed to the repo. Visitors can only look; editing what
belongs in a category needs a password (see below).

A GitHub Actions job (`.github/workflows/refresh-prices.yml`) refreshes the
snapshot every Monday: it starts from `snapshot/pantry.db`, re-fetches every
store that works without a browser, and commits the new snapshot, which
redeploys the app. It can also be started by hand from the repo's Actions tab.
Migros needs a browser, so the cloud run keeps its last published prices;
refresh them from a laptop. The app shows a "prices as of" date per store.

Refresh the online prices (including Migros) from a laptop. Run every store,
not just `--store Migros`: the published snapshot is replaced by the laptop's
DB, so the other stores need to be just as fresh in it.

```bash
git pull
.venv/bin/python -m swiss_pantry.pipeline
.venv/bin/python scripts/publish_snapshot.py
git add snapshot/pantry.db && git commit -m "Refresh prices" && git push
```

The app redeploys on push. The snapshot drops hidden products and the raw
store responses, which keeps it around 0.5 MB.

First-time setup: sign in to Streamlit Community Cloud with GitHub, choose
**Create app**, pick this repo, branch `main` and main file `streamlit_app.py`.

### Editing what belongs in a category

Keyword matching lets through products that only contain the ingredient (tofu
burgers) or share a word with it (quinoa shampoo). In edit mode you can hide a
single product with its × button, or hide every product in a category whose
name contains a word. Both are applied when the app shows the data, so they
take effect at once and survive every price refresh.

Locally, edits go to `data/pantry.db` and no password is needed. On the hosted
app they go to a free [Supabase](https://supabase.com) project, because the
hosted app's own disk is wiped on every restart. To set it up once:

1. Create a Supabase project. In its **SQL Editor**, run the `SUPABASE_SETUP_SQL`
   from `swiss_pantry/storage/curation.py`.
2. From **Project Settings → API Keys**, copy the project URL and a **secret**
   key (not the publishable/anon one).
3. In Streamlit Community Cloud, open the app's **Settings → Secrets** and add:

   ```toml
   admin_password = "choose-one"

   [supabase]
   url = "https://<project>.supabase.co"
   secret_key = "sb_secret_..."
   ```

Then open **Edit mode** in the sidebar and enter the password.

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
- **Migros** needs a headed browser: its API is behind Cloudflare, which refuses
  plain HTTP requests. Aldi, Denner, Lidl and Otto's are fetched with plain
  HTTP requests from the JSON feeds or pages their own websites use.
- **Otto's** sells mostly non-food; its grocery range is small and
  shelf-stable, so most fresh categories have no Otto's products.
- Only Migros gives barcodes. The other stores' products are matched to Open
  Food Facts by name, which is why most of them are Unrated.
- Scraping is low-volume and rate-limited, for personal use. Store markup
  changes will occasionally break a scraper — each one is isolated to its own
  module.
- Open Food Facts is crowd-sourced, so coverage of Swiss private-label products
  is patchy. That is the main reason many products are Unrated.

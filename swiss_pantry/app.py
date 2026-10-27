from __future__ import annotations
import hmac
import json

import pandas as pd
import streamlit as st

from swiss_pantry import ui
from swiss_pantry.health import scoring
from swiss_pantry.matching.categorize import load_categories, matches_category
from swiss_pantry.storage.curation import SqliteCuration, SupabaseCuration, apply_rules
from swiss_pantry.storage.db import (
    DB_PATH,
    SNAPSHOT_PATH,
    get_connection,
    get_snapshot_connection,
)

st.set_page_config(page_title="Nourish and Nickle", layout="wide", page_icon="🥕")

if "cart" not in st.session_state:
    st.session_state.cart = {}

categories = load_categories()
cat_by_id = {c.id: c for c in categories}
# Locally the app runs on the scraper's working DB. Hosted, there is no data/
# directory, so it serves the committed snapshot read-only instead.
read_only = not DB_PATH.exists() and SNAPSHOT_PATH.exists()
conn = get_snapshot_connection() if read_only else get_connection()


def secret(*path: str):
    """A value from .streamlit/secrets.toml (or the hosted app's Secrets
    setting), or None when it isn't set - st.secrets raises if the file is
    missing altogether."""
    try:
        value = st.secrets
        for key in path:
            value = value[key]
        return value
    except (KeyError, FileNotFoundError):
        return None


# Curation (hidden products, extra exclude keywords) goes to Supabase when the
# app has its keys, which is how it works on the hosted app; otherwise to the
# local working DB. With neither, the app is view-only.
if secret("supabase", "url") and secret("supabase", "secret_key"):
    curation = SupabaseCuration(secret("supabase", "url"), secret("supabase", "secret_key"))
    needs_login = True
elif not read_only:
    curation = SqliteCuration(conn)
    needs_login = False
else:
    curation = None
    needs_login = False

UNIT_LABEL = {"g": "CHF/100g", "ml": "CHF/100ml", "roll": "CHF/roll", "piece": "CHF/piece"}
NO_DATA = ui.NO_DATA

# (display column, OFF nutriments key) - all already cached in off_raw, no
# extra querying needed per https://world.openfoodfacts.org nutriment fields.
NUTRITION_FIELDS = [
    ("kcal/100g", "energy-kcal_100g"),
    ("protein g/100g", "proteins_100g"),
    ("carbs g/100g", "carbohydrates_100g"),
    ("sugars g/100g", "sugars_100g"),
    ("fat g/100g", "fat_100g"),
    ("fiber g/100g", "fiber_100g"),
    ("salt g/100g", "salt_100g"),
]

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&display=swap');
      div[data-testid="stMetricValue"] { font-size: 1.35rem; }
      .sp-title { font-size:1.6rem; font-weight:700; margin:0.2rem 0 0.1rem 0; }
      .sp-sub { color:#8b949e; font-size:0.85rem; margin-bottom:0.6rem; }
      .nn-hero { display:flex; align-items:center; gap:1rem; padding:1.1rem 1.4rem;
                 margin:0 0 1rem 0; border-radius:16px; color:#fdfbf4;
                 background: radial-gradient(circle at 96% 10%, rgba(243,198,90,0.35), transparent 28%),
                             linear-gradient(120deg, #17452f 0%, #245f43 50%, #2f7d57 100%);
                 box-shadow: 0 6px 18px -10px rgba(23,69,47,0.6); }
      .nn-hero-mark { font-size:2.3rem; line-height:1; filter: drop-shadow(0 2px 3px rgba(0,0,0,0.2)); }
      .nn-hero h1 { font-family:'Fraunces', Georgia, serif; font-weight:700; font-size:2.1rem;
                    letter-spacing:-0.01em; margin:0; padding:0; color:#fdfbf4; line-height:1.1; }
      .nn-hero h1 .nn-amp { color:#f3c65a; font-style:italic; font-weight:600; }
      .nn-hero p { margin:0.25rem 0 0 0; font-size:0.95rem; opacity:0.88; }
      .nn-legend { display:flex; flex-wrap:wrap; gap:0.9rem; font-size:0.85rem; margin:0.2rem 0 0.5rem 0;
                   color: var(--text-color, inherit); opacity:0.85; }
      .nn-legend span { display:inline-flex; align-items:center; gap:0.35rem; }
      .nn-swatch { width:0.85rem; height:0.85rem; border-radius:3px; display:inline-block; }
      .nn-stats { display:flex; flex-wrap:wrap; gap:0.5rem 1.8rem; margin:0.3rem 0 0.6rem 0; }
      .nn-stats div { display:flex; flex-direction:column; }
      .nn-stats span { font-size:0.8rem; opacity:0.7; }
      .nn-stats b { font-size:1.35rem; font-weight:600; }
      @media (max-width: 640px) {
        .block-container { padding-top: 2.5rem; padding-left: 1rem; padding-right: 1rem; }
        .nn-hero { padding:0.7rem 0.9rem; gap:0.6rem; border-radius:12px; margin-bottom:0.6rem; }
        .nn-hero-mark { font-size:1.6rem; }
        .nn-hero h1 { font-size:1.45rem; }
        .nn-hero p { display:none; }
        .nn-stats { gap:0.4rem 1.2rem; }
        .nn-stats b { font-size:1.1rem; }
        .nn-legend { font-size:0.8rem; gap:0.6rem; }
        .nn-legend .nn-desktop { display:none; }
        .nn-legend .nn-mobile { display:inline-flex; }
      }
      .nn-legend .nn-mobile { display:none; }
    </style>
    <div class="nn-hero">
      <div class="nn-hero-mark">🥕</div>
      <div>
        <h1>Nourish <span class="nn-amp">and</span> Nickle</h1>
        <p>Healthy groceries, fair prices: Swiss supermarkets compared by health score and price per gram.</p>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


def nutrition_row(off_raw_json: str | None) -> dict:
    """Values are formatted as display strings (not left numeric) specifically
    so a missing value can show as an explicit "No data" instead of a blank
    cell that reads as zero or an accidental gap."""
    if not isinstance(off_raw_json, str):
        row = dict.fromkeys([label for label, _ in NUTRITION_FIELDS], NO_DATA)
        row["Ingredients"] = NO_DATA
        return row
    data = json.loads(off_raw_json)
    nutriments = data.get("nutriments", {})
    row = {}
    for label, key in NUTRITION_FIELDS:
        value = nutriments.get(key)
        row[label] = f"{value:g}" if isinstance(value, (int, float)) else NO_DATA
    row["Ingredients"] = data.get("ingredients_text") or NO_DATA
    return row


def load_category_df(category_id: str) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT id, store, raw_name, brand, price_chf, package_qty, package_unit,
               price_per_unit, health_score, health_grade,
               nova_group, additives_tags, saturated_fat_per_100g, off_raw, off_barcode, url, scraped_at
        FROM products
        WHERE category = ?
          AND NOT EXISTS (
              SELECT 1 FROM excluded_products e
              WHERE e.store = products.store AND e.category = products.category
                AND e.raw_name = products.raw_name
          )
        ORDER BY (health_score IS NULL) ASC, health_score DESC, price_per_unit ASC
        """,
        (category_id,),
    ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def add_to_cart(row) -> None:
    st.session_state.cart[int(row["id"])] = {
        "Store": row["Store"], "Product": row["Product"],
        "Brand": row["Brand"], "Price CHF": float(row["Price CHF"]),
    }


def column_kind(col: str, unit_label: str) -> str:
    if col == "Product":
        return "product"
    if col == "Grade":
        return "grade"
    if col == "Source":
        return "link"
    if col in ("Why", "Ingredients"):
        return "long"
    if col in {"Price CHF", unit_label, "Score"} | {c for c, _ in NUTRITION_FIELDS}:
        return "num"
    return "text"


def render_interactive_table(df: pd.DataFrame, table_cols: list[str], unit_label: str,
                             default_pinned: list[str]) -> None:
    st.markdown(
        '<div class="nn-legend">'
        '<span><i class="nn-swatch" style="background:#e0a100"></i>Lowest price per '
        f'{unit_label.split("/")[1]}</span>'
        '<span><i class="nn-swatch" style="background:#2e9e5b"></i>Best health score</span>'
        '<span class="nn-desktop">＋ adds to your shopping list · click a row for its full text · '
        "drag a header edge to resize · 📌 keeps a column in view</span>"
        '<span class="nn-mobile">Tap a product for nutrition and details</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    by_id = {int(r["id"]): r for _, r in df.iterrows()}
    rows = []
    for row_id, r in by_id.items():
        cells = {}
        for col in table_cols:
            value = r[col]
            cells[col] = None if not isinstance(value, str) and pd.isna(value) else str(value)
        rows.append({
            "id": row_id,
            "cells": cells,
            "cheapest": bool(r["_cheapest"]),
            "healthiest": bool(r["_healthiest"]),
            "in_cart": row_id in st.session_state.cart,
        })
    result = ui.interactive_table(
        columns=[{"name": c, "kind": column_kind(c, unit_label)} for c in table_cols],
        rows=rows,
        default_pinned=default_pinned,
        product_column="Product",
        card={"store": "Store", "grade": "Grade", "price": unit_label, "meta": ["Size", "Price CHF"]},
        editable=can_edit,
        key=f"products_{selected_id}",
    )
    toggled, hidden = result.toggle_cart, result.hide
    if toggled is not None and int(toggled) in by_id:
        row = by_id[int(toggled)]
        if int(toggled) in st.session_state.cart:
            del st.session_state.cart[int(toggled)]
            st.toast(f"Removed {row['Product']} from your list")
        else:
            add_to_cart(row)
            st.toast(f"Added {row['Product']} ({row['Store']}) to your list", icon="🛒")
        st.rerun()
    if hidden is not None and can_edit and int(hidden) in by_id:
        row = by_id[int(hidden)]
        curation.hide(row["Store"], selected_id, row["Product"])
        st.session_state.cart.pop(int(hidden), None)
        st.rerun()


def render_static_table(df: pd.DataFrame, table_cols: list[str], unit_label: str,
                        default_pinned: list[str]) -> None:
    """For Streamlit installs without v2 components: the read-only HTML table
    plus list pickers for adding and hiding."""
    pinned = st.multiselect(
        "Keep visible while scrolling sideways",
        options=["Store", "Product", "Brand", "Size", "Price CHF", unit_label, "Grade"],
        default=default_pinned,
    )
    st.markdown(
        ui.render_table(
            df,
            columns=table_cols,
            pinned=pinned,
            numeric_cols={"Price CHF", unit_label, "Score"} | {c for c, _ in NUTRITION_FIELDS},
            long_cols={"Why", "Ingredients"},
            html_cols={"Grade": ui.grade_pill, "Source": ui.source_link},
        ),
        unsafe_allow_html=True,
    )
    left, right = st.columns(2) if can_edit else (st.container(), None)
    labels = {f"{r['Store']} — {r['Product']}": int(r["id"]) for _, r in df.iterrows()}
    with left:
        to_add = st.multiselect("Add to shopping list", options=list(labels))
        if st.button("Add selected", use_container_width=True, disabled=not to_add):
            for label in to_add:
                add_to_cart(df[df["id"] == labels[label]].iloc[0])
            st.rerun()
    if right is not None:
        with right:
            to_hide = st.multiselect("Hide from this category", options=list(labels))
            if st.button("Hide selected", use_container_width=True, disabled=not to_hide):
                for label in to_hide:
                    row = df[df["id"] == labels[label]].iloc[0]
                    curation.hide(row["Store"], selected_id, row["Product"])
                    st.session_state.cart.pop(labels[label], None)
                st.rerun()


tab_browse, tab_list = st.tabs(["Compare", "Shopping list"])

with tab_browse:
    # Category and filters sit above the results rather than in the sidebar,
    # which on a phone hides behind a menu button.
    pick, filters = st.columns([3, 1], vertical_alignment="bottom")
    selected_id = pick.selectbox(
        "Product type",
        options=sorted((c.id for c in categories), key=lambda k: cat_by_id[k].name),
        format_func=lambda k: cat_by_id[k].name,
    )
    category = cat_by_id[selected_id]
    df = load_category_df(selected_id)

    stores = sorted(df["store"].unique()) if not df.empty else []
    with filters.popover("Filters", use_container_width=True):
        chosen_stores = st.multiselect("Stores", stores, default=stores)
        rated_only = st.checkbox("Only products with a health grade", value=False)

    if needs_login and not st.session_state.get("can_edit"):
        with st.sidebar.expander("Edit mode"):
            password = st.text_input("Password", type="password")
            if password:
                expected = secret("admin_password") or ""
                if expected and hmac.compare_digest(password, expected):
                    st.session_state.can_edit = True
                    st.rerun()
                st.error("Wrong password")
    can_edit = curation is not None and (not needs_login or st.session_state.get("can_edit", False))

    hidden, rules = set(), []
    if curation is not None:
        try:
            hidden, rules = curation.hidden(selected_id), curation.rules(selected_id)
        except Exception as e:  # a Supabase outage shouldn't take the app down
            st.sidebar.warning(f"Couldn't load your edits, showing the unedited list ({e.__class__.__name__}).")
            can_edit = False
    if not df.empty:
        df = df[[(s, n) not in hidden for s, n in zip(df["store"], df["raw_name"])]]
    # The yaml's own keywords are re-applied here too, so a keyword fix takes
    # effect on the published snapshot without waiting for a re-scrape.
    if not df.empty:
        df = df[df["raw_name"].apply(lambda n: matches_category(n, category))]
    before_rules = df
    df = apply_rules(df, rules)

    if can_edit:
        st.sidebar.header("What belongs here")
        st.sidebar.caption(
            f"Hide a product with its × button. Or hide every {category.name.lower()} "
            "product whose name contains a word:"
        )
        with st.sidebar.form("add_rule", clear_on_submit=True, border=False):
            word = st.text_input("Word", placeholder="e.g. burger", label_visibility="collapsed")
            if st.form_submit_button("Hide products with this word") and word.strip():
                curation.add_rule(selected_id, word)
                st.rerun()
        for kw in rules:
            n = len(before_rules) - len(apply_rules(before_rules, [kw]))
            if st.sidebar.button(f"✕ “{kw}” · hides {n}", key=f"rule_{kw}", help="Stop hiding this word"):
                curation.remove_rule(selected_id, kw)
                st.rerun()
        if hidden:
            with st.sidebar.expander(f"{len(hidden)} hidden product(s)"):
                for store, name in sorted(hidden):
                    if st.button(f"Unhide · {store}: {name}", key=f"unhide_{store}_{name}"):
                        curation.unhide(store, selected_id, name)
                        st.rerun()
                if st.button("Unhide all"):
                    curation.unhide_all(selected_id)
                    st.rerun()

    unit_label = UNIT_LABEL[category.unit]

    if not df.empty:
        df = df[df["store"].isin(chosen_stores)]
        if rated_only:
            df = df[df["health_score"].notna()]

    if df.empty:
        if read_only:
            st.info("Nothing to show. Try widening the filters.")
        else:
            st.info("Nothing to show. Run `python -m swiss_pantry.pipeline` or widen the filters.")
    else:
        rated = int(df["health_score"].notna().sum())
        # A unit price of 0 is a pack-size parsing error upstream, not a bargain.
        cheapest = df.loc[df["price_per_unit"] > 0, "price_per_unit"].min()
        best_grade_row = df.loc[df["health_score"].idxmax()] if rated else None

        # One wrapping row of small stats instead of st.metric columns, which
        # stack into a full screen of numbers on a phone.
        stats = [
            ("Products", len(df)),
            ("Stores", df["store"].nunique()),
            (f"Cheapest {unit_label.split('/')[1]}", f"{cheapest:.2f}" if pd.notna(cheapest) else "—"),
            ("With a grade", f"{rated}/{len(df)}"),
        ]
        st.markdown(
            '<div class="nn-stats">'
            + "".join(f"<div><span>{label}</span><b>{value}</b></div>" for label, value in stats)
            + "</div>",
            unsafe_allow_html=True,
        )
        if best_grade_row is not None:
            st.caption(
                f"Best-scoring: **{best_grade_row['raw_name']}** ({best_grade_row['store']}) "
                f"— grade {best_grade_row['health_grade']}, {best_grade_row['price_per_unit']:.2f} {unit_label}"
            )

        # Explanation columns rebuilt from the same stored values the score used.
        if category.fresh_produce:
            df["Why"] = "Fresh, unpackaged produce - assumed unprocessed with no additives."
        else:
            nn_int = lambda v: None if pd.isna(v) else int(v)  # noqa: E731
            nn_float = lambda v: None if pd.isna(v) else float(v)  # noqa: E731
            nn_tags = lambda v: None if pd.isna(v) else json.loads(v)  # noqa: E731
            df["Why"] = df.apply(
                lambda r: scoring.explain(
                    nn_int(r["nova_group"]), nn_tags(r["additives_tags"]), nn_float(r["saturated_fat_per_100g"])
                ),
                axis=1,
            )

        # Highlights are for the rows on screen: this category, current filters.
        # Ties all get highlighted, unless every row ties (e.g. fresh produce
        # all scores 100), where a highlight would single nothing out.
        df["_cheapest"] = df["price_per_unit"].notna() & (df["price_per_unit"] == cheapest)
        df["_healthiest"] = df["health_score"].notna() & (df["health_score"] == df["health_score"].max())
        for flag in ("_cheapest", "_healthiest"):
            if len(df) > 1 and df[flag].all():
                df[flag] = False

        nutrition_df = pd.DataFrame(df["off_raw"].apply(nutrition_row).tolist(), index=df.index)
        df = pd.concat([df, nutrition_df], axis=1)

        df["Source"] = df["off_barcode"].apply(
            lambda code: f"https://world.openfoodfacts.org/product/{code}" if pd.notna(code) else None
        )
        df = df.rename(
            columns={
                "store": "Store",
                "raw_name": "Product",
                "brand": "Brand",
                "price_chf": "Price CHF",
                "health_grade": "Grade",
                "health_score": "Score",
                "price_per_unit": unit_label,
            }
        )
        df["Size"] = df.apply(
            lambda r: f"{r['package_qty']:g}{r['package_unit']}" if pd.notna(r["package_qty"]) else NO_DATA,
            axis=1,
        )
        df["Grade"] = df["Grade"].fillna("Unrated")
        df["Score"] = df["Score"].apply(lambda v: NO_DATA if pd.isna(v) else f"{v:g}")
        df[unit_label] = df[unit_label].apply(lambda v: NO_DATA if pd.isna(v) else f"{v:.2f}")
        df["Price CHF"] = df["Price CHF"].apply(lambda v: f"{v:.2f}")

        base_cols = ["Store", "Product", "Brand", "Size", "Price CHF", unit_label]
        table_cols = base_cols + ["Grade", "Score"] + [c for c, _ in NUTRITION_FIELDS] + ["Why", "Ingredients", "Source"]

        default_pinned = ["Store", "Product"]
        if ui.HAS_INTERACTIVE_TABLE:
            render_interactive_table(df, table_cols, unit_label, default_pinned)
        else:
            render_static_table(df, table_cols, unit_label, default_pinned)

        with st.expander("How is the health score calculated?"):
            st.markdown(
                """
Starts at **100** and subtracts penalties, weighted toward what you care about
(additives and saturated fat; salt and calories are ignored):

- **Processing level (NOVA group)**: 1 (unprocessed) → -0, 2 → -5, 3 → -15, 4 (ultra-processed) → -30.
- **Additives**, weighted by risk tier from Open Food Facts' EFSA/ANSES data rather than merely counted:
  **high** risk (e.g. nitrites, MSG) → -10 each, **moderate** → -5, **low/unflagged** (e.g. citric acid) → -1. Capped at -30.
- **Saturated fat**: -6 per g/100g, capped at -30.

Grades: **A** ≥85 · **B** ≥70 · **C** ≥50 · **D** ≥30 · else **E**.

**No NOVA classification means no grade.** Processing level is the heaviest single
term, so without it a score would be a guess wearing a grade — those products show
as *Unrated*, and the **Why** column says which kind of data was missing. Fresh
produce is the one exception: it's treated as unprocessed by definition.
                """
            )
        # Per store, because stores are refreshed separately: the weekly cloud
        # run skips any store that needs a real browser.
        as_of = pd.to_datetime(df["scraped_at"], utc=True, format="ISO8601").groupby(df["Store"]).max()
        st.caption("Prices as of: " + " · ".join(f"{s} {d:%d %b %Y}" for s, d in as_of.items()))

with tab_list:
    st.markdown('<div class="sp-title">Shopping list</div>', unsafe_allow_html=True)
    if not st.session_state.cart:
        st.info("Nothing added yet — pick products in the Compare tab.")
    else:
        cart_df = pd.DataFrame(st.session_state.cart.values())
        grand_total = cart_df["Price CHF"].sum()

        stats = [("Items", len(cart_df)), ("Stores", cart_df["Store"].nunique()), ("Total", f"CHF {grand_total:.2f}")]
        st.markdown(
            '<div class="nn-stats">'
            + "".join(f"<div><span>{label}</span><b>{value}</b></div>" for label, value in stats)
            + "</div>",
            unsafe_allow_html=True,
        )

        # A tick box per item, so the list can be used in the shop on a phone.
        for store, group in cart_df.groupby("Store"):
            st.markdown(f"#### {store} — CHF {group['Price CHF'].sum():.2f}")
            for item_id, item in zip(st.session_state.cart, st.session_state.cart.values()):
                if item["Store"] == store:
                    st.checkbox(f"{item['Product']} · CHF {item['Price CHF']:.2f}", key=f"got_{item_id}")

        if st.button("Clear list"):
            st.session_state.cart = {}
            st.rerun()

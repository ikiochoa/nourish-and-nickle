from __future__ import annotations
import json

import pandas as pd
import streamlit as st

from swiss_pantry import ui
from swiss_pantry.health import scoring
from swiss_pantry.matching.categorize import load_categories
from swiss_pantry.storage.db import (
    DB_PATH,
    SNAPSHOT_PATH,
    clear_exclusions,
    count_exclusions,
    exclude_product,
    get_connection,
    get_snapshot_connection,
)

st.set_page_config(page_title="Swiss Pantry", layout="wide", page_icon="🛒")

if "cart" not in st.session_state:
    st.session_state.cart = {}

categories = load_categories()
cat_by_id = {c.id: c for c in categories}
# Locally the app runs on the scraper's working DB. Hosted, there is no data/
# directory, so it serves the committed snapshot read-only instead.
read_only = not DB_PATH.exists() and SNAPSHOT_PATH.exists()
conn = get_snapshot_connection() if read_only else get_connection()

UNIT_LABEL = {"g": "CHF/100g", "ml": "CHF/100ml", "roll": "CHF/roll"}
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
      div[data-testid="stMetricValue"] { font-size: 1.35rem; }
      .sp-title { font-size:1.6rem; font-weight:700; margin:0.2rem 0 0.1rem 0; }
      .sp-sub { color:#8b949e; font-size:0.85rem; margin-bottom:0.6rem; }
    </style>
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


tab_browse, tab_list = st.tabs(["Compare", "Shopping list"])

with tab_browse:
    st.sidebar.header("Category")
    selected_id = st.sidebar.selectbox(
        "Product",
        options=sorted((c.id for c in categories), key=lambda k: cat_by_id[k].name),
        format_func=lambda k: cat_by_id[k].name,
    )
    category = cat_by_id[selected_id]
    df = load_category_df(selected_id)

    st.sidebar.header("Filters")
    stores = sorted(df["store"].unique()) if not df.empty else []
    chosen_stores = st.sidebar.multiselect("Stores", stores, default=stores)
    rated_only = st.sidebar.checkbox("Only products with a health grade", value=False)

    hidden_count = 0 if read_only else count_exclusions(conn, selected_id)
    if hidden_count:
        st.sidebar.caption(f"{hidden_count} item(s) hidden here")
        if st.sidebar.button("Unhide all in this category"):
            clear_exclusions(conn, selected_id)
            st.rerun()

    unit_label = UNIT_LABEL[category.unit]

    if not df.empty:
        df = df[df["store"].isin(chosen_stores)]
        if rated_only:
            df = df[df["health_score"].notna()]

    st.markdown(f'<div class="sp-title">{category.name}</div>', unsafe_allow_html=True)

    if df.empty:
        if read_only:
            st.info("Nothing to show. Try widening the filters.")
        else:
            st.info("Nothing to show. Run `python -m swiss_pantry.pipeline` or widen the filters.")
    else:
        rated = int(df["health_score"].notna().sum())
        cheapest = df["price_per_unit"].min()
        best_grade_row = df.loc[df["health_score"].idxmax()] if rated else None

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Products", len(df))
        c2.metric("Stores", df["store"].nunique())
        c3.metric(f"Cheapest {unit_label.split('/')[1]}", f"{cheapest:.2f}" if pd.notna(cheapest) else "—")
        c4.metric("With a grade", f"{rated}/{len(df)}")
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

        pinned = st.multiselect(
            "Keep visible while scrolling sideways",
            options=base_cols + ["Grade"],
            default=["Store", "Product"],
            help="These columns stay frozen on the left, so you always know which product a row belongs to.",
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

        st.divider()
        # Hiding writes to the DB, so it only exists when running locally.
        left, right = (st.container(), None) if read_only else st.columns(2)
        labels = {f"{r['Store']} — {r['Product']}": int(r["id"]) for _, r in df.iterrows()}

        with left:
            to_add = st.multiselect("Add to shopping list", options=list(labels))
            if st.button("Add selected", use_container_width=True, disabled=not to_add):
                for label in to_add:
                    row = df[df["id"] == labels[label]].iloc[0]
                    st.session_state.cart[labels[label]] = {
                        "Store": row["Store"], "Product": row["Product"],
                        "Brand": row["Brand"], "Price CHF": float(row["Price CHF"]),
                    }
                st.rerun()

        if right is not None:
            with right:
                to_hide = st.multiselect(
                    "Hide from this category",
                    options=list(labels),
                    help="For products that don't belong here. Persists across re-scrapes.",
                )
                if st.button("Hide selected", use_container_width=True, disabled=not to_hide):
                    for label in to_hide:
                        row = df[df["id"] == labels[label]].iloc[0]
                        exclude_product(conn, row["Store"], selected_id, row["Product"])
                        st.session_state.cart.pop(labels[label], None)
                    st.rerun()

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

        top = st.columns(3)
        top[0].metric("Items", len(cart_df))
        top[1].metric("Stores", cart_df["Store"].nunique())
        top[2].metric("Total", f"CHF {grand_total:.2f}")

        for store, group in cart_df.groupby("Store"):
            st.subheader(f"{store} — CHF {group['Price CHF'].sum():.2f}")
            st.dataframe(
                group[["Product", "Brand", "Price CHF"]].reset_index(drop=True),
                hide_index=True,
                use_container_width=True,
            )

        if st.button("Clear list"):
            st.session_state.cart = {}
            st.rerun()

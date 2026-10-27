"""Presentation layer for the browse table.

The comparison table is a small custom component (st.components.v2, Streamlit
1.51+): pin icons in the headers, drag-to-resize columns, click a row for its
full text, and a per-row button that adds the product to the shopping list.
Older Streamlit installs (e.g. on Python 3.8) don't have v2 components, so
they fall back to `render_table`, a static HTML table with the same columns.
"""
from __future__ import annotations

import html
from pathlib import Path


NO_DATA = "No data"

# Width reserved for each pinned column, so following pinned columns know how
# far from the left edge to sit. Sticky offsets have to be absolute pixels.
PINNED_WIDTH_PX = 190

GRADE_COLORS = {
    "A": ("#0f6b32", "#d3f2de"),
    "B": ("#4a7c15", "#e6f4cd"),
    "C": ("#8a6100", "#fbeec6"),
    "D": ("#a4500b", "#fbe0cb"),
    "E": ("#9d2019", "#fad9d6"),
}

CSS = """
<style>
.sp-wrap { overflow: auto; max-height: 72vh; border: 1px solid var(--sp-border);
           border-radius: 10px; background: var(--sp-bg); }
:root { --sp-border:#e3e6ea; --sp-bg:#ffffff; --sp-head:#f6f7f9; --sp-text:#1f2328;
        --sp-muted:#8b949e; --sp-zebra:#fafbfc; --sp-hover:#eef4ff; }
@media (prefers-color-scheme: dark) {
  :root { --sp-border:#30363d; --sp-bg:#0f1116; --sp-head:#161b22; --sp-text:#e6edf3;
          --sp-muted:#7d8590; --sp-zebra:#12151b; --sp-hover:#1b2430; }
}
table.sp { border-collapse: separate; border-spacing: 0; font-size: 0.86rem;
           color: var(--sp-text); width: max-content; min-width: 100%; }
table.sp th, table.sp td { padding: 0.5rem 0.65rem; text-align: left;
           border-bottom: 1px solid var(--sp-border); white-space: nowrap; }
table.sp thead th { position: sticky; top: 0; z-index: 3; background: var(--sp-head);
           font-weight: 600; border-bottom: 2px solid var(--sp-border); }
table.sp tbody tr:nth-child(even) td { background: var(--sp-zebra); }
table.sp tbody tr:hover td { background: var(--sp-hover); }
table.sp td.sp-pin, table.sp th.sp-pin { position: sticky; z-index: 2;
           background: var(--sp-bg); border-right: 1px solid var(--sp-border); }
table.sp tbody tr:nth-child(even) td.sp-pin { background: var(--sp-zebra); }
table.sp tbody tr:hover td.sp-pin { background: var(--sp-hover); }
table.sp thead th.sp-pin { z-index: 4; background: var(--sp-head); }
/* Pinned columns must occupy exactly the width their sticky offset reserves,
   otherwise a narrow column (e.g. "Store") leaves a gap that scrolled columns
   show through as they pass underneath. */
td.sp-pin, th.sp-pin { width: 190px; min-width: 190px; max-width: 190px;
           overflow: hidden; text-overflow: ellipsis; }
td.sp-num { text-align: right; font-variant-numeric: tabular-nums; }
td.sp-long { max-width: 320px; overflow: hidden; text-overflow: ellipsis; }
.sp-muted { color: var(--sp-muted); font-style: italic; }
.sp-pill { padding: 0.1rem 0.5rem; border-radius: 999px; font-weight: 700; font-size: 0.78rem; }
.sp-best { font-weight: 700; }
.sp-best::after { content: " ★"; color: #d29200; }
a.sp-src { color: #2f6feb; text-decoration: none; }
a.sp-src:hover { text-decoration: underline; }
</style>
"""


def _cell(value, *, numeric=False, long_text=False) -> str:
    text = "" if value is None else str(value)
    classes = []
    if numeric:
        classes.append("sp-num")
    if long_text:
        classes.append("sp-long")
    title = f' title="{html.escape(text)}"' if long_text and text else ""
    if text == NO_DATA:
        return f'<td class="{" ".join(classes)}"><span class="sp-muted">{NO_DATA}</span></td>'
    return f'<td class="{" ".join(classes)}"{title}>{html.escape(text)}</td>'


def grade_pill(grade) -> str:
    if not grade or grade == "Unrated":
        return '<span class="sp-muted">Unrated</span>'
    fg, bg = GRADE_COLORS.get(grade, ("#57606a", "#eaeef2"))
    return f'<span class="sp-pill" style="color:{fg};background:{bg}">{html.escape(grade)}</span>'


def source_link(url) -> str:
    if not url:
        return '<span class="sp-muted">—</span>'
    return f'<a class="sp-src" href="{html.escape(str(url))}" target="_blank" rel="noopener">Open Food Facts ↗</a>'


def render_table(df, columns: list[str], pinned: list[str], numeric_cols: set,
                 long_cols: set, html_cols: dict, best_value=None, best_col=None) -> str:
    """Build the comparison table. `pinned` columns are frozen to the left, in
    the order given, so the product's identity stays on screen while the wide
    nutrition columns scroll underneath."""
    ordered = [c for c in pinned if c in columns] + [c for c in columns if c not in pinned]
    offsets, running = {}, 0
    for col in pinned:
        if col in columns:
            offsets[col] = running
            running += PINNED_WIDTH_PX

    head = []
    for col in ordered:
        if col in offsets:
            head.append(f'<th class="sp-pin" style="left:{offsets[col]}px">{html.escape(col)}</th>')
        else:
            head.append(f"<th>{html.escape(col)}</th>")

    body = []
    for _, row in df.iterrows():
        cells = []
        for col in ordered:
            raw = row.get(col)
            if col in html_cols:
                rendered = html_cols[col](raw)
                if col in offsets:
                    cells.append(f'<td class="sp-pin" style="left:{offsets[col]}px">{rendered}</td>')
                else:
                    cells.append(f"<td>{rendered}</td>")
                continue
            if col in offsets:
                text = "" if raw is None else str(raw)
                cells.append(
                    f'<td class="sp-pin" style="left:{offsets[col]}px" title="{html.escape(text)}">'
                    f"{html.escape(text)}</td>"
                )
                continue
            is_best = best_col == col and best_value is not None and raw == best_value
            cell = _cell(raw, numeric=col in numeric_cols, long_text=col in long_cols)
            if is_best:
                cell = cell.replace("<td ", '<td class="sp-best" ', 1) if 'class="' not in cell[:12] else cell
            cells.append(cell)
        body.append("<tr>" + "".join(cells) + "</tr>")

    return (
        CSS
        + '<div class="sp-wrap"><table class="sp"><thead><tr>'
        + "".join(head)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


_COMPONENT_DIR = Path(__file__).parent / "table_component"
try:
    from streamlit.components import v2 as _components_v2
except ImportError:
    _interactive_table = None
else:
    _interactive_table = _components_v2.component(
        "nourish_product_table",
        css=(_COMPONENT_DIR / "table.css").read_text(encoding="utf-8"),
        js=(_COMPONENT_DIR / "table.js").read_text(encoding="utf-8"),
    )

HAS_INTERACTIVE_TABLE = _interactive_table is not None


def interactive_table(*, columns: list[dict], rows: list[dict], default_pinned: list[str],
                      product_column: str, card: dict, editable: bool, key: str):
    """Mount the interactive table. Returns the component result, whose
    `toggle_cart` / `hide` attributes hold a row id on the run after a click.

    `columns` are {"name", "kind"} with kind one of text, product, num, long,
    grade, link. Each row is {"id", "cells", "cheapest", "healthiest", "in_cart"}.
    On narrow (phone) screens rows show as cards instead; `card` names the
    columns a card shows up front: {"store", "grade", "price", "meta": [...]}.
    Every other column goes in the details a tap on the card opens.
    """
    return _interactive_table(
        data={
            "columns": columns,
            "rows": rows,
            "default_pinned": default_pinned,
            "product_column": product_column,
            "card": card,
            "editable": editable,
        },
        key=key,
        on_toggle_cart_change=lambda: None,
        on_hide_change=lambda: None,
    )

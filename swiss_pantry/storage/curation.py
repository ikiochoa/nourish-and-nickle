"""What belongs in a product type, as curated by hand: single products hidden
from a category, and extra "must not contain" keywords per category.

Keyword matching in config/categories.yaml lets through products that merely
contain the ingredient (tofu burgers, tofu ravioli) or share a word with it
(quinoa shampoo). These two lists fix that without touching the scrapers.

Two backends, same interface:
- SqliteCuration: the local working DB, for running the app on the Mac.
- SupabaseCuration: a Supabase table, so curating also works on the hosted
  app, whose own disk is wiped on every restart. Talks to Supabase's REST API
  with the project's secret key, which only ever lives in the app's secrets.
"""
from __future__ import annotations

import sqlite3
from typing import Protocol

import httpx

RULES_SCHEMA = """
CREATE TABLE IF NOT EXISTS category_rules (
    category TEXT NOT NULL,
    keyword TEXT NOT NULL,
    PRIMARY KEY (category, keyword)
);
"""

# Run once in the Supabase SQL editor. Row level security with no policies
# means the public (anon) key can't read or write these; only the secret key
# the app uses can.
SUPABASE_SETUP_SQL = """
create table if not exists excluded_products (
    store text not null,
    category text not null,
    raw_name text not null,
    created_at timestamptz not null default now(),
    primary key (store, category, raw_name)
);
create table if not exists category_rules (
    category text not null,
    keyword text not null,
    created_at timestamptz not null default now(),
    primary key (category, keyword)
);
alter table excluded_products enable row level security;
alter table category_rules enable row level security;
"""


def normalize_keyword(keyword: str) -> str:
    # Product names are matched lowercased (see categorize.matches_category).
    return " ".join(keyword.lower().split())


class Curation(Protocol):
    def hidden(self, category: str) -> set[tuple[str, str]]: ...
    def hide(self, store: str, category: str, raw_name: str) -> None: ...
    def unhide(self, store: str, category: str, raw_name: str) -> None: ...
    def unhide_all(self, category: str) -> None: ...
    def rules(self, category: str) -> list[str]: ...
    def add_rule(self, category: str, keyword: str) -> None: ...
    def remove_rule(self, category: str, keyword: str) -> None: ...


class SqliteCuration:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        conn.execute(RULES_SCHEMA)

    def hidden(self, category: str) -> set[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT store, raw_name FROM excluded_products WHERE category = ?", (category,)
        ).fetchall()
        return {(r[0], r[1]) for r in rows}

    def hide(self, store: str, category: str, raw_name: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO excluded_products (store, category, raw_name) VALUES (?, ?, ?)",
            (store, category, raw_name),
        )
        self.conn.commit()

    def unhide(self, store: str, category: str, raw_name: str) -> None:
        self.conn.execute(
            "DELETE FROM excluded_products WHERE store = ? AND category = ? AND raw_name = ?",
            (store, category, raw_name),
        )
        self.conn.commit()

    def unhide_all(self, category: str) -> None:
        self.conn.execute("DELETE FROM excluded_products WHERE category = ?", (category,))
        self.conn.commit()

    def rules(self, category: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT keyword FROM category_rules WHERE category = ? ORDER BY keyword", (category,)
        ).fetchall()
        return [r[0] for r in rows]

    def add_rule(self, category: str, keyword: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO category_rules (category, keyword) VALUES (?, ?)",
            (category, normalize_keyword(keyword)),
        )
        self.conn.commit()

    def remove_rule(self, category: str, keyword: str) -> None:
        self.conn.execute(
            "DELETE FROM category_rules WHERE category = ? AND keyword = ?", (category, keyword)
        )
        self.conn.commit()


class SupabaseCuration:
    def __init__(self, url: str, key: str, client: httpx.Client | None = None):
        headers = {"apikey": key}
        # Legacy service_role keys are JWTs and also go in Authorization; the
        # newer sb_secret_ keys only go in apikey.
        if key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {key}"
        self.client = client or httpx.Client(
            base_url=f"{url.rstrip('/')}/rest/v1", headers=headers, timeout=10
        )

    def _get(self, table: str, params: dict) -> list[dict]:
        r = self.client.get(f"/{table}", params=params)
        r.raise_for_status()
        return r.json()

    def _insert(self, table: str, row: dict, conflict: str) -> None:
        r = self.client.post(
            f"/{table}",
            params={"on_conflict": conflict},
            json=row,
            headers={"Prefer": "resolution=ignore-duplicates,return=minimal"},
        )
        r.raise_for_status()

    def _delete(self, table: str, filters: dict) -> None:
        r = self.client.delete(f"/{table}", params={k: f"eq.{v}" for k, v in filters.items()})
        r.raise_for_status()

    def hidden(self, category: str) -> set[tuple[str, str]]:
        rows = self._get("excluded_products", {"category": f"eq.{category}", "select": "store,raw_name"})
        return {(r["store"], r["raw_name"]) for r in rows}

    def hide(self, store: str, category: str, raw_name: str) -> None:
        self._insert(
            "excluded_products",
            {"store": store, "category": category, "raw_name": raw_name},
            "store,category,raw_name",
        )

    def unhide(self, store: str, category: str, raw_name: str) -> None:
        self._delete("excluded_products", {"store": store, "category": category, "raw_name": raw_name})

    def unhide_all(self, category: str) -> None:
        self._delete("excluded_products", {"category": category})

    def rules(self, category: str) -> list[str]:
        rows = self._get(
            "category_rules", {"category": f"eq.{category}", "select": "keyword", "order": "keyword"}
        )
        return [r["keyword"] for r in rows]

    def add_rule(self, category: str, keyword: str) -> None:
        self._insert(
            "category_rules", {"category": category, "keyword": normalize_keyword(keyword)}, "category,keyword"
        )

    def remove_rule(self, category: str, keyword: str) -> None:
        self._delete("category_rules", {"category": category, "keyword": keyword})


def apply_rules(df, extra_excludes: list[str], name_col: str = "raw_name"):
    """Drop rows whose name contains any of the extra keywords - the same test
    categorize.matches_category applies to the yaml's keywords_exclude."""
    if df.empty or not extra_excludes:
        return df
    names = df[name_col].str.lower()
    mask = names.apply(lambda n: any(kw in n for kw in extra_excludes))
    return df[~mask]

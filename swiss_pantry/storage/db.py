from __future__ import annotations
import json
import sqlite3
from pathlib import Path

from swiss_pantry.storage.models import ScoredProduct

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "pantry.db"
# Published copy of DB_PATH, committed to the repo so the hosted app has data
# to show without running any scraper (see scripts/publish_snapshot.py).
SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "snapshot" / "pantry.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store TEXT NOT NULL,
    category TEXT NOT NULL,
    raw_name TEXT NOT NULL,
    brand TEXT,
    price_chf REAL NOT NULL,
    package_qty REAL,
    package_unit TEXT,
    price_per_unit REAL,
    url TEXT,
    barcode TEXT,
    nova_group INTEGER,
    additives_tags TEXT,
    saturated_fat_per_100g REAL,
    health_score REAL,
    health_grade TEXT,
    scraped_at TEXT NOT NULL,
    store_raw TEXT,
    off_raw TEXT,
    off_barcode TEXT,
    UNIQUE(store, category, raw_name, package_qty)
);
"""

# User-curated blocklist: products that don't actually belong in a category
# (keyword matching lets some junk through - e.g. "Banana Hair Food Shampoo"
# matching "banana"). Kept separate from `products` so it survives re-scrapes.
EXCLUSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS excluded_products (
    store TEXT NOT NULL,
    category TEXT NOT NULL,
    raw_name TEXT NOT NULL,
    PRIMARY KEY (store, category, raw_name)
);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.execute(EXCLUSIONS_SCHEMA)
    return conn


def get_snapshot_connection() -> sqlite3.Connection:
    """Read-only, so the hosted app can never write to the published data -
    and visitors can't hide products for everyone else."""
    conn = sqlite3.connect(f"file:{SNAPSHOT_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def exclude_product(conn: sqlite3.Connection, store: str, category: str, raw_name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO excluded_products (store, category, raw_name) VALUES (?, ?, ?)",
        (store, category, raw_name),
    )
    conn.commit()


def clear_exclusions(conn: sqlite3.Connection, category: str) -> None:
    conn.execute("DELETE FROM excluded_products WHERE category = ?", (category,))
    conn.commit()


def count_exclusions(conn: sqlite3.Connection, category: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM excluded_products WHERE category = ?", (category,)
    ).fetchone()[0]


def upsert_products(conn: sqlite3.Connection, products: list[ScoredProduct]) -> None:
    conn.executemany(
        """
        INSERT INTO products (
            store, category, raw_name, brand, price_chf, package_qty, package_unit,
            price_per_unit, url, barcode, nova_group, additives_tags,
            saturated_fat_per_100g, health_score, health_grade, scraped_at, store_raw, off_raw, off_barcode
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(store, category, raw_name, package_qty) DO UPDATE SET
            brand=excluded.brand,
            price_chf=excluded.price_chf,
            package_unit=excluded.package_unit,
            price_per_unit=excluded.price_per_unit,
            url=excluded.url,
            barcode=excluded.barcode,
            nova_group=excluded.nova_group,
            additives_tags=excluded.additives_tags,
            saturated_fat_per_100g=excluded.saturated_fat_per_100g,
            health_score=excluded.health_score,
            health_grade=excluded.health_grade,
            scraped_at=excluded.scraped_at,
            store_raw=excluded.store_raw,
            off_raw=excluded.off_raw,
            off_barcode=excluded.off_barcode
        """,
        [
            (
                p.store, p.category, p.raw_name, p.brand, p.price_chf,
                p.package_qty, p.package_unit, p.price_per_unit, p.url, p.barcode,
                p.nova_group, json.dumps(p.additives_tags) if p.additives_tags is not None else None,
                p.saturated_fat_per_100g, p.health_score, p.health_grade, p.scraped_at.isoformat(),
                json.dumps(p.store_raw) if p.store_raw is not None else None,
                json.dumps(p.off_raw) if p.off_raw is not None else None,
                p.off_barcode,
            )
            for p in products
        ],
    )
    conn.commit()

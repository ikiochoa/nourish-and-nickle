"""Copy the working DB to snapshot/pantry.db, the read-only copy the hosted app
serves. Run after a scrape, then commit and push snapshot/pantry.db - the
hosted app redeploys on push.

The scrapers can't run in the cloud (Migros needs a headed browser), so this
is how fresh prices get online.

The snapshot leaves out what visitors don't need:
- products hidden as not belonging to their category are dropped, not just
  flagged, since visitors can't unhide them anyway (the hide list itself is
  kept, so the scheduled cloud run, which starts from this snapshot, keeps
  honouring it);
- products a store no longer lists are dropped: anything not seen within
  STALE_AFTER_DAYS of the latest scrape of the same store and category. It is
  measured per store and category so that one skipped in a run (blocked, or
  needing a browser the cloud run doesn't have, or a --category run) keeps
  its last known prices instead of vanishing;
- store_raw (the raw store API response, ~80% of the DB) is cleared. Nothing
  in the app reads it.
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "pantry.db"
SNAPSHOT_PATH = ROOT / "snapshot" / "pantry.db"
STALE_AFTER_DAYS = 14


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"No working DB at {DB_PATH} - run the pipeline first.")

    SNAPSHOT_PATH.parent.mkdir(exist_ok=True)
    SNAPSHOT_PATH.unlink(missing_ok=True)

    # The backup API gives a consistent copy even if the app has the DB open.
    with sqlite3.connect(DB_PATH) as src, sqlite3.connect(SNAPSHOT_PATH) as dst:
        src.backup(dst)

    conn = sqlite3.connect(SNAPSHOT_PATH)
    conn.execute(
        """
        DELETE FROM products WHERE EXISTS (
            SELECT 1 FROM excluded_products e
            WHERE e.store = products.store AND e.category = products.category
              AND e.raw_name = products.raw_name
        )
        """
    )
    stale = conn.execute(
        """
        DELETE FROM products WHERE julianday(scraped_at) < (
            SELECT julianday(MAX(p.scraped_at)) - ? FROM products p
            WHERE p.store = products.store AND p.category = products.category
        )
        """,
        (STALE_AFTER_DAYS,),
    ).rowcount
    conn.execute("UPDATE products SET store_raw = NULL")
    conn.commit()
    conn.execute("VACUUM")

    total, rated, newest = conn.execute(
        "SELECT COUNT(*), COUNT(health_score), MAX(scraped_at) FROM products"
    ).fetchone()
    conn.close()

    size_kb = SNAPSHOT_PATH.stat().st_size // 1024
    print(f"Wrote {SNAPSHOT_PATH.relative_to(ROOT)} ({size_kb} KB): "
          f"{total} products, {rated} with a grade, newest scrape {newest}; "
          f"dropped {stale} no longer listed")
    print("Now commit and push it:  git add snapshot/pantry.db && git commit -m 'Refresh prices' && git push")


if __name__ == "__main__":
    main()

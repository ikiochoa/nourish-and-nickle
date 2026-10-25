"""Recompute health scores from data already stored in the DB.

Scoring rules change more often than the underlying facts do, and every input
the scorer needs (nova_group, additives_tags, saturated fat) is already cached
per product - so a rule change is a local recomputation, not a re-scrape.
"""
import json
import sqlite3

from swiss_pantry.health import scoring
from swiss_pantry.storage.db import get_connection

conn = get_connection()
rows = conn.execute(
    "SELECT id, nova_group, additives_tags, saturated_fat_per_100g, health_score, health_grade FROM products"
).fetchall()

updates = []
for r in rows:
    tags = json.loads(r["additives_tags"]) if r["additives_tags"] is not None else None
    score, grade = scoring.score_from_parts(r["nova_group"], tags, r["saturated_fat_per_100g"])
    if (score, grade) != (r["health_score"], r["health_grade"]):
        updates.append((score, grade, r["id"]))

conn.executemany("UPDATE products SET health_score=?, health_grade=? WHERE id=?", updates)
conn.commit()

now_rated = conn.execute("SELECT COUNT(*) FROM products WHERE health_score IS NOT NULL").fetchone()[0]
food = conn.execute("SELECT COUNT(*) FROM products WHERE category != 'toilet_paper'").fetchone()[0]
print(f"updated {len(updates)} rows; now rated: {now_rated}/{food} food products")
conn.close()

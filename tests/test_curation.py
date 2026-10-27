import json
import sqlite3

import httpx
import pandas as pd

from swiss_pantry.storage.curation import SqliteCuration, SupabaseCuration, apply_rules
from swiss_pantry.storage.db import EXCLUSIONS_SCHEMA


def test_apply_rules_drops_names_containing_a_keyword():
    df = pd.DataFrame({"raw_name": ["Bio Tofu Classic", "Tofu Burgers · Bio", "Tofu and Kale Burger"]})
    assert apply_rules(df, ["burger"])["raw_name"].tolist() == ["Bio Tofu Classic"]
    assert apply_rules(df, []).equals(df)


def test_sqlite_curation_round_trip():
    conn = sqlite3.connect(":memory:")
    conn.execute(EXCLUSIONS_SCHEMA)
    cur = SqliteCuration(conn)

    cur.hide("Migros", "tofu", "Tofu Skewers · Bio")
    cur.hide("Migros", "tofu", "Tofu Skewers · Bio")  # twice is fine
    cur.add_rule("tofu", "  Burger ")
    assert cur.hidden("tofu") == {("Migros", "Tofu Skewers · Bio")}
    assert cur.rules("tofu") == ["burger"]
    assert cur.hidden("quinoa") == set()

    cur.unhide("Migros", "tofu", "Tofu Skewers · Bio")
    cur.remove_rule("tofu", "burger")
    assert cur.hidden("tofu") == set()
    assert cur.rules("tofu") == []


def test_supabase_curation_sends_postgrest_requests():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET" and request.url.path.endswith("/excluded_products"):
            return httpx.Response(200, json=[{"store": "Otto's", "raw_name": "Gold Quinoa Shampoo"}])
        if request.method == "GET":
            return httpx.Response(200, json=[{"keyword": "shampoo"}])
        return httpx.Response(201)

    client = httpx.Client(base_url="https://x.supabase.co/rest/v1", transport=httpx.MockTransport(handler))
    cur = SupabaseCuration("https://x.supabase.co", "sb_secret_abc", client=client)

    assert cur.hidden("quinoa") == {("Otto's", "Gold Quinoa Shampoo")}
    assert cur.rules("quinoa") == ["shampoo"]
    cur.hide("Otto's", "quinoa", "Gold Quinoa Shampoo")
    cur.add_rule("quinoa", "Maske")
    cur.unhide_all("quinoa")

    hide, rule, unhide_all = seen[2:]
    assert hide.method == "POST" and hide.url.params["on_conflict"] == "store,category,raw_name"
    assert "ignore-duplicates" in hide.headers["Prefer"]
    assert json.loads(rule.content) == {"category": "quinoa", "keyword": "maske"}
    assert unhide_all.method == "DELETE" and unhide_all.url.params["category"] == "eq.quinoa"


def test_supabase_key_headers():
    jwt = SupabaseCuration("https://x.supabase.co", "eyJhbGciOi.legacy")
    new = SupabaseCuration("https://x.supabase.co", "sb_secret_abc")
    assert jwt.client.headers["Authorization"] == "Bearer eyJhbGciOi.legacy"
    assert "Authorization" not in new.client.headers and new.client.headers["apikey"] == "sb_secret_abc"

"""One-off: build config/additives_risk.json from Open Food Facts' additives
taxonomy, which bundles EFSA overexposure-risk evaluations and France's
ANSES "additives of interest" list - the same underlying sources Yuka's
additive risk rating draws from. Re-run this occasionally to pick up
taxonomy updates; the app reads the cached JSON, not this script.
"""
import json
import urllib.request
from pathlib import Path

TAXONOMY_URL = "https://static.openfoodfacts.org/data/taxonomies/additives.json"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "config" / "additives_risk.json"


def classify(entry: dict) -> str:
    efsa = entry.get("efsa_evaluation_overexposure_risk", {}).get("en")
    anses = entry.get("anses_additives_of_interest", {}).get("en")
    if efsa == "en:high" or anses == "yes":
        return "high"
    if efsa == "en:moderate":
        return "moderate"
    return "low"


def main() -> None:
    with urllib.request.urlopen(TAXONOMY_URL) as resp:
        taxonomy = json.load(resp)

    result = {}
    for tag, entry in taxonomy.items():
        if not tag.startswith("en:e"):
            continue
        name = entry.get("name", {}).get("en")
        result[tag] = {
            "name": name or tag,
            "risk": classify(entry),
        }

    OUTPUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    counts = {}
    for v in result.values():
        counts[v["risk"]] = counts.get(v["risk"], 0) + 1
    print(f"Wrote {len(result)} additives to {OUTPUT_PATH}")
    print("Risk distribution:", counts)


if __name__ == "__main__":
    main()

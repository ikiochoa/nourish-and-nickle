"""Run the pipeline for a single category id, appending to the existing DB."""
import sys

from swiss_pantry.pipeline import run

run(category_ids=[sys.argv[1]])

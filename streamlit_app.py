"""Entry point for Streamlit Community Cloud, which looks for this file at the
repo root by default. Running from here puts the repo root on the import path,
so `swiss_pantry` imports the same way it does under `python -m`."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parent / "swiss_pantry" / "app.py"), run_name="__main__")

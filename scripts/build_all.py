"""Rebuild every ParkSight artifact from the raw CSV, in order.

Usage:  python scripts/build_all.py
Requires the raw CSV in the project root (only needed to rebuild; the app ships
with precomputed artifacts and does not need this).
"""
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STEPS = [
    "parksight/etl/build_artifacts.py",
    "parksight/models/train_forecast.py",
    "parksight/reports/figures.py",
    "parksight/reports/make_deck.py",
    "parksight/reports/briefing.py",
]

for step in STEPS:
    print(f"\n{'='*60}\n▶ {step}\n{'='*60}")
    runpy.run_path(str(ROOT / step), run_name="__main__")

print("\n✅ All artifacts rebuilt.")

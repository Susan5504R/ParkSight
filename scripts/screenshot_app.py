"""Capture live screenshots of the running ParkSight app via Playwright.

Assumes the app is already serving on http://localhost:8501.
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "parksight" / "assets" / "screens"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://localhost:8505"

PAGES = [
    ("01_overview", "/"),
    ("02_hotspot_map", "/Hotspot_Map"),
    ("03_impact_pcis", "/Impact_PCIS"),
    ("04_forecast", "/Forecast"),
    ("05_prioritize", "/Prioritize"),
    ("06_simulator", "/Simulator"),
    ("07_copilot", "/Copilot"),
    ("08_offenders", "/Offenders"),
    ("09_about", "/About"),
    ("10_data_refresh", "/Data_Refresh"),
]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
            "--use-gl=angle", "--enable-webgl"])
        page = browser.new_page(viewport={"width": 1680, "height": 1050},
                                device_scale_factor=2)
        for name, path in PAGES:
            try:
                page.goto(BASE + path, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(9000)  # let charts/maps (WebGL tiles) render
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
                print(f"  captured {name}")
            except Exception as e:  # noqa: BLE001
                print(f"  FAILED {name}: {type(e).__name__} {str(e)[:120]}")
        browser.close()
    print("screens in", OUT)


if __name__ == "__main__":
    main()

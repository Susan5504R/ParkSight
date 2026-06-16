"""Headless smoke-test: run every Streamlit page via AppTest and report exceptions."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "parksight" / "app"
pages = [APP / "Home.py"] + sorted((APP / "pages").glob("*.py"))

failed = 0
for p in pages:
    try:
        at = AppTest.from_file(str(p), default_timeout=60).run()
        if at.exception:
            failed += 1
            print(f"❌ {p.name}: EXCEPTION")
            for ex in at.exception:
                print("    ", str(ex.value)[:300])
        else:
            n_charts = len(at.get("plotly_chart")) if hasattr(at, "get") else 0
            print(f"✅ {p.name}: ok  (errors={len(at.error)}, warnings={len(at.warning)})")
            for e in at.error:
                print("    error:", str(e.value)[:200])
    except Exception as e:  # noqa: BLE001
        failed += 1
        print(f"❌ {p.name}: RAISED {type(e).__name__}: {str(e)[:300]}")

print(f"\n{'ALL PAGES OK' if failed == 0 else f'{failed} PAGE(S) FAILED'}")
sys.exit(1 if failed else 0)

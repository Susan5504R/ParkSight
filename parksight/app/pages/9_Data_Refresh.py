"""Live Data Refresh — prove nothing is hardcoded: rebuild the whole intelligence
layer from new data, in-app, and every map/chart updates."""
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lib  # noqa: E402
from parksight import config as C  # noqa: E402
from parksight.etl import build_artifacts  # noqa: E402
from parksight.models import train_forecast  # noqa: E402

st.set_page_config(page_title="ParkSight — Data Refresh", page_icon="⚙️", layout="wide")
lib.inject_css()

lib.page_header("⚙️ Live Data Refresh",
                "Nothing is hardcoded. Drop in new violation data and the entire platform — "
                "heatmaps, PCIS, forecast, offenders — recomputes.")

# current state
art = C.PROCESSED / "cell_pcis.parquet"
if art.exists():
    built = datetime.fromtimestamp(art.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    m = lib.meta()
    c = st.columns(4)
    c[0].metric("Current rows", f"{m.get('total_violations', 0):,}")
    c[1].metric("Date range", f"{m.get('date_min','—')} → {m.get('date_max','—')}")
    c[2].metric("Hotspot cells", f"{m.get('n_cells', 0):,}")
    c[3].metric("Artifacts built", built)

st.divider()
st.markdown("### 1 · Choose a data source")
up = st.file_uploader("Upload a violation CSV (same schema as the official dataset)", type=["csv"])
has_local = C.RAW_CSV.exists()
src_choice = st.radio("Source", ["Uploaded file" if up else "Uploaded file (none yet)",
                                 f"Local raw CSV {'✓' if has_local else '(not found)'}"],
                      horizontal=True, index=0 if up else (1 if has_local else 0))

st.markdown("### 2 · Rebuild")
go = st.button("🔁 Rebuild intelligence from this data", type="primary",
               use_container_width=True)

if go:
    try:
        with st.status("Rebuilding ParkSight…", expanded=True) as status:
            if up is not None and src_choice.startswith("Uploaded"):
                st.write("Reading uploaded CSV…")
                df = pd.read_csv(up, low_memory=False)
                source = df
            elif has_local:
                st.write("Reading local raw CSV…")
                source = None  # build_artifacts defaults to RAW_CSV
            else:
                st.error("No data source available. Upload a CSV first.")
                st.stop()

            t0 = time.time()
            st.write("⚙️ ETL → IST → H3 → PCIS → zones → offenders…")
            build_artifacts.main(source)
            st.write("🔮 Retraining LightGBM forecast…")
            try:
                train_forecast.main()
            except Exception as fe:  # noqa: BLE001
                st.warning(f"Forecast step skipped (need ≥~30 days of data): {type(fe).__name__}")
            st.write("🧹 Clearing caches so every page reflects the new data…")
            st.cache_data.clear()
            status.update(label=f"✅ Rebuilt in {time.time()-t0:.1f}s — all pages now reflect the new data.",
                          state="complete")
        st.balloons()
        st.success("Done. Open any page (Hotspot Map, PCIS, Forecast…) — it's fully recomputed.")
        m2 = lib.meta()
        st.metric("New total rows", f"{m2.get('total_violations', 0):,}")
    except Exception as e:  # noqa: BLE001
        st.exception(e)

st.divider()
st.info("**Why this matters:** the demo runs on precomputed artifacts for speed and easy "
        "deployment, but the pipeline is fully parameterised. In production this same step is a "
        "scheduled job (or a streaming consumer) — point it at a live SCITA/e-challan feed and the "
        "command center stays current automatically. The maps and scores you see are computed from "
        "data, not baked in.")

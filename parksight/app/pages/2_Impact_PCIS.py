"""Congestion Impact Engine — explain PCIS and let judges re-weight it live."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lib  # noqa: E402
from parksight import config as C  # noqa: E402

st.set_page_config(page_title="ParkSight — Impact (PCIS)", page_icon="📊", layout="wide")
lib.inject_css()
if not lib.artifacts_exist():
    lib.no_data_warning()

lib.page_header("📊 Parking Congestion Impact Score (PCIS)",
                "Our proprietary, explainable metric — the answer to 'quantify impact on traffic flow'.")

st.markdown(r"""
The dataset has **no traffic-flow column**, so we model impact transparently from what
*does* drive congestion. For every zone:

$$PCIS = 100 \times (w_V\hat V + w_S\hat S + w_L\hat L + w_P\hat P + w_T\hat T)$$

| Term | Meaning | Intuition |
|---|---|---|
| **V̂** Volume | how many violations (log-scaled) | more illegal parking = more obstruction |
| **Ŝ** Severity | carriageway-blocking weight of violation types | main-road / double / footpath block moving lanes |
| **L̂** Location | junction & commercial-keyword criticality | a junction blockage cascades into gridlock |
| **P̂** Peak-overlap | share occurring in IST peak windows (08–11, 17–21) | a 6 PM block hurts more than a 3 AM one |
| **T̂** Trend | month-over-month growth | rising hotspots get prioritised early |
""")

st.divider()
st.markdown("### 🎛️ Tune the model (judges: try it live)")
grain = st.radio("Granularity", ["junction", "station", "hex (cell)"], horizontal=True)
fname = {"junction": "junction_pcis.parquet", "station": "station_pcis.parquet",
         "hex (cell)": "cell_pcis.parquet"}[grain]
namecol = {"junction": "junction_name", "station": "police_station",
           "hex (cell)": "h3_r9"}[grain]
df = lib.load(fname).copy()

cols = st.columns(5)
defaults = C.PCIS_WEIGHTS
wV = cols[0].slider("Volume wᵥ", 0.0, 1.0, defaults["V"], 0.05)
wS = cols[1].slider("Severity wₛ", 0.0, 1.0, defaults["S"], 0.05)
wL = cols[2].slider("Location wₗ", 0.0, 1.0, defaults["L"], 0.05)
wP = cols[3].slider("Peak wₚ", 0.0, 1.0, defaults["P"], 0.05)
wT = cols[4].slider("Trend wₜ", 0.0, 1.0, defaults["T"], 0.05)
tot = wV + wS + wL + wP + wT or 1.0
raw = (wV * df["V"] + wS * df["S"] + wL * df["L"] + wP * df["P"] + wT * df["T"]) / tot
lo, hi = raw.min(), raw.max()
df["PCIS_live"] = (100 * (raw - lo) / (hi - lo + 1e-9)).round(1)
df = df.sort_values("PCIS_live", ascending=False)

st.caption(f"Weights normalised to sum 1 (entered total = {tot:.2f}). Ranking updates instantly.")

a, b = st.columns([1.3, 1])
with a:
    top = df.head(15)
    fig = px.bar(top, x="PCIS_live", y=top[namecol], orientation="h",
                 color="PCIS_live", color_continuous_scale="Turbo",
                 labels={"PCIS_live": "PCIS", namecol: ""})
    fig.update_layout(yaxis=dict(autorange="reversed"), coloraxis_showscale=False)
    st.plotly_chart(lib.style_fig(fig, height=520, title=f"Top 15 {grain}s by live PCIS"),
                    use_container_width=True)
with b:
    show = df.head(15)[[namecol, "PCIS_live", "violations"]].copy()
    show.columns = [grain.title(), "PCIS", "Violations"]
    st.dataframe(show, hide_index=True, use_container_width=True,
                 column_config={"PCIS": st.column_config.ProgressColumn(
                     "PCIS", min_value=0, max_value=100, format="%.0f")})
    moved = (df[namecol].head(10).tolist() !=
             lib.load(fname).sort_values("PCIS", ascending=False)[namecol].head(10).tolist())
    st.info("⚖️ Re-weighting reshuffles priorities — proving PCIS is a transparent, "
            "auditable policy lever, not a black box." if moved else
            "These weights reproduce the default ranking.")
    exp = df[[namecol, "PCIS_live", "V", "S", "L", "P", "T", "violations"]].round(3)
    lib.df_download(exp, "⬇️ Export scored zones (CSV)", "parksight_pcis_scored.csv")

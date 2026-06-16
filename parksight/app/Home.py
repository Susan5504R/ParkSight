"""ParkSight — Executive Dashboard (app entry point)."""
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib  # noqa: E402

st.set_page_config(page_title="ParkSight — Parking Congestion Command Center",
                   page_icon=lib.FAVICON, layout="wide", initial_sidebar_state="expanded")
lib.inject_css()
lib.persist_state()  # keep other pages' widget values alive when passing through Home

with st.sidebar:
    _logo = lib.C.ASSETS / "logo.png"
    if _logo.exists():
        st.image(str(_logo), use_container_width=True)
    else:
        st.markdown("## 🅿️ ParkSight")
    st.caption("Bengaluru Traffic Command")
    st.divider()
    st.markdown("**Navigate** the modules above ↑")
    st.caption("Hotspot Map · PCIS · Forecast · Prioritize · Simulator · Copilot · Offenders")

if not lib.artifacts_exist():
    lib.no_data_warning()

m = lib.meta()
mx = lib.metrics()

st.markdown("# Parking-Congestion Command Center")
st.caption(f"Bengaluru Traffic Police · {m['total_violations']:,} violations · "
           f"{m['date_min']} → {m['date_max']} · {m['n_stations']} stations · {m['n_junctions']} junctions")

# ---- hero: the headline insight ----
st.markdown(
    f'<div class="ps-hero">🔦 <b>Key discovery — the Evening Enforcement Blind-Spot.</b> '
    f'Parking-violation records collapse during <b>{m.get("evening_trough_hours","IST 15:00–24:00")}</b>, '
    f'spanning the evening commercial-congestion peak. Low tickets here mean low '
    f'<i>enforcement visibility</i>, not fewer violations — this is the gap ParkSight closes.</div>',
    unsafe_allow_html=True)

# ---- KPI row ----
c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    lib.kpi("Total Violations", f"{m['total_violations']:,}", "Nov 2023 – Apr 2024")
with c2:
    lib.kpi("Active Hotspots", f"{m['n_hotspots']:,}", "High-impact H3 cells", "#F97316")
with c3:
    st_high = (lib.load("station_pcis.parquet")["tier"] == "High").sum()
    lib.kpi("High-Risk Zones", f"{int(st_high)}", "police-station level", "#EF4444")
with c4:
    lib.kpi("Repeat-Offender Share", f"{m['repeat_share']}%", "of all violations", "#FACC15")
with c5:
    lib.kpi("Carriageway-Blocking", f"{m['severe_share']}%", "main-road / junction / footpath", "#22D3EE")

st.write("")
left, right = st.columns([1.15, 1])

with left:
    st.markdown("#### 🗺️ City-wide parking-congestion hotspots (PCIS)")
    cell = lib.load("cell_pcis.parquet").sort_values("PCIS", ascending=False).head(900)
    st.pydeck_chart(lib.deck([lib.hex_layer(cell, elevation=False)], zoom=10.6),
                    use_container_width=True)
    st.caption("Hex colour = Parking Congestion Impact Score (cyan→red). "
               "Open **Hotspot Map** for layers, time-lapse and zone drill-down.")

with right:
    st.markdown("#### ⏰ When violations happen (IST)")
    st.plotly_chart(lib.hourly_curve(), use_container_width=True)
    st.markdown("#### 📈 Monthly trend")
    mt = lib.load("monthly_trend.parquet")
    fig = px.bar(mt, x="month", y="n", color_discrete_sequence=["#6366F1"])
    st.plotly_chart(lib.style_fig(fig, height=200), use_container_width=True)

st.write("")
b1, b2 = st.columns([1.4, 1])
with b1:
    st.markdown("#### 🎯 Top priority enforcement zones (junctions)")
    j = lib.load("junction_pcis.parquet").sort_values("PCIS", ascending=False).head(8)
    show = j[["rank", "junction_name", "PCIS", "violations", "tier", "reason"]].copy()
    show.columns = ["#", "Junction", "PCIS", "Violations", "Tier", "Why it ranks high"]
    st.dataframe(show, hide_index=True, use_container_width=True,
                 column_config={"PCIS": st.column_config.ProgressColumn(
                     "PCIS", min_value=0, max_value=100, format="%.0f")})
with b2:
    st.markdown("#### 🚗 Violations by vehicle type")
    vm = lib.load("vehicle_mix.parquet").head(8)
    fig = px.bar(vm, x="n", y="vehicle_type", orientation="h",
                 color="n", color_continuous_scale="Magma")
    fig.update_layout(coloraxis_showscale=False, yaxis=dict(autorange="reversed"))
    st.plotly_chart(lib.style_fig(fig, height=320), use_container_width=True)

st.divider()
g1, g2, g3 = st.columns(3)
g1.metric("Forecast model MAE", mx.get("mae_model", "—"),
          f"{mx.get('improvement_pct', 0)}% better than baseline", delta_color="inverse")
g2.metric("Distinct enforcement devices", f"{m.get('n_devices', 0):,}")
g3.metric("Top hotspot station", m.get("top_station", "—"))
st.caption("PCIS = Parking Congestion Impact Score = 100·(0.30·Volume + 0.20·Severity + "
           "0.20·Location + 0.20·PeakOverlap + 0.10·Trend). A decision-support index, not "
           "automated enforcement. Built on the official violation dataset only.")

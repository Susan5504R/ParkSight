"""AI Hotspot Map — interactive PCIS hexes, raw density, DBSCAN zones, time filter."""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lib  # noqa: E402

st.set_page_config(page_title="ParkSight — Hotspot Map", page_icon="🗺️", layout="wide")
lib.inject_css()
lib.common_sidebar()
if not lib.artifacts_exist():
    lib.no_data_warning()

lib.page_header("🗺️ AI Hotspot Map",
                "Where illegal parking chokes the city — coloured by Parking Congestion Impact Score.")

cell = lib.load("cell_pcis.parquet")
zones = lib.load("zones.parquet")

# Pre-initialize session state so values survive page navigation
if "map_layers"     not in st.session_state: st.session_state["map_layers"]     = ["PCIS hotspots"]
if "map_min_pcis"   not in st.session_state: st.session_state["map_min_pcis"]   = 0
if "map_hour_range" not in st.session_state: st.session_state["map_hour_range"] = (0, 23)
if "map_extruded"   not in st.session_state: st.session_state["map_extruded"]   = True

ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1.4, 1, 1, 1])
layers_on  = ctrl1.multiselect("Map layers",
                               ["PCIS hotspots", "Raw violations (by time)", "DBSCAN zones"],
                               key="map_layers")
min_pcis   = ctrl2.slider("Min PCIS", 0, 100, step=5, key="map_min_pcis")
hour_range = ctrl3.slider("IST hour window", 0, 23, key="map_hour_range")
extruded   = ctrl4.toggle("3-D columns", key="map_extruded")

layers = []
tooltip = {"text": "PCIS {PCIS}"}

if "PCIS hotspots" in layers_on:
    sub = cell[cell["PCIS"] >= min_pcis].sort_values("PCIS", ascending=False).head(1200)
    layers.append(lib.hex_layer(sub, elevation=extruded))

if "Raw violations (by time)" in layers_on:
    v = lib.load("violations_clean.parquet")
    v = v[(v["hour"] >= hour_range[0]) & (v["hour"] <= hour_range[1])]
    dens = (v.groupby("h3_r9").size().reset_index(name="count"))
    dens = dens.merge(cell[["h3_r9", "lat", "lon"]], on="h3_r9", how="left")
    mx = dens["count"].max() or 1
    dens["PCIS"] = (100 * dens["count"] / mx).round(1)
    dens = lib.add_colors(dens.sort_values("count", ascending=False).head(1500))
    layers.append(pdk.Layer("H3HexagonLayer", data=dens, get_hexagon="h3_r9",
                            get_fill_color="[r,g,b,a]", pickable=True, extruded=False))
    tooltip = {"text": "violations {count}"}

if "DBSCAN zones" in layers_on:
    z = lib.add_colors(zones.copy())
    layers.append(pdk.Layer("ScatterplotLayer", data=z, get_position="[lon, lat]",
                            get_radius="violations / 8 + 80", get_fill_color="[r,g,b,200]",
                            pickable=True, stroked=True, get_line_color=[255, 255, 255]))
    tooltip = {"text": "{name}\nPCIS {PCIS} · {violations} violations"}

if not layers:
    st.info("Select at least one map layer.")
else:
    st.pydeck_chart(lib.deck(layers, zoom=10.6, pitch=40 if extruded else 0,
                             tooltip=tooltip), use_container_width=True)

st.divider()
st.markdown("### 🔎 Zone drill-down")
jun = lib.load("junction_pcis.parquet").sort_values("PCIS", ascending=False)
pick = st.selectbox("Inspect a junction hotspot",
                    jun["junction_name"].tolist(), key="map_junction")
row = jun[jun["junction_name"] == pick].iloc[0]

d1, d2 = st.columns([1, 1.2])
with d1:
    st.markdown(f"#### {pick}")
    st.markdown(f"{lib.tier_badge(str(row['tier']))} &nbsp; **PCIS {row['PCIS']:.0f}** · "
                f"rank #{int(row['rank'])} of {len(jun)}", unsafe_allow_html=True)
    cc = st.columns(3)
    cc[0].metric("Violations", f"{int(row['violations']):,}")
    cc[1].metric("Peak hour (IST)", f"{int(row['peak_hour']):02d}:00")
    cc[2].metric("Top violation", row["top_type"])
    st.info(f"**Why it ranks high:** {row['reason']}")
    units = max(1, round(row["PCIS"] / 100 * 3))
    st.success(f"**Recommendation:** deploy ~{units} patrol unit(s) during the "
               f"{int(row['peak_hour']):02d}:00 window; prioritise carriageway-blocking violations.")
with d2:
    comp = pd.DataFrame({
        "Component": ["Volume", "Severity", "Location", "Peak-overlap", "Trend"],
        "Value": [row["V"], row["S"], row["L"], row["P"], row["T"]]})
    fig = go.Figure(go.Bar(x=comp["Value"], y=comp["Component"], orientation="h",
                           marker_color=["#6366F1", "#EF4444", "#22D3EE", "#F97316", "#FACC15"]))
    fig.update_xaxes(range=[0, 1], title="Normalised component (0–1)")
    st.plotly_chart(lib.style_fig(fig, height=300, title="PCIS component breakdown"),
                    use_container_width=True)

st.divider()
with st.expander("📽️  Month-by-month time-lapse — watch hotspots evolve", expanded=False):
    st.caption("Press ▶ on the player. Density of parking violations across Bengaluru, "
               "Nov 2023 → Apr 2024 (IST).")
    st.plotly_chart(lib.timelapse_fig(), use_container_width=True)

"""Chronic-Offender Watchlist — 15% of vehicles drive 34% of violations."""
import sys
from pathlib import Path

import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lib  # noqa: E402

st.set_page_config(page_title="ParkSight — Offenders", page_icon="🚨", layout="wide")
lib.inject_css()
lib.common_sidebar()
if not lib.artifacts_exist():
    lib.no_data_warning()

m = lib.meta()
off = lib.load("offenders.parquet")

lib.page_header("🚨 Chronic-Offender Watchlist",
                "Repeat offenders are a small, targetable slice of the problem.")

k = st.columns(4)
k[0].metric("Repeat-offender share", f"{m['repeat_share']}%", "of all violations")
k[1].metric("Repeat vehicles", f"{len(off):,}")
k[2].metric("Worst single vehicle", f"{int(off['violations'].max())}", "violations")
k[3].metric("Vehicles with 11+", f"{int((off['violations'] >= 11).sum()):,}")

st.divider()
if "off_min_v" not in st.session_state: st.session_state["off_min_v"] = 5
if "off_area"  not in st.session_state: st.session_state["off_area"]  = ""
if "off_n"     not in st.session_state: st.session_state["off_n"]     = 40

c1, c2, c3 = st.columns([1, 1, 1])
min_v = c1.slider("Min violations", 2, int(off["violations"].max()), step=1, key="off_min_v")
area  = c2.text_input("Filter by station/junction contains", key="off_area")
n     = c3.slider("Show top N", 10, 200, step=10, key="off_n")

f = off[off["violations"] >= min_v]
if area.strip():
    f = f[f["top_station"].str.contains(area, case=False, na=False) |
          f["top_junction"].str.contains(area, case=False, na=False)]
f = f.sort_values("violations", ascending=False).head(n)

a, b = st.columns([1.2, 1])
with a:
    show = f[["rank", "vehicle_number", "vehicle_type", "violations", "severe_n",
              "top_station", "last_seen"]].copy()
    show.columns = ["#", "Vehicle", "Type", "Violations", "Severe", "Top station", "Last seen"]
    st.dataframe(show, hide_index=True, use_container_width=True, height=460)
    lib.df_download(f[["vehicle_number", "vehicle_type", "violations", "severe_n",
                       "top_station", "top_junction", "last_seen"]],
                    "⬇️ Export watchlist (CSV)", "parksight_offender_watchlist.csv")
with b:
    layer = pdk.Layer("ScatterplotLayer", data=f, get_position="[lon, lat]",
                      get_radius="violations * 4 + 60", get_fill_color=[239, 68, 68, 150],
                      pickable=True)
    st.pydeck_chart(lib.deck([layer], zoom=10.4,
                    tooltip={"text": "{vehicle_number}\n{violations} violations · {top_station}"}),
                    use_container_width=True)
    st.caption("Hotspots of chronic offenders — candidates for targeted notices / towing.")

st.info(f"**Insight:** {m['repeat_share']}% of all violations come from repeat offenders. "
        "A focused notice/tow programme on this watchlist attacks a third of the problem "
        "with a fraction of the effort.")

"""Shared helpers for the ParkSight Streamlit app: data loaders, theme, maps."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from parksight import config as C  # noqa: E402

# ---------------------------------------------------------------- theme
ACCENT = "#6366F1"
RISK_RAMP = [(0, (34, 211, 238)), (40, (250, 204, 21)),
             (66, (249, 115, 22)), (100, (239, 68, 68))]


def inject_css():
    st.markdown("""
    <style>
      .stApp { background: #0B0F1A; }
      section[data-testid="stSidebar"] { background: #0E1422; border-right: 1px solid #1F2937; }
      h1,h2,h3 { color:#F8FAFC; letter-spacing:-0.01em; }
      .ps-kpi { background:linear-gradient(160deg,#161D2E,#10182A); border:1px solid #243049;
                border-radius:14px; padding:16px 18px; height:100%; }
      .ps-kpi .v { font-size:30px; font-weight:700; color:#F8FAFC; line-height:1.1; }
      .ps-kpi .l { font-size:12px; color:#94A3B8; text-transform:uppercase; letter-spacing:.06em; }
      .ps-kpi .d { font-size:12px; margin-top:4px; }
      .ps-badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:600; }
      .ps-hero { background:linear-gradient(135deg,#3B1D6E33,#6366F133); border:1px solid #6366F155;
                 border-radius:16px; padding:18px 22px; margin-bottom:8px; }
      .tier-High{background:#7f1d1d;color:#fecaca;} .tier-Medium{background:#78350f;color:#fed7aa;}
      .tier-Low{background:#064e3b;color:#a7f3d0;}
      .block-container{padding-top:2rem;}
    </style>""", unsafe_allow_html=True)


def kpi(label, value, delta="", color="#F8FAFC"):
    d = f'<div class="d" style="color:{color}">{delta}</div>' if delta else ""
    st.markdown(f'<div class="ps-kpi"><div class="l">{label}</div>'
                f'<div class="v">{value}</div>{d}</div>', unsafe_allow_html=True)


def tier_badge(tier):
    return f'<span class="ps-badge tier-{tier}">{tier}</span>'


def pcis_color(v, alpha=170):
    v = max(0, min(100, float(v)))
    for i in range(len(RISK_RAMP) - 1):
        x0, c0 = RISK_RAMP[i]; x1, c1 = RISK_RAMP[i + 1]
        if x0 <= v <= x1:
            t = (v - x0) / (x1 - x0 + 1e-9)
            return [int(c0[j] + t * (c1[j] - c0[j])) for j in range(3)] + [alpha]
    return list(RISK_RAMP[-1][1]) + [alpha]


# ---------------------------------------------------------------- loaders
@st.cache_data(show_spinner=False)
def load(name):
    p = C.PROCESSED / name
    if p.suffix == ".json":
        return json.loads(p.read_text())
    return pd.read_parquet(p)


@st.cache_data(show_spinner=False)
def meta():
    p = C.PROCESSED / "meta.json"
    return json.loads(p.read_text()) if p.exists() else {}


@st.cache_data(show_spinner=False)
def metrics():
    p = C.MODELS.parent / "metrics.json"
    return json.loads(p.read_text()) if p.exists() else {}


def artifacts_exist():
    return (C.PROCESSED / "cell_pcis.parquet").exists()


def add_colors(df, col="PCIS"):
    cols = df[col].apply(pcis_color)
    df = df.copy()
    df["r"] = cols.apply(lambda c: c[0]); df["g"] = cols.apply(lambda c: c[1])
    df["b"] = cols.apply(lambda c: c[2]); df["a"] = cols.apply(lambda c: c[3])
    return df


def hex_layer(df, hexcol="h3_r9", elevation=False):
    import pydeck as pdk
    df = add_colors(df)
    return pdk.Layer(
        "H3HexagonLayer", data=df, get_hexagon=hexcol, pickable=True,
        stroked=False, filled=True, extruded=elevation,
        get_elevation="PCIS * 12" if elevation else 0, elevation_scale=1,
        get_fill_color="[r,g,b,a]", auto_highlight=True,
    )


def scatter_layer(df, get_radius=60, color=(99, 102, 241, 140)):
    import pydeck as pdk
    return pdk.Layer(
        "ScatterplotLayer", data=df, get_position="[lon, lat]",
        get_radius=get_radius, get_fill_color=list(color), pickable=True,
    )


def deck(layers, lat=12.97, lon=77.59, zoom=10.7, pitch=0, tooltip=None):
    import pydeck as pdk
    return pdk.Deck(
        map_style="dark",
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon,
                                         zoom=zoom, pitch=pitch),
        layers=layers, tooltip=tooltip or {"text": "PCIS {PCIS}"},
    )


def page_header(title, subtitle=""):
    st.markdown(f"## {title}")
    if subtitle:
        st.caption(subtitle)


def no_data_warning():
    st.error("Analytics artifacts not found. Run the ETL first:\n\n"
             "```\npython parksight/etl/build_artifacts.py\n"
             "python parksight/models/train_forecast.py\n```")
    st.stop()


# ---------------------------------------------------------------- charts
def style_fig(fig, height=300, title=None):
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", height=height,
        margin=dict(l=10, r=10, t=40 if title else 16, b=10),
        # explicit text avoids Plotly rendering a None title as the literal "undefined"
        title=dict(text=title or "", x=0.01, xanchor="left",
                   font=dict(size=14, color="#F8FAFC")),
        font=dict(color="#CBD5E1", size=12),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor="#1F2937", zeroline=False)
    fig.update_yaxes(gridcolor="#1F2937", zeroline=False)
    return fig


WEEK_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
              "Saturday", "Sunday"]


@st.cache_data(show_spinner=False)
def timelapse_fig():
    """Animated month-by-month parking-density map (no map token needed)."""
    import plotly.express as px
    v = load("violations_clean.parquet")
    agg = (v.groupby(["month", "h3_r9"])
             .agg(n=("id", "size"), lat=("latitude", "mean"), lon=("longitude", "mean"))
             .reset_index().sort_values("month"))
    fig = px.density_mapbox(
        agg, lat="lat", lon="lon", z="n", radius=16, animation_frame="month",
        center=dict(lat=12.97, lon=77.59), zoom=10.2,
        mapbox_style="carto-darkmatter", color_continuous_scale="Inferno",
        range_color=[0, agg["n"].quantile(0.985)])
    fig.update_layout(height=560, margin=dict(l=0, r=0, t=10, b=0),
                      paper_bgcolor="rgba(0,0,0,0)", coloraxis_colorbar_title="viol.")
    return fig


def df_download(df, label, filename):
    st.download_button(label, df.to_csv(index=False).encode(), file_name=filename,
                       mime="text/csv", use_container_width=True)


def hourly_curve():
    """IST hour-of-day violation curve highlighting the evening blind-spot."""
    import plotly.graph_objects as go
    hp = load("hourly_profile.parquet")
    by_hour = hp.groupby("hour")["n"].sum().reindex(range(24), fill_value=0)
    x0, x1 = blind_spot_band(by_hour)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(range(24)), y=by_hour.values, mode="lines",
                             line=dict(color="#6366F1", width=3), fill="tozeroy",
                             fillcolor="rgba(99,102,241,0.18)", name="Violations"))
    fig.add_vrect(x0=x0, x1=x1, fillcolor="#EF4444", opacity=0.12, line_width=0,
                  annotation_text=f"Enforcement blind-spot (IST {x0:02d}:00–{x1:02d}:00)",
                  annotation_position="top left", annotation_font_color="#FCA5A5")
    fig.update_xaxes(title="Hour of day (IST)", dtick=2, range=[-0.5, 23.5])
    fig.update_yaxes(title="Violations recorded")
    return style_fig(fig, height=300)


def exposure_divergence_fig():
    """Enforcement exposure vs external congestion prior, by IST hour.

    The shaded gap in the evening is the selection bias the de-biasing engine
    corrects: congestion is maxed while enforcement (and therefore tickets) is
    near-zero — so raw counts can't be trusted there."""
    import plotly.graph_objects as go
    ex = load("enforcement_exposure.parquet")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ex["hour"], y=ex["synthetic_congestion"], mode="lines",
        line=dict(color="#F97316", width=3), name="Congestion prior (external)",
        fill="tozeroy", fillcolor="rgba(249,115,22,0.10)"))
    fig.add_trace(go.Scatter(
        x=ex["hour"], y=ex["exposure"], mode="lines",
        line=dict(color="#22D3EE", width=3), name="Enforcement exposure (devices)",
        fill="tozeroy", fillcolor="rgba(34,211,238,0.12)"))
    fig.add_vrect(x0=17, x1=21, fillcolor="#EF4444", opacity=0.10, line_width=0,
                  annotation_text="Blind spot: high congestion, ~0 enforcement",
                  annotation_position="top left", annotation_font_color="#FCA5A5")
    fig.update_xaxes(title="Hour of day (IST)", dtick=2, range=[-0.5, 23.5])
    fig.update_yaxes(title="Normalised (0–1)", range=[0, 1.05])
    fig.update_layout(legend=dict(orientation="h", y=1.12, x=0))
    return style_fig(fig, height=320)


def blind_spot_band(by_hour):
    """Data-driven afternoon/evening low-enforcement window (contiguous, hour ≥ 12)."""
    thresh = 0.15 * float(by_hour.max())
    low = [h for h in range(12, 24) if float(by_hour[h]) < thresh]
    return (min(low), max(low) + 1) if low else (14, 21)


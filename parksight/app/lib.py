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
# Browser-tab favicon: the ParkSight icon mark (falls back to emoji if missing).
_FAVICON_PATH = C.ASSETS / "favicon.png"
FAVICON = str(_FAVICON_PATH) if _FAVICON_PATH.exists() else "🅿️"
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


# Prefixes of the page-state keys we OWN and want to survive multipage navigation.
# persist_state only ever self-assigns these — never a button, download_button,
# text_input, chat, or any Streamlit-internal key. This is an explicit allowlist
# (not a blocklist) so newer Streamlit versions, which forbid self-writing command
# widget keys (raising StreamlitValueAssignmentNotAllowedError), can never be tripped
# by a key we didn't anticipate.
_PERSIST_PREFIXES = ("pri_", "map_", "pcis_", "fc_", "sim_", "off_", "_pk_")


def persist_state():
    """Keep our page-state alive across multipage navigation.

    Streamlit garbage-collects a widget's key from session_state on any run where
    that widget isn't rendered (i.e. when you're on another page). Re-assigning each
    key to itself marks it 'active' for the current run so it survives. We restrict
    this to keys we own (see ``_PERSIST_PREFIXES``); transient command widgets such
    as buttons are intentionally NOT persisted (they're momentary) and must never be
    self-written, or newer Streamlit raises StreamlitValueAssignmentNotAllowedError.
    MUST run before any widget on the page is instantiated (called from
    common_sidebar / Home, near the top)."""
    for k in list(st.session_state.keys()):
        if not k.startswith(_PERSIST_PREFIXES):
            continue
        try:
            st.session_state[k] = st.session_state[k]
        except Exception:  # noqa: BLE001 — some widget types disallow re-assignment
            pass


def common_sidebar():
    """Render API key inputs in sidebar on every page; persist keys across navigation."""
    import os
    persist_state()
    # Restore os.environ from session state (set on a previous page)
    if st.session_state.get("_pk_anthropic"):
        os.environ["ANTHROPIC_API_KEY"] = st.session_state["_pk_anthropic"]
    if st.session_state.get("_pk_gemini"):
        os.environ["GOOGLE_API_KEY"] = st.session_state["_pk_gemini"]

    has_claude = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_gemini = bool(os.environ.get("GOOGLE_API_KEY"))

    with st.sidebar:
        st.markdown("---")
        st.markdown("#### 🔑 AI Copilot Keys *(optional)*")
        st.caption("Session-only — never stored.")
        if not has_claude:
            val = st.text_input("Anthropic API Key", type="password",
                                placeholder="sk-ant-...", key="_anthro_input")
            if val:
                st.session_state["_pk_anthropic"] = val
                os.environ["ANTHROPIC_API_KEY"] = val
                has_claude = True
        else:
            st.success("Claude active ✓", icon="🔑")
        if not has_claude and not has_gemini:
            val = st.text_input("Google Gemini Key", type="password",
                                placeholder="AIza...", key="_gemini_input")
            if val:
                st.session_state["_pk_gemini"] = val
                os.environ["GOOGLE_API_KEY"] = val
                has_gemini = True
        elif has_gemini and not has_claude:
            st.success("Gemini active ✓", icon="🔑")

    return has_claude, has_gemini


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


# ---------------------------------------------------------------- PCIS scoring
def pcis_recompute(df, weights):
    """Re-score a pre-aggregated PCIS frame for an arbitrary weight vector.

    `df` already holds per-zone V/S/L/P/T components (built once by the ETL and
    cached), so this is a cheap vectorised weighted sum — NOT a re-group of the
    raw 298k violations. `weights` is a dict V/S/L/P/T; it is normalised to a
    convex combination (sum=1) so the score can never exceed the component scale,
    then min-max stretched to a 0–100 display range. Returns (scored_df, norm)
    where `norm` is the normalised weight dict actually applied."""
    tot = sum(max(0.0, float(weights[k])) for k in "VSLPT") or 1.0
    norm = {k: max(0.0, float(weights[k])) / tot for k in "VSLPT"}
    raw = sum(norm[k] * df[k] for k in "VSLPT")
    lo, hi = raw.min(), raw.max()
    out = df.copy()
    out["PCIS_live"] = (100 * (raw - lo) / (hi - lo + 1e-9)).round(1)
    return out.sort_values("PCIS_live", ascending=False), norm


@st.cache_data(show_spinner=False)
def _anchor_rows():
    """Resolve the expert ground-truth anchors to their junction rows once.

    Matched on the stable BTP code embedded in `junction_name`, so a rename or a
    re-ranking of the junctions can't silently break the validation set."""
    j = load("junction_pcis.parquet")
    rows = []
    for code, label, tier, exp_rank in C.PCIS_GROUND_TRUTH:
        hit = j[j["junction_name"].str.contains(code, na=False)]
        if len(hit):
            r = hit.iloc[0]
            rows.append({"code": code, "label": label, "tier": tier,
                         "expert_rank": exp_rank, "junction_name": r["junction_name"],
                         **{k: float(r[k]) for k in "VSLPT"}})
    return pd.DataFrame(rows)


def ground_truth_alignment(weights):
    """Spearman ρ between the live PCIS ranking and the expert anchor ordering.

    Recomputed on every weight change so the page can show how re-weighting moves
    the formula toward (or away from) the human-known congestion ordering. Returns
    (rho, detail_df) — detail_df carries each anchor's expert vs. model rank."""
    from scipy.stats import spearmanr
    a = _anchor_rows()
    if len(a) < 3:
        return float("nan"), a
    scored, _ = pcis_recompute(a, weights)
    scored["model_rank"] = scored["PCIS_live"].rank(ascending=False, method="min")
    scored = scored.sort_values("expert_rank")
    rho, _ = spearmanr(scored["expert_rank"], scored["model_rank"])
    return float(rho), scored


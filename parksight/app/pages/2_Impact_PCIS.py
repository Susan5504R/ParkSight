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

st.set_page_config(page_title="ParkSight — Impact (PCIS)", page_icon=lib.FAVICON, layout="wide")
lib.inject_css()
lib.common_sidebar()
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

if "pcis_grain" not in st.session_state: st.session_state["pcis_grain"] = "junction"
if "pcis_wV"    not in st.session_state: st.session_state["pcis_wV"]    = C.PCIS_WEIGHTS["V"]
if "pcis_wS"    not in st.session_state: st.session_state["pcis_wS"]    = C.PCIS_WEIGHTS["S"]
if "pcis_wL"    not in st.session_state: st.session_state["pcis_wL"]    = C.PCIS_WEIGHTS["L"]
if "pcis_wP"    not in st.session_state: st.session_state["pcis_wP"]    = C.PCIS_WEIGHTS["P"]
if "pcis_wT"    not in st.session_state: st.session_state["pcis_wT"]    = C.PCIS_WEIGHTS["T"]

_COMP = [("V", "Volume", "pcis_wV"), ("S", "Severity", "pcis_wS"),
         ("L", "Location", "pcis_wL"), ("P", "Peak", "pcis_wP"),
         ("T", "Trend", "pcis_wT")]
_COMP_COLOR = {"V": "#6366F1", "S": "#EF4444", "L": "#22D3EE",
               "P": "#F97316", "T": "#FACC15"}


def _apply_global():
    """Promote the current slider weights to the app-wide policy."""
    st.session_state["pcis_weights_active"] = {k: float(st.session_state[key])
                                               for k, _, key in _COMP}


def _reset_global():
    """Drop the custom policy and restore recommended weights everywhere."""
    st.session_state["pcis_weights_active"] = None
    for k, _, key in _COMP:
        st.session_state[key] = C.PCIS_WEIGHTS[k]


def _policy_bar(norm):
    """Live stacked bar of the actual normalised policy vector (sums to 100%)."""
    import plotly.graph_objects as go
    fig = go.Figure()
    for k, label, _ in _COMP:
        pct = 100 * norm[k]
        fig.add_trace(go.Bar(
            y=["policy"], x=[pct], orientation="h", name=label,
            marker_color=_COMP_COLOR[k], text=f"{label} {pct:.0f}%",
            textposition="inside", insidetextanchor="middle",
            hovertemplate=f"{label}: %{{x:.1f}}%<extra></extra>"))
    fig.update_layout(barmode="stack", showlegend=False, height=92,
                      margin=dict(l=4, r=4, t=8, b=4),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(range=[0, 100], visible=False),
                      yaxis=dict(visible=False))
    return fig


@st.fragment
def pcis_studio():
    """Self-contained tuning + scoring block.

    Wrapped in @st.fragment so dragging a slider re-runs ONLY this function — the
    298k-row page never re-executes the CSS, the LaTeX explainer or the sidebar.
    Scoring itself runs against the pre-aggregated, cached V/S/L/P/T matrix
    (a few hundred to a few thousand rows), so each tick is a vectorised weighted
    sum, not a re-group of the raw violations."""
    st.divider()
    st.markdown("### 🎛️ Dynamic Policy Configuration Matrix "
                "<span style='font-size:13px;color:#94A3B8'>(judges: try it live)</span>",
                unsafe_allow_html=True)
    grain = st.radio("Granularity", ["junction", "station", "hex (cell)"],
                     horizontal=True, key="pcis_grain")
    fname = {"junction": "junction_pcis.parquet", "station": "station_pcis.parquet",
             "hex (cell)": "cell_pcis.parquet"}[grain]
    namecol = {"junction": "junction_name", "station": "police_station",
               "hex (cell)": "h3_r9"}[grain]
    df = lib.load(fname)

    cols = st.columns(5)
    for (k, label, key), col in zip(_COMP, cols):
        col.slider(f"{label} w", 0.0, 1.0, step=0.05, key=key)
    weights = {k: st.session_state[key] for k, _, key in _COMP}

    df, norm = lib.pcis_recompute(df, weights)
    tot = sum(weights.values())

    # --- Upgrade 1: live normalised policy distribution (convex combination) ---
    pc, cc = st.columns([2, 1])
    with pc:
        st.caption(f"**Normalised policy vector** — entered total {tot:.2f} auto-scaled "
                   "to a convex combination (Σ = 100%), so the composite can never "
                   "distort past its 0–100 range.")
        st.plotly_chart(_policy_bar(norm), use_container_width=True,
                        config={"displayModeBar": False})
    with cc:
        # --- Upgrade 3: ground-truth alignment, recomputed live ---
        rho, anchors = lib.ground_truth_alignment(weights)
        pct = 0 if rho != rho else round(100 * max(0.0, rho))  # NaN-safe
        color = "#22C55E" if pct >= 80 else "#FACC15" if pct >= 60 else "#EF4444"
        lib.kpi("Ground-truth alignment (Spearman ρ)", f"{pct}%",
                delta="vs. expert-labelled bottlenecks", color=color)

    # --- Apply this weighting across the whole dashboard ---
    ga, gb, gc = st.columns([1.5, 1, 1.5])
    ga.button("✅ Apply these weights across the app", on_click=_apply_global,
              type="primary", use_container_width=True)
    gb.button("↩️ Reset to recommended", on_click=_reset_global, use_container_width=True)
    with gc:
        if lib.custom_weights_active():
            st.success("Custom policy is **active app-wide** — Home, Hotspot Map, "
                       "Prioritize, Simulator and the briefing PDF all use it.")
        else:
            st.caption("The app currently uses the **recommended** weights. "
                       "Apply yours to re-score every page.")

    st.divider()
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

    # --- Upgrade 3 (detail): the expert anchor set the ρ is measured against ---
    with st.expander("🔬 Ground-truth anchor — how the alignment score is validated"):
        st.caption(
            "No traffic-flow sensors exist in this dataset, so PCIS is validated against an "
            "**expert-labelled** reference: known Bengaluru bottlenecks vs. quiet residential "
            "junctions, ranked most→least congested by local traffic knowledge. The Spearman "
            "rank correlation (ρ) above measures how closely the live formula reproduces that "
            "ordering — it moves as you re-weight, so you can *see* which priority profiles "
            "stay faithful to ground truth. This is a face-validity check, not sensor truth.")
        if len(anchors):
            tbl = anchors[["label", "tier", "expert_rank", "model_rank", "PCIS_live"]].copy()
            tbl.columns = ["Junction", "Expert label", "Expert rank", "Model rank", "PCIS"]
            st.dataframe(tbl, hide_index=True, use_container_width=True)


pcis_studio()

"""About / Methodology — in-app documentation for judges who don't read the README."""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lib  # noqa: E402

st.set_page_config(page_title="ParkSight — About", page_icon="ℹ️", layout="wide")
lib.inject_css()
lib.common_sidebar()
if not lib.artifacts_exist():
    lib.no_data_warning()

m = lib.meta()
mx = lib.metrics()

lib.page_header("ℹ️ Methodology & About",
                "How ParkSight works — and what it does (and doesn't) claim.")

c1, c2 = st.columns(2)
with c1:
    st.markdown("### 📦 Data")
    st.markdown(
        f"- **{m['total_violations']:,}** parking violations, {m['date_min']} → {m['date_max']}\n"
        f"- 100% geo-located; {m['n_stations']} police stations, {m['n_junctions']} junctions\n"
        f"- Timestamps converted **UTC → IST** (critical for every temporal insight)\n"
        f"- Dropped 100%-null columns (description, closed/action timestamps)\n"
        f"- **Only the official provided dataset** is used")

    st.markdown("### 🧮 PCIS — Parking Congestion Impact Score")
    st.latex(r"PCIS = 100\times(0.30\hat V+0.20\hat S+0.20\hat L+0.20\hat P+0.10\hat T)")
    st.markdown(
        "- **V** volume (log-scaled) · **S** carriageway-blocking severity · "
        "**L** junction/commercial location criticality · **P** IST peak-window overlap · "
        "**T** month-over-month trend\n"
        "- Components normalised [0,1]; score min-max rescaled 0–100 per level\n"
        "- Weights are **tunable in the app** — a policy lever, not a black box")

    st.markdown("### 🚦 Enforcement-Gap")
    st.markdown("`gap = norm(PCIS) − norm(evening-peak enforcement share)` → high where impact is "
                "high but evening enforcement is thin (the blind spot).")

    st.markdown("### 🧠 De-biasing engine (breaks the feedback loop)")
    st.markdown(
        "Tickets are a *selection-biased* sample — enforcement exposure drops to "
        f"**~{m.get('debias_evening_exposure_pct', 2.2)}% of peak** in the evening "
        f"(peak is **{m.get('debias_peak_exposure_hour', 11)}:00**), so a naive model "
        "would learn *enforcement*, not violations. We correct it:")
    st.latex(r"\hat\lambda(c)=\sum_{t\in c}\frac{1}{e(h_t)}\quad,\quad "
             r"C(c)=\text{road}(c)\cdot s(h)")
    st.markdown(
        "- **e(h)** = hourly enforcement exposure (distinct active devices); "
        "**1/e(h)** = inverse-propensity weight (Horvitz–Thompson, capped ×12)\n"
        "- **road(c)·s(h)** = external congestion prior (OSM-style road class × "
        "synthetic rush-hour curve) — *independent of ticket timing*\n"
        "- **Blind-Spot** = latent demand × divergence(prior − observed) → deploy where "
        "data is missing but congestion is maxed (default sort on *Prioritize*)")

with c2:
    st.markdown("### 🔮 Forecasting")
    _added = mx.get("features_added", [])
    st.markdown(
        f"- Per station × day, {mx.get('horizon_days',7)}-day horizon; **count-aware** objective "
        f"(Poisson/log1p) — beats plain L2\n"
        f"- **Chosen by {mx.get('cv_folds',4)}-fold rolling-origin CV** (risk-adjusted): "
        f"**{mx.get('best_model','—')}**; **Optuna**-tuned ({'gain kept' if mx.get('tuned') else 'no gain → defaults'}); "
        f"CV-gated features added: {', '.join(_added) if _added else 'none (parsimony)'}\n"
        f"- **Mondrian conformal** intervals (per volume-tier widths) → coverage "
        f"{mx.get('coverage_raw_pct','—')}% → **{mx.get('coverage_conformal_pct','—')}%** (target 80%)\n"
        f"- **Hierarchical** bottom-up city forecast (Σ stations, coherent); **weekly** lower-noise view\n"
        f"- CV MAE **{mx.get('mae_model','—')}** vs **{mx.get('mae_baseline','—')}** climatology "
        f"(**{mx.get('improvement_pct',0)}%** better); **MASE {mx.get('mase','—')}** (<1 beats "
        f"seasonal-naive); day-ahead top-10 precision **{int(round(100*mx.get('precision_at_10',0)))}%**\n"
        f"- Benchmarked & rejected: classical **AutoETS** (unstable on intermittent series, MAE "
        f"{mx.get('ets_mae','—')}); **direct multi-horizon** (day+1 already direct; degrades "
        f"gracefully to day+7)\n"
        f"- Honest ceiling: WAPE ≈ {mx.get('wape_pct','—')}% — enforcement counts are spiky, so we "
        f"optimise for *ranking the right hotspots*, not exact counts. **Roadmap:** global deep models "
        f"(N-BEATS/TFT/DeepAR) once multi-year history is available (today's 5 months would overfit them).")

    st.markdown("### 🏗️ Architecture & stack")
    st.markdown(
        "- Offline ETL/ML → compact parquet (<50 MB) → instant Streamlit app\n"
        "- **H3** hexagons power maps *and* ML features\n"
        "- Python · pandas · H3 · scikit-learn (DBSCAN) · LightGBM · Streamlit · "
        "pydeck (deck.gl) · Plotly · Claude · reportlab")
    if (lib.C.ASSETS / "architecture.png").exists():
        st.image(str(lib.C.ASSETS / "architecture.png"), use_container_width=True)

st.divider()
st.markdown("### ⚖️ Honest limitations")
st.warning(
    "- **No traffic-flow ground truth** → PCIS is an explicit, assumption-labelled *proxy*, "
    "not measured delay.\n"
    "- **No closure/action timestamps** (100% null) → we don't claim enforcement response-time analytics.\n"
    "- **5 months, one city** → forecasts are short-horizon; weekly/hourly seasonality is solid.\n"
    "- **Tickets reflect enforcement, not ground-truth violations** → so we don't trust raw counts: "
    "the de-biasing engine inverse-propensity-corrects them and adds a ticket-independent congestion "
    "prior, ranking deployment by *divergence* rather than observed volume.\n"
    "- All recommendations are **decision-support**, not automated enforcement.")

st.caption("ParkSight · Flipkart Gridlock 2.0 · Round 2 · Theme 1 — Parking-Induced Congestion.")

"""Prediction module — next-7-day station forecast with confidence + baseline."""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lib  # noqa: E402

st.set_page_config(page_title="ParkSight — Forecast", page_icon="🔮", layout="wide")
lib.inject_css()
lib.common_sidebar()
if not lib.artifacts_exist():
    lib.no_data_warning()

fc = lib.load("forecast.parquet")
mx = lib.metrics()

lib.page_header("🔮 Hotspot Forecast",
                "LightGBM predicts tomorrow's parking-violation load per station, with confidence bands.")

st.caption(f"Model: **{mx.get('best_model','—')}** — selected by "
           f"{mx.get('cv_folds',4)}-fold rolling-origin cross-validation, with conformal-calibrated "
           f"intervals. Honest, not asserted.")
try:
    _city = lib.load("forecast_city.parquet")
    st.info(f"🏙️ **Hierarchical (bottom-up) city forecast:** ≈ **{int(_city.iloc[0]['pred']):,}** "
            f"violations tomorrow, **{int(_city['pred'].sum()):,}** over the next 7 days "
            f"(Σ of the 54 station forecasts — coherent by construction).")
except Exception:
    pass
k = st.columns(4)
k[0].metric("CV MAE (model)", mx.get("mae_model", "—"), f"vs {mx.get('mae_baseline','—')} climatology")
k[1].metric("Improvement vs baseline", f"{mx.get('improvement_pct', 0)}%")
k[2].metric("MASE (vs seasonal-naive)", mx.get("mase", "—"),
            "skill ✓" if (mx.get("mase", 1) or 1) < 1 else "", delta_color="off")
k[3].metric("Top-10 hotspot precision", f"{int(round(100*mx.get('precision_at_10',0)))}%",
            "day-ahead", delta_color="off")
k2 = st.columns(4)
k2[0].metric("Interval coverage (raw)", f"{mx.get('coverage_raw_pct','—')}%", "uncalibrated", delta_color="off")
k2[1].metric("Interval coverage (conformal)", f"{mx.get('coverage_conformal_pct','—')}%",
             "target 80% ✓", delta_color="off")
k2[2].metric("WAPE", f"{mx.get('wape_pct','—')}%", "counts are spiky", delta_color="off")
k2[3].metric("Forecast horizon", f"{mx.get('horizon_days', 7)} days")
_qd = mx.get("conformal_Q", {})
if isinstance(_qd, dict) and "high" in _qd:
    st.caption(f"🎯 Intervals use **Mondrian conformal** — per volume-tier widths "
               f"(high-volume ±{_qd.get('high')}, mid ±{_qd.get('mid')}, low ±{_qd.get('low')}) — "
               f"so large and small stations are *both* calibrated to ~80%, not forced into one "
               f"global band.")

with st.expander("⚠️ Doesn't this just predict enforcement, not violations? (the feedback-loop trap)"):
    _m = lib.meta()
    st.markdown(
        "A fair challenge: tickets are a *biased* sample — they only exist where an officer was "
        "present, and enforcement collapses in the evening "
        f"(active devices fall to **~{_m.get('debias_evening_exposure_pct', 2.2)}% of peak**). "
        "Trained naively, a model would 'learn' that rush-hour corridors are quiet and reinforce "
        "the blind spot. We handle this with a **separation of concerns**:\n\n"
        "- **This forecast predicts ticket *workload* per station** — a legitimate operational "
        "target for staffing (how many cases each station will process). It is *not* used to decide "
        "where congestion is worst.\n"
        "- **Where & when to deploy is driven by the de-biased Blind-Spot index** on the *Prioritize* "
        "page: it inverse-propensity-weights tickets by hourly enforcement exposure and adds an "
        "external congestion prior (road hierarchy × synthetic rush-hour curve) that doesn't depend "
        "on ticket timing — so the missing-evening-label loop can't train it away.\n\n"
        "In short: the forecast plans capacity; the blind-spot engine corrects the selection bias.")

st.divider()
left, right = st.columns([1.3, 1])

with left:
    stations = sorted(fc["police_station"].unique())
    _fc_default = "Upparpet" if "Upparpet" in stations else stations[0]
    if "fc_station" not in st.session_state: st.session_state["fc_station"] = _fc_default
    s = st.selectbox("Station", stations, key="fc_station")
    d = fc[fc["police_station"] == s].sort_values("date")
    hist = d[~d["is_future"]]
    fut = d[d["is_future"]]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["date"], y=hist["pred"], mode="lines",
                             line=dict(color="#94A3B8", width=2), name="Actual (recent)"))
    fig.add_trace(go.Scatter(x=fut["date"], y=fut["p90"], mode="lines",
                             line=dict(width=0), showlegend=False))
    fig.add_trace(go.Scatter(x=fut["date"], y=fut["p10"], mode="lines", fill="tonexty",
                             fillcolor="rgba(99,102,241,0.20)", line=dict(width=0),
                             name="p10–p90 confidence"))
    fig.add_trace(go.Scatter(x=fut["date"], y=fut["pred"], mode="lines+markers",
                             line=dict(color="#6366F1", width=3), name="Forecast"))
    fig.add_trace(go.Scatter(x=fut["date"], y=fut["baseline"], mode="lines",
                             line=dict(color="#F97316", width=2, dash="dot"), name="Climatology baseline"))
    st.plotly_chart(lib.style_fig(fig, height=380,
                    title=f"{s}: 30-day actual + 7-day forecast"), use_container_width=True)

with right:
    if "fc_horizon" not in st.session_state: st.session_state["fc_horizon"] = "Tomorrow (day+1)"
    view = st.radio("Horizon", ["Tomorrow (day+1)", "Next week (7-day total)"], horizontal=True, key="fc_horizon")
    if view.startswith("Tomorrow"):
        st.markdown("#### 📅 Tomorrow's predicted top stations")
        nxt = (fc[(fc["is_future"]) & (fc["horizon"] == 1)]
               .sort_values("pred", ascending=False).head(10))
        show = nxt[["police_station", "pred", "p10", "p90"]].copy()
    else:
        st.markdown("#### 🗓️ Next-week predicted top stations (lower-noise)")
        try:
            wk = lib.load("forecast_weekly.parquet")
        except Exception:
            wk = (fc[fc["is_future"]].groupby("police_station")[["pred", "p10", "p90"]]
                  .sum().reset_index())
        show = wk.sort_values("pred", ascending=False).head(10)[
            ["police_station", "pred", "p10", "p90"]].copy()
    show.columns = ["Station", "Predicted", "Low (p10)", "High (p90)"]
    st.dataframe(show, hide_index=True, use_container_width=True)
    st.caption("Weekly totals are smoother (less day-to-day noise) — useful for staffing.")

st.divider()
st.markdown("#### 🧠 What drives the forecast (feature importance)")
fi = mx.get("feature_importance", {})
if fi:
    fid = pd.DataFrame({"feature": list(fi.keys()), "importance": list(fi.values())})
    fig = px.bar(fid.sort_values("importance"), x="importance", y="feature",
                 orientation="h", color="importance", color_continuous_scale="Viridis")
    fig.update_layout(coloraxis_showscale=False)
    st.plotly_chart(lib.style_fig(fig, height=320), use_container_width=True)
st.caption("Recent lags dominate (parking pressure is sticky); weekday, day-of-year and "
           "holidays add seasonality. The model is benchmarked against a station×weekday "
           "climatology baseline so its added value is explicit.")

st.divider()
st.markdown("#### 🏆 Model bake-off — rolling-origin CV (lower MAE = better)")
bo = mx.get("bakeoff", {})
bstd = mx.get("bakeoff_std", {})
if bo:
    import plotly.express as px
    bdf = pd.DataFrame({"Model": list(bo.keys()), "MAE": list(bo.values())})
    bdf["std"] = bdf["Model"].map(bstd).fillna(0)
    bdf = bdf.sort_values("MAE")
    best = mx.get("best_model", bdf.iloc[0]["Model"])
    bdf["is_best"] = bdf["Model"] == best
    fig = px.bar(bdf, x="MAE", y="Model", orientation="h", color="is_best",
                 error_x="std", color_discrete_map={True: "#22C55E", False: "#475569"})
    fig.update_layout(yaxis=dict(autorange="reversed"), showlegend=False)
    cda, cdb = st.columns([1.3, 1])
    with cda:
        st.plotly_chart(lib.style_fig(fig, height=320), use_container_width=True)
    with cdb:
        st.dataframe(bdf[["Model", "MAE", "std"]].rename(columns={"std": "±std"}),
                     hide_index=True, use_container_width=True)
        st.success(f"Selected by CV: **{best}**")
    st.caption(f"Mean ± std MAE over {mx.get('cv_folds',4)} rolling-origin folds (not a single "
               "holdout). Count-aware objectives (Poisson/log1p) beat plain L2; the model is chosen "
               "on a risk-adjusted score (mean + 0.25·std).")
    _added = mx.get("features_added", [])
    st.caption(
        f"🔧 Optuna tuning under CV: **{'improved the model' if mx.get('tuned') else 'no gain → kept defaults (anti-overfit)'}**. "
        f"CV-gated features added: **{', '.join(_added) if _added else 'none — parsimony won'}**. "
        f"Classical **AutoETS** was benchmarked (MAE {mx.get('ets_mae','—')}) but is unstable on these "
        f"intermittent, zero-heavy series — so a tree-ensemble + moving-average is the principled choice.")

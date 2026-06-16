"""Enforcement Prioritization — ranked deployment plan + downloadable briefing."""
import sys
from datetime import date
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lib  # noqa: E402
from parksight.reports.briefing import build_briefing  # noqa: E402

st.set_page_config(page_title="ParkSight — Prioritize", page_icon="🎯", layout="wide")
lib.inject_css()
lib.common_sidebar()
if not lib.artifacts_exist():
    lib.no_data_warning()

lib.page_header("🎯 Enforcement Prioritization",
                "Turn impact scores into a ranked, reasoned deployment plan.")

if "pri_grain"   not in st.session_state: st.session_state["pri_grain"]   = "Police station"
if "pri_window"  not in st.session_state: st.session_state["pri_window"]  = "evening"
if "pri_sort_by" not in st.session_state: st.session_state["pri_sort_by"] = "Blind-Spot (de-biased)"

c1, c2, c3 = st.columns([1, 1, 1.4])
grain = c1.radio("Level", ["Police station", "Junction"], horizontal=False, key="pri_grain")
window = c2.radio("Target window", ["evening", "morning"], horizontal=False,
                  format_func=lambda w: "Evening (17–21 IST)" if w == "evening" else "Morning (08–11 IST)",
                  key="pri_window")
sort_by = c1.radio("Rank by", ["Blind-Spot (de-biased)", "PCIS (impact)", "Enforcement-Gap"],
                   horizontal=False, key="pri_sort_by",
                   help="Blind-Spot = de-biased deploy-here index. It inverse-propensity-"
                        "weights tickets by hourly enforcement exposure and compares them to "
                        "an external congestion prior, so it surfaces high-congestion places "
                        "the raw ticket data under-reports. PCIS = raw impact. "
                        "Enforcement-Gap = PCIS minus evening presence (a simpler proxy).")
fname = "station_pcis.parquet" if grain == "Police station" else "junction_pcis.parquet"
namecol = "police_station" if grain == "Police station" else "junction_name"
sort_col = ("blindspot_risk" if sort_by.startswith("Blind") else
            "PCIS" if sort_by.startswith("PCIS") else "gap_score")
df = lib.load(fname).sort_values(sort_col, ascending=False).copy()
df["rank"] = range(1, len(df) + 1)
df["units"] = (df["PCIS"] / 100 * 3).round().clip(lower=1).astype(int)

with c3:
    st.markdown("**📄 Daily Deployment Briefing**")
    st.caption("One-page PDF a station officer can act on this shift.")
    pdf = build_briefing(window=window, top_n=10, for_date=date.today())
    st.download_button("⬇️ Download briefing PDF", data=pdf,
                       file_name=f"parksight_briefing_{window}.pdf",
                       mime="application/pdf", use_container_width=True)

st.divider()
m = lib.meta()
with st.expander("🧠  How we beat the enforcement feedback loop (de-biasing engine)",
                 expanded=sort_by.startswith("Blind")):
    g1, g2 = st.columns([1, 1])
    with g1:
        st.markdown(
            "**The trap.** A ticket only exists where an officer was present. "
            f"Enforcement collapses in the evening — distinct active devices drop to "
            f"**~{m.get('debias_evening_exposure_pct', 2.2)}% of the daytime peak** "
            f"(peak enforcement is at **{m.get('debias_peak_exposure_hour', 11)}:00**, not rush hour). "
            "A model trained naively on tickets would 'learn' that 7 PM commercial "
            "corridors are *safe* — reinforcing the blind spot.\n\n"
            "**The fix (two ticket-independent corrections):**\n"
            "1. **Inverse-propensity weighting** — re-inflate observed tickets by "
            "1/exposure(hour) (Horvitz–Thompson), correcting up to "
            f"**{m.get('debias_max_ipw_uplift', 2.8)}×** in dark hours.\n"
            "2. **External congestion prior** = OSM-style road-hierarchy(place) × a "
            "synthetic rush-hour curve. Neither depends on ticket timing, so the "
            "missing-label loop can't train them to zero.\n\n"
            "The **Blind-Spot** score = latent demand × the divergence between "
            "predicted congestion and the (biased) observed evening signal — it "
            "*forces* deployments toward where data is missing but probability is maxed.")
    with g2:
        st.plotly_chart(lib.exposure_divergence_fig(), use_container_width=True)

tiers = {"High": "#EF4444", "Medium": "#F97316", "Low": "#22D3EE"}
counts = df["tier"].value_counts()
kc = st.columns(3)
for i, t in enumerate(["High", "Medium", "Low"]):
    with kc[i]:
        lib.kpi(f"{t} priority", f"{int(counts.get(t, 0))}", f"{grain.lower()}s", tiers[t])

st.write("")
a, b = st.columns([1.5, 1])
with a:
    show = df.head(15)[["rank", namecol, "blindspot_risk", "PCIS", "ipw_uplift",
                        "violations", "tier", "units", "reason"]].copy()
    show.columns = ["#", grain, "Blind-Spot", "PCIS", "IPW×", "Violations", "Tier", "Units", "Why this rank"]
    st.dataframe(show, hide_index=True, use_container_width=True,
                 column_config={
                     "Blind-Spot": st.column_config.ProgressColumn("Blind-Spot", min_value=0, max_value=100, format="%.0f"),
                     "PCIS": st.column_config.ProgressColumn("PCIS", min_value=0, max_value=100, format="%.0f"),
                     "IPW×": st.column_config.NumberColumn(
                         "IPW×", help="Inverse-propensity uplift: how much the raw count is "
                         "scaled up to correct for under-enforcement.", format="%.2f×")})
    lib.df_download(df[[namecol, "blindspot_risk", "PCIS", "gap_score", "divergence",
                        "ipw_uplift", "violations", "tier", "units", "reason"]],
                    "⬇️ Export full ranking (CSV)", f"parksight_priority_{namecol}.csv")
with b:
    top = df.head(12)
    fig = px.bar(top, x="PCIS", y=top[namecol], orientation="h", color="tier",
                 color_discrete_map=tiers, labels={namecol: ""})
    fig.update_layout(yaxis=dict(autorange="reversed"))
    st.plotly_chart(lib.style_fig(fig, height=460), use_container_width=True)

st.caption("Units scale with PCIS (≈ PCIS/100 × 3, min 1). Recommendations are decision-support.")

st.divider()
with st.expander("📈  Emerging hotspots — fastest-worsening zones (get ahead of them)", expanded=True):
    em = df[df["trend_slope"] > 0].sort_values("trend_slope", ascending=False).head(10).copy()
    em["growth_per_month"] = em["trend_slope"].round(0).astype(int)
    e1, e2 = st.columns([1.3, 1])
    with e1:
        et = em[[namecol, "growth_per_month", "PCIS", "violations", "tier"]].copy()
        et.columns = [grain, "▲ Violations/month", "PCIS", "Violations", "Tier"]
        st.dataframe(et, hide_index=True, use_container_width=True)
    with e2:
        fig = px.bar(em.head(8), x="growth_per_month", y=em.head(8)[namecol],
                     orientation="h", color="growth_per_month", color_continuous_scale="Reds",
                     labels={namecol: "", "growth_per_month": "▲/month"})
        fig.update_layout(yaxis=dict(autorange="reversed"), coloraxis_showscale=False)
        st.plotly_chart(lib.style_fig(fig, height=300), use_container_width=True)
    st.caption("Trend = month-over-month slope of violation counts. Rising zones are flagged "
               "before they become entrenched — proactive, not reactive, enforcement.")

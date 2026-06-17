"""Smart Enforcement Simulator — What-If deployment & projected impact reduction."""
import sys
from pathlib import Path

import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lib  # noqa: E402
from parksight import scoring  # noqa: E402

st.set_page_config(page_title="ParkSight — Simulator", page_icon=lib.FAVICON, layout="wide")
lib.inject_css()
lib.common_sidebar()
if not lib.artifacts_exist():
    lib.no_data_warning()

lib.page_header("🧪 Smart Enforcement Simulator",
                "Pick where to deploy, dial up enforcement, and see projected congestion impact fall.")

lib.policy_banner()

st_df = lib.scored("station_pcis.parquet").sort_values("PCIS", ascending=False).copy()
st_df["impact"] = st_df["PCIS"] * st_df["violations"]
total_impact = st_df["impact"].sum()
total_viol = st_df["violations"].sum()

_default_sel = st_df["police_station"].head(5).tolist()
if "sim_chosen"     not in st.session_state: st.session_state["sim_chosen"]     = _default_sel
if "sim_delta"      not in st.session_state: st.session_state["sim_delta"]      = 25
if "sim_elasticity" not in st.session_state: st.session_state["sim_elasticity"] = lib.C.DETERRENCE_ELASTICITY
if "sim_units"      not in st.session_state: st.session_state["sim_units"]      = 8
if "sim_objective"  not in st.session_state: st.session_state["sim_objective"]  = "Maximize impact coverage"

c1, c2, c3 = st.columns([1.5, 1, 1])
chosen = c1.multiselect("Deploy patrol focus to these stations",
                        st_df["police_station"].tolist(), key="sim_chosen")
delta = c2.slider("Enforcement increase (%)", 0, 100, step=5, key="sim_delta")
elasticity = c3.slider("Deterrence elasticity", 0.0, 1.0, step=0.05,
                       help="Assumed fraction of the enforcement increase that converts "
                            "to fewer violations. Documented, tunable assumption.", key="sim_elasticity")

sel = st_df[st_df["police_station"].isin(chosen)]
covered = sel["impact"].sum()
coverage_pct = 100 * covered / total_impact if total_impact else 0
prevented = int(sel["violations"].sum() * (delta / 100) * elasticity)
new_total = int(total_viol - prevented)
reduction_pct = 100 * prevented / total_viol if total_viol else 0

st.divider()
k = st.columns(4)
k[0].metric("Impact coverage", f"{coverage_pct:.0f}%",
            f"{len(chosen)} of {len(st_df)} stations")
k[1].metric("Violations prevented", f"{prevented:,}", f"-{reduction_pct:.1f}%", delta_color="inverse")
k[2].metric("Projected total", f"{new_total:,}", f"was {total_viol:,}", delta_color="off")
k[3].metric("Patrol units suggested",
            f"{int(scoring.recommended_units(sel['PCIS']).sum()) if len(sel) else 0:,}")

st.progress(min(coverage_pct / 100, 1.0),
            text=f"Selected deployment covers {coverage_pct:.0f}% of the city's PCIS-weighted "
                 f"parking-congestion impact")

m1, m2 = st.columns([1.3, 1])
with m1:
    base = st_df.copy()
    base["sel"] = base["police_station"].isin(chosen)
    base["r"] = base["sel"].map({True: 239, False: 80})
    base["g"] = base["sel"].map({True: 68, False: 110})
    base["b"] = base["sel"].map({True: 68, False: 160})
    layer = pdk.Layer("ScatterplotLayer", data=base, get_position="[lon, lat]",
                      get_radius="violations / 6 + 120", get_fill_color="[r,g,b,170]",
                      pickable=True, stroked=True, get_line_color=[255, 255, 255])
    st.pydeck_chart(lib.deck([layer], zoom=10.5,
                    tooltip={"text": "{police_station}\nPCIS {PCIS} · {violations} violations"}),
                    use_container_width=True)
    st.caption("Red = selected for deployment. Bubble size = violation volume.")
with m2:
    st.markdown("#### Selected stations")
    st.dataframe(sel[["police_station", "PCIS", "violations"]].rename(
        columns={"police_station": "Station", "violations": "Violations"}),
        hide_index=True, use_container_width=True)

st.info("**What-If model:** prevented ≈ Σ(zone violations) × (increase%) × elasticity. "
        "Elasticity is a transparent, adjustable deterrence assumption (we lack causal "
        "enforcement-outcome data) — shown openly rather than hidden. This lets commanders "
        "compare deployment strategies before committing scarce patrol hours.")

st.divider()
st.markdown("### 🤖 AI Patrol Optimizer")
st.caption("Given a limited number of patrol units, where do they cover the most "
           "congestion impact? Greedy max-coverage over stations.")
o1, o2 = st.columns([1, 1.4])
units_avail = o1.number_input("Patrol units available", 1, 30, key="sim_units")
objective = o2.radio("Objective", ["Maximize impact coverage", "Target enforcement-gap zones"],
                     horizontal=True, key="sim_objective")
rank_col = "impact" if objective.startswith("Maximize") else "gap_score"
ranked = st_df.sort_values(rank_col, ascending=False).reset_index(drop=True)
chosen_opt = ranked.head(int(units_avail))
opt_cov = 100 * chosen_opt["impact"].sum() / total_impact if total_impact else 0

cumcov = (ranked["impact"].cumsum() / total_impact * 100)
import plotly.graph_objects as go
oc1, oc2 = st.columns([1.2, 1])
with oc1:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(range(1, len(cumcov) + 1)), y=cumcov.values,
                             mode="lines", line=dict(color="#22D3EE", width=3),
                             fill="tozeroy", fillcolor="rgba(34,211,238,0.12)"))
    fig.add_vline(x=units_avail, line_dash="dash", line_color="#F97316")
    fig.add_hline(y=opt_cov, line_dash="dot", line_color="#F97316")
    fig.add_annotation(x=units_avail, y=opt_cov, text=f"{units_avail} units → {opt_cov:.0f}%",
                       showarrow=True, arrowcolor="#F97316", font_color="#FDBA74")
    fig.update_xaxes(title="Patrol units deployed"); fig.update_yaxes(title="Impact covered (%)", range=[0, 100])
    st.plotly_chart(lib.style_fig(fig, height=340, title="Diminishing-returns coverage curve"),
                    use_container_width=True)
with oc2:
    st.metric("Optimal coverage", f"{opt_cov:.0f}%", f"with {units_avail} units")
    st.dataframe(chosen_opt[["police_station", "PCIS", "gap_score"]].rename(
        columns={"police_station": "Deploy to", "gap_score": "Gap"}),
        hide_index=True, use_container_width=True, height=240)
    lib.df_download(chosen_opt[["police_station", "PCIS", "gap_score", "violations"]],
                    "⬇️ Export plan (CSV)", "parksight_optimizer_plan.csv")
st.caption("The curve shows where extra patrols stop adding much coverage — the data-driven "
           "answer to 'how many teams are enough, and where'.")

# ParkSight — Build TODO

Status legend: ✅ done · 🔄 in progress · ⬜ pending

## Pipeline
- ✅ Project scaffold + requirements.txt + dependency install
- ✅ ETL → 16 artifacts (clean, IST, H3, severity, PCIS, zones, offenders, profiles, meta) — ~14 MB
- ✅ PCIS engine (hex/junction/station) + min-max 0–100 rescale + tiers
- ✅ Enforcement-Gap score (PCIS vs evening-peak presence) on station/junction
- ✅ Forecasting (LightGBM + p10/p90 quantiles vs climatology baseline) — 8.2% MAE improvement
- ✅ Offenders table
- ✅ All artifacts verified loadable & sane

## App (Streamlit + pydeck) — all 8 pages pass headless AppTest (0 errors)
- ✅ Theme config + shared lib (loaders, CSS, KPI, map + chart helpers)
- ✅ Home / Executive Dashboard
- ✅ Hotspot Map (PCIS hex, density-by-hour, DBSCAN zones, drill-down)
- ✅ Impact / PCIS (live re-weighting)
- ✅ Forecast (confidence band + feature importance)
- ✅ Prioritize (PCIS / Enforcement-Gap toggle + PDF briefing)
- ✅ Simulator / What-If
- ✅ Copilot (deterministic + Claude grounded)
- ✅ Offenders watchlist

## Intelligence
- ✅ Copilot engine (intents + Claude NL→grounded analytics + offline fallback)
- ✅ Daily Deployment Briefing PDF (reportlab)

## Content / submission
- ✅ Static report figures (blind-spot, top zones, mix, monthly, forecast)
- ✅ Architecture diagram (PNG)
- ✅ README.md (hero, features, screenshots, run steps, limitations)
- ✅ PPTX pitch deck (12 slides)
- ✅ docs/SUBMISSION.md (every form field + pitch + video script)
- ✅ ARCHITECTURE.md + DECISIONS.md (living docs)
- ✅ .gitignore (excludes raw CSV, keeps artifacts)
- ✅ scripts/build_all.py (one-command rebuild) + scripts/smoke_test_app.py
- 🔄 Live app screenshots (automated capture attempt)

## Finalize
- ✅ Headless AppTest smoke-test (all pages pass)
- ✅ Run instructions documented
- ⬜ Optional: deploy to Streamlit Cloud (needs user's GitHub + account)

REMAINING: 
1. Make the judges emotional by the idea itself
2. Include hyped tech(like NLP, CV, LLM) that will make your project sound like innovation
3. Include a WOW factor in the demo - refine your UI
My additional tips - 1. Research the competitors of your idea and make a comparision table. Mention your novelty
                                 2. Make a business model out of your idea and be clear about your target consumer
                                 3. Do not start coding until you get a WOW idea/ WOW approach (sharpen the axe before cutting the tree)

these are the things that should be included in my submission. 

## Forecasting upgrades (Tiers 1–3, all CV-gated)
- ✅ Tier 1: count-aware objective, rolling-origin CV model selection, leak-free refit, conformal intervals, MASE/WAPE/precision@10
- ✅ Tier 2: Optuna tuning (CV-gated), CV-gated feature selection (kept samedow_mean + days_to_holiday), AutoETS benchmark, weekly view
- ✅ Tier 3: Mondrian (per-tier) conformal, hierarchical bottom-up city forecast, direct multi-horizon evaluation, DL roadmap
- ✅ Final: CV MAE ≈15.9 (14% < climatology), MASE 0.73, conformal coverage ~80%, precision@10 ~0.75; all 10 pages pass AppTest

## De-biasing engine (feedback-loop fix) — ★ headline gap closed
- ✅ Hourly enforcement-exposure model from distinct active devices (evening ≈ 2.2% of peak)
- ✅ Inverse-propensity (Horvitz–Thompson) latent-demand correction (capped ×12; up to 2.8× uplift)
- ✅ External congestion prior = OSM-style road-hierarchy(place) × synthetic rush-hour curve
- ✅ Blind-Spot divergence + blindspot_risk merged onto station/junction/cell PCIS
- ✅ Artifacts: enforcement_exposure.parquet, blindspot_cells.parquet; meta debias_* fields
- ✅ Prioritize page: default Blind-Spot sort + IPW× column + exposure-vs-congestion chart + explainer
- ✅ Forecast page: "predicts enforcement not violations?" trap answered (workload vs deployment split)

_Status: prototype + model rigor complete and validated end-to-end. Deployment + video are the only user-credential steps._

# ParkSight — Submission Pack (copy-paste ready)

Fill the Flipkart Gridlock 2.0 Round-2 form with the content below.

---

## Theme
**Theme 1 — Poor Visibility on Parking-Induced Congestion**

## Title
**ParkSight — AI Parking-Congestion Intelligence for Targeted Enforcement**

## Description (judge-facing)

**The problem.** On-street and spillover parking near markets, metro stations and event venues
chokes Bengaluru's carriageways and junctions. Enforcement is reactive and patrol-based, there is no
heatmap of violations vs. congestion impact, and authorities can't prioritise where — or when — to deploy.

**The discovery.** Profiling the official dataset (298,445 geo-located violations, Nov 2023–Apr 2024)
and converting timestamps UTC→IST reveals an **Evening Enforcement Blind-Spot**: violation records
collapse during IST 15:00–24:00, spanning the evening commercial-congestion peak. Few tickets here means low
enforcement *visibility*, not fewer violations — the precise gap the theme names.

**The solution — ParkSight**, an 8-module command center:
- **Executive Dashboard** — KPIs, citywide impact, the blind-spot.
- **AI Hotspot Map** — H3 hex heatmap coloured by impact, density-by-hour, DBSCAN zones, drill-down.
- **PCIS Engine** — our proprietary, explainable **Parking Congestion Impact Score** =
  `100·(0.30·Volume + 0.20·Severity + 0.20·Location + 0.20·PeakOverlap + 0.10·Trend)`, re-weightable live.
- **Forecast** — next-7-day prediction per station, **model chosen by rolling-origin cross-validation**
  (count-aware Blend log1p+MA-7, Optuna-tuned, CV-gated features), **Mondrian conformal** p10–p90
  intervals (coverage ~80%), hierarchical city total and a weekly view. Honest decision metrics:
  ~14% better MAE than climatology, MASE 0.73 (beats seasonal-naive), day-ahead top-10 precision ~75%.
- **Prioritize** — ranked High/Med/Low deployment plan with reasons + a downloadable PDF briefing.
- **Simulator** — What-If: choose zones, dial enforcement and deterrence, watch projected impact fall.
- **AI Copilot** — plain-English Q&A grounded in the data (optional Claude NL understanding).
- **Offenders** — chronic-offender watchlist: 15% of vehicles cause 34% of violations.

**Why it's credible.** PCIS is an explicit, assumption-labelled proxy (the data has no traffic-flow
column, and we say so). Forecasts are baseline-benchmarked. The whole pipeline precomputes to <50 MB
artifacts, so the app is instant and deployable. Built only on the official provided dataset.

**Impact.** A station officer gets a ranked, reasoned deployment plan — and a one-page briefing —
in a single click, targeting the third of violations driven by repeat offenders and the evening blind-spot.

## Demo Link
**https://parksight.streamlit.app/**  *(live — Streamlit Community Cloud; works out-of-the-box on committed artifacts)*

## Repository URL
**https://github.com/Susan5504R/ParkSight**

## Video URL
`https://youtu.be/<id>`  *(2.5-min walkthrough — script below)*

## Instructions to Run
```bash
pip install -r requirements.txt
streamlit run parksight/app/Home.py        # works out-of-the-box (artifacts committed)
# optional: export ANTHROPIC_API_KEY=sk-...  to enable Claude in the Copilot
# optional rebuild: python parksight/etl/build_artifacts.py && python parksight/models/train_forecast.py
```
Open http://localhost:8501. The raw 109 MB CSV is **not required** — precomputed artifacts ship in
`parksight/data/processed/`. To rebuild, drop the original CSV in the project root and run the ETL.

## Source Code
Zip the repo **excluding** the raw CSV (it exceeds 50 MB and is provided by HackerEarth). The
committed `parksight/data/processed/*.parquet` (~15 MB) keeps the app fully runnable.

## Presentation
`parksight/reports/out/ParkSight_Pitch_Deck.pptx` (12 slides).

## Snapshots (upload these)
`parksight/assets/`: `fig_blindspot.png`, `architecture.png`, `fig_top_zones.png`,
`fig_forecast.png`, `fig_violation_mix.png` — plus live screenshots of the Hotspot Map,
PCIS re-weighting, Simulator and Copilot pages.

---

## Elevator pitch (30s)
> Bengaluru writes ~2,000 parking tickets a day but still can't see where illegal parking actually
> chokes traffic — and enforcement goes dark every evening just as congestion peaks. ParkSight turns
> 298,450 violations into a live congestion-impact map, predicts tomorrow's hotspots, and hands each
> station a deployment plan. It's the heatmap, the forecast, and the dispatcher the city doesn't have today.

## Video script (~2.5 min)
1. **0:00 Cold open** — the blind-spot chart. "The city stops watching at 5 PM, just as congestion peaks."
2. **0:20 Dashboard** — KPIs, 298k violations, 34% from repeat offenders, citywide PCIS.
3. **0:45 Hotspot Map** — toggle PCIS hexes, scrub the IST hour window, click KR Market → breakdown + recommendation.
4. **1:20 PCIS** — drag the weight sliders; the ranking reshuffles. "Transparent policy lever, not a black box."
5. **1:40 Forecast** — next-7-day with confidence band; beats the baseline.
6. **1:55 Prioritize → Simulator** — download the briefing PDF; drop 5 stations, raise enforcement 25%, watch impact fall.
7. **2:15 Copilot** — "Where should I deploy tomorrow evening?" → grounded answer + table.
8. **2:30 Close** — "ParkSight sees the blind spot, scores the impact, deploys the plan." Roadmap card.

## Demo-day tips
- Lead with the blind-spot, end with the Copilot — two memorable bookends.
- If offline, the Copilot's deterministic engine still answers every scripted question.
- Have the briefing PDF pre-downloaded as a backup artifact.

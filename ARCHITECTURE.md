# ParkSight — Architecture

## Overview
Offline batch analytics + ML produce compact artifacts; a Streamlit + pydeck app
reads them. Raw 109 MB CSV never ships — only small parquet (<50 MB total),
which also satisfies the 50 MB submission limit.

```
 RAW CSV (298,450 rows, 109 MB)
        │
        ▼
 ┌─────────────────────┐   parksight/etl/build_artifacts.py
 │  ETL & FEATURE BUILD │   - drop dead cols (description/closed/action ts = 100% null)
 │                      │   - UTC → IST (Asia/Kolkata)   [critical fix]
 │                      │   - parse violation_type JSON → tags, severity, is_severe
 │                      │   - H3 index res-8 (city) + res-9 (street hotspots)
 │                      │   - location keyword score, at-junction flag, peak-window weight
 │                      │   - repeat-offender flag
 └─────────┬───────────┘
           ▼
 ┌─────────────────────┐
 │   PCIS ENGINE        │   PCIS = 100·(0.30 V + 0.20 S + 0.20 L + 0.20 P + 0.10 T)
 │  (hex/junction/stn)  │   V=volume(log) S=severity L=location P=peak-overlap T=trend
 │  + DBSCAN zones      │   all components min-max normalised to [0,1]
 │  + offenders         │
 └─────────┬───────────┘
           ▼
 ┌─────────────────────┐   parksight/models/debias.py  ★ feedback-loop fix
 │  DE-BIASING ENGINE   │   tickets are a selection-biased sample (enforcement dark
 │  (break endogeneity) │   in the evening → ~2.2% of peak exposure). Correct with:
 │                      │   • inverse-propensity weighting 1/exposure(hour)  [Horvitz–Thompson]
 │                      │   • external congestion prior = road-hierarchy(place)·synthetic(hour)
 │                      │   → blindspot_risk = latent_demand × divergence(prior vs observed)
 └─────────┬───────────┘
           ▼
 ┌─────────────────────┐   parksight/models/train_forecast.py
 │  FORECASTING         │   LightGBM (mean + p10/p90 quantiles) per station/day
 │                      │   features: lag1/7, roll7/14, dow, weekend, month, doy, holiday
 │                      │   baseline: station×weekday climatology (model must beat it)
 └─────────┬───────────┘
           ▼
   parksight/data/processed/*.parquet  +  models/metrics.json  +  meta.json
           │
           ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  STREAMLIT APP (pydeck deck.gl maps, plotly charts)            │
 │  Home(Exec) · Hotspot Map · PCIS · Forecast · Prioritize ·    │
 │  Simulator · Copilot · Offenders                              │
 │  Copilot: deterministic intents → analytics; optional Claude   │
 │  tool-use (claude-sonnet-4-6) with offline fallback            │
 │  Reports: reportlab Daily Deployment Briefing PDF              │
 └──────────────────────────────────────────────────────────────┘
```

## Artifacts (data contracts)
| File | Grain | Key columns |
|---|---|---|
| violations_clean.parquet | ticket | id, lat, lon, h3_r9/r8, severity, is_severe, is_repeat, hour, weekday, month |
| cell_pcis.parquet | h3 res-9 | h3_r9, V,S,L,P,T, PCIS, tier, reason, lat, lon, top_type, peak_hour |
| city_cells.parquet | h3 res-8 | h3_r8, PCIS, violations |
| enforcement_exposure.parquet | hour | devices, exposure, ipw, synthetic_congestion |
| blindspot_cells.parquet | h3 res-9 | latent_demand, road_class, congestion_prior, divergence, blindspot_risk |
| station_pcis.parquet | police_station | PCIS, tier, rank, reason, components |
| junction_pcis.parquet | junction | PCIS, tier, rank, reason |
| zones.parquet | DBSCAN cluster | name, lat, lon, PCIS, violations, cells |
| offenders.parquet | vehicle | violations, type, last_seen, top_station/junction |
| hourly_profile.parquet | hour×weekday | n (blind-spot chart) |
| daily_station.parquet | station×date | n (forecast input) |
| forecast.parquet | station×date | pred, p10, p90, baseline, is_future, horizon |
| meta.json / metrics.json | — | headline KPIs / model metrics |

## Tech stack
Python 3.12 · pandas · h3 · scikit-learn (DBSCAN) · LightGBM · Streamlit · pydeck (deck.gl)
· Plotly · Anthropic SDK (Claude) · reportlab (PDF) · python-pptx (deck) · matplotlib (figures).

## Why this design scores
- **Precompute → small artifacts**: app is instant, deployable on free tiers, fits 50 MB limit.
- **H3** powers both maps and ML features; uniform, hierarchical, scalable.
- **Explainable PCIS** answers "quantify impact" without faking traffic data.
- **De-biasing engine** neutralises the enforcement feedback loop (the sharpest ML
  critique): tickets ≠ violations, so we IPW-correct + inject a ticket-independent
  congestion prior and rank deployments by *divergence*, not raw counts.
- **Baseline-benchmarked forecast** proves the ML adds value (credibility).
- **Offline copilot fallback** → the live demo never dies.

# ParkSight — Decision Log (with assumptions & alternatives)

Each entry: **Decision** · *Why (score impact)* · Alternatives parked for later.

### D1 — Theme 1 (Parking-Induced Congestion)
Dataset is a near-perfect fit (298k geocoded parking violations); Theme 2 data
doesn't match its ask, Theme 3 (CV) is crowded/high-variance. *Maximises feasibility + data-fit.*

### D2 — "C-core + D-ceiling" scope
Build the predictive platform fully (hotspot+PCIS+forecast+prioritize), then add
3 wow features (copilot, simulator, briefing). *Protects Functionality score while raising Innovation/Wow.*
Parked: full Agentic command-center, OSM road-graph spillover (Approach E) → roadmap slide.

### D3 — Tech stack: Streamlit + pydeck + Plotly + DuckDB-optional
pydeck gives deck.gl-quality maps without React overhead; highest demo-quality-per-build-hour at low risk.
Parked: Next.js + deck.gl + Mapbox (rebuild map page only) if time remains.

### D4 — Precompute artifacts, never ship raw CSV
109 MB raw → small parquet. *Instant app, deployable, fits 50 MB submission limit.*
Assumption: app is read-only over precomputed data; acceptable for a hackathon demo.

### D5 — PCIS as explainable weighted composite (not black-box)
PCIS = 100·(0.30V+0.20S+0.20L+0.20P+0.10T). *Judges trust an explainable, defensible
metric over an opaque model; weights are UI-tunable for an interactive demo.*
Assumption: weights are a reasoned prior, documented and adjustable; not learned (no ground-truth flow data to learn from).

### D6 — Severity = max tag weight per ticket; "severe" if ≥0.80
Worst carriageway-blocking tag dominates a ticket's congestion impact. Alternative (mean of tags) parked.

### D7 — UTC → IST conversion in ETL
created_datetime is UTC(+00); all temporal insight (esp. the evening blind-spot) is wrong without it. *Correctness-critical.*

### D8 — Forecast at police-station × day granularity
54 stations × ~150 days = robust signal and a clean demo ("tomorrow's hotspot stations").
*Cell-level daily is too sparse for ML;* cell-level "predicted tomorrow" map uses weekday climatology instead.
Parked: junction-level LightGBM, cell-level spatio-temporal model.

### D9 — LightGBM over deep learning
5 months tabular data → gradient boosting wins on accuracy + build speed + explainability (feature importance). DL parked (data-hungry, slower, no gain).

### D10 — Copilot: deterministic intents + optional Claude tool-use, offline fallback
Demo must never fail on a network/API issue. Deterministic layer answers scripted questions with grounded numbers; Claude (claude-sonnet-4-6) enhances free-form NL when ANTHROPIC_API_KEY is set.

### D11 — Enforcement presence proxy
No closure/action timestamps (100% null) → use violation coverage + distinct devices in peak window as a presence proxy for the Enforcement-Gap metric. Documented as a proxy, not measured enforcement.

### D12 — Holiday features via `holidays` (country=IN)
Nov–Apr window includes major holidays affecting traffic; cheap, improves forecast realism.

### D13 — PCIS rescaled min-max to 0–100 per grain
A weighted sum of normalised components never maxes all five at once, so raw PCIS topped ~55 and
nothing crossed the "High" tier. Min-max rescaling per grain gives a full-range, punchy index and
meaningful tiers (n_hotspots went 0 → 234). `PCIS_abs` kept for reference. *Standard for an impact index.*

### D14 — Enforcement-Gap score added (signature differentiator)
`gap = norm(PCIS) − norm(evening-peak share)`, rescaled 0–100. High = high impact but low evening
enforcement presence → where deploying helps most. Operationalises the blind-spot at zone level;
exposed as a sort toggle on Prioritize. Evening share is ~0.02–0.5% citywide → confirms the blind-spot.

### D15 — Pin streamlit==1.58.0
`use_container_width` is deprecation-warned (removal flagged after 2025-12-31) but still works in 1.58.
Pinning guarantees the deployed app matches the tested version. Parked: migrate to `width='stretch'`.

### D16 — Validate via streamlit.testing AppTest (headless)
Runs every page and captures exceptions without a browser — all 8 pages pass with 0 errors. Best
headless proof the demo works. Live Playwright screenshots added for the Snapshots field.

### D17 — Forecast at station×day (not cell×day)
Cell-day series too sparse for ML; 54 stations × ~150 days gives robust signal and a clean
"tomorrow's hotspot stations" demo. Cell-level "predicted" uses climatology. Parked: cell-level spatio-temporal model.

### D18 — Model bake-off + ensemble (don't assert "best", prove it)
A bake-off (naive, seasonal-naive, MA-7, climatology, LightGBM) exposed that a plain **7-day moving
average (17.04) initially beat LightGBM (17.58)**. Fixed honestly: richer features (lag14, roll3/28),
regularisation + early stopping → LightGBM (tuned) 16.83, and a **LightGBM＋MA-7 ensemble = 16.54
(best, 14.6% < climatology)**. Forecast uses whichever the bake-off selects; shown on the Forecast page.
*Lesson: evidence over assertion — and the simple baseline nearly won, which is worth knowing.*

### D19 — Live Data Refresh (prove nothing is hardcoded)
ETL refactored so `load_clean`/`main` accept a file path OR a DataFrame. New in-app **Data Refresh**
page lets a user upload a CSV (or use the local file); it re-runs ETL + forecast and clears the
Streamlit cache so every map/chart recomputes. Demonstrates the platform is data-driven, not a static
facade; in production this is a scheduled job / streaming consumer on a live e-challan feed.

### D20 — Forecasting overhaul (Tiers 1–3), all CV-gated to avoid overfitting
Driven by `scripts/model_experiments.py` (rolling-origin CV) which exposed that a plain 7-day MA
initially beat L2 and that *adding features overfit* on 150 days. Final design:
- **Count-aware** objective (Poisson/Tweedie/log1p) — beats L2; **model selected by 4-fold
  rolling-origin CV** on a risk-adjusted score (mean+0.25·std). Winner: **Blend log1p+MA-7**.
- **Leak-free refit**: tune n_estimators on an inner split, retrain on all data (no scoring-window leak).
- **CV-gated forward feature selection**: kept only `samedow_mean`, `days_to_holiday` (dropped `ewma7`).
- **Optuna** tuning *gated by CV* — kept only because it improved CV (→ ~15.9 MAE).
- **Mondrian (per-volume-tier) conformal** intervals: tier widths (high ±8.9, mid ±1.9, low ±0.4)
  → coverage ~71% → ~80%, vs a mis-calibrated single global band.
- **Hierarchical** bottom-up city forecast (coherent); **weekly** lower-noise view.
- **Benchmarked & rejected** (honest): classical **AutoETS** (unstable on intermittent counts,
  MAE ≫ baselines) and **direct multi-horizon** (day+1 already direct; recursion fine for h≥2).
- **Decision metrics** reported: MASE 0.73 (<1 beats seasonal-naive), WAPE ~48%, precision@10 ≈ 0.7–0.8.
- **DL parked**: N-BEATS/TFT/DeepAR need multi-year history; 5 months would overfit — roadmap item.
*Lesson honored throughout: parsimony + CV-gating beat complexity on a small, noisy, enforcement-driven target.*

### D21 — De-biasing engine (break the enforcement feedback loop) ★ headline fix
The fatal critique: tickets are a *selection-biased* sample — a violation is only
recorded where an enforcement device is present, and enforcement collapses in the
evening (distinct active devices fall to **~2.2% of the daytime peak; peak
enforcement is 11:00, not rush hour**). A model trained naively on tickets learns
*enforcement behaviour*, not congestion, and would call 7 PM commercial corridors
"safe" — an endogeneity loop that reinforces the blind spot.
Fix (`parksight/models/debias.py`), two corrections that are **decoupled from ticket
timing** so the missing-label loop can't train them away:
- **Inverse-propensity weighting (Horvitz–Thompson):** estimate hourly enforcement
  *exposure* e(h) from distinct active devices; re-inflate observed counts by
  1/e(h) (capped ×12) → latent-demand estimate, correcting up to **2.8×** in dark hours.
- **External congestion prior** C(cell,h) = OSM-style **road-hierarchy(place)** ×
  **synthetic rush-hour curve(h)** — a static spatial property × a traffic-engineering
  prior, neither derived from ticket timestamps.
- **Blind-Spot Divergence** = norm(congestion prior) − norm(observed evening signal);
  the **blindspot_risk** index = latent demand × divergence *forces* deployment toward
  cells where data is missing but congestion is maxed out. It reorders priorities
  (e.g. HAL Old Airport rises; a high-PCIS but well-enforced station drops).
New artifacts: `enforcement_exposure.parquet`, `blindspot_cells.parquet`; blind-spot
columns merged onto station/junction/cell PCIS; exposed as the default **Blind-Spot**
sort on *Prioritize* with an exposure-vs-congestion divergence chart, and answered on
*Forecast* (forecast = ticket *workload* for staffing; deployment = de-biased index).
*Why it scores: directly neutralises the single most likely model-savvy judge question.*
Parked: live TomTom/Google congestion API and a real OSM road graph (network calls) —
the road-hierarchy proxy + synthetic profile is the offline-safe stand-in.

_Assumptions are revisited if they cause errors or weaken the submission._

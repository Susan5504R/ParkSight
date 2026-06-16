# SKILL.md — Flipkart Gridlock 2.0 (Round 2) · Theme 1
## ParkSight — AI-Driven Parking-Congestion Intelligence Platform
### Master Implementation & Strategy Plan (analysis-first; build only after Phase 9)

> **Roles authoring this plan:** Senior AI/ML Engineer · Traffic Analytics Expert · Smart-City Solutions Architect · Full-Stack Engineer · Product Manager · Hackathon Judge.
> **Mandate:** maximize the Round-2 score. Every decision below is tied to *why it earns points*.
> **Window:** challenge open 15 Jun 2026 22:00 IST → 21 Jun 2026 23:59 IST (~5.5 working days).
> **Hard rule:** only the provided dataset may be used for the data model; external *image/geometry reference* layers (e.g., OSM road graph) are allowed as enrichment, not as a substitute data source. We will keep the violation analytics 100% on the provided file.

---

## 0. The Winning Thesis (read this first)

The problem statement names three pains: enforcement is **reactive**, there is **no heatmap of violations vs. congestion impact**, and zones are **hard to prioritize**. The dataset gives us *where* and *when* violations happen — but **no traffic-flow column**. 90% of teams will therefore stop at a pretty heatmap.

**We win by doing the one hard thing the data resists:** turning raw violations into a defensible, explainable **Parking Congestion Impact Score (PCIS)**, then layering **prediction → prioritization → simulation → an AI copilot** on top, wrapped in a command-center UI that feels like the Bengaluru Traffic Police could deploy it Monday morning.

**One-line pitch:** *"ParkSight converts 298,450 parking violations into a live congestion-impact map, predicts tomorrow's hotspots, and tells each police station exactly where and when to deploy — closing the enforcement blind spot that opens every evening."*

Three "moat" assets no other team will have unless they do the work:
1. **PCIS** — a transparent composite metric that answers the literal ask ("quantify impact on traffic flow") without faking traffic data.
2. **The Evening Blind-Spot finding** (see §1) — a real, data-grounded insight that reframes the whole problem and gives the demo a "wow, that's a genuine discovery" moment.
3. **Enforcement-Gap prioritization** — ranking zones by *predicted impact minus current enforcement presence*, not just by raw counts.

---

## 0.5 Inferred Judging Rubric (what we are optimizing)

The exact rubric was not published, so we optimize against the rubric these hackathons consistently use. **All scoring tables in this document use these weights.**

| Criterion | Weight | What moves the needle |
|---|---|---|
| Innovation & Uniqueness | 20% | PCIS, blind-spot insight, simulator, copilot |
| Technical Implementation & Complexity | 20% | Geospatial ML, forecasting, optimization, clean architecture |
| Impact & Smart-City Relevance | 20% | "A city could actually use this"; ties to real ops |
| Functionality & Completeness | 15% | A *working* deployed demo, end-to-end |
| UX / Demo / Presentation | 15% | Command-center polish, story, video |
| Scalability & Feasibility | 10% | H3 + precompute architecture, productionizable |

**Design principle:** never sacrifice "Functionality & Completeness" for an unfinished moonshot. A *complete* C-tier scope beats a *broken* S-tier scope. We build a high floor, then add ceiling.

---

## 1. PHASE 0 — Data Profiling Report (real numbers, full 298,450 rows)

Source: `jan to may police violation_anonymized791b166.csv` (~109 MB). Profiled with `eda_profile.py` (stdlib, full-file stream). **Title note:** the file says "jan to may" but the data actually spans **2023-11-09 → 2024-04-08** (Nov→Apr). Use the real range in the deck.

### 1.1 Schema & completeness (24 columns)

| Column | Missing % | Verdict / use |
|---|---|---|
| `id` | 0% | primary key |
| `latitude`, `longitude` | 0% | **core geo** — 100% valid, bbox lat[12.80,13.29] lon[77.44,77.77] (Greater Bengaluru) |
| `location` | 1.02% | text address; mine keywords (Market/Metro/Mall/School/Hospital) |
| `vehicle_number` | 0% | **repeat-offender key** (anonymized but stable) |
| `vehicle_type` | 0% | SCOOTER/CAR/MOTOR CYCLE/PASSENGER AUTO… (2-wheelers dominate) |
| `description` | **100% NULL** | **DROP** |
| `violation_type` | 0% | JSON array of tags → **severity model input** |
| `offence_code` | 0% | JSON array of ints (mirrors violation_type) |
| `created_datetime` | 0% | **core temporal** (UTC; convert to IST) |
| `closed_datetime` | **100% NULL** | **DROP** (cannot measure closure) |
| `modified_datetime` | 0% | **only lifecycle proxy** (created→modified) |
| `device_id` | 0% | 3,070 devices → enforcement-effort proxy |
| `created_by_id` | ~0% | officer/account id |
| `center_code` | 3.77% | 52 centers |
| `police_station` | ~0% | **54 stations → deployment unit** |
| `data_sent_to_scita` | 0% | bool flag (SCITA = signal/ITMS integration) |
| `junction_name` | ~0% | 169 named junctions; 50.4% at a named junction |
| `action_taken_timestamp` | **100% NULL** | **DROP** |
| `data_sent_to_scita_timestamp` | 85.9% | mostly empty |
| `updated_vehicle_number` / `updated_vehicle_type` | 42% | validated subset; type corrected in 6,169 rows |
| `validation_status` | 42% | approved 38.7% / rejected 16.7% / unvalidated 42% → **data-quality layer** |
| `validation_timestamp` | 42% | when validated |

### 1.2 Temporal profile
- **Span:** 2023-11-09 → 2024-04-08 (5 months; April partial). Monthly: Nov 44k, Dec 64k, Jan 66k, Feb 55k, Mar 55k, Apr(partial) 15k.
- **Weekday:** fairly flat, **Sunday highest (46.9k)**, Mon lowest (38.9k) → weekend commercial-area pressure.
- **Hour (THE headline finding):** `created_datetime` is **UTC**. Converted to **IST (+5:30)**:

| IST window | Activity | Interpretation |
|---|---|---|
| 05:30–13:30 | **High (morning peak ~10:30)** | daytime enforcement sweeps |
| 15:00–24:00 | **Near-zero trough** | **enforcement blind spot** |
| 23:30–04:30 | **Second high peak** | night towing / overnight illegal parking |

> **Insight to headline:** the city's parking-enforcement record goes dark precisely during the **evening commercial congestion peak (IST ~17:00–20:30)**. Caveat to state honestly: low tickets ≠ low violations — it likely means low *enforcement visibility*, which **is exactly the "poor visibility" problem in the statement.** ParkSight quantifies and closes that gap.

### 1.3 Geographic profile
- 54 police stations, 169 junctions, 52 center codes, 3,070 devices.
- 50.4% of violations at a **named junction**, 49.5% on open street segments ("No Junction").
- **Top stations:** Upparpet 34.5k · Shivajinagar 28.0k · Malleshwaram 22.2k · HAL Old Airport 20.8k · City Market 17.6k (all dense commercial/market/transit zones — perfect theme fit).
- **Top junctions:** Safina Plaza 15.4k · KR Market 11.5k · Elite 10.7k · Sagar Theatre 10.5k · Central Street 5.4k.

### 1.4 Violation profile
- WRONG PARKING 55.3% · NO PARKING 46.6% · PARKING IN A MAIN ROAD 8.0% · PARKING ON FOOTPATH 1.3% · NEAR BUS-STOP/SCHOOL/HOSPITAL 0.8% · DOUBLE PARKING 0.7% · NEAR ROAD CROSSING 0.6% · NEAR TRAFFIC LIGHT/ZEBRA 0.2%.
- **~97% parking-related.** Non-parking noise (defective plate 2.6%, refuse-hire, excess-fare) is minor → filter or keep as context.
- **Carriageway-blocking ("severe") tickets: 30,681 (10.3%)** — the rows that most directly choke traffic; weighted heavily in PCIS.
- Multi-tag tickets exist (258k single, 33k double, up to 12 tags) → severity can exceed 1 per ticket.

### 1.5 Vehicle & quality profile
- SCOOTER 94.9k · CAR 88.9k · MOTOR CYCLE 40.8k · PASSENGER AUTO 37.8k · MAXI-CAB 11.4k · LGV 8.3k. **2-wheelers + autos ≈ 60%** (footpath/spillover parking signature).
- Validation: 38.7% approved, 16.7% rejected, 42% unvalidated → we can show a **data-quality / confidence** layer and optionally down-weight rejected tickets.

### 1.6 Repeat-offender profile
- 231,890 distinct vehicles. **35,587 (15.3%) are repeat offenders, accounting for 102,147 tickets = 34.2% of all violations.** Max 55 tickets on one vehicle; 552 vehicles with 11+.
- **Story:** *"34% of the congestion problem comes from 15% of vehicles"* → a targeted "chronic offender watchlist" feature.

### 1.7 Hard limitations (state them proactively — judges trust honesty)
1. **No traffic-flow / speed / volume data** → PCIS is an explicit, assumption-labeled *proxy*, not measured delay.
2. **No closure/action timestamps** → cannot measure enforcement response time; use `modified_datetime` only as a weak proxy and don't overclaim.
3. **5 months, single city** → good for weekly/hourly seasonality, not annual; forecasts are short-horizon.
4. **Tickets reflect enforcement, not ground-truth violations** → the blind-spot caveat above; we frame ParkSight as improving *visibility & allocation*, which is the actual ask.
5. **Timezone** — must convert UTC→IST in ETL or every temporal insight is wrong.

---

## 2. PHASE 1 — Solution Architecture Options, Comparison & Ranking

Scores are 1–10; **Weighted Total** uses the §0.5 rubric. "Feasibility" = buildable well in ~5.5 days with this data.

| # | Approach | Innov. | Tech | Feasibility | Demo | Scalability | Smart-city | Wow | **Weighted** |
|---|---|---|---|---|---|---|---|---|---|
| A | **Descriptive dashboard** (heatmap + filters + stats) | 3 | 3 | 10 | 6 | 7 | 6 | 3 | **5.2** |
| B | **Hotspot Intelligence + PCIS** (clustering + proprietary score + dashboard) | 7 | 6 | 9 | 8 | 8 | 8 | 7 | **7.5** |
| C | **Predictive Enforcement Platform** (B + spatio-temporal forecast + prioritization + simulator) | 8 | 8 | 8 | 9 | 8 | 9 | 8 | **8.3** |
| D | **Agentic AI Command Center** (C + NL copilot + what-if + auto-deployment plans + digital-twin view) | 10 | 9 | 6 | 10 | 8 | 10 | 10 | **8.8** |
| E | **Road-graph congestion propagation** (snap to OSM network, model spillover along edges) | 10 | 10 | 4 | 7 | 6 | 9 | 8 | **7.4** |
| F | **Computer-vision augmentation** (detect parking from images) | 9 | 9 | 1 | 7 | 5 | 7 | 8 | **5.9** — *no images in data; reject* |

### Ranking
**D (8.8) > C (8.3) > B (7.5) > E (7.4) > F (5.9) > A (5.2)**

### Recommendation — "C-core + D-ceiling" (build C completely, bolt on the 3 highest-ROI D features)
- **Build C fully** (it is the high floor that guarantees a complete, working, impressive demo).
- **Add three D features** that have the best wow-to-effort ratio: **AI Copilot**, **Smart Enforcement Simulator / What-If**, and **Auto-generated daily deployment plan**.
- **Keep E in your back pocket** as the "future work / scalability" slide — mentioning OSM road-graph spillover modeling signals technical depth without the build risk. Optionally use a *lightweight* slice of E (snap to nearest road class) only as a PCIS feature if time remains.
- **Reject F** (no images).

**Why this wins:** it maxes Innovation + Smart-city + Wow (the three 20%/Wow drivers) while protecting Functionality (15%) because the C core is finishable. The judge sees a moonshot that *actually runs*.

---

## 3. PHASE 2 — Feature Prioritization (with reasoning)

### MUST HAVE (MVP — without these we don't place)
| Feature | Why it's mandatory |
|---|---|
| Clean ETL + UTC→IST + H3 indexing + precomputed parquet | Everything depends on it; also keeps deployed artifact <50 MB |
| Interactive hotspot map (H3 heat + clusters) | Directly answers "no heatmap exists today"; the visual the demo lives on |
| **PCIS engine** (per hex / junction / station) | The literal ask: "quantify impact"; our core differentiator |
| Executive KPI dashboard | Judge's 10-second orientation; "command center" feel |
| Enforcement prioritization ranked list (High/Med/Low + reasoning) | Answers "hard to prioritize zones" |
| Time/severity/vehicle filters | Makes the demo interactive and credible |
| Deployed public demo + GitHub + README | Functionality/Completeness points; required submission fields |

### HIGH IMPACT (each materially lifts the score)
| Feature | Why |
|---|---|
| **Next-day / peak-hour hotspot forecast** + confidence | Moves us from descriptive→predictive (Innovation + Tech) |
| **Enforcement-Gap score** (predicted impact − current presence) | The "blind spot" operationalized; genuinely novel |
| **AI Copilot** (NL → analytics) | Highest wow-per-second in a live demo |
| **Smart Enforcement Simulator / What-If** | Interactive, memorable, "city could use this" |
| **Repeat/chronic-offender watchlist** | Strong data-story ("15% → 34%") |
| Time-lapse animation of hotspots over months | Cheap to build, huge visual payoff |
| Auto-generated **daily deployment briefing (PDF)** | "Deployable product" signal |

### NICE TO HAVE (only if ahead of schedule)
| Feature | Why deferred |
|---|---|
| OSM road-class enrichment for PCIS | Adds rigor but ETL risk |
| Patrol-allocation optimizer (max-coverage) | Great, but simulator already conveys the idea |
| Multi-city / upload-your-own-CSV mode | Scalability flex; not scored heavily |
| Role-based views (commissioner vs. station officer) | Polish, not core |
| Anomaly detection (sudden new hotspot alerts) | Nice story, moderate effort |

### AVOID (time sinks with low judging return)
| Feature | Why avoid |
|---|---|
| Real-time streaming/Kafka ingestion | Data is static; pure over-engineering |
| Heavy deep-learning forecaster (LSTM/Transformer) | 5 months of data → gradient boosting wins; DL is slower to build and not more accurate here |
| User auth / accounts / multi-tenant | Zero demo value in a hackathon |
| Native mobile app | Web demo is enough; splits effort |
| Pixel-perfect custom design system from scratch | Use a themed component kit instead |
| Training a custom LLM / fine-tuning | Use Claude API; fine-tuning is pointless here |

**Rule:** anything in AVOID is *not* discussed in the pitch except as "deliberately out of scope so we could ship a complete product" (turns a cut into a maturity signal).

---

## 4. PHASE 3 — AI/ML Strategy

We have **five** model surfaces. For each, options compared, then the pick.

### 4.1 Hotspot detection (spatial)
| Option | Pros | Cons |
|---|---|---|
| Raw point heatmap (KDE) | trivial | not quantized, weak for ranking/ML |
| **H3 hex aggregation + thresholding** ✅ | uniform, hierarchical, ML-ready, fast | choose resolution |
| DBSCAN / HDBSCAN clusters | finds arbitrary-shape clusters, great visual "zones" | params sensitive; pair with H3 |
| Getis-Ord Gi* hotspot statistics | statistically rigorous "significant hotspot" | extra concept to explain |

**Pick:** **H3 (res 9 ≈ 0.1 km² for street-level hotspots; res 8 for the city heat layer) + DBSCAN to draw named "zones"**, with **Getis-Ord Gi\*** as an optional rigor badge ("statistically significant hotspots, p<0.05"). *Why:* H3 powers both the map and the ML features; DBSCAN gives human-readable zones for the prioritization list; Gi\* is a cheap credibility flex.

### 4.2 PCIS (the impact metric) — see full formula in §5.3 and Appendix A
Not "ML" but a transparent weighted model with tunable weights — judges prefer explainable over black-box here.

### 4.3 Forecasting (temporal / spatio-temporal)
| Option | Pros | Cons |
|---|---|---|
| Climatology baseline (weekday×hour-window mean) | trivial, surprisingly strong | not "ML" alone |
| **LightGBM/XGBoost regressor** ✅ | best accuracy on tabular, fast, feature importance = explainability | needs feature engineering |
| Prophet/ARIMA per cell | nice intervals | thousands of series = slow, overkill |
| LSTM/Temporal-CNN/Transformer | "deep learning" buzz | data-hungry, slow, no accuracy gain here |

**Pick:** **LightGBM** predicting next-day violation count + hotspot probability per (cell, peak-window), **always shown against the climatology baseline** to prove ML adds value. Features: lag-1/7, rolling-7/14 mean, weekday, is_weekend, month, station, hour-window, **Indian-holiday flag** (Nov–Apr covers Christmas, New Year, Sankranti/Pongal, Republic Day, Ramzan run-up). **Confidence** via LightGBM **quantile** models (p10/p50/p90) → "confidence band." *Why:* highest accuracy-per-build-hour, and feature importance is a great explainability slide.

### 4.4 Enforcement prioritization (decision layer)
Rank = f(PCIS, predicted next-day risk, **Enforcement-Gap**). Enforcement-Gap = predicted impact normalized − recent enforcement presence normalized (presence proxied by ticket coverage and distinct `device_id`s active in that cell's peak window). Output High/Med/Low + a generated natural-language *reason* per zone. *Why:* turns analytics into an action a station officer understands.

### 4.5 AI Copilot (NL interface)
| Option | Pros | Cons |
|---|---|---|
| Rule/intent templates → pandas/DuckDB | 100% reliable offline, no key | limited phrasing |
| **Claude API (tool-use) → analytics functions** ✅ | handles free-form NL, explains answers | needs API key, network |
| Text-to-SQL over DuckDB via LLM | flexible | hallucination risk on schema |

**Pick (hybrid, demo-safe):** a **deterministic intent layer** covering the scripted demo questions ("top 10 zones", "highest-congestion hotspot", "where to deploy tomorrow", "chronic offenders near X") **backed by Claude** (`claude-sonnet-4-6` for speed/cost; `claude-opus-4-8` if quality matters more) using **tool-use / function-calling** that invokes our own analytics functions on the precomputed tables and returns grounded numbers. **Always keep the deterministic fallback** so the live demo never dies if the network/API does. *Why:* the copilot is the single highest-wow demo moment; the fallback protects Functionality points.

### Recommended AI stack (final)
**H3 + DBSCAN (+optional Gi\*) for hotspots · explainable weighted PCIS · LightGBM (quantile) for forecasting with climatology baseline · rule+Claude tool-use hybrid copilot.** All trained/precomputed offline; the app loads artifacts. *Why this balances dataset limits (small, tabular, no flow data), build time (boosting + precompute is fast), demo value (maps + copilot), and judge appeal (explainable, baseline-validated, not buzzword-driven).*

---

## 5. PHASE 4 — Best-in-Class System Design (modules)

```
┌──────────────────────────────────────────────────────────────────────┐
│  PARKSIGHT — Parking Congestion Command Center                          │
├───────────────┬───────────────┬───────────────┬───────────────────────┤
│ ① Executive    │ ② AI Hotspot  │ ③ PCIS         │ ④ Prediction          │
│   Dashboard    │   Map          │   Impact Engine│   & Forecast          │
├───────────────┼───────────────┼───────────────┼───────────────────────┤
│ ⑤ Enforcement  │ ⑥ AI Copilot  │ ⑦ Simulator /  │ ⑧ Offender Watchlist  │
│   Prioritizer  │   (NL)         │   What-If      │   + Daily Briefing    │
└───────────────┴───────────────┴───────────────┴───────────────────────┘
        ▲ reads precomputed parquet/JSON artifacts (built by offline ETL+ML)
```

### ① Executive Dashboard
KPI cards: Total Violations (298,450) · Active Hotspots (count of cells above PCIS threshold) · High-Risk Zones (top-N) · Predicted Tomorrow's Top Hotspot · **Estimated Congestion Impact** (citywide PCIS roll-up + assumption-labeled "lane-block-minutes" proxy) · Repeat-offender share (34.2%). Trend spar+lines for monthly/weekday. A bold callout card for the **Evening Blind-Spot**.

### ② AI Hotspot Map
- Dark command-center basemap; **H3 hex heat layer** colored by PCIS (not raw count).
- Toggle layers: raw density · PCIS · DBSCAN "zones" (polygons with names) · spillover (street-segment cells adjacent to high-PCIS junctions) · predicted-tomorrow overlay.
- Time slider (hour-of-day in IST, weekday, month) → animated time-lapse.
- Click a hex/zone → side panel: PCIS breakdown, top violation types, peak hours, top offenders, recommended action.

### ③ PCIS — Parking Congestion Impact Engine (the moat)
Computed per H3 cell, then rolled up to junction & police-station. See §5.3 for the formula.

### ④ Prediction & Forecast
- Tomorrow's top hotspots (ranked, with p10–p90 confidence band).
- "Weekend vs weekday" hotspot shift view.
- Per-zone **24-hour risk curve** (IST), highlighting the evening peak.

### ⑤ Enforcement Prioritization
Ranked High/Med/Low table per police station and per junction with: PCIS, predicted risk, Enforcement-Gap, recommended **time window** + **# patrol units**, and a one-line generated reason. Export to the daily briefing.

### ⑥ AI Copilot
Chat panel answering grounded questions (see §4.5). Returns numbers + a mini-map/table, not just prose.

### ⑦ Smart Enforcement Simulator / What-If
Drag patrol units onto the map (or pick zones + a coverage radius/time-window) and an enforcement-elasticity slider → instantly recompute projected PCIS reduction and "% of citywide impact covered." All assumptions shown on screen.

### ⑧ Offender Watchlist + Daily Briefing
Chronic-offender table (top vehicles, their hotspots, recency). One-click **PDF "Morning Deployment Briefing"**: tomorrow's top 10 zones, time windows, unit counts, watch-list plates.

### 5.3 PCIS formula (designed to be explainable & defensible)

For each spatial cell *c* over a chosen time window:

```
PCIS(c) = 100 × ( wV·V̂(c) + wS·Ŝ(c) + wL·L̂(c) + wP·P̂(c) + wT·T̂(c) )
```
All components normalized to [0,1]; weights sum to 1 (defaults, tunable in UI):

| Comp | Meaning | How computed | Default w |
|---|---|---|---|
| **V̂** Volume | how many violations | log1p(count) then min-max across cells (heavy-tailed → log) | 0.30 |
| **Ŝ** Severity | how much each blocks the carriageway | mean of per-ticket severity weights (main-road/junction/footpath/double/road-crossing/traffic-light = high; no-parking/wrong-parking = base), min-max | 0.20 |
| **L̂** Location criticality | does the spot matter for flow | at-junction flag + address keyword score (Market/Metro/Mall/Bus-stop/School/Hospital/Main Rd) + optional road class | 0.20 |
| **P̂** Peak-hour overlap | does it happen during congestion | share of cell's violations in IST congestion windows (08–11, 17–21) × window weight | 0.20 |
| **T̂** Trend | is it getting worse | sign+magnitude of month-over-month slope (normalized) | 0.10 |

**Why this scores:** (a) it directly answers "quantify impact on traffic flow" without inventing flow data; (b) every term maps to a real traffic-engineering intuition we can defend to a judge; (c) weights are tunable on screen → interactive demo; (d) severity + peak-overlap is what makes a *main-road evening* violation outrank a *residential 3 a.m.* one — exactly the prioritization the statement wants.

**Optional "impact translation" (label as estimate):** EstimatedDelay(c) ≈ Σ severe_violations × avg_lane_block_minutes × demand_factor(peak). State the assumed constants on screen; present as an illustrative proxy, never as measured truth.

---

## 6. PHASE 5 — Judge Wow-Factor (ranked)

| Innovation | Dev effort | Presentation impact | Judge-score potential | Verdict |
|---|---|---|---|---|
| **AI Copilot (grounded NL)** | Med | **Very High** | **Very High** | **Build** |
| **Evening Blind-Spot reveal** (insight, not feature) | **Low** | **Very High** | High | **Build — open the demo with it** |
| **Smart Enforcement Simulator / What-If** | Med | **Very High** | High | **Build** |
| **Daily Deployment Briefing PDF** | Low-Med | High | High | **Build** |
| Hotspot time-lapse animation | Low | High | Med | **Build** |
| Chronic-offender watchlist ("15%→34%") | Low | High | Med-High | **Build** |
| Patrol max-coverage optimizer | Med-High | High | High | Nice-to-have |
| Getis-Ord Gi* "statistically significant hotspots" | Low-Med | Med | Med (credibility) | Nice-to-have |
| Digital-twin / live "command center" mode (simulated live ticker) | Med | High | Med | Nice-to-have (fake-live = risky if judge probes) |
| OSM road-graph spillover propagation (Approach E) | High | Med-High | High | **Roadmap slide only** |

**Demo-day rule:** lead with the **Blind-Spot insight**, end with the **Copilot** asking "where do I deploy tomorrow?" → it answers with a map + the briefing PDF. That bookends the pitch with two memorable moments.

---

## 7. PHASE 6 — UI/UX (enterprise command-center)

### 7.1 Information architecture / navigation
Left rail (icons + labels): **Overview · Hotspot Map · Impact (PCIS) · Forecast · Prioritize · Simulator · Copilot · Offenders**. Top bar: title, date-range + IST time filter, city selector (Bengaluru), "Generate Briefing" button.

### 7.2 Wireframe — Overview (landing)
```
┌───────────────────────────────────────────────────────────────────────┐
│ ParkSight ▸ Bengaluru Traffic Command   [Nov'23–Apr'24 ▾] [Generate ⤓] │
├──────┬────────────────────────────────────────────────────────────────┤
│ N    │ ┌─KPI─┐ ┌─KPI─┐ ┌─KPI─┐ ┌─KPI─┐ ┌─KPI─┐                          │
│ A    │ │298k │ │ 42  │ │ Top │ │34.2%│ │BLIND│   ← KPI cards            │
│ V    │ │Viol.│ │Hot- │ │Zone │ │repeat│ │SPOT │                         │
│      │ └─────┘ └spots┘ └─────┘ └─────┘ └17-21┘                          │
│ rail │ ┌──────────────────────────┐ ┌───────────────────────────────┐  │
│      │ │  Mini hotspot map (PCIS) │ │ Hourly risk curve (IST)        │  │
│      │ │                          │ │   ▁▃▅▇█▇▅▂   ▁▁▁   ▂▅▇█▇        │  │
│      │ └──────────────────────────┘ └───────────────────────────────┘  │
│      │ ┌──────────────────────────┐ ┌───────────────────────────────┐  │
│      │ │ Top 5 priority zones      │ │ Monthly trend + weekday bars  │  │
│      │ └──────────────────────────┘ └───────────────────────────────┘  │
└──────┴────────────────────────────────────────────────────────────────┘
```

### 7.3 Wireframe — Hotspot Map
```
┌───────────────────────────────────────────────────────────────────────┐
│ Layers: [✓PCIS hex][ Density][ Zones][ Spillover][ Predicted]  Time ◀▮▶ │
├───────────────────────────────────────────────┬───────────────────────┤
│                                                │  ZONE DETAIL          │
│      (dark map, glowing H3 hexes by PCIS)      │  KR Market Jn         │
│            ● clustered "zones"                 │  PCIS 92  ▲ worsening │
│                                                │  V .9 S .7 L .9 P .8  │
│                                                │  Peak 18–20 IST       │
│                                                │  Top: MAIN ROAD,DOUBLE│
│                                                │  Rec: 2 units 17–21   │
└───────────────────────────────────────────────┴───────────────────────┘
```

### 7.4 Component hierarchy
```
App
 ├─ Shell (LeftNav, TopBar, GlobalFilters[date,time,severity,vehicle])
 ├─ pages/Overview        → KpiCard×5, MiniMap, RiskCurve, PriorityTable, TrendCharts
 ├─ pages/HotspotMap      → DeckMap(layers), TimeSlider, LayerToggles, ZoneDetailPanel
 ├─ pages/Impact          → PcisExplainer, WeightSliders, PcisRankTable, Breakdown
 ├─ pages/Forecast        → ForecastMap, ConfidenceBand, NextDayTable
 ├─ pages/Prioritize      → StationTable, JunctionTable, ReasonChips
 ├─ pages/Simulator       → DeckMap(editable units), ElasticitySlider, ImpactDeltaCards
 ├─ pages/Copilot         → ChatPanel, GroundedAnswer(map/table/number)
 └─ pages/Offenders       → OffenderTable, OffenderMap, Watchlist export
```

### 7.5 Visual system
- **Theme:** dark "operations" UI. Background `#0B0F1A`/`#111827`, panels `#1B2333`, text `#E5E7EB`.
- **Accent / risk ramp:** low `#22D3EE` (cyan) → med `#FACC15` (amber) → high `#F97316` → critical `#EF4444`; primary action `#6366F1`. Sequential map ramp via a perceptual scale (viridis/magma for hexes).
- **Type:** Inter / IBM Plex Sans. Numbers in tabular figures.
- **KPI cards:** big number, label, delta vs prior month, sparkline.
- **Charts:** hour curve (area), monthly trend (line), weekday (bar), violation mix (treemap/donut), PCIS breakdown (radial/stacked bar), feature importance (horizontal bar).
- **Maps:** deck.gl H3HexagonLayer (PCIS), ScatterplotLayer (raw), PolygonLayer (zones), dark Carto/Mapbox basemap.

**Why this scores:** UX/Demo is 15%. A dark, dense, KPI-driven layout *reads as "real city software"* in the first 5 seconds — that perception alone lifts Impact + Presentation scores.

---

## 8. PHASE 7 — Tech-Stack Decision

| Option | Stack | Build speed | Demo quality | Risk (5.5 days) | Verdict |
|---|---|---|---|---|---|
| A | Python · **Streamlit · Plotly · Folium** | **Fastest** | Good (Folium = basic maps) | Low | strong floor; maps look "okay" |
| A+ | Python · **Streamlit · pydeck(deck.gl) · Plotly · DuckDB** ✅ | Fast | **High** (same deck.gl visuals as React) | Low | **RECOMMENDED** |
| B | FastAPI · React · Leaflet · Postgres | Slow | High | **High** (full-stack + DB in 5 days) | over-scoped |
| C | Next.js · Supabase · Mapbox | Medium-slow | **Very High** | Med-High | stretch only |
| D-rec | **A+ core, optional thin Next.js+deck.gl shell for the Map page if ahead** | — | — | — | **best balance** |

**Recommendation:** **Streamlit + pydeck + Plotly + DuckDB**, deployed on **Streamlit Community Cloud** (or Hugging Face Spaces). DuckDB queries the precomputed parquet instantly; pydeck gives *the same deck.gl maps* a React app would, so we get near-Mapbox polish without front-end overhead. Claude API powers the copilot. **Why:** maximizes Functionality (it *will* be done and deployed) and Demo quality together, with the lowest risk — and judges score the *insight + working product*, not the framework. The Next.js/deck.gl rebuild of just the map page is a clearly-scoped stretch, not a dependency.

**Repo/runtime:** Python 3.12 · `uv`/`pip` + `requirements.txt` · `pyarrow`/`duckdb` · `h3` · `scikit-learn` · `lightgbm` · `pydeck` · `plotly` · `streamlit` · `anthropic` · `reportlab`(PDF). Precompute step is a script; app loads artifacts (<50 MB → fits submission limit).

---

## 9. PHASE 8 — Submission Optimization

**Title (primary):** **"ParkSight — AI Parking-Congestion Intelligence for Targeted Enforcement"**
Alternates: "ParkSight: From Reactive Patrols to Predictive Enforcement" · "GridSight" · "ClearWay".

**Elevator pitch (30s):** *"Bengaluru writes ~2,000 parking tickets a day but still can't see where illegal parking actually chokes traffic — and enforcement goes dark every evening just as congestion peaks. ParkSight turns 298,450 violations into a live Parking Congestion Impact Score map, predicts tomorrow's hotspots, and hands each station a deployment plan. It's the heatmap, the forecast, and the dispatcher the city doesn't have today."*

**Judge-facing description (structure):** Problem → Insight (blind spot, 15%→34% offenders) → What it does (8 modules) → **PCIS methodology + honest data caveats** → Tech & scalability (H3 + precompute) → Impact ("a station officer gets a ranked plan in one click") → Roadmap (OSM spillover, live ITMS/SCITA integration).

**Demo storyline (≈2.5 min video):**
1. (0:00) Cold open on the **blind-spot** chart — "the city stops watching at 5 PM."
2. (0:20) Overview dashboard — KPIs, citywide PCIS.
3. (0:45) Hotspot map — toggle PCIS, scrub the time-lapse, click KR Market → breakdown.
4. (1:20) Forecast — tomorrow's top hotspots with confidence.
5. (1:40) Prioritize → **Simulator**: drop 3 units, watch projected impact drop.
6. (2:05) **Copilot**: "Where should I deploy teams tomorrow evening?" → map + briefing PDF.
7. (2:25) Close on the one-line vision + roadmap.

**Pitch deck (10–12 slides):** Title · Problem & why-hard · **The insight** (blind spot) · Dataset (298k, real numbers) · Solution overview (8 modules, 1 screenshot) · **PCIS** (formula + intuition) · Prediction (model + baseline + importance) · Prioritization & Simulator · Architecture (H3+precompute+ML+app, scalable) · Impact & smart-city fit · Limitations & honesty slide (earns trust) · Roadmap + ask.

**GitHub structure:**
```
parksight/
├─ README.md            # hero gif, problem, features, run steps, screenshots, architecture
├─ requirements.txt
├─ data/                # (gitignored raw csv) + processed/*.parquet (small)
├─ etl/                 # 01_clean.py 02_h3_index.py 03_pcis.py 04_features.py
├─ models/              # train_forecast.py, artifacts/*.pkl, metrics.json
├─ app/                 # streamlit app: Home.py + pages/, components/, theme/
├─ copilot/             # intents.py + claude_tools.py (+ offline fallback)
├─ reports/             # briefing_pdf.py
├─ assets/              # screenshots, logo, demo.gif
└─ docs/                # SKILL.md (this), PCIS_METHODOLOGY.md, DATA_PROFILE.md
```

**Video:** 2.5–3 min, screen-record + voiceover; captions; export <50 MB or host on YouTube/Drive (use the URL field).
**Screenshots needed (Snapshots field):** Overview KPIs · Hotspot map with detail panel · PCIS weight-slider view · Forecast with confidence · Simulator before/after · Copilot answer · Briefing PDF.
**Instructions-to-run:** `pip install -r requirements.txt` → `python etl/run_all.py` (or "artifacts pre-built in data/processed") → `streamlit run app/Home.py` → optional `ANTHROPIC_API_KEY` for live copilot (fallback works without).

**Why this scores:** the submission fields are graded too. A crisp title + honest methodology + a story-driven video + a clean README with a hero GIF is often the difference between top-10 and top-3.

---

## 10. PHASE 9 — Implementation Roadmap (day-by-day, ~5.5 days)

Priorities: **P0** = MVP-critical, **P1** = high-impact, **P2** = wow/stretch. Effort in hours.

### Day 1 — Foundation & ETL (P0)
| Task | Output | Deps | Pri | Effort |
|---|---|---|---|---|
| Repo scaffold, env, requirements, theme tokens | runnable skeleton | — | P0 | 1.5 |
| ETL clean: drop dead cols, parse violation_type/offence JSON, **UTC→IST**, dedupe | clean dataframe | — | P0 | 2.5 |
| H3 indexing (res 8 + 9), spatial joins to station/junction | indexed parquet | clean | P0 | 2 |
| Aggregation cubes (cell×hour×weekday×month) → parquet artifacts | small parquet (<50 MB) | h3 | P0 | 2 |
| `DATA_PROFILE.md` from eda output | doc | eda | P1 | 1 |

### Day 2 — PCIS + Core Map + KPIs (P0)
| Task | Output | Deps | Pri | Effort |
|---|---|---|---|---|
| Severity weight table + L̂ keyword scorer | severity/location features | ETL | P0 | 1.5 |
| **PCIS engine** (V,S,L,P,T → score) at hex/junction/station | pcis parquet | aggregates | P0 | 3 |
| Streamlit shell + nav + global filters + dark theme | app skeleton | scaffold | P0 | 2 |
| pydeck H3 hotspot map (PCIS layer) + zone detail panel | working map page | pcis | P0 | 3 |
| Executive dashboard KPI cards + charts | overview page | pcis | P0 | 2 |

### Day 3 — Prediction + Prioritization (P0/P1)
| Task | Output | Deps | Pri | Effort |
|---|---|---|---|---|
| Feature build (lags, rolling, weekday, holiday flag) | feature matrix | aggregates | P1 | 2 |
| **LightGBM** count + quantile models; climatology baseline; metrics.json | model + metrics | features | P1 | 3 |
| Forecast page (next-day map, confidence band, 24h risk curve) | forecast page | model | P1 | 2.5 |
| Enforcement-Gap + prioritization ranking + reasons | prioritize page | pcis+forecast | P0 | 2.5 |
| DBSCAN named zones overlay + time-lapse animation | map enhancements | map | P1 | 2 |

### Day 4 — Wow layer (P1/P2)
| Task | Output | Deps | Pri | Effort |
|---|---|---|---|---|
| Offender watchlist page + map | offenders page | ETL | P1 | 2 |
| **Simulator / What-If** (editable units, elasticity, impact delta) | simulator page | pcis | P2 | 3.5 |
| **Daily Deployment Briefing** PDF (reportlab) | PDF export | prioritize | P1 | 2 |
| **AI Copilot**: intents + Claude tool-use + offline fallback | copilot page | analytics | P2 | 3.5 |

### Day 5 — Polish, deploy, content (P0/P1)
| Task | Output | Deps | Pri | Effort |
|---|---|---|---|---|
| Visual QA, empty/loading states, mobile-ish responsiveness | polished app | all | P0 | 2.5 |
| **Deploy** to Streamlit Cloud / HF Spaces; smoke-test | live demo link | app | P0 | 1.5 |
| README hero GIF + screenshots + architecture diagram | repo content | app | P0 | 2 |
| Pitch deck (10–12 slides) | presentation | all | P0 | 3 |
| Record + edit demo video to script | video URL | deploy | P0 | 2.5 |

### Day 6 (half) — Buffer & submit (P0)
| Task | Output | Pri | Effort |
|---|---|---|---|
| Bug-fix buffer / judge-proofing (test scripted copilot Qs) | stable demo | P0 | 2 |
| Final submission form (title, desc, links, files, run steps) | submitted | P0 | 1.5 |
| `PCIS_METHODOLOGY.md` + limitations write-up | docs | P1 | 1 |

**Critical path:** ETL → H3 → PCIS → Map/Dashboard → Forecast → Prioritization → **deploy** → deck/video. If behind, cut in this order: Simulator → Copilot-LLM (keep offline copilot) → Gi\*/optimizer. **Never cut deploy, deck, or video.**

---

## 11. PHASE 10 — Build Readiness (project structure & contracts — code on your go-ahead)

> Per the mandate, no production code yet. This is the agreed structure and the data contracts so Phase-10 coding is mechanical.

**Artifact contracts (what ETL must emit for the app):**
- `data/processed/violations_clean.parquet` — row-level, IST datetimes, parsed tags, h3_r8, h3_r9, severity, is_severe, station, junction, is_repeat.
- `data/processed/cell_pcis.parquet` — h3_r9, V,S,L,P,T, PCIS, lat, lon, top_types, peak_hour.
- `data/processed/station_pcis.parquet`, `junction_pcis.parquet` — rolled-up + rank + tier + reason.
- `data/processed/forecast.parquet` — cell/zone, date, window, pred, p10, p50, p90, baseline.
- `data/processed/offenders.parquet` — vehicle, count, last_seen, top_cell, types.
- `models/artifacts/lgbm_*.pkl`, `models/metrics.json`.

**Copilot tool functions (grounded):** `top_zones(n, by, window)`, `zone_detail(name)`, `where_to_deploy(date, window, units)`, `offenders_near(area, n)`, `impact_if(enforcement_delta_pct, zones)`.

**Definition of done (MVP):** deployed app where a judge can: see KPIs → explore the PCIS hotspot map with time slider → read tomorrow's forecast with confidence → get a ranked deployment plan → export the briefing PDF. Everything else is bonus.

---

## 12. Risk Register & Mitigations
| Risk | Likelihood | Mitigation |
|---|---|---|
| Over-scoping → nothing finished | High | C-core first; wow features are P2; strict cut-order |
| "Where's the traffic data?" challenge | High | Lead with honest PCIS-proxy framing + limitations slide |
| Live copilot/API fails on demo day | Med | Deterministic offline fallback always on |
| Map/deploy perf with big data | Med | Precompute to small parquet; never ship the 109 MB raw |
| Misread timezone → wrong insights | Med | UTC→IST in ETL, unit-tested; the blind-spot finding depends on it |
| Forecast looks weak | Med | Always show vs. climatology baseline + feature importance |
| Submission file >50 MB | Low | Ship aggregates, not raw; host video externally |

## 13. Appendix A — PCIS defaults & severity weights (starting point, tune in UI)
Severity weights: MAIN ROAD 1.0 · NEAR ROAD CROSSING 0.95 · NEAR TRAFFIC LIGHT/ZEBRA 0.95 · DOUBLE PARKING 0.9 · FOOTPATH 0.85 · NEAR BUS-STOP/SCHOOL/HOSPITAL 0.8 · OPPOSITE PARKED VEH 0.7 · OTHER-THAN-BUS-STOP 0.6 · WRONG PARKING 0.5 · NO PARKING 0.4 · (non-parking tags) 0.1.
Location keywords (+L̂): market, metro, mall, bus, school, hospital, main road, circle, junction, station, temple, theatre.
IST congestion windows: morning 08:00–11:00 (weight 0.9), evening 17:00–21:00 (weight 1.0), else 0.3.
PCIS weights: wV .30, wS .20, wL .20, wP .20, wT .10 (UI-tunable; document any change in the deck).

---

### TL;DR for the team
Build **ParkSight** = C-core (PCIS hotspot map + forecast + prioritization) + three wow features (copilot, simulator, briefing PDF), on **Streamlit + pydeck + LightGBM + Claude**, precomputed via H3. Open the pitch with the **evening blind-spot**, close with the **copilot deploying tomorrow's teams**. Ship a deployed demo + clean repo + story-driven video. Be honest about the no-traffic-data limitation — PCIS is the credible answer to it, and that honesty is itself a scoring edge.

"""
ParkSight AI Copilot — natural-language interface over the precomputed analytics.

Three layers (tried in order):
  1. Claude  — when ANTHROPIC_API_KEY is set.
  2. Gemini  — when GOOGLE_API_KEY is set (fallback if no Claude key).
  3. Deterministic intent engine — always available, 100% grounded, demo-safe.

Both AI layers only map NL → {intent, params} from a whitelist. Execution always
runs through the same audited deterministic functions — no hallucinated statistics.

Returns a dict: {"text": str, "table": DataFrame|None, "map": DataFrame|None, "engine": str}
"""
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from parksight import config as C  # noqa: E402
from parksight import scoring  # noqa: E402

CLAUDE_MODEL  = "claude-sonnet-4-6"    # fast + cheap; grounded execution keeps it accurate
GEMINI_MODEL  = "gemini-1.5-flash"    # free-tier friendly fallback

# Per-call context set by answer(): a custom PCIS policy + elasticity from the
# dashboard, so the Copilot's numbers match the rest of the app instead of always
# using the ETL defaults. Reset after every call (single-threaded Streamlit reruns).
_CTX = {"weights": None, "elasticity": None}


@lru_cache(maxsize=None)
def _load(name):
    return pd.read_parquet(C.PROCESSED / name)


def _scored(name):
    """Load a grain file, re-scoring PCIS/tier from the active custom policy (if the
    user applied one on the dashboard) so Copilot agrees with every other tab."""
    df = _load(name).copy()
    w = _CTX.get("weights")
    if w and set("VSLPT").issubset(df.columns):
        df, _ = scoring.recompute_pcis(df, w)
        df["PCIS"] = df["PCIS_live"]
        df["tier"] = scoring.assign_tier(df["PCIS"]).to_numpy()
    return df


def _elasticity():
    return _CTX.get("elasticity") or C.DETERRENCE_ELASTICITY


@lru_cache(maxsize=1)
def _meta():
    return json.loads((C.PROCESSED / "meta.json").read_text())


# ----------------------------------------------------------------- intents
def top_zones(n=10, grain="junction"):
    f = {"junction": "junction_pcis.parquet", "station": "station_pcis.parquet",
         "zone": "zones.parquet"}.get(grain, "junction_pcis.parquet")
    df = _scored(f)
    name_col = ("junction_name" if grain == "junction"
                else "police_station" if grain == "station" else "name")
    cols = [c for c in [name_col, "PCIS", "violations", "tier", "reason"] if c in df.columns]
    out = df.sort_values("PCIS", ascending=False).head(n)[cols]
    return (f"Top {n} parking-congestion {grain}s by PCIS (Parking Congestion Impact "
            f"Score). #1 is **{out.iloc[0][name_col]}** at PCIS {out.iloc[0]['PCIS']}.",
            out.reset_index(drop=True))


def rank_at(position=1, grain="junction"):
    """Return the single zone at a specific rank position (e.g. 'the 12th area')."""
    f = {"junction": "junction_pcis.parquet", "station": "station_pcis.parquet",
         "zone": "zones.parquet"}.get(grain, "junction_pcis.parquet")
    df = _scored(f).sort_values("PCIS", ascending=False).reset_index(drop=True)
    name_col = ("junction_name" if grain == "junction"
                else "police_station" if grain == "station" else "name")
    pos = max(1, min(int(position), len(df)))
    r = df.iloc[pos - 1]
    ordn = {1: "1st", 2: "2nd", 3: "3rd"}.get(pos, f"{pos}th")
    txt = (f"The **{ordn} highest-impact {grain}** by PCIS is **{r[name_col]}** "
           f"(PCIS {r['PCIS']}, {int(r['violations']):,} violations, {r.get('tier','')} tier). "
           f"{str(r.get('reason','')).capitalize()}.")
    cols = [c for c in [name_col, "PCIS", "violations", "tier", "reason"] if c in df.columns]
    # show the target row plus one neighbour either side for context
    lo, hi = max(0, pos - 2), min(len(df), pos + 1)
    return txt, df.iloc[lo:hi][cols].reset_index(drop=True)


def highest_congestion():
    j = _scored("junction_pcis.parquet").sort_values("PCIS", ascending=False)
    r = j.iloc[0]
    txt = (f"The single highest-impact parking hotspot is **{r['junction_name']}** "
           f"(PCIS {r['PCIS']}, {int(r['violations']):,} violations). "
           f"Why it ranks #1: {r['reason']}.")
    return txt, j.head(5)[["junction_name", "PCIS", "violations", "tier", "reason"]].reset_index(drop=True)


def _allocate_units(scores, total):
    """Split a fixed budget of `total` whole patrol units across rows in
    proportion to `scores`, using the largest-remainder method so the parts sum
    to exactly `total`. Returns an int list aligned to `scores`."""
    import numpy as np
    w = scores.clip(lower=0).to_numpy(dtype=float)
    if w.sum() <= 0 or total <= 0:
        return [0] * len(w)
    raw = w / w.sum() * total
    base = np.floor(raw).astype(int)
    for i in np.argsort(-(raw - base))[: int(total - base.sum())]:
        base[i] += 1
    return base.tolist()


def _deploy_window(window):
    key = "morning" if window == "morning" else "evening"
    lo, hi, _ = C.PEAK_WINDOWS[key]
    return f"{lo:02d}:00–{hi:02d}:00 IST ({key} peak)"


def where_to_deploy(window="evening", n=8, units=None):
    """NAIVE operational ranking by raw congestion impact (PCIS).

    Deliberately ranks by PCIS, NOT the Blind-Spot index — the de-biased view
    (blind_spot_deploy) corrects the evening enforcement gap and produces a
    *different* order on purpose. If `units` is given, that exact budget is split
    across the top stations in proportion to PCIS (sums to the budget)."""
    st = _scored("station_pcis.parquet").sort_values("PCIS", ascending=False)
    win = _deploy_window(window)
    if units:
        pool = st.head(min(len(st), max(int(units), n))).copy()
        pool["units"] = _allocate_units(pool["PCIS"], int(units))
        pool = pool[pool["units"] > 0]
        pool["recommended_window"] = win
        txt = (f"With a budget of **{int(units)} patrol units** for the **{win}** window, "
               f"here's the PCIS-proportional allocation across these {len(pool)} stations "
               f"(units sum to {int(pool['units'].sum())}). Higher PCIS ⇒ more units. "
               f"*Tip: ask for the **de-biased** allocation to shift units toward hidden "
               f"evening hotspots.*")
        cols = [c for c in ["police_station", "PCIS", "tier", "units",
                            "recommended_window", "reason"] if c in pool.columns]
        return txt, pool[cols].reset_index(drop=True)
    st = st.head(n).copy()
    st["recommended_window"] = win
    st["units"] = scoring.recommended_units(st["PCIS"]).to_numpy()
    txt = (f"Recommended deployment for the **{win}** window — these {n} stations rank highest by "
           f"**raw congestion impact (PCIS)**, sorted by the PCIS column below. Patrol units scale "
           f"with PCIS. *Tip: ask for the **de-biased** ranking to surface evening hotspots that "
           f"raw counts hide — it reshuffles this list.*")
    cols = [c for c in ["police_station", "PCIS", "tier",
                        "recommended_window", "units", "reason"] if c in st.columns]
    return txt, st[cols].reset_index(drop=True)


def blind_spot_deploy(n=8, units=None):
    """Explicitly de-biased deploy-here ranking (Blind-Spot index).

    If `units` is given, the budget is split across the top stations in
    proportion to the Blind-Spot index (sums to the budget)."""
    st = _scored("station_pcis.parquet")
    if "blindspot_risk" not in st.columns:
        return where_to_deploy("evening", n, units)
    st = st.sort_values("blindspot_risk", ascending=False)
    if units:
        pool = st.head(min(len(st), max(int(units), n))).copy()
        pool["units"] = _allocate_units(pool["blindspot_risk"], int(units))
        pool = pool[pool["units"] > 0]
        txt = (f"**De-biased allocation of {int(units)} patrol units (Blind-Spot index).** "
               f"Units are split across these {len(pool)} stations in proportion to the "
               f"inverse-propensity-corrected risk (sums to {int(pool['units'].sum())}), so the "
               f"evening enforcement gap can't hide hotspots from the budget.")
        cols = [c for c in ["police_station", "blindspot_risk", "PCIS", "units",
                            "ipw_uplift", "reason"] if c in pool.columns]
        return txt, pool[cols].reset_index(drop=True)
    st = st.head(n)
    r = st.iloc[0]
    txt = (f"**De-biased deploy-here ranking (Blind-Spot index).** #1 is "
           f"**{r['police_station']}** (Blind-Spot {r['blindspot_risk']}, PCIS {r['PCIS']}). "
           f"This corrects the enforcement feedback loop: tickets collapse in the evening, so we "
           f"inverse-propensity-weight by hourly exposure (up to ×{_meta().get('debias_max_ipw_uplift', 2.8)}) "
           f"and compare against an external congestion prior — surfacing hotspots the raw counts hide.")
    cols = [c for c in ["police_station", "blindspot_risk", "PCIS", "ipw_uplift",
                        "divergence", "reason"] if c in st.columns]
    return txt, st[cols].reset_index(drop=True)


def offenders_near(area=None, n=10):
    off = _load("offenders.parquet").copy()
    matched = False
    where = ""
    if area:
        area = str(area).strip()
        loc = (off["top_station"].fillna("") + " " + off["top_junction"].fillna("")).str.lower()
        m = loc.str.contains(re.escape(area.lower()), na=False)
        if not m.any():  # fall back to significant-token overlap (e.g. "elite junction")
            toks = [t for t in re.findall(r"[a-z0-9]+", area.lower())
                    if len(t) > 2 and t not in _LOOKUP_STOP]
            if toks:
                m = loc.apply(lambda s: any(t in s for t in toks))
        if m.any():
            off, matched = off[m], True
            where = f" near **{area}**"
    out = off.sort_values("violations", ascending=False).head(n)
    note = ("" if matched or not area else
            f" *(no offenders are linked to “{area}” — showing the citywide leaders instead)*")
    txt = (f"Top {len(out)} chronic parking offenders{where}. The worst vehicle has "
           f"{int(out.iloc[0]['violations'])} violations. Repeat offenders cause "
           f"{_meta()['repeat_share']}% of all violations citywide.{note}")
    cols = [c for c in ["vehicle_number", "vehicle_type", "violations", "severe_n",
                        "top_station", "top_junction", "last_seen"] if c in out.columns]
    return txt, out[cols].reset_index(drop=True)


def impact_if(delta_pct=20):
    """Scenario: extra enforcement in top zones → estimated violation reduction."""
    st = _scored("station_pcis.parquet").sort_values("PCIS", ascending=False).head(10)
    # transparent, documented elasticity (shared default; matches the Simulator slider)
    elasticity = _elasticity()
    reduced = st["violations"].sum() * (delta_pct / 100) * elasticity
    txt = (f"**What-if:** increasing enforcement by **{delta_pct}%** in the top-10 PCIS "
           f"stations could prevent roughly **{int(reduced):,} violations** over a comparable "
           f"period (assuming a {elasticity:g} deterrence elasticity — a documented, tunable assumption). "
           f"That targets the {st['violations'].sum():,} violations these zones generate today.")
    return txt, st[["police_station", "PCIS", "violations"]].reset_index(drop=True)


def blind_spot():
    hp = _load("hourly_profile.parquet")
    by_hour = hp.groupby("hour")["n"].sum().reindex(range(24), fill_value=0)
    low = [h for h in range(12, 24) if by_hour[h] < 0.15 * by_hour.max()]
    x0, x1 = (min(low), min(max(low) + 1, 24)) if low else (15, 24)
    span = int(by_hour.loc[x0:x1 - 1].sum()); peak = int(by_hour.max())
    txt = (f"**Enforcement blind-spot:** violation records collapse during IST "
           f"**{x0:02d}:00–{x1:02d}:00** — across the afternoon/evening commercial-congestion peak. "
           f"Only {span:,} records span those {x1 - x0} hours vs a single-hour peak of {peak:,}. "
           f"Low tickets here mean low *enforcement visibility*, not low violations — exactly the gap "
           f"ParkSight closes by redeploying into this window.")
    return txt, None


_LOOKUP_STOP = {
    "number", "numbers", "violations", "violation", "how", "many", "much", "what",
    "whats", "is", "are", "the", "of", "in", "at", "for", "about", "tell", "me",
    "show", "pcis", "give", "near", "and", "to", "a", "an", "please", "stats",
    "statistic", "statistics", "details", "detail", "info", "information", "on",
    "score", "count", "total", "there", "have", "has", "do", "does", "this",
    "that", "which", "get", "find", "lookup", "look", "up", "data",
}


def _match_place(df, name_col, query):
    """Best-effort match of a free-text place against a name column.

    Returns (score, row) where score>0 means a real match. Matches a BTP code
    (e.g. 'btp40' → 'BTP040') exactly, otherwise ranks rows by how many
    significant query tokens appear in the name, breaking ties by violation
    volume. Score 0 ⇒ no usable match."""
    names = df[name_col].fillna("").str.lower()
    num = re.search(r"btp\s*0*(\d{1,3})", query.lower())
    if num:
        pat = re.compile(rf"btp0*{int(num.group(1))}\b")
        hit = df[names.str.contains(pat, regex=True, na=False)]
        if len(hit):
            return 99, hit.iloc[0]
    tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower())
              if len(t) > 2 and t not in _LOOKUP_STOP]
    if not tokens:
        return 0, None
    score = names.apply(lambda s: sum(t in s for t in tokens))
    if int(score.max()) == 0:
        return 0, None
    idx = df.assign(_s=score, _v=df.get("violations", 0)) \
            .sort_values(["_s", "_v"], ascending=False).index[0]
    return int(score.max()), df.loc[idx]


def lookup_zone(name=None):
    """Answer a question about ONE specific named junction / station / BTP code."""
    if not name or not str(name).strip():
        return overview()
    name = str(name).strip()
    j = _scored("junction_pcis.parquet")
    s = _scored("station_pcis.parquet")
    js, jr = _match_place(j, "junction_name", name)
    ss, sr = _match_place(s, "police_station", name)

    if max(js, ss) == 0:
        txt = (f"I couldn't find a junction or station matching **“{name}”** in the "
               f"dataset. Here are the highest-impact junctions instead — try one of "
               f"these names or a BTP code (e.g. *BTP082*).")
        _, tbl = top_zones(8, "junction")
        return txt, tbl

    if js >= ss:  # junction match wins ties (finer grain)
        r = jr
        rank = f" — ranked #{int(r['rank'])} of {len(j)} junctions" if "rank" in j.columns else ""
        txt = (f"**{r['junction_name']}** has **{int(r['violations']):,} violations** "
               f"(PCIS {r['PCIS']}, {r['tier']} tier{rank}). {str(r.get('reason','')).capitalize()}.")
        cols = [c for c in ["junction_name", "PCIS", "violations", "tier", "reason"]
                if c in j.columns]
        return txt, j.loc[[r.name], cols].reset_index(drop=True)

    r = sr
    txt = (f"**{r['police_station']}** police-station limits recorded "
           f"**{int(r['violations']):,} violations** (PCIS {r['PCIS']}, {r['tier']} tier). "
           f"{str(r.get('reason','')).capitalize()}.")
    cols = [c for c in ["police_station", "PCIS", "violations", "tier", "reason"]
            if c in s.columns]
    return txt, s.loc[[r.name], cols].reset_index(drop=True)


def overview():
    m = _meta()
    txt = (f"ParkSight covers **{m['total_violations']:,} parking violations** "
           f"({m['date_min']} → {m['date_max']}) across {m['n_stations']} police stations and "
           f"{m['n_junctions']} junctions. {m['n_hotspots']} high-impact hotspot cells detected. "
           f"Repeat offenders drive {m['repeat_share']}% of violations; "
           f"{m['severe_share']}% are carriageway-blocking. Top station: **{m['top_station']}**.")
    return txt, None


# ----------------------------------------------------------------- router
# WHITELIST: the LLM may only SELECT one of these audited functions and supply
# typed params. It never sees the database, never writes SQL, never executes code.
INTENTS = {
    "top_zones": top_zones, "highest_congestion": highest_congestion,
    "where_to_deploy": where_to_deploy, "blind_spot_deploy": blind_spot_deploy,
    "offenders_near": offenders_near, "impact_if": impact_if,
    "blind_spot": blind_spot, "overview": overview, "lookup_zone": lookup_zone,
    "rank_at": rank_at,
}

# Allowed params per intent — anything else from the LLM is dropped (hard guardrail).
INTENT_SPEC = {
    "top_zones": {"n": "int", "grain": "junction|station|zone"},
    "highest_congestion": {},
    "where_to_deploy": {"window": "morning|evening", "n": "int", "units": "int|null"},
    "blind_spot_deploy": {"n": "int", "units": "int|null"},
    "offenders_near": {"area": "str|null", "n": "int"},
    "impact_if": {"delta_pct": "int"},
    "blind_spot": {}, "overview": {},
    # one specific named junction/station/BTP code (e.g. "violations in KR Market")
    "lookup_zone": {"name": "str"},
    # the zone at a specific rank position (e.g. "the 12th worst area")
    "rank_at": {"position": "int", "grain": "junction|station|zone"},
}

SUGGESTIONS = [
    "Show the top 10 illegal parking zones",
    "How many violations in KR Market Junction?",
    "Which hotspot causes the highest congestion?",
    "Where should we deploy in the evening (de-biased)?",
    "Show chronic offenders near Shivajinagar",
    "What happens if we increase enforcement by 20%?",
]


def _extract_place(q):
    """Pull a specific place reference out of a question, or None.

    Triggers on an explicit BTP code, or a 'how many … in/at/for/of <place>'
    style phrase. Returns the raw place text for _match_place to resolve."""
    ql = q.lower()
    if re.search(r"\bbtp\s*0*\d{1,3}\b", ql):
        return q  # let _match_place pick the code out of the full question
    lookupish = any(k in ql for k in
                    ["violation", "how many", "number of", "tell me about",
                     "info on", "details", "stats", "pcis of", "pcis for",
                     "pcis in", "about ", "ticket"])
    if not lookupish:
        return None
    m = re.search(r"\b(?:in|at|for|of|about|around)\s+(.+?)(?:\?|\.|$)", q, re.I)
    place = m.group(1).strip(" ?.") if m else None
    return place or None


def _extract_units(ql):
    """Patrol-unit budget from phrases like '12 units' / 'only 12' / 'with 20 patrols'."""
    um = (re.search(r"(\d{1,3})\s*(?:units?|patrols?|teams?|vehicles?|officers?|cars?|cops?)", ql)
          or re.search(r"\b(?:have|only|with|got|using|use|budget of)\s+(\d{1,3})\b", ql))
    return int(um.group(1)) if um else None


def _rule_route(q):
    """Deterministic NL → structured plan {intent, params}. No execution here."""
    ql = q.lower()
    num = re.search(r"\b(\d{1,3})\b", ql)
    n = int(num.group(1)) if num else 10
    if any(k in ql for k in ["blind", "trough", "evening gap", "5 pm", "5pm"]):
        if "deploy" in ql or "where" in ql or "patrol" in ql:
            return {"intent": "blind_spot_deploy", "params": {"n": n, "units": _extract_units(ql)}}
        return {"intent": "blind_spot", "params": {}}
    if "%" in ql or "increase" in ql or "what if" in ql or "what happens" in ql:
        return {"intent": "impact_if", "params": {"delta_pct": int(num.group(1)) if num else 20}}
    if "deploy" in ql or "where should" in ql or "send teams" in ql or "patrol" in ql:
        units = _extract_units(ql)
        if any(k in ql for k in ["de-bias", "debias", "blind", "unbiased", "corrected"]):
            return {"intent": "blind_spot_deploy", "params": {"n": n, "units": units}}
        return {"intent": "where_to_deploy",
                "params": {"window": "morning" if "morning" in ql else "evening", "units": units}}
    # Offenders = vehicles. Catch offender/offence/offense/repeat/chronic/vehicle
    # AND phrasings like "who has the most …", before the 'highest' junction branch.
    if (any(k in ql for k in ["offend", "offens", "offenc", "repeat", "chronic",
                              "vehicle", "number plate", "registration"])
            or re.search(r"\bwho (?:has|is|are)\b", ql)):
        m = re.search(r"\b(?:near|in|at|around|within|inside)\s+(?:the\s+)?(.+?)(?:\?|\.|$)", ql)
        area = m.group(1).strip(" ?.").title() if m else None
        return {"intent": "offenders_near", "params": {"area": area, "n": n}}
    # Ordinal / rank-position query: "the 12th area", "number 3 junction", "#5 station".
    om = (re.search(r"\b(\d{1,3})\s*(?:st|nd|rd|th)\b", ql)
          or re.search(r"\b(?:number|rank(?:ed)?|position|no\.?|#)\s*(\d{1,3})\b", ql))
    if om and any(k in ql for k in ["area", "zone", "junction", "station", "hotspot",
                                    "violation", "congest", "parking", "place", "worst", "spot"]):
        return {"intent": "rank_at",
                "params": {"position": int(om.group(1)),
                           "grain": "station" if "station" in ql else "junction"}}
    # Specific-place lookup: a BTP code, or a "<verb> ... <prep> <place>" question.
    # Checked before the generic top/highest fallbacks so named places don't get
    # swallowed into the city-wide ranking.
    place = _extract_place(q)
    if place and ("highest" not in ql and "top" not in ql):
        return {"intent": "lookup_zone", "params": {"name": place}}
    if "highest" in ql or "worst" in ql or "most congest" in ql:
        return {"intent": "highest_congestion", "params": {}}
    if "top" in ql or "zone" in ql or "hotspot" in ql:
        return {"intent": "top_zones", "params": {"n": n, "grain": "station" if "station" in ql else "junction"}}
    if "overview" in ql or "summary" in ql or "total" in ql:
        return {"intent": "overview", "params": {}}
    return {"intent": "top_zones", "params": {"n": 10, "grain": "junction"}}


def _execute(plan):
    """Run a validated plan against the SAME audited functions, regardless of who
    produced it (rules or Claude). Guardrail: intent must be whitelisted; only
    declared params survive; a bad call degrades to the no-arg form."""
    intent = plan.get("intent")
    fn = INTENTS.get(intent)
    if fn is None:
        intent, fn = "top_zones", top_zones
    allowed = set(INTENT_SPEC.get(intent, {}))
    params = {k: v for k, v in (plan.get("params") or {}).items()
              if v is not None and k in allowed}
    try:
        txt, tbl = fn(**params)
    except TypeError:
        txt, tbl = fn()
    return txt, tbl, {"intent": intent, "params": params}


def answer(q, use_ai=True, weights=None, elasticity=None):
    """Main entry. An AI layer (Claude → Gemini → rules) maps NL → structured plan;
    the plan is always executed deterministically on real analytics.

    `weights`/`elasticity` let the Copilot page pass the dashboard's active custom
    PCIS policy and deterrence assumption so answers match the rest of the app."""
    parser = "deterministic router"
    if use_ai:
        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                plan = _claude_plan(q)
                parser = f"Claude ({CLAUDE_MODEL})"
            except Exception as e:  # noqa: BLE001
                plan = _rule_route(q)
                parser = f"deterministic router (Claude error: {type(e).__name__})"
        elif os.getenv("GOOGLE_API_KEY"):
            try:
                plan = _gemini_plan(q)
                parser = f"Gemini ({GEMINI_MODEL})"
            except Exception as e:  # noqa: BLE001
                plan = _rule_route(q)
                parser = f"deterministic router (Gemini error: {type(e).__name__})"
        else:
            plan = _rule_route(q)
    else:
        plan = _rule_route(q)
    _CTX["weights"], _CTX["elasticity"] = weights, elasticity
    try:
        txt, tbl, used = _execute(plan)
    finally:
        _CTX["weights"] = _CTX["elasticity"] = None
    return {"text": txt, "table": tbl, "map": None,
            "engine": f"{parser} → grounded analytics", "plan": used, "parser": parser}


# keep old kwarg name working for any callers that pass use_claude=True/False
def _answer_compat(q, use_claude=True):
    return answer(q, use_ai=use_claude)


def _gemini_plan(q):
    """Use Gemini ONLY to map NL → {intent, params}. Same whitelist guardrail as Claude."""
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    model = genai.GenerativeModel(GEMINI_MODEL)
    prompt = (
        "You route a traffic-enforcement analytics question to ONE intent. "
        "Reply ONLY with compact JSON: {\"intent\":..., \"params\":{...}}. "
        f"Valid intents and params: {json.dumps(INTENT_SPEC)}. "
        "If the question asks about ONE specific named junction, station, area or "
        "BTP code (e.g. 'violations in KR Market', 'PCIS of BTP040'), use "
        "lookup_zone with name set to that place. "
        "If it asks for a specific RANK position (e.g. 'the 12th worst area', "
        "'number 3 junction'), use rank_at with position set to that number. "
        "If a deployment question gives a patrol-unit BUDGET (e.g. 'I have 12 "
        "units'), set units to that number on where_to_deploy/blind_spot_deploy. "
        f"Infer sensible params from the question.\n\nQuestion: {q}"
    )
    response = model.generate_content(prompt)
    raw = response.text
    m = re.search(r"\{.*\}", raw, re.S)
    return json.loads(m.group(0))


def _claude_plan(q):
    """Use Claude ONLY to map NL → {intent, params}. It selects from a whitelist;
    it cannot run code or SQL. The plan is executed by _execute()."""
    import anthropic
    client = anthropic.Anthropic()
    sys_prompt = (
        "You route a traffic-enforcement analytics question to ONE intent. "
        "Reply ONLY with compact JSON: {\"intent\":..., \"params\":{...}}. "
        f"Valid intents and params: {json.dumps(INTENT_SPEC)}. "
        "If the question asks about ONE specific named junction, station, area or "
        "BTP code (e.g. 'violations in KR Market', 'PCIS of BTP040'), use "
        "lookup_zone with name set to that place. "
        "If it asks for a specific RANK position (e.g. 'the 12th worst area', "
        "'number 3 junction'), use rank_at with position set to that number. "
        "If a deployment question gives a patrol-unit BUDGET (e.g. 'I have 12 "
        "units'), set units to that number on where_to_deploy/blind_spot_deploy. "
        "Infer sensible params from the question.")
    msg = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=200,
        system=sys_prompt, messages=[{"role": "user", "content": q}])
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", raw, re.S)
    return json.loads(m.group(0))


if __name__ == "__main__":
    for query in SUGGESTIONS:
        r = answer(query, use_claude=False)
        print(f"\nQ: {query}\n   [{r['engine']}] plan={r['plan']}\n   {r['text'][:160]}")
        if r["table"] is not None:
            print("   rows:", len(r["table"]))

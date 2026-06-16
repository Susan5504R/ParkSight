"""
ParkSight AI Copilot — natural-language interface over the precomputed analytics.

Two layers:
  1. Deterministic intent engine (always available, 100% grounded, demo-safe).
  2. Optional Claude layer: when ANTHROPIC_API_KEY is set, Claude parses free-form
     questions into a structured {intent, params} call, which is then executed by
     the SAME deterministic functions — so answers are always backed by real numbers
     (no hallucinated statistics). Falls back to layer 1 on any error.

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

CLAUDE_MODEL = "claude-sonnet-4-6"   # fast + cheap; grounded execution keeps it accurate


@lru_cache(maxsize=None)
def _load(name):
    return pd.read_parquet(C.PROCESSED / name)


@lru_cache(maxsize=1)
def _meta():
    return json.loads((C.PROCESSED / "meta.json").read_text())


# ----------------------------------------------------------------- intents
def top_zones(n=10, grain="junction"):
    f = {"junction": "junction_pcis.parquet", "station": "station_pcis.parquet",
         "zone": "zones.parquet"}.get(grain, "junction_pcis.parquet")
    df = _load(f).copy()
    name_col = ("junction_name" if grain == "junction"
                else "police_station" if grain == "station" else "name")
    cols = [c for c in [name_col, "PCIS", "violations", "tier", "reason"] if c in df.columns]
    out = df.sort_values("PCIS", ascending=False).head(n)[cols]
    return (f"Top {n} parking-congestion {grain}s by PCIS (Parking Congestion Impact "
            f"Score). #1 is **{out.iloc[0][name_col]}** at PCIS {out.iloc[0]['PCIS']}.",
            out.reset_index(drop=True))


def highest_congestion():
    j = _load("junction_pcis.parquet").sort_values("PCIS", ascending=False)
    r = j.iloc[0]
    txt = (f"The single highest-impact parking hotspot is **{r['junction_name']}** "
           f"(PCIS {r['PCIS']}, {int(r['violations']):,} violations). "
           f"Why it ranks #1: {r['reason']}.")
    return txt, j.head(5)[["junction_name", "PCIS", "violations", "tier", "reason"]].reset_index(drop=True)


def where_to_deploy(window="evening", n=8):
    st = _load("station_pcis.parquet").copy()
    # De-biased deployment: rank by the Blind-Spot index when available (corrects the
    # evening enforcement gap), else fall back to raw PCIS. See models/debias.py.
    rank_col = "blindspot_risk" if "blindspot_risk" in st.columns else "PCIS"
    st = st.sort_values(rank_col, ascending=False).head(n)
    win = "17:00–21:00 IST (evening peak)" if window == "evening" else "08:00–11:00 IST (morning peak)"
    st["recommended_window"] = win
    st["units"] = (st["PCIS"] / 100 * 3).round().clip(lower=1).astype(int)
    basis = ("the **de-biased Blind-Spot index** (inverse-propensity-corrected, so the evening "
             "enforcement gap doesn't hide hotspots)" if rank_col == "blindspot_risk"
             else "predicted congestion impact (PCIS)")
    txt = (f"Recommended deployment for the **{win}** window — these {n} stations rank highest by "
           f"{basis}. Suggested patrol units scale with PCIS.")
    cols = [c for c in ["police_station", "blindspot_risk", "PCIS", "tier",
                        "recommended_window", "units", "reason"] if c in st.columns]
    return txt, st[cols].reset_index(drop=True)


def blind_spot_deploy(n=8):
    """Explicitly de-biased deploy-here ranking (Blind-Spot index)."""
    st = _load("station_pcis.parquet").copy()
    if "blindspot_risk" not in st.columns:
        return where_to_deploy("evening", n)
    st = st.sort_values("blindspot_risk", ascending=False).head(n)
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
    if area:
        m = (off["top_station"].str.contains(area, case=False, na=False) |
             off["top_junction"].str.contains(area, case=False, na=False))
        if m.any():
            off = off[m]
    out = off.sort_values("violations", ascending=False).head(n)
    where = f" near **{area}**" if area else ""
    txt = (f"Top {len(out)} chronic parking offenders{where}. The worst vehicle has "
           f"{int(out.iloc[0]['violations'])} violations. Repeat offenders cause "
           f"{_meta()['repeat_share']}% of all violations citywide.")
    return txt, out[["vehicle_number", "vehicle_type", "violations", "severe_n",
                     "top_station", "last_seen"]].reset_index(drop=True)


def impact_if(delta_pct=20):
    """Scenario: extra enforcement in top zones → estimated violation reduction."""
    st = _load("station_pcis.parquet").sort_values("PCIS", ascending=False).head(10)
    # transparent elasticity assumption (documented): +1% enforcement → 0.4% fewer violations
    elasticity = 0.4
    reduced = st["violations"].sum() * (delta_pct / 100) * elasticity
    txt = (f"**What-if:** increasing enforcement by **{delta_pct}%** in the top-10 PCIS "
           f"stations could prevent roughly **{int(reduced):,} violations** over a comparable "
           f"period (assuming a 0.4 deterrence elasticity — a documented, tunable assumption). "
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
    "blind_spot": blind_spot, "overview": overview,
}

# Allowed params per intent — anything else from the LLM is dropped (hard guardrail).
INTENT_SPEC = {
    "top_zones": {"n": "int", "grain": "junction|station|zone"},
    "highest_congestion": {},
    "where_to_deploy": {"window": "morning|evening", "n": "int"},
    "blind_spot_deploy": {"n": "int"},
    "offenders_near": {"area": "str|null", "n": "int"},
    "impact_if": {"delta_pct": "int"},
    "blind_spot": {}, "overview": {},
}

SUGGESTIONS = [
    "Show the top 10 illegal parking zones",
    "Which hotspot causes the highest congestion?",
    "Where should we deploy in the evening (de-biased)?",
    "Show chronic offenders near Shivajinagar",
    "What happens if we increase enforcement by 20%?",
    "Explain the enforcement blind spot",
]


def _rule_route(q):
    """Deterministic NL → structured plan {intent, params}. No execution here."""
    ql = q.lower()
    num = re.search(r"\b(\d{1,3})\b", ql)
    n = int(num.group(1)) if num else 10
    if any(k in ql for k in ["blind", "trough", "evening gap", "5 pm", "5pm"]):
        if "deploy" in ql or "where" in ql or "patrol" in ql:
            return {"intent": "blind_spot_deploy", "params": {"n": n}}
        return {"intent": "blind_spot", "params": {}}
    if "%" in ql or "increase" in ql or "what if" in ql or "what happens" in ql:
        return {"intent": "impact_if", "params": {"delta_pct": int(num.group(1)) if num else 20}}
    if "deploy" in ql or "where should" in ql or "send teams" in ql or "patrol" in ql:
        if any(k in ql for k in ["de-bias", "debias", "blind", "unbiased", "corrected"]):
            return {"intent": "blind_spot_deploy", "params": {"n": n}}
        return {"intent": "where_to_deploy", "params": {"window": "morning" if "morning" in ql else "evening"}}
    if "offender" in ql or "repeat" in ql or "chronic" in ql or "vehicle" in ql:
        m = re.search(r"near ([a-zA-Z .]+)", ql)
        return {"intent": "offenders_near",
                "params": {"area": m.group(1).strip().title() if m else None, "n": n}}
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


def answer(q, use_claude=True):
    """Main entry. Claude (or rules) parses NL → structured plan; the plan is then
    executed deterministically on real analytics — so every number is grounded."""
    parser = "deterministic router"
    if use_claude and os.getenv("ANTHROPIC_API_KEY"):
        try:
            plan = _claude_plan(q)
            parser = f"Claude ({CLAUDE_MODEL})"
        except Exception as e:  # noqa: BLE001
            plan = _rule_route(q)
            parser = f"deterministic router (Claude error: {type(e).__name__})"
    else:
        plan = _rule_route(q)
    txt, tbl, used = _execute(plan)
    return {"text": txt, "table": tbl, "map": None,
            "engine": f"{parser} → grounded analytics", "plan": used, "parser": parser}


def _claude_plan(q):
    """Use Claude ONLY to map NL → {intent, params}. It selects from a whitelist;
    it cannot run code or SQL. The plan is executed by _execute()."""
    import anthropic
    client = anthropic.Anthropic()
    sys_prompt = (
        "You route a traffic-enforcement analytics question to ONE intent. "
        "Reply ONLY with compact JSON: {\"intent\":..., \"params\":{...}}. "
        f"Valid intents and params: {json.dumps(INTENT_SPEC)}. "
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

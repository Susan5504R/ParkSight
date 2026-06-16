"""
ParkSight de-biasing engine — breaks the enforcement feedback loop.

THE PROBLEM (selection bias / endogeneity):
  A ticket only exists where an enforcement device was present. Enforcement
  collapses in the evening (citywide evening share ≈ 0.02–0.5%), so raw ticket
  counts UNDER-report exactly when parking-induced congestion peaks. Any model
  trained naively on tickets learns *enforcement behaviour*, not violation
  density — and would declare commercial corridors "safe" at 19:00 because no
  tickets were filed, reinforcing the blind spot instead of fixing it.

THE FIX (two independent corrections, neither learnable-away):
  1. Inverse-Propensity Weighting (Horvitz–Thompson). Estimate the hourly
     enforcement *exposure* e(h) from device activity (a violation's chance of
     being observed). Re-inflate observed counts by 1/e(h) to recover a latent-
     demand estimate. Evening hours get the largest correction.
  2. External congestion prior C(cell,h) = road_hierarchy(cell) · synthetic(h),
     built from the road network class of the PLACE and a canonical rush-hour
     curve — both decoupled from ticket timing, so the missing-label loop cannot
     train them down to zero.

THE OUTPUT the judges asked for:
  A **Blind-Spot Divergence** score = (predicted evening congestion prior) −
  (observed evening enforcement signal). High divergence = high probability,
  no data → deploy here. This mathematically forces recommendations into cells
  where data is missing but congestion is maxed out.

Artifacts: data/processed/enforcement_exposure.parquet, blindspot_cells.parquet
and blindspot columns merged onto the station / junction / cell PCIS frames.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from parksight import config as C  # noqa: E402

EVENING = (17, 21)   # IST evening congestion window (inclusive start, exclusive end)


def minmax(s):
    s = pd.Series(s).astype(float)
    lo, hi = s.min(), s.max()
    if hi - lo < 1e-12:
        return pd.Series(np.zeros(len(s)), index=s.index)
    return (s - lo) / (hi - lo)


# --------------------------------------------------------------------- priors
def road_hierarchy_weight(addr, at_junction=False):
    """OSM-style functional road class from the location text — a static spatial
    property, NOT a function of when tickets were written (so it is unbiased by
    the evening enforcement gap)."""
    base = C.ROAD_HIERARCHY_DEFAULT
    if isinstance(addr, str) and addr:
        a = addr.lower()
        hits = [w for k, w in C.ROAD_HIERARCHY.items() if k in a]
        if hits:
            base = max(hits)
    if at_junction:
        base = max(base, C.ROAD_HIERARCHY["junction"])
    return float(base)


def synthetic_congestion(hour):
    """Canonical bimodal rush-hour congestion weight for an IST hour."""
    return float(C.SYNTHETIC_CONGESTION.get(int(hour), 0.3))


# ----------------------------------------------------------------- exposure
def estimate_exposure(df):
    """Hourly enforcement EXPOSURE (propensity that a violation gets observed).

    Proxy = distinct active enforcement devices per hour, scaled to its own max.
    Falls back to ticket-activity share if no device_id column is present.
    Returns a 24-row frame: hour, devices, exposure, ipw (capped 1/exposure),
    synthetic_congestion. The gap between `exposure` and `synthetic_congestion`
    IS the time-of-day blind spot."""
    by_hour = df.groupby("hour")
    if "device_id" in df.columns and df["device_id"].notna().any():
        active = by_hour["device_id"].nunique()
        basis = "distinct active devices"
    else:
        active = by_hour.size()
        basis = "ticket activity (device_id unavailable)"
    active = active.reindex(range(24), fill_value=0).astype(float)
    exposure = (active / active.max()) if active.max() > 0 else active
    exposure = exposure.clip(lower=0.0)
    eff = exposure.clip(lower=C.EXPOSURE_FLOOR)
    ipw = (1.0 / eff).clip(upper=C.IPW_WEIGHT_CAP)
    out = pd.DataFrame({
        "hour": range(24),
        "devices": active.values,
        "exposure": exposure.values.round(4),
        "ipw": ipw.values.round(3),
        "synthetic_congestion": [synthetic_congestion(h) for h in range(24)],
    })
    out.attrs["basis"] = basis
    return out


# --------------------------------------------------------------- blind spot
def compute_blindspot(df, exposure, group_col):
    """Per-group de-biased latent demand + blind-spot divergence.

    latent_demand : Σ ticket·ipw(hour)  — Horvitz–Thompson inverse-propensity
                    estimate of true violation intensity (evening counts re-inflated).
    congestion_prior : mean road-hierarchy(place) · synthetic(hour) over the
                    EVENING window — external, ticket-independent estimate of
                    congestion stake.
    obs_evening : observed share of this group's tickets in the evening window
                    (the biased signal a naive model would trust).
    divergence  : norm(congestion_prior) − norm(obs_evening_signal).  > 0 means
                    "high predicted congestion, little/no evening data" = blind spot.
    blindspot_risk : 0–100 index = latent_demand × divergence, the deploy-here score."""
    ipw_by_hour = exposure.set_index("hour")["ipw"].to_dict()
    d = df.copy()
    d["ipw"] = d["hour"].map(ipw_by_hour).fillna(1.0)
    d["road_w"] = [road_hierarchy_weight(a, j)
                   for a, j in zip(d.get("location", pd.Series(index=d.index)), d["at_junction"])]
    d["cong"] = d["road_w"] * d["hour"].map(synthetic_congestion)
    d["is_evening"] = (d["hour"] >= EVENING[0]) & (d["hour"] < EVENING[1])

    g = d.groupby(group_col)
    out = pd.DataFrame({
        "observed": g.size(),
        "latent_demand": g["ipw"].sum(),                 # Σ inverse-propensity weight
        "road_class": g["road_w"].max(),                 # functional class of the place
        "congestion_prior": g.apply(                     # evening congestion stake
            lambda s: float((s["road_w"] * s["hour"].map(synthetic_congestion))
                            [s["is_evening"]].mean()) if s["is_evening"].any()
            else float(s["road_w"].mean() * synthetic_congestion(18))),
        "obs_evening_share": g["is_evening"].mean(),
    })
    # uplift the inverse-propensity correction adds over raw counts (×)
    out["ipw_uplift"] = (out["latent_demand"] / out["observed"].clip(lower=1)).round(2)

    # divergence: predicted congestion vs the (biased) observed evening signal
    out["divergence"] = (minmax(out["congestion_prior"])
                         - minmax(out["obs_evening_share"])).round(3)
    # deploy-here index: large latent demand AND a positive prior-vs-data gap
    risk_raw = minmax(out["latent_demand"]) * (0.5 + 0.5 * minmax(out["divergence"]))
    out["blindspot_risk"] = (100 * minmax(risk_raw)).round(1)
    return out.reset_index()


def attach(agg, blind, group_col):
    """Merge blind-spot columns onto a PCIS frame (idempotent)."""
    cols = ["latent_demand", "road_class", "congestion_prior", "obs_evening_share",
            "ipw_uplift", "divergence", "blindspot_risk"]
    drop = [c for c in cols if c in agg.columns]
    return agg.drop(columns=drop, errors="ignore").merge(
        blind[[group_col] + cols], on=group_col, how="left")


def summary(exposure, station_blind):
    """Headline numbers for meta.json / the narrative."""
    ev = exposure[(exposure["hour"] >= EVENING[0]) & (exposure["hour"] < EVENING[1])]
    pk = exposure.loc[exposure["exposure"].idxmax()]
    worst = station_blind.sort_values("blindspot_risk", ascending=False).iloc[0]
    return {
        "evening_exposure_pct": round(100 * float(ev["exposure"].mean()), 2),
        "peak_exposure_hour": int(pk["hour"]),
        "max_ipw_uplift": round(float(station_blind["ipw_uplift"].max()), 1),
        "top_blindspot_station": str(worst.get("police_station", worst.iloc[0])),
        "top_blindspot_risk": float(worst["blindspot_risk"]),
        "exposure_basis": exposure.attrs.get("basis", "device activity"),
    }

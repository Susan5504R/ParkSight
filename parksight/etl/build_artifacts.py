"""
ParkSight ETL — turns the raw 298k-row violation CSV into compact analytics
artifacts the Streamlit app loads (all <50 MB, deploy-friendly).

Outputs (parquet) in parksight/data/processed/:
  violations_clean.parquet   row-level, IST datetimes, parsed tags, h3, severity
  cell_pcis.parquet          h3 res-9 cells with V/S/L/P/T + PCIS
  city_cells.parquet         h3 res-8 aggregate (city heat layer)
  station_pcis.parquet       rolled up to police_station + rank/tier/reason
  junction_pcis.parquet      rolled up to junction + rank/tier/reason
  zones.parquet              DBSCAN named hotspot zones
  offenders.parquet          repeat / chronic offenders
  hourly_profile.parquet     IST hour x weekday counts (blind-spot chart)
  daily_station.parquet      station x date counts (forecasting input)
  meta.json                  headline numbers for the dashboard

Run:  python parksight/etl/build_artifacts.py
"""
import json
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from parksight import config as C  # noqa: E402
from parksight import scoring  # noqa: E402

warnings.filterwarnings("ignore")

# ---- h3 v3/v4 compatibility -------------------------------------------------
import h3  # noqa: E402

def latlng_to_cell(lat, lng, res):
    if hasattr(h3, "latlng_to_cell"):          # v4
        return h3.latlng_to_cell(lat, lng, res)
    return h3.geo_to_h3(lat, lng, res)          # v3

def cell_to_latlng(cell):
    if hasattr(h3, "cell_to_latlng"):           # v4
        return h3.cell_to_latlng(cell)
    return h3.h3_to_geo(cell)                    # v3


# ---- helpers ----------------------------------------------------------------
def parse_tags(raw):
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return []
    s = str(raw).strip()
    if s in ("", "NULL", "null", "[]"):
        return []
    try:
        v = json.loads(s)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
    except Exception:
        pass
    return [t.strip().strip('"') for t in s.strip("[]").split(",") if t.strip()]


def ticket_severity(tags):
    if not tags:
        return C.SEVERITY_DEFAULT
    return max(C.SEVERITY_WEIGHTS.get(t, C.SEVERITY_DEFAULT) for t in tags)


_kw = [k.lower() for k in C.LOCATION_KEYWORDS]
def location_score(addr):
    if not isinstance(addr, str) or not addr:
        return 0.0
    a = addr.lower()
    hits = sum(1 for k in _kw if k in a)
    return min(hits / 4.0, 1.0)   # saturate at 4 keyword hits


def peak_weight(hour):
    for _, (lo, hi, w) in C.PEAK_WINDOWS.items():
        if lo <= hour < hi:
            return w
    return C.OFFPEAK_WEIGHT


def minmax(s):
    s = s.astype(float)
    lo, hi = s.min(), s.max()
    if hi - lo < 1e-12:
        return pd.Series(np.zeros(len(s)), index=s.index)
    return (s - lo) / (hi - lo)


# ---- 1. load + clean --------------------------------------------------------
def load_clean(source=None):
    src = source if source is not None else C.RAW_CSV
    if isinstance(src, pd.DataFrame):
        df = src.copy()
        print(f"[etl] using in-memory dataframe ({len(df):,} rows)")
    else:
        print(f"[etl] reading {getattr(src, 'name', src)} ...")
        df = pd.read_csv(src, low_memory=False)
    print(f"[etl] raw rows: {len(df):,}")

    # drop 100%-null / unused columns
    df = df.drop(columns=[c for c in
                          ["description", "closed_datetime", "action_taken_timestamp",
                           "data_sent_to_scita_timestamp"] if c in df.columns],
                 errors="ignore")

    # timezone: stored UTC (+00) -> IST
    dt = pd.to_datetime(df["created_datetime"], utc=True, errors="coerce")
    df["created_ist"] = dt.dt.tz_convert(C.TZ_IST)
    df = df[df["created_ist"].notna()].copy()
    df["hour"] = df["created_ist"].dt.hour
    df["weekday"] = df["created_ist"].dt.weekday          # 0=Mon
    df["weekday_name"] = df["created_ist"].dt.day_name()
    df["is_weekend"] = df["weekday"] >= 5
    df["date"] = df["created_ist"].dt.date
    df["month"] = df["created_ist"].dt.to_period("M").astype(str)

    # violations
    df["tags"] = df["violation_type"].apply(parse_tags)
    df["severity"] = df["tags"].apply(ticket_severity)
    df["is_severe"] = df["severity"] >= 0.80
    df["primary_tag"] = df["tags"].apply(lambda t: t[0] if t else "UNKNOWN")
    df["n_tags"] = df["tags"].apply(len)

    # geo
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df[(df["latitude"].between(12.5, 13.5)) &
            (df["longitude"].between(77.2, 78.0))].copy()
    df["h3_r9"] = [latlng_to_cell(la, lo, C.H3_HOT)
                   for la, lo in zip(df["latitude"], df["longitude"])]
    df["h3_r8"] = [latlng_to_cell(la, lo, C.H3_CITY)
                   for la, lo in zip(df["latitude"], df["longitude"])]

    # location criticality + junction flag
    df["loc_score"] = df["location"].apply(location_score)
    df["at_junction"] = (df["junction_name"].notna() &
                         (df["junction_name"] != "No Junction"))
    df["peak_w"] = df["hour"].apply(peak_weight)
    df["is_evening"] = (df["hour"] >= 17) & (df["hour"] < 21)   # IST evening peak

    # repeat offender flag
    vc = df["vehicle_number"].value_counts()
    repeat_vehicles = set(vc[vc > 1].index)
    df["is_repeat"] = df["vehicle_number"].isin(repeat_vehicles)

    df["police_station"] = df["police_station"].fillna("Unknown")
    df["junction_name"] = df["junction_name"].fillna("No Junction")

    print(f"[etl] clean rows: {len(df):,} | "
          f"{df['created_ist'].min()} -> {df['created_ist'].max()}")
    return df


# ---- 2. PCIS (generic, by any grouping column) ------------------------------
def trend_slopes(df, group_col):
    """month-over-month slope of violation counts per group (normalised later)."""
    months = sorted(df["month"].unique())
    midx = {m: i for i, m in enumerate(months)}
    piv = (df.groupby([group_col, "month"]).size()
             .reset_index(name="n"))
    piv["mi"] = piv["month"].map(midx)
    slopes = {}
    for g, sub in piv.groupby(group_col):
        if len(sub) >= 2:
            slopes[g] = np.polyfit(sub["mi"], sub["n"], 1)[0]
        else:
            slopes[g] = 0.0
    return pd.Series(slopes)


def compute_pcis(df, group_col):
    g = df.groupby(group_col)
    agg = pd.DataFrame({
        "violations": g.size(),
        "severity_mean": g["severity"].mean(),
        "loc_mean": g["loc_score"].mean(),
        "junction_share": g["at_junction"].mean(),
        "peak_mean": g["peak_w"].mean(),
        "severe_n": g["is_severe"].sum(),
        "repeat_n": g["is_repeat"].sum(),
        "lat": g["latitude"].mean(),
        "lon": g["longitude"].mean(),
        "peak_hour": g["hour"].agg(lambda s: int(s.mode().iloc[0]) if len(s) else 0),
        "evening_share": g["is_evening"].mean(),
    })
    # top violation type per group
    top_tag = (df.explode("tags").groupby(group_col)["tags"]
                 .agg(lambda s: s.value_counts().index[0] if len(s.dropna()) else "—"))
    agg["top_type"] = top_tag
    # dominant station/junction labels for context
    if group_col != "police_station":
        agg["police_station"] = g["police_station"].agg(
            lambda s: s.value_counts().index[0] if len(s) else "Unknown")
    if group_col != "junction_name":
        agg["junction_name"] = g["junction_name"].agg(
            lambda s: s.value_counts().index[0] if len(s) else "No Junction")

    slopes = trend_slopes(df, group_col)
    agg["trend_slope"] = slopes.reindex(agg.index).fillna(0.0)

    # ---- components (normalised 0-1) ----
    agg["V"] = minmax(np.log1p(agg["violations"]))
    agg["S"] = minmax(agg["severity_mean"])
    agg["L"] = minmax(0.5 * agg["junction_share"] + 0.5 * agg["loc_mean"])
    agg["P"] = minmax(agg["peak_mean"])
    agg["T"] = minmax(agg["trend_slope"].clip(lower=0))   # only worsening counts

    w = C.PCIS_WEIGHTS
    raw = (w["V"] * agg["V"] + w["S"] * agg["S"] + w["L"] * agg["L"] +
           w["P"] * agg["P"] + w["T"] * agg["T"])
    # absolute composite (0-100) kept for reference; displayed PCIS is min-max
    # rescaled to use the full 0-100 range within this grain (relative impact index)
    agg["PCIS_abs"] = (100 * raw).round(1)
    agg["PCIS"] = (100 * minmax(raw)).round(1)
    agg = agg.reset_index().sort_values("PCIS", ascending=False)
    agg["rank"] = range(1, len(agg) + 1)
    return agg


def add_priority(agg):
    """tier + enforcement-gap + human-readable reason."""
    # enforcement presence proxy: distinct devices active during peak window
    agg = agg.copy()
    agg["tier"] = scoring.assign_tier(agg["PCIS"]).to_numpy()
    # Enforcement-Gap: high predicted impact but low evening-peak enforcement presence.
    agg["gap_score"] = scoring.gap_score(
        agg["PCIS"], agg.get("evening_share", pd.Series(0, index=agg.index))).to_numpy()
    med_v = agg["violations"].median()
    gap_hi = agg["gap_score"].quantile(0.75)

    def reason(r):
        bits = []
        if r["S"] > 0.6:
            bits.append("carriageway-blocking violations")
        if r["P"] > 0.6:
            bits.append("concentrated in peak-congestion hours")
        if r["gap_score"] >= gap_hi:
            bits.append("under-enforced during the evening peak")
        if r["T"] > 0.4:
            bits.append("worsening month-on-month")
        if r["violations"] > med_v:
            bits.append("high violation volume")
        if r.get("repeat_n", 0) > 0 and r["violations"] > 0 and \
                r["repeat_n"] / r["violations"] > 0.35:
            bits.append("driven by repeat offenders")
        return "; ".join(bits) or "moderate, steady activity"
    agg["reason"] = agg.apply(reason, axis=1)
    return agg


# ---- 3. DBSCAN named zones --------------------------------------------------
def build_zones(cell_pcis, df):
    from sklearn.cluster import DBSCAN
    hot = cell_pcis[cell_pcis["violations"] >= C.MIN_CELL_VIOLATIONS].copy()
    if len(hot) < 5:
        return pd.DataFrame()
    X = np.radians(hot[["lat", "lon"]].values)
    # eps ~ 400m in radians (earth radius 6371 km)
    db = DBSCAN(eps=400 / 6_371_000, min_samples=3, metric="haversine").fit(X)
    hot["zone"] = db.labels_
    hot = hot[hot["zone"] >= 0]
    if hot.empty:
        return pd.DataFrame()
    rows = []
    for z, sub in hot.groupby("zone"):
        name = sub.sort_values("violations", ascending=False)["junction_name"].iloc[0]
        if name in ("No Junction", "—", None):
            name = sub.sort_values("violations", ascending=False)["police_station"].iloc[0]
        rows.append({
            "zone": int(z),
            "name": name,
            "lat": sub["lat"].mean(),
            "lon": sub["lon"].mean(),
            "cells": len(sub),
            "violations": int(sub["violations"].sum()),
            "PCIS": round(sub["PCIS"].mean(), 1),
            "police_station": sub["police_station"].mode().iloc[0],
        })
    zones = pd.DataFrame(rows).sort_values("PCIS", ascending=False)
    zones["rank"] = range(1, len(zones) + 1)
    return zones


# ---- 4. offenders -----------------------------------------------------------
def build_offenders(df):
    g = df.groupby("vehicle_number")
    off = pd.DataFrame({
        "violations": g.size(),
        "vehicle_type": g["vehicle_type"].agg(lambda s: s.mode().iloc[0]),
        "last_seen": g["created_ist"].max().dt.tz_localize(None),
        "top_station": g["police_station"].agg(lambda s: s.mode().iloc[0]),
        "top_junction": g["junction_name"].agg(lambda s: s.mode().iloc[0]),
        "severe_n": g["is_severe"].sum(),
        "lat": g["latitude"].mean(),
        "lon": g["longitude"].mean(),
    }).reset_index()
    off = off[off["violations"] > 1].sort_values("violations", ascending=False)
    off["rank"] = range(1, len(off) + 1)
    return off


# ---- main -------------------------------------------------------------------
def main(source=None):
    df = load_clean(source)

    # row-level clean (compact columns only)
    keep = ["id", "latitude", "longitude", "location", "vehicle_number",
            "vehicle_type", "police_station", "junction_name", "primary_tag",
            "severity", "is_severe", "is_repeat", "at_junction", "loc_score",
            "peak_w", "hour", "weekday", "weekday_name", "is_weekend", "month",
            "h3_r9", "h3_r8", "created_ist"]
    clean = df[keep].copy()
    clean["created_ist"] = clean["created_ist"].dt.tz_localize(None)
    clean.to_parquet(C.PROCESSED / "violations_clean.parquet", index=False)
    print(f"[etl] saved violations_clean.parquet ({len(clean):,} rows)")

    # ---- De-biasing engine: break the enforcement feedback loop --------------
    # Estimate hourly enforcement EXPOSURE, then inverse-propensity-weight the
    # observed tickets and compare against an external (ticket-independent)
    # congestion prior. See parksight/models/debias.py.
    from parksight.models import debias as DB
    exposure = DB.estimate_exposure(df)
    exposure.to_parquet(C.PROCESSED / "enforcement_exposure.parquet", index=False)
    print(f"[etl] enforcement_exposure: basis={exposure.attrs.get('basis')}, "
          f"evening exposure ~ {100 * exposure.loc[17:20, 'exposure'].mean():.1f}% of peak")

    # PCIS at three grains, each augmented with de-biased blind-spot columns
    cell = add_priority(compute_pcis(df, "h3_r9"))
    cell = DB.attach(cell, DB.compute_blindspot(df, exposure, "h3_r9"), "h3_r9")
    cell.to_parquet(C.PROCESSED / "cell_pcis.parquet", index=False)
    print(f"[etl] cell_pcis: {len(cell):,} hexes")

    city = compute_pcis(df, "h3_r8")
    city.to_parquet(C.PROCESSED / "city_cells.parquet", index=False)

    station_blind = DB.compute_blindspot(df, exposure, "police_station")
    station = add_priority(compute_pcis(df, "police_station"))
    station = DB.attach(station, station_blind, "police_station")
    station.to_parquet(C.PROCESSED / "station_pcis.parquet", index=False)
    print(f"[etl] station_pcis: {len(station):,} stations")

    junction = compute_pcis(df, "junction_name")
    junction = junction[junction["junction_name"] != "No Junction"]
    junction = add_priority(junction)
    junction = DB.attach(junction, DB.compute_blindspot(
        df[df["junction_name"] != "No Junction"], exposure, "junction_name"), "junction_name")
    junction.to_parquet(C.PROCESSED / "junction_pcis.parquet", index=False)
    print(f"[etl] junction_pcis: {len(junction):,} junctions")

    # blind-spot cell artifact (deploy-here ranking, de-biased)
    bs_cell = cell[["h3_r9", "lat", "lon", "PCIS", "violations", "latent_demand",
                    "road_class", "congestion_prior", "obs_evening_share",
                    "ipw_uplift", "divergence", "blindspot_risk"]].copy()
    bs_cell.sort_values("blindspot_risk", ascending=False).to_parquet(
        C.PROCESSED / "blindspot_cells.parquet", index=False)
    db_summary = DB.summary(exposure, station)

    zones = build_zones(cell, df)
    if not zones.empty:
        zones.to_parquet(C.PROCESSED / "zones.parquet", index=False)
        print(f"[etl] zones: {len(zones):,} DBSCAN clusters")

    offenders = build_offenders(df)
    offenders.to_parquet(C.PROCESSED / "offenders.parquet", index=False)
    print(f"[etl] offenders: {len(offenders):,} repeat vehicles")

    # hourly x weekday profile (blind-spot chart) + data-driven evening trough
    hp = (df.groupby(["hour", "weekday_name"]).size().reset_index(name="n"))
    hp.to_parquet(C.PROCESSED / "hourly_profile.parquet", index=False)
    _bh = df.groupby("hour").size().reindex(range(24), fill_value=0)
    _low = [h for h in range(12, 24) if _bh[h] < 0.15 * _bh.max()]
    trough = (f"{min(_low):02d}:00-{min(max(_low) + 1, 24):02d}:00 IST"
              if _low else "15:00-24:00 IST")

    # station x date (forecast input)
    ds = (df.groupby(["police_station", "date"]).size().reset_index(name="n"))
    ds["date"] = pd.to_datetime(ds["date"])
    ds.to_parquet(C.PROCESSED / "daily_station.parquet", index=False)

    # chart-ready aggregates (keep app lightweight)
    (df.groupby("month").size().reset_index(name="n")
       .to_parquet(C.PROCESSED / "monthly_trend.parquet", index=False))
    (df.groupby("weekday_name").size().reset_index(name="n")
       .to_parquet(C.PROCESSED / "weekday_counts.parquet", index=False))
    vmix = (df.explode("tags").groupby("tags").size()
              .reset_index(name="n").sort_values("n", ascending=False))
    vmix.to_parquet(C.PROCESSED / "violation_mix.parquet", index=False)
    (df.groupby("vehicle_type").size().reset_index(name="n")
       .sort_values("n", ascending=False)
       .to_parquet(C.PROCESSED / "vehicle_mix.parquet", index=False))
    # daily totals for trend sparkline
    (df.groupby("date").size().reset_index(name="n")
       .assign(date=lambda d: pd.to_datetime(d["date"]))
       .to_parquet(C.PROCESSED / "daily_total.parquet", index=False))

    # headline meta
    total = len(df)
    repeat_tickets = int(df["is_repeat"].sum())
    meta = {
        "total_violations": int(total),
        "date_min": str(df["created_ist"].min().date()),
        "date_max": str(df["created_ist"].max().date()),
        "n_stations": int(df["police_station"].nunique()),
        "n_junctions": int((df["junction_name"] != "No Junction").sum() and
                           df.loc[df["junction_name"] != "No Junction",
                                  "junction_name"].nunique()),
        "n_cells": int(cell.shape[0]),
        "n_hotspots": int((cell["tier"] == "High").sum()),
        "repeat_share": round(100 * repeat_tickets / total, 1),
        "severe_share": round(100 * int(df["is_severe"].sum()) / total, 1),
        "n_devices": int(df["device_id"].nunique()) if "device_id" in df else 0,
        "top_station": station.iloc[0]["police_station"],
        "top_zone": zones.iloc[0]["name"] if not zones.empty else station.iloc[0]["police_station"],
        "evening_trough_hours": trough,
        **{f"debias_{k}": v for k, v in db_summary.items()},
    }
    (C.PROCESSED / "meta.json").write_text(json.dumps(meta, indent=2))
    print("[etl] meta:", json.dumps(meta, indent=2))
    print("[etl] DONE.")


if __name__ == "__main__":
    main()

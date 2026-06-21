"""
ParkSight forecasting — next-7-day parking-violation volume per police station.

Pipeline (evidence-driven; see scripts/model_experiments.py):
  T1  COUNT-AWARE objective (Poisson/Tweedie/log1p) chosen by ROLLING-ORIGIN CV
      (risk-adjusted mean+0.25·std); leak-free refit; CONFORMAL (CQR) p10–p90.
  T2  CV-GATED feature selection (add a feature only if it improves CV) ·
      OPTUNA hyper-tuning gated by CV · AutoETS classical benchmark ·
      weekly (lower-noise) forecast view.
  Decision metrics: MASE, WAPE, precision@10.

Outputs: data/processed/forecast.parquet, forecast_weekly.parquet ; models/metrics.json
Run:  python parksight/models/train_forecast.py
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from parksight import config as C  # noqa: E402

warnings.filterwarnings("ignore")

HORIZON, ALPHA, CAL_DAYS, CV_FOLDS, CV_WINDOW = 7, 0.20, 21, 4, 7
BASE_PARAMS = dict(n_estimators=600, learning_rate=0.04, num_leaves=24,
                   subsample=0.85, colsample_bytree=0.85, min_child_samples=30,
                   reg_lambda=1.0, reg_alpha=0.2, random_state=42, verbose=-1)
FEATS_BASE = ["lag1", "lag7", "lag14", "roll3", "roll7", "roll14", "roll28",
              "dow", "is_weekend", "month", "doy", "is_holiday", "station_code"]
EXTRA_CANDS = ["samedow_mean", "ewma7", "days_to_holiday"]


# --------------------------------------------------------------------------- features
def indian_holidays(years):
    try:
        import holidays
        return set(holidays.country_holidays("IN", years=years).keys())
    except Exception:
        return set()


def make_features(df, holiday_set):
    # reset_index so every derived column aligns by POSITION, not by stale label:
    # the recursive forecast appends future rows at the end, so after sorting the
    # index is non-monotonic and label-based assignment would scramble the rolling
    # features. A clean RangeIndex + grouped transforms keep windows within a
    # station and correctly aligned.
    df = df.sort_values(["police_station", "date"]).reset_index(drop=True).copy()
    g = df.groupby("police_station")["n"]
    df["lag1"] = g.shift(1); df["lag7"] = g.shift(7); df["lag14"] = g.shift(14)
    for w in (3, 7, 14, 28):
        df[f"roll{w}"] = g.transform(lambda s, w=w: s.shift(1).rolling(w).mean())
    df["ewma7"] = g.transform(lambda s: s.shift(1).ewm(span=7).mean())
    df["dow"] = df["date"].dt.weekday
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df["month"] = df["date"].dt.month
    df["doy"] = df["date"].dt.dayofyear
    df["is_holiday"] = df["date"].dt.date.isin(holiday_set).astype(int)
    df["station_code"] = df["police_station"].astype("category").cat.codes
    # leak-safe same-(station,weekday) expanding mean
    df["samedow_mean"] = (df.groupby(["police_station", "dow"])["n"]
                          .transform(lambda s: s.shift(1).expanding().mean()))
    # calendar distance to nearest holiday (capped)
    hd = sorted(holiday_set)
    if hd:
        hda = np.array([pd.Timestamp(h).toordinal() for h in hd])
        ordv = df["date"].map(lambda d: d.toordinal()).to_numpy()
        df["days_to_holiday"] = [int(min(abs(o - hda).min(), 30)) for o in ordv]
    else:
        df["days_to_holiday"] = 30
    return df


def build_grid(daily):
    daily["date"] = pd.to_datetime(daily["date"])
    full = pd.date_range(daily["date"].min(), daily["date"].max(), freq="D")
    idx = pd.MultiIndex.from_product([daily["police_station"].unique(), full],
                                     names=["police_station", "date"])
    return daily.set_index(["police_station", "date"]).reindex(idx, fill_value=0).reset_index()


def mae(a, b):
    return float(np.mean(np.abs(np.asarray(a, float) - np.asarray(b, float))))


# --------------------------------------------------------------------------- gbm
def _gbm(Xtr, ytr, params, objective=None, log=False, n_estimators=None):
    import lightgbm as lgb
    p = dict(params)
    if objective:
        p["objective"] = objective
    if n_estimators:
        p["n_estimators"] = int(n_estimators)
    return lgb.LGBMRegressor(**p).fit(Xtr, np.log1p(ytr) if log else ytr), log


def _pred(model_log, X):
    model, log = model_log
    p = model.predict(X)
    return np.clip(np.expm1(p) if log else p, 0, None)


CANDIDATES = {
    "LGBM Poisson":      dict(obj="poisson", log=False, blend=False),
    "LGBM Tweedie":      dict(obj="tweedie", log=False, blend=False),
    "LGBM log1p":        dict(obj=None, log=True, blend=False),
    "LGBM L2":           dict(obj=None, log=False, blend=False),
    "Blend Poisson+MA7": dict(obj="poisson", log=False, blend=True),
    "Blend log1p+MA7":   dict(obj=None, log=True, blend=True),
    "MA-7":              dict(obj=None, log=False, blend=False, pure="ma7"),
    "Climatology":       dict(obj=None, log=False, blend=False, pure="clim"),
}


def _cand_pred(spec, tr, te, gm, feats, params):
    ma = np.where(np.isnan(te["roll7"].values), gm, te["roll7"].values)
    if spec.get("pure") == "ma7":
        return ma
    if spec.get("pure") == "clim":
        clim = tr.groupby(["police_station", "dow"])["n"].mean()
        v = te.set_index(["police_station", "dow"]).index.map(clim).astype(float).values
        return np.where(np.isnan(v), gm, v)
    m = _gbm(tr[feats], tr["n"], params, spec["obj"], spec["log"])
    p = _pred(m, te[feats])
    return 0.5 * p + 0.5 * ma if spec["blend"] else p


def _folds(feat):
    dmax = feat["date"].max()
    for k in range(CV_FOLDS, 0, -1):
        cut = dmax - pd.Timedelta(days=CV_WINDOW * k)
        tr = feat[feat["date"] <= cut]
        te = feat[(feat["date"] > cut) & (feat["date"] <= cut + pd.Timedelta(days=CV_WINDOW))]
        if not te.empty:
            yield tr, te


def cv_eval(feat, feats, spec, params):
    """mean,std MAE of ONE spec across rolling folds."""
    errs = []
    for tr, te in _folds(feat):
        gm = tr["n"].mean()
        errs.append(mae(te["n"].values, _cand_pred(spec, tr, te, gm, feats, params)))
    return float(np.mean(errs)), float(np.std(errs))


def rolling_cv(feat, feats, params):
    scores = {k: [] for k in CANDIDATES}
    mase_n = mase_d = wape_n = wape_d = 0.0
    prec = []
    for tr, te in _folds(feat):
        gm = tr["n"].mean(); y = te["n"].values
        preds = {n: _cand_pred(s, tr, te, gm, feats, params) for n, s in CANDIDATES.items()}
        for n in CANDIDATES:
            scores[n].append(mae(y, preds[n]))
        ref = preds["LGBM Poisson"]
        sn = np.where(np.isnan(te["lag7"].values), gm, te["lag7"].values)
        mase_n += np.abs(y - ref).sum(); mase_d += np.abs(y - sn).sum()
        wape_n += np.abs(y - ref).sum(); wape_d += y.sum()
        d1 = te[te["date"] == te["date"].min()].copy()
        d1["p"] = _cand_pred(CANDIDATES["LGBM Poisson"], tr, d1, gm, feats, params)
        tt = set(d1.sort_values("n", ascending=False).head(10)["police_station"])
        pp = set(d1.sort_values("p", ascending=False).head(10)["police_station"])
        prec.append(len(tt & pp) / 10)
    summ = {k: (float(np.mean(v)), float(np.std(v))) for k, v in scores.items() if v}
    return summ, mase_n / mase_d, 100 * wape_n / wape_d, float(np.mean(prec))


# --------------------------------------------------------------------------- AutoETS (classical benchmark)
def ets_cv_mae(grid):
    try:
        from statsforecast import StatsForecast
        from statsforecast.models import AutoETS
        errs = []
        long = grid.rename(columns={"police_station": "unique_id", "date": "ds", "n": "y"})
        dmax = long["ds"].max()
        for k in range(CV_FOLDS, 0, -1):
            cut = dmax - pd.Timedelta(days=CV_WINDOW * k)
            tr = long[long["ds"] <= cut]
            te = long[(long["ds"] > cut) & (long["ds"] <= cut + pd.Timedelta(days=CV_WINDOW))]
            if te.empty:
                continue
            sf = StatsForecast(models=[AutoETS(season_length=7)], freq="D", n_jobs=1)
            sf.fit(tr[["unique_id", "ds", "y"]])
            fc = sf.predict(h=CV_WINDOW).reset_index()
            mcol = [c for c in fc.columns if c not in ("unique_id", "ds")][0]
            j = te.merge(fc, on=["unique_id", "ds"], how="left")
            j[mcol] = j[mcol].clip(lower=0).fillna(j["y"].mean())
            errs.append(mae(j["y"].values, j[mcol].values))
        return float(np.mean(errs)) if errs else None
    except Exception as e:  # noqa: BLE001
        print(f"[fcst] AutoETS skipped: {type(e).__name__}: {str(e)[:80]}")
        return None


# --------------------------------------------------------------------------- conformal (Mondrian)
def station_tiers(feat):
    """Split stations into low/mid/high volume tiers for per-group (Mondrian) conformal."""
    mv = feat.groupby("police_station")["n"].mean()
    return pd.qcut(mv.rank(method="first"), 3, labels=["low", "mid", "high"]).astype(str)


def _q_from_scores(s):
    n = len(s)
    return float(np.quantile(s, min(1.0, np.ceil((n + 1) * (1 - ALPHA)) / n))) if n else 0.0


def conformal_Q(feat, feats, params, stn_tier):
    """Mondrian split-conformal: a separate interval width per volume tier so big and
    small stations both get honest ~80% coverage (global Q over-/under-covers them)."""
    import lightgbm as lgb
    dmax = feat["date"].max()
    cut = dmax - pd.Timedelta(days=CAL_DAYS)
    tr, cal = feat[feat["date"] <= cut].copy(), feat[feat["date"] > cut].copy()
    if cal.empty or len(tr) < 100:
        return {"global": 0.0}, 0.0, None, None
    q10 = lgb.LGBMRegressor(objective="quantile", alpha=ALPHA / 2, **params).fit(tr[feats], tr["n"])
    q90 = lgb.LGBMRegressor(objective="quantile", alpha=1 - ALPHA / 2, **params).fit(tr[feats], tr["n"])
    lo = np.clip(q10.predict(cal[feats]), 0, None); hi = np.clip(q90.predict(cal[feats]), 0, None)
    y = cal["n"].values
    cal["score"] = np.maximum(lo - y, y - hi)
    cal["tier"] = cal["police_station"].map(stn_tier)
    gQ = _q_from_scores(cal["score"].values)
    Qby = {"global": gQ}
    for t, grp in cal.groupby("tier"):
        Qby[t] = _q_from_scores(grp["score"].values) if len(grp) >= 20 else gQ
    teQ = cal["tier"].map(lambda t: Qby.get(t, gQ)).values
    cov_raw = float(np.mean((y >= lo) & (y <= hi)))
    cov_mon = float(np.mean((y >= lo - teQ) & (y <= hi + teQ)))
    return Qby, gQ, cov_raw, cov_mon


# --------------------------------------------------------------------------- main
def main(source=None):
    import lightgbm as lgb

    daily = pd.read_parquet(C.PROCESSED / "daily_station.parquet")
    grid = build_grid(daily)
    years = sorted({grid["date"].min().year, grid["date"].max().year})
    hol = indian_holidays(years)
    feat = make_features(grid, hol).dropna(subset=["lag14", "roll28"])
    print(f"[fcst] rows={len(feat):,}  stations={grid['police_station'].nunique()}")

    # 1) base objective via CV
    cv0, *_ = rolling_cv(feat, FEATS_BASE, BASE_PARAMS)
    gbm_only = {k: v for k, v in cv0.items() if k.startswith(("LGBM", "Blend"))}
    best = min(gbm_only, key=lambda k: gbm_only[k][0] + 0.25 * gbm_only[k][1])
    spec = CANDIDATES[best]
    print(f"[fcst] base objective: {best} ({gbm_only[best][0]:.2f})")

    # 2) CV-gated forward feature selection
    feats = list(FEATS_BASE)
    cur = cv_eval(feat, feats, spec, BASE_PARAMS)
    cur_risk = cur[0] + 0.25 * cur[1]
    kept = []
    for c in EXTRA_CANDS:
        trial = cv_eval(feat, feats + [c], spec, BASE_PARAMS)
        if trial[0] + 0.25 * trial[1] < cur_risk - 1e-3:
            feats.append(c); kept.append(c); cur_risk = trial[0] + 0.25 * trial[1]
    print(f"[fcst] features kept (CV-gated): {kept or 'none - parsimony wins'}")

    # 3) Optuna tuning gated by CV
    params = dict(BASE_PARAMS)
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def obj(trial):
            p = dict(BASE_PARAMS,
                     learning_rate=trial.suggest_float("learning_rate", 0.02, 0.08, log=True),
                     num_leaves=trial.suggest_int("num_leaves", 12, 40),
                     min_child_samples=trial.suggest_int("min_child_samples", 20, 60),
                     reg_lambda=trial.suggest_float("reg_lambda", 0.0, 3.0),
                     reg_alpha=trial.suggest_float("reg_alpha", 0.0, 1.0),
                     subsample=trial.suggest_float("subsample", 0.7, 1.0),
                     colsample_bytree=trial.suggest_float("colsample_bytree", 0.7, 1.0))
            m, sd = cv_eval(feat, feats, spec, p)
            return m + 0.25 * sd
        study = optuna.create_study(direction="minimize")
        study.optimize(obj, n_trials=25, show_progress_bar=False)
        tuned = dict(BASE_PARAMS, **study.best_params)
        tm = cv_eval(feat, feats, spec, tuned)
        if tm[0] + 0.25 * tm[1] < cur_risk - 1e-3:
            params = tuned; cur_risk = tm[0] + 0.25 * tm[1]
            print(f"[fcst] Optuna improved CV -> {tm[0]:.2f} (kept tuned params)")
        else:
            print(f"[fcst] Optuna gave no CV gain ({tm[0]:.2f}) - kept defaults (anti-overfit)")
    except Exception as e:  # noqa: BLE001
        print(f"[fcst] Optuna skipped: {type(e).__name__}")

    # 4) final bake-off (incl. AutoETS classical benchmark) for the report
    cv, mase, wape, prec10 = rolling_cv(feat, feats, params)
    ets_mae = ets_cv_mae(grid)   # benchmarked separately; classical ETS is unstable on
    # these intermittent, zero-heavy station series, so it's reported as a footnote, not charted.
    print(f"[fcst] selected={best} feats={len(feats)} | MASE={mase:.3f} WAPE={wape:.1f}% prec@10={prec10:.2f}"
          + (f" | AutoETS MAE={ets_mae:.2f} (unstable, excluded from chart)" if ets_mae else ""))

    # 5) leak-free n_estimators (inner split) then refit on ALL data
    dmax = feat["date"].max()
    tin, vin = feat[feat["date"] <= dmax - pd.Timedelta(days=21)], feat[feat["date"] > dmax - pd.Timedelta(days=21)]
    pin = dict(params)
    if spec["obj"]:
        pin["objective"] = spec["obj"]
    yt = np.log1p(tin["n"]) if spec["log"] else tin["n"]
    yv = np.log1p(vin["n"]) if spec["log"] else vin["n"]
    es = lgb.LGBMRegressor(**pin).fit(tin[feats], yt, eval_set=[(vin[feats], yv)], eval_metric="l1",
                                      callbacks=[lgb.early_stopping(60, verbose=False)])
    n_used = es.best_iteration_ or params["n_estimators"]
    model = _gbm(feat[feats], feat["n"], params, spec["obj"], spec["log"], n_estimators=n_used)

    # 6) Mondrian (per volume-tier) conformal + quantile models on all data
    stn_tier = station_tiers(feat)
    Qby, gQ, cov_raw, cov_cqr = conformal_Q(feat, feats, params, stn_tier)
    q10m = lgb.LGBMRegressor(objective="quantile", alpha=ALPHA / 2, **params).fit(feat[feats], feat["n"])
    q90m = lgb.LGBMRegressor(objective="quantile", alpha=1 - ALPHA / 2, **params).fit(feat[feats], feat["n"])
    print(f"[fcst] Mondrian conformal Q={ {k: round(v,2) for k,v in Qby.items()} } "
          f"coverage {None if cov_raw is None else round(100*cov_raw)}%"
          f"->{None if cov_cqr is None else round(100*cov_cqr)}% (target 80%)")

    clim = feat.groupby(["police_station", "dow"])["n"].mean(); gm = feat["n"].mean()

    def point_predict(cur_):
        ma = np.where(np.isnan(cur_["roll7"].values), gm, cur_["roll7"].values)
        p = _pred(model, cur_[feats])
        return 0.5 * p + 0.5 * ma if spec["blend"] else p

    # 7) recursive 7-day forecast
    hist = grid.copy(); last = hist["date"].max(); rows = []
    for step in range(1, HORIZON + 1):
        fdate = last + pd.Timedelta(days=step)
        hist = pd.concat([hist, pd.DataFrame({"police_station": grid["police_station"].unique(),
                                              "date": fdate, "n": np.nan})], ignore_index=True)
        cur_ = make_features(hist, hol); cur_ = cur_[cur_["date"] == fdate]
        pred = point_predict(cur_)
        qrow = cur_["police_station"].map(stn_tier).map(lambda t: Qby.get(t, gQ)).fillna(gQ).values
        lo = np.clip(q10m.predict(cur_[feats]), 0, None) - qrow
        hi = np.clip(q90m.predict(cur_[feats]), 0, None) + qrow
        hist.loc[hist["date"] == fdate, "n"] = pred
        cl = cur_.set_index(["police_station", "dow"]).index.map(clim).astype(float).values
        rows.append(pd.DataFrame({
            "police_station": cur_["police_station"].values, "date": fdate,
            "pred": np.round(pred, 1), "p10": np.round(np.clip(np.minimum(lo, pred), 0, None), 1),
            "p90": np.round(np.maximum(hi, pred), 1),
            "baseline": np.round(np.where(np.isnan(cl), gm, cl), 1),
            "is_future": True, "horizon": step}))
    fc = pd.concat(rows, ignore_index=True)
    histtail = (grid[grid["date"] > last - pd.Timedelta(days=30)]
                .rename(columns={"n": "pred"})[["police_station", "date", "pred"]])
    for c in ("p10", "p90", "baseline"):
        histtail[c] = histtail["pred"]
    histtail["is_future"] = False; histtail["horizon"] = 0
    pd.concat([histtail, fc], ignore_index=True).to_parquet(C.PROCESSED / "forecast.parquet", index=False)
    (fc.groupby("police_station")[["pred", "p10", "p90"]].sum().round(0).reset_index()
       .to_parquet(C.PROCESSED / "forecast_weekly.parquet", index=False))
    # hierarchical bottom-up: city total = Σ stations (coherent by construction)
    (fc.groupby("date")[["pred", "p10", "p90"]].sum().round(0).reset_index()
       .to_parquet(C.PROCESSED / "forecast_city.parquet", index=False))

    # 8) metrics
    mae_best, mae_clim = cv[best][0], cv["Climatology"][0]
    fi = pd.Series(model[0].feature_importances_, index=feats).sort_values(ascending=False)
    metrics = {
        "mae_model": round(mae_best, 2), "mae_baseline": round(mae_clim, 2),
        "improvement_pct": round(100 * (mae_clim - mae_best) / mae_clim, 1),
        "cv_folds": CV_FOLDS, "horizon_days": HORIZON,
        "best_model": best, "features_used": feats, "features_added": kept,
        "model": f"{best} (rolling-CV selected, {len(feats)} feats) + conformal p10–p90",
        "n_estimators_used": int(n_used), "tuned": params != BASE_PARAMS,
        "mase": round(mase, 3), "wape_pct": round(wape, 1), "precision_at_10": round(prec10, 2),
        "coverage_raw_pct": None if cov_raw is None else round(100 * cov_raw, 1),
        "coverage_conformal_pct": None if cov_cqr is None else round(100 * cov_cqr, 1),
        "conformal_Q": {k: round(v, 2) for k, v in Qby.items()},
        "conformal_method": "Mondrian split-conformal (per volume tier)",
        "ets_mae": None if ets_mae is None else round(ets_mae, 2),
        "bakeoff": {k: round(v[0], 2) for k, v in cv.items()},
        "bakeoff_std": {k: round(v[1], 2) for k, v in cv.items()},
        "feature_importance": {k: int(v) for k, v in fi.items()},
    }
    (C.MODELS.parent / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print("[fcst] DONE.", json.dumps({k: metrics[k] for k in
          ("best_model", "mae_model", "improvement_pct", "mase", "precision_at_10",
           "coverage_conformal_pct", "tuned")}))


if __name__ == "__main__":
    main()

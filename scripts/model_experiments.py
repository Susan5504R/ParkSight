"""
Read-only forecasting experiments to find genuine, non-overfitting improvements.
Compares model variants under ROLLING-ORIGIN cross-validation (not a single holdout),
plus diagnostics: scale-free errors (MASE/WAPE), error concentration, interval coverage.
Writes nothing to data/.
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from parksight import config as C  # noqa: E402
from parksight.models.train_forecast import (make_features, build_grid,  # noqa: E402
                                             indian_holidays)
warnings.filterwarnings("ignore")
import lightgbm as lgb  # noqa: E402
from sklearn.linear_model import Ridge  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

BASE_FEATS = ["lag1", "lag7", "lag14", "roll3", "roll7", "roll14", "roll28",
              "dow", "is_weekend", "month", "doy", "is_holiday", "station_code"]
PARAMS = dict(n_estimators=500, learning_rate=0.05, num_leaves=24, subsample=0.85,
              colsample_bytree=0.85, min_child_samples=30, reg_lambda=1.0,
              reg_alpha=0.2, random_state=42, verbose=-1)


def mae(a, b):
    return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))


def add_extra(df):
    g = df.groupby("police_station")["n"]
    df["ewma7"] = g.shift(1).ewm(span=7).mean().reset_index(0, drop=True)
    df["roll_std7"] = g.shift(1).rolling(7).std().reset_index(0, drop=True)
    df["roll_med7"] = g.shift(1).rolling(7).median().reset_index(0, drop=True)
    return df


def with_samedow(tr, te):
    m = tr.groupby(["police_station", "dow"])["n"].mean()
    gm = tr["n"].mean()
    for d in (tr, te):
        d["samedow"] = d.set_index(["police_station", "dow"]).index.map(m).astype(float)
        d["samedow"] = d["samedow"].fillna(gm)
    return tr, te


def fit_pred(objective, tr, te, feats, target_log=False):
    Xtr, Xte = tr[feats], te[feats]
    ytr = np.log1p(tr["n"]) if target_log else tr["n"]
    p = dict(PARAMS)
    if objective:
        p["objective"] = objective
    m = lgb.LGBMRegressor(**p).fit(Xtr, ytr)
    pred = m.predict(Xte)
    if target_log:
        pred = np.expm1(pred)
    return np.clip(pred, 0, None)


def main():
    daily = pd.read_parquet(C.PROCESSED / "daily_station.parquet")
    grid = build_grid(daily)
    years = sorted({grid["date"].min().year, grid["date"].max().year})
    hol = indian_holidays(years)
    feat = add_extra(make_features(grid, hol)).dropna(
        subset=["lag14", "roll28", "roll_std7"])
    dmax = feat["date"].max()
    EXTRA = BASE_FEATS + ["ewma7", "roll_std7", "roll_med7", "samedow"]

    # rolling-origin: 5 folds, each predicts a 7-day window
    cuts = [dmax - pd.Timedelta(days=7 * k) for k in range(5, 0, -1)]
    variants = {
        "MA-7 (reference)": [], "Climatology(stn x dow)": [], "Seasonal-naive lag7": [],
        "LGBM L2 (base)": [], "LGBM Poisson": [], "LGBM Tweedie": [], "LGBM log1p": [],
        "LGBM L2 +extra feats": [], "Ridge +extra": [],
        "Blend LGBM-Poisson+MA7": [],
    }
    mase_num, mase_den, wape_num, wape_den = [], [], [], []

    for cut in cuts:
        tr = feat[feat["date"] <= cut].copy()
        te = feat[(feat["date"] > cut) & (feat["date"] <= cut + pd.Timedelta(days=7))].copy()
        if len(te) == 0:
            continue
        tr, te = with_samedow(tr, te)
        y = te["n"].values
        variants["MA-7 (reference)"].append(mae(y, te["roll7"].fillna(tr["n"].mean())))
        variants["Climatology(stn x dow)"].append(mae(y, te["samedow"]))
        variants["Seasonal-naive lag7"].append(mae(y, te["lag7"].fillna(tr["n"].mean())))
        p_l2 = fit_pred(None, tr, te, BASE_FEATS)
        p_po = fit_pred("poisson", tr, te, BASE_FEATS)
        p_tw = fit_pred("tweedie", tr, te, BASE_FEATS)
        p_lg = fit_pred(None, tr, te, BASE_FEATS, target_log=True)
        p_ex = fit_pred(None, tr, te, EXTRA)
        sc = StandardScaler().fit(tr[EXTRA].fillna(0))
        rid = Ridge(alpha=5.0).fit(sc.transform(tr[EXTRA].fillna(0)), tr["n"])
        p_ri = np.clip(rid.predict(sc.transform(te[EXTRA].fillna(0))), 0, None)
        ma = te["roll7"].fillna(tr["n"].mean()).values
        variants["LGBM L2 (base)"].append(mae(y, p_l2))
        variants["LGBM Poisson"].append(mae(y, p_po))
        variants["LGBM Tweedie"].append(mae(y, p_tw))
        variants["LGBM log1p"].append(mae(y, p_lg))
        variants["LGBM L2 +extra feats"].append(mae(y, p_ex))
        variants["Ridge +extra"].append(mae(y, p_ri))
        variants["Blend LGBM-Poisson+MA7"].append(mae(y, 0.5 * p_po + 0.5 * ma))
        # scale-free vs seasonal-naive
        mase_num.append(np.abs(y - p_po).sum())
        mase_den.append(np.abs(y - te["lag7"].fillna(tr["n"].mean()).values).sum())
        wape_num.append(np.abs(y - p_po).sum()); wape_den.append(y.sum())

    print("=" * 64)
    print("ROLLING-ORIGIN CV (5 folds x 7-day windows) — mean MAE ± std")
    print("=" * 64)
    res = {k: (np.mean(v), np.std(v)) for k, v in variants.items() if v}
    for k, (mu, sd) in sorted(res.items(), key=lambda x: x[1][0]):
        print(f"  {k:26s} {mu:6.2f} ± {sd:4.2f}")
    best = min(res, key=lambda k: res[k][0])
    print(f"\n  BEST: {best} ({res[best][0]:.2f})")
    print(f"  MASE (Poisson vs seasonal-naive): {np.sum(mase_num)/np.sum(mase_den):.3f}  "
          f"(<1 = beats seasonal-naive)")
    print(f"  WAPE (Poisson): {100*np.sum(wape_num)/np.sum(wape_den):.1f}%")

    # interval coverage + error concentration on final holdout
    cut = cuts[-1]
    tr = feat[feat["date"] <= cut].copy()
    te = feat[(feat["date"] > cut) & (feat["date"] <= cut + pd.Timedelta(days=7))].copy()
    q10 = lgb.LGBMRegressor(objective="quantile", alpha=0.1, **PARAMS).fit(tr[BASE_FEATS], tr["n"])
    q90 = lgb.LGBMRegressor(objective="quantile", alpha=0.9, **PARAMS).fit(tr[BASE_FEATS], tr["n"])
    lo = np.clip(q10.predict(te[BASE_FEATS]), 0, None)
    hi = np.clip(q90.predict(te[BASE_FEATS]), 0, None)
    cov = float(np.mean((te["n"].values >= lo) & (te["n"].values <= hi)))
    print(f"\n  p10–p90 interval coverage: {100*cov:.1f}%  (target ≈ 80%)")

    p_po = fit_pred("poisson", tr, te, BASE_FEATS)
    err = pd.Series(np.abs(te["n"].values - p_po), index=te["police_station"].values)
    by_stn = err.groupby(level=0).sum().sort_values(ascending=False)
    share = 100 * by_stn.head(5).sum() / by_stn.sum()
    print(f"  Top-5 stations' share of total abs error: {share:.0f}%  "
          f"(high = scale dominated by big stations)")
    print("  Worst stations:", ", ".join(f"{s}({e:.0f})" for s, e in by_stn.head(5).items()))

    # DIRECT multi-horizon: train one model per horizon (target shifted by h) — avoids
    # recursive error compounding. Shows how accuracy degrades with horizon.
    print("\n  Direct multi-horizon (Poisson, CV MAE by horizon):")
    for h in (1, 3, 7):
        d = feat.copy()
        d["y_h"] = d.groupby("police_station")["n"].shift(-h)
        d = d.dropna(subset=["y_h"])
        dm = d["date"].max()
        errs = []
        for k in range(5, 0, -1):
            c = dm - pd.Timedelta(days=7 * k)
            tr = d[d["date"] <= c]; te = d[(d["date"] > c) & (d["date"] <= c + pd.Timedelta(days=7))]
            if te.empty:
                continue
            m = lgb.LGBMRegressor(objective="poisson", **PARAMS).fit(tr[BASE_FEATS], tr["y_h"])
            errs.append(mae(te["y_h"].values, np.clip(m.predict(te[BASE_FEATS]), 0, None)))
        print(f"      day+{h}: MAE {np.mean(errs):.2f}  (day+1 is already 'direct' in production)")

    # ranking quality: does day+1 correctly find tomorrow's top-10 hot stations?
    d1 = te[te["date"] == te["date"].min()].copy()
    d1["pred"] = fit_pred("poisson", tr, d1, BASE_FEATS)
    true_top = set(d1.sort_values("n", ascending=False).head(10)["police_station"])
    pred_top = set(d1.sort_values("pred", ascending=False).head(10)["police_station"])
    print(f"  Top-10 hotspot precision@10 (day+1): {len(true_top & pred_top)}/10")


if __name__ == "__main__":
    main()

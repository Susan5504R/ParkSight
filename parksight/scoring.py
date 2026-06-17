"""Framework-agnostic scoring helpers — the single source of truth for deriving
PCIS, patrol units, tiers and the enforcement-gap.

Imported by the ETL, the Streamlit app (lib), the briefing PDF and the Copilot
engine so none of them drift from one another. No Streamlit / app dependencies.
"""
import numpy as np
import pandas as pd

from parksight import config as C


def _mm(s):
    """Min-max scale a Series to 0-1 (flat series → zeros)."""
    s = pd.Series(s).astype(float)
    lo, hi = s.min(), s.max()
    return (s - lo) / (hi - lo) if hi - lo > 1e-12 else s * 0.0


def recompute_pcis(df, weights):
    """Re-score a frame carrying V/S/L/P/T components for an arbitrary weight dict.

    Mirrors the ETL formula exactly: weights are normalised to a convex
    combination (Σ=1) so the score can't exceed the component scale, then the raw
    composite is min-max stretched to a 0-100 range within this frame. Returns
    (scored_df_sorted_desc, normalised_weights) — `PCIS_live` holds the new score."""
    tot = sum(max(0.0, float(weights[k])) for k in "VSLPT") or 1.0
    norm = {k: max(0.0, float(weights[k])) / tot for k in "VSLPT"}
    raw = sum(norm[k] * df[k] for k in "VSLPT")
    lo, hi = raw.min(), raw.max()
    out = df.copy()
    out["PCIS_live"] = (100 * (raw - lo) / (hi - lo + 1e-9)).round(1)
    return out.sort_values("PCIS_live", ascending=False), norm


def recommended_units(pcis):
    """Patrol units recommended for a zone from its PCIS. Accepts a scalar or a
    Series; returns the matching type (int, or an int Series)."""
    scalar = np.isscalar(pcis)
    u = (pd.Series([pcis]) if scalar else pd.Series(pcis))
    out = (u / 100 * C.UNITS_PER_PCIS).round().clip(lower=1).astype(int)
    return int(out.iloc[0]) if scalar else out


def assign_tier(pcis):
    """Low / Medium / High tier for a PCIS scalar or Series (returns a Categorical)."""
    return pd.cut(pd.Series(pcis), bins=C.TIER_BINS, labels=C.TIER_LABELS)


def gap_score(pcis, evening_share):
    """Enforcement-Gap (0-100): high predicted impact but low evening enforcement
    presence. gap = minmax(PCIS) - minmax(evening_share), rescaled to 0-100."""
    return (100 * _mm(_mm(pcis) - _mm(evening_share))).round(1)

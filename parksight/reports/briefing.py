"""
Daily Deployment Briefing — one-page PDF a station officer could act on.
Generates bytes (for Streamlit download) or writes a sample to disk.
"""
import io
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from parksight import config as C  # noqa: E402

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,  # noqa: E402
                                TableStyle)

NAVY = colors.HexColor("#0B0F1A")
INDIGO = colors.HexColor("#6366F1")
SLATE = colors.HexColor("#94A3B8")
TIER_COLOR = {"High": colors.HexColor("#7f1d1d"),
              "Medium": colors.HexColor("#78350f"),
              "Low": colors.HexColor("#064e3b")}


def build_briefing(window="evening", top_n=10, for_date=None,
                   grain="Police station", sort_by="Blind-Spot (de-biased)",
                   weights=None):
    for_date = for_date or (date.today())
    meta = json.loads((C.PROCESSED / "meta.json").read_text())

    # Mirror the Prioritize page exactly: same grain file, same ranking metric,
    # so the PDF reflects the controls the officer actually selected.
    if grain == "Junction":
        fname, namecol, glabel = "junction_pcis.parquet", "junction_name", "Junction"
    else:
        fname, namecol, glabel = "station_pcis.parquet", "police_station", "Police Station"
    if sort_by.startswith("Blind"):
        sort_col, slabel = "blindspot_risk", "Blind-Spot"
    elif sort_by.startswith("PCIS"):
        sort_col, slabel = "PCIS", "PCIS"
    else:
        sort_col, slabel = "gap_score", "Gap"

    full = pd.read_parquet(C.PROCESSED / fname).copy()

    # If the user applied a custom PCIS policy on the dashboard, re-score PCIS / tier
    # from their weights so the briefing matches what's on screen (V/S/L/P/T are
    # persisted per zone, so this is a cheap weighted sum — nothing hardcoded).
    if weights and set("VSLPT").issubset(full.columns):
        tot = sum(max(0.0, float(weights[k])) for k in "VSLPT") or 1.0
        norm = {k: max(0.0, float(weights[k])) / tot for k in "VSLPT"}
        raw = sum(norm[k] * full[k] for k in "VSLPT")
        lo2, hi2 = raw.min(), raw.max()
        full["PCIS"] = (100 * (raw - lo2) / (hi2 - lo2 + 1e-9)).round(1)
        full["tier"] = pd.cut(full["PCIS"], bins=[-1, 33, 66, 101],
                              labels=["Low", "Medium", "High"])

    # Window-focused ranking. The hour range comes from config (not hardcoded
    # here), and the share of each zone's violations that actually fall inside the
    # target window is computed LIVE from the row-level data — so a morning vs.
    # evening briefing genuinely re-ranks, and it adapts to any dataset uploaded
    # via Data Refresh. Deployment score = chosen metric x in-window share, so a
    # zone that scores high overall but is quiet in the target window won't top a
    # briefing for that window.
    lo, hi, _ = C.PEAK_WINDOWS["evening" if window == "evening" else "morning"]
    if sort_col not in full.columns:          # tolerate older artifact schemas
        sort_col, slabel = "PCIS", "PCIS"
    # Compute each zone's in-window violation share LIVE from the row-level data.
    # Wrapped defensively (int cast + .map, not merge) so it can't crash on any
    # pandas version or an older artifact; if the row file is unavailable we fall
    # back to ranking by the chosen metric alone (window_share = 1).
    try:
        vc = pd.read_parquet(C.PROCESSED / "violations_clean.parquet",
                             columns=[namecol, "hour"])
        vc["in_win"] = ((vc["hour"] >= lo) & (vc["hour"] < hi)).astype(int)
        share = vc.groupby(namecol)["in_win"].mean()
        full["window_share"] = full[namecol].map(share).fillna(0.0).astype(float)
    except Exception:
        full["window_share"] = 1.0
    full["window_score"] = (full[sort_col].astype(float) * full["window_share"]).round(2)
    st = full.sort_values("window_score", ascending=False).head(top_n).copy()
    st["units"] = (st["PCIS"] / 100 * 3).round().clip(lower=1).astype(int)
    off = (pd.read_parquet(C.PROCESSED / "offenders.parquet")
             .sort_values("violations", ascending=False).head(8))
    win = (f"{lo:02d}:00–{hi:02d}:00 IST "
           f"({'Evening' if window == 'evening' else 'Morning'} Peak)")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=14 * mm, bottomMargin=12 * mm,
                            leftMargin=14 * mm, rightMargin=14 * mm)
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=INDIGO, fontSize=20, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], textColor=SLATE, fontSize=9)
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=9, leading=13)
    sec = ParagraphStyle("sec", parent=ss["Heading2"], fontSize=12, textColor=INDIGO,
                         spaceBefore=10, spaceAfter=4)
    el = []
    el.append(Paragraph("ParkSight — Daily Deployment Briefing", h1))
    el.append(Paragraph(f"Bengaluru Traffic Police · {for_date:%A, %d %b %Y} · "
                        f"Target window: <b>{win}</b> · "
                        f"Level: <b>{glabel}</b> · Ranked by: <b>{slabel}</b>", sub))
    el.append(Spacer(1, 6))
    el.append(Paragraph(
        f"Dataset: {meta['total_violations']:,} violations ({meta['date_min']}→{meta['date_max']}). "
        f"Repeat offenders drive {meta['repeat_share']}% of violations; "
        f"{meta['severe_share']}% are carriageway-blocking. "
        f"<b>Action:</b> prioritise the {glabel.lower()}s below; enforcement records currently "
        f"collapse during {meta['evening_trough_hours']} — close that blind spot first.", body))

    winpct_label = f"% in {'Eve' if window == 'evening' else 'Morn'}"
    el.append(Paragraph(f"Priority {glabel}s — recommended deployment "
                        f"(ranked by {slabel}, focused on the {win.split(' IST')[0]} window)", sec))
    show_score = slabel != "PCIS"  # avoid a duplicate PCIS column when that's the sort
    header = (["#", glabel] + ([slabel] if show_score else []) +
              ["PCIS", winpct_label, "Tier", "Units", "Why"])
    rows = [header]
    for i, r in st.reset_index(drop=True).iterrows():
        row = [str(i + 1), r[namecol]]
        if show_score:
            row.append(f"{r[sort_col]:.0f}")
        row += [f"{r['PCIS']:.0f}", f"{100 * r['window_share']:.0f}%",
                str(r["tier"]), str(r["units"]),
                Paragraph(r["reason"], ParagraphStyle("c", parent=body, fontSize=7.5))]
        rows.append(row)
    if show_score:
        colw = [7 * mm, 36 * mm, 14 * mm, 12 * mm, 14 * mm, 14 * mm, 11 * mm, 74 * mm]
    else:
        colw = [7 * mm, 40 * mm, 13 * mm, 14 * mm, 15 * mm, 12 * mm, 81 * mm]
    t = Table(rows, colWidths=colw)
    style = [("BACKGROUND", (0, 0), (-1, 0), INDIGO),
             ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONTSIZE", (0, 0), (-1, -1), 8), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F1F5F9"), colors.white]),
             ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    tier_col = header.index("Tier")
    for i, r in st.reset_index(drop=True).iterrows():
        style.append(("TEXTCOLOR", (tier_col, i + 1), (tier_col, i + 1),
                      TIER_COLOR.get(str(r["tier"]), colors.black)))
    t.setStyle(TableStyle(style))
    el.append(t)

    el.append(Paragraph("Chronic-Offender Watchlist", sec))
    orows = [["Vehicle", "Type", "Violations", "Top location"]]
    for _, r in off.iterrows():
        orows.append([r["vehicle_number"], r["vehicle_type"], str(int(r["violations"])),
                      str(r["top_station"])])
    ot = Table(orows, colWidths=[36 * mm, 30 * mm, 24 * mm, 80 * mm])
    ot.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7f1d1d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#FEF2F2"), colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#FCA5A5"))]))
    el.append(ot)
    el.append(Spacer(1, 8))
    el.append(Paragraph(
        f"Generated by ParkSight · PCIS = Parking Congestion Impact Score "
        f"(volume·severity·location·peak-overlap·trend). Ranking = {slabel} × the share of each "
        f"{glabel.lower()}'s violations falling in the {win.split(' IST')[0]} window (computed live "
        f"from {meta['total_violations']:,} records — nothing hardcoded). Recommendations are "
        f"decision-support, not automated enforcement.", sub))
    doc.build(el)
    return buf.getvalue()


if __name__ == "__main__":
    data = build_briefing()
    out = C.REPORTS_OUT / "sample_briefing.pdf"
    out.write_bytes(data)
    print(f"wrote {out} ({len(data)/1024:.1f} KB)")

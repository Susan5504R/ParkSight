"""Render static PNG figures (snapshots + deck) and the architecture diagram."""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.patches as mpatches  # noqa: E402
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from parksight import config as C  # noqa: E402

plt.rcParams.update({
    "figure.facecolor": "#0B0F1A", "axes.facecolor": "#0B0F1A",
    "savefig.facecolor": "#0B0F1A", "text.color": "#E5E7EB",
    "axes.labelcolor": "#CBD5E1", "xtick.color": "#94A3B8", "ytick.color": "#94A3B8",
    "axes.edgecolor": "#243049", "font.size": 11, "axes.grid": True,
    "grid.color": "#1F2937", "grid.alpha": 0.6,
})
INDIGO, CYAN, AMBER, ORANGE, RED = "#6366F1", "#22D3EE", "#FACC15", "#F97316", "#EF4444"
A = C.ASSETS


def load(n):
    return pd.read_parquet(C.PROCESSED / n)


def fig_blindspot():
    hp = load("hourly_profile.parquet")
    bh = hp.groupby("hour")["n"].sum().reindex(range(24), fill_value=0)
    thresh = 0.15 * float(bh.max())
    low = [h for h in range(12, 24) if float(bh[h]) < thresh]
    x0, x1 = (min(low), max(low) + 1) if low else (14, 21)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.fill_between(bh.index, bh.values, color=INDIGO, alpha=0.25)
    ax.plot(bh.index, bh.values, color=INDIGO, lw=2.5)
    ax.axvspan(x0, x1, color=RED, alpha=0.13)
    ax.text((x0 + x1) / 2, bh.max() * 0.8, f"Enforcement\nblind-spot\nIST {x0:02d}:00–{x1:02d}:00",
            color="#FCA5A5", ha="center", fontsize=10, fontweight="bold")
    ax.set_xlabel("Hour of day (IST)"); ax.set_ylabel("Violations recorded")
    ax.set_title("When parking violations are recorded — the evening blind-spot",
                 color="#F8FAFC", fontweight="bold")
    ax.set_xlim(0, 23); ax.set_xticks(range(0, 24, 2))
    fig.tight_layout(); fig.savefig(A / "fig_blindspot.png", dpi=140); plt.close(fig)


def fig_top_zones():
    j = load("junction_pcis.parquet").sort_values("PCIS", ascending=False).head(12)
    fig, ax = plt.subplots(figsize=(9, 5))
    names = [n.split(" - ")[-1][:28] for n in j["junction_name"]]
    bars = ax.barh(names[::-1], j["PCIS"].values[::-1], color=ORANGE)
    ax.set_xlim(0, 100); ax.set_xlabel("PCIS")
    ax.set_title("Top junction hotspots by Parking Congestion Impact Score",
                 color="#F8FAFC", fontweight="bold")
    fig.tight_layout(); fig.savefig(A / "fig_top_zones.png", dpi=140); plt.close(fig)


def fig_violation_mix():
    vm = load("violation_mix.parquet").head(8)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.barh([t[:32] for t in vm["tags"]][::-1], vm["n"].values[::-1], color=CYAN)
    ax.set_xlabel("Violations"); ax.set_title("Violation-type mix (parking-dominated)",
                                               color="#F8FAFC", fontweight="bold")
    fig.tight_layout(); fig.savefig(A / "fig_violation_mix.png", dpi=140); plt.close(fig)


def fig_monthly():
    mt = load("monthly_trend.parquet")
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.bar(mt["month"], mt["n"], color=INDIGO)
    ax.set_ylabel("Violations"); ax.set_title("Monthly violation volume",
                                               color="#F8FAFC", fontweight="bold")
    fig.tight_layout(); fig.savefig(A / "fig_monthly.png", dpi=140); plt.close(fig)


def fig_forecast():
    fc = load("forecast.parquet")
    s = fc.loc[fc["is_future"]].groupby("police_station")["pred"].sum().idxmax()
    d = fc[fc["police_station"] == s].sort_values("date")
    h, f = d[~d["is_future"]], d[d["is_future"]]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(h["date"], h["pred"], color="#94A3B8", lw=2, label="Actual (recent)")
    ax.fill_between(f["date"], f["p10"], f["p90"], color=INDIGO, alpha=0.22, label="p10–p90")
    ax.plot(f["date"], f["pred"], color=INDIGO, lw=2.5, marker="o", label="Forecast")
    ax.plot(f["date"], f["baseline"], color=ORANGE, lw=1.8, ls=":", label="Baseline")
    ax.legend(facecolor="#161D2E", edgecolor="#243049", labelcolor="#E5E7EB")
    ax.set_title(f"7-day forecast with confidence — {s}", color="#F8FAFC", fontweight="bold")
    fig.autofmt_xdate(); fig.tight_layout()
    fig.savefig(A / "fig_forecast.png", dpi=140); plt.close(fig)


def fig_architecture():
    fig, ax = plt.subplots(figsize=(12, 7)); ax.axis("off")
    ax.set_xlim(0, 12); ax.set_ylim(0, 7)

    def box(x, y, w, h, text, fc="#161D2E", ec=INDIGO, tc="#F8FAFC", fs=10):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.04,rounding_size=0.12",
                                    fc=fc, ec=ec, lw=1.6))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                color=tc, fontsize=fs, fontweight="bold", wrap=True)

    def arrow(x1, y1, x2, y2):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                                     mutation_scale=16, color="#64748B", lw=1.6))

    ax.text(6, 6.6, "ParkSight — System Architecture", ha="center",
            color="#F8FAFC", fontsize=16, fontweight="bold")
    box(0.4, 5.0, 2.4, 1.0, "RAW CSV\n298,450 rows · 109 MB", fc="#1E293B", ec="#475569")
    box(3.4, 5.0, 3.0, 1.0, "ETL & FEATURE BUILD\nclean · UTC→IST · H3 · severity\nlocation · peak · repeat", ec=CYAN)
    box(7.0, 5.0, 2.3, 1.0, "PCIS ENGINE\nV·S·L·P·T → score\n+ DBSCAN zones", ec=ORANGE)
    box(9.6, 5.0, 2.0, 1.0, "FORECAST\nLightGBM\n+ quantiles", ec=AMBER)
    box(4.5, 3.1, 3.0, 1.0, "PROCESSED ARTIFACTS\n*.parquet · meta/metrics json\n(<50 MB, deployable)",
        fc="#0E1B2A", ec="#22C55E")
    # app modules
    mods = ["Executive\nDashboard", "Hotspot\nMap", "PCIS\nEngine", "Forecast",
            "Prioritize", "Simulator", "AI Copilot\n(Claude)", "Offenders"]
    for i, mtxt in enumerate(mods):
        box(0.3 + i * 1.46, 1.1, 1.34, 0.95, mtxt, fc="#161D2E", ec=INDIGO, fs=8.5)
    ax.text(6, 0.55, "STREAMLIT + pydeck (deck.gl) + Plotly  ·  reportlab PDF briefing",
            ha="center", color="#94A3B8", fontsize=10, style="italic")

    arrow(2.8, 5.5, 3.4, 5.5); arrow(6.4, 5.5, 7.0, 5.5); arrow(9.3, 5.5, 9.6, 5.5)
    arrow(8.1, 5.0, 6.5, 4.1); arrow(10.6, 5.0, 7.5, 4.1); arrow(4.9, 5.0, 5.8, 4.1)
    arrow(6.0, 3.1, 6.0, 2.05)
    fig.savefig(A / "architecture.png", dpi=140, bbox_inches="tight"); plt.close(fig)


def make_logo():
    fig, ax = plt.subplots(figsize=(6.2, 1.5)); ax.axis("off")
    ax.set_xlim(0, 6.2); ax.set_ylim(0, 1.5)
    ax.add_patch(FancyBboxPatch((0.08, 0.22), 1.0, 1.0,
                 boxstyle="round,pad=0.02,rounding_size=0.22", fc=INDIGO, ec="none"))
    ax.text(0.58, 0.72, "P", ha="center", va="center", color="white",
            fontsize=40, fontweight="bold")
    ax.add_patch(plt.Circle((0.95, 1.06), 0.12, color=CYAN))
    ax.text(1.32, 0.92, "ParkSight", va="center", color="#F8FAFC",
            fontsize=32, fontweight="bold")
    ax.text(1.34, 0.42, "Parking Congestion Intelligence", va="center",
            color="#94A3B8", fontsize=11.5)
    fig.savefig(A / "logo.png", dpi=170, transparent=True, bbox_inches="tight")
    plt.close(fig)


def main():
    make_logo()
    fig_blindspot(); fig_top_zones(); fig_violation_mix(); fig_monthly()
    fig_forecast(); fig_architecture()
    print("figures written to", A)
    for p in sorted(A.glob("*.png")):
        print("  ", p.name, f"{p.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()

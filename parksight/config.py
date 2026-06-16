"""Central configuration for ParkSight (paths, weights, windows)."""
from pathlib import Path

# --- Paths -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
RAW_CSV = ROOT / "jan to may police violation_anonymized791b166.csv"
DATA = ROOT / "parksight" / "data"
PROCESSED = DATA / "processed"
MODELS = ROOT / "parksight" / "models" / "artifacts"
ASSETS = ROOT / "parksight" / "assets"
REPORTS_OUT = ROOT / "parksight" / "reports" / "out"
for _p in (PROCESSED, MODELS, ASSETS, REPORTS_OUT):
    _p.mkdir(parents=True, exist_ok=True)

# --- Timezone ----------------------------------------------------------------
TZ_IST = "Asia/Kolkata"

# --- H3 resolutions ----------------------------------------------------------
H3_CITY = 8     # ~0.74 km^2  (city heat layer)
H3_HOT = 9      # ~0.10 km^2  (street-level hotspots)

# --- Severity weights (carriageway-blocking impact) --------------------------
# higher = blocks moving traffic more directly
SEVERITY_WEIGHTS = {
    "PARKING IN A MAIN ROAD": 1.00,
    "PARKING NEAR ROAD CROSSING": 0.95,
    "PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS": 0.95,
    "DOUBLE PARKING": 0.90,
    "PARKING ON FOOTPATH": 0.85,
    "PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC": 0.80,
    "PARKING OPPOSITE TO ANOTHER PARKED VEHICLE": 0.70,
    "PARKING OTHER THAN BUS STOP": 0.60,
    "WRONG PARKING": 0.50,
    "NO PARKING": 0.40,
}
SEVERITY_DEFAULT = 0.10  # non-parking / minor tags

# --- Location-criticality keywords (boost L component) -----------------------
LOCATION_KEYWORDS = [
    "market", "metro", "mall", "bus", "school", "hospital", "main road",
    "circle", "junction", "station", "temple", "theatre", "complex", "road",
]

# --- IST congestion windows (hour ranges, inclusive start / exclusive end) ---
PEAK_WINDOWS = {
    "morning": (8, 11, 0.9),    # 08:00-11:00
    "evening": (17, 21, 1.0),   # 17:00-21:00
}
OFFPEAK_WEIGHT = 0.30

# --- PCIS component weights (UI-tunable defaults) ----------------------------
PCIS_WEIGHTS = {"V": 0.30, "S": 0.20, "L": 0.20, "P": 0.20, "T": 0.10}

# --- Ground-truth anchor (expert face-validity set) --------------------------
# The dataset has no traffic-flow sensor column, so we validate PCIS against an
# EXPERT-LABELLED reference: well-known Bengaluru congestion landmarks vs. quiet
# residential junctions, ordered most→least congested by local traffic knowledge.
# This is a face-validity check (does the score agree with what humans already
# know is gridlocked?), NOT a claim of independent sensor ground truth. Each
# anchor is matched on its stable BTP code so renames/reorders can't break it.
# rank 1 = most congested. Spearman ρ vs. the live PCIS ranking is shown on the
# page and recomputed as the weights move — neutralising "your weights are
# arbitrary" by proving the formula reproduces a known ordering.
PCIS_GROUND_TRUTH = [
    # --- known severe bottlenecks ---
    ("BTP082", "KR Market Junction",   "high", 1),
    ("BTP051", "Safina Plaza Junction", "high", 2),
    ("BTP038", "Mysore Bank Junction",  "high", 3),
    ("BTP043", "Upparpet Junction",     "high", 4),
    ("BTP044", "Sagar Theatre Junction", "high", 5),
    ("BTP027", "Modi Bridge Junction",  "high", 6),
    # --- quiet residential / low-traffic junctions ---
    ("BTP216", "Yediyur Junction",            "low", 7),
    ("BTP164", "29th Main Road, BTM Layout",  "low", 8),
    ("BTP200", "15th Cross, 33rd Main, JP Nagar", "low", 9),
    ("BTP110", "Bharathi Nursing Home, Basavanagudi", "low", 10),
    ("BTP154", "Itmadu Junction",             "low", 11),
    ("BTP144", "Commando Hospital Junction",  "low", 12),
]

# --- De-biasing engine (selection-bias / endogeneity correction) -------------
# Tickets are a BIASED sample of true violations: a violation is only observed
# if an enforcement device is present. Enforcement collapses in the evening, so
# raw ticket counts under-report exactly when congestion peaks. We correct this
# with (a) inverse-propensity weighting of observed tickets by hourly enforcement
# exposure, and (b) an EXTERNAL congestion prior built from road hierarchy and a
# synthetic rush-hour profile — both decoupled from ticket timing, so they can
# never be "trained away" by the missing-evening-labels feedback loop.

# Road-hierarchy weight (OSM-style functional road class) inferred from the
# location/junction text. Static property of the PLACE, independent of WHEN a
# ticket was written — this is what makes it an unbiased spatial prior.
ROAD_HIERARCHY = {
    # arterial / trunk — carries the most through-traffic → highest congestion stake
    "main road": 1.00, "highway": 1.00, "circle": 0.95, "flyover": 0.95,
    "ring road": 0.95, "junction": 0.90, "metro": 0.85, "station": 0.80,
    # collector — feeds arterials
    "market": 0.75, "mall": 0.70, "complex": 0.65, "bus": 0.70,
    "hospital": 0.65, "school": 0.60, "temple": 0.55, "theatre": 0.55,
    # local
    "cross": 0.45, "layout": 0.40, "road": 0.40,
}
ROAD_HIERARCHY_DEFAULT = 0.35   # un-classified local street

# Synthetic congestion profile s(h): canonical bimodal urban traffic curve
# (morning + evening commute peaks) from traffic-engineering norms — NOT learned
# from ticket timestamps. This injects the prior that 17:00–21:00 is high-
# congestion regardless of whether any tickets were filed then.
SYNTHETIC_CONGESTION = {
    0: 0.10, 1: 0.06, 2: 0.05, 3: 0.05, 4: 0.08, 5: 0.18, 6: 0.35,
    7: 0.60, 8: 0.85, 9: 0.95, 10: 0.78, 11: 0.62, 12: 0.58, 13: 0.55,
    14: 0.52, 15: 0.55, 16: 0.68, 17: 0.88, 18: 1.00, 19: 1.00, 20: 0.90,
    21: 0.70, 22: 0.45, 23: 0.25,
}

# Inverse-propensity weighting controls (Horvitz–Thompson style)
EXPOSURE_FLOOR = 0.05    # min propensity to avoid divide-by-zero blow-up
IPW_WEIGHT_CAP = 12.0    # cap inverse weight so a near-zero-exposure hour can't dominate

# --- Misc --------------------------------------------------------------------
MIN_CELL_VIOLATIONS = 5      # ignore noise cells for hotspot ranking
TOP_N_ZONES = 20

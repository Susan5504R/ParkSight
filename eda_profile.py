"""
EDA / Data Profiling for Flipkart Gridlock 2.0 - Theme 1 (Parking Congestion).
Pure stdlib (no pandas) so it runs anywhere. Streams the full 298k-row file.
Produces a structured profiling report used to ground the SKILL.md plan.
"""
import csv, json, sys, math
from collections import Counter, defaultdict
from datetime import datetime

PATH = r"c:\Users\mazar\Desktop\projects\GLR2\jan to may police violation_anonymized791b166.csv"
csv.field_size_limit(10**7)

MISSING = {"", "NULL", "null", "None", None}

def parse_dt(s):
    if s in MISSING:
        return None
    s = s.strip()
    # forms: 2023-11-20 00:28:46+00 ; 2023-11-28 04:48:04.582978+00
    core = s.split("+")[0].split("Z")[0].strip()
    core = core.split(".")[0]
    try:
        return datetime.strptime(core, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(core, "%Y-%m-%d %H:%M")
        except ValueError:
            return None

def pct(sorted_list, p):
    if not sorted_list:
        return None
    k = (len(sorted_list) - 1) * p
    f = math.floor(k); c = math.ceil(k)
    if f == c:
        return sorted_list[int(k)]
    return sorted_list[f] * (c - k) + sorted_list[c] * (k - f)

rows = 0
null_counts = Counter()
cols = None
viol_tokens = Counter()
multi_viol = Counter()          # how many violation tags per ticket
veh_type = Counter()
upd_veh_type = Counter()
veh_type_changed = 0
val_status = Counter()
station = Counter()
junction = Counter()
center = set()
device = set()
veh_no = Counter()
hour_hist = Counter()
weekday_hist = Counter()
month_hist = Counter()
min_date = None; max_date = None
closed_present = 0
action_present = 0
modified_present = 0
valts_present = 0
lat_min = 90; lat_max = -90; lon_min = 180; lon_max = -180
zero_geo = 0
ttf_action_hours = []           # created -> action_taken
ttf_modify_hours = []           # created -> modified
WEEK = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
SEVERE = {"PARKING IN A MAIN ROAD","PARKING NEAR ROAD CROSSING",
          "PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS","DOUBLE PARKING",
          "PARKING ON FOOTPATH","PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC"}
severe_rows = 0
at_junction_rows = 0

with open(PATH, encoding="utf-8", errors="replace", newline="") as f:
    reader = csv.DictReader(f)
    cols = reader.fieldnames
    for r in reader:
        rows += 1
        for c in cols:
            if r.get(c) in MISSING:
                null_counts[c] += 1
        # violations
        raw = r.get("violation_type")
        toks = []
        if raw not in MISSING:
            try:
                toks = json.loads(raw)
            except Exception:
                toks = [t.strip().strip('"') for t in raw.strip("[]").split(",") if t.strip()]
        for t in toks:
            viol_tokens[t] += 1
        multi_viol[len(toks)] += 1
        if any(t in SEVERE for t in toks):
            severe_rows += 1
        # categ(cardinality)
        vt = r.get("vehicle_type");  veh_type[vt if vt not in MISSING else "(missing)"] += 1
        uvt = r.get("updated_vehicle_type")
        if uvt not in MISSING:
            upd_veh_type[uvt] += 1
            if vt not in MISSING and uvt != vt:
                veh_type_changed += 1
        val_status[r.get("validation_status") if r.get("validation_status") not in MISSING else "(missing)"] += 1
        ps = r.get("police_station");  station[ps if ps not in MISSING else "(missing)"] += 1
        jn = r.get("junction_name")
        junction[jn if jn not in MISSING else "(missing)"] += 1
        if jn not in MISSING and jn != "No Junction":
            at_junction_rows += 1
        if r.get("center_code") not in MISSING: center.add(r["center_code"])
        if r.get("device_id") not in MISSING: device.add(r["device_id"])
        vn = r.get("vehicle_number")
        if vn not in MISSING: veh_no[vn] += 1
        # temporal
        cdt = parse_dt(r.get("created_datetime"))
        if cdt:
            hour_hist[cdt.hour] += 1
            weekday_hist[cdt.weekday()] += 1
            month_hist[cdt.strftime("%Y-%m")] += 1
            if min_date is None or cdt < min_date: min_date = cdt
            if max_date is None or cdt > max_date: max_date = cdt
        if r.get("closed_datetime") not in MISSING: closed_present += 1
        adt = parse_dt(r.get("action_taken_timestamp"))
        if adt: action_present += 1
        if r.get("modified_datetime") not in MISSING: modified_present += 1
        if r.get("validation_timestamp") not in MISSING: valts_present += 1
        mdt = parse_dt(r.get("modified_datetime"))
        if cdt and adt and adt >= cdt:
            ttf_action_hours.append((adt - cdt).total_seconds()/3600)
        if cdt and mdt and mdt >= cdt:
            ttf_modify_hours.append((mdt - cdt).total_seconds()/3600)
        # geo
        try:
            la = float(r.get("latitude")); lo = float(r.get("longitude"))
            if la == 0 or lo == 0:
                zero_geo += 1
            else:
                lat_min=min(lat_min,la); lat_max=max(lat_max,la)
                lon_min=min(lon_min,lo); lon_max=max(lon_max,lo)
        except (TypeError, ValueError):
            zero_geo += 1

def show(title): print("\n" + "="*70 + "\n" + title + "\n" + "="*70)

print("TOTAL ROWS:", rows)
print("COLUMNS (", len(cols), "):", cols)

show("MISSING VALUES PER COLUMN (count | %)")
for c in cols:
    m = null_counts[c]
    print(f"  {c:28s} {m:8d}  {100*m/rows:6.2f}%")

show("TEMPORAL COVERAGE")
print("created_datetime range:", min_date, "->", max_date)
print("month distribution:")
for k in sorted(month_hist): print(f"   {k}: {month_hist[k]}")
print("\nhour-of-day distribution (0-23):")
for h in range(24):
    bar = "#" * int(40*hour_hist[h]/max(hour_hist.values()))
    print(f"   {h:02d}: {hour_hist[h]:7d} {bar}")
print("\nweekday distribution:")
for d in range(7):
    print(f"   {WEEK[d]}: {weekday_hist[d]}")

show("TICKET LIFECYCLE COMPLETENESS")
print(f"closed_datetime present:   {closed_present} ({100*closed_present/rows:.1f}%)")
print(f"action_taken present:      {action_present} ({100*action_present/rows:.1f}%)")
print(f"modified_datetime present: {modified_present} ({100*modified_present/rows:.1f}%)")
print(f"validation_ts present:     {valts_present} ({100*valts_present/rows:.1f}%)")
for label, arr in [("created->action (h)", sorted(ttf_action_hours)),
                   ("created->modified (h)", sorted(ttf_modify_hours))]:
    if arr:
        print(f"\n{label}: n={len(arr)} p10={pct(arr,.1):.2f} median={pct(arr,.5):.2f} "
              f"p90={pct(arr,.9):.2f} mean={sum(arr)/len(arr):.2f}")

show("GEOGRAPHY")
print(f"non-zero geo rows; bbox lat[{lat_min:.4f},{lat_max:.4f}] lon[{lon_min:.4f},{lon_max:.4f}]")
print(f"zero/invalid geo rows: {zero_geo} ({100*zero_geo/rows:.2f}%)")
print(f"distinct police_station: {len([k for k in station if k!='(missing)'])}")
print(f"distinct junction_name:  {len([k for k in junction if k!='(missing)'])}")
print(f"distinct center_code:    {len(center)}")
print(f"distinct device_id:      {len(device)}")
print(f"rows at a NAMED junction: {at_junction_rows} ({100*at_junction_rows/rows:.1f}%)")
print(f"rows tagged 'No Junction': {junction.get('No Junction',0)} ({100*junction.get('No Junction',0)/rows:.1f}%)")

show("VIOLATION TYPES (full dataset)")
total_tags = sum(viol_tokens.values())
for k,v in viol_tokens.most_common():
    print(f"   {v:8d}  {100*v/rows:5.1f}%  {k}")
print(f"\ntotal violation tags: {total_tags}; severe-type rows: {severe_rows} ({100*severe_rows/rows:.1f}%)")
print("tags-per-ticket distribution:", dict(sorted(multi_viol.items())))

show("VEHICLE TYPES (top 15)")
for k,v in veh_type.most_common(15):
    print(f"   {v:8d}  {k}")
print(f"updated_vehicle_type rows: {sum(upd_veh_type.values())}; "
      f"rows where type was corrected: {veh_type_changed}")

show("VALIDATION STATUS")
for k,v in val_status.most_common():
    print(f"   {v:8d}  {100*v/rows:5.1f}%  {k}")

show("TOP 20 POLICE STATIONS BY VOLUME")
for k,v in station.most_common(20):
    print(f"   {v:8d}  {k}")

show("TOP 20 JUNCTIONS BY VOLUME (excl. No Junction/missing)")
shown = 0
for k,v in junction.most_common():
    if k in ("No Junction","(missing)"): continue
    print(f"   {v:8d}  {k}"); shown += 1
    if shown >= 20: break

show("REPEAT OFFENDERS (full dataset)")
distinct_v = len(veh_no)
rep = [c for c in veh_no.values() if c > 1]
print(f"distinct vehicle_numbers: {distinct_v}")
print(f"vehicles with >1 violation: {len(rep)} ({100*len(rep)/distinct_v:.1f}% of vehicles)")
print(f"violations attributable to repeat offenders: {sum(rep)} ({100*sum(rep)/rows:.1f}% of all tickets)")
print(f"max violations by a single vehicle: {max(veh_no.values())}")
print("top 10 offender ticket counts:", sorted(veh_no.values(), reverse=True)[:10])
buckets = Counter()
for c in veh_no.values():
    if c == 1: buckets["1"] += 1
    elif c <= 3: buckets["2-3"] += 1
    elif c <= 5: buckets["4-5"] += 1
    elif c <= 10: buckets["6-10"] += 1
    else: buckets["11+"] += 1
print("offender frequency buckets:", dict(buckets))
print("\nDONE.")

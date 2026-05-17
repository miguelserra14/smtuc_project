import csv
from pathlib import Path

metrics_path = Path("outputs/overlap/line_metrics_db.csv")

with metrics_path.open("r", encoding="utf-8", newline="") as fh:
    reader = csv.DictReader(fh)
    rows = list(reader)

print(f"Total linhas no CSV: {len(rows)}")

# Verificar cálculos
total_spatial = sum(int(float(r.get('temporal_spatial_candidates_count', 0) or 0)) for r in rows)
total_temporal = sum(int(float(r.get('temporal_overlaps_count', 0) or 0)) for r in rows)
total_overlap_stops = sum(int(float(r.get('overlap_stops', 0) or 0)) for r in rows)
total_overlap_lines = len([r for r in rows if float(r.get('overlap_pct', 0) or 0) > 0])
total_temporal_lines = len({r.get('line') for r in rows if float(r.get('temporal_overlaps_count', 0) or 0) > 0})

print(f"Total spatial candidates: {total_spatial}")
print(f"Total temporal overlaps: {total_temporal}")
print(f"Total overlap stops: {total_overlap_stops}")
print(f"Overlap lines (pct > 0): {total_overlap_lines}")
print(f"Temporal overlap lines: {total_temporal_lines}")

if total_spatial > 0:
    pct = (total_temporal / total_spatial) * 100.0
    print(f"Temporal overlap %: {pct:.2f}%")

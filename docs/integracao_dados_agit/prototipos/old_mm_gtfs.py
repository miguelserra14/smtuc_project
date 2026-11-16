"""GTFS oficial antigo do Metro Mondego (export 2025-12-19): padrões de viagem e passagens (só leitura)."""
import io
import sys
import zipfile

import pandas as pd

with zipfile.ZipFile(sys.argv[1]) as zf:
    rd = lambda n: pd.read_csv(io.BytesIO(zf.read(n)), dtype=str)
    stops, trips, st, cal = rd("stops.txt"), rd("trips.txt"), rd("stop_times.txt"), rd("calendar.txt")
st["seq"] = st.stop_sequence.astype(int)
st = st.sort_values(["trip_id", "seq"]).merge(stops[["stop_id", "stop_name"]], on="stop_id")
g = st.groupby("trip_id").agg(first=("stop_name", "first"), last=("stop_name", "last"), n=("stop_name", "size"))
g = g.join(trips.set_index("trip_id")[["service_id", "direction_id"]])
print(cal.to_string())
print(g.groupby(["service_id", "direction_id", "first", "last", "n"]).size().to_string())
wd = st.merge(trips[["trip_id", "service_id"]], on="trip_id")
wd = wd[wd.service_id == "3"]
for name in ("Portagem", "Vale das Flores", "Portela"):
    x = wd[wd.stop_name == name]
    print(f"WD passagens em {name}: {len(x)}")
print("paragens:", "; ".join(stops.stop_name))

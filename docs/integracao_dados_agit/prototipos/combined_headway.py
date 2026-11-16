import io, sys, zipfile
import pandas as pd
zf = zipfile.ZipFile(sys.argv[1])
rd = lambda n: pd.read_csv(io.BytesIO(zf.read(n)), dtype=str)
stops, trips, st = rd("stops.txt"), rd("trips.txt"), rd("stop_times.txt")
st = st.merge(stops[["stop_id", "stop_name"]], on="stop_id").merge(trips[["trip_id", "service_id"]], on="trip_id")
st["seq"] = st.stop_sequence.astype(int)
first = st.sort_values("seq").groupby("trip_id").stop_name.first()
dep = st[(st.stop_name == "Portagem") & (st.trip_id.map(first) == "Portagem") & (st.service_id == "3")]
m = sorted(int(t[:2]) * 60 + int(t[3:5]) for t in dep.departure_time)
for a, b, pdf in ((7*60+30, 9*60+30, "5"), (9*60+38, 16*60, "10"), (16*60, 19*60, "5"), (20*60, 24*60, "15")):
    d = [y - x for x, y in zip(m, m[1:]) if a <= x < b]
    print(f"WD partidas de Portagem (urbano+suburbano) {a//60:02d}:{a%60:02d}-{b//60:02d}:{b%60:02d}: intervalo mediano {sorted(d)[len(d)//2]} min (PDF: {pdf} min)")

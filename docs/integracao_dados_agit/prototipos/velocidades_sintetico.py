"""Inspeção só-de-leitura: velocidades implícitas, dtypes de load_gtfs, BOM, cruzamento de nomes."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "src"))
from gtfs_processing.gtfs import load_gtfs  # noqa: E402


def hav(a, b, c, d):
    a, b, c, d = map(np.radians, (a, b, c, d))
    h = np.sin((c - a) / 2) ** 2 + np.cos(a) * np.cos(c) * np.sin((d - b) / 2) ** 2
    return 6371000 * 2 * np.arcsin(np.sqrt(h))


for ds in ("smtuc", "metrobus", "metrobus_fase2"):
    raw = (root / "data" / ds / "stops.txt").read_bytes()[:3]
    g = load_gtfs(dataset=ds)
    print(f"\n== {ds}: BOM={raw == b'\xef\xbb\xbf'} | dtypes stops: {dict(g.stops.dtypes.astype(str))}")
    print("   trips:", dict(g.trips.dtypes.astype(str)), "| stop_times.stop_id:", g.stop_times.stop_id.dtype)
    print("   shapes:", len(g.shapes), "calendar:", len(g.calendar), "calendar_dates:", len(g.calendar_dates))

g = load_gtfs(dataset="metrobus_fase2")
st = g.stop_times.merge(g.stops, on="stop_id")
for tid in ("WD_OUT_001", "EXT_WD_REP_0_001"):
    t = st[st.trip_id == tid].sort_values("stop_sequence")
    lat, lon, sec = t.stop_lat.to_numpy(float), t.stop_lon.to_numpy(float), t.arrival_seconds.to_numpy()
    d = hav(lat[:-1], lon[:-1], lat[1:], lon[1:])
    dt = np.diff(sec) / 60
    ids = t.stop_id.tolist()
    print(f"\n{tid}: segmento, dist_m, min, km/h")
    for i in range(len(d)):
        kmh = d[i] / 1000 / (dt[i] / 60) if dt[i] > 0 else float("inf")
        flag = "  <<<" if kmh > 80 or kmh < 8 else ""
        print(f"  {ids[i]}->{ids[i+1]}: {d[i]:7.0f} m  {dt[i]:4.0f} min  {kmh:6.1f}{flag}")

# Paragens Metro vs paragens SMTUC com o mesmo nome
s = load_gtfs(dataset="smtuc").stops
for name in ("Portagem", "Portela", "Coimbra-B", "Mercado", "Arnado", "Câmara", "Aeminium", "Loja do Cidad", "Praça"):
    m = g.stops[g.stops.stop_name.str.contains(name.split("-")[0], case=False)]
    b = s[s.stop_name.str.contains(name, case=False, na=False)]
    for r in m.itertuples():
        if b.empty:
            print(f"metro {r.stop_id} {r.stop_name}: sem paragem SMTUC c/ '{name}'")
            continue
        dist = hav(r.stop_lat, r.stop_lon, b.stop_lat.to_numpy(float), b.stop_lon.to_numpy(float))
        i = int(dist.argmin())
        print(f"metro {r.stop_id} {r.stop_name} -> SMTUC mais próxima c/ '{name}': {b.iloc[i].stop_name} ({dist[i]:.0f} m, {len(b)} candidatas)")

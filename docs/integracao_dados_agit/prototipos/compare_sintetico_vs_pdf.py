"""Compara, linha a linha do PDF suburbano, chegadas/partidas em Portagem com o feed (sÃ³ leitura)."""
import re
import sys
from pathlib import Path

import pandas as pd

root, sub_txt = Path(sys.argv[1]), Path(sys.argv[2])
lines = sub_txt.read_text(encoding="utf-8", errors="replace").split("\n")
# (nÂº de linha 1-based no txt, service, direction_id no feed)
PDF_ROWS = [(82, "WD", "0"), (112, "WD", "1"), (246, "SAT", "0"), (276, "SAT", "1"), (410, "SUN", "0"), (440, "SUN", "1")]


def norm(t):
    h, m = map(int, t.split(":"))
    if h < 4:
        h += 24
    return f"{h:02d}:{m:02d}"


tr = pd.read_csv(root / "data" / "metrobus" / "trips.txt", dtype=str)
st = pd.read_csv(root / "data" / "metrobus" / "stop_times.txt", dtype=str)
x = st.merge(tr, on="trip_id")
for ln, svc, dirn in PDF_ROWS:
    pdf = sorted(norm(t) for t in re.findall(r"\d{1,2}:\d{2}", lines[ln - 1]))
    col = "arrival_time" if dirn == "0" else "departure_time"
    feed = sorted(x[(x.service_id == svc) & (x.direction_id == dirn) & (x.stop_id == "PTG")][col].str[:5])
    only_pdf = sorted(set(pdf) - set(feed))
    only_feed = sorted(set(feed) - set(pdf))
    print(f"{svc} dir{dirn} Portagem: PDF={len(pdf)} feed={len(feed)} | sÃ³ PDF={only_pdf} | sÃ³ feed={only_feed}")


wd0 = x[(x.service_id == "WD") & (x.direction_id == "0") & (x.stop_id == "PTG")].copy()
dup = wd0[wd0.duplicated("arrival_time", keep=False)].sort_values("arrival_time")
print("\nWD dir0: viagens com a MESMA hora de chegada a Portagem:")
first = st.assign(seq=st.stop_sequence.astype(int)).sort_values("seq").groupby("trip_id").first()
for r in dup.itertuples():
    f = first.loc[r.trip_id]
    print(f"  {r.trip_id:14s} chega {r.arrival_time} | começa em {f.stop_id} {f.arrival_time}")

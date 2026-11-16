"""Pressuposto do cenário "antes": o GTFS oficial do Metro (export 2025-12-19) bate com os PDFs de 06/09/2026?

Compara passagens em Portagem (serviço suburbano, por dia e sentido) com o PDF suburbano, e
1ª/última passagem + intervalos do serviço urbano VDF<->Portagem com o PDF urbano. Só leitura.
"""
import io
import re
import sys
import zipfile

import pandas as pd

gtfs_zip, sub_txt, urb_txt = sys.argv[1], sys.argv[2], sys.argv[3]
with zipfile.ZipFile(gtfs_zip) as zf:
    rd = lambda n: pd.read_csv(io.BytesIO(zf.read(n)), dtype=str)
    stops, trips, st = rd("stops.txt"), rd("trips.txt"), rd("stop_times.txt")
st["seq"] = st.stop_sequence.astype(int)
st = st.merge(stops[["stop_id", "stop_name"]], on="stop_id").merge(trips[["trip_id", "service_id"]], on="trip_id")
ends = st.sort_values("seq").groupby("trip_id").stop_name.agg(["first", "last"])
st = st.merge(ends, left_on="trip_id", right_index=True)
st["urban"] = (st["first"] == "Vale das Flores") | (st["last"] == "Vale das Flores")


def hm(t):
    h, m = int(t[:2]), int(t[3:5])
    return f"{h:02d}:{m:02d}"


def norm(t):
    h, m = map(int, t.split(":"))
    if h < 4:
        h += 24
    return f"{h:02d}:{m:02d}"


# --- suburbano: linhas "Portagem" do PDF (numeração com split("\n"))
lines = open(sub_txt, encoding="utf-8", errors="replace").read().split("\n")
PDF_ROWS = [(82, "3", "to"), (112, "3", "from"), (246, "2", "to"), (276, "2", "from"), (410, "1", "to"), (440, "1", "from")]
names = {"3": "Dias úteis", "2": "Sábado", "1": "Domingo"}
print("SUBURBANO (passagens em Portagem, viagens não urbanas)")
for ln, svc, sense in PDF_ROWS:
    pdf = sorted(norm(t) for t in re.findall(r"\d{1,2}:\d{2}", lines[ln - 1]))
    sub = st[(st.service_id == svc) & (~st.urban) & (st.stop_name == "Portagem")]
    sub = sub[sub["last"] == "Portagem"] if sense == "to" else sub[sub["first"] == "Portagem"]
    col = "arrival_time" if sense == "to" else "departure_time"
    feed = sorted(hm(t) for t in sub[col])
    only_pdf, only_feed = sorted(set(pdf) - set(feed)), sorted(set(feed) - set(pdf))
    print(f"  {names[svc]:10s} {'-> Portagem' if sense == 'to' else 'Portagem ->'}: PDF {len(pdf)} | GTFS {len(feed)} | só PDF {only_pdf[:8]}{'...' if len(only_pdf) > 8 else ''} | só GTFS {only_feed[:8]}{'...' if len(only_feed) > 8 else ''}")

# --- urbano: PDF tem 1ª/última por tipo de dia na mesma linha (dias úteis, sábados, domingos)
ul = open(urb_txt, encoding="utf-8", errors="replace").read().split("\n")
row_to = next(l for l in ul if l.strip().startswith("Portagem") and "6:28" in l)
row_from = next(l for l in ul if l.strip().startswith("Portagem") and "6:10" in l)
print("\nURBANO VDF<->Portagem (PDF: tempos-chave por tipo de dia, na mesma linha)")
print("  PDF chegadas a Portagem :", re.findall(r"\d{1,2}:\d{2}", row_to))
print("  PDF partidas de Portagem:", re.findall(r"\d{1,2}:\d{2}", row_from))
for svc in ("3", "2", "1"):
    u = st[(st.service_id == svc) & st.urban & (st.stop_name == "Portagem")]
    to = sorted(hm(t) for t in u[u["last"] == "Portagem"].arrival_time)
    fr = sorted(hm(t) for t in u[u["first"] == "Portagem"].departure_time)
    def hw(ts, a, b):
        mins = [int(t[:2]) * 60 + int(t[3:]) for t in ts]
        d = [y - x for x, y in zip(mins, mins[1:]) if a * 60 <= x < b * 60]
        return sorted(d)[len(d) // 2] if d else None
    print(f"  GTFS {names[svc]:10s}: urbanas ->PTG {len(to)} (1ª {to[0] if to else '-'}, última {to[-1] if to else '-'}) | PTG-> {len(fr)} (1ª {fr[0] if fr else '-'}, última {fr[-1] if fr else '-'})"
          f" | intervalo mediano 8-9h {hw(to, 8, 9)} min, 11-15h {hw(to, 11, 15)} min, 17-19h {hw(to, 17, 19)} min, 21-23h {hw(to, 21, 23)} min")

# --- paragens técnicas
with zipfile.ZipFile(gtfs_zip) as zf:
    raw = pd.read_csv(io.BytesIO(zf.read("stop_times.txt")), dtype=str)
pcs = stops[stops.stop_name.str.match(r"^PC\d")].stop_id
x = raw[raw.stop_id.isin(pcs)]
print("\nPC1-PC8: ocorrências", len(x), "| pickup_type", x.pickup_type.value_counts().to_dict(), "| drop_off_type", x.drop_off_type.value_counts().to_dict())

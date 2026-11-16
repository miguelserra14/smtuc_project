"""Compara IDs/nomes de paragens e linhas do NeTEx SMTUC novo com data/smtuc atual (só leitura)."""
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

NS = "{http://www.netex.org.uk/netex}"
zpath, root = Path(sys.argv[1]), Path(sys.argv[2])


def keyval(el, key):
    for kv in el.iter(NS + "KeyValue"):
        if kv.findtext(NS + "Key") == key:
            return kv.findtext(NS + "Value")
    return None


ssp, lines = [], []
with zipfile.ZipFile(zpath) as zf, zf.open("netex.xml") as f:
    for _, el in ET.iterparse(f, events=("end",)):
        t = el.tag.rsplit("}", 1)[-1]
        if t == "ScheduledStopPoint":
            ssp.append({"stop_id": keyval(el, "gtfs:stop_id"), "name": el.findtext(NS + "Name"),
                        "code": el.findtext(NS + "PublicCode"),
                        "lat": float(el.findtext(f"{NS}Location/{NS}Latitude")),
                        "lon": float(el.findtext(f"{NS}Location/{NS}Longitude"))})
            el.clear()
        elif t == "Line":
            lines.append({"route_id": keyval(el, "gtfs:route_id"), "name": el.findtext(NS + "Name"),
                          "public": el.findtext(NS + "PublicCode"), "short": el.findtext(NS + "ShortName")})
            el.clear()
        elif t in ("ServiceJourney", "ServiceJourneyPattern", "Route"):
            el.clear()

new = pd.DataFrame(ssp)
old = pd.read_csv(root / "data" / "smtuc" / "stops.txt", dtype=str)
print("paragens: nova", len(new), "| antiga", len(old))
old = old.rename(columns={"stop_id": "old_stop_id", "stop_code": "stop_id"}); old["stop_code"] = old["stop_id"]; m = new.merge(old, on="stop_id", how="outer", indicator=True, suffixes=("_new", "_old"))
print("match por stop_id:", m["_merge"].value_counts().to_dict())
both = m[m["_merge"] == "both"].copy()
both["same_name"] = both["name"].str.strip().str.lower() == both["stop_name"].str.strip().str.lower()
a = np.radians(both[["lat", "lon"]].astype(float).to_numpy())
b = np.radians(both[["stop_lat", "stop_lon"]].astype(float).to_numpy())
h = np.sin((b[:, 0] - a[:, 0]) / 2) ** 2 + np.cos(a[:, 0]) * np.cos(b[:, 0]) * np.sin((b[:, 1] - a[:, 1]) / 2) ** 2
both["dist_m"] = 6371000 * 2 * np.arcsin(np.sqrt(h))
print("mesmo nome:", int(both.same_name.sum()), "de", len(both), "| deslocadas >20 m:", int((both.dist_m > 20).sum()), "| mediana desloc. m:", round(float(both.dist_m.median()), 1))
print("stop_code antigo == PublicCode novo:", int((both["code"] == both["stop_code"]).sum()))
print("exemplos nome diferente:\n", both.loc[~both.same_name, ["stop_id", "stop_name", "name", "dist_m"]].head(8).to_string())
for pat in ("Portagem", "Portela do Mondego", "Coimbra-B"):
    print(f"'{pat}' -> nova: {new[new.name.str.contains(pat, case=False)].name.unique().tolist()[:8]}")
    print(f"'{pat}' -> antiga: {old[old.stop_name.str.contains(pat, case=False)].stop_name.unique().tolist()[:8]}")

L = pd.DataFrame(lines)
old_r = pd.read_csv(root / "data" / "smtuc" / "routes.txt", dtype=str)
print("\nlinhas novas:", len(L), "| route_id novos únicos:", L.route_id.nunique(), "| PublicCode únicos:", L.short.nunique())
print(L.head(5).to_string())
print("route_short_name antigos únicos:", old_r.route_short_name.nunique())
print("códigos só na nova:", sorted(set(L.short.dropna()) - set(old_r.route_short_name))[:40])
print("códigos só na antiga:", sorted(set(old_r.route_short_name) - set(L.short.dropna()))[:40])


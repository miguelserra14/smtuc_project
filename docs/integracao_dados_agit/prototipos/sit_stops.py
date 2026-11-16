"""SIT: paragens perto da rede SMTUC/Metro e restrições de embarque/desembarque (só leitura)."""
import collections
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

NS = "{http://www.netex.org.uk/netex}"
zpath, root = Path(sys.argv[1]), Path(sys.argv[2])


def kv(el, key):
    for k in el.iter(NS + "KeyValue"):
        if k.findtext(NS + "Key") == key:
            return k.findtext(NS + "Value")


ssp, flags, sjp_count = {}, collections.Counter(), collections.Counter()
with zipfile.ZipFile(zpath) as zf, zf.open("netex.xml") as f:
    for _, el in ET.iterparse(f, events=("end",)):
        t = el.tag.rsplit("}", 1)[-1]
        if t == "ScheduledStopPoint":
            ssp[el.get("id")] = (kv(el, "gtfs:stop_id"), el.findtext(NS + "PublicCode"), el.findtext(NS + "Name"),
                                 float(el.findtext(f"{NS}Location/{NS}Latitude")), float(el.findtext(f"{NS}Location/{NS}Longitude")))
            el.clear()
        elif t == "StopPointInJourneyPattern":
            ref = el.find(NS + "ScheduledStopPointRef").get("ref")
            b, a = el.findtext(NS + "ForBoarding"), el.findtext(NS + "ForAlighting")
            flags[(ref, b, a)] += 1
        elif t == "ServiceJourneyPattern":
            el.clear()
        elif t == "ServiceJourney":
            el.clear()

df = pd.DataFrame([(k, *v) for k, v in ssp.items()], columns=["ssp", "stop_id", "code", "name", "lat", "lon"])
print("paragens SIT:", len(df), "| exemplos id/código:", df[["stop_id", "code", "name"]].head(4).values.tolist())
smtuc = pd.read_csv(root / "data" / "smtuc" / "stops.txt", dtype={"stop_code": str})


def mind(qlat, qlon, rlat, rlon):
    q = np.radians(np.c_[qlat, qlon])[:, None, :]
    r = np.radians(np.c_[rlat, rlon])[None, :, :]
    h = np.sin((r[..., 0] - q[..., 0]) / 2) ** 2 + np.cos(q[..., 0]) * np.cos(r[..., 0]) * np.sin((r[..., 1] - q[..., 1]) / 2) ** 2
    return (6371000 * 2 * np.arcsin(np.sqrt(h))).min(axis=1)


df["d_smtuc"] = mind(df.lat.values, df.lon.values, smtuc.stop_lat.values, smtuc.stop_lon.values)
print("SIT a <=50 m de uma paragem SMTUC:", int((df.d_smtuc <= 50).sum()), "| <=300 m:", int((df.d_smtuc <= 300).sum()))
print("SIT com stop_code igual a stop_code SMTUC:", int(df.code.isin(smtuc.stop_code).sum()))
# dentro da bbox do concelho de Coimbra (aprox. pela extensão das paragens SMTUC)
inbox = df[(df.lat.between(smtuc.stop_lat.min(), smtuc.stop_lat.max())) & (df.lon.between(smtuc.stop_lon.min(), smtuc.stop_lon.max()))]
print("SIT dentro da extensão da rede SMTUC:", len(inbox))
# restrições
fl = pd.DataFrame([(k[0], k[1], k[2], c) for k, c in flags.items()], columns=["ssp", "board", "alight", "n"])
fl = fl.merge(df[["ssp", "name", "d_smtuc"]], on="ssp")
urb = fl[fl.d_smtuc <= 300]
print("\nocorrências em padrões, paragens a <=300 m do SMTUC, por (embarque, desembarque):")
print(urb.groupby(["board", "alight"]).n.sum().to_string())
print("\nexemplos 'só desembarque' em Coimbra:", urb[(urb.board == "false") & (urb.alight == "true")].name.value_counts().head(10).to_dict())
print("exemplos 'só embarque' em Coimbra:", urb[(urb.board == "true") & (urb.alight == "false")].name.value_counts().head(10).to_dict())

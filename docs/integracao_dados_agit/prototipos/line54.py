"""Linhas 54 e 38 no NeTEx SMTUC novo: sequência de paragens e distância às paragens do Metro (só leitura)."""
import math
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = "{http://www.netex.org.uk/netex}"
METRO = {"Portagem": (40.207526, -8.430654), "Parque": (40.203753, -8.425116), "Portela": None}


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))


def kv(el, key):
    for k in el.iter(NS + "KeyValue"):
        if k.findtext(NS + "Key") == key:
            return k.findtext(NS + "Value")


ssp, lines, routes, pats = {}, {}, {}, {}
with zipfile.ZipFile(sys.argv[1]) as zf, zf.open("netex.xml") as f:
    for _, el in ET.iterparse(f, events=("end",)):
        t = el.tag.rsplit("}", 1)[-1]
        if t == "ScheduledStopPoint":
            ssp[el.get("id")] = (el.findtext(NS + "Name"), float(el.findtext(f"{NS}Location/{NS}Latitude")), float(el.findtext(f"{NS}Location/{NS}Longitude")), kv(el, "gtfs:stop_id"))
            el.clear()
        elif t == "Line":
            lines[el.get("id")] = (el.findtext(NS + "ShortName"), el.findtext(NS + "Name"), kv(el, "gtfs:route_id"))
            el.clear()
        elif t == "Route":
            routes[el.get("id")] = (el.find(NS + "LineRef").get("ref"), el.findtext(NS + "DirectionType"))
            el.clear()
        elif t == "ServiceJourneyPattern":
            seq = sorted((int(sp.get("order")), sp.find(NS + "ScheduledStopPointRef").get("ref")) for sp in el.iter(NS + "StopPointInJourneyPattern"))
            pats[el.get("id")] = (el.find(NS + "RouteRef").get("ref"), [s for _, s in seq])
            el.clear()
        elif t == "ServiceJourney":
            el.clear()

seen = set()
for pid, (rid, seq) in pats.items():
    lid, direction = routes[rid]
    short, name, gid = lines[lid]
    if short not in ("54", "38"):
        continue
    key = (short, gid, direction, tuple(seq))
    if key in seen:
        continue
    seen.add(key)
    names = [ssp[s][0] for s in seq]
    print(f"\n[{short}] route_id={gid} {name} | {direction} | {len(seq)} paragens")
    print("   ", " > ".join(names))
    for end in (seq[0], seq[-1]):
        n, la, lo, sid = ssp[end]
        d = {k: round(hav((la, lo), v)) for k, v in METRO.items() if v}
        print(f"    terminal {n} (stop_id {sid}) dist. metro: {d}")

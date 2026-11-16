"""Resumo de um NeTEx EPIP da AGIT (só leitura, streaming a partir do zip).

Constrói em memória tabelas mínimas equivalentes a GTFS (protótipo de conversor) e imprime:
linhas, calendários (DayType -> período + dias da semana), padrões (1ª/última paragem), contagem de
viagens por linha/calendário, presença de DayOffset, e passagens por paragem num dia escolhido.
"""
import collections
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

NS = "{http://www.netex.org.uk/netex}"
zpath = Path(sys.argv[1])
probe_day = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else None
probe_stops = sys.argv[3].split("|") if len(sys.argv) > 3 else []


def local(tag):
    return tag.rsplit("}", 1)[-1]


def keyval(el, key):
    for kv in el.iter(NS + "KeyValue"):
        if kv.findtext(NS + "Key") == key:
            return kv.findtext(NS + "Value")
    return None


lines, routes, patterns, stops_ssp, daytypes, periods, assignments = {}, {}, {}, {}, {}, {}, []
journeys = []  # (gtfs_trip_id, pattern_id, [daytype ids], first_dep, n_passing, has_dayoffset, passing list)
spijp_to_ssp = {}
dayoffset_seen = 0
tags_seen = collections.Counter()

with zipfile.ZipFile(zpath) as zf, zf.open("netex.xml") as f:
    for ev, el in ET.iterparse(f, events=("end",)):
        t = local(el.tag)
        if t in ("Line", "Route", "ServiceJourneyPattern", "ScheduledStopPoint", "DayType",
                 "UicOperatingPeriod", "DayTypeAssignment", "ServiceJourney", "StopPlace",
                 "Interchange", "ServiceJourneyInterchange", "HeadwayJourneyGroup", "FlexibleLine", "DeadRun"):
            tags_seen[t] += 1
        if t == "Line":
            lines[el.get("id")] = {
                "gtfs": keyval(el, "gtfs:route_id"), "name": el.findtext(NS + "Name"),
                "short": el.findtext(NS + "ShortName"), "public": el.findtext(NS + "PublicCode"),
                "colour": el.findtext(f"{NS}Presentation/{NS}Colour"),
            }
            el.clear()
        elif t == "Route":
            lr = el.find(NS + "LineRef")
            routes[el.get("id")] = {"line": lr.get("ref") if lr is not None else None,
                                    "dir": el.findtext(NS + "DirectionType")}
            el.clear()
        elif t == "ServiceJourneyPattern":
            rr = el.find(NS + "RouteRef")
            seq = []
            for sp in el.iter(NS + "StopPointInJourneyPattern"):
                ssp = sp.find(NS + "ScheduledStopPointRef").get("ref")
                spijp_to_ssp[sp.get("id")] = ssp
                seq.append((int(sp.get("order")), ssp))
            patterns[el.get("id")] = {"route": rr.get("ref") if rr is not None else None,
                                      "stops": [s for _, s in sorted(seq)]}
            el.clear()
        elif t == "ScheduledStopPoint":
            stops_ssp[el.get("id")] = {
                "gtfs": keyval(el, "gtfs:stop_id"), "name": el.findtext(NS + "Name"),
                "code": el.findtext(NS + "PublicCode"),
                "lat": float(el.findtext(f"{NS}Location/{NS}Latitude") or "nan"),
                "lon": float(el.findtext(f"{NS}Location/{NS}Longitude") or "nan"),
            }
            el.clear()
        elif t == "DayType":
            daytypes[el.get("id")] = {"gtfs": keyval(el, "gtfs:service_id"), "name": el.findtext(NS + "Name")}
        elif t == "UicOperatingPeriod":
            periods[el.get("id")] = {"from": el.findtext(NS + "FromDate")[:10], "to": el.findtext(NS + "ToDate")[:10],
                                     "bits": el.findtext(NS + "ValidDayBits") or ""}
        elif t == "DayTypeAssignment":
            op = el.find(NS + "OperatingPeriodRef")
            dt = el.find(NS + "DayTypeRef")
            d = el.findtext(NS + "Date")
            assignments.append({"period": op.get("ref") if op is not None else None, "date": d,
                                "daytype": dt.get("ref"), "avail": el.findtext(NS + "isAvailable")})
        elif t == "ServiceJourney":
            pref = el.find(NS + "ServiceJourneyPatternRef")
            dts = [d.get("ref") for d in el.iter(NS + "DayTypeRef")]
            pts = []
            for tp in el.iter(NS + "TimetabledPassingTime"):
                off = tp.findtext(NS + "DepartureDayOffset") or tp.findtext(NS + "ArrivalDayOffset") or tp.findtext(NS + "DayOffset")
                if off:
                    dayoffset_seen += 1
                dep = tp.findtext(NS + "DepartureTime") or tp.findtext(NS + "ArrivalTime")
                h, m, s = map(int, dep.split(":"))
                pts.append((tp.find(NS + "StopPointInJourneyPatternRef").get("ref"), h * 3600 + m * 60 + s + int(off or 0) * 86400))
            journeys.append({"trip": keyval(el, "gtfs:trip_id"), "pattern": pref.get("ref") if pref is not None else None,
                             "daytypes": dts, "pts": pts, "name": el.findtext(NS + "Name")})
            el.clear()

print("elementos:", dict(tags_seen), "| TimetabledPassingTime c/ DayOffset:", dayoffset_seen)


def nm(ssp):
    s = stops_ssp.get(ssp, {})
    return s.get("name", ssp)


# Calendários
dt_periods = collections.defaultdict(list)
for a in assignments:
    dt_periods[a["daytype"]].append(a)
print("\n== Calendários (DayType)")
for dt_id, dt in daytypes.items():
    for a in dt_periods.get(dt_id, []):
        p = periods.get(a["period"])
        if p:
            start = date.fromisoformat(p["from"])
            wd = collections.Counter((start + timedelta(days=i)).strftime("%a") for i, b in enumerate(p["bits"]) if b == "1")
            n_days = p["bits"].count("1")
            print(f"  service {dt['gtfs']!s:>4} ({dt['name']}): {p['from']}..{p['to']} | {n_days} dias ativos | dias semana {dict(wd)} | avail={a['avail']}")
        else:
            print(f"  service {dt['gtfs']}: data avulsa {a['date']} avail={a['avail']}")


def active_daytypes(d):
    out = set()
    for a in assignments:
        p = periods.get(a["period"])
        if p:
            i = (d - date.fromisoformat(p["from"])).days
            if 0 <= i < len(p["bits"]) and p["bits"][i] == "1":
                out.add(a["daytype"])
        elif a["date"] and a["date"][:10] == d.isoformat() and a["avail"] != "false":
            out.add(a["daytype"])
    return out


# Linhas e padrões
by_line = collections.defaultdict(list)
for j in journeys:
    pat = patterns.get(j["pattern"], {})
    route = routes.get(pat.get("route"), {})
    by_line[route.get("line")].append((j, pat, route))
print(f"\n== Linhas ({len(lines)}) / viagens ({len(journeys)})")
for lid, items in sorted(by_line.items(), key=lambda kv: -len(kv[1]))[:40]:
    ln = lines.get(lid, {})
    ends = collections.Counter((r.get("dir"), nm(p["stops"][0]), nm(p["stops"][-1]), len(p["stops"])) for _, p, r in items)
    svc = collections.Counter(daytypes.get(d, {}).get("gtfs") for j, _, _ in items for d in j["daytypes"])
    print(f"  [{ln.get('gtfs')}] {ln.get('name')!s} / {ln.get('short')!s}: {len(items)} viagens | por service {dict(svc)}")
    for (d, a, b, n), c in ends.most_common(6):
        print(f"       {d:8s} {a} -> {b} ({n} paragens): {c}")

# Paragens
print(f"\n== Paragens ({len(stops_ssp)}):", "; ".join(f"{s['gtfs']}:{s['name']}" for s in list(stops_ssp.values())[:60]))

# Passagens num dia
if probe_day:
    act = active_daytypes(probe_day)
    print(f"\n== {probe_day} ({probe_day.strftime('%A')}): DayTypes ativos {[daytypes[a]['gtfs'] for a in act]}")
    todays = [j for j in journeys if set(j["daytypes"]) & act]
    print(f"   viagens nesse dia: {len(todays)}")
    for target in probe_stops:
        cnt = collections.Counter()
        times = collections.defaultdict(list)
        for j in todays:
            pat = patterns[j["pattern"]]
            last = nm(pat["stops"][-1])
            for spij, sec in j["pts"]:
                if nm(spijp_to_ssp[spij]).lower().startswith(target.lower()):
                    cnt[(nm(spijp_to_ssp[spij]), "-> " + last)] += 1
                    times[(nm(spijp_to_ssp[spij]), "-> " + last)].append(sec)
        for k, v in cnt.most_common():
            ts = sorted(times[k])
            hw = [b - a for a, b in zip(ts, ts[1:])]
            peak = [b - a for a, b in zip(ts, ts[1:]) if 7 * 3600 <= a < 9 * 3600]
            print(f"   {k[0]} {k[1]}: {v} passagens | 1ª {ts[0]//3600:02d}:{ts[0]%3600//60:02d} última {ts[-1]//3600:02d}:{ts[-1]%3600//60:02d}"
                  f" | intervalo mediano {sorted(hw)[len(hw)//2]/60 if hw else float('nan'):.1f} min | ponta 7-9h mediano {sorted(peak)[len(peak)//2]/60 if peak else float('nan'):.1f} min")

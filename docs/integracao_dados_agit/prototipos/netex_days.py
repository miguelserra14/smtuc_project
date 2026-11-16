"""Lista as datas ativas de cada DayType (UicOperatingPeriod.ValidDayBits) de um NeTEx (só leitura)."""
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta

NS = "{http://www.netex.org.uk/netex}"
periods, assigns, names = {}, [], {}
with zipfile.ZipFile(sys.argv[1]) as zf, zf.open("netex.xml") as f:
    for _, el in ET.iterparse(f, events=("end",)):
        t = el.tag.rsplit("}", 1)[-1]
        if t == "UicOperatingPeriod":
            periods[el.get("id")] = (date.fromisoformat(el.findtext(NS + "FromDate")[:10]), el.findtext(NS + "ValidDayBits"))
        elif t == "DayType":
            names[el.get("id")] = el.findtext(NS + "Name")
        elif t == "DayTypeAssignment":
            assigns.append((el.find(NS + "OperatingPeriodRef").get("ref"), el.find(NS + "DayTypeRef").get("ref")))
        elif t in ("ServiceJourney", "ServiceJourneyPattern", "Route", "ScheduledStopPoint", "StopPlace"):
            el.clear()
for pref, dref in assigns:
    start, bits = periods[pref]
    days = [start + timedelta(days=i) for i, b in enumerate(bits) if b == "1"]
    gaps = []
    if len(days) > 1:
        full = {start + timedelta(days=i) for i in range((days[-1] - start).days + 1)}
        same_wd = [d for d in sorted(full) if d.weekday() in {x.weekday() for x in days} and d not in days]
        gaps = same_wd
    print(f"{names[dref]}: {len(days)} dias, {days[0]}..{days[-1]}")
    if len(days) <= 12:
        print("   datas:", [d.isoformat() for d in days])
    if gaps:
        print("   mesmos dias-da-semana EXCLUÍDOS:", [d.isoformat() for d in gaps][:20])

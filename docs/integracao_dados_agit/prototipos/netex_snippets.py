"""Mostra o 1º exemplar de cada elemento NeTEx relevante + metadata.jsonld (só leitura, a partir do zip)."""
import re
import sys
import zipfile
from pathlib import Path

zpath = Path(sys.argv[1])
max_chars = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
with zipfile.ZipFile(zpath) as zf:
    print("=== metadata.jsonld ===")
    print(zf.read("metadata.jsonld").decode("utf-8", errors="replace")[:4600])
    with zf.open("netex.xml") as f:
        head = f.read(25_000_000).decode("utf-8", errors="replace")

print("\n=== início do XML ===")
print(head[:1200])
for tag in ("Operator", "Line", "Route", "ServiceJourneyPattern", "DayType", "UicOperatingPeriod", "DayTypeAssignment",
            "StopPlace", "ScheduledStopPoint", "PassengerStopAssignment", "ServiceJourney"):
    m = re.search(rf"<{tag}[\s>].*?</{tag}>", head, flags=re.S)
    print(f"\n=== <{tag}> ===")
    print(m.group(0)[:max_chars] if m else "(não encontrado nos primeiros 25 MB)")

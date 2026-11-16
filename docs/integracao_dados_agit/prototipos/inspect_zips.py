"""Lista o conteúdo dos zips AGIT (só leitura, sem extrair para disco) e resume os XML NeTEx."""
import collections
import io
import re
import sys
import zipfile
from pathlib import Path

raw = Path(sys.argv[1])


def summarize_xml(name, data, max_tags=60):
    text = data[:400_000].decode("utf-8", errors="replace")
    root_tag = re.search(r"<([A-Za-z:]+)[\s>]", text[text.find("<", 1) if text.startswith("<?") else 0:])
    print(f"    root/primeiro elemento: {root_tag.group(1) if root_tag else '?'}")
    for attr in ("version", "ProfileVersion"):
        m = re.search(rf'{attr}="([^"]+)"', text)
        if m:
            print(f"    {attr}={m.group(1)}")
    # contagem de tags no ficheiro inteiro
    full = data.decode("utf-8", errors="replace")
    tags = collections.Counter(re.findall(r"<([A-Za-z][\w:]*)[\s>/]", full))
    interesting = [t for t, _ in tags.most_common() if t.endswith(("Frame", "Journey", "Pattern", "Point", "Place", "Line", "Route", "Calendar", "DayType", "Assignment", "Period", "Operator", "Link", "Interchange", "Version"))]
    print("    tags principais:", {t: tags[t] for t in interesting[:max_tags]})
    for t in ("ValidBetween", "FromDate", "ToDate"):
        vals = re.findall(rf"<{t}>([^<]+)</{t}>", full)
        if vals:
            print(f"    {t}: {sorted(set(vals))[:6]}")


for z in sorted(raw.glob("*.zip")) + sorted(raw.glob("*.kmz")):
    print(f"\n===== {z.name}")
    with zipfile.ZipFile(z) as zf:
        for info in zf.infolist():
            print(f"  {info.filename}  {info.file_size} B")
        for info in zf.infolist():
            data = zf.read(info.filename)
            if info.filename.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(data)) as inner:
                    for ii in inner.infolist():
                        print(f"    [interno] {ii.filename}  {ii.file_size} B")
                        if ii.filename.lower().endswith(".xml"):
                            summarize_xml(ii.filename, inner.read(ii.filename))
            elif info.filename.lower().endswith(".xml"):
                print(f"  -- {info.filename}")
                summarize_xml(info.filename, data)
            elif info.filename.lower().endswith(".txt"):
                lines = data.decode("utf-8-sig", errors="replace").splitlines()
                if not lines:
                    print(f"  -- {info.filename}: vazio")
                    continue
                print(f"  -- {info.filename}: {len(lines) - 1} linhas | {lines[0]}")
                for ln in lines[1:4]:
                    print(f"       {ln}")
            elif info.filename.lower().endswith(".kml"):
                text = data.decode("utf-8", errors="replace")
                names = re.findall(r"<name>([^<]+)</name>", text)
                print(f"  -- {info.filename}: {len(names)} <name>, Placemarks={text.count('<Placemark')}, LineString={text.count('<LineString')}, Point={text.count('<Point')}")
                print("     nomes:", names[:40])

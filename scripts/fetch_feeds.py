"""Descarrega e congela os dados oficiais (AGIT, dados.gov.pt, Município de Coimbra) em data/raw/ (D0.3).

    python scripts/fetch_feeds.py --dry-run          # o que mudou na origem, sem descarregar
    python scripts/fetch_feeds.py                    # descarrega o que for novo (grupo base)
    python scripts/fetch_feeds.py --grupos base,sit  # inclui o SIT (D3)
    python scripts/fetch_feeds.py listar             # fontes configuradas
    python scripts/fetch_feeds.py registar FICH --fonte manual/metro-mondego-pdf --versao 2026-09-06 [--mover]

NUNCA é chamado pelo regenerate nem pelos testes (a apresentação tem de funcionar offline).

data/raw/ é IMUTÁVEL: data/raw/<fonte>/<versão>/<ficheiro original>, um ficheiro nunca é
substituído (fica só de leitura) e uma publicação nova vai para uma pasta nova. Tudo o que entra
fica registado em data/raw/MANIFEST.csv (só se acrescentam linhas).

Quatro verificações, por esta ordem (uma falha = nada é gravado, exit 1):
  1. transporte  o ficheiro chegou inteiro: sha1 + tamanho do catálogo dados.gov.pt, ou sha256 do
                 /validation da API AGIT (zip, netex.xml e metadata.jsonld); zip íntegro (testzip)
  2. identidade  é o conjunto certo: dcterms:identifier do metadata.jsonld (NeTEx) ou nome do
                 operador em agency/feed_info (GTFS); regista o período de validade
  3. conteúdo    é novo ou repetido? A AGIT regenera os ficheiros sem mudar os dados (só muda
                 <PublicationTimestamp>), por isso compara-se o sha256 do conteúdo SEM essa linha
                 (NeTEx) ou dos .txt normalizados (GTFS). Repetido -> linha "igual" no manifest,
                 sem nova cópia. Na API, o source.sha256 (GTFS de origem) igual dispensa o download.
  4. semântica   o ficheiro tem o que a AGIT diz que tem: contagens de elementos do netex.xml ==
                 counts.netex do /validation (paragens, linhas, viagens, horários...)

Descarregar é seguro de repetir: o que já está no manifest não é descarregado de novo.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
USER_AGENT = "smtuc-analise/0.1"  # genérico: sem dados pessoais
CATALOG_API = "https://dados.gov.pt/api/1/datasets/{slug}/"
AGIT_API = "https://api.planner.agit.pt/v1/datasets/{dataset}/distributions/netex"

MANIFEST_COLUMNS = [
    "registado_em", "fonte", "versao", "estado", "ficheiro", "bytes", "sha256", "sha1", "conteudo_sha256",
    "origem_sha256", "igual_a", "identificador", "modificado", "valido_de", "valido_ate", "contagens",
    "verificacoes", "url",
]

# counts.netex do /validation da AGIT -> elemento NeTEx (calibrado no Metro a 2026-11-16: os 11 batem)
NETEX_COUNT_TAGS = {
    "operators": "Operator", "stopPlaces": "StopPlace", "quays": "Quay", "scheduledStopPoints": "ScheduledStopPoint",
    "lines": "Line", "routeVariants": "Route", "journeyPatterns": "ServiceJourneyPattern",
    "serviceJourneys": "ServiceJourney", "passingTimes": "TimetabledPassingTime",
    "serviceCalendars": "ServiceCalendar", "dayTypes": "DayType",
}
GTFS_REQUIRED = ("agency.txt", "routes.txt", "trips.txt", "stop_times.txt", "stops.txt")
GTFS_CONTENT_FILES = ("agency.txt", "routes.txt", "trips.txt", "stop_times.txt", "stops.txt", "calendar.txt",
                      "calendar_dates.txt", "shapes.txt", "feed_info.txt")
_TIMESTAMP_RE = re.compile(rb"<PublicationTimestamp>.*?</PublicationTimestamp>")


class FetchError(RuntimeError):
    """Uma das verificações falhou - nada foi gravado para esta fonte."""


@dataclass(frozen=True)
class Source:
    id: str              # pasta em data/raw/
    kind: str            # "agit" (API AGIT + /validation) | "agit_validacao" (só o /validation) | "catalogo"
    dataset: str         # id na API AGIT ou slug do dados.gov.pt
    fmt: str             # "netex" | "gtfs" | "outro"
    filename: str = ""   # catálogo: nome (ou padrão fnmatch) do recurso
    identifier: str = ""  # NeTEx: dcterms:identifier esperado
    operator: str = ""   # GTFS: texto que tem de aparecer em agency_name/feed_publisher_name
    agit_origin: str = ""  # GTFS: dataset AGIT cujo source.sha256 deve ser este ficheiro (prova de origem)
    versionar: bool = True
    grupo: str = "base"
    descricao: str = ""
    mesmo_conteudo: str = ""  # outra fonte com os mesmos dados (espelho <-> API): conteúdo repetido não se guarda 2x

    def content_sources(self) -> set[str]:
        return {self.id, self.mesmo_conteudo} - {""}


SOURCES: tuple[Source, ...] = (
    Source("agit/metro-mondego-netex", "agit", "metro-mondego", "netex", identifier="urn:agit:Dataset:metro-mondego",
           descricao="Metro fase 2 (desde 10/09/2026) - NeTEx oficial, a converter na D2"),
    Source("dados-gov/metro-mondego-netex", "catalogo", "metro-mondego-netex", "netex", "metro-mondego-netex.zip",
           identifier="urn:agit:Dataset:metro-mondego", mesmo_conteudo="agit/metro-mondego-netex",
           descricao="espelho do anterior no dados.gov.pt (outra publicação)"),
    Source("dados-gov/metro-mondego-gtfs", "catalogo", "metro-mondego", "gtfs", "*-export-gtfs.zip", operator="Metro",
           descricao="Metro fase 1 (até 09/09/2026) - GTFS oficial de 2025-12-19"),
    Source("dados-gov/metro-mondego-kmz", "catalogo", "metro-mondego", "outro", "rede-metrobus.kmz",
           descricao="rede do Metro (KMZ, Linha do Hospital - D4)"),
    Source("municipio-coimbra/smtuc-gtfs", "catalogo", "gtfs-estaticos-servicos-municipalizados-de-transportes-urbanos-de-coimbra",
           "gtfs", "smtuc-static-gtfs-*.zip", operator="Coimbra", agit_origin="smtuc", versionar=False,
           descricao="SMTUC atual - GTFS do Município (licença não especificada: não versionado)"),
    Source("agit/smtuc-netex-validacao", "agit_validacao", "smtuc", "outro",
           descricao="só o /validation do NeTEx SMTUC (prova de origem + contagens; o zip de 10 MB não é preciso)"),
    Source("agit/sit-netex", "agit", "sit", "netex", identifier="urn:agit:Dataset:sit", grupo="sit",
           descricao="SIT - NeTEx oficial (D3)"),
    Source("dados-gov/sit-percursos-gpkg", "catalogo", "sistema-intermunicipal-de-transportes", "outro",
           "gtfs-percursos-paragens.gpkg", grupo="sit", descricao="percursos/paragens do SIT para os mapas (D3)"),
)


# --------------------------------------------------------------------------- rede


class Http:
    """Acesso à rede (substituível nos testes)."""

    def __init__(self, timeout: float = 120.0) -> None:
        self.timeout = timeout

    def _open(self, url: str):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        return urllib.request.urlopen(req, timeout=self.timeout)

    def get_json(self, url: str) -> dict:
        with self._open(url) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def download(self, url: str, dest: Path) -> None:
        with self._open(url) as resp, open(dest, "wb") as out:
            shutil.copyfileobj(resp, out, length=1 << 20)


# --------------------------------------------------------------------------- utilitários


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hashes(path: Path) -> tuple[str, str, int]:
    sha256, sha1, size = hashlib.sha256(), hashlib.sha1(), 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sha256.update(chunk)
            sha1.update(chunk)
            size += len(chunk)
    return sha256.hexdigest(), sha1.hexdigest(), size


def _member_sha256(zf: zipfile.ZipFile, name: str) -> str:
    h = hashlib.sha256()
    with zf.open(name) as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(raw_dir: Path) -> list[dict[str, str]]:
    path = raw_dir / "MANIFEST.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def append_manifest(raw_dir: Path, row: dict[str, object]) -> None:
    """Acrescenta uma linha (escrita atómica: as linhas anteriores nunca se perdem a meio)."""
    rows = read_manifest(raw_dir)
    rows.append({k: "" if row.get(k) is None else str(row.get(k)) for k in MANIFEST_COLUMNS})
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / "MANIFEST.csv"
    tmp = path.with_name(f".MANIFEST.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _store(part: Path, final: Path) -> None:
    if final.exists():
        raise FetchError(f"{final} já existe - data/raw é imutável (versão repetida com outro conteúdo?)")
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(part, final)
    os.chmod(final, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def _validation_bytes(validation: dict) -> bytes:
    """Sempre os mesmos bytes (LF, UTF-8) em qualquer sistema - write_text no Windows punha CRLF."""
    return json.dumps(validation, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8") + b"
"


def _version_from_catalog_url(url: str) -> str:
    """dados.gov.pt/s/resources/<slug>/<AAAAMMDD-HHMMSS-hash>/<ficheiro> -> AAAAMMDD-HHMMSS-hash."""
    parts = url.rstrip("/").split("/")
    if len(parts) >= 2 and re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]+", parts[-2]):
        return parts[-2]
    raise FetchError(f"URL do catálogo sem versão no caminho: {url}")


# --------------------------------------------------------------------------- inspeção dos ficheiros


def inspect_netex(path: Path, expected_identifier: str, validation: dict | None) -> dict[str, str]:
    """Verificações 1 (membros vs /validation), 2 (identidade), 3 (conteúdo) e 4 (contagens)."""
    checks: list[str] = []
    with zipfile.ZipFile(path) as zf:
        if zf.testzip() is not None:
            raise FetchError("zip corrompido")
        names = zf.namelist()
        xml_name = next((n for n in names if n.endswith(".xml")), None)
        if xml_name is None or "metadata.jsonld" not in names:
            raise FetchError(f"zip NeTEx sem netex.xml/metadata.jsonld: {names}")
        meta = json.loads(zf.read("metadata.jsonld").decode("utf-8"))
        identifier = str(meta.get("dcterms:identifier", ""))
        if identifier != expected_identifier:
            raise FetchError(f"identidade: dcterms:identifier={identifier!r}, esperado {expected_identifier!r}")
        checks.append("identidade")
        if validation:
            art = validation["artifact"]
            if _member_sha256(zf, xml_name) != art["xmlSha256"]:
                raise FetchError("transporte: sha256 do netex.xml diferente do /validation")
            if _member_sha256(zf, "metadata.jsonld") != art.get("metadata", {}).get("sha256"):
                raise FetchError("transporte: sha256 do metadata.jsonld diferente do /validation")
            checks.append("membros=validacao")

        content = hashlib.sha256()
        with zf.open(xml_name) as fh:
            for line in fh:
                content.update(_TIMESTAMP_RE.sub(b"", line))

        counts: Counter[str] = Counter()
        wanted = set(NETEX_COUNT_TAGS.values())
        with zf.open(xml_name) as fh:
            for _, el in ET.iterparse(fh, events=("end",)):
                tag = el.tag.rsplit("}", 1)[-1]
                if tag in wanted:
                    counts[tag] += 1
                el.clear()

    found = {key: counts.get(tag, 0) for key, tag in NETEX_COUNT_TAGS.items()}
    if validation:
        official = validation["counts"]["netex"]
        wrong = {k: (found.get(k), v) for k, v in official.items() if k in NETEX_COUNT_TAGS and found.get(k) != v}
        if wrong:
            raise FetchError(f"semântica: contagens diferentes do /validation (lido, oficial): {wrong}")
        checks.append("contagens=validacao")
    temporal = meta.get("dcterms:temporal") or {}
    return {
        "identificador": identifier,
        "modificado": str((meta.get("dcterms:modified") or {}).get("@value", "")),
        "valido_de": str((temporal.get("dcat:startDate") or {}).get("@value", "")),
        "valido_ate": str((temporal.get("dcat:endDate") or {}).get("@value", "")),
        "conteudo_sha256": content.hexdigest(),
        "contagens": json.dumps(found, sort_keys=True),
        "_checks": ";".join(checks),
    }


def _csv_rows(zf: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    with zf.open(name) as fh:
        return list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")))


def _count_lines(zf: zipfile.ZipFile, name: str) -> int:
    with zf.open(name) as fh:
        return max(sum(1 for _ in fh) - 1, 0)


def inspect_gtfs(path: Path, expected_operator: str) -> dict[str, str]:
    with zipfile.ZipFile(path) as zf:
        if zf.testzip() is not None:
            raise FetchError("zip corrompido")
        names = {n.rsplit("/", 1)[-1]: n for n in zf.namelist()}
        missing = [f for f in GTFS_REQUIRED if f not in names]
        if missing:
            raise FetchError(f"GTFS sem ficheiros obrigatórios: {missing}")
        agency = _csv_rows(zf, names["agency.txt"])
        info = _csv_rows(zf, names["feed_info.txt"])[0] if "feed_info.txt" in names else {}
        who = " | ".join([*(a.get("agency_name", "") for a in agency), info.get("feed_publisher_name", "")])
        if expected_operator.lower() not in who.lower():
            raise FetchError(f"identidade: operador {who!r} não contém {expected_operator!r}")
        start, end = info.get("feed_start_date", ""), info.get("feed_end_date", "")
        if not (start and end) and "calendar.txt" in names:
            cal = _csv_rows(zf, names["calendar.txt"])
            start = min((r["start_date"] for r in cal), default="")
            end = max((r["end_date"] for r in cal), default="")
        content = hashlib.sha256()
        for f in GTFS_CONTENT_FILES:
            content.update(f.encode())
            content.update(zf.read(names[f]).replace(b"\r\n", b"\n") if f in names else b"<ausente>")
        counts = {f.removesuffix(".txt"): _count_lines(zf, names[f]) for f in ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")}
    return {
        "identificador": info.get("feed_version", "") or who,
        "modificado": "",
        "valido_de": start,
        "valido_ate": end,
        "conteudo_sha256": content.hexdigest(),
        "contagens": json.dumps(counts, sort_keys=True),
        "_checks": "identidade",
    }


def inspect_other(path: Path) -> dict[str, str]:
    if path.suffix.lower() in (".zip", ".kmz"):
        with zipfile.ZipFile(path) as zf:
            if zf.testzip() is not None:
                raise FetchError("zip corrompido")
    elif path.suffix.lower() == ".gpkg":
        with open(path, "rb") as fh:
            if fh.read(16) != b"SQLite format 3\x00":
                raise FetchError("GeoPackage inválido (não é SQLite)")
    return {"conteudo_sha256": _hashes(path)[0], "_checks": "formato"}


# --------------------------------------------------------------------------- uma fonte


@dataclass
class Result:
    source: str
    status: str   # novo | igual | sem_alteracoes | seria_descarregado | falhou
    detail: str = ""


def _known(manifest: list[dict[str, str]], sources: str | set[str], column: str, value: str) -> dict[str, str] | None:
    if not value:
        return None
    sources = {sources} if isinstance(sources, str) else sources
    for row in manifest:
        if row["fonte"] in sources and row.get(column) == value and row["estado"] in ("novo", "igual", "manual"):
            return row
    return None


def _stored_at(row: dict[str, str]) -> str:
    """Onde está o ficheiro de uma linha: "fonte/versão" da linha "novo" (as "igual" apontam para ela)."""
    return row.get("igual_a") or f"{row['fonte']}/{row['versao']}"


def _remote(src: Source, http: Http) -> dict[str, object]:
    if src.kind == "catalogo":
        ds = http.get_json(CATALOG_API.format(slug=src.dataset))
        matches = [r for r in ds.get("resources", [])
                   if fnmatch.fnmatch(r.get("title", ""), src.filename) or fnmatch.fnmatch(r.get("url", "").rsplit("/", 1)[-1], src.filename)]
        if len(matches) != 1:
            raise FetchError(f"catálogo {src.dataset}: {len(matches)} recursos para {src.filename!r} (esperado 1)")
        r = matches[0]
        checksum = r.get("checksum") or {}
        if checksum.get("type") != "sha1" or not checksum.get("value") or not r.get("filesize"):
            raise FetchError(f"catálogo {src.dataset}: recurso sem sha1/tamanho - não é verificável")
        return {"url": r["url"], "sha1": checksum["value"], "bytes": int(r["filesize"]),
                "version": _version_from_catalog_url(r["url"]), "filename": r["url"].rsplit("/", 1)[-1]}
    validation = http.get_json(f"{AGIT_API.format(dataset=src.dataset)}/validation")
    if validation.get("status") != "valid":
        raise FetchError(f"AGIT {src.dataset}: /validation com estado {validation.get('status')!r}")
    art = validation["artifact"]
    stamp = re.sub(r"[^0-9T]", "", art["generatedAt"])[:15].replace("T", "-")
    return {"url": f"{AGIT_API.format(dataset=src.dataset)}/download", "sha256": art["sha256"],
            "origin": validation["source"]["sha256"], "release": validation["source"]["releaseId"],
            "version": f"{stamp}-{art['sha256'][:8]}", "filename": f"{src.dataset}-netex.zip", "validation": validation}


def process_source(src: Source, http: Http, raw_dir: Path, dry_run: bool = False) -> Result:
    manifest = read_manifest(raw_dir)
    remote = _remote(src, http)
    base = {"fonte": src.id, "versao": remote["version"], "url": remote["url"]}

    if src.kind == "catalogo":
        if _known(manifest, src.id, "sha1", str(remote["sha1"])):
            return Result(src.id, "sem_alteracoes", f"sha1 {str(remote['sha1'])[:10]} já no manifest")
    else:
        if _known(manifest, src.id, "sha256", str(remote["sha256"])) or (
            src.kind == "agit_validacao" and _known(manifest, src.id, "origem_sha256", str(remote["origin"]))
        ):
            return Result(src.id, "sem_alteracoes", f"release {remote['release']} já no manifest")
        same_origin = _known(manifest, src.id, "origem_sha256", str(remote["origin"]))
        if same_origin and dry_run:
            return Result(src.id, "igual", f"mesma origem que {_stored_at(same_origin)} (seria registado sem download)")
        if same_origin:
            # Mesmo GTFS de origem => mesmo conteúdo (provado no Metro: só muda o PublicationTimestamp).
            append_manifest(raw_dir, {**base, "registado_em": _now(), "estado": "igual", "sha256": remote["sha256"],
                                      "origem_sha256": remote["origin"], "igual_a": _stored_at(same_origin),
                                      "conteudo_sha256": same_origin["conteudo_sha256"], "verificacoes": "origem=validacao"})
            return Result(src.id, "igual", f"mesma origem que {_stored_at(same_origin)} (sem download)")
    if dry_run:
        return Result(src.id, "seria_descarregado", f"versão {remote['version']}")

    folder = raw_dir / src.id / str(remote["version"])
    if src.kind == "agit_validacao":
        validation = remote["validation"]
        data = _validation_bytes(validation)
        folder.mkdir(parents=True, exist_ok=True)
        part = folder / ".validation.json.part"
        part.write_bytes(data)
        sha256, sha1, size = _hashes(part)
        final = folder / "validation.json"
        _store(part, final)
        append_manifest(raw_dir, {**base, "registado_em": _now(), "estado": "novo", "ficheiro": final.relative_to(raw_dir).as_posix(),
                                  "bytes": size, "sha256": sha256, "sha1": sha1, "origem_sha256": remote["origin"],
                                  "identificador": f"release {remote['release']}", "contagens": json.dumps(validation["counts"]["gtfs"], sort_keys=True),
                                  "verificacoes": "estado=valid"})
        return Result(src.id, "novo", f"release {remote['release']}")

    folder.mkdir(parents=True, exist_ok=True)
    part = folder / f".{remote['filename']}.part"
    try:
        http.download(str(remote["url"]), part)
        sha256, sha1, size = _hashes(part)
        checks = []
        if src.kind == "catalogo":
            if sha1 != remote["sha1"] or size != remote["bytes"]:
                raise FetchError(f"transporte: sha1/tamanho {sha1[:10]}/{size} != catálogo {str(remote['sha1'])[:10]}/{remote['bytes']}")
            checks.append("sha1+tamanho=catalogo")
        else:
            if sha256 != remote["sha256"]:
                raise FetchError(f"transporte: sha256 {sha256[:16]} != /validation {str(remote['sha256'])[:16]}")
            checks.append("sha256=validacao")

        if src.fmt == "netex":
            info = inspect_netex(part, src.identifier, remote.get("validation"))
        elif src.fmt == "gtfs":
            info = inspect_gtfs(part, src.operator)
            if src.agit_origin:
                agit = http.get_json(f"{AGIT_API.format(dataset=src.agit_origin)}/validation")
                same = agit.get("source", {}).get("sha256") == sha256
                checks.append(f"origem_agit_{src.agit_origin}={'sim' if same else 'nao'}")
        else:
            info = inspect_other(part)
        checks.append(info.pop("_checks"))

        row = {**base, **info, "registado_em": _now(), "bytes": size, "sha256": sha256, "sha1": sha1,
               "origem_sha256": remote.get("origin", ""), "verificacoes": ";".join(c for c in checks if c)}
        duplicate = _known(manifest, src.content_sources(), "conteudo_sha256", info["conteudo_sha256"])
        if duplicate:
            part.unlink()
            if not any(folder.iterdir()):
                folder.rmdir()
            append_manifest(raw_dir, {**row, "estado": "igual", "igual_a": _stored_at(duplicate)})
            return Result(src.id, "igual", f"conteúdo igual a {_stored_at(duplicate)} (não guardado)")

        final = folder / str(remote["filename"])
        _store(part, final)
        if remote.get("validation"):
            vpart = folder / ".validation.json.part"
            vpart.write_bytes(_validation_bytes(remote["validation"]))
            _store(vpart, folder / "validation.json")
        append_manifest(raw_dir, {**row, "estado": "novo", "ficheiro": final.relative_to(raw_dir).as_posix()})
        return Result(src.id, "novo", f"versão {remote['version']} ({size / 1e6:.1f} MB)")
    finally:
        if part.exists():
            part.unlink()
        if folder.exists() and not any(folder.iterdir()):
            folder.rmdir()


def register_manual(path: Path, source_id: str, version: str, raw_dir: Path, move: bool = False) -> Path:
    """Regista um ficheiro obtido à mão (PDF, zip do INE...) em data/raw/<fonte>/<versão>/."""
    if not source_id.startswith("manual/"):
        raise FetchError("ficheiros manuais vão para fontes 'manual/...'")
    if not re.fullmatch(r"[0-9A-Za-z._-]+", version):
        raise FetchError(f"versão inválida: {version!r}")
    sha256, sha1, size = _hashes(path)
    if _known(read_manifest(raw_dir), source_id, "sha256", sha256):
        raise FetchError(f"{path.name} já está registado em {source_id}")
    final = raw_dir / source_id / version / path.name
    part = final.with_name(f".{final.name}.part")
    final.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, part)
    _store(part, final)
    append_manifest(raw_dir, {"registado_em": _now(), "fonte": source_id, "versao": version, "estado": "manual",
                              "ficheiro": final.relative_to(raw_dir).as_posix(), "bytes": size, "sha256": sha256,
                              "sha1": sha1, "conteudo_sha256": sha256, "verificacoes": "manual"})
    if move:
        path.unlink()
    return final


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None, http: Http | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("comando", nargs="?", default="fetch", choices=("fetch", "listar", "registar"))
    parser.add_argument("ficheiro", nargs="?", type=Path, help="registar: ficheiro a registar")
    parser.add_argument("--dry-run", action="store_true", help="só mostra o que mudou na origem")
    parser.add_argument("--grupos", default="base", help="grupos de fontes (base,sit)")
    parser.add_argument("--fontes", default="", help="só estas fontes (ids separados por vírgulas)")
    parser.add_argument("--raw", type=Path, default=RAW_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--fonte", default="", help="registar: fonte manual/... ")
    parser.add_argument("--versao", default="", help="registar: versão (ex.: data do documento AAAA-MM-DD)")
    parser.add_argument("--mover", action="store_true", help="registar: apaga o original depois de copiar")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if args.comando == "listar":
        for s in SOURCES:
            print(f"{s.id:34s} [{s.grupo}] {s.fmt:6s} {'versionado' if s.versionar else 'NÃO versionado'} - {s.descricao}")
        return 0
    if args.comando == "registar":
        if not (args.ficheiro and args.fonte and args.versao):
            parser.error("registar precisa de FICHEIRO --fonte manual/... --versao ...")
        final = register_manual(args.ficheiro, args.fonte, args.versao, args.raw, move=args.mover)
        print(f"registado: {final}")
        return 0

    groups = {g.strip() for g in args.grupos.split(",") if g.strip()}
    only = {f.strip() for f in args.fontes.split(",") if f.strip()}
    unknown = only - {s.id for s in SOURCES}
    if unknown:
        parser.error(f"fontes desconhecidas: {sorted(unknown)}")
    selected = [s for s in SOURCES if s.id in only] if only else [s for s in SOURCES if s.grupo in groups]
    http = http or Http()
    results: list[Result] = []
    for src in selected:
        try:
            results.append(process_source(src, http, args.raw, dry_run=args.dry_run))
        except Exception as exc:  # uma fonte falhada não impede as outras; o exit code reflete-a
            results.append(Result(src.id, "falhou", f"{type(exc).__name__}: {exc}"))
        r = results[-1]
        print(f"[{r.status:18s}] {r.source}: {r.detail}")
    failed = [r for r in results if r.status == "falhou"]
    print(f"\n{len(results)} fontes: " + ", ".join(f"{k} {v}" for k, v in Counter(r.status for r in results).items()))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

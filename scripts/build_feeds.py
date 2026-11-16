"""Constrói as pastas GTFS que o código lê (data/gtfs/...) a partir dos ficheiros congelados em
data/raw/ (D1, passo 3). Cada transformação é explícita, contada e registada no PROVENANCE.json
da pasta; data/raw/ nunca é alterado.

    python scripts/build_feeds.py                 # constrói o que faltar e confirma o que já existe
    python scripts/build_feeds.py --verificar     # só confirma que as pastas são o que o build produz

Uma pasta construída é imutável: se já existir e o resultado do build for diferente, o script
recusa (nunca sobrescreve) - uma versão nova vai para outra pasta (ver data/README.md).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from gtfs_processing.fingerprint import feed_fingerprint  # noqa: E402

RAW_DIR = ROOT / "data" / "raw"
GTFS_DIR = ROOT / "data" / "gtfs"
GTFS_TXT = ("agency.txt", "routes.txt", "trips.txt", "stop_times.txt", "stops.txt", "calendar.txt",
            "calendar_dates.txt", "shapes.txt", "feed_info.txt", "frequencies.txt", "transfers.txt")
CALENDAR_DATES_HEADER = ["service_id", "date", "exception_type"]

Table = tuple[list[str], list[dict[str, str]]]  # (colunas, linhas)


class BuildError(RuntimeError):
    pass


# --------------------------------------------------------------------------- transformações
# Cada uma recebe o feed (nome do ficheiro -> tabela) e devolve uma descrição do que mudou,
# com contagens, que vai para o PROVENANCE.json.


def drop_technical_stops(pattern: str, reason: str) -> Callable[[dict[str, Table]], dict]:
    def step(feed: dict[str, Table]) -> dict:
        rx = re.compile(pattern)
        cols, stops = feed["stops.txt"]
        drop = {s["stop_id"] for s in stops if rx.fullmatch(s["stop_name"].strip())}
        if not drop:
            raise BuildError(f"nenhuma paragem corresponde a {pattern!r} - o feed mudou?")
        feed["stops.txt"] = (cols, [s for s in stops if s["stop_id"] not in drop])
        st_cols, st = feed["stop_times.txt"]
        kept = [r for r in st if r["stop_id"] not in drop]
        feed["stop_times.txt"] = (st_cols, kept)
        names = sorted(s["stop_name"] for s in stops if s["stop_id"] in drop)
        return {"passo": "remover paragens técnicas", "padrao_nome": pattern, "motivo": reason,
                "paragens_removidas": names, "passagens_removidas": len(st) - len(kept)}
    return step


def extend_calendar(service_end_from: str, service_end_to: str, reason: str) -> Callable[[dict[str, Table]], dict]:
    def step(feed: dict[str, Table]) -> dict:
        cols, rows = feed["calendar.txt"]
        changed = [r["service_id"] for r in rows if r["end_date"] == service_end_from]
        if len(changed) != len(rows):
            raise BuildError(f"calendar.txt: nem todos os serviços acabam em {service_end_from} - o feed mudou?")
        for r in rows:
            r["end_date"] = service_end_to
        return {"passo": "estender validade do calendário", "de": service_end_from, "para": service_end_to,
                "servicos": changed, "motivo": reason}
    return step


def swap_route_names(route_id: str, expected_short: str, reason: str) -> Callable[[dict[str, Table]], dict]:
    def step(feed: dict[str, Table]) -> dict:
        _, rows = feed["routes.txt"]
        hit = [r for r in rows if r["route_id"] == route_id]
        if len(hit) != 1 or hit[0]["route_short_name"] != expected_short:
            raise BuildError(f"routes.txt: rota {route_id} com route_short_name {expected_short!r} não encontrada - o feed mudou?")
        r = hit[0]
        before = (r["route_short_name"], r["route_long_name"])
        r["route_short_name"], r["route_long_name"] = r["route_long_name"], r["route_short_name"]
        return {"passo": "trocar route_short_name/route_long_name", "route_id": route_id,
                "antes": list(before), "depois": [r["route_short_name"], r["route_long_name"]], "motivo": reason}
    return step


@dataclass(frozen=True)
class Build:
    target: str               # pasta relativa a data/gtfs/
    raw: str                  # ficheiro relativo a data/raw/ (tem de estar no MANIFEST.csv)
    descricao: str
    steps: tuple = field(default_factory=tuple)


BUILDS: tuple[Build, ...] = (
    Build(
        target="metro/fase1_gtfs_20251219",
        raw="dados-gov/metro-mondego-gtfs/20260817-153951-d08309cb/20251219-export-gtfs.zip",
        descricao="Metro Mondego fase 1 (até 09/09/2026): GTFS oficial exportado a 2025-12-19 (dados.gov.pt, CC BY 4.0)",
        steps=(
            drop_technical_stops(
                r"PC\d+",
                "PC1-PC8 são pontos técnicos do traçado sem serviço a passageiros, mas o feed não os marca "
                "(pickup_type/drop_off_type = 0); sem isto contavam como paragens na cobertura e nas isócronas",
            ),
            extend_calendar(
                "20251231", "20260909",
                "O feed só cobre 2025-11-01..2025-12-31. O horário de dez/2025 foi verificado igual, minuto a "
                "minuto, aos PDFs oficiais de horários (criados a 2025-12-22, ainda publicados a 2026-09-06: "
                "data/raw/manual/metro-mondego-horarios-pdf/2025-12-22/) e vigorou até à fase 2 (dias úteis "
                "desde 2026-09-10). "
                "Feriados de 2026 não codificados: o feed não tem calendar_dates e config.FERIADOS_COMO_DOMINGO trata-os.",
            ),
            swap_route_names(
                "3606", "Serpins - Portagem",
                "No feed o nome curto e o longo vêm trocados (short='Serpins - Portagem', long='S1').",
            ),
        ),
    ),
)


# --------------------------------------------------------------------------- leitura / escrita


def _read_member(zf: zipfile.ZipFile, name: str) -> Table:
    text = zf.read(name).decode("utf-8-sig")
    if not text.strip():
        return [], []
    reader = csv.DictReader(io.StringIO(text))
    return list(reader.fieldnames or []), [dict(r) for r in reader]


def _write_table(path: Path, table: Table, name: str) -> None:
    cols, rows = table
    if not cols and name == "calendar_dates.txt":
        cols = CALENDAR_DATES_HEADER  # o original só tem o BOM: pd.read_csv rebentava com EmptyDataError
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha256(path: Path) -> str:
    """sha256 de um .txt com as quebras de linha normalizadas: com core.autocrlf o git converte os
    ficheiros para CRLF no checkout e o hash dos bytes deixaria de bater com o PROVENANCE.json."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _manifest_row(raw_rel: str) -> dict[str, str]:
    with open(RAW_DIR / "MANIFEST.csv", encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["ficheiro"] == raw_rel and r["estado"] == "novo"]
    if len(rows) != 1:
        raise BuildError(f"{raw_rel}: {len(rows)} linhas 'novo' no MANIFEST.csv (esperado 1)")
    return rows[0]


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "desconhecido"


def build_into(build: Build, out_dir: Path) -> dict:
    """Constrói `build` em `out_dir` (vazio) e devolve o PROVENANCE (sem o gravar)."""
    raw_path = RAW_DIR / build.raw
    manifest = _manifest_row(build.raw)
    raw_sha = _sha256(raw_path)
    if raw_sha != manifest["sha256"]:
        raise BuildError(f"{build.raw}: sha256 {raw_sha[:16]} != MANIFEST {manifest['sha256'][:16]} (ficheiro alterado?)")

    with zipfile.ZipFile(raw_path) as zf:
        members = {Path(n).name: n for n in zf.namelist() if n.endswith(".txt")}
        ignored = sorted(Path(n).name for n in zf.namelist() if not n.endswith(".txt"))
        unknown = sorted(set(members) - set(GTFS_TXT))
        if unknown:
            raise BuildError(f"ficheiros .txt inesperados no zip: {unknown}")
        feed = {name: _read_member(zf, members[name]) for name in members}

    steps = [step(feed) for step in build.steps]
    for name, table in sorted(feed.items()):
        _write_table(out_dir / name, table, name)
    return {
        "pasta": f"data/gtfs/{build.target}",
        "descricao": build.descricao,
        "origem": {"ficheiro": f"data/raw/{build.raw}", "sha256": raw_sha, "versao": manifest["versao"],
                   "url": manifest["url"], "verificacoes_no_download": manifest["verificacoes"]},
        "ignorados_do_zip": ignored,
        "transformacoes": steps,
        "ficheiros": {p.name: text_sha256(p) for p in sorted(out_dir.glob("*.txt"))},
        "impressao_digital": feed_fingerprint(out_dir),
        "construido_por": "scripts/build_feeds.py",
        "commit": _git_commit(),
    }


def _comparable(prov: dict) -> dict:
    return {k: v for k, v in prov.items() if k != "commit"}


def run_build(build: Build, verify_only: bool = False) -> str:
    target = GTFS_DIR / build.target
    with tempfile.TemporaryDirectory(prefix="build_") as tmp:
        fresh = build_into(build, Path(tmp))
        if target.exists():
            prov_path = target / "PROVENANCE.json"
            if not prov_path.exists():
                raise BuildError(f"{target} existe sem PROVENANCE.json - não foi feito por este script")
            current = {p.name: text_sha256(p) for p in sorted(target.glob("*.txt"))}
            if current != fresh["ficheiros"]:
                raise BuildError(f"{target}: o conteúdo difere do que o build produz (alterado à mão ou o build mudou) - "
                                 "uma versão nova vai para OUTRA pasta")
            if _comparable(json.loads(prov_path.read_text(encoding="utf-8"))) != _comparable(fresh):
                raise BuildError(f"{target}: PROVENANCE.json desatualizado face ao build")
            return "igual"
        if verify_only:
            raise BuildError(f"{target} não existe (corre sem --verificar para construir)")
        part = target.with_name(f".{target.name}.part")
        if part.exists():
            shutil.rmtree(part)
        shutil.copytree(tmp, part)
        (part / "PROVENANCE.json").write_text(json.dumps(fresh, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(part, target)
        return "construido"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verificar", action="store_true", help="só confirma, não constrói")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    failed = 0
    for build in BUILDS:
        try:
            print(f"[{run_build(build, verify_only=args.verificar):10s}] data/gtfs/{build.target}")
        except BuildError as exc:
            failed += 1
            print(f"[{'falhou':10s}] data/gtfs/{build.target}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

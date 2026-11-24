from __future__ import annotations

import argparse
import shutil
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd
from paths import PROJECT_ROOT

from gtfs_processing.timeutil import series_hhmmss_to_seconds

# Fonte única para o projeto inteiro
REQUIRED_GTFS = ("routes", "trips", "stop_times", "stops")
OPTIONAL_GTFS = ("shapes", "calendar", "calendar_dates")

REQUIRED_FILES = {f"{name}.txt" for name in REQUIRED_GTFS}
OPTIONAL_FILES = {f"{name}.txt" for name in OPTIONAL_GTFS}
_MISSING_OPTIONAL_WARNED: set[tuple[str, str]] = set()


@dataclass
class GTFSData:
    routes: pd.DataFrame
    trips: pd.DataFrame
    stop_times: pd.DataFrame
    stops: pd.DataFrame
    shapes: pd.DataFrame
    calendar: pd.DataFrame
    calendar_dates: pd.DataFrame


# Colunas de identificadores lidas SEMPRE como texto. Os feeds atuais têm ids numéricos, que o
# pandas lia como int64 - o código fazia depois ~120 `astype(str)` espalhados para conseguir
# juntar tabelas e comparar com ids vindos de CSV/config. `route_short_name` entra porque é o
# número público da linha ("54", "5F"): lido como número, uma célula vazia tornava a coluna float
# e "54" passava a "54.0".
ID_COLUMNS = (
    "agency_id",
    "route_id",
    "route_short_name",
    "trip_id",
    "service_id",
    "shape_id",
    "block_id",
    "stop_id",
    "parent_station",
    "zone_id",
)


def _read_csv(source: Path, stem: str) -> pd.DataFrame:
    file_path = source / f"{stem}.txt"
    if not file_path.exists():
        return pd.DataFrame()
    return pd.read_csv(file_path, dtype={col: str for col in ID_COLUMNS})


def _looks_like_gtfs_folder(folder: Path) -> bool:
    return folder.exists() and folder.is_dir() and all((folder / f).exists() for f in REQUIRED_FILES)


def dataset_dir(dataset: str, root: Path | None = None) -> Path:
    """Pasta do feed `dataset` (nome lógico -> config.DATASET_DIRS, relativo a config.GTFS_DIR).
    Fonte ÚNICA do caminho de um dataset: carregamento, assinatura da cache, impressões digitais,
    snapshots e regenerate passam todos por aqui. Nome desconhecido = erro (sem adivinhar pastas)."""
    from config import DATASET_DIRS, GTFS_DIR

    if dataset not in DATASET_DIRS:
        raise KeyError(f"dataset GTFS desconhecido: {dataset!r} (conhecidos: {', '.join(sorted(DATASET_DIRS))}; ver config.DATASET_DIRS)")
    root = Path(root) if root is not None else PROJECT_ROOT
    return root / GTFS_DIR / DATASET_DIRS[dataset]


def _find_gtfs_dir(dataset: str, root: Path) -> Path:
    # Os ficheiros têm de estar DIRETAMENTE na pasta do dataset. Antes procurava-se recursivamente
    # e aceitava-se a 1ª subpasta com GTFS: com cópias/exports lá dentro lia-se o feed errado em
    # silêncio.
    folder = dataset_dir(dataset, root)
    if _looks_like_gtfs_folder(folder):
        return folder
    raise FileNotFoundError(f"Dataset GTFS não encontrado/incompleto: {dataset} (esperado em {folder})")


def _resolve_source_dir(source_dir: Optional[str], dataset: str) -> Path:
    root = PROJECT_ROOT

    if source_dir:
        p = Path(source_dir)
        if not p.is_absolute():
            p = (root / p).resolve()
        if not _looks_like_gtfs_folder(p):
            raise FileNotFoundError(f"Diretório GTFS inválido: {p}")
        return p

    return _find_gtfs_dir(dataset, root)


def load_gtfs(source_dir: Optional[str] = None, dataset: str = "nd") -> GTFSData:
    source = _resolve_source_dir(source_dir=source_dir, dataset=dataset)

    frames: dict[str, pd.DataFrame] = {}
    for name in REQUIRED_GTFS + OPTIONAL_GTFS:
        frames[name] = _read_csv(source, name)

    missing = [name for name in REQUIRED_GTFS if frames[name].empty]
    if missing:
        missing_list = ", ".join(f"{name}.txt" for name in missing)
        raise ValueError(f"Arquivos GTFS obrigatórios em falta: {missing_list}")

    missing = [name for name in OPTIONAL_GTFS if frames[name].empty]
    if missing:
        missing_list = ", ".join(f"{name}.txt" for name in missing)
        warning_key = (str(source), missing_list)
        if warning_key not in _MISSING_OPTIONAL_WARNED:
            print(f"Arquivos GTFS opcionais em falta ou sem linhas: {missing_list}")
            _MISSING_OPTIONAL_WARNED.add(warning_key)

    st = frames["stop_times"]
    for col in ("arrival_time", "departure_time"):
        if col not in st.columns:
            raise ValueError(f"stop_times.txt sem coluna obrigatória: {col}")

    # Estrito: uma hora vazia/malformada levanta ValueError (antes valia 0 = meia-noite em
    # silêncio). O projeto não interpola horários de paragens sem ponto de controlo.
    st["arrival_seconds"] = series_hhmmss_to_seconds(st["arrival_time"], f"arrival_time em {source}")
    st["departure_seconds"] = series_hhmmss_to_seconds(st["departure_time"], f"departure_time em {source}")

    return GTFSData(
        routes=frames["routes"],
        trips=frames["trips"],
        stop_times=st,
        stops=frames["stops"],
        shapes=frames["shapes"],
        calendar=frames["calendar"],
        calendar_dates=frames["calendar_dates"],
    )


@lru_cache(maxsize=8)
def load_gtfs_cached(dataset: str) -> GTFSData:
    """`load_gtfs(dataset=...)` com cache em memória - a ÚNICA cache de feeds do projeto (antes
    overlap_db e transit tinham cada um a sua, e lines_map/operations_population voltavam a ler
    os ficheiros). O GTFSData devolvido é partilhado: quem o usa NÃO pode alterar os DataFrames no
    lugar (trabalhar sobre `.copy()`). `load_gtfs_cached.cache_clear()` força nova leitura."""
    return load_gtfs(dataset=dataset)


def extract_or_copy_gtfs(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)

    if src.is_file() and src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src, "r") as zf:
            by_name = {Path(m).name: m for m in zf.namelist()}
            missing = REQUIRED_FILES - set(by_name.keys())
            if missing:
                raise FileNotFoundError(f"GTFS incompleto. Faltam: {', '.join(sorted(missing))}")

            for name in sorted(REQUIRED_FILES | OPTIONAL_FILES):
                if name in by_name:
                    with zf.open(by_name[name]) as src_f, (dst / name).open("wb") as dst_f:
                        shutil.copyfileobj(src_f, dst_f)

    elif src.is_dir():
        files = {p.name for p in src.glob("*.txt")}
        missing = REQUIRED_FILES - files
        if missing:
            raise FileNotFoundError(f"GTFS incompleto. Faltam: {', '.join(sorted(missing))}")

        for name in sorted(REQUIRED_FILES | OPTIONAL_FILES):
            fp = src / name
            if fp.exists():
                shutil.copy2(fp, dst / name)
    else:
        raise ValueError("Origem inválida. Usa uma pasta GTFS ou um ficheiro .zip")


def _main() -> None:
    parser = argparse.ArgumentParser(description="GTFS utilitário")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_int = sub.add_parser("integrate", help="Integrar GTFS (.zip/pasta) numa pasta de data/gtfs/")
    p_int.add_argument("--source", required=True, help="Caminho para GTFS (.zip ou pasta)")
    # Sem valor por omissão: o antigo "data" despejava os .txt na raiz de data/.
    p_int.add_argument("--target", required=True, help="Pasta destino (ex.: data/gtfs/metro/<nova_pasta>)")

    p_ins = sub.add_parser("inspect", help="Carregar um GTFS de config.DATASET_DIRS")
    p_ins.add_argument("--dataset", default="smtuc", help="nome lógico (ver config.DATASET_DIRS)")
    p_ins.add_argument("--source-dir", default=None, help="Override de diretório GTFS")

    args = parser.parse_args()
    root = PROJECT_ROOT

    if args.cmd == "integrate":
        source = Path(args.source).expanduser().resolve()
        target = (root / args.target).resolve()
        extract_or_copy_gtfs(source, target)
        print(f"GTFS integrado em: {target}")
        return

    gtfs = load_gtfs(source_dir=args.source_dir, dataset=args.dataset)
    print(f"dataset={args.dataset}")
    print(f"routes={len(gtfs.routes)} trips={len(gtfs.trips)} stops={len(gtfs.stops)} stop_times={len(gtfs.stop_times)}")

if __name__ == "__main__":
    _main()

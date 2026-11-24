"""Snapshot dos números de controlo do projeto e comparação entre snapshots (passo D0.2).

Para cada troca de dados (Fase D: metro oficial, fase 2, SIT) ou refatoração de cálculo (Fases
4/5), tira-se um snapshot ANTES e outro DEPOIS e compara-se: o que mudou fica explícito em vez
de se descobrir nos slides.

    python scripts/snapshot_metrics.py snapshot sintetico                       # cenário por omissão
    python scripts/snapshot_metrics.py snapshot oficial_fase2 --cenario fase2   # feeds + dia do cenário
    python scripts/snapshot_metrics.py snapshot teste --metro outro_metro       # cenário com outro feed
    python scripts/snapshot_metrics.py diff reports/metricas/sintetico.csv reports/metricas/metro_2025.csv
    python scripts/snapshot_metrics.py diff A.csv B.csv --check                 # exit 1 se algo mudou

Formato (CSV longo, uma linha por número): section, key, metric, value. As linhas com
section="meta" descrevem COMO foi calculado (datasets, impressões digitais, dia/hora, parâmetros,
commit) e não contam como diferença no diff. Os valores são arredondados a 4 casas.

Secções:
  linhas          por linha SMTUC: frequência, viagens no dia, overlap espacial/temporal, raio do estádio
  overlap_resumo  totais do overlap (os do rodapé/slide de overlap) e rankings top/bottom 5
  esperas_54      espera mediana, cobertura <=10 min e perda >15 min por sentido nos nós
                  INTEGRATION_SITES, para o horário atual e as propostas com os desvios do config
  busca_fase_54   melhor desvio de fase de cada proposta (scripts/search_phase_shift.py)
  isocrona        população e zonas por faixa de tempo a partir do estádio, e por modo
  populacao       população sem oferta (total e no raio do painel do estádio), top 10 de subserviço

Nada é escrito em outputs/: o cache de métricas é copiado para uma pasta temporária e as tabelas
intermédias vão para lá. Um snapshot existente NÃO é substituído sem --force (é uma linha de base).

Os feeds e o dia/hora de referência vêm do cenário (--cenario, config.SCENARIOS); --smtuc/--metro
trocam só o feed (o dia continua o do cenário). Todas as secções, incluindo as esperas da 54,
usam o mesmo cenário.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

import pandas as pd  # noqa: E402

COLUMNS = ["section", "key", "metric", "value"]
SECTIONS = ("linhas", "overlap_resumo", "esperas_54", "busca_fase_54", "isocrona", "populacao")
DEFAULT_OUT_DIR = ROOT / "reports" / "metricas"
DECIMALS = 4

# Colunas de outputs/overlap/line_metrics_db.csv que entram na secção "linhas".
LINE_METRICS = (
    "avg_freq_min",
    "ref_day_trips",
    "overlap_pct",
    "overlap_extension_m",
    "line_extension_m",
    "overlap_stops",
    "total_stops",
    "radius_extension_pct",
    "temporal_overlaps_count",
    "temporal_overlaps_pct",
    "temporal_spatial_candidates_count",
)


class Snapshot:
    """Acumula as linhas (section, key, metric, value) de um snapshot."""

    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def add(self, section: str, key: object, metric: str, value: object) -> None:
        self.rows.append({"section": section, "key": str(key), "metric": metric, "value": _normalize(value)})

    def frame(self) -> pd.DataFrame:
        df = pd.DataFrame(self.rows, columns=COLUMNS)
        dup = df.duplicated(["section", "key", "metric"], keep=False)
        if dup.any():
            raise ValueError(f"chaves repetidas no snapshot: {df[dup].head().to_dict('records')}")
        return df


def _normalize(value: object) -> object:
    """Números arredondados (int quando inteiros), NaN/inf como texto, o resto como str."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)) or hasattr(value, "item"):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if math.isnan(number):
            return "nan"
        if math.isinf(number):
            return "inf" if number > 0 else "-inf"
        rounded = round(number, DECIMALS)
        return int(rounded) if rounded == int(rounded) else rounded
    return str(value)


# --------------------------------------------------------------------------- secções


def _section_lines(snap: Snapshot, metrics: pd.DataFrame) -> None:
    for _, row in metrics.sort_values("line", key=lambda s: s.astype(str)).iterrows():
        for col in LINE_METRICS:
            if col in metrics.columns:
                snap.add("linhas", row["line"], col, row[col])


def _section_overlap_summary(snap: Snapshot, metrics_csv: Path) -> None:
    from visualizations.dashboard import load_overlap_stats

    stats = load_overlap_stats(metrics_csv) or {}
    for name, value in sorted((stats.get("temporal_summary") or {}).items()):
        if isinstance(value, (int, float, str)) and not str(name).endswith("_fmt"):
            snap.add("overlap_resumo", "total", name, value)
    for ranking in ("top5", "bottom5", "bottom5_stadium"):
        for i, row in enumerate(stats.get(ranking) or [], start=1):
            snap.add("overlap_resumo", f"{ranking}_{i:02d}", "line", row.get("line"))


def _load_phase_search():
    spec = importlib.util.spec_from_file_location("search_phase_shift", ROOT / "scripts" / "search_phase_shift.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _section_waits(snap: Snapshot, workdir: Path, with_search: bool, scenario) -> None:
    from config import LINE_54_MELHORADO_PHASE_SHIFT_MIN, LINE_54_OPTIMIZED_PHASE_SHIFT_MIN

    search = _load_phase_search()
    schedules = search.load_schedules(workdir, scenario=scenario)
    shifts = {"atual": 0.0, "otimizado": LINE_54_OPTIMIZED_PHASE_SHIFT_MIN, "melhorado": LINE_54_MELHORADO_PHASE_SHIFT_MIN}
    for sense, df in schedules.items():
        for variant, shift in shifts.items():
            m = search.sense_metrics(search._variant(variant, sense, df, float(shift)))
            for metric in ("median", "cov10", "lost15"):
                snap.add("esperas_54", f"{sense} | {variant}", metric, m[metric])
            snap.add("esperas_54", f"{sense} | {variant}", "shift_min", shift)
    if with_search:
        results, _ = search.search(schedules)  # meio ciclo de cada proposta, critério do script
        for variant in ("otimizado", "melhorado"):
            best = search.best(results, variant)
            for metric in ("shift_min", "melhorados", "regressoes", "soma_medianas"):
                snap.add("busca_fase_54", variant, metric, best[metric])


def _section_population(snap: Snapshot, datasets: tuple[str, str], day_str: str, time_str: str, workdir: Path,
                        with_isochrone: bool, with_population: bool) -> None:
    from config import POPULATION_STADIUM_MAP_RADIUS_M, REACHABILITY_MAX_TRANSFERS, STADIUM_COORD
    from overlap.overlap import compute_bgri_reachability_now
    from population.data_processing import compute_underserved_zones, filter_zones_by_distance

    merged = compute_underserved_zones(
        day_str=day_str, datasets=datasets, output_csv_path=str(workdir / "bgri_transport_gap.csv")
    )
    pop = pd.to_numeric(merged["N_INDIVIDUOS"], errors="coerce").fillna(0.0)

    if with_population:
        no_supply = merged["supply_departures"] <= 0
        snap.add("populacao", "total", "populacao", pop.sum())
        snap.add("populacao", "total", "zonas", len(merged))
        snap.add("populacao", "total", "partidas", merged["supply_departures"].sum())
        snap.add("populacao", "sem_oferta", "populacao", pop[no_supply].sum())
        snap.add("populacao", "sem_oferta", "zonas", int(no_supply.sum()))
        near = filter_zones_by_distance(merged, distance_m=POPULATION_STADIUM_MAP_RADIUS_M)
        near_pop = pd.to_numeric(near["N_INDIVIDUOS"], errors="coerce").fillna(0.0)
        near_no_supply = near["supply_departures"] <= 0
        key = f"raio_estadio_{int(POPULATION_STADIUM_MAP_RADIUS_M)}m"
        snap.add("populacao", key, "populacao", near_pop.sum())
        snap.add("populacao", key, "populacao_sem_oferta", near_pop[near_no_supply].sum())
        snap.add("populacao", key, "zonas_sem_oferta", int(near_no_supply.sum()))
        top = merged.sort_values(["underservice_score", "BGRI2021"], ascending=[False, True]).head(10)
        for i, (_, row) in enumerate(top.iterrows(), start=1):
            snap.add("populacao", f"top_subservico_{i:02d}", "bgri", row["BGRI2021"])
            snap.add("populacao", f"top_subservico_{i:02d}", "score", row["underservice_score"])

    if with_isochrone:
        reach = compute_bgri_reachability_now(
            merged_bgri=merged, origin_lat=STADIUM_COORD[0], origin_lon=STADIUM_COORD[1], datasets=datasets,
            day_str=day_str, time_str=time_str, max_transfers=REACHABILITY_MAX_TRANSFERS,
        )
        reach_pop = pd.to_numeric(reach["N_INDIVIDUOS"], errors="coerce").fillna(0.0)
        snap.add("isocrona", "origem", "hora_partida", str(reach["reach_time"].iloc[0]) if len(reach) else "")
        for band in ("0-10", "10-15", "15-30", "30-60", ">60"):
            mask = reach["reach_bin"] == band
            snap.add("isocrona", f"faixa {band}", "populacao", reach_pop[mask].sum())
            snap.add("isocrona", f"faixa {band}", "zonas", int(mask.sum()))
        for mode in sorted(reach["reach_mode"].unique()):
            snap.add("isocrona", f"modo {mode}", "populacao", reach_pop[reach["reach_mode"] == mode].sum())
        finite = reach["reach_min"].replace([float("inf")], pd.NA).dropna().astype(float)
        weights = reach_pop.loc[finite.index]
        if weights.sum() > 0:
            snap.add("isocrona", "total", "tempo_medio_ponderado_min", float((finite * weights).sum() / weights.sum()))


# --------------------------------------------------------------------------- snapshot


def _git_commit() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True, text=True)
        return head.stdout.strip() + ("+alterações" if dirty.stdout.strip() else "")
    except (OSError, subprocess.CalledProcessError):
        return "desconhecido"


def _add_meta(snap: Snapshot, phase: str, smtuc: str, metro: str, day_str: str, time_str: str,
              scenario_name: str) -> None:
    import config
    from gtfs_processing.fingerprint import feed_fingerprint

    snap.add("meta", "snapshot", "fase", phase)
    snap.add("meta", "snapshot", "cenario", scenario_name)
    snap.add("meta", "snapshot", "criado_em", date.today().isoformat())
    snap.add("meta", "snapshot", "commit", _git_commit())
    snap.add("meta", "dados", "smtuc", smtuc)
    snap.add("meta", "dados", "metro", metro)
    from gtfs_processing.gtfs import dataset_dir

    # Pelo papel (smtuc/metro) e não pelo nome do dataset, para o diff mostrar "mudou" ao trocar de feed.
    for role, dataset in (("smtuc", smtuc), ("metro", metro)):
        folder = dataset_dir(dataset, ROOT)
        snap.add("meta", "dados", f"pasta_{role}", folder.relative_to(ROOT).as_posix())
        snap.add("meta", "dados", f"impressao_digital_{role}", feed_fingerprint(folder) or "ausente")
    snap.add("meta", "dados", "dia_referencia", day_str)
    snap.add("meta", "dados", "hora_isocrona", time_str)
    for name in (
        "WALK_SPEED_M_MIN", "CATCHMENT_M", "TRANSFER_BUFFER_MIN", "FREQUENCY_WINDOW_START_H", "FREQUENCY_WINDOW_END_H",
        "TEMPORAL_OVERLAP_MAX_MIN", "SPATIAL_OVERLAP_WALK_MIN", "STADIUM_RADIUS_M", "REACHABILITY_MAX_MIN",
        "REACHABILITY_MAX_TRANSFERS", "LINE_54_OPTIMIZED_PHASE_SHIFT_MIN", "LINE_54_MELHORADO_PHASE_SHIFT_MIN",
    ):
        if hasattr(config, name):
            snap.add("meta", "parametros", name, getattr(config, name))


def _metrics_cache(scenario, workdir: Path) -> tuple[pd.DataFrame, Path]:
    """Métricas por linha a partir de uma CÓPIA do cache publicado do cenário (reaproveita-o se
    ainda for válido - a chave do cache confere datasets, dia e parâmetros; senão recalcula na
    cópia) - outputs/ nunca é tocado."""
    from config import LINE_METRICS_DB_PATH
    from gtfs_processing.scenarios import scenario_output_path
    from overlap.overlap_db import build_line_metrics_db

    published = ROOT / scenario_output_path(LINE_METRICS_DB_PATH, scenario)
    copy = workdir / "line_metrics_db.csv"
    if published.exists():
        shutil.copyfile(published, copy)
    metrics = build_line_metrics_db(db_path=str(copy), scenario=scenario)
    return metrics, copy


def take_snapshot(phase: str, smtuc: str | None = None, metro: str | None = None,
                  sections: tuple[str, ...] = SECTIONS, workdir: Path | None = None,
                  scenario: str | None = None) -> pd.DataFrame:
    """`scenario` (config.SCENARIOS; None = o por omissão) dá os feeds e o dia/hora; `smtuc`/`metro`
    substituem só o feed respetivo (cenário ad hoc com o mesmo dia)."""
    import dataclasses

    from gtfs_processing.scenarios import get_scenario
    from overlap.transit import resolve_reference_day

    unknown = set(sections) - set(SECTIONS)
    if unknown:
        raise ValueError(f"secções desconhecidas: {sorted(unknown)} (válidas: {', '.join(SECTIONS)})")
    sc = get_scenario(scenario)
    sc = dataclasses.replace(sc, smtuc=smtuc or sc.smtuc, metro=metro or sc.metro)
    smtuc, metro = sc.smtuc, sc.metro
    day_str = resolve_reference_day(scenario=sc).isoformat()
    # Hora fixa SEMPRE (mesmo com USE_FIXED_REFERENCE_DAY=False) para o snapshot ser reprodutível.
    time_str = sc.reference_time

    snap = Snapshot()
    _add_meta(snap, phase, smtuc, metro, day_str, time_str, sc.name)
    skipped: list[str] = []

    with tempfile.TemporaryDirectory(prefix="snapshot_") as tmp:
        work = Path(workdir) if workdir else Path(tmp)
        if {"linhas", "overlap_resumo"} & set(sections):
            print(f"[snapshot] métricas por linha ({smtuc} + {metro})...")
            metrics, metrics_csv = _metrics_cache(sc, work)
            if "linhas" in sections:
                _section_lines(snap, metrics)
            if "overlap_resumo" in sections:
                _section_overlap_summary(snap, metrics_csv)

        wants_waits = {"esperas_54", "busca_fase_54"} & set(sections)
        if wants_waits:
            print("[snapshot] esperas da 54" + (" + busca de fase (meio ciclo)" if "busca_fase_54" in sections else "") + "...")
            _section_waits(snap, work, with_search="busca_fase_54" in sections, scenario=sc)

        if {"isocrona", "populacao"} & set(sections):
            print("[snapshot] população BGRI" + (" + isócronas do estádio" if "isocrona" in sections else "") + "...")
            _section_population(snap, (smtuc, metro), day_str, time_str, work,
                                with_isochrone="isocrona" in sections, with_population="populacao" in sections)

    snap.add("meta", "snapshot", "secoes", ";".join(s for s in sections if s not in skipped))
    snap.add("meta", "snapshot", "secoes_omitidas", ";".join(skipped))
    return snap.frame()


def write_snapshot(df: pd.DataFrame, path: Path, force: bool = False) -> Path:
    path = Path(path)
    if path.exists() and not force:
        raise FileExistsError(f"{path} já existe (é uma linha de base) - usa --force para substituir")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        df.to_csv(tmp, index=False, encoding="utf-8", lineterminator="\n")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path


# --------------------------------------------------------------------------- diff


def read_snapshot(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"{path}: não é um snapshot (faltam colunas {sorted(missing)})")
    return df[COLUMNS]


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def diff_snapshots(before: pd.DataFrame, after: pd.DataFrame, tol: float = 1e-6) -> pd.DataFrame:
    """Uma linha por número que mudou, apareceu ou desapareceu (meta incluída, marcada como tal).
    Colunas: section, key, metric, before, after, delta, delta_pct, status."""
    keys = ["section", "key", "metric"]
    merged = before.rename(columns={"value": "before"}).merge(
        after.rename(columns={"value": "after"}), on=keys, how="outer", indicator=True
    )
    rows = []
    for rec in merged.to_dict("records"):
        a, b = rec.get("before"), rec.get("after")
        status = {"left_only": "removido", "right_only": "novo"}.get(rec["_merge"])
        delta = delta_pct = None
        if status is None:
            fa, fb = _as_float(a), _as_float(b)
            if fa is not None and fb is not None and math.isfinite(fa) and math.isfinite(fb):
                if abs(fb - fa) <= tol:
                    continue
                delta = fb - fa
                delta_pct = (delta / abs(fa) * 100.0) if fa != 0 else None
                status = "mudou"
            elif a == b or (fa is not None and fb is not None and fa == fb):
                continue
            else:
                status = "mudou"
        rows.append({**{k: rec[k] for k in keys}, "before": "" if pd.isna(a) else a, "after": "" if pd.isna(b) else b,
                     "delta": delta, "delta_pct": delta_pct, "status": status})
    out = pd.DataFrame(rows, columns=[*keys, "before", "after", "delta", "delta_pct", "status"])
    order = {s: i for i, s in enumerate(("meta", *SECTIONS))}
    return out.sort_values(keys, key=lambda s: s.map(order).fillna(99) if s.name == "section" else s).reset_index(drop=True)


def _print_diff(diff: pd.DataFrame) -> None:
    data = diff[diff["section"] != "meta"]
    meta = diff[diff["section"] == "meta"]
    if not meta.empty:
        print("Contexto diferente (meta):")
        for r in meta.itertuples():
            print(f"  {r.key}/{r.metric}: {r.before or '-'} -> {r.after or '-'}")
    if data.empty:
        print("Nenhum número mudou.")
        return
    print(f"{len(data)} números diferentes:")
    for section, group in data.groupby("section", sort=False):
        print(f"\n[{section}] {len(group)}")
        for r in group.itertuples():
            pct = f" ({r.delta_pct:+.1f}%)" if isinstance(r.delta_pct, float) and math.isfinite(r.delta_pct) else ""
            print(f"  {r.key} | {r.metric}: {r.before or '-'} -> {r.after or '-'}{pct}  [{r.status}]")


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_snap = sub.add_parser("snapshot", help="calcula e grava reports/metricas/<fase>.csv")
    p_snap.add_argument("fase", help="nome do snapshot (ex.: sintetico, oficial_fase1_d24, oficial_fase2)")
    p_snap.add_argument("--cenario", default=None, help="cenário de config.SCENARIOS (feeds + dia/hora; por omissão o DEFAULT_SCENARIO)")
    p_snap.add_argument("--smtuc", default=None, help="troca o SMTUC do cenário (nome lógico em config.DATASET_DIRS)")
    p_snap.add_argument("--metro", default=None, help="troca o metro do cenário (nome lógico em config.DATASET_DIRS)")
    p_snap.add_argument("--secoes", default=",".join(SECTIONS), help=f"lista separada por vírgulas ({','.join(SECTIONS)})")
    p_snap.add_argument("--out", type=Path, default=None, help="ficheiro de saída (por omissão reports/metricas/<fase>.csv)")
    p_snap.add_argument("--force", action="store_true", help="substitui um snapshot existente")

    p_diff = sub.add_parser("diff", help="compara dois snapshots")
    p_diff.add_argument("antes", type=Path)
    p_diff.add_argument("depois", type=Path)
    p_diff.add_argument("--tol", type=float, default=1e-6, help="diferença numérica ignorada (absoluta)")
    p_diff.add_argument("--csv", type=Path, default=None, help="grava a tabela de diferenças neste CSV")
    p_diff.add_argument("--check", action="store_true", help="exit 1 se algum número (fora de meta) mudou")

    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    if args.command == "snapshot":
        if not args.fase.replace("_", "").replace("-", "").isalnum():
            parser.error("nome da fase: só letras, números, _ e -")
        out = args.out or DEFAULT_OUT_DIR / f"{args.fase}.csv"
        if out.exists() and not args.force:
            print(f"[ERRO] {out} já existe (é uma linha de base) - usa --force para substituir", file=sys.stderr)
            return 2
        sections = tuple(s.strip() for s in args.secoes.split(",") if s.strip())
        df = take_snapshot(args.fase, smtuc=args.smtuc, metro=args.metro, sections=sections, scenario=args.cenario)
        write_snapshot(df, out, force=args.force)
        print(f"[snapshot] {int((df['section'] != 'meta').sum())} números -> {out}")
        return 0

    diff = diff_snapshots(read_snapshot(args.antes), read_snapshot(args.depois), tol=args.tol)
    _print_diff(diff)
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        diff.to_csv(args.csv, index=False)
    changed = int((diff["section"] != "meta").sum())
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())

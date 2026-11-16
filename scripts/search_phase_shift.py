"""Busca exaustiva do desvio de fase da linha 54 (propostas "otimizado" e "melhorado").

Reproduz o raciocínio documentado em config.LINE_54_OPTIMIZED_PHASE_SHIFT_MIN /
LINE_54_MELHORADO_PHASE_SHIFT_MIN (o script original que deu -16 / -8 não estava no repositório):
para cada desvio de -20 a +20 min, desloca as passagens da linha 54 e mede os 4 sentidos de
transbordo em simultâneo (Portagem e Portela, metro->autocarro e autocarro->metro) - um desvio
da 54 mexe nos dois nós ao mesmo tempo, por isso não se pode otimizar cada sentido isolado.

  otimizado: mesmas viagens, ciclo de 40 min, só desloca a partida.
  melhorado: 2º autocarro no ciclo (40 -> 20 min, +1 autocarro/motorista), mais o desvio.

Métrica por sentido: espera mediana (min) entre a chegada e a partida apanhada, já com o
transbordo a pé (config.TRANSFER_BUFFER_MIN + distância real) - ver
overlap.transit.compute_transfer_waits. Um sentido "melhora" se a mediana descer e "regride" se
subir face ao horário atual. Escolha: mais sentidos melhorados, depois menos regressões, depois
menor soma de medianas, depois o desvio de menor módulo (mexer menos no horário atual).

Os resultados dependem do horário do Metrobus (dataset metrobus em config.DATASET_DIRS). Sempre que os dados mudarem
(ex.: feeds oficiais AGIT), correr de novo e atualizar o config:

    PYTHONPATH="src;." python scripts/search_phase_shift.py            # Windows (Git Bash)
    python scripts/search_phase_shift.py --csv outputs/integration/phase_search.csv
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

import pandas as pd  # noqa: E402

from config import (  # noqa: E402
    INTEGRATION_SITES,
    LINE_54_MELHORADO_PHASE_SHIFT_MIN,
    LINE_54_OPTIMIZED_PHASE_SHIFT_MIN,
    TRANSFER_BUFFER_MIN,
)
from overlap.transit import (  # noqa: E402
    build_line_stop_vs_metro_table,
    build_reverse_stop_vs_metro_table,
    resolve_reference_day,
)
from visualizations.integration import (  # noqa: E402
    _build_waits_table,
    _double_and_shift_reverse_schedule_bus_arrivals,
    _double_and_shift_schedule_bus_times,
    _shift_reverse_schedule_bus_arrivals,
    _shift_schedule_bus_times,
)

LINE = "54"


def _lines(site: dict) -> str | list[str]:
    value = site["line_number"]
    return value if isinstance(value, str) else list(value)


def load_schedules(output_dir: Path) -> dict[str, pd.DataFrame]:
    """As 4 tabelas atuais (2 nós x 2 sentidos), escritas num diretório temporário."""
    out: dict[str, pd.DataFrame] = {}
    for s in INTEGRATION_SITES:
        out[f"{s['name']} metro→bus"] = build_line_stop_vs_metro_table(
            s["metro_stop_ref"], s["bus_stop_ref"], _lines(s), metro_origin_ref=s["metro_origin_ref"],
            bus_origin_ref=s["bus_origin_ref"], output_dir=output_dir,
        )
        out[f"{s['name']} bus→metro"] = build_reverse_stop_vs_metro_table(
            s["bus_stop_ref"], s["metro_stop_ref"], _lines(s), metro_towards_ref=s["reverse_metro_towards_ref"],
            bus_origin_ref=s["bus_origin_ref"], output_dir=output_dir,
        )
    return out


def _variant(name: str, sense: str, df: pd.DataFrame, shift: float) -> pd.DataFrame:
    forward = sense.endswith("metro→bus")
    if name == "atual":
        return df
    if name == "otimizado":
        return _shift_schedule_bus_times(df, LINE, shift) if forward else _shift_reverse_schedule_bus_arrivals(df, shift)
    if name == "melhorado":
        return (
            _double_and_shift_schedule_bus_times(df, LINE, shift)
            if forward
            else _double_and_shift_reverse_schedule_bus_arrivals(df, shift)
        )
    raise ValueError(name)


def sense_metrics(df: pd.DataFrame) -> dict[str, float]:
    waits = pd.to_numeric(_build_waits_table(df)["wait_min"], errors="coerce")
    n = len(waits)
    return {
        "median": float(waits.median()) if waits.notna().any() else float("nan"),
        "cov10": float((waits <= 10).sum() / n * 100.0) if n else float("nan"),
        "lost15": float(((waits > 15) | waits.isna()).sum() / n * 100.0) if n else float("nan"),
    }


def search(schedules: dict[str, pd.DataFrame], shifts: range) -> pd.DataFrame:
    base = {sense: sense_metrics(df) for sense, df in schedules.items()}
    rows = []
    for variant in ("otimizado", "melhorado"):
        for shift in shifts:
            row: dict[str, object] = {"variant": variant, "shift_min": shift}
            improved = regressed = 0
            total = 0.0
            for sense, df in schedules.items():
                m = sense_metrics(_variant(variant, sense, df, float(shift)))
                row[f"{sense} mediana"] = round(m["median"], 2)
                row[f"{sense} cob≤10%"] = round(m["cov10"], 1)
                row[f"{sense} perda>15%"] = round(m["lost15"], 1)
                delta = m["median"] - base[sense]["median"]
                improved += delta < -1e-9
                regressed += delta > 1e-9
                total += m["median"]
            row.update({"melhorados": improved, "regressoes": regressed, "soma_medianas": round(total, 2)})
            rows.append(row)
    out = pd.DataFrame(rows)
    out["_rank_key"] = list(zip(-out["melhorados"], out["regressoes"], out["soma_medianas"], out["shift_min"].abs()))
    return out, base


def best(results: pd.DataFrame, variant: str) -> pd.Series:
    sub = results[results["variant"] == variant]
    return sub.loc[sub["_rank_key"].idxmin()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--min", type=int, default=-20, dest="lo")
    parser.add_argument("--max", type=int, default=20, dest="hi")
    parser.add_argument("--csv", type=Path, default=None, help="grava a tabela completa neste CSV")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument(
        "--sem-transbordo", action="store_true",
        help="regra antiga (transbordo = 0 min) - só para comparar/reproduzir os valores originais",
    )
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    print(f"Dia de referência: {resolve_reference_day().isoformat()} | margem de transbordo: {TRANSFER_BUFFER_MIN} min")
    with tempfile.TemporaryDirectory() as tmp:
        schedules = load_schedules(Path(tmp))
    if args.sem_transbordo:
        print("[AVISO] --sem-transbordo: regra antiga, transbordo = 0 min (ligações fisicamente impossíveis contam)")
        schedules = {k: v.drop(columns=["target_transfer_min", "trigger_transfer_min"], errors="ignore") for k, v in schedules.items()}
    results, base = search(schedules, range(args.lo, args.hi + 1))

    print("\nHorário atual (espera mediana, min):")
    for sense, m in base.items():
        print(f"  {sense:22s} mediana={m['median']:5.1f}  cob≤10={m['cov10']:5.1f}%  perda>15={m['lost15']:5.1f}%")

    medians = [c for c in results.columns if c.endswith(" mediana")]
    show = ["shift_min", *medians, "melhorados", "regressoes", "soma_medianas"]
    configured = {"otimizado": LINE_54_OPTIMIZED_PHASE_SHIFT_MIN, "melhorado": LINE_54_MELHORADO_PHASE_SHIFT_MIN}
    pd.set_option("display.width", 250, "display.max_columns", 30)
    for variant in ("otimizado", "melhorado"):
        sub = results[results["variant"] == variant].sort_values("_rank_key")
        print(f"\n=== {variant}: top {args.top} ===")
        print(sub[show].head(args.top).to_string(index=False))
        winner = best(results, variant)
        current = sub[sub["shift_min"] == int(configured[variant])]
        rank = int((sub["shift_min"] == int(configured[variant])).to_numpy().argmax()) + 1 if not current.empty else None
        print(
            f"-> recomendado: {int(winner['shift_min']):+d} min "
            f"({int(winner['melhorados'])}/4 sentidos melhorados, {int(winner['regressoes'])} regressões). "
            f"Valor atual no config: {configured[variant]:+.0f} min (posição {rank} de {len(sub)})."
        )

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        results.drop(columns="_rank_key").to_csv(args.csv, index=False)
        print(f"\nTabela completa: {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

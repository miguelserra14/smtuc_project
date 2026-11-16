"""Corrige (em vez de simplesmente apagar) as viagens do Metrobus com horários não-cronológicos
(bug pré-existente nos dados, não relacionado com a extensão da fase 2 - ver conversa: descoberto
ao investigar por que razão o mapa de isócronas da fase 2 não mostrava o impacto dos ramais
novos).

41 das 201 viagens do tronco original (SAT_OUT_005..020, WD_OUT_004..028) têm um PREFIXO de
paragens com horários errados (parecem fragmentos de outras viagens, colados por engano), mas o
resto da viagem - da paragem em diante onde os horários voltam a ser monótonos - está limpo e
internamente consistente:
 - As 16 viagens SAT_OUT_* têm as primeiras 3 paragens erradas (SRP, CSA, CES); as restantes 24
   (a partir de LES) estão corretas.
 - As 25 viagens WD_OUT_* têm as primeiras 7 paragens erradas (SRP..PAD); as restantes 20 (a
   partir de COR) estão corretas.
Em ambos os casos, o padrão é sistemático (mesmo ponto de corte em TODAS as viagens do mesmo
grupo) e o troço mantido chega sempre corretamente a Portagem. Corrigir apagando só o prefixo
(sem inventar novos horários) transforma estas viagens em viagens "curtas" que começam a meio da
linha - exatamente o mesmo formato que as viagens SUB_WD_0_2xx/SUB_SAT_0_2xx já usam neste feed,
por isso não é um padrão estranho para os dados.

Uma primeira versão deste script apagava as 41 viagens inteiras - preferível corrigir o prefixo e
manter o resto (mais fiel à frequência real). Se essa primeira versão já correu (as 41 viagens já
não existem em data/metrobus/ nem em data/metrobus_fase2/), corre `git show` para recuperar a
versão original (ainda com o bug, mas completa) de HEAD antes de aplicar a correção - por isso
este script precisa de correr dentro de um repositório git com HEAD:data/metrobus/stop_times.txt
ainda a conter estas viagens (não commitar a versão apagada antes de correr esta versão).

Afeta tanto data/metrobus/ (dados antigos/atuais) como data/metrobus_fase2/ (extensão) - as
viagens EXT_* geradas para a fase 2 não têm este problema (confirmado: 0 delas aparecem na
lista).

Corre uma vez, a partir da raiz do repo:
    python scripts/fix_metrobus_scrambled_trips.py
"""
from __future__ import annotations

import csv
import io
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASETS = ["metrobus", "metrobus_fase2"]


def _to_seconds(hhmmss: str) -> int:
    h, m, s = (int(part) for part in hhmmss.split(":"))
    return h * 3600 + m * 60 + s


def _read_rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def _read_rows_from_git_head(relative_path: str) -> list[dict]:
    """Conteúdo de um ficheiro tal como está em HEAD (para recuperar viagens já apagadas por uma
    execução anterior deste script - ver docstring do módulo)."""
    text = subprocess.run(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        encoding="utf-8",
    ).stdout
    return list(csv.DictReader(io.StringIO(text)))


def _write_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _longest_clean_tail(rows: list[dict]) -> list[dict]:
    """Maior sufixo (por stop_sequence) em que arrival_time nunca decresce - ver docstring do
    módulo. `rows` já vem ordenado por stop_sequence."""
    times = [_to_seconds(r["arrival_time"]) for r in rows]
    cut = len(rows) - 1
    while cut > 0 and times[cut - 1] <= times[cut]:
        cut -= 1
    tail = rows[cut:]
    return [
        {**r, "stop_sequence": i}
        for i, r in enumerate(tail, start=1)
    ]


def _find_scrambled_trip_ids(rows: list[dict]) -> set[str]:
    by_trip: dict[str, list[dict]] = {}
    for row in rows:
        by_trip.setdefault(row["trip_id"], []).append(row)

    bad: set[str] = set()
    for trip_id, trip_rows in by_trip.items():
        trip_rows = sorted(trip_rows, key=lambda r: int(r["stop_sequence"]))
        times = [_to_seconds(r["arrival_time"]) for r in trip_rows]
        if any(later < earlier for earlier, later in zip(times, times[1:])):
            bad.add(trip_id)
    return bad


def main() -> None:
    # Fonte de recuperação: o tronco tal como está em HEAD (usado se uma execução anterior deste
    # script já tiver apagado a viagem de algum dos datasets - ver docstring do módulo).
    recovery_stop_time_rows = _read_rows_from_git_head("data/metrobus/stop_times.txt")
    recovery_trip_rows = _read_rows_from_git_head("data/metrobus/trips.txt")
    recovery_st_by_trip: dict[str, list[dict]] = {}
    for row in recovery_stop_time_rows:
        recovery_st_by_trip.setdefault(row["trip_id"], []).append(row)
    recovery_trips_by_id = {row["trip_id"]: row for row in recovery_trip_rows}

    for dataset in DATASETS:
        data_dir = REPO_ROOT / "data" / dataset
        stop_times_path = data_dir / "stop_times.txt"
        trips_path = data_dir / "trips.txt"

        st_fields, st_rows = _read_rows(stop_times_path)
        tr_fields, tr_rows = _read_rows(trips_path)

        st_by_trip: dict[str, list[dict]] = {}
        for row in st_rows:
            st_by_trip.setdefault(row["trip_id"], []).append(row)
        tr_by_id = {row["trip_id"]: row for row in tr_rows}

        scrambled = _find_scrambled_trip_ids(st_rows)

        # Viagens já apagadas por uma execução antiga deste script: presentes no recovery
        # (data/metrobus), mas já não neste dataset.
        missing = {
            tid
            for tid in _find_scrambled_trip_ids(recovery_stop_time_rows)
            if tid not in st_by_trip
        }

        to_fix = scrambled | missing
        print(f"--- {dataset}: {len(scrambled)} por corrigir + {len(missing)} a repor = {len(to_fix)} ---")
        if not to_fix:
            continue

        new_st_rows = [row for row in st_rows if row["trip_id"] not in to_fix]
        new_tr_rows = [row for row in tr_rows if row["trip_id"] not in to_fix]

        for trip_id in sorted(to_fix):
            source_rows = st_by_trip.get(trip_id) or recovery_st_by_trip[trip_id]
            source_rows = sorted(source_rows, key=lambda r: int(r["stop_sequence"]))
            fixed_rows = _longest_clean_tail(source_rows)
            new_st_rows.extend(fixed_rows)

            trip_meta = tr_by_id.get(trip_id) or recovery_trips_by_id[trip_id]
            new_tr_rows.append(trip_meta)

        _write_rows(stop_times_path, st_fields, new_st_rows)
        _write_rows(trips_path, tr_fields, new_tr_rows)
        print(f"  {len(to_fix)} viagens corrigidas (prefixo com horários errados removido, resto mantido).")


if __name__ == "__main__":
    main()

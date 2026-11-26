"""Diferenças de rede SMTUC entre dois cenários, linha a linha (N1.3).

Compara o SMTUC de dois cenários, cada um no seu dia de referência. Na narrativa da apresentação é
o horário Ep212 contra o Ep225 do Como Vou, com o mesmo metro e o mesmo dia (cenários
fase2_ep212 -> fase2, config.NETWORK_DIFF_PAIRS). Só olha para a OFERTA SMTUC (linhas, paragens
servidas, partidas); o overlap de cada linha com o metro vem do cache de métricas de cada
cenário e junta-se à parte (`add_line_metrics`).

- Linha = route_short_name (`overlap_db.line_to_route_ids`, a regra do resto do projeto).
- Paragem física = stop_code quando o feed o tem: o Ep225 renumerou os stop_id (o novo stop_id é
  o stop_code antigo), mas o stop_code manteve-se (1510 das 1519 paragens do Ep212, no mesmo
  sítio). Sem stop_code usa-se o stop_id.
- Só contam viagens ativas no dia (`active_service_ids`): uma linha que só circula ao fim de
  semana não aparece num dia útil.

Estado de cada linha (coluna "estado", ordem de STATUS_ORDER):
- "cortada" / "nova": só existe antes / só existe depois;
- "renumerada": uma linha cortada e uma nova que servem quase as mesmas paragens (semelhança de
  Jaccard >= RENUMBER_MIN_JACCARD), emparelhadas pela maior semelhança; cada linha só entra num par;
- "percurso alterado": existe nos dois e passa a servir (ou deixa de servir) pelo menos
  ROUTE_CHANGE_MIN_STOPS paragens que o outro lado não tem por perto;
- "ajuste de paragens": diferenças menores - menos de ROUTE_CHANGE_MIN_STOPS paragens retiradas
  ou novas, e/ou paragens trocadas por outras a <= STOP_MOVE_MAX_M (a mesma paragem com outro
  código - ex.: a reorganização das paragens da Manutenção, Praça da República e Loja do
  Cidadão em setembro de 2026);
- "só horário": mesmas paragens, partidas diferentes (nº de viagens ou horas de partida);
- "igual".
As contagens (mantidas / deslocadas / retiradas / novas) vão sempre na tabela, para o limiar
nunca esconder o tamanho de uma mudança.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from gtfs_processing.geo import haversine_m
from gtfs_processing.gtfs_probe import active_service_ids
from overlap.overlap_db import line_to_route_ids

RENUMBER_MIN_JACCARD = 0.6
STOP_MOVE_MAX_M = 150.0
ROUTE_CHANGE_MIN_STOPS = 4
STATUS_ORDER = ("cortada", "renumerada", "nova", "percurso alterado", "ajuste de paragens", "só horário", "igual")

Coords = dict[str, tuple[float, float]]

# Colunas do cache de métricas por linha (overlap_db) juntadas a cada lado da comparação.
LINE_METRIC_COLUMNS = ("line_extension_m", "overlap_extension_m", "overlap_pct", "temporal_overlaps_count")


@dataclass(frozen=True)
class LineProfile:
    """Oferta de uma linha num dia: viagens, paragens físicas servidas e partidas."""

    line: str
    name: str
    trips: int
    stops: frozenset[str]
    departures: tuple[int, ...]  # segundos da partida na 1.ª paragem de cada viagem, ordenados


def line_sort_key(line: object) -> tuple[float, str]:
    """Ordem natural das linhas: 2, 5T, 12, 100E (prefixo numérico, depois o texto)."""
    text = str(line)
    match = re.match(r"\d+", text)
    return (float(match.group()) if match else float("inf"), text)


def _stop_keys(gtfs) -> pd.Series:
    """stop_id -> paragem física (stop_code; "id:<stop_id>" se o feed não tiver código)."""
    stops = gtfs.stops
    ids = stops["stop_id"].astype(str)
    if "stop_code" in stops.columns:
        codes = stops["stop_code"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
        missing = codes.isin(["", "nan", "None", "<NA>"])
        keys = codes.where(~missing, "id:" + ids)
    else:
        keys = "id:" + ids
    return pd.Series(keys.to_numpy(), index=ids.to_numpy())


def stop_coordinates(gtfs) -> Coords:
    """Paragem física (a mesma chave dos perfis) -> (lat, lon); a 1.ª ocorrência de cada chave."""
    keys = _stop_keys(gtfs)
    stops = gtfs.stops.assign(_key=gtfs.stops["stop_id"].astype(str).map(keys)).dropna(subset=["stop_lat", "stop_lon"])
    stops = stops.drop_duplicates("_key")
    return {
        str(k): (float(lat), float(lon))
        for k, lat, lon in zip(stops["_key"], stops["stop_lat"].astype(float), stops["stop_lon"].astype(float))
    }


def _moved_stop_pairs(removed: set[str], added: set[str], coords_before: Coords, coords_after: Coords,
                      max_m: float) -> int:
    """Quantas paragens retiradas têm uma paragem nova a <= max_m (pares 1-para-1, as mais próximas
    primeiro). Sem coordenadas não há pares."""
    rem = [k for k in sorted(removed) if k in coords_before]
    add = [k for k in sorted(added) if k in coords_after]
    if not rem or not add:
        return 0
    lat_r = np.array([coords_before[k][0] for k in rem])[:, None]
    lon_r = np.array([coords_before[k][1] for k in rem])[:, None]
    lat_a = np.array([coords_after[k][0] for k in add])[None, :]
    lon_a = np.array([coords_after[k][1] for k in add])[None, :]
    dist = haversine_m(lat_r, lon_r, lat_a, lon_a)
    used_r: set[int] = set()
    used_a: set[int] = set()
    for flat in np.argsort(dist, axis=None, kind="stable"):
        i, j = divmod(int(flat), len(add))
        if dist[i, j] > max_m:
            break
        if i in used_r or j in used_a:
            continue
        used_r.add(i)
        used_a.add(j)
    return len(used_r)


def line_profiles(gtfs, day: date) -> dict[str, LineProfile]:
    """Perfil de cada linha com viagens ativas em `day` (as outras não aparecem)."""
    active = active_service_ids(gtfs, day)
    route_to_line = {str(rid): line for line, rids in line_to_route_ids(gtfs).items() for rid in rids}
    trips = gtfs.trips[gtfs.trips["service_id"].astype(str).isin(active)][["trip_id", "route_id"]].copy()
    if trips.empty:
        return {}
    trips["line"] = trips["route_id"].astype(str).map(route_to_line)

    st = gtfs.stop_times[gtfs.stop_times["trip_id"].isin(trips["trip_id"])][
        ["trip_id", "stop_id", "stop_sequence", "departure_seconds"]
    ].merge(trips[["trip_id", "line"]], on="trip_id")
    st["stop_key"] = st["stop_id"].astype(str).map(_stop_keys(gtfs))
    first = st.loc[st.groupby("trip_id")["stop_sequence"].idxmin(), ["line", "departure_seconds"]]
    departures = first.groupby("line")["departure_seconds"].apply(lambda s: tuple(sorted(int(x) for x in s)))

    names: dict[str, str] = {}
    if "route_long_name" in gtfs.routes.columns:
        named = trips.merge(gtfs.routes[["route_id", "route_long_name"]].astype({"route_id": str}), on="route_id", how="left")
        for line, grp in named.groupby("line"):
            values = grp["route_long_name"].dropna().astype(str)
            names[line] = values.mode().iloc[0] if not values.empty else ""

    profiles: dict[str, LineProfile] = {}
    for line, grp in st.groupby("line"):
        profiles[str(line)] = LineProfile(
            line=str(line),
            name=names.get(line, ""),
            trips=int(grp["trip_id"].nunique()),
            stops=frozenset(grp["stop_key"].dropna().astype(str)),
            departures=departures.get(line, ()),
        )
    return profiles


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if (a or b) else 1.0


def _row(before: LineProfile | None, after: LineProfile | None, status: str, moved: int = 0) -> dict[str, object]:
    stops_b = before.stops if before else frozenset()
    stops_a = after.stops if after else frozenset()
    return {
        "linha_antes": before.line if before else "",
        "linha_depois": after.line if after else "",
        "estado": status,
        "nome_antes": before.name if before else "",
        "nome_depois": after.name if after else "",
        "viagens_antes": before.trips if before else 0,
        "viagens_depois": after.trips if after else 0,
        "mesmas_partidas": bool(before and after and before.departures == after.departures),
        "paragens_antes": len(stops_b),
        "paragens_depois": len(stops_a),
        "paragens_mantidas": len(stops_b & stops_a),
        "paragens_deslocadas": moved,
        "paragens_retiradas": len(stops_b - stops_a) - moved,
        "paragens_novas": len(stops_a - stops_b) - moved,
        "semelhanca_paragens": round(jaccard(stops_b, stops_a), 4) if (before and after) else 0.0,
    }


def compare_networks(
    before: dict[str, LineProfile],
    after: dict[str, LineProfile],
    coords_before: Coords | None = None,
    coords_after: Coords | None = None,
    renumber_min_jaccard: float = RENUMBER_MIN_JACCARD,
    stop_move_max_m: float = STOP_MOVE_MAX_M,
    route_change_min_stops: int = ROUTE_CHANGE_MIN_STOPS,
) -> pd.DataFrame:
    """Uma linha por linha (ou par renumerado), com o estado e as contagens; ordenada pelo estado
    (STATUS_ORDER) e depois pela linha. Sem coordenadas (`coords_*`) nenhuma paragem conta como
    deslocada: todas as diferenças de paragens são percurso alterado."""
    coords_before = coords_before or {}
    coords_after = coords_after or {}
    only_before = sorted(set(before) - set(after), key=line_sort_key)
    only_after = sorted(set(after) - set(before), key=line_sort_key)
    common = sorted(set(before) & set(after), key=line_sort_key)

    # Renumerações: pares (cortada, nova) por semelhança decrescente; desempate pela ordem das linhas.
    candidates = sorted(
        ((jaccard(before[b].stops, after[a].stops), b, a) for b in only_before for a in only_after),
        key=lambda c: (-c[0], line_sort_key(c[1]), line_sort_key(c[2])),
    )
    paired_b: set[str] = set()
    paired_a: set[str] = set()
    rows: list[dict[str, object]] = []
    for similarity, b, a in candidates:
        if similarity < renumber_min_jaccard:
            break
        if b in paired_b or a in paired_a:
            continue
        paired_b.add(b)
        paired_a.add(a)
        rows.append(_row(before[b], after[a], "renumerada"))

    for line in common:
        b, a = before[line], after[line]
        removed, added = set(b.stops - a.stops), set(a.stops - b.stops)
        moved = _moved_stop_pairs(removed, added, coords_before, coords_after, stop_move_max_m)
        unmatched = (len(removed) - moved) + (len(added) - moved)
        if unmatched >= route_change_min_stops:
            status = "percurso alterado"
        elif removed or added:
            status = "ajuste de paragens"
        elif b.departures != a.departures:
            status = "só horário"
        else:
            status = "igual"
        rows.append(_row(b, a, status, moved))
    rows += [_row(before[b], None, "cortada") for b in only_before if b not in paired_b]
    rows += [_row(None, after[a], "nova") for a in only_after if a not in paired_a]

    df = pd.DataFrame(rows, columns=list(_row(None, None, "").keys()))
    order = {status: i for i, status in enumerate(STATUS_ORDER)}
    df["_ordem"] = df["estado"].map(order)
    df["_linha"] = [line_sort_key(b or a) for b, a in zip(df["linha_antes"], df["linha_depois"])]
    return df.sort_values(["_ordem", "_linha"], kind="stable").drop(columns=["_ordem", "_linha"]).reset_index(drop=True)


def add_line_metrics(diff: pd.DataFrame, metrics_before: pd.DataFrame | None, metrics_after: pd.DataFrame | None) -> pd.DataFrame:
    """Junta LINE_METRIC_COLUMNS do cache de métricas de cada cenário (sufixos _antes/_depois),
    pela linha de cada lado. Linhas sem métricas ficam vazias (NaN), nunca a zero."""
    out = diff.copy()
    for side, metrics in (("antes", metrics_before), ("depois", metrics_after)):
        cols = [c for c in LINE_METRIC_COLUMNS if metrics is not None and c in metrics.columns]
        for col in LINE_METRIC_COLUMNS:
            out[f"{col}_{side}"] = float("nan")
        if not cols:
            continue
        by_line = metrics.assign(line=metrics["line"].astype(str)).drop_duplicates("line").set_index("line")[cols]
        for col in cols:
            out[f"{col}_{side}"] = pd.to_numeric(out[f"linha_{side}"].map(by_line[col]), errors="coerce")
    return out


def load_line_changes(path: str | Path) -> pd.DataFrame:
    """Avisos de alterações de linhas (ex.: data/smtuc_alteracoes_2026.csv), uma linha de rede por
    linha da tabela (a coluna "linhas" separada por ';')."""
    changes = pd.read_csv(path, dtype=str).fillna("")
    changes["linha"] = changes["linhas"].str.split(";")
    return changes.explode("linha").assign(linha=lambda d: d["linha"].str.strip()).reset_index(drop=True)


def annotate_line_changes(diff: pd.DataFrame, changes: pd.DataFrame | None) -> pd.DataFrame:
    """Coluna "aviso" ("<período> (<dd/mm/aaaa>)", vários separados por '; ') e "aviso_fonte"
    (URLs), para as linhas de cada lado que aparecem nos avisos."""
    out = diff.copy()
    out["aviso"] = ""
    out["aviso_fonte"] = ""
    if changes is None or changes.empty:
        return out
    by_line: dict[str, list[pd.Series]] = {}
    for _, change in changes.iterrows():
        by_line.setdefault(change["linha"], []).append(change)
    labels, sources = [], []
    for b, a in zip(out["linha_antes"], out["linha_depois"]):
        found = []
        for line in dict.fromkeys(x for x in (b, a) if x):
            found += by_line.get(line, [])
        unique = list({(c["periodo"], c["data_vigor"], c["fonte"]): c for c in found}.values())
        labels.append("; ".join(f"{c['periodo']} ({_fmt_iso(c['data_vigor'])})" for c in unique))
        sources.append(" ".join(c["fonte"] for c in unique))
    out["aviso"] = labels
    out["aviso_fonte"] = sources
    return out


def _fmt_iso(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def summarize(diff: pd.DataFrame) -> dict[str, object]:
    """Contagens por estado e totais (viagens no dia; extensão a par do metro, se juntada)."""
    counts = {status: int((diff["estado"] == status).sum()) for status in STATUS_ORDER}
    summary: dict[str, object] = {
        "estados": counts,
        "linhas_antes": int((diff["linha_antes"] != "").sum()),
        "linhas_depois": int((diff["linha_depois"] != "").sum()),
        "viagens_antes": int(diff["viagens_antes"].sum()),
        "viagens_depois": int(diff["viagens_depois"].sum()),
    }
    for side in ("antes", "depois"):
        col = f"overlap_extension_m_{side}"
        if col in diff.columns:
            summary[f"overlap_extension_m_{side}"] = float(pd.to_numeric(diff[col], errors="coerce").sum())
    return summary

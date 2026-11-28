"""Redundância autocarro x metro, viagem a viagem (N2.1): quanto serviço SMTUC corre a par do metro.

A regra de "a par do metro" é a MESMA da extensão a par do metro das métricas por linha
(`overlap_db._route_direction_summaries`): um troço entre duas paragens consecutivas conta quando
as DUAS ficam a <= velocidade a pé x SPATIAL_OVERLAP_WALK_MIN de uma estação do metro. A diferença
é a unidade: a extensão mede o percurso representativo de cada sentido (km de linha); aqui somam-se
TODAS as viagens do dia de referência, cada uma com as suas paragens (autocarros·km e
autocarros·hora). É esta a medida do desperdício: o mesmo troço servido 60 vezes pesa 60 vezes.

Cada troço a par do metro é também atribuído a um CORREDOR do metro: as estações mais próximas das
suas duas pontas (a mesma estação nas duas pontas = troço junto a essa estação). As plataformas
"(asc)"/"(desc)" do NeTEx da fase 2 contam como a mesma estação.

Mesmas linhas que as métricas por linha (número público < 100). Paragens sem coordenadas saem da
sequência (os vizinhos passam a ser consecutivos), como no percurso representativo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from config import SPATIAL_OVERLAP_WALK_MIN, WALK_SPEED_M_MIN
from gtfs_processing.geo import haversine_m
from gtfs_processing.gtfs import load_gtfs_cached
from gtfs_processing.gtfs_probe import active_service_ids
from gtfs_processing.scenarios import Scenario, get_scenario, scenario_reference_day
from overlap.overlap_db import _line_numeric_prefix, line_to_route_ids

_PLATFORM_SUFFIX = re.compile(r"\s*\((?:asc|desc)\)\s*$", re.IGNORECASE)

SEGMENT_COLUMNS = (
    "line", "trip_id", "from_stop_id", "to_stop_id", "length_m", "minutes", "overlap", "station_a", "station_b",
)
LINE_COLUMNS = (
    "line", "viagens", "km", "km_metro", "pct_km_metro", "horas", "horas_metro", "viagens_com_troco_metro",
)
CORRIDOR_COLUMNS = ("station_a", "station_b", "km_metro", "horas_metro", "passagens", "linhas")
LINE_CORRIDOR_COLUMNS = ("line", "station_a", "station_b", "km_metro", "horas_metro", "passagens")


def station_name(stop_name: object) -> str:
    """Nome da estação sem o sufixo de plataforma: "Câmara (desc)" -> "Câmara"."""
    return _PLATFORM_SUFFIX.sub("", str(stop_name)).strip()


def _metro_stations(gtfs_metro) -> pd.DataFrame:
    stops = gtfs_metro.stops.dropna(subset=["stop_lat", "stop_lon"])
    return pd.DataFrame(
        {
            "station": stops["stop_name"].map(station_name).to_numpy(),
            "lat": stops["stop_lat"].astype(float).to_numpy(),
            "lon": stops["stop_lon"].astype(float).to_numpy(),
        }
    )


def bus_stop_overlap(gtfs_bus, gtfs_metro, catchment_m: float) -> pd.DataFrame:
    """Por paragem de autocarro com coordenadas: distância à estação do metro mais próxima, essa
    estação e se fica dentro de `catchment_m`. Índice = stop_id."""
    stops = gtfs_bus.stops.dropna(subset=["stop_lat", "stop_lon"])
    stops = stops.assign(stop_id=stops["stop_id"].astype(str)).drop_duplicates("stop_id")
    metro = _metro_stations(gtfs_metro)
    if stops.empty or metro.empty:
        return pd.DataFrame(columns=["distance_m", "station", "overlap"], index=pd.Index([], name="stop_id"))
    lat = stops["stop_lat"].astype(float).to_numpy()
    lon = stops["stop_lon"].astype(float).to_numpy()
    dist = haversine_m(lat[:, None], lon[:, None], metro["lat"].to_numpy()[None, :], metro["lon"].to_numpy()[None, :])
    nearest = dist.argmin(axis=1)
    best = dist[np.arange(len(stops)), nearest]
    return pd.DataFrame(
        {"distance_m": best, "station": metro["station"].to_numpy()[nearest], "overlap": best <= catchment_m},
        index=pd.Index(stops["stop_id"].astype(str).to_numpy(), name="stop_id"),
    )


def _active_trips_by_line(gtfs_bus, day: date) -> pd.DataFrame:
    active = active_service_ids(gtfs_bus, day)
    route_line = {route: line for line, routes in line_to_route_ids(gtfs_bus).items() for route in routes}
    trips = gtfs_bus.trips[gtfs_bus.trips["service_id"].isin(active)][["trip_id", "route_id"]]
    trips = trips.assign(line=trips["route_id"].map(route_line))
    prefix = trips["line"].map(_line_numeric_prefix)
    return trips[trips["line"].notna() & prefix.notna() & (prefix < 100)][["trip_id", "line"]]


def trip_segments(gtfs_bus, gtfs_metro, day: date, catchment_m: float | None = None) -> pd.DataFrame:
    """Um troço por par de paragens consecutivas de cada viagem com serviço em `day`. Colunas
    SEGMENT_COLUMNS; station_a/station_b (ordenadas) só nos troços a par do metro."""
    if catchment_m is None:
        catchment_m = WALK_SPEED_M_MIN * SPATIAL_OVERLAP_WALK_MIN
    trips = _active_trips_by_line(gtfs_bus, day)
    flags = bus_stop_overlap(gtfs_bus, gtfs_metro, catchment_m)
    st = gtfs_bus.stop_times[["trip_id", "stop_id", "stop_sequence", "arrival_seconds", "departure_seconds"]]
    st = st[st["trip_id"].isin(trips["trip_id"]) & st["stop_id"].astype(str).isin(flags.index)]
    if st.empty:
        return pd.DataFrame(columns=list(SEGMENT_COLUMNS))
    st = st.assign(_seq=pd.to_numeric(st["stop_sequence"]), stop_id=st["stop_id"].astype(str))
    st = st.sort_values(["trip_id", "_seq"], kind="mergesort").reset_index(drop=True)
    coords = gtfs_bus.stops.dropna(subset=["stop_lat", "stop_lon"]).assign(stop_id=lambda s: s["stop_id"].astype(str))
    coords = coords.drop_duplicates("stop_id").set_index("stop_id")
    lat = coords.loc[st["stop_id"], "stop_lat"].astype(float).to_numpy()
    lon = coords.loc[st["stop_id"], "stop_lon"].astype(float).to_numpy()

    same_trip = (st["trip_id"].to_numpy()[:-1] == st["trip_id"].to_numpy()[1:])
    a = np.flatnonzero(same_trip)
    b = a + 1
    overlap_stop = flags.loc[st["stop_id"], "overlap"].to_numpy(dtype=bool)
    station = flags.loc[st["stop_id"], "station"].to_numpy()
    overlap = overlap_stop[a] & overlap_stop[b]
    s1, s2 = station[a], station[b]
    first = np.where(s1 <= s2, s1, s2)
    second = np.where(s1 <= s2, s2, s1)
    seg = pd.DataFrame(
        {
            "trip_id": st["trip_id"].to_numpy()[a],
            "from_stop_id": st["stop_id"].to_numpy()[a],
            "to_stop_id": st["stop_id"].to_numpy()[b],
            "length_m": haversine_m(lat[a], lon[a], lat[b], lon[b]),
            "minutes": (st["arrival_seconds"].to_numpy()[b] - st["departure_seconds"].to_numpy()[a]) / 60.0,
            "overlap": overlap,
            "station_a": np.where(overlap, first, ""),
            "station_b": np.where(overlap, second, ""),
        }
    )
    seg = seg.merge(trips, on="trip_id", how="left")
    return seg[list(SEGMENT_COLUMNS)]


def redundancy_by_line(segments: pd.DataFrame) -> pd.DataFrame:
    """Por linha: viagens no dia, autocarros·km e autocarros·hora (totais e a par do metro)."""
    if segments.empty:
        return pd.DataFrame(columns=list(LINE_COLUMNS))
    seg = segments.assign(
        _m_metro=segments["length_m"].where(segments["overlap"], 0.0),
        _min_metro=segments["minutes"].where(segments["overlap"], 0.0),
    )
    per_trip = seg.groupby(["line", "trip_id"]).agg(
        m=("length_m", "sum"), m_metro=("_m_metro", "sum"), mins=("minutes", "sum"), mins_metro=("_min_metro", "sum"),
    )
    g = per_trip.groupby("line")
    out = pd.DataFrame(
        {
            "viagens": g.size(),
            "km": g["m"].sum() / 1000.0,
            "km_metro": g["m_metro"].sum() / 1000.0,
            "horas": g["mins"].sum() / 60.0,
            "horas_metro": g["mins_metro"].sum() / 60.0,
            "viagens_com_troco_metro": g["m_metro"].apply(lambda s: int((s > 0).sum())),
        }
    )
    out["pct_km_metro"] = np.where(out["km"] > 0, 100.0 * out["km_metro"] / out["km"], 0.0)
    out = out.reset_index().sort_values(["km_metro", "line"], ascending=[False, True], kind="mergesort")
    return out[list(LINE_COLUMNS)].reset_index(drop=True)


def redundancy_by_corridor(segments: pd.DataFrame) -> pd.DataFrame:
    """Por corredor do metro (par de estações): autocarros·km e ·hora a par dele, nº de passagens
    (troços de viagens) e linhas (separadas por ";")."""
    seg = segments[segments["overlap"]] if not segments.empty else segments
    if seg.empty:
        return pd.DataFrame(columns=list(CORRIDOR_COLUMNS))
    g = seg.groupby(["station_a", "station_b"])
    out = pd.DataFrame(
        {
            "km_metro": g["length_m"].sum() / 1000.0,
            "horas_metro": g["minutes"].sum() / 60.0,
            "passagens": g.size(),
            "linhas": g["line"].apply(lambda s: ";".join(sorted(set(map(str, s)), key=_line_key))),
        }
    ).reset_index()
    out = out.sort_values(["km_metro", "station_a", "station_b"], ascending=[False, True, True], kind="mergesort")
    return out[list(CORRIDOR_COLUMNS)].reset_index(drop=True)


def redundancy_by_line_corridor(segments: pd.DataFrame) -> pd.DataFrame:
    """Por linha e corredor do metro: autocarros·km, ·hora e passagens a par dele (N3.4: a
    capacidade de uma linha nos corredores das estações novas)."""
    seg = segments[segments["overlap"]] if not segments.empty else segments
    if seg.empty:
        return _empty_line_corridor()
    g = seg.groupby(["line", "station_a", "station_b"])
    out = pd.DataFrame(
        {"km_metro": g["length_m"].sum() / 1000.0, "horas_metro": g["minutes"].sum() / 60.0, "passagens": g.size()}
    ).reset_index()
    out = out.sort_values(["line", "km_metro", "station_a", "station_b"], ascending=[True, False, True, True], kind="mergesort")
    return out[list(LINE_CORRIDOR_COLUMNS)].reset_index(drop=True)


def _empty_line_corridor() -> pd.DataFrame:
    return pd.DataFrame(columns=list(LINE_CORRIDOR_COLUMNS))


def _line_key(line: str) -> tuple[float, str]:
    prefix = _line_numeric_prefix(line)
    return (prefix if prefix is not None else float("inf"), line)


@dataclass(frozen=True)
class Redundancy:
    scenario: str
    day: date
    by_line: pd.DataFrame
    by_corridor: pd.DataFrame
    by_line_corridor: pd.DataFrame = field(default_factory=_empty_line_corridor)

    def totals(self) -> dict[str, float]:
        bl = self.by_line
        km = float(bl["km"].sum())
        km_metro = float(bl["km_metro"].sum())
        return {
            "linhas": int(len(bl)),
            "linhas_com_troco_metro": int((bl["km_metro"] > 0).sum()),
            "viagens": int(bl["viagens"].sum()),
            "km": km,
            "km_metro": km_metro,
            "pct_km_metro": 100.0 * km_metro / km if km > 0 else 0.0,
            "horas": float(bl["horas"].sum()),
            "horas_metro": float(bl["horas_metro"].sum()),
        }


def scenario_redundancy(scenario: str | Scenario | None = None, day: date | None = None) -> Redundancy:
    """Redundância do cenário no seu dia de referência (ou em `day`, ex.: sábado da semana-tipo)."""
    sc = get_scenario(scenario)
    day = day or scenario_reference_day(sc)
    segments = trip_segments(load_gtfs_cached(sc.smtuc), load_gtfs_cached(sc.metro), day)
    return Redundancy(sc.name, day, redundancy_by_line(segments), redundancy_by_corridor(segments),
                      redundancy_by_line_corridor(segments))


# --------------------------------------------------------------------------- desperdício (N2.2)


@dataclass(frozen=True)
class WasteFactors:
    """Fatores de conversão autocarros·km -> CO2 (config.WASTE_*; fontes em reports/estatisticas.txt)."""

    fleet_total: int
    fleet_electric: int
    diesel_l_per_km: float
    electric_kwh_per_km: float
    diesel_kg_co2_per_l: float
    grid_kg_co2_per_kwh: float
    weeks_per_year: int

    @property
    def electric_share(self) -> float:
        return self.fleet_electric / self.fleet_total

    @property
    def kg_co2_per_km(self) -> float:
        """Média da frota: a parte a combustão em gasóleo, a elétrica na rede (frota repartida por igual)."""
        e = self.electric_share
        return (1 - e) * self.diesel_l_per_km * self.diesel_kg_co2_per_l + e * self.electric_kwh_per_km * self.grid_kg_co2_per_kwh


def waste_factors() -> WasteFactors:
    import config

    factors = WasteFactors(
        fleet_total=int(config.WASTE_FLEET_TOTAL),
        fleet_electric=int(config.WASTE_FLEET_ELECTRIC),
        diesel_l_per_km=float(config.WASTE_DIESEL_L_PER_KM),
        electric_kwh_per_km=float(config.WASTE_ELECTRIC_KWH_PER_KM),
        diesel_kg_co2_per_l=float(config.WASTE_DIESEL_KG_CO2_PER_L),
        grid_kg_co2_per_kwh=float(config.WASTE_GRID_KG_CO2_PER_KWH),
        weeks_per_year=int(config.WASTE_WEEKS_PER_YEAR),
    )
    if not 0 <= factors.fleet_electric <= factors.fleet_total or factors.fleet_total <= 0:
        raise ValueError(f"frota inválida em config.WASTE_FLEET_*: {factors.fleet_electric}/{factors.fleet_total}")
    return factors


WEEKDAYS_PER_WEEK = 5
WEEK_COLUMNS = ("tipo", "dia", "peso", "viagens", "km", "km_metro", "horas_metro")
_SEARCH_DAYS = 28


def _in_period(gtfs, day: date) -> bool:
    from gtfs_processing.gtfs_probe import feed_service_period

    period = feed_service_period(gtfs)
    if period is None:
        return True
    ymd = day.year * 10000 + day.month * 100 + day.day
    return period[0] <= ymd <= period[1]


def nearest_weekday(gtfs, day: date, weekday: int) -> date:
    """O dia com o `weekday` pedido (5 = sábado, 6 = domingo) mais próximo de `day`, dentro do
    período do feed e que não seja feriado; empate -> o seguinte. Levanta ValueError se não houver
    nenhum a <= 4 semanas."""
    from gtfs_processing.gtfs_probe import is_public_holiday

    for offset in range(1, _SEARCH_DAYS + 1):
        for candidate in (day + timedelta(days=offset), day - timedelta(days=offset)):
            if candidate.weekday() == weekday and not is_public_holiday(candidate) and _in_period(gtfs, candidate):
                return candidate
    raise ValueError(f"nenhum dia {weekday} (0 = 2.ª) fora de feriados no período do feed a <= {_SEARCH_DAYS} dias de {day}")


def typical_week(gtfs, reference_day: date) -> list[tuple[str, date, int]]:
    """Semana-tipo: (tipo, dia, peso). O dia útil é o dia de referência (peso 5); o sábado e o
    domingo são os mais próximos dele dentro do período do feed, fora de feriados (peso 1 cada).
    O dia de referência tem de ser um dia útil que não seja feriado."""
    from gtfs_processing.gtfs_probe import is_public_holiday

    if reference_day.weekday() >= 5 or is_public_holiday(reference_day):
        raise ValueError(f"o dia de referência {reference_day} não é um dia útil: a semana-tipo parte de um dia útil")
    return [
        ("dia útil", reference_day, WEEKDAYS_PER_WEEK),
        ("sábado", nearest_weekday(gtfs, reference_day, 5), 1),
        ("domingo", nearest_weekday(gtfs, reference_day, 6), 1),
    ]


@dataclass(frozen=True)
class Waste:
    """Desperdício de um cenário: o dia de referência, a semana-tipo e o ano estimado."""

    scenario: str
    reference: Redundancy
    week: pd.DataFrame          # WEEK_COLUMNS: dia útil, sábado e domingo, com o peso de cada um
    line_week: pd.DataFrame     # por linha: km_metro e horas_metro da semana-tipo (pesados)
    factors: WasteFactors
    # por linha e corredor (LINE_CORRIDOR_COLUMNS): a semana-tipo pesada (N3.4)
    line_corridor_week: pd.DataFrame = field(default_factory=_empty_line_corridor)

    def summary(self) -> dict[str, float]:
        f = self.factors
        ref = self.reference.totals()
        week_km = float((self.week["km_metro"] * self.week["peso"]).sum())
        week_h = float((self.week["horas_metro"] * self.week["peso"]).sum())
        return {
            "dia_km_metro": ref["km_metro"],
            "dia_horas_metro": ref["horas_metro"],
            "dia_t_co2": ref["km_metro"] * f.kg_co2_per_km / 1000.0,
            "semana_km_metro": week_km,
            "semana_horas_metro": week_h,
            "ano_km_metro": week_km * f.weeks_per_year,
            "ano_horas_metro": week_h * f.weeks_per_year,
            "ano_t_co2": week_km * f.weeks_per_year * f.kg_co2_per_km / 1000.0,
            "kg_co2_por_km": f.kg_co2_per_km,
        }

    def line_year(self) -> pd.DataFrame:
        """Por linha: ano estimado (semana-tipo x semanas por ano) em autocarros·km, ·hora e t CO2."""
        f = self.factors
        out = self.line_week.copy()
        out["ano_km_metro"] = out["km_metro"] * f.weeks_per_year
        out["ano_horas_metro"] = out["horas_metro"] * f.weeks_per_year
        out["ano_t_co2"] = out["ano_km_metro"] * f.kg_co2_per_km / 1000.0
        return out[["line", "ano_km_metro", "ano_horas_metro", "ano_t_co2"]]


def scenario_waste(scenario: str | Scenario | None = None) -> Waste:
    """Dia de referência + sábado e domingo da semana-tipo (`typical_week`), cada um com o serviço
    GTFS desse dia; ano = semana-tipo x config.WASTE_WEEKS_PER_YEAR (estimativa)."""
    sc = get_scenario(scenario)
    ref_day = scenario_reference_day(sc)
    reference = scenario_redundancy(sc, ref_day)
    rows, lines, line_corridors = [], [], []
    for kind, day, weight in typical_week(load_gtfs_cached(sc.smtuc), ref_day):
        red = reference if day == ref_day else scenario_redundancy(sc, day)
        t = red.totals()
        rows.append({"tipo": kind, "dia": day.isoformat(), "peso": weight, "viagens": t["viagens"], "km": t["km"],
                     "km_metro": t["km_metro"], "horas_metro": t["horas_metro"]})
        lines.append(red.by_line[["line", "km_metro", "horas_metro"]].assign(
            km_metro=lambda d, w=weight: d["km_metro"] * w, horas_metro=lambda d, w=weight: d["horas_metro"] * w))
        line_corridors.append(red.by_line_corridor.assign(
            km_metro=lambda d, w=weight: d["km_metro"] * w, horas_metro=lambda d, w=weight: d["horas_metro"] * w,
            passagens=lambda d, w=weight: d["passagens"] * w))
    line_week = pd.concat(lines).groupby("line", as_index=False)[["km_metro", "horas_metro"]].sum()
    line_week = line_week.sort_values(["km_metro", "line"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    keys = ["line", "station_a", "station_b"]
    line_corridor_week = pd.concat(line_corridors).groupby(keys, as_index=False)[["km_metro", "horas_metro", "passagens"]].sum()
    return Waste(sc.name, reference, pd.DataFrame(rows, columns=list(WEEK_COLUMNS)), line_week, waste_factors(),
                 line_corridor_week[list(LINE_CORRIDOR_COLUMNS)])


# --------------------------------------------------------------------------- metro novo (N3.4)


def new_stations(before: str | Scenario, after: str | Scenario) -> tuple[str, ...]:
    """Estações (sem sufixo de plataforma) do metro de `after` que não existem no de `before`."""
    def names(sc) -> set[str]:
        return set(_metro_stations(load_gtfs_cached(get_scenario(sc).metro))["station"])

    return tuple(sorted(names(after) - names(before)))


INCREASE_COLUMNS = (
    "line", "km_antes", "km_depois", "delta_km", "horas_antes", "horas_depois", "delta_horas",
    "ano_delta_horas", "ano_delta_t_co2", "horas_novas", "ano_horas_novas", "km_novos", "ano_km_novos",
    "estacoes_novas", "corredores_novos",
)


def _touches(frame: pd.DataFrame, stations: tuple[str, ...]) -> pd.Series:
    return frame["station_a"].isin(stations) | frame["station_b"].isin(stations)


def new_station_corridors(after: Waste, stations: tuple[str, ...]) -> pd.DataFrame:
    """Corredores (CORRIDOR_COLUMNS) do dia de referência de `after` com uma estação nova numa ponta."""
    corridors = after.reference.by_corridor
    return corridors[_touches(corridors, stations)].reset_index(drop=True)


def _corridor_label(a: str, b: str) -> str:
    return f"junto a {a}" if a == b else f"{a} – {b}"


def metro_extension_increase(before: Waste, after: Waste, stations: tuple[str, ...]) -> pd.DataFrame:
    """O que um metro novo (mesmo SMTUC) faz à redundância, linha a linha (INCREASE_COLUMNS):
    autocarros·km e ·hora a par do metro num dia útil antes/depois e a diferença; a diferença no ano
    estimado (semana-tipo x semanas, em horas e t CO2); e as horas nos corredores com uma estação
    nova (`stations`) numa ponta, no dia e no ano - a capacidade que passa a correr ao lado da
    linha nova -, as estações novas junto às quais a linha passa no dia útil (pela ordem de
    `stations`) e esses corredores. Entram as linhas do dia útil E da semana-tipo (uma linha só de
    fim de semana conta no ano) com alguma diferença ou horas nesses corredores; maior aumento em km
    no dia útil primeiro. Somando a coluna do ano obtém-se a diferença dos totais da semana-tipo."""
    f = after.factors
    cols = ["line", "km_metro", "horas_metro"]
    b = before.reference.by_line[cols].rename(columns={"km_metro": "km_antes", "horas_metro": "horas_antes"})
    a = after.reference.by_line[cols].rename(columns={"km_metro": "km_depois", "horas_metro": "horas_depois"})
    # Linhas da semana-tipo também (uma linha só de fim de semana não está no dia útil mas conta no ano).
    week_lines = pd.DataFrame({"line": pd.concat([before.line_week["line"], after.line_week["line"]]).unique()})
    out = b.merge(a, on="line", how="outer").merge(week_lines, on="line", how="outer")
    for col in ("km_antes", "km_depois", "horas_antes", "horas_depois"):
        out[col] = out[col].fillna(0.0).astype(float)

    def week(w: Waste, col: str):
        return out["line"].map(w.line_week.set_index("line")[col]).fillna(0.0).astype(float)

    out["delta_km"] = out["km_depois"] - out["km_antes"]
    out["delta_horas"] = out["horas_depois"] - out["horas_antes"]
    out["ano_delta_horas"] = (week(after, "horas_metro") - week(before, "horas_metro")) * f.weeks_per_year
    out["ano_delta_t_co2"] = (week(after, "km_metro") - week(before, "km_metro")) * f.weeks_per_year * f.kg_co2_per_km / 1000.0

    day_lc = after.reference.by_line_corridor
    day_new = day_lc[_touches(day_lc, stations)]
    week_lc = after.line_corridor_week
    week_new = week_lc[_touches(week_lc, stations)]
    out["horas_novas"] = out["line"].map(day_new.groupby("line")["horas_metro"].sum()).fillna(0.0).astype(float)
    out["ano_horas_novas"] = (out["line"].map(week_new.groupby("line")["horas_metro"].sum()).fillna(0.0).astype(float)
                              * f.weeks_per_year)
    out["km_novos"] = out["line"].map(day_new.groupby("line")["km_metro"].sum()).fillna(0.0).astype(float)
    out["ano_km_novos"] = (out["line"].map(week_new.groupby("line")["km_metro"].sum()).fillna(0.0).astype(float)
                           * f.weeks_per_year)
    labels = day_new.assign(_c=[_corridor_label(x, y) for x, y in zip(day_new["station_a"], day_new["station_b"])])
    by_line = labels.groupby("line")["_c"].apply(lambda s: "; ".join(dict.fromkeys(s))) if not labels.empty else pd.Series(dtype=str)
    out["corredores_novos"] = out["line"].map(by_line).fillna("")
    touched = {line: set(g["station_a"]) | set(g["station_b"]) for line, g in day_new.groupby("line")}
    out["estacoes_novas"] = out["line"].map(
        lambda line: ", ".join(s for s in stations if s in touched.get(line, set()))).fillna("")
    changed = (out["delta_km"].abs() > 1e-9) | (out["ano_delta_horas"].abs() > 1e-9) | (out["ano_delta_t_co2"].abs() > 1e-9)
    out = out[changed | (out["horas_novas"] > 0) | (out["ano_horas_novas"] > 0)]
    out = out.assign(_k=out["line"].astype(str).map(_line_key))
    out = out.sort_values(["delta_km", "_k"], ascending=[False, True], kind="mergesort")
    return out[list(INCREASE_COLUMNS)].reset_index(drop=True)

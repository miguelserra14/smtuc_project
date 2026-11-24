"""Propostas de horário da linha 54 sobre as tabelas de `overlap.transit`: desvios de fase
("otimizado"), segundo autocarro desfasado 20 min ("melhorado") e a tabela de esperas por chegada.

Lógica de cálculo - usada pelas páginas de integração (`visualizations.integration`), pela busca
de desvio (`scripts/search_phase_shift.py`) e pelos snapshots. Antes vivia dentro de
`visualizations/integration.py` com nomes privados, e o script importava-a de lá.
"""

from __future__ import annotations

import pandas as pd

from gtfs_processing.timeutil import hhmmss_to_seconds, seconds_to_hhmmss
from overlap.transit import compute_transfer_waits


def period_label(seconds: int) -> str:
    hour = int(seconds // 3600)
    if 6 <= hour < 12:
        return "manha"
    if 12 <= hour < 17:
        return "meio_dia"
    if 17 <= hour < 24:
        return "tarde_noite"
    return "fora_faixa"


def build_waits_table(schedule_df: pd.DataFrame) -> pd.DataFrame:
    """Tabela de esperas por chegada (gatilho), com a regra única de transbordo de
    `overlap.transit.compute_transfer_waits`: a partida seguinte só conta se der para lá chegar a
    pé (distância real entre paragens + margem). `wait_min` = minutos entre a chegada e a partida
    apanhada, caminhada incluída; `transfer_min` = a parte que é caminhada + margem."""
    rows: list[dict] = []
    for w in compute_transfer_waits(schedule_df):
        wait_min = w["wait_min"]
        if wait_min is None:
            class_label = "sem_ligacao"
        elif wait_min <= 10:
            class_label = "<=10"
        elif wait_min <= 15:
            class_label = "10-15"
        else:
            class_label = ">15"
        rows.append(
            {
                "metro_time": seconds_to_hhmmss(w["trigger_s"]),
                "next_bus_time": w["target_time"],
                "next_bus_line": w["target_line"],
                "wait_min": wait_min,
                "transfer_min": w["transfer_min"],
                "wait_class": class_label,
                "period": period_label(w["trigger_s"]),
            }
        )
    columns = ["metro_time", "next_bus_time", "next_bus_line", "wait_min", "transfer_min", "wait_class", "period"]
    return pd.DataFrame(rows, columns=columns)


def shift_schedule_bus_times(schedule_df: pd.DataFrame, line_value: str, shift_minutes: float) -> pd.DataFrame:
    """Devolve uma cópia de `schedule_df` com `bus_time` deslocado `shift_minutes` minutos,
    apenas nas linhas cuja `bus_line_passage` seja `line_value` - as restantes linhas (ex.: a 38
    em Portagem) ficam exatamente como estavam, porque a proposta de horário otimizado só mexe
    no ciclo da linha 54."""
    out = schedule_df.copy()
    line_col = out["bus_line_passage"] if "bus_line_passage" in out.columns else out["bus_line"]
    mask = (line_col.astype(str).str.strip() == str(line_value)) & (out["bus_time"].astype(str).str.strip() != "")
    shifted = out.loc[mask, "bus_time"].astype(str).map(
        lambda t: seconds_to_hhmmss(int(round(hhmmss_to_seconds(t) + shift_minutes * 60)))
    )
    out.loc[mask, "bus_time"] = shifted
    return out


def shift_reverse_schedule_bus_arrivals(schedule_df: pd.DataFrame, shift_minutes: float) -> pd.DataFrame:
    """Equivalente a `shift_schedule_bus_times`, mas para tabelas de `build_reverse_stop_vs_metro_table`
    - aí são as chegadas do autocarro que ficam em `metro_time_from_origin` (ver docstring dessa
    função), por isso é essa coluna que se desloca. Desloca a coluna inteira sem filtrar por
    linha: `build_reverse_stop_vs_metro_table` já é chamada com a(s) linha(s) pretendida(s), ao
    contrário do sentido direto onde uma única tabela pode combinar várias linhas na mesma
    coluna `bus_time` (ex. 54+38)."""
    out = schedule_df.copy()
    mask = out["metro_time_from_origin"].astype(str).str.strip() != ""
    shifted = out.loc[mask, "metro_time_from_origin"].astype(str).map(
        lambda t: seconds_to_hhmmss(int(round(hhmmss_to_seconds(t) + shift_minutes * 60)))
    )
    out.loc[mask, "metro_time_from_origin"] = shifted
    return out


def double_and_shift_schedule_bus_times(
    schedule_df: pd.DataFrame, line_value: str, shift_minutes: float
) -> pd.DataFrame:
    """Constrói a proposta "melhorado": simula um 2º autocarro na linha `line_value`, desfasado
    20 min do 1º (dobra a frequência de 40 para 20 min - o ciclo físico do autocarro não muda,
    só passa a ter 2 veículos a percorrê-lo em simultâneo em vez de 1), e desloca o conjunto
    (original + duplicado) por `shift_minutes` - ver `config.LINE_54_MELHORADO_PHASE_SHIFT_MIN`
    para o valor e o raciocínio por trás dele. As restantes linhas (ex.: a 38 em Portagem) ficam
    exatamente como estavam - a proposta só mexe na linha 54."""
    out = schedule_df.copy()
    line_col = out["bus_line_passage"] if "bus_line_passage" in out.columns else out["bus_line"]
    mask = (line_col.astype(str).str.strip() == str(line_value)) & (out["bus_time"].astype(str).str.strip() != "")
    base_rows = out.loc[mask]
    dup_rows = base_rows.copy()
    dup_rows["bus_time"] = dup_rows["bus_time"].astype(str).map(
        lambda t: seconds_to_hhmmss(int(round(hhmmss_to_seconds(t) + 20 * 60)) % 86400)
    )
    doubled = pd.concat([base_rows, dup_rows], ignore_index=True)
    doubled["bus_time"] = doubled["bus_time"].astype(str).map(
        lambda t: seconds_to_hhmmss(int(round(hhmmss_to_seconds(t) + shift_minutes * 60)) % 86400)
    )
    if "idx" in doubled.columns:
        doubled["idx"] = range(1, len(doubled) + 1)
    other = out.loc[~mask]
    return pd.concat([other, doubled], ignore_index=True)


def double_and_shift_reverse_schedule_bus_arrivals(schedule_df: pd.DataFrame, shift_minutes: float) -> pd.DataFrame:
    """Equivalente a `double_and_shift_schedule_bus_times`, mas para tabelas de
    `build_reverse_stop_vs_metro_table` - tal como em `shift_reverse_schedule_bus_arrivals`, é a
    coluna `metro_time_from_origin` (as chegadas de autocarro, nesta tabela invertida) que se
    duplica e desloca, sem filtrar por linha."""
    out = schedule_df.copy()
    mask = out["metro_time_from_origin"].astype(str).str.strip() != ""
    base_rows = out.loc[mask]
    dup_rows = base_rows.copy()
    dup_rows["metro_time_from_origin"] = dup_rows["metro_time_from_origin"].astype(str).map(
        lambda t: seconds_to_hhmmss(int(round(hhmmss_to_seconds(t) + 20 * 60)) % 86400)
    )
    doubled = pd.concat([base_rows, dup_rows], ignore_index=True)
    doubled["metro_time_from_origin"] = doubled["metro_time_from_origin"].astype(str).map(
        lambda t: seconds_to_hhmmss(int(round(hhmmss_to_seconds(t) + shift_minutes * 60)) % 86400)
    )
    if "idx" in doubled.columns:
        doubled["idx"] = range(1, len(doubled) + 1)
    other = out.loc[~mask]
    return pd.concat([other, doubled], ignore_index=True)

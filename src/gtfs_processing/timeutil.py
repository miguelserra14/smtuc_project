"""Horas GTFS ("HH:MM:SS", horas >= 24 para viagens depois da meia-noite) <-> segundos desde a
meia-noite do dia de serviço. Fonte ÚNICA destas conversões no projeto (antes havia 3 parsers e 3
formatadores com comportamentos diferentes - um deles devolvia 0, i.e. meia-noite, para horas
vazias ou malformadas).

Todas as funções são estritas: uma hora vazia/malformada levanta ValueError em vez de ser
silenciosamente tratada como 00:00:00.
"""

from __future__ import annotations

import pandas as pd

_HHMMSS_PATTERN = r"^\s*(\d{1,3}):([0-5]\d):([0-5]\d)\s*$"


def hhmmss_to_seconds(value: str) -> int:
    """'HH:MM:SS' (ou 'H:MM:SS'; horas podem passar das 24) -> segundos. ValueError se inválida."""
    try:
        h, m, s = (int(part) for part in str(value).strip().split(":"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Hora inválida (esperado HH:MM:SS): {value!r}") from exc
    if h < 0 or not (0 <= m < 60) or not (0 <= s < 60):
        raise ValueError(f"Hora inválida (esperado HH:MM:SS): {value!r}")
    return h * 3600 + m * 60 + s


def seconds_to_hhmmss(value: int) -> str:
    """Segundos -> 'HH:MM:SS' (sem dar a volta às 24h: 90000 -> '25:00:00')."""
    value = int(value)
    return f"{value // 3600:02d}:{value % 3600 // 60:02d}:{value % 60:02d}"


def series_hhmmss_to_seconds(values: pd.Series, what: str = "hora") -> pd.Series:
    """Versão vetorizada de `hhmmss_to_seconds` para uma coluna inteira (ex.: stop_times).

    Levanta ValueError se ALGUMA célula estiver vazia ou malformada, indicando quantas e
    exemplos. O GTFS permite horas vazias em paragens que não são pontos de controlo, mas o
    projeto não interpola horários: aceitá-las como 0 punha passagens à meia-noite.

    Só as horas DISTINTAS passam pelo regex (num stop_times há ~10-30x menos horas distintas do
    que linhas): é o que custava ~0,4 s por coluna ao carregar cada feed.
    """
    codes, uniques = pd.factorize(values.astype("string"), use_na_sentinel=True)
    parts = pd.Series(uniques, dtype="string").str.extract(_HHMMSS_PATTERN)
    bad_unique = parts.isna().any(axis=1).to_numpy()
    bad = (codes < 0) | bad_unique[codes.clip(min=0)] if len(uniques) else codes < 0
    if bad.any():
        sample = values[bad].head(5).tolist()
        raise ValueError(
            f"{int(bad.sum())} valor(es) de {what} vazio(s) ou inválido(s) (esperado HH:MM:SS); "
            f"exemplos: {sample}"
        )
    p = parts.astype("int64")
    seconds = (p[0] * 3600 + p[1] * 60 + p[2]).to_numpy()
    return pd.Series(seconds[codes], index=values.index, dtype="int64")

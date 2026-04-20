from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import OUTPUTS_INTEGRATION_DIR
from overlap.transit import (
    build_line_stop_vs_metro_table,
    build_metro_bus_connection_metrics,
)
from visualizations.io import _write_readable_plotly_html

try:
    import plotly.express as px
    import plotly.graph_objects as go
except Exception:  # pragma: no cover - optional dependency guard
    px = None
    go = None


def _safe_slug(value: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value).strip())
    while "__" in out:
        out = out.replace("__", "_")
    out = out.strip("_")
    return out or "value"


def _hhmmss_to_seconds(value: str) -> int:
    h, m, s = (int(part) for part in str(value).split(":"))
    return h * 3600 + m * 60 + s


def _seconds_to_hhmmss(value: int) -> str:
    value = int(value)
    h = value // 3600
    m = (value % 3600) // 60
    s = value % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _period_label(seconds: int) -> str:
    hour = int(seconds // 3600)
    if 6 <= hour < 12:
        return "manha"
    if 12 <= hour < 17:
        return "meio_dia"
    if 17 <= hour < 24:
        return "tarde_noite"
    return "fora_faixa"


def _build_waits_table(schedule_df: pd.DataFrame) -> pd.DataFrame:
    bus_times = sorted(
        {
            _hhmmss_to_seconds(v)
            for v in schedule_df["bus_time"].astype(str).tolist()
            if str(v).strip()
        }
    )
    metro_times = sorted(
        {
            _hhmmss_to_seconds(v)
            for v in schedule_df["metro_time_from_origin"].astype(str).tolist()
            if str(v).strip()
        }
    )

    rows: list[dict] = []
    for metro_s in metro_times:
        next_bus = next((b for b in bus_times if b >= metro_s), None)
        if next_bus is None:
            wait_min = None
            next_bus_str = ""
            class_label = "sem_ligacao"
        else:
            wait_min = round((next_bus - metro_s) / 60.0, 2)
            next_bus_str = _seconds_to_hhmmss(next_bus)
            if wait_min <= 10:
                class_label = "<=10"
            elif wait_min <= 15:
                class_label = "10-15"
            else:
                class_label = ">15"

        rows.append(
            {
                "metro_time": _seconds_to_hhmmss(metro_s),
                "next_bus_time": next_bus_str,
                "wait_min": wait_min,
                "wait_class": class_label,
                "period": _period_label(metro_s),
            }
        )

    return pd.DataFrame(rows)


def generate_connection_visualizations(
    metro_stop_ref: str,
    bus_stop_ref: str,
    line_number: str | int,
    day_str: str | None = None,
    metro_origin_ref: str = "Portagem",
    bus_origin_ref: str = "Portagem",
    output_prefix: str | None = None,
) -> dict[str, str]:
    """
    Gera visualizacoes de coordenacao metro -> autocarro e grava HTML em outputs/integration.

    Retorna um dicionario com os caminhos dos ficheiros gerados.
    """
    if px is None or go is None:
        raise ImportError("plotly nao esta disponivel para gerar visualizacoes")

    schedule_df = build_line_stop_vs_metro_table(
        metro_stop_ref=metro_stop_ref,
        bus_stop_ref=bus_stop_ref,
        line_number=line_number,
        day_str=day_str,
        metro_origin_ref=metro_origin_ref,
        bus_origin_ref=bus_origin_ref,
    )
    metrics_df = build_metro_bus_connection_metrics(
        metro_stop_ref=metro_stop_ref,
        bus_stop_ref=bus_stop_ref,
        line_number=line_number,
        day_str=day_str,
        metro_origin_ref=metro_origin_ref,
        bus_origin_ref=bus_origin_ref,
    )

    waits_df = _build_waits_table(schedule_df)

    out_root = Path(__file__).resolve().parents[2] / OUTPUTS_INTEGRATION_DIR
    out_root.mkdir(parents=True, exist_ok=True)

    sample_date = str(schedule_df["date"].iloc[0]) if not schedule_df.empty else (day_str or "unknown_date")
    date_tag = sample_date.replace("-", "")
    prefix = output_prefix or f"l{_safe_slug(line_number)}"

    # 1) Timeline plot
    bus_points = pd.DataFrame(
        {
            "time": [v for v in schedule_df["bus_time"].astype(str).tolist() if str(v).strip()],
            "series": [f"Autocarro {line_number} ({bus_stop_ref})"] * int((schedule_df["bus_time"].astype(str) != "").sum()),
        }
    )
    metro_points = pd.DataFrame(
        {
            "time": [v for v in schedule_df["metro_time_from_origin"].astype(str).tolist() if str(v).strip()],
            "series": [f"Metro ({metro_origin_ref} -> {metro_stop_ref})"] * int((schedule_df["metro_time_from_origin"].astype(str) != "").sum()),
        }
    )
    timeline_df = pd.concat([bus_points, metro_points], ignore_index=True)
    timeline_df["time_s"] = timeline_df["time"].map(_hhmmss_to_seconds)

    fig_timeline = px.scatter(
        timeline_df,
        x="time_s",
        y="series",
        color="series",
        title=f"Timeline de Passagens ({sample_date})",
        labels={"time_s": "Hora", "series": "Rede"},
    )
    fig_timeline.update_traces(marker={"size": 10, "line": {"color": "black", "width": 0.6}})
    fig_timeline.update_layout(
        plot_bgcolor="white",
        xaxis={
            "tickmode": "array",
            "tickvals": list(range(6 * 3600, 24 * 3600 + 1, 3600)),
            "ticktext": [f"{h:02d}:00" for h in range(6, 25)],
            "showgrid": True,
            "gridcolor": "#d9d9d9",
        },
        yaxis={"showgrid": False},
    )

    # 2) Wait-time bar plot
    fig_wait = px.bar(
        waits_df,
        x="metro_time",
        y="wait_min",
        color="wait_class",
        title=f"Espera ate ao Proximo Autocarro ({sample_date})",
        labels={"metro_time": "Hora de chegada do metro na Portela", "wait_min": "Espera (min)"},
        color_discrete_map={"<=10": "#2a9d8f", "10-15": "#e9c46a", ">15": "#e76f51", "sem_ligacao": "#6c757d"},
    )
    fig_wait.update_layout(
        plot_bgcolor="white",
        xaxis={"showgrid": False, "tickangle": -45},
        yaxis={"showgrid": True, "gridcolor": "#d9d9d9", "rangemode": "tozero"},
    )

    # 3) Period equity heatmap (coverage<=10, lost>15, median wait)
    heat_records = []
    for period in ["manha", "meio_dia", "tarde_noite"]:
        sub = waits_df[waits_df["period"] == period]
        if sub.empty:
            cov10 = None
            lost15 = None
            med_wait = None
        else:
            waits = pd.to_numeric(sub["wait_min"], errors="coerce")
            n = len(sub)
            cov10 = round(float((waits <= 10).sum() / n * 100.0), 2)
            lost15 = round(float(((waits > 15) | waits.isna()).sum() / n * 100.0), 2)
            med_wait = round(float(waits.dropna().median()), 2) if not waits.dropna().empty else None

        heat_records.extend(
            [
                {"period": period, "metric": "coverage<=10 (%)", "value": cov10},
                {"period": period, "metric": "lost>15 (%)", "value": lost15},
                {"period": period, "metric": "median_wait (min)", "value": med_wait},
            ]
        )

    heat_df = pd.DataFrame(heat_records)
    heat_pivot = heat_df.pivot(index="metric", columns="period", values="value")
    fig_heat = px.imshow(
        heat_pivot,
        text_auto=True,
        aspect="auto",
        color_continuous_scale="YlOrRd",
        title=f"Equidade Temporal de Ligacoes ({sample_date})",
        labels={"color": "Valor"},
    )
    fig_heat.update_layout(plot_bgcolor="white")

    timeline_path = out_root / f"{prefix}_tl_{date_tag}.html"
    waits_path = out_root / f"{prefix}_wt_{date_tag}.html"
    heatmap_path = out_root / f"{prefix}_eq_{date_tag}.html"
    waits_csv_path = out_root / f"{prefix}_wt_{date_tag}.csv"
    schedule_csv_path = out_root / (
        f"line_{_safe_slug(line_number)}_bus_{_safe_slug(bus_stop_ref)}"
        f"_metro_{_safe_slug(metro_stop_ref)}_{date_tag}.csv"
    )
    metrics_csv_path = out_root / (
        f"line_{_safe_slug(line_number)}_connection_metrics_"
        f"{_safe_slug(bus_stop_ref)}_vs_{_safe_slug(metro_stop_ref)}_{date_tag}.csv"
    )

    _write_readable_plotly_html(fig_timeline, timeline_path, title="Timeline de Passagens")
    _write_readable_plotly_html(fig_wait, waits_path, title="Espera de Transbordo")
    _write_readable_plotly_html(fig_heat, heatmap_path, title="Equidade Temporal")
    waits_df.to_csv(waits_csv_path, index=False)

    return {
        "output_dir": str(out_root),
        "schedule_csv": str(schedule_csv_path),
        "metrics_csv": str(metrics_csv_path),
        "timeline_html": str(timeline_path),
        "waits_html": str(waits_path),
        "equity_html": str(heatmap_path),
        "waits_csv": str(waits_csv_path),
        "metrics_rows": str(len(metrics_df)),
    }

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

    # 1) Timeline heatmap: frequency of passages per hour and transport type
    bus_times_s = [
        _hhmmss_to_seconds(v)
        for v in schedule_df["bus_time"].astype(str).tolist()
        if str(v).strip()
    ]
    metro_times_s = [
        _hhmmss_to_seconds(v)
        for v in schedule_df["metro_time_from_origin"].astype(str).tolist()
        if str(v).strip()
    ]

    # Create 20-minute bins (6 to 24)
    bin_minutes = 20
    start_h, end_h = 6, 24
    bins_per_hour = 60 // bin_minutes  # 3 bins per hour
    n_bins = (end_h - start_h) * bins_per_hour
    
    bus_counts = []
    metro_counts = []
    heatmap_labels_x = []
    
    for i in range(n_bins):
        start_sec = start_h * 3600 + i * bin_minutes * 60
        end_sec = start_sec + bin_minutes * 60
        bus_counts.append(sum(1 for t in bus_times_s if start_sec <= t < end_sec))
        metro_counts.append(sum(1 for t in metro_times_s if start_sec <= t < end_sec))
        
        h = (start_h * 60 + i * bin_minutes) // 60
        m = (start_h * 60 + i * bin_minutes) % 60
        heatmap_labels_x.append(f"{h:02d}:{m:02d}")

    heatmap_data = [
        metro_counts,
        bus_counts,
    ]
    heatmap_labels_y = [f"Metro ({metro_origin_ref} -> {metro_stop_ref})", f"Autocarro {line_number}"]

    fig_timeline = go.Figure(
        data=go.Heatmap(
            z=heatmap_data,
            x=heatmap_labels_x,
            y=heatmap_labels_y,
            colorscale="YlOrRd",
            text=heatmap_data,
            texttemplate="%{text}",
            textfont={"size": 10},
            colorbar={"title": "Freq."},
        )
    )
    fig_timeline.update_layout(
        title=f"Frequencia de Passagens por Hora ({sample_date})",
        xaxis_title="Hora",
        yaxis_title="Rede",
        plot_bgcolor="white",
    )

    # 2) Wait-time bar plot (sorted by temporal order)
    # Convert metro_time to seconds for proper ordering
    waits_df_sorted = waits_df.copy()
    waits_df_sorted["metro_time_s"] = waits_df_sorted["metro_time"].apply(_hhmmss_to_seconds)
    waits_df_sorted = waits_df_sorted.sort_values("metro_time_s").reset_index(drop=True)
    waits_df_sorted["index_label"] = range(len(waits_df_sorted))

    fig_wait = px.bar(
        waits_df_sorted,
        x="index_label",
        y="wait_min",
        color="wait_class",
        title=f"Espera ate ao Proximo Autocarro ({sample_date})",
        labels={"index_label": "Hora de chegada do metro", "wait_min": "Espera (min)"},
        color_discrete_map={"<=10": "#2a9d8f", "10-15": "#e9c46a", ">15": "#e76f51", "sem_ligacao": "#6c757d"},
    )
    
    # Custom x-axis with temporal labels
    fig_wait.update_layout(
        plot_bgcolor="white",
        xaxis={
            "tickmode": "array",
            "tickvals": list(range(len(waits_df_sorted))),
            "ticktext": waits_df_sorted["metro_time"].tolist(),
            "showgrid": False,
            "tickangle": -45,
        },
        yaxis={"showgrid": True, "gridcolor": "#d9d9d9", "rangemode": "tozero"},
    )

    # 3) Period equity heatmap (coverage<=10, lost>15, median wait)
    period_labels = {
        "manha": "Manha (6h-12h)",
        "meio_dia": "Meio Dia (12h-17h)",
        "tarde_noite": "Tarde-Noite (17h-24h)",
        "dia_inteiro": "Dia Inteiro (6h-24h)",
    }
    heat_records = []
    for period in ["manha", "meio_dia", "tarde_noite", "dia_inteiro"]:
        if period == "dia_inteiro":
            sub = waits_df
        else:
            sub = waits_df[waits_df["period"] == period]
        
        if sub.empty:
            cov10 = None
            lost15 = None
            med_wait = None
            mean_wait = None
        else:
            waits = pd.to_numeric(sub["wait_min"], errors="coerce")
            n = len(sub)
            cov10 = round(float((waits <= 10).sum() / n * 100.0), 2)
            lost15 = round(float(((waits > 15) | waits.isna()).sum() / n * 100.0), 2)
            med_wait = round(float(waits.dropna().median()), 2) if not waits.dropna().empty else None
            mean_wait = round(float(waits.dropna().mean()), 2) if not waits.dropna().empty else None

        heat_records.extend(
            [
                {"period": period_labels[period], "metric": "coverage<=10 (%)", "value": cov10},
                {"period": period_labels[period], "metric": "lost>15 (%)", "value": lost15},
                {"period": period_labels[period], "metric": "median_wait (min)", "value": med_wait},
                {"period": period_labels[period], "metric": "mean_wait (min)", "value": mean_wait},
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

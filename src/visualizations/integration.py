from __future__ import annotations

import html
import shutil
from pathlib import Path

import pandas as pd

from config import OUTPUTS_INTEGRATION_DIR
from overlap.transit import (
    build_line_stop_vs_metro_table,
    build_metro_bus_connection_metrics,
    resolve_reference_day,
)

try:
    import plotly.express as px
    import plotly.graph_objects as go
    import plotly.io as pio
except Exception:  # pragma: no cover - optional dependency guard
    px = None
    go = None
    pio = None


_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _read_template(template_name: str) -> str:
    template_path = _TEMPLATE_DIR / template_name
    return template_path.read_text(encoding="utf-8")


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


def _line_display(line_number: str | int | list[str | int] | tuple[str | int, ...]) -> str:
    if isinstance(line_number, (list, tuple, set)):
        items = [str(v).strip() for v in line_number if str(v).strip()]
        return "+".join(dict.fromkeys(items))
    text = str(line_number).strip()
    if "," in text:
        items = [p.strip() for p in text.split(",") if p.strip()]
        return "+".join(dict.fromkeys(items))
    return text


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
    if "bus_line_passage" in schedule_df.columns:
        bus_line_col = schedule_df["bus_line_passage"].astype(str).str.strip()
    else:
        bus_line_col = schedule_df.get("bus_line", pd.Series([""] * len(schedule_df))).astype(str).str.strip()

    bus_events = []
    for time_v, line_v in zip(schedule_df["bus_time"].astype(str).tolist(), bus_line_col.tolist()):
        if not str(time_v).strip():
            continue
        bus_events.append(
            {
                "time_s": _hhmmss_to_seconds(time_v),
                "time": str(time_v),
                "line": str(line_v),
            }
        )
    bus_events = sorted(bus_events, key=lambda r: (int(r["time_s"]), str(r["line"])))
    metro_times = sorted(
        {
            _hhmmss_to_seconds(v)
            for v in schedule_df["metro_time_from_origin"].astype(str).tolist()
            if str(v).strip()
        }
    )

    rows: list[dict] = []
    for metro_s in metro_times:
        next_bus = next((b for b in bus_events if int(b["time_s"]) >= metro_s), None)
        if next_bus is None:
            wait_min = None
            next_bus_str = ""
            next_bus_line = ""
            class_label = "sem_ligacao"
        else:
            wait_min = round((int(next_bus["time_s"]) - metro_s) / 60.0, 2)
            next_bus_str = str(next_bus["time"])
            next_bus_line = str(next_bus["line"])
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
                "next_bus_line": next_bus_line,
                "wait_min": wait_min,
                "wait_class": class_label,
                "period": _period_label(metro_s),
            }
        )

    return pd.DataFrame(rows)


def create_combined_integration_dashboard(
    output_path: Path | str,
    title: str,
    timeline_fig: object,
    waits_fig: object,
    equity_fig: object,
) -> str:
    """Create a single HTML page with timeline, waits and equity in one document."""
    if pio is None:
        raise ImportError("plotly.io nao esta disponivel para gerar visualizacoes")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    timeline_json = pio.to_json(timeline_fig)
    waits_json = pio.to_json(waits_fig)
    equity_json = pio.to_json(equity_fig)

    page = _read_template("integration_dashboard.html")
    page = page.replace("__TITLE__", html.escape(title))
    page = page.replace("__TIMELINE_JSON__", timeline_json)
    page = page.replace("__WAITS_JSON__", waits_json)
    page = page.replace("__EQUITY_JSON__", equity_json)

    output_path.write_text(page, encoding="utf-8")
    return str(output_path)


def generate_connection_visualizations(
    metro_stop_ref: str,
    bus_stop_ref: str,
    line_number: str | int | list[str | int] | tuple[str | int, ...],
    day_str: str | None = None,
    metro_origin_ref: str = "Portagem",
    bus_origin_ref: str = "Portagem",
    output_prefix: str | None = None,
    output_subdir: str | None = None,
    fixed_html_name: str | None = None,
) -> dict[str, str]:
    """
    Gera visualizacoes de coordenacao metro -> autocarro e grava HTML em outputs/integration.

    Retorna um dicionario com os caminhos dos ficheiros gerados.
    """
    if px is None or go is None or pio is None:
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

    out_root_base = Path(__file__).resolve().parents[2] / OUTPUTS_INTEGRATION_DIR
    if output_subdir:
        out_root = out_root_base / str(output_subdir)
    else:
        stop_ref_norm = str(metro_stop_ref).strip().lower()
        if "portagem" in stop_ref_norm:
            out_root = out_root_base / "portagem"
        elif "portela" in stop_ref_norm:
            out_root = out_root_base / "portela"
        else:
            out_root = out_root_base
    out_root.mkdir(parents=True, exist_ok=True)

    # Always bind displayed date to the shared nearest-business-day policy.
    sample_date = resolve_reference_day().strftime("%Y-%m-%d")
    date_tag = sample_date.replace("-", "")
    line_display = _line_display(line_number)
    prefix = output_prefix or f"l{_safe_slug(line_display)}"

    # 1) Timeline heatmap: frequency of passages per hour and transport type
    metro_times_s = [
        _hhmmss_to_seconds(v)
        for v in schedule_df["metro_time_from_origin"].astype(str).tolist()
        if str(v).strip()
    ]

    if "bus_line_passage" in schedule_df.columns:
        bus_line_col = schedule_df["bus_line_passage"].astype(str).str.strip()
    else:
        bus_line_col = schedule_df["bus_line"].astype(str).str.strip()

    bus_lines_unique = [v for v in bus_line_col.tolist() if v]
    bus_lines_unique = list(dict.fromkeys(bus_lines_unique))
    if not bus_lines_unique:
        bus_lines_unique = [line_display]

    bus_times_by_line: dict[str, list[int]] = {}
    for line_val in bus_lines_unique:
        mask = (
            (schedule_df["bus_time"].astype(str).str.strip() != "")
            & (bus_line_col == line_val)
        )
        bus_times_by_line[line_val] = [
            _hhmmss_to_seconds(v)
            for v in schedule_df.loc[mask, "bus_time"].astype(str).tolist()
            if str(v).strip()
        ]

    # Create 20-minute bins (6 to 24)
    bin_minutes = 20
    start_h, end_h = 6, 24
    bins_per_hour = 60 // bin_minutes  # 3 bins per hour
    n_bins = (end_h - start_h) * bins_per_hour
    
    bus_counts_by_line = {line_val: [] for line_val in bus_lines_unique}
    metro_counts = []
    heatmap_labels_x = []
    
    for i in range(n_bins):
        start_sec = start_h * 3600 + i * bin_minutes * 60
        end_sec = start_sec + bin_minutes * 60
        for line_val in bus_lines_unique:
            bus_counts_by_line[line_val].append(
                sum(1 for t in bus_times_by_line.get(line_val, []) if start_sec <= t < end_sec)
            )
        metro_counts.append(sum(1 for t in metro_times_s if start_sec <= t < end_sec))
        
        h = (start_h * 60 + i * bin_minutes) // 60
        m = (start_h * 60 + i * bin_minutes) % 60
        heatmap_labels_x.append(f"{h:02d}:{m:02d}")

    heatmap_data = [metro_counts]
    heatmap_labels_y = [f"Metro ({metro_origin_ref} -> {metro_stop_ref})"]
    for line_val in bus_lines_unique:
        heatmap_data.append(bus_counts_by_line[line_val])
        heatmap_labels_y.append(f"Autocarro {line_val}")

    fig_timeline = go.Figure(
        data=go.Heatmap(
            z=heatmap_data,
            x=heatmap_labels_x,
            y=heatmap_labels_y,
            colorscale="YlOrRd",
            colorbar={
                "title": "Freq.",
                "tickvals": [0, 1, 2],
                "ticktext": ["0", "1", "2"],
                "len": 0.3,
            },
        )
    )
    fig_timeline.update_layout(
        title=f"Frequência de Passagens ({sample_date})",
        xaxis_title="Hora",
        yaxis_title="Rede",
        plot_bgcolor="white",
    )

    # 2) Wait-time bar plot with point overlays for special cases
    # Convert metro_time to seconds for proper ordering
    waits_df_sorted = waits_df.copy()
    waits_df_sorted["metro_time_s"] = waits_df_sorted["metro_time"].apply(_hhmmss_to_seconds)
    waits_df_sorted = waits_df_sorted.sort_values("metro_time_s").reset_index(drop=True)
    waits_df_sorted["index_label"] = range(len(waits_df_sorted))

    zero_waits = waits_df_sorted[pd.to_numeric(waits_df_sorted["wait_min"], errors="coerce") == 0]
    no_link_waits = waits_df_sorted[waits_df_sorted["wait_class"] == "sem_ligacao"]
    bar_waits = waits_df_sorted[
        (pd.to_numeric(waits_df_sorted["wait_min"], errors="coerce") != 0)
        & (waits_df_sorted["wait_class"] != "sem_ligacao")
    ]

    fig_wait = px.bar(
        bar_waits,
        x="index_label",
        y="wait_min",
        color="wait_class",
        title=f"Espera até ao Próximo Autocarro ({sample_date})",
        labels={"index_label": "Hora de chegada do metro", "wait_min": "Espera (min)"},
        color_discrete_map={"<=10": "#2a9d8f", "10-15": "#e9c46a", ">15": "#e76f51"},
        hover_data={
            "metro_time": True,
            "next_bus_time": True,
            "next_bus_line": True,
            "wait_min": True,
            "index_label": False,
        },
    )

    if not zero_waits.empty:
        fig_wait.add_trace(
            go.Scatter(
                x=zero_waits["index_label"],
                y=[0] * len(zero_waits),
                mode="markers",
                name="0 min",
                marker={"size": 11, "color": "#2a9d8f", "line": {"width": 0.5, "color": "white"}},
                hovertemplate=(
                    "Hora de chegada do metro=%{customdata[0]}"
                    "<br>Próximo autocarro=%{customdata[1]}"
                    "<br>Linha=%{customdata[2]}"
                    "<br>Espera (min)=0<extra></extra>"
                ),
                customdata=zero_waits[["metro_time", "next_bus_time", "next_bus_line"]].to_numpy(),
            )
        )

    if not no_link_waits.empty:
        fig_wait.add_trace(
            go.Scatter(
                x=no_link_waits["index_label"],
                y=[0] * len(no_link_waits),
                mode="markers",
                name="sem ligação",
                marker={"size": 11, "color": "#6c757d", "line": {"width": 0.5, "color": "white"}},
                hovertemplate="%{customdata[0]}<br>Sem ligação<extra></extra>",
                customdata=no_link_waits[["metro_time"]].to_numpy(),
            )
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
        legend_title_text="",
    )

    # 3) Period equity heatmap (cobertura <=10, perdas >15, espera média)
    period_labels = {
        "manha": "Manhã (6h-12h)",
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
                {"period": period_labels[period], "metric": "Cobertura <= 10 (%)", "value": cov10},
                {"period": period_labels[period], "metric": "Perda > 15 minutos (%)", "value": lost15},
                {"period": period_labels[period], "metric": "Espera Mediana (min)", "value": med_wait},
                {"period": period_labels[period], "metric": "Espera Média (min)", "value": mean_wait},
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
        labels={"color": "Valor", "x": "Período", "y": "Métrica"},
    )
    fig_heat.update_layout(plot_bgcolor="white")

    waits_csv_path = out_root / f"{prefix}_wt.csv"
    schedule_csv_path = out_root / (
        f"line_{_safe_slug(line_number)}_bus_{_safe_slug(bus_stop_ref)}"
        f"_metro_{_safe_slug(metro_stop_ref)}.csv"
    )
    metrics_csv_path = out_root / (
        f"line_{_safe_slug(line_number)}_connection_metrics_"
        f"{_safe_slug(bus_stop_ref)}_vs_{_safe_slug(metro_stop_ref)}.csv"
    )

    waits_df.to_csv(waits_csv_path, index=False)

    root_schedule_path = out_root_base / schedule_csv_path.name
    if root_schedule_path.exists() and root_schedule_path.resolve() != schedule_csv_path.resolve():
        if schedule_csv_path.exists():
            schedule_csv_path.unlink()
        shutil.move(str(root_schedule_path), str(schedule_csv_path))

    root_metrics_path = out_root_base / metrics_csv_path.name
    if root_metrics_path.exists() and root_metrics_path.resolve() != metrics_csv_path.resolve():
        if metrics_csv_path.exists():
            metrics_csv_path.unlink()
        shutil.move(str(root_metrics_path), str(metrics_csv_path))

    combined_name = fixed_html_name or f"{prefix}_all.html"
    combined_path = out_root / combined_name
    create_combined_integration_dashboard(
        output_path=combined_path,
        title=(
            f"Integracao Linha {line_display}: {bus_origin_ref} -> {bus_stop_ref} "
            f"vs Metro {metro_origin_ref} -> {metro_stop_ref} ({sample_date})"
        ),
        timeline_fig=fig_timeline,
        waits_fig=fig_wait,
        equity_fig=fig_heat,
    )

    return {
        "output_dir": str(out_root),
        "schedule_csv": str(schedule_csv_path),
        "metrics_csv": str(metrics_csv_path),
        "combined_html": str(combined_path),
        "waits_csv": str(waits_csv_path),
        "metrics_rows": str(len(metrics_df)),
    }

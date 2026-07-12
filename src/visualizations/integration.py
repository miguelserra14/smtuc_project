from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import OUTPUTS_INTEGRATION_DIR
from overlap.transit import (
    _hhmmss_to_seconds,
    build_line_stop_vs_metro_table,
    build_metro_bus_connection_metrics,
    build_reverse_stop_vs_metro_table,
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


def _shift_schedule_bus_times(schedule_df: pd.DataFrame, line_value: str, shift_minutes: float) -> pd.DataFrame:
    """Devolve uma cópia de `schedule_df` com `bus_time` deslocado `shift_minutes` minutos,
    apenas nas linhas cuja `bus_line_passage` seja `line_value` - as restantes linhas (ex.: a 38
    em Portagem) ficam exatamente como estavam, porque a proposta de horário otimizado só mexe
    no ciclo da linha 54."""
    out = schedule_df.copy()
    line_col = out["bus_line_passage"] if "bus_line_passage" in out.columns else out["bus_line"]
    mask = (line_col.astype(str).str.strip() == str(line_value)) & (out["bus_time"].astype(str).str.strip() != "")
    shifted = out.loc[mask, "bus_time"].astype(str).map(
        lambda t: _seconds_to_hhmmss(int(round(_hhmmss_to_seconds(t) + shift_minutes * 60)))
    )
    out.loc[mask, "bus_time"] = shifted
    return out


def _shift_reverse_schedule_bus_arrivals(schedule_df: pd.DataFrame, shift_minutes: float) -> pd.DataFrame:
    """Equivalente a `_shift_schedule_bus_times`, mas para tabelas de `build_reverse_stop_vs_metro_table`
    - aí são as chegadas do autocarro que ficam em `metro_time_from_origin` (ver docstring dessa
    função), por isso é essa coluna que se desloca. Desloca a coluna inteira sem filtrar por
    linha: `build_reverse_stop_vs_metro_table` já é chamada com a(s) linha(s) pretendida(s), ao
    contrário do sentido direto onde uma única tabela pode combinar várias linhas na mesma
    coluna `bus_time` (ex. 54+38)."""
    out = schedule_df.copy()
    mask = out["metro_time_from_origin"].astype(str).str.strip() != ""
    shifted = out.loc[mask, "metro_time_from_origin"].astype(str).map(
        lambda t: _seconds_to_hhmmss(int(round(_hhmmss_to_seconds(t) + shift_minutes * 60)))
    )
    out.loc[mask, "metro_time_from_origin"] = shifted
    return out


def _wait_summary(waits_df: pd.DataFrame) -> dict[str, float]:
    if waits_df.empty:
        return {"median": float("nan"), "coverage10": float("nan")}
    waits = pd.to_numeric(waits_df["wait_min"], errors="coerce")
    n = len(waits_df)
    dropna = waits.dropna()
    return {
        "median": float(dropna.median()) if not dropna.empty else float("nan"),
        "coverage10": float((waits <= 10).sum() / n * 100.0) if n else float("nan"),
    }


def _wait_chart_traces(
    waits_df: pd.DataFrame,
    visible: bool,
    trigger_label: str = "Hora de chegada do metro",
    target_label: str = "Próximo autocarro",
    target_line_label: str = "Linha",
) -> tuple[list, pd.DataFrame]:
    """Constrói as barras de espera + sobreposições (0 min, sem ligação) para `waits_df`, com
    `visible` aplicado a todas as traces - usado para gerar o mesmo conjunto de traces duas
    vezes (horário atual e horário otimizado) e trocar entre elas com um botão.

    `waits_df` guarda sempre as mesmas colunas (`metro_time`, `next_bus_time`,
    `next_bus_line`), mas o SIGNIFICADO troca consoante o sentido (ver
    `build_reverse_stop_vs_metro_table`): `trigger_label`/`target_label`/`target_line_label`
    deixam o chamador rotular o hover/eixo com o texto certo em vez de "metro"/"autocarro" fixos."""
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

    bar_fig = px.bar(
        bar_waits,
        x="index_label",
        y="wait_min",
        color="wait_class",
        labels={"index_label": trigger_label, "wait_min": "Espera (min)"},
        color_discrete_map={"<=10": "#2a9d8f", "10-15": "#e9c46a", ">15": "#e76f51"},
        hover_data={
            "metro_time": True,
            "next_bus_time": True,
            "next_bus_line": True,
            "wait_min": True,
            "index_label": False,
        },
    )
    traces = list(bar_fig.data)
    for trace in traces:
        if getattr(trace, "hovertemplate", None):
            trace.hovertemplate = (
                trace.hovertemplate
                .replace("metro_time=", f"{trigger_label}=")
                .replace("next_bus_time=", f"{target_label}=")
                .replace("next_bus_line=", f"{target_line_label}=")
            )

    if not zero_waits.empty:
        traces.append(
            go.Scatter(
                x=zero_waits["index_label"],
                y=[0] * len(zero_waits),
                mode="markers",
                name="0 min",
                marker={"size": 11, "color": "#2a9d8f", "line": {"width": 0.5, "color": "white"}},
                hovertemplate=(
                    f"{trigger_label}=%{{customdata[0]}}"
                    f"<br>{target_label}=%{{customdata[1]}}"
                    f"<br>{target_line_label}=%{{customdata[2]}}"
                    "<br>Espera (min)=0<extra></extra>"
                ),
                customdata=zero_waits[["metro_time", "next_bus_time", "next_bus_line"]].to_numpy(),
            )
        )

    if not no_link_waits.empty:
        traces.append(
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

    for trace in traces:
        trace.visible = visible

    return traces, waits_df_sorted


def _bin_counts(times_s: list[int], bin_minutes: int, start_h: int, n_bins: int) -> list[int]:
    counts = []
    for i in range(n_bins):
        start_sec = start_h * 3600 + i * bin_minutes * 60
        end_sec = start_sec + bin_minutes * 60
        counts.append(sum(1 for t in times_s if start_sec <= t < end_sec))
    return counts


def _timeline_heatmap_trace(
    schedule_df: pd.DataFrame,
    metro_row_label: str,
    bus_lines_unique: list[str],
    visible: bool,
    bus_row_label_prefix: str = "Autocarro",
):
    """Constrói uma única trace go.Heatmap com a frequência de passagens (linha "metro" +
    cada linha "bus") em bins de 20 min, 06h-24h. Reutilizado para o horário atual e otimizado,
    e para os dois sentidos (metro->bus e bus->metro - ver `build_reverse_stop_vs_metro_table`,
    onde o conteúdo das colunas `metro_time_from_origin`/`bus_time` é trocado de propósito, por
    isso os rótulos das linhas não podem ser fixos "Metro"/"Autocarro X": `metro_row_label` e
    `bus_row_label_prefix` deixam o chamador escolher o texto certo para cada sentido)."""
    metro_times_s = [
        _hhmmss_to_seconds(v)
        for v in schedule_df["metro_time_from_origin"].astype(str).tolist()
        if str(v).strip()
    ]
    if "bus_line_passage" in schedule_df.columns:
        bus_line_col = schedule_df["bus_line_passage"].astype(str).str.strip()
    else:
        bus_line_col = schedule_df["bus_line"].astype(str).str.strip()

    bus_times_by_line: dict[str, list[int]] = {}
    for line_val in bus_lines_unique:
        mask = (schedule_df["bus_time"].astype(str).str.strip() != "") & (bus_line_col == line_val)
        bus_times_by_line[line_val] = [
            _hhmmss_to_seconds(v)
            for v in schedule_df.loc[mask, "bus_time"].astype(str).tolist()
            if str(v).strip()
        ]

    bin_minutes = 20
    start_h, end_h = 6, 24
    bins_per_hour = 60 // bin_minutes
    n_bins = (end_h - start_h) * bins_per_hour

    heatmap_labels_x = []
    for i in range(n_bins):
        h = (start_h * 60 + i * bin_minutes) // 60
        m = (start_h * 60 + i * bin_minutes) % 60
        heatmap_labels_x.append(f"{h:02d}:{m:02d}")

    heatmap_data = [_bin_counts(metro_times_s, bin_minutes, start_h, n_bins)]
    heatmap_labels_y = [metro_row_label]
    for line_val in bus_lines_unique:
        heatmap_data.append(_bin_counts(bus_times_by_line.get(line_val, []), bin_minutes, start_h, n_bins))
        label = f"{bus_row_label_prefix} {line_val}".strip() if bus_row_label_prefix else str(line_val)
        heatmap_labels_y.append(label)

    trace = go.Heatmap(
        z=heatmap_data,
        x=heatmap_labels_x,
        y=heatmap_labels_y,
        colorscale="YlOrRd",
        colorbar={"title": "Freq.", "tickvals": [0, 1, 2], "ticktext": ["0", "1", "2"], "len": 0.3},
        visible=visible,
    )
    return trace


def _equity_heat_pivot(waits_df: pd.DataFrame) -> pd.DataFrame:
    period_labels = {
        "manha": "Manhã (6h-12h)",
        "meio_dia": "Meio Dia (12h-17h)",
        "tarde_noite": "Tarde-Noite (17h-24h)",
        "dia_inteiro": "Dia Inteiro (6h-24h)",
    }
    heat_records = []
    for period in ["manha", "meio_dia", "tarde_noite", "dia_inteiro"]:
        sub = waits_df if period == "dia_inteiro" else waits_df[waits_df["period"] == period]

        if sub.empty:
            cov10 = lost15 = med_wait = mean_wait = None
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
    return heat_df.pivot(index="metric", columns="period", values="value")


def _build_direction_figures(
    schedule_df: pd.DataFrame,
    schedule_df_opt: pd.DataFrame | None,
    metro_row_label: str,
    bus_lines_unique: list[str],
    sample_date: str,
    timeline_title: str,
    wait_title: str,
    equity_title: str,
    optimization_desc: str | None,
    bus_row_label_prefix: str = "Autocarro",
    wait_trigger_label: str = "Hora de chegada do metro",
    wait_target_label: str = "Próximo autocarro",
    wait_target_line_label: str = "Linha",
) -> tuple[object, object, object, dict | None, pd.DataFrame]:
    """Constrói as 3 figuras (timeline, espera, equidade) + payload de otimização para UM
    sentido de transbordo. Partilhado pelo sentido metro->bus e bus->metro (ver
    `build_reverse_stop_vs_metro_table`) - só muda o `schedule_df` de entrada e os rótulos.
    `schedule_df_opt` (opcional) é a versão com o horário otimizado já aplicado; se None, as
    figuras saem sem a comparação Atual/Otimizado. Devolve também `waits_df` (não otimizado),
    útil para o chamador gravar em CSV."""
    waits_df = _build_waits_table(schedule_df)
    apply_optimization = schedule_df_opt is not None
    waits_df_opt = _build_waits_table(schedule_df_opt) if apply_optimization else None

    # 1) Timeline heatmap: frequency of passages per hour and transport type
    timeline_trace_current = _timeline_heatmap_trace(
        schedule_df, metro_row_label, bus_lines_unique, visible=True, bus_row_label_prefix=bus_row_label_prefix
    )
    fig_timeline = go.Figure(data=[timeline_trace_current])
    timeline_indices = {"current": [0], "optimized": []}
    if apply_optimization:
        timeline_trace_opt = _timeline_heatmap_trace(
            schedule_df_opt, metro_row_label, bus_lines_unique, visible=False, bus_row_label_prefix=bus_row_label_prefix
        )
        fig_timeline.add_trace(timeline_trace_opt)
        timeline_indices = {"current": [0], "optimized": [1]}
    fig_timeline.update_layout(
        title=timeline_title,
        xaxis_title="Hora",
        yaxis_title="Rede",
        plot_bgcolor="white",
    )

    # 2) Wait-time bar plot with point overlays for special cases
    waits_traces_current, waits_df_sorted = _wait_chart_traces(
        waits_df, visible=True, trigger_label=wait_trigger_label,
        target_label=wait_target_label, target_line_label=wait_target_line_label,
    )
    fig_wait = go.Figure(data=waits_traces_current)
    waits_indices = {"current": list(range(len(waits_traces_current))), "optimized": []}
    if apply_optimization:
        waits_traces_opt, _ = _wait_chart_traces(
            waits_df_opt, visible=False, trigger_label=wait_trigger_label,
            target_label=wait_target_label, target_line_label=wait_target_line_label,
        )
        start = len(fig_wait.data)
        for trace in waits_traces_opt:
            fig_wait.add_trace(trace)
        waits_indices["optimized"] = list(range(start, start + len(waits_traces_opt)))

    fig_wait.update_layout(
        title=wait_title,
        plot_bgcolor="white",
        xaxis={
            "title": wait_trigger_label,
            "tickmode": "array",
            "tickvals": list(range(len(waits_df_sorted))),
            "ticktext": waits_df_sorted["metro_time"].tolist(),
            "showgrid": False,
            "tickangle": -45,
        },
        yaxis={"title": "Espera (min)", "showgrid": True, "gridcolor": "#d9d9d9", "rangemode": "tozero"},
        legend_title_text="",
    )

    # 3) Period equity heatmap (cobertura <=10, perdas >15, espera média)
    heat_pivot = _equity_heat_pivot(waits_df)
    equity_trace_current = go.Heatmap(
        z=heat_pivot.to_numpy(),
        x=list(heat_pivot.columns),
        y=list(heat_pivot.index),
        colorscale="YlOrRd",
        texttemplate="%{z}",
        colorbar={"title": "Valor"},
        visible=True,
    )
    fig_heat = go.Figure(data=[equity_trace_current])
    equity_indices = {"current": [0], "optimized": []}
    if apply_optimization:
        heat_pivot_opt = _equity_heat_pivot(waits_df_opt)
        equity_trace_opt = go.Heatmap(
            z=heat_pivot_opt.to_numpy(),
            x=list(heat_pivot_opt.columns),
            y=list(heat_pivot_opt.index),
            colorscale="YlOrRd",
            texttemplate="%{z}",
            colorbar={"title": "Valor"},
            visible=False,
        )
        fig_heat.add_trace(equity_trace_opt)
        equity_indices = {"current": [0], "optimized": [1]}
    fig_heat.update_layout(
        title=equity_title,
        xaxis_title="Período",
        yaxis_title="Métrica",
        plot_bgcolor="white",
    )

    optimization_payload = None
    if apply_optimization:
        cur_summary = _wait_summary(waits_df)
        opt_summary = _wait_summary(waits_df_opt)
        regresses = opt_summary["median"] > cur_summary["median"]
        caveat = (
            " Este sentido/paragem piora ligeiramente em troca de ganhos maiores nos outros "
            "sentidos/paragens, que esta visualização não mostra sozinha - o desvio foi "
            "escolhido a olhar para os 4 sentidos possíveis ao mesmo tempo (metro->bus e bus-"
            ">metro, em Portela e em Portagem), não só para este; não existe nenhum desvio que "
            "melhore os 4 sem exceção (ciclo de um só autocarro)."
            if regresses
            else ""
        )
        note = (
            f"Proposta de horário otimizado ({optimization_desc}): espera mediana "
            f"{cur_summary['median']:.1f} -> {opt_summary['median']:.1f} min, cobertura <=10min "
            f"{cur_summary['coverage10']:.1f}% -> {opt_summary['coverage10']:.1f}%.{caveat}"
        )
        optimization_payload = {
            "note": note,
            "timeline": timeline_indices,
            "waits": waits_indices,
            "equity": equity_indices,
        }

    return fig_timeline, fig_wait, fig_heat, optimization_payload, waits_df


def create_combined_integration_dashboard(
    output_path: Path | str,
    timeline_fig: object,
    waits_fig: object,
    equity_fig: object,
    optimization: dict | None = None,
    reverse: dict | None = None,
) -> str:
    """Create a single HTML page with timeline, waits and equity in one document.

    `optimization` (opcional) descreve a comparação "horário atual vs. otimizado" já embutida
    nas figuras (como traces extra com `visible=False`) - deve ter as chaves `note` (texto),
    `current_indices`/`optimized_indices` por figura (`timeline`, `waits`, `equity`), cada uma
    uma lista de índices de traces. Sem isto, o botão de alternância não é mostrado.

    `reverse` (opcional) descreve o sentido inverso (bus->metro, ver
    `build_reverse_stop_vs_metro_table`) a mostrar como 3 painéis extra na mesma página - deve
    ter as chaves `timeline_fig`/`waits_fig`/`equity_fig` e opcionalmente `optimization` (mesmo
    formato do parâmetro acima). Sem isto, a página só mostra o sentido metro->bus.
    """
    if pio is None:
        raise ImportError("plotly.io nao esta disponivel para gerar visualizacoes")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    import json

    def _js_string_literal(text: str) -> str:
        # json.dumps produces a valid, fully-escaped JS string literal (quotes, backslashes,
        # newlines...); only "</" still needs manual escaping so the note can never prematurely
        # close the surrounding <script> tag if it ever contained that substring.
        return json.dumps(text, ensure_ascii=False).replace("</", "<\\/")

    def _optimization_indices_json(opt: dict | None) -> str:
        if not opt:
            return "{}"
        return json.dumps(
            {
                "timeline": opt.get("timeline", {}),
                "waits": opt.get("waits", {}),
                "equity": opt.get("equity", {}),
            },
            ensure_ascii=False,
        )

    page = _read_template("integration_dashboard.html")
    page = page.replace("__TIMELINE_JSON__", pio.to_json(timeline_fig))
    page = page.replace("__WAITS_JSON__", pio.to_json(waits_fig))
    page = page.replace("__EQUITY_JSON__", pio.to_json(equity_fig))
    page = page.replace("__HAS_OPTIMIZATION__", "true" if optimization else "false")
    page = page.replace("__OPTIMIZATION_NOTE__", _js_string_literal(str(optimization.get("note", "")) if optimization else ""))
    page = page.replace("__OPTIMIZATION_INDICES__", _optimization_indices_json(optimization))

    page = page.replace("__HAS_REVERSE__", "true" if reverse else "false")
    if reverse:
        page = page.replace("__TIMELINE_REV_JSON__", pio.to_json(reverse["timeline_fig"]))
        page = page.replace("__WAITS_REV_JSON__", pio.to_json(reverse["waits_fig"]))
        page = page.replace("__EQUITY_REV_JSON__", pio.to_json(reverse["equity_fig"]))
        rev_opt = reverse.get("optimization")
        page = page.replace("__HAS_OPTIMIZATION_REV__", "true" if rev_opt else "false")
        page = page.replace("__OPTIMIZATION_NOTE_REV__", _js_string_literal(str(rev_opt.get("note", "")) if rev_opt else ""))
        page = page.replace("__OPTIMIZATION_INDICES_REV__", _optimization_indices_json(rev_opt))
    else:
        page = page.replace("__TIMELINE_REV_JSON__", "null")
        page = page.replace("__WAITS_REV_JSON__", "null")
        page = page.replace("__EQUITY_REV_JSON__", "null")
        page = page.replace("__HAS_OPTIMIZATION_REV__", "false")
        page = page.replace("__OPTIMIZATION_NOTE_REV__", '""')
        page = page.replace("__OPTIMIZATION_INDICES_REV__", "{}")

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
    phase_shift_min: float | None = None,
    phase_shift_line: str = "54",
    reverse_metro_direction_id: int | None = None,
) -> dict[str, str]:
    """
    Gera visualizacoes de coordenacao metro -> autocarro e grava HTML em outputs/integration.

    `phase_shift_min` (opcional): se indicado, gera também uma proposta de horário otimizado -
    desloca só os horários de `phase_shift_line` por `phase_shift_min` minutos (mesmo número de
    viagens, mesmo ciclo) e embute um botão "Atual/Otimizado" em cada visualização.
    Ver `config.LINE_54_OPTIMIZED_PHASE_SHIFT_MIN` para o valor e o raciocínio por trás dele.

    `reverse_metro_direction_id` (opcional): se indicado (0 ou 1, conforme `trips.direction_id`
    do Metrobus), gera TAMBÉM o sentido inverso (bus->metro - ver
    `build_reverse_stop_vs_metro_table`) como 3 painéis extra na mesma página, cada um com o seu
    próprio botão Atual/Otimizado. Sem isto, só sai o sentido metro->bus (comportamento anterior).

    Retorna um dicionario com os caminhos dos ficheiros gerados.
    """
    if px is None or go is None or pio is None:
        raise ImportError("plotly nao esta disponivel para gerar visualizacoes")

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
    # CSVs ficam separados por subpasta consoante representem o horário atual ou a proposta
    # otimizada - "otimizado" só é criada se `phase_shift_min` vier a produzir algum ficheiro.
    atual_dir = out_root / "atual"
    atual_dir.mkdir(parents=True, exist_ok=True)

    schedule_df = build_line_stop_vs_metro_table(
        metro_stop_ref=metro_stop_ref,
        bus_stop_ref=bus_stop_ref,
        line_number=line_number,
        day_str=day_str,
        metro_origin_ref=metro_origin_ref,
        bus_origin_ref=bus_origin_ref,
        output_dir=atual_dir,
    )
    metrics_df = build_metro_bus_connection_metrics(
        metro_stop_ref=metro_stop_ref,
        bus_stop_ref=bus_stop_ref,
        line_number=line_number,
        day_str=day_str,
        metro_origin_ref=metro_origin_ref,
        bus_origin_ref=bus_origin_ref,
        output_dir=atual_dir,
    )

    # Always bind displayed date to the shared nearest-business-day policy.
    sample_date = resolve_reference_day().strftime("%Y-%m-%d")
    line_display = _line_display(line_number)
    prefix = output_prefix or f"l{_safe_slug(line_display)}"

    if "bus_line_passage" in schedule_df.columns:
        bus_line_col = schedule_df["bus_line_passage"].astype(str).str.strip()
    else:
        bus_line_col = schedule_df["bus_line"].astype(str).str.strip()
    bus_lines_unique = [v for v in bus_line_col.tolist() if v]
    bus_lines_unique = list(dict.fromkeys(bus_lines_unique))
    if not bus_lines_unique:
        bus_lines_unique = [line_display]

    apply_optimization = phase_shift_min is not None and phase_shift_line in bus_lines_unique
    schedule_df_opt = (
        _shift_schedule_bus_times(schedule_df, phase_shift_line, phase_shift_min)
        if apply_optimization
        else None
    )
    n_trips = int((bus_line_col == phase_shift_line).sum()) if apply_optimization else 0
    optimization_desc = (
        f"linha {phase_shift_line}, desvio de {phase_shift_min:+.0f} min face ao horário atual, "
        f"mesmas {n_trips} viagens/dia e mesmo ciclo de 40 min - sem autocarros ou motoristas "
        f"extra; horário noturno fora de âmbito por agora"
        if apply_optimization
        else None
    )

    fig_timeline, fig_wait, fig_heat, optimization_payload, waits_df = _build_direction_figures(
        schedule_df,
        schedule_df_opt,
        metro_row_label=f"Metro ({metro_origin_ref} -> {metro_stop_ref})",
        bus_lines_unique=bus_lines_unique,
        sample_date=sample_date,
        timeline_title=f"Frequência de Passagens ({sample_date})",
        wait_title=f"Espera até ao Próximo Autocarro ({sample_date})",
        equity_title=f"Equidade Temporal de Ligações ({sample_date})",
        optimization_desc=optimization_desc,
        wait_trigger_label="Hora de chegada do metro",
        wait_target_label="Próximo autocarro",
        wait_target_line_label="Linha",
    )

    reverse_payload = None
    waits_df_rev: pd.DataFrame | None = None
    if reverse_metro_direction_id is not None:
        schedule_df_rev = build_reverse_stop_vs_metro_table(
            bus_stop_ref=bus_stop_ref,
            metro_stop_ref=metro_stop_ref,
            line_number=line_number,
            metro_direction_id=reverse_metro_direction_id,
            day_str=day_str,
            bus_origin_ref=bus_origin_ref,
            output_dir=atual_dir,
        )
        apply_optimization_rev = phase_shift_min is not None
        schedule_df_rev_opt = (
            _shift_reverse_schedule_bus_arrivals(schedule_df_rev, phase_shift_min)
            if apply_optimization_rev
            else None
        )
        optimization_desc_rev = (
            f"linha {phase_shift_line}, desvio de {phase_shift_min:+.0f} min face ao horário "
            f"atual, mesmas {n_trips or len(schedule_df_rev)} viagens/dia e mesmo ciclo de 40 "
            f"min - sem autocarros ou motoristas extra; horário noturno fora de âmbito por agora"
            if apply_optimization_rev
            else None
        )
        fig_timeline_rev, fig_wait_rev, fig_heat_rev, optimization_payload_rev, waits_df_rev = _build_direction_figures(
            schedule_df_rev,
            schedule_df_rev_opt,
            metro_row_label=f"Autocarro {line_display} (chegada a {bus_stop_ref})",
            bus_lines_unique=["Metro"],
            sample_date=sample_date,
            timeline_title=f"Frequência de Passagens - sentido inverso ({sample_date})",
            wait_title=f"Espera até à Próxima Partida de Metro ({sample_date})",
            equity_title=f"Equidade Temporal de Ligações - sentido inverso ({sample_date})",
            optimization_desc=optimization_desc_rev,
            bus_row_label_prefix="",
            wait_trigger_label="Hora de chegada do autocarro",
            wait_target_label="Próxima partida de metro",
            wait_target_line_label="Sentido",
        )
        reverse_payload = {
            "timeline_fig": fig_timeline_rev,
            "waits_fig": fig_wait_rev,
            "equity_fig": fig_heat_rev,
            "optimization": optimization_payload_rev,
        }

    waits_csv_path = atual_dir / f"{prefix}_wt.csv"
    schedule_csv_path = atual_dir / (
        f"line_{_safe_slug(line_number)}_bus_{_safe_slug(bus_stop_ref)}"
        f"_metro_{_safe_slug(metro_stop_ref)}.csv"
    )
    metrics_csv_path = atual_dir / (
        f"line_{_safe_slug(line_number)}_connection_metrics_"
        f"{_safe_slug(bus_stop_ref)}_vs_{_safe_slug(metro_stop_ref)}.csv"
    )

    waits_df.to_csv(waits_csv_path, index=False)
    if apply_optimization:
        otimizado_dir = out_root / "otimizado"
        otimizado_dir.mkdir(parents=True, exist_ok=True)
        (otimizado_dir / f"{prefix}_wt_otimizado.csv").write_text(
            _build_waits_table(schedule_df_opt).to_csv(index=False), encoding="utf-8"
        )
    if waits_df_rev is not None:
        waits_df_rev.to_csv(atual_dir / f"{prefix}_wt_reverso.csv", index=False)

    combined_name = fixed_html_name or f"{prefix}_all.html"
    combined_path = out_root / combined_name
    create_combined_integration_dashboard(
        output_path=combined_path,
        timeline_fig=fig_timeline,
        waits_fig=fig_wait,
        equity_fig=fig_heat,
        optimization=optimization_payload,
        reverse=reverse_payload,
    )

    return {
        "output_dir": str(out_root),
        "schedule_csv": str(schedule_csv_path),
        "metrics_csv": str(metrics_csv_path),
        "combined_html": str(combined_path),
        "waits_csv": str(waits_csv_path),
        "metrics_rows": str(len(metrics_df)),
    }

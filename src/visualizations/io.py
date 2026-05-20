from __future__ import annotations

from pathlib import Path

try:
    import plotly.io as pio
except Exception:  # pragma: no cover - optional dependency guard
    pio = None


_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _read_template(template_name: str) -> str:
    template_path = _TEMPLATE_DIR / template_name
    return template_path.read_text(encoding="utf-8")


def _write_readable_plotly_html(
    fig: object,
    output_path: Path | str,
    title: str = "Visualization",
) -> None:
    """
    Write a readable Plotly figure to an HTML file with dark mode protection.

    Args:
        fig: Plotly figure object
        output_path: Path where to save the HTML file
        title: HTML page title
    """
    if pio is None:
        raise ImportError("plotly.io não está disponível")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig_json = pio.to_json(fig)
    html_content = _read_template("plotly_single.html")
    html_content = html_content.replace("__TITLE__", str(title))
    html_content = html_content.replace("__FIGURE_JSON__", fig_json)
    output_path.write_text(html_content, encoding="utf-8")


def _write_folium_html(map_obj: object, output_path: Path | str, footer_html: str | None = None) -> None:
    """Write a Folium map to an HTML file and optionally append footer HTML below the map.

    Args:
        map_obj: Folium map object
        output_path: Path where to save the HTML file
        footer_html: Optional HTML string to append after the map (e.g., tables or summaries)
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Save map to file first
    map_obj.save(str(output_path))

    if not footer_html:
        return

    try:
        # Read the generated file and append footer HTML before closing body
        text = output_path.read_text(encoding="utf-8")
        insert_at = text.rfind("</body>")
        if insert_at == -1:
            # Fallback: append at end
            new_text = text + "\n" + footer_html
        else:
            new_text = text[:insert_at] + footer_html + "\n" + text[insert_at:]
        output_path.write_text(new_text, encoding="utf-8")
    except Exception:
        # If anything goes wrong, keep the originally saved map and do not raise
        return

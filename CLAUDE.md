# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Data analysis + interactive HTML visualization project studying public transit in Coimbra (Portugal): overlap between SMTUC bus lines and the new Metrobus, population coverage gaps (BGRI census data), reachability from key points, and timetable integration between bus line 54 and Metrobus at Portela/Portagem. Code, comments and docstrings are in Portuguese (PT-PT).

## Environment & commands

Python env is a conda env named `smtuc312`. On this machine the interpreter is at:
```
C:/Users/migue/miniconda3/envs/smtuc312/python.exe
```

Install dependencies:
```
pip install -r requirements.txt
```

Run tests (`pythonpath = src` in `pytest.ini` adds `src/` to `sys.path`, so tests import modules directly, e.g. `from overlap.transit import ...` - no manual `PYTHONPATH` needed):
```
pytest
pytest -m "not integration"          # skip tests needing real GTFS data on disk
pytest -m integration                 # only integration tests (read-only against data/)
pytest src/tests/test_overlap.py::test_name   # single test
```

Regenerate every HTML output (population, overlap/reachability, line-54 integration, master + presentation dashboards) in one go:
```
python src/tests/regenerate_all_htmls.py
```

Serve `outputs/` locally to view generated HTML in a browser:
```
C:/Users/migue/miniconda3/envs/smtuc312/python.exe -m http.server 8000
```
Then open e.g. `http://localhost:8000/outputs/dashboard.html`. All dates shown in visualizations are computed automatically as "nearest weekday" (see `resolve_reference_day` in `overlap/transit.py`, the single canonical implementation), never hardcoded.

## Architecture

**Data flow**: raw GTFS feeds in `data/smtuc/` and `data/metrobus/` → `gtfs_processing/gtfs.py` (`load_gtfs`) parses them into a `GTFSData` dataclass → `overlap/overlap_db.py` builds a cached line-metrics table (`build_line_metrics_db`, persisted to `outputs/overlap/line_metrics_db.csv`, plus an in-memory `lru_cache` over `load_gtfs`) → `overlap/overlap.py` computes overlap %, reachability, and stadium-proximity queries on top of that table → `overlap/transit.py` builds line-vs-metro schedule comparison tables (spatial + temporal overlap, walking transfer windows) → `visualizations/*.py` renders Folium maps and Plotly figures → `visualizations/io.py` writes the HTML (`_write_folium_html`, `_write_readable_plotly_html`, using templates from `visualizations/templates/`) → `visualizations/dashboard.py` assembles the master and presentation dashboards from the individual views.

Population analysis is a separate track: `population/data_processing.py` loads the BGRI census grid (`data/dadospopulacaoBGRI/*.gpkg`) and joins it against transit stop buffers (`CATCHMENT_M`) to compute `compute_underserved_zones` — population living outside walking distance of any stop. `population/_common.py` has shared helpers (`_project_root`, `_require_bgri_data`, `_require_geo_stack`). It uses `resolve_reference_day` (imported from `overlap/transit.py`) for its reference day, same as every other visualization — there used to be a separate `_next_monday` helper here that picked the next Monday instead of the nearest weekday, which silently diverged from the rest of the pipeline; it was removed.

**Tunable parameters live in one place**: `src/config.py` centralizes all thresholds used across modules — walk speed, spatial/temporal overlap windows, reachability limits (max minutes, transfers, boarding/transfer walk), the stadium/home/work reference coordinates, and every output path. Changing behavior almost always starts here rather than in the consuming module. Note `config.py` also carries a docstring at the bottom listing the manual dev commands (http.server invocation, output URLs) — treat it as the informal runbook, not just settings.

**Import style differs by entrypoint**: modules under `src/` import each other without the `src.` prefix (e.g. `from overlap.transit import ...`), relying on `src/` being on `sys.path` (added by `pytest_conftest.py`, or implicitly when running scripts from within `src/tests/`). `src/tests/regenerate_all_htmls.py`, run from the repo root, instead imports config as `from src.config import ...`. Keep this distinction in mind when adding new inter-module imports or new entrypoint scripts.

**Reference-day resolution**: schedules are always evaluated against a dynamically computed reference day (`resolve_reference_day` in `overlap/transit.py` — the single shared implementation used by every dashboard, population included) rather than a fixed date, so regenerated visualizations stay current.

**Optional/guarded dependencies**: geospatial (`geopandas`) and BGRI data availability are checked at runtime via `_require_geo_stack` / `_require_bgri_data` and GTFS dataset completeness via `_require_dataset` (checking for `routes.txt`, `trips.txt`, `stops.txt`, `stop_times.txt`) — code degrades to warnings/skips rather than hard failures when these are missing, which is why `regenerate_all_htmls.py` and integration tests wrap generation steps in try/except per section.

## Open work

See README.md's "O que falta fechar" section for the current state of in-progress presentation/visualization work (line overlap map, isochrones, line 54 Portela/Portagem integration, final report). Note: README links to `mockups_apresentacao.md`, but that file is currently deleted in the working tree (shows as `D` in `git status`) — check with the user before assuming it should be restored or that the link is stale.
from __future__ import annotations

WALK_SPEED_M_MIN = 80.0
TEMPORAL_OVERLAP_MAX_MIN = 5.0

HOME_COORD = (40.207883, -8.398107)
WORK_COORD = (40.186724, -8.416078)
STADIUM_COORD = (40.203809, -8.407904)

OVERLAP_TABLE_TOP_N = 5
OVERLAP_SCAN_TOP_N = 10000
UNDERSERVED_TOP_N = 20
STADIUM_RADIUS_M  = 2000.0
CATCHMENT_M = 500.0
STADIUM_MIN_EXTENSION_PCT = 50.0

OUTPUTS_ROOT_DIR = "outputs"
OUTPUTS_POPULATION_DIR = "outputs/population"
OUTPUTS_OVERLAP_DIR = "outputs/overlap"

LINE_METRICS_DB_PATH = "outputs/overlap/line_metrics_db.csv"
DEFAULT_BGRI_GPKG_PATH = "data/dadospopulacaoBGRI/BGRI2021_0603.gpkg"
DEFAULT_BGRI_LAYER = "BGRI2021_0603"
DEFAULT_OUTPUT_GAP_CSV = "outputs/population/bgri_transport_gap.csv"


r"""

COmandos para gerar as visualizações:

Set-Location "C:\Users\migue\OneDrive\Documentos\trabalho\side quests\smtuc 2.0"; C:/Users/migue/miniconda3/envs/smtuc312/python.exe -m http.server 8000

Links visualizações:

http://localhost:8000/outputs/overlap/overlap_reachability_now.html
http://localhost:8000/outputs/population/2kmstadium.html
http://localhost:8000/outputs/population/bgri_population_heatmap.html
http://localhost:8000/outputs/population/bgri_population_vs_supply_scatter.html
http://localhost:8000/outputs/population/bgri_underservice_choropleth.html
http://localhost:8000/outputs/population/bgri_underservice_dense_population.html
"""
from __future__ import annotations

WALK_SPEED_M_MIN = 80.0
TEMPORAL_OVERLAP_MAX_MIN = 5.0

HOME_COORD = (40.207883, -8.398107)
WORK_COORD = (40.186724, -8.416078)
STADIUM_COORD = (40.203809, -8.407904)
#meter coords outros sitos relevante, vale das flores, chuc, fuck it rebolim, etc
OVERLAP_TABLE_TOP_N = 5
OVERLAP_SCAN_TOP_N = 10000
UNDERSERVED_TOP_N = 20
STADIUM_RADIUS_M  = 2000.0
CATCHMENT_M = 500.0
STADIUM_MIN_EXTENSION_PCT = 50.0

OUTPUTS_ROOT_DIR = "outputs"
OUTPUTS_POPULATION_DIR = "outputs/population"
OUTPUTS_OVERLAP_DIR = "outputs/overlap"
OUTPUTS_INTEGRATION_DIR = "outputs/integration"

LINE_METRICS_DB_PATH = "outputs/overlap/line_metrics_db.csv"
DEFAULT_BGRI_GPKG_PATH = "data/dadospopulacaoBGRI/BGRI2021_0603.gpkg"
DEFAULT_BGRI_LAYER = "BGRI2021_0603"
DEFAULT_OUTPUT_GAP_CSV = "outputs/population/bgri_transport_gap.csv"


r"""

COmandos para gerar as visualizações:

Set-Location "C:\Users\migue\OneDrive\Documentos\trabalho\side quests\smtuc 2.0"; 
C:/Users/migue/miniconda3/envs/smtuc312/python.exe -m http.server 8000

Links visualizações:

Nota: todas as datas mostradas nas visualizações são calculadas automaticamente pela função de dia útil mais próximo (resolve_reference_day).

http://localhost:8000/outputs/overlap/overlap_reachability_now.html
http://localhost:8000/outputs/population/bgri.html

Views integração (linha 54, data útil automática):

Portela (Portagem -> Portela do Mondego/Portela):
http://localhost:8000/outputs/integration/portela/l54_all.html

Portagem (Portela do Mondego/Portela -> Portagem):
http://localhost:8000/outputs/integration/portagem/l54_portagem_all.html

Cada página agrega as 3 análises no mesmo HTML:
 - Timeline
 - Espera de transbordo
 - Equidade temporal
"""
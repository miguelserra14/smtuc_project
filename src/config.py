from __future__ import annotations

WALK_SPEED_M_MIN = 80.0
TEMPORAL_OVERLAP_MAX_MIN = 5.0

# Reachability tuning parameters
REACHABILITY_MAX_MIN = 60.0
REACHABILITY_MAX_BOARDING_WALK_MIN = 10.0
REACHABILITY_MAX_TRANSFER_WALK_MIN = 5.0
REACHABILITY_MAX_TRANSFERS = 2

# Dia/hora de referência partilhados por TODAS as visualizações com horários GTFS, resolvidos via
# resolve_reference_day() (overlap/transit.py). USE_FIXED_REFERENCE_DAY=True usa o dia/hora fixos
# abaixo (reprodutível); False usa o dia útil mais próximo de "hoje" (dinâmico).
USE_FIXED_REFERENCE_DAY: bool = True
REACHABILITY_REFERENCE_DAY: str | None = "2026-05-11"
REACHABILITY_REFERENCE_TIME: str | None = "08:20:00"

# Minutos de caminhada para considerar uma paragem/segmento SMTUC "perto" de uma paragem Metrobus -
# fonte única de todo o overlap espacial (overlap_pct, candidatos temporais, eventos); não
# duplicar esta constante. Usado como `walk_speed_m_min * SPATIAL_OVERLAP_WALK_MIN`.
SPATIAL_OVERLAP_WALK_MIN = 3.0

HOME_COORD = (40.207883, -8.398107)
WORK_COORD = (40.186724, -8.416078)
STADIUM_COORD = (40.203809, -8.407904)
#meter coords outros sitos relevante, vale das flores, chuc, fuck it rebolim, etc
#dps clarificar aqui melhor que metricas servem para que
OVERLAP_TABLE_TOP_N = 5
OVERLAP_SCAN_TOP_N = 10000
UNDERSERVED_TOP_N = 20
STADIUM_RADIUS_M  = 2000.0
CATCHMENT_M = 500.0
STADIUM_MIN_EXTENSION_PCT = 50.0

# Raio do painel "Estádio a X km" na dashboard de população - propositadamente separado de
# STADIUM_RADIUS_M, que é partilhado por outras análises que não devem mudar de raio só por
# causa deste painel específico.
POPULATION_STADIUM_MAP_RADIUS_M = 3000.0

OUTPUTS_ROOT_DIR = "outputs"
OUTPUTS_POPULATION_DIR = "outputs/population"
OUTPUTS_OVERLAP_DIR = "outputs/overlap"
OUTPUTS_INTEGRATION_DIR = "outputs/integration"
OUTPUTS_OVERLAP_LINES_MAP = "outputs/overlap/overlap_lines_map.html"

LINE_METRICS_DB_PATH = "outputs/overlap/line_metrics_db.csv"
DEFAULT_BGRI_GPKG_PATH = "data/dadospopulacaoBGRI/BGRI2021_0603.gpkg"
DEFAULT_BGRI_LAYER = "BGRI2021_0603"
DEFAULT_OUTPUT_GAP_CSV = "outputs/population/bgri_transport_gap.csv"

# Catálogo de polos de emprego e outros locais concorridos (ver population/points_of_interest.py
# para a fonte/raciocínio de cada estimativa - este CSV é gerado a partir desse ficheiro).
POINTS_OF_INTEREST_CSV = "data/points_of_interest.csv"

# Desvio de fase (min) do horário otimizado da linha 54 em Portela/Portagem - mesmo nº de viagens
# e ciclo de 40 min, só desloca a partida. -16 min é o melhor compromisso achado por busca
# exaustiva de fase (-20 a +20 min) nos 4 sentidos de transbordo: regride ligeiramente só 1 deles.
LINE_54_OPTIMIZED_PHASE_SHIFT_MIN = -16.0

# Desvio de fase (min) da proposta "melhorado": assume um 2º autocarro no ciclo (dobra a
# frequência de 40 para 20 min, +1 autocarro/motorista). -8 min é o único desvio, dos 20
# possíveis, que melhora os 4 sentidos de transbordo em simultâneo, sem nenhuma regressão.
LINE_54_MELHORADO_PHASE_SHIFT_MIN = -8.0

# Parede FeedNPlay (feednplay_dashboard.html) - toggles independentes: FEEDNPLAY_CLICK_TO_ADVANCE
# liga/desliga poder clicar/tocar nas zonas ◀/▶ (o dwell fica sempre ativo); FEEDNPLAY_PREVIEW_MODE
# troca a escala de fonte da parede por um tamanho de secretária normal, para pré-visualizar no PC.
FEEDNPLAY_CLICK_TO_ADVANCE: bool = True
FEEDNPLAY_PREVIEW_MODE: bool = True
FEEDNPLAY_PREVIEW_BASE_FONT_PX = 16


r"""

COmandos para gerar as visualizações:

Set-Location "C:\Users\migue\OneDrive\Documentos\trabalho\side quests\smtuc 2.0"; 
C:/Users/migue/miniconda3/envs/smtuc312/python.exe -m http.server 8000

Links visualizações:

Nota: todas as datas mostradas nas visualizações vêm de resolve_reference_day(), controlada pela
variável global USE_FIXED_REFERENCE_DAY acima - por omissão (True) usam todas o dia fixo
REACHABILITY_REFERENCE_DAY; com a flag a False usam o dia útil mais próximo de "hoje".

http://localhost:8000/outputs/overlap/overlap_reachability_now.html
http://localhost:8000/outputs/overlap/overlap_lines_map.html
http://localhost:8000/outputs/overlap/overlap_temporal_breakdown.html
http://localhost:8000/outputs/population/bgri.html

http://localhost:8000/outputs/dashboard.html

Views integração (linha 54, dia de referência controlado por USE_FIXED_REFERENCE_DAY):

Portela (Portagem -> Portela do Mondego/Portela):
http://localhost:8000/outputs/integration/portela/l54_all.html
Portagem (Portela do Mondego/Portela -> Portagem):
http://localhost:8000/outputs/integration/portagem/l54_portagem_all.html

Cada página agrega as 2 análises no mesmo HTML, para os sentidos metro->bus e bus->metro:
 - Espera de transbordo
 - Equidade temporal
"""
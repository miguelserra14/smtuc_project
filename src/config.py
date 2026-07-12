from __future__ import annotations

WALK_SPEED_M_MIN = 80.0
TEMPORAL_OVERLAP_MAX_MIN = 5.0

# Reachability tuning parameters
REACHABILITY_MAX_MIN = 60.0
REACHABILITY_MAX_BOARDING_WALK_MIN = 10.0
REACHABILITY_MAX_TRANSFER_WALK_MIN = 5.0
REACHABILITY_MAX_TRANSFERS = 2

# Dia/hora de referência partilhados por TODAS as visualizações que dependem de horários GTFS
# (integração linha 54↔metro, mapa de isócronas, população/BGRI) - resolvidos através de
# resolve_reference_day() em overlap/transit.py, a única implementação usada por todos os
# módulos (ver docstring dessa função). USE_FIXED_REFERENCE_DAY é a variável global que escolhe
# entre os dois modos, sem tocar em resolve_reference_day() nem em nenhum chamador individual:
#   True  -> todas usam o dia (e, no caso do mapa de isócronas, a hora) fixos abaixo -
#            reprodutível, não depende de quando o script é corrido nem do horário de verão em
#            vigor nesse dia. 2026-05-11 08:20 é uma manhã de dia útil em horário de verão.
#   False -> todas usam o dia útil mais próximo de "hoje" (comportamento dinâmico); o mapa de
#            isócronas usa a hora atual em vez de REACHABILITY_REFERENCE_TIME.
USE_FIXED_REFERENCE_DAY: bool = True
REACHABILITY_REFERENCE_DAY: str | None = "2026-05-11"
REACHABILITY_REFERENCE_TIME: str | None = "08:20:00"

# Spatial overlap: how many minutes of walking to consider when testing whether a SMTUC
# stop/segment is "near" a Metrobus stop. Single source of truth for every spatial-overlap
# radius in the codebase (line overlap_pct, temporal overlap candidates, overlap events) -
# do not reintroduce a second constant for this, it previously caused the radius used for
# the aggregate temporal-overlap percentage to silently diverge from the radius used for the
# per-event breakdown. (used as `walk_speed_m_min * SPATIAL_OVERLAP_WALK_MIN`). Default: 3 minutes.
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

# Raio do painel "Estádio a X km" na dashboard de população (o mapa de subserviço mais
# restrito, centrado no estádio). Propositadamente separado de STADIUM_RADIUS_M - esse é
# partilhado por outras análises (overlap de linhas perto do estádio, círculo no mapa de
# linhas) que não devem mudar só porque este painel específico muda de raio.
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

# Desvio de fase (minutos) da proposta de horário otimizado da linha 54 em Portela/Portagem.
# Mantém o mesmo número de viagens/dia e o mesmo ciclo de 40 min (zero autocarros/motoristas
# extra) - só desloca a hora de partida. Escolhido por pesquisa exaustiva de fase (-20 a +20
# min, passo de 1 min) sobre os horários reais GTFS, validada nos 4 sentidos de transbordo
# possíveis (metro->bus e bus->metro, em Portela E em Portagem - duas escolhas anteriores, -6 e
# depois -10, só tinham sido validadas em 1-2 desses 4 sentidos e continham regressões que só
# apareceram ao verificar os 4 ao mesmo tempo). Testei exaustivamente (busca completa de -20 a
# +19 min) se existe algum desvio que melhore os 4 sentidos SEM NENHUMA regressão - não existe
# nenhum: é uma restrição real do ciclo de 40 min de um único autocarro, não uma falha de busca.
# -16 min é o melhor compromisso encontrado: só regride ligeiramente 1 dos 4 sentidos, e por uma
# margem mínima, enquanto melhora bastante os outros 3:
#   Portela  metro->bus: 16.0 -> 10.0 min (melhor, -6.0)   bus->metro: 14.0 -> 10.0 min (melhor, -4.0)
#   Portagem metro->bus: 19.5 -> 20.0 min (pior, +0.5)     bus->metro: 12.0 ->  8.0 min (melhor, -4.0)
# Portela e Portagem são servidos pelo MESMO autocarro em ciclo fechado (Portagem->Portela->
# Portagem sem folga), por isso partilham uma única variável de fase - não podem ser otimizados
# de forma totalmente independente com a frota atual. Horário noturno (após a última viagem
# atual) deliberadamente fora desta proposta por agora - fica para uma iteração futura que
# envolva expandir o período de serviço.
LINE_54_OPTIMIZED_PHASE_SHIFT_MIN = -16.0

# Desvio de fase (minutos) da proposta "melhorado" da linha 54 em Portela/Portagem: em vez de só
# reajustar o horário de UM autocarro no ciclo de 40 min (LINE_54_OPTIMIZED_PHASE_SHIFT_MIN),
# esta proposta assume um SEGUNDO autocarro no mesmo ciclo (Portagem->Portela->Portagem),
# desfasado 20 min do primeiro - dobra a frequência de 40 para 20 min. Implica +1 autocarro/
# motorista face ao atual, ao contrário da proposta "otimizado". Como a frequência duplicada tem
# período de 20 min (não 40), o desvio de fase só tem 20 valores possíveis (não 40) - testei os
# 20 exaustivamente sobre os horários reais GTFS, nos mesmos 4 sentidos de transbordo. Ao
# contrário do caso de um único autocarro, aqui EXISTE um desvio que melhora os 4 sentidos em
# simultâneo, sem nenhuma exceção - a folga extra do 2º autocarro é suficiente para desfazer o
# acoplamento rígido entre Portela e Portagem que impede uma vitória pura na proposta "otimizado":
#   Portela  metro->bus: 16.0 -> 13.0 min (-3.0)    bus->metro: 14.0 -> 12.0 min (-2.0)
#   Portagem metro->bus: 19.5 ->  9.0 min (-10.5)   bus->metro: 12.0 -> 10.0 min (-2.0)
# Horário noturno (após a última viagem atual) deliberadamente fora desta proposta por agora,
# tal como na "otimizado".
LINE_54_MELHORADO_PHASE_SHIFT_MIN = -8.0


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
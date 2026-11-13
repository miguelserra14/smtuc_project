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

# Feriados (ver gtfs_processing/gtfs_probe._active_service_ids): os feeds GTFS deste projeto não
# marcam os feriados em calendar_dates.txt, por isso sem isto um feriado a uma 6ª feira era
# avaliado com o horário de dia útil. Com FERIADOS_COMO_DOMINGO=True, nesses dias usa-se o
# serviço de domingo ("Domingos e Feriados") - exceto se o próprio feed já tiver uma exceção em
# calendar_dates.txt para essa data (aí manda o feed). Os feriados móveis são calculados a partir
# da Páscoa de cada ano (offset em dias), por isso não é preciso atualizar esta lista todos os anos.
FERIADOS_COMO_DOMINGO: bool = True
FERIADOS_FIXOS_MMDD: tuple[str, ...] = (
    "01-01",  # Ano Novo
    "04-25",  # Dia da Liberdade
    "05-01",  # Dia do Trabalhador
    "06-10",  # Dia de Portugal
    "08-15",  # Assunção de Nossa Senhora
    "10-05",  # Implantação da República
    "11-01",  # Todos os Santos
    "12-01",  # Restauração da Independência
    "12-08",  # Imaculada Conceição
    "12-25",  # Natal
    "07-04",  # Feriado municipal de Coimbra (Rainha Santa Isabel)
)
FERIADOS_MOVEIS_OFFSET_PASCOA: tuple[int, ...] = (
    -2,  # Sexta-feira Santa
    0,  # Domingo de Páscoa
    60,  # Corpo de Deus
)

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

# Frequência média das linhas (coluna avg_freq_min / "Frequência média (min)" nos dashboards), ver
# overlap_db._line_avg_frequency_min: no dia de referência, por sentido, mediana dos intervalos
# entre passagens numa paragem de referência dentro desta janela horária [início, fim); o valor da
# linha é a média dos sentidos. A janela evita que os buracos da noite/madrugada distorçam o valor.
FREQUENCY_WINDOW_START_H = 7
FREQUENCY_WINDOW_END_H = 20
DEFAULT_BGRI_GPKG_PATH = "data/dadospopulacaoBGRI/BGRI2021_0603.gpkg"
DEFAULT_BGRI_LAYER = "BGRI2021_0603"
DEFAULT_OUTPUT_GAP_CSV = "outputs/population/bgri_transport_gap.csv"

# Catálogo de polos de emprego e outros locais concorridos (ver population/points_of_interest.py
# para a fonte/raciocínio de cada estimativa - este CSV é gerado a partir desse ficheiro).
POINTS_OF_INTEREST_CSV = "data/points_of_interest.csv"

# Transbordo metro <-> autocarro (visualizations/integration.py, overlap/transit.py): tempo mínimo
# para mudar de veículo = distância real entre as duas paragens usadas ÷ WALK_SPEED_M_MIN + esta
# margem (sair do veículo, atravessar, chegar antes da partida). Antes assumia-se 0 min - ligações
# "à mesma hora" contavam como perfeitas, apesar de as paragens estarem a 20-250 m.
TRANSFER_BUFFER_MIN = 1.0

# Os 2 nós de integração linha 54 <-> Metrobus analisados (fonte única para
# regenerate_all_htmls.py e scripts/search_phase_shift.py - não duplicar estes argumentos).
INTEGRATION_SITES: tuple[dict, ...] = (
    {
        "name": "Portagem",  # Portela -> Portagem, linhas 54 + 38
        "metro_stop_ref": "Portagem",
        "bus_stop_ref": "Portagem",
        "line_number": ("54", "38"),
        "metro_origin_ref": "Portela",
        "bus_origin_ref": "Portela do Mondego",
        "output_prefix": "l54_38",
        "output_subdir": "portagem",
        "fixed_html_name": "l54_38_all.html",
        "reverse_metro_direction_id": 1,  # Metrobus sentido Serpins, a partir de Portagem
        "reverse_metro_route_id": "LOUSA",  # não confundir com as viagens dos ramais (fase 2)
    },
    {
        "name": "Portela",  # Portagem -> Portela, linha 54
        "metro_stop_ref": "Portela",
        "bus_stop_ref": "Portela do Mondego",
        "line_number": "54",
        "metro_origin_ref": "Portagem",
        "bus_origin_ref": "Portagem",
        "output_prefix": "l54",
        "output_subdir": "portela",
        "fixed_html_name": "l54_all.html",
        "reverse_metro_direction_id": 0,  # Metrobus sentido Portagem, a passar por Portela
        "reverse_metro_route_id": "LOUSA",
    },
)

# Desvios de fase da linha 54 em Portela/Portagem - PROVISÓRIOS: obtidos com o feed Metrobus
# sintético (data/metrobus, sem o serviço urbano nem parte da ponta da tarde). Quando houver dados
# oficiais (Fase 0B do roadmap), correr `scripts/search_phase_shift.py` e atualizar aqui.
# Ambos já contam com o transbordo a pé (TRANSFER_BUFFER_MIN + distância real entre paragens);
# sem ele (regra antiga, `--sem-transbordo`) os ótimos eram -16 e -8.

# "otimizado": mesmo nº de viagens e ciclo de 40 min, só desloca a partida. -11 min é o melhor
# compromisso da busca exaustiva (-20 a +20 min) nos 4 sentidos de transbordo: melhora 3,
# regride ligeiramente 1 (Portela bus->metro, 14 -> 15 min de mediana); menor espera total (58 min
# de soma de medianas, contra 75 com o antigo -16).
LINE_54_OPTIMIZED_PHASE_SHIFT_MIN = -11.0

# "melhorado": 2º autocarro no ciclo (40 -> 20 min, +1 autocarro/motorista). Com transbordo já
# nenhum desvio melhora os 4 sentidos; -10 min é o que melhora sem NENHUMA regressão (melhora 2,
# mantém 2) e tem a menor espera total (54). Alternativa preterida: -9 (melhora 3 mas regride
# Portagem bus->metro de 12 para 21 min; soma 64) - o script ordena primeiro por nº de sentidos
# melhorados, por isso lista -9 à frente; a escolha de -10 privilegia "sem regressões".
LINE_54_MELHORADO_PHASE_SHIFT_MIN = -10.0

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
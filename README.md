# MVP — Alocação eficiente de autocarros e metrobus

visa responder a questao: agora que o metrobus faz parte da mobilidade em coimbra, como adaptar os smtuc a esta mudanca de forma a cobrir as suas mais conhecidas e habituais lacunas, assim como nao so se adaptar a coimbra de hoje mas a de amanha

## to do :
- dados:
- corrigir e limpar dados metrobus: locais das paragens, corrigir horarios, arranjar shape.txt
- atualizar dados smtuc: pq e que da erro no dados.gov?

- gtfs: colocar numa pasta separada? tentar tornar mais pequeno e flexivel

- operations: separar em 2 (route_operations e overlap_operations)
- brincar mais com os dados: sera que o output está certo sequer? como é que ele chegou a estes valores mm? (mt importante na do overlap) 
- fazer com que seja mais facil testar eustoes como:
- como ir de ponto a a b no horario x?
- quais as paragens mais proximas de um ponto a e b?
- qual o alcance de uma paragem em 15min em varios horarios
- vista por linha: frequencia, overlap com o metrobus
- quais as areas c menos overlap? e dessas quais e que se encontram mais no centro da cidade? e quais têm pior frequência?
- começar a pensasr em partes para criar um score final de necessidade com base em população, frequencia, overlap ou falta dele

- visualização
- meter tudo num mapa : linhas, paragens, so smtuc, so metrobus
- conseguir visualizar cada linha e comparar overlap com o metrobus, dar estatisticas em percentagem
- limpar slop: evitar duplicados e fazer com que seja mais facil testar eustoes como:
- como ir de ponto a a b no horario x?
- quais as paragens mais proximas de um ponto a e b?
- qual o alcance de uma paragem em 15min em varios horarios
- vista por linha: frequencia, overlap com o metrobus


# MVP — Alocação eficiente de autocarros e metrobus (Coimbra)

## Enquadramento

Este projeto procura responder à pergunta:

**Agora que o Metrobus faz parte da mobilidade em Coimbra, como adaptar os SMTUC para cobrir lacunas atuais e preparar a cidade para necessidades futuras?**

## Objetivos do MVP

- Integrar e validar dados GTFS de **SMTUC** e **Metrobus**.
- Comparar cobertura e oferta entre as duas redes.
- Testar trajetos reais (A → B) por dia e hora.
- Apoiar decisões de ajuste de linhas e frequências.

## To-Do

### 1: Dados

- [ ] Corrigir e limpar dados do Metrobus:
  - localização das paragens;
  - consistência de horários.
- [ ] Atualizar dados SMTUC:
  - investigar erro no `dados.gov`.
- [ ] Validar consistência GTFS:
  - `stops`, `trips`, `stop_times`, `calendar`, `calendar_dates`.

### 2: Probe (análise)

- [ ] Limpar ruído e evitar duplicados nos resultados.
- [ ] Facilitar testes de perguntas como:
  - como ir de ponto A para B no horário X?
  - quais as paragens mais próximas de A e de B?
  - qual o alcance de uma paragem em 15 min em diferentes horários?
  - vista por linha: frequência e overlap com Metrobus.
- [ ] Melhorar pesquisa para incluir transbordos (além de trajetos diretos).

### 3: Visualização

- [ ] Colocar tudo num mapa:
  - linhas;
  - paragens;
  - filtro SMTUC;
  - filtro Metrobus.
- [ ] Comparar cada linha com overlap Metrobus.
- [ ] Mostrar estatísticas percentuais por linha/corredor.

## Resultado esperado

No fim do MVP, deve ser possível responder com dados a:

- onde o Metrobus já cobre bem a procura;
- onde os SMTUC devem reforçar/adaptar serviço;
- que alterações melhoram tempo de viagem e cobertura.

## Próximos passos (smtuc-vad)

- [ ] smtuc-vad
  - [ ] melhorar london map: menos pesado
    - [ ] trocar cores
  - [ ] refatorizar e limpar bloated
  - [ ] mais dados
    - [ ] relevo
    - [ ] onde é que as pessoas trabalham
  - [ ] visualizações
    - [ ] cores: verde para vermelho
    - [ ] overlaps
    - [ ] índice de subserviço com parte mais densa da cidade

## Checklist técnica de visualização (estado atual)

### Arquitetura e organização

- [x] Visualizações separadas por domínio numa package própria (`src/visualizations`)
- [x] Escrita/export de HTML centralizada em módulo dedicado (`src/visualizations/io.py`)
- [x] Remoção de shims de compatibilidade e APIs públicas mais explícitas
- [ ] Uniformizar imports relativos (`from .module import ...`) em todos os pacotes de `src/`

### Consistência visual

- [x] Escalas robustas a outliers (percentis) para choropleths/scatter
- [x] Paleta semântica consistente no reachability (menos tempo = melhor cor)
- [x] Tooltip com métricas de decisão (intervalo temporal, área, modo dominante)
- [ ] Definir tema visual único (cores/tipografia/margens) para todos os gráficos Plotly/Folium

### Interatividade e performance

- [x] Isócronas dinâmicas com atualização por posição do rato
- [x] Legenda dinâmica com áreas por classe e total agregada
- [x] Otimização de performance com debounce + limiar mínimo de movimento
- [ ] Parametrizar os valores de performance (ex.: `debounceMs`, `minMoveMeters`) no `config.py`

### Qualidade e validação

- [x] Testes de integração para geração das visualizações principais
- [x] Regressão validada após refatores de estrutura de módulos
- [ ] Adicionar smoke test dedicado para garantir presença dos elementos-chave no HTML (legenda, classes, modo)

## Atualizar parâmetros que exigem regeneração

Resumo rápido: muitos parâmetros (ex.: `SPATIAL_OVERLAP_MIN`, `TEMPORAL_OVERLAP_MAX_MIN`, `WALK_SPEED_M_MIN`, `REACHABILITY_MAX_TRANSFERS`) vivem em `src/config.py` e são lidos por várias funções que geram a tabela de métricas em `outputs/overlap/line_metrics_db.csv`.

- Quando alteras um parâmetro que afeta as métricas, é necessário regenerar a tabela e os HTMLs para que as visualizações reflitam a nova configuração.
- O processo automatizado faz isto em dois passos principais:
  1. Recalcular a base de métricas (`build_line_metrics_db`) — que agora popula também as contagens temporais (`temporal_spatial_candidates_count`, `temporal_overlaps_count`) antes de escrever o CSV.
  2. Regenerar os HTMLs (`src/tests/regenerate_all_htmls.py`) que consomem o CSV e reconstroem o mapa e o dashboard.

Comandos úteis:

1) Regenerar tudo (leva alguns segundos/minutos dependendo dos GTFS):

```powershell
$env:PYTHONPATH='.;src'
$env:PYTHONIOENCODING='utf-8'
python src/tests/regenerate_all_htmls.py
```

2) Forçar apenas o recompute da tabela de métricas (útil em desenvolvimento):

```python
from overlap.overlap_db import build_line_metrics_db
df = build_line_metrics_db(force_refresh=True)
```

3) Forçar recompute manual apagando o cache CSV antes de regenerar:

```powershell
del outputs\overlap\line_metrics_db.csv
python src/tests/regenerate_all_htmls.py
```

Notas internas importantes:
- A função `build_line_metrics_db` adiciona metadados `__meta_*` ao CSV para detectar mudanças de parâmetros (por exemplo `__meta_spatial_overlap_min`). Se um parâmetro mudar, o código invalida o cache e re-calcula automaticamente.
- O cálculo de overlap temporal é feito por `compute_temporal_overlaps_for_db` (em `src/overlap/overlap.py`) e é executado automaticamente dentro de `build_line_metrics_db` antes de gravar o CSV.
- Existe um script de watcher simples `scripts/watch_config_regenerate.py` que detecta alterações em `src/config.py` e executa a regeneração automaticamente — podes substituí‑lo por `watchdog`/FS events se preferires uma solução com eventos em vez de polling.
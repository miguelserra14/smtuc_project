# SMTUC: A caminho da complementaridade

A chegada do Metrobus mudou a mobilidade em Coimbra. A fase 1 (Serpins – Portagem) reorganizou fluxos, criou sobreposição em alguns corredores e deixou outras zonas numa posição mais frágil. A fase 2, em operação desde 10/09/2026, levou o metro à Baixa, a Coimbra B e à República. No mesmo dia o SMTUC reorganizou as linhas (o Como Vou). Só o metro fez a extensão de linhas SMTUC a par do metro passar de 104 para 398 km; o Como Vou baixou-a para 338 km. Este trabalho responde a uma pergunta prática e urgente: o que é que o SMTUC pode adaptar já para ter o máximo de utilidade neste novo cenário de mobilidade?

O projeto combina análise de dados populacionais e visualizações interativas para construir uma leitura mais completa da cidade. Em vez de olhar só para linhas ou horários isolados, a abordagem cruza cobertura espacial, sobreposição entre SMTUC e Metrobus, pressão populacional e integração temporal entre serviços. O resultado é uma apresentação interativa, pensada também para a parede de ecrãs do FeedNPlay.

## Estado (17/11/2026)

Todos os horários usados são **oficiais**: o SMTUC publicado pelo Município de Coimbra e o Metro Mondego publicado pela AGIT no dados.gov.pt. Os feeds do Metro que tinham sido construídos à mão a partir dos PDFs foram arquivados em `data/_arquivo/sintetico/`.

A análise corre em três cenários, definidos em `src/config.py` (`SCENARIOS`):

| Cenário | SMTUC | Metro Mondego | Dia de referência |
|---|---|---|---|
| `antes` (por omissão; degrau A) | Ep212 (em vigor desde 09/03/2026) | fase 1: GTFS oficial de 19/12/2025 | segunda, 11/05/2026 |
| `fase2_ep212` (contrafactual; degrau B) | Ep212 | fase 2: NeTEx da AGIT de 11/11/2026 | segunda, 09/11/2026 |
| `fase2` (degrau C, o Como Vou) | Ep225 (GTFS válido desde 18/09/2026; as alterações às linhas entraram a 10/09) | fase 2: NeTEx da AGIT de 11/11/2026 | segunda, 09/11/2026 |

O `fase2_ep212` nunca existiu: o metro da fase 2 e o Como Vou entraram no mesmo dia. Serve para separar os dois efeitos. `antes` → `fase2_ep212` mede só o metro e `fase2_ep212` → `fase2` mede só o horário SMTUC.

Já feito:
- **População e subserviço**: a BGRI 2021 (INE) cruzada com a oferta a ≤ 500 m de cada subsecção: heatmap, índice de subserviço, zonas sem oferta, polos de emprego e locais concorridos.
- **Overlap SMTUC × Metrobus**, linha a linha:
  - espacial: troços e paragens SMTUC a ≤ 240 m (3 min a pé) de uma estação;
  - temporal: passagens de autocarro nessas paragens com um metro a ≤ 5 min.

  Mapa de linhas e isócronas em todos os cenários.
- **Isócronas** a partir do estádio (a pé e em transporte público, até 2 transbordos), com a população em cada faixa de tempo.
- **Integração da linha 54 com o Metrobus** em Portela e em Portagem (onde conta também a 38). As esperas nos dois sentidos já incluem o transbordo a pé entre paragens e são calculadas para três horários:
  - **atual**;
  - **otimizado**: as mesmas viagens, deslocadas −10 min;
  - **melhorado**: um 2.º autocarro, que passa a linha de 40 em 40 para 20 em 20 min.
- **Dashboards**: master (`outputs/dashboard.html`), apresentação (`outputs/mockups_dashboard.html`) e parede FeedNPlay de 9 ecrãs (`outputs/feednplay_dashboard.html`). A apresentação está organizada por secções (ver "O que falta fechar"); cada slide diz que cenário mostra. Na secção 2 já tem o efeito do metro, o efeito do Como Vou, as diferenças de rede linha a linha e, no slide da 54, um botão para trocar entre o Como Vou e o horário de março com o mesmo metro.
- **Comparações de cenários** (`outputs/comparacao/<antes>_vs_<depois>.html` e `.csv`, pares em `COMPARISON_PAIRS`): overlap, acessibilidade a partir do estádio, população sem oferta e esperas da 54 lado a lado. Os pares mudam uma coisa de cada vez (só o metro, só o horário SMTUC); `antes_vs_fase2` junta as duas e fica só no master. Os números são os do `snapshot_metrics.py`, recalculados em cada regenerate.
- **Diferenças de rede SMTUC** (`outputs/comparacao/rede_fase2_ep212_vs_fase2.html` e `.csv`): cada linha como cortada, nova, renumerada, com percurso alterado, com ajuste de paragens, só com horário diferente, ou igual. Para cada uma, viagens no dia, paragens e extensão a par do metro. As linhas com avisos SMTUC (`data/smtuc_alteracoes_2026.csv`) ficam assinaladas, incluindo as alterações anteriores ao Como Vou.
- **Redundância e desperdício** (`outputs/redundancia/`): viagem a viagem, no dia útil de referência, os autocarros·km e as horas que o SMTUC faz a par do metro, por linha e por troço do metro, com o CO₂ e um ano estimado pela semana-tipo do horário (fatores da frota em `reports/estatisticas.txt`, sem euros). Há um ranking por cenário e uma página com o que o Como Vou fez às linhas mais redundantes. As comparações de cenários levam também estes números.
- **Rede da fase 1 sem a 54** (cenário A′, `antes_sem54`): o mesmo horário de março com a linha 54 retirada em memória, para medir o que a 54 acrescenta. As comparações incluem isócronas a partir das estações de Portagem e da Portela, em média das partidas da ponta da manhã.
- **Dados verificáveis**: os ficheiros oficiais ficam congelados em `data/raw/`. Os feeds que o código lê são construídos a partir deles com transformações registadas. Antes e depois de cada troca de dados tira-se um snapshot dos números de controlo (`reports/metricas/`).

## Principais números

Valores de `reports/metricas/oficial_fase1_t3.csv` (antes), `oficial_fase2_ep212.csv` (metro novo, SMTUC de março) e `oficial_fase2_t3.csv` (fase 2); as duas últimas linhas vêm de `n2_redundancia_<cenário>.csv`. Da 1.ª para a 2.ª coluna só muda o metro; da 2.ª para a 3.ª só muda o horário SMTUC.

| | Antes (11/05/2026) | Metro da fase 2 + SMTUC Ep212 (09/11/2026) | Fase 2, Como Vou (09/11/2026) |
|---|---|---|---|
| Linhas SMTUC com troços a ≤ 240 m do metro | 68 | 94 | 86 |
| Paragens SMTUC a ≤ 240 m de uma estação | 59 | 96 | 94 |
| Extensão de linhas SMTUC a par do metro (soma por linha) | 103,6 km | 398,2 km | 338,1 km |
| Passagens nessas paragens com um metro a ≤ 5 min (no dia de referência) | 93,6 % | 95,9 % | 95,6 % |
| Tempo médio a partir do estádio, às 08:20 (ponderado pela população) | 39,5 min | 35,3 min | 35,7 min |
| População a ≤ 10 min do estádio | 14 141 | 16 952 | 16 633 |
| População em subsecções sem oferta | 13 701 | 13 701 | 13 534 |
| Autocarros·km a par do metro num dia útil (viagem a viagem) | 815 | 2 443 | 1 970 |
| t CO₂ por ano a par do metro (estimativa) | 198 | 588 | 459 |

A extensão soma o troço de cada linha, por isso um corredor com várias linhas conta várias vezes. Os autocarros·km somam ainda cada viagem.

**Sem a 54** (A′ → A, `oficial_fase1_sem54.csv`): a população sem oferta e as isócronas do estádio não mudam, porque todas as zonas que a 54 serve têm outra linha. O que a 54 acrescenta vê-se a partir da estação da Portela (`n2_isocronas_nos_*.csv`): cerca de 1 min a menos no tempo médio e mais ~1 200 pessoas a ≤ 30 min.

**Linha 54 na fase 2**: espera mediana, em minutos.

| Sentido | Atual | Otimizado (−10 min) | Melhorado (2 autocarros) | Antes, atual |
|---|---|---|---|---|
| Portagem metro → autocarro | 19,0 | 18,5 | **9,1** | 19,0 |
| Portagem autocarro → metro | 4,5 | 4,0 | 4,5 | 4,0 |
| Portela metro → autocarro | 19,8 | 19,8 | 17,7 | 15,3 |
| Portela autocarro → metro | 6,3 | 6,3 | 6,8 | 7,7 |

A 54 passa de 40 em 40 min, por isso é ela que limita a espera de quem sai do metro. Deslocar o horário quase não muda nada. Só o 2.º autocarro (+1 autocarro e motorista) corta para metade a espera em Portagem. As páginas de integração da fase 2 estão em `outputs/integration/portagem_fase2/` e `portela_fase2/`.

Definições, histórico das trocas de dados e decisões sobre os desvios: [reports/metricas/README.md](reports/metricas/README.md).

## Dados

| Dados | Fonte | Licença |
|---|---|---|
| Metro Mondego, fase 1 (GTFS) e fase 2 (NeTEx) | AGIT / dados.gov.pt | CC BY 4.0 ("Dados: AGIT / dados.gov.pt") |
| SMTUC Ep212 | GTFS do SMTUC/Município | — |
| SMTUC Ep225 | GTFS publicado pelo Município de Coimbra | não especificada: **não é versionado** (só o sha256 e o `PROVENANCE.json`) |
| População | BGRI 2021, INE (Censos 2021) | — |
| Polos de emprego e locais concorridos | pesquisa manual (`src/population/points_of_interest.py`) | — |

Proveniência, validade e transformações de cada pasta: [data/README.md](data/README.md).

## Como correr

Python 3.12. O projeto usa o ambiente conda `smtuc312`.

```bash
conda create -n smtuc312 python=3.12
conda activate smtuc312
pip install -r requirements.txt
```

`requirements.txt` tem os intervalos de versões aceites; `requirements-lock.txt` tem as versões exatas do ambiente de desenvolvimento (Windows), as mesmas que a CI usa (`.github/workflows/testes.yml`, que corre a suite em cada push para `main`). Depois de atualizar um pacote, regenerar o lock a partir do ambiente e confirmar que os testes passam.

**SMTUC Ep225 (cenário `fase2`).** Os ficheiros não vêm no git. Numa máquina nova, descarregam-se e constroem-se assim:

```bash
python scripts/fetch_feeds.py      # descarrega os dados oficiais novos para data/raw/ (precisa de rede)
python scripts/build_feeds.py      # constrói data/gtfs/... e confirma as pastas que já existem
```

O catálogo do Município só serve a versão mais recente. Se o Ep225 já tiver sido substituído, deixa de se poder descarregar dali; o sha256 esperado está em `data/raw/MANIFEST.csv`.

**Regenerar todos os HTML e ver no browser.** Não precisa de `PYTHONPATH`: o script põe `src/` no caminho.

```bash
python scripts/regenerate.py

python -m http.server 8000
# http://localhost:8000/outputs/dashboard.html
# http://localhost:8000/outputs/mockups_dashboard.html
# http://localhost:8000/outputs/feednplay_dashboard.html
```

Antes de gerar, o regenerate confirma que o dia de referência de cada cenário cabe no período de todos os feeds. Se não couber, aborta sem gerar nada. No fim imprime um resumo e sai com código 1 se alguma secção falhar. A lista completa de páginas está no fundo de `src/config.py`.

**Testes.**

```bash
pytest
pytest -m "not integration"     # sem os testes que leem os GTFS e a BGRI do disco
```

Os testes só escrevem em pastas temporárias: a sessão falha se algum mexer em `outputs/`.

**Números de controlo e desvios da 54.** Correr antes e depois de cada troca de dados ou mudança de cálculo:

```bash
python scripts/snapshot_metrics.py snapshot <nome> --cenario fase2
python scripts/snapshot_metrics.py diff reports/metricas/A.csv reports/metricas/B.csv
python scripts/search_phase_shift.py --cenario fase2
```

**Valores locais.** Coordenadas pessoais e caminhos desta máquina vão em `src/config_local.py` e `scripts/local_settings.ps1`. Os dois são ignorados pelo git; os modelos são `src/config_local.example.py` e `scripts/local_settings.example.ps1`.

**Parede FeedNPlay.** O script abaixo sobe o Kafka, arranca um produtor de amostra da câmara e abre a janela da parede. Precisa do `feednplay_devkit` clonado ao lado do projeto e do Docker Desktop a correr.

```powershell
.\scripts\test_feednplay_local.ps1             # janela pequena
.\scripts\test_feednplay_local.ps1 -FullWall   # 9720x1920, o tamanho real da parede
```

## Organização

```
src/
  config.py              parâmetros: velocidade a pé, janelas de overlap, cenários, nós de integração, desvios da 54
  gtfs_processing/       leitura de GTFS, calendário e feriados, cenários, conversor NeTEx → GTFS
  overlap/               métricas por linha (com cache), overlap, isócronas, esperas metro ↔ autocarro
  population/            BGRI, subserviço, pontos de interesse
  visualizations/        mapas Folium, gráficos Plotly, dashboards; textos dos slides em presentation_content.py
  feednplay/             ponte para a parede (pywebview + câmara via Kafka)
  tests/                 testes pytest
scripts/                 regenerate, fetch_feeds, build_feeds, snapshot_metrics, search_phase_shift, FeedNPlay local
data/                    feeds GTFS, ficheiros oficiais congelados (raw/), BGRI, pontos de interesse
outputs/                 HTML e CSV gerados (versionados)
reports/
  metricas/              números de controlo antes e depois de cada troca de dados
  estatisticas.txt       composição da frota SMTUC (base para estimar o desperdício)
  *.tex, *.pdf, figures/ relatórios de maio de 2026, ainda com o metro sintético
docs/integracao_dados_agit/   plano, decisões e protótipos da integração dos dados oficiais
```

## O que falta fechar

**Análise**
- Propor 2 ou 3 versões otimizadas da rede que resolvam pelo menos os casos mais graves (N4, proposta E). O desperdício já está medido (N2).
- Incluir locais de trabalho e de convívio nas isócronas. Hoje só entram nos mapas de população.
- SIT, a rede interurbana, na fase 2: acessibilidade, cobertura, sobreposição SIT × SMTUC e transbordos SIT ↔ Metro em Portagem e Coimbra B. O plano está em `docs/integracao_dados_agit/README.md` (fase D3).

**Apresentação**
- Narrativa (o esqueleto já está nos slides, `src/visualizations/presentation_content.py`): 1 fase 1 (set 2025 – set 2026), 1.5 linha 54, 2 Como Vou (a reorganização das linhas SMTUC de setembro de 2026), 3 fase 3 (Linha do Hospital, março de 2027), 4 para onde levar os autocarros que a fase 3 torna redundantes. Cada secção compara dois degraus de uma escada de cenários que diferem numa só coisa: A (fase 1), A′ (A sem a 54), B (SMTUC Ep212 + Metro fase 2), C (Como Vou), D (fase 3, planeado), E (proposta, planeado). Os slides marcados "por construir" esperam por:
  - N1 (feito): cenário B, comparação por pares e diferenças Ep212 → Ep225 (secção 2). Fica para depois procurar o horário SMTUC em vigor a 09/09, para tirar de B → C a reestruturação de junho;
  - N2 (feito): ranking das redundâncias com o desperdício, a rede sem a 54 (A′) e as isócronas a partir dos nós (secções 1 e 1.5), e "as maiores redundâncias depois do Como Vou" (secção 2). Fica para depois um mapa dos troços do metro com mais autocarros a par;
  - N3 (feito): horário planeado da Linha do Hospital a partir do KMZ oficial (todas as viagens U2/U3/S2 prolongadas até ao Pediátrico, e a variante com metade), cenários D, isócronas a partir dos Hospitais, o que a Linha do Hospital torna redundante e a capacidade nos corredores das estações novas (secção 3, com o selo "cenário planeado");
  - N4: onde investir e a proposta E (secção 4).
- Fazer os mockups finais e melhorar o design. Juntar tudo no dashboard e limar arestas (legendas, etc.). Fechar as transições.
- A isócrona dinâmica no browser é uma aproximação: o tempo base mais a distância extra a 80 m/min. Rotulá-la como estimativa ou pré-calcular uma grelha de origens.

**FeedNPlay**
- Testar mais a interatividade e planear em que pontos da apresentação entram as componentes interativas. Pensar de forma mais estruturada a arquitetura do frontend para a parede.
- Servir o Plotly e o Leaflet localmente: hoje vêm de CDN, e sem internet a parede não mostra os mapas nem os gráficos.
- Tornar a ponte Kafka robusta a mensagens malformadas.
- Escapar o texto que o `master_dashboard.html` insere com `innerHTML`.

**Relatório**
- Escrever e finalizar o relatório com a narrativa centrada no impacto do Metrobus e na adaptação do SMTUC. Os relatórios em `reports/` são de maio de 2026 e usam números do metro sintético.

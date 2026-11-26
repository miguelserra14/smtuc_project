# Números de controlo: antes e depois de cada troca de dados

Gerados por `scripts/snapshot_metrics.py` e `scripts/search_phase_shift.py`. Os ficheiros não se substituem: cada troca de dados acrescenta um snapshot novo e o diff contra o anterior.

| Ficheiro | O que é |
|---|---|
| `sintetico.csv` | **Antes** (D0.2, 2026-11-16): SMTUC Ep212 + Metro **sintético** fase 1 |
| `sintetico_fase2.csv` | Metro sintético da fase 2 com o SMTUC Ep212 a 2026-05-11 (slide da fase 2 até à D2.7; sem esperas da 54) |
| `oficial_fase2.csv` | **Fase 2 oficial** (D2.7): SMTUC Ep225 + Metro NeTEx AGIT a 2026-11-09, cenário `fase2`, com as esperas da 54 |
| `diff_sintetico_fase2_vs_oficial_fase2.csv` | Diferenças do slide da fase 2 ao trocar o sintético pelo oficial |
| `oficial_fase1.csv` | **Depois** (D1 passo 4, 2026-11-16): SMTUC Ep212 + **GTFS oficial** do Metro (fase 1), ainda com os desvios da 54 do sintético (−11 / −10) e o critério de busca antigo |
| `diff_sintetico_vs_oficial_fase1.csv` | Todas as diferenças entre os dois (305 números) |
| `oficial_fase1_desvios.csv` | O mesmo com os desvios **decididos** (−10 / 0) e o critério novo |
| `oficial_fase1_d24.csv` | D2.4 (mesmos dados): a 38 conta em Portagem com origem própria (Santa Clara) e as paragens do nó incluem as que ficam a ≤ 250 m. Linha de base até ao T3 |
| `oficial_fase1_t3.csv` | T3 (2026-11-24, mesmos dados): overlap temporal só com o serviço do dia de referência. É a linha de base atual (`test_snapshot_metrics.py`) |
| `oficial_fase2_t3.csv` | O mesmo para o cenário `fase2` |
| `oficial_fase2_norte.csv` | Cenário `fase2` (2026-11-24, mesmos dados): + o sentido informativo Portagem autocarro→metro para norte. Linha de base atual da fase 2 |
| `diff_oficial_fase2_t3_vs_norte.csv` | Diferenças (12 números novos, só esse sentido; a busca de fase não muda) |
| `oficial_fase2_ep212.csv` | **Cenário `fase2_ep212`** (N1, 2026-11-26): contrafactual, Metro fase 2 com o SMTUC Ep212 a 2026-11-09 (as mesmas 2373 viagens do Ep212 a 11/05). Separa as mudanças de setembro: `antes` → `fase2_ep212` é só o metro, `fase2_ep212` → `fase2` é só o horário SMTUC (Como Vou + o que mudou de março a setembro). Os registos `oficial_fase1_t3` e `oficial_fase2_norte` não mudaram |
| `n2_redundancia_antes.csv`, `n2_redundancia_fase2_ep212.csv`, `n2_redundancia_fase2.csv` | **Redundância viagem a viagem** (N2.1, 2026-11-26; só a secção opcional `redundancia`, `--secoes redundancia`): autocarros·km e autocarros·hora a par do metro no dia de referência de cada cenário, no total, por linha e por corredor do metro. Mesma regra da extensão a par do metro; nenhum número dos outros registos mudou. Regravados com `--force` no N2.2 só com 24 números novos cada (desperdício e semana-tipo; os outros iguais) |
| `oficial_fase1_sem54.csv`, `n2_redundancia_antes_sem54.csv` | **Cenário `antes_sem54`** (A′, N2.3, 2026-11-26): a rede da fase 1 sem a linha 54 (Ep212 filtrado em memória, vista `smtuc-sem-54`; mesmos metro e dia). Sem esperas nem busca da 54 (secções omitidas) |
| `diff_oficial_fase1_d24_vs_t3.csv`, `diff_oficial_fase2_vs_t3.csv` | Diferenças do T3 (só colunas `temporal_*`) |
| `diff_oficial_fase1_desvios_vs_d24.csv` | Diferenças da D2.4 (19 números: só esperas em Portagem e a busca de fase) |
| `busca_fase_54_oficial_fase1_com_38.csv` | Busca de desvio no cenário `antes` com a 38: daria 0 / −10 |
| `busca_fase_54_fase2_oficial.csv` | Busca de desvio na rede da **fase 2 oficial** (cenário `fase2_oficial`): −10 / 0, os valores adotados |
| `diff_oficial_fase1_vs_desvios.csv` | Diferenças da decisão dos desvios (26 números: só as propostas e a busca) |
| `busca_fase_54_sintetico.csv` | Busca de desvio da 54 no sintético, com transbordo a pé (passo 0.2: −11 / −9) |
| `busca_fase_54_sintetico_sem_transbordo.csv` | Idem com a regra antiga (transbordo 0): reproduz os −16 / −8 originais |
| `busca_fase_54_oficial_fase1.csv` | Busca de desvio da 54 com o Metro oficial, critério antigo (−20..+20 nas duas propostas) |
| `busca_fase_54_oficial_fase1_alargada_40.csv` | Idem de −40 a +40: mostra os ótimos espúrios fora de meio ciclo (−28 / +28) |
| `busca_fase_54_oficial_fase1_meio_ciclo.csv` | Busca com o critério **atual** (meio ciclo; sem regressões e menor espera total): −10 / 0 |

Para reproduzir: `python scripts/snapshot_metrics.py diff reports/metricas/sintetico.csv reports/metricas/oficial_fase1.csv`.

## Metro sintético → GTFS oficial (fase 1)

Só mudou o metro. SMTUC, BGRI, dia de referência (2026-05-11, 08:20) e parâmetros são iguais.

Verificação independente no ficheiro bruto oficial: 291 viagens por dia útil; 62 chegadas a Portagem vindas de Portela e 57 a Portela vindas de Portagem, iguais aos PDFs; 142 partidas de Portagem sentido Vale das Flores, com intervalo mediano de 7 min.

**Esperas da 54 no horário atual** (mediana em min; cobertura = % com espera ≤ 10 min):

| Sentido | Sintético | Oficial |
|---|---|---|
| Portagem metro→autocarro | 27 (24 %) | 26,0 (21 %) |
| Portagem autocarro→metro | 12 (43 %) | **2 (90 %)** |
| Portela metro→autocarro | 16 (23 %) | 15,3 (21 %) |
| Portela autocarro→metro | 14 (43 %) | **7,7 (67 %)** |

- **Autocarro→metro melhora muito** porque o sintético não tinha os vaivéns urbanos Portagem ↔ Vale das Flores (172 por dia útil no oficial, contando os dois sentidos).
- **Metro→autocarro quase não muda**: é a 54 (de 40 em 40 min) que limita a espera.
- **Transbordos a pé**: Portagem 1,40 min (32 m; antes 1,28) e Portela 2,42 min (113 m; antes 2,39).

**Overlap**:
- Temporal: 58,9 % → **92,3 %** dos candidatos espaciais (8255 → 14 115 ocorrências), por haver muito mais metros.
- Espacial: paragens em overlap 52 → 59; extensão de linhas SMTUC em overlap 85,4 → 103,6 km. As coordenadas são as oficiais, e há uma paragem nova (Alto de São João).
- Linhas com overlap: 68 → 68.

**Isócronas e população**: tempo médio ponderado 39,4 → 39,5 min; população a ≤ 10 min do estádio 14 441 → 14 141; população sem oferta 13 705 → 13 701. Variações abaixo de 3 %.

**Busca de desvio da 54** (ranking: mais sentidos melhorados, depois menos regressões, depois menor soma de medianas):

| Proposta | Sintético | Oficial |
|---|---|---|
| Otimizado (mesmas viagens) | −11: 3 melhorados / 1 regressão | −11: **2 / 2** (soma 50,2); −10: 1 / 0 (soma 50,2) |
| Melhorado (2.º autocarro, 20 min) | −9: 3 / 1; −10: 2 / 0 | −18: **3 / 1** (soma 39,4); −20: 2 / 0 (soma 34,7) |

## Decisão dos desvios (2026-11-16)

O critério de busca mudou:

- **Antes:** mais sentidos melhorados primeiro, com −20..+20 nas duas propostas.
- **Agora:** a busca fica em meio ciclo de cada proposta (±20 no otimizado, ±10 no melhorado). Escolhe-se o desvio que **não piora nenhum sentido**, com a menor espera total, e em empate o mais pequeno.

Com o critério antigo, os desvios grandes ganhavam por efeito de borda (a 1.ª ou a última viagem do dia a entrar ou sair) e aceitavam piorar um sentido para melhorar outro.

| Proposta | Desvio | Efeito (mediana, min) | Soma |
|---|---|---|---|
| Otimizado (mesmas viagens) | **−10** (era −11) | Portagem metro→autocarro 26,0 → 25,2; os outros 3 sentidos iguais | 50,2 |
| Melhorado (2.º autocarro, 20 min) | **0** (era −10) | Portagem metro→autocarro 26,0 → 15,0; os outros 3 sentidos iguais | 40,0 |

Com a regra antiga do transbordo (0 min), os desvios seriam −13 / −3.

## D2.4 e D2.6: linha 38 e desvios na rede da fase 2 (2026-11-16)

Decisões do utilizador:
- A 38 fica no nó de Portagem com **origem própria**. Antes partilhava a origem da 54 ("Portela do Mondego"), onde nunca passa, e contribuía 0 passagens. Agora conta no sentido Santa Clara → Polo II, que chega a Portagem vindo da margem esquerda, como a 54 vinda de Portela: 14 passagens por dia útil, com 3,23 min de transbordo a pé.
- Em Portagem, autocarro→metro continua a contar **só o sentido Vale das Flores/Serpins** (o da fase 1), mesmo na fase 2.
- **Um só par de desvios** para todos os cenários: −10 / 0, o ótimo da rede da fase 2.

Efeito no `antes` (`diff_oficial_fase1_desvios_vs_d24.csv`):
- Portagem metro→autocarro passa de 26,0 para 19,0 min de mediana, porque a 38 junta passagens à 54.
- Portagem autocarro→metro passa de 2 para 4 min, porque as chegadas da 38 são na paragem do Parque Manuel Braga, mais longe.
- Portela não muda.

Uma linha com viagens no dia que nunca passa no nó depois da sua origem passa a ser um **erro**. Antes contribuía 0 passagens sem aviso.

Busca na fase 2 oficial (`busca_fase_54_fase2_oficial.csv`):
- **Otimizado −10:** melhora 3 dos 4 sentidos sem piorar nenhum (soma das medianas 49,5 → 48,6).
- **Melhorado 0:** nenhum desvio evita piorar um sentido; o 0 é o de menor espera total (38,0).
- **No `antes`:** a busca daria 0 / −10. O −10 do otimizado só perde lá 0,1 min num sentido.

## Metro sintético → oficial na fase 2 (D2.7, 2026-11-16)

Mudam o metro (NeTEx oficial), o SMTUC (Ep225) e o dia (2026-11-09). Os números do slide da fase 2 passam a ser oficiais:
- **Overlap temporal:** 82,6 % → 97,8 % dos candidatos espaciais.
- **Overlap espacial:** estações em overlap 88 → 94 e linhas SMTUC com overlap 94 → 86. A extensão em overlap fica igual (338 km). O salto face aos 104 km da fase 1 vem da rede da fase 2 (Baixa, Coimbra B) e já existia no sintético.
- **Isócronas e população:** o tempo médio ponderado a partir do estádio passa de 37,9 para 35,7 min; as partidas por dia sobem 1,5 %.
- **Esperas da 54** (novas no slide): Portagem metro→autocarro 19,0 min e autocarro→metro 4,5 min; Portela 19,8 e 6,3 min (mediana).

## Overlap temporal só no dia de referência (T3, 2026-11-24)

Mesmos dados e parâmetros; muda só a regra do overlap temporal, aprovada pelo utilizador. Antes comparavam-se padrões semanais: as passagens de dias úteis, sábados e domingos somavam-se, e um serviço sem calendário contava como "partilhado". Agora contam só as viagens SMTUC e do metro que circulam no dia de referência (feriados como domingo), como nas outras métricas. Mudam só as colunas `temporal_*`; frequências, esperas, isócronas e população ficam iguais.

| | Antes: semana | Antes: dia | Fase 2: semana | Fase 2: dia |
|---|---|---|---|---|
| Passagens SMTUC junto ao metro | 15 292 | 4 971 | 35 553 | 10 294 |
| …com um metro a ≤ 5 min | 14 115 | 4 651 | 34 785 | 9 840 |
| % | 92,3 % | 93,6 % | 97,8 % | 95,6 % |
| Linhas com overlap temporal | 82 | 74 | 88 | 82 |

- As contagens descem cerca de 70 % por passarem de uma semana somada a um dia útil; a percentagem quase não muda.
- Deixam de ter overlap as linhas que não circulam no dia de referência: no `antes` 5F, 10F, 18F, 22F, 23F, 28F, 47F e 50M; na fase 2 18F, 22F, 23F, 28F, 36F e 47F.

## Portagem autocarro→metro para norte, informativo (2026-11-24)

Mesmos dados. Na fase 2 o metro continua de Portagem para Coimbra B (U1, S1) e para a República (U2, S2). O sentido norte é provavelmente o transbordo mais usado: a 54 termina em Parque 2 e a 38 segue ela própria para Polo II. Entra como **métrica informativa**, só no cenário `fase2` (decisão do utilizador):
- **Conta a primeira partida em qualquer dos ramos:** 153 partidas por dia, tantas como para sul (150).
- **Fica fora da busca do desvio de fase.** O par −10 / 0 continua a otimizar só os 4 sentidos. Com o norte no objetivo o ótimo mudava, mas só por ~0,1 min.
- **No `antes` não existe**, porque o metro acaba em Portagem. O snapshot do `antes` não muda.

| Portagem autocarro→metro (54+38, mediana) | atual | otimizado (−10) | melhorado (0) |
|---|---|---|---|
| Sul (sentido contado) | 4,5 min | 4,0 min | 4,5 min |
| Norte, qualquer ramo | 5,7 min | 5,8 min | 5,8 min |

Por ramo (análise de 2026-11-24, horário atual): só Coimbra B 9,8 min; só República 6,8 min (média 11,3 e p90 21, por causa de buracos de até 41 min).

Na mesma altura, uma origem ou um sentido que não existe no feed passa a ser um **erro**. Antes, a lista vazia de paragens desligava o filtro de sentido e contava os dois sentidos: o metro "vindo de Coimbra B" no feed da fase 1 dava as 257 passagens. Nenhum número publicado dependia disso.

## Metro novo com a rede antiga: cenário `fase2_ep212` (N1, 2026-11-26)

Contrafactual para separar as duas mudanças de setembro de 2026: o metro da fase 2 e a reorganização SMTUC do Como Vou. As duas entraram no **mesmo dia, 10/09/2026** (avisos SMTUC de 09/09; o GTFS Ep225 do Município só é válido a partir de 18/09), por isso a rede real nunca as separou: esta rede nunca existiu. O cenário junta o Metro da fase 2 ao SMTUC Ep212 no dia da fase 2. O `calendar.txt` do Ep212 vai até 31/12/2026, por isso não houve transformação de dados: são as mesmas 2373 viagens de 11/05.

| | `antes` (A) | `fase2_ep212` (B) | `fase2` (C) |
|---|---|---|---|
| Linhas SMTUC com troços a ≤ 240 m do metro | 68 | 94 | 86 |
| Paragens SMTUC a ≤ 240 m de uma estação | 59 | 96 | 94 |
| Extensão de linhas SMTUC a par do metro | 103,6 km | 398,2 km | 338,1 km |
| Passagens com um metro a ≤ 5 min | 93,6 % | 95,9 % | 95,6 % |
| Tempo médio a partir do estádio (ponderado) | 39,5 min | 35,3 min | 35,7 min |
| População a ≤ 10 min do estádio | 14 141 | 16 952 | 16 633 |
| População em subsecções sem oferta | 13 701 | 13 701 | 13 534 |
| Portagem metro→autocarro (54+38, mediana, atual) | 19,0 min | 18,5 min | 19,0 min |
| Portela metro→autocarro (54, mediana, atual) | 15,3 min | 19,8 min | 19,8 min |

- **O aumento do overlap vem do metro.** De A para B a extensão a par do metro passa de 104 para 398 km. De B para C o horário SMTUC **reduz-a** em 60 km e tira 8 linhas do overlap.
- **A espera na Portela piora por causa do metro.** O horário da 54 é o mesmo em A e B, e B já tem a espera de C.
- **B → C não é só o Como Vou.** O Ep212 é de 09/03/2026. Dos avisos SMTUC de março a setembro, a única alteração permanente antes do Como Vou é a reestruturação de 14/06 das linhas 5, 5T, 5F, 33 e 33R (as outras são obras, eventos ou horários sazonais); fica assinalada linha a linha nas diferenças de rede (`data/smtuc_alteracoes_2026.csv`). Procurar o horário em vigor a 09/09 fica para depois.
- **A busca do desvio de fase em B daria −10 / +1.** Fica só como registo: o par adotado continua a ser −10 / 0, o ótimo da fase 2.

## Redundância viagem a viagem (N2.1, 2026-11-26)

Registos `n2_redundancia_<cenário>.csv` (`--secoes redundancia`, código em `src/overlap/redundancy.py`). A regra de "a par do metro" é a mesma da extensão a par do metro: um troço entre duas paragens consecutivas ambas a ≤ 240 m de uma estação. Muda a unidade: em vez do percurso representativo de cada sentido, somam-se todas as viagens do dia de referência, cada uma com as suas paragens. Ficam as mesmas linhas das métricas por linha (número < 100), por isso as viagens são menos do que as 2373 do Ep212 com todas as linhas.

| Dia útil de referência | A (fase 1) | B (metro fase 2 + Ep212) | C (Como Vou) |
|---|---|---|---|
| Viagens SMTUC | 2110 | 2110 | 1970 |
| Autocarros·km | 16 472 | 16 472 | 16 055 |
| Autocarros·km a par do metro | 815 (4,9 %) | 2443 (14,8 %) | 1970 (12,3 %) |
| Autocarros·hora a par do metro | 70 | 194 | 150 |

- Conferido com as métricas por linha: por linha, autocarros·km a par do metro ÷ (viagens × extensão a par do metro por sentido) tem mediana 1,00 em A e em C. Os desvios vêm das viagens curtas e das variantes.
- O corredor do metro de cada troço são as estações mais próximas das duas pontas; as plataformas "(asc)"/"(desc)" contam como uma estação. Em A o mais carregado é Parque–Portagem; em B e C são Mercado–República e Açude–Casa do Sal.

## Desperdício: CO2 e ano estimado (N2.2, 2026-11-26)

Os fatores estão em `src/config.py` (`WASTE_*`), com as fontes de `reports/estatisticas.txt`: frota de 118 autocarros com 46 elétricos, repartida por igual por todas as linhas; 0,45 L/km e 2,68 kg CO2/L no gasóleo; 0,65 kWh/km e 0,097 kg CO2/kWh na eletricidade. Dá 0,76 kg CO2 por autocarro·km. Não há euros (decisão do utilizador).

O ano é uma **estimativa**: semana-tipo × 52. A semana-tipo é o dia útil de referência × 5 mais o sábado e o domingo mais próximos dele dentro do período do feed e fora de feriados. Cada dia usa o seu serviço GTFS. Não se descontam feriados nem agosto. O Ep225 só cobre até 12/11/2026, por isso não se podia usar a semana de 09/11 inteira; em todos os cenários o fim de semana é o anterior ao dia de referência.

| A par do metro | A (fase 1) | B (metro fase 2 + Ep212) | C (Como Vou) |
|---|---|---|---|
| Dia útil: autocarros·km / t CO2 | 815 / 0,6 | 2443 / 1,9 | 1970 / 1,5 |
| Sábado / domingo: autocarros·km | 566 / 370 | 1688 / 970 | 1123 / 644 |
| Ano estimado: autocarros·km | 260 600 | 773 400 | 604 100 |
| Ano estimado: autocarros·hora | 21 800 | 59 800 | 45 300 |
| Ano estimado: t CO2 | 198 | 588 | 459 |

- Substitui as contas à mão de `reports/estatisticas.txt` (503 574 km/ano e ~383 t CO2/ano na fase 1). Essas partiam de 85,4 km de extensão, viagens = 19 h ÷ intervalo médio e 365 dias iguais. Calculado viagem a viagem, a fase 1 dá cerca de metade.
- Linhas com mais CO2 por ano: A 7T, 24T, 33; B 7T, 29, 24T; C 5, 24T, 29.

## Rede da fase 1 sem a 54 (A′, N2.3, 2026-11-26)

O cenário `antes_sem54` é o `antes` com a linha 54 tirada do Ep212 em memória: não há ficheiros novos, e a cache de métricas tem assinatura própria. Comparado com `oficial_fase1_t3` (A), só mudam números ligados à 54:

- **Linhas:** desaparece a linha 54. Todas as outras linhas têm exatamente os mesmos números.
- **Overlap:** menos 1 linha e menos 1,7 km de extensão a par do metro (de 103,6 para 101,9 km).
- **População:** a população sem oferta e as isócronas do estádio não mudam (13 701 pessoas; 39,5 min). Só as partidas na área de influência das paragens descem 0,7 %: todas as subsecções servidas pela 54 têm outra linha.
- **Redundância:** a 54 faz 34,5 autocarros·km por dia útil a par do metro (4,2 % dos 815 de A).
- **Esperas da 54:** omitidas em A′, porque não há 54.

O contributo da 54 não aparece na cobertura nem no estádio. Fica para as isócronas a partir da Portela e da Portagem (N2.4) e para as esperas da integração.

# Integração dos dados oficiais AGIT (SMTUC, Metro Mondego, SIT)

Plano preparado a 2026-11-13, antes de começar. **Nada do código nem dos dados do projeto foi alterado** durante o planeamento; esta pasta é o único ficheiro novo, juntamente com os scripts em `prototipos/`.

Objetivo: substituir os feeds sintéticos do Metro (`data/metrobus`, `data/metrobus_fase2`) por dados oficiais e juntar o SIT (rede interurbana), sem fazer tudo de uma vez.

---

## 1. Ponto de partida

- **Os feeds do Metro em uso são sintéticos.** Foram construídos à mão no repositório e nunca vieram da Metro Mondego. Comparados com os horários oficiais:
  - falta todo o serviço urbano Vale das Flores ↔ Portagem;
  - nos dias úteis faltam 21 chegadas a Portagem, sobretudo à tarde, e há 9 viagens duplicadas;
  - o `calendar.txt` é uma cópia do calendário do SMTUC;
  - quatro paragens da Lousã têm coordenadas erradas (segmentos a ~320 km/h);
  - a topologia da fase 2 foi inventada e não corresponde à real.
- **A AGIT publica agora dados oficiais** no dados.gov.pt (CC BY 4.0, creditar "Dados: AGIT / dados.gov.pt"). A lista e as estruturas estão na secção 4.
- **A Fase 0 do roadmap da auditoria está feita**: frequência, transbordos, calendário, regenerate e isócronas determinísticas. Falta só a 0.5, que passa para dentro da D1.5.

## 2. Decisões tomadas

| Tema | Decisão |
|---|---|
| Cenários | **Antes** = SMTUC Ep212 (`data/smtuc` atual) + GTFS oficial do Metro exportado a 2025-12-19. **Fase 2** = SMTUC NeTEx Ep225 + Metro NeTEx + SIT. |
| Pressuposto do "antes" | O horário do Metro de Dez 2025 ainda vigorava em maio de 2026. **Confirmado** (secção 5). |
| Dia de referência | Um por dataset/cenário. "Antes": SMTUC 2026-05-11, Metro 2025-12-15. "Fase 2": 2026-11-09, ou um snapshot mais recente. |
| NeTEx | **Esperar pela API AGIT** para ver se o endpoint `distributions` também dá GTFS. Só se não der, escrever o conversor NeTEx→GTFS. |
| Dados brutos no git | Só os zips originais, com `metadata.jsonld` e sha256. Nunca o XML do SMTUC (141 MB, acima do limite de 100 MB do GitHub). |
| SIT, quando | Só no cenário fase 2. A intermodalidade (bilhete comum) começou a **2026-10-01**, por isso o dia de referência da fase 2 tem de ser a partir dessa data. |
| SIT, como | Respeitar as regras de embarque e desembarque (portas fechadas a viagens urbanas). Recortar as viagens ao concelho de Coimbra. BGRI só de Coimbra. |
| Análises com SIT | As quatro: acessibilidade/isócronas, cobertura populacional, sobreposição SIT×SMTUC, transbordos SIT↔Metro em Portagem e Coimbra B. |
| Para mais tarde | Cenário what-if com o SIT de portas abertas a viagens urbanas dentro de Coimbra, para comparar com o real. |

## 3. Roadmap (Fase D)

Regras para todas as fases:
- Nunca trocar dados e código de cálculo no mesmo passo.
- Cada fase termina com o regenerate a correr sem erros, a apresentação a funcionar, os números comparados com a fase anterior, commit, e README/CLAUDE.md atualizados.
- Um branch por fase.

### D0 Preparação (~4 h, não muda números)
1. ~~Commitar a 0.2~~ (feito, `4e6661d`).
2. ~~Snapshot~~ (feito a 2026-11-16: `reports/metricas/sintetico.csv` e `sintetico_fase2.csv`; ver CLAUDE.md). `scripts/snapshot_metrics.py`: exporta os números de controlo (overlap por linha, overlap temporal, esperas por sentido na 54, população por faixa de isócrona, zonas mal servidas) para `reports/metricas/<fase>.csv`. Corre-se sobre o sintético para ter a **linha de base**. Há testes com valores fixos (`test_calendar.py`, `test_frequency.py`, `test_transfer.py`) que falham quando os dados mudam: guardá-los por impressão digital dos feeds, como já faz `test_phase_search.py`.
3. `scripts/fetch_agit.py`: tenta a API e, se falhar, os espelhos do dados.gov.pt. Guarda em `data/raw/agit/<dataset>/<data>/` e não repete o download se o sha256 for igual. Descarregar tudo: NeTEx SMTUC/Metro/SIT, GTFS Metro 2025, GeoPackage SIT e KMZ. **Nunca corre dentro do regenerate**, para a apresentação continuar a funcionar offline.
4. Ver se `/v1/datasets/{smtuc,metro-mondego,sit}/distributions` oferece GTFS. Só bloqueia a D2.
5. `data/README.md` com a proveniência de cada feed.

### D1 Corrigir o sintético: Metro fase 1 oficial (~8–12 h, não precisa da API)
1. Extrair o GTFS de 2025-12-19 para `data/metro_2025/`. Usar `gtfs.py integrate` **com `--target` explícito**: por omissão despeja os ficheiros na raiz de `data/`. As paragens técnicas PC1–PC8 vêm como paragens normais; filtrar pelo nome (`^PC\d`).
2. ~~Validar contra os PDFs~~ (feito, secção 5).
3. Validador de feed como teste (item 3.3): integridade, horas por ordem, velocidades, calendário que cobre o dia de referência.
4. Alterações de código:
   - ler os IDs como texto (item 3.2);
   - dia de referência por dataset;
   - nome do dataset do Metro numa constante de config;
   - `metro_route_id` da rota 3606.
   
   O `regenerate` (`_REFERENCE_DAY_DATASETS`, `_validate_reference_day`) e o `INTEGRATION_SITES` assumem um só dia e os nomes `smtuc`/`metrobus`. **Se não mudarem, o regenerate aborta**, porque o `metro_2025` só cobre 2025-11-01 a 2025-12-31.
5. Regenerar, correr `snapshot_metrics` e comparar com o sintético. Refazer a busca de fase da 54 (`scripts/search_phase_shift.py`) e decidir os desvios (hoje −11/−10, provisórios). Rever os números dos slides (= 0.5).
6. Arquivar `data/metrobus` e `scripts/fix_metrobus_scrambled_trips.py` em `data/_arquivo/sintetico/`.

### D2 Fase 2 oficial e diferenças entre fase 1 e fase 2 (~16–24 h)
1. GTFS do SMTUC Ep225 e do Metro: da API se houver, senão do conversor (mapeamento na secção 4), com testes sobre um NeTEx mínimo. O snapshot Ep225 de 24/10 **acabou a 2026-11-12**: é preciso um novo.
2. Validar: janelas de calendário, feriados (o SMTUC codifica-os, o Metro não), serviços "Especial" que duplicam os dias úteis, `DayOffset`.
3. `SCENARIOS` no config, com datasets e dias por cenário. Tirar todos os `"smtuc"`/`"metrobus"` escritos à mão (`transit.py` 406-407, 542-543, 981-997; valores por omissão em population/overlap/lines_map). Caches e outputs por cenário, generalizando o sufixo `_fase2`.
4. Adaptar às mudanças de rede:
   - encontrar paragens pela distância, porque a 54 no sentido Portela sai de **Parque 2**;
   - `metro_route_id` passa a ser uma lista (5 linhas);
   - paragens da Baixa divididas por sentido (asc/desc);
   - linhas SMTUC novas e removidas;
   - linha 38 em Portagem: hoje é excluída sempre, por isso "54+38" é na prática só a 54. Decidir se se tira.
5. Vista ou slide comparativo antes vs fase 2: overlap, cobertura, isócronas, esperas em Portela e Portagem.
6. Busca de fase da 54 na rede atual: a proposta tem de visar a fase 2.
7. Trocar o slide sintético da fase 2. Textos: "em operação desde 10/09/2026", crédito CC BY. Arquivar `metrobus_fase2`, o gerador e os PDFs.

### D3 SIT, só na fase 2 (~14–20 h)
1. Medir o tempo das isócronas com o SIT. Se ficar lento, fazer primeiro o item 5.3 (RAPTOR em numpy).
2. SIT → GTFS (calendário escolar, regras de embarque), recortado ao concelho. Validar que o dia de referência é a partir de 2026-10-01 e cai em período escolar normal.
3. Acessibilidade e isócronas a respeitar `pickup_type`/`drop_off_type`, com teste numa rede sintética.
4. Cobertura BGRI com as paragens SIT: só onde se pode fazer uma viagem urbana, ou contadas à parte.
5. Sobreposição SIT×SMTUC.
6. Transbordos SIT↔Metro em Portagem e Coimbra B, reaproveitando `INTEGRATION_SITES` e `compute_transfer_waits`.
7. Mapas com os percursos do GeoPackage e slide de intermodalidade.

### D4 Depois, sem data
- What-if com o SIT de portas abertas (pedido explícito).
- Coletor SIRI-ET para medir a pontualidade real (só existe para o SMTUC).
- Linha do Hospital a partir do KMZ.
- Atualização periódica dos snapshots.

**Total estimado: ~42–60 h.** Itens do roadmap da auditoria absorvidos: 2.3, 3.2, 3.3, 4.4, 0.5. A Fase 1 (dia da apresentação: assets offline, bridge) não depende destas fases.

## 4. O que se sabe dos dados (verificado a 2026-11-13)

### Fontes (organização AGIT no dados.gov.pt)
| Conjunto | Ficheiro | Notas |
|---|---|---|
| METRO MONDEGO NETEX | `metro-mondego-netex.zip` (790 KB) | API: `https://api.planner.agit.pt/v1/datasets/metro-mondego/distributions/netex/download` |
| Transportes Urbanos de Coimbra NETEX | `smtuc-netex.zip` (9,7 MB; XML 141 MB) | API: `.../datasets/smtuc/distributions/netex/download` |
| Metro Mondego | `20251219-export-gtfs.zip` (86 KB), `rede-metrobus.kmz` | GTFS oficial pré-fase 2, válido 2025-11-01 a 2025-12-31, com shapes |
| SIT da Região de Coimbra NETEX | `sit-netex.zip` (6,9 MB) | API: `.../datasets/sit/distributions/netex/download` |
| Sistema Intermunicipal de Transportes | `gtfs-percursos-paragens.gpkg` (18 MB), shapefile, KMZ | percursos para os mapas |
| SMTUC SIRI, Ocorrências, Intervenções | zips de amostra + endpoints `.../realtime/...` | tempo real; fora do âmbito por agora |

A pesquisa na API do catálogo faz-se com `https://dados.gov.pt/api/1/datasets/?q=<termos>`. A `api.planner.agit.pt` respondia **502** a 2026-11-13; os espelhos `dados.gov.pt/s/resources/...` funcionavam.

### Estrutura do NeTEx da AGIT
- Perfil EPIP, um único `netex.xml` com um `PublicationDelivery`. Vem acompanhado de `metadata.jsonld`.
- **É um export a partir de GTFS**: cada elemento traz `keyList` com `gtfs:route_id`, `gtfs:stop_id`, `gtfs:trip_id` e `gtfs:service_id`.
- Viagens explícitas (`ServiceJourney` + `TimetabledPassingTime`). Horas depois da meia-noite com `DayOffset`.
- Calendários: `DayType` ↔ `UicOperatingPeriod.ValidDayBits` (um bit por dia a partir de `FromDate`).
- Não traz geometria dos percursos.
- Lê-se bem em streaming com `xml.etree.ElementTree.iterparse` + `el.clear()`: os 141 MB do SMTUC passam em 1–2 min.

Mapeamento para o conversor, se for preciso:

| GTFS | NeTEx |
|---|---|
| agency | `Operator` |
| routes | `Line` (`ShortName`, `Name`, `Presentation/Colour`) |
| stops | `ScheduledStopPoint` (`PublicCode` → `stop_code`) |
| trips | `ServiceJourney` → `ServiceJourneyPattern` → `Route` → `Line`; `DirectionType` outbound/inbound → 0/1; `DayType` → service_id |
| stop_times | `TimetabledPassingTime`; `DayOffset` → `24:xx`; `ForBoarding`/`ForAlighting` → `pickup_type`/`drop_off_type` |
| calendar | `ValidDayBits` → **padrão semanal + exceções**, e não uma data por linha em `calendar_dates` |

O último ponto é obrigatório. O `FERIADOS_COMO_DOMINGO` só atua em datas sem exceção no feed. Se cada data virasse exceção, os feriados do Metro, que o feed não codifica, ficavam com serviço de dia útil.

### Metro NeTEx (fase 2 em operação)
- 5 linhas, 40 paragens, 979 viagens. Válido de 2026-06-13 a 2026-12-31, mas **os dias úteis só começam a 2026-09-10** (sábados desde 06-13, domingos desde 09-13).
  - **U1 Azul:** Coimbra B ↔ Vale das Flores
  - **U2 Vermelho:** República ↔ Vale das Flores
  - **U3 Verde:** República ↔ Coimbra B
  - **S1:** Serpins/Lousã/Corvo ↔ Coimbra B
  - **S2:** Serpins/Lousã/Corvo ↔ República
- Cerca de 10 min no troço urbano; cerca de 300 passagens por dia útil em Portagem.
- As paragens da Baixa estão divididas por sentido: República, Mercado e Câmara "(asc)"/"(desc)". Há uma paragem nova, Alto de São João.
- **Feriados não codificados**: 5/10, 1/12, 8/12 e 25/12 aparecem como dias úteis.

### Metro GTFS 2025-12-19 (pré-fase 2)
- 1 rota (3606, com o nome e o código trocados nos campos). Serviços: 1 = domingo, 2 = sábado, 3 = dias úteis.
- **291 passagens por dia útil em Portagem**, das quais 85+87 são vaivéns urbanos Vale das Flores↔Portagem. O sintético tem 107.
- Inclui as paragens técnicas PC1–PC8 como paragens normais e tem `shapes.txt`.

### SMTUC NeTEx Ep225
- 230 `Line` (variantes) para 104 códigos, 8222 viagens, 1529 paragens. Janela do snapshot de 24/10: 2026-09-18 a 2026-11-12.
- **O novo `stop_id` é igual ao `stop_code` antigo** (1510 de 1519 coincidem, mesmas coordenadas). O `stop_id` antigo com o mesmo número é outra paragem.
- O `route_id` passa a ser o código da linha, alfanumérico (`38A`, `100E`).
- Feriados e dias especiais vêm explícitos: 5/10 usa o serviço de domingo; há serviços especiais a 23/9, 7/10, 23/10 e 7/11.
- Linha 54: no sentido Portela parte de **Parque 2** (a 178 m do Metro Portagem). Só o regresso passa na paragem "Portagem".
- Já não existem as paragens "Portagem (Beira Rio)" e "(Parque Manuel Braga)".
- Linhas removidas: 10F, 12R, 30A, 30F, 33, 33R, 5F, 7T. Novas: 100E, 101, 251.

### SIT NeTEx
- 210 linhas, 1909 viagens, 6383 paragens. Calendário de 2025-08 a 2026-12, com **104 DayTypes** que codificam períodos escolares e variantes por concelho.
- IDs do tipo `agn_001`; nenhum código coincide com o do SMTUC. Há 458 paragens SIT a menos de 50 m de uma paragem SMTUC, por isso a ligação faz-se pela distância.
- Dentro da área urbana, **58% das passagens só deixam embarcar ou só deixam desembarcar**. Terminais: Arnado (~97 passagens por dia útil), Portagem (~71), Rodoviária, Estevão Cabral, Coimbra B.

## 5. Validações já feitas

- **Pressuposto do "antes" confirmado.**
  - O serviço suburbano do GTFS de Dez 2025 é **idêntico** ao PDF de 06/09/2026, em todos os dias e sentidos: 62/57/27/27/20/20 passagens em Portagem, minuto a minuto.
  - Em Portagem, urbano + suburbano dá intervalos medianos de 5/7/5/15 min, os mesmos do PDF urbano.
- **Feed sintético contra os PDFs**: o tronco transcrito bate nas viagens existentes, mas tem as falhas da secção 1.

## 6. O que ainda não se sabe (não dava para planear)

1. ~~**Se a API dá GTFS.**~~ Respondido a 2026-11-16: a API voltou, mas as `distributions` dos três conjuntos só têm NeTEx (e GTFS Realtime "pending"). **O conversor NeTEx→GTFS é necessário** (D2.1, 4–6 h). O catálogo do dados.gov.pt dá, por ficheiro, sha1, tamanho, `last_modified` e um URL de espelho com a versão no caminho (`/s/resources/<slug>/<AAAAMMDD-HHMMSS-hash>/<ficheiro>`); a API não dá checksum nem versão.
2. **A data da apresentação.** Decide até onde ir antes dela. Recomendação: levar a D1 pronta e deixar a D2 e a D3 para depois, se o prazo for curto.
3. **Snapshot novo do SMTUC**: o de 24/10 já expirou.
4. **Desvios da 54**: só se decidem com dados oficiais (D1.5 e D2.6).

## 7. Como começar

1. Ler o roadmap e confirmar que a Fase 0 está commitada.
2. D0.2: correr a linha de base **antes** de tocar em dados.
3. D0.3: descarregar e congelar os ficheiros AGIT.
4. Seguir para a D1, que não depende da API.

## 8. Protótipos (`prototipos/`)

São scripts de análise só de leitura, usados no planeamento. Correm com `python -I <script> <args>`. Os ficheiros descarregados devem ficar numa pasta própria (`<raw>`). `<repo>` é a raiz do projeto.

| Script | Para quê | Argumentos |
|---|---|---|
| `inspect_zips.py` | Lista o conteúdo dos zips/KMZ e resume os XML | `<pasta com zips>` |
| `netex_snippets.py` | Mostra o primeiro exemplar de cada elemento NeTEx e o `metadata.jsonld` | `<netex.zip> [max_chars]` |
| `netex_summary.py` | **Meio conversor**: linhas, calendários, padrões, viagens por serviço e passagens por paragem num dia | `<netex.zip> [AAAA-MM-DD] ["Paragem1\|Paragem2"]` |
| `netex_days.py` | Datas ativas de cada DayType (`ValidDayBits`) | `<netex.zip>` |
| `compare_ids_smtuc.py` | Cruza as paragens e linhas do NeTEx SMTUC com `data/smtuc` (pelo `stop_code`) | `<smtuc-netex.zip> <repo>` |
| `line54.py` | Sequências das linhas 54 e 38 no NeTEx SMTUC e distância ao Metro | `<smtuc-netex.zip>` |
| `sit_stops.py` | Paragens SIT perto do SMTUC e regras de embarque | `<sit-netex.zip> <repo>` |
| `old_mm_gtfs.py` | Padrões de viagem do GTFS Metro de 2025 | `<mm-gtfs.zip>` |
| `check_assumption.py` | Validação do pressuposto do "antes" contra os PDFs | `<mm-gtfs.zip> <suburbana.txt> <urbana.txt>` |
| `combined_headway.py` | Intervalos combinados em Portagem (GTFS 2025) | `<mm-gtfs.zip>` |
| `compare_sintetico_vs_pdf.py` | Feed sintético contra o PDF suburbano | `<repo> <suburbana.txt>` |
| `velocidades_sintetico.py` | Velocidades implícitas e tipos de dados do feed sintético | `<repo>` |

Os PDFs estão em `data/raw/manual/metro-mondego-horarios-pdf/2025-12-22/` (criados a 22/12/2025, descarregados a 06/09/2026). Os `.txt` geram-se com `pdftotext -layout MM_Horarios_Digital_Suburbana.pdf suburbana.txt` (há `pdftotext` no MiKTeX). Os números de linha usados em `check_assumption.py` e `compare_sintetico_vs_pdf.py` (82, 112, 246...) correspondem a essa extração e ficam errados se o PDF mudar.

## 9. Organização de `data/` (proposta de 2026-11-16, por aprovar)

```
data/
  README.md              proveniência de cada feed (D0.5)
  raw/                   IMUTÁVEL: os ficheiros exatamente como publicados
    MANIFEST.csv         1 linha por ficheiro, só se acrescenta
    agit/<slug>/<versão>/<ficheiro original>     versão = AAAAMMDD-HHMMSS da publicação (do URL do espelho)
    manual/<fonte>/<versão>/                     PDFs do Metro, zip BGRI do INE, gtfs_cp.zip...
  gtfs/<dataset>/        o que o código lê: um GTFS por pasta, nome com versão, nunca reutilizado
                         (smtuc_ep212, metro_gtfs_20251219, smtuc_ep225_20261024...) + PROVENANCE.json
  bgri/, poi/            referência estática
  _arquivo/sintetico/    metrobus, metrobus_fase2 e os scripts que os geraram
```

Regras:
1. `raw/` nunca se edita nem se substitui. Uma publicação nova vai para uma pasta nova.
2. Download atómico: `.part`, depois sha256, sha1 e tamanho comparados com o catálogo, `testzip`, e só então o nome final. Se o catálogo já estiver no `MANIFEST.csv`, não se descarrega nada.
3. A API e o espelho **não são alternativas**: dão versões diferentes (no Metro, 11/11 e 21/10). Guardam-se ambos, cada um com a sua verificação (ver 9.1).
4. O XML nunca é extraído para o disco. O conversor lê o zip em streaming.
5. Uma troca de dados muda o cenário no config. Nunca se sobrescreve uma pasta de `gtfs/`.
6. Em `gtfs/<dataset>/` só há GTFS. O fallback `rglob` de `gtfs._find_gtfs_dir` passa a ser um erro.
7. Os caminhos de dados ficam num só sítio no config (hoje há 4 lugares que montam `data/<dataset>`).
8. `fetch_agit.py` nunca é chamado pelo regenerate nem pelos testes.

Migração: a D0.3 cria apenas `raw/`, que nenhum código lê ainda. A mudança de `data/smtuc` e afins para `data/gtfs/` faz-se no início da D1.4, num commit só de caminhos, validado com `snapshot_metrics.py diff --check` (zero números alterados).

### 9.1 Como garantir que os ficheiros são os certos (verificado a 2026-11-16)

Há quatro níveis de verificação, todos registados no `MANIFEST.csv`:

1. **Transporte:** o ficheiro chegou inteiro.
   - Do espelho: sha1 e tamanho do catálogo.
   - Da API: `artifact.sha256` do endpoint `/validation`, mais o `xmlSha256` do `netex.xml` e o sha256 do `metadata.jsonld`.
   - Confirmado para o Metro nos dois casos.
2. **Identidade:** é o conjunto e o período certos. O `metadata.jsonld` dentro do zip tem de ter o `dcterms:identifier` esperado, `modified` e `temporal`, e o período de validade tem de cobrir o dia de referência do cenário.
3. **Conteúdo:** é uma versão nova ou repetida.
   - A AGIT regenera os ficheiros sem mudar os dados: entre 21/10 e 11/11 só mudou `<PublicationTimestamp>`.
   - Por isso a impressão digital de conteúdo é o sha256 do XML **sem** essa linha. Se coincidir com uma versão já guardada, regista-se a nova publicação no manifest como "igual a X" e não se guarda outra cópia.
   - O `source.sha256` e o `releaseId` da validação identificam o GTFS interno de onde a AGIT parte.
4. **Semântica:** a conversão não perdeu nada. Depois de NeTEx→GTFS, as contagens têm de coincidir **exatamente** com `counts.gtfs` da validação. No Metro a 11/11 eram 40 paragens, 5 linhas, 979 viagens, 15 676 horários e 3 serviços. Segue-se o validador de feed (D1.3) e o `snapshot_metrics diff`.

### 9.2 Versões passadas

- **Metro:** só existe um GTFS (19/12/2025, já descarregado no planeamento). O NeTEx de 27/07 foi apagado do catálogo a 24/10 e dá 404. A API não tem histórico. A Wayback Machine estava em baixo e tem de se tentar outra vez. O Metro não está na Mobility Database. Restam duas vias: pedir à AGIT (cliente@agit.pt) os GTFS de origem por `releaseId`, ou arquivar a partir de agora com fetches periódicos.
- **SMTUC:** o Município publica **GTFS oficial** (`gtfs-estaticos-servicos-municipalizados-de-transportes-urbanos-de-coimbra`, atual de 18/09/2026), com dezenas de versões desde abril. A Mobility Database arquiva-as (`mdb-2851`, `mdb-2992`, `mdb-3535`): o `latest.zip` é público e o histórico completo exige um token gratuito. Isto pode dispensar o conversor no SMTUC e permite confirmar a origem do `data/smtuc` atual (Ep212). Licença "não especificada": confirmar antes de o publicar no repositório.

**Prova de origem (2026-11-16):** o sha256 do GTFS do Município (`Ep225_Prog1@202609182223`, válido de 18/09 a 12/11/2026, com `shapes.txt`) é igual ao `source.sha256` da validação AGIT do SMTUC, e as contagens coincidem. O NeTEx do SMTUC é portanto derivado desse GTFS. Na D2 usa-se o GTFS do Município diretamente, e o conversor NeTEx→GTFS fica só para o Metro e o SIT.

### 9.3 Estrutura escolhida (2026-11-16)

```
data/gtfs/
  smtuc/
    antigo_ep212/            pré-setembro 2026: Ep212_Prg1@20260305 (o data/smtuc atual)
    atual_ep225/             pós-setembro 2026: Ep225_Prog1@202609182223 (GTFS do Município)
  metro/
    fase1_gtfs_20251219/     até 09/09/2026: GTFS oficial (substitui o sintético)
    fase2_netex_<data>/      desde 10/09/2026 (início dos dias úteis da fase 2): NeTEx AGIT convertido
data/_arquivo/sintetico/     metrobus, metrobus_fase2
```

Linha 54, verificada em todas as versões acessíveis:

| Versão | Válido | Linha 54 |
|---|---|---|
| Ep194 | set/2025 | não existe |
| Ep202 | jan/2026 | não existe |
| Ep212 | a partir de 09/03/2026 | `route_id` 684/685, 42 viagens por dia útil, passa em Portagem e Portela |
| Ep225 | a partir de 18/09/2026 | `route_id` "54", 42 viagens, sai de Parque 2 |

**Armadilha:** nos feeds antigos, o `route_id` "54" é a linha **5F**. `transit.py:439-441` usa o `route_id` quando não encontra o nome curto, por isso num feed sem a 54 apanharia a 5F sem dar erro. Tem de ser corrigido, com teste.

**Decisões de 2026-11-16:**
- O corte do metro é a **10/09/2026**.
- O SMTUC antigo é o **Ep212**. Houve 73 carregamentos no catálogo do Município, em 8 dias entre março e setembro, e nenhum antigo ainda se descarrega. Em dia útil, o horário da 54 é **igual ao minuto** no Ep212 e no Ep225; só o terminal passou de "Portagem (Parque Manuel Braga)" a "Parque 2". Na rede, 75 de 99 linhas mantêm as viagens por dia útil (2373 → 2407 no total). As grandes mudanças vêm com o Ep225: saem a 7T e a 33, entra a 100E.

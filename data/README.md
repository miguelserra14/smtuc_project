# Dados: proveniência

Estado a 2026-11-16. Quando uma pasta mudar, atualiza esta tabela no mesmo commit.

## Feeds que o código lê hoje

Os feeds estão em `gtfs/` e o código chama-os pelo nome lógico de `config.DATASET_DIRS`: `smtuc` → `gtfs/smtuc/antigo_ep212/`, `metrobus` → `gtfs/metro/fase1_gtfs_20251219/` (oficial), `smtuc_atual` → `gtfs/smtuc/atual_ep225/`, `metro_fase2_oficial` → `gtfs/metro/fase2_netex_20261111/`. Que feeds se comparam, e em que dia, está em `config.SCENARIOS`: `antes` (Ep212 + Metro fase 1, 2026-05-11) e `fase2` (Ep225 + Metro fase 2, 2026-11-09).

| Pasta | O que é | Origem | Validade | Usado em |
|---|---|---|---|---|
| `gtfs/smtuc/antigo_ep212/` | SMTUC **Ep212** (`Ep212_Prg1@20260305`), cenário "antes" | GTFS do SMTUC/Município (versão exata e data do download não registadas; o catálogo já não tem esta versão) | 2026-03-09 a 2027-03-09 | tudo |
| `gtfs/metro/fase1_gtfs_20251219/` | Metro **oficial** fase 1 (nome lógico `metrobus`), construído por `scripts/build_feeds.py` a partir de `raw/dados-gov/metro-mondego-gtfs/`: sem PC1-PC8, calendário estendido até 2026-09-09, nomes da rota destrocados (ver `PROVENANCE.json`) | AGIT / dados.gov.pt, CC BY 4.0 | 2025-11-01 a 2026-09-09 | tudo (dataset `metrobus` desde a D1 passo 4) |
| `gtfs/smtuc/atual_ep225/` | SMTUC **Ep225** (`Ep225_Prog1@202609182223`, nome lógico `smtuc_atual`), construído por `scripts/build_feeds.py` de `raw/municipio-coimbra/smtuc-gtfs/` sem transformações. **Só o `PROVENANCE.json` é versionado** (licença por esclarecer): numa máquina nova, `fetch_feeds.py` e depois `build_feeds.py` reconstroem os `.txt` e confirmam que são os registados | Município de Coimbra (= origem do NeTEx SMTUC da AGIT) | 2026-09-18 a 2026-11-12 | cenário `fase2` (slide da fase 2) |
| `gtfs/metro/fase2_netex_20261111/` | Metro **oficial** fase 2 (nome lógico `metro_fase2_oficial`): NeTEx da AGIT de 2026-11-11 convertido por `gtfs_processing/netex_to_gtfs.py`; contagens iguais às `counts.gtfs` do `validation.json` da AGIT; nomes das linhas destrocados (U1, U2, U3, S1, S2); calendário semanal sem exceções (os feriados, que o Metro não codifica, ficam para `FERIADOS_COMO_DOMINGO`); sem `shapes.txt` (o NeTEx não traz geometria) | AGIT / dados.gov.pt, CC BY 4.0 | 2026-06-13 a 2026-12-31 (dias úteis desde 2026-09-10) | cenário `fase2` (slide da fase 2) |
| `dadospopulacaoBGRI/` | BGRI 2021 (subsecções estatísticas) do concelho de Coimbra | INE, Censos 2021 | 2021 | população, isócronas |
| `points_of_interest.csv` | polos de emprego e locais concorridos | pesquisa manual (`src/population/points_of_interest.py`) | — | população (camada POI) |

Arquivado: `_arquivo/sintetico/` (metro sintético das fases 1 e 2 e os scripts que os geraram/corrigiam; ver o README de lá). Sem uso no código, a arquivar: `gtfs_20deabril/` (só cabeçalhos, vazio), `gtfs_cp.zip` (GTFS da CP, sem `feed_info`) e `BGRI2021_0603.zip` (zip original do `.gpkg`).

## `raw/`: ficheiros oficiais congelados

`raw/<fonte>/<versão>/<ficheiro original>`, registados em `raw/MANIFEST.csv`, uma linha por publicação. Escreve-os só `scripts/fetch_feeds.py`: nunca se editam, nunca se substituem e ficam só de leitura.

| Fonte | Conteúdo | Cenário | Licença |
|---|---|---|---|
| `agit/metro-mondego-netex/` | NeTEx oficial do Metro (+ `validation.json` da AGIT) | Metro fase 2 (desde 10/09/2026) | CC BY 4.0, "Dados: AGIT / dados.gov.pt" |
| `dados-gov/metro-mondego-netex/` | espelho do anterior (outra publicação, mesmo conteúdo: só regista `igual`) | — | CC BY 4.0 |
| `dados-gov/metro-mondego-gtfs/` | GTFS oficial `20251219-export-gtfs.zip` | Metro fase 1 (até 09/09/2026) | CC BY 4.0 |
| `dados-gov/metro-mondego-kmz/` | `rede-metrobus.kmz` | mapas, Linha do Hospital (D4) | CC BY 4.0 |
| `municipio-coimbra/smtuc-gtfs/` | GTFS do SMTUC publicado pelo Município (Ep225, a partir de 18/09/2026) | SMTUC atual | **não especificada** no catálogo: o ficheiro **não é versionado** (`.gitignore`), só o sha256 no manifest; cada máquina corre o fetch |
| `agit/smtuc-netex-validacao/` | só o `validation.json` do NeTEx SMTUC: prova que é gerado do GTFS acima (`source.sha256`) e dá as contagens oficiais | — | CC BY 4.0 |
| `agit/sit-netex/`, `dados-gov/sit-percursos-gpkg/` | SIT (grupo `sit`, ainda não descarregado) | D3 | CC BY 4.0 |
| `manual/metro-mondego-horarios-pdf/2025-12-22/` | PDFs oficiais de horários (criados a 22/12/2025, descarregados a 06/09/2026) | validação do "antes" | Metro Mondego |
| `manual/metro-mondego-mapa/` | `Mapa-metro.svg` | — | Metro Mondego |

Como cada ficheiro é verificado (transporte, identidade, conteúdo, semântica): ver o docstring de `scripts/fetch_feeds.py` e a coluna `verificacoes` do manifest.

```
python scripts/fetch_feeds.py --dry-run         # há versões novas?
python scripts/fetch_feeds.py                   # descarrega o que for novo
python scripts/fetch_feeds.py registar FICH --fonte manual/<nome> --versao <AAAA-MM-DD>
```

## Próximas pastas (D1/D2)

Geradas a partir de `raw/` por `scripts/build_feeds.py`, com `PROVENANCE.json` (as da fase 2 já existem, ver acima; falta o SIT, D3). Uma pasta construída nunca é alterada: `python scripts/build_feeds.py --verificar` confirma que cada uma é exatamente o que o build produz. Os sintéticos vão para `_arquivo/sintetico/` quando deixarem de ser usados.

Atenção a duas coisas:
- nos feeds SMTUC antigos o `route_id` "54" é a linha 5F; a linha procura-se sempre pelo `route_short_name`;
- no Ep225 a 54 parte de "Parque 2".

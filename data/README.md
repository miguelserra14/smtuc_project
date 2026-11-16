# Dados: proveniência

Estado a 2026-11-16. Quando uma pasta mudar, atualiza esta tabela no mesmo commit.

## Feeds que o código lê hoje

Os feeds estão em `gtfs/` e o código chama-os pelo nome lógico de `config.DATASET_DIRS`: `smtuc` → `gtfs/smtuc/antigo_ep212/`, `metrobus` → `gtfs/metro/sintetico_fase1/`, `metrobus_fase2` → `gtfs/metro/sintetico_fase2/`.

| Pasta | O que é | Origem | Validade | Usado em |
|---|---|---|---|---|
| `gtfs/smtuc/antigo_ep212/` | SMTUC **Ep212** (`Ep212_Prg1@20260305`), cenário "antes" | GTFS do SMTUC/Município (versão exata e data do download não registadas; o catálogo já não tem esta versão) | 2026-03-09 a 2027-03-09 | tudo |
| `gtfs/metro/sintetico_fase1/` | Metro **SINTÉTICO** fase 1, feito à mão a partir de PDFs | não oficial (ver `docs/integracao_dados_agit/README.md`, secção 1) | `calendar.txt` copiado do SMTUC | tudo; substituído na D1 |
| `gtfs/metro/sintetico_fase2/` | Metro **SINTÉTICO** fase 2, topologia inventada | não oficial | idem | slide da fase 2; substituído na D2 |
| `dadospopulacaoBGRI/` | BGRI 2021 (subsecções estatísticas) do concelho de Coimbra | INE, Censos 2021 | 2021 | população, isócronas |
| `points_of_interest.csv` | polos de emprego e locais concorridos | pesquisa manual (`src/population/points_of_interest.py`) | — | população (camada POI) |

Sem uso no código, a arquivar: `gtfs_20deabril/` (só cabeçalhos, vazio), `gtfs_cp.zip` (GTFS da CP, sem `feed_info`) e `BGRI2021_0603.zip` (zip original do `.gpkg`).

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

Geradas a partir de `raw/`, com `PROVENANCE.json`: `gtfs/metro/fase1_gtfs_20251219/` (D1), `gtfs/smtuc/atual_ep225/` e `gtfs/metro/fase2_netex_<data>/` (D2). Os sintéticos vão para `_arquivo/sintetico/` quando deixarem de ser usados.

Atenção a duas coisas:
- nos feeds SMTUC antigos o `route_id` "54" é a linha 5F; a linha procura-se sempre pelo `route_short_name`;
- no Ep225 a 54 parte de "Parque 2".

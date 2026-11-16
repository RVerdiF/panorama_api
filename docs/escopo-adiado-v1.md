# Escopo adiado da v1 — itens fora do escopo com gatilho de entrada

Este documento registra o que **não** entra na v1 da API e o que precisa
acontecer para cada item ser reavaliado. Nenhum dos itens abaixo possui rota,
schema, stub ou qualquer implementação neste repositório.

Origem: plano `t_39045d95` (doc de origem em
`~/hermes/docs/panorama-api/t_39045d95-escopo-adiado-concorrentes.md`).
Card de registro: `t_e3564e46`.

## Itens FORA da v1 e gatilho de entrada

| Item | Por que fica fora | Gatilho para entrar (todos exigem piloto) |
|---|---|---|
| HHI como endpoint próprio | `mart_concentracao` existe, mas grão é município×ano×etapa×recorte×nível (4 variantes por etapa) — exige decidir recorte/nível padrão e semântica para o usuário | Piloto registra ≥1 pedido concreto de usuário por índice de concentração do município **e** decisão documentada de recorte/nível padrão |
| Perfil de rede (mantenedora) | Depende de CNPJ raiz com genéricos agregados em `PRIV_GENERICO` (PROJECT.md §17) — qualidade não validada para exposição | Piloto demanda visão por grupo/rede **e** auditoria de cobertura de CNPJ raiz não genérico em MG aprovada |
| Exportação CSV/Excel | Sem demanda medida; aumenta superfície (volume, formato, licença de dado) | Piloto mostra usuários copiando/extraindo dados manualmente de forma recorrente |
| Mapas e comparação por raio | Nenhuma mart calcula distância/raio; exigiria nova mart geoespacial (fora do escopo da API) | Piloto demonstra que comparação municipal é insuficiente **e** existe card aprovado no `panorama_escola` criando mart por raio |

Nenhum item acima ganha implementação, rota ou stub na v1.

## Notas de escopo

- "Todos exigem piloto" é condição necessária, não suficiente: o item só entra
  na API quando o gatilho da linha correspondente for integralmente satisfeito.
- Comparação de concorrentes na v1 é **municipal**; o termo "raio", "próximos"
  ou "na região" é proibido em rota, campos, OpenAPI e docs. A decisão do
  endpoint de concorrentes está registrada no doc de origem
  (`t_39045d95`), não neste arquivo.

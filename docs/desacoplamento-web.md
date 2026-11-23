# Desacoplamento do front `/app` (extração futura para `panorama_web`)

Decisão vigente: **monorepo no MVP, com desacoplamento preservado** (plano
`t_029a0162` §6, D1 = A). Este documento fixa o contrato que mantém a extração
do front para um repositório próprio **mecânica** em vez de reescrita.

O contrato é executável: `tests/unit/test_web_fronteira.py` falha se qualquer
regra abaixo for violada. Leia este documento junto do teste — se divergirem, o
teste manda (e a divergência é bug).

## 1. O que compõe o "front"

| Componente | Caminho | Papel |
|---|---|---|
| Pacote do front | `src/panorama_api/web/` | router `/app`, templates, assets, filtros |
| Router | `web/routes.py` | rotas `/app/*`, ambiente Jinja2, páginas de erro |
| Fachada de dados | `web/dados.py` | **único** caminho do front para dados |
| Regras de exibição | `web/filters.py`, `web/conteudo.py` | formatação de valor e vocabulário |
| Templates | `web/templates/` | layout, macros, telas |
| Assets | `web/static/` | CSS versionado por hash de conteúdo |
| Dados estáticos | `web/data/` | apoio de tela (ex.: municípios), sem BigQuery |
| Middleware | `web/middleware.py` | gzip restrito ao prefixo `/app` |
| Montagem | `main.py` | inclui `web_router` e registra o prefixo |

## 2. Imports permitidos dentro de `web/`

| Importado | Permitido? | Por quê |
|---|---|---|
| `panorama_api.contract`, `panorama_api.config`, `panorama_api.core.errors` | sim | contrato e infraestrutura de erro, sem I/O |
| `panorama_api.core.validation` | sim | validação de entrada compartilhada com `/v1` |
| `panorama_api.schemas.*` | sim | envelope `{data, meta, page}` |
| `panorama_api.services.*` | **só em `web/dados.py`** | ponto único de acesso a dado |
| `panorama_api.repositories.*`, `google.cloud` | **nunca** | o front não fala com a fonte de dados |
| `panorama_api.api.*` | **nunca** | o front não depende da camada HTTP do `/v1` |
| `panorama_api.web.*` | sim | o pacote é fechado em si |

Direção única, na outra ponta: **fora de `web/`, só `main.py` importa
`panorama_api.web`.** Nenhum módulo de `api/`, `services/`, `repositories/`,
`core/` ou `schemas/` conhece o front.

Regra de ouro para telas novas (F3–F5): a tela importa `web.dados`, `web.filters`
e `web.conteudo` — nunca `services`, nunca `repositories`.

O teste avalia a **AST**, não o texto: `from panorama_api import repositories`,
`from ..repositories import X` e nomes relativos são resolvidos para o nome
absoluto antes da comparação — escrever o import de forma rebuscada não burla a
fronteira.

## 3. Por que `dados.py` é o seam

`web/dados.py` reúne, para cada tela, uma função fina:

1. valida a entrada com `core.validation` (mesma validação do `/v1`, nenhuma
   regra nova);
2. obtém `(repositório, settings)` de `request.app.state` por `dados.fonte`;
3. delega ao caso de uso em `services/` e devolve o **mesmo** objeto Pydantic
   que o `/v1` devolve.

Consequências verificadas pelo teste:

- `routes.py` não importa `services` (critério de aceite do card);
- um único lugar muda na extração;
- a tela não pode divergir do contrato: o envelope é o mesmo objeto.

## 4. Procedimento de extração (passos)

Pré-requisito: decidir (Fase 2 do plano, com gatilho de piloto) que o front sai
do `panorama_api`. A partir daí:

1. **Criar `panorama_web`** e mover, preservando histórico (`git subtree split`
   ou `git filter-repo` limitado a `src/panorama_api/web/`, `tests/unit/test_web_*.py`
   e `docs/desacoplamento-web.md`):
   - `src/panorama_api/web/` → `src/panorama_web/` (renomear o pacote);
   - `web/templates/`, `web/static/`, `web/data/` junto do pacote;
   - ajustar `pyproject.toml`: `package-data` do pacote e dependências
     (`fastapi`, `jinja2`, `httpx`); `google-cloud-bigquery` **não** entra.
2. **Substituir `web/dados.py`** por um cliente do `/v1`: mesma superfície de
   funções, mesma assinatura (incluindo o `request`, que deixa de ter sentido e
   pode virar o cliente configurado), mesmos objetos de resposta. Os objetos
   Pydantic precisam ser reexportados ou copiados como contrato do cliente —
   alternativa aceitável é consumir `dict` e validar com os mesmos schemas.
   Toda chamada passa a ser HTTP (`GET /v1/...`) em vez de in-process.
3. **Trocar o erro**: `ProblemError` do `panorama_api` é substituído por um
   erro local equivalente que preserve `status`, `code` e `detail`, para que
   `pagina_erro` continue renderizando as mesmas páginas.
4. **Remover a montagem** em `panorama_api/main.py`: `web_router`,
   `WebGZipMiddleware`, `PAGINAS_ERRO`/`_is_web` e o prefixo `/app`. O serviço
   Cloud Run deixa de servir HTML; `/v1` não muda.
5. **Ajustar `pyproject.toml`** do `panorama_api`: sai `jinja2` e o
   `package-data` dos templates/assets.
6. **Autenticação**: IAP deixa de ser do `panorama_api` e passa a ser do novo
   serviço (ou do mesmo serviço, se o front for servido por outro path).
7. **DNS/caminho**: `/app` vira o host próprio; qualquer link interno troca de
   base — hoje tudo é relativo (`app_prefix`), então isso é configuração.
8. **Suíte**: os testes de `/v1` do `panorama_api` seguem intocados; os de
   interface (`test_web_fronteira.py` inclusive) migram junto — no repo novo,
   o teste de fronteira passa a verificar que **nada** importa o backend por
   código, apenas HTTP.

## 5. O que quebra e o que não quebra

**Não quebra (por construção):**

- `/v1` — nenhuma rota, status, header ou formato de erro do `/v1` depende do
  front; o repositório executa o mesmo código nas duas superfícies;
- `services/`, `repositories/`, `core/`, `schemas/` — não importam `web/`;
- o contrato de dados: `dados.py` devolve os mesmos objetos do `/v1`, então
  chaves, flags `is_*_missing` e tri-estado de oferta seguem idênticos;
- as regras de exibição: `filters.py`/`conteudo.py` são autocontidos (vocabulário
  apenas), e continuam valendo no repo novo sem o backend.

**Quebra (e precisa de card próprio):**

- renderização in-process: o novo cliente paga latência de rede e precisa de
  timeout, retry e mapeamento de `problem+json` → `ProblemError` local;
- `request.app.state` (repositório e settings): deixa de existir; vira
  configuração do cliente (`base_url`, credenciais IAP);
- `ETag`/LRU de páginas por `DATA_VERSION`/`APP_BUILD` (card F2): o front passa
  a ver essas versões pela resposta do `/v1`, não pelo processo;
- `WebGZipMiddleware` e o cache HTTP: precisam ser registrados no app novo;
- observabilidade (`page_view`, alertas de 503 em `/app`): pertencem ao serviço
  novo;
- custo: uma chamada HTTP por página em vez de uma consulta in-process — o
  número de consultas ao BigQuery **não** muda (mesmo código do `/v1`), mas o
  egress e o número de instâncias passam a ser do serviço do front.

## 6. Como verificar hoje

```bash
pytest tests/unit/test_web_fronteira.py -q
```

Cobre: imports proibidos em `web/`, ausência de `services` fora da fachada,
direção única `main.py → web`, ausência de BigQuery no front, e uma prova de que
o detector flagra cada forma de import proibido (mutação sintética — o teste não
passa por vacuidade).

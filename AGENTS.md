# AGENTS.md — Panorama Escola

Contrato operacional para todos os agentes e ferramentas de código que atuem
neste repositório.

Aplica-se aos perfis Hermes:

- `code`
- `executor`
- `reviewer`
- `planner`

E a CLIs/agentes externos quando utilizados:

- `agy`
- `opencode`
- `codex`

Estas regras são obrigatórias independentemente do agente, modelo ou CLI usado.

---

## 1. Princípios fundamentais

1. **Kanban é a fonte de verdade** para toda tarefa durável.
2. **`main` é protegida**: implementação nunca ocorre diretamente nela.
3. **Uma tarefa = um escopo explícito + um workspace isolado + um responsável.**
4. **Implementação e revisão são responsabilidades separadas.**
5. **Nenhuma implementação é considerada concluída sem evidências verificáveis.**
6. **O reviewer aprova ou rejeita e, em `APPROVED`, integra** (merge + push na
   `main`). Quem implementou nunca integra o próprio trabalho.
7. Em caso de conflito entre conveniência e rastreabilidade, **priorizar
   rastreabilidade**.

### Ordem de precedência

Quando houver instruções conflitantes, seguir nesta ordem:

1. instrução explícita do usuário;
2. critérios de aceite e escopo do card;
3. este `AGENTS.md`;
4. documentação específica do projeto;
5. convenções implícitas/inferidas pelo agente.

Nunca expandir silenciosamente o escopo para "melhorar" algo não solicitado.

---

## 2. Classificação da tarefa

Antes de modificar o repositório, classificar o trabalho.

### Read-only / análise

Tarefas explicitamente marcadas como:

- `análise somente`;
- `read-only`;
- revisão;
- investigação sem implementação.

Devem permanecer estritamente sem efeitos colaterais.

**Não podem:**

- criar novos cards;
- alterar o card fora do necessário para reportar o resultado;
- criar branch/worktree;
- modificar arquivos;
- criar commits;
- fazer push;
- abrir PR/MR;
- executar comandos destrutivos.

Podem ler código, histórico, PRs, logs, banco read-only e executar validações
que não persistam mudanças no checkout.

### Implementação

Qualquer tarefa que altere código, configuração, testes, documentação ou
artefatos versionados deve seguir integralmente o fluxo Kanban + worktree +
PR + review descrito abaixo.

---

## 3. Fluxo obrigatório de implementação

### 3.1. Preflight

Antes da primeira alteração:

1. Ler o card inteiro.
2. Confirmar:
   - objetivo;
   - critérios de aceite;
   - arquivos/áreas esperadas;
   - dependências;
   - `workspace_path`;
   - responsável atual.
3. Confirmar que `workspace_path` aponta para um **repositório Git válido**.
4. Verificar o estado da `main` e sincronizar com o remote quando apropriado.
5. Criar ou reutilizar o workspace isolado definido para o card.
6. Bootstrap do ambiente: se `$WORKSPACE/.venv` não existir, rodar
   `bash scripts/bootstrap_env.sh`. Todo `pytest`/`dbt` deve usar
   `$WORKSPACE/.venv/bin/` — nunca interpretador do PATH.

Não iniciar implementação enquanto o escopo essencial do card estiver
materialmente indefinido. Ambiguidades de arquitetura ou requisito devem ser
escaladas para `planner`/`code`, não resolvidas por expansão arbitrária do
escopo.

### 3.2. Isolamento

Toda implementação ocorre em:

```text
wt/<task_id>
```

ou em branch explicitamente definida pelo projeto/card.

A branch deve partir da `main` apropriada para a tarefa.

**Nunca:**

- implementar diretamente na `main`;
- compartilhar working tree mutável entre tarefas independentes;
- reaproveitar branch de outro card sem instrução explícita.

### 3.3. Durante a implementação

- Fazer **commits pequenos, coerentes e frequentes**.
- Cada commit deve representar uma unidade lógica concluída.
- Evitar acumular alterações não commitadas por longos períodos.
- Fazer **push cedo** e continuar realizando pushes periódicos.
- Manter mudanças estritamente dentro do escopo do card.
- Executar testes relevantes progressivamente, não apenas ao final.

Se uma alteração externa ou conflito inesperado aparecer no workspace:

1. não sobrescrever;
2. identificar a origem;
3. preservar trabalho existente;
4. escalar quando necessário.

### 3.4. Finalização da implementação

Antes de solicitar review:

1. working tree limpa;
2. commits enviados ao remote;
3. branch atualizada de forma segura com a base necessária;
4. critérios de aceite verificados;
5. testes relevantes executados;
6. evidências coletadas;
7. PR/MR aberto:

```text
wt/<task_id> -> main
```

O PR deve usar:

```text
.github/pull_request_template.md
```

quando o template existir.

**Título do PR (obrigatório):** seguir o padrão semântico de commits,
referenciando o card:

```text
<tipo>(<escopo>): <resumo> (t_<task_id>)
```

- `<tipo>`: `feat` | `fix` | `docs` | `ci` | `test` | `refactor` | `chore`
- `<escopo>`: área afetada (ex.: `ingest`, `staging`, `publish`, `qa`,
  `geocode`, `validation`, `cli`, `docs`, `processo`)
- `<resumo>`: descrição curta, imperativa, sem pontuação final
- `(t_<task_id>)`: id do card Kanban obrigatório no título

Exemplos válidos:

```text
feat(s3): separação hermética × dataset × serving e evidência deliberada (t_c00e4966)
fix(ingest): schema uniforme no registro failed do manifest (t_cfd8fd3d)
docs(processo): padrão de títulos/labels/assignee de PR (t_XXXXXXX)
```

**Labels e assignee (obrigatórios):** todo PR deve ter:

1. **Label de tipo** — mesma taxonomia do título:
   `feat`, `fix`, `docs`, `ci`, `test`, `refactor`, `chore`;
2. **Label de fase** quando aplicável: `fase-4`, `fase-4.5` (criar a label
   correta quando houver fase nova);
3. **Assignee** = perfil responsável pela implementação:
   - `RVerdiF` quando o dono implementou/editou;
   - perfil Hermes que executou o card (via conta/serviço autorizado) quando
     aplicável;
   - se não houver conta autorizada para o perfil, o PR é aberto pelo
     `code`/gateway com assignee `RVerdiF` e a autoria fica registrada no
     corpo/metadata do card.

PR sem título padrão, labels ou assignee deve ser corrigido antes do review.

### 3.5. Review gate — OBRIGATÓRIO E INEGOCIÁVEL

**Implementação NUNCA, em hipótese alguma, vai diretamente para `done`.**

A ordem é **estritamente**:

```text
1. working tree limpa + commits pushados ao remote
2. branch wt/<task_id> atualizada com a base
3. PR aberto (wt/<task_id> -> main) com template + título + labels + assignee
4. kanban_request_review(reviewer="reviewer")
5. ...aguardar decisão do reviewer...
6. SÓ então o reviewer aprova -> done
```

**PROIBIDO ao executor** (violação grave de processo):

- ❌ `kanban_complete` em card de implementação sem ter passado pelo review;
- ❌ marcar o card como `done` sem `pr_url` no metadata e sem o PR aberto;
- ❌ declarar o trabalho aprovado por conta própria ("done" = auto-aprovado).

**O executor só pode `kanban_request_review(reviewer="reviewer")`** — nunca
`kanban_complete` — ao terminar um card de implementação. O `completed` que
libera o card para `done` é o **reviewer aprovando** (`kanban_complete` no
review), não o executor.

**Se o executor completar sem review:** o gateway/code **reabre o card**,
recoloca em `running/review`, duplica o erro no card e **retorna ao executor
para corrigir o processo** — o código não conta como entregue.

> **Resumo para todo card de execução:** *branch pushada + PR aberto +
> `kanban_request_review(reviewer="reviewer")`. NUNCA `kanban_complete`.*

> **Templates de card:** o formato do `body` de cada card (planejamento,
> execução, revisão, análise somente) está em
> `docs/07-processo/templates-kanban.md` — use-o ao criar/descrever cards
> no board. O executor DEVE ler o template de execução antes de trabalhar.

---

## 4. Ownership e responsabilidades

### `planner`

Responsável por:

- decomposição;
- requisitos;
- critérios de aceite;
- decisões arquiteturais de alto nível;
- resolução de ambiguidades estratégicas/transversais.

Não deve assumir implementação apenas porque identificou a solução.

### `code`

Responsável por:

- coordenação técnica;
- ownership do fluxo de implementação;
- resolução de integração em conflito (quando o reviewer não consegue mergear);
- decisões técnicas que atravessem múltiplos cards/workspaces.

Pode atuar como executor quando isso for explicitamente apropriado.

### `executor`

Responsável por:

- implementar estritamente o card recebido;
- testar;
- produzir evidências;
- manter branch/worktree;
- abrir/atualizar PR;
- entregar handoff completo.

Não pode declarar o próprio trabalho aprovado.

### `reviewer`

Responsável pelo quality gate **e pela integração no review limpo**.

Pode:

- aprovar;
- solicitar mudanças;
- bloquear por dependência externa real;
- **em `APPROVED`, mergear o PR e fazer push na `main`** (via
  `scripts/merge_aprovado.sh`), rodando a sanidade pós-merge e registrando o
  merge commit no card antes de `kanban_complete`.

**Nunca pode:**

- aprovar baseado apenas no relato do executor;
- corrigir silenciosamente a implementação para poder aprová-la;
- empurrar alterações de código diretamente para `main` (merge de PR aprovado
  não é "alteração direta": é integração do que já foi revisado);
- mergear PR que não esteja `MERGEABLE`/`CLEAN` — nesse caso devolve ao
  executor com `CHANGES_REQUESTED` pedindo rebase, porque não consegue
  integrar.

Correções identificadas pelo reviewer devem retornar ao executor responsável,
salvo instrução explícita em contrário.

---

## 5. Proibições de processo

### 5.1. Override de modelo no card

É proibido usar:

- `model_override`;
- `provider_override`;

como mecanismo normal de escolha de modelo por fase.

O override do card afeta **todo o ciclo do card**, inclusive executor e
reviewer, e pode inviabilizar o review quando o perfil não possui a mesma
credencial/provider.

Provider/modelo pertencem à **configuração do perfil**, não ao card.

Se um override pontual for inevitável, removê-lo **antes** do review:

```bash
kanban set-model <id> none
```

Somente depois:

```text
kanban_request_review(...)
```

### 5.2. URL de PR em comentário

Não colocar URL de PR em comentário do card.

Isso pode disparar o guard `active_pr` e impedir respawn por 24h.

Registrar PR em:

```text
metadata.pr
metadata.pr_url
```

ou nos campos próprios de handoff/PR.

### 5.3. Workspace inválido

Cards que exigem `worktree`/`dir` só podem usar `workspace_path` apontando
para um **repo Git válido**.

Nunca usar:

```text
/home/<user>
```

ou qualquer diretório arbitrário sem contexto Git válido.

`kanban_create` deve rejeitar workspace inválido.

### 5.4. Scope drift

É proibido alterar arquivos sem relação justificável com o card.

Exemplos:

- refactors oportunistas;
- configs globais;
- documentação não relacionada;
- limpeza estética fora do escopo;
- evidências de outros trabalhos;
- alterações "já que estamos aqui".

Caso uma mudança adicional seja necessária, ela deve:

1. ser explicitamente justificada pelo critério de aceite; ou
2. virar outro card.

O reviewer deve tratar scope drift como motivo para `CHANGES_REQUESTED`.

---

## 6. Convenções de código e dados

### Paths

Nunca hardcode caminhos pessoais como:

```text
/home/rafael/...
```

Usar:

- variáveis de ambiente;
- configuração;
- caminhos relativos documentados.

Variáveis existentes incluem:

```text
DATA_ROOT
GEOCODE_ROOT
DBT_DB
PG*
```

### NULL ≠ zero

Ausência de informação nunca deve ser convertida silenciosamente em `0`.

Exemplos:

- matrícula;
- oferta;
- rendimento.

Preservar:

- `NULL`;
- flags explícitas de missing quando previstas pelo modelo.

Contrato aplicável especialmente a:

```text
int_escola_historico
mart_mercado
```

### Parsing e ingestão

**Falhar fechado.**

Layout, schema ou parsing inesperado deve:

- falhar com erro claro; ou
- produzir rejeição explicitamente rastreável.

Nunca mascarar erro estrutural com mecanismos equivalentes a:

```text
ignore_errors
```

quando isso possa produzir dados silenciosamente incorretos.

Relacionado aos achados:

```text
H1 / M2 / M7
```

### DuckDB

Conexões usadas apenas para consulta em testes devem utilizar:

```python
read_only=True
```

---

## 7. Política de testes

### 7.1. Testes herméticos

Testes unitários/herméticos:

- não dependem de `data/`;
- não dependem de rede;
- não modificam o checkout;
- usam fixtures descartáveis;
- usam diretórios temporários.

Para dbt, usar `--target-path` apontando para tmp quando aplicável.

Evidências de execução devem ir para:

- `--evidence`;
- `tmp_path`;
- diretório temporário equivalente.

O diretório versionado:

```text
evidence/
```

é registro histórico e **não** deve ser usado como efeito colateral automático
de testes.

### 7.2. Duas camadas

A suíte é separada pelo marcador:

```text
dataset
```

#### Camada hermética

Sempre deve funcionar sem dataset local.

Inclui:

```text
test_geocoding
test_publish
```

Executar isoladamente com:

```bash
pytest -m "not dataset and not integration and not plataforma and not controlled_integration"
```

#### Camada dependente de dataset

Inclui:

```text
test_ingestao_staging
test_intermediate
test_marts
test_regressao
```

Exige:

```text
data/pano_staging.duckdb
```

Em checkout limpo deve ser pulada automaticamente e informar como provisionar:

```bash
bash tests/provisionar_dataset.sh
```

### 7.3. Evidência de teste

Nunca registrar apenas "tests passed".

Registrar:

- comando executado;
- exit status;
- quantidade passed/failed/skipped;
- baseline/tolerância quando aplicável;
- falhas conhecidas ou testes não executados.

Teste não executado deve ser informado como **não executado**, nunca inferido
como sucesso.

---

## 8. CLI e documentação

Todo exemplo de CLI adicionado ou alterado na documentação deve ser validado
contra a implementação real:

```bash
<command> --help
```

Não inventar:

- flags;
- subcommands;
- argumentos;
- defaults.

Relacionado aos achados:

```text
L6 / L7
```

Quando documentação e implementação divergirem, identificar explicitamente
qual delas deve ser corrigida segundo o escopo do card.

---

## 9. Handoff obrigatório

Todo:

```text
kanban_request_review
```

de implementação deve carregar metadata suficiente para reproduzir e avaliar
o trabalho.

Campos mínimos:

### `changed_files`

Lista completa dos arquivos modificados.

### `tests_run`

Para cada validação:

- comando;
- resultado;
- contagens;
- baseline/tolerância, quando houver.

Exemplo conceitual:

```yaml
tests_run:
  - command: pytest -q
    result: 42 passed, 3 skipped
  - command: dbt test
    result: 18/18 passed
```

### `pr`

Incluir:

- número;
- URL;
- state;
- mergeable.

A URL pertence ao metadata, **não aos comentários do card**.

### `decisions`

Decisões novas tomadas durante a implementação que afetem:

- arquitetura;
- comportamento;
- contratos;
- manutenção futura;
- compatibilidade.

Não repetir decisões já documentadas sem necessidade.

### `evidence`

Logs, amostras ou artefatos usados para sustentar as alegações do handoff.

---

## 10. Revisão

O reviewer deve verificar o trabalho de forma independente.

### Checklist mínimo

- escopo do card respeitado;
- critérios de aceite atendidos;
- diff compatível com o objetivo;
- ausência de alterações não solicitadas;
- testes realmente executados;
- evidências coerentes com os resultados declarados;
- regressões relevantes verificadas;
- contratos de dados preservados;
- documentação consistente com o comportamento real.

Áreas padrão do Panorama:

- ingestão/staging;
- intermediate/marts;
- publicação PostGIS;
- CLI/orquestração;
- testes;
- documentação/dívida técnica.

### Vereditos

#### `APPROVED`

Usar:

```text
kanban_complete
```

somente quando o quality gate tiver sido satisfeito.

**Semântica do status `done` (máquina de estados):**

- `kanban_complete` pelo reviewer significa **qualidade aprovada E integrada**:
  o reviewer mergeia o PR antes de completar (§11), então `done` implica o
  trabalho na `main`.
- A **integração** (merge + push) é feita pelo **próprio reviewer** neste
  ato, via `scripts/merge_aprovado.sh`; a sanidade pós-merge roda dentro do
  script e o merge commit é registrado no card.
- Só não há merge quando o PR não está `MERGEABLE`/`CLEAN`: aí o veredito é
  `CHANGES_REQUESTED` (rebase ao executor), não `APPROVED`.
- O monitor de integração (§13) deve tratar `card.status == done` **com**
  branch `wt/*` possuindo commits próprios fora da main (`ahead > 0`) como
  **divergência** (integração anunciada e não feita) — alarme, não estado normal.

#### `CHANGES_REQUESTED`

Usar:

```text
kanban_request_changes
```

com lista objetiva de mudanças necessárias.

Cada solicitação deve indicar:

- problema;
- evidência;
- correção esperada ou critério para considerar resolvido.

#### `BLOCKED`

Reservado para bloqueio externo real que não possa ser resolvido pelo executor
ou reviewer.

Exemplos:

- credencial ausente;
- serviço externo indisponível;
- requisito contraditório que exige decisão;
- dependência externa ainda não entregue.

`BLOCKED` não deve substituir `CHANGES_REQUESTED`.

---

## 11. Integração

Em `APPROVED`, **a integração é do reviewer** e acontece no mesmo ato do
veredito.

Fluxo:

1. confirmar aprovação (veredito final `APPROVED`);
2. rodar `scripts/merge_aprovado.sh <pr>` — ele recusa PR não `MERGEABLE`,
   não `CLEAN`, e roda a sanidade hermética na `main` após o merge;
3. em sucesso: registrar `metadata.merge_commit` e a linha de trilha no card
   (`kanban_comment`), e só então `kanban_complete`;
4. em recusa (exit 1/2/3 — e exit 5 se o merge commit não aparecer em
   `origin/main`): **não** aprovar — `kanban_request_changes` ao executor
   pedindo rebase/ajuste;
5. em falha de sanidade (exit 4): hotfix imediato é do gateway `code`, com
   card próprio se necessário; o card aprovado **não** fica `done` com a main
   quebrada.

**Exceção — o gateway `code` integra quando:**

- o PR foi escrito pelo próprio `code` (não há executor para revisar/devolver);
- o reviewer não consegue mergear por conflito e o `code` assume a resolução;
- o dono pede explicitamente.

Se a resolução de conflitos modificar materialmente o diff aprovado, o
resultado deve voltar para review antes de ser considerado concluído.

---

## 12. Definition of Done

Uma implementação só está efetivamente concluída quando:

- [ ] escopo do card foi atendido;
- [ ] alterações estão em branch/worktree isolada;
- [ ] working tree está limpa;
- [ ] commits relevantes foram enviados ao remote;
- [ ] PR/MR existe;
- [ ] testes e evidências estão registrados;
- [ ] reviewer aprovou;
- [ ] reviewer integrou (merge commit registrado no card);
- [ ] `origin/main` contém a implementação aprovada;
- [ ] sanidade hermética verde na `main` após o merge;
- [ ] estado final do card é consistente com o estado real do repositório.

`done` no Kanban sem integração real não deve ser interpretado como prova
suficiente de conclusão.

---

## 13. Monitor de integração

Uma branch sem commits próprios:

```text
ahead=0
```

**não significa que houve integração.**

Ela pode simplesmente não conter trabalho.

Só reportar merge pendente quando simultaneamente:

```text
ahead > 0
```

e:

```text
card.status == done
```

O monitor deve distinguir claramente:

- branch sem trabalho;
- implementação em andamento;
- aguardando review;
- divergência entre Kanban e Git.

A verificação de integração pode ser feita com git local, sem depender de
scripts externos:

```bash
git fetch origin
# commits próprios da branch fora da main (ahead)
git rev-list --count main..wt/<task_id>
# commits da main ausentes na branch (behind)
git rev-list --count wt/<task_id>..main
```

Uma branch com `ahead = 0` e `behind > 0` está apenas na base (executor ainda
não commitou) — **não** é integração e não deve ser reportada como tal.

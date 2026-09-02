# panorama_api

API do Panorama Escola.

Este repositório contém a API Python do Panorama Escola. A estrutura inicial
está preparada para o desenvolvimento posterior com FastAPI, sem endpoints,
integrações ou regras de negócio nesta etapa.

## Ambiente de desenvolvimento

Crie o ambiente virtual com:

```bash
python3 -m venv .venv
```

Ative-o no Linux/macOS com:

```bash
source .venv/bin/activate
```

No Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

## Estrutura

```text
src/panorama_api/
├── api/v1/          # Rotas HTTP e endpoints versionados
├── core/            # Configuração e componentes compartilhados
├── repositories/    # Acesso às fontes de dados
├── schemas/         # Modelos de entrada e saída
└── services/        # Regras de aplicação

tests/unit/          # Testes isolados
tests/integration/   # Testes de integração
scripts/             # Scripts auxiliares
docs/                # Documentação técnica
```

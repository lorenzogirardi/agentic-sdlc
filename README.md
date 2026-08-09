# Agentic SDLC Platform

**Bead: B-001-000 | Version: 0.1.0 | Status: MVP (M0–M8)**

Automated, policy-guarded software delivery pipeline: a Trello card (or local
YAML task) triggers a DAG of specialized agents that plan, inspect, implement,
verify, and review changes on a repository — producing a structured report and,
optionally, a Pull Request. Every risky action requires human approval.

## 1. Obiettivo

Trasformare una card Trello formattata secondo la metodologia VSDD in un flusso
SDLC automatizzato ma controllato: tracciabilità totale (execution_id), policy
deterministica, zero esecuzioni arbitrarie, sicurezza by-default.

## 2. Diagramma architetturale

```
 Trello card ──webhook/poll──┐
 Task YAML  ────────────────▶│
                             ▼
                      ┌─────────────┐     ┌───────────────┐
                      │ Orchestrator│────▶│ Policy Engine │ (YAML, deterministico)
                      │ state mach. │     └───────────────┘
                      │ + DAG sched.│
                      └──────┬──────┘
                             │ parallel agents (semaphore)
        ┌──────────┬─────────┼──────────┬───────────┬───────────┐
        ▼          ▼         ▼          ▼           ▼           ▼
     Planner   Inspector   Lint      TestPyr    Security    Reviewer
     (LLM)     (scan)    (ruff)     (pytest)  (gitleaks/   (verdict)
                                               semgrep)        │
        │          │         │          │           │          ▼
        ▼          ▼         ▼          ▼           ▼      Report JSON
   OpenCode    ToolRunner (allowlist, timeout, secret redaction) ──▶ PR + Trello
   Adapter
```

## 3. Prerequisiti

- Python 3.12+
- Docker + Docker Compose (opzionale, per esecuzione containerizzata)
- Tool CLI opzionali: `ruff`, `pytest`, `gitleaks`, `semgrep`, `hadolint`,
  `terraform` (fallback controllato se assenti)

## 4. Setup locale

```bash
cd agentic-sdlc
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## 5. Configurazione environment

```bash
cp .env.example .env
# edit .env — nessun segreto va committato
```

Variabili: `OPENCODE_*` (LLM), `TRELLO_*` (cards + webhook), `GITHUB_*`,
`OTEL_EXPORTER_OTLP_ENDPOINT`, `PROMETHEUS_PORT`, `DRY_RUN`, `ALLOW_NETWORK`,
`ALLOW_TERRAFORM_APPLY`.

## 6. Avvio con Docker Compose

```bash
docker compose up --build sdlc          # esecuzione singola (dry-run demo)
docker compose --profile test up sdlc-test   # suite di test nel container
```

## 7. Avvio in dry-run

```bash
python -m orchestrator.engine \
  --task examples/local-task.yaml \
  --mode dry_run --no-opencode
```

Dry-run non tocca Trello, non crea branch/PR, non esegue comandi distruttivi.

## 8. Esecuzione con task YAML

```yaml
# examples/local-task.yaml
execution_id: local-demo-001
title: Add health endpoint
repository_path: ./examples/sample-service
requested_agents: [repo_inspector, test_pyramid, security, lint]
mode: dry_run
```

Report in `data/executions/<execution_id>/report.json`.

## 9. Configurazione Trello

- Modalità **webhook** (preferita): esponi `integrations/trello_webhook.py`
  (FastAPI) e registra il callback su Trello con `TRELLO_WEBHOOK_SECRET` +
  `TRELLO_WEBHOOK_CALLBACK_URL`. La firma HMAC-SHA1 è verificata.
- Modalità **polling** (fallback): `poll_trello(...)` con intervallo
  configurabile.
- Card attivata dalla label configurabile `TRELLO_RUN_LABEL_ID`.
- Sezioni riconosciute nella descrizione: `## Acceptance Criteria`, `## Agents`.

## 10. Configurazione GitHub

Token con permessi minimi (`contents:write`, `pull_requests:write`,
`issues:write` sul solo repo target). In `DRY_RUN=true` l'adapter non chiama
l'API. Adattatore no-op: `DryRunGitHubAdapter`.

## 11. Configurazione OpenCode

Endpoint OpenAI-compatible:

```env
OPENCODE_BASE_URL=https://opencode.ai/zen/v1
OPENCODE_API_KEY=<secret>
OPENCODE_MODEL=deepseek-v4-flash-free
```

Il modello non è hardcodato; output validato con JSON Schema; output non
conforme rifiutato; retry con backoff solo per errori trasienti (mai per
errori di validazione).

## 12. Gestione dei secret

- Solo env vars / GitHub Secrets — mai in codice, mai nei log.
- ToolRunner redaziona pattern di secret su stdout/stderr.
- CodingAgent rifiuta path che contengono `.env`, `secret`, `credential`.
- Firma webhook Trello verificata (HMAC-SHA1).

## 13. Esempio end-to-end

```bash
# 1. avvia il sample service target
python -m orchestrator.engine --task examples/local-task.yaml --mode dry_run --no-opencode
# 2. leggi il report
cat data/executions/local-demo-001/report.json
```

Verdict atteso: `PASS`, `PASS_WITH_WARNINGS`, `BLOCKED` o
`REQUIRES_HUMAN_APPROVAL`.

## 14. Troubleshooting

| Problema | Causa | Soluzione |
|----------|-------|-----------|
| `tool_blocked` | comando fuori allowlist | aggiungi a `policies/default.yaml` |
| `No such file or directory: gitleaks` | tool non installato | comportamento atteso: fallback controllato |
| verdict `REQUIRES_HUMAN_APPROVAL` | uno o più agenti falliti | leggi `findings` nel report |
| stato `BACKLOG` nel report | bug noto MVP: stato persistito da ultima scrittura | fixed via `update_state(..., ctx=ctx)` |

## 15. Limiti noti

- Nessun webhook Trello gestito in HA (singolo receiver).
- Cost Evaluation usa euristica statica, non Infracost live.
- Coverage test non aggregata cross-linguaggio.
- Nessun merge automatico (by design).

## 16. Roadmap

1. CodingAgent con apply su branch GitHub reale (PR mode).
2. Infracost integration per CostEvalAgent.
3. ReviewerAgent LLM-assisted con acceptance-criteria matching semantico.
4. Web UI per approval flow.
5. Supporto multi-repo per execution.

## 17. Threat model sintetico

Vedi [SECURITY.md](SECURITY.md): prompt injection, command injection, secret
leakage, terraform apply accidentale, esecuzioni duplicate, esfiltrazione OTLP.

## 18. Comandi Makefile

| Comando | Scopo |
|---------|-------|
| `make install` | Installa dipendenze + dev |
| `make test` / `test-integration` / `test-all` | Suite di test |
| `make lint` / `format` / `typecheck` | Quality gate |
| `make run` | Dry-run con task di esempio |
| `make build` | Build immagine Docker |
| `make clean` | Pulizia artefatti |

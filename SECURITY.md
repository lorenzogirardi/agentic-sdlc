# SECURITY.md — Agentic SDLC Platform

**Bead: B-001-029 | Last Updated: 2026-08-09**

## Threat Model (Synthetic)

| Threat | Vector | Impact | Mitigation |
|--------|--------|--------|------------|
| Prompt Injection | Untrusted content in Trello cards, README, issue comments, or repository files fed to LLM | Model executes unintended actions or leaks context | Input sanitization; policy engine blocks unauthorized commands; LLM never has direct shell access |
| Command Injection | Malicious strings in repository files interpreted by shell | Arbitrary code execution on runner | ToolRunner always uses structured args (`subprocess.run([...])`, never `shell=True`); allowlist enforcement |
| Secret Leakage | LLM output, logs, or PR comments contain API keys or tokens | Credential compromise | Regex-based redaction on all output; policy secrets never passed to LLM context; pre-commit checks |
| Privilege Escalation | Agent uses `sudo`, setuid, or privileged container | Host compromise | Non-root user in Docker; no privileged containers; `sudo` not in allowlist |
| Terraform Drift / Apply | Accidental `terraform apply` on production | Infrastructure destruction or cost spike | `terraform apply` hard-blocked by policy engine; never in allowlist for this mode |
| Branch/Push to Protected Branch | Agent pushes directly to main/master | Bypasses review/CI | Adapter creates feature branches only; PR mode never merges; protected branch rules in GitHub |
| Exfiltration via OTLP | Telemetry data sent to unauthorized collector | Data leak | OTLP endpoint configurable only via env var; default empty → no export |
| Resource Exhaustion | Infinite LLM loops or recursive tool calls | Cost spike, CI minutes exhaustion | Per-execution timeout (`max_execution_minutes`); max retries; max agent steps |
| Poisoned Dependencies | Malicious package in autofix (e.g., lint autofix adds import) | Supply chain compromise | Autofix disabled by default; all dependency changes flagged for human review |
| Duplicate Execution | Same card triggered twice simultaneously | Conflicting branches, wasted cost | Lock file per execution; duplicate detector in orchestrator |
| Untrusted Model Output | LLM returns code with vulnerabilities or backdoors | Security regression | All output verified by Security Agent before PR; findings with severity `critical` → BLOCKED |

## Sensitive Paths

- `.env` — Never commit; use `.env.example` for templates
- `data/executions/` — Contains state files with potentially sensitive repo metadata; excluded from git
- `policies/` — Policy files; review changes to `allowed_commands`

## Reporting

Report security issues via the repository security policy. Do not include secrets in issue descriptions.
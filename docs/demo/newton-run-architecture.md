# Inside the Pipeline: the Newton Run

**Visual version (with UI reconstructions):** https://claude.ai/code/artifact/c8a12718-d3a0-414a-ba98-535cb81ff89d
**Date:** 2026-08-12
**Trello card:** https://trello.com/c/5PkJ8tE0
**GitHub Action run:** https://github.com/lorenzogirardi/agentic-sdlc/actions/runs/31576762331
**Pull request:** https://github.com/lorenzogirardi/agentic-sdlc/pull/14
**Image:** `ghcr.io/lorenzogirardi/agentic-sdlc-fractal:latest`

## Purpose

A second, clean demonstration run — same pipeline as
[the Burning Ship Run](./burning-ship-storytelling.md), no debugging this
time. The card asked for a Newton fractal endpoint (`GET /newton`) on the
sample service. The point of this run is architectural: which agents ran,
in what order, why the planner chose them, what each one actually produced,
and where the system drew the line and asked for a human — not how many
bugs got fixed along the way.

## How to read this document

1. **In plain language** — what happened, for a non-technical reader
2. **Architecture** — C4 Context, Container, and Component views
3. **The flow, step by step** — one sequence diagram per stage, in order
4. **Agent-by-agent output** — the real table
5. **Honest caveats**

---

## 1. In plain language

Someone wanted a new feature on a small demo service: a fractal-generating
endpoint. They wrote what they wanted on a Trello card, the way they'd write
a ticket for any teammate, and attached a label. Nobody touched a keyboard
again for this task.

A little over a minute later, there was a pull request waiting for review,
with working code that matched the existing app's style, and a container
image ready to deploy. Nothing was merged automatically — the system found
one code-quality issue on its own and, by policy, that alone was enough to
stop and ask a human to look before anything ships. That pause isn't a bug;
it's the point.

| | |
|---|---|
| **Speed** | A request becomes a reviewable pull request in about the time it takes to read this paragraph. |
| **Specialization** | Seven different checks — code, tests, security, style, types, container hygiene — run every time, not just when someone remembers to. |
| **Judgment, not autopilot** | The one thing that failed was enough to hold the release for a human. No policy in this system allows a silent override. |

**Headline numbers:**

| | |
|---|---|
| Wall clock, card → PR + image | ~68 seconds |
| Agents invoked | 7 (`repo_inspector`, `coding`, `test_pyramid`, `security`, `lint`, `code_quality`, `docker`) + `planner` + `reviewer` |
| LLM calls | 1 (coding agent, single turn, 5830 tokens, 10.2s) |
| Findings that gated auto-merge | 1 (`code_quality` / mypy, exit code 2) |
| Verdict | `REQUIRES_HUMAN_APPROVAL` |

---

## 2. Architecture

The C4 model describes a system at increasing detail: who uses it and what
it talks to (**Context**), the deployable pieces inside it (**Container**),
and the parts one of those pieces is built from (**Component**).

### Context

```mermaid
C4Context
    title Agentic SDLC — System Context

    Person(dev, "Developer", "Writes the request as a Trello card. Never touches code for this task.")
    Person(reviewer, "Reviewer", "Reads the pull request, decides whether to merge.")

    System(sdlc, "Agentic SDLC Platform", "Turns a Trello card into a reviewed-ready code change and a published container image.")

    System_Ext(trello, "Trello", "Where the request is written down.")
    System_Ext(github, "GitHub", "Code, pipeline, pull request.")
    System_Ext(llm, "OpenCode Zen (DeepSeek)", "Writes the code, given the task and the existing files.")
    System_Ext(ghcr, "GitHub Container Registry", "Where the built image ends up.")

    Rel(dev, trello, "Creates a card, adds a label")
    Rel(sdlc, trello, "Receives the card via webhook")
    Rel(sdlc, github, "Triggers a run, opens a PR")
    Rel(sdlc, llm, "Asks for code, given the task and existing files")
    Rel(sdlc, ghcr, "Publishes the built image")
    Rel(reviewer, github, "Reviews and merges the PR")

    UpdateElementStyle(dev, $bgColor="#3b5b7d", $borderColor="#24405c", $fontColor="#ffffff")
    UpdateElementStyle(reviewer, $bgColor="#3b5b7d", $borderColor="#24405c", $fontColor="#ffffff")
    UpdateElementStyle(sdlc, $bgColor="#ff6b35", $borderColor="#c9451f", $fontColor="#ffffff")
    UpdateElementStyle(trello, $bgColor="#64748b", $borderColor="#45536b", $fontColor="#ffffff")
    UpdateElementStyle(github, $bgColor="#64748b", $borderColor="#45536b", $fontColor="#ffffff")
    UpdateElementStyle(llm, $bgColor="#64748b", $borderColor="#45536b", $fontColor="#ffffff")
    UpdateElementStyle(ghcr, $bgColor="#64748b", $borderColor="#45536b", $fontColor="#ffffff")
    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="2")
```
<sub>Blue = human actors · orange = the platform · grey = third-party systems</sub>

### Container

```mermaid
C4Container
    title Agentic SDLC — Containers (this run's path)

    Person(dev, "Developer")

    System_Boundary(sdlc, "Agentic SDLC Platform") {
        Container(webhook, "Webhook Receiver", "FastAPI, local + tunnel", "Verifies the Trello signature, decides local-run vs GitHub-run")
        Container(dispatch, "Dispatch Client", "Python / httpx", "Fires a repository_dispatch event")
        Container(action, "GitHub Actions Workflow", "agentic-run.yml", "Checks out, runs the orchestrator, opens the PR, builds the image")
        Container(orchestrator, "Orchestrator", "Python, LangGraph StateGraph", "Runs the agent DAG, applies policy, decides the verdict")
        Container(agents, "Agent Registry", "Python", "7 specialized checks")
    }

    System_Ext(trello, "Trello API")
    System_Ext(gh_api, "GitHub API")
    System_Ext(llm, "OpenCode Zen")
    System_Ext(ghcr, "GHCR")

    Rel(dev, trello, "Creates card")
    Rel(trello, webhook, "Webhook POST, HMAC-signed")
    Rel(webhook, dispatch, "On match: build TaskSpec")
    Rel(dispatch, gh_api, "repository_dispatch")
    Rel(gh_api, action, "Triggers workflow")
    Rel(action, orchestrator, "python -m orchestrator.engine")
    Rel(orchestrator, agents, "Runs each node, in DAG order")
    Rel(agents, llm, "Coding agent only: generate the change")
    Rel(action, gh_api, "Opens the pull request")
    Rel(action, ghcr, "Builds + pushes the image")

    UpdateElementStyle(dev, $bgColor="#3b5b7d", $borderColor="#24405c", $fontColor="#ffffff")
    UpdateElementStyle(webhook, $bgColor="#ff6b35", $borderColor="#c9451f", $fontColor="#ffffff")
    UpdateElementStyle(dispatch, $bgColor="#ff6b35", $borderColor="#c9451f", $fontColor="#ffffff")
    UpdateElementStyle(action, $bgColor="#ff8a5c", $borderColor="#c9451f", $fontColor="#ffffff")
    UpdateElementStyle(orchestrator, $bgColor="#ff8a5c", $borderColor="#c9451f", $fontColor="#ffffff")
    UpdateElementStyle(agents, $bgColor="#ff8a5c", $borderColor="#c9451f", $fontColor="#ffffff")
    UpdateElementStyle(trello, $bgColor="#64748b", $borderColor="#45536b", $fontColor="#ffffff")
    UpdateElementStyle(gh_api, $bgColor="#64748b", $borderColor="#45536b", $fontColor="#ffffff")
    UpdateElementStyle(llm, $bgColor="#64748b", $borderColor="#45536b", $fontColor="#ffffff")
    UpdateElementStyle(ghcr, $bgColor="#64748b", $borderColor="#45536b", $fontColor="#ffffff")
    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="2")
```
<sub>Blue = the developer · orange shades = platform containers · grey = third-party</sub>

### Component — inside the Orchestrator

```mermaid
C4Component
    title Orchestrator — Components exercised by this run

    Container_Boundary(orch, "Orchestrator") {
        Component(planner, "PlannerAgent", "Python", "LLM call, or deterministic fallback if the card already named the agents")
        Component(langgraph, "langgraph_engine.build_graph()", "LangGraph StateGraph", "Wires agents into a graph, enforces severity-blocking + human-approval interrupts")
        Component(policy, "PolicyEngine", "YAML-driven", "policies/default.yaml — what blocks, what requires a human")
        Component(toolrunner, "ToolRunner", "asyncio subprocess", "Runs the underlying CLI tools under an allowlist")
        Component(reviewer, "ReviewerAgent", "Python", "Aggregates every agent's result into one verdict")
    }

    Component_Ext(coding, "CodingAgent", "Reads existing files, calls the LLM, applies the diff")
    Component_Ext(quality, "5 verification agents", "test_pyramid, security, lint, code_quality, docker")

    Rel(planner, langgraph, "Hands off the DAG")
    Rel(langgraph, coding, "Runs first, outside the graph proper")
    Rel(langgraph, quality, "Runs each node in dependency order")
    Rel(quality, toolrunner, "Shells out to the real tool")
    Rel(langgraph, policy, "Checks severity + approval rules per node")
    Rel(langgraph, reviewer, "Last node — produces the verdict")

    UpdateElementStyle(planner, $bgColor="#ff6b35", $borderColor="#c9451f", $fontColor="#ffffff")
    UpdateElementStyle(langgraph, $bgColor="#ff6b35", $borderColor="#c9451f", $fontColor="#ffffff")
    UpdateElementStyle(policy, $bgColor="#ff8a5c", $borderColor="#c9451f", $fontColor="#ffffff")
    UpdateElementStyle(toolrunner, $bgColor="#ff8a5c", $borderColor="#c9451f", $fontColor="#ffffff")
    UpdateElementStyle(reviewer, $bgColor="#ff8a5c", $borderColor="#c9451f", $fontColor="#ffffff")
    UpdateElementStyle(coding, $bgColor="#64748b", $borderColor="#45536b", $fontColor="#ffffff")
    UpdateElementStyle(quality, $bgColor="#64748b", $borderColor="#45536b", $fontColor="#ffffff")
    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="2")
```
<sub>Orange = the graph/policy core · grey = the agents it drives</sub>

---

## 3. The flow, step by step

### Step 1 — card to dispatch

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#ff6b35','primaryBorderColor':'#c9451f','primaryTextColor':'#ffffff','actorBkg':'#3b5b7d','actorBorder':'#24405c','actorTextColor':'#ffffff','actorLineColor':'#94a3b8','signalColor':'#334155','signalTextColor':'#1e293b','labelBoxBkgColor':'#16a34a','labelBoxBorderColor':'#0f7a37','labelTextColor':'#ffffff','loopTextColor':'#334155','noteBkgColor':'#fde68a','noteBorderColor':'#b45309','noteTextColor':'#78350f','activationBorderColor':'#0f7a37','activationBkgColor':'#c8f0d8','sequenceNumberColor':'#ffffff'}}}%%
sequenceDiagram
    actor Dev as Developer
    participant Trello
    participant Webhook as Webhook (FastAPI)
    participant GH as GitHub API
    participant Actions as GitHub Actions

    Dev->>Trello: Create card "Add Newton fractal endpoint"<br/>label: agent:run
    Trello->>Webhook: POST /webhook/trello<br/>X-Trello-Webhook: base64 HMAC-SHA1
    rect rgba(22,163,74,0.10)
    Webhook->>Webhook: verify signature against API Secret
    Webhook->>Webhook: card_to_task() — parse Acceptance Criteria + Agents
    end
    Webhook->>GH: POST /repos/.../dispatches<br/>event_type=trello-card
    GH-->>Actions: repository_dispatch triggers agentic-run.yml
    Actions->>Actions: checkout, setup Python, pip install (~20s)
```
<sub>Green band = the fix from the Burning Ship run holding up on a clean delivery</sub>

### Step 2 — how the agents get chosen

The planner only calls an LLM when it has to. This card's `## Agents`
section already named all seven agents in canonical form, so the planner
resolves them against a known alias table and builds the dependency graph
**deterministically** — no model call, no ambiguity, no cost.

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#ff6b35','primaryBorderColor':'#c9451f','primaryTextColor':'#ffffff','actorBkg':'#3b5b7d','actorBorder':'#24405c','actorTextColor':'#ffffff','actorLineColor':'#94a3b8','signalColor':'#334155','signalTextColor':'#1e293b','labelBoxBkgColor':'#ff6b35','labelBoxBorderColor':'#c9451f','labelTextColor':'#ffffff','loopTextColor':'#334155','noteBkgColor':'#fde68a','noteBorderColor':'#b45309','noteTextColor':'#78350f','activationBorderColor':'#c9451f','activationBkgColor':'#ffd9c2','sequenceNumberColor':'#ffffff'}}}%%
sequenceDiagram
    participant Task as TaskSpec
    participant Planner as PlannerAgent
    participant Alias as Alias table
    participant LLM as OpenCode LLM

    Task->>Planner: requested_agents = [repo_inspector, coding,<br/>test_pyramid, security, lint, code_quality, docker]
    Planner->>Alias: resolve each name
    Alias-->>Planner: all 7 already canonical — unresolved list is empty
    rect rgba(100,116,139,0.12)
    Note over Planner,LLM: skipped entirely this run —<br/>only reached when a name is ambiguous
    Planner--xLLM: (not called)
    end
    Planner->>Planner: _fallback_plan() — build linear DAG deterministically
    Planner-->>Task: dag ready in 0.32ms
```
<sub>Grey band = the path not taken this run</sub>

A vaguer card ("make it more secure") would route through the LLM instead;
this one didn't need to.

### Step 3 — the coding step, in detail

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#ff6b35','primaryBorderColor':'#c9451f','primaryTextColor':'#ffffff','actorBkg':'#3b5b7d','actorBorder':'#24405c','actorTextColor':'#ffffff','actorLineColor':'#94a3b8','signalColor':'#334155','signalTextColor':'#1e293b','labelBoxBkgColor':'#16a34a','labelBoxBorderColor':'#0f7a37','labelTextColor':'#ffffff','loopTextColor':'#334155','noteBkgColor':'#fde68a','noteBorderColor':'#b45309','noteTextColor':'#78350f','activationBorderColor':'#0f7a37','activationBkgColor':'#c8f0d8','sequenceNumberColor':'#ffffff'}}}%%
sequenceDiagram
    participant CA as CodingAgent
    participant Repo as _read_repo_context()
    participant LLM as deepseek-v4-flash-free
    participant Pre as pytest + ruff pre-check

    CA->>Repo: read existing files under examples/sample-service/
    Repo-->>CA: app.py — existing /fractal and /burning-ship endpoints
    CA->>LLM: chat(system + user w/ existing code, schema=CodingResult)
    Note right of LLM: reasoning model · max_tokens=16384
    LLM-->>CA: 5830 tokens · 10.2s — one FileChange (app.py, +74 lines)
    CA->>CA: apply change to working tree
    rect rgba(22,163,74,0.10)
    CA->>Pre: pytest -q, ruff check .
    Pre-->>CA: both exit 0
    Note over CA: coding_converged — turn 1, no retry
    end
```
<sub>Green band = convergence on the first attempt</sub>

Same mechanism that failed three times on the Burning Ship run (Aug 11) —
this time it converged on the first attempt because the agent could see the
code it was extending.

### Step 4 — the verification DAG

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#ff6b35','primaryBorderColor':'#c9451f','primaryTextColor':'#ffffff','actorBkg':'#3b5b7d','actorBorder':'#24405c','actorTextColor':'#ffffff','actorLineColor':'#94a3b8','signalColor':'#334155','signalTextColor':'#1e293b','labelBoxBkgColor':'#ff6b35','labelBoxBorderColor':'#c9451f','labelTextColor':'#ffffff','loopTextColor':'#334155','noteBkgColor':'#fde68a','noteBorderColor':'#b45309','noteTextColor':'#78350f','activationBorderColor':'#c9451f','activationBkgColor':'#ffd9c2','sequenceNumberColor':'#ffffff'}}}%%
sequenceDiagram
    participant O as Orchestrator
    participant RI as repo_inspector
    participant TP as test_pyramid
    participant SEC as security
    participant LI as lint
    participant CQ as code_quality
    participant DK as docker
    participant REV as reviewer

    O->>RI: execute()
    RI-->>O: pass · 1.4ms
    O->>TP: execute() — pytest -q
    TP-->>O: pass · exit 0 · 2026ms
    rect rgba(180,83,9,0.10)
    O->>SEC: execute() — gitleaks + semgrep
    Note right of SEC: both binaries absent on the runner —<br/>no scan ran, reported as pass
    SEC-->>O: pass (unverified) · 1.4ms
    end
    O->>LI: execute() — ruff check
    LI-->>O: pass · exit 0 · 7ms
    rect rgba(225,29,72,0.10)
    O->>CQ: execute() — mypy --ignore-missing-imports
    CQ-->>O: FAIL · exit 2 · 168ms
    end
    rect rgba(180,83,9,0.10)
    O->>DK: execute() — hadolint
    Note right of DK: binary absent on the runner —<br/>no check ran, reported as pass
    DK-->>O: pass (unverified) · 1.3ms
    end
    O->>REV: aggregate all results
    REV-->>O: REQUIRES_HUMAN_APPROVAL — code_quality is the sole failure
```
<sub>Amber = unverified (tool missing) · red = the one real failure</sub>

**Execution order:** `repo_inspector → test_pyramid → security → lint →
code_quality → docker → reviewer`. (`coding` runs first, outside this DAG,
in its own converge-or-retry loop; `test_pyramid` and `lint` also fire once
as a fast pre-check right after coding, before the formal DAG shown above.)

### Step 5 — PR and image

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#ff6b35','primaryBorderColor':'#c9451f','primaryTextColor':'#ffffff','actorBkg':'#3b5b7d','actorBorder':'#24405c','actorTextColor':'#ffffff','actorLineColor':'#94a3b8','signalColor':'#334155','signalTextColor':'#1e293b','labelBoxBkgColor':'#16a34a','labelBoxBorderColor':'#0f7a37','labelTextColor':'#ffffff','loopTextColor':'#334155','noteBkgColor':'#fde68a','noteBorderColor':'#b45309','noteTextColor':'#78350f','activationBorderColor':'#0f7a37','activationBkgColor':'#c8f0d8','sequenceNumberColor':'#ffffff'}}}%%
sequenceDiagram
    participant Actions as GitHub Actions
    participant GH as GitHub API
    participant GHCR

    rect rgba(22,163,74,0.10)
    Actions->>GH: push branch agentic/31576762331
    Actions->>GH: open PR #14 ("Agentic SDLC run 31576762331")
    Actions->>GHCR: docker login
    Actions->>GHCR: docker buildx build --push<br/>tags: latest, commit-sha
    GHCR-->>Actions: pushed, digest sha256:3b82c7f6...
    end
```
<sub>Green band = the deliverable, published</sub>

---

## 4. Agent-by-agent output

| Agent | What it does | Result | Duration | Note |
|---|---|---|---|---|
| `planner` | Decides which agents run and in what order | pass | 0.32ms | Deterministic fallback — see Step 2 |
| `coding` | Writes the actual endpoint code | pass | 10.2s | 1 LLM turn, 5830 tokens, converged immediately |
| `repo_inspector` | Detects language, framework, test setup | pass | 1.4ms | — |
| `test_pyramid` | Runs the existing test suite | pass | 2.0s | `pytest -q`, exit 0 |
| `security` | Scans for secrets and vulnerable patterns | pass (**unverified**) | 1.4ms | gitleaks + semgrep not installed on this runner |
| `lint` | Style and formatting | pass | 7ms | `ruff check .`, exit 0 |
| `code_quality` | Static type checking | **fail** | 168ms | `mypy --ignore-missing-imports .`, exit code 2 — sole cause of the human-review gate |
| `docker` | Dockerfile hygiene | pass (**unverified**) | 1.3ms | hadolint not installed on this runner |
| `reviewer` | Aggregates everything into one verdict | ran | 0.15ms | `REQUIRES_HUMAN_APPROVAL` |

### The code

A hand-rolled Newton's-method solver for `f(z) = z³ − 1` — the classic
three-basin Newton fractal — added next to the existing `/fractal` and
`/burning-ship` endpoints, matching their response shape and clamping
conventions:

```python
@app.get("/newton")
async def newton(
    iterations: int = 5, width: int = 400, height: int = 300,
    xmin: float = -1.0, xmax: float = 1.0, ymin: float = -1.0, ymax: float = 1.0,
) -> JSONResponse:
    max_iter = max(1, min(iterations, 100))
    w = max(100, min(width, 800))
    h = max(75, min(height, 600))
    points = _newton_set(w, h, xmin, xmax, ymin, ymax, max_iter)
    return JSONResponse(content={"type": "newton", ...})
```

No new tests were added for the endpoint — the acceptance criteria required
existing tests to keep passing, but didn't explicitly ask for new coverage,
and the coding agent didn't volunteer any.

---

## 5. Honest caveats

1. **`security` and `docker` didn't really check anything this run** —
   their underlying tools (gitleaks, semgrep, hadolint) aren't installed on
   this GitHub Actions runner. A missing binary is currently treated as "no
   findings" rather than "couldn't verify." Worth fixing (install the tools
   in the workflow, or fail loudly when a scanner binary is absent) before
   relying on those two gates for anything real.
2. **No test coverage for the new endpoint.**
3. **mypy's actual error text isn't captured in the structured logs** —
   only its exit code. A reviewer would need to run mypy locally to see
   what it flagged.

## Reconstructed screens

No browser was available in this session to capture real screenshots of
Trello or GitHub. The [visual version](https://claude.ai/code/artifact/c8a12718-d3a0-414a-ba98-535cb81ff89d)
includes UI reconstructions built from the real API data shown here (card
content, run step timings, PR file stats, image tags) — explicitly labeled
as reconstructions, not screenshots.

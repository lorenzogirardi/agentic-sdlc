# The Burning Ship Run — a real Trello card, a real AI pipeline, six real bugs

**Visual version:** https://claude.ai/code/artifact/99a5f5de-206d-4cc7-93f1-48c32f7f9f38
**Date:** 2026-08-11 → 2026-08-12
**Trigger:** one Trello card, created by a human, never touched again except to add a label
**Result:** [PR #12](https://github.com/lorenzogirardi/agentic-sdlc/pull/12) merged-ready, Docker image live on GHCR
**Full run:** https://github.com/lorenzogirardi/agentic-sdlc/actions/runs/31575555378

---

## How to read this document

1. **TL;DR** — the 60-second version
2. **Architecture** — what the system is made of (C4 Context + Container)
3. **The journey** — one diagram showing all six failed attempts and what fixed each
4. **Six bugs, step by step** — each one: what broke, the mechanism (diagram), the fix, the commit
5. **The clean run** — full sequence diagram, end to end, once everything worked
6. **Why this is the story worth telling**

---

## 1. TL;DR

We asked one question: *if a developer only ever creates a Trello card, can a
team of AI agents take it all the way to a reviewable pull request and a
published Docker image — with no human writing a line of code, wiring a
webhook, or babysitting a build?*

We ran it for real, against a live Trello board and a live GitHub repo, not a
simulation. It found **six real bugs in our own automation** on the way —
a webhook signature check that could never have worked, a container that
silently ran as root, an infinite retry loop quietly burning API credits, and
an AI coding agent that rewrote a working app in the wrong framework because
nobody had shown it the app it was supposed to be extending. We fixed every
one of them live, using the same agents' own findings to know where to look,
and re-ran the exact same card until it worked cleanly.

That's the real story: not a demo that worked on the first try, but a system
whose safety checks caught its own mistakes — and ours — before anything
shipped broken.

---

## 2. Architecture

### Context — who talks to this system

```mermaid
C4Context
    title Agentic SDLC — System Context

    Person(dev, "Developer", "Creates a Trello card. Never touches code for this task.")
    Person(reviewer, "Reviewer", "Reads the pull request the system opens, decides whether to merge.")

    System(sdlc, "Agentic SDLC Platform", "Turns a Trello card into a reviewed-ready code change and a published container image.")

    System_Ext(trello, "Trello", "Where the request is written down.")
    System_Ext(github, "GitHub", "Code, pipeline, pull request.")
    System_Ext(llm, "OpenCode Zen (DeepSeek)", "Writes the code, given the task and the existing files.")
    System_Ext(ghcr, "GHCR", "Where the built image ends up.")

    Rel(dev, trello, "Creates card, adds label")
    Rel(sdlc, trello, "Receives the card via webhook")
    Rel(sdlc, github, "Triggers a run, opens a PR")
    Rel(sdlc, llm, "Asks for code")
    Rel(sdlc, ghcr, "Publishes the image")
    Rel(reviewer, github, "Reviews and merges")

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

### Container — the pieces this run exercised

```mermaid
C4Container
    title Agentic SDLC — Containers

    Person(dev, "Developer")

    System_Boundary(sdlc, "Agentic SDLC Platform") {
        Container(webhook, "Webhook Receiver", "FastAPI + ngrok tunnel", "Verifies the Trello signature")
        Container(dispatch, "Dispatch Client", "Python / httpx", "Fires repository_dispatch")
        Container(action, "GitHub Actions Workflow", "agentic-run.yml", "Runs the orchestrator, opens the PR, builds the image")
        Container(orchestrator, "Orchestrator", "Python, LangGraph StateGraph", "Runs the agent DAG, applies policy")
        Container(agents, "Agent Registry", "Python", "repo_inspector, coding, test_pyramid, security, lint, code_quality, docker")
    }

    System_Ext(trello, "Trello API")
    System_Ext(gh_api, "GitHub API")
    System_Ext(llm, "OpenCode Zen")
    System_Ext(ghcr, "GHCR")

    Rel(dev, trello, "Creates card")
    Rel(trello, webhook, "Webhook POST, HMAC-signed")
    Rel(webhook, dispatch, "Build TaskSpec, dispatch")
    Rel(dispatch, gh_api, "repository_dispatch")
    Rel(gh_api, action, "Triggers workflow")
    Rel(action, orchestrator, "python -m orchestrator.engine")
    Rel(orchestrator, agents, "Runs each node")
    Rel(agents, llm, "Coding agent: generate the change")
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
<sub>Blue = the developer · orange shades = platform containers (darker where the entry point/dispatch lives) · grey = third-party</sub>

Every bug in this story lives on one of these arrows. Keep this picture in
mind — each numbered step below points back to the hop that broke.

---

## 3. The journey — six failed attempts, one diagram

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#e11d48','primaryBorderColor':'#a8102f','primaryTextColor':'#ffffff','lineColor':'#64748b','tertiaryColor':'#fde68a'}}}%%
stateDiagram-v2
    [*] --> WorkflowBroken: trigger card

    WorkflowBroken --> WebhookRejected: fix path prefix (99827c0)
    WebhookRejected --> DockerBlocked: fix signature base64 (a1fed29)
    DockerBlocked --> InfiniteLoop: fix root USER (f1bb0e3)
    InfiniteLoop --> LLMRejected400: fix label removal (bd6498d)
    LLMRejected400 --> LLMEmptyReply: fix response_format (14fdf3b)
    LLMEmptyReply --> WrongFramework: fix max_tokens + retry (cd0c047, 2a499c8)
    WrongFramework --> CleanRun: fix blind codegen (b31eb46)
    CleanRun --> [*]: PR #12 + image on GHCR

    WorkflowBroken: Step 1 — bad path prefix
    WebhookRejected: Step 2 — signature always 401
    DockerBlocked: Step 3 — container ran as root
    InfiniteLoop: Step 4 — card reprocessed 9×
    LLMRejected400: Step 5a — response_format rejected
    LLMEmptyReply: Step 5b — empty completions
    WrongFramework: Step 6 — FastAPI rewritten to Flask
    CleanRun: Clean run

    classDef failState fill:#e11d48,color:#ffffff,stroke:#a8102f,stroke-width:1px
    classDef okState fill:#16a34a,color:#ffffff,stroke:#0f7a37,stroke-width:1px
    class WorkflowBroken,WebhookRejected,DockerBlocked,InfiniteLoop,LLMRejected400,LLMEmptyReply,WrongFramework failState
    class CleanRun okState
```
<sub>Red = broken · green = the one state that shipped</sub>

Every arrow above is a real commit, found by running the system against
live infrastructure instead of mocks. None of these were visible from
reading the code — they only surfaced once a real Trello webhook, a real
LLM, and a real GitHub Actions runner were all in the loop at once.

---

## 4. Six bugs, step by step

### Step 1 — the workflow that would have failed before touching an agent

`.github/workflows/agentic-run.yml` still pointed at
`agentic-sdlc/examples/sample-service` — a path prefix left over from before
the repository's layout was flattened. First real run would have failed at
"checkout", before a single agent ran.

**Fixed in `99827c0`**, before the first trigger — caught by review, not by
a failed run.

### Step 2 — the signature check that could never have verified anything

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#ff6b35','primaryBorderColor':'#c9451f','primaryTextColor':'#ffffff','actorBkg':'#3b5b7d','actorBorder':'#24405c','actorTextColor':'#ffffff','actorLineColor':'#94a3b8','signalColor':'#334155','signalTextColor':'#1e293b','labelBoxBkgColor':'#ff6b35','labelBoxBorderColor':'#c9451f','labelTextColor':'#ffffff','loopTextColor':'#334155','noteBkgColor':'#fde68a','noteBorderColor':'#b45309','noteTextColor':'#78350f','activationBorderColor':'#c9451f','activationBkgColor':'#ffd9c2','sequenceNumberColor':'#ffffff'}}}%%
sequenceDiagram
    participant Trello
    participant Webhook

    Trello->>Webhook: POST /webhook/trello<br/>X-Trello-Webhook: base64(HMAC-SHA1(secret, body+callbackURL))
    rect rgba(225,29,72,0.10)
    Webhook->>Webhook: computed = hexdigest(HMAC-SHA1(secret, body+callbackURL))
    Note right of Webhook: base64 string ≠ hex string, always
    Webhook-->>Trello: 401 Unauthorized
    end
```
<sub>Red band = where it fails · amber = notes</sub>

Trello signs webhook payloads with HMAC-SHA1, **base64-encoded**. The
verification code compared against a **hex** digest instead. Every real
delivery, for as long as this integration has existed, would have been
rejected — nobody had tested it against an actual Trello webhook until this
run.

```
2026-08-11 20:15:49 [warning] trello_webhook_bad_signature
INFO: "POST /webhook/trello HTTP/1.1" 401 Unauthorized
```

**Fixed in `a1fed29`**, with a regression test asserting a hex signature is
explicitly rejected — so this exact bug can't come back silently.

### Step 3 — the container that silently ran as root

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#ff6b35','primaryBorderColor':'#c9451f','primaryTextColor':'#ffffff','actorBkg':'#3b5b7d','actorBorder':'#24405c','actorTextColor':'#ffffff','actorLineColor':'#94a3b8','signalColor':'#334155','signalTextColor':'#1e293b','labelBoxBkgColor':'#ff6b35','labelBoxBorderColor':'#c9451f','labelTextColor':'#ffffff','loopTextColor':'#334155','noteBkgColor':'#fde68a','noteBorderColor':'#b45309','noteTextColor':'#78350f','activationBorderColor':'#c9451f','activationBkgColor':'#ffd9c2','sequenceNumberColor':'#ffffff'}}}%%
sequenceDiagram
    participant Orch as Orchestrator
    participant Docker as DockerAgent
    participant Policy as PolicyEngine

    Orch->>Docker: execute() — static Dockerfile checks
    Docker->>Docker: no USER directive found
    rect rgba(225,29,72,0.10)
    Docker-->>Orch: finding SDLC-DOCKER-001, severity=high
    Orch->>Policy: should_block_on_severity("high")?
    Policy-->>Orch: true (policy default: block on high/critical)
    Orch--xOrch: raise PolicyBlockedError
    Note over Orch: pipeline halts — no PR, no image
    end
```
<sub>Red band = the safety mechanism doing its job, not a bug</sub>

Once the webhook worked, the pipeline actually ran — and one of its own
agents caught something real: `examples/sample-service/Dockerfile` had no
`USER` directive. The severity-blocking mechanism (built earlier this
session, previously dead code that nothing had ever exercised) did exactly
what it was designed to do.

```
[error] graph_node_blocked  node=docker  severity=high
Verdict: BLOCKED
Summary: Execution failed: node 'docker' blocked by policy (severity=high)
```

This one is not a bug in the demo — it's the safety mechanism working
exactly as built. **Fixed in `f1bb0e3`** by adding a non-root `USER app`.

### Step 4 — the card that reprocessed itself nine times

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#ff6b35','primaryBorderColor':'#c9451f','primaryTextColor':'#ffffff','actorBkg':'#3b5b7d','actorBorder':'#24405c','actorTextColor':'#ffffff','actorLineColor':'#94a3b8','signalColor':'#334155','signalTextColor':'#1e293b','labelBoxBkgColor':'#b45309','labelBoxBorderColor':'#7c3a06','labelTextColor':'#ffffff','loopTextColor':'#334155','noteBkgColor':'#fde68a','noteBorderColor':'#b45309','noteTextColor':'#78350f','activationBorderColor':'#c9451f','activationBkgColor':'#ffd9c2','sequenceNumberColor':'#ffffff'}}}%%
sequenceDiagram
    participant Cron as sdlc-run.yml (cron, every ~15min)
    participant Trello
    participant Card as Demo card

    rect rgba(180,83,9,0.08)
    loop every scheduled poll — 9 times, unattended
        Cron->>Trello: fetch_cards(board_id, label_id=agent:run)
        Trello-->>Cron: [Card] — label still attached, board-wide match
        Cron->>Card: process again, prepend [BLOCKED] to name
        Note right of Card: label never removed —<br/>card matches again next poll
    end
    end
```
<sub>Amber = silent, unattended waste — not a crash, a slow leak</sub>

While debugging the above, the demo card's title had accumulated **nine**
`[BLOCKED]` prefixes. The scheduled Trello-polling workflow matches cards by
label across the *entire board*, and nothing ever removed the label after a
card was processed — so every card that ever got labeled `agent:run` was
silently re-run, forever, on every subsequent poll. Each unattended re-run
burned real OpenCode and GitHub Actions usage.

**Fixed in `bd6498d`**: the label is now stripped after processing.

### Step 5 — the LLM that returned nothing, for two different reasons

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#ff6b35','primaryBorderColor':'#c9451f','primaryTextColor':'#ffffff','actorBkg':'#3b5b7d','actorBorder':'#24405c','actorTextColor':'#ffffff','actorLineColor':'#94a3b8','signalColor':'#334155','signalTextColor':'#1e293b','labelBoxBkgColor':'#ff6b35','labelBoxBorderColor':'#c9451f','labelTextColor':'#ffffff','loopTextColor':'#334155','noteBkgColor':'#fde68a','noteBorderColor':'#b45309','noteTextColor':'#78350f','activationBorderColor':'#c9451f','activationBkgColor':'#ffd9c2','sequenceNumberColor':'#ffffff'}}}%%
sequenceDiagram
    participant CA as CodingAgent
    participant LLM as OpenCode Zen

    rect rgba(225,29,72,0.10)
    Note over CA,LLM: 5a — before fix 14fdf3b
    CA->>LLM: chat(response_format=json_schema)
    LLM-->>CA: 400 "response_format type is unavailable now"
    end
    rect rgba(180,83,9,0.10)
    Note over CA,LLM: 5b — after 5a fixed, before cd0c047
    CA->>LLM: chat(prompt-based JSON, max_tokens=4096)
    Note right of LLM: reasoning model — thinking tokens<br/>count against the same budget
    LLM-->>CA: content="" (budget spent on reasoning)
    end
```
<sub>Red = rejected request · amber = silently starved of output budget</sub>

- **Rejected request.** `response_format: json_schema` — the "give me
  strict, schema-validated JSON" API mode — was rejected outright by the
  free-tier model routing with a `400 invalid_request_error`. Fixed by
  asking for JSON through the prompt instead, with lenient parsing that
  also strips markdown code fences (`14fdf3b`).
- **Silent empty replies.** Even after that fix, the model sometimes
  returned a completely empty response. We looked up the model's real specs
  on models.dev instead of guessing further: `deepseek-v4-flash-free` is a
  **reasoning model** with interleaved `reasoning_content` — its thinking
  tokens count against the same `max_tokens` budget as its final answer. At
  `max_tokens=4096`, it was burning the entire budget on reasoning and
  never emitting the answer. Real output ceiling is 128,000 tokens; default
  raised to 16,384 (`cd0c047`), and genuinely empty completions made
  retryable rather than a hard failure (`2a499c8`).

### Step 6 — the agent that rewrote a working app in the wrong framework

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#ff6b35','primaryBorderColor':'#c9451f','primaryTextColor':'#ffffff','actorBkg':'#3b5b7d','actorBorder':'#24405c','actorTextColor':'#ffffff','actorLineColor':'#94a3b8','signalColor':'#334155','signalTextColor':'#1e293b','labelBoxBkgColor':'#ff6b35','labelBoxBorderColor':'#c9451f','labelTextColor':'#ffffff','loopTextColor':'#334155','noteBkgColor':'#fde68a','noteBorderColor':'#b45309','noteTextColor':'#78350f','activationBorderColor':'#c9451f','activationBkgColor':'#ffd9c2','sequenceNumberColor':'#ffffff'}}}%%
sequenceDiagram
    participant CA as CodingAgent
    participant LLM as OpenCode Zen
    participant Tests as pytest

    rect rgba(225,29,72,0.10)
    Note over CA,Tests: before fix b31eb46 — CodingAgent never sends existing code
    CA->>LLM: chat(task description only)
    LLM-->>CA: FileChange — full app.py, rewritten in Flask
    CA->>Tests: pytest -q
    Tests-->>CA: FAIL (existing tests expect FastAPI)
    Note over CA: retry turn 2, 3 — same rewrite, same failure
    end
    rect rgba(22,163,74,0.10)
    Note over CA,Tests: after fix — reads existing code first
    CA->>CA: _read_repo_context() — read app.py
    CA->>LLM: chat(task + existing_files, "extend, don't replace")
    LLM-->>CA: FileChange — new endpoint added, FastAPI untouched
    CA->>Tests: pytest -q
    Tests-->>CA: PASS
    end
```
<sub>Red = blind rewrite, breaks tests · green = same agent, now shown the real code</sub>

With the LLM finally responding, the pipeline produced its first real code —
and CodingAgent used it to rewrite the sample service from **FastAPI to
Flask**, from scratch, breaking every existing test. Three self-correction
turns, three failures, verdict `REQUIRES_HUMAN_APPROVAL`:

```
coding_feedback  feedback=['Tests failed. Fix: 1 error in 0.96s']
coding_feedback  feedback=['Tests failed. Fix: 1 error in 0.26s']
coding_feedback  feedback=['Tests failed. Fix: 1 error in 0.27s']
```

The root cause, once we looked: **CodingAgent never showed the LLM the
existing code.** It prompted for a solution from a task description alone,
with zero visibility into what `app.py` already looked like — so the model
had nothing to extend and invented something plausible-but-wrong instead.

**Fixed in `b31eb46`**: the agent now reads the existing source files under
the target repository and includes them in the prompt, with an explicit
instruction to extend the existing framework rather than replace it.

---

## 5. The clean run

Same card, same label, one more trigger:

```
coding_turn      turn=1
agent_done       agent=coding  success=True
coding_converged turn=1
```

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#ff6b35','primaryBorderColor':'#c9451f','primaryTextColor':'#ffffff','actorBkg':'#3b5b7d','actorBorder':'#24405c','actorTextColor':'#ffffff','actorLineColor':'#94a3b8','signalColor':'#334155','signalTextColor':'#1e293b','labelBoxBkgColor':'#16a34a','labelBoxBorderColor':'#0f7a37','labelTextColor':'#ffffff','loopTextColor':'#334155','noteBkgColor':'#fde68a','noteBorderColor':'#b45309','noteTextColor':'#78350f','activationBorderColor':'#0f7a37','activationBkgColor':'#c8f0d8','sequenceNumberColor':'#ffffff'}}}%%
sequenceDiagram
    actor Dev as Developer
    participant Trello
    participant Webhook
    participant GH as GitHub API
    participant Actions as GitHub Actions
    participant Orch as Orchestrator (LangGraph)
    participant GHCR

    Dev->>Trello: Create card, label agent:run
    Trello->>Webhook: POST /webhook/trello (signature OK)
    Webhook->>GH: repository_dispatch (event_type=trello-card)
    GH-->>Actions: triggers agentic-run.yml
    Actions->>Orch: python -m orchestrator.engine --task ci-task.yaml --mode pr
    rect rgba(22,163,74,0.10)
    Orch->>Orch: repo_inspector → coding → test_pyramid → security →<br/>lint → code_quality → docker → reviewer
    Orch-->>Actions: verdict=REQUIRES_HUMAN_APPROVAL
    end
    Actions->>GH: push branch, open PR #12
    Actions->>GHCR: docker buildx build --push
    Actions-->>Dev: PR ready for review
```
<sub>Green band = the run that finally went clean</sub>

CodingAgent added `GET /burning-ship`, matching the existing `/fractal`
endpoint's pattern exactly — same clamping logic, same response shape, a new
`_burning_ship_set` helper sitting next to the existing `_julia_set` one,
plus three new tests. Zero deletions of working code:

```python
@app.get("/burning-ship")
async def burning_ship(
    iterations: int = 5,
    width: int = 400,
    height: int = 300,
    xmin: float = -2.0,
    xmax: float = 1.0,
    ymin: float = -1.5,
    ymax: float = 1.5,
) -> JSONResponse:
    max_iter = max(1, min(iterations, 200))
    w = max(100, min(width, 800))
    h = max(75, min(height, 600))
    ...
```

All seven requested agents passed (`repo_inspector`, `coding`,
`test_pyramid`, `security`, `lint`, `code_quality`, `docker`). Docker image
published:

```
ghcr.io/lorenzogirardi/agentic-sdlc-fractal:latest
ghcr.io/lorenzogirardi/agentic-sdlc-fractal:b31eb465edeee921b6d7388442bfe95ea4cd3332
```

Verdict: `REQUIRES_HUMAN_APPROVAL` — by design. No policy in this system
allows an unattended merge, ever. The PR sits open, waiting for a human,
exactly as intended.

---

## 6. Why this is the story worth telling

A demo that had worked cleanly on the first attempt would have proven
nothing except that the happy path exists. What actually happened is a
stronger claim: **the verification layer caught six real problems — five in
our own infrastructure, one in the AI agent's judgment — before any of them
reached a human as a broken PR or a vulnerable container image.** Every fix
was driven by evidence the system itself produced (a log line, a severity
finding, a failed test, a real API spec lookup), not by guessing. And the
one thing that never happened, through six rounds of failure: nothing was
ever force-merged, silently retried into a broken state, or shipped without
a human able to say no.

---

## Appendix — raw artifacts

- Trello card: https://trello.com/c/nYkVhmFI
- Final GitHub Action run: https://github.com/lorenzogirardi/agentic-sdlc/actions/runs/31575555378
- Final pull request: https://github.com/lorenzogirardi/agentic-sdlc/pull/12
- Docker image: `ghcr.io/lorenzogirardi/agentic-sdlc-fractal:latest`
- Fix commits, in order: `99827c0`, `a1fed29`, `f1bb0e3`, `bd6498d`, `14fdf3b`, `2a499c8`, `cd0c047`, `b31eb46`

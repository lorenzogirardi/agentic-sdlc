# Inside the Pipeline: the Newton Run

**Visual version (C4 + sequence diagrams + business summary):** https://claude.ai/code/artifact/c8a12718-d3a0-414a-ba98-535cb81ff89d
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

## Headline numbers

| | |
|---|---|
| Wall clock, card → PR + image | ~68 seconds |
| Agents invoked | 7 (`repo_inspector`, `coding`, `test_pyramid`, `security`, `lint`, `code_quality`, `docker`) + `planner` + `reviewer` |
| LLM calls | 1 (coding agent, single turn, 5830 tokens, 10.2s) |
| Findings that gated auto-merge | 1 (`code_quality` / mypy, exit code 2) |
| Verdict | `REQUIRES_HUMAN_APPROVAL` |

## How agent selection actually worked

The Trello card's `## Agents` section named all seven agents by their
canonical names. `PlannerAgent` resolves each name against a known alias
table (`agents/planner.py:AGENT_ALIASES`); when every name resolves cleanly
— no unrecognized or ambiguous agent name — the LLM path is skipped
entirely and a linear DAG is built deterministically in `_fallback_plan()`.
This run: `planner` completed in **0.32ms**, no model call. The LLM planning
path only activates when a card leaves agent selection ambiguous (e.g. "make
this more secure" instead of naming `security` explicitly).

## Execution order (from the real run log)

```
repo_inspector → test_pyramid → security → lint → code_quality → docker → reviewer
```
(`coding` runs first, outside the verification DAG, in its own
converge-or-retry loop; `test_pyramid` and `lint` also run once as a fast
pre-check right after coding, before the formal DAG.)

## Agent-by-agent, verbatim results

| Agent | Result | Duration | Detail |
|---|---|---|---|
| `planner` | pass | 0.32ms | Deterministic fallback, no LLM call |
| `coding` | pass | 10.2s | 1 LLM turn, 5830 tokens, `deepseek-v4-flash-free`, converged immediately |
| `repo_inspector` | pass | 1.4ms | |
| `test_pyramid` | pass | 2.0s | `pytest -q`, exit 0 |
| `security` | pass (**unverified**) | 1.4ms | gitleaks + semgrep not installed on the runner — no scan actually ran |
| `lint` | pass | 7ms | `ruff check .`, exit 0 |
| `code_quality` | **fail** | 168ms | `mypy --ignore-missing-imports .`, exit code 2 — sole cause of the human-review gate |
| `docker` | pass (**unverified**) | 1.3ms | hadolint not installed on the runner — no static check actually ran |
| `reviewer` | ran | 0.15ms | Aggregated verdict: `REQUIRES_HUMAN_APPROVAL` |

## The code

`CodingAgent` (fixed the day before, see the Burning Ship writeup) read the
existing `app.py` — including the `/fractal` and `/burning-ship` endpoints
already there — and added a third, matching their exact response shape and
parameter-clamping conventions: a hand-rolled Newton's-method solver for
`f(z) = z³ − 1`, the classic three-basin Newton fractal.

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

## Honest caveats

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
Trello or GitHub. The visual version linked above includes UI
reconstructions built from the real API data shown here (card content, run
step timings, PR file stats, image tags) — explicitly labeled as
reconstructions, not screenshots.

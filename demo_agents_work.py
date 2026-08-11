"""E2E: Trello → Agentic Conversation (coding → fix → verify) → Report.

The user ONLY creates a Trello card. Agents do everything else.
"""

import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

from integrations.opencode_adapter import OpenCodeAdapter
from integrations.trello_adapter import TrelloRESTAdapter
from orchestrator.engine import Orchestrator
from orchestrator.execution_context import ExecutionStore
from orchestrator.policy_engine import PolicyEngine
from runners.tool_runner import ToolRunner
from schemas.execution import ExecutionMode

load_dotenv(".env")

K = os.getenv("TRELLO_API_KEY")
T = os.getenv("TRELLO_TOKEN")
B = os.getenv("TRELLO_BOARD_ID")
L = os.getenv("TRELLO_LIST_ID")
LABEL = os.getenv("TRELLO_RUN_LABEL_ID")
OC_BASE = os.getenv("OPENCODE_BASE_URL")
OC_KEY = os.getenv("OPENCODE_API_KEY")
P = {"key": K, "token": T}
IN_PROGRESS = "6a784e64550433b46214797e"
DONE = "6a784e64550433b46214797f"
TODO = "6a784e64550433b46214797d"

OUT_DIR = Path("docs/demo/agentic_conversation")


async def cleanup_board(c: httpx.AsyncClient) -> None:
    r = await c.get(f"https://api.trello.com/1/boards/{B}/cards", params=P)
    if r.status_code == 200:
        for card in r.json():
            await c.delete(f"https://api.trello.com/1/cards/{card['id']}", params=P)


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    def save(name: str, data: object) -> None:
        with open(OUT_DIR / name, "w") as f:
            json.dump(data, f, indent=2, default=str)

    print("=" * 70)
    print("  AGENTIC SDLC — Trello → Agents Do The Work")
    print(f"  {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    # ── User action: clean board + create card ──
    async with httpx.AsyncClient(timeout=10) as c:
        await cleanup_board(c)

    desc = """## Acceptance Criteria
- GET /mandelbrot returns Mandelbrot set fractal data as JSON
- parameters: iterations (1-500), width (100-800), height (75-600), xmin/xmax/ymin/ymax (float)
- input is clamped and validated
- all existing tests still pass (6/6 total)
- ruff lint reports zero errors
- type annotations on all new code

## Agents
- coding
- security
- code_quality"""

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            "https://api.trello.com/1/cards",
            params=P,
            json={
                "name": "[AGENTS] Add Mandelbrot set endpoint to fractal API",
                "desc": desc,
                "idList": L,
                "idLabels": [LABEL],
            },
        )
        card = r.json()

    save("01_trello_card.json", card)
    card_url = card.get("url", "?")
    print(f"\n📋 User creates Trello card: [{card['shortLink']}]")
    print(f"   {card_url}")
    print("   Agents requested: coding, security, code_quality")

    # ── Move to In Progress ──
    trello = TrelloRESTAdapter(api_key=K, token=T, dry_run=False)
    await trello.move_card(card["id"], IN_PROGRESS)
    await trello.add_comment(card["id"], "⚙️ Orchestrator starting — agents will do the work")

    # ── Convert to TaskSpec ──
    task = trello.card_to_task(card, "./examples/sample-service", mode=ExecutionMode.DRY_RUN)
    save("02_taskspec.json", task.model_dump())

    # ── Run orchestrator (conversation loop built-in) ──
    store = ExecutionStore()
    policy = PolicyEngine.from_yaml("policies/default.yaml")
    runner = ToolRunner(allowed_commands=policy.get_allowed_commands())
    opencode = OpenCodeAdapter(base_url=OC_BASE, api_key=OC_KEY)
    orch = Orchestrator(store=store, policy_engine=policy, runner=runner, opencode=opencode)

    t0 = time.perf_counter()
    report = await orch.run(task)
    elapsed = time.perf_counter() - t0

    save("03_final_report.json", report)
    if store.load(task.execution_id):
        save("04_execution_state.json", store.load(task.execution_id).model_dump())

    verdict = report["verdict"]
    print(f"\n{'─' * 50}")
    print(f"  Verdict: {verdict}  |  {elapsed:.1f}s  |  {len(report['agent_results'])} agents")
    print(f"{'─' * 50}")
    for a in report["agent_results"]:
        s = "PASS" if a["status"] == "SUCCESS" else "FAIL"
        print(f"  {s:6s} {a['agent_name']:20s} {a['duration_ms']:8.0f}ms")

    if report.get("findings"):
        print("\n  Findings:")
        for f in report["findings"][:5]:
            print(f"    - {f[:130]}")

    # ── Update Trello ──
    prefix = {
        "PASS": "PASS",
        "PASS_WITH_WARNINGS": "PASS*",
        "BLOCKED": "BLOCKED",
        "REQUIRES_HUMAN_APPROVAL": "REVIEW",
    }
    new_name = f"[{prefix.get(verdict, verdict)}] {card['name'].replace('[AGENTS] ', '')}"
    await trello.update_card_fields(card["id"], name=new_name)

    comment = [
        "## 🤖 Agents Did The Work\n",
        f"**Verdict:** {verdict}",
        f"**Duration:** {elapsed:.1f}s",
        f"**Execution ID:** `{report['execution_id']}`",
        "**LLM:** deepseek-v4-flash-free\n",
        "### Conversation\n",
    ]
    for a in report["agent_results"]:
        s = "PASS" if a["status"] == "SUCCESS" else "FAIL"
        comment.append(f"- {s} **{a['agent_name']}** ({a['duration_ms']:.0f}ms)")
    if report.get("findings"):
        comment.append("\n### Findings\n")
        for f in report["findings"][:8]:
            comment.append(f"- {f}")
    comment.append("\n---\n_Agents converged after conversation loop — no human wrote code_")

    await trello.add_comment(card["id"], "\n".join(comment))

    dest = DONE if verdict == "PASS" else TODO
    await trello.move_card(card["id"], dest)

    print(f"\n  Card updated: {new_name}")
    print(f"  URL: {card_url}")

    # ── Save file diff ──
    app_content = Path("examples/sample-service/app.py").read_text()
    test_content = Path("examples/sample-service/test_app.py").read_text()
    save("05_result_app.py.txt", app_content)
    save("06_result_test_app.py.txt", test_content)

    print(f"\n{'=' * 70}")
    print("  DONE — agents wrote code, verified, reported")
    print(f"  Trello: {card_url}")
    print(f"  Artifacts: {OUT_DIR}/")
    print(f"{'=' * 70}")

    await trello.close()


if __name__ == "__main__":
    asyncio.run(main())

# self-improving-deck

A Temporal durable-execution demo where two Claude agents collaboratively generate and refine an HTML presentation deck, with a human-in-the-loop feedback loop that survives crashes, restarts, and multi-hour waits.

## Purpose

This repo exists to demonstrate Temporal concepts:
- Durable workflow execution (resume from last success after any failure)
- Long-lived `wait_condition` for async human feedback (hours/days)
- Signals and queries against a running workflow
- Activity retries and heartbeating
- Two-agent collaboration orchestrated by a single workflow

## Project Layout

```
self-improving-deck/
├── activities.py      # All Temporal activities (Claude API calls + file I/O)
├── workflow.py        # SelfImprovingDeckWorkflow definition
├── worker.py          # Starts the Temporal worker process
├── starter.py         # Starts a new workflow run
├── feedback.py        # Sends signals to a running workflow (feedback / approve)
├── status.py          # Queries current workflow state
├── content.md         # Presentation input — edit this to change deck content
├── requirements.txt
└── output/            # Generated HTML decks land here (gitignored except .gitkeep)
    ├── deck_latest.html
    └── deck_v<N>.html
```

## Running the Demo

> See `README.md` for the full step-by-step instructions to run the demo.

## Demonstrating Durable Execution

To show crash recovery live:
1. Start the workflow (`python starter.py`)
2. Kill the worker mid-activity (`Ctrl+C`)
3. Restart the worker (`python worker.py`)
4. Observe: the workflow resumes from the last completed activity — no repeated LLM calls

The 72-hour `wait_condition` in `workflow.py` is not a sleep timer — it is persisted in Temporal's event history. The process can be restarted at any point during the wait and the workflow will still unblock correctly when a signal arrives.

## Claude's Role in This Repo

Claude must not write or modify any code in this repository,except for files under `agents/output/` which are generated artifacts. Claude's role is strictly advisory:
- Point to the exact file and line number where a change is needed
- Explain *what* to change and *why*
- Provide code snippets as suggestions only — the human writes all code
- If asked to write code directly, decline and offer a suggestion instead

## Conventions

- Python 3.12+
- Always use Claude SDK
- Temporal server must be running on `localhost:7233`
- All activities call `activity.heartbeat()` at least once to signal liveness
- Activities are idempotent — safe for Temporal to retry on failure
- Do not use `time.sleep()` inside workflows — use `await asyncio.sleep()` or `workflow.wait_condition()`
- The workflow ID `self-improving-deck-001` is fixed for demo purposes; change in `starter.py` for multiple runs
- Generated decks are self-contained single HTML files — no external CSS/JS dependencies

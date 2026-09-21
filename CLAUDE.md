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
├── agents/
│   ├── activities.py  # All Temporal activities (Claude Agent SDK calls + file I/O)
│   ├── workflow.py    # Deck workflow definition (run, submit_feedback, approve)
│   ├── saga.py        # Saga helper — compensation stack, unwound LIFO
│   ├── models.py      # Dataclasses passed across the workflow/activity boundary
│   ├── worker.py      # Starts the Temporal worker process
│   ├── app.py         # Starts a new workflow run
│   ├── feedback.py    # Sends feedback (update) / approval (signal) to a running workflow
│   └── output/        # Generated HTML decks land here
│       └── deck_<workflow_id>.html
├── content/
│   └── content.md     # Presentation input — edit this to change deck content
├── improvement.md     # Running list of demo improvements
├── index.html
└── requirements.txt
```

## Running the Demo

> See `README.md` for the full step-by-step instructions to run the demo.

## Demonstrating Durable Execution

To show crash recovery live:
1. Start the workflow (`python app.py`) and note the Workflow ID it prints
2. Kill the worker mid-activity (`Ctrl+C`)
3. Restart the worker (`python worker.py`)
4. Observe: the workflow resumes from the last completed activity — no repeated LLM calls

The 72-hour `wait_condition` in `workflow.py` is not a sleep timer — it is persisted in Temporal's event history. The process can be restarted at any point during the wait and the workflow will still unblock correctly when a signal arrives.

## Claude's Role in This Repo

Claude must not write or modify any code in this repository,except for files under `agents/output/` and index.html which are generated artifacts. Claude's role is strictly advisory:
- Point to the exact file and line number where a change is needed
- Explain *what* to change and *why*
- Provide code snippets as suggestions only — the human writes all code
- If asked to write code directly, decline and offer a suggestion instead

## Conventions

- Python 3.12+
- Always use Claude SDK
- Temporal server must be running on `localhost:7233`
- Long-running activities (those calling Claude) heartbeat inside their message loop, and their `execute_activity` call sets a `heartbeat_timeout`; fast file-I/O activities do not heartbeat
- Activities are idempotent — safe for Temporal to retry on failure
- Side-effecting steps register a compensation with `Saga.add()` immediately after succeeding; compensations run LIFO via `Saga.compensate()` and must be safe to run when the action never happened
- Do not use `time.sleep()` inside workflows — use `await asyncio.sleep()` or `workflow.wait_condition()`
- `app.py` generates a unique workflow ID per run (`deck-workflow-<8 hex chars>`) so the demo can be re-run without hitting `WorkflowAlreadyStartedError`; `feedback.py` takes that ID as its first positional argument (`python feedback.py <workflow_id> --feedback "..."` or `--approve`)
- Generated decks are self-contained single HTML files — no external CSS/JS dependencies

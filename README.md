## Getting started
This repository shows how hard it is to generate a deck and iterate on it with human feedback durably. It sounds like a simple exercise — until you run it in a distributed environment where the worker can crash, the model can fail mid-edit, and the human can take days to respond.

> Note: This may be an overly simplified example, but in a production setting e.g. transfer fund, make travel booking, these considereations may be worth considering.

**4 Areas to be covered:**
Interaction    — signal vs update vs query; validators; handler concurrency
Detection      — timeouts; heartbeats; retryable vs terminal errors
Recovery       — idempotency; saga/compensation; durability/replay
Foundation     — determinism & sandbox; workflow ID reuse; schema evolution

## Architecture 

### Failure Cases

| Failure Case No. | Workflow | Failure Case Name | Failure Case Description |
|---|---|---|---|
| 1 | Deck.run() | Retries exhausted — Durability (Scenario A) | `generate_deck` fails on every attempt (network, `ClaudeAgentFailed`, `EmptyResult`). Retry policy gives 3 attempts with 5s → 10s backoff. Because the deck is written via `.tmp` + `os.replace`, no partial file is ever visible. After attempt 3, `saga.compensate()` runs `delete_deck(delete_all=True)` and the workflow FAILS with nothing left on disk. |
| 2 | Deck.run() | Non-retryable Claude error — Retryable vs terminal (Scenario C) | Claude reports "Not logged in". `_as_temporal_error` maps it to `ApplicationError(type="Unauthorized", non_retryable=True)`, which is in `non_retryable_error_types`. Attempts 2 and 3 are skipped; compensation runs immediately. Retrying a login failure would only waste ~35s. |
| 3 | Deck.run() | No approval within timer — Timeout (Scenario B) | `wait_condition(approved, timeout=3m)` is a durable timer in event history — it survives worker restarts. On expiry the workflow raises `ApprovalTimeout`, waits for any in-flight update handler to finish, then `delete_deck(delete_all=True)` removes deck, backup and `.tmp`. Workflow FAILS. |
| 4 | Deck.run() | Worker crash mid-generate — Detection (Scenario D) | `generate_deck` has no heartbeat, so Temporal cannot distinguish a slow Claude call from a dead worker. It waits the full `start_to_close=5m`, then schedules attempt 2. On restart the workflow replays from history; `saga.add` is re-applied deterministically and no completed activity is re-run. |
| 5 | Deck.run() | Approve while revision running — Handler concurrency (Scenario E) | The `approve` signal sets `approved=True` and unblocks `wait_condition`, but `finally: wait_condition(all_handlers_finished)` holds the workflow open until the in-flight `submit_feedback` completes. The revised deck is never cut off half-way. Workflow COMPLETES with the revision applied. |
| 6 | Deck.run() | Timeout while revision running — Handler concurrency † | Same `finally` as case 5, on the timeout path. The update handler finishes (or fails and runs `restore_deck`), and *then* `run()`'s `delete_deck` wipes everything. Both sagas unwind, LIFO within each. |
| 7 | Deck.run() | Cancel — Foundation † (untested) | `asyncio.CancelledError` is caught by `run()`'s `except (Exception, asyncio.CancelledError)`, so `delete_deck` runs. Note `submit_feedback`'s `except Exception` does **not** catch `CancelledError`, so a revision in flight at cancel time will not run `restore_deck` — `delete_deck` cleans up regardless. |
| 8 | Deck.run() | Terminate — Foundation † | Terminate stops the workflow at the server without running any workflow code. No saga runs; deck, backup and any `.tmp` are left on disk. This is the one failure mode Temporal cannot help with. |
| 9 | submit_feedback() | Concurrent feedbacks — Concurrency (Scenario A) | Two updates arrive together. Both pass the validator, but `asyncio.Lock` serialises them: B waits while A runs, and `revision_status` reports `locked=true`. B's snapshot is taken *after* A finishes, so a rollback of B lands on A's deck, not the original. |
| 10 | submit_feedback() | Worker crash mid-revise — Detection + Idempotency (Scenario B) | `revise_deck` heartbeats every 2s with `heartbeat_timeout=30s`, so a dead worker is detected in ~30s (vs 5m for case 4). On retry the activity resets the deck from the snapshot before Claude edits, so the feedback is applied exactly once. `snapshot_deck` is not re-run on replay. |
| 11 | submit_feedback() | Validator rejection — Sequence of events (Scenario C) | `validate_feedback` rejects the update if `deck_ready` is False or the feedback is blank. The handler body never runs — no lock is taken, no activities are scheduled, and the rejected update leaves no events in history. |
| 12 | submit_feedback() | Non-retryable Claude error — Retryable vs terminal (Scenario D) | Same `Unauthorized` rule as case 2. Attempt 1 fails, retries are skipped, `restore_deck` copies the snapshot back over the deck. The update FAILS but the workflow stays alive, parked on the approval timer. |
| 13 | submit_feedback() | Retries exhausted — Saga (Scenario E) | `revise_deck` fails on all 3 attempts (each one resets from snapshot first). `saga.compensate()` runs `restore_deck`, so the deck returns to its pre-feedback state. The update FAILS; the workflow stays alive, and the next `submit_feedback` snapshots a clean baseline. |
| 14 | submit_feedback() | Snapshot fails — Saga safety † | `snapshot_deck` is fast file I/O but can still fail (disk, permissions). It is retried 3×. If exhausted, `saga.add(restore_deck)` was never reached, so `compensate()` is a no-op — correct, because the deck was never touched. Update FAILS, deck unchanged. |
| 15 | submit_feedback() | Feedback after completion — Lifecycle † | Once approved, the workflow is COMPLETED. A later `feedback.py --feedback` is rejected by the Temporal server ("workflow execution already completed"), not by the validator — there is no running workflow to validate against. |

### Happy Path 
This look complex for revising deck, but if you put it across banking environment e.g. transfer fund and booking tickets, this will justify the flow. Because you cannot tolerate failure and worst failure with corrupted state. The remaining use case will explains what each of the workflow will handle.

**Workflow Name**:
1. Deck.run()
2. submit_feedback()

app.py /                Deck.run()              submit_feedback()        Activity worker           Claude Agent SDK        Disk (agents/output/)
feedback.py             (workflow)              (update handler)
   |                        |                        |                        |                        |                        |
   |-- start workflow ----->|                        |                        |                        |                        |
   |   deck-workflow-xxxx   |                        |                        |                        |                        |
   |                        |-- saga.add(delete_deck)  [registered, not run]  |                        |                        |
   |                        |                        |                        |                        |                        |
   |                        |-- execute_activity(generate_deck) ------------->|                        |                        |
   |                        |   start_to_close=5m, no heartbeat               |-- read content.md ---------------------------->|
   |                        |                        |                        |-- query(prompt) ------>|                        |
   |                        |                        |                        |<-- ResultMessage(html)-|                        |
   |                        |                        |                        |-- write deck.tmp ----------------------------->| deck_<id>.html.tmp
   |                        |                        |                        |-- os.replace ---------------------------------->| deck_<id>.html
   |                        |<-- DeckOutput(200) ----------------------------|                        |                        |
   |                        |-- deck_ready = True    |                        |                        |                        |
   |                        |                        |                        |                        |                        |
   |                        |-- wait_condition(approved, timeout=3m)  ......  [TIMER STARTS — workflow parked]                 |
   |                        |                        |                        |                        |                        |
   |-- update: submit_feedback("add slide") -------->|                        |                        |                        |
   |                        |                        |-- validator: deck_ready? non-empty? ok          |                        |
   |                        |                        |-- acquire revision_in_progress_lock             |                        |
   |                        |                        |   (query revision_status -> locked=true)        |                        |
   |                        |                        |                        |                        |                        |
   |                        |                        |-- execute_activity(snapshot_deck) ------------->|                        |
   |                        |                        |                        |-- copy deck -> backup.tmp -> os.replace ------->| deck_<id>-backup.html
   |                        |                        |<-- SnapshotResult(created=True) ----------------|                        |
   |                        |                        |-- saga.add(restore_deck)  [registered, not run] |                        |
   |                        |                        |                        |                        |                        |
   |                        |                        |-- execute_activity(revise_deck) --------------->|                        |
   |                        |                        |   start_to_close=5m, heartbeat_timeout=30s      |-- reset deck from backup --------------------->| deck_<id>.html (= backup)
   |                        |                        |                        |                        |-- query(prompt, tools=Read/Edit/Write) ->|
   |                        |                        |                        |   heartbeat every 2s ->|   Claude edits file directly ----------------->| deck_<id>.html (revised)
   |                        |                        |                        |<-- ResultMessage ------|                        |
   |                        |                        |<-- result_text --------------------------------|                        |
   |                        |                        |-- release lock         |                        |                        |
   |<-- "Revised Deck: ..." ---------------------------|                        |                        |                        |
   |                        |                        |                        |                        |                        |
   |-- signal: approve ---->|                        |                        |                        |                        |
   |                        |-- approved = True      |                        |                        |                        |
   |                        |-- wait_condition unblocks  [TIMER CANCELLED]    |                        |                        |
   |                        |-- finally: wait_condition(all_handlers_finished)  [no-op, handler done]  |                        |
   |                        |-- return result.message  ("Deck generated successfully at ...")          |                        |
   |                        |   saga NOT compensated  |                        |                        |                        |
   |<-- workflow COMPLETED  |                        |                        |                        |                        |
   |                        |                        |                        |                        |                        | deck_<id>.html        (kept)
   |                        |                        |                        |                        |                        | deck_<id>-backup.html (kept)

### Workflow 1:Deck.run()
Possible failure scenarios:
Possible failure scenarios:
1. **The activity could fail | Durability** → *Scenario A (Case 1)*: `generate_deck` can fail from a network error or a Claude error. The retry policy allows 3 attempts (5s → 10s backoff). `generate_deck` is idempotent because it writes to `.tmp` then `os.replace` — a partial deck is never visible on disk, so every attempt starts clean.
2. **Terminal errors | Retryable vs non-retryable** → *Scenario C (Case 2)*: Not every failure deserves a retry. `Unauthorized` (Claude not logged in) is in `non_retryable_error_types` — attempts 2 and 3 are skipped and the saga runs immediately. Retrying a login failure would only waste ~35s.
3. **Human never responds | Timeout** → *Scenario B (Case 3)*: `wait_condition(approved, timeout=3m)` is a durable timer persisted in event history — the worker can restart mid-wait and the timer still fires. On expiry the workflow raises `ApprovalTimeout` and rolls back.
4. **Worker dies mid-activity | Detection (heartbeats)** → *Scenario D (Case 4)*: `generate_deck` has no heartbeat, so Temporal cannot tell a slow Claude call from a dead worker and waits the full `start_to_close=5m` before retrying. Compare with `revise_deck` (Workflow 2, Scenario B), which heartbeats every 2s and is detected in ~30s. On restart the workflow replays from history; `saga.add` is re-applied deterministically and no completed activity is re-run.
5. **A half-done transaction | Saga Pattern** → *Scenarios A, B, C (Cases 1, 2, 3)*: `delete_deck` is registered on the saga *before* `generate_deck` runs, so whatever fails — retries exhausted, terminal error, timeout — `saga.compensate()` removes the deck, backup, and any `.tmp` files. Compensations are safe to run even if the action never happened. This is the mechanism every failure path above ends in, not a separate trigger.
6. **Approval racing a revision | Handler concurrency** → *Scenario E (Case 5)*, timeout variant *Case 6 †*: If `approve` fires while `submit_feedback` is mid-revision, `wait_condition(all_handlers_finished)` blocks the workflow from completing until the update handler finishes — no revision is cut off half-way. The same `finally` applies when the *timer* fires mid-revision: the handler completes (or restores), then `delete_deck` wipes everything.
7. **Cancel vs Terminate | Foundation** → *Cases 7, 8 †* (untested): Cancel delivers `asyncio.CancelledError` into `run()`, which is caught and compensated — `delete_deck` runs. Terminate kills the workflow at the server without running any code — no saga, files left on disk.


**Scenario A — generate_deck retries exhausted**

Client                    Workflow (Deck.run)                    Activities                     Disk
  |                              |                                    |                            |
  |-- start workflow ----------> |                                    |                            |
  |                              |-- saga.add(delete_deck)            |                            |
  |                              |      [registered BEFORE generate]  |                            |
  |                              |                                    |                            |
  |                              |-- execute_activity(generate_deck) -|--> attempt 1               |
  |                              |      (retry_policy max_attempts=3) |    query(Claude)...        |
  |                              |      (no heartbeat: a dead worker  |    X ClaudeAgentFailed     | (no file — write is
  |                              |       is only noticed at 5m)       |                            |  tmp + os.replace)
  |                              |                                    |                            |
  |                              |   Temporal waits 5s, retries ----- |--> attempt 2               |
  |                              |                                    |    X ClaudeAgentFailed     |
  |                              |                                    |                            |
  |                              |   Temporal waits 10s, retries ---- |--> attempt 3               |
  |                              |                                    |    X ClaudeAgentFailed     |
  |                              |                                    |                            |
  |                              |<-- ActivityError (retries exhausted)                            |
  |                              |-- except: saga.compensate()        |                            |
  |                              |-- execute_activity(delete_deck, delete_all=True) -------------->|
  |                              |                                    |--> remove deck/backup/.tmp if present --> | (nothing left)
  |                              |<-- removed=False                   |                            |
  |                              |-- raise                            |                            |
  |<-- workflow FAILED ----------|                                    |                            |

  (Unauthorized: same flow, but attempt 1 X goes straight to saga.compensate() — no attempts 2/3)

**Scenario B — no approval within the timer**

Client                    Workflow (Deck.run)                    Activities                     Disk
  |                              |                                    |                            |
  |-- start workflow ----------> |                                    |                            |
  |                              |-- saga.add(delete_deck)            |                            |
  |                              |-- execute_activity(generate_deck) -|--> Claude -> tmp -> replace -> | deck.html
  |                              |<-- DeckOutput(200)                 |                            |
  |                              |-- deck_ready = True                |                            |
  |                              |-- wait_condition(approved, 3m)   [TIMER STARTS — durable]       |
  |                              |                                    |                            |
  |-- submit_feedback ---------> |   (update handler runs — see Workflow 2)                        | deck-backup.html
  |<-- "Revised Deck: ..." ------|                                    |                            | deck.html (revised)
  |                              |                                    |                            |
  |         ... no approve signal ...                                 |                            |
  |                              |                                    |                            |
  |                              |-- 3m elapsed: asyncio.TimeoutError |                            |
  |                              |-- raise ApplicationError(ApprovalTimeout, non_retryable)        |
  |                              |-- finally: wait_condition(all_handlers_finished)                |
  |                              |      [blocks here if a revision is still running]               |
  |                              |-- except: saga.compensate()        |                            |
  |                              |-- execute_activity(delete_deck, delete_all=True) -------------->|
  |                              |                                    |--> os.remove ------------->| deck.html        (deleted)
  |                              |                                    |                            | deck-backup.html (deleted)
  |                              |                                    |                            | *.tmp            (deleted)
  |                              |<-- removed=True                    |                            |
  |                              |-- raise                            |                            |
  |<-- workflow FAILED (ApprovalTimeout)  
  
**Scenario C — Non-retryable Claude error (Unauthorized)**

Client                    Workflow (Deck.run)                    Activities                     Disk
  |                              |                                    |                            |
  |-- start workflow ----------> |                                    |                            |
  |                              |-- saga.add(delete_deck)            |                            |
  |                              |                                    |                            |
  |                              |-- execute_activity(generate_deck) -|--> attempt 1               |
  |                              |      non_retryable_error_types=    |    query(Claude)           |
  |                              |        ["Unauthorized"]            |    ProcessError "Not logged in"
  |                              |                                    |    -> _as_temporal_error   |
  |                              |                                    |    X ApplicationError(     |
  |                              |                                    |        type="Unauthorized",|
  |                              |                                    |        non_retryable=True) |
  |                              |                                    |                            |
  |                              |<-- ActivityError (NO retries — attempts 2/3 skipped)            |
  |                              |-- except: saga.compensate()        |                            |
  |                              |-- execute_activity(delete_deck, delete_all=True) -------------->|
  |                              |                                    |--> nothing to remove ----->| (no file was written)
  |                              |<-- removed=False                   |                            |
  |                              |-- raise                            |                            |
  |<-- workflow FAILED (Unauthorized) ----------------------------------------------------------- | 

**Scenario D — Worker crash mid-generate: no heartbeat → detected only at start_to_close**

Client                    Workflow (Deck.run)                    Activities                     Disk
  |                              |                                    |                            |
  |-- start workflow ----------> |-- saga.add(delete_deck)            |                            |
  |                              |-- execute_activity(generate_deck) -|--> attempt 1               |
  |                              |   start_to_close=5m                |    query(Claude)...        | (nothing — file is written
  |                              |   NO heartbeat_timeout             |    ### WORKER KILLED ###   |  only after Claude returns)
  |                              |                                    |                            |
  |                              |   ... Temporal hears nothing. Without heartbeats it cannot tell |
  |                              |       a slow Claude call from a dead worker. Waits the FULL 5m. |
  |                              |<-- Temporal: start_to_close timeout, schedule retry             |
  |                              |                                    |                            |
  |                              |   ### WORKER RESTARTED — workflow replays; saga.add re-applied  |
  |                              |       deterministically, no activity re-run ###                 |
  |                              |   Temporal waits 5s, retries ----- |--> attempt 2               |
  |                              |                                    |    Claude -> tmp -> replace ->| deck.html
  |                              |<-- DeckOutput(200)                 |                            |
  |                              |-- deck_ready = True, wait_condition(approved, 3m) ...           |      

**Scenario E — approve arrives while a revision is running (Handler concurrency)**

Client                    Workflow (Deck.run)                    Update handler / Activities    Disk
  |                              |                                    |                            |
  |-- start workflow ----------> |-- saga.add(delete_deck)            |                            |
  |                              |-- generate_deck -------------------|--> Claude -> tmp -> replace ->| deck.html
  |                              |-- deck_ready = True                |                            |
  |                              |-- wait_condition(approved, 3m)   [TIMER STARTS]                 |
  |                              |                                    |                            |
  |-- submit_feedback("...") --> |                                    |-- validator ok, acquire lock
  |                              |                                    |-- snapshot_deck ---------->| deck-backup.html
  |                              |                                    |-- saga.add(restore_deck)   |
  |                              |                                    |-- revise_deck: Claude editing...  | deck.html (mid-edit)
  |                              |                                    |                            |
  |-- signal: approve ---------> |-- approved = True                  |   ...still editing...      |
  |                              |-- wait_condition unblocks  [TIMER CANCELLED]                    |
  |                              |-- finally: wait_condition(all_handlers_finished)                |
  |                              |      ### BLOCKS — handler still running ###                     |
  |                              |                                    |   ...still editing...      |
  |                              |                                    |<-- result_text            | deck.html (revised)
  |<-- "Revised Deck: ..." ------|                                    |-- release lock, handler done
  |                              |   [all_handlers_finished -> True]  |                            |
  |                              |-- return result.message            |                            |
  |                              |   saga NOT compensated             |                            |
  |<-- workflow COMPLETED -------|                                    |                            | deck.html        (revised, kept)
  |                              |                                    |                            | deck-backup.html (kept)

  The approve signal is accepted immediately, but the workflow refuses to complete until the
  in-flight update finishes. Without the all_handlers_finished wait, the workflow would return
  while Claude is still writing to deck.html — Temporal would log an "unfinished handler" warning
  and the deck's final state would be whatever the edit had reached when the worker stopped.
                 
### Workflow 2:submit_feedback()
Possible failure scenarios:
1. **Data Corruption | Concurrency** → *Scenario A (Case 9)*: Two `submit_feedback` updates arrive together and would both write to the same deck. Solution: `asyncio.Lock` serialises them — B waits while A runs, and `revision_status` shows `locked=true`.
2. **The activity could fail | Durability** → *Scenario B (Case 10)* and *Scenario E (Case 13)*: `revise_deck` is retried up to 3 attempts so it has the opportunity to complete at least once. At each attempt the deck could be left half-edited by the previous one.
    - Solution: every attempt must be idempotent, so `revise_deck` always resets the deck from the snapshot before Claude edits. Scenario B shows the retry *succeeding* (worker crash, heartbeat timeout, attempt 2 applies the feedback exactly once). Scenario E shows all 3 attempts *failing*.
3. **A half-done transaction is worse than nothing done | Saga Pattern** → *Scenario D (Case 12)* and *Scenario E (Case 13)*: Even after 3 attempts the activity may still fail (network, Claude). Rather than leave a corrupted deck, the update handler rolls back by running `restore_deck`, which copies the snapshot back over the deck. The workflow stays alive and the next feedback starts from a clean baseline.
4. **Sequence of events | Validator** → *Scenario C (Case 11)*: It makes no sense to revise a deck that hasn't been generated. `validate_feedback` rejects the update if `deck_ready` is False (or the feedback is blank) before the handler body runs — no lock, no activities, no history events.
5. **Terminal errors | Retryable vs non-retryable** → *Scenario D (Case 12)*: `Unauthorized` (Claude not logged in) is in `non_retryable_error_types`, so attempts 2 and 3 are skipped and the saga runs immediately. Same rule as Deck.run() Scenario C.


**Scenario A — Concurrency: two feedbacks at once (Lock)**

Client A / B              Workflow (update handlers)             Activities                     Disk
  |                              |                                    |                            |
  |-- A: submit_feedback("x") -> |-- A: validator ok                  |                            |
  |-- B: submit_feedback("y") -> |-- B: validator ok                  |                            |
  |                              |-- A: acquire lock  [got it]        |                            |
  |                              |-- B: acquire lock  [WAITS]         |                            |
  |                              |                                    |                            |
  |-- query revision_status ---> |<-- {"locked": true}                |                            |
  |                              |                                    |                            |
  |                              |-- A: snapshot_deck ----------------|--> copy ------------------>| deck-backup.html (= original)
  |                              |-- A: revise_deck ------------------|--> Claude edits ---------->| deck.html (A applied)
  |<-- A: "Revised Deck" --------|-- A: release lock                  |                            |
  |                              |                                    |                            |
  |                              |-- B: acquire lock  [got it]        |                            |
  |                              |-- B: snapshot_deck ----------------|--> copy ------------------>| deck-backup.html (= A's result)
  |                              |-- B: revise_deck ------------------|--> Claude edits ---------->| deck.html (A + B applied)
  |<-- B: "Revised Deck" --------|-- B: release lock                  |                            |
  |                              |                                    |                            |
  (B's snapshot is taken AFTER A finished — so a rollback of B lands on A's deck, not the original)

**Scenario B — Worker crash mid-revise: heartbeat timeout → retry → reset from snapshot (Idempotency)**

Client                    Workflow (update handler)              Activities                     Disk
  |                              |                                    |                            |
  |-- submit_feedback("...") --> |-- validator ok, acquire lock       |                            |
  |                              |-- snapshot_deck -------------------|--> copy ------------------>| deck-backup.html
  |                              |                                    |                            |
  |                              |-- revise_deck ---------------------|--> attempt 1               |
  |                              |   heartbeat_timeout=30s            |    reset deck from backup  |
  |                              |                                    |    heartbeat every 2s      |
  |                              |                                    |    Claude edits...         | deck.html (half-edited)
  |                              |                                    |    ### WORKER KILLED ###   |
  |                              |                                    |                            |
  |                              |   ... 30s with no heartbeat ...    |                            |
  |                              |<-- Temporal: heartbeat timeout, schedule retry                  |
  |                              |                                    |                            |
  |                              |   ### WORKER RESTARTED — workflow replays from history ###      |
  |                              |   (snapshot_deck NOT re-run; handler resumes at revise_deck)   |
  |                              |                                    |                            |
  |                              |   Temporal waits 5s, retries ----- |--> attempt 2               |
  |                              |                                    |    reset deck from backup  | deck.html (== backup, half-edit gone)
  |                              |                                    |    Claude edits...         | deck.html (feedback applied ONCE)
  |                              |<-- result_text --------------------|                            |
  |<-- "Revised Deck: ..." ------|-- release lock                     |                            |

**Scenario C — Validator rejection (no lock, no activities)**

  |-- submit_feedback("...") --> |-- validator: deck_ready == False   |
  |<-- REJECTED: "Deck not generated yet" (ValueError)               |
  (Also rejected: empty/whitespace feedback. The handler body never runs, so no lock is taken
   and no event is recorded for the failed update's activities.)

**Scenario D — Non-retryable Claude error (Unauthorized)**

  |-- submit_feedback("...") --> |-- validator ok, acquire lock       |
  |                              |-- snapshot_deck -------------------|--> copy ------------------>| deck-backup.html
  |                              |-- revise_deck ---------------------|--> attempt 1: "Not logged in" -> ApplicationError(Unauthorized, non_retryable)
  |                              |<-- ActivityError (NO retries)      |
  |                              |<-- ActivityError (retries exhausted)                            |
  |                              |-- except: saga.compensate()        |                            |
  |                              |-- execute_activity(restore_deck) --|--> copy backup -> tmp -> replace ->| deck.html (== backup)
  |                              |<-- RestoreResult(restored=True)    |                            |
  |                              |-- release lock, raise              |                            |
  |<-- update FAILED ------------|                                    |                            | deck.html (restored — attempt 3's half-edit gone)
  |                              |                                    |                            |
  (Workflow is still alive, parked on wait_condition(approved). Because restore_deck ran,
   the next submit_feedback snapshots the clean pre-feedback deck — a failed revision
   never poisons the next one's baseline.)  

**Scenario E — revise_deck retries exhausted → saga**

Client                    Workflow (update handler)              Activities                     Disk
  |                              |                                    |                            |
  |-- submit_feedback("...") --> |-- validator ok, acquire lock       |                            |
  |                              |-- snapshot_deck -------------------|--> copy ------------------>| deck-backup.html
  |                              |                                    |                            |
  |                              |-- revise_deck ---------------------|--> attempt 1               |
  |                              |      (retry_policy max_attempts=3) |    reset from backup       |
  |                              |                                    |    X ClaudeAgentFailed     | deck.html (half-edited)
  |                              |   Temporal waits 5s, retries ----- |--> attempt 2               |
  |                              |                                    |    reset from backup       | deck.html (== backup)
  |                              |                                    |    X ClaudeAgentFailed     | deck.html (half-edited)
  |                              |<-- ActivityError (retries exhausted)                            |
  |                              |-- except: saga.compensate()        |                            |
  |                              |-- execute_activity(restore_deck) --|--> copy backup -> tmp -> replace ->| deck.html (== backup)
  |                              |<-- RestoreResult(restored=True)    |                            |
  |                              |-- release lock, raise              |                            |
  |<-- update FAILED ------------|                                    |                            | deck.html (restored — attempt 3's half-edit gone)
  |                              |                                    |                            |
```sh
# Activate environment
python3.13 -m venv .venv
source .venv/bin/activate 

# Installation
pip install -r requirements.txt 

# Getting Started
temporal server start-dev
python worker.py

cd agents
python app.py
# app.py prints a unique Workflow ID (deck-workflow-<8 hex chars>) — pass it to the commands below
python feedback.py deck-workflow-96853fe5 --feedback "Add a new slide at first slide called 2 you and a picture of a flower"
python feedback.py deck-workflow-ab2ca2ba --approve
temporal workflow query --workflow-id deck-workflow-96382778 --type revision_status # show lock
```

### Other useful CLI command
```sh
# Show temporal workflow (use the ID printed by app.py)
export workflowname="deck-workflow-a1b2c3d4"
temporal workflow show --workflow-id $workflowname --detailed
```

## Tech Stack
- Claude Agent SDK : Use this instead of client sdk due to cost reason. You will need a claude code subscription to run this project
- Temporal: Will display (1) Durability, (2) Visibility, (3)Atomicity in activities Orchestration, (4) Faciliate Saga Pattern
- Code: Idempotency, Saga Pattern

## Use Case
**Happy Path**
1. Approve before Gen Deck Completed: Passed, Outcome: Deck Generated and Saved
2. Feedback cannot be started before Gen Deck is ready, Passed, Outcome: Error message 
3. Approve while Revise Deck is running, 
4. Approve while Gen Deck is running, 
**Saga**
5. Timeout (Gen Deck > Revise Deck > Timeout): Passed, outcome: All files deleted (Saga kicked in)
6. Gen Deck > Completed > Revise Deck > Logout from Claude: Failed > restore deck: Passed, Outcome: Restore Deck worked (Saga Kicked in)
7. Gen Deck > Completed > Click cancelled
8. Gen Deck > Completed > Click terminated
**Test Durability**
8. Gen Deck > shut down worker > complete Gen Deck > Revise Deck: Passed, Outcome: Worker Resumed and activity continued
**Concurrency**
9. Gen Deck > Completed > Send Feedback A and Feedback B at the same time > B waits on lock > A applied > B applied, Passed, Outcome: Revisions serialized by asyncio.Lock, revision_status query shows locked=true while A runs, 
**Idempotency**
10. Gen Deck > Completed > Revise Deck > kill worker after Claude has partially edited the deck > restart worker > retry attempt 2: Outcome: Deck reset from snapshot before retry, feedback applied exactly once (no duplicated edits)


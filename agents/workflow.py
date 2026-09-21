import asyncio
from temporalio import workflow
from datetime import timedelta
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():                                                    
    from models import DeckInput, SnapshotResult, DeckOutput, RestoreResult
    from saga import Saga

@workflow.defn
class Deck:
    def __init__(self):
        self.approved = False  # Initialize approval status
        self.revision_in_progress_lock = asyncio.Lock()
        self.deck_ready = False #status for deck existence

    @workflow.run
    async def run(self, input: DeckInput) -> str:
        # Add Activity Retry Policy
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=5),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(minutes=1),
            maximum_attempts=3,
            non_retryable_error_types=["Unauthorized"]
        )
        saga = Saga()
        try:
            # Step 1: Generate the initial deck
            wf_id = workflow.info().workflow_id
            saga.add(lambda: workflow.execute_activity(
                                "delete_deck",
                                DeckInput(content=input.content, workflow_id=wf_id, delete_all=True),
                                start_to_close_timeout=timedelta(seconds=30),
                                retry_policy=retry_policy
                ))
            workflow.logger.info("Step 1: Starting deck generation activity.")

            result = await workflow.execute_activity(
                "generate_deck",
                DeckInput(content=input.content, workflow_id=workflow.info().workflow_id),
                result_type=DeckOutput,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy
            )
            self.deck_ready = result.status == 200
            # Step 2: Wait for approval
            if not self.deck_ready:
                raise ApplicationError(f"Deck Creation failed: {result.message}", type="DeckGenerationFailed", non_retryable=True) 
            else:
                workflow.logger.info("Step 3: Waiting for deck approval.")
                try:
                    await workflow.wait_condition(lambda: self.approved, timeout=timedelta(minutes=3))
                except asyncio.TimeoutError:
                    raise ApplicationError("No approval within 1h", type="ApprovalTimeout", non_retryable=True)
                finally:
                    await workflow.wait_condition(workflow.all_handlers_finished)

            return result.message
        except (Exception, asyncio.CancelledError):
            await saga.compensate()
            raise

    @workflow.update
    async def submit_feedback(self, feedback: str):
        workflow.logger.info("Step 2: Submitting feedback for deck revision.")
        saga = Saga()
        wf_id = workflow.info().workflow_id
        async with self.revision_in_progress_lock:
            backup = SnapshotResult(created=False)
            retry_policy = RetryPolicy(
                        initial_interval=timedelta(seconds=5),
                        backoff_coefficient=2.0,
                        maximum_interval=timedelta(minutes=1),
                        maximum_attempts=3,
                        non_retryable_error_types=["Unauthorized"]
                    )
            try:
                # Step 1: Create backup for restore if needed
                backup = await workflow.execute_activity(
                    "snapshot_deck",
                    DeckInput(content=feedback, workflow_id=wf_id),
                    result_type=SnapshotResult,
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=retry_policy
                )
                workflow.logger.info(f"Deck snapshot created at {backup}")
                if backup.created:
                    saga.add(lambda: workflow.execute_activity(
                        "restore_deck",
                        DeckInput(workflow_id=wf_id),
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=retry_policy
                    ))
                #Step 2: Revise Deck if Backup is done. 
                revised_result = await workflow.execute_activity(
                    "revise_deck",
                    DeckInput(content=feedback, workflow_id=wf_id),
                    start_to_close_timeout=timedelta(minutes=5),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=retry_policy
                )
                workflow.logger.info(f"Revised Deck: {revised_result}")
                return f"Revised Deck: {revised_result}"
            except Exception:
                # If encounter exception rollback the revision
                await saga.compensate()
                raise
    
    @workflow.query
    def revision_status(self) -> dict:
        return {
            "locked": self.revision_in_progress_lock.locked()
            # "holder": self.current_revision,
            # "step": self.current_step,
        }

    @submit_feedback.validator
    def validate_feedback(self, feedback: str) -> None:
        if not self.deck_ready:
            raise ValueError("Deck not generated yet; send feedback after generation completes")
        if not feedback.strip():
            raise ValueError("Feedback cannot be empty")

    @workflow.signal
    async def approve(self):
        # Step 4: Approve the deck
        self.approved = True
        return f"Deck approved."
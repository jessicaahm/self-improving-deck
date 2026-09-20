from temporalio import workflow
from datetime import timedelta
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():                                                    
    from models import DeckInput 

@workflow.defn
class Deck:
    def __init__(self):
        self.approved = False  # Initialize approval status
        self.revision_in_progress = False  # Initialize revision work-in-progress

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
        # Step 1: Generate the initial deck
        workflow.logger.info("Step 1: Starting deck generation activity.")
        result = await workflow.execute_activity(
            "generate_deck",
            DeckInput(content=input.content, workflow_id=workflow.info().workflow_id),
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=retry_policy
        )
        # Step 3: Wait for approval
        workflow.logger.info("Step 3: Waiting for deck approval.")
        try:
            await workflow.wait_condition(lambda: self.approved, timeout=timedelta(hours=1))
        except workflow.TimeoutError:
            # Handle timeout (e.g., log, send notification, etc.)
            return "Deck generation timed out due to lack of approval."

    @workflow.update
    async def submit_feedback(self, feedback: str):
        workflow.logger.info("Step 2: Submitting feedback for deck revision.")
        await workflow.wait_condition(lambda: not self.revision_in_progress)
        self.revision_in_progress = True
        retry_policy = RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(minutes=1),
                    maximum_attempts=3,
                    non_retryable_error_types=["Unauthorized"]

                )
        try:
            revised_result = await workflow.execute_activity(
                "revise_deck",
                DeckInput(content=feedback, workflow_id=workflow.info().workflow_id),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy
            )
            workflow.logger.info(f"Revised Deck: {revised_result}")
            return f"Revised Deck: {revised_result}"
        finally:
            self.revision_in_progress = False  # Reset the revision work-in-progress flag

    @workflow.signal
    async def approve(self):
        # Step 4: Approve the deck
        self.approved = True
        return f"Deck approved."
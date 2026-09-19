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
        )
        # Step 1: Generate the initial deck
        result = await workflow.execute_activity(
            "generate_deck",
            DeckInput(content=input.content, workflow_id=workflow.info().workflow_id),
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=retry_policy
        )
        # Step 2: Wait for approval
        try:
            await workflow.wait_condition(lambda: self.approved, timeout=timedelta(hours=1))
        except workflow.TimeoutError:
            # Handle timeout (e.g., log, send notification, etc.)
            return "Deck generation timed out due to lack of approval."

    @workflow.update
    async def submit_feedback(self, feedback: str):
        await workflow.wait_condition(lambda: not self.revision_in_progress)
        self.revision_in_progress = True
        retry_policy = RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(minutes=1),
                    maximum_attempts=3,
        )
            # Step 3: Revise the deck based on feedback
        try:
            revised_result = await workflow.execute_activity(
                "revise_deck",
                DeckInput(content=feedback, workflow_id=workflow.info().workflow_id),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy
            )
            return f"Revised Deck: {revised_result}"
        finally:
            self.revision_in_progress = False  # Reset the revision work-in-progress flag

    @workflow.signal
    async def approve(self):
        # Step 4: Approve the deck
        self.approved = True
        return f"Deck approved."